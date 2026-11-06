"""What the last weeks of the calendar say about a typical week: which evenings are usually taken, which days are
heavy. Counting only, no model: every figure can be shown to the user next to the reason it supports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .model import Event
from .profile import minutes_of

WEEKS = 8
MIN_WEEKS = 3  # fewer weeks with any event: too little history to call anything a habit
RECENT_WEEKS = 3  # a pattern not seen in the last few weeks is over, however often it happened before


@dataclass
class DayStat:
    weekday: int
    weeks: int = 0  # how many of this weekday the history covers
    taken: int = 0  # of those, how many had an event inside the window
    recent: int = 0  # of those, how many in the last RECENT_WEEKS weeks
    ago: int = 0  # weeks between the most recent one and now (1 = the week just before this one)
    titles: Counter = field(default_factory=Counter)
    example: str = ""  # the most recent title found in the window
    load_min: float = 0.0  # average minutes of events over the whole day

    @property
    def share(self) -> float:
        return self.taken / self.weeks if self.weeks else 0.0

    @property
    def over(self) -> bool:
        """Taken often enough to be a habit, but not once recently: it stopped."""
        return self.taken > 0 and self.recent == 0


@dataclass
class Habits:
    days: dict[int, DayStat]
    weeks_with_events: int
    mean_load: float

    @property
    def thin(self) -> bool:
        return self.weeks_with_events < MIN_WEEKS

    def load_word(self, weekday: int) -> str:
        """light | normal | heavy, relative to the average of the days that have any history."""
        load = self.days[weekday].load_min
        if not self.mean_load:
            return "normal"
        if load >= 1.25 * self.mean_load:
            return "heavy"
        if load <= 0.75 * self.mean_load:
            return "light"
        return "normal"


def _overlap(event: Event, lo: datetime, hi: datetime) -> int:
    return max(0, int((min(event.end, hi) - max(event.start, lo)).total_seconds() // 60))


def analyse(events: list[Event], today: date, win: tuple[str, str], weeks: int = WEEKS) -> Habits:
    """The ``weeks`` full weeks before the one that holds ``today``."""
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks)
    stats = {d: DayStat(d) for d in range(1, 8)}
    active_weeks = set()
    timed = [e for e in events if not e.all_day]
    for w in range(weeks):
        for d in range(7):
            day = first + timedelta(weeks=w, days=d)
            stat = stats[day.isoweekday()]
            stat.weeks += 1
            lo, hi = datetime.combine(day, datetime.min.time()), datetime.combine(day, datetime.min.time()) + timedelta(days=1)
            w_lo = lo + timedelta(minutes=minutes_of(win[0]))
            w_hi = lo + timedelta(minutes=minutes_of(win[1]))
            mine = [e for e in timed if e.start < hi and e.end > lo]
            if mine:
                active_weeks.add(w)
            stat.load_min += sum(_overlap(e, lo, hi) for e in mine)
            inside = [e for e in mine if _overlap(e, w_lo, w_hi) > 0]
            if inside:
                stat.taken += 1
                stat.recent += w >= weeks - RECENT_WEEKS
                stat.ago = weeks - w
                stat.example = sorted(inside, key=lambda e: e.start)[0].title
                stat.titles.update(e.title.strip().lower() for e in inside)
    for stat in stats.values():
        stat.load_min = stat.load_min / stat.weeks if stat.weeks else 0.0
    loaded = [s.load_min for s in stats.values() if 1 <= s.weekday <= 5 and s.load_min]
    mean = sum(loaded) / len(loaded) if loaded else 0.0
    return Habits(stats, len(active_weeks), mean)
