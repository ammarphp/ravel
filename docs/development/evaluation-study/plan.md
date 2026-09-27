# Evaluation study: plan

Primary study (Track A): does an evidence-bound delivery mechanism improve valid task completion
and reduce unsupported delivered conclusions beyond the same tools plus instructions alone? The
research plan's other tracks (Track B, a separate method-development track, and Track C, optional
learned methods) do not gate Track A and are not described here (E-37). Packet:
`research-planning/2026-09-25-ravel-research-packet/` in the DSRLab workspace (private, outside
this repository; SHA-256 of the supplied archive
`4e84e465cc581fda2dcea205f143245c0365438f2677a04bf003998617b518cd`).

Integration owner: the development lead session on branch `evaluation-slice`. Workers use separate
worktrees and disjoint file ownership; the integration owner merges, reruns tests and records
results here. A worker never grades its own scientific output or edits an oracle it is scored by.

## Phase status

| Phase / WP | Scope | Status | Evidence |
|---|---|---|---|
| Phase 0: WP00 | Baseline inventory, command map, gap table | done | [phase-0-audit.md](phase-0-audit.md) §1–3 |
| Phase 0: WP01 | Related-work comparison | done; not published (E-37) | phase-0-audit.md §5 |
| Phase 0: WP02 | Study charter and oracle definitions | provisional (E-01); the G0 review is deferred to the consolidated review (E-34) and no longer blocks development | [slice-design.md](slice-design.md), [decisions.md](decisions.md) |
| Guard inventory | 85-check inventory; Design A ruling | done (provisional ruling E-02) | phase-0-audit.md §4 |
| Phase 1: WP03 | v1 registry compatibility lock | implemented, agent-reviewed | `tests/governance/test_v1_contract_lock.py` |
| Phase 1: WP04 | Isolation manifest, sandbox, admission | implemented, agent-reviewed and red-teamed; repair wave: terminals and POSIX IPC denied (E-22), System V objects removed and flagged `ipc_residue` (E-20), census count cap replaced by the older-member check (E-19 as amended), clock-step identity (E-23); sign-off of E-19 and E-20 deferred (H-09, E-34); Linux `/proc` readers tested against recorded samples only (E-33); no live host has run under the profile | `isolation.py`, `allowlist_proxy.py`, `tests/governance/test_isolation.py` |
| Phase 1: WP05 | Independent likelihood oracle | implemented, provisional; the statistics review is deferred (B-02, E-34) | `oracle/counting.py`, [oracle-review-packet.md](oracle-review-packet.md) |
| Phase 1: WP06 | Fake host adapter | implemented, agent-reviewed | `adapters/fake.py`, `fake_subject.py` |
| Phase 1: WP07 | Coordinator, broker custody, receipt mapping | implemented, agent-reviewed; integration fixes merged (`7cf10d0`); repair wave: campaign freeze and per-launch verification (E-24), real-host binding and behavioral gate (E-25), outcome re-derivation and incident decisions (E-26), kind-bound specs and sealed-record verification (E-21); the real-host path has never run | `broker.py`, `runner.py`, `campaign_manifest.py` |
| Phase 1: WP08/WP09 | Codex and Claude CLI adapters (mocked; no paid call) | implemented against mocked executables, agent-reviewed; no real-host campaign builder, adapter factory, launch policy or proxy start exists yet ([smoke-request.md](smoke-request.md)); the Claude live smoke is authorized (E-34) and waits on that engineering (B-03); Codex live validation blocked (B-04) | `adapters/claude_cli.py`, `codex_cli.py` |
| Phase 1: WP10 | Treatment delivery and audit | implemented, agent-reviewed; manifest, behavioral and delivered-prompt checks (slice §4.3); the mechanism study is library-level only (E-27) | `treatment.py`, `guard.py` |
| Phase 1: WP11 | Claim/outcome audit and v1 outcomes | implemented, agent-reviewed; repair wave R3.0–R3.8 plus two review-and-repair rounds (E-28 to E-31); scoring rules provisional (PKT-D04, H-13), their review deferred (E-34) | `audit.py` |
| Phase 2: WP13 | Analysis and cost planning (synthetic design simulation only) | implemented, agent-reviewed | `analysis.py` |
| Phase 2: WP14 | Offline full-stack and isolation tests | built; slice §12 maps each acceptance item to its tests; G1 (synthetic engineering) met at `0b3d251`: `pytest tests` 4776 passed, 0 failed, and two CLI campaigns; after the merge at `12cc6f9`, `pytest tests` 4980 passed, 41 skipped, 0 failed (iteration 5) | `tests/governance/test_campaign_fullstack.py` (32 tests), [g1-record.md](g1-record.md) |
| Phase 1: WP35 | Isolation/state/evaluator red team | built: 23 test functions, 30 collected; 20 sandboxed attack cases (13 functions, 7 of them run in an enforcement and a baseline arm) skip without `sandbox-exec`, and 10 state and evaluator attacks run everywhere. Defect RT-01 fixed by eval/integfix `20c4506` (regression test `test_rt01_a_consistent_reseal_and_reaudit_is_reconciled_against_the_journal`); a judge report edited on its own is now refused too (E-26). Residual: a writer on the store's own account who rewrites the journal's seal digest together with the sealed tree and its manifest | `tests/governance/test_redteam.py` |
| Phase 2: WP12 | Development task bank | one provisional family (`likelihood_freshness`, four variants); its human reference review is deferred (E-34) | `tasks/development/` |
| Phase 2: WP15 | 8-assignment real-host engineering smoke | authorized (E-34); not launchable until its real-host engineering exists (B-03) | [smoke-request.md](smoke-request.md) |
| Phase 2: WP16 | Development pilot | not authorized; needs its own authorization (E-34) | — |
| Phase 3+ | Confirmatory study, native anchors, method-development track | not started | — |

