# Continuously normalized floating-power background counts

`background_construction.construct` accepts `floating_power` in the existing
complete candidate population. `write_native_population` prepares the ordinary
`background-discrete-profile` study; individual regional laws also use
`statistical_construction.write_native_bundle` and ordinary `native-likelihood`.
There is no new optimizer, fit runner, arbitrary function language or sampling law.
Preparation does not execute or approve a fit.

For a supplied positive finite domain `[a,b]`, dimensionless exponent `p`,
component yield `Y` and bin `[u,v]`, the contribution before explicit transfers is

```
Y * integral_u^v (x/a)^p dx / integral_a^b (x/a)^p dx.
```

The component coefficient is an expected count on the **full** source domain.
The reference `a` makes the density power dimensionless and cancels in the
normalized fraction. Changing a common x unit therefore changes neither the
exponent nor the fraction. No unit conversion is inferred. At `p=-1`, the
fraction is `log(v/u)/log(b/a)`; at `p=0`, it is `(v-u)/(b-a)`. These are limits
of the same family, rather than separate candidates. A missing window contributes
zero. Unobserved normalization mass remains outside the observed windows;
surviving windows are never renormalized. Coincident windows in different regions
still require their own disjoint-selection/transfer evidence.

The closed family declaration is:

```json
{
  "kind": "floating_power",
  "exponents": ["power1", "power2"],
  "exponent_response": [["0", "0"], ["1/10", "-1/5"]]
}
```

`parameters` declares component yields first (`role: rate`), followed by every
corresponding dimensionless exponent (`role: coefficient`), in that order. One
through eight components are admitted. Every coordinate retains its source ID,
explicit bounds, initial value, fixed flag and physical meaning. Candidate source
IDs must be present in the unchanged regional source census. All floating yields
and exponents count in the existing explicitly supplied complexity penalty;
no rank or identifiable dimension is inferred.

For the original shared Gaussian block `theta=z+L_aux*eta`, component `j` has
`p_effective=p_j+response_j dot theta`. Response rows follow the entire original
auxiliary order and have units consistent with that dimensionless exponent.
The same physical theta also drives existing yield/transfer responses. All
original signed signal terms, including every control-region contribution, and
the complete Gaussian law remain in every candidate. The family is added to
the explicitly supplied baseline; it does not guess which background to replace.

## Numerical/source-native formula contract

Let `L=log(b/a)`, `t=log(x/a)/L`, and `q=(p_effective+1)*L`.
The Jacobian gives `(x/a)^p dx = a*L*exp(q*t) dt`; the constant cancels in the
normalized integral. Bin endpoints in t are computed with stable `log1p` of
original rational ratios. Complete original x endpoints stay in the document.
This is a deterministic binary64 coordinate map, not exact transcendental
rational arithmetic. The admitted domain requires `0<L<=50` and binary64-distinct
positive physical and mapped endpoints. The complete physical/auxiliary box
must satisfy `abs((p_effective+1)*L)<=50`, with a conservative positive-bin
probability floor still representable. These are numerical envelopes, not
physical priors or an asserted applicability domain. Unsupported/unrepresentable
positive windows refuse without clipping.

The existing normalized exponential integral kernel evaluates fractions in t:

```
span * exp(q*(midpoint-1/2)) * sinhc(q*span/2)/sinhc(q/2).
```

The emitted closed RooFormulaVar uses the existing even sinhc polynomial through
degree eight for `abs(z)<1e-3`. The Python path uses the existing anchored expm1
formula and analytic conditional-log-moment derivative. The native auxiliary
`Exponential` object describes the **transformed log coordinate**, not an x-space
RooExponential or an additional observation. The counting means use the explicit
integral functions. The native formula's q coefficient includes the Jacobian's
`+1`; omitting it would turn the logarithmic and constant limits into the wrong law.
At p=0, source evaluation and the closed native expression use the original
rational bin-width ratio directly. At p=-1 the q=0 kernel has no 0/0.

The derivative with respect to p is

```
fraction * (E_bin[log(x/a)] - E_full[log(x/a)]).
```

It generally remains nonzero at both p=-1 and p=0. Gaussian-coordinate derivatives
include the supplied shared factor, and count derivatives include both the
shape derivative and the existing yield/transfer response. There are no density
values at bin centers and no finite-difference replacement in the implementation.

This extends the C26 regional/exponential construction source. Fixed integer,
Bernstein, template, exponential and HistFactory laws are preserved. Formula
controls independently differentiate physical-x antiderivatives with Decimal
precision 150, compare complete partitions and unobserved mass, and exercise
the generated ordinary mean graph using an inert formula evaluator. They do
not import ROOT or certify native numerical behavior.

## Scope and remaining qualification

The native preparation inherits the existing Combine 9.2.1/declared ROOT
RooFormulaVar interface and source/runtime/role gates. Actual installed formula
parsing, full-count/derivative agreement, boundary and invalid-trial behavior,
fit convergence/globality, identifiability, candidate completeness, model
applicability, finite-MC shape uncertainty and calibration remain unqualified.
Conditional template coefficients stay conditional. An explicitly supplied
unweighted Poisson normalization experiment can use the existing
`poisson_template_auxiliary`; no covariance or MC law follows from the density
family itself. Existing calibration consumers that refuse parametric shapes
remain separate dependencies; this addition does not bypass their restriction.
