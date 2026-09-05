# Step 8 — Scan → exclusion contour  ·  [judgment — script-assisted: `scan_orchestrator.py` drives; the grid spec itself is approved at CHECK-IN 1]  · CHECK-IN

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Steps 1–7 take **one model point** (a fixed mass spectrum) all the way to **one number**: the 95% CL
upper limit µ₉₅ on its signal strength. That is a complete unit of work — but it is **not** what the
reference paper reports. **mapyde's actual deliverable is a CONTOUR**, produced by scanning a *grid* of
model points and interpolating the µ₉₅ = 1 boundary. This step is the **outer loop** that turns the
per-point pipeline into that contour.

## The mental model — two spaces, do not conflate them
A single run *does* produce a distribution, and it *does* collapse to a single point — in **different
spaces**. Confusing the two is the error this step exists to prevent.

| Space | What lives here | Who produces it |
|---|---|---|
| **kinematic-observable** (m_T2, M_ll, MET, …) | the generated events ARE a distribution; steps 3–4 bin it into signal regions | one pipeline run, *within* a point |
| **model-parameter** (m_parent, m_LSP / Δm) | one run = **one point**, collapsing to **one µ₉₅** (excluded iff µ₉₅ < 1) | one pipeline run = one lattice site |

So: *"shouldn't we see a distribution?"* — **yes, in the kinematic space**, and the pipeline is needed
precisely to turn that per-event distribution into per-SR yields → µ₉₅. *"isn't it just a single
point?"* — **yes, in the mass space**, one run is one site. The **headline figure is the contour over
the grid of sites**, not any single site. A run on its own answers "is *this one* spectrum excluded?";
the scan answers "**what region** of the mass plane is excluded?" — which is the published result.

## Why a scan, not a point (and when you'd skip the pipeline entirely)
For a model ATLAS **already published**, the published exclusion contour *already answers* any single
point — you could read the verdict off their figure with no pipeline at all. The harness earns its keep
in exactly two modes, **both of which are scans**:

- **Reproduction (validation).** Re-derive ATLAS's *own* published contour with our pipeline and show
  they agree — this is what certifies the tool. RRR: *"we generate a grid of Higgsino model points to
  reproduce the ATLAS results … the mapyde exclusion contour follows the corresponding ATLAS contour"*
  (§3.3). The validation figure is the **relative difference of the limits**, *"the relative difference
  in the limits on the SUSY signal strength µ_SUSY, between mapyde and ATLAS results"* (Fig 3/8 caption).
- **Reinterpretation (the product).** Scan a model ATLAS **never considered** (e.g. slepton-wino-bino,
  §3.2; a pMSSM slice, §3.4) — **no published contour exists**, so our scanned contour *is* the new
  scientific result.

A single-point run is a **unit within a scan** or a **sanity check** (e.g. `mass_plane_overlay.py`
locating one tested point on someone else's published contour). It is never the deliverable.

**Single-point query from a completed scan.** When the question is "is (m, Δm) excluded?" and a
completed scan of the same analysis+model already covers that point, the verdict is a **read, not a
run**: read the scan's `scan.json` — `mu95_obs` at the lattice point (excluded iff <1), or, off-lattice,
interpolate the excluded-Δm reach (where µ₉₅ crosses 1) at that mass from the neighbouring lattice
points. Always cite the scan's coverage (`n_done`/`n_planned`) and its σ normalization (e.g. whether the
NLO+NLL renorm was applied — `nlo_renorm` in `scan.json`) alongside the verdict. To show the point,
`mass_plane_overlay.py --plane dm` locates it against the published contour — NOTE: on the dm plane its
`--point` is `m,Delta_m` (not `m_parent,m_lsp`).

## The deliverable IS a 2-D contour vs the PUBLISHED ATLAS contour (not a 1-D line)
RRR Fig 3 is a **2-D mass plane** (m(parent) × Δm) with TWO things: (a) the mapyde 95% CL exclusion
**contour overlaid on ATLAS's PUBLISHED contour**, and (b) a **color map of the relative difference
(mapyde−ATLAS)/ATLAS** in the signal-strength limit — *that difference map is the paper's figure of
merit.* So the scan target is a **2-D grid** (`grid:` spec), the published ATLAS contour fetched in
step 6 (`docs/workflow/checklists/data-acquisition.md` §exclusion-contour), and the two-panel render below. A 1-D Δm
**line** at one mass is an honest **partial PoC**, NOT the deliverable — label it as such.

