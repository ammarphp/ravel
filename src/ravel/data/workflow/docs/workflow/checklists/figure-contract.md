# Checklist — the FIGURE CONTRACT  ·  [judgment] declares · [agent] extracts/composes

A reproduction is only checkable if the run states, **up front**, the specific published figure it is
reproducing ("Figure N of arXiv:XXXX.XXXXX") — echoes it to the physicist at the step-2 check-in —
and, at the end, emits the generated counterpart **side-by-side** with it. The contract lives at
`<rundir>/inputs/figure_target.json` and is owned by `src/ravel/plotting/figure_target.py`.
It is fully general: nothing in the protocol is tied to any one analysis — the figure↔data linkage
is the paper-agnostic fact that HEPData table names very often literally carry the figure id
("Figure 7 Observed …"), which `hepdata_fetch.py` indexes as `figure_index` on every discovery pass.

**On the controller.** The contract is written by plan step `inputs.figures` (`outputs/figure_target.json`,
with `gallery.json` and the waypoint proposal `waypoint.json`), reviewed by a `figure-critic` seat and checked
before CHECK-IN 1: every target records its published axis scales and its source, and every requested figure panel
has a target.

## The contract file (schema_version 1)
`targets[]`, one per figure the run reproduces (typically one `summary` + optionally one `overlay`):

| field | meaning |
|---|---|
| `primary` | the headline target (one per run) |
| `role` | `summary` (exclusion contour/limit figure) or `overlay` (yield/distribution figure) |
| `paper` | `{arxiv, inspire, code}` — at least one id, so the reference is precise |
| `figure_id` | normalized `"Figure 16a"` form (declare accepts `fig 16a` / `Fig. 16(a)` / …), or null |
| `caption_snippet` | first sentence of the published caption (the textual anchor) |
| `source` | how the id was resolved: `user-prompt \| registry-hint \| hepdata-table-name \| paper-inspection \| description-only` |
| `hepdata_tables` | the HEPData table name(s) backing the figure (from `figure_index`) |
| `extracted_image` | `{path, route: arxiv-tex-map\|pdf-page\|none, pdf_page}` — the published pixels |
| `generated_counterpart` | `{path, step: 05-visualize\|08-scan}` — this pipeline's figure |
| `side_by_side` | the composed published-vs-generated PNG (from `compose`) |
| `declared_at_checkin` / `verified_by_physicist` | the echo + confirmation audit trail |

## Resolution precedence (how `figure_id` gets decided — [judgment], never auto)
| rank | source | mechanism |
|---|---|---|
| 1 | **user-prompt** | the requester named the figure ("reproduce Fig 3 of arXiv:…") → `declare` directly, no resolve |
| 2 | **registry-hint** | `figure_manifest.py --figure-hint <supplied.json>` (request-selected source metadata; confirm against the source) |
| 3 | **hepdata-table-name** | `figure_target.py resolve` ranks the manifest's `figure_index` by role + model keywords; **it prints candidates and exits — [judgment] reads the descriptions and chooses**, then calls `declare` |
| 4 | **paper-inspection** | read the paper (`fetch_figures.py`, the PDF) and identify the figure by eye |
| 5 | **description-only** | no figure id resolvable — declare a caption/description and raise it at the CHECK-IN |

## Extraction routes + the degradation ladder (`fetch_figures.py --figure <id>`)
1. **arxiv-tex-map** — parse the saved source tarball's `.tex` (main file → `\input` order → figure
   envs in document order, `\includegraphics` + caption, `\graphicspath`), match the figure to its
   extracted file; the whole map persists as `<out>/figure_map.json` (`--map-captions` builds it
   standalone). Numbering follows document order — any inconsistency WARNs and falls through.
2. **pdf-page** — pypdf text-scan for the "Figure N:" caption; rasterize that page via
   `gs -r200` to `figures/figN_pageP.png` (if gs fails, the page number alone is recorded).
3. **textual reference (route `none`)** — no pixels. **A VALID terminal state** provided
   `figure_id` + `caption_snippet` are populated: the physicist verifies against the precise
   reference instead of an echoed image. Never block a run on figure extraction.

