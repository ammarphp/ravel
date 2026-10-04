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
| Phase 1: WP04 | Isolation manifest, sandbox, admission | implemented, agent-reviewed and red-teamed; repair wave: terminals and POSIX IPC denied (E-22), System V objects removed and flagged `ipc_residue` (E-20), census count cap replaced by the older-member check (E-19 as amended), clock-step identity (E-23); sign-off of E-19 and E-20 deferred (H-09, E-34); Linux `/proc` readers tested against recorded samples only (E-33); the real host ran under the real-host profile only in the 2026-09-27 smoke ([smoke-record.md](smoke-record.md)) | `isolation.py`, `allowlist_proxy.py`, `tests/governance/test_isolation.py` |
| Phase 1: WP05 | Independent likelihood oracle | implemented, provisional; the statistics review is deferred (B-02, E-34) | `oracle/counting.py`, [oracle-review-packet.md](oracle-review-packet.md) |
| Phase 1: WP06 | Fake host adapter | implemented, agent-reviewed | `adapters/fake.py`, `fake_subject.py` |
| Phase 1: WP07 | Coordinator, broker custody, receipt mapping | implemented, agent-reviewed; integration fixes merged (`7cf10d0`); repair wave: campaign freeze and per-launch verification (E-24), real-host binding and behavioral gate (E-25), outcome re-derivation and incident decisions (E-26), kind-bound specs and sealed-record verification (E-21); live smoke build: one builder for the fake and a real host, the build-time binding, the per-launch proxy, credential injection, post-run checks, kernel receipts, stop and limit (E-61 to E-70), then two review repairs (E-71 to E-100); for the pilot, its approval kind, the design budget and the census of a lost run launch before preflight (E-204 to E-206); the real-host path has run in tests against mock CLIs, with the real 2.1.281 pin at zero cost (probes, preflight and an offline 8-run rehearsal with a dummy token against a local mock API, E-71, E-88; the 48-run pilot-shaped rehearsal of every bank family, E-208), and in the authorized 8-run paid smoke (2026-09-27, [smoke-record.md](smoke-record.md)); LC-18's collector fixed after it (E-162) | `broker.py`, `runner.py`, `campaign_manifest.py`, `live.py`, `credentials.py` |
| Phase 1: WP08/WP09 | Codex and Claude CLI adapters (mocked; one paid Claude smoke) | implemented against mocked executables, agent-reviewed; the Claude adapter has a real-host builder, factory, launch policy and proxy (smoke configuration E-40 to E-51, [smoke-request.md](smoke-request.md)), run end to end in tests against mock CLIs, with the real 2.1.281 pin in the zero-cost probes and the offline rehearsal (E-88), and in the Claude live smoke (2026-09-27: 8 of 8 runs sealed, no stop; [smoke-record.md](smoke-record.md)) and the development pilot (2026-09-29: 96 of 96 sealed, no stop; [pilot-record.md](pilot-record.md)); Codex live validation blocked (B-04) | `adapters/claude_cli.py`, `codex_cli.py` |
| Phase 1: WP10 | Treatment delivery and audit | implemented, agent-reviewed; manifest, behavioral and delivered-prompt checks (slice §4.3); the mechanism study is library-level only (E-27) | `treatment.py`, `guard.py` |
| Phase 1: WP11 | Claim/outcome audit and v1 outcomes | implemented, agent-reviewed; repair wave R3.0–R3.8 plus two review-and-repair rounds (E-28 to E-31); repaired against the real-host smoke's findings with a held-out check and replayed regression cases (E-188), and a read-only `rejudge` (E-189); repaired again after that repair's review, its probes held out first (E-190, E-191); its two known false-clean paths closed before the pilot, held-out cases first (E-200 to E-202, iteration 23); on the pilot's 96 realistic reports it left `unsupported_claim` null in 62 runs and decided most checked cells wrongly (E-217, E-218); repaired by the pilot's taxonomy, held-out cases first (E-220 to E-223, iteration 28), and the sealed pilot re-judged read-only (E-224, iteration 29): 16 of 23 false-positive cells cleared, 3 of 8 kx-a and 3 of 5 lf-d refusals valid (E-219's acceptance not met), `unsupported_claim` still null in 64 of 96 runs (H-116); scoring rules provisional (PKT-D04, H-13, H-90, H-91, H-100), their review deferred (E-34) | `audit.py`, [smoke-record.md](smoke-record.md), [pilot-record.md](pilot-record.md) |
| Phase 2: WP13 | Analysis and cost planning (synthetic design simulation only) | implemented, agent-reviewed | `analysis.py` |
| Phase 2: WP14 | Offline full-stack and isolation tests | built; slice §12 maps each acceptance item to its tests; G1 (synthetic engineering) met at `0b3d251`: `pytest tests` 4776 passed, 0 failed, and two CLI campaigns; after the merge at `12cc6f9`, `pytest tests` 4980 passed, 41 skipped, 0 failed (iteration 5) | `tests/governance/test_campaign_fullstack.py` (32 tests), [g1-record.md](g1-record.md) |
| Phase 1: WP35 | Isolation/state/evaluator red team | built: 23 test functions, 30 collected; 20 sandboxed attack cases (13 functions, 7 of them run in an enforcement and a baseline arm) skip without `sandbox-exec`, and 10 state and evaluator attacks run everywhere. Defect RT-01 fixed by eval/integfix `20c4506` (regression test `test_rt01_a_consistent_reseal_and_reaudit_is_reconciled_against_the_journal`); a judge report edited on its own is now refused too (E-26). Residual: a writer on the store's own account who rewrites the journal's seal digest together with the sealed tree and its manifest | `tests/governance/test_redteam.py` |
| Phase 2: WP12 | Development task bank | five provisional families, twelve tasks in six pairs: `likelihood_freshness`, kx, hv, mq and tz, all runnable since iteration 15 (E-136); the bank's oracles and their cross-checks (plan steps 2 and 3, [taskbank-oracle-appendix.md](taskbank-oracle-appendix.md)); step 1 done in iteration 12: task and claim schema version 2, the bank rules, the registry and the LF migration (E-110 to E-119); steps 4 and 5 done in iteration 13: the generalized fit, the census, calc and coordinator-only figure stages, and the broker's registry inputs, prior recipes, keyed run directories and stage budget (E-120 to E-124); steps 6 and 7 done in iteration 14: the guard's field registry, dependency classes, pb, relation and categorical claims, and the four family builders (E-125 to E-130); steps 8 and 9 done in iteration 15: the evaluator's scoring profiles (`audit_bank.py`, judge report version 2), claim version 2 at the broker, the fake subject's behaviours and the 12-task synthetic campaign through the CLI (E-131 to E-136); steps 10 and 11 done in iteration 16: the tool guide for claim version 2, the resource and permitted-actions sentences, the treatment digests and the packet-similarity check (E-137 to E-140), and the review packet (E-141; E-142 records a gap it found); iteration 17 repaired the findings of the engineering review of 2026-09-27 (E-143 to E-158, questions H-62 to H-66), and iteration 18 those of the second review of that day (E-165 to E-186, questions H-80 to H-89); merged into `evaluation-slice` in iteration 19 (E-187); its human reference review is deferred (E-34), and the packet is ready for it | `tasks/`, `contracts.py`, `guard.py`, `audit_bank.py`, `client/tools.md`, [taskbank-review-packet.md](taskbank-review-packet.md) |
| Phase 2: WP15 | 8-assignment real-host engineering smoke | done (2026-09-27, iteration 11): 8 of 8 runs sealed with no stop; engineering evidence only, with seven stated deviations (E-161) | [smoke-record.md](smoke-record.md), [smoke-request.md](smoke-request.md) |
| Phase 2: WP16 | Development pilot | done (2026-09-29, iteration 27): design A, authorized by the owner on 2026-09-28 (H-73), ran 96 of 96 assignments from `8c89d4b` with no stop, hold or trigger; 18.44 USD CLI-reported against the 192 USD admission threshold. Development evidence only, under provisional rules, with stated deviations (E-215, E-216). The mechanical evaluator left `unsupported_claim` null in 62 of 96 runs (E-217), and its decided cells were mostly wrong where the lead's analysis agents checked them (E-218); the repair it opened (E-219 to E-223) re-judged it read-only (E-224) without meeting E-219's acceptance. Earlier: the request's engineering items 1 to 6 (E-200 to E-209) and their review's repair (E-210 to E-214) | [pilot-record.md](pilot-record.md), [pilot-request.md](pilot-request.md) |
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

### Iteration 8 — real-host smoke engineering (2026-09-26)

- Numbering: this was iteration 6 on `eval/live-smoke`; renumbered at the merge (iteration 10), since
  `evaluation-slice` had its own iterations 6 and 7.
- Artifacts: branch `eval/live-smoke` from `7bad716`. The implementation spec's §9 steps 1 to 7 are in
  `21a90a8`, `77d3ed2`, `be40857`, `bd28495`, `4272144`, `a76dce4`, `a944707`, `1bf9ca2` and `b763f21`,
  with decisions E-40 to E-69 and H-20 to H-24 (`8550089`, `a677813`). Step 8 (these documents, E-70,
  H-25) is the commit that adds this entry.
- Tests run, as the build stages reported them, every `tests/governance` run through the
  cross-workflow lock: `tests/governance` in one run after steps 1 to 4 (2906 passed, 0 skipped); after
  steps 5 to 7 all 21 files of `tests/governance` in five runs (3052 passed, no skips). For step 8 the
  targeted runs are listed in its commit message.
- Not run: the real pinned binary in any probe, rehearsal or launch (only `--version` and `--help` in
  the design survey, and read-only byte and signature reads); anything paid; anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02); the smoke is engineering evidence only.
- Next action: the operator procedure in [smoke-request.md](smoke-request.md): H-20 and the approval,
  the harness-owned pin copy, the zero-cost probes on the real pin, then the token.

### Iteration 9 — real-pin probes and two review repairs (2026-09-26 to 2026-09-27)

- Numbering: this was iteration 7 on `eval/live-smoke`; renumbered at the merge (iteration 10).
- Artifacts: on `eval/live-smoke`, the harness-owned 2.1.281 copy (S3) and the first zero-cost probes
  on the real pin, with their fixes (E-71, E-72); the first 2026-09-27 review's fixes (`c30a452`,
  `6202c7a`, `3586e9a`: E-73 to E-87) and the probes and offline rehearsal on campaign F (`2fb4c0b`,
  E-88); the second review's fixes (`bebd7de`, `a87afcc`: E-89 to E-100, H-30, H-31), among them the
  ledger's own directory (the smoke's build needed it), the pin's code-signature check, the init
  skill and agent checks, the enforced S10a go/no-go after run 1, the per-run ceiling stop, the
  approval's spend envelope, the gate on unclean probe launches, the bounded leader wait and the stage
  supervisor's hold of a leaderless group; and rehearsal campaign G on that revision (E-101).
