# Step 5 — Visualize  ·  [judgment] selects + reads · [agent] renders

Run commands from the repository root in Bash. First run `source native/scripts/paths.sh`;
this selects the native build and binary paths, including an existing local toolchain.
`CONDA=$RAVEL_NATIVE_BUILD/tools/miniforge3/bin/conda` — every `$CONDA` below.

Produce the comparison figures from ONE source of truth, in three renderers for three audiences, then
read them against the checklist. The figure FORM is a physics choice (5.0); the renderers are how that
same form is drawn for the paper, for re-plot/hand-off, and for ROOT-native colleagues.

## Division of labour (one source, multiple renderers)
The per-SR yields (`outputs/sr_yields.json`), the signal `.yoda` + the published REF, and the HEPData
exclusion contour are the **single source of truth**. Three renderers draw from it — never re-derive
numbers per renderer:
- **mplhep = PRIMARY publication figures** — the figures that go in the paper / `RESULT.md`
  (`overlay_on_data.py`, `mass_plane_overlay.py`). The reference style.
- **YODA = interchange / persistence** — `write_yoda.py` persists the per-SR yields (+ histos) as
  Rivet-native `.yoda` so the yields are re-plottable and hand-off-able **without re-running** the
  pipeline. Rivet's native interchange format.
- **ROOT = colleague-facing MIRROR (optional)** — `root_figures.py` mirrors the two key figures in
  ROOT (TGraph/THStack) in ATLAS ROOT style, for colleagues whose norm is ROOT. A **mirror** of the
  mplhep figures from the same source, not a re-derivation.

The manifest (5.0) prints this `renderers` block alongside the archetype recipe, so the chosen figure
form and its three renderers are read off together.

## 5.0 Figure selection ([judgment — script-assisted: `figure_manifest.py` emits the recipe; an ESCAPE classification escalates] — MANDATORY, do not choose free-hand)
Before rendering anything, consult the figure-selection manifest so the discriminating figure is chosen
by analysis-type, not by hand. ~85% of detector-level BSM searches fall into 4 counting/cutflow
archetypes (A 0-lepton jets+MET, B multilepton/EW-ino, C 1-lepton+jets, D monojet/MET-binned), each
with a fixed OVERLAY primitive + CERT primitive; the rest are a per-paper escape hatch.
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_manifest \
  --analysis <RIVET_ID>           # known id -> archetype; else:
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_manifest \
  --classify "<one-line routine description>"   # heuristic archetype guess ([judgment] confirms)
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_manifest --archetype <A|B|C|D|ESCAPE>
```
The recipe is a **physics judgment, not a free-hand pick**: it tells you the **discriminating figure +
observable + REF/HEPData table + overlay primitive + tool**, the cross-cutting **renderers** block,
and — for SUSY exclusion searches — the **mass-plane summary** (which HEPData sub-table is the canonical
observed/expected contour). Use it to drive 5.1–5.4. If the manifest returns **ESCAPE** (or
`--classify` is ambiguous), do NOT auto-select — read the routine + paper and choose the bespoke
discriminating observable + canonical HEPData sub-figure yourself.

**Load the figure contract first**: read `<rundir>/inputs/figure_target.json` (declared in step 2 —
`docs/workflow/checklists/figure-contract.md`). The declared `figure_id` + `hepdata_tables` name the SPECIFIC
published figure this run reproduces; the figures rendered below are its counterpart, so keep the
form/axes consistent with it. If no contract exists yet, declare it now (`figure_target.py declare`)
before rendering.

**For every SUSY exclusion search the manifest ALSO returns a `summary_recipe`: the MASS-PLANE summary
figure** — the 95% CL exclusion contour in the m(parent)-m(LSP) plane with the tested point marked.
This is the contract's **headline faithful-FORM deliverable** and no detector-level routine emits it;
produce it in 5.4 whenever a published exclusion contour is available.

**Axis SCALES come from the contract, not from heuristics** (see `docs/workflow/checklists/plot-guidelines.md`):
the published figure's scales were recorded at declaration (`figure_target.json` `axes`, step 2) —
render with `--figure-target <rundir>` so `mass_plane_overlay.py`/`scan_contour.py` consume them
(explicit `--logx/--linx/--logy/--liny` override; the ≥~1.5-decade log heuristic applies ONLY when no
published reference exists). If the contract has no `axes` record yet, read the scales off the
extracted published figure and record them now before rendering.

## 5.1 mplhep primary figures — the publication path ([agent])
The question a scientist asks is "would my model have shown up?" — which means comparing **signal + SM
background** to the observed data. `overlay_on_data.py` (built on the shared `mplhep_style.py` house
module) draws the publication figure for the form 5.0 selected.

**Differential distribution (archetypes A / D, where the bundled REF carries the background in `y02`):**
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.overlay_on_data \
  --signal <rundir>/outputs/<sig>.yoda --ref <…>/envs/rivet/share/Rivet/<RIVET_ID>.yoda.gz \
  --routine <RIVET_ID> --table <dNN-x01> --label "<model>" --xlabel "<obs> [GeV]" \
  --experiment <ATLAS|CMS> --com 13 --lumi <fb⁻¹> \
  --stack <rundir>/outputs/bkg_components.json \   # optional per-process stack (hepdata_fetch.py --tables)
  --sig-scale <k> \                                # NLO k-factor if the YODA is LO + the label claims NLO
  --out <rundir>/plots/<RIVET_ID>/named/<RIVET_ID>__<dNN-x01>__overlay-sigbkg-vs-data.png
```
Draws the published background (filled, with its uncertainty — stacked per-process if `--stack`), the
data (black points), and signal+background (line), plus a ratio-to-background panel — the experiment's
own view. `--experiment` applies the **mplhep ATLAS/CMS house style** (Helvetica / TeX-Gyre-Heros, the
bold-italic experiment label, the "√s, L" header, four-side inward ticks). Writes PDF (vector,
Type-42 fonts) + PNG.

