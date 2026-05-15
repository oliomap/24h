# Extensions — known gaps & future work

What's *not* in the current implementation, what a next maintainer should
understand before extending, and roughly how to wire each one in. Items
are ordered by how race-impacting they are.

Most of this list is unbuilt. The point is to capture the limitation and
the design hook so the next dev doesn't rediscover it under time pressure.
Items that *have* shipped (currently: §4) are kept for historical context
and to flag their tuning knobs.

---

## 1. Rule §6 — MP / non-counted leg with Zielschluss shift

**Status:** not implemented. The planner treats every finished leg as
counting toward the team total, and the cutoff is a hard `09:00 Sun`.

**The rule (verbatim):**
> Wurde eine Bahn nicht korrekt abgelaufen (z.B. bei Nichterbringen eines
> Postennachweises, falscher Anlaufreihenfolge der Posten u. ä. m.), so wird
> diese nicht für die Teamwertung gezählt. Der Läufer, dessen Lauf nicht
> gewertet wurde, darf weiterhin für sein Team starten. Das Team bleibt in
> der Wertung.
>
> Beträgt die Laufzeit eines nichtgewerteten Läufers weniger als 30 Minuten,
> verschiebt sich für das jeweilige Team der Zielschluss um die Zeitdifferenz
> "30 Minuten minus Laufzeit" nach vorn.

**What needs to happen:**

1. **Data model.** The `Assignment` status enum currently is
   `planned | in_progress | done | skipped`. Add `mp` (or extend `done`
   with a `counted: bool`). Distinguish "ran the course but it doesn't
   count" from "didn't run at all".
2. **Score (rule §9).** Only count `done && counted` legs toward the team
   total. The optimizer's count-maximisation should reflect this — picking
   a leg that's likely to MP at-risk runners on hard courses is now a real
   tradeoff.
3. **Cutoff adjustment.** Maintain a derived
   `effective_cutoff = CUTOFF_TIME − Σ max(0, 30min − leg_time)` over all
   MP legs `<30 min`. The optimizer's hard cutoff filter must use this
   derived value, not the raw `CUTOFF_TIME`. The UI's "Puffer bis Ziel"
   needs to read this too.
4. **Operator UX.** The "Ist-Zeit" input currently only accepts a duration.
   Add a flag (a key like `M` for MP, or a small toggle next to the input)
   so the operator can record "Hannes finished H4 in 22 min but it doesn't
   count". Replan from there.
5. **Calibration.** Don't update the pace multiplier from an MP leg —
   the actual time reflects the wrong route, not the runner's pace.

**Hooks already in place:** `Assignment.status` is already a string,
`replan()` already keys off `status ∈ {done, in_progress}` to decide what
stays; adding a new status value is a one-line change. The optimizer's
cutoff check is centralised in `_candidate_scores` / `simulate`.

---

## 2. Rule §7 — DNF runner; 5-runner team continuation

**Status:** not implemented. The planner assumes all six runners stay
available through the cutoff. If a runner DNFs, the operator has to
hand-edit `schedule.csv` or accept that the locked cyclic order keeps
sending them out.

**The rule (verbatim):**
> Wenn alle 6 Läufer eines Teams einmal gestartet sind, kann bei Ausfall
> eines Läufers der Wettkampf als 5er-Team fortgesetzt werden. Mit dem
> zweiten und jeden weiteren Ausfall verschiebt sich der Zielschluss für
> das betreffende Team um jeweils 30 Minuten nach vorn (Wettkampf endet
> zeitiger).
>
> Jeder Ausfall ist spätestens mit dem Start des Läufers, der vor dem
> ausgefallenen Läufer eine Bahn absolviert, der Wettkampfleitung zu melden.
> Als Ausfall gemeldete Läufer dürfen nicht wieder zum Einsatz kommen.

**What needs to happen:**

1. **Data model.** Add an `available: bool` (or a `dnf_at_cycle: int | None`)
   per `Runner`. Once true/set, the cyclic-order helper must *skip* that
   runner and dispatch the next one in sequence.
2. **Order helper.** `RaceState.runner_for_cycle()` currently does
   `runners_in_order[(cycle-1) % 6]`. Replace with a generator that filters
   out DNF'd runners, walking forward until a live runner is found. Must
   stay deterministic and rule-compliant: the *relative* order of the
   remaining runners is preserved (rule §4).
