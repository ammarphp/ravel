# Supplied native cumulant mappings

`native_cumulant` transports complete supplied finalized Scatter2D outputs and
RAW Profile1D operands through the existing `analyze` exporter. It adds no runner,
native import, inference or numerical recomputation. The engine holds no analysis
snapshot or output table mapping; a mapping is always an input. The released CMS
two-particle cumulant/flow routine ships as data in `src/ravel/data/native_cumulants`
(source bundle, reference YODA and `mapping.json`);
`ravel.physics.shipped_assets.cumulant_mapping(native_weight=...)` returns that mapping
with pins to the bundled bytes.

Supply a mapping and construct its complete population:

```python
from ravel.physics.native_cumulant import requests_for
requests = requests_for(supplied_mapping)
task["observables"] = requests
```

The mapping's closed fields are `protocol:"native-cumulant/v1"`, `routine`,
`runtime_version`, `sources`, `outputs`, `profiles`, `native_weight`,
`semantic_notes`, `study`. The existing task must declare the same source routine
and runtime version. Sources are unique `{role, path, sha256}` records, including
exactly one `reference`; all source/writer dependencies must be supplied and pinned.
The supported transport grammar is YODA V3 midpoint-booked Scatter2D/Profile1D.
Other booking or writer laws require source-backed extension and qualification.

Each final output supplies `path`, `operation`, `operands`, `reference_path`,
`axes`, `unit`, `error_policy`, `error_semantics`. Each raw profile supplies a unique
`id`, `path`, `reference_path`. Operand ids must account for the whole supplied RAW
population. Subsamples are explicit profile rows, without a fixed number. The
final and profile reference paths bind their exact geometry to the pinned source
reference file. All outputs are required for every declared weight stream.

`native_weight` is `{native, suffix}`. Names and suffixes remain
supplied/unverified until native weight/RAW reconciliation. Existing original-event
census and normalization checks remain in force. `study` supplies
`{study_id, parameter_grid, datasets, output:{stem, formats}}`; report formats select
JSON and/or Markdown, and filenames follow the supplied stem. Missing a mapping
raises `NativeCumulantError` with `reason="missing_input"`.

The exporter preserves complete native text, object type/path/block commitments,
finite and nonfinite scalar tokens, asymmetric midpoint geometry, native error
magnitudes, underflow, overflow and masked profile rows. It checks exact geometry
serialization against the supported binary64 and scientific writer precisions.
`error_policy` selects `native_magnitudes` or the explicitly justified
`literal_zero` error convention. A serialized zero never establishes physical
zero uncertainty. Interpretation notes come from the selected source package.

No width transform, cross-section scaling, covariance from errors, reference-bin
recoverability, ordinary profile variance or independent-group law is inferred.
All declared source and output bytes are rechecked at the end. Complete mapping
transport and synthetic controls are distinct from native runtime, error-convention,
normalization, observer and physics qualification. Native work uses the existing
method-decision admission, approval and supervised launch workflow.
