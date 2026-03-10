"""Spreadsheet parsing and column auto-detection."""

from __future__ import annotations

import io
import os
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
        r"event[\s_-]*name", r"title", r"summary", r"game",
        r"opponent", r"event", r"activity",
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
    "home_team": [
        r"home[\s_-]*team", r"^home$",
    ],
    "away_team": [
        r"away[\s_-]*team", r"^away$", r"visitor", r"visiting[\s_-]*team",
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
# Home/Away → event name helpers
# ---------------------------------------------------------------------------

def _find_common_prefix(names: List[str]) -> str:
    """Find the longest common prefix among team names (word-boundary aligned)."""
    if not names:
        return ""
    prefix = os.path.commonprefix(names)
    # Trim to last complete word/space boundary
    last_space = prefix.rfind(" ")
    if last_space > 0:
        return prefix[:last_space + 1]
    return ""


def _shorten_team(name: str, prefix: str) -> str:
    """Strip the common org prefix to get a short team name."""
    if prefix and name.startswith(prefix):
        short = name[len(prefix):].strip()
        if short:
            return short
    return name


def _detect_my_team(df: pd.DataFrame, col_home: str, col_away: str) -> Optional[str]:
    """Detect the user's team — the one that appears in every row.

    In a team schedule export, the user's team appears in either
    Home or Away for every single match.
    """
    from collections import Counter

    all_teams: List[str] = []
    for _, row in df.iterrows():
        h = str(row.get(col_home, "")).strip() if pd.notna(row.get(col_home)) else ""
        a = str(row.get(col_away, "")).strip() if pd.notna(row.get(col_away)) else ""
        if h:
            all_teams.append(h)
        if a:
            all_teams.append(a)

    if not all_teams:
        return None

    # The user's team should appear in every row (once per row)
    counter = Counter(all_teams)
    num_rows = len(df.dropna(subset=[col_home, col_away], how="all"))
    if num_rows == 0:
        return None

    # Team appearing the most is likely the user's team
    most_common = counter.most_common(1)[0]
    return most_common[0] if most_common[1] >= num_rows * 0.8 else None


def _build_event_name(
    row: Any,
    col_home: str,
    col_away: str,
    my_team: Optional[str],
    prefix: str,
) -> str:
    """Build 'vs <opponent>' or '@ <opponent>' event name."""
    home = str(row.get(col_home, "")).strip() if pd.notna(row.get(col_home)) else ""
    away = str(row.get(col_away, "")).strip() if pd.notna(row.get(col_away)) else ""

    if my_team:
        if home == my_team:
            opponent = _shorten_team(away, prefix) if away else "TBD"
            return f"vs {opponent}"
        elif away == my_team:
            opponent = _shorten_team(home, prefix) if home else "TBD"
            return f"@ {opponent}"

    # Fallback: no team detected — show "Home vs Away" shortened
    h_short = _shorten_team(home, prefix) if home else "TBD"
    a_short = _shorten_team(away, prefix) if away else "TBD"
    return f"{h_short} vs {a_short}"


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
    col_home = column_mapping.get("home_team")
    col_away = column_mapping.get("away_team")

    if not col_date:
        return events

    # Pre-compute home/away naming context if both columns are mapped
    use_home_away = bool(col_home and col_away
                         and col_home in df.columns
                         and col_away in df.columns)
    my_team = None  # type: Optional[str]
    prefix = ""
    if use_home_away:
        assert col_home is not None and col_away is not None
        my_team = _detect_my_team(df, col_home, col_away)
        # Build a common prefix from all team names for shortening
        all_names = set()  # type: set
        for _, r in df.iterrows():
            h = str(r.get(col_home, "")).strip() if pd.notna(r.get(col_home)) else ""
            a = str(r.get(col_away, "")).strip() if pd.notna(r.get(col_away)) else ""
            if h:
                all_names.add(h)
            if a:
                all_names.add(a)
        if len(all_names) >= 2:
            prefix = _find_common_prefix(sorted(all_names))

    for _, row in df.iterrows():
        parsed_date = _parse_date(row.get(col_date) if col_date else None)
        if not parsed_date:
            continue  # skip rows without a valid date

        # Build event name: prefer home/away logic, fall back to mapped column
        if use_home_away:
            assert col_home is not None and col_away is not None
            event_name = _build_event_name(row, col_home, col_away, my_team, prefix)
        elif col_event and pd.notna(row.get(col_event)):
            event_name = str(row.get(col_event)).strip()
        else:
            event_name = "Event"

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
