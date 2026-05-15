from datetime import timedelta

from src.calibration import update_multiplier
from src.models import Assignment, RaceState, Runner
from src.optimizer import plan, replan, simulate
from src.state import empty_state, load_constants, load_courses, load_team


def _planned_state():
    """Build a full pre-race plan; cached per test session via module-level fixture."""
    c = load_constants()
    courses = load_courses()
    team = load_team()
    base = empty_state(courses, team)
    return plan(base, team, c), c, courses, team


def test_plan_starts_with_SF_at_race_start():
    state, c, _, _ = _planned_state()
    first = sorted(state.assignments, key=lambda x: x.cycle)[0]
    assert first.cycle == 1
    assert first.course.code == "SF"
    assert first.planned_start == c.RACE_START


def test_plan_runs_all_TH_in_first_six_cycles():
    state, _c, _, _ = _planned_state()
    th_cycles = [a.cycle for a in state.assignments if a.course.type == "TH"]
    assert sorted(th_cycles) == [2, 3, 4, 5, 6]


def test_plan_places_ST_LT_in_twilight_window():
    """ST and LT must run *during* civil twilight. They can start no earlier
    than ``TWILIGHT_TIME - TWILIGHT_EARLY_UNLOCK_MIN`` (the safety release
    valve when every remaining day course would worst-case overshoot the
    Wechselzeitpunkt) and must finish before the second-day daylight cap."""
    from datetime import timedelta
    state, c, _, _ = _planned_state()
    earliest = c.TWILIGHT_TIME - timedelta(minutes=c.TWILIGHT_EARLY_UNLOCK_MIN)
    for code in ("ST", "LT"):
        a = next(x for x in state.assignments if x.course.code == code)
        assert a.planned_start >= earliest, (
            f"{code} starts {a.planned_start.time()} — earlier than the "
            f"early-unlock window opens at {earliest.time()}"
        )
        assert a.planned_finish < c.DAY_RESUME, (
            f"{code} finishes {a.planned_finish.time()} — past the dark stretch"
        )


def test_plan_FF_is_last_or_skipped():
    state, _c, _, _ = _planned_state()
    ff_legs = [a for a in state.assignments if a.course.code == "FF"]
    if ff_legs:
        assert ff_legs[0].cycle == max(a.cycle for a in state.assignments)


def test_plan_finishes_before_cutoff():
    state, c, _, _ = _planned_state()
    last = max(a.planned_finish for a in state.assignments)
    assert last <= c.CUTOFF_TIME


def test_plan_projects_reasonable_count():
    state, _c, _, _ = _planned_state()
    count = len(state.assignments)
    # Mid-pack 24h-OL teams typically do 25-35 courses; with the configured
    # defaults our team should land in that range.
    assert 20 <= count <= 37, f"projected {count} courses, out of plausible range"


def test_replan_after_slow_finish_shifts_or_drops_courses():
    state, c, _, _ = _planned_state()
    # Simulate the first leg coming in 50% slower than predicted.
    first = sorted(state.assignments, key=lambda x: x.cycle)[0]
    actual = first.planned_duration_min * 1.5
    first.actual_start = c.RACE_START
    first.actual_duration_min = actual
    first.status = "done"
    state.pace_multiplier[first.runner.name] = update_multiplier(
        first.runner, first.course, actual, 1.0, c
    )
    rep = replan(state, c)
    # The new last-finish should still be within cutoff.
    last = max(a.planned_finish for a in rep.assignments)
    assert last <= c.CUTOFF_TIME
    # Total count should be <= original (we lost some time).
    assert len(rep.assignments) <= len(state.assignments) + 0  # not more than before


