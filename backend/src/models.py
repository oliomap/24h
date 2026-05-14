from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Runner:
    name: str
    T: float
    K: float


@dataclass(frozen=True)
class Course:
    code: str
    type: str
    length_km: float
    climb_m: int
    controls: int


@dataclass
class Constants:
    K6_PACE_MIN_PER_KM: float
    K_STEP_PCT: float
    T_GAP_PCT: float
    NIGHT_PCT: float
    SIGMA_PCT: float
    HANDOVER_OVERHEAD_SEC: int
    CLIMB_M_PER_FLAT_KM: float
    RACE_START: datetime
    TWILIGHT_TIME: datetime
    CUTOFF_TIME: datetime
    DAY_RESUME: datetime
    DAY_SAFETY_SIGMA: float
    SAFETY_SIGMA_THRESHOLD: float
    ROLLOUT_TOP_K: int
    ROLLOUT_DEPTH: int
    STARTING_ORDER_PRUNE_TOP_N: int
    CALIBRATION_ALPHA: float
    COURSE_T_BY_TYPE: dict[str, int]
    # Safety bounds for the per-runner pace multiplier. A single outlier
    # observation (lost runner, mid-leg DNF, typo entering "100" instead of
    # "10") would otherwise push the multiplier far out of plausible range and
    # disable the runner's future legs. Both the per-observation ratio and the
    # blended multiplier are clamped to [PACE_MULTIPLIER_MIN, PACE_MULTIPLIER_MAX].
    PACE_MULTIPLIER_MIN: float = 0.4
    PACE_MULTIPLIER_MAX: float = 2.5
    # If the next dispatch is within this many minutes of TWILIGHT_TIME, the
    # legal pool surfaces ST/LT alongside day courses so the optimiser can
    # switch early rather than be forced into a day course that finishes dark.
    TWILIGHT_EARLY_UNLOCK_MIN: float = 30.0
    # Morning-side mirror of the above: a day map is only legal once `now`
    # has crossed DAY_RESUME by this many minutes. Absorbs the case where the
    # previous leg's actual_finish runs faster than mean and would otherwise
    # drag a day-course dispatch back into pre-sunrise twilight.
    DAY_DISPATCH_BUFFER_MIN: float = 10.0


@dataclass
class Assignment:
    cycle: int
    runner: Runner
    course: Course
    planned_start: datetime
    planned_duration_min: float
    planned_sigma_min: float
    actual_start: Optional[datetime] = None
    actual_duration_min: Optional[float] = None
    status: str = "planned"   # planned | in_progress | done | skipped

    @property
    def planned_finish(self) -> datetime:
        from datetime import timedelta
        return self.planned_start + timedelta(minutes=self.planned_duration_min)

    @property
    def actual_finish(self) -> Optional[datetime]:
        from datetime import timedelta
        if self.actual_start is None or self.actual_duration_min is None:
            return None
        return self.actual_start + timedelta(minutes=self.actual_duration_min)


@dataclass
class RaceState:
    runners_in_order: list[Runner]
    assignments: list[Assignment]
    course_pool: dict[str, Course]
    completed_codes: set[str]
    pace_multiplier: dict[str, float] = field(default_factory=dict)

    def runner_for_cycle(self, cycle: int) -> Runner:
        # cycles are 1-indexed; cycle 1 -> runners_in_order[0]
        return self.runners_in_order[(cycle - 1) % len(self.runners_in_order)]

    def completed_count(self) -> int:
        return sum(1 for a in self.assignments if a.status == "done")

    def last_finish(self) -> Optional[datetime]:
        finishes = [a.actual_finish or a.planned_finish for a in self.assignments]
        return max(finishes) if finishes else None
