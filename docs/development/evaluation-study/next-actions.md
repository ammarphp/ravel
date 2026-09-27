# Evaluation study: next actions

The offline slice, its adversarial review, the repair wave and the G1 acceptance run are done
(plan.md iterations 2 to 4), and the merged tree has been prepared for publication (iteration 5).
Under E-34 the human reviews are deferred to one consolidated review and no longer block
development, and the 8-assignment engineering smoke is authorized. The smoke's engineering (item 3)
is therefore the next local work. What remains:

## Local, permitted now (integration lead)

1. **Done: the final acceptance run and the G1 record** ([g1-record.md](g1-record.md), `0b3d251`:
   `pytest tests` 4776 passed, 0 failed; two synthetic CLI campaigns). The earlier ignored
   `local-runs/evaluation-slice/g1-evidence/` (`0fb3922`) is superseded and is not G1 evidence.
2. **A Linux run.** Record a run of `tests/governance` on Linux before calling the Linux start-time
   handling (`START_READ_ERROR_S`, E-23) fixed there; none exists yet. The first will be the public
   CI's test job (ubuntu-24.04); publishing to a branch first (`export-distribution.sh --push-branch`)
   and opening a pull request runs it before the public `main` moves. What has run instead (plan.md
   iteration 5, E-33): recorded Linux `/proc` and util-linux samples read through the Linux readers on
   macOS, and the exported tree on a case-sensitive volume with Seatbelt reported unavailable and start
   times truncated the way `/proc` gives them. Still unexercised: the real `/proc`, `killpg` on a group
   of zombies, orphan reaping on the runner, GNU `env -0`, the runner's locale, a wall-clock step
   during a run, and `STOCK_PYHF_RTOL` (1e-6 in `tests/governance/test_oracle_counting.py`, measured
   only on macOS arm64). Publish procedure (docs/development/distribution.md, "Publishing"): a fresh
   export with `--push-branch`, a pull request against `main`, the `test suite` job's log read; then
   `main` is fast-forwarded to the reviewed commit from the retained publish checkout, not merged in
   GitHub's web interface (that would make the web-flow identity the last committer, and the next
   `--push` would stop at the identity check). A Linux failure is fixed at its source and recorded
   here, in E-33 and in the CHANGELOG's Linux sentence; a timing flake is rerun and recorded (item 3
   below), never loosened or skipped.
3. **Next: real-host engineering for the authorized smoke** (E-34; [smoke-request.md](smoke-request.md),
   "Not implemented" 1–6): a real-host campaign builder that also freezes the smoke's approval record
   (per-run cap, model and the Claude choices of H-04) and names it by its authorization's
   `reference_sha256`; a `claude_cli` adapter factory and launcher; a real-host launch policy;
   starting the allowlist proxy; a path for the host's credential; and arm-free path names. Runner
   review minors 1 and 6 below touch the same path and belong with it. Then record the smoke's
   prerequisites (smoke-request.md) and run it; its live checks (item 7 there, B-05) are part of the
   run. No paid call before these exist, and none outside the smoke's eight assignments without a
   further authorization (E-34). Needs from Ammar: a credential for the isolated config.

## Follow-ups from the repair wave (open, tracked here)

The review names and numbers below (runner review, minor n) and where the reports are kept are
explained in [decisions.md](decisions.md).

- **Per-stage kernel fingerprint (runner review, minor 5, second half):** the before-launch and
  after-run code checks miss a stage-worker or kernel file changed and reverted during a run. Seal a
  per-run kernel and stage fingerprint (for example from the RAVEL `execution_state` receipts) and have
  `audit.py` compare it with the arm manifest's `common.kernel_source_sha256` and
  `stage_workers_sha256`. The first half (the evaluator re-checks the sealed prompt's instruction
  segment) is done.
- **Runner review minors left open** (`runner.py`; no repair round took them; minor 5 is the kernel
  fingerprint above):
  1. The behavioral gate accepts any passing record of the campaign.json, including one older than a
     failing check, and a hand-written `result.json`. Require the latest check to pass and re-derive
     its verdict from the recorded custody (H-11).
  2. An exception in the post-run drift check escapes `process()`; on resume the run becomes a lost
     launch, its real result is discarded and it is charged at the cap. Make the post-run check total
     and record a failure as drift.
  3. A judge report that differs from its re-derivation, or a judged digest that differs from its
     seal, has no recovery path and blocks outcomes for the whole campaign (H-10).
  4. Incident rows are not fully bound to the recorded decision: the not-started or crash row is
     chosen from the unsealed journal, the row falls back to the current tree digest when the
     journaled one is unusable, and decision-admitted rows are not counted per arm (H-10).
  6. The host binding compares the argv `build_argv` produces, not the argv the adapter passes to the
     launcher; `launch.json` seals environment names only, not the adapter's added path values; and
     the arm-term scan runs over whole absolute paths (smoke-request item 6).
- **Campaign manifest residual:** journal the manifest's kind and authorization digest in each run's
  records and in `run.json`, a partial step against a writer on the store's own account who
  re-freezes a relabeled campaign.
- **Lost-launch System V objects:** journal the pre-launch listing ids in the `process_started` record
  (a §13 change), or refuse sandboxed launches on resume until a human clears them (E-20 residual).
- **Reader-side IPC gap:** a later run that could have probed an object an earlier run left is not
  flagged (H-08).
- **Clock-free leader identity:** an optional `leader_id` in the launch record, so `census_launch`
  can prove a Linux leader across a wall-clock step (E-23).
