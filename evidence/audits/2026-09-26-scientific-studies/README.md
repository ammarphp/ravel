# Supplied-data scientific studies: implementation and controls

The supplied-data study types now have executable components behind
`ravel plan`, `approve`, `run` and `status`. The new work separates delivery of a
specified calculation from detector validation, reference closure and expert
review. It does **not** establish RRR reproduction or successful execution of all
633 catalogue entries.

[Operating guide](../../../docs/workflow/reference/scientific-studies.md) ·
[Quantity and measurement schemas](../../../docs/reference/quantities-and-measurements.md) ·
[Domain schemas](../../../docs/reference/domain-adapters.md) ·
[Control population](controls.json) · [Offline verifier](verify.py)

## What is implemented

| Sequence | Executable behavior | Evidence boundary |
|---|---|---|
| Frozen-event Rivet | Compile the pinned routine unchanged, bind runtime/options/assets, stream a HepMC2/3 census, execute all supplied events, export declared YODA quantities | Six ATLAS/CMS routine controls on twelve artificial event records; no generated physical sample |
| Reconstructed objects | Explicit object bits and thresholds, ordered overlap removal, complete event-decision comparisons, signed/grouped yields, overlap and covariance; mapped pyhf signal and control-region injection | Analytic object/region controls; no new detector calibration or published cutflow closure |
| Upstream SimpleAnalysis | Supplied binary/build attestation, pinned source/assets, slim ROOT census and per-event CSV/ROOT reconciliation | Real ROOT I/O tests and exact pinned protocol inspection; **no upstream SimpleAnalysis binary executed** locally |
| Quantity transport | Integrated/differential and absolute/normalized ND bins, all weight streams, signed/correlated subevents, full joint covariance, flow and shard merging | Independent analytic moment, normalization and merge checks; supplied fill/weight meaning remains an assumption |
| Measurement inference | Supplied SM/signal/data, covariance and overlap policy, normalized-shape constraints, Gaussian GOF, actual Spey observed and five expected CLs roots | Analytic Gaussian controls and bounded failures; not a full experimental likelihood or toy-calibrated inference |
| Model and EFT | Non-executing UFO structure/order/parameter checks; supplied benchmark comparisons; quadratic EFT basis including interference and independent controls | No FeynRules derivation, generator matrix-element calculation, loop accuracy or model validation inferred |
| Classifier | Actual one-thread ONNX Runtime inference with explicit features, units, preprocessing, threshold and reference outputs | No classifier training, detector-feature validation or experimental classifier equivalence inferred |
| Topology and efficiency | Exact map nodes, signed/grouped yields and separate map covariance; alternative hypotheses never summed | No interpolation/extrapolation or implicit detector response; map validity must be established separately |
| LLP | Boosted cylindrical decay probabilities and proper-length reweighting including right censoring | No displaced reconstruction or missing efficiency supplied automatically |
| Nuclear, forward, neutrino | Explicit per-event nuclear normalization; neutral straight-line geometry; integrated flux × cross section × targets | Elementary supplied-model operations, not full nuclear simulation, beam optics or neutrino analysis support |

The source implementation is original. Upstream Rivet routines are compiled from
an external pinned checkout without copying their code into this repository.

## Actual execution and independent checks

The final population contains **21 controls: 18 successful deliveries and three
expected failures**. Fifteen are analytic supplied-data workflows, including a
failed EFT independent control and a CLs scan deliberately too short to resolve
its crossings. Six compile and execute unmodified upstream Rivet analyses. Each
control goes through a concrete CHECK-IN 1, recorded scripted assent, one bounded
supervised attempt and explicit completion/failure state. Scripted assent requires
explicit authorization and is never counted as expert review.

Rivet controls use the catalogue's source revision
`74816bd4cf29a9d71447f8c122887d498d3dea3a` (4.1.4 source), the installed **Rivet
4.1.3 / YODA 2.1.3** runtime and one compilation worker. These identities are
separate; compatibility is demonstrated only for the selected controls.

| Routine | Control | Result |
|---|---|---|
| ATLAS_2013_I1234228 | Drell–Yan, signed correlated subevents and two weight streams | Delivered; two records form one independent group, nominal sumw/sumw2 = 1/1, variation = 2/4 |
| CMS_2018_I1711625 | Drell–Yan, independent events | Delivered |
| ATLAS_2016_I1494075 | ZZ leptonic selection and explicit branching-ratio normalization | Delivered |
| CMS_2012_I1298807 | Normalized ZZ distribution | Retained normalization failure |
| ATLAS_2010_I871366 | Inclusive jets and rapidity-width normalization | Delivered |
| CMS_2016_I1459051 | Inclusive jets and rapidity-width normalization | Delivered |

