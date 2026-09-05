# Adversarial workflow tests

The suite constructs invalid workflow states and checks the expected response
from hooks, validators, and stage supervisors. All 30 registered gate IDs
(`G0a`–`G27`) have a lowercase `cases/case_g*.py` file. Gate IDs in reports retain
their uppercase spelling.

From the repository root, with the development environment active:

```bash
bash scripts/maintenance/install-git-hooks.sh
python3 tests/adversarial/run_suite.py --require-all
```

The hook installer updates this checkout's pre-commit hook. G20 checks both the
installed hook's current implementation path and a staged document's planted
missing reference. Other source-tree failures cannot substitute for that trigger.

Use `--json` for machine-readable results or `--only G13,G16` for a selected
family. `--require-all` retains the complete denominator and fails on a missing
case. Test the aggregator with:

```bash
python3 tests/adversarial/run_suite.py --selftest
```

## Interpreting the board

A case exits 0 when its assertion passes, 1 when the expected behavior fails,
and 2 for a fixture/setup error. Setup errors never count as passes.
`_case_lib.py` supplies temporary run fixtures, package imports, hook drivers,
and subprocess access to the current implementations.

G0a verifies that the recorded SPK-1 probe remains consistently **unproven**;
it does not establish live hook firing. G0b and G0c recheck their recorded probe
artifacts. The fixture records live under `tests/fixtures/hook-probes/`.

G21 attests `self_drive/last_verdict.json`. When that artifact is absent, the
default board reports SKIP. `--with-self-drive` requires the case to run, and an
existing artifact is always checked. A skip is not evidence of agent success.
The separate `clean_room.py --live` command launches an agent and incurs its
runtime costs; the normal board does not run it.

`clean_room.py --replay` evaluates the captured payload's declared file names and
text markers. That bounded transcript check does not independently validate file
bytes, reconstruct event order, or certify a completed physics analysis. The
[prospective evaluation](../../docs/research/2026-09-05-competitive-design-and-validation.md)
requires independent scoring of those stronger claims.

## Case coverage

The table preserves the seeded trigger and expected response for every case.
Unit and integration checks in `tests/unit/test_spine_sim*.py` enforce the exact
30-case set and allow only G21's documented skip.

