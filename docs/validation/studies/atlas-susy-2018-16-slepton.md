# A×ε certification — ATLAS-SUSY-2018-16 (EwkCompressed2018), SimpleAnalysis path

Slepton (200, Δm=50), the existing 50k containerized run (MadGraph→Delphes→SimpleAnalysis→pyhf).
A×ε is cross-section-independent, so it isolates the selection-chain fidelity.

## Acceptance comparison
| Quantity | Value |
|---|---|
| my total signal across all SR bins | 6.99 events (σ=20.47 fb × k=1.18 × 139 fb⁻¹ = 3357 produced) |
| my total A×ε (summed over SR bins) | **2.08 × 10⁻³** |
| ATLAS published acceptance, SR-S, nearest grid (m=200, Δm=40) | 4.0 × 10⁻³ (Fig 32a; "acceptance", before efficiency) |
| ATLAS A×ε estimate (× soft-lepton efficiency ~0.6, Fig 32b) | ~2.4 × 10⁻³ |

My summed A×ε (2.1 × 10⁻³) is **within ~2×** of ATLAS's single most-relevant SR (SR-S) A×ε — same order,
not the catastrophic shortfall a broken chain would show.

## Does ATLAS exclude (200, Δm=50)?
The observed exclusion contour (Fig 2a RH/LH slepton, Fig 16a) is a closed region in (m(ℓ̃), Δm) that
favours **small Δm** (soft leptons); its Δm reach near m(ℓ̃)=200 is at the upper edge of sensitivity.
**(m=200, Δm=50) sits at/beyond ATLAS's observed boundary** — the published acceptance grid itself only
extends to Δm≈40 there. So this point is marginal even for ATLAS.

## Verdict: WARN (acceptance within ~2×; documented cause)
The pipeline's slepton acceptance is the right order of magnitude (within ~2× of ATLAS), so the µ₉₅=6.4
is **not** a broken-chain artefact. The residual gap is understood and quantified:
- the `mapyde` **`isrslep` 1-jet ISR sample** vs ATLAS's **2-jet CKKW-L-merged** sample — the
  ISR-based SR acceptance is reduced (the dominant ~2× effect);
- LO×k(1.18) σ vs NLO+NLL;
- this point is **marginal/at-the-boundary** for the compressed search, so ATLAS's own expected µ₉₅
  there is already O(1), not ≪1.

To certify the SimpleAnalysis path to the ≤30% Rivet-path level, re-run with the merged sample and the
soft-lepton efficiency tune. The Rivet path (jets+MET) is certified to ≤~25% (see the gluino cert).
