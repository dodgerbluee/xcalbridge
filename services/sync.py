"""Sync engine — orchestrates download → parse → ICS generation."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from config import FEEDS_DIR, UPLOADS_DIR
from models import Source

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """Convert a source name into a URL-safe slug."""
    # Normalize unicode
    s = unicodedata.normalize("NFKD", name)
    s = s.encode("ascii", "ignore").decode("ascii")
    # Lowercase, replace non-alphanum with underscores
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s-]+", "_", s)
    return s or "calendar"


def sync_source(source: Source) -> None:
    """Full sync pipeline for a single source.

    1. Download remote file (if URL type)
    2. Read/parse the spreadsheet
    3. Apply column mapping → EventData list
    4. Generate ICS and write to /data/feeds/{slug}.ics
    5. Update DB status
    """
    from database import update_source_status
    from services.parser import (
        download_remote_source,
        read_spreadsheet,
        dataframe_to_events,
    )
    from services.ics_generator import generate_ics

    source_id = source.id
    update_source_status(source_id, "syncing")

    try:
        # Step 1: Determine file path
        if source.source_type in ("excel_url", "csv_url"):
            if not source.source_url:
                raise ValueError("Source URL is required for URL-type sources")
            file_path = download_remote_source(
                source.source_url, source.source_type, source.slug
            )
        else:
            # Upload type — file should already be on disk
            if not source.upload_filename:
                raise ValueError("No uploaded file found for this source")
            file_path = UPLOADS_DIR / source.upload_filename
            if not file_path.exists():
                raise FileNotFoundError(f"Upload file not found: {file_path}")

        # Step 2: Parse
        df = read_spreadsheet(file_path, source.source_type)
        if df.empty:
            raise ValueError("Spreadsheet is empty or could not be parsed")

        # Step 3: Map columns → events
        events = dataframe_to_events(df, source.column_mapping)
        if not events:
            raise ValueError(
                "No events could be parsed. Check your column mapping."
            )

        # Step 4: Generate ICS
        generate_ics(events, source_id, source.name, source.slug)

        # Step 5: Success
        now = datetime.now(timezone.utc).isoformat()
        update_source_status(source_id, "synced", last_sync=now)
        logger.info(
            "Synced source '%s' (%d events)", source.name, len(events)
        )

    except Exception as exc:
        logger.exception("Failed to sync source '%s'", source.name)
        update_source_status(source_id, "error", error_message=str(exc))


def sync_all_sources() -> None:
    """Sync every configured source. Called by the scheduler."""
    from database import list_sources

    sources = list_sources()
    logger.info("Starting scheduled sync for %d source(s)", len(sources))
    for source in sources:
        sync_source(source)
    logger.info("Scheduled sync complete")


def delete_source_files(source: Source) -> None:
    """Remove feed and upload files for a deleted source."""
    feed_path = FEEDS_DIR / f"{source.slug}.ics"
    if feed_path.exists():
        feed_path.unlink()

    if source.upload_filename:
        upload_path = UPLOADS_DIR / source.upload_filename
        if upload_path.exists():
            upload_path.unlink()
