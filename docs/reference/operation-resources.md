# Non-event operation resources

An ordinary checked full stage can declare solver work separately from generated
events. Supply the same closed `operation_resources` object in the task contract,
endpoint plan and its sole selected stage, `execution.plan_stage`, and
`stage_supervisor.supervise`. Schema version 1 requires `kind: solver`, exactly
zero `generated_events`, positive integer `solver_evaluations` and a positive
finite `max_seconds`. Supply an explicit supervisor wall ceiling no larger than
that declaration. The matching cost estimate names solver evaluations and omits
the generation-specific `events_per_point` field.

The existing CHECK-IN 1 and applicable CHECK-IN 2/review gates remain in force.
The resource class comes from the approved task, so omitting it from a launch
context cannot turn solver work into legacy admission. The resource field enters
the stage fingerprint. The exact task/endpoint bytes are committed separately to
avoid a contract/plan hash cycle, and are checked freshly at launch, finish and
reuse. Frozen launch validation also checks the retained class, command, IO and
wall ceiling. Event-generation stages retain their positive-event requirement.

`solver_evaluations` is a declared source-operation count. The generic parent
enforces wall time and owns launched processes. It does not instrument arbitrary
native calls inside a worker. The source-bound worker must retain and independently
check its actual evaluation census. A prospective scientific-study schema 2 uses
its existing science approval and zero-new-event semantics instead of borrowing
this generic full-stage contract. No approval or scientific acceptance follows
from supplying a resource declaration.
