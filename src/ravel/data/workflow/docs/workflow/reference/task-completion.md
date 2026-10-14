# Original task and scoped child delivery

Keep the full original request in `inputs/task_contract.json`. New routing retains a literal `original-request` obligation in `task_requirements`; finer source-located obligations describe experiment, model, domain, quantity, method, deliverable and quality. They supplement that whole request. They cannot replace it. Caller declarations and matching criteria do not prove scientific relevance or semantic completeness.

Decompose normally. Each assignment names its purpose and the original obligations it addresses, with its bounded criteria. A smaller study is useful even when it cannot finish the parent. In a version-2 scientific-study specification or AgentGraph, supply `goal_binding: {contract: {path, sha256, size}, assignment_id}` with an absolute parent-contract path. The ordinary input census, check-in, Host context, status and genuine reviewer manifest carry the original request, full obligation census, amendments and selected assignment. A missing source or changed binding must be repaired before that assignment is executed or reused; it does not show that the scientific question is impossible.

## Progress, evidence and completion

A completion request is a pinned JSON document with `schema_version: 1`, `contract`, `outcomes`, `parent_review` and `report`. Each outcome contains its declared `assignment_id`, child `rundir`, scoped `claim_scope` and the complete assignment `coverage` census. Each coverage row has `obligation_id`, exact assigned `criteria`, `state`, pinned `evidence` and an explanation. States are `satisfied`, `negative`, `partial`, `blocked` and `unknown`.

Partial or unavailable inputs remain visible and active. Source-negative evidence can satisfy a reviewed search-eligibility question: for example, an analysis outside the requested mass window need not produce an invented curve. Resolved and negative contributions require an actual current accepted child review that captured the exact parent contract, child study binding and evidence. A child whose assigned criteria are narrower than an original obligation does not close that obligation. Independent matching of complete criteria produces readiness for parent review, not final acceptance.

Use `ravel task-completion --request completion.json --base BASE` for the read-only census. The output distinguishes `ready_for_parent_review` and `parent_task_accepted`. These projections authorize no execution. Historical runs without explicit requirements remain unassessed for whole-task completion; their original scoped reviews are preserved.

A final whole-task decision uses the reserved `original_task_completion` claim scope in the existing review policy/journal, with checks appropriate to the task. The parent critic, verifier and decider must assess the original request and every open obligation. Exact custody does not replace their scientific judgment. Set `parent_review` to that actual review root/scope and bind a base scientific-report recipe in `report` before opening the parent cycle. The base recipe excludes `task_completion` and `delivery` to avoid a circular record. The parent cycle must snapshot the prospective completion request and all derived child/source/report dependencies; review holds or drift invalidate current acceptance.

For final delivery from that review root, retain the prospective record as `inputs/task_completion.json`, with source paths interpreted relative to the review root unless absolute. Then run:

```sh
ravel task-completion --request /absolute/review-root/inputs/task_completion.json --base /absolute/review-root --require-final
python -m ravel.validation.verify_pack /absolute/review-root --whole-task
ravel review --rundir /absolute/review-root gate --action final_task
```

When the original request supplied a numeric result template, fill it from the accepted result with `ravel fill-template`; see [result templates](result-templates.md).

The existing `delivery` gate and ordinary `verify_pack` still allow scoped progress. They do not label it as parent completion. `final_task` adds no bulk, reuse or new runtime authority. Reports using `task_completion` and `delivery: progress` show the literal original request, original/effective criteria and open contributions. `delivery: final` additionally requires the exact parent-reviewed recipe and whole-task decision. Changed facts, plots or recipe text require a fresh applicable review.

## Material scope changes

New routed contracts carry `task_requirements.completion_epoch: 1`. Their parent
lifecycle is evaluated through original obligation coverage and current child and
parent reviews. Retained contracts without that marker keep their previous route.
Research parents still owe the resource census and trap sweep. A partial or blocked
contribution can close a boundary only with a pinned `task-boundary` or `held-node`
record naming the obligation and reviewed scope, a reason and its pinned
`DEVIATIONS.md`. The delivered contribution retains its partial or blocked state.

