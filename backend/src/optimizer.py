from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

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


# Phase-restricted singleton course types — they appear once in the pool and
# their phase position is dictated by the rules, not by free choice. Counting
# them in a constrained runner's "allowed remaining" overstates that runner's
# real options (FF only unlocks at the very end; SF only fires at cycle 1).
_PHASE_SINGLETON_TYPES = frozenset({"SF", "FF"})


def _reserved_for_constrained_teammates(
    state: RaceState,
    current_runner: Runner,
    current_cycle: int,
    legal: list[Course],
    now: datetime,
    constants: Constants,
) -> set[str]:
    """Courses ``current_runner`` should yield to tighter teammates.

    The score formula's ``÷ time`` term makes fast runners systematically
    prefer short courses at their own cycle — exactly the courses a runner
    with tight forbid lists (e.g. Alicia: H/HN/long-E/long-EN blocked) needs.
    The bounded rollout depth can't see the eventual halt 20 cycles ahead, so
    by the time the constrained runner's cycle comes around, all of her short
    options have been swept by faster teammates and the simulator stops.

    This helper closes that long-horizon externality. For each teammate R:

      * ``r_allowed`` = R's allowed courses *intersected with the currently
        legal pool*. Counting R's full cross-phase allowed set inflates
        slack — e.g. Alicia at cycle 8 has 3 short-E options legal *right
        now* but 9 if you also count her ST/LT/EN options that won't unlock
        until twilight/night. The immediate-phase number is what governs
        whether other runners can safely take from her pool today; her
        night allowance is irrelevant to a day-phase decision.
      * ``r_remaining`` = how many of R's cyclic slots fall in the
        remaining-cycles window, bounded structurally by ``len(course_pool)``
        (no course repeats, rule §3).
      * ``r_slack = r_allowed - r_remaining``.

    A teammate R is *tight* when ``r_slack <= 1`` — at most one spare beyond
    what they need. The current runner yields R's allowed pool **only when
    R is strictly tighter than the current runner** (``my_slack > r_slack``),
    so a tight caller never starves itself for an even tighter teammate.

    The reservation is advisory: ``_candidate_scores`` retries without it if
    every candidate ends up filtered out, so we never halt the race over a
    soft constraint.
    """
    if not state.runners_in_order:
        return set()

    n_runners = len(state.runners_in_order)

    if (constants.CUTOFF_TIME - now).total_seconds() <= 0:
        return set()

    # Structural bound on remaining cycles: no course repeats (rule §3) caps
    # the entire race at ``len(course_pool)`` cycles. Estimating from avg
    # past duration (the obvious approach) blew up in the few-fast-legs
    # replan case — six TH+SF legs at 0.7× pace extrapolated to ~67 cycles
    # of slack, inflated per-runner remaining counts, drove every constrained
    # teammate's slack negative, and over-reserved. The structural bound
    # decouples reservation from short-term pace noise.
    team_remaining_cycles = max(0, len(state.course_pool) - (current_cycle - 1))
    if team_remaining_cycles <= 0:
        return set()

    # Per-runner status snapshot.
    status: dict[str, tuple[int, int, frozenset[str]]] = {}
    for idx, r in enumerate(state.runners_in_order):
        r_remaining = sum(
            1
            for k in range(current_cycle, current_cycle + team_remaining_cycles)
            if (k - 1) % n_runners == idx
        )
        # Intersect with the currently legal pool — phase-relevance matters.
        # ``legal`` already excludes courses outside the current phase, done
        # courses, and forbidden-by-phase-machine entries.
        r_allowed = frozenset(
            c.code
            for c in legal
            if c.code not in r.forbid_courses
            and c.type not in r.forbid_types
            and c.type not in _PHASE_SINGLETON_TYPES
        )
        status[r.name] = (len(r_allowed), r_remaining, r_allowed)

    my_allowed_count, my_remaining, _ = status[current_runner.name]
    my_slack = my_allowed_count - my_remaining

    reserved: set[str] = set()
    for r in state.runners_in_order:
        if r.name == current_runner.name:
            continue
        r_allowed_count, r_remaining, r_allowed_codes = status[r.name]
        r_slack = r_allowed_count - r_remaining
        if r_slack <= 1 and my_slack > r_slack:
            reserved |= r_allowed_codes
    return reserved


def _candidate_scores(
    state: RaceState,
    runner: Runner,
    legal: list[Course],
    now: datetime,
    constants: Constants,
    current_cycle: int,
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

    # Reservation: courses to yield to tighter teammates (extensions.md §4).
    # First pass tries with reservation; if it filters out everything, fall
    # back to a pass without reservation so we never halt over a soft hint.
    reserved_initial = _reserved_for_constrained_teammates(
        state, runner, current_cycle, legal, now, constants
    )
    passes = [reserved_initial, set()] if reserved_initial else [set()]

    safe: list[tuple[float, Course, float, float]] = []
    unsafe_day: list[tuple[float, Course, float, float]] = []
    for reserved in passes:
        safe = []
        unsafe_day = []
        for course in legal:
            # Per-runner hard blocks the time model can't express (coach knowledge:
            # injury, navigation fear, distance limit). Stacks on top of the phase
            # machine and the cutoff filter — three independent filters, each
            # surgically scoped. See extensions.md §4.
            if course.code in runner.forbid_courses or course.type in runner.forbid_types:
                continue
            # Soft reservation for tighter constrained teammates. Skipped on
            # the fallback pass (when reserved == set()).
            if course.code in reserved:
                continue
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
        if safe or unsafe_day:
            break

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
        cands = _candidate_scores(state, runner, legal, now, constants, cycle)
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
    candidates = _candidate_scores(state, runner, legal, now, constants, cycle)
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
        candidates = _candidate_scores(local_state, runner, legal, local_now, constants, local_cycle)
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


def plan(
    base_state: RaceState,
    all_runners: list[Runner],
    constants: Constants,
) -> RaceState:
    """Pre-race plan. The cyclic dispatch order is fixed by ``all_runners``
    (i.e. the order in ``team.yaml``) — rule §4 locks the rotation pre-race,
    so we no longer search over starting-order permutations. ``simulate`` is
    called once with the given order and the full rollout depth.
    """
    return simulate(base_state, all_runners, constants)


def replan(state_with_history: RaceState, constants: Constants) -> RaceState:
    """Replan from the current state. Runner order is already locked.

    Drops any previously-planned (not done) assignments and rebuilds the tail.
    """
    state = _clone_state(state_with_history)
    state.assignments = [a for a in state.assignments if a.status in ("done", "in_progress")]
    # Re-derive completed_codes from history to be safe.
    state.completed_codes = {a.course.code for a in state.assignments if a.status == "done"}
    return simulate(state, state.runners_in_order, constants)
