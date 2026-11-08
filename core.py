"""The Guardian: one object holding the database and the calendar settings, used by the slash command,
the CLI command and the model tools alike."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from . import brief, discover, planner, profile as prof, sources, store
from .agenda import AgendaMixin
from .model import Block, Plan, Task, UserError  # noqa: F401  (UserError is part of core's public surface)
from .texts import tr

JOB_BRIEF, JOB_NUDGE = "agenda-guardian-brief", "agenda-guardian-nudge"
SCRIPT_TEMPLATE = '''"""Written by the agenda-guardian plugin (/day cron on). It only prints text for the cron job to deliver."""
import importlib.util
import sys
from pathlib import Path

PLUGIN = Path({plugin!r})
spec = importlib.util.spec_from_file_location("agenda_guardian", PLUGIN / "__init__.py",
                                              submodule_search_locations=[str(PLUGIN)])
module = importlib.util.module_from_spec(spec)
sys.modules["agenda_guardian"] = module
spec.loader.exec_module(module)
text = module.scheduled_text({what!r}, {data!r}, {home!r})
if text:
    print(text)
'''

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
             "lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6}


def parse_minutes(text: str, lang: str = "en") -> int:
    text = text.strip().lower()
    match = re.fullmatch(r"(?:(\d+)\s*h(?:ours?|eures?)?)?\s*(?:(\d+)\s*(?:m|min|mins|minutes?)?)?", text)
    if not text or not match or not (match.group(1) or match.group(2)):
        raise UserError(tr(lang, "bad_duration", text=text))
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def parse_day(text: str, today: date, lang: str = "en") -> date:
    text = text.strip().lower()
    if text in ("", "today", "aujourd'hui", "auj"):
        return today
    if text in ("tomorrow", "demain"):
        return today + timedelta(days=1)
    if re.fullmatch(r"\+\d{1,3}d?", text):
        return today + timedelta(days=int(text.strip("+d")))
    if text[:3] in _WEEKDAYS:
        return today + timedelta(days=(_WEEKDAYS[text[:3]] - today.weekday()) % 7)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise UserError(tr(lang, "bad_day", text=text))


class Guardian(AgendaMixin):
    def __init__(self, db_path: Path, home: Path, now: Callable[[], datetime] | None = None,
                 run=subprocess.run, urlopen=urllib.request.urlopen,
                 cron: Callable[[dict], dict] | None = None, plugin_dir: Path | None = None):
        self.db_path, self.home = db_path, home
        self._now, self._run, self._urlopen = now or datetime.now, run, urlopen
        self._cron, self.plugin_dir = cron, plugin_dir or Path(__file__).resolve().parent
        self._conn = None

    @property
    def conn(self):
        if self._conn is None:
            self._conn = store.connect(self.db_path)
        return self._conn

    def now(self) -> datetime:
        return self._now().replace(tzinfo=None, microsecond=0)

    def profile(self) -> dict:
        """The stored rules; language and time zone, until the user sets them, come from the Hermes profile."""
        p = store.load_profile(self.conn)
        if not prof.is_set(p, "language"):
            p["language"] = discover.language(self.home) or "en"
        if not prof.is_set(p, "timezone"):
            p["timezone"] = discover.timezone(self.home)
        if not prof.is_set(p, "protected"):  # a default is rebuilt each time, never frozen in the stored profile
            p["protected"] = [dict(x, name="déjeuner" if p["language"] == "fr" else x["name"])
                              for x in prof.DEFAULTS["protected"]]
        return p

    def lang(self) -> str:
        return self.profile()["language"]

    # --- rules -------------------------------------------------------------------------------------------
    def set_rules(self, pairs: list[tuple[str, str]], *, from_tool: bool = False) -> str:
        profile, lines = self.profile(), []
        for key, value in pairs:
            try:
                lines.append(tr(profile["language"], "set_ok", line=prof.apply_setting(
                    profile, key, value, self.now().date(), from_tool=from_tool)))
            except ValueError as exc:
                lines.append(tr(profile["language"], "set_refused", key=key, why=exc))
        store.save_profile(self.conn, profile)
        return "\n".join(lines) if lines else tr(profile["language"], "set_nothing")

    # --- onboarding --------------------------------------------------------------------------------------------
    def detect(self) -> dict:
        return {"timezone": discover.timezone(self.home), "language": discover.language(self.home),
                "google": discover.google_state(self.home), "jobs": discover.other_jobs(self.home)}

    def _probe(self, profile: dict) -> tuple[bool, str]:
        """Read today's events from the profile's calendar: (True, count) or (False, reason)."""
        try:
            events, _ = sources.fetch_events(profile, self.now().date(), self.home, run=self._run, urlopen=self._urlopen)
        except sources.SourceError as exc:
            return False, str(exc)
        return True, str(len(events))

    def _adoptable(self, profile: dict, found: dict) -> dict:
        todo = {}
        if not prof.is_set(profile, "language") and found["language"]:
            todo["language"] = found["language"]
        if not prof.is_set(profile, "timezone") and found["timezone"]:
            todo["timezone"] = found["timezone"]
        if profile["calendar"]["type"] == "none" and found["google"] == "ready":
            todo["calendar"] = "google"
        return todo

    def facts(self) -> dict:
        """What setup found, as data for an agent: nothing here is an answer of the user."""
        p, found = self.profile(), self.detect()
        return {"language": p["language"], "timezone": p["timezone"], "google_calendar": found["google"],
                "calendar": p["calendar"]["type"], "other_reminders": [f"{n} ({s})" for n, s in found["jobs"]],
                "can_adopt": {k: v for k, v in self._adoptable(p, found).items() if k != "calendar"},
                "rules_set_by_user": sorted(p["_set"])}

    def setup_text(self) -> str:
        p, found = self.profile(), self.detect()
        lang = p["language"]

        def T(key, **kw):
            return tr(lang, key, **kw)

        out = [T("setup_title"), T("setup_count", n=len(p["_set"])), "", T("found_head")]
        if p["timezone"]:
            out.append("  " + T("found_tz", tz=p["timezone"]))
        cal = p["calendar"]
        if cal["type"] != "none":
            ok, detail = self._probe(p)
            out.append("  " + (T("found_cal_ok", kind=cal["type"], n=detail) if ok
                               else T("found_cal_bad", kind=cal["type"], why=detail)))
        elif found["google"] == "ready":
            ok, detail = self._probe(dict(p, calendar={"type": "google"}))
            out.append("  " + (T("found_google", n=detail) if ok else T("found_google_bad", why=detail)))
        elif found["google"] == "skill_only":
            out.append("  " + T("found_google_nosignin"))
        else:
            out.append("  " + T("found_google_off"))
        if found["jobs"]:
            shown = ", ".join(f"{name or T('unnamed')} ({when})" for name, when in found["jobs"][:5])
            more = len(found["jobs"]) - 5
            out.append("  " + T("found_jobs", n=len(found["jobs"]), jobs=shown + (f", +{more}" if more > 0 else "")))
        else:
            out.append("  " + T("found_no_jobs"))
        if "calendar" in self._adoptable(p, found):
            out.append("  " + T("adopt"))

        cats = ", ".join(f"{k} {v} min" for k, v in sorted(p["categories"].items())) or T("none_yet")
        where = cal.get("path") or " ".join(cal.get("argv", []))
        cal_text = (cal["type"] + (f" ({where})" if where else "")) if cal["type"] != "none" else T("none")
        protected = ", ".join(f"{x['name']} {x['start']}-{x['end']}" for x in p["protected"]) or T("none")
        focus = ", ".join(f"{x['start']}-{x['end']}" for x in p["focus"]) or T("none")
        out += ["", T("rules_head"),
                "  " + T("rule_line_hours", value="-".join(p["work_hours"]), source=prof.source_of(p, "work_hours")),
                "  " + T("rule_line_protected", value=protected, source=prof.source_of(p, "protected")),
                "  " + T("rule_line_focus", value=focus, source=prof.source_of(p, "focus")),
                "  " + T("rule_line_calendar", value=cal_text),
                "  " + T("rule_line_language", value=lang),
                "", T("fine_tune", days=",".join(map(str, p["workdays"])), block=p["max_block_min"],
                      brk=p["break_min"], buf=p["buffer_min"], cap=p["max_tasks_per_day"], cats=cats),
                "", T("next_steps")]
        return "\n".join(out)

    def setup_auto(self, *, from_tool: bool = False) -> str:
        """Adopt what the Hermes profile already says: language, time zone and a working Google calendar.
        From an agent tool the calendar is left to the user: only their typed command adopts it."""
        p, found = self.profile(), self.detect()
        lang = p["language"]
        todo, skipped = self._adoptable(p, found), ""
        if from_tool and "calendar" in todo:
            del todo["calendar"]
            skipped = tr(lang, "auto_cal_user")
        if "calendar" in todo:
            ok, detail = self._probe(dict(p, calendar={"type": "google"}))
            if not ok:
                del todo["calendar"]
                skipped = tr(lang, "auto_skip_cal", why=detail)
        if not todo:
            return "\n".join([tr(lang, "auto_nothing")] + ([skipped] if skipped else []))
        today, lines = self.now().date(), []
        for key, value in todo.items():
            lines.append("ok  " + prof.apply_setting(p, key, value, today))
            p["_set"][key] = "auto:" + today.isoformat()
        store.save_profile(self.conn, p)
        return "\n".join([tr(lang, "auto_done")] + lines + ([skipped] if skipped else []))

    # --- tasks -------------------------------------------------------------------------------------------
    def add(self, name: str, minutes: int | None = None, category: str = "", priority: int = 2,
            due: date | None = None) -> str:
        name = name.strip()
        profile = self.profile()
        lang = profile["language"]
        if not name:
            raise UserError(tr(lang, "add_name"))
        category = (category or "general").strip().lower()
        if minutes is None:
            minutes = profile["categories"].get(category)
            if minutes is None:
                raise UserError(tr(lang, "add_estimate", name=name))
        if not 5 <= minutes <= 480:
            raise UserError(tr(lang, "add_range"))
        if priority not in (1, 2, 3):
            raise UserError(tr(lang, "add_priority"))
        task = store.add_task(self.conn, name, category, minutes, priority, due, self.now())
        tail = tr(lang, "due_tail", day=due.isoformat()) if due else ""
        return tr(lang, "added", id=task.id, name=name, minutes=minutes, category=category, priority=priority, tail=tail)

    def tasks_text(self) -> str:
        lang = self.lang()
        items = store.tasks(self.conn)
        if not items:
            return tr(lang, "tasks_none")
        facs = store.factors(self.conn)
        lines = []
        for t in items:
            fac = facs.get(t.category, (1.0, 0))
            note = f" x{fac[0]:g}" if fac[1] >= store.MIN_SAMPLES and fac[0] != 1.0 else ""
            due = tr(lang, "task_due", day=t.due.isoformat()) if t.due else ""
            lines.append(f"#{t.id} {t.name} - {t.est_min} min{note}, {t.category}, p{t.priority}{due}")
        return "\n".join(lines)

    def done(self, ref: str, actual_min: int | None) -> str:
        lang = self.lang()
        try:
            task = store.find_task(self.conn, ref, lang)
        except store.RefError as exc:
            raise UserError(str(exc))
        if actual_min is None:
            raise UserError(tr(lang, "done_need", name=task.name, id=task.id))
        if not 1 <= actual_min <= 960:
            raise UserError(tr(lang, "done_range"))
        store.finish_task(self.conn, task, actual_min, self.now())
        fac, count = store.factors(self.conn).get(task.category, (1.0, 1))
        if count < store.MIN_SAMPLES:
            calib = tr(lang, "done_start", count=count, category=task.category, min=store.MIN_SAMPLES)
        else:
            calib = tr(lang, "done_now", category=task.category, factor=fac, count=count)
        return tr(lang, "done_msg", id=task.id, name=task.name, actual=actual_min, est=task.est_min, calib=calib)

    def drop(self, ref: str) -> str:
        lang = self.lang()
        try:
            task = store.find_task(self.conn, ref, lang)
        except store.RefError as exc:
            raise UserError(str(exc))
        store.drop_task(self.conn, task)
        return tr(lang, "dropped", id=task.id, name=task.name)

    # --- plans -------------------------------------------------------------------------------------------
    def make_plan(self, day: date | None = None, from_now: bool = False,
                  remember: bool = True) -> tuple[Plan, dict]:
        profile, now = self.profile(), self.now()
        day = day or now.date()
        warnings: list[str] = []
        if not profile["_set"]:
            warnings.append(tr(profile["language"], "no_rules_warning"))
        try:
            events, more = sources.fetch_events(profile, day, self.home, run=self._run, urlopen=self._urlopen)
            warnings += more
        except sources.SourceError as exc:
            events = []
            warnings.append(tr(profile["language"], "cal_unreadable", why=exc))
        plan = planner.plan_day(day, events, store.tasks(self.conn), profile, store.factors(self.conn),
                                now if from_now else None, warnings)
        if remember:
            self._remember(plan)
        return plan, profile

    def _remember(self, plan: Plan) -> None:
        """Keep the plan reminders follow: a later replan must not move a block the user already saw."""
        blocks = [{"task_id": b.task_id, "name": b.name, "part": b.part, "parts": b.parts, "focus": b.focus,
                   "start": b.start.isoformat(), "end": b.end.isoformat()} for b in plan.blocks]
        store.save_plan(self.conn, plan.day.isoformat(), json.dumps(blocks))

    def _remembered(self, day: date) -> list[Block] | None:
        raw = store.load_plan(self.conn, day.isoformat())
        if raw is None:
            return None
        return [Block(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]), b["task_id"], b["name"],
                      b["part"], b["parts"], b["focus"]) for b in json.loads(raw)]

    # --- reminders (run by the nudge cron job, no model call) --------------------------------------------
    def nudge_text(self) -> str:
        """What to say right now, or "" (an empty answer sends nothing). Each reminder is sent once:
        a block about to start, and, after a task's last block, the question that feeds the calibration."""
        now, lines = self.now(), []
        day = now.date()
        blocks = self._remembered(day)
        if blocks is None:
            blocks = self.make_plan(day, from_now=True)[0].blocks
        t = brief.T.get(self.profile()["language"], brief.T["en"])
        open_ids = {task.id for task in store.tasks(self.conn)}
        for b in blocks:
            start_key = f"{day}:{b.task_id}:{b.start:%H:%M}:start"
            if b.start - timedelta(minutes=6) <= now < b.end and not store.was_notified(self.conn, start_key):
                part = f", {t['part'].format(i=b.part, n=b.parts)}" if b.parts > 1 else ""
                lines.append(t["nudge_start"].format(time=b.start.strftime("%H:%M"), name=b.name,
                                                     minutes=b.minutes, part=part))
                store.mark_notified(self.conn, start_key, now)
            end_key = f"{day}:{b.task_id}:{b.end:%H:%M}:end"
            if (b.part == b.parts and b.task_id in open_ids and b.end <= now < b.end + timedelta(hours=3)
                    and not store.was_notified(self.conn, end_key)):
                lines.append(t["nudge_end"].format(name=b.name, end=b.end.strftime("%H:%M"), id=b.task_id))
                store.mark_notified(self.conn, end_key, now)
        lines += self.kind_questions(now)
        return "\n".join(lines)

    # --- scheduling (two cron jobs that run a script, no model call) -------------------------------------
    def _jobs(self) -> dict[str, str]:
        listed = self._cron({"action": "list"})
        if not isinstance(listed, dict) or listed.get("error") or not isinstance(listed.get("jobs"), list):
            raise UserError(tr(self.lang(), "jobs_failed",
                               why=(listed.get("error") if isinstance(listed, dict) else None) or "unexpected answer"))
        jobs = listed["jobs"]
        return {j["name"]: j.get("job_id") or j.get("id") for j in jobs
                if isinstance(j, dict) and j.get("name") in (JOB_BRIEF, JOB_NUDGE) and (j.get("job_id") or j.get("id"))}

    def schedule(self, at_time: str = "", deliver: str = "") -> str:
        if self._cron is None:
            raise UserError(tr(self.lang(), "need_session", action="on"))
        profile = self.profile()
        start_h, start_m = divmod(prof.minutes_of(profile["work_hours"][0]), 60)
        default = max(5 * 60, start_h * 60 + start_m - 30)
        try:
            minutes = prof.minutes_of(at_time) if at_time else default
        except ValueError as exc:
            raise UserError(str(exc))
        days = ",".join(str(d % 7) for d in profile["workdays"])  # cron: 0 = Sunday
        end_hour = min(23, divmod(prof.minutes_of(profile["work_hours"][1]), 60)[0] + 3)
        scripts = self.home / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        specs = {
            JOB_BRIEF: ("brief", f"{minutes % 60} {minutes // 60} * * {days}"),
            JOB_NUDGE: ("nudge", f"*/5 {max(0, start_h - 1)}-{end_hour} * * {days}"),
        }
        existing = self._jobs()
        for name, (what, expr) in specs.items():
            script = scripts / f"{name}.py"
            script.write_text(SCRIPT_TEMPLATE.format(plugin=str(self.plugin_dir), what=what,
                                                           data=str(self.db_path.parent), home=str(self.home)), encoding="utf-8")
            args = {"schedule": expr, "script": script.name, "no_agent": True, "name": name}
            if deliver:
                args["deliver"] = deliver
            if name in existing:
                reply = self._cron({"action": "update", "job_id": existing[name], **args})
            else:
                reply = self._cron({"action": "create", "prompt": f"Run {script.name}", **args})
            if isinstance(reply, dict) and (reply.get("error") or reply.get("success") is False):
                raise UserError(tr(profile["language"], "job_refused", what=what, why=reply.get("error") or reply))
        h, m = divmod(minutes, 60)
        return tr(profile["language"], "scheduled", time=f"{h:02d}:{m:02d}", scripts=scripts)

    def unschedule(self) -> str:
        if self._cron is None:
            raise UserError(tr(self.lang(), "need_session", action="off"))
        jobs = self._jobs()
        for job_id in jobs.values():
            self._cron({"action": "remove", "job_id": job_id})
        for name in (JOB_BRIEF, JOB_NUDGE):
            (self.home / "scripts" / f"{name}.py").unlink(missing_ok=True)
        lang = self.lang()
        return tr(lang, "unscheduled", n=len(jobs)) if jobs else tr(lang, "unscheduled_none")

    def schedule_status(self) -> str:
        if self._cron is None:
            raise UserError(tr(self.lang(), "need_session", action="status"))
        jobs = self._jobs()
        lang = self.lang()
        return tr(lang, "sched_status", names=", ".join(sorted(jobs))) if jobs else tr(lang, "sched_status_none")

    def plan_text(self, day_text: str = "") -> str:
        day = parse_day(day_text, self.now().date(), self.lang())
        plan, profile = self.make_plan(day, from_now=day == self.now().date())
        return brief.render(plan, profile)

    def now_text(self) -> str:
        plan, profile = self.make_plan(from_now=True)
        return brief.render_now(plan, profile, self.now())

    def brief_text(self) -> str:
        """Today's plan; tomorrow's once today's work hours are over."""
        profile, now = self.profile(), self.now()
        end = planner.at(now.date(), profile["work_hours"][1])
        day = now.date() + timedelta(days=1) if now >= end else now.date()
        plan, profile = self.make_plan(day, from_now=day == now.date())
        return brief.render(plan, profile)
