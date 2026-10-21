# Task contract validation

`src/ravel/validation/validate_task_contract.py` is the structural authority for
`task_contract.json`. It uses only the Python standard library. The full machine-readable
structural schema is emitted by `python3 src/ravel/validation/validate_task_contract.py --schema`.
The schema's `$comment` records the additional exact-type, interval, and cross-field checks.

Passing this gate establishes a well-formed request and compute plan. It does not establish
correct physics, a validated detector model, a measured compute cost, user approval, or
permission to publish an exclusion. Those remain separate lifecycle obligations.

## Required fields

| Field | Accepted value |
|---|---|
| `schema_version` | Integer `1`. Missing versions, booleans, `1.0`, strings, and unknown versions fail. |
| `prompt` | Nonblank string. Validation preserves the supplied text verbatim. |
| `task_mode` | `survey`, `reproduce`, `reinterpret`, `projection`, `scan`, `summary_plot`, `anomaly_search`, `no_routine`, `generate`, `likelihood`, `calculation`, `research`, `unsupported`. |
| `detector_mode` | `particle-level`, `rivet-smearing`, `simpleanalysis-delphes-native`, `container`, `effmap-folded`, `delphes-custom-uncertified`, `TBD-judgment`, `parton-level`, `none`. |
| `stat_mode` | `published-likelihood`, `simplified-likelihood`, `constructed-likelihood`, `best-sr-counting`, `combined-counting`, `stability-only`, `shape-fit`, `blocked-shape-fit`, `sensitivity-expected-only`, `none-survey`, `prescribed-statistic`, `TBD-judgment`, `none-generation`, `provided-likelihood`. |
| `required_user_inputs`, `assumptions` | Arrays of nonblank strings. Empty arrays are allowed. |
| `compute_plan` | `none`, `dry`, `smoke`, `full`, `scan`. This is the requested ladder rung, not approval to run. |
| `approval_required` | Literally JSON `true`. Integer `1` does not qualify. |

Unknown properties are rejected at every fixed-structure object. Optional fields, when
present, must have their declared type. `null` is accepted only where explicitly listed.
Strings containing only whitespace fail wherever nonblank text is required.

## Targets

`targets` is optional and can be partial. Its only accepted fields are:

| Field | Accepted value |
|---|---|
| `model`, `process` | Nonblank string or `null` for unresolved information. `model` lists every recognised model hint, comma-separated. |
| `models` | Array of nonblank strings: each model hint as written in the request. |
| `analysis`, `arxiv`, `inspire`, `hepdata`, `figures` | Arrays of nonblank strings. Descriptive historical identifier strings remain allowed; this gate does not authenticate a publication. |
| `masses_gev` | Array of finite, nonnegative numbers. Zero is allowed for a massless particle. No model-dependent upper mass limit is invented. |
| `sqrt_s_gev` | Collision energy in GeV, a finite, strictly positive number or `null`. It is never counted as a mass. |
| `lumi_fb` | Finite, strictly positive number or `null` for unresolved information. |
| `mass_floor_note` | Nonblank string. |

Missing target data is never inferred, filled in, or converted from strings. The router and
CHECK-IN 1 must record and resolve the missing physics inputs.

The router reads masses in keV, MeV, GeV or TeV. Collision energies, widths, decay constants,
mass splittings, bounds and cuts are not masses. A Rivet routine name adds its analysis name and
INSPIRE record. A host `--interpretation` can carry a `targets` object that replaces the
extracted fields; any identifier it names must appear in the request.

## Reading and plan sidecars

`ravel initiate` writes two sidecars next to the contract:

- `inputs/reading.json` (`kind: request-reading`): the request read into witness items,
  facts, constraints, deliverables, ambiguity rows, boundaries and dismissals, each bound to
  exact spans. `ravel.workflow.request_reading.check` validates it.
- `inputs/plan.json` (`kind: request-plan`): the draft plan, when the plan module is
  installed. Stage 1 shows it at CHECK-IN 1; it does not govern.

The obligation census in `task_requirements` is derived from the reading. Its first
obligation is the whole request verbatim, and every finer obligation carries exact spans.

A contract can pin the sidecars with the optional keys `reading` and `request_plan`, each
`{path, sha256}` with a run-relative path. Pinned files enter the approval fingerprint, so
editing one after approval fails verification. A contract without pins validates,
evaluates and fingerprints exactly as before.

## Cost estimates

`cost_estimate` is optional before `full`/`scan` and required for those two rungs. Whenever
present, it must be an object with a valid `mode` equal to `compute_plan` and either:

