"""Shared helpers of the analysis-route adapter: digests, store records, adopted artifacts, typed errors.

The adapter reads only controller-owned evidence: records in the run store (step outcomes, custody,
authority, ledger) and the bytes of artifacts the governed step adopted, each verified against the
digest its custody record pins. Nothing here writes the run directory.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib import import_module
import json
from pathlib import Path

PROVIDER = "route.analysis"
# Record kinds other packages append to the run store (P04 custody and outcomes, P06 authority).
CUSTODY = "custody"
OUTCOME = "step-outcome"
LAUNCH = "step-launch"
AUTHORITY = "authority"
# The discharging nodes of the P09 coverage rows (coverage.csv ``graph_node``).
NODES = {
    "route": "route.analysis",
    "inputs": "route.analysis.inputs",
    "scan": "route.analysis.scan",
    "waypoint": "route.analysis.waypoint",
    "ci1": "authority.ci1",
    "ci3": "authority.ci3",
    "compare": "step.compare",
    "validate": "step.validate",
}
PLACEHOLDERS = {"", "n/a", "na", "not applicable", "none", "tbd", "todo", "-", "--", "...", "null", "unknown",
                "placeholder", "to follow", "later"}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def file_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unwrap(row):
    """A store row as the record its package appended (store envelopes carry it under ``record``)."""
    if type(row) is dict and type(row.get("record")) is dict and set(row) - {"record"}:
        found = deepcopy(row["record"])
        identifier = row.get("id") or row.get("record_id")
        if identifier is not None:
            found.setdefault("_record_id", identifier)
        return found
    return deepcopy(row)


def records(store, kind) -> list:
    if store is None:
        return []
    try:
        return [unwrap(row) for row in store.scan(kind)]
    except (OSError, ValueError, KeyError):
        return []


def error(code, message, *, gate=None, row=None, step=None, fix=None, pins=(), consequence=None) -> dict:
    """One typed refusal in the controller's gate-error shape (P01 ``controller_gate``)."""
    return {"code": code, "gate": gate, "provider": PROVIDER, "message": str(message)[:1500],
            "fix": fix or "supply the missing evidence through the governed step and rerun it", "row": row,
            "step": step, "consequence": consequence, "pins": [str(p) for p in pins]}


def placeholder(value) -> bool:
    """True for empty or placeholder content (the CHECK-IN placeholder vocabulary)."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in PLACEHOLDERS
    if isinstance(value, (list, tuple, dict)):
        return not value or all(placeholder(v) for v in (value.values() if isinstance(value, dict) else value))
    return False


def optional_module(name):
    """An installed controller module, or None when its package has not landed (never a refusal by itself)."""
    try:
        return import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name and name.startswith(exc.name):
            return None
        raise


def ledger():
    return optional_module("ravel.controller.ledger")


def step_id_of(step):
    return step.get("id") if isinstance(step, dict) else None


def adapter_of(step) -> str | None:
    params = (step or {}).get("parameters") or {}
    value = params.get("adapter")
    return value if isinstance(value, str) else None


def phase_of(step) -> str:
    return ((step or {}).get("parameters") or {}).get("phase") or "execute"


def workflow_step_of(step) -> str | None:
    value = ((step or {}).get("parameters") or {}).get("workflow_step")
    return value if isinstance(value, str) else None


# ---- adopted artifacts ------------------------------------------------------------------------

def custody_rows(store, step_id=None) -> list:
    rows = records(store, CUSTODY)
    return [r for r in rows if step_id is None or r.get("step_id") == step_id]


def accepted(store, artifact) -> dict | None:
    """The latest accepted custody record of ``<step>:<path>``, or None."""
    found = None
    for row in records(store, CUSTODY):
        if row.get("artifact") == artifact:
            found = row
    return found if found is not None and found.get("status") == "accepted" else None


def outcome_outputs(outcome) -> dict:
    """``path -> {artifact, sha256}`` from a step outcome's accepted outputs."""
    found = {}
    for row in (outcome or {}).get("outputs") or ():
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            found[row["path"]] = {"artifact": row.get("artifact"), "sha256": row.get("sha256")}
    return found


def destination(step_id, path) -> str:
    """Where the governed step adopts a declared output in the run directory (P04 custody convention)."""
    return f"steps/{step_id}/{path}"


def _output_bytes(context, step_id, path, *, outcome=None):
    """``(bytes, pin, problem)`` for an adopted output of ``step_id``.

    The bytes are read from the custody destination and must equal the digest the custody record (or,
    without one, the step outcome) pins. A missing, unpinned or changed artifact is a problem, never
    content.
    """
    store, run_dir = context.get("store"), context.get("run_dir")
    if run_dir is None:
        return None, None, "the run directory is not named"
    record = accepted(store, f"{step_id}:{path}")
    history = [r for r in records(store, CUSTODY) if r.get("artifact") == f"{step_id}:{path}"]
    if history and record is None:
        return None, None, f"{step_id}:{path} has no current accepted custody record"
    relative = record.get("destination") if record else destination(step_id, path)
    wanted = record.get("sha256") if record else outcome_outputs(outcome).get(path, {}).get("sha256")
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return None, None, f"{step_id}:{path} has an unsafe custody destination"
    root = Path(run_dir).resolve()
    target = root / relative
    if any(part.is_symlink() for part in (target, *target.parents) if part != root and root in part.parents):
        return None, None, f"{step_id}:{path} has a symbolic link in its custody destination"
    if not target.is_file():
        return None, None, f"{step_id}:{path} is not adopted at {relative}"
    raw = target.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if wanted is None:
        return None, None, f"{step_id}:{path} has no custody digest"
    if actual != wanted:
        return None, None, f"{step_id}:{path} differs from the bytes its custody record pins"
    return raw, {"artifact": f"{step_id}:{path}", "path": relative, "sha256": actual}, None


def read_output(context, step_id, path, *, outcome=None):
    """Decode the same byte buffer whose custody digest was checked."""
    raw, pin, problem = _output_bytes(context, step_id, path, outcome=outcome)
    if problem:
        return None, None, problem
    try:
        return json.loads(raw.decode("utf-8")), pin, None
    except (UnicodeError, ValueError) as exc:
        return None, None, f"{step_id}:{path} is not JSON: {exc}"[:500]


def trace_problem(context, artifact) -> str | None:
    """A numerical source must name current, adopted bytes in this controller's custody."""
    if not isinstance(artifact, str) or ":" not in artifact:
        return "no source artifact is named"
    step_id, path = artifact.removeprefix("artifact:").split(":", 1)
    record = accepted(context.get("store"), f"{step_id}:{path}")
    if record is None:
        return f"{artifact} is not in accepted custody"
    _, _, problem = _output_bytes(context, step_id, path)
    return problem


def outcomes(store) -> dict:
    """``step id -> latest outcome record`` (P04 ``step-outcome``), seats excluded."""
    found = {}
    for row in records(store, OUTCOME):
        if row.get("seat"):
            continue
        if isinstance(row.get("step_id"), str):
            found[row["step_id"]] = row
    return found


def state_steps(context) -> dict:
    """The controller's own step states (RunState ``steps``), the source of truth inside the graph."""
    state = context.get("state") or {}
    return state.get("steps") or {}


def step_status(context, step_id) -> str | None:
    row = state_steps(context).get(step_id)
    if isinstance(row, dict) and row.get("status"):
        return row["status"]
    found = outcomes(context.get("store")).get(step_id)
    if isinstance(found, dict):
        return found.get("status") or (found.get("outcome") or {}).get("status")
    return None
