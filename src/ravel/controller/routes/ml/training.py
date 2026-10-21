"""Dedicated ML training: only on a training route, with its own authority and prerequisites (R12).

Inference with a published or supplied classifier is an ordinary science-mode operation.
Training is separate work with its own prerequisites (``docs/workflow/start.md``): an inference
request, or a worker that asks for training while serving one, never authorizes it.

Training runs in one of two governed forms, never as the atomic ``ml-training`` operation (it opens
test data inside the same process that trains):

- **Staged** (the ``ml.training`` route): typed ``ml-stage-*`` operate steps, each one confined launch
  of ``ravel.workflow.ml_stages`` (admit, features, train, evaluate, card, review). A full training
  launch depends on a training smoke waypoint of the same plan, so its effect authorization needs
  CHECK-IN 1 and a CHECK-IN 2 GO bound to the executed smoke (the authority service,
  ``authorize_effect``). Only the one evaluation step reads the withheld partition: that read is an
  unblinding, an R3 step that also needs its own R3 authority bound to the plan, the step and its operation.
- **The ``ml.study`` subgraph** (method studies the judgment graph plans): its stages keep the
  confirmation split sealed until its one charged read; as one subgraph step without a waypoint it
  needs its own consequential-action (R3) authority bound to the plan digest, the step and the
  operation, in addition to CHECK-IN 1.

Both are planned only by the training route or the judgment graph; a plan compiled from the inference
route never contains them. The prerequisite is the staged executor itself: when it is not installed,
a training step holds with the same typed reason the ``ml.study`` graph raises without it.
"""
from __future__ import annotations

from .modes import TRAINING, _error

STUDY_GRAPH = "ml.study"
TRAINING_ROUTES = ("ml.training", "judgment")
INFERENCE_ROUTES = ("ml.inference",)
# The staged executor interface ``ml.study`` calls (``graphs/ml_study.py``): pinned stages, the
# binding, supervised training, arm selection, evaluator-only confirmation and attribution.
STAGED_INTERFACE = ("stage", "binding", "train", "select", "confirm", "attribute")
PREREQUISITE_HOLD = "awaits the staged ML executor interface"
PROVIDER = "ravel.workflow.ml_executor"
# The staged route's operations: one confined launch of the stage module each.
STAGE_MODULE = "ravel.workflow.ml_stages"
STAGES = ("admit", "features", "train", "evaluate", "card", "review")
STAGED_OPERATIONS = tuple(f"ml-stage-{stage}" for stage in STAGES)
WITHHELD = "outputs/partitions/test.npz"
PREPARE_STAGES = ("admit", "features")
PREPARE_RUNGS = (None, "none", "dry")
# The one read of the withheld partition is unblinding: always R3, never lowered by a plan.
UNBLIND_CLASS = "R3"


def stage_of(step):
    operation = step.get("operation") if type(step) is dict else None
    return operation.removeprefix("ml-stage-") if operation in STAGED_OPERATIONS else None


def _route(plan):
    return (plan.get("route") or {}).get("id") if type(plan.get("route")) is dict else None


def _argv(step):
    launch = (step.get("parameters") or {}).get("launch") if type(step.get("parameters")) is dict else None
    argv = launch.get("argv") if type(launch) is dict else None
    return argv if type(argv) is list else []


def reads_withheld(step):
    """True when the step consumes the withheld partition (an input or a declared launch read)."""
    inputs = [str(row.get("artifact", "")) for row in step.get("inputs") or () if type(row) is dict]
    launch = (step.get("parameters") or {}).get("launch") if type(step.get("parameters")) is dict else None
    reads = [str(r) for r in (launch or {}).get("reads") or ()] if type(launch) is dict else []
    argv = [str(a) for a in _argv(step)]
    return (any(a.endswith(":" + WITHHELD) for a in inputs) or any(r.endswith("partitions/test.npz") for r in reads)
            or any(a.endswith("/" + WITHHELD) for a in argv))


def _steps(plan):
    return {row["id"]: row for row in plan.get("steps") or () if type(row) is dict and type(row.get("id")) is str}