"Agent-reviewed" means reviewed and repaired by agent workers and reviewers; no human has approved
any row, design or scoring rule.

## Iteration log

Each iteration ends with an artifact, the tests actually run, the source revision, the unresolved
scientific issue and the next action.

### Iteration 1 — Phase 0 (2026-09-25)

- Artifact: Phase 0 audit, slice design, decisions, blockers (this directory).
- Tests run: full baseline at `89273df` (2153 passed, 14 prerequisite skips; publication, evidence,
  replay and adversarial boards green). No source change.
- Unresolved scientific issue: the lab has not chosen the primary claim, oracle prescription or
  fault realism (B-01).
- Next action: implement the offline vertical slice (next-actions.md).

### Iteration 2 — offline vertical slice (2026-09-25)

- Artifacts so far: the evaluation harness under `benchmarks/governance/` (contracts, campaign
  manifest, independent oracle and development family, isolation, broker with the delivery guard
  and RAVEL kernel stage workers, subject client, fake/Claude/Codex adapters, treatment manifests,
  analysis, runner and CLI, independent audit), built in parallel worktrees, each independently
  reviewed and repaired, then merged (`4feda4f`); oracle review packet and costed smoke request.
- Tests run: 2010 governance tests pass at `4feda4f` on macOS with the Seatbelt sandbox active; a
  reviewer's probe ran the full 16-assignment synthetic reference campaign end to end (V0 reuse,
  V1 refit, V2 fit reuse and reconversion, V3 valid refusal in all four arms). The full repository
  suite at `6a976c9` passed except one test that diffs ignored files and failed only because
  concurrent worktrees were writing under `local-runs/` (narrowed in `cab8d9f`).
- A machine crash interrupted wave 3 (integration fixes, full-stack acceptance tests, red team);
  partial work was checkpointed as WIP commits on its branches and resumed.
- Unresolved scientific issue: unchanged (B-01); the audit's claim-classification word lists and
  refusal rules are provisional (PKT-D04).
- A second session kill at 16:00 was investigated before any further work (the OS never rebooted
  either time): the 16:00 "crash" was the harness census SIGKILLing every user process, reproduced
  exactly; the 14:08 one has the same signature but its trigger is unconfirmed. Root cause, reproduction
  under a diagnostic signal guard, the fail-closed fix (`f6c0f45`) and prevention rules are in
  [incident-2026-09-25.md](incident-2026-09-25.md); the fix was merged into all wave-3 branches.
