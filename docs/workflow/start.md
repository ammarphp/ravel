# Start or resume a physics request

Describe the scientific question in ordinary language. "Initiate:" is optional. Name a paper,
figure, analysis, model or mass range when known; attach available inputs. Missing inputs
prompt public-resource recovery first, then explicit owner questions or justified assumptions. A request to develop a collider-search method starts
as a bounded research proposal, with data access, baselines, evaluation splits, calibration and
compute still to be agreed. It does not launch model training.

RAVEL prioritizes broad LHC recasting,
scientific-tool integrations, custom routines and fits, and physics judgment. The current program includes source-backed method development through bounded research
experiments. Dedicated new ML-training expansion remains separate later work with its own
prerequisites. This priority does not imply new executable support;
use the actual contract and evidence for the requested operation.

For an analysis, the first deliverable is CHECK-IN 1: the request restated, relevant published
figures with captions, a proposed verification waypoint, a scoped plan and budget, and numbered
assumptions. Choose manual decisions or explicitly delegated autonomous operation below.
The user may answer, ask questions or change the proposal. Generation, including smoke,
starts only after the exact plan receives manual or authorized delegated approval.
Timing depends on the chosen analysis and resources;
the approved budget and actual completed coverage are reported, not promised in advance.

Internal CHECK-IN 2 reviews executed evidence; a fresh CHECK-IN 3 critic, verifier and synthesizer
cycle reviews final research artifacts and the whole-task population. These steps continue in
autonomous mode under the original resource and correction bounds. Later check-ins retain
comparisons, deviations, and final figures with artifact-backed numbers and limitations.
Required verification follows `docs/workflow/steps/09-verify.md`.
An exclusion request that does not prescribe a statistic gets 95% CLs exclusion limits by
default. When the request prescribes a statistic (an explicit formula, an Nσ region, a Δχ²
threshold or a Bayesian credible interval), that statistic is the primary result, with CLs
optionally alongside. Fits, measurements, calculations and summaries report their own
quantities. Reference agreement is not discovery or coverage certification. The requested
deliverable controls whether a point, figure, or scan is appropriate.

## Which route a request takes

Use the first row that matches. The first three rows depend on what the request supplies or
produces, so they come before the derived `task_mode`. If `inputs/intake_handoff.json` or
`current_state.json` names a different next step, follow this table.

