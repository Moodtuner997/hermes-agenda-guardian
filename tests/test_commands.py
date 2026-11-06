import json
from datetime import datetime

import pytest

import agenda_guardian
from agenda_guardian import commands, profile as prof
from agenda_guardian.core import UserError, parse_day, parse_minutes

from conftest import MONDAY


def write_calendar(tmp_path, events):
    path = tmp_path / "cal.json"
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


def test_durations_and_days_are_understood():
    assert [parse_minutes(t) for t in ("45", "45m", "1h", "1h30", "2h15m", "90 min")] == [45, 45, 60, 90, 135, 90]
    with pytest.raises(UserError):
        parse_minutes("soon")
    assert parse_day("tomorrow", MONDAY).day == 10 and parse_day("+3", MONDAY).day == 12
    assert parse_day("fri", MONDAY).day == 13 and parse_day("mon", MONDAY) == MONDAY
    assert parse_day("2026-12-01", MONDAY).month == 12
    with pytest.raises(UserError):
        parse_day("someday", MONDAY)


def test_settings_validate_and_remember_where_they_came_from(profile):
    today = MONDAY
    prof.apply_setting(profile, "work_hours", "08:30-17:00", today)
    prof.apply_setting(profile, "workdays", "mon-thu", today)
    prof.apply_setting(profile, "protected", "lunch@12:00-13:00,gym@17:00-18:00", today)
    prof.apply_setting(profile, "category", "Admin:20", today)
    assert profile["work_hours"] == ["08:30", "17:00"] and profile["workdays"] == [1, 2, 3, 4]
    assert [p["name"] for p in profile["protected"]] == ["lunch", "gym"] and profile["categories"] == {"admin": 20}
    assert prof.source_of(profile, "work_hours") == "you set it on 2026-11-09"
    assert prof.source_of(profile, "focus").startswith("default")
    for key, value in [("work_hours", "17:00-09:00"), ("work_hours", "9h-17h"), ("buffer_min", "500"),
                       ("protected", "lunch"), ("workdays", "funday"), ("calendar", "outlook"), ("nope", "1")]:
        with pytest.raises(ValueError):
            prof.apply_setting(profile, key, value, today)


def test_a_local_calendar_path_is_stored_absolute(profile, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "cal.json").write_text("[]", encoding="utf-8")
    prof.apply_setting(profile, "calendar", "file:cal.json", MONDAY)
    assert profile["calendar"]["path"] == str((tmp_path / "cal.json").resolve())
    prof.apply_setting(profile, "calendar", "ics:https://example.com/a.ics", MONDAY)
    assert profile["calendar"]["path"] == "https://example.com/a.ics"


def test_full_session_from_onboarding_to_calibrated_plan(make_guardian, tmp_path):
    g = make_guardian()
    cal = write_calendar(tmp_path, [{"summary": "Client call", "start": "2026-11-09T10:30:00",
                                     "end": "2026-11-09T11:00:00"}])
    assert "work_hours" in commands.run(g, "setup") and "Typical minutes" in commands.run(g, "setup")
    out = commands.run(g, f"set work_hours=09:00-17:00 calendar=file:{cal} category=writing:60")
    assert out.count("ok  ") == 3
    assert commands.run(g, 'add "Write the quote" 45m cat=writing p=1 due=tomorrow').startswith("Added #1")

    plan = commands.run(g, "plan")
    assert "Write the quote" in plan and "09:00-09:45" in plan and "Client call" in plan
    assert "work hours 09:00-17:00 (you set it on 2026-11-09)" in plan and "Rules used:" in plan

    assert "calibration starts at 3" in commands.run(g, "done 1 90")
    for name in ("Draft A", "Draft B"):
        commands.run(g, f'add "{name}" 45m cat=writing')
    commands.run(g, "done 2 90")
    assert "now multiplied by 2" in commands.run(g, "done Draft B 90")

    commands.run(g, 'add "Next piece" 30m cat=writing p=1')
    plan = commands.run(g, "plan")
    assert "30 x 2" in plan and "median of 3" in plan
    assert commands.run(g, "list").startswith("#4 Next piece - 30 min x2")


def test_missing_estimate_and_missing_real_time_are_asked_for(make_guardian):
    g = make_guardian()
    assert "How long do you think" in commands.run(g, 'add "Write the quote"')
    commands.run(g, 'add "Write the quote" 30m')
    assert "How long did" in commands.run(g, "done 1")
    assert "no open task" in commands.run(g, "done 9 20")
    commands.run(g, 'add "Write the quote again" 30m')
    assert "matches several" in commands.run(g, "done quote 20")


def test_category_typical_minutes_fill_a_missing_estimate(make_guardian):
    g = make_guardian()
    commands.run(g, "set category=admin:20")
    assert "20 min, admin" in commands.run(g, 'add "File expenses" cat=admin')


def test_bad_settings_are_refused_line_by_line(make_guardian):
    g = make_guardian()
    out = commands.run(g, "set work_hours=25:00-26:00 buffer_min=15")
    assert "refused  work_hours" in out and "ok  buffer_min" in out


