# Durable execution and recovery

Use the registered native execution plan for full simulation. Its stages declare commands, scientific inputs, outputs and parent stages. See [native pipeline](native-pipeline.md). To supervise an additional supported local stage directly:

```bash
python scripts/run.py ravel.workflow.stage_supervisor \
  --stage analysis --rundir RUN --cwd RUN --log logs/analysis.log \
  --input inputs/analysis-config.json --input output/events.hepmc \
  --output output/selected.json --depends-on pythia --resume \
  --kill-secs 1800 -- python path/to/analysis.py
```

Replace the example with the actual approved command and artifact paths. A generic supervisor provides execution integrity; it is not a substitute for the physics route, task approval or scientific output validator.

## What resume checks

The supervisor writes `execution_state.json` atomically and retains individual attempt records under `logs/execution/`. A successful process is reusable only if the command, working directory, executable/package source, declared inputs, runtime context, parent receipts and current outputs still match. Relevant supervisor environment settings and installed package versions are fingerprinted. External runtimes, dynamically linked libraries and external data still need explicit dependency or environment manifests in the stage's declared inputs. This is not an operating-system sandbox or a complete machine image.

Every changed parent invalidates its descendants. Changed output bytes also invalidate reuse. A zero exit code with missing, empty or malformed declared JSON output is a failed attempt. Input mutation during execution is rejected. Distinct stages cannot own overlapping output paths, and stage outputs cannot overwrite their declared inputs. Directory artifacts must not conceal symlinked content.

Do not mutate or delete a stage output after its receipt is written. Decompressing a generated event file is a separate stage that preserves the compressed original. Keep scratch process directories separate from the immutable scientific products used by downstream stages.

## Failure and interruption

The supervisor holds a per-stage process lock, runs the child in its own process group and terminates that group on timeout or interruption. Log silence is not a default stall signal because buffered scientific programs may remain healthy without printing. Set an explicit `--stall-secs` only when log updates are a valid progress contract for that program. A wall-time budget always remains.

Retrying retains the previous outputs, logs and failure record before creating a new attempt. After a killed supervisor, resume identifies an owned orphan using its recorded process identity and group before termination. A mismatched identity is held for reconciliation; the supervisor does not kill an unrelated process. Abrupt machine loss remains a recoverable interruption, not a successful receipt.

The lifecycle gate, result pack and scan harvester reject known stale execution evidence. Historical runs without a durable ledger remain explicitly outside stage-reuse certification. Archived attempts never count as current scientific outputs or unresolved live failures.

An unavailable applicable validator holds delivery and records a repairable gate failure. Repair the runtime or validator, rerun it and resolve the failure record with evidence. Do not relabel an unavailable check as a pass.

## Resume the agent as well as the processes

```bash
ravel status --rundir RUN --write
```

This rebuilds `current_state.json` from the current contract, run ledger, approvals, lifecycle gates and execution evidence. Read its next blocker and then open the relevant workflow step. The packet is a derived view and never grants permission to execute. Revalidate source artifacts before any launch or delivery. Never reinitialize an existing run to clear its state.

Run-state writers use revision checks and atomic replacement. Concurrent records retry conflicts instead of silently losing updates. An explicit forced reset preserves a prior state snapshot. The failure and recovery tests are in `tests/unit/test_execution_durability.py` and `tests/unit/test_current_state.py`.
