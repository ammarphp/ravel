# Quantity transport and supplied measurement inference

These adapters preserve the distinction between a weighted quantity, its
uncertainty and a statistical model. Quantity transport calculates grouped
moments from supplied event contributions. Measurement inference evaluates a
supplied Gaussian model with an explicit covariance and SM prediction. Neither
operation establishes detector fidelity or reproduction of an experimental
analysis.

Use the [scientific-study workflow](../workflow/reference/scientific-studies.md)
for approval, supervised execution and retained input identities. The Python
interfaces below are calculation primitives; calling them directly does not
create approval or execution receipts.

## Installation

From a source checkout containing these adapters, with Python 3.10–3.12:

```bash
python -m pip install '.[science,measurement]'
```

The quantity calculation itself uses the standard library. The `science` extra
provides numerical dependencies and diagnostic figures. The `measurement`
extra provides NumPy, SciPy and the verified Spey version, **0.2.6**. Goodness of
fit needs NumPy/SciPy; `spey_cls` additionally requires that exact Spey version.
Neither adapter requires a MadGraph, Rivet or SimpleAnalysis installation.

## A complete quantity study

Save the following as `study.json`. All paths resolve relative to this file.
The example is an arithmetic control, not a physical event sample.

```json
{
  "schema_version": 1,
  "mode": "quantities",
  "source": "Synthetic signed-weight arithmetic control",
  "assumptions": [
    "Each group is independent of every other group",
    "Supplied weights are in pb and the fixed scale is exactly one"
  ],
  "max_seconds": 60,
  "approval_mode": "physicist",
  "task": {"contract": "quantity.json", "records": "fills.jsonl"}
}
```

Save the quantity contract as `quantity.json`:

```json
{
  "schema_version": 1,
  "axes": [{"name": "pT", "unit": "GeV"}],
  "bins": [
    {"id": "low", "low": [0.0], "high": [1.0]},
    {"id": "high", "low": [1.0], "high": [3.0]}
  ],
  "weight_names": ["nominal"],
  "input_weight_unit": "pb",
  "representation": "differential",
  "normalization": {"kind": "absolute", "scale": 1.0, "unit": "pb"}
}
```

Save these two JSON records, one per line, as `fills.jsonl`:

```jsonl
{"event_id":"event-a","group_id":"group-a","shard_id":"sample-a","weights":{"nominal":2.0},"fills":[[0.5],[2.0]]}
{"event_id":"event-b","group_id":"group-b","shard_id":"sample-a","weights":{"nominal":-1.0},"fills":[[2.0]]}
```

The first event fills both bins. Its contributions are correlated. The expected
integrated values are `[2, 1]` pb. The differential values are `[2, 0.5]`
`pb/(GeV)`, with covariance `[[4, 2], [2, 1.25]]` in `(pb/(GeV))^2`.
The unequal bin widths affect both values and both axes of the covariance.

Plan and review the concrete proposal before execution:

```bash
ravel plan --rundir quantity-study --spec study.json
ravel approve --rundir quantity-study --quote 'Actual approval of the recorded proposal'
ravel run --rundir quantity-study
ravel status --rundir quantity-study --write
```

Replace the quotation with actual assent. Authorized scripted comparative
controls use `approval_mode: "scripted_yes"` and `approve --scripted`, as
described in the workflow guide. Scripted assent is not expert review.

Read `quantity-study/outputs/quantities.json` for values, covariance, flow,
denominators and additive moments. `outputs/result.json`, `recipe.json`,
`verification.json` and `checkin2.json` describe the delivered scope and its
custody. Available PDF/PNG diagnostics use the recorded bin coordinates and
units without additional normalization.

## Quantity contract and record rules

The contract has exactly the fields shown above. Unknown fields are rejected.

| Field | Required meaning |
|---|---|
| `axes` | Nonempty ordered list of unique `name` values and explicit `unit` strings; use `"1"` for dimensionless axes |
| `bins` | Nonempty list of unique `id` values and finite `low`/`high` coordinate arrays matching the axes |
| `weight_names` | Unique ordered names; every record must supply exactly these weights |
| `input_weight_unit` | Unit of the supplied weights before scaling |
| `representation` | `"integrated"` or `"differential"` |
| `normalization` | One of the explicit alternatives below |

