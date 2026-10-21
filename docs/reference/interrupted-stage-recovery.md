# Interrupted stage recovery

A recorded RUNNING attempt can outlive its supervisor. Host recovery checks the child PID, its start identity and recorded process group. Descendants that start another group or session require independent containment evidence.

The supervisor records that interruption as **failed, exit 130**, after the existing host-before-guest barrier. It preserves the exact complete preterminal record in `logs/execution/<stage>/<attempt_id>/interrupted-preterminal.json`, bounds that metadata read to 64 MiB, rejects linked/changed metadata, and binds its hash and size in `interrupted_finalization`. The failed record keeps `requires_recovery: true` and `descendant_containment: not_established`. No scientific output snapshot or success receipt is generated. Partial files stay in place; the original attempt ID, original scientific diagnostics, charged attempt token and attempt journal remain intact.

`stage_supervisor.recover_previous_attempt(rundir, stage, grace=...)` owns the existing stage lock and performs recovery only. `science.run(..., resume=True)` uses this barrier before any current plan check. Repeated recovery of the new held failure verifies its preserved snapshot and raises again. An empty group or a changed cleanup Boolean must not clear this marker. A missing recorded child, unreadable/reused identity, wrong group, unknown census or unresolved guest also blocks launch; those observations do not receive the new absence-based negative-finalization classification. Existing verified live-owned group cleanup and legacy already-terminal failed records retain their scoped behavior.

A known owned guest is still inspected after host custody fails. Host descendants require their own containment evidence in addition to a stopped-guest observation. Conversely, unresolved guest identity/recovery prevents the new failure transition. The existing live host fence, saved job/approval bindings, exact CID/name/image/label checks and guest cleanup reserve remain unchanged.

## Operator recovery

Keep the run held, inspect the retained preterminal snapshot and independently retained outer supervision evidence, and account for **all** known escaped groups and guests. Do not delete the state, token, marker or snapshot to resume. Root machine recovery requires authorized operational action and retains separate human or physicist review.

A concrete recovery needs independent review of complete launch lineage and containment, exact current ledger/attempt/preterminal pins, launch and supervision source pins, process start identities and parent/group/session transitions for every observed descendant. It also needs a fresh fence observation for every owned group and exact guest identities with producer-before-guest closure. Retain the hold for unknown, reused, live or unobservable populations.

Ordinary accepted reuse or an admitted correction supplies separate authority for a spent science attempt. Preserve the interrupted attempt's original records and scientific diagnostics.
