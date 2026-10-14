# Step 8 — Scan  ·  [judgment — script-assisted: `scan_orchestrator.py` drives; the axes, normalization and figures are approved at CHECK-IN 1]  · CHECK-IN

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Steps 1–7 take **one parameter point** to its requested quantity (a limit, a fitted value, a
prediction). A scan repeats that unit over a set of points and assembles the results. Run this step
only when the request asks for a scan; its shape comes from the question, not from a fixed layout.

## Derive the scan from the question
Record each of these in the plan before CHECK-IN 1:

- **Axes.** Each scanned parameter by name, unit and values (or range and spacing), taken from the
  request's `scan_axis`, `parameter_range`, `parameter_values` or `parameter_grid` constraints. The
  number of axes is the scan's dimensionality: one axis, two, or more. Parameters held fixed are
  listed with their values.
- **Quantity per point.** The claim the request asks for at each point: an exclusion statistic, a
  fitted value and interval, a significance or a prediction, under the declared statistic.
- **Normalization operations.** The rate, correction and basis changes the selected study inputs
  require, each with its pinned source (`ravel xsec lookup --request request.json` for a published
  rate). List them in order. A scan applies only the operations the plan lists.
- **Comparison.** Whether a supplied reference (a published table, contour or curve) is compared,
  on which lattice, with which metric and tolerance.
- **Figures.** Chosen by dimensionality and quantity: a curve with its band along one axis; a
  plane with the requested boundary (for example the excluded region) and a colour map where requested for
  two axes; slices or tables at declared values for more. `ravel.plotting.parameter_plane` renders
  declared axes, limit curves, grids, colour maps and references from a specification.

**Single-point question against a completed scan.** When a completed scan of the same inputs
covers the point, the answer is a **read, not a run**: read `scan.json` through its typed status
(a resolved value at a lattice point; off-lattice, interpolate between the neighbouring points along
each axis and say so). Cite the scan's coverage (`n_done`/`n_planned`) and its normalization basis.

## Operational — `scan_orchestrator.py` (outer loop)
The request determines the scan dimensionality, dataset population, requested quantities
and presentation. Use the [named scan and card recipe contract](../reference/named-scans.md)
for `scan_orchestrator` planning, status, supervised native proposals and aggregation.
The package ships parameter-free schemas; select model/process/card inputs explicitly.

Before native execution, record cost preflight, a method decision and the actual CHECK-IN 1
approval. Do not turn a dry proposal into authorization. Reuse approved source-bound results
only within their recorded scope. Keep per-point evidence under the declared run tree,
preserve failed attempts and monitor the supervised execution state when resuming.

When a correction or another production basis is requested, supply it explicitly:
`assemble <scandir> --normalization-contract <contract.json>` applies per-point like-for-like
corrections (limits and reference cross sections scale inversely), and
`rebase <scandir> --transformation <contract.json>` maps limits onto another production basis
from complete source and target conventions, component responses and justified approximations.
The [cross-section conventions](../../reference/cross-section-conventions.md) define both
contracts. Cite the scan's coverage and its `normalization` record with every verdict.

