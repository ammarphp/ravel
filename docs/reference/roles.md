# Role cards, host bindings and adoption

`src/ravel/data/roles/registry.json` defines the effective cards. Reserved
`cards/<id>.json` overrides replace defaults. `load()` resolves aliases;
`resolve_names()` refuses unknown names. `request_requires()` supplies the card's
tool requirement to the worker request as `role_requires`; the dispatcher also
binds `card_sha256` and the registry digest.

Card schema v2 refuses `requires.parallel_safe`. Shipped cards explicitly set
`stop.evidence_budget`; omitted budgets default to zero. Every output schema
requires `handoff`, either null or `{role, reason}`. Schema compliance establishes
neither live host qualification nor scientific validity.

| Card class | Tools | Isolation | Evidence budget | Transport expectation |
|---|---|---|---|---|
| Voting, no evidence requests | `none` | `cli-policy` | 0 | `claude-cli-oneshot`, verified transport receipt |
| Voting, positive evidence budget | `broker-readonly` | `ravel-sandbox` | positive | `claude-cli-worker` once this host holds its live qualification record; refusal before |
| Producer, consultant, investigation and other tool roles | As declared | `ravel-sandbox` | As declared | `claude-cli-worker` once this host holds its live qualification record; refusal before |

A positive evidence budget with no tools is refused. Shipped cards keep
`attestation_min: transport`. Native host subagents never establish that
attestation. Qualification is per host. The shipped `claude-cli-worker`
declaration does not claim `live_qualified`; `ravel transport qualify` writes a
qualification record into the host state directory after a live conformance run,
and the registry raises the route's status only while that record matches the
declaration digest, the stored probe and the probed executable. Without that
record every role is refused with its exact reasons. A voting refusal on a
qualified host is a coordinator stop.

The per-role selection table below is a selection control, not a qualification.
`tests/integration/test_roles_merged.py` stores synthetic probes and a
matching qualification record for `claude-cli-worker` under a temporary state
directory, reads them back through the registry's stored-record path, and writes
the table with `truth_table_markdown(truth_table_rows(...))`. Every voting role
must select `claude-cli-worker`. Do not alter shipped declarations or their
qualification status to make this test pass.

