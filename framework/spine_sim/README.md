# `framework/spine_sim/` — the L6 per-gate verification board

`run_spine_sim.py` is the level-6 verification board for the workflow-adherence spine: for every gate
(`G0a`–`G27`) a sibling `cases/case_<G>.py` script seeds a throwaway fixture that trips the gate's
trigger and asserts the matching gate FIRES (exit 0 = fired/PASS · 1 = did-not-fire/FAIL · 2 =
setup/ERROR). The engine discovers those case scripts, runs each as a subprocess from the repo root,
and prints one board row per gate. Run the whole board with
`python3 framework/spine_sim/run_spine_sim.py --require-all` (or `make green`) — `--require-all` also
fails if any expected gate has no case file yet, so an unwritten case is a coverage FAIL, not a silent
hole. Prove the aggregator itself with `--selftest`; the self-drive gate (`G21`, which attests the live
`clean_room.py --live` artifact) is SKIPped when that artifact is absent unless `--with-self-drive` is
passed (`make green-self-drive`). The `cases/` dir is filled one gate at a time by the 6.x family tasks.

**Case toolkit (`_case_lib.py`).** Every `cases/case_<G>.py` imports the shared, stdlib-only
`_case_lib.py`: throwaway rundir/session fixtures (`tempdir`, `write_json`/`write_text`,
`write_contract` built from `validate_run_state._base_contract` so it always validates, `write_run_state`),
subprocess drivers for the hooks and infra tools (`run_validate` + `invariant_status`/`stage_status`,
`run_tool`/`tool_path`, `drive_hook`/`drive_stop`, the `HOOKS`/`STOP_TOKENS` relpath maps so a moved
hook touches one line), attestation helpers (`spike_check`, `attest`), and the gate-assertion discipline
(`case_main` → exit 0 fired / 1 did-not-fire / 2 setup-error, `gate_fired`, `assert_block`, and the
`CaseSetupError`/`GateDidNotFire` exceptions). It is tested (`tests/test_spine_sim_caselib.py`) against
only REAL on-disk infra, so the toolkit is green independent of any unbuilt enforcement phase.

## Case coverage (filled one gate at a time by the 6.x family)

