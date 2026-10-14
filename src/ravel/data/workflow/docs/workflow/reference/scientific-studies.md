# Scientific studies with supplied events and models

This route executes **existing inputs** under a concrete, byte-bound proposal.
It adds Rivet and reconstructed-object analysis, quantity transport, complete
paired event contrasts, typed compositional cutflows, supplied Gaussian measurement
inference and bounded model/classifier/lifetime and topology-efficiency operations.
It does not generate a collision sample or certify a paper reproduction.

## Install and start

For selected table packages and explicit regional mass/width grids, follow
[source materialization](width-input-materialization.md) and
[regional construction](../../reference/mass-width-grid-recipes.md). SAF delivery
uses the supplied-booking schema2 family with source and upstream API pins,
complete named views and population descriptions; schema1 needs external
conversion, with missing metadata reported as `missing-input`. Its task may
declare `output: {filename, format}` for `json` or `json-compact` delivery.
MSSM source-listed populations use only the complete `point-list-v1` form.
Normalize another supplied JSON layout with
`python -m ravel.physics.population_inputs --contract <mapping.json> --output-dir <fresh-dir>`.
The contract declares `schema_version: 1`, source pin, mapping (`records`,
`identity`, `coordinates`, `relations`) and `{filename, format}` output.
Mappings use literal JSON key paths; each relation has linear `{path, factor}`
terms and a rational `equals`. The converter preserves every row and tests
supplied relations. Select its returned pin explicitly in the spectrum-map
request; there is no identity or fixed-count compatibility reader.
The spectrum-map task also accepts the explicit JSON output contract. These
offline transformations authorize no native generation or fit.

<a id="from-the-repository-checkout-in-a-dedicated-python-312-environment"></a>