## Emission contract (what the run owes at the end)
- Step 5 (`05-visualize`) or step 8 (`08-scan`) attaches the generated figure:
  `figure_target.py attach-generated --figure-id <ID> --path <plot> --step <05-visualize|08-scan>`.
- `figure_target.py compose --figure-id <ID>` emits the side-by-side PNG — published left
  (labelled "published (arXiv:X, Figure N)"), generated right ("this pipeline"); a PDF source is
  rasterized via gs. With no extracted image it emits the generated figure under a
  **textual-reference banner** (the degraded-but-valid form) and exits 0.
- `figure_target.py show` prints the check-in block (paper ids, figure id, caption, image path or
  "NOT EXTRACTED — verify via figure id + caption") — echo it at the step-2 and step-8 CHECK-INs.
- `result_pack.py` embeds the contract top-level in `figures.json` and **WARNs on any declared
  target whose `generated_counterpart` is null** — a declared-but-unfulfilled contract is loud.
- `validate_run_state.py` is **PRIMARY-aware and hard-FAILs** (not WARNs) once generation is
  complete, in **every** task_mode (scan/reinterpret included, where the figure_contract STAGE is
  only level O and does not gate on `side_by_side`): the single target marked `primary` — once it
  carries `declared_at_checkin` — must have BOTH a non-null `generated_counterpart` AND a non-null
  `side_by_side` (run `figure_target.py compose`), or the `figure-contract-fulfilled` invariant
  fails the run. A contract with **more than one target marked `primary`** also FAILs here — the
  single-primary invariant is enforced at validate time, not only on the write path via
  `figure_target.py primary`. Non-primary declared-but-unrendered targets stay advisory (the
  `result_pack.py` WARN above), not a hard fail.

## Figure-SPEC block + the critique loop
Beyond `axes`, the contract carries a `style` block read off the EXTRACTED published figure at
declaration (protocol P1 look-first): `{binning, error_band_style, marker_conventions,
color_encoding, annotation_set (experiment label, lumi, √s, region labels), hatching,
legend_order, panel_structure}` — each a FACT from looking, never a default (scales live in
`axes`). Declare it with `figure_target.py declare --style-json '{...}'` (inline JSON or `@file`);
`show` prints the recorded facts; `read_style()` is the consumption API (mirrors `read_axes`).

