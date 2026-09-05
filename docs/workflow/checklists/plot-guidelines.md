# Checklist — plot construction (CERN ROOT + ATLAS/CMS style + dataviz)

How a figure is *built* so a physicist reads the hypothesis off it at a glance: the right axis scale,
a legend that hides nothing, ticks and labels in the house style, and colours that survive print and
colour-blindness. `plot-criteria.md` is the per-figure structural sign-off (does the figure carry
data + band + signal + ratio); THIS file is the construction guidance behind those choices. Both
plotters (`overlay_on_data.py`, `mass_plane_overlay.py`) and the ROOT mirror (`root_figures.py`) draw
from the shared house module (`mplhep_style.py`), so the rules below are centralised there.

## The LOG-vs-LINEAR decision (the decisive rule)
**The published target figure's axis scales are FACTS read at declaration time, not defaults.** The
rule has two tiers, and the first one is binding:

- **(a) Published-figure match (binding whenever a figure contract target exists).** The produced
  counterpart MUST use exactly the axis scales of the PUBLISHED figure it reproduces — log where the
  published axis is log, **linear where the published axis is linear**. Read the scales off the
  extracted published figure at declaration and record them in the contract
  (`figure_target.py declare/attach-image --axes-x linear|log --axes-y linear|log` →
  `inputs/figure_target.json`); the renderers consume the record (`scan_contour.py` /
  `mass_plane_overlay.py --figure-target <rundir>`, with `--logx/--linx/--logy/--liny` as explicit
  per-axis overrides). Matching the published SHAPE is the litmus test that tells a physicist the
  reproduction is functional.
- **(b) Data-span heuristic (ONLY when there is NO published reference).** With no published figure
  to match, use log when the plotted quantity spans roughly **≥1.5 orders of magnitude** (decades).
  A log scale is "linear in multiplication" (a unit step multiplies by a fixed factor) and is the
  right choice for data spanning different orders of magnitude; on a linear axis the large values
  are over-emphasised and the small ones obscured. This heuristic must NEVER override a recorded
  published scale — it is the fallback, not a trigger that fires alongside (a).

**Both failure modes have actually happened — neither is hypothetical:**
- *published log, produced linear*: the compressed (small-Δm) region collapses to a sliver — a
  definite shape mismatch against the published figure;
- *published linear, produced log* (the overcorrection): after fixing the first mode, the ≥1.5-decade
  heuristic was applied as if it were a default and forced log axes onto figures whose published
  counterpart is linear — equally a shape mismatch. If the published axis is linear, the produced
  axis is linear, regardless of how many decades the data span.

Worked example: a compressed-spectrum **Δm** axis (mass splitting) typically spans ~0.4–40 GeV ≈ **2
decades** and the published ATLAS compressed-plane figure IS log → record `y: log` at declaration and
render log. A pure **mass-mass** plane (m(parent) vs m(LSP)) spans <1 decade and the published figure
is linear → record and keep it LINEAR. `mass_plane_overlay.py` encodes these per-plane defaults (log
Δm on the `--plane dm` compressed plane, linear on the mass-mass plane) as the no-contract fallback;
when the contract records the axes, `--figure-target` makes the recorded scales win.

### Log-axis hygiene (encode as guards)
- A log axis **cannot show zero or negative values** (log is undefined there). Floor the lower limit to
  the smallest positive data value, never 0. (`mass_plane_overlay.py` floors to the smallest published
  Δm.)
- The axis **title names the variable + units** (e.g. `Δm [GeV]`), **never** `log(Δm)`. If
  log-transformed *data* is ever plotted directly, always state the base.

## Legend placement (must hide nothing)
- Place the legend in **empty plot space** near the data it labels — never over the data, the
  stacked background, or (for a mass plane) an exclusion contour or the tested point. An exclusion
  contour can fill the frame; the empty space may be a mid-frame pocket (the open mouth of a
  "C"-shaped compressed contour), not a corner.
- Show **colour swatches**, not colour names; keep entries **≤8**. In ROOT use `TLegend` with explicit
  NDC corner coordinates (or `BuildLegend` as a starting point) and move it off the contours.
- The shared module places the legend deterministically (occupancy-scored candidate boxes, including
  mid-frame pockets, with the experiment-label and annotation-box corners reserved) and **warns** if
  the placed legend still occludes drawn data.