- Tests run, every `tests/governance` run through the cross-workflow lock: `test_contracts.py`,
  `test_adapters_claude.py` and `test_signal_ownership.py` (1344 passed); `test_live_host.py` (262
  passed, 1 failed: LC-06 did not list the new init flags, fixed, and its tests rerun); `test_rehearsal.py`
  (21 passed); the stage supervisor's users in `tests/unit` with the governance signal guard loaded,
  and the adversarial G6 selftest in that process (250 passed). The whole of `tests/governance` at
  `a87afcc`: 3186 passed and 8 failed in 64 min at a load average near 30 from other workflows; seven
  were `test_campaign_fullstack.py`, whose CLI job hit its 1200 s timeout, and that file then passed
  alone (36 passed); the eighth is `test_audit.py::test_evaluator_reads_a_megabyte_text_in_linear_time`,
  a 20 s wall-time bound that took 30 to 36 s at that load, on `audit.py` unchanged since `c30a452`,
  and that failed the same way in the previous full run (3147 passed, 1 failed).
- Real pin, zero cost only: rehearsal campaign G (a dummy token in a scratch file, a deny-all proxy, a
  local mock Messages API): build, every required probe, PF-01 to PF-14, and the offline run path with
  the S10a go between run 1 and the other seven, without a stop (E-101).
- Not run: anything paid; the smoke's own campaign; anything on Linux; `pytest tests` in one process.
- Unresolved scientific issue: unchanged (B-01, B-02); the smoke is engineering evidence only.
- Next action: the operator procedure in [smoke-request.md](smoke-request.md): H-20 (and H-21, H-30,
  H-31) and the approval with its spend envelope, then S0 onward on a clean checkout.

### Iteration 10 — merge of the live path (2026-09-27)

- Artifacts: `eval/live-smoke` (tip `c281393`, iterations 8 and 9) merged into `evaluation-slice`
  (tip `6ab1dae`) with `git merge --no-ff`, in the commit that adds this entry. Git merged every code
  and test file without a conflict; the conflicts were in `DIRECTORY.md`, the governance README and six
  records in this directory. Resolution (E-102): every entry of both branches is kept. No decision,
  question or blocker id was shared, so none was renumbered; the live branch's iterations 6 and 7 are
  8 and 9 here. Rows both branches changed carry both changes (H-04, H-11, H-12, E-20, B-03, B-05,
  and the WP08/WP09 and WP15 rows above). The live branch's rewritten smoke-request.md is kept whole
  with E-34 beside E-47, and slice-design.md §9 takes the live text with this branch's fixture wording,
  corrected for the one fixture the real pin produced with scripted content. E-37 applied to the
  merged text: E-47's chat quotation and a collaborator's name in four owner cells. CHANGELOG.md,
  README.md and docs/development/status.md said the real-host path had not run or could not yet
  run; they now say it has run only at zero cost.
- Code: no merge-induced change was needed. The census rule of `1dc95eb` is intact in
  `isolation.census_launch` beside the live branch's launcher changes (deferred interrupts, bounded
  leader wait, `remove_unattributed_ipc`); the treatment texts of `6b296d4` are unchanged, and no
  live-branch test pins a treatment digest.
- Checks at the merge, on this macOS 15.5 host with Seatbelt, `.venv-dev` (Python 3.12.13) first on
  `PATH`: `check_agent_surface` OK; `scripts/check_publication.py` OK; `check_evidence.py --check`
  17 of 17. `pytest tests` in one process through the shared lock (a background task of the merging
  session), at a load average of 21 to 41 from other workflows: 5913 collected, 5872
  passed, 41 skipped (optional dependencies, the wheel checks, an unshipped archive, the native RJR
  toolchain), 0 failed, in 61 min. The records, publication and hygiene unit tests were rerun after
  this entry was written (counts in the commit message).
- Not run: anything paid; the real pinned binary (no probe or rehearsal at this revision); the
  smoke's own campaign; anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02); the smoke is engineering evidence only.
- Next action: the operator procedure in [smoke-request.md](smoke-request.md) from S0 on a clean
  checkout of this merge: H-20 answered in the approval (S4), the smoke campaign's build and its
  probes (S5 to S7), then the token (S8).

### Iteration 11 — the real-host engineering smoke (2026-09-27)

