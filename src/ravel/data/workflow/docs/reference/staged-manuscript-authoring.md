# Staged manuscript authoring

The staged writer prepares an outline, consumes its actual response, and uses it
to issue bounded citation, caption, section and revision calls. Each call keeps
its own current request, model identity, usage, source context and image receipt.
The terminal synthesis produces the manuscript through the existing author
consumer. Independent integrity review, the ordinary native build, compiled
visual review and whole original task acceptance still govern delivery.

Use the scientific intake in [start.md](../workflow/start.md) and the required
[installation profiles](../installation.md). Writing uses the configured Host
model or explicitly selected external writer. Native author images require an
explicit vision-capable model and the required Pillow/PDFium runtime. A selected
TeX or image-conversion route also needs its bound native prerequisites. A source
binding or software regression does not qualify a provider, publisher or result.

## Prepare the source and allocation

A `staged-manuscript-request` has `schema_version: 2`, a pinned known
`production_request`, located `missing` obligations, an ordered `phase_slots`
list and one `budget`. The known production request retains the original task,
current quantitative report, actual method/code/result records, environment,
skills, formatting and source-review policy. Missing citation, figure, method
and evidence records each have an ID, description and located original source.
Planning can start with these obligations; final source resolution must supply
all their actual records. Missing data is never replaced with synthetic results.

The first slot is `story`, the last is `synthesis`. Other slots select
`citation-scout`, `caption`, `section`, `coherence` or `editorial-revision`.
Every later slot depends on its consumed story; synthesis depends on all earlier
slots. Each runtime declares the model/build, transport, input/output/context
bounds, wall ceiling and accounting policy. The sum of calls, output and wall
reservations must fit the original campaign allocation. Revisions consume that
same allocation. Unknown external token counts remain null under an explicitly
selected `reserved_unknown` policy; reservations are never reported as usage.

The APIs live in
[manuscript_workflow.py](../../src/ravel/workflow/manuscript_workflow.py).
`prepare_story(request_pin, out, base_dir=..., campaign=...)` creates the initial
Graph binding. `execute_phase(prepared, host)` uses the existing charged campaign
executor. `consume_phase(prepared, out, base_dir=...)` authenticates the current
response into a story product. The outline requires the actual charged writer response.

## Consume the story and its phases

The actual story contains the complete claim/evidence/counterevidence map,
method and quantity references, plotting objectives, introduction and related
work tasks, section dependencies, citation obligations, phase plan and unresolved
population. Statements such as a proposed novelty gap or unsubstantiated theorem
remain hypotheses or unknown claims. Matching a citation's identity does not
establish its scientific applicability.

`prepare_phase(story, phase_id, out, base_dir=..., campaign=...,
prior_products=..., resolution_pin=...)` consumes the exact ordered prior products.
`phase_destination(...)` and `consumption_destination(...)` derive the unique
issuance and consumption paths from authenticated bindings. Each source-reserved
slot is issued once. Pending, failed, interrupted and unissued slots remain in
`phase_status`; an unknown started effect is not repeated to make it pass.
The ordinary coordinator calls these services after its selecting Graph releases
the campaign lock. It supplies no second scheduler or editorial voting loop.

Every figure is allocated to a caption phase. The author packet contains the
exact complete native PNG/PDF source roster for that phase. PDF presentation
includes every page with source, renderer, raster and actual image-wire custody.
There is no 25-figure sample. Larger populations use prospectively reserved
caption batches; over-budget populations fail visibly rather than truncate.
JPEG/SVG originals need actual bound ordinary conversion to a native view, with
the original source retained. Conversion custody is not a pixel-equivalence
certificate. Missing vision capability, conversion or pages remain a hold.

Section/refinement calls retain the relevant consumed captions and source
records. Author images and responses are author evidence; they do not constitute
an independent reviewer vote. Terminal synthesis is a separate actual text call
over the complete consumed transcript and resolved records. Its receipt does not
claim that it viewed pixels presented to an earlier caption call.

## Resolve acquisition and material objections