## Operational — `scan_orchestrator.py` (outer loop) → `scan_contour.py` (renderer)
The scan is declarative, resumable, fail-loud. One grid spec JSON drives it; each point gets its own run
dir + mass-substituted TOML (keyed line edit, not a greedy sed — `.claude/rules/madgraph-pythia.md`),
runs the full pipeline, and emits `exclusion.json` (native backend) / `result.json` (container) that the
orchestrator harvests. **Two backends; native is the default and is what you want locally:**
- **`--backend native` (DEFAULT)** → `run-pipeline-native.sh` (VM-FREE, all native conda envs). For each
  point the orchestrator runs `prepare_native_slepton.py` (materializes the point's cards/`run.mg5`/
  `shower.cfg` from its masses) then the native driver. Native points share **no VM / no fixed container
  names**, so they run **in PARALLEL** (`--max` sets concurrency) and a full-chain point is **~30–50 min**, not hours.
  Scope today: the native SimpleAnalysis is slepton-bino / EwkCompressed2018-specific (see
  `docs/workflow/reference/native-pipeline.md`).
- **`--backend container`** → `run-pipeline.sh` (mapyde in the podman VM, x86 under emulation). The
  legacy path: ~9 h/point AND strictly **sequential** (shared VM + fixed container names — a concurrent
  launch clobbers the in-flight point), so it refuses while any point runs. Use only if native is
  unavailable for your analysis.

**Before planning — reuse a completed scan.** Points are expensive; re-assembling and re-rendering
are cheap. Before planning a new scan, check `docs/development/status.md`, `DIRECTORY.md`, and the spec's
`run_root` for an existing scan dir of the **same analysis + model + grid** carrying a
`scan_manifest.json` **and** an assembled `scan.json`. If one exists, reuse it **read-only** — run
`assemble`/`scan_contour.py` against it rather than re-running points — after verifying its
provenance: `scan.json`'s `n_done`/`n_planned` cover the grid you need, and the ATLAS reference
yamls it renders against match a freshly fetched copy (step 6.4). Plan a fresh scan only when no
such scan exists or its provenance fails these checks.

**Disk budget + per-point cleanup (mandatory for a parallel scan).** Cost it first —
`python3 scripts/run.py ravel.workflow.cost_preflight --mode scan --points N --parallel 4` —
and note the ~6 GB/point TRANSIENT (LHE+HepMC+Delphes) × concurrent points: once a point's
`output/exclusion.json` is harvested, delete/gzip its LHE + HepMC + Delphes root (keep the
curated set: `exclusion.json`/`.txt`/`_patch.json`/`exclusion.png` + `config/` + `logs/`).
An uncleaned grid exhausts a laptop disk mid-scan.

**Record the smoke rung before the full scan (D11/G13).** The `none→dry→smoke→full→scan` ladder that
`cost_preflight.py` climbs must leave a record: a `<scandir>/logs/ladder.json` (or `inputs/ladder.json`)
carrying a `rungs[]` entry `{"rung":"smoke","status":"PASS"}` (schema: `schema_version`, `generated_by`,
`rungs[]`). `validate_run_state.py`'s `ladder-order` invariant hard-FAILs a `compute_plan=full|scan` run
that has already reached generation (or ships `scan.json`+`scan_manifest.json`) without that smoke-rung
PASS — the ladder must not be skipped from dry straight to a full scan.

**Keep every point's evidence IN-TREE (N2/G23).** Each `scan_manifest.json` point's `run_dir` (and its
on-disk `output/exclusion.json` / `output/sr_yields.json` / `logs/STATUS.txt`) must resolve UNDER the
scan dir or the repo tree — never under `/tmp`, `/private/tmp`, or a session scratchpad.
`validate_run_state.py`'s `outputs-in-tree` invariant hard-FAILs a scan any of whose point evidence (or a
non-scan run's generation output) resolves outside the run/repo tree: such a path is invisible to
`verify_pack.py` / `directory-keeper` / `.gitignore` (they all key on the run dir), so a limit assembled
from it rests on evidence that no gate can see and no export can carry. Point each `run_dir` at a
`trial-runs/` sibling (repo-relative or an absolute path under the repo), not a temp dir.

**Checkpoint (multi-hour scans outlive sessions — that is NORMAL, charter §4c).** Maintain
`<scandir>/RESUME.md`, updated at every launch and check-in: state, running pids/log paths, the
exact resume commands (`status` → `launch` again — it skips done points), what remains. After a
restart or context compaction, re-anchor from `task_contract.json` + `RESUME.md` + `status`,
never from an auto-summary.

