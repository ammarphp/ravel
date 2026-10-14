# Returned scans in the SFitter domain review

`ravel.workflow.sfitter_scan_review` connects the supplied signed-scan extractor
to the existing `sfitter_review_protocol` and its ordinary judgment roles. It
recomputes the complete source extraction and checks the actual delivered
coefficient handoff before constructing any domain evidence. It does not launch
scans, native fits, models, roles, or a second review journal.

The closed request has `schema_version: 1`, `id`, pins named
`extraction_request`, `extraction_receipt`, and `regime`, plus `criteria`,
`check_ids`, and `claim_scope`. Pins contain exactly `path` and `sha256`.
`criteria` contains `baseline` and `polynomial`; each maps every observable ID
to `{absolute, relative, justification}`. A justification is a located source
`{artifact: <pin>, location: <JSON pointer>}`. Absolute bands have the actual
comparison's units, which differ between a raw SM rate and a normalized shape.
They are declared numerical criteria, not calibrated significance thresholds.
`check_ids` must be the original policy's scientific check IDs when roles are
prepared. Regime definitions retain the existing complete observable census.

```python
from ravel.workflow import sfitter_scan_review, sfitter_review_protocol

prepared = sfitter_scan_review.prepare(request_pin, base_dir, output_directory)
binding = sfitter_review_protocol.prepare_role(
    actual_rundir, prepared['protocol_request'], role_output_directory,
    role='critic', actor_id=registered_actor, model=assigned_model,
    reasoning_effort=assigned_effort,
    max_output_tokens=declared_output_tokens, max_wall_seconds=declared_seconds,
)
```

The existing protocol checks the registered scope and original scientific
checks. Its `consume` and `rework` operate on the original judgment journal and
owning phase. A prepared file grants neither a vote nor retry or execution
authority. A passing coefficient concern cannot replace the other concerns
needed by the full phase continuation.

For each observable, every returned `total` or `sm` point becomes a native
polynomial probe. Shape central values use the same exact width-weighted rate
integral as the native engine. The polynomial uses the actual handed-off SM
template and modifiers; its original mixed terms occur once. Independent SM
reference points are compared separately to that template. Their origin and
independence remain supplied premises.

Isolated `linear` and `quadratic` points are not total cross sections. The
complete coverage ledger locates them in the original extraction's residual,
weight and covariance census. It preserves their entries without pretending
they have a physical normalized shape. A nonpositive total integral produces
explicit unresolved evidence; no reference shape is invented, and the material
coefficient concern remains inconclusive. Nonfinite arithmetic refuses.

Shape covariance uses the declared first-order Jacobian
`delta_ij / I - rate_i * width_j / I**2`. The full supplied cross-point and
cross-bin covariance follows that map. Absolute isolated-component rows keep
their original coordinates. This is a delta-method uncertainty projection, not
an exact finite-sample law; MC errors do not alter the declared bands or become
native Gaussian/RFit nuisances. The separate SM template is treated as fixed;
its absent covariance is not inferred.

`prepare` writes the projection, comparison data, derived regime provenance,
existing protocol request/report, and preparation receipt. Every original
dependency is included in the protocol's retained source census, including the
complete source-defined scan roster. Acceptance definitions are unchanged.
Known output bytes and complete membership are checked after final callbacks.
`graph(request, base_dir, request_pin)` exposes the same projection through the
ordinary `sfitter-scan-review` Host tool, with complete explicit input pins and
blinded-role refusal. These source controls are not actual scan or fit efficacy.
