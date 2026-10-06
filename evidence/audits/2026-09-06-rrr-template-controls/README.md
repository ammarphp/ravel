# Fresh 100/98 GeV signal-likelihood omission controls

Removing signal MC constraints strengthens the observed limit by 6.1073% and the median expected limit by 3.7411%. Additionally omitting CR signal strengthens them by another 0.4582% and 0.1700%. These changes move the result toward smaller signal-strength limits. They do not explain a discrepancy that requires weakening the nominal bound.

This is a post-observation diagnostic using the completed four-state 20,000-event signal template. The original nominal fit is retained, and the two omission controls were declared before their execution. Neither omission is the preferred nuisance model, a preregistered acceptance test, a calibrated correction, or evidence of RRR closure. No new cross-section conversion is made.

| Quantile | Baseline mu | MC off mu | MC and CR signal off mu | MC off change (%) | Additional CR off change (%) | Total change (%) |
|---|---:|---:|---:|---:|---:|---:|
| observed | 0.3096298567 | 0.2907199316 | 0.2893877407 | -6.107268008 | -0.4582385658 | -6.537520716 |
| expected minus2 | 0.1260837492 | 0.124572728 | 0.1243531825 | -1.198426642 | -0.1762388218 | -1.37255337 |
| expected minus1 | 0.172905962 | 0.1693198213 | 0.1690273788 | -2.074041103 | -0.17271603 | -2.243174932 |
| expected median | 0.2493117505 | 0.2399848003 | 0.2395768969 | -3.741079251 | -0.1699705286 | -3.904691047 |
| expected plus1 | 0.3691183732 | 0.3447645964 | 0.3441833819 | -6.597822983 | -0.1685829949 | -6.75528317 |
| expected plus2 | 0.5388028017 | 0.4813946274 | 0.4805816365 | -10.65476535 | -0.1688824289 | -10.80565376 |

The expected entries are the background-only asymptotic minus-two, minus-one, median, plus-one and plus-two bands. All values are dimensionless mu multiplying the retained signal scale. Ratios are arithmetic comparisons of the specified interventions, with no invented ratio uncertainty or uniform-rescaling assumption. The MC effect varies across the bands, reaching about 10.65% in the upper-two-sigma band.

The first arm removes exactly 16 signal shapesys modifiers, retaining all 38 central signal additions. The second additionally omits the six CR signal additions and retains all 32 SR additions. All 38 background channels, background samples/modifiers and observations remain the same. Parameter counts are 207 → 191 → 191. The exact background JSON bytes are compressed in [background.json.gz](background.json.gz); all three exact patch files are included. [model_changes.json](model_changes.json) records every removed modifier and CR yield. [compiled.json](compiled.json) preserves the reviewed compiled metadata; the standard-library verifier checks its central differences without recompiling the model.

All 18 limits resolve. The maximum retained absolute CLs residual from 0.05 is 5.2962291774e-6. The 48 producer-reported fresh evaluations include roots and bounds. Both controlled fits provide their final 16 evaluations, including descending/ascending order and 32 saved NLL nesting summaries in total. The successful baseline CLI did not retain its full evaluation portfolio. Its six root scan values, typed brackets, final profile summary and 16 log checks were verified in the source-bound report, but the missing portfolio is not reconstructed. These are recorded numerical consistency checks, not new objective evaluations, global-minimum proofs or independent coverage validation.

The high/low SR unions contain 59/11 selected events from the original 20,000, with histogram MC errors about 13%/30%. All 38 channel rows, both union moments, and the 22 zero-selected/precision-unresolved rows remain in [precision.json](precision.json). Removing shapesys does not reduce the underlying simulation error. The analogous 5% diagnostic target is unmet here; the formally specified primary 5% checkpoint is 150/140, so this bundle does not invent a point-specific publication gate.

Both controlled fits used the same a852 numerical engine and retained inference settings: JAX float64, tolerance 1e-9, maxiter 200000, n_curve 11, POI cap 128, and the original root tolerances. They ran sequentially with one 2700-second cap each and no retry. Recorded fit times are approximately 553.43 and 560.59 seconds. The original protocol and local immutable receipts remain preserved. This public bundle omits execution environments, process IDs, authorization text and raw events.

Every mandatory original result/model role has a fixed repository-relative path and original SHA256 in [sources.json](sources.json) and the verifier source constants. Small background/patch inputs are byte-exact; numerical, compiled, precision and review records are explicit projections. The full original local results, receipt context and event payloads are not provided, so the public check does not establish full public raw-data custody or replay those fits. Projection hashes are fixed in the reviewed verifier, in addition to the transport manifest. Updating the manifest alone cannot authorize changed data or omitted source roles.

Run the standard-library verifier from any directory (no private environment needed):

```sh
python -B -S /path/to/checkout/evidence/audits/2026-09-06-rrr-template-controls/verify.py
```

Run the portable admission tests explicitly, from outside the checkout:

```sh
python -B -m pytest /path/to/checkout/evidence/audits/2026-09-06-rrr-template-controls/test_verify.py -q
```

If the exact local originals are available, add `--source-root /path/to/original-checkout` to independently rederive and compare every projection. `curate.py --source-root ... --out NEW_DIRECTORY` writes only the projected data to a new directory. Both paths use standard-library hashing and JSON/arithmetic only, with no inference backend, event traversal or fit.

The prior local report underwent 49 independent controls and an independent stored-output reconstruction, including all 18 limits, six CSV rows, both final pass orders and 32 saved NLL nesting summaries. The public bundle has separate portable admission controls. [independent_review.json](independent_review.json) is an explicitly scoped projection of the prior local review, not a claim that this public bundle reviewed itself. No new events, fits, physics certificate, preferred-model endorsement or acceptance promotion is claimed.