- Merge review of `evaluation-slice` (integfix, fullstack, redteam) found a Linux-only defect in the
  lost-launch census (from `985b30b`): `isolation._proc_info` reads start times from `/proc` as the
  whole-second boot time plus clock ticks, up to 1.01 s early, so `check_launch_record` rejected
  real `process_started` records and the unsandboxed census could list the launch's own group
  members `foreign` and seal a live subject as a clean lost launch. Fixed on the branch (untested on
  Linux, below):
  `START_READ_ERROR_S` (1 + 1/CLK_TCK on Linux, 0 on macOS) widens every start-time floor, a
  proven group's live member that the floor still excludes makes the census incomplete (runner flag
  `census_incomplete`), and the full-stack evidence-chain check runs on every platform again.
  Correction (repair wave): reads of one Linux process agree only while the wall clock does not step.
  A step moves the boot time, and with it every later start-time read, by whole seconds, so the
  launcher compares a clock-free identity (boot id and start ticks) and `census_launch`, which holds
  only the recorded wall-clock `leader_start`, treats a holder whose start differs from it by whole
  seconds, or by less than 1e-4 s on any platform, as unprovable (nothing signalled, census
  incomplete). Residual: on Linux the floor admits a process started up to 1.06 s before the launch
  (a proven group or a sandbox holds only the launch's descendants anyway). Verified on macOS only.
  The Linux path has never run: CI (Linux) runs only on a push to `main` or a pull request, which this
  branch, in a repository with no remote, has not had. Record a Linux run of `tests/governance` before
  calling the Linux defect fixed.
- Iteration 2 closes here; the review and repair wave that followed is iteration 3.

### Iteration 3 — holistic review and repair wave (2026-09-25/26)

- Artifacts: a five-lens holistic review of the merged slice at `0fb3922` (treatment identity,
  custody, documentation truth, scoring, isolation; a skeptic pass upheld all 14 findings it
  checked, downgrading one to minor); four repair tracks (`eval/fix-manifest`, `fix-isolation`,
  `fix-runner`, `fix-scoring`), each reviewed and repaired, merged at `44dc69f`; a scoring review
  repair (`436e8c4`…`d5d6bc7`); the integration hand-offs (`234d655`…`8b5ab00`); an integration
  review and its repair (`f55e962`…`5a300a4`); and this documentation pass, which changed no code.
  The rules are recorded as E-19 (amended) to E-31, the open questions as H-08 to H-13. The holistic
  review, its skeptic verdicts and the repair tracks' reports are kept in the ignored
  `local-runs/evaluation-slice/reviews/`; [decisions.md](decisions.md) explains their IDs.
- Tests run, as reported by the workers: at `8b5ab00` the governance suite in two halves,
  404 + 2141 = 2545 passed (2517 in `tests/governance` plus the 28 v1 tests); at `5a300a4`, 122
  passed (`test_runner.py`, `test_campaign_fullstack.py`, `test_redteam.py`) plus 2529 passed (every
  other `tests/governance` file and `tests/unit/test_governance_experiment.py`), 2651 in all,
  0 failed. Both ran on this macOS 15.5 host, where the Seatbelt sandbox and its census are
  available, under the diagnostic kill guard, which logged no refusal. The documentation pass ran
  only the two files that check `slice-design.md`'s content (`test_family.py`, `test_contracts.py`:
  1089 passed) and `pytest --collect-only`, which collects the same 2651 tests (2623 + 28). No full
  `pytest tests` run exists after `6a976c9` (none at any repair-wave revision); the full suite G1
  needs is `pytest tests` (slice §12 item 7). The ignored `local-runs/evaluation-slice/g1-evidence/`
  (two synthetic CLI campaigns at `0fb3922`) predates the repair wave and is not G1 evidence.
- Unresolved scientific issue: unchanged (B-01); the evaluator's word lists and conventions are
  provisional (PKT-D04, H-13).
- Next action (done in iteration 4): the integration owner's final acceptance run and the G1 record (slice §12); human
  decisions H-08 to H-13; the engineering follow-ups in [next-actions.md](next-actions.md).

### Iteration 4 — G1 acceptance run (2026-09-26)

- Artifact: [g1-record.md](g1-record.md), the G1 record at `0b3d251` (a clean tree; the only
  change after `2110cf6` is a decisions.md pointer to the saved integration reports).
- Tests run: `pytest tests`, serialized, on this macOS 15.5 host with Seatbelt and the kill guard:
  4776 passed, 14 skipped (none in `tests/governance`), 0 failed, 777.96 s. Then two synthetic CLI
  campaigns (`g1-reference`, `g1-mechanism`, 16 assignments each): every command exited 0, both
  behavioral treatment checks and both `verify` runs passed. The kill guard refused nothing and
  was then removed (environment change log, 2026-09-25 entry). `scripts/check_evidence.py --check`:
  17 of 17 pass. `scripts/check_publication.py`: fails only on the 7 known filename errors (E-10).
- Unresolved scientific issue: unchanged (B-01, B-02); G1 is engineering evidence only.
- Next action: human gates and decisions (G0, WP05 review, H-08 to H-13, smoke authorization);
  the local engineering items in [next-actions.md](next-actions.md).

### Iteration 5 — integration, publication, Linux portability and release preparation (2026-09-26)

- Integration: `feature/analysis-landscape-census` (tip `6fbae4b`, the source commit of the public
  release `def0415`) merged into `evaluation-slice` at `12cc6f9`. At `12cc6f9`, as the integration
  lead reported it: `pytest tests` 4980 passed, 41 skipped (optional dependencies), 0 failed;
  `check_evidence.py --check` 17 of 17; `check_publication.py` failed only on the seven filename
  errors that E-32 then fixed.
