# Source-bound slepton origin accounting — 2026-09-06

The new `ravel.physics.slepton_origin` diagnostic partitions retained native compressed-slepton
events by their stored production ancestry. It preserves original generated exposure and
normalized event weights, including signed weights, and checks every one of the 38 likelihood
channels against the original signal metadata and patch. It does not generate events, fit a
likelihood, change detector response or issue a physics certificate.

The implementation is in `src/ravel/physics/slepton_origin.py`; its 59 focused controls are in
`tests/unit/test_slepton_origin.py`. The implementation SHA-256 at review closure is
`e644014e3983e6608b018c69a7a2d5da408212e710c5f0530e089acd992a9ec7`.
The test file SHA-256 is
`8e411af42f11f5cbae92fe0d07e53c709bfeb5e1ad76c7bb1e2568534999f519`.

## Accounting contract

The caller supplies a saved native execution plan and its exact SHA-256. The reader verifies
the original successful ancestor receipts through `sa2json`, source and output hashes,
dependency receipts, the full compressed model, the generated exposure and the reconciled
normalization. It rehashes the source files after traversal. This is historical data reading:
the recorded producer runtime is retained, while the diagnostic reports its own reader
runtime. It does not claim execution under a new producer runtime or authorize a stage rerun.

Original Delphes `Event.Number`, converted all-event `Event`, trace event identities and the
analysis ROOT rows join by exact keys. Shuffled records are allowed; missing, duplicate,
invented or inconsistent records reject. The analysis population must equal the trace's
solved RJR population. Nonselected events remain in the denominator. Native one-lepton plus
track rows outside the 38-channel model remain valid diagnostic rows; they are not assigned
invented track flavour evidence.

The disjoint event categories are `four_state_only`, `contains_stau` and
`unresolved_topology`. Signed parent pairs retain both charge and mass eigenstate, including
mixed stau eigenstates. Unsupported roots, missing or extra roots, same-sign pairs and
inconsistent stable-bino populations remain explicit unresolved categories. Malformed
ancestry graphs, references or impossible event joins fail the complete diagnostic.

Every signal and control channel retains counts, signed `sumw`, `sumw2`, original-exposure
yields, category contributions and signed-pair contributions. The unsplit channel moments
must match the original metadata and patch, including the declared MC constraint. A selected
unresolved topology remains in the channel denominator and makes its origin attribution
unresolved. There is no `2/3` rescaling, selected-subset denominator or replacement of the
sample's tagged cross section by an inclusive four-state cross section. For a six-state
sample, contributions retain its original `sigma6 * K / N6` basis.

Raw reconstructed lepton references additionally identify overlapping event subsets with
stored stau-to-tau ancestry, other tau ancestry or ambiguous slepton ancestry. These describe
selected events containing such raw reconstructed leptons. The native trace does not retain
the individual selected lepton's Particle UID, so these subsets do **not** assign an origin
to the particular native-selected lepton. Stored mother endpoints can omit further mothers;
the result remains conditional on the stored ancestry.

LHE production is inventoried separately. Exact particle-row cardinality and mother-graph
checks prevent undeclared particles from disappearing. Recognized `rwgt/wgt` and compact
`weights` XML is validated and recorded as auxiliary metadata, without applying its values
or creating theory nuisances. Unsupported metadata fails explicitly. LHE and Delphes entry
numbers are not treated as an event-by-event identity.

`sqrt(sumw2)` is the conditional Poissonized independent-event MC prescription, not an exact
fixed-N variance. Subset-to-total ratios retain the shared-event covariance
`Cov(subset,total) = sumw2(subset)`. Empty or complete subsets and exact signed cancellation
retain unresolved precision. Generator integration uncertainty, K-factor uncertainty,
detector response, tau efficiency and statistical coverage remain separate.

## Retained four-state positive control

The actual 20,000-event `nominal_m150_dm10_20k` anchor was read with the existing Rivet
environment: Python 3.14.5, uproot 5.7.4 and awkward 2.9.0. No environment, frozen runtime,
production card, original event file or active binary was changed.

The final diagnostic reports 20,000 four-state events, zero stau events and zero unresolved
topologies. All 38 channel moments and their patch yields/MC errors close. The original 357
signal-region selections and 85 control-region selections remain unchanged. The signal
population contains 204 high and 153 low selections.

| Signed production pair | LHE count | Delphes count |
|---|---:|---:|
| `-1000011,1000011` | 6,990 | 6,990 |
| `-2000011,2000011` | 3,011 | 3,011 |
| `-1000013,1000013` | 7,029 | 7,029 |
| `-2000013,2000013` | 2,970 | 2,970 |

These are matching population inventories, not an asserted event-by-event LHE/Delphes join.
The all-event ROOT weight sum is `0.04078872279933421 pb`; its retained sum of squared weights
is `8.318599538004632e-08 pb^2`. The original normalization receipt gives
`0.040788724879999995 pb`. The small ROOT representation difference is preserved within the
declared reconciliation tolerance, rather than rebasing the event weights.

Local records are under `local-runs/rrr-closure/physics-review/sixstate-origin/`:

- `anchor20k-v1/failure.json` and its log retain the initial overly strict one-lepton/track
  flavour check. The repair was confined to this new diagnostic; the native producer did
  not change.
- `anchor20k-v2/` retains the first successful full ROOT traversal.
- `anchor20k-v3/` retains the successful traversal after the independent LHE parser repair.
  Its `origin.json` SHA-256 is
  `0b4a9dec769e8bbaa114cbe9feba1f0e7e2395f20b676d96f83d8283feff574e`.
- `v2-v3-parity.json` confirms identical decompressed event records and identical central
  category, pair, channel and reconstructed-origin fields between those successful runs.

The v3 output rechecks 151 source/receipt/reader file pins. It does not establish public raw
event custody: the large original ROOT and LHE artifacts remain local, outside the curated
public waypoint bundle.

## Verification and review

The locked Python 3.12 environment passed all 59 focused tests from outside the checkout.
The independent IO reviewer also reran all 59, reproduced the original surplus-particle and
truncated-header findings, verified their repairs, and independently compared all 20,000
retained v2/v3 event records. A complementary reviewer checked eight independent
partition/covariance/boundary controls and 12 selected tests. Both bounded reviews closed
without an additional material finding. They did not independently repeat the full ROOT
traversal or claim tau efficiency, acceptance, likelihood or coverage certification.

Review records are local under `physics-review/origin-independent/` and
`physics-review/sixstate-origin-moment-review/`, within the same `local-runs/rrr-closure/`
prefix. The ordinary malformed LHE fixtures and numerical probes are retained there.

The exact final retained replay command, run from the repository root, was:

```sh
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 \
stages/01-event-generation/build/tools/miniforge3/envs/rivet/bin/python -B \
  -m ravel.physics.slepton_origin \
  --plan trial-runs/2026-09-05_SUSY-2018-16_rrr-closure/runs/nominal_m150_dm10_20k/inputs/native_execution_plan.json \
  --plan-sha256 9f308e89d3a5c308a07793d82e4326752bd7a208608ac64d21ce6c090e28d36a \
  --out local-runs/rrr-closure/physics-review/sixstate-origin/anchor20k-v3 \
  > local-runs/rrr-closure/physics-review/sixstate-origin/anchor20k-v3.log 2>&1
```

The output directory must be new, so another replay must choose a new suffix. A successful
run writes `origin.json` and `events.jsonl.gz`; a failed diagnostic retains `failure.json`
without advertising complete population accounting. The command above requires the
original retained source workspace and cannot be reproduced from public source alone.

At implementation review closure, the separately executing six-state sample had not been
diagnosed. The subsequent result is recorded below. The public waypoint evidence was not changed.

## Subsequent completed six-state diagnostic

After the parent recorded complete twelve-stage execution and all six resolved numerical
limits, the unchanged reviewed helper read `nominal_m150_dm10_6state_20k`. The saved plan
SHA-256 is `cb6d2dad36e866dd6b71bc973b8a1344376b1a8ecec6bae37a6a338fa890c7e7`.
The new output is `sixstate-origin/sixstate20k-v1/` under the local physics-review prefix.
Its `origin.json` SHA-256 is
`56d77b8fbb973a74d15026a9c7d15ebca973bb17af47c11be85758c7785546ca`.
No source-package, frozen-runtime, binary or original-event changes were made for this run.

All 20,000 events join successfully: 13,372 are non-stau production and 6,628 contain staus,
with zero unresolved production topologies. All 38 channel moments close. The independent
LHE and Delphes inventories agree for eight signed pairs, including 318 events with
`-2000015,1000015` and 305 with `-1000015,2000015`. These are population comparisons; no
LHE-to-Delphes event identity is inferred.

The original six-state LO tagged rate is `0.05175315 pb`, with the fixed K=1.18 applied once
to give `0.061068717 pb`. Its original weights and 20,000-event denominator are preserved.
The 232 SR selections comprise 143 high and 89 low events. Only two are stau-production
events, both high; the 69 CR selections contain one stau-production event in the low top
control region. No low-SR stau event was selected, so its finite-MC precision remains
unresolved. The non-stau and stau contributions are not rescaled to either sample's total.

At 139/fb, the six-state total-SR yield is 98.4672, compared with 101.2029 in the four-state
control. The independent-stream ratio is 0.97297 ± 0.08205 from conditional Poissonized
own-MC moments. The six-state sample's non-stau component gives a ratio of
0.96458 ± 0.08156 relative to the four-state total. Staus contribute a yield of 0.8489 from
two SR events and 0.4244 from one CR event. These sparse counts and conditional errors do
not establish tau calibration, full sample equivalence or a calibrated confidence interval.
Generator integration uncertainty and the common K assumption remain separate.

The source-pinned comparison script is local `sixstate-origin/compare_origins.py`.
`four-six-comparison-v1/` retains `comparison.json`, all 38 rows in `channels.csv`, and a
README with exact commands, recipe checks, pair counts and uncertainty scope. Configuration
and parameter-card checks pass; the declared process and independent seeds change, while
the checked remaining run/shower/detector settings agree. Raw reconstructed ancestry
overlays still do not identify the individual native-selected lepton. This additional
diagnostic performed no event generation or fit, and does not update physics certification.
