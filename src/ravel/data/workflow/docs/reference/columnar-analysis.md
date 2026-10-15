# Columnar reconstructed-event analysis

`columnar-analysis` applies a declared selection to reconstructed or parton-level events and
delivers binned yields, cutflows and provenance. It reads Delphes ROOT files, flat or
PHYSLITE-like ntuples and LHE files. The selection is a JSON recipe, not code: objects, overlap
removal, isolation, object efficiencies, observables, regions, histograms and systematic
variations. The histograms are `binned_values` documents that `ravel fill-template` and the
statistics modes read directly.

Use it when an analysis has no public Rivet or SimpleAnalysis routine and the selection can be
stated from the paper (step 4, Option C), or for any supplied-event study that needs a cutflow
and histograms. When a step cannot be stated as a recipe, use the governed authored step
(`docs/reference/authored-analysis.md`).

## Running a study

The study is planned, approved and run like any other science mode. The task is:

```json
{"recipe": "recipe.json",
 "format": "delphes",
 "inputs": ["signal-1.root", "signal-2.root"],
 "normalization": {"mode": "cross-section", "cross_section_pb": {"production_receipt": "production-receipt.json", "pointer": "/sigma/value_pb"},
                   "cross_section_source": "generator cross section from the production receipt",
                   "luminosity_ifb": 139.0, "luminosity_source": "integrated luminosity of the analysis",
                   "sum_of_weights": "all-input-events"},
 "chunk_size": 100000,
 "detector_card": "delphes_card.tcl",
 "analysis_spec": "analysis-spec.json"}
```

- `format` is `delphes`, `nanoaod`, or a path to a supplied format descriptor.
  The packaged descriptors and public record identities are described below.
- `normalization` is `cross-section` (σ × L / sum of weights), `event-weights-in-pb` (the event
  weights already carry the cross section) or `none`. The cross section is a number with its
  source, `{"lhe_init": true}` for the LHE header, a pointer into a production receipt,
  `{"production_receipt": path}` for the receipt's sigma block, `{"normalization_ledger": path}`
  or `{"cross_section_registry": request}`. A ledger, directly or embedded in the receipt, gives
  sigma x k as the cross section and the branching fractions times the filter efficiency as the
  factor; a declared `factor` beside a ledger is refused.
- `detector_card` and `analysis_spec` are optional; see below.

Planning compiles the recipe, loads every efficiency map and checks every branch the recipe
reads in every input file, so a wrong branch name or a missing collection stops the study before
approval. The worker processes the files as partitions of one sample, merges them and writes:

- `columnar-analysis/histograms/<name>.json`: one `binned_values` document per histogram and
  systematic variation (variations end in `__<variation>`);
- `columnar-analysis/cutflow.json`: every region's ordered cuts with raw counts, sums of weights,
  sums of squared weights and normalised yields;
- `columnar-analysis/analysis-result.json`: every sum, the normalisation and its sources, the
  Monte Carlo precision of each bin, efficiency-map counts and the provenance (input, recipe,
  descriptor, map and detector-card hashes, and the engine source hash);
- one figure per one-dimensional histogram, with natural-language axis labels.

## Format descriptors

A format descriptor says where each physics field lives in a file. No branch name is written in
code. Each collection declares `pt`, `eta`, `phi` and `mass` (a branch or a fixed value with its
source) and any other fields; `met` and `event` fields are one value per event; `scale` converts
units (for example MeV to GeV); `variations` rename branches for systematic trees. LHE
descriptors select particles by PDG id and status, and the missing momentum is the vector sum of
the declared invisible particles.

`ravel root-schema --input FILE --draft` inspects a ROOT file without writing anything and
drafts a descriptor and a weight contract. It lists every choice it cannot read from the file,
such as a missing mass branch, an energy unit or which of several weight branches is the
generator weight. Review the draft before using it.

## The recipe

A recipe has `schema_version: 1` and `kind: columnar-analysis-recipe`, and these sections:

- `weights`: the generator weight field (or `null`) and further weight factors.
- `objects`: ordered steps. A step defines an object from a collection (`from`, `select`), a
  subset of an object (`from_object`), or a union; or it is `overlap_removal` (remove objects
  within ΔR of another collection, the cone may depend on the object), `isolation` (a new field
  with the scalar pT sum in a cone, absolute or relative), `efficiency` (see below) or
  `pair_split` (an on-Z or other pair and the remaining objects). Objects are sorted by pT.
