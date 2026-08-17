---
name: cost-preflight
description: Estimate walltime/disk for any hep-agentic-pipeline compute BEFORE spending it — events × points × backend through cost_preflight.py's measured model (30–50 min/point native, 9 h/point container), and climb the dry→smoke→full→scan ladder. Use before CHECK-IN 1's budget line, before any scan launch, and whenever generation statistics or grid size change mid-run.
when_to_use: composing CHECK-IN 1's budget; sizing/re-sizing a scan or a background sample; any "how long / how much disk will this take" question
allowed-tools: Bash, Read
---
# Skill — cost preflight (estimate first, generate second)

Compute is the scarce resource and the physicist approves its budget at CHECK-IN 1 (charter
F5). Numbers come from the measured model, never from vibes:
```bash
python3 trial-runs/_infrastructure/cost_preflight.py --mode <none|dry|smoke|full|scan> \
  [--points N] [--events E] [--backend native|container] [--parallel M] [--json]
```

## The ladder (the contract's `compute_plan` — climb it, never jump)
| rung | what | cost |
|---|---|---|
| `none` | survey/summary from published material | zero |
| `dry` | render cards/configs, fail-loud placeholder scan, NO generation | seconds |
| `smoke` | 1 point × ≤1k events — the CHECK-IN 2 waypoint fuel | minutes |
| `full` | 1 point × full statistics | ~30–50 min native |
| `scan` | N points (parallel native; the deliverable) | hours–overnight |
Anything ≥ `full` waits for the CHECK-IN 1 go-ahead. An overnight-scale estimate (>6 h) means
the run maintains a `RESUME.md` checkpoint (charter §4c; run-scan skill).

## The two costs prose forgets
- **Background samples are the cost driver** for distribution-shape work (continuum QCD/DY:
  slicing + per-slice statistics dwarf the signal cost — trial gap G-CMS-06). Estimate the
  background FIRST for any waypoint that needs a simulated background curve.
- **Transient disk**: ~6 GB/point (LHE+HepMC+Delphes) × concurrent points; the scan plan
  states its per-point cleanup rule (run-scan skill) or a laptop dies mid-grid.

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "The signal sample is cheap, so the waypoint is cheap" | Trial gap G-CMS-06: the continuum BACKGROUND (slicing × per-slice statistics) is the cost driver — estimate it first. |
| "It took ~40 min last time; quote that" | The backend decides: ~30–50 min/pt native vs ~9 h/pt container (catalogue D2 is doc drift re-installing the wrong cost model). Cost the route actually taken. |
| "The grid only grew a little — no need to re-ask" | Re-sizing without a DEVIATION entry + re-preflight is the exact bypass of the budget the physicist approved at CHECK-IN 1. |

## Stop conditions
- Estimate exceeds the free disk or a sane wall (warns at >14 h) → shrink the grid to the
  published lattice subset / lower `--parallel` / stage the scan in waves — and put THAT in
  the plan for approval.
- Never present a compute plan without these numbers; never re-size silently mid-run (a
  size change is a DEVIATION check-in + ledger entry).

- **The budget is an ARTIFACT (H4):** always pass `--rundir <rd>` — it writes `inputs/cost_preflight.json`, which the CHECK-IN-1 approval gate (`workflow_state.py approve`) and the `cost-preflight-recorded` invariant require.
