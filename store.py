"""SQLite storage: tasks, finished-task measurements and the profile. Standard library only."""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from .model import Task
from .profile import merged

MIN_SAMPLES = 3
FACTOR_RANGE = (0.7, 3.0)

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
  est_min INTEGER NOT NULL, priority INTEGER NOT NULL, due TEXT, status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL, done_at TEXT);
CREATE TABLE IF NOT EXISTS samples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, category TEXT NOT NULL,
  est_min INTEGER NOT NULL, actual_min INTEGER NOT NULL, logged_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plan_cache (day TEXT PRIMARY KEY, json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS notified (key TEXT PRIMARY KEY, at TEXT NOT NULL);
"""


class RefError(ValueError):
    pass


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def _task(row) -> Task:
    return Task(id=row[0], name=row[1], category=row[2], est_min=row[3], priority=row[4],
                due=date.fromisoformat(row[5]) if row[5] else None, status=row[6])


_COLS = "id, name, category, est_min, priority, due, status"


def load_profile(conn) -> dict:
    row = conn.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
    return merged(json.loads(row[0]) if row else None)


def save_profile(conn, profile: dict) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES('profile', ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(profile),))
    conn.commit()


def add_task(conn, name: str, category: str, est_min: int, priority: int, due: date | None, now: datetime) -> Task:
    cur = conn.execute("INSERT INTO tasks(name, category, est_min, priority, due, created_at) VALUES(?,?,?,?,?,?)",
                       (name, category, est_min, priority, due.isoformat() if due else None, now.isoformat()))
    conn.commit()
    return Task(cur.lastrowid, name, category, est_min, priority, due)


def tasks(conn, status: str = "open") -> list[Task]:
    rows = conn.execute(f"SELECT {_COLS} FROM tasks WHERE status=? ORDER BY id", (status,)).fetchall()
    return [_task(r) for r in rows]


def find_task(conn, ref: str) -> Task:
    """An open task by number ('3' or '#3') or by a unique piece of its name."""
    ref = ref.strip().lstrip("#")
    if ref.isdigit():
        row = conn.execute(f"SELECT {_COLS} FROM tasks WHERE id=? AND status='open'", (int(ref),)).fetchone()
        if row:
            return _task(row)
        raise RefError(f"no open task number {ref}")
    rows = conn.execute(f"SELECT {_COLS} FROM tasks WHERE status='open' AND lower(name) LIKE ?",
                        (f"%{ref.lower()}%",)).fetchall()
    if not rows:
        raise RefError(f"no open task matches '{ref}'")
    if len(rows) > 1:
        names = "; ".join(f"#{r[0]} {r[1]}" for r in rows)
        raise RefError(f"'{ref}' matches several tasks ({names}); use the number")
    return _task(rows[0])


def finish_task(conn, task: Task, actual_min: int, now: datetime) -> None:
    conn.execute("UPDATE tasks SET status='done', done_at=? WHERE id=?", (now.isoformat(), task.id))
    conn.execute("INSERT INTO samples(task_id, category, est_min, actual_min, logged_at) VALUES(?,?,?,?,?)",
                 (task.id, task.category, task.est_min, actual_min, now.isoformat()))
    conn.commit()


def drop_task(conn, task: Task) -> None:
    conn.execute("UPDATE tasks SET status='dropped' WHERE id=?", (task.id,))
    conn.commit()


def factors(conn) -> dict[str, tuple[float, int]]:
    """Per category: (median of actual/estimate clamped to a sane range, number of measurements).
    Under MIN_SAMPLES measurements the factor stays 1.0: three data points are the least that mean anything."""
    ratios: dict[str, list[float]] = {}
    for category, est, actual in conn.execute("SELECT category, est_min, actual_min FROM samples"):
        ratios.setdefault(category, []).append(actual / est)
    result = {}
    for category, values in ratios.items():
        if len(values) < MIN_SAMPLES:
            result[category] = (1.0, len(values))
        else:
            low, high = FACTOR_RANGE
            result[category] = (round(min(high, max(low, statistics.median(values))), 2), len(values))
    return result


def save_plan(conn, day: str, payload: str) -> None:
    """The plan a day's reminders follow: one row per day, rows older than two weeks are dropped."""
    conn.execute("INSERT INTO plan_cache(day, json) VALUES(?, ?) ON CONFLICT(day) DO UPDATE SET json=excluded.json",
                 (day, payload))
    conn.execute("DELETE FROM plan_cache WHERE day < date(?, '-14 days')", (day,))
    conn.commit()


def load_plan(conn, day: str) -> str | None:
    row = conn.execute("SELECT json FROM plan_cache WHERE day=?", (day,)).fetchone()
    return row[0] if row else None


def was_notified(conn, key: str) -> bool:
    return conn.execute("SELECT 1 FROM notified WHERE key=?", (key,)).fetchone() is not None


def mark_notified(conn, key: str, now: datetime) -> None:
    conn.execute("INSERT OR IGNORE INTO notified(key, at) VALUES(?, ?)", (key, now.isoformat()))
    conn.execute("DELETE FROM notified WHERE at < ?", ((now - timedelta(days=14)).isoformat(),))
    conn.commit()
