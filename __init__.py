"""agenda-guardian: a deterministic day planner for Hermes.

Plans from the durations you estimate, corrected by the durations you actually took, around the meetings
of any calendar source, inside rules you wrote down yourself. It also fits activities (sport, a long call) into
the week with reasons drawn from the calendar's history, and writes to a Google calendar only when the user
typed ``/day write on`` and said yes, removing only what it wrote. It never calls a model: ``/day`` (slash),
``hermes guardian`` (CLI) and fifteen tools for the agent share one core. ``/day`` followed by a sentence is
a request in plain words: it goes to the agent, not to the command parser.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import commands
from .core import Guardian, UserError, parse_day, parse_minutes
from .texts import tr


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


_DAY_SENTENCE = re.compile(r"^/day(?:@\w+)?\s+(.+)$", re.I | re.S)


def _plain_words(event: Any = None, **_: Any) -> dict | None:
    """pre_gateway_dispatch: "/day <a sentence>" is a request, not a command. Hand it to the agent as an ordinary
    message (with a pointer to the tools) instead of answering "unknown command" with a wall of syntax."""
    try:
        match = _DAY_SENTENCE.match(str(getattr(event, "text", "") or "").strip())
        request = commands.free_text(match.group(1)) if match else ""
        if request:
            return {"action": "rewrite", "text": tr(_guardian(with_cron=False).lang(), "free_text_prefix") + request}
    except Exception:  # a hook must never stop a message
        pass
    return None


def _cli_setup(parser: Any) -> None:
    import argparse

    parser.add_argument("rest", nargs=argparse.REMAINDER, help="a request in plain words, or: setup | set k=v | add | list | plan | now | done | brief | propose | undo")


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
    due = parse_day(str(a["due"]), g.now().date(), g.lang()) if a.get("due") else None
    return {"message": g.add(str(a.get("name", "")), int(minutes) if minutes is not None else None,
                             str(a.get("category", "")), int(a.get("priority", 2)), due)}


def _t_done(g: Guardian, a: dict) -> dict:
    minutes = a.get("actual_minutes")
    return {"message": g.done(str(a.get("task", "")), int(minutes) if minutes is not None else None)}


def _t_setup(g: Guardian, a: dict) -> dict:
    settings = a.get("settings") or {}
    if a.get("adopt"):
        return {"result": g.setup_auto()}
    if not settings:
        return {"questions": g.setup_text(), "found": g.facts(), "for_agent": tr("en", "agent_hint")}
    return {"result": g.set_rules([(str(k), str(v)) for k, v in settings.items()])}


def _t_schedule(g: Guardian, a: dict) -> dict:
    action = str(a.get("action", "status")).lower()
    if action == "on":
        return {"message": g.schedule(str(a.get("time", "")), str(a.get("deliver", "")))}
    if action == "off":
        return {"message": g.unschedule()}
    return {"message": g.schedule_status()}


def _day(text: Any, g: Guardian) -> Any:
    return parse_day(str(text), g.now().date(), g.lang()) if text else None


def _t_kind(g: Guardian, a: dict) -> dict:
    action = str(a.get("action") or ("set" if a.get("real_minutes") is not None else "list")).lower()
    if action == "list":
        return g.kinds_view()
    if action == "remove":
        return g.kind_remove(str(a.get("name", "")))
    if a.get("real_minutes") is None:
        raise UserError("real_minutes is required: ask the user how long the activity itself really takes.")
    return g.kind_set(str(a.get("name", "")), int(a["real_minutes"]), int(a.get("before_minutes") or 0),
                      int(a.get("after_minutes") or 0), str(a.get("window", "")), str(a.get("days", "")))


def _t_habit(g: Guardian, a: dict) -> dict:
    action = str(a.get("action", "list")).lower()
    if action == "list":
        return g.habits_view()
    if action == "remove":
        return g.habit_remove(int(a.get("id", 0)))
    return g.habit_add(str(a.get("day", "")), str(a.get("hours", "")), str(a.get("label", "")))


def _t_propose(g: Guardian, a: dict) -> dict:
    result = g.propose(str(a.get("activity", "")), int(a.get("count") or 1), _day(a.get("from_day"), g),
                       _day(a.get("to_day"), g), str(a.get("days", "")))
    result["for_agent"] = tr("en", "agent_propose")
    return result


def _t_week_plan(g: Guardian, a: dict) -> dict:
    result = g.week_plan(a.get("activities") or [], _day(a.get("from_day"), g), _day(a.get("to_day"), g))
    result["for_agent"] = tr("en", "agent_week")
    return result


def _t_stage(g: Guardian, a: dict) -> dict:
    result = g.stage(a.get("blocks") or [])
    result["for_agent"] = tr("en", "agent_stage")
    return result


def _t_confirm(g: Guardian, a: dict) -> dict:
    return g.confirm(int(a.get("proposal_id", 0)), str(a.get("days", "")))


def _t_undo(g: Guardian, a: dict) -> dict:
    return g.undo(str(a.get("which", "last")))


def _t_took(g: Guardian, a: dict) -> dict:
    if a.get("actual_minutes") is None:
        raise UserError("actual_minutes is required: ask the user how long it really took.")
    return g.took(str(a.get("session", "")), int(a["actual_minutes"]))


def _t_week(g: Guardian, a: dict) -> dict:
    return g.week_view(_day(a.get("week_of"), g))


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
        "answers, plus what the Hermes profile already shows (time zone, connected calendar, existing reminders): "
        "propose answers from what you know of the user, then ask only to confirm or complete, in their language. "
        "With 'settings' (a map such as {\"work_hours\": \"09:00-17:30\", \"category\": \"admin:20\"}) it saves "
        "the user's answers; with adopt=true it adopts the calendar, language and time zone the profile already has. "
        "Never invent answers.",
        {"adopt": {"type": "boolean"}, "settings": {"type": "object", "additionalProperties": _S,
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
    ("day_kind", _t_kind, _schema(
        "day_kind", "The activity sheet: what one kind of activity (sport, a call block, shopping...) really takes. "
        "ASK the user for each number, never guess: real_minutes (the activity itself, at their honest pace), "
        "before_minutes (getting ready), after_minutes (shower, travel, winding down), window (HH:MM-HH:MM in which "
        "everything must fit) and days (preferred weekdays, e.g. 'mon,thu'). action: set (default when real_minutes "
        "is given), list, remove.",
        {"action": {**_S, "enum": ["set", "list", "remove"]}, "name": _S, "real_minutes": {"type": "integer"},
         "before_minutes": {"type": "integer"}, "after_minutes": {"type": "integer"}, "window": _S, "days": _S})),
    ("day_habit", _t_habit, _schema(
        "day_habit", "Things the user does that are NOT in their calendar (a family dinner every Wednesday evening): "
        "they count as busy when proposing. action: add (day, hours HH:MM-HH:MM, label), list, remove (id).",
        {"action": {**_S, "enum": ["add", "list", "remove"]}, "day": _S, "hours": _S, "label": _S,
         "id": {"type": "integer"}})),
    ("day_propose", _t_propose, _schema(
        "day_propose", "Where could this activity go in the user's week? Reads the Google calendar and its last "
        "eight weeks, returns concrete slots WITH THE REASONS (free time, what the history says about each day, "
        "how heavy the day usually is), the days left out and why, and the questions to ask the user. Writes "
        "NOTHING. Show the reasons to the user, ask the questions (especially what is planned but not in the "
        "calendar), and wait for a clear yes.",
        {"activity": {**_S, "description": "the activity sheet name"}, "count": {"type": "integer"},
         "days": {**_S, "description": "force these weekdays, e.g. 'tue' (the user's explicit wish)"},
         "from_day": {**_S, "description": "today (default), tomorrow, +N, fri, YYYY-MM-DD"},
         "to_day": {**_S, "description": "last day to consider (default: 6 days after from_day)"}},
        ["activity"])),
    ("day_week_plan", _t_week_plan, _schema(
        "day_week_plan", "Place several activities in the user's week in ONE call (sport, client calls, a course...): "
        "each around the calendar events and around the ones placed before it, with its reasons. Pass the numbers the "
        "user gave you, nothing has to be saved first; ask only for what is missing, never guess a number. Writes "
        "NOTHING: tell the plan in plain words, ask the questions listed, wait for a clear yes, then day_confirm.",
        {"activities": {"type": "array", "minItems": 1, "maxItems": 6, "description": "most important first: each "
                        "one is placed around the previous ones", "items": {
                            "type": "object", "additionalProperties": False, "required": ["name"], "properties": {
                                "name": _S, "minutes": {"type": "integer", "description": "the activity itself, in the "
                                                        "user's own figure"},
                                "sessions": {"type": "integer", "description": "how many in the range (default 1)"},
                                "per_day": {"type": "integer", "description": "instead of sessions: this many every "
                                            "allowed day (2 blocks of 2h of a course each day)"},
                                "window": {**_S, "description": "HH:MM-HH:MM in which the whole thing must fit"},
                                "days": {**_S, "description": "weekdays the user asked for, e.g. 'tue,thu'"},
                                "before_minutes": {"type": "integer"}, "after_minutes": {"type": "integer"},
                                "remember": {"type": "boolean", "description": "keep these numbers as the activity's "
                                             "sheet for next time"}}}},
         "from_day": {**_S, "description": "today (default), tomorrow, +N, fri, YYYY-MM-DD"},
         "to_day": {**_S, "description": "last day to consider (default: 6 days after from_day)"}},
        ["activities"])),
    ("day_stage", _t_stage, _schema(
        "day_stage", "Register blocks YOU composed from what the user told you (a fixed appointment, an evening they "
        "spend elsewhere) as a proposal: checked against the calendar, then written and taken back exactly like any "
        "other proposal. Use it instead of any other calendar tool. Writes NOTHING until the user says yes and "
        "day_confirm is called.",
        {"blocks": {"type": "array", "minItems": 1, "maxItems": 40, "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "day", "start", "end"],
            "properties": {"title": _S, "day": {**_S, "description": "today, tomorrow, +N, fri or YYYY-MM-DD"},
                           "start": {**_S, "description": "HH:MM"}, "end": {**_S, "description": "HH:MM"},
                           "why": {**_S, "description": "the user's own reason, shown with the block"}}}}},
        ["blocks"])),
    ("day_confirm", _t_confirm, _schema(
        "day_confirm", "Write a proposal (day_propose, day_week_plan or day_stage) to the user's Google calendar. Call "
        "it ONLY after the user has clearly said yes to this exact proposal in this conversation; never on your own "
        "initiative. It refuses unless the user themselves turned writing on (/day write on). It never touches an "
        "existing event: it only adds events marked as created by this plugin, so /day undo can take them back. "
        "Never write to the calendar with another tool.",
        {"proposal_id": {"type": "integer"}, "days": {**_S, "description": "only these weekdays of the proposal"}},
        ["proposal_id"])),
    ("day_undo", _t_undo, _schema(
        "day_undo", "Take back what this plugin wrote: the last session ('last'), a session number, or 'all'. It can "
        "only remove events this plugin created and still recognises; it never removes anything else.",
        {"which": _S})),
    ("day_took", _t_took, _schema(
        "day_took", "Record how long a finished activity REALLY took (the activity itself). Ask the user; the next "
        "proposal is corrected by their own pace.",
        {"session": {**_S, "description": "session number from the question, or the activity name"},
         "actual_minutes": {"type": "integer"}}, ["session", "actual_minutes"])),
    ("day_week", _t_week, _schema(
        "day_week", "The user's week as the plugin sees it: calendar events, what it wrote, what is proposed and "
        "waiting for a yes. Read-only.", {"week_of": {**_S, "description": "any day of the week; default this week"}})),
    ("day_schedule", _t_schedule, _schema(
        "day_schedule", "Turn the proactive part on or off: a morning brief on workdays and a reminder when a "
        "block starts or ends. Creates two script-only cron jobs (no model call). Ask the user before 'on'.",
        {"action": {**_S, "enum": ["on", "off", "status"]}, "time": {**_S, "description": "HH:MM, brief time"},
         "deliver": {**_S, "description": "where to send, e.g. telegram; omit for this chat"}}, ["action"])),
]


RULES = {
    "en": (
        "agenda-guardian manages the user's agenda. When they talk about fitting activities into their week, "
        "or about their agenda (also when a message starts with /day followed by a sentence):\n"
        "1. If they give the numbers (how long, how many, when), call day_week_plan with ALL the activities at "
        "once. Ask only for what is missing and never guess a number. For one activity with a saved sheet, "
        "day_propose is enough (day_kind saves a sheet).\n"
        "2. Tell the plan in plain words WITH ITS REASONS (taken from their calendar history), the days left out "
        "and why, and ask what is planned that is not in the calendar.\n"
        "3. If they tell you things the planner cannot express (a fixed appointment, an evening spent elsewhere), "
        "build those blocks yourself and register them with day_stage.\n"
        "4. Call day_confirm only after the user clearly said yes to that proposal in this conversation. If "
        "writing is off, tell them to type /day write on themselves; if they would rather not, give the plan as "
        "text and write nothing. NEVER create, move or delete calendar events with any other tool (the Google "
        "Workspace skill, the terminal): they would not be marked, and /day undo could not take them back.\n"
        "5. Never modify or delete an event the user created (priorities, medical appointments, unforeseen "
        "things). Only day_undo removes anything, and only what this plugin wrote.\n"
        "6. After an activity ends, ask how long it really took and record it with day_took.\n"
        "Speak like a person: do not show command syntax unless asked."),
    "fr": (
        "agenda-guardian gère l'agenda de l'utilisateur. Quand il parle de caser des activités dans sa semaine "
        "ou de son agenda (aussi quand un message commence par /day suivi d'une phrase) :\n"
        "1. S'il donne les chiffres (combien de temps, combien de fois, quand), appelle day_week_plan avec "
        "TOUTES les activités d'un coup. Demande seulement ce qui manque et ne devine jamais un chiffre. Pour "
        "une seule activité qui a une fiche, day_propose suffit (day_kind enregistre une fiche).\n"
        "2. Dis le plan en mots simples AVEC SES RAISONS (tirées de l'historique de son agenda), les jours "
        "écartés et pourquoi, et demande ce qui est prévu hors agenda.\n"
        "3. S'il te dit des choses que le planificateur ne sait pas exprimer (un rendez-vous fixe, une soirée "
        "passée ailleurs), compose ces blocs toi-même et enregistre-les avec day_stage.\n"
        "4. N'appelle day_confirm qu'après un oui clair à cette proposition dans cette conversation. Si "
        "l'écriture est désactivée, dis-lui de taper /day write on lui-même ; s'il préfère ne pas, donne le plan "
        "en texte et n'écris rien. Ne crée, ne déplace et ne supprime JAMAIS d'événement avec un autre outil "
        "(skill Google Workspace, terminal) : il ne serait pas marqué et /day undo ne pourrait pas le retirer.\n"
        "5. Ne modifie ni ne supprime jamais un événement créé par l'utilisateur (priorités, rendez-vous "
        "médicaux, imprévus). Seul day_undo retire quelque chose, et seulement ce que ce plugin a écrit.\n"
        "6. Quand une activité est finie, demande combien de temps elle a vraiment pris et note-le avec "
        "day_took.\n"
        "Parle comme une personne : ne montre pas la syntaxe des commandes sauf si on te la demande."),
}


def _rules(_info: Any = None) -> str:
    try:
        return RULES[_guardian(with_cron=False).lang()]
    except Exception:
        return RULES["en"]


def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx
    ctx.register_command("day", _slash, description="Plan your day from your rules, estimates and calendar",
                         args_hint="<what you want in plain words> | setup | set | add | plan | now | done | brief")
    ctx.register_cli_command("guardian", "Plan your day from your rules, estimates and calendar", _cli_setup, _cli_run)
    for name, fn, schema in _TOOLS:
        ctx.register_tool(name=name, toolset="agenda-guardian", schema=schema, handler=_tool(fn),
                          description=schema["description"], emoji="🗓")
    if hasattr(ctx, "register_hook"):  # "/day <sentence>" reaches the agent as an ordinary message
        try:
            ctx.register_hook("pre_gateway_dispatch", _plain_words)
        except Exception:
            pass
    if hasattr(ctx, "register_system_prompt_section"):  # older Hermes: the tool descriptions carry the rules
        ctx.register_system_prompt_section("agenda-guardian", _rules)
