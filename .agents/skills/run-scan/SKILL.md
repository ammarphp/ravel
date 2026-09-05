---
name: run-scan
description: Run the step-8 outer loop in hep-agentic-pipeline — a grid of model points through the native pipeline to the µ95=1 exclusion contour vs the published ATLAS/CMS contour. Use for ANY mass-plane scan, reproduction contour, or reinterpretation region; also for a single-point query against a completed scan (a read, not a run).
when_to_use: producing an exclusion contour / difference map; launching or resuming a grid scan; asked whether a model point is excluded when a scan of that analysis+model exists
allowed-tools: Bash, Read, Write
---
# Skill — run a scan (grid → contour; the deliverable, not a point)

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.

Steps 1–7 take one point to one µ₉₅; the PRODUCT is the step-8 contour
(`docs/workflow/steps/08-scan.md` + `docs/workflow/checklists/scan-and-contour.md` govern; this skill is the
operational order). A 1-D line is a declared partial PoC, never the deliverable (catalogue D1).

## 0. REUSE before you plan (points are expensive; re-renders are cheap)
A completed scan of the same analysis+model+grid (check `docs/development/status.md`, `DIRECTORY.md`,
the spec's `run_root` for `scan_manifest.json` + assembled `scan.json`) is reused READ-ONLY:
re-run `assemble`/`scan_contour.py` against it after verifying provenance (coverage covers your
grid; the ATLAS reference yamls match a fresh fetch). Single-point question + covering scan =
read `scan.json` (`mu95_obs<1` ⇒ excluded), cite coverage + σ basis; `mass_plane_overlay.py
--plane dm` to show it (its `--point` is `m,Delta_m` there).

## 1. Cost + disk BEFORE launch
```bash
python3 scripts/run.py ravel.workflow.cost_preflight --mode scan --points <N> --parallel 4
```
Native: ~30–50 min/point, parallel; **~6 GB/point transient**. The scan must state its disk
plan: after each point's harvest (`output/exclusion.json` exists), delete/gzip its LHE + HepMC
+ Delphes root (keep `exclusion.json`/`.txt`/`_patch.json`/`exclusion.png` + `config/` — the
curated trio). A full grid left uncleaned exhausts a laptop disk mid-scan.

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
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator assemble <scandir> --nlo-renorm <process>
$CONDA run -n rivet python scripts/run.py ravel.workflow.scan_orchestrator rebase <scandir> --process <process>  # REQUIRED before --atlas-limit
$CONDA run -n rivet python scripts/run.py ravel.plotting.scan_contour --scan <scandir>/scan.json \
  --experiment ATLAS --com 13 --lumi <L> --atlas-contour observed=<obs>.yaml \
  --atlas-contour expected=<exp>.yaml --atlas-limit <UL_grid>.yaml --out <scandir>/plots/<name>__contour
```
Per-point gates run INSIDE the driver (lhe_check stage 1b — a FAIL stops that point). Grid
spec: 2-D `grid`, ON the published lattice (never interpolate the reference), inside the
published acc×eff region (off-grid points are refused — one has been retracted before).
Normalization order is binding: assemble `--nlo-renorm` (per-mass k) THEN `rebase` (model-σ
basis) THEN render; LIKE-COLUMNS (obs-vs-obs / exp-vs-exp); floored/capped points carry
`quality` tags and render as '×' bounds (CR-001) — never quote them as limits.

## 3. Checkpoint (charter §4c — scans outlive sessions; that is normal)
Maintain `<scandir>/RESUME.md` updated at EVERY launch and check-in: current state, what is
running (pids + log paths), the exact resume commands (`status`/`launch` again — it skips done
points), what remains. After a restart/compaction: re-anchor from `task_contract.json` +
`RESUME.md` + `status`, never from an auto-summary.

**Self-report every ~30 min (G7 mandate).** For any compute expected to exceed ~30 min (a scan or a
native point), schedule a `ScheduleWakeup` every ~30 min running
`python3 scripts/run.py ravel.workflow.progress_reporter --rundir <rundir>` so the run **self-reports**
its one-line progress (`done=k/N running=… failed=… pending=… free=…GB`) WITHOUT a nudge — the non-hook
FALLBACK for the G7 reporter (the abandoned-ScheduleWakeup fix). It is read-only and never gates (exit 0
always); `--json` for the machine form.

## 4. Deliver
Coverage honestly (`n_done`/`n_planned`/`missing_tags` on the figure + RESULT.md); fulfil the
figure contract (attach `__fig3` + compose the side-by-side — figure-contract skill); the
results deck goes out ONLY through the step-9 panel (verification-panel skill).

## Red flags (you are rationalizing — stop)
| Thought | Reality |
|---|---|
| "A single point / a 1-D Δm line will do for now" | Catalogue D1: sessions repeatedly collapsed the deliverable, and one stale checklist line kept reinstalling it — the product is the 2-D contour. |
| "Dark-red diff cell = huge exclusion; quote it" | Catalogue B1: those were floored `obs_limit=1.0` points — bounds rendered as '×', never limits. |
| "Overlay our observed on the published dots as-is" | Catalogue A3+A4: the dots decoded to the EXPECTED column and the σ basis tilted ×0.56→×1.01. Like-columns + `rebase` are mandatory, not polish. |

## Stop conditions
- Disk projection exceeds free space → shrink the wave (`--max`), clean as you go, or stop.
- A point FAILs its lhe_check/driver stage → diagnose that point; do not launch more wallpaper.
- Reference tables missing (no `--atlas-limit` counterpart) → the diff map is impossible;
  deliver the contour-only form and SAY SO.
