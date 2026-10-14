# Supplied background families and discrete native profiles

`ravel.physics.background_construction` constructs bin-integrated background
components and lowers each complete candidate to `statistical_construction`.
`background_discrete_profile` is an ordinary version-2 science mode. It prepares
and runs serial instances of the existing `native-likelihood` Combine adapter;
it does not contain an optimizer or execute a fit during preparation.

The input is a question-directed regional law plus the complete declared
background candidate population. Observations are disjoint Poisson counts only
when the supplied partition evidence says so. All original signal terms,
including signed interference and control-region contamination, remain in every
candidate. The supplied Gaussian auxiliary block, its lower covariance factor,
correlations, observed values and bounds also remain identical. A table of
overlapping regions or weighted observations cannot become this law implicitly.

## Integrated families

The fixed-basis kinds are `bernstein`, `fixed_integer_powers`,
`histogram_templates` and `linear_templates`. The continuously normalized
`exponential` family is described in [its construction contract](parametric-exponential-construction.md). Its floating slopes are evaluated at
every point; its fractions are not frozen into the rational basis table. The
`floating_power` family also has continuously normalized bin integrals,
including exponent −1 and 0; see [its contract](parametric-power-construction.md).
Bernstein degree is 0–12. Fixed
integer powers span −12 through 12, excluding −1, on a strictly positive domain.
The fixed-integer API still excludes −1; use the explicitly floating family
for the logarithmic limit. Templates contain the full ordered knot population and all
nonnegative density heights, with either constant or linear interpolation
explicitly selected. Heights are densities, not unlabelled bin counts. There is
no extrapolation or guessed interpolation outside the supplied source interval.

Every fixed basis component is analytically integrated with rational arithmetic and
normalized over the same full source domain. Exact bin fractions are retained;
neither bin centers nor numerical quadrature replace the integral. Each
candidate coefficient is a nonnegative expected component count over that full
domain, before the shared bin transfer. There is no additional free overall
normalization multiplied by unconstrained mixture amplitudes. Arbitrary
dependence between the supplied bases is not ruled out by this parameterization;
fit identifiability and conditioning still require qualification.

`bin_windows` follows the complete regional bin order. `null` means an explicitly
absent contribution. Windows can coincide for different event selections, but
the disjoint-count claim still needs its own source justification. A component
with no support in any modeled observation refuses. Transfers supply a complete
nonnegative coefficient vector, optional powers of shared nonnegative physical
rates, and an all-bin response to the common correlated auxiliary coordinates.
The final whole law goes through the original namespace, domain and parameter
checks. A common transfer parameter can first appear in the new family; dummy
baseline-only terms are unnecessary. Literal zero signal/background components
are preserved. The constructor never clips a nonpositive total mean into the domain. Native
optimizer trial-point error handling remains the upstream implementation; its
retained warnings and failed proposals require review.

The family is **added** to the supplied baseline. The caller must explicitly
choose which existing background components belong in that baseline. This API
never guesses which source process to replace. It conditions on supplied template coefficients by default. An explicitly supplied
unweighted Poisson MC normalization law can be composed into the full regional
law with `poisson_template_auxiliary`; see the exponential construction contract.
Weighted, signed and fixed-total marked multinomial consumers remain separate;
no MC uncertainty is inferred, silently Gaussianized or discarded from a
purported unconditional result.

## Native comparison and correction

`write_native_population(spec, output, runtime=..., fit=...,
candidate_seconds=[...], overhead_seconds=...)` writes every candidate's ordinary
native input and a `background-discrete-profile` handoff. The fit must be an
observed Combine 9.2.1 `MultiDimFit` grid with `absolute_nll: true`.
All candidates have exactly the same runtime, full grid, POI, minimizer settings,
observations, auxiliary law and baseline mean. Each has its own explicitly
bounded background coefficients. No candidate, auxiliary constraint or signal
control contribution is selected or removed by the runner.

The native command adds `--saveNLL`, `--saveSpecifiedNuis all`, the exact generated
`ravel_mean_<bin>` population through `--saveSpecifiedFunc`, and
`--X-rtd REMOVE_CONSTANT_ZERO_POINT=1`. The ordinary native extractor retains
the full numeric tree and ROOT files. Every floating nuisance branch is required
at every returned best-fit/grid row. Fixed source coordinates are separately
identified as source declarations; they are not fabricated per-point native
measurements. Native workspace witnesses and saved native objects retain their
existing scope.

