from datetime import datetime, timedelta

from src.models import RaceState, Runner
from src.phases import legal_next_courses
from src.state import load_constants, load_courses, load_team


def _new_state():
    constants = load_constants()
    courses = load_courses()
    team = load_team()
    return RaceState(
        runners_in_order=team,
        assignments=[],
        course_pool=courses,
        completed_codes=set(),
        pace_multiplier={r.name: 1.0 for r in team},
    ), constants


def test_cycle_1_only_SF_legal():
    state, c = _new_state()
    legal = legal_next_courses(state, c.RACE_START, c.TWILIGHT_TIME)
    assert [x.code for x in legal] == ["SF"]


def test_after_SF_only_TH_legal():
    state, c = _new_state()
    state.completed_codes.add("SF")
    legal = legal_next_courses(state, c.RACE_START + timedelta(minutes=30), c.TWILIGHT_TIME)
    codes = sorted(x.code for x in legal)
    assert codes == ["TH1", "TH2", "TH3", "TH4", "TH5"]


def test_after_SF_and_TH_day_pool_legal():
    state, c = _new_state()
    state.completed_codes.update(["SF", "TH1", "TH2", "TH3", "TH4", "TH5"])
    now = c.RACE_START + timedelta(hours=3)
    legal = legal_next_courses(state, now, c.TWILIGHT_TIME)
    types = {x.type for x in legal}
    assert types == {"E", "H"}  # no EN/HN/ST/LT/FF yet


def test_twilight_forces_ST_LT():
    state, c = _new_state()
    state.completed_codes.update(["SF", "TH1", "TH2", "TH3", "TH4", "TH5"])
    # Plenty of day courses left, but it's now past twilight.
    after_twilight = c.TWILIGHT_TIME + timedelta(minutes=1)
    legal = legal_next_courses(state, after_twilight, c.TWILIGHT_TIME)
    codes = sorted(x.code for x in legal)
    assert codes == ["LT", "ST"]


def test_after_twilight_done_night_and_leftover_day_legal():
    state, c = _new_state()
    state.completed_codes.update(
        ["SF", "TH1", "TH2", "TH3", "TH4", "TH5", "ST", "LT"]
    )
    after_twilight = c.TWILIGHT_TIME + timedelta(hours=1)
    legal = legal_next_courses(state, after_twilight, c.TWILIGHT_TIME)
    types = {x.type for x in legal}
    # E and H leftovers stay legal alongside EN/HN.
    assert types == {"E", "H", "EN", "HN"}
    assert "FF" not in {x.code for x in legal}


def test_FF_only_when_everything_else_done():
    state, c = _new_state()
    # Mark all 36 non-FF courses as completed.
    for code in state.course_pool:
        if code != "FF":
            state.completed_codes.add(code)
    after_twilight = c.TWILIGHT_TIME + timedelta(hours=2)
    legal = legal_next_courses(state, after_twilight, c.TWILIGHT_TIME)
    assert [x.code for x in legal] == ["FF"]


def test_st_lt_locked_well_before_twilight():
    """Without the early-unlock, ST/LT must not appear in the legal pool when
    we're far from twilight (don't blow the twilight courses at noon)."""
    state, c = _new_state()
    state.completed_codes.update(["SF", "TH1", "TH2", "TH3", "TH4", "TH5"])
    far_from_twilight = c.TWILIGHT_TIME - timedelta(hours=2)
    legal = legal_next_courses(
        state,
        far_from_twilight,
        c.TWILIGHT_TIME,
        twilight_early_unlock_min=c.TWILIGHT_EARLY_UNLOCK_MIN,
    )
    types = {x.type for x in legal}
    assert "ST" not in {x.code for x in legal}
    assert "LT" not in {x.code for x in legal}
    assert types == {"E", "H"}


def test_st_lt_unlocked_inside_window():
    """Bug 1 fix: within TWILIGHT_EARLY_UNLOCK_MIN of twilight, ST/LT join the
    legal pool so the optimiser can pick them instead of being forced into a
    day course that would finish in the dark."""
    state, c = _new_state()
    state.completed_codes.update(["SF", "TH1", "TH2", "TH3", "TH4", "TH5"])
    # 10 min before twilight, with a 30-min unlock window.
    inside_window = c.TWILIGHT_TIME - timedelta(minutes=10)
    legal = legal_next_courses(
        state,
        inside_window,
        c.TWILIGHT_TIME,
        twilight_early_unlock_min=c.TWILIGHT_EARLY_UNLOCK_MIN,
    )
    codes = {x.code for x in legal}
    assert "ST" in codes and "LT" in codes, (
        f"ST/LT should be unlocked in the final {c.TWILIGHT_EARLY_UNLOCK_MIN} min "
        f"before twilight; got {sorted(codes)}"
    )
    # Day courses also remain legal in this window — the optimiser scores both
    # and picks the safer option.
    legal_types = {course.type for course in legal}
    assert {"E", "H"} & legal_types, f"day courses lost from pool: {legal_types}"


def test_nothing_legal_when_all_done():
    state, c = _new_state()
    for code in state.course_pool:
        state.completed_codes.add(code)
    legal = legal_next_courses(state, c.CUTOFF_TIME - timedelta(minutes=1), c.TWILIGHT_TIME)
    assert legal == []
