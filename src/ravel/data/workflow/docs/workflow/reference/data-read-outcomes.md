# Source-bound data acquisition and read outcomes

New ordinary ROOT acquisitions use `research_tools.prepare_data_acquisition`
(`research_tools` CLI operation `data-prepare`). Its explicit arguments are
`specification_pin`, `authority_pin`, `context_request_pin`, `base_dir`,
`output_dir`, `rundir` and a complete `quantity_bindings` map from original
context quantity IDs to original ROOT quantity IDs. All pins retain the actual
source bytes. This prepares an enriched ROOT task and the existing unapproved
ordinary science plan. Ordinary approval and execution remain separate.

The acquisition authority is a schema-1 `data-acquisition-source-authority`
document with `original_goal_sha256` and one ordered `sources` row per original
sample/member. Each row names `sample`, `member`, `role`, `availability`,
`acquisition_source`, `version`, `identity_authority` and nonempty `provenance`
pins. Roles are `observed`, `supplied_mc`, `generated_simulation`, `calibration`
or `software_fixture`. Availability is `supplied` or `missing`. The identity
authority must equal the original member checksum authority; original sample
kind, schema, branch units, blinding and signed full-population normalization
prevail. These are documentary source bindings. Hashes do not prove observed
provenance, detector truth, actor identity or server immutability.

Missing acquisitions return a prepared original unresolved context and an
`acquisition_missing` plan blocker, without making observations or consuming a
run. A separate generated-simulation acquisition has its own source role and
ordinary experiment. It cannot complete a missing observed-data obligation.
The preparation directory must have an existing ordinary parent. Source pins in
the relocated ordinary specification must resolve identically; inherited relative
pins requiring another base are refused instead of guessed.

The existing approved `root_stream.run` reads the original cohort, emits
`<destination>/native/read-outcomes.json`, and binds it through the existing complete native
census/publication Guard. Each original member remains present with its expected
entries, attempted intervals, remaining interval, role and reason. States are
`read_complete`, `read_partial`, `read_failed` and `acquisition_missing`. Full
original quantities, bin contracts, units, transform/runtime/source pins and
normalization survive failures. Partial moments are neither synthesized nor
renormalized. A complete read is distinct from independent statistical or
physics qualification. Ending input drift still fails the existing strict Guard;
this operation does not publish a qualified record from stale source custody.

The complete record is machine-only, preserving original DATA blinding. Public
`read_summary` contains roles, state and original quantity dispositions, without
DATA entry counts, intervals, identities or protected-region values. The actual
native request remains the full reader/runtime source binding.

Use `research_tools.data_result_context` (CLI `data-result-context`) with
`context_pin`, `result_pin`, `base_dir`, `artifact_id`, `attempt_id`, `question`
and `next_experiment`. Every newly prepared quantity carries `read_requirement`
with the original contract pin, `quantity_id`, allowed original `roles`, and
`purpose: original_quantity`. Ingestion verifies the selected original ordinary
attempt, launch, source/runtime and publication closure before numerical checks
can complete the quantity. An arbitrary same-shaped array or caller success flag
cannot supply a ROOT read outcome. Legacy directly authored tasks and context
schemas remain usable; a typed result cannot bypass its original read requirement.

An explicitly separate requirement with `purpose: partial_diagnostic` can use
valid retained failed/partial diagnostics. Its read check reports
`original_scientific_obligation_complete: false`; it does not complete the
original acquisition. Existing failed ordinary attempts may lack a committed
output snapshot. Their actual terminal token, original input/runtime, launch and
reader Guard are checked, while that output-snapshot limitation remains explicit.
No success/review vote or scientific acceptance is inferred.

This first finite implementation targets original full schema-1 ROOT acquisitions.
Partitioned execution/merged data retain their separate original master/group
contracts; no per-partition read prefix or independent-group law is inferred here.
Actual native, source-provenance, data-access and physics qualification are pending.
The authored software controls use explicitly inert readers/runtime/authorization
stand-ins. Their execution is root-controlled and is not a data-read experiment.
