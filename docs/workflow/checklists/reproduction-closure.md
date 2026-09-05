# Diagnose a failed physics reproduction

Use this checklist when a residual map, cutflow, shape, or limit differs from its
published reference. Follow the existing approved run and certificate policy in
[scientific results](../../reference/scientific-results.md). A completed scan or
a passing statistical regression does not establish experimental closure.

## Establish what is being compared

Record the paper version, figure/table, data release, model states and branching
fractions, collider energy, luminosity, observable, units, and normalization basis.
Pair observed limits with observed references and expected limits with expected
references, including the overlaid contours. Preserve the full planned population,
missing outputs, numerical bounds, and failed comparisons. Use exact published
grid points for quantitative comparison. A residual in an upper limit is not an
observed event excess.

Archive the effective generator, shower and detector cards, the executed commands,
versions, random seeds, normalization report, signal-region sums of weights and
squared weights, channel-level patch, and statistical model. A requested TOML is
not evidence that its settings reached the generator. Do not clean these small
diagnostic artifacts when deleting large event intermediates.

## Test causes in an order that separates them

1. **Numerical inversion.** Hold the workspace and signal patch fixed. Recompute
   the observed and all five expected roots with `ravel.physics.pyhf_exclude`.
   Check the typed status, fitted CLs at each root, brackets and optimizer
   diagnostics. An endpoint is a bound; a crossing interpolated between sparse
   CLs evaluations is not a numerically certified root. Agreement between two
   root solvers tests inversion, not coverage or the correctness of the model.
2. **Likelihood closure.** Where published benchmark signal patches exist, apply
   them to their own released background workspace and recover the corresponding
   published limits before injecting simulated signals. Pin workspace version,
   measurement, channel order, nuisance correlations, and expected-limit
   construction. A structurally valid signal mapping is not a physics validation.
   Inspect signal contamination in control regions explicitly. Omitting signal
   there changes the simultaneous fit, even if its signal-region yields are
   identical. Removing signal-systematic/MC modifiers also changes the model.
   Use published benchmark patches for controlled omission tests; their nuisance
   response cannot be transferred to a new model without supporting evidence.
3. **Normalization and signal composition.** Write the complete yield equation
   `yield = luminosity * cross_section * branching_fraction * acceptance * efficiency`.
   Identify factors already included in cross section or event weights. Expand
   any rebasing algebra before assigning a discrepancy to a k-factor. An
   inclusive/tagged acceptance correction requires matching states, PDF, energy,
   process definitions and cuts. A numerically consistent ratio can still embody
   an unvalidated physical assumption.
4. **Sampling precision.** Keep per-bin `sumw` and `sumw2`, and compute effective
   count `(sumw)^2/sumw2` where defined. Total generated events do not determine
   precision in a sparse driving bin. Repeat independent seeds or use a justified
   resampling model; fixed seeds under different generation settings do not imply
   paired identical events. Zero selected events carry uncertainty. Declare how
   signal MC uncertainty enters the likelihood; do not treat omitted uncertainties
   as measured zero. Separate an MC precision requirement from a residual tolerance.
5. **Truth selection.** Compare particle-level cutflows and distributions against
   the published truth acceptance, before tuning detector efficiencies. Vary ISR
   cuts, jet matching/merging, PDFs, scales, shower settings and decay handling
   separately. Preserve physically consistent process and normalization definitions
   for each variant. Changes in several settings define a bundle comparison, not
   a measurement of one cause.
6. **Detector and analysis.** On the same retained events compare object-level
   definitions, efficiencies, overlap removal, thresholds, derived kinematics and
   exclusive likelihood-bin yields. One inclusive acceptance sum can agree while
   migration among fitted bins biases the limit. Use event identifiers and
   differential records to locate the first divergent cut.
7. **Generalization.** Freeze changes before evaluating held-out mass points,
   splittings, flavors and a second compatible model. If detector response is
   calibrated on benchmark limits, label those points as calibration data. They
   cannot also establish out-of-sample accuracy. Use independent reference
   cutflows and object efficiencies where available.

## Design the next campaign

Before new simulation, choose diagnostic anchors from the actual failure pattern:
isolated outliers, low-efficiency bins, boundary crossings, and a well-populated
control. Specify retained data, changed inputs, held-fixed inputs, independent
seeds, stopping rules and compute budget in the existing CHECK-IN 1 plan. Start
with retained-template and retained-event checks. Escalate to fresh generation
only when the next experiment can distinguish remaining hypotheses. Do not tune
a global signal scale or a color scale to make the reference map look correct.

Choose scientific tolerances prospectively in the artifact-bound comparison plan.
Report signed residuals, absolute residuals, tails and regional breakdowns with
MC precision, rather than only a median that can hide a bias or a red island.
Certification requires the approved scope and complete evidence. An unresolved
point remains unresolved, even when a neighboring point passes.

The retained RRR diagnostic can be recomputed with the script documented in
[`evidence/audits/2026-09-05-rrr-diagnosis/`](../../../evidence/audits/2026-09-05-rrr-diagnosis/README.md).
Its archival comparisons are a diagnosis, not a new physics certificate.
