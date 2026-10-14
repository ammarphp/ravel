# Prospective review for bounded scientific studies

Version 2 scientific studies bind a real science plan, specification, CHECK-IN 1,
prospective review policy and science approval. They use the existing three-role
review journal. No native compute approval or native waypoint manifest is created.
The first supervised calculation produces evidence. Its successful execution stays
`PENDING` until the three role decisions accept a declared claim scope. Scripted
CHECK-IN 1 assent does not constitute expert review.

The original version 1 route remains available for existing supplied-event,
quantity, measurement and domain tasks. New event contrasts, analysis IR, supplied
routine builds, execution of reviewed built Rivet plugins, statistical models,
published likelihood inversions and fixed-phase-space model probes require
version 2 before any worker can execute.

## Specification

Keep the existing `mode`, `source`, `assumptions`, `max_seconds`, `approval_mode`
and `task` fields. Set `schema_version` to `2` and add `max_attempts` plus the
following `review_policy` wrapper. This zero-redo example authorizes a narrower
diagnostic delivery when scientific agreement fails while integrity passes.

```json
{
  "schema_version": 1,
  "policy": {
    "schema_version": 1,
    "actors": {
      "proposer": "producer",
      "executor": "producer",
      "physics_critic": "critic",
      "skeptical_verifier": "verifier",
      "physics_decider": "decider"
    },
    "max_redos": 0,
    "allowed_changed_paths": [],
    "allowed_stages": ["science"],
    "required_checks": [
      {"id": "integrity", "kind": "integrity"},
      {"id": "scientific", "kind": "scientific"}
    ],
    "claim_scopes": {
      "diagnostic": {"checks": ["integrity"], "actions": ["delivery", "reuse"]},
      "supported": {"checks": ["integrity", "scientific"], "actions": ["delivery", "reuse"]}
    }
  },
  "correction_contract": {"task_fields": [], "input_slots": []}
}
```

Set top-level `max_attempts` to exactly `1 + policy.max_redos`. No automatic retry
is granted. Policy actors, checks and claim scopes use the strict existing
[scientific-review contract](physics-review.md). Every scope includes every
integrity check. A negative scientific diagnostic can be accepted in a narrower
initial scope. A failed inherited defect recheck remains unresolved under every
scope.

`ravel plan --rundir <new-run> --spec <spec.json>` copies the policy to
`inputs/physics_review_policy.json`. `ravel approve` binds the exact bytes of
`inputs/science-plan.json`, `inputs/science.json`, `inputs/checkin1.json` and that
policy. The receipt is `inputs/science-approval.json`. Approval cannot be replaced
or retrospectively attached to a version 1 study.

## Execution and review

`ravel run --rundir <run>` executes the first bounded worker. Attempt 1 writes to
`outputs/attempt-1` and `logs/science-worker-1.log`. The worker checks the selected
supervised attempt, approved source and input identities, and original hard time
ceiling. The launch journal retains the real science approval and exact recipe.

Successful computation returns zero while `ravel status --rundir <run> --write`
reports actionable `PENDING` review. Computation failure, stale input bytes or
invalid integrity evidence remain failures. Adapter machine postconditions do not
automatically pass arbitrary scientific checks declared in the policy.

Prepare a located check-results document in the existing review schema. Cite the
current successful receipt's `attempt_id` and actual raw artifacts in the selected
output directory. Then call `physics_review.open_cycle` or its `open` CLI with:

- `effective_settings` from `science.review_effective_settings(run)`
- `stage_receipts` containing the current science attempt's `attempt_record`
- `check_results` naming the explicit checked-evidence document

The science adapter supplies the actual worker CHECK-IN 2 and individually pinned
output artifacts. Role packets can therefore inspect raw arithmetic and retained
settings. Follow the existing critic, verifier and decider process. Delivery and
`--resume` reuse require three compatible acceptances for the same declared scope.
Acceptance records declared actor separation, without authenticating identity.

A material scientific defect discovered after acceptance uses the
[late-evidence hold](physics-review.md#material-evidence-discovered-after-acceptance).
The original registered critic or verifier owns the located finding; the original
registered decider binds its exact context digest and records the hold. This
preserves the accepted outputs and votes while refusing future delivery, reuse,
bulk and correction admission. Source or input-inventory drift can independently
block those actions. The hold grants no attempt or redo, and this cycle cannot be
reopened or lifted through it. A replacement scientific claim needs a separately
approved study with explicit parent finding, fresh evidence and fresh acceptance;
the original held run remains preserved.

## Numeric corrections

The initial contract may prospectively identify existing finite numeric leaves.
`task_fields` contains unescaped JSON pointers into the task. For example,
`/config/target_ctau/value` permits changing that value while retaining its unit,
the operation and every other task field. Mode, backend, domain, executable,
runtime, process, topology, resource ceilings and nonnumeric structure stay fixed.

An input slot can copy a supplied JSON document before approval:

```json
{
  "task_path": "/config/data_file",
  "run_path": "inputs/science-mutable/data.json",
  "fields": ["/numeric_parameter"]
}
```

The slot must identify an actual regular file in the original scientific input
inventory. The original file stays unchanged and bound. Only named numeric leaves
in its run-local copy may change. Nested file references in a copied document must
remain resolvable from its copied location. New external files, changed units,
new structures, string edits and undeclared numeric fields require a new study.

Set `policy.allowed_changed_paths` to exactly the copied slot paths plus
`inputs/science-execution-task.json` when `task_fields` is nonempty. Set
`allowed_stages` to `["science"]`. Review the copied settings in the initial
cycle so subsequent findings refer to actual effective paths.

After a send-back, prepare the allowed changes on those copies. Write a correction
request with exact `actor_id`, `changed_paths` and `recheck_checks`, optionally a
smaller `max_seconds`. Then run:

```bash
ravel science-correct --rundir <run> --request correction-request.json
ravel run --rundir <run>
```

`science-correct` materializes `inputs/science-correction-N.json` before asking the
existing decider admission function to bind its exact settings and stage command.
The command contains that derivative plan's byte digest. The original plan,
specification and approval stay unchanged. Unadmitted drafts may be revised, with
prior drafts retained. Once admitted, changed plan bytes invalidate the command.

Admission consumes the prospective redo even if execution fails. The same logical
`science` stage receives a new receipt and writes to `outputs/attempt-(N+1)` and a
distinct worker log. Old output directories and receipt records remain available.
Successful repaired execution does not close a finding. Open the successor cycle
with the correction ID, fresh receipt and located rechecks, then collect fresh
role decisions. Exhausted budgets, unsupported structural repairs and stopped
reviews cannot be reset by deleting a current-state or attempt file.
