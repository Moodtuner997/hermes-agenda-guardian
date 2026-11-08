"""The user's planning rules. Every rule remembers whether the user set it or it is still a default,
so a plan can say where each constraint comes from."""

from __future__ import annotations

import copy
import os
import re
import shlex
from datetime import date
from pathlib import Path

from .texts import tr

DEFAULTS: dict = {
    "language": "en",
    "timezone": "",
    "work_hours": ["09:00", "18:00"],
    "workdays": [1, 2, 3, 4, 5],
    "protected": [{"name": "lunch", "start": "12:30", "end": "13:30"}],
    "focus": [{"start": "09:00", "end": "11:30"}],
    "buffer_min": 10,
    "max_block_min": 50,
    "break_min": 10,
    "max_tasks_per_day": 3,
    "calendar": {"type": "none"},
    "categories": {},
    "_set": {},
}

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7,
         "lun": 1, "mar": 2, "mer": 3, "jeu": 4, "ven": 5, "sam": 6, "dim": 7}
_INT_BOUNDS = {"buffer_min": (0, 60), "max_block_min": (15, 120), "break_min": (0, 30), "max_tasks_per_day": (1, 10)}

KEYS = ("language", "timezone", "work_hours", "workdays", "protected", "focus", "buffer_min", "max_block_min",
        "break_min", "max_tasks_per_day", "calendar", "category")


def new_profile() -> dict:
    return copy.deepcopy(DEFAULTS)


def merged(stored: dict | None) -> dict:
    profile = new_profile()
    for key, value in (stored or {}).items():
        profile[key] = value
    return profile


def clock(text: str, lang: str = "en") -> str:
    match = _HHMM.match(text.strip())
    if not match:
        raise ValueError(tr(lang, "bad_time", text=text))
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def minutes_of(text: str) -> int:
    hours, minutes = clock(text).split(":")
    return int(hours) * 60 + int(minutes)


def _range(text: str, lang: str = "en") -> tuple[str, str]:
    parts = text.split("-")
    if len(parts) != 2:
        raise ValueError(tr(lang, "bad_range", text=text))
    start, end = clock(parts[0], lang), clock(parts[1], lang)
    if minutes_of(end) <= minutes_of(start):
        raise ValueError(tr(lang, "range_backwards", text=text))
    return start, end


def _weekdays(text: str, lang: str = "en") -> list[int]:
    days: set[int] = set()
    for part in text.lower().replace(" ", "").split(","):
        if "-" in part:
            first, last = (_one_day(p, lang) for p in part.split("-", 1))
            span = range(first, last + 1) if first <= last else list(range(first, 8)) + list(range(1, last + 1))
            days.update(span)
        elif part:
            days.add(_one_day(part, lang))
    if not days:
        raise ValueError(tr(lang, "workdays_empty"))
    return sorted(days)


def _one_day(token: str, lang: str = "en") -> int:
    if token.isdigit() and 1 <= int(token) <= 7:
        return int(token)
    if token[:3] in _DAYS:
        return _DAYS[token[:3]]
    raise ValueError(tr(lang, "bad_weekday", text=token))


def _calendar(text: str, lang: str = "en") -> dict:
    text = text.strip()
    if text in ("none", "off", ""):
        return {"type": "none"}
    if text == "google":
        return {"type": "google"}
    kind, _, rest = text.partition(":")
    if kind in ("ics", "file") and rest:
        if not rest.startswith(("http://", "https://")):
            # A cron script or the gateway does not run in the folder the rule was typed in.
            rest = str(Path(rest).expanduser().resolve())
        return {"type": kind, "path": rest}
    if kind == "cmd" and rest:
        argv = [a[1:-1] if len(a) > 1 and a[0] == a[-1] and a[0] in "\"'" else a
                for a in shlex.split(rest, posix=os.name != "nt")]
        if not argv:
            raise ValueError(tr(lang, "cmd_needs"))
        return {"type": "command", "argv": argv}
    raise ValueError(tr(lang, "bad_calendar"))


def normal_key(key: str) -> str:
    """The name a setting is stored under, however the key was typed (case, dashes, outer spaces)."""
    return key.strip().lower().replace("-", "_")


def apply_setting(profile: dict, key: str, value: str, today: date, *, from_tool: bool = False) -> str:
    """Set one rule from text; returns a confirmation line. Raises ValueError on bad input.
    ``from_tool``: the call comes from an agent tool, so the calendar source (which names a program or an address
    that is run or read on every plan) stays the user's own: only their typed command may set it."""
    key = normal_key(key)
    value = value.strip()
    lang = profile.get("language", "en")
    if from_tool and key == "calendar":
        raise ValueError(tr(lang, "calendar_user_only"))
    if key == "language":
        if value not in ("en", "fr"):
            raise ValueError(tr(lang, "language_values"))
        profile["language"] = value
    elif key == "timezone":
        if value:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(value)
            except Exception:
                raise ValueError(tr(lang, "unknown_tz", text=value))
        profile["timezone"] = value
    elif key == "work_hours":
        profile["work_hours"] = list(_range(value, lang))
    elif key == "workdays":
        profile["workdays"] = _weekdays(value, lang)
    elif key == "protected":
        items = []
        if value.lower() != "none":
            for item in value.split(","):
                name, sep, span = item.partition("@")
                if not sep or not name.strip():
                    raise ValueError(tr(lang, "protected_form"))
                start, end = _range(span, lang)
                items.append({"name": name.strip(), "start": start, "end": end})
        profile["protected"] = items
    elif key == "focus":
        items = []
        if value.lower() != "none":
            for item in value.split(","):
                start, end = _range(item, lang)
                items.append({"start": start, "end": end})
        profile["focus"] = items
    elif key in _INT_BOUNDS:
        low, high = _INT_BOUNDS[key]
        try:
            number = int(value)
        except ValueError:
            raise ValueError(tr(lang, "int_needed", key=key, low=low, high=high))
        if not low <= number <= high:
            raise ValueError(tr(lang, "int_range", key=key, low=low, high=high))
        profile[key] = number
    elif key == "calendar":
        profile["calendar"] = _calendar(value, lang)
    elif key == "category":
        name, sep, minutes = value.partition(":")
        name = name.strip().lower()
        if not sep or not name:
            raise ValueError(tr(lang, "category_form"))
        if minutes.strip().lower() == "none":
            profile["categories"].pop(name, None)
        else:
            try:
                number = int(minutes)
            except ValueError:
                raise ValueError(tr(lang, "category_whole"))
            if not 5 <= number <= 480:
                raise ValueError(tr(lang, "category_range"))
            profile["categories"][name] = number
        key = f"category:{name}"
    else:
        raise ValueError(tr(lang, "unknown_setting", key=key, known=", ".join(KEYS)))
    profile["_set"][key] = today.isoformat()
    return f"{key} = {value}"


def is_set(profile: dict, key: str) -> bool:
    return key in profile.get("_set", {})


def source_of(profile: dict, key: str) -> str:
    when = profile.get("_set", {}).get(key)
    lang = profile.get("language", "en")
    if not when:
        return tr(lang, "set_default")
    if when.startswith("auto:"):
        return tr(lang, "set_auto", when=when[5:])
    return tr(lang, "set_by_you", when=when)
