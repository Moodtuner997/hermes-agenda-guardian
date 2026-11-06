"""The proactive side on invented data: reasons from the calendar's history, the yes before any write,
and the rule that only events this plugin created can ever be removed."""

from datetime import date, datetime, timedelta

import pytest

from agenda_guardian import kinds as kindmod
from agenda_guardian import writer
from agenda_guardian.core import UserError
from agenda_guardian.model import UserError as ModelUserError
from fakegoogle import FakeGoogle, install_script

NOW = datetime(2026, 11, 9, 8, 0)  # a Monday
FIRST_HISTORY_MONDAY = date(2026, 9, 14)  # eight full weeks before the week of NOW


@pytest.fixture
def world(make_guardian, tmp_path):
    """A Google calendar with eight weeks of habits (dinner on Tuesdays, family meals on Wednesdays, heavy
    Mondays and Thursdays) and a guardian that knows a sport sheet."""
    install_script(tmp_path)
    cal = FakeGoogle()
    cal.weekly("Réunions", 1, "08:00", "18:00", FIRST_HISTORY_MONDAY, 8)
    cal.weekly("Réunions", 4, "09:00", "17:30", FIRST_HISTORY_MONDAY, 8)
    cal.weekly("Dîner Léa", 2, "19:30", "22:00", FIRST_HISTORY_MONDAY, 8, skip=(1, 4, 6))  # 5 of 8
    cal.weekly("Repas de famille", 3, "19:00", "21:30", FIRST_HISTORY_MONDAY, 8, skip=(0, 3))  # 6 of 8
    g = make_guardian(NOW, run=cal)
    g.set_rules([("calendar", "google"), ("language", "fr")])
    g.kind_set("sport", 120, 15, 30, "18:00-22:00", "lun,mar,mer,jeu")
    return g, cal


def test_a_sheet_that_does_not_fit_its_window_is_refused(make_guardian):
    g = make_guardian(NOW)
    with pytest.raises(UserError, match="165"):
        g.kind_set("sport", 120, 15, 30, "18:00-20:00")
    assert g.kinds_view()["kinds"] == []
    assert kindmod.build("sport", 120, 15, 30, "18:00-21:00", "mon").total() == 165


def test_proposal_picks_free_evenings_and_says_why(world):
    g, cal = world
    g.habit_add("mer", "18:00-21:00", "repas de famille")
    result = g.propose("sport", 2)
    days = [s["day"] for s in result["sessions"]]
    assert days == ["2026-11-09", "2026-11-12"]  # Monday and Thursday, three days apart
    monday = result["sessions"][0]
    assert monday["block_start"].endswith("18:00:00") and monday["start"].endswith("18:15:00")
    assert monday["end"].endswith("20:15:00") and monday["block_end"].endswith("20:45:00")
    reasons = " ".join(monday["reasons"])
    assert "libre lundi de 18:00 à 22:00" in reasons and "8 semaines sur 8" in reasons
    assert "chargée" in reasons and "120 min" in reasons and "15 min avant" in reasons
    rejected = " ".join(r["reason"] for r in result["rejected"])
    assert "mardi : d'habitude pris, 5 des 8" in rejected and "Dîner Léa" in rejected  # history, not this week
    assert "mercredi : tu m'as dit « repas de famille »" in rejected  # a habit that is not in the calendar
    assert any("pas dans ton agenda" in q for q in result["questions"])  # asks about what it cannot see
    assert cal.deleted() == [] and not [c for c in cal.calls if c[3] == "create"]  # a proposal writes nothing


def test_an_event_in_the_calendar_is_a_reason_too(world):
    g, cal = world
    cal.add("Cinéma", datetime(2026, 11, 9, 19, 0), datetime(2026, 11, 9, 22, 0))
    result = g.propose("sport", 1, days="lun,jeu")
    assert result["sessions"][0]["day"] == "2026-11-12"
    assert "Cinéma" in result["rejected"][0]["reason"] and result["rejected"][0]["day"] == "2026-11-09"


def test_no_calendar_means_no_proposal(make_guardian):
    g = make_guardian(NOW)
    g.kind_set("sport", 60, 0, 0, "18:00-21:00")
    with pytest.raises(UserError, match="calendar"):
        g.propose("sport")


def test_a_thin_history_is_said_not_hidden(make_guardian, tmp_path):
    install_script(tmp_path)
    cal = FakeGoogle()
    g = make_guardian(NOW, run=cal)
    g.set_rules([("calendar", "google"), ("language", "en")])
    g.kind_set("run", 45, 0, 10, "18:00-21:00")
    result = g.propose("run", 1)
    assert result["history_thin"] and "too short" in " ".join(result["sessions"][0]["reasons"])


