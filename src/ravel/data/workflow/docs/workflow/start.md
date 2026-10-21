# Start or resume a physics request

Describe the scientific question in ordinary language. "Initiate:" is optional. Name a paper,
figure, analysis, model or mass range when known; attach available inputs. Missing inputs
prompt public-resource recovery first, then explicit owner questions or justified assumptions. A request to develop a collider-search method starts
as a bounded research proposal specifying data access, baselines, evaluation splits, calibration and
compute for review.

RAVEL connects scientific questions to source-backed plans, specialist operations, review and
evidence records. Use the actual contract and evidence for the requested operation.

For an analysis, the first deliverable is CHECK-IN 1: the request restated, relevant published
figures with captions, a proposed verification waypoint, a scoped plan and budget, and numbered
assumptions. Choose manual decisions or explicitly delegated autonomous operation below.
Answer, ask questions or change the proposal at this check-in. Generation, including smoke,
starts only after the exact plan receives manual or authorized delegated approval.
Timing depends on the chosen analysis and resources;
the approved budget and actual completed coverage are reported, not promised in advance.

Internal CHECK-IN 2 reviews executed evidence; a fresh CHECK-IN 3 critic, verifier and synthesizer
cycle reviews final research artifacts and the whole-task population. These steps continue in
autonomous mode under the original resource and correction bounds. Later check-ins retain
comparisons, deviations, and final figures with artifact-backed numbers and qualifications.
Required verification follows `docs/workflow/steps/09-verify.md`.
An exclusion request that does not prescribe a statistic gets 95% CLs exclusion limits by
default. When the request prescribes a statistic (an explicit formula, an Nσ region, a Δχ²
threshold or a Bayesian credible interval), that statistic is the primary result, with CLs
optionally alongside. Fits, measurements, calculations and summaries report their own
quantities. Reference agreement is not discovery or coverage certification. The requested
deliverable controls whether a point, figure, or scan is appropriate.

## Start a request: the controller

Give the request to RAVEL's controller from your own terminal:

```sh
ravel ask "<the question, in your own words>"
ravel drive --request-file request.txt [--input [KIND=]PATH ...] [--rundir <new-run>]
```

