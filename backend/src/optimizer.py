from __future__ import annotations

import copy
import itertools
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Iterable, Optional

from .models import Assignment, Constants, Course, RaceState, Runner
from .phases import DAY_TYPES, legal_next_courses
from .time_model import predict_time


def _legal(state: RaceState, now: datetime, constants: Constants) -> list[Course]:
    """Centralised legal-pool lookup so every call site passes the same kwargs.

    Two knobs are wired through:
      * ``day_resume`` (with the morning-side ``DAY_DISPATCH_BUFFER_MIN``
        applied) — combined with ``TWILIGHT_TIME``, drops day-type maps from
        the legal pool whenever the dispatch moment is inside the dark window
        ``[TWILIGHT_TIME, DAY_RESUME + buffer)``. Rule §5.3.4 mandates the
        switch to twilight maps at TWILIGHT_TIME and day maps carry no
        reflectors — so we keep them locked through the entire dark stretch.
        The morning buffer absorbs the fast-tail case where a previous leg
        runs faster than mean and would otherwise drag the day-map dispatch
        back into pre-sunrise twilight.
      * ``twilight_early_unlock_min`` — allow ST/LT to be picked a few minutes
        before the announced TWILIGHT_TIME as a release valve when every
        remaining day course would worst-case overshoot the Wechselzeitpunkt.

    The per-candidate ``_day_course_unsafe`` check below stacks on top, adding
    the finer "this *specific* course's worst-case finish would cross
    TWILIGHT_TIME" filter that the coarse phase filter alone cannot express.
    """
    effective_day_resume = constants.DAY_RESUME + timedelta(
        minutes=constants.DAY_DISPATCH_BUFFER_MIN
    )
    return legal_next_courses(
        state,
        now,
        constants.TWILIGHT_TIME,
        day_resume=effective_day_resume,
        twilight_early_unlock_min=constants.TWILIGHT_EARLY_UNLOCK_MIN,
    )


def _day_course_unsafe(
    course: Course, now: datetime, mean: float, sigma: float, constants: Constants
) -> bool:
    """True if this day-type course's worst-case finish lands past the Wechselzeitpunkt.

    Rule §5.3.4 mandates the team to be on Dämmerungsbahnen (ST/LT) from
    ``TWILIGHT_TIME`` onward, and day maps carry no reflectors — a runner
    finishing a day course at or after TWILIGHT_TIME is already in fading
    light, off the rule-mandated phase, and progressively harder to extract.
    So a day map is only safe to dispatch if its realistic slow-tail finish
    (``mean + DAY_SAFETY_SIGMA * sigma``) lands strictly before TWILIGHT_TIME.

    The check stays open at the top: any finish past TWILIGHT_TIME up to
    DAY_RESUME (next morning daylight) is flagged. Non-day courses are never
    flagged.
    """
    if course.type not in DAY_TYPES:
        return False
    finish = now + timedelta(minutes=mean + constants.DAY_SAFETY_SIGMA * sigma)
    return constants.TWILIGHT_TIME <= finish < constants.DAY_RESUME


def _clone_state(state: RaceState) -> RaceState:
    return RaceState(
        runners_in_order=list(state.runners_in_order),
        assignments=list(state.assignments),
        course_pool=state.course_pool,
        completed_codes=set(state.completed_codes),
        pace_multiplier=dict(state.pace_multiplier),
    )


def _current_time_after_history(state: RaceState, constants: Constants) -> tuple[datetime, int]:
    """Return (now, next_cycle) given done/in-progress assignments.

    The next runner's start equals the previous runner's finish (or the race
    start if nothing has run yet).
    """
    if not state.assignments:
        return constants.RACE_START, 1
    last = state.assignments[-1]
    if last.status == "done" and last.actual_finish is not None:
        return last.actual_finish, last.cycle + 1
    return last.planned_finish, last.cycle + 1


def _risk_adjusted_minutes(
    mean: float, sigma: float, now: datetime, cutoff: datetime, threshold: float
) -> float:
    """Switch to mean+sigma when remaining slack is tight relative to this run's sigma."""
    slack_min = (cutoff - now).total_seconds() / 60.0 - mean
    if slack_min < threshold * sigma:
        return mean + sigma
    return mean