Bins may form an irregular arrangement of disjoint rectangular cells in any
number of dimensions. Every width must be positive. Bins include their lower
edges and exclude their upper edges. A fill on the largest upper edge or in a
gap contributes to flow. The adapter rejects overlapping rectangles rather than
choosing the first matching bin. Differential values divide by the full bin
hypervolume, including widths along dimensionless axes.

Every record has exactly `event_id`, `group_id`, `shard_id`, `weights` and
`fills`. IDs are nonempty strings. Each `event_id` is globally unique across the
calculation and any later merge; it identifies a subevent/contribution record.
Correlated subevents use a common `group_id`. Different groups are assumed
independent. A group cannot span shards. Each fill is a coordinate array with
one finite number per axis. An empty `fills` list retains an event that made no
histogram entry. Do not omit rejected events from an inclusive denominator.

Signed and zero weights are accepted. Add additional names to `weight_names`
and supply their values in every record to transport multiple weight streams.
No missing weight is replaced by nominal. The result orders its joint
covariance by weight, then bin; `covariance_order` records this mapping.
Cross-weight correlations are retained, but a collection of variations does not
automatically become a systematic uncertainty envelope.

### Absolute and normalized quantities

Absolute normalization requires exactly:

```json
{"kind": "absolute", "scale": 1.0, "unit": "pb"}
```

`scale` must be finite and positive. It is a supplied fixed conversion applied
once, not an inferred cross section or k-factor. Its uncertainty is not included.
For differential output, axis units are appended to the denominator: for
example `pb/(GeV)` or `pb/(GeV*GeV)`. Dimensionless axis units are omitted from
the unit string, but their numerical bin widths still divide the value.

Normalized quantities instead require exactly one of:

```json
{"kind": "normalized", "scope": "in_range"}
```

```json
{"kind": "normalized", "scope": "all_events"}
```

`in_range` uses the sum of weighted fills in the finite bins as the denominator.
The resulting integrated area is one. `all_events` uses each record's weight
once, including empty records and events with flow. This gives a quantity per
weighted input event; its area need not be one. Multiple fills can make it
larger than one, and signed cancellations can produce negative bin values.
Each weight stream has its own denominator.

A finalized normalized result requires a positive denominator for every weight
stream. It reports the denominator's weighted second moment and relative
standard error. A positive but poorly determined denominator is not made
statistically reliable by this check.

### Covariance and merging

For each independent group, contributions are summed before their outer
product enters the second moment. Two correlated subevents of weights `+2`
and `-1` in the same bin therefore contribute variance `1`, whereas independent
events contribute `5`. Multiple fills in one record remain correlated.
Signed cross-bin covariance is allowed.

This is a **Poissonized independent-group** covariance, not the sample covariance
for a fixed number of events. For a normalized bin `y = N/D`, the Jacobian uses
both derivatives `1/D` and `-N/D^2`. The propagated covariance includes the
denominator variance and its covariance with every bin and weight stream.
It is first-order propagation and can be unreliable near a cancelling or
poorly determined denominator. No integration, luminosity, detector, theory or
fixed-scale uncertainty is supplied automatically.

The Python API is:

```python
from ravel.physics.quantities import validate, calculate, merge

checked_contract = validate(contract)
result = calculate(checked_contract, records)

# Useful when a signed shard has a zero or negative denominator on its own.
left = calculate(checked_contract, left_records, finalize=False)
right = calculate(checked_contract, right_records, finalize=False)
combined = merge([left, right])
```

`records` may be an iterable. `merge` adds raw moments before normalization; it
does not average separately normalized histograms. Contracts, including fixed
scales, must match. Event IDs, group IDs and shard IDs must be disjoint across
inputs. Splitting a correlated group across shards loses cross-shard products
and is rejected. Additive-state checksums detect mutation; they are not a
substitute for the supervising workflow's source receipts. A pending additive
result is not a finalized plotted quantity.

Full covariance storage grows quadratically with the number of bins times the
number of weights. Retained identities and grouped contributions also consume
memory. Budget large analyses explicitly; this implementation is not an
unbounded streaming histogram service.

## A complete supplied measurement

Save this as `measurement.json`. All numerical values describe a synthetic
Gaussian control in pb, not event counts or an ATLAS/CMS likelihood.

