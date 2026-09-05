# Interrogation — visualization (Session 2/S2, 2026-06-09)

_Defects → fixes → eyeball-verified figures → gate. The figures are THE physicist-facing
deliverable ("grafting the hypothetical particle's histogram onto the published one"); every
regenerated/new figure was Read as an image and checked against
`docs/workflow/checklists/plot-criteria.md`. Gate state at stage close: `run_benchmark.py --full`
**exit 0, 4/4 green** (A×ε 2.4/6.4/13.2/3.9%, s95 1.01/—/1.00/1.01 — all numerics unchanged, as
expected for a figures-only stage; the only gate-relevant change is the new merged-run
`require_files` entry, which passes provenance)._

## Defects found (Wave-1 diagnosis + findings encountered while fixing)

| ID | Sev | Where | Finding | Status |
|---|---|---|---|---|
| VIS-D1 | major | `overlay_on_data.py` | **No tick-density control**: default locators only; the known axis-tick-label-overlap defect class (CLAUDE.md hygiene item) had no guard on either axis | **FIXED** (shared `tick_hygiene`: x `MaxNLocator` driven from the ratio panel, log-y `LogLocator` with decade-capped `numticks`, labelled-minor suppression, ratio `MaxNLocator(prune="upper")`) |
| VIS-D2 | major | `overlay_on_data.py:79` | **Hardcoded `loc="upper right"` legend** — no collision awareness; first regeneration pass proved the failure live (legend ran into the "√s, L" header) | **FIXED** (`smart_legend`: deterministic occupancy scoring of upper-right/left/center, measured bbox-vs-text collision check, font-shrink before re-anchor, post-placement occlusion warning to stderr) |
| VIS-D3 | major | both plot helpers | **No Type-42 font embedding** (`pdf.fonttype`/`ps.fonttype` unset → Type-3 in PDFs; journals reject) | **FIXED** in `mplhep_style.apply_style`; verified: regenerated PDFs contain `FontFile2`, no `Type3` |
| VIS-D4 | major | runs on disk | **Registered gluino overlay predated the house style entirely** (default-matplotlib fonts, a `title()`, no ATLAS label, no inward ticks); the registered squark figure was the rivet-mkhtml signal-vs-data plot, i.e. **no SM background drawn at all** — fails plot-criteria's core content requirement | **FIXED** — both regenerated in place (same filenames) as proper s+b-over-data overlays |
| VIS-D5 | major | normalization vs label | **LO-normalized YODA vs higher-order claims**: the signal YODA holds σ_LO·L (verified: 2jl REF-integration s=232.4 LO = the value `pyhf_exclude.py` scales by k); drawing it under an "NLO+NNLL" legend label would overstate/understate the curve by 1/k (gluino: 1.9×) | **FIXED**: new `--sig-scale` flag; figures drawn with the registry k (0.862 / 1.915 / 0.855 — `cases.json` is the only k authority) and the label states the normalization |
| VIS-D6 | major | merged run | **No figures at all** in `…_squark-merged/` (BENCHMARK.md caveat: "merged case has no figure"; STATUS.md carry-over) | **FIXED**: rivet-mkhtml (21 plots) + `name_plots.py` (named/ + INDEX.md) + the 2jl overlay; added to the case's `provenance.require_files` (deliverables ratchet) |
| VIS-D7 | minor | `overlay_on_data.py --stack` | **No stack-sum validation** — a wrong per-process JSON would silently draw a background that disagrees with the published total | **FIXED**: per-bin >2% deviation → stderr warning (tested with a synthetic 5%-deficit stack: fires on exactly the 3 doctored bins) |
| VIS-D8 | minor | `--stack` colours | Default colour cycle: not colourblind-safe, no process→colour consistency across figures | **FIXED**: Okabe-Ito palette + stable `PROCESS_COLORS` map + deterministic fallback cycle (verified visually on the synthetic stack) |
| VIS-D9 | major | `name_plots.py` | **Silent no-op**: empty/missing `--plots-dir` produced an empty `named/` + INDEX and exit 0 — a run could ship with no named plots and nothing would notice | **FIXED**: missing dir / zero PNGs / missing `--labels` → loud stderr + exit 1 (all three paths tested) |
| VIS-D10 | major | `plot_simpleanalysis.py` | Crude style: no mplhep, fontsize-7 labels at 75° rotation on the SR-yield bars (unreadable), `139 fb⁻¹` **hardcoded** in the ylabel while lumi is an argv (silently wrong for any other lumi), non-CB-safe colours, 130 dpi | **FIXED**: house style, horizontal `barh` SR labels at full size, lumi computed from argv, Okabe-Ito, 200 dpi, framed legend; smoke-tested on the slepton 50k run (output to /tmp, run dir untouched) |
| VIS-D11 | minor | style duplication | ATLAS-style setup duplicated across `overlay_on_data.py`, `plot_simpleanalysis.py`, run-local scripts — divergence guaranteed | **FIXED** for the shared helpers via new `mplhep_style.py` (style+fonts+palette+ticks+legend in one module, mplhep-absent fallback); run-local scripts deliberately not touched (run records) |
| VIS-D12 | minor | ratio panel | Ratio x-axis only aligned by `sharex` luck; no shared locator guarantee; exponent/offset text could land on the axis title | **FIXED**: shared-axis locator set once on the bottom panel (matplotlib shares the Ticker), x offset disabled (GeV axes must not grow a `×10³`), y offset text shrunk + moved clear |
| VIS-D13 | minor | mplhep 1.2 API | `hep.atlas.label(label=…)` is deprecated (FutureWarning on every call) | **FIXED**: `text=…` with a `TypeError` fallback for older mplhep |
| VIS-D14 | minor | frameless legends | mplhep styles set `legend.frameon=False`; a marker glyph entry ("Data") floats ambiguously over the canvas — in the gluino figure it read as a stray data point at (~2350, 17) | **FIXED**: `smart_legend` forces `frameon=True` + `framealpha=0.85` (soft white pad, per the approved hygiene list) |
| VIS-D15 | minor | `named/INDEX.md` legends | Overlay figures written by `overlay_on_data.py --out` were never indexed (gluino INDEX had no row for its registered overlay); the squark d04 row described content the file no longer shows | **FIXED**: rows updated/appended in all three ins1458270 runs' INDEX.md |