- `observables`: ordered per-event quantities. The library has counts and fields; missing
  momentum; scalar and vector sums (H_T, S_T, S_T^γ, H_T^γ, m_eff); invariant mass; transverse
  mass; Δφ, ΔR, Δη; the minimum Δφ between jets and the missing momentum; same-flavour
  opposite-charge pair masses with a declared target mass; the minimum lepton–b-jet mass M_lb;
  sums of masses over assignments; MT2 over declared assignments (MT2(ll), MT2(lb,lb)); MT2W;
  modified topness; the neutrino longitudinal momentum; aplanarity; and expressions over earlier
  observables. A quantity that cannot be formed in an event has no value; a cut on it fails and a
  histogram counts it separately as undefined. `only_if` skips expensive observables in events
  that cannot pass.
- `regions`: named regions with ordered, named cuts; a region may start from a `base` region.
- `histograms`: an observable (or two or three) in a region with declared edges, units,
  natural-language labels and a normalisation (`yield`, `raw`, `fraction`, `density`,
  `yield-per-width`). Under- and overflow are kept separately or placed in the edge bins by
  declaration. Bins are low-inclusive. A one-dimensional slice of a two-dimensional distribution
  declares `slice_width` so per-width normalisations divide by the slice width too.
- `efficiency_maps`: named maps with their source, axes, out-of-range policy, citation and
  semantics.
- `systematics`: weight-factor variations, branch variations (from the descriptor) and
  alternative efficiency maps. Each is a full pass with its own histograms and cutflow.
- `event_record`: an optional per-event record of the first events, for review.

Every name is checked when the recipe compiles, before any event is read.

## Object weights and period selection

`weights` keeps its generator field (or `null`) and an ordered `factors` list. Each factor
multiplies the event weight. Existing event-field strings remain valid; a typed event factor
uses `{"field": "correction"}`. The other factor forms refer to the final selected collections:

```json
{"generator": "generator", "factors": [
  "event_correction",
  {"object_product": {"objects": "selected", "field": "identification_sf"}},
  {"trigger_or_sf": {"objects": "selected", "data_eff": "data_eff", "mc_eff": "mc_eff"}},
  {"field": "period_correction", "applies_when": {"field": "period", "in": [1, 2]},
   "optional_in_files": true}
]}
```

`object_product` multiplies the declared field over the selected objects in each event;
an empty collection contributes one. Rejected objects contribute nothing. Fields must be
finite; signed and zero weights are retained. Factors are evaluated on each surviving subset
when efficiencies use `enumerate`, preserving the subsets' correlations in the squared weights.

`trigger_or_sf` computes `(1 - product(1 - data_eff)) / (1 - product(1 - mc_eff))`.
The supplied efficiencies must be finite probabilities between zero and one. The law assumes
independent object trigger responses for the declared OR; use it only where that assumption
describes the supplied efficiencies. A zero MC denominator, including an empty collection,
refuses with the original file entry index. A one-object collection gives the efficiency ratio.

Any typed factor may add `applies_when: {"field": "period", "in": [1, 2]}`. The field is
required and must contain finite numeric values. The factor contributes one outside the listed
periods; its values are checked only where it applies. Periods have no built-in meaning.

For an event-field factor, `optional_in_files: true` allows its nominal branch to be absent
from a ROOT input file; the factor then contributes one in that file. Its descriptor mapping
is still required. A present branch with an invalid shape or value refuses. Object fields,
generator weights, period fields, trigger fields and systematic replacement/multiply fields
remain required. `optional_weights_missing` lists absent optional event fields in each input
read record and in the final result's input provenance. Planning and execution use the same
policy. Optional object fields and optional LHE weights are not supported.

Weight-factor systematics can replace a typed event factor's `field`; they retain its period
condition and optional declaration. A declared replacement field is required, including in a
file without the nominal optional field. Branch variations apply the ordinary descriptor rules
to present fields; an absent nominal optional field is omitted in every branch variation.

A region cut may select boolean event fields by period instead of using an expression:

```json
{"name": "trigger selection", "any_of_by_period": {
  "period_field": "period", "table": {"1": ["first", "second"], "2": ["second"]}
}}
```

Table keys encode finite numeric period values (the event readers expose numeric fields).
Each event passes the OR of exactly its period's listed fields, whose values must be zero or
one. An unlisted period refuses with its value, even if an earlier cut rejected that event.
An event cut declares exactly one of `expr` and `any_of_by_period`.

## Recomputed missing momentum