```json
{
  "schema_version": 1,
  "analysis_id": "synthetic-correlated-gaussian-control",
  "quantity": {
    "axes": [{"name": "mass", "unit": "GeV"}],
    "bins": [
      {"id": "a", "low": [0.0], "high": [1.0]},
      {"id": "b", "low": [1.0], "high": [3.0]}
    ],
    "representation": "integrated",
    "normalization": "absolute",
    "unit": "pb"
  },
  "data": {"bin_ids": ["a", "b"], "values": [11.0, 19.0], "unit": "pb"},
  "sm": {"bin_ids": ["a", "b"], "values": [10.0, 20.0], "unit": "pb"},
  "signal": {"bin_ids": ["a", "b"], "values": [2.0, 1.0], "unit": "pb"},
  "experimental_covariance": {
    "bin_ids": ["a", "b"],
    "matrix": [[4.0, 1.0], [1.0, 9.0]],
    "unit": "(pb)^2"
  },
  "covariance_policy": "experimental_only",
  "overlap": {"policy": "single_measurement"},
  "constraints": []
}
```

The expectation is `SM + mu × signal`, with a covariance fixed for every `mu`.
There is no implicit luminosity multiplication, bin-width conversion, SM
subtraction or counting-model approximation. Supply vectors in the requested
representation and units already. Each vector and covariance has its own
`bin_ids`; order may differ because alignment uses exact identifiers. Missing,
extra or repeated IDs fail. Unit strings must match exactly. A covariance unit
is the literal `(<quantity unit>)^2`, for example `(pb)^2`.

Save the following as `measurement-study.json`:

```json
{
  "schema_version": 1,
  "mode": "measurement",
  "source": "Synthetic correlated Gaussian arithmetic control",
  "assumptions": [
    "The supplied fixed Gaussian covariance is the complete model for this control",
    "No experimental or detector validation is inferred"
  ],
  "max_seconds": 60,
  "approval_mode": "physicist",
  "task": {
    "schema_version": 1,
    "input": "measurement.json",
    "inference": "goodness_of_fit",
    "signal_strength": 1.0
  }
}
```

Use the same `plan → approve → run → status` commands with a new run directory.
The adapter writes `outputs/measurement/measurement.json`; the common result is
also in `outputs/result.json`. For this control, the SM chi-square is `15/35`
with two degrees of freedom. The tested model at `mu=1` has chi-square `21/35`.
These goodness-of-fit p-values are not CLs exclusions or discovery claims.
The reported unconstrained signal-strength estimate may be negative.

### Covariance and overlap declarations

The input has exactly the fields in the example, plus an optional
`theory_covariance`. The two covariance policies are:

- `experimental_only`: use the experimental covariance. Supplying a theory
  covariance under this policy is an error, not a silent omission.
- `independent_theory_sum`: require `theory_covariance` with the same
  `bin_ids`, `matrix`, `unit` schema, then add it to the experimental covariance.
  The declaration asserts independence and a theory covariance fixed with
  signal strength. Parameter-dependent theory uncertainty requires another model.

Covariances must be finite, symmetric and positive semidefinite. Symmetry and
positive-semidefinite checks allow only numerical tolerance. The stochastic
subspace must be positive definite, without undeclared null directions or
numerical condition numbers reaching the `10^12` cutoff. No diagonal fallback,
ridge term or unrecorded bin removal repairs a failed covariance.

`overlap` must use one of these exact forms:

```json
{"policy": "single_measurement"}
```

```json
{"policy": "joint_covariance", "evidence": "Identify the supplied joint covariance and its provenance"}
```

```json
{
  "policy": "independent_measurements",
  "bin_groups": ["measurement-A", "measurement-B"],
  "evidence": "Identify the justification for independence"
}
```

`bin_groups` follows the order of `quantity.bins`, with one group per bin. The
independence policy rejects any nonzero experimental or theory covariance
between different groups. Overlapping measurements need a supplied joint model;
different histogram names do not establish independence. Evidence text records
the declaration but does not independently verify its scientific justification.

### Normalized measurements and singular covariance

A unit-normalized measurement has an exact area constraint, so its covariance
is normally singular. Supply that constraint explicitly. For integrated bins,
its coefficients are all ones; for differential bins they are the bin volumes.
Set its `value` to one. The data and SM must satisfy it, the signal deformation
must have zero area, and the covariance must preserve it within numerical
tolerance. Normalized integrated units are `"1"`; differential units use the
canonical inverse-axis form such as `"1/(GeV)"`.

This complete alternative `measurement.json` is an unequal-width normalized
control:

