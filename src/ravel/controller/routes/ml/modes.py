"""Science-mode admission for the ML and manuscript modes: a vocabulary match grants nothing.

The mode descriptors (``data/mode_descriptors.json``) are a suggestion vocabulary. A plan that
names one of these modes is admitted only on positive evidence of all four parts of the mode's
contract, and this module never reads the descriptors:

1. **typed adapter**: the operation's signature names a ``science-mode`` implementation for
   exactly this mode, its module is installed and the mode is a registered science mode; a
   typed task the step carries names the same mode;
2. **executor**: the step's role is the mode's registered production role (``executors.json``);
3. **authority**: a current CHECK-IN 1 record of the authority service covers the plan digest;
4. **delivery contract**: the step declares required outputs and a mapped plan deliverable is
   produced by the step or by a step that depends on it.

The training and manuscript modes add their own structure (``ravel.controller.routes.ml`` and
``ravel.controller.routes.manuscript``). The staged training operations (``ml-stage-*``) are stages
of the ``ml-training`` mode: their typed adapter is the stage module their signature names, and a
dry stage before CHECK-IN 1 (dataset admission, feature definition) is authorized as the authority
service authorizes every dry effect, by the run's frozen operating mode. ``admit`` is the single
entry the governed step's preflight calls for an operation or a subgraph of these modes; an empty
list admits the step. Errors are dicts with a ``code`` (the hold reason), in the governed step's
error style.
"""
from __future__ import annotations

from importlib import util
from pathlib import Path

TRAINING = "ml-training"
INFERENCE = ("published-classifier", "classifier-inputs", "analysis-response-features")
MANUSCRIPT = "manuscript-build"
GOVERNED = (TRAINING, *INFERENCE, MANUSCRIPT)
# Registered graphs that run these modes as a ``subgraph`` step.
GRAPHS = {"ml.study": TRAINING, "manuscript.build": "manuscript.build"}
DATA = Path(__file__).resolve().parents[3] / "data"
SIGNATURES = DATA / "operation_signatures.json"


def signatures():
    from ravel.workflow.operation_registration import read_signatures
    return read_signatures(SIGNATURES)


def executor_table():
    from ravel.workflow import production_executor
    return production_executor.executors()


def science_modes():
    from ravel.workflow import science
    return tuple(science.MODES)


def governed(step: dict) -> str | None:
    """The governed mode a step runs (an operation of these modes, a stage of one, or one of their graphs)."""
    if type(step) is not dict:
        return None
    graph = step.get("graph") if type(step.get("graph")) is dict else {}
    if graph.get("id") in GRAPHS:
        return GRAPHS[graph["id"]]
    operation = step.get("operation")
    from ..manuscript import NOTE_OPERATIONS
    if operation in NOTE_OPERATIONS:
        return MANUSCRIPT
    from .training import STAGED_OPERATIONS
    if operation in STAGED_OPERATIONS:
        return TRAINING
    return operation if operation in GOVERNED else None


def _error(code, step, **detail):
    return {"code": code, "step": step.get("id") if type(step) is dict else None, **detail}


def unresolved_placeholders(value):
    from ..compiler import PLACEHOLDER
    if type(value) is str:
        return bool(PLACEHOLDER.search(value))
    if type(value) is dict:
        return any(unresolved_placeholders(v) for v in value.values())
    return type(value) in (list, tuple) and any(unresolved_placeholders(v) for v in value)


def adapter_errors(step, mode, *, table=None, modes=None):
    """Part 1: the typed adapter behind the mode."""
    table = signatures() if table is None else table
    signature = table.get(mode)
    if signature is None:
        return [_error("mode_signature_missing", step, operation=mode)]
    implementation = signature.get("implementation") or {}
    if implementation.get("kind") != "science-mode" or implementation.get("mode") != mode:
        return [_error("mode_adapter_untyped", step, operation=mode, implementation=implementation.get("kind"))]
    module = implementation.get("module")
    try:
        found = type(module) is str and module and util.find_spec(module) is not None
    except (ImportError, ValueError):
        found = False
    if not found:
        return [_error("mode_adapter_missing", step, operation=mode, module=module)]
    if mode not in (science_modes() if modes is None else modes):
        return [_error("mode_not_registered", step, operation=mode)]
    task = (step.get("parameters") or {}).get("task") if type(step.get("parameters")) is dict else None
    if task is not None and (type(task) is not dict or task.get("mode") != mode):
        return [_error("mode_task_mismatch", step, operation=mode,
                       named=task.get("mode") if type(task) is dict else None)]
    return []


