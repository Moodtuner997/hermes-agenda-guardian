"""The planner: deterministic, no model call. Free time = work window minus calendar events (with a buffer)
minus protected windows; the day's tasks are the first few by due date then priority; each is split into
focus-sized blocks and placed all-or-nothing, so a full day says what drops and why."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from .model import Block, Dropped, Event, Plan, Task
from .profile import clock, minutes_of, source_of

STEP = 5


def ceil_step(minutes: float) -> int:
    return int(math.ceil(minutes / STEP) * STEP)


def at(day: date, hhmm: str) -> datetime:
    minutes = minutes_of(hhmm)
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minutes)


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def _subtract(window: tuple[datetime, datetime], busy: list[tuple[datetime, datetime]]):
    free, cursor = [], window[0]
    for start, end in _merge([(max(s, window[0]), min(e, window[1])) for s, e in busy if e > window[0] and s < window[1]]):
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < window[1]:
        free.append((cursor, window[1]))
    return free


def _split_by_focus(free, focus):
    """Cut free spans at focus-window edges: every slot is then wholly inside or outside focus time."""
    slots = []
    for start, end in free:
        cuts = {start, end}
        for f_start, f_end in focus:
            for point in (f_start, f_end):
                if start < point < end:
                    cuts.add(point)
        ordered = sorted(cuts)
        for lo, hi in zip(ordered, ordered[1:]):
            if (hi - lo) >= timedelta(minutes=STEP):
                inside = any(f_start <= lo and hi <= f_end for f_start, f_end in focus)
                slots.append({"start": lo, "end": hi, "focus": inside})
    return slots


def chunk_sizes(planned: int, max_block: int) -> list[int]:
    units = planned // STEP
    count = max(1, math.ceil(planned / max_block))
    base, extra = divmod(units, count)
    return [(base + (1 if i < extra else 0)) * STEP for i in range(count)]


def _why(task: Task, planned: int, factor: tuple[float, int], focus: bool, day: date) -> list[str]:
    value, count = factor
    if count and value != 1.0:
        lines = [f"{planned} min = your estimate {task.est_min} x {value:g} (median of {count} finished "
                 f"'{task.category}' tasks)"]
    elif count:
        lines = [f"{planned} min = your estimate ({count} finished '{task.category}' task"
                 f"{'s' if count != 1 else ''}; calibration starts at 3)"]
    else:
        lines = [f"{planned} min = your estimate (no finished '{task.category}' task yet)"]
    if task.due:
        if task.due < day:
            lines.append(f"overdue since {task.due.isoformat()}")
        else:
            lines.append(f"due {task.due.isoformat()}")
    lines.append(f"priority {task.priority}")
    if focus:
        lines.append("in your focus window")
    return lines


def rules_used(profile: dict) -> list[str]:
    """Each rule that shaped the plan, once, with whether the user set it or it is still a default."""
    start, end = profile["work_hours"]
    lines = [f"work hours {start}-{end} ({source_of(profile, 'work_hours')})"]
    lines += [f"{p['name']} {p['start']}-{p['end']} kept free ({source_of(profile, 'protected')})"
              for p in profile["protected"]]
    if profile["focus"]:
        spans = ", ".join(f"{f['start']}-{f['end']}" for f in profile["focus"])
        lines.append(f"focus window {spans} for priority 1 ({source_of(profile, 'focus')})")
    lines += [f"{profile['buffer_min']} min around meetings ({source_of(profile, 'buffer_min')})",
              f"blocks of at most {profile['max_block_min']} min, {profile['break_min']} min break "
              f"({source_of(profile, 'max_block_min')})",
              f"at most {profile['max_tasks_per_day']} tasks a day ({source_of(profile, 'max_tasks_per_day')})"]
    return lines


def plan_day(day: date, events: list[Event], tasks: list[Task], profile: dict,
             factors: dict[str, tuple[float, int]], now: datetime | None = None,
             warnings: list[str] | None = None) -> Plan:
    warnings = list(warnings or [])
    todays = [e for e in events if e.end > datetime.combine(day, datetime.min.time())
              and e.start < datetime.combine(day, datetime.min.time()) + timedelta(days=1)]
    open_tasks = sorted(tasks, key=lambda t: (t.due is None, t.due or date.max, t.priority, t.id))
    if day.isoweekday() not in profile["workdays"]:
        dropped = [Dropped(t, "non_workday", f"{day.isoformat()} is not one of your workdays "
                           f"(rule workdays, {source_of(profile, 'workdays')})") for t in open_tasks]
        return Plan(day, None, [], todays, [], dropped, 0, 0, warnings)

    start_text, end_text = profile["work_hours"]
    window = (at(day, start_text), at(day, end_text))
    if now is not None and now.date() == day and now > window[0]:
        window = (min(window[1], datetime.combine(day, datetime.min.time()) + timedelta(minutes=ceil_step(now.hour * 60 + now.minute))), window[1])
    buffer = timedelta(minutes=profile["buffer_min"])
    protected = [(p["name"], at(day, p["start"]), at(day, p["end"])) for p in profile["protected"]]
    busy = [(e.start - buffer, e.end + buffer) for e in todays if not e.all_day]
    busy += [(s, e) for _, s, e in protected]
    focus = [(at(day, f["start"]), at(day, f["end"])) for f in profile["focus"]]
    slots = _split_by_focus(_subtract(window, busy), focus)
    free_min = sum(int((s["end"] - s["start"]).total_seconds() // 60) for s in slots)

    cap = profile["max_tasks_per_day"]
    chosen, dropped = open_tasks[:cap], []
    for task in open_tasks[cap:]:
        dropped.append(Dropped(task, "daily_cap", f"not among the {cap} tasks of the day "
                               f"(rule max_tasks_per_day, {source_of(profile, 'max_tasks_per_day')})"))

    blocks: list[Block] = []
    for task in chosen:
        factor = factors.get(task.category, (1.0, 0))
        planned = ceil_step(task.est_min * factor[0])
        sizes = chunk_sizes(planned, profile["max_block_min"])
        trial = [dict(s) for s in slots]
        placed: list[tuple[datetime, datetime, bool]] = []
        order = (True, False) if task.priority == 1 else (False, True)
        for size in sizes:
            need = timedelta(minutes=size)
            pick = next((s for want in order for s in sorted(trial, key=lambda x: x["start"])
                         if s["focus"] == want and s["end"] - s["start"] >= need), None)
            if pick is None:
                break
            placed.append((pick["start"], pick["start"] + need, pick["focus"]))
            pick["start"] = pick["start"] + need + timedelta(minutes=profile["break_min"])
        if len(placed) < len(sizes):
            fit = sum(int((e - s).total_seconds() // 60) for s, e, _ in placed)
            dropped.append(Dropped(task, "no_room", f"needs {planned} min in blocks of at most "
                                   f"{profile['max_block_min']}; only {fit} min fit before {end_text} "
                                   f"(short by {planned - fit} min)"))
            continue
        slots = trial
        placed.sort()
        for index, (b_start, b_end, in_focus) in enumerate(placed, 1):
            blocks.append(Block(b_start, b_end, task.id, task.name, index, len(placed), in_focus,
                                _why(task, planned, factor, in_focus, day)))
    blocks.sort(key=lambda b: b.start)
    planned_total = sum(b.minutes for b in blocks)
    if dropped and any(d.code == "no_room" for d in dropped):
        warnings.append("The day is full: " + ", ".join(d.task.name for d in dropped if d.code == "no_room")
                        + " does not fit. Move it, shorten it, or free time.")
    return Plan(day, window, blocks, todays, protected, dropped, free_min, planned_total, warnings,
                rules_used(profile))
