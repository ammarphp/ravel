# Source-bound response recipe preparation

`ravel.physics.source_calibration.prepare_recipes(request_path, fresh_output_dir)`
prepares inputs for the existing `CalibrationProvider`. The request has kind
`athena-marginal-calibration-recipes`, schema 1, and exact fields:

```json
{
  "schema_version": 1,
  "kind": "athena-marginal-calibration-recipes",
  "native_sources": {
    "common_efficiency": {"path": "...", "sha256": "..."},
    "helper_functions": {"path": "...", "sha256": "..."},
    "tool_configuration": {"path": "...", "sha256": "..."},
    "trigger_tool": {"path": "...", "sha256": "..."},
    "shared_files_version": {"path": "...", "sha256": "..."}
  },
  "decoded": {"path": "...", "sha256": "..."},
  "root_key_census": {"path": "...", "sha256": "..."},
  "scope": {"path": "...", "sha256": "..."},
  "payloads": [{
    "root": {"path": "...", "sha256": "..."},
    "domain": {
      "configuration_namespace": "explicit producer configuration",
      "simulation_namespace": "explicit simulation namespace",
      "era_namespace": "explicit era/run namespace"
    },
    "population": {"path": "...", "sha256": "..."}
  }]
}
```

Every primary file in the decoded census must occur exactly once. The retained
physical-key census must bind the same complete original files and every decoded
key/cycle/class. This authenticates supplied source records. Numerical extraction
requires independent validation. Scope and
population documents retain the complete requested channels, eras, producer
configuration and missing physical prerequisites. They are input declarations
requiring applicability review. Naming a namespace does not qualify it.

The supported source profile is Athena commit
`0c2e91577f7832d6dc527b00f61f7e03db46064b`, SharedFiles `00-03-16`.
All five external source files must match the compiler's exact digests. These
files remain external inputs; the product contains no copied Athena tool bodies.
The [native tool configuration](https://gitlab.cern.ch/atlas/athena/-/blob/0c2e91577f7832d6dc527b00f61f7e03db46064b/PhysicsAnalysis/TauID/TauAnalysisTools/Root/TauEfficiencyCorrectionsTool.cxx)
leaves WP unset for `RecoHadTauTool` and `EleOLRHadTauTool`. The empty-WP extension
requires those exact tool names, the complete matching source bytes and the
matching hadronic-tau file/truth/prong policy. Empty WP is not a wildcard.

The compiler recomputes the complete
[CommonEfficiencyTool alias law](https://gitlab.cern.ch/atlas/athena/-/blob/0c2e91577f7832d6dc527b00f61f7e03db46064b/PhysicsAnalysis/TauID/TauAnalysisTools/Root/CommonEfficiencyTool.cxx)
and emits each supported working point as a separate alternative. Exact nominal
and up/down object cycles remain bound. Recommended and affecting native CP
nuisance identities remain distinct from released likelihood modifier mappings;
no string matching invents that mapping. A shared native nuisance ID is retained
across recipes. Each nuisance is a separate coherent up/down alternative;
recommended source sets must not be combined with other variations. The compiler
does not compose event weights or multiply nested working-point recipes.

The native trigger tool uses `sf_<period>_<WP>_<prong>`.
This preparation supports explicit `PeriodBinningAll` alternatives. For example,
native WP `medium` has effective key prefix `all_medium`. It does not infer run
menus, trigger matching, technical exposures, a joint two-leg response or an OR
efficiency. Eta, absolute eta, leading-track eta, average pileup, truth pt and the
source's literally signed `truthTauAbsEta` route remain separate. Momentum is
GeV. Histograms retain native clamp/FindFixBin behavior with no interpolation;
supported TF1s retain the existing bounded zero-parameter evaluator.

TES containers describe kinematic smearing/migrations, `eveto_cutvals` contains
selection thresholds, and the retained EleBDT campaign/substructure modes need
native key routing outside the declared source schema. They remain in the output census without SF
bindings. TH1 objects ignored by the pinned native CommonEfficiencyTool remain
visible; they are never converted to unity or to another class. A marginal
data/MC scale factor is not an absolute reconstruction or detector efficiency.

`recipe_input_pins(request_path)` returns the complete authenticated closure for
an ordinary AgentGraph tool node. Use action `response-recipes`, role `designer`,
`proposer` or `executor`, one attempt, and parameters `request_input` (the request
input ID) and `output_dir`. All returned pins must be explicit node inputs.
The Host identity includes the preparation and existing provider/math sources.
The operation writes `binding-NNNN.json` files and `preparation.json`, then checks
their initially generated commitments, source bytes and exact output membership
before returning. Failed outputs remain evidence. Each public call captures
inputs afresh. Input observations are time-local,
not a filesystem lock or persistent sandbox.

Load one selected binding using the ordinary existing API:

```python
from ravel.physics.source_calibration import ArtifactPin, CalibrationProvider
provider = CalibrationProvider.load(
    decoded=ArtifactPin(**receipt["decoded"]),
    original_root=ArtifactPin(**receipt["primary_census"][i]["root"]),
    binding=ArtifactPin(**selected_binding_pin),
)
```

Preparation checks this existing admission for every emitted binding, without
evaluating an event. Later scalar application requires the exact `SourceDomain`
and explicit source coordinates/truth/prongs. The 8 MiB per-file input/output,
32 MiB distinct source-byte and 256 recipe limits are software bounds. Repeated
source/provider proof reads and serialization are real work; these limits do
not claim a total-operation I/O or wall-time ceiling.

This preparation composes with existing native response construction,
calibrated-event, LLP and RS1 consumers after their original physical inputs and
fresh ordinary reviews are supplied. Preserve complete event/group identities,
all named signed weights, rejected/zero events and the applicable uncertainty
and normalization law when preparing those later inputs.
