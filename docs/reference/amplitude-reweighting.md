# Amplitude-basis reweighting and measurement predictions

These modes predict how a differential measurement changes when new s-channel states interfere
with a continuum, for any coupling, mass, width and propagator choice, without generating new
events for each choice.

## Idea

When every hypothesis is a linear combination of a fixed set of amplitudes (the *basis members*),

    A(theta, x) = sum_k c_k(theta, s) a_k(x),

the squared amplitude at a phase-space point x, summed over helicities, is a quadratic form
c^dagger G(x) c. The coefficients c_k hold the couplings and the propagators of the partonic
invariant s. RAVEL stores the small Hermitian matrix G for every weighted integration point.
Any hypothesis is then evaluated afterwards, exactly, at the same points.

A hypothesis is data:

```json
{"id": "S600", "constant": {"continuum": 1},
 "states": [{"mass_gev": 125.0, "width_gev": 0.0041, "propagator": "fixed-width",
             "couplings": {"scalar_bottom": 1, "scalar_top": 1}},
            {"mass_gev": 600.0, "width_gev": 60.0, "propagator": "running-width",
             "couplings": {"scalar_top": [0.4, 0.0]}}]}
```

Couplings are real numbers or `[real, imaginary]` pairs. Propagators are `fixed-width`,
1/(s - M^2 + i M Gamma), or `running-width`, 1/(s - M^2 + i s Gamma/M).

Points with identical leptons use a pairing partition built from a fixed reference amplitude,
so every hypothesis stays a quadratic form and the estimator stays unbiased.

## Workflow

1. **`amplitude-integration`** runs the amplitude program through the execution backend: one
   warm-up per channel to freeze the integration grid, then independent equal-exposure blocks.
   Each block is checked against the program's own squared amplitudes before it is stored. The
   store is resumable: a later approved run continues from the first missing block.
2. **`amplitude-predictions`** turns the store into binned predictions. The bin edges (literal
   or read from a HEPData table), point-level cuts on stored observables, the representation
   (integrated or differential) and any cited normalization factor are supplied in the
   document. It writes one `binned_values` result per stream, the joint block covariance and
   the input of a `differential-likelihood` document.
3. **`weighted-events`** writes the stored points as HepMC3 or Les Houches events with one
   named weight per hypothesis, per difference to the reference, and per declared polynomial
   term. Through the execution
   backend it runs an optional shower and any Rivet routine, then normalizes the RAW
   histograms by the attempted draws of each block.

`ravel amplitudes example --mode <mode>` prints an example document,
`ravel amplitudes check --mode <mode> --input doc.json` lists its inputs, and
`ravel amplitudes spec ...` writes the study specification for `ravel plan`.
Computation always runs through `ravel plan`, `ravel approve` and `ravel run`.

## Spin-0 members

`spin0_amplitudes` adds gluon-fusion spin-0 states decaying to four leptons:

- production through the exact quark-loop form factors, with scalar (CP-even) and
  pseudoscalar (CP-odd) Yukawa couplings for any declared quark mass;
- decay through the g1, g2 and g4 terms of the spin-0 ZZ vertex (g4 is CP-odd).

The amplitudes are numerators: the propagator comes from the hypothesis. Every constant
(alpha_s, v, Z mass and width, lepton couplings) is a required input.

Phases of helicity amplitudes depend on spinor conventions. Before spin-0 members join amplitudes
from another program, a closure fit must reproduce that program's own CP-even amplitudes at the
same points with one factor per helicity (`spin0` in the integration document). The fit fails
if the ratio is not constant.

Useful exact properties:

- a scalar and a pseudoscalar never interfere after the gluon-helicity sum;
- a CP-odd decay term interferes point by point with the CP-even one, but cancels in
  CP-symmetric observables such as the four-lepton mass;
- a continuum has independent (++) and (--) gluon amplitudes, so it interferes with both.

## Coupling polynomials

With `coupling_scaling`, the listed states scale as kappa^p. Each difference to the reference
is then written exactly as a constant, an interference term (kappa^p) and a pure-signal term
(kappa^2p). The `differential-likelihood` input carries these terms with their powers. The width
stays as declared while the coupling scales.

Declare the same polynomial in the prediction and event documents. Alternatively,
`coupling_polynomial` supports several parameters through disjoint state groups:

```json
{"parameters": [{"name": "x", "unit": "", "label": "First coupling"},
                {"name": "y", "unit": "", "label": "Second coupling"}],
 "components": [{"states": [0], "powers": {"x": 1}},
                {"states": [1], "powers": {"y": 1}}]}
```

The reference cannot contain scaled states. Constants and unlisted states stay
fixed. Each component multiplies an amplitude monomial, and its pair products
give the signed cross-section terms, including mixed powers. The event streams
use portable names: `<hypothesis>--constant`, `--interference`, `--pure-signal`
for `coupling_scaling`, or `<hypothesis>--term-<index>` for `coupling_polynomial`.
Stream ordering is recorded in `joint_layout`; terms and cross-covariances stay
paired by their block and attempted-draw exposure even when weights span passes.

After Rivet, each histogram's `differential-likelihood-input.json` takes its
reference, polynomial vectors and stacked term covariance from the normalized
RAW output. `ravel.physics.rivet_fit.selected_prediction` validates that output;
`rivet_fit.likelihood_input` makes the inference fragment. The MC covariance
covers terms times bins, with every term cross-covariance retained. Differential
bin widths are applied to both axes of the covariance; flows remain integrated.
Negative interference is preserved. `provenance` records `stage: rivet-selected`,
the declared `showered` state, units and `RAW/attempted-draws` normalization.
Born outputs record `stage: Born`.

The fragment feeds the existing differential measurement model, including its
prediction-dependent covariance and nuisance profiling. For several couplings,
use `differential.Model` with the fragment's parameters, terms and covariance;
the file-backed `differential-likelihood` adapter still scans one free parameter.
This handoff supplies a signal model and does not add a multidimensional scan.

The interference parent uses selected terms for its fit, ablation and signed
delivery. Its Born/store comparison is a pinned diagnostic, with explicit value
and covariance tolerances, rather than an equality requirement. Radiation,
selection losses and bin migrations can change both means and covariance.
An identity selection without showering should agree within those tolerances;
agreement alone does not qualify amplitudes or shower accuracy.

## Normalization of signed streams

Rivet routines usually scale a histogram by crossSection()/sumOfWeights(). That is wrong for a
signed stream such as an interference or a difference. Event weights here are absolute (the mean
over the attempted draws of a block is the cross section in pb), and predictions come from the
`/RAW/` histograms divided by the attempted draws.

## Uncertainty

Blocks of one cohort are independent equal-exposure estimates; their centered covariance of the
mean is the Monte Carlo covariance. Cohorts are independently integrated contributions (for
example lepton-flavour channels) and add. Draws that the program reports as failed are not
zeros: predictions refuse blocks with failed draws.

## Safety cuts of the amplitude program

A program can be numerically unreliable in part of phase space. It declares such a region as a
safety cut in its `addon.json` (`protocol.safety_cuts`: kind, threshold, the particles it applies
to, whether the excluded weight is measured, the reason and its upstream source) and applies the
cut when it makes each draw. Kind `pair_pt_min` bounds the transverse momentum of declared
particle pairs; `normalized_invariant_min` bounds E_j / E_ref and |p_j.p_k| / |E_j E_k| over the
declared particles and beams. A draw below a cut is excluded: it counts in the attempted draws
and contributes zero, and nothing of it is stored. Every integral and prediction from the store therefore covers
exactly the restricted phase space, with exact exposure and normalisation there.

The integration document accepts the declared cuts by id in `safety_cuts`; a document that omits
one, or names a cut the program does not declare, is refused before any stage runs, and so is a
program that reports a cut its manifest does not declare. RAVEL recomputes each cut from the
recorded momenta of every stored point and excluded draw, writes the cuts into the store header,
the result's assumptions and each stage receipt, and measures the excluded share of the draws and,
for cuts with a measured excluded weight, of the integration factor and of the program's own
weight per stage. That share is reported, never
assumed negligible; the excluded region itself is not modelled.

## The MCFM program

The MCFM overlay that writes helicity amplitudes per point is GPL-3.0-or-later and lives outside
the Python package in `addons/gpl/mcfm-amplitudes`. The installer builds it as a separate
program. RAVEL finds it through, in order: `RAVEL_ADDON_PATH`, `$RAVEL_NATIVE_BUILD/addons`,
the shared native build and a source checkout, and checks every listed file against its sha256.
Its `addon.json` declares the record format, how the program's amplitude channels form the
basis members and two safety cuts, both MCFM's own. MCFM omits its continuum quark loops for a
Z candidate below 0.1 GeV of transverse momentum (`src/ZZ/getggZZamps.f`), so the program
excludes those draws in both lepton pairings and measures their weight. MCFM's `lowint` also
discards a draw whose lepton energies or normalized invariants fall below 1e-9
(`passed_smallnew`, `src/Need/smallnew.f`) before it evaluates the flux, the PDFs or the
squared amplitude; those draws are excluded with an unmeasured weight (MCFM's own integrand is
zero there), and their share of the draws is reported.

