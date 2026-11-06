"""The /day slash command and the `hermes guardian` CLI: text in, text out."""

from __future__ import annotations

import re
import shlex

from .core import Guardian, UserError, parse_day, parse_minutes
from .texts import tr

_DURATION = re.compile(r"^\d+(h(\d+)?|m|min)?$|^\d+h\d*m?$", re.I)


def _tokens(raw: str, lang: str) -> list[str]:
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError as exc:
        raise UserError(tr(lang, "quote", why=exc))
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in tokens]


def _add(guardian: Guardian, args: list[str]) -> str:
    lang = guardian.lang()
    minutes, category, priority, due, words = None, "", 2, None, []
    for token in args:
        key, sep, value = token.partition("=")
        if sep and key.lower() in ("cat", "category"):
            category = value
        elif sep and key.lower() in ("p", "priority"):
            if not value.isdigit():
                raise UserError(tr(lang, "p_value"))
            priority = int(value)
        elif sep and key.lower() == "due":
            due = parse_day(value, guardian.now().date(), lang)
        elif minutes is None and _DURATION.match(token) and words:
            minutes = parse_minutes(token, lang)
        else:
            words.append(token)
    return guardian.add(" ".join(words), minutes, category, priority, due)


def run(guardian: Guardian, raw: str) -> str:
    lang = "en"
    try:
        lang = guardian.lang()
        tokens = _tokens(raw or "", lang)
        if not tokens or tokens[0] in ("help", "-h", "--help"):
            return tr(lang, "help")
        command, args = tokens[0].lower(), tokens[1:]
        if command == "setup":
            return guardian.setup_auto() if args and args[0].lower() == "auto" else guardian.setup_text()
        if command == "set":
            pairs = []
            for token in args:
                key, sep, value = token.partition("=")
                if not sep:
                    raise UserError(tr(lang, "key_value", token=token))
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
                raise UserError(tr(lang, "done_usage"))
            minutes = parse_minutes(args[-1], lang) if len(args) > 1 and _DURATION.match(args[-1]) else None
            ref = " ".join(args[:-1] if minutes is not None else args)
            return guardian.done(ref, minutes)
        if command in ("drop", "rm"):
            if not args:
                raise UserError(tr(lang, "drop_usage"))
            return guardian.drop(" ".join(args))
        if command == "brief":
            return guardian.brief_text()
        if command == "nudge":
            return guardian.nudge_text() or tr(lang, "nothing_now")
        if command == "cron":
            action = args[0].lower() if args else "status"
            if action == "on":
                rest = args[1:]
                deliver = next((a.partition("=")[2] for a in rest if a.startswith("deliver=")), "")
                at_time = next((a for a in rest if not a.startswith("deliver=")), "")
                return guardian.schedule(at_time, deliver)
            if action == "off":
                return guardian.unschedule()
            if action == "status":
                return guardian.schedule_status()
            raise UserError(tr(lang, "cron_usage"))
        return tr(lang, "unknown_cmd", command=command) + "\n" + tr(lang, "help")
    except UserError as exc:
        return f"! {exc}"