### Compose registered children

Science and scoped planning register a `goal_binding` in the parent's
`inputs/children.jsonl` and show assigned parent obligations in the child CHECK-IN 1.
Other producers use `task_completion.register_child(child, binding, run_kind=...)`.
Registration creates the ledger directory after validating the parent contract and
child assignment. A contract in the parent's inputs directory identifies that
directory's parent as the run root; a supplied contract directly in the parent
directory identifies that directory as the run root. Repeated registration keeps
one ledger row for the same child and assignment.
The accepted kinds are science, scoped, route-a, research and calculation. A child
publishes `inputs/completion_outcome.json` in the existing outcome shape (legacy
`outputs/completion_outcome.json` is also read):
`assignment_id`, `rundir`, `claim_scope`, and a complete `coverage` census including
unresolved obligations. One assignment may have several distinct child scopes.

An optional `<rundir>/inputs/completion_sources.json` binds existing collector
denominators: `schema_version:1`, `resonance:{request:pin,runs:{stage:absolute_run}}`
and `research_cycles:[head_pin]`. Composition reuses `resonance_study.collect`
with no output destination and the current research-cycle ledger. Every discovered
ordinary run must bind the exact parent. These sources discover contributions;
their component status cannot substitute for complete coverage and accepted review.
Both source-ledger state and input population are checked again before return.

```bash
ravel task-completion compose --rundir PARENT
```

This writes `outputs/completion/composition.json`; `--no-write` only returns the
projection. It includes every child, accepted review anchors, deliverable pins,
coverage and uncovered obligations. Missing or refused children stay visible.
Every contributing review is rechecked, including the published-figure comparison
obligation. Composition does not approve execution or accept the whole parent.
CHECK-IN 3's `sections.ci3_list` must equal the current census of RDJ-authorized
choices and adopted adapter defaults, across the parent and registered children.

### Delivered claim records and disclosure

Before final parent review, write `inputs/claim_records.json` with `claims` and,
for a research protocol, `disclosure`. Each claim names `id`, a pinned `quantity`,
its current `execution_receipts`, `validator_receipts`, `n_trials` and pinned
`selection`. A child quantity also names its registered `rundir`. The selection
record contains `n_trials`, all `trials` (distinct id, candidate, select and confirm
values), `selected_candidate`, `selected_result_on_confirm`, `best_of_n_select`,
`rule` and `objective` (maximize or minimize). A deterministic single evaluation
still reports its trial count. A null funnel records no selected candidate or
confirmation; an empty search reports zero trials.

`completion_claims.validate_delivery(root, document)` computes the claim records.
The primary selection result is the selected candidate's confirmation. The
best-of-N select value is labelled `optimistic`; the confirm oracle gap is separate.
In `closed_scored`, the selected trial records distinct `seed` and `confirm_seed`.
Missing or inconsistent N fails `trials_unreported`. The research protocol owns the selection producer;
this consumer does not alter its protocol or choose a winner.

`evidence_status.derive` returns executed, checked (validator IDs), or validated
(reference pins and tolerances). It requires successful current supervised receipts
that bind the exact delivered quantity. The implemented validator records are
`finite-quantity` and `reference-comparison`; the latter recomputes a numerical
JSON-pointer comparison using explicit absolute and relative tolerances. Stored
PASS labels and caller-written evidence statuses grant no validation. Reference
agreement covers that reference and tolerance; it does not establish detector
fidelity, coverage or broader physics validity. A `certified` label requires a
fresh validated derivation at CHECK-IN 1, CHECK-IN 2 and final delivery.
The claim record's `fidelity` is derived from that status (`certified` only when
validated); the supplied text is kept as `declared_fidelity`. Free text naming a
certification, `validated` or `checked` above the derived status is refused.

