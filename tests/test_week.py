"""0.4: a whole week in one request, blocks the agent composed, habits that stopped, and plain words after /day.
All on invented data; the stand-in Google script records every call."""

import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import agenda_guardian
from agenda_guardian import commands, writer
from agenda_guardian.core import UserError
from fakegoogle import FakeGoogle, install_script

NOW = datetime(2026, 11, 9, 8, 0)  # a Monday
FIRST_HISTORY_MONDAY = date(2026, 9, 14)  # eight full weeks before the week of NOW

CALLS = {"name": "appels clients", "minutes": 150, "sessions": 2, "window": "09:00-12:30"}
COURSE = {"name": "take off", "minutes": 120, "per_day": 2, "window": "13:00-19:30", "days": "mar,mer"}


@pytest.fixture
def world(make_guardian, tmp_path):
    install_script(tmp_path)
    cal = FakeGoogle()
    cal.weekly("Réunions", 1, "08:00", "18:00", FIRST_HISTORY_MONDAY, 8)  # every Monday, all day
    cal.weekly("Réunions", 4, "09:00", "17:30", FIRST_HISTORY_MONDAY, 8)  # every Thursday
    g = make_guardian(NOW, run=cal)
    g.set_rules([("calendar", "google"), ("language", "fr")])
    return g, cal


def created(cal):
    return [c for c in cal.calls if c[3] == "create"]


def test_several_activities_are_placed_in_one_request_around_each_other(world):
    g, cal = world
    cal.add("Dentiste", datetime(2026, 11, 10, 15, 0), datetime(2026, 11, 10, 16, 0))
    result = g.week_plan([CALLS, COURSE])
    by_kind = {}
    for s in result["sessions"]:
        by_kind.setdefault(s["kind"], []).append(s)
    # calls: Monday and Thursday are usually taken (8 weeks out of 8), so Tuesday and Friday, two days apart
    assert [s["day"] for s in by_kind["appels clients"]] == ["2026-11-10", "2026-11-13"]
    assert by_kind["appels clients"][0]["start"].endswith("09:00:00") and by_kind["appels clients"][0]["end"].endswith("11:30:00")
    # the course: lunch (12:30-13:30) is protected; Wednesday holds two blocks one after the other, Tuesday only one around the dentist
    starts = {s["day"]: [x["start"][11:16] for x in by_kind["take off"] if x["day"] == s["day"]]
              for s in by_kind["take off"]}
    assert starts == {"2026-11-10": ["16:10"], "2026-11-11": ["13:30", "15:40"]}
    summary = {a["activity"]: a for a in result["activities"]}
    assert summary["take off"]["wanted"] == 4 and summary["take off"]["placed"] == 3 and summary["take off"]["missing"] == 1
    assert "Dentiste" not in json.dumps(result["sessions"])  # the event is a reason to avoid, not a session
    text = result["text"]
    assert "mardi 10/11" in text and "Take off" in text and "Appels clients" in text and "seulement 1 séance(s) sur 2" in text
    assert any("pas dans ton agenda" in q for q in result["questions"])
    assert not created(cal) and result["calendar_write"] is False  # a plan writes nothing


def test_a_week_plan_is_written_and_taken_back_like_any_proposal(world):
    g, cal = world
    before = cal.ids()
    plan = g.week_plan([CALLS, COURSE])
    with pytest.raises(UserError, match="write on"):
        g.confirm(plan["proposal_id"])
    assert not created(cal)
    g.set_write(True)
    done = g.confirm(plan["proposal_id"])
    made = [e for e in cal.events if e["id"].startswith("made-")]
    assert done["ok"] and len(made) == len(plan["sessions"]) == 6
    assert all(writer.MARK in e["description"] for e in made)
    assert {e["summary"] for e in made} == {"Appels clients", "Take off"}
    g.undo("all")
    assert cal.ids() == before  # the calendar is exactly what it was, nothing of the user's was touched


def test_a_saved_sheet_fills_the_numbers_the_request_leaves_out(world):
    g, cal = world
    g.kind_set("sport", 120, 15, 30, "18:00-22:00", "mar,mer")
    result = g.week_plan([{"name": "sport", "sessions": 1}])
    session = result["sessions"][0]
    assert session["block_start"].endswith("18:00:00") and session["start"].endswith("18:15:00")
    assert session["end"].endswith("20:15:00") and session["block_end"].endswith("20:45:00")


