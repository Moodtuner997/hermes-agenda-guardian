"""The /day slash command and the `hermes day` CLI: text in, text out."""

from __future__ import annotations

import re
import shlex

from .core import Guardian, UserError, parse_day, parse_minutes

HELP = """/day setup                         the rules to answer (work hours, focus, durations, calendar)
/day set key=value ...             answer them, e.g. /day set work_hours=09:00-17:30 calendar=google
/day add "name" 45m [cat=admin] [p=1] [due=fri]   a task with YOUR estimate
/day list                          open tasks
/day plan [today|tomorrow|2026-11-12]   the plan, each block with its reason
/day now                           what to do right now
/day done <# or name> <real minutes>    log the real time (this calibrates the plan)
/day drop <# or name>              forget a task
/day brief                         the morning brief (today, or tomorrow after work hours)"""

_DURATION = re.compile(r"^\d+(h(\d+)?|m|min)?$|^\d+h\d*m?$", re.I)


def _tokens(raw: str) -> list[str]:
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError as exc:
        raise UserError(f"unbalanced quote in the command ({exc})")
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in tokens]


def _add(guardian: Guardian, args: list[str]) -> str:
    minutes, category, priority, due, words = None, "", 2, None, []
    for token in args:
        key, sep, value = token.partition("=")
        if sep and key.lower() in ("cat", "category"):
            category = value
        elif sep and key.lower() in ("p", "priority"):
            if not value.isdigit():
                raise UserError("p= must be 1, 2 or 3")
            priority = int(value)
        elif sep and key.lower() == "due":
            due = parse_day(value, guardian.now().date())
        elif minutes is None and _DURATION.match(token) and words:
            minutes = parse_minutes(token)
        else:
            words.append(token)
    return guardian.add(" ".join(words), minutes, category, priority, due)


def run(guardian: Guardian, raw: str) -> str:
    try:
        tokens = _tokens(raw or "")
        if not tokens or tokens[0] in ("help", "-h", "--help"):
            return HELP
        command, args = tokens[0].lower(), tokens[1:]
        if command == "setup":
            return guardian.setup_text()
        if command == "set":
            pairs = []
            for token in args:
                key, sep, value = token.partition("=")
                if not sep:
                    raise UserError(f"'{token}' is not key=value. Example: /day set buffer_min=10")
                pairs.append((key, value))
            return guardian.set_rules(pairs)
        if command == "add":
            return _add(guardian, args)
        if command in ("list", "ls", "tasks"):
            return guardian.tasks_text()
        if command == "plan":
            return guardian.plan_text(args[0] if args else "")
        if command == "now":
            return guardian.now_text()
        if command == "done":
            if not args:
                raise UserError("/day done <# or name> <real minutes>")
            minutes = parse_minutes(args[-1]) if len(args) > 1 and _DURATION.match(args[-1]) else None
            ref = " ".join(args[:-1] if minutes is not None else args)
            return guardian.done(ref, minutes)
        if command in ("drop", "rm"):
            if not args:
                raise UserError("/day drop <# or name>")
            return guardian.drop(" ".join(args))
        if command == "brief":
            return guardian.brief_text()
        return f"Unknown command '{command}'.\n{HELP}"
    except UserError as exc:
        return f"! {exc}"
