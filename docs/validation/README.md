# Benchmark validation

Generated from the committed historical `benchmarks/{cases.json,results.json}`.
Baseline timestamp: `2026-07-09T02:22:22+00:00`. These pages do not claim a fresh replay.

All 9 registered cases are listed, including failures and unscorable comparisons.
The 7 observed model-independent S95 comparisons span 4 distinct searches; their worst deviation is 8.6%.
This tests the statistical/data-input layer. It does not establish detector selection or end-to-end fidelity.
Acceptance is scorable in 6 cases and unscorable in 3; recorded cert verdicts are {'PASS': 4, 'WARN': 1, 'FAIL': 1}.
Acceptance certification, the regression tier, and numerical stability are separate judgments.

The end-to-end mass-plane result is recorded separately in the
[flagship scan](../../evidence/scans/slepton-bino-figure-3/RESULT.md): 24.9% median same-basis
cross-section-limit residual over 50 reference-matched cells from a 52-point scan.

| Case | Observed S95 deviation | Acceptance verdict | Baseline gate |
|---|---|---|---|
| [ins1458270_squark_800_100](cases/ins1458270-squark-800-100.md) | 0.2% | PASS | OK |
| [ins1676551_c1n2_300_100](cases/ins1676551-c1n2-300-100.md) | unscorable | PASS | OK |
| [ins1458270_gluino_1000_100](cases/ins1458270-gluino-1000-100.md) | 5.4% | WARN | OK |
| [ins1458270_squark_merged_800_100](cases/ins1458270-squark-merged-800-100.md) | 0.2% | PASS | OK |
| [ins1458270_gluino_merged_1000_100](cases/ins1458270-gluino-merged-1000-100.md) | 5.9% | PASS | OK |
| [conf2016054_gluino_onestep_1500_60](cases/conf2016054-gluino-onestep-1500-60.md) | 8.6% | unscorable | OK |
| [ins1452559_dm_axial_850_1](cases/ins1452559-dm-axial-850-1.md) | 2.3% | unscorable | OK |
| [conf2016037_gluino_2step_sleptons_1400_60](cases/conf2016037-gluino-2step-sleptons-1400-60.md) | 8.2% | unscorable | OK |
| [ins2182381_gbb_1900_1](cases/ins2182381-gbb-1900-1.md) | unscorable | FAIL | OK |
