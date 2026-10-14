# Figures and comparison with published results

RAVEL reads published figures, compares a result with them and draws comparison figures.
Four tools share one specification style: strict JSON with `"schema_version": 1`, paths
relative to the specification file, and output directories that must be new or empty.
Every figure passes the house plot lint and every label must be natural language
("Four-lepton invariant mass", not `m_4l` or `Muon.PT`).

| Tool | Command | Writes |
|---|---|---|
| Digitise a figure | `ravel figure digitize --spec S --out D` | `digitized.json`, `review.png` |
| Compare with a reference | `ravel compare --spec S --out comparison.json` | the comparison object |
| Parameter-plane figure | `ravel figure plane --spec S --out D` | `NAME.pdf`, `NAME.png`, `NAME.json` |
| Measurement overlay | `ravel figure measurement --spec S --out D` | the overlay, an optional side-by-side figure, `NAME.json` |

`ravel figure inventory PAGE.pdf` lists the paths, fills and text on a PDF page, which helps
pick colours and regions. Inside a run, use the `figure-comparison` scientific study so the
work is planned, approved and reviewed like any other study (see below).

Prefer tabulated values. Use HEPData when the figure has a table; digitise only when it
does not.

## Digitise

Vector PDFs are read directly: the content stream is walked with the full transformation
matrix, so stroked curves, markers and filled bands come out in page coordinates. Axes are
calibrated from the tick labels on the page, from declared tick values, or from declared
anchors, on linear or logarithmic scales. A series is selected by colour or by its legend
entry.

```json
{"schema_version": 1,
 "source": {"path": "figure-3.pdf", "page": 1},
 "axes": {"x": {"label": "Mediator mass", "unit": "GeV", "calibration": {"method": "tick_labels"}},
          "y": {"label": "Coupling", "unit": "", "scale": "log", "calibration": {"method": "tick_labels"}}},
 "series": [{"name": "observed", "label": "Observed limit", "kind": "line", "select": {"legend": "Observed"}}]}
```

Images (PNG, JPEG and others) need declared pixel anchors on each axis and a colour to trace.
The output records the source hash, page, calibration anchors and residuals, and per-point
uncertainties. Open `review.png` and check that the extracted points sit on the intended curve
and the anchors sit on the labelled ticks before using the series.

## Compare

A comparison names an `agent` source, a `reference` source and the `kind`: `binned`, `curve`,
`contour`, `region` or `scalar`. Sources can be inline values, a file, a `binned_values`
result, a HEPData table (`{"hepdata": "table.json", "column": 0}`) or a digitised series
(`{"digitized": "digitized.json", "series": "observed", "as": "curve"}`; `"as"` can also be
`bins`, `contour` or `region`).

Changes of representation are declared, applied in order and recorded:
`fraction_to_density`, `density_to_fraction`, `rebin` (to existing edges), `rebin_matrix`
(with a reason), `unit`, `normalize` (unit area or a declared total), `scale` (with a reason),
`relabel` (with a reason) and `select` (an x range). Nothing is converted silently: different
units, quantities or bin edges stop the comparison until a transformation is declared.

Binned metrics on matched bins:

- relative L2 difference `||a - b|| / ||b||`, the same after unit-area normalisation (shape),
  and the signed normalisation offset;
- total variation distance, the largest single-bin difference and their ratio (at least 2/K
  for K bins);
- per-bin pulls, chi2 with every supplied covariance (agent, reference, digitisation and
  declared systematics) and its p-value, and the binned Kolmogorov-Smirnov statistic;
- Poisson deviance, only when the reference is declared as raw observed counts
  (`"reference_counts": "raw_observed"`); weighted counts are refused.

Curves are compared at the reference points or at declared `at` values in the declared axis
scales. Contours use the symmetric Hausdorff distance (largest and mean) in fractions of the
declared axis ranges, with logarithmic axes measured in decades, and the `tip` position in a
declared direction. Regions use intersection over union and the area ratio. Scalars give the
pull, relative deviation and resolving power (prediction uncertainty over reference
uncertainty).

Tolerances decide the verdict. Each needs `pass`, `warn` and a typed `basis`:

```json
"tolerances": {
  "shape_l2": {"pass": 0.05, "warn": 0.10,
               "basis": {"kind": "published_precision", "source": "Uncertainties in the HEPData table"}},
  "delta_norm": {"pass": 0.10, "warn": 0.20,
                 "basis": {"kind": "supervised_spread", "n": 5, "evidence_sha256": "<sha256>",
                           "evidence": "independent reference reruns"}}}
```

The other basis kind is `{"kind": "community", "citation": "..."}`. The raw L2 difference
never decides a verdict alone. Bins present on one side only make the comparison incomplete.
The verdict is PASS, WARN, FAIL or INCOMPLETE, with a hint that says what the difference is
compatible with (normalisation, selection or detector, or statistics). The hint is advice and
never triggers a correction. The comparison object carries a `summary` in plain sentences;
figures and reports show that summary.

## Parameter-plane figures

Declare the axes once and one or more panels. A panel can hold a `grid` of surfaces
(`observed`, `expected`, `expected_1sigma` and `expected_2sigma` with `low` and `high`) with the
exclusion `level` and whether points `below` or `above` it are excluded; a `colour_map` of one
surface; one-dimensional `limit_curves` with bands; disjoint excluded `intervals`; `theory`
curves; labelled `points`; and `references` drawn on the same axes. A reference with
`"compare": {"with": "observed", "kind": "contour", "tolerances": {...}}` gets a comparison
object, and its summary appears next to the legend.

```json
{"schema_version": 1, "name": "plane",
 "axes": {"x": {"label": "Mediator mass", "unit": "GeV"},
          "y": {"label": "Coupling to quarks", "unit": "", "scale": "log"}},
 "layout": {"columns": 2},
 "panels": [{"title": "Width equal to 1 percent of the mass",
             "grid": {"x": [...], "y": [...], "level": 1.0, "excluded": "below",
                      "observed": [[...]], "expected": [[...]],
                      "expected_1sigma": {"low": [[...]], "high": [[...]]}},
             "references": [{"label": "Published observed limit",
                             "source": {"digitized": "digitized.json", "series": "observed"}}]}]}
```

Surfaces are lists of rows, one row per y value.

A grid can come straight from a statistics `inference.json`: `{"inference": "inference.json",
"x": "mass", "y": "coupling", "surfaces": {"observed": "<result name>"}, "bands":
{"expected_1sigma": {"low": "<name>", "high": "<name>"}}}` reads the product grid and its
`grid-values` results; missing values stay blank. A reference can be a `contour` result of the
same record (`{"inference": "inference.json", "result": "<name>"}`) or any plot-coordinate-series
document.

## Measurement overlays

The overlay draws data with total uncertainties (and statistical caps when supplied), each
prediction with its uncertainty band, a ratio panel and, optionally, a panel with the signed
difference from the denominator. A prediction with `"delta_from": "sm"` holds a signed
difference, such as signal-background interference; it is drawn as the total, and negative
bins are kept and listed. A logarithmic axis refuses a total that is not positive; use a linear
axis or the difference panel. `official` draws the published series (HEPData points or a
digitised curve) on the same axes, and `"side_by_side": true` adds a figure with the published
series and this result in two panels. `comparison` either reads a saved comparison object
(`{"path": "comparison.json"}`) or computes one between a prediction and `data` or `official`.

## Inside a run

The `figure-comparison` scientific study runs an ordered list of operations:

```json
{"operations": [
  {"name": "published", "kind": "digitize", "specification": "digitise.json"},
  {"name": "agreement", "kind": "compare", "specification": "compare.json"},
  {"name": "figure", "kind": "measurement-overlay", "specification": "overlay.json"}]}
```

A later operation reads an earlier one with `{"operation": "published", "series": "..."}`
sources or `"comparison": {"operation": "agreement"}`. Planning reads every specification,
checks these references and pins every input file. `ravel figure plan --task task.json` shows
the files a task reads. Outputs go under `figure-comparison/<name>/`, and the figures appear in
the study's `figures.json` and CHECK-IN 2 packet. All verdicts are machine comparisons; physics
review stays with the reviewer.
