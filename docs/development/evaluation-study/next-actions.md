# Evaluation study: next actions

The offline slice, its adversarial review, the repair wave and the G1 acceptance run are done
(plan.md iterations 2 to 4), and the merged tree has been prepared for publication (iteration 5).
Under E-34 the human reviews are deferred to one consolidated review and no longer block
development, and the 8-assignment engineering smoke was authorized. It ran on 2026-09-27 (item 3,
plan.md iteration 11, [smoke-record.md](smoke-record.md)); the evaluator repair it opened (item 4)
comes before any pilot. The WP12 development task bank (item 8, plan.md iterations 12 to 18) was
built on its own branch and merged in iteration 19. What remains:

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
3. **Done: the authorized real-host smoke** (E-34; engineering E-40 to E-101, plan.md iterations 8
   to 10; execution iteration 11). Campaign `smoke-claude-2.1.281-a` ran all 8 assignments from
   `8dbc4a2` on 2026-09-27 with no stop, hold or trigger, 2.59 USD CLI-reported
   ([smoke-record.md](smoke-record.md); its deviations are E-161). Still open from the reviews:
   censusing a lost run launch before preflight (E-96), and H-30 and H-31. No paid call without a
   further authorization (E-34, H-73).
4. **Done: the evaluator repair before any pilot** (E-163, E-188, E-189; plan.md iteration 20). A
   held-out check was written first, and the 8 smoke runs are replayed regression cases. `cli.py
   rejudge` re-scored the sealed smoke read-only (smoke-record.md, "Re-judged with scorer
   `e64ae0848fcb`"): one verified completion; two valid refusals, which stay unadjudicated because their
   no-value claims keep `unsupported_claim` null (H-13). Left open: numbered-list markers, a unit
   label before a number or a list, unlabelled list members and arrows (E-163 f). There is also a
   pre-existing fail-open in E-28's marked-after route ("I cannot say the previous <n> was not used"
   reads historical) and a pre-existing quadratic `_bindings` scan (plan.md iteration 20). The rules
   await the consolidated review (H-13, H-90, H-91).
   **Done: the repair after that repair's review** (E-190, E-191; plan.md iteration 21), with the
   review's probes held out first. The re-judged smoke is unchanged.
   **Precondition for scoring the next campaign:** a decimal that no rule reads but that states a
   current or prior quantity is now judged in the likelihood_freshness profile (E-190), but the
   task-bank profile (`audit_bank.Scale`) has no `stray_match`, so a stale value in a label-value
   line, a numbered line or a semicolon clause is still silently dropped there, which can give a
   false clean verdict. Add that pass (with held-out cases first) before any task-bank campaign is
   scored. Still open, failing toward null (slice §11): a unit label before a number or a list,
   bracketed pairs and ranges under one role label, "not carried forward".
5. **Done: LC-18 no longer counts the collector's own `log` invocation** (E-162), with recorded
   unified-log fixtures. Its count stays machine-wide and the collector stays blind to the subject
   (HP-11); both are recorded residuals.
6. **LC-16 without a reported geography.** Every smoke run reported `inference_geo: not_available`,
   which HP-13 did not measure, so LC-16 warned in all 8 runs although the recompute with no multiplier
   matched exactly (E-160). Before the pilot, have HP-13 measure the absent-geography case (or record
   that the pin applies no multiplier to it), so a pilot's go needs no accepted exception.
7. **The pilot request.** Prepare the request the owner decides (H-73): scope, caps, model and effort,
   a fresh token minted outside any agent session and revoked at close-out, and the operator rules
   (H-71), with the evaluator repair (item 4) done first.

8. **The WP12 development task bank.** Plan steps 1 to 11 are done: the oracles and their
   cross-checks ([taskbank-oracle-appendix.md](taskbank-oracle-appendix.md)); step 1 (plan.md
   iteration 12): task and claim schema version 2, the bank rules, the registry and the LF migration,
   on the provisional decisions E-110 to E-119; steps 4 and 5 (iteration 13): the generalized `fit`,
   the `census`, `calc` and coordinator-only `figure` stages, and the broker's registry inputs, prior
   recipes, keyed run directories and `max_stage_executions` (E-120 to E-124); steps 6 and 7
   (iteration 14): the guard for claim version 2 (E-125) and the kx, hv, mq and tz builders with the
   errata of E-119 (E-126 to E-130); steps 8 and 9 (iteration 15): the evaluator's scoring profiles
   (`audit_bank.py`, judge report version 2, `scope_change` for E-116), claim version 2 at the broker,
   the fake subject's behaviours and the 12-task synthetic campaign through the CLI, every family
   runnable (E-131 to E-136).
   - Step 10 (iteration 16): the tool guide now documents claim version 2 with its field table, the
     estimand, the fit's POI range, and the census and calc fields (E-137). The prompt's resource
     sentence states the stage limit, and the guard's permitted-actions sentence is neutral (E-138).
     The digests are recorded (E-139). The packet-similarity check found no shared run longer than 4
     words (E-140).
   - Step 11: the review packet [taskbank-review-packet.md](taskbank-review-packet.md) (E-141), with
     H-40 to H-61. While it was assembled, the lead found that the likelihood_freshness profile does
     not apply the design's convention values (E-142, H-61).
   - Repairs after the engineering review of 2026-09-27 (iteration 17, E-143 to E-158): grouped
     thousands read as one number, claim version 2 in the likelihood_freshness profile, attributed
     restatement rebuilt, census claims judged per copy, the kx nearer-answer rule and recall list,
     pre-WP12 campaigns still verified and audited (the paid smoke store checked read-only), the
     truncated fixture moved out of `tests/`, and a reference-in-every-arm cohort. New questions
     H-62 to H-66.
   - Repairs after the second review of 2026-09-27 (iteration 18, E-165 to E-186): tz's required
     endpoints are the request's three facts; the guard and the evaluator read evidence alike (bounds
     citing a conversion, one cited holder of the field's kind, figures holding what they plot); a
     declined input beside a complete delivery is a named extra; prose roles are named, ordered or
     unresolved; index numbers are no counts; the kx refusal matcher and the boilerplate rule narrowed;
     secondary calc results, weaker bounds and CLs relations scored as the review asked; the registry
     bound into the treatment and scorer identities; new digests (E-185); a reference_variant cohort in
     every arm (E-186). New questions H-80 to H-89. Not built: claim version 2 probes in the product
     behavioural check (H-89).

   Next: the consolidated review of the packet. Until the reviewer records D-V (H-40, H-50), the bank
   scores only synthetic engineering campaigns (E-110). A pilot on the bank needs its own
   authorization (E-34) and its budget. **Done: merged into `evaluation-slice`** (plan.md
   iteration 19, E-187): no decision or question id collided, so none was renumbered; the task
   bank's iterations 11 to 17 are 12 to 18, after the smoke's iteration 11. The smoke's evaluator
   repair (item 4, E-163) now starts from the merged `audit.py`, which carries the bank's changes.

