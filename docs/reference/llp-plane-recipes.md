# Whole supplied LLP model-plane construction

`llp-plane-recipe` is a source-bound ordinary study that constructs the complete
requested mass/spectrum, production-component, lifetime and projection population.
It does not generate events, run a spectrum solver, fit a likelihood or approve
an exclusion. Use an ordinary version-2 `ravel plan` specification with task
`{"input":"/absolute/request.json"}`, the original `goal_binding`, a review policy,
one attempt and a 60-second construction budget. The generic scientific-study
Graph, status, review and report routes remain authoritative. Each emitted
`model-events` or `signal-template` specification needs a separate fresh ordinary
plan and approval. Construction never completes the original research task.

The private regression fixture demonstrates a fully supplied input graph. Every
physical assertion in that fixture is synthetic, including its charged response.
It must not be used as an ATLAS calibration.

## Request population and original source

The request has schema version 1, `source`, `goal_binding`, `analysis`, `axes`,
`points`, `projection_scenarios`, `cells`, `mixture_sampling`, pinned generation
and inference policies, `child_seconds` and explicit `assumptions`. Source
references use canonical absolute regular paths with SHA-256 and size. Existing
generation requests retain their two-field path/SHA pins. All source members
returned by the existing generation and published-model input enumerators are
individual ordinary stage inputs, not just manifest names.

* `analysis` preserves ID, original energy and luminosity, every ordered fitted
  SR/CR bin (ID, channel, signal sample, index, role), unresolved bins, primary
  sources, and `charged_source_required` or `neutral_source_required` transport.
* One to four typed axes contain the full literal Cartesian plane. Every point
  has a separate physical identity document: coordinates, energy, exact spectrum
  source, complete component process/decay-channel definitions, LLP species with
  mass and charge, and source pins. No interpolation supplies an absent point.
* Every point contains exactly its identity document's production components.
  Each component has a literal source cross section in pb and branching fraction,
  a full cohort or explicit null, a calibrated joint-response input or null,
  and an optional existing `model_event_plan` generation request. Gauge fractions
  do not supply component rates or acceptance. Missing components stay in all cells.
* Every point's lifetime rows give ctau in mm for every source LLP species.
  Cells are the entire ordered point × lifetime × projection product. No missing,
  failed, unknown or rejected member disappears from the report.

Declared bounds are 32 plane points, 16 components/point, 16 lifetimes/point,
8 projection scenarios and 128 complete cells. A source JSON document is bounded
by the existing task-input reader (2 MB), its compact source population by 512
members/64 MB, and expanded generation/archive inputs by 32,768 members/512 MiB.
The response/trace and covariance arithmetic budgets are checked before lifetime
transformation. Exceeding a bound refuses the complete request; it does not sample
or silently reduce its population.

## Lifetime cohort, response and support

A cohort binds `point_identity_sha256` and component ID, source species/lifetimes,
complete event/group IDs, every ordered source-defined named weight and every
unstable particle's species and proper decay length. Zero-LLP events have an
explicit empty particle list; rejected and zero-weight events remain present.
Weight definitions retain their unit, meaning and primary source. The nominal
normalization weight is explicit; variations remain separate prediction streams.

The implemented first branch is fully observed, independent, untruncated
exponential proper lengths. For source means a_i, target means b_i and retained
proper lengths u_i, the joint ratio is

`R = exp(sum_i(log(a_i/b_i) + u_i*(1/a_i - 1/b_i)))`.

The empty product is one. Source mass, spectrum, energy, process, production
kinematics, decay channels and branching assumptions remain fixed. Overflow,
underflow or an unrepresentable ratio refuses; no clipping creates a zero event.
Forced/truncated decays and right-censored records are retained as source-required
branches. They need their actual normalized joint sampling density and support
proof, and selection must be measurable from the retained record. They cannot use
this unconditional formula.

A response binds the same point, component and cohort bytes. Its complete
exclusive joint region-mask probabilities include rejection and preserve region
membership overlaps. States have canonical region order; probabilities sum to
one without renormalization. Region marginal probabilities may overlap. Lifetime
marks are `R * epsilon_region`; they need not form a probability simplex.

This operation never propagates a charged trajectory through a magnetic field
or material, constructs a tracklet, or multiplies object efficiencies. A
published per-tracklet efficiency map alone does not provide the joint event
selection/calibration input. The source must supply the charged truth/selection
producer, complete conditioning, overlaps and calibration. A pin preserves the
assertion; it does not certify its physical validity.

## Original exposure and MC moments

The supported linear normalization is an externally known component coefficient
`K = sigma_pb * BR * luminosity_fb * 1000` with dimensionless importance marks.
The source must establish the nominal group mark's unit-mean convention. Native
weights carrying pb or requiring sum-original-weights ratio normalization remain
an explicit unsupported branch here, rather than being rescaled by guesswork.
The divisor is unchanged across target lifetimes. No selected or lifetime-weighted
sum is a denominator.

For a declared fixed-N IID generator-group experiment, the divisor counts **all**
original groups. The reusable `marked_response.empirical_group_mean` returns the
mean and estimated full covariance `K²/[N(N-1)] * sum_g (x_g-xbar)(x_g-xbar)^T`.
N=1 has unavailable covariance, not zero covariance. This centered estimate is
not the known-category population formula or a finite-MC auxiliary likelihood.
For a declared independent Poisson-group experiment, its known external original
exposure divisor and the existing full uncentered group Gram are retained instead.
The realized count is not silently used to estimate that Poisson exposure.

