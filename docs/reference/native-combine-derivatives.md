# Native Combine fixed-point derivatives

The existing `native-likelihood` scientific-study adapter accepts a closed
schema3 configuration for selected-axis fixed-point diagnostics. It builds the
supplied full datacard/assets with the existing `text2workspace` command, creates
one NLL with the existing ModelConfig PDF and observed data, and sends raw native
values to the shared finite-difference kernel. It performs no fit. Schema1 limit/
grid and schema2 saved-fit operations retain their existing command paths.

Use the existing source/model/runtime/configuration fields and `max_seconds`.
Schema3 additionally requires:

```json
"derivatives": {
  "anchor": {"r": 1.0},
  "axes": [{"name": "r", "step": 0.25}],
  "max_points": 32
}
```

The existing `fit` block supplies the POI, physical domain, mass and seed. For
schema3 it must declare `method: MultiDimFit`, `data: observed`, `points: null`,
`minimizer: null`, `reference_quantiles: null`, and `fixed_witness_points: []`.
Those fields do not request an optimization: the command plan explicitly records
`fit: null`, and the result reports zero fit calls. No optimizer, derivative
formula for an invented yield model, Gaussian constraint or covariance is added.

Ordinary `science plan/approve/run` admission owns the source recipe, complete
model/assets, runtime, consumer/worker/kernel bytes, selection and point budget.
The native workspace's actual complete ordered real/category state is discovered
inside that admitted recipe. The resulting exact stencil is retained; it is not
claimed to have been observed prospectively. POI planning bounds intersect the
native range and declared POI domain. Nuisances retain their observed native
ranges. Infinite native bounds are recorded as explicitly unbounded (`null`),
while all assignments, weights and NLL values must remain finite. Every axis and
anchor override must be a floating continuous native POI/nuisance; observables,
globals, fixed/unrelated coordinates and discrete categories must not become axes.

The consumer receives the SAME NLL constructed by the original worker's
`createNLL(data_obs, RooLinkedList)` call with `Constrain(nuisances)` and
`GlobalObservables(globals)`. Other ROOT/custom-PDF options retain their pinned
native defaults. This branch requires empty conditional-observable and external-constraint sets, preserving the existing fit NLL.
The result binds the native workspace blob, complete observed dataset rows,
weights/covariates and typed dataset-attached auxiliary snapshots, all ModelConfig sets, PDF component names/classes and actual
native coordinate order. Category labels/indices use `getOrdinal`, preserving
sparse indices. These are actual recorded states, not a declaration that a source
file has a particular ordering or an exhaustive internal-table/loaded-ABI proof.

All workspace values, constant flags and category states reset before each
point and on success or exception. Observable values/categories can change during
dataset evaluation; global/POI/nuisance/unrelated values, bounds and flags must not.
The attached dataset global snapshot is kept distinct from workspace globals:
null, an empty set, and an missing accessor are separate states. Complete real
values/classes/constant flags/bounds and category values/domains are retained.
Their initial, pre-call, post-call and final states must agree. A change fails
without replacing the observation or forcing a new NLL global-source option.

The new branch admits exact source-reviewed ROOT 6.22/00, 6.24/00 and 6.30/00
policies. The old source has no attached dataset snapshot API or ModelConfig
external-constraint getter; this absence is recorded and admitted only under that
exact source/runtime version. ROOT 6.30 uses the dataset global values by default,
with model fallback; without an explicit ModelConfig global set it can derive the
global set from the data. This default selection is recorded with each selected
coordinate. ROOT6.30 requires its actual external-constraint getter; older reviewed source
has none. The PDF DefaultGlobalObservablesTag is observed separately. When no
explicit ModelConfig global set is supplied, this tag can take precedence over
the dataset automatic set; admission requires an explicit ModelConfig global option for that case, before any NLL value call. Actual option truthiness is retained separately from member count, including
a truthy empty set. With an explicit ModelConfig global option, ROOT
uses that existing option and the tag is retained but does not select globals.
No tag or model observation is silently cleared/replaced. Unknown versions or an accessor contradicting its source policy
refuse during ordinary admission/execution. Custom-PDF compliance with the pinned
ROOT semantics remains an empirical qualification requirement.

All raw assigned and post-NLL states are retained on successful delivery. Native
exceptions/nonfinite returns fail the attempt; the ordinary failure path retains
native logs and artifacts, with no manufactured derivative result or automatic
retry. The existing worker opens an exclusive `ravel_derivative_points.jsonl`
(64MiB/1040-event cap) before evaluating any point. Source-bound, chained records
retain the initial state and plan, a running point before the call, its literal
binary64 return immediately before dependent checks, then checked/failure/reset
status and distinct attempted/returned call counts. Nonfinite returns are typed
hex tokens with a null numeric value; they remain failures. Each event is flushed
and fsynced before acknowledgment; a recorder failure permits no subsequent call.
The ordinary failure path retains partial JSONL as failed evidence. Pure callers without a durable recorder receive partial events and actual attempted/returned counts on the exception; those memory facts are explicitly not a successful or durable scientific delivery. A successful
host delivery must reconcile that durable file and every journal event with the
complete declared rows and reduction. No second supervisor or process is added. A failed reset remains a failure. Native evaluator bias/error logging
beyond the retained raw logs still needs empirical qualification.

The host replays the deterministic plan and exact-rational reduction from returned
binary64 NLL values. It cross-checks actual ModelConfig and data denominators,
complete assignments, recorded resets, final restoration, source/staged/runtime
identities and all output fields. This authenticates neither a remote runtime nor
an independent likelihood law by itself; ordinary execution and role review are
still required. NLL differences retain the NLL convention, with no factor of two.

The plan and estimates expose `effective_refinement.axes`: actual coarse/fine
nodes and modes, exact rational radii/spans, repeated grids, contraction and
boundary use. Requested h/2 can round to precisely the same nodes. Even changed,
contracted grids do not prove accuracy. Nominal uniform-grid three-node first
errors are O(h²); one-sided second errors are O(h), while central second errors
are O(h²), under sufficient smoothness. Rounding asymmetry, changed boundary modes,
kinks and unknown native evaluator error invalidate automatic order assumptions.
An affine native bias can be invisible to h/h2 agreement. All estimates retain
`profiler_derivative_qualified: false`, `evaluator_noise_qualified: false`, and
`native_evaluation_error_bound: null`. A seven-axis/256-point diagnostic does not
cover every free coordinate of a large model or establish KKT, stationarity,
Hessian/covariance, globality, interval coverage or published-model fidelity.

The source controls use inert protocol objects and analytic supplied laws. Real
ROOT/custom-Combine ABI, full dataset semantics and native numerical comparisons
remain separately scheduled qualification requirements.