def staged_adapter_errors(step, operation, *, table=None):
    """Part 1 for a staged stage: its signature runs the stage module as a command."""
    from .training import STAGE_MODULE
    from ..manuscript import NOTE_OPERATIONS
    if operation in NOTE_OPERATIONS:
        STAGE_MODULE = "ravel.controller.routes.manuscript.note"
    table = signatures() if table is None else table
    signature = table.get(operation)
    if signature is None:
        return [_error("mode_signature_missing", step, operation=operation)]
    implementation = signature.get("implementation") or {}
    if implementation.get("kind") != "command" or implementation.get("module") != STAGE_MODULE:
        return [_error("mode_adapter_untyped", step, operation=operation, implementation=implementation.get("kind"))]
    try:
        found = util.find_spec(STAGE_MODULE) is not None
    except (ImportError, ValueError):
        found = False
    if not found:
        return [_error("mode_adapter_missing", step, operation=operation, module=STAGE_MODULE)]
    return []


def executor_errors(step, mode, *, table=None):
    """Part 2: the registered production role runs the mode; no other role substitutes."""
    table = executor_table() if table is None else table
    required = (table.get("operations") or {}).get(mode)
    if required is None:
        return [_error("mode_executor_missing", step, operation=mode)]
    if step.get("role") != required:
        return [_error("mode_executor_mismatch", step, operation=mode, required=required, named=step.get("role"))]
    return []


def authority_errors(step, plan, authority):
    """Part 3: a current CHECK-IN 1 authority record for this plan digest."""
    if authority is None:
        return [_error("mode_authority_unavailable", step)]
    pins = {"plan_sha256": plan.get("sha256")}
    try:
        record = authority("approve_plan", pins)
    except Exception as exc:  # an authority question that fails never admits
        return [_error("mode_authority_unavailable", step, detail=str(exc)[:300])]
    if not record:
        return [_error("mode_authority_missing", step, pins=pins)]
    return []


def descendants(plan, step_id):
    """``step_id`` and every plan step that depends on it, directly or through others."""
    children = {}
    for row in plan.get("steps") or ():
        for parent in row.get("depends_on") or ():
            children.setdefault(parent, []).append(row.get("id"))
    found, queue = {step_id}, [step_id]
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in found:
                found.add(child)
                queue.append(child)
    return found


def ancestors(plan, step_id):
    """Every plan step ``step_id`` depends on, directly or through others (not the step itself)."""
    by_id = {row.get("id"): row for row in plan.get("steps") or () if type(row) is dict}
    found, queue = set(), [step_id]
    while queue:
        for parent in (by_id.get(queue.pop()) or {}).get("depends_on") or ():
            if parent not in found:
                found.add(parent)
                queue.append(parent)
    return found


def delivery_errors(step, plan):
    """Part 4: required outputs that a mapped deliverable is produced from."""
    if not any(type(o) is dict and o.get("required") for o in step.get("outputs") or ()):
        return [_error("mode_outputs_undeclared", step)]
    reach = descendants(plan, step.get("id"))
    mapped = [row for row in plan.get("deliverables") or ()
              if type(row) is dict and row.get("status") == "mapped" and row.get("step") in reach]
    if not mapped:
        return [_error("mode_delivery_contract_missing", step,
                       detail="no mapped deliverable is produced by this step or a step that depends on it")]
    return []


