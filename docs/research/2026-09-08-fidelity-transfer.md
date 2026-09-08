# Which RRR repairs transfer to the pipeline?

The pipeline has accumulated useful, reusable safeguards. The remaining RRR
discrepancy nevertheless requires validation of the simulated signal, including
its differential shape and uncertainty model. Strong bookkeeping and reliable
fits cannot establish that a detector approximation represents the experiment.

## What is implemented and preserved

| Repair | Scope and evidence | Publication history |
|---|---|---|
| Guarded profile minimization, refined and checked CLs roots, explicit limit/bound status | Common inference and result transport; controls on counting and published multi-bin models | Already public at d1d6351 and retained in c5bef05 |
| Explicit normalization, per-event moments, control-region signal and finite-MC policy | Native signal construction; no silent replacement of missing nuisance information by measured zero | Already public at d1d6351 and subsequent releases |
| Original-event joins, exposure accounting, activated PDF inputs and durable receipts | Common native execution and provenance interfaces | Public at 2a709d5 and c5bef05 |
| Unique reference nodes in both acceptance readers | New shared helper and regressions, with all six actual compressed ATLAS maps exercised | Included in this source/export update |
| Irregular-grid contour support and readable logarithmic ticks | Shared renderer, linear/log regressions and fresh cached rendering | Included in this source/export update |
| Separate fresh checks from inherited evidence; verify source/export lineage | Publication verification and developer procedure | Included in this source/export update |

The first three are engineering capabilities, not universal physics certification.
The last three similarly prevent wrong comparisons or misleading presentation;
they do not retune generator or detector response. The
[new evidence bundle](../../evidence/audits/2026-09-08-statistical-fidelity/README.md)
and [rendering](../../evidence/audits/2026-09-08-scan-fidelity/README.md) state exactly
what ran. Experimental local median-only fit helpers remain diagnostics, rather
than changing the shared statistical defaults after two boundary points.

The workspace's older source checkout is intentionally held at its historical
revision. Later releases came from separate worktrees, and the current source
starts from 3507b8f, behind public c5bef05. Future changes should follow that
lineage. Blindly exporting the held checkout would revert previously released
repairs. The [distribution procedure](../development/distribution.md) now makes
this check explicit.

## The highest-impact remaining gaps

1. **Effective physics recipe and generator-cut stability.** Requested cards are
   not enough. The executed settings, state composition, normalization and
   radiation treatment must be identified together. The published
   [lower-cut control](../../evidence/audits/2026-09-06-rrr-cut-dependence/README.md)
   fails its prespecified equivalence criterion despite good nominal 150/140
   limits. This is direct evidence that a numerically successful result can
   depend materially on an unclosed generation approximation. It is not proof
   that ISR alone explains every residual.
2. **Response and fitted-bin migration.** Inclusive acceptance can conceal an
   incorrect shape. Near soft-lepton thresholds, object definitions, overlap
   removal, recoil and mT2-dependent selections can move events among bins with
   different background sensitivity. The existing native traces, weight moments
   and truth/reconstruction joins make a differential investigation possible.
   They do not supply the missing response calibration. The documented generic
   b-tag-to-working-point aliases and truth-cutflow definition differences still
   need analysis-specific resolution.
3. **A supported signal uncertainty model.** Nonzero-bin sumw2 addresses sampled
   MC fluctuations. It does not estimate unseen support in empty bins, detector
   response variations, generator variations or their correlations. Removing
   nuisances from an official signal patch is a useful control; copying its
   nuisance response to a different simulated model is not justified by that
   control. The common pipeline should preserve the declared scope and missing
   inputs until validated response variations exist.
4. **Comparability before scoring.** Every test needs to identify whether it
   compares a public likelihood, a fitted-background counting approximation,
   truth acceptance, detector-level selection, or full signal reproduction.
   A regression floor can pass while acceptance certification fails. The current
   benchmark correctly preserves that distinction, but it leaves some scalar
   discrepancies informational rather than resolving them. That is an open
   scientific task, not a reason to relabel all registered benchmarks green.

These are broader than small procedural edits. The inexpensive procedural fix
is to expose rate, shape, MC precision, fit validity and contour support at the
first waypoint, and hold a claim at the scope its evidence supports. The revised
[reproduction checklist](../workflow/checklists/reproduction-closure.md) requires
that review. It does **not** claim that an automatic covariance-aware shape
certificate now exists. Such a certificate needs a declared observable basis,
actual reference uncertainty/covariance, a prospective decision rule and explicit
behavior when those inputs are unavailable.

The [RRR/mapyde design](https://arxiv.org/abs/2306.11055v2) combines public analysis
code and serialized likelihoods with generation, showering and detector simulation.
That suggests a useful architectural rule for RAVEL: validate each handoff against
an appropriate published object before asking an agent to extend the analysis.
This is an inference from that design and our failure evidence. Adding an agent
or a new model-authoring tool cannot on its own establish these downstream
physics relationships.

## Efficient controls and next decisions

| Control | Diagnostic role | Current result and next action |
|---|---|---|
| ATLAS 2016 jets + missing energy | Reference/background input and common counting inference | Fresh 2jl check recovers observed/expected S95 within 2%; use retained acceptance data if this adapter changes, not a new shower campaign |
| ATLAS SUSY-2018-06 three leptons | Released-workspace optimizer and reconstructed-frame behavior | Fresh free fit recovers the known minimum. The separate retained-event eRJR acceptance shortfall remains open; a fit pass does not close it |
| ATLAS SUSY-2018-16 soft dileptons | Fractional references, recoil/threshold selection, fitted-bin shapes | All six maps pass the fresh lookup check. The historical grid remains biased; inspect an independent 225/220 diagnostic anchor only after effective-recipe identity and explicit seeds are established |

For the next RRR anchor, predeclare the high-MET 101–102 GeV mT2-bin fraction
as a shape discriminator, with neighboring bins, flavor, lepton pT and RISR
as diagnostics. Retain pre/post-selection values and event identities. If the
effect recurs with an equivalent recipe, identify the first divergent selection
and change one response or recoil assumption at a time. If recipe equivalence
cannot be established, label the new sample as a current-code control rather
than a pure independent replica of the historical sample. Inspect its shape
before spending time on another complete limit inversion.

No additional events or broad reproduction campaigns were generated for this
assessment. A second analysis is useful when it tests a different failure
mechanism with interpretable references; merely increasing the number of runs
would not identify the cause of the RRR blue bias. Publication still requires
the complete, consistently modeled RRR evidence chain and a review of its
remaining disagreements. Neither these controls nor a passing CI job closes it.