def test_nothing_is_written_until_the_user_turned_writing_on_and_said_yes(world):
    g, cal = world
    proposal = g.propose("sport", 2)
    with pytest.raises(UserError, match="write on"):
        g.confirm(proposal["proposal_id"])
    assert not [c for c in cal.calls if c[3] == "create"]
    g.set_write(True)
    done = g.confirm(proposal["proposal_id"])
    made = [e for e in cal.events if e["id"].startswith("made-")]
    assert done["ok"] and len(made) == 6  # three events (get ready, sport, wind down) for each of two sessions
    assert all(writer.MARK in e["description"] for e in made)
    assert [e["summary"] for e in made[:3]] == ["Sport : préparation", "Sport", "Sport : récupération"]
    assert {row[0] for row in g.conn.execute("SELECT event_id FROM written")} == {e["id"] for e in made}
    with pytest.raises(UserError, match="déjà écrite"):
        g.confirm(proposal["proposal_id"])


def test_writing_needs_a_google_calendar_and_the_switch(make_guardian):
    g = make_guardian(NOW)
    with pytest.raises(UserError, match="Google"):
        g.set_write(True)
    assert g.write_enabled() is False


def test_a_proposal_goes_stale_and_a_new_clash_blocks_the_write(world):
    g, cal = world
    g.set_write(True)
    proposal = g.propose("sport", 2)
    cal.add("Dentiste", datetime(2026, 11, 9, 18, 30), datetime(2026, 11, 9, 19, 30))
    done = g.confirm(proposal["proposal_id"])
    assert [s["day"] for s in done["skipped"]] == ["2026-11-09"] and "Dentiste" in done["skipped"][0]["why"]
    assert len(done["written"]) == 1 and done["written"][0]["day"] == "2026-11-12"
    stale = g.propose("sport", 1)
    g._now = lambda: NOW + timedelta(days=2)
    with pytest.raises(UserError, match="plus d'un jour"):
        g.confirm(stale["proposal_id"])


def test_undo_removes_only_what_the_plugin_wrote(world):
    g, cal = world
    g.set_write(True)
    g.confirm(g.propose("sport", 1)["proposal_id"])
    mine = {e["id"] for e in cal.events if e["id"].startswith("made-")}
    foreign = {e["id"] for e in cal.events} - mine
    outcome = g.undo()
    assert [r["outcome"] for r in outcome["removed"]] == ["deleted"] * 3
    assert set(cal.deleted()) == mine and foreign <= cal.ids()  # every event the user created is still there
    assert g.undo()["removed"] == []


def test_a_foreign_event_id_is_refused_without_calling_the_calendar(world):
    g, cal = world
    cal.add("Rendez-vous médical", datetime(2026, 11, 10, 10, 0), datetime(2026, 11, 10, 11, 0), event_id="mine-not")
    calls = len(cal.calls)
    with pytest.raises(writer.ForeignEvent):
        writer.remove(g.conn, g.home, "", "mine-not", NOW, cal)
    assert len(cal.calls) == calls and "mine-not" in cal.ids()


def test_an_event_the_user_rewrote_is_left_alone(world):
    g, cal = world
    g.set_write(True)
    g.confirm(g.propose("sport", 1)["proposal_id"])
    main = next(e for e in cal.events if e["summary"] == "Sport")
    main["description"] = "Match avec Paul"  # the user took the slot over
    results = {r["event"]: r["outcome"] for r in g.undo()["removed"]}
    assert results["Sport"] == "rewritten" and main["id"] in cal.ids()


def test_an_event_the_user_deleted_is_not_recreated_and_not_an_error(world):
    g, cal = world
    g.set_write(True)
    g.confirm(g.propose("sport", 1)["proposal_id"])
    cal.events = [e for e in cal.events if e["summary"] != "Sport"]
    assert "gone" in [r["outcome"] for r in g.undo()["removed"]]


