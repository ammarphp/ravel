# CR-004 FULL RESULT — 52/52, corrected (2026-07-07)

Basis: MG-internal nn23nlo (NNPDF2.3 NLO) vs the cteq6l1 record scan; SAME grid + 20k events/point +
same seeds → isolates the PDF term. BOTH scans on the inclusive model-σ basis (rebased).

## Headline
- **Median |(mapyde−ATLAS)/ATLAS| σ-UL residual = 22.0%** (2-D map; 20.8% obs / 17.0% exp on the
  fig3 panels) — vs the cteq6l1 record scan's ~24–26%. The PDF change trims the median residual by
  ~2–4 points, no more.
- **Point-matched σ-UL(nn23nlo)/σ-UL(cteq6l1): median +6.5%** (robust, 48 non-floored of 52 matched).
  Mass-dependent: ≈0 at low mass, larger at the higher masses.

## Verdict (corrects the earlier claims)
The PDF is a **minor contributor (~a few %)**, NOT the dominant lever on the residual. The ~22%
residual is still **acceptance / fast-sim / statistics**, exactly as the record RESULT.md argued.
- This SUPERSEDES the 2026-07-07 *preliminary* claim of −0.8% "not the lever": that partial (37/52)
  had excluded the higher-mass points, which carry the PDF sensitivity — so it understated the shift.
- It also SUPERSEDES the buggy automated first pass (71% / −55.8%): that fired at 50/52 (a status
  race) AND its rebase had FAILED (a floored/healed point lacked σ_ref), so its numbers were on the
  wrong σ basis. Both bugs are now fixed (σ_ref analysis.log fallback; see the registry).

## The remaining residual levers (unchanged conclusion)
Higher statistics (>20k events/point) + fast-sim (Delphes) tuning — NOT the PDF. The LHAPDF
lhaid=260000 idea (CR-004's original motivation) is answered: the PDF basis is not where the residual
lives.