def staged_errors(step, plan):
    """Structure of one staged ML step; empty when the plan may run it."""
    from .modes import ancestors
    stage = stage_of(step)
    errors = []
    if _route(plan) not in TRAINING_ROUTES:
        errors.append(_error("ml_training_outside_training_route", step, route=_route(plan),
                             detail="an inference or other fixed route does not authorize training"))
    if step.get("kind") != "operate":
        errors.append(_error("ml_stage_kind", step, kind=step.get("kind")))
    argv = _argv(step)
    prefix_ok = len(argv) >= 5 and argv[1:5] == ["-I", "-m", STAGE_MODULE, stage]
    if not prefix_ok or (step.get("parameters") or {}).get("ml_stage") != stage:
        errors.append(_error("ml_stage_launch_mismatch", step, operation=step.get("operation"),
                             detail=f"the launch runs {STAGE_MODULE} {stage} and nothing else"))
    if reads_withheld(step) and stage != "evaluate":
        errors.append(_error("ml_withheld_partition_read", step, stage=stage,
                             detail="only the evaluation reads the withheld partition"))
    launch = (step.get("parameters") or {}).get("launch") or {}
    if stage != "admit" and (launch.get("reads") or "--dataset" in argv or "--dataset-sha256" in argv):
        errors.append(_error("ml_stage_excess_reads", step, detail="only admission can read the supplied dataset; "
                             "other stages read their committed inputs only"))
    if not any(o.get("path") == "outputs/ml/receipt.json" and o.get("required") is True
               for o in step.get("outputs") or ()):
        errors.append(_error("ml_stage_receipt_undeclared", step))
    smoke = "--smoke" in argv
    if smoke and stage != "train":
        errors.append(_error("ml_stage_launch_mismatch", step, detail="only the training stage has a smoke rung"))
    steps = _steps(plan)
    above = [steps[s] for s in ancestors(plan, step.get("id")) if s in steps]
    if stage in PREPARE_STAGES and step.get("rung") not in PREPARE_RUNGS:
        errors.append(_error("ml_stage_rung", step, rung=step.get("rung"), detail="admission and feature definition "
                             "are dry stages"))
    if stage == "train":
        if smoke and (step.get("rung") != "smoke" or step.get("waypoint") is not True):
            errors.append(_error("ml_training_smoke_not_waypoint", step, rung=step.get("rung"),
                                 detail="the training smoke is a smoke-rung waypoint"))
        if not smoke:
            if step.get("rung") != "full":
                errors.append(_error("ml_stage_rung", step, rung=step.get("rung"), detail="the training launch is full"))
            if not any(stage_of(row) == "train" and "--smoke" in _argv(row) and row.get("waypoint") is True
                       for row in above):
                errors.append(_error("ml_training_without_smoke", step, detail="a full training launch follows a "
                                     "training smoke waypoint, so its GO is bound to executed evidence"))
    if stage == "evaluate":
        if step.get("rung") != "full":
            errors.append(_error("ml_stage_rung", step, rung=step.get("rung"), detail="the evaluation is full"))
        if step.get("consequence_class") != UNBLIND_CLASS:
            errors.append(_error("ml_unblind_class_lowered", step, consequence_class=step.get("consequence_class"),
                                 detail="reading the withheld partition is unblinding, always R3"))
        if not any(stage_of(row) == "train" and "--smoke" not in _argv(row) for row in above):
            errors.append(_error("ml_evaluation_without_training", step,
                                 detail="the evaluation follows the full training it evaluates"))
    if stage in ("features", "train", "evaluate", "card", "review") and not any(
            stage_of(row) == "admit" for row in above):
        errors.append(_error("ml_stage_without_admission", step, detail="every stage follows the dataset admission"))
    return errors


