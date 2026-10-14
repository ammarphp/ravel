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
