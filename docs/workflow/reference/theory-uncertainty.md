# Theory uncertainty from supplied predictions

Use `ravel.physics.sm.theory_uncertainty` to assemble `prediction_bundle.v1`
from supplied predictions. Study identity, binning, member population and output
filename/format come from the caller. The operation generates no events and
launches no native program.

The adapter exposes `validate(task)`, `inputs(task, base)` and
`run(task, base, output)`. Its task contains `input` (the JSON configuration path)
and `output` (`filename` and `format`, either `json` or `json-compact`). The
configuration contains `bundle` and `correlation_model`; the schema is
`src/ravel/data/sm/schema/prediction-bundle.schema.json`.

Supply the complete member table in `bundle.members`, or leave that list empty
and supply one of these sources:

- `member_table`: `generator`, `streams` (each with `id` and `values`) and retained
  `headers` when the source uses numeric identifiers.
- `yoda`: a pinned `input` (`path` and `sha256`), `observable_path`, `generator`,
  `nominal_weight`, and `quantity` (`integral`, `density` or `estimate`). A positive
  common `factor` declares conversion of every stream. Compressed text is accepted.

The pure `from_member_table` and `from_yoda` interfaces perform the same assembly.
YODA 2 text uses the existing GPL-free reader. The selected nominal is the
unsuffixed observable; every bracket-suffix stream for that observable is retained.
Histograms contain integrated sumW; `density` divides by bin width. Estimates
contain final values. Binning and types must agree across streams. Flow bins are
excluded explicitly. Other observables remain outside the caller's selection.

For PDF streams, `nominal_pdf_member: 0` explicitly identifies the unsuffixed
central as PDF member zero. `member_metadata` can supply named PDF member indices,
matching PDF couplings, correction roles or ratio semantics; it must name actual
streams. Member indices are never inferred from numeric LHA identifiers.

Generator maps live in `src/ravel/data/sm/weight-names/`. They describe supported
grammars; installed-generator source qualification is a separate job. Numeric
MG headers preserve `id`, `attributes`, `description` and `canonical_header_xml`
from the existing weight census. Combined scale/PDF variations, unknown names
and uninterpreted coupling factors stay `unclassified`, are listed in the bundle
and force `complete: false`.

## Prescriptions

`band(bundle, pdf_result=...)` returns nonnegative down/up errors by class and
their declared independent-class quadrature. Central values are retained.

| Class | Required prescription and semantics |
|---|---|
| Scale | `7pt-envelope` excludes the two opposite pairs; `9pt-envelope` retains them; `independent-muR-muF` combines axis envelopes in quadrature. Ratios are 0.5, 1 and 2. A repeated nominal point can be omitted. Missing points, duplicates and mixed dynamical-scale choices refuse. |
| PDF | `lhapdf-error-type` with source-bound `.info` metadata and all members. An incompatible ErrorType refuses. The isolated library handles Hessian, symmetric Hessian or replicas and confidence rescaling. |
| α_s | `pdf-set-members` or `plus-minus-delta` with `delta`, two bracketing predictions, each member's `alpha_s_mz` and equal `pdf_alpha_s_mz`. Error is half their difference. A delta without predictions is insufficient. |
| EW | `multiplicative`, `additive` or `difference-as-uncertainty`. Supply both absolute predictions with those roles. The first two report deviation of the selected prediction from central and retain the comparison; the third reports their absolute difference. |
| NP | `ratio-envelope`, positive ratio members and explicit `np_already_applied: false`. Ratio deviations around one become central-value errors. Already-applied or undeclared correction status refuses. |
| Shower, MPI, tune, mass, MC statistics | An explicit `envelope` over supplied absolute predictions. No statistical sampling law is inferred. |

`check:sm.alphas_consistent` compares matrix-element and PDF α_s. Missing PDF
coupling metadata is `unknown`; a mismatch is `failed`. Both prevent completeness.
`read_pdf_info(text)` retains full text and digest. A composite ErrorType ending
in `+as` needs explicit PDF prescription `components: [pdf, alphas]` and refuses
separate α_s members or prescriptions. Its library band is a declared combined
group; covariance records `component_groups` so consumers must not count it twice.

Declare normalization to a different-order cross section with
`normalization_order` and `normalization_declaration`: `shape_order`,
`cross_section_order`, positive common `factor`,
`applied_to: all-central-and-members`, `source` and `definition`. These describe
values already normalized together; the operation applies no second factor.

## Isolated worker and covariance

`pdf_worker_request(bundle)` returns JSON. Execute
`src/ravel/physics/sm/lhapdf_worker.py --request PATH --output PATH` under the
existing `rivet` environment Python through ordinary method-decision admission
and supervised execution. The host never imports the GPL tool modules. The
worker imports LHAPDF only in its executable entry point, verifies installed
`.info` bytes and loaded metadata, and delegates PDF math to
`PDFSet.uncertainty()` at the requested confidence level.

Pass its JSON to the pure interfaces, or pin it as `pdf_result` in the adapter
configuration. Set, ordered member IDs, metadata digest, confidence level and
complete request digest must agree. Replica ensemble central values remain
separate from supplied member zero. This transport centers the library's error
magnitudes on the supplied prediction; it retains the ensemble mean separately.

`theory_covariance(bundle, model, pdf_result=...)` requires one entry for every
classified uncertainty class: `fully-correlated`, `uncorrelated`, or
`{kind: matrix, values: ...}` with a symmetric positive-semidefinite correlation
matrix and unit diagonal. The larger down/up error defines each marginal width.
The model is retained verbatim. Fully correlated classes give outer products;
uncorrelated classes give diagonal matrices. Classes combine independently.
These are declared second-moment proxies, not Gaussian likelihoods or coverage
proofs derived from scale envelopes.

`assemble` attaches bands, covariance, computed checks, unclassified streams and
completeness. Every result retains `physics_validated: false`. Normalization
validity, prescription applicability and source qualification need scientific
review. The common workflow does not dispatch this operation yet: the registration
fragment `src/ravel/data/sm/registration/theory-uncertainty.json` lists the shared
registry and resource declarations that remain to be applied.