def test_optimiser_assigns_hard_courses_by_comparative_advantage():
    """In team A, Sofia (T=6) should run more H/HN courses than Alicia (T=1).
    In a swapped team where Alicia is the only competent runner, the assignment
    flips. This tests that the optimiser actually uses per-runner T/K rather
    than just picking shortest courses for whoever is up."""
    c = load_constants()
    courses = load_courses()

    team_a = load_team()
    base_a = empty_state(courses, team_a)
    out_a = plan(base_a, team_a, c)
    sofia_hard_a = sum(
        1 for a in out_a.assignments
        if a.runner.name == "Sofia" and a.course.type in ("H", "HN")
    )
    alicia_hard_a = sum(
        1 for a in out_a.assignments
        if a.runner.name == "Alicia" and a.course.type in ("H", "HN")
    )
    assert sofia_hard_a > alicia_hard_a, (
        f"Sofia (T=6) should run more H/HN than Alicia (T=1); "
        f"got Sofia={sofia_hard_a}, Alicia={alicia_hard_a}"
    )

    team_b = [
        Runner(name="Sofia", T=1, K=1),
        Runner(name="Hannes", T=1, K=1),
        Runner(name="Erich", T=1, K=1),
        Runner(name="Christine", T=1, K=1),
        Runner(name="Flocke", T=1, K=1),
        Runner(name="Alicia", T=6, K=6),
    ]
    base_b = empty_state(courses, team_b)
    out_b = plan(base_b, team_b, c)
    sofia_hard_b = sum(
        1 for a in out_b.assignments
        if a.runner.name == "Sofia" and a.course.type in ("H", "HN")
    )
    alicia_hard_b = sum(
        1 for a in out_b.assignments
        if a.runner.name == "Alicia" and a.course.type in ("H", "HN")
    )
    assert alicia_hard_b > sofia_hard_b, (
        f"in swapped team, Alicia (T=6) should run more H/HN than Sofia (T=1); "
        f"got Sofia={sofia_hard_b}, Alicia={alicia_hard_b}"
    )


DAY_TYPES = {"SF", "TH", "E", "H"}


def test_plan_keeps_every_day_course_inside_daylight():
    """Rule §5.3.4: the team must be on Dämmerungsbahnen (ST/LT) from
    TWILIGHT_TIME onward. Day maps carry no reflectors, so a day course
    planned to finish anywhere in ``[TWILIGHT_TIME, DAY_RESUME)`` is both
    rule-noncompliant on the next handover and unsafe (fading light)."""
    state, c, _, _ = _planned_state()
    violations = [
        a for a in state.assignments
        if a.course.type in DAY_TYPES
        and c.TWILIGHT_TIME <= a.planned_finish < c.DAY_RESUME
    ]
    assert not violations, (
        "day-type courses scheduled into twilight/night: "
        + ", ".join(
            f"cycle {a.cycle} {a.runner.name} {a.course.code} "
            f"finish={a.planned_finish.strftime('%H:%M')}"
            for a in violations
        )
    )


def test_pace_multiplier_is_clamped():
    """Bug 2 root cause: a single 1000-min finish was driving the multiplier to
    ~40, after which every future leg for that runner predicted hours and the
    simulator halted. Both extremes must be clamped."""
    c = load_constants()
    courses = load_courses()
    team = load_team()
    hannes = next(r for r in team if r.name == "Hannes")
    sf = courses["SF"]

    # 1000-min observation → without clamp would land at ~40×.
    high = update_multiplier(hannes, sf, 1000.0, 1.0, c)
    assert high <= c.PACE_MULTIPLIER_MAX, f"multiplier escaped upper clamp: {high}"

    # 1-min observation → without clamp would land near 0.04.
    low = update_multiplier(hannes, sf, 1.0, 1.0, c)
    assert low >= c.PACE_MULTIPLIER_MIN, f"multiplier escaped lower clamp: {low}"


def test_replan_keeps_simulating_after_extreme_finish_input():
    """Bug 2: a wild actual time (1000 min) must not brick the planner. The
    replan must still schedule all remaining runners; this is the test the
    user's screenshot fails (12 done + 0 planned, "Bahnen 12/37")."""
    state, c, _, _ = _planned_state()

    # Stamp the first leg with a 1000-minute "DNF / typo / lost runner" actual.
    first = sorted(state.assignments, key=lambda x: x.cycle)[0]
    first.actual_start = c.RACE_START
    first.actual_duration_min = 1000.0
    first.status = "done"
    state.pace_multiplier[first.runner.name] = update_multiplier(
        first.runner, first.course, 1000.0, 1.0, c
    )

    rep = replan(state, c)
    planned_after = sum(1 for a in rep.assignments if a.status == "planned")
    # If the multiplier clamp is working, the simulator should still produce
    # *some* future schedule rather than halting at the next blocked-runner cycle.
    assert planned_after >= 5, (
        f"replan halted after extreme finish; only {planned_after} legs planned"
    )


