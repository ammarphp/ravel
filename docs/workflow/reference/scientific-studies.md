# Scientific studies with supplied events and models

This route executes **existing inputs** under a concrete, byte-bound proposal.
It adds Rivet and reconstructed-object analysis, quantity transport, supplied
Gaussian measurement inference and bounded model/classifier/lifetime and topology-efficiency operations.
It does not generate a collision sample or certify a paper reproduction.

## Install and start

Python 3.10–3.12 is supported by the package. Choose the extras needed by the task:

```bash
# From the repository checkout, in a dedicated Python 3.12 environment
python -m pip install '.[science,measurement,classifier,replay]'
```

`science` provides figures and ROOT transport, `measurement` adds Spey,
`classifier` adds ONNX Runtime, and `replay` supplies pyhf for a mapped likelihood.
Rivet and upstream SimpleAnalysis remain separately installed native dependencies.
The Rivet worker can use its own Python interpreter, including a newer Python,
without changing the Ravel interpreter or the user's installed toolchains.

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

## Analyze supplied events

Set `mode: "analyze"`. There are three backends.

### Unmodified Rivet source

The `rivet` task has exactly `backend`, `routine`, `source_root`, `events`,
`metadata`, `runtime`, `observables`, `options` and `seed`.

- `routine` is an unambiguous catalogue identity, such as
  `rivet:ATLAS_2013_I1234228`. `source_root` must contain the pinned source,
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
Rivet 4 finalized density estimates require a matching raw histogram, preventing
an extra width division. Arbitrary estimates, profiles and categorical quantities
need a distinct adapter. Asymmetric errors are retained; bin covariance is not
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

## Reproducible engineering controls

From a source checkout with the optional dependencies and `test` extra:

```bash
python scripts/validation/run_science_controls.py --out controls
# Inspect the generated proposals. To execute a fresh set after authorization:
python scripts/validation/run_science_controls.py --out controls-approved --execute \
  --assent 'Actual authorization for these scripted synthetic controls'
```

The script exercises analytic fixtures through the same supervised lifecycle.
It keeps expected EFT-reference and bounded-root failures. The separate
`run_rivet_controls.py` takes `--runtime runtime.json --source <pinned-checkout>`
and prepares six ATLAS/CMS controls with matched beams. Neither harness measures
paper fidelity or autonomous scientific success.

Measurement diagnostics use supplied covariance errors, a ratio panel and supplied
prediction bands when available. A zero SM denominator stays a gap. These are
linear quantity diagnostics without a published figure target; a paper comparison
still requires the existing figure contract, matched axes and independent visual
review. No experiment luminosity or detector-response uncertainty is invented.

[The supplied-data control report](../../../evidence/audits/2026-09-26-scientific-studies/README.md) separates
executed checks, retained failures and capabilities that still need validation.