def test_real_durations_correct_the_next_proposal_and_are_asked_once(world):
    g, cal = world
    g.set_write(True)
    for week in range(3):  # three finished sessions that each took 150 min instead of 120
        base = datetime(2026, 11, 9) + timedelta(weeks=week)
        cal.add("old", base, base)  # keeps the history non-empty
        group = 100 + week
        g.conn.execute("INSERT INTO written(event_id, calendar_id, group_id, kind, part, summary, start, end, link, "
                       "created_at) VALUES(?, 'primary', ?, 'sport', 'main', 'Sport', ?, ?, '', ?)",
                       (f"old-{week}", group, (base + timedelta(hours=18)).isoformat(),
                        (base + timedelta(hours=20)).isoformat(), NOW.isoformat()))
        g.conn.commit()
        g._now = lambda: datetime(2026, 12, 20, 12, 0)
        assert "prévu 120 min, réel 150 min" in g.took(str(group), 150)["text"]
    g._now = lambda: NOW
    result = g.propose("sport", 1)
    session = result["sessions"][0]
    assert result["minutes"]["activity"] == 150  # 120 x 1.25
    assert "x1.25" in " ".join(session["reasons"]) and "tu dis 120" in " ".join(session["reasons"])


def test_the_duration_question_comes_once_after_the_activity_ends(world):
    g, cal = world
    g.set_write(True)
    g.confirm(g.propose("sport", 1)["proposal_id"])
    main = next(r for r in g.conn.execute("SELECT end FROM written WHERE part='main'"))
    end = datetime.fromisoformat(main[0])
    assert g.kind_questions(end - timedelta(minutes=5)) == []
    first = g.kind_questions(end + timedelta(minutes=10))
    assert len(first) == 1 and "Combien de temps" in first[0]
    assert g.kind_questions(end + timedelta(minutes=20)) == []


def test_took_rejects_an_unknown_session(world):
    g, _ = world
    with pytest.raises(UserError, match="Aucune activité terminée"):
        g.took("99", 60)


def test_week_view_separates_calendar_events_proposals_and_written(world):
    g, cal = world
    g.set_write(True)
    cal.add("Réunions", datetime(2026, 11, 9, 9, 0), datetime(2026, 11, 9, 12, 0))
    g.confirm(g.propose("sport", 1)["proposal_id"])
    g.propose("sport", 1, days="jeu")
    view = g.week_view()
    assert view["week_start"] == "2026-11-09" and view["write_enabled"]
    assert len(view["written"]) == 3 and len(view["proposed"]) == 1
    assert not any(e["title"].startswith("Sport") for e in view["events"])  # ours are listed under "written"
    assert any(e["title"] == "Réunions" for e in view["events"])  # the user's own events are listed as theirs


def test_model_and_core_share_one_usererror():
    assert UserError is ModelUserError


def test_the_whole_conversation_through_the_slash_command(make_guardian, tmp_path):
    from agenda_guardian import commands

    install_script(tmp_path)
    cal = FakeGoogle()
    cal.weekly("Réunions", 1, "09:00", "17:00", FIRST_HISTORY_MONDAY, 8)
    g = make_guardian(NOW, run=cal)
    run = lambda text: commands.run(g, text)
    run("set calendar=google language=fr")
    assert "Enregistré" in run("kind sport real=2h before=15 after=30 window=18:00-22:00 days=lun,jeu")
    assert "sport : 120 min, +15 min avant, +30 min après" in run("kind")
    assert "Noté n°1 : mercredi" in run("habit mer 18:00-21:00 repas de famille")
    proposal = run("propose sport 2")
    assert "Proposition n°1" in proposal and "Rien n'est écrit" in proposal and "pourquoi" not in proposal.lower()
    assert "Ton agenda est libre lundi" in proposal and "/day write on" in proposal
    assert "désactivée" in run("ok 1")  # writing was never switched on
    assert "L'écriture est activée" in run("write on")
    written = run("ok 1")
    assert "Écrit n°1" in written and "https://cal/made-" in written
    assert run("undo").count("retiré") == 3  # the last session only (two were written)
    assert run("undo all").count("retiré") == 3
    assert "Rien de ce que j'ai écrit" in run("undo")
    assert not [e for e in cal.events if e["id"].startswith("made-")]


def test_the_reminder_script_also_asks_the_duration_question(world):
    g, _ = world
    g.set_write(True)
    g.confirm(g.propose("sport", 1)["proposal_id"])
    end = datetime.fromisoformat(next(g.conn.execute("SELECT end FROM written WHERE part='main'"))[0])
    g._now = lambda: end + timedelta(minutes=10)
    assert "Combien de temps" in g.nudge_text()
    assert "Combien de temps" not in g.nudge_text()


def test_a_refused_proposal_is_closed_and_cannot_be_written(world):
    g, cal = world
    g.set_write(True)
    proposal = g.propose("sport", 1)
    assert "écartée" in g.refuse(proposal["proposal_id"])["text"]
    with pytest.raises(UserError, match="déjà écartée"):
        g.confirm(proposal["proposal_id"])
    assert not [c for c in cal.calls if c[3] == "create"]