Render only the axes, layers and outputs selected by the supplied plot contract
([figure contract](../checklists/figure-contract.md#declarative-scan-plots)):

```bash
python scripts/run.py ravel.plotting.scan_contour \
  --scan <scandir>/scan.json --plot-spec <plot-spec.json> \
  --experiment <experiment> --com <energy-TeV> --lumi <luminosity-fb-inverse>
```

At delivery, report coverage, missing and invalid points, numerical status, uncertainty and
qualification scope for the quantities requested. Supply plot axes, labels, comparison
sources and output names to the applicable renderer. Apply the
[plot criteria](../checklists/plot-criteria.md), [figure contract](../checklists/figure-contract.md),
[scan review checklist](../checklists/scan-and-contour.md) and
[check-ins](../checklists/check-ins.md). A successful renderer or software check does not
certify scientific agreement.

```bash
# 1) PLAN — enumerate the contract's named axes; write each point's run dir and scan_manifest.json
python scripts/run.py ravel.workflow.scan_orchestrator plan <contract.json> [--dry-run]

# 1b) VALIDATE THE VARIED PARAMETERS BEFORE LAUNCH — emit the obligations, record each PASS with
#     evidence, then gate the launch (exit 0 required); validate_run_state.py refuses a shipped scan without it.
python3 scripts/run.py ravel.validation.validate_parameters emit   --rundir <scandir> --param <name>:varied
python3 scripts/run.py ravel.validation.validate_parameters record --rundir <scandir> --param <name> --status PASS --evidence "<why>"
python3 scripts/run.py ravel.validation.validate_parameters check  --rundir <scandir> --require-nonempty

# 2) LAUNCH — persist dry native proposals for approval, then launch after the actual CHECK-IN 1 approval
python scripts/run.py ravel.workflow.scan_orchestrator launch <scandir> --write-plans
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator launch <scandir> --backend native --max 4 --go

# 3) STATUS and 4) ASSEMBLE (add --normalization-contract only when the plan lists that operation)
python scripts/run.py ravel.workflow.scan_orchestrator status <scandir>
python scripts/run.py ravel.workflow.scan_orchestrator assemble <scandir> [--normalization-contract <contract.json>]
```

**Before planning — reuse a completed scan.** Points are expensive; re-assembling and re-rendering
are cheap. Check `DIRECTORY.md` and the spec's `run_root` for an existing
scan of the **same inputs, axes and per-point quantity** carrying a `scan_manifest.json` **and** an
assembled `scan.json`. Reuse it **read-only** after verifying provenance: its coverage contains the
points you need, and any reference it renders against matches a fresh fetch (step 6.4).

**Disk budget + per-point cleanup (mandatory for a parallel scan).** Cost it first —
`python3 scripts/run.py ravel.workflow.cost_preflight --mode scan --points N --parallel 4` —
and note the per-point TRANSIENT disk (LHE+HepMC+Delphes) it reports in `disk_note` × concurrent points: once a point's
result is harvested and validated, remove its transient event files through a separate declared stage
(keep its result files, `config/` and `logs/`; see `docs/workflow/reference/durable-execution.md`).
An uncleaned grid exhausts a laptop disk mid-scan.

**Record the smoke rung before the full scan (D11/G13).** The `none→dry→smoke→full→scan` ladder that
`cost_preflight.py` climbs must leave a record: a `<scandir>/logs/ladder.json` (or `inputs/ladder.json`)
carrying a `rungs[]` entry `{"rung":"smoke","status":"PASS"}` (schema: `schema_version`, `generated_by`,
`rungs[]`). `validate_run_state.py`'s `ladder-order` invariant hard-FAILs a `compute_plan=full|scan` run
that has already reached generation (or ships `scan.json`+`scan_manifest.json`) without that smoke-rung
PASS — the ladder must not be skipped from dry straight to a full scan.

**Keep every point's evidence IN-TREE (N2/G23).** Each `scan_manifest.json` point's `run_dir` (and its
on-disk outputs and `logs/STATUS.txt`) must resolve UNDER the
scan dir or the repo tree — never under `/tmp`, `/private/tmp`, or a session scratchpad.
`validate_run_state.py`'s `outputs-in-tree` invariant hard-FAILs a scan any of whose point evidence (or a
non-scan run's generation output) resolves outside the run/repo tree: such a path is invisible to
`verify_pack.py` / `directory-keeper` / `.gitignore` (they all key on the run dir), so a result assembled
from it rests on evidence that no gate can see and no export can carry. Point each `run_dir` at a
`trial-runs/` sibling (repo-relative or an absolute path under the repo), not a temp dir.

**Checkpoint (multi-hour scans outlive sessions — that is NORMAL).** Maintain
`<scandir>/RESUME.md`, updated at every launch and check-in: state, running pids/log paths, the
exact resume commands (`status` → `launch` again — it skips done points), what remains. After a
restart or context compaction, re-anchor from `task_contract.json` + `RESUME.md` + `status`,
never from an auto-summary.

**Interrupting the dispatcher does not stop its points.** Each launched point is a job in its
own session that outlives the `launch` command by design; an interrupt (Ctrl-C) of the dispatcher
ends the dispatch loop and leaves the points it already started running. To stop them, pause the
scan with steering: each point is bound to the scan when it launches and its process is registered
there, so `ravel gate-wiring steer pause --rundir <scandir>` refuses further points and, under an
`on_pause: cancel` policy, terminates the registered point processes (under `drain` they finish).
`steer state` then reports `requested`, `draining` or `observed-stopped`.

## Compute reality (state it; don't pretend)
Size the scan before launch with `ravel cost --mode scan --points <N> --parallel <k>` and the
`cost-preflight` skill; a point's wall time and transient disk come from same-process pilots, not
from another study. Report coverage explicitly (`scan.json` carries `n_done`/`n_planned`/
`missing_tags`); a result from a partial grid says so. If a point fails from a rare stochastic
crash, re-run it with a different seed; it is an equivalent sample.

**Stage-hang CATCH (G6/D6).** Each native `run_stage` is wrapped by `stage_supervisor.py` — a hung
stage is killed (wall-clock / progress-stall) and the point is FAILED, so it can't silently hold a
scan slot forever. The supervisor writes `logs/<stage>.failure.json` **and** records the open failure
to `run_state.open_failure_records[]` via `workflow_state.py record --kind failure`, so the Stop
CATCH branch — and its `workflow_state.py status` fallback — see the failure at turn-end. That branch
(`stop_dispatch.py` `branch_catch`) walks the rundir at turn-end and **BLOCKS** (exit 2) if any
`logs/*.failure.json` carries a `status` outside `{resolved,handled,closed}` and no truthy `handled` —
so an unresolved stage failure cannot be papered over by simply ending the turn. Its non-hook FALLBACK
is `workflow_state.py status`, which lists those same records under `open_failure_records[]` (populated
by `stage_supervisor.py`'s `record --kind failure` — do **not** assume that list was
filled by anything else). To clear it: on a stage failure, fire the `stage-recovery` skill (RESOLVE/D8 —
diagnose locally AND recipe-search externally CO-PRIMARY, `resource_census.py --debug recipe-search`);
a diagnosed generator-model failure cannot be closed until `inputs/recipe_search.json` exists
(`resource_census.py --assert-recipe-search` must exit 0). Then resolve each failure (diagnose+fix, or
reset the point) and set that record's `"status":"resolved"` **before ending the turn**. If a stage
hangs with **no** supervisor (`STAGE_SUPERVISED=0`, or an old driver), `scan_babysitter.py`'s HEAL loop
(reset FAILED + stale-running points to pending) is the backstop. Its liveness guard matches each
running point's manifest tag, so a live long stage whose status file is idle is protected from a false
stale-heal, while a point that died mid-stage is still reset.

**Long-compute self-report (G7).** For any compute expected to exceed ~30 min (a scan, a native point,
a background sample), schedule a `ScheduleWakeup` every ~30 min running
`python3 scripts/run.py ravel.workflow.progress_reporter --rundir <rundir>` so the run **self-reports**
its one-line progress (`done=k/N running=… failed=… pending=… free=…GB`) without being asked —
this is the non-hook FALLBACK for the G7 reporter. The reporter is
read-only and never gates (exit 0 always): it reads `scan_manifest.json` per-point state
(`output/exclusion.json` = done, `logs/*.failure.json` = failed, `logs/STATUS.txt` last line =
running/pending) or, for a single point, that point's `logs/STATUS.txt`. `--json` for the machine form.

**Phantom-background BLOCK (G5/D5).** A turn must never END by *announcing* a background job it did not
actually launch. The Stop branch `stop_dispatch.py` `branch_phantom` reads the last assistant
message and **BLOCKS** turn-end (exit **2**) when it CLAIMS a job is running (`RUNNING_RE`: "running in
the background", "kicked off", "backgrounded", "now running", "still running", "monitoring the
run/job/scan", "will ping/notify when done", …) **and** no live job is found — no
`run_state.compute_launched[].logfile` whose mtime is within `PHANTOM_WINDOW_SECS=180` s, **and** no
matching pipeline process (`run-pipeline-native`/`mg5_aMC`/`DelphesHepMC`/`scan_orchestrator`/…) naming
this rundir in `ps`. The logfile-mtime is the robust liveness signal: the DRIVE `workflow_state.py
record --kind compute` command writes `logfile` onto the `compute_launched[]` entry (the PostToolUse
observer does **not**) and a genuinely-live job keeps that file fresh; the `ps` scan is a
best-effort backstop for an un-recorded job. FALLBACK (non-hook): **before claiming a job is running,
confirm it** — run `workflow_state.py status` (or point at a live logfile) and only narrate a background
job you actually started via the harness-tracked `run_in_background`. This closes the D5 phantom-
background signature (a turn that ends by reporting a job that was never launched, so nothing ever
finishes and no watchdog ever fires). Clearing it: launch the job for real (and record it), or correct
the claim, then end the turn.

**Watcher-preflight ARM (N3/G24).** A backgrounded *completion-watcher* — a job that sleeps until
SCAN-DONE then FIRES an assembly/aggregation command (e.g. wait-then-assemble the per-point scan) — is
never smoke-tested, so a fire command that is a **3-arg call to a 5-arg script** crashes hours later at
SCAN-DONE, invisibly (nothing ever assembles and no watchdog fires). So **arm any completion-watcher with
`preflight_watcher.py --arm` BEFORE backgrounding it — a fire-command that fails the preflight never gets
armed**: `python3 scripts/run.py ravel.workflow.preflight_watcher --arm --rundir <rundir> --name <watcher>
--fire "<command>" --target <script>` exercises the fire command (`bash -n` syntax **and** an arity probe —
the count of positionals the fire passes vs the target's declared required-positional count, read from an
argparse `--help` usage for a `.py` target or a `$N` scan for a shell target), REFUSES (exit 1) on a bad
fire, and writes `logs/<watcher>.preflight.json` (`schema_version`/`generated_by`/`input_fingerprint`/
`checks`/`verdict`). Only a `verdict=pass` watcher gets backgrounded; the DRIVE step then records the armed
watcher into `run_state.armed_watchers` (via `workflow_state.py`). Read-only except that one artifact,
stdlib-only, fail-loud. **Turn-end enforcement:** `preflight_watcher.py --assert-all --rundir
<rd>` must pass before turn-end — it exits 1 if any `armed_watchers` entry lacks a passing preflight
artifact on disk. The `branch_armed_watcher` branch registered in `stop_dispatch.py` shells it at the Stop
hook (non-invariant → its own branch, not under the D18 umbrella) and BLOCKs the turn (exit 2, token
`G24-ARMED-WATCHER:`) if an armed watcher was never preflighted; the DRIVE step runs the same `--assert-all`
before backgrounding as the fallback.

## Inside the region the inputs support
Scan only where the supplied inputs apply: inside any published acceptance or efficiency map, inside
the kinematically allowed region, and inside the validity range of each correction. A point outside
them is not uninformative by default; it stays pending until its response and statistical inputs are
acquired or generated and qualified through an admitted route. Do not delete it from the requested
grid, and do not extrapolate a published response to reach it.

## CHECK-IN
When the plan declares a reference figure, fulfil the figure contract first
(`docs/workflow/checklists/figure-contract.md`): attach the generated counterpart and compose the
side-by-side:
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target attach-generated \
  --rundir <rundir> --figure-id "<figure id>" --path <selected-counterpart.png> --step 08-scan
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target compose \
  --rundir <rundir> --figure-id "<figure id>"
```
This final check-in takes the **RESULTS DECK** form (`docs/workflow/checklists/check-ins.md`) and is sent only
after the step-9 verification panel (`docs/workflow/steps/09-verify.md`), its verdict + findings appended
verbatim. Lead with the declared figures, each captioned per the caption rule; state coverage
(done/planned points), the normalization operations applied, and the requested quantity over the
scanned axes. With a supplied reference, state the agreement under the declared metric. Confirm
before closing. The scan's headline goes in the scan dir's `RESULT.md`, cross-checked against
`scan.json` (numbers in the prose = numbers in the pack), exactly as a single run's `RESULT.md` is
generated-from `result.json` (step 7).