The controller is one RAVEL process that owns the run from intake to delivery. The request
bytes come only from your argument or file (from the operator's file with `--unattended`); no
agent rewrites them. The controller writes the reading, selects the route below, compiles a
typed plan, presents CHECK-IN 1 at your terminal, runs every step through the governed step
graph, presents CHECK-IN 2 at a verification waypoint and CHECK-IN 3 before delivery, and
delivers through one sink. Model sessions are workers that individual steps start, with only the
tools those steps allow. `ravel status --run <run-id>` shows progress from another terminal.
A run ends in a delivery or in a qualified ending that states every original obligation as
satisfied, negative, partial or blocked.

Unattended runs (a cluster or facility submit host) take their authority from the operator's
configuration, written beforehand with `ravel operator`; the controller then waits, notifies or
takes a recorded conservative default within the configured bounds.

An answer typed at the controller's terminal is recorded as unattested terminal evidence
(`terminal_operator_unattested`): terminal input has unattested identity, so a typed approval never
authorizes anything by itself, and no record labels terminal input a physicist's or a human's
decision (`physicist_terminal_response` is unreachable on this platform). After an approval at the
terminal the run keeps waiting, and its pause names the operator-answer step: `ravel operator answer
--run <run-id> --request <id> --code <code> --decision <decision>`, quoting the request and the
challenge code printed with its WAITING line at the controller's terminal. The operator's
notification command receives only the run name and a state code, never the challenge code.
That authenticated operator command is what the check-in gate accepts; continue with
`ravel drive --resume <run-id>`. A refusal typed at the terminal is taken as it is.

## Which route a request takes

Use the first row that matches. The first three rows depend on what the request supplies or
produces, so they come before the derived `task_mode`. If `inputs/intake_handoff.json` or
`current_state.json` names a different next step, follow this table.

`ravel initiate` reads the request into `inputs/reading.json` (facts with exact spans,
constraints, deliverables, open questions and boundaries) and writes the obligation census into
the contract. The `task_mode` is derived from that reading; see
[task modes](../reference/task-contract.md).

| Request | Route | Next step |
|---|---|---|
| Whole scope works on supplied events, models, workspaces or measurements | Scientific-study route | Draft the typed specification from [scientific studies](reference/scientific-studies.md) and run `ravel plan --rundir <new-run> --spec study.json`; its CHECK-IN 1 is the intake. Skip `initiate`. |
| A manuscript, note or paper from existing results | `manuscript-build` mode | Write with [staged manuscript authoring](../reference/staged-manuscript-authoring.md), then build the PDF in an ordinary `manuscript-build` study ([manuscript production](../reference/manuscript-production.md)). |
| Feynman diagrams, diagram estimates or amplitudes for a model and process | `feyn-graph`, `diagram-analysis` or `feynarts-amplitude` mode | Check inputs with `ravel feyn-graph inspect`, then plan the study with `ravel plan` ([model-bound diagrams](../reference/model-bound-diagrams.md)). |
| `open` route: a research parent that no rule recognises as one bounded shape (`next_route=open`) | Open parent | Read `inputs/reading.json`, the obligation census and `inputs/plan.json` when present. Compose the request from the operation catalogue: prepare each component as an ordinary study with `ravel plan --spec`, or run `ravel research-orchestrate` for open-ended research. Each child has its own CHECK-IN 1. Every obligation stays open until a child covers it or a boundary row bounds it. |
| `research`, `method_study`, `anomaly_search` | Research orchestrator | `ravel research-orchestrate prepare` with the parent contract, then `run` ([research orchestration](reference/research-orchestration.md)). A `method_study` keeps `<run>/method_proposal.md` as an intermediate plan. |
| `reproduce`, `reinterpret`, `scan`, `projection`, `survey`, `summary_plot`, `no_routine` | Analysis intake | Follow `docs/workflow/steps/02-inputs.md` (resource sweep, route analysis, trap sweep, figures and cost), then present CHECK-IN 1 from `docs/workflow/checklists/check-ins.md`. |
| `calculation` | Calculation route | `ravel intake-plan` prepares the designer choice ([calculations and research intake](../reference/intake-and-challenges.md)). Exact arithmetic uses `literal-calculation`. No detector stage or figure is required. |
| `generate`, `likelihood` | Scoped route | `ravel plan --spec`, CHECK-IN 1, `ravel approve`, `ravel run` ([scoped workflow](reference/scoped-workflows.md)). For a multipart request requiring stages beyond the scoped route’s declared contract, retain every stage as an obligation in the research parent. |
| `unsupported` (held draft) | Capability recovery | Only a boundary holds a request: no scientific object, an ungrounded context identifier, or a claim, input or contradiction that holds every part of it. Read the boundary rows in `inputs/reading.json` and `inputs/capability_recovery.json`; each states what would make the request possible. Supply that, or a grounded `--interpretation`, then follow the row of the resolved kind. `ravel initiate` exits 1 only here. |

The controller evaluates this table as data: each route package ships a route spec
(`src/ravel/data/controller/routes/`) whose match predicate names its row, and the first spec
that matches in row order selects the route. A held request, an open parent, a request no spec
matches and a request whose matched route covers only part of it go to the judgment route, which
plans the request as typed steps under the same check-ins, review and sink. No request is
refused for lack of a fixed route.

The selector honours the recorded intake classification: an `inspect` intake retains its inspection route rather than a
scientific route solely because its task mode or prompt also matches that route. Conflicting
scientific deliverables remain obligations for judgment. Before admitting any ready step, the
controller verifies that `route.record_id` resolves to a route record of this run with the same
route id. Missing, unknown or inconsistent pins hold dispatch with `route_not_pinned`, including
routes with no admission adapter.

Open research follows the [required stages and keyless stage handoff](reference/research-orchestration.md#required-research-stages); missing artifacts block progression and completion.

## Choose manual or delegated operation

For controller runs, the operator sets the operating mode and its budgets once, with
`ravel operator`, outside any worker; every route uses that one record, the judgment route
included. A delegation sentence in the request counts only where the operator's configuration
allows request-stated delegation. The commands below remain for runs the controller does not own.

The operator can export `RAVEL_OPERATING_MODE` and `RAVEL_AUTONOMY_BOUNDS` before intake, but environment values alone never establish authority. A protected environment-selection receipt and a separate exact run-selection receipt are required. An explicit affirmative delegation statement in the request selects operating-mode autonomy only with that run-selection receipt. Without the operator service, intake still admits the request: it freezes the configured or default mode, and the statement remains available to the existing text-delegation paths (`prepare_declaration`, `record_checkin1_delegation`) exactly as before. A present but invalid or mismatched ledger still refuses. No provider, model, or credential setting is read. The authority consumer reads only the fixed protected ledger described below.

Precedence is explicit request, authenticated operator environment, project, user default. An unset mode is physicist-in-the-loop. Approval prerequisites, negated delegation and conflicting instructions preserve human check-ins. Intake freezes even the implicit human default in custody; its extra input file is omitted for compatibility. Children inherit the original choice and budget, never current defaults. Every approval records its source. Later operator changes affect future runs only; the agent must not create operator receipts. The worker sandbox must keep trusted runtime code and machine custody outside the agent's writable surface.

Autonomous mode authorizes machine decisions within the retained plan, stage, resource and retry bounds. Supply the scientific inputs and review receipts required by the plan. Complete the plan and CHECK-IN 1, obtain required independent plan review/RDJ receipts, then call ordinary `workflow_state approve` (or `delegated-approve`). The receipt is labelled `delegated_machine` and records the mode source. Never turn a delegation quote into a claimed human approval. A changed plan, missing authority, revocation, exhausted ceiling, unresolved critical ambiguity, scientific hold, or absent required review still refuses.

Explicit affirmative delegation in the retained initial request remains supported alongside operator defaults. The coordinator records that text, the original objective, named machine delegate, permitted compute plans and stages, allowed changed paths and redo ceilings, and prepares the declaration with `scientific_autonomy.prepare_declaration` before the initial plan. For a new delegation in the actual CHECK-IN 1 response, retain that response through `scientific_autonomy.record_checkin1_delegation`; for a Host-declared child use `ravel intake-plan checkin1-response`. The ordinary `science.approve_delegated` path records the machine decision within those bounds; the coordinator then advances the required internal reviews, retained-evidence requests and bounded repair loop without requesting another human response for an already delegated action. Keep the original objective and scientific contract unchanged. CI2 and fresh CI3 research review remain required, with machine decisions identified as such. The validated literal calculator retains its distinct complete calculation-delivery path. Keep the current run and spent work when a boundary requires escalation.

## What the controller does with a new request

1. **Intake.** The controller pins the request bytes in the run's protected store (outside the
   run directory), writes `request.txt`, `inputs/reading.json` and the draft contract as reading
   copies, and freezes the operating mode. Nothing is surveyed or launched before the route is
   recorded.
2. **Route.** The table above selects a fixed route or the judgment route. A fixed route's spec is
   compiled into a typed plan; every deliverable in the reading maps to a step output or stays an
   open obligation. Open obligations send the request to the judgment route, which keeps the
   covered part.
3. **Plan review and CHECK-IN 1.** Each step receives its instruction manifest; an independent
   plan critic reviews the plan; CHECK-IN 1 is decided by you at the controller's terminal, or by
   the operator's configuration in unattended mode. A refused or revised plan dispatches no
   step. Machine authority is never labelled human.
4. **Execution in waves.** Ready steps run through the governed step graph: reservation,
   instruction packet, sandboxed worker or confined launch, validation, adoption, review and
   credit. At a verification waypoint CHECK-IN 2 decides whether full and scan rungs can run. A
   changed plan needs renewed authority; an escalation goes to you or the operator; a hold stops
   only its own branch.
5. **Final review, CHECK-IN 3 and delivery.** Fresh reviewers check the result before CHECK-IN 3;
   the sink renders the deliverable, its labels and its receipt. A stop, an exhausted budget or a
   branch nothing can release ends in a qualified delivery instead.

Every route keeps these scope rules, which the plan, its reviews and the check-ins enforce:

- A supplied-data operation never substitutes for a request to generate events or reproduce a
  paper; such a request keeps its full scope.
- A familiar model or analysis name never substitutes for the requested analysis; unmet
  requirements stay open when no current operation serves them.
- A calculation needs no detector stage and no compulsory figure; physical and symbolic
  calculations keep their units, children and whole-request completion review.
- A method-study proposal is an intermediate plan; its original scientific outputs remain
  obligations of the whole request.
- A scoped generation or likelihood request runs only the stages it asks for; a statistical fit
  does not start a detector analysis.

## Commands outside the controller (legacy runs)

The 1.1.0 commands keep working on runs the controller does not own; their results carry the
`NOT GOVERNED` label. For a controller-owned run, every command that writes approvals,
responses, steering, a stop, review verdicts, run registration or custody is refused before it
runs; read-only commands (`ravel status --rundir` without `--write`, `doctor`, `knowledge`,
`modes`, `validate`) stay available.

For a request whose complete scope is an operation on supplied events or models, the
[scientific-study route](reference/scientific-studies.md) uses `ravel plan --rundir <new-run>
--spec study.json` as its intake and CHECK-IN 1. Otherwise start with
`ravel initiate --prompt-file request.txt --out <new-run>` and
`ravel validate <new-run>/inputs/task_contract.json --json` (from a source checkout without
installation, `python3 scripts/run.py ravel.__main__` replaces `ravel`), read the generated
`current_state.json`, resolve inputs through `docs/workflow/steps/02-inputs.md`, prepare
CHECK-IN 1 from `docs/workflow/checklists/check-ins.md`, record approval through the ordinary
path and continue the next step. Scoped generation and likelihood requests use
[scoped workflows](reference/scoped-workflows.md); calculations and research use
[calculations, research and challenge intake](../reference/intake-and-challenges.md).

Every compute operation in an epoch-two plan has a production role in
`src/ravel/data/roles/executors.json`. `ravel work seal|pin-obligations|next|dispatch|adopt`
manage sealed work orders, and `ravel drive --rundir RUN` runs a legacy run's lifecycle graph;
it stops at each CHECK-IN and resumes with
`ravel drive respond --rundir RUN --decision approve --record inputs/checkin1_approval.json`
after the approval is recorded through its ordinary path.

The host plans, routes, dispatches, presents CHECK-INs and runs smoke rungs. It edits nothing under
`stages/` at the full or scan rung. A node's compute still goes through the supervised stage, the
decision gate and the machine lease: the `executor` provider refuses a full or scan `launch` unless
the node has an ok receipt from its role's worker or a host waiver. If the host authors a node
itself, record `ravel work waive --rundir RUN --node N --reason "..."`; `ravel work host-authored`
lists those nodes for the CHECK-IN 2 packet and the delivery record. Under delegation a waiver
counts only with an R2 (or higher) RDJ authorize receipt for its bytes. Epoch-one runs keep their
own procedure.

## Resume an existing run

A controller run resumes with `ravel drive --resume <run-id>`: the same graph thread, plan,
budgets, attempts and records, read from its store and re-verified. A run whose store does not
verify, or whose directory was copied, moved or replaced, is refused; its custody stays with
the original. `ravel status --run <run-id>` reads it without writing.

A legacy run resumes from `ravel status --rundir <existing-run> --write`: read the refreshed
`current_state.json` (a derived view, not execution authority), open only the blocker's step or
checklist, use `RESUME.md` and `DEVIATIONS.md` for context, and never replay intake or
overwrite the run.

## Requests with no fixed route

A request no route spec matches, an open parent and a held draft go to the judgment route: it
frames the question with numbered assumptions, decomposes it into typed steps from the
operation catalogue, records and reviews every judgment call, asks you or the operator when it
must, and ends in a reviewed result or a qualified one. A held draft keeps its boundary rows;
capability recovery runs as ordinary steps. The source-only recovery planner can be called
directly:

```bash
python -m ravel.workflow.capability_routing --prompt-file request.txt --out recovery.json
```

Its candidate suggestions do not select an analysis, authorize compute or accept the parent
request. A missing identifier, routine, likelihood, off-grid map entry or required plotting
package first prompts targeted recovery or adaptation. Missing private data, an
incompatible model and unverified scientific claims still hold the dependent result. Partial
work and alternative assumptions remain explicit; they never replace a requested scan,
cross-search synthesis or reproduction. A hypothetical response study does not imply a
future-luminosity projection or require immediate tagger training.

For ordinary scientific/scoped studies with a retained environment capsule,
[prepared runtime replay](../reference/prepared-runtime.md) explicitly restores
only the eight declared environment variables before the normal approval or run
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

Ordinary `native-statistical-construction` cells can explicitly declare fixed-NLL
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