Each row is a `cases/case_<G>.py` script that seeds the bad fixture in the last column and asserts the
named enforcement FIRES. The **invariant-family** cases (Task 6.3) drive the REAL Phase 3/4
`validate_run_state.py` invariants/stages; the **Stop-dispatch + watchdog family** (Task 6.4) drive the
REAL Phase 2 `stop_dispatch.py` branches (each `drive_stop`'s a fixture at one `--branch` and asserts
exit 2 + the branch's `STOP_TOKENS` token) plus the `stage_supervisor.py --selftest` hang→kill watchdog.
The **hook + tool family** (Task 6.5) is the third integration lane: it drives the Phase-0 `spike_probe.py`
spike re-checks (G0a–G0c), the Phase-1/2/3/4 hook SCRIPTS directly with a crafted stdin JSON (G1 router,
G9 pre-generate guard, G17 deviations guard, G22 PreToolUse-Skill guard — asserting the hook's exit + its
message, the direct-drive per the SPK-1 auth finding, not a live turn), the wired infra tools
(`workflow_state.py advance`/G3, `progress_reporter.py --selftest`/G7, `validate_checkin.py`/G18,
`validate_run_state.py --verify-provenance`/G19, `check_agent_surface.py --stage` + the worktree-resolved
`pre-commit` hook/G20), and the two D-4 NON-invariant Stop branches (`armed-watcher`/G24, `open-defect`/G26).
All three are the integration lane — they go green only once those instruments are on disk.

**The self-drive lane (Task 6.6, `clean_room.py` — the D17 clean-room proof).** `clean_room.py` builds
an *un-hinted* launch command (`build_launch_cmd` → `claude -p` from the DSRLab **PARENT** cwd with
`--setting-sources user` + `--strict-mcp-config`, so the project `CLAUDE.md`/settings do **not**
auto-load — the parent-cwd routing gap D17 exists to close) and scores the resulting
`--output-format json` transcript with the PURE `evaluate_transcript` verdict engine: PASS iff a valid
`task_contract.json` was emitted **and** CHECK-IN 1 (optionally CHECK-IN 2, `--checkin 2`) was reached
**and** no dev-repo survey preceded the route **and** no generation preceded the go-ahead. Because a
live run is slow/costed/non-deterministic — and because headless `claude -p` is **NOT authenticated in
this environment** (EXECUTION ADJUSTMENT / the SPK-1 auth finding) — the deterministic core is
`--replay <captured payload.json>` and `--selftest` (what `tests/test_clean_room.py` drives); `--live`
shells the real launcher and records `self_drive/last_verdict.json` on a host where `claude` IS
authenticated (or an authenticated in-harness subagent supplies the captured transcript, scored via
`--replay`). `case_G21.py` ATTESTS that recorded verdict == PASS; with the artifact **absent** the
engine SKIPs G21 (`make green` stays green) and `--with-self-drive` / `make green-self-drive` forces
it — the gate runs **on-demand** and is **never faked** to PASS.

The completeness gate `framework/tests/test_spine_sim_complete.py` asserts this table is EXHAUSTIVE: every one of the 30 `EXPECTED_GATES` (G0a-G27) has a `cases/case_<G>.py` script AND `run_spine_sim.py --require-all` is green. GREEN = the case process exits 0 (the gate FIRED); G21 is SKIP (never FAIL) until `make green-self-drive` records the live verdict; G0a is honestly attested unproven-but-consistent (never a false PASS).

| Gate | Trigger seeded (bad fixture) | Mechanism (enforcement that FIRES) | Case | GREEN assertion (harness verdict) |
|---|---|---|---|---|
| G0a | the L0 SPK-1 hook-firing artifact `framework/spine/spikes/SPK-1.json`, recorded `verdict=unproven`/`decision=fallback-primary` (this harness could not auth `claude -p` for a full-turn probe) — the case asserts the recorder faithfully re-derives that CONSISTENT recorded-not-PASS (exit 1, NOT a tamper/exit 3); recorder-not-vacuous is separately proven by `spike_probe --selftest`'s seeded-FAIL cases | `spike_probe.py --spike SPK-1 --check` re-reports the RECORDED not-PASS (exit 1) | `case_G0a.py` | case exit 0 = `spike_probe --check` faithfully re-reports the RECORDED not-PASS (exit 1, not a tamper) — honestly unproven-but-attested, never a false PASS |
| G0b | the SPK-2 completion-re-invoke artifact (`verdict=PASS`: an unguessable token round-tripped through the harness `run_in_background` completion channel) | `spike_probe.py --spike SPK-2 --check` re-verifies the recorded PASS (exit 0) | `case_G0b.py` | `case_G0b.py` exits 0 — the gate FIRED |
| G0c | the SPK-3 scheduled-wake artifact (`verdict=PASS`: a de-facto timed wake on the SPK-2 completion re-invoke, fired within tolerance) | `spike_probe.py --spike SPK-3 --check` re-verifies the recorded PASS (exit 0) | `case_G0c.py` | `case_G0c.py` exits 0 — the gate FIRED |
| G1 | a physics prompt (`Initiate: reinterpret ATLAS SUSY-2018-16 …`) driven through `userpromptsubmit-router.sh` | UserPromptSubmit `router` hook injects the INITIATE/route reminder naming `physicist-intake` (additionalContext, exit 0) | `case_G1.py` | `case_G1.py` exits 0 — the gate FIRED |
| G2 | a `scan` task_mode run at the `statistics` step whose `skills_invoked` never records `run-scan` (G2; `08-scan` is not a STAGE_ORDER stage — the run-scan obligation keys on task_mode `scan` at `statistics`) | stop `skill-coverage` branch (exit 2 + `SKILL-COVERAGE`) | `case_G2.py` | `case_G2.py` exits 0 — the gate FIRED |
| G3 | a freshly `init`'d run asked to `advance --to statistics` with nothing generated (resource_census/trap_sweep/figure_contract stages FAIL) | `workflow_state.py advance` REFUSES an out-of-order jump (exit nonzero + unmet preconditions) | `case_G3.py` | `case_G3.py` exits 0 — the gate FIRED |
| G4 | a turn with a `next_required`, no `compute_launched`, no live/recent bg, not a delivery — narrates the next step instead of running it (D4) | stop `drive` branch (exit 2 + `DRIVE`) | `case_G4.py` | `case_G4.py` exits 0 — the gate FIRED |
| G5 | last message claims a background job is running but the liveness probe finds no recent logfile and no matching process (D5-signature) | stop `phantom` branch (exit 2 + `PHANTOM`) | `case_G5.py` | `case_G5.py` exits 0 — the gate FIRED |
| G6 | (a) the wired watchdog selftest seeds a hang→kill→`failure.json`; (b) an unhandled `*.failure.json` under the rundir makes the umbrella refuse turn-end (D6) | (a) `stage_supervisor.py --selftest` kill (exit 0); (b) stop `catch` branch (exit 2 + `CATCH`) | `case_G6.py` | `case_G6.py` exits 0 — the gate FIRED |
| G7 | the wired reporter selftest (the seeded 'long job running' trigger) | `progress_reporter.py --selftest` emits a progress line for a running job (exit 0 + nonempty stdout) | `case_G7.py` | `case_G7.py` exits 0 — the gate FIRED |
| G8 | an OPEN `failure_class=tool_generator_model` record with NO `inputs/recipe_search.json` — `resource_census.py --assert-recipe-search` close-block (D8/D-4, non-invariant branch) | stop `recipe-search` branch (exit 2 + `G8-RECIPE-SEARCH`) | `case_G8.py` | `case_G8.py` exits 0 — the gate FIRED |
| G9 | a `run-pipeline-native.sh trial-runs/<run>` launch whose contract declares `targets.model=SVJ` with NO fetched recipe, driven through `pre-generate-guard.sh` against an isolated `CLAUDE_PROJECT_DIR` (D7) | pre-generate guard hook BLOCKS (exit 2) | `case_G9.py` | `case_G9.py` exits 0 — the gate FIRED |
| G10 | scan run, generation done, PRIMARY figure target declared-at-check-in with a `generated_counterpart` but `side_by_side: null` (D9, primary-aware, all modes) | inv `figure-contract-fulfilled` FAIL | `case_G10.py` | `case_G10.py` exits 0 — the gate FIRED |
| G11 | a CHECK-IN-2 delivery turn whose PRIMARY figure target has `side_by_side: null`, so `validate_run_state.py --rundir` exits nonzero and the umbrella blocks (D5 waypoint) | stop `d18` umbrella (exit 2 + `D18`) | `case_G11.py` | `case_G11.py` exits 0 — the gate FIRED |
| G12 | shipping scan whose `inputs/validations.json` varied-param obligation is still `PENDING` (D10) | inv `param-validated-before-scan` FAIL | `case_G12.py` | `case_G12.py` exits 0 — the gate FIRED |
| G13 | full/scan run that reached generation with NO smoke-rung PASS in `logs/ladder.json` (D11) | inv `ladder-order` FAIL | `case_G13.py` | `case_G13.py` exits 0 — the gate FIRED |
| G14 | scan shipping an exclusion with NO discoverable acc×eff cert (D12; scan.json point attestation does not substitute) | inv `certify-before-limit` FAIL | `case_G14.py` | `case_G14.py` exits 0 — the gate FIRED |
| G15 | T8 trap hit with a `PENDING` (undischarged) `trap_sweep.json` obligation, generation reached (D13) | inv `trap-obligations-discharged` FAIL | `case_G15.py` | `case_G15.py` exits 0 — the gate FIRED |
| G16 | all-zero SR yields → degenerate huge µ95 → `sr_plausibility.json` verdict `implausible` folded by `check_statistics` (D14) | `statistics` stage FAIL | `case_G16.py` | `case_G16.py` exits 0 — the gate FIRED |
| G17 | an Edit to the CHECK-IN-1-baselined `inputs/task_contract.json` with no DEVIATIONS.md row naming it (D15) | edit-time `deviations-guard.sh` PostToolUse hook BLOCKS (exit 2) | `case_G17.py` | `case_G17.py` exits 0 — the gate FIRED |
| G18 | a thin CHECK-IN 1 JSON missing `schema_version`/`kind` (no gallery / numbered flags / waypoint / validations manifest) | `validate_checkin.py` FAILs (exit 1) | `case_G18.py` | `case_G18.py` exits 0 — the gate FIRED |
| G19 | `outputs/sr_plausibility.json` written with NO `generated_by` (its declared inputs present) — the only `LIFECYCLE_REQUIRED_PROVENANCE` artifact (G19) | `validate_run_state.py --verify-provenance` rejects a hand-written required artifact (exit 1, raw non-JSON) | `case_G19.py` | `case_G19.py` exits 0 — the gate FIRED |
| G20 | (a) a staged export tree whose `workflow/x.md` references a nonexistent path; (b) the worktree-resolved `git rev-parse --git-path hooks`/`pre-commit` (D16) | `check_agent_surface.py --stage` FAILs on a dead ref (exit nonzero) + the installed `pre-commit` hook is executable and invokes `check_agent_surface` | `case_G20.py` | `case_G20.py` exits 0 — the gate FIRED |
| G21 | a fresh **un-hinted** `claude` launched from the DSRLab PARENT cwd that fails to route: surveys the dev repo, or never emits `task_contract.json`, or generates before CHECK-IN 1 (D17). Headless `claude -p` is unauthenticated here, so this gate runs **on-demand** (`make green-self-drive`); it is never faked to PASS | self-drive verdict attested PASS — `clean_room.py --live` writes `self_drive/last_verdict.json`, the case `attest`s it (SKIP when absent unless `--with-self-drive`) | `case_G21.py` | case exit 0 = the recorded self-drive verdict == PASS; **SKIP** (never FAIL) when `self_drive/last_verdict.json` is absent and `--with-self-drive` was not passed |
| G22 | a first Skill `new-analysis` (not physicist-intake) with an empty isolated `trial-runs/` (no active-run task_contract.json) (N1) | PreToolUse-on-Skill guard `pretooluse-skill.sh` BLOCKS (exit 2) | `case_G22.py` | `case_G22.py` exits 0 — the gate FIRED |
| G23 | `scan_manifest.json` point whose `run_dir` resolves under `/tmp` (N2, out of the run/repo tree) | inv `outputs-in-tree` FAIL | `case_G23.py` | `case_G23.py` exits 0 — the gate FIRED |
| G24 | a turn-end with an armed watcher whose preflight artifact is missing on disk — `stop_dispatch.py --branch armed-watcher` shells `preflight_watcher.py --assert-all` (N3/D-4) | stop `armed-watcher` branch (exit 2 + `G24-ARMED-WATCHER`) | `case_G24.py` | `case_G24.py` exits 0 — the gate FIRED |
| G25 | a real `.lhe.gz` whose banner `nevents` (3) ≠ its counted `<event>` records (2), Cross-section line present (N4, grabbed mid-write) | inv `producer-complete` FAIL | `case_G25.py` | `case_G25.py` exits 0 — the gate FIRED |
| G26 | a DELIVERY turn-end with an unresolved `open_defect_notes[]` (read_yoda.py) — `stop_dispatch.py --branch open-defect` shells `verify_pack.py`, gated on `is_delivery` (N5/D-4) | stop `open-defect` branch (exit 2 + `G26-OPEN-DEFECT`) | `case_G26.py` | `case_G26.py` exits 0 — the gate FIRED |
| G27 | a `bg_kind=detached` `compute_launched` entry missing `logfile`/`done_condition`/`next_action` and with no live heartbeat (N6) | stop `detach` branch (exit 2 + `DETACH`) | `case_G27.py` | `case_G27.py` exits 0 — the gate FIRED |
