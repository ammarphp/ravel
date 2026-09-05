# Independent adversarial execution review

Reviewed the concurrent working tree descending from source `8d8b4b5`. This is a read-only review of the execution/native implementation authored by other agents. Root subsequently requested separate author repairs to my own typed-pack/projection code; those repairs are not independent findings in this report. No physics generation or external installations were performed.

## Confirmed findings

### P1 — A succeeded stage can still have a live descendant writing its output

Reviewed path: `src/ravel/workflow/stage_supervisor.py:170–206` and `src/ravel/workflow/execution.py:300–323`. The supervisor waits for its direct `Popen` process, then emits success and a content receipt. It does not require the owned process group to be quiescent. Orphan recovery at `stage_supervisor.py:105–126` also tests the old leader PID, so a dead leader with surviving descendants is not the covered recovery case.

The real subprocess probe writes `{}` to `result.json`, starts a child that sleeps two seconds before changing it, and exits zero. Immediately after supervision returns, the observed state is `return_code=0`, `receipt_status=succeeded`, `validate_execution=[]`, and `descendant_live=true`. The descendant later changes the output, at which point validation detects `stage fit outputs changed`. Detection after the write is a useful control, but there was a false-success window while an owned writer remained active. A retry can also overlap that old writer.

Required fix: account for the owned process group before declaring terminal success and during interrupted-attempt recovery. Remaining writers must be waited for within the stage deadline or terminated with a recorded failure; do not silently label completion. Preserve process ownership checks before signaling. Root has been notified and is implementing this repair.

### P1 — Log paths bypass artifact ownership and can replace scientific outputs

Reviewed path: `stage_supervisor.py:151–171`; `execution.py:241–256`, `execution.py:283–286`. Artifact reservation compares only the declared `outputs`. The log is resolved as a writable path but is neither checked against declared inputs nor reserved against other stage outputs/logs and workflow control records.

Positive control: stage `fit` writes and owns `result.json`, returns zero, and validates cleanly. Adversary: another stage uses `logrel='result.json'`, emits a normal log line, and writes its distinct `other.json` output. It also returns zero. `result.json` now contains `overwritten by a log\n`; the first receipt subsequently fails. The previous JSON was preserved under the second stage's `prior.log`, so this probe did not lose its bytes, but the current scientific output was stolen through a field outside the ownership model.

Required fix: validate and reserve log paths alongside all output paths, reject overlap with declared inputs, execution/workflow/approval records, and other stages' scientific outputs or logs. Perform rejection before archiving or opening any file. Root has been notified and is implementing this repair.

### P1 — Canonical native/module launch commands bypass the existing approval hook

Reviewed path: `.claude/hooks/pretooluse-bash.sh:28–72`, `src/ravel/physics/native_pipeline.py:444–513`, `src/ravel/workflow/scan_orchestrator.py:674–749` (native agent is modifying these lines). The hook recognizes old script basenames, while the new executor and scan dispatch use Python module names. The executor itself did not verify approval before execution.

Actual hook tests used the same session-scoped smoke contract with no approval:

| Command form | Observed hook exit |
|---|---:|
| `bash native/scripts/run-pipeline-native.sh ...` | 2, blocked as unapproved |
| `python src/ravel/workflow/scan_orchestrator.py launch scan --go` | 2, blocked as unapproved |
| `python scripts/run.py ravel.physics.native_pipeline run ...` | 0, allowed |
| `python -m ravel.physics.native_pipeline run ...` | 0, allowed |
| `python scripts/run.py ravel.workflow.scan_orchestrator launch scan --go` | 0, allowed |

No listed command was executed; only the real hook was exercised. Static inspection confirms the allowed new commands reached execution without an equivalent internal approval check. This is separate from the acknowledged lack of independent human authentication.

Required fix: enforce current contract/approval/scope in the actual native executor and scan control plane, and recognize canonical script-launcher/module invocation forms in the hook without blocking help/dry-plan controls. Bind the launched plan's scope and inputs rather than treating `compute_authorized=false` as an inert annotation. Root assigned the executor repair to the native agent.

### P1 — The `c1n2-wz` adapter accepts a different, even charge-inconsistent decay topology

Reviewed path: `src/ravel/physics/native_pipeline.py:131–175`, especially the parent branching-row check at `:159–164`. It checks finite widths/branching fractions and an LSP in the daughters, but not the promised W/Z daughters or charge assignments.