A citation scout emits complete ordered acquisition tasks with
`obligation_id`, `query`, `source_scope`, `claim_ids` and `failure_or_missing`.
`source_scope` and `failure_or_missing` are nonempty strings. `prepare_literature`
requires the issued located-literature request to retain exactly those tasks,
then consumes the ordinary literature product. Failed/missing acquisitions,
extractions, contradictory sources and visual/OCR unknowns remain explicit.
The separate ordinary acquisition/extraction services own any authorized work;
declaring a task or URL never establishes that a paper was read.

`resolve_sources` binds a strict completed production request to every original
missing obligation. Existing records, task, context, runtime and formatting stay
current. Figure records use actual numerical plotting/source contracts; numerical
plots are not image-model inventions. Supplied templates remain exact sources.

`prepare_revision` consumes the actual current independent critic, verifier and
synthesizer assessment. Located material objections and unsubstantiated edges become
unresolved revision tasks; scores and prose do not resolve them. Changing a
method/evidence source invalidates its dependent captions, sections, native build
and compiled review. `prepare_supplementary` uses the ordinary fresh replication
producer and its explicit check contract. Preparation grants no execution or
scientific acceptance; fresh outputs and fresh reviews are still required.

## Assemble and verify delivery

The final synthesis slot requires strict source resolution and all preceding
actual phase products. `assemble(..., synthesis_binding=...)` reconsumes each
current phase receipt, the whole caption page/wire population and the distinct
actual synthesis call. It retains measured usage or nulls, every reservation,
all phase/source pins and the complete original slot denominator. It materializes
through [manuscript_production.py](../../src/ravel/workflow/manuscript_production.py);
it never forges a single-call receipt representing several calls.

Use the existing source-bound integrity roles and ordinary manuscript-build
preparation on that package, followed by fresh compiled visual/CI3 review and
`task_completion.require_final`. Failed fits, unscorable quantities, missing
proofs, acquisition failures and unsubstantiated claims remain in the delivered
record. A format-only edit must not renew scientific evidence or prior review.

The staged caption/section/reflection mechanism and the explicit
outline/figure/refinement plan run through RAVEL's existing charged services and current
source consumers.

Revision obligations retain the authenticated original writer campaign, current original task and quantity context, and its actual remaining one-time reservation. A fresh campaign, even with copied context, must not renew that allowance. The original campaign and source pins are rechecked at return; concurrent changes require preparation against the current original state. Preparing obligations grants neither execution nor scientific acceptance.

Each noninitial phase presents complete reauthenticated prior product records, including their original source, actual role receipts and accounting. The issued binding separately retains the exact ordered prior product pin roster. Preparation and consumption reconstruct the same full context; pins alone do not stand in for the presented product contents.

The Host presentation receipt records hashes recomputed from the exact input text sent alongside the role packet, as well as the inline packet content. Input declarations alone do not establish presentation. The current Graph still requires the exact phase subject and separately verifies every required native image page against the completed accounted provider call.


## Objections drive the next research and writer action

After `manuscript-revision` captures the complete actual critic, verifier and
synthesizer feedback, `manuscript-actions` consumes its pinned revision and an
ordered row for **every** objection: `objection_index`, `kind`, `response`,
`protocol_claim_ids`, `protocol_stage_ids`, and `required_experiment_ids`.
Kinds are `editorial`, `citation`, `empirical`, and `core-method`. The service
derives affected manuscript claims, methods, citations, figures and the complete
section population from the authenticated audit. These are proposed action
choices; a writer must not declare a material objection resolved.

Editorial and citation actions use a new complete writer request without a
numerical job. Scientific source and quantities stay fixed. Citation records
must retain actual located identity evidence; existing literature acquisition
and `manuscript-literature` supply it. A core-method action retains every
baseline, full-evaluation and ablation stage of the implicated candidate family.

`manuscript-action-meta` uses the existing charged protocol meta Graph. Its
context includes the whole original objection/action map and source inputs.
The observed role must name every mapped affected claim, stage and requested
test. Existing `research_protocol.apply_meta_review` invalidates scientific
dependencies; new stages, fresh ordinary observations and their current reviews
are still required. Existing `manuscript-supplementary`, replication design and
comparison services produce the full original/fresh studies. A changed-method
request does not reuse old baseline/ablation votes or only favorable cells.
The complete inline meta context refuses if it exceeds its admitted
capacity; it never samples objections or correlated cells.

