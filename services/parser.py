"""Spreadsheet parsing and column auto-detection."""

from __future__ import annotations

import io
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pandas as pd

from config import UPLOADS_DIR
from models import EventData


# ---------------------------------------------------------------------------
# Known column name patterns for auto-detection
# ---------------------------------------------------------------------------

_COLUMN_PATTERNS: Dict[str, List[str]] = {
    "event_name": [
        r"event[\s_-]*name", r"title", r"summary", r"game", r"match",
        r"opponent", r"event", r"activity", r"description",
    ],
    "date": [
        r"^date$", r"game[\s_-]*date", r"event[\s_-]*date", r"match[\s_-]*date",
        r"day", r"start[\s_-]*date",
    ],
    "start_time": [
        r"start[\s_-]*time", r"^time$", r"game[\s_-]*time", r"begin",
        r"kickoff", r"first[\s_-]*pitch",
    ],
    "end_time": [
        r"end[\s_-]*time", r"finish", r"stop[\s_-]*time",
    ],
    "location": [
        r"location", r"venue", r"field", r"stadium", r"facility",
        r"site", r"place", r"address", r"gym", r"court", r"park",
    ],
    "description": [
        r"description", r"notes", r"details", r"comments", r"memo", r"info",
    ],
}


def auto_detect_columns(columns: List[str]) -> Dict[str, Optional[str]]:
    """Return a mapping of event field -> spreadsheet column name.

    Uses fuzzy regex matching against known patterns commonly found in sports
    schedule exports from GotSport, TeamSideline, RankOne, Mojo, etc.
    """
    mapping: Dict[str, Optional[str]] = {}
    used: set = set()

    for field, patterns in _COLUMN_PATTERNS.items():
        for col in columns:
            if col in used:
                continue
            col_lower = col.strip().lower()
            for pat in patterns:
                if re.search(pat, col_lower):
                    mapping[field] = col
                    used.add(col)
                    break
            if field in mapping:
                break

    # Ensure all fields present (None if not detected)
    for field in _COLUMN_PATTERNS:
        mapping.setdefault(field, None)

    return mapping


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_spreadsheet(file_path: Path, source_type: str) -> pd.DataFrame:
    """Read an Excel or CSV file into a DataFrame."""
    if source_type in ("excel_upload", "excel_url"):
        df = pd.read_excel(file_path, engine="openpyxl")
    else:
        # Try common encodings
        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(file_path, encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            df = pd.read_csv(file_path, encoding="utf-8", errors="replace")

    # Strip whitespace from column names
    df.columns = [str(c).strip() for c in df.columns]
    return df


def read_spreadsheet_from_bytes(data: bytes, source_type: str, filename: str = "") -> pd.DataFrame:
    """Read spreadsheet from raw bytes (for preview before saving)."""
    buf = io.BytesIO(data)
    if source_type in ("excel_upload", "excel_url"):
        df = pd.read_excel(buf, engine="openpyxl")
    else:
        text = data.decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(text))
    df.columns = [str(c).strip() for c in df.columns]
    return df


# ---------------------------------------------------------------------------
# Remote download
# ---------------------------------------------------------------------------

def download_remote_source(url: str, source_type: str, slug: str) -> Path:
    """Download a remote Excel/CSV file and store it in uploads dir."""
    ext = ".xlsx" if source_type == "excel_url" else ".csv"
    dest = UPLOADS_DIR / f"{slug}{ext}"

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        resp = client.get(url)
        resp.raise_for_status()

    dest.write_bytes(resp.content)
    return dest


# ---------------------------------------------------------------------------
# Date / time parsing helpers
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%y",
    "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d",
]

_TIME_FORMATS = [
    "%I:%M %p", "%I:%M%p", "%H:%M", "%I:%M:%S %p", "%H:%M:%S",
    "%I %p", "%I%p",
]


def _parse_date(value: Any) -> Optional[str]:
    """Try to parse a date value into YYYY-MM-DD."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    # Already a date/datetime object (pandas Timestamp)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")

    s = str(value).strip()
    if not s:
        return None

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Last resort: pandas to_datetime
    try:
        return pd.to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return None


def _parse_time(value: Any) -> Optional[str]:
    """Try to parse a time value into HH:MM (24h)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    # pandas Timestamp
    if isinstance(value, (datetime, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%H:%M")

    s = str(value).strip()
    if not s:
        return None

    # Strip trailing timezone abbreviations (e.g. "11:00 CST", "6:30 PM EDT")
    s = re.sub(r"\s+[A-Z]{2,5}$", "", s)

    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# DataFrame → EventData list
# ---------------------------------------------------------------------------

def dataframe_to_events(
    df: pd.DataFrame,
    column_mapping: Dict[str, Optional[str]],
) -> List[EventData]:
    """Convert a DataFrame to a list of EventData using the column mapping."""
    events: List[EventData] = []

    col_event = column_mapping.get("event_name")
    col_date = column_mapping.get("date")
    col_start = column_mapping.get("start_time")
    col_end = column_mapping.get("end_time")
    col_loc = column_mapping.get("location")
    col_desc = column_mapping.get("description")

    if not col_date:
        return events

    for _, row in df.iterrows():
        parsed_date = _parse_date(row.get(col_date) if col_date else None)
        if not parsed_date:
            continue  # skip rows without a valid date

        event_name = str(row.get(col_event, "Event")).strip() if col_event and pd.notna(row.get(col_event)) else "Event"
        start_time = _parse_time(row.get(col_start)) if col_start else None
        end_time = _parse_time(row.get(col_end)) if col_end else None
        location = str(row.get(col_loc, "")).strip() if col_loc and pd.notna(row.get(col_loc)) else None
        description = str(row.get(col_desc, "")).strip() if col_desc and pd.notna(row.get(col_desc)) else None

        all_day = start_time is None

        events.append(EventData(
            event_name=event_name,
            date=parsed_date,
            start_time=start_time,
            end_time=end_time,
            location=location or None,
            description=description or None,
            all_day=all_day,
        ))

    return events
