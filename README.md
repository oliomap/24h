# 24h-OL Thüringen 2026 — Optimizer

Planning and live-replanning tool for a 6-runner team in the **24-hour
orienteering relay at Heyda (Thüringer Wald), 16–17 May 2026**. Python
backend with the optimization engine; Next.js dashboard for the race-day
operator.

## Layout

```
24h/
├── backend/      FastAPI + optimizer + CLI (Python 3.10+)
│   ├── api.py           HTTP shim over the optimizer
│   ├── main.py          CLI entrypoint (plan/finish/show/reset)
│   ├── config/          YAML knobs (constants, courses, team)
│   ├── data/            schedule.csv lives here at race time
│   ├── src/             models, time model, phases, optimizer, calibration
│   └── tests/           pytest suite (34 tests)
├── frontend/     Next.js 16 + Tailwind v4 dashboard (Node 20+)
├── mockups/      static HTML mockups used to pick the visual direction
├── extensions.md possible follow-ups (MP/DNF rules, etc.)
└── Makefile      `make backend` / `make frontend` / `make check`
```

## Quick start

Two terminals.

```bash
# one-time setup
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && nvm use && npm install && cd ..

# terminal A — backend at http://127.0.0.1:8000
make backend

# terminal B — frontend at http://localhost:3000
make frontend
```

Open <http://localhost:3000>.

### Race-day loop

1. First load: click **Plan erstellen** (or press `P`). The optimizer searches
   starting orders and writes `backend/data/schedule.csv`.
2. As each runner crosses the line: type the actual minutes into the
   highlighted row, press <kbd>↵</kbd>. The runner's pace multiplier is
   recalibrated and the remaining cycles are re-optimised.
3. <kbd>R</kbd> forces a full replan, <kbd>?</kbd> shows the shortcut overlay.

### CLI fallback

If the UI is down, the same operations work from the shell:

```bash
cd backend
.venv/bin/python main.py plan
.venv/bin/python main.py finish Hannes 28.4
.venv/bin/python main.py show
.venv/bin/python main.py reset
```

CLI and UI share `backend/data/schedule.csv` — they can be mixed freely.

---

## How the optimization works

The race is a sequence of cycles; each cycle one runner starts one course
and finishes when they hand the next runner off. The optimizer's job is to
choose, before each cycle, **which course this runner should take** so the
team finishes the maximum number of correctly-completed courses by the
09:00 cutoff (rule §9). The cyclic order of runners is locked from cycle 1
onward (rule §4) so the decision is purely about *which course*.

### The four moving parts

```
┌─────────────────┐   predict(runner, course)     ┌────────────────┐
│   Time model    ├──────────────────────────────►│   Optimizer    │
│ (pace×T×K×night)│                               │ rollout+greedy │
└────────▲────────┘                               │  + tiebreaker  │
         │                                        └───────┬────────┘
         │ pace_multiplier per runner                     │
         │ (EWMA, clamped)                                │ writes
┌────────┴────────┐   actual minutes              ┌───────▼────────┐
│   Calibration   │◄──────────────────────────────┤    schedule    │
│   (online)      │  POST /api/finish from UI     │   CSV (atomic) │
└─────────────────┘                               └────────────────┘
```

#### 1. Time model — `backend/src/time_model.py`

Predicts `(mean, σ)` minutes for *(runner, course)*:

```
pace = K6_PACE_MIN_PER_KM × (1 + K_STEP_PCT × (6 − runner.K)) × pace_multiplier
nav  = 1 + T_GAP_PCT × max(0, course_T − runner.T)
night= 1 + NIGHT_PCT  if course is EN/HN  else 1
flat = course.length_km + course.climb_m / CLIMB_M_PER_FLAT_KM
mean = pace × flat × nav × night
σ    = SIGMA_PCT × mean
```

So fitness (`K`) scales the base pace, technicality gap (`course_T − runner_T`)
penalizes runners who are out of their depth, climb is folded into flat-equivalent
km Naismith-style, and night maps carry a constant penalty. `pace_multiplier`
starts at 1.0 per runner and is learned live from actual finishes.

#### 2. Online calibration — `backend/src/calibration.py`

Each actual finish blends a new observation into that runner's multiplier:

```
observation = clamp(actual / clean_prediction, MIN, MAX)
multiplier  = clamp(α × observation + (1−α) × previous_multiplier, MIN, MAX)
```

The two clamps are non-negotiable: a 1000-min outlier (lost runner, typo,
DNF) without a clamp drives the multiplier to absurd values and silently
disables that runner's future legs (every prediction overshoots the
cutoff). `PACE_MULTIPLIER_MIN/MAX = 0.4 / 2.5` keeps everything tractable.