- Artifacts: `1e162bd` (E-32: the seven kebab-case renames) and the E-33 changes: the research
  packet's location derived from the checkout, the Linux `/proc` readers split out and tested against
  recorded Linux samples, no `/private` paths in test fixtures, and these records. An export dry run
  through `scripts/maintenance/export-distribution.sh` into a new directory outside the repository,
  without `--push`.
- Tests run, on this macOS 15.5 host: at `1e162bd` (the rename worker's report) `tests/governance` and
  `tests/unit/test_governance_experiment.py`, 2651 passed; `check_publication.py` OK; `check_evidence.py
  --check` 17 of 17. At `1e162bd`, before the E-33 changes, `tests/governance` with Seatbelt reported
  unavailable (a scratch plugin; the Linux path): 2566 passed, 57 skipped, 0 failed. At `bb63c59` (the
  E-33 code): `test_contracts.py`, `test_isolation.py`, `test_signal_guard.py` and
  `test_v1_contract_lock.py`, 1473 passed with Seatbelt available. The export dry run, at `bb63c59`:
  with the system `python3` (3.13.0) first on `PATH`, the staged
  `check_publication.py` fails in the fidelity audit ("Source AST claim changed": the audit pins an AST
  digest that differs between Python versions; the same check fails in the source tree under 3.13 and
  passes under 3.12). With `.venv-dev/bin` (3.12.13, the CI version) first on `PATH` the export
  completes: 1508 files, 19 of them sanitized (none under `benchmarks/governance`, `tests/governance`
  or this directory), evidence 17 of 17, agent surface OK on the stage, publication OK, no file over
  5 MB.
- A CI-like run of the exported tree: copied to a case-sensitive APFS volume as a fresh git checkout
  without bytecode, hooks installed, run by an interpreter holding the lock's packages and no `ravel`
  install. `tests/governance`, with scratch plugins outside the repository that report Seatbelt
  unavailable and truncate every process's start time as Linux `/proc` does (whole-second boot time
  plus ticks): 2570 passed, 58 skipped, 0 failed. `tests/unit` and `tests/adversarial` (macOS start
  times), with the governance signal guard loaded: 2347 passed, 51 skipped, 0 failed. This is a
  simulation on macOS, not a Linux run.
- At `7bad716` (the portability worker's final run, Seatbelt available, foreground, one pytest at a
  time): `tests/governance` and `tests/unit/test_governance_experiment.py`, 2656 passed, 0 failed.
  The export dry run repeated at `7bad716` gave the same results as at `bb63c59`.
