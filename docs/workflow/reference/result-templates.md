# Result templates

Some requests supply the exact form their numbers must take, such as a
HEPData-style YAML table with bin edges and empty values. Keep that file with the
original request. Once the result is accepted, `ravel fill-template` copies the
values into a new file and leaves every edge, header and qualifier as supplied.

```sh
ravel fill-template --template template.yaml --result RUN/outputs/quantities.json \
  --rundir RUN --claim-scope reproduction --out deliverables/filled.yaml
```

The command writes the filled template and, beside it, a provenance record named
after it with `.provenance.json` appended. `--out` and its provenance must be new files.
Delivery code can call `ravel.workflow.result_templates.fill` with the same
arguments, or `deliver` for several templates.

To deliver into the requester's file as well, pass `--deliver-into PATH`. PATH
must still contain exactly the unfilled template bytes pinned at the start of
the fill; PATH can be the `--template` file itself. After writing `--out` and
its provenance, the command stages the filled bytes beside PATH, checks their
metadata semantics and rechecks PATH's SHA256 immediately before atomic
replacement. A changed or already filled file is refused and left untouched.
The provenance records `delivered_into` with the path and before/after hashes.
If delivery fails, the filled output and provenance remain available, without
a successful-delivery record. Metadata meaning, edges, headers and qualifiers
are preserved; YAML formatting can change.

For event-yield deliverables, pass `--require-nonnegative`. It refuses a negative
filled value and names the zero-based bin index and edges. The policy is explicit;
without the flag, signed general results remain supported.

For a run the controller owns, `ravel fill-template` (and `fill`/`deliver`) refuse before writing anything,
whether the run, the output or the delivery target lies in it: only the controller's sole sink delivers its
results. The sink fills a trusted-side results file only for an accepted delivery. On every other run the fill
works as described here and its receipt carries `NOT GOVERNED`.

## Accepted results

The result must be captured by the current accepted review of `RUN` under the
named claim scope. Pass the result file as an extra review input so the review
cycle records its hash. A run with `agent_layer_epoch: 2` also passes the
delivery gate. A run without delegation delivers under its human approvals and
must clear every refusal of the review-point provider: pending blocking points,
standing findings, changed review obligations, an action outside the plan, an
unsafe fan-out, a required decision receipt, and an original requirement that no
accepted output maps to. A delegated run passes the whole `delivery` decision
gate, as result packaging does; that gate needs the R3 delivery decision
receipt. A delegated run fills a template after that decision is recorded. The command names what refuses.
On an epoch-two run the accepted review itself stands only while the attested
worker receipts credit its CHECK-IN 2 review points.

The fill records a fresh delivery label with its plain-language notices. A
`diagnostic` claim scope delivers with the diagnostic label: the record keeps
`review_accepted: true` and `accepted: false`, because a diagnostic review never
carries scientific acceptance. Any other scope needs the accepted label: the
result bytes must be the exact output of a stage with current supervisor custody
and a matching approval-bound launch, required roles must be credited and the
current review must cover those bytes. Otherwise the fill is refused and nothing
is written. Two result forms are read:

- the `quantities.json` output of a `quantities` study (choose a stream with
  `--weight` when there are several);
- a `binned_values` table:

```json
{"schema_version": 1, "kind": "binned_values",
 "axes": [{"name": "MET", "unit": "GeV"}], "unit": "events", "representation": "integrated",
 "bins": [{"low": [250], "high": [350], "value": 12.0, "uncertainty": 1.5},
          {"low": [350], "high": [450], "value": 4.0}],
 "overflow": 1.0}
```

`overflow` and `underflow` hold content outside the bins. Use
`"overflow_in_last_bin": true` or `"underflow_in_first_bin": true` instead when the
edge bin already contains it.

## Templates

A YAML or JSON HEPData table gives edges as `low`/`high` independent values and
the column to fill as `value: null` rows (or an empty `values` list). Use
`--table` and `--column` when a file has several tables or empty columns. A plain
JSON template uses `"kind": "result_template"` with `axes`, `unit`, optional
`overflow`/`underflow` and `bins` of `low`, `high` and `"value": null`.

Overflow and underflow follow the template's declaration, given as a dependent
column qualifier (`name: overflow`, `value: last-bin`) or a plain-template field:

| Declaration | Meaning |
|---|---|
| `overflow: last-bin` | The last bin holds everything from its lower edge upward |
| `underflow: first-bin` | The first bin holds everything below its upper edge |
| `excluded` | The edge bin holds only its own range |

Flow wording is scanned throughout every template document, including free-text
instructions in metadata documents. Wording such as "rightmost bin includes all
events above its lower edge", "last bin is inclusive", or "first bin ... and
below" requires an explicit declaration; the command quotes the instruction and
offers the placement and exclusion options. It does not infer the convention.

