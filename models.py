"""Pydantic models for API requests/responses and internal data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

class ColumnMapping(BaseModel):
    """Maps spreadsheet columns to event fields."""
    event_name: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    home_team: Optional[str] = None
    away_team: Optional[str] = None


# ---------------------------------------------------------------------------
# Source CRUD models
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str
    source_type: str  # excel_upload, excel_url, csv_upload, csv_url
    source_url: Optional[str] = None
    column_mapping: Dict[str, Optional[str]] = Field(default_factory=dict)


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    column_mapping: Optional[Dict[str, Optional[str]]] = None


class Source(BaseModel):
    id: int
    name: str
    slug: str
    source_type: str
    source_url: Optional[str] = None
    upload_filename: Optional[str] = None
    column_mapping: Dict[str, Optional[str]] = Field(default_factory=dict)
    last_sync: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    created_at: str
    updated_at: str

    @property
    def feed_url(self) -> str:
        return f"/feeds/{self.slug}.ics"

    @property
    def source_type_display(self) -> str:
        return {
            "excel_upload": "Excel Upload",
            "excel_url": "Excel URL",
            "csv_upload": "CSV Upload",
            "csv_url": "CSV URL",
        }.get(self.source_type, self.source_type)

    @property
    def status_badge(self) -> str:
        return {
            "pending": "secondary",
            "syncing": "warning",
            "synced": "success",
            "error": "danger",
        }.get(self.status, "secondary")


# ---------------------------------------------------------------------------
# Event data (internal, used between parser and ICS generator)
# ---------------------------------------------------------------------------

class EventData(BaseModel):
    """A single parsed calendar event."""
    event_name: str
    date: str  # ISO date string YYYY-MM-DD
    start_time: Optional[str] = None  # HH:MM
    end_time: Optional[str] = None  # HH:MM
    location: Optional[str] = None
    description: Optional[str] = None
    all_day: bool = False


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class AppSettings(BaseModel):
    """Application settings (persisted as key-value pairs in DB)."""
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    sync_interval_hours: int = 3
    default_event_duration_minutes: int = 90
