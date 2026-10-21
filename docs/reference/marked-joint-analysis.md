# Complete marked-response statistics consumers

This private successor composes with immutable C6 (286 members, seal `4a3d31b9...`). It implements the ordinary `joint-fit` subtype `response_family: complete_marked_categories`. Existing absent-discriminator joint-fit and all other C6 routes retain their exact source. The implementation reuses the existing analytic joined law and SLSQP/LP profiler; it introduces no optimizer, approximate Gaussian MC likelihood, external backend translation, or automatic calibration.

## Implemented operations

A single input binds one or more complete workspace/MC/response cases. Each case declares the source measurement, signal samples in every source channel, complete source-bin permutation, exact background auxiliary policy (including the original background source for pooled-MC rebuilding), and the complete same-group mark ledger. `source_bound_semantics` labels every compiled source coordinate's lower and upper bound as physical or numerical. Original fixed flags and source bounds remain authoritative. Caller `fixed_source` masks are conditional subproblems, never silently treated as original fixed parameters.

Each case has an explicit request population:

- `shape`: supplied complete latent probabilities and source points produce raw normalized joined NLL/gradient/means plus the full same-population cross-point template covariance. Covariance is exact only for the admitted fixed-N linear estimator with constant denominator marks; variable denominators keep their first-order delta label. It is never inserted as an additional Gaussian constraint. Covariance is for the mu=1 template; raw density points retain their supplied mu.
- `profile`: a free-strength fit and every supplied fixed-strength point use the existing complete analytic profiler. It accepts an optional complete fixed-latent reference and explicit conditional source mask. Every returned normalized NLL and fit record is retained. The raw signed twice-NLL difference is stored even when nesting fails. Only an additional diagnostic field uses the existing 1e-5 nesting tolerance; original fit results are not rewritten.
- `finite_mc_comparison`: run the same profile grid with the supplied complete latent reference fixed and with the full finite-MC probabilities free. Both use the same original normalized auxiliary experiment. Each lane has its own free-strength baseline. No ordering of recentered curves, interval, CLs or global-minimum conclusion is inferred.

All categories, including zero-count and unselected support, stay in the density. Probabilities are checked and never renormalized. No nuisance prior is sampled. Each source auxiliary and the complete multinomial factor occurs once. Model compilation, fits, shape evaluations, covariance requests and all declared fit work are counted prospectively. Fit wall ceilings can be explicitly admitted up to 300 seconds via an optional WorkBudget ceiling; all old callers retain the 30-second default. The consumer requires the stage to contain the sum of declared per-fit ceilings, with the caller responsible for appropriate setup/verification margin. The ordinary supervisor remains necessary for blocking callbacks.

## Corrected numerical search/domain interface

On this absolute-response branch only, the numerical denominator search restriction is `(d/max(abs(d))) dot p >= 1e-10`. Common finite mark scales such as 1e-200 and 1e200 therefore give the same search row. The raw denominator, original probabilities and density formulas are unchanged. Loss of a nonzero coefficient during normalization refuses. This is still a restricted numerical search, not proof that every physical optimum is covered. Positive-observation probability floors remain dimensionless numerical restrictions.

The old multiplicative branch imposed reference-template `W_reference p >= 0`. That condition is not valid for an absolute transported response at a different nuisance point: e.g. a negative category can move from the fitted bin to the explicit outside category. The new branch removes the reference linear rows and no longer calls reference `MC.nominal()` to obtain auxiliary means. `complete_auxiliary_means` checks the complete MC population independently; the actual signal/background nonnegativity and strict denominator are checked by the existing full source+MC nonlinear response constraints and density. The old nominal API, its physical domain, and all legacy branches remain intact. The original normalized Poisson/Normal/multinomial summation tail is byte-identical.

## Derivatives and external native interfaces

The consumer requires the exact byte-bound MarkedResponseProvider and its complete-domain C1 mark-law binding. It must not substitute HS3/Combine finite-difference diagnostic estimates. The native derivative stream's `profiler_derivative_qualified: false` and `agreement_has_accuracy_authority: false` remain meaningful: h/h2 agreement, even with contracting actual nodes, does not certify smoothness, absence of common bias, Hessian inversion, or covariance.

## Source controls and empirical limits

Seventeen one-worker controls passed in 0.071 seconds. They include actual extracted linear-constraint assembly, exact signed-transport and common-scale algebra, genuine tiny source/ledger capture (including an opaque source pin), source-mask/bound refusal, the ordinary route discriminator, and the real adapter's serialization and failure paths with injected fake numerical objects. The numerical engines/compiler/LP/fit entry points were barred. The initial four mock-transport errors came from macOS's symlinked default temporary path; the fixtures now resolve their own temporary root. The original failure log and test draft remain.

The software controls exercise the supplied mark-law and derivative contracts. Native runtime, numerical, sampling-law and detector qualification each require source-bound scientific evidence.

## Composition

Apply only the explicit seven-source patch to the matching C6 source (five changed and two new files), plus the portable test and this reference document. In particular, apply the two-line `science.adapter` hunk; do not replace a moving workflow module from an older capsule. C6's HS3 derivative, Contur, MPI and other routes remain present. The current worker already records returned `status: failed` and refuses stage success; no new supervisor or worker authority is introduced.
