from src.models import Course, Runner
from src.state import load_constants, load_courses
from src.time_model import predict_time


def test_higher_k_is_faster_same_course():
    c = load_constants()
    course = Course(code="X", type="E", length_km=5.0, climb_m=0, controls=10)
    hannes = Runner(name="Hannes", T=3, K=6)
    alicia = Runner(name="Alicia", T=1, K=1)
    h_mean, _ = predict_time(hannes, course, c)
    a_mean, _ = predict_time(alicia, course, c)
    assert h_mean < a_mean


def test_higher_t_reduces_time_on_hard_course():
    c = load_constants()
    hard = Course(code="HX", type="H", length_km=5.0, climb_m=0, controls=10)
    sofia = Runner(name="Sofia", T=6, K=4)
    flocke = Runner(name="Flocke", T=2, K=5)
    # Flocke is fitter (K=5 vs K=4) but Sofia is more technical (T=6 vs T=2)
    # on a T=5 hard course. Sofia should be faster.
    s_mean, _ = predict_time(sofia, hard, c)
    f_mean, _ = predict_time(flocke, hard, c)
    assert s_mean < f_mean


def test_night_courses_slower_than_day_equivalent():
    c = load_constants()
    day = Course(code="E1", type="E", length_km=5.0, climb_m=0, controls=10)
    night = Course(code="EN1", type="EN", length_km=5.0, climb_m=0, controls=10)
    runner = Runner(name="R", T=4, K=4)
    d_mean, _ = predict_time(runner, day, c)
    n_mean, _ = predict_time(runner, night, c)
    # Night penalty is +15% default.
    assert n_mean > d_mean
    assert abs(n_mean / d_mean - (1 + c.NIGHT_PCT)) < 1e-6


def test_climb_adds_time():
    c = load_constants()
    flat = Course(code="F", type="E", length_km=5.0, climb_m=0, controls=10)
    hilly = Course(code="H", type="E", length_km=5.0, climb_m=200, controls=10)
    runner = Runner(name="R", T=4, K=4)
    f_mean, _ = predict_time(runner, flat, c)
    h_mean, _ = predict_time(runner, hilly, c)
    # 200m climb = 2km flat-equivalent extra, so hilly should take 40% longer.
    assert abs(h_mean / f_mean - 1.4) < 1e-6


def test_sigma_is_pct_of_mean():
    c = load_constants()
    course = Course(code="X", type="E", length_km=5.0, climb_m=0, controls=10)
    runner = Runner(name="R", T=4, K=4)
    mean, sigma = predict_time(runner, course, c)
    assert abs(sigma / mean - c.SIGMA_PCT) < 1e-6


def test_pace_multiplier_scales_linearly():
    c = load_constants()
    course = Course(code="X", type="E", length_km=5.0, climb_m=0, controls=10)
    runner = Runner(name="R", T=4, K=4)
    m1, _ = predict_time(runner, course, c, pace_multiplier=1.0)
    m2, _ = predict_time(runner, course, c, pace_multiplier=1.5)
    assert abs(m2 / m1 - 1.5) < 1e-6


def test_real_courses_load_and_have_sane_times():
    c = load_constants()
    pool = load_courses()
    assert len(pool) == 37
    sofia = Runner(name="Sofia", T=6, K=4)
    # Sofia on TH1 (short themed): should be roughly 15-25 min.
    mean, _ = predict_time(sofia, pool["TH1"], c)
    assert 10 < mean < 30
    # Hannes on H7 (10km hard day): should be substantial, 60-100 min range.
    hannes = Runner(name="Hannes", T=3, K=6)
    mean, _ = predict_time(hannes, pool["H7"], c)
    assert 50 < mean < 110
