"""Issue 7: ``/day set calendar="cmd:prog arg"`` typed in a chat. A quote that opens right after ``=`` closes at its pair, so the
value keeps its space; the guard and the dispatcher still read the same tokens (``sets_calendar``)."""
import pytest

from agenda_guardian import commands, guard


def calendar_after(make_guardian, raw):
    g = make_guardian()
    reply = commands.run(g, raw)
    return reply, g.profile()["calendar"]


@pytest.mark.parametrize("raw", ['set calendar="cmd:prog arg"', 'set "calendar=cmd:prog arg"', "set calendar='cmd:prog arg'"])
def test_both_quoting_forms_set_the_same_source(make_guardian, raw):
    reply, calendar = calendar_after(make_guardian, raw)
    assert calendar == {"type": "command", "argv": ["prog", "arg"]}, reply


def test_a_windows_path_keeps_its_backslashes_quoted_or_not(make_guardian):
    _, plain = calendar_after(make_guardian, r"set calendar=file:C:\cal\week.json")
    _, quoted = calendar_after(make_guardian, r'set calendar="file:C:\my cal\week.json"')
    assert "week.json" in plain["path"] and plain["type"] == "file"
    assert quoted["type"] == "file" and "my cal" in quoted["path"]


def test_other_settings_are_read_as_before(make_guardian):
    g = make_guardian()
    assert commands.run(g, "set protected=lunch@12:00-13:00,gym@17:00-18:00 buffer_min=5").startswith("!") is False
    assert [p["name"] for p in g.profile()["protected"]] == ["lunch", "gym"] and g.profile()["buffer_min"] == 5


def test_an_apostrophe_inside_a_word_does_not_open_a_quote(make_guardian):
    g = make_guardian()
    assert "!" not in commands.run(g, "add Don't forget the keys 10m")
    assert g.tasks_text().count("Don't forget the keys") == 1


def test_an_unclosed_quote_is_an_error_not_a_guess(make_guardian):
    reply, calendar = calendar_after(make_guardian, 'set calendar="cmd:prog arg')
    assert reply.startswith("!") and calendar == {"type": "none"}


@pytest.mark.parametrize("raw", ['set calendar="cmd:prog arg"', 'set "calendar=cmd:prog arg"', 'set work_hours=9-17 calendar="x y"'])
def test_dispatcher_and_guard_agree_that_these_set_the_calendar(raw):
    assert commands.sets_calendar(raw) is True
    assert commands.free_text(raw) == ""          # never handed to the agent


def test_the_guard_still_asks_for_a_side_road_to_the_calendar():
    decision = guard.check("terminal", {"command": 'hermes guardian set calendar="cmd:prog arg"'})
    assert decision is not None
