# RRR reproduction: diagnosis and research program

Date: 2026-09-05. Scope: retained Ravel compressed-slepton campaigns, selected
fixed-template likelihood refits, native Mac infrastructure, and a public-analysis
survey. No new collision events or detector samples were generated for this audit.

## The principal conclusion

The mass-plane disagreement is not presently attributable to a single detector
efficiency or PDF choice. We have found a numerical inversion defect that explains
the conspicuous low-mass red cell, incomplete detector samples in a later campaign,
and omissions from the signal likelihood that can produce a substantial negative
residual even with the experiment's own nominal signal predictions. Other cells
remain discrepant after root refinement. Calling the remainder an intrinsic
fast-simulation floor would get ahead of the evidence.

The strongest next project is a controlled, experiment-anchored reproduction
program. Ravel should produce a supported result, a localized discrepancy, or an
explicit refusal with the missing evidence named. Its success criterion should
be scientific validity over a declared domain, including failed attempts, rather
than the number of tools an agent can invoke.

The numerical and model controls below are useful progress toward that goal.
They do not complete an end-to-end reproduction of the RRR paper or establish
superiority over another agentic system.

## What the figure actually compares

The target is Figure 3 of the PDF of *Reduce, Reuse, Reinterpret: an end-to-end
pipeline for recycling particle physics results*, version 2. The HTML rendering
numbers this illustration differently. Its reference search is ATLAS
SUSY-2018-16, with a slepton–bino model and the released compressed-electroweak
likelihood. The exact upper-limit grid used here is HEPData version 5, table 91.
[RRR paper](https://arxiv.org/abs/2306.11055v2),
[ATLAS analysis](https://arxiv.org/abs/1911.12606),
[limit table](https://doi.org/10.17182/hepdata.91374.v5/t91).

The colored quantity is `r = sigma95_Ravel / sigma95_ATLAS - 1`. Blue means that
Ravel's upper limit is too small, hence too strong. Red means a weaker upper
limit. A red cell inside an exclusion contour is not an excess of observed
events: the model can remain excluded while the two upper limits disagree.

Our expected-limit drawing also overlaid observed ATLAS contour points. The
renderer now selects the matching observed or expected family, with an explicit
notice when none is supplied. The expected contour is cached from
[HEPData table 9](https://doi.org/10.17182/hepdata.91374.v5/t9). This fixes the
comparison's presentation; it does not change a single fitted limit or residual.
The RRR caption itself does not explicitly identify the observed/expected family
of its ATLAS dots, so the workflow no longer asserts an interpretation that the
caption does not establish.

## Findings, ordered by evidence strength

### 1. The prominent low-mass red cell is largely a numerical artifact

At slepton mass 50 GeV and mass splitting 5 GeV, the old observed limit was
obtained by linearly interpolating a very wide CLs bracket. At the reported
limit, a fresh fit gives CLs about 0.000604, instead of the required 0.05.
Holding the signal patch, background likelihood and normalization fixed, the
guarded root finder changes the raw observed signal-strength limit from
0.0959401 to 0.0478638. The observed residual changes from **+87.84% to −6.29%**;
the expected median changes from **+40.52% to −0.31%**.

A separate NumPy/MIGRAD evaluation at the new observed root gives CLs
0.0500019. This cross-check addresses numerical inversion at that point, not
frequentist coverage or the correctness of the detector model.

The red cell at mass 100 GeV and splitting 2 GeV does not disappear: its observed
raw limit changes by less than 1%. At 200 GeV and splitting 20 GeV, refinement
also leaves a large negative residual. A fourth selected native point, 150 GeV
and splitting 20 GeV, failed twice on nonmonotonic CLs diagnostics. Its attempted
refits remain failures; a provisional root is not promoted to a result.

Thus three of four selected native anchors resolved. They were chosen to diagnose
specific failures and are not an unbiased accuracy estimate for the full plane.
The existing production solver already refines roots; this work applies it to
old outputs and demonstrates why old cached numbers cannot inherit its assurance.
[Inputs, outputs and independent numerical checks](../../evidence/audits/2026-09-05-rrr-refits/README.md).

### 2. The signal likelihood omits terms that materially affect limits

As a control, apply ATLAS's own released signal patch at masses 150/130 GeV to
the corresponding released background workspace. The fitted observed limit
agrees with the published table to approximately **0.03%**, and the expected
median to **0.93%**. This is an important separation: the tested statistical path
can recover this experimental result when given the experimental signal model.

Independent review found that the retained background's digest differed from
the official patchset metadata. The original cached archive resolves this:
its background matches the declared digest, and the retained copy differs only
in 24 integer/float representations such as `1` versus `1.0`. Values, structure,
parameter configuration and tested likelihood evaluations agree exactly. Both
files and the exhaustive difference record are retained; the fit used the
numerically equivalent copy, not the original byte representation.

Two controlled omissions reveal what the current compressed native patch leaves
out. Removing the published signal nuisance modifiers while preserving nominal
signal yields strengthens the observed limit by about 5.4%. Then omitting the
signal contributions in the six control regions strengthens it further. Combined,
these omissions strengthen the observed limit by about **13.7%**, and the expected
median by about **12.0%**, relative to the full signal patch.

All 156 retained native patches contain only the signal-strength normfactor;
they do not carry a signal uncertainty model. The compressed native selection
also does not provide the six control-region signal contributions. A structural
pairing check that accepts untouched control regions cannot establish that their
signal contamination is negligible.

This is a controlled causal result for one published benchmark. It neither
decomposes the entire plane nor isolates MC statistics from all other signal
nuisances. Published ATLAS signal-systematic responses cannot simply be borrowed
for arbitrary Ravel signals. The proper implementation needs model-specific
control-region selection, weighted signal templates, and justified nuisance
responses and correlations. A global correction factor would conceal that work.
[Full model and omission controls](../../evidence/audits/2026-09-05-rrr-refits/README.md).

### 3. A rescan includes detector outputs from only about 1% of its events

Four CR004 points at slepton mass 250 GeV contain 206–233 detector events despite
20,000 showered events. Two points have only three selected detector events yet
carry ordinary limits. Their patches normalize over the truncated detector
sample, while their reported cutflow acceptance uses the full 20,000-event count.
These are incompatible exposures, not precision samples. Three selected events
alone imply roughly 58% relative Poisson counting uncertainty before other effects.

The current detector converter already rejects a detector/normalization event
count mismatch. New adversarial tests explicitly reproduce the 221- and
206-event cases, as well as near-complete mismatches, and verify rejection before
conversion. This closes the current fail-open path; it does not repair historical
events. Multiplying historical results by an event-count ratio would not recover
the missing sample or establish why the detector stage terminated early.

### 4. The historical PDF comparison is confounded

The original native preparation did not apply the requested generator options.
The later fix changed the effective jet cut before CR004. At mass 200 GeV, the
tagged LO cross section changed from roughly 42.71 to 20.04 fb, closely matching
an earlier fixed-PDF cut comparison of 42.83 to 19.99 fb. The campaign also changed
the sampling procedure and contains the incomplete detector outputs above.
Identical seeds under different settings do not make these identical events.

Consequently, the original-to-CR004 shift cannot be assigned to the PDF alone.
The newer cteq6l1 campaign's smaller residual also contradicts a simple one-cause
reading of the original comparison. PDF effects remain plausible; their size and
direction require a controlled comparison on a consistent normalization basis.

### 5. Normalization must be expanded before attributing the residual

For the retained rebased scans, the implemented algebra for the final cross-section
upper limit reduces to

```text
mu_raw * (1.18 / k_exact) * (sigma_inclusive4_LO * k_rounded / sigma_model)
       * sigma_model
 = mu_raw * 1.18 * sigma_inclusive4_LO * (k_rounded / k_exact).
```

The displayed model cross section and the chirality k-factor cancel apart from
rounding below 0.004%. They cannot by themselves explain a 20–30% discrepancy in
this particular final residual. The inclusive four-state LO normalization and
tagged six-state generated acceptance still embody a physical assumption, and the
CR004 denominator uses a different PDF basis from its tagged sample. Those deserve
validation rather than a cosmetic rebase. This cancellation is specific to the
retained computation, not a general claim that higher-order corrections are irrelevant.

### 6. Neither a small aggregate acceptance difference nor smoother colors closes physics

One fresh 150/130 GeV point has an aggregate acceptance difference of +3.37%, based
on 142 selected events, with approximately 8.4% counting precision. It does not
establish agreement in the exclusive bins driving a simultaneous likelihood.
ISR, lepton thresholds, reconstruction efficiencies, overlap removal and migrations
can alter those bins while leaving the total yield similar.

The RRR methodology includes benchmark-dependent soft-lepton efficiency tuning
and truth-acceptance checks before testing additional models. Ravel must distinguish
calibration points from held-out tests and preserve the relevant truth, detector
and likelihood evidence. Matching a tuned benchmark alone is insufficient to show
generalization. [RRR methodology](https://scipost.org/SciPostPhysCodeb.27/pdf).

## What the three campaigns establish

The diagnostic retains the original planned 52 points in each campaign. The table
describes historical reference-comparison eligibility, not physics certification.
Negative medians mean systematically stronger limits.

| Campaign | Observed comparable / planned | Signed median residual | Median absolute residual |
|---|---:|---:|---:|
| Original | 50 / 52 | −22.72% | 24.92% |
| CR004 | 50 / 52 | −15.65% | 20.77% |
| Fresh August scan | 52 / 52 | −13.22% | 14.01% |

All 152 unflagged observed limits and all 152 expected medians reproduce linear
interpolation of their retained CLs samples. Four material nonmonotonic curves
are retained and identified. The apparent trend toward smaller residuals cannot
be promoted to a measured improvement in detector fidelity while the numerical,
exposure and model issues are unresolved.
[Three-campaign forensic audit and per-point tables](../../evidence/audits/2026-09-05-rrr-diagnosis/README.md).

## A sequence that would establish a useful physics pipeline

The new [reproduction checklist](../workflow/checklists/reproduction-closure.md)
turns this diagnosis into an order of operations. These are proposed scientific
milestones, not claims that their campaigns have already passed.

| Milestone | Concrete work | Evidence required to advance |
|---|---|---|
| Numerical closure | Refit the full retained 52-point population; investigate failed fits and all six observed/expected roots | CLs-at-root checks, typed bounds/failures, optimizer evidence, complete denominator; no silent interpolation fallback |
| Published-model closure | Replay several official patches spanning compressed, boundary and control-contaminated points | Matched workspace release and published reference, pointwise discrepancies, documented construction differences |
| Signal-model completeness | Implement and independently validate CR signal selections and weighted signal uncertainty templates | Exclusive channel/bin closure, sumw/sumw2, nuisance justification and correlations, controlled omissions with unchanged yields |
| Sampling and normalization | Rebuild the minimum affected anchors on one consistent process/PDF basis | Complete event exposure, effective cards, uncertainty budget per driving bin, independently checked yield equation |
| Truth closure | Separate ISR cuts, matching/merging, PDF/scale, shower and decay variations | Truth cutflow and relevant spectra before detector tuning; distinct seeds and retained variation identities |
| Detector closure | Fit only declared calibration points, then freeze the response | Exclusive-bin tests on held-out masses/splittings, threshold and migration diagnostics; no tuning to every residual cell |
| Generalization | Test a second model and an independently chosen analysis | Prespecified scope and tolerances, full failed/missing population, physics and numerical evidence bound to exact artifacts |

Sampling should be chosen by useful precision, not by a fixed event count for
every mass. For simple positive, independent, unit-weight counts, a 5% relative
counting error corresponds approximately to 400 selected events. That is a planning
heuristic, not a universal certification threshold; weighted events, signed
weights, zero bins and shared nuisance parameters need their own treatment.
Each simulation plan should declare a cost ceiling and stopping rule based on the
driving bins and required uncertainty budget.

Coverage studies belong after the likelihood and procedure are fixed. Spot checks
of CLs roots, central published limits or background-only toys do not establish
coverage for every low-count, nuisance-boundary or data-selected analysis. The
program should test representative boundary cases, signal injections and the
actual selection rule used to choose regions or analyses.

## Mac portability: implemented scope and remaining test

The native path now has a read-only doctor, architecture and Rosetta diagnostics,
explicit environment prefixes, pinned/checksummed Miniforge bootstrap for Intel
and ARM, compiler discovery, and staged shower/RJR/RestFrames builds with dry runs.
The independent review caught and repaired a disagreement between the doctor's
compiler detection and the builder's `CXX` override. The local Apple Silicon
prerequisites pass; helper tests exercise invalid environments, unsafe archives,
partial builds and ownership of outputs.

The new macOS CI matrix tests these prerequisites and helpers on both architectures.
It does not build the full HEP stack or establish cross-architecture physics
agreement. Clean installation still needs a complete versioned Delphes/ROOT/Pythia
recipe and a small shared-input physics corpus. Binary architecture, ABI compatibility,
selection outputs and limits must each be checked. Existing native/container parity
is bounded historical evidence, not an all-Mac guarantee.
[Portability commands and boundaries](../reference/native-portability.md).

## How to expand ambitiously without losing scientific control

The [companion survey](2026-09-05-public-hep-analysis-landscape.md) provides 26
curated analysis candidates, a separate snapshot of 45 public ATLAS model-index
entries, 33 primary sources and pinned repositories. It is a starting census,
not an exhaustive survey of all reusable HEP data. No candidate is promoted to a
newly validated executable analysis by its inclusion.

The first expansion should exploit released full likelihoods and benchmark signal
patches, because they permit cheap statistical closure before expensive generation.
Then add measurement/EFT reuse, LLP maps, shape-based dark-sector searches, and
preserved open-data workflows as distinct scientific routes. Their objects differ:
signed EFT interference and covariance cannot be squeezed into a monotonic positive
signal-strength limit; displaced response needs lifetime and geometry; broad
resonances need shapes; learned anomaly searches need protected data splits and
calibrated trials. New instruction files can enforce admission, but cannot supply
missing response maps, correlations or calibration measurements.

MadAgents and ColliderAgent are relevant demonstrations of orchestration and
research workflow breadth. Established tools contribute complementary lessons:
mapyde exposes the simulation chain, pyhf makes likelihood structure executable,
Rivet/Contur define measurement reuse, SModelS limits reinterpretation to documented
maps/topologies, and RECAST/REANA motivate preserved workflows. Exact revisions and
primary references are recorded in the companion survey; no competitor code was
copied. A fair comparison must test matched scientific tasks and equivalent inputs,
count refusals/failures, and separate user effort, compute cost, physics error and
unsupported conclusions.

The ambitious architecture is an evidence-driven analysis registry with independent
states for discovery, artifact retrieval, executable adapter, benchmark reproduction
and validated scientific domain. Each transition should name its required evidence.
An agent can propose a route, assemble artifacts, run bounded experiments and diagnose
failures; it must not grant its own scientific claims by changing a status string.

To test whether Ravel's procedures add value, compare the same tasks with and without
the proposed physics/statistics gates, holding the underlying engines and resource
budgets fixed. Predeclare held-out analyses and failure criteria. Measure false
scientific claims and useful validated completions as well as success rate. This
would test the causal contribution of the infrastructure instead of assuming that
a large validation codebase is already superior.

## Delivered changes and limits of this pass

This pass delivers the archival diagnosis, selected refits and model-omission
controls, contour-family correction, detector-exposure regression tests, explicit
reproduction procedure, Mac bootstrap/build hardening and a source-backed expansion
catalogue. Review and test details are in the
[implementation record](../development/history/2026-09-05-rrr-and-portability.md).

It does not deliver a newly simulated 52-point plane, CR signal templates for new
models, propagated detector/theory uncertainties, full frequentist calibration,
or clean Intel/ARM HEP execution. Those are specific measurable scientific tasks
above. The main gain is that several large discrepancies now have falsifiable,
quantified explanations, and the remaining work can be separated into experiments
that will actually distinguish competing causes.
