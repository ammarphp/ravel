# Continuously normalized dijet families

This source implementation prepares ordinary regional likelihood and discrete
background-population tasks. It does not run ROOT, fit data, select a family or
qualify an analysis. The standalone legacy `shape_fit.py` midpoint/clipping
implementation is not used by this route.

For a supplied mass `m`, energy scale `sqrt_s` and `q=m/sqrt_s`, the density is

```
g(q) = exp(alpha*log(1-q) + beta1*log(q) + ... + betaJ*log(q)**J)
P(bin) = integral_bin g(q)dq / integral_full_domain g(q)dq
```

The coefficient signs are explicit: in the conventional denominator form
`(1-q)**p1 / q**(p2+p3*log(q)+...)`, `alpha=p1`, `beta1=-p2`, `beta2=-p3`, etc.
The full-domain rate is a separate parameter. A common coefficient-dependent
centering factor cancels from both integrals. Physical mass units cancel through
the common Jacobian; both native integrals use the same dimensionless variable.

`dijet3` declares one rate and two shape coefficients (`alpha,beta1`);
`dijet4` declares one rate and three shape coefficients (`alpha,beta1,beta2`).
`dijet_log_polynomial` permits `1<=J<=4`, with every coefficient declared.
The naming refers to the total rate-plus-shape parameter count. Rates and shape
coefficients retain their supplied fixed flags, bounds, sources and meanings.
The supplied complexity penalty counts every floating background coefficient,
including the rate and each shape coefficient, consistently with other families.

Each bin receives its actual interval integral, with full-domain normalization.
An absent `None` window contributes zero. Gaps retain unobserved mass; fractions
are never renormalized to the observed windows. Different supplied regional
observations may share a mass interval, but their existing declared Poisson
partition must still justify distinct counts. This family does not infer that
partition or remove contamination or signal/interference terms in control regions.

## Source schema and preparation

The ordinary `ravel.physics.background_construction.construct(spec)` accepts a
candidate family of the form below, inside a complete source-bound background
specification. This example provides integration settings, not an experimental
fit specification:

```python
family = {
    'kind': 'dijet4',
    'sqrt_s': '13000',
    'parameters': ['dijet_alpha', 'dijet_beta1', 'dijet_beta2'],
    'parameter_response': [['0', '0'], ['0', '0'], ['0', '0']],
    'integration': {
        'native': {
            'engine': 'RooIntegrator1D',
            'absolute_tolerance': '1e-12',
            'relative_tolerance': '1e-10',
            'max_steps': 16,
        },
        'reference': {
            'absolute_tolerance': '1e-12',
            'relative_tolerance': '1e-10',
            'max_depth': 20,
            'max_evaluations': 200000,
            'maximum_probability_error': '1e-8',
            'maximum_gradient_error': '1e-7',
        },
    },
}
```

`parameter_response` has one row per ordered coefficient and one column per
source auxiliary. Use empty rows when there are no auxiliaries. The source law is
`theta=z+L*eta`, shared with the full regional mean and its Gaussian auxiliaries;
the effective coefficient is its physical value plus that row times `theta`.
Every shape coefficient must have role `coefficient`, be candidate-specific and
be source-bound. Candidate parameters are the rate first, then every ordered
shape coefficient. The family has no user formula, callback or optimizer.

The lowered shape has kind `normalized_dijet` and the exact closed keys
`sqrt_s,domain,bin_windows,parameters,parameter_response,integration`. A direct
regional construction can also declare that shape on a nonnegative background
term. Transfer powers and log responses remain on the term, so one full-domain
rate can participate in the supplied common SR/CR transfer law. All baseline
terms, observations, auxiliary factors, assumptions, and finite-MC law are retained.

Prepare the entire supplied candidate population through the existing writer:

```python
from ravel.physics.background_construction import write_native_population
packet = write_native_population(
    complete_source_specification,
    fresh_output_directory,
    runtime=authenticated_native_runtime,
    fit=observed_absolute_nll_grid_specification,
    candidate_seconds=complete_per_candidate_ceilings,
    overhead_seconds=explicit_overhead_ceiling,
)
```

The writer calls the existing regional `write_native_bundle` for each candidate
and emits the ordinary `background-discrete-profile` task. Its required census
remains all ordered 2..16 supplied candidates. It prepares files and reports
`native_calls_executed=0`. Original native runtime authentication, input snapshots,
admission, process ceilings, complete population checks and failure preservation
apply when a later authorized study executes that task. `native_likelihood.inputs`
pins the new implementation whenever a source construction contains this shape.

## Bounded numerical contract

Source and binary64 intervals must satisfy `0<q_low<q_high<1`. Every window is
inside the full supplied domain, with distinct representable endpoints. There
are at most 256 windows and five shape coefficients. Validation propagates the
complete physical and auxiliary box, including observed auxiliary offsets.
Every effective coefficient obeys `|coefficient|<=100`; monotone-feature triangle
bounds enforce centered `|log g|<=80` throughout that entire box and continuum.
A conservative full-box lower probability must remain representable. These
are numerical admission bounds, not fit-quality or extrapolation criteria.

