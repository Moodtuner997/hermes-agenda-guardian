"""End-to-end check against a real Hermes install, without any LLM.

Run with the Hermes interpreter and a throwaway HERMES_HOME in which the plugin is installed and enabled:

    HERMES_HOME=<home> <hermes python> tests/e2e_hermes.py

It sends real tool calls through ``model_tools.handle_function_call`` (registry, hooks, approvals) and checks
that the planner answers, that ``day_schedule`` creates the two cron jobs through Hermes' own cron tool and
that the scripts it wrote run under the scheduler's script runner.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from hermes_cli.plugins import discover_plugins, get_plugin_command_handler
from model_tools import handle_function_call

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        failures.append(label)


def tool(name: str, args: dict) -> dict:
    raw = handle_function_call(name, args, task_id="e2e", session_id="e2e-session")
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def slash(raw: str) -> str:
    return get_plugin_command_handler("day")(raw, session_id="e2e-session")


discover_plugins(force=True)
work = Path(tempfile.mkdtemp(prefix="day-e2e-"))
(work / "cal.json").write_text(json.dumps([{"summary": "Client call", "start": "2026-11-09T10:30:00",
                                            "end": "2026-11-09T11:00:00"}]), encoding="utf-8")

print(slash(f"set language=en work_hours=09:00-17:30 calendar=file:{work / 'cal.json'}"))  # the checks read English
added = tool("day_add_task", {"name": "Write the quote", "minutes": 45, "priority": 1})
check("day_add_task answers through the registry", added.get("ok") is True, json.dumps(added)[:200])
plan = tool("day_plan", {"day": "2026-11-09"})
check("day_plan lists the task and the meeting", "Write the quote" in plan.get("plan", "")
      and "Client call" in plan.get("plan", ""), json.dumps(plan)[:300])

kind = tool("day_kind", {"name": "sport", "real_minutes": 90, "before_minutes": 10, "after_minutes": 20,
                         "window": "18:00-22:00"})
check("day_kind saves an activity sheet", kind.get("ok") is True and kind.get("kind", {}).get("name") == "sport", json.dumps(kind)[:300])
proposal = tool("day_propose", {"activity": "sport", "from_day": "2026-11-09", "to_day": "2026-11-11"})
check("day_propose answers with reasons and says nothing was written",
      proposal.get("ok") is True and proposal.get("sessions") and proposal["sessions"][0]["reasons"]
      and "Nothing is written" in proposal.get("text", ""), json.dumps(proposal)[:400])
blocked = tool("day_confirm", {"proposal_id": proposal.get("proposal_id", 1)})
check("day_confirm is refused until the user typed /day write on",
      blocked.get("ok") is False and "write on" in blocked.get("error", ""), json.dumps(blocked)[:300])
plan_week = tool("day_week_plan", {"from_day": "2026-11-09", "to_day": "2026-11-11", "activities": [
    {"name": "calls", "minutes": 90, "sessions": 1, "window": "09:00-12:00"},
    {"name": "course", "minutes": 60, "per_day": 1, "window": "13:00-18:00", "days": "tue"}]})
check("day_week_plan places two activities in one call and writes nothing",
      plan_week.get("ok") is True and {s["kind"] for s in plan_week.get("sessions", [])} == {"calls", "course"}
      and "Nothing is written" in plan_week.get("text", ""), json.dumps(plan_week)[:400])
staged = tool("day_stage", {"blocks": [{"title": "Choir", "day": "2026-11-10", "start": "19:00", "end": "20:00"}]})
check("day_stage registers a composed block as a proposal", staged.get("ok") is True
      and staged.get("proposal_id") and "Choir" in staged.get("text", ""), json.dumps(staged)[:300])
blocked = tool("day_confirm", {"proposal_id": staged.get("proposal_id", 1)})
check("a staged block is refused too until the user typed /day write on",
      blocked.get("ok") is False and "write on" in blocked.get("error", ""), json.dumps(blocked)[:300])
from types import SimpleNamespace  # noqa: E402

from hermes_cli.lifecycle import invoke_hook  # noqa: E402

said = invoke_hook("pre_gateway_dispatch", event=SimpleNamespace(text="/day place two sport sessions in my week"),
                   gateway=None, session_store=None)
check("the gateway hook hands a /day sentence to the agent", len(said) == 1 and said[0].get("action") == "rewrite"
      and said[0].get("text", "").endswith("place two sport sessions in my week"), json.dumps(said)[:300])
check("the gateway hook leaves a command alone",
      invoke_hook("pre_gateway_dispatch", event=SimpleNamespace(text="/day plan tomorrow"), gateway=None,
                  session_store=None) == [])
week = tool("day_week", {"week_of": "2026-11-09"})
check("day_week reads the week", week.get("ok") is True and week.get("week_start") == "2026-11-09"
      and len(week.get("proposed", [])) >= 1, json.dumps(week)[:300])

setup = tool("day_setup", {"settings": {"Calendar": "cmd:python -c print(1)", "buffer_min": "5"}})
check("day_setup refuses a calendar source from a tool and still applies the rest",
      setup.get("ok") is True and "refused  Calendar" in setup.get("result", "") and "ok  buffer_min" in setup.get("result", "")
      and "for_agent" in setup, json.dumps(setup)[:300])
check("the calendar is still the user's file", "Client call" in tool("day_plan", {"day": "2026-11-09"}).get("plan", ""))
check("the gateway hook leaves a typed calendar command to the dispatcher",
      invoke_hook("pre_gateway_dispatch", event=SimpleNamespace(text="/day set calendar=cmd:mycal"), gateway=None,
                  session_store=None) == [])
said = invoke_hook("pre_gateway_dispatch", event=SimpleNamespace(text="/day set work_hours=09:00-19:00"), gateway=None,
                   session_store=None)
check("the other settings still go to the agent", len(said) == 1 and said[0].get("action") == "rewrite", json.dumps(said)[:200])

os.environ["HERMES_CRON_SESSION"] = "1"  # what a cron-spawned agent runs under
try:
    for action in ("on", "off"):
        refused = tool("day_schedule", {"action": action})
        check(f"day_schedule {action} is refused in a cron run", refused.get("ok") is False
              and "refused inside a cron run" in refused.get("error", ""), json.dumps(refused)[:300])
    check("day_schedule status still works in a cron run", tool("day_schedule", {"action": "status"}).get("ok") is True)
finally:
    os.environ.pop("HERMES_CRON_SESSION", None)

# The pre_tool_call guard, through Hermes' own dispatch: a side road to the calendar source reaches the approval gate
# (a recorder stands in for the human), an ordinary call never does, and a cron run is refused without asking anyone.
import tools.approval as approval  # noqa: E402
from hermes_cli.plugins import resolve_pre_tool_block  # noqa: E402

asked: list[tuple] = []
answer = {"approved": False, "message": "denied by the e2e"}
real_gate = approval.request_tool_approval
approval.request_tool_approval = lambda tool_name, reason, rule_key="", **kw: (
    asked.append((tool_name, reason, rule_key)) or dict(answer))
road = {"command": 'echo "hermes guardian set calendar=cmd:x"'}
note = Path(os.environ["HERMES_HOME"]) / "plugin-data" / "agenda-guardian" / "e2e-note.txt"
try:
    denied = tool("terminal", road)
    check("a side road to the calendar source reaches Hermes' approval gate with the exact call",
          len(asked) == 1 and asked[0][0] == "terminal" and "hermes guardian set calendar=cmd:x" in asked[0][1]
          and asked[0][2].startswith("agenda-guardian:calendar:"), repr(asked)[:300])
    check("a denial stops the call", "denied by the e2e" in json.dumps(denied), json.dumps(denied)[:300])
    asked.clear()
    check("an ordinary call never reaches the gate",
          resolve_pre_tool_block("terminal", {"command": "echo ok"}) is None and not asked)
    answer.update(approved=True, message="")
    written = tool("write_file", {"path": str(note), "content": "approved"})
    check("an approved call goes through", len(asked) == 1 and asked[0][2].startswith("agenda-guardian:storage:")
          and note.exists(), json.dumps(written)[:300] + repr(asked)[:200])
    asked.clear()
    os.environ["HERMES_CRON_SESSION"] = "1"
    refused = tool("terminal", road)
    check("in a cron run the same road is refused without asking anyone",
          not asked and "nobody is here to confirm" in json.dumps(refused), json.dumps(refused)[:300])
finally:
    os.environ.pop("HERMES_CRON_SESSION", None)
    approval.request_tool_approval = real_gate
    note.unlink(missing_ok=True)

on = tool("day_schedule", {"action": "on", "time": "07:30"})
print(json.dumps(on, ensure_ascii=False)[:400])
check("day_schedule on is accepted by the cron tool", on.get("ok") is True, json.dumps(on)[:300])
status = tool("day_schedule", {"action": "status"})
check("both jobs are listed by Hermes", "agenda-guardian-brief" in json.dumps(status)
      and "agenda-guardian-nudge" in json.dumps(status), json.dumps(status)[:300])

jobs = tool("cronjob_manage", {"action": "list"})
mine = [j for j in jobs.get("jobs", []) if str(j.get("name", "")).startswith("agenda-guardian-")]
check("jobs are script-only (no_agent)", len(mine) == 2 and all(j.get("no_agent") for j in mine), json.dumps(mine)[:400])

from cron.scheduler_script import _run_job_script  # noqa: E402

for name in ("agenda-guardian-brief.py", "agenda-guardian-nudge.py"):
    ok, out = _run_job_script(name)
    check(f"scheduler runs {name}", ok, out[:300])
    print(f"--- {name} printed {len(out)} chars")
    if name.endswith("brief.py"):
        check("the brief script prints a plan", out.startswith("Plan for"), out[:200])

# The duration question: a written activity ended ten minutes ago; the real nudge job, run by Hermes' own
# scheduler (no model), says it once and then stays silent.
import sqlite3  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

from cron.jobs import get_job  # noqa: E402
from cron.scheduler import SILENT_MARKER, run_job  # noqa: E402

ended = datetime.now().replace(microsecond=0) - timedelta(minutes=10)
db = sqlite3.connect(str(Path(os.environ["HERMES_HOME"]) / "plugin-data" / "agenda-guardian" / "guardian.db"))
db.execute("INSERT INTO written (event_id, calendar_id, group_id, kind, part, summary, start, end, link, created_at) "
           "VALUES ('e2e-sport', 'primary', 99, 'sport', 'main', 'sport', ?, ?, '', ?)",
           ((ended - timedelta(minutes=90)).isoformat(), ended.isoformat(), ended.isoformat()))
db.commit()
db.close()
nudge_id = next((j.get("job_id") or j.get("id") for j in mine if j.get("name") == "agenda-guardian-nudge"), None)
first = run_job(get_job(nudge_id)) if nudge_id else (False, "", "", "no nudge job")
check("the nudge job, run by Hermes' scheduler, asks how long the activity really took",
      first[0] and "How long did it really take" in first[2] and f"{ended:%H:%M}" in first[2], repr(first)[:300])
second = run_job(get_job(nudge_id)) if nudge_id else (False, "", "", "no nudge job")
check("the question is asked once: the next run of the job is silent", second[0] and second[2] == SILENT_MARKER,
      repr(second)[:300])
answered = tool("day_took", {"actual_minutes": 70})
check("a bare duration answers it", answered.get("ok") is True and answered.get("real_minutes") == 70, json.dumps(answered)[:300])

off = tool("day_schedule", {"action": "off"})
check("day_schedule off removes the jobs", "Removed 2" in json.dumps(off), json.dumps(off)[:300])
jobs = tool("cronjob_manage", {"action": "list"})
check("no job of ours is left", not [j for j in jobs.get("jobs", []) if str(j.get("name", "")).startswith("agenda-guardian-")])

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
