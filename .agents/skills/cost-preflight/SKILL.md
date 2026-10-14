---
name: cost-preflight
description: Size compute before spending it. Classify the work as none, calculation, stream or generation; record the requested rung with cost_preflight.py; and for new event generation run same-process pilots first, because generation cost stays uncalibrated until matched pilots exist. Use for CHECK-IN 1's budget line, before any scan launch, and whenever statistics, grid size or resources change mid-run.
when_to_use: composing CHECK-IN 1's budget; sizing or re-sizing a scan, a background sample, a solver run or a pass over supplied events; any "how long / how much disk will this take" question
allowed-tools: Bash, Read
---
# Skill — cost preflight (pilot first, then budget)

State the required output and precision in the user's terms. Choose the cheapest method that meets the output, validity domain and precision, record why each cheaper method is insufficient or unavailable with evidence in `inputs/method-decision.json`, and stop when the answer is complete. Validate and render the record with `ravel method-decision --rundir RUN` before CHECK-IN 1 approval; full and scan launches refuse a missing, invalid or unjustified decision.

The physicist approves the budget at CHECK-IN 1. Budget numbers come from measurements of the
same process, model, settings and machine, or from the study's declared ceilings.

## Cost classes

| Class | Work | How to size it |
|---|---|---|
| `none` | Surveys and summaries of published results, literature questions, routing | No compute. Record `--mode none`. |
| `calculation` | Literal arithmetic, solver runs (cosmology, EFT running, symbolic, finite integrals), fits to supplied likelihoods or measurements, diagram enumeration | No events. The study declares `max_seconds` and, where the adapter has one, `max_ram_mib`. Solver stages declare `operation_resources` with `kind: solver`, zero `generated_events` and the `solver_evaluations` count ([operation resources](../../../docs/reference/operation-resources.md)). Put these ceilings in CHECK-IN 1. |
| `generation` | New events (MadGraph, Pythia, Delphes) | Pilot first, below. |

## Pilot first (generation)

`cost_preflight` reports `calibration_status: uncalibrated` and `walltime_h: null` for
`smoke`, `full` and `scan` until matched pilots exist. It names
`generation_efficiency.prepare_pilot` as the next step. Historical anchors stay with their own
historical process and are never applied to a new one.

1. Record the requested rung. The approval gate requires this artifact:
   ```bash
   ravel cost --mode <none|dry|smoke|full|scan> \
     --points N --events E --rundir <run>
   ```
   It writes `inputs/cost_preflight.json`.
2. Prepare a pilot of the production `model-events` specification: same process, model,
   settings and review policy, fewer events, a ceiling no larger than production.
   ```bash
   ravel generation-efficiency prepare-pilot --request pilot-request.json --base . --output pilot.json
   ```
   The request holds `production` and `pilot` specification pins and the pilot `rundir`. The
   pilot is an ordinary study and needs its own CHECK-IN 1 approval.
3. After each pilot finishes, `observe` records its measured wall time, disk and efficiency.
   Failed attempts stay as observations.
4. With two comparable completed pilots, `forecast` produces the production estimate from an
   explicit `scaling_assumption` and `wall_margin`. Present that estimate as the production budget.
5. Turn the forecast into the budget record the approval gate accepts for `full` and `scan`:
   ```bash
   ravel cost --mode full --points N --events E \
     --from-forecast forecast.json --rundir <run>
   ```
   The record has `schema_version: 3`, `calibration_status: measured` and pins the forecast
   by hash. Approval re-checks that pin and that the machine is the one the pilots ran on.

Any supervised generation run (a scoped generation or a `model-events` study) can be a pilot.
`ravel pilot-cost observe --rundir <pilot> --output obs.json` reads the completed stage times,
output size and machine; `ravel pilot-cost forecast --pilot obs.json [--pilot obs2.json]
--target spec.json --route scoped|science --margin M --output forecast.json` scales them to the
target. One pilot gives a proportional upper bound; two sizes give a fitted line. A forecast
over the target's `max_seconds` is refused. Pilots measured on another machine, or differing
from the target in anything but events, seeds or the list of points, are refused.

## The ladder (`compute_plan`)

| Rung | What | Cost |
|---|---|---|
| `none` | No compute | zero |
| `dry` | Render cards and configs; no generation | seconds |
| `smoke` | One point at small statistics; the CHECK-IN 2 waypoint | from the pilot |
| `full` | One point at full statistics | from the pilot |
| `scan` | N points; the deliverable | from the pilot |

Anything at `smoke` or above waits for CHECK-IN 1 approval. An overnight-scale estimate means
the run keeps a `RESUME.md` checkpoint (run-scan skill).

## Costs that are easy to miss

- **Background samples** often dominate distribution-shape work: slicing and per-slice
  statistics for continuum backgrounds cost more than the signal. Size the background first
  whenever the waypoint needs a simulated background curve.
- **Transient disk** for LHE, HepMC and detector output accumulates per concurrent point. The
  scan plan states its per-point cleanup rule (run-scan skill).

## Stop conditions

- The estimate exceeds free disk or a reasonable wall time: shrink the grid to the published
  lattice subset, lower concurrency or stage the scan in waves, and put that in the plan.
- Present every compute plan with these numbers. A size change mid-run is a DEVIATION check-in
  and ledger entry followed by a fresh preflight.