The pure reference integrates the density and all centered logarithmic moments
together using recursive adaptive Simpson with Richardson correction. It checks
its explicit absolute and relative estimated convergence tolerances at each
subdivision. These tolerances must lie in `[1e-14,1e-6]`. Declared depth is 4..24
and a single call has a shared 32..200000 evaluation budget over its denominator
and every numerator. Depth, budget, nonfinite arithmetic and unresolved positive
normalization failures raise errors. There is no quadrature fallback or clipping.

For each coefficient `c_j`, it computes

```
dP/dc_j = integral_bin g*f_j / D - P*integral_full g*f_j / D
```

where `f_j` is the centered source feature and `D` is the full integral.
The common centering derivative cancels. Estimated integral errors are propagated
through the normalization and this derivative. Every probability/gradient must
meet the supplied `maximum_probability_error` / `maximum_gradient_error`, each
in `[1e-12,1e-4]`. `reference` returns these error estimates, evaluation and
subdivision counts, and explicit non-certification metadata. Their reliability
has not been proved over every admitted source box. Analytic-limit and arithmetic
controls do not certify numerical integration or scientific results.

The native bridge uses the original RooFit PDF/integral engine. It emits a closed
`RooGenericPdf` via the uppercase `EXPR` factory, then calls original
`RooAbsReal.createIntegral` with `RooArgSet(variable)`, `NumIntConfig(config)` and
one named `Range`. It supplies **no NormSet**: numerator and denominator are raw
integrals of one common density. A `RooFormulaVar` divides each raw bin integral
by the raw full-domain integral. The integration variable is constant and is not
added to the POI or extra nuisance list. It introduces no hidden fit coordinate.

The density owns its copied special integrator configuration; integral objects
retain that configuration and are imported into the ordinary workspace with
`RecycleConflictNodes`. Configuration is local to that density. It does not
mutate the global RooFit default. Native tolerances are explicit and in the same
`[1e-14,1e-6]` range. The supported closed policy is `RooIntegrator1D`,
`sumRule=Trapezoid`, `extrapolation=Wynn-Epsilon`, `fixSteps=0`, and `maxSteps`
in 8..20. It sets `minSteps=maxSteps+1` for a precise source-derived reason:
in the original integrator, that setting controls only the early zero-threshold
return. A strictly positive density must not disappear through that shortcut.
The ordinary absolute/relative extrapolation convergence branch is separate and
still stops early; this policy does not require every integral to hit maxSteps.

The original trapezoid refinement uses at most `2**(maxSteps-1)+1` density
evaluations per integral invocation (32769 at the example's 16 steps, 524289 at
20). This is not a ceiling for a fit, repeated integral calls, PDF normalization
or total RooFit work. Existing task process budgets provide the execution ceiling.
The integrator warns and returns its final estimate on nonconvergence; configured
epsAbs/epsRel or RooFit success do not provide a certified error bound. Native
diagnostics remain preserved by the existing adapter. Native parity/convergence
qualification is required before scientific use.

## Original API evidence and later qualification

The module's `UPSTREAM_API` pins the exact original ROOT `v6-22-08` sources by
URL and SHA256. Important contracts are in original
[RooAbsReal.cxx](https://github.com/root-project/root/blob/v6-22-08/roofit/roofitcore/src/RooAbsReal.cxx)
(raw-integral versus NormSet semantics, lines 543..608; special owned config,
lines 3530..3599),
[RooIntegrator1D.cxx](https://github.com/root-project/root/blob/v6-22-08/roofit/roofitcore/src/RooIntegrator1D.cxx)
(config fields, lines 53..70 and 126..149; distinct zero and normal convergence,
lines 275..345; trapezoid evaluation counts, lines 390..416), and
[RooRealIntegral.cxx](https://github.com/root-project/root/blob/v6-22-08/roofit/roofitcore/src/RooRealIntegral.cxx)
(configuration pointer, lines 90..150). The original source is provenance;
configured runtime identity and behavior still require their own qualification.

The conventional signed-coefficient mapping follows the functional form in
the [CMS dijet-search presentation](https://indico.cern.ch/event/568360/contributions/2446908/attachments/1440404/2217258/CMS-dijet-searches_v4.pdf).
The generalized degree cap and numerical envelopes are this implementation's
explicit contract, not a claimed recommendation or experimental acceptance.

Before scientific qualification, independently review source composition with
floating-power and calibration-consumer changes; compare native persisted raw
integrals and means to independent reference methods and convergence scans over
complete representative physical/auxiliary boxes; check narrow bins, tails and
endpoint proximity; investigate all native integration warnings and error-estimate
reliability; qualify derivative transport, full finite-MC and SR/CR likelihood,
all candidate failures, discrete penalty choice and calibration. No such study
has been executed by these source controls. All previous scientific failures,
standing questions, 130 strands, 16 families, 18 comparators and full 52-point RS1
qualification obligations remain intact.
