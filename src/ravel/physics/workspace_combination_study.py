"""Bounded complete-workspace combination witness; no optimization or limits.

The ordinary science workflow owns approval, source/runtime custody and the
outer deadline. This adapter admits two exact published-model imports and
retains the reviewed five-vector structural law witness without inference.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time

from ravel.workflow.release_registry import lazy_module
pm = lazy_module('ravel.physics.published_model')
from ravel.physics import workspace_combination as compiler
from ravel.physics import workspace_combination_witness as witness
from ravel.physics.finite_mc_model import _admit_output
from ravel.physics.quantities import _keys, _text

MAX_FILE_BYTES = 8 * 1024**2
MAX_CAPTURE_BYTES = 64 * 1024**2
MAX_CHECKPOINT_BYTES = 16 * 1024**2
MAX_JOURNAL_BYTES = 1024**2
PROTOCOL = {"points": ["nominal", "poi_zero", "poi_two", "plus", "minus"],
            "backend": "numpy", "precision": "64b", "max_calls": 20,
            "model_compilations": 8, "mathematical_seconds": 60.,
            "mean_atol": 1e-9, "density_atol": 1e-7, "fits": 0}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def validate(task):
    _keys(task, ("input",), label="workspace combination study task")
    _text(task["input"], "input")
    return deepcopy(task)


def _capture(task, base):
    from ravel.workflow.science import regular
    captured = {}

    def read(path, expected=None):
        path = regular(str(path), base)
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("combination input exceeds 8 MiB")
        raw = path.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("combination input exceeds 8 MiB")
        if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("combination input hash differs")
        key = str(path)
        if key in captured and captured[key] != raw:
            raise ValueError("input changed during capture")
        captured[key] = raw
        if sum(map(len, captured.values())) > MAX_CAPTURE_BYTES:
            raise ValueError("combination capture exceeds 64 MiB")
        return path, raw

    def bound(pin, parent):
        _keys(pin, ("path", "sha256"), label="exact input pin")
        pm._sha(pin["sha256"], "input digest")
        return read(regular(pin["path"], parent), pin["sha256"])

    path, raw = read(validate(task)["input"])
    doc = json.loads(raw)
    _keys(doc, ("schema_version", "components", "policy", "protocol", "grounding"), label="combination study")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise ValueError("combination study schema must be integer 1")
    if _json(doc["protocol"]) != _json(PROTOCOL):
        raise ValueError("exact reviewed five-vector protocol required")
    if type(doc["components"]) is not list or len(doc["components"]) != 2:
        raise ValueError("exactly two complete components required")
    rows = []
    for row in doc["components"]:
        _keys(row, ("id", "published_model", "prepared_workspace", "parameter_map"), label="component")
        _text(row["id"], "component id")
        model_path, model_raw = bound(row["published_model"], path.parent)
        model_document = pm.validate_document(json.loads(model_raw))
        # The importer input graph includes the exact archive, external record
        # acknowledgment, and every declared grounding source. No model call.
        for dependency in pm.inputs({"input": str(model_path)}, model_path.parent):
            read(dependency)
        _, workspace_raw = bound(row["prepared_workspace"], path.parent)
        if type(row["parameter_map"]) is not dict or not row["parameter_map"]:
            raise ValueError("complete parameter map required")
        for key, value in row["parameter_map"].items():
            _text(key, "source parameter"); _text(value, "joined parameter")
        rows.append((row, model_path, model_document, json.loads(workspace_raw)))
    if len({row[0]["id"] for row in rows}) != 2:
        raise ValueError("distinct component identities required")
    _, policy_raw = bound(doc["policy"], path.parent)
    policy = json.loads(policy_raw)
    if type(doc["grounding"]) is not list or not doc["grounding"]:
        raise ValueError("source and prospective-review grounding required")
    for pin in doc["grounding"]:
        bound(pin, path.parent)
    return doc, rows, policy, captured


def inputs(task, base):
    """Fresh byte enumeration only, with no patch/model compilation or evaluation."""
    return [Path(path) for path in _capture(task, base)[3]]


class Recorder:
    """Atomic latest state retains every prior return; compact journal is bounded."""
    def __init__(self, out):
        self.out = out
        self.sequence = 0
        self.previous = None
        self.journal_bytes = 0
        self.journal = out / "combination-progress.jsonl"
        with self.journal.open("xb"):
            pass

    def __call__(self, state):
        raw = _json(state)
        if len(raw) > MAX_CHECKPOINT_BYTES:
            raise ValueError("combination checkpoint exceeds 16 MiB")
        checkpoint = self.out / "combination-checkpoint.json"
        if self.previous is None:
            if checkpoint.exists():
                raise FileExistsError("unowned checkpoint exists")
        elif hashlib.sha256(checkpoint.read_bytes()).hexdigest() != self.previous:
            raise ValueError("retained checkpoint changed")
        digest = hashlib.sha256(raw).hexdigest()
        row = {"sequence": self.sequence, "previous_state_sha256": self.previous,
               "state_sha256": digest, "status": state.get("status"),
               "calls": state.get("calls"), "journal_records": len(state.get("journal", [])),
               "point_records": len(state.get("points", []))}
        line = _json(row) + b"\n"
        if self.journal_bytes + len(line) > MAX_JOURNAL_BYTES:
            raise ValueError("combination journal exceeds 1 MiB")
        temporary = self.out / "combination-checkpoint.tmp"
        with temporary.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(checkpoint)
        # No historical checkpoint is claimed retained separately. All prior
        # numerical returns persist in the kernel's cumulative current state.
        self.previous = digest
        with self.journal.open("ab") as stream:
            stream.write(line); stream.flush(); os.fsync(stream.fileno())
        self.journal_bytes += len(line)
        self.sequence += 1


def run(task, base, output):
    out = _admit_output(output)
    started = time.monotonic()
    recorder = Recorder(out)
    state, error, captured, contracts = None, None, {}, []
    try:
        doc, rows, policy, captured = _capture(task, base)
        components = []
        for row, path, source, prepared in rows:
            contract = pm.load_published_model(source, path.parent)
            workspace = contract.workspace()
            if workspace != prepared:
                raise ValueError("published import differs from exact prepared complete workspace")
            contracts.append({"id": row["id"], "manifest": contract.manifest()})
            components.append({"id": row["id"], "workspace": workspace,
                               "measurement": source["measurement"], "parameter_map": row["parameter_map"]})
        with (out / "combination-source-contracts.json").open("xb") as stream:
            stream.write(_json(contracts))
        import pyhf
        pyhf.set_backend("numpy", precision="64b")
        state = witness.qualify(components, policy, PROTOCOL["points"], compiler=compiler.combine,
                                record=recorder, max_calls=20, max_seconds=60.,
                                mean_atol=1e-9, density_atol=1e-7)
        if state.get("status") != "completed" or state.get("passed") is not True or state.get("calls") != 20:
            raise ValueError("complete fixed-vector comparison did not pass")
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
    ending_errors = []
    for path, raw in captured.items():
        try:
            if Path(path).read_bytes() != raw:
                ending_errors.append(path)
        except OSError:
            ending_errors.append(path)
    passed = error is None and not ending_errors and state is not None
    result = {"schema_version": 1, "status": "passed" if passed else "failed",
              "scope": "complete-workspace fixed-vector structural law parity",
              "physics_validated": False, "fits": 0, "generated_events": 0,
              "protocol": PROTOCOL, "error": error, "ending_input_errors": ending_errors,
              "checkpoint": "combination-checkpoint.json" if recorder.previous else None,
              "checkpoint_sha256": recorder.previous, "elapsed_seconds": time.monotonic()-started,
              "source_inputs": [{"path": p, "sha256": hashlib.sha256(raw).hexdigest()} for p,raw in captured.items()],
              "limits": ["Component and joined means share pyhf interpolation.",
                         "Source-prescribed population independence is not reconstructed event disjointness.",
                         "No optimization, interval, exclusion, coverage or detector validation.",
                         "The 60-second mathematical ceiling is cooperative; ordinary outer supervision includes input and final custody."]}
    with (out / "combination-result.json").open("xb") as stream:
        stream.write(_json(result))
    return result


def execution_seconds(task, base):
    """Minimum ordinary budget for the reviewed 60s mathematical phase."""
    validate(task)
    return int(PROTOCOL["mathematical_seconds"])


def resource_bounds(task, base):
    """Declared limits; observed numerical calls remain in the retained witness."""
    validate(task)
    return {"processes": 2, "maximum_mathematical_workers": 1,
            "maximum_native_children": 0, "threads": 1, "generated_events": 0,
            "fits": 0, "model_compilations": PROTOCOL["model_compilations"],
            "mean_density_calls": PROTOCOL["max_calls"],
            "mathematical_seconds": PROTOCOL["mathematical_seconds"],
            "recommended_outer_seconds": 180, "capture_bytes": MAX_CAPTURE_BYTES,
            "checkpoint_bytes": MAX_CHECKPOINT_BYTES, "journal_bytes": MAX_JOURNAL_BYTES}
