# Observed events to a complete SFitter scan

`sfitter-observed-events` connects complete original LHE records and analysis-bin observations to the existing `sfitter-scan-extraction` operation. It exports the complete ordered SM, single, mixed and held-out point population, signed original weight census, rates and cross-point/bin covariance. It does not run a generator, shower, detector, optimizer or fit.

There is a concrete producer in the existing `analysis-ir` workflow. Its optional `sfitter_observation` input names a pinned producer configuration. The producer consumes the actual `evaluate_program` decisions, retains the original replay bundle, and emits one observation row for every original event, including zero weights, vetoes and no-fill events. The bridge re-runs the existing detached replay checker and matches every object-content identity to an explicitly supplied original LHE ordinal/content hash. It preserves overlapping regions; it does not convert them into exclusive regions.

This establishes a source-object analysis connection. It does not establish a shower or detector response, ordinary execution acceptance, native all-weight transport, or statistical/physical applicability. The original object-to-LHE join and response invariance remain source-bound premises. A generic `supplied_observations` branch also exists, and reports that its decisions were not replayed. A pinned file named `execution_evidence` alone receives no execution credit.

## Acquisition configuration

The optional analysis-IR producer configuration has exactly these fields:

```json
{
  "schema_version": 1,
  "generator": {
    "lhe": {"path": "original.lhe", "sha256": "<literal SHA256>"},
    "events": 5,
    "weight_groups": [{"name": "scan", "combine": "none", "ids": ["point_0", "point_1"]}],
    "maximum_decoded_bytes": 1048576
  },
  "original_join": {"path": "original-object-join.json", "sha256": "<literal SHA256>"},
  "bins": {"path": "bins.json", "sha256": "<literal SHA256>"},
  "region_bins": ["first_region", "second_region"],
  "sources": [{"path": "response-premise.txt", "sha256": "<literal SHA256>"}],
  "response_weight_policy": {
    "kind": "weight_invariant_same_objects",
    "source": {"path": "response-premise.txt", "sha256": "<literal SHA256>"},
    "description": "Explicit premise that these source-object region decisions apply to every original reweight"
  }
}
```

The original join contains `schema_version`, `lhe_sha256`, `records`, and `sources`. Every record contains `event_id`, `ordinal`, `canonical_event_sha256`, and `reconstructed_event_sha256`. The last hash is the existing AgentGraph canonical digest of the complete original object record. Join source dependencies are traversed before ordinary planning and are checked again during emission. A file-order coincidence or matching event ID is insufficient.

The producer emits `sfitter-bin-observations.jsonl` and `sfitter-observation-producer.json`. The JSONL header declares the exact LHE hash, analysis source hash, full ordered bins and original weight IDs. Each row contains the original ordinal/content hash, every original weight token, `vetoed`, and all fill entries (`bin_index`, one fraction per original weight). The connected IR producer uses its actual region decisions to emit zero or unit fractions. The generic callable `ObservationWriter` supports an exporter supplying actual fractions; it authenticates emitted bytes but does not authenticate a native caller.

IR itself supports at most 16 consumed streams. Using one object/mask population with more LHE reweights is admitted only under the explicit same-object invariant-response premise. All original reweights still enter the bridge's complete moments; they are never trimmed to the IR subset. Point-dependent response without complete separately supported analysis bundles is refused.

## Bridge request and denominator law

The bridge request contains `schema_version`, `id`, `extractor_template`, `cohorts`, `relationships`, and `normalization`.

- `extractor_template` pins an existing extraction request without its `rates` field. Its actual workflow, full scan definition, EFT conventions, process/order, bins and coupling evidence determine the required population. This bridge does not invent a scan design or a coefficient convention.
- Every cohort declares `id`, `point_ids`, `generator`, `analysis`, `grouping`, and `sampling`. `generator` extends the acquisition configuration with nonempty `sources`. `analysis` contains trace/source/execution-evidence/bin-definition pins and `producer_kind` (`analysis_ir_complete_decisions` or `supplied_observations`). A grouping document contains every original ordinal's `group_ids`, the exact LHE hash, a description, and source pins. Noncontiguous group reappearance is refused.
- Relationships explicitly declare one shared reweight cohort or independent cohorts and bind a source premise. Distinct files, held-out roles and weight names do not prove independence. Reuse of identical raw LHE bytes as independent cohorts is refused. The output always reports `independence_proven: false`.
- Normalization rows follow the full original point order. They contain `point_id`, a fixed per-bin `scale`, `scale_uncertainty: conditional_fixed`, a denominator rule, description and source pin. The denominator is either literal nonzero `fixed_external` values or `observed_weight_sum` with an independently selected original weight ID. A numerator reweight does not imply use of its own weight sum. Mixed fixed/random denominator modes and uncertain scale covariance need a separately typed extension and currently refuse.

