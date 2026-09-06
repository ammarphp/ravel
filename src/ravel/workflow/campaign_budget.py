"""Conservative event reservations for single-point native campaign children.

This is allocation accounting, not a measurement of CPU cost or accepted events.
Every retained generation attempt, including a failed/interrupted attempt, is
charged its entire original requested exposure. A prepared child with no attempt
reserves its declared exposure. Callers serialize reservation creation with
``logs/campaign-allocation.lock``; the read-only function never grants approval.
"""
from pathlib import Path
from datetime import datetime
import tomllib
import re

from .execution import digest, file_hash
from .state_io import read_json
from .workflow_state import verify_approval


def _positive(value, label):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


POLICY_REGISTRATION = "inputs/budget-policy.json"
POLICY_DIRECTORY = "inputs/budget-policies"
PARENT_INPUTS = ("task_contract.json", "cost_preflight.json", "checkin1.json", "checkin1_approval.json")


def _policy_artifact(campaign, binding, load):
    if type(binding) is not dict or set(binding) != {"path", "sha256"}:
        raise ValueError("budget policy artifact requires exact path/hash binding")
    relative, expected = binding["path"], binding["sha256"]
    if (type(relative) is not str or not relative or Path(relative).is_absolute() or
            ".." in Path(relative).parts or Path(relative).as_posix() != relative or
            not relative.startswith(POLICY_DIRECTORY + "/") or
            type(expected) is not str or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
        raise ValueError("budget policy artifact path/hash is invalid")
    path = campaign / relative
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError("budget policy artifact is missing or symlinked")
    value = load(path)
    if file_hash(path) != expected:
        raise ValueError("budget policy artifact changed")
    return value


def _effective_policy(campaign, allocation, sources, load, required_sha):
    """A registered restriction is automatic; explicit pins also detect removal.

    The fixed registration and every referenced document are append-only campaign
    artifacts by convention. This is consistency checking, not filesystem access
    control or cryptographic authentication of a human approver.
    """
    if required_sha is not None and (type(required_sha) is not str or re.fullmatch(r"[0-9a-f]{64}", required_sha) is None):
        raise ValueError("required policy SHA must be a lowercase SHA256")
    registration = campaign / POLICY_REGISTRATION
    directory = campaign / POLICY_DIRECTORY
    if directory.is_symlink() or registration.is_symlink():
        raise ValueError("budget policy registration/directory cannot be symlinked")
    if not registration.exists():
        if required_sha is not None or (directory.exists() and any(directory.iterdir())):
            raise ValueError("required budget policy registration is missing")
        return allocation, None, None
    record = load(registration)
    if type(record) is not dict or set(record) != {"schema_version", "path", "sha256"} or type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("invalid budget policy registration")
    if required_sha is not None and record["sha256"] != required_sha:
        raise ValueError("registered budget policy differs from required policy SHA")
    policy = _policy_artifact(campaign, {key: record[key] for key in ("path", "sha256")}, load)
    keys = {"schema_version", "policy_id", "original_allocation_events", "effective_allocation_events",
            "parent_bindings", "inventory_basis", "reason", "scope"}
    if type(policy) is not dict or set(policy) != keys or type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("invalid budget restriction schema")
    if any(type(policy[key]) is not str or not policy[key].strip() for key in ("policy_id", "reason", "scope")):
        raise ValueError("budget restriction requires explicit identity, reason and scope")
    original = _positive(policy["original_allocation_events"], "policy original allocation")
    effective = _positive(policy["effective_allocation_events"], "policy effective allocation")
    if original != allocation or effective >= original:
        raise ValueError("budget policy must strictly lower its actual bound parent allocation")
    expected = {"inputs/" + name: sources[str(campaign / "inputs" / name)] for name in PARENT_INPUTS}
    if policy["parent_bindings"] != expected:
        raise ValueError("budget policy parent approval binding changed")
    basis = _policy_artifact(campaign, policy["inventory_basis"], load)
    return effective, {"path": record["path"], "sha256": record["sha256"], "policy_id": policy["policy_id"],
                       "registration_path": POLICY_REGISTRATION, "registration_sha256": sources[str(registration)]}, basis


def _preserve_basis(basis, rows, allocation):
    """Preserve earlier charges while allowing newly completed/pending work.

    Attempt status/record hashes may legitimately evolve; original attempt ID,
    requested exposure and plan bytes may not. A reserved run may start, but its
    total charge cannot disappear. New attempts and new children remain allowed.
    """
    if (type(basis) is not dict or type(basis.get("parent_allocation_events")) is not int or
            basis["parent_allocation_events"] != allocation or type(basis.get("runs")) is not list):
        raise ValueError("invalid budget policy inventory basis")
    current = {row["run"]: row for row in rows}
    seen = set()
    total = 0
    for row in basis["runs"]:
        if type(row) is not dict or type(row.get("run")) is not str or row["run"] in seen:
            raise ValueError("invalid or duplicate budget basis run")
        seen.add(row["run"])
        charge = _positive(row.get("charged_or_reserved_events"), "basis run charge")
        total += charge
        now = current.get(row["run"])
        if now is None or now["charged_or_reserved_events"] < charge:
            raise ValueError("historical campaign charge disappeared: " + row["run"])
        if type(row.get("attempts")) is not list:
            raise ValueError("invalid budget basis attempt list")
        attempts = {item["attempt_id"]: item for item in now["attempts"]}
        identities = set()
        original_charged = 0
        for old in row["attempts"]:
            if type(old) is not dict or type(old.get("attempt_id")) is not str or old["attempt_id"] in identities:
                raise ValueError("invalid or duplicate budget basis attempt")
            identities.add(old["attempt_id"])
            original_charged += _positive(old.get("requested_events"), "basis original attempt exposure")
            if type(old.get("plan_sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", old["plan_sha256"]) is None:
                raise ValueError("invalid budget basis original plan hash")
            candidate = attempts.get(old["attempt_id"])
            if candidate is None or any(candidate.get(key) != old.get(key) for key in ("requested_events", "plan_sha256")):
                raise ValueError("historical generation attempt charge changed: " + row["run"])
        pending = row.get("pending_reserved_events")
        if type(pending) is not int or pending < 0 or original_charged + pending != charge:
            raise ValueError("budget basis run total contradicts original attempts/reservation")
    if type(basis.get("charged_or_reserved_events")) is not int or total != basis["charged_or_reserved_events"]:
        raise ValueError("budget basis total contradicts its run population")


def _generation_plan_binding(child, record, retained_plans, load):
    """Select this run's canonical plan, not incidental provenance with its name.

    Historical own-plan bytes may live in this run's retained archives. Other
    named plan inputs remain source-checked but never contribute this attempt's
    exposure. This does not grant execution or replace full receipt validation.
    """
    own_path = child / "inputs/native_execution_plan.json"
    own_name = str(own_path)
    if Path(record.get("cwd", "")).resolve() != child:
        raise ValueError("generation receipt working directory differs from its run")
    snapshot = record.get("input_snapshot")
    declared = record.get("inputs")
    if type(snapshot) is not dict or type(declared) is not list:
        raise ValueError("generation receipt lacks a declared input snapshot")
    declared_paths = []
    for name in declared:
        if type(name) is not str or not name.strip():
            raise ValueError("invalid generation input declaration")
        raw = Path(name)
        declared_paths.append(str((raw if raw.is_absolute() else child / raw).resolve()))
    if declared_paths.count(own_name) != 1 or own_name not in snapshot:
        raise ValueError("generation attempt has no unique canonical run plan")

    def file_binding(value):
        if (type(value) is not dict or value.get("kind") != "file" or
                type(value.get("files")) is not list or len(value["files"]) != 1):
            raise ValueError("generation plan snapshot must name exactly one file")
        item = value["files"][0]
        if (type(item) is not dict or item.get("name") != "." or
                type(item.get("sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("generation plan snapshot has invalid file identity")
        if "size" in item and (type(item["size"]) is not int or item["size"] < 0):
            raise ValueError("generation plan snapshot has invalid file size")
        return item

    own = file_binding(snapshot[own_name])
    pinned = own["sha256"]
    if pinned not in retained_plans:
        raise ValueError("original generation plan bytes unavailable for " + own_name)
    retained = retained_plans[pinned]
    original = load(retained)
    if file_hash(retained) != pinned:
        raise ValueError("original generation plan changed during inventory")
    if "size" in own and retained.stat().st_size != own["size"]:
        raise ValueError("retained generation plan size differs")
    if "rundir" in original and original["rundir"] != str(child):
        raise ValueError("original generation plan belongs to another run")
    for name, value in snapshot.items():
        if name == own_name:
            continue
        if type(name) is not str:
            raise ValueError("invalid generation snapshot input name")
        if Path(name).name != "native_execution_plan.json":
            continue
        incidental = Path(name)
        if (not incidental.is_absolute() or incidental.resolve() == own_path or
                any(part.is_symlink() for part in (incidental, *incidental.parents))):
            raise ValueError("incidental generation plan path aliases canonical input")
        if name not in declared_paths:
            raise ValueError("incidental generation plan is not a declared input")
        binding = file_binding(value)
        load(incidental)
        if (file_hash(incidental) != binding["sha256"] or
                ("size" in binding and incidental.stat().st_size != binding["size"])):
            raise ValueError("incidental generation plan source changed: " + name)
    return pinned, original


def native_campaign_budget(campaign, *, additional_events=0, required_policy_sha256=None):
    """Return a source-pinned reservation inventory or raise on unknown exposure.

    Only a validated native scan parent and single-point native children are
    supported. Historical attempt plans may be located in a child's retained
    archives, but their bytes must match that attempt's input snapshot. Unknown
    runs, orphan generation directories and missing attempt evidence fail closed.
    The integer allocation is agent-selected within the recorded authorization;
    this function does not represent it as a number quoted by the user.
    """
    campaign = Path(campaign).resolve()
    if type(additional_events) is not int or additional_events < 0:
        raise ValueError("additional_events must be a nonnegative integer")
    errors = verify_approval(str(campaign), required_plan="scan")
    if errors:
        raise ValueError("parent approval invalid: " + "; ".join(errors))
    sources = {}

    def load(path):
        value = read_json(path)
        sources[str(path)] = file_hash(path)
        return value

    contract = load(campaign / "inputs/task_contract.json")
    budget = load(campaign / "inputs/cost_preflight.json")
    load(campaign / "inputs/checkin1.json")
    load(campaign / "inputs/checkin1_approval.json")
    if contract["cost_estimate"] != budget or budget.get("mode") != "scan" or budget.get("backend") != "native":
        raise ValueError("parent native scan cost does not match its bound contract")
    allocation = _positive(budget.get("points"), "parent points") * _positive(budget.get("events_per_point"), "parent exposure")
    effective, policy, basis = _effective_policy(campaign, allocation, sources, load, required_policy_sha256)
    runs = campaign / "runs"
    if not runs.is_dir() or runs.is_symlink():
        raise ValueError("campaign runs directory is missing or a symlink")
    rows = []
    for child in sorted(runs.iterdir()):
        if not child.is_dir() or child.is_symlink():
            raise ValueError(f"unrecognized campaign run entry: {child}")
        config_path = child / "config.toml"
        with config_path.open("rb") as stream:
            config = tomllib.load(stream)
        sources[str(config_path)] = file_hash(config_path)
        requested = _positive(config.get("madgraph", {}).get("run", {}).get("nevents"), f"{child.name} configured exposure")
        declarations = {"config": requested}
        for path in (child / "inputs/cost_preflight.json", child / "inputs/task_contract.json"):
            if path.exists():
                data = load(path)
                cost = data.get("cost_estimate", data)
                if cost.get("backend") != "native" or _positive(cost.get("points"), "child points") != 1:
                    raise ValueError(f"{child.name}: only single-point native children are supported")
                declarations[path.name] = _positive(cost.get("events_per_point"), "child cost exposure")
        plan_path = child / "inputs/native_execution_plan.json"
        if plan_path.exists():
            declarations["plan"] = _positive(load(plan_path).get("nevents"), "child plan exposure")
        if len(set(declarations.values())) != 1:
            raise ValueError(f"{child.name}: current exposure declarations disagree: {declarations}")

        # A snapshot may name an old pathname now occupied by a different plan.
        # Only a byte-identical retained copy can supply that attempt's exposure.
        candidates = list(child.glob("**/native_execution_plan.json"))
        plans = {}
        for path in candidates:
            if path.is_symlink():
                raise ValueError(f"symlink plan evidence: {path}")
            plans.setdefault(file_hash(path), path)
        attempts = {}
        attempt_records = {}
        records = list(child.glob("logs/execution/madgraph/*/record.json"))
        records += list(child.glob("archive/**/logs/execution/madgraph/*/record.json"))
        for path in records:
            record = load(path)
            identity = record.get("attempt_id")
            if type(identity) is not str or not identity or record.get("stage") != "madgraph":
                raise ValueError(f"malformed generation attempt: {path}")
            fingerprint = digest({k: record[k] for k in ("command", "cwd", "inputs", "outputs", "input_snapshot", "parents", "runtime")})
            if record.get("fingerprint") != fingerprint:
                raise ValueError(f"generation attempt specification changed: {path}")
            pinned, original = _generation_plan_binding(child, record, plans, load)
            events = _positive(original.get("nevents"), "attempt original exposure")
            if record.get("status") not in ("running", "succeeded", "failed", "interrupted"):
                raise ValueError(f"unknown generation attempt status: {path}")
            entry = {"attempt_id": identity, "status": record["status"], "requested_events": events,
                     "plan_sha256": pinned, "record_sha256": file_hash(path)}
            if identity in attempts and attempts[identity] != entry:
                raise ValueError(f"conflicting retained attempt identity: {identity}")
            attempts[identity] = entry
            attempt_records[identity] = (record, path)
        ledger_path = child / "execution_state.json"
        if ledger_path.exists():
            ledger = load(ledger_path)
            current = ledger.get("stages", {}).get("madgraph")
            if current is not None:
                entry = attempts.get(current.get("attempt_id"))
                if entry is None or entry["record_sha256"] != file_hash(child / current["attempt_record"]):
                    raise ValueError(f"{child.name}: current generation receipt lacks retained attempt")
                if current != read_json(child / current["attempt_record"]):
                    raise ValueError(f"{child.name}: ledger and attempt record disagree")
        scratches = list(child.glob("work/madgraph/attempt-*"))
        if any(path.parent != child / "work/madgraph"
               for path in child.glob("**/work/madgraph/attempt-*")):
            raise ValueError(f"{child.name}: unaccounted generation work in an unsupported archived root")
        if scratches:
            # Runtime-v4 prints its scratch directory before generation. The
            # supervisor preserves the previous log in the next attempt's
            # prior.log. Equal directory/attempt counts cannot establish this
            # association: a preflight failure may have created no scratch.
            if not attempts:
                raise ValueError(f"{child.name}: unaccounted generation work directories")
            ordered = []
            for identity, (record, path) in attempt_records.items():
                started = datetime.fromisoformat(record["started_utc"])
                if started.tzinfo is None:
                    raise ValueError(f"{child.name}: attempt start time has no timezone")
                ordered.append((started, identity, record, path))
            ordered.sort(key=lambda item: item[0])
            if len({item[0] for item in ordered}) != len(ordered):
                raise ValueError(f"{child.name}: ambiguous generation attempt chronology")
            claimed = {}
            for index, (_started, identity, record, path) in enumerate(ordered):
                if index + 1 < len(ordered):
                    log = ordered[index + 1][3].parent / "prior.log"
                else:
                    log = Path(record["log"])
                    log = log if log.is_absolute() else child / log
                if log.is_symlink() or not log.resolve().is_relative_to(child / "logs"):
                    raise ValueError(f"{child.name}: generation log is outside retained run logs")
                # Missing log is permissible only for a failure before scratch
                # creation. Such an attempt still consumes its full reservation.
                if not log.exists():
                    continue
                sources[str(log)] = file_hash(log)
                values = [line.split(": ", 1)[1] for line in log.read_text().splitlines()
                          if line.startswith("MadGraph working directory: ")]
                if len(values) > 1:
                    raise ValueError(f"{child.name}: ambiguous generation work log")
                if not values:
                    continue
                work = Path(values[0])
                if (not work.is_absolute() or work.is_symlink() or
                        work.parent != child / "work/madgraph" or not work.name.startswith("attempt-")):
                    raise ValueError(f"{child.name}: generation work log has an unsupported path")
                if work in claimed:
                    raise ValueError(f"{child.name}: generation scratch claimed by multiple attempts")
                claimed[work] = identity
                attempts[identity]["work_directory"] = str(work)
                attempts[identity]["work_log"] = str(log)
            if any(work not in claimed for work in scratches):
                raise ValueError(f"{child.name}: unaccounted generation work directories")
        produced = child / "output/madgraph"
        if not attempts and ((produced.exists() and any(produced.iterdir())) or (child / "output/normalization.json").exists()):
            raise ValueError(f"{child.name}: generated artifacts without attempt evidence")
        charged = sum(item["requested_events"] for item in attempts.values())
        # The current request can differ after a deliberate retry reconfiguration;
        # reserve it additionally unless an existing attempt pins that exact plan.
        current_hash = file_hash(plan_path) if plan_path.exists() else None
        pending = requested if not attempts or not any(item["plan_sha256"] == current_hash for item in attempts.values()) else 0
        norm_path = child / "output/normalization.json"
        generated = None
        if norm_path.exists():
            generated = _positive(load(norm_path).get("generation", {}).get("n_events"), "normalized generated exposure")
            if generated > charged:
                raise ValueError(f"{child.name}: generated exposure exceeds retained attempts")
        rows.append({"run": child.name, "attempts": list(attempts.values()),
                     "attempt_requested_events": charged, "pending_reserved_events": pending,
                     "latest_normalization_events": generated,
                     "charged_or_reserved_events": charged + pending})
    used = sum(row["charged_or_reserved_events"] for row in rows)
    if basis is not None:
        _preserve_basis(basis, rows, allocation)
    if used + additional_events > effective:
        raise ValueError(f"effective parent allocation exhausted: {used} charged/reserved + {additional_events} requested > {effective}")
    for path, expected in sources.items():
        if file_hash(path) != expected:
            raise ValueError("campaign accounting source changed during inventory: " + path)
    return {"schema_version": 1, "accounting": "full original requested exposure per retained generation attempt, including failures; unstarted children reserved",
            "allocation_basis": "agent-selected native event allocation under valid bound parent scan authorization",
            "parent_allocation_events": allocation, "effective_allocation_events": effective, "budget_policy": policy,
            "charged_or_reserved_events": used,
            "additional_events": additional_events, "remaining_events_after_addition": effective - used - additional_events,
            "runs": rows, "sources": [{"path": path, "sha256": sha} for path, sha in sorted(sources.items())]}