def test_unreadable_calendar_is_a_loud_warning_not_an_empty_day(make_guardian, tmp_path):
    g = make_guardian()
    commands.run(g, f"set calendar=file:{tmp_path / 'missing.json'}")
    commands.run(g, 'add "Task" 30m')
    assert "Calendar unreadable" in commands.run(g, "plan") and "ignores your meetings" in commands.run(g, "plan")


def test_now_says_what_is_current_or_next(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 9, 20))
    commands.run(g, 'add "Write the quote" 45m p=1')
    assert commands.run(g, "now").startswith("Now: Write the quote until 10:05")
    g = make_guardian(now=datetime(2026, 11, 9, 8, 0))
    assert commands.run(g, "now").startswith("Next: Write the quote at 09:00")


def test_brief_turns_to_tomorrow_after_work_hours(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 19, 0))  # Monday evening
    commands.run(g, 'add "Write the quote" 45m')
    assert "Plan for Tue 2026-11-10" in commands.run(g, "brief")
    g = make_guardian(now=datetime(2026, 11, 9, 7, 30))
    assert "Plan for Mon 2026-11-09" in commands.run(g, "brief")


def test_french_brief(make_guardian):
    g = make_guardian()
    commands.run(g, "set language=fr")
    commands.run(g, 'add "Rédiger le devis" 45m')
    plan = commands.run(g, "plan")
    assert "Plan du lun. 2026-11-09" in plan and "pourquoi" in plan


class Ctx:
    def __init__(self):
        self.commands, self.cli, self.tools, self.hooks = {}, {}, {}, {}

    def register_command(self, name, handler, **kw):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn):
        self.cli[name] = handler_fn

    def register_hook(self, name, callback, **kw):
        self.hooks[name] = callback

    def register_tool(self, name, toolset, schema, handler, **kw):
        assert schema["name"] == name and schema["parameters"]["type"] == "object"
        self.tools[name] = handler


def test_registration_and_tools_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = Ctx()
    agenda_guardian.register(ctx)
    assert set(ctx.commands) == {"day"} and set(ctx.cli) == {"guardian"}
    assert set(ctx.tools) == {"day_setup", "day_add_task", "day_plan", "day_done", "day_tasks", "day_schedule",
                              "day_kind", "day_habit", "day_propose", "day_confirm", "day_undo", "day_took",
                              "day_week", "day_week_plan", "day_stage"}
    assert set(ctx.hooks) == {"pre_gateway_dispatch"}

    call = lambda name, args: json.loads(ctx.tools[name](args))
    assert call("day_setup", {})["questions"].startswith("Agenda guardian setup")
    assert call("day_setup", {"settings": {"buffer_min": "5"}})["result"].startswith("ok  buffer_min")
    added = call("day_add_task", {"name": "Write the quote", "minutes": 45, "priority": 1})
    assert added["ok"] and added["message"].startswith("Added #1")
    assert "Write the quote" in call("day_plan", {})["plan"]
    refused = call("day_add_task", {"name": "No estimate"})
    assert refused["ok"] is False and "How long" in refused["error"]
    assert call("day_done", {"task": "1", "actual_minutes": 60})["ok"]
    assert "calendar" in ctx.commands["day"]("setup")
    assert (tmp_path / "plugin-data" / "agenda-guardian" / "guardian.db").exists()


def test_no_tool_can_switch_calendar_writing_on(tmp_path, monkeypatch):
    """Only the user's own typed command turns writing on: the agent has no tool or setting for it."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = Ctx()
    agenda_guardian.register(ctx)
    call = lambda name, args: json.loads(ctx.tools[name](args))
    assert not [n for n in ctx.tools if "write" in n]
    refused = call("day_setup", {"settings": {"calendar_write": "on"}})
    assert "unknown setting" in refused["result"] and "refused" in refused["result"]
    blocked = call("day_confirm", {"proposal_id": 1})
    assert blocked["ok"] is False and "write on" in blocked["error"]
    assert "Writing is off" in ctx.commands["day"]("write status")


def test_day_kind_saves_when_given_numbers_without_an_action(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = Ctx()
    agenda_guardian.register(ctx)
    call = lambda name, args: json.loads(ctx.tools[name](args))
    saved = call("day_kind", {"name": "sport", "real_minutes": 120, "before_minutes": 15, "after_minutes": 30,
                              "window": "18:00-22:00", "days": "mon,thu"})
    assert saved["ok"] and saved["kind"]["name"] == "sport" and saved["kind"]["weekdays"] == [1, 4]
    assert [k["name"] for k in call("day_kind", {})["kinds"]] == ["sport"]
    assert call("day_kind", {"name": "sport"})["kinds"][0]["real_minutes"] == 120  # no numbers: it is a lookup
    assert call("day_kind", {"action": "remove", "name": "sport"})["ok"]
    assert call("day_kind", {"action": "set", "name": "sport"})["ok"] is False  # numbers are never guessed
