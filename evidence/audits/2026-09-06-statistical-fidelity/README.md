# Statistical fidelity audit — 6 September 2026 UTC

The current implementation passes 91 focused regressions, five numerical self-test controls and nine actual ROOT conversion controls. The full retained-input benchmark keeps all nine cases: seven meet the established gate and two remain provenance breaches. Numerical stability is 9/9, while fresh acceptance verdicts are three PASS, three FAIL and three unscorable. No regression floor, historical audit, original event sample or baseline was changed.

[Machine-readable audit](audit.json) pins the tested implementation and test bytes. [Focused tests](focused-tests.json), [self-test record](selftest.json) and [ROOT integration record](root-io-verification.json) separate their evidence and runtime. These are numerical and data-transport checks. They do not certify detector acceptance or asymptotic coverage.

## Fresh root precision and nuisance-branch control

For n=10, b=10, db=2 and s=5, the current guarded engine with only five display-grid points gives an observed limit **1.6587461726312438**. A fresh model with the standard SciPy optimizer and pyhf's TOMS748 root solver gives **1.6587476148447502**. The relative difference is −8.6945928e−7, or approximately −0.000087%. All five expected roots agree within relative 1e−4. The independent part is the root solver and optimization setup; both use pyhf's likelihood and asymptotic calculation. This is not an independent statistical framework or a coverage experiment. [Full numerical record](root-precision.json), [rerunnable check](check_numerics.py), [pyhf root-solver documentation](https://pyhf.readthedocs.io/en/v0.7.6/_generated/pyhf.infer.intervals.upper_limits.toms748_scan.html).

The retained m150/dm20 likelihood previously exposed different local nuisance minima at neighboring signal strengths, even when the optimizer reported success. The repaired engine checks current-objective values, bounds and feasible gradients, compares a bounded deterministic portfolio of starts, checks likelihood nesting, and validates every root with a frozen portfolio in both evaluation orders. Strict monotonicity and root-residual checks remain in force.

The final-source [guarded JAX64 run](m150-dm20-jax-refit.json) uses the unchanged historical background and patch. It resolves observed μ95=0.623722403950509 and expected median 0.5667101469300333, with all six statuses resolved. Sixteen fresh checks give maximum CLs root residual 2.88616184e−6. Runtime was 877.09 seconds. An [independent NumPy/MIGRAD control](m150-dm20-numpy-lower-branch.json), using numerical derivatives from the selected lower-branch start, finds fixed-Asimov twice-NLL 396.641645740885 and unrestricted observed twice-NLL 408.607333795593. This supports the recovered branch at those tested points; it is not a global-minimum proof or an independent full-limit determination.

The input hashes bind [background.json](../2026-09-05-rrr-refits/inputs/background.json) and [m150_dm20-patch.json](../2026-09-05-rrr-refits/inputs/m150_dm20-patch.json). Their historical missing control-region signal, nuisance construction and generation/acceptance assumptions are not repaired by numerical inversion. The separate 52-point unchanged-template replay was still in progress at audit creation and is not counted as 52 successful fits in this audit.

## Full retained-input benchmark

The [complete result](benchmark-results.json) retains every case, metric, failure and timing. [Provenance](benchmark-provenance.json) records the fresh Rivet runtime and the sole publication transformation: converting the registry pathname to a repository-relative path. Four available YODA acceptance comparisons were rerun using YODA 2.1.3; no acceptance values came from the fallback baseline cache. The initial locked-Python report, which lacked YODA and cached those four comparisons, remains preserved separately.

| Case | Existing gate | Acceptance residual | Fresh acceptance verdict |
|---|---|---:|---|
| conf2016037_gluino_2step_sleptons_1400_60 | BREACH | — | unscorable |
| conf2016054_gluino_onestep_1500_60 | PASS | — | unscorable |
| ins1452559_dm_axial_850_1 | PASS | — | unscorable |
| ins1458270_gluino_1000_100 | PASS | 13.243% | FAIL |
| ins1458270_gluino_merged_1000_100 | PASS | 8.078% | FAIL |
| ins1458270_squark_800_100 | PASS | 2.448% | PASS |
| ins1458270_squark_merged_800_100 | PASS | 3.938% | PASS |
| ins1676551_c1n2_300_100 | BREACH | 6.445% | PASS |
| ins2182381_gbb_1900_1 | PASS | 26.490% | FAIL |

The two breaches are missing generated deliverables: C1N2 `build/analysis.yoda` and the two-step gluino `outputs/analysis_patched.yoda`. Targeted original-run searches and a broader workspace search did not recover those files. Installed published Rivet reference tables were identified and excluded as replacements. [Search scope and evidence](missing-yoda-search.json).

C1N2's observed cross-section-limit ratio to publication remains 4.99641, with an observed-verdict mismatch. This is a serious separate discrepancy, not solved by the RRR numerical repair. The current registry treats that ratio as informational; its provenance breach remains visible. Gbb retains a 26.49% acceptance residual and a failed acceptance verdict even though its established regression floor is met. The gluino acceptance verdicts also fail at 13.2428% and 8.07821%. A regression floor pass must not be read as acceptance certification.

## Reproduction and scope

Run the following from a checkout with the documented dependencies. Use a new output pathname for each check. The ROOT script requires actual uproot; optional dependency skips do not replace it.

```sh
python evidence/audits/2026-09-06-statistical-fidelity/check_numerics.py --out /tmp/ravel-new-root-check.json
python evidence/audits/2026-09-06-statistical-fidelity/check_root_io.py --out /tmp/ravel-new-root-io.json
python scripts/run.py ravel.physics.pyhf_exclude selftest
python scripts/run.py ravel.validation.benchmark --full --python-current --work-dir /tmp/ravel-new-benchmark/work --out /tmp/ravel-new-benchmark/results.json
```

The focused suite combines [26 profile-optimization controls](../../../tests/unit/test_profile_optimization.py) and [65 statistical-fidelity controls](../../../tests/unit/test_statistical_fidelity.py). Invoke pytest from the repository's parent if a local `py.py` shadows its dependency.

The ROOT controls preserve signed selected contributions where each net channel yield is nonnegative, reject missing/nonfinite inputs and background-owned signal POIs, and exercise unsorted channels through actual files. Zero-net and all-zero templates are accepted as input; no finite limit is thereby established.

The [audit limitations](audit.json) remain explicit. Missing counting correlations are not invented. No full covariance, nuisance pull uncertainties, impacts, toy calibration or propagated acceptance uncertainty was computed. Numerical convergence and typed resolved roots describe the supplied statistical model, not the fidelity of the underlying event generation or detector selection. [pyhf hypothesis-test semantics](https://pyhf.readthedocs.io/en/v0.7.6/_generated/pyhf.infer.hypotest.html), [Minuit validity and covariance interfaces](https://scikit-hep.org/iminuit/reference.html).
