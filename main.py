"""xCalBridge — FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import ensure_dirs
from database import init_db
from routes import api, feeds, settings, ui
from services.scheduler import start_scheduler, stop_scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — startup and shutdown."""
    # Startup
    logger.info("Starting xCalBridge")
    ensure_dirs()
    init_db()
    start_scheduler()
    logger.info("Application ready")
    yield
    # Shutdown
    stop_scheduler()
    logger.info("Shutting down")


app = FastAPI(
    title="xCalBridge",
    description="Convert sports schedules to ICS calendar feeds",
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(api.router)
app.include_router(feeds.router)
app.include_router(settings.router)
app.include_router(ui.router)


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT

    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
