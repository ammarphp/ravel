# Host enforcement in this release

Codex, Gemini and opencode are hookless hosts: `pre_execution_guards: none`.
Their optional `ravel-gate.sh` shims forward an explicit gate request; they do not register
host events. Call `ravel gate` before consequential actions. Supervised launch authorization
and the required delivery providers enforce their respective contracts in code.

Claude Code reports `host-hooks` only with a host-emitted session variable and the project's
wired PreToolUse Bash hook. Broker custody can establish `broker` for a pinned worker
session. Environment declarations alone establish neither value. A path that calls
`decision_gate.check` gives every host the same decision, including required-provider refusal
and the earlier-run and invalid-contract rules; the [gate-wiring record](gate-wiring.md) lists
the paths that call it. The operator commands record their text as the operator's, whoever runs
them under that OS user: nothing in the record attests a human identity.

See [host governance](../workflow/hooks.md) for the gate CLI, interpreter installation,
append-only enforcement records and extension surface. This describes
implemented software guards; it does not claim live host qualification or scientific validity.

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
RAVEL's governed node host. Their common matcher is `mcp__.*`. Hookless hosts
still report `pre_execution_guards: none`: their declarations require explicit
pre-call admission and post-call observation, not fictitious automatic hooks.
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