All subevents are grouped once; signed marks, named weights, region overlaps and
cross-lifetime/group covariance remain complete. Component covariance is summed
only with explicit source-supported independence. Unknown/shared component
sampling retains all component records and requires a full common experiment;
no independence is inferred. Different physical model points are alternatives,
never summed into a total or declared statistically independent by this recipe.

For an unbounded source exponential, the individual lifetime-factor second moment
is `a²/[b(2a-b)]` only for b < 2a and diverges for b >= 2a if that species occurs.
This condition alone does not prove the joint importance-weight/selection moment.
Finite empirical moments or ESS provide no tail certificate. Such cells retain
raw finite sums but are blocked from template/inference admission, with explicit
same-model source-cohort/card/generation/response requirements (new source mean
strictly greater than target/2), or a request for certified compact selection
support/complete mixture-density treatment. No requested lifetime is removed.

## Full likelihood inputs and explicit projections

The existing published-model and signal-template contracts retain every source
SR/CR channel, observation, modifier and auxiliary factor. The supplied mixed
signal template must equal the exact normalized original-exposure prediction in
all mapped bins. Scalar upper limits and post-fit error bars cannot replace the
complete source likelihood. Correlated, signed or fixed-N moments cannot be
turned into independent bin errors. The existing conditional Poissonized
all-bin `signal-template` child can be emitted only with its exact source-law,
nonnegative group, diagonal-within-cell and sumw2 checks.

Projection scenarios explicitly supply luminosity, energy, the existing
`stat`/`syst`/`frozen` background scaling law and its sources. New energy requires
new source generation/response; luminosity scaling cannot provide it. The existing
`project_workspace` background/global-luminosity convention is used explicitly.
For the reused signal cohort, yields and signal histosys variations scale by f;
absolute staterror/shapesys values scale by f, and signal template covariance
scales by f². Relative signal normsys terms remain unchanged. This differs from
assuming additional signal MC statistics grew with luminosity. Unsupported
modifier types refuse. f=1 is the exact source identity.

Complete projected workspaces are scientific inputs. Only expected quantiles may
be interpreted as a projection; scaled observed entries are a proxy, not new data.
Projected/fixed-N/correlated-MC inference still needs an applicable full auxiliary
law and ordinary bridge. The result exposes those continuation obligations and
retains all original requested cells for research-cycle selection and reporting.

## Generator target correspondence and generated-byte commitments

A supplied generation request is not a physical-target mapping by itself.
Before constructing any child, this LHC branch checks symmetric pp beams
(`beam_type=[1,1]`, `beam_pdg=[2212,2212]`, equal positive beam energies), with
their sum in GeV exactly matching the selected point and original analysis energy
in TeV. Other species or asymmetric beams remain an explicit unsupported source
need; no guessed center-of-mass conversion or child is emitted.

A component with a generation request may additionally supply a pinned
`generation_target` document. Without it, all requested points/cells remain, and
child preparation is blocked. The document has schema version 1, the exact
`point_identity_sha256` and `component_id`, all three beam arrays, exact
`model_manifest`, `process_card` and `parameter_card` pins, the configured `decay`
settings, and nonempty physical `sources`. Those exact source pins must be the
ones consumed by the generator configuration. `coordinate_parameters` has one
ordered row for every axis: `axis_id`, its literal `unit`, and a `parameter`
address with `block` and integer `indices`. Every corresponding literal SLHA
value must equal the selected coordinate. `mass_parameters` similarly retains
all ordered LLP species (`id`, `parameter` address in the MASS block), whose
literal values must equal their point's masses in GeV. There is no implicit
unit conversion, interpolation or automatic width calculation.

This verifies declared exact-source correspondence and available literal target
values. It does not prove an arbitrary UFO's charge, process aliases, decay or
matrix-element equivalence. The source mapping for the full spectrum, charges,
process and decay-channel definitions remains a disclosed physical premise.
Native execution and independent physics review stay separate.

Every newly written LLP JSON member is committed from its intended strict JSON
serialization before its atomic write. The same digest/size commitments, rather
than observed replacement stamps, are checked immediately and at ending census,
including the final receipt. The existing generator preparation's own intended
specification pin and returned literal receipt are retained and rechecked. The
existing template constructor receives the local committing writer; its numerical
and auxiliary-law checks are unchanged. Extra, missing or changed generated
members refuse success; failed outputs are retained.

`record_measurable=True` asserts a response conditional on the retained full
proper-length/kinematic record. An efficiency already averaged over a source
lifetime is not this response and cannot be multiplied by another lifetime ratio.
The selection/calibration sources must define the complete conditioning,
coordinates and units, period, domain and uncertainties; their pins do not prove
calibration. `joint_second_moment=source_asserted_finite` is likewise an explicit
premise for the FULL original weight × target lifetime density ratio × conditional
response mark, for every requested target lifetime and named weight. It is not
merely a premise about source-time weight/response variance. Length-correlated
weights can make that full moment divergent even for target ctau < 2×source ctau;
unknown full-mark premises block inference while retaining raw predictions.
