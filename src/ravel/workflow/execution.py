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
from .validation_io import ValidationSession, _empty_directory_members, _verbatim_input_source_copies, validate_output_policy

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


def receipt_digest(record):
    """Logs used as downstream scientific inputs need the same custody as outputs.

    Historical receipts without a log commitment remain inspectable; they cannot
    establish the new regenerated-log correction contract.
    """
    keys = ("fingerprint", "output_snapshot")
    if "log_snapshot" in record:
        keys += ("log_snapshot",)
    if "operation_resources" in record:
        keys += ("operation_authority",)
    return digest({k: record[k] for k in keys})


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


def helper_declaration_fields(mapping):
    """Absent field preserves legacy serialization; dynamic owner transport is excluded."""
    if "helper_declaration" not in mapping:return {}
    from . import helper_registration
    from copy import deepcopy
    helper_registration.validate_declaration(mapping["helper_declaration"])
    return {"helper_declaration":deepcopy(mapping["helper_declaration"])}


def stage_metadata_fields(mapping):
    """Optional admitted stage fields; absence preserves legacy identities."""
    return output_policy_fields(mapping) | helper_declaration_fields(mapping) | operation_resource_fields(mapping)


def helper_input_paths(declaration, *, _session=None):
    from . import helper_registration
    helper_registration.validate_declaration(declaration)
    pins = [declaration['registration_source']]
    for row in declaration['helpers']:
        pins.extend([row['helper_source'], row['interpreter_binary']])
    hash_file = _session.hash_file if _session is not None else file_hash
    for pin in pins:
        if hash_file(pin['path']) != pin['sha256']:
            raise ValueError('registered helper source or interpreter bytes changed')
    return list(dict.fromkeys(pin['path'] for pin in pins))


def relocate_helper_fields(mapping, old_output, new_output):
    """Pure attempt-root relocation for frozen detached correction replay."""
    from copy import deepcopy
    if 'helper_declaration' not in mapping:return {}
    declaration=deepcopy(mapping['helper_declaration'])
    old_output, new_output = Path(old_output), Path(new_output)
    for row in declaration['helpers']:
        root=Path(row['request_root'])
        if root==old_output or not root.is_relative_to(old_output):
            raise ValueError('registered helper root is outside its admitted output')
        row['request_root']=str(new_output/root.relative_to(old_output))
    return {'helper_declaration':declaration}
def operation_resource_fields(mapping):
    from .operation_resources import fields
    return fields(mapping)


def output_policy_fields(mapping):
    """Preserve absent-field identity for legacy fingerprints and recipes."""
    return {'output_policy': mapping['output_policy']} if 'output_policy' in mapping else {}


def output_snapshot_fields(mapping):
    """Source-copy exceptions carry the exact committed singleton inputs."""
    fields = output_policy_fields(mapping)
    if fields and (fields['output_policy'].get('verbatim_input_source_copies') or any(entry.get('role') in ('retained_build_marker', 'generated_build_marker_family', 'retained_source_file') for entry in fields['output_policy']['allow_empty_directory_members'])):
        fields.update(input_snapshot=mapping['input_snapshot'], input_paths=mapping['inputs'])
    return fields


def snapshot(rundir, paths, *, outputs=False, output_policy=None, input_snapshot=None, input_paths=None):
    paths = list(paths)
    allowed = _empty_directory_members(rundir, paths, outputs, output_policy, resolve_path, input_snapshot=input_snapshot, input_paths=input_paths)
    copies = _verbatim_input_source_copies(rundir, paths, outputs, output_policy, resolve_path, input_snapshot=input_snapshot, input_paths=input_paths)
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
            if outputs and size == 0 and (item == path or item not in allowed):
                raise ValueError(f"empty output: {item}")
            content_digest = file_hash(item)
            if item in copies and (size != copies[item]['size'] or content_digest != copies[item]['sha256']):
                raise ValueError('verbatim copied source differs from approved input')
            if outputs and item.suffix.lower() == ".json" and item not in copies:
                read_json(item)  # Truncated, duplicate-key and non-finite JSON is not success.
            entries.append({"name": "." if item == path else item.relative_to(path).as_posix(),
                            "size": size, "sha256": content_digest})
        if outputs and path.is_dir() and not any(entry['size'] for entry in entries):
            raise ValueError(f'empty output directory: {value}')
        key = str(path)
        if key in result:
            raise ValueError(f"duplicate artifact path: {value}")
        result[key] = {"kind": "file" if path.is_file() else "directory", "files": entries}
    if any(not path.is_file() for path in copies):
        raise ValueError('declared verbatim source copy is missing')
    if copies != _verbatim_input_source_copies(rundir, paths, outputs, output_policy, resolve_path, input_snapshot=input_snapshot, input_paths=input_paths):
        raise ValueError('source-copy declaration changed during validation')
    if allowed != _empty_directory_members(rundir, paths, outputs, output_policy, resolve_path, input_snapshot=input_snapshot, input_paths=input_paths):
        raise ValueError('empty-member declaration or family changed during validation')
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


