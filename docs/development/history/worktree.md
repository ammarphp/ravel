# Spine hardening — isolated worktree

All workflow-adherence-spine work (Phases 0–7) happens HERE, never in the main tree
(`$DSRLAB_ROOT/hep-agentic-pipeline`), whose `.claude/settings.json` the live
SVJ trial reads. This worktree has its OWN `.claude/settings.json`, so hook wiring is isolated.

- **Worktree path:** `$DSRLAB_ROOT/wt-spine-hardening`
- **Branch:** `spine-hardening` (base `harness-phase0-3-rework`; merge back when the trial completes)
- **Toolchain symlink (regenerable, machine-specific — recreate after any `git worktree` prune):**
  ```bash
  ln -s $DSRLAB_ROOT/hep-agentic-pipeline/stages/01-event-generation/build \
    stages/01-event-generation/build
  ```
- **IMPORTANT — the symlink is NOT caught by the tracked `stages/**/build/` gitignore pattern** (a
  trailing-slash pattern matches directories, not symlinks; `git check-ignore` errors "beyond a
  symbolic link"). So it is excluded LOCALLY via the worktree's `info/exclude`. After recreating the
  symlink, re-add the exclude:
  ```bash
  EXCL="$(git rev-parse --git-path info/exclude)"
  grep -qxF 'stages/01-event-generation/build' "$EXCL" || echo 'stages/01-event-generation/build' >> "$EXCL"
  ```
  Never `git add` the symlink — it points at a machine-specific absolute path.
- **Rebuild check:** `stages/01-event-generation/build/tools/miniforge3/bin/conda --version` → `conda 26.3.2`.
- **Spike verifier:** `tests/adversarial/spike_probe.py` (`--selftest`, `--spike … --record/--check`, `--primacy`) — records/re-verifies the L0 harness-behaviour spikes SPK-1/2/3 and synthesizes the per-branch `HOOK-PRIMACY.json` hook-vs-fallback table.

## Spike outcomes
- **SPK-1 — hooks fire (G0a): unproven / fallback-primary** (2026-07-09). Recorded from a REAL
  headless `claude -p` turn (cwd=worktree), NOT from hand-driven sentinels. The turn fired the
  `UserPromptSubmit` hook LIVE — a probe logged one sentinel — proving the harness loads the worktree
  `.claude/settings.json` and invokes hooks on a real turn. The nested agent then hit this host's
  OAuth login check (`"result":"Not logged in · Please run /login"`, `is_error:true` in the recorded
  `-p` transcript) and exited before any tool call or turn-end, so `PostToolUse` and `Stop` never
  fired. Exactly ONE of the five checks (`UserPromptSubmit fired`) is honestly `ok:true`; the four
  `PostToolUse` / `Stop` / exit-2-block / reason-fed-back checks are honestly `ok:false`. Per the
  Step-3/4 decision tree this is a valid RECORDED outcome, not a task failure — this OAuth-limited
  host cannot drive a nested tool call or turn-end, so the hook cannot be proven end-to-end here.
  `spike_probe.py` therefore records `verdict=unproven`, `decision=fallback-primary`, and Task 0.6's
  `HOOK-PRIMACY.json` routes every SPK-1 branch to its fallback (the safe default — an unproven hook
  is never trusted as sole authority). The `Stop` exit-2 block feeding its `SPK1-STOP-BLOCK` reason
  back remains corroborated in-repo by the `PreToolUse` card-guard precedent (exit-2 blocking already
  proven) and is exercised in the Phase-5 `spine_sim`, but that corroboration is deliberately NOT
  recorded as a live SPK-1 check. Recorded artifact: `evidence/hooks/spk-1.json` (evidence =
  the genuine probe log + `-p` transcript, so `--check` recomputes and rejects any tamper); re-verify
  with `python3 tests/adversarial/spike_probe.py --spike SPK-1 --check evidence/hooks/spk-1.json`
  (exits 1 iff the recorded verdict is not PASS — here `unproven`). To upgrade G0a to a live PASS,
  re-drive Step 3 on a host where `claude -p` is authenticated (a real tool call + turn-end will then
  fire `PostToolUse` and the one-shot `Stop`), then re-record — no schema change needed.
- **The three `spk1-*.sh` PROBE blocks are inert once SPK-1 is recorded** — the `UserPromptSubmit`/
  `PostToolUse` probes only append a sentinel and `exit 0`, and the `Stop` probe is one-shot (guarded
  by `logs/.spk1-stop-fired`), so it passes after its first fire. Per RECONCILE D-1 every later phase
  MERGES its hook blocks into `.claude/settings.json` idempotently and NEVER wholesale-writes it, so
  these blocks coexist with the real spine blocks (Phase 2's real `Stop` dispatcher merges as a
  SEPARATE `Stop` block). If `logs/` is ever cleared the one-shot `Stop` probe re-arms and blocks
  turn-end once; drop the `spk1-` blocks then with the SAME D-1 idempotent-merge idiom in reverse
  (remove any hook block whose `command` contains `spk1-`, keep `PreToolUse` byte-for-byte) — never
  by wholesale-writing the file.
- **SPK-2 — completion re-invocation (G0b): PASS / harness-reinvoke-primary** (2026-07-09). Proven by a
  token round-trip through the harness `run_in_background` completion channel: a per-run unguessable
  token minted by `spike_probe.py --new-token` (`SPK-e3acc687cd66`) was echoed by a
  `run_in_background`-tracked job (`sleep 5; echo "SPK2_DONE <TOK>"`); the turn ended WITHOUT polling;
  the harness re-invoked this agent when the job exited, and that completion re-invocation carried the
  job's stdout (a `<task-notification status=completed>` event + the `SPK2_DONE <TOK>` line it delivered),
  so the same unforgeable token appears in BOTH `launch_cmd` and `reinvoke_text`. Because the token is
  minted fresh and is unguessable, a matching token in the re-invocation cannot have been fabricated
  ahead of time — the re-invocation genuinely carried the job output. `spike_probe.py` records
  `verdict=PASS`, `decision=harness-reinvoke-primary`, so Task 0.6's `HOOK-PRIMACY.json` routes the
  `drive_completion_reinvoke` branch to its harness-reinvoke primary (the poll-the-logfile path stays the
  recorded fallback). **N6 constraint (load-bearing):** the background mechanism MUST be the harness
  `run_in_background`, NEVER `nohup`/`start_new_session` — N6 proved a detached process silently defeats
  the completion notification, so DRIVE mandates `run_in_background` for every long job. Recorded
  artifacts: `evidence/hooks/spk-2.evidence.json` (the verbatim launch + completion re-invoke) +
  `SPK-2.json` (evidence carries `generated_by`+`input_fingerprint`, so `--check` recomputes and rejects
  any tamper); re-verify with
  `python3 tests/adversarial/spike_probe.py --spike SPK-2 --check evidence/hooks/spk-2.json`
  (exit 0 iff PASS).
- **SPK-3 — scheduled wake (G0c): PASS / wake-primitive-primary** (2026-07-09). Proven by a de-facto
  timed wake on the SPK-2-confirmed harness `run_in_background` completion re-invoke — **the confirmed
  scheduled-wake mechanism in this harness (decision: bg-sleep-reinvoke)**; a dedicated `ScheduleWakeup`
  primitive (probed via `mcp__scheduled-tasks__*`) is a secondary/UNCONFIRMED path deliberately NOT
  relied on (do not block on it). A wake scheduled 120 s out (launch `07:10:38Z` + 120 s = scheduled
  `07:12:38Z`) fired on schedule: the harness re-invoked this agent on the bg job's completion carrying
  its stdout (`SPK3_WAKE … bg_done=2026-07-09T07:12:38Z`), so `fired_utc = scheduled_utc` to 1 s
  resolution — **observed wake latency ≈ 0 s** (`|fired−scheduled| = 0 s`), well inside the 30 s
  tolerance that absorbs re-invoke jitter. (A redundant polling waiter separately observed the fire at
  `07:13:17Z`; that is poll-cadence-inflated, recorded in the evidence `note` for transparency and
  explicitly NOT used as the fire time.) The verifier was first proven armed (red): the SAME evidence
  with a 30-min-late `fired_utc` records `verdict=unproven` / `decision=bg-sleep-reinvoke-fallback` /
  exit 1, so a PASS cannot be fabricated. `spike_probe.py` records `verdict=PASS`,
  `decision=wake-primitive-primary` — note the verifier ties the decision enum to the within-tolerance
  PASS, not to the mechanism string, so here the proven "wake primitive" IS the bg-sleep re-invoke — so
  Task 0.6's `HOOK-PRIMACY.json` routes the `scheduled_wake` and `progress_reporter_30min` branches to
  their wake-primitive primary (the bg-sleep-reinvoke path is the recorded fallback for those same
  branches). Recorded artifacts: `evidence/hooks/spk-3.evidence.json` (the scheduled/fired
  timestamps + mechanism + provenance note) + `SPK-3.json` (evidence carries `generated_by`+
  `input_fingerprint`, so `--check` recomputes and rejects a tamper); re-verify with
  `python3 tests/adversarial/spike_probe.py --spike SPK-3 --check evidence/hooks/spk-3.json`
  (exit 0 iff PASS).

## Hook primacy (L0 decision)
`evidence/hooks/hook-primacy.json` is the **authoritative** per-branch `{governed_by, primary,
fallback}` table Phases 2/3/4 read to decide, for each enforcement branch, whether the hook or its
agent-invoked twin is the enforcement of record. It is a pure `spike_probe.py --primacy` synthesis of
the recorded SPK-1/2/3 verdicts (`generated_by`+`input_fingerprint` over the embedded spike decisions,
so `--check-primacy` recomputes and rejects a tamper AND asserts each branch's `primary` is consistent
with its governing spike's verdict). Re-verify:
`python3 tests/adversarial/spike_probe.py --check-primacy evidence/hooks/hook-primacy.json` (exit 0).

**Binding rule (the whole spec §4 "hooks + fallback" principle keys on this):** a `fallback`-primary
branch MUST ship its **agent-invoked twin as the enforcement of record**, with the hook wired as
best-effort belt-and-suspenders; a hook-primary branch trusts the hook as the enforcement of record
(the twin is redundancy). No SPK-1-governed branch is trusted as a hook-only sole authority while
SPK-1 is `unproven` — that is the safe default (`check_primacy` and `test_primacy_flips_on_spk1_fail`
both lock it in).

**The 14 branches, as recorded (2026-07-09):**
- **11 SPK-1-governed branches → `primary=fallback`** — G0a is the honest `unproven` record on this
  OAuth-limited host, so the twin is the enforcement of record for all of them. Their design-basis
  fixes the *promotion order* the moment a live authenticated SPK-1 turn upgrades G0a to PASS (no
  schema change — just re-run `--primacy`):
  - `userpromptsubmit_route` and `pretooluse_skill_precedence` are the **hook-primary-by-design** pair
    with independent proven-fire evidence — `UserPromptSubmit` LIVE-fired in SPK-1 (`checks[0].ok=true`)
    and the `PreToolUse` card-guard is a proven in-repo exit-2 precedent — so they are the FIRST to flip
    to machine `primary=hook` on a live SPK-1 PASS.
  - the six `stop_*` branches (`stop_primary_d18`, `stop_drive_d4`, `stop_catch_d6`, `stop_skill_coverage`,
    `stop_integrity_d5d9`, `stop_detach_n6`) and the three `posttooluse_*` branches (`posttooluse_observer`,
    `posttooluse_edit_deviations`, `posttooluse_pregenerate_guard`) depend on turn-end/loop blocking and a
    fired `PostToolUse`, which this host cannot live-automate (`claude -p` = "Not logged in"). They are
    hook-primary-by-design with the **fallback co-authoritative**: the agent-invoked twin ships as the
    authoritative enforcement of record until a live authenticated worktree session confirms the hook.
- **`drive_completion_reinvoke` → `primary=harness-reinvoke` (SPK-2 PASS — CONFIRMED)** — the harness
  `run_in_background` completion re-invoke; poll-the-logfile stays the recorded fallback.
- **`progress_reporter_30min`, `scheduled_wake` → `primary=wake-primitive` (SPK-3 PASS — CONFIRMED)** —
  the proven wake primitive IS the SPK-2 harness completion re-invoke (`bg-sleep-reinvoke`), i.e. the
  same confirmed harness-reinvoke channel; the bg-sleep-reinvoke path is the recorded fallback.

So NONE of the three harness-reinvoke-family branches (`drive_completion_reinvoke`,
`progress_reporter_30min`, `scheduled_wake`) is fallback-primary — all are proven — while every
SPK-1-governed branch degrades to its twin, exactly as the plan is designed to. Authoritative artifact:
`evidence/hooks/hook-primacy.json`.