def _candidate_scores(
    state: RaceState,
    runner: Runner,
    legal: list[Course],
    now: datetime,
    constants: Constants,
) -> list[tuple[float, Course, float, float]]:
    """Return (score, course, mean, sigma) for each legal course that fits before cutoff.

    Score blends two signals:
      1. 1 / risk_adjusted_minutes  — be efficient with time;
      2. comparative advantage      — prefer courses on which this runner is
                                      much faster than the team median. This is
                                      what makes the optimiser assign HN/H
                                      courses to high-T runners and long E
                                      courses to high-K runners instead of
                                      everyone naively picking the shortest
                                      legal course.

    Comparative advantage = median_other_time / my_time. A value of 2.0 means
    "I do this course in half the time the median teammate would", which
    strongly suggests the team should spend MY minute here rather than someone
    else's.
    """
    mult = state.pace_multiplier.get(runner.name, 1.0)
    handover = timedelta(seconds=constants.HANDOVER_OVERHEAD_SEC).total_seconds() / 60.0
    other_runners = [r for r in state.runners_in_order if r.name != runner.name]

    safe: list[tuple[float, Course, float, float]] = []
    unsafe_day: list[tuple[float, Course, float, float]] = []
    for course in legal:
        mean, sigma = predict_time(runner, course, constants, mult)
        if now + timedelta(minutes=mean) > constants.CUTOFF_TIME:
            continue
        adj = _risk_adjusted_minutes(
            mean, sigma, now, constants.CUTOFF_TIME, constants.SAFETY_SIGMA_THRESHOLD
        )
        if now + timedelta(minutes=adj) > constants.CUTOFF_TIME:
            continue

        if other_runners:
            other_means = []
            for r in other_runners:
                m_r = state.pace_multiplier.get(r.name, 1.0)
                t, _ = predict_time(r, course, constants, m_r)
                other_means.append(t)
            other_means.sort()
            median_other = other_means[len(other_means) // 2]
            advantage = median_other / mean
        else:
            advantage = 1.0

        score = advantage / (adj + handover)
        record = (score, course, mean, sigma)
        if _day_course_unsafe(course, now, mean, sigma, constants):
            unsafe_day.append(record)
        else:
            safe.append(record)

    safe.sort(key=lambda x: x[0], reverse=True)
    if safe:
        return safe
    # Hard-corner fallback: every legal option would put a day map in the dark.
    # Pick the single least-risky one (shortest predicted duration ⇒ smallest
    # encroachment into twilight). This keeps the relay moving rather than
    # halting; the leg will be visibly short which lets the team see the
    # squeeze and bail to twilight courses early on race day.
    unsafe_day.sort(key=lambda x: x[2])
    return unsafe_day[:1]


def _greedy_tail_count(
    state: RaceState, now: datetime, cycle: int, constants: Constants
) -> int:
    """Fast greedy continuation. No rollout. Returns extra courses gained."""
    gained = 0
    handover = timedelta(seconds=constants.HANDOVER_OVERHEAD_SEC)
    while True:
        if now > constants.CUTOFF_TIME:
            break
        legal = _legal(state, now, constants)
        if not legal:
            break
        runner = state.runner_for_cycle(cycle)
        cands = _candidate_scores(state, runner, legal, now, constants)
        if not cands:
            break
        _, course, mean, _sigma = cands[0]
        state.completed_codes.add(course.code)
        gained += 1
        now = now + timedelta(minutes=mean) + handover
        cycle += 1
    return gained


def _pick_best_course(
    state: RaceState,
    now: datetime,
    cycle: int,
    constants: Constants,
    depth: int,
) -> Optional[tuple[Course, float, float]]:
    legal = _legal(state, now, constants)
    if not legal:
        return None
    runner = state.runner_for_cycle(cycle)
    candidates = _candidate_scores(state, runner, legal, now, constants)
    if not candidates:
        return None

    top = candidates[: max(1, constants.ROLLOUT_TOP_K)]

    # Depth-0 shortcut: just take the best by score.
    if depth <= 0 or len(top) == 1:
        _, course, mean, sigma = top[0]
        return course, mean, sigma

    handover = timedelta(seconds=constants.HANDOVER_OVERHEAD_SEC)
    # Metric is (count, -finish_min); larger wins on both axes. Rule §9: the
    # team with more courses wins, ties go to whoever finishes earlier.
    best_metric: Optional[tuple[int, float]] = None
    best_choice: Optional[tuple[Course, float, float]] = None

    for _, course, mean, sigma in top:
        sub = _clone_state(state)
        sub.completed_codes.add(course.code)
        new_now = now + timedelta(minutes=mean) + handover
        # Recurse one level deeper, then greedy tail.
        recursive = _rollout_value(sub, new_now, cycle + 1, constants, depth - 1)
        total = 1 + recursive[0]
        finish_min = recursive[1]
        metric = (total, -finish_min)
        if best_metric is None or metric > best_metric:
            best_metric = metric
            best_choice = (course, mean, sigma)
    return best_choice


def _rollout_value(
    state: RaceState, now: datetime, cycle: int, constants: Constants, depth: int
) -> tuple[int, float]:
    """Return (extra_courses_gained, final_now_minutes_from_race_start).

    Up to `depth` recursive expansions then greedy tail.
    """
    gained = 0
    handover = timedelta(seconds=constants.HANDOVER_OVERHEAD_SEC)
    local_state = _clone_state(state)
    local_now = now
    local_cycle = cycle

    while depth > 0:
        legal = _legal(local_state, local_now, constants)
        if not legal:
            break
        runner = local_state.runner_for_cycle(local_cycle)
        candidates = _candidate_scores(local_state, runner, legal, local_now, constants)
        if not candidates:
            break
        # Single-level expansion of the best by score (no further recursion to keep cost bounded).
        _, course, mean, _sigma = candidates[0]
        local_state.completed_codes.add(course.code)
        gained += 1
        local_now = local_now + timedelta(minutes=mean) + handover
        local_cycle += 1
        depth -= 1

    # Greedy tail.
    gained += _greedy_tail_count(local_state, local_now, local_cycle, constants)
    final_min = (local_now - constants.RACE_START).total_seconds() / 60.0
    return gained, final_min


def simulate(
    base_state: RaceState,
    starting_order: list[Runner],
    constants: Constants,
    rollout_depth: Optional[int] = None,
) -> RaceState:
    """Play out the race from the current state with a given runner order.

    Returns the resulting state with all planned assignments appended.
    """
    state = _clone_state(base_state)
    state.runners_in_order = list(starting_order)
    for r in starting_order:
        state.pace_multiplier.setdefault(r.name, 1.0)

    now, cycle = _current_time_after_history(state, constants)
    handover = timedelta(seconds=constants.HANDOVER_OVERHEAD_SEC)
    depth = constants.ROLLOUT_DEPTH if rollout_depth is None else rollout_depth

    while True:
        if now > constants.CUTOFF_TIME:
            break
        pick = _pick_best_course(state, now, cycle, constants, depth)
        if pick is None:
            break
        course, mean, sigma = pick
        runner = state.runner_for_cycle(cycle)
        state.assignments.append(
            Assignment(
                cycle=cycle,
                runner=runner,
                course=course,
                planned_start=now,
                planned_duration_min=mean,
                planned_sigma_min=sigma,
                status="planned",
            )
        )
        state.completed_codes.add(course.code)
        now = now + timedelta(minutes=mean) + handover
        cycle += 1

    return state


def _starter_heuristic_score(runner: Runner) -> float:
    # Higher = better starter. Mix K and T with K dominant (SF rewards speed in a crowd).
    return runner.K * 1.5 + runner.T


def plan(
    base_state: RaceState,
    all_runners: list[Runner],
    constants: Constants,
) -> RaceState:
    """Pre-race plan. Search over starting orders.

    Strategy: enumerate all 720 permutations but only run a full rollout simulation
    for the top STARTING_ORDER_PRUNE_TOP_N as ranked by a cheap "shallow" simulate
    (rollout_depth=0). This keeps plan() under ~10 s on a laptop while still
    exploring the search space broadly.
    """
    perms = list(itertools.permutations(all_runners))

    # Phase 1: cheap shallow simulation for every permutation.
    shallow_results: list[tuple[int, float, tuple[Runner, ...]]] = []
    for order in perms:
        out = simulate(base_state, list(order), constants, rollout_depth=0)
        count = sum(1 for a in out.assignments if a.status == "planned")
        finish_min = (
            (out.assignments[-1].planned_finish - constants.RACE_START).total_seconds() / 60.0
            if out.assignments else 0.0
        )
        shallow_results.append((count, finish_min, order))

    # Rank: most courses, then earliest finish.
    shallow_results.sort(key=lambda r: (-r[0], r[1]))
    top_n = shallow_results[: max(1, constants.STARTING_ORDER_PRUNE_TOP_N)]

    # Phase 2: full-depth rollout for top candidates.
    best_state: Optional[RaceState] = None
    best_metric: tuple[int, float] = (-1, float("inf"))
    for _, _, order in top_n:
        out = simulate(base_state, list(order), constants)
        count = sum(1 for a in out.assignments if a.status == "planned")
        finish_min = (
            (out.assignments[-1].planned_finish - constants.RACE_START).total_seconds() / 60.0
            if out.assignments else 0.0
        )
        metric = (count, finish_min)
        if (metric[0], -metric[1]) > (best_metric[0], -best_metric[1]):
            best_metric = metric
            best_state = out

    assert best_state is not None
    return best_state


def replan(state_with_history: RaceState, constants: Constants) -> RaceState:
    """Replan from the current state. Runner order is already locked.

    Drops any previously-planned (not done) assignments and rebuilds the tail.
    """
    state = _clone_state(state_with_history)
    state.assignments = [a for a in state.assignments if a.status in ("done", "in_progress")]
    # Re-derive completed_codes from history to be safe.
    state.completed_codes = {a.course.code for a in state.assignments if a.status == "done"}
    return simulate(state, state.runners_in_order, constants)
