# Agent architecture

A RAVEL study is carried out by a team of agents with fixed roles. A driver agent plans the work and dispatches
it; producers build and run; reviewers who did not do the work judge it; and the physicist approves the plan, the
early evidence and the final result. Every role is defined by a *role card* in a shipped registry, and every
dispatch, review and approval leaves a receipt.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../figures/svg/dark/methodology-agent-roles.svg">
  <img src="../figures/svg/light/methodology-agent-roles.svg" width="100%" alt="Agent roles across a study. Swimlanes for the physicist, the driver, producers and tool consultants, the research team, specialist reviewers, the voting panel and decision-justification reviewers run across the study phases: request, plan, CHECK-IN 1, build and run, CHECK-IN 2, research loop, delivery and CHECK-IN 3. Each lane shows the roles that act in that phase. Failures route to investigators and back to the producers.">
</picture>

## Terms

- **Role card.** The definition of a role: its purpose, what it sees, the tools and actions it uses, the
  model tier it needs, its budgets, its output schema and who reviews its work.
- **Model tier.** The class of model a card requires: `judgment` for physics-judgment work, `agent` for
  tool work that is safe to delegate, `cheap` for the lowest-cost models. A route serves a card when one of its
  declared models lists that tier.
- **Model family.** The vendor family of a model, read from the model identifier the route reports. A card
  can require a family different from another role's.
- **Driver.** The agent session the physicist talks to. It holds the `coordinator` role.
- **Worker.** A fresh agent session that performs one role on one task, in its own workspace.
- **Quorum.** The join rule of a map node that completes when at least *n* of its items succeed, written
  `quorum:n`; the alternative join `all` needs every item.
- **Receipt.** A record written by the dispatcher, not by the worker, of what a worker received, did and returned.
- **Check-in.** A point at which the study stops for the physicist. A plan the driver writes has three; a
  plan built from a specification (`ravel plan`) has no CHECK-IN 2, and its result review shapes the next
  proposal. A deviation notice is sent whenever a mid-run judgment changes course.
- **Gate.** A check in code that refuses an action without the approvals and decisions it requires.

## The study and its check-ins

| Phase | What happens | Who decides |
|---|---|---|
| Request | RAVEL reads the request into facts, constraints, deliverables and open questions | — |
| Plan | The driver chooses the cheapest sufficient method, sources, budget and a verification waypoint | Plan critic advises |
| **CHECK-IN 1** | The physicist approves, redirects or narrows the plan; no event generation before this, not even a smoke run | Physicist |
| Build and run | Producers build models, cards, routines and fits, and run the approved work | Gates check every launch |
| **CHECK-IN 2** | Early verification at the waypoint: the produced element beside the published one | Voting panel, then the physicist's GO |
| Research loop | Staged experiments for research questions ([research loop](research-loop.md)) | Research reviewers, decision justification |
| Delivery | Figures, report and record audit | Figure critic, integrity auditor |
| **CHECK-IN 3** | Final review of every result against the original question | Voting panel, then the physicist |