3. **Cutoff adjustment.** Same machinery as §6: derived `effective_cutoff`,
   shifted forward by 30 min per DNF *beyond the first*. The first DNF is
   free.
4. **Validation gate.** The rule requires the DNF be reported *no later
   than the start of the runner before the DNF'd runner*. The UI should
   surface that deadline so the operator doesn't miss it.
5. **Replan.** Trivially follows once the data model and order helper
   are wired — replan from the DNF cycle, all downstream cycles re-assign.

**Why this matters more than it looks:** a DNF early in the race can flip
the optimal starting-order choice (e.g., we picked Sofia first because
she was the best technical runner; if she DNFs, the remaining 5 may
prefer a different sub-rotation). The current implementation can't
re-evaluate that; it just keeps the original cyclic order minus the
DNF'd runner.

---

## 3. Stamina nonlinearity in the time model

**Status:** not implemented. The current `predict_time` is linear in
length: pace is a constant per runner, so a K=2 runner is "40% slower"
than a K=6 runner *regardless of distance*. Reality is nonlinear — a
recreational K=2 runner asked to do 8 km in technical forest fatigues,
walks the climbs, and the time blows out well past the linear prediction
(or doesn't finish).

**Symptom this produces.** On a fresh full plan, total km per runner came
out *inverted* to fitness:

```
Hannes    K=6   24.3 km   (fittest, runs the least)
Sofia     K=4   30.4 km
Erich     K=3   34.3 km   (gets H7 10.1 km AND HN7 8.3 km)
Christine K=2   31.3 km   (gets E7 8.2 km AND EN7 8.3 km)
Flocke    K=5   29.8 km
Alicia    K=1   29.0 km
```

Christine (K=2) logs more total km than Hannes (K=6) — structurally
wrong. The root cause is that the score formula `advantage ÷ time` makes
short courses look exponentially more attractive for fast runners, so
they gobble shorts, leaving long courses for whoever's cycle comes up
later in the rotation.

**The proposed fix — one factor in `predict_time`:**

```
threshold_km = STAMINA_BASE_KM + STAMINA_K_KM × runner.K     # comfort distance
overrun_km   = max(0, flat_equivalent_km − threshold_km)
stamina      = 1 + STAMINA_PCT_PER_KM × overrun_km

mean = pace × flat_equivalent_km × nav × night × stamina
```

`flat_equivalent_km` already folds climb in Naismith-style, so climb
costs stamina too — no extra term needed.

**Suggested defaults** (chosen to leave short courses untouched and bite
hardest where the model is most wrong):

| Constant | Default | Effect |
|---|---|---|
| `STAMINA_BASE_KM` | `2` | Everyone fine for 2 km. |
| `STAMINA_K_KM` | `1.5` | K=6 comfort 11 km (longest course covered); K=1 comfort 3.5 km. |
| `STAMINA_PCT_PER_KM` | `0.06` | 6 % pace inflation per overrun km. |

**Expected impact on the target case** (EN7, 9.75 km flat-eq):

| Runner | K | Threshold | Overrun | Stamina | Mean now | Mean after | Δ |
|---|---|---|---|---|---|---|---|
| Hannes | 6 | 11.0 | 0 | 1.00 | 62 | 62 | +0 |
| Sofia | 4 | 8.0 | 1.75 | 1.105 | 74 | 82 | +8 |
| Erich | 3 | 6.5 | 3.25 | 1.195 | 80 | 96 | +16 |
| **Christine** | **2** | **5.0** | **4.75** | **1.285** | **86** | **111** | **+25** |
| Alicia | 1 | 3.5 | 6.25 | 1.375 | 115 | 158 | +43 |

The Hannes↔Christine gap widens from 24 min to 49 min — that's the
lever the optimiser's comparative-advantage score needs to start
preferring fit runners for long courses.

**Caveat — necessary but possibly not sufficient.** Because the score
formula's `÷ time` term still dominates, fast runners will *still*
prefer short courses at their own cycle. The fix improves prediction
accuracy and *re-weights* the score (Christine's score for EN7 drops),
but if Christine's cycle is last and the only remaining options are
long, she'll still inherit one. If after implementing the optimiser
keeps making the same long-for-weak-runner assignments, the next step
is either:

- **Reweight the score** (e.g. `advantage² / sqrt(time)` to lessen the
  short-course bias), or
- **Hard-block by stamina-overrun ratio** in `_candidate_scores` —
  refuse to dispatch a course where `overrun / threshold > some_ratio`,
  forcing the optimiser to find someone else (at the cost of leaving
  some courses unscheduled at the tail).

**Where to wire it (concrete hooks):**

1. `backend/config/constants.yaml` — add the three constants with the
   defaults above and a short comment block.
2. `backend/src/models.py` — three new fields on `Constants` with
   defaults so older YAML still loads.
3. `backend/src/state.py` — read them in `load_constants` with `.get()`
   fallbacks.
4. `backend/src/time_model.py` `predict_time` — compute and apply the
   `stamina` factor. Single multiplicative line. Add a new test that
   covers: zero overrun → factor 1.0; positive overrun → factor matches
   the formula; the existing `test_climb_adds_time` continues to pass
   for K=4 + flat-eq 7 km (threshold 8 — stays inside comfort).
5. Existing `test_real_courses_load_and_have_sane_times` upper bound for
   Hannes-on-H7 (currently `< 110`) needs a hand-check: with K=6
   threshold 11, H7 flat-eq 12.25, overrun 1.25, stamina 1.075, time
   lands at ~90 min — comfortably inside.

**Acceptance check after implementation:**

- All existing tests pass.
- Per-runner total km becomes monotone or near-monotone in K (fittest
  ≥ least fit).
- A fresh `python main.py plan` shows Hannes (K=6) carrying more total
  km than the K≤3 runners.
- Total cycle count doesn't regress materially (within 1 of the prior
  37-or-near-37 baseline).

If the optimiser still gives Christine EN7 after this change, the
follow-up reweighting / hard-block options above are the next surgery.

---

## 4. Allowed-maps matrix — operator-driven course constraints

**Status:** **implemented.** Per-runner course/type forbid-lists in
`team.yaml`, filtered in `_candidate_scores`. Three independent filters
now stack: phase machine → forbid matrix → cutoff fit.

### Why it exists

The time model assumes any runner can complete any course, just at a
slower predicted time. In reality, a coach knows things the time model
never will: "Christine's knee can't take anything over 6 km this race",
"Alicia disorients on H-type maps at night", "Hannes refuses HN courses
with >100 m climb". These are physical / mental / preference constraints
orthogonal to T, K, and (future) stamina, and they can't be derived from
numbers — they have to be declared.

Without the matrix, the optimiser will *eventually* assign a low-T/low-K
runner to a long technical night course because the cyclic order forces
their cycle to come up at a moment where that's the only legal high-score
option. The numbers say "yes, 110 min"; reality says "she may not finish,
or worse, get lost in the woods at 3 AM".

### Data shape

```yaml
- name: Christine
  T: 4
  K: 2
  forbid_courses: [E7, H7, EN7, HN6, HN7]   # K=2 → longest in each pool out of scope
- name: Flocke
  T: 2
  K: 5
  forbid_types:   [HN]                       # T-gap of 3 in pitch dark is unsafe
- name: Alicia
  T: 1
  K: 1
  forbid_types:   [H, HN]                    # T-mismatch on technical maps
  forbid_courses: [E7, EN7]                  # + longest distances
```

Either key is optional; an absent or empty key means "no extra
restrictions". The other three runners (Sofia, Hannes, Erich) carry no
forbids.

### Behavior

- A forbidden course is dropped from the candidate list for that
  runner — the optimiser must find someone else for it.
- Stacks cleanly on top of the phase machine and (future) stamina —
  each filter surgically scoped, no entanglement.
- Can produce infeasible cycles if constraints are too tight (no
  runner can take the only remaining course at the locked-order cycle);
  the simulator stops there, leaving an unplotted course rather than
  silently violating the operator's intent. With the current defaults
  this hasn't been observed — fresh plans produce 34 cycles with +11 min
  slack to cutoff.
- **Don't forbid mandatory single-course types/codes (SF, ST, LT, FF)**
  on the runner whose locked cycle they fall into — the simulator will
  halt at that cycle. The team.yaml comment block flags this.

### Where it's wired

1. [`backend/config/team.yaml`](backend/config/team.yaml) — optional
   `forbid_courses: [...]` and `forbid_types: [...]` per runner.
2. [`backend/src/models.py`](backend/src/models.py) `Runner` — two
   frozenset fields, default empty. `Runner` stays frozen and hashable.
3. [`backend/src/state.py`](backend/src/state.py) `load_team` — reads
   the optional lists, builds frozensets, attaches to the `Runner`.
4. [`backend/src/optimizer.py`](backend/src/optimizer.py)
   `_candidate_scores` — first line in the `for course in legal:` loop,
   `continue` if `course.code in runner.forbid_courses or course.type in
   runner.forbid_types`.
5. Tests in [`backend/tests/test_optimizer.py`](backend/tests/test_optimizer.py):
   `test_forbid_courses_excluded_from_runner_candidates`,
   `test_forbid_types_excluded_from_runner_candidates`,
   `test_plan_honors_forbid_matrix_end_to_end`.

### Caveats / what's still open

- **Static, edited as YAML.** A forbid set pre-race may turn out wrong
  on race day (the runner felt fine, knee held up). There's no UI to
  clear an entry mid-race yet — the operator has to edit
  `backend/config/team.yaml` on the server and `systemctl restart
  24h-backend`. A live-toggle UI is captured under §8 (Schedule-aware
  operator UX).
- **No allow-list form.** The doc earlier proposed allow-lists too;
  only forbid-lists are implemented (easier to maintain — empty means
  "anything legal"). If a future use case needs an allow-list, the
  hook is one extra `if course.code not in runner.allow_courses`
  line in the same place.
- **No infeasibility warning.** If a tight forbid set means cycle N has
  zero candidates, `simulate` stops cleanly but doesn't surface *why*.
  An operator looking at "Bahnen 23/37" with the cutoff still 4h away
  has to guess that a forbid is too aggressive. A debug log line in
  `_candidate_scores` ("runner X had 0 candidates at cycle N: all
  legal courses forbidden") would help — not wired yet.

### Synergy with §3 (stamina)

Stamina is a *soft, automatic, physical* correction — it lets the
optimiser self-rebalance based on what the model knows. The forbid-list
is a *hard, manual, knowledge-injection* override — it captures the part
of "fit for course" that the model will never see. They complement each
other and the matrix already partially mitigates the §3 "weakest runner
logs more total km than the fittest" inversion as a side effect: with
the current forbids, Christine drops from 31.3 km → 18.3 km and Alicia
from 29.0 km → 21.0 km, while Hannes (no forbids) lands at 29.6 km.
Stamina nonlinearity is still worth implementing — the matrix only
removes *categorical* mismatches; in-scope load distribution is
stamina's domain.

---

## 5. Calibration: per-course-type multipliers

**Status:** one pace multiplier per runner. So a runner who is bad at
H (technical hard) but fine at E (easy) drags her predictions for both
types in the same direction.

**Hook:** `pace_multiplier: dict[str, float]` keyed by runner name in
`RaceState`. Generalise to `dict[(runner_name, course_type), float]`
with fallback to `runner_name → mean across types`. The time model and
calibration are isolated in `time_model.py` / `calibration.py`; no other
component cares.

---

## 6. Cumulative-sigma planning on the morning DAY_RESUME boundary

**Status:** the morning-side `DAY_DISPATCH_BUFFER_MIN` is a *constant*
(10 min), set to roughly absorb 1.5σ of a single ~30-min night cycle.
A correct treatment would track the *cumulative* σ of all planned cycles
between the moment of decision and the proposed day-map dispatch.

**Why it matters in practice:** if the planner is choosing the next leg
six cycles before DAY_RESUME (so six planned-cycle σs stack), the actual
arrival time has much wider variance than one σ. The current constant
buffer under-protects in that case; conversely, when the decision is one
cycle out from DAY_RESUME, the buffer over-protects.

**Hook:** track `Σ planned_sigma_min` per simulated branch, expose it to
`_day_course_unsafe` (or to `_legal` via a buffered `day_resume`).

---

## 7. Multi-segment course model (flats vs climbs vs technical bits)

**Status:** every course is one homogeneous (`length_km`, `climb_m`,
`controls`) tuple, converted to flat-equivalent km via a single Naismith
constant.

**Reality:** the same runner can be fast on flat-and-fast forest and
slow on contour-detail. A `controls`-density factor for technicality and
a steepness factor for climb (Naismith is conservative for short steep
sections) would improve predictions noticeably.

**Hook:** `time_model.flat_equivalent_km` and `predict_time` are both
tiny pure functions. Extending the `Course` schema to carry segment
breakdowns or per-control densities, and refining those functions, is
strictly local.

---

## 8. Schedule-aware operator UX

A handful of UX gaps that would matter on race day but are not in scope
for the v1:

- **Wechselzeitpunkt announcement input.** Currently
  `TWILIGHT_TIME` is edited in `constants.yaml` and the backend restarts
  to pick it up. Officials announce by 19:00; a UI input on the
  dashboard would let the operator set it once and trigger a replan.
- **Runner-status toggles.** Mark a runner as on-course, available,
  warming up, resting, DNF (see §2). Currently invisible to the planner.
- **Audible-alerting / pre-arrival countdown.** The planner knows the
  predicted finish time; a 60-second pre-arrival ping for the next
  runner would reduce hand-touch overhead.
- **MP / strafkennzeichen entry.** Right now `actual_minutes` is the
  only field. See §1 above.

---

## 9. Search quality knobs that are turned conservatively

- `STARTING_ORDER_PRUNE_TOP_N = 60` (of 720) — we full-rollout-simulate
  the top 60 cheap-evaluated starting orders. Race-day machine is fine,
  so this could be raised to 120 or 200 for a small gain at the cost of
  a slower `plan()`.
- `ROLLOUT_DEPTH = 3`, `ROLLOUT_TOP_K = 3` — the recursion budget per
  decision point. Beam-search depth of 4–5 with a wider top-K would
  almost certainly find better tails, especially near the cutoff where
  one extra cycle is high-value.
- Both expand the optimizer's search; nothing else changes.

---

## 10. Twilight early-unlock vs. strict §5.3.4 reading

**Current behavior:** `TWILIGHT_EARLY_UNLOCK_MIN = 30` lets the planner
pick ST/LT up to 30 min before `TWILIGHT_TIME` *when every remaining day
course would worst-case overshoot the Wechselzeitpunkt*. This is a
**safety override** of a strict reading of rule §5.3.4, which only
explicitly permits early ST/LT once all day courses are done.

It's documented (in `constants.yaml` and in the README), the tests
encode the behavior, but a maintainer who's tightening for rule strictness
should be aware it exists. Two ways to harden:

- Only fire early-unlock when all `E` and `H` courses are done (strict
  §5.3.4) — the planner will then idle a runner near twilight if no day
  map fits safely, which costs 5–15 min of utilisation.
- Move the override into the operator's hands: surface a "switch to ST/LT
  now" button instead of doing it automatically.

---

## 11. Operational extras

Not rule-related but real on race day:

- **Persistent runner notes / injuries.** Free-text "left knee felt
  iffy on H3" attached to a runner.
- **Drop-from-team-result toggle.** Sometimes a course is run for
  experience, not for score (e.g., the operator wants Alicia to try LT
  even though she's not the optimal pick). A "force assignment" override
  in the UI that locks one cycle to a chosen course while replan handles
  the rest.
- **Spectator export.** A read-only public URL that shows the current
  plan + last-finish times, so family / supporters can watch without
  needing the operator's dashboard.
- **Race-night dark-mode polish.** The current scheme is already
  low-light-friendly but a dedicated red-light theme for sunset–sunrise
  would help.

---

## Where to start (if you're picking this up)

§4 (forbid matrix) is the only item from this list that's shipped. Two
natural next starting points, depending on what you're optimising for:

- **Rule robustness (highest race-day impact):** do **§1 (MP) + §2 (DNF)
  together** — they share the cutoff-shift machinery and the operator-input
  wiring, and together they take the planner from "happy path only" to
  robust against the two failures that actually happen at 24h relays.
  Touch `backend/src/models.py`, `backend/src/state.py`, the API in
  `backend/api.py`, and `frontend/components/ScheduleTable.tsx`. The
  optimizer itself (`backend/src/optimizer.py`) needs one change: read
  `effective_cutoff` instead of `constants.CUTOFF_TIME` in the two filter
  sites in `_candidate_scores`.
- **Assignment quality (highest "is this a sensible plan?" impact):** do
  **§3 (stamina nonlinearity)**. Smaller surgery — a single multiplicative
  factor in `predict_time` plus three constants — but it directly fixes
  the structurally-wrong load distribution where the weakest stamina
  runner currently logs more total km than the fittest. §4 has already
  closed the *categorical* mismatch case (the matrix moves long maps off
  Christine and Alicia entirely); §3 is now about smoothly re-weighting
  the *in-scope* load distribution. The section above spells out the
  formula, the suggested defaults, and a hand-computed expected-impact
  table.