`completion_disclosure.build(root)` computes the research candidate funnel from
protocol stage artifacts and the selection record, with the regime, dataset
manifest changes and human interventions. Record data transformations in
`<rundir>/research/dataset_manifest_deltas.json` (`deltas`: before/after pins, operation and
reason); record manual filtering or steering in
`<rundir>/research/human_interventions.json` (`interventions`: kind, action, reason), including
`human_manual`. The builder computes changed manifest fields and binds source pins.
The delivered deck or manuscript must include the exact computed block; omission
or editing of its funnel is refused. Procedure-note and result-pack producers use
the same delivery helper. The quantitative-report renderer inserts the computed
claim table and disclosure; final manuscript delivery requires that exact rendered
block in its current quantitative section. Source absence is recorded in the observation; adding a
previously absent intervention ledger during evaluation invalidates the result.

Aggregate delegation optionally adds `bounds.aggregate` with `max_seconds`,
`max_events` and `max_children`. Every authorized child reserves its full declared
ceiling against the original parent authority, including failed attempts; changing
the limits or exceeding them is refused. Reservations are ceilings, not measured
cost. Cost provenance binds the cost inputs and payload; it does not calibrate a
forecast. A trap's PASS discharge must bind its current artifact pin.

Ordinary decomposition and authorized repairs require no extra scope approval. To replace or withdraw a parent obligation, preserve its original row and add a pinned `task-scope-instruction` amendment with the literal instruction, original prompt hash and each exact preceding obligation hash. Such notes are proposals until the existing original task CHECK-IN1 envelope binds the amended contract and amendment bytes and its recorded quote matches the instructions. An agent-created file claiming `authority: direct-user-instruction` is insufficient. If authorization is absent, the original obligations stay effective while ordinary constructive work continues.

The software checks source custody and the existing approval envelope; it cannot authenticate a person's identity from a quote or an actor field. `authority_origin_authenticated: false` and `semantic_entailment_verified: false` remain explicit. Trusted direct-user provenance and a scientifically adequate whole-goal decision are review responsibilities, not benefits inferred from passing structural controls.

Every contributing accepted child and the parent review are observed within existing per-run `ValidationSession` objects lasting only for the completion projection. Their full live scientific source, journal, output and runtime custody is checked at the final return boundary, then every session is closed, including failures. The small completion dependency table does not duplicate the potentially large native scientific input inventory. A later call creates fresh sessions; no saved acceptance proof substitutes for current custody.


## Ordinary prospective whole-parent review context

Use science schema2 mode `task-completion-context` to prepare the current complete
parent evidence for its existing independent review journal. Its task is
`{schema_version:1, ready_request:pin3, final_request:pin3,
parent_review_root:absolute_path, completion_base:absolute_path}`. Both request pins are absolute. `completion_base` fixes the existing consumer base for all nested request/report source paths; it is not inferred from the future review root or worker specification directory. The ready
request has `parent_review:null`, its exact base report recipe and the complete
original outcomes/census. The final request must differ only by
`parent_review:{rundir:parent_review_root,claim_scope:original_task_completion}`.
It cannot change the goal, outcomes, report or source population. The root must
be distinct from every contributor child.

The study binds the actual full original `goal_binding`, permits exactly one
attempt and registers the original whole-parent review claim scope. Normal
plan/approval/run gates apply. The worker uses the explicit `completion_base` for nested inputs
and writes only its own `outputs/attempt-1/task-completion-context` destination.
It invokes the existing complete task consumer in a fresh ending-read session and
returns readiness with `parent_task_accepted:false`; this is source/readiness
evidence, not a numerical result or scientific certification.

Review the context and complete final-request inputs with the actual ordinary
critic, skeptical verifier and synthesis roles under the registered scope. Then
prepare the exact immutable draft artifacts for CI3 and consume public
`task_completion.require_final` on the same final request/report recipe. This
sequence avoids a circular parent acceptance requirement and prevents an earlier
child review from certifying a completion request written later. Missing or
changed evidence remains unresolved. The adapter is shared by manuscript and
ordinary research finalizers; it creates no acceptance journal or manual
whole-final pass receipt.
