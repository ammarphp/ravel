# Native NLL finite differences

The optional HS3 derivative selection uses the existing supplied-model import
and fixed-point RooFit NLL evaluator. It adds no optimizer, likelihood formula,
native runner, Gaussian constraint, or inference operation. The implementation
is a private source candidate until independent review and integration.

Add `derivatives` to an HS3 configuration and select exactly one ordinary source
anchor. For example, a nonzero signal-strength anchor can retain the original
source nuisance defaults while varying signal strength and a shape nuisance:

```json
{
  "selection": {
    "analysis": "original_source_analysis",
    "parameter_point": "default_values",
    "points": [{"id": "mu1", "parameters": {"mu": 1.0}}]
  },
  "derivatives": {
    "axes": [{"name": "mu", "step": 0.2}, {"name": "shape", "step": 0.1}],
    "max_points": 64
  }
}
```

Names must resolve to the supplied graph; the example creates no model or
physics input. Only continuous floating coordinates can be axes. Planning
rejects source constants and data covariates. The native ModelConfig then
confirms every axis is a POI or nuisance and excludes globals, conditional
observables, data observables, and unrelated floating variables.

The prospective plan preserves complete source parameter order, values and
constant flags, the intersection of original and selected coordinate bounds,
the exact model/runtime/evaluation definition, and the existing NLL convention
(`NLL`, without a factor of two). No nominal-yield approximation is introduced.
Every evaluation uses the original evaluator's full native-state reset,
including implicit variables outside the source snapshot. Complete native
parameter rows and the original data/ModelConfig remain in `native-evaluation.json`.

For each requested axis the planner chooses three distinct binary64 nodes at
step sizes h and h/2. Central nodes are preferred; a complete forward or backward
stencil is used near a boundary. Values are never clipped, the physical domain
is never enlarged, and an unrepresentable or insufficient stencil refuses.
Coefficients are derivatives of the interpolating polynomial at the anchor,
using the actual assigned nodes rather than ideal decimal spacing. Mixed terms
use tensor products of the first-derivative weights. All generated points must
fit the explicit bound, at most 256 points and seven axes.

The adapter retains `derivative-plan.json`, `derivative-observations.json`, and
`derivative-estimates.json`. The pure reducer requires every ordered point,
coordinate and constant flag, with finite NLLs and the exact planned identity.
It subtracts the common anchor and reduces the returned binary64 values with
exact rational arithmetic. This avoids extra cancellation introduced by the
reducer; it cannot recover information already lost during native NLL
evaluation or rounding. The h/2-minus-h differences are diagnostics, not error
bounds, convergence proofs, or certified arithmetic enclosures.

Differentiability is not established by this operation. A stencil crossing a
source interpolation kink is a finite difference across that kink; it cannot
certify a gradient or Hessian of a smooth model. A source-backed regularity
contract is still required before a smooth profiler consumes these estimates.
Boundary directions and all assigned nodes remain explicit. No KKT,
stationarity, covariance, global-optimum, fit-quality, CLs, coverage or physics
claim follows from a derivative table or a RooFit covariance.

This candidate is based on current C3 source, including its existing HS3
fixed-point route. It does not silently transplant the separately qualified
published serializer/bound-metadata worker into C3. The published TriHiggs
model still needs that exact serializer source integrated and freshly bound
before native derivative execution can use it. The ready nonzero-signal
published endpoint follow-up uses the unchanged separately frozen 229-file
qualified route and remains a separate study.

Portable controls exercise independent polynomial laws, boundary directions,
actual representable node moments, NLL rounding loss, complete-state reset,
native-role refusal, staged source identity, retained derivative outputs, and
real ordinary unapproved planning. All ROOT/process delivery in those unit
controls is explicitly mocked; actual native derivative qualification requires
a new ordinary plan, CHECK-IN 1, root lease and independent result review.