For `fixed_N_IID_groups`, the operation uses the existing centered empirical covariance of a group mean, multiplied by N² to obtain the covariance of raw sums. At least two groups are required. For `poissonized_independent_groups`, it uses the existing uncentered group Gram matrix. Sub-events are summed inside their declared group before either estimator takes products. Sampling and grouping assumptions are not inferred from LHE metadata.

Random denominators are included in the complete covariance after **all** point/bin numerator coordinates, including every cross block. A shared denominator is repeated with its full singular cross-covariance. The existing extractor subsequently applies the first-order map `z = K Y/(D Δ)`, with `J_Y = K/(D Δ)` and `J_D = -K Y/(D² Δ)`. K remains conditional/fixed. The LHE header's cross-section error is not a replacement for missing joint K/Y/D covariance. Same-event held-out points remain correlated with training points.

## Numeric and resource boundaries

Every original weight is parsed by the existing complete LHE reader. The bridge compares original Decimal values and signed-zero signs. Population sign counts come from the original Decimal tokens, and `sumw`/`sumw2` remain the parser's 80-digit transport diagnostics. Covariance arithmetic uses admitted finite binary64 values. Nonzero Decimal values that convert to binary64 zero refuse instead of being relabeled as zero events. This does not establish arbitrary-precision covariance or a general error enclosure for the centered branch.

The complete population is bounded by 64 cohorts, 20,000 original events per cohort, 256 numerator coordinates, 512 numerator-plus-denominator coordinates, and two million group-cell products. Source admission is bounded by 1,024 complete files and 128 MiB aggregate, with 8 MiB per file at the downstream extractor seam. Larger LHE inputs may be read by the streaming scanner, but this delivery refuses them if the downstream full-source capture cannot consume them. Graph's existing 128-input limit remains unchanged; an over-limit Graph refuses without dropping sources. Ordinary scientific planning captures the larger declared input population.

The existing extractor can refuse near-null propagated coefficient/held-out covariance because of its retained numerical checks. This implementation does not relax those checks. Original source files, output files and complete replay membership are checked through the final boundary. Every generated output is committed against the intended serialized bytes immediately and checked again at the end; changed bytes are never recaptured as the original commitment.

## Reachable operations

```text
ravel sfitter-observed-events --request <pinned request JSON> --output <fresh directory>
ravel plan --rundir <fresh ordinary run> --spec <schema2 spec>
```

For ordinary studies, use mode `sfitter-observed-events`, task `{"request": "<request path>"}`, one attempt, zero redo, at most 60 seconds, and the single delivery scope `sfitter_observed_event_rate_delivery`. Existing CHECK-IN1 and independent role machinery still apply. Graph tool action `sfitter-observed-events` reaches the same materializer through the existing Host. The CLI materializer itself confers no science approval, native permission or parent-goal acceptance.

The four outputs are `observed-scan-rates.json`, `scan-extraction-request.json`, `event-rate-diagnostics.json`, and `event-rate-receipt.json`. The extraction request reaches the existing extractor and its later SFitter card/fit handoffs; this bridge adds no optimizer or native fit. Complete fitted-coefficient/model, detector, EFT-validity and calibration claims remain separate.

## Producer ending custody and bounded input acquisition

The optional analysis-IR producer commits the exact intended serialized replay bytes before each write, authenticates the original observation trace and producer receipt, and closes the complete emitted file/directory population at return. It also rechecks already committed outputs and original inputs on a failed or exceptional path. Partial/corrupted outputs are retained; a secondary custody refusal preserves an earlier scientific refusal in its exception chain rather than repairing or reclassifying it. This is finite file observation, not a hermetic adversarial-filesystem proof.

The existing scan extractor retains its per-file 8 MiB ceiling, complete source census up to 1,024 entries, and separate Graph input ceiling. A call-local capture now reserves the remaining 128 MiB unique retained source-payload budget before opening each new source. It authenticates path/descriptor identity before and after a read bounded by that remaining capacity; duplicate references do not spend that retained budget twice. The aggregate is a source-payload admission bound, not a measured RSS limit for parsed documents, matrices or replay outputs. No covariance, sampling, normalization, coefficient, physical-domain or acceptance law changes.