- Release preparation (documentation only, no code): a CHANGELOG entry, a README pointer, the
  evaluation-study section of `docs/development/status.md`, E-34 (the human reviews deferred to one
  consolidated review; the 8-assignment engineering smoke authorized) and E-35 (the development
  family, its oracle and the evaluator are published; protected cases never are), with blockers.md,
  next-actions.md, the smoke request's status and the governance README updated to match. Checks run on these changes: `scripts/gen_status.py
  --check` OK; `check_agent_surface` OK (every section, including dirmap); `check_publication.py`
  OK (1508 files, 975 links); `check_evidence.py --check` 17 of 17; the repository, record and
  export unit tests (eight files), 106 passed. No code changed, so `tests/governance` was not rerun.
- Not run: anything on Linux; `pytest tests` in one process after the renames.
- Unresolved scientific issue: unchanged; the reviews that would settle it (B-01, B-02) are deferred
  (E-34).
- Next action: read the public CI's first Linux run of `tests/governance` after the push
  ([next-actions.md](next-actions.md) item 2); build the real-host pieces the authorized smoke needs
  (item 3).

### Iteration 6 — export review repairs (2026-09-26)

- Trigger: the staged export of `cb469a8` and its independent reviews. The export passed its own checks
  and its stage suite, but the frozen treatment texts were the research packet's candidate prompts, and
  the publisher's `--push` would have committed under the machine's global Git identity.
- Artifacts: `6b296d4` (E-36: the envelope and the scientific instruction text rewritten for the
  repository, the packet-equality test replaced by a no-copy check; H-14 opened), `1dc95eb` (the
  lost-launch census is incomplete when a live group lists no members; two census tests use synthetic
  leader starts a fixed .37 s off a whole second), `43db3e7` (the exporter checks the publish identity
  against the remote's last commit, adds `--message`, `--push-branch` and `--allow-new-identity`, stops
  unless `python3` is 3.12, and maps `tests/governance` and `benchmarks/governance` in the public
  `DIRECTORY.md`), `bef681a` (the changelog's proxy claim corrected; open items in next-actions.md) and
  `68be547` (the red-team packet probe uses `runner.packet_dirs()`).
- Tests run, on this macOS 15.5 host with Seatbelt, `.venv-dev` (Python 3.12.13), foreground, each
  governance run holding the shared lock: `tests/governance` in six runs, 2629 passed, 0 skipped, 0
  failed (`test_isolation`, `test_signal_guard`, `test_guard`, `test_broker`, `test_treatment`: 387;
  `test_runner`: 61; `test_redteam`: 30; `test_campaign_fullstack`: 32; `test_contracts`: 1068; the
  other nine files: 1051). `tests/unit` and `tests/adversarial` in one run without the governance signal
  guard: 2357 passed, 41 skipped (optional dependencies and unshipped archives). Not one `pytest tests`
  process. The new no-copy test fails on the old texts (checked by pointing it at copies of them). The
  exporter's `--push` path was run only against a local bare repository in the scratch directory: a
  global identity that differs from the last commit is refused with nothing committed, a matching one
  publishes to `main` and to a review branch, and `--allow-new-identity` proceeds with a warning.
- Not changed, and why: the test session's signal guard edge cases, the `spk-2` fixture's dash-encoded
  user name and one Linux clock-step flake window (next-actions.md, "Export review, left open"); the
  owner's confirmation of the working records' private-planning content, the E-34 quotation and the
  citation email (next-actions.md, "Still needing a human decision").
- Not run: anything on Linux; a push to GitHub.
- Unresolved scientific issue: unchanged (B-01, B-02); the treatment wording to preregister is H-14.
- Next action: the owner's confirmation above, then a fresh export and a publish to a branch with a pull
  request, so the public CI's Linux job runs before `main` moves (next-actions.md item 2).

### Iteration 7 — second export review repairs (2026-09-26)

- Trigger: the staged export of `917c049` and its reviews. The export and its stage suite passed. The
  reviews found that the working records publish paraphrased private research planning and a third
  party's name without the owner's confirmation, and that `tests/governance` has never run on Linux
  while a direct `--push` would make the public `main` its first Linux run; plus minor items.
- Artifacts: `1b7b210` (the exporter's leak check, `export_safety.py leak-check`, refuses the home
  path, its dash-encoded form and the bare account name in text files, binary files and paths; the
  `spk-2` fixture's project directory redacted and the record re-recorded; distribution.md describes
  the leak check and branch-first publishing with a fast-forward of `main`), `4c402c4` (the host-stream
  fixtures described as hand-written, not recorded), `3ac5891` (E-37: private planning removed or
  neutralized until the owner decides; E-38 and H-15: the sidecar interfaces taken from the packet;
  next-actions.md updated) and this entry.
- Tests run at `3ac5891`, on this macOS 15.5 host with Seatbelt, `.venv-dev` (Python 3.12.13),
  foreground, every run holding the shared lock: `tests/governance` in four runs, 2629 passed,
  0 skipped, 0 failed (`test_campaign_fullstack` 32, `test_redteam` 30, `test_runner` 61, the other
  files 2506). `tests/unit` and `tests/adversarial` in three runs, without the governance signal guard:
  2359 passed, 41 skipped (optional dependencies, the wheel check, unshipped archives), 0 failed. Not one
  `pytest tests` process. `tests/adversarial/run_suite.py --require-all`: 29 PASS, 1 SKIP (G21), 0 FAIL.
  `check_evidence.py --check` 17 of 17; `check_publication.py` OK; agent surface OK. An export dry run
  into a new directory outside the repository, without `--push`: 1508 files, 19 sanitized, the leak
  check clean, 16 evidence redactions rebound, evidence 17 of 17, agent surface and publication OK;
  compared with the stage of `917c049` it differs only in the 13 changed source files and
  `evidence/export-provenance.json`.
- Not changed, and why: the Linux census gap for a zombie thread-group leader with live threads, the
  test guard's None-read edge cases and the Linux clock-step window (next-actions.md, "Export review,
  left open", items 4, 1 and 3); restoring any text E-37 removed, H-14, H-15 and the citation email
  (the owner's); the incident record's local times and process ids, kept as forensic detail; packet
  section references in the harness code (E-37).
- Not run: anything on Linux; a push to GitHub.
- Unresolved scientific issue: unchanged (B-01, B-02).
- Next action: a fresh export published with `--push-branch` and a pull request against `main`; `main`
  fast-forwarded to the reviewed commit only after the test job passes (next-actions.md item 2); the
  owner's decisions above.