| Gate | Trigger seeded (bad fixture) | Mechanism (enforcement that FIRES) | Case | GREEN assertion (harness verdict) |
|---|---|---|---|---|
| G0a | the L0 SPK-1 hook-firing artifact `tests/fixtures/hook-probes/spk-1.json`, recorded `verdict=unproven`/`decision=fallback-primary` (this harness could not auth `claude -p` for a full-turn probe) — the case asserts the recorder faithfully re-derives that CONSISTENT recorded-not-PASS (exit 1, NOT a tamper/exit 3); recorder-not-vacuous is separately proven by `spike_probe --selftest`'s seeded-FAIL cases | `spike_probe.py --spike SPK-1 --check` re-reports the RECORDED not-PASS (exit 1) | `case_g0a.py` | case exit 0 = `spike_probe --check` faithfully re-reports the RECORDED not-PASS (exit 1, not a tamper) — honestly unproven-but-attested, never a false PASS |
| G0b | the SPK-2 completion-re-invoke artifact (`verdict=PASS`: an unguessable token round-tripped through the harness `run_in_background` completion channel) | `spike_probe.py --spike SPK-2 --check` re-verifies the recorded PASS (exit 0) | `case_g0b.py` | `case_g0b.py` exits 0 — the gate FIRED |
| G0c | the SPK-3 scheduled-wake artifact (`verdict=PASS`: a de-facto timed wake on the SPK-2 completion re-invoke, fired within tolerance) | `spike_probe.py --spike SPK-3 --check` re-verifies the recorded PASS (exit 0) | `case_g0c.py` | `case_g0c.py` exits 0 — the gate FIRED |
| G1 | a physics prompt (`Initiate: reinterpret ATLAS SUSY-2018-16 …`) driven through `userpromptsubmit-router.sh` | UserPromptSubmit `router` hook injects the INITIATE/route reminder naming `physicist-intake` (additionalContext, exit 0) | `case_g1.py` | `case_g1.py` exits 0 — the gate FIRED |
| G2 | a `scan` task_mode run at the `statistics` step whose `skills_invoked` never records `run-scan` (G2; `08-scan` is not a STAGE_ORDER stage — the run-scan obligation keys on task_mode `scan` at `statistics`) | stop `skill-coverage` branch (exit 2 + `SKILL-COVERAGE`) | `case_g2.py` | `case_g2.py` exits 0 — the gate FIRED |
| G3 | a freshly `init`'d run asked to `advance --to statistics` with nothing generated (resource_census/trap_sweep/figure_contract stages FAIL) | `workflow_state.py advance` REFUSES an out-of-order jump (exit nonzero + unmet preconditions) | `case_g3.py` | `case_g3.py` exits 0 — the gate FIRED |
| G4 | a turn with a `next_required`, no `compute_launched`, no live/recent bg, not a delivery — narrates the next step instead of running it (D4) | stop `drive` branch (exit 2 + `DRIVE`) | `case_g4.py` | `case_g4.py` exits 0 — the gate FIRED |
| G5 | last message claims a background job is running but the liveness probe finds no recent logfile and no matching process (D5-signature) | stop `phantom` branch (exit 2 + `PHANTOM`) | `case_g5.py` | `case_g5.py` exits 0 — the gate FIRED |
| G6 | (a) the wired watchdog selftest seeds a hang→kill→`failure.json`; (b) an unhandled `*.failure.json` under the rundir makes the umbrella refuse turn-end (D6) | (a) `stage_supervisor.py --selftest` kill (exit 0); (b) stop `catch` branch (exit 2 + `CATCH`) | `case_g6.py` | `case_g6.py` exits 0 — the gate FIRED |
| G7 | the wired reporter selftest (the seeded 'long job running' trigger) | `progress_reporter.py --selftest` emits a progress line for a running job (exit 0 + nonempty stdout) | `case_g7.py` | `case_g7.py` exits 0 — the gate FIRED |
| G8 | an OPEN `failure_class=tool_generator_model` record with NO `inputs/recipe_search.json` — `resource_census.py --assert-recipe-search` close-block (D8/D-4, non-invariant branch) | stop `recipe-search` branch (exit 2 + `G8-RECIPE-SEARCH`) | `case_g8.py` | `case_g8.py` exits 0 — the gate FIRED |
| G9 | a `run-pipeline-native.sh trial-runs/<run>` launch whose contract declares `targets.model=SVJ` with NO fetched recipe, driven through `pre-generate-guard.sh` against an isolated `CLAUDE_PROJECT_DIR` (D7) | pre-generate guard hook BLOCKS (exit 2) | `case_g9.py` | `case_g9.py` exits 0 — the gate FIRED |
| G10 | scan run, generation done, PRIMARY figure target declared-at-check-in with a `generated_counterpart` but `side_by_side: null` (D9, primary-aware, all modes) | inv `figure-contract-fulfilled` FAIL | `case_g10.py` | `case_g10.py` exits 0 — the gate FIRED |
| G11 | a CHECK-IN-2 delivery turn whose PRIMARY figure target has `side_by_side: null`, so `validate_run_state.py --rundir` exits nonzero and the umbrella blocks (D5 waypoint) | stop `d18` umbrella (exit 2 + `D18`) | `case_g11.py` | `case_g11.py` exits 0 — the gate FIRED |
| G12 | shipping scan whose `inputs/validations.json` varied-param obligation is still `PENDING` (D10) | inv `param-validated-before-scan` FAIL | `case_g12.py` | `case_g12.py` exits 0 — the gate FIRED |
| G13 | full/scan run that reached generation with NO smoke-rung PASS in `logs/ladder.json` (D11) | inv `ladder-order` FAIL | `case_g13.py` | `case_g13.py` exits 0 — the gate FIRED |
| G14 | scan shipping an exclusion with NO discoverable acc×eff cert (D12; scan.json point attestation does not substitute) | inv `certify-before-limit` FAIL | `case_g14.py` | `case_g14.py` exits 0 — the gate FIRED |
| G15 | T8 trap hit with a `PENDING` (undischarged) `trap_sweep.json` obligation, generation reached (D13) | inv `trap-obligations-discharged` FAIL | `case_g15.py` | `case_g15.py` exits 0 — the gate FIRED |
| G16 | all-zero SR yields → degenerate huge µ95 → `sr_plausibility.json` verdict `implausible` folded by `check_statistics` (D14) | `statistics` stage FAIL | `case_g16.py` | `case_g16.py` exits 0 — the gate FIRED |
| G17 | an Edit to the CHECK-IN-1-baselined `inputs/task_contract.json` with no DEVIATIONS.md row naming it (D15) | edit-time `deviations-guard.sh` PostToolUse hook BLOCKS (exit 2) | `case_g17.py` | `case_g17.py` exits 0 — the gate FIRED |
| G18 | a thin CHECK-IN 1 JSON missing `schema_version`/`kind` (no gallery / numbered flags / waypoint / validations manifest) | `validate_checkin.py` FAILs (exit 1) | `case_g18.py` | `case_g18.py` exits 0 — the gate FIRED |
| G19 | `outputs/sr_plausibility.json` written with NO `generated_by` (its declared inputs present) — the only `LIFECYCLE_REQUIRED_PROVENANCE` artifact (G19) | `validate_run_state.py --verify-provenance` rejects a hand-written required artifact (exit 1, raw non-JSON) | `case_g19.py` | `case_g19.py` exits 0 — the gate FIRED |
| G20 | (a) a staged export tree whose `docs/workflow/x.md` references a nonexistent path; (b) the worktree-resolved `git rev-parse --git-path hooks`/`pre-commit` (D16) | `check_agent_surface.py --stage` FAILs on a dead ref (exit nonzero) + the installed `pre-commit` hook is executable and invokes `check_agent_surface` | `case_g20.py` | `case_g20.py` exits 0 — the gate FIRED |
| G21 | a fresh **un-hinted** `claude` launched from the DSRLab PARENT cwd that fails to route: surveys the dev repo, or never emits `task_contract.json`, or generates before CHECK-IN 1 (D17). Headless `claude -p` is unauthenticated here, so this gate runs **on-demand** (`make green-self-drive`); it is never faked to PASS | self-drive verdict attested PASS — `clean_room.py --live` writes `self_drive/last_verdict.json`, the case `attest`s it (SKIP when absent unless `--with-self-drive`) | `case_g21.py` | case exit 0 = the recorded self-drive verdict == PASS; **SKIP** (never FAIL) when `self_drive/last_verdict.json` is absent and `--with-self-drive` was not passed |
| G22 | a first Skill `new-analysis` (not physicist-intake) with an empty isolated `trial-runs/` (no active-run task_contract.json) (N1) | PreToolUse-on-Skill guard `pretooluse-skill.sh` BLOCKS (exit 2) | `case_g22.py` | `case_g22.py` exits 0 — the gate FIRED |
| G23 | `scan_manifest.json` point whose `run_dir` resolves under `/tmp` (N2, out of the run/repo tree) | inv `outputs-in-tree` FAIL | `case_g23.py` | `case_g23.py` exits 0 — the gate FIRED |
| G24 | a turn-end with an armed watcher whose preflight artifact is missing on disk — `stop_dispatch.py --branch armed-watcher` shells `preflight_watcher.py --assert-all` (N3/D-4) | stop `armed-watcher` branch (exit 2 + `G24-ARMED-WATCHER`) | `case_g24.py` | `case_g24.py` exits 0 — the gate FIRED |
| G25 | a real `.lhe.gz` whose banner `nevents` (3) ≠ its counted `<event>` records (2), Cross-section line present (N4, grabbed mid-write) | inv `producer-complete` FAIL | `case_g25.py` | `case_g25.py` exits 0 — the gate FIRED |
| G26 | a DELIVERY turn-end with an unresolved `open_defect_notes[]` (read_yoda.py) — `stop_dispatch.py --branch open-defect` shells `verify_pack.py`, gated on `is_delivery` (N5/D-4) | stop `open-defect` branch (exit 2 + `G26-OPEN-DEFECT`) | `case_g26.py` | `case_g26.py` exits 0 — the gate FIRED |
| G27 | a `bg_kind=detached` `compute_launched` entry missing `logfile`/`done_condition`/`next_action` and with no live heartbeat (N6) | stop `detach` branch (exit 2 + `DETACH`) | `case_g27.py` | `case_g27.py` exits 0 — the gate FIRED |