RUNTIME_ENVIRONMENT_KEYS = (
    "PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "CONDA_PREFIX",
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
)


def runtime_environment():
    """Capture only the execution environment values committed by runtime_context."""
    return {name: os.environ.get(name) for name in RUNTIME_ENVIRONMENT_KEYS}


def _validate_runtime_environment(record):
    if "runtime_environment" not in record:
        # Historical receipts remain inspectable, but cannot recover their environment.
        return
    environment = record["runtime_environment"]
    if (type(environment) is not dict or set(environment) != set(RUNTIME_ENVIRONMENT_KEYS)
            or any(value is not None and type(value) is not str for value in environment.values())):
        raise ValueError("invalid runtime environment capsule")
    runtime = record.get("runtime")
    if (type(runtime) is not dict
            or runtime.get("environment_sha256") != digest(environment)):
        raise ValueError("runtime environment capsule digest differs from planned runtime")


def runtime_context():
    # Every boundary discovers the complete current distribution population.
    # Reuse only this one parsed metadata object, never a cross-call census.
    environment = runtime_environment()
    packages = []
    for distribution in importlib.metadata.distributions():
        metadata = distribution.metadata
        name = metadata.get("Name")
        if not name:
            continue
        if (type(distribution) is importlib.metadata.PathDistribution
                and type(distribution).metadata is importlib.metadata.Distribution.metadata
                and type(distribution).version is importlib.metadata.Distribution.version):
            # The pinned stdlib getter is precisely self.metadata["Version"].
            # A custom finder/subclass or getter retains its version semantics.
            version = metadata["Version"]
        else:
            version = distribution.version
        packages.append((name, version))
    packages.sort()
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


def _check_validation_session(rundir, session):
    if session.closed or Path(session.rundir).resolve() != Path(rundir).resolve():
        raise ValueError('closed or cross-run validation session')


