# Workflow concepts and diagrams

These retained diagrams illustrate the workflow vocabulary and scientific tool layers. Their boxes describe
concepts and possible handoffs. The current [controller](controller.md), [research](research.md),
[execution](execution.md), [provider](providers.md) and [safety](safety.md) appendices specify which paths are
connected and what evidence they require. The [scope page](../reference/scope.md) records current integration boundaries.

Amber represents the physicist, pink agents, red review and limits, blue RAVEL, green external tools or services,
and grey records. An arrow in these concept figures is a relationship, not an executed result or authority grant.

## How it works

The [methodology pages](../methodology/README.md) explain the agent, research and decision laws in detail.

### Studies and check-ins

A **study** connects one scientific question to evidence and a stated result scope. Its **run directory** holds
scientific and working files; the protected store holds controller state and authority. Scientific **operations** are typed
units of work with declared inputs, outputs, tools and checks. A science **mode** binds an operation to its adapter.
Tool executions are **stages**; the **supervisor** records their attempts, bounds and failures. A **receipt** records
what actually ran or was checked, against exact source and input identities.

**CHECK-IN 1** binds the plan, assumptions and budget. Its **approval scope** includes the permitted compute rungs:
none, dry, smoke, pilot, full or scan. **CHECK-IN 2** reviews a declared waypoint before its dependent work.
**CHECK-IN 3** reviews final artifacts and original-task coverage. Current authority can come from an authenticated
operator decision or an admitted bounded machine delegation. A deviation changes the scope through its own gate.
The lower-level ordinary specification lifecycle has no internal CHECK-IN 2; a controller route retains its outer
check-ins. See [controller transitions](controller.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/readme-overview.svg">
  <img src="../figures/svg/light/readme-overview.svg" width="100%" alt="Concept illustration of readme overview. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

The figure illustrates the plan/run/review cycle. The selected route determines which operations and waypoints apply.

### Agents and roles

The **driver agent** holds the coordinator role and proposes plans and work. The controller schedules actual seats.
The **plan critic** judges the current plan. **Workers** produce scoped artifacts in fresh sessions and workspaces.
**Reviewers** test the presented evidence and inherited obligations; the controller credits their observed responses
on an exact subject. A result review and an authority decision remain separate actions.

A **transport** connects a role to a provider. Controller seats use restricted CLI workers or RAVEL's sandboxed
HTTP/local-model loop. A **qualification** record describes observed conformance for the selected declaration,
executable or code identity. A version/help probe checks flags; actual worker qualification checks tools, instructions, output
custody and identity. Separate sessions and role-projected packets establish the recorded independence, while
model-family relations remain labels. See [agent architecture](../methodology/agent-architecture.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-agent-roles.svg">
  <img src="../figures/svg/light/methodology-agent-roles.svg" width="100%" alt="Concept illustration of methodology agent roles. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

The lanes show responsibilities available across a study. A role card's presence is distinct from a dispatched,
completed and credited seat. The current plan and engagement policy select the applicable duties.

### The research loop

The **research loop** retains hypotheses, experiments, failures, revision and synthesis. Its **hypothesis board**
records predictions, rival explanations and reopening or kill conditions. Citation-led and speculative proposals
can supply that population; the selected protocol determines their required preparation and review.

A search protocol separates baseline, screening and full evaluation from **protected confirmation**: evaluation on
a disjoint population after selection is committed. An **ablation** changes one named component while retaining
its controls. Comparisons retain declared metrics, uncertainty and cell-level outcomes. A plain reproduction
without search or selection has different stage obligations.

The campaign also records an expected-gain/cost judgment before each cycle and reserves each child at its own tier.
A stop or exhausted approved remainder ends new admission and preserves a progress or qualified synthesis.
See [the research loop](../methodology/research-loop.md) and [current research bindings](research.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-research-loop.svg">
  <img src="../figures/svg/light/methodology-research-loop.svg" width="100%" alt="Concept illustration of methodology research loop. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

The figure illustrates the staged search protocol and its preparation, evidence and review relationships.

### Recursive Decision Justification

**Recursive Decision Justification** records why a consequential action is supported. Its recursive case engine
links claims and alternatives until a branch reaches an **anchor** verified from held bytes. Edge review,
criticism, revision and verification determine that case's outcome. The **custody** record is the retained hash-linked
record of proposals, evidence and decisions outside the worker-writable run tree.

The current controller binds consequential decisions to exact-subject governed RDJ critic-seat credit and current
operator authority. Every recursive case phase requires its own execution record. Risk,
resource and authority checks still apply to the action that follows. See
[Recursive Decision Justification](../methodology/decision-justification.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-decision-justification.svg">
  <img src="../figures/svg/light/methodology-decision-justification.svg" width="100%" alt="Concept illustration of methodology decision justification. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

This figure explains the recursive case machinery. [Controller authority](controller.md) and [receipt provenance](safety.md)
define the current action and delivery checks.

<a id="what-ravel-does"></a>
<a id="supported-analyses-and-statistics"></a>

## Architecture diagrams

The following six figures are tool-layer tutorials. Their **In** and **Out** descriptions name the information at
each boundary; actual artifacts and claim scope come from the selected operation contract and observed execution.

<details>
<summary><b>Physicist steering and compute</b></summary>

The operator supplies scope, time and resource bounds. The controller checks current authority before effects,
records stop/drain and reserves new work against the approved remainder. Matched pilots calibrate new generation
forecasts. Actual resource isolation follows the runtime's recorded mechanisms; aggregate memory and disk quotas require the selected runtime's actual enforcement mechanism. See [controller](controller.md) and [safety](safety.md).

**In:** grants, check-in decisions, budgets and instructions. **Out:** admitted actions, recorded spending and typed endings.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-steering.svg">
  <img src="../figures/svg/light/arch-steering.svg" width="100%" alt="Concept illustration of arch steering. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<details>
<summary><b>The physics toolchain</b></summary>

The collider tutorial connects model, events, response and analysis. Theory operations connect supplied sources,
models, spectra, decays, diagrams and amplitudes. The retained solver/simulation lane illustrates additional native
adapter families. Each adapter keeps its own model, source and runtime domain and executes through its bound native contract. See [scientific execution](execution.md) and [upstream tools](upstream-tools.md).

**In:** admitted models, cards, event files and data. **Out:** the selected adapter's artifacts and diagnostics.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-toolchain.svg">
  <img src="../figures/svg/light/arch-toolchain.svg" width="100%" alt="Concept illustration of arch toolchain. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<details>
<summary><b>Statistics and inference</b></summary>

Statistical operations consume supplied or constructed likelihoods and declared correlation/uncertainty inputs.
Situation detection selects an applicable method and the checks it owes. Observed check outcomes determine valid,
qualified or held records. Exclusion defaults to 95% CLs; a prescribed statistic retains its definition.
See [inference engines](../reference/inference-engines.md) and [statistics execution](execution.md#statistics).

**In:** likelihoods, counts, templates and uncertainty laws. **Out:** contracted quantities, validity diagnostics and included/omitted uncertainty.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-statistics.svg">
  <img src="../figures/svg/light/arch-statistics.svg" width="100%" alt="Concept illustration of arch statistics. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<details>
<summary><b>Models and hosts</b></summary>

Provider declarations describe model, authentication and wire/launcher capabilities. Current controller seats
narrow them to wired restricted workers with admitted destination and qualification evidence. Standalone Host
interfaces retain separate contracts. See [providers](providers.md) for code identity, cost and qualification-adoption boundaries.

**In:** provider preferences, role requirements and resource shares. **Out:** observed model sessions, usage and validated outputs.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-models-hosts.svg">
  <img src="../figures/svg/light/arch-models-hosts.svg" width="100%" alt="Concept illustration of arch models hosts. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<details>
<summary><b>Provenance and receipts</b></summary>

Scientific files live in the run directory; protected decisions, execution and checkpoint state live in the store.
The sole sink fixes the delivered population, traces quantities and renders qualifications from current evidence.
A share or backup is a separately verified snapshot. See [output records](../reference/outputs.md) and [safety](safety.md).

**In:** source/input pins, observed attempts, reviews and authority. **Out:** inventoried delivery bytes, labels and a derived receipt.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-provenance.svg">
  <img src="../figures/svg/light/arch-provenance.svg" width="100%" alt="Concept illustration of arch provenance. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<details>
<summary><b>Workflow engines</b></summary>

LangGraph checkpoints the registered controller and child graphs. The supervisor observes actual local or container
processes. A direct site backend and brokered workflow profiles provide their own scheduler protocols. Journalled
handles and verified outputs determine completion; completion requires verified scheduler records and outputs. See [batch execution](execution.md#batch-and-site-work).

**In:** approved steps, pinned runtime/site configuration and resources. **Out:** observed process/job outcomes, adopted artifacts and retained failures.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/arch-engines.svg">
  <img src="../figures/svg/light/arch-engines.svg" width="100%" alt="Concept illustration of arch engines. The adjacent explanation and current appendix define which routes, evidence and authority apply.">
</picture>

</details>

<a id="appendix-b-citing-upstream-dependencies"></a>

## Glossary

<details>
<summary>Terms used in this overview</summary>

- **Ablation.** An experiment that changes exactly one component of a candidate method and holds every other input fixed.
- **Anchor.** The end of a justification branch: evidence RAVEL verifies itself, such as a tool output with a stage receipt, a measurement, an input file, your recorded words or a shipped invariant.
- **Approval scope.** What an approval permits; at CHECK-IN 1, the largest compute plan allowed: none, dry, pilot, smoke, full or scan, whose meaning depends on the route.
- **CHECK-IN 1, 2 and 3.** Plan approval, early verification (GO or ADJUST) and final review before delivery. A standalone specification plan uses its own approval and result review; a controller-owned child also follows the outer controller's applicable waypoints.
- **Custody.** Hash-chained ledgers outside the run directory; inputs, approvals, stage receipts and decision cases are appended and never rewritten.
- **Deviation.** A change to the approved plan, reported at once and recorded in the study.
- **Driver agent.** The coding-agent session you talk to; it holds the coordinator role.
- **Hypothesis board.** The shared board where research roles post sealed hypotheses, predictions and evidence requests.
- **Mode.** The science mode an operation runs under; it binds the operation to its code and its toolchain groups.
- **Operation.** A typed unit of scientific work with declared inputs, outputs, tools and review checks.
- **Protected confirmation.** Evaluation on data disjoint from every selection input, read after the selection is committed; each protected population is read once.
- **Qualification.** The recorded level a transport route has reached, from a probe of its command to a live conformance run; roles require a level.
- **Receipt.** A record, written by code, of an effect: a stage run, a worker call, a model call or a decision.
- **Recursive Decision Justification (RDJ).** The recursive case engine links claims to verified anchors. Current controller decisions use exact-subject RDJ critic-seat credit and applicable authority; that receipt records its own review scope.
- **Research loop.** The staged protocol for open-ended questions: hypotheses, baseline, screen, full run, protected confirmation, ablations and objection tests.
- **Reviewer.** A role that judges evidence and votes, such as the physics critic, skeptical verifier and physics decider.
- **Run directory.** The folder that holds one study's request, plan, inputs, outputs and working records; custody is kept outside it.
- **Stage.** One supervised tool run within a study, such as event generation or a fit.
- **Study.** One question carried from request to delivered result.
- **Supervisor.** The process that runs a stage within its wall-time limit and records any failure.
- **Transport.** The route a role's call takes: a hosted model API, a command-line agent session, a sandboxed worker, a sub-agent of the host or a relay.
- **Worker.** A role that does scientific work in a fresh session and workspace with its own budget, sandboxed on command-line routes.

The [glossary page](../reference/glossary.md) links each term to its full description.

</details>
