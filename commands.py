"""The /day slash command and the `hermes guardian` CLI: text in, text out."""

from __future__ import annotations

import re
import shlex

from .core import Guardian, UserError, parse_day, parse_minutes
from .profile import normal_key
from .texts import tr

_DURATION = re.compile(r"^\d+(h(\d+)?|m|min)?$|^\d+h\d*m?$", re.I)

# Commands that need no format: the dispatcher answers them. After /day anything else is a request in plain words
# (a sentence, a fragment, or a syntax nobody should have to learn): the gateway hook hands it to the agent.
# One exception, see ``sets_calendar``: the commands that fix the calendar source are answered by the dispatcher too.
DIRECT = frozenset({"help", "list", "ls", "tasks", "plan", "now", "brief", "nudge", "ok", "confirm", "undo", "write",
                    "cron"})
KNOWN = DIRECT | frozenset({"setup", "set", "add", "done", "drop", "rm", "kind", "habit", "propose", "took"})


def free_text(raw: str) -> str:
    """What follows /day when it is not one of the format-free commands: the request to hand to the agent (else "")."""
    words = (raw or "").split()
    if not words or words[0].lower().lstrip("-") in DIRECT or sets_calendar(raw):
        return ""
    return " ".join(words)


def _tokens(raw: str, lang: str) -> list[str]:
    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError as exc:
        raise UserError(tr(lang, "quote", why=exc))
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in tokens]


def sets_calendar(raw: str) -> bool:
    """``set ... calendar=<source>`` and ``setup auto`` (which adopts a Google calendar) typed by the user.
    An agent tool never sets the calendar source (it names a program or an address run on every plan), so these two
    are answered by the dispatcher itself: through the agent they would hit the same refusal. Keys are read the way
    ``profile.apply_setting`` reads them, so no spelling slips past this test into the agent's hands."""
    try:
        tokens = _tokens(raw or "", "en")
    except UserError:
        tokens = (raw or "").split()
    head = tokens[0].lower() if tokens else ""
    if head == "set":
        return any(normal_key(token.partition("=")[0]) == "calendar" for token in tokens[1:] if "=" in token)
    return head == "setup" and len(tokens) > 1 and tokens[1].lower() == "auto"


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


def _split(args: list[str]) -> tuple[dict[str, str], list[str]]:
    """key=value tokens and the plain words, in order."""
    named, plain = {}, []
    for token in args:
        key, sep, value = token.partition("=")
        if sep and key.isidentifier():
            named[key.lower()] = value
        else:
            plain.append(token)
    return named, plain


def _kind(guardian: Guardian, args: list[str]) -> str:
    lang = guardian.lang()
    named, plain = _split(args)
    if not plain:
        return guardian.kinds_view()["text"]
    if plain[-1].lower() == "none":
        return guardian.kind_remove(" ".join(plain[:-1]))["text"]
    name = " ".join(plain).lower()
    old = next((k for k in guardian.kinds_view()["kinds"] if k["name"] == name), None)
    if "real" in named:
        real = parse_minutes(named["real"], lang)
    elif old:
        real = old["real_minutes"]
    else:
        raise UserError(tr(lang, "kind_real_needed", name=name))
    before = parse_minutes(named["before"], lang) if "before" in named else (old["before_minutes"] if old else 0)
    after = parse_minutes(named["after"], lang) if "after" in named else (old["after_minutes"] if old else 0)
    days = named.get("days", ",".join(map(str, old["weekdays"])) if old else "")
    return guardian.kind_set(name, real, before, after, named.get("window", ""), days)["text"]


def _habit(guardian: Guardian, args: list[str]) -> str:
    lang = guardian.lang()
    if not args:
        return guardian.habits_view()["text"]
    if args[0].lower() in ("rm", "drop", "del") and len(args) == 2 and args[1].lstrip("#").isdigit():
        return guardian.habit_remove(int(args[1].lstrip("#")))["text"]
    if len(args) < 3:
        raise UserError(tr(lang, "habit_usage"))
    return guardian.habit_add(args[0], args[1], " ".join(args[2:]))["text"]


def _propose(guardian: Guardian, args: list[str]) -> str:
    lang = guardian.lang()
    named, plain = _split(args)
    if not plain:
        raise UserError(tr(lang, "propose_usage"))
    counted = len(plain) > 1 and plain[-1].isdigit()
    name = " ".join(plain[:-1] if counted else plain)
    today = guardian.now().date()
    first = parse_day(named["from"], today, lang) if "from" in named else None
    last = parse_day(named["to"], today, lang) if "to" in named else None
    return guardian.propose(name, int(plain[-1]) if counted else 1, first, last, named.get("days", ""))["text"]


def run(guardian: Guardian, raw: str) -> str:
    lang = "en"
    try:
        lang = guardian.lang()
        tokens = _tokens(raw or "", lang)
        if not tokens:
            return tr(lang, "help")
        if tokens[0] in ("help", "-h", "--help"):
            return tr(lang, "help_full" if len(tokens) > 1 and tokens[1].lower() in ("all", "tout", "full") else "help")
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
        if command == "kind":
            return _kind(guardian, args)
        if command == "habit":
            return _habit(guardian, args)
        if command == "propose":
            return _propose(guardian, args)
        if command in ("ok", "confirm"):
            named, plain = _split(args)
            if not plain or not plain[0].lstrip("#").isdigit():
                raise UserError(tr(lang, "ok_usage"))
            return guardian.confirm(int(plain[0].lstrip("#")), named.get("days", ""))["text"]
        if command == "undo":
            return guardian.undo(args[0] if args else "last")["text"]
        if command == "took":
            if len(args) < 2:
                raise UserError(tr(lang, "took_usage"))
            return guardian.took(" ".join(args[:-1]), parse_minutes(args[-1], lang))["text"]
        if command == "write":
            action = args[0].lower() if args else "status"
            if action in ("on", "off"):
                return guardian.set_write(action == "on")["text"]
            return tr(lang, "write_on" if guardian.write_enabled() else "write_off")
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
        return tr(lang, "unknown_cmd", command=command)
    except UserError as exc:
        return f"! {exc}"