Positive control: the existing explicit-card test fixture has `n2 -> LSP + Z` and `x1+ -> LSP + W+`. After replacing both boson PDGs with 22, `build_execution_plan` still succeeds and declares `model='c1n2-wz'`. Its charged parent now decays only to neutral LSP plus photon. No engine was run.

Required fix: either enforce the exact registered simplified-model decay conventions, including signs where charge matters, or route the input to a separately named broader capability with unresolved model identification. A changed topology must not retain the WZ model label. This bounded validation repair was sent to the native agent.

### P2 — Normalization reader accepts internally contradictory provenance metadata

Reviewed path: `src/ravel/physics/native_normalization.py:167–181`. The reader checks headline multiplication and the hashes of whatever source files are listed, but does not reconcile the source roles or recorded generation rate.

The probe supplies a nonempty arbitrary file with a valid SHA-256 and a record containing `generation.cross_section_pb=2`, `cross_section_pb=200`, `kfactor=.8`, and `applied_cross_section_pb=160`. `load_normalization` accepts it. Thus even an explicit contradiction is accepted, and an arbitrary hashed file can stand in for the LHE/shower evidence. The normal producer's stronger checks and the durable ledger's detection of post-emission output edits limit this in a fully supervised pipeline; they do not make the standalone loader validate what its accepted record claims.

Required fix: use an exact schema with mandatory source roles, compare all rate/event/weight summaries, and recompute the bounded normalization from those declared sources where it is being relied upon. At minimum reject contradictory generation/headline evidence and malformed count/Boolean fields. Sent to native agent for repair or an explicit scope boundary.

### P2 — Phantom-job check still confuses recent output with a running process

Reviewed path: `src/ravel/workflow/stop_dispatch.py:170–202`. A newly written log in `compute_launched` is sufficient to accept the prose claim that a simulation is running. The probe starts no child process, creates `recent.log`, and calls `branch_phantom` on “The simulation is running in the background.” It returns `(False, '')`, allowing the claim.

A recent log is useful evidence that work happened, but it does not establish current liveness. For durable jobs, prefer validated live supervisor/child ownership from receipts; distinguish running, recently completed, failed, and stale. The legacy no-ledger fallback should remain explicitly heuristic. This is a remaining behavioral-control limitation, not a demonstrated numerical-result bypass.

## Reproducers and outputs

- `<review-workdir>/ravel-execution-review-probes.py` and `.json`: real descendant, cross-stage log ownership, and phantom-message probes.
- `<review-workdir>/ravel-native-review-probes.py` and `.json`: actual approval-hook paired controls, WZ topology substitution, and contradictory normalization reader.

The scripts create isolated temporary fixtures and retain only their machine-readable outputs. The native script uses existing unit-fixture builders, not external physics engines. JSON output records correspond to the first observed failures before owner repairs. Do not overwrite these observations with repaired results; save a separate verification file.

## Areas inspected without an additional confirmed defect

- `state_io.py` serializes before atomic replacement, fsyncs file and parent directory, and rejects duplicate/nonfinite JSON. `workflow_state.write_state` compares revisions under a file lock and archives forced replacements. The existing real twelve-process append test is a meaningful control for lost updates.
- `execution.py` binds command, implementation files, runtime identity, input bytes, parent receipts and output bytes. Mutation of a recorded dependency is detected transitively. Existing directory-overlap/symlink checks are useful controls; they did not cover logs, which produced the finding above.
- `current_state.py` re-derives lifecycle/approval/execution state and labels the packet a view. It does not trust an earlier green `current_state.json`; the implementation rechecks contract/run-state hashes after evaluation. It is not a transactionally isolated snapshot of all external files, and executors must still revalidate before action.
- Native capability dispatch rejects mismatched production families, unsupported detector/statistics adapters, absent correction factors, unsupported merging, and scan/card mass disagreement. Inclusive discovery regions remain yields-only, avoiding an invented independent likelihood.
- The native agent's final changes isolate mutable MadGraph process directories per attempt and use stable declared LHE outputs. Durable babysitter branches stop deleting receipt artifacts or resetting failed status records. I did not run a fresh real MadGraph/Delphes campaign; the agent's subprocess stubs test control flow, not physics fidelity.

## Verification requirements after repair

Run the retained adversaries with positive controls after the source freezes. Add regressions for dead group leaders with live descendants, log/input/control/output collisions, canonical module commands with no/stale/wrong-rung approval, exact WZ daughter substitutions, and malformed normalization source roles. Then run the root source/public/package suite on the frozen tree. No new detector campaign is required to establish these software-control repairs, and passing them must not be described as detector or statistical calibration.
