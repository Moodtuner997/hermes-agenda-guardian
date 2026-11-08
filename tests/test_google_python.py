"""The Google skill's script runs on an interpreter that can import its libraries.

Under a managed Hermes (0.23) the running interpreter, ``sys.executable``, is the store's base Python and only the
dependency environment is on ``sys.path``: the base interpreter cannot import ``googleapiclient``, the environment's own
``python`` can. The end-to-end tests use ``fakegoogle.py``, which imports nothing, so they never saw it."""

import importlib
import importlib.util
import os
import subprocess
import sys
import venv
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agenda_guardian import sources
from agenda_guardian import writer
from agenda_guardian.sources import (SourceError, _child_env, _run_json, google_argv, google_python,
                                      run_google)

from fakegoogle import install_script

POSIX = ("lib/python3.14/site-packages", "bin/python")
WINDOWS = ("Lib/site-packages", "Scripts/python.exe")


def environment(root: Path, layout=POSIX, *, config=True, python=True, site=None) -> Path:
    """A virtual-environment folder holding a fake library; returns the library's own folder."""
    where, interpreter = layout
    library = root / (site or where) / "googleapiclient"
    library.mkdir(parents=True)
    (library / "__init__.py").write_text("", encoding="utf-8")
    if config:
        (root / "pyvenv.cfg").write_text("home = /store\n", encoding="utf-8")
    if python:
        (root / interpreter).parent.mkdir(parents=True, exist_ok=True)
        (root / interpreter).write_text("", encoding="utf-8")
    return library


def found_in(library: Path):
    return lambda name: SimpleNamespace(submodule_search_locations=[str(library)])


@pytest.mark.parametrize("layout", [POSIX, WINDOWS], ids=["posix", "windows"])
def test_the_environment_that_holds_the_library_is_the_one_run(tmp_path, layout):
    library = environment(tmp_path / "env", layout)
    chosen = google_python(found_in(library), executable="/store/bin/python3", prefix="/store")
    assert chosen == str(tmp_path / "env" / layout[1])


def test_a_process_already_on_that_environment_keeps_its_own_interpreter(tmp_path):
    library = environment(tmp_path / "env")
    assert google_python(found_in(library), executable="/venv/bin/python", prefix=str(tmp_path / "env")) == "/venv/bin/python"


@pytest.mark.parametrize("case", ["no library", "dist-packages", "a source checkout", "no pyvenv.cfg", "no interpreter",
                                  "a zip or no folder", "the finder fails", "the finder breaks"])
def test_any_other_case_runs_the_interpreter_that_is_running(tmp_path, case):
    base = {"executable": "/store/bin/python3", "prefix": "/store"}
    if case == "no library":
        finder = lambda name: None
    elif case == "dist-packages":
        finder = found_in(environment(tmp_path / "env", site="lib/python3.14/dist-packages"))
    elif case == "a source checkout":
        finder = found_in(environment(tmp_path / "env", site="lib/python3.14/src"))
    elif case == "no pyvenv.cfg":
        finder = found_in(environment(tmp_path / "env", config=False))
    elif case == "no interpreter":
        finder = found_in(environment(tmp_path / "env", python=False))
    elif case == "a zip or no folder":
        finder = lambda name: SimpleNamespace(submodule_search_locations=None)
    elif case == "the finder fails":
        def finder(name):
            raise ValueError("googleapiclient.__spec__ is None")
    else:
        def finder(name):
            raise RuntimeError("anything a third-party finder does")
    assert google_python(finder, **base) == "/store/bin/python3"


def test_google_argv_names_the_environment_python(tmp_path, monkeypatch):
    """The whole road: what ``fetch_range`` and the writer receive as the interpreter."""
    home = tmp_path / "home"
    install_script(home)
    library = environment(tmp_path / "env")
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *rest: found_in(library)(name) if name == "googleapiclient" else real(name, *rest))
    argv = google_argv(home, "calendar", "list")
    assert argv[0] == str(tmp_path / "env" / "bin" / "python")
    assert argv[2:] == ["calendar", "list"]