def test_replan_adds_more_courses_when_runners_are_faster():
    """The flip side of bug 2: when finishes come in *faster* than predicted,
    replan must extend the schedule with new legs to absorb the slack — not
    leave the original count untouched."""
    state, c, _, _ = _planned_state()
    baseline_count = len(state.assignments)

    # Stamp the first 6 legs (one cycle) as 30% faster than predicted.
    for a in sorted(state.assignments, key=lambda x: x.cycle)[:6]:
        a.actual_start = a.planned_start
        a.actual_duration_min = a.planned_duration_min * 0.7
        a.status = "done"
        state.pace_multiplier[a.runner.name] = update_multiplier(
            a.runner, a.course, a.actual_duration_min, 1.0, c
        )

    rep = replan(state, c)
    assert len(rep.assignments) >= baseline_count, (
        f"team finished faster but replan shrank: was {baseline_count}, "
        f"now {len(rep.assignments)}"
    )


def test_simulate_with_locked_order_respects_cyclic_runner_sequence():
    c = load_constants()
    courses = load_courses()
    team = load_team()
    base = empty_state(courses, team)
    out = simulate(base, team, c, rollout_depth=0)
    for a in out.assignments:
        expected = team[(a.cycle - 1) % 6]
        assert a.runner.name == expected.name, (
            f"cycle {a.cycle} should be {expected.name}, got {a.runner.name}"
        )


# ---------------------------------------------------------------------------
# Regression: bug 1 — day courses must not be planned to finish in darkness.
# ---------------------------------------------------------------------------


def test_no_planned_day_course_runs_in_dark_window():
    """No day-type course (SF/TH/E/H) may finish in the dark stretch
    ``[TWILIGHT_TIME, DAY_RESUME)``. Rule §5.3.4 mandates that teams be on
    Dämmerungsbahnen at TWILIGHT_TIME, and day maps lack reflectors so they
    are unreadable thereafter. A day course is legal only when it finishes
    strictly before TWILIGHT_TIME (Saturday daylight) or starts at/after
    DAY_RESUME (Sunday morning daylight). The previous version happily
    scheduled H7 at 19:34 finishing 20:55, exactly what the user flagged as
    'extremely risky'.
    """
    state, c, _, _ = _planned_state()
    for a in state.assignments:
        if a.course.type not in ("SF", "TH", "E", "H"):
            continue
        finishes_in_daylight = a.planned_finish < c.TWILIGHT_TIME
        starts_after_resume = a.planned_start >= c.DAY_RESUME
        assert finishes_in_daylight or starts_after_resume, (
            f"cycle {a.cycle} {a.runner.name} {a.course.code} "
            f"({a.course.type}) runs {a.planned_start.time()}–{a.planned_finish.time()} "
            f"which crosses or sits inside the dark window "
            f"[{c.TWILIGHT_TIME.time()}, {c.DAY_RESUME.time()})"
        )


# ---------------------------------------------------------------------------
# Regression: bug 2 — an outlier actual must not disable a runner for the
# remainder of the race. Before the clamp, a 1000-min entry pushed Hannes'
# multiplier to ~18x; every future Hannes leg "exceeded the cutoff" and
# `simulate` halted with no further assignments.
# ---------------------------------------------------------------------------


def test_pace_multiplier_clamped_within_configured_bounds():
    c = load_constants()
    courses = load_courses()
    team = load_team()
    hannes = next(r for r in team if r.name == "Hannes")
    h1 = courses["H1"]

    # 1000 min on a ~22 min course — extreme outlier (typo / DNF).
    new_mult = update_multiplier(hannes, h1, 1000.0, 1.0, c)
    assert new_mult <= c.PACE_MULTIPLIER_MAX, (
        f"a 1000-min outlier pushed multiplier to {new_mult}, "
        f"above PACE_MULTIPLIER_MAX={c.PACE_MULTIPLIER_MAX}"
    )

    # Symmetric: a runner crossing in 0.1 min (typo) must not collapse pace below MIN.
    new_mult_fast = update_multiplier(hannes, h1, 0.1, 1.0, c)
    assert new_mult_fast >= c.PACE_MULTIPLIER_MIN