def test_the_plugin_never_invents_a_length_but_a_missing_window_is_assumed_and_said(world):
    g, cal = world
    with pytest.raises(UserError, match="Pas de durée"):  # the agent picks one and says so; the plugin does not
        g.week_plan([{"name": "yoga", "window": "18:00-20:00"}])
    with pytest.raises(UserError, match="Donne entre 1 et 6"):
        g.week_plan([])
    with pytest.raises(UserError, match="per_day"):
        g.week_plan([{"name": "yoga", "minutes": 60, "window": "18:00-20:00", "per_day": 9}])
    assert not cal.calls  # every request is checked before the calendar is read
    plan = g.week_plan([{"name": "yoga", "minutes": 60, "remember": True}])
    assert plan["sessions"] and any("pas de plage horaire" in w and "09:00-18:00" in w for w in plan["warnings"])
    assert "pas de plage horaire" in plan["text"]
    assert g.kinds_view()["kinds"] == []  # a window nobody gave is not kept as if they had


def test_more_sessions_than_days_means_so_many_a_day(world):
    g, _ = world
    plan = g.week_plan([{"name": "yoga", "minutes": 60, "window": "18:00-22:00", "days": "mar,mer", "sessions": 6}])
    assert plan["activities"][0]["mode"] == "daily" and plan["activities"][0]["per_day"] == 3
    assert [s["day"] for s in plan["sessions"]].count("2026-11-10") == 3 and len(plan["sessions"]) == 6
    with pytest.raises(UserError, match="sessions"):
        g.week_plan([{"name": "yoga", "minutes": 60, "window": "18:00-22:00", "days": "mar,mer", "sessions": 12}])


def test_remember_keeps_the_numbers_as_a_sheet(world):
    g, _ = world
    g.week_plan([{**CALLS, "remember": True}])
    assert [k["name"] for k in g.kinds_view()["kinds"]] == ["appels clients"]
    g.week_plan([COURSE])
    assert [k["name"] for k in g.kinds_view()["kinds"]] == ["appels clients"]  # not asked for: not saved


def test_a_habit_that_stopped_is_kept_and_said(world):
    g, cal = world
    cal.weekly("Bloc du vendredi", 5, "18:30", "21:00", FIRST_HISTORY_MONDAY, 8, skip=(5, 6, 7))  # over for 3 weeks
    cal.weekly("Dîner Léa", 2, "19:30", "22:00", FIRST_HISTORY_MONDAY, 8, skip=(1, 4, 6))  # still happening
    g.kind_set("yoga", 60, 0, 0, "18:00-22:00", "mar,ven")
    result = g.propose("yoga", 1)
    days = {s["day"]: s for s in result["sessions"]}
    assert list(days) == ["2026-11-13"]  # Friday: the old block no longer counts
    reasons = " ".join(days["2026-11-13"]["reasons"])
    assert "plus depuis 3 semaines" in reasons and "Bloc du vendredi" in reasons and "finie" in reasons
    # Tuesday: the dinner is still a habit, so it comes last; free this week, it is said, not hidden
    assert "Dîner Léa" in " ".join(r["reason"] for r in result["rejected"])


def test_history_orders_the_days_it_never_rules_out_a_free_one(world):
    g, _ = world  # Monday and Thursday were taken 8 weeks out of 8, this week's calendar leaves them free
    g.kind_set("sport", 120, 0, 0, "13:00-18:00", "")
    plan = g.propose("sport", 6)  # five other days exist: the sixth session needs one of the usually-taken ones
    chosen = [s["day"] for s in plan["sessions"]]
    assert len(chosen) == 6 and "2026-11-09" in chosen
    usual = next(s for s in plan["sessions"] if s["day"] == "2026-11-09")
    assert "libre cette semaine" in " ".join(usual["reasons"])
    assert "dernier choix" in " ".join(usual["reasons"]) and "n'y figure pas" in " ".join(usual["notes"])
    fewer = g.propose("sport", 2)  # two are enough: the usually-taken days are kept in reserve, and said
    assert not {"2026-11-09", "2026-11-12"} & {s["day"] for s in fewer["sessions"]}
    assert {"lundi", "jeudi"} <= {r["weekday"] for r in fewer["rejected"]}
    assert "Il est libre cette semaine" in " ".join(r["reason"] for r in fewer["rejected"])