## Ticks, labels, units (ATLAS house style)
- **Tick marks on all four sides, pointing inward** (top + right as well as bottom + left). ROOT:
  `gStyle->SetPadTickX(1); gStyle->SetPadTickY(1)`; mplhep ATLAS/CMS style does this by default.
- **Axis labels always carry units in brackets** (e.g. `m(ℓ̃) [GeV]`, `Δm [GeV]`, `Events / bin`) and
  must not collide with the frame — use generous pad margins.
- **Control tick density** so labels never overlap (`MaxNLocator` on linear, `LogLocator` capped by the
  spanned decades on log); keep any offset/exponent text clear of the axis title and never let an
  `×10ⁿ` offset detach the numbers from a physical (GeV) axis.

## Colour (colour-blind-safe, print-safe)
- Default categorical palette: **Okabe-Ito** (Wong) 8-colour set —
  orange `#E69F00`, sky blue `#56B4E9`, bluish green `#009E73`, yellow `#F0E442`, blue `#0072B2`,
  vermilion `#D55E00`, reddish purple `#CC79A7`, black `#000000`. (Alternative: Paul Tol "bright".)
  These are centralised in `mplhep_style.py` (`OKABE_ITO`) and mirrored into the ROOT figures, so a
  series is the same colour in every renderer.
- **Never separate categories by red-vs-green alone** (indistinguishable under common CVD). Cap
  categorical colours at ~8 (3–5 ideal). Colour reads poorly on thin lines / small markers, so
  **thicken contour lines and enlarge markers** when colour-coded, and pair colour with line-style or
  marker (redundant coding) so the figure survives **black-and-white** reproduction. For continuous /
  sequential heat data use **viridis** (perceptually uniform, CVD-safe). Verify the final figure in a
  CVD simulator.

## ROOT-specific gotchas (for the `root_figures.py` mirror)
- **Log scale is a PAD attribute**, set per-pad: `gPad->SetLogx(1)` / `SetLogy(1)` / `SetLogz(1)`. It
  does NOT propagate to sub-pads — set it on each pad. (A `TGaxis` takes option `'G'` for log.)
- **TGraph on a log axis**: only the *points* are converted to log; the *lines connecting them stay
  linear*, so a sparse exclusion contour drawn with option `'L'` (polyline) looks kinked. Mitigate by
  interpolating to many points before drawing, or use option `'C'` (smooth curve). (Options: `A`=axes,
  `L`=polyline, `C`=smooth curve, `P`=markers; combine e.g. `AC`.)

## ATLAS numeric style (centralised once, not per-figure)
Set on `gStyle` then `canvas->UseCurrentStyle()` (ROOT) / rcParams in `mplhep_style.py` (matplotlib):
font 42 (Helvetica) on text/labels/titles; text/label/title size 0.05; marker style 20 (full circle),
size 1.2; hist line width 2; `SetEndErrorSize 0`; `SetOptStat 0` (no stat box); `SetOptTitle 0` (no
in-frame title); `SetOptFit 0`; `SetPadTickX 1`/`SetPadTickY 1`; margins top/right 0.05, bottom/left
0.16; white canvas/pad/frame. Increase line widths for print/grayscale legibility.

## Sources
- Wilke, *Fundamentals of Data Visualization* — coordinate systems / axes (log-vs-linear, log hygiene):
  <https://clauswilke.com/dataviz/coordinate-systems-axes.html>; colour pitfalls (CVD, red-green,
  redundant coding, viridis): <https://clauswilke.com/dataviz/color-pitfalls.html>.
- Okabe & Ito colour-blind-safe palette (via Wilke, above); Paul Tol / SRON palettes:
  <https://personal.sron.nl/~pault/>.
- ATLAS Style Guide v2.4 (ATL-GEN-PUB-2008-001):
  <https://pprc.qmul.ac.uk/~efe/ATLAS_StyleGuide_2_4.pdf>; canonical `AtlasStyle.C`:
  <https://github.com/dguest/HistFitter/blob/master/macros/AtlasStyle.C>.
- CERN ROOT manual — graphics / pads / log scale: <https://root.cern/manual/graphics/>; TGraph painter
  (log-axis line caveat, draw options): <https://root.cern/doc/master/classTGraphPainter.html>.
