# Inference engines

RAVEL has five science modes for statistical inference on supplied numbers. Each one reads a
single JSON document, evaluates exactly what it declares, and writes `inference.json`. They run
through the ordinary study lifecycle: `ravel plan`, `ravel approve`, `ravel run`, then CHECK-IN 2.

| Mode | What it computes |
|---|---|
| `prescribed-statistic` | The statistic a request prescribes, as the primary result: a closed-form formula on a grid, or a binned Poisson profile likelihood with per-bin nuisances. CLs can be added alongside. |
| `formula-grid` | Declared formulas (widths, branching ratios, bands, factors) over a parameter grid, with contours. |
| `coupling-morphing` | A polynomial in couplings fitted to cross sections or binned yields from several runs. |
| `search-statistics` | Signal, control and validation region models in pyhf: discovery significance, CLs, background-only fits. |
| `differential-likelihood` | A Gaussian likelihood for a measured spectrum with full covariance and signed (interfering) signals. |

## Which statistic is primary

When a request prescribes a statistic, record its wording in `statistic.verbatim`. That statistic
is the primary result. For an exclusion request with no prescribed statistic, RAVEL's default is
95% CLs. CLs requested alongside a prescribed statistic is labelled `companion` and never replaces
it. `inference.json` records the origin as `prescribed`, `default` or `not-applicable`.

Values that the requester supplies (an efficiency, a K-factor, a transcribed table) are recorded
as requester assumptions with the requester's statement. Values from a paper or note carry a
citation. A document without one of these is refused.

## Using a mode

```sh
ravel inference modes                                  # list the modes
ravel inference example --mode prescribed-statistic > stat.json
ravel inference check --mode prescribed-statistic --input stat.json
ravel inference spec --mode prescribed-statistic --input stat.json --policy review.json \
  --source "Table 1 of the paper; signal templates from run X" \
  --assumption "Background uncertainties are uncorrelated between bins" --out spec.json
ravel plan --rundir my-study --spec spec.json
```

`check` validates the document and lists every input file with its sha256. `spec` writes the
schema 2 study specification; the review policy follows
[scientific review for adapter studies](../workflow/reference/science-review.md). Nothing is
computed before approval.

The task in the study specification is `{"input": "<document>.json"}`. Paths inside the document
are relative to the document. Vectors can be literal lists or file references:

- `{"path": "bkg.json", "format": "binned-values"}`: the `values` of a binned_values result, with
  `sumw2` (or `uncertainty` squared) as the MC variance;
- `{"path": "table.yaml", "format": "hepdata", "column": 0}`: one dependent column of a HEPData
  table (index or header name);
- `{"path": "numbers.json", "format": "json", "key": "b"}`.

Matrices are literal nested lists, a two-axis HEPData table (`"format": "hepdata"`), or JSON. A
HEPData correlation table becomes a covariance with `"kind": "correlation", "errors": <vector>`.

## prescribed-statistic

### Closed form

```json
{"schema_version": 1, "kind": "prescribed-statistic",
 "statistic": {"kind": "closed-form", "verbatim": "Sig = 2(sqrt(S+B) - sqrt(B)), contour at 2"},
 "grid": {"axes": [{"name": "g1", "unit": "", "label": "Coupling g1", "min": 0, "max": 1, "points": 101},
                   {"name": "g2", "unit": "", "label": "Coupling g2", "min": 0, "max": 1, "points": 101}]},
 "program": {"constants": [{"name": "B", "value": 120, "unit": "events", "origin": "requester-assumption",
                            "statement": "B = 120 events"}],
             "definitions": [{"name": "S", "expression": "400 * (g1**2 + g2**2)", "unit": "events"}],
             "outputs": [{"name": "Sig", "expression": "2 * (sqrt(S + B) - sqrt(B))", "unit": "",
                          "label": "Significance"}]},
 "statistic_output": "Sig", "threshold": 2, "region": "at-or-above"}
```

A one-axis grid gives the parameter intervals where the region holds, with crossings refined
between neighbouring grid points. A two-axis grid gives contour lines at the threshold.

