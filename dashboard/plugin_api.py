"""Dashboard API of agenda-guardian, mounted at /api/plugins/agenda-guardian/.

A thin layer over the same Guardian the slash command and the tools use. Reading a plan never changes
what the reminders follow. Writes: adding a task, logging a real duration, and, on the user's click, writing or
undoing a proposal (which still needs the switch the user turned on with /day write on).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()
PLUGIN = Path(__file__).resolve().parent.parent


def _plugin():
    module = sys.modules.get("agenda_guardian")
    if module is None:
        spec = importlib.util.spec_from_file_location("agenda_guardian", PLUGIN / "__init__.py",
                                                      submodule_search_locations=[str(PLUGIN)])
        module = importlib.util.module_from_spec(spec)
        sys.modules["agenda_guardian"] = module
        spec.loader.exec_module(module)
    return module


def _guard(call):
    plugin = _plugin()
    try:
        return call(plugin, plugin._guardian(with_cron=False))
    except plugin.UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class NewTask(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    minutes: int | None = Field(default=None, ge=5, le=480)
    category: str = ""
    priority: int = Field(default=2, ge=1, le=3)
    due: str = ""


class Finished(BaseModel):
    minutes: int = Field(ge=1, le=960)


@router.get("/plan")
def get_plan(day: str = ""):
    def build(plugin, guardian):
        from agenda_guardian import store

        today = guardian.now().date()
        target = plugin.parse_day(day, today)
        plan, profile = guardian.make_plan(target, from_now=target == today, remember=False)
        now = guardian.now()
        data = plan.to_dict()
        data.update({
            "language": profile["language"],
            "today": today.isoformat(),
            "now": now.strftime("%H:%M") if target == today else None,
            "work_hours": profile["work_hours"] if plan.window else None,
            "focus": profile["focus"],
            "protected": [{"name": n, "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
                          for n, s, e in plan.protected],
            "tasks": [{"id": t.id, "name": t.name, "category": t.category, "est_min": t.est_min,
                       "priority": t.priority, "due": t.due.isoformat() if t.due else None}
                      for t in store.tasks(guardian.conn)],
        })
        return data

    return _guard(build)


@router.post("/tasks")
def add_task(body: NewTask):
    def build(plugin, guardian):
        due = plugin.parse_day(body.due, guardian.now().date()) if body.due else None
        return {"message": guardian.add(body.name, body.minutes, body.category, body.priority, due)}

    return _guard(build)


@router.post("/tasks/{task_id}/done")
def finish_task(task_id: int, body: Finished):
    return _guard(lambda plugin, guardian: {"message": guardian.done(str(task_id), body.minutes)})


# --- the week: the agenda this plugin keeps beside the calendar ------------------------------------------------

class Which(BaseModel):
    days: str = ""


@router.get("/week")
def get_week(week_of: str = ""):
    def build(plugin, guardian):
        return guardian.week_view(plugin.parse_day(week_of, guardian.now().date()) if week_of else None)

    return _guard(build)


@router.post("/proposals/{proposal_id}/ok")
def accept_proposal(proposal_id: int, body: Which):
    """The user's click on OK. Writing still needs the switch the user turned on with /day write on."""
    return _guard(lambda plugin, guardian: guardian.confirm(proposal_id, body.days))


@router.post("/proposals/{proposal_id}/refuse")
def refuse_proposal(proposal_id: int):
    return _guard(lambda plugin, guardian: guardian.refuse(proposal_id))


@router.post("/groups/{group_id}/undo")
def undo_group(group_id: int):
    return _guard(lambda plugin, guardian: guardian.undo(str(group_id)))