<!-- B1 T-M1 truth table: start -->
| Role | Voting | Selected route | Missing |
|---|---|---|---|
| `ablation-critic` | no | `claude-cli-worker` | `[]` |
| `analysis-author` | no | `claude-cli-worker` | `[]` |
| `assumption-auditor` | no | `claude-cli-worker` | `[]` |
| `baseline-producer` | no | `claude-cli-worker` | `[]` |
| `calculation` | no | `claude-cli-worker` | `[]` |
| `comparative-reviewer` | no | `claude-cli-worker` | `[]` |
| `consult-columnar` | no | `claude-cli-worker` | `[]` |
| `consult-cosmology` | no | `claude-cli-worker` | `[]` |
| `consult-feynrules` | no | `claude-cli-worker` | `[]` |
| `consult-inference` | no | `claude-cli-worker` | `[]` |
| `consult-latex` | no | `claude-cli-worker` | `[]` |
| `consult-madgraph` | no | `claude-cli-worker` | `[]` |
| `consult-normalization` | no | `claude-cli-worker` | `[]` |
| `consult-onnx` | no | `claude-cli-worker` | `[]` |
| `consult-pythia-delphes` | no | `claude-cli-worker` | `[]` |
| `consult-recast` | no | `claude-cli-worker` | `[]` |
| `consult-rivet` | no | `claude-cli-worker` | `[]` |
| `consult-symbolic` | no | `claude-cli-worker` | `[]` |
| `consult-theory` | no | `claude-cli-worker` | `[]` |
| `coordinator` | no | `claude-cli-worker` | `[]` |
| `detector-calibrator` | no | `claude-cli-worker` | `[]` |
| `discrepancy-attributor` | no | `claude-cli-worker` | `[]` |
| `figure-critic` | no | `claude-cli-worker` | `[]` |
| `generator` | no | `claude-cli-worker` | `[]` |
| `idea-proposer-a` | no | `claude-cli-worker` | `[]` |
| `idea-proposer-b` | no | `claude-cli-worker` | `[]` |
| `inference` | no | `claude-cli-worker` | `[]` |
| `integrity-auditor` | no | `claude-cli-worker` | `[]` |
| `investigation-worker` | no | `claude-cli-worker` | `[]` |
| `limitation-census` | no | `claude-cli-worker` | `[]` |
| `literature-scout` | no | `claude-cli-worker` | `[]` |
| `ma-coupling-order-consultant` | no | `claude-cli-worker` | `[]` |
| `ma-eft-consultant` | no | `claude-cli-worker` | `[]` |
| `ma-scales-pdf-consultant` | no | `claude-cli-worker` | `[]` |
| `ma-ufo-consultant` | no | `claude-cli-worker` | `[]` |
| `manuscript-writer` | no | `claude-cli-worker` | `[]` |
| `ml-planner` | no | `claude-cli-worker` | `[]` |
| `ml-reviewer` | no | `claude-cli-worker` | `[]` |
| `ml-trainer` | no | `claude-cli-worker` | `[]` |
| `model-builder` | no | `claude-cli-worker` | `[]` |
| `model-critic` | no | `claude-cli-worker` | `[]` |
| `normalization-auditor` | no | `claude-cli-worker` | `[]` |
| `novelty-scout` | no | `claude-cli-worker` | `[]` |
| `object-selection-mapper` | no | `claude-cli-worker` | `[]` |
| `physics-critic` | yes | `claude-cli-worker` | `[]` |
| `physics-decider` | yes | `claude-cli-worker` | `[]` |
| `physics-improver` | no | `claude-cli-worker` | `[]` |
| `plan-critic` | no | `claude-cli-worker` | `[]` |
| `rca-investigator` | no | `claude-cli-worker` | `[]` |
| `rdj-critic` | no | `claude-cli-worker` | `[]` |
| `rdj-edge-reviewer` | no | `claude-cli-worker` | `[]` |
| `rdj-verifier` | no | `claude-cli-worker` | `[]` |
| `re-deriver` | no | `claude-cli-worker` | `[]` |
| `rebuttal-planner` | no | `claude-cli-worker` | `[]` |
| `research-evolver` | no | `claude-cli-worker` | `[]` |
| `research-explorer` | no | `claude-cli-worker` | `[]` |
| `research-meta-reviewer` | no | `claude-cli-worker` | `[]` |
| `routine-constructor` | no | `claude-cli-worker` | `[]` |
| `screen-producer` | no | `claude-cli-worker` | `[]` |
| `second-method-deriver` | no | `claude-cli-worker` | `[]` |
| `sf-convention-translator` | no | `claude-cli-worker` | `[]` |
| `sf-datacard-schema-reviewer` | no | `claude-cli-worker` | `[]` |
| `sf-id-encoder` | no | `claude-cli-worker` | `[]` |
| `sf-kappa-extractor` | no | `claude-cli-worker` | `[]` |
| `sf-measurement-extractor` | no | `claude-cli-worker` | `[]` |
| `sf-methodology-consultant` | no | `claude-cli-worker` | `[]` |
| `sf-modifier-namer` | no | `claude-cli-worker` | `[]` |
| `sf-order-corrector` | no | `claude-cli-worker` | `[]` |
| `sf-parametric-uncertainty-estimator` | no | `claude-cli-worker` | `[]` |
| `sf-pdf-uncertainty-estimator` | no | `claude-cli-worker` | `[]` |
| `sf-reviewer` | no | `claude-cli-worker` | `[]` |
| `sf-scale-uncertainty-estimator` | no | `claude-cli-worker` | `[]` |
| `sf-scan-designer` | no | `claude-cli-worker` | `[]` |
| `sf-scan-sanitizer` | no | `claude-cli-worker` | `[]` |
| `sf-systematics-decomposer` | no | `claude-cli-worker` | `[]` |
| `shower-detector` | no | `claude-cli-worker` | `[]` |
| `skeptical-verifier` | yes | `claude-cli-worker` | `[]` |
| `sufficiency-verifier` | no | `claude-cli-worker` | `[]` |
| `trap-auditor` | no | `claude-cli-worker` | `[]` |
| `upstream-agentrivet-analyst` | no | `claude-cli-worker` | `[]` |
| `upstream-agentrivet-code-reviewer` | no | `claude-cli-worker` | `[]` |
| `upstream-agentrivet-coder` | no | `claude-cli-worker` | `[]` |
| `upstream-agentrivet-physics-reviewer` | no | `claude-cli-worker` | `[]` |
<!-- B1 T-M1 truth table: end -->

`src/ravel/data/agent_surface/host_capabilities.json` records native fields,
exact value mappings, sources and confirmation status. A spawnable profile needs
every requirement and model constraint to have a confirmed mapping, plus
`attestation_min: self`. Any unverified field forces a dispatch redirect.

| Host | Documented fields | Unresolved policy mappings | Current output |
|---|---|---|---|
| Claude | `tools`, `model`, `effort`, `isolation` | Zero tools (an empty `tools` list is listed as all tools), tiers, broker/sandbox isolation, blinding, structured output | Redirect body; tool authority not restricted |
| Codex | `sandbox_mode`, `model`, `model_reasoning_effort` | Zero tools, tiers, exact Ravel isolation | Read-only redirect |
| Gemini | `tools`, `model` | Profile `mode`/`permission`, effort, tiers, sandbox isolation | Empty-tool redirect |
| opencode | `mode`, `permission`, `model` | Effort, tiers, structured output, sandbox isolation | Deny-all subagent redirect |
| Antigravity | No confirmed mapping | All native policies | Redirect |
| Governed node | Full effective card | Dispatcher/broker enforcement required | Full card JSON |

