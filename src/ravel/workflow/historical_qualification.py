"""Bounded import of a genuine Ravel historical qualification across workflows.

No physics models are constructed or evaluated. A separately declared
metadata child validates the old run with its original frozen API/runtime.
Planning hooks consume an externally pinned immutable receipt and recheck
current custody. Fresh old-API calls are restricted to initial/final worker
boundaries. This library confers neither scientific acceptance nor a lease.
"""
from pathlib import Path
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import select
import shutil
import signal
import subprocess
import sys
import time
import traceback

MAX_FILE_BYTES = 8 * 1024**2
MAX_INPUT_BYTES = 64 * 1024**2
MAX_INTERPRETER_BYTES = 64 * 1024**2
MAX_OUTPUT_BYTES = 16 * 1024**2
MAX_PINS = 4096
MAX_WORKFLOW_FILES = 512
CHILD_SECONDS = 10.
NATIVE_INPUT_BYTES = 96 * 1024**2
NATIVE_BINARY_BYTES = 64 * 1024**2
BINARY_CHUNK_BYTES = 1024**2
NATIVE_BINARY_PINS = 64
ROLES = ("physics_critic", "skeptical_verifier", "physics_decider")


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(compact(value)).hexdigest()


def keys(value, wanted):
    if not isinstance(value, dict) or set(value) != set(wanted):
        raise ValueError("Exact object fields required: " + str(wanted))


def regular(value):
    path = Path(value)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Absolute ordinary source path required")
    if not path.is_file():
        raise ValueError("Regular source absent: " + str(path))
    return path


