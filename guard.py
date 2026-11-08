"""pre_tool_call: ask a human before an agent tool changes the calendar source by a side road.

Hermes offers every tool call to the ``pre_tool_call`` hooks. For the four tools that can reach this plugin's
storage (``terminal``, ``execute_code``, ``write_file``, ``patch``) the guard recognises the obvious roads to the
calendar source or to the plugin's own folders and answers with a directive: ``approve`` (Hermes' own human gate,
one rule per exact call, never a plugin-wide "always") or, in a cron run where nobody can answer, ``block``.

It is not a security boundary. A command that hides what it does (base64, a path built in pieces, another
interpreter, a script written first and run later) is not recognised, and the agent's terminal already runs under
Hermes' approvals; the guard closes the obvious roads and puts a human on the one that would persist a program run
at every plan. It only matches: it stores nothing and reads no config. Hermes blocks a ``pre_tool_call`` that runs
past its timeout and ``re`` holds the GIL, so every quantifier below is bounded (checked on 260 KB inputs), and any
error lets the call through.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import commands
from .core import in_cron_session
from .texts import tr

# The tool arguments that carry text able to name a command, a program or a path (scanned).
FIELDS = {"terminal": ("command", "workdir"), "execute_code": ("code",), "write_file": ("path",),
          "patch": ("path", "patch")}
# What would be written: shown to the human, not scanned (a script written first and run later is a documented limit).
CONTENT = {"write_file": ("content",), "patch": ("old_string", "new_string")}

# ``{0,40}+`` is possessive (Python 3.11+, as Hermes requires): without it "hermes.hermes.hermes. ..." backtracks 40 ways
# at each of its starts and the match becomes cubic.
_CLI = re.compile(r"\b(?:hermes[\w.]{0,40}+|main\.py)\b[^;&|]{0,200}?\bguardian\b([^;&|]{0,600})", re.I)
_CODE = re.compile(r"\b(?:apply_setting|set_rules|save_profile|setup_auto)\b|agenda_guardian", re.I)
_HOME = re.compile(r"(?:(?<![\w-])(?:plugin-data|plugins|scripts)[\s/]{1,8}agenda[-_]guardian|guardian\.db)", re.I)
_CONT = re.compile(r"[\\^`]\r?\n\s*")  # a line continuation: bash \, cmd ^, PowerShell `
_ESCAPE = re.compile(r"[\\^](?=\S)")  # bash \ and cmd.exe ^ before a character are dropped: calendar\=x is calendar=x
_SHELL = re.compile(r"[\"'`]")  # a shell strips quotes: 'calendar'=x is calendar=x
_LISTS = re.compile(r"[,\[\]()]")  # a python argv list reads like a command line once these are gone
_ARGV = re.compile(r"[\"'`,\[\]()]")  # the same, for quotes that separate words
SHOW, WINDOW = 300, 500  # characters of a call shown whole; longest matched part shown in a long call


def _squash(text: str) -> str:
    return " ".join(text.split())


def readings(raw: str) -> list[str]:
    """The text as a shell reads it, as a python argv list reads it, and, when it has a one-character escape, with
    the escapes dropped (an added reading: ``plugins\\agenda-guardian`` must stay readable as a Windows path)."""
    joined = _CONT.sub(" ", raw)
    flat = joined.replace("\\", "/")
    found = [_squash(_LISTS.sub(" ", _SHELL.sub("", flat))), _squash(_ARGV.sub(" ", flat))]
    if _ESCAPE.search(joined):
        found.append(_squash(_LISTS.sub(" ", _SHELL.sub("", _ESCAPE.sub("", joined)))))
    return found


def scan(plain: str) -> tuple[str, list[tuple[int, int]]] | None:
    """The first obvious road this reading takes to the calendar source, with where it matched, or None."""
    low = plain.lower()
    if "guardian" in low:
        hits = [found.span() for found in _CLI.finditer(plain)
                if found.group(1).strip()[:3].lower() == "set" and commands.sets_calendar(found.group(1).strip())]
        if hits:
            return "calendar", hits
    code = list(_CODE.finditer(plain))
    if code and ("calendar" in low or any(h.group().lower() in ("setup_auto", "agenda_guardian") for h in code)):
        return "code", [h.span() for h in code]
    home = [h.span() for h in _HOME.finditer(plain)]
    return ("storage", home) if home else None


def route(raw: str) -> tuple[str, str, list[tuple[int, int]]] | None:
    """(road, reading, where) for the first reading that takes an obvious road, or None."""
    for plain in readings(raw):
        found = scan(plain)
        if found:
            return found[0], plain, found[1]
    return None


def _shown(raw: str, plain: str, spans: list[tuple[int, int]]) -> str:
    """The call as the human sees it: whole when short, else its start and then every part that matched, so that
    nothing that matters hides past the cut."""
    raw = raw.strip()
    if len(raw) <= SHOW:
        return raw
    windows: list[list[int]] = []
    for start, end in spans[:6]:
        low, high = max(0, start - 60), min(len(plain), end + 200, max(0, start - 60) + WINDOW)
        if windows and low <= windows[-1][1]:
            windows[-1][1] = max(high, windows[-1][1])
        else:
            windows.append([low, high])
    more = f" […+{len(spans) - 6} more]" if len(spans) > 6 else ""
    return " […] ".join([raw[:100]] + [plain[low:high] for low, high in windows]) + more


def _content(tool_name: str, args: dict) -> str:
    out = ""
    for name in CONTENT.get(tool_name, ()):
        value = args.get(name)
        if isinstance(value, str) and value.strip():
            out += f"\n[{name}] {value.strip()[:200]}" + (" […]" if len(value.strip()) > 200 else "")
    return out


def check(tool_name: str, args: Any) -> dict | None:
    """The ``pre_tool_call`` directive for this call, or None to let it through."""
    fields = FIELDS.get(tool_name)
    if not fields or not isinstance(args, dict):
        return None
    raw = "\n".join(args[field] for field in fields if isinstance(args.get(field), str))
    found = route(raw)
    if found is None:
        return None
    road, plain, spans = found
    if in_cron_session():  # nobody to ask: refuse, whatever approvals.cron_mode says
        return {"action": "block", "message": tr("en", "guard_cron")}
    shown = _shown(raw, plain, spans) + _content(tool_name, args)
    message = "\n".join(tr(lang, "guard_ask", tool=tool_name, what=tr(lang, f"guard_{road}"), shown=shown)
                        for lang in ("en", "fr"))
    # the whole call, content included: an "always" answer covers that exact call and nothing else
    call = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, default=str)
    return {"action": "approve", "message": message,
            "rule_key": f"agenda-guardian:{road}:{hashlib.sha256(call.encode('utf-8')).hexdigest()[:12]}"}
