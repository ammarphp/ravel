# RESULT — RRR Fig-3 reproduction of EwkCompressed2018 (slepton-bino), faithful 2-D mass plane

The canonical proof (`framework/PLAN-OF-RECORD.md`): the workflow reproducing the **entire**
EwkCompressed2018 analysis (ATLAS-SUSY-2018-16 / HEPData ins1767649) across a **2-D mass plane**,
**natively, no VM**. This is the 2-D deliverable — RRR Fig 3 in form. Generated-from / cross-checked
against `scan.json`. **95% CL exclusion (CLs), not a discovery.**

## Method — the faithful ATLAS grid, native, VM-free
- **Grid = ATLAS's own published lattice** (Fig 44ab σ-UL grid): 12 slepton masses 50–300 GeV × Δm≥2 GeV
  = **52 on-grid points** (Δm<2 dropped — no soft-lepton sensitivity, native gen degenerate). Scanning the
  *exact* ATLAS points → the difference map is point-for-point (no interpolation). Spec
  `_infrastructure/specs/slepton_bino_fig3_FULL.json`.
- **Every point fully native** (no podman/VM/emulation): MadGraph → Pythia8 → DelphesHepMC3 → native
  SimpleAnalysis(EwkCompressed2018) + native RestFrames RJR → sa2json → pyhf → exclusion.json. 20k
  events/point, cteq6l1 LO. Driven by `scan_orchestrator launch --backend native`, ≤4 points in
  PARALLEL, per-point disk cleanup. Wall ≈ 30–50 min/point; the 52-point plane completed in ~hours on this
  laptop (no VM), run over a pause/resume.
- **Signal σ normalization = NLO+NLL, per-mass k(m)** (2026-07-04 re-normalization, post-hoc — no
  regeneration): the original flat cteq6l1-LO × k=1.18 was replaced by
  µ′₉₅ = µ₉₅ × 1.18/k(m), k(m) = σ_NNLOapprox+NNLL(m)/σ_LO(m) ∈ **1.381–1.407** (table below), via
  `scan_orchestrator assemble --nlo-renorm slepton`. k is the like-for-like single-state ratio
  (HEPi ẽ_L-pair NNLL, PDF4LHC21_40 ÷ MG5 ẽ_L-pair LO, cteq6l1 —
  `_infrastructure/slepton_selL_lo_cteq6l1.json`), interpolated in k (nearly flat), not in the
  steeply-falling σ. The pre-renorm assembly is kept as `scan_lo.json`; each point stores
  `mu95_obs_lo`, `k_nlo`, `sigma_ref_fb_lo`.
