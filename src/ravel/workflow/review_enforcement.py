"""Shared review checks at execution, reuse and delivery boundaries."""
from pathlib import Path

from . import physics_review, execution
from .state_io import read_json


def required(root, *, _session=None):
    """Legacy records stay inspectable; removing a live review marker never waives it."""
    root = Path(root)
    if (root / physics_review.POLICY).exists() or physics_review.active(root, _session=_session):
        return True
    path = root / "inputs/checkin2_go.json"
    if path.exists():
        try:
            return read_json(path).get("schema_version", 0) >= 3
        except (OSError, ValueError, TypeError, AttributeError):
            return True
    return False


def delivery_errors(root, *, _session=None):
    return physics_review.gate_errors(root, "delivery", _session=_session) if required(root, _session=_session) else []


def before_stage(root, stage, command, inputs, outputs, depends_on, cwd, log, *, resume=False, helper_declaration=None, _session=None):
    """The first smoke produces the review evidence; a recorded critique gates every retry."""
    if _session is not None:
        execution._check_validation_session(root, _session)
        if not resume:
            raise ValueError('observation session is confined to accepted reuse; fresh launch admission required')
    shared = {"_session": _session} if _session is not None else {}
    if not physics_review.active(root, **shared):
        return None
    state = physics_review.status(root, **shared)
    correction = state.get("state") == "correction_admitted"
    if correction and _session is not None:
        raise ValueError("observation session cannot admit a correction launch")
    action = "correction" if correction else "reuse" if resume else "bulk"
    errors = physics_review.gate_errors(root, action, stage, **shared)
    if correction:
        errors += physics_review.correction_execution_errors(root, stage, command, inputs, outputs, depends_on, cwd, log, **({"helper_declaration":helper_declaration} if helper_declaration is not None else {}))
    elif not errors and not resume:
        # Do not archive reviewed artifacts before discovering the launch is stale.
        pinned = [Path(p).resolve() for p in physics_review.bound_paths(root)]
        for value in [*outputs, str(execution.log_path(root, log))]:
            target = execution.resolve_path(root, value, output=True)
            if any(p == target or p.is_relative_to(target) for p in pinned):
                errors.append(f"stage would overwrite preserved review evidence: {value}; use distinct production outputs")
    if errors:
        raise ValueError("scientific review blocks stage: " + "; ".join(errors))
    return state["correction_id"] if correction else None


def finish_correction_failure(root, correction_id, reason):
    if correction_id is not None:
        physics_review.fail_correction(root, correction_id=correction_id, reason=reason)