## Figures regenerated / created (eyeball verdicts)

| Figure (path) | Action | Verdict vs plot-criteria.md |
|---|---|---|
| `trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-pair/plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d04-x01-y01__meff-incl_SR-2jl.png` (+.pdf) | regenerated in place: was signal-vs-data (no bkg); now data + published-bkg band + s+b (k=0.862, "NLO+NNLL" stated) + ratio panel, ATLAS house style | **PASS** — legend upper-right clear of header/data, ticks 500-GeV spacing no overlap, ratio aligned, Type-42 PDF; s+b rises visibly above data ⇒ exclusion legible at a glance |
| `trial-runs/2026-06-08_ATLAS_2016_I1458270_gluino-pair/plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d08-x01__overlay-sigbkg-vs-data_SR-5j.png` (+.pdf) | regenerated in place: was default-matplotlib (no ATLAS label, title, Type-3 fonts); now house style, signal at NLO+NNLL (k=1.915) | **PASS** — framed legend disambiguates the Data glyph; ratio panel honestly clips the s/b≈30 tail (unity line + data + band still legible) |
| `trial-runs/2026-06-08_ATLAS_2018_I1676551_C1N2-WZ/plots/named/ATLAS_2018_I1676551__SRyields__overlay-sigbkg-vs-data.png` (+.pdf) | re-run **as-is** from the run-local `config/overlay_sr_yields.py` (reproducibility confirmed) | **PASS with recorded divergence** — content correct (per-SR data/bkg/band/s+b + ratio); style predates the upgrade: frameless legend, and its `ax.text` annotation collides with the bold-italic ATLAS label. Run-local record — not edited (see Deferred) |
| `trial-runs/2026-06-08_ATLAS_2016_I1458270_squark-merged/plots/ATLAS_2016_I1458270/named/ATLAS_2016_I1458270__d04-x01__overlay-sigbkg-vs-data_SR-2jl.png` (+.pdf) | **NEW** (closes the BENCHMARK.md "merged case has no figure" caveat) + 21 rivet-mkhtml plots + named/ + INDEX.md | **PASS** — the long label exercised the font-shrink path (legend stayed top-right, zero occlusion warnings); registered in `cases.json` require_files |

