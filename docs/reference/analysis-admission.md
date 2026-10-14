# Open analysis admission

`ravel.workflow.analysis_admission` assesses an explicit analysis specification
without executing a compiler, routine or reviewer. Unknown analysis names are
permitted. Requirements follow the requested task, physical target and exact
source-bound output basis. The report is an evidence census and numerical
comparison, not an acceptance certificate or permission to execute.

```bash
python -m ravel.workflow.analysis_admission \
  --specification analysis.json --out admission.json
```

Exit 0 means the scoped supplied evidence census is complete. Exit 2 means a
prerequisite is missing, failed, blocked or unresolved. Every report has
`physics_validated: false`, `admitted_action: inspect-source-bound-evidence` and
`scientific_certification: requires-authoritative-review`.

## Specification v1

The JSON document has exactly these top-level fields.

| Field | Contract |
|---|---|
| `schema_version`, `kind` | Integer `1`, string `analysis_specification` |
| `analysis_id` | Nonempty analysis identity, including an uncatalogued/generated analysis |
| `implementation` | Exact `framework`, `routine`, `artifact`; the artifact must be a bound subject |
| `request` | Exact `purpose`, `input_level`, `target_level`, `scope` |
| `artifacts` | Unique records with exact `id`, `path`, lowercase SHA256, `role` |
| `subjects` | Complete unique IDs of the implementation/input/source artifacts against which checks were performed |
| `definitions` | Unique records with exact `id`, `role`, `definition`, `artifact`, `locator` |
| `outputs` | Complete requested output denominator, with the basis fields below |
| `checks` | Source-bound receipt, direct build-receipt or numerical comparison checks |

Physical levels are `particle`, `reconstructed`, `truth` and `non-event`. The
input and requested target are separate. Truth events used for a reconstructed
exclusion still require response evidence. `scope` is a nonempty explicit JSON
object, for example model/era/mass/lifetime/energy/domain conventions. It is bound
in checks. Free prose cannot widen the admitted claim or action.

Purposes are `routine-evaluation`, `reference-reproduction`,
`measurement-comparison`, `exclusion`, `projection` and `method-study`.

Every purpose requires `source-closure`, `build`, `exposure` and
`output-completeness`. Non-event calculations omit event exposure. Every
scientific purpose additionally requires `definitions`, `semantics`,
`normalization` and `reference`; reconstructed targets require `response`.
Measurement comparison, exclusion and projection also require `uncertainty`,
`statistics` and `independent-review`. Projection requires
`projection-calibration`. Method studies require `data-use`,
`method-calibration` and `independent-review`.

These are prerequisites, not a claim that any named statistical/physical family
has been implemented. A response receipt is attributed supplied evidence. A
missing experimental response must remain missing. A valid report can retain a
partial executable calculation while the requested scientific conclusion remains
blocked.

## Exact output basis and numerical comparison

Each output has exact fields `name`, `quantity`, `unit`, `normalization`,
`representation`, `weight`, `definition`, `bin`. The definition ID points to a
source-bound object/observable/selection definition in the specification.

Representations are `integrated`, `differential` or `scalar`. Normalizations are
`absolute`, `all-events`, `in-range` or `conditional`. They have different
meanings; the assessor does not convert between them. `weight` binds the actual
stream, rather than accepting a nominal result as a PDF/scale variation.

An unbinned scalar or region can use `bin: null`. Finite bin geometry is
`{"axes": [{"name": "mjj", "unit": "GeV", "lower": 1000, "upper": 1200}]}`.
Axes are unique, finite and strictly increasing. Differential output requires
explicit geometry. Unbounded bins or an unsupported volume convention need a
separately implemented transport contract.

A numerical check is

```json
{
  "kind": "reference",
  "method": "comparison",
  "prediction": "candidate-values",
  "reference": "published-values",
  "criteria": {"atol": 0.0, "rtol": 0.05}
}
```

The two artifact IDs must be distinct and bound. Their JSON documents have exact
fields `schema_version: 1`, `kind: analysis_reference_values`, `analysis_id`,
`scope_sha256`, `request_sha256`, `implementation_sha256`,
`definitions_sha256`, `subjects`, `source`, `outputs`. Digest fields use SHA256
of sorted compact JSON with no nonfinite numbers. `subjects` maps bound artifact
IDs to their exact digests. The prediction must bind the specification's entire
subject census; reference sources must resolve to actual bound artifact IDs and
digests. A hash-shaped fictional publisher ID is rejected.

