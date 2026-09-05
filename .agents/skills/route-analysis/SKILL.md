---
name: route-analysis
description: Resolve a task contract to the concrete analysis route in hep-agentic-pipeline — Rivet vs SimpleAnalysis(native/container) vs no-routine custom path, and the statistical mode (published likelihood / counting / sensitivity-only / blocked). Use at step 2 after physicist-intake, and WHENEVER routine_fetch returns 0 hits or the analysis has no routine at all.
when_to_use: mapping an analysis id to its routine + detector + stat modes; routine_fetch returned 0/0; deciding the no-routine (Option C) path
allowed-tools: Bash, Read
---
# Skill — route the analysis (contract → routine/detector/stat, incl. the 0-hit path)

Turns `task_contract.json` targets into the concrete route.

| Thought | Reality |
|---|---|
| "routine_fetch says 0/0 — no routine exists" | Trial gaps G-CMS-02 + G-AD-02 (hit in BOTH trials): 0/0 was a vocabulary-query artifact; the code-requery loop below found the routine. |
| "No routine, so I'll build my own selection" | G-CMS-01/G-AD-07: the silently-improvised custom path is the recorded failure — Option C is DECLARED in the contract, capped and labeled. |
| "Same signature as the last analysis — same route" | A trap-sweep hit (T2/T5/T10) changes the route entirely; similarity is not routing. |

**BEFORE routing, run the trap-sweep** (`docs/workflow/checklists/physics-traps.md` T1–T12, protocol
P3 of `docs/workflow/checklists/judgment-protocols.md`): interference, long-lived, broken simplified-model
purity, trigger floors, shape-fit stats, compressed-ISR, dark showers, wide widths, σ×BR
conventions, non-standard objects — a hit CHANGES the route (T2 → efficiency-map folding, T5 →
the named refusal, T10 → Option C or the block) and becomes a numbered CHECK-IN flag. Record
`traps_checked`/`traps_hit` in the contract; never route by similarity to the last analysis.

## 1. Resolve the routine — both ecosystems at once
```bash
python3 scripts/run.py ravel.workflow.routine_fetch --query "<ATLAS-SUSY-20XX-XX | insNNNN>"
```
`routine_fetch` matches **analysis CODES / literal ids, not physics vocabulary**. On 0 hits:
- extract the analysis CODE from the paper/HEPData landing page (hepdata.net search; the Rivet
  id's `_I<NNNN>` suffix ↔ `ins<NNNN>`), re-query with the code — NEVER conclude "no routine"
  from a vocabulary query;
- still 0 → check the SimpleAnalysis catalogue (`docs/workflow/analysis-simpleanalysis/`) and the
  Rivet share directly (`rivet --show-analysis`, substring hunt);
- genuinely no routine → the **no_routine route** (below), declared in the contract, never
  improvised silently.

## 2. Pick detector + stat mode (the PRODUCT-CONTRACT §2/§3 tables decide)
- Rivet routine ships → `rivet-smearing`; check `rivet --show-analysis` Status flags
  (SINGLEWEIGHT/NOTREENTRY → run-stage skill knows the flags).
- SimpleAnalysis routine → `simpleanalysis-delphes-native` when a native port exists (today:
  EwkCompressed2018/slepton — `docs/workflow/reference/native-pipeline.md` scope; CR-005), else
  `container` (legacy fallback, ~9 h/pt sequential — say so in the plan).
- Stat: serialized pyhf workspace on HEPData (`hepdata_fetch.py` resources) →
  `published-likelihood`; else `best-sr-counting`/`combined-counting` (exclusive SRs);
  shape/template-fit paper → **`shape-fit`** — route to the `shape_fit.py` engine (Option B,
  `docs/development/decisions/shape-fit.md`), NOT a blanket refusal. Two per-analysis gates: (1)
  REPRESENTABILITY — the engine handles binned 1-D shape/bump fits; an unbinned/multi-observable/
  NN-based fit DOWNGRADES to `blocked-shape-fit` with the reason named; (2) R5 — no limit ships
  until the engine reproduces the paper's own published fit within tolerance (`shape_fit.py`
  prints the gate; engine R5-validated on ins2813982, CR-027). Until R5 closes, the
  generator-level shape comparison + `sensitivity-expected-only` is the shippable offer
  (precedent + boundary: `docs/research/reviews/generality.md`).
- Detector-fidelity gate (step 3.5, `docs/workflow/checklists/detector-fidelity.md`) applies to
  WHICHEVER path wins — name it in the plan.

## 3. The no_routine route (Option C — custom particle-level)
`task_mode=no_routine`, `detector_mode=particle-level`, `stat_mode` per the ask (usually
`sensitivity-expected-only`). The run builds a custom particle-level selection under the run's
`build/` (sources are TRACKED — they regenerate everything else), reproduces the paper's
selection from its text, and labels every output `particle-level-proxy` (PRODUCT-CONTRACT §5).
Flag in CHECK-IN 1 that no routine exists and what that caps: no detector model, no published
acc×eff cert, no exclusion of record.

## Stop conditions
- Never proceed past a 0/0 without the code-requery loop above — it is the recorded dead end.
- A `shape-fit` route runs the engine but the R5 gate HOLDS the limit until it reproduces the
  paper's own fit; a `blocked-shape-fit` downgrade (engine can't represent it, or R5 won't close)
  stops the standard chain and delivers the refusal + generator-level offer.
- The route lands in the contract (update `detector_mode`/`stat_mode` from TBD) and is
  re-validated (`validate_task_contract.py`) before CHECK-IN 1 goes out.