Install it with `bash scripts/setup/install.sh --only mcfm-amplitudes --jobs 4 --accept-licenses`
and check it with `ravel doctor --group mcfm-amplitudes`. On macOS the build runs in a pinned
linux/amd64 image in the Podman machine; start a stopped machine with
`ravel-podman machine start ravel`. On Linux x86_64 the program is compiled on the host with the
GNU compilers of the compiler-bootstrap group. The installer writes the prefix record
`installations/mcfm-amplitudes.json`; an integration backend that omits the program (and, for a
container, the image and read-only trees) takes them from the record found by
`ravel.paths.native_build_root()`. The record is pinned in the study inputs and every backend
stage, so a changed program invalidates prepared work. The Linux x86_64 native route is
qualified from a clean-prefix build; the macOS container route stays built-unqualified until its
own build and checks are recorded. Installation authority covers compilation and the binary
check; it grants no study approval and is never a human review.

## Continuous fits on retained blocks

`differential-likelihood` also accepts `operation: "cached-profile"`. This route
re-evaluates complete cached amplitudes as masses, widths and couplings change;
it does not interpolate a grid or extract a coupling polynomial. Use it for
conditional profiles whose covariance must change at each fitted state. The
ordinary `ravel science` plan, approval and run path remains the execution entry.
The adapter task is `{"input": "profile.json"}`.

For exact replay of a program's hypothesis-dependent pairing partition, set
`retain_pairings: true` in the source document of the integration that writes the blocks. This adds
every accepted point's two pairing amplitudes, normalization and flags to each
completed block. A sample of audit amplitudes cannot substitute for this payload.
Existing Gram-only stores and consumers keep their format and behavior when the
option is absent. The larger retained payload counts toward the cache budget.

The profile's `response` supplies a pinned `amplitude-predictions` document, a
non-reference hypothesis ID, scalar bindings and an explicit estimator:

```json
{
  "prediction": {"path": "prediction.json", "sha256": "<supplied digest>"},
  "hypothesis": "alternative",
  "estimator": "hypothesis-pairing",
  "bindings": [
    {"path": ["states", 0, "mass_gev"], "offset": 0, "coefficients": {"mass": 1}},
    {"path": ["states", 0, "width_gev"], "offset": 0, "coefficients": {"width": 1}},
    {"path": ["states", 0, "couplings", "scalar"], "offset": 1,
     "coefficients": {"fraction": -1}},
    {"path": ["states", 1, "couplings", "scalar"], "offset": 0,
     "coefficients": {"fraction": 1}}
  ]
}
```

Each binding assigns `offset + sum(coefficient * parameter)` to an existing
numeric leaf. This can preserve a shared-pole mixture without embedding any
particular pole mass, width, flavour or mixing convention in the implementation.
Complex couplings can bind their explicit real/imaginary leaves. The unmodified
reference hypothesis supplies the subtraction. `reference-gram` instead uses the
stored fixed-reference Gram estimator. The two estimators can differ on a finite
sample; the rational hypothesis-pairing estimator must not be treated as a
polynomial or passed into polynomial term extraction. The Rivet-selected term
and joint covariance handoff remains a separate route.

For original-return custody replay, supply `response.replay` as a pinned JSON
source containing `protocol` (the amplitude-record protocol) and ordered `blocks`.
Each block gives `id`, integer `channel`, `source: {path, sha256}` for its original
native record stream and `proposal: {path, sha256}` for its frozen proposal.
Paths are relative to that descriptor. The reader checks every scheduled block,
reparses the complete attempted population, checks the point oracle, reconstructs
all stored arrays (using the exact Hermitian packing law) and compares all retained
pairings. Proposal hashes must match the cached cohort. These files enter the
same byte budget and ending checks. Results explicitly distinguish `raw_replayed`
from cache/manifest-only consumption. Replay authenticates saved source bytes;
it does not recertify the original native runtime or proposal accuracy.

The complete profile document has these fields:

