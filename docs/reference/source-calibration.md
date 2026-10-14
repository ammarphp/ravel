# Source calibration and joint response

`ravel.physics.source_calibration` provides scalar corrections from explicitly
bound, decoded calibration objects and event weights from supplied absolute joint
probability tables. It uses Python's standard library. It does not reconstruct
objects or derive an absolute efficiency from a scale factor.

The scalar provider implements the inspected Athena TauAnalysisTools semantics
at commit `0c2e91577f7832d6dc527b00f61f7e03db46064b`, with shared-files namespace
`00-03-16`. Those identities do not establish which calibration release an
analysis used. The caller must supply the analysis configuration, simulation,
era and working-point namespaces explicitly.

## Scalar corrections

```python
from ravel.physics.source_calibration import (
    ArtifactPin, CalibrationProvider, SourceDomain,
)

provider = CalibrationProvider.load(
    decoded=ArtifactPin(decoded_json_path, decoded_file_sha256),
    original_root=ArtifactPin(original_root_path, original_root_sha256),
    binding=ArtifactPin(binding_json_path, binding_file_sha256),
)
context = SourceDomain(**binding_domain)
result = provider.evaluate(
    event,
    context=context,
    nuisance="HIGHPT",
    direction=1,
)
scale_factor = result["value"]
```

The three artifacts have separate byte digests. The binding also pins the
canonical decoded numerical content, exact ROOT object keys and cycles, literal
coordinate routing, nominal keys by prong, and asymmetric source aliases for
every admitted nuisance. Loading makes the numerical tables immutable and
indexes them once. Evaluation returns an immutable result with source identities.
The original container is checked at loading; subsequent evaluation uses the
captured tables. A changed source requires a new provider instance and binding.

Supported histogram objects are `TH2F` and `TH2D`. Each coordinate follows the
source operation `min(max(value, xmin), xmax * .999)`, then the ROOT upper-edge
bin convention. There is no interpolation. A clamp that reaches an unsupported
flow bin is refused. Supported `TF1` objects have one dimension, no parameters
and a bounded arithmetic/comparison expression; their routed coordinate is
evaluated without the histogram or saved-domain clamp. Arbitrary ROOT formulas,
TH1/TH3 objects and object/MET migrations are unsupported.

The event supplies the fields required by the literal source routing. These can
include final calibrated pT in GeV, signed or absolute eta, lead-track eta,
average interactions, or specified truth coordinates. In particular, a source
trigger axis named `mu` requires average interactions. Replacing it with eta
would evaluate a different correction. Truth category and one/three-prong
identity are explicit; an unknown truth match is refused. A known truth mismatch
uses the inspected source unity branch.

Relative nuisance magnitudes combine coherently in quadrature and multiply the
nominal correction with a declared direction. Missing nuisance mappings never
fall back to nominal. Duplicate JSON fields, nonfinite values, ambiguous cycles,
changed source bytes, mismatched contexts and unsupported source modes are
refused. A negative or nonfinite resulting correction is also refused.

The source implementation is
[CommonEfficiencyTool.cxx](https://gitlab.cern.ch/atlas/athena/-/blob/0c2e91577f7832d6dc527b00f61f7e03db46064b/PhysicsAnalysis/TauID/TauAnalysisTools/Root/CommonEfficiencyTool.cxx).
Source bytes, decoded numerical content and applicability must all be reviewed
when admitting a scientific calculation. The provider does not open ROOT files
or certify an external decoder.

## Joint categorical weights

Marginal scale factors do not determine correlated trigger probabilities or
failed-tight-ID categories. `JointCategoricalResponse` instead requires complete
absolute joint probabilities for both data and simulation, with pinned evidence.

```python
from ravel.physics.source_calibration import JointCategoricalResponse

joint = JointCategoricalResponse.load(
    ArtifactPin(table_path, table_sha256),
    evidence=ArtifactPin(evidence_path, evidence_sha256),
)
weight = joint.weight_category(generator_weight, context, observed_category)
selection_ratio = joint.selection_sf(context, accepted_categories)
```

Category weighting and a selected-probability ratio are alternative estimators
for the intended correction. Applying both to the same selection double counts
the correction. Category weighting multiplies the finite signed generator
weight by `p_data(category) / p_MC(category)` and preserves its sign.

The JSON table requires these fields:

- `quantity`: `absolute_joint_data_and_mc_probabilities`.
- `calibration_evidence_sha256`: the supplied evidence artifact digest.
- `exhaustive_mutually_exclusive`: literal `true`.
- `conditioning_fields`: unique field names.
- `cells`: rows containing an exact string-valued `context`, plus `mc` and
  `data` maps over the same exhaustive outcome labels.

Every probability is finite and in [0,1]; each table sums to one within absolute
tolerance `1e-12`, with zero relative tolerance. Data support absent from MC,
missing cells, duplicate outcomes, zero selected MC mass and overflowing ratios
are refused. There is no inferred independence or interpolation across cells.
Evidence hashes establish custody; they cannot establish that a supplied table
is a measured or applicable calibration.

`exclusive_probabilities(loose, medium, tight)` computes the four exclusive
outcomes of nested absolute efficiencies. `exclusive_scale_factors(mc, data)`
forms their data/MC ratios. Both inputs must contain all three absolute
efficiencies. An ID scale factor alone is insufficient.

## Validation and use in a recast

Portable unit tests use explicitly synthetic tables and container-byte tokens.
They exercise scalar arithmetic, bin edges, formula routing, source bindings,
joint support, signed weights and refusal behavior. These controls require no
ROOT runtime or experimental payload download.

A detector-level stau calculation additionally needs a complete matched
reconstructed-event population, the actual analysis release/configuration,
joint ID/trigger response, top-veto behavior, coherent nuisance object/MET states,
and process/decay/filter/exposure normalization. The all-region event adapter
must receive the complete response state for every affected SR and CR. The
source scalar library supplies supported correction factors within that larger
construction; it does not establish those missing inputs or a statistical
finite-MC sampling law.
