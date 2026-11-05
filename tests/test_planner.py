from datetime import datetime, timedelta

from agenda_guardian.planner import chunk_sizes, plan_day

from conftest import MONDAY, SATURDAY, at, event, task


def spans(plan):
    return [(b.start.strftime("%H:%M"), b.end.strftime("%H:%M")) for b in plan.blocks]


def test_priority_one_goes_to_the_focus_window(profile):
    plan = plan_day(MONDAY, [], [task(1, minutes=45, priority=1)], profile, {})
    assert spans(plan) == [("09:00", "09:45")]
    assert plan.blocks[0].focus is True


def test_meeting_pushes_the_task_past_its_buffer(profile):
    # 09:30-10:30 plus 10 min each side blocks 09:20-10:40; the first focus slot of 45 min starts at 10:40
    plan = plan_day(MONDAY, [event("09:30", "10:30")], [task(1, minutes=45, priority=1)], profile, {})
    assert spans(plan) == [("10:40", "11:25")]


def test_low_priority_keeps_out_of_the_focus_window(profile):
    plan = plan_day(MONDAY, [], [task(1, minutes=30, priority=3)], profile, {})
    assert spans(plan) == [("11:30", "12:00")]
    assert plan.blocks[0].focus is False


def test_long_task_is_split_into_blocks_with_breaks(profile):
    plan = plan_day(MONDAY, [], [task(1, minutes=120, priority=1)], profile, {})
    assert spans(plan) == [("09:00", "09:40"), ("09:50", "10:30"), ("10:40", "11:20")]
    assert [b.part for b in plan.blocks] == [1, 2, 3] and plan.blocks[0].parts == 3


def test_chunk_sizes_add_up_and_respect_the_limit():
    for planned in (5, 25, 50, 55, 120, 245):
        sizes = chunk_sizes(planned, 50)
        assert sum(sizes) == planned and max(sizes) <= 50


def test_nothing_is_ever_placed_in_protected_time(profile):
    tasks = [task(i, minutes=90, priority=2) for i in (1, 2, 3)]
    plan = plan_day(MONDAY, [], tasks, profile, {})
    lunch = (at("12:30"), at("13:30"))
    assert plan.blocks and all(b.end <= lunch[0] or b.start >= lunch[1] for b in plan.blocks)


def test_a_full_day_names_what_does_not_fit(profile):
    plan = plan_day(MONDAY, [], [task(1, "Huge", minutes=600, priority=1)], profile, {})
    assert plan.blocks == []
    assert plan.dropped[0].code == "no_room" and "short by" in plan.dropped[0].detail
    assert any("day is full" in w for w in plan.warnings)


def test_a_task_that_does_not_fit_leaves_no_partial_block(profile):
    plan = plan_day(MONDAY, [], [task(1, "Huge", minutes=600, priority=1), task(2, "Small", minutes=30)], profile, {})
    assert {b.task_id for b in plan.blocks} == {2}


def test_daily_cap_keeps_the_most_urgent_tasks(profile):
    tasks = [task(1, due=MONDAY + timedelta(days=5)), task(2, due=MONDAY + timedelta(days=1)),
             task(3, priority=1), task(4, priority=3), task(5, due=MONDAY)]
    plan = plan_day(MONDAY, [], tasks, profile, {})
    assert {b.task_id for b in plan.blocks} == {5, 2, 1}
    assert {d.task.id for d in plan.dropped} == {3, 4} and all(d.code == "daily_cap" for d in plan.dropped)


def test_calibration_scales_the_estimate_and_says_so(profile):
    plan = plan_day(MONDAY, [], [task(1, minutes=40, category="admin", priority=1)], profile, {"admin": (1.5, 4)})
    assert plan.planned_min == 60
    assert "40 x 1.5" in plan.blocks[0].why[0] and "4 finished 'admin'" in plan.blocks[0].why[0]


def test_below_three_measurements_the_estimate_is_kept(profile):
    plan = plan_day(MONDAY, [], [task(1, minutes=40, category="admin")], profile, {"admin": (1.0, 2)})
    assert plan.planned_min == 40 and "calibration starts at 3" in plan.blocks[0].why[0]


def test_weekend_plans_nothing(profile):
    plan = plan_day(SATURDAY, [], [task(1)], profile, {})
    assert plan.window is None and plan.blocks == [] and plan.dropped[0].code == "non_workday"


def test_planning_from_now_does_not_use_the_past(profile):
    now = datetime(2026, 11, 9, 10, 7)
    plan = plan_day(MONDAY, [], [task(1, minutes=30, priority=1)], profile, {}, now=now)
    assert spans(plan) == [("10:10", "10:40")]


def test_all_day_events_do_not_block_time(profile):
    plan = plan_day(MONDAY, [event("00:00", "23:59", "Birthday", all_day=True)], [task(1, priority=1)], profile, {})
    assert spans(plan)[0][0] == "09:00"


def test_every_block_cites_its_rules_and_where_they_came_from(profile):
    profile["_set"]["work_hours"] = "2026-11-05"
    plan = plan_day(MONDAY, [], [task(1, priority=1, due=MONDAY)], profile, {})
    why = " | ".join(plan.blocks[0].why)
    assert "due 2026-11-09" in why and "in your focus window" in why
    rules = " | ".join(plan.rules)
    assert "work hours 09:00-18:00 (you set it on 2026-11-05)" in rules
    assert "focus window 09:00-11:30 for priority 1 (default, not set by you yet)" in rules
