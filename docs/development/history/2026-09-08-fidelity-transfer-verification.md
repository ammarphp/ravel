# Reference-grid and plotting transfer verification

Source baseline: `3507b8f3edbbf53925dd2e7ac9b3653a01504871`, the source revision
behind public `c5bef054eb2d5efa38f01938a3b8e8ec245dab1d`. Work was developed in a
separate worktree. Historical simulation source, cards, events and run receipts
were preserved. No agent delegation, dependency installation or event generation
was used for this review.

## Checks performed

| Check | Observed result |
|---|---|
| Six actual ATLAS Figure 32 maps and three acceptance-efficiency products, two row orders | 1,350 queries, zero failures |
| Exact legacy lookup predicate on those maps | 13 wrong coordinates and values per map in either order; mismatch identities retained |
| Two other ATLAS numerical controls | Counting observed/expected S95 43.6513/54.8857; three-lepton free-fit twice-NLL 271.78623; 2.92 seconds total |
| Reference, statistical, contour, rendering and evidence-integrity selection | 206 passed and one optional-luminosity header failure in 4.37 seconds |
| After repairing that header failure | All 43 rendering and current-fidelity checks passed in 0.84 seconds |
| Evidence-builder and publication-scope regressions | All 61 passed in 0.57 seconds |
| Source publication checks | Repository layout, current audit integrity, retained RRR arithmetic, catalog and generated-page checks passed |
| Source evidence manifest | 17 claims passed, zero warnings or failures; two already-missing historical generated-YODA files remain missing |

The tests include adversarial duplicate/ambiguous nodes, mixed interpolation
slices, fractional coordinates that would otherwise share a rounded label,
missing contour support, altered evidence populations, removed source pins and
changed inherited fields. They are automated failure controls and root-agent
review, not an independent-personnel review or a proof of physics fidelity.

Review corrected a diagnostic counterfactual from `<= 1 GeV` to the old reader's
actual `< 1 GeV` predicate. The preliminary 23-per-map count was not retained as
the finding. The final [reference result](../../../evidence/audits/2026-09-08-statistical-fidelity/reference-grid.json)
and source-bound audit record the corrected population.

The cached scan was rendered again after the optional-header repair; its PNG/PDFs
pass the house-style checks. The final README figure was visually inspected.
Original per-point limits, reference YAML and residuals are unchanged. The older
render and its code remain in the prior dated audit and Git history.

## Data, environment and scope

ATLAS Figure 32a–f are exact copies of retained HEPData v5 YAML. The submission
file is a declared six-entry metadata subset, with the original submission hash,
ATLAS credit, license, unit convention and truth-selection restriction recorded.
Workflow pointer: [reproduction closure](../../workflow/checklists/reproduction-closure.md).
Interpretation pointer: [fidelity transfer](../../research/2026-09-08-fidelity-transfer.md).
No generator, shower or detector input was edited.

The development worktree restored one 73 KB local-only historical Gbb YODA file
from the held checkout, verifying its existing SHA-256 before copying it. This
preserves the old development evidence pin without changing the public evidence
selection or the two genuinely missing artifacts. Existing Python/replay and
plotting runtimes were used with single-thread math limits. No environment
package or frozen simulation executable changed.

The new current statistical audit inherits the old nine-case replay explicitly;
that full campaign was not rerun. The current inference engine is byte-identical
to the preceding release. Source/export checks distinguish those retained
observations from the newly executed controls. Full RRR reproduction, calibrated
detector response, covariance-aware shape certification and signal-systematic
closure remain open.