An observable can retain a new transverse vector while exposing its magnitude as its scalar
value. `met_override` adds each selected collection's summed `(pt*cos(phi), pt*sin(phi))` to
the base MET vector, treating these objects as invisible:

```json
[
  {"name": "hidden_met", "op": "met_override", "base": "met", "add_invisible": ["selected"]},
  {"name": "hidden_phi", "op": "met_phi", "met": "hidden_met"},
  {"name": "mass", "op": "mt", "object": "remaining[0]", "met": "hidden_met"},
  {"name": "angle", "op": "delta_phi", "a": "remaining[0]", "b": "hidden_met"},
  {"name": "minimum", "op": "min_delta_phi_met", "collection": "jets", "met": "hidden_met"}
]
```

`base` is `met` or an earlier override. `mt`, `met`, `met_phi` and `min_delta_phi_met` accept
the optional `met` key; `delta_phi` accepts the vector name as either operand. References to
future overrides or scalar observables refuse during compilation. The original `met` vector
is preserved. An empty selected collection adds zero; `only_if` leaves both magnitude and
vector undefined outside its selection. Declare disjoint collections in `add_invisible` to
avoid counting the same object twice; duplicate collection names are refused.

## Object efficiencies

Efficiency maps are read from ROOT TH1/TH2/TH3 histograms (numeric edges, or edges written in
the bin labels such as `(0,0.8)` or `20-35`), JSON grids, HEPData tables and YODA scatters. Each
axis declares what happens outside its range: `refuse`, `clamp` or `zero`; clamped and zeroed
objects are counted. A map must come from a citable public source.

Each map declares its `semantics`: `absolute` (probability to reconstruct and identify the
object), `conditional_on_reco` (given that the detector simulation already reconstructed it) or
`scale_factor` (a ratio that multiplies an applied efficiency; only this kind may exceed 1). A
map in percent is refused. `card_modules` names the Delphes card modules the map corresponds to.
When the study supplies `detector_card`, planning refuses an absolute map on objects the card
already makes inefficient, and refuses a conditional map whose card module is missing. The
decision is recorded in the provenance.

The map is applied to the object collection before any selection uses it, in one of three ways:

- `enumerate` replaces each event by every keep/drop subset of the collection, weighted by its
  probability. Every later selection gets its exact expectation: vetoes gain acceptance from
  inefficiency, "at least one photon" with two candidates gives 1 − (1 − ε₁)(1 − ε₂), and
  leading-object choices follow the surviving objects. Counts become expected counts. The
  subsets of one event add as one correlated term in the sum of squared weights. `max_objects`
  (default 8, at most 12) bounds the subsets.
- `select` keeps each object with probability ε using reproducible random numbers keyed by the
  seed, the file, the entry and the object. Any split into chunks or partitions gives the same
  result.
- `all-required-weight` multiplies the event weight by the product of the efficiencies. It is
  exact only when the selection requires every object of the collection.

## Partitioned execution

The engine is three functions that the execution backend can schedule:

- `analyse(partition, plan)` reads one partition (files and entry ranges) and returns additive
  sums;
- `merge(partials)` adds them and refuses overlapping entry ranges or different plans;
- `finalize(merged, plan, normalization, out_dir=...)` normalises and writes the outputs.

The command line exposes the same steps:

```
ravel columnar-analysis inspect  --format delphes --input sample.root
ravel columnar-analysis validate --recipe recipe.json --format delphes --input sample.root [--detector-card card.tcl]
ravel columnar-analysis analyse  --recipe recipe.json --format delphes --input sample.root@0:0-50000 --out part-1.json
ravel columnar-analysis merge    part-1.json part-2.json --out merged.json
ravel columnar-analysis finalize --recipe recipe.json --format delphes --partial merged.json --normalization norm.json --out result/
ravel columnar-analysis plot     --histogram "met in three-lepton region" --entry "bkg/::Diboson simulation::background" --entry "sig/::Benchmark signal::signal" --out control
ravel columnar-analysis spec-check --spec analysis-spec.json --recipe recipe.json --format delphes
```

`analyse` and `merge` are steps of an approved study's execution plan; they do not replace the
CHECK-IN 1 approval.

## Typed analysis specification

When the selection is written from a paper, first record what the paper says in a typed
specification (`ravel.workflow.analysis_spec`): every object, overlap, cut, observable and
histogram field with its value, its status (`explicit`, `inferred`, `ambiguous`,
`not_specified`) and, for explicit fields, the exact lines of the source with their hash.
Inferred fields carry a note. Histograms state their normalisation basis (`fiducial_N`,
`in_range_N`, `xsec`, `bin_width_area_2D`).

