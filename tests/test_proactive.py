import os
import subprocess
import sys
from datetime import datetime

import agenda_guardian
from agenda_guardian import commands

from conftest import ROOT


def add_task(g, text='add "Write the quote" 45m p=1'):
    commands.run(g, text)


def test_reminder_fires_once_before_a_block_and_once_after_it(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 7, 30))
    add_task(g)
    commands.run(g, "brief")                                    # the morning plan: block 09:00-09:45
    assert make_guardian(now=datetime(2026, 11, 9, 8, 40)).nudge_text() == ""      # too early
    first = make_guardian(now=datetime(2026, 11, 9, 8, 56)).nudge_text()
    assert first == "Starting 09:00: Write the quote (45 min)"
    assert make_guardian(now=datetime(2026, 11, 9, 9, 1)).nudge_text() == ""       # already said
    end = make_guardian(now=datetime(2026, 11, 9, 9, 50)).nudge_text()
    assert "Write the quote was planned until 09:45" in end and "/day done 1 <minutes>" in end
    assert make_guardian(now=datetime(2026, 11, 9, 9, 55)).nudge_text() == ""
    # nothing is asked about a task that is already done
    g2 = make_guardian(now=datetime(2026, 11, 9, 7, 30))
    commands.run(g2, "add \"Other\" 30m p=1")
    commands.run(g2, "brief")
    commands.run(g2, "done 2 25")
    assert "Other" not in make_guardian(now=datetime(2026, 11, 9, 10, 40)).nudge_text()


def test_replanning_does_not_make_a_block_announce_twice(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 7, 30))
    add_task(g)
    commands.run(g, "brief")
    late = make_guardian(now=datetime(2026, 11, 9, 8, 56))
    assert late.nudge_text().startswith("Starting 09:00")
    commands.run(late, "plan")                                  # replan from now, same block
    assert late.nudge_text() == ""


def test_the_first_check_of_the_day_builds_its_own_plan(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 8, 58))
    add_task(g)
    assert g.nudge_text().startswith("Starting 09:00: Write the quote")


def test_multi_block_task_asks_for_the_real_time_only_after_its_last_block(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 7, 30))
    commands.run(g, 'add "Report" 120m p=1')
    commands.run(g, "brief")                                    # 09:00-09:40, 09:50-10:30, 10:40-11:20
    assert "real" not in make_guardian(now=datetime(2026, 11, 9, 9, 45)).nudge_text()
    assert "really take" in make_guardian(now=datetime(2026, 11, 9, 11, 25)).nudge_text()


def test_french_reminders(make_guardian):
    g = make_guardian(now=datetime(2026, 11, 9, 8, 58))
    commands.run(g, "set language=fr")
    add_task(g)
    assert g.nudge_text().startswith("Début à 09:00 : Write the quote (45 min)")


class FakeCron:
    def __init__(self, existing=()):
        self.calls, self.jobs = [], list(existing)

    def __call__(self, args):
        self.calls.append(args)
        if args["action"] == "list":
            return {"success": True, "jobs": self.jobs}
        return {"success": True, "job_id": "j1"}


def test_cron_on_creates_two_script_jobs_without_a_model(make_guardian, tmp_path):
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    commands.run(g, "set work_hours=09:00-17:30 workdays=1-5")
    out = commands.run(g, "cron on 07:30 deliver=telegram")
    assert "07:30" in out and "no model call" in out
    creates = [c for c in cron.calls if c["action"] == "create"]
    assert [c["name"] for c in creates] == ["agenda-guardian-brief", "agenda-guardian-nudge"]
    assert all(c["no_agent"] is True and c["deliver"] == "telegram" for c in creates)
    assert creates[0]["schedule"] == "30 7 * * 1,2,3,4,5"
    assert creates[1]["schedule"] == "*/5 8-20 * * 1,2,3,4,5"
    brief_script = (tmp_path / "scripts" / "agenda-guardian-brief.py").read_text(encoding="utf-8")
    assert "scheduled_text('brief'" in brief_script and repr(str(ROOT)) in brief_script
    assert repr(str(tmp_path)) in brief_script          # the data folder and home are baked in, not guessed at run time


