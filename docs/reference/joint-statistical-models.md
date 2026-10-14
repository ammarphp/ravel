# Joined published-background and finite-MC models

The Python APIs in `mc_auxiliary`, `joint_likelihood` and `joint_profile` combine
a supplied published background model with a separately specified signal-MC
experiment. They preserve signal contributions in every mapped signal and
control bin, shared source nuisance coordinates, source auxiliary observations
and the complete MC support. Scientific applicability depends on the supplied
source response and generator sampling law.

## The three likelihood factors

The construction evaluates

\[
L = \prod_i \operatorname{Pois}(n_i\mid b_i(\theta)+\mu s_i(\theta,\eta))
    L_{\mathrm{source\ aux}}(z\mid\theta)
    L_{\mathrm{MC}}(m\mid\eta).
\]

Each auxiliary experiment occurs once. Source parameters shared by background
and signal use the same coordinate value. Supplied source/new-MC independence
is an explicit model assumption requiring scientific review.

`BackgroundAuxBlock` in `published_background` retains the source channel
ordering, parameter bounds, initial values and fixed flags. Its
`separable_signal_mc` policy preserves the admitted source auxiliary model.
`rebuild_background_mc_from_source` requires the exact separate background-only
workspace and a new model identity when signal and background originally shared
pooled MC constraints. Such reconstruction changes the auxiliary experiment.
For the official five-channel stau workspace, simply setting signal strength
to zero does not restore the background-only statistical-error widths.

## Independent MC schema

```python
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock

mc = MCAuxiliaryBlock({"input": "mc-model.json"})
signal = mc.nominal(latent)["signal_expectation"]
log_l_mc = mc.auxiliary_logpdf(latent, observations=mc_counts)
```

The model document contains exactly `schema_version`, `model_id`, `sources`,
`bins`, `mc_design`, `classes` and `assumptions`. Target bins declare their
identity, signal/control role and source reference. Each class declares fixed
contribution marks, denominator marks or exposure, integer observed population,
complete observed group identities, an interior initial value and source
reference. A separate source-pinned ledger records the complete class support,
observed groups and known normalization.

The supported laws are:

- Independent Poisson group populations, with known exposure
  `m_k ~ Pois(t_k rho_k)` and signal expectation `W rho`.
- A complete fixed-N IID categorical experiment, including unselected and
  zero-observed categories, with `m ~ Multinomial(N, p)` and signal expectation
  `kappa A p / (d · p)`.

The MC schema contains no main observations, fixed background array, profile
grid or numerical rate cap. `extract_legacy_mc` can export this schema from a
source-bound historical conditional model. It requires a new destination and
retains the original wrapper as provenance; any historical search settings are
written separately. A producer can supply the independent schema directly.

The physical domain requires nonnegative latent signal expectation in every
bin. The fixed-N law additionally requires a complete probability simplex and
strictly positive expected signed denominator. Observed signed sums and
denominators can be negative or zero and remain unchanged. Their observed sign
does not define the latent physical domain. Moments such as sumw and sumw2
alone are insufficient to select either sampling law.

Inputs are bounded to 8 MiB per file, 16 source references and 32 MiB aggregate
captured bytes. The class and bin support is limited to at most eight entries;
at least two target bins with signal and control roles are required. Subsequent
custody checks detect source changes. A zero-probability observed outcome
returns an explicitly nonfinite likelihood rather than a fabricated finite
penalty.

## Source response and joint evaluation

```python
from ravel.physics.joint_likelihood import JointPublishedFiniteMC

joint = JointPublishedFiniteMC(
    background, mc,
    source_workspace=source_workspace,
    signal_samples=signal_samples,
    source_bin_map=source_bin_map,
    response=response,
    response_contract=response_contract,
    model_id="explicit-new-statistical-model",
    main_disposition="replace_conditional_control_with_bound_published_source",
)
value = joint.evaluate(source_point, latent, mu=1.0)
draw = joint.draw_joint_data(source_point, latent, mu=1.0, rng=rng)
```