- **Comparison basis = the PUBLISHED model σ** (2026-07-04 basis fix, `scan_orchestrator rebase
  --process slepton`, post-hoc — no regeneration): ATLAS Fig 44ab quotes the UL on the **inclusive
  fourfold-mass-degenerate ẽ_L,R+µ̃_L,R model σ** (paper: "Slepton refers to the scalar partners of
  left- and right-handed electrons and muons ... fourfold mass degenerate"; **verified**: on the
  published exclusion contour UL/(2σ_LR^WG) = 1.10 median, i.e. µ=1 exactly there, while ẽ_L-only
  bases give 1.47/0.74). Our `sigma_ref_fb` had been the **ISR-tagged 6-state sample σ** (incl. τ̃τ̃,
  leading-jet-tagged) — a DIFFERENT σ basis, off by ×0.56 (m=50) … ×1.01 (m=300). The rebase maps the
  basis-free event-count UL onto the model σ: UL(σ_incl4) = µ₉₅ × σ_incl4^LO(cteq6l1, same cards) ×
  k(m) (`slepton_incl4_lo_cteq6l1.json`), then µ_SUSY = UL/σ_model with σ_model = 2×σ_LR^WG (Resummino
  NLO+NLL, PDF4LHC15 — ATLAS's own normalization; `slepton_flavLR_nlonll_pdf4lhc15.json`). Each point
  keeps `mu95_obs_tagged6`/`sigma_ref_fb_tagged6`; `scan.json:model_basis` carries the per-mass table
  (f_tag = 0.375…0.671, 4-state fraction = 2/3 exactly — τ̃₁+τ̃₂ sum to one more flavour of L+R).

## The artifacts (`plots/`)
- **RRR-COMPARISON HEADLINE — `sleptonbino_fig3_vsATLAS__fig3_expected.{png,pdf}`**: the
  expected-vs-expected variant (RRR Fig 3's own convention — its ATLAS dots decode to the Fig 16a
  *Expected* contour, tip m≈238 GeV). µ_exp(scan) against the Fig 44ab *Expected* UL column, both
  on the model-σ basis; median |rel diff| **25.2%**. The observed-vs-observed variant below is the
  self-consistent twin.
  *(2026-07-06 re-render, CR-001 quality tags + CR-016 layout: the two hyper-excluded floored
  points at (60,5)/(70,5) now render as × "bound, not a limit" and are EXCLUDED from the fig3
  medians, which become **24.1% expected / 24.9% observed over 50 ref-matched cells**; coverage
  stays 52/52 and the all-point two-panel/reldiff medians stay 26.2%. The same render moves the
  legend to the occupancy-scored lower-right and the caption box below the axes — the ATLAS
  contour tail is un-occluded for the first time — and every figure passes the new plot-lint
  gate.)*
- **HEADLINE (observed) — `sleptonbino_fig3_vsATLAS__fig3.{png,pdf}`, RRR Fig 3's actual FORM (one panel,
  form-verified against the EXTRACTED published figure, arXiv:2306.11055 p.6):** a SPARSE BLOCKY
  per-cell (mapyde−ATLAS)/ATLAS map on the scan lattice (discrete ±0.55 banded colorbar in 0.10
  steps, white |Δ|<0.05 central band, outliers saturate — labeled "Limits on µ_SUSY" like the
  paper's) BEHIND the two limits: ATLAS's published observed contour as blue DOTS and mapyde's
  smooth µ95=1 contour as a blue LINE, log-Δm axis. (The first render was a smooth filled heatmap
  built from the caption text without looking at the figure — replaced after extracting Fig 3
  itself; the side-by-side vs the published figure is the check-in artifact.) HONEST content
  difference vs RRR: their tuned cells are mostly white/±15%; ours (on the corrected same-σ basis)
  are mostly −5…−35% (median |rel diff| 26%, the genuine acceptance/fast-sim/stats residual) — same
  form, worse agreement, stated not hidden. An earlier revision of this map read −25…−55% (median
  33%); that included a mass-dependent comparison-basis artifact (see Results) since removed.
- **Diagnostics — `sleptonbino_fig3_vsATLAS.{png,pdf}`** (scatter+tricontour vs ATLAS contour) and
  **`…__reldiff.{png,pdf}`** (the raw two-panel difference map), unchanged in role.

## Results
- **Coverage: 52/52 points (100%).** Excluded (obs µ_SUSY<1, model basis): **36/52** — same count as
  the NLO-renormed tagged basis, zero flips under the rebase (it scales µ up by only ×1.06–1.12; was
  32/52 at LO×1.18: those four LO→NLO flips — m60_dm5, m70_dm5, m200_dm2, m250_dm5 — were all at
  µ_LO ∈ [1.00, 1.05]).
- **Median |(mapyde−ATLAS)/ATLAS| = 26% on the SAME-σ basis (the earlier "33%" compared MISMATCHED
  bases).** The earlier map's numerator was the UL on our **ISR-tagged 6-state sample σ**, ATLAS's is
  the UL on the **inclusive 4-state model σ** — apples-to-oranges, biased by the basis ratio
  σ_tag6/σ_incl4×k = **0.56 (m=50) → 0.76 (m=100) → 0.92 (m=200) → 1.01 (m=300)**: a spurious,
  mass-dependent extra "more constraining" tilt, largest exactly in the low-mass corner. The old
  −25…−55% bulk therefore decomposes into **basis artifact (0…−44%, mass-dependent) + genuine
  residual (mostly −5…−35%)**. After the rebase: median |rel diff| **32.8% → 26.2%**; cells within
  ±0.15: **6 → 13**/52; within ±0.25: **17 → 25**/52; the deep-blue (−0.35…−0.55) population drops
  17 → 9. The strongest whitenings are the low-mass cells (m50_dm2 −49%→−8%, m70_dm2 −42%→−14%,
  m90_dm20 −42%→−21%). Still 44/52 cells blue — mapyde remains genuinely ~5–35% more constraining;
  that residual is acceptance/fast-sim/20k-stats, reported as-is, NOT tuned white. The worst cells
  remain the **saturated small-Δm artifacts** (m60_dm5/m70_dm5 carry the upstream µ=1.0-floor bug →
  +hundreds-%, now +1200–1450% since the basis factor is >1 there) and m50_dm5/m100_dm2 (+46…+88%,
  softest leptons, previously masked by the basis tilt).
- **σ_ref provenance finding (the 59.9-vs-24 fb puzzle DIAGNOSED, measured):** the scan's σ_ref at
  m=200 (59.94 fb = 42.71 fb MG-log σ × k=1.4035) is ~2.1× the 2026-06-06 container run's tagged σ
  (20.47 fb), *same process card (isrslep 6-state), same masses*. NOT a log-parsing bug — the scan's
  `madgraph.log` has a single `Cross-section :` line (42.71 fb) and both the driver's and the
  orchestrator's parsers read exactly it. Cause: **`prepare_native_slepton.py` renders the run card
  from the raw mapyde `default_LO.dat` template and applies only nevents/iseed/ebeam/pdlabel/use_syst
  — the mapyde TOML's `[madgraph.run.options]` block (notably `ptj1min = 50`) is container-path
  machinery and was never applied natively.** The native samples were thus generated with
  **ptj1min=0** (template default; the only jet cut is ptj=20) and cteq6l1, while the container path
  had **ptj1min=50** + lhapdf/NNPDF. Measured split at m=200 (500-evt MG, cteq6l1): σ_tag(ptj1min=50)
  = **19.99 fb** vs σ_tag(ptj1min=0) = **42.83 fb** — the leading-jet threshold IS the ×2.14; the PDF
  swap is the residual +2.4% (19.99 → 20.47). This is a *tag-definition* difference, not a yield
  inconsistency (each sample is normalized to its OWN σ, and the basis rebase removes the tag from
  the quoted UL entirely) — but it IS a documented native-prep deviation from the RRR isrslep sample
  (they tag at 50 GeV; softer 20 GeV ISR ⇒ slightly different acceptance mix).
- **k(m) used** (σ_NNLL ẽ_L-pair / σ_LO ẽ_L-pair; µ-scale = 1.18/k):

  | m [GeV] | 50 | 60 | 70 | 90 | 100 | 125 | 150 | 175 | 200 | 225 | 250 | 300 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | k | 1.381 | 1.382 | 1.383 | 1.385 | 1.386 | 1.393 | 1.400 | 1.402 | 1.404 | 1.405 | 1.407 | 1.402 |

- **Excluded-Δm reach, LO vs NLO-renormalized vs model-basis vs ATLAS** (µ=1 crossing per mass; "≥" =
  every scanned Δm excluded, censored at the lattice edge; the µ_SUSY row is the apples-to-apples one):

  | m [GeV] | 50 | 60 | 70 | 90 | 100 | 125 | 150 | 175 | 200 | 225 | 250 | 300 |
  |---|---|---|---|---|---|---|---|---|---|---|---|---|
  | LO×1.18 (tagged µ) | ≥5 | 5.0 | 5.0 | ≥40 | ≥40 | 33.5 | 26.5 | 21.4 | 21.2 | 15.2 | 11.7 | none |
  | NLO k(m) (tagged µ) | ≥5 | ≥5 | ≥5 | ≥40 | ≥40 | 36.2 | 27.4 | 23.2 | 22.5 | 18.1 | 13.4 | none |
  | µ_SUSY (model basis) | ≥5 | ≥5 | ≥5 | ≥40 | ≥40 | 34.8 | 27.0 | 22.4 | 22.0 | 16.9 | 12.7 | none |
  | ATLAS    | 35.5 | 34.8 | 34.0 | 31.7 | 30.3 | 26.5 | 23.1 | 20.4 | 17.5 | 14.5 | 10.7 | — |

- **RRR Fig-3 construction deltas (forensic reconstruction of their never-published color-map code)
  + validation against the decoded published map.** The published map was decoded cell-by-cell from
  the PDF vectors (32 cells, m∈{100,150,200,250} × Δm∈{0.5,1,2,5,10,20,30,50}, 0.1-wide bins over
  ±0.55, white = [−0.05,0.05]). Adopted from their construction (general, analysis-agnostic):
  **expected-vs-expected** as the RRR-comparison variant (`--limit-kind`), **no interpolation of the
  published grid** (exact tolerance-snapped lattice matches only — all 52/52 of our points match, by
  design of the grid spec), **white-with-note for published-point gaps** (we add a gray circle + an
  on-figure note; RRR renders missing-reference and agrees-within-5% as the same white — mildly
  misleading, we do better). Deliberately NOT adopted (cosmetics / our versions are corrections):
  their `bwr`-sampled palette, linear-Δm cell midpoints, no colorbar extend arrows, 11×9 badge-free
  style; their **jagged tricontour-trick contour** (piecewise-linear on the lattice hull) and their
  **µ capped at 2 by muscan's fixed 0.1–2×10-point grid** — our smooth hull-masked contour and true
  bracketed CLs crossings are known visual/physics deltas vs the published figure, kept on purpose.
  **Cell-by-cell validation (expected variant, 19 comparable cells): 2 same-bin, 6 within one bin —
  target (within one bin) NOT met; ours are systematically bluer by 1–3 bins.** Stated causes, not
  tuned away: (i) their µ comes from a 10-point linspace(0.1,2) scan — µ quantization up to ±0.1 ≈
  1–2 bins per cell by itself; (ii) their sample is the ptj1min=50 container sample vs our
  ptj1min=0 native samples (different tag acceptance mix); (iii) their µ_mapyde treats
  σ_tag6(50 GeV)×1.18 as the model σ and their µ_ATLAS derivation was never published — our rebased
  inclusive-model basis is the MORE correct construction, so bin-level parity with their pixels is
  not the right acceptance bar; the declared-basis comparison against ATLAS itself (median 25–26%)
  is.
- **The renorm moved the µ=1 contour OUTWARD — away from ATLAS, not toward it** (all 6 bracketed
  masses). This is the *coherent* outcome, not a surprise: k(m)≈1.38–1.41 > 1.18 means the flat LO
  normalization had been UNDER-normalizing the signal by ~15%, and that error had been partially
  *cancelling* the acceptance-side over-constraint visible in the difference map. The **basis rebase
  then pulls the contour slightly back IN** (µ_SUSY row: −0.4…−1.2 GeV vs the tagged-µ row) because
  the sample-consistent σ_incl4^assumed = σ_incl4^LO×k_eL sits 6–12% above ATLAS's σ_model (k is the
  ẽ_L ratio; the ẽ_R k is lower, ~1.22 vs 1.40 at m=200 — recorded in `model_basis.approximations`).
  With normalization AND basis now right, the remaining contour offset (e.g. m=150: 27.0 vs ATLAS
  23.1 GeV) is *attributable* — it is the difference map's genuine ~26% residual, nothing else.

