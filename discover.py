"""What the Hermes profile already knows, read without a model call and without opening any secret:
the language, the time zone, whether the Google Workspace skill is installed and signed in (existence of its
token file only, never its content), and the reminders already scheduled (name and schedule only)."""

from __future__ import annotations

import json
import locale
import os
import re
from pathlib import Path

GOOGLE_SCRIPT = Path("skills") / "productivity" / "google-workspace" / "scripts" / "google_api.py"
GOOGLE_TOKEN = "google_token.json"
OUR_JOBS = ("agenda-guardian-brief", "agenda-guardian-nudge")


def _windows_ui_language() -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes

        return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except Exception:
        return ""


def language(home: Path) -> str:
    """"fr", "en" or "" when nothing says. Hermes' own config first, then the environment, then the system."""
    config = _config_value(home, "language") or _config_value(home, "locale")
    candidates = [config, os.environ.get("LC_ALL", ""), os.environ.get("LC_MESSAGES", ""),
                  os.environ.get("LANGUAGE", ""), os.environ.get("LANG", ""), _windows_ui_language()]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except Exception:
        pass
    for value in candidates:
        code = value.strip().lower()[:2]
        if code in ("fr", "en"):
            return code
    return ""


def _config_value(home: Path, key: str) -> str:
    """A top-level ``key: value`` line of config.yaml (no YAML library needed for one flat key)."""
    try:
        text = (home / "config.yaml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(rf"^{re.escape(key)}:[ \t]*['\"]?([^'\"#\r\n]*)", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def timezone(home: Path) -> str:
    return _config_value(home, "timezone")


def google_state(home: Path) -> str:
    """"ready" (skill and sign-in file present), "skill_only" or "absent"."""
    if not (home / GOOGLE_SCRIPT).exists():
        return "absent"
    return "ready" if (home / GOOGLE_TOKEN).exists() else "skill_only"


def other_jobs(home: Path) -> list[tuple[str, str]]:
    """(name, schedule) of the enabled reminders that are not ours. Prompts are never read into the result."""
    try:
        data = json.loads((home / "cron" / "jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    found = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict) or job.get("enabled") is False or job.get("name") in OUR_JOBS:
            continue
        schedule = job.get("schedule_display") or job.get("schedule") or ""
        if isinstance(schedule, dict):
            schedule = schedule.get("display") or schedule.get("expr") or ""
        found.append((str(job.get("name") or job.get("id") or ""), str(schedule)))
    return found
