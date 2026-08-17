# Checklist — judgment protocols  ·  the HOW behind every [judgment] tag

These eight protocols are the difference between knowing physics and *operating* on physics under
limited information. They were extracted from this project's recorded incidents (each cites its
worked case in `framework/FAILURE-CATALOGUE.md`): a weaker model's physics knowledge is rarely the
gap — its *protocol* is. Run the matching protocol BEFORE taking any [judgment] step; the
`judgment-protocols` skill routes here. They compose: a typical step-2 decision runs P6→P3→P2 in
sequence; a discrepancy runs P5 with P4 anchors; every delivery ends with P8.

---

## P1 — look-first
**WHEN:** about to render, compare against, or describe ANY published artifact (figure, table,
contour, cutflow).
**DO:** 1. Extract the actual artifact (`fetch_figures.py --figure N`, `hepdata_fetch.py`) — not
its caption, not your memory of similar figures. 2. LOOK at it (Read the image). 3. Enumerate its
visual/structural grammar (axes+scales, binning, marker/band conventions, panel structure) into
the figure contract BEFORE building the counterpart.
| Thought | Reality |
|---|---|
| "The caption tells me what the figure shows" | Captions omit the visual grammar — the RRR Fig-3 color map was rebuilt as a smooth heatmap from its caption and looked "absolutely nothing like" the real sparse blocky lattice (A1). |
| "I know what an exclusion contour looks like" | You know what a GENERIC one looks like. The published one has a specific form, and the physicist compares against THAT. |
**Worked incident:** A1 (caption-imagined figure) — two supervisor rejections before the artifact
was actually extracted and looked at.

## P2 — basis-manifest
**WHEN:** about to compare ANY two numbers (or curves) where one side is published — limits,
cross-sections, acceptances, yields, significances.
**DO:** 1. Write BOTH sides' conventions explicitly: states summed (charges? flavors? L/R?),
perturbative order + PDF, inclusive-vs-tagged sample, expected-vs-observed column, per-channel vs
combined, and the σ the limit is normalized to. 2. REFUSE the comparison until the two manifests
match (transform one side; record the transformation). 3. Verify with an identity check where one
exists (on the published exclusion contour, UL/σ_model ≡ 1).
| Thought | Reality |
|---|---|
| "Both are 'the cross-section limit', just divide" | Ours was on the ISR-tagged 6-state SAMPLE σ, ATLAS's on the inclusive 4-state MODEL σ — a mass-dependent ×0.56→×1.01 spurious tilt that inflated the headline residual 33% vs the real 26% (A4). |
| "Expected, observed — they're within a band anyway" | Like columns or nothing (A3). RRR's own convention is expected-vs-expected. |
**Worked incident:** A4 (σ-comparison-basis) — caught only by the UL/σ_model=1 on-contour identity
(measured 1.10 on the right basis; 1.47/0.74 on wrong ones).

## P3 — trap-sweep
**WHEN:** routing any new analysis/model pair (step 2), and again before generation (step 3).
**DO:** walk `checklists/physics-traps.md` top to bottom; for each trap answer its CHEAP CHECK;
any hit becomes a numbered CHECK-IN flag with the trap's named route consequence. Never route by
similarity to the last analysis.
| Thought | Reality |
|---|---|
| "It's a resonance search, overlay a Breit-Wigner" | A ~343 GeV A/H→tt̄ signal interferes with SM tt̄ — the signature is a peak–DIP; a naive bump limit is invalid (trap T1). |
| "The paper's model is close enough to the request" | µ–M₂ with M₁=M₂, tanβ=50 is a MIXED wino–bino–higgsino sector, not the paper's pure-higgsino simplified model — σ×BR AND A×ε both move (trap T3; caught live by an eval subject). |
**Worked incident:** ROUTING-EVALS subject 7's T3 catch; the 2408.00049 audit's T5 catch (the
named shape-fit refusal instead of a silently-wrong counting product).