#### 3. Phase machine — `backend/src/phases.py`

`legal_next_courses` returns the courses the next runner is *allowed* to
choose from. Encodes the Regelordnung §5.3 phase ordering verbatim:

```
SF (cycle 1 only)
  └── TH1..5 (any order, all 5 before anything else)
        └── E/H day courses (free choice)
              ├── ST, LT mandatory at TWILIGHT_TIME (Wechselzeitpunkt)
              │     [early-unlock window: ST/LT also legal up to
              │      TWILIGHT_EARLY_UNLOCK_MIN min before, used as a safety
              │      release valve when every remaining day course would
              │      worst-case overshoot the Wechselzeitpunkt]
              └── after ST and LT both done:
                    EN/HN night courses + any remaining day courses
                    (day courses BLOCKED in [TWILIGHT_TIME, DAY_RESUME +
                     DAY_DISPATCH_BUFFER_MIN) — no reflectors, unreadable
                     in fading/pre-sunrise light)
                    └── FF (Schlussbahn, only when everything else done)
```

#### 4. Optimizer — `backend/src/optimizer.py`

For each decision point, **score every legal course** for the up-runner:

```
score = comparative_advantage / (risk_adjusted_minutes + handover)

comparative_advantage = median(other_runners' time on this course) / my_time
risk_adjusted_minutes = mean+σ when slack < SAFETY_SIGMA_THRESHOLD × σ,
                        else mean
```

That score is the heart of the assignment logic. It rewards both **efficiency**
(shorter expected time wins) and **specialization** (use *your* minute on
the course where you are most disproportionately faster than your teammates).
The latter is why high-T runners get hard courses while high-K runners get
the long flat ones, instead of every runner naively grabbing the shortest
legal map.

Selecting the next course:

- **`plan()`** — pre-race. Enumerate all 720 starting-order permutations,
  cheap-simulate each (`rollout_depth=0`), keep the top
  `STARTING_ORDER_PRUNE_TOP_N`, full-simulate those, pick the winner by
  rule §9 metric (most courses, then earliest finish).
- **`replan()`** — after a finish. Keep the done legs as anchors, re-simulate
  the tail from the actual finish time of the last done leg.
- **`simulate()`** — `_pick_best_course` evaluates the top-K candidates by
  score, simulates each `ROLLOUT_DEPTH` cycles deeper plus a greedy tail,
  and picks the one that yields the most total courses (rule §9 primary
  axis) — tie-broken on **earliest simulated finish** (rule §9 secondary).

#### Day-map safety (the part where runners don't get lost in the dark)

Two layered checks keep day courses inside daylight:

- **Phase-level**: day maps are excluded from the legal pool whenever
  `now ∈ [TWILIGHT_TIME, DAY_RESUME + DAY_DISPATCH_BUFFER_MIN)`. The
  morning buffer absorbs the fast-tail case where a previous leg comes
  in faster than its mean and the actual handover would otherwise drag
  the day-course dispatch back into pre-sunrise twilight.
- **Candidate-level (`_day_course_unsafe`)**: a day course is rejected
  if its worst-case finish (`mean + DAY_SAFETY_SIGMA × σ`) lands inside
  `[TWILIGHT_TIME, DAY_RESUME)`. So a day map is only dispatched when
  even its slow tail is back before the Wechselzeitpunkt.

Night maps (EN/HN) have reflectors and remain legal at any time after
ST/LT are done — rule §5.3.5 explicitly puts them *in addition to any
remaining day maps* without a time cap.

---

## Configurable parameters — `backend/config/`

Three YAML files. Edit and re-run `plan` (CLI) or hit **Plan erstellen** in
the UI.

### `constants.yaml`

