# Checklist — rigour for a model nobody has tested  ·  [judgment]

The workflow's job is to test a model the analysis's authors did **not** consider, so for the actual
run there is no published result to compare against. Rigour therefore has to be **intrinsic** — built
into the inputs and the method — and the chain is **certified once** on a benchmark the authors *did*
publish. Do not make the per-run answer depend on a known result.

## A. Per-run rigour (every analysis — no comparison needed)
1. **The statistical model is the analysis's own.** Use its published likelihood (step 6.1), or its
   observed+background per SR (6.2), paired with the *matching* selection. A likelihood from a
   different analysis/version invalidates the result — check the channel/SR names match the selection.
2. **The signal cross-section carries its higher-order normalisation** (NLO+NLL where available, or a
   documented k-factor) — a bare LO σ biases every limit conservative by that factor.
3. **The limit reaches the true 95% CL crossing** (step 7): CLs must fall to 0.05, not stop at a grid
   edge. `pyhf_exclude.py` brackets µ with no ceiling.
4. **Physical sanity** (no reference needed): σ is in a sensible range; the acceptance is not
   pathological; the SRs that fill are the ones the model's final state should populate (e.g. squarks
   → low jet-multiplicity SRs, gluinos → high). A surprise here is a flag, not a result.
5. **State the approximations** with the number: counting model vs full likelihood, the background
   uncertainty treatment, the SR/threshold mapping, LO×k vs NLO. The limit is read in their light.

## B. One-time pipeline certification (per routine + generation setup)
Run **once** when adopting a routine — not per model. It certifies that this generation→shower→
detector→selection chain reproduces the analysis; new model points then inherit that trust. It has two
halves — the **object-level** detector-fidelity gate (B0) and the **selection-level** cutflow/acc×eff
cert (B1). Run both; a faithful selection on a mis-modelled detector still gives a biased limit.
0. **Detector fidelity** (`docs/workflow/checklists/detector-fidelity.md`, step 3.5). The object-level half: a
   Rivet routine must **declare** its smearing/efficiencies with an era matching the analysis
   (`verify_smearing.py`); a SimpleAnalysis/Delphes routine must have its card object efficiencies
   **matched to the analysis's published performance** and the resulting per-SR acc×eff **certified**
   against the published acc×eff map (`certify_acceptance.py`, the SA-path analog of the cutflow cert).
   An un-matched soft-object (e.g. low-pT lepton) efficiency loses a large fraction of acceptance
   *before* the selection runs — fix it here, not by tuning the selection downstream.
1. **Acceptance × efficiency vs the published cutflow.** Generate a signal benchmark the authors
   published (their simplified-model point), run the routine, and compare the per-cut / per-SR yields
   to the analysis's cutflow table (often on HEPData, or in the paper). Agreement to ~10–20% certifies
   the chain; a factor-2+ gap means the detector model or selection is off and must be fixed before any
   limit is trusted. (Rivet search routines self-validate their cutflows to roughly this level — note
   the routine's own validation status, e.g. `VALIDATED`.)
2. **Expected-limit sanity.** At that benchmark, the *expected* µ₉₅ (data-independent) should reflect
   the analysis's stated sensitivity. A large expected-limit gap is an acceptance problem, not a
   data fluctuation — the cleanest discriminator of pipeline fidelity.
3. **Record the certification** (routine, generation setup, benchmark point, tolerances met, date) so
   subsequent new-model runs through the same chain can cite it instead of re-validating.

The cert's **A×ε verdict + tier** and the run's **fidelity verdict** (PASS/WARN/FAIL with the attributed
cause classes) are surfaced in the run's machine-checkable headline, `result.json` (the RESULT-PACK,
emitted in step 7 by `result_pack.py`): its `cert` block carries `{verdict, tier, driving_sr,
driving_ratio, worst_driving_mu95_impact, n_attributed}` and a POINTER to the cert json, and its
`fidelity` block carries `{verdict, attributed_causes}`. So a reader (the benchmark gate, the audit)
reads the cert verdict from one parseable shape instead of reconstructing it from the cert json +
provenance prose. The pack POINTS at the cert json (in-run `outputs/cutflow_cert.json` or the
`evidence/validation/studies/<id>.json` sibling) — it does not duplicate the per-row rationale.

## What certification does and does not buy
It establishes that the *chain* is faithful; it does not pre-justify any particular new-model limit —
that still rests on the per-run checks in A. If the generation setup changes materially (merging,
√s, the detector card), re-certify.