## Follow-ups from the repair wave (open, tracked here)

The review names and numbers below (runner review, minor n) and where the reports are kept are
explained in [decisions.md](decisions.md).

- **Per-stage kernel fingerprint (runner review, minor 5): done** (M5, E-66). The RAVEL
  `execution_state` receipts are sealed with every run, the runner compares them with the arm's
  kernel source digest, interpreter and stage workers, and `audit.py` restates the rule
  independently.
- **Runner review minors** (`runner.py`; no repair round took them, and the live smoke build closed
  1, 2 and 5 and part of 6; minor 5 is the kernel fingerprint above):
  1. Done (M1, E-61): the behavioral gate reads only the latest record and re-derives it from its
     custody (H-11 stays open for the other questions).
  2. Done (M2): the adapter result is written before the post-run drift check, and an exception in
     that check is recorded as drift.
  3. A judge report that differs from its re-derivation, or a judged digest that differs from its
     seal, has no recovery path and blocks outcomes for the whole campaign (H-10).
  4. Incident rows are not fully bound to the recorded decision: the not-started or crash row is
     chosen from the unsealed journal, the row falls back to the current tree digest when the
     journaled one is unusable, and decision-admitted rows are not counted per arm (H-10).
  6. Partly done (M6, E-61): for a real host the recording launcher compares the exact launch call
     with the build-time binding. Still open: `launch.json` seals environment names only, not the
     adapter's added path values, and the arm-term scan runs over whole absolute paths (the smoke's
     roots are chosen to pass it).
- **Campaign manifest residual:** journal the manifest's kind and authorization digest in each run's
  records and in `run.json`, a partial step against a writer on the store's own account who
  re-freezes a relabeled campaign.
- **Lost-launch System V objects:** journal the pre-launch listing ids in the `process_started` record
  (a §13 change), or refuse sandboxed launches on resume until a human clears them (E-20 residual).
- **Reader-side IPC gap:** a later run that could have probed an object an earlier run left is not
  flagged (H-08).
- **Clock-free leader identity:** an optional `leader_id` in the launch record, so `census_launch`
  can prove a Linux leader across a wall-clock step (E-23).
- **Live-host capability (with H-04):** for the Claude smoke, HP-04 exercises the shell under the
  real-host profile and HP-10 records a multiprocessing script, whose failure is accepted for the
  smoke (E-45). Codex's pty-backed exec is still unexercised (slice §8).
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
  development task bank ([taskbank-review-packet.md](taskbank-review-packet.md), H-40 to H-61).
- Ammar: sign off E-19 as amended, E-20 and E-21 (H-09); decide the scope of invalidating flags
  (H-08).
- Ammar and the lab: H-03, custody incidents (H-10), the treatment gate (H-11), real-host identity and
  spend (H-12), the scoring conventions (H-13), the treatment texts to preregister (H-14) and the
  interfaces taken from the packet (H-15).
- Ammar and the lab: the real-host smoke's review questions H-22 to H-24 and H-26 to H-31; their
  recorded defaults and the lead's decisions (E-73, E-84, E-85) held for the smoke. The guard's
  handling of non-value claims that cite stale evidence (H-70).
- Ammar and the lab: the evaluator repair after the smoke (H-90, E-188) and after its review (H-91, E-190),
  with H-13.

## Still needing a human decision or resource

- Ammar: the smoke ran (H-20 answered; the token minted, then deleted after the smoke). Still
  needed: confirm the smoke token's revocation and the clean-up of its minting (H-72, E-192); the
  operator rules for later paid campaigns (H-71); authorization of the development pilot and of any
  other paid use (E-34, H-73); the approval-per-rebuild question (H-25); the Codex pin
  (B-04, H-04).
- Lab: holdout custodian and external store (B-06, PKT-D08).
- Ammar: external baselines (B-08, PKT-D11). The lab: the method-development track's choices (B-09).
- Ammar, for the public export: whether any text that E-37 removed from these working records (the
  publication's title and claim framing, the related-work comparison, the method-development track and
  its local pilot, the E-34 quotation) is published after all, and whether the track's code, tests and
  pages, which the export excludes (E-192), ship; the text can be restored from `917c049`
  (the E-47 quotation, kept out at the live path's merge, from `c281393`; E-102).
  Whether the decision-record and claim interfaces taken from the packet stay (H-15, E-38). Whether
  `CITATION.cff` (already public) keeps his personal email address or uses the GitHub noreply address
  the publish commits use.