Iteration trail (the checklist was enforced, not assumed): pass 1 squark — legend/header collision
caught by eyeball → measured-bbox collision logic added; pass 2 merged — wide-label legend re-anchored
down INTO the data, caught by the new stderr occupancy warning + eyeball → label wrapping +
font-shrink-before-re-anchor; pass 3 — Data legend glyph ambiguity (frameless) → framed legend; final
pass — all four figures clean, zero occlusion warnings.

## Label note (small deviation from the approved list, flagged)

The approved merged-figure label was `squark MLM-merged (800,100)`; the figure carries
`squark MLM-merged (800,100), NLO+NNLL` with `--sig-scale 0.855`, so the merged and unmerged squark
overlays draw the *same* normalization claim and are directly comparable (an unscaled merged curve
would have differed from its sibling by 1/0.855 ≈ 17% for no physics reason). VIS-D5 is why the
normalization must be stated on the figure.

## Deferred (with why)

- **R6 visual-fidelity gate scoring** (machine-compare the overlay against the published figure):
  Phase-2 hook in `BENCHMARK.md`; the provenance gate still checks only path+size. New
  KNOWN-LIMITATIONS entry added ("R6 visual fidelity is checklist-verified, not machine-scored").
- **C1N2 run-local overlay style divergence**: `config/overlay_sr_yields.py` is part of the certified
  run record (do-not-modify); its figure diverges from the upgraded house style (frameless legend,
  ATLAS-label/annotation collision, `label="Internal"`). Recorded here + in KNOWN-LIMITATIONS; the
  clean path is a future re-certified run using the shared helpers.
- **Legacy squark-pair `…__d04-x01__overlay-sigbkg-vs-data_SR-2jl.png`**: the run's original
  (pre-upgrade, LO-normalized) overlay duplicate left untouched as a historical run artifact; the
  registered deliverable is the regenerated `d04-x01-y01__meff-incl_SR-2jl` figure.
- **Ratio-panel clipping heuristic** (cap at 12 when s/b is huge, gluino): kept — a log-ratio or
  split-scale panel is a design change beyond the approved hygiene list; the panel's job (data-vs-bkg
  agreement + visible signal rise) survives the clip.
- **Garwood/Poisson asymmetric data errors** (currently √n): cosmetic at these counts; a content
  change to the data series deserves its own reviewed pass.

## Files changed (this stage)

- `src/ravel/plotting/mplhep_style.py` — **NEW** shared house-style module (style+Type-42,
  Okabe-Ito + process map, `tick_hygiene`, `smart_legend`, mplhep-absent fallback).
- `src/ravel/plotting/overlay_on_data.py` — hygiene block (ticks/legend/offset/ratio-sync),
  `--sig-scale`, stack validation + CB-safe colours, label wrapping, mplhep-1.2 `text=` fix.
- `src/ravel/plotting/name_plots.py` — input validation (loud stderr + exit 1).
- `src/ravel/plotting/plot_simpleanalysis.py` — house style, readable `barh` SR labels,
  argv-derived lumi label, Okabe-Ito, 200 dpi.
- `benchmarks/cases.json` — squark-merged `provenance.require_files` += the new 2jl overlay
  (only edit to the registry).
- 3× `named/INDEX.md` (squark-pair row update; gluino + merged overlay rows appended).
- `docs/reference/limitations.md` — R6 entry (above).
- Figures: 3 regenerated in place + 1 new (+ 21 merged-run rivet-mkhtml plots + named copies).

## Final gate state

`python3 benchmarks/run_benchmark.py --full` → **exit 0**, GATE OK, 4/4:
squark Ideal/Ideal (2.4%, s95 1.01/1.03) · C1N2 Good (6.4%) · gluino Acceptable/Ideal (13.2%,
1.00/1.02, WARN=known merging attribution) · merged Ideal/Ideal (3.9%, 1.01/1.03). µ₉₅ stability,
verdicts, certs, provenance (incl. the new merged-figure requirement) all hold. `results.json`
refreshed by the run (commit together with `cases.json`).