```bash
# 1) PLAN — enumerate the grid; write each point's run-dir + TOML; write scan_manifest.json
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator plan <spec.json>

# 1b) VALIDATE THE VARIED PARAMS BEFORE LAUNCH (D10/G12) — emit the obligations, record each PASS with
#    evidence, then GATE the launch (exit 0 REQUIRED). emit auto-seeds a trap_obligation for each gated
#    trap (T3/T6/T7/T8) that inputs/trap_sweep.json hit — record those PASS too. Skipping this makes
#    validate_run_state.py's param-validated-before-scan invariant hard-FAIL once scan.json/scan_manifest ships.
python3 scripts/run.py ravel.validation.validate_parameters emit   --rundir <scandir> --param <name>:varied
python3 scripts/run.py ravel.validation.validate_parameters record --rundir <scandir> --param <name> --status PASS --evidence "<why>"
python3 scripts/run.py ravel.validation.validate_parameters check  --rundir <scandir> --require-nonempty

# 2) LAUNCH — native is the default; --max N runs N points in parallel (container backend is sequential)
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator launch <scandir> --backend native --max 4 --go

# 3) STATUS — per-point done/running/failed/pending (re-run any time; resumable)
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator status <scandir>

# 4) ASSEMBLE — harvest each done point's exclusion.json/result.json → scan.json (+ coverage).
#    Add --nlo-renorm slepton to re-normalize the limits from the sample's flat LO k-factor to the
#    per-mass NLO+NLL k(m) (what ATLAS/RRR normalize to) POST-HOC — no regeneration: µ′₉₅=µ₉₅×flat_k/k(m),
#    per point it stores mu95_obs_lo/k_nlo and scales sigma_ref_fb inversely so σ_UL=µ₉₅×σ_ref (the
#    difference map's input) is INVARIANT — only the µ₉₅=1 contour moves. Fails loud if k is
#    unavailable or unphysical (like-for-like rule: .claude/rules/statistics.md). Back up scan.json
#    first if you want to keep the LO assembly (convention: scan_lo.json).
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator assemble <scandir> [--nlo-renorm slepton]

# 4b) REBASE — REQUIRED before comparing against the experiment's per-point UL grid (--atlas-limit).
#    THE COMPARISON-BASIS RULE: a σ-UL comparison is only meaningful on the SAME model-σ basis
#    (compare µ limits like RRR — both sides ÷ the same σ_model^NLO+NLL). assemble's sigma_ref_fb is
#    the SAMPLE σ (the ISR-tagged subset from the MadGraph log, incl. any extra states like τ̃); the
#    published UL grid is on the INCLUSIVE simplified-model σ — different, mass-dependently tilted
#    bases (slepton: ×0.56 at m=50 → ×1.01 at m=300). rebase maps the basis-free event-count UL onto
#    the model σ (µ → µ_SUSY; sigma_ref_fb := σ_model^WG) using the local reference tables
#    slepton_incl4_lo_cteq6l1.json + slepton_flavLR_nlonll_pdf4lhc15.json; scan_contour warns loudly
#    if a scan without model_basis is rendered against --atlas-limit. Details: cmd_rebase docstring +
#    docs/workflow/checklists/scan-and-contour.md (Normalization).
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator rebase <scandir> --process slepton

# 5) RENDER — scan.json → the contour-vs-ATLAS + the (mapyde−ATLAS)/ATLAS difference map (the deliverable)
#    --atlas-contour is repeatable (ROLE=PATH; ROLE ∈ observed/expected/…): when the published figure
#    shows BOTH contours, pass both — observed draws solid, expected draws dashed, as published.
$CONDA run -n rivet python scripts/run.py ravel.plotting.scan_contour \
  --scan <scandir>/scan.json --experiment ATLAS --com 13 --lumi 139 \
  --atlas-contour observed=<hepdata_obs_contour>.yaml \
  --atlas-contour expected=<hepdata_exp_contour>.yaml \
  --atlas-limit <hepdata_perpoint_UL>.yaml \
  --out <scandir>/plots/<name>__contour
#   With BOTH --atlas-contour AND --atlas-limit on a 2-D grid, the HEADLINE artifacts are
#   <out>__fig3.{png,pdf} (observed) and <out>__fig3_expected.{png,pdf} — RRR Fig 3's actual FORM
#   in ONE panel: the (mapyde−ATLAS)/ATLAS rel-diff color map as the fill + the ATLAS published
#   contour + the Ravel µ₉₅=1 contour (piecewise linear, missing-vertex triangles masked) on the log-Δm plane
#   convention (plot-guidelines.md). --limit-kind picks the variant(s) (default both; LIKE-COLUMNS
#   rule — mu95_obs vs Observed, mu95_exp vs Expected, including matching contour roles).
#   Pin the paper figure's role from primary data; dot styling does not identify it.
#   The fill colors ONLY exact (tolerance-snapped) matches to the published
#   grid — the reference is NEVER interpolated; scanned cells without a published point are white +
#   gray circle (stated on the figure), unscanned cells are holes (checklist: scan-and-contour.md).
#   The GRID two-panel outputs (scatter+tricontour; __reldiff) are still written as diagnostics;
#   LINE layout (1-D) is the partial-PoC fallback. 95% CL exclusion, never a discovery.
```

