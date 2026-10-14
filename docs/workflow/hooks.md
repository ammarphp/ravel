# Host governance: hooks, `ravel gate` and the gates in code

RAVEL's gates live in code. A host with hooks runs them before each tool call; a host without
hooks asks `ravel gate` before acting, and the delivery-side checks refuse what slipped past.

## What each host gets

| Host | Pre-execution checks | Delivery-side checks |
|---|---|---|
| Claude Code with this repository's `.claude/settings.json` | the hooks below (`pre_execution_guards: host-hooks`) | raw-launch invariant, scientific review, delivery checks |
| Any other host (Codex, Gemini CLI, opencode, a bare shell, an SDK loop) | none run automatically; the host or agent calls `ravel gate` (`pre_execution_guards: none`) | the same delivery-side checks |
| A broker worker whose session is pinned in the broker's custody ledger | `broker` only after a matching registered worker receipt | the same delivery-side checks |

**Hook governance covers Claude Code only.** The hook scripts under `.claude/hooks/` run only where
Claude Code loads this repository's `.claude/settings.json`. Codex, Gemini CLI and other hosts do
not run them, and an installed wheel used from another project does not either. On those hosts
the supervised launch path (`ravel run`, `stage_supervisor`, `launch_authorization`) still checks
approval just before it starts a process, and delivery refuses generation output that has no
approved launch record. Nothing stops a raw command on such a host before it runs: the agent must
call `ravel gate` first, and the refusal at delivery is the backstop.

## `ravel gate`

```
ravel gate --rundir <run> --action <gate|tool_call> [--command "<text>"] [--session <id>] [--floor R0|R1|R2|R3] --json
```

- `--action` is a decision-gate name (`approve_plan`, `launch`, `failed_stage_feedback`,
  `checkin2_accept`, `correction`, `deviation`, `research_choice`, `delivery`, `final_task`,
  `report_integrity`, `export`, `unblind`, `spend_above_ceiling`) or `tool_call`.
- For `tool_call`, the command text is classified: generation launches (MadGraph, Pythia,
  `run-pipeline-native.sh`, `ravel run`, `ravel partitions run`, `ravel backend launch`,
  `ravel stage` compute commands, `ravel scan launch` with or without `--go`, and
  `python -m ravel.workflow.scan_orchestrator|scan_babysitter|stage_supervisor`) map to `launch`; `ravel approve`,
  `ravel go`, `ravel result-pack` and `ravel export-submission` map to their gates; anything else
  is `none` and is allowed.
- Prefix wrappers (`env`, `nohup`, `setsid`, `time`, `nice`, `command`, `exec`, `caffeinate`,
  `stdbuf`, `conda run`) and their options are unwrapped before classification.
- Help segments, quoted reader text (`echo`, `printf`, `grep`, `rg`, `cat`) and
  `ravel stage list|show|status` map to `none`. Only `--go` raises a scan launch
  to `required_plan="scan"`.
- `--floor` raises the decision risk floor. It is omitted from the action record unless supplied.
- Exit status: 0 allow, 2 deny, 1 a usage error or no run for a gated action.
- Without `--rundir` the run comes from the run registry (below), never from the newest run.
- The verdict carries `pre_execution_guards` and the enforcement-surface digest of the host.

The `launch` gate and Claude Code Bash hook share the same verdict: no detached launch,
no launch before intake, run-kind approval that binds the current inputs, and supervised
execution. Native generation additionally requires a valid generation compute plan and a
recorded generation recipe. Classified science stage launches use the science envelope
before native generation checks; the decision gate still decides contract validity.
Every gated action delegates to `decision_gate.check`; a missing decision-gate module
refuses with `provider_inactive`, and every provider row (including inactive rows) appears
in the verdict. The launch built-ins remain in addition to that check. Runs created before
the current agent layer retain their earlier decision; absent or invalid contracts are
`gate_inputs_invalid`. The host gate never stamps `agent_layer_epoch`. Delivery providers
are owned by the decision gate's provider registry.

An explicit gated action without a resolvable run refuses with `no_active_run` (exit 1).
A classified compute launch without a run refuses with `pre_intake`, including on hookless
hosts before any router marker exists. Science runs use `inputs/science-approval.json` and
`science.verify_approval_envelope`; native runs use `workflow_state.verify_approval`.

## The run registry

`ravel initiate`, `ravel plan` and `ravel research-orchestrate prepare` register the run under the
host session id, in `$RAVEL_STATE_DIR/active-runs/` (default `~/.local/state/ravel`). The session
id comes from `--session-id`, `RAVEL_SESSION_ID`, or Claude Code's `CLAUDE_CODE_SESSION_ID`;
other hosts pass one of the first two. `ravel initiate` also records it in `run_state.json`.

