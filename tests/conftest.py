import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The plugin directory is a package (hyphenated repo name): load it under a fixed name.
spec = importlib.util.spec_from_file_location(
    "agenda_guardian", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
module = importlib.util.module_from_spec(spec)
sys.modules["agenda_guardian"] = module
spec.loader.exec_module(module)

from agenda_guardian import profile as prof  # noqa: E402
from agenda_guardian.core import Guardian  # noqa: E402
from agenda_guardian.model import Event, Task  # noqa: E402

MONDAY = date(2026, 11, 9)
SATURDAY = date(2026, 11, 7)


def at(hhmm: str, day: date = MONDAY) -> datetime:
    hours, minutes = hhmm.split(":")
    return datetime(day.year, day.month, day.day, int(hours), int(minutes))


def event(start: str, end: str, title: str = "Meeting", all_day: bool = False, day: date = MONDAY) -> Event:
    return Event(title, at(start, day), at(end, day), all_day)


def task(id: int, name: str = "Task", minutes: int = 30, priority: int = 2, category: str = "general",
         due: date | None = None) -> Task:
    return Task(id, name, category, minutes, priority, due)


@pytest.fixture(autouse=True)
def no_ambient_language(monkeypatch):
    """The language and time zone of the machine running the tests must not change what they expect."""
    import locale

    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(locale, "getlocale", lambda *a, **k: (None, None))
    monkeypatch.setattr(sys.modules["agenda_guardian.discover"], "_windows_ui_language", lambda: "")


@pytest.fixture(autouse=True)
def no_ambient_cron(monkeypatch):
    """A test run from inside a cron job must not look like a cron session to the scheduling guard."""
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)


@pytest.fixture
def profile():
    return prof.new_profile()


@pytest.fixture
def make_guardian(tmp_path):
    def build(now: datetime = datetime(2026, 11, 9, 8, 0), **kwargs):
        return Guardian(tmp_path / "guardian.db", tmp_path, now=lambda: now, **kwargs)

    return build
