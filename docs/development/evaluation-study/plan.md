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
| Phase 1: WP07 | Coordinator, broker custody, receipt mapping | implemented, agent-reviewed; integration fixes merged (`7cf10d0`); repair wave: campaign freeze and per-launch verification (E-24), real-host binding and behavioral gate (E-25), outcome re-derivation and incident decisions (E-26), kind-bound specs and sealed-record verification (E-21); live smoke build: one builder for the fake and a real host, the build-time binding, the per-launch proxy, credential injection, post-run checks, kernel receipts, stop and limit (E-61 to E-70), then two review repairs (E-71 to E-100); the real-host path has run in tests against mock CLIs, with the real 2.1.281 pin at zero cost (probes, preflight and an offline 8-run rehearsal with a dummy token against a local mock API, E-71, E-88), and in the authorized 8-run paid smoke (2026-09-27, [smoke-record.md](smoke-record.md)); LC-18's collector fixed after it (E-162) | `broker.py`, `runner.py`, `campaign_manifest.py`, `live.py`, `credentials.py` |
| Phase 1: WP08/WP09 | Codex and Claude CLI adapters (mocked; one paid Claude smoke) | implemented against mocked executables, agent-reviewed; the Claude adapter has a real-host builder, factory, launch policy and proxy (smoke configuration E-40 to E-51, [smoke-request.md](smoke-request.md)), run end to end in tests against mock CLIs, with the real 2.1.281 pin in the zero-cost probes and the offline rehearsal (E-88), and in the Claude live smoke (2026-09-27: 8 of 8 runs sealed, no stop; [smoke-record.md](smoke-record.md)); Codex live validation blocked (B-04) | `adapters/claude_cli.py`, `codex_cli.py` |
| Phase 1: WP10 | Treatment delivery and audit | implemented, agent-reviewed; manifest, behavioral and delivered-prompt checks (slice §4.3); the mechanism study is library-level only (E-27) | `treatment.py`, `guard.py` |
| Phase 1: WP11 | Claim/outcome audit and v1 outcomes | implemented, agent-reviewed; repair wave R3.0–R3.8 plus two review-and-repair rounds (E-28 to E-31); repaired against the real-host smoke's findings with a held-out check and replayed regression cases (E-188), and a read-only `rejudge` (E-189); repaired again after that repair's review, its probes held out first (E-190, E-191); scoring rules provisional (PKT-D04, H-13, H-90, H-91), their review deferred (E-34) | `audit.py`, [smoke-record.md](smoke-record.md) |
| Phase 2: WP13 | Analysis and cost planning (synthetic design simulation only) | implemented, agent-reviewed | `analysis.py` |
| Phase 2: WP14 | Offline full-stack and isolation tests | built; slice §12 maps each acceptance item to its tests; G1 (synthetic engineering) met at `0b3d251`: `pytest tests` 4776 passed, 0 failed, and two CLI campaigns; after the merge at `12cc6f9`, `pytest tests` 4980 passed, 41 skipped, 0 failed (iteration 5) | `tests/governance/test_campaign_fullstack.py` (32 tests), [g1-record.md](g1-record.md) |
| Phase 1: WP35 | Isolation/state/evaluator red team | built: 23 test functions, 30 collected; 20 sandboxed attack cases (13 functions, 7 of them run in an enforcement and a baseline arm) skip without `sandbox-exec`, and 10 state and evaluator attacks run everywhere. Defect RT-01 fixed by eval/integfix `20c4506` (regression test `test_rt01_a_consistent_reseal_and_reaudit_is_reconciled_against_the_journal`); a judge report edited on its own is now refused too (E-26). Residual: a writer on the store's own account who rewrites the journal's seal digest together with the sealed tree and its manifest | `tests/governance/test_redteam.py` |
| Phase 2: WP12 | Development task bank | five provisional families, twelve tasks in six pairs: `likelihood_freshness`, kx, hv, mq and tz, all runnable since iteration 15 (E-136); the bank's oracles and their cross-checks (plan steps 2 and 3, [taskbank-oracle-appendix.md](taskbank-oracle-appendix.md)); step 1 done in iteration 12: task and claim schema version 2, the bank rules, the registry and the LF migration (E-110 to E-119); steps 4 and 5 done in iteration 13: the generalized fit, the census, calc and coordinator-only figure stages, and the broker's registry inputs, prior recipes, keyed run directories and stage budget (E-120 to E-124); steps 6 and 7 done in iteration 14: the guard's field registry, dependency classes, pb, relation and categorical claims, and the four family builders (E-125 to E-130); steps 8 and 9 done in iteration 15: the evaluator's scoring profiles (`audit_bank.py`, judge report version 2), claim version 2 at the broker, the fake subject's behaviours and the 12-task synthetic campaign through the CLI (E-131 to E-136); steps 10 and 11 done in iteration 16: the tool guide for claim version 2, the resource and permitted-actions sentences, the treatment digests and the packet-similarity check (E-137 to E-140), and the review packet (E-141; E-142 records a gap it found); iteration 17 repaired the findings of the engineering review of 2026-09-27 (E-143 to E-158, questions H-62 to H-66), and iteration 18 those of the second review of that day (E-165 to E-186, questions H-80 to H-89); merged into `evaluation-slice` in iteration 19 (E-187); its human reference review is deferred (E-34), and the packet is ready for it | `tasks/`, `contracts.py`, `guard.py`, `audit_bank.py`, `client/tools.md`, [taskbank-review-packet.md](taskbank-review-packet.md) |
| Phase 2: WP15 | 8-assignment real-host engineering smoke | done (2026-09-27, iteration 11): 8 of 8 runs sealed with no stop; engineering evidence only, with seven stated deviations (E-161) | [smoke-record.md](smoke-record.md), [smoke-request.md](smoke-request.md) |
| Phase 2: WP16 | Development pilot | not authorized; needs its own authorization (E-34, H-73). The evaluator repair the smoke opened is done (E-163, E-188); its rules await the deferred review (H-13, H-90) | — |
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
