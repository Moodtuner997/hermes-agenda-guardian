"""SQLite storage: tasks, finished-task measurements and the profile. Standard library only."""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

from .model import Task
from .profile import merged
from .texts import tr

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
CREATE TABLE IF NOT EXISTS kinds (
  name TEXT PRIMARY KEY, real_min INTEGER NOT NULL, before_min INTEGER NOT NULL, after_min INTEGER NOT NULL,
  win_start TEXT NOT NULL, win_end TEXT NOT NULL, days TEXT NOT NULL, set_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS habits (
  id INTEGER PRIMARY KEY AUTOINCREMENT, weekday INTEGER NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
  label TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
  payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS written (
  event_id TEXT PRIMARY KEY, calendar_id TEXT NOT NULL, group_id INTEGER NOT NULL, proposal_id INTEGER,
  kind TEXT NOT NULL, part TEXT NOT NULL, summary TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
  link TEXT NOT NULL, created_at TEXT NOT NULL, removed_at TEXT, removed_why TEXT);
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


def find_task(conn, ref: str, lang: str = "en") -> Task:
    """An open task by number ('3' or '#3') or by a unique piece of its name."""
    ref = ref.strip().lstrip("#")
    if ref.isdigit():
        row = conn.execute(f"SELECT {_COLS} FROM tasks WHERE id=? AND status='open'", (int(ref),)).fetchone()
        if row:
            return _task(row)
        raise RefError(tr(lang, "ref_number", ref=ref))
    rows = conn.execute(f"SELECT {_COLS} FROM tasks WHERE status='open' AND lower(name) LIKE ?",
                        (f"%{ref.lower()}%",)).fetchall()
    if not rows:
        raise RefError(tr(lang, "ref_none", ref=ref))
    if len(rows) > 1:
        names = "; ".join(f"#{r[0]} {r[1]}" for r in rows)
        raise RefError(tr(lang, "ref_several", ref=ref, names=names))
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


# --- activity sheets, habits, proposals, written events --------------------------------------------------

def get_flag(conn, key: str) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return bool(row) and row[0] == "1"


def set_flag(conn, key: str, on: bool) -> None:
    conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, "1" if on else "0"))
    conn.commit()


def save_kind(conn, kind, now: datetime) -> None:
    conn.execute(
        "INSERT INTO kinds(name, real_min, before_min, after_min, win_start, win_end, days, set_at) "
        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET real_min=excluded.real_min, "
        "before_min=excluded.before_min, after_min=excluded.after_min, win_start=excluded.win_start, "
        "win_end=excluded.win_end, days=excluded.days, set_at=excluded.set_at",
        (kind.name, kind.real_min, kind.before_min, kind.after_min, kind.win[0], kind.win[1],
         ",".join(map(str, kind.days)), now.date().isoformat()))
    conn.commit()


def _kind(row):
    from .kinds import Kind

    return Kind(row[0], row[1], row[2], row[3], (row[4], row[5]),
                tuple(int(d) for d in row[6].split(",") if d), row[7])


_KIND_COLS = "name, real_min, before_min, after_min, win_start, win_end, days, set_at"


def kinds(conn) -> list:
    return [_kind(r) for r in conn.execute(f"SELECT {_KIND_COLS} FROM kinds ORDER BY name")]


def get_kind(conn, name: str):
    row = conn.execute(f"SELECT {_KIND_COLS} FROM kinds WHERE name=?", (name.strip().lower(),)).fetchone()
    return _kind(row) if row else None


def remove_kind(conn, name: str) -> bool:
    cur = conn.execute("DELETE FROM kinds WHERE name=?", (name.strip().lower(),))
    conn.commit()
    return cur.rowcount > 0


def add_habit(conn, weekday: int, start: str, end: str, label: str, now: datetime) -> int:
    cur = conn.execute("INSERT INTO habits(weekday, start, end, label, created_at) VALUES(?,?,?,?,?)",
                       (weekday, start, end, label, now.isoformat()))
    conn.commit()
    return cur.lastrowid


def habits(conn) -> list[dict]:
    return [{"id": r[0], "weekday": r[1], "start": r[2], "end": r[3], "label": r[4]}
            for r in conn.execute("SELECT id, weekday, start, end, label FROM habits ORDER BY weekday, start")]


def remove_habit(conn, habit_id: int) -> bool:
    cur = conn.execute("DELETE FROM habits WHERE id=?", (habit_id,))
    conn.commit()
    return cur.rowcount > 0


def add_proposal(conn, kind: str, payload: str, now: datetime) -> int:
    cur = conn.execute("INSERT INTO proposals(kind, status, created_at, payload) VALUES(?, 'pending', ?, ?)",
                       (kind, now.isoformat(), payload))
    conn.commit()
    return cur.lastrowid


def get_proposal(conn, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT id, kind, status, created_at, payload FROM proposals WHERE id=?",
                       (proposal_id,)).fetchone()
    if not row:
        return None
    return {"id": row[0], "kind": row[1], "status": row[2], "created_at": row[3], "payload": json.loads(row[4])}


def pending_proposals(conn) -> list[dict]:
    rows = conn.execute("SELECT id FROM proposals WHERE status='pending' ORDER BY id").fetchall()
    return [get_proposal(conn, r[0]) for r in rows]


def set_proposal_status(conn, proposal_id: int, status: str) -> None:
    conn.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
    conn.commit()


def new_group(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(group_id), 0) + 1 FROM written").fetchone()[0]


def record_written(conn, row: dict, now: datetime) -> None:
    conn.execute(
        "INSERT INTO written(event_id, calendar_id, group_id, proposal_id, kind, part, summary, start, end, link, "
        "created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (row["event_id"], row["calendar_id"], row["group_id"], row.get("proposal_id"), row["kind"], row["part"],
         row["summary"], row["start"], row["end"], row.get("link", ""), now.isoformat()))
    conn.commit()


_WRITTEN_COLS = "event_id, calendar_id, group_id, proposal_id, kind, part, summary, start, end, link, removed_at"


def _written(row) -> dict:
    keys = _WRITTEN_COLS.split(", ")
    return dict(zip(keys, row))


def written(conn, group_id: int | None = None, live_only: bool = True) -> list[dict]:
    where, args = [], []
    if live_only:
        where.append("removed_at IS NULL")
    if group_id is not None:
        where.append("group_id=?")
        args.append(group_id)
    sql = f"SELECT {_WRITTEN_COLS} FROM written" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY start"
    return [_written(r) for r in conn.execute(sql, args)]


def written_event(conn, event_id: str) -> dict | None:
    row = conn.execute(f"SELECT {_WRITTEN_COLS} FROM written WHERE event_id=? AND removed_at IS NULL",
                       (event_id,)).fetchone()
    return _written(row) if row else None


def mark_removed(conn, event_id: str, why: str, now: datetime) -> None:
    conn.execute("UPDATE written SET removed_at=?, removed_why=? WHERE event_id=?", (now.isoformat(), why, event_id))
    conn.commit()


def last_group(conn) -> int | None:
    row = conn.execute("SELECT MAX(group_id) FROM written WHERE removed_at IS NULL").fetchone()
    return row[0]


def log_sample(conn, category: str, est_min: int, actual_min: int, now: datetime) -> None:
    conn.execute("INSERT INTO samples(task_id, category, est_min, actual_min, logged_at) VALUES(NULL,?,?,?,?)",
                 (category, est_min, actual_min, now.isoformat()))
    conn.commit()