def test_replan_continues_after_extreme_actual():
    """The user's failure scenario: cycle 7 records 1000 actual minutes for
    Hannes' H1 leg. Before the clamp, every subsequent Hannes leg was
    predicted to take ~18x its baseline and replan returned no further
    assignments. After the clamp, the replan must still produce a tail.
    """
    state, c, _, _ = _planned_state()
    assignments_by_cycle = {a.cycle: a for a in state.assignments}

    # Mark cycles 1..7 done. Cycles 1..6 finish at planned times; cycle 7
    # (Hannes H1) gets the disastrous 1000-min outlier.
    prev_finish = c.RACE_START
    for cyc in range(1, 7):
        a = assignments_by_cycle[cyc]
        a.actual_start = prev_finish
        a.actual_duration_min = a.planned_duration_min
        a.status = "done"
        state.pace_multiplier[a.runner.name] = update_multiplier(
            a.runner, a.course, a.actual_duration_min,
            state.pace_multiplier.get(a.runner.name, 1.0), c,
        )
        prev_finish = a.actual_finish

    seven = assignments_by_cycle[7]
    seven.actual_start = prev_finish
    seven.actual_duration_min = 1000.0
    seven.status = "done"
    state.pace_multiplier[seven.runner.name] = update_multiplier(
        seven.runner, seven.course, 1000.0,
        state.pace_multiplier.get(seven.runner.name, 1.0), c,
    )

    # Sanity: the clamp must have engaged.
    assert state.pace_multiplier[seven.runner.name] <= c.PACE_MULTIPLIER_MAX

    rep = replan(state, c)
    new_legs = [a for a in rep.assignments if a.status != "done"]
    # The previous (broken) behaviour: no new legs at all. After the fix:
    # the cutoff is still ~3.5h away after the 1000-min stretch, so there
    # must be SOME further legs in the schedule.
    assert len(new_legs) >= 1, (
        "replan produced no further legs after an extreme actual; "
        "the multiplier clamp should keep predictions tractable"
    )
    # And every planned finish stays within the hard cutoff.
    for a in new_legs:
        assert a.planned_finish <= c.CUTOFF_TIME, (
            f"replan placed leg cycle {a.cycle} past the cutoff"
        )


# ---------------------------------------------------------------------------
# Rollout tiebreaker (rule §9: more courses wins, ties go to earliest finish).
# Before the fix, _pick_best_course's comparison was inverted on the second
# axis — among candidates that produced the same projected course count, the
# *latest* finish won. That made the optimiser systematically pick longer
# courses on ties, eating slack that could fit one more cycle later.
# ---------------------------------------------------------------------------


def test_rollout_tiebreaker_prefers_earlier_finish():
    """Among rollout candidates that yield the same total cycle count, the
    chosen course must be the one whose simulated finish is earliest. This
    is both rule §9 (Einlaufreihenfolge breaks ties) and the lever that often
    unlocks one extra cycle later in the schedule."""
    from datetime import timedelta
    from src.optimizer import (
        _candidate_scores,
        _clone_state,
        _legal,
        _pick_best_course,
        _rollout_value,
    )
    from src.state import empty_state

    c = load_constants()
    courses = load_courses()
    team = load_team()
    base = empty_state(courses, team)
    state = plan(base, team, c)

    # Stamp cycles 1..12 done with a 1000-min cycle-7 outlier and 1-min
    # cycles 8..12 — the same scenario the user reported on. The replan
    # then has cycle 13 as the next decision point.
    a_by_cycle = {a.cycle: a for a in state.assignments}
    prev_finish = c.RACE_START
    for cyc in range(1, 13):
        a = a_by_cycle[cyc]
        a.actual_start = prev_finish
        if cyc == 7:
            a.actual_duration_min = 1000.0
        elif cyc == 8:
            a.actual_duration_min = 12.0
        else:
            a.actual_duration_min = (
                a.planned_duration_min if cyc <= 6 else 1.0
            )
        a.status = "done"
        state.pace_multiplier[a.runner.name] = update_multiplier(
            a.runner, a.course, a.actual_duration_min,
            state.pace_multiplier.get(a.runner.name, 1.0), c,
        )
        prev_finish = a.actual_finish

    # Find the cycle-13 decision point.
    state2 = _clone_state(state)
    state2.assignments = [x for x in state2.assignments if x.status == "done"]
    state2.completed_codes = {x.course.code for x in state2.assignments}
    now = max(state2.assignments, key=lambda x: x.cycle).actual_finish

    legal = _legal(state2, now, c)
    runner = state2.runner_for_cycle(13)
    candidates = _candidate_scores(state2, runner, legal, now, c, 13)
    assert candidates, "no candidates at cycle 13 — test setup is wrong"
    top = candidates[: c.ROLLOUT_TOP_K]

    # Compute each top-candidate's projected (total_cycles, finish_min).
    handover = timedelta(seconds=c.HANDOVER_OVERHEAD_SEC)
    outcomes = []
    for _, course, mean, _sigma in top:
        sub = _clone_state(state2)
        sub.completed_codes.add(course.code)
        new_now = now + timedelta(minutes=mean) + handover
        gained, finish_min = _rollout_value(sub, new_now, 14, c, c.ROLLOUT_DEPTH - 1)
        outcomes.append((1 + gained, finish_min, course))

    pick = _pick_best_course(state2, now, 13, c, c.ROLLOUT_DEPTH)
    assert pick is not None, "pick_best returned None for non-empty candidates"
    chosen_course, _, _ = pick
    chosen = next(o for o in outcomes if o[2].code == chosen_course.code)
    best_total = max(o[0] for o in outcomes)
    same_count = [o for o in outcomes if o[0] == best_total]
    earliest = min(same_count, key=lambda o: o[1])
    assert chosen[2].code == earliest[2].code, (
        f"on a {best_total}-cycle tie, optimiser picked {chosen[2].code} "
        f"(finish={chosen[1]:.1f}) but should have picked {earliest[2].code} "
        f"(finish={earliest[1]:.1f}) — earliest finish breaks ties"
    )


