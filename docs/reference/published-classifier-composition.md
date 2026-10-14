# Published classifier composition

Use ordinary science mode `published-classifier` to connect a published model's
source-defined scalar features to weighted categories, or to retain the original
native C++ classifier route. This does not train a model, reconstruct missing
objects, interpret an undocumented feature, or certify detector applicability.

The public task is:

```json
{"schema_version":1,"input":"inputs/classifier-composition.json","input_sha256":"<exact file SHA256>"}
```

Include it in a version-2 science specification with the original parent goal,
source, numbered assumptions, actor/review policy, maximum wall time and prospective
attempt limit. Use the existing public lifecycle:

```python
from ravel.workflow import science
science.plan(rundir, specification_file)
# Actual CHECK-IN 1 approval is a separate ordinary step.
science.run(rundir, resume=False)
```

The CLI is `ravel plan --spec <spec.json> --rundir <new-run>`, then the
ordinary `ravel approve` and `ravel run` after genuine approval.
Use their `--help` options for arguments. No previous source/build/scientific
vote authorizes a new classifier study. A prepared native build remains a separate
`mode=analyze`, `backend=routine-build` study; its resulting unchanged build receipt
and plan are subsequently consumed by `native_task` below. This composition does
not rebuild a plugin silently or schedule another study.

All relative artifact paths resolve against the science `base_dir`. Pins have
`path`, `sha256`, optionally an exact integer `size`. JSON rejects duplicate fields,
nonfinite numbers and unknown top-level fields. The input and every source/model
pin are authenticated on consumption and rechecked before successful return.

## Supplied ONNX rows

The composition document has exactly:

- `kind`: `published-classifier-composition/v1`;
- `route`: `supplied-onnx`;
- `models`: the complete ordered model declarations;
- `events`: an exact pin to the event/feature document;
- `score_bins`: all requested source category predicates;
- `quantities`: the existing weighted-quantities/v1 contract;
- `source_semantics`: a substantive supplied interpretation and applicability boundary.

Each model has exactly `id`, `contract`, `feature_units`, `score_unit`, `score_range`,
`eligibility`, and `controls`. `contract` is the existing
`source-classifier-feature-contract/v2`, with unchanged original model bytes,
complete static tensor census and literal source excerpts. Features retain their
source order, expression, `identity|log10|normalize|jet_log10_or_default` operation,
`float32|float64` cast and `binary32_each|binary64_then_cast` arithmetic. An explicit
source default may occur only through the existing declared jet operation; an
absent feature does not become a zero. `feature_units` maps every feature ID to its
supplied original scalar unit. No conversion is inferred. `score_unit` and the
finite ordered `score_range` are supplied declarations.

`eligibility` contains `source_expression` and the integer `source_excerpt` index
for the original selection. Reference controls contain `id`, complete raw
`values`, complete `expected_outputs`, and fixed nonnegative `atol`, `rtol`.
Controls are supplied reference checks, not an independent oracle or calibration.
The reference and event tensors both pass through the same source arithmetic and
shared checked ONNX executor. Every model output component, including unused
components, is retained and checked for finite values and exact shape.

The event document has exactly `kind=published-classifier-events/v1`, `event_ids`,
`weight_names`, `feature_units`, and `events`. Each row has:

```json
{
  "event_id":"original-event-id", "event_number":19,
  "group_id":"original-independent-group", "shard_id":"original-shard",
  "weights":{"nominal":1.0,"variation":-0.2},
  "source_selected":{"published-model":true},
  "eligible":{"published-model":true},
  "features":{"published-model":{"source_feature_a":1.0,"source_feature_b":2.0}}
}
```

`event_ids` is the whole original ordered supplied population, with no missing or
duplicate rows. Each row retains every named weight, including zero and negative
weights. A correlated group cannot cross independent shards. Every model must
appear in `source_selected`, `eligible`, and `features`. Ineligible features are
explicit `null`; an event remains in the exposure with empty fills.

Source routing supports a fixed supplied model, no additional routing, or the
existing literal signed-C++ event-number modulo-2 even/odd declaration. For that
last route, `eligible` must equal the declared source selection AND the exact
native parity branch. Negative C++ remainders preserve the released `otherwise`
branch; Python's positive modulo convention is not substituted. Other routing
requires the original native route. The initial source selection is supplied,
not proven by this scalar adapter.

