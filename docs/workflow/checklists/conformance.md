# Check a repository against supplied conformance rules

For supplied note classes, literal sentence rules and slide builds, follow the
[supplied document build contract](../reference/supplied-document-builds.md).

Use this check when a requester supplies repository, workflow or submission
requirements. Obtain their rule pack; no rule pack ships with RAVEL. Check only
the declared rules and evidence, and preserve every missing-source result.

```bash
ravel conformance check --repo /path/to/repository --rules /path/to/rules.json \
  --rundir /path/to/run --out /path/outside/inspected/trees/report.json
```

Repeat `--rundir` for more runs; relative `--rundir` paths are resolved from the
current directory. The pack can also name run directories under `rundirs`;
relative pack directories are interpreted against the repository. A rule's
`scope` defaults to `repo`; `runs` applies that rule to every explicitly named
run and aggregates the evidence. Record paths in parameters are relative to the
selected scope. Paths must not escape it or traverse symlinks or `.git`.

The output must be a new file outside the inspected repository and every declared
run. `.md` selects Markdown; `--format json|markdown` selects either rendering
explicitly. Inspection writes no run state, receipts, repository files or Git
index. It never creates or moves a tag. Exit codes are 0 for all PASS, 1 if any
rule FAILs, 2 for an invalid request or report destination, and 3 if evidence is
NOT-CHECKABLE with no FAIL. A disabled rule is NOT-CHECKABLE.

The pack is a JSON object with `schema_version: 1`,
`kind: "conformance-rule-pack"`, and a nonempty `rules` list. Each row has a
unique requester-chosen `id`, a `check` from the table below, and `params`.
`enabled` is a Boolean, defaulting to true. Unknown fields, checks and parameters
are refused. The portable schema is
`src/ravel/data/submission/rule-pack.schema.json`. Supply identities, thresholds,
source paths, policy hashes and tag names at run time.

| Check | Required parameters | Evidence and interpretation |
|---|---|---|
| `instruction_hash` | `path`, `sha256` | Compare the declared document's bytes with the supplied upstream SHA256. |
| `session_instructions` | `path`, `sha256` | Prompt audit JSON with `records`; each row must carry the hash in `instruction_sha256`, or a supplied `receipt_field`. A missing row receipt FAILs. |
| `prompt_log` | `path` | Audit JSON with `records` and the explicit `gaps` list from its build. Every row requires full `prompt`, `model`, timezone-qualified `timestamp`, `usage_reported: true` and all five nonnegative `usage` token counts. Unknown or inexact `model_build_exact` is listed by row as NOT-CHECKABLE. Missing text, model, time, tokens or nonzero gaps FAIL. |
| `workflow_launches` | `stages`, `receipts`, `guard_log`, `policy_sha256`, `manager` | The full stage-attempt population, manager launch receipts and guard command census described below. |
| `tracked_clean` | `paths` | Listed files and all files consumed by enabled checks must be ordinary files tracked at HEAD, with matching working bytes, executable modes and a clean index. Tracking runs after the other checks. External run records must not satisfy this repository tracking rule. |
| `environment` | `stages`, `runtime_directory`, `requirements`, `installability` | Verify runtime snapshot content identities and exact stage-attempt coverage. Check exact named requirements pins against supplied installability records. `vendored_ravel` names the directory containing a vendored copy's nonempty LICENSE and NOTICE. |
| `skill_coverage` | `invoked`, `coverage` | Supplied complete invoked-software census and mappings to nonempty, clean, HEAD-tracked skill files. |
| `rerun_comparison` | `workflow`, `tolerances` | Ordered declared workflow `rules` must end in `kind: "quantity-comparison"` with `tolerances` naming the supplied nonempty JSON tolerances object. This checks the declared comparison's presence. |
| `size_budget` | `max_file_bytes` | Apply the declared positive byte ceiling to files in HEAD, the index and the working tree. Report folder totals using each file's largest size across those three views. `max_total_bytes` sets a total ceiling; `intermediates` supplies off-repository storage references. Symbolic links and submodule entries are measured from their recorded objects and never followed. |
| `note_limits` | `pdf`, `aux`, `segments`, `max_main_pages` | Read the built PDF through `pdfinfo` and use `manuscript_build.page_census` with emitted physical-page boundaries and the complete supplied segment population. Shared and unclassified pages count conservatively. Missing `pdfinfo` is NOT-CHECKABLE. |
| `submission_tag` | `tag` | Check that the declared lightweight or annotated tag resolves to HEAD. |

