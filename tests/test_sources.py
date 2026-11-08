import json
import subprocess
from datetime import date

import pytest

from agenda_guardian import profile as prof, sources, store
from agenda_guardian.sources import SourceError, fetch_events, parse_ics

from conftest import MONDAY

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20261109T100000
DTEND:20261109T110000
SUMMARY:Stand\\, up
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261109
DTEND;VALUE=DATE:20261110
SUMMARY:Birthday
END:VEVENT
BEGIN:VEVENT
DTSTART:20261110T100000
DTEND:20261110T110000
SUMMARY:Tomorrow only
END:VEVENT
BEGIN:VEVENT
DTSTART:20261109T150000
DTEND:20261109T160000
SUMMARY:Cancelled one
STATUS:CANCELLED
END:VEVENT
END:VCALENDAR
"""


def titles(events):
    return sorted(e.title for e in events)


def test_ics_keeps_only_the_events_of_the_day():
    events = parse_ics(ICS, MONDAY)
    assert titles(events) == ["Birthday", "Stand, up"]
    standup = next(e for e in events if e.title == "Stand, up")
    assert (standup.start.hour, standup.end.hour, standup.all_day) == (10, 11, False)
    assert next(e for e in events if e.title == "Birthday").all_day is True


def rule_ics(rule, extra="", start="20261005T140000"):
    return (f"BEGIN:VEVENT\nDTSTART:{start}\nDTEND:{start[:9]}150000\nSUMMARY:Weekly\nRRULE:{rule}\n{extra}END:VEVENT\n")


def test_weekly_recurrence_lands_on_the_right_weekdays():
    text = rule_ics("FREQ=WEEKLY;BYDAY=MO,WE")  # 5 Oct 2026 is a Monday
    assert len(parse_ics(text, MONDAY)) == 1                       # Mon 9 Nov
    assert parse_ics(text, date(2026, 11, 10)) == []               # Tue
    assert len(parse_ics(text, date(2026, 11, 11))) == 1           # Wed


def test_recurrence_interval_count_until_and_exdate():
    assert parse_ics(rule_ics("FREQ=WEEKLY;INTERVAL=2"), MONDAY) == []                    # 9 Nov is 5 weeks after 5 Oct
    assert len(parse_ics(rule_ics("FREQ=WEEKLY;INTERVAL=2"), date(2026, 11, 2))) == 1      # 4 weeks after
    assert parse_ics(rule_ics("FREQ=WEEKLY;COUNT=3"), MONDAY) == []                       # 5, 12, 19 Oct only
    assert parse_ics(rule_ics("FREQ=WEEKLY;UNTIL=20261101T000000Z"), MONDAY) == []
    assert parse_ics(rule_ics("FREQ=WEEKLY", "EXDATE:20261109T140000\n"), MONDAY) == []
    assert len(parse_ics(rule_ics("FREQ=DAILY"), MONDAY)) == 1


def test_monthly_recurrence_is_flagged_not_guessed():
    warnings = []
    events = parse_ics(rule_ics("FREQ=MONTHLY"), MONDAY, warnings=warnings)
    assert events == [] and "monthly or yearly" in warnings[0]


def test_json_events_in_the_google_script_shape():
    data = [{"id": "a", "summary": "Dentist", "start": "2026-11-09T14:00:00", "end": "2026-11-09T15:00:00"},
            {"id": "b", "summary": "Holiday", "start": "2026-11-09", "end": "2026-11-10"},
            {"id": "c", "summary": "Gone", "start": "2026-11-09T09:00:00", "end": "2026-11-09T10:00:00",
             "status": "cancelled"},
            {"id": "d", "summary": "Broken", "start": "garbage", "end": "x"}]
    events = sources._json_events(data, "")
    assert titles(events) == ["Dentist", "Holiday"]
    assert next(e for e in events if e.title == "Holiday").all_day


class Done:
    def __init__(self, out="", code=0, err=""):
        self.stdout, self.returncode, self.stderr = out, code, err


def test_command_source_gets_the_day_window_and_runs_without_a_shell(tmp_path):
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, shell=kw.get("shell"))
        return Done(json.dumps([{"summary": "X", "start": "2026-11-09T09:00:00", "end": "2026-11-09T10:00:00"}]))

    profile = prof.new_profile()
    profile["calendar"] = {"type": "command", "argv": ["mycal", "--from", "{start}", "--to", "{end}"]}
    events, _ = fetch_events(profile, MONDAY, tmp_path, run=run)
    assert titles(events) == ["X"] and seen["shell"] is False
    assert seen["argv"][2].endswith("Z") and seen["argv"][4].endswith("Z") and seen["argv"][2] < seen["argv"][4]


@pytest.mark.parametrize("run, message", [
    (lambda argv, **kw: Done("", 3, "auth expired"), "exited 3: auth expired"),
    (lambda argv, **kw: Done("not json"), "did not print JSON"),
    (lambda argv, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)), "timed out"),
    (lambda argv, **kw: (_ for _ in ()).throw(FileNotFoundError()), "not found"),
])
def test_a_broken_command_raises_a_readable_error(run, message, tmp_path):
    profile = prof.new_profile()
    profile["calendar"] = {"type": "command", "argv": ["mycal"]}
    with pytest.raises(SourceError, match=message):
        fetch_events(profile, MONDAY, tmp_path, run=run)


def test_google_source_needs_the_skill_script(tmp_path):
    profile = prof.new_profile()
    profile["calendar"] = {"type": "google"}
    with pytest.raises(SourceError, match="Google Workspace skill not found"):
        fetch_events(profile, MONDAY, tmp_path)


def test_google_source_calls_the_skill_script(tmp_path):
    script = tmp_path / sources.GOOGLE_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return Done("[]")

    profile = prof.new_profile()
    profile["calendar"] = {"type": "google"}
    assert fetch_events(profile, MONDAY, tmp_path, run=run)[0] == []
    assert seen["argv"][2:5] == ["calendar", "list", "--start"] and seen["argv"][-2:] == ["--max", "100"]


def test_no_calendar_is_stated_not_silent(tmp_path):
    events, warnings = fetch_events(prof.new_profile(), MONDAY, tmp_path)
    assert events == [] and "ignores your meetings" in warnings[0]


class IcsResponse:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, size=-1):
        data = ICS.encode()
        return data if size < 0 else data[:size]


class EndlessResponse(IcsResponse):
    """A server that never stops sending: counts what was asked of it, hands out exactly what is asked."""

    def __init__(self):
        self.asked = []

    def read(self, size=-1):
        self.asked.append(size)
        return b"X" * (size if size >= 0 else 10**9)


def test_an_ics_answer_past_the_limit_is_refused_and_never_read_whole(tmp_path):
    response = EndlessResponse()
    profile = prof.new_profile()
    profile["calendar"] = {"type": "ics", "path": "https://example.test/cal.ics"}
    with pytest.raises(SourceError, match="more than 5 MB"):
        fetch_events(profile, MONDAY, tmp_path, urlopen=lambda request, timeout: response)
    assert response.asked == [sources.MAX_ICS_BYTES + 1]


def test_an_ics_answer_of_exactly_the_limit_is_read(tmp_path):
    class Exact(IcsResponse):
        def read(self, size=-1):
            return (ICS + "\r\n" * 10).encode().ljust(sources.MAX_ICS_BYTES, b" ")[:size if size >= 0 else None]

    profile = prof.new_profile()
    profile["calendar"] = {"type": "ics", "path": "https://example.test/cal.ics"}
    events, warnings = fetch_events(profile, MONDAY, tmp_path, urlopen=lambda request, timeout: Exact())
    assert titles(events) == ["Birthday", "Stand, up"] and warnings == []


def test_the_too_big_answer_is_said_in_french_too(tmp_path):
    profile = prof.new_profile()
    profile["language"] = "fr"
    profile["calendar"] = {"type": "ics", "path": "https://example.test/cal.ics"}
    with pytest.raises(SourceError, match="plus de 5 Mo"):
        fetch_events(profile, MONDAY, tmp_path, urlopen=lambda request, timeout: EndlessResponse())


def test_ics_url_is_fetched_over_https(tmp_path):
    seen = []

    def urlopen(request, timeout):
        seen.append(request.full_url)
        return IcsResponse()

    profile = prof.new_profile()
    profile["calendar"] = {"type": "ics", "path": "https://example.test/cal.ics"}
    events, warnings = fetch_events(profile, MONDAY, tmp_path, urlopen=urlopen)
    assert titles(events) == ["Birthday", "Stand, up"] and warnings == [] and seen == ["https://example.test/cal.ics"]


@pytest.mark.parametrize("location", ["http://example.test/cal.ics", "HTTP://example.test/cal.ics"])
def test_ics_over_plain_http_is_an_error_and_nothing_is_requested(tmp_path, location):
    profile = prof.new_profile()
    profile["calendar"] = {"type": "ics", "path": location}
    with pytest.raises(SourceError, match="must start with https://"):
        fetch_events(profile, MONDAY, tmp_path, urlopen=lambda *a, **kw: pytest.fail("a request was made"))


def test_a_local_ics_file_is_still_read_as_is(tmp_path):
    path = tmp_path / "cal.ics"
    path.write_text(ICS, encoding="utf-8")
    profile = prof.new_profile()
    profile["calendar"] = {"type": "ics", "path": str(path)}
    events, _ = fetch_events(profile, MONDAY, tmp_path, urlopen=lambda *a, **kw: pytest.fail("a request was made"))
    assert titles(events) == ["Birthday", "Stand, up"]


def test_calibration_needs_three_measurements_and_is_bounded(tmp_path):
    conn = store.connect(tmp_path / "s.db")

    def sample(category, est, actual):
        conn.execute("INSERT INTO samples(task_id, category, est_min, actual_min, logged_at) VALUES(0,?,?,?,'x')",
                     (category, est, actual))

    sample("a", 30, 60)
    sample("a", 30, 60)
    assert store.factors(conn)["a"] == (1.0, 2)
    sample("a", 30, 45)
    assert store.factors(conn)["a"] == (2.0, 3)                       # median of 2, 2, 1.5
    for _ in range(3):
        sample("b", 10, 100)
        sample("c", 100, 10)
    assert store.factors(conn)["b"][0] == 3.0 and store.factors(conn)["c"][0] == 0.7