The formula language allows numbers, declared names, `pi`, `+ - * / ** %`, comparisons,
`and`/`or`/`not`, `a if condition else b`, and the functions `sqrt exp log log10 sin cos tan asin
acos atan atan2 sinh cosh tanh abs min max pow where`. Anything else is refused before evaluation.
Definitions are evaluated in order. Units are labels carried into the record.

### Binned profile likelihood

Each channel (for example one experiment) lists `observed`, `background` and
`background_uncertainty` per bin. The per-bin mean is `background + signal`, with one nuisance per
bin profiled independently. `nuisance_form` selects the law:

- `gaussian-linear`: mean `b(1 + theta) + s`, `theta` Gaussian with width `db/b` (the pyhf
  `staterror` law); `background_floor: nonnegative` keeps the fitted background at or above zero;
- `poisson-gamma`: the pyhf `shapesys` law with auxiliary count `(b/db)^2`;
- `lognormal`: mean `b (1 + db/b)^theta + s`, `theta` standard normal;
- `none`: fixed background.

Channels are independent and their log-likelihoods add. The signal is one of:

- `{"kind": "linear", "templates": {...}}`: signal strength times template;
- `{"kind": "power", "reference": g0, "power": k, "templates": {...}}`: `(g/g0)^k` times the
  template simulated at `g0`;
- `{"kind": "polynomial", "morphs": {"<channel>": {"path": "coupling-morph.json"}}, "fixed": {...}}`:
  a fitted coupling polynomial per bin, which can be negative (interference).

`test_statistic` is `two-sided` (the region where Delta(-2 ln L) is at or below `threshold`),
`one-sided-upper` (zero below the best fit) or `discovery` (q0 against `null`, reported as a
significance). Use `hypotheses: [{"id", "coordinates", "signal"}]` for one result per mass point.
`expected: true` adds the background-only Asimov expectation; `companion: {"cls": true}` adds pyhf
CLs for linear and power-law signals, converted to the scanned parameter.

## formula-grid

The same `grid` and `program` as the closed form, plus optional
`contours: [{"output", "levels", "x", "y"}]`. Every output is reported at every grid point;
nonfinite points are listed by index.

## coupling-morphing

```json
{"schema_version": 1, "kind": "coupling-morphing",
 "parameters": [{"name": "g1", "unit": "", "label": "First coupling"}, {"name": "g2", "unit": "", "label": "Second coupling"}],
 "quantity": {"name": "xsec", "unit": "pb", "label": "Cross section"},
 "basis": [{"g1": 2}, {"g1": 1, "g2": 1}, {"g2": 2}],
 "amplitudes": [{"g1": 1}, {"g2": 1}],
 "method": "exact", "max_condition": 1e6,
 "runs": [{"id": "r1", "point": {"g1": 1, "g2": 0}, "value": 2.0, "uncertainty": 0.02}, ...],
 "holdout": [{"id": "h1", "point": {"g1": 0.5, "g2": 1}, "value": 0.9, "uncertainty": 0.02}],
 "closure_tolerance_sigma": 3,
 "width": {"treatment": "fixed", "value": 1.5, "unit": "GeV", "source": "..."},
 "evaluate": {"axes": [...]}}
```

The basis can be written out, or derived:

- `amplitudes`: the coupling orders of each amplitude term (`{}` for a term without the
  couplings, such as a Standard Model amplitude). The basis is every product of two terms, so
  interference terms of mixed degree are included. For example `[{}, {"g": 1}]` gives
  `1, g, g^2`.
- `degree`: `{"total": 4, "homogeneous": true}` gives every monomial of total degree 4.

When `basis` is given together with `amplitudes` or `degree`, they must agree; a mismatch names the
missing and extra monomials.

`exact` needs as many runs as monomials; `weighted-least-squares` needs at least as many, each
with an uncertainty, and reports chi2 and its degrees of freedom. The condition number of the
column-scaled design matrix must stay below `max_condition` (the raw value is also reported).