- Artifacts: [smoke-record.md](smoke-record.md), the record of campaign `smoke-claude-2.1.281-a`, its
  tables generated from the sealed store by the ignored `local-runs/evaluation-slice/smoke/record-tables.py`;
  decisions E-160 to E-163 and H-70 to H-73 (H-20 answered; H-21 moot for the smoke's token); the LC-18
  collector fix (E-162) with recorded unified-log fixtures in `tests/governance/fixtures/unified_log/`.
- What ran, from `8dbc4a2` with the lead agent session as operator in a scrubbed environment (E-161):
  S0 and S2 to S13 of the procedure, S1 not run (E-161 (6)): the approval, the build, the treatment
  check, both probe records, preflight, paid run 1, the S10a go under E-160, paid runs 2 to 8, audit,
  report, verify and `live-checks --costs`. All 8 runs sealed with no stop, hold or trigger; the pinned CLI reported
  2.59 USD (quota usage on a subscription token). `lf-b` completed in all four arms with fidelity error
  3.6 × 10⁻⁶; `lf-d` was refused in all four. The mechanical evaluator left no run a verified completion
  or a verified valid refusal (E-163). LC-16 warned in every run (no reported geography, E-160), LC-17
  as expected, and LC-18 once, on the collector's own `log` invocation (E-162).
- Tests run, through the cross-workflow lock: `tests/governance/test_live_host.py` with the E-162 change
  (268 passed, 5 of them new, in 563 s) and `tests/governance/test_runner.py`, which imports live.py
  (73 passed); `check_agent_surface` OK; `verify` on the smoke's campaign still passes at the fix's
  commit (`019c08e`).
- Not run: `pytest tests` in one process (only live.py and its tests changed); anything on Linux; any
  paid call after S11.
- Unresolved scientific issue: unchanged (B-01, B-02); the smoke is engineering evidence only, and the
  evaluator's verdicts decided most of its cells.
- Correction (2026-09-27, after an independent re-check of the record against the sealed store, the
  journals, the custody logs, the operator's logs and the host's crash reports): the lead's background
  workflow ran until 17:42, through S8, and was stopped only from S8b to S13 (E-161 (3)). Two further
  deviations are counted: S1 was not run as a serialized step, and S3's outputs and S6's `verify`
  output were not kept (E-161 (6), (7)). E-160 separates the reason the go record keeps from the x1
  recompute found after the smoke. Run 1's 7 attempted invalid conclusions are six σ_vis values and the
  stale 120 fb⁻¹ value, taken from the task fixture's prior artifact (not an earlier campaign run), and
  its Bash error is the rejected submit itself. In `lf-b` enforcement only the two broker-rejected
  submits carried a "diagnostic" claim. The two `sandbox-exec` reads cited for LC-18 crashed `/bin/cat`
  and are no evidence (E-162). The synthetic labels are in `spec.json` and `registry.json`, not
  `summary.json`. The generated tables name both host-binding digests and show that the dry start's 16
  CONNECTs were denied (`record-tables.py` changed). The record now states the token's lifetime, that
  the revocation is unconfirmed (H-72), and that H-21 and P0 item 2 were never
  done (smoke-request.md). The unified-log fixtures' boot UUID was replaced by zeros. The findings,
  counts and costs are unchanged.
- Next action: the evaluator repair (E-163) with a held-out check, using the 8 transcripts as regression
  cases; then the owner's decisions on the pilot (H-71, H-73) and the guard (H-70).

### Iteration 12 — WP12 task bank, plan step 1 (2026-09-27)

- Numbering: this was iteration 11 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Artifacts (branch `eval/taskbank-v2` from `evaluation-slice` at `8dbc4a2`; code in `3c86111`):
  task-definition and claim schema version 2 beside unchanged version 1, with their schema mirrors
  (`task_definition_v2`, `claim_v2`); `contracts.validate_task_bank` (twins, identical request bytes,
  bank-wide budget and operations, contrasts and their declared subject-visible differences,
  leaky ids, the visibility waiver); the registry `tasks/registry.py` and `build_bank`, which the
  runner now freezes as `coordinator/family/`; the LF migration (two pairs and `lf-sup`, one new title,
  the estimand clause, `bank_version` `wp12-dev-1`, `lf-a` carrying `visibility_waiver_pending`). The
  decisions this build rests on are E-110 to E-119 (D-V adopted provisionally; D-UV, D-CP, D-KX, D-MC
  and the toy estimand decided provisionally; the review's errata recorded); their questions are
  H-40 to H-46.
- Tests, all through the shared lock on this macOS 15.5 host with Seatbelt and `.venv-dev` (Python
  3.12.13), on the code of `3c86111`: all 3700 collected tests of `tests/governance`, in chunks under
  ten minutes that together cover the collected set, 3700 passed, 0 failed, 0 skipped. They include the
  new `test_task_bank.py` and the updated contract, family, manifest, evaluator, fake-adapter, runner
  and full-stack tests (the reason for each change is in the commit message); the live-host,
  isolation, rehearsal, red-team, broker and oracle files are unchanged and pass.
  `check_agent_surface` OK; `scripts/check_publication.py` OK; `tests/unit/test_export_safety.py` 22
  passed. A follow-up (`85c0adc`) keeps `campaign_manifest.verify` from judging part of a bank whose
  index names an unreadable definition; after it, the manifest and bank tests and the first half of the
  runner tests were rerun (all passed).
- Not run: anything paid; the real pinned binary; the smoke's campaign; anything on Linux; the
  repository's other suites (no file outside the governance package and its tests changed).
- Unresolved scientific issue: unchanged (B-01, B-02); the bank's human reference review is deferred
  (E-34), and D-V keeps the bank to synthetic engineering campaigns (E-110).
- Next action: WP12 plan step 4 (the generalized `fit`, `census` and `calc` stage workers), then the
  broker (step 5).

### Iteration 13 — WP12 task bank, plan steps 4-5 (2026-09-27)

- Numbering: this was iteration 12 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Artifacts (branch `eval/taskbank-v2`; code in `186f1b9` and `37f4b02`): the generalized `fit` stage (the cap is
  the workspace's POI bound, `MODIFIER_SETTINGS` explicit, `cls_at_cap_obs` and `cls_at_cap_exp` for
  curves above the scan; every LF value unchanged); the standalone `census`, `calc` and
  coordinator-only `figure` stage workers under the RAVEL stage supervisor, each in a run directory
  keyed by stage, input digests and parameters; the broker's registry input kinds (gzip event files
  stored unparsed), per-task prior recipes from the task definition (LF's custody lines unchanged),
  the `census` and `calc` operations (client and tool-guide rows) and the budget key
  `max_stage_executions` in the broker, the campaign manifest, the task definitions, the schema
  mirrors and the CLI. The runner reads each task's input kinds and recipe from its definition.
  Decisions E-120 to E-124; questions H-47 (the calc grammar's reading) and H-48 (the census gating).
- Tests: the new `test_stages.py` (census against the oracle on both public DY files, the truncated
  fixture, a gzip-level cut, an extra status-1 particle, the plan's final state, malformed records;
  the calc grammar, its exact evaluation and its worker; the figure) and new broker tests (custody of
  census, calc and figure prior recipes; subjects cannot call `figure`; handle stability within and
  across brokers; the stage budget; the cap read from a [0, 10] workspace against `counting.cls_at`;
  the lf-d laundering routes; bindings from mixed inputs). On the code of `186f1b9`, every test file
  of `tests/governance`, all through the shared lock in chunks under ten minutes that together cover
  the 3772 collected tests: all passed, 0 failed, 0 skipped (the reason for each changed existing test
  is in the commit message). `check_agent_surface` OK; `scripts/check_publication.py` OK;
  `tests/unit/test_export_safety.py` 22 passed. A follow-up (`37f4b02`) makes the census withhold its
  physics, instead of failing, when the record's plan has no final-state list; after it
  `test_stages.py` and `test_broker.py` were rerun (all passed). `6ac66bb` adds the end-to-end test of
  input subdirectories (`sample/`, `archive/`) and wraps long lines; after it the stage, broker,
  contract, treatment, full-stack, manifest and bank tests were rerun (all passed).
- Not run: anything paid; the real pinned binary; the smoke's campaign; anything on Linux; the
  repository's other suites (no file outside the governance package, its tests and these records
  changed).
- Unresolved scientific issue: unchanged (B-01, B-02); the bank's human reference review is deferred
  (E-34), and D-V keeps the bank to synthetic engineering campaigns (E-110).
- Next action: WP12 plan step 6 (the guard's field registry, dependency classes, pb, relation and
  categorical claims, and the calc and census fields), then the family builders (step 7).

### Iteration 14 — WP12 task bank, plan steps 6-7 (2026-09-27)

- Numbering: this was iteration 13 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Artifacts (branch `eval/taskbank-v2`): the delivery guard for the bank (`87d2421`): the registry's
  field registry replaces the version 1 field pattern, stale codes follow each input kind's dependency
  class, claim version 2 (pb rescaled to fb, relation claims in the kernel status's direction,
  categorical values), supplied records license numbers by unit; `unresolved_value` stays out; the
  broker still accepts only version 1 claims (E-125). The counting oracle's pre-fit convention
  helper, optional prior side and `cls_at_cap` per side (`6637950`, E-129). The shared builder
  `tasks/builder.py` and the kx family (`59d3a9e`), hv (`dffe851`, with shared-evidence visibility,
  E-126), mq (`06b77e9`, with the pinned LHE samples) and tz (`5677e78`): each write-once with the bank
  canary and path roles, effect floors from the fault values, convention and collision checks, the
  visibility declarations, the twin-difference check, value canaries and the a/b draw from the
  frozen seed (kx-b, hv-a, mq-b, tz-b valid). Every campaign freezes the 12-task bank; only
  likelihood_freshness is schedulable until the evaluator profiles and fake behaviours exist
  (E-127); the runner checks oracle canaries per oracle kind and reads value canaries from the bank
  index (E-128). Decisions E-125 to E-130; questions H-49 to H-52.
- Tests: the guard's version 1 behaviour is pinned by a 794-case golden corpus recorded before the
  change (all identical), plus the step-6 tests (a kx `gt` bound not blocked, an `eq` claim at the cap
  not blocked, the mq draft not blocked, lf-d calc laundering refused or stale, pb, declared units,
  categorical claims, dependency classes, supplied-record licensing); the new
  `test_bank_families.py` (55 tests: each family's inputs, oracle, fault, convention and visibility
  tables, build failures, the shared rules, and a real broker per task reproducing the predicted
  prior artifacts, the kx fit's CLs at the cap and the tz census). On the code of `5677e78`, every
  test file of `tests/governance`, all through the shared lock in chunks under ten minutes that
  together cover the 3843 collected tests: all passed, 0 failed, 0 skipped (the reason for each
  changed existing test is in its commit message). `check_agent_surface` OK (every commit);
  `scripts/check_publication.py` OK; `tests/unit/test_export_safety.py` 22 passed.
- Not run: anything paid; the real pinned binary; the smoke's campaign; anything on Linux; the
  repository's other suites (no file outside the governance package, its tests and these records
  changed).
- Unresolved scientific issue: unchanged (B-01, B-02); the bank's human reference review is deferred
  (E-34); D-V keeps the bank to synthetic engineering campaigns (E-110), now with the shared-evidence
  declarations of E-126 (H-50).
- Next action: WP12 plan step 8 (the evaluator's scoring profiles: LF first, then kx, hv, mq, tz,
  with E-116's scope verdict and the tables in the oracle records), then step 9 (the 12-task synthetic
  campaign and the naive behaviours; the families become runnable).

### Iteration 15 — WP12 task bank, plan steps 8-9 (2026-09-27)

- Numbering: this was iteration 14 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Artifacts (branch `eval/taskbank-v2`): the evaluator's scoring profiles (`a29bbbe`): `audit.py`
  dispatches by family, likelihood_freshness stays its own rules (version 1 reports, unchanged
  outputs), the four new families are scored by `audit_bank.py` over each definition and oracle
  record (the §1.6 verdict order with the clause rules before the fault values, attributed
  restatement, fault and convention values with their collisions, relation and categorical claims,
  evidence constraints, generic refusal validity with the boilerplate exclusion for every family);
  judge report schema version 2 with its mirror; the verdict `scope_change` for E-116; the broker
  accepts claim version 2; the scorer id binds both evaluator sources (E-131 to E-134). The fake
  subject's behaviours (`0bac66f`): family detection by inputs, each family's reference route, each
  pair's naive behaviour, `boilerplate_refusal`; every family runnable, so the default schedule is the
  12-task bank, and `build-synthetic --task` (E-135, E-136). Decisions E-131 to E-136; questions
  H-53 to H-58.
- Tests: `test_audit_bank.py` (26: the profiles' rules on the frozen records, and one campaign of the
  eight new tasks x 4 arms with reference, naive, over-refusal and boilerplate refusal per task: the
  references complete validly or refuse validly (kx's `gt` bounds supported), each naive gives its
  verdict (kx `cap_as_root`, hv `swapped_roles` in prose, mq `pb_as_fb`, tz `record_as_census` and an
  unbound cross section), over-refusals are false refusals and a boilerplate refusal is never valid);
  `test_bank_fullstack.py` (3: the 12 x 4 campaign through the CLI with each pair's naive behaviour in
  every arm; twin discrimination; the block arms differ on lf-p1, lf-p2, kx (sigma_vis claims only)
  and tz and not on mq or hv's prose). On the code of `0bac66f`, every test of `tests/governance`,
  all through the shared lock in chunks that together cover the 4024 collected tests: all passed,
  0 failed, 0 skipped (the likelihood_freshness full-stack chunk took 610 s under load, past the tool's
  foreground limit, and finished in the background: 36 passed). Each changed existing test has its
  reason in its commit message. `check_agent_surface` OK (every commit).
- Not run: anything paid; the real pinned binary; the smoke's campaign; anything on Linux; the
  repository's other suites (no file outside the governance package, its tests and these records
  changed).
- Unresolved scientific issue: unchanged (B-01, B-02); the scoring rules of the new profiles are
  provisional (H-53 to H-58, PKT-D04); D-V keeps the bank to synthetic engineering campaigns (E-110,
  E-126).
- Next action: WP12 plan step 10 (the tool guide documents claim version 2, the census and calc fields
  and the estimand; the guard's permitted-actions sentence; the prompt's resource sentence with the
  stage limit; the treatment digests; the packet-similarity check outside the repository), then step
  11 (the review packet, with H-49 to H-58).

### Iteration 16 — WP12 task bank, plan steps 10-11 (2026-09-27)

- Numbering: this was iteration 15 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Artifacts (branch `eval/taskbank-v2`):
  - **Step 10** (`67c6791`):
    - The regenerated tool guide (E-137). It is one text for every task and documents claim schema
      version 2 with a table of every registered field (its artifact, unit and role), the full
      estimand, the fit's POI range read from the workspace, the census fields and when physics is
      withheld, the calc rules and the precision sentence.
    - The prompt's resource sentence now states the census and calc limit. The guard's
      permitted-actions sentence no longer names the likelihood stages. The operation-schema digest
      binds the claim version 2 mirror (E-138).
    - The digests of the tool guide and of the treatment manifests regenerated at that revision
      (E-139).
    - The packet-similarity check, run outside the repository: the longest run shared with the
      packet is 4 words, and the best paragraph ratio is 0.28. A test makes E-36's six-word rule
      permanent for the bank's texts (E-140).
  - **Step 11** (`7b8db34`): [taskbank-review-packet.md](taskbank-review-packet.md) (E-141), with
    the construction, the cross-check, tolerance, margin, convention and collision tables, D-V as
    applied, the PKT-D05 realism questions, design §5's reference-review checklist and H-40 to H-61.
    While assembling it, the lead found that the likelihood_freshness profile does not apply the
    design's pre-fit convention values. This is recorded and not changed (E-142, H-61).
  - `4a74776`: slice-design §5a (the bank's families), and §2, §4.5, §6 and §7 updated; the
    governance README's module table.
  - Decisions E-137 to E-142; questions H-59 to H-61.
- Tests, all through the shared lock on this macOS 15.5 host with Seatbelt and `.venv-dev` (Python
  3.12.13):
  - New: two tool-guide tests in `test_broker.py` (the guide against the registry, and its
    neutrality) and the packet test in `test_treatment.py`.
  - Changed, with the reasons in `67c6791`'s message: the pinned permitted-actions sentence in
    `test_guard.py`, and the policy format in `test_campaign_fullstack.py`.
  - On the code and records of `4a74776`, every test of `tests/governance`, in 11 node-id chunks
    that together cover the 4027 collected tests (their union was checked against the collected set):
    all passed, 0 failed, 0 skipped. The likelihood_freshness full-stack module ran in two halves
    (338 s and 384 s); `test_bank_fullstack.py` took 325 s.
  - A synthetic 12-task campaign built at `67c6791` passed `treatment-diff --behavioral`.
  - `scripts/check_publication.py` OK; `scripts/check_evidence.py --check` 17 PASS, 0 WARN, 0 FAIL
    (both with `.venv-dev/bin` first on `PATH`); `check_agent_surface` OK on every commit;
    `tests/unit/test_export_safety.py` 22 passed.
- Not run: anything paid; the real pinned binary; the smoke's campaign; anything on Linux; the
  repository's other suites (no file outside the governance package, its tests and these records
  changed).
- Unresolved scientific issue: unchanged (B-01, B-02). The bank's human reference review is deferred
  (E-34), and the packet for it is ready. D-V keeps the bank to synthetic engineering campaigns
  (E-110). The new questions are H-59 to H-61.
- Next action: WP12 plan steps 1 to 11 are done. Before the bank scores anything, the consolidated
  review of the packet must decide H-40 to H-61. A development pilot needs its own authorization
  (E-34) and a budget (the runner's default, 40 operations, 4 fits and 600 s, still differs from the
  design budget of 30, 3 and 900 s). Merging `eval/taskbank-v2` into `evaluation-slice` is the
  integration owner's call. The paid smoke must still run from its own checkout (E-24).

### Iteration 17 — WP12 task bank, repairs after the engineering review (2026-09-27)

- Numbering: this was iteration 16 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Input: the engineering review of branch `eval/taskbank-v2` at `f00fb69` (two blockers, seven
  majors and ten minors from an evaluator lens, an engineering lens and a statistics lens). Every one
  was repaired; none was judged wrong. Where the review offered alternatives, the choice is recorded.
- Artifacts (branch `eval/taskbank-v2`):
  - `232b496`, code and tests:
    - Grouped thousands ("33,083.27 events") are one number in the guard and the evaluator, and a
      scale word before "events" multiplies (E-156). A correct mq delivery had been `unit_error` and
      falsely blocked.
    - The likelihood_freshness profile reads claim version 2: calc and census artifacts, pb, relation
      claims, fields it does not score, and a caught evaluator defect per run; every version 1
      verdict is unchanged (E-150).
    - Attributed restatement rebuilt: only supplied inputs and prior artifacts are sources, a
      correction must be predicated of the source, and attribution never yields an invalid verdict
      nor licenses a fault value (E-143).
    - Census claims judged per copy, and every census field the oracle computes scored (E-144).
    - kx: the nearer-answer rule, recall values separable at their printed precision, the published
      S95_exp and band added, the pre-fit widening and the pre-fit CLs at the cap listed (E-145).
    - The calc result's unit outside mq (E-146), coarse absolute diagnostics (E-147), the role
      `diagnostic` (E-148), the kx refusal matcher failing toward human review (E-149).
    - Campaigns frozen before WP12 verify and are audited; the runner refuses them (E-151). verify
      rejects a task-bank index without its rules and checks the environment's binding of the index
      (E-157).
    - The truncated LHE fixture moved to `benchmarks/governance/tasks/data/` (E-152); the a/b seed
      comment corrected (E-153); the kx citation names the table by its label (E-158); the tool
      guide's estimand sentence covers the observed limits (E-155).
    - The fake subject's reference reports read as an analyst's, and a new cohort runs the reference
      in every arm (E-154).
  - The records commit: decisions E-143 to E-158 and questions H-62 to H-66 (H-51 and H-53 carry
    dated updates); the review packet, the oracle appendix and the slice design updated; the new
    digests (E-155).
- Checks outside the test suite:
  - A campaign built and run with the `8dbc4a2` code in scratch verifies with this code, and this
    code's 8 judge reports of it equal the `8dbc4a2` evaluator's apart from the scorer id (E-151).
  - The paid smoke store, read in place and never written, verifies with this code, and
    `build_report` reproduces its 8 stored judge reports apart from the scorer id (E-151).
  - `treatment-diff --behavioral` passed on a scratch 12-task campaign built at `232b496`; the
    packet-similarity check, rerun outside the repository, found no shared run longer than 4 words
    (E-155).
- Tests, all through the shared lock on this macOS 15.5 host with Seatbelt and `.venv-dev` (Python
  3.12.13):
  - New: the review's cases as regression tests in `test_audit_bank.py` (a realistic-phrasing corpus
    for both twins of every pair, grouped numbers, census copies, the kx nearer-answer rule, the
    disclosed widening, the CLs diagnostics, the calc unit, the refusal matcher, and a
    reference-in-every-arm cohort of 32 runs), `test_guard.py` (grouped numbers, the diagnostic
    role), `test_audit.py` (claim version 2 in LF runs, an evaluator defect as an unscorable row, a
    pre-WP12 budget audited), `test_campaign_manifest.py` (the bank index's rules and binding, the
    legacy budget), `test_contracts.py` (the legacy budget), `test_bank_families.py` (recall
    separability) and `test_live_host.py` (the build's dependency on the pinned LHE files).
  - Changed, with the reasons in `232b496`'s message: expectations the repairs change in
    `test_audit_bank.py`, `test_bank_families.py`, `test_contracts.py`, `test_guard.py` and
    `test_broker.py`, and the fixture path in the LHE tests.
  - The whole of `tests/governance` on the final code (`fdc6d35`, whose only change after
    `96f56f6` is the tz family docstring naming the fixture's new place): all 4080 collected tests
    passed, 0 failed, 0 skipped, in 23 node-id chunks whose union was checked equal to the collected
    set. The host was heavily loaded by another project's builds (load averages about 15 to 147 on 8
    cores). So `test_bank_fullstack.py` (3 tests) timed out twice at its own 540 s cap on the CLI
    `run` step, and passed in 1321 s with that cap raised to 1800 s by a scratch pytest plugin
    outside the repository that changes no assertion; the unmodified module had passed at `232b496`
    in 322 s on a lighter host. The runner's last third and the LF full-stack thirds passed in 12
    to 20 minutes each.
  - An interrupted earlier run had one live-host failure (`test_real_launch_starts_and_stops_its_own_proxy_on_every_path`,
    refused with code `treatment`). It ran while `96f56f6` edited `audit_bank.py` and the slice
    design, which the harness binds (`runner.harness_manifest`, the protocol digest). The test passed
    alone and in its chunk on the unchanged tree.
- Not run: anything paid; the real pinned binary; anything on Linux; the repository's other suites
  (no file outside the governance package, its tests and these records changed).
- Next action: the consolidated review of the packet, now with H-62 to H-66. Merging `eval/taskbank-v2`
  into `evaluation-slice` is the integration owner's call; after the merge the smoke store stays
  verifiable and auditable (E-151).

### Iteration 18 — WP12 task bank, repairs after the second review (2026-09-28)

- Numbering: this was iteration 17 on `eval/taskbank-v2`; renumbered at the merge (iteration 19),
  since `evaluation-slice` had its own iteration 11 (the real-host engineering smoke).
- Input: the second review of 2026-09-27, of branch `eval/taskbank-v2` at `8f8a3d4` (one blocker,
  ten majors and thirteen minors). The blocker, every major and every minor were repaired, with one
  exception: the minor on the behavioural treatment check had two halves, and only one was built.
  - Built: the reference-in-every-arm cohort gained another analyst's citations and phrasing.
  - Deferred: claim version 2 probes in the product check (H-89). They need a new record section that
    the stricter gate re-derives, and the tests already cover the false blocks they would catch.
  Where the review offered alternatives, the choice is recorded. No finding was judged wrong.
- Artifacts (branch `eval/taskbank-v2`):
  - `a764f33`, code and tests:
    - tz's required endpoints are the three facts the request asks for. Completeness and identity
      are scored only when claimed (E-170, the blocker).
    - The guard and the evaluator read evidence alike (E-169):
      - a bound in fb takes the luminosity of any cited record, a conversion included;
      - a version 2 claim is judged against the cited artifacts of its field's own kind, and one
        of them holding it suffices.
    - A figure holds the values it plots. The hv naive behaviour types the legend citing the
      figure (E-171).
    - Scoring repairs:
      - a secondary calc result is unresolved (E-166);
      - weaker or contrary bounds are unresolved, and a bound on the wrong side is wrong_value
        (E-167);
      - a relation on a CLs diagnostic is judged as a relation (E-168);
      - an integer with trailing zeros is read at its last nonzero digit (E-172).
    - Reading repairs:
      - a declined input beside a complete delivery is a named extra (E-173; LF unchanged, E-178);
      - prose roles are named, ordered or unresolved (E-174);
      - index numbers are no counts (E-175);
      - the kx refusal matcher and the boilerplate rule are narrowed (E-176, E-177).
    - Other repairs:
      - recipe_check has an oracle definition (E-165);
      - derived kx recall values have their own mechanism (E-180);
      - the registry is part of the treatment and scorer identities (E-179);
      - `cli.py audit` fails on evaluator-error rows (E-181);
      - test timeouts scale with an environment variable (E-182);
      - a runtime value-canary test covers every new family (E-183);
      - the schema mirrors are corrected (E-184).
    - A new fake behaviour, `reference_variant`, and its cohort (E-186).
  - `3e767b9`, the records: decisions E-165 to E-186 and questions H-80 to H-89 (H-65 and E-158
    reworded); the review packet, next-actions (with the merge note), the slice design, the README
    and the DIRECTORY row; the new digests (E-185).
  - The last commit, a request-literal tz campaign through the CLI in `test_bank_fullstack.py`, the
    packet's re-record rule, and this iteration.
- Checks outside the test suite:
  - The paid smoke store, read in place and never written, verifies with the code of `a764f33`.
    `build_report` reproduces its 8 stored judge reports apart from the scorer id (E-151 holds).
  - `treatment-diff --behavioral` passed on a scratch 12-task campaign built at `a764f33`.
  - The packet-similarity rerun outside the repository found no 5-word run; the best paragraph
    ratio was 0.28 (E-185).
  - The stage's `recipe_check` equals the oracle's on every census copy.
  - A mutation that skipped the new families' value canaries failed the new runner test.
  - `git merge-tree` against `evaluation-slice` (`803d9d3`) shows conflicts in `DIRECTORY.md`,
    `decisions.md` and `plan.md` only (next-actions item 8; item 4 on that branch).
- Tests, all through the shared lock on this macOS 15.5 host with Seatbelt and `.venv-dev` (Python
  3.12.13):
  - New in `test_audit_bank.py`:
    - the secondary calc results;
    - the weaker and contrary bounds;
    - the kx bound citing a conversion and the CLs relation, in the guard and the evaluator;
    - the hv figure transcription;
    - the hv prose phrasings;
    - the tz truncation descriptions;
    - the request-literal tz delivery and `recipe_check`;
    - both mq calcs cited;
    - large integers;
    - the refused object;
    - the denied condition;
    - the wrong-reason refusals;
    - the reference_variant cohort, 32 runs.
  - New elsewhere:
    - `test_audit.py`: the lf-d boilerplate rule in both directions, and the evaluator-error row;
    - `test_runner.py`: the value canary of every bank family, and the CLI audit failing on an
      evaluator-error row;
    - `test_contracts.py`: the legacy budget in the schema mirror;
    - `test_bank_families.py`: the stage's `recipe_check` against the oracle's;
    - `test_bank_fullstack.py`: a request-literal tz campaign through the CLI.
  - Changed on purpose, with the reasons in `a764f33`'s message:
    - the tz endpoints, `open_block_counted` and the kx recall mechanism;
    - the fake behaviour list;
    - the CLI audit output;
    - the guard implementation digest;
    - the scorer-id sources;
    - the hv naive route.
  - The whole of `tests/governance` passed: all 4131 collected tests, 0 failed, 0 skipped.
    - They ran in 15 node-id chunks, and their union was checked equal to the collected set.
    - The code was that of `a764f33` throughout. Every test file but `test_bank_fullstack.py` was that
      of `3e767b9`. `test_bank_fullstack.py` gained the literal tz test afterwards and ran last,
      in its final form.
    - Another project's builds loaded the host heavily, with load averages up to 105 on 8 cores.
    - The LF full-stack halves took 808 s and 915 s. They ran past the 10-minute tool limit and
      finished in the background, uninterrupted.
    - The audit_bank chunks took 214 s, 351 s and 306 s.
    - `test_bank_fullstack.py` passed in 515 s and 71 s with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3` (E-182).
- Not run:
  - anything paid;
  - the real pinned binary;
  - anything on Linux;
  - the repository's other suites (no file outside the governance package, its tests and these
    records changed).
- Next action: the consolidated review of the packet, now with H-80 to H-89. Merging
  `eval/taskbank-v2` into `evaluation-slice` is the integration owner's call (next-actions item 8;
  item 4 on that branch).

### Iteration 19 — merge of the WP12 task bank (2026-09-28)

- Artifacts: `eval/taskbank-v2` (tip `92ccc5f`, iterations 12 to 18 here) merged into
  `evaluation-slice` (tip `803d9d3`) with `git merge --no-ff`, in the commit that adds this entry.
  Git merged every code and test file without a conflict, `live.py`'s LC-18 collector (E-162) and
  both branches' changes to `test_live_host.py` included; the conflicts were in `DIRECTORY.md`,
  `decisions.md` and `plan.md`. Resolution (E-187): every entry of both branches is kept. No
  decision or question id was shared, so none was renumbered (the id mapping is the identity, and
  E-160 keeps the id the sealed smoke cites). The task bank's iterations 11 to 17 are 12 to 18 here,
  in ascending order after the smoke's iteration 11; `next-actions.md` merged textually with two
  items numbered 4, and the task bank's is item 8. CHANGELOG.md and docs/development/status.md named
  a four-variant development family; they now name the task bank.
- Code: no merge-induced change was needed.
- Checks at the merge, on this macOS 15.5 host with Seatbelt, `.venv-dev` (Python 3.12.13) first on
  `PATH`: `check_agent_surface` OK; `scripts/check_publication.py` OK; `check_evidence.py --check`
  17 of 17. The paid smoke store, read in place and never written (its paths, sizes, modes, times
  and SHA-256 digests identical before and after), verifies with the merged code (`cli.py verify`: 8
  judge reports, provenance OK), and `audit.build_report` reproduces its 8 stored judge reports
  apart from the scorer id (E-151 holds).
- Tests: `pytest tests`, all 6734 collected tests, through the shared lock in 24 node-id chunks
  whose union was checked equal to the collected set, with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3` (E-182):
  6693 passed, 41 skipped (optional dependencies uproot, onnx, yoda, spey and mplhep; the wheel
  checks; an unshipped archive; the native RJR toolchain), 0 failed. Of them `tests/governance` is
  4136 tests (the task bank's 4131 and the smoke's 5 LC-18 collector tests): all passed, none
  skipped. The chunks took 4565 s of test time at load averages from 6 to 85 from other workflows;
  the longest were the bank full-stack module (491 s) and the LF full-stack module (304 s).
- Not run: anything paid; the real pinned binary; anything on Linux; a new synthetic campaign
  through the CLI outside the test suite.
- Unresolved scientific issue: unchanged (B-01, B-02); the smoke and the task bank are engineering
  evidence only, and the bank's reference review and D-V (H-40, H-50) are open.
- Next action: the evaluator repair (E-163, next-actions item 4) on the merged `audit.py`, with the
  smoke's 8 transcripts as regression cases and a held-out check; the consolidated review of the
  task-bank packet (next-actions item 8).

### Iteration 20 — evaluator repair after the smoke (2026-09-28)

- Order, recorded in the commit messages: the held-out check `tests/governance/test_audit_heldout.py`
  was committed first (`c664208`), before any change to `audit.py` or `audit_bank.py`. It holds 50
  synthetic cases written from the rule descriptions of the five failure classes, with correct and
  incorrect deliveries and the fail-toward-null guards. The pre-repair evaluator failed 23 of them,
  every one a repair target. Two cases (c1b, c3b) were added after that first baseline run, before any
  code change.
- Artifacts: the repair (E-188, `638a09d`), then the regression cases and `rejudge` (E-189, `f29422b`). (a) Non-primary claim roles are judged as the field's own, in both
  profiles. (b) Header-aware pipe tables. (c) Annotations after a value bind to that value; ±nσ
  notation names no cross section for refusal validity; registered artifact field names bind their
  unit and role. (d) Absence-statement variants. (e) A prior value quoted to reject it is historical.
  `SCORER_ID` is now `ravel-eval-mechanical/e64ae0848fcb`. The 8 smoke runs are replayed regression
  cases (`tests/governance/fixtures/smoke/`, `test_audit_smoke.py`): minimal subject texts, claims,
  operations and task records only, each file under 200 KB. With the pre-repair evaluator the replay
  reproduced all 8 sealed judge reports exactly. Their expected cells were fixed after the repair, from
  the rules (E-188 records this departure from E-163). Development tests are in `test_audit_repair.py`,
  with one task-bank role test and two updated table expectations in `test_audit.py`. `cli.py
  rejudge` (E-189) is tested for refusals on the replay campaign and for its written path on the CLI
  full-stack campaign, whose tree is byte-identical before and after.
- Held-out result at the first post-repair run: 48 of 50 passed. c1b and c3b failed on their first
  value, because the fragment's "Band" is expected-role wording in slice §11 (an expectation error).
  They are kept as written and marked xfail(strict).
- Re-judged smoke (smoke-record.md, "Re-judged with scorer `e64ae0848fcb`"; the store was byte-identical
  before and after): run 5 is clean (unsupported true to false); run 3 goes from true to null; runs 2
  and 4 are valid refusals (null to true); reason matched is true in all four refusals. Runs 1 and 8's
  refusals and the other completions stay null, for the reasons recorded there.
- Found and not fixed (pre-existing): the E-28 marked-after route reads "I cannot say the previous <n>
  was not used" as historical, because that subject is not negated; and `_bindings` is quadratic in a
  long sentence with many marked prior values (its subject scan starts at the sentence start). The
  megabyte CPU-time test does not cover that shape. The E-188 code adds only bounded or bisected
  searches.
- Tests: all of `tests/governance` (4229 collected: 4136 before, plus 50 held-out, 29 development, 12
  regression, 1 task-bank and 1 table case), run through the shared lock in 24 node-id chunks. The
  chunks were checked to equal the collected set, and every one ran with
  `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`. Result: 4227 passed, 2 xfailed (the recorded held-out failures), 0
  failed, in 3544 s of test time. `check_agent_surface`, `scripts/check_publication.py` and
  `check_evidence.py --check` (17 of 17) passed, and so did the records, publication and hygiene unit
  tests (114).
- Not run: anything paid; the real pinned binary; anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02). The re-judged smoke is engineering evidence
  only, under provisional rules (H-13, H-90).
- Next action: the pilot request (next-actions item 7) and the consolidated review (E-34), which now
  includes H-90.

### Iteration 21 — repair after the review of the evaluator repair (2026-09-28)

- The review of E-188 found one blocker, five major and four minor issues (E-190 lists them by rule).
  None was judged wrong. Two were built more conservatively than proposed: a value stated as the
  result is never made historical, even when the rejection's subject is the value itself; and a
  header's own rejection makes a cell unresolved, not historical. One was extended: "(±nσ)" after a
  single value is ambiguous too.
- Order (E-163): the review's probes and the unit-carry probes S1 to S6 were committed first as a
  second held-out batch (`a5029c3`, 57 cases). The evaluator at `6f90e67` failed 54 of them and passed
  the 3 controls. After the change all 57 pass; no held-out expectation was edited.
- Artifacts: `audit.py` (E-190; `SCORER_ID` `ravel-eval-mechanical/dc3f775e427a`), 21 development tests
  in `test_audit_repair.py`, one of whose E-188 expectations moves from historical to unresolved ("it
  is the luminosity I use" reasserts the value). The replayed smoke is unchanged. The new scans are
  bounded (a number's own clause, at most 300 characters each side; a list line's heading, at most 24
  lines of at most 400 characters, found once per line); the megabyte CPU-time test passes.
- Re-judged smoke (E-191; smoke-record.md, "Re-judged with scorer `dc3f775e427a`"): every cell and
  all 245 findings equal the `e64ae0848fcb` re-judgment; the store was byte-identical before and after.
- Not done, and flagged as a precondition for scoring the next campaign (next-actions item 4): the
  task-bank profile (`audit_bank.Scale`) has no stray-decimal pass, so there a stale value in a
  label-value line, a numbered line or a semicolon clause is still dropped. Known coverage gaps,
  failing toward null, are recorded in slice §11 (bracketed pairs and ranges, "not carried forward",
  a unit label before a number or a list).
- Tests: all of `tests/governance` (4307 collected: 4229 before, plus 57 held-out and 21 development
  cases), run through the shared lock in 37 node-id chunks, each in the foreground with
  `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`. The chunks were checked to equal the collected set. Result: 4305
  passed, 2 xfailed (the E-188 recorded held-out failures), 0 failed, in 4993 s of test time.
  `scripts/check_publication.py` and `check_agent_surface` passed.
- Not run: anything paid; the real pinned binary; anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02). The re-judged smoke is engineering evidence
  only, under provisional rules (H-13, H-90, H-91).
- Next action: the task-bank profile's stray pass before any bank campaign is scored; the pilot
  request (next-actions item 7); the consolidated review (E-34), which now includes H-91.

### Iteration 22 — the development-pilot request (2026-09-28)

- Drafted [pilot-request.md](pilot-request.md), the costed request for the WP16 development pilot
  that the owner decides (H-73). Nothing is authorized, and nothing paid ran.
- Proposed design A: all 12 bank tasks x 2 seeds x 4 arms = 96 assignments, one shuffle of the roster by
  the schedule seed, the smoke's pin, model and effort (E-40), c = 2.0 USD and 900 s per run, the bank's
  design budget, G = 192 USD, and a worst case of 192.67 USD only at k = r = 0 and the smoke's T (not
  a bound fixed in advance: the pilot re-measures T, and k and r hold the campaign at the review pause).
  Alternatives: B with 48 and C with 144 assignments.
- Numbers: the smoke's per-run CLI costs and wall times (mean 0.324 USD and 174 s); `analysis.cost_plan`
  (c 2.0, h 0.25, q 5); and `analysis.design_simulation` (5 families; 2, 4 or 6 blocks; arms at 0.5;
  missing 0 to 0.75; seed 20260928; n_sim 1000; n_bootstrap 1000). With no missing outcomes, A's
  interval for `full_minus_instructions` is 0.43 wide and detects +0.4 with probability 0.90. At 25 %
  missing or more, no design detects any grid effect. The re-judged smoke's missing rate was 0.75 (n = 4).
- Preconditions before launch, as listed there: the owner's decisions (H-71, H-72 and H-21, H-70, B-07,
  and H-20 for this campaign); the task-bank stray pass and the E-28 marked-after fix; HP-13's
  absent-geography case; a pilot approval kind and authorization text in the live build (both are
  smoke-only now), binding the schedule seed and the broker limits too; the pilot budget; an
  offline rehearsal and S7 probes on the pilot campaign; E-96. The consolidated review can wait. Results
  stay synthetic engineering evidence while the D-V waivers stand (E-110).
