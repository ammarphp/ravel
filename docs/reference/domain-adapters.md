# Supplied-artifact domain operations

The domain worker adds executable operations for model checks, EFT interpolation,
classifiers, long-lived particles and specialized collision inputs. It does not
generate events or turn an upstream model into a validated analysis. Use these
tasks through the supervised workflow so that input identities, approval, runtime
budget and results are retained together.

The Python interface in `ravel.physics.domain_adapters` is:

```python
validate(task)                        # raises ValueError on invalid configuration
inputs(task, base_dir)                # every consumed artifact as pathlib.Path
run(task, base_dir, output_dir)       # writes a new domain-result.json and returns it
```

Every task has exactly `{"domain": "...", "config": {...}}`. Unknown fields are
errors. Input file paths resolve relative to `base_dir`. Symlink inputs and output
directories, duplicate JSON keys and nonfinite numeric inputs are rejected.
Input hashes are checked again after execution. Existing results cannot be
overwritten. A result with `status: "passed"` means the requested arithmetic and
supplied checks passed. Every result retains `physics_validated: false` and
branch-specific limitations. A failed supplied comparison is retained as
`status: "failed"`; it is not converted to a successful scientific result.

## Exported UFO model checks

```json
{
  "domain": "ufo",
  "config": {
    "model_dir": "inputs/MyModel_UFO",
    "parameters": {"mass": 100.0},
    "orders": {"NP": 2},
    "benchmarks_file": "inputs/model-benchmarks.json"
  }
}
```

The worker parses Python syntax without importing or evaluating model code. It
requires `__init__.py`, `object_library.py`, `particles.py`, `parameters.py`,
`couplings.py`, `coupling_orders.py`, `vertices.py` and `lorentz.py`. It inventories
direct, static UFO constructors, checks external parameter names and unique LHA
addresses, declared coupling-order powers and expansion bounds, and explicit
particle mass/width references. All files in the supplied model directory are
bound to the result, including optional source and auxiliary files.

The benchmark file has exactly:

```json
{
  "model_parameters": {"mass": 100.0},
  "coupling_orders": {"NP": 2},
  "checks": [
    {"name": "supplied width control", "actual": 1.0, "reference": 1.0,
     "unit": "GeV", "atol": 0.000001, "rtol": 0.0,
     "source": "identifier of the actual independent control artifact"}
  ]
}
```