Missing evidence files are NOT-CHECKABLE. Malformed evidence, contradictory
records and documented violations FAIL. A known violation dominates a missing
source when both occur. Byte evidence carries source paths, SHA256 and sizes;
records or Git state changing during inspection invalidate the result. Evidence
scope remains documentary: completeness of supplied populations, instruction
receipt authenticity and public-source availability require producer or source
qualification. The check performs no installation, network query, workflow
execution or scientific comparison.

## Record interfaces

One-shot CLI results retain `prompt_text` and `model_requested`, `model_reported`,
`model_build_exact`, and `cli_version`. The [launcher receipt](../../../src/ravel/workflow/cli_agent_host.py)
keeps the UTF-8 text under `content.prompt_text`, bound by `content.prompt_sha256`,
and the model fields under `cli_reported`. Prompts above 16 MiB refuse before model
dispatch. External answers also keep `<response-stem>.receipt.prompt.txt` beside
the receipt; command-host calls retain the text inside the stored launcher receipt.
Only a reported valid calendar snapshot establishes exactness; aliases and missing
reports remain inexact. Consumers must preserve that flag and check the text hash.

`stages` can name the existing `execution_state.json` ledger. The check also reads
`logs/execution/<stage>/<attempt>/record.json` under that ledger's directory,
including failed, interrupted and superseded attempts. Ledger rows must match
retained current attempts. Missing retained history is NOT-CHECKABLE. A supplied
normalized census instead uses `{"stages": [{"id": "...", "attempt": "...",
"executed": true}]}`; each stage-attempt pair is distinct and the execution flag
is explicit. Runtime snapshots use `env_snapshot`'s existing content-addressed
schema and filenames `<stage>-<attempt>.json`. The snapshot attempt must match
the execution attempt; a snapshot from another attempt must not certify it.

Launch records use `{"receipts": [...]}`. Every receipt carries `stage`,
`attempt`, the declared `manager` and `policy_sha256`. The receipt population
must match all executed attempts exactly. Direct or different-manager receipts,
missing or duplicate receipts, and mismatched policy hashes FAIL. Guard records
carry the same `policy_sha256`, `complete: true` and a nonempty `commands` list.
Each command has explicit Boolean `allowed` and `within_policy`; an allowed
command outside policy FAILs. An incomplete guard census is NOT-CHECKABLE.
The check evaluates the supplied command-policy declarations.

Installability JSON has `distributions` rows with `name` and `version`. A supplied
public source has `public: true`, an HTTPS `url` without credentials and an
artifact `sha256`. A confirmed missing source has `public: false`; it FAILs
unless a checksum-bound `vendored` file or `public_tag` replacement is present.
A `public_tag` has HTTPS `url`, `tag` and artifact `sha256`. A missing source or
incomplete public pin is NOT-CHECKABLE. The requirements file accepts exact
named distribution pins, including lock hashes and markers; pip directives,
unpinned requirements and unresolved direct references FAIL. Every non-RAVEL
runtime distribution must appear at its recorded version. For vendored RAVEL,
supply `vendored_ravel` and retain both LICENSE and NOTICE. These are offline
comparisons of supplied evidence; they do not prove current network availability.

The invoked-software record has `executables` and `distributions` name lists.
The coverage record has `skills` rows with `kind` (`executable` or
`distribution`), `name` and `path`. Distribution names use standard normalized
spelling; executable names retain their supplied spelling. Requesters must
provide the complete invocation census. A name-to-skill mapping establishes
coverage presence; the check does not assess the skill's semantic adequacy.

Intermediate references have `artifacts` rows with `sha256` and `storage_path`.
If a row supplies an in-repository `path`, that path must not be tracked. The
check never fetches external storage. `segments` is the complete section list
accepted by `manuscript_build.page_census`: each row declares `id`, `section`,
`start`, `end` and Boolean `counted`, with native absolute-page labels in `aux`.

## Consumer handoff

`submission_conformance.check(repo, rules, rundirs=())` accepts a pack mapping or
JSON path and returns ordered `rules` rows containing `id`, `status`, `evidence`
and `fix_hint`, plus counts, HEAD and the evidence scope.
`render_markdown(report)` renders the same evidence. Inspection consumers and
submission exporters can use this interface without reimplementing checks.
Preserve NOT-CHECKABLE rows and apply the requester's policy for accepting them;
only `passed: true` means every supplied rule passed.

Existing prompt-audit builds supply the full-text and gap fields; exact-build
and instruction-receipt fields must arrive from their producers or a documented
supplied adapter. Manager/guard producers must provide complete policy-bound
records. Environment producers must bind retained snapshots to execution
attempts. Installability and skill-coverage sources must preserve reviewed
source identities. The registration fragment under
`src/ravel/data/submission/registration/` provides the shared-manifest and
knowledge-atlas handoff; it grants no launch or scientific acceptance authority.