Every hook, `ravel gate` and the Stop dispatcher resolve the active run in this order: the working
directory (a directory holding `run_state.json`, or `<repo>/trial-runs/<run>/`), the registry,
then a trial run whose `run_state.json` names the session. A run created outside `trial-runs/`
is therefore found from its directory and from the session.

A development session that runs `ravel initiate` becomes a physics session for that run, and its
enforcement surface turns read-only. End the registration with
`python3 -m ravel.workflow.active_run release --session <id>`.

## The hooks (Claude Code)

| Hook | Event | What it does |
|---|---|---|
| `userpromptsubmit-router.sh` | UserPromptSubmit | Runs the intake router on every prompt that is not a development request or a short reply, including calculation, research and method-study prompts. Injects the intake reminder; leaves a route-pending marker only when the routed contract admits compute (`compute_plan` other than `none`). Unsupported and research questions without compute leave no marker. A development prompt (a brief naming a worktree, branch, owned files or acceptance tests; a code task) leaves no marker. |
| `pretooluse-skill.sh` | PreToolUse · Skill, Agent, Task | Blocks contract-dependent skills, and subagent fan-out while the route is pending, until the session's run has a task contract; then consumes the marker. |
| `pretooluse-bash.sh` | PreToolUse · Bash | Shim over `host_gate.verdict(tool_call)`: blocks on deny and reports its first error message. |
| `protect-enforcement.sh` | PreToolUse · Edit, Write | The enforcement surface is read-only in a physics session (a pending route, or a run tied to the session). |
| `posttooluse-observer.sh` | PostToolUse | Records skills, edits and subagents in the session's run ledger; never blocks. |
| `deviations-guard.sh` | PostToolUse · Edit, Write | An edit to a CHECK-IN 1 input needs a `DEVIATIONS.md` entry. |
| `pre-generate-guard.sh` | PostToolUse · Bash | Recipe check for a declared model. |
| `stop-dispatcher.sh` | Stop | Shim over `stop_dispatch`; the pending action comes from the status packet (`current_state.build_packet`), for every run kind. |
| `sessionstart-orient.sh` | SessionStart | Re-orients the session on its own run; silent when the session has none. |

The installer records its import-capable interpreter in `.claude/settings.json` as
`env.RAVEL_PYTHON`. Hooks use `${RAVEL_PYTHON:-python3}` and their checkout import path.
The enforcement write guard blocks when `ravel` cannot import during a physics session
(a pending marker or a resolvable run); observers allow and log failures in
`logs/hook-failures.log`.

## Records at CHECK-IN 1 and delivery

- `ravel approve` fingerprints the enforcement surface (hook table, hook scripts and gate modules)
  into `<run>/logs/enforcement-surface.jsonl`, appending one hash-chained JSONL row per
  change (`sequence`, `prev_sha256`, `sha256`). Earlier rows are never rewritten; a broken
  chain refuses another append. Existing `enforcement-surface.json` archives are preserved.
  The digest includes transport modules/declarations, the provider registry, Claude
  hooks/settings and optional gate shims under `.claude`, `.codex` and `.gemini`. Additional owners
  register zero-argument `{label: path}` callbacks through `host_governance.SURFACE_EXTENSIONS`
  (for example the role registry's owned paths). Codex/Gemini pseudo tables are not host registrations.
- `ravel result-pack` requires the `raw_launch` provider; a missing provider fails closed.
  That provider owns output coverage and retained-approval validation. It writes
  `"enforcement": {"pre_execution_guards", "enforcement_surface_sha256", "host", "raw_launch",
  "declared_pre_execution_guards", "declared_host"}`
  into `result.json` and into every delivered claim under `outputs/claims/`. When the delivery-check
  helper is installed it also refuses a severity-A failure or a missing input for a delivered
  absolute yield, and keeps the findings in `outputs/delivery-checks.json`.

`host` and `pre_execution_guards` derive from host-emitted variables, the wired Claude
hook table and broker custody evidence. `RAVEL_HOST` and `RAVEL_PRE_EXECUTION_GUARDS` are retained
only as the separate declared fields, never credited as enforcement evidence. A machine approval is never labelled human or physicist review.

## Resuming from the status packet

`python -m ravel.validation.check_status_packet <run>` regenerates the status packet from the
run's records alone and compares its next work item with `current_state.json`, byte for byte. A
difference means the packet is stale: refresh it with `ravel status --rundir <run> --write`
before resuming.
