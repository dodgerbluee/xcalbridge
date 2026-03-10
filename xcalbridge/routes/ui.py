"""UI routes — server-rendered HTML with HTMX."""

from __future__ import annotations

import json
import logging
from threading import Thread
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from xcalbridge.config import UPLOADS_DIR
from xcalbridge.database import (
    create_source,
    delete_source,
    get_source,
    list_sources,
    update_source,
)
from xcalbridge.models import SourceCreate, SourceUpdate
from xcalbridge.services.parser import (
    auto_detect_columns,
    dataframe_to_events,
    download_remote_source,
    read_spreadsheet,
    read_spreadsheet_from_bytes,
)
from xcalbridge.services.sync import delete_source_files, slugify, sync_source

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="xcalbridge/templates")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    sources = list_sources()
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "sources": sources,
    })


# ---------------------------------------------------------------------------
# Add source form
# ---------------------------------------------------------------------------

@router.get("/sources/new", response_class=HTMLResponse)
def new_source_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("source_form.html", {
        "request": request,
        "source": None,
        "columns": [],
        "mapping": {},
        "edit": False,
    })


# ---------------------------------------------------------------------------
# Edit source form
# ---------------------------------------------------------------------------

@router.get("/sources/{source_id}/edit", response_class=HTMLResponse)
def edit_source_form(request: Request, source_id: int) -> HTMLResponse:
    source = get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    # Try to get columns from existing file
    columns: List[str] = []
    try:
        if source.upload_filename:
            file_path = UPLOADS_DIR / source.upload_filename
            if file_path.exists():
                df = read_spreadsheet(file_path, source.source_type)
                columns = list(df.columns)
    except Exception:
        pass

    return templates.TemplateResponse("source_form.html", {
        "request": request,
        "source": source,
        "columns": columns,
        "mapping": source.column_mapping,
        "edit": True,
    })


# ---------------------------------------------------------------------------
# Create source (form POST)
# ---------------------------------------------------------------------------

@router.post("/sources/create", response_class=HTMLResponse)
async def create_source_form(
    request: Request,
    name: str = Form(...),
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    col_event_name: Optional[str] = Form(None),
    col_date: Optional[str] = Form(None),
    col_start_time: Optional[str] = Form(None),
    col_end_time: Optional[str] = Form(None),
    col_location: Optional[str] = Form(None),
    col_description: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> RedirectResponse:
    slug = slugify(name)

    # Build column mapping
    mapping = {
        "event_name": col_event_name or None,
        "date": col_date or None,
        "start_time": col_start_time or None,
        "end_time": col_end_time or None,
        "location": col_location or None,
        "description": col_description or None,
    }

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

    data = SourceCreate(
        name=name,
        source_type=source_type,
        source_url=source_url if source_url else None,
        column_mapping=mapping,
    )
    source = create_source(data, slug, upload_filename)

    # Trigger initial sync
    if source:
        Thread(target=sync_source, args=(source,), daemon=True).start()

    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Update source (form POST)
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/update", response_class=HTMLResponse)
async def update_source_form(
    request: Request,
    source_id: int,
    name: str = Form(...),
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    col_event_name: Optional[str] = Form(None),
    col_date: Optional[str] = Form(None),
    col_start_time: Optional[str] = Form(None),
    col_end_time: Optional[str] = Form(None),
    col_location: Optional[str] = Form(None),
    col_description: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> RedirectResponse:
    existing = get_source(source_id)
    if not existing:
        raise HTTPException(404, "Source not found")

    mapping = {
        "event_name": col_event_name or None,
        "date": col_date or None,
        "start_time": col_start_time or None,
        "end_time": col_end_time or None,
        "location": col_location or None,
        "description": col_description or None,
    }

    upload_filename: Optional[str] = None
    if file and file.filename:
        slug = slugify(name)
        ext = ".xlsx" if source_type in ("excel_upload", "excel_url") else ".csv"
        upload_filename = f"{slug}{ext}"
        dest = UPLOADS_DIR / upload_filename
        with open(dest, "wb") as f:
            content = await file.read()
            f.write(content)

    data = SourceUpdate(
        name=name,
        source_type=source_type,
        source_url=source_url if source_url else None,
        column_mapping=mapping,
    )
    source = update_source(source_id, data, upload_filename)

    # Re-sync after update
    if source:
        Thread(target=sync_source, args=(source,), daemon=True).start()

    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Delete source (HTMX)
# ---------------------------------------------------------------------------

@router.delete("/sources/{source_id}", response_class=HTMLResponse)
def delete_source_ui(request: Request, source_id: int) -> HTMLResponse:
    source = get_source(source_id)
    if source:
        delete_source_files(source)
        delete_source(source_id)
    # Return updated sources table partial
    sources = list_sources()
    return templates.TemplateResponse("partials/sources_table.html", {
        "request": request,
        "sources": sources,
    })


# ---------------------------------------------------------------------------
# Sync now (HTMX)
# ---------------------------------------------------------------------------

@router.post("/sources/{source_id}/sync", response_class=HTMLResponse)
def sync_source_ui(request: Request, source_id: int) -> HTMLResponse:
    source = get_source(source_id)
    if not source:
        raise HTTPException(404, "Source not found")

    Thread(target=sync_source, args=(source,), daemon=True).start()

    # Return updated row (will show "syncing" status)
    from xcalbridge.database import update_source_status
    update_source_status(source_id, "syncing")
    sources = list_sources()
    return templates.TemplateResponse("partials/sources_table.html", {
        "request": request,
        "sources": sources,
    })


# ---------------------------------------------------------------------------
# Preview (HTMX) — parse uploaded file or URL and show events
# ---------------------------------------------------------------------------

@router.post("/preview", response_class=HTMLResponse)
async def preview_events(
    request: Request,
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
) -> HTMLResponse:
    try:
        columns: List[str] = []
        events: List[Dict[str, Any]] = []
        mapping: Dict[str, Optional[str]] = {}

        if source_type in ("excel_upload", "csv_upload") and file and file.filename:
            data = await file.read()
            df = read_spreadsheet_from_bytes(data, source_type, file.filename)
        elif source_type in ("excel_url", "csv_url") and source_url:
            file_path = download_remote_source(source_url, source_type, "_preview")
            df = read_spreadsheet(file_path, source_type)
            # Clean up preview file
            file_path.unlink(missing_ok=True)
        else:
            return templates.TemplateResponse("partials/preview_table.html", {
                "request": request,
                "events": [],
                "columns": [],
                "mapping": {},
                "error": "Please provide a file or URL",
            })

        columns = list(df.columns)
        mapping = auto_detect_columns(columns)

        # Parse events using auto-detected mapping
        parsed = dataframe_to_events(df, mapping)
        events = [e.model_dump() for e in parsed[:25]]  # Limit preview to 25

        return templates.TemplateResponse("partials/preview_table.html", {
            "request": request,
            "events": events,
            "columns": columns,
            "mapping": mapping,
            "error": None,
        })

    except Exception as exc:
        logger.exception("Preview failed")
        return templates.TemplateResponse("partials/preview_table.html", {
            "request": request,
            "events": [],
            "columns": [],
            "mapping": {},
            "error": str(exc),
        })