def stage_errors(rundir, name, state=None, visiting=None, *, _session=None):
    if _session is not None:
        _check_validation_session(rundir, _session)
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
    try:
        _validate_runtime_environment(record)
    except (ValueError, TypeError) as exc:
        return [f"stage {name} evidence unavailable: {exc}"]
    if record.get("status") != "succeeded":
        return [f"stage {name} is {record.get('status', 'invalid')}"]
    try:
        errors = []
        if "operation_resources" in record:
            from .operation_resources import check_record
            check_record(rundir, record)
        expected_fingerprint = digest({k: record[k] for k in
                                       ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")}
                                      | output_policy_fields(record) | helper_declaration_fields(record) | operation_resource_fields(record))
        if 'output_policy' in record:
            validate_output_policy(rundir, record['outputs'], record['output_policy'], resolve_path, input_snapshot=record['input_snapshot'], input_paths=record['inputs'], require_input_binding=True)
        if expected_fingerprint != record.get("fingerprint"):
            errors.append(f"stage {name} specification changed")
        if record["runtime"] != _session.runtime:
            errors.append(f"stage {name} runtime changed")
        if _session.snapshot(record["inputs"]) != record["input_snapshot"]:
            errors.append(f"stage {name} inputs changed")
        if _session.snapshot(record["outputs"], outputs=True, **output_snapshot_fields(record)) != record["output_snapshot"]:
            errors.append(f"stage {name} outputs changed")
        if "log_snapshot" in record and _session.snapshot([str(log_path(rundir, record["log"]))]) != record["log_snapshot"]:
            errors.append(f"stage {name} log changed")
        expected_receipt = receipt_digest(record)
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


def validate_completed_execution(rundir, planned_stages, *, _session=None):
    """Require the exact declared plan and valid terminal receipts for every stage.

    Unlike ``validate_execution``, absent or partial ledgers cannot pass. The caller
    must independently authenticate the supplied plan (for example its approved
    contract hash). Supervisor-added executable/source inputs are permitted, but
    every declared input, output, command and dependency must match the receipt.
    This is a current-runtime validation, with the same semantics as stage_errors.
    """
    owns_session = _session is None
    session = _session
    try:
        if session is not None:
            _check_validation_session(rundir, session)
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
        if owns_session:
            session = _validation_session(rundir, state, planned_stages)
        else:
            session.read_document(Path(rundir) / STATE_NAME)
            session.track(state)
            session.track(planned_stages)
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
            if output_policy_fields(record) != output_policy_fields(item):
                errors.append(f"stage {name} output policy differs from plan")
            if helper_declaration_fields(record) != helper_declaration_fields(item):
                errors.append(f"stage {name} helper declaration differs from plan")
            if operation_resource_fields(record) != operation_resource_fields(item):
                errors.append(f"stage {name} operation resources differ from plan")
            expected_cwd = Path(item.get("cwd", rundir)).resolve()
            if Path(record.get("cwd", "")).resolve() != expected_cwd:
                errors.append(f"stage {name} cwd differs from plan")
            errors.extend(stage_errors(rundir, name, state, _session=session))
        return list(dict.fromkeys([*errors, *(session.finish() if owns_session else [])]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"completed execution unavailable: {exc}"]
    finally:
        if owns_session and session is not None:
            session.close()


def plan_stage(rundir, stage, command, inputs, outputs, depends_on, cwd, *, _session=None, output_policy=None, operation_resources=None, helper_declaration=None):
    if operation_resources is not None:
        from .operation_resources import validate
        operation_resources = validate(operation_resources)
    if not NAME.fullmatch(stage):
        raise ValueError("invalid stage name")
    if not command or any(type(v) is not str or not v for v in command):
        raise ValueError("stage command must be a nonempty list of strings")
    if stage in depends_on or len(set(depends_on)) != len(depends_on):
        raise ValueError("invalid stage dependencies")
    inputs = list(inputs)
    if helper_declaration is not None:
        for path in helper_input_paths(helper_declaration, _session=_session):
            if path not in inputs:inputs.append(path)
    outputs = list(outputs)
    if output_policy is not None:
        validate_output_policy(rundir, outputs, output_policy, resolve_path)
    # Hash executable identity, argument scripts, and this package's implementation.
    executable = shutil.which(command[0]) if not Path(command[0]).is_absolute() else command[0]
    if not executable or not Path(executable).is_file():
        raise ValueError(f"missing executable: {command[0]}")
    executable = str(Path(executable).resolve())
    if executable not in inputs:
        inputs.append(executable)
    resolved_inputs = {str(resolve_path(rundir, value)) for value in inputs}
    for arg in command[1:]:
        if arg.startswith("-"):
            continue
        candidate = Path(arg) if Path(arg).is_absolute() else Path(cwd) / arg
        if candidate.suffix in (".py", ".sh") and candidate.is_file():
            resolved = str(candidate.resolve())
            if resolved not in resolved_inputs:
                inputs.append(resolved)
                resolved_inputs.add(resolved)
    for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        literal = str(path)
        if literal not in resolved_inputs:
            inputs.append(literal)
            resolved_inputs.add(str(resolve_path(rundir, path)))
    input_data = _session.snapshot(inputs) if _session is not None else snapshot(rundir, inputs)
    if output_policy is not None:
        validate_output_policy(rundir, outputs, output_policy, resolve_path, input_snapshot=input_data, input_paths=inputs, require_input_binding=True)
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
        errors = stage_errors(rundir, parent, state, _session=_session)
        if errors:
            raise ValueError("; ".join(errors))
        parents[parent] = state["stages"][parent]["receipt_sha256"]
    specification = {"command": list(command), "cwd": str(Path(cwd).resolve()),
                     "inputs": inputs, "outputs": outputs, "input_snapshot": input_data,
                     "parents": parents, "runtime": _session.runtime if _session is not None else runtime_context()}
    if output_policy is not None:
        # Isolate the planned immutable declaration from caller-owned objects.
        from copy import deepcopy
        specification['output_policy'] = deepcopy(output_policy)
    if helper_declaration is not None:
        from copy import deepcopy
        specification["helper_declaration"]=deepcopy(helper_declaration)
    if operation_resources is not None:
        specification["operation_resources"] = operation_resources
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
    environment = runtime_environment()
    runtime = specification.get("runtime")
    if (type(runtime) is not dict
            or runtime.get("environment_sha256") != digest(environment)):
        raise ValueError("runtime environment changed since stage planning")
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
              "runtime_environment": environment,
              "attempt_record": str((directory / "record.json").relative_to(root)),
              "status": "running", "started_utc": utc_now(), "supervisor_pid": os.getpid(),
              "child_pid": None, "child_identity": None, "log": logrel}
    _update(root, stage, record)
    return record


def record_process(rundir, record, pid):
    record.update(child_pid=pid, child_identity=process_identity(pid))
    _update(rundir, record["stage"], record)


def finish_attempt(rundir, record, code, error=None, *, ending_check=None):
    if code == 0:
        try:
            if "operation_resources" in record:
                from .operation_resources import check_record
                check_record(rundir, record)
                committed = {k: record[k] for k in ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")}
                committed.update(stage_metadata_fields(record))
                if digest(committed) != record["fingerprint"]:
                    raise ValueError("stage operation resources changed during execution")
            if record["runtime"] != runtime_context():
                raise ValueError("stage runtime changed during execution")
            if snapshot(rundir, record["inputs"]) != record["input_snapshot"]:
                raise ValueError("stage inputs changed during execution")
            for parent, expected in record["parents"].items():
                state = load_execution(rundir)
                if stage_errors(rundir, parent, state) or state["stages"][parent]["receipt_sha256"] != expected:
                    raise ValueError(f"parent {parent} changed during execution")
            if 'output_policy' in record:
                validate_output_policy(rundir, record['outputs'], record['output_policy'], resolve_path, input_snapshot=record['input_snapshot'], input_paths=record['inputs'], require_input_binding=True)
                committed = {k: record[k] for k in ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")}
                committed.update(output_policy_fields(record))
                committed.update(helper_declaration_fields(record));committed.update(operation_resource_fields(record))
                if digest(committed) != record.get('fingerprint'):
                    raise ValueError('stage output policy or specification changed during execution')
            if 'helper_declaration' in record:
                committed={k:record[k] for k in ("command","cwd","inputs","outputs","input_snapshot","parents","runtime")}
                committed.update(output_policy_fields(record));committed.update(helper_declaration_fields(record));committed.update(operation_resource_fields(record))
                if digest(committed)!=record.get('fingerprint'):
                    raise ValueError('stage helper declaration or specification changed during execution')
            record["output_snapshot"] = snapshot(rundir, record["outputs"], outputs=True, **output_snapshot_fields(record))
            log = log_path(rundir, record["log"])
            if log.is_file():
                record["log_snapshot"] = snapshot(rundir, [str(log)])
            if ending_check is not None:ending_check()
            record["receipt_sha256"] = receipt_digest(record)
        except (OSError, ValueError, KeyError) as exc:
            code, error = 3, str(exc)
    record.update(status="succeeded" if code == 0 else "failed", exit_code=code,
                  error=error, finished_utc=utc_now())
    _update(rundir, record["stage"], record)
    return code


def await_worker_registration(rundir, stage, *, timeout=5.0):
    """Wait for the supervisor's sole child publication before pinning its ledger.

    This is process-registration custody only. All scientific inputs, approval,
    launch selection and the complete ledger are freshly verified afterward.
    """
    import math
    import time
    if type(stage) is not str or not NAME.fullmatch(stage):
        raise ValueError('valid stage name required for worker registration')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5.0:
        raise ValueError('worker registration timeout must be positive and at most five seconds')
    rd = Path(rundir).resolve()
    if os.environ.get(BACKEND_JOB_ENV) and os.getppid() != _recorded_supervisor(rd, stage):
        return _await_backend_payload(rd, stage, timeout)
    parent, child = os.getppid(), os.getpid()
    parent_identity = process_identity(parent)
    child_identity = process_identity(child)
    if parent_identity is None or child_identity is None:
        raise ValueError('scientific worker process registration identity unavailable')
    deadline = time.monotonic() + timeout
    while True:
        if os.getppid() != parent or process_identity(parent) != parent_identity:
            raise ValueError('scientific worker registration parent changed or disappeared')
        path = rd / STATE_NAME
        if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
            raise ValueError(f'expected a regular input without symlinks: {path}')
        record = load_execution(rd)['stages'].get(stage, {})
        if record.get('status') != 'running' or record.get('supervisor_pid') != parent:
            raise ValueError('scientific worker requires its current approved supervised attempt')
        if record.get('child_pid') == child and record.get('child_identity') == child_identity:
            return {'mode': 'direct', 'supervisor_pid': parent, 'worker_pid': child}
        if record.get('child_pid') is not None or record.get('child_identity') is not None:
            raise ValueError('scientific worker process registration differs from its actual child')
        if time.monotonic() >= deadline:
            raise ValueError('scientific worker process registration timed out')
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))


# ---------------------------------------------------------------- backend payload custody
BACKEND_JOB_ENV = 'RAVEL_BACKEND_JOB'


def _parent_pid(pid):
    try:
        value = subprocess.check_output(["ps", "-p", str(pid), "-o", "ppid="], text=True, timeout=5).strip()
        return int(value) if value else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _recorded_supervisor(rd, stage):
    try:
        return load_execution(rd)['stages'].get(stage, {}).get('supervisor_pid')
    except (OSError, ValueError, KeyError, TypeError):
        return None


def worker_custody(rundir, stage, record=None):
    """Prove that this process is the current attempt's scientific worker.

    Direct custody: the supervisor's registered child. Backend custody: the payload
    of the native backend job of the current attempt, proven link by link. The
    supervisor recorded the backend worker as its child; the worker's handle in the
    attempt directory records the launcher's pid and start identity; the launcher
    is the worker's child and this process is the launcher's child; the launcher
    acknowledged this exact pid and start identity in payload.json; and the attempt's
    plan.json is byte-for-byte a pinned input of the attempt. Any missing or
    different link refuses. The environment only names the job directory to check.
    These records are files of this user: the chain separates cooperating RAVEL
    processes; it is not a defence against a hostile process of the same user.
    """
    rd = Path(rundir).resolve()
    record = load_execution(rd)['stages'].get(stage, {}) if record is None else record
    refused = 'scientific worker requires its current approved supervised attempt'
    if record.get('status') != 'running':
        raise ValueError(refused)
    me, parent = os.getpid(), os.getppid()
    identity = process_identity(me)
    if identity is None:
        raise ValueError('scientific worker process registration identity unavailable')
    supervisor = record.get('supervisor_pid')
    if parent == supervisor:
        if record.get('child_pid') != me or record.get('child_identity') != identity:
            raise ValueError(refused)
        return {'mode': 'direct', 'supervisor_pid': supervisor, 'worker_pid': me}
    job_value = os.environ.get(BACKEND_JOB_ENV)
    if not job_value or not record.get('attempt_id'):
        raise ValueError(refused)
    attempt = rd / 'logs/execution' / stage / record['attempt_id'] / 'backend'
    job = Path(job_value)
    if (not job.is_absolute() or job != attempt / 'job'
            or any(p.is_symlink() for p in (job, *job.parents))):
        raise ValueError('backend payload job directory is not the current attempt\'s job')
    worker, worker_identity = record.get('child_pid'), record.get('child_identity')
    if (type(worker) is not int or worker_identity is None or process_identity(worker) != worker_identity
            or type(supervisor) is not int or process_identity(supervisor) is None
            or _parent_pid(worker) != supervisor):
        raise ValueError('backend worker is not the live registered child of the live supervisor')
    handle = read_json(attempt / 'backend-handle.json')
    remote = handle.get('remote') if isinstance(handle.get('remote'), dict) else {}
    launcher = remote.get('pid')
    if (handle.get('backend') != 'native' or handle.get('job_dir') != str(job)
            or handle.get('state') not in ('submitted',) or type(launcher) is not int):
        raise ValueError('backend payload custody requires the attempt\'s submitted native job')
    if (parent != launcher or remote.get('identity') is None
            or process_identity(launcher) != remote['identity'] or _parent_pid(launcher) != worker):
        raise ValueError('backend payload is not the child of the recorded launcher of the registered worker')
    if read_json(job / 'payload.json') != {'pid': me, 'identity': identity}:
        raise ValueError('backend launcher did not acknowledge this payload process')
    # The attempt keeps the exact bytes of the pinned plan; the handle names their digests.
    plan_file = attempt / 'plan.json'
    pinned = {entry['files'][0]['sha256'] for entry in (record.get('input_snapshot') or {}).values()
              if isinstance(entry, dict) and entry.get('kind') == 'file' and len(entry.get('files', [])) == 1}
    plan_digest = file_hash(plan_file)
    if (plan_digest not in pinned or handle.get('plan_file_sha256') != plan_digest
            or read_json(plan_file).get('plan_sha256') != handle.get('plan_sha256')):
        raise ValueError('backend payload plan is not the pinned plan of the approved attempt')
    return {'mode': 'backend', 'supervisor_pid': supervisor, 'worker_pid': worker, 'launcher_pid': launcher,
            'payload_pid': me, 'job_dir': str(job), 'output_dir': str(job / 'output'),
            'plan_sha256': handle.get('plan_sha256')}


def _await_backend_payload(rd, stage, timeout):
    """Wait (bounded) for the handle and the launcher acknowledgement, then prove custody."""
    import time
    deadline = time.monotonic() + timeout
    while True:
        try:
            return worker_custody(rd, stage)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if time.monotonic() >= deadline:
                raise ValueError(f'backend payload registration refused: {exc}') from exc
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