The bin map is a complete permutation between MC target identities and every
source channel/bin. Missing, duplicate or mismatched bins are refused. The
main-disposition marker explicitly assigns the main experiment to the published
source. All source signal-response nuisance dependencies must be represented.

The response callback has the exact signature
`response(latent, nominal, source_point, configuration, source_data)`. Its
contract pins the implementation file, module function identity, explicit
configuration and named source data. A designated source workspace must equal
the workspace used by the background block. Dynamic closures, bound methods,
mutable function attributes and hidden defaults are refused. Direct function
identity and file custody still require a reviewed execution environment for
transitive globals and dependencies. These checks cannot establish detector
calibration or physical response fidelity.

The callback returns the complete signal response in MC target-bin order at
the same source parameter point as the background. The explicit bin map then
permutes it into source channel/bin order. The library checks finite,
nonnegative expectations and includes source and MC auxiliary constants.
Repeated joint data draws fluctuate the main Poisson observations, every
retained source auxiliary measurement and the full MC observation at one fixed
supplied truth. Source Gaussian constraints are repeated measurements, rather
than draws of nuisance truth values.

## Bounded profiling

`JointProfiler(joint, background, mc, ...)` binds the exact same model blocks.
Its `mu_domain`, Poisson `rate_caps` and classification of source bounds make
numerical search limits explicit. Source physical/numerical bound classifications
must come from source authority. The optimizer cannot infer that authority from
an endpoint contact.

`fit` profiles every admitted unfixed coordinate. `fixed_mu`, `fixed_source`
and `fixed_latent` define separately labeled conditional subproblems; source
fixed flags remain distinct. A fixed-N fit eliminates the final probability
algebraically while retaining all categories in the density and sampler.

Each fit requires a budget with `objective_calls`, `gradient_calls`,
`feasibility_lp_calls`, `stationarity_lp_calls`, `maxiter`, `lp_maxiter` and
`wall_seconds`. Every density probe and derivative/LP call is charged, including
failed probes. `profile` validates its entire finite, unique strength grid
before starting any fit and declares the maximum fit count. It returns all
failed or incomplete attempts and two-sided likelihood differences when the
required fits resolve.

This generic branch uses finite differences and admits at most eight free
coordinates. It retains distinct feasible starts, local rank, tangent descent
checks, solver warnings and artificial-bound contacts. General results are
bounded numerical agreement, without a global-optimum certificate. Sparse cases
with no established finite strength endpoint remain unresolved. Wall checks and
LP limits need an outer supervisor to interrupt blocking callbacks or native
solvers. Thread environment requests alone do not prove an observed native
thread ceiling.

## Evidence and remaining scientific work

Portable tests synthesize complete source workspaces and MC ledgers locally.
They check exact normalized densities, source constraints counted once, both
SR/CR signal contributions, fixed flags, repeated data, source custody, signed
domains, bounded inputs and resource refusals. An independent two-bin proof
establishes a particular saturated global maximum and exact mu=0 profile.
Additional Poisson and fixed-N examples demonstrate an unattained likelihood
supremum despite full local rank.

These mathematical controls do not qualify an arbitrary native generator law,
source/new-MC independence, marked nuisance migrations or detector response.
The complete official stau model exceeds the finite-difference branch's
eight-coordinate limit. The analytic branch below addresses that numerical
limit. Qualified response/MC inputs and separately admitted repeated-measurement
calibration remain necessary before interval, CLs or exclusion claims. The
library APIs provide model construction and bounded numerical diagnostics;
the `joint-fit` scientific mode dispatches the source-conditioned study below.

## Analytic source graph and full-coordinate profiling

`AnalyticPublishedJoint` in `joint_analytic` compiles the supplied source model
with the qualified code4 normsys and code4p histosys interpolation conventions.
It applies additive histogram changes before multiplicative factors and
retains scalar/vector parameter indexing. Exact product derivatives handle
zero factors without dividing by them. Changed interpolation implementations
and enabled expectation clipping are refused.

The signal extension is an explicit new model. In each mapped bin it multiplies
the finite-MC latent yield by the published non-MC signal response divided by
the canonical nominal signal yield. The denominator must be positive. This
construction retains source nuisance correlations across signal and background;
it does not determine nuisance-dependent event migration or variation-MC
correlations from nominal yields. A source-pinned marked response model is
still needed when that diagonal response assumption is insufficient.

