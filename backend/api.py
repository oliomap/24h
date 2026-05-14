"""FastAPI shim over the optimiser.

Endpoints:
  GET  /api/schedule  — current schedule + derived UI state
  POST /api/plan      — build a fresh pre-race plan (refuses if any leg done; pass {"force": true} to override)
  POST /api/finish    — body: {"runner_name": str, "actual_minutes": float}; records + re-plans
  POST /api/reset     — wipe schedule.csv

The frontend talks to localhost:8000. Run with:
  uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.calibration import update_multiplier
from src.models import Assignment, RaceState
from src.optimizer import plan as plan_fn
from src.optimizer import replan as replan_fn
from src.state import (
    SCHEDULE_CSV,
    empty_state,
    load_constants,
    load_courses,
    load_state,
    load_team,
    save_state,
)


app = FastAPI(title="24h-OL Optimiser API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ApiAssignment(BaseModel):
    cycle: int
    runner_name: str
    course_code: str
    course_type: str
    planned_start: datetime
    planned_duration_min: float
    planned_sigma_min: float
    planned_finish: datetime
    actual_start: Optional[datetime] = None
    actual_duration_min: Optional[float] = None
    actual_finish: Optional[datetime] = None
    status: str


class ApiNextUp(BaseModel):
    runner_name: str
    course_code: str
    course_type: str
    planned_start: datetime
    planned_duration_min: float
    cycle: int


class ApiSchedule(BaseModel):
    assignments: list[ApiAssignment]
    next_up: Optional[ApiNextUp]
    projected_count: int
    done_count: int
    in_progress_count: int
    total_courses: int
    race_start: datetime
    cutoff: datetime
    twilight: datetime
    last_finish: Optional[datetime]
    slack_min: Optional[float]
    pace_multipliers: dict[str, float]
    has_plan: bool


class FinishRequest(BaseModel):
    runner_name: str
    actual_minutes: float


class PlanRequest(BaseModel):
    force: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_api_assignment(a: Assignment) -> ApiAssignment:
    return ApiAssignment(
        cycle=a.cycle,
        runner_name=a.runner.name,
        course_code=a.course.code,
        course_type=a.course.type,
        planned_start=a.planned_start,
        planned_duration_min=round(a.planned_duration_min, 2),
        planned_sigma_min=round(a.planned_sigma_min, 2),
        planned_finish=a.planned_finish,
        actual_start=a.actual_start,
        actual_duration_min=a.actual_duration_min,
        actual_finish=a.actual_finish,
        status=a.status,
    )


def _next_pending(state: RaceState) -> Optional[Assignment]:
    for a in sorted(state.assignments, key=lambda x: x.cycle):
        if a.status != "done":
            return a
    return None


def _build_schedule_response(state: RaceState, constants) -> ApiSchedule:
    assignments = [_to_api_assignment(a) for a in sorted(state.assignments, key=lambda x: x.cycle)]
    pending = _next_pending(state)
    next_up = None
    if pending is not None:
        next_up = ApiNextUp(
            runner_name=pending.runner.name,
            course_code=pending.course.code,
            course_type=pending.course.type,
            planned_start=pending.planned_start,
            planned_duration_min=round(pending.planned_duration_min, 2),
            cycle=pending.cycle,
        )
    done_count = sum(1 for a in state.assignments if a.status == "done")
    in_progress = sum(1 for a in state.assignments if a.status == "in_progress")
    projected = len(state.assignments)
    last_finish = None
    if state.assignments:
        last_finish = max(
            (a.actual_finish or a.planned_finish) for a in state.assignments
        )
    slack_min = (
        (constants.CUTOFF_TIME - last_finish).total_seconds() / 60.0
        if last_finish
        else None
    )
    return ApiSchedule(
        assignments=assignments,
        next_up=next_up,
        projected_count=projected,
        done_count=done_count,
        in_progress_count=in_progress,
        total_courses=len(state.course_pool),
        race_start=constants.RACE_START,
        cutoff=constants.CUTOFF_TIME,
        twilight=constants.TWILIGHT_TIME,
        last_finish=last_finish,
        slack_min=slack_min,
        pace_multipliers=state.pace_multiplier,
        has_plan=bool(state.assignments),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/schedule", response_model=ApiSchedule)
def get_schedule():
    constants = load_constants()
    courses = load_courses()
    team = load_team()
    state = load_state(courses, team, constants)
    return _build_schedule_response(state, constants)


@app.post("/api/plan", response_model=ApiSchedule)
def post_plan(req: PlanRequest = PlanRequest()):
    constants = load_constants()
    courses = load_courses()
    team = load_team()

    if SCHEDULE_CSV.exists() and not req.force:
        existing = load_state(courses, team, constants)
        if any(a.status == "done" for a in existing.assignments):
            raise HTTPException(
                status_code=409,
                detail=(
                    "schedule already has finished legs; pass force=true to overwrite"
                ),
            )

    base = empty_state(courses, team)
    out = plan_fn(base, team, constants)
    save_state(out, SCHEDULE_CSV)
    return _build_schedule_response(out, constants)


@app.post("/api/finish", response_model=ApiSchedule)
def post_finish(req: FinishRequest):
    constants = load_constants()
    courses = load_courses()
    team = load_team()
    state = load_state(courses, team, constants)

    if not state.assignments:
        raise HTTPException(status_code=400, detail="no plan exists; POST /api/plan first")

    pending = _next_pending(state)
    if pending is None:
        raise HTTPException(status_code=400, detail="all legs already done")

    if pending.runner.name != req.runner_name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"next leg is cycle {pending.cycle} for {pending.runner.name}, "
                f"not {req.runner_name}"
            ),
        )

    # Stamp actual + recalibrate.
    prev = next(
        (a for a in state.assignments if a.cycle == pending.cycle - 1), None
    )
    pending.actual_start = (
        (prev.actual_finish or prev.planned_finish) if prev is not None else constants.RACE_START
    )
    pending.actual_duration_min = req.actual_minutes
    pending.status = "done"
    state.pace_multiplier[pending.runner.name] = update_multiplier(
        pending.runner,
        pending.course,
        req.actual_minutes,
        state.pace_multiplier.get(pending.runner.name, 1.0),
        constants,
    )

    rep = replan_fn(state, constants)
    save_state(rep, SCHEDULE_CSV)
    return _build_schedule_response(rep, constants)


@app.post("/api/reset")
def post_reset():
    if SCHEDULE_CSV.exists():
        SCHEDULE_CSV.unlink()
    return {"ok": True}
