"""Background scheduler for periodic source syncing."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from xcalbridge.config import SYNC_INTERVAL_HOURS

logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None


def start_scheduler() -> None:
    """Start the background sync scheduler."""
    global _scheduler

    from xcalbridge.services.sync import sync_all_sources

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        sync_all_sources,
        trigger=IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
        id="sync_all",
        name="Sync all calendar sources",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started — syncing every %d hour(s)", SYNC_INTERVAL_HOURS
    )


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        _scheduler = None
