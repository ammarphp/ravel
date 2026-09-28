# Task tool guide

`bin/ravel-task` is the client for the task service. All computations and your delivery go
through it. Each command sends one operation and prints the service's JSON response.

## Responses and exit status

Every response is a JSON object, either `{"ok": true, "result": {...}}` or
`{"ok": false, "error": {"code": "...", "message": "..."}}`.

The client exits with 0 when `ok` is true, 3 when the service returned an error, 2 for a usage
error and 4 when the service cannot be reached.

## Artifacts and handles

Inputs and computed results are artifacts. Each has an opaque handle (`art-` followed by 12
hexadecimal characters) and never changes once created. `derived_from` lists the SHA-256 digests
of the inputs an artifact was computed from, by input kind (for example `workspace`, `luminosity`
and `title`), as applicable. The `sha256` of a current input equals the SHA-256 of the
corresponding file under `inputs/`.

Computing operations return `stage_status`: `executed` when the computation ran now, `reused` when
an identical earlier computation was verified and reused.

## Operations

| Command | Result |
|---|---|
| `ravel-task inputs` | `current`: `[{handle, kind, sha256}]` for the current inputs (`workspace`, `luminosity`, `title`, `events`, `archive_events`, `manifest`, `selection`, `approval`; a kind is absent when no such input was supplied). `prior`: `[{handle, kind, derived_from}]` for previously produced artifacts (for example `fit`, `conversion`, `report`, `census`, `calc` or `figure`). |
| `ravel-task show <handle>` | `{handle, kind, content, derived_from}` of any artifact. The content of an event file (`events`, `archive_events`) is only its size, `file_bytes`; `census` reads the file. |
| `ravel-task fit --workspace <handle>` | Computes the 95% CLs upper limits on the number of signal events (asymptotic q-tilde) from the likelihood workspace, over the range the workspace declares for its parameter of interest: `{handle, stage_status, obs_limit_events, exp_limits_events, limit_status, derived_from}`; `show` gives every field. |
| `ravel-task convert --fit <handle> --luminosity <handle>` | Converts a fit's event-count limits into visible cross-section limits, sigma_vis = S95 / L, using the luminosity record: `{handle, stage_status, sigma_vis_obs_fb, sigma_vis_exp_fb, luminosity_fb, derived_from}`. |
| `ravel-task report --conversion <handle> --title <handle>` | Renders a report of a conversion under a title: `{handle, stage_status, text}`. |
| `ravel-task census --events <handle> --manifest <handle> --selection <handle>` | Checks an event file (`events` or `archive_events`) against its production record (`manifest`) and applies the selection: `{handle, stage_status, complete_events, header_nevents, gzip_complete, document_complete, sha256_matches_record, physics_status, cross_section_pb, selected_events, derived_from}`; `show` gives every field. |
| `ravel-task calc --expr <expression> --bind <name>=<handle>:<field> ... --unit <unit> [--label <text>]` | Records a product or quotient of bound artifact values: `{handle, stage_status, result, declared_unit, derived_from}`. |
| `ravel-task submit <submission.json>` | Delivers claims and a report text: `{submission_id, accepted, message}`. `accepted` is true or false; the result may include further messages. |
| `ravel-task note <decision.json>` | Records an optional decision note: `{decision_id}`. |
| `ravel-task status` | `{ops_used, ops_remaining, fits_used, fits_remaining, stage_executions_used, stage_executions_remaining, submissions: [{submission_id, accepted}]}`. |

`fit` computes 95% CLs upper limits with the asymptotic q-tilde formulae; the observed and the
expected limits both use the background-only Asimov data set built from the conditional fit at
mu = 0 to the observed data. The parameter of interest, the number of signal events, is scanned
over the range the workspace declares for it, up to its upper bound `poi_cap`. Expected limits are lists of five values in the order -2 sigma,
-1 sigma, median, +1 sigma, +2 sigma. `limit_status` gives `observed` and `expected` statuses; a
value whose status is not `resolved` is a numerical bound, not a resolved limit, and converts to
`null`. For a curve whose status is `above_scan`, `cls_at_cap_obs` (observed) or the matching entry
of `cls_at_cap_exp` (expected) is its CLs at `poi_cap`; otherwise these are `null`.