At least one held-out run is required. Each gives a pull per bin against the combined uncertainty
of the run and the fitted prediction; any pull beyond the tolerance fails the study. A quantity
that is not a polynomial in the declared basis is caught here.

The width declaration is required:

- `fixed`: `value`, `unit` and `source`;
- `morphed`: its own `runs` and `holdout` (and optionally `basis`), fitted with the same method;
- `not-applicable`: a `reason`.

Runs can give per-bin `values` (lists or file references) to morph whole templates. The fit is
written to `coupling-morph.json` with `usable: true` only when every held-out comparison passed.
`prescribed-statistic` and `differential-likelihood` read a morph only when it is usable.

The design matrix, SVD solve, covariance propagation and held-out comparison live in
`ravel.physics.coupling_polynomial`, which the SFitter scan extractor also uses.

## search-statistics

The document declares `regions` (role `SR`, `CR` or `VR`; `observed: null` for a blinded region),
`backgrounds` with per-region `values` and `sumw2` and an optional `normfactor`,
`signal_points`, and:

- `mc_statistics`: `staterror`, `shapesys` or `none`;
- `systematics`: a registry (below), inline or `{"path": ...}`;
- `data`: `{"mode": "observed"}` or `{"mode": "mc-pseudo-data", "injections": {"top": 1.2}}`;
- `computations`: `discovery`, `cls_at_nominal`, `cls_limits`, `background_only_fit`, and
  `allow_blinded_signal_regions` for observed control regions with blinded signal regions;
- `asimov_source`: `nominal` or `background-only-fit`;
- `cls_level`, `mc_adequacy` (`max_relative_uncertainty`, `min_effective_entries`) and `contours`;
- `statistic`: `{"origin": "default"}` (CLs primary) or
  `{"origin": "prescribed", "verbatim": "...", "primary": "discovery"}`, with optional `claim`
  (`local`, the default, or `global`) and `independent_tests` (boolean) for a scan;
