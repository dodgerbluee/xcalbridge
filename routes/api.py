"""REST API routes for source CRUD and sync."""

from __future__ import annotations

import json
import logging
import shutil
from threading import Thread
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse

from config import UPLOADS_DIR
from database import (
    create_source,
    delete_source,
    get_source,
    list_sources,
    update_source,
)
from models import SourceCreate, SourceUpdate
from services.sync import delete_source_files, slugify, sync_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# List sources
# ---------------------------------------------------------------------------

@router.get("/sources")
def api_list_sources() -> List[Dict[str, Any]]:
    sources = list_sources()
    return [
        {
            **s.model_dump(),
            "feed_url": s.feed_url,
            "source_type_display": s.source_type_display,
        }
        for s in sources
    ]


# ---------------------------------------------------------------------------
# Create source
# ---------------------------------------------------------------------------

@router.post("/sources")
async def api_create_source(
    name: str = Form(...),
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    column_mapping: str = Form("{}"),
    file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    slug = slugify(name)

    # Handle file upload
    upload_filename: Optional[str] = None
    if source_type in ("excel_upload", "csv_upload"):
        if not file or not file.filename:
            raise HTTPException(400, "File is required for upload source types")
        ext = ".xlsx" if source_type == "excel_upload" else ".csv"
        upload_filename = f"{slug}{ext}"
        dest = UPLOADS_DIR / upload_filename
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)

    # Parse column mapping JSON
    try:
        mapping = json.loads(column_mapping) if column_mapping else {}
    except json.JSONDecodeError:
        mapping = {}

    data = SourceCreate(
        name=name,
        source_type=source_type,
        source_url=source_url if source_url else None,
        column_mapping=mapping,
    )

    source = create_source(data, slug, upload_filename)
    if not source:
        raise HTTPException(500, "Failed to create source")

    # Trigger initial sync in background
    Thread(target=sync_source, args=(source,), daemon=True).start()

    return {
        **source.model_dump(),
        "feed_url": source.feed_url,
        "source_type_display": source.source_type_display,
    }


# ---------------------------------------------------------------------------
# Update source
# ---------------------------------------------------------------------------

@router.put("/sources/{source_id}")
async def api_update_source(
    source_id: int,
    name: Optional[str] = Form(None),
    source_type: Optional[str] = Form(None),
    source_url: Optional[str] = Form(None),
    column_mapping: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    existing = get_source(source_id)
    if not existing:
        raise HTTPException(404, "Source not found")

    # Handle file upload if provided
    upload_filename: Optional[str] = None
    effective_type = source_type or existing.source_type
    if file and file.filename:
        new_slug = slugify(name or existing.name)
        ext = ".xlsx" if effective_type in ("excel_upload", "excel_url") else ".csv"
        upload_filename = f"{new_slug}{ext}"
        dest = UPLOADS_DIR / upload_filename
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)

    # Parse column mapping
    mapping: Optional[Dict[str, Optional[str]]] = None
    if column_mapping:
        try:
            mapping = json.loads(column_mapping)
        except json.JSONDecodeError:
            mapping = None

    data = SourceUpdate(
        name=name,
        source_type=source_type,
        source_url=source_url,
        column_mapping=mapping,
    )

    source = update_source(source_id, data, upload_filename)
    if not source:
        raise HTTPException(500, "Failed to update source")

    return {
        **source.model_dump(),
        "feed_url": source.feed_url,
        "source_type_display": source.source_type_display,
    }


# ---------------------------------------------------------------------------
# Delete source
# ---------------------------------------------------------------------------

@router.delete("/sources/{source_id}")
def api_delete_source(source_id: int) -> Dict[str, str]:
    source = get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    delete_source_files(source)
    delete_source(source_id)
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Force sync
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/sync")
def api_sync_source(source_id: int) -> Dict[str, str]:
    source = get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    # Run sync in background thread
    Thread(target=sync_source, args=(source,), daemon=True).start()
    return {"status": "sync_started"}


# ---------------------------------------------------------------------------
# Test Ollama connection
# ---------------------------------------------------------------------------

@router.post("/test-ollama")
async def api_test_ollama(body: Dict[str, Any]) -> Dict[str, Any]:
    from services.ai import test_ollama_connection
    url = body.get("url", "http://localhost:11434")
    return await test_ollama_connection(url)


# ---------------------------------------------------------------------------
# AI column mapping suggestion
# ---------------------------------------------------------------------------

@router.post("/ai-suggest")
async def api_ai_suggest(
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """Send spreadsheet columns + sample rows to Ollama for mapping suggestion."""
    from services.ai import suggest_column_mapping
    from services.parser import (
        download_remote_source,
        read_spreadsheet,
        read_spreadsheet_from_bytes,
    )

    try:
        # Parse the spreadsheet to get columns and sample data
        if source_type in ("excel_upload", "csv_upload") and file and file.filename:
            data = await file.read()
            df = read_spreadsheet_from_bytes(data, source_type, file.filename)
        elif source_type in ("excel_url", "csv_url") and source_url:
            file_path = download_remote_source(source_url, source_type, "_ai_preview")
            df = read_spreadsheet(file_path, source_type)
            file_path.unlink(missing_ok=True)
        else:
            return {"error": "No file or URL provided", "mapping": {}}

        columns = list(df.columns)
        # Get first 3 rows as sample data
        sample_rows = []
        for _, row in df.head(3).iterrows():
            sample_rows.append(
                {col: str(val) if not (isinstance(val, float) and val != val) else ""
                 for col, val in row.items()}
            )

        mapping = await suggest_column_mapping(columns, sample_rows)
        return {"mapping": mapping, "columns": columns, "error": None}

    except Exception as exc:
        logger.exception("AI suggest failed")
        return {"error": str(exc), "mapping": {}}
