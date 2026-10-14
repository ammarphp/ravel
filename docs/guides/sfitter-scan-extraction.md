# SFitter signed scan extraction

The free fitted SM intercept and the separately supplied SM template are
distinct records. The delivered polynomial uses the template. Reports retain
both fitted and actually emitted all-point residuals, and handoff eligibility
requires both to pass the original residual bands. A permissive baseline band
cannot substitute for those emitted-polynomial checks. The emitted coefficient
and residual maps preserve all supplied cross terms while treating the template
offset as fixed; its unprovided covariance is not invented.

`sfitter-scan-extraction` connects supplied observed scan summaries to the existing SFitterAgents parameterization handoff, convention stage and native datacard assembler. It does not start a generator, fit, parser or agent application. The ordinary science route uses CHECK-IN 1, one supervised attempt, source custody and delivery-only review. The deterministic Host action `sfitter-scan-extract` and module CLI use the same extraction implementation.

This implementation solves their SM/linear/square/mixed rate polynomial as a fixed linear map. It does not copy the upstream Taylor-normalized shape prescription or treat its R²/mixed-ratio suggestions as universal statistical tests.

## Input connection

The task is `{"request":"scan-extraction-request.json"}`. Its closed request has `schema_version:1`, `id`, `workflow`, `rates`, `scan_definition`, `coupling_sanity_evidence` and `criteria`. Every reference is an ordinary `{path,sha256}` pin. The workflow must contain exactly the full extraction and SM-template source handoffs. Its native 22-axis basis, declared square/mixed population, model/process/order, same scale, flavour, units and original observation/bin identities remain unchanged.

`scan_definition` is the complete source-defined original point and weight roster: `schema_version`, `target_sha256`, `points` and `sources`. Each point declares `id`, `component`, `role`, all 22 `values`, `selected_weight` and ordered `weight_ids`. Component is `sm`, `total`, `linear` or `quadratic`; the last two mean independently source-backed isolated contributions, not a projection inferred from a full matrix-element weight. Role is `training`, `sm_reference` or `held_out`. The returned deck must reproduce the complete roster, including failed or noisy points that remain supplied records. Dropping a point or named weight while rehashing the rate file refuses.

`rates` is a `supplied_observed_scan_rates` document with schema version, exact target commitment, EFT/process/order, full ordered `bins`, `points`, `joint_covariance`, `sampling`, `sources` and `normalization_uncertainty`. Each bin declares its observable ID, bin ID, literal output unit, representation and original bin width. Each point retains full coordinates, signed raw rates, explicit scale/denominator/width normalization, complete signed weight census, original source pins and a declared independence basis. Numerical scales and units are source premises, not an inferred unit conversion or k-factor. Original weights can retain their Decimal W/Q tokens as strings. No generated command or zeroing ledger is admitted as observed rate data.

All raw summary, analysis and weight sources are bound through the deck. A future CMS `model-events` return can supply the complete original LHE/weight journal, parameter point definitions and event denominator as source parents. It does **not** supply per-bin analysis assignments, cross-section/luminosity normalization, isolated interference, shared-sample covariance or independent observations automatically. Those require actual source-defined analysis/normalization summaries. The generator has no actual produced fixture in this source package. Source and sample-origin declarations are not authenticated native event consumption.

## Fixed map, full uncertainty and retained failures

The design contains SM offset plus every requested linear, diagonal square and mixed monomial. A mixed coefficient multiplies `Ci*Cj` once, including the conventional factor two already present in a cross term. A full symmetric coefficient matrix would have half that mixed coefficient in each off-diagonal slot. Positive and negative single points and mixed points can identify signs; point count alone cannot establish rank. Unweighted SVD extracts a fixed linear map after the declared rank and condition checks. It does not optimize a likelihood or claim minimum-variance weighting.

For fixed denominators, `scale/denominator/bin_width` is a conditional fixed multiplier. `joint_delta_denominators` additionally requires every denominator coordinate and its complete covariance with every raw rate and other denominator. The ratio Jacobian then propagates the full joint covariance; this is explicitly a first-order delta approximation, not exact finite-sample calibration. Marginal sumw2 cannot establish independence, and covariance may legitimately be singular while the design has full rank. No ridge, covariance whitening, input symmetrization or eigenvalue clipping is used.

The fitted coefficient covariance is `A C Aᵀ`. The report also retains the emitted response map, with its fitted-intercept rows zeroed because the actual template offset is fixed, and the corresponding full emitted coefficient covariance. All training, held-out and SM residuals retain both joint prediction-minus-observation maps, including training–held-out cross terms. The full matrices, original point/weight census, normalized values, map, singular values, condition, raw SM references and fitted-intercept comparison are delivered. Dimensionful per-bin residual/SM bands are declared source criteria; they do not give a calibrated simultaneous probability. Kappas are central diagnostics against a fixed source SM template; zero SM bins retain null kappas, not fabricated ratios. Their uncertainty is the retained absolute coefficient covariance, not an inferred uncertain-SM ratio law.

Finite arithmetic is checked before every comparison. Cancellation-sensitive covariance products get a bounded 100-digit recomputation of the same binary64 inputs/map, followed by unchanged PSD admission. This does not change a sampling law or repair the input. The operation refuses if arithmetic is nonfinite, compensated work exceeds its budget or the result remains inadmissible. Rank/condition and baseline/residual failures retain their scientific diagnosis without emitting a parameterization handoff. The worker reports unresolved rank as failed delivery with an explicit `numerical_disposition:unresolved`.

## Existing workflow and native preparation

On declared numerical success, the bundle contains `scan-extraction.json`, `parameterization.json`, `workflow.json` and `extraction-receipt.json`. `parameterization.json` covers every requested observable/bin/operator/pair, with original rates, coupling evidence and complete diagnostics pinned. `workflow.json` continues into the existing conventions stage. After a grounded convention handoff, the existing SFitter assembler produces its native card and exact upstream numerical run settings. The native engine normalizes every multi-bin prediction by its full width-weighted polynomial integral; no extracted Taylor shape coefficients replace that law.

The full Monte Carlo coefficient covariance is retained separately. The current native card does not consume it as a finite-MC likelihood; no silent Gaussian/RFit modifier is manufactured. Review must explicitly assess that remaining statistical limitation before a scientific fit claim. Source coupling pins are not a cleanliness verdict: the existing domain review requires actual returned card/generated-coupling evidence, SM order checks and concern-complete judgment before phase advancement.

Use the module CLI for deterministic source materialization:

```sh
python -m ravel.physics.sfitter_scan_extraction --request scan-extraction-request.json --output fresh-bundle
```

For an ordinary study, use mode `sfitter-scan-extraction`, schema 2, at most 60 seconds, one attempt/zero redos, and only claim scope `sfitter_signed_scan_extraction` with action `delivery`. The science CLI plans and supervises it through the normal worker. Approval is always required for that worker. No extraction handoff authorizes a generator, agent call or native fit.

The bounded portable population is at most 768 joint covariance coordinates, at most 512 point records and nonempty source files up to 8 MiB. Wide observations must use an explicitly reviewed larger resource contract; this implementation does not silently drop bins or pairs. The original SFitterAgents Linux/Claude/Apptainer/SLURM application remains a distinct backend, not completed by this operation.
