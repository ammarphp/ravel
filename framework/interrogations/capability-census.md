# Capability census — testing the "small number of categories" hypothesis (roadmap §4, W2a)

**Date:** 2026-07-07 (overnight roadmap execution, checkpoint C8).
**Question (supervisor's):** do most target analyses/asks fall into a small number of categories
admitting more rigid, less-judgment routines?
**Method:** three independently gathered substrates, synthesized here —
supply side: `overnight-roadmap/inputs/census-substrate-local.md` (SModelS DB 135 analyses /
1113 SR-datasets, Rivet 41 BSM searches of 2041 analyses, 79 local SimpleAnalysis routines) and
`inputs/census-substrate-web.md` (26 ATLAS full likelihoods, 81 public SA routines, MA5-PAD 62–67,
CheckMATE 13 active, LLP efficiency-map practice);
demand side: the 7 physicist prompts (`CAPABILITY-ROADMAP.md` §1) and Collider-Bench's 53 tasks
(`inputs/census-colliderbench.md`), plus the Reinterpretation Forum's four documented product
types. Every number below carries its source file; nothing here is new measurement.

## Verdict: the hypothesis HOLDS, with a precise shape

**Demand clusters into SIX product categories** (complete over both demand samples + the forum):
1. **reproduce/recast** a published analysis for a new/same model — the current engine's class
   (Collider-Bench: 53/53; prompts: 3/7)
2. **summary-of-limits** across analyses (prompts: 2/7; forum type 2) — no event generation on
   the base path
3. **projection** to higher luminosity (prompts: 1/7; forum type 4)
4. **replane** — parameter-plane transformation of published limits (prompts: 1/7; forum type 3)
5. **extension/hypothetical** — beyond-published-grid scans, hypothetical detectors (prompts: 1/7)
6. **anomaly/model-agnostic study** (prompts: 1/7)

**Execution routes within reproduce/recast collapse onto FIVE cells** (supply-side masses):
| Route cell | Supply mass (measured) | Machinery today |
|---|---|---|
| counting + published routine (Rivet/SA) | Rivet 41 BSM (37/41 scalar-SR; 90% wireable to counting) + 79–81 SA routines (~95% SUSY) | THE ENGINE (steps 1–9, native chain) |
| counting + efficiency-map folding (no routine needed) | **90% of SModelS's 1113 SR-datasets are EM-type; 47% of its 135 analyses have EM data** — both numbers are true, quote by use-case | SModelS installed (`reinterpret_db.py`); G2a route = wiring + validity discipline (C10) |
| counting + full published likelihood | 26 ATLAS analyses (2→26 growth since 2020; **0 CMS** via this channel) | pyhf path exists; likelihood presence is the EXCEPTION, not the default |
| shape-fit statistics | ~40% of the pre-registered 20-analysis search census (8/20) | BLOCKED by design (PRODUCT-CONTRACT §6.1); decision memo C14 |
| no-routine particle-level (Option C) | 5/6 Collider-Bench analyses have NO routine — the benchmark deliberately lives here | Option C (two trials + step-4 §C) |

**Special-object overlay (cuts across cells):** LLP/displaced → published per-object efficiency
maps in YAML are STANDARD practice (EXOT-2019-23 template: 6-D map, ~25% documented accuracy,
explicit validity envelope) — the P7 class has a well-trodden bounded-accuracy path;
substructure/tagger objects → particle-level proxy or published WP efficiencies (T10).

## What "rigid routine" can honestly mean per category
The census supports rigid PROCEDURAL SPINES with NAMED judgment forks — not judgment elimination:
- **summary-of-limits**: rigid spine (census → harvest → basis-manifest → render); judgment
  localizes to sensitivity selection + basis conversion (G4). The P1 HVT survey run already
  improvised ~this spine; C11 formalizes it.
- **EM-folding recast**: rigid spine (SLHA/spectrum → SModelS EM fold → r-values → limit
  statement); judgment localizes to validity ranges + topology mapping. Biggest supply mass.
- **projection**: rigid spine (likelihood/counting inputs → lumi rescale under DECLARED
  background scaling → expected-only labels); judgment = the scaling assumption, flagged.
- **reproduce w/ routine**: already the engine; the ladder (C7) is its rigidity upgrade.
- **replane**: semi-rigid for SUSY-shaped cases (SModelS's 121/135 SUSY DB is the natural
  substrate); NON-SUSY replanes remain judgment-heavy (only a 14-analysis EXOT slice folds).
- **shape-fit + anomaly**: NOT rigid-routine candidates; paradigm decision (C14) and study-class
  framing respectively.

## Ranked rigid-routine build candidates (mass × machinery ÷ judgment-fork count)
1. **Summary-of-limits track (G1)** — 2/7 prompts + forum-documented method + zero generation;
   machinery = HEPData harvest + basis manifest. → C11.
2. **EM-folding route (G2a)** — 90%-of-SR-information supply mass; SModelS ALREADY INSTALLED and
   validated in this repo (crosscheck r_obs=8.07 precedent). → C10.
3. **Projection module (G2c)** — forum-standard, small, pyhf-native. → C12.
4. **Replane, SUSY slice (G2d)** — rides on 1+2 (SModelS topology space); non-SUSY stays
   escalation territory. → C12 spike.
5. Counting+routine hardening via the verification ladder — already underway (C7).

## Honest caveats (the census's own basis manifest)
- Demand N is small and skewed: 7 prompts (reinterpretation-shaped) + 53 Collider-Bench tasks
  (100% reproduce-shaped, near-orthogonal — it densely samples the cell we already serve, and
  0/53 non-standard-detector vs 4/7 in the prompts). Real CERN demand presumably sits between;
  the categories above are COMPLETE over both samples, which is the strongest claim this N buys.
- Supply masses are database-shaped (SModelS is 90% SUSY-cascade), so the EM route's mass is
  SUSY-shaped too; a generic Z′/leptoquark/dark-shower ask finds only the 14-analysis EXOT slice
  directly foldable.
- Rivet's BSM archive is small, ATLAS-skewed, and 20/41 obsolete-or-unvalidated — a supplement,
  not a recast DB.
- Collider-Bench corroborates two roadmap claims independently: the G4 normalization-basis
  bottleneck (their §4.3 recurring failure) and the [judgment] escalation policy (their
  physicist-in-the-loop beats all autonomous agents), plus a 6% cheap-model fabrication rate
  caught only by trace-level provenance audit — the number-integrity rule's external twin.

## Feeds
`framework/capability-matrix.json` (the per-prompt × capability board consumed by audit v2, C5);
W3 gates: C11 (summary) and C12 (projection/replane) are hereby EVIDENCE-GATED OPEN; C10 was
ungated. The three sub-products Collider-Bench surfaced that neither our workflow nor the prompts
contain (observed-data replay, signal-efficiency-vs-mass curves, kit/nokit ML-retrain fork) are
recorded as future intake vocabulary, not built tonight.