The grid spec — make it a **`grid`** (2-D) for the deliverable; `line`/`points` are the partial-PoC forms.
A ready example is `benchmarks/specs/slepton-bino-figure-3-coarse.json`:
```json
{ "name": "slepton-bino-fig3-coarse", "model": "slepton-bino", "analysis_id": "ins1767649",
  "template_toml": "src/ravel/data/templates/slepton_scan_template.toml",
  "subst": {"MSLEP": "m_parent", "MN1": "m_lsp"}, "plane": "dm",
  "run_root": "trial-runs", "run_prefix": "sleptonscan_fig3",
  "grid": {"m_parent": [150,200,250], "dm": [5,10,20,30]} }
```

## Compute reality (state it; don't pretend)
**Native** (the default): a **full-chain** point is **~30–50 min** wall (native MadGraph ~7–8 min/50k +
Pythia shower + Delphes + native SimpleAnalysis + pyhf — measured ≈49 min for a 20k-event point), and
points run **in parallel** (`--max`) — so a coarse 2-D grid (≈12–18 points) is **hours**, not days, on this laptop.
**Container** (legacy): ~9 h/point, sequential → a dense grid is days and belongs on a cluster. Either way,
report coverage explicitly (`scan.json` carries `n_done`/`n_planned`/`missing_tags`); a contour from a
partial grid must say so. (Native MC re-seeds a point on a rare per-event Delphes segfault — re-run that
point with a different seed; it is an equivalent sample.)

**Stage-hang CATCH (G6/D6).** Each native `run_stage` is wrapped by `stage_supervisor.py` — a hung
stage is killed (wall-clock / progress-stall) and the point is FAILED, so it can't silently hold a
scan slot forever. The supervisor writes `logs/<stage>.failure.json` **and** records the open failure
to `run_state.open_failure_records[]` via `workflow_state.py record --kind failure` (D-3), so the Stop
CATCH branch — and its `workflow_state.py status` fallback — see the failure at turn-end. That branch
(`stop_dispatch.py` `branch_catch`, CR-062) walks the rundir at turn-end and **BLOCKS** (exit 2) if any
`logs/*.failure.json` carries a `status` outside `{resolved,handled,closed}` and no truthy `handled` —
so an unresolved stage failure cannot be papered over by simply ending the turn. Its non-hook FALLBACK
is `workflow_state.py status`, which lists those same records under `open_failure_records[]` (populated
by `stage_supervisor.py`'s `record --kind failure`, Task 2.1 / D-3 — do **not** assume that list was
filled by anything else). To clear it: on a stage failure, fire the `stage-recovery` skill (RESOLVE/D8 —
diagnose locally AND recipe-search externally CO-PRIMARY, `resource_census.py --debug recipe-search`);
a diagnosed generator-model failure cannot be closed until `inputs/recipe_search.json` exists
(`resource_census.py --assert-recipe-search` must exit 0). Then resolve each failure (diagnose+fix, or
reset the point) and set that record's `"status":"resolved"` **before ending the turn**. If a stage
hangs with **no** supervisor (`STAGE_SUPERVISED=0`, or an old driver), `scan_babysitter.py`'s HEAL loop
(reset FAILED + stale-running points to pending) is the backstop. That HEAL loop's liveness guard is now
**real** (CR-059): `live_points()` returns each running point's short manifest tag (`m<..>_dm<..>`, incl.
a fractional `dm2p5`), so the `tag not in live` stale-heal conjunct actually fires — a genuinely-live
30–50 min MadGraph stage (its STATUS.txt mtime frozen while it works) is **protected** from a false
stale-heal, while a died-mid-stage point (no live proc + stale STATUS) is still reset. Previously the
guard yielded only the full run-token tag and the short-tag regex rejected the `p` in a decimal Δm, so
`tag not in live` was always-true and the mtime alone decided — a slow-but-alive point could be reset
out from under itself.

