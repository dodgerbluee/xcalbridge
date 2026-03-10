"""Feed serving routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from xcalbridge.config import FEEDS_DIR

router = APIRouter()


@router.get("/feeds/{calendar_name}.ics")
def serve_feed(calendar_name: str) -> FileResponse:
    """Serve a generated ICS calendar feed."""
    feed_path = FEEDS_DIR / f"{calendar_name}.ics"
    if not feed_path.exists():
        raise HTTPException(404, f"Feed '{calendar_name}' not found")

    return FileResponse(
        path=feed_path,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{calendar_name}.ics"',
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )
