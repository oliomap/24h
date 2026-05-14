from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import yaml
from dateutil import parser as dtparse

from .calibration import update_multiplier
from .models import Assignment, Constants, Course, RaceState, Runner

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
SCHEDULE_CSV = DATA_DIR / "schedule.csv"

CSV_HEADER = [
    "cycle",
    "runner_name",
    "course_code",
    "planned_start",
    "planned_duration_min",
    "planned_sigma_min",
    "actual_start",
    "actual_duration_min",
    "status",
]


def load_constants(path: Optional[Path] = None) -> Constants:
    path = path or (CONFIG_DIR / "constants.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    return Constants(
        K6_PACE_MIN_PER_KM=float(data["K6_PACE_MIN_PER_KM"]),
        K_STEP_PCT=float(data["K_STEP_PCT"]),
        T_GAP_PCT=float(data["T_GAP_PCT"]),
        NIGHT_PCT=float(data["NIGHT_PCT"]),
        SIGMA_PCT=float(data["SIGMA_PCT"]),
        HANDOVER_OVERHEAD_SEC=int(data["HANDOVER_OVERHEAD_SEC"]),
        CLIMB_M_PER_FLAT_KM=float(data["CLIMB_M_PER_FLAT_KM"]),
        RACE_START=dtparse.isoparse(data["RACE_START"]),
        TWILIGHT_TIME=dtparse.isoparse(data["TWILIGHT_TIME"]),
        CUTOFF_TIME=dtparse.isoparse(data["CUTOFF_TIME"]),
        DAY_RESUME=dtparse.isoparse(data["DAY_RESUME"]),
        DAY_SAFETY_SIGMA=float(data["DAY_SAFETY_SIGMA"]),
        SAFETY_SIGMA_THRESHOLD=float(data["SAFETY_SIGMA_THRESHOLD"]),
        ROLLOUT_TOP_K=int(data["ROLLOUT_TOP_K"]),
        ROLLOUT_DEPTH=int(data["ROLLOUT_DEPTH"]),
        STARTING_ORDER_PRUNE_TOP_N=int(data["STARTING_ORDER_PRUNE_TOP_N"]),
        CALIBRATION_ALPHA=float(data["CALIBRATION_ALPHA"]),
        COURSE_T_BY_TYPE=dict(data["COURSE_T_BY_TYPE"]),
        PACE_MULTIPLIER_MIN=float(data.get("PACE_MULTIPLIER_MIN", 0.4)),
        PACE_MULTIPLIER_MAX=float(data.get("PACE_MULTIPLIER_MAX", 2.5)),
        TWILIGHT_EARLY_UNLOCK_MIN=float(data.get("TWILIGHT_EARLY_UNLOCK_MIN", 30.0)),
        DAY_DISPATCH_BUFFER_MIN=float(data.get("DAY_DISPATCH_BUFFER_MIN", 10.0)),
    )


def load_courses(path: Optional[Path] = None) -> dict[str, Course]:
    path = path or (CONFIG_DIR / "courses.yaml")
    with open(path) as f:
        rows = yaml.safe_load(f)
    pool: dict[str, Course] = {}
    for row in rows:
        c = Course(
            code=row["code"],
            type=row["type"],
            length_km=float(row["length_km"]),
            climb_m=int(row["climb_m"]),
            controls=int(row["controls"]),
        )
        pool[c.code] = c
    return pool


def load_team(path: Optional[Path] = None) -> list[Runner]:
    path = path or (CONFIG_DIR / "team.yaml")
    with open(path) as f:
        rows = yaml.safe_load(f)
    return [Runner(name=r["name"], T=float(r["T"]), K=float(r["K"])) for r in rows]


def empty_state(courses: dict[str, Course], team: list[Runner]) -> RaceState:
    return RaceState(
        runners_in_order=[],
        assignments=[],
        course_pool=courses,
        completed_codes=set(),
        pace_multiplier={r.name: 1.0 for r in team},
    )


def _parse_optional_datetime(s: str) -> Optional[datetime]:
    return dtparse.isoparse(s) if s else None


def _parse_optional_float(s: str) -> Optional[float]:
    return float(s) if s else None


def load_state(
    courses: dict[str, Course],
    team: list[Runner],
    constants: Constants,
    path: Optional[Path] = None,
) -> RaceState:
    """Reconstruct a RaceState from schedule.csv. pace_multiplier is rebuilt
    by replaying calibration on done legs in cycle order.
    """
    path = path or SCHEDULE_CSV
    if not path.exists():
        return empty_state(courses, team)

    runners_by_name = {r.name: r for r in team}
    state = empty_state(courses, team)

    with open(path) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    rows.sort(key=lambda r: int(r["cycle"]))

    # First pass: figure out the cyclic order from cycles 1..6.
    order_slots: dict[int, Runner] = {}
    for r in rows:
        cycle = int(r["cycle"])
        if 1 <= cycle <= 6:
            order_slots[cycle] = runners_by_name[r["runner_name"]]
    if len(order_slots) == 6:
        state.runners_in_order = [order_slots[i] for i in range(1, 7)]

    # Second pass: build assignments and recompute pace_multiplier from done legs.
    pace_mult = {r.name: 1.0 for r in team}
    for r in rows:
        runner = runners_by_name[r["runner_name"]]
        course = courses[r["course_code"]]
        actual_start = _parse_optional_datetime(r["actual_start"])
        actual_dur = _parse_optional_float(r["actual_duration_min"])
        status = r["status"]
        assignment = Assignment(
            cycle=int(r["cycle"]),
            runner=runner,
            course=course,
            planned_start=dtparse.isoparse(r["planned_start"]),
            planned_duration_min=float(r["planned_duration_min"]),
            planned_sigma_min=float(r["planned_sigma_min"]),
            actual_start=actual_start,
            actual_duration_min=actual_dur,
            status=status,
        )
        state.assignments.append(assignment)
        if status == "done":
            state.completed_codes.add(course.code)
            if actual_dur is not None:
                pace_mult[runner.name] = update_multiplier(
                    runner, course, actual_dur, pace_mult[runner.name], constants
                )

    state.pace_multiplier = pace_mult
    return state


def save_state(state: RaceState, path: Optional[Path] = None) -> None:
    path = path or SCHEDULE_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".schedule_", suffix=".csv", dir=str(path.parent))
    os.close(fd)
    try:
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADER)
            w.writeheader()
            for a in sorted(state.assignments, key=lambda x: x.cycle):
                w.writerow(
                    {
                        "cycle": a.cycle,
                        "runner_name": a.runner.name,
                        "course_code": a.course.code,
                        "planned_start": a.planned_start.isoformat(),
                        "planned_duration_min": f"{a.planned_duration_min:.2f}",
                        "planned_sigma_min": f"{a.planned_sigma_min:.2f}",
                        "actual_start": a.actual_start.isoformat() if a.actual_start else "",
                        "actual_duration_min": (
                            f"{a.actual_duration_min:.2f}" if a.actual_duration_min is not None else ""
                        ),
                        "status": a.status,
                    }
                )
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
