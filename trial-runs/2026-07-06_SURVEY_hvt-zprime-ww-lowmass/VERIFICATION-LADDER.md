# VERIFICATION-LADDER — 2026-07-06_SURVEY_hvt-zprime-ww-lowmass

`task_mode=summary_plot` (no event generation; `stat_mode=none-survey`). Per
`workflow/checklists/summary-plot.md` §5: **"Ladder rungs: R6 only (+ the identity checks of
§3)"** — this run harvests/digitizes/overlays PUBLISHED limits, it derives nothing. R1-R5
(generation truth-level, reconstructed-object spectra, selection cutflow, per-SR A×eps,
statistics-from-published-inputs) are **not-applicable** by construction: there is no MadGraph/
Pythia/Rivet/SimpleAnalysis/pyhf stage in this track. R0 (toolchain sanity) has no
benchmark-baseline equivalent for this track; the track's own mechanical gate
(`summary_audit.py` R-SA1..8 + the CR-016 plot-lint gate) is recorded below in its place.

## R0 — track mechanical gate (this track's toolchain-sanity equivalent)
`checked-pass`. `python3 trial-runs/_infrastructure/summary_audit.py --rundir <this run>` →
**PASS** (all 8 rules R-SA1..8; see `outputs/summary_audit.json`). Render
(`summary_overlay.py --experiment ATLAS --com 13`) → **plot-lint PASS** (exit 0; the CR-016
`mplhep_style.enforce_lint` gate — no legend/annotation occlusion, no tick collisions), producing
`plots/hvt_zprime_ww_summary.{png,pdf}`.

## R1-R5 — generation / selection / statistics
`not-applicable`. No signal MC, no detector simulation, no cutflow, no likelihood fit exists or
is claimed in this run; the deliverable is a literature overlay of already-published limits on a
common basis (§3 identity checks below stand in for R1-R5's role of cross-checking the numbers).

## R6 — figure: form + numbers vs. the extracted published figure (per curve)

| Candidate | disposition | R6 status | compared against | note |
|---|---|---|---|---|
| `ATLAS_2004.14636` (l-nu-qq semileptonic, 139 fb⁻¹) | plotted, primary | `checked-pass` | `outputs/published/atlas_2004.14636/figures/fig_14a.pdf` (Fig. 14(a)) | 20-point digitization (pre-existing, this session's fix only relabels + adds provenance); identity check = HVT-theory-curve crossing vs the paper's quoted excluded range (visual). HEPData Table 12 download blocked (Cloudflare) on this host — `provenance=digitized`, not machine-read. |
| `ATLAS_1710.07235` (l-nu-qq semileptonic, 36.1 fb⁻¹) | **superseded** by `ATLAS_2004.14636`, drawn `crosscheck` (faint, not co-equal — R-SA5) | `checked-pass` | `outputs/published/atlas_1710.07235/figures/HVTWW_LPHP_ggF.pdf` | 27-point digitization (pre-existing; this session fixes the F2 mislabel — was "qqqq boosted", is l-nu-qq semileptonic per its own `survey.json` `final_state` — and the F3 demotion to `superseded`). Identity check: the 36.1 fb⁻¹ curve sits above the 139 fb⁻¹ `ATLAS_2004.14636` curve at high mass (less data ⇒ weaker/higher limit) — holds. `provenance=digitized`, HEPData table download blocked on this host. |
| `ATLAS_1710.01123` (fully-leptonic eνμν, 36.1 fb⁻¹) | **plotted, primary** (F1 fix — was mechanically dropped; see below) | `checked-pass` | `outputs/published/atlas_1710.01123/figures/Limit_HVT.pdf` | **New this session.** No HEPData aux data file exists for this paper (`1710.01123.tar.gz` is the arXiv LaTeX source — `figures/*.pdf` only, no `.yaml`/`.dat`/`.csv`; this is also *why* the paper's HEPData table names carry no WW/HVT/limit keyword, the original F1 mechanical-drop cause). Digitized from the rasterized PDF (Ghostscript, 400 dpi): axis-frame + major-tick pixel positions fit a linear-x(mass)/log-y(σ) map, then observed-curve pixels read column-by-column with the legend/label text box and axis-tick bands masked out. 24 observed points (200-5000 GeV), plus expected (6 points) and the HVT-theory reference line (10 points) where the dashed/red line was unambiguously resolvable — left `null` (not interpolated or fabricated) elsewhere. Two independent checks: (a) **numeric cross-check** — the extracted HVT g_V=1 theory value at m=1000 GeV is 0.232 pb vs `ATLAS_2004.14636`'s independently-digitized theory value of 0.23 pb at the same mass (same model; <1% agreement, two unrelated extractions of the same physics line); (b) **visual QA** — all 24 digitized observed points overlaid back onto the source raster as markers landed on the plotted curve (see the digitization session's overlay check). **This is an approximate, summary-reach digitization (explicitly not a precision extraction) — sufficient to establish the ~200 GeV floor, not to be read to more than ~1 significant figure.** |
| `CMS_1612.09159` | excluded (`out-of-range`) | `not-applicable` (not plotted) | — | out-of-window context only, per `survey.json`: mass axis starts ~600-700 GeV in the target Fig. 6, verified by direct rasterization; entirely above the run's [150,1000] GeV window. |
| `CMS_2601.12583` | excluded (`out-of-range`) | `not-applicable` (not plotted) | — | out-of-window context only, per `survey.json`: mass axis starts at 1000 GeV in every panel checked (Fig. 4(b), Fig. 10(a)), verified by direct rasterization; entirely above the window. |

## §3 identity checks (basis_manifest.json `curves[].identity_check`, summarized)
- `ATLAS_2004.14636`: theory-curve crossing vs the paper's quoted excluded mass range (visual).
- `ATLAS_1710.07235`: lower-luminosity curve sits above the higher-luminosity successor at high
  mass (unit/ordering sanity) — holds.
- `ATLAS_1710.01123`: cross-paper theory-line agreement (<1% at m=1000 GeV) + visual marker-overlay
  QA (both described in the R6 table above).

## Bracketing statement
No `checked-fail` at any rung — R6 is clean for every drawn curve, and R-SA1..8 (the track's own
mechanical gate) all PASS. The one still-open limitation is the digitization *precision* of
`ATLAS_1710.01123` (approximate/summary-reach, not machine-read/precision) — recorded here and in
`basis_manifest.json`, not silently absorbed into a `checked-pass`.