## Honest assessment (the bar is high — state it plainly)
This is a **faithful reproduction in FORM** — the workflow produced the RRR Fig-3 mass-plane artifact
(single-panel rel-diff map + published ATLAS contour + own contour) end-to-end, natively, across the
real ATLAS grid, now on the right σ normalization AND the right comparison basis. It is **NOT yet a
publication-grade numerical match.** An earlier revision attributed a "~33% acceptance/fast-sim
residual"; that number CONFLATED a mass-dependent comparison-basis artifact (tagged-6-state vs
inclusive-4-state σ, 0…−44%) with the real residual. The corrected decomposition:
1. **σ normalization: RESOLVED** — per-mass NLO+NLL k(m) replaces the flat LO×1.18. The remaining
   offset is *not* a normalization artifact.
2. **Comparison basis: RESOLVED** (this update) — both ULs now on the inclusive 4-state model σ
   (µ_SUSY, RRR's own convention); median |rel diff| 33% → **26%**, low-mass cells whiten (−49%→−8%
   at m50_dm2), 13/52 within ±0.15. What remains is genuine.
3. **Delphes fast-sim vs full sim:** the soft-lepton efficiency card is the RRR §3.2-tuned one, but
   fast-sim acceptance still differs at the ~10–20% level (RRR's own floor), worst where leptons are
   softest. THE leading residual now (~26% median, mapyde more constraining in 44/52 cells).
4. **Showering + tag definition:** native standalone `pythia_shower` (Monash/HepMC3) vs ATLAS
   MG-internal Pythia8; and the native samples tag the ISR jet at 20 GeV, not the container/RRR
   50 GeV (`ptj1min` dropped by the native prep — see the σ_ref provenance finding).
5. **Statistics:** 20k events/point (vs the larger samples a publication contour would use).
The contour SHAPE + the excluded region are reproduced; closing the magnitude to RRR's smaller residuals
is the verified-Delphes-tuning + higher-stats refinement, deferred.

## Caveats / scope
- **HEPi slepton grid is SINGLE-state** (ẽ_L pair only, PDG 1000011; verified against the WG ẽ_L
  NLO+NLL values) — NOT the 6-state inclusive sum our `chsleptons chsleptons j` sample produces.
  k was therefore built state-for-state (ẽ_L NNLL ÷ ẽ_L LO), dodging the k<1 unlike-quantities trap
  (`.claude/rules/statistics.md`); slepton k-factors are flavour/chirality-universal to good
  approximation. k=1.38–1.41 sits at/above the naive "1.1–1.4" window because the numerator is
  NNLOapprox+NNLL with PDF4LHC21 while the denominator is deliberately cteq6l1-LO (the sample's own
  PDF): the matched-PDF WG ratio (CT10 NLO+NLL ÷ cteq6l1 LO) is ~1.33–1.36, and the NNLL+PDF4LHC21
  numerator adds ~4% — understood, physical, and the correction the sample actually needs.
- **Our sample is the ISR-tagged subset** (explicit `j` in the ME); the INCLUSIVE k(m) is still the
  right multiplicative fix to the normalization assumption (both sides of k are inclusive; QCD
  k-factors are ~flat across the ISR subset). The sample also includes τ̃₁/τ̃₂ at the same mass
  (mapyde's SleptonBino card); the k correction is normalization-only and unaffected.
- **µ=1.0-saturation artifact upstream:** m60_dm5 and m70_dm5 carry `obs_limit=1.0` with a flat
  [1,1,1,1,1] band in `exclusion.json` although their CLs is ≪0.05 across the whole µ grid (they are
  in reality hyper-excluded — the limit-finder floored instead of bracketing DOWN below µ=0.1). The
  renorm+rebase move them to µ≈0.86 ("excluded"), which happens to be the physically right side; they
  are the dark-red saturated cells of the difference map (+1200–1450%: a floored µ becomes a huge
  fake σ-UL where the true UL is tiny). The underlying limit-finder floor is a separate, flagged fix.
- **Basis-rebase approximations** (recorded in `scan.json:model_basis`): (a) τ̃ SR contamination ≈ 0
  (ee/µµ SRs, soft taus) — the tagged sample's accepted yield is attributed entirely to the 4-state
  subset; (b) k(m) is the ẽ_L-pair ratio applied to the whole 4-state σ (measured ẽ_R k ≈ 1.22 vs
  ẽ_L 1.40 at m=200 → σ_incl4^assumed sits ~6–12% above the best NNLL 4-state σ — kept because it is
  what the SAMPLE's yields actually assume); (c) WG model grid loglog-interpolated at the non-node
  masses 60/70/90.
- Native SimpleAnalysis is slepton/EwkCompressed2018-specific (the generality ceiling — `reference/native-pipeline.md`).
- The figure is the native-tool-vs-published-ATLAS comparison; it is the RRR Fig-3 *form*, with the above
  systematics. Heavy per-point intermediates were cleaned (regenerable); `exclusion.json` + `scan.json`
  (+ `scan_lo.json`, the pre-renorm assembly) kept.
- NEXT (PLAN-OF-RECORD §4): the genuine self-drive proof — a fresh agent reproduces this from the docs
  alone, zero operator intervention, to flip the self-drive verdict "partial → yes".

---

## 2026-07-06 addendum — CR-001 applied to the record artifacts (re-render, no regeneration)
The µ-floor fix (CHANGES-REGISTRY CR-001) landed today: `pyhf_exclude.py` now brackets DOWN and
flags floors; the harvest tags legacy floored artifacts (`obs_limit==1.0` + flat band) as
`quality=floored-legacy`; the renderer draws them as gray '×' BOUNDS excluded from the fill and
the contour field. Applied to THIS scan by re-assembly + re-render (per-point artifacts
unchanged): m60_dm5 and m70_dm5 — the two cells this RESULT's caveats diagnosed as +1200–1450%
diff-map artifacts — are now honest bounds. **Headline median |(mapyde−ATLAS)/ATLAS| =
24.9% observed / 24.1% expected over the 50 ref-matched measured cells** (was 26.2% over 52
incl. the two fake cells). Both points remain excluded (their true µ₉₅ is far below the bound);
their measured limits await the CR-004 rescan. Ledger entry: `DEVIATIONS.md` (same date).
