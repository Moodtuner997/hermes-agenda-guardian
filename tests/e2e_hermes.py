"""End-to-end check against a real Hermes install, without any LLM.

Run with the Hermes interpreter and a throwaway HERMES_HOME in which the plugin is installed and enabled:

    HERMES_HOME=<home> <hermes python> tests/e2e_hermes.py

It sends real tool calls through ``model_tools.handle_function_call`` (registry, hooks, approvals) and checks
that the planner answers, that ``day_schedule`` creates the two cron jobs through Hermes' own cron tool and
that the scripts it wrote run under the scheduler's script runner.
"""

from __future__ import annotations

import json
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

print(slash(f"set work_hours=09:00-17:30 calendar=file:{work / 'cal.json'}"))
added = tool("day_add_task", {"name": "Write the quote", "minutes": 45, "priority": 1})
check("day_add_task answers through the registry", added.get("ok") is True, json.dumps(added)[:200])
plan = tool("day_plan", {"day": "2026-11-09"})
check("day_plan lists the task and the meeting", "Write the quote" in plan.get("plan", "")
      and "Client call" in plan.get("plan", ""), json.dumps(plan)[:300])

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

off = tool("day_schedule", {"action": "off"})
check("day_schedule off removes the jobs", "Removed 2" in json.dumps(off), json.dumps(off)[:300])
jobs = tool("cronjob_manage", {"action": "list"})
check("no job of ours is left", not [j for j in jobs.get("jobs", []) if str(j.get("name", "")).startswith("agenda-guardian-")])

print("\nFAILED: " + ", ".join(failures) if failures else "\nAll checks passed")
sys.exit(1 if failures else 0)