Every returned floating physical/auxiliary coordinate must be a literal finite
Float_t value. Its exact closed IEEE round-to-nearest cell must intersect the
original native binary64 domain (the existing bridge writes .17g bounds).
Midpoint ties are conservatively included; this establishes only compatibility,
not the precise pre-rounding point. No bound or returned value is clipped, and
no arbitrary coordinate epsilon is introduced. Conversion semantics require the
stated native runtime qualification.

Every actual saved native full-mean function must also be finite and strictly
positive. Missing, negative, zero or unrepresentable leaves refuse. A positive
native Double_t mean can underflow to a zero Float_t leaf; that refusal is
ambiguous representability, not a finding that the physical mean was negative.
The full source mean is not recomputed at rounded nuisance coordinates and
mislabelled as the exact native state. Independent native/source density parity
remains unqualified until the separate admitted witnesses run. These checks
happen after durable raw-return retention and before the next candidate.

The [Combine 9.2.1 discrete-profiling example](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/docs/part3/nonstandard.md#discrete-profiling)
compares fixed-candidate curves using `deltaNLL + nll + nll0`. This adapter uses
that absolute-NLL recipe on its restricted, common regional law. Comparing only
the separately zeroed `deltaNLL` curves is forbidden. Exact rational arithmetic
on the returned floating terms prevents an extra reduction-rounding loss; it
does not recover precision already lost in native leaves. In particular,
Combine stores `deltaNLL`, scanned coordinates and saved nuisances as floats.

The supplied correction is `factor × number of floating background coefficients`
in NLL units. It is recorded separately and added once. A factor of 1/2 adds one
per coefficient to twice NLL; a factor of 1 adds two. There is no automatic
choice or asserted coverage. The upstream [RooMultiPdf implementation](https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit/blob/v9.2.1/src/RooMultiPdf.cxx)
counts nonconstant variables and defaults to factor 1/2; its AIC enum uses 1.
That variable count is not a fitted matrix rank. The current route expressly
counts candidate-specific floating coefficients, leaving common coordinates
out of the model-dependent correction. The equivalence of correction
*differences* needs an identical common variable population. It does not claim
the same absolute RooMultiPdf count or automatic RooMultiPdf traversal.

This implementation runs the finite candidate set through actual existing
native continuous fits, then takes its discrete minimum on exactly matching
returned grid coordinates. Every candidate's raw return, correction, branches
and ties are retained. The reference is the minimum of all **retained** corrected
values, including native best-fit rows. It is labelled a retained-point reference,
not a certified global minimum. No interval interpolation, CLs, discovery
probability, covariance or automatic MINOS interpretation is produced.

The [discrete-profiling paper](https://arxiv.org/abs/1408.6865) motivates the finite
set of continuous minimizations and discusses bias/coverage for particular
examples. It does not qualify this supplied population, these parameter
boundaries or this native implementation. The normal review must assess
optimization, source family applicability, missing alternatives and calibration.

## Execution, output and remaining qualification

Ordinary `science.task_inputs` binds all population inputs, each native model
and runtime, the source-defined construction, and this implementation. The
whole allowance is the sum of per-candidate ceilings plus explicit overhead.
Native commands are serial. The adapter refuses before another call if the
remaining full candidate allowances do not fit inside the whole ceiling. The
existing stage supervisor retains the hard outer deadline and cleanup authority.

The candidate census starts with every row `not_executed`. A raw child return is
saved before checking its status or computing comparisons. A failed candidate,
missing grid/nuisance term, differing actual coordinate, changed input or
retention failure prevents a successful envelope. No hidden retry follows.
Ordinary worker `result.json`, verification, Check-In 2 and report paths carry
that status; the comparison table always includes failed/unexecuted rows.

Pure controls establish integrated algebra, construction and inert API behavior.
No actual native build, full-density parity, fit, multiple-start qualification,
empirical calibration or published-analysis applicability has been performed
for this new operation. Before scientific use, root must admit the concrete
source/runtime/candidate population and resource budget. The first useful native
test is the same common law in fixed candidates with independently evaluated
absolute NLL at multiple parameter points, followed by full nuisance scans and
failure/offset comparisons. Statistical coverage is a separate experiment.