The five delivered Rivet quantities are independently checked against the
synthetic exposure and the routine's declared normalization: respectively
1 pb, 1 pb, `1000 / ((3.3632 + 3.3662)/100)^2` fb, `2/(2 × 0.3)` pb and
`2/(2 × 0.5)` pb after integration over the exported momentum bins. The latter
jet quantities remain differential in rapidity. The values are **analytic fixture
expectations**, not measured cross sections or collider predictions.

The unmodified CMS ZZ routine explicitly rescales bins by their widths and
accumulates another volume-divided area before normalization. Its exported
finite-bin integral fails the requested unit-area contract. The failed YODA,
export error and worker log remain in
[the CMS ZZ control](controls/CMS_2012_I1298807/export.log). Ravel does not repair
this by changing the routine or renormalizing the visualization. This is a
specific source/runtime control result, not a claim about every release of the
analysis or the experimental result. See the
[pinned upstream source](https://gitlab.com/hepcedar/rivet/-/blob/74816bd4cf29a9d71447f8c122887d498d3dea3a/analyses/pluginCMS/CMS_2012_I1298807.cc).

## Scientific bugs found and repaired

- Rivet 4 finalizes histogram densities as YODA estimates. Reading them as counts
  and dividing by bin width again changes shape and normalization. The adapter
  now requires the matching RAW histogram, checks **all** bin dimensions/edges,
  and applies the declared integrated/differential convention exactly once.
- A normalized quantity could be labelled with a cross-section unit. Normalized
  output now requires dimensionless integrated or inverse-axis density units.
- A sumw-only exposure check could miss a lost cancelling `+w, −w` pair. Exact
  global counters now reconcile independent groups and second moments for every
  declared weight stream.
- Missing dilepton/dijet/leading-object observables could pass a cut through a
  numeric zero sentinel. Undefined observables cannot pass selections now.
- A b-jet cut without a b-tag definition, correlated MC bins injected as independent
  errors, and a zero-yield bin with nonzero variance could be admitted incorrectly.
  Those cases require the missing definition or a suitable statistical model.
- SimpleAnalysis event identifiers could be truncated by `int()`. Fractional,
  nonfinite and boolean identifiers are rejected before event joins.
- Approval semantics are tied to the exact proposal and check-in. Changed inputs,
  runtime, implementation, budgets, stale outputs and unsupervised entry fail.
  A failed attempt cannot be silently restarted.

The review also caught a misspelled lifetime field in an early fixture. Its
worker refused the input; the corrected fixture passes. Earlier failed attempts
are not included. The published population contains the
final declared controls and deliberately failed scientific cases, not a selected
success-only population.

## Figures and validation

![Supplied correlated measurement with explicit data errors and ratio](controls/correlated-measurement/measurement.png)

This synthetic example displays supplied measurement errors from its covariance,
SM and SM-plus-signal values and their ratios. Prediction uncertainty is shown
only when supplied; this example supplies none. Undefined ratios at zero SM stay
gaps. Actual bin coordinates and widths are retained. No smooth interpolation,
plot-time normalization, clipped negative yield or experimental luminosity is
invented. These diagnostics pass the house layout checks and produce PDF plus
220 dpi PNG. They are not paper-target figure reproductions.

The final focused suite checks quantity/domain/inference, reconstructed and ROOT
transport, lifecycle, plots and catalogue regression behavior. Native YODA tests
separately cover real finalized objects, malformed RAW/final geometry and units.
The verification record below is updated from actual test logs, and CI exercises
Spey, ONNX Runtime and ROOT I/O rather than silently skipping those backends.

See [validation record](validation.json), [environment changes](changes/environment-changes.md)
and [input changes](changes/data-and-card-changes.md). Run the portable evidence check:

```bash
python evidence/audits/2026-09-26-scientific-studies/verify.py
```

This verifies curated bytes, the complete control population, explicit failure
states, numerical normalization and grouped-weight counters. It does not rerun
Rivet or independently validate physics. Absolute operator paths are redacted;
original plan, approval, attempt and result hashes remain recorded. Curated
result receipts explicitly identify their path-only transformation.

## Open scientific limitations

Shared-event and published-reference closure of ordinary dilepton/jets selections
is not established, and the response and normalization diagnoses are not
transferred to RRR. Native SimpleAnalysis compilation and execution
still need a compatible AnalysisBase installation. Public source availability
alone does not establish that every routine, external model or classifier builds.

The RRR low-delta-m shape, acceptance definition, generator-cut sensitivity and
full mass-plane closure remain unresolved. No contour has been tuned to agree
with the paper. These new routes make targeted comparisons possible and reject
several general failure modes, but cannot replace the missing physics evidence.
