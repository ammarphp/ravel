# Host enforcement in this release

Hook capability, generated registration and observed enforcement are separate facts.
The capability census below was read on 2026-10-15. No model session or native
scientific program was launched to qualify these adapters.

| Host | Evidence and native configuration | Projected checks | Remaining limits |
|---|---|---|---|
| Claude Code | Existing `.claude/settings.json` lifecycle hooks retained | Bash admission, pristine cards, enforcement surface, deviations, prompt routing and existing observer/session/stop adapters | Native write tools are checked; arbitrary shell writes remain outside the write guard |
| Codex CLI | Installed `0.162.0-alpha.17.2`; `--help` documents hook trust; `features list` reports `hooks stable true`; `.codex/hooks.json` | `PreToolUse`, `PostToolUse`, `UserPromptSubmit` delegate to shared Python guards | Project and current hook definitions must be trusted; actual host invocation unverified |
| Gemini CLI | No executable found on PATH or checked standard install paths; official interface documented; `.gemini/settings.json` | `BeforeTool`, `AfterTool`, `BeforeAgent` delegate to the same guards | Installed version and runtime compatibility unverified |
| opencode | No executable found on PATH or checked standard install paths; official plugin interface documented; `.opencode/plugins/ravel-guards.js` | `tool.execute.before` and `tool.execute.after` call shared guards; exceptions refuse calls | Installed version, runtime compatibility and prompt interception unverified |
| Antigravity | Native hook format unverified | Explicit gate adapter and native PATH shims | Lifecycle and write checks require explicit calls |