Field sources, checked 2026-10-11: [Claude subagents](https://code.claude.com/docs/en/sub-agents),
[official OpenAI subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Gemini subagent schema](https://geminicli.com/docs/core/subagents/), and
[opencode agents](https://opencode.ai/docs/agents/). Documentation checks are not
live host probes. A documented field name alone does not establish a mapping
from Ravel policy to vendor policy.

Redirect bodies contain only “Do not perform this role here. Run
`ravel work dispatch --role <id>`.” They carry no card or protocol. Claude always
has a `tools:` line, but Claude Code lists a profile with `tools: []` as having
all tools, so a Claude redirect restricts instructions, not tool authority. Governed nodes retain the complete card. Dispatch execution
belongs to the executor; adoption does not implement it.

Regenerate with `ravel agent-surface render --project .`. The coherence gate
refuses missing files, byte drift and unproduced files in every owned profile
directory and among manual shim siblings: `generated surface orphan: <path>`.
Unprefixed registered legacy twins are removed.

A single cross-host hook table is deferred. No `.codex/hooks.json`,
`.gemini/settings.json`, `.claude/settings.ravel-gates.json` or
`.ravel/gate-surface.json` is rendered. Codex, Gemini and opencode are hookless.
`ravel-gate.sh` files are manual adapters with explicit CLI arguments; they do
not register native events. Existing Claude hooks remain host-governance-owned.

`owned_paths(project)` registers through `host_governance.SURFACE_EXTENSIONS`.
It covers the registry, reserved overrides, generated profiles and manual shims.
Package initialization registers it before governance-first consumers run.
Its `metadata(project)` callback returns `role_registry_sha256` for CHECK-IN 1.
Host governance must invoke it with the actual project and incorporate that
metadata. A zero-argument invocation fails closed. The CHECK-IN 1 surface digest
and physics-session write protection cover these files once host governance
provides that project/metadata interface.

Before approval, the executor seals `inputs/work-orders/<node>.json` with `role`,
`review_points`, declared outputs and obligations. Run:

```sh
ravel work pin-obligations --rundir RUN
```

This writes `inputs/work-obligations.json` once, deriving obligations from
`role_registry.self_checks(role)` and the order's review points. Its SHA-256 is
pinned in `inputs/checkin1.json`, and the sidecar enters the approval fingerprint.
Post-approval pinning is refused. Node IDs admit dots and refuse `..`.

Derived obligations point under `/obligations/<escaped-id>` in a required JSON
sidecar. `obligation_output` can explicitly select that output; otherwise an
output of kind `obligations` is preferred, then the first required JSON output.
Scientific code or document outputs may appear before that sidecar. Preserve
each complete derived obligation in the order; extra obligations are allowed
and checked. Required output and pointer content must be nonempty; zero and
false remain valid observations.

```sh
ravel work adopt --rundir RUN --node-id N3.author --attempt 1
```

Adoption reads `agent-work/N3.author/1/outputs/`, verifies approved sidecar bytes,
current card/review-point derivation, the order digest and obligation superset,
then copies the exact checked bytes. JSON digests use sorted keys, compact
separators and `ensure_ascii=False`. Legacy `work/<node>/attempt-<n>` workspaces
are refused. Adoption never registers worker receipts, writes custody or grants
execution credit, launch authority or scientific acceptance. Only the dispatcher
registers receipts.

`finding_effect(item, resolve=...)` ignores declared `evidence_class` and resolves
evidence IDs. A resolved `code_check` or `new_receipt` can block severity A;
cited/opinion evidence is advisory. Without a resolver, every ID is opinion.
Pending/unresolved typed requests hold the finding; a self-declared failed
result does not block. The review loop supplies the resolver from its recorded
decision evidence.

Aliases cover the five author/verifier names and every current tool name.
`consult-cosmology`, `consult-onnx` and `consult-latex` are minimal purpose-only
cards pending review through reserved overrides. They assert no tool
qualification or new scientific protocol.

The twelve failure-consult bindings are declared in
`src/ravel/data/knowledge/consult_bindings.json`. The pyhf binding uses the
registered inference alias. Site diagnostics currently use the registered
read-only columnar card; a dedicated site card remains a role-owner handoff.
Bindings name manifest groups and full handbooks; they establish neither tool
qualification nor scientific acceptance. The failure graph refuses dispatch when
its targeted knowledge provider or a required handbook is absent. See the
specialist failure-advice APIs in `docs/workflow/steps/03-generate.md`.
