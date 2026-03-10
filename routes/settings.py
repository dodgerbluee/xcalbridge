"""Settings routes — manage app configuration."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from database import get_all_settings, update_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: Optional[str] = None) -> HTMLResponse:
    """Display the settings form."""
    settings = get_all_settings()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "saved": saved == "1",
    })


@router.post("/settings", response_class=HTMLResponse)
async def save_settings(
    request: Request,
    ollama_url: str = Form(...),
    ollama_model: str = Form(...),
    sync_interval_hours: int = Form(...),
    default_event_duration_minutes: int = Form(...),
) -> RedirectResponse:
    """Save settings and redirect back."""
    update_settings({
        "ollama_url": ollama_url.rstrip("/"),
        "ollama_model": ollama_model.strip(),
        "sync_interval_hours": str(max(1, sync_interval_hours)),
        "default_event_duration_minutes": str(max(15, default_event_duration_minutes)),
    })
    logger.info(
        "Settings updated: ollama=%s model=%s interval=%dh duration=%dm",
        ollama_url, ollama_model, sync_interval_hours, default_event_duration_minutes,
    )

    # Reschedule the sync job with the new interval
    _reschedule_sync(max(1, sync_interval_hours))

    return RedirectResponse(url="/settings?saved=1", status_code=303)


def _reschedule_sync(hours: int) -> None:
    """Update the scheduler interval without a full restart."""
    try:
        from services.scheduler import reschedule_sync
        reschedule_sync(hours)
    except Exception:
        logger.warning("Could not reschedule sync job", exc_info=True)