To declare flow without editing the template, use `--overflow {last-bin,excluded}`
and/or `--underflow {first-bin,excluded}` with `--flow-evidence "quoted text"`.
The evidence must occur verbatim, with whitespace normalised, in a template
document. A declaration that conflicts with a template qualifier is refused.
For example, when the template contains the quoted instruction:

```sh
ravel fill-template --template template.yaml --result RUN/outputs/histogram.json \
  --rundir RUN --claim-scope diagnostic --out deliverables/filled.yaml \
  --overflow last-bin \
  --flow-evidence "The rightmost bin includes all events above its lower edge." \
  --deliver-into template.yaml --require-nonnegative
```

The provenance records `conventions.source: cli-declaration`, the evidence text
and its zero-based document index, or `template metadata` for metadata declarations.
Separate result flow requires a convention even when the template has no flow
wording. Explicitly excluded values are recorded in `flow_excluded` with their
declaration and source. Already folded overflow requires `last-bin`; declaring
it `excluded` is refused. The corresponding underflow rule uses `first-bin`.
Flow placement needs integrated values and a result that records overflow and
underflow separately. Fraction or shape results with separate flow are refused:
fold flow before normalising upstream, then deliver the already folded result.
Single-bin templates follow the same rules, including folding both flows.

Python callers use `fill(..., overflow=None, underflow=None, flow_evidence=None,
deliver_into=None, require_nonnegative=False)`; `deliver()` forwards these keywords.

## Matching rules

- Each template bin matches a result bin with exactly the same edges.
- A declared rebinning merges adjacent result bins into one template bin:
  `{"schema_version": 1, "reason": "...", "merges": [{"template_bin": 2, "result_bins": [4, 5]}]}`.
  The merged bins must cover the template bin exactly; totals are preserved and recorded.
- Axis and value units must match wherever the template states them.
- Values are copied or summed; nothing is interpolated, extrapolated or converted.

`--uncertainty-label LABEL` also writes each bin's standard deviation as a
symmetric error with that label. Without it, uncertainties stay in the provenance
record.

The provenance record holds the template, result and output hashes, the review
scope and sequence, units, conventions, the bin-by-bin mapping and the totals.

## Provisional delivery at a study deadline

A study can declare a delivery deadline in its task contract, as an absolute UTC
time or as a wall budget from the recorded run start:

```json
"deadline": {"utc": "2030-01-01T12:00:00Z", "margin_s": 3600}
"deadline": {"budget_s": 86400, "start_utc": "2030-01-01T00:00:00Z", "margin_s": 3600}
```

`margin_s` is the delivery margin before the deadline. `ravel status` shows
`study_deadline` with the deadline, the seconds left and `in_margin`. Inside the
margin it adds a warning and the one action that delivers something valid:

| `action.kind` | When |
|---|---|
| `reviewed-fill` | The review has accepted; fill from the accepted result |
| `provisional-fill` | The review is still open and a valid stage receipt pins an output |
| `finish-review` | Neither applies; finish the review (or produce and open one) |

`--provisional` fills from an output awaiting review. It is refused
unless the contract declares a deadline, the margin has been reached, a valid
stage receipt pins the exact result bytes, and an open, unresolved review
(`awaiting_review`) cites the result. A hand-made file, a changed output, an
accepted review (use the ordinary fill) or a sent-back or held review is refused.

```sh
ravel fill-template --provisional --template template.yaml --result RUN/outputs/histogram.json \
  --rundir RUN --claim-scope diagnostic --out deliverables/provisional.yaml \
  --deliver-into requester.yaml
```

The filled file says so: a YAML file starts with a `# RAVEL PROVISIONAL FILL`
comment block that names the open review and claim scope, and a JSON file gains a
top-level `provisional` object. The provenance record has `provisional: true`,
`acceptance.accepted: false`, the stage receipt, the open review (with its
attestation) and the deadline state at the fill.

When the review accepts, the reviewed fill supersedes the provisional one in place:

```sh
ravel fill-template --template template.yaml --result RUN/outputs/histogram.json \
  --rundir RUN --claim-scope diagnostic --out deliverables/reviewed.yaml \
  --deliver-into requester.yaml --supersedes deliverables/provisional.yaml.provenance.json
```

The requester file must still hold exactly what the provisional fill delivered.
The reviewed provenance records `supersedes`; the provisional record is never
rewritten, and a `.superseded.json` sidecar beside it links both records. A
provisional record can be superseded once.

A provisional fill never stands in for reviewed evidence. A claim record, a
CHECK-IN 3 claim census, an accepted fill and `export-submission` refuse a
provisional file, its provenance and its supersession sidecar
(`result_templates.provisional_errors`). Python callers pass
`fill(..., provisional=True)` or `fill(..., supersedes=PATH, deliver_into=PATH)`.