**Counting / per-SR-yield (archetypes B / C — no differential distribution exists):** the publishable
figure is the **per-SR-yield overlay** (data points + background band + signal+background across the
SRs) via `overlay_on_data.py` (per-SR mode) / `plot_simpleanalysis.py`, from `outputs/sr_yields.json`.

**For a Rivet routine** you may also generate the raw per-observable `rivet-mkhtml` panels first
(`rivet-mkhtml <rundir>/build/analysis.yoda:'Title=<model>' -o <rundir>/plots`); note that draws the
model against the **data only** (no SM background — 5.1's `overlay_on_data.py` adds it). For the
**SimpleAnalysis** path the SR ntuple holds yields, not differential distributions, so only the per-SR
view is available.

Then standardize names (`<routine>__<origID>__<label>`, traceable to the HEPData table) with
`name_plots.py --plots-dir … --routine … --labels <rundir>/inputs/plot_labels.json`; the `--labels`
map is the [judgment] physics descriptor per id (see `docs/workflow/checklists/plot-naming.md`). Output lands under
`<rundir>/plots/<RIVET_ID>/named/` + an `INDEX.md` legend.

## 5.2 YODA persistence — interchange / hand-off ([agent])
Persist the per-SR yields (+ histos) as a Rivet-native `.yoda` so the yields are **re-plottable and
hand-off-able without re-running** the pipeline (Rivet's native interchange format):
```bash
$CONDA run -n rivet python scripts/run.py ravel.physics.write_yoda \
  --srs <rundir>/outputs/sr_yields.json --label <model> \
  [--histos <rundir>/outputs/<sig>.yoda(.gz)] \   # clone Histo1D cutflow/m_eff distributions through
  --out <rundir>/outputs/<RIVET_ID>__yields.yoda  # .gz extension => gzip
```
Serialises the per-SR `{name,n,b,db,s}` rows to a YODA2 file (signal `Estimate0D`, observed `Counter`,
background `Estimate0D` ±db); with `--histos` it also clones every `Histo1D`-family object (the `CF-*`
cutflows / distributions) through, so one file carries both the final scalar yields and the underlying
histograms. The write is **round-trip self-checked** (read back, every signal yield asserted equal —
exit nonzero on mismatch). This is the persistence layer of the single source of truth: a colleague (or
a later re-plot) reads the `.yoda` back with `yoda` / `rivet-mkhtml` and reconstructs the yields figure
**without** the generator stack — so it reproduces the 5.1 numbers exactly.

## 5.3 ROOT mirror — colleague-facing (optional) ([agent])
For colleagues whose norm is ROOT, mirror the two key figures in ROOT, from the **same source of
truth**, in ATLAS ROOT style. Two subcommands, run in the **`recast`** env (ROOT 6.40); each writes
`STEM.pdf` (vector) + `STEM.png` + `STEM.root` (a live canvas a colleague can open in a ROOT session):
```bash
# (a) per-SR-yield overlay mirror — same source of truth as 5.1 (sr_yields.json)
$CONDA run -n recast python scripts/run.py ravel.plotting.root_figures yields \
  --srs <rundir>/outputs/sr_yields.json \
  --analysis <RIVET_ID> --com 13 --lumi <fb⁻¹> \
  --out <rundir>/plots/named/<RIVET_ID>__sr-yields__root

# (b) mass-plane mirror — same HEPData contour tables as 5.4
$CONDA run -n recast python scripts/run.py ravel.plotting.root_figures massplane \
  --contour-obs <…>/<combined-observed>.yaml --contour-exp <…>/<combined-expected>.yaml \
  --point <m_parent,m_lsp> --mu95-obs <obs> --mu95-exp <exp> \
  --analysis <RIVET_ID> --com 13 --lumi <fb⁻¹> \
  --parent-label 'm(#tilde{#chi}_{1}^{#pm}/#tilde{#chi}_{2}^{0})' \
  --lsp-label 'm(#tilde{#chi}_{1}^{0})' \
  --out <rundir>/plots/named/<RIVET_ID>__massplane__root
```
A minimal ATLAS-like `TStyle` is set inline (no external `rootlogon`): four-side **inward** ticks, **no
stat box**, no title box, the `#bf{#it{ATLAS}}` + √s + lumi header; the mass-plane carries the explicit
**"95% CL exclusion (CLs), not a discovery"** line and the point is starred green/red by obs µ₉₅.
Colours are the Okabe-Ito hexes mirrored from `mplhep_style.py`, so a series is the same colour in both
renderers. This is a **mirror** of the mplhep figures for a ROOT-native audience — it reads the same
`sr_yields.json` / HEPData contour, so its numbers match 5.1/5.4 by construction; it is not a
re-derivation. Optional — produce it when colleagues will work the figure in ROOT.

## 5.4 Mass-plane SINGLE-POINT quick-look ([agent]) — a sanity view, NOT the headline deliverable
> The **headline SUSY deliverable is the step-8 SCAN contour** — the mapyde 95% CL contour from a grid
> scan, overlaid on ATLAS's published contour, + the (mapyde−ATLAS)/ATLAS difference map
> (`scan_contour.py`, `docs/workflow/steps/08-scan.md`). This §5.4 tool (`mass_plane_overlay.py`) is the **single-point
> quick-look**: it marks ONE tested point (a star, green/red by its µ₉₅) on the experiment's
> **already-published** contour — useful for "is my one point inside the published exclusion?", but it
> does NOT reproduce the contour and is NOT the RRR-style result. Use it for a per-point sanity check;
> use step 8 for the deliverable.

The single-point quick-look re-plots the *published contour numbers* (from HEPData, the table 5.0 named)
in the experiment's house style, with the model point + this run's µ₉₅ verdict grafted on (not a raster
overlay onto the published PNG). Produce it when you want to locate a single tested point:
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.mass_plane_overlay \
  --contour observed=<rundir>/outputs/hepdata/tables/<…>/<combined-observed>.yaml \
  --contour expected=<rundir>/outputs/hepdata/tables/<…>/<combined-expected>.yaml \
  [--contour observed_aux=<per-channel-obs>.yaml ...] \      # optional thin per-channel lines
  --point <m_parent,m_lsp> --mu95-obs <obs> --mu95-exp <exp> \
  --analysis <RIVET_ID> --experiment <ATLAS|CMS> --com 13 --lumi <fb⁻¹> \
  --parent-label '<TeX, e.g. m(#tilde{#chi}_{1}^{#pm}/#tilde{#chi}_{2}^{0})>' \
  --lsp-label '<TeX, e.g. m(#tilde{#chi}_{1}^{0})>' --model-label '<model>' \
  [--plane dm] \                                             # compressed plane: m(sparticle) vs Δm, no diagonal
  [--exp-band-lo <pyhf exp -1σ µ95> --exp-band-hi <pyhf exp +1σ µ95>] \   # band note (see below)
  [--xlim lo,hi --ylim lo,hi] \
  --out <rundir>/plots/named/<RIVET_ID>__massplane__<point>
```
Behaviour: the published **observed** contour is drawn solid, the **expected** dashed (vertex order is
the boundary polyline — never sorted). For a **compressed** model pass `--plane dm` to draw the
m(sparticle)-vs-Δm plane (no m_LSP=m_parent diagonal — a y=x line is meaningless when y is a mass
splitting); `--plane auto` (default) detects a "Δm" axis header. The tested point is a **star, GREEN if
obs µ₉₅ < 1 (excluded by this reproduction) else RED (allowed)**; an annotation box states µ₉₅
obs/exp, the verdict, and that this is a **95% CL exclusion (CLs), not a 5σ discovery**. The
kinematically-forbidden region is shaded. Writes both `.pdf` (vector, Type-42 fonts) and `.png`. The
±1σ expected **band** is often NOT shipped in HEPData; if so it is omitted from the curve and noted
honestly from the pyhf expected band via `--exp-band-lo/--exp-band-hi` (do **not** fabricate a
mass-plane band). Get the contour-table assignment + µ₉₅ values from steps 6–7 (HEPData fetch + pyhf).

## 5.5 Read + verify ([judgment])
The layout-hygiene half of this check is now MACHINE-GATED (CR-016): the house renderers run
`mplhep_style.lint_figure` at save time and exit 4 on legend/annotation-vs-data occlusion,
box overlaps, or tick-label collisions — a figure that saved cleanly already passed those. Your
judgment here is the PHYSICS half (right series, right reference, right axes, honest labels).
Check **every** rendered figure against **`docs/workflow/checklists/plot-criteria.md`** (structure: experiment label,
axis titles with units, no chartjunk / no axis-tick-label overlap, legend identifying every series,
uncertainty band, ratio panel; fonts embedded) and **`docs/workflow/checklists/plot-guidelines.md`** (construction:
the LOG-vs-LINEAR decision — the reproduced axis scales match the published figure's as recorded in
the contract's `axes`; the ≥~1.5-decade log heuristic only when no published reference exists; legend
clear of the data/contour; four-side inward ticks; colour-blind- and print-safe palette) — and
confirm each figure **resembles the published figure's FORM**:
- the mplhep overlay (5.1) is the same view the experiment publishes — data + background band +
  signal+background + ratio panel;
- the YODA persistence (5.2) re-plots to the same yields as 5.1 (it is the same numbers, just
  persisted);
- the ROOT mirror (5.3), where produced, matches the mplhep figure (same source, same numbers) in
  ATLAS ROOT style;
- the mass plane (5.4) re-plots the published contour numbers correctly, with the point coloured by
  this run's µ₉₅ verdict.

Compare each contract figure against the **EXTRACTED published image** (the `extracted_image.path`
recorded in `inputs/figure_target.json`; `fetch_figures.py --figure <id>` extracted it in step 2) —
same form, same axes, same scale. When the route was `none` (no pixels extracted), verify against
the figure id + caption snippet instead — the precise textual reference is the valid degraded state
(`docs/workflow/checklists/figure-contract.md`).

Then read the physics: where the model's signal+background rises above the data in a discriminating
region, the model would have produced a visible excess → it is constrained/excluded there; where it
tracks the background, the analysis is insensitive. Note the most sensitive observable/region — it
drives step 7.

## 5.6 Emit `figures.json` — the machine-readable figure index ([agent])
Promote the `named/INDEX.md` legend into a versioned **`figures.json`** — the RESULT-PACK's figure layer.
The INDEX.md is unreliable across runs (it can be absent, a stub, or fully populated), so a generated
`figures.json` is the parseable index a reader trusts: one entry per deliverable figure carrying
`{filename, what_it_shows, source_ref / hepdata_table, criteria_pass}`. It is written by the same tool
that emits `result.json` in step 7 (`result_pack.py`), which reads the plots `INDEX.md` when present and
otherwise discovers the figures from their standardized `<routine>__<origID>__<label>` filenames:
```bash
# figures.json is written alongside result.json by the step-7 pack:
$CONDA run -n rivet python scripts/run.py ravel.workflow.result_pack --rundir <rundir> \
  --stat-mode <…> --detector-mode <…>     # → <rundir>/figures.json (schema_version=1)
```
`criteria_pass` (per-figure, NEW vs the INDEX) records the `docs/workflow/checklists/plot-criteria.md` verdict for each
figure — set it from the 5.5 read so a downstream reader sees, per figure, whether it passed the hygiene
gate (left `null` = unrecorded). Keep the INDEX.md as the human legend; `figures.json` is its
machine-checkable mirror.

**THE CAPTION RULE (`docs/workflow/checklists/check-ins.md`):** every figure displayed to the physicist — at any
check-in, at any point in the run — carries a physics-judgment caption optimized for clarity: name
the visual elements (which curve/band/point is which), the axes, what to look at, and what it means.
`what_it_shows` is where that caption lives — write it to that standard, not as a filename echo.

**Fulfil the figure contract**: attach the rendered counterpart of the declared published figure so
the contract is not left declared-but-unfulfilled (`result_pack.py` WARNs on that):
```bash
$CONDA run -n rivet python scripts/run.py ravel.plotting.figure_target attach-generated \
  --rundir <rundir> --figure-id "Figure <N>" --path <rundir>/plots/<the counterpart>.png \
  --step 05-visualize
```
(For a scan run the counterpart is the step-8 contour — attach there with `--step 08-scan`.)

**Gap to the official figure:** these are faithful re-plots of the *same numbers* the experiment
published (the REF is digitised from HEPData), not the exact published figure — they lack the full
background decomposition, the experiment's exact styling, and systematic-band detail. The
SimpleAnalysis path has no differential distributions at all (yields only), so its statistical power
comes from the likelihood in step 7, not from a distribution overlay. A figure ships into `RESULT.md`
or the paper only after it passes `docs/workflow/checklists/plot-criteria.md`.

**Next:** `docs/workflow/steps/06-acquire-data.md`