def test_forbid_courses_excluded_from_runner_candidates():
    """A course in a runner's ``forbid_courses`` set must never surface as a
    candidate for that runner — even when it's in the legal pool and would
    otherwise score well. Stacks on top of the phase machine and cutoff
    filter as a third independent gate (extensions.md §4)."""
    from src.optimizer import _candidate_scores, _legal

    c = load_constants()
    courses = load_courses()
    team = load_team()
    base = empty_state(courses, team)

    # Synthesise a runner with EN7 explicitly forbidden, plug them into the
    # cyclic order, and rewind to a "night phase" moment where EN7 is in the
    # legal pool. Anyone *without* the forbid sees EN7; the forbidden runner
    # never does.
    christine = next(r for r in team if r.name == "Christine")
    assert "EN7" in christine.forbid_courses, "team.yaml regression: Christine should be forbidden EN7"

    # Move state into a night-legal phase by marking all TH and ST/LT done.
    state = empty_state(courses, team)
    state.runners_in_order = team
    state.completed_codes = {
        "SF", "TH1", "TH2", "TH3", "TH4", "TH5", "ST", "LT",
        "E1", "E2", "E3", "H1", "H2",
    }

    now = c.TWILIGHT_TIME + timedelta(minutes=30)  # well into the night window
    legal = _legal(state, now, c)
    assert any(course.code == "EN7" for course in legal), (
        "legal pool should include EN7 in the night phase after ST/LT done"
    )

    # Christine: EN7 must be absent. Pick a cycle in the post-twilight night
    # window for the reservation logic to compute against.
    cycle = 22
    cands = _candidate_scores(state, christine, legal, now, c, cycle)
    assert all(course.code != "EN7" for _, course, _, _ in cands), (
        "Christine has EN7 in forbid_courses but it still appears as a candidate"
    )

    # Sanity: a non-forbidden teammate (Hannes) DOES see EN7 in the legal
    # candidate list when slack permits. This proves the filter is per-runner,
    # not a global drop.
    hannes = next(r for r in team if r.name == "Hannes")
    assert "EN7" not in hannes.forbid_courses
    cands_h = _candidate_scores(state, hannes, legal, now, c, cycle)
    if any(course.code == "EN7" for _, course, _, _ in cands_h):
        pass  # expected case: EN7 visible to Hannes
    else:
        # Acceptable fallback: EN7 might be cutoff-filtered for Hannes too at
        # this very late `now`. The point is that *if* it's visible to anyone
        # it's not Christine. Re-verify with a far earlier `now`.
        early = c.TWILIGHT_TIME + timedelta(minutes=5)
        legal_e = _legal(state, early, c)
        cands_h2 = _candidate_scores(state, hannes, legal_e, early, c, cycle)
        assert any(course.code == "EN7" for _, course, _, _ in cands_h2), (
            "EN7 should be a candidate for Hannes at some legal night moment"
        )