def test_cron_on_updates_instead_of_duplicating(make_guardian):
    cron = FakeCron([{"job_id": "a1", "name": "agenda-guardian-brief"}, {"job_id": "b2", "name": "agenda-guardian-nudge"},
                     {"job_id": "c3", "name": "unrelated"}])
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    commands.run(g, "cron on")
    assert [c["action"] for c in cron.calls] == ["list", "update", "update"]
    assert {c["job_id"] for c in cron.calls[1:]} == {"a1", "b2"}


def test_cron_off_removes_only_its_own_jobs(make_guardian):
    cron = FakeCron([{"job_id": "a1", "name": "agenda-guardian-brief"}, {"job_id": "c3", "name": "unrelated"}])
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    assert commands.run(g, "cron off") == "Removed 1 scheduled job(s)."
    assert [c for c in cron.calls if c["action"] == "remove"] == [{"action": "remove", "job_id": "a1"}]
    assert commands.run(make_guardian(cron=FakeCron(), plugin_dir=ROOT), "cron status").startswith("Nothing scheduled")


def test_hermes_refusing_a_job_is_reported(make_guardian):
    def refusing(args):
        return {"success": True, "jobs": []} if args["action"] == "list" else {"success": False, "error": "not allowed"}

    out = commands.run(make_guardian(cron=refusing, plugin_dir=ROOT), "cron on")
    assert out.startswith("! Hermes refused") and "not allowed" in out


def test_cron_off_also_removes_the_scripts_it_wrote(make_guardian, tmp_path):
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    commands.run(g, "cron on")
    assert sorted(p.name for p in (tmp_path / "scripts").iterdir()) == ["agenda-guardian-brief.py", "agenda-guardian-nudge.py"]
    commands.run(g, "cron off")
    assert list((tmp_path / "scripts").iterdir()) == []


def test_the_script_does_not_need_hermes_home_in_its_environment(make_guardian, tmp_path):
    g = make_guardian(cron=FakeCron(), plugin_dir=ROOT)
    commands.run(g, 'add "Write the quote" 45m')
    commands.run(g, "cron on")
    env = {k: v for k, v in os.environ.items() if k != "HERMES_HOME"}
    done = subprocess.run([sys.executable, str(tmp_path / "scripts" / "agenda-guardian-brief.py")],
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    assert "Write the quote" in done.stdout or "Not a workday" in done.stdout   # read this DB, not an empty one


def test_a_failed_job_listing_changes_nothing_and_keeps_the_scripts(make_guardian, tmp_path):
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    commands.run(g, "cron on")
    broken = make_guardian(cron=lambda args: {"success": False, "error": "no scheduler here"}, plugin_dir=ROOT)
    for action in ("off", "status", "on"):
        out = commands.run(broken, f"cron {action}")
        assert out.startswith("! Hermes did not list its cron jobs") and "no scheduler here" in out
    assert len(list((tmp_path / "scripts").iterdir())) == 2


def test_cron_without_a_session_explains_itself(make_guardian):
    assert "needs a running Hermes session" in commands.run(make_guardian(), "cron on")


def test_the_generated_script_runs_and_prints_the_brief(make_guardian, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cron = FakeCron()
    g = make_guardian(cron=cron, plugin_dir=ROOT)
    commands.run(g, 'add "Write the quote" 45m')
    commands.run(g, "cron on")
    # The script uses the real clock and the data folder under HERMES_HOME, like the scheduler would.
    data = tmp_path / "plugin-data" / "agenda-guardian"
    data.mkdir(parents=True)
    (tmp_path / "plugin-data" / "agenda-guardian" / "guardian.db").write_bytes(g.db_path.read_bytes())
    done = subprocess.run([sys.executable, str(tmp_path / "scripts" / "agenda-guardian-brief.py")],
                          capture_output=True, text=True, env={**os.environ, "HERMES_HOME": str(tmp_path)})
    assert done.returncode == 0, done.stderr
    assert "Plan for" in done.stdout
    nudge = subprocess.run([sys.executable, str(tmp_path / "scripts" / "agenda-guardian-nudge.py")],
                           capture_output=True, text=True, env={**os.environ, "HERMES_HOME": str(tmp_path)})
    assert nudge.returncode == 0, nudge.stderr


def test_scheduled_text_entry_point(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert agenda_guardian.scheduled_text("nudge") == ""
    assert agenda_guardian.scheduled_text("brief").startswith("Plan for")
