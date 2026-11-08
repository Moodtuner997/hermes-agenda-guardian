import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from agenda_guardian import commands, discover, profile as prof, sources
from agenda_guardian.core import parse_day, parse_minutes, UserError

NOW = datetime(2026, 11, 9, 8, 0)


def fake_google(events=None, code=0):
    def run(argv, **_):
        return SimpleNamespace(returncode=code, stdout=json.dumps(events or []), stderr="boom" if code else "")
    return run


def install_google(home, signed_in=True):
    script = home / sources.GOOGLE_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text("# stub", encoding="utf-8")
    if signed_in:
        (home / discover.GOOGLE_TOKEN).write_text("{}", encoding="utf-8")


def test_language_follows_the_environment_until_the_user_chooses(make_guardian, monkeypatch):
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    g = make_guardian()
    assert g.lang() == "fr" and commands.run(g, "setup").startswith("Réglage de l'agenda guardian")
    commands.run(g, "set language=en")
    assert g.lang() == "en" and commands.run(g, "setup").startswith("Agenda guardian setup")


def test_hermes_config_language_and_timezone_are_read(make_guardian, tmp_path):
    (tmp_path / "config.yaml").write_text("model: x\ntimezone: Europe/Paris\nlanguage: fr  # comment\n", encoding="utf-8")
    g = make_guardian()
    profile = g.profile()
    assert profile["language"] == "fr" and profile["timezone"] == "Europe/Paris"
    assert "language" not in profile["_set"]


def test_french_session_end_to_end_speaks_french(make_guardian):
    g = make_guardian()
    commands.run(g, "set language=fr")
    assert commands.run(g, "set work_hours=25:00-26:00").startswith("refusé  work_hours : « 25:00 » n'est pas une heure")
    assert commands.run(g, 'add "Rédiger le devis" 45m p=1 due=demain').startswith("Ajouté n°1 : Rédiger le devis")
    plan = commands.run(g, "plan")
    assert "Plan du lun. 2026-11-09" in plan and "ton estimation" in plan and "heures de travail" in plan
    assert "pour le 2026-11-10" in plan and "Règles appliquées" in plan
    assert commands.run(g, "done 9 20").startswith("! aucune tâche ouverte n°9")
    assert "Terminé n°1" in commands.run(g, "done 1 1h")
    assert commands.run(g, "help").startswith("Dis-moi simplement") and "/day set " not in commands.run(g, "help")
    assert "les réglages" in commands.run(g, "help all")


def test_french_words_are_accepted_for_days_and_durations():
    today = NOW.date()
    assert parse_day("demain", today).day == 10 and parse_day("ven", today).day == 13 and parse_day("aujourd'hui", today) == today
    assert parse_minutes("1h30") == 90 and parse_minutes("2 heures") == 120
    with pytest.raises(UserError, match="n'est pas une durée"):
        parse_minutes("bientôt", "fr")


def test_discovery_lists_other_reminders_but_not_ours(tmp_path):
    (tmp_path / "cron").mkdir()
    jobs = [{"name": "news", "schedule": "0 7 * * *", "prompt": "SECRET PROMPT"},
            {"name": "agenda-guardian-brief", "schedule": "0 8 * * 1-5"},
            {"name": "old", "schedule": "0 9 * * *", "enabled": False},
            {"name": "weekly", "schedule": {"display": "every monday"}}]
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
    assert discover.other_jobs(tmp_path) == [("news", "0 7 * * *"), ("weekly", "every monday")]
    assert discover.google_state(tmp_path) == "absent"
    install_google(tmp_path, signed_in=False)
    assert discover.google_state(tmp_path) == "skill_only"
    (tmp_path / discover.GOOGLE_TOKEN).write_text("{}", encoding="utf-8")
    assert discover.google_state(tmp_path) == "ready"


def test_setup_shows_what_the_profile_already_has(make_guardian, tmp_path):
    install_google(tmp_path)
    (tmp_path / "config.yaml").write_text("timezone: Europe/Paris\n", encoding="utf-8")
    (tmp_path / "cron").mkdir()
    (tmp_path / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"name": "news", "schedule": "0 7 * * *"}]}), encoding="utf-8")
    events = [{"summary": "Call", "start": "2026-11-09T10:00:00", "end": "2026-11-09T10:30:00"}]
    g = make_guardian(run=fake_google(events))
    text = commands.run(g, "setup")
    assert "Time zone: Europe/Paris" in text and "Google Calendar: the google-workspace skill is connected, 1 event(s) today" in text
    assert "news (0 7 * * *)" in text and "/day setup auto" in text and "SECRET" not in text


def test_setup_auto_adopts_a_working_google_calendar_and_says_so(make_guardian, tmp_path):
    install_google(tmp_path)
    g = make_guardian(run=fake_google([]))
    out = commands.run(g, "setup auto")
    assert "ok  calendar = google" in out and g.profile()["calendar"] == {"type": "google"}
    assert g.profile()["_set"]["calendar"] == "auto:2026-11-09"
    assert "now google\n" in commands.run(g, "setup")
    assert prof.source_of(g.profile(), "calendar") == "detected in your Hermes profile on 2026-11-09"
    assert commands.run(g, "setup auto").startswith("Nothing more to adopt")


def test_setup_auto_refuses_a_calendar_that_cannot_be_read(make_guardian, tmp_path):
    install_google(tmp_path)
    g = make_guardian(run=fake_google(code=1))
    out = commands.run(g, "setup auto")
    assert "Calendar not adopted" in out and g.profile()["calendar"] == {"type": "none"}


def test_skill_without_sign_in_is_reported_not_guessed(make_guardian, tmp_path):
    install_google(tmp_path, signed_in=False)
    text = commands.run(make_guardian(), "setup")
    assert "not signed in yet" in text and "/day setup auto" not in text


def test_setup_tool_gives_the_agent_the_facts(tmp_path, monkeypatch):
    import agenda_guardian as ag
    from test_commands import Ctx

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    install_google(tmp_path)
    ctx = Ctx()
    ag.register(ctx)
    answer = json.loads(ctx.tools["day_setup"]({}))
    assert answer["found"]["google_calendar"] == "ready" and "calendar" not in answer["found"]["can_adopt"]
    assert "propose each answer" in answer["for_agent"]


def test_a_default_lunch_name_follows_the_language_and_is_not_frozen(make_guardian, monkeypatch):
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    g = make_guardian()
    commands.run(g, "set buffer_min=5")  # saves the profile while the language is French
    assert g.profile()["protected"][0]["name"] == "déjeuner"
    commands.run(g, "set language=en")
    assert g.profile()["protected"][0]["name"] == "lunch"
