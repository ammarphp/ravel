# Transfer checks for reference identity and ATLAS inference

The shared reference-grid repair prevents a validator from silently comparing
different published masses. This audit checks the repair against actual ATLAS
tables and exercises the common statistical engine on two other ATLAS analyses.
It does not certify the RRR signal model or establish end-to-end reproduction.

## Fresh reference checks

The old acceptance readers used the first node **strictly less than 1 GeV** away
on both axes. In the original row order, this selects the wrong reference at
**13 of 75 points in each of six maps**, at splittings 0.3, 0.5 and 0.7 GeV.
Reversing the rows also produces 13 incorrect selections per map, with different
selected nodes. The public [result](reference-grid.json) retains every mismatch.
A preliminary diagnostic used `<= 1` and incorrectly counted 23 per map; the
record here uses the released implementation's strict `< 1` condition.

Both production validators now share a 1e-6 GeV numerical tolerance, reject
duplicate or ambiguous coordinates and refuse interpolation across different
fixed masses. Lookup labels preserve round-trip coordinate precision, including
when checking separate acceptance and efficiency nodes. These rules protect
compressed and fractional grids generally. They do not change physical masses,
reference values or simulated yields.

The fresh check makes **1,350 successful queries**: 450 original map nodes and
225 acceptance-times-efficiency products, each in original and reversed order.
The product checks use the full production adapter and the published acceptance
scale of 10^-3. Unit regressions exercise both validator entry points, interpolation,
nearby fractional coordinates, duplicates and deliberately ambiguous requests.

The six [reference tables](reference/) are unchanged copies of ATLAS Figure 32a–f,
[HEPData 91374 v5, tables 57–62](https://doi.org/10.17182/hepdata.91374.v5/t57),
from [ATLAS SUSY-2018-16](https://arxiv.org/abs/1911.12606).
ATLAS Collaboration, CC BY 4.0. The retained submission metadata is restricted
to these six entries; [provenance](reference/provenance.json) records the original
submission hash. Their truth mT2 range is [100,140] GeV. They are not unrestricted
detector-efficiency maps. This lookup defect does **not** explain the 5 GeV RRR
discrepancy or change the historical full-plane residuals.

## Fresh controls from two other ATLAS analyses

| Control | Result | What this establishes |
|---|---|---|
| ATLAS 2016 jets + missing energy, 2jl | S95 observed 43.6513 vs 44; median expected 54.8857 vs 54 | About -0.79%/+1.64% recovery from the published fitted-background counting approximation, with all six roots resolved |
| ATLAS SUSY-2018-06, released ERJR 300/100 workspace | Free-fit twice-NLL 271.78623, mu-hat 0.24502 | Recovery of the known good minimum instead of the historical false-success solution near 302.52 |

The two controls ran sequentially in **2.92 seconds** with one math thread.
Their [complete numerical record](atlas-controls.json) binds the engine, fixtures
and benchmark registry. The first uses n=263, b=283, db=24 and s=1 event, so the POI
is directly an event limit. It is not the experiment's full correlated likelihood.
The second deliberately reruns only the free fit, not a full six-root campaign.
Sources: [2016 ATLAS paper, Table 6](https://arxiv.org/abs/1605.03814),
[three-lepton ATLAS paper](https://arxiv.org/abs/1912.08479),
[released-workspace fixture and prior regression](../../../src/ravel/data/fixtures/susy-2018-06/README.md).

## Reproduce and interpret

From a checkout with replay dependencies, using new output files:

```bash
python benchmarks/check_reference_grid.py --out /tmp/reference-grid-check.json
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python benchmarks/check_atlas_likelihood_controls.py --out /tmp/atlas-controls.json
python scripts/check_fidelity_audits.py
```

[audit.json](audit.json) distinguishes these fresh checks from the **inherited**
root example and nine-case replay in the
[September 6 audit](../2026-09-06-statistical-fidelity/README.md).
The numerical engine is unchanged. The nine-case replay was not rerun with the
new reader, its baselines were not rewritten, and its two missing-YODA failures
remain. Publication checks bind fresh artifacts and source hashes and compare
the inherited fields byte-for-byte as parsed data with their original audit.

The [architectural assessment](../../../docs/research/2026-09-08-fidelity-transfer.md)
sets out the remaining physics work and the scope of each control.
