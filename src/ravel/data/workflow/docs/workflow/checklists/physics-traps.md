# Checklist — physics traps  ·  the domain trap-sweep behind protocol P3

Run this sweep when ROUTING any analysis/model pair (step 2) and again before GENERATION (step 3).
Each trap: what it is → the CHEAP CHECK (≤ minutes, no event generation) → the route consequence →
the CHECK-IN flag line. A hit is never a dead end — it is a NAMED route change or a numbered flag.
This is the domain-physics sibling of `docs/reference/failure-modes.md` (our own process incidents);
the Tier-B adversary uses BOTH as attack lists. Sweep ALL traps — they compound (a wide resonance
that also interferes hits T1+T8 together).

For a reinterpretation of a measured spectrum, also walk the interpretation notes listed in
[inference engines](../../reference/inference-engines.md#applicability-checks); the
`differential-likelihood` mode records them with every result.

| # | Trap | Cheap check | Route consequence |
|---|---|---|---|
| T1 | **Signal–SM interference.** The BSM amplitude shares initial+final state with a large SM amplitude → the observable signature is peak–dip (or pure shape distortion), NOT a bump. Classic: a heavy (pseudo)scalar A/H→tt̄ near the pair-production threshold against SM tt̄; W′→tb̄ vs s-channel top. A declared power-law coupling scaling (g/g₀)^k, or a morphing basis without its lower orders, on a final state shared with an SM amplitude of the same structure assumes the interference away. | Shared initial and final states with a Standard Model amplitude, including a loop-induced channel? Are interference and relative phase relevant in the signal window? If a power-law scaling or reduced morphing basis is declared on such a final state, run a σ-only probe with the SM amplitude on and report the fitted lower-order fraction. | A naive σ×BR bump limit is invalid. Inspect interference-aware published results or construct a compatible coherent signal-plus-background prediction and statistical model through current operations. Preserve signed interference, relative phase, response and uncertainty requirements. Withhold unsupported limit claims while recovering or testing missing inputs; a sensitivity diagnostic does not complete a requested constraint. Never overlay a Breit-Wigner and call it a limit. |
| T2 | **Long-lived / displaced decays.** Any new state with cτ ≳ 0.1 mm (check Γ in the card/model!): prompt-object reconstruction (vanilla Delphes, standard SA objects) silently returns ~zero or nonsense efficiency — exit 0, empty/false SRs. | Compute cτ = ħc/Γ for every BSM state in the decay chain; any in [0.1 mm, 10 m]? Analysis mentions displaced/disappearing/DV/dE-dx objects? | The standard chain is OFF the table. Route: efficiency-map folding (the analysis's published per-object efficiency maps on HEPData resources — the LLP-recast standard), or the honest block. Detector_mode label changes; flag the cτ. |
| T3 | **Simplified-model purity broken at the target point.** Published limits assume a pure state / fixed BRs (pure higgsino, 100% BR); the requested plane breaks it (M₁=M₂ & tanβ=50 → MIXED wino–bino–higgsino: masses, σ, BRs, AND A×ε all move). | Does the target parameter plane hold the published model's stated assumptions (purity, BR=1, degeneracies) at EVERY point of the requested range? | Per-point spectrum calculation (mixing matrices) + σ×BR re-weighting BEFORE any limit mapping; A×ε revalidation where the kinematics shift; basis manifest (P2) mandatory. Escalate with the decomposition — this is never a silent proceed. |
| T4 | **Trigger/reconstruction floors vs the mass range under study.** The range extends below (or between) the analyses' trigger thresholds or boosted-regime floors (diboson resonances below the boosted-jet mass regime; low-mass dijets vs HLT floors; low-energy anomaly windows). | Compare the analysis's trigger + leading-object thresholds against the signal's characteristic pT/mass at the studied parameter values. | "Coverage is sparse/absent here" is a FIRST-CLASS answer — evidence it (thresholds vs kinematics), name the nearest covering analyses (TLA/ISR-assisted/prescaled), and deliver the coverage map instead of forcing a limit from an insensitive search. |
| T5 | **Shape-fit statistical paradigm.** The analysis uses a functional form or templates across a spectrum. Its likelihood, correlations and background treatment determine the statistical operation. | Read the paper's statistics section: "background parameterization", "fit function", "template/profile over the spectrum" vs "signal regions + yields". HEPData: no per-SR yields table is a strong hint. | Inspect the published/native likelihood and current binned, continuous or custom fit construction contracts. Recover the complete domain, background and nuisance model, correlations and applicable validation. A shape label is not a blanket refusal. An incompatible counting substitute remains invalid; hold the dependent inference while constructing and qualifying the appropriate fit, preserving the original requested scope. |
| T6 | **ISR-driven compressed-spectrum acceptance.** Δm ≪ m: everything visible comes from ISR recoil, so A×ε hangs on generator ISR modeling, merging choice, and tune — a 2× yield error with exit 0. | Δm/m ≲ 0.1 anywhere in the plane? SRs cut on ISR proxies (R_ISR, pT(jet1)/MET, soft leptons)? | ME/PS treatment is a DECLARED choice (merging or matched ISR jet in the process definition); run-card jet cuts audited against the anchor σ (P4 — the ptj1min incident lived here); expect the fast-sim floor to be worst here and SAY so in the deliverable. |
| T7 | **Dark-sector shower under-specification.** Hidden-valley / semi-visible-jet asks: Λ_d, N_c/N_f, dark-hadron spectrum, r_inv, decay portal — papers under-specify, Pythia HV defaults silently fill the gaps → wrong jet substructure and MET with no error. | Are ALL HV parameters the paper used recoverable (paper, aux material, authors' cards on HEPData/GitHub)? List each one: source or ASSUMED. | Every assumed parameter is a numbered flag; a truth-level validation gate vs any published gen-level distribution runs BEFORE detector simulation or scans; sensitivity-only labels until validated. |
| T8 | **Wide resonances (Γ/m ≳ 5%).** Narrow-width approximation breaks: σ×BR factorization degrades, the low-mass PDF-enhanced tail grows, signal shape morphs across the fit window, interference (T1) grows with Γ. | Γ/m over the studied range (strongly coupled mediators can reach tens of percent); does the published analysis quote limits only for narrow widths? | Evaluate shape and acceptance at each requested width using new generation or applicable, independently reviewed coherent amplitude reuse/full matrix-element reweighting. Check phase-space support, effective statistics, interference, acceptance and tail/Breit-Wigner cutoff conventions. Generate new samples when reuse cannot cover the required support or precision. Normalization-only rescaling of a narrow template is invalid. A narrow-only published limit cannot directly supply broad-width constraints; qualify the appropriate model and fit. |
| T9 | **σ×BR / coupling convention mismatches.** HVT model A vs B (g_V), single-charge vs charge-summed EWKino grids, one-flavor vs summed sleptons, σ×BR vs σ×BR×A — the silent factor-of-N class. | Before ANY published-limit comparison: write both sides' basis manifest (P2). The WG-grid charge/flavor conventions are in `.claude/rules/statistics.md`. | Transform onto ONE declared basis and record it in the artifact (`model_basis` block precedent); the identity check where available (on-contour UL/σ_model = 1). k<1 or a factor ≈2/N is a convention smell, not physics (B-class incidents). |
| T10 | **Non-standard reconstruction objects.** The analysis selects on objects the fast chain doesn't model: groomed fat-jet substructure (τ_N, SoftDrop mass), b/τ/top taggers at specific WPs, soft tracks, displaced vertices, AD scores. | List every selection variable in the paper's object section; mark each as {Delphes-standard, derivable at particle level, requires published efficiency, unavailable}. | Derivable → particle-level proxy with fidelity labels (Option C precedent: CMS A→BC, ATLAS AD trials); published per-object efficiencies → fold them; neither → the block, with the object named. Tagger WPs NEVER guessed — published (ε_sig, ε_bkg) or flagged. |
| T11 | **Spectrum-card override + decay-table traps (generation-side).** Mass/mixing inputs depend on the imported model and restriction; MSOFT/HMIX presence alone does not establish an override; width-only DECAY tables (no BR rows) → Pythia imports nothing → undecayed sparticles → empty SRs, exit 0. | `lhe_check.py --expect-mass` BEFORE showering, always; card diff against the model-cards recipe. | Fix the card, never the symptom; the gate is mandatory (steps 03); catalogue C1 is the worked case. |
| T12 | **Production-mode PDF sensitivity.** b-initiated processes (bbA/bbH), photon-initiated production, or heavy-flavor-enhanced modes: the default LO proton PDF choice moves σ at the tens-of-% level, and 4F vs 5F scheme changes the process definition itself. | Is any initial-state parton b/γ, or the paper explicit about 4F/5F or a special PDF? | Match the paper's scheme+PDF (declare it in the basis manifest); if unmatched, quote the σ spread as a flagged uncertainty, not silently. |

## Sweep output
Record the sweep with the trap-sweep tool. Write one verdict per trap in a JSON file:

```json
{"verdicts": [
   {"id": "T1", "hit": false, "evidence": "no shared SM amplitude in the final state"},
   {"id": "T8", "hit": true, "evidence": "requested width reaches 20% of the mass",
    "consequence": "width-dependent shape and acceptance study", "flag_number": 3}
 ],
 "escalations": [],
 "obligations": []}
```

`verdicts` holds a row for every trap T1–T12; the example shows two of the twelve. A hit carries its `consequence` and either a
positive `flag_number` (the numbered CHECK-IN flag) or an `escalations` row `{id, reason}`.
Then write and check the record:

```sh
python -m ravel.workflow.trap_sweep write --rundir <run> --input verdicts.json
python -m ravel.workflow.trap_sweep validate --rundir <run>
```

`write` refuses an existing record; pass `--replace` to record a revised sweep and log the change
in `DEVIATIONS.md`. The file `inputs/trap_sweep.json` contains `traps_checked` (T1–T12),
`none_hit`, `verdicts`, `traps_hit: [{id, evidence, consequence, flag_number}]`, `escalations`
and `obligations: [{trap, obligation_kind, artifact, status}]` with status `PENDING`, `PASS` or
`FAIL`. A sweep with no hits is still recorded. The Tier-B adversary re-runs the sweep and a
mismatch is a finding. Name each hit in the contract's `escalate[]` or in `DEVIATIONS.md`.

**Every obligation-bearing hit needs a `PASS` obligation before generation ships.** The writer
opens a `PENDING` `route-consequence` obligation for each hit that has none. Record the evidence
artifact and `PASS` once the route consequence is done, for example a width-shape-and-acceptance
study for T8, and check with `validate --require-discharged`. `validate_run_state.py`'s
`inv_trap_obligations` invariant (`trap-obligations-discharged`) fails the run once
generation or a result pack exists while any hit other than T3 and T9 lacks a `PASS` obligation.
The basis-manifest gate (`inv_basis_manifest_before_comparison`) already covers T3 and T9.
The scan-only D10 gate (`param-validated-before-scan`) is the complementary obligation ledger over
`inputs/validations.json`; this one applies to every task mode at generation.
