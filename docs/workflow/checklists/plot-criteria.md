# Checklist — publication-grade plots  ·  [agent] produce · [judgment] check

A scientist validates a hypothesis off the figure, so its structure must make the hypothesis legible.
(No-routine / sensitivity-only runs: where an item presumes published REF data or a
routine id, substitute the run's declared reference — a digitized anchor or the paper figure —
and label expected-only content as such; the structural items still apply unchanged.)
`overlay_on_data.py` produces this via `mplhep` (the selected experiment style). Every distribution plot must pass.

**MACHINE GATE:** the layout-hygiene items below are no longer eyeball-only — every house
renderer (`scan_contour.py`, `overlay_on_data.py`, `mass_plane_overlay.py`) runs
`mplhep_style.lint_figure` at save time and **fails loud (exit 4)** on: legend/boxed-annotation
occluding drawn data (fills exempt; bare in-plot feature labels exempt), box↔box overlap,
successive tick-label overlap, off-canvas boxes (fixed-canvas savers only). `--no-lint` downgrades
to WARN and must be justified in the run record. Placement is solved, not hand-tuned:
`smart_legend` + `smart_annotate` score corner occupancy and fall back to a below-axes caption when
every inside corner is occupied. Selftest: `plot_lint.py --selftest` (rivet env).
For the *construction* choices behind these checks — the LOG-vs-LINEAR axis-scale decision (match the
published figure's scale; use log when the quantity spans ≥~1.5 decades), legend placement off the
data/contour, ticks/labels, and the colour-blind-safe palette — see **`plot-guidelines.md`**.

## Structure (selected experiment style)
- [ ] **Experiment style applied** — the matching `mplhep.style` entry; **Helvetica** (TeX Gyre Heros) for all text.
- [ ] **Experiment label** — the supplied experiment label in bold italic + a "√s = N TeV, L fb⁻¹" sub-label (`hep.<exp>.label`).
- [ ] **Ticks inward on all four sides**, with minor ticks (mplhep default).
- [ ] **Axis labels with units** (e.g. `m_eff (incl.) [GeV]`, `Events / bin`); **axis scale matches the
      published figure** — log where the quantity spans ≥~1.5 decades (see `plot-guidelines.md`).
- [ ] **Legend** clear of the data, white/transparent, every drawn series labelled.

## Content (so the hypothesis is readable)
- [ ] **Data** as black points with Poisson error bars.
- [ ] **SM background** drawn — the per-process **stack** (W/t̄t/Z/Diboson/…) when the per-process tables
      are available (`hepdata_fetch.py --tables` + `--stack`), else the published **total**.
- [ ] **SM total-uncertainty band** (hatched) on the background — without it the agreement/excess must not be judged.
- [ ] **Signal + background** drawn on top (the new model) so "would it have shown up?" is read directly.
- [ ] **Ratio panel** (data / background) with the unity line and the signal+background curve overlaid.

## Output
- [ ] Vector **PDF** (for the paper) plus a PNG (for review); ≥200 dpi.
- [ ] Named per `plot-naming.md`; a fidelity check vs the published figure recorded (`fetch_figures.py` +
      a fidelity verdict in the run directory).
- [ ] **Figure contract fulfilled** — the figure that reproduces the declared published target is
      attached (`figure_target.py attach-generated`) and the side-by-side composed (`compose`);
      see `figure-contract.md`.

## What "good" looks like
The published data tracks the background within its uncertainty band; the model's signal+background
rises visibly above the data in the sensitive region (→ excluded) or sits within it (→ insensitive).
If the plot leaves that distinction unclear, the plot fails this checklist regardless of the numbers.


## Readable scientific labels and reference comparisons

New figures use readable axis, tick, series and title labels. Standard scientific
math stays math: `m_ll` becomes `$m_{\ell\ell}$`, `p_T` becomes
`$p_{\mathrm{T}}$`, and supplied TeX/subscripts and units are preserved.
Do not make raw identifiers look scientific by deleting operators or units.
Unknown names receive conservative token spacing, or an explicit display label;
opaque region/cell identifiers such as `sr_3_obs_0` require a supplied semantic
label explaining the actual observable or selection. Merely changing that ID
to “sr 3 obs 0” leaves its meaning unresolved and is refused.
opaque dataset/observable paths use a numbered display label with the full
original identity retained in the plot contract. An explicit label containing
machine underscores outside math is refused. The ordinary house lint checks
these visible labels alongside its existing geometry checks.

An agent-versus-official overlay accompanies the side-by-side for new reference
comparison targets. Use the ordinary figure-target route documented in
[the figure contract](figure-contract.md#source-bound-overlays-for-new-targets).
Prefer genuine source-compatible numerical coordinates. An image-backed overlay
needs recorded crop/axis/scale/unit calibration and source pins, and remains a
visual comparison; a raster is never a numerical reference. Unknown points and
incompatible model/width/production/energy/BR/response conventions stay explicit.
No-reference or incomparable-reference dispositions do not claim an overlay or
close a task that requested that comparison.
