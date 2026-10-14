# Checks and evidence: inference-engines

`formula.Program` checks constant origins and its expression grammar.
`prescribed_statistic.load` reads the actual document. `record.validate` checks
that a passed prescribed result retains a primary quantity; it does not decide
whether the chosen formula is physically appropriate. `morphing.fit` returns
closure and conditioning evidence. `differential.Model` enforces declared signal
convention and tests covariance at evaluated points.

The executable block runs a generic squared-parameter rule on a small grid.
Tests trace its primary contour, exact wording, input record and uncertified
physics status. They also require a scan continuing past an edge to stay failed,
and reject missing wording and an uncited constant. No toy campaign or collider
likelihood is executed. The engine-specific unit suites hold broader synthetic
numerical controls; those are separate from native or statistical calibration.

| Advisory ID | Candidate check | Evidence needed | Current enforcement |
|---|---|---|---|
| IN-A1 | Measure coverage or type-I error for the actual statistic, nuisance law, bounds and estimator over declared parameter points | Independent pseudoexperiments including fluctuated auxiliary data, seeds, event/MC law, resource budget and uncertainty on empirical error rates | Partial: differential toys and goodness-of-fit toys are implemented for their own contracts; no universal calibration certificate follows from an optimizer flag |

RAVEL implementation: `src/ravel/physics/inference/`,
`src/ravel/physics/coupling_polynomial.py`,
`src/ravel/validation/regression_triggers.py`, and
`src/ravel/workflow/physics_review.py`. Keep threshold overrides with their
recorded basis. Diagnostic review cannot overwrite a computed fail.
