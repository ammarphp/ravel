# Checklist — the verification ladder  ·  how a gap claim becomes ATTRIBUTED, not asserted

Every run writes `VERIFICATION-LADDER.md` (run root) at close — the table below, one row per
rung. The ladder answers the question a RESULT.md alone cannot: *how do we KNOW the recorded gaps
were the actual failure points?* `postmortem-capture` includes it; step 9's Tier-A checks the
table exists and its statuses match the artifacts.

## The rungs (pipeline order — each is a published-or-independent checkpoint)

| Rung | Checkpoint | Compared against | Typical tool |
|---|---|---|---|
| R0 | Toolchain sanity | the locked benchmark baselines | `run_benchmark.py --fast`, `audit.py --check` (read-only by default; `--write` to refresh `AUDIT.md`) |
| R1 | Generation: σ and truth-level shapes | paper's quoted σ / WG tables / gen-level figures | `nlo_xsec.py`, `lhe_check.py`, anchor tables |
| R2 | Reconstructed-object spectra | paper's object-level distributions (digitized) | overlay vs digitized anchors |
| R3 | Selection: cutflow / per-cut efficiencies | published cutflow tables (aux material, theses) | `validate_cutflow.py` |
| R4 | Per-SR A×ε / yields | published acceptance×efficiency maps, SR tables | `certify_acceptance.py` |
| R5 | Statistics: THEIR limit from THEIR inputs | published µ₉₅/UL at a published point | `pyhf_exclude.py` on the published likelihood/yields |
| R6 | Figure: form + numbers side-by-side | the EXTRACTED published figure | figure contract + compose |

## Statuses (exactly one per rung; "not-checked" is LOUD, never implied)
- `checked-pass` — comparison ran; within stated tolerance (cite the artifact + number).
- `checked-fail` — comparison ran; outside tolerance (cite both numbers; this rung brackets a gap).
- `unavailable-published` — no published checkpoint exists at this rung (say what you looked for:
  the resource census + source-ladder rungs walked).
- `not-checked` — a checkpoint EXISTS but was not compared. This row is the debt: every
  `not-checked` carries a one-line reason and survives into the RESULT.md limitations.

## The bracketing rule (what "confirmed failure point" means)
A recorded gap is **CONFIRMED** at rung Rn iff R(n−1) is `checked-pass` and Rn is `checked-fail`
(or the gap demonstrably made Rn unevaluable — cite how). Anything else is **PLAUSIBLE,
UNATTRIBUTED** and must be labeled so in RESULT.md. Corollaries:
- A run whose ladder is all `unavailable-published` below R5 can still confirm at R5/R6
  (their-limit-from-their-inputs and figure form are almost always available).
- Two adjacent `checked-fail` rungs mean the UPPER one is confounded — fix the lower first,
  re-run the ladder, then re-attribute.
- Method-internal anchors (e.g. an AD method's published ROC/SIC on a public benchmark) count as
  rung checkpoints when the analysis publishes them — cite as R2/R3-equivalent.

## Worked precedent (the record scan)
The fig3 slepton scan brackets cleanly: R0 benchmark green · R1 σ vs WG NLO+NLL verified on the
model basis (k(m) 1.38–1.41; on-contour UL/σ_model = 1.10) · R3/R4 certified vs the published
acc×eff (driving-SR tiers) · R5 EXACT (container µ₉₅ 6.36594 reproduced; fresh-gen 0.51%) ·
R6 form-verified vs the extracted RRR Fig 3 — so its ~25% residual is CONFIRMED to live between
R4 and R5's tolerances (acceptance/fast-sim/stats), not below R3 (selection) or at R1 (σ basis):
exactly the RESULT.md's decomposition claim, now stated as a bracket.
