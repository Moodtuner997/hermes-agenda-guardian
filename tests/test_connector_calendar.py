"""A calendar behind an agent-side connector (``calendar=connector:<program>``): the plugin reads through the program and writes
nothing itself. ``day_confirm`` stages the exact tool calls, ``day_record`` records only what the calendar really shows.
The fake program below prints the events as JSON, like the connector's client does; ``agent_*`` plays the agent's tool calls."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import agenda_guardian as ag
from agenda_guardian import commands, store
from agenda_guardian.core import Guardian, UserError

from test_commands import Ctx

NOW = datetime(2026, 11, 9, 8, 0)


class FakeConnector:
    """The program behind ``calendar=connector:...``: a list of events, a switch to stop it, a log of every launch."""

    def __init__(self):
        self.events, self.launched, self.down, self.n = [], [], None, 0

    def __call__(self, argv, **kw):
        self.launched.append(list(argv))
        if self.down == "exit":
            return SimpleNamespace(returncode=1, stdout="", stderr="connector agenda: stopped or unreachable")
        if self.down == "missing":
            raise FileNotFoundError(argv[0])
        return SimpleNamespace(returncode=0, stdout=json.dumps([e for e in self.events if e.get("status") != "cancelled"]), stderr="")

    def add(self, summary, start, end, description="", **extra):
        self.n += 1
        event = {"id": f"ev{self.n:04d}", "summary": summary, "start": start, "end": end, "description": description,
                 "htmlLink": f"https://cal.test/ev{self.n}", "status": "confirmed", **extra}
        self.events.append(event)
        return event["id"]

    def agent_creates(self, call, **override):
        """What the connector does when the user accepts the staged call."""
        a = call["arguments"]
        return self.add(override.get("titre", a["titre"]), override.get("debut", a["debut"]), override.get("fin", a["fin"]),
                        override.get("description", a["description"]))

    def agent_deletes(self, event_id):
        next(e for e in self.events if e["id"] == event_id)["status"] = "cancelled"

    def writes(self):
        return [a for a in self.launched if any(x in ("create", "delete") for x in a)]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    program = FakeConnector()
    g = Guardian(tmp_path / "guardian.db", tmp_path, now=lambda: NOW, run=program)
    g.set_rules([("calendar", "connector:agenda-read --from {start} --to {end}"), ("language", "en")])
    g.kind_set("sport", 60, 0, 0, "18:00-20:00", "mon,tue,wed,thu")
    g.set_write(True)
    return SimpleNamespace(g=g, program=program, home=tmp_path)


def staged(world, count=1):
    proposal = world.g.propose("sport", count)
    return world.g.confirm(proposal["proposal_id"])


def test_connector_is_a_calendar_source_the_user_sets_and_no_tool_does(world, monkeypatch):
    assert world.g.profile()["calendar"] == {"type": "connector", "argv": ["agenda-read", "--from", "{start}", "--to", "{end}"]}
    monkeypatch.setattr(ag, "_guardian", lambda **kw: world.g)
    ctx = Ctx()
    ag.register(ctx)
    answer = json.loads(ctx.tools["day_setup"]({"settings": {"calendar": "connector:evil"}}))
    assert "refused" in answer["result"]
    assert world.g.profile()["calendar"]["argv"][0] == "agenda-read"


def test_the_plan_is_read_through_the_program(world):
    plan = world.g.propose("sport", 1)
    assert plan["sessions"]
    assert world.program.launched and world.program.launched[0][0] == "agenda-read"


def test_confirm_writes_nothing_itself_and_stages_the_exact_calls(world):
    done = staged(world, 2)
    assert done["ok"] and world.program.writes() == []
    assert done["handoff"] and [c["tool"] for c in done["handoff"]] == ["agenda_creer"] * len(done["handoff"])
    call = done["handoff"][0]["arguments"]
    assert set(call) == {"titre", "debut", "fin", "description"} and call["description"].startswith("[agenda-guardian:")
    assert "STAGED, NOTHING IS WRITTEN YET" in done["text"]
    assert store.written(world.g.conn) == []
    assert store.get_proposal(world.g.conn, 1)["status"] == "handoff"


def test_record_finds_nothing_until_the_user_accepted(world):
    done = staged(world)
    first = world.g.record()
    assert first["recorded"] == [] and first["waiting"] == len(done["handoff"]) and "not seen in your calendar" in first["text"]
    assert store.written(world.g.conn) == []


def test_record_writes_down_what_the_calendar_shows(world):
    done = staged(world)
    ids = [world.program.agent_creates(c) for c in done["handoff"]]
    result = world.g.record()
    assert len(result["recorded"]) == len(ids) and result["waiting"] == 0
    assert {r["event_id"] for r in store.written(world.g.conn)} == set(ids)
    assert world.g.record()["text"] == "Nothing waits to be recorded."


def test_record_ignores_an_event_with_the_wrong_times_or_no_marker(world):
    done = staged(world)
    call = done["handoff"][0]
    later = (datetime.fromisoformat(call["arguments"]["debut"]) + timedelta(hours=1)).isoformat()
    world.program.agent_creates(call, debut=later)
    world.program.agent_creates(call, description="no marker")
    world.program.add("Mine", call["arguments"]["debut"], call["arguments"]["fin"])
    world.program.agent_creates(call, description="[agenda-guardian:99:main] other group")
    result = world.g.record()
    assert result["recorded"] == [] and store.written(world.g.conn) == []


def test_record_lapses_after_a_day_instead_of_waiting_forever(world):
    staged(world)
    world.g._now = lambda: NOW + timedelta(days=2)
    result = world.g.record()
    assert result["lapsed"] == 1 and result["waiting"] == 0 and "set aside" in result["text"]
    assert world.g.record()["text"] == "Nothing waits to be recorded."


def test_groups_stay_distinct_while_calls_are_still_staged(world):
    first, second = staged(world), staged(world)
    groups = [c["arguments"]["description"].split(":")[1] for c in first["handoff"] + second["handoff"]]
    assert len(set(groups)) == 2


def test_undo_stages_removals_and_record_confirms_them_only_once_gone(world):
    done = staged(world)
    ids = [world.program.agent_creates(c) for c in done["handoff"]]
    world.g.record()
    undo = world.g.undo()
    assert [c["tool"] for c in undo["handoff"]] == ["agenda_supprimer"] * len(ids)
    assert {c["arguments"]["evenement"] for c in undo["handoff"]} == set(ids)
    assert all(c["arguments"]["prevenir"] is False for c in undo["handoff"]) and world.program.writes() == []
    again = world.g.undo()
    assert len(again["handoff"]) == len(ids) and len(store.pending_handoff(world.g.conn)) == len(ids)
    still = world.g.record()
    assert still["removed"] == [] and len(store.written(world.g.conn)) == len(ids)
    for i in ids:
        world.program.agent_deletes(i)
    gone = world.g.record()
    assert len(gone["removed"]) == len(ids) and store.written(world.g.conn) == []


def test_a_stopped_connector_is_an_error_never_an_empty_day(world):
    for mode in ("exit", "missing"):
        world.program.down = mode
        with pytest.raises(UserError, match="could not read"):
            world.g.propose("sport", 1)
    world.program.down = None


def test_record_with_a_stopped_connector_records_nothing(world):
    done = staged(world)
    world.program.agent_creates(done["handoff"][0])
    world.program.down = "exit"
    with pytest.raises(UserError, match="nothing was recorded"):
        world.g.record()
    assert store.written(world.g.conn) == []
    world.program.down = None
    assert world.g.record()["recorded"]


def test_day_record_is_a_tool_and_a_command_and_only_for_a_connector_calendar(world, tmp_path, monkeypatch):
    monkeypatch.setattr(ag, "_guardian", lambda **kw: world.g)
    ctx = Ctx()
    ag.register(ctx)
    assert "day_record" in ctx.tools and "record" in commands.DIRECT and "record" in commands.KNOWN
    assert json.loads(ctx.tools["day_record"]({}))["ok"] is True
    assert commands.run(world.g, "record") == "Nothing waits to be recorded."
    other = Guardian(tmp_path / "other.db", tmp_path, now=lambda: NOW, run=world.program)
    with pytest.raises(UserError, match="agenda connector"):
        other.record()


def test_the_rules_for_the_agent_name_the_exception_and_day_record():
    for lang in ("en", "fr"):
        assert "day_record" in ag.RULES[lang] and "handoff" in ag.RULES[lang]