The ambiguity check (`ravel.workflow.spec_ambiguity`) names collection-scope, veto-scope,
object-reuse, cut-ordering, fill-timing, variable-consistency and normalisation-basis
ambiguities. Those that move a yield or a shape stop planning until the specification resolves
them; the others are listed as defaulted assumptions for CHECK-IN 1. Each recipe node names the
items it implements with `spec_item`, and planning checks the mapping both ways, including that
each histogram realises its normalisation basis.

## Worked recipe

A generic selection with three leptons, an on-Z pair, missing momentum and an isolated-track
veto, on Delphes output. The Z mass value and its source are declared, not built in.

```json
{
  "schema_version": 1,
  "kind": "columnar-analysis-recipe",
  "name": "three leptons with an on-Z pair and missing momentum",
  "weights": {"generator": "weight", "factors": []},
  "objects": [
    {"name": "electrons", "from": "Electron", "select": "pt > 10 and abs(eta) < 2.47"},
    {"name": "muons", "from": "Muon", "select": "pt > 10 and abs(eta) < 2.5"},
    {"name": "jets", "from": "Jet", "select": "pt > 20 and abs(eta) < 2.8"},
    {"name": "tracks", "from": "EFlowTrack", "select": "pt > 1 and abs(eta) < 2.5"},
    {"overlap_removal": {"remove": "jets", "near": "electrons", "dr": 0.2}},
    {"overlap_removal": {"remove": "electrons", "near": "jets", "dr": 0.4}},
    {"overlap_removal": {"remove": "muons", "near": "jets", "dr": 0.4}},
    {"isolation": {"object": "tracks", "against": "tracks", "cone": 0.3, "field": "track_isolation", "relative": true}},
    {"name": "bjets", "from_object": "jets", "select": "btag == 1"},
    {"name": "leptons", "union": ["electrons", "muons"]},
    {"overlap_removal": {"remove": "tracks", "near": "leptons", "dr": 0.05}},
    {"name": "isolated_tracks", "from_object": "tracks", "select": "pt > 10 and track_isolation < 0.1"},
    {"pair_split": {"from": "leptons", "charge": "opposite", "flavour": "same", "choose": "closest-to-mass",
                    "target_mass": 91.1876, "source": "PDG Z boson mass", "pair": "z_leptons", "rest": "other_leptons"}}
  ],
  "observables": [
    {"name": "n_leptons", "op": "count", "collection": "leptons"},
    {"name": "n_bjets", "op": "count", "collection": "bjets"},
    {"name": "n_isolated_tracks", "op": "count", "collection": "isolated_tracks"},
    {"name": "met", "op": "met", "unit": "GeV", "label": "Missing transverse momentum"},
    {"name": "mll", "op": "ossf_pair_mass", "collection": "leptons", "choose": "closest-to-mass",
     "target_mass": 91.1876, "source": "PDG Z boson mass", "unit": "GeV"},
    {"name": "mt_third", "op": "mt", "object": "other_leptons[0]", "unit": "GeV"},
    {"name": "min_dphi", "op": "min_delta_phi_met", "collection": "jets", "max_objects": 4}
  ],
  "regions": [
    {"name": "three leptons on Z", "cuts": [
      {"name": "three leptons", "expr": "n_leptons >= 3"},
      {"name": "on-Z pair", "expr": "abs(mll - 91.1876) < 15"},
      {"name": "b-jet veto", "expr": "n_bjets == 0"},
      {"name": "missing momentum", "expr": "met > 50"},
      {"name": "transverse mass", "expr": "mt_third > 50"}]},
    {"name": "three leptons and no isolated track", "base": "three leptons on Z", "cuts": [
      {"name": "isolated-track veto", "expr": "n_isolated_tracks == 0"}]}
  ],
  "histograms": [
    {"name": "missing momentum", "region": "three leptons on Z", "observable": "met",
     "edges": [50, 100, 150, 250, 400], "unit": "GeV", "label": "Missing transverse momentum",
     "normalization": "yield", "overflow": "last-bin", "underflow": "separate"},
    {"name": "third-lepton transverse mass", "region": "three leptons on Z", "observable": "mt_third",
     "binning": {"uniform": {"low": 50, "high": 350, "bins": 6}}, "unit": "GeV",
     "label": "Transverse mass of the third lepton", "normalization": "yield"}
  ]
}
```