def staged_plan_errors(plan):
    """Plan-level: at most one step reads the withheld partition, and it is the evaluation."""
    errors = []
    readers = [row for row in _steps(plan).values() if reads_withheld(row)]
    for row in readers:
        if stage_of(row) != "evaluate":
            errors.append(_error("ml_withheld_partition_read", row, detail="only the evaluation reads the withheld "
                                 "partition"))
    evaluations = [row for row in readers if stage_of(row) == "evaluate"]
    if len(evaluations) > 1:
        errors.append(_error("ml_test_once_violated", evaluations[1], detail="the withheld partition is read once"))
    return errors


def structure_errors(step, plan):
    if stage_of(step) is not None:
        return staged_errors(step, plan)
    errors = []
    graph = step.get("graph") if type(step.get("graph")) is dict else {}
    if step.get("kind") != "subgraph" or graph.get("id") != STUDY_GRAPH:
        errors.append(_error("ml_training_atomic_refused", step, operation=TRAINING,
                             detail="training runs as staged launches or the ml.study subgraph; the atomic operation "
                                    "opens test data"))
    if step.get("operation") not in (None, TRAINING):
        errors.append(_error("ml_training_operation_mismatch", step, operation=step.get("operation")))
    route = _route(plan)
    if route not in TRAINING_ROUTES:
        errors.append(_error("ml_training_outside_training_route", step, route=route,
                             detail="an inference or other fixed route does not authorize training"))
    return errors


def authority_errors(step, plan, authority):
    """Own R3 authority bound to the plan digest, this step and the operation: the ``ml.study`` subgraph's,
    and the staged evaluation's (the one read of the withheld partition, an unblinding)."""
    unblind = stage_of(step) == "evaluate"
    code = "ml_unblind_authority_missing" if unblind else "ml_training_authority_missing"
    if authority is None:
        return [_error(code, step, detail="no authority service")]
    pins = {"plan_sha256": plan.get("sha256"), "step": step.get("id"),
            "operation": step.get("operation") if unblind else TRAINING}
    try:
        record = authority("r3_action", pins)
    except Exception as exc:
        return [_error(code, step, detail=str(exc)[:300])]
    if not record:
        return [_error(code, step, pins=pins,
                       detail="reading the withheld partition needs its own R3 authority beyond CHECK-IN 1 and the "
                              "smoke GO" if unblind else "dedicated training needs its own R3 authority beyond "
                                                         "CHECK-IN 1")]
    return []


def prerequisites(provider=None, *, profile="staged") -> list[dict]:
    """The training prerequisites that are not met (empty when training may start)."""
    from importlib import import_module
    if provider is None:
        try:
            provider = import_module(PROVIDER)
            import_module(STAGE_MODULE)
        except ImportError as exc:
            return [{"id": "training_provider", "reason": f"{PROVIDER} is not installed: {exc}"[:300],
                     "hold": PREREQUISITE_HOLD}]
    if profile == "study" and callable(getattr(provider, "prerequisites", None)):
        return provider.prerequisites(profile="study")
    interface = ("run_step",) if provider is not None and getattr(provider, "__name__", "") == PROVIDER else STAGED_INTERFACE
    missing = [name for name in interface if not callable(getattr(provider, name, None))]
    if missing:
        return [{"id": "staged_ml_executor", "reason": PREREQUISITE_HOLD, "missing": missing,
                 "provider": getattr(provider, "__name__", None)}]
    return []


def prerequisite_errors(step, override=None):
    missing = prerequisites(profile="staged" if stage_of(step) is not None else "study") if override is None else list(override)
    if missing:
        return [_error("ml_training_prerequisites_unmet", step, hold=PREREQUISITE_HOLD, missing=missing)]
    return []


def inference_errors(step, plan):
    """Inference never carries training: no training effect, parameters or graph ride along."""
    errors = []
    parameters = step.get("parameters") if type(step.get("parameters")) is dict else {}
    task = parameters.get("task") if type(parameters.get("task")) is dict else {}
    if "runs_authored_code" in (parameters.get("effects") or ()) or task.get("train") or task.get("training"):
        errors.append(_error("ml_inference_requests_training", step, operation=step.get("operation"),
                             detail="inference admits no training; plan training separately"))
    return errors
