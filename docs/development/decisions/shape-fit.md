# DECISION MEMO — the shape-fit statistical boundary (G2b)  ·  for the physicist/supervisor

**Date:** 2026-07-07 (roadmap C14). **Status: SIGNED — Option B; engine BUILT** (CR-027
`shape_fit.py`, R5-validated on ins2813982). See the signed decision line + build record below.
**The stake:** ~40% of the search population is shape/template-fit (8/20 in the pre-registered
census, `docs/research/reviews/generality.md`). Before this decision, every such ask got the
NAMED refusal + a generator-level offer (`docs/reference/scope.md` §6.1) — two live precedents
delivered that refusal correctly (the 2026-06-21 dijet+photon audit; eval subject #4). Option B is
now SIGNED and the scoped `shape_fit.py` engine is BUILT (R5-validated on ins2813982): a
representable binned/template fit (single-observable spectrum + a published background
parameterization family) now routes to `stat_mode=shape-fit`, R5-gated per analysis before any
number ships; only an unrepresentable fit (unbinned / multi-observable / per-event NN) still gets
the named `blocked-shape-fit` refusal. Per-instance R5 closures (e.g. 2408.00049) remain the
residual work — see `docs/reference/scope.md` §6.1. Three costed options (below) were the basis for
the decision:

## Option A — stay blocked (cost: 0)
Keep §6.1 as the permanent product: named refusal, generator-level/expected-only offer, honest
labels. **Pro:** zero risk of silently-wrong limits (a per-bin counting shortcut on a shape-fit
spectrum is invalid — Collider-Bench's own recurring failure class is normalization/statistics
missteps); the refusal is already routed, evaluated, and understood by users. **Con:** ~40% of
asks terminate at CHECK-IN 1 forever; P4-class prompts (dijet+photon, wide-width variants) never
produce a number.

## Option B — the scoped binned-template fit engine (cost: ~2–4 dev sessions + validation run)
Build the NARROW version, not a general fit framework:
1. Scope: single-observable binned spectra (m_jj, m_jjγ, m_tt̄…) where the paper publishes the
   observed spectrum + a background parameterization family (the dijet-function class) — the
   commonest shape-fit search shape.
2. Mechanics (all standard, no invention): digitize/HEPData the observed spectrum; refit the
   paper's OWN background functional form (χ²/ML on the sideband or full window per the paper's
   procedure); signal template from our generation (per width — trap T8); limit via pyhf
   shapesys/normsys on (bkg-fit ± envelope, signal template) or a plain profile-likelihood scan.
3. Validation gate (non-negotiable, ladder R5): reproduce the PAPER's own limit at ≥2 published
   mass points within a stated tolerance BEFORE any reinterpretation number ships; the fit
   function + window + envelope treatment recorded in the basis manifest.
4. Honest caps: no correlated-systematics model unless published; wide widths flagged as
   extrapolation beyond the paper's narrow-width grid; interference asks (T1) remain BLOCKED.
**Pro:** unlocks the single biggest refused class with the industry-standard method; P4 becomes
fully servable end-to-end. **Con:** background-fit subtleties (window choice, function degrees of
freedom, spurious-signal) are exactly where silent wrongness lives — hence the hard R5 gate; real
cost is the validation discipline, not the code.

## Option C — generator-level-only comparisons, upgraded (cost: ~1 session)
Keep the statistical refusal but upgrade the offer: standardized truth-level spectrum overlays
(our signal on the published spectrum figure) + σ×A sensitivity statements at the paper's quoted
per-bin sensitivities where published. **Pro:** cheap, honest, some value per ask. **Con:** still
no limit; risks being mistaken for one (labels must scream).

## Recommendation
**B, gated and scoped exactly as above — but scheduled AFTER the W3 tracks that are pure
engineering wins (C10 efficiency-map folding, C11 summary track, C12 projection).** Rationale:
those three serve P1/P2/P7 with near-zero physics risk; Option B carries real silent-wrongness
risk and deserves a dedicated, validation-first session rather than a slot in a crowded wave.
Option C is NOT recommended as a separate build — its deliverables fall out of B's step 2/3
anyway.

## The decision line
- [ ] A — stay blocked   · [x] **B — scoped fit engine** (as specified above, with the
  non-negotiable R5 validation gate)   · [ ] C — upgraded truth-level offers
Signed: supervisor (chat directive: "go with the scoped fit engine (option B, as you specified
and recommended)")  Date: 2026-07-07
Build record: CR-027 (`shape_fit.py`, overnight-2 checkpoint D3); the C10/11/12 sequencing was
overtaken by the same directive — B builds tonight alongside them.
