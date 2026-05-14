from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import Course, RaceState

NIGHT_TYPES = {"EN", "HN"}
TWILIGHT_TYPES = {"ST", "LT"}
DAY_TYPES = {"SF", "TH", "E", "H"}


def legal_next_courses(
    state: RaceState,
    now: datetime,
    twilight: datetime,
    day_resume: Optional[datetime] = None,
    twilight_early_unlock_min: Optional[float] = None,
) -> list[Course]:
    """Courses that the next runner is allowed to choose from right now.

    The mandatory phase ordering is encoded as a series of overriding clauses
    in priority order. The first clause that fires defines the legal set.

    Day-type courses (SF/TH/E/H) are excluded once ``now`` reaches
    ``twilight`` (the Wechselzeitpunkt of rule §5.3.4) and stay excluded
    until ``day_resume`` (next morning's daylight). Even when rule §5.3.5
    technically re-opens day maps after ST/LT are completed, day maps have
    no reflectors and are unreadable in the dark — so we keep them locked
    for the entire dark stretch ``[twilight, day_resume)``. A finer
    per-course finish-time safety check stacks on top in the optimiser.

    If ``twilight_early_unlock_min`` is provided and the next dispatch is
    within that many minutes of ``twilight``, ST/LT are surfaced into the
    legal pool alongside day courses so the optimiser can switch early rather
    than be forced into a day course that would finish in darkness.
    """
    done = state.completed_codes
    pool = state.course_pool

    # Cycle 1: SF is mandatory and the only legal choice.
    if "SF" not in done:
        return [pool["SF"]]

    # After SF: all 5 TH must be run before anything else.
    th_remaining = [c for c in pool.values() if c.type == "TH" and c.code not in done]
    if th_remaining:
        return th_remaining

    # At/after twilight OR once every E and H is done, ST+LT become mandatory
    # before any other non-twilight course. Rule §5.3.4 verbatim: "Hat ein
    # Team vor diesem Zeitpunkt alle Tagbahnen absolviert, wechselt dieses
    # Team entsprechend früher auf die Dämmerungsbahnen."
    twilight_remaining = [
        pool[code] for code in ("ST", "LT") if code not in done
    ]
    all_day_done = all(
        c.code in done for c in pool.values() if c.type in ("E", "H")
    )
    if twilight_remaining and (now >= twilight or all_day_done):
        return twilight_remaining

    in_dark_window = (
        day_resume is not None
        and twilight <= now < day_resume
    )

    pre_twilight = now < twilight
    early_unlock = (
        pre_twilight
        and twilight_early_unlock_min is not None
        and (twilight - now).total_seconds() / 60.0 <= twilight_early_unlock_min
    )

    # Free-choice pool: everything except FF, EN/HN (locked until after twilight
    # + ST + LT), and ST/LT before twilight (unless inside the early-unlock
    # window, in which case ST/LT may be picked early to avoid spilling a day
    # course into darkness).
    free = []
    for c in pool.values():
        if c.code in done or c.code == "FF":
            continue
        if c.type in NIGHT_TYPES and twilight_remaining:
            # Rule §5.3.5: "Nachtbahnen … erst gelaufen werden, nachdem das
            # Team beide Dämmerungsbahnen absolviert hat." The gate is ST+LT
            # being done, not the wall clock — a team that finishes both
            # twilight courses while it's technically still daylight may
            # legally start night courses.
            continue
        if c.type in TWILIGHT_TYPES and pre_twilight and not early_unlock:
            # ST/LT are normally twilight-locked. Inside the early-unlock window
            # they can be picked early.
            continue
        if c.type in DAY_TYPES and in_dark_window:
            # Day maps are off-limits between TWILIGHT_TIME (rule-mandated
            # switch to Dämmerungsbahnen) and DAY_RESUME (next daylight),
            # regardless of whether ST/LT are already done — they have no
            # reflectors and would be unreadable in fading/dark light.
            continue
        free.append(c)
    if free:
        return free

    # Only FF left.
    if "FF" not in done:
        return [pool["FF"]]

    return []
