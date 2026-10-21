# Continuously normalized exponential background counts

`background_construction.construct` accepts an `exponential` candidate in the
same complete population as Bernstein, fixed-power or supplied-template
candidates. `write_native_population` prepares the existing ordinary
`background-discrete-profile` study. A single regional construction also uses
`statistical_construction.write_native_bundle` and ordinary `native-likelihood`.
These functions prepare inputs; the existing plan, Check-In 1, supervised native
worker and independent Check-In 2 review still govern execution and reuse.

The source convention is ROOT's `RooExponential`, proportional to `exp(c*x)`.
The [ROOT 6.24 implementation](https://github.com/root-project/root/blob/v6-24-00/roofit/roofit/src/RooExponential.cxx)
normalizes using the range-dependent integral and has a separate zero-slope
limit. The [Combine 9.2.1 example](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/docs/part3/nonstandard.md#discrete-profiling)
uses a continuously floating exponential slope alongside other candidate
families. This implementation adopts that function convention, without adopting
the example's parameter bounds, data, family-selection criterion or penalty.

For a declared full domain `[a,b]`, component yield `Y`, slope `c`, and bin
window `[l,h]`, the contribution before supplied transfer factors is

```
Y * integral_l^h exp(c*x) dx / integral_a^b exp(c*x) dx.
```

`Y` is the expected full-domain component count. It is not a density height or
a second normalization multiplying free mixture fractions. At `c=0`, the
fraction is `(h-l)/(b-a)`. Missing windows contribute zero and never cause
renormalization over surviving bins. Multiple regions can have the same window
only with their own supplied disjoint-selection and transfer justification.
The domain/window coordinates must use the same declared physical units; slope
parameter meanings and assumptions must state their inverse units. No unit
conversion, data-driven slope, efficiency or correlation is inferred.

The family object is closed:

```json
{
  "kind": "exponential",
  "slopes": ["slope1", "slope2"],
  "slope_log_response": [["0", "0"], ["1/10", "0"]]
}
```

`parameters` contains all component yields first (`role: rate`), then the
corresponding slope coefficients (`role: coefficient`), in that exact order.
Each parameter has the existing explicit initial value, bounds, fixed flag,
meaning and source. One through eight components are supported. Each yield is
nonnegative; slopes can have either sign. The supplied correction counts every
floating candidate parameter, including slopes, and excludes fixed parameters.
Mixture components with equal/overlapping slopes can be poorly identified;
neither the census nor successful source construction proves identifiability.

For the original source Gaussian auxiliary law `theta=z+L*eta`, the physical
slope of component `j` is `c_j + response_j dot theta`. Responses follow the
complete original auxiliary order. This shares correlations with all original
SR/CR and yield responses; no additional slope constraint is invented. The
entire parameter/auxiliary box must satisfy `abs(c_effective*(b-a)) <= 50`.
This is a declared numerical admission envelope, not a physics range or prior.
Binary64-distinct endpoints and normalization widths are required. A conservative
full-box lower probability bound must remain representable; a positive bin can
not silently become absent through underflow.

The native bridge creates a `RooExponential` on `t=(x-a)/(b-a)` with coefficient
`lambda=c_effective*(b-a)`. Its fixed integration coordinate is not an extra
data observation or fitted nuisance. Bin yields use closed `RooFormulaVar`
integrals in a stable form:

```
width * exp(lambda*(midpoint-1/2))
      * sinhc(lambda*width/2) / sinhc(lambda/2),
sinhc(z) = sinh(z)/z, sinhc(0)=1.
```

The small-argument evaluation uses the even Taylor polynomial through degree
eight below `abs(z)<1e-3`, with omitted relative term below `1e-36` there. This
is a binary64 evaluation method for the analytic integral, not a new density
family. The Python reference independently uses anchored `expm1` fractions and
analytic derivatives. Its conditional first moment uses the Bernoulli series
through degree eleven near zero. Neither path clips or renormalizes values.
Pure source controls compare the emitted formulas to independent high precision
antiderivatives. Actual ROOT/Combine agreement, invalid-trial handling and fit
behavior remain separately unqualified. Native mean witnesses and full returned
coordinate/domain checks retain their existing scope.

## Explicit finite-MC normalization experiments

The original conditional-template law remains the default. The new
`statistical_construction.poisson_template_auxiliary` composes only an explicitly
supplied independently Poissonized **unweighted** MC normalization experiment:

```
m_j ~ Poisson(exposure_j * rate_j).
```

The same latent nonnegative rate already enters the main SR/CR means, including
any supplied transfers and signed physical contributions. One count constrains
that shared rate once across the entire main population; it is not independently
repeated in every bin. The helper takes the validated whole law and a complete
list of `{bin,rate,exposure,source,observed,observation_id}`, plus source-bound
sampling and independence statements. The rate's existing bounds, initial value
and fixed flag remain authoritative. Fixing it conditions on that coordinate;
it does not imply a measured precision.

The output has `template_statistics.kind` equal to
`explicit_independent_poisson_auxiliary`, the complete experiment map and
distinct `mc_auxiliary` bins. Each auxiliary mean is exactly its exposure times
its rate, with no signal contamination, log response or second mean term. All
original main-bin coefficients, Gaussian auxiliaries and source assumptions
are retained; zeros are appended for absent auxiliary contributions. The same
ordinary native counting product includes these observations and saves their
full means. This extra region role requires the constructed full-mean source contract.

This composition requires an explicitly justified independent MC experiment.
Review independence and duplicate-sample provenance against the declared source population and sampling law. Reattaching an MC
law, repeating an observation/rate, inconsistent exposure or a contaminated
auxiliary mean refuses. Zero observed counts are allowed, while the existing
strict-positive total-mean native domain remains unchanged; zero-mean boundary
inference is not covered. No fixed-total multinomial, weighted/signed-MC law,
sumw2 Gaussian approximation or automatic shape uncertainty is introduced.
Those laws remain with the existing marked finite-MC consumers. The analytic
shape remains conditional unless its shape uncertainty is separately supplied.

All original signed interference, SM/BSM and CR signal terms enter the complete
main mean once. Individual signed pieces are not assigned independent Poissons.
The unchanged Gaussian covariance, declared MC counts and all source files are
bound by ordinary native intake. The family implementation itself is included
in the launch source census. An unapproved prepared bundle is not a fit,
physics acceptance, global minimum, calibrated interval or exclusion.
