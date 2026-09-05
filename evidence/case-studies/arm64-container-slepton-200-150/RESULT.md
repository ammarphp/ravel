# RESULT — slepton (200,150), 50,000 events (production)

## Status: COMPLETE — all six stages PASS
Identical faithful configuration to the 1k smoke test; only `nevents` differs (50000 vs 1000).

| Stage | Result | Wall time |
|---|---|---|
| madgraph (MG 2.9.3 + Pythia8) | PASS | 28449 s (~7.9 h) |
| delphes | PASS | 2517 s (~42 min) |
| analysis (Delphes2SA) | PASS | 42 s |
| simpleanalysis (EwkCompressed2018) | PASS | 19 s |
| sa2json | PASS | 20 s |
| pyhf (muscan) | PASS | 1057 s (~18 min) |
| **total** | | **~8.9 h** (amd64 emulation) |

## Config
MSSM `SleptonBino`, `isrslep` (slepton pair + 1 ISR jet), √s=13 TeV, m(slepton)=200, m(χ̃₁⁰)=150
(Δm=50), seed=0, k=1.18, lumi=139 fb⁻¹, selection `EwkCompressed2018`, likelihood
`Slepton_bkgonly.json`. Engine: podman (native arm64) + Apple-Virtualization VM, amd64 under emulation.

## Per-stage outputs
- **MadGraph σ (LO, 1-jet isrslep):** 0.02047 ± 0.00003 pb = **20.47 fb** (50000 events).
  Stable vs the 1k run (20.55 fb) → cross-section reproducibility confirmed.
- **SimpleAnalysis (EwkCompressed2018):** total baseline acceptance **2.42%**; the binned signal
  regions each receive ≤ 8×10⁻⁵ acceptance (≤4 events / 50k).
- **Signal injected into pyhf:** **7.0 expected events** total across 32 signal regions
  (max **0.81** events in any single region), after σ×k×lumi scaling.
- **Complex analysis (handled end-to-end):** this is a multi-region, multi-bin search — the combined
  likelihood spans 6 **control regions** (CRVV/CRtau/CRtop) + 32 **signal-region bins** (m_T2 a–h ×
  hi/lo-MET, ee+mm). The CR-constrained background + correlations are carried by the published
  likelihood; complexity required no simplification (see `workflow/checklists/complex-analysis.md`).
- **pyhf 95% CL on signal strength µ** (full ATLAS serialized likelihood: 38 channels, 191 params):
  - **observed µ₉₅ = 6.36** (expected 6.49, +1σ ≳8 / −1σ 4.66) — resolved with
    `pyhf_exclude.py likelihood` via a bracket-and-interpolate scan (14 fits, ~40 s each).
  - CLs falls from 0.75 at µ=1 to 0.05 only at µ ≈ 6.4 ⇒ **(200,150) is NOT excluded** (µ₉₅ ≫ 1).
  - Plot: `outputs/pyhf_exclusion/exclusion.png` (CLs-vs-µ, observed + expected ±1,2σ, crossing 0.05).
  - **Why the earlier plot stopped at µ=2:** mapyde's `muscan` uses a *fixed* grid 0.1–2.0. At its
    µ=2 ceiling CLs was still ≈0.52 — nowhere near the 0.05 crossing — so the scan ended long before
    the limit. The model is simply weakly constrained: the true limit (µ₉₅ ≈ 6.4) lies far past the
    grid. `pyhf_exclude.py` removes the grid (it brackets µ by doubling until CLs<0.05, then
    interpolates), so the reported limit is real even when large.

## Sensibility & sanity analysis
- **Cross-section:** 20.5 fb for the ISR-jet-tagged slepton sample is physically reasonable (inclusive
  NLO+NLL slepton σ at m=200 is ~60 fb; the 1-jet-tagged LO subset being ~20 fb is consistent), and
  it is stable between the 1k and 50k runs → the generation stage is sound.
- **Acceptance:** ~2.4% baseline is plausible for a compressed soft-lepton + ISR selection; the
  per-signal-region acceptance is small because the events spread across the ~100 finely-binned
  (flavour × M_ll × M_T2) regions.
- **Why not excluded — and why that is expected:** the total signal in the discriminating regions is
  only ~7 events (≤0.8 per region), far too few to constrain. Δm=50 GeV is at the **upper edge** of
  the compressed (soft-lepton) search's sensitivity: the leptons are near the top of the soft-pT
  acceptance and the signal migrates into the higher M_ll/M_T2 bins, diluting every region. The ATLAS
  slepton-bino exclusion for m(slepton)≈200 GeV reaches only **Δm≈15.7 GeV** (HEPData ins1767649,
  figure_2a; global max reach ~31 GeV), so (200, Δm=50) sits **well above (outside) the excluded
  region** → "not excluded" is correct but **uninformative**: a point this far outside cannot
  demonstrate a reproduced exclusion. A point at Δm≈10–15 GeV (m≈150–200) would be required for that.

## Did we reproduce the paper's pipeline?
**Faithful in FORM, but NOT yet a reproduction** (corrected 2026-06-15). Every stage ran in the paper's
actual containers (MadGraph 2.9.3, ATLAS Delphes card, ATLAS SimpleAnalysis `EwkCompressed2018`, the
bundled `pyhf` Slepton likelihood) via `mapyde`. The cause, however, is **not** what an earlier draft of this file claimed: (1) the paper's **low-pT
lepton-efficiency tuning** (§3.2, Listings 4/5) **was in fact applied** — a value-by-value check
(2026-06-15) shows the run's Delphes card matches the paper's tuned e/µ efficiencies byte-for-byte
(e 0.30→0.87, µ 0.65→0.93, incl. the §3.2 low-pT bump). The earlier "tuning not applied / acceptance
~2× off" claim was a **mis-attribution and is retracted**. (2) The real reason this trial is
uninformative is the **off-grid tested point**: (200, Δm=50) lies beyond the published acc×eff grid
(max Δm≈40) and outside the exclusion (boundary Δm≈15.7 at m≈200), so the analysis was never sensitive
there. (3) The native `mapyde` µ-scan was degenerate (µ pinned at 2.0) — superseded by the corrected
`pyhf_exclude.py` (band resolved, the A1 fix). So the chain runs end-to-end *with the paper's own
calibration*; this trial simply tests an off-grid point. **The on-grid reproduction is the
(150,140)/Δm=10 run** (`trial-runs/2026-06-15_slepton_150-140_efftuned/`), which should EXCLUDE its point.
(The detector-fidelity gate remains valid as a general check — and here it behaves correctly, reporting
"off published grid" rather than falsely blaming the efficiency.)

### Caveats limiting an exact numerical match to the published contour
1. mapyde's `isrslep` is a **1-jet** ISR-tagged sample; ATLAS used a **2-jet CKKW-L-merged** sample.
2. **LO** matrix element + a flat k-factor (1.18) vs ATLAS NLO+NLL.
3. **Delphes** fast-sim with the bundled ATLAS lepton-efficiency card vs ATLAS full simulation; the
   paper additionally hand-tuned the lowest-pT lepton efficiencies, which we did not re-tune.
4. ~~The muscan ceiling (µ=2)…~~ **Resolved:** the limit is now µ₉₅ = 6.36 from `pyhf_exclude.py`
   (no fixed grid). The earlier ">2" was only the muscan's grid edge, not the limit.
5. A precise contour comparison needs the **EwkCompressed2018** slepton exclusion (the 2020 analysis),
   not the different 2024 BDT-analysis ULs that also happen to be in the workspace.