def read(path):
    path = regular(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("8MiB file ceiling")
    return raw


def pin(path):
    path = regular(path)
    raw = read(path)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


class _BinaryEvidence:
    def __init__(self, sha256, size):
        self.sha256, self.size = sha256, size
    def __len__(self):
        return self.size


def binary_pin(path):
    path = regular(path)
    size = path.stat().st_size
    if size > MAX_INTERPRETER_BYTES:
        raise ValueError("64MiB interpreter binary ceiling")
    sha, total = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while True:
            raw = stream.read(1024**2)
            if not raw:
                break
            total += len(raw)
            if total > MAX_INTERPRETER_BYTES:
                raise ValueError("Interpreter binary grew beyond ceiling")
            sha.update(raw)
    if total != size:
        raise ValueError("Interpreter binary changed while hashing")
    return {"path": str(path), "sha256": sha.hexdigest()}


def _evidence_sha(raw):
    return raw.sha256 if isinstance(raw, _BinaryEvidence) else hashlib.sha256(raw).hexdigest()


def _checked_custody(value, contract):
    profile = _custody_profile(contract)
    if profile is not None:
        declared = next((r for r in profile["binary_pins"] if r["path"] == value["path"]), None)
        if declared is not None:
            if declared["sha256"] != value["sha256"]:
                raise ValueError("Declared native binary source hash differs")
            if declared["custody_role"] == "declared_metadata_query":
                raw = checked(value)
                if len(raw) != declared["bytes"] or _binary_format(raw[:4]) != declared["format"]:
                    raise ValueError("Declared metadata executable binary class/size differs")
                return raw  # Ordinary bounded executable bytes; never an opaque assertion bypass.
            return _native_binary_evidence(declared)
        raw = checked(value)
        if _binary_format(raw[:4]) is not None:
            raise ValueError("Undeclared native binary refused")
        return raw
    if value["path"] == contract["old_runtime"]["interpreter_binary"]["path"]:
        if binary_pin(value["path"]) != value:
            raise ValueError("Interpreter binary custody changed")
        return _BinaryEvidence(value["sha256"], Path(value["path"]).stat().st_size)
    return checked(value)


def _binary_format(magic):
    if magic[:4] in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce",
                     b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca"):
        return "mach_o"
    if magic[:4] == b"\x7fELF":
        return "elf"
    if magic[:2] == b"\x1f\x8b":
        return "gzip"
    return None


def _native_binary_evidence(value):
    """Opaque identity only: no loading, decompression or execution."""
    path = regular(value["path"])
    size = path.stat().st_size
    if size != value["bytes"] or size > NATIVE_BINARY_BYTES:
        raise ValueError("Declared native binary size/64MiB ceiling differs")
    sha, total, observed = hashlib.sha256(), 0, None
    with path.open("rb") as stream:
        while True:
            raw = stream.read(BINARY_CHUNK_BYTES)
            if not raw:
                break
            if total == 0:
                observed = _binary_format(raw[:4])
            total += len(raw)
            if total > NATIVE_BINARY_BYTES or total > value["bytes"]:
                raise ValueError("Declared native binary grew beyond bounded size")
            sha.update(raw)
    if observed != value["format"]:
        raise ValueError("Declared native binary class differs")
    if total != size or path.stat().st_size != size or sha.hexdigest() != value["sha256"]:
        raise ValueError("Declared native binary content changed")
    return _BinaryEvidence(sha.hexdigest(), total)


def _custody_profile(contract):
    if type(contract.get("schema_version")) is not int:
        raise ValueError("Integer custody profile schema required")
    if contract["schema_version"] == 1:
        if "custody_profile" in contract:
            raise ValueError("Schema1 stau custody defaults cannot select a native profile")
        return None
    if contract["schema_version"] != 2:
        raise ValueError("Explicit native schema2 required")
    profile = contract.get("custody_profile")
    keys(profile, ("name", "maximum_captured_input_bytes", "maximum_binary_file_bytes", "stream_chunk_bytes", "binding", "binary_pins"))
    if (profile["name"] != "native_custody_96MiB" or profile["maximum_captured_input_bytes"] != NATIVE_INPUT_BYTES
            or profile["maximum_binary_file_bytes"] != NATIVE_BINARY_BYTES or profile["stream_chunk_bytes"] != BINARY_CHUNK_BYTES
            or any(type(profile[k]) is not int for k in ("maximum_captured_input_bytes", "maximum_binary_file_bytes", "stream_chunk_bytes"))):
        raise ValueError("Exact declared native custody profile resources required")
    if contract["numerical_runtime"]["scope"] != "workflow_only_consumer_native_runtime_separate":
        raise ValueError("Native custody profile cannot broaden Python numerical-law qualification")
    binding = profile["binding"]
    keys(binding, ("run_id", "cycle_id", "claim_scope", "review_snapshot_sha256"))
    if any(binding[k] != contract["required_admission"][k] for k in binding):
        raise ValueError("Native custody profile accepted scope/identity differs")
    rows = profile["binary_pins"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= NATIVE_BINARY_PINS:
        raise ValueError("Bounded explicit native binary inventory required")
    protected = [contract["boundary_source"], contract["old_runtime"]["pyvenv_cfg"], contract["old_runtime"]["platform_source"],
                 *contract["old_runtime"]["workflow_sources"], *contract["qualified_numerical_modules"].values(),
                 *contract["new_law"]["numerical_modules"].values(), *contract["numerical_runtime"]["package_entry_pins"].values()]
    assertion_labels = {r["artifact"] for r in contract["qualified_identity"]["artifact_assertions"]}
    protected += [contract["artifacts"][label] for label in assertion_labels | {"receipt"}]
    protected_paths = {p["path"] for p in protected}
    forbidden_suffixes = {".py", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".md", ".txt", ".c", ".cc", ".cpp", ".h", ".hpp", ".xml", ".csv", ".tex", ".html"}
    seen = set()
    interpreter = contract["old_runtime"]["interpreter_binary"]
    queries = {r["executable"]["path"]: r["executable"] for r in contract["old_runtime"]["OS_metadata_queries"].values()}
    interpreter_resolved = str(Path(interpreter["path"]).resolve(strict=True))
    resolved_queries = {str(Path(p).resolve(strict=True)): value for p, value in queries.items()}
    if (interpreter_resolved in resolved_queries or len(resolved_queries) != len(contract["old_runtime"]["OS_metadata_queries"])):
        raise ValueError("Special interpreter/metadata query path-role conflict")
    for row in rows:
        keys(row, ("path", "sha256", "bytes", "format", "custody_role"))
        if (not Path(row["path"]).is_absolute() or row["path"] in seen or row["path"] in protected_paths
                or Path(row["path"]).suffix.lower() in forbidden_suffixes):
            raise ValueError("Native binary duplicate/source/JSON assertion classification refused")
        if (not isinstance(row["sha256"], str) or len(row["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in row["sha256"])
                or type(row["bytes"]) is not int or not 1 <= row["bytes"] <= NATIVE_BINARY_BYTES
                or row["format"] not in ("mach_o", "elf", "gzip")):
            raise ValueError("Exact bounded native binary pin/class required")
        identity = {k: row[k] for k in ("path", "sha256")}
        role = row["custody_role"]
        resolved_path = str(Path(row["path"]).resolve(strict=True))
        if resolved_path == interpreter_resolved:
            if role != "historical_interpreter" or identity != interpreter:
                raise ValueError("Historical interpreter path requires exact historical_interpreter role/identity")
        elif resolved_path in resolved_queries:
            if role != "declared_metadata_query" or identity != resolved_queries[resolved_path]:
                raise ValueError("Metadata query path requires exact declared_metadata_query role/identity")
        elif role != "accepted_snapshot":
            raise ValueError("Ordinary native binary path requires accepted_snapshot role")
        seen.add(row["path"])
    if interpreter["path"] not in seen:
        raise ValueError("Native binary inventory must explicitly include historical interpreter")
    return profile


def select_native_profile(contract, binary_pins):
    """Prepare an explicit source-only contract; this never prepares a receipt."""
    if type(contract.get("schema_version")) is not int or contract["schema_version"] != 1 or "custody_profile" in contract:
        raise ValueError("Original schema1 contract required for explicit native profile selection")
    document = json.loads(compact(contract))
    document["schema_version"] = 2
    document["custody_profile"] = {
        "name": "native_custody_96MiB", "maximum_captured_input_bytes": NATIVE_INPUT_BYTES,
        "maximum_binary_file_bytes": NATIVE_BINARY_BYTES, "stream_chunk_bytes": BINARY_CHUNK_BYTES,
        "binding": {k: document["required_admission"][k] for k in ("run_id", "cycle_id", "claim_scope", "review_snapshot_sha256")},
        "binary_pins": json.loads(compact(binary_pins))}
    _custody_profile(document)
    document["budget"]["maximum_captured_input_bytes"] = NATIVE_INPUT_BYTES
    _budget(document["budget"], document)
    return document


def _input_limit(contract):
    profile = _custody_profile(contract)
    return MAX_INPUT_BYTES if profile is None else profile["maximum_captured_input_bytes"]


def _native_profile_custody(contract, snapshot, custody_pins):
    profile = _custody_profile(contract)
    if profile is None:
        return
    cycles = [r for r in snapshot["events"] if r["event"] == "cycle"]
    if not cycles or cycles[-1]["cycle_id"] != contract["required_admission"]["cycle_id"]:
        raise ValueError("Native profile actual accepted cycle differs")
    root = Path(contract["run_directory"])
    bound = {}
    for value in snapshot["registration"]["bindings"] + cycles[-1]["snapshots"]:
        path = Path(value["path"])
        if not path.is_absolute():
            path = root / path
        path = str(path.absolute())
        if path in bound and bound[path] != value["sha256"]:
            raise ValueError("Inconsistent native accepted snapshot source identity")
        bound[path] = value["sha256"]
    retained = {p["path"]: p["sha256"] for p in custody_pins}
    for row in profile["binary_pins"]:
        if retained.get(row["path"]) != row["sha256"]:
            raise ValueError("Declared native binary absent from retained custody")
        if row["custody_role"] == "accepted_snapshot" and bound.get(row["path"]) != row["sha256"]:
            raise ValueError("Declared native binary absent from genuine accepted snapshot custody")


def _same_evidence(left, right):
    return len(left) == len(right) and _evidence_sha(left) == _evidence_sha(right)


def checked(pin_value):
    keys(pin_value, ("path", "sha256"))
    raw = read(pin_value["path"])
    if hashlib.sha256(raw).hexdigest() != pin_value["sha256"]:
        raise ValueError("Source custody changed: " + pin_value["path"])
    return raw


def fresh(path):
    out = Path(path)
    if not out.is_absolute() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("Absolute ordinary output directory required")
    if out.exists():
        raise FileExistsError("Fresh absent output directory required")
    out.mkdir(parents=True)
    return out


def save(path, value):
    raw = compact(value)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("8MiB metadata output ceiling")
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    if path.exists():
        raise FileExistsError("Immutable metadata output already exists")
    temporary.rename(path)
    return pin(path)


def validate(contract):
    fields = ("schema_version", "boundary_source", "run_directory", "old_runtime",
              "required_admission", "artifacts", "qualified_identity", "qualified_numerical_modules",
              "new_law", "numerical_runtime", "budget")
    if type(contract.get("schema_version")) is not int or contract["schema_version"] not in (1, 2):
        raise ValueError("Integer historical qualification schema1 or explicit native schema2 required")
    keys(contract, fields if contract["schema_version"] == 1 else (*fields, "custody_profile"))
    runtime = contract["old_runtime"]
    keys(runtime, ("interpreter_invocation", "interpreter_binary", "prefix", "base_prefix", "pyvenv_cfg", "platform_source", "OS_metadata_queries",
                   "cwd", "environment", "workflow_root", "workflow_sources"))
    if not Path(runtime["interpreter_invocation"]).is_absolute() or not Path(runtime["cwd"]).is_dir():
        raise ValueError("Exact original interpreter/cwd required")
    if str(Path(runtime["interpreter_invocation"]).resolve(strict=True)) != runtime["interpreter_binary"]["path"]:
        raise ValueError("Interpreter invocation does not resolve to pinned binary")
    if runtime["environment"].get("PYTHONPATH") != runtime["workflow_root"]:
        raise ValueError("Original workflow PYTHONPATH required")
    keys(runtime["OS_metadata_queries"], ("uname", "file"))
    literal_target = platform._follow_symlinks(runtime["interpreter_invocation"])
    if str(Path(literal_target).resolve(strict=True)) != runtime["interpreter_binary"]["path"]:
        raise ValueError("Literal stdlib interpreter target differs from pinned binary")
    for name, arguments in (("uname", ["-p"]), ("file", ["-b", literal_target])):
        query = runtime["OS_metadata_queries"][name]
        keys(query, ("executable", "arguments"))
        if (query["arguments"] != arguments
                or shutil.which(name, path=runtime["environment"].get("PATH")) != query["executable"]["path"]):
            raise ValueError("Exact approved-context resolved metadata command/target required")
    if not isinstance(runtime["workflow_sources"], list) or not 1 <= len(runtime["workflow_sources"]) <= MAX_WORKFLOW_FILES:
        raise ValueError("Bounded complete original Python workflow inventory required")
    admission = contract["required_admission"]
    keys(admission, ("action", "run_id", "cycle_id", "claim_scope", "review_snapshot_sha256", "review_event_sha256", "checks"))
    if admission["action"] != "reuse" or set(admission["review_event_sha256"]) != set(ROLES):
        raise ValueError("Exact reuse and all three role decisions required")
    if not admission["checks"] or set(admission["checks"].values()) != {"integrity", "scientific"}:
        raise ValueError("Integrity and scientific qualification checks required")
    if not isinstance(contract["artifacts"], dict) or "receipt" not in contract["artifacts"] or not 1 <= len(contract["artifacts"]) <= 32:
        raise ValueError("Bounded explicit historical artifacts including receipt required")
    keys(contract["qualified_identity"], ("artifact_assertions",))
    assertions = contract["qualified_identity"]["artifact_assertions"]
    if not isinstance(assertions, list) or not 1 <= len(assertions) <= 128:
        raise ValueError("Explicit bounded historical identity assertions required")
    for row in assertions:
        if set(row) not in ({"artifact", "pointer", "expected"}, {"artifact", "pointer", "expected_sha256"}):
            raise ValueError("Exact artifact assertion fields required")
        if row["artifact"] not in contract["artifacts"] or not isinstance(row["pointer"], str):
            raise ValueError("Assertion must reference a declared historical artifact")
    keys(contract["new_law"], ("artifacts", "numerical_modules"))
    if not isinstance(contract["new_law"]["artifacts"], dict) or not set(contract["new_law"]["artifacts"]).issubset(contract["artifacts"]):
        raise ValueError("New preserved artifacts must name original qualified artifacts")
    keys(contract["numerical_runtime"], ("scope", "interpreter_binary", "prefix", "base_prefix", "machine_facts", "recorded_context",
                                       "package_entry_pins", "environment"))
    keys(contract["numerical_runtime"]["recorded_context"], ("platform", "python", "packages_sha256"))
    if contract["numerical_runtime"]["scope"] not in ("python_numerical_law", "workflow_only_consumer_native_runtime_separate"):
        raise ValueError("Explicit numerical-versus-workflow qualification scope required")
    if not isinstance(contract["numerical_runtime"]["package_entry_pins"], dict) or not 0 <= len(contract["numerical_runtime"]["package_entry_pins"]) <= 64:
        raise ValueError("Bounded explicit numerical package entries required")
    if contract["numerical_runtime"]["scope"] == "python_numerical_law" and not contract["numerical_runtime"]["package_entry_pins"]:
        raise ValueError("Python numerical law must bind actual numerical packages")
    if contract["numerical_runtime"]["interpreter_binary"] != runtime["interpreter_binary"]:
        raise ValueError("New numerical interpreter differs from old qualification")
    if set(contract["qualified_numerical_modules"]) != set(contract["new_law"]["numerical_modules"]):
        raise ValueError("New numerical-law module inventory differs")
    if not 0 <= len(contract["qualified_numerical_modules"]) <= 64:
        raise ValueError("Bounded qualified numerical module inventory required")
    if any(not name.startswith("ravel.physics.") for name in contract["qualified_numerical_modules"]):
        raise ValueError("Explicit qualified physics module names required")
    _custody_profile(contract)
    _budget(contract["budget"], contract)
    if contract["boundary_source"] != pin(Path(__file__).resolve()):
        raise ValueError("Historical boundary source differs")
    return contract


def resource_bounds(contract=None):
    return {"metadata_children_per_preparation": 1, "metadata_children_per_worker": 2,
            "OS_metadata_queries_per_child": 2, "OS_metadata_query_seconds": 1.,
            "OS_metadata_query_output_bytes": 4096, "maximum_processes_in_gate_tree": 3,
            "OS_metadata_queries_serial": True, "maximum_process_launches_per_gate": 4,
            "maximum_process_launches_per_preparation": 4, "maximum_process_launches_per_worker": 8,
            "peak_processes_including_calling_worker": 4, "peak_processes_including_outer_supervisor": 5,
            "preparation_launches_including_worker_and_supervisor": 6,
            "worker_launches_including_worker_and_supervisor": 10,
            "registered_anchor_forks_per_gate": 1, "registered_ownership_ack_seconds": 1.,
            "owner_registry_output_bytes": 1024**2, "owner_global_cleanup_seconds": 3.,
            "owner_cleanup_separate_from_active_stage_clock": True,
            "owner_kernel_observer_charges": 4096, "ACK_observer_charges_per_role": 16,
            "ACK_roles_per_gate": 2, "identity_getsid_calls_in_addition_to_observer_charges": True,
            "metadata_child_seconds": CHILD_SECONDS, "maximum_file_bytes": MAX_FILE_BYTES,
            "maximum_captured_input_bytes": MAX_INPUT_BYTES if contract is None else _input_limit(contract), "maximum_output_bytes": MAX_OUTPUT_BYTES,
            "maximum_interpreter_binary_bytes": MAX_INTERPRETER_BYTES, "interpreter_hash_buffer_bytes": 1024**2,
            "maximum_source_pins": MAX_PINS, "maximum_workflow_source_files": MAX_WORKFLOW_FILES,
            "new_scientific_calls": 0, "requested_BLAS_threads": 1, "native_thread_ceiling_measured": False,
            "proposed_metadata_child_RSS_ceiling_MiB": 512, "RSS_ceiling_enforced_by_library": False,
            "proposed_preimport_anchor_RSS_ceiling_MiB": 512, "anchor_RSS_ceiling_enforced_by_library": False,
            "worker_inner_seconds": 130., "solver_work_cutoff_seconds": 120.,
            "initial_capture_compile_gate_seconds": 20., "final_gate_reservation_seconds": 10.,
            "complete_worker_seconds": 150., "completion_guaranteed": False}


def _budget(budget, contract=None):
    fixed = resource_bounds(contract)
    keys(budget, fixed)
    varied = {"worker_inner_seconds", "solver_work_cutoff_seconds", "initial_capture_compile_gate_seconds",
              "final_gate_reservation_seconds", "complete_worker_seconds"}
    if any(compact(budget[k]) != compact(v) for k, v in fixed.items() if k not in varied):
        raise ValueError("Exact bounded historical metadata resources required")
    if any(isinstance(budget[k], bool) or not isinstance(budget[k], (int, float))
           or not math.isfinite(budget[k]) or not 0 < budget[k] <= 3600 for k in varied):
        raise ValueError("Finite explicit worker phase deadlines required")
    if (budget["final_gate_reservation_seconds"] > CHILD_SECONDS
            or budget["initial_capture_compile_gate_seconds"] > budget["worker_inner_seconds"]
            or budget["solver_work_cutoff_seconds"] != budget["worker_inner_seconds"]-budget["final_gate_reservation_seconds"]
            or budget["complete_worker_seconds"] < budget["worker_inner_seconds"]):
        raise ValueError("Worker deadline reservation arithmetic differs")


def _check_sources(contract):
    validate(contract)
    all_pins = [contract["boundary_source"],
                contract["old_runtime"]["pyvenv_cfg"],
                contract["old_runtime"]["platform_source"],
                *[v["executable"] for v in contract["old_runtime"]["OS_metadata_queries"].values()],
                *contract["old_runtime"]["workflow_sources"], *contract["artifacts"].values(),
                *contract["qualified_numerical_modules"].values(), *contract["new_law"]["artifacts"].values(),
                *contract["new_law"]["numerical_modules"].values(),
                *contract["numerical_runtime"]["package_entry_pins"].values()]
    profile = _custody_profile(contract)
    if profile is not None:
        all_pins += [{k: r[k] for k in ("path", "sha256")} for r in profile["binary_pins"]]
    binary = contract["old_runtime"]["interpreter_binary"]
    inventory = {binary["path"]: _checked_custody(binary, contract)}
    for value in all_pins:
        raw = _checked_custody(value, contract)
        if value["path"] in inventory and not _same_evidence(inventory[value["path"]], raw):
            raise ValueError("Inconsistent repeated source")
        inventory[value["path"]] = raw
        if len(inventory) > MAX_PINS or sum(map(len, inventory.values())) > _input_limit(contract):
            raise ValueError("Historical input count/aggregate ceiling")
    workflow = Path(contract["old_runtime"]["workflow_root"])
    declared = {p["path"] for p in contract["old_runtime"]["workflow_sources"]}
    actual = set()
    for path in (workflow / "ravel").rglob("*.py"):
        actual.add(str(path.absolute()))
        if len(actual) > MAX_WORKFLOW_FILES:
            raise ValueError("Workflow source inventory ceiling")
    if declared != actual:
        raise ValueError("Original workflow source inventory changed")
    for p in declared:
        if not Path(p).is_relative_to(workflow):
            raise ValueError("Workflow source escaped original root")
    for key, value in contract["new_law"]["artifacts"].items():
        if not _same_evidence(_checked_custody(contract["artifacts"][key], contract), _checked_custody(value, contract)):
            raise ValueError("New operative numerical law differs: " + key)
    for name, old in contract["qualified_numerical_modules"].items():
        if checked(old) != checked(contract["new_law"]["numerical_modules"][name]):
            raise ValueError("New numerical module differs: " + name)
    actual_receipt = json.loads(checked(contract["artifacts"]["receipt"]))
    if actual_receipt["command"][0] != contract["old_runtime"]["interpreter_invocation"]:
        raise ValueError("Historical virtualenv invocation differs from actual qualified stage")
    return inventory


def _pointer(document, pointer):
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("Exact JSON pointer required")
    current = document
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        current = current[int(key)] if isinstance(current, list) else current[key]
    return current


def machine_facts():
    if not hasattr(os, "uname"):
        raise ValueError("This source-only machine observer requires POSIX")
    value = os.uname()
    return {"sys_platform": sys.platform, "system": value.sysname, "release": value.release,
            "version": value.version, "machine": value.machine,
            "mac_version": platform.mac_ver()[0] if sys.platform == "darwin" else "",
            "pointer_bits": 64 if sys.maxsize > 2**32 else 32}


def _new_numeric_runtime(contract, *, old_context=False):
    """Permit a different workflow, with the same recorded numerical runtime."""
    runtime = contract["numerical_runtime"]
    observed = {"python": sys.version,
                "packages_sha256": digest(sorted((d.metadata["Name"], d.version)
                    for d in importlib.metadata.distributions() if d.metadata.get("Name")))}
    expected = {k: runtime["recorded_context"][k] for k in observed}
    if observed != expected or machine_facts() != runtime["machine_facts"]:
        raise ValueError("Unqualified new numerical interpreter/packages")
    if old_context and platform.platform() != runtime["recorded_context"]["platform"]:
        raise ValueError("Old genuine platform context differs")
    if binary_pin(Path(sys.executable).resolve()) != runtime["interpreter_binary"]:
        raise ValueError("New numerical interpreter binary differs")
    if sys.prefix != runtime["prefix"] or sys.base_prefix != runtime["base_prefix"]:
        raise ValueError("New Python virtualenv/site-package prefix differs")
    if any(os.environ.get(k) != v for k, v in runtime["environment"].items()):
        raise ValueError("New numerical environment differs")
    for name, expected in runtime["package_entry_pins"].items():
        module = importlib.import_module(name)
        if pin(Path(module.__file__).absolute()) != expected:
            raise ValueError("New loaded numerical package entry differs: " + name)
    mapping = contract["qualified_numerical_modules"] if old_context else contract["new_law"]["numerical_modules"]
    for name, expected in mapping.items():
        module = importlib.import_module(name)
        if pin(Path(module.__file__).absolute()) != expected:
            raise ValueError("New actual loaded numerical module differs: " + name)
    return observed


def _metadata_request(contract, command, options, used):
    """Exact stdlib platform queries only; pure admission, no command execution."""
    for name, expected in contract["old_runtime"]["OS_metadata_queries"].items():
        if command in ([name, *expected["arguments"]], [expected["executable"]["path"], *expected["arguments"]]):
            if name in used:
                raise RuntimeError("OS metadata command already attempted")
            if name == "uname":
                if options != {"stderr": subprocess.DEVNULL, "text": True, "encoding": "utf8"}:
                    raise RuntimeError("Exact uname metadata options required")
            elif options != {"stderr": subprocess.DEVNULL, "env": dict(os.environ, LC_ALL="C")}:
                raise RuntimeError("Exact file metadata locale/options required")
            if name == "file" and binary_pin(Path(expected["arguments"][-1]).resolve()) != contract["old_runtime"]["interpreter_binary"]:
                raise ValueError("Literal file target resolved binary changed")
            return name, expected
    raise RuntimeError("Undeclared OS metadata command/argv/target refused")


PHASE_PROGRESS_MAX_BYTES = 64 * 1024
PHASE_PROGRESS_NAMES = frozenset(("child_enter", "source_custody_checked", "old_workflow_import_begin", "old_workflow_import_end", "runtime_identity_begin", "runtime_identity_end", "old_snapshot_begin", "old_snapshot_end", "snapshot_validation_begin", "snapshot_validation_end", "binding_custody_begin", "binding_custody_end", "artifact_assertions_begin", "artifact_assertions_end", "ending_custody_begin", "ending_custody_end", "child_validation_written"))


def _phase_progress(out, phase, started):
    """Bounded append-only diagnostics; never a historical admission signal."""
    if phase not in PHASE_PROGRESS_NAMES:
        raise ValueError("unknown historical diagnostic phase")
    path = Path(out) / "phase-progress.jsonl"
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("diagnostic path traverses a symlink")
    if not path.parent.is_dir():
        raise ValueError("existing diagnostic directory required")
    previous = b""
    observed = None
    if path.exists():
        before = regular(path).stat()
        if before.st_size > PHASE_PROGRESS_MAX_BYTES:
            raise ValueError("historical diagnostic byte ceiling")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            previous = stream.read(PHASE_PROGRESS_MAX_BYTES + 1)
            final_read = os.fstat(stream.fileno())
        after = regular(path).stat()
        fields = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if (len(previous) > PHASE_PROGRESS_MAX_BYTES or fields(before) != fields(opened)
                or fields(opened) != fields(final_read) or fields(final_read) != fields(after)):
            raise ValueError("historical diagnostic changed during read")
        observed = fields(after)
        if not previous.endswith(b"\n"):
            raise ValueError("incomplete diagnostic row")
        for index, line in enumerate(previous.splitlines(), 1):
            old_row = json.loads(line)
            if old_row.get("sequence") != index or old_row.get("phase") not in PHASE_PROGRESS_NAMES:
                raise ValueError("historical diagnostic row changed")
        if any(json.loads(line)["phase"] == phase for line in previous.splitlines()):
            raise ValueError("historical diagnostic phase already observed")
    sequence = len(previous.splitlines()) + 1
    if sequence > len(PHASE_PROGRESS_NAMES):
        raise ValueError("historical diagnostic phase census exceeded")
    row = {"sequence": sequence, "phase": phase, "pid": os.getpid(),
           "elapsed_seconds": time.monotonic() - started, "scientific_calls": 0,
           "scope": "diagnostic progress only; no admission or completed phase inferred"}
    raw = compact(row) + b"\n"
    if len(previous) + len(raw) > PHASE_PROGRESS_MAX_BYTES:
        raise ValueError("historical diagnostic byte ceiling")
    flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW
    if observed is None:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "ab") as stream:
        opened = os.fstat(stream.fileno())
        fields = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        if (observed is None and opened.st_size != 0) or (observed is not None and fields(opened) != observed):
            raise ValueError("diagnostic changed before append")
        stream.write(raw); stream.flush()
        final = os.fstat(stream.fileno())
    current = regular(path).stat()
    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns):
        raise ValueError("diagnostic changed after append")


def _child_observation(out, child, exhausted, started):
    """Record actual poll result before closure can mask the child outcome."""
    return save(Path(out) / "child-observation.json", {
        "pid": child.pid, "observed_returncode": child.poll(), "exhausted": exhausted,
        "elapsed_seconds": time.monotonic() - started,
        "scientific_calls": 0, "scope": "point observation; no quiescence or admission claim"})


def _historical_child(contract, out):
    """Only this source-only child imports the genuine old workflow package."""
    started = time.monotonic()
    _phase_progress(out, "child_enter", started)
    if any(name == "ravel" or name.startswith("ravel.") for name in sys.modules):
        raise ValueError("Already loaded ravel before old-context installation")
    inventory = _check_sources(contract)
    _phase_progress(out, "source_custody_checked", started)
    runtime = contract["old_runtime"]
    if pin(Path(platform.__file__).absolute()) != runtime["platform_source"]:
        raise ValueError("Actually loaded qualified stdlib platform source differs")
    if (sys.executable != runtime["interpreter_invocation"]
            or str(Path(sys.executable).resolve()) != runtime["interpreter_binary"]["path"]
            or sys.prefix != runtime["prefix"] or sys.base_prefix != runtime["base_prefix"]
            or str(Path.cwd()) != runtime["cwd"]):
        raise ValueError("Child interpreter/cwd differs")
    if any(os.environ.get(k) != v for k, v in runtime["environment"].items()):
        raise ValueError("Child relevant runtime environment differs")
    queries = []
    original_popen = subprocess.Popen
    def metadata_query(command, *args, **kwargs):
        if args:
            raise RuntimeError("Undeclared OS metadata positional options refused")
        name, expected = _metadata_request(contract, command, kwargs, [r["name"] for r in queries])
        _checked_custody(expected["executable"], contract)
        stamp = time.monotonic()
        row = {"name": name, "command": [expected["executable"]["path"], *expected["arguments"]],
               "executable": expected["executable"]}
        queries.append(row)  # Attempt is charged before spawn.
        process = original_popen(row["command"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                 env=kwargs.get("env"))
        row["pid"] = process.pid
        streams = [process.stdout, process.stderr]; chunks = {p: [] for p in streams}
        total, deadline = 0, stamp + 1.
        try:
            while streams:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("1s OS metadata query deadline")
                ready, _, _ = select.select(streams, [], [], remaining)
                for stream in ready:
                    raw = os.read(stream.fileno(), min(4097-total, 4096))
                    if not raw:
                        streams.remove(stream)
                    else:
                        total += len(raw)
                        if total > 4096:
                            raise ValueError("4KiB OS metadata query output ceiling")
                        chunks[stream].append(raw)
            process.wait(timeout=max(.001, deadline-time.monotonic()))
            stdout = b"".join(chunks[process.stdout]); stderr = b"".join(chunks[process.stderr])
            row.update(exit_code=process.returncode, stdout_sha256=hashlib.sha256(stdout).hexdigest(),
                       stderr_sha256=hashlib.sha256(stderr).hexdigest(), elapsed_seconds=time.monotonic()-stamp)
            _checked_custody(expected["executable"], contract)
            if name == "file" and binary_pin(Path(expected["arguments"][-1]).resolve()) != runtime["interpreter_binary"]:
                raise ValueError("Literal file target resolved binary changed")
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, row["command"])
            return stdout.decode(kwargs.get("encoding", "utf8")) if kwargs.get("text") else stdout
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=1.)
            for stream in chunks:
                stream.close()
    subprocess.check_output = metadata_query
    subprocess.Popen = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Undeclared child/native command refused"))
    subprocess.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Undeclared child/native command refused"))
    sys.path.insert(0, runtime["workflow_root"])
    _phase_progress(out, "old_workflow_import_begin", started)
    from ravel.workflow import physics_review, execution, science
    _phase_progress(out, "old_workflow_import_end", started)
    for module in (physics_review, execution, science):
        expected_path = Path(runtime["workflow_root"]) / Path(*module.__name__.split(".")).with_suffix(".py")
        expected = next(p for p in runtime["workflow_sources"] if p["path"] == str(expected_path))
        if pin(Path(module.__file__).absolute()) != expected:
            raise ValueError("Actually loaded old workflow module differs: " + module.__name__)
    _phase_progress(out, "runtime_identity_begin", started)
    _new_numeric_runtime(contract, old_context=True)
    _phase_progress(out, "runtime_identity_end", started)
    forbidden = []
    def fail(name):
        def blocked(*args, **kwargs):
            forbidden.append(name)
            raise RuntimeError("Historical source gate forbids numerical work: " + name)
        return blocked
    for name, expected in contract["qualified_numerical_modules"].items():
        module = importlib.import_module(name)
        if pin(Path(module.__file__).absolute()) != expected:
            raise ValueError("Old imported numerical runtime differs: " + name)
        for attribute in ("run", "_compile"):
            if hasattr(module, attribute):
                setattr(module, attribute, fail(name + "." + attribute))
        for classname in ("AnalyticPublishedJoint", "BackgroundAuxBlock", "IndependentSourceOracle",
                          "JointProfiler", "AnalyticJointProfiler"):
            if hasattr(module, classname):
                setattr(getattr(module, classname), "__init__", fail(name + "." + classname))
    if "pyhf" in contract["numerical_runtime"]["package_entry_pins"]:
        import pyhf
        pyhf.Workspace = fail("pyhf.Workspace"); pyhf.Model = fail("pyhf.Model")
    if "scipy" in contract["numerical_runtime"]["package_entry_pins"]:
        import scipy.optimize
        scipy.optimize.minimize = fail("scipy.optimize.minimize"); scipy.optimize.linprog = fail("scipy.optimize.linprog")
    # A metadata helper must not spawn an undeclared native or second helper.
    subprocess.Popen = fail("subprocess.Popen")
    subprocess.run = fail("subprocess.run")
    # Keep the two separately counted serial queries for genuine runtime_context().
    root = Path(contract["run_directory"])
    _phase_progress(out, "old_snapshot_begin", started)
    snapshot = physics_review.snapshot(root, action="reuse")
    _phase_progress(out, "old_snapshot_end", started)
    _phase_progress(out, "snapshot_validation_begin", started)
    errors = physics_review.validate_snapshot(snapshot, require_admission=True)
    _phase_progress(out, "snapshot_validation_end", started)
    if errors:
        raise ValueError("Genuine historical admission failed: " + "; ".join(errors))
    required = contract["required_admission"]
    cycle = [e for e in snapshot["events"] if e["event"] == "cycle"][-1]
    reviews = [e for e in snapshot["events"] if e["event"] == "review" and e["cycle_id"] == cycle["cycle_id"]]
    if (digest(snapshot) != required["review_snapshot_sha256"] or snapshot["registration"]["run_id"] != required["run_id"]
            or cycle["cycle_id"] != required["cycle_id"]
            or {e["role"]: e["sha256"] for e in reviews} != required["review_event_sha256"]
            or any(e["verdict"] != "accept" or e["claim_scope"] != required["claim_scope"] for e in reviews)):
        raise ValueError("Exact accepted historical identity/scope differs")
    policy = snapshot["registration"]["policy"]
    kinds = {r["id"]: r["kind"] for r in policy["required_checks"]}
    scope = policy["claim_scopes"][required["claim_scope"]]
    if any(kinds.get(k) != kind or k not in scope["checks"] for k, kind in required["checks"].items()):
        raise ValueError("Accepted scope lacks declared scientific/integrity obligations")
    _phase_progress(out, "binding_custody_begin", started)
    bound = {}
    for value in snapshot["registration"]["bindings"] + cycle["snapshots"]:
        path = Path(value["path"])
        if not path.is_absolute():
            path = root / path
        normalized = {"path": str(path.absolute()), "sha256": value["sha256"]}
        inventory[normalized["path"]] = _checked_custody(normalized, contract)
        bound[normalized["path"]] = normalized["sha256"]
        if len(inventory) > MAX_PINS or sum(map(len, inventory.values())) > _input_limit(contract):
            raise ValueError("Historical custody inventory ceiling")
    for eventpath in [root / "logs/physics_review/registration.json", root / "logs/physics_review/head.json",
                      *sorted((root / "logs/physics_review/events").glob("*.json"))]:
        inventory[str(eventpath)] = read(eventpath)
        if len(inventory) > MAX_PINS or sum(map(len, inventory.values())) > _input_limit(contract):
            raise ValueError("Historical custody inventory ceiling")
    _phase_progress(out, "binding_custody_end", started)
    docs = {}
    for label, value in contract["artifacts"].items():
        if bound.get(value["path"]) != value["sha256"]:
            raise ValueError("Historical artifact absent from genuine accepted custody: " + label)
        raw = _checked_custody(value, contract)
        try:
            docs[label] = None if isinstance(raw, _BinaryEvidence) else json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            docs[label] = None  # Non-JSON source/plugin artifacts remain byte-bound.
    receipt = docs["receipt"]
    state_path = root / "execution_state.json"
    state_raw = read(state_path)
    inventory[str(state_path)] = state_raw
    current_state = json.loads(state_raw)
    if current_state["stages"].get(receipt["stage"]) != receipt or receipt["status"] != "succeeded":
        raise ValueError("Current historical execution ledger differs from qualified receipt")
    if receipt["command"][0] != runtime["interpreter_invocation"]:
        raise ValueError("Historical virtualenv invocation differs from actual qualified stage")
    if execution.load_execution(root)["stages"].get(receipt["stage"]) != receipt or receipt["status"] != "succeeded":
        raise ValueError("Historical receipt is not current successful attempt")
    if {k: receipt["runtime"][k] for k in ("platform", "python", "packages_sha256")} != contract["numerical_runtime"]["recorded_context"]:
        raise ValueError("Numerical runtime is not the actually qualified receipt runtime")
    if not any(r["attempt_id"] == receipt["attempt_id"] and r["receipt_sha256"] == receipt["receipt_sha256"]
               for r in cycle["receipts"]):
        raise ValueError("Historical current attempt differs from accepted receipt")
    for name in required["checks"]:
        check = next(r for r in cycle["checks"] if r["id"] == name)
        if check["status"] != "pass" or receipt["attempt_id"] not in check["attempt_ids"]:
            raise ValueError("Historical check is not passing on current attempt")
    _phase_progress(out, "artifact_assertions_begin", started)
    for assertion in contract["qualified_identity"]["artifact_assertions"]:
        value = _pointer(docs[assertion["artifact"]], assertion["pointer"])
        if ("expected" in assertion and compact(value) != compact(assertion["expected"])) or (
                "expected_sha256" in assertion and digest(value) != assertion["expected_sha256"]):
            raise ValueError("Historical artifact identity assertion differs")
    if len(inventory) > MAX_PINS or sum(map(len, inventory.values())) > _input_limit(contract):
        raise ValueError("Historical custody inventory ceiling")
    _phase_progress(out, "artifact_assertions_end", started)
    pins = [{"path": p, "sha256": _evidence_sha(raw)} for p, raw in sorted(inventory.items())]
    _native_profile_custody(contract, snapshot, pins)
    _phase_progress(out, "ending_custody_begin", started)
    for value in pins:
        _checked_custody(value, contract)
    _phase_progress(out, "ending_custody_end", started)
    if forbidden:
        raise ValueError("Forbidden historical numerical entry called")
    result = {"schema_version": 1, "status": "validated", "contract_sha256": digest(contract),
              "boundary_source": contract["boundary_source"], "snapshot": snapshot, "snapshot_sha256": digest(snapshot),
              "custody_pins": pins, "captured_bytes": sum(map(len, inventory.values())),
              "old_attempt_id": receipt["attempt_id"], "old_receipt_sha256": receipt["receipt_sha256"],
              "execution_state_pin": {"path": str(state_path), "sha256": hashlib.sha256(state_raw).hexdigest()},
              "child_pid": os.getpid(), "child_elapsed_seconds": time.monotonic() - started,
              "observed_interpreter": str(Path(sys.executable).resolve()), "observed_cwd": str(Path.cwd()),
              "observed_invocation": sys.executable, "observed_prefix": sys.prefix, "observed_base_prefix": sys.base_prefix,
              "OS_metadata_queries": queries,
              "observed_environment": {k: os.environ.get(k) for k in runtime["environment"]},
              "forbidden_numerical_entries": forbidden, "scientific_calls": 0,
              "scope": "Historical provenance and current byte custody only; no inherited scientific approval/lease or actor authentication"}
    save(out / "child-validation.json", result)
    _phase_progress(out, "child_validation_written", started)


def _registration_module():
    """Stdlib source bootstrap only; never import a new ravel namespace in old child."""
    import types
    descriptor_path=os.environ.get("RAVEL_REGISTERED_HELPER_OWNER")
    if not descriptor_path:raise ValueError("Owner-backed historical preparation/worker gate required; no standalone fallback")
    descriptor=json.loads(read(descriptor_path))
    source=descriptor["declaration"]["registration_source"]
    raw=checked(source)
    module=types.ModuleType("registered_metadata_bootstrap");module.__file__=source["path"]
    exec(compile(raw,source["path"],"exec"),module.__dict__)  # Captured checked bytes; no pycache/ravel import.
    module.validate_declaration(descriptor["declaration"])
    return module,descriptor


def validate_historical(contract, output_dir, *, timeout_seconds=CHILD_SECONDS, registration_key="preparation"):
    out = fresh(output_dir)  # admission before source or child work
    started = time.monotonic()
    attempted = None
    child = None
    result_pin = None
    try:
        if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= CHILD_SECONDS:
            raise ValueError("Positive remaining historical deadline at most10s required")
        deadline = started + timeout_seconds
        registration,owner_descriptor=_registration_module()
        route=next((r for r in owner_descriptor["declaration"]["helpers"] if r["key"]==registration_key),None)
        if (route is None or route["contract_sha256"]!=digest(contract)
                or route["helper_source"]!=pin(Path(__file__).resolve())
                or out!=Path(route["request_root"])
                or route["interpreter_binary"]!=contract["old_runtime"]["interpreter_binary"]
                or route["interpreter_invocation"]!=contract["old_runtime"]["interpreter_invocation"]):
            raise ValueError("Historical helper route differs from approved static declaration")
        _check_sources(contract)
        if time.monotonic() >= deadline:
            raise TimeoutError("Historical remaining deadline exhausted before child")
        request = save(out / "request.json", contract)
        runtime = contract["old_runtime"]
        environment = os.environ.copy()
        for key, value in runtime["environment"].items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        environment[registration.KEY_ENV]=registration_key
        environment[registration.DEADLINE_ENV]=repr(deadline)
        command = [runtime["interpreter_invocation"], str(Path(__file__).resolve()), "--child", str(out / "request.json")]
        save(out / "started.json", {"command": command, "cwd": runtime["cwd"], "request": request,
                                   "timeout_seconds": timeout_seconds, "metadata_children": 1, "registration_anchor": 1, "registration_declaration_sha256": registration.digest(owner_descriptor["declaration"]), "scientific_calls": 0})
        with (out / "stdout").open("xb") as stdout, (out / "stderr").open("xb") as stderr:
            # Nonempty transport headers avoid undeclared empty science outputs.
            stdout.write(b"Historical metadata child stdout follows\n"); stdout.flush()
            stderr.write(b"Historical metadata child stderr follows\n"); stderr.flush()
            _check_sources(contract)
            if time.monotonic() >= deadline:
                raise TimeoutError("Historical remaining deadline exhausted before spawn")
            child = subprocess.Popen(command, cwd=runtime["cwd"], env=environment,
                                     stdout=stdout, stderr=stderr, start_new_session=True)
            attempted = child.pid
            save(out / "child-started.json", {"pid": child.pid, "deadline_monotonic": deadline,
                                              "command": command, "metadata_children": 1})
            exhausted = None
            while child.poll() is None:
                size = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
                if size > MAX_OUTPUT_BYTES or time.monotonic() >= deadline:
                    exhausted = "output_bytes" if size > MAX_OUTPUT_BYTES else "metadata_wall_seconds"
                    # Outer retains exact live-generation group authority; worker does not signal discovered PIDs.
                    break
                time.sleep(.02)
        observation_pin = _child_observation(out, child, exhausted, started)
        closure = registration.wait_closed(registration_key,deadline)
        if exhausted or child.returncode != 0:
            raise RuntimeError("Historical metadata admission refused: " + str(exhausted or ("child_exit_" + str(child.returncode))))
        if sum(p.stat().st_size for p in out.iterdir() if p.is_file()) > MAX_OUTPUT_BYTES:
            raise ValueError("Historical metadata output byte ceiling")
        returned = json.loads(read(out / "child-validation.json"))
        if (returned["status"] != "validated" or returned["contract_sha256"] != digest(contract)
                or returned["snapshot_sha256"] != contract["required_admission"]["review_snapshot_sha256"]
                or returned["scientific_calls"] != 0 or returned["forbidden_numerical_entries"] != []):
            raise ValueError("Historical child result identity differs")
        _check_sources(contract)
        for value in returned["custody_pins"]:
            _checked_custody(value, contract)
        if time.monotonic() >= deadline:
            raise TimeoutError("Historical remaining deadline exhausted after custody recheck")
        receipt = {"schema_version": 1, "status": "validated", "contract_sha256": digest(contract),
                   "boundary_source": contract["boundary_source"], "child_validation": pin(out / "child-validation.json"),
                   "request": request, "started": pin(out / "started.json"),
                   "child_started": pin(out / "child-started.json"),
                   "stdout": pin(out / "stdout"), "stderr": pin(out / "stderr"),
                   "observed_child_pid": attempted, "observed_exit_code": child.returncode,
                   "child_observation": observation_pin, "phase_progress": pin(out / "phase-progress.jsonl"),
                   "elapsed_seconds": time.monotonic() - started,
                   "elapsed_scope": "Observed before receipt serialization; API return additionally requires the final output scan and full gate deadline check",
                   "metadata_children": 1, "registration_anchor": 1,
                   "registered_helper": {"owner_descriptor":pin(os.environ[registration.ENV]),"closure":closure,
                       "proof":json.loads(read(out / "registration-ack.json"))["proof"],
                       "ready_proof":json.loads(read(out / "registration-ack.json"))["ready_proof"]},
                   "scientific_calls": 0,
                   "admission_class": "historical runtime/custody; never a new physics result",
                   "thread_RSS_scope": "BLAS environment requested1; native ceiling/RSS not measured or enforced by this library; root supervisor must admit/observe costs"}
        result_pin = save(out / "validation-receipt.json", receipt)
        if sum(p.stat().st_size for p in out.iterdir() if p.is_file()) > MAX_OUTPUT_BYTES:
            raise ValueError("Historical metadata output byte ceiling")
        if time.monotonic() >= deadline:
            raise TimeoutError("Historical full gate deadline exhausted after receipt serialization and output scan")
        return result_pin
    except BaseException as error:
        # No worker-issued PGID signal. Outer/anchor owns bounded cleanup even after this worker exits.
        cleanup_pending = child is not None and child.poll() is None
        # A refusal is a check this gate raised (ValueError or TimeoutError); any other exception is a crash and
        # is a typed failure, never a refusal. Both block admission of a leftover receipt (``refusal.json``).
        refused = isinstance(error, (ValueError, TimeoutError))
        trace = traceback.format_exc()
        trace_file = out / "failure-traceback.txt"
        if not refused:
            trace_file.write_text(trace, encoding="utf-8")
        save(out / "refusal.json", {"status": "refused" if refused else "failed",
                                   "class": ("historical_runtime_or_custody_admission" if refused
                                             else "historical_runtime_crash"),
                                   "failure_class": None if refused else type(error).__name__,
                                   "traceback_ref": None if refused else str(trace_file),
                                   "error_type": type(error).__name__, "error": str(error), "traceback": trace,
                                   "child_pid": attempted, "child_observed_returncode": child.poll() if child is not None else None, "returned_validation_receipt": result_pin, "admitted": False, "outer_cleanup_pending":cleanup_pending,
                                   "elapsed_seconds": time.monotonic() - started,
                                   "scientific_calls": 0, "started_fits": 0})
        raise


def _verify_current_attempt(contract, child):
    """Current mutable ledger plus exact immutable successful receipt identity."""
    state_pin = child["execution_state_pin"]
    if state_pin["path"] != str(Path(contract["run_directory"]) / "execution_state.json") or state_pin not in child["custody_pins"]:
        raise ValueError("Historical execution ledger custody binding differs")
    state = json.loads(checked(state_pin))
    qualified_receipt = json.loads(checked(contract["artifacts"]["receipt"]))
    if (state["stages"].get(qualified_receipt["stage"]) != qualified_receipt or qualified_receipt["status"] != "succeeded"
            or child["old_attempt_id"] != qualified_receipt["attempt_id"]
            or child["old_receipt_sha256"] != qualified_receipt["receipt_sha256"]):
        raise ValueError("Current historical attempt is not the qualified successful receipt")


def verify_receipt(contract, receipt_pin):
    """Zero-child hooks: immutable validated receipt AND unchanged current custody."""
    receipt_path = regular(receipt_pin["path"])
    if (receipt_path.parent / "refusal.json").exists():
        raise ValueError("Historical validation directory was refused; leftover receipt is not admitted")
    _check_sources(contract)
    _new_numeric_runtime(contract)
    receipt = json.loads(checked(receipt_pin))
    child_path = regular(receipt["child_validation"]["path"])
    if (child_path.parent / "refusal.json").exists():
        raise ValueError("Historical child-validation directory was refused; copied leftover receipt is not admitted")
    if (receipt["status"] != "validated" or receipt["contract_sha256"] != digest(contract)
            or receipt["boundary_source"] != contract["boundary_source"]
            or receipt["observed_exit_code"] != 0 or receipt["metadata_children"] != 1
            or receipt["scientific_calls"] != 0):
        raise ValueError("Historical validation receipt differs")
    request = json.loads(checked(receipt["request"]))
    if compact(request) != compact(contract):
        raise ValueError("Historical receipt request differs")
    started = json.loads(checked(receipt["started"]))
    child_started = json.loads(checked(receipt["child_started"]))
    for field in ("stdout", "stderr"):
        checked(receipt[field])
    for field in ("child_observation", "phase_progress"):
        if field in receipt:
            checked(receipt[field])
    child = json.loads(checked(receipt["child_validation"]))
    if (child["contract_sha256"] != digest(contract) or child["status"] != "validated"
            or digest(child["snapshot"]) != contract["required_admission"]["review_snapshot_sha256"]
            or child["scientific_calls"] != 0 or child["forbidden_numerical_entries"] != []):
        raise ValueError("Validated historical snapshot differs")
    runtime = contract["old_runtime"]
    registered=receipt["registered_helper"]
    descriptor=json.loads(checked(registered["owner_descriptor"]))
    proof=json.loads(checked(registered["proof"]))
    ready=json.loads(checked(registered["ready_proof"]))
    closure=json.loads(checked(registered["closure"]))
    checked(descriptor["declaration"]["registration_source"])
    if (ready["event"]!="anchor_ready" or ready["registered_proof"]!=registered["proof"]
            or ready["key"]!=proof["key"] or proof["event"]!="registered" or proof["request"]!=receipt["request"]
            or proof["declaration_sha256"]!=digest(descriptor["declaration"])
            or closure["requires_recovery"] is not False or closure["nonce"]!=descriptor["nonce"]
            or closure["key"]!=proof["key"] or closure["declaration_sha256"]!=digest(descriptor["declaration"])):
        raise ValueError("Historical registered group closure/proof differs")
    command = [runtime["interpreter_invocation"], contract["boundary_source"]["path"], "--child", receipt["request"]["path"]]
    if (started["command"] != command or child_started["command"] != command
            or started["cwd"] != runtime["cwd"] or started["request"] != receipt["request"]
            or child_started["pid"] != receipt["observed_child_pid"] or child["child_pid"] != receipt["observed_child_pid"]
            or child["observed_invocation"] != runtime["interpreter_invocation"]
            or child["observed_interpreter"] != runtime["interpreter_binary"]["path"]
            or child["observed_prefix"] != runtime["prefix"] or child["observed_base_prefix"] != runtime["base_prefix"]
            or child["observed_cwd"] != runtime["cwd"] or child["observed_environment"] != runtime["environment"]):
        raise ValueError("Historical observed process provenance differs")
    query_rows = child["OS_metadata_queries"]
    if (len(query_rows) > 2 or len({r["name"] for r in query_rows}) != len(query_rows)
            or any(r["name"] not in runtime["OS_metadata_queries"] for r in query_rows)):
        raise ValueError("Historical OS metadata query provenance differs")
    if any(r["command"] != [runtime["OS_metadata_queries"][r["name"]]["executable"]["path"],
                            *runtime["OS_metadata_queries"][r["name"]]["arguments"]]
           or r["executable"] != runtime["OS_metadata_queries"][r["name"]]["executable"] or r["exit_code"] != 0
           or not 0 <= r["elapsed_seconds"] <= 1. for r in query_rows):
        raise ValueError("Historical OS metadata query provenance differs")
    _verify_current_attempt(contract, child)
    _native_profile_custody(contract, child["snapshot"], child["custody_pins"])
    if len(child["custody_pins"]) > MAX_PINS:
        raise ValueError("Historical receipt source pin ceiling")
    total = 0
    for value in child["custody_pins"]:
        total += len(_checked_custody(value, contract))
        if total > _input_limit(contract):
            raise ValueError("Current historical custody byte ceiling")
    return child


def inputs(contract, receipt_pin):
    child = verify_receipt(contract, receipt_pin)
    receipt = json.loads(checked(receipt_pin))
    paths = {p["path"] for p in child["custody_pins"]}
    paths.add(receipt_pin["path"])
    paths.update(receipt[k]["path"] for k in ("request", "started", "child_started", "stdout", "stderr", "child_validation"))
    paths.update(receipt[k]["path"] for k in ("child_observation", "phase_progress") if k in receipt)
    return [Path(p) for p in sorted(paths)]


def execution_seconds(contract, receipt_pin):
    verify_receipt(contract, receipt_pin)
    return contract["budget"]["complete_worker_seconds"]


def hook_resource_bounds(contract, receipt_pin):
    verify_receipt(contract, receipt_pin)
    return dict(contract["budget"])


class WorkerSession:
    """Exactly initial/final metadata calls; persistent ledger blocks replay."""
    def __init__(self, contract, receipt_pin, directory, *, worker_started=None):
        self.directory = fresh(directory)
        self.contract, self.receipt = contract, receipt_pin
        self.started = time.monotonic() if worker_started is None else worker_started
        elapsed = time.monotonic() - self.started
        budget = contract["budget"]
        if not math.isfinite(elapsed) or not 0 <= elapsed < budget["worker_inner_seconds"]:
            raise ValueError("Valid worker monotonic deadline required")
        verify_receipt(contract, receipt_pin)
        self.outer_deadline = self.started + budget["worker_inner_seconds"]
        self.work_deadline = self.started + budget["solver_work_cutoff_seconds"]
        self.phases = []
        self.completed_phases = []
        save(self.directory / "session.json", {"contract_sha256": digest(contract), "receipt": receipt_pin,
                                              "metadata_child_ceiling": 2, "worker_inner_seconds": budget["worker_inner_seconds"],
                                              "solver_work_cutoff_seconds": budget["solver_work_cutoff_seconds"], "scientific_calls": 0})

    def boundary(self, phase):
        if phase not in ("initial", "final") or self.phases != ([] if phase == "initial" else ["initial"]):
            raise ValueError("Historical worker phase/call ceiling; no hook children or retries")
        if phase == "final" and self.completed_phases != ["initial"]:
            raise ValueError("Initial historical phase did not complete")
        if (self.directory / (phase + "-started.json")).exists():
            raise ValueError("Historical phase already attempted")
        deadline = self.started + self.contract["budget"]["initial_capture_compile_gate_seconds"] if phase == "initial" else self.outer_deadline
        remaining = min(CHILD_SECONDS, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Historical phase remaining deadline exhausted")
        save(self.directory / (phase + "-started.json"), {"phase": phase, "remaining_seconds": remaining,
                                                        "metadata_child_number": len(self.phases) + 1})
        self.phases.append(phase)
        result = None
        try:
            result = validate_historical(self.contract, self.directory / phase, timeout_seconds=remaining, registration_key=phase)
            if time.monotonic() >= deadline:
                raise TimeoutError("Historical full phase deadline exhausted after helper return")
            verify_receipt(self.contract, result)
            if time.monotonic() >= deadline:
                raise TimeoutError("Historical full phase deadline exhausted after custody verification")
            save(self.directory / (phase + "-returned.json"), {
                "validation_receipt": result, "scientific_calls": 0, "phase_deadline_monotonic": deadline,
                "scope": "Returned helper preserved; final serialized-phase deadline check is still pending"})
            if time.monotonic() >= deadline:
                raise TimeoutError("Historical full phase deadline exhausted after serialization")
            self.completed_phases.append(phase)
            return result
        except BaseException as error:
            save(self.directory / (phase + "-refused.json"), {
                "validation_receipt": result, "phase_completed": False, "scientific_calls": 0,
                "phase_deadline_monotonic": deadline, "observed_monotonic": time.monotonic(),
                "error_type": type(error).__name__, "error": str(error)})
            raise


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--child" or sys.flags.optimize:
        raise ValueError("Only exact nonoptimized source-validation child invocation supported")
    request = regular(sys.argv[2])
    try:
        registration,descriptor=_registration_module()
        guard=registration.bootstrap(request,float(os.environ[registration.DEADLINE_ENV]))
        save(request.parent / "registration-ack.json", {"proof":guard.proof,"ready_proof":guard.ready_proof,"owner_descriptor":pin(os.environ[registration.ENV]),"old_work_started":False})
        _historical_child(json.loads(read(request)), request.parent)
        guard.finish()
    except BaseException as error:
        save(request.parent / "child-refusal.json", {"error_type": type(error).__name__, "error": str(error),
                                                    "traceback": traceback.format_exc(), "scientific_calls": 0})
        raise