```python
from ravel.physics.joint_analytic import (
    AnalyticPublishedJoint,
    AnalyticJointProfiler,
)

value = analytic_joint.evaluate_with_gradient(source_point, latent, mu=1.0)
profiler = AnalyticJointProfiler(
    analytic_joint, background, mc,
    mu_domain=mu_domain,
    source_bound_semantics=source_bound_semantics,
    rate_caps=rate_caps,
)
fit = profiler.fit(budget=budget)
```

The analytic profiler supports up to 256 free coordinates, with up to eight
target bins and the bounded MC support described above. It charges objective,
analytic-gradient, physical-constraint and LP work, and preserves distinct
feasible starts, warnings, artificial-bound contacts and failed attempts.
It does not condition source nuisance coordinates to satisfy the older
eight-coordinate limit. Fixed source flags and explicitly requested conditional
fits continue to have separate meanings.

For the five-region stau construction, all 119 retained source coordinates,
the signal strength and five independent categorical probabilities produce
125 free coordinates. The 117 source auxiliary factors appear once. Five
pooled statistical-error widths are rebuilt from the exact background-only
source; this changes those auxiliary experiments while preserving their count.

Forty portable synthetic controls exercise the graph, full-coordinate mapping,
derivatives, sampler, bounded fitting and refusal cases. Official source graph
compilation has been checked separately. Full official density, all-column
gradient/mean-Jacobian qualification and fit acceptance remain prospective.
Local multistart agreement and full rank do not prove a global optimum:
an independently checked counterexample has positive MC category counts but
an unattained strength optimum as source signal response tends to zero.

Independent follow-up review also found that the current profiler's approximate
boundary-activity test can remove a feasible descent direction at a point with
small positive physical-bound slack. A high-curvature synthetic counterexample
passes that projected test despite a lower feasible objective. The full-source
scientific preparation is held pending a separately reviewed repair covering
coordinate, linear and nonlinear physical constraints. Existing returned
verification flags describe their original numerical rule; they are not exact
KKT certificates. Original frozen studies and comparator source remain intact.

## Source-conditioned study adapter

`ravel.physics.joint_fit` provides admission, input discovery, resource bounds
and a fresh-output study driver around the bounded profiler. Each supplied
source point explicitly partitions every retained source coordinate into free
and conditioned sets. Free source coordinates must be signal-absent background
normalization factors. Every signal-response coordinate is conditioned at its
published initial value, and the driver verifies that this is the literal
nominal-template point. A changed response coordinate is refused.

For each source point, the driver compares a fixed-latent baseline with one or
two separately specified complete fixed-N MC experiments. It retains every
fit, failed attempt, work count and fixed-strength likelihood ratio. Source
main observations, control-region signal and rebuilt background auxiliaries
remain present. The original source fixed flags and the caller's conditional
mask remain distinct. A maximum of two points, three fixed strengths per
point and two MC experiments admits at most 24 fits within a separately
approved outer limit of at most 300 seconds. Each fit has its own charged work
budget and at most 30-second wall hook. Exhausted work yields failure evidence.

The driver also records the MC auxiliary log density at its initial latent
point. Adding that value to a fitted NLL removes the experiment-specific
constant. In a controlled central-count experiment with common marks and
probabilities, this permits comparison of the fixed-strength penalized
objectives across MC exposures. Globally recentered likelihood-ratio curves
need not follow the same ordering.

The official stau input census has 120 scalar parameters in each of the two
prepared patched workspaces. Removing the source signal-strength parameter
leaves 119 source coordinates and 117 source auxiliary factors. The conditioned
study frees `mu_W` and `mu_QCD` and explicitly holds the other 117 coordinates
at their source initial values. The 74 non-luminosity signal-response modifier
names are a subset of the source model, not its total nuisance dimension.
The separately supplied MC categories describe a controlled statistical
experiment. Published yields and statistical-error widths do not establish a
native generator sampling law.