def test_a_real_second_interpreter_imports_what_the_running_one_cannot(tmp_path, monkeypatch):
    """Two real interpreters: the library lives only in a virtual environment that is on this process's search path,
    as the managed environment is on Hermes'. The choice must be the one that imports it, with the minimal child
    environment and no PYTHONPATH."""
    name = "hermes_fake_google_library"  # not the real name: a machine that has the real library must not hide the case
    monkeypatch.setattr(sources, "GOOGLE_LIBRARY", name)
    env = tmp_path / "env"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(env)  # as `python -m venv` does
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    purelib = subprocess.run([str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                             capture_output=True, text=True, check=True).stdout.strip()
    library = Path(purelib) / name
    library.mkdir(parents=True)
    (library / "__init__.py").write_text("MARK = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(purelib)
    child = _child_env(tmp_path)
    assert "PYTHONPATH" not in child
    # a shared libpython (a CI runner's) is found through these; they are no part of the choice under test
    child.update({key: os.environ[key] for key in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH") if key in os.environ})
    probe = ["-c", f"import {name}"]
    without = subprocess.run([sys.executable, *probe], env=child, capture_output=True, text=True)
    assert without.returncode != 0 and "No module named" in without.stderr  # it started and could not import
    chosen = google_python()
    assert chosen == str(python)
    assert subprocess.run([chosen, *probe], env=child, capture_output=True, text=True).returncode == 0


def failing(stderr: str):
    return lambda argv, **_: SimpleNamespace(returncode=1, stdout="", stderr=stderr)


@pytest.mark.parametrize("last", ["ModuleNotFoundError: No module named 'googleapiclient'",
                                  "ModuleNotFoundError: No module named 'google.oauth2'",
                                  "ModuleNotFoundError: No module named 'google_auth_oauthlib'"])
def test_a_missing_google_library_says_what_to_do(tmp_path, last):
    stderr = f"Traceback (most recent call last):\n  File \"google_api.py\", line 3, in <module>\n{last}\n"
    with pytest.raises(SourceError) as error:
        _run_json(["python", "google_api.py"], failing(stderr), tmp_path, google=True)
    text = str(error.value)
    assert last.split(": ", 1)[1] in text
    assert "--install-deps" in text and "restart Hermes" in text


def test_any_other_failure_keeps_its_plain_message(tmp_path):
    with pytest.raises(SourceError, match="calendar program exited 1: boom"):
        _run_json(["x"], failing("boom\n"), tmp_path)
    with pytest.raises(SourceError, match="calendar program exited 1: ModuleNotFoundError: No module named 'yaml'"):
        _run_json(["x"], failing("ModuleNotFoundError: No module named 'yaml'\n"), tmp_path)


def test_a_cmd_source_is_not_blamed_on_the_google_skill(tmp_path):
    with pytest.raises(SourceError, match="calendar program exited 1: ModuleNotFoundError: No module named 'google.cloud'"):
        _run_json(["mycalendar"], failing("ModuleNotFoundError: No module named 'google.cloud'\n"), tmp_path)


def runner(starts, payload="[]"):
    """Starts only the interpreters named in ``starts``; any other raises as the system does for a file it cannot run."""
    calls = []

    def run(argv, **_):
        calls.append(list(argv))
        if argv[0] not in starts:
            raise PermissionError(13, "Permission denied")
        return SimpleNamespace(returncode=0, stdout=payload, stderr="")

    run.calls = calls
    return run


@pytest.fixture
def chosen(tmp_path, monkeypatch):
    install_script(tmp_path)
    path = str(tmp_path / "env" / "bin" / "python")
    monkeypatch.setattr(sources, "google_python", lambda: path)
    return path


def test_an_interpreter_that_cannot_start_gives_way_to_the_running_one(tmp_path, chosen):
    run = runner({sys.executable})
    assert run_google(tmp_path, "calendar", "list", run=run) == []
    assert [call[0] for call in run.calls] == [chosen, sys.executable]
    assert run.calls[0][1:] == run.calls[1][1:]


def test_when_nothing_starts_the_error_is_a_source_error(tmp_path, chosen):
    run = runner(set())
    with pytest.raises(SourceError, match="could not start: python"):
        run_google(tmp_path, "calendar", "list", run=run)
    assert len(run.calls) == 2


def test_the_running_interpreter_is_not_tried_twice(tmp_path, monkeypatch):
    install_script(tmp_path)
    monkeypatch.setattr(sources, "google_python", lambda: sys.executable)
    run = runner(set())
    with pytest.raises(SourceError, match="could not start"):
        run_google(tmp_path, "calendar", "list", run=run)
    assert len(run.calls) == 1


def test_a_script_that_ran_and_failed_is_never_run_again(tmp_path, chosen):
    calls = []

    def run(argv, **_):
        calls.append(argv[0])
        return SimpleNamespace(returncode=1, stdout="", stderr="HttpError 500\n")

    with pytest.raises(SourceError, match="exited 1: HttpError 500"):
        run_google(tmp_path, "calendar", "create", run=run)
    assert calls == [chosen]


def test_a_write_whose_first_interpreter_cannot_start_creates_the_event_once(tmp_path, chosen):
    run = runner({sys.executable}, payload='{"id": "e1", "htmlLink": "https://cal/e1"}')
    start = datetime(2026, 11, 9, 10, 0)
    assert writer.create(tmp_path, "Europe/Paris", "primary", "Report", start, start + timedelta(hours=1), "d",
                         run=run) == ("e1", "https://cal/e1")
    assert [call[0] for call in run.calls] == [chosen, sys.executable]
