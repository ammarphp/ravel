"""Durable stage receipts, dependency checks, and immutable attempt history.

A succeeded process is reusable only while its command, scientific inputs, parent
receipts and outputs still match. Legacy runs without this ledger remain explicitly
outside this execution check; they are not silently upgraded to verified runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
import platform
import sys
import importlib.metadata

from .state_io import atomic_json, file_lock, read_json
from .validation_io import ValidationSession

STATE_NAME = "execution_state.json"
VERSION = 1
NAME = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def resolve_path(rundir, value, *, output=False):
    root = Path(rundir).resolve()
    raw = Path(value)
    path = raw if raw.is_absolute() else root / raw
    if output and (path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root)):
        raise ValueError(f"output must not traverse a symlink: {value}")
    path = path.resolve()
    if output and (path == root or not path.is_relative_to(root)):
        raise ValueError(f"output must be inside the run directory: {value}")
    if output and (path.name == STATE_NAME or path.is_relative_to(root / "logs/execution")):
        raise ValueError(f"stage output cannot replace execution evidence: {value}")
    return path


def snapshot(rundir, paths, *, outputs=False):
    result = {}
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("artifact paths must be nonblank strings")
        path = resolve_path(rundir, value, output=outputs)
        if not path.exists():
            raise ValueError(f"missing {'output' if outputs else 'input'}: {value}")
        children = [] if path.is_file() else sorted(path.rglob("*"))
        if any(p.is_symlink() for p in children):
            raise ValueError(f"artifact directory contains an untracked symlink: {value}")
        files = [path] if path.is_file() else [p for p in children if p.is_file()]
        if not files:
            raise ValueError(f"empty artifact: {value}")
        entries = []
        for item in files:
            if outputs and item.is_symlink():
                raise ValueError(f"output contains a symlink: {item}")
            size = item.stat().st_size
            if outputs and size == 0:
                raise ValueError(f"empty output: {item}")
            if outputs and item.suffix.lower() == ".json":
                read_json(item)  # Truncated, duplicate-key and non-finite JSON is not success.
            entries.append({"name": "." if item == path else item.relative_to(path).as_posix(),
                            "size": size, "sha256": file_hash(item)})
        key = str(path)
        if key in result:
            raise ValueError(f"duplicate artifact path: {value}")
        result[key] = {"kind": "file" if path.is_file() else "directory", "files": entries}
    return result


def load_execution(rundir):
    path = Path(rundir) / STATE_NAME
    if not path.exists():
        return {"schema_version": VERSION, "revision": 0, "stages": {}}
    state = read_json(path)
    if (type(state) is not dict or type(state.get("schema_version")) is not int or state.get("schema_version") != VERSION
            or type(state.get("revision")) is not int or state["revision"] < 0
            or type(state.get("stages")) is not dict):
        raise ValueError("invalid execution ledger")
    return state


def _update(rundir, stage, record):
    root = Path(rundir)
    with file_lock(root / "logs/execution/ledger.lock"):
        state = load_execution(root)
        state["stages"][stage] = record
        state["revision"] += 1
        state["updated_utc"] = utc_now()
        atomic_json(root / record["attempt_record"], record)
        atomic_json(root / STATE_NAME, state)


def process_identity(pid):
    """Start time is used only to identify an owned orphan, never as science evidence."""
    try:
        os.kill(pid, 0)
        value = subprocess.check_output(["ps", "-p", str(pid), "-o", "lstart="],
                                        text=True, timeout=5).strip()
        return value or None
    except (OSError, subprocess.SubprocessError):
        return None


def process_group_members(pgid):
    """Active members only; an exited leader does not prove its descendants stopped."""
    output = subprocess.check_output(["ps", "-axo", "pid=,pgid=,stat="], text=True, timeout=5)
    members = []
    for line in output.splitlines():
        columns = line.split()
        if len(columns) >= 3 and columns[1].isdigit() and int(columns[1]) == pgid and not columns[2].startswith("Z"):
            members.append(int(columns[0]))
    return members


def log_path(rundir, value):
    root = Path(rundir).resolve()
    path = resolve_path(root, value, output=True)
    if (not path.is_relative_to(root / "logs") or path.suffix != ".log"
            or path.is_relative_to(root / "logs/state")):
        raise ValueError("stage log must be a .log file under logs/, outside state/control directories")
    return path


def runtime_context():
    # Only execution-relevant configuration; never serialize arbitrary environment secrets.
    environment = {name: os.environ.get(name) for name in
                   ("PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "CONDA_PREFIX",
                    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")}
    packages = sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()
                      if d.metadata.get("Name"))
    return {"platform": platform.platform(), "python": sys.version,
            "environment_sha256": digest(environment), "packages_sha256": digest(packages)}


def _validation_session(rundir, *tracked):
    session = ValidationSession(rundir, resolve_path=resolve_path, read_json=read_json,
                                runtime_context=runtime_context, digest=digest,
                                state_name=STATE_NAME, tracked=tracked)
    if session.ledger_existed and tracked and digest(read_json(session.ledger)) != digest(tracked[0]):
        session.close()
        raise ValueError("execution ledger differs from supplied validation state")
    return session


def stage_errors(rundir, name, state=None, visiting=None, *, _session=None):
    state = load_execution(rundir) if state is None else state
    if _session is None:
        session = None
        try:
            session = _validation_session(rundir, state)
            errors = stage_errors(rundir, name, state, visiting, _session=session)
            return list(dict.fromkeys([*errors, *session.finish()]))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return [f"stage {name} evidence unavailable: {exc}"]
        finally:
            if session is not None:
                session.close()
    visiting = set() if visiting is None else set(visiting)
    if name in visiting:
        return [f"dependency cycle at {name}"]
    if name in _session.stages:
        return list(_session.stages[name])
    visiting.add(name)
    record = state["stages"].get(name)
    if not isinstance(record, dict):
        return [f"stage {name} has no receipt"]
    if record.get("status") != "succeeded":
        return [f"stage {name} is {record.get('status', 'invalid')}"]
    try:
        errors = []
        expected_fingerprint = digest({k: record[k] for k in
                                       ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")})
        if expected_fingerprint != record.get("fingerprint"):
            errors.append(f"stage {name} specification changed")
        if record["runtime"] != _session.runtime:
            errors.append(f"stage {name} runtime changed")
        if _session.snapshot(record["inputs"]) != record["input_snapshot"]:
            errors.append(f"stage {name} inputs changed")
        if _session.snapshot(record["outputs"], outputs=True) != record["output_snapshot"]:
            errors.append(f"stage {name} outputs changed")
        expected_receipt = digest({k: record[k] for k in ("fingerprint", "output_snapshot")})
        if record.get("receipt_sha256") != expected_receipt:
            errors.append(f"stage {name} receipt changed")
        for parent, parent_digest in record["parents"].items():
            errors.extend(stage_errors(rundir, parent, state, visiting, _session=_session))
            if state["stages"].get(parent, {}).get("receipt_sha256") != parent_digest:
                errors.append(f"stage {name} parent {parent} changed")
        _session.stages[name] = tuple(errors)
        return errors
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"stage {name} evidence unavailable: {exc}"]


def validate_execution(rundir):
    """Return current errors, or [] for legacy absence. Consumers report absence separately."""
    session = None
    try:
        state = load_execution(rundir)
        if (Path(rundir) / STATE_NAME).exists() and not state["stages"]:
            return ["execution ledger has no stages"]
        session = _validation_session(rundir, state)
        errors = [error for name in state["stages"]
                  for error in stage_errors(rundir, name, state, _session=session)]
        return list(dict.fromkeys([*errors, *session.finish()]))
    except (OSError, ValueError, TypeError) as exc:
        return [f"execution ledger unavailable: {exc}"]
    finally:
        if session is not None:
            session.close()


def validate_completed_execution(rundir, planned_stages):
    """Require the exact declared plan and valid terminal receipts for every stage.

    Unlike ``validate_execution``, absent or partial ledgers cannot pass. The caller
    must independently authenticate the supplied plan (for example its approved
    contract hash). Supervisor-added executable/source inputs are permitted, but
    every declared input, output, command and dependency must match the receipt.
    This is a current-runtime validation, with the same semantics as stage_errors.
    """
    session = None
    try:
        if not isinstance(planned_stages, list) or not planned_stages:
            raise ValueError("completed execution requires a nonempty stage plan")
        names = []
        for item in planned_stages:
            if not isinstance(item, dict) or not isinstance(item.get("stage"), str) or not NAME.fullmatch(item["stage"]):
                raise ValueError("invalid planned stage")
            names.append(item["stage"])
            for key in ("command", "inputs", "outputs", "depends_on"):
                values = item.get(key)
                if not isinstance(values, list) or any(type(v) is not str or not v for v in values):
                    raise ValueError(f"invalid planned {key}")
                if len(values) != len(set(values)) and key != "command":
                    raise ValueError(f"duplicate planned {key}")
            if not item["command"]:
                raise ValueError("empty planned command")
        if len(names) != len(set(names)):
            raise ValueError("duplicate planned stage")
        for item in planned_stages:
            if item["stage"] in item["depends_on"] or not set(item["depends_on"]) <= set(names):
                raise ValueError("invalid planned dependency")
        if not (Path(rundir) / STATE_NAME).is_file():
            return ["completed execution requires an execution ledger"]
        state = load_execution(rundir)
        session = _validation_session(rundir, state, planned_stages)
        errors = [f"planned stage {name} has no receipt" for name in names if name not in state["stages"]]
        errors += [f"unplanned stage {name} is present" for name in state["stages"] if name not in names]
        for item in planned_stages:
            name = item["stage"]
            record = state["stages"].get(name)
            if not isinstance(record, dict):
                if name in state["stages"]:
                    errors.append(f"stage {name} has no valid receipt")
                continue
            if record.get("command") != item["command"]:
                errors.append(f"stage {name} command differs from plan")
            if set(record.get("parents", {})) != set(item["depends_on"]):
                errors.append(f"stage {name} dependencies differ from plan")
            for key in ("inputs", "outputs"):
                expected = {resolve_path(rundir, p) for p in item[key]}
                actual = {resolve_path(rundir, p) for p in record.get(key, [])}
                if not (expected <= actual if key == "inputs" else expected == actual):
                    errors.append(f"stage {name} {key} differ from plan")
            expected_cwd = Path(item.get("cwd", rundir)).resolve()
            if Path(record.get("cwd", "")).resolve() != expected_cwd:
                errors.append(f"stage {name} cwd differs from plan")
            errors.extend(stage_errors(rundir, name, state, _session=session))
        return list(dict.fromkeys([*errors, *session.finish()]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"completed execution unavailable: {exc}"]
    finally:
        if session is not None:
            session.close()


def plan_stage(rundir, stage, command, inputs, outputs, depends_on, cwd):
    if not NAME.fullmatch(stage):
        raise ValueError("invalid stage name")
    if not command or any(type(v) is not str or not v for v in command):
        raise ValueError("stage command must be a nonempty list of strings")
    if stage in depends_on or len(set(depends_on)) != len(depends_on):
        raise ValueError("invalid stage dependencies")
    inputs = list(inputs)
    outputs = list(outputs)
    # Hash executable identity, argument scripts, and this package's implementation.
    executable = shutil.which(command[0]) if not Path(command[0]).is_absolute() else command[0]
    if not executable or not Path(executable).is_file():
        raise ValueError(f"missing executable: {command[0]}")
    executable = str(Path(executable).resolve())
    if executable not in inputs:
        inputs.append(executable)
    for arg in command[1:]:
        if arg.startswith("-"):
            continue
        candidate = Path(arg) if Path(arg).is_absolute() else Path(cwd) / arg
        if candidate.suffix in (".py", ".sh") and candidate.is_file():
            resolved = str(candidate.resolve())
            if resolved not in [str(resolve_path(rundir, p)) for p in inputs]:
                inputs.append(resolved)
    for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        if str(path) not in [str(resolve_path(rundir, p)) for p in inputs]:
            inputs.append(str(path))
    input_data = snapshot(rundir, inputs)
    output_paths = [resolve_path(rundir, value, output=True) for value in outputs]
    if len(set(output_paths)) != len(output_paths):
        raise ValueError("duplicate output paths")
    for out in output_paths:
        if any(out != other and (out.is_relative_to(other) or other.is_relative_to(out)) for other in output_paths):
            raise ValueError("nested output paths overlap")
        for inp in input_data:
            if out == Path(inp) or Path(inp).is_relative_to(out) or out.is_relative_to(Path(inp)):
                raise ValueError("a stage cannot overwrite its declared inputs")
    state = load_execution(rundir)
    parents = {}
    for parent in depends_on:
        errors = stage_errors(rundir, parent, state)
        if errors:
            raise ValueError("; ".join(errors))
        parents[parent] = state["stages"][parent]["receipt_sha256"]
    specification = {"command": list(command), "cwd": str(Path(cwd).resolve()),
                     "inputs": inputs, "outputs": outputs, "input_snapshot": input_data,
                     "parents": parents, "runtime": runtime_context()}
    specification["fingerprint"] = digest(specification)
    return specification


def reusable(rundir, stage, specification):
    state = load_execution(rundir)
    old = state["stages"].get(stage, {})
    return old.get("fingerprint") == specification["fingerprint"] and not stage_errors(rundir, stage, state)


def begin_attempt(rundir, stage, specification, logrel):
    # Reserve output ownership atomically across different concurrently launched stages.
    with file_lock(Path(rundir) / "logs/execution/artifacts.lock"):
        root = Path(rundir).resolve()
        outputs = [resolve_path(root, value, output=True) for value in specification["outputs"]]
        log = log_path(root, logrel)
        def overlaps(a, b):
            return a == b or a.is_relative_to(b) or b.is_relative_to(a)
        if any(overlaps(log, p) for p in [*outputs, *(resolve_path(root, v) for v in specification["inputs"])]):
            raise ValueError("stage log cannot overwrite an input or output artifact")
        writes = [*outputs, log]
        for name, other in load_execution(root)["stages"].items():
            if name == stage:
                continue
            if not isinstance(other, dict) or not isinstance(other.get("outputs"), list):
                raise ValueError(f"invalid output ownership for stage {name}")
            for value in [*other["outputs"], *([other["log"]] if other.get("log") else [])]:
                prior = resolve_path(root, value, output=True)
                if any(overlaps(out, prior) for out in writes):
                    raise ValueError(f"output is already owned by stage {name}; use a distinct artifact path")
        return _begin_attempt(rundir, stage, specification, logrel)


def _begin_attempt(rundir, stage, specification, logrel):
    root = Path(rundir).resolve()
    previous = load_execution(root)["stages"].get(stage)
    if previous and previous.get("status") == "running":
        pid = previous.get("child_pid")
        identity = previous.get("child_identity")
        if pid and process_identity(pid):
            # The supervisor's stage lock has been acquired, so no live supervisor owns this job.
            # Refuse automatic adoption: terminate/reconcile through the supervised recovery path.
            raise ValueError(f"orphaned stage {stage} still owns process {pid}; recover it before retry")
        previous = dict(previous, status="interrupted", finished_utc=utc_now(),
                        error="supervisor ended without a terminal receipt")
        _update(root, stage, previous)
    attempt = uuid.uuid4().hex
    directory = root / "logs/execution" / stage / attempt
    directory.mkdir(parents=True)
    failure = root / "logs" / f"{stage}.failure.json"
    if failure.exists():
        shutil.copy2(failure, directory / "prior.failure.json")
    # Keep earlier results, including malformed/truncated outputs, before a retry writes new ones.
    for i, value in enumerate(specification["outputs"]):
        path = resolve_path(root, value, output=True)
        if path.exists():
            destination = directory / "prior_outputs" / str(i) / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), destination)
    log = resolve_path(root, logrel, output=True)
    if log.exists():
        shutil.move(str(log), directory / "prior.log")
    record = {**specification, "stage": stage, "attempt_id": attempt,
              "attempt_record": str((directory / "record.json").relative_to(root)),
              "status": "running", "started_utc": utc_now(), "supervisor_pid": os.getpid(),
              "child_pid": None, "child_identity": None, "log": logrel}
    _update(root, stage, record)
    return record


def record_process(rundir, record, pid):
    record.update(child_pid=pid, child_identity=process_identity(pid))
    _update(rundir, record["stage"], record)


def finish_attempt(rundir, record, code, error=None):
    if code == 0:
        try:
            if record["runtime"] != runtime_context():
                raise ValueError("stage runtime changed during execution")
            if snapshot(rundir, record["inputs"]) != record["input_snapshot"]:
                raise ValueError("stage inputs changed during execution")
            for parent, expected in record["parents"].items():
                state = load_execution(rundir)
                if stage_errors(rundir, parent, state) or state["stages"][parent]["receipt_sha256"] != expected:
                    raise ValueError(f"parent {parent} changed during execution")
            record["output_snapshot"] = snapshot(rundir, record["outputs"], outputs=True)
            record["receipt_sha256"] = digest({k: record[k] for k in ("fingerprint", "output_snapshot")})
        except (OSError, ValueError, KeyError) as exc:
            code, error = 3, str(exc)
    record.update(status="succeeded" if code == 0 else "failed", exit_code=code,
                  error=error, finished_utc=utc_now())
    _update(rundir, record["stage"], record)
    return code