## P4 — anchor-chain
**WHEN:** any produced number is about to be used downstream (σ, A×ε, yield, µ₉₅).
**DO:** 1. Before using it, obtain an INDEPENDENT order-of-magnitude anchor (WG σ tables, the
paper's own quoted σ·A×ε, HEPData yields, an SModelS r-value). 2. If |ratio−1| is outside the
regime you can name a reason for, STOP and run P5 — do not proceed hoping it averages out.
3. Record number+anchor+ratio in the run (the verify-pack traces them).
| Thought | Reality |
|---|---|
| "MadGraph ran clean, the σ is what it is" | 59.9 fb vs the 24 fb anchor was not parsing noise — the card prep had silently dropped ptj1min=50 (B2, a ×2.14 normalization error caught BY the anchor). |
| "The fit converged, µ₉₅ is fine" | A converged fit on a floored bracket returned obs_limit=1.0 exactly — an artifact, not a limit (B1). Anchors catch what convergence flags don't. |
**Worked incident:** B2 (ptj1min drop) — found because the anchor disagreed, not because anything
errored.

## P5 — discrepancy-decomposition
**WHEN:** two numbers/curves that should agree, don't (beyond stated tolerances).
**DO:** 1. Enumerate EVERY candidate cause you can name (basis, normalization, acceptance,
statistics, implementation, reference-decoding). 2. Rank by the CHEAPEST discriminating test, not
by prior plausibility. 3. Run tests in cost order; each test kills or confirms a cause; STOP at
the first confirmed cause, subtract it, re-measure the residual, repeat. 4. The final statement
decomposes the discrepancy into named parts + an honest irreducible remainder.
| Thought | Reality |
|---|---|
| "It's probably statistics, regenerate with more events" | The 33% residual decomposed into a σ-basis artifact (0…−44%, mass-dependent, fixed by a re-normalization costing NOTHING) + a genuine 26% acceptance/fast-sim floor. Regeneration would have spent hours and explained nothing. |
| "One cause explains it" | Discrepancies are usually sums. Subtract the confirmed cause and LOOK at what remains before declaring victory. |
**Worked incident:** the 33% → (basis + 26%) decomposition on the fig3 scan (A4 + RESULT.md §7).

## P6 — source-ladder
**WHEN:** required information is missing (efficiencies, cutflows, likelihoods, model files,
generator settings).
**DO:** climb in order, recording each rung's outcome in `inputs/resource_census.json`
(`resource-sweep` skill automates rungs 1–5): 1. the paper body + auxiliary material; 2. HEPData
record INCLUDING the resources tab (full likelihoods and efficiency maps live there, not under
"tables"); 3. the collaboration's public analysis code/glance pages + GitHub orgs; 4. recast DBs
(Rivet, SimpleAnalysis, SModelS, CheckMATE, MA5-PAD); 5. INSPIRE forward-citations — recast papers
and THESES (theses carry the cutflows the paper cut); 6. ask the physicist WITH the ladder's
evidence + named options. Never invent the missing number; never stop at rung 1.
| Thought | Reality |
|---|---|
| "The paper doesn't provide it, so it's unavailable" | The RRR analysis's public GitHub repo sat unexplored for weeks until prompted (the M1 incident); HEPData full tables were declared "impossible to download" until a second pass found the working endpoint in minutes. |
| "I checked HEPData" | You checked the TABLES. The resources tab is where reinterpretation material lives. |
**Worked incident:** the HEPData-download "limitation" (KNOWN-LIMITATIONS' own resolved-item
cautionary tale) + the missed-RRR-repo failure.

## P7 — conservative-default
**WHEN:** an assumption must be made to proceed and the physicist is not available (or the site
says proceed-with-flag).
**DO:** 1. Choose the option that WEAKENS the exclusion claim (under-estimates sensitivity), so a
later correction strengthens rather than retracts. 2. Implement it REVERSIBLY (a config/
normalization knob, never baked into generated events when avoidable). 3. Flag it numbered in the
check-in + `DEVIATIONS.md`, with the expected sign+size of the bias.
| Thought | Reality |
|---|---|
| "LO σ is the conservative choice" | Not automatically: for the squark cases k<1 (LO-PDF overshoot) — bare LO OVER-excluded. Conservative means you CHECKED the sign, not that you picked the lower-order option (KNOWN-LIMITATIONS R2). |
| "It's a small effect, no flag needed" | Unflagged assumptions are how 2% effects get stacked five deep into a 15% surprise. The flag costs one line. |
**Worked incident:** the flat k=1.18 → per-mass k(m)=1.38–1.41 fix moved the contour OUTWARD —
the "safe" LO-ish choice had been anti-conservative the whole time.

## P8 — kill-the-result
**WHEN:** a result is drafted for delivery (final check-in, RESULT.md, deck) — ALWAYS, as step 9.
**DO:** before the verification panel sees it, argue your own result is wrong three specific ways:
1. BASIS — which convention mismatch would produce exactly this agreement/disagreement? 2.
ACCEPTANCE — which selection/object/detector shortcut would fake it? 3. STATISTICS — which
floor/cap/stat-fluctuation would fake it? Write the three attacks + why each fails (or doesn't) —
they seed the Tier-B adversary, which walks the FAILURE-CATALOGUE as its attack list.
| Thought | Reality |
|---|---|
| "It matches, we're done" | The 141/141 "bit-faithful" SA port matched because it was RJR-CIRCULAR — it read R_ISR from the container it claimed to reproduce. The adversarial pass caught it; the agreement was the disguise (native-simpleanalysis memory, corrected). |
| "The panel will catch anything I missed" | The panel is a NET, not a substitute — a drafted attack list is what makes Tier-B sharp instead of ceremonial. |
**Worked incident:** the RJR-circularity catch; the panel's number-integrity rule (quoted-number
vs artifact discrepancy = automatic FAIL) exists because prose drifted from artifacts twice.

---

## Using these under the model-tier policy
The [judgment] policy (`WORKFLOW.md` §Roles) still binds: a cheap model's job at a judgment site
is to RUN the protocol mechanically (extract, manifest, sweep, anchor) and present the structured
evidence — escalate-to-physicist remains the default verdict where the site names nothing else.
The protocols make escalation SHARP (evidence + named options), not optional.