def test_forbid_types_excluded_from_runner_candidates():
    """``forbid_types`` blocks every course of a type for that runner.
    Alicia in team.yaml is forbidden from H and HN; no H/HN course may ever
    surface as a candidate for her, even when one is in the legal pool."""
    from src.optimizer import _candidate_scores, _legal

    c = load_constants()
    courses = load_courses()
    team = load_team()

    alicia = next(r for r in team if r.name == "Alicia")
    assert {"H", "HN"} <= alicia.forbid_types

    state = empty_state(courses, team)
    state.runners_in_order = team
    # Day phase first: H must be legal but invisible to Alicia.
    state.completed_codes = {"SF", "TH1", "TH2", "TH3", "TH4", "TH5"}
    day_now = c.RACE_START + timedelta(hours=4)
    legal_day = _legal(state, day_now, c)
    assert any(course.type == "H" for course in legal_day)
    cands_day = _candidate_scores(state, alicia, legal_day, day_now, c, 7)
    assert all(course.type != "H" for _, course, _, _ in cands_day), (
        "Alicia has 'H' in forbid_types but H courses still appear"
    )

    # Night phase: HN must be legal but invisible to Alicia.
    state.completed_codes |= {"ST", "LT"}
    night_now = c.TWILIGHT_TIME + timedelta(minutes=30)
    legal_night = _legal(state, night_now, c)
    assert any(course.type == "HN" for course in legal_night)
    cands_night = _candidate_scores(state, alicia, legal_night, night_now, c, 21)
    assert all(course.type != "HN" for _, course, _, _ in cands_night), (
        "Alicia has 'HN' in forbid_types but HN courses still appear"
    )


def test_reservation_triggers_when_constrained_teammate_is_tight():
    """When a constrained teammate's allowed-in-legal pool shrinks to within
    one of their remaining cycles, an unconstrained current runner should
    yield those courses (extensions.md §4 reservation sub-feature).

    Setup: late night phase, Alicia (forbidden H/HN/long-E/long-EN) has only
    EN2, EN3, EN4 legal-and-allowed with two remaining cycles. Hannes
    deciding at this moment must NOT see EN2/EN3/EN4 in his candidates —
    they're reserved for Alicia.
    """
    from src.optimizer import _candidate_scores, _legal, _reserved_for_constrained_teammates

    c = load_constants()
    courses = load_courses()
    team = load_team()

    alicia = next(r for r in team if r.name == "Alicia")
    hannes = next(r for r in team if r.name == "Hannes")
    assert {"H", "HN"} <= alicia.forbid_types
    assert "EN5" in alicia.forbid_courses and "EN6" in alicia.forbid_courses

    # Construct a state late in the night phase: SF, all TH, ST, LT, all E,
    # all H, and EN1 done. Alicia's legal-and-allowed pool is then exactly
    # {EN2, EN3, EN4} — three courses, and she has two more cyclic slots
    # ahead (slack = 1, the tight threshold).
    state = empty_state(courses, team)
    state.runners_in_order = team
    state.completed_codes = {
        "SF",
        "TH1", "TH2", "TH3", "TH4", "TH5",
        "E1", "E2", "E3", "E4", "E5", "E6", "E7",
        "H1", "H2", "H3", "H4", "H5", "H6", "H7",
        "ST", "LT", "EN1",
    }
    now = c.TWILIGHT_TIME + timedelta(minutes=60)

    # Pin Alicia at slot 0 for determinism. With 6 runners, slot 0 → cycles
    # 1, 7, 13, 19, 25, 31. At current_cycle=24, Alicia's future cycles in
    # [24, 24 + len(course_pool)) are 25 and 31 → r_remaining = 2. Combined
    # with her 3 allowed-in-legal codes that's slack = 1 (the tight edge).
    state.runners_in_order = [alicia] + [r for r in team if r.name != "Alicia"]
    current_cycle = 24  # decider is slot (24-1)%6 = 5 → 6th runner (not Alicia)

    legal = _legal(state, now, c)
    assert {"EN2", "EN3", "EN4"} <= {co.code for co in legal}

    # The current decider is at slot 5 (not Alicia). They should see Alicia's
    # remaining pool reserved.
    decider = state.runners_in_order[5]
    assert decider.name != "Alicia"
    reserved = _reserved_for_constrained_teammates(
        state, decider, current_cycle, legal, now, c
    )
    assert {"EN2", "EN3", "EN4"} <= reserved, (
        f"Alicia is tight (3 allowed-legal vs 2 remaining cycles) but her pool "
        f"{{'EN2','EN3','EN4'}} is not reserved. Got reserved={reserved}"
    )

    # End-to-end: candidate scoring for the decider does NOT include
    # EN2/EN3/EN4 (they're reserved away to Alicia).
    cands = _candidate_scores(state, decider, legal, now, c, current_cycle)
    cand_codes = {course.code for _, course, _, _ in cands}
    assert not (cand_codes & {"EN2", "EN3", "EN4"}), (
        f"decider's candidates include Alicia-reserved courses: "
        f"{cand_codes & {'EN2', 'EN3', 'EN4'}}"
    )