- **Live-host capability (with H-04):** the live smoke must exercise each host's shell tool (Codex's
  exec is pty-backed) and a multiprocessing script under the production profile (slice §8).
- **Scoring:** estimate the unresolved rate on realistic reports before the pilot (H-13); the
  negation-window gap and the unread unattached unitless integers (slice §11 known gaps).
- **Analysis limitations (optional code change):** `analysis.py`'s limitations say the enforcement
  contrasts do not separate blocking from feedback, but not that the design cannot estimate RAVEL
  versus no RAVEL (slice §1). Add that note if the report should carry it.
- **Outside the documentation pass's files:** `tests/governance/test_redteam.py`'s RT-01 residual
  should add that a judge report edited on its own is now refused (E-26).
- **Exporter interpreter (done, iteration 6):** `scripts/maintenance/export-distribution.sh` runs its
  checks with the `python3` first on `PATH`; under 3.13 `check_publication.py`'s fidelity audit fails on
  its version-specific AST pin, which is recorded evidence and was not changed. The exporter now stops at
  once, with that reason, unless `python3` is 3.12 (the CI version). Publish with `.venv-dev/bin` first
  on `PATH`.
- **Export review, left open (iterations 6 and 7):**
  1. The test session's signal guard (`tests/governance/conftest.py`) allows a signal whenever the
     target's start time reads as None: a gone process or a zombie, but also a live process it cannot
     read (on Linux a zombie thread-group leader with live threads), and `killpg` checks only the
     process whose pid is the group id. Production never signals on a None read. Telling "gone or
     zombie" from "live but unreadable", and checking every group member before a `killpg`, needs a
     process listing inside tight kill loops and a zombie test per platform; not done.
  2. Done (iteration 7): `tests/fixtures/hook-probes/spk-2.evidence.json` held a Claude Code task
     notification whose output path carried the local user name in dash-encoded form
     (`-Users-<name>-...`), public since 2026-09-05. The project directory in that path is now
     `[redacted-project-dir]` and `spk-2.json` was re-recorded from it with `spike_probe.py --record`
     (new `input_fingerprint`; verdict and decision unchanged; `case_g0b` passes). The exporter's leak
     check (`export_safety.py leak-check`) now refuses the home directory, its dash-encoded form and the
     bare account name in every staged file, text or binary, and in staged paths. It does not redact the
     new forms: rewriting text a fingerprint covers would make the record fail its check, so a hit is
     fixed at its source. The public repository's earlier commits still hold the old text.
  3. Linux-only flake windows, tracked rather than loosened: a clock step by chrony or timesyncd during
     the 20 start-time reads of `test_isolation.py`'s start-time test. If it shows up in CI, rerun and
     record it. (The synthetic leader starts in two census tests now sit a fixed .37 s off a whole
     second from the holder's start, which removes the other window.)
  4. Linux census completeness (`isolation.census_launch`, unsandboxed branch): `_linux_proc_read`
     returns None for state Z, and on Linux Z also covers a thread-group leader whose main thread exited
     while its other threads run. Such a member of a proven group, not yet signalled, is listed
     `foreign`, so the census can end complete while a live subject thread group was never signalled.
     Signalling stays fail-closed (nothing unproven is signalled; the live launcher's `killpg` path does
     kill it), and on Linux only synthetic `none_test_only` campaigns can run. Fix: a member of a proven
     group still listed without a readable start at the last listing leaves the census incomplete and is
     listed as a survivor, or `/proc/<pid>/task` tells a zombie from a zombie leader with live threads;
     with a recorded-sample test. Not changed here: it needs a design choice and cannot be exercised on
     a real `/proc` on this host.
- **Publication check (done, E-32):** the seven names that failed the filename rule of
  `scripts/check_publication.py` were renamed to lowercase kebab-case: the four working records in
  this directory, and `tools.md`, `request.md` and `scientific-instructions.md` under
  `benchmarks/governance/`. The checker was not changed.

## Deferred to the consolidated review (E-34; see [blockers.md](blockers.md))

These no longer block development. Their questions stay open, and nothing produced under their
provisional defaults is reported as a scored or empirical finding before the review.

- Ammar and the lab: G0 review of the Phase 0 audit and slice design (PKT-D01, D02, D04, D05; B-01).
- Reviewers: the WP05 statistics review of the oracle (B-02) and the WP12 reference review of the
  development task bank.
- Ammar: sign off E-19 as amended, E-20 and E-21 (H-09); decide the scope of invalidating flags
  (H-08).
- Ammar and the lab: H-03, custody incidents (H-10), the treatment gate (H-11), real-host identity and
  spend (H-12), the scoring conventions (H-13), the treatment texts to preregister (H-14) and the
  interfaces taken from the packet (H-15).

## Still needing a human decision or resource

- Ammar: a provider credential for the smoke's isolated config (B-03); authorization of the
  development pilot and of any other paid use (E-34); the Codex pin (B-04, H-04).
- Lab: holdout custodian and external store (B-06, PKT-D08).
- Ammar: external baselines (B-08, PKT-D11). The lab: the method-development track's choices (B-09).
- Ammar, for the public export: whether any text that E-37 removed from these working records (the
  publication's title and claim framing, the related-work comparison, the method-development track and
  its local pilot, the E-34 quotation) is published after all; it can be restored from `917c049`.
  Whether the decision-record and claim interfaces taken from the packet stay (H-15, E-38). Whether
  `CITATION.cff` (already public) keeps his personal email address or uses the GitHub noreply address
  the publish commits use.
