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

from . import brief, planner, profile as prof, sources, store
from .model import Block, Plan, Task

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
text = module.scheduled_text({what!r})
if text:
    print(text)
'''

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class UserError(ValueError):
    """A mistake in what the user typed; the message tells them how to fix it."""


def parse_minutes(text: str) -> int:
    text = text.strip().lower()
    match = re.fullmatch(r"(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*(?:m|min|mins|minutes?)?)?", text)
    if not text or not match or not (match.group(1) or match.group(2)):
        raise UserError(f"'{text}' is not a duration (examples: 45, 45m, 1h, 1h30)")
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def parse_day(text: str, today: date) -> date:
    text = text.strip().lower()
    if text in ("", "today"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if re.fullmatch(r"\+\d{1,3}d?", text):
        return today + timedelta(days=int(text.strip("+d")))
    if text[:3] in _WEEKDAYS:
        return today + timedelta(days=(_WEEKDAYS[text[:3]] - today.weekday()) % 7)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise UserError(f"'{text}' is not a day (use today, tomorrow, +3, fri or 2026-11-12)")


class Guardian:
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
        return store.load_profile(self.conn)

    # --- rules -------------------------------------------------------------------------------------------
    def set_rules(self, pairs: list[tuple[str, str]]) -> str:
        profile, lines = self.profile(), []
        for key, value in pairs:
            try:
                lines.append("ok  " + prof.apply_setting(profile, key, value, self.now().date()))
            except ValueError as exc:
                lines.append(f"refused  {key}: {exc}")
        store.save_profile(self.conn, profile)
        return "\n".join(lines) if lines else "Nothing to set. Example: /day set work_hours=09:00-17:30"

    def setup_text(self) -> str:
        p = self.profile()
        cats = ", ".join(f"{k} {v} min" for k, v in sorted(p["categories"].items())) or "none yet"
        cal = p["calendar"]
        cal_text = cal["type"] + (f" ({cal.get('path') or ' '.join(cal.get('argv', []))})" if cal["type"] != "none" else "")
        protected = ", ".join(f"{x['name']} {x['start']}-{x['end']}" for x in p["protected"]) or "none"
        focus = ", ".join(f"{x['start']}-{x['end']}" for x in p["focus"]) or "none"
        n = len(p["_set"])
        return "\n".join([
            "Agenda guardian setup (answer any of these; each answer is one /day set line)",
            f"({n} rule(s) set by you so far; the rest are defaults)",
            "",
            f"1. Work hours: {p['work_hours'][0]}-{p['work_hours'][1]} [{prof.source_of(p, 'work_hours')}]   work_hours=09:00-17:30",
            f"2. Workdays: {','.join(map(str, p['workdays']))} (1 = Monday) [{prof.source_of(p, 'workdays')}]   workdays=1-5",
            f"3. Protected time that tasks never use: {protected} [{prof.source_of(p, 'protected')}]   protected=lunch@12:30-13:30",
            f"4. Focus window, when your head is best (kept for priority 1 tasks): {focus} [{prof.source_of(p, 'focus')}]   focus=09:00-11:30",
            f"5. Longest stretch before a break: {p['max_block_min']} min, break {p['break_min']} min "
            f"[{prof.source_of(p, 'max_block_min')}]   max_block_min=50 break_min=10",
            f"6. Space around meetings: {p['buffer_min']} min [{prof.source_of(p, 'buffer_min')}]   buffer_min=10",
            f"7. Most tasks planned in one day: {p['max_tasks_per_day']} [{prof.source_of(p, 'max_tasks_per_day')}]   max_tasks_per_day=3",
            f"8. Calendar: {cal_text}   calendar=google | ics:<file or https URL> | file:<json> | none",
            f"9. How long do your usual tasks take? Typical minutes per kind: {cats}   category=admin:20 category=writing:60",
            "   Then, after each task, tell me the real time: /day done <task> <minutes>. From the third finished task "
            "of a kind, the plan multiplies your estimate by the median real/estimated ratio and says so.",
            f"10. Language: {p['language']}   language=fr",
        ])

    # --- tasks -------------------------------------------------------------------------------------------
    def add(self, name: str, minutes: int | None = None, category: str = "", priority: int = 2,
            due: date | None = None) -> str:
        name = name.strip()
        if not name:
            raise UserError('Give the task a name: /day add "Write the quote" 45m')
        profile = self.profile()
        category = (category or "general").strip().lower()
        if minutes is None:
            minutes = profile["categories"].get(category)
            if minutes is None:
                raise UserError("How long do you think it will take? Add an estimate, e.g. /day add \"%s\" 45m "
                                "(the planner learns from the gap between this and the real time)." % name)
        if not 5 <= minutes <= 480:
            raise UserError("An estimate must be between 5 minutes and 8 hours; split bigger tasks.")
        if priority not in (1, 2, 3):
            raise UserError("Priority is 1 (most important), 2 or 3.")
        task = store.add_task(self.conn, name, category, minutes, priority, due, self.now())
        tail = f", due {due.isoformat()}" if due else ""
        return f"Added #{task.id}: {name} ({minutes} min, {category}, priority {priority}{tail})"

    def tasks_text(self) -> str:
        items = store.tasks(self.conn)
        if not items:
            return 'No open task. Add one: /day add "Write the quote" 45m'
        facs = store.factors(self.conn)
        lines = []
        for t in items:
            fac = facs.get(t.category, (1.0, 0))
            note = f" x{fac[0]:g}" if fac[1] >= store.MIN_SAMPLES and fac[0] != 1.0 else ""
            due = f" due {t.due.isoformat()}" if t.due else ""
            lines.append(f"#{t.id} {t.name} - {t.est_min} min{note}, {t.category}, p{t.priority}{due}")
        return "\n".join(lines)

    def done(self, ref: str, actual_min: int | None) -> str:
        try:
            task = store.find_task(self.conn, ref)
        except store.RefError as exc:
            raise UserError(str(exc))
        if actual_min is None:
            raise UserError(f"How long did '{task.name}' really take? /day done {task.id} <minutes> - that "
                            "measurement is what makes the next plan honest.")
        if not 1 <= actual_min <= 960:
            raise UserError("The real time must be between 1 minute and 16 hours.")
        store.finish_task(self.conn, task, actual_min, self.now())
        fac, count = store.factors(self.conn).get(task.category, (1.0, 1))
        if count < store.MIN_SAMPLES:
            calib = f"{count} finished '{task.category}' task(s); calibration starts at {store.MIN_SAMPLES}."
        else:
            calib = f"'{task.category}' estimates are now multiplied by {fac:g} ({count} measurements)."
        return f"Done #{task.id} {task.name}: {actual_min} min for an estimate of {task.est_min}. {calib}"

    def drop(self, ref: str) -> str:
        try:
            task = store.find_task(self.conn, ref)
        except store.RefError as exc:
            raise UserError(str(exc))
        store.drop_task(self.conn, task)
        return f"Dropped #{task.id} {task.name}"

    # --- plans -------------------------------------------------------------------------------------------
    def make_plan(self, day: date | None = None, from_now: bool = False) -> tuple[Plan, dict]:
        profile, now = self.profile(), self.now()
        day = day or now.date()
        warnings: list[str] = []
        if not profile["_set"]:
            warnings.append("None of your planning rules are set yet, so defaults are used. Run /day setup.")
        try:
            events, more = sources.fetch_events(profile, day, self.home, run=self._run, urlopen=self._urlopen)
            warnings += more
        except sources.SourceError as exc:
            events = []
            warnings.append(f"Calendar unreadable ({exc}): the plan ignores your meetings.")
        plan = planner.plan_day(day, events, store.tasks(self.conn), profile, store.factors(self.conn),
                                now if from_now else None, warnings)
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
        return "\n".join(lines)

    # --- scheduling (two cron jobs that run a script, no model call) -------------------------------------
    def _jobs(self) -> dict[str, str]:
        listed = self._cron({"action": "list"})
        jobs = listed.get("jobs", []) if isinstance(listed, dict) else listed
        return {j["name"]: j.get("job_id") or j.get("id") for j in jobs
                if isinstance(j, dict) and j.get("name") in (JOB_BRIEF, JOB_NUDGE) and (j.get("job_id") or j.get("id"))}

    def schedule(self, at_time: str = "", deliver: str = "") -> str:
        if self._cron is None:
            raise UserError("Scheduling needs a running Hermes session: send /day cron on from a chat.")
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
            script.write_text(SCRIPT_TEMPLATE.format(plugin=str(self.plugin_dir), what=what), encoding="utf-8")
            args = {"schedule": expr, "script": script.name, "no_agent": True, "name": name}
            if deliver:
                args["deliver"] = deliver
            if name in existing:
                reply = self._cron({"action": "update", "job_id": existing[name], **args})
            else:
                reply = self._cron({"action": "create", "prompt": f"Run {script.name}", **args})
            if isinstance(reply, dict) and (reply.get("error") or reply.get("success") is False):
                raise UserError(f"Hermes refused the {what} job: {reply.get('error') or reply}")
        h, m = divmod(minutes, 60)
        return (f"Scheduled: a morning brief at {h:02d}:{m:02d} on your workdays, and a reminder check every 5 "
                f"minutes during work hours (it speaks only when a block is about to start or ended). Both run "
                f"a small script, no model call, no token cost. Scripts: {scripts}. Turn off: /day cron off")

    def unschedule(self) -> str:
        if self._cron is None:
            raise UserError("Scheduling needs a running Hermes session: send /day cron off from a chat.")
        jobs = self._jobs()
        for job_id in jobs.values():
            self._cron({"action": "remove", "job_id": job_id})
        return f"Removed {len(jobs)} scheduled job(s)." if jobs else "Nothing was scheduled."

    def schedule_status(self) -> str:
        if self._cron is None:
            raise UserError("Scheduling needs a running Hermes session: send /day cron status from a chat.")
        jobs = self._jobs()
        return "Scheduled: " + ", ".join(sorted(jobs)) if jobs else "Nothing scheduled. Turn on: /day cron on 07:30"

    def plan_text(self, day_text: str = "") -> str:
        day = parse_day(day_text, self.now().date())
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
