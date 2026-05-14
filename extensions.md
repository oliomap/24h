# Extensions — known gaps & future work

What's *not* in the current implementation, what a next maintainer should
understand before extending, and roughly how to wire each one in. Items
are ordered by how race-impacting they are.

Nothing in this list is built. The point is to capture the limitation and
the design hook so the next dev doesn't rediscover it under time pressure.

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

## 3. Calibration: per-course-type multipliers

**Status:** one pace multiplier per runner. So a runner who is bad at
H (technical hard) but fine at E (easy) drags her predictions for both
types in the same direction.

**Hook:** `pace_multiplier: dict[str, float]` keyed by runner name in
`RaceState`. Generalise to `dict[(runner_name, course_type), float]`
with fallback to `runner_name → mean across types`. The time model and
calibration are isolated in `time_model.py` / `calibration.py`; no other
component cares.

---

## 4. Cumulative-sigma planning on the morning DAY_RESUME boundary

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

## 5. Multi-segment course model (flats vs climbs vs technical bits)

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

## 6. Schedule-aware operator UX

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

## 7. Search quality knobs that are turned conservatively

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

## 8. Twilight early-unlock vs. strict §5.3.4 reading

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

## 9. Operational extras

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

If you implement only one thing, do **§1 (MP) + §2 (DNF) together** —
they share the cutoff-shift machinery and the operator-input wiring, and
together they take the planner from "happy path only" to robust against
the two failures that actually happen at 24h relays. Touch
`backend/src/models.py`, `backend/src/state.py`, the API in
`backend/api.py`, and `frontend/components/ScheduleTable.tsx`. The
optimizer itself (`backend/src/optimizer.py`) needs one change: read
`effective_cutoff` instead of `constants.CUTOFF_TIME` in the two filter
sites in `_candidate_scores`.