def test_blocks_the_agent_composed_go_through_the_same_door(world):
    g, cal = world
    before = cal.ids()
    staged = g.stage([
        {"title": "Club canin", "day": "2026-11-14", "start": "13:30", "end": "15:30", "why": "tous les samedis"},
        {"title": "Natif Records", "day": "tue", "start": "19:00", "end": "22:00"},
    ])
    assert [s["kind"] for s in staged["sessions"]] == ["Natif Records", "Club canin"]
    assert "tous les samedis" in staged["text"] and "Comme tu l'as décrit" in staged["text"]
    assert not created(cal)
    with pytest.raises(UserError, match="write on"):
        g.confirm(staged["proposal_id"])
    g.set_write(True)
    assert g.confirm(staged["proposal_id"])["ok"]
    made = [e for e in cal.events if e["id"].startswith("made-")]
    assert {e["summary"] for e in made} == {"Club canin", "Natif Records"}
    assert all(writer.MARK in e["description"] for e in made)
    assert g.kind_questions(datetime(2026, 11, 14, 16, 0)) == []  # a fixed block: no "how long did it take"
    g.undo("all")
    assert cal.ids() == before


def test_staged_blocks_that_clash_or_overlap_are_refused_with_the_reason(world):
    g, cal = world
    cal.add("Dentiste", datetime(2026, 11, 10, 19, 30), datetime(2026, 11, 10, 20, 0))
    with pytest.raises(UserError, match="Dentiste"):
        g.stage([{"title": "Natif Records", "day": "2026-11-10", "start": "19:00", "end": "22:00"}])
    with pytest.raises(UserError, match="se chevauchent"):
        g.stage([{"title": "A", "day": "2026-11-12", "start": "10:00", "end": "11:00"},
                 {"title": "B", "day": "2026-11-12", "start": "10:30", "end": "12:00"}])
    with pytest.raises(UserError, match="entre aujourd'hui"):
        g.stage([{"title": "Plus tard", "day": "2027-03-01", "start": "10:00", "end": "11:00"}])
    with pytest.raises(UserError, match="titre"):
        g.stage([{"title": "", "day": "2026-11-12", "start": "10:00", "end": "11:00"}])
    assert not created(cal)


def test_a_sentence_after_day_is_a_request_not_a_command(make_guardian):
    g = make_guardian(NOW)
    assert commands.free_text("essayons d'organiser ma semaine") == "essayons d'organiser ma semaine"
    assert commands.free_text("plan tomorrow") == "" and commands.free_text("write on") == ""
    assert commands.free_text("") == "" and commands.free_text("--help me") == ""
    # what used to be a syntax to learn is a request now, even one word or a fragment of the old syntax
    for loose in ("organise", "real=90", "set work_hours=09:00-19:00", "kind sport real=2h", "took sport 90", "setup"):
        assert commands.free_text(loose) == loose
    hint = commands.run(g, "essayons")  # the command line (no gateway hook) still answers in one line
    assert "without /day" in hint and "/day setup" not in hint
    short, full = commands.run(g, ""), commands.run(g, "help all")
    assert commands.run(g, "help") == short
    assert "your own words" in short and "/day kind" not in short and "=" not in short and "/day kind" in full
    assert len(short.splitlines()) <= 6 and len(short) < 600
    for name in commands.KNOWN - {"help"}:  # every command the dispatcher knows is in the list
        assert "I do not know" not in commands.run(make_guardian(NOW), name)
    assert commands.DIRECT <= commands.KNOWN and "set" not in commands.DIRECT


