from __future__ import annotations

from .models import Constants, Course, Runner


NIGHT_TYPES = {"EN", "HN"}


def course_T(course: Course, constants: Constants) -> int:
    return constants.COURSE_T_BY_TYPE[course.type]


def flat_equivalent_km(course: Course, constants: Constants) -> float:
    return course.length_km + course.climb_m / constants.CLIMB_M_PER_FLAT_KM


def base_pace(runner: Runner, constants: Constants, multiplier: float = 1.0) -> float:
    return (
        constants.K6_PACE_MIN_PER_KM
        * (1 + constants.K_STEP_PCT * (6 - runner.K))
        * multiplier
    )


def predict_time(
    runner: Runner,
    course: Course,
    constants: Constants,
    pace_multiplier: float = 1.0,
) -> tuple[float, float]:
    """Return (mean_minutes, sigma_minutes) for runner on course."""
    pace = base_pace(runner, constants, pace_multiplier)
    nav = 1 + constants.T_GAP_PCT * max(0.0, course_T(course, constants) - runner.T)
    night = 1 + constants.NIGHT_PCT if course.type in NIGHT_TYPES else 1.0
    mean = pace * flat_equivalent_km(course, constants) * nav * night
    sigma = constants.SIGMA_PCT * mean
    return mean, sigma