- `statistics_choices`: optional seat choices `{"<situation>": {"method", "justification"}}`
  (see [Statistics situations and validity](#statistics-situations-and-validity)); a choice for a
  situation no signal point can present is refused.

Every point with CLs limits or a discovery significance carries a `statistics` record, and every
CLs limit an `uncertainty` statement; a discovery scan over two or more points adds one
look-elsewhere record. They become `statistics` diagnostics in `inference.json`, and their
qualification and hold labels join its `limitations`.

Validation regions never enter a fit. The background-only fit uses the control regions with
iminuit and reports normalisation factors, pulls, the correlation matrix, post-fit predictions
with residuals in every region, and a goodness of fit (see below). Expected discovery significance uses an Asimov dataset at signal
strength one. CLs uses the guarded optimizer of `pyhf_exclude`. MC adequacy flags mark bins with a
large relative MC uncertainty, few effective entries, or nonpositive yields.

### CLs calculator: asymptotics or toys, recorded

`cls_calculator` is `"asymptotic"` (default), `"auto"` or `"toybased"`; `"auto"` and `"toybased"`
need `cls_toys: {"count", "seed", optional "max_fits", "max_seconds"}`. Every `cls_limits` result
carries a `calculator` block: the request, what was applied, the small-count triggers (main bins
with fewer than five observed or background-only expected counts, the threshold the counting
flags already use) and the reason. `auto` applies pyhf's toy calculator when a trigger fires;
an explicit request is honoured with the triggers still recorded. Toy limits are the log-linear
crossings between seeded toy points around the asymptotic roots, with first-order binomial MC
uncertainties and a crossing interval; the asymptotic result stays in the record as the bracket
reference. The toy budget is checked before the main ensemble, on the toy-experiment count and,
with `max_seconds`, on the wall time projected from a measured pilot of a few toys (drawn from its
own seeded stream, so the main ensemble does not depend on it); a refusal keeps the asymptotic
headline and records the recommendation and the pilot, never silently. Coverage is not validated
by either calculator.

### Published background covariance (simplified likelihood)

`background_covariance: {"regions": [...], "covariance": [[...]] | "correlation": [[...]], "errors": [...],
"third_moments": [...], "blocks": [[...], ...], "source": "<citation>"}` replaces the systematics
registry by a published covariance of the background predictions (a simplified likelihood). The
listed regions order the matrix, with bins flattened within each region; a correlation needs the
per-bin `errors`; optional `third_moments` select spey's third-moment expansion; optional
`blocks` partition the regions into independent sets (zero cross-covariance, checked) that are
combined through spey's uncorrelated combiner. The variant is signal-region only: no control or
validation regions, no normalisation factors, `systematics` null, `mc_statistics` `"none"` (signal
MC statistics are not represented), `asimov_source` `"nominal"`, no discovery significance,
background-only fit or goodness of fit. Observed quantities need observed counts in every region;
otherwise the record is expected-only with a `missing` observed limit. The engine is
`spey-simplified-likelihood` (spey 0.2.6); every CLs root is bracketed and re-evaluated by RAVEL
on spey's confidence levels and typed through `ravel.limits`. The source citation is required.

### Model construction and builder parity

`model_construction: {"builder": "cabinetry" | "native"}` builds the HistFactory model through
cabinetry (`cabinetry.workspace.build` on template histograms written under the study's
`model_construction/` folder) or through RAVEL's native builder. Both builders always run; the
record carries a `model-construction` diagnostic with one parity record per built model:
channels, samples, nominal yields, MC-statistics widths, normalisation factors and the set of
constrained parameters must agree exactly, and every systematic's templates must agree at its
plus and minus one-sigma points, otherwise the construction is refused (`mismatch`). Specs that
are identical after canonicalisation are `identical`; a shape systematic that cabinetry represents
as a normalisation factor plus a yield-normalised shape while the native builder keeps one
absolute template is `equivalent-at-one-sigma`, and the CLs at unit signal strength of both
representations is recorded with its relative difference. cabinetry represents MC statistics as
`staterror`, so a `shapesys` document must not be built through it. Without the key the document
behaves exactly as before.

### Systematic-uncertainty registry

```json
{"schema_version": 1,
 "sources": [
   {"name": "luminosity", "kind": "normsys", "relative": 0.017,
    "applies_to": {"samples": "all", "regions": "all"}, "correlation": "correlated",
    "origin": "cited", "citation": "luminosity paper, table 3"},
   {"name": "top_generator", "kind": "histosys", "construction": "one-sided-symmetrised",
    "applies_to": {"samples": ["top"], "regions": ["SR", "CR"]}, "correlation": "correlated",
    "alternative": {"SR": [12.0, 6.0], "CR": [110.0]},
    "origin": "cited", "citation": "alternative generator sample"}],
 "absent": [{"component": "jet energy scale", "reason": "nominal-only samples"}]}
```

`normsys` takes `relative`, `up`/`down`, or `relative_by_region` (`{"<region>": 0.05, ...}`: one
constrained parameter under the source's correlation model with a different magnitude per listed
region, the form of a published per-region uncertainty breakdown; `applies_to.regions` must list
exactly those regions). `histosys` builds variations from alternative-sample
yields: `one-sided-symmetrised` mirrors the alternative about the nominal, `one-sided` keeps the
nominal as the other side, `two-sided` takes `alternative_up` and `alternative_down`. A mirrored
variation below zero is refused. `correlation` is `correlated`, `per-region`, `per-sample` or
`per-sample-and-region`. Every registry lists its known missing components in `absent`. The record
includes a comparison of each alternative sample with the nominal.

The search engine also writes `systematics_selfcheck.json`: for each source, its impact on the
background templates, whether it has no impact, whether another source has an identical shift
vector, its share of the total systematic variance, and whether a shape variation is in fact a
flat shift.

## differential-likelihood

The prediction is `reference + sum_k m_k(p) v_k`: the published reference plus a signed
polynomial difference (for example `kappa^2 I + kappa^4 S`). `signal.convention` must be
`difference-to-reference`, and `signal.difference_reference` states the reference the difference
was taken from. A prediction that already contains the reference is refused, so the reference is
never counted twice.

The covariance is a sum of components with scaling laws in `R = prediction / reference`:
`fixed`, `ratio` (`R_i R_j C_ij`) and `sqrt-ratio` (`sqrt(R_i R_j) C_ij`), plus the MC covariance
of the term vectors when supplied (`mc_covariance`, or the morph covariance). A covariance that is
not positive definite, or exceeds `max_condition`, makes that scan point missing; it is never
repaired.

Nuisances shift the prediction by `nu` times a vector: `relative` to the reference, `relative` to
one term (`"applies_to": "term:0"`), or an `absolute` shift. Each has a unit Gaussian constraint and
is profiled exactly. `objective` is `chi2` (the usual published chi-square) or `gaussian` (adds
`ln det C`).

The scan gives Delta(-2 ln L) to the best fit and, separately, to the reference point (all
parameters zero); the second can be negative and is reported as it is. Allowed regions can be
disjoint, for example around zero and where destructive interference returns the prediction to the
reference. `hypotheses` gives one analysis per mass and width point.

`statistic.toys` (`n`, `seed`, `method` `neyman` or `cls`, `points`, `confidence_level`, `null`)
runs a toy construction at the listed parameter values. Without `statistic.verbatim` the default
statistic is toy CLs, which is then primary.

### Applicability checks

- Unfolding validity: `applicability.unfolding` with `max_relative_deviation` and a citation (or
  requester statement) flags every scanned value where the prediction differs from the reference by
  more than that in any bin. Interval edges in that range are marked `outside_unfolding_validity`.
- K-factors on interference: a term with `kind: interference` and a `scale` needs a nuisance on
  that term; otherwise the record lists `unconstrained_interference_k_factor`.
- Interpretation notes: every record lists the physics checks in
  `src/ravel/data/inference/interpretation_traps.json` (Landau-Yang, CP-odd continuum
  interference, CP-even and CP-odd interference in CP-even observables, signed-weight
  normalisation, interference K-factors, unfolding validity, reference double counting).

## Goodness of fit

Fits report a `goodness-of-fit` result. The statistic compares the fit with a saturated model that
reproduces the main measurements exactly; constraint terms stay at the best fit.

```json
"goodness_of_fit": {"toys": 500, "seed": 1, "max_seconds": 300}
```

With toys, each toy draws new main counts and new auxiliary measurements at the best fit, and the
fit is repeated on the toy. The p-value is `(k + 1) / (N + 1)` and the 95% toy band is reported.
Without toys, or when the budget ends before a toy completes, the chi-square approximation is
reported as `method: asymptotic` with its degrees of freedom. A goodness of fit that keeps the
auxiliary measurements fixed is never the reported one.

- `prescribed-statistic` (binned profile) and `search-statistics` (control-region fit) take the
  `goodness_of_fit` block.
- `differential-likelihood` reports the chi-square at the best fit with its asymptotic p-value.

## Statistics situations and validity

`ravel.physics.inference.situations` is a catalogue defined in code of the statistics situations
RAVEL detects in its inputs. For each one it gives the methods that treat it, cheapest first, the
installed code that provides each method, the validity checks each method owes and a qualified
fallback. Its generated export, `src/ravel/data/inference/statistics_situations.json`
(`python -m ravel.physics.inference.situations catalogue --check`), is what deciding seats receive.

| Situation | Revealed by | Methods (cheapest first) | Fallback |
|---|---|---|---|
| `derived-quantity-propagation` | derived quantities of uncertain inputs | linear, sampled (split-normal for asymmetric errors), correlation bracketing | widest interval over the stated correlation range (qualified) |
| `systematic-nuisances` | systematic sources in the model | profiled nuisances, correlation bracketing | most sensitive single region (qualified) |
| `low-counts` | an exclusion from main bins below five observed or expected counts | asymptotic CLs, toy CLs, exact one-bin reference | asymptotic CLs (qualified) |
| `low-count-significance` | a discovery significance from such bins | asymptotic q0, background-only toys | asymptotic q0 (qualified) |
| `combination` | two or more inputs to combine | independent product, joint likelihood with shared parameters | most sensitive single input (qualified) |
| `likelihood-availability` | what the analysis published | published, simplified, constructed likelihood, counting | none: held |
| `limited-mc-statistics` | bins with a large MC relative uncertainty or few effective entries | staterror, shapesys, exact finite-MC model | not modelled (qualified) |
| `look-elsewhere` | a significance over two or more hypotheses | local significance, upcrossing trials factor (one-dimensional scans), Sidak (independent tests) | local significance (qualified) |
| `model-validation` | a model constructed or supplied here, or an estimate | signal injection, validation-region closure, coverage toys | not evaluated (qualified) |
| `parameter-estimation` | a fitted parameter | quadratic errors, profile likelihood, toy Neyman | profile interval near a boundary (qualified) |
| `efficiency-acceptance` | efficiencies from selected and generated entries | normal, Wilson, Clopper-Pearson, weighted | Clopper-Pearson (qualified) |

On the constructed and simplified rungs of the likelihood ladder, the closure checks compare each
published benchmark limit with the limit the same model gives for the benchmark's yields
(`--reference-limits`). The checks recompute the relative differences. A miss beyond 20% holds the
result. Without published limits, or a declared absence with its reason and evidence, the result
is qualified.

A check is decided from the inputs (`facts`) or from the computed result (`result`), and states
what a failure means: escalate to the method's stronger successor, qualify the result with a
stated label, or hold it. The default is the cheapest available method that applies to the inputs
and whose input checks pass. A method passed over is recorded with its reason, so asymptotic
formulae are used exactly when their conditions hold, and toys or a fuller treatment are chosen
automatically otherwise. A method can state when it applies: the toy calculators sample and refit
a HistFactory model, so they do not apply to a simplified likelihood. When a result check fails,
the engine escalates and runs the stronger method. A method that a declared budget refuses is
recorded with that refusal, and the result is qualified with the fallback's label. A search
document without `cls_toys` or discovery `toys` declares no toy budget. A seat can choose another
listed method or the fallback, with a justification. A seat's choice is never escalated; its
failed checks qualify the result.

The `statistics` record holds the facts, the assessment, the decision with any escalation
chain, the evidence and the validity: `valid`, `qualified` (with labels) or `held`. `audit`
recomputes the assessment, the decision and the validity from the facts and evidence, and checks
that every escalation's check fails on that evidence and that every budget claim has its refusal
(`python -m ravel.physics.inference.situations audit --record <file>`). A record made with
another catalogue version is refused. Passing the checks does not certify a result: the
thresholds are conventions recorded with each check.

The `uncertainty` statement of a reported number lists its components by kind: statistical,
systematic and method. A component that was not evaluated carries its reason. The statement also
lists what is included and what is not. For a CLs limit, these are:
- the expected band;
- the systematic impact, against an expected limit with the constrained parameters fixed (for
  models up to 60 parameters);
- the numerical or toy precision of the roots;
- on the constructed and simplified rungs, the closure against the published benchmark limits;
- the registry's absent components, MC pseudo-data and blinded regions.

Intervals give statistical and systematic parts. Propagated quantities and efficiencies give
their own components.

Producers:
- `pyhf_exclude.py` (every subcommand; `--statistics-choices`, `--uncertainty-breakdown`; a held
  record exits 3);
- `search-statistics`;
- `python -m ravel.physics.inference.profile --workspace W.json [--patch P.json]
  [--parameter NAME ...] --out estimation.json` for profile intervals (exit 3 when held);
- the propagation and efficiency modules.

On the analysis route, step 07 refuses a limit without a record that recomputes, refuses a held
outcome, requires every qualification label in the result's `limitations`, and requires a valid
uncertainty statement. Scan points owe the same records. The delivery sink withholds a held
record and qualifies a qualified one (`QUALIFIED: STATISTICAL VALIDITY`). The statistics seats
receive the catalogue export as a run input pinned by digest.

`python -m ravel.physics.inference.situations assess --facts F.json [--choices C.json]` shows a
seat the detected situations and the defaults before anything runs.

Outside the controller, `result_pack.py` carries the uncertainty statement and the record's outcome
into `result.json`. It recomputes the record against the packed region counts, refuses a held or
inconsistent record, and adds each qualification label as a `statistics-qualified` scope condition.

A scan carries each point's record and statement into `scan.json`. The harvest recomputes every
point's record. A held or inconsistent point is an explicit hole, never a harvested limit. The
assembly lists each qualification label with the points it applies to, and the sink recomputes
every point's record.

## Computed review checks

Every `inference.json` carries `computed_checks`: alarms computed from the record itself, each
`pass`, `warn` or `fail`, with its location and any proposed fix. `computed_check_summary`
counts them.

| Alarm | Fails or warns when |
|---|---|
| `closure` | chi2/ndf above 3 or a held-out pull above 5 (fail); chi2/ndf below 0.1 (warn) |
| `fit-triviality` | a chi-square of exactly zero, or a fit returning every parameter at its input (fail; warn for MC pseudo-data) |
| `parameter-at-bound` | a parameter at or near a fit bound or physical boundary (warn) |
| `nuisance-pulls` | a pull above 3 sigma; an RMS of five or more pulls below 0.7 (warn) |
| `systematic-dominance` | one source above 80% of the systematic variance; a flat shift used as a shape variation (warn) |
| `systematic-selfcheck` | a source with no impact, or two sources with identical shifts (fail) |
| `reference-deviation` | more than 30% from a declared well-measured reference (fail) |
| `goodness-of-fit` | p below 0.05, or a fixed-auxiliary goodness of fit (fail) |
| `excluded-bins` | more than half of the bins excluded from a fit (fail) |
| `open-at-edge` | an interval, best fit or contour touching the edge of the evaluated points, or a limit at the scan floor or median at the ceiling (fail, with a proposed extension) |
| `validity-status` | a fit without a validity status, or with a failed one (fail) |
| `statistics-validity` | a statistics record that does not recompute or is held (fail); a qualified one (warn) |

A document can change a threshold only with a recorded basis, and can declare references:

```json
"review": {
  "thresholds": {"gof_p_value_min": {"value": 0.01, "basis": "the analysis tests at 1%"}},
  "references": [{"label": "published observed limit", "path": "results[3].parameter_limit.observed",
                  "value": 1.2, "source": "HEPData table 5"}]}
```

At CHECK-IN 2, scientific review recomputes the alarms from the retained outputs (every
`inference.json`, and the boundary and censoring flags of other result files). A failure blocks
any claim scope that needs a scientific check. A diagnostic scope stays available; a correction
whose new outputs pass clears the block. Reviewers must not overwrite a computed result.

## The inference record

`inference.json` has `mode`, `engine`, `status`, `statistic` (`origin`, `verbatim`,
`definition`), `parameters` (name, unit, natural-language label), `results`, `grid`,
`diagnostics`, `inputs` (path and sha256), `requester_assumptions`, `limitations` and
`physics_validated: false`. Each result has a `quantity` (`grid-values`, `contour`,
`morph-coefficients`, `morph-closure`, `delta-nll-region`, `delta-nll-scan`, `significance`,
`cls-limit`, `cls-values`, `fitted-parameters`, `post-fit-predictions`, `toy-p-values`,
`applicability`, `mc-adequacy`, `systematics`, `goodness-of-fit`, `model-construction`,
`statistics`), a `role` (`primary`,
`companion`, `diagnostic`) and usually a one-line `summary`. The record also carries
`computed_checks`, `computed_check_summary` and, when supplied, `review`.

An interval edge has a status: `resolved` (a sign change bracketed between scan points, refined
and re-evaluated at the root), `domain_boundary` (the declared physical boundary) or
`beyond_scan` (the region continues past the scan; no value is given). A region with a
`beyond_scan` edge is `unresolved` and the study fails; widen the scan in a new study. Nonfinite
values are written as `null` and listed.

The worker draws figures from the record: profile scans with the threshold and allowed regions,
upper edges against a mass coordinate, contours, grid maps, the measured spectrum with the
best-fit prediction, and background-fit pulls. Figures use the house style and natural-language
labels from the document.
