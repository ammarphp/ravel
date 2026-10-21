# Outputs and provenance

A controller run has two locations: a private run directory for scientific
files and a protected store for decisions and execution state. The run marker
connects them. Use `ravel status --run RUN_ID` to inspect a controller run and
`ravel drive --resume RUN_ID` to continue it.

## Controller records

| Record | What it establishes | Reader |
|---|---|---|
| `controller-run.json` | The run identity and its original directory | Controller entry and store |
| `request.txt` and intake records | Original question, input classification and derived requirements | Route planner |
| Store journal and blobs | Authenticated record sequence and content-addressed evidence | `ravel.controller.store` |
| Graph checkpoints | Saved graph/thread state and completed transitions | Controller graph and checkpoint backend |
| Execution manifest | Source, dependencies, interpreter, graph and checkpoint identities | Resume admission |
| Instruction packets and receipts | Exact sources delivered to a seat and its acknowledged duties | Instruction and obligation services |
| Plan and authority records | Reviewed scope, assumptions, budgets and operator/machine authority | Admission gates |
| Step and seat receipts | Dispatch identity, inputs, outputs, qualification and captured usage | Step graph and review custody |
| Obligation ledger | Pending, discharged and typed inapplicable requirements | Enforcing action and delivery sink |
| Judgment records | Action identity, evidence, findings and decision | Judgment graph |
| Batch-job journal | Submitted handles, observations, adopted outputs and cancellation | Batch observer and stop path |
| `delivery/RECEIPT.json` | Delivered artifact identities, outcome and qualifications | Result consumer |

The [architecture appendix](../architecture/safety.md) explains the trust
boundary. The store authenticates records outside workers' writable mounts;
the unconfined account owner remains part of the stated boundary.

## Scientific files

The operation's output contract names the authoritative paths. Common files
include `result.json`, `scan.json`, `exclusion.json`, `figures.json`, normalization
ledgers, fit diagnostics and acceptance certificates. Each is interpreted under
its own schema, units, domain and source bindings.

Legacy workflow runs also use `run_state.json`, `execution_state.json`,
`current_state.json`, `RESULT.md`, `DEVIATIONS.md` and check-in records.
`current_state.json` is a reconstructed view. Supervised execution retains
individual attempts under `logs/execution/`; reuse checks the command, source,
inputs, dependencies and output bytes.

See [run-directory layout](../workflow/run-directory.md#layout),
[durable execution](../workflow/reference/durable-execution.md) and
[scientific results](scientific-results.md).

## Reading a result

Read the outcome, qualifications and covered population before using a number.
Follow each quoted quantity to its machine artifact and input lineage.
Missing scan cells, bounded limits, failed fits, uncertain correlations and
unknown costs keep their explicit status. An exit code describes a command;
the [work outcome](../cli.md#work-command-outcomes) describes the study.

Presentation copies carry visible receipt references and qualification notices.
Scientific data preserves its bytes and travels with its hashed provenance
sidecar. The [run guide](../workflow/run-directory.md#labels-on-delivered-artifacts)
lists supported presentation formats.

## Export, share and restore

`ravel share group` and `ravel share public` create audience-labelled delivery
copies under operator authority. The source remains private. Public sharing
requires the run's frozen public classification.

`ravel operator export-run` snapshots a quiescent run and its store. A full
private bundle supports restoration; `--share-only` creates inspection evidence.
Restoration verifies the inventory, journal, checkpoints and authority history
at the original absolute run/store locations. Keep issuer-key backup separate.
Use the exact procedure in
[export and restore](../workflow/run-directory.md#export-and-restore).