Then the **bounded structural-critique loop**:
```
figure_target.py compose  --rundir R --figure-id ID              # build the side-by-side first
figure_target.py critique --rundir R --figure-id ID              # EMIT the task (composite + style facts + rubric)
#   -> hand the printed task to a FRESH-CONTEXT agent that sees ONLY the composite; it returns
#      {"iterations":N,"mismatches":[...],"surviving_mismatches":[...]}
figure_target.py critique --rundir R --figure-id ID --record @findings.json
```
The critic lists STRUCTURAL mismatches only (never aesthetics), distinguishing **defects**
(→ `mismatches`, drive ≤2 fix iterations) from **stated-subset / deliberate deviations**
(→ `surviving_mismatches`, become caption'd deviations in the deck). The loop is bounded at 2
iterations (a warning fires past it). The lint gate owns the LAYOUT half of R6; this loop
owns the CONTENT half — together they cover both halves of the figure check.

## Generality note
The protocol logic carries **no analysis-specific knowledge**: `figure_index` is a regex over table
names on any HEPData record; `resolve` ranks by *role* vocabulary (exclusion/contour/limit vs
yield/distribution/events) plus whatever model keywords the caller supplies; `compose` is
renderer-agnostic (any published image vs any generated PNG/PDF — contour, bars, distribution).
Figure identities and hints come from the actual request and selected source metadata.
The compatibility hint registries are empty; supplied hints never select a required figure.

- **compose stamps provenance** (`composed_by {tool, utc}`): the run-state gate hard-FAILs a PRIMARY whose `side_by_side` is hand-populated (path not on disk, or no stamp) — only `figure_target.py compose` output satisfies the primary contract.


## Source-bound overlays for new targets

A new target naming a published reference requires an agent-versus-reference overlay
**as well as** its side-by-side image. Declare the target, attach its generated
counterpart, then use the ordinary composition command:

```bash
python -m ravel.plotting.figure_target declare --rundir R --role overlay \
  --figure-id 'Figure 3' --source user-prompt --arxiv PAPER \
  --axes-x linear --axes-y log --primary
python -m ravel.plotting.figure_target attach-generated --rundir R \
  --figure-id 'Figure 3' --path R/plots/generated.png --step 05-visualize
python -m ravel.plotting.figure_target compose --rundir R --figure-id 'Figure 3' \
  --comparison-request R/inputs/figure-comparison.json
python -m ravel.plotting.figure_target show --rundir R
```

Prepare the request after the generated artifact exists, so its counterpart pin is genuine.
It can be supplied at declaration when that artifact already exists.
It is a pinned input, not a free command string. The contract exposes both overlay
PNG and PDF, their receipt, the side-by-side, and the comparison disposition.
The existing run-state and result-pack figure gates check the prospective receipt.
Historical targets without this field retain their original contract. A changed
counterpart, request, reference, axis scale, or committed artifact invalidates the
new delivery.

Use genuine numerical reference data first. Three request kinds are supported:

| Kind | Ordinary renderer | Appropriate use |
|---|---|---|
| `existing-numerical` | `scan_contour` | Supplied named-column scan data and a pinned declarative plot specification with genuine reference layers; residual layers require explicit matching normalization and basis. |
| `existing-numerical` | `mass_plane_overlay` | A source-compatible mass or mass-splitting plane with a tested point and an actual limit artifact. This is a one-point overlay, not a recovered full exclusion contour. |
| `existing-numerical` | `overlay_on_data` | Same-bin signal and published data/background YODA with literal count data, linear x, log event-count y, and events-per-bin normalization. Density or incompatible-bin inputs require a different source-compatible route. |
| `numerical` | ordered coordinate overlay | Source-bound agent and official coordinate-series artifacts, retaining their own point order, bin edges, and unknown records. |
| `raster` | calibrated coordinate-on-image overlay | Only when numerical reference data are missing, with a pinned availability disposition and calibrated official image. This is explicitly visual-only. |

Each request has `schema_version: 1`, `kind`, an exact `target` containing the
figure ID and paper dictionary, a `counterpart` pin matching the attached generated
figure, and `applicability` with `state: comparable`, a source explanation, and
nonempty source pins. Every pin is `{path, sha256, size}`; paths identify actual
bounded input files. The public `reference_comparison.file_pin(path)` computes
this tuple without importing a plotting runtime. Admission uses one bounded byte
snapshot per input, retained copies for numerical rendering, and ending byte
checks; it does not certify the scientific equivalence asserted by a caller.

The explicit physics basis has exactly these fields: `quantity`, `model`,
`production`, `width`, `branching_fraction`, `energy`, `normalization`,
`interference`, and `response`. Fill them from inspected sources, including a
sourced “not applicable” when appropriate. Unknown fields must not establish
comparability. Different basis, quantity identity, unit, or scale is refused;
there is no plot-time conversion, rescaling, rebinning, or model transfer.

For `numerical`, `agent` and `reference` are pins to
`plot-coordinate-series` schema 1 JSON. Each document has that complete
`basis`, `axes.x` and `axes.y` (`quantity`, `name`, `unit`, `scale`),
and an ordered `series` list. A series supplies unique `id`, a readable `label`,
`geometry: markers|polyline|bins`, and every requested `records` entry.
Each record supplies unique `id`, finite `x`, and either finite `y` with
`status: delivered` or null `y` with `status: unknown` and a reason.
Bins additionally supply literal `low` and `high` edges in ordered,
non-overlapping interval support. Every binned series in both documents must
have the same complete ordered interval population, including intervals with
unknown values. Equal events-per-bin values on different intervals are refused.
Mixed bin/point geometry also requires a separately reviewed transformation;
this renderer performs none. Unknowns produce
visible gaps and remain in the receipt; point order is never sorted and missing
points are never invented. At least one delivered agent coordinate is required.

Document, axis, series and record fields are checked against the declared schema.
Unrecognized scientific fields are refused rather than retained but omitted
from the figure. A series with uncertainty supplies
`uncertainty: {convention: absolute-y-offsets, meaning: TEXT}`. The meaning is
the supplied source description, not an inferred confidence level or covariance
law. Every delivered record in that series supplies both nonnegative
`error_low` and `error_high` in the y-axis unit; they are absolute offsets from
its literal y value. Unknown records carry no numerical error. The renderer draws
these endpoints, states the supplied meaning on the figure, and retains the
whole population in the receipt. An uncertainty crossing zero on a log axis
refuses; there is no clipping or replacement. Calibrated images map the actual
uncertainty endpoints through the declared log/linear transform rather than
treating offsets as symmetric pixel distances.
If no errors are available, use `uncertainty: {convention: unavailable, meaning: TEXT}`
with the source reason. A series without an uncertainty declaration is also
displayed with an `Uncertainty unavailable: ...` notice; absence never means zero
error. Keep error fields absent from such series. Tasks requiring uncertainty
need an explicit uncertainty model with its scientific evidence.

At final figure gates, kind, counterpart, applicability source inventory and
the complete displayed population are derived again from the original pinned
request and coordinate documents and compared with the receipt. File hashes
alone must not establish that a differently serialized population was displayed.

For `existing-numerical`, the request supplies the basis and axes above, and
`renderer` supplies the fixed original renderer configuration:

| Renderer | Required configuration beyond renderer ID, experiment, com and lumi |
|---|---|
| `scan_contour` | `scan` and `plot_spec` pins. The plot axes must match `data_schema.columns` and the comparison request in quantity, unit and scale. Reference layers are required. Output names and formats come from the supplied plot specification. |
| `mass_plane_overlay` | `contours`, two literal `point` coordinates, `analysis`, `plane: mass\|dm`, `limit_artifact` pin and readable `model_label`. Axes are `m_parent` and `m_lsp` or `dm`, both GeV. Axis names are supplied in the request. |
| `overlay_on_data` | `signal` and `ref` pins, `routine`, `table`, `data_y`, `bkg_y`, readable `label`; optional `stack` pin. Y quantity is `events_per_bin`, unit `events/bin`; basis normalization is `events_per_bin`. Signal scale is exactly one. |

This calls the existing renderer with explicit configuration through `compose`;
no new statistical engine is introduced. The original routines retain their
source-specific interpolation, limit-status, display and uncertainty policies.
Their raw inputs remain available in the receipt. The scan adapter retains the complete supplied scan and plot specification and derives the overlay population from its requested outputs. A numerical overlay is not
independent accuracy or full-task qualification.

For `raster`, the agent uses the same coordinate-series schema. The reference
object supplies matching `axes` and `basis`, an `image` pin, and
`calibration`: `format: png|jpeg`, original `image_size: [width,height]`,
plot-area `crop: [left,top,right,bottom]`, `source_note`, and two
`{pixel,value}` anchors for each of x and y at the respective crop corners.
Pixel y increases downwards. Calibration is affine in the declared linear
coordinate or log10 coordinate, including descending y; nonpositive log values,
degenerate anchors, out-of-crop agent values and incompatible dimensions refuse.
The original image is drawn without interpolation; it is not digitized into data.
If the image is a derived PDF-page extraction, `origin` supplies its source pin
matching the attached official figure and the literal extraction method/provenance.
Otherwise the image itself must match the attached official figure.
For binned agent coordinates the image reference must additionally state
`bin_support: [[low, high], ...]`, the complete source-established official
interval population, identical to the agent support. Calibration of pixels alone
does not establish compatible count normalization or bin boundaries.
`numerical_reference_availability` must record `state: unavailable`, a reason,
and the pinned sources supporting that disposition. Existing numerical data must
use a numerical route instead.

Raster receipts say `visual_only: true`, `numerical_reference: false`, and
`numerical_fidelity: null`. All three routes keep `physics_validated: false`.
Establish numerical fidelity and calibration with independent numerical and source evidence; review completion against the original scientific question.

A description-only synthesis target remains a non-comparison deliverable. For a
new diagnostic whose reference is absent or physically incomparable, explicitly
use `--non-comparison-reason TEXT` and `--reference-disposition no-reference`
or `incomparable-reference`. This records why an overlay is not produced. It
must not discharge a requested comparison; keep that original task obligation open.

## Declarative scan plots

Run the scan renderer only with the request-selected plot specification:

```bash
python scripts/run.py ravel.plotting.scan_contour \
  --scan <scan.json> --plot-spec <plot-spec.json> \
  --experiment <experiment> --com <energy-TeV> --lumi <luminosity-fb-inverse>
```

The CLI presentation arguments must agree with the supplied specification. Missing
inputs raise `PlotInputError` with `code: missing_plot_input`; contradictory axes
raise `axis_schema_mismatch`. No layout, coordinate transformation, reference
population, comparison column, output name or figure number is selected implicitly.

The scan supplies `points`, `n_planned`, and `data_schema.columns`. Each column maps
to `{quantity, unit}`; point records use those literal column names. Existing limit
artifacts retain their typed observed and five expected statuses and brackets.
A mass coordinate and a coupling coordinate use the same column interface.
The scan producer must export this schema with the actual coordinate population.
For an older scan, supply an explicit schema with its original columns and meanings;
do not infer axis identity from particle names.

The plot specification has `schema_version: 1` and these required fields:

| Field | Supplied content |
|---|---|
| `axes.x`, `axes.y` | `{column, quantity, unit, label, scale}`; `scale` is `linear` or `log`; quantities and units must equal the selected data columns. Labels are readable source-derived text. |
| `presentation` | `{experiment, com, lumi}` with explicit positive energy in TeV and luminosity in inverse fb. |
| `layers` | Nonempty ordered list of the selected numerical and reference layers below. Every layer has a readable `label`. |
| `outputs` | Nonempty list of `{path, format}`; format is `png`, `pdf` or `svg`, and each path has the matching suffix. Only these destinations are written. |

Layer `kind` selects `points`, `contour`, `line`, `band`, `reference-contour` or
`residual`. Numerical layers specify `quantity: observed|expected`. Contours also
supply the actual `level`; only supported crossing segments receive a legend.
Lines require one point per x coordinate. Bands supply two ordered expected-slot
`indices` in the complete five-slot limit artifact. Bounds and missing values
never become numerical contour vertices or filled band endpoints. A missing
lattice vertex masks its adjacent triangles; interpolation stays piecewise linear.

Reference layers supply a `reference` object with matching `quantity` and `basis`
(equal to the scan's `model_basis`), literal
`axes: {x: {quantity, unit}, y: {quantity, unit}}`, and ordered `records` carrying
`x` and `y`. No implicit swapping, mass subtraction or reference interpolation
occurs. A residual reference additionally supplies positive `value` per record,
`basis` and `unit`. Its layer supplies nonnegative `match_tolerance` in the actual
coordinate units and `normalization: {field, basis, unit}`. That field is a positive
per-point multiplier. Both basis objects must match the scan's explicit
`model_basis`, and both units must agree. The residual is
`selected_limit * supplied_multiplier / exact_reference - 1`.
`unsupported`, bound, invalid and unmatched records remain separate in the report;
coverage uses the original `n_planned` denominator. No reference value is invented.

Styles such as `color`, `cmap`, `linestyle`, band `alpha` and residual `vmin`/`vmax`
can be supplied per layer; they never select a scientific population or output.
`figsize` controls the supplied canvas geometry. The renderer applies the existing
layout gate before writing. `--no-lint` retains its explicit warning semantics.
The return report and CLI JSON retain axes, full limit population, layer accounting
and the selected outputs; they establish display behavior, not physics qualification.

For an `existing-numerical` comparison, the pinned scan and specification must
contain a reference layer. The comparison gate checks the data bindings before
rendering and again during final receipt verification. It retains both full input
documents, keeps requested formats and filenames, and places those artifacts in
its own delivery directory. The specialized single-point mass renderer keeps its
existing protective mass-axis check; its renderer has a different coordinate contract.
