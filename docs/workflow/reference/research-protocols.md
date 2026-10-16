# Staged scientific research protocols

Research parents now bind the [default nine-stage methodology](research-orchestration.md#required-research-stages).
That binding governs the campaign even when no detailed candidate/cell protocol has been
authored. The candidate/cell protocol below adds experiment-specific baselines, comparisons,
ablations and source dependencies. It cannot remove the default stage obligations.

The default definition and stage-role contracts live in `src/ravel/data/research/protocol-default.json`;
coordinator and meta-review text lives in `src/ravel/data/research/instructions.json`.
`research-protocol methodology-status` reports the required stage and missing artifacts.
`preregister`, `register-concerns`, `stage-prepare`, `stage-run` and `stage-complete` handle the
ordinary record and Graph handoffs. Meta-review also accepts `adapter: "external"` for
fresh host-agent delivery without an API key. The existing cumulative budget, approval and
scientific-review requirements remain in force.

A protocol connects candidate sources, reproduced baselines, screening, full evaluations, isolated component ablations, objection tests and fresh meta-review to the existing research cycle. Its stages carry explicit physics scope and uncertainty. No additional scheduler, call ledger or scientific review journal is created.

These APIs have connected source controls. They have not established agent effectiveness or native scientific accuracy. The complete implementation control uses the real Graph, Host, role-packet reader, supplied arithmetic comparator and ordinary unapproved planning. Returned scientific outcomes and acceptance are explicit synthetic seams. An actual study still needs ordinary CHECK-IN 1, supervised execution and the independent scientific review required by its policy.

## Declare the whole evaluation before affected planning

Create a normal `research_cycle` with the original question, parent goal, requested quantities, premises, cumulative budget and experiment ceiling. Ideas may be supplied or generated through the existing source-bound Graph path. Speculative generation is optional. A fixed correctness task need not invent a novelty competition or run every stage below.

Freeze a protocol JSON and bind its exact `{path, sha256, size}` pin using `research_protocol.bind(cycle, pin)`. Its closed top-level fields are:

| Field | Meaning |
|---|---|
| `schema_version`, `id`, `scope` | Version 1 and the complete declared scientific scope |
| `candidates` | Exact component/source pins, held inputs, parent generation, premise IDs and reason; optional explicit old-source requalification |
| `cells` | Population and normalization pins, regime, fidelity, metric/unit, premise IDs and actual exposure |
| `stages` | Baseline, screen, full, ablation or objection-test purpose; complete cell-to-experiment/output pointers; required stages/comparisons; review scope |
| `comparisons` | Two complete same-cell stages, one independent ordinary comparison experiment, prospective rule pin and exact review scope |
| `objectives` (optional) | Prospective typed conclusions with exact cell, candidate and comparison requirements; see [objective contracts](../../methodology/research-loop.md) |
| `claims` | Literal statement, acceptance-criteria pin, stage/comparison/premise dependencies and report slot |
| `required_stage_ids`, `required_comparison_ids` | Original evaluation denominator, retained when rows are appended |
| `round_limits` | Finite candidate-generation, ablation and meta-review bounds within the original cycle budget |
| `not_applicable` | Explicit reasons for phases absent from this task; cannot remove declared rows |
| `meta_actors` | Distinct declared critic and verifier identities |

Every row has a stable ID. Cell, stage, comparison and claim rows also have a nullable `replaces` field. Candidate rows use a nullable `requalifies` field when explicitly requalifying an older source generation. The source-complete schema and a validated working construction are in `tests/unit/test_research_protocol.py`; no public example embeds fabricated scientific acceptance.

Cell exposure is `adaptive_screen`, `adaptive_full` or `withheld_confirmation`. It is a supplied scientific declaration, not an inferred proof of blindness or independence. Evaluation engineered against a full benchmark is adaptive. A renamed file, fresh reviewer or repeated retained output does not create a new independent confirmation. Cohort, repeats, weights, pairing and scientific validity belong in the pinned population/normalization and ordinary study/review contracts.

Bind before affected planning. Amendments append rows while preserving every old row, scope, policy, threshold, original evaluation obligation and cost. A new threshold cannot retroactively make an old result pass. Candidate source changes become new generations. A component ablation must change exactly one declared component and preserve held scientific inputs; removal, replacement and addition are explicit. Source equality alone does not establish causal isolation, and component effects are not summed into a mechanism explanation.

Optional objectives express regional or uniform improvement, supplied cost and
accuracy trade-offs, or complementary candidate coverage. Claims can name exact
`objective_ids`; status reports their typed conclusions and retained scope.
Uniform improvement still requires every participating cell. Regional evidence
does not authorize extrapolation, and portfolio coverage does not authorize a
combined likelihood. Existing comparison, source, approval and scientific-review
obligations remain required. Objectives do not change selection ranking.

## Run the ordinary studies and comparisons

Materialize candidate studies with the existing `research_blueprint.materialize` or supply complete ordinary study files. Candidate source, invariant inputs, population and normalization must be real `science.task_inputs`, not decorative proposal citations. `research_cycle.design` validates protocol membership and this input closure. The original parent goal remains unchanged.

`research_cycle.select` filters stage eligibility before its existing experiment ranking. `prepare_experiment` uses that same current selection and calls `science.plan`; `run_experiment` rechecks protocol eligibility at the final dispatch boundary before the ordinary approved runner. Changed premises, missing baselines, unresolved screen comparisons or material objections therefore block dispatch even after a plan exists. Planning does not approve an experiment. Several declared cells may share one ordinary experiment; its attempt is charged once in the existing cycle ledger.

After ordinary results return, use `observe`, the normal scientific judgment/review flow and `adjudicate`. Merely reading a number, a supplied `good` boolean or two accepted operand studies does not establish the comparison. `research_protocol.prepare_comparison` creates a fresh normal `research-comparison` study and a cycle experiment. Its inputs contain both complete currently scoped operand results plus the actual candidate/cohort/normalization/rule dependencies. The comparison preparation inherits the cycle's exact original `goal_binding` and refuses a conflicting supplied binding. Original parent dependencies remain protected inputs to ordinary planning. Design, plan, approve, execute and review this comparison normally.

The ordinary comparison task is `{schema_version: 1, request: pin}`. The pinned request contains `schema_version`, `protocol_sha256`, `comparison_id`, `rule`, `cells` and `dependencies`. Here `protocol_sha256` is the digest of the exact comparison-basis projection: comparator, both stages, their candidate manifests and their cells. It is not the SHA256 of the complete append-only protocol file. This permits unrelated new rows without laundering an altered comparison.

Each cell has two source pins and literal JSON pointers for value, interval and quality. The fixed rule declares metric, unit, minimize/maximize, minimum gain, tolerance, `deterministic` or `supplied_intervals` uncertainty, and `all_cells` reduction. Quality must be literal `true` or `"passed"`. Missing measurements, missing intervals or unresolved validity stay unknown. Bool values are not numeric metrics. Values/intervals must be finite, with the value inside its supplied interval.

For a lower-is-better rule the gain interval is `[right.low-left.high, right.high-left.low]`; the converse applies when higher is better. A cell is better only above the prospective gain threshold, worse only below the negative tolerance, equivalent only inside the tolerance, otherwise unknown. A matrix is better/worse only when every cell supports that direction or equivalence. Mixed tradeoffs stay unknown. No generic averaging, unit conversion, covariance, standard error, interval coverage or independence is inferred. Heterogeneous objectives require a separately qualified domain comparison; this scalar/interval operation does not silently substitute for it. Adapter `status: passed` means arithmetic was delivered, including a worse or unknown result. It is not scientific acceptance.

## Critique, revise, verify and reopen

The ordinary `scientific_judgment` remains responsible for Check-In 2, grounded criticism, nonvoting improvements, skeptical verification, correction and result closure. Its attached Graphs use the cycle's existing prepared-Graph charge route; role failures and redos retain cost. `research_followup` supplies complete actual role feedback and source-bound revised designs. Neither module is replaced by the protocol.

For a methodological meta-review, `prepare_meta_review` freezes the complete protocol/status, original goal, hypotheses, premises, retained failures, actual feedback prose and complete ordinary experimental input inventory. It copies authenticated content for every captured ordinary input, in addition to protocol/result/review dependencies, into a fresh normal role packet. Duplicate canonical paths are merged only when their exact hash/size commitments agree. Fresh critic/verifier Graphs receive that packet through the existing blind-role reader, without extra raw Graph inputs or the other current meta-response. Execute through `research_cycle.execute_graph`, retaining the same cumulative charge and campaign clock. `apply_meta_review` requires the exact current subject, all required source-content hashes actually presented in the role receipt, and a separately observed role receipt. An already consumed exact Graph/node result refuses without a second event, charge or round; a new round needs a fresh charged result. Control-only receipts are refused by the public CLI; the library's explicit test-only option is retained as `control_only` and carries no scientific authority.

The typed actions are:

- `report_only`: retain numeric evidence and record a located presentation correction request. Actual rendering uses `scientific_report`, with the original report preserved.
- `additional_evidence`: hold the affected claim while preserving independently supported raw incumbent facts; name explicit fresh ordinary test obligations.
- `candidate_revision`: invalidate the located affected stage and dependent comparison/promotion evidence, then require a fresh source generation and re-evaluation.
- `premise_revision`: request a located revision through `research_cycle.revise_premise`; explicit cross-candidate cell/source/claim dependencies also reopen.
- `resolve_objections`: bind fresh current evidence for every open objection and exact replacement rows. The same prior output/review commitments cannot close a fresh evidence request.

A nonwinning refinement may leave an unaffected valid incumbent available. A scientifically invalid incumbent cannot regain validity because its repair failed. Replacement rows must retain exact original claim statement, criteria, population, units, scope and complete stage/comparison obligations. A shared report slot is presentation linkage, not semantic discharge. Criteria changes need the existing explicit parent-goal amendment route. A successful replacement can fulfill the old reporting obligation; the old invalid evidence itself remains stale forever.

## Ordinary APIs and CLI

The library entry points are `bind`, `eligibility`, `admit_design`, `status`, `prepare_comparison`, `context`, `input_pins`, `prepare_meta_review`, `apply_meta_review`, `prepare_host_request` and `host_prepare`. `validate` accepts an explicit cycle state and base directory. The ordinary arithmetic adapter exposes `validate`, `inputs`, `calculate` and `run`.

The focused CLI is `ravel research-protocol`. It supports `bind`, `status`, `context`, `comparison`, `host-prepare`, `meta-prepare` and `meta`. Use `--cycle` for the existing cycle. Mutating/preparation commands take `--request` as one bounded descriptor-backed invocation snapshot. Nested protocol/source/context pins still require their expected digests. `context` takes a fresh `--out` file. The command never launches a provider or scientific worker on its own.

Examples of closed command documents:

```json
{"protocol_pin": {"path": "protocol.json", "sha256": "<actual hash>", "size": 1234}}
```

```json
{"output_dir": "fresh-meta", "role": "verifier", "model": "<admitted model>", "reasoning_effort": "high", "max_output_tokens": 4096, "max_wall_seconds": 120}
```

`host-prepare` takes `{operation, parameters, graph_root, output_dir}`. Supported deterministic Host operations are `status`, `context` and `comparison`. The return includes the exact request/subject/current source pins for a normal designer tool node with action `research-protocol` and parameter `{request_input: <input ID>}`. The exact pre-reservation subject must still match; only that Graph's own reservation may have been added to the ledger. One ordinary tool call is charged. It cannot impersonate a blind review, bind state, cast votes or approve execution.

`meta` takes `{graph_root, node_id, context_pin}` and consumes an already charged fresh role result. It does not accept a public control-only override. The entire active schema, including a typed meta-response, is exercised in the portable test module.

## Reporting and finite limits

`research_cycle.status`, `feedback_packet` and `synthesize` carry the complete staged status. Every declared cell remains visible as unplanned, declared, planned, stale, operationally unresolved, scientifically unresolved, unreviewed or accepted-current. The view records every candidate generation, actual exposure, unresolved comparison, original requirement and exact replacement. `reviewed_local_contrasts` retains each full-stage comparison with its actual cells, rule and scope. Candidate-level `reviewed_dominance` requires current comparisons covering every full-stage/cell obligation of both candidates, under one exact compatible prospective rule and acceptance scope. Equivalent cells may complete coverage, but at least one contrast must favor the same candidate and none may oppose it or remain unknown. Missing regimes, mixed results, incompatible policies or unreviewed comparisons leave both choices unresolved; no favorable contrast is silently selected. Current undominated full candidates are options, not a new optimization algorithm. Protocol evidence completeness is a necessary additional condition for cycle completion. It does not accept the original parent goal or bypass its complete requested-quantity census and scientific review.

The implementation admits at most 8 candidates, 32 cells, 32 stages, 16 comparisons, 32 claims, 8 generations, 16 ablations and 8 meta-reviews. The unchanged cycle budget/experiment ceiling can be smaller. Source payload pins are at most 8 MiB each; the unique declared population is admitted before opening payloads and limited to 64 MiB per source-consumption call. A protocol presentation admits at most 8,192 input references and 128 unique canonical file commitments, applying the unique limit after deduplication; conflicting aliases refuse. The ordinary comparison operation retains its prior 256-reference/256-unique profile. Protocol JSON and complete meta content are limited to 2,000,000 bytes. Meta content must be UTF-8; oversized/binary contexts refuse rather than truncating. Normal Graph/Host limits still apply and can be smaller. This is a finite supported profile, not arbitrary native-run corpus support. Repeated proof-path reads, original runtime/approval validation, operation time and total I/O are not bounded or metered by these source-population limits.

Consumed bytes are authenticated from a bounded descriptor snapshot, with leaf and ancestor identity checked at the ending boundary. No across-call cache or hash-then-unverified reread is used. Ancestor ctime can conservatively refuse a concurrent sibling change; there is no automatic retry or authority extension. Failed preparation outputs remain available for diagnosis and are never recaptured as successful commitments.

Later effectiveness work must separately qualify the provider/runtime and scientific adapters, execute complete matched tasks and measure useful outputs, failures, repairs, false acceptances and costs. These source controls establish an implemented connected protocol, not measured scientific gain.


## Concurrent source and command reads

The ordinary command reader and supplied comparison-source reader consume one
bounded regular-file descriptor snapshot. They reuse the existing no-follow
component traversal, compare the full leaf identity before opening, on the
opened descriptor, after reading and at the ending current path, and parse only
the consumed buffer. Comparison inputs also require the supplied exact size and
SHA-256. Existing strict JSON and 2 MiB command / 8 MiB comparison bounds remain.

Ancestor observations compare device, inode and mode rather than directory entry
size or timestamps. Adding, removing or renaming an unrelated sibling therefore
does not invalidate the input. An observed changed ancestor inode or mode, a
symlink component, changed leaf identity or changed pinned bytes still refuses.

These are finite, time-local observations, not a pathname lock, stable generation
token or persistence guarantee. A directory rename/replacement restored between
observations, or a reused identity, need not be detected. The bytes actually
consumed remain subject to descriptor identity and, for pinned sources, exact
hash checks. Later launches, review or reuse must keep their existing fresh
checks; this snapshot creates no execution or scientific acceptance authority.

## Confirmation, register and mandatory protocols

Every research route binds the fixed P01–P17 producer/check rows in the default
protocol. Resume refuses a changed binding. There is no production protocol
switch; `validate_protocol_controls` checks config and CLI schema keys. Missing
producers are visible through `check:protocol_producers_present` and refuse claim
acceptance as `producer_pending:<protocol>`. These are record contracts; source
registration does not establish that a protocol ran.

`full` uses only `adaptive_full` cells. `confirm` uses withheld cells with data
`seeds` and `generation` distinct from every earlier input. These fields identify
the data generation, independently of candidate ancestry. Declare all cells and
source pins before planning. The same population digest cannot be renamed into
confirmation. Record the exact R1 screen action and receipt with
`research_protocol.authorize_screen` before preparing a screen experiment.

Freeze the metric, direction, k and alpha in preregistration `selection_rule`.
`commit_selection` derives N and the selected k from the complete observed
evaluation census. Failed and screen-only evaluations remain in N. Screen
measurements cannot compete as full-fidelity results. Repeated full measurements
use the fixed arithmetic mean, with candidates considered reported separately.
The ordinary dispatch seam records one confirmation read per selected candidate
per disjoint cell before execution; an interrupted attempt consumes the read. It returns
`confirm_read_before_selection`, `confirm_cell_in_selection_inputs` or
`confirm_reads_exceed_k` on violations. The shared ML/research study ledger
atomically prevents reuse across rundirs before the local dispatch event. The
default methodology carries `validate.selection.receipt` and
`validate.selection.confirmation_pins`. Stage preparation and adoption verify the
journaled selection-before-read order and match result identities to reserved
reads, including before accepting performance, mechanism or agreement claims.
Typed `reproduce` and `reinterpret` task modes and kinds bind the default research
protocol at ordinary intake and plan boundaries as well as child research cycles. An `agreement` claim also binds it
when no task mode is supplied. Plain agreement without selection/calibration uses its agreement ledger and noise
model; search/calibration retains the prospective confirmation boundary. Every experiment purpose other
than `confirm` refuses cells reserved as `withheld_confirmation`.

`selection_report` recomputes the selected results on fresh confirmation inputs
and applies Holm when k exceeds one. The best select value is labelled
"optimistic"; an oracle gap is computed only inside evaluation fixtures. Evaluators supply the p values; the protocol
does not construct a likelihood. Claims carry N and pinned selection receipt and
report. A null funnel is a valid delivery without a promoted performance claim.
Claim records consume these fields. `validate.stop` is computed from
observed select results, measured attempt costs and family coverage; its reasons
are `successes`, `max_rounds`, `budget` and `coverage_unmet`. A worker's completion assertion is
never a stop rule. `completion_disclosure` supplies per-worker and per-model-cell
missing-receipt counts to completion consumers.

Research hypotheses declare an operator, identity signature, kill condition and
typed reopening predicate. `research_cycle.replay_register` derives statuses from
`hypothesis`, `test`, and computed `transition` journal events. Every observation
retains a structured residual. Mismatch alone weakens a hypothesis; refutation
requires matching comparator and sensitivity receipts within the declared scope.
Failed execution is not exclusion. Budget parking has `scope_of_negative:
"budget_only"`. Reopening cites a satisfying receipt and a `what_is_new` that
differs from the retained signature. The hypothesis board consumes the register events; it cannot
write status. Shared input shapes are in `src/ravel/data/research/followup.schema.json`.

`check:seed_to_test` verifies both streams' dispatch receipts, exact prediction
commitments before exposure, operator tags, and result-derived screen/full yield.
The evaluator alone may call the `feedback_arm` transform hook. Family/operator
evaluations require the factorial census, an independent best-of-N arm and
a shared positive evaluation budget;
unqualified cells remain advisory.

`experiment_allocator.allocate` protects validation and confirmation reservations
before a bounded least-covered prediction-class reserve. Aliases share a class.
Every applicable queued work item carries `recommend(case)['input_digest']`;
`bind_allocation` checks the current hypothesis/action census and binds the queue
advice for eligibility. The queue consumer must adopt these work items. Allocation
is advice, not execution authority or calibrated physics.

Set `allocation_policy: expected_information` in the case (or use the allocator
CLI's `--policy expected_information`) to rank expected class mutual information
in bits per expected path cost. The default remains `guaranteed`. A
`predictive_model` PIN must resolve to schema 1 with `kind` equal to
`source_backed_predictive_model` or `calibrated_record`, the case's exact `scope`,
a `method` description, nonempty evidence `sources` PINs, and `distribution`.
Each joint row has `class_key` from `canonicalize(case)`, `outcomes` for every
action, and positive `probability`. The law must normalize, cover every distinct
class and respect categorical predictions. This supplies class priors and joint
outcome probabilities, including adaptive conditioning; no prior, independence
or agent-confidence probabilities are inferred. Reports retain `allocation_policy`,
`predictive_basis`, `selection_reason` and the computed objective. Evidence pins
authenticate supplied provenance; they do not certify calibration or physics.
The queue puts the chosen information policy's first action first, including
when information requires two joint outcomes. Entropy gains within arithmetic
roundoff of zero cause abstention.

Comparison output keeps `decision` for claims; search retention is derived in
staged status from the cells' gain intervals. Nonnegative lower bounds everywhere
and a lower bound above the rule's tolerance somewhere establish dominance; the
claim minimum gain plays no part. Staged status exposes
`search_frontier_candidate_ids` separately from reviewed claim preferences. Complete compatible full-stage comparisons are required to drop a
candidate; missing or overlapping objectives retain candidates. Frontier
membership never clears claim, promotion or confirmation gates.
`search_pending_candidate_ids` identifies incomplete full evaluations retained
for search; those candidates gain no incumbent-selection authority.

A comparison cell may name `paired_evaluation: {source: PIN, pointer: POINTER}`.
The pointed evaluation records `construction: same_events`, a `population` PIN,
`left` and `right` operand `{source: PIN, value_pointer: POINTER}` bindings,
`covariance_source`, `covariance_pointer`, `values_pointer`, two `indices`,
`interval_prescription: symmetric_covariance` and a positive `interval_multiplier`.
Matrix diagonals and cross covariance must be the actual paired estimator
coordinates, with central values equal to the operands; retained event-group
`output_covariance` matrices can be used directly. The symmetric difference
interval uses the supplied multiplier times the square root of
`Var(L) + Var(R) - 2 Cov(L,R)`. No coverage level is inferred.
The covariance fields may all be omitted when no covariance was retained.
An embedded joint evaluation may use `source: self` and `covariance_source: self`.
Ordinary staged preparation reads such records from the left result's
`paired_evaluations` object keyed by cell ID. Null or missing covariance falls
back to marginal intervals; absent pairing also keeps the marginal construction.
Malformed or mismatched pairing refuses the comparison. A cell using the paired
construction records `interval_construction: paired_covariance`; marginal cells keep
the original result schema. Output authenticates the population and covariance
sources through the ordinary input census.

Measured diagnosis actions carry `cost_class` (`none`, `calculation`, `stream` or
`generation`) and a `cost_measurement` PIN. The pinned stage record must carry the
same class and be a `supervised_pilot_observation`, `supervised_pilot_forecast`, or
a measured schema-3 `cost_preflight.py` record. Cost is the upper measured wall
bound in seconds, rounded up with a minimum of one allocation unit. The consumer
does not infer the operation class from elapsed time; a producer that omits it
needs an explicit class-bearing record before using this seam. Pass `base_dir`
for relative measurement pins. Legacy categorical declarations remain advisory.
The exact minimax ratio remains primary; equal-ratio, equal-cost actions prefer
earlier cost classes, and an unclassified action ranks after every class. `selection_order` lists informative feasible single-step
actions; `policy` retains the declared one- or two-step minimax recommendation.

An action with `exposure: withheld_confirmation` appears in `reserved_actions`
and never in the selection policy or exploration reserve. Allocation protects at
least the summed costs of these actions as confirmation capacity. The queue must
retain those actions and their recommendations; eligibility refuses their
dispatch before committed selection and enforces the selected candidate/read
limit. Ordinary research dispatch always reserves the shared ledger before
opening data; voluntary `reserve_confirmation` calls do not replace dispatch. This reservation grants no execution
authority or independent scientific confirmation.

`check:obligation_coverage` derives outputs from both plan and claims and reads
their pinned content; missing, empty, conflicting or malformed outputs refuse.
Zero is valid content. An anomaly or method study declares a precision target and
records `precision_size` in preregistration. Its independent-sample assumptions
and supplied variance bound remain explicit; sizing grants no compute approval.

## Execution enforcement and producer boundaries

Ordinary reproduce/reinterpret intake (CLI intake writer and `workflow_state init`), plan approval and
science planning use `research_admission.admission`. Launch, review adoption,
delivery and reuse recheck the same bound record. Removing a binding refuses.
A reason string cannot exempt a mandatory stage. The applicability predicate
allows search stages to be absent only for a plain ordinary reproduction or
reinterpretation without a declared or observed search. Plain agreement claims
use `agreement_ledger` and `noise_model` pins and N; they do not invent selection
trials. A claim linked to a selection, metric or calibration must carry its
selection evidence even when labelled `finding`.

The P01–P17 entries are **record contracts**, not proof that all producers have
executed. `methodology-status` exposes `producer_contracts`; accepting any claim
or delivering a claim-bearing run refuses with `producer_pending:<protocol>` for
each absent producer/check. These refusals are not waivable with `not_applicable`.
Current missing-producer owners are:

| Protocol | Producer/check owner |
|---|---|
| P01 board, P02 sealed seeding | Research board (`check:board_replay`, `check:board_schema` and `check:board_sealed` are registered in `src/ravel/validation/check_research_board.py`) |
| P04 support closure/common-mode anchor | Evidence queue and knowledge support closure |
| P05 authority boundary | Authority broker |
| P06 rival contract | Root-cause analysis |
| P07 allocation queue | Evidence queue with the experiment allocator |
| P10 request fidelity | Decision gate and request-fidelity intake |
| P11 normalization ledger | Normalization-ledger producer/check package |
| P12 executable contrasts | Analysis-IR package |
| P13 event accounting | Event-accounting producer/check package |
| P15 delegated dispatch | Work-dispatch and RDJ packages |
| P17 critic basis | RDJ and role registry |

## Launch preregistration, resume migration and route applicability

Approving CHECK-IN 1 writes the run's research preregistration. The
`workflow_state approve`, delegated approval and science approval paths call
`research_launch.produce`. It derives every field in code from the approved plan
files: claims from the task obligations, comparators from the contract targets,
evaluator pins for the approved statistic and detector route, stage and protocol
applicability, the declared seed and selection policy, and the plan digest.
Evaluator sources are copied into the run's research/evaluators directory and pinned. A model or
host never writes this record. `ravel research-preregister --rundir RUN` produces
the same record for a run whose plan is approved, and `--check` verifies it.

Launch admission re-derives the record and refuses a missing record, a record from
another producer or any field that differs from the current approved plan. A new
approval of a changed plan supersedes the record and names the record it replaces,
with `superseded_after_execution` set when execution records or a CHECK-IN 2 record
already exist. The new record is written before the protocol pin moves to it, and the
history entry and the new pin are one atomic write. Earlier attempts keep the record
they ran with. Once a research stage has completed under a record, it cannot be
replaced.

A first record written when execution records already exist is `post_hoc` and pins
those records. Launch verifies `supersedes`, `superseded_after_execution` and
`post_hoc` against the protocol history and the custody ledger
(`$RAVEL_STATE_DIR/research-protocol/<run digest>.jsonl`, an append-only hash chain
outside the run tree). `methodology-status` reports `claim_cap` and `prospective`.
A post-hoc record, a plan revised after results or capped prior results are
delivered as ordinary results with their label. They never admit a research
(search-route) launch or support a delivered research claim.

`ravel status --rundir RUN --write` binds the default protocol to an existing run
that predates it. The machine writes the run's migration receipt, research/migration.json, with the old and new
binding, the protocol epoch, the time and its machine authority. The prior-results
label comes from the run's records: `pre_protocol_capped` past CHECK-IN 2,
`pre_protocol_executed` when execution records exist, otherwise
`none_before_checkin2`. The receipt pins those records. `methodology-status` reports
the label and refuses an edited receipt. Plan, approval and science-plan admission
bind an existing run only through this migration.

Binding publishes the protocol record, then the custody row, then `binding.json`.
The custody row records the origin (`intake` or `migration`) and the receipt digest,
so deleting the run's `migration` key or editing the binding's origin refuses. An
interrupted bind or migration leaves no `binding.json`; the next bind rolls the
partial records back and redoes the migration with its receipt. A run whose intake
binding has no custody row and already has results is labelled
`binding_origin_unverified`. A refused bind-on-resume is a blocker in the status and
science packets, never a traceback.

`research_protocol.route_applicability` is the code-owned table. A plain
reproduction or reinterpretation without declared or observed search, calibration
or selection marks `ideas`, `screen`, `validate` and `critique_to_experiments`
`not_applicable` with a route-derived reason at preregistration. P01, P02, P07,
P08, P09 and P16 do not apply to it. Limitation census, baseline, acceptance,
meta-review, integrity and every other protocol apply. `producer_pending:<protocol>`
blocks delivery only for applicable protocols. `check:protocol_producers_present`
lists each missing producer with its `component` and the sorted
`missing_components`. A non-empty list is a release push blocker.

Search is declared by the contract's mode and route, the contract's or request
plan's `candidate_search`, `calibration` or `selection`, or a plan claim of kind
`method_performance`. The plan's derived `label` is a compatibility label, not a
declaration.

An ordinary (non-campaign) run completes each applicable stage through the workflow
record that already produces it (`ORDINARY_STAGE_PRODUCERS`,
`research_protocol.ordinary_stage_evidence`). Nothing is written; every read
recomputes:

| Stage | Ordinary producer |
|---|---|
| limitation_census | the code-produced preregistration with its approved approximations |
| baseline | the accepted CHECK-IN 2 cycle's produced, reference and comparison records, with the count of corrections admitted before acceptance |
| acceptance | every reviewer accepted one claim scope that authorizes delivery |
| meta_review | the physics critic, skeptical verifier and physics decider review records |
| integrity | every integrity check and machine claim check of the accepted cycle passed |

A stage the route makes inapplicable is `stage_inapplicable` with its route reason.
A missing record blocks delivery with a message naming it. On a plain ordinary run
P06, P12 and P15 do not apply; P11 and P13 do not apply when `compute_plan` is
`none` or `dry`. P04, P10, P11, P13 and P17 are satisfied by the ordinary producers
`validation.claim_checks`, `workflow.decision_gate`, `validation.normalization_ledger`,
`validation.event_accounting` and `workflow.physics_review`. An ordinary reproduction
that passes CHECK-IN 1, launch and the CHECK-IN 2/3 review is deliverable.

Every research campaign binds the default protocol at creation, including when
`research_protocol_required` and `goal_binding` are omitted. Only the library
library caller (`research_cycle.create(..., evaluation_harness=True)`) creates
an unbound synthetic campaign, labelled `protocol_exemption`. A campaign's
preregistration is code-derived by `research_launch.produce_campaign` from its
journal contract and a pinned design record (selection and stop rules,
approximations, optional withheld cells and sizing). The `preregister` CLI operation
takes only `{"design": <pin>}`. Design admission re-derives the record. A supplied
preregistration is accepted only with `evaluation_harness=True`, is labelled so, and
never supports a delivered research claim.

A deterministic `confirmation_criterion` with k > 1 is refused unless the
confirmation measurement is declared exact (`exact: true`); otherwise Holm p values
apply.

`decision_errors` calls the real decision-gate aggregator through its
`research_choice` seam. A missing `ravel.workflow.decision_gate` module produces
`decision_gate_unavailable`, including at stage preparation and selection commit;
it cannot approve an action or crash via an unhandled import. The optional real
module integration test remains skipped until that package is installed.

For the default path, each prospective experiment carries `evaluation` with
`candidate`, `family`, positive `round`, `purpose`, `cells`, `seeds`, `generation`,
`population_pins`, `value_pointer` (or `value_pointers`), and optional
`p_value_pointer` / `decision_pointer`. Pointers read the ordinary result; multiple
value pointers have the fixed arithmetic-mean reduction. The staged path derives
the same declaration from its pinned cell assignments. Population pins must be
ordinary study inputs. `observe()` writes `research_evaluation_observed` using
the actual result and attempt pins; execution cost comes from the attempt's
measured wall time. Failed/unresolved attempts remain in the census.

`commit_selection` accepts only the complete observed census and its exact result
pins (attempt pins for failures without a result). It writes
`<rundir>/research/selection.json`. N counts evaluated attempts; `candidates_considered`
counts distinct candidates. Repeated full evaluations use their arithmetic mean;
a failed full attempt leaves the candidate unresolved. Hand-written scores or
omitted evaluations cannot be adopted. `produce_selection_report(root)` writes
fresh confirmation values and p-values from observed outputs, checks their shared
ledger reservations and preserves null funnels. The arithmetic-only helper APIs
are useful for fixtures; their output alone grants no adoption authority.

The research binding is an immutable input of the approved ordinary science plan;
deleting its marker refuses ordinary execution. Before every declared research
dispatch, the executor reserves exposure in the
same `ml-exposure` namespace and under the same lock used by ML `Study`. It checks
baseline, screening and diagnostic reads as well as selection. Canonical NPZ
identities reuse the ML decoder (events, groups and normalized values); JSON
cohorts use decoded IDs/content. File renaming, seed string/integer aliases,
a different campaign directory and concurrent reservations cannot reset a read.
`RAVEL_STATE_DIR` migration requires the existing ML namespace policy; the
explicit `RAVEL_ML_TEST_NAMESPACE` is for isolated software fixtures only.
A supplied exposure declaration does not establish physical independence of
otherwise undocumented data transformations.

Confirmation can be performed once per selected candidate per disjoint cell.
Inferential confirmations use observed p-values and Holm correction across the
reported family. A preregistered `confirmation_criterion: {op: ge|le|eq, value}`
supports deterministic scored confirmation without inventing a p-value.
`void_confirmation(root, experiment_id)` records at most one recovery per
candidate, only after a terminal failed/interrupted receipt with no result file.
The old population remains spent. A replacement needs fresh cells, seeds,
generation and populations; the journal preserves the failed attempt.

Stops are computed from observed outcomes and measured attempt costs, then
checked before further dispatch. `validation_trace(root)` projects the ordered
observations and the computed stop. Crossing a stop requires
`authorize_stop_continuation(root, stop_rule, decision)` with an R2 decision over
the exact stop digest and new finite bounds, plus the real decision gate. A cap
with unmet family coverage is `coverage_unmet`, a deliverable null outcome with
uncovered families. The current stop schema retains the scalar wall-time budget;
the broader v2 multidimensional budget contract remains separate integration work.

Register transitions normalize `success` and the live `succeeded` through one
enum. Refutation still needs scoped comparator and sensitivity evidence. Identity
signatures normalize whitespace/case and declared `what_is_new` changes must be
applied. New exclusion/reopening events snapshot their receipt bytes for stable
replay. Production idea operators are `limitation_fix`, `ablation_refinement` and
`provocation`; the two additional operators remain evaluation-wrapper only.

Remaining producer work includes graph-authenticated P08 seed dispatch, the full
P09 manipulation/held-input/power/statistic signature and numerical kill-condition
schema, and full diagnostic operation ordering beyond enforcing the allocator's next
recommended action. These are not established by the synthetic software tests.

## Research board transitions, seasons and projections

Register transitions are code-written from `hypothesis_board.TRANSITION_RULES`. A
rule fixes its edge and its evidence. Comparator rules (`comparator_matches`,
`comparator_differs`, `scoped_exclusion`, `comparator_unknown`, `execution_failed`)
need a successful `registered_validator` broker receipt whose outputs hold a
`prediction-comparison` record naming the hypothesis's register id; a scoped
exclusion also needs a passed `sensitivity-check`. `budget_exhausted` needs an
exhausted budget receipt, `reopening` a receipt that satisfies the declared
predicate, and the RDJ rules an RDJ authorization of exactly that transition. Code
reads the evidence; the entry retains its snapshots and the observation, and a
custody replay re-reads them. A hypothesis may carry a `register` declaration
(identity signature, kill condition, reopening trigger, operator, `what_is_new`).
`research_board.cycle_events` emits the declared hypotheses and each comparator or
budget transition as research-cycle `hypothesis`, `test` and `transition` events;
`research_cycle.replay_register` recomputes the same state. `import_board` carries
the declaration into the cycle.

On a version 2 season, commits and reveals are written only by
`research_board.reveal_season`, authenticated by the digest of the season's frozen
record. Appends need the participant's `board append` broker call
(`research_board.append_action`). The board CLI refuses `commit`, `reveal` and
`append` on version 2 seasons. `reveal_season` checks the reveal barrier itself. The
season open time is stamped by code, and a `no_commit` exclusion needs the
participant's own observation after the timeout.

`sealing` accepts a worker receipt only when its ledger node and attempt are the
participant's broker binding and its session is the participant's session. The
reveal record keeps the receipt pins, and a meeting's season binding recomputes the
sealing label from them. A record beyond the journal head rolls forward only on a
custody open; an unverifiable one is moved to `quarantine/` and never applied.

The `full` projection keeps no actor, session or submission identity. A
spec-denied card that forbids `board_prose` reads the structural critic projection
with every free-text value removed. Critic refs are keyed by the journal head, and
lineage pins keep digests only. The blind-bundle guard compares normalized text
(Unicode compatibility, case, JSON escaping, whitespace and dash variants) on
three-word shingles, catches quoted short values, and walks every hypothesis and
post field.