**Long-compute self-report (G7).** For any compute expected to exceed ~30 min (a scan, a native point,
a background sample), schedule a `ScheduleWakeup` every ~30 min running
`python3 scripts/run.py ravel.workflow.progress_reporter --rundir <rundir>` so the run **self-reports**
its one-line progress (`done=k/N running=… failed=… pending=… free=…GB`) WITHOUT a physicist nudge —
this is the non-hook FALLBACK for the G7 reporter (the abandoned-ScheduleWakeup fix). The reporter is
read-only and never gates (exit 0 always): it reads `scan_manifest.json` per-point state
(`output/exclusion.json` = done, `logs/*.failure.json` = failed, `logs/STATUS.txt` last line =
running/pending) or, for a single point, that point's `logs/STATUS.txt`. `--json` for the machine form.

**Phantom-background BLOCK (G5/D5).** A turn must never END by *announcing* a background job it did not
actually launch. The Stop branch `stop_dispatch.py` `branch_phantom` (CR-063) reads the last assistant
message and **BLOCKS** turn-end (exit **2**) when it CLAIMS a job is running (`RUNNING_RE`: "running in
the background", "kicked off", "backgrounded", "now running", "still running", "monitoring the
run/job/scan", "will ping/notify when done", …) **and** no live job is found — no
`run_state.compute_launched[].logfile` whose mtime is within `PHANTOM_WINDOW_SECS=180` s, **and** no
matching pipeline process (`run-pipeline-native`/`mg5_aMC`/`DelphesHepMC`/`scan_orchestrator`/…) naming
this rundir in `ps`. The logfile-mtime is the robust liveness signal: the DRIVE `workflow_state.py
record --kind compute` command writes `logfile` onto the `compute_launched[]` entry (the PostToolUse
observer does **not**, per D-2) and a genuinely-live job keeps that file fresh; the `ps` scan is a
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
stdlib-only, fail-loud. **Turn-end enforcement (N3/G24, D-4):** `preflight_watcher.py --assert-all --rundir
<rd>` must pass before turn-end — it exits 1 if any `armed_watchers` entry lacks a passing preflight
artifact on disk. The `branch_armed_watcher` branch registered in `stop_dispatch.py` shells it at the Stop
hook (non-invariant → its own branch, not under the D18 umbrella) and BLOCKs the turn (exit 2, token
`G24-ARMED-WATCHER:`) if an armed watcher was never preflighted; the DRIVE step runs the same `--assert-all`
before backgrounding as the fallback.

## On-grid only — the off-grid trap
Scan **inside** the published acc×eff grid and the kinematically-sensible region. The slepton-bino
search has a **maximum Δm** beyond which the soft leptons fall below efficiency (RRR §3.2: *"the contour
is prevented from covering arbitrarily small values of Δm … such models produce softer SM leptons"*; and
an upper bound likewise). A point like (200, Δm=50) sits **above** the published reach and is
uninformative, and a point of this kind has been retracted on exactly this basis before. The
on-grid reproduction line lives at Δm ≈ 5–40 GeV.

## CHECK-IN
Fulfil the figure contract first (`docs/workflow/checklists/figure-contract.md`): the scan contour IS the generated
counterpart of the declared published figure — attach it and compose the side-by-side:
```bash
# When the DECLARED figure is the analysis's own exclusion contour, attach the __fig3 output —
# the single-panel log-Δm compressed-plane form that matches the published convention — NOT the
# __contour grid diagnostic:
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target attach-generated \
  --rundir <rundir> --figure-id "Figure <N>" --path <scandir>/plots/<name>__contour__fig3.png --step 08-scan
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target compose \
  --rundir <rundir> --figure-id "Figure <N>"     # published | this-pipeline side-by-side PNG
```
This final check-in takes the **RESULTS DECK** form (`docs/workflow/checklists/check-ins.md`) and is sent only
after the step-9 verification panel (`docs/workflow/steps/09-verify.md`), its verdict + findings appended
verbatim. The deck's headline is the **side-by-side** (published figure left, our contour right —
or the generated figure under its textual-reference banner when no image was extracted) and the
contour (or the line slice + excluded-Δm interval), each captioned per the caption rule; state
coverage (done/planned points), and for a **reproduction** state the agreement with the ATLAS
contour (the relative-difference read); for a **reinterpretation** state the newly-excluded region.
Confirm before closing. The scan's headline goes in the scan dir's `RESULT.md`, cross-checked
against `scan.json` (numbers in the prose = numbers in the pack), exactly as a single run's
`RESULT.md` is generated-from `result.json` (step 7).
