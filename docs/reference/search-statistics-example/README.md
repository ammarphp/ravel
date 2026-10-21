# Synthetic search statistics example

All inputs are invented. The fit uses simulated pseudo-data: background expectations,
with optional injected scale factors, rather than random measurement observations.
Two control regions constrain `scale_alpha` and `scale_beta`. The validation region
is held out. The single-bin target has role `abcd`, treated as a signal region in
the search fit. Its alpha background is estimated from independent external B, C,
D sidebands as B*C/D. Those sidebands must be disjoint from the fitted observations.
The beta background is supplied directly. Five signal points form an irregular grid
whose two interior points are enclosed by three outer points, so the 0.05 contour closes
inside the hull. A contour that reaches the hull of the evaluated points fails the
`open-at-edge` review check and needs more evaluated points.

Run from the checkout with the installed `ravel` environment. These commands use
only supplied synthetic yields, with no native jobs. Use a fresh destination and
review CHECK-IN 1 before approving this scripted example.

```bash
ravel inference check --mode search-statistics --input docs/reference/search-statistics-example/search.json
ravel inference spec --mode search-statistics \
  --input docs/reference/search-statistics-example/search.json \
  --policy docs/reference/search-statistics-example/policy.json \
  --source 'Invented supplied-yield example' \
  --assumption 'All observations are simulated pseudo-data; all yields are invented' \
  --max-seconds 180 --approval-mode scripted_yes --out example-spec.json
ravel plan --rundir trial-runs/synthetic-search --spec example-spec.json
cp docs/reference/search-statistics-example/method.json trial-runs/synthetic-search/inputs/method-decision.json
ravel method-decision --rundir trial-runs/synthetic-search
# Review trial-runs/synthetic-search/CHECKIN1.md.
ravel approve --rundir trial-runs/synthetic-search --scripted \
  --quote 'Authorize this bounded synthetic supplied-yield example only'
ravel run --rundir trial-runs/synthetic-search
ravel status --rundir trial-runs/synthetic-search --write
```

The output directory contains `points.json`, `inference.json`, `contour-1.pdf/png`,
`search-background-summary.pdf/png`, `search-significance-map.pdf/png`, and
`figures.json`. The table and result explicitly state: **The fit uses simulated
pseudo-data.** The reference overlay is a synthetic supplied coordinate series,
pinned by SHA256; replacing it with published coordinates requires a new pin and
matching axes. Acquisition is separate from this example.

`points.json` is always written for valid supplied grids, including one-dimensional
or degenerate grids whose contour is refused. Each row includes the expected median
CLs, observed CLs when unblinded observed data exist, separately named
observed-on-pseudo-data CLs, Asimov discovery significance, signal-region yield,
per-region signal yields and all input pins. CLs and Asimov significance are computed
for the table even if their individual summaries are disabled. These values do not
turn pseudo-data into an measurement observation.

Irregular contours are labelled `interpolated`. `triangulation.coordinates`,
`simplices`, `convex_hull` and `point_ids` record exactly the interpolation vertices
and triangles. Linear segments stay inside the hull. Fewer than three non-collinear
vertices, duplicates, missing values and plateau triangles give an explicit
`not_interpolable` diagnostic; the point table survives. Complete rectangular grids
retain their original contour algorithm unless interpolation is requested explicitly.

Declare `contours.interpolation` as `{"method":"delaunay-linear","coordinates":["x","y"]}`.
An affine coordinate can replace either name, for example
`{"terms":{"x":1,"y":-1},"offset":0}` for a difference. The two coordinates must
preserve an invertible affine map to the plot axes. Triangulation occurs in that
coordinate system; recorded contour segments are mapped back to the declared axes.
Interpolation says nothing about uncomputed model points or holes inside the hull.

ABCD requires `independent: true` and the declared
`uncertainty_treatment: "independent-delta-lognormal"`. Its propagated variance is
A²*(var(B)/B² + var(C)/C² + var(D)/D²); a lognormal modifier uses
sqrt(log(1 + relative_variance)). This approximation is unsuitable for sparse or
strongly correlated sidebands without further validation. It is an external estimate,
not a simultaneous four-region Poisson fit. `closure.json` supplies paired unweighted
binary selections on simulated events. The output records their phi correlation,
quadrant counts, Fisher p-value and the supplied correlation threshold. Exceeding that
threshold flags applicability; it does not silently adjust the estimate.

Optional discovery `toys: {"count":1000,"seed":19,"required_significance":2}` adds
conditional background-only q0 ensembles. Counts are capped at 10,000 per point.
Main and auxiliary observations fluctuate; each toy refits q0. The output reports
k/N, an exact 68.27% binomial interval, its asymmetric maximum deviation as the MC
uncertainty, and the corresponding significance interval. Zero tails are unresolved,
with a significance bound rather than a finite value. A declared significance beyond
the count's resolution or the cap is refused before computation. Null nuisance
parameters are plug-in values; these toys do not validate general coverage.

Alternative-generator histosys sources declare `alternative_kind: "generator"`
and `sample_metadata` with `nominal` and `alternative` (or both `alternative_up`
and `alternative_down`). Each entry contains nonblank `process` and `campaign`.
All must match. Missing metadata or mismatches are refused. Legacy unspecified
histosys sources remain template variations with comparability `not-declared`.

The summary figure shows process contributions before and after the CR-only fit,
normalisation-factor errors and held-out validation residuals. Post-fit background
uncertainties include mapped prior variances for parameters absent from the CR fit.
The significance map colours actual evaluated points and overlays the interpolated
contour; marker colours are never extrapolated. Software tests on these inputs do
not establish detector fidelity, physical ABCD closure or coverage.