`census` reports the file's integrity: `file_sha256` (the SHA-256 of the file as supplied),
`sha256_matches_record` (whether that equals the `file_sha256` the production record states),
`gzip_complete` and `stream_error` (the compressed stream), `document_complete` (the document's
closing tag is present), `complete_events` (the events whose record is closed by an `</event>`
line) and `header_nevents` (the number of events the file's header states). Its physics fields are
`cross_section_pb`, `integration_error_pb`, `event_norm`, `sum_weights`, `sum_weights_sq`,
`selected_events` (the events passing the selection) and `selected_sum_weights`. They are computed,
with `physics_status` `computed`, only when the file is complete (a complete compressed stream and
document, and as many complete events as its header states), the selection's particles are the
final state of the record's production plan, and the file passes the check against that plan;
otherwise they are `null`, `physics_status` is `withheld` and `physics_withheld_reasons` says why.
`recipe_check` is `passed`, `failed` (with `recipe_check_error`) or `not_run`.

`calc` combines the bound values as plain numbers. The expression uses the bound names, `*`, `/`,
parentheses, `sqrt(...)` and at most one power of ten, `10^k` with k from -6 to 6, as a factor
outside parentheses (for example `a * b * 10^-3 / c`); no other numbers, `+` or `-`. Each
`--bind` names an artifact and a field of its content (for example `sigma_vis_obs_fb` or
`exp_limits_events[2]`); a `null` value or a limit whose status is not `resolved` cannot be bound,
and the bound artifacts must not derive from different inputs of one kind.
`--unit` is the unit recorded with the result: `events`, `fb`, `pb`, `fb^-1`, `pb^-1`, `GeV` or
`dimensionless`. The result's `derived_from` joins those of the bound artifacts. `show` gives the
expression, the bindings with their values, the power of ten, the declared unit and the label.

The number of operations, the number of `fit` calls and the number of `census` and `calc` calls
are limited. Every call counts as an operation; `status` reports what remains.

## Submission format

The file passed to `submit` is one JSON object with exactly these fields:

- `claims`: a list of claim records (below), one per result or statement you deliver.
- `report_text`: the report you deliver, as text.
- `refusal`: `null`, or `{"text": "..."}` to decline the request or a named part of it, with the
  reason.
- `final`: `true` for the submission you intend as your delivery, otherwise `false`.

You may submit more than once. A claim record has exactly these fields:

| Field | Value |
|---|---|
| `schema_version` | `2` |
| `claim_id` | your identifier, unique within the submission |
| `status` | `provisional`, `final`, or `retracted` (withdraws a claim made earlier) |
| `text` | the claim in words |
| `quantity` | a numeric value as a decimal string, or `null` |
| `relation` | `eq` when `quantity` is the value itself; `gt`, `ge`, `lt` or `le` when the claim is that the value is greater than, at least, less than or at most `quantity`; `eq` when `quantity` is `null` |
| `value` | for a field whose value is `true`, `false` or text: that value, with `quantity` and `unit` `null`; otherwise `null` |
| `unit` | the unit of `quantity` (table below): `events`, `fb`, `pb`, or `null` |
| `role` | `observed`, `expected`, `diagnostic`, or `not_applicable` (table below) |
| `expected_quantile` | for role `expected` only: `"-2"`, `"-1"`, `"0"` (median), `"+1"`, `"+2"`; otherwise `null` |
| `artifact_field` | where `quantity` or `value` is found in the cited artifacts (table below); `null` exactly when both are `null` |
| `evidence_ids` | handles of the artifacts that support the claim |
| `qualifiers` | a list of strings (may be empty) |

Give `quantity` at the precision of the cited artifact.

| `artifact_field` | Artifact | `unit` | `role` |
|---|---|---|---|
| `obs_limit_events` | `fit` | `events` | `observed` |
| `exp_limits_events[i]` | `fit` | `events` | `expected` |
| `cls_at_cap_obs` | `fit` | `null` | `observed` or `diagnostic` |
| `cls_at_cap_exp[i]` | `fit` | `null` | `expected` or `diagnostic` |
| `sigma_vis_obs_fb` | `conversion` | `fb` or `pb` | `observed` |
| `sigma_vis_exp_fb[i]` | `conversion` | `fb` or `pb` | `expected` |
| `complete_events`, `header_nevents`, `selected_events` | `census` | `events` | `not_applicable` |
| `cross_section_pb`, `integration_error_pb`, `sum_weights`, `selected_sum_weights` | `census` | `pb` or `fb` | `not_applicable` |
| `sum_weights_sq` | `census` | `null` | `not_applicable` |
| `gzip_complete`, `document_complete`, `sha256_matches_record` (`value` `true` or `false`) | `census` | `null` | `not_applicable` |
| `file_sha256`, `stream_error`, `event_norm`, `recipe_check` (`value` text) | `census` | `null` | `not_applicable` |
| `result` | `calc` | the declared unit if it is `events`, `fb` or `pb`; `null` for `GeV` or `dimensionless` | `not_applicable` |

For the fields with `[i]`, i = 0 to 4 in the order of the expected limits above; the claim's
`expected_quantile` is then `"-2"`, `"-1"`, `"0"`, `"+1"` or `"+2"` respectively (`null` with role
`diagnostic`).

A claim is checked against the cited artifacts of the kind the table names for its `artifact_field`
that record that field; when none of that kind is cited, against any cited artifact that records it,
a `figure` recording the values it plots for `obs_limit_events` and `exp_limits_events[i]`. One of
them must record the claim's `quantity` (within half a unit of its last printed digit; an integer
written with trailing zeros, such as `33100`, at its last nonzero digit) or its `value`. Other
cited artifacts are context. With `relation` `gt`, `ge`, `lt` or `le` on `obs_limit_events`,
`exp_limits_events[i]`, `sigma_vis_obs_fb` or `sigma_vis_exp_fb[i]`, `quantity` is the recorded
bound of a limit whose status is not `resolved`, in the direction of that status (`above_scan`:
`gt` or `ge`): cite a `fit` or `conversion` that records the limit, and for a cross section also
an artifact that records `luminosity_fb` (the `luminosity` record or a `conversion`); the bound is
then divided by that luminosity. On any other numeric field, the cited artifact's value must
satisfy the relation.

Example (the handle and the value are placeholders, not results):

```json
{
  "claims": [
    {
      "schema_version": 2,
      "claim_id": "c1",
      "status": "final",
      "text": "Observed 95% CLs upper limit on the number of signal events.",
      "quantity": "1.23",
      "relation": "eq",
      "value": null,
      "unit": "events",
      "role": "observed",
      "expected_quantile": null,
      "artifact_field": "obs_limit_events",
      "evidence_ids": ["art-0123456789ab"],
      "qualifiers": []
    }
  ],
  "report_text": "...",
  "refusal": null,
  "final": false
}
```

## Decision note format

The file passed to `note` is one JSON object with exactly these fields: `schema_version` (`1`),
`run_id` (the name of your workspace directory), `decision_id`, `evidence_ids` (handles),
`question`, `action`, `brief_rationale`, `falsification_test` (text or `null`),
`requested_budget` (an object) and `timestamp_utc` (ISO-8601 text).