The table describes a plan the driver writes. A plan built from a specification runs its approved
calculation with `ravel run` after CHECK-IN 1; `ravel go` refuses it, and its result check-in offers GO or
ADJUST for the next proposal, not another attempt. CHECK-IN 3 presents the reviewed results; the actions
the physicist can delegate are listed under [steering](#how-the-physicist-steers).

The CHECK-IN 1 approval binds the exact plan: the request, the method decision, the cost forecast and a
fingerprint of every input. Changing any of them requires a new approval and invalidates a later GO. Each
consequential action between check-ins needs a [decision justification](decision-justification.md) receipt.

## The driver

The driver holds the `coordinator` card. It sees the whole run. It plans, routes the request, dispatches
workers, presents the check-ins and runs dry and smoke rungs itself. Full and scan launches go to workers: a
launch at those rungs is refused without the worker's receipt or a recorded host waiver. Before each dispatch the
driver reads the physicist's steering state and acknowledges new instructions. The driver never approves: a graph
checkpoint is never a check-in approval, and an agent's statement of independence counts for nothing.

## Roles

The registry ships 89 role cards in ten families. A *voting* role casts a verdict that a gate counts; a
*specialist* reviewer files located findings; a *producer* writes artifacts; an *advisory* role answers questions.

| Family | Roles | Kind |
|---|---|---|
| Coordination (1) | `coordinator` | Driver |
| Production (11) | `analysis-author`, `calculation`, `detector-calibrator`, `extended-scalar-modeler`, `generator`, `higgs-coupling-analyst`, `inference`, `ml-trainer`, `model-builder`, `physics-improver`, `shower-detector` | Producer |
| Consult (15) | `consult-columnar`, `consult-cosmology`, `consult-feynrules`, `consult-higgs`, `consult-inference`, `consult-latex`, `consult-madgraph`, `consult-normalization`, `consult-onnx`, `consult-pythia-delphes`, `consult-recast`, `consult-rivet`, `consult-symbolic`, `consult-theory`, `consult-workflow-manager` | Advisory |
| Research (14) | `limitation-census`, `idea-proposer-a`, `idea-proposer-b`, `literature-scout`, `research-explorer`, `baseline-producer`, `screen-producer`, `research-evolver`, `rebuttal-planner`, `ml-planner`; reviewers `novelty-scout`, `sufficiency-verifier`, `ablation-critic`, `research-meta-reviewer` | Producer and specialist |
| Specialist review (15) | `plan-critic`, `normalization-auditor`, `object-selection-mapper`, `discrepancy-attributor`, `trap-auditor`, `re-deriver`, `second-method-deriver`, `model-critic`, `ml-reviewer`, `figure-critic`, `assumption-auditor`, `integrity-auditor`, `comparative-reviewer` (a research reviewer by task), `higgs-combination-reviewer`, `higgs-theory-uncertainty-auditor` | Specialist |
| Governance (3) | `physics-critic`, `skeptical-verifier`, `physics-decider` | Voting |
| Decision justification (3) | `rdj-edge-reviewer`, `rdj-critic`, `rdj-verifier` | Specialist |
| Investigation (2) | `rca-investigator`, `investigation-worker` | Investigation |
| Writing (1) | `manuscript-writer` | Producer |
| Integrated tools (24) | Rivet routine construction (`routine-constructor`, `upstream-agentrivet-analyst`, `-coder`, `-code-reviewer`, `-physics-reviewer`), model-parameterization consultants (`ma-coupling-order-consultant`, `ma-eft-consultant`, `ma-scales-pdf-consultant`, `ma-ufo-consultant`) and SFitter roles (`sf-*`, 15) | Producer, advisory and specialist |

**What a role sees.** Each card declares one of four views.

| View | Contents | Roles |
|---|---|---|
| Full | The whole run context | Driver, decider, figure critic, assumption auditor, integrity auditor, model critic |
| Workspace | Its own isolated workspace with read-only copies of its inputs | Producers, consultants, investigators |
| Blind | A review packet that code computes from the evidence, with no raw inputs, no work order, no producer headline, no lessons and no withheld sources | Physics critic, skeptical verifier, the research and decision-justification reviewers, and the auditors, mappers and derivers that recompute a quantity |
| Structural | The proposals' predictions, receipts and requests with authors and rationale removed | Plan critic, ML reviewer |

**What a role does.** Every tool call goes through the RAVEL broker, which serves the actions on the role's
toolbelt and writes a receipt for each call. On a command-line worker route a card is raised to the route's tool
level, so a non-blind reviewer receives the route's full toolbelt and can rerun a check or recompute a number; a
producer's toolbelt also runs the self-checks its reviewers require. The 24 cards that declare `requires.blind`
keep workspace read and write and the actions their own card names (knowledge query, check run and, for most,
review-context read), and judge the packet they are given. Four review roles of the agent graph (`critic`,
`verifier`, `rdj_critic`, `rdj_verifier`) keep workspace read and write and nothing else. Every reviewer card
forbids the producer's headline, lessons and withheld sources.

**Who reviews whom.** Each producer card names its reviewers, and the dispatcher derives the producer's
self-checks from them. For example, the generator is reviewed by the normalization auditor and the trap auditor;
the analysis author by the object-selection mapper and the physics critic; a calculation by the skeptical verifier.

## When each role enters

| Point in the study | Gate | Roles |
|---|---|---|
| Plan, before CHECK-IN 1 | Plan approval | `plan-critic` (advisory; blocking under delegated operation) |
| First use of a tool, a failure or a contested step | — | The producer's declared consultant, for example `consult-madgraph` before the first smoke run |
| A stage fails | Correction | `rca-investigator`, `investigation-worker`, `skeptical-verifier`; `physics-improver` proposes the smallest repair |
| CHECK-IN 2, per claim | CHECK-IN 2 acceptance | Voting panel; `normalization-auditor` for simulated acceptance or absolute yields; `object-selection-mapper` with a second independent `analysis-author` for reimplemented selections; `discrepancy-attributor` for a deviation from the reference; `trap-auditor` for the trap sweep |
| Research request or method-performance claim | Research choice | Research family, stage by stage |
| Figures and documents | Delivery, report integrity | `figure-critic`, `integrity-auditor`, `assumption-auditor` |
| CHECK-IN 3 | Final task | Voting panel |
| Any consequential action | The action's gate | `rdj-edge-reviewer`, `rdj-critic`, `rdj-verifier`, by risk class |

**The voting panel.** The physics critic tests the frozen evidence; the skeptical verifier tests it again,
including every obligation inherited from earlier reviews; the physics decider recommends a claim scope and cannot
overrule a blocker. The verifier follows the critic and the decider follows both. Acceptance requires
all three to accept the same scope declared before the review, every required check to pass and every inherited
finding to be closed. A send-back must locate its findings. A correction is authorized by the decider alone, within
the paths, stages and redo count the review policy fixed before CHECK-IN 1, and it consumes a redo even if it fails.

## Independence

Independence is established by construction and recorded in receipts.

- **Separate actors.** The critic, verifier and decider are three different actors, and each differs from the
  proposer and the executor; the proposer and the executor can be one actor. Each review must come from the
  actor declared for that role.
- **Fresh sessions in isolated workspaces.** Every card role runs in a fresh session. A worker's workspace holds
  its inputs (read-only, digest-checked), its outputs, scratch space and its call log. RAVEL takes a digest of the
  run tree before and after, and a worker that changed the run is voided. A declared output counts when a broker
  receipt pins its bytes.
- **Isolation by route.** A command-line worker runs under an operating-system sandbox with no user
  configuration. On a hosted-model route or RAVEL's own loop, RAVEL makes the model call itself and every tool
  call passes through the broker. A host's own subagent runs under the host's tool policy with the user's
  configuration loaded, and its receipt is host-attested at most; an external relay is host-attested. Three
  planning roles of the agent graph (`proposer`, `improver`, `designer`) can be answered from the host's own
  context, and their receipts record that isolation.
- **Transport attestation.** The dispatcher labels each worker receipt *transport-attested* when the session
  exited cleanly, used a session identifier no earlier worker used, ran with confirmed sandbox denials and loaded
  no user configuration. Other receipts are host-attested or self-attested. On a command-line or host route a
  voting role requires a sandbox-isolated worker, and a blind role requires a blind-capable route; a host's own
  subagent serves neither. Selection checks each route's tools, isolation, attestation and qualification level
  (declared, stub-tested, probed or live-qualified). A probe confirms a command-line route's flags; it does not
  establish sandbox isolation, and a sandboxed worker route serves blind roles after a live qualification run.
- **Full-tool reviewers.** Non-blind review roles run with the route's full toolbelt in their isolated
  workspace. Their independence comes from the sandbox and the isolation of configuration, not from withholding
  tools.
- **Distinct models where it matters.** A card can require a model family different from another role's, checked
  on the observed models; the ML reviewer differs from the ML trainer.

## Dispatch

Work runs as an *agent graph*: a finite acyclic graph of nodes with a budget for nodes, calls, output tokens,
wall time and reworks. Dependencies schedule nodes; they do not pass context. An agent node dispatches one worker;
a map node dispatches up to 256 items over at most 16 concurrent workers and joins on all items or on a
quorum, a declared minimum number of successful items. Each
worker is pinned to its card digest and has budgets for turns, wall time, broker calls and cost.

When a worker exits, the dispatcher computes its status (ok, failed, refused, voided or ambiguous) from checks it
runs itself: self-checks, declared outputs, the final record, the exit status, the unchanged run tree and
inputs, budgets and broker receipts. A failed item retries as a new attempt, up to 16. An ambiguous call, one
started without a recorded outcome, is never retried automatically. Reworking a node invalidates it and its
descendants.

## How the physicist steers

- **Approvals.** CHECK-IN 1 approves a plan at a rung and records the physicist's quoted words, an authority
  label and a fingerprint of every input. The rungs are ordered `none` < `dry` < `smoke` < `full` < `scan`, and an
  approval never exceeds the rung the request asked for. `none` runs no compute (surveys and summaries of
  published results); `dry` renders cards and configurations and generates no events; `smoke` runs one point at
  small statistics, the CHECK-IN 2 waypoint; `full` runs one point at full statistics; `scan` runs every point.
  On a plan built from a specification, `full` means the complete scoped calculation in one attempt; it
  schedules no detector simulation or scan, and CHECK-IN 2 does not apply. On a driver-written plan,
  CHECK-IN 2 records a GO bound to the waypoint evidence and the accepted review, and CHECK-IN 3 accepts or
  revisits the final deck.
- **Steering.** `ravel steer` records a note, requirement, redirect, pause, resume, veto or priority at any time.
  The driver reads the steering state before every dispatch. A scope increase needs a renewed plan approval.
- **Budgets.** CHECK-IN 1 shows the cost forecast and the agent ceilings. The defaults are 6 concurrent workers,
  72 worker invocations for an analysis or 120 for research, 3 investigations per review, 2700 s per producer and
  1200 s per reviewer, and one native scientific job per machine. API routes carry dollar caps.
- **Delegation.** The physicist can delegate plan approval, the CHECK-IN 2 GO and acceptance of a
  recommendation, in their own words, with explicit bounds on compute plans, changed paths, stages and redos.
  The delegation is bound to the objective, so it cannot change the question or the resource contract, and it can
  be revoked at any time. Delegated decisions are labelled as machine decisions under user delegation, never as
  human review.

Implementation: `src/ravel/data/roles/registry.json` and `review_points.json`, `ravel.workflow.role_registry`,
`agent_graph`, `agent_worker`, `physics_review`, `scientific_autonomy`, `run_ceilings`; transports in
[transports](../reference/transports.md); check-ins in [check-ins](../workflow/checklists/check-ins.md).

## Glossary

| Term | Meaning |
|---|---|
| Agent graph | A budgeted acyclic graph of worker dispatches |
| Blind packet | Review input computed by code from the evidence, without the producer's framing |
| Check-in | A scheduled stop for the physicist: plan, early verification, final results (no CHECK-IN 2 for a specification plan) |
| Driver | The physicist's session, holding the coordinator role |
| Model family | The vendor family of a model, read from its identifier |
| Model tier | `judgment`, `agent` or `cheap`: the class of model a card requires |
| Quorum | A map join that completes when at least *n* items succeed |
| Role card | The declared purpose, view, tools, budgets and reviewers of a role |
| Transport attestation | A worker identity established by the dispatching host from the session it ran |
| Voting panel | Physics critic, skeptical verifier and physics decider |
| Waypoint | The early result checked at CHECK-IN 2 before bulk compute |
| Worker | A fresh session performing one role in its own workspace; sandboxed on command-line routes |

See also the [RAVEL glossary](../reference/glossary.md), the [research loop](research-loop.md) and
[Recursive Decision Justification](decision-justification.md).