`ravel initiate` reads the request into `inputs/reading.json` (facts with exact spans,
constraints, deliverables, open questions and boundaries) and writes the obligation census into
the contract. The `task_mode` is derived from that reading; see
[task modes](../reference/scope.md#1-task-modes-task_mode).

| Request | Route | Next step |
|---|---|---|
| Whole scope works on supplied events, models, workspaces or measurements | Scientific-study route | Draft the typed specification from [scientific studies](reference/scientific-studies.md) and run `ravel plan --rundir <new-run> --spec study.json`; its CHECK-IN 1 is the intake. Skip `initiate`. |
| A manuscript, note or paper from existing results | `manuscript-build` mode | Write with [staged manuscript authoring](../reference/staged-manuscript-authoring.md), then build the PDF in an ordinary `manuscript-build` study ([manuscript production](../reference/manuscript-production.md)). |
| Feynman diagrams, diagram estimates or amplitudes for a model and process | `feyn-graph`, `diagram-analysis` or `feynarts-amplitude` mode | Check inputs with `ravel feyn-graph inspect`, then plan the study with `ravel plan` ([model-bound diagrams](../reference/model-bound-diagrams.md)). |
| `open` route: a research parent that no rule recognises as one bounded shape (`next_route=open`) | Open parent | Read `inputs/reading.json`, the obligation census and `inputs/plan.json` when present. Compose the request from the operation catalogue: prepare each component as an ordinary study with `ravel plan --spec`, or run `ravel research-orchestrate` for open-ended research. Each child has its own CHECK-IN 1. Every obligation stays open until a child covers it or a boundary row bounds it. |
| `research`, `method_study`, `anomaly_search` | Research orchestrator | `ravel research-orchestrate prepare` with the parent contract, then `run` ([research orchestration](reference/research-orchestration.md)). A `method_study` keeps `<run>/method_proposal.md` as an intermediate plan. |
| `reproduce`, `reinterpret`, `scan`, `projection`, `survey`, `summary_plot`, `no_routine` | Analysis intake | Follow `docs/workflow/steps/02-inputs.md` (resource sweep, route analysis, trap sweep, figures and cost), then present CHECK-IN 1 from `docs/workflow/checklists/check-ins.md`. |
| `calculation` | Calculation route | `ravel intake-plan` prepares the designer choice ([calculations and research intake](../reference/intake-and-challenges.md)). Exact arithmetic uses `literal-calculation`. No detector stage or figure is required. |
| `generate`, `likelihood` | Scoped route | `ravel plan --spec`, CHECK-IN 1, `ravel approve`, `ravel run` ([scoped workflow](reference/scoped-workflows.md)). A request whose stages the scoped adapter cannot all run, such as a Herwig shower or a detector simulation, is an open research parent instead, with each stage an obligation. |
| `unsupported` (held draft) | Capability recovery | Only a boundary holds a request: no scientific object, an ungrounded context identifier, or a claim, input or contradiction that holds every part of it. Read the boundary rows in `inputs/reading.json` and `inputs/capability_recovery.json`; each states what would make the request possible. Supply that, or a grounded `--interpretation`, then follow the row of the resolved kind. `ravel initiate` exits 1 only here. |

Open research follows the [required stages and keyless stage handoff](reference/research-orchestration.md#required-research-stages); missing artifacts block progression and completion.

## Choose manual or delegated operation

Manual mode presents the exact plan for the user’s actual assent. To delegate decisions,
explicitly ask to **run autonomously** in the complete initial request or in the actual
CHECK-IN 1 response. The coordinator records that text, the original objective, named
machine delegate, permitted compute plans and stages, allowed changed paths and redo
ceilings. It prepares the declaration with `scientific_autonomy.prepare_declaration`
before the initial plan, or retains the existing CI1 response with
`scientific_autonomy.record_checkin1_delegation`. For a Host-planned child,
`ravel intake-plan checkin1-response` authenticates that same transition.

The ordinary `science.approve_delegated` path records the machine decision within those
bounds. The coordinator then executes and advances the required internal reviews,
retained-evidence requests and bounded repair loop without requesting another human
response for an already delegated action. CI2 and fresh CI3 research review remain
required; decisions identify machine authority under the user’s instruction. The
validated literal calculator retains its distinct complete calculation-delivery path.
Revocation, an unclear delegation or a requested change outside those bounds follows
the existing authority checks. Keep the current run and all spent work.

## Agent procedure: a new request

For a request whose complete scope is an operation on **supplied events or models**,
first consider the [scientific-study route](reference/scientific-studies.md):
inspect the actual selected `science.MODES` and dispatch contracts, including current
construction/build, quantities, model/provider, response and native statistical operations.
Every candidate remains within its own adapter contract. Preserve the original request,
identify the supplied input meaning and missing scientific evidence, then draft its
typed specification and numbered assumptions. Use `ravel plan` with a new directory
as the explicit intake and CHECK-IN 1; do not first create an incompatible
reproduction contract with `initiate`. This is host-agent routing, not a claim that
the bounded natural-language parser recognizes these new modes automatically.
Approval, execution, CHECK-IN 2 and evidence limits follow that guide. New version 2
operations require its prospective review and bounded correction contract.
Requests for new generation or paper reproduction continue through the procedure
below; a supplied-data operation must not silently substitute for their full scope.

1. Read `.claude/skills/physicist-intake/SKILL.md` (or its generated Codex mirror). Use the original
   request and a **new** run directory:
   ```sh
   ravel initiate --prompt-file request.txt --out <new-run>
   ravel validate <new-run>/inputs/task_contract.json --json
   ```
   From a source checkout without installation, replace `ravel` with
   `python3 scripts/run.py ravel.__main__`. The local action/negation parser drafts intent; a host
   agent may instead supply `--interpretation <intent.json>` grounded in the exact request hash
   and matching text spans. Supply it on the first call when the parser will clearly miss the
   request's kind. Structural validation does not establish scientific judgment.
2. Read the generated `current_state.json`. Resolve required inputs and draft assumptions using
   the relevant resource-sweep/route-analysis procedure and `docs/workflow/steps/02-inputs.md`.
   Check parser hints against the actual analysis, supplied inputs and available engines. A
   familiar model name must not substitute for the requested analysis. Preserve unmet requirements
   when no current route serves them; the development program does not authorize an incompatible run.
   Pick the next step from the table above. Calculation and research drafts retain the full
   question and an authenticated `inputs/intake_handoff.json`. For a calculation, the host uses
   `ravel intake-plan` to prepare a bounded designer Graph and authenticate its ordinary-study
   or source-development choice;
    a calculation needs no detector stages or compulsory figure. Exact literal arithmetic
    uses its approved ordinary calculation child; physical and symbolic calculations retain
    their scientific children, units and whole-parent completion reviews. Research uses the
   existing goal-bound cycle, blueprint and ordinary experiments. Read
   [calculations, research and challenge intake](../reference/intake-and-challenges.md).
   A `method_study` proposal is an intermediate planning artifact; its original
   scientific outputs remain whole-task obligations.
   For `task_mode=generate` or `likelihood`, follow the
   [scoped workflow](reference/scoped-workflows.md): prepare a typed specification with
   `ravel plan`, review CHECK-IN 1, record approval and use `ravel run`. Its required stages
   reflect the requested scope; do not initialize a detector analysis for a statistical fit.
3. Prepare CHECK-IN 1 using `docs/workflow/checklists/check-ins.md` and validate its JSON.
   In manual mode, present it and record the actual user assent. In explicitly delegated mode,
   authenticate the original instruction or actual CI1 transition and record the named machine
   decision through the ordinary approval path. Continue the next required step within that
   authority, keeping provenance, deviations, internal CI2 and fresh CI3 research review.
   Load environment setup when needed, using `docs/reference/environment.md`.

Intake records no completed skills, approved compute, or scientific result. The documented
procedure applies when host hooks are unavailable too. Existing guards scope a run by its
working directory/session; an unrelated old contract elsewhere is not sufficient.

## Dispatch production work (agent-layer epoch two)

Every compute operation in an epoch-two plan has a production role in
`src/ravel/data/roles/executors.json`; `host_operations` lists record-only commands and their reasons.
A plan with an unroutable compute node is refused at CHECK-IN 1 before approval with
`executor_role_missing`, naming the node, operation and required table mapping.
`ravel drive` sends every compute node of the approved plan to its role's governed worker.

The host plans, routes, dispatches, presents CHECK-INs and runs smoke rungs. It edits nothing under
`stages/` at the full or scan rung.

```sh
ravel work seal --rundir RUN               # before CHECK-IN 1: one sealed work order per node
ravel work pin-obligations --rundir RUN    # pins the derived obligations into CHECK-IN 1
ravel work next --rundir RUN               # the next ready node and its work order
ravel work dispatch --rundir RUN --node N  # the role's governed worker; the dispatcher writes the receipt
ravel work adopt --rundir RUN --node-id N --attempt 1
```

The node's compute still goes through the supervised stage, the decision gate and the
machine lease. The `executor` provider refuses a full or scan `launch` unless the node has
an ok receipt from its role's worker or a host waiver. If the host authors a node itself,
record `ravel work waive --rundir RUN --node N --reason "..."`. `ravel work host-authored`
lists those nodes for the CHECK-IN 2 packet and the delivery record. Under delegation a
waiver counts only with an R2 RDJ authorize receipt for its bytes.

`ravel drive --rundir RUN [--transport ravel-loop]` runs the whole lifecycle as the
`lifecycle.drive` graph. It needs no agent CLI. It dispatches the coordinator card as a
worker and runs the review points and production nodes. It stops at CHECK-IN 1, at
CHECK-IN 2 and at CHECK-IN 3. Record the approval through its ordinary path (`ravel approve`,
`ravel go` or `science.approve`), then resume:

```sh
ravel drive respond --rundir RUN --decision approve --record inputs/checkin1_approval.json
```

A resume without the run's own approval record, or with different bytes, is refused. A
refusal or hold ends the attempt; start the next with `--attempt 2`. Completed nodes and
credited reviews are reused. Epoch-one runs keep the procedure above.

## Agent procedure: resume an existing run

```sh
ravel status --rundir <existing-run> --write
```

Read the refreshed `current_state.json`: request, contract/ledger fingerprints, approval state,
execution receipts, lifecycle verdict, blockers and next required step. It is a derived view,
not execution authority. The executors and serving gates must check the current source artifacts
again. If inputs changed, repair the identified stale stage or approval; preserve failed receipts.

Open only the blocker-relevant workflow step or checklist. Use the run's `RESUME.md` and
`DEVIATIONS.md` for context when needed, not as substitutes for live validation. Do not replay
intake, overwrite an existing run, or survey the repository again after compaction.


A request that no rule recognises becomes an open parent, not a refusal. `ravel initiate`
retains a source-bound capability recovery packet, literal request, reading, contract and
current state, and exits 0. It prints the label, the obligation coverage, the gaps, the open
questions and any boundary. A held `unsupported` draft keeps the same files and exits 1. For an
unfamiliar or compound request, inspect it, preserve the exact whole goal, and compose it from
typed component specifications.
Current engine contracts, rather than particle keywords or an old list of modes, determine
candidate support. The source-only planner can be called directly:

```bash
python -m ravel.workflow.capability_routing --prompt-file request.txt --out recovery.json
```

Its candidate suggestions do not select an analysis, authorize compute or accept the parent
request. Discovery/retrieval/reversible preparation can continue under existing authorization.
A missing identifier, routine, likelihood, off-grid map entry or required plotting package
first prompts targeted recovery/adaptation. Unavailable private data, an incompatible model
and unsupported scientific claims still hold the dependent result. Partial work and alternative
assumptions remain explicit; they never replace a requested scan, cross-search synthesis or
reproduction. A hypothetical response study does not imply a future-luminosity projection or
require immediate tagger training.

For ordinary scientific/scoped studies with a retained environment capsule,
[prepared runtime replay](../reference/prepared-runtime.md) explicitly restores
only the eight planned environment variables before the normal approval or run
checks. Use it for inherited environment drift; changed source or inputs still
require their normal new plan and actual assent. Historical missing values are
not reconstructed from hashes.

For a source-bound DAOD columnar query or supplied native ROOT/Parquet return,
use the [supplied columnar operation](../reference/dataset-query-quantities.md).
It retains the complete supplied dataset/member/exposure and observable populations;
source-only context preparation connects to the ordinary unapproved scientific
plan. Credentials, native runtime, query/analysis source and subsequent review
remain explicit inputs and workflow obligations.

For a supplied EasyScan scan contract, sampler and ordered external programme chain, use [the native EasyScan operation](../reference/parameter-space-sampling.md). Supply a study identity, pinned request and INI, complete mappings and source/runtime/workspace manifests, finite resources and a selected JSON or CSV table export. Missing inputs are refused with a typed reason; context is source-only and the ordinary scientific plan remains unapproved.


For supplied ROOT tree-to-array export, inspect with
`ravel tree-array-export inspect --task task.json` and use science mode
`tree-array-export`. Supply the pinned schema-2 dataset, tree, column, shape,
padding, overflow and output-format contract described in the
[array export reference](../reference/tree-array-export.md). Preserve all source
rows, positional order, units and separate raw normalization columns. Consumer
associations are supplied inputs. Missing data or readers remain inputs to
recover. Execution requires the existing method-decision, admission and
plan/approve/run route; inspection grants no execution or scientific authority.


### Native source-graph diagnostics and calibration

Ordinary `native-statistical-construction` cells may explicitly declare fixed-NLL
derivatives or full-auxiliary fixed-truth calibration. Read the [source graph
diagnostics and calibration contract](../reference/source-graph-diagnostics-calibration.md)
before preparing these studies. Observed data, explicitly generated Asimov data,
conditioning fits and calibration experiments retain separate source populations
and ordinary approval/review requirements. Software source checks do not establish
native integration, sampling, optimizer or coverage qualification.


### CosmicIC and Nyx source-bound operations

The ordinary `cosmic-evolution` mode prepares supplied source, native cards,
transfer tables and complete IC/Nyx product commitments. Read the
[CosmicIC/Nyx operation contract](../physics/cosmic-evolution.md) before planning
retained-product reuse or an explicitly admitted site-local operation in an
already allocated job. Missing generator/writer sources, runtime/build closure,
IC normalization and remote accounting remain explicit prerequisites. Source
preparation does not establish native evolution or scientific qualification.


### Contur native companion operations

The ordinary `contur-companion` mode connects declared native SM tests, Herwig
cross-section and branching extraction, parameter-map plots, and Rivet plots to
source capture, unapproved planning and supervised operation reports. Read the
[Contur companion contract](../reference/contur-companion.md) for complete input and product
populations, serial profiles and runtime requirements. Joint model-point/all-beam
grids use `contur-yoda`; cached results and software controls do not qualify native
execution, statistical inference or scientific applicability.


### Required site ROOT and WMS route

For a complete explicit site ROOT sample/DSID population, use ordinary `root-stream`
and the [site workflow contract](../reference/site-workflows.md). Source-reviewed
analysis/blinding and full original MC normalization remain required. Export
already prepared studies with `ravel site-workflow`; the separate Linux analysis
and WMS profiles are required, and existing approvals/campaign budgets remain
authoritative. A source export does not establish site access or scientific results.