```json
{
  "schema_version": 1,
  "analysis_id": "synthetic-normalized-gaussian-control",
  "quantity": {
    "axes": [{"name": "mass", "unit": "GeV"}],
    "bins": [
      {"id": "a", "low": [0.0], "high": [1.0]},
      {"id": "b", "low": [1.0], "high": [3.0]}
    ],
    "representation": "differential",
    "normalization": "normalized",
    "unit": "1/(GeV)"
  },
  "data": {"bin_ids": ["a", "b"], "values": [0.4, 0.3], "unit": "1/(GeV)"},
  "sm": {"bin_ids": ["a", "b"], "values": [0.5, 0.25], "unit": "1/(GeV)"},
  "signal": {"bin_ids": ["a", "b"], "values": [0.1, -0.05], "unit": "1/(GeV)"},
  "experimental_covariance": {
    "bin_ids": ["a", "b"],
    "matrix": [[0.01, -0.005], [-0.005, 0.0025]],
    "unit": "(1/(GeV))^2"
  },
  "covariance_policy": "experimental_only",
  "overlap": {"policy": "single_measurement"},
  "constraints": [{"coefficients": [1.0, 2.0], "value": 1.0}]
}
```

Here `[1,2]·data = [1,2]·SM = 1`, and `[1,2]·signal = 0`. This is an additive
shape deformation, not a second unit-normalized signal distribution added to
the first. The adapter projects into the orthogonal stochastic subspace and
records the projection. The example has one degree of freedom and SM
chi-square one. Additional constraints must be independent and justified;
absolute measurements may also declare exact constraints where appropriate.
No undeclared covariance null direction is silently discarded.

A normalized shape generated by `(SM + mu × new physics)` followed by a
`mu`-dependent normalization is generally nonlinear. This adapter's linear
deformation model is not a replacement for that construction.

### Optional observed and expected 95% CLs limits

To request limits, keep the common study fields and replace `task` with:

```json
{
  "schema_version": 1,
  "input": "measurement.json",
  "inference": "spey_cls",
  "signal_strength": 1.0,
  "poi_max": 20.0
}
```

`signal_strength` is a finite nonnegative tested strength. `poi_max` is the
positive, explicit upper bound of the limit search; it is required for
`spey_cls` and forbidden for `goodness_of_fit`. The result includes observed
and five *a priori* expected limits ordered `[-2σ, -1σ, median, +1σ, +2σ]`.
Limits are dimensionless signal strengths, not automatically cross sections.

The worker invokes Spey's documented
[`default.multivariate_normal` backend](https://spey.readthedocs.io/en/stable/plugins.html)
with asymptotic `qtilde` CLs. For the fixed-covariance linear Gaussian model, an
exact one-dimensional sufficient statistic preserves every likelihood ratio.
The statistic is recorded; this mathematical projection does not turn
measurement values into counts. Each resolved crossing is also checked against
the independent Gaussian tail-ratio expression and the `CLs=0.05` residual.
The normalized control above has expected median `mu95 ≈ 1.959964`.

A crossing outside `poi_max` stays `above_scan` with its bound. It is not
replaced by a resolved limit at the cap. If any of the six crossings is
unresolved, the adapter retains its result but returns `status: "failed"`.
Zero sensitivity cannot produce a limit. The fit's separately recorded bound
can exceed the search cap so that the maximum-likelihood fit itself is not
artificially clipped there.

The Python interfaces are:

```python
from ravel.physics.measurement import validate, inputs, prepare, run

checked_task = validate(task)          # Syntax only; no file reads or inference.
bound_files = inputs(task, base_dir)   # List of Paths for workflow custody.
model = prepare(measurement_document) # Validate and project the supplied model.
result = run(task, base_dir, output_dir)
```

`run` creates the output directory when needed and writes a new
`measurement.json` exclusively; it will not overwrite an existing result.

## What a successful result establishes

`status: "passed"` means the declared numerical operation completed and its
implemented checks passed. `physics_validated` remains false. Source provenance,
detector response, unfolding/model dependence, the Gaussian approximation,
theory coverage, overlap evidence and any published-reference comparison need
separate scientific validation. The adapter does not provide toy-calibrated
coverage, arbitrary nuisance profiling, parameter-dependent covariance or
nonlinear EFT coupling inference. A YODA histogram's marginal errors alone do
not supply the missing measurement covariance or likelihood.

For broader input and execution boundaries, see
[scientific studies](../workflow/reference/scientific-studies.md) and
[scientific result contracts](scientific-results.md).
