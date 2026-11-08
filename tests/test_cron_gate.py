"""A cron run may not create or remove scheduled jobs unless cron.allow_agent_scheduling is true: the same rule Hermes
applies to the cronjob toolset, kept for the plugin tool that reaches the registry from the side."""

import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import agenda_guardian as ag
from agenda_guardian import commands, core

from conftest import ROOT
from test_commands import Ctx
from test_proactive import FakeCron


def session(monkeypatch, cron: bool, allowed: bool):
    monkeypatch.setattr(core, "in_cron_session", lambda: cron)
    monkeypatch.setattr(core, "cron_scheduling_allowed", lambda: allowed)


def fake_module(monkeypatch, dotted: str, **attrs):
    parts = dotted.split(".")
    for i in range(1, len(parts) + 1):
        name = ".".join(parts[:i])
        if name not in sys.modules or i == len(parts):
            monkeypatch.setitem(sys.modules, name, ModuleType(name))
    for key, value in attrs.items():
        setattr(sys.modules[dotted], key, value)


@pytest.mark.parametrize("typed", ["cron on", "cron on 07:30", "cron off"])
def test_a_cron_run_cannot_schedule_unless_the_setting_is_true(make_guardian, monkeypatch, typed):
    cron = FakeCron([{"job_id": "a1", "name": "agenda-guardian-brief"}])
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    session(monkeypatch, cron=True, allowed=False)
    answer = commands.run(g, typed)
    assert answer.startswith("! Scheduling is refused inside a cron run") and "cron.allow_agent_scheduling" in answer
    assert cron.calls == []  # the cron tool was never reached, not even to list


def test_the_refusal_comes_back_to_the_agent_as_a_tool_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    ctx = Ctx()
    ag.register(ctx)
    ctx.dispatch_tool = lambda name, args: pytest.fail("the cron tool was reached")
    ag._CTX = ctx
    session(monkeypatch, cron=True, allowed=False)
    for action in ("on", "off"):
        answer = json.loads(ctx.tools["day_schedule"]({"action": action}))
        assert answer["ok"] is False and "refused inside a cron run" in answer["error"]


def test_a_french_session_gets_the_refusal_in_french(make_guardian, monkeypatch):
    g = make_guardian(cron=FakeCron(), plugin_dir=ROOT)
    commands.run(g, "set language=fr")
    session(monkeypatch, cron=True, allowed=False)
    assert commands.run(g, "cron on").startswith("! La planification est refusée dans une exécution de cron")


@pytest.mark.parametrize("typed, calls", [("cron on", ["list", "create", "create"]), ("cron off", ["list", "remove"])])
def test_a_cron_run_may_schedule_when_the_setting_is_true(make_guardian, monkeypatch, typed, calls):
    cron = FakeCron([{"job_id": "a1", "name": "agenda-guardian-brief"}] if typed == "cron off" else [])
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    session(monkeypatch, cron=True, allowed=True)
    assert not commands.run(g, typed).startswith("!")
    assert [c["action"] for c in cron.calls] == calls


@pytest.mark.parametrize("typed", ["cron on", "cron off"])
def test_outside_a_cron_run_nothing_changes_and_the_setting_is_not_even_read(make_guardian, monkeypatch, typed):
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    monkeypatch.setattr(core, "in_cron_session", lambda: False)
    monkeypatch.setattr(core, "cron_scheduling_allowed", lambda: pytest.fail("the config was read outside a cron run"))
    assert not commands.run(g, typed).startswith("!")
    assert cron.calls


def test_status_stays_available_in_a_cron_run(make_guardian, monkeypatch):
    cron = FakeCron([{"job_id": "a1", "name": "agenda-guardian-brief"}])
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    session(monkeypatch, cron=True, allowed=False)
    assert commands.run(g, "cron status") == "Scheduled: agenda-guardian-brief"
    assert [c["action"] for c in cron.calls] == ["list"]


@pytest.mark.parametrize("session_value, environ_value, expected", [
    ("1", "", True), ("true", "", True), ("YES", "", True), ("on", "", True),   # the session variable says cron
    ("", "1", False),             # a value left in os.environ by another run does not make this chat a cron run
    ("0", "1", False), ("false", "", False), ("", "", False),
])
def test_the_session_variable_wins_over_the_environment(monkeypatch, session_value, environ_value, expected):
    seen = {}

    def get_session_env(name, default=""):
        seen["name"] = name
        return session_value

    fake_module(monkeypatch, "gateway.session_context", get_session_env=get_session_env)
    monkeypatch.setenv("HERMES_CRON_SESSION", environ_value)
    assert core.in_cron_session() is expected and seen["name"] == "HERMES_CRON_SESSION"


@pytest.mark.parametrize("environ_value, expected", [("1", True), ("true", True), ("", False), ("0", False)])
def test_without_the_hermes_session_module_the_environment_is_read(monkeypatch, environ_value, expected):
    monkeypatch.setitem(sys.modules, "gateway.session_context", None)  # an import error, as outside Hermes
    monkeypatch.setenv("HERMES_CRON_SESSION", environ_value)
    assert core.in_cron_session() is expected


@pytest.mark.parametrize("config, expected", [
    ({"cron": {"allow_agent_scheduling": True}}, True),
    ({"cron": {"allow_agent_scheduling": False}}, False),
    ({"cron": {}}, False), ({"cron": None}, False), ({}, False), (None, False),
    ({"cron": "oops"}, False),   # a config that is not what Hermes writes is read as "not allowed"
])
def test_the_setting_is_read_through_the_hermes_loader(monkeypatch, config, expected):
    fake_module(monkeypatch, "hermes_cli.config", load_config=lambda: config)
    assert core.cron_scheduling_allowed() is expected


def test_an_unreadable_config_means_refused(monkeypatch):
    def broken():
        raise OSError("config.yaml is locked")

    fake_module(monkeypatch, "hermes_cli.config", load_config=broken)
    assert core.cron_scheduling_allowed() is False
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)  # no Hermes at all
    assert core.cron_scheduling_allowed() is False


def test_a_cron_run_with_an_unreadable_config_is_refused_end_to_end(make_guardian, monkeypatch):
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    fake_module(monkeypatch, "gateway.session_context", get_session_env=lambda name, default="": "1")
    monkeypatch.setitem(sys.modules, "hermes_cli.config", None)
    assert "refused inside a cron run" in commands.run(g, "cron on") and cron.calls == []
