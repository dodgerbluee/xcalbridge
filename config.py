"""Application configuration and path constants."""

import os
from pathlib import Path


# Base data directory — /data in Docker, ./data locally
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

DB_PATH = DATA_DIR / "db.sqlite"
FEEDS_DIR = DATA_DIR / "feeds"
UPLOADS_DIR = DATA_DIR / "uploads"

# Sync interval in hours
SYNC_INTERVAL_HOURS = int(os.getenv("SYNC_INTERVAL_HOURS", "3"))

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))

# Maximum upload size (50 MB)
MAX_UPLOAD_SIZE = 50 * 1024 * 1024


def ensure_dirs() -> None:
    """Create required data directories if they don't exist."""
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
