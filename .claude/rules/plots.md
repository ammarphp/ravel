# Rule — publication-grade plots (the fidelity a scientist trusts)

Read when producing any figure. A figure ships only if it passes
`workflow/checklists/plot-criteria.md`. Use `trial-runs/_infrastructure/overlay_on_data.py` (built on
**mplhep**) for the signal-over-data overlay; `--experiment ATLAS|CMS --com 13 --lumi <fb⁻¹>` applies
the house style (Helvetica / TeX-Gyre-Heros, the bold-italic experiment label, the √s+L header,
four-side inward ticks), `--stack <bkg.json>` draws the per-process stack.

## The hygiene checklist (every figure)
- **No axis-tick-label overlap** (the known defect to fix): control tick *density* (`MaxNLocator` /
  explicit locators), use a shared offset/exponent placed clearly (not colliding with the axis title),
  rotate or thin x-labels if they crowd, and keep the ratio-panel x-axis aligned with the main panel.
- **Axis titles carry units** (e.g. `m_eff [GeV]`, `Events / 100 GeV`); log-y where the data span it.
- **Legend identifies every series** (data, each background process, signal+background) and does not
  collide with the data or the stack; place it where it occludes nothing. MACHINE-ENFORCED
  (CR-016): the house renderers run `mplhep_style.lint_figure` at save and exit 4 on
  legend/annotation occlusion, box overlap, or tick collisions; use `smart_legend`/`smart_annotate`
  for placement (below-axes caption fallback when every corner is occupied), `--no-lint` only with
  a recorded justification.
- **Uncertainty band** on the background (hatched), **data as black points with error bars**,
  **signal+background as a clear line**; a **ratio (data/bkg) panel** below with a unity line.
- **Fonts embedded** in the PDF (Type-42/TrueType, not Type-3); export both PDF (vector, for the paper)
  and PNG (for quick view). Colourblind-safe palette; consistent process colours across figures.
- **Per-process stack fidelity**: the stacked backgrounds sum to the published total; the binning and
  range match the published figure (this is R6 — check against the actual published figure, not just
  the digitised REF).

## Cutflow-only / counting analyses
No differential distribution exists — the publishable figure is the **per-SR yield overlay** (data
points + background band + signal+background across SRs), not a distribution overlay. See
`workflow/reference/example-rivet-ewk-path.md`.

The goal of this stage is the figure a referee trusts at a glance: correct numbers, no chartjunk, and
the model's excess (or its absence) immediately visible over the published data.