| Field | Contract |
|---|---|
| `schema_version`, `kind`, `operation` | `1`, `differential-likelihood`, `cached-profile` |
| `statistic` | `verbatim` request and `objective: chi2` or `gaussian`; no threshold is inferred |
| `response` | The object above; optional `fiducial: {path, sha256}` and `replay: {path, sha256}` |
| `measurement` | `values`, `unit`, `bin_edges`, exactly matching response geometry and units |
| `reference` | Supplied baseline `values` and source `description` |
| `covariance` | List of `{name, law, matrix}`; laws `fixed`, `ratio`, `sqrt-ratio` |
| `parameters` | List of `{name, unit, label, value, min, max, constant}` |
| `fit` | Complete `starts`, `profile_cells: [{id, fixed}]`, positive numerical `tolerance`, optional `engine` |
| `mc_policy` | Explicit `retained_only` or `independent_gaussian_sum` |
| `max_condition` | Finite covariance condition ceiling |
| `resources` | Positive integer `max_cache_bytes`, `max_evaluations`, `max_seconds`, `max_output_bytes` |
| `auxiliary` | Optional pinned JSON source `{path, sha256}` described below |

Values and matrices support the existing literal, JSON and HEPData source
references. HEPData matrix intervals are joined to the measurement order, not
flattened by row order. Every fit coordinate must have an amplitude-binding or
auxiliary role. Starts list all coordinates, including constants. Each profile
cell fixes a subset of originally free coordinates; all other free coordinates
are fitted anew from every start. Domain boundaries, independent starts,
failed/unissued fits and disconnected cells remain explicit.

A supplied auxiliary source contains `parameters`, an additive bin-by-parameter
`response`, and Gaussian `observed`, `offset`, `matrix`, `covariance`. Its mean is
`offset + matrix @ nuisance`. The nuisance-shifted spectrum enters experimental
covariance rescaling. The auxiliary covariance must be SPD within the declared
condition ceiling. Experimental component matrices are composite coefficients;
their eigenvalue diagnostics are retained and no independent component sampling
law is inferred. The experimental sum must pass strict SPD/condition admission
before optional MC covariance addition. Neither matrix is repaired. Gaussian
scores retain the log determinant and normalization constants for both the
spectrum and auxiliary observations.

A `fiducial` source may define the generic Born two-pair projection in
`amplitude_selection.validate`: four `particles` indices; per-species
`acceptance` (`pt_min`, `abs_eta_max`); three `rank_pt_min` thresholds;
`pairing_mass`; `primary_window`; a piecewise-linear `secondary_min` with `knots`
and `values`; `secondary_max`; `same_pair_dr`, `same_species_dr`,
`different_species_dr`, `all_pair_mass_min`, and `overlap_dr`. All thresholds are
supplied. Pairing uses opposite signed species, nearest-pole ranking and disjoint
pairs; exact ranking ties refuse. pT/eta acceptance is strict, mass windows are
lower-inclusive/upper-exclusive, and the secondary minimum is clamped outside
its knots. Stored-observable selection cuts apply as well. This projection does
not establish particle-level or detector equivalence.

The default `fit.engine: scipy` uses bounded L-BFGS-B, saves numerical status,
projected gradients and approximate inverse Hessians, and re-evaluates each
returned objective. Optional `fit.engine: roofit` uses the general
`RavelCachedObjective.cxx` callback bridge and the existing RooMinimizer policy.
It additionally requires a positive initial `error` on every parameter and
`runtime: {version, files: [{path, sha256}, ...]}` covering the actual Python interpreter, ROOT module
and loaded native libraries. Only the approved science worker may invoke it.
Each raw RooFitResult is saved and reread, with status history, covariance,
EDM, errors and full state restoration retained. The objective itself is not a
portable saved workspace. The callback uses the Python numerical evaluator;
it is not an independent second implementation. Native compilation, callback
ABI and execution are unqualified until separately tested with a supplied
runtime; the package's controls execute no native job.

`inference.json` retains all evaluation records, three-stream block responses
(reference, model, difference), both integrated flows, and the full shared-block
cross-state covariance kernel. Differential finite bins divide by their supplied
widths; flows stay integrated. A profile's `q` is the difference of twice-NLL
values from the best accepted declared global start. Negative values exposing
an unresolved global minimum are retained and rejected. No CLs limit, discovery
significance, threshold, interval, coverage or proposal-adequacy qualification
follows from delivery of these conditional profiles.