The benchmark recipe must match the declared parameter/order point exactly.
These are comparisons of supplied numbers; the worker does not rerun the
generator or prove a citation's provenance. Parameter defaults are reported
separately from requested values: requested values are not silently applied to
the UFO. FeynRules itself, dynamic model construction, gauge identities, Ward
tests, numerical expression evaluation, vertex completeness and NLO counterterms
remain outside this static check. A syntactically valid malicious module is never
executed by this branch. The format follows the structure described in
[UFO 2.0](https://arxiv.org/abs/2304.09883).

## EFT basis and interference reconstruction

```json
{
  "domain": "eft",
  "config": {
    "basis_file": "inputs/eft-basis.json",
    "coefficients": ["c1"],
    "coefficient_units": {"c1": "TeV^-2"},
    "validity": {"c1": [-1.0, 1.0]},
    "queries": [{"c1": 0.25}],
    "atol": 0.00000001,
    "rtol": 0.00000001
  }
}
```

The basis file contains `coefficient_units`, `prediction_unit`, unique `bins`,
`source`, `samples` and `controls`. Each sample/control is
`{"point": {"c1": value}, "values": [bin_prediction, ...]}`. For one coefficient,
three distinct samples determine the constant, linear interference and quadratic
terms; at least one additional independent control point is required. For *n*
coefficients the number of terms is `1 + n + n(n+1)/2`, including every mixed
quadratic term. The input design must have full rank and condition number at most
`1e10`. At most 20 coefficients are admitted in one task.

The worker fits all supplied samples, checks their residuals, checks the held-out
control points, and evaluates every query. It reports the constant, linear and
quadratic contributions separately. Negative interference, signed bin values and
negative total predictions are preserved. No clipping is available; a negative
total is explicitly unsuitable as a Poisson mean. The quadratic assumption and
declared validity intervals require physics review: they are not automatically
proved by polynomial agreement. Monte Carlo covariance, EFT truncation and
scale uncertainties are not invented. NumPy is required.

## ONNX classifier inference

```json
{
  "domain": "classifier",
  "config": {
    "model_file": "inputs/classifier.onnx",
    "events_file": "inputs/features.json",
    "controls_file": "inputs/reference-scores.json",
    "features": [
      {"name": "pt", "unit": "GeV", "mean": 50.0, "scale": 20.0},
      {"name": "eta", "unit": "1", "mean": 0.0, "scale": 1.0}
    ],
    "dtype": "float32",
    "input_name": "features",
    "output_name": "score",
    "score_index": null,
    "threshold": 0.5,
    "comparison": ">=",
    "score_range": [0.0, 1.0],
    "atol": 0.000001,
    "rtol": 0.000001
  }
}
```

The feature list defines ordering and the transform `(value - mean) / scale`.
Units must match the data exactly; no implicit unit conversion is attempted.
Supported dtypes are `float32` and `float64`, matched to the actual ONNX input.
The graph must have one rank-two input `[batch, features]`. Set `score_index`
to `null` for a rank-one output or to an integer column for a rank-two output.
Both `>` and `>=` are supported and their boundary behavior is explicit.

The event file has `units` and `events`:

```json
{
  "units": {"pt": "GeV", "eta": "1"},
  "events": [
    {"event_id": "sample-a:1", "values": {"pt": 65.0, "eta": 0.2}, "weight": 1.0}
  ]
}
```

The control file has the same fields plus `expected_scores`, in event order.
Every feature must be present, extra features are errors, event identities must
be unique within each file, and signed weights are retained. Results include
scores, selection decisions, selected sum of weights and sum of squared weights.
Failed reference scores retain a failed result even if inference itself runs.

The optional `onnx` and `onnxruntime` dependencies are required. Graph validation
rejects external tensor data and custom operator domains, including in nested
graphs. Inference uses the actual
[ONNX Runtime CPU API](https://onnxruntime.ai/docs/api/python/api_summary.html),
with one intra-operation and one inter-operation thread. This does not validate
training data, classifier calibration, distribution shift or detector response.
The model executes numerical operators and still belongs inside a bounded,
approved workflow.

## Long-lived particle operations

```json
{
  "domain": "llp",
  "config": {
    "operation": "decay-probability",
    "events_file": "inputs/llp-events.json",
    "target_ctau": {"value": 10.0, "unit": "mm"},
    "geometry": {"r_min_mm": 10.0, "r_max_mm": 100.0, "z_half_mm": 300.0},
    "combination": "at-least-one"
  }
}
```

The events file is a nonempty JSON list of
`{"event_id": "...", "weight": 1.0, "particles": [...]}`. For decay probability,
each particle has exactly `px_GeV`, `py_GeV`, `pz_GeV`, `mass_GeV`. The finite
cylindrical shell is centered at the production origin. The worker finds the
proper flight-length interval inside it and integrates the exponential decay
law. It supports `all` or `at-least-one` independent decays within an event,
particles along the beam axis, particles at rest and signed event weights.
Proper decay lengths accept `mm`, `cm` or `m`; seconds are rejected rather than
silently treated as a length. The relativistic lifetime relation follows
[PDG kinematics](https://pdg.lbl.gov/2024/reviews/rpp2024-rev-kinematics.pdf).

For lifetime reweighting, use `operation: "reweight"`, omit `geometry` and
`combination`, and add `source_ctau` with the same value/unit structure. Each
particle then has `proper_length_mm` and boolean `right_censored`. An observed
decay at proper length *l* receives the density ratio
`(ctau_source / ctau_target) exp[l(1/ctau_source - 1/ctau_target)]`. A right-censored
observation receives the survival ratio, which omits the prefactor. Products are
computed in log space; unstable ratios are refused, never clipped.

These operations require identical production kinematics and untruncated
exponential sampling or the stated right-censoring model. They do not invent
branching ratios, reconstruction efficiencies, absolute normalization or a
detector response. Sum-of-squared-contributions is retained as a weighted moment,
not a complete uncertainty model. The existing efficiency-map folding route
remains separate and requires its published-map validation gates.

## Nuclear, forward and neutrino inputs

Use `{"domain": "applicability", "config": {"family": "...", "data_file": "..."}}`.
These branches perform the bounded operations below, rather than declaring an
entire domain supported.

| Family | Required input data | Computation and boundary |
|---|---|---|
| `heavy-ion` | `beam_mass_numbers` (two positive integers, at least one greater than one), `sqrt_sNN_GeV`, `centrality_percent` (increasing pair within 0–100), `centrality_definition`, positive `event_exposure`, `observable_unit`, `source`, `bins` | Per-event differential yield `sumw / (event_exposure * bin_width)` and conditional fixed-exposure variance `sumw2 / (event_exposure * bin_width)^2`. Each ordered, nonoverlapping bin has `low`, `high`, `sumw`, `sumw2`. No nuclear generator, centrality calibration, nuclear PDF, R_AA reference or exposure uncertainty is supplied automatically. |
| `forward` | `plane_z_mm`, positive `radius_mm`, `transport: "neutral-straight-line-vacuum"`, `source`, `events` | Straight-line neutral propagation to a plane and circular-aperture selection. Each event has `event_id`, `weight`, `x_mm`, `y_mm`, `z_mm`, `px_GeV`, `py_GeV`, `pz_GeV`, `charge`. Charge must be zero. Backward or parallel trajectories do not reach the plane. No beam optics, material transport or detector efficiency is supplied. |
| `neutrino` | `flavor_pdg` (one of ±12, ±14, ±16), `target`, `target_basis` (`nucleon`, `nucleus` or `electron`), `n_targets`, `flux_unit: "cm^-2/bin"`, matching `cross_section_unit: "cm^2/<target_basis>"`, `flux_exposure: "integrated"`, `cross_section_averaging: "flux-weighted-per-bin"`, `source`, `bins` | Expected count per bin is `flux * cross_section * n_targets * efficiency`. Ordered nonoverlapping energy bins have `energy_low_GeV`, `energy_high_GeV`, `flux`, `cross_section`, `efficiency` (fraction 0–1). Already integrated flux is never multiplied by bin width again. Thin-target folding uses supplied flavor, material and target basis; it does not generate flux, nuclear interactions, oscillations, migration or uncertainties. |

For neutrino inputs, the [PDG review of neutrino cross-section measurements](https://pdg.web.cern.ch/pdg/2020/reviews/rpp2020-rev-nu-cross-sections.pdf)
explains why a nuclear target and energy-dependent interaction model cannot be
borrowed silently from ordinary proton-proton analysis assumptions.

## Exact-node topology and efficiency-map folding

```json
{
  "domain": "efficiency-map",
  "config": {
    "map_file": "inputs/efficiency-map.json",
    "events_file": "inputs/map-events.json"
  }
}
```

This branch executes a supplied event-selection probability map at exact nodes.
It requires NumPy and admits at most 256 map nodes in one bounded fold. It does
not extrapolate, interpolate, clamp probabilities or assign zero to an uncovered
point. A per-object efficiency cannot silently become an event-selection map.
The map file has this structure:

```json
{
  "map_id": "supplied-map-v1",
  "topology": "explicit-production-and-decay-topology",
  "coordinate_units": {"mass": "GeV"},
  "response_kind": "event-selection-probability",
  "source": "identifier for the supplied response artifact",
  "nodes": [
    {"node_id": "m100", "coordinates": {"mass": 100.0}, "efficiency": 0.5},
    {"node_id": "m200", "coordinates": {"mass": 200.0}, "efficiency": 0.25}
  ],
  "uncertainty": {
    "kind": "absolute-probability-covariance",
    "node_ids": ["m100", "m200"],
    "covariance": [[0.01, 0.005], [0.005, 0.04]],
    "source": "identifier and justification for the supplied covariance"
  }
}
```

The illustrated numbers are an analytic software control, not detector response
evidence. The map identity, topology and coordinate units must match the event
document exactly. Node IDs and coordinate tuples must be unique. Efficiencies
must be finite fractions between zero and one. The covariance uses absolute
probability units, declares its node ordering, and must be symmetric and positive
semidefinite within relative numerical tolerance `1e-12`; it is never silently
symmetrized or repaired.

The event document is:

```json
{
  "map_id": "supplied-map-v1",
  "topology": "explicit-production-and-decay-topology",
  "coordinate_units": {"mass": "GeV"},
  "node_semantics": "alternative-model-points",
  "weight_unit": "events",
  "source": "identifier for the weighted event or point population",
  "events": [
    {"event_id": "sample:1", "group_id": "independent-group:1",
     "node_id": "m100", "coordinates": {"mass": 100.0}, "weight": 3.0},
    {"event_id": "sample:2", "group_id": "independent-group:1",
     "node_id": "m100", "coordinates": {"mass": 100.0}, "weight": -1.0}
  ]
}
```

Every event has a unique identity and an explicit independent-group identity.
Correlated subevents use the same group. A point aggregate can be used only when
its weight really represents the declared independent statistical group; merely
compressing independent events to one row changes the second moment and is not
equivalent. Signed weights are preserved. Node identity and coordinates must
agree exactly, with no automatic unit conversion or near-node tolerance.

For node *i*, the folded value is `efficiency_i * sum_weights_i`. The worker sums
weights within each independent group before computing the joint second moment.
It reports this input moment matrix, the conditional MC covariance after applying
the central efficiencies, and the separately propagated supplied-map covariance
`sum_weights_i * map_covariance_ij * sum_weights_j`. The latter keeps correlations
between nodes, including anticorrelations induced by signed weights. Counts and
nodes without input events are reported, so an unsampled node is distinguishable
from a cancellation or a zero response.

`node_semantics: "alternative-model-points"` produces per-node predictions and
covariance only: total-yield and total-variance fields are `null`, since different
mass or lifetime hypotheses must not be summed into one result. Use
`node_semantics: "event-kinematics"` only for exclusive kinematic contributions
to one population; that mode additionally reports the total and the sum of each
covariance matrix. MC and response contributions remain separate. Their mixed
term, cross-covariance and joint statistical model are not inferred.

The calculation does not establish a physical validity envelope, topology
completeness, branching ratio, luminosity, cross section, lifetime dependence or
detector calibration. Those assumptions require supplied evidence and review.
The existing published-map closure gates still apply to a physics result.

## Engineering controls and remaining scientific work

`tests/unit/test_domain_adapters.py` uses independent analytic controls for the
complete quadratic polynomial, finite-cylinder decay probabilities, censored
lifetime ratios, unequal-width nuclear bins, integrated neutrino exposure and
forward aperture boundaries. An actual asymmetric ONNX graph checks feature
ordering, affine normalization, threshold boundaries and failure retention when
the optional runtime is available. UFO tests include an import-time sentinel
that must never execute. Input mutation, symlink substitution, malformed units,
rank loss, negative predictions and missing references are adversarial cases.
Exact-node map controls additionally exercise signed correlated groups, supplied
response covariance, alternative-hypothesis isolation, uncovered coordinates,
inconsistent units/topology, covariance ordering and nonphysical probabilities.

These tests establish software behavior in the stated domain. They are not
published ATLAS/CMS closure, classifier-efficiency validation, nuclear-response
validation or an RRR acceptance repair. Each scientific application still needs
the matching reference inputs, reviewed assumptions and target-specific closure.