- Tests: `tests/unit/test_directory_reconciled.py`, `test_records_reconciled.py`,
  `test_repository_hygiene.py` and `check_agent_surface`.
- Review repair (2026-09-28): the worst case is labelled conditional on k = r = 0 and the smoke's T,
  with a hold on k ≥ 1 or r ≥ 1; the page no longer says the approval binds the schedule seed (the
  pilot kind is to bind it and the broker limits); the review pause moves from a fixed 8 runs, which
  miss at least one unmeasured family with probability 0.685, to the first position where every
  family has two runs, with a hold instead of an S8 stop; E-28's marked-after fail-open joins the
  engineering preconditions; and the precision text is corrected (1.14, Monte Carlo error on C's
  ±0.3, the inflated false exclusion rate, optimistic widths, 7 of 8 unresolved on
  `unsupported_claim`, every WP12 path untested live).
- Next action: the owner's decision on the request; the engineering preconditions in its order.

### Iteration 23 — the pilot request's engineering item 1: two false-clean paths (2026-09-28)

- Scope: pilot-request.md "Before launch", engineering item 1. (a) The task-bank profile had no stray
  pass, so a stale or fault value in a label-value line, a numbered line or a semicolon clause was
  silently dropped. (b) E-28's marked-after route read "I cannot say the previous <n> was not used" as
  historical. Both could give a false clean verdict.