Once the linked protocol holds have actual fresh replacement resolution,
`manuscript-successor` consumes the action plan and a pinned complete replacement
production request. It preserves the original task, author, venue, account policy
and cumulative revision allocation, checks current replacement method receipts,
and inserts a pinned response-lineage record in the ordinary source manifest.
The real improver Graph reads this evidence and creates the next full package.
Pure editorial/citation changes must not substitute a new quantitative result.

`manuscript-action-resolve` consumes that exact new package and its fresh actual
independent integrity review. A prepared writer, old review, failed observation,
response string or unknown outcome must not close an objection. The resolution
records all original objection indices and replacement lineage. It certifies
only the current scoped manuscript response; the real native build, compiled
CI3, scientific judgments and original whole-parent completion remain separate
required services. Failed/interrupted effects stay in their original Graph and
campaign history, within the original finite allocation.

The first preparation of a complete criticism records its original revision
allocation and charged starting usage in the same campaign journal. Copying an
action plan or preparing the same author and criticism again keeps that exact
allocation. It does not start a new allowance. A genuinely new independently
verified criticism has its own explicit allocation within the current original
campaign ceiling.

Direct protocol meta preparation, first Graph dispatch, and protocol application
use the same allocation checks. A prepared meta or successor writer Graph is
bound to that plan in the ordinary journal. An already charged exact Graph
resumes against its original full reservation without a second charge; failed
and unknown-started effects retain the existing recovery rules.

The successor compares actual bound method and operation definitions, including
code and source identities. An empirical action can add fresh observations from
the same method. A changed method requires an implicated core-method action and
its complete baseline, full-evaluation and ablation replacements, regardless of
the caller's label. Unmapped new methods are refused at this revision boundary.


## Preserve every declared claim through independent review

The consumed story assigns every ordered `claim_map` entry a section and phase
processing path. Terminal synthesis reconciles the full original roster. Each
nonstory response must fill the provider-facing `claim_dispositions` schema for
every claim allocated to that phase, even if drafting is empty. Use exactly one
of `retained`, `merged`, `qualified`, `withdrawn`, or `unresolved`; keep the entire
original row, including status, scope, evidence, counterevidence and every
indexed literal scope condition. A merge lists its complete ordered reciprocal group
on every original entry and maps them to the same actual targets.

`paragraph_ids` and `figure_ids` identify actual returned scientific paragraphs
or captions. Each indexed scope condition maps to those targets; the final prose or
caption must contain its exact literal text, the original scope and the stated
reason. `evidence_ids` and `counterevidence_ids` retain all original references
and map to actual target sources. A phase can explicitly retain missing source
IDs in `unresolved_evidence_ids`; final assembly requires actual resolved source
records. A label or acquisition task must not supply missing evidence. Caption-only
claims use actual source-bound captions instead of invented prose targets.

Write natural scientific prose inside the contracted results, scope conditions and
other permitted sections, or an allowed appendix/caption. Do not add a machine
census heading, internal claim IDs or an implementation log to the manuscript.
An unsubstantiated positive claim can be honestly withdrawn using its existing
negative evidence; no fictional successful experiment is needed. Changed
methods, empirical sources or results still need the existing original action,
protocol requalification, linked ordinary observations and fresh review.

Assembly emits a separate `planned-claim-census.json` audit artifact. It binds the
actual outline and phase receipts, original located sources and missing records,
current evidence, terminal dispositions, and exact final paragraph/caption text.
The integrity preparation observes the current real writer and complete
transcript, checks this census once, derives literal Unicode locations, and adds
one material `planned-claim` audit node per original claim. The ordinary critic,
verifier and synthesizer receive the complete typed original/disposition rows,
negative evidence, indexed scope conditions and final locations as authenticated
case anchors. They must judge qualifier preservation and evidential validity;
structural correspondence establishes neither scientific truth nor acceptance.
An unresolved node follows the existing objection/action pathway.

A direct improver of a package with this census inherits its complete original
roster even without a new staged run. It must not omit the declared fields by using
the direct writer API. The unplanned legacy one-call schema remains unchanged.
All existing figure/viewing, method/citation, accounting, native build, compiled
CI3 and whole original task gates remain required.
