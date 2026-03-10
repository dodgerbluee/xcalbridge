"""SQLite database setup and helpers."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Optional

from config import DB_PATH
from models import Source, SourceCreate, SourceUpdate

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    source_url TEXT,
    upload_filename TEXT,
    column_mapping TEXT NOT NULL DEFAULT '{}',
    last_sync TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Default settings — inserted on first run if not present
_DEFAULT_SETTINGS: Dict[str, str] = {
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "sync_interval_hours": "3",
    "default_event_duration_minutes": "90",
}


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Initialize the database schema."""
    with _get_conn() as conn:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_SETTINGS_TABLE)
        # Seed default settings (only inserts if key doesn't already exist)
        for key, value in _DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def _row_to_source(row: sqlite3.Row) -> Source:
    d = dict(row)
    d["column_mapping"] = json.loads(d["column_mapping"]) if d["column_mapping"] else {}
    return Source(**d)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_sources() -> list:
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM sources ORDER BY created_at DESC").fetchall()
    return [_row_to_source(r) for r in rows]


def get_source(source_id: int) -> Optional[Source]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return _row_to_source(row) if row else None


def get_source_by_slug(slug: str) -> Optional[Source]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone()
    return _row_to_source(row) if row else None


def create_source(data: SourceCreate, slug: str, upload_filename: Optional[str] = None) -> Source:
    now = datetime.now(timezone.utc).isoformat()
    mapping_json = json.dumps(data.column_mapping) if data.column_mapping else "{}"
    with _get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO sources (name, slug, source_type, source_url, upload_filename,
               column_mapping, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (data.name, slug, data.source_type, data.source_url, upload_filename,
             mapping_json, now, now),
        )
        source_id = cur.lastrowid
    return get_source(source_id)  # type: ignore[return-value]


def update_source(source_id: int, data: SourceUpdate, upload_filename: Optional[str] = None) -> Optional[Source]:
    existing = get_source(source_id)
    if not existing:
        return None

    now = datetime.now(timezone.utc).isoformat()
    name = data.name if data.name is not None else existing.name
    source_type = data.source_type if data.source_type is not None else existing.source_type
    source_url = data.source_url if data.source_url is not None else existing.source_url
    uf = upload_filename if upload_filename is not None else existing.upload_filename

    if data.column_mapping is not None:
        mapping_json = json.dumps(data.column_mapping)
    else:
        mapping_json = json.dumps(existing.column_mapping)

    # Regenerate slug if name changed
    from services.sync import slugify
    slug = slugify(name)

    with _get_conn() as conn:
        conn.execute(
            """UPDATE sources SET name=?, slug=?, source_type=?, source_url=?,
               upload_filename=?, column_mapping=?, updated_at=?
               WHERE id=?""",
            (name, slug, source_type, source_url, uf, mapping_json, now, source_id),
        )
    return get_source(source_id)


def delete_source(source_id: int) -> bool:
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return cur.rowcount > 0


def update_source_status(
    source_id: int,
    status: str,
    error_message: Optional[str] = None,
    last_sync: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            """UPDATE sources SET status=?, error_message=?, last_sync=COALESCE(?, last_sync),
               updated_at=? WHERE id=?""",
            (status, error_message, last_sync, now, source_id),
        )


def update_column_mapping(source_id: int, mapping: dict) -> None:
    """Persist a column mapping (e.g. from auto-detection) back to the DB."""
    now = datetime.now(timezone.utc).isoformat()
    mapping_json = json.dumps(mapping)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE sources SET column_mapping=?, updated_at=? WHERE id=?",
            (mapping_json, now, source_id),
        )


# ---------------------------------------------------------------------------
# Settings CRUD
# ---------------------------------------------------------------------------

def get_all_settings() -> Dict[str, str]:
    """Return all settings as a dict."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def get_setting(key: str) -> Optional[str]:
    """Return a single setting value, or None if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else _DEFAULT_SETTINGS.get(key)


def update_settings(settings: Dict[str, str]) -> None:
    """Upsert multiple settings at once."""
    with _get_conn() as conn:
        for key, value in settings.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