def test_reservation_falls_back_when_filtering_kills_all_candidates():
    """Reservation is *advisory*. If the only legal courses are all reserved
    for tighter teammates, the current runner must still get a candidate
    (we don't halt the race over a soft constraint). The retry-without-
    reservation pass in ``_candidate_scores`` provides this safety valve.
    """
    from src.optimizer import _candidate_scores, _legal

    c = load_constants()
    courses = load_courses()
    team = load_team()

    # Pathological setup: drive Alicia into deep tightness *and* deplete all
    # non-Alicia options in the legal pool. The decider has zero options
    # except Alicia's reserved set; fallback must return them.
    alicia = next(r for r in team if r.name == "Alicia")
    state = empty_state(courses, team)
    state.runners_in_order = [alicia] + [r for r in team if r.name != "Alicia"]

    # Complete everything except EN2/EN3/EN4. Now the only legal night
    # courses are exactly Alicia's tight pool.
    everything_except = {
        c.code for c in courses.values()
        if c.code not in {"EN2", "EN3", "EN4"}
    }
    state.completed_codes = everything_except

    now = c.TWILIGHT_TIME + timedelta(minutes=60)
    legal = _legal(state, now, c)
    assert {co.code for co in legal} <= {"EN2", "EN3", "EN4"}

    # Decider is *not* Alicia. With reservation strictly applied they'd see
    # zero candidates; the fallback pass must rescue them.
    decider = state.runners_in_order[1]  # slot 1, runs at cycle 2, 8, 14, ...
    cands = _candidate_scores(state, decider, legal, now, c, 26)
    assert cands, (
        "fallback failed: reservation should retry without itself when it "
        "filters out every legal candidate"
    )


def test_plan_honors_forbid_matrix_end_to_end():
    """Full pre-race plan: no assignment in the final schedule may pair a
    runner with one of their forbidden codes or types. This catches the
    case where the filter works in isolation but a code path elsewhere
    (rollout, replan) bypasses it."""
    state, _c, _, team = _planned_state()
    by_name = {r.name: r for r in team}
    violations = []
    for a in state.assignments:
        r = by_name[a.runner.name]
        if a.course.code in r.forbid_courses or a.course.type in r.forbid_types:
            violations.append(
                f"cycle {a.cycle} {r.name} → {a.course.code} ({a.course.type})"
            )
    assert not violations, "forbid-matrix violations in plan: " + "; ".join(violations)


def test_replan_after_user_scenario_extends_schedule():
    """The user's exact reported scenario: cycle 7 takes 1000 min and cycles
    8..12 each take ~1 min. With the rollout tiebreaker fix in place, the
    replan should produce *more* than the previously-stuck 4 planned cycles
    (13..16) — picking shorter courses at cycle 13 frees up slack for at
    least one more leg before the cutoff."""
    c = load_constants()
    courses = load_courses()
    team = load_team()
    base = empty_state(courses, team)
    state = plan(base, team, c)

    a_by_cycle = {a.cycle: a for a in state.assignments}
    prev = c.RACE_START
    durations = {7: 1000.0, 8: 12.0, 9: 1.0, 10: 1.0, 11: 1.0, 12: 1.0}
    for cyc in range(1, 13):
        a = a_by_cycle[cyc]
        a.actual_start = prev
        a.actual_duration_min = durations.get(cyc, a.planned_duration_min)
        a.status = "done"
        state.pace_multiplier[a.runner.name] = update_multiplier(
            a.runner, a.course, a.actual_duration_min,
            state.pace_multiplier.get(a.runner.name, 1.0), c,
        )
        prev = a.actual_finish

    rep = replan(state, c)
    planned_count = sum(1 for a in rep.assignments if a.status == "planned")
    assert planned_count >= 5, (
        f"replan should fit ≥5 cycles after the user's slow-then-fast scenario; "
        f"got {planned_count}. The tiebreaker fix should have freed up at least "
        f"one extra cycle by picking shorter courses on cycle 13."
    )