def test_the_gateway_hook_hands_a_sentence_to_the_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    hooks = {}
    ctx = SimpleNamespace(register_command=lambda *a, **k: None, register_cli_command=lambda *a, **k: None,
                          register_tool=lambda **k: None, register_hook=lambda name, fn, **k: hooks.update({name: fn}))
    agenda_guardian.register(ctx)
    hook = hooks["pre_gateway_dispatch"]
    said = hook(event=SimpleNamespace(text="/day essayons de placer 3 séances de sport"), gateway=None)
    assert said == {"action": "rewrite", "text": "Use the agenda-guardian tools (day_*) for this request: "
                                                 "essayons de placer 3 séances de sport"}
    assert hook(event=SimpleNamespace(text="/day@guardian_bot place du sport"))["action"] == "rewrite"
    for text in ("/day plan tomorrow", "/day", "/day write on", "/day undo", "/day help", "hello /day there",
                 "place du sport", ""):
        assert hook(event=SimpleNamespace(text=text)) is None  # the format-free commands stay with the plugin
    for text in ("/day oops", "/day real=90", "/day set work_hours=09:00-19:00", "/day setup", "/day took sport 90"):
        assert hook(event=SimpleNamespace(text=text))["action"] == "rewrite"  # the rest is a request in words
    assert hook(event=None) is None and hook() is None  # never raises into the gateway


def test_the_rules_only_name_tools_that_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    tools = {}
    ctx = SimpleNamespace(register_command=lambda *a, **k: None, register_cli_command=lambda *a, **k: None,
                          register_tool=lambda **k: tools.update({k["name"]: 1}))
    agenda_guardian.register(ctx)
    import re

    for lang, text in agenda_guardian.RULES.items():
        named = set(re.findall(r"\bday_[a-z_]+", text))
        assert named and named <= set(tools), (lang, named - set(tools))
        assert "day_week_plan" in named and "day_stage" in named


def test_a_real_week_request_is_placed_in_one_call_whatever_the_history_says(make_guardian, tmp_path):
    """Théo's request of 6 Nov: his history called Monday to Wednesday afternoons 'usually taken' while the week itself
    held three appointments. 0.3 left most days out and the agent wrote the plan by hand; now everything is placed."""
    install_script(tmp_path)
    cal = FakeGoogle()
    cal.weekly("Cadre souple", 1, "13:00", "19:00", FIRST_HISTORY_MONDAY, 8)  # every Monday afternoon
    cal.weekly("Appel assurance", 2, "09:00", "12:30", FIRST_HISTORY_MONDAY, 8, skip=(3,))  # Tuesday morning, 7 of 8
    cal.weekly("Visio club", 2, "13:00", "18:00", FIRST_HISTORY_MONDAY, 8, skip=(1, 4, 6))  # Tuesday afternoon, 5 of 8
    cal.weekly("Rendez-vous", 3, "13:00", "19:00", FIRST_HISTORY_MONDAY, 8, skip=(1, 4, 6))  # Wednesday afternoon
    cal.add("Djamila", datetime(2026, 11, 9, 10, 0), datetime(2026, 11, 9, 10, 30))
    cal.add("Anton", datetime(2026, 11, 11, 14, 0), datetime(2026, 11, 11, 14, 30))
    cal.add("Café", datetime(2026, 11, 12, 9, 0), datetime(2026, 11, 12, 11, 0))
    g = make_guardian(NOW, run=cal)
    g.set_rules([("calendar", "google"), ("language", "fr")])
    plan = g.week_plan([
        {"name": "sport", "minutes": 120, "sessions": 3, "before_minutes": 15, "after_minutes": 30,
         "window": "18:00-22:00"},
        {"name": "appels clients", "minutes": 150, "sessions": 2, "window": "09:00-12:30"},
        {"name": "take off", "minutes": 120, "per_day": 2, "window": "13:00-19:00"}])
    placed = {a["activity"]: (a["placed"], a["wanted"]) for a in plan["activities"]}
    assert placed == {"sport": (3, 3), "appels clients": (2, 2), "take off": (14, 14)}
    assert not created(cal) and plan["calendar_write"] is False
    assert not any("plage" in q for q in plan["questions"])  # nothing asked about a time window
    # the sheet-based road (day_propose with a saved Tuesday-afternoon sport): 0.3 and 0.4 answered "no slot fits"
    g.kind_set("sport-aprem", 120, 15, 30, "13:00-18:00", "mar")
    alone = g.propose("sport-aprem", 1, date(2026, 11, 10), date(2026, 11, 10))
    assert len(alone["sessions"]) == 1 and alone["sessions"][0]["start"].endswith("13:45:00")  # lunch is protected until 13:30
    assert "libre cette semaine" in " ".join(alone["sessions"][0]["reasons"])