The track isolation is computed against all tracks before the tracks of selected leptons are
removed, so the veto counts only additional isolated tracks.

## Limits

For bounded per-event `features` output and hash-pinned, held-out `model_score`
observables, see the [population and frozen-score contract](../workflow/reference/scientific-studies.md#bounded-feature-populations-and-frozen-model-scores).
The export records the sample role, weight treatment, sampling and group folds;
prediction requires the existing frozen NumPy checkpoint, preprocessing and group custody.

The engine reports the declared selection on the supplied events with Monte Carlo statistical
uncertainties. Detector fidelity, generator accuracy and agreement with a published result are
separate checks (step 3.5 and the certification in step 9).

## Flat trees, large-radius jets and public record identities

Select `format: "nanoaod"` for a NanoAOD-style `Events` tree. The packaged descriptor
maps Electron, Muon, Photon, Jet and IsoTrack flat branches, their `nCollection`
counts, scalar MET, `genWeight`, and run/luminosity-block/event identifiers. Integer
identifiers retain their source precision. Counts must match each collection's
object lengths. The descriptor defines a particular branch layout; a different
production version or discriminant requires a supplied descriptor, with no branch
substitution inferred from the file. IsoTrack uses a declared charged-pion mass
hypothesis; supply a different descriptor when that hypothesis does not apply.

`Jet.btag` is the `Jet_btagDeepFlavB` discriminant. The recipe supplies the
working-point threshold in its object selection, with the chosen tagger, era and
calibration source recorded in the supplied study inputs. The descriptor supplies
no threshold, efficiency or scale factor. A discriminant cut alone does not
establish tagging calibration.

The `delphes` descriptor includes an ancillary `FatJet` collection. Its fields
include `mass`, `softdrop_mass`, `tau1` through `tau5`, `tau21`, `tau32`, and
`trimmed_mass` where present. These use the Delphes 3.5 Jet class's `Tau[5]`,
`SoftDroppedJet` and `TrimmedP4[5]` members. The first trimmed four-vector is the
whole trimmed jet; slots after it are subjets. Each four-vector is stored as one
unsplit object branch, so its components are read as members of that branch;
invariant masses follow the signed four-vector mass convention.
A zero subjettiness denominator gives an undefined ratio, so a cut on it fails.
Bulk inspection can omit an absent ancillary collection. A recipe selecting
FatJet requires its branches. A missing ancillary field used in an object cut or
field observable is refused before analysis; unused trimmed fields can be absent.
The branch layout was read from an existing detector file; the numerical values
still require qualification against a supplied file with independent references.

Supplied ROOT descriptors can declare a scalar collection `count` branch, a
collection or field `optional: true` for ancillary content, a branch field `index`
for a fixed array slot, a branch field `member` (a list of nested member names) for
a number inside an unsplit object branch, `ratio: [numerator, denominator]`, and
`mass_from: {px, py, pz, e}`. Derived operands are field specifications, not
executable code. Branch names are read literally, including array brackets.
Unrequested absent ancillary fields are omitted, never filled with fabricated
measurements. Recipes bind the fields used by cuts and field observables.

Pinned dataset samples use `id_scheme: "dsid"` by default. Legacy integer DSIDs,
Rucio-style member identifiers and delivery receipt structure retain their existing
contract. A public sample instead supplies `id_scheme: "record"`, a nonempty
`record_id`, and an `authority` containing a DOI or literal HTTP(S) landing URL.
Record samples omit `dsid`. This is source identity, not a normalization rule.
If the source has no member `did`, omit it. Retain a source-provided GUID when
available; otherwise set `guid` to `<checksum algorithm>:<checksum value>` using
that member's declared checksum. A checksum identity must match that checksum.

Both pinned normalization documents must contain the same sample identity:
`sample_id`, and either `dsid` or all of `id_scheme`, `record_id`, `authority`.
The original population lists member `guid`, `entries`, and `did` when declared.
The normalization source binds `original_population_sha256` and explicitly declares
`sum_weights`, `luminosity_fb_inverse`, `cross_section_pb`, `filter_efficiency` and
`k_factor`. A record authority does not supply or inherit any of those quantities.
Use the existing `inputs: {dataset: <pin>}` and `normalization: {mode: "dataset"}`
interface; local members retain their `file://` URIs. ROOT-stream context, worker,
partition and final receipts carry the record identity and verify the same source
binding. Dataset discovery and DSID-shaped supplied-ntuple operations retain their
own contracts; public-record acquisition must supply a pinned dataset directly.
