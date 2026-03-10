"""ICS calendar file generation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from ics import Calendar, Event
from ics.grammar.parse import ContentLine

from xcalbridge.config import FEEDS_DIR
from xcalbridge.models import EventData


def _make_uid(source_id: int, event: EventData) -> str:
    """Generate a deterministic UID for an event.

    Based on source + event content so UIDs stay stable across re-syncs,
    preventing duplicate events in subscribing calendar apps.
    """
    raw = f"{source_id}:{event.event_name}:{event.date}:{event.start_time or ''}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{h}@xcalbridge"


def generate_ics(
    events: List[EventData],
    source_id: int,
    calendar_name: str,
    slug: str,
) -> Path:
    """Generate an ICS file from a list of events and write it to disk.

    Returns the path to the written .ics file.
    """
    cal = Calendar()
    # X-WR-CALNAME is non-standard but widely supported
    # for setting a display name on the calendar.
    cal.extra.append(ContentLine(name="X-WR-CALNAME", value=calendar_name))

    for ev_data in events:
        e = Event()
        e.uid = _make_uid(source_id, ev_data)
        e.name = ev_data.event_name

        if ev_data.all_day or not ev_data.start_time:
            # All-day event
            dt = datetime.strptime(ev_data.date, "%Y-%m-%d")
            e.begin = dt
            e.make_all_day()
        else:
            # Timed event
            start_str = f"{ev_data.date} {ev_data.start_time}"
            e.begin = datetime.strptime(start_str, "%Y-%m-%d %H:%M")

            if ev_data.end_time:
                end_str = f"{ev_data.date} {ev_data.end_time}"
                e.end = datetime.strptime(end_str, "%Y-%m-%d %H:%M")
            else:
                # Default to 1.5 hour duration for sports events
                e.end = e.begin + timedelta(hours=1, minutes=30)

        if ev_data.location:
            e.location = ev_data.location
        if ev_data.description:
            e.description = ev_data.description

        cal.events.add(e)

    # Write to disk
    FEEDS_DIR.mkdir(parents=True, exist_ok=True)
    feed_path = FEEDS_DIR / f"{slug}.ics"
    with open(feed_path, "w", encoding="utf-8") as f:
        f.writelines(cal.serialize_iter())

    return feed_path