The outputs are unique `{basis, value}` rows. Their complete basis must equal
the requested output, including source definition and bin geometry. Missing,
duplicate, extra or differently normalized outputs fail. For each requested
output the assessor calculates

`difference = prediction - reference` and
`tolerance = atol + rtol * abs(reference)`.

Both derived quantities must be finite. A comparison passes only when every
absolute difference is within its prospective tolerance. Failed rows are retained.
These thresholds are supplied scientific criteria. They are neither inferred
confidence intervals nor a test of reference extraction or detector calibration.

This complete output denominator matters for routine-specific dependencies. A routine
may return successfully and fill an inclusive histogram while skipping the
requested classifier selection after a model-load failure. Exit status and the
presence of one histogram cannot establish the requested computation.

## Observed source-build receipt

The direct build check is

```json
{
  "kind": "build",
  "method": "build-receipt",
  "artifact": "actual-build-receipt",
  "plan": "actual-build-plan",
  "capsule": "implementation-capsule",
  "binary": "actual-built-binary"
}
```

These are artifact IDs. The plan is the builder's **generated**
`build-plan.json`, not its input configuration. The capsule must be the declared
implementation artifact, and its routine/framework must match that implementation.
The assessor invokes `routine_build.verify_receipt` read-only, checking original
and staged source, source layout/dependencies, original build configuration,
runtime tools/artifacts, exact command/probe identities, raw process observations,
logs and the built binary. The plan's retained `base_dir` preserves path resolution.

`inputs` enumerates these transitive inputs and retained observations as well as
the specification's artifacts; it never reruns the compiler or probe. The verifier
establishes retained evidence integrity. A supplied receipt does not authenticate
an external process or establish detector physics. Actual supervised stage custody
is separate.

## Supplied checks and independent review

Other checks use `{kind, method: "receipt", artifact}`. The receipt has exact
fields `schema_version: 1`, `kind: analysis_check_receipt`, `check`, `analysis_id`,
`scope_sha256`, `request_sha256`, `implementation_sha256`, `subjects`,
`definitions_sha256`, `outputs_sha256`, `status`, `producer`, `method`,
`limitations`. Status is `passed`, `failed`, `blocked` or `unknown`; producer has
exact `identity`, `role`, `context_id`. All subject/request/definition/output
identities must match the current specification. A changed target, era, bin,
threshold or weight invalidates the old check. Subject bindings include every
definition's source artifact as well as the caller's subject list, so changing
paper bytes invalidates receipts even when that paper was omitted from the list.

An independent-review receipt additionally needs a `host_receipt` ID pointing to
a bound `review-host` artifact and a distinct verifier role, identity and context.
At this increment a caller's correctly hashed host JSON remains **unknown**.
Role strings and an arbitrary host artifact do not demonstrate an actual fresh
host invocation/response on the current subject packet. Dummy and stale host
receipts therefore keep inference tasks blocked.

An executed graph model can instead supply
`{kind: "independent-review", method: "graph-model", graph, node_id, subject,
packet_sha256}`. `subject` is a bound artifact containing the exact
`review_subject(specification)` JSON, including the current request,
implementation, source subjects, definitions and requested output basis. The
subject also binds every definition's source artifact, the nonreview check
descriptors and their evidence artifacts. Changing a comparison tolerance or a
definition's paper bytes invalidates the old review, even if that source was
omitted from the caller's subject list. Review artifacts are excluded from this
closure to avoid a self-referential digest. The
assessor reads `agent_graph.model_receipt` and verifies the completed fresh
critic/verifier's current subject, packet, request, result and observed host
bindings. It requires the exact full-subject bytes in the presented packet;
a projection carrying only their original source hash cannot substitute for
that presentation. It never starts a model call. Loopback controls and unestablished
transports remain unknown.

The actual public response has exact fields `schema_version: 1`,
`kind: analysis_review_verdict`, `analysis_id`, `subject_sha256`, `status`,
`findings` and `limitations`. Every finding has `id` and `summary`; any retained
finding blocks the check, including a response that labels itself passed. The
response digest must match the graph's actual result. A host attestation records
source-call custody and disclosed context separation, not cryptographic actor
authentication, enforced sandboxing or scientific certification.

Material supplied failures remain in the report even when they exceed a narrow
requested task's minimal requirement set. Removing a failed check is a change
to the specification and needs attributable review; this assessor does not erase
historical evidence or authorize such a repair.

The executable engineering examples and adverse controls are in
[`test_analysis_admission.py`](../../tests/unit/test_analysis_admission.py).
