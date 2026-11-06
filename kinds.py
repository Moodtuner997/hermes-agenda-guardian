"""Activity sheets ("fiches"): what one kind of activity really takes, with the time around it, and when it fits."""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import profile as prof
from .model import UserError
from .texts import tr

STEP = 5


def ceil_step(minutes: float) -> int:
    return int(math.ceil(minutes / STEP) * STEP)


@dataclass(frozen=True)
class Kind:
    name: str
    real_min: int  # what the activity itself takes, in the user's own words
    before_min: int  # time to get ready, kept free before it
    after_min: int  # shower, travel, wind-down, kept free after it
    win: tuple[str, str]  # the hours in which the whole thing (before + activity + after) must fit
    days: tuple[int, ...] = ()  # preferred weekdays, 1 = Monday; empty = any
    set_at: str = ""

    def planned(self, factor: float = 1.0) -> int:
        """The activity itself, corrected by the user's measured pace."""
        return ceil_step(self.real_min * factor)

    def total(self, factor: float = 1.0) -> int:
        return self.before_min + self.planned(factor) + self.after_min


def category(name: str) -> str:
    """The key under which this activity's measured durations are kept."""
    return f"kind:{name}"


def build(name: str, real_min: int, before_min: int, after_min: int, window: str, days: str,
          lang: str = "en") -> Kind:
    name = " ".join(str(name).lower().split())
    if not name or len(name) > 40:
        raise UserError(tr(lang, "kind_name"))
    if not 5 <= real_min <= 480:
        raise UserError(tr(lang, "kind_real_range"))
    for value in (before_min, after_min):
        if not 0 <= value <= 180:
            raise UserError(tr(lang, "kind_pad_range"))
    try:
        win = prof._range(window, lang)
        weekdays = tuple(prof._weekdays(days, lang)) if str(days).strip() else ()
    except ValueError as exc:
        raise UserError(str(exc))
    kind = Kind(name, int(real_min), int(before_min), int(after_min), win, weekdays)
    room = prof.minutes_of(win[1]) - prof.minutes_of(win[0])
    if kind.total() > room:
        raise UserError(tr(lang, "kind_too_big", total=kind.total(), room=room, start=win[0], end=win[1]))
    return kind
