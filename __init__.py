"""agenda-guardian: a deterministic day planner for Hermes.

Plans from the durations you estimate, corrected by the durations you actually took, around the meetings
of any calendar source, inside rules you wrote down yourself. It also fits activities (sport, a long call) into
the week with reasons drawn from the calendar's history, and writes to a Google calendar only when the user
typed ``/day write on`` and said yes, removing only what it wrote. It never calls a model: ``/day`` (slash),
``hermes guardian`` (CLI) and fifteen tools for the agent share one core. ``/day`` followed by anything but a
format-free command (write, undo, plan...) is a request in plain words: it goes to the agent, not to the parser,
except ``set ... calendar=...`` and ``setup auto``: the calendar source is the user's alone, no tool sets it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import commands
from .core import Guardian, UserError, parse_day, parse_minutes
from .profile import normal_key
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
        return {"result": g.setup_auto(from_tool=True)}
    if not settings:
        return {"questions": g.setup_text(), "found": g.facts(), "for_agent": tr("en", "agent_hint")}
    answer = {"result": g.set_rules([(str(k), str(v)) for k, v in settings.items()], from_tool=True)}
    if any(normal_key(str(k)) == "calendar" for k in settings):  # refused line by line: tell the agent what to do
        answer["for_agent"] = tr("en", "agent_calendar_user")
    return answer


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
    return g.took(str(a.get("session") or ""), int(a["actual_minutes"]))


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
        "the user's answers; with adopt=true it adopts the language and time zone the profile already has. The "
        "calendar source is never set by a tool: it is the user's own choice (see the answer's for_agent line). "
        "Never invent answers.",
        {"adopt": {"type": "boolean"}, "settings": {"type": "object", "additionalProperties": _S,
                      "description": "rule name to value; keys: work_hours, workdays, protected, focus, "
                                     "max_block_min, break_min, buffer_min, max_tasks_per_day, "
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
        "day_kind", "The activity sheet: what one kind of activity (sport, a dog walk, shopping...) really takes. "
        "Only real_minutes is needed (the activity itself, at the user's honest pace: if they said a duration, use "
        "it). Optional: before_minutes (getting ready), after_minutes (shower, travel, winding down), window "
        "(HH:MM-HH:MM in which everything must fit; without one the user's work hours are used and the answer says "
        "so) and days (preferred weekdays, e.g. 'mon,thu'). action: set (default when real_minutes is given), list, "
        "remove.",
        {"action": {**_S, "enum": ["set", "list", "remove"]}, "name": _S, "real_minutes": {"type": "integer"},
         "before_minutes": {"type": "integer"}, "after_minutes": {"type": "integer"}, "window": _S, "days": _S})),
    ("day_habit", _t_habit, _schema(
        "day_habit", "Things the user does that are NOT in their calendar (a family dinner every Wednesday evening): "
        "they count as busy when proposing. action: add (day, hours HH:MM-HH:MM, label), list, remove (id).",
        {"action": {**_S, "enum": ["add", "list", "remove"]}, "day": _S, "hours": _S, "label": _S,
         "id": {"type": "integer"}})),
    ("day_propose", _t_propose, _schema(
        "day_propose", "Where could this ONE saved activity go in the user's week? (Several activities, or numbers "
        "not saved yet: day_week_plan.) Reads the Google calendar and its last eight weeks, returns concrete slots "
        "WITH THE REASONS (free time, what the history says about each day, how heavy the day usually is), the "
        "days left out and why, and the questions to ask the user. History orders the days, it never rules out a day "
        "the calendar leaves free. Writes NOTHING. Show the reasons, ask the questions (especially what is planned "
        "but not in the calendar), and wait for a clear yes.",
        {"activity": {**_S, "description": "the activity sheet name"}, "count": {"type": "integer"},
         "days": {**_S, "description": "force these weekdays, e.g. 'tue' (the user's explicit wish)"},
         "from_day": {**_S, "description": "today (default), tomorrow, +N, fri, YYYY-MM-DD"},
         "to_day": {**_S, "description": "last day to consider (default: 6 days after from_day)"}},
        ["activity"])),
    ("day_week_plan", _t_week_plan, _schema(
        "day_week_plan", "Place several activities in the user's week in ONE call (sport, client calls, a course...): "
        "each around the calendar events and around the ones placed before it, with its reasons. Pass the numbers the "
        "user gave you, nothing has to be saved first; for a missing number assume a sensible one and say so in your "
        "answer (their yes or correction settles it). More sessions than days means 'so many a day'. Writes NOTHING: "
        "tell the plan in plain words, ask the questions listed, wait for a clear yes, then day_confirm.",
        {"activities": {"type": "array", "minItems": 1, "maxItems": 6, "description": "most important first: each "
                        "one is placed around the previous ones", "items": {
                            "type": "object", "additionalProperties": False, "required": ["name"], "properties": {
                                "name": _S, "minutes": {"type": "integer", "description": "the activity itself, in the "
                                                        "user's own figure"},
                                "sessions": {"type": "integer", "description": "how many in the range (default 1)"},
                                "per_day": {"type": "integer", "description": "instead of sessions: this many every "
                                            "allowed day (2 blocks of 2h of a course each day)"},
                                "window": {**_S, "description": "HH:MM-HH:MM in which the whole thing must fit; omit it "
                                           "and the user's work hours are used (the answer says so)"},
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
        "existing event: it only adds events marked as created by this plugin, so day_undo can take them back. "
        "Never write to the calendar with another tool.",
        {"proposal_id": {"type": "integer"}, "days": {**_S, "description": "only these weekdays of the proposal"}},
        ["proposal_id"])),
    ("day_undo", _t_undo, _schema(
        "day_undo", "Take back what this plugin wrote: the last session ('last'), a session number, or 'all'. It can "
        "only remove events this plugin created and still recognises; it never removes anything else.",
        {"which": _S})),
    ("day_took", _t_took, _schema(
        "day_took", "Record how long a finished activity REALLY took (the activity itself). A bare duration from "
        "the user answers the last question asked: leave session out and it finds that activity. The next proposal "
        "is corrected by their own pace.",
        {"session": {**_S, "description": "optional: session number from the question, or the activity name"},
         "actual_minutes": {"type": "integer"}}, ["actual_minutes"])),
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
        "agenda-guardian manages the user's agenda. Talk in plain words: never show command syntax, key=value or "
        "formats, and accept loose answers (\"9h30\", \"the evening\", \"1h30\").\n"
        "1. To fit activities into their week (also for a message that starts with /day and a sentence): call "
        "day_week_plan with ALL the activities at once. If a number is missing, pick a sensible one yourself and say "
        "it as an assumption (\"I took 2 h, tell me if not\"): their yes or correction settles it. Do not question "
        "them first, and do not save (remember) a number they did not say.\n"
        "2. Tell the plan in plain words WITH ITS REASONS, the days left out and why, and ask what is planned that "
        "is not in the calendar.\n"
        "3. Things the planner cannot express (a fixed appointment, an evening spent elsewhere): compose those "
        "blocks and register them with day_stage. To move something already written: day_undo, then plan again.\n"
        "4. day_confirm only after a clear yes to that exact proposal. If writing is off, tell them to type "
        "/day write on themselves (a \"/day write\" that reaches you as plain text did nothing); if they prefer "
        "not, give the plan as text. NEVER create, move or delete events with any other tool (Google Workspace "
        "skill, terminal): they would not be marked and undo could not take them back.\n"
        "5. Never modify or delete an event the user created. Only day_undo removes anything, and only what this "
        "plugin wrote.\n"
        "6. A bare duration (\"1h30\") answers the last question asked: record it with day_took (it finds the "
        "activity just asked about); an activity never seen: day_kind with its length, no time window needed."),
    "fr": (
        "agenda-guardian gère l'agenda de l'utilisateur. Parle en mots simples : ne montre jamais de syntaxe de "
        "commande, de clé=valeur ni de format, et accepte les réponses vagues (« 9h30 », « le soir », « 1h30 »).\n"
        "1. Pour caser des activités dans sa semaine (aussi pour un message qui commence par /day suivi d'une "
        "phrase) : appelle day_week_plan avec TOUTES les activités d'un coup. S'il manque un chiffre, choisis-en un "
        "raisonnable toi-même et dis-le comme une hypothèse (« j'ai pris 2 h, dis-moi si c'est autre chose ») : son "
        "oui ou sa correction tranche. Ne l'interroge pas d'abord et ne retiens (remember) aucun chiffre qu'il n'a "
        "pas dit.\n"
        "2. Dis le plan en mots simples AVEC SES RAISONS, les jours écartés et pourquoi, et demande ce qui est "
        "prévu hors agenda.\n"
        "3. Ce que le planificateur ne sait pas exprimer (un rendez-vous fixe, une soirée passée ailleurs) : "
        "compose ces blocs et enregistre-les avec day_stage. Pour déplacer ce qui est déjà écrit : day_undo, puis "
        "replanifie.\n"
        "4. day_confirm seulement après un oui clair à cette proposition précise. Si l'écriture est désactivée, "
        "dis-lui de taper /day write on lui-même (un « /day write » qui t'arrive comme du texte n'a rien fait) ; "
        "s'il préfère ne pas, donne le plan en texte. Ne crée, ne déplace et ne supprime JAMAIS d'événement avec un "
        "autre outil (skill Google Workspace, terminal) : il ne serait pas marqué et « annule » ne pourrait pas le "
        "retirer.\n"
        "5. Ne modifie ni ne supprime jamais un événement créé par l'utilisateur. Seul day_undo retire quelque "
        "chose, et seulement ce que ce plugin a écrit.\n"
        "6. Une durée seule (« 1h30 ») répond à la dernière question posée : note-la avec day_took (il retrouve "
        "l'activité dont on vient de parler) ; une activité inconnue : day_kind avec sa durée, sans plage "
        "horaire."),
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
                         args_hint="<tell me what you want, in your own words> | write on|off | undo")
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