| Key | Default | Meaning |
|---|---|---|
| `K6_PACE_MIN_PER_KM` | `5.5` | Pace (min/km) of a K=6 runner on clean flat forest with no navigation penalty. **Tune to the team's actual fitness floor.** |
| `K_STEP_PCT` | `0.10` | Each K-point below 6 adds this fraction to pace. K=4 ⇒ pace × 1.20. |
| `T_GAP_PCT` | `0.12` | Penalty per step the course is more technical than the runner. Course T=5, runner T=3 ⇒ time × 1.24. |
| `NIGHT_PCT` | `0.15` | Constant slowdown for EN/HN courses regardless of dispatch time. |
| `SIGMA_PCT` | `0.12` | Predicted-time σ as fraction of mean. Drives both the risk-adjusted finish check and the day-course safety check. |
| `HANDOVER_OVERHEAD_SEC` | `90` | Hand-touch + Startpflichtstrecke + map pickup + start punch, added between every cycle in the planner. |
| `CLIMB_M_PER_FLAT_KM` | `100` | Naismith conversion: 100 m climb ≈ 1 km flat-equivalent. |
| `RACE_START` | `2026-05-16T09:00:00+02:00` | Mass start (rule §5.1). |
| `TWILIGHT_TIME` | `2026-05-16T20:00:00+02:00` | Announced **Wechselzeitpunkt** for ST/LT. Update on race day once officials announce it (rule §5.3.4: by 19:00, at least 1h before). |
| `CUTOFF_TIME` | `2026-05-17T09:00:00+02:00` | Zielschluss (rule §8). |
| `DAY_RESUME` | `2026-05-17T05:30:00+02:00` | First moment a day map can dispatch in the morning. Sunrise at Heyda is ~05:18; this is ~12 min after, in safe daylight. |
| `DAY_SAFETY_SIGMA` | `1.5` | Worst-case σ multiplier in the day-course safety check: a day map is only dispatched if `mean + 1.5σ` finishes before TWILIGHT_TIME. |
| `DAY_DISPATCH_BUFFER_MIN` | `10` | Morning-side safety buffer (minutes). A day map is only legal once `now ≥ DAY_RESUME + buffer`, absorbing the fast-tail case where the previous leg comes in faster than mean. |
| `TWILIGHT_EARLY_UNLOCK_MIN` | `30` | Allow ST/LT into the legal pool this many minutes before TWILIGHT_TIME. Safety release valve when every remaining day course would worst-case overshoot the Wechselzeitpunkt. |
| `SAFETY_SIGMA_THRESHOLD` | `2.0` | Switch a candidate's risk-adjusted finish from `mean` to `mean+σ` when slack to cutoff is below `threshold × σ`. |
| `ROLLOUT_TOP_K` | `3` | Number of top-scored candidates expanded with a deeper rollout per decision point. Bigger = slower but searches wider. |
| `ROLLOUT_DEPTH` | `3` | Extra cycles to expand recursively before falling back to greedy continuation. |
| `STARTING_ORDER_PRUNE_TOP_N` | `60` | Of the 720 starting-order permutations, this many get the full rollout simulation; the rest are kept-or-dropped on the cheap pass. Bigger = slower `plan()` but better starting order. |
| `CALIBRATION_ALPHA` | `0.4` | EWMA weight for a new actual-time observation when updating a runner's pace multiplier. Higher = react faster, more jitter. |
| `PACE_MULTIPLIER_MIN/MAX` | `0.4 / 2.5` | Hard clamps on the per-runner multiplier (per-observation *and* after blending). Stops a single outlier finish from disabling a runner. |
| `COURSE_T_BY_TYPE` | `{SF:2, TH:3, E:2, H:5, ST:2, LT:2, EN:3, HN:5, FF:5}` | Per-type default technicality (1..6), used by the navigation-penalty term. Tweak when courses are visibly harder/easier than their type implies. |

### `courses.yaml`

The 37 courses from the **Programmheft 2026 page 12**. Format:

```yaml
- {code: SF,  type: SF, length_km: 4.2, climb_m: 95,  controls: 15}
```

Update on race day if the organizers adjust the `*`-marked count (rule §5.3).

### `team.yaml`

The six runners with their team-relative `T` (orienteering technicality, 1–6)
and `K` (fitness, 1–6) scores:

```yaml
- {name: Sofia,  T: 6, K: 4}
- {name: Hannes, T: 3, K: 6}
- ...
```

Online calibration handles ±20–30% pace drift automatically; only edit `T/K`
mid-race if a runner is clearly above/below their listed level.

---

## Tests

```bash
cd backend && env -u PYTHONPATH -u AMENT_PREFIX_PATH .venv/bin/pytest tests/ -q
```

34 tests covering the time model (pace × T × K × climb × night), the phase
machine (every legal-pool transition + early-unlock + dark-window blocks),
and the optimizer (pre-race plan invariants, replan after extreme finishes,
the rollout tiebreaker, day-course-in-daylight regression for both ends,
the user-reported slow-then-fast scenario).

---

## What's intentionally missing

See [`extensions.md`](extensions.md) for follow-ups a next maintainer should
be aware of — most notably the Regelordnung §6 (MP / non-counted course)
and §7 (DNF / 5er-team continuation) Zielschluss-shift rules, which are
captured in the data model but not yet acted on by the planner.