- `walltime_h`, or
- all three fields `walltime_h_naive`, `walltime_h_with_lhe_reuse`, and `lhe_reuse_note`.

The second representation preserves an explicit two-scenario budget.
Both scenarios are validated. The validator does not choose or average them.

| Field | Accepted value |
|---|---|
| `mode` | A compute-plan enum. Must equal the contract's `compute_plan`. |
| `points` | Positive integer, required for `full`/`scan` in live validation. |
| `events_per_point`, `parallel` | Optional positive integers. Booleans and fractional or floating-point counts fail. |
| `backend` | `native` or `container`. |
| `walltime_h`, `per_point_min`, `walltime_h_naive`, `walltime_h_with_lhe_reuse` | Exactly two finite, nonnegative numbers in ascending order. Full/scan walltime intervals must have a positive upper bound. |
| `disk_gb_peak` | Finite, nonnegative number. |
| `note`, `disk_note`, `warning`, `cpu_note`, `ladder`, `lhe_reuse_note`, `proposed_primary_grid` | Nonblank strings. |
| `waypoint_smoke` | Object requiring `walltime_h` (an ordered interval) and `disk_gb` (finite, nonnegative). |
| `schema_version` | Optional integer `1` when embedding an emitted cost artifact. |
| `generated_by` | Optional literal `cost_preflight.py` when embedding an emitted cost artifact. |
| `generated_utc` | Optional string; the cost emitter permits an empty deterministic timestamp. |

Historical compact costs can omit events, disk, backend, parallelism, and per-point timing.
The validator does not manufacture the absent metadata. `full`/`scan` still require numeric
`points` by default. A budget is a declared estimate that requires measured cost evidence.

## Optional annotations

These version-1 annotations are explicitly enumerated because they already occur in the
committed trial contracts. They are not an unrestricted extension dictionary.

| Field | Accepted value |
|---|---|
| `blocking`, `escalate`, `option_c_caps`, `traps_noted_generation_side` | Arrays of nonblank strings. |
| `notes`, `validation_oracle`, `deliverable`, `stat_mode_note` | Nonblank strings. A `prescribed-statistic` contract quotes the requested statistic verbatim in `stat_mode_note`. |
| `traps_checked` | Array of trap identifiers matching `T` followed by a positive integer. |
| `traps_hit` | Array whose entries are either trap identifiers or objects requiring `id`, nonblank `evidence`, nonblank `consequence`, and `flag_number`. |
| `traps_hit[].flag_number` | Positive integer or string `F` followed by a positive integer. Both existing representations are retained; booleans fail. |
| `traps_procedural` | Array of objects requiring a trap `id` and nonblank `note`. |
| `channels_under_consideration` | Object with nonblank channel-name keys and nonblank descriptive string values. |
| `published_dark_sector_fixed` | Object with the fields listed below. |

`published_dark_sector_fixed` accepts finite, nonnegative `m_qdark_gev`,
`m_pid_diagonal_gev`, `m_pid_offdiagonal_gev`, `m_rhod_diagonal_gev`, and
`m_rhod_offdiagonal_gev`; finite, positive `Lambda_d_gev`; positive integer `nFlav_HV`;
and nonblank `Lambda_d_note`, `alpha_dark`, and `correction_note`. These structural checks
do not endorse a numerical dark-sector assumption or establish its provenance.

## Cross-field and live-consumer behavior

- `unsupported` requires a nonempty `blocking` list and must not request generation.
- `blocked-shape-fit` must not carry `full` or `scan`.
- The existing survey/summary rule rejects `full` and `scan`.
- Invalid objects fail before lifecycle code reads their fields. Library calls to
  `validate_run_state.evaluate()` enforce the same gate as its CLI.
- `workflow_state init`, `advance`, and approval use strict validation. Approval also
  validates the recorded budget for the rung being approved and refuses a rung above
  the task contract's scope. A lower rung, such as smoke before a declared scan, is allowed.
- The approval emitter, Bash guard, and lifecycle approval invariant share
  `workflow_state.verify_approval()`. A present file alone is never live approval.
- The session-scoped Bash generation guard rejects missing or invalid contracts,
  missing validators, and generation under `none`/`dry`. Non-generation commands
  and development sessions without a scoped physics run retain their existing behavior.
- Task-contract JSON readers reject duplicate keys at any nesting level, nonstandard
  `NaN`/`Infinity` literals, and non-finite values produced by exponent overflow. The
  validator never converts a boolean into a number or mutates its input.

