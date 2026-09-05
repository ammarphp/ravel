# Statistical fidelity audit

The limit solver now refines bracketed CLs crossings, validates numerical inputs and fit results, and distinguishes resolved limits from scan bounds. The acceptance comparators retain missing and zero measurements honestly and report the largest residual across every driving region. These are correctness improvements to inference and validation; they do not establish improved detector agreement or asymptotic coverage.

[audit.json](audit.json) binds the tested implementations by SHA-256 and records the runtime, numerical comparison, all nine cached benchmark outcomes, and limitations. The current verification refresh targets source version 0.4.0 from the integration worktree; the starting commit is recorded separately from the tested file hashes. The v0.3.0 audit remains in Git history and its digest is retained in the refresh record.

## Numerical check

For the counting model `n=10, b=10, db=2, s=5`, the old five-point plotting scan returned an observed 95% CLs limit of **1.850559**. Independent pyhf TOMS748 root inversion gives **1.658748**. The old interpolation error was **11.56%**. The revised shared-cache Brent solver agrees with the independent result within the tested numerical tolerance. All five expected limits are also compared, so agreement of the observed limit alone cannot conceal a broken band.

The method continues to use pyhf's asymptotic `qtilde` calculation. Root-finding accuracy and statistical coverage are different questions. See the primary [pyhf hypothesis-test API](https://pyhf.readthedocs.io/en/v0.7.6/_generated/pyhf.infer.hypotest.html) and [bracketed upper-limit solver](https://scikit-hep.org/pyhf/_generated/pyhf.infer.intervals.upper_limits.toms748_scan.html).

## Tested changes

- **65 focused regressions pass.** They cover nonfinite and negative measurements, zero uncertainties, missing comparisons, true zero acceptance, worst-region aggregation, unmatched mass references, independent root agreement, scan bounds, nonmonotonic expected curves, fit validity, and signal-strength unit conversion.
- The existing solver selftest passes its normal, hyper-excluded, unconstrained and NaN-pocket cases. The published SUSY-2018-06 free fit reaches `twice_nll=271.7864`, rather than the previously observed false minimum near 302.52.
- Fit diagnostics expose named best-fit parameters, their actual bounds and bound proximity, and the objective value. Covariance and pull uncertainties are explicitly unavailable. Rechecking the original objective prevents a finite penalty value from masquerading as a valid minimum. A convergence flag alone is insufficient; see [iminuit's fit-validity guidance](https://scikit-hep.org/iminuit/notebooks/basic.html).
- The SimpleAnalysis converter preserves signed selected weights and inserts yields by the original workspace channel order. The original suite exercises its CLI with NumPy branch-array reader doubles, real pyhf workspace validation and JSON Patch application. A negative net signal expectation fails explicitly. The additional real ROOT check is recorded below.

## Additional real ROOT verification

The converter cases in the original 65-test suite used reader doubles. The [ROOT I/O verification](root-io-verification.json), refreshed on **2026-09-05** for the current explicit adapter, runs nine cases with actual tiny ROOT TTrees using **uproot 5.7.4 and pyhf 0.7.6**, with no new installation or historical-input changes. An unsorted `Z,A` workspace receives signal yields `Z=9, A=12`, while pyhf's sorted `A,Z` view predicts totals `22,19`. Explicit channel maps and flavour masks preserve signed sums `1.5,2`. Negative-net weights, missing branches, nonfinite weights, and zero luminosity reject without producing patches. Every case checks that the input workspace, channel map, and ROOT file bytes remain unchanged.

The fixture now declares a distinct signal POI, `signal_strength`, and constructs the patched pyhf model without overriding that declaration. Its earlier `background_scale` POI already modified background samples and is correctly rejected by the current converter. The ninth case retains that previous configuration as a required refusal. This refresh updates the maintained verifier to the supported interface; it does not relax the converter's signal/background separation.

Zero-net signal channels remain valid and are retained as zero. An entirely zero signal template is also accepted by the converter; this I/O check does not claim a finite exclusion limit for that case. The prior eight-case verification remains in Git history. Historical scientific inputs and baseline verdicts are preserved.

The portable [check_root_io.py](check_root_io.py) recreates its inputs in a fresh temporary directory, invokes the converter with the current Python environment, validates the patches through pyhf, and removes its temporary files. From a checkout with uproot, NumPy, pyhf, and jsonpatch available:

```sh
python evidence/audits/2026-09-05-statistical-fidelity/check_root_io.py \
  --out /tmp/root-io-verification.json
```

Use a new output path for each run, or omit `--out` to print the record. The generated record binds the converter and verification script by SHA-256 and includes the actual dependency versions.

## Full cached replay

All **nine** registered cases remain in the denominator. Seven aggregate gates pass. Two remain breached because native artifacts are missing: the three-lepton case's `build/analysis.yoda` and the same-sign gluino case's `outputs/analysis_patched.yoda`. All nine statistical stability checks pass. The available native rivet environment allowed the acceptance comparisons to run on cached scientific inputs instead of reusing four baseline summaries. The resulting six scorable cases have **three PASS and three FAIL**, with three unscorable cases. The two gluino comparisons now report FAIL under the current all-row comparator, as does Gbb with a 26.49% residual. All three still meet their separately declared historical regression floors. This stricter fresh comparison does not overwrite the historical baseline or its recorded verdicts.

No historical measurements or benchmark baselines were rewritten. Counting-mode background correlations remain assumptions; full-workspace modifier correlations are preserved. Acceptance comparisons still omit MC, published and interpolation uncertainty, and their residuals do not identify a detector or generation failure's cause. The legacy `mu95_impact` field is now explicitly labeled as an acceptance-residual proxy. Conditional inverse-signal rescaling is reported separately.

Implementations: [statistical engine](../../../src/ravel/physics/pyhf_exclude.py), [signal converter](../../../src/ravel/physics/sa2json_native.py), [Rivet comparator](../../../src/ravel/validation/validate_cutflow.py), [SimpleAnalysis comparator](../../../src/ravel/validation/certify_acceptance.py), and [regressions](../../../tests/unit/test_statistical_fidelity.py).
