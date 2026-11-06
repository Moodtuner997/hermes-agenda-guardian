"""Where could this activity go? Deterministic: free gaps in the calendar (events, the user's own habits and
protected hours subtracted), minus the days the history says are usually taken, spread over the range. Every
chosen slot and every rejected day comes with the figure that decided it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .history import RECENT_WEEKS, Habits, _overlap
from .kinds import Kind
from .model import Event
from .planner import _subtract, at, ceil_step
from .profile import minutes_of
from .texts import day_name, hm, tr

USUAL_SHARE = 0.5  # a window taken in at least half of the recorded weeks counts as a habit
MIN_TAKEN = 2


@dataclass
class Session:
    day: date
    start: datetime  # the activity itself
    end: datetime
    block_start: datetime  # with the time before it
    block_end: datetime  # with the time after it
    reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    share: float = 0.0
    spare: dict | None = None  # set when the day is usually taken but free this time: said if it is not chosen

    def to_dict(self, lang: str) -> dict:
        return {"day": self.day.isoformat(), "weekday": day_name(lang, self.day.isoweekday()),
                "block_start": self.block_start.isoformat(), "start": self.start.isoformat(),
                "end": self.end.isoformat(), "block_end": self.block_end.isoformat(),
                "reasons": self.reasons, "notes": self.notes}


def _titles(events: list[Event], lo: datetime, hi: datetime) -> str:
    inside = sorted((e for e in events if _overlap(e, lo, hi) > 0), key=lambda e: e.start)
    return ", ".join(f"« {e.title} » {e.start:%H:%M}-{e.end:%H:%M}" for e in inside[:3])


def _busy(current: date, events: list[Event], habit_rows: list[dict], profile: dict, buffer: timedelta,
          extra: tuple) -> tuple[list[Event], list[Event], list[dict], list[tuple[datetime, datetime]]]:
    """What is taken on one day: (its events, the timed ones, the user's own habits, every busy span)."""
    midnight = datetime.combine(current, datetime.min.time())
    day_events = [e for e in events if e.end > midnight and e.start < midnight + timedelta(days=1)]
    timed = [e for e in day_events if not e.all_day]
    mine = [h for h in habit_rows if h["weekday"] == current.isoweekday()]
    busy = [(e.start - buffer, e.end + buffer) for e in timed]
    busy += [(at(current, h["start"]), at(current, h["end"])) for h in mine]
    busy += [(at(current, p["start"]), at(current, p["end"])) for p in profile["protected"]]
    busy += [span for span in extra]
    return day_events, timed, mine, busy


def _window(kind: Kind, current: date, now: datetime) -> tuple[datetime, datetime]:
    window = (at(current, kind.win[0]), at(current, kind.win[1]))
    if now.date() == current:
        floor = datetime.combine(current, datetime.min.time()) + timedelta(
            minutes=ceil_step(now.hour * 60 + now.minute + 30))
        window = (max(window[0], floor), window[1])
    return window


def _rejection(lang: str, name: str, current: date, timed: list[Event], mine: list[dict], kind: Kind,
               total: int) -> dict:
    """Why nothing fits on this day: the habit, the event, or simply no gap long enough."""
    full_window = (at(current, kind.win[0]), at(current, kind.win[1]))
    habit = next((h for h in mine if minutes_of(h["start"]) < minutes_of(kind.win[1])
                  and minutes_of(h["end"]) > minutes_of(kind.win[0])), None)
    seen = _titles(timed, *full_window)
    if habit:
        text = tr(lang, "rej_habit", day=name, label=habit["label"], start=habit["start"], end=habit["end"])
        short = habit["label"]
    elif seen:
        text = tr(lang, "rej_busy", day=name, events=seen)
        short = next(e.title for e in sorted(timed, key=lambda e: e.start) if _overlap(e, *full_window) > 0)
    else:
        text = tr(lang, "rej_small", day=name, total=total)
        short = tr(lang, "short_small")
    return {"day": current.isoformat(), "weekday": name, "short": short, "reason": text}


def _length_reason(lang: str, kind: Kind, value: float, samples: int, real: int) -> str:
    if samples >= 3 and value != 1.0:
        return tr(lang, "r_len_factor", real=real, said=kind.real_min, value=value, n=samples)
    if samples:
        return tr(lang, "r_len_few", real=real, n=samples)
    return tr(lang, "r_len_said", real=real)


def propose(kind: Kind, factor: tuple[float, int], count: int, first: date, last: date, events: list[Event],
            habit_rows: list[dict], history: Habits, profile: dict, now: datetime,
            force_days: tuple[int, ...] = (), extra_busy: tuple = ()) -> dict:
    """``extra_busy``: spans already given to another activity of the same plan."""
    lang = profile.get("language", "en")
    value, samples = factor
    total, real = kind.total(value), kind.planned(value)
    buffer = timedelta(minutes=profile["buffer_min"])
    pool: list[Session] = []
    rejected: list[dict] = []
    allowed = force_days or kind.days
    day = first
    while day <= last:
        weekday = day.isoweekday()
        day, current = day + timedelta(days=1), day
        if allowed and weekday not in allowed:
            continue
        window = _window(kind, current, now)
        if window[0] >= window[1]:
            continue
        name = day_name(lang, weekday)
        day_events, timed, mine, busy = _busy(current, events, habit_rows, profile, buffer, extra_busy)
        gaps = [g for g in _subtract(window, busy) if g[1] - g[0] >= timedelta(minutes=total)]
        stat = history.days[weekday]
        if not gaps:
            rejected.append(_rejection(lang, name, current, timed, mine, kind, total))
            continue
        usual = (not history.thin and stat.taken >= MIN_TAKEN and stat.share >= USUAL_SHARE)
        over = usual and stat.over  # it was a habit, it has not happened for weeks: keep the day, say so
        usual = usual and not over  # a day the history calls busy but THIS week's calendar leaves free is kept, last
        gap = gaps[0]
        block_start = gap[0]
        start = block_start + timedelta(minutes=kind.before_min)
        end = start + timedelta(minutes=real)
        block_end = end + timedelta(minutes=kind.after_min)
        reasons = [tr(lang, "r_free", name=name, a=f"{gap[0]:%H:%M}", b=f"{gap[1]:%H:%M}")]
        if history.thin:
            reasons.append(tr(lang, "r_thin", n=history.weeks_with_events))
        elif stat.taken == 0:
            reasons.append(tr(lang, "r_hist_free", weeks=stat.weeks, day=name, start=kind.win[0], end=kind.win[1]))
        elif over:
            reasons.append(tr(lang, "r_hist_over", taken=stat.taken, weeks=stat.weeks, day=name, start=kind.win[0],
                              end=kind.win[1], recent=RECENT_WEEKS, ago=stat.ago, example=stat.example))
        else:
            reasons.append(tr(lang, ("r_hist_forced" if force_days else "r_hist_usual_free") if usual else "r_hist_some",
                              taken=stat.taken, weeks=stat.weeks, day=name, example=stat.example, start=kind.win[0],
                              end=kind.win[1]))
        if not history.thin:
            reasons.append(tr(lang, "r_load_" + history.load_word(weekday), day=name,
                              hours=hm(int(round(stat.load_min)))))
        reasons.append(_length_reason(lang, kind, value, samples, real))
        if kind.before_min or kind.after_min:
            reasons.append(tr(lang, "r_pad", before=kind.before_min, after=kind.after_min))
        notes = [tr(lang, "n_allday", title=e.title) for e in day_events if e.all_day][:2]
        if usual:
            notes.append(tr(lang, "n_usual" if force_days else "n_usual_free", taken=stat.taken, weeks=stat.weeks))
        spare = {"day": current.isoformat(), "weekday": name, "short": stat.example, "reason": tr(
            lang, "rej_usual", day=name, taken=stat.taken, weeks=stat.weeks, example=stat.example, start=kind.win[0],
            end=kind.win[1])} if usual and not force_days else None
        pool.append(Session(current, start, end, block_start, block_end, reasons, notes,
                            0.0 if over else stat.share, spare))

    chosen: list[Session] = []

    def pick(gap_days: int) -> None:
        for candidate in sorted(pool, key=lambda s: (s.share, s.day)):
            if len(chosen) >= count:
                return
            if candidate not in chosen and all(abs((candidate.day - c.day).days) >= gap_days for c in chosen):
                chosen.append(candidate)

    pick(2)
    spread = len(chosen)
    pick(1)
    rejected += [s.spare for s in pool if s.spare and s not in chosen]
    chosen.sort(key=lambda s: s.day)
    for session in chosen:
        others = [abs((session.day - o.day).days) for o in chosen if o is not session]
        if others:
            session.reasons.append(tr(lang, "r_spread", n=min(others)))
    return {"sessions": [s.to_dict(lang) for s in chosen], "rejected": rejected[:6],
            "missing": max(0, count - len(chosen)), "adjacent": len(chosen) > spread,
            "history_weeks": history.weeks_with_events, "history_thin": history.thin,
            "minutes": {"before": kind.before_min, "activity": real, "after": kind.after_min, "total": total}}


def fill_days(kind: Kind, factor: tuple[float, int], per_day: int, first: date, last: date, events: list[Event],
              habit_rows: list[dict], history: Habits, profile: dict, now: datetime,
              force_days: tuple[int, ...] = (), extra_busy: tuple = ()) -> dict:
    """An activity that happens every day (a course, a block of focus): each allowed day gets ``per_day``
    sessions, one after the other with a break between, wherever the calendar has room. History never rules a
    day out here, it only says when a day is usually heavy."""
    lang = profile.get("language", "en")
    value, samples = factor
    total, real = kind.total(value), kind.planned(value)
    buffer = timedelta(minutes=profile["buffer_min"])
    pause = timedelta(minutes=profile["break_min"])
    allowed = force_days or kind.days
    sessions: list[Session] = []
    rejected: list[dict] = []
    wanted = 0
    day = first
    while day <= last:
        weekday = day.isoweekday()
        day, current = day + timedelta(days=1), day
        if allowed and weekday not in allowed:
            continue
        window = _window(kind, current, now)
        if window[0] >= window[1]:
            continue
        wanted += per_day
        name = day_name(lang, weekday)
        day_events, timed, mine, busy = _busy(current, events, habit_rows, profile, buffer, extra_busy)
        stat = history.days[weekday]
        placed: list[Session] = []
        for _ in range(per_day):
            gaps = [g for g in _subtract(window, busy) if g[1] - g[0] >= timedelta(minutes=total)]
            if not gaps:
                break
            block_start = gaps[0][0]
            start = block_start + timedelta(minutes=kind.before_min)
            end = start + timedelta(minutes=real)
            block_end = end + timedelta(minutes=kind.after_min)
            reasons = [tr(lang, "r_free", name=name, a=f"{gaps[0][0]:%H:%M}", b=f"{gaps[0][1]:%H:%M}"),
                       _length_reason(lang, kind, value, samples, real)]
            if not history.thin and history.load_word(weekday) == "heavy":
                reasons.append(tr(lang, "r_load_heavy", day=name, hours=hm(int(round(stat.load_min)))))
            notes = [tr(lang, "n_allday", title=e.title) for e in day_events if e.all_day][:2]
            placed.append(Session(current, start, end, block_start, block_end, reasons, notes))
            busy.append((block_start - pause, block_end + pause))
        sessions += placed
        if not placed:
            rejected.append(_rejection(lang, name, current, timed, mine, kind, total))
        elif len(placed) < per_day:
            rejected.append({"day": current.isoformat(), "weekday": name, "short": tr(lang, "short_part"),
                             "reason": tr(lang, "rej_part", day=name, got=len(placed), wanted=per_day)})
    return {"sessions": [s.to_dict(lang) for s in sessions], "rejected": rejected[:6],
            "missing": max(0, wanted - len(sessions)), "adjacent": False, "wanted": wanted,
            "history_weeks": history.weeks_with_events, "history_thin": history.thin,
            "minutes": {"before": kind.before_min, "activity": real, "after": kind.after_min, "total": total}}