Codex was inspected at
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` with `--version`,
`--help`, `debug --help` and `features list`. Gemini and opencode were checked via
`command -v` and standard system/user executable locations; absence from these
locations is not a claim that no copy exists anywhere on disk. Neither was installed
or invoked over the network.

Official sources: [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Gemini hooks reference](https://geminicli.com/docs/hooks/reference/),
[opencode plugins](https://opencode.ai/docs/plugins/).
Codex command hooks accept event JSON on stdin and exit 2 with a reason on stderr
to deny a supported pre-tool call. Its hook table is `{"hooks":{"PreToolUse":[{"hooks":[{"type":"command","command":"..."}]}]}}`;
shell calls match `Bash`, native patches match `apply_patch` (also `Edit`/`Write`).
Gemini uses the same group structure with `BeforeTool`/`AfterTool` and `BeforeAgent`;
its timeout unit is milliseconds. opencode loads a JavaScript plugin exporting an
async function returning event callbacks; the before callback reads `input.tool`
and `output.args` and throws to refuse. The generated plugin uses only built-in
runtime modules. Generated command hooks omit timeouts to use the host default.
Prompt hooks are advisory, as in Claude's router: a routing failure warns on stderr
and exits 0, because exit 2 would block the prompt (Codex) or drop it (Gemini).
Tool hooks fail closed: an unavailable guard exits 2. Adapters find the nearest ancestor containing `.claude/settings.json`, then fall
back to the Git root or the starting directory. Claude starts from
`CLAUDE_PROJECT_DIR` when set; other command hooks start from the working directory,
and the plugin starts from its host directory. This locates the local runtime even
when the RAVEL project is nested inside another repository.
The adapters inspect every tool event, translating documented shell/write arguments;
they do not infer unknown tool semantics. MCP naming outside `mcp__server__tool`
needs explicit admission through the site-tool gate below.

The role renderer owns these projections and every host's `ravel-gate.sh`:

```sh
python -m ravel.workflow.role_registry --write --project .
ravel agent-surface install --project /path/to/project
ravel agent-surface check --project /path/to/project
```

The installer preserves foreign or modified configuration files and reports conflicts.
A reported conflict means that registration needs manual integration before relying
on it. `agent-surface check` reports the capability/enforcement level for all five
hosts; this is a declaration of wiring and limits, not attestation that a host loaded
or trusted it. Runtime `pre_execution_guards` remains `host-hooks` only with the
existing host-emitted evidence and wired Claude hook, or `broker` with pinned broker
custody; other contexts remain `none`. Configuration presence or an environment
claim does not upgrade custody. No Codex/Gemini/opencode runtime attestation is inferred.

## Native execution on every host

Installation writes local `.ravel/bin/` shims for the executable names declared in
`src/ravel/data/agent_surface/hooks.json`: generator, shower, detector simulation
and workflow-manager entry points. It also writes local interpreter settings and
an activation script. Activate in the shell environment used by the host:

```sh
. /path/to/project/.ravel/activate.sh
```

Each shim calls `execution_guard.decide`, resolves the active run and reuses its
byte-bound CHECK-IN 1 approval verifier and live steering gate before `exec` of
the next executable on PATH. Missing run, invalid/stale approval, unavailable guard
or paused steering refuses before execution. Arguments and the executable exit
status are preserved. The shim grants no approval or supervised launch receipt;
use the normal supervised workflow for admitted work. Shims and activation files
are local installer state, covered by the installation manifest and ignored by Git.
Reinstall after moving a project or changing interpreter.

PATH shims cover only the registered executable names while that directory heads
PATH. **An absolute executable path bypasses a PATH shim.** Changing PATH, copying
or renaming an executable, invoking it through an interpreter, and direct libraries
also fall outside this boundary. Recognized shell commands can additionally be
held by a loaded host hook, but lexical inspection is not a universal shell sandbox.
Protected-file writes through arbitrary shell programs require an explicit gate;
PATH shims do not intercept file writes. Rules in `.claude/rules` are host guidance;
other hosts read the shared workflow guidance, with no native rules enforcement claim.
RAVEL's supervised launch authorization, `decision_gate.check` and `execution_guard`
retain their in-code checks regardless of host. Cached checks do not qualify physics.

## Explicit write gates

Every generated `ravel-gate.sh` forwards unchanged arguments and exit status:

```sh
ravel gate --project . --action protected_write --path /path/to/destination --json
ravel gate --project . --action deviation_check --path /path/to/input --json
```

The first refuses configured pristine-card writes and enforcement-surface changes
in a physics session. Card protection is enabled only by the card hook registration
in the same project's `.claude/settings.json`; public settings omit that registration.
When enabled, `RAVEL_PROTECTED_CARD_ROOT` overrides the default root derived from
Git's common directory, matching the source hook across linked worktrees. The second also checks required deviation records and current approved
input bytes. The shared Python owner resolves relative paths, patch destinations,
moves and symlink aliases for native write tools. A changed approved input still
requires amendment and reapproval; a deviation note does not renew approval.
Claude's existing post-edit guard retains its timing and failure behavior. Native
adapters protect records before writes and check deviations after completion;
post-tool checks can report a violation but cannot undo a completed write.

See [host governance](../workflow/hooks.md) for explicit decision gates, interpreter
installation and append-only records, and the [gate-wiring record](gate-wiring.md)
for the code paths that enforce decisions. Operator records attest the supplied
text under the executing OS user, not a human identity.

## Site tool servers

Facility plugins can expose MCP tools named `mcp__<server>__<tool>` for dataset
lookups, transfers, batch jobs, notebook execution and filesystem access. Claude
Code's shipped settings now match `mcp__.*` in both PreToolUse and PostToolUse.
`pretooluse-mcp.sh` delegates to `ravel.workflow.site_tools`; the observer records
completed calls. Installation into another project merges equivalent MCP groups
without replacing that project's other hooks.

`src/ravel/data/site_tools/policy.json` is a schema-validated policy. Each rule
matches separate server and tool glob patterns and declares read-only or effectful
behavior. Matching effectful rules take precedence. Unknown servers, tools and
malformed MCP names default to the `unknown` effect. Only explicitly declared
lookup, metadata, status, listing and reading operations pass without approval.
Downloads, transfers, job submissions/cancellations, notebook execution and file
writes require a current run approval covering the exact call. Policy or interpreter
failure refuses admission, including read-only calls whose policy cannot be checked.
Review the actual server inventory and semantics before adding read-only rules;
a generic execution or multi-action tool must remain effectful.

The policy contains a generic `ravel-site-example` server and illustrative
`*af-uchicago*` patterns for capabilities described in the
[UChicago facility's public AI documentation](https://usatlas.github.io/af-docs/ai/).
The facility/plugin context was supplied for this implementation; these patterns
are examples, not a verified live tool inventory. Names that do not match remain
effectful. Plugin installation and credential setup are [human site steps](site-workflows.md#facility-agent-plugins).

Before approval, write `inputs/site-tools.json` with this scope:

```json
{
  "schema_version": 1,
  "calls": [
    {
      "tool_name": "mcp__ravel-site-example__download_dataset",
      "tool_input_sha256": "<SHA256 of the complete planned tool_input object>",
      "effects": ["download"]
    }
  ]
}
```

Replace the explanatory digest token with 64 lowercase hex characters. Obtain it
with `ravel.workflow.site_tools.input_digest(tool_input)`, which hashes canonical
JSON with sorted keys. Scope names are exact, with no globs, and the complete
argument object is bound: datasets, destinations, submitted code, cancellation
job identifiers and resource limits cannot change silently. The scope schema is
`src/ravel/data/site_tools/scope.schema.json`. Display the planned arguments,
effects and resource cost in CHECK-IN 1; a hash alone is not a reviewable plan.
An unknown operation requires an explicit `unknown` effect for its exact call.
Run `python -m ravel.workflow.site_tools refresh-checkin --rundir <run>` to
materialize the registered `sections.site_tools` section before presenting CHECK-IN 1.
The scope file also enters both approval input inventories. Existing native
CHECK-IN records with a valid inline scope remain supported; science proposals
use the registered producer so regenerating their CHECK-IN preserves the scope.

Admission calls the same run-kind approval verifier as the Bash heavy-compute
guard and the live steering check used by launch authorization. Native/scoped runs use
`workflow_state.verify_approval`; science runs use
`science.verify_approval_envelope`. Both bind the whole CHECK-IN 1 artifact, so
changing the scope requires amendment and reapproval. A compute approval without
this section grants no site-tool effects. Checks cover approval and call scope;
they do not prove that a remote server respects limits or supervise a remote job.
Use the governed acquisition or execution route for outputs and subsequent stages.

Generated declarations live under `.ravel/site-tools/<host>.json`. The role
renderer generates them for Claude, Codex, Gemini, opencode, Antigravity and
RAVEL's governed node host. Their common matcher is `mcp__.*`. Hosts without runtime hook custody still report `pre_execution_guards: none`.
Only Claude's existing adapter has the full native MCP observer wiring; use explicit
pre-call admission and post-call observation for other tool naming conventions.
Pass host tool-call JSON (`tool_name`, `tool_input`, optional `session_id`, `cwd`,
and after execution `tool_response`) on stdin:

```sh
python -m ravel.workflow.site_tools check --project <project> --rundir <run>
# Only after an allow verdict, invoke the exact MCP call through the host.
python -m ravel.workflow.site_tools observe --project <project> --rundir <run>
```

`check` exits 0 for allow and 2 for refusal/error. The refusal points to
`docs/workflow/start.md` and the scope-bearing CHECK-IN 1. Generate shipped Claude
MCP hook groups with `python -m ravel.workflow.site_tools render --project .`;
regenerate declarations with `python -m ravel.workflow.role_registry --write --project .`.

The observer appends every completed MCP call to `<run>/logs/site-tools.jsonl`,
or `<project>/logs/site-tools.jsonl` if no run resolves. It stores tool name,
classification/effects, input and response hashes, policy hash, approval hash
when currently valid, and observation-time decision. It stores no raw arguments,
results, credentials or tokens. These are host-reported observations, distinct
from supervised launch receipts and from remote success. Observers remain
best-effort: failures are reported in `logs/hook-failures.log`. The policy, schemas,
admission module and generated declarations enter the enforcement fingerprint
and are read-only during a registered physics session.
