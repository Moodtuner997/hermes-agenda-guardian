"""The only place that writes to a calendar. Two rules live here and nowhere else:

* what is written is recorded (event id, link, group) the moment it exists;
* ``remove`` refuses any event that is not in that record, and any record whose marker is gone from the event
  (the user rewrote it), so an event the user created can never be deleted through this plugin.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from . import sources, store

MARK = "agenda-guardian"


class ForeignEvent(Exception):
    """An event id this plugin did not create."""


def marker(group: int, part: str) -> str:
    return f"[{MARK}:{group}:{part}]"


def create(home: Path, tzname: str, calendar_id: str, summary: str, start: datetime, end: datetime,
           description: str, run=subprocess.run) -> tuple[str, str]:
    """One event on the Google calendar: (event id, link). Raises ``sources.SourceError``."""
    argv = sources.google_argv(
        home, "calendar", "create", "--summary", summary, "--start", sources._aware(start, tzname).isoformat(),
        "--end", sources._aware(end, tzname).isoformat(), "--description", description, "--calendar", calendar_id)
    data = sources._run_json(argv, run)
    if not isinstance(data, dict) or not data.get("id"):
        raise sources.SourceError("the calendar did not return an event id")
    return str(data["id"]), str(data.get("htmlLink", ""))


def _live(home: Path, tzname: str, calendar_id: str, day_start: datetime, day_end: datetime, run) -> dict[str, dict]:
    argv = sources.google_argv(home, "calendar", "list", "--start", sources.iso_utc(day_start, tzname),
                               "--end", sources.iso_utc(day_end, tzname), "--max", "100", "--calendar", calendar_id)
    data = sources._run_json(argv, run)
    return {str(e.get("id")): e for e in data if isinstance(e, dict)} if isinstance(data, list) else {}


def remove(conn, home: Path, tzname: str, event_id: str, now: datetime, run=subprocess.run) -> str:
    """Delete one event this plugin created. Returns ``deleted``, ``gone`` or ``rewritten``.
    Raises ``ForeignEvent`` for any other id, without calling the calendar."""
    row = store.written_event(conn, event_id)
    if row is None:
        raise ForeignEvent(event_id)
    start, end = datetime.fromisoformat(row["start"]), datetime.fromisoformat(row["end"])
    midnight = start.replace(hour=0, minute=0, second=0)
    live = _live(home, tzname, row["calendar_id"], midnight, midnight + timedelta(days=2), run)
    found = live.get(event_id)
    if found is None:
        store.mark_removed(conn, event_id, "gone", now)
        return "gone"
    if marker(row["group_id"], row["part"]) not in str(found.get("description", "")):
        store.mark_removed(conn, event_id, "rewritten", now)
        return "rewritten"
    argv = sources.google_argv(home, "calendar", "delete", event_id, "--calendar", row["calendar_id"])
    sources._run_json(argv, run)
    store.mark_removed(conn, event_id, "deleted", now)
    return "deleted"
