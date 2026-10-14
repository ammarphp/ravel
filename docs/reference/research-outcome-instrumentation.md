# Research outcome instrumentation

`research_cycle.outcome_metrics(cycle, completion_request=None,
utility_declaration=None)` reads the existing cycle, original parent assignment,
Graph call receipts and ordinary science attempt records. It makes no calls to a
model, provider, scientific worker or review role. There is no new state store,
metric acceptance gate or scheduler.

The ordinary `research-cycle status` result includes this readout automatically.
`research-cycle synthesize` includes the same typed readout and appends an
instrumentation section to the existing quantity-bound report. The existing
128,000-byte report text limit is retained. Partial/failed campaigns can use status
or the read-only metrics command without claiming that they satisfy synthesis's
scientific prerequisites:

```sh
ravel research-cycle metrics --cycle /absolute/cycle
ravel research-cycle metrics --cycle /absolute/cycle --out /absolute/fresh-report
```

The latter returns the common `files` report descriptor for a typed JSON and its
Markdown companion. `--completion-request` and `--utility-declaration` are optional
paths to exact pinned input documents; neither grants execution permission.

## Outcomes and original scope

The original parent contract supplies every original obligation, its effective
criteria and any explicitly retained scope changes. Without a parent binding,
the original question is retained and the whole-task denominator stays unknown.
Never substitute the number of successful components for the original task.
An optional completion request uses the existing `task_completion.evaluate`
operation and must name the exact original contract. No new evaluator is added.

The complete experiment population contains every declared design and every
required but not yet designed identity. Records remain not-designed, unresolved,
failed, partial, or a recorded component result. A component's historical review
state/scope and current premise applicability are separate fields. A source/API
port, software control, refusal, role vote or author's improvement claim is not a
correct complete physics result. Even a genuine recorded whole-parent acceptance
is reported as `recorded_full_delivery`, with independent correctness unknown.
All scientific error/effectiveness counters remain null. These records cannot
calibrate autonomous benefit, erroneous acceptance, or erroneous refusal.

## Resource and intervention accounting

`resource_use.charged_ceiling` and the complete original reservation ledger are
declared ceilings, not actual calls, tokens or native time. The planned experiment
cost vectors remain explicitly prospective. Graph checkpoints contain the whole
debited call census. The engine debits a call and writes its initial `started`
receipt before invoking the Host function, so neither is evidence of provider
dispatch. `calls.observed_count` is retained for compatibility and explicitly
means resolved completed/failed outcome receipts. `complete_count` is null while
any call is started/ambiguous or any Graph is unobserved. Separate debited,
receipt, started, ambiguous, resolved, completed and failed counts retain the
entire denominator. Reusing one receipted outcome does not add another record.
Actual provider invocation count remains null: even a failed Host outcome can
occur before a provider call, and reconciled outcomes are retained attestations.

Model token usage comes only from receipt-reported `model_result.usage` values.
Ambiguous receipts keep any individually reported token/elapsed measurements as
scoped observations, but unresolved records leave complete totals null. Missing
tokens stay unknown even when an output token ceiling is recorded. Provider/Host
reports are not authenticated billing. Markdown labels debited records and
resolved outcomes explicitly; it never calls them actual provider calls.

Ordinary stage time comes from recorded UTC start/end times. Every old ordinary
science attempt under that study, including failed/interrupted attempts, is
retained; an attempt directory lacking its record is explicit and makes the total
unknown. Per-call duration and inclusive ordinary-stage duration are separately
reported. They are not added to each other or to campaign wall time. Native calls,
native seconds and actual/estimated monetary cost remain unknown because these
generic records do not observe them. A not-observed Graph keeps complete calls,
tokens and call-time totals unknown; observed subtotals and coverage counts remain
useful. No unknown measurement is converted to zero.

Approval observations preserve the exact quote and declared approval mode.
`scripted_yes` is machine assent. `physicist` is a declared mode with the original
`expert_review:false`, not proof that a physicist or person acted. Human/physicist
intervention counts remain unknown. Cycle events, Graph events/reworks and all
retained review/send-back/correction events stay available; repeated snapshots of
one review chain are deduplicated by origin and exact event content. No actor-name
prefix is trusted as human authentication.

## Explicit utility

No default scientific score or reward is supplied. An optional utility declaration
has these exact fields:

```json
{
  "schema_version": 1,
  "kind": "declared-research-utility",
  "original_contract": {"path": "/absolute/task_contract.json", "sha256": "<hash>", "size": 123},
  "declaration_source": "user_instruction",
  "statement": "The literal declared user/task utility goal.",
  "goals": [{"id": "full-task", "statement": "Deliver the complete original request.",
             "criteria": {"complete_original_request": true},
             "obligation_ids": ["original-request"]}]
}
```

`task_declaration` is the other supported declaration-source label. Goals must
refer to existing original obligations. The exact declaration is retained;
origin authentication is false, utility value null and benefit unmeasured.
Caller-declared criteria are neither calibrated rewards nor outcome evidence.

## Custody, budgets and qualification

Each numerical/resource record is parsed from the same bounded descriptor-backed
byte snapshot used for its hash. Complete call/attempt directory membership and
ending bytes are checked without rebasing. The existing research reader is
reused. The instrumentation limits are 16 MiB per document/readout, 64 MiB of
unique evidence, 512 files/receipt-directory entries and 128 attempts per study.
An exceeded bound refuses rather than clipping the denominator. Final serialized
JSON is also bounded. Report writers receive a detached serialization-derived
value, and durable output bytes plus ending source readout are checked.

`input_pins` describes the metrics records. Full cycle dependency authority remains
with `research_cycle._load`; these pins are not a replacement for complete native
runtime, output, source and scientific-review inventories. Pure source fixtures
test the integration and accounting, with synthetic Host returns/authority where
explicitly marked. They are not autonomous efficacy, physics correctness or a
historical result reclassification. Such future studies need prospectively fixed
task/utility definitions, independent truth assessment, complete populations,
actual intervention provenance and measured resource/cost instrumentation.
