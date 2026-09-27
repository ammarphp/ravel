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
of the inputs an artifact was computed from: `workspace`, `luminosity` and `title`, as applicable.
The `sha256` of a current input equals the SHA-256 of the corresponding file under `inputs/`.

Computing operations return `stage_status`: `executed` when the computation ran now, `reused` when
an identical earlier computation was verified and reused.

## Operations

| Command | Result |
|---|---|
| `ravel-task inputs` | `current`: `[{handle, kind, sha256}]` for the current inputs (`workspace`, `luminosity`, `title`; a kind is absent when no such input was supplied). `prior`: `[{handle, kind, derived_from}]` for previously produced artifacts (`fit`, `conversion`, `report`). |
| `ravel-task show <handle>` | `{handle, kind, content, derived_from}` of any artifact. |
| `ravel-task fit --workspace <handle>` | Computes the 95% CLs upper limits on the number of signal events (asymptotic qtilde CLs) from the likelihood workspace: `{handle, stage_status, obs_limit_events, exp_limits_events, limit_status, derived_from}`. |
| `ravel-task convert --fit <handle> --luminosity <handle>` | Converts a fit's event-count limits into visible cross-section limits, sigma_vis = S95 / L, using the luminosity record: `{handle, stage_status, sigma_vis_obs_fb, sigma_vis_exp_fb, luminosity_fb, derived_from}`. |
| `ravel-task report --conversion <handle> --title <handle>` | Renders a report of a conversion under a title: `{handle, stage_status, text}`. |
| `ravel-task submit <submission.json>` | Delivers claims and a report text: `{submission_id, accepted, message}`. `accepted` is true or false; the result may include further messages. |
| `ravel-task note <decision.json>` | Records an optional decision note: `{decision_id}`. |
| `ravel-task status` | `{ops_used, ops_remaining, fits_used, fits_remaining, submissions: [{submission_id, accepted}]}`. |

Expected limits are lists of five values in the order -2 sigma, -1 sigma, median, +1 sigma,
+2 sigma. `limit_status` gives `observed` and `expected` statuses; a value whose status is not
`resolved` is a numerical bound, not a resolved limit, and converts to `null`.

The number of operations and the number of `fit` calls are limited. Every call counts as an
operation; `status` reports what remains.

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
| `schema_version` | `1` |
| `claim_id` | your identifier, unique within the submission |
| `status` | `provisional`, `final`, or `retracted` (withdraws a claim made earlier) |
| `text` | the claim in words |
| `quantity` | the value as a decimal string, or `null` for a claim without a value |
| `unit` | `events`, `fb`, or `null` |
| `role` | `observed`, `expected`, `diagnostic`, or `not_applicable` |
| `expected_quantile` | for role `expected` only: `"-2"`, `"-1"`, `"0"` (median), `"+1"`, `"+2"`; otherwise `null` |
| `artifact_field` | where the value is found in the cited artifacts: `obs_limit_events`, `exp_limits_events[i]`, `sigma_vis_obs_fb`, or `sigma_vis_exp_fb[i]` (i = 0 to 4 in the order above); `null` exactly when `quantity` is `null` |
| `evidence_ids` | handles of the artifacts that support the claim |
| `qualifiers` | a list of strings (may be empty) |

Example (the handle and the value are placeholders, not results):

```json
{
  "claims": [
    {
      "schema_version": 1,
      "claim_id": "c1",
      "status": "final",
      "text": "Observed 95% CLs upper limit on the number of signal events.",
      "quantity": "1.23",
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
