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
| `consult-higgs` | no | `claude-cli-worker` | `[]` |
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
| `consult-workflow-manager` | no | `claude-cli-worker` | `[]` |
| `coordinator` | no | `claude-cli-worker` | `[]` |
| `detector-calibrator` | no | `claude-cli-worker` | `[]` |
| `discrepancy-attributor` | no | `claude-cli-worker` | `[]` |
| `extended-scalar-modeler` | no | `claude-cli-worker` | `[]` |
| `figure-critic` | no | `claude-cli-worker` | `[]` |
| `generator` | no | `claude-cli-worker` | `[]` |
| `higgs-combination-reviewer` | no | `claude-cli-worker` | `[]` |
| `higgs-coupling-analyst` | no | `claude-cli-worker` | `[]` |
| `higgs-theory-uncertainty-auditor` | no | `claude-cli-worker` | `[]` |
| `idea-proposer-a` | no | `claude-cli-worker` | `[]` |
| `idea-proposer-b` | no | `claude-cli-worker` | `[]` |
| `inference` | no | `claude-cli-worker` | `[]` |
| `integrity-auditor` | no | `claude-cli-worker` | `[]` |
| `investigation-worker` | no | `claude-cli-worker` | `[]` |
| `limitation-census` | no | `claude-cli-worker` | `[]` |
| `literature-discovery-selector` | no | `claude-cli-worker` | `[]` |
| `literature-evidence-scorer` | no | `claude-cli-worker` | `[]` |
| `literature-query-expander` | no | `claude-cli-worker` | `[]` |
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

Every redirect calls the common role dispatcher with an exact run, node, role,
worker spec and subject. Resolve these from the active request; missing bindings
hold the role. The module command works in an installed package:

```bash
python -m ravel.workflow.transports.host_subagent dispatch --rundir RUN --node NODE --role ROLE --spec SPEC.json --subject SUBJECT.json
```

`ravel work dispatch` accepts the same arguments. SUBJECT.json contains the
scope and sha256 returned by `host_subagent.subject_for(spec)`: the pinned review
subject, sealed work order, or spec identity. Host integrations call
`agent_host.dispatch_role` with the same bindings and a `NativeDelegateAdapter`
for Claude Code/Codex or a `DelegateAdapter` for an MCP tool advertising the
`ravel/role-dispatch` metadata and exact schemas in
`src/ravel/data/agents/role-dispatch.json`. Tool names do not select adapters.
Callbacks must launch a fresh child and collect its bound response. The complete
role card, budgets, subject and gated broker reach that child.

Required host roles need evidence establishing their declared guarantees. Explicit
advisory mode requires the parent session identity, labels the result
`ADVISORY - REQUIRED ROLE NOT SATISFIED`, and creates no worker acceptance
receipt. A claimed child identity establishes no isolation or review credit.
Blind or voting cards refuse host advisory dispatch before packet exposure.
Uncertain host calls remain reserved and require reconciliation; they are never
automatically repeated. A governed worker never launches on an attempt whose
broker a host window served (`host_attempt`); dispatch a new attempt. Never
perform a refused role as a parent persona.

Claude always has a `tools:` line, but Claude Code lists a profile with
`tools: []` as having all tools, so its redirect restricts instructions, not tool
authority. Governed nodes retain the complete card. Qualified CLI workers retain
their existing supervisor, tool gate, isolation checks and receipt semantics.

Regenerate with `ravel agent-surface render --project .`. The coherence gate
refuses missing files, byte drift and unproduced files in every owned profile
directory and among manual shim siblings: `generated surface orphan: <path>`.
Unprefixed registered legacy twins are removed.

## Scalar roles and supplied-declaration checks

The scalar role cards and bindings compose append-only fragments in
`src/ravel/data/higgs/registration/`. `consult-higgs` advises on the declared
framework; `higgs-coupling-analyst` and `extended-scalar-modeler` construct supplied
inputs. `higgs-combination-reviewer` and `higgs-theory-uncertainty-auditor` review
in fresh sessions distinct from those producers and must not read producer headlines.
Role-card check aliases must resolve even when an atlas row lists the name.

Declare semantic facts in plan fields `/review/domain_tags` and
`/review/experiments`. Tags `higgs` and `combination` staff the combination reviewer;
`extended-scalar` staffs the modeler and consult. A `combination` with at least two
distinct supplied experiment identities staffs the shared theory auditor. Study
names, titles, parameter grids and output formats do not select these roles.

Use `check run` with a card-named `check:higgs.*` ID and one source-bound workspace
JSON document. `src/ravel/validation/higgs_checks.py` checks framework declarations
and signal-theory correlations and delegates measurement, parameterization, basis,
theory-constraint and cross-engine checks to their operation owners. Missing owner
implementations or inputs return `inconclusive`, which must not close an obligation.
TH1–TH12 inspect supplied overlap, mass, loop, width, boundary, sign, basis, channel,
statistic, release and tension declarations. The legacy T1–T12 sweep remains intact.
Each validator row in the registration fragment states its input document. A missing
field or an undeclared label is `inconclusive`. A role can run the check of every
trap its card must read. Any two measurements sharing an event set need a supplied
joint likelihood; a signal-theory correlation below one needs located evidence. A
confidence-region dimension counts the jointly estimated parameters of interest, and
a goodness-of-fit dimension is the observable count minus the fitted parameters.

The `higgs` convention shard uses located authored evidence with the existing
physics-knowledge kernel. Primary scientific sources and framework/tool handbooks
remain required at use; these declarations establish neither a valid fit nor a
qualified prediction. Native and remote work uses the existing method admission
and supervised launch guard. See [inference conventions](inference-engines.md)
for the requested statistic and likelihood scope.


## Quantity ownership and the supplied coupling group

Each role card has a closed `ownership` contract: `owns` identifies produced
quantity kinds, `judges` identifies review scope, and `inputs` identifies consumed
quantity kinds. Only producers own quantities; a role must not judge its own kind.
The role registry's controlled `quantity_kinds` records the existing source roles
behind each kind. The vocabulary describes the cards' existing work and grants
no new scientific capability.

In a Higgs combination inside the fit workflow, the coupling analyst owns the
measurement and parameterisation bundle it hands to the fit specialists. The
fit roles own coupling-modifier extraction and scale, PDF and parametric theory
uncertainty estimation. The theory auditor and combination reviewer judge and
own no quantities. See [the fit assembly contract](../workflow/steps/sfitter.md#quantity-ownership-at-assembly)
for the exact kind names, graph bindings, required quantities and handoff rules.
Registry validation checks the fit phase table, and graph validation refuses
parallel ownership unless an explicit output-to-input chain is declared.
These declarations do not enable any protected setup group.
