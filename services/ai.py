"""AI-powered column mapping suggestions via Ollama."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from database import get_setting

logger = logging.getLogger(__name__)

# The fields we want the AI to map
_TARGET_FIELDS = [
    "event_name",
    "date",
    "start_time",
    "end_time",
    "location",
    "description",
    "home_team",
    "away_team",
]

_SYSTEM_PROMPT = """You are a data mapping assistant. You will be given:
1. A list of spreadsheet column names
2. A few sample rows of data

Your job is to map the column names to calendar event fields. Return a JSON object
where keys are the target field names and values are the matching spreadsheet column
names (or null if no match).

Target fields:
- event_name: The name/title of the event (e.g. game name, match description)
- date: The date of the event
- start_time: When the event starts
- end_time: When the event ends
- location: Where the event takes place (venue, field, stadium, address)
- description: Additional details or notes
- home_team: The home team name (for sports schedules)
- away_team: The away/visiting team name (for sports schedules)

Rules:
- Only use column names that actually exist in the provided list
- If a column clearly doesn't match any target field, don't force a mapping
- For sports schedules with Home Team and Away Team columns, map those instead of event_name
- Columns like "Match #", "Division", "Status", "Results" should NOT be mapped to event_name
- Return ONLY the JSON object, no other text or markdown formatting
"""


def _build_user_prompt(columns: List[str], sample_rows: List[Dict[str, Any]]) -> str:
    """Build the user prompt with column names and sample data."""
    parts = [
        "Spreadsheet columns:",
        json.dumps(columns),
        "",
        "Sample rows (first 3):",
    ]
    for i, row in enumerate(sample_rows[:3], 1):
        parts.append(f"Row {i}: {json.dumps(row, default=str)}")

    parts.append("")
    parts.append(
        "Map these columns to the target fields. Return only a JSON object."
    )
    return "\n".join(parts)


def _get_ollama_config() -> tuple:
    """Return (url, model) from settings."""
    url = get_setting("ollama_url") or "http://localhost:11434"
    model = get_setting("ollama_model") or "llama3.2"
    return url.rstrip("/"), model


async def list_ollama_models(url: str) -> List[str]:
    """Fetch available models from an Ollama instance via GET /api/tags."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            data = resp.json()

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            # Strip ":latest" suffix for cleanliness
            if name.endswith(":latest"):
                name = name[:-7]
            if name:
                models.append(name)
        return sorted(models)
    except Exception as exc:
        logger.warning("Could not list Ollama models: %s", exc)
        return []


async def test_ollama_connection(url: str) -> Dict[str, Any]:
    """Test connectivity to an Ollama instance and discover available models."""
    clean_url = url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(clean_url)
            resp.raise_for_status()
    except httpx.ConnectError:
        return {"ok": False, "error": "Connection refused — is Ollama running?"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Connection timed out"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    # Connection succeeded — discover models
    models = await list_ollama_models(clean_url)
    return {"ok": True, "models": models}


async def suggest_column_mapping(
    columns: List[str],
    sample_rows: List[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    """Ask Ollama to suggest a column mapping.

    Returns a dict mapping target field names to spreadsheet column names.
    """
    url, model = _get_ollama_config()
    user_prompt = _build_user_prompt(columns, sample_rows)

    payload = {
        "model": model,
        "prompt": user_prompt,
        "system": _SYSTEM_PROMPT,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
        },
    }

    logger.info("Asking Ollama (%s, model=%s) for column mapping", url, model)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(f"{url}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw_response = data.get("response", "")
    logger.debug("Ollama raw response: %s", raw_response)

    # Parse the JSON from the response
    try:
        mapping = json.loads(raw_response)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        import re
        match = re.search(r"\{[^}]+\}", raw_response, re.DOTALL)
        if match:
            mapping = json.loads(match.group())
        else:
            logger.error("Could not parse Ollama response as JSON: %s", raw_response)
            return {field: None for field in _TARGET_FIELDS}

    # Validate: only keep values that are actual column names
    validated: Dict[str, Optional[str]] = {}
    for field in _TARGET_FIELDS:
        val = mapping.get(field)
        if val and val in columns:
            validated[field] = val
        else:
            validated[field] = None

    logger.info("AI suggested mapping: %s", validated)
    return validated
