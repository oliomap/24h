from __future__ import annotations

from .models import Constants, Course, Runner
from .time_model import predict_time


def update_multiplier(
    runner: Runner,
    course: Course,
    actual_minutes: float,
    current_multiplier: float,
    constants: Constants,
) -> float:
    """Blend a new observation into the runner's pace multiplier.

    The "clean" prediction is what we would have predicted with multiplier=1.0,
    so the ratio actual / clean is the multiplier implied by this single run.
    We then blend it with the previous multiplier using CALIBRATION_ALPHA.

    Both the per-observation ratio and the final blended multiplier are
    clamped to ``[MULTIPLIER_MIN, MULTIPLIER_MAX]``. Without this clamp, a
    single outlier (lost runner gone for 4 hours, or a typo entering ``1000``
    instead of ``10``) drives the multiplier to absurd values, after which
    every future prediction for that runner overshoots the cutoff and the
    re-planner returns no further legs — exactly the failure mode that
    motivated this clamp.
    """
    clean_mean, _ = predict_time(runner, course, constants, pace_multiplier=1.0)
    if clean_mean <= 0:
        return current_multiplier
    lo, hi = constants.PACE_MULTIPLIER_MIN, constants.PACE_MULTIPLIER_MAX
    observation = max(lo, min(hi, actual_minutes / clean_mean))
    alpha = constants.CALIBRATION_ALPHA
    blended = alpha * observation + (1 - alpha) * current_multiplier
    return max(lo, min(hi, blended))