This does not make arbitrary command execution a security boundary. The Bash guard still
recognizes generation commands heuristically. Standard explicit
`scan_orchestrator.py launch ... --go` and `scan_babysitter.py ...` invocations require a
bound **scan** approval; a bound smoke approval must not launch either driver. Dry launch,
status, and help calls remain available without scan approval. These two known drivers
launch the existing pipeline runners internally.

A generic `run-pipeline-native.sh` command does not state whether the referenced event
configuration is smoke or full statistics. The guard validates its bound approval but
does not inspect that configuration or enforce its event count, point count, or walltime
budget. Aliases and arbitrary shell wrappers can also evade command recognition. This is
a remaining execution-scope scope condition, not proof of end-to-end budget enforcement.

Content integrity and human authentication
are separate: the user quote and emitter identity remain editable data, without a signed
human-approval service. Approver identity requires authenticated authority evidence in addition to the hash binding.

## Version-2 approval binding

Native execution also requires an `execution_plan` object with a portable run-relative `path` and lowercase 64-character `sha256` of the exact saved plan bytes. Pin the actual model, analysis, cards, seeds, budget and stage outputs before presenting the plan. The executor verifies this pin and the current approval before every stage; a status view or `--go` flag alone must not authorize it. A changed execution plan requires recording the actual renewed authorization for its scope. Artifact-bound comparison policies use the separate `certification_plans` pins described in [scientific results](scientific-results.md).

Task contracts remain version 1. Newly recorded `inputs/checkin1_approval.json` artifacts
use version 2 and require exactly these fields:

| Field | Required value |
|---|---|
| `schema_version` | Integer `2`, never a boolean or string. |
| `generated_by` | Literal `workflow_state.py approve`. |
| `generated_utc` | String; an empty deterministic timestamp remains supported. |
| `approved_plan` | `none`, `dry`, `smoke`, `full`, or `scan`, at or below the task contract's requested rung. Static comparison approval does not authorize generation. |
| `quote` | Nonblank string recording the physicist's reply. |
| `task_contract` | The active contract's run-relative path, either `inputs/task_contract.json` or the supported root layout `task_contract.json`. |
| `checkin1` | Literal `inputs/checkin1.json`. The source must have `kind=checkin1`. |
| `cost_preflight` | Literal `inputs/cost_preflight.json`. Its emitted metadata and mode must match the approved rung. |
| `input_fingerprint` | The existing `provenance.py` fingerprint over the ordered contract, check-in, and budget file bytes. |

The fingerprint is captured before approval validation and recomputed after its reads.
The live guard and lifecycle invariant recompute it again from the current inputs.
Changing any bound source, including a formatting-only byte change, invalidates the old
approval. Missing sources, duplicate JSON keys, malformed approval fields, changed paths,
an altered rung, or an invalid cost/check-in source also fail. Re-record approval for the
revised inputs through the normal CHECK-IN process; do not update fingerprints by hand.

Existing version-1 approval files remain untouched as historical records. They do not
bind their source bytes and must not authorize new compute. Live reuse requires a new
version-2 approval. The lifecycle's existing pre-epoch archival reporting concession can
report incomplete historical approval as a warning; strict lifecycle checks and the live
Bash guard never apply that concession.

Regression tests reproduce the old bug using the real Bash guard: both an empty approval
object and a file containing `not JSON` previously returned exit 0. Tests now verify that
both fail, that edits to each of the three sources invalidate approval, that re-recording
restores validity, and that a declared scan can still have a valid smoke-rung approval.

## Explicit archive compatibility

`validate_task_contract.py --legacy CONTRACT.json` and `validate(contract, legacy=True)`
are archive-audit interfaces. They can waive only a missing `cost_estimate.points` for
`full`/`scan` when a valid `disk_gb_peak` and nonblank `note` exist. Each waiver emits an
`ARCHIVE ONLY` warning. CLI success is labeled **NOT live-compute validation**. No point
count is inferred, and versions, malformed fields, non-finite values, scope, and approval
requirements remain enforced. Live lifecycle and approval paths never request this waiver.

Reusing an archived contract for new compute requires an explicitly revised contract with numeric
counts and the normal approval process.

## Regression coverage

Regression coverage includes boolean versions/masses/counts, malformed budgets, negative
luminosity, non-finite costs, blank refusal reasons, unknown properties, real router output,
archive compatibility, strict JSON loading, direct lifecycle entry, first-stage advancement,
approval and the real Bash guard.

Run the focused tests from outside the repository to avoid its legacy `py.py` shadowing
pytest's dependency:

```bash
cd /private/tmp
python3 -m pytest /path/to/ravel/tests/unit/test_validate_task_contract.py /path/to/ravel/tests/unit/test_approval_chain.py -q
```
