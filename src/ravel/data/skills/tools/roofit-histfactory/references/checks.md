# Checks and evidence: roofit-histfactory

The runtime contract chooses the actual ROOT libraries. A handbook version pin
for the legacy Combine group is an availability reference, not authority to
swap the original model's runtime. `native_statistical_construction` prepares
source-bound native work; `statistical_model` implements the separately declared
count model. Neither can replace unknown source terms with invented ones.

Tests execute the exact source-template block, checking a nonuniform template's
full and clipped integrals, no overlap, reversed/zero-width bins and a width
that underflows the native representation. They reject an incomplete constructor
before native execution. Native fit, readback and optimizer witnesses remain
unexecuted by these tests. The use of the internal geometry checker is intentional
and tied to the current source; re-review this block when that source changes.

| Advisory ID | Candidate check | Evidence needed | Current enforcement |
|---|---|---|---|
| RF-A1 | Compare the original and transported native model over source integrals, parameter/nuisance points, categories and optimizer starts; then calibrate the contracted statistic | Complete source, exact runtime, source/native readback, numerical tolerances, failed endpoints and independent repeated-data study | Partial: `structural_witness`, `integration_witness`, `statistical_model.compare_likelihoods` and multi-start fits cover their recorded quantities; they do not supply a general equivalence or coverage proof |

RAVEL references: `src/ravel/physics/native_statistical_construction.py`,
`statistical_construction.py`, `statistical_model.py`, `asimov_sensitivity.py`,
`mc_closure.py` and `src/ravel/validation/statistical_model_witness.py`.
The upstream manual pointers describe the frameworks; RAVEL APIs above come
from these local sources, not an assumed framework converter API.