- Order (E-163), recorded in the commit messages: a third held-out batch (67 SYNTHETIC cases at the end
  of `test_audit_heldout.py`, `1d226ab`) was committed before `audit.py` or `audit_bank.py` changed.
  The evaluator at `f21ebff` (scorer `dc3f775e427a`) failed 58 and passed 9: B19 and D20, which earlier
  rules already caught, and the controls C1 to C7. After the change (`f7a2824`) 65 pass. B16 and K4 fail
  on their own expectations (a finding reports a pb number in canonical fb; the LHE header cross
  section is an input restatement, not supported); they are kept as written and marked xfail(strict).
  No held-out expectation was edited.
- Probing for relatives, beyond the two named paths: integer counts and published values in the same
  shapes (tz, kx), a fault written in pb under a "(pb)" heading, which E-190 also read as fb in the
  likelihood_freshness profile, and a unitless cross section whose digits are the answer in pb and the
  fault in fb (mq). For (b): the verb route, the label route, the change route, E-188's rejection route
  under a negated frame, and a doubted retraction that withdrew a claim. Two relatives of the stray pass
  were quadratic: E-190's rescan of the sentence per stray number (8000 numbers in a 120 KB sentence
  took 196 s) and the task-bank reader's attribution scan from the sentence start.
- Artifacts: E-200 (the task-bank stray pass, the carried unit, identifiers, the fb/pb ambiguity),
  E-201 (the doubting frame, `_DOUBT` and `_Doubts`, for supersession, change, rejection and retraction
  statements, read per clause), E-202 (linear time: `_Carry`, `ANNOTATE_REACH`, the `_bindings` slice).
  `SCORER_ID` `ravel-eval-mechanical/87e336893f5c`. Development tests: 17 in `test_audit_repair.py`, 6
  in `test_audit_bank.py`. Review question H-100.