The existing source output operations are `scalar_index`, `difference` and
`strict_score_threshold`. The latter retains its original strict threshold result
as a separate field. Each score bin has `id`, `model`, `conditions`,
`source_expression`, and `source_excerpt`; one or two conditions use explicit
`>`, `>=`, `<`, `<=` and a finite `value`. Overlapping categories deliberately
produce correlated fills. No bin edge, selection or normalization is invented.

The quantity contract must use a single `source_category` axis of unit `1`, the
ordered bin IDs with ordinal intervals `[i,i+1)`, and integrated representation.
The emitted category coordinate is `i+0.5`. The original score predicates remain
in the delivery, so this ordinal axis is not mistaken for physical score binning.
Every input event yields exactly one quantity record. The existing quantity
engine retains full cross-category, cross-model and cross-weight independent-group
second moments. With `normalization.scope=all_events`, vetoed events still enter
the shared denominator. Negative/zero normalized denominators remain unresolved
and refuse finalization. Weight variations are not automatically a systematic
uncertainty envelope. These quantities use the supplied row weights uniformly
across its matched categories; source-specific per-fill weighting or native
finalization belongs in the original C++ route, not an inferred scalar rewrite.

The shared loader retains the existing full ONNX checker, nested external-data
and custom-domain refusals, complete input metadata checks and one-thread CPU
provider. Inference uses one source event per call, including reference controls,
so fixed batch-one and symbolic/unknown batch-one declarations remain explicit.
No optional ONNX module loads during task admission. External payloads, local
function/training graphs, multiple input/output tensors and unlowered source
features are not admitted here. Use the native route where appropriate.

Finite limits: 8 models, 4096 events, 256 controls/model, 512 features/output
components, 16 weights, 32 categories, 256 additive-moment dimensions, 200000
stored feature/output tensor cells. Each supplied document/resource is bounded to
8 MiB; the inherited model census also applies its 4 MiB model bound. The ordinary
study controls execution wall/resources. This is not a bound on all optional
runtime allocations or a performance certification. Oversized whole tasks must
use a supported complete route, not silently discard events/categories.

## Original native Rivet ONNX/TMVA

The native composition document has exactly `kind`, `route=native-rivet`,
`native_task`, `source_bindings`, `native_output_paths`,
`native_per_event_scores=not_published_by_this_handoff`, and `source_semantics`.

`native_task` is an unchanged existing `rivet-built` task with its current build
receipt, plan, original supplied events/metadata, runtime identity, options,
smearing seed, complete requested observables and `native_weight_cap=0`. Each
source binding has `role=source|model|preprocessing|configuration`,
`provider=ONNX|TMVA`, a `pin`, and `source_expression`. At least the full compile
source and real model assets are required. Every binding must already be a member
of the exact admitted native build/input closure. Bind all required original
assets and retain their normal capsule roles. Provider labels/excerpts remain
traceable declarations requiring review, not proof of the model's scientific use.
`native_output_paths` must equal the complete ordered requested native paths.

The worker delegates to `existing_events.run_in_worker` with the original task
and ordinary worker start clock. Original booking, selection, preprocessing,
feature order, model choice, native inference, finalization and normalization stay
in the preserved C++ source. Existing output files are retained unchanged under
`published-classifier/native`; their full file census, hashes and ending identities
are checked. Native output limits are 4096 files, 64 MiB/member, 512 MiB total.
Original optional historical/helper lineage stays registered through its existing
helper API at the actual delegated path. No new TMVA Python provider is implemented.

The exact native result is embedded unchanged. This wrapper does not invent
per-event scores or convert marginal YODA errors into a full bin covariance.
Actual native inference-call counts remain unavailable unless the original source
observes them; a completed native event route is not automatic inference parity,
calibration, detector validation or physics acceptance. Where full joint moments
are required, supply the existing source-qualified group/fill observer contracts
and their fresh scientific qualification rather than replacing missing information
with independent-bin errors.

## Delivered artifacts and later acceptance

`published-classifier.json` retains every event, feature/tensor output, source
score operation, category matches, references, group moments and input identities
for supplied rows; or the unchanged native result/output commitments. Failed
reference checks produce `status=failed` with the full returned population retained.
The ordinary worker emits its normal `result.json`, integrity verification and
CHECK-IN 2, then existing independent critique/verifier/decider reviews apply.
Successful source/API controls do not complete the parent analysis task.

Later native qualification must bind the exact original paper/source/assets,
object/feature and eligibility census, source casts/libm/ORT versions, every model
component and category boundary, original named weights/groups, source fill and
finalization law, and complete output population. Use withheld reference events
and independently checked expected tensors/scores/quantities. Preserve all failed
attempts. No training, real provider execution or physics validation accompanies
this source package.
