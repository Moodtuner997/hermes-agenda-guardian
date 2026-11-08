"""The calendar source names a program or an address that is run or read on every plan: only the user's own typed
command may set it. Every test pairs a refused case (an agent tool) with an accepted one (the user)."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

import agenda_guardian as ag
from agenda_guardian import commands, profile as prof
from agenda_guardian.core import Guardian

from conftest import MONDAY
from test_commands import Ctx
from test_onboarding import install_google

NOW = datetime(2026, 11, 9, 8, 0)
SOURCES = ["cmd:python -c \"print(1)\"", "ics:https://example.com/a.ics", "file:/tmp/a.json", "google", "none", "off"]
SPELLINGS = ["calendar", "Calendar", " calendar ", "CALENDAR"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """One guardian behind the tools and the /day command; every program it launches is recorded."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    launched = []

    def run(argv, **kw):
        launched.append(argv)
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    g = Guardian(tmp_path / "guardian.db", tmp_path, now=lambda: NOW, run=run)
    monkeypatch.setattr(ag, "_guardian", lambda **kw: g)
    ctx = Ctx()
    ag.register(ctx)
    tool = lambda name, args: json.loads(ctx.tools[name](args))
    return SimpleNamespace(g=g, tool=tool, slash=ctx.commands["day"], launched=launched, home=tmp_path)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("key", SPELLINGS)
def test_a_tool_cannot_set_the_calendar_in_any_spelling(world, key, source):
    answer = world.tool("day_setup", {"settings": {key: source}})
    assert "refused" in answer["result"] and "yours to choose" in answer["result"]
    assert "no tool ever sets it" in answer["for_agent"] and "/day set calendar=" in answer["for_agent"]
    assert world.g.profile()["calendar"] == {"type": "none"} and "calendar" not in world.g.profile()["_set"]
    assert world.launched == []


def test_the_other_settings_of_the_same_call_still_apply_and_the_refusal_is_said(world):
    answer = world.tool("day_setup", {"settings": {"work_hours": "09:00-17:00", "Calendar": "cmd:mycal",
                                                   "buffer_min": "5"}})
    lines = answer["result"].splitlines()
    assert [line.split()[0] for line in lines] == ["ok", "refused", "ok"] and "refused  Calendar:" in lines[1]
    profile = world.g.profile()
    assert profile["work_hours"] == ["09:00", "17:00"] and profile["buffer_min"] == 5
    assert profile["calendar"] == {"type": "none"}
    assert "for_agent" in answer


def test_a_call_without_the_calendar_key_has_no_calendar_advice(world):
    answer = world.tool("day_setup", {"settings": {"buffer_min": "5"}})
    assert answer["result"].startswith("ok  buffer_min") and "for_agent" not in answer


def test_adopt_from_a_tool_takes_language_and_time_zone_but_leaves_the_calendar(world):
    install_google(world.home)
    (world.home / "config.yaml").write_text("timezone: Europe/Paris\n", encoding="utf-8")
    answer = world.tool("day_setup", {"adopt": True})
    assert "timezone = Europe/Paris" in answer["result"] and "Calendar left to you" in answer["result"]
    assert world.g.profile()["calendar"] == {"type": "none"}
    facts = world.tool("day_setup", {})["found"]
    assert facts["google_calendar"] == "ready" and "calendar" not in facts["can_adopt"]


def test_the_user_adopts_the_google_calendar_with_a_typed_command(world, monkeypatch):
    install_google(world.home)
    world.g._run = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="[]", stderr="")
    assert "ok  calendar = google" in world.slash("setup auto")
    assert world.g.profile()["calendar"] == {"type": "google"}


def test_apply_setting_refuses_the_calendar_only_when_the_call_comes_from_a_tool(profile):
    with pytest.raises(ValueError, match="yours to choose"):
        prof.apply_setting(profile, "CALENDAR", "google", MONDAY, from_tool=True)
    assert profile["calendar"] == {"type": "none"}
    prof.apply_setting(profile, " Calendar ", "cmd:mycal --from {start}", MONDAY)
    assert profile["calendar"] == {"type": "command", "argv": ["mycal", "--from", "{start}"]}
    assert prof.normal_key(" Calendar ") == "calendar" and prof.normal_key("Max-Block_Min") == "max_block_min"


def test_no_other_setting_can_name_a_program_or_a_path(profile):
    def walk(value):  # every dict key, however deep
        for item in (value.values() if isinstance(value, dict) else value if isinstance(value, list) else []):
            yield from walk(item)
        if isinstance(value, dict):
            yield from value

    for key in prof.KEYS:
        if key != "calendar":
            try:
                prof.apply_setting(profile, key, "cmd:evil ../../evil", MONDAY, from_tool=True)
            except ValueError:
                pass
    assert profile["calendar"] == {"type": "none"}
    assert not {"argv", "path", "command"} & set(walk(profile))
    typed = prof.new_profile()  # the walk does see a program when the user's own command set one
    prof.apply_setting(typed, "calendar", "cmd:mycal", MONDAY)
    assert "argv" in set(walk(typed))


def event(text):
    return SimpleNamespace(text=text)


def test_the_users_own_calendar_command_is_answered_directly_never_through_the_agent(world):
    for typed in ("set calendar=cmd:mycal", "set work_hours=09:00-17:00 CALENDAR=google", 'set " calendar =cmd:mycal"',
                  "set Calendar=none", "setup auto"):
        assert commands.sets_calendar(typed) and commands.free_text(typed) == ""
        assert ag._plain_words(event(f"/day {typed}")) is None  # the gateway hook leaves it to the dispatcher
    assert ag._plain_words(event("/day@my_bot set calendar=google")) is None
    answer = world.slash("set work_hours=09:00-17:00 calendar=cmd:mycal")
    assert answer.count("ok  ") == 2 and "refused" not in answer  # the user is not refused as a tool is
    assert world.g.profile()["calendar"] == {"type": "command", "argv": ["mycal"]} and world.launched == []


def test_the_rest_of_set_and_setup_still_goes_to_the_agent(world):
    for typed in ("set work_hours=09:00-19:00", "set buffer_min=5 language=fr", "setup", "setup tomorrow",
                  "calendar is google please", "set calendar", "set calendar:google"):
        assert not commands.sets_calendar(typed) and commands.free_text(typed) == typed
    sentence = ag._plain_words(event("/day set work_hours=09:00-19:00"))
    assert sentence["action"] == "rewrite" and sentence["text"].endswith("set work_hours=09:00-19:00")


def test_an_unbalanced_quote_in_a_calendar_command_is_not_handed_to_the_agent(world):
    typed = 'set calendar="cmd:mycal'
    assert commands.sets_calendar(typed) and commands.free_text(typed) == ""
