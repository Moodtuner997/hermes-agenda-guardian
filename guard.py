"""pre_tool_call: ask a human before an agent tool changes the calendar source by a side road.

Hermes offers every tool call to the ``pre_tool_call`` hooks. For the four tools that can reach this plugin's
storage (``terminal``, ``execute_code``, ``write_file``, ``patch``) the guard recognises the obvious roads to the
calendar source or to the plugin's own folders and answers with a directive: ``approve`` (Hermes' own human gate,
one rule per exact command, never a plugin-wide "always") or, in a cron run where nobody can answer, ``block``.

It is not a security boundary. A command that hides what it does (base64, a path built in pieces, another
interpreter) is not recognised, and the agent's terminal already runs under Hermes' approvals; the guard closes the
obvious roads and puts a human on the one that would persist a program run at every plan. It only matches: it
stores nothing, reads no config (a slow ``pre_tool_call`` is blocked by Hermes), and any error lets the call through.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from . import commands
from .core import in_cron_session
from .texts import tr

# The tool arguments that carry text able to name a command, a program or a path.
FIELDS = {"terminal": ("command", "workdir"), "execute_code": ("code",), "write_file": ("path",),
          "patch": ("path", "patch")}

_CLI = re.compile(r"\b(?:hermes[\w.]*|main\.py)\b[^;&|\n]*?\bguardian\b([^;&|\n]*)", re.I)
_API = re.compile(r"\b(?:apply_setting|set_rules|setup_auto|save_profile)\b|agenda_guardian")
_HOME = re.compile(r"(?:plugin-data|plugins)[\s/]+agenda[-_]guardian|guardian\.db", re.I)
_QUOTES = re.compile(r"[\"'`,\[\]()]")  # a python argv list reads like a command line once these are gone


def _plain(raw: str) -> str:
    return " ".join(_QUOTES.sub(" ", raw.replace("\\", "/")).split())


def route(plain: str) -> str | None:
    """Which obvious road the text takes to the calendar source, or None."""
    for found in _CLI.finditer(plain):
        if commands.sets_calendar(found.group(1).strip()):
            return "calendar"
    if _API.search(plain):
        return "code"
    if _HOME.search(plain):
        return "storage"
    return None


def check(tool_name: str, args: Any) -> dict | None:
    """The ``pre_tool_call`` directive for this call, or None to let it through."""
    fields = FIELDS.get(tool_name)
    if not fields or not isinstance(args, dict):
        return None
    raw = "\n".join(args[field] for field in fields if isinstance(args.get(field), str))
    plain = _plain(raw)
    road = route(plain)
    if road is None:
        return None
    if in_cron_session():  # nobody to ask: refuse, whatever approvals.cron_mode says
        return {"action": "block", "message": tr("en", "guard_cron")}
    shown = raw.strip()[:300]
    message = "\n".join(tr(lang, "guard_ask", tool=tool_name, what=tr(lang, f"guard_{road}"), shown=shown)
                        for lang in ("en", "fr"))
    return {"action": "approve", "message": message,
            "rule_key": f"agenda-guardian:{road}:{hashlib.sha256(plain.encode('utf-8')).hexdigest()[:12]}"}
