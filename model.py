"""Plain data types shared by the planner, the store and the renderers (all times are naive local time)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


class UserError(ValueError):
    """A mistake in what the user typed; the message tells them how to fix it."""


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    end: datetime
    all_day: bool = False


@dataclass
class Task:
    id: int
    name: str
    category: str
    est_min: int
    priority: int  # 1 = most important, 3 = least
    due: date | None
    status: str = "open"  # open | done | dropped


@dataclass
class Block:
    start: datetime
    end: datetime
    task_id: int
    name: str
    part: int
    parts: int
    focus: bool
    why: list[str] = field(default_factory=list)

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Dropped:
    task: Task
    code: str  # daily_cap | no_room | non_workday
    detail: str


@dataclass
class Plan:
    day: date
    window: tuple[datetime, datetime] | None
    blocks: list[Block]
    events: list[Event]
    protected: list[tuple[str, datetime, datetime]]
    dropped: list[Dropped]
    free_min: int
    planned_min: int
    warnings: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "free_min": self.free_min,
            "planned_min": self.planned_min,
            "blocks": [
                {"start": b.start.strftime("%H:%M"), "end": b.end.strftime("%H:%M"), "task_id": b.task_id,
                 "task": b.name, "part": b.part, "parts": b.parts, "focus": b.focus, "why": b.why}
                for b in self.blocks
            ],
            "events": [{"title": e.title, "start": e.start.strftime("%H:%M"), "end": e.end.strftime("%H:%M"),
                        "all_day": e.all_day} for e in self.events],
            "not_today": [{"task_id": d.task.id, "task": d.task.name, "code": d.code, "detail": d.detail}
                          for d in self.dropped],
            "warnings": self.warnings,
            "rules": self.rules,
        }