- The replayed smoke (`fixtures/smoke/`, 8 runs) is unchanged: every cell and all 245 findings equal
  the `dc3f775e427a` replay, verdict for verdict (compared outside the suite with both scorers). The
  sealed smoke was not re-judged.
- Tests: all of `tests/governance` at `f7a2824` (4398 collected: 4307 at iteration 21, plus 67
  held-out, 23 development and 1 task-bank family case added since), run through the shared lock in 41
  node-id chunks on the iteration-21 layout, each in the foreground with
  `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`; the union of the chunks' JUnit records equals the collected set.
  Result: 4394 passed, 4 xfailed (E-188's c1b and c3b, and B16 and K4), 0 failed, in 7161 s of test
  time on a loaded machine (three chunks ran past 10 minutes of wall time and were waited for).
  `check_agent_surface`, `scripts/check_publication.py`, `check_evidence.py --check` (17 of 17) and the
  records, directory and hygiene unit tests (15) passed.
- Not run: anything paid; the real pinned binary; anything on Linux; a re-judgment of the sealed smoke.
- Unresolved scientific issue: unchanged (B-01, B-02). The rules stay provisional (H-13, H-90, H-91,
  H-100). Still open, failing toward null: a unit label before a number or a list, bracketed pairs and
  ranges, "not carried forward"; not read: an integer in prose or in an unstructured line; the
  pre-existing `_bindings` subject scan for many marked prior values in one sentence.
- Next action: the pilot request's remaining engineering items (2 onward) and the owner's decisions.

### Iteration 24 — the pilot request's engineering items 2, 3, 4 and 6 (2026-09-28)

- Scope: pilot-request.md "Before launch", engineering items 2 (LC-16 without a reported geography), 3
  (a pilot approval kind and authorization), 4 (the pilot budget in the live build) and the E-96 part of
  6 (census a lost run launch before preflight). Nothing paid ran; `~/.config/ravel-eval/` and the sealed
  smoke were not touched (the smoke's adapter results were only read).
- Item 2 (E-203): the pinned bundle multiplies a request's cost by 1.1 only when `inference_geo` is
  exactly "us" (`ZA`, found in the binary's bytes). HP-13 now also measures "not_available", the value
  every smoke run reported. The zero-cost variant on the real pin: rehearsal campaign P, built from
  `3c7bb46` in scratch with a pilot-kind rehearsal approval and the design budget, a dummy token in a
  scratch file, a deny-all proxy, the local mock API, the approval ledger in scratch and the tests'
  signal guard; `host-probe --rehearse --catalog-rates` passed every required probe it ran (HP-09 was not
  run; the non-required HP-10 and HP-11 failed, as in the earlier rehearsal H of `8dbc4a2`) with `cli_geo_multiplier` {"us": 1.1, "not_available": 1.0}, no unclean
  probe launch and nothing refused by the guard. With that record LC-16's recompute, replayed read-only,
  verifies all 8 smoke runs with no flag (all 8 were unverified before).
- Items 3 and 4 (E-204, E-205): the kind `synthetic_engineering_pilot`, which also binds the schedule
  seed, the broker limits and the roster order; the pilot's authorization text; `live.design_budget` and
  `build-live --design-budget`. The design budget passes the bank rules and the approval (mock CLI tests;
  campaign P on the real pin). `contracts.py` is part of the operation schema digest, so it and the four
  arm manifests moved (E-207; the review packet §8 re-recorded); `treatment-diff --behavioral` passed on a
  scratch 12-task campaign built at `3c7bb46`. `SCORER_ID` is unchanged (`87e336893f5c`).
- Item 6, E-96 part (E-206): `run` censuses every journaled but unclosed lost run launch by its
  `process_started` record before preflight (`live.census_lost_runs`, `precensus-<k>.json`), through the
  unchanged `isolation.census_launch`, and refuses while one stays unclean; the resume seals those
  censuses with its own. Tested under the tests' signal guard with a coordinator killed by SIGKILL and
  with a lost launch whose group cannot be proven (never signalled).
- Tests: 60 new (43 contract cases, 17 live-host tests: the pilot approval, the design budget, LC-16
  with and without the measured geography end to end, and the two census cases); the rehearsal test
  expects the second geography. All of `tests/governance` at `3c7bb46` (4458 collected: the 4398
  of iteration 23 plus the 60 new) ran through the shared lock in 47 node-id chunks (iteration 23's
  layout, the new tests in two added chunks, the slowest chunks split), each started in the foreground
  with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`; the union of the chunks' JUnit records equals the collected
  set. Result: 4454 passed, 4 xfailed (as in iteration 23), 0 failed, in 9032 s of test time on a loaded
  machine (load average up to 30; eight chunks ran past 10 minutes of wall time and were waited for).
- Not run: anything paid; HP-09 or the offline run path on the pilot campaign (engineering item 5);
  anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02). New question H-101 (the approval's reach, the
  integer 900, the census refusal's recovery).
- Next action: engineering item 5 (an offline rehearsal of the exact 12-task roster and S6 and S7 on the
  pilot campaign), then S0 and S1; the owner's decisions (H-73 with H-71, H-72, H-21, H-70, B-07, H-20).

### Iteration 25 — the pilot request's engineering item 5: the offline rehearsal (2026-09-28)

- Scope: pilot-request.md "Before launch", engineering item 5. Nothing paid ran and nothing left the
  machine: the real pin ran only against a local mock Messages API with a dummy token in a scratch file
  and a deny-all proxy. `~/.config/ravel-eval/` and the sealed smoke were not touched. No code changed.
- Rehearsal campaign Q (E-208): built from `1c63d78` in scratch with a pilot-kind rehearsal approval
  (12 tasks in bank order x seed 11 x 4 arms, 48 assignments, schedule seed 7, the design budget,
  96.0 USD and 46080 s), the approval ledger in scratch and the tests' signal guard in every coordinator.
  Build, `verify`, `treatment-diff --behavioral` (lf-c), `host-probe --dry-start --rehearse
  --catalog-rates` (complete; every required probe passed, HP-09 and HP-13 included; `cli_geo_multiplier`
  {"us": 1.1, "not_available": 1.0}), preflight (PF-01 to PF-14), `run --limit 1`, the S10a go by the
  lead as rehearsal reviewer, `run` for the other 47 (11 min 24 s; no stop, hold or pause), `audit`
  (40 completions, 8 valid refusals, no evaluator error), `report`, `verify` and `live-checks --costs`
  (48 of 48 recomputes equal to the reported cost) all passed. An independent walk of the rehearsal tree
  found the dummy token only in its credential file.
- The mock's scripted sessions (a scratch driver, like E-88's and E-101's): per family, one Bash call of
  the task client per operation of the reference route (inputs, show, fit, convert, report, census,
  calc), a helper written with Write, a submission of claim-version-2 claims Read and Edited before
  `submit`, then `status`; dry-run first against a real in-process broker per task (12 of 12 accepted).
  So the WP12 paths ran through the real CLI for the first time: kx's fit above the scan and its
  refusal, the migrated LF tasks, keyed kernel receipts, the stage budget, the hv, mq and tz stages,
  claim version 2 and the 30/3/6 limits (at most 8 operations, 1 fit and 2 stage executions per run).
- LC-18 warned in 5 of 48 runs. Diagnostic campaign D (8 runs, same path) with `log stream` running
  showed the subject's own routine Seatbelt denials in every run while the post-run collector counted
  none: the log mostly does not keep them (E-209). Nothing changed; H-102 asks whether to build a
  per-launch stream collector.
- Tests: none of `tests/governance` reran, since no code changed after iteration 24's full run at
  `3c7bb46` (`1c63d78` changed records only). The records checks (agent surface, publication,
  evidence, and the directory, records and hygiene tests of `tests/unit`) ran on this commit.
- Not run: anything paid; the pilot's own campaign (it is built at S5 and needs S6 and S7 then); a
  rejected submission through the CLI, a naive or fault behaviour, a model's own text, a timeout or a
  stop rule firing; anything on Linux.
- Unresolved scientific issue: unchanged (B-01, B-02). New question H-102 (the sandbox-denial evidence).
- Next action: engineering item 6's open questions (H-22, H-25, H-30, H-31) and S0 and S1; the owner's
  decisions (H-73 with H-71, H-72, H-21, H-70, B-07, H-20).

### Iteration 26 — the repair after the review of the pilot's engineering (2026-09-28)

- Scope: the review of engineering items 1 to 6 (E-200 to E-209): 7 major and 9 minor findings.
  Nothing paid ran and nothing left the machine: the real pin ran only in zero-cost probes and the
  offline rehearsal against the local mock with a dummy token and a deny-all proxy.
  `~/.config/ravel-eval/` and the sealed smoke were not touched.
- Evaluator (E-210): a fourth held-out batch (76 SYNTHETIC cases, `1173a00`) was committed before
  `audit.py` or `audit_bank.py` changed. At `c723ecb` it gave 67 failed, 8 passed (controls) and 1
  xfailed. That was K4, which fails for a pre-existing reason outside the batch (the `_META` guard).
  After the change (`ea7a555`, scorer `10875c1f1bef`) 72 pass. P1 to P3 fail on their own
  expectation (tz's record_as_census is typed-claim-only by E-144 and E-175) and are marked
  xfail(strict); no expectation was edited. The review asked for an allowlist instead of a longer
  list. Both were built: more words, and an embedded statement is framed unless the frame is the
  writer's own assertion. Also built: the reach before and after a statement, the E-200 unit-carry
  regression, integers in tables and label lines, a doubted correction, and an input that is also a
  named prose fault value (kx's cap). The replayed smoke (245 findings) and a re-judgment of Q's 48
  sealed runs were unchanged, compared outside the suite.
- Live build (E-211 to E-213): the frozen approval is re-read by `verify` and preflight PF-15, and
  PF-15 needs the ledger's line for the campaign. A smoke approval covers at most 8 assignments and the
  default limits. A pilot's fixes max_turns at 100. For the lost launch, `_lost_census` uses lexists,
  an earlier incomplete precensus is kept as `census_incomplete`, an unclean sealed lost launch prints
  REVOKE, and the documented recovery is tested. The denial collector records pids, the
  subject-profile marker and the launch-attributed split. E-209's attribution was corrected.
- Judged partly wrong or not done: the review's tz example for the input-versus-fault precedence
  (the fault is typed-claim-only by design; the gap is real for kx and fixed); `campaign.json`'s
  sha256 in the ledger line, which would move the operation schema and arm digests (PF-15's ledger
  check covers the attack instead); scripted sessions that exceed the broker limits (the records now
  say the limits were never reached through the CLI).
- Rehearsal (E-214): Q's tooling, logs, ledger, stores and roots were copied to
  `local-runs/evaluation-slice/rehearsal-q/`. R2 re-ran the rehearsal from `f7b6ac4` with a new driver
  patch (the scratch ledger for PF-15). Build, `verify`, `treatment-diff`, the probes (complete),
  PF-01 to PF-15, run 1, the go, the other 47 (11 min 48 s, no stop), `live-checks --costs`, `audit`,
  `report` and `verify` all passed. On the real pin, a pilot build with `--max-turns 5` and a
  smoke-kind copy of the approval were refused. LC-18 warned in 11 runs; the new split attributes 0 to
  2 reports per run to the launch's leader, and one run's 15 reports came from a system daemon.
  R2's tooling, logs and stores are kept too (`local-runs/evaluation-slice/rehearsal-r2/`). Campaign R (`98ecd7b`) was built and probed but not
  run: the decision numbers in its code were corrected first (`f7b6ac4`).
- Tests: all of `tests/governance` at `f7b6ac4` (4570 collected: the 4458 of iteration 24 plus 76
  held-out, 24 and 7 evaluator development and 5 live-host tests) ran through the shared lock in 57
  node-id chunks (iteration 24's layout, the slowest split, the new tests in four added chunks), each
  started in the foreground with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`. The union of the chunks' JUnit
  records equals the collected set. Result: 4562 passed, 8 xfailed (c1b, c3b, B16 and the batch-3
  K4, the batch-4 K4 and P1 to P3), 0 failed, in 7690 s of test time.
- Not run: anything paid; the pilot's own campaign; anything on Linux; a re-judgment of the sealed
  smoke.
- Unresolved scientific issue: unchanged (B-01, B-02). New question H-103 (the repair's rules); H-102
  updated.
- Next action: the owner's decisions (H-73 with H-71, H-72, H-21, H-70, B-07, H-20, and H-102, H-103);
  S0 and S1 on the pilot's build revision, re-running the rehearsal if it differs from `f7b6ac4` in
  `benchmarks/governance`.

### Iteration 27 — the development pilot and its record (2026-09-28 to 2026-10-03)

- Scope: WP16, design A of [pilot-request.md](pilot-request.md), which the budget owner authorized in chat
  on 2026-09-28 (H-73 answered for the pilot), keeping the token (E-215). The lead agent session was the
  operator at the owner's request; H-71 was not decided (E-216). Record:
  [pilot-record.md](pilot-record.md).
- Execution (2026-09-29 UTC), campaign `pilot-claude-2.1.281-a` built from `8c89d4b`: S1 (`tests/unit`
  and `tests/adversarial` at `8c89d4b`, 2557 passed, 41 skipped, 0 failed; the governance half is
  iteration 26's run at `f7b6ac4`), build, `verify`, `treatment-diff --behavioral`, `host-probe`
  (complete, every required probe passed), PF-01 to PF-15, run 1 (mq-b enforcement, 0.334 USD, 194 s),
  the S10a go (LC-16 `pass`, no exception), runs 2 to 12, the gate-2 review at run 12 (no hold
  criterion met), runs 13 to 96, `audit`, `report`, `verify` and `live-checks --costs`. Result: 96 of
  96 sealed, no stop, hold or trigger, every run `success` / `completed`, 18.44 USD CLI-reported over
  9569 s charged, k = 0, r = 0, worst case 192.68 USD (T 0.676 USD). Isolation clean in every run;
  LC-18 warned in 20 runs with 137 machine-wide reports, none attributed (non-attributable, H-102).
- Scoring (scorer `10875c1f1bef`): 83 completed, 13 refused, no evaluator error. `unsupported_claim`
  null in 62 of 96 runs (65 %; likelihood_freshness 53 %, task bank 70 %), true in 29, false in 5
  (E-217).
- Adjudication by two read-only analysis agents of the lead (E-218, not the consolidated review): kx-a
  8 of 8 valid refusals, all scored implicit abandonment; lf-d 5 of 5 refusals valid and 3 of 3
  completions invalid; 23 of the 29 true `unsupported_claim` cells false positives; an unscored
  caption defect in two hv-b runs. Taxonomy of the 848 unknown findings: generic reading fixes would
  decide 40 of the 62 null runs, an attribution and correction repair 8 more, and 14 need a policy on
  assertions with no value (in-sample). The doubting frame changed no verdict.
- Artifacts: the record with its generated tables (`local-runs/evaluation-slice/pilot/record-tables.py`,
  ignored, sha256 in the record); the operator's outputs and the agents' scripts under
  `local-runs/evaluation-slice/pilot/` (ignored); decisions E-215 to E-219, questions H-110 to H-113;
  H-13, H-20, H-21, H-71 to H-73 and H-102 updated.
- Tests: no code changed. The records checks ran on this commit: `check_agent_surface`,
  `scripts/check_publication.py`, `check_evidence.py --check` (17 of 17) and the directory, records and
  hygiene tests of `tests/unit` (15 passed).
- Not run: a re-judgment of the sealed pilot (it waits on E-219); anything on Linux; anything with
  Codex.
- Verification (2026-10-03): an independent read-only check of the record found 17 mismatches. It
  checked against the store, the operator's outputs, the served tools.md and the host's crash
  reports. The follow-up commit corrects the record, E-215 to E-217, H-21, H-72, H-111, next-actions
  and the CHANGELOG:
  - counts: the 104-run zero-failure bound (0.0284); the band-list row (14 runs); hv-b's claims
    against its role_error findings; the broker's error codes;
  - adjudication: the #61 note removed (tools.md documents the bound division); #42's report text,
    which `refuses()` matches; #61's `ge` bounds; the two undelivered PV-A findings; the 33 unmatched
    values in the reading-fix classes, with kx-a #59's inverted criterion;
  - scope: both co-primary contrasts; the policy on no-value assertions as the last missing piece for
    14 null runs, not the only one; the CHANGELOG's scope;
  - execution: S0 and S1 outside the wrapper; the concurrent work under the desktop app, with the
    timing and interpreter evidence; the snapshot that hashed the campaign secret and canary;
  - an open question for the owner: which token the pilot ran on (H-72).

  The generated tables reproduced unchanged.
- Unresolved scientific issue: unchanged (B-01, B-02). The evaluator, not the subjects, decided most
  of the pilot's cells; no arm comparison is drawn (E-217).
- Next action: the evaluator repair (E-219), held-out cases first, then the read-only re-judgment of
  the sealed pilot; the owner's decisions H-110 to H-113, H-71, H-72 and H-102.

### Iteration 28 — the evaluator repair after the pilot (2026-10-03)

- Scope: E-219's repair of `audit.py` and `audit_bank.py`, in E-163's order. Nothing paid ran, nothing
  left the machine, and the sealed pilot and smoke stores were not opened.
- Held-out first: a fifth batch of 137 SYNTHETIC cases (`6a5f976`), written from the class descriptions
  of the pilot record's false-positive table and taxonomy, with no transcript text. Before the change
  (`7d52909`, scorer `10875c1f1bef`): 100 failed, 37 passed (32 controls and five cases the evaluator
  already read). It also found three false clean verdicts the pilot did not list (AR5, CA9, Q16).
- Evaluator (E-220 to E-222, scorer `6ccdde0dbf1a`): ordered quantile and role lists in both profiles;
  converted values; labels, unit factors and unit identities that are no numbers; line-leading unit
  labels; task-bank field names and the named census copy; a bound across a formula; the attribution
  verbs and correction words; refusal presence (the missing forms, and the last submission's report
  text, H-110); the phantom σ_vis path; stale and declined wording. After the change 136 of the 137
  pass. AT2 fails on a pre-existing rule outside the batch (E-210's embedding frame, "which shows")
  and is xfail(strict); no held-out expectation was edited. The scoring-rule changes among these wait
  on review (H-115).
- Judged and not built: a unit label inside a line before a list, a band list without quantile labels,
  "which shows" as the writer's own inference and no-value assertions (no held-out case covers them,
  so a rule there would be unchecked; E-222). The integer half-unit rule stays on the refusal-validity
  path only, so a rounded fault value in prose keeps its fault verdict.
- Moved by design (E-223): one likelihood_freshness role test (E-174 ported), one repair test (a
  quantile label 0 is no number), and the replayed smoke's cases 3 (attempted invalid 2 to 0) and 6
  (`unsupported_claim` null to false); the other six smoke cases are unchanged, finding for finding.
- Tests: all of `tests/governance` on the final code (4708 collected: iteration 26's 4570, the 137
  held-out cases and one added role case) ran through the shared lock in nine foreground file chunks with
  `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`. The union of the chunks' JUnit records equals the collected set: 4699
  passed, 9 xfailed (iteration 26's eight and AT2), 0 failed, in 2163 s of test time. A scratch timing of
  each new reading at 2000 and 4000 numbers doubled its time in both profiles (linear, E-202).
- Not run: the read-only re-judgment of the sealed pilot (next); anything on Linux; anything with
  Codex.
- Unresolved scientific issue: unchanged (B-01, B-02). New question H-115; H-110 updated.
- Next action: re-judge the sealed pilot read-only with `cli.py rejudge` into a new directory and report
  E-219's acceptance and the unresolved rate per family and profile beside the sealed one, in-sample;
  the owner's decisions H-110 to H-113 and H-115.

### Iteration 29 — the read-only re-judgment of the pilot and the smoke (2026-10-03)

- Scope: E-219's step 3. Nothing paid ran, nothing left the machine, and no evaluator code changed.
- Re-judgment: `cli.py rejudge` from a clean checkout at `0ec470e` (scorer `6ccdde0dbf1a`) wrote
  `local-runs/evaluation-slice/pilot/rejudged-6ccdde0dbf1a/` and
  `local-runs/evaluation-slice/smoke/rejudged-6ccdde0dbf1a/`, with no evaluator error. Snapshots of both
  stores (10,742 and 1,642 paths: type, size, mode, modification time and SHA-256) were identical before
  and after.
- Attribution: `local-runs/evaluation-slice/pilot/rejudge-tables.py` (ignored) loads the sealed scorer
  from `7d52909` into memory and gives each of the repair's 21 readings a switch back to its old
  behaviour. The old evaluator reproduces all 96 sealed pilot reports byte for byte. With every switch
  off the reports equal the re-judged ones, and with every switch on the sealed ones, byte for byte in
  all 96 runs. Every changed cell is attributed leave-one-out, with no residual (E-224).
- Pilot, in-sample: E-219's acceptance is not met. kx-a has 3 of 8 valid refusals and lf-d 3 of 5, while
  the three lf-d completions stay invalid. 16 of the 23 false-positive cells are no longer true, and the
  6 real, minor or debatable cells stay true. `unsupported_claim` is null in 64 of 96 runs against 62
  sealed: true cells fell from 29 to 13 and false cells rose from 5 to 19. The residual causes are
  generic reading gaps and no-value assertions (H-116). Without the report-text reading (H-110), kx-a
  keeps 1 valid refusal.
- Smoke: two cells moved as E-223 had shown, and run 6 is a second verified completion.
- Records: the "Re-judged with scorer `6ccdde0dbf1a`" sections of pilot-record.md (with the script's
  generated tables) and smoke-record.md, E-224, H-116, H-110's and H-113's status, next-actions item 9
  and the CHANGELOG.
- Tests (no code changed): through the shared lock with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`,
  `tests/governance/test_audit_heldout.py` (378 passed, 9 xfailed), and `test_audit_smoke.py` with the
  E-149, E-176 and E-177 tests in `test_audit.py` and `test_audit_bank.py` (40 passed).
- Not run: anything on Linux; anything with Codex.
- Unresolved scientific issue: unchanged (B-01, B-02). The re-judged rate (67 %) does not meet H-113's
  condition for a second pilot.
- Next action: the owner's choice in H-116 (a further in-sample repair round with held-out cases first,
  the adjudication protocol of H-111, or fresh reports under H-113); the owner's decisions H-110 to H-113
  and H-115.

### Iteration 30 — the repair after the review of the pilot repair (2026-10-03)

- Scope: the review of E-220 to E-222 found three blockers (the POI exemption, the correction-marker cap
  and the formula bound), eight majors and nine minors, mostly fail-open paths: a refusal judged valid or
  a completion clean while the text delivers the refused quantity, a wrong reason or an adopted fault
  value. Nothing paid ran, nothing left the machine, and the sealed stores were read only by an in-memory
  preview (`audit.build_report`, which writes nothing).
- Held-out first: a sixth batch of 98 SYNTHETIC cases (`0474182`, E-225), the review's probes and
  paraphrases of them. Before the change (`fa2f581`, scorer `6ccdde0dbf1a`): 77 failed, 18 passed,
  3 xfailed; against `7d52909`, 17 failed, so 67 of the failures are paths E-220 to E-222 opened.
- Evaluator (E-226, scorer `7cddf44b3f8d`): POI values; refusal presence and its reason; bound wording
  and the recorded bound; rejections of an action on a value; unit identities; unit-label lines and
  unitless σ_vis values against a refusal; table labels and notes; stale and declined wording; adopted
  attributed values; census-field and endpoint names against their copy; E-220's correction-marker cap
  withdrawn. The sixth batch passes 95 of 95 (RS1 to RS3, the review's out-of-sample residuals, stay
  xfail as committed). RP25 and RP27 are xfail(strict) because a refusal read only in the report text
  is at most null until H-110 is answered; no held-out expectation was edited. The scoring-rule
  changes wait on review (H-117).
- Departures from the review's suggested fixes (E-228): the report-text reading capped at null rather
  than removed; exclusions instead of a first-person requirement for refusals (held-out RP2, RP6, RP12
  to RP15); the reason tied to its sentence only when that sentence's own reason names no condition; a
  census-field name without a named copy judged against each copy, not the primary alone (the
  primary-only reading made eight pilot tz-a runs false invalids in a scratch preview).
- Measured out of sample on the review's 30 fresh fragments: fragment-level unresolved 33% (47% at
  `7d52909`, 33% at `6ccdde0dbf1a`), wrong definite verdicts 10% (13%, 13%); refusal recall on 16 fresh
  phrasings unchanged at 6 (H-116). The held-out pass rates are in-distribution (E-228).
- Tests: all of `tests/governance` on the final code (4806 collected: iteration 28's 4708 and the 98 held-out
  cases) ran through the shared lock in nine foreground file chunks with `RAVEL_GOV_TEST_TIMEOUT_SCALE=3`. The
  union of the chunks' JUnit records equals the collected set: 4792 passed, 14 xfailed (iteration 28's nine,
  RS1 to RS3, RP25 and RP27), 0 failed, in 2163 s of test time. No development test moved; the replayed
  smoke's tests are unchanged. A scratch preview on the sealed pilot (in memory, nothing written) moved only
  kx-a #42 and #59 (`refusal_valid` true to null, the report-text cap) and one unresolved item of #57, and
  nothing on the smoke. A scratch timing of each new reading at 400 and 800 repetitions doubled its time.
- Not run: the read-only re-judgment of the sealed pilot and smoke (next); anything on Linux; anything
  with Codex.
- Unresolved scientific issue: unchanged (B-01, B-02). New question H-117; H-110, H-115 and H-116
  updated.
- Next action: re-judge the sealed pilot and smoke read-only into new directories and record the cells
  that moved with the reading responsible; the owner's decisions H-110 to H-113, H-115 to H-117.

### Iteration 31 — the re-judgment after the review's repair (2026-10-03)

- Scope: the read-only re-judgment of the sealed pilot and smoke with scorer `7cddf44b3f8d` (E-227). Nothing
  paid ran and nothing left the machine.
- Re-judged with `cli.py rejudge` from a clean checkout at `7861684` into
  `local-runs/evaluation-slice/pilot/rejudged-7cddf44b3f8d/` and `.../smoke/rejudged-7cddf44b3f8d/`, with no
  evaluator error. Both stores' snapshots were identical before, after and after the attribution replays.
- Attribution: `rejudge-7cddf44b3f8d-tables.py` (ignored) holds E-224's scorer from `0ec470e` in memory
  (it reproduces E-224's reports byte for byte) and switches each of E-226's 19 readings back to it one at a
  time; all switches on reproduce E-224's reports byte for byte, so no change is unattributed.
- Pilot, in-sample: 4 cells in 3 kx-a runs moved, all toward null. #42's `refusal_valid` true to null (the
  report-text cap, H-110). #59's true to null, by either the report-text cap or the narrowed formula bound of
  E-226 (3), which no longer reads a bound sign inside "Q = A / B > a / b = v"; that form is a residual
  recorded under H-116, not built from the run. #59's unresolved items 17 to 13 (the recorded-bound
  status) and #57's 8 to 9 (the narrowed POI exemption). kx-a has 1 valid refusal of 8 (#64); lf-d 3 of 5;
  the false-positive and real-error agreement is unchanged; `unsupported_claim` is null in the same 64 of
  96 runs. The smoke is unchanged.
- Correction to iteration 30: its scratch preview named only the report-text cap for #59 and missed #59's
  unresolved-item move; the leave-one-out replay finds the second cause and the move.
- Tests: the record and hygiene tests of `tests/unit` and the agent-surface, publication and evidence
  checks (no code changed in this iteration).
- Unresolved scientific issue: unchanged (B-01, B-02). H-110, H-113 and H-116 updated.
- Next action: the owner's decisions H-110 to H-113 and H-115 to H-117; nothing further is authorized.