Prepare Python 3.12 and the [compiler prerequisites](../../installation.md#before-you-start), then run the complete setup from the checkout:

```bash
python3.12 scripts/setup/python_installation.py
source .venv/bin/activate
```

The Python host supports 3.11–3.12. The installer provides the required numerical, measurement, classifier and inference libraries and isolated engine environments. Follow the [installation guide](../../installation.md) for required native engines. Rivet and SimpleAnalysis use separately recorded runtimes; a worker's interpreter can differ from the RAVEL host without changing installed toolchains.

A new supplied-data study starts from an explicit JSON specification. Its task is
the intake; do not initialize a detector/reproduction run and then change its mode.
`--rundir` must name a new directory.

```bash
ravel plan --rundir my-study --spec study.json
# Review my-study/CHECKIN1.md and inputs/checkin1.json.
ravel approve --rundir my-study --quote 'The actual approval of this proposal'
ravel run --rundir my-study
ravel status --rundir my-study --write
```

For an explicitly authorized scripted experiment, set
`approval_mode: "scripted_yes"` and add `--scripted` to `approve`. The quotation
must describe the actual authorization. No expert review is inferred.

Version 1 specifications retain the existing one-attempt lifecycle for existing
operations. New `contrast`, `analysis-ir`, `routine-build`, `rivet-built`, `model-probe`,
`statistical-model`, `published-model`, `model-portfolio`, `likelihood-parity`,
`signal-template`, `stau-events`, `native-likelihood`, `eft-functions`,
`normalized-measurement`, `ratio-measurement`, `group-normalization`, `group-composition`, `derived-quantities`, `continuous-fit`,
`model-inputs`, `contur-import`, `finite-mc`, `model-tool-bridge`, `pdf-variations` and `routine-candidate` executions require
version 2 and the prospective review and bounded correction envelope in
[scientific review for adapter studies](science-review.md). Review actors and
their declared separation remain explicit; a scripted approval is not expert review.

All specifications share these fields:

```json
{
  "schema_version": 1,
  "mode": "quantities",
  "source": "Exact input/reference provenance, or an explicit synthetic control",
  "assumptions": ["State scientific approximations and unresolved evidence"],
  "max_seconds": 60,
  "approval_mode": "physicist",
  "task": {"contract": "quantity.json", "records": "fills.jsonl"}
}
```

Paths in the task resolve relative to the specification. Inputs, runtime files and
Ravel's implementation are hashed before approval and checked at execution and
completion. Large existing event files are bound in place instead of copied.
Do not modify those inputs. There is one supervised attempt, including a failed
attempt. `--resume` verifies a successful existing result without doing more
compute. A changed recipe or retry needs a new study. Processes are cleaned up
only within their owned process group. CHECK-IN 2 never authorizes more compute
automatically.

## Additional study operations

The following modes use the same plan, approval, execution and review lifecycle.
Their adapters validate the exact task and enumerate its input files before any
worker starts. A mode being available does not establish analysis-wide validation.

| Mode | Delivered operation | Evidence boundary |
|---|---|---|
| `model-portfolio` | Run the declared SModelS model/database portfolio while retaining model cross sections, branching ratios, lifetimes, prediction population and expected-sensitive selection | Database applicability, coverage and permitted combinations remain explicit; a simplified-model constraint is not detector-level reproduction |
| `signal-template` | Compile complete nominal and absolute signal variations into a pinned published workspace, preserving signal/control regions and shared modifiers | An explicitly declared compile-only source identity study may retain incomplete signal coverage; it cannot produce a new-model limit |
| `stau-events` | Project supplied calibrated features through an explicitly selected analysis package, with complete event accounting and grouped moments | Supplied features and arithmetic checks do not establish tau, trigger, fake or detector response; signed moments alone do not admit an MC likelihood |
| `native-likelihood` | Execute a pinned CMS card/ROOT model in its declared compatible native worker, including complete signal replacement where supplied | Runtime qualification, unchanged reference agreement and new-signal validation are separate requirements |
| `eft-functions` | Preserve admitted coefficient-dependent source functions and exact process mappings | Unsupported source syntax or missing used mappings are refused; static algebra is not a native fit |
| `normalized-measurement` | Evaluate an explicitly declared normalized signal-plus-background contrast with retained covariance and a bounded signal-strength fit | Approximate contrast inference retains the discarded normalization direction; it does not silently repair the published covariance or claim CLs |
| `ratio-measurement` | Compare an absolute ratio prediction with a supplied full experimental covariance, retaining numerator and denominator contributions and declared joint prediction uncertainty | Fixed-hypothesis Gaussian diagnostics use the declared covariance and optional linear uncertainty propagation; they do not establish a fitted likelihood, CLs or detector applicability |
| `group-normalization` | Normalize complete supplied histogram/event-counter group vectors by an explicitly fixed coefficient times N/sumW, preserving joint correlations and original native marginals | First-order Poissonized independent-group delta covariance; it performs no native acquisition, model validation or inference |
| `group-composition` | Reconcile complete supplied native-coordinate groups before exact rebinning, join original-event modes with one counter, and deliver an exact measurement-component slice with full cross-mode covariance | Supplied conditional group arithmetic; original acquisition, projection/model applicability and inference remain separately unqualified |
| `derived-quantities` | Construct source-defined ratios, efficiencies and asymmetries with a complete joint input basis, named variations and conditional covariance | Supplied covariance or explicitly Poissonized independent-group moments determine the propagated uncertainty; missing cross correlations cannot be inferred from marginal errors |
| `finite-mc` | Fit disjoint SR/CR counts jointly with an explicitly declared finite-simulation sampling law and retained zero-count or signed fixed-mark categories | Validity is conditional on that sampling law and supplied background; bounded diagnostic toys do not establish calibrated coverage or general treatment of adaptive event-generator weights |
| `likelihood-parity` | Compare fixed likelihood values and gradients at predeclared source-bound parameter vectors | A fixed-vector numerical diagnostic does not establish optimizer convergence, modifier independence or an exclusion limit |
| `continuous-fit` | Fit a supplied bin-integrated continuum and joint disjoint SR/CR transfer model under its explicit assumptions | The model requires independent numerical checks and calibration; it does not replace a published likelihood merely because the histograms look similar |
| `model-inputs` | Deliver a source-pinned static SLHA inventory, consistency findings and declared completeness | Diagnostic completion is separate from card acceptance; the diagnostic never authorizes generator execution or certifies a model |
| `model-tool-bridge` | Evaluate declared supplied-UFO processes at bounded phase-space points with pinned MadGraph, parameter card and runtime, retaining independent numerical witnesses | Native matrix-element consistency does not establish model-wide validity or detector applicability; this operation generates no collision sample |
| `contur-import` | Import a pinned retained Contur results database and export its original mode, point and pool quantities with explicit confidence conventions | Cached result import/export is not a fresh Contur inference or a new Ravel exclusion calculation |
| `reco-ntuple-routine` | Run a registered native SimpleAnalysis routine port on flat reconstructed ntuples through a supplied format descriptor (branches, energy unit, object-selection flags, ID and isolation flag-to-bit map, named weight branches); deliver raw counts, sumw and sumw2 per routine region | The branch and flag map is supplied data; equivalence to the routine's original object definitions and normalisation to a cross section and luminosity are separate steps |

Use each adapter's validated source contract for the full task schema. In
particular, a successful source diagnostic with a refused model disposition is
not a successful model validation. Preserve the findings in the result and in
the accepted review scope.

## Calculations, measurements, diagrams and manuscripts

These modes use the same `ravel plan`, `approve`, `run` and CHECK-IN 2 lifecycle.

| Mode | Use it for | Contract |
|---|---|---|
| `measurement` | Compare supplied Gaussian measurements with a prediction: goodness of fit, a signal-strength fit, or observed and expected 95% CLs | [Quantities and measurements](../../reference/quantities-and-measurements.md) |
| `literal-calculation` | Exact decimal arithmetic on a literal expression | [Calculations intake](../../reference/intake-and-challenges.md) |
| `eft-toolchain` | Run a supplied WCxf point through Wilson running, matching and basis translation, flavio predictions and an optional smelli likelihood | [EFT toolchain](../../guides/eft-toolchain.md) |
| `cosmology-solver` | Evaluate CAMB or CLASS matter power, Hubble rate and distances, or a Cobaya log-posterior, at listed parameter points | [Cosmology solvers](../steps/cosmology-solvers.md) |
| `feyn-graph` | Enumerate every Feynman diagram for a model and process and export SVG or TikZ drawings | [Model-bound diagrams](../../reference/model-bound-diagrams.md) |
| `feynarts-amplitude` | Build amplitudes with FeynArts and FeynCalc and export diagram PDFs | [Model-bound diagrams](../../reference/model-bound-diagrams.md) |
| Result templates (`ravel fill-template`) | Copy accepted values into a supplied HEPData-style YAML or JSON template, keeping its bins and headers | [Result templates](result-templates.md) |

| Mode | Use it for | Contract |
|---|---|---|
| `measurement` | Compare supplied Gaussian measurements with a prediction: goodness of fit, a signal-strength fit, or observed and expected 95% CLs | [Quantities and measurements](../../reference/quantities-and-measurements.md) |
| `literal-calculation` | Exact decimal arithmetic on a literal expression | [Calculations intake](../../reference/intake-and-challenges.md) |
| `eft-toolchain` | Run a supplied WCxf point through Wilson running, matching and basis translation, flavio predictions and an optional smelli likelihood | [EFT toolchain](../../guides/eft-toolchain.md) |
| `cosmology-solver` | Evaluate CAMB or CLASS matter power, Hubble rate and distances, or a Cobaya log-posterior, at listed parameter points | [Cosmology solvers](../steps/cosmology-solvers.md) |
| `feyn-graph` | Enumerate every Feynman diagram for a model and process and export SVG or TikZ drawings | [Model-bound diagrams](../../reference/model-bound-diagrams.md) |
| `diagram-analysis` | Pass enumerated diagrams to NDA width estimates and Diagrammatica code | [Model-bound diagrams](../../reference/model-bound-diagrams.md) |
| `feynarts-amplitude` | Build amplitudes with FeynArts and FeynCalc and export diagram PDFs | [Model-bound diagrams](../../reference/model-bound-diagrams.md) |
| Result templates (`ravel fill-template`) | Copy accepted values into a supplied HEPData-style YAML or JSON template, keeping its bins and headers | [Result templates](result-templates.md) |

## Compare Rivet output with HEPData

A comparison of a Rivet prediction with a published measurement runs three studies in order.

1. `analyze` with the `rivet` backend runs the routine on the supplied events. Its attempt
   directory holds the original `histograms.yoda` and `observables.json` with the requested
   observables, bin edges, values and units.
2. `source-tables` reads the measurement from its HEPData YAML record: the measured values,
   every error component and the published covariance or correlation matrix in a declared bin
   order. See [source tables](../../reference/source-tables.md).
3. `measurement` compares the two. Write `measurement.json` with the HEPData values as `data`,
   the Rivet prediction as `sm` and the published covariance as `experimental_covariance`, using
   the same `bin_ids`, representation and units. Add a prediction covariance as
   `theory_covariance` with `covariance_policy: "independent_theory_sum"` when one exists. Set
   `signal` to an explicit deformation, such as the prediction itself for a normalization shift,
   and run `inference: "goodness_of_fit"` with `signal_strength: 0`.

The `sm` goodness of fit (χ², degrees of freedom, p-value) is the data–prediction agreement,
and the fitted signal strength measures a normalization offset. A normalized measurement adds
its area constraint. Take the covariance from the HEPData record; the routine's reference file
supplies the binning.

## Compare with a published figure

`figure-comparison` digitises published figures, compares a result with a HEPData table, a
digitised series or another result, and draws parameter-plane figures and measurement overlays
on the official figure's axes, with a side-by-side panel. Its task is an ordered list of
operations, each with its own specification; later operations read earlier ones by name. Every
verdict is a machine comparison with a stated tolerance basis. See
[figures and comparison](../../reference/figures-and-comparison.md).

## Analyze supplied events

Set `mode: "analyze"`. The original three backends are retained, with an additional
closed compositional backend described below.

### Unmodified Rivet source

The `rivet` task has exactly `backend`, `routine`, `source_root`, `events`,
`metadata`, `runtime`, `observables`, `options` and `seed`, with optional `grounding`.
Both `rivet` and `rivet-built` accept `grounding` as a nonempty list of explicit
`{"path": "source-oracle.json", "sha256": "..."}` records. These bind external
source definitions, precision contracts and checking code into the actual stage
input census and are checked again before execution. Paths must be distinct regular
files without symlinks. Including a checker as evidence does not execute it or
establish the scientific truth of its assertions.

- `routine` is an unambiguous catalogue identity, such as
  `rivet:SYN_9003_I1145`. `source_root` must contain the pinned source,
  metadata, reference binning and literal assets at the catalogue revision.
- `events` is an existing HepMC2/3 ASCII file, optionally gzipped. `metadata` is
  JSON with `schema_version: 1`, `event_level: "hadron"`, two `beam_pdg` values,
  two `beam_energy_gev` values, ordered `weight_names`, positive `events`,
  `groups: "independent"` or `"correlated_event_number"`,
  positive `cross_section_pb`, and a `source` description. The first weight is
  explicitly nominal. The census checks serialized beams, units, identities,
  exposure and group moments. A hadron-level declaration is not verified
  hadronization or generator fidelity.
- `runtime` contains `python`, `executable`, `build`, exact `version`, a nonempty
  `artifacts` list of runtime libraries/modules/tool files, and explicit
  `environment`. The selected libraries and compiler should be included.
  Environment keys are bounded to path/library/compiler/SDK settings. Rivet must
  be version 4, YODA version 2. Source and runtime versions are recorded separately.
- `options` contains named upstream analysis options; use `{}` explicitly when
  none apply. `seed` fixes detector-smearing randomness. The adapter never uses
  `--ignore-beams`, skips events, silently clips weights or disables subevent
  grouping. Compilation uses one worker and unmodified routine source.
- Each requested observable declares `path`, `axes` (`name`/`unit` for each),
  `representation: "integrated"` or `"differential"`,
  `normalization: "absolute"` or `"normalized"`, and output `unit`.
  Every requested path must be delivered. Normalized means unit integrated area
  over the finite booked bins; an inconsistent upstream result fails. Normalized
  integrated units must be `1`; densities use inverse axis units, such as `1/GeV`
  or `1/(GeV*GeV)`. Exact global counters for every declared weight must match
  independent-group counts, sums of weights and group second moments.

The output preserves original YODA and exports continuous 1D/2D quantities.
Source-finalized Rivet density estimates use the separate
`quantity_kind: "native_density_estimate"`, `representation: "native"`,
`normalization: "absolute"` contract. The `native_density` declaration pins the
normalization source excerpt and reviewed source/API dependencies, identifies the
exact matching `/RAW` histogram, and declares integral, axis, RAW-weight and
optional group-width units. It requires `flow_policy: "retain_all"` and
`group_covariance: "not_supplied"`. Export requires reviewed YODA 2.1.3 text.
Every final density token, labeled signed error and undefined state is retained
alongside the RAW primitive moments and all finite/flow rows. These source-native
values retain their original normalization and units; integral, variance and
bin/event-group covariance remain unavailable. The portable table delivers the
full token population. Source conventions and physics applicability still
require separate review.

Source-native categorical and mixed axes use the distinct
[`native_categorical` contract](../../reference/native-categorical.md).
Literal string/integer labels, OTHER and continuous flow states, masks, native
signed errors and declared RAW objects are retained without transforms. A
weight-name/suffix mapping is a declaration, not an observed native weight census.
The closed YODA 2.1.3 serialization contract keeps group covariance unavailable.

Continuous one- and two-dimensional profiles use the
distinct `quantity_kind: "profile_mean"`, `representation: "mean"`,
`normalization: "absolute"` contract. Their dependent-variable unit is explicit;
the finalized mean and error must agree with retained raw running moments under
the serialization tolerance. No bin-width division applies. Transformed profile
estimates without that agreement and mixed continuous RAW moment/categorical profile transport remain
unsupported. Asymmetric errors are retained; bin covariance is not
invented. Finalized overflow normalization is left unspecified when it cannot be
reconstructed safely; raw flow is retained separately. A reference file supplies
binning, not automatically a usable measurement likelihood.

### Reconstructed-object selections

`backend: "native-selection"` requires `events`, `object_contract` and `selection`;
optional `reference` and `mapping` request decision comparison and likelihood
injection. Events are a JSON array with stable `event_id`, `group_id`, named
`weights`, `objects` collections (`electron`, `muon`, `jet`) and `met` (`pt`, `phi`).
Each object declares `pt`, `eta`, `phi`, `mass`, `charge` and `idbits`.

The object contract declares `schema_version: 1`, `level: "reconstructed"`,
`energy_unit: "GeV"`, `source`, unique `weight_names`, per-collection `flags`
(label to distinct single-bit integer), and a `response_evidence` path list.
No detector working points are inferred or aliased. The selection uses the
preserved native engine's `name`, explicit baseline `objects`, `signal`
requirements (`pt`, `eta`, `id` for every collection), ordered
`overlap_removal`, named `regions` with `var`/`op`/`val` cuts, and optional `btag`.
Undefined object-derived observables cannot pass cuts through zero sentinels.

The result retains every rejected event, region decision, weighted yield,
region overlap and group covariance. A reference must contain `source` and an
`events` list with exact `event_id`/`regions` decisions for the entire input
population. A mismatch is a failed delivered comparison, not a successful
physics result. An empty response-evidence list is allowed for engineering
controls but establishes no detector fidelity.

An optional mapping supplies a pyhf `workspace`, `poi`, `weight_name`, documented
`normalization` (`kind: "events_per_input_weight"`, `factor`, `source`),
`channels` (`channel`, `sample`, ordered `regions`, `role`), `omitted_regions`
with reasons and `mc_modifier`. Every POI-controlled sample, including control
regions, must be mapped. Overlaps, correlated-group off-diagonal MC covariance,
negative bins, and zero nominal yield with positive variance cannot be disguised
as independent Poisson/staterror bins. Absolute/shape nuisances need a new
model-specific template. Zero-selected bins remain precision-unresolved.

### Upstream SimpleAnalysis binary

`backend: "simpleanalysis"` requires `routine`, `source_root`, slim ROOT `events`,
`object_contract`, `runtime` and requested `regions`. The source check uses the
catalogue revision. The supplied executable needs a build attestation containing
`schema_version`, `source_revision`, `framework_revision`, `binary_sha256`,
`source_sha256` (selected source path to hash), `build_log`, `build_log_sha256`
and `description`. Runtime declares `executable`, `build_manifest`, dependency
`artifacts`, and `environment`.

The slim-object contract declares `schema_version`, `level: "reconstructed"`,
`energy_unit: "GeV"`, `source`, an `object_definitions` file, a `response_evidence`
list, `weight_names: ["nominal"]`, and `independent_events: true`. Inputs must have
unique `EventNumber` values and one nonzero nominal `mcWeights` value per event.
Upstream skips zero-weight events; this adapter refuses to hide that loss.
It runs the supplied routine without implied smearing and reconciles its ROOT
per-event contributions with its CSV summary and original event census.

A supplied build attestation is not an independently repeated build. The full
upstream framework requires AnalysisBase and dependencies that are not supplied
by this Python package. The release's ROOT transport tests are not proof of a
clean Mac installation or parity for all 79 routines. In particular, the
ordinary two-lepton candidate already needs MET significance, working-point
logic and dynamic overlap radii beyond the generic declarative subset.

The separate source-built route, `backend: "simpleanalysis-built"`, prepares and
runs a governed build before event reuse. Its build and event recipes keep
`set -e` while sourcing the pinned vendor setup, then restore `set -euo pipefail`
before tool probes, build commands or event execution. A failing setup aborts
before downstream operations. Source-bound vendor compatibility tests and a
successful environment qualification remain separate from native full-build or
event acceptance.

### Typed compositional cutflows

`backend: "analysis-ir"` consumes three regular JSON files:

```json
{
  "backend": "analysis-ir",
  "program": "program.json",
  "contract": "objects.json",
  "events": "events.json"
}
```

The object contract and complete event population have the reconstructed-object
semantics above. The program has `schema_version: 1`, a `name`, topologically
ordered `nodes`, and named `regions` whose ordered `cuts` refer to predicate
nodes. Optional `limits` bound `max_events`, `max_objects_per_event`, and
`max_pairs_per_event`; bounds are checked without truncation.

For example, a jet-multiplicity program is:

```json
{
  "schema_version": 1,
  "name": "two-jets",
  "nodes": [
    {"id": "jets", "op": "input", "collection": "jet"},
    {"id": "njet", "op": "count", "args": ["jets"]},
    {"id": "two", "op": "const", "value": 2, "unit": "1"},
    {"id": "pass", "op": "compare", "args": ["njet", "two"], "comparison": "ge"}
  ],
  "regions": [{"name": "two-jets", "cuts": ["pass"]}]
}
```

Nodes are typed expressions, never Python text. The compiler rejects mismatched
energy/angular dimensions, forward references, unsupported operators and cuts
that are not predicates. Available operations include object filtering,
ordered fixed or variable-radius overlap removal, sorting, leading-object
selection, OSSF pairing, invariant and transverse masses, MET quantities,
arithmetic and three-valued predicate composition. An undefined leading object
or empty pairing propagates as `null`; only `true` passes a cut.
`mt` includes the supplied visible rest mass and assumes massless invisible MET;
`mt_massless` retains the legacy convention with a massless visible object.
Both require a typed MET input as their second operand.

Every event, including rejected and zero/signed-weight events, retains node
values, object lineage and region decisions in
`outputs/attempt-1/analysis-witness/trace.json` for the first supervised attempt.
The summary includes cumulative cutflow counts, group moments, region overlaps
and weighted yields. A separate standard-library checker replays the serialized
program and full event population; a checker defect is a failed delivery. To
inspect a retained bundle independently:

```bash
ravel analysis-witness --bundle my-study/outputs/attempt-1/analysis-witness \
  --manifest-sha256 EXTERNALLY_RETAINED_MANIFEST_SHA256
```

Use the actual output directory recorded by the run, including its attempt
directory for reviewed studies. Without an externally retained manifest digest,
the checker reports self-consistency, not input authenticity. Complete retained
event agreement does not prove detector fidelity or equivalence on all possible
events.

## Complete paired event contrasts

Set `mode: "contrast"` and `task: {"input": "contrast-input.json"}`. This task
uses the same plan, actual approval, supervised attempt and status custody as
other scientific studies. Its input document requires exactly:

- `schema_version: 1`, `source`, `original_artifacts` and `census`. Every source
  pin has `path` and lowercase hexadecimal `sha256`; nested paths resolve
  relative to the contrast document. The census has `kind: "original_event_census"`
  and complete `records` with `event_id`, `group_id` and `shard_id`.
- `coupling: {"kind": "same_source_groups", "evidence": "..."}`. This is an
  explicit declared coupling basis tied to retained source bytes, not an
  independently established detector or systematic relation.
- `quantity`, using the quantity contract with normalized `in_range` or
  `all_events` scope, explicit axes, bin volumes and named weights.
- `arms`, each with a distinct `name` and pinned `records` file. Each original
  event must occur exactly once in every arm with identical group/shard IDs,
  explicit named `weights`, and zero or one `fills`. Empty fills represent
  rejection. A missing rejected row is an error, never an implicit zero.
- `contrasts`, each with a safe unique `id`, and `baseline`/`candidate` objects
  containing declared `arm` and `weight` names.
- `uncertainty_model: "poissonized_independent_groups"` or `"fixed_iid_groups"`.
  The latter needs at least two independent groups and uses `G/(G-1)`, with
  groups counted before arm expansion.

Arm-specific weights and fills may both change. The worker transports the joint
group moments, reports each normalized arm, the candidate-minus-baseline
difference, and the baseline/candidate cross covariance. It does not discard
that cross covariance to assume independence. `in_range` is a unit-area shape
over finite exclusive fills; `all_events` is a quantity per weighted input event
whose area can differ from one. Density covariance scales with the volume on
both axes. Negative event weights remain signed.

`contrast-quantities.json`, `contrast-result.json`, per-contrast producer claims
and independent numerical-witness receipts retain the complete calculation.
A failed independent arithmetic check forces a failed result. Plots read the
reported central values and covariance without renormalizing. Zero-selected
bins retain their central values and explicitly unresolved precision; a zero
MC variance is not an upper bound on unseen acceptance. This is first-order
conditional MC covariance, with no inferred nuisance covariance, coverage,
physics certification or causal explanation of a discrepancy.

## Statistical inference engines

Five modes evaluate statistics on supplied numbers and write `inference.json`:
`prescribed-statistic` (the statistic a request prescribes, as the primary result, with CLs
alongside on request), `formula-grid` (declared formulas on a parameter grid),
`coupling-morphing` (polynomial coupling dependence from several runs),
`search-statistics` (signal, control and validation regions in pyhf) and
`differential-likelihood` (a measured spectrum with full covariance and signed signals). Their
task is `{"input": "<document>.json"}` and they require version 2. `ravel inference example`,
`check` and `spec` prepare the study. See [inference engines](../../reference/inference-engines.md).

## Quantity transport and measurement inference

See [quantity and measurement contracts](../../reference/quantities-and-measurements.md).
Signed/multiple weights, correlated subevents and disjoint shard merging are
executable operations. Supplied Gaussian measurements support goodness of fit
and Spey's observed plus five expected 95% CLs crossings. Covariance, theory
predictions, bin units, normalization constraints and overlap policy remain
explicit inputs. A histogram is never converted into counts to manufacture a fit.

## Model, classifier, lifetime and additional domains

See [domain operations](../../reference/domain-adapters.md) for exact tasks using
`mode: "domain"`. Available operations include safe static UFO checking, EFT
interference reconstruction, ONNX inference, finite-cylinder decay probabilities,
censored lifetime reweighting, nuclear per-event normalization, neutral straight
line forward acceptance, and supplied neutrino flux folding. Those bounded
operations are not full experiment adapters. FeynRules generation, detector
calibration, charged beam optics, medium evolution and neutrino interaction
simulation are not implicitly supplied.

The `model-probe` domain executes one explicitly bounded fixed-phase-space
matrix-element check using a supplied native runtime. It has its own strict
parameters, analytic oracle and applicability statuses. Planning inventories
its runtime and inputs without starting MG5. See the exact operation and
evidence limits in [fixed-phase-space probes](../../reference/domain-adapters.md#fixed-phase-space-matrix-element-probe).

## Source builds and statistical construction

The `analyze` task can select `{"backend": "routine-build", "input": "routine-build.json"}`.
This builds an explicitly supplied source capsule with declared tools and an
exact recipe. Planning inventories the source and dependencies; compilation and
the bounded probe execute only in the approved worker. The
[routine-build contract](../../reference/routine-build.md) describes catalogue,
external and generated source capsules, output binary custody and unsupported
framework recipes. A build receipt establishes retained source/build agreement,
while event semantics, detector response and requested-output closure require
their own evidence.

The `rivet-built` analysis backend consumes an exactly verified build receipt and
plan, declared existing events/metadata, the bound Rivet Python/version, routine,
requested observable census, options and seed. It loads that verified plugin;
it does not rebuild it or silently choose a catalogue routine. Continuous
histograms retain their declared geometry. An explicitly requested
`quantity_kind: "scalar_counter"` uses no axes, integrated representation and
absolute normalization. Its scalar report retains native final values/errors and
RAW Counter moments separately, without a bin-index plot or invented covariance.
This is a built-Rivet observable variant; the shared quantity kernel remains a
continuous-bin interface. See the [built-plugin contract](../../reference/routine-build.md).

`mode: "statistical-model"` constructs the implemented Poisson model from an
explicit input specification, rather than replacing a published signal template.
Its task has `input`, a finite list of `profile_points`, and at least two complete
physical parameter maps in `comparison_points`. The worker retains the constructed
workspace, model settings, fit/profile diagnostics, local identifiability and an
independent likelihood witness. Scientific assumptions, data use, nuisance
relationships and calibration remain explicit. The implemented code-1 model
family supports SR/CR, ABCD and correlated auxiliary constraints.
A converged fit does not establish identifiability, calibration or physics validity.

`mode: "published-model"` is a separate numerical route for a supplied official
workspace and declared inference settings. It preserves the original workspace
and evidence lineage under the same prospective review and attempt budget.
Published-model evaluation and constructed-model diagnostics have different
scientific assumptions; neither supplies missing experimental response evidence.

Reviewed metadata discrepancies require a selected `source_reference_acknowledgment`
with a `reviewed_registry` file pin. The errata registry binds the archive, member
pair, affected metadata pointer, literal value and external attribution
assertions. Its evidence files join the ordinary approval input census. Ambient
configuration cannot authorize an exception. Missing reviewed errata refuse
with `missing_reviewed_erratum`; archive and member bytes remain unchanged.

Event cutflow diagnostics consume a supplied reviewed definition. Its predicate
population, ordered flows, unavailable decisions, membership checks, source-row
mapping, normalization population and luminosity are inputs. The trace header
binds the definition; missing definitions refuse with `missing_cutflow_definition`.
Use the data-only comparator after a trace exists:

```bash
python -m ravel.physics.compressed_validation --trace trace.jsonl.gz \
  --definition reviewed-cutflow.json --definition-sha256 <sha256> \
  --out comparison.json --format json
```

The generic schema is `src/ravel/data/source_records/records.schema.json`.
Native trace production uses `--validation-definition` and
`--validation-definition-sha256` within the existing supervised launch plan.
The existing native planner selects `[ravel.native].cutflow_definition =
{path, sha256}` when the selected analysis package declares the event-trace
helper output. The definition must bind that package's selection source bytes.
The planner includes every definition, reference and review dependency in each
stage's approval input census. Missing records refuse during planning, and a
definition supplied for a package without a trace output is refused.
Selection and normalization records enter that census before approval. Cutflow agreement remains diagnostic; it grants no detector or
statistical certification.

For a read-only census of source, build, event, response, reference and inference
evidence, use `ravel analyses assess --specification analysis.json [--out report.json]`.
The [analysis-admission contract](../../reference/analysis-admission.md) defines
the complete output basis and source-bound comparisons. Its result can remain
blocked while a partial calculation is executable. Assessment grants no compute
approval or scientific certificate.

## Reproducible engineering controls

From a source checkout after the complete Python setup, including its development tools:

```bash
python scripts/validation/run_science_controls.py --out controls
# Inspect the generated proposals. To execute a fresh set after authorization:
python scripts/validation/run_science_controls.py --out controls-approved --execute \
  --assent 'Actual authorization for these scripted synthetic controls'
```

The script exercises analytic fixtures through the same supervised lifecycle.
It keeps expected EFT-reference and bounded-root failures. The separate
`run_rivet_controls.py` requires `--cases controls.json --out controls`. Its version 1
manifest supplies every synthetic kinematic control (`name`, `energy`, `kind`,
`observable`, `unit`, `normalized`, `grouped`, `expected`); also supply
`--runtime runtime.json --source <pinned-checkout>`. There is no built-in routine roster.

Version 2 selects arbitrary complete scientific specifications and a requested report:

```json
{"schema_version": 2, "cases": [{"name": "fictional-control", "spec": "science.json", "expected": "passed"}],
 "report": {"path": "reports/checks.jsonl", "format": "jsonl"}}
```

Spec paths are resolved relative to the manifest; each specification supplies the study,
parameter grid, datasets, runtime and resources of its operation. Reports support `json`
and `jsonl` at a supplied relative output path. Preparation launches nothing.
`--execute --assent '<actual authorization>'` uses ordinary plan, approval and supervised
execution, including method admission. Every failed or unexecuted case remains in the
population. Missing cases, specs or report selection raise `MissingControlInput` with
reason `missing_control_input`. These controls measure neither paper fidelity nor
autonomous scientific success.

Measurement diagnostics use supplied covariance errors, a ratio panel and supplied
prediction bands when available. A zero SM denominator stays a gap. These are
linear quantity diagnostics without a published figure target; a paper comparison
still requires the existing figure contract, matched axes and independent visual
review. No experiment luminosity or detector-response uncertainty is invented.


### Supplied group normalization

Use mode `group-normalization` with a version 2 scientific specification and
task `{"schema_version": 1, "input": "normalization-contract.json",
"contract_sha256": "<exact SHA256>"}`. The existing `ravel plan`, `approve`,
`run` and review lifecycle applies. The task inventories the outer contract and
every size/hash-pinned original acquisition contract, complete acquired record,
routine definition, trace and RAW source before approval. The retained v2 record
is supplied data; there is no dependency on a native acquisition implementation.

The contract declares every weight/component/finite/flow bin, the independent
single-subevent group convention, signed or nonnegative weights, positive or
nonzero signed normalization denominator, and fixed conditional source coefficients.
All rejected and zero-weight encounters must match the original file-hash/ordinal
population. An event counter enters the full joint basis once per event and weight,
including its cross-output and cross-weight correlations. Inputs are integrated
quantities. Fixed coefficients have no inferred theory error; finite density
conversion requires the explicit `finite_slice` callable and exact widths.

The fresh `outputs/attempt-1/group-normalization/` directory contains
`group-normalization.json` with the complete original groups, basis, Jacobian,
covariance, arithmetic enclosure and native origins, and `normalized-joint.json`
with the existing supplied-covariance component schema. An ensuing
`derived-quantities` contract must pin both artifacts and original source/geometry,
use identity component scales and declare its complete output census. Linearized
group gradients are not central event contributions and must not be relabelled as
`independent_group_moments`; a second xs/sumW factor would double normalize.

Native acquisition qualification remains false in the result. The operation does
not establish trace correctness, detector/model applicability, independence from
experimental data, native marginal-error parity, sparse-event calibration or a
statistical inference. Nonrepresentable central values or derivatives refuse,
while representable subnormals and exact zero/cancellation remain allowed.


### Same-event composition and coordinate rebin

Use mode `group-composition` with a version 2 scientific specification and task
`{"schema_version": 1, "operation": "measurement-components", "input":
"component-contract.json", "contract_sha256": "<exact SHA256>"}`. Operations
`coordinate-rebin` and `same-event-compose` are also admitted through the same
ordinary planning, approval, worker and review lifecycle. The closed nested
contracts bind all original normalization/acquisition/trace/RAW inputs, source
fill definitions, target geometry and the measurement basis before approval.
There is no import of a private native observer or event runner.

A coordinate rebin first reconstructs every original finite and flow group from
its complete source-coordinate trace, effective selected weights and exact fill
site. Only then does it assign the original coordinates to the new half-open
finite and flow bins. The result keeps a distinct source-coordinate-rebin origin;
it does not rewrite native marginal bins, errors or a native acquisition record.
Both axis and units must match. Exact and nextafter arbitrary-coordinate controls
are separate from physical native events: a published rounded angular upper edge
above pi is not an achievable native deltaPhi boundary.

Composition requires exactly identical ordered input-file-SHA/encounter populations,
selected native weight mappings and whole-event counters in every arm. It joins
complete finite/flow group vectors across 2–8 modes and appends one event counter
per selected weight to the union basis. The declared independent-single-subevent,
uncentered Poissonized model then supplies cross-mode/output/weight covariance.
Fixed cross-section coefficients remain conditional. Numerical source marginals
remain pinned separately; a marginal error never creates a missing cross term.
The complete union, rather than each arm alone, must fit the bounded covariance
budget of 768 coordinates, 4096 groups and 25 million coordinate-pair/group terms.

The measurement-components contract pins an exact measurement-basis document,
the composition contract, complete numerator and denominator mappings and an
explicit identity-only unit-notation join. The operation divides by each exact
finite bin width once and refuses approximate geometry joins. Its fresh
`outputs/attempt-1/group-composition/` directory retains `group-composition.json`,
`normalized-joint.json` and, for this operation, `measurement-components.json` with
both component vectors and their complete joint covariance. The existing
ratio-measurement component contract can consume these vectors, but any full SM
joint covariance and independence from experimental data must be separately
supplied and declared. No theory covariance, zero SM covariance or inference is
created automatically. All operations retain `native_acquisition_qualified: false`,
`experimental_independence: null`, `physics_validated: false` and no inference.


### Explicit Rivet cap-zero argument

Rivet tasks may declare the optional `native_weight_cap: 0` field. Only literal
integer zero is admitted. This opt-in requires a version 2 scientific study,
including for the initial `rivet` route. It adds exactly `--weight-cap 0` to the
event command; the nominal weight remains the first explicitly supplied metadata
weight name. The field is unavailable to other backends and accepts no arbitrary
CLI passthrough. Absence preserves the existing command and output schema.

Opt-in delivery retains `native-dispatch.json` with the declared analysis options,
original native CLI and actual launched command (including the existing loader
wrapper for `rivet-built`), the event-file hash and the cap-zero declaration. The
result and successful build-reuse record bind its exact bytes. This records
argument dispatch, with `native_effective_weights_observed: false`. Effective
native weights, cap semantics, projection behavior and complete trace/RAW
agreement still require their separately approved source/API experiment. No
acquisition, covariance, inference or physics qualification follows from these
argument declarations or portable routing controls.

## Named PDF-member transport

The [PDF variation operation](pdf-variations.md) transports explicitly supplied
counterterm-free tree-level parton records through the complete named NNPDF replica
set with a fixed supplied response. It preserves PDF-member dispersion and nominal
finite-MC covariance separately. Its first installed capsule and grid-knot protocol
need actual native qualification; portable controls do not establish a physics result.


## Development admission smoke

Before preparing an expensive new adapter campaign, exercise one inexpensive actual
public lifecycle with synthetic inputs: plan, scripted development approval within
its existing authority, supervised run, completed receipt and status or pending-review
packet. Use a distinct supervisor log outside every declared scientific output tree.
Retain failures and actual imported source identities. Mocked authorization or a
direct adapter call alone does not cover this route.

This engineering fixture does not waive numbered scientific checks, grant a native
lease or qualify physics. Native generation or another substantial workload still
requires its own bound approval. Frozen experiments retain their original source
and cannot inherit later smoke-test results.


## Retained original-LHA shower

The prospective `retained-shower` mode consumes one digest-pinned
`retained-shower-contract` through `task={input,contract_sha256}`. Its closed source
inventory names the supplied executable, actual wrapper source, original LHE,
nominal unmerged run card, fresh shower card, exact reviewed initialization-report
schema, producer evidence, and complete native runtime inventory. The ordinary
version-2 study, approval, supervisor and worker own execution and resource limits.
This mode performs no build, hard-event generation, detector simulation, analysis
or likelihood calculation. It showers every declared original event once and
retains the original-LHA sidecar, verified HepMC stream, initialization report,
source identities, transport verification and separate initialization checks.

`native_event_io.shower_original(..., initialized_settings=...)` and its
`shower-original --initialized-settings` command add an optional fresh output to
the existing original-LHA transport path. The default preserves the previous
command and report. Publication requires a clean child exit, full original-event
transport, a bounded strict JSON report with the literal actual request, and an
initialization-only completion marker. Partial files remain retained on failure.
The adapter additionally verifies the exact reviewed schema, finite values,
ordered eight particle records and full channel census, supplied compiled-source
identity, declared post-init getter values, and an unchanged read-only RNG state.
An initialization report does not mean event generation finished. The producer's
claimed PID does not authenticate the loader or replace actual source/binary/runtime
qualification and independent review. Supplied producer evidence must be reviewed
in its actual scope before interpreting a native result.

The contract permits up to 20,000 complete nominal unmerged events and one worker.
Declared bytes and free-space floors are pre/post checks, not a disk quota or peak
memory measurement. Thread fields are explicitly one. Signed and zero original
weights remain source data, and duplicate original event content refuses transport.
The conditional shower establishes neither missing historical shower settings nor
model applicability, cross section, selected efficiency, covariance law, correlated
theory errors or an experimental constraint. Such downstream operations require
separate exact source/event contracts and reviews. Portable controls mock the native
producer while exercising actual planning, worker, publication, parser and repeat
refusal. Native qualification still requires the source-bound same-seed initialized
report enabled/disabled comparison and exact original event/sidecar equality.

The initialized-settings reader couples strict JSON to the digest of one unchanged regular descriptor. It reads at most 1MiB plus one byte, rechecks the descriptor and pathname including timestamps, and is reused for producer publication and adapter consumption. This bounds the read even when the file grows or is replaced during access.


The prospective version-2 `model-sources` mode exports the complete supplied source inventory into a typed stored bundle with member hashes/modes, including empty members. See [model-source contracts](../../reference/model-sources.md). Generic scientific output nonemptiness and existing review gates stay strict; source exports establish no provider execution or model validity.

The version-2 `initialized-settings-qualification` mode composes the existing retained original-LHA runner for one compile and four32-event same-seed observer checks. See its [reference](../../reference/initialized-settings-qualification.md). Source controls do not establish compilation, settings values or physics validity.

### Conditional BSM component covariance in ratio measurements

For `ratio-measurement` with `prediction.kind=numerator_denominator`, an optional
`bsm_component_covariance` retains the supplied joint numerator/denominator MC
covariance while conditioning on the literal SM central values. Its exact ordered
coordinates are all `bsm_numerator/<bin_id>`, then all `bsm_denominator/<bin_id>`;
`coordinate_units` must match the two component vectors. Supply the complete
finite symmetric matrix, a source, `method=first_order_delta_method`,
`experimental_independence=declared_independent`, and
`sm_treatment=conditional_fixed_central_no_theory_covariance`. This field and
`joint_component_covariance` are mutually exclusive. Unknown SM or correlated
theory uncertainty remains unknown; the input is not padded with an inferred
SM covariance.

At fixed signal strength, the prediction is `(SMnum + mu*BSMnum)/(SMden + mu*BSMden)`.
Both BSM derivatives and all cross-bin and numerator/denominator covariance terms
enter the first-order propagation. The existing positive or signed contribution
policy, positive final denominator over the declared domain, full experimental
covariance, exact basis/units and prospective version 2 review remain required.
At mu zero the BSM covariance contributes zero and the literal SM baseline stays
unchanged. The result is a conditional fixed-hypothesis Gaussian diagnostic;
source applicability, prompt-lepton control contamination, MC sampling calibration,
theory covariance, a fitted likelihood and CLs limits require separate evidence.

The [HS3 likelihood adapter](../../reference/hs3-likelihood.md) admits pinned supplied model graphs and complete bounded evaluation points through the ordinary version-2 lifecycle. Native ABI and numerical model equivalence require separate qualification.

The [complete-workspace comparison](workspace-combination-study.md) and [retained initialized-settings verification](initialized-settings-retained.md) use the same version 2 lifecycle and preserve failed original results.

### Complete semi-visible-jet recipe construction

Use schema2 mode `svj-recipe` for a complete supplied ATLAS non-resonant Run2 parameter/scenario grid, with an exact original `goal_binding`. The pure worker reuses existing generation planning, supplied-event analysis intake, same-event detector response, full signal templates and conditional inference preparation. It retains every prepared/blocked cell and unresolved fitted bin. No events or fits are run and the original task stays incomplete. See [SVJ study recipes](../../reference/svj-study-recipes.md) for closed inputs, resource bounds, ordered-shower prerequisite and MC/applicability requirements. Each future child requires its own ordinary approval and qualified inputs/runtime.

## Original EasyScan framework and programme chains

The `parameter-space-sampling` mode wraps a supplied schema-2 scan contract and source-bound EasyScan CLI, retaining raw programme calls, table/chain/weighted populations, supplied plots and source discrepancies. The contract supplies its identity, parameters, mappings, workspace population, resources and JSON/CSV table export; missing inputs receive a typed reason before external inspection. See [the complete native contract](../../reference/parameter-space-sampling.md). This requires schema2, actual original inputs/runtime and ordinary approval; source context does not run a sampler or establish engine/physics/convergence validity.


### Optional symbolic evaluation

Use ordinary schema2 mode `symbolic-evaluation` for reviewed, source-bound Wolfram/FeynCalc scripts and the original external HEPTAPOD symbolic-to-Python converter. `ravel symbolic-evaluation inspect --input request.json --input-sha256 SHA256` checks complete declared prerequisites without importing the required engines or launching a kernel. The task is `{input,input_sha256}`. Bind the original question, executable/application metadata, complete provider/script/dependency trees, exact backend files, result/marker populations, variables, units, conventions and aggregate resources. Existing approval and Check-In2 review remain required. Complete formulas, complex pairs and failed/unissued entries reach ordinary result/report files; no physics correctness, numerical equivalence or original-catalogue completion is inferred. Missing installed Wolfram/SymPy is a prerequisite; the adapter installs nothing and edits no configuration. The source API and `docs/reference/symbolic-evaluation.md` describe the complete contract.

Additional registered studies:

- `mpi-observer` qualifies a multiple-parton-interaction observer on retained LHE events. It draws no MPI inference.
- `mpi-paired-effect` contrasts paired runs with multiple-parton interactions on and off, after initialized-settings qualification.
- `likelihood-profile-probe` replays a retained conditional likelihood profile under two explicit minimizer protocols.
- `likelihood-candidate-check` verifies retained conditional-profile candidate vectors without a refit.
- `likelihood-step-refinement` repeats finite-difference likelihood checks at refined steps. It runs no optimizer.
- `joint-qualification` qualifies analytic-source joint models and runs full-nuisance fits.
- `generation-reconciliation` compares a declared physics intent with supplied MadGraph proc, run and param cards.


## Delivery normalization and event accounting

Science `event-production` checks the complete LHE before any shower dispatch.
`model-events` installs a source-bound `lhe_check` guard inside its admitted
integrated LO/NLO shower launch, and checks the generated LHE again as a
postcondition. Malformed or truncated events, undeclared weight signs, and
available card mass/decay inconsistencies refuse. External states must match the
card mass within the tolerance or three widths; intermediate resonances use the
header run card's `bwcutoff` window (the generator default of 15 when undeclared),
and the record states which window applied. These checks establish event
integrity under the supplied contract; native shower and physics qualification
remain separate.

Delivery producers write machine findings under `check_results` and retain
`outputs/delivery-checks.json`. The shared producer interface is
`ravel.validation.delivery_checks.check_delivery(rundir, pack)`. A pack can declare
`deliverables`, each with its `path`, `absolute_yield`, and pinned
`normalization_ledger`, `figure_comparison`, or `counting_inputs` inputs.
A figure pin names an ordinary `figure-comparison`
task, including the explicit source transformations and tolerance basis. An
absolute yield without its full source-backed ledger is `missing_input`;
missing order, PDF, BR or filter semantics are never filled with assumptions.
The pack consumer must refuse severity A failures and missing normalization
inputs for absolute yields. Normalization parity rows retain expected and
observed bins and factor diagnoses. Optional independently observed factor rows
localize disagreement within the chain rather than proving its physics.

`binned_values` carries optional per-bin or top-level `sumw2`, covariance,
normalization and provenance. The template reader retains covariance. Columnar
histograms are stamped normalized; partition merges refuse finalized outputs,
even when their numerical scale is one. `columnar-partial` is an additive merge
kind. Reconstructed routine outputs include `binned-values.json` with explicit
region-index edges and an unnormalized stamp. Root-stream report writers also
emit MC projections in `binned-values/` for a whole delivery, retaining covariance
and named weights; one partition's public record carries no projections. These
convenience files do not widen the existing blinded DATA evidence roster.

A columnar task can use `inputs: {"dataset": {"path": "dataset.json", "sha256":
"..."}}` and `normalization: {"mode": "dataset"}`. The dataset uses the existing
root-stream schema and complete membership authority. Each MC sample retains
its original full denominator, cross section, luminosity, filter and k factor.
Local checksums and entry counts are verified; `root://` members use uproot with
recorded declared checksums, without a claim of remote byte checksum verification.
DATA requires the original root-stream blinding route. A cross-section source
can instead be `{"cross_section_result": {"path": "cross-section.json",
"sha256": "..."}}`; the consumer checks the result kind and copies its order,
PDF and production basis.

Use `ravel check:event_accounting --spec accounting.json --out accounting-check.json`
for count and signed-weight moments. The version-1 document has `input` and
`output` rows containing `count`, `sumw`, `sumw2`, `positive`, `negative`, and
`zero`, plus a `transformation`. Supported laws are `identity`, `scale`
(`weight_scale`), `selection` (independently observed `rejected` moments), and
`selection-and-scale` (both). Unknown laws refuse. Agreement of these moments
does not prove event identity or physical shower association.

Pyhf and search outputs retain computed boundary and MC-adequacy alarms. Counting
outputs additionally retain a bounded exact count-ordered Poisson CLs reference
when the observation is an integer, background is known, and signal is positive.
Its finite-lattice `coverage` field states the fixed truth and omitted-tail bound.
It is an independent reference, not a replacement for the primary asymptotic
qtilde result or a certification of general likelihood coverage.

The pre-shower guard also runs at scoped-generation, retained-shower and weighted
LHE entry points. Integrated generation and shower reentry bind the original
supplied LO/NLO method source before installing the guard. Unsupported source
interfaces refuse; inert fixtures do not qualify an installed native toolchain.

### Supplied calibrated selection packages

The `stau-events` compatibility mode now consumes a general calibrated-event projection contract.
Its input JSON supplies `analysis_package: {path, sha256}` for the manifest, plus `output` with
`prediction`, `contract`, `decisions` filenames and `format` (`json` or `jsonl`). Region order,
state validation, response-component requirements and era semantics come from the selected
source, never a built-in channel population. The adapter retains original generator denominators,
branching/filter conventions, correlated groups and all absolute variation streams. Every package
member enters science input commitments; changing any member invalidates reuse and approval.
Reference comparison and native detector qualification are separately admitted jobs. A projection
continues to report `physics_validated: false` and does not grant finite-MC likelihood admission.

For a supplied parameter population, `stau_adapter.project_contract` takes `study_id`,
`parameter_points`, `datasets`, and `output`. Each point supplies `parameters`, a named `dataset`
and its complete projection `document`; datasets provide the original event records. Output
supplies `format` (`json` or `jsonl`) and a new `path`. Parameter values label the supplied event
predictions; the adapter never infers model-dependent event changes from those labels.
