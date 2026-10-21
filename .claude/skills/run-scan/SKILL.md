---
name: run-scan
description: Run the step-8 outer loop — repeat one admitted per-point computation over the axes the request names and assemble the results (limits, fits or predictions) into the declared figures. Use for ANY parameter scan, limit boundary, fit scan or reference comparison over named axes; also for a single-point query against a completed scan (a read, not a run).
when_to_use: the request asks for a quantity over one or more named parameter axes; launching or resuming a scan; asked about a point a completed scan of the same inputs covers
allowed-tools: Bash, Read, Write
---
# Skill — run a scan over named axes

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

Steps 1–7 take one point to its requested quantity; a scan repeats that unit over the axes the
request names (`docs/workflow/steps/08-scan.md` + `docs/workflow/checklists/scan-and-contour.md`
govern; this skill is the operational order). The plan fixes the axes (name, unit, values), the
per-point quantity and statistic, the normalization operations and the figures before CHECK-IN 1.
The dimensionality is the number of axes the request names — one, two or more.

## 0. REUSE before you plan (points are expensive; re-renders are cheap)
A completed scan of the same inputs, axes and per-point quantity (check
`DIRECTORY.md`, the spec's `run_root` for `scan_manifest.json` + assembled `scan.json`) is reused
READ-ONLY: re-run `assemble` and the renderer against it after verifying provenance (coverage
contains your points; any reference matches a fresh fetch). Single-point question + covering scan =
read `scan.json` through its typed status and cite coverage and the normalization basis.

## 1. Cost + disk BEFORE launch
```bash
ravel cost --mode scan --points <N> --parallel <k>
```
Per-point wall time and transient disk come from same-process pilots (`cost-preflight` skill). The
scan states its disk plan before launch. For runs with durable receipts, keep declared inputs and outputs through validation and delivery; deleting or modifying them invalidates reuse and serving. Never compress an artifact in place after its receipt. Use separate stages for transformed products and reduce the grid/concurrency when evidence exceeds the available storage. Archival curation is a separate operation that must explicitly relinquish live replay certification. See `docs/workflow/reference/durable-execution.md`.

## 1b. Validate the varied params BEFORE launch (D10/G12 — `param-validated-before-scan`)
A scan must not SHIP its varied physics until every varied-param/trap obligation is recorded PASS.
Emit the obligations, discharge each with evidence, then GATE the launch on them:
```bash
python3 scripts/run.py ravel.validation.validate_parameters emit   --rundir <scandir> --param <name>:varied
python3 scripts/run.py ravel.validation.validate_parameters record --rundir <scandir> --param <name> --status PASS --evidence "<why>"
python3 scripts/run.py ravel.validation.validate_parameters check  --rundir <scandir> --require-nonempty   # exit 0 REQUIRED before launch
```
`emit` auto-seeds a `trap_obligation` for each gated trap (T3/T6/T7/T8) that `inputs/trap_sweep.json`
hit — record those PASS too. Skipping this makes `validate_run_state.py`'s
`param-validated-before-scan` invariant hard-FAIL the moment `scan.json`/`scan_manifest.json` ships.

## 2. The loop (declarative, resumable, fail-loud)
```bash
CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator plan <spec.json>
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator launch <scandir> --backend native --max 4 --go
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator status <scandir>   # any time; resumable
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator assemble <scandir> [--normalization-contract <contract.json>]
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator rebase <scandir> --transformation <contract.json>  # when the comparison basis changes
```
Apply only the normalization operations the plan lists, in its order, each from its supplied
contract: `assemble --normalization-contract` for a like-for-like correction and `rebase
--transformation` when the comparison basis changes (`docs/reference/cross-section-conventions.md`).
Render the declared figures: `ravel.plotting.scan_contour --plot-spec <plot-spec.json>` for a limit
plane with the layers, references and outputs the plot contract selects, and
`ravel.plotting.parameter_plane` for other declared axes and panels (curves along one axis, planes,
colour maps, references).

Per-point gates run INSIDE the driver (a FAIL stops that point). The spec preserves the requested
parameter domain. Reference comparisons use the reference's own lattice without interpolation.
Outside a published acceptance or efficiency map, do not extrapolate its response: acquire or
generate and qualify the missing per-point inputs through an admitted route. Such points remain
pending until those checks close; they are not automatically uninformative and must not be deleted
from the requested grid. Compare like columns (observed with observed, expected with expected) on
the same model-rate basis; points carrying `quality` bounds render as bounds — never quote
them as resolved values.

## 3. Checkpoint (scans outlive sessions; that is normal)
Maintain `<scandir>/RESUME.md` updated at EVERY launch and check-in: current state, what is
running (pids + log paths), the exact resume commands (`status`/`launch` again — it skips done
points), what remains. After a restart/compaction: re-anchor from `task_contract.json` +
`RESUME.md` + `status`, never from an auto-summary.

**Self-report every ~30 min (G7 mandate).** For any compute expected to exceed ~30 min (a scan or a
native point), schedule a `ScheduleWakeup` every ~30 min running
`python3 scripts/run.py ravel.workflow.progress_reporter --rundir <rundir>` so the run **self-reports**
its one-line progress (`done=k/N running=… failed=… pending=… free=…GB`) WITHOUT a nudge — the non-hook
FALLBACK for the G7 reporter. It is read-only and never gates (exit 0
always); `--json` for the machine form.

## 4. Deliver
Coverage honestly (`n_done`/`n_planned`/`missing_tags` on the figure + RESULT.md); when the plan
declares a reference figure, fulfil the figure contract (attach the counterpart the plot contract selects + compose
the side-by-side — figure-contract skill); the results deck goes out ONLY through the step-9 panel
(verification-panel skill).

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "Every scan is a two-axis plane" | The request names the axes. One axis is a complete scan when one was asked for; a plane collapsed to a line is not. |
| "A bound cell is a strong result; quote it" | Points carrying `quality` bounds are bounds, never resolved values. |
| "Overlay our result on the published one as-is" | Compare like columns on the same model-rate basis; establish the reference's column and basis from its source first. |

## Stop conditions
- Disk projection exceeds free space → shrink the wave (`--max`), clean as you go, or stop.
- A point FAILs its lhe_check/driver stage → diagnose that point; do not launch more wallpaper.
- A requested reference comparison lacks its reference table → inspect official resources,
  preserved caches and a source-labelled digitized reference where appropriate. If no usable
  pointwise comparison exists, that comparison obligation remains unmet. A boundary-only artifact
  is explicitly partial, not a replacement for the requested comparison.

## Live steering before dispatch

Read `ravel gate-wiring steer state --rundir <run>` before each dispatch.
Acknowledge new events with `ravel gate-wiring steer ack <event-id> --rundir <run>
--interpretation <text> [--amended-plan <path>]`. Reconcile requirements and
redirects in the amended plan, then call `dispatch_permitted(run, node_id)`.
A scope increase needs CHECK-IN 1 reapproval even after acknowledgement.
Pause and veto prevent dispatch. Priority orders eligible pending work inside
the existing budget. Preserve earlier results. Research-board posts are advisory
and grant neither steering nor approval.