def admit(step: dict, context=None, *, plan: dict = None, authority=None, signature_table=None, executors=None, modes=None,
          prerequisites=None) -> list[dict]:
    """Why ``step`` of ``plan`` may not run its governed mode (empty when it may, or when it runs none).

    ``authority(kind, pins)`` returns the current authority record for ``kind`` covering
    ``pins`` or None (the authority service's ``current``). ``prerequisites`` overrides the
    training prerequisite probe (tests and the integrator's qualification only).
    A controller context additionally admits current adopted stage prerequisites and records
    the exact unblind action. The keyword-only plan interface remains a structural probe.
    """
    mode = governed(step)
    if mode is None:
        return []
    runtime = context is not None
    scope = {}
    if runtime:
        if type(context) is not dict:
            return [_error('mode_context_invalid', step)]
        if plan is not None and plan != context.get('plan'):
            return [_error('mode_context_invalid', step, detail='conflicting plans')]
        plan = context.get('plan')
        if type(plan) is not dict or type(plan.get('sha256')) is not str or not plan['sha256']:
            return [_error('mode_plan_digest_missing', step)]
        for name in ('pins', 'scope_pins'):
            supplied = context.get(name, {})
            if type(supplied) is not dict or any(k in scope and scope[k] != v for k, v in supplied.items()):
                return [_error('mode_authority_unavailable', step, detail='conflicting scope pins')]
            scope.update(supplied)
        resolver = authority or context.get('authority')
        if resolver is not None and not callable(resolver):
            return [_error('mode_authority_unavailable', step, detail='authority must be callable')]
        if resolver is None:
            from .staged import authority_service
            service = authority_service()
            store = context.get('store')
            if store is None:
                return [_error('mode_authority_unavailable', step, detail='controller store absent')]
            def resolver(kind, pins):
                if kind == 'approve_plan':
                    ci1, amendment = service.plan_authority(store, pins)
                    return amendment or ci1
                return service.current(store, kind, pins)
        def scoped_authority(kind, pins):
            if any(k in scope and scope[k] != v for k, v in pins.items()):
                raise ValueError('mode authority conflicts with context scope pins')
            return resolver(kind, {**scope, **pins})
        authority = scoped_authority
    if type(plan) is not dict or step.get("id") not in {row.get("id") for row in plan.get("steps") or ()
                                                       if type(row) is dict}:
        return [_error("mode_step_not_in_plan", step, operation=mode)]
    if runtime and step not in plan['steps']:
        return [_error('mode_step_not_in_plan', step, detail='step differs from the current plan')]
    from .. import manuscript
    from . import training
    errors = []
    if unresolved_placeholders(step):
        errors.append(_error('mode_unresolved_placeholder', step))
    stage = training.stage_of(step)
    if mode == TRAINING:
        errors += training.structure_errors(step, plan)
    elif mode in (MANUSCRIPT, "manuscript.build") or manuscript.is_note_stage(step):
        errors += manuscript.structure_errors(step, plan)
    elif step.get("kind") != "operate":
        errors.append(_error("mode_step_kind", step, operation=mode, kind=step.get("kind")))
    operation = TRAINING if mode == TRAINING else (MANUSCRIPT if mode == MANUSCRIPT else None)
    if mode in INFERENCE:
        operation = mode
    if stage is not None or manuscript.is_note_stage(step):
        errors += staged_adapter_errors(step, step["operation"], table=signature_table)
        errors += executor_errors(step, step["operation"], table=executors)
    elif operation is not None:
        errors += adapter_errors(step, operation, table=signature_table, modes=modes)
        errors += executor_errors(step, operation, table=executors)
    elif step.get("operation") is not None:
        errors.append(_error("mode_step_operation", step, operation=step.get("operation")))
    prepared = stage in training.PREPARE_STAGES and step.get("rung") in training.PREPARE_RUNGS
    if not prepared:
        errors += authority_errors(step, plan, authority)
    errors += delivery_errors(step, plan)
    if mode in INFERENCE:
        errors += training.inference_errors(step, plan)
    if runtime and not errors:
        if (stage is not None or manuscript.is_note_stage(step)) and (
                context.get('store') is None or not context.get('run_dir')):
            return [_error('mode_context_invalid', step, detail='staged admission needs store and run directory')]
        if stage is not None:
            from . import staged
            errors += staged.admit(step, context)
        elif manuscript.is_note_stage(step):
            from ..manuscript import staged
            errors += staged.admit(step, context)
    if mode == TRAINING and stage in (None, "evaluate"):
        errors += training.authority_errors(step, plan, authority)
    if mode == TRAINING and stage in (None, "train"):
        errors += training.prerequisite_errors(step, prerequisites)
    return errors


def observe(step, outcome, context):
    """Apply staged ending checks before a governed step outcome unlocks its dependents."""
    from . import staged, training
    from .. import manuscript
    if training.stage_of(step) is not None:
        problems = staged.step(step, outcome, context)
    elif manuscript.is_note_stage(step):
        from ..manuscript import staged as note
        problems = note.step(step, outcome, context)
    else:
        return outcome
    if problems and outcome.get('status') == 'completed':
        return {**outcome, 'status': 'failed', 'reason': 'staged_ending_refused', 'problems': problems}
    return outcome
