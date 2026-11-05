"""agenda-guardian: a deterministic day planner for Hermes.

Plans from the durations you estimate, corrected by the durations you actually took, around the meetings
of any calendar source, inside rules you wrote down yourself. It never writes to a calendar and never calls
a model: ``/day`` (slash), ``hermes day`` (CLI) and five tools for the agent share one core.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import commands
from .core import Guardian, UserError, parse_day, parse_minutes


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


_CTX: Any = None


def _cron(args: dict) -> dict:
    """The cronjob tool, called the way a plugin may: through the registry, so Hermes' own checks apply."""
    if _CTX is None:
        raise UserError("Scheduling needs a running Hermes session: send /day cron on from a chat.")
    reply = _CTX.dispatch_tool("cronjob_manage", args)
    try:
        return json.loads(reply) if isinstance(reply, str) else dict(reply)
    except (TypeError, ValueError):
        return {"error": f"unreadable answer from cronjob_manage: {str(reply)[:200]}"}


def _guardian(*, with_cron: bool = True, data_dir: str = "", home: str = "") -> Guardian:
    """Built per call: the active profile (and so the data folder) can change between calls. The cron scripts
    pass the folders they were written for, so they never depend on the scheduler's environment."""
    if data_dir:
        return Guardian(Path(data_dir) / "guardian.db", Path(home) if home else _home(),
                        plugin_dir=Path(__file__).resolve().parent)
    try:
        from plugins.plugin_storage import plugin_data_dir

        data = Path(plugin_data_dir("agenda-guardian"))
    except Exception:
        data = _home() / "plugin-data" / "agenda-guardian"
        data.mkdir(parents=True, exist_ok=True)
    return Guardian(data / "guardian.db", _home(), cron=_cron if with_cron else None,
                    plugin_dir=Path(__file__).resolve().parent)


def scheduled_text(what: str, data_dir: str = "", home: str = "") -> str:
    """Entry point of the two cron scripts: the morning brief, or the reminder check ("" = say nothing)."""
    guardian = _guardian(with_cron=False, data_dir=data_dir, home=home)
    return guardian.brief_text() if what == "brief" else guardian.nudge_text()


def _slash(raw_args: str = "", **_: Any) -> str:
    return commands.run(_guardian(), raw_args)


def _cli_setup(parser: Any) -> None:
    import argparse

    parser.add_argument("rest", nargs=argparse.REMAINDER, help="setup | set k=v | add | list | plan | now | done | brief")


def _cli_run(args: Any) -> None:
    import shlex

    print(commands.run(_guardian(with_cron=False), " ".join(shlex.quote(a) for a in (getattr(args, "rest", None) or ["help"]))))


# --- tools: the same core, structured arguments, JSON out -------------------------------------------------

def _tool(fn):
    def handler(args: dict | None = None, **_: Any) -> str:
        try:
            return json.dumps({"ok": True, **fn(_guardian(), args or {})}, ensure_ascii=False)
        except UserError as exc:
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        except Exception as exc:  # a tool must answer, never raise into the agent loop
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)

    return handler


def _t_plan(g: Guardian, a: dict) -> dict:
    return {"plan": g.plan_text(str(a.get("day", "")))}


def _t_tasks(g: Guardian, a: dict) -> dict:
    return {"tasks": g.tasks_text()}


def _t_add(g: Guardian, a: dict) -> dict:
    minutes = a.get("minutes")
    due = parse_day(str(a["due"]), g.now().date()) if a.get("due") else None
    return {"message": g.add(str(a.get("name", "")), int(minutes) if minutes is not None else None,
                             str(a.get("category", "")), int(a.get("priority", 2)), due)}


def _t_done(g: Guardian, a: dict) -> dict:
    minutes = a.get("actual_minutes")
    return {"message": g.done(str(a.get("task", "")), int(minutes) if minutes is not None else None)}


def _t_setup(g: Guardian, a: dict) -> dict:
    settings = a.get("settings") or {}
    if not settings:
        return {"questions": g.setup_text()}
    return {"result": g.set_rules([(str(k), str(v)) for k, v in settings.items()])}


def _t_schedule(g: Guardian, a: dict) -> dict:
    action = str(a.get("action", "status")).lower()
    if action == "on":
        return {"message": g.schedule(str(a.get("time", "")), str(a.get("deliver", "")))}
    if action == "off":
        return {"message": g.unschedule()}
    return {"message": g.schedule_status()}


def _schema(name: str, description: str, properties: dict, required: list | None = None) -> dict:
    params: dict = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


_S = {"type": "string"}
_TOOLS = [
    ("day_setup", _t_setup, _schema(
        "day_setup",
        "Agenda guardian onboarding. With no arguments it returns the planning questions with the user's current "
        "answers. With 'settings' (a map such as {\"work_hours\": \"09:00-17:30\", \"category\": \"admin:20\"}) it "
        "saves the user's answers. Ask the user, never invent their answers.",
        {"settings": {"type": "object", "additionalProperties": _S,
                      "description": "rule name to value; keys: work_hours, workdays, protected, focus, "
                                     "max_block_min, break_min, buffer_min, max_tasks_per_day, calendar, "
                                     "category (name:minutes), language, timezone"}})),
    ("day_add_task", _t_add, _schema(
        "day_add_task", "Add a task with the USER's own time estimate in minutes (ask for it; the planner learns "
        "from the gap between estimate and real time).",
        {"name": _S, "minutes": {"type": "integer"}, "category": _S,
         "priority": {"type": "integer", "enum": [1, 2, 3]}, "due": {**_S, "description": "today, tomorrow, +3, fri or YYYY-MM-DD"}},
        ["name"])),
    ("day_plan", _t_plan, _schema(
        "day_plan", "The day plan: blocks placed around calendar events inside the user's rules, each with its "
        "reason, plus what does not fit. Read-only.", {"day": {**_S, "description": "today (default), tomorrow, +N, fri, YYYY-MM-DD"}})),
    ("day_done", _t_done, _schema(
        "day_done", "Mark a task done and record how many minutes it really took. Ask the user for the real time.",
        {"task": {**_S, "description": "task number or part of its name"}, "actual_minutes": {"type": "integer"}},
        ["task"])),
    ("day_tasks", _t_tasks, _schema("day_tasks", "List the open tasks with their estimates.", {})),
    ("day_schedule", _t_schedule, _schema(
        "day_schedule", "Turn the proactive part on or off: a morning brief on workdays and a reminder when a "
        "block starts or ends. Creates two script-only cron jobs (no model call). Ask the user before 'on'.",
        {"action": {**_S, "enum": ["on", "off", "status"]}, "time": {**_S, "description": "HH:MM, brief time"},
         "deliver": {**_S, "description": "where to send, e.g. telegram; omit for this chat"}}, ["action"])),
]


def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx
    ctx.register_command("day", _slash, description="Plan your day from your rules, estimates and calendar",
                         args_hint="setup | set | add | plan | now | done | brief")
    ctx.register_cli_command("day", "Plan your day from your rules, estimates and calendar", _cli_setup, _cli_run)
    for name, fn, schema in _TOOLS:
        ctx.register_tool(name=name, toolset="agenda-guardian", schema=schema, handler=_tool(fn),
                          description=schema["description"], emoji="🗓")
