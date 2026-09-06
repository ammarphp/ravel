# Native fidelity revalidation — 2026-09-06 UTC

The current source reproduces the preserved **200,000-event eRJR differential** and all production-driver region counts. The differential is byte-identical to the September 5 record: all **18 old/new region counts, 12 cutflow counts and 73 changed-event records** agree. This confirms retained-event reconstruction consistency. The **23.1% SR-low acceptance deficit remains**, exceeding the existing 15% tolerance. No physics certificate was issued.

This is a new dated record. Every file in [the September 5 audit](../2026-09-05-native-fidelity/README.md), its reference metadata and the original detector ntuple were hashed before and after the replay and remain unchanged. The new [verification record](verification.json) pins the actual source, commands, runtime, outputs and predecessor audit. [Comparisons](comparisons.json) enumerate every checked count and changed-event identity; [the differential](erjr_differential.json) retains the complete event records and discriminating variables.

## Actual eRJR replay

The retained C1N2(300,100 GeV) input contains 200,000 events and has SHA-256 `91c8ed8887601986f401971007a25754c38d3bf01d33c0bfa8456443ac09f8ac`. Two independent command invocations processed it: the differential routine evaluates the historical and paper-defined boost expressions, and the current `native_simpleanalysis` driver evaluates the production selection. Both completed on September 6 UTC using the existing Python 3.14.5, NumPy 2.4.6 and uproot 5.7.4 environment. Neither command generated events or ran a limit fit.

| Region | Historical expression | Paper definition | Current driver |
|---|---:|---:|---:|
| Preselection | 1,055 | 1,055 | 1,055 |
| SRlow | 43 | 95 | 95 |
| SRISR | 19 | 19 | 19 |
| CRlow | 50 | 65 | 65 |
| CRISR | 16 | 16 | 16 |
| VRlow | 22 | 28 | 28 |
| VRISR | 19 | 19 | 19 |
| VRISRsmallPTsoft | 2 | 2 | 2 |
| VRISRsmallRjetsinv | 15 | 15 | 15 |

Fifty-two events enter SRlow and none leave. Its acceptance is `95 / 200000 = 0.000475`, versus the preserved reference `0.00061805`. The resulting relative difference is `−0.2314537658765473`. The [reference](reference.json) is copied unchanged from the historical audit and identified as such; it is not a new reference determination. The original physical interpretation and paper provenance remain in the [earlier report](../2026-09-05-native-fidelity/README.md).

From a source checkout with the retained input and NumPy/uproot installed:

```sh
python -B scripts/run.py ravel.physics.sa_routines.ewkthreeleptonerjr2018 \
  --input trial-runs/CR005cert_c1n2_300_100/output/analysis/Delphes2SA.root \
  --out /tmp/new-erjr-differential.json
python -B scripts/run.py ravel.physics.native_simpleanalysis \
  --input trial-runs/CR005cert_c1n2_300_100/output/analysis/Delphes2SA.root \
  --output /tmp/new-erjr-driver --ngen 200000 --routine EwkThreeLeptonERJR2018
```

Use fresh output paths. Exact executed arguments, elapsed times and environment handling are in [replay-execution.json](replay-execution.json). `<repo>` denotes the source checkout root; it replaces the machine-specific absolute prefix only. The new [driver text](driver-counts.txt) also matches the prior recorded driver hash. Raw detector and output ROOT files remain local and are not distributed with this audit.

## Compressed SR parity and new control-region outputs

The current compressed driver writes **141 SR branches plus six control-region branches**. Its previous whole-output byte-identity claim cannot describe that expanded output. The bounded current evidence is exact per-event SR weight agreement on two retained inputs:

| Retained sample (parent/LSP GeV) | Input events | Prior/current output rows | Equal SR branches | Original-only rows |
|---|---:|---:|---:|---:|
| 150/130 | 1,000 | 685 / 685 | 141 / 141 | 0 |
| 200/150 | 10,000 | 10,000 / 7,164 | 141 / 141 | 2,836 |

Rows are aligned by unique Event ID. Every original-only row has zero weight in every SR. The 200/150 container branches store float32 values and the native branches store float64 values; all values agree exactly after lossless float64 promotion, although their original storage bytes differ. Both 150/130 outputs store float64. An initial stricter storage-byte assertion exposed this distinction; its failed probe log is retained, and the final report states the narrower verified claim.

The native selections were run earlier in this development session with the same selection, diagnostic and converter source hashes that are current here. This dated refresh **rechecked their saved ROOT outputs read-only**; it did not repeat those two selection loops. [The new parity record](compressed-sr-parity.json) enumerates every SR, source/output hashes, dtypes, CR moments and original-input preservation. [The earlier actual selection/transport verification](compressed-prior-verification.json) is retained with an explicit origin hash and path sanitization. The read-only comparison can be repeated with:

```sh
python -B evidence/audits/2026-09-06-native-fidelity/check_retained_sr_parity.py \
  --out /tmp/new-compressed-sr-parity.json
```

This requires the original retained files and the source checkout's recorded current outputs. The six new CR raw counts, in VV-high/VV-low/tau-high/tau-low/top-high/top-low order, are **1, 1, 0, 0, 0, 0** and **13, 4, 1, 2, 3, 1**. The latter includes one mixed-flavour VV-high event. These are selection and weighted-moment transport checks. No executable ATLAS CR acceptance reference was established, and the sparse samples do not demonstrate sufficient MC precision. Earlier 38-channel patch checks retain 27 and 14 zero-selected bins with unresolved precision. They do not certify those bins to have zero uncertainty or establish the experimental/theory nuisance model.

## Current engineering checks and limits

The same five test files were run from the checkout's parent directory with inherited `PYTHONPATH` removed. [The complete test record](tests.json) retains each test status, source hashes, exact commands and original log/JUnit hashes.

| Environment | Passed | Failed | Skipped | Warnings | Time |
|---|---:|---:|---:|---:|---:|
| Locked Python 3.12 | 120 | 0 | 10 | 32 | 2.53 s |
| Existing Rivet Python 3.14 | 130 | 0 | 0 | 35 | 7.99 s |

The ten Python 3.12 skips require optional uproot; all run successfully in the existing Rivet environment. The tests cover Lorentz-frame regressions, signed weights, CR selection boundaries, event traces, event I/O and source-bound replica pooling. The pooling cases include distinct generator/shower/detector seeds and an ordinary CLI child without inherited `PYTHONPATH`. Its `sqrt(sumw2)` uncertainty is explicitly a conditional Poissonized independent-event approximation; generator cross-section integration uncertainty is separate. These targeted checks are not a full-suite or remote-CI result, nor a demonstration of genuine multi-replica physics pooling.

The earlier zero-lepton cutflows, cached zero-lepton output comparisons, direct Delphes nominal-weight read and figure inspection were **not repeated** here. Their historical records remain in the old audit. There was no fresh generation, detector retuning, altered tolerance, fitted exclusion limit, recertification, full-plane closure or resolved ATLAS truth/reconstruction acceptance definition. Retained-event parity verifies the stated comparison only.
