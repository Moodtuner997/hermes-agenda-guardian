"""A calendar program (the Google skill's script or the user's own) starts with the basics and the profile folder, never
with the provider keys the Hermes process holds."""

import subprocess
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

from agenda_guardian import profile as prof, store, writer
from agenda_guardian.sources import _child_env, fetch_events

from conftest import MONDAY
from fakegoogle import FakeGoogle, install_script

DECOYS = {"ANTHROPIC_API_KEY": "sk-ant-decoy", "OPENAI_API_KEY": "sk-decoy", "GITHUB_TOKEN": "ghp_decoy",
          "MA_CLE_DE_TEST": "decoy", "HTTPS_PROXY": "http://proxy.invalid:3128", "PYTHONPATH": "/somewhere",
          "AWS_SECRET_ACCESS_KEY": "decoy"}
BASICS = {"PATH": "/usr/bin", "HOME": "/home/me", "LANG": "fr_FR.UTF-8", "LC_ALL": "fr_FR.UTF-8", "TZ": "Europe/Paris"}


@pytest.fixture
def environ(monkeypatch):
    for key, value in {**DECOYS, **BASICS, "HERMES_HOME": "/elsewhere"}.items():
        monkeypatch.setenv(key, value)


def recorder(reply="[]"):
    seen = []

    def run(argv, **kw):
        seen.append(kw)
        return SimpleNamespace(returncode=0, stdout=reply, stderr="")

    run.seen = seen
    return run


def assert_minimal(env, home):
    assert not set(DECOYS) & set(env), f"leaked: {sorted(set(DECOYS) & set(env))}"
    assert env["HERMES_HOME"] == str(home)  # the folder given, not the one the parent happened to hold
    assert {key: env[key] for key in BASICS} == BASICS


def test_a_command_source_gets_no_provider_key(environ, tmp_path):
    run = recorder()
    profile = prof.new_profile()
    profile["calendar"] = {"type": "command", "argv": ["mycal"]}
    fetch_events(profile, MONDAY, tmp_path, run=run)
    assert len(run.seen) == 1 and run.seen[0]["shell"] is False
    assert_minimal(run.seen[0]["env"], tmp_path)


def test_the_google_script_gets_the_same_minimal_environment_and_its_home(environ, tmp_path):
    install_script(tmp_path)
    run = recorder()
    profile = prof.new_profile()
    profile["calendar"] = {"type": "google"}
    fetch_events(profile, MONDAY, tmp_path, run=run)
    assert_minimal(run.seen[0]["env"], tmp_path)


def test_every_write_to_the_calendar_gets_the_same_environment(environ, tmp_path):
    install_script(tmp_path)
    run = recorder(reply='{"id": "e1", "htmlLink": "https://cal/e1"}')
    start, end = datetime(2026, 11, 9, 18, 0), datetime(2026, 11, 9, 19, 0)
    assert writer.create(tmp_path, "", "primary", "Sport", start, end, "[agenda-guardian:1:a]", run=run)[0] == "e1"
    assert_minimal(run.seen[0]["env"], tmp_path)
    run.seen.clear()
    writer._live(tmp_path, "", "primary", start, end, run=recorder())  # the lookup before a delete
    cal = FakeGoogle()
    calls = []

    def spy(argv, **kw):
        calls.append(kw["env"])
        return cal(argv, **kw)

    cal.add("Sport", start, end, "[agenda-guardian:1:a]", event_id="e1")
    conn = store.connect(tmp_path / "w.db")
    store.record_written(conn, {"event_id": "e1", "calendar_id": "primary", "group_id": 1, "kind": "sport",
                                "part": "a", "summary": "Sport", "start": start.isoformat(), "end": end.isoformat()}, start)
    assert writer.remove(conn, tmp_path, "", "e1", start, run=spy) == "deleted"
    assert len(calls) == 2 and all(env["HERMES_HOME"] == str(tmp_path) for env in calls)  # the lookup, then the delete
    for env in calls:
        assert_minimal(env, tmp_path)


def test_the_basics_a_program_needs_stay_and_nothing_else_does(tmp_path):
    parent = {**DECOYS, **BASICS, "LC_TIME": "en_GB", "LANGUAGE": "fr", "TERM": "xterm", "SHELL": "/bin/zsh"}
    env = _child_env(tmp_path, parent, windows=False)
    assert env == {**BASICS, "LC_TIME": "en_GB", "HERMES_HOME": str(tmp_path)}


def test_windows_keeps_the_variables_without_which_python_and_sockets_fail(tmp_path):
    parent = {**DECOYS, "PATH": "C:\\bin", "SYSTEMROOT": "C:\\WINDOWS", "TEMP": "C:\\t", "TMP": "C:\\t",
              "USERPROFILE": "C:\\Users\\me", "PATHEXT": ".EXE", "COMSPEC": "C:\\cmd.exe", "APPDATA": "C:\\a",
              "OPENAI_API_KEY": "decoy"}
    env = _child_env(tmp_path, parent, windows=True)
    assert set(env) == {"PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "PATHEXT", "COMSPEC", "HERMES_HOME"}
    assert "SYSTEMROOT" not in _child_env(tmp_path, parent, windows=False)  # a POSIX parent has none to pass


def test_a_real_python_starts_and_resolves_names_with_the_minimal_environment(tmp_path):
    """Known good on this machine, whatever it is: the child can import the network stack and resolve a name."""
    code = "import ssl, socket, json, urllib.request, tempfile; socket.getaddrinfo('localhost', 80); print('ok')"
    done = subprocess.run([sys.executable, "-c", code], env=_child_env(tmp_path), capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.strip() == "ok", done.stderr[-300:]


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows loader needs SYSTEMROOT for name resolution")
def test_windows_without_systemroot_cannot_resolve_names(tmp_path):
    """Known bad: the reason SYSTEMROOT is on the list (measured on Windows 11)."""
    import os

    code = "import socket; socket.getaddrinfo('localhost', 80); print('ok')"
    bare = {"PATH": os.environ["PATH"], "HOME": str(tmp_path)}
    assert subprocess.run([sys.executable, "-c", code], env=bare, capture_output=True, text=True).returncode != 0
