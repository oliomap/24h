from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .calibration import update_multiplier
from .models import Assignment, Constants, RaceState, Runner
from .optimizer import plan as plan_fn
from .optimizer import replan as replan_fn
from .state import (
    SCHEDULE_CSV,
    empty_state,
    load_constants,
    load_courses,
    load_state,
    load_team,
    save_state,
)

try:
    from rich.console import Console
    from rich.table import Table

    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False


def _format_time(dt: datetime, race_start: datetime) -> str:
    """HH:MM, with a leading day marker if it's the Sunday side of the race."""
    if dt.date() == race_start.date():
        return dt.strftime("%H:%M")
    return dt.strftime("Su %H:%M")


def _print_schedule(state: RaceState, constants: Constants, header: str = "") -> None:
    if header:
        print(header)
    done = state.completed_count()
    planned = sum(1 for a in state.assignments if a.status == "planned")
    in_prog = sum(1 for a in state.assignments if a.status == "in_progress")
    total = len(state.assignments)
    if _RICH:
        console = Console()
        table = Table(show_lines=False, header_style="bold")
        for col in ("#", "Runner", "Course", "Type", "Start", "Dur", "Finish", "Actual", "Status", "Done"):
            table.add_column(col)
        cum = 0
        for a in sorted(state.assignments, key=lambda x: x.cycle):
            cum_label = ""
            if a.status == "done":
                cum += 1
                cum_label = str(cum)
            actual = (
                f"{a.actual_duration_min:.1f}" if a.actual_duration_min is not None else "-"
            )
            table.add_row(
                str(a.cycle),
                a.runner.name,
                a.course.code,
                a.course.type,
                _format_time(a.planned_start, constants.RACE_START),
                f"{a.planned_duration_min:.0f}",
                _format_time(a.planned_finish, constants.RACE_START),
                actual,
                a.status,
                cum_label,
            )
        console.print(table)
    else:
        # Plain text fallback.
        cols = ("Cycle", "Runner", "Course", "Type", "Start", "Dur", "Finish", "Actual", "Status")
        print("  ".join(f"{c:<9}" for c in cols))
        cum = 0
        for a in sorted(state.assignments, key=lambda x: x.cycle):
            actual = (
                f"{a.actual_duration_min:.1f}" if a.actual_duration_min is not None else "-"
            )
            print(
                "  ".join(
                    f"{v:<9}"
                    for v in (
                        a.cycle,
                        a.runner.name,
                        a.course.code,
                        a.course.type,
                        _format_time(a.planned_start, constants.RACE_START),
                        f"{a.planned_duration_min:.0f}",
                        _format_time(a.planned_finish, constants.RACE_START),
                        actual,
                        a.status,
                    )
                )
            )
    print(
        f"\nProjected courses: {total}   (done: {done}, in progress: {in_prog}, planned: {planned})"
    )
    if state.assignments:
        last_finish = max(
            (a.actual_finish or a.planned_finish) for a in state.assignments
        )
        slack = (constants.CUTOFF_TIME - last_finish).total_seconds() / 60.0
        print(
            f"Last leg finishes {_format_time(last_finish, constants.RACE_START)}  "
            f"(slack to cutoff: {slack:+.0f} min)"
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_plan(argv: list[str]) -> int:
    force = "--force" in argv
    constants = load_constants()
    courses = load_courses()
    team = load_team()

    if SCHEDULE_CSV.exists() and not force:
        existing = load_state(courses, team, constants)
        if any(a.status == "done" for a in existing.assignments):
            print(
                f"refusing to overwrite {SCHEDULE_CSV}: it has done legs. "
                "Use `python main.py finish` to record actuals, or `--force` to start over."
            )
            return 2

    base = empty_state(courses, team)
    print(
        f"Planning {len(courses)} courses for {len(team)} runners "
        f"(cyclic order: {', '.join(r.name for r in team)})…"
    )
    out = plan_fn(base, team, constants)
    save_state(out, SCHEDULE_CSV)
    _print_schedule(out, constants, header="\n=== Pre-race plan ===")
    print(f"\nSaved to {SCHEDULE_CSV}")
    return 0


def _next_pending_assignment(state: RaceState) -> Optional[Assignment]:
    """First assignment by cycle that is not done. May be 'in_progress' or 'planned'."""
    for a in sorted(state.assignments, key=lambda x: x.cycle):
        if a.status != "done":
            return a
    return None


def _previous_finish(state: RaceState, cycle: int, constants: Constants) -> datetime:
    if cycle <= 1:
        return constants.RACE_START
    prev = next(
        (a for a in state.assignments if a.cycle == cycle - 1), None
    )
    if prev is None:
        return constants.RACE_START
    return prev.actual_finish or prev.planned_finish


def cmd_finish(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python main.py finish <runner_name> <actual_minutes>")
        return 2
    runner_name = argv[0]
    try:
        actual_minutes = float(argv[1])
    except ValueError:
        print(f"actual_minutes must be a number, got {argv[1]!r}")
        return 2

    constants = load_constants()
    courses = load_courses()
    team = load_team()
    state = load_state(courses, team, constants)

    if not state.assignments:
        print("no schedule found. Run `python main.py plan` first.")
        return 2

    pending = _next_pending_assignment(state)
    if pending is None:
        print("all legs already done. Nothing to record.")
        return 0

    if pending.runner.name != runner_name:
        print(
            f"next leg is cycle {pending.cycle} for {pending.runner.name}, "
            f"not {runner_name}. Use `python main.py show` to inspect."
        )
        return 2

    # Stamp the actual.
    pending.actual_start = _previous_finish(state, pending.cycle, constants)
    pending.actual_duration_min = actual_minutes
    pending.status = "done"

    # Recalibrate this runner's pace multiplier.
    current_mult = state.pace_multiplier.get(pending.runner.name, 1.0)
    new_mult = update_multiplier(
        pending.runner, pending.course, actual_minutes, current_mult, constants
    )
    state.pace_multiplier[pending.runner.name] = new_mult

    # Replan from here.
    rep = replan_fn(state, constants)
    save_state(rep, SCHEDULE_CSV)

    mult_delta = (new_mult - current_mult) * 100
    print(
        f"Recorded: {pending.runner.name} ran {pending.course.code} in "
        f"{actual_minutes:.1f} min (predicted {pending.planned_duration_min:.1f})"
    )
    print(
        f"  pace multiplier for {pending.runner.name}: "
        f"{current_mult:.2f} → {new_mult:.2f} ({mult_delta:+.0f}%)"
    )
    _print_schedule(rep, constants, header="\n=== Updated plan ===")
    return 0


def cmd_show(argv: list[str]) -> int:
    constants = load_constants()
    courses = load_courses()
    team = load_team()
    if not SCHEDULE_CSV.exists():
        print("no schedule yet. Run `python main.py plan`.")
        return 2
    state = load_state(courses, team, constants)
    _print_schedule(state, constants, header="=== Current schedule ===")
    return 0


def cmd_reset(argv: list[str]) -> int:
    force = "--force" in argv or "-y" in argv
    if not SCHEDULE_CSV.exists():
        print("no schedule to reset.")
        return 0
    if not force:
        try:
            ans = input(f"delete {SCHEDULE_CSV}? [y/N] ")
        except EOFError:
            ans = "n"
        if ans.strip().lower() != "y":
            print("aborted.")
            return 1
    SCHEDULE_CSV.unlink()
    print(f"removed {SCHEDULE_CSV}")
    return 0


COMMANDS = {
    "plan": cmd_plan,
    "finish": cmd_finish,
    "show": cmd_show,
    "reset": cmd_reset,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print("usage: python main.py {plan|finish|show|reset} [args]")
        return 0
    cmd = argv[0]
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(f"unknown command: {cmd}")
        return 2
    return fn(argv[1:])
