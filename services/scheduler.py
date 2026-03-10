"""Background scheduler for periodic source syncing."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database import get_setting

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def _get_sync_interval() -> int:
    """Read sync interval from DB settings, fall back to config default."""
    try:
        val = get_setting("sync_interval_hours")
        return int(val) if val else 3
    except Exception:
        from config import SYNC_INTERVAL_HOURS
        return SYNC_INTERVAL_HOURS


def start_scheduler() -> None:
    """Start the background sync scheduler."""
    global _scheduler

    from services.sync import sync_all_sources

    interval = _get_sync_interval()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        sync_all_sources,
        trigger=IntervalTrigger(hours=interval),
        id="sync_all",
        name="Sync all calendar sources",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — syncing every %d hour(s)", interval)


def reschedule_sync(hours: int) -> None:
    """Update the sync interval on a running scheduler."""
    global _scheduler
    if not _scheduler or not _scheduler.running:
        logger.warning("Scheduler not running, cannot reschedule")
        return

    from services.sync import sync_all_sources

    _scheduler.reschedule_job(
        "sync_all",
        trigger=IntervalTrigger(hours=hours),
    )
    logger.info("Rescheduled sync job to every %d hour(s)", hours)


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        _scheduler = None
