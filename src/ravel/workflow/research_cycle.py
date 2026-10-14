"""Question-led investigations composed from ordinary Ravel operations.

A hypothesis/experiment/rebuttal loop. AgentGraph and AgentHost own calls; science owns approval, processes and attempts; physics_review owns
decisions. This module connects their actual artifacts into an immutable research
history. Prediction separation is an exploration heuristic, not an information
gain estimator or an automatic scientific truth test.
"""
from copy import deepcopy
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import agent_graph, candidate_experiments as ce, hypothesis_board
from . import physics_review, science, scientific_context, state_io

MAX_REVISIONS = 128
PARENT_PREMISE = "original-parent-task"
VECTORS = ("calls", "output_tokens", "wall_seconds", "native_attempts")


from enum import Enum


class ExecutionStatus(str, Enum):
    SUCCESS = "succeeded"
    FAILED = "failed"
    UNRESOLVED = "unresolved"

    @classmethod
    def normalize(cls, value):
        if value in ("success", "succeeded"):
            return cls.SUCCESS
        if value == "failed":
            return cls.FAILED
        return cls.UNRESOLVED


class OperationalBoundaryError(ValueError):
    """An admitted operation cannot fit its original campaign; no physics result."""


def _clock(state, required_seconds):
    timing = state["timing"]
    now = time.time()
    if timing["started_epoch"] is None:
        timing.update(started_epoch=now, deadline_epoch=now + state["contract"]["budget"]["wall_seconds"])
    remaining = max(0.0, timing["deadline_epoch"] - now)
    if required_seconds > remaining:
        return {"kind": "campaign_deadline_insufficient_for_declared_branch", "observed_epoch": now,
            "original_started_epoch": timing["started_epoch"], "original_deadline_epoch": timing["deadline_epoch"],
            "elapsed_seconds": now - timing["started_epoch"], "remaining_seconds": remaining,
            "required_ceiling_seconds": required_seconds, "scientific_result": None, "new_attempts": 0}
    return None


def _text(value, maximum=8000):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError("bounded explicit research text required")


def _vector(value):
    ce.keys(value, VECTORS)
    for key in VECTORS:
        if type(value[key]) is not int or not 0 <= value[key] <= 10**9:
            raise ValueError("nonnegative integer resource ceilings required")
    return deepcopy(value)


def _ordinary(path):
    path = Path(path).absolute()
    # Name the outermost link: on a new host that is the component to look at.
    linked = next((p for p in (*reversed(path.parents), path) if p.is_symlink()), None)
    if linked is not None:
        raise ValueError(f"ordinary research paths required: {linked} is a symbolic link")
    return path


def _pin(path):
    path = _ordinary(path)
    if not path.is_file():
        raise ValueError("existing research artifact required")
    before = path.stat()
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            sha.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("research bytes changed while hashing")
    return {"path": str(path), "sha256": sha.hexdigest(), "size": after.st_size}


def _check_pin(pin, base):
    ce.keys(pin, ("path", "sha256", "size"))
    ce.sha(pin["sha256"])
    if type(pin["size"]) is not int or not 0 <= pin["size"] <= 64 * 1024 * 1024:
        raise ValueError("bounded ordinary research artifact size required")
    path = Path(pin["path"])
    path = path if path.is_absolute() else Path(base) / path
    actual = _pin(path)
    if any(actual[key] != pin[key] for key in ("sha256", "size")):
        raise ValueError("retained research artifact changed")
    return path, actual


def _read(pin, base):
    path, actual = _check_pin(pin, base)
    if actual["size"] > ce.MAX_BYTES:
        raise ValueError("research JSON exceeds bounded input size")
    result = state_io.read_json(path)
    if _pin(path) != actual:
        raise ValueError("research input changed while reading")
    return result


def _read_failed_intake(pin, base):
    """Only the canonical retained failure has the existing 16MiB bound."""
    from .research_presentation import document, MAX_INVENTORY_BYTES
    value = document(pin, base, MAX_INVENTORY_BYTES)
    if (type(value) is not dict or value.get("kind") != "failed_stage_diagnostic_intake"
            or type(value.get("schema_version")) is not int or value["schema_version"] != 1):
        raise ValueError("canonical failed-stage intake required")
    if value.get("sha256") != science.execution.digest({k:v for k,v in value.items() if k!="sha256"}):
        raise ValueError("canonical failed-stage intake digest differs")
    # Its complete ordinary validator, called by each consumer, authenticates
    # original source, runtime, record, launch, membership and returned outputs.
    return value


def _read_failed_feedback(pin, base):
    from .research_presentation import document, MAX_INVENTORY_BYTES
    value = document(pin, base, MAX_INVENTORY_BYTES)
    if type(value) is not dict or value.get("kind") not in {
            "failed_stage_diagnostic_feedback", "failed_stage_historical_feedback"}:
        raise ValueError("typed canonical diagnostic feedback required")
    return value


def _failed_dependency_pins(document, document_pin, base):
    from . import failed_stage_review
    # Large canonical snapshots already commit every leaf. Do not duplicate
    # their thousands of rows into a declaration-bounded campaign head.
    if document_pin["size"] > ce.MAX_BYTES:
        _check_pin(document_pin, base)
        return [deepcopy(document_pin)]
    return [_pin(Path(row["path"])) for row in
            failed_stage_review.inputs(document["request"], base_dir=document["run_dir"])]


def _seal(value):
    result = deepcopy(value)
    result["sha256"] = ce.digest(value)
    return result


def _load(root, *, check_parent=True):
    root = _ordinary(root)
    head = state_io.read_json(root / "head.json")
    current = _read(head, root)
    for revision in range(current["revision"] + 1):
        path = root / "history" / f"{revision:04d}.json"
        record = state_io.read_json(path)
        content = deepcopy(record)
        checksum = content.pop("sha256")
        if checksum != ce.digest(content) or record["revision"] != revision:
            raise ValueError("research history content differs")
        if revision and record["parent_sha256"] != previous["sha256"]:
            raise ValueError("research ancestry differs")
        previous = record
    if previous != current:
        raise ValueError("research head differs from immutable history")
    if current['contract'].get('research_protocol_required') or current.get('methodology') is not None:
        from . import research_protocol
        methodology = research_protocol.methodology_status(root)['record']
        if current.get('methodology') != methodology:
            raise ValueError('research protocol differs from its committed campaign state')
    declaration = current.get("scientific_context_declaration")
    if declaration is not None:
        _verified_context_declaration(current, declaration)
    request = _read(declaration["request"] if declaration is not None else current["contract"]["context_request"], current["base_dir"])
    initial = scientific_context.compile_context(request, current["base_dir"])
    if initial["request_sha256"] != current["context"]["request_sha256"]:
        raise ValueError("question context request changed")
    for row in current["premises"]:
        for pin in row["basis"]: _check_pin(pin, current["base_dir"])
    for row in current["hypotheses"]:
        for pin in row["source_basis"]: _check_pin(pin, current["base_dir"])
    for step in current["context"]["steps"]:
        for pin in step["outputs"]: _check_pin(_pin_shape(pin), current["base_dir"])
    for pin in current["adaptations"]:
        record = _read(pin, current["base_dir"])
        for dependency in record["dependencies"]: _check_pin(dependency, current["base_dir"])
    _check_knowledge(current)
    if check_parent: _parent_goal(current)
    return root, current


def _pin_shape(row):
    path = Path(row["path"])
    return {"path": row["path"], "sha256": row["sha256"], "size": path.stat().st_size}


def _commit(root, state, event, **payload):
    _parent_goal(state)
    if state["revision"] + 1 >= MAX_REVISIONS:
        raise ValueError("finite research revision budget exhausted")
    newer = deepcopy(state)
    newer["revision"] += 1
    newer["parent_sha256"] = newer.pop("sha256")
    newer["events"].append({"revision": newer["revision"], "kind": event, **deepcopy(payload)})
    newer = _seal(newer)
    path = root / "history" / f"{newer['revision']:04d}.json"
    if path.exists():
        raise ValueError("immutable research revision already exists")
    state_io.atomic_json(path, newer)
    state_io.atomic_json(root / "head.json", _pin(path))
    return newer


def _fresh(state, bindings):
    current = {row["id"]: row["sha256"] for row in state["premises"]}
    if "parent_task" in state: current[PARENT_PREMISE] = ce.digest(state["parent_task"])
    return all(current.get(key) == digest for key, digest in bindings.items())


def _attempt_from_step(step):
    return {"id": step["id"], "outputs": {x["id"]: {k: x[k] for k in ("path", "sha256")} for x in step["outputs"]},
        "code_status": step["code_status_reported"], "actor_complete": step["actor_complete_reported"],
        "question": step["question"] or "Replay unaffected complete scientific outputs.",
        "next_experiment": step["next_experiment"] or {key: "Preserve the unaffected scoped result."
            for key in ("hypothesis", "change", "measurement", "if_supported", "if_not_supported")}}


def _usage(state):
    return {key: sum(x["ceiling"][key] for x in state["resource_ledger"]) for key in VECTORS}



def _failed_parent(e):
    return e.get("kind") in {"imported_failed_stage", "attached_failed_stage"}


def _applicability(state, e):
    active = {h["id"] for h in state["hypotheses"] if _fresh(state, h["premise_bindings"])}
    return {"measurement": _fresh(state, e["premise_bindings"]) and "applicability_reopened" not in e,
            "prediction_interpretations": {identity: identity in active for identity in e["predictions"]}}


def _current_evidence(state, e, *, accepted=False, _session=None):
    """Fresh ordinary custody and scope; an old accepted label is insufficient."""
    if "tool_context" in e:
        from .research_tools import check_binding
        check_binding(e["tool_context"], state["base_dir"], state=state)
    if _failed_parent(e):
        from . import failed_stage_review
        document = _read_failed_intake(e["failed_intake"], state["base_dir"])
        failed_stage_review.verify(document, base_dir=e["rundir"])
        for pin in e["input_pins"]: _check_pin(pin, state["base_dir"])
        if e.get("kind") == "attached_failed_stage":
            for pin in [e["study"], e["plan"]]: _check_pin(pin, state["base_dir"])
            science.verify_plan(e["rundir"], approved=True,
                **({} if _session is None else {"_session": _session, "_recheck": True}))
        if e["diagnostic_feedback"] is not None:
            saved = _read_failed_feedback(e["diagnostic_feedback"], state["base_dir"])
            failed_stage_review.verify_feedback(document, saved, base_dir=e["rundir"],
                                               allow_control=e["diagnostic_control_only"])
        if accepted:
            raise ValueError("failed-stage diagnostic evidence never grants scientific acceptance or reuse")
        return
    for pin in [e["study"], *e["input_pins"]]: _check_pin(pin, state["base_dir"])
    if e["plan"] is not None: _check_pin(e["plan"], state["base_dir"])
    if e["observation"] is None: raise ValueError("actual observation required")
    observation = e["observation"]
    _check_pin(observation["receipt"], state["base_dir"])
    if observation["result"] is not None: _check_pin(observation["result"], state["base_dir"])
    science.verify_plan(e["rundir"], approved=True,
                **({} if _session is None else {"_session": _session, "_recheck": True}))
    if _quantitative(e) and observation.get("quantitative_check") is not None:
        from .quantitative_predictive_checks import verify_evidence
        saved = verify_evidence(e["quantitative_binding"]["binding"], observation["quantitative_check"],
            observation["result"], base_dir=state["base_dir"])
        if ce.digest(saved) != ce.digest(observation["quantitative_evidence"]):
            raise ValueError("retained quantitative evidence changed")
    if accepted:
        if e["adjudication"] is None: raise ValueError("actual scoped roles required")
        saved = _read(e["adjudication"]["snapshot"], state["base_dir"])
        actual = physics_review.snapshot(e["rundir"], action="reuse")
        if actual != saved: raise ValueError("accepted ordinary review state changed")
        view = physics_review.status(e["rundir"])
        if view["state"] != "accepted" or view["live_errors"] or view["claim_scope"] != e["acceptance_scope"]:
            raise ValueError("actual accepted scientific scope no longer reusable")


def import_failed_stage(root, identity, document_pin, *, premise_ids, predictions, historical_cost):
    """Connect a genuine retained failure without re-running or accepting it.

    The original operation's declared costs debit this investigation's cumulative
    ceiling. Its elapsed time is retained as prior history; a newly declared
    phase starts only on its own actual dispatch and cannot amend the old wall.
    The independently owned canonical adapter defines custody/classification.
    """
    from . import failed_stage_review
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        ce.identity(identity)
        if len(state["experiments"]) >= state["contract"]["max_experiments"] or identity in {x["id"] for x in state["experiments"]}:
            raise ValueError("finite distinct retained failure identity required")
        document = _read_failed_intake(document_pin, state["base_dir"])
        failed_stage_review.verify(document, base_dir=document["run_dir"])
        active = {h["id"] for h in state["hypotheses"] if _fresh(state, h["premise_bindings"])}
        if type(predictions) is not dict or not predictions or set(predictions) - active:
            raise ValueError("retained failure needs current competing hypotheses")
        if any(value is not None for value in predictions.values()):
            raise ValueError("failed execution cannot classify scientific predictions as measured outcomes")
        amount = _vector(historical_cost)
        from .research_presentation import document as retained_document
        record_pin = _pin(Path(document["record"]["path"]))
        if record_pin["sha256"] != document["record"]["sha256"]:
            raise ValueError("canonical historical record differs")
        record = retained_document(record_pin, state["base_dir"], 64*1024**2)
        declared_walls = []
        resources = record.get("operation_resources", {})
        if "max_seconds" in resources:
            bound = resources["max_seconds"]
            if type(bound) not in (int, float) or not math.isfinite(bound) or bound <= 0:
                raise ValueError("positive source-bound historical wall required")
            declared_walls.append(bound)
        # Current ordinary science records bind the prospective wall through
        # inputs/science.json, not necessarily through operation_resources.
        # Consume only this genuine original ordinary-file snapshot; historical
        # custody is defined by the canonical adapter, not a newly supplied file.
        old_spec = Path(document["run_dir"]) / science.SPEC
        fact = document["source_inputs"].get(str(old_spec))
        if fact is not None:
            actual = _pin(old_spec)
            if fact != {"kind": "file", "files": [{"name": ".", "size": actual["size"], "sha256": actual["sha256"]}]}:
                raise ValueError("historical ordinary specification snapshot differs")
            historical_spec = _read(actual, state["base_dir"])
            bound = historical_spec.get("max_seconds")
            if type(bound) not in (int, float) or not math.isfinite(bound) or bound <= 0:
                raise ValueError("positive original science wall required")
            declared_walls.append(bound)
        if not declared_walls:
            raise ValueError("original declared wall unavailable; cannot reset historical cost")
        original_wall = max(declared_walls)
        if amount["native_attempts"] != 1 or amount["wall_seconds"] < original_wall:
            raise ValueError("one retained operation attempt and its original declared wall must be debited")
        pins = _failed_dependency_pins(document, document_pin, state["base_dir"])
        _charge(state, "historical-failure:" + identity, amount, document_pin)
        observation = {"receipt": _pin(Path(document["record"]["path"])), "attempt_id": document["attempt_id"],
            "result": None if document["result"] is None else _pin(Path(document["result"]["path"])),
            "execution_status": "failed", "packet": None, "measured": None, "outcome": None,
            "prediction_comparison": {key: "unknown" for key in predictions},
            "result_category": document["failure_kind"], "scientific_acceptance": False,
            "original_started_utc": record.get("started_utc"), "original_finished_utc": record["finished_utc"],
            "original_elapsed_seconds": record.get("elapsed_seconds"),
            "prior_failed_campaign_deadline_extended": False}
        state["experiments"].append({"id": identity, "kind": "imported_failed_stage",
            "question": state["contract"]["question"], "premise_ids": deepcopy(premise_ids),
            "premise_bindings": _bindings(state, premise_ids), "parent": None,
            "change": "Retain the actual failed operation as the diagnostic parent, without a new attempt.",
            "study": None, "cost": amount, "predictions": deepcopy(predictions), "observable": None,
            "context_outputs": {}, "acceptance_scope": None, "exploratory": False,
            "input_pins": pins, "rundir": document["run_dir"], "plan": None, "observation": observation,
            "adjudication": None, "failed_intake": deepcopy(document_pin), "diagnostic_feedback": None,
            "diagnostic_control_only": False})
        _register_observation(state, state["experiments"][-1])
        return _commit(Path(root), state, "actual_failed_stage_connected", experiment_id=identity,
                       failure_kind=document["failure_kind"], original_attempt_id=document["attempt_id"])



def attach_failed_stage(root, identity, document_pin):
    """Attach canonical diagnosis to this already charged ordinary failure.

    This does not import a second attempt, restart the worker, accept failed
    outputs, or overwrite the first observation. It makes an actual returned
    scientific-unresolved or infrastructure failure available for constructive
    review in the same investigation. Historical operation receipts remain the
    canonical adapter's responsibility.
    """
    from . import failed_stage_review
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(row for row in state["experiments"] if row["id"] == identity)
        if (_failed_parent(e) or e["rundir"] is None or e["plan"] is None
                or e["observation"] is None or e["adjudication"] is not None
                or e["observation"]["execution_status"] != "failed"):
            raise ValueError("an unaccepted observed ordinary failure is required")
        # The earlier ordinary observation is a commitment, not a recapture
        # opportunity. A later truthful canonical intake cannot replace it.
        _current_evidence(state, e)
        document = _read_failed_intake(document_pin, state["base_dir"])
        failed_stage_review.verify(document, base_dir=e["rundir"])
        record_path, _ = _check_pin(e["observation"]["receipt"], state["base_dir"])
        if (str(_ordinary(document["run_dir"])) != str(_ordinary(e["rundir"]))
                or document["stage"] != "science"
                or document["attempt_id"] != e["observation"]["attempt_id"]
                or str(_ordinary(document["record"]["path"])) != str(record_path)
                or document["record"]["sha256"] != e["observation"]["receipt"]["sha256"]):
            raise ValueError("canonical failure must be this exact observed attempt")
        reservation = next((row for row in state["resource_ledger"] if row["id"] == "experiment:" + identity), None)
        attributed = _experiment_reservation(state,e,root)
        expected_cost = e["cost"] if attributed is None else attributed["incremental_cost"]
        if reservation is None or reservation["ceiling"] != expected_cost or e["cost"]["native_attempts"] != 1:
            raise ValueError("exact existing ordinary operation reservation required")
        science.verify_plan(e["rundir"], approved=True)
        for pin in [e["study"], e["plan"], *e["input_pins"]]: _check_pin(pin, state["base_dir"])
        saved_observation = deepcopy(e["observation"])
        pins = _failed_dependency_pins(document, document_pin, state["base_dir"])
        by_path = {pin["path"]: pin for pin in e["input_pins"]}
        for pin in pins:
            if pin["path"] in by_path and by_path[pin["path"]] != pin:
                raise ValueError("canonical input and ordinary dependency custody differ")
            by_path[pin["path"]] = pin
        e.update(kind="attached_failed_stage", failed_intake=deepcopy(document_pin),
                 diagnostic_feedback=None, diagnostic_control_only=False,
                 input_pins=list(by_path.values()), original_ordinary_observation=saved_observation,
                 failure_origin="this_cycle_observed_ordinary_attempt")
        e["observation"] = {**saved_observation, "result_category": document["failure_kind"],
            "canonical_returned_result": deepcopy(document["result"]),
            "measured": None, "measurement_present": False, "outcome": None,
            "prediction_comparison": {h: "unknown" for h in e["predictions"]},
            "scientific_acceptance": False}
        _register_observation(state, e)
        from .research_evaluation import record_observation
        record_observation(state, e)
        return _commit(Path(root), state, "ordinary_failed_stage_diagnosis_attached", experiment_id=identity,
                       intake=document_pin, duplicate_attempt_or_resource_charge=False)


def diagnostic_feedback(root, identity, feedback_pin, *, allow_control=False):
    """Consume canonical actual diagnostic critique, never an acceptance vote.

    Historical source-bound reports and observed fresh Graph transports remain
    distinct in the adapter's receipt. The controller never relabels one as the
    other. Fresh diagnostic Graphs must already be cumulatively charged here.
    """
    from . import failed_stage_review
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(x for x in state["experiments"] if x["id"] == identity)
        if not _failed_parent(e) or e["diagnostic_feedback"] is not None:
            raise ValueError("unreviewed canonical failed-stage parent required")
        document = _read_failed_intake(e["failed_intake"], state["base_dir"])
        feedback = _read_failed_feedback(feedback_pin, state["base_dir"])
        failed_stage_review.verify_feedback(document, feedback, base_dir=e["rundir"], allow_control=allow_control)
        if feedback["kind"] == "failed_stage_diagnostic_feedback":
            roots = {g["root"] for g in state["graphs"]}
            if any(str(_ordinary(row["binding"]["graph_root"])) not in roots for row in feedback["reviews"]):
                raise ValueError("fresh diagnostic roles must use this cycle's charged ordinary Graphs")
        e["diagnostic_feedback"] = deepcopy(feedback_pin)
        e["diagnostic_control_only"] = allow_control
        return _commit(Path(root), state, "actual_failure_critique_connected", experiment_id=identity,
                       feedback=feedback_pin, transport_kind=feedback["kind"])


def configure_phases(root, request_pin, *, check_contracts, preconstruction_checks):
    """Bind declared checking resources to actual ordinary scoped check results.

    Construction cost is the already-declared study branch. Check cost is an
    additional conservative ceiling, not provider telemetry. Policy tool calls
    dispatched through execute_graph are charged there and cannot be omitted.
    Configuration may append designs/checks, retaining every earlier obligation.
    """
    from . import scientific_phase_allocation
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        request = _read(request_pin, state["base_dir"])
        scientific_phase_allocation.allocate(request)
        if request["budget"] != state["contract"]["budget"] or request["usage"] != _usage(state):
            raise ValueError("phase request must bind actual cumulative research reservations")
        if request["completed_check_ids"] or request["retained_design_ids"]:
            raise ValueError("actual completed and retained identities are derived by the cycle")
        designs = {e["id"]: e for e in state["experiments"]}
        rows = {e["id"]: e for e in request["designs"]}
        if set(rows) != set(designs) or any(rows[i]["construction_cost"] != designs[i]["cost"] for i in rows):
            raise ValueError("complete actual design census and construction ceilings required")
        checks = {c["id"] for c in request["checks"]}
        if type(check_contracts) is not dict or set(check_contracts) != checks:
            raise ValueError("every resource check requires an explicit ordinary evidence contract")
        for row in check_contracts.values():
            ce.keys(row, ("experiment_id", "required_check_ids", "purpose"))
            if row["experiment_id"] not in designs or row["purpose"] not in {"scientific", "adapter_lifecycle"}:
                raise ValueError("existing prospective check study and explicit purpose required")
            ids = row["required_check_ids"]
            if type(ids) is not list or not ids or len(set(ids)) != len(ids):
                raise ValueError("complete distinct ordinary check identities required")
            if _failed_parent(designs[row["experiment_id"]]):
                raise ValueError("failed-stage diagnosis cannot satisfy successful scientific checking reservations")
            spec = _read(designs[row["experiment_id"]]["study"], state["base_dir"])
            if set(ids) - {x["id"] for x in spec["review_policy"]["policy"]["required_checks"]}:
                raise ValueError("check contract must use the actual prospective study policy")
        if type(preconstruction_checks) is not dict or set(preconstruction_checks) != set(designs):
            raise ValueError("explicit preconstruction obligation census required")
        for identity, ids in preconstruction_checks.items():
            if type(ids) is not list or len(set(ids)) != len(ids) or set(ids) - checks:
                raise ValueError("known distinct preconstruction checks required")
            if any(check_contracts[i]["experiment_id"] == identity for i in ids):
                raise ValueError("a design cannot qualify its own preconstruction lifecycle")
        policy = {"request": deepcopy(request), "source": deepcopy(request_pin),
            "check_contracts": deepcopy(check_contracts), "preconstruction_checks": deepcopy(preconstruction_checks)}
        if state["phase_policy"] is not None:
            old = state["phase_policy"]
            for key in ("checks", "designs"):
                new_rows = {x["id"]: x for x in request[key]}
                if any(new_rows.get(x["id"]) != x for x in old["request"][key]):
                    raise ValueError("old phase resource obligations cannot be silently replaced")
            if not set(old["request"]["mandatory_check_ids"]) <= set(request["mandatory_check_ids"]):
                raise ValueError("mandatory checking cannot disappear")
            for identity, row in old["check_contracts"].items():
                if check_contracts.get(identity) != row: raise ValueError("check evidence contract changed")
            for identity, ids in old["preconstruction_checks"].items():
                if not set(ids) <= set(preconstruction_checks.get(identity, [])):
                    raise ValueError("preconstruction lifecycle obligation disappeared")
        state["phase_policy"] = policy
        return _commit(Path(root), state, "phase_checking_policy_bound", source=request_pin)


def _phase_allocation(state):
    from . import scientific_phase_allocation
    if state["phase_policy"] is None: return None
    policy = state["phase_policy"]
    _check_pin(policy["source"], state["base_dir"])
    request = deepcopy(policy["request"])
    if {e["id"] for e in request["designs"]} != {e["id"] for e in state["experiments"]}:
        raise ValueError("new designs need a fresh complete phase policy before preparation")
    complete = []
    for check in state["phase_checks"]:
        e = next(e for e in state["experiments"] if e["id"] == check["experiment_id"])
        if _fresh(state, e["premise_bindings"]) and "applicability_reopened" not in e:
            _current_evidence(state, e, accepted=True)
            complete.append(check["id"])
    request["usage"] = _usage(state)
    request["completed_check_ids"] = complete
    request["retained_design_ids"] = [e["id"] for e in state["experiments"] if e["rundir"] is not None]
    result = scientific_phase_allocation.allocate(request)
    result["ordinary_current_completed_check_ids"] = complete
    return result


def record_check(root, check_id):
    """Complete a reservation only from fresh accepted ordinary check evidence."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        if state["phase_policy"] is None: raise ValueError("phase resource/evidence policy required")
        policy = state["phase_policy"]
        if check_id in {x["id"] for x in state["phase_checks"]}: raise ValueError("check already retained")
        row = policy["check_contracts"][check_id]
        e = next(e for e in state["experiments"] if e["id"] == row["experiment_id"])
        _current_evidence(state, e, accepted=True)
        if not _fresh(state, e["premise_bindings"]) or "applicability_reopened" in e:
            raise ValueError("changed premise reopens check applicability")
        snapshot = _read(e["adjudication"]["snapshot"], state["base_dir"])
        cycle = next(x for x in reversed(snapshot["events"]) if x["event"] == "cycle")
        checks = {x["id"]: x for x in cycle["checks"]}
        if any(checks[i]["status"] != "pass" for i in row["required_check_ids"]):
            raise ValueError("failed or unknown checks remain pending")
        amount = next(x["cost"] for x in policy["request"]["checks"] if x["id"] == check_id)
        _charge(state, "phase-check:" + check_id, amount, e["adjudication"]["snapshot"])
        state["phase_checks"].append({"id": check_id, **deepcopy(row), "evidence": e["adjudication"]["snapshot"]})
        return _commit(Path(root), state, "ordinary_check_reservation_completed", check_id=check_id)


def _bindings(state, identities):
    if type(identities) is not list or len(set(identities)) != len(identities):
        raise ValueError("distinct explicit premise dependencies required")
    current = {row["id"]: row["sha256"] for row in state["premises"]}
    if set(identities) - current.keys():
        raise ValueError("unknown research premise")
    result = {identity: current[identity] for identity in identities}
    if "parent_task" in state: result[PARENT_PREMISE] = ce.digest(state["parent_task"])
    return result


def _charge(state, identity, amount, evidence):
    amount = _vector(amount)
    if identity in {row["id"] for row in state["resource_ledger"]}:
        raise ValueError("resource reservation cannot be reset or repeated")
    usage = {key: sum(row["ceiling"][key] for row in state["resource_ledger"]) + amount[key] for key in VECTORS}
    if any(usage[key] > state["contract"]["budget"][key] for key in VECTORS):
        raise ValueError("cumulative research resource ceiling exhausted")
    state["resource_ledger"].append({"id": identity, "ceiling": amount, "basis": deepcopy(evidence)})


def reserve_operation(root, identity, amount, evidence):
    """Charge one prospective non-Graph operation against the campaign, once.

    The full ceiling is reserved before any launch and is never renewed; an
    identical repeat returns the retained row, a different amount refuses.
    """
    if type(identity) is not str or not identity.startswith("operation:") or len(identity) > 2048:
        raise ValueError("explicit operation reservation identity required")
    amount = _vector(amount)
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        row = next((r for r in state["resource_ledger"] if r["id"] == identity), None)
        if row is not None:
            if row["ceiling"] != amount or row["basis"] != evidence:
                raise ValueError("operation reservation identity already holds another ceiling")
            return deepcopy(row)
        refusal = _clock(state, amount["wall_seconds"])
        if refusal is not None:
            state["operational_boundaries"].append({"operation": identity, **refusal})
            _commit(Path(root), state, "operational_boundary_retained", operation=identity)
            raise OperationalBoundaryError("original campaign cannot fit the declared operation")
        _charge(state, identity, amount, evidence)
        _commit(Path(root), state, "ordinary_operation_reserved", operation=identity)
        return deepcopy(state["resource_ledger"][-1])


def create(root, contract, *, base_dir, evaluation_harness=False):
    """Create a question and complete task context; ideation needs no prior paper.

    Every campaign binds the default research protocol. Omitting
    ``research_protocol_required`` or ``goal_binding`` binds it too; omission is
    never a bypass. Only a library caller (``evaluation_harness=True``,
    unreachable from the CLI) creates an unbound synthetic campaign, labelled so.
    """
    if type(evaluation_harness) is not bool:
        raise ValueError('evaluation_harness must be explicit')
    ce.keys(contract, ("schema_version", "id", "question", "scope", "context_request", "premises", "budget",
                       "max_experiments", "exploration_every", "required_experiments",
                       *({"goal_binding"} if "goal_binding" in contract else set()),
                       *({'research_protocol_required'} if 'research_protocol_required' in contract else set()),
                       *({'research_regime'} if 'research_regime' in contract else set())))
    if 'research_protocol_required' in contract and contract['research_protocol_required'] is not True:
        raise ValueError('research protocol cannot be disabled')
    if type(contract["schema_version"]) is not int or contract["schema_version"] != 1:
        raise ValueError("research-cycle/v1 required")
    ce.identity(contract["id"])
    _text(contract["question"]); _text(contract["scope"])
    _vector(contract["budget"])
    for key, maximum in (("max_experiments", 32), ("exploration_every", 16)):
        if type(contract[key]) is not int or not 1 <= contract[key] <= maximum:
            raise ValueError("finite experiment and exploration bounds required")
    if type(contract["required_experiments"]) is not list or len(set(contract["required_experiments"])) != len(contract["required_experiments"]):
        raise ValueError("distinct complete required experiment census required")
    for identity in contract["required_experiments"]: ce.identity(identity)
    base = _ordinary(base_dir).resolve(strict=True)
    request = _read(contract["context_request"], base)
    context = scientific_context.compile_context(request, base)
    parent = None
    if "goal_binding" in contract:
        from .task_completion import binding_projection
        parent = binding_projection(contract["goal_binding"], base_dir=base)
        from . import research_protocol
        original = _read(contract['goal_binding']['contract'], base)
        if research_protocol.required_for(original):
            contract = {**contract, 'research_protocol_required': True}
    if not evaluation_harness:
        contract = {**contract, 'research_protocol_required': True}
    premises = []
    if type(contract["premises"]) is not list or len(contract["premises"]) > 32:
        raise ValueError("bounded explicit research premises required")
    for row in contract["premises"]:
        ce.keys(row, ("id", "statement", "basis")); ce.identity(row["id"]); _text(row["statement"])
        if row["id"] in {x["id"] for x in premises}: raise ValueError("duplicate research premise")
        if parent is not None and row["id"] == PARENT_PREMISE:
            raise ValueError("reserved original parent task premise")
        if type(row["basis"]) is not list or len(row["basis"]) > 16: raise ValueError("bounded premise basis required")
        for pin in row["basis"]: _check_pin(pin, base)
        premises.append(_seal(row))
    root = _ordinary(root)
    root.mkdir()
    from . import gate_wiring
    gate_wiring.initialize_steering(root, route='research-study')
    state = _seal({"schema_version": 1, "kind": "connected_research_cycle", "revision": 0,
        "parent_sha256": None, "base_dir": str(base), "contract": deepcopy(contract), "premises": premises,
        "hypotheses": [], "experiments": [], "resource_ledger": [], "graphs": [], "context": context,
        "events": [{"revision": 0, "kind": "question_created"}],
        "timing": {"started_epoch": None, "deadline_epoch": None,
                   "policy": "End-to-end wall time from first dispatched ordinary operation, including coordination, source admission, reviews and native queue."},
        "operational_boundaries": [], "phase_policy": None, "phase_checks": [], "revisions": [], "adaptations": [], "execution_authorized": False,
        "physics_validated": False, "benefit_measured": False})
    if parent is not None:
        state = _seal({**{k: v for k, v in state.items() if k != "sha256"}, "parent_task": parent})
    if evaluation_harness and not contract.get('research_protocol_required'):
        state = _seal({**{k: v for k, v in state.items() if k != 'sha256'}, 'protocol_exemption': 'evaluation_harness'})
    if contract.get('research_protocol_required'):
        from . import research_protocol
        state = _seal({**{k: v for k, v in state.items() if k != 'sha256'},
                       'methodology': research_protocol.bind_default(root,
                           regime=contract.get('research_regime', 'open_exploratory'))})
    _parent_goal(state)
    state_io.atomic_json(root / "history/0000.json", state)
    state_io.atomic_json(root / "head.json", _pin(root / "history/0000.json"))
    return state


def _context_mapping(state, request, mapping):
    """Retain every original scientific AND nonnumeric deliverable explicitly."""
    if state.get('parent_task') is None:
        raise ValueError('open context declaration requires its original parent assignment')
    from .task_completion import _Inputs, _contract
    inputs = _Inputs(state['base_dir'])
    try:
        parent, requirements, _, _ = _contract(state['parent_task']['contract'], inputs)
        if request['task'] != parent['prompt']:
            raise ValueError('scientific context must preserve the literal complete original question')
        obligations = {row['id']: row for row in requirements['obligations']}
        quantities = {q['id'] for q in scientific_context._requirements(request['requested_quantities'])}
        if type(mapping) is not list or len(mapping) != len(obligations):
            raise ValueError('complete original obligation to quantity/method/source mapping required')
        seen = set()
        mapped = set()
        for row in mapping:
            ce.keys(row, ('obligation_id', 'original', 'quantities', 'method', 'sources', 'unresolved'))
            identity = row['obligation_id']
            if identity in seen or identity not in obligations or row['original'] != obligations[identity]:
                raise ValueError('original obligation wording/criteria changed or duplicated')
            seen.add(identity)
            _text(row['method'])
            if type(row['quantities']) is not list or len(set(row['quantities'])) != len(row['quantities']) or set(row['quantities']) - quantities:
                raise ValueError('mapping must name actual declared scientific quantities')
            mapped.update(row['quantities'])
            if type(row['unresolved']) is not str or ((not row['quantities'] or not row['sources']) and not row['unresolved'].strip()):
                raise ValueError('nonnumeric or unresolved deliverables must retain an explicit method and outstanding criterion')
            if type(row['sources']) is not list or len(row['sources']) > 32:
                raise ValueError('finite actual method/source mapping required')
            for pin in row['sources']: _check_pin(pin, state['base_dir'])
        if mapped != quantities:
            raise ValueError('every declared quantity must address an original obligation')
        inputs.finish()
    finally:
        inputs.close()


def _verified_context_declaration(state, declaration):
    ce.keys(declaration, ('request', 'mapping', 'origin', 'original_planning_context', 'authority'))
    if declaration['authority'] != 'prospective source declaration; no review, execution or parent acceptance':
        raise ValueError('context declaration cannot confer authority')
    if declaration['original_planning_context'] != state['contract']['context_request']:
        raise ValueError('original planning context must remain in immutable history')
    origin = declaration['origin']
    actual = _graph_result(origin['root'], origin['node_id'])
    if (actual != origin or actual['role'] != 'designer' or actual['node_kind'] != 'model'
            or actual['value'].get('kind') != 'model_result'):
        raise ValueError('context declaration must retain its actual designer result')
    graph_root = _ordinary(origin['root'])
    spec, _ = agent_graph._load(graph_root)
    validate_graph_reservation(state, graph_root, spec)
    value = actual['value']['value']
    ce.keys(value, ('kind', 'context_json', 'obligation_mapping_json', 'modes', 'reason'))
    request = _read(declaration['request'], state['base_dir'])
    from .agent_host import _loads
    if (value['kind'] != 'research-context-declaration' or _loads(value['context_json']) != request
            or _loads(value['obligation_mapping_json']) != declaration['mapping'] or value['modes']!=[]):
        raise ValueError('declared quantities/methods differ from actual model output')
    _context_mapping(state, request, declaration['mapping'])
    allowed = {(p['path'], p['sha256']) for p in actual['inputs']}
    pins = scientific_context.input_pins(request, state['base_dir'])
    pins += [p for row in declaration['mapping'] for p in row['sources']]
    if any((str(_ordinary(Path(p['path']) if Path(p['path']).is_absolute() else Path(state['base_dir']) / p['path'])), p['sha256']) not in allowed for p in pins):
        raise ValueError('quantity/method sources must actually have been supplied to the designer')


def declare_context(root, request_pin, mapping, *, graph_root, node_id, expected_context_sha256=None):
    """Pre-experiment source-grounded refinement, never a goal or budget reset.

    The planning-only obligation census is retained separately. It cannot be
    counted as a measured scientific quantity or discharge any original goal.
    Later changes require the existing explicit premise/scope revision route.
    """
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = _load(root)
        if state['experiments'] or state['context']['steps'] or state['hypotheses']:
            raise ValueError('scientific context declaration is allowed only before hypotheses and experiments')
        origin = _graph_result(graph_root, node_id)
        declaration = {'request': deepcopy(request_pin), 'mapping': deepcopy(mapping), 'origin': origin,
            'original_planning_context': deepcopy(state['contract']['context_request']),
            'authority': 'prospective source declaration; no review, execution or parent acceptance'}
        if 'scientific_context_declaration' in state:
            if state['scientific_context_declaration'] == declaration:
                return state
            if expected_context_sha256 != state['context']['context_sha256']:
                raise ValueError('prospective context repair requires the exact current predecessor')
        elif expected_context_sha256 is not None:
            raise ValueError('context predecessor supplied for an initial declaration')
        original = state['context']['requested_quantities']
        if 'scientific_context_declaration' not in state and (len(original) != 1 or original[0]['id'] != 'original-obligations-pending-science'):
            raise ValueError('independently declared scientific context must not be replaced')
        _verified_context_declaration(state, declaration)
        request = _read(request_pin, state['base_dir'])
        context = scientific_context.compile_context(request, state['base_dir'])
        if any(q['id'] == 'original-obligations-pending-science' for q in context['requested_quantities']):
            raise ValueError('planning-status census cannot become scientific evidence')
        if 'scientific_context_declaration' in state:
            state.setdefault('prior_scientific_context_declarations',[]).append(deepcopy(state['scientific_context_declaration']))
        else:
            state['planning_context'] = deepcopy(state['context'])
        state['scientific_context_declaration'] = declaration
        state['context'] = context
        return _commit(Path(root), state, 'original_task_scientific_context_declared',
            complete_original_obligations_retained=True, review_required_before_scientific_effects=True)


def _graph_result(graph_root, node_id):
    root = _ordinary(graph_root)
    with state_io.file_lock(root / "state.lock"):
        spec, state = agent_graph._load(root)
        if state["cancelled"]: raise ValueError("cancelled graph cannot supply a current construction")
        selected = next((x for x in spec["nodes"] if x["id"] == node_id), None)
        node = state["nodes"].get(node_id)
        if selected is None or node is None or node["status"] != "completed" or node["result"] is None:
            raise ValueError("ordinary graph result is not complete")
        agent_graph._artifact_checks(selected)
        saved = agent_graph._result(root, node["result"])
        expected = agent_graph._request(spec, state, selected, saved["host_sha256"])
        if expected["binding_sha256"] != saved["request"]["binding_sha256"]:
            raise ValueError("graph response belongs to superseded source or dependencies")
        return {"root": str(root), "node_id": node_id, "generation": node["generation"],
            "binding_sha256": saved["request"]["binding_sha256"], "receipt": _pin(root / node["result"]["path"]),
            "inputs": deepcopy(selected["inputs"]), "node_kind": selected["kind"], "role": selected["role"],
            "value": saved["result"]}


def _context_revision(before, after):
    """Only one declared model node's bound packet/instructions may change."""
    before, after = agent_graph.validate(before), agent_graph.validate(after)
    a, b = deepcopy(before), deepcopy(after)
    changed = []
    if len(a['nodes']) != len(b['nodes']):
        raise ValueError('context revision retains the original node census')
    for old, new in zip(a['nodes'], b['nodes']):
        if old != new:
            if old['kind'] != 'model' or old['packet'] is None or new['packet'] is None:
                raise ValueError('context revision changes only an existing packet-bound model node')
            changed.append(old['id'])
            new['packet'] = deepcopy(old['packet'])
            new['parameters']['instructions'] = old['parameters']['instructions']
    if len(changed) != 1 or a != b:
        raise ValueError('context revision changes task, actors, model settings, parent or frozen budgets')
    return changed[0]


def _revision_state(state):
    return {k: deepcopy(state[k]) for k in ('graph_id', 'started_epoch', 'usage', 'reworks',
                'graph_revision', 'cancelled', 'cancel_reason', 'nodes')}


def _after_revision(record, current):
    before = record['before_state']
    if (current['started_epoch'] != before['started_epoch'] or current['usage'] != before['usage']
            or current['cancelled'] != before['cancelled'] or current['cancel_reason'] != before['cancel_reason']
            or current['reworks'] != before['reworks'] + 1
            or current['graph_revision'] != before['graph_revision'] + 1):
        raise ValueError('context admission cannot reset clocks, charges or graph generations')
    affected = set(agent_graph._affected(record['before_spec'], [record['node_id']]))
    for node_id, old in before['nodes'].items():
        expected = deepcopy(old)
        if node_id in affected:
            expected.update(status='pending', generation=old['generation']+1, generation_attempts=0,
                            attempt_id=None, result=None, retryable=False, error=None)
        if current['nodes'][node_id] != expected:
            raise ValueError('pending context revision requires its exact before/after graph checkpoint')


def validate_graph_reservation(state, graph_root, current_spec):
    """Read-only finite admitted revision chain; original reservation is never replaced."""
    graph_root = _ordinary(graph_root)
    current_spec = agent_graph.validate(current_spec)
    rows = [r for r in state['resource_ledger'] if r['id'] == 'graph:'+str(graph_root)]
    budget = current_spec['budget']
    amount = {'calls':budget['max_calls'], 'output_tokens':budget['max_output_tokens'],
              'wall_seconds':budget['max_wall_seconds'], 'native_attempts':0}
    if len(rows) != 1 or rows[0]['ceiling'] != amount:
        raise ValueError('retained exact resource reservation required; original resource reservation cannot change')
    origin = rows[0]['basis']['specification_sha256']
    prior = _read(_pin(graph_root/'specs'/(origin+'.json')), graph_root)
    if ce.digest(prior) != origin:
        raise ValueError('original reserved Graph specification changed')
    original = deepcopy(prior)
    pending = None
    for event in state['events']:
        if event.get('graph_root') != str(graph_root): continue
        if event['kind'] == 'ordinary_graph_revision_pending':
            if pending is not None: raise ValueError('unresolved graph context admission')
            record = event['admission']
            if (record['before_sha256'] != ce.digest(prior) or record['before_spec'] != prior
                    or record['reservation'] != rows[0]
                    or record['node_id'] != _context_revision(prior, record['new_spec'])
                    or record['after_sha256'] != ce.digest(record['new_spec'])):
                raise ValueError('context revision does not follow original admitted reservation')
            if _pin(record['predecessor_result_pin']['path']) != record['predecessor_result_pin']:
                raise ValueError('admitted context predecessor result changed')
            from .scientific_context_followup import authorize_revision
            if record['authorization'] != authorize_revision(graph_root, record['before_spec'], record['new_spec'], record['before_checkpoint'], record['predecessor_result_pin']):
                raise ValueError('admitted context authorization changed')
            pending = record
        elif event['kind'] == 'ordinary_graph_revision_admitted':
            if pending is None or event['admission_sha256'] != ce.digest(pending):
                raise ValueError('graph revision admission has no exact pending pair')
            saved = _read(_pin(graph_root/'specs'/(pending['after_sha256']+'.json')),graph_root)
            if saved != pending['new_spec']:
                raise ValueError('immutable admitted graph revision changed')
            prior, pending = saved, None
    if pending is not None:
        raise ValueError('pending graph revision must be reconciled before dispatch')
    if (current_spec != prior or current_spec['budget'] != original['budget']
            or ('goal_binding' in state['contract'] and current_spec.get('goal_binding') != state['contract']['goal_binding'])):
        raise ValueError('current Graph is not the exact admitted context revision')
    existing, checkpoint = agent_graph._load(graph_root)
    if existing != current_spec:
        raise ValueError('current graph checkpoint differs from admitted specification')
    return {'graph_root':str(graph_root), 'original_specification_sha256':origin,
            'current_specification_sha256':ce.digest(prior), 'reservation':deepcopy(rows[0]),
            'usage':deepcopy(checkpoint['usage']), 'started_epoch':checkpoint['started_epoch']}


def _recover_graph_revision_pair(graph_root, record, new_spec, before_sha, result_pin, reason):
    """Complete only the exact spec-after/state-before pair retained before revision."""
    if (record['before_sha256']!=before_sha or record['new_spec']!=new_spec
            or record['predecessor_result_pin']!=result_pin or record['reason']!=reason):
        raise ValueError('interrupted admission recovers only the same exact pair and predecessor')
    with state_io.file_lock(graph_root/'run.lock',blocking=False), state_io.file_lock(graph_root/'state.lock'):
        from .research_presentation import document
        actual_spec=document(_pin(graph_root/agent_graph.SPEC),graph_root,8*1024**2)
        actual_state=document(_pin(graph_root/agent_graph.STATE),graph_root,8*1024**2)
        if actual_spec!=new_spec or actual_state!=record['before_checkpoint']:
            raise ValueError('interrupted Graph files are not exact retained spec-after/state-before pair')
        if document(_pin(graph_root/'specs'/(record['after_sha256']+'.json')),graph_root,8*1024**2)!=new_spec:
            raise ValueError('interrupted immutable new specification changed')
        if _pin(result_pin['path'])!=result_pin:raise ValueError('interrupted predecessor changed')
        from .scientific_context_followup import authorize_revision
        if record['authorization']!=authorize_revision(graph_root,record['before_spec'],new_spec,actual_state,result_pin):
            raise ValueError('interrupted context authorization changed')
        agent_graph._deadline(record['before_spec'],actual_state)
        affected=agent_graph._affected(record['before_spec'],[record['node_id']])
        agent_graph._invalidate(actual_state,affected,reason)
        actual_state['spec_sha256']=record['after_sha256']
        agent_graph._event(actual_state,'spec_revised',before_sha256=before_sha,after_sha256=record['after_sha256'])
        agent_graph._save(graph_root,actual_state)
        _after_revision(record,actual_state)


def revise_graph(root, graph_root, new_spec, *, expected_spec_sha256, predecessor_result_pin, reason):
    """Admit a context-only revision, recovering only an exact retained pending pair."""
    graph_root = _ordinary(graph_root)
    _text(reason, 4000)
    ce.sha(expected_spec_sha256)
    new_spec = agent_graph.validate(new_spec)
    predecessor_result_pin = deepcopy(predecessor_result_pin)
    if root is None:
        from .scientific_context_followup import authorize_revision
        before, checkpoint = agent_graph._load(graph_root)
        if ce.digest(before)!=expected_spec_sha256:raise ValueError('stale expected standalone Graph specification')
        _context_revision(before,new_spec)
        result=checkpoint['nodes'][_context_revision(before,new_spec)]['result']
        if result is None or _pin(graph_root/result['path'])!=predecessor_result_pin:
            raise ValueError('exact standalone nonvoting predecessor required')
        authorize_revision(graph_root,before,new_spec,checkpoint,predecessor_result_pin)
        agent_graph._deadline(before,checkpoint)
        return agent_graph.revise(graph_root,new_spec,reason=reason,
            expected_spec_sha256=expected_spec_sha256,expected_state_sha256=ce.digest(checkpoint))
    root = _ordinary(root)
    _text(reason, 4000)
    ce.sha(expected_spec_sha256)
    new_spec = agent_graph.validate(new_spec)
    predecessor_result_pin = deepcopy(predecessor_result_pin)
    with state_io.file_lock(root/'operation.lock', blocking=False):
        _, state = _load(root)
        if state['timing']['deadline_epoch'] is None or time.time() >= state['timing']['deadline_epoch']:
            raise OperationalBoundaryError('context revision retains the original active campaign deadline')
        unresolved = None
        for event in state['events']:
            if event.get('graph_root') != str(graph_root): continue
            if event['kind'] == 'ordinary_graph_revision_pending': unresolved = event['admission']
            elif event['kind'] == 'ordinary_graph_revision_admitted': unresolved = None
        try:
            before, checkpoint = agent_graph._load(graph_root)
        except agent_graph.GraphError:
            if unresolved is None: raise
            _recover_graph_revision_pair(graph_root, unresolved, new_spec, expected_spec_sha256, predecessor_result_pin, reason)
            before, checkpoint = agent_graph._load(graph_root)
        agent_graph._deadline(before, checkpoint)
        if unresolved is not None:
            record = unresolved
            from .scientific_context_followup import authorize_revision
            if record['authorization']!=authorize_revision(graph_root,record['before_spec'],record['new_spec'],record['before_checkpoint'],record['predecessor_result_pin']):
                raise ValueError('pending nonvoting context authorization changed')
            if (record['before_sha256'] != expected_spec_sha256 or record['new_spec'] != new_spec
                    or record['predecessor_result_pin'] != predecessor_result_pin or record['reason'] != reason):
                raise ValueError('interrupted admission recovers only the same exact pair and predecessor')
            if ce.digest(before) == record['before_sha256']:
                if _revision_state(checkpoint) != record['before_state']:
                    raise ValueError('pending predecessor graph changed')
                agent_graph.revise(graph_root, new_spec, reason=reason, expected_spec_sha256=record['before_sha256'], expected_state_sha256=ce.digest(record['before_checkpoint']))
                before, checkpoint = agent_graph._load(graph_root)
            if ce.digest(before) != record['after_sha256']:
                raise ValueError('interrupted admission has a foreign graph revision')
            _after_revision(record, checkpoint)
        else:
            validate_graph_reservation(state, graph_root, before)
            if ce.digest(before) != expected_spec_sha256:
                raise ValueError('stale expected graph revision')
            node_id = _context_revision(before, new_spec)
            observed = [g for g in state['graphs'] if g['root'] == str(graph_root)]
            if (len(observed) != 1 or not observed[0]['complete']
                    or observed[0]['revision'] != expected_spec_sha256
                    or observed[0]['usage'] != checkpoint['usage']):
                raise ValueError('context revision requires current complete observed predecessor usage')
            result = checkpoint['nodes'][node_id]['result']
            if result is None or _pin(graph_root/result['path']) != predecessor_result_pin:
                raise ValueError('context revision requires the exact current predecessor result')
            if checkpoint['usage']['calls'] >= before['budget']['max_calls'] or checkpoint['reworks'] >= before['budget']['max_reworks']:
                raise ValueError('original graph call or rework budget exhausted')
            for node in new_spec['nodes']: agent_graph._artifact_checks(node)
            from .scientific_context_followup import authorize_revision
            authorization=authorize_revision(graph_root,before,new_spec,checkpoint,predecessor_result_pin)
            record = {'authorization':authorization,'before_spec':before,'before_sha256':expected_spec_sha256,'new_spec':new_spec,
                      'after_sha256':ce.digest(new_spec),'node_id':node_id,'before_state':_revision_state(checkpoint),'before_checkpoint':deepcopy(checkpoint),
                      'predecessor_result_pin':predecessor_result_pin,'reason':reason,
                      'reservation':deepcopy(next(r for r in state['resource_ledger'] if r['id']=='graph:'+str(graph_root)))}
            state = _commit(root,state,'ordinary_graph_revision_pending',graph_root=str(graph_root),admission=record)
            agent_graph.revise(graph_root,new_spec,reason=reason,expected_spec_sha256=expected_spec_sha256,expected_state_sha256=ce.digest(checkpoint))
            _, checkpoint = agent_graph._load(graph_root)
            _after_revision(record,checkpoint)
        if _pin(predecessor_result_pin['path']) != predecessor_result_pin:
            raise ValueError('context predecessor changed during admission')
        _commit(root,state,'ordinary_graph_revision_admitted',graph_root=str(graph_root),admission_sha256=ce.digest(record))
        return agent_graph.status(graph_root)


def execute_graph(root, graph_root, graph_spec, host, *, prepared=False, workers=1):
    """Use the existing graph/Host; preserve spent reservations if dispatch fails."""
    graph_root = _ordinary(graph_root)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError('finite Graph worker population required')
    if type(prepared) is not bool: raise ValueError("explicit prepared Graph policy required")
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        if "goal_binding" in state["contract"]:
            graph_spec = deepcopy(graph_spec)
            inherited = state["contract"]["goal_binding"]
            if "goal_binding" in graph_spec and graph_spec["goal_binding"] != inherited:
                raise ValueError("research Graph cannot replace its original parent assignment")
            graph_spec["goal_binding"] = deepcopy(inherited)
        validated = agent_graph.validate(graph_spec)
        ceilings = graph_spec["budget"]
        amount = {"calls": ceilings["max_calls"], "output_tokens": ceilings["max_output_tokens"],
                  "wall_seconds": ceilings["max_wall_seconds"], "native_attempts": 0}
        identity = "graph:" + str(graph_root)
        from . import manuscript_workflow
        manuscript_workflow._action_graph_admission(root,state,graph_root,validated,amount,
            reserved=identity in {row["id"] for row in state["resource_ledger"]})
        if identity not in {row["id"] for row in state["resource_ledger"]}:
            refusal = _clock(state, ceilings["max_wall_seconds"])
            if refusal is not None:
                state["operational_boundaries"].append({"operation": identity, **refusal})
                _commit(Path(root), state, "operational_boundary_retained", operation=identity)
                raise OperationalBoundaryError("original campaign cannot fit the declared graph branch")
            if prepared:
                with state_io.file_lock(graph_root / "state.lock"):
                    existing, current = agent_graph._load(graph_root)
                    if (existing != validated or current["started_epoch"] is not None
                            or current["cancelled"] or current["reworks"] or current["graph_revision"]
                            or current["usage"] != {"calls": 0, "reserved_output_tokens": 0} or current["calls"]
                            or any(n["status"] != "pending" or n["attempts"] or n["generation"] or n["result"] is not None
                                   for n in current["nodes"].values())):
                        raise ValueError("first campaign reservation requires exact pristine prepared Graph")
                    for node in existing["nodes"]: agent_graph._artifact_checks(node)
                    _charge(state, identity, amount, {"specification_sha256": ce.digest(graph_spec)})
                    _commit(Path(root), state, "ordinary_graph_reserved", graph_root=str(graph_root))
            else:
                _charge(state, identity, amount, {"specification_sha256": ce.digest(graph_spec)})
                agent_graph.create(graph_root, graph_spec)
                _commit(Path(root), state, "ordinary_graph_reserved", graph_root=str(graph_root))
        else:
            validate_graph_reservation(state, graph_root, validated)
            with state_io.file_lock(graph_root / "state.lock"):
                existing, _ = agent_graph._load(graph_root)
                if existing != validated: raise ValueError("current Graph differs from its original campaign reservation")
        failure = None
        try:
            # Authenticate/reload after the potentially costly reservation and
            # source validation. This is the original timer, never a fresh fit
            # of the full ceiling for an already-started charged Graph.
            _, current_campaign = _load(root)
            timing = current_campaign['timing']
            with state_io.file_lock(graph_root / 'state.lock'):
                existing, checkpoint = agent_graph._load(graph_root)
                if existing != validated:
                    raise ValueError('current Graph differs from its original campaign reservation')
                agent_graph._deadline(existing, checkpoint)
                now = time.time()
                if timing['started_epoch'] is None or timing['deadline_epoch'] is None:
                    raise ValueError('existing reservation requires its original campaign timer')
                remaining = timing['deadline_epoch'] - now
                if checkpoint['started_epoch'] is None:
                    required = ceilings['max_wall_seconds']
                    fits = required <= remaining
                else:
                    child_deadline = checkpoint['started_epoch'] + ceilings['max_wall_seconds']
                    required = child_deadline - now
                    if required <= 0:
                        raise agent_graph.GraphError('graph cumulative wall-time budget exhausted')
                    # Compare fixed deadlines directly: equality is admitted
                    # without subtracting elapsed validation twice or tolerance.
                    fits = child_deadline <= timing['deadline_epoch']
            if remaining <= 0 or not fits:
                refusal = {'kind':'campaign_deadline_insufficient_for_declared_branch', 'observed_epoch':now,
                    'original_started_epoch':timing['started_epoch'], 'original_deadline_epoch':timing['deadline_epoch'],
                    'elapsed_seconds':now-timing['started_epoch'], 'remaining_seconds':max(0.0,remaining),
                    'required_ceiling_seconds':required, 'scientific_result':None, 'new_attempts':0}
                current_campaign['operational_boundaries'].append({'operation':identity,**refusal})
                _commit(Path(root),current_campaign,'operational_boundary_retained',operation=identity)
                raise OperationalBoundaryError('original campaign cannot fit the declared graph branch')
            return agent_graph.execute(graph_root, host, workers=workers)
        except BaseException as exc:
            failure = type(exc).__name__
            raise
        finally:
            _, state = _load(root)
            try:
                observed = agent_graph.status(graph_root)
                row = {"root": str(graph_root), "usage": observed["usage"],
                       "revision": observed["spec_sha256"], "complete": observed["complete"]}
            except (ValueError, OSError, KeyError, TypeError):
                row = {"root": str(graph_root), "usage": None, "revision": ce.digest(graph_spec), "complete": False}
            if failure is not None: row["dispatch_error"] = failure
            state["graphs"] = [old for old in state["graphs"] if old["root"] != str(graph_root)] + [row]
            _commit(Path(root), state, "ordinary_graph_observed", graph_root=str(graph_root))


def _append_hypotheses(state, hypotheses, provenance):
    if type(hypotheses) is not list or not 1 <= len(hypotheses) <= 16 or len(state["hypotheses"]) + len(hypotheses) > 64:
        raise ValueError("bounded competing hypothesis census required")
    for row in hypotheses:
        ce.keys({k: v for k, v in row.items() if k not in {"identity_signature", "kill_condition", "reopening_trigger", "operator", "what_is_new", "reopening_receipt"}}, ("id", "statement", "stream", "premise_ids", "source_basis", "parents"))
        _register_proposal(state, row)
        ce.identity(row["id"]); _text(row["statement"])
        if row["id"] in {h["id"] for h in state["hypotheses"]} or row["stream"] not in {"citation_led", "speculative"}:
            raise ValueError("distinct hypothesis identity and explicit stream required")
        if type(row["source_basis"]) is not list or len(row["source_basis"]) > 16: raise ValueError("bounded source basis required")
        for pin in row["source_basis"]: _check_pin(pin, state["base_dir"])
        if type(row["parents"]) is not list or len(set(row["parents"])) != len(row["parents"]) or set(row["parents"]) - {h["id"] for h in state["hypotheses"]}:
            raise ValueError("retained existing hypothesis parents required")
        # No citation-count, consensus, prior-success or likelihood filter.
        inherited = {key: digest for h in state["hypotheses"] if h["id"] in row["parents"]
                     for key, digest in h["premise_bindings"].items()}
        # A descendant remains conditional on its parents' premises. Explicitly
        # restating a changed premise creates a visibly requalified new hypothesis.
        inherited.update(_bindings(state, row["premise_ids"]))
        state["hypotheses"].append({**deepcopy(row), "premise_bindings": inherited,
                                     "origin": provenance})

def propose(root, hypotheses, *, origin):
    """Retain rivals, including unsupported speculative ideas, without a truth gate.

    Origin is either a current ordinary graph result or an explicitly supplied
    source proposal. Source controls cannot masquerade as actual model calls.
    """
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        if origin.get("kind") == "graph":
            ce.keys(origin, ("kind", "root", "node_id")); provenance = _graph_result(origin["root"], origin["node_id"])
            result = provenance["value"]
            if result.get("kind") not in {"model_result", "ravel_tool_result"} or result["value"].get("hypotheses") != hypotheses:
                raise ValueError("hypotheses must equal the actual structured graph response")
        elif origin.get("kind") == "supplied_source":
            ce.keys(origin, ("kind", "pin", "description")); _text(origin["description"])
            supplied = _read(origin["pin"], state["base_dir"])
            if supplied != hypotheses: raise ValueError("supplied hypotheses differ from original bytes")
            provenance = deepcopy(origin)
        else: raise ValueError("actual graph or explicit source proposal origin required")
        _append_hypotheses(state, hypotheses, provenance)
        return _commit(Path(root), state, "competing_hypotheses_proposed", ids=[h["id"] for h in hypotheses])



def propose_action(root, origin, hypotheses):
    """Consume a real research-action envelope while retaining its whole receipt."""
    from .agent_host import _loads
    with state_io.file_lock(Path(root)/'operation.lock',blocking=False):
        _,state=_load(root)
        actual=_graph_result(origin['root'],origin['node_id'])
        if actual!=origin or actual['value'].get('kind')!='model_result':
            raise ValueError('actual model action origin required')
        public=actual['value']['value']
        if (public.get('kind')!='research-action' or public.get('action')!='propose'
                or _loads(public['arguments_json'])!={'hypotheses':hypotheses}):
            raise ValueError('hypotheses must equal the unchanged actual action envelope')
        allowed={(p['path'],p['sha256']) for p in actual['inputs']}
        if any((p['path'],p['sha256']) not in allowed for h in hypotheses for p in h['source_basis']):
            raise ValueError('new hypothesis sources must have been actually presented')
        existing=[h for h in state['hypotheses'] if h['id'] in {r['id'] for r in hypotheses}]
        if existing:
            if len(existing)!=len(hypotheses) or any(h['origin']!=actual or
                    {k:h[k] for k in hypotheses[0]}!=next(r for r in hypotheses if r['id']==h['id']) for h in existing):
                raise ValueError('partial or foreign hypothesis effect cannot be replayed')
            return state
        _append_hypotheses(state,hypotheses,actual)
        return _commit(Path(root),state,'model_action_hypotheses_proposed',ids=[h['id'] for h in hypotheses])


def _coordinator_effect(state, origin):
    """Reconcile routing references against the existing campaign history.

    This is an effect commitment, never an approval, physics vote or parent
    acceptance. Ordinary effects continue to validate their own receipts.
    """
    from .agent_host import _loads
    actual=_graph_result(origin['root'],origin['node_id'])
    if actual!=origin or actual['value'].get('kind')!='model_result':
        raise ValueError('unchanged actual coordinator decision required')
    rows=[event for event in state['events'] if event['kind']=='coordinator_effect_committed'
        and event['decision_sha256']==ce.digest(actual)]
    if not rows:return None
    if len(rows)!=1:raise ValueError('one canonical effect per actual coordinator decision required')
    pin=rows[0]['effect'];document=_read(pin,state['base_dir'])
    ce.keys(document,{'action','arguments','origin','actual_effect','parent_task_accepted','scientific_authority_from_checkpoint'})
    public=actual['value']['value']
    if (public.get('kind')!='research-action' or document['origin']!=actual
            or document['action']!=public['action']
            or document['arguments']!=_loads(public['arguments_json'])
            or document['parent_task_accepted'] is not False
            or document['scientific_authority_from_checkpoint'] is not False):
        raise ValueError('committed coordinator effect differs from its actual decision')
    effect=document['actual_effect']
    for artifact in effect.get('materialized_inputs',[]):_check_pin(artifact,state['base_dir'])
    if 'actual_preparation' in effect:
        prepared=effect['actual_preparation']
        if _graph_result(prepared['root'],prepared['node_id'])!=prepared:
            raise ValueError('ordinary preparation effect changed')
    if 'authored_configuration_provenance' in effect:
        authored=_read(effect['authored_configuration_provenance'],state['base_dir'])
        if authored['origin']!=actual or authored['physics_validated'] is not False:
            raise ValueError('authored configuration lost its actual decision/non-observation provenance')
    if 'experiment' in effect:
        experiment=next(e for e in state['experiments'] if e['id']==effect['experiment'])
        if experiment['observation'] is None:
            for artifact in [experiment['study'],*experiment['input_pins']]:_check_pin(artifact,state['base_dir'])
        else:_current_evidence(state,experiment)
        if 'actual_observation' in effect and effect['actual_observation']!=experiment['observation']:
            raise ValueError('recorded observation differs from its ordinary scientific attempt')
        if document['action']=='experiment' and (experiment.get('coordinator_origin')!=actual or effect['study']!=experiment['study']):
            raise ValueError('experiment design differs from its actual ordinary admission')
    return {'pin':deepcopy(pin),'document':document}


def _record_coordinator_effect(root, origin, effect_pin):
    """Append the intended effect pin to the original immutable domain journal."""
    with state_io.file_lock(Path(root)/'operation.lock',blocking=False):
        _,state=_load(root)
        previous=_coordinator_effect(state,origin)
        if previous is not None:
            if previous['pin']!=effect_pin:raise ValueError('coordinator decision already committed another effect')
            return previous
        actual=_graph_result(origin['root'],origin['node_id'])
        graph_root=_ordinary(actual['root'])
        spec,_=agent_graph._load(graph_root)
        validate_graph_reservation(state,graph_root,spec)
        path,_=_check_pin(effect_pin,state['base_dir'])
        if not path.is_relative_to(Path(root)):
            raise ValueError('coordinator effects must remain inside their original campaign')
        # Validate the whole prospective row using the same ending consumer
        # before adding it. No rehashing or new source capture is accepted.
        prospective=deepcopy(state)
        prospective['events'].append({'kind':'coordinator_effect_committed',
            'decision_sha256':ce.digest(actual),'effect':deepcopy(effect_pin)})
        checked=_coordinator_effect(prospective,actual)
        newer=_commit(Path(root),state,'coordinator_effect_committed',
            decision_sha256=ce.digest(actual),effect=deepcopy(effect_pin),scientific_acceptance=False)
        return _coordinator_effect(newer,actual)


def _board_hypothesis_id(charter_sha256, actor_id, hypothesis_id, source_sha256):
    # Original charter, actor, hypothesis name and complete claim bytes bind the
    # cycle identity. Explicit duplicate/collision admission remains below.
    return 'board-' + ce.digest({'charter_sha256': charter_sha256, 'actor_id': actor_id,
        'hypothesis_id': hypothesis_id, 'source_sha256': source_sha256})


def import_board(root, board_root, *, streams):
    """Import the complete revealed population, in one existing cycle commit."""
    view = hypothesis_board.snapshot(board_root)
    if view['phase'] != 'followups_open': raise ValueError('initial board reveals incomplete')
    if type(streams) is not dict or set(streams) != {p['actor_id'] for p in view['participants']}:
        raise ValueError('complete participant stream declarations required')
    # A board hypothesis's register declaration travels with it; the cycle register
    # validates it exactly as for a directly proposed hypothesis.
    rows = [{'id': _board_hypothesis_id(view['charter_sha256'], row['actor_id'], row['id'], row['hypothesis_sha256']), 'statement': row['statement'],
        'stream': streams[row['actor_id']], 'premise_ids': [], 'source_basis': [], 'parents': [],
        **deepcopy(row.get('register', {}))}
        for row in view['hypotheses']]
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('original board identity mapping collision')
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = _load(root)
        path = Path(root) / 'board-proposals' / (ce.digest(view) + '.json')
        board_path = Path(root) / 'board-proposals' / (ce.digest(view) + '-complete-board.json')
        if path.exists() or board_path.exists():
            raise ValueError('original complete board import already materialized')
        raw = (json.dumps(rows, indent=2, allow_nan=False) + '\n').encode()
        pin = {'path': str(_ordinary(path)), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
        provenance = {'kind': 'supplied_source', 'pin': pin,
            'description': 'Existing sealed board ' + view['charter_sha256'] +
                '; complete original predictions and artifacts retained at ' + str(board_path) +
                '; actor independence is declared, not OS-enforced.'}
        # Existing per-addition bounds remain; all batches validate BEFORE writes
        # or a commit, so an oversized/invalid tail cannot silently omit rivals.
        if not rows: raise ValueError('nonempty revealed hypothesis population required')
        for offset in range(0, len(rows), 16):
            _append_hypotheses(state, rows[offset:offset + 16], provenance)
        if hypothesis_board.snapshot(board_root) != view:
            raise ValueError('board changed before complete import')
        state_io.atomic_json(path, rows)
        state_io.atomic_json(board_path, view)
        from .research_followup import _bytes
        _bytes(pin, state['base_dir'])
        board_raw = (json.dumps(view, indent=2, allow_nan=False) + '\n').encode()
        _bytes({'path': str(_ordinary(board_path)), 'sha256': hashlib.sha256(board_raw).hexdigest(),
                'size': len(board_raw)}, state['base_dir'])
        if hypothesis_board.snapshot(board_root) != view:
            raise ValueError('board changed during complete import')
        return _commit(Path(root), state, 'competing_hypotheses_proposed', ids=[h['id'] for h in rows])


def _discrimination(predictions):
    """Prospective contrast metadata, never observed resolving power."""
    known = {value for value in predictions.values() if value is not None}
    status = "distinct_declared_predictions" if len(known) >= 2 else "same_declared_prediction" if known else "predictions_unknown"
    return {"status": status, "hypotheses_with_known_prediction": sum(v is not None for v in predictions.values()),
            "distinct_declared_outcomes": len(known), "observed_discrimination": False,
            "scope": "Prospective outcome labels only; actual resolution still needs source-bound intervention, held conditions, measurement and precision."}


def _tool_input_closure(experiment, dependencies, base, *, state=None):
    """Retain actual design context beside the ordinary scientific dependencies."""
    result = deepcopy(dependencies)
    if _quantitative(experiment):
        from . import quantitative_predictive_checks as predictive
        spec = _read(experiment["study"], base)
        if spec.get("quantitative_check", {}).get("contract") != experiment["observable"]["contract"]:
            raise ValueError("quantitative observable differs from ordinary planned binding")
        for path in predictive.inputs(spec["quantitative_check"], base):
            pin = _pin(path)
            if pin not in result:
                if any(p["path"] == pin["path"] for p in result): raise ValueError("quantitative source identity conflicts")
                result.append(pin)
    if "tool_context" not in experiment:
        return result
    from .research_tools import check_binding, input_pins
    check_binding(experiment["tool_context"], base, state=state)
    for pin in input_pins(experiment["tool_context"], base):
        matches = [existing for existing in result if existing["path"] == pin["path"]]
        if matches and any(existing != pin for existing in matches):
            raise ValueError("conflicting complete research-tool input identity")
        if not matches:
            result.append(deepcopy(pin))
    return result


def _quantitative(experiment):
    return type(experiment.get("observable")) is dict and experiment["observable"].get("kind") == "quantitative"


def _append_design(state, experiment):
    fields = {"id", "question", "premise_ids", "parent", "change", "study", "cost", "predictions",
              "observable", "context_outputs", "acceptance_scope", "exploratory"}
    ce.keys(experiment, fields | ({"evaluation"} if "evaluation" in experiment else set()) | ({"input_exposure"} if "input_exposure" in experiment else set())
            | ({"tool_context"} if "tool_context" in experiment else set()))
    ce.identity(experiment["id"])
    if "evaluation" in experiment:
        from .research_evaluation import validate_declaration
        validate_declaration(experiment["evaluation"])
    for key in ("question", "change", "acceptance_scope"): _text(experiment[key])
    if len(state["experiments"]) >= state["contract"]["max_experiments"] or experiment["id"] in {x["id"] for x in state["experiments"]}:
        raise ValueError("finite distinct experiment identity required")
    parent = experiment["parent"]
    if parent is not None and parent not in {x["id"] for x in state["experiments"]}: raise ValueError("existing experiment parent required")
    if type(experiment["exploratory"]) is not bool: raise ValueError("explicit exploratory designation required")
    _vector(experiment["cost"])
    spec = _read(experiment["study"], state["base_dir"]); science.validate(spec)
    if "goal_binding" in state["contract"] and spec.get("goal_binding") != state["contract"]["goal_binding"]:
        raise ValueError("prospective study must preserve the research parent assignment")
    if spec["schema_version"] != 2 or spec["max_attempts"] != 1 or spec["review_policy"]["policy"]["max_redos"] != 0:
        raise ValueError("new immutable v2 one-attempt study per design required")
    if experiment["acceptance_scope"] not in spec["review_policy"]["policy"]["claim_scopes"]:
        raise ValueError("study must prospectively admit exactly the requested claim scope")
    if experiment["cost"]["wall_seconds"] < spec["max_seconds"] or experiment["cost"]["native_attempts"] != 1:
        raise ValueError("study hard ceiling and one counted operation attempt must fit declared cost")
    active = {h["id"] for h in state["hypotheses"] if _fresh(state, h["premise_bindings"])}
    predictions = experiment["predictions"]
    if type(predictions) is not dict or not predictions or set(predictions) - active:
        raise ValueError("current explicit competing hypothesis predictions required")
    observable = experiment["observable"]
    quantitative_binding = None
    if _quantitative(experiment):
        from . import quantitative_predictive_checks as predictive
        quantitative_binding = predictive.admit_design(state, experiment, spec)
    else:
        ce.keys(observable, ("pointer", "outcomes"))
        if type(observable["pointer"]) is not str or not observable["pointer"].startswith("/"):
            raise ValueError("literal observed result pointer required")
        if type(observable["outcomes"]) is not dict or not 1 <= len(observable["outcomes"]) <= 16:
            raise ValueError("bounded prospective exact outcome classifier required")
        for label, value in observable["outcomes"].items(): ce.identity(label); ce.digest(value)
        if len({ce.digest(x) for x in observable["outcomes"].values()}) != len(observable["outcomes"]):
            raise ValueError("outcome labels require distinct exact measurements")
        if any(value is not None and value not in observable["outcomes"] for value in predictions.values()):
            raise ValueError("predictions must name a prospective outcome or remain unknown")
    artifacts = {q["artifact"] for q in state["context"]["requested_quantities"]}
    if type(experiment["context_outputs"]) is not dict or set(experiment["context_outputs"]) - artifacts:
        raise ValueError("context outputs must name requested scientific artifacts")
    for path in experiment["context_outputs"].values():
        if path != "outputs/attempt-1/result.json": raise ValueError("current delivered result required for quantity context")
    base = Path(experiment["study"]["path"]).parent
    base = base if base.is_absolute() else Path(state["base_dir"]) / base
    dependencies = [_pin(path) for path in science.task_inputs(spec, base)]
    dependencies = _tool_input_closure(experiment, dependencies, state["base_dir"], state=state)
    _exposure_manifest(experiment, dependencies, state["base_dir"])
    from . import research_protocol
    research_protocol.admit_design(state, experiment)
    state["experiments"].append({**deepcopy(experiment), "premise_bindings": _bindings(state, experiment["premise_ids"]),
        "input_pins": dependencies, "discrimination": _discrimination(predictions),
        "rundir": None, "plan": None, "observation": None, "adjudication": None})
    if quantitative_binding is not None:
        state["experiments"][-1]["quantitative_binding"] = quantitative_binding

def _verify_preregistration(root, state):
    """Design admission re-derives the campaign preregistration, as ordinary launch does."""
    if state['contract'].get('research_protocol_required') and state.get('methodology'):
        from .research_launch import verify
        errors = verify(root)
        if errors:
            raise ValueError('; '.join(errors))


def design(root, experiment):
    """Add a complete prospective ordinary study and rival predicted outcomes."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        _append_design(state, experiment)
        _verify_preregistration(root, state)
        return _commit(Path(root), state, "prospective_design_added", experiment_id=experiment["id"],
                       discrimination=state["experiments"][-1]["discrimination"])


def bind_input_exposure(experiment, classifications, output_dir, *, base_dir, reason):
    """Separate model-visible source from withheld evaluation/runtime bytes.

    Whole execution custody is preserved. The model receives a complete pinned
    inventory, plus only explicitly disclosed source content. This is packet
    isolation, not an OS sandbox or proof that a shared-filesystem actor is blind.
    """
    _text(reason)
    spec = _read(experiment["study"], base_dir)
    source = Path(experiment["study"]["path"])
    source = source if source.is_absolute() else Path(base_dir) / source
    pins = [_pin(path) for path in science.task_inputs(spec, source.parent)]
    pins = _tool_input_closure(experiment, pins, base_dir)
    if type(classifications) is not dict or set(classifications) != {pin["path"] for pin in pins}:
        raise ValueError("complete canonical execution input exposure census required")
    if any(x not in {"model_context", "withheld_evaluation", "execution_dependency"} for x in classifications.values()):
        raise ValueError("explicit model, withheld-evaluation or execution-dependency purpose required")
    value = {"kind": "research_execution_input_exposure", "study": experiment["study"],
        "inputs": [{**pin, "purpose": classifications[pin["path"]]} for pin in pins], "reason": reason,
        "whole_worker_custody_retained": True, "OS_blinding_enforced": False}
    path = _ordinary(output_dir) / (ce.digest(value) + ".json")
    if not path.exists(): state_io.atomic_json(path, value)
    result = deepcopy(experiment)
    result["input_exposure"] = _pin(path)
    return result


def _exposure_manifest(experiment, dependencies, base):
    if "input_exposure" not in experiment: return None
    manifest = _read(experiment["input_exposure"], base)
    ce.keys(manifest, ("kind", "study", "inputs", "reason", "whole_worker_custody_retained", "OS_blinding_enforced"))
    if manifest["kind"] != "research_execution_input_exposure" or manifest["study"] != experiment["study"]:
        raise ValueError("exposure inventory must bind the exact prospective study")
    if manifest["whole_worker_custody_retained"] is not True or manifest["OS_blinding_enforced"] is not False:
        raise ValueError("actual declared packet isolation boundary required")
    _text(manifest["reason"])
    actual = {pin["path"]: pin for pin in dependencies}
    listed = {}
    if type(manifest["inputs"]) is not list: raise ValueError("complete exposure input list required")
    for row in manifest["inputs"]:
        ce.keys(row, ("path", "sha256", "size", "purpose"))
        if row["path"] in listed or row["purpose"] not in {"model_context", "withheld_evaluation", "execution_dependency"}:
            raise ValueError("distinct exact input exposure classifications required")
        listed[row["path"]] = {k: row[k] for k in ("path", "sha256", "size")}
    if listed != actual: raise ValueError("all execution dependencies must remain exactly pinned in exposure inventory")
    return manifest


def _model_input_admission(experiment, dependencies, presented_pins, base):
    presented = {(str(_ordinary(pin["path"])), pin["sha256"]) for pin in presented_pins}
    manifest = _exposure_manifest(experiment, dependencies, base)
    if manifest is None:
        required = dependencies
    else:
        pin = experiment["input_exposure"]
        if (str(_ordinary(pin["path"])), pin["sha256"]) not in presented:
            raise ValueError("the whole exposure inventory must be an ordinary Host input")
        required = [row for row in manifest["inputs"] if row["purpose"] == "model_context"]
        presented_hashes = {digest for _, digest in presented}
        if any(row["sha256"] in presented_hashes for row in manifest["inputs"] if row["purpose"] != "model_context"):
            raise ValueError("withheld evaluation or execution-only content cannot enter this model packet")
    if any((pin["path"], pin["sha256"]) not in presented for pin in required):
        raise ValueError("all explicitly disclosed study sources must be normal Host inputs")



def _experiment_reservation(state,e,root):
    """Source-bound attribution only for an already reserved ROOT master."""
    spec=_read(e['study'],state['base_dir'])
    if spec.get('mode')!='root-stream':return None
    from ravel.physics import root_stream_partitions
    path=Path(e['study']['path']);path=path if path.is_absolute() else Path(state['base_dir'])/path
    return root_stream_partitions.campaign_reservation(spec,path.parent,root,e['cost'])

def select(root, *, allocation=None):
    """Rank affordable distinct predictions, reserving an exploratory branch.

    Optional allocation is recomputed through scientific_phase_allocation, whose
    mandatory check reservations cannot be overridden by this ranking.
    """
    _, state = _load(root)
    usage = _usage(state)
    afforded = None
    policy = _phase_allocation(state)
    if policy is not None:
        if allocation is not None: raise ValueError("bound phase policy cannot be overridden by an advisory request")
        afforded = set(policy["affordable_design_ids"])
    if allocation is not None:
        from . import scientific_phase_allocation
        if allocation["budget"] != state["contract"]["budget"] or allocation["usage"] != usage:
            raise ValueError("phase allocation must use actual cumulative research reservations")
        policy = scientific_phase_allocation.allocate(allocation)
        afforded = set(policy["affordable_design_ids"])
        by_id = {row["id"]: row for row in allocation["designs"]}
        if set(by_id) != {e["id"] for e in state["experiments"]} or any(
                by_id[e["id"]]["construction_cost"] != e["cost"] for e in state["experiments"]):
            raise ValueError("allocation must retain the exact design census and actual construction ceilings")
    rows = []
    active_hypotheses = {x["id"] for x in state["hypotheses"] if _fresh(state, x["premise_bindings"])}
    from . import research_protocol
    for e in state["experiments"]:
        reasons = research_protocol.eligibility(state, e["id"])
        if "tool_context" in e and e["observation"] is None and _fresh(state, e["premise_bindings"]):
            from .research_tools import check_binding
            check_binding(e["tool_context"], state["base_dir"], state=state)
        if e["rundir"] is not None: reasons.append("already reserved; use ordinary resume or evidence intake")
        if not _fresh(state, e["premise_bindings"]) or "applicability_reopened" in e or set(e["predictions"]) - active_hypotheses: reasons.append("changed premise; redesign required")
        if e["parent"] is not None:
            parent = next(x for x in state["experiments"] if x["id"] == e["parent"])
            reviewed = parent["adjudication"] is not None or parent.get("diagnostic_feedback") is not None
            if parent["observation"] is None or not reviewed: reasons.append("parent outcome and constructive review still required")
            elif _failed_parent(parent): _current_evidence(state, parent)
        reservation = None if _failed_parent(e) else _experiment_reservation(state,e,root)
        incremental = e["cost"] if reservation is None else reservation["incremental_cost"]
        if any(usage[k] + incremental[k] > state["contract"]["budget"][k] for k in VECTORS): reasons.append("remaining resource ceiling insufficient")
        if state["timing"]["started_epoch"] is not None and e["cost"]["wall_seconds"] > max(0.0, state["timing"]["deadline_epoch"] - time.time()):
            reasons.append("original campaign wall cannot fit the declared branch, including queue/admission time")
        phase_afforded = afforded
        reserved_phase = None
        if reservation is not None and state["phase_policy"] is not None:
            # Original declared cost/evidence policy stays immutable. Only the
            # construction debit is attributed to its authenticated master;
            # every pending check, polish cost and actual usage stays intact.
            from . import scientific_phase_allocation
            request = deepcopy(state["phase_policy"]["request"])
            request["usage"] = usage
            request["completed_check_ids"] = policy["ordinary_current_completed_check_ids"]
            request["retained_design_ids"] = [x["id"] for x in state["experiments"] if x["rundir"] is not None]
            next(x for x in request["designs"] if x["id"] == e["id"])["construction_cost"] = incremental
            reserved_phase = scientific_phase_allocation.allocate(request)
            phase_afforded = set(reserved_phase["affordable_design_ids"])
        if phase_afforded is not None and e["id"] not in phase_afforded: reasons.append("required checking reservation blocks construction")
        if state["phase_policy"] is not None:
            completed = set(policy["ordinary_current_completed_check_ids"])
            required = set(state["phase_policy"]["preconstruction_checks"][e["id"]])
            if required - completed: reasons.append("actual low-cost lifecycle or preconstruction checking remains incomplete")
        spec = None if _failed_parent(e) else _read(e["study"], state["base_dir"])
        if spec is not None and spec["mode"] in {"routine-build", "rivet", "rivet-built", "native-construction", "model-derive"}:
            lifecycle = [] if state["phase_policy"] is None else [i for i in state["phase_policy"]["preconstruction_checks"][e["id"]]
                if state["phase_policy"]["check_contracts"][i]["purpose"] == "adapter_lifecycle"]
            if not lifecycle: reasons.append("new native adapter phase requires an actual declared low-cost lifecycle check")
        separation = sum(left is not None and right is not None and left != right for left, right in combinations(e["predictions"].values(), 2))
        rows.append({"id": e["id"], "affordable": not reasons, "reasons": reasons, "distinct_prediction_pairs": separation,
                     "exploratory": e["exploratory"], "cost": e["cost"]})
        if _quantitative(e):
            from . import quantitative_predictive_checks as predictive
            guidance = e["quantitative_binding"]["guidance"]
            # Checking is inside the planned producer wall; advisory selection
            # consumes only the already committed prospective separation below.
            rows[-1]["quantitative_selection"] = _quantitative_selection_current(state,e)
            if guidance["requirements"]["status"] != "admitted":
                rows[-1]["affordable"] = False
                rows[-1]["reasons"].extend(guidance["requirements"]["reasons"])
        if reservation is not None:
            rows[-1].update(reservation_basis=reservation["master"],incremental_cost=incremental,
                            reserved_master_phase_allocation=reserved_phase)
    from . import gate_wiring
    for row in rows:
        allowed, reason = gate_wiring.dispatch_permitted(root, row['id'])
        if not allowed:
            row['affordable'] = False
            row['reasons'].append(reason)
    eligible = [row for row in rows if row["affordable"]]
    completed = sum(x["observation"] is not None for x in state["experiments"])
    exploration = bool(completed and completed % state["contract"]["exploration_every"] == 0)
    pool = [x for x in eligible if x["exploratory"]] if exploration and any(x["exploratory"] for x in eligible) else eligible
    chosen = min(pool, key=lambda x: (-x["distinct_prediction_pairs"], x["cost"]["native_attempts"], x["cost"]["wall_seconds"], x["id"])) if pool else None
    from .quantitative_predictive_checks import choose_declared
    declared = choose_declared(pool)
    if declared is not None: chosen = declared
    ordinary_order = sorted(pool, key=lambda x: (-x['distinct_prediction_pairs'], x['cost']['native_attempts'], x['cost']['wall_seconds'], x['id']))
    if declared is not None:
        ordinary_order = [declared] + [row for row in ordinary_order if row['id'] != declared['id']]
    ranked = gate_wiring.prioritize_pending(root, ordinary_order)
    if ranked and any(event['effect'] == 'priority' for event in gate_wiring.steering_records(root)):
        chosen = ranked[0]
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during selection")
    return {"kind": "research_experiment_selection", "state_sha256": state["sha256"], "selected": None if chosen is None else chosen["id"],
            "designs": rows, "usage_ceiling": usage, "exploration_due": exploration,
            "policy": "ordinary eligibility and periodic exploration first; one explicit comparable committed quantitative objective when supplied, otherwise distinct declared categorical pairs; then smaller declared cost and stable ID; no posterior or causal estimate",
            "phase_allocation": policy, "parent_task": deepcopy(state.get("parent_task")),
            "parent_task_accepted": False, "execution_authorized": False, "physics_validated": False}



def bind_quantitative_selection(root, identity, *, graph_root=None, node_id=None, rundir=None):
    """Connect a charged actual tool or ordinary pure-operation diagnostic.

    No compute occurs here or in select. The old campaign/authority gates own
    effects; this binds an actual quantitative result to one prospective design.
    """
    from . import quantitative_predictive_checks as predictive
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(row for row in state["experiments"] if row["id"] == identity)
        if not _quantitative(e) or e["rundir"] is not None or not _fresh(state,e["premise_bindings"]):
            raise ValueError("current unissued quantitative design required")
        binding=e["quantitative_binding"]["binding"]
        if (graph_root is None) == (rundir is None):raise ValueError("one actual charged tool or ordinary operation origin required")
        if graph_root is not None:
            if str(_ordinary(graph_root)) not in {row["root"] for row in state["graphs"]}:
                raise ValueError("predictive tool must be charged to this original campaign")
            origin=_graph_result(graph_root,node_id)
            if origin["node_kind"]!="tool" or origin["value"].get("action")!="quantitative-predictive":
                raise ValueError("actual quantitative tool result required")
            value=origin["value"]["value"]
            retained={"kind":"charged_host","origin":origin}
        else:
            rd=_ordinary(rundir);science.verify_plan(rd,approved=True)
            packet=science.packet(rd)
            if packet["execution"]["status"]!="completed" or packet["errors"]:
                raise ValueError("actual successful pure quantitative operation required")
            spec=science.execution_spec(rd)
            if spec["mode"]!="quantitative-predictive" or spec["task"]["binding"]!=binding or spec.get("goal_binding")!=state["contract"].get("goal_binding"):
                raise ValueError("ordinary predictive origin differs from target source and whole goal")
            # The existing experiment ledger must already charge this checking
            # operation; a free external run cannot silently enter the campaign.
            owner=next((row for row in state["experiments"] if row.get("rundir")==str(rd)),None)
            if owner is None or owner["observation"] is None:raise ValueError("ordinary predictive operation must be charged and observed in this cycle")
            _current_evidence(state,owner)
            pin=_pin(rd/"outputs/attempt-1/result.json");value=_read(pin,rd)
            retained={"kind":"ordinary_study","experiment_id":owner["id"],"result":pin}
        predictive.verify_value(binding,value,base_dir=state["base_dir"],observation_pin=None)
        if value["delivery_status"]!="complete" or value["selection_evidence"] is None:
            raise ValueError("full quantitative separation remains unresolved")
        e["quantitative_selection"]=deepcopy(value["selection_evidence"])
        e["quantitative_selection_origin"]=retained
        return _commit(Path(root),state,"actual_quantitative_selection_bound",experiment_id=identity,origin=retained)


def _quantitative_selection_current(state,e):
    from . import quantitative_predictive_checks as predictive
    origin=e.get("quantitative_selection_origin")
    if origin is None:return None
    if not _fresh(state,e["premise_bindings"]):raise ValueError("quantitative selection premises changed")
    if origin["kind"]=="charged_host":
        actual=_graph_result(origin["origin"]["root"],origin["origin"]["node_id"])
        if actual!=origin["origin"]:raise ValueError("quantitative Host source or result changed")
        value=actual["value"]["value"]
    else:
        owner=next(row for row in state["experiments"] if row["id"]==origin["experiment_id"])
        _current_evidence(state,owner);value=_read(origin["result"],state["base_dir"])
    predictive.verify_value(e["quantitative_binding"]["binding"],value,base_dir=state["base_dir"],observation_pin=None)
    if ce.digest(value["selection_evidence"])!=ce.digest(e["quantitative_selection"]):raise ValueError("quantitative selection differs from actual evidence")
    return deepcopy(e["quantitative_selection"])

def prepare_experiment(root, identity, rundir):
    """Materialize ordinary CHECK-IN 1; never approve on a selection's behalf."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(x for x in state["experiments"] if x["id"] == identity)
        if _failed_parent(e):
            raise ValueError("retained failure cannot be launched or retried as the old experiment")
        if not next(x for x in select(root)["designs"] if x["id"] == identity)["affordable"]:
            raise ValueError("experiment not currently admissible for preparation")
        if "tool_context" in e:
            from .research_tools import check_binding
            check_binding(e["tool_context"], state["base_dir"], state=state)
        for pin in [e["study"], *e["input_pins"]]:
            path = Path(pin["path"]); path = path if path.is_absolute() else Path(state["base_dir"]) / path
            if _pin(path)["sha256"] != pin["sha256"]: raise ValueError("prospective study dependency changed")
        reservation = _experiment_reservation(state,e,root)
        # Use the same alias-refusing canonical ordinary identity that the
        # actual science plan and worker use, before any materialization.
        rd = _ordinary(rundir).resolve()
        _charge(state, "experiment:" + identity, e["cost"] if reservation is None else reservation["incremental_cost"], e["study"])
        path = Path(e["study"]["path"]); path = path if path.is_absolute() else Path(state["base_dir"]) / path
        from . import research_protocol
        bound = research_protocol._bound(state)
        needs_binding = state.get('methodology') or e.get('evaluation') or (
            bound and any(cell['exposure'] == 'withheld_confirmation' for cell in bound[0]['cells']))
        options = {'research_binding': {'root': str(Path(root).resolve()), 'experiment_id': identity}} if needs_binding else {}
        science.plan(rd, path, **options)
        rd = science.root(rd)
        from . import gate_wiring
        gate_wiring.bind_steering_child(root, rd, identity)
        e["rundir"] = str(rd); e["plan"] = _pin(rd / science.PLAN)
        return _commit(Path(root), state, "ordinary_study_planned", experiment_id=identity, plan=e["plan"],
                       partition_master=None if reservation is None else reservation["master"], declared_cost=deepcopy(e["cost"]))


def _experiment_dispatch_admission(state, identity):
    """Existing current-parent, phase, premise, source and plan checks."""
    e = next(x for x in state["experiments"] if x["id"] == identity)
    if _failed_parent(e):
        raise ValueError("retained failure cannot be launched or retried as the old experiment")
    from . import research_protocol
    if research_protocol.eligibility(state, identity):
        raise ValueError("current staged scientific protocol prerequisites incomplete")
    active_hypotheses = {h["id"] for h in state["hypotheses"] if _fresh(state, h["premise_bindings"])}
    if (e["rundir"] is None or not _fresh(state, e["premise_bindings"])
            or "applicability_reopened" in e or set(e["predictions"]) - active_hypotheses):
        raise ValueError("current prepared experiment and prediction premises required")
    # Planning is not enduring admission: re-observe every retained ancestor
    # at the last ordinary dispatch boundary. A changed failed diagnostic,
    # reopened ancestor or superseded accepted scope blocks the challenger.
    parent_id = e["parent"]
    while parent_id is not None:
        parent = next(x for x in state["experiments"] if x["id"] == parent_id)
        if (not _fresh(state, parent["premise_bindings"]) or "applicability_reopened" in parent
                or set(parent["predictions"]) - active_hypotheses):
            raise ValueError("research ancestor or predicted premises reopened")
        if parent["observation"] is None or (parent["adjudication"] is None and parent.get("diagnostic_feedback") is None):
            raise ValueError("current reviewed research ancestor required")
        accepted = parent["adjudication"] is not None and parent["adjudication"]["view"]["state"] == "accepted"
        _current_evidence(state, parent, accepted=accepted)
        parent_id = parent["parent"]
    phase = _phase_allocation(state)
    if phase is not None:
        pending = set(state["phase_policy"]["preconstruction_checks"][identity]) - set(phase["ordinary_current_completed_check_ids"])
        if pending or any(phase["actual_usage_overrun"].values()) or any(phase["check_reservation_deficits"].values()):
            raise ValueError("current required checking reservation or preconstruction evidence incomplete")
    if "tool_context" in e:
        from .research_tools import check_binding
        check_binding(e["tool_context"], state["base_dir"], state=state)
    for pin in [e["study"], *e["input_pins"], e["plan"]]: _check_pin(pin, state["base_dir"])
    science.verify_plan(e["rundir"], approved=True)
    return e


def run_experiment(root, identity, *, resume=False):
    """Invoke the ordinary runner; partition workers serialize their own claim."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        from . import gate_wiring
        allowed, reason = gate_wiring.dispatch_permitted(root, identity)
        if not allowed:
            raise ValueError(reason)
        e = _experiment_dispatch_admission(state, identity)
        reservation = _experiment_reservation(state,e,root)
        refusal = _clock(state, e["cost"]["wall_seconds"])
        if refusal is not None:
            state["operational_boundaries"].append({"operation": identity, **refusal})
            _commit(Path(root), state, "operational_boundary_retained", operation=identity)
            raise OperationalBoundaryError("original campaign cannot fit the approved study branch")
        from .research_protocol import record_confirmation_dispatch
        state = record_confirmation_dispatch(root, state, identity)
        _commit(Path(root), state, "ordinary_study_dispatch_boundary", experiment_id=identity,
                partition_master=None if reservation is None else reservation["master"],
                plan=deepcopy(e["plan"]),study=deepcopy(e["study"]))
        if reservation is None:
            return science.run(e["rundir"], resume=resume)
        # Parent does not wait holding the lock needed by its real worker.
        # Exact ordinary run/execution locks and original master claim journal
        # still own concurrency, failure/unknown spend and all current checks.
        rundir=e["rundir"]
    return science.run(rundir, resume=resume)



def _pointer(document, pointer):
    for raw in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw): raise ValueError("literal JSON pointer escape required")
        token = raw.replace("~1", "/").replace("~0", "~")
        if type(document) is list:
            if not re.fullmatch(r"0|[1-9][0-9]*", token): raise ValueError("literal ASCII array index required")
            document = document[int(token)]
        elif type(document) is dict: document = document[token]
        else: raise KeyError("observed pointer crosses scalar")
    return document


def observe(root, identity):
    """Intake actual ordinary outcomes before adjudication, including failure."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(x for x in state["experiments"] if x["id"] == identity)
        if _failed_parent(e):
            raise ValueError("canonical failed-stage intake already retains the failed observation")
        if e["rundir"] is None or e["observation"] is not None: raise ValueError("unobserved ordinary study required")
        if _quantitative(e):
            if not _fresh(state, e["premise_bindings"]): raise ValueError("quantitative observation requires current premises")
            for p in e["input_pins"]: _check_pin(p, state["base_dir"])
            _exposure_manifest(e, e["input_pins"], state["base_dir"])
        rd = Path(e["rundir"])
        science.verify_plan(rd, approved=True)
        packet = science.packet(rd)
        if packet["execution"]["status"] in {"running", "approved", "planned"}: raise ValueError("study terminal evidence required")
        if packet["execution"]["status"] == "invalid": raise ValueError("source or authority refusal is not a scientific result")
        execution = science.execution.load_execution(rd)["stages"]["science"]
        receipt = _pin(rd / execution["attempt_record"])
        result_path = rd / "outputs/attempt-1/result.json"
        pin = _pin(result_path) if result_path.is_file() else None
        measured = None; outcome = None; measurement_present = False
        successful = ExecutionStatus.normalize(execution["status"]) == ExecutionStatus.SUCCESS and not packet["errors"]
        if successful and pin is not None and not _quantitative(e):
            try:
                measured = _pointer(_read(pin, rd), e["observable"]["pointer"])
                measurement_present = True
            except (KeyError, IndexError): pass
            matches = [key for key, value in e["observable"]["outcomes"].items()
                       if measurement_present and ce.digest(value) == ce.digest(measured)]
            outcome = matches[0] if len(matches) == 1 else None
        observation = {"receipt": receipt, "attempt_id": execution["attempt_id"], "result": pin,
            "execution_status": execution["status"], "packet": packet, "measured": measured, "measurement_present": measurement_present, "outcome": outcome,
            "prediction_comparison": {h: "unknown" if expected is None or outcome is None else "matches" if expected == outcome else "differs"
                                      for h, expected in e["predictions"].items()},
            "result_category": "defined_measurement" if successful and outcome is not None else
                "unresolved_measurement" if successful else "execution_or_adapter_failure_unresolved",
            "scientific_acceptance": False}
        if _quantitative(e):
            from .quantitative_predictive_checks import verify_evidence
            quantitative_path = rd / "outputs/attempt-1/quantitative-check.json"
            evidence = None; check_pin = None
            if successful and pin is not None and quantitative_path.is_file():
                check_pin = _pin(quantitative_path)
                evidence = verify_evidence(e["quantitative_binding"]["binding"], check_pin, pin, base_dir=state["base_dir"])
            observation.update(quantitative_check=check_pin, quantitative_evidence=evidence,
                result_category="quantitative_diagnostic_delivery" if successful and evidence is not None and evidence["delivery_status"] == "complete" else
                    "quantitative_check_unresolved" if successful else "execution_or_adapter_failure_unresolved")
        e["observation"] = observation
        _register_observation(state, e)
        from .research_evaluation import record_observation
        record_observation(state, e)
        if successful and pin is not None and _fresh(state, e["premise_bindings"]) and (not _quantitative(e) or observation["result_category"] == "quantitative_diagnostic_delivery"):
            outputs = {key: {"path": pin["path"], "sha256": pin["sha256"]} for key in e["context_outputs"]}
            state["context"] = scientific_context.apply_step(state["context"], {"id": identity, "outputs": outputs,
                "code_status": "success", "actor_complete": False, "question": e["question"],
                "next_experiment": {"hypothesis": "Compare the retained competing predictions to this actual measurement.",
                    "change": e["change"], "measurement": "Review the complete supplied quantity census and outcome.",
                    "if_supported": "Accumulate only the scoped accepted evidence.", "if_not_supported": "Retain the negative result and redesign a discriminating experiment."}}, state["base_dir"])
        return _commit(Path(root), state, "actual_study_observed", experiment_id=identity, observation=observation)


def adjudicate(root, identity):
    """Consume real separate role decisions; this controller casts no votes."""
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        e = next(x for x in state["experiments"] if x["id"] == identity)
        if _failed_parent(e):
            raise ValueError("failed-stage diagnosis must remain outside ordinary scientific acceptance")
        if e["observation"] is None: raise ValueError("actual study observation required before review intake")
        rd = Path(e["rundir"])
        if not physics_review.active(rd): raise ValueError("ordinary actual review cycle required")
        view = physics_review.status(rd)
        if view["state"] not in {"accepted", "send_back", "stopped"}: raise ValueError("actual terminal role decision required")
        if view["state"] == "accepted" and (view["live_errors"] or view["claim_scope"] != e["acceptance_scope"]):
            raise ValueError("accepted scope or current evidence differs")
        action = "reuse" if view["state"] == "accepted" else "delivery"
        if view["state"] == "accepted":
            snapshot = physics_review.snapshot(rd, action=action)
        else:
            # The public admission snapshot rightly refuses a send-back. Retain
            # its genuine existing journal as non-authorizing detached history.
            registration, events = physics_review._read(rd)
            snapshot = {"schema_version": 1, "registration": registration, "events": events,
                        "checkpoint": state_io.read_json(rd / physics_review.HEAD), "action": action, "stage": None}
        errors = physics_review.validate_snapshot(snapshot, require_admission=view["state"] == "accepted")
        if errors: raise ValueError("ordinary detached review snapshot differs: " + "; ".join(errors))
        path = Path(root) / "review-snapshots" / (ce.digest(snapshot) + ".json")
        if not path.exists(): state_io.atomic_json(path, snapshot)
        e["adjudication"] = {"view": view, "snapshot": _pin(path), "scope": view.get("claim_scope"),
            "current_applicability": _fresh(state, e["premise_bindings"]), "historical_decision_preserved": True}
        return _commit(Path(root), state, "actual_roles_adjudicated", experiment_id=identity, decision_state=view["state"])


def feedback_packet(root, identity):
    """Expose actual results and constructive reviews for a bounded next turn.

    Unknown, negative and adapter failures remain different from hypothesis
    falsification. This packet contains no invented successful measurement.
    The caller decides what genuinely withheld evaluation inputs stay private.
    """
    from . import research_protocol
    _, state = _load(root)
    e = next(e for e in state["experiments"] if e["id"] == identity)
    _current_evidence(state, e, accepted=e["adjudication"] is not None and e["adjudication"]["view"]["state"] == "accepted")
    diagnostic = e.get("diagnostic_feedback")
    if e["adjudication"] is None and diagnostic is None:
        raise ValueError("actual separate role outcome required before constructive revision")
    value = {"kind": "research_experiment_feedback", "question": state["contract"]["question"],
        "scope": state["contract"]["scope"], "experiment_id": identity,
        "parent_task": deepcopy(state.get("parent_task")), "parent_task_accepted": False,
        "complete_requested_quantities": state["context"]["requested_quantities"],
        "premise_bindings": e["premise_bindings"], "predictions": e["predictions"],
        "current_applicability": _applicability(state, e),
        "historical_prediction_comparisons_are_not_current_when_premise_changed": True,
        "observation": deepcopy(e["observation"]), "adjudication": deepcopy(e["adjudication"]),
        "staged_protocol": research_protocol.status_state(state),
        "hypothesis_register": replay_register(state["events"], base_dir=state["base_dir"]),
        "failed_stage_intake": e.get("failed_intake"), "diagnostic_feedback": diagnostic,
        "failed_parent_acceptance_remains_false": _failed_parent(e),
        "unknown_or_delivery_failure_is_not_hypothesis_contradiction": True,
        "next_turn": "Propose an improved candidate, competing explanation or discriminating experiment; retain the whole task.",
        "execution_authorized": False, "physics_validated": False}
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during feedback construction")
    path = Path(root) / "constructive-feedback" / (ce.digest(value) + ".json")
    if not path.exists(): state_io.atomic_json(path, value)
    return _pin(path)


def bound_revision(proposal, feedback, *, proposal_base, feedback_pin, presented_pins):
    """Materialize an explicitly supplied proposal through the ordinary Host.

    This is structured source admission, not hypothesis invention. A real model
    may instead return the identical contract through the existing model adapter.
    """
    ce.keys(proposal, ("kind", "parent_experiment", "feedback_sha256", "reason", "hypotheses", "experiment"))
    if proposal["kind"] != "research_revision" or feedback["kind"] != "research_experiment_feedback":
        raise ValueError("typed constructive research proposal and actual feedback required")
    if proposal["parent_experiment"] != feedback["experiment_id"] or proposal["feedback_sha256"] != feedback_pin["sha256"]:
        raise ValueError("proposal feedback subject differs")
    _text(proposal["reason"])
    e = proposal["experiment"]
    if e["parent"] != feedback["experiment_id"]: raise ValueError("actual parent retained")
    spec = _read(e["study"], proposal_base)
    science.validate(spec)
    base = Path(e["study"]["path"]).parent
    base = base if base.is_absolute() else Path(proposal_base) / base
    hashes = {pin["sha256"] for pin in presented_pins}
    if e["study"]["sha256"] not in hashes or feedback_pin["sha256"] not in hashes:
        raise ValueError("revised study and feedback must be normal Host inputs")
    _model_input_admission(e, [_pin(path) for path in science.task_inputs(spec, base)], presented_pins, proposal_base)
    return deepcopy(proposal)


def adopt_revision(root, *, graph_root, node_id):
    """Adopt the actual improver's structured next hypothesis and study together.

    The graph performs the bounded call. Successful incumbents are retained,
    send-backs/failures are not relabeled successes, and no review vote carries.
    Trusted-command controls remain controls, not actual LLM efficacy.
    """
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        if str(_ordinary(graph_root)) not in {g["root"] for g in state["graphs"]}:
            raise ValueError("revision must use this cycle's cumulatively charged ordinary graph")
        origin = _graph_result(graph_root, node_id)
        if origin["role"] != "improver" or origin["value"].get("kind") not in {"model_result", "ravel_tool_result"}:
            raise ValueError("actual structured improver graph response required")
        value = origin["value"]["value"]
        ce.keys(value, ("kind", "parent_experiment", "feedback_sha256", "reason", "hypotheses", "experiment"))
        if value["kind"] != "research_revision": raise ValueError("research_revision structured contract required")
        _text(value["reason"])
        parent = next(e for e in state["experiments"] if e["id"] == value["parent_experiment"])
        feedback = feedback_packet(root, parent["id"])
        presented = {pin["sha256"] for pin in origin["inputs"]}
        if feedback["sha256"] != value["feedback_sha256"] or feedback["sha256"] not in presented:
            raise ValueError("revision must consume the exact actual outcome and role feedback")
        study = value["experiment"]["study"]
        if study["sha256"] not in presented: raise ValueError("actual revised prospective study must be a normal graph input")
        if value["experiment"]["parent"] != parent["id"]:
            raise ValueError("revised design must retain the actual experiment parent")
        if type(value["hypotheses"]) is not list: raise ValueError("explicit revised hypothesis census required")
        if value["hypotheses"]: _append_hypotheses(state, value["hypotheses"], origin)
        _append_design(state, value["experiment"])
        new = state["experiments"][-1]
        _model_input_admission(new, new["input_pins"], origin["inputs"], state["base_dir"])
        new["constructive_origin"] = origin
        state["revisions"].append({"parent": parent["id"], "candidate": new["id"], "feedback": feedback,
            "origin": origin, "reason": value["reason"], "incumbent_and_negative_results_retained": True,
            "old_votes_carried": []})
        return _commit(Path(root), state, "actual_constructive_revision_adopted", experiment_id=new["id"])


def adopt_source_revision(root, proposal_pin, *, description):
    """Admit an explicitly source-supplied successor without fabricating a model.

    This entry lets a reviewed domain implementation become the next ordinary
    experiment. It preserves the distinction from execute_graph/adopt_revision,
    which consume actual bounded improver transport. Full worker dependencies
    remain bound; a source proposal supplies no execution or acceptance right.
    """
    _text(description)
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        proposal = _read(proposal_pin, state["base_dir"])
        parent = next(e for e in state["experiments"] if e["id"] == proposal["parent_experiment"])
        feedback = feedback_packet(root, parent["id"])
        e = proposal["experiment"]
        spec = _read(e["study"], state["base_dir"])
        path, _ = _check_pin(e["study"], state["base_dir"])
        dependencies = [_pin(p) for p in science.task_inputs(spec, path.parent)]
        dependencies = _tool_input_closure(e, dependencies, state["base_dir"], state=state)
        presented = [proposal_pin, feedback, e["study"], *dependencies]
        if "input_exposure" in e:
            # The pure source admission still honors any declared proposer
            # isolation: only disclosed bytes enter that admission context.
            manifest = _exposure_manifest(e, dependencies, state["base_dir"])
            presented = [proposal_pin, feedback, e["study"], e["input_exposure"],
                         *[{k: row[k] for k in ("path", "sha256", "size")}
                           for row in manifest["inputs"] if row["purpose"] == "model_context"]]
        bound_revision(proposal, _read(feedback, state["base_dir"]), proposal_base=state["base_dir"],
                       feedback_pin=feedback, presented_pins=presented)
        origin = {"kind": "source_supplied_constructive_revision", "pin": deepcopy(proposal_pin),
                  "description": description, "actual_model_calls": 0, "model_transport_observed": False}
        if proposal["hypotheses"]: _append_hypotheses(state, proposal["hypotheses"], origin)
        _append_design(state, e)
        state["experiments"][-1]["constructive_origin"] = origin
        state["revisions"].append({"parent": parent["id"], "candidate": e["id"], "feedback": feedback,
            "origin": origin, "reason": proposal["reason"], "incumbent_and_negative_results_retained": True,
            "old_votes_carried": []})
        return _commit(Path(root), state, "source_supplied_constructive_revision_adopted", experiment_id=e["id"])


def reuse_adaptation(root, request_pin, *, entry_id, bindings):
    """Use the executable adaptation library, retaining scoped requalification."""
    from . import adaptation_reuse
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        request = _read(request_pin, state["base_dir"])
        retrieval = adaptation_reuse.retrieve(request, base_dir=state["base_dir"])
        proposal = adaptation_reuse.prepare(retrieval, entry_id, bindings, base_dir=state["base_dir"])
        record = {"request": request_pin, "dependencies": adaptation_reuse.input_pins(request, base_dir=state["base_dir"]),
            "retrieval": retrieval, "proposal": proposal,
            "relation_to_question": state["contract"]["question"], "fresh_whole_target_study_required": True}
        path = Path(root) / "adaptation-proposals" / (ce.digest(record) + ".json")
        if not path.exists(): state_io.atomic_json(path, record)
        state["adaptations"].append(_pin(path))
        return _commit(Path(root), state, "scoped_executable_adaptation_proposed", proposal=_pin(path))


def revise_premise(root, identity, statement, *, basis, reason, coordinator_origin=None):
    """Backtrack applicability, retaining all old measurements and decisions."""
    _text(statement); _text(reason)
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        payload = {}
        if coordinator_origin is not None:
            from .agent_host import _loads
            actual = _graph_result(coordinator_origin['root'], coordinator_origin['node_id'])
            args = {'identity':identity,'statement':statement,'basis':basis,'reason':reason}
            public = actual['value'].get('value',{})
            if (actual != coordinator_origin or public.get('kind') != 'research-action'
                    or public.get('action') != 'revise-premise'
                    or _loads(public['arguments_json']) != args):
                raise ValueError('premise revision differs from its actual original decision')
            spec,_ = agent_graph._load(_ordinary(actual['root']))
            validate_graph_reservation(state,actual['root'],spec)
            presented = {(p['path'],p['sha256']) for p in actual['inputs']}
            if any((p['path'],p['sha256']) not in presented for p in basis):
                raise ValueError('premise revision source was not presented')
            prior = [event for event in state['events'] if event['kind']=='premise_revised'
                and event.get('coordinator_decision_sha256') == ce.digest(actual)]
            if prior:
                if len(prior)!=1:raise ValueError('one premise effect per actual decision required')
                event=prior[0]
                if event.get('coordinator_origin')!=actual or event.get('coordinator_arguments')!=args:
                    raise ValueError('retained premise effect differs from actual decision')
                before=state_io.read_json(Path(root)/'history'/f"{event['revision']-1:04d}.json")
                result=state_io.read_json(Path(root)/'history'/f"{event['revision']:04d}.json")
                expected=_seal({'id':identity,'statement':statement,'basis':deepcopy(basis)})
                if (event['before_state_sha256']!=before['sha256'] or result['parent_sha256']!=before['sha256']
                        or result['events'][-1]!=event or event['after']!=expected
                        or next(p for p in before['premises'] if p['id']==identity)!=event['before']
                        or next(p for p in state['premises'] if p['id']==identity)!=expected):
                    raise ValueError('known premise revision cannot be reconstructed from original history')
                for pin in basis:_check_pin(pin,state['base_dir'])
                return result
            payload = {'coordinator_origin':deepcopy(actual),'coordinator_arguments':deepcopy(args),
                'coordinator_decision_sha256':ce.digest(actual),'before_state_sha256':state['sha256']}
        old = next(row for row in state["premises"] if row["id"] == identity)
        if type(basis) is not list or len(basis) > 16: raise ValueError("bounded premise revision basis required")
        for pin in basis: _check_pin(pin, state["base_dir"])
        new = _seal({"id": identity, "statement": statement, "basis": deepcopy(basis)})
        if new["sha256"] == old["sha256"]: raise ValueError("premise revision must change the retained premise")
        state["premises"] = [new if row["id"] == identity else row for row in state["premises"]]
        invalid = _reopen_premise_descendants(state, identity, reason)
        return _commit(Path(root), state, "premise_revised", before=old, after=new, reason=reason,
                       descendants_reopened=sorted(invalid), **payload)


def status(root):
    """Productive next obligations, complete denominator and retained negatives."""
    _, state = _load(root)
    rows = []
    for e in state["experiments"]:
        applicability = _applicability(state, e)
        applicable = applicability["measurement"]
        accepted = e["adjudication"] is not None and e["adjudication"]["view"]["state"] == "accepted"
        current_reuse = False; refusal = None
        if applicable and accepted:
            try:
                _current_evidence(state, e, accepted=True)
                current_reuse = True
            except (ValueError, OSError) as exc:
                refusal = {"kind": "current_source_authority_or_custody_refusal", "error_type": type(exc).__name__, "message": str(exc)}
        rows.append({"id": e["id"], "current_applicability": applicable,
            "prediction_interpretations_current": applicability["prediction_interpretations"], "historically_accepted": accepted,
            "current_scoped_reuse_clear": current_reuse, "current_refusal": refusal,
            "quantitative_delivery": None if e["observation"] is None else deepcopy(e["observation"].get("quantitative_evidence")),
            "outcome": None if e["observation"] is None else e["observation"]["outcome"],
            "next": "redesign_after_premise_change" if not applicable else "prepare_prospective_study" if e["rundir"] is None else
                "run_only_after_actual_approval" if e["observation"] is None else
                "obtain_failed_stage_diagnostic_roles" if _failed_parent(e) and e["diagnostic_feedback"] is None else
                "construct_discriminating_successor_without_accepting_failed_parent" if _failed_parent(e) else
                "obtain_actual_roles" if e["adjudication"] is None else
                "construct_improvement_or_discriminating_experiment" if not accepted or (e["observation"]["outcome"] is None and
                    (e["observation"].get("quantitative_evidence") is None or e["observation"]["quantitative_evidence"]["delivery_status"]!="complete")) else "accumulate_scoped_evidence"})
    complete_ids = {e["id"] for e, row in zip(state["experiments"], rows) if row["current_scoped_reuse_clear"]
        and (row["outcome"] is not None or row["quantitative_delivery"] is not None and row["quantitative_delivery"]["delivery_status"] == "complete") and all(row["prediction_interpretations_current"].values())}
    missing = sorted(set(state["contract"]["required_experiments"]) - complete_ids)
    current_sources = {row["source_step"] for row in state["context"]["effective_outputs"]}
    reviewed_sources = {row["id"] for row in rows if row["current_scoped_reuse_clear"]}
    missing_output_reviews = sorted(current_sources - reviewed_sources)
    from . import research_protocol
    protocol = research_protocol.status_state(state)
    methodology = (research_protocol.methodology_status(root)
                   if state['contract'].get('research_protocol_required') else None)
    from . import research_outcome_metrics
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during status construction")
    return {"state_sha256": state["sha256"], "revision": state["revision"], "question": state["contract"]["question"],
            "experiments": rows, "missing_required_experiments": missing, "quantity_completion": state["context"]["quantity_completion"],
            "missing_current_output_reviews": missing_output_reviews,
            "connected_task_complete": bool(state["experiments"]) and not missing and not missing_output_reviews and state["context"]["quantity_completion"] and (protocol is None or protocol["complete_scientific_evidence"]) and (methodology is None or methodology['complete']),
            "research_methodology": methodology,
            "hypothesis_register": replay_register(state["events"], base_dir=state["base_dir"]),
            "staged_protocol": protocol,
            "outcome_metrics": research_outcome_metrics.project(root, state),
            "timing": state["timing"], "operational_boundaries": state["operational_boundaries"],
            "parent_task": deepcopy(state.get("parent_task")), "parent_task_accepted": False,
            "completion_scope": "contracted_research_component; original parent acceptance is separate",
            "execution_authorized": False, "physics_validated": False, "benefit_measured": False}


def outcome_metrics(root, *, completion_request=None, utility_declaration=None):
    """Read instrumentation; no operation, review, truth label or reward is issued."""
    from .research_outcome_metrics import readout
    return readout(root, completion_request=completion_request, utility_declaration=utility_declaration)


def continue_campaign(root, new_root, contract, *, reason):
    """Declare a new phase while preserving an exhausted original campaign.

    This does not extend the original deadline or grant a call/study approval.
    Calls, tokens and attempts retain the original cumulative ceiling/debits.
    A new explicit wall bound starts only at a future ordinary dispatch.
    """
    _text(reason)
    _, parent = _load(root)
    if parent["timing"]["deadline_epoch"] is None or time.time() <= parent["timing"]["deadline_epoch"]:
        raise ValueError("explicit expired original campaign required for continuation")
    for key in ("calls", "output_tokens", "native_attempts"):
        if contract["budget"][key] != parent["contract"]["budget"][key]:
            raise ValueError("continuation must preserve the same cumulative nonwall ceiling")
    if not 1 <= contract["budget"]["wall_seconds"] <= 3600:
        raise ValueError("new prospectively bounded phase wall required")
    if any(contract[key] != parent["contract"][key] for key in ("question", "scope", "context_request")):
        raise ValueError("same complete question/context required; changed premises need a declared revision")
    if contract.get("goal_binding") != parent["contract"].get("goal_binding"):
        raise ValueError("continuation cannot drop or replace the original parent assignment")
    if parent['contract'].get('research_protocol_required') and not contract.get('research_protocol_required'):
        raise ValueError('continuation cannot drop its research protocol')
    state = create(new_root, contract, base_dir=parent["base_dir"])
    history_pins = [_pin(Path(root) / "history" / f"{i:04d}.json") for i in range(parent["revision"] + 1)]
    usage = _usage(parent)
    state["resource_ledger"].append({"id": "original-campaign:" + parent["sha256"],
        "ceiling": {**usage, "wall_seconds": 0},
        "basis": {"head": _pin(Path(root) / "history" / f"{parent['revision']:04d}.json"), "history": history_pins,
            "original_declared_wall_reservations": usage["wall_seconds"], "original_timing": parent["timing"],
            "original_elapsed_seconds": time.time() - parent["timing"]["started_epoch"],
            "new_phase_wall_compliance_is_not_original_campaign_compliance": True}})
    state["hypotheses"] = deepcopy(parent["hypotheses"])
    return _commit(Path(new_root), state, "separate_continuation_declared", original_root=str(Path(root).absolute()), reason=reason)


def synthesize(root, report_request, *, base_dir):
    """Construct a reproducible report through the actual quantity-bound writer."""
    from . import scientific_report
    _, state = _load(root)
    view = status(root)
    if not view["connected_task_complete"]: raise ValueError("complete current task quantities and required actual role decisions needed")
    context_path = Path(root) / "synthesis-context" / (state["context"]["context_sha256"] + ".json")
    if not context_path.exists(): state_io.atomic_json(context_path, state["context"])
    supplied, _ = _check_pin(report_request["context"], base_dir)
    if _pin(supplied) != _pin(context_path): raise ValueError("report must consume the exact current complete scientific context")
    if state.get("parent_task") is not None and "task_completion" not in report_request:
        # A component report is useful before whole-parent closure. Reuse the
        # existing completion view to expose every original obligation as open,
        # without inventing coverage or requiring another approval.
        progress = {"schema_version": 1, "contract": state["parent_task"]["contract"],
                    "outcomes": [], "parent_review": None, "report": None}
        progress_path = Path(root) / "synthesis-context" / (ce.digest(progress) + "-parent-progress.json")
        if not progress_path.exists(): state_io.atomic_json(progress_path, progress)
        progress_pin = _pin(progress_path)
        if _read(progress_pin, base_dir) != progress:
            raise ValueError("retained parent progress projection differs")
        report_request = {**deepcopy(report_request), "task_completion": progress_pin, "delivery": "progress"}
    if "task_completion" in report_request:
        if state.get("parent_task") is None:
            raise ValueError("parent final synthesis requires an original bound research parent")
        completion_request = _read(report_request["task_completion"], base_dir)
        if completion_request.get("contract") != state["parent_task"]["contract"]:
            raise ValueError("research report completion must name its exact original parent contract")
    report = scientific_report.compose(report_request, base_dir=base_dir)
    if not report["requested_quantity_completion"] or any(not row["exposed_fact_ids"] for row in report["requested_quantity_census"]):
        raise ValueError("report must expose every requested quantity without silent omission")
    if state.get("parent_task") is not None and report.get("task_completion") is not None:
        expected = state["parent_task"]["contract"]
        if not any(p == expected for p in report["task_completion"]["input_pins"]):
            raise ValueError("research final report must bind its exact original parent contract")
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during synthesis")
    from . import research_outcome_metrics
    metrics = research_outcome_metrics.project(root, state, completion=report.get("task_completion"))
    report["outcome_metrics"] = metrics
    report["report_text"] += "\n" + research_outcome_metrics.markdown(metrics)
    if len(report["report_text"].encode()) > scientific_report.MAX_TEXT_BYTES:
        raise ValueError("complete research report including instrumentation exceeds existing text budget")
    evidence = [{"id": e["id"], "premise_bindings": e["premise_bindings"], "change": e["change"],
        "predictions": e["predictions"], "observation": e["observation"], "adjudication": e["adjudication"],
        "failed_stage_intake": e.get("failed_intake"), "diagnostic_feedback": e.get("diagnostic_feedback"),
        "current_applicability": _applicability(state, e),
        "historical_comparison_scope": "Retained original prediction comparison; current interpretation requires its premise binding."} for e in state["experiments"]]
    return {"kind": "reproducible_research_synthesis", "research_state_sha256": state["sha256"], "question": view["question"],
        "complete_required_experiment_denominator": state["contract"]["required_experiments"], "hypotheses": state["hypotheses"],
        "all_evidence_including_negative_and_reopened": evidence, "resource_ledger": state["resource_ledger"],
        "actual_graph_usage": state["graphs"], "outcome_metrics": metrics, "report": report, "staged_protocol": view["staged_protocol"],
        "parent_task": deepcopy(state.get("parent_task")),
        "parent_task_accepted": bool(state.get("parent_task") is not None and
            (report.get("task_completion") or {}).get("parent_task_accepted", False)),
        "execution_authorized": False,
        "timing": state["timing"], "operational_boundaries": state["operational_boundaries"],
        "physics_validated": False, "benefit_measured": False}


def progress_synthesis(root, *, base_dir=None, report_request=None, render_text=True):
    """Complete typed incomplete delivery; optional human text, final gates unchanged."""
    from .research_progress import compose
    return compose(root, base_dir=base_dir, report_request=report_request, render_text=render_text)



def prepare_author_sources(root, request_pin, out, *, base_dir):
    """Normal prerequisite action: full blinded source context before the writer.

    Existing original review actors/ordinary CI2 capture and judge the exact
    generated source context; their calls remain charged through execute_graph.
    The completed source-review binding is then an explicit author request input.
    """
    from . import manuscript_production
    request=_read(request_pin,base_dir);_,state=_load(root)
    report=manuscript_production._load(request,base_dir)
    if state.get('parent_task') is not None:
        parent=_read(state['parent_task']['contract'],root)
        if parent['prompt']!=report['documents']['original_task']:raise ValueError('source review changed original research task')
    result=manuscript_production.prepare_source_review(request,out,base_dir=base_dir)
    if _load(root)[1]['sha256']!=state['sha256']:raise ValueError('research state changed during author-source preparation')
    return result


def prepare_author(root, request_pin, out, *, base_dir):
    """Normal deliverable action from the current original research task.

    The coordinator selects manuscript-author and assembles source-defined pins
    from the evolving research context. This creates one model Graph only;
    execute_writer calls the unchanged campaign-charged execute_graph outside
    the coordinator lock. No manually authored manuscript is an input.
    """
    from . import manuscript_production
    request = _read(request_pin, base_dir)
    return manuscript_production.prepare_writer(request, out, base_dir=base_dir, campaign=root)


def prepare_manuscript(root, request, *, base_dir):
    """Connect complete manuscript/source audit to this current research context.

    Roles still use the ordinary scientific_judgment path. Their prepared Graphs
    are charged by execute_graph(root, graph, spec, host, prepared=True), including
    the default backend selected by that stable public API. No new scheduler,
    model calls, approval, or second decision journal is introduced here.
    """
    from . import report_integrity, scientific_report
    _, state = _load(root)
    binding = request.get("quantitative_report")
    if binding is None:
        raise ValueError("research manuscript must bind its actual quantity report")
    path, _ = _check_pin(binding["request"], base_dir)
    source = _read(binding["request"], base_dir)
    if source.get("context") is None:
        raise ValueError("research manuscript needs its current scientific quantity context")
    context = scientific_report._context(source["context"], path.parent)
    if context != state["context"]:
        raise ValueError("manuscript cannot borrow an old or different research quantity context")
    result = report_integrity.prepare(request, base_dir=base_dir)
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research context changed during manuscript preparation")
    return {**result, "research_state_sha256":state["sha256"],
        "original_parent":deepcopy(state.get("parent_task")), "parent_task_accepted":False}


def _knowledge_packet(request_pin, base):
    """Consume the shared knowledge kernel, with an ending dependency check."""
    from . import physics_knowledge
    request = _read(request_pin, base)
    dependencies = [request_pin, *physics_knowledge.input_pins(request, Path(base))]
    by_path = {}
    for pin in dependencies:
        path, actual = _check_pin(pin, base)
        if str(path) in by_path and by_path[str(path)] != actual:
            raise ValueError("knowledge dependency identity conflicts")
        by_path[str(path)] = actual
    packet = physics_knowledge.retrieve(request, Path(base))
    if packet["kind"] != "physics-knowledge-context" or packet["claims"] != {
            "physics_verified": False, "execution_authorized": False}:
        raise ValueError("retrieved assertions cannot transfer scientific authority")
    for pin in by_path.values(): _check_pin(pin, base)
    if _read(request_pin, base) != request:
        raise ValueError("knowledge request changed during retrieval")
    return packet, [by_path[key] for key in sorted(by_path)]


def _check_knowledge(state):
    bindings = state.get("knowledge_bindings", [])
    if not bindings: return
    # Retained history is not necessarily current: check every binding still
    # supporting a live premise, including bindings older than the latest query.
    # Superseded historical bindings remain evidence without becoming a veto.
    contexts = [row.get("knowledge_context") for row in state["premises"]]
    for index, binding in enumerate(bindings):
        context = {"request_sha256": binding["packet"]["request_sha256"],
                   "packet_sha256": ce.digest(binding["packet"])}
        supports_current = any({**context, "premise_id": source} in contexts
                               for source in binding["premise_map"])
        if not supports_current and index != len(bindings) - 1:
            continue
        packet, dependencies = _knowledge_packet(binding["request"], state["base_dir"])
        if packet != binding["packet"] or dependencies != binding["dependencies"]:
            raise ValueError("current knowledge binding changed; retain an immutable successor source")


def _reopen_premise_descendants(state, identity, reason):
    invalid = {e["id"] for e in state["experiments"] if not _fresh(state, e["premise_bindings"])}
    changed = True
    while changed:
        before = len(invalid)
        invalid.update(e["id"] for e in state["experiments"] if e["parent"] in invalid)
        changed = len(invalid) != before
    for e in state["experiments"]:
        if e["id"] in invalid: e["applicability_reopened"] = {"premise_id": identity, "reason": reason}
    previous_context = deepcopy(state["context"])
    state["context"] = scientific_context.compile_context(previous_context["request"], state["base_dir"])
    for step in previous_context["steps"]:
        if step["id"] not in invalid:
            state["context"] = scientific_context.apply_step(state["context"], _attempt_from_step(step), state["base_dir"])
    return sorted(invalid)


def bind_knowledge(root, request_pin, *, premise_map, reason):
    """Bind retrieved source assertions to explicit research premises atomically.

    Every selected premise remains represented. Query/domain/context changes
    conservatively reopen applicability; source assertions never become proof.
    An immutable successor source is required, rather than editing an old pin.
    """
    _text(reason)
    with state_io.file_lock(Path(root) / "operation.lock", blocking=False):
        _, state = _load(root)
        packet, dependencies = _knowledge_packet(request_pin, state["base_dir"])
        supplied = {row["id"]: row for row in packet["premises"]}
        if len(supplied) != len(packet["premises"]): raise ValueError("distinct kernel premise IDs required")
        if type(premise_map) is not dict or set(premise_map) != set(supplied):
            raise ValueError("explicit complete selected-premise mapping required")
        if len(set(premise_map.values())) != len(premise_map):
            raise ValueError("distinct research premises cannot collapse retrieved assertions")
        for identity in premise_map.values(): ce.identity(identity)
        existing = {row["id"]: row for row in state["premises"]}
        if len(set(existing) | set(premise_map.values())) > 32:
            raise ValueError("finite research premise bound exceeded")
        context = {"request_sha256": packet["request_sha256"], "packet_sha256": ce.digest(packet)}
        changes = []
        for source_id, target_id in sorted(premise_map.items()):
            row = supplied[source_id]
            ce.keys(row, ("id", "statement", "basis")); _text(row["statement"])
            if type(row["basis"]) is not list or len(row["basis"]) > 16:
                raise ValueError("bounded knowledge premise basis required")
            for pin in row["basis"]: _check_pin(pin, state["base_dir"])
            newer = _seal({"id": target_id, "statement": row["statement"], "basis": deepcopy(row["basis"]),
                           "knowledge_context": {**context, "premise_id": source_id}})
            before = existing.get(target_id)
            if before != newer:
                existing[target_id] = newer
                changes.append({"before": before, "after": newer})
        bindings = state.setdefault("knowledge_bindings", [])
        if len(bindings) >= 32: raise ValueError("finite knowledge-binding revision bound exceeded")
        if not changes and bindings and bindings[-1]["packet"] == packet and bindings[-1]["premise_map"] == premise_map:
            raise ValueError("knowledge binding already retained")
        state["premises"] = [existing[key] for key in sorted(existing)]
        reopened = _reopen_premise_descendants(state, "knowledge-context", reason) if changes else []
        bindings.append({"request": deepcopy(request_pin), "dependencies": dependencies,
            "packet": packet, "premise_map": deepcopy(premise_map), "reason": reason,
            "source_assertions_only": True, "scientific_acceptance": False})
        if len(json.dumps(state, sort_keys=True, allow_nan=False).encode()) > ce.MAX_BYTES - 8192:
            raise ValueError("knowledge binding exceeds readable research-state byte bound")
        for pin in dependencies: _check_pin(pin, state["base_dir"])
        return _commit(Path(root), state, "knowledge_assertions_bound", changes=changes,
                       descendants_reopened=reopened, knowledge_packet_sha256=ce.digest(packet))


def knowledge_next(root, *, obligation_designs):
    """Recommend an existing affordable design against explicit open obligations.

    The mapping is a declared proposed test, not an entailment or completed proof.
    Retained matching/differing predictions inform constructive follow-up without
    deleting hypotheses. Unknowns and adapter failures never falsify a prediction.
    """
    _, state = _load(root)
    if not state.get("knowledge_bindings"): raise ValueError("source-bound knowledge context required")
    binding = state["knowledge_bindings"][-1]
    packet = binding["packet"]
    premises = {row["id"]: row for row in state["premises"]}
    context = {"request_sha256": packet["request_sha256"], "packet_sha256": ce.digest(packet)}
    if any(premises[target].get("knowledge_context") != {**context, "premise_id": source}
           for source, target in binding["premise_map"].items()):
        raise ValueError("retrieved premise context was manually revised; explicit knowledge rebinding required")
    obligations = {row["id"]: row for row in packet["test_obligations"]}
    if len(obligations) != len(packet["test_obligations"]): raise ValueError("distinct test-obligation IDs required")
    if type(obligation_designs) is not dict or set(obligation_designs) != set(obligations):
        raise ValueError("complete obligation-to-design census required, including empty lists")
    experiments = {row["id"]: row for row in state["experiments"]}
    imported = set(binding["premise_map"].values())
    for identities in obligation_designs.values():
        if type(identities) is not list or len(set(identities)) != len(identities) or set(identities) - set(experiments):
            raise ValueError("distinct existing prospective design IDs required")
        for identity in identities:
            if imported - set(experiments[identity]["premise_bindings"]):
                raise ValueError("knowledge-directed designs must explicitly bind the retrieved premise context")
    ordinary = select(root)
    evidence, reopened = [], []
    for e in state["experiments"]:
        applicability = _applicability(state, e)
        if not applicability["measurement"]:
            reopened.append(e["id"]); continue
        if e["observation"] is None: continue
        accepted = e["adjudication"] is not None and e["adjudication"]["view"]["state"] == "accepted"
        _current_evidence(state, e, accepted=accepted)
        observation = e["observation"]
        evidence.append({"experiment_id": e["id"], "outcome": observation["outcome"],
            "result_category": observation["result_category"],
            "prediction_comparison": deepcopy(observation["prediction_comparison"]),
            "current_prediction_applicability": applicability["prediction_interpretations"],
            "scientific_acceptance": accepted,
            "scope": e["acceptance_scope"], "global_hypothesis_refutation": False})
    rows = deepcopy(ordinary["designs"])
    for row in rows:
        tests = [obligations[key] for key in sorted(obligations) if row["id"] in obligation_designs[key]]
        nodes = {identity for obligation in tests for identity in obligation["node_ids"]}
        row["knowledge_obligation_ids"] = [test["id"] for test in tests]
        row["unresolved_contradiction_ids"] = [c["id"] for c in packet["contradictions"]
            if c["source"] in nodes or c["target"] in nodes]
    eligible = [row for row in rows if row["affordable"]]
    if ordinary["exploration_due"] and any(row["exploratory"] for row in eligible):
        eligible = [row for row in eligible if row["exploratory"]]
    chosen = min(eligible, key=lambda row: (-len(row["unresolved_contradiction_ids"]),
        -len(row["knowledge_obligation_ids"]), -row["distinct_prediction_pairs"],
        row["cost"]["native_attempts"], row["cost"]["wall_seconds"], row["id"])) if eligible else None
    # Recheck after ordinary evidence admission; a concurrently changed question,
    # knowledge source or premise may not produce a stale recommendation.
    if _load(root)[1]["sha256"] != state["sha256"]:
        raise ValueError("research state changed during knowledge-directed selection")
    return {"kind": "knowledge_directed_research_selection", "state_sha256": state["sha256"],
        "knowledge_packet_sha256": ce.digest(packet), "selected": None if chosen is None else chosen["id"],
        "source_assertion_domains": [{key: node[key] for key in
            ("id", "kind", "domain", "conventions", "applicability", "query_applicability")} for node in packet["nodes"]],
        "designs": rows, "ordinary_selection": ordinary,
        "open_obligations": deepcopy(packet["test_obligations"]),
        "obligation_designs": deepcopy(obligation_designs),
        "missing_design_obligations": sorted(key for key, value in obligation_designs.items() if not value),
        "contradictions": deepcopy(packet["contradictions"]), "retained_outcomes": evidence,
        "reopened_experiments": reopened,
        "constructive_followup": {"changed_applicability": reopened,
            "prediction_differences": [{"experiment_id": e["experiment_id"], "scope": e["scope"],
                "hypothesis_ids": sorted(key for key, value in e["prediction_comparison"].items()
                    if value == "differs" and e["current_prediction_applicability"][key])}
                for e in evidence if any(value == "differs" and e["current_prediction_applicability"][key]
                    for key, value in e["prediction_comparison"].items())],
            "unknown_predictions": [{"experiment_id": e["experiment_id"],
                "hypothesis_ids": sorted(key for key, value in e["prediction_comparison"].items()
                    if value == "unknown" and e["current_prediction_applicability"][key])}
                for e in evidence if any(value == "unknown" and e["current_prediction_applicability"][key]
                    for key, value in e["prediction_comparison"].items())],
            "next_turn": "Use the existing feedback_packet and bounded constructive revision route to propose a competing explanation or discriminating study; retain negatives, unknowns and source-domain changes."},
        "policy": "ordinary custody, affordability and periodic exploration first; unresolved contradiction coverage, declared obligation coverage, prediction separation, then cost; no posterior, proof or automatic closure",
        "execution_authorized": False, "physics_validated": False, "benefit_measured": False}


def _bounded_source_snapshot(path, maximum):
    """Observe bounded regular bytes and their named path at read boundaries.

    Parent inode/mode checks tolerate unrelated directory entries. The existing
    anchored traversal refuses symlink components when opening both parent fds;
    full leaf identity is compared before/open/after/current-path observations.
    This is not a lock or a promise that the path cannot change between or after
    those observations; a fully restored directory substitution may be unseen.
    """
    import os
    import stat
    if type(maximum) is not int or maximum < 0:
        raise ValueError("nonnegative integer source byte bound required")
    path = _ordinary(path)
    leaf = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    directory_identity = lambda s: (s.st_dev, s.st_ino, s.st_mode)
    ancestors = lambda: [(str(p), directory_identity(p.lstat())) for p in path.parents]
    directory = ending_directory = descriptor = None
    try:
        initial_ancestors = ancestors()
        # A change made within the current step of the stamping clock would keep every field
        # compared below, so the opening observation waits that step out (validation_io.settled).
        from .validation_io import settled
        initial = settled(path.lstat)
        if not stat.S_ISREG(initial.st_mode) or initial.st_size > maximum:
            raise ValueError("existing bounded regular research source required")
        directory = hypothesis_board._directory(path.parent)
        if directory_identity(os.fstat(directory)) != initial_ancestors[0][1]:
            raise ValueError("research source parent changed before bounded consumption")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        stream = os.fdopen(descriptor, "rb")
        descriptor = None  # the stream now owns the leaf descriptor
        with stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum or leaf(initial) != leaf(before):
                raise ValueError("research source changed before bounded consumption")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
            ending = _ordinary(path).lstat()
            ending_directory = hypothesis_board._directory(path.parent)
            if (initial_ancestors != ancestors() or
                    directory_identity(os.fstat(ending_directory)) != initial_ancestors[0][1]):
                raise ValueError("research source ancestor identity changed during bounded consumption")
            current = os.stat(path.name, dir_fd=ending_directory, follow_symlinks=False)
            if (len(raw) > maximum or len(raw) != before.st_size or
                    leaf(before) != leaf(after) or leaf(after) != leaf(ending) or leaf(after) != leaf(current)):
                raise ValueError("research source changed during bounded consumption")
        return path, raw
    except OSError as exc:
        raise ValueError("ordinary bounded research source or path unavailable") from exc
    finally:
        for opened in (descriptor, ending_directory, directory):
            if opened is not None:
                os.close(opened)


def _cli_document(path):
    """Parse the exact descriptor snapshot; no separate pathname content read."""
    from .research_followup import MAX_BYTES
    from .agent_host import HostFailure, _loads
    _, raw = _bounded_source_snapshot(Path(path).expanduser(), MAX_BYTES)
    try:
        return _loads(raw)
    except HostFailure as exc:
        raise ValueError("malformed research command JSON") from exc


def _cli_path(value, base):
    if type(value) is not str or not value.strip():
        raise ValueError("explicit research command path required")
    path = Path(value).expanduser()
    return _ordinary(path if path.is_absolute() else Path(base) / path)


def main(argv=None):
    """Ordinary command entry for the existing connected controller.

    Every command is one existing operation. There is no automatic sequencing,
    new journal, approval, role vote, credential discovery or runtime replay.
    graph/run are actual dispatch commands and retain their original gates.
    """
    import argparse
    from .agent_host import HostFailure
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    documents = {"create", "propose", "design", "graph", "import-board",
        "source-revision", "revise-premise", "configure-phases", "failed-import",
        "failed-attach", "diagnostic-feedback", "bind-knowledge", "knowledge-next",
        "reuse-adaptation", "continue", "synthesize", "blueprint-admission", "adopt-portfolio",
        "discussion-prepare", "discussion-run", "discussion-adopt"}
    operations = ["create", "status", "propose", "import-board", "design", "graph",
        "select", "prepare", "run", "observe", "adjudicate", "feedback", "adopt-revision",
        "source-revision", "revise-premise", "configure-phases", "record-check",
        "failed-import", "failed-attach", "diagnostic-feedback", "bind-knowledge",
        "knowledge-next", "reuse-adaptation", "continue", "synthesize",
        "blueprint-context", "blueprint-admission", "adopt-portfolio",
        "discussion-prepare", "discussion-run", "discussion-adopt", "metrics", "progress"]
    for name in operations:
        sub = commands.add_parser(name)
        sub.add_argument("--cycle", type=Path, required=True)
        if name in documents:
            sub.add_argument("--request", type=Path, required=True,
                help="strict JSON request; exact schema in connected-research-cycle guide")
        if name == "progress":
            sub.add_argument("--request", type=Path, help="optional current accepted quantity report recipe")
        if name in {"create", "graph", "import-board", "continue", "synthesize", "progress"}:
            sub.add_argument("--base-dir", type=Path,
                help="explicit request path base; defaults to the request file's directory")
        if name in {"prepare", "run", "observe", "adjudicate", "feedback", "failed-attach", "diagnostic-feedback"}:
            sub.add_argument("--experiment", required=True)
        if name == "prepare":
            sub.add_argument("--rundir", type=Path, required=True)
        if name == "run":
            sub.add_argument("--resume", action="store_true",
                help="existing ordinary guarded reuse; never a new attempt permission")
        if name == "graph":
            sub.add_argument("--prepared", action="store_true",
                help="charge a pristine pre-created Graph through the reviewed existing-ledger join")
        if name in {"adopt-revision", "blueprint-admission", "adopt-portfolio"}:
            sub.add_argument("--graph", type=Path, required=True)
            sub.add_argument("--node", required=True)
        if name == "blueprint-context":
            sub.add_argument("--out", type=Path, required=True)
            sub.add_argument("--parent", help="explicit reviewed experiment for refinement; omit for a concrete baseline")
        if name == "metrics":
            sub.add_argument("--completion-request", type=Path)
            sub.add_argument("--utility-declaration", type=Path)
            sub.add_argument("--out", type=Path, help="fresh typed JSON/Markdown report directory")
        if name == "record-check":
            sub.add_argument("--check", required=True)
    args = parser.parse_args(argv)
    try:
        request = (_cli_document(args.request) if args.command in documents or
            args.command == "progress" and args.request is not None else None)
        base = (_ordinary(args.base_dir.expanduser()) if getattr(args, "base_dir", None) is not None
            else _ordinary(args.request.expanduser()).parent if (args.command in documents or
                args.command == 'progress' and args.request is not None) else Path.cwd())
        code = 0
        if args.command == "create":
            result = create(args.cycle, request, base_dir=base)
        elif args.command == "status":
            result = status(args.cycle)
        elif args.command == "metrics":
            from . import research_outcome_metrics
            supplied = {}
            for name in ("completion_request", "utility_declaration"):
                path = getattr(args, name)
                if path is not None: supplied[name] = _pin(_ordinary(path.expanduser()))
            result = (research_outcome_metrics.write_report(args.cycle, args.out, **supplied)
                      if args.out is not None else outcome_metrics(args.cycle, **supplied))
        elif args.command == "propose":
            ce.keys(request, ("hypotheses", "origin"))
            result = propose(args.cycle, request["hypotheses"], origin=request["origin"])
        elif args.command == "design":
            result = design(args.cycle, request)
        elif args.command == "import-board":
            ce.keys(request, ("board_root", "streams"))
            result = import_board(args.cycle, _cli_path(request["board_root"], base), streams=request["streams"])
        elif args.command == "graph":
            from .agent_host import AgentHost
            from .research_followup import _json
            ce.keys(request, ("graph_root", "spec", "host_config"))
            graph_spec = _json(request["spec"], base)
            host_config = _json(request["host_config"], base)
            host = AgentHost.from_config(host_config)
            if args.prepared:
                import inspect
                if "prepared" not in inspect.signature(execute_graph).parameters:
                    raise ValueError("prepared Graph ledger join is not available in this source epoch")
                result = execute_graph(args.cycle, _cli_path(request["graph_root"], base), graph_spec, host, prepared=True)
            else:
                result = execute_graph(args.cycle, _cli_path(request["graph_root"], base), graph_spec, host)
            code = 0 if result["complete"] else 1
        elif args.command == "select":
            result = select(args.cycle)
        elif args.command == "prepare":
            result = prepare_experiment(args.cycle, args.experiment, args.rundir)
        elif args.command == "run":
            code = run_experiment(args.cycle, args.experiment, resume=args.resume)
            result = {"experiment_id": args.experiment, "ordinary_scientific_exit_code": code,
                "scientific_acceptance_inferred": False}
        elif args.command == "observe":
            result = observe(args.cycle, args.experiment)
        elif args.command == "adjudicate":
            from . import gate_wiring  # research_choice before adjudication.
            gate_wiring.require_research_choice(args.cycle, args.experiment)
            result = adjudicate(args.cycle, args.experiment)
        elif args.command == "feedback":
            result = feedback_packet(args.cycle, args.experiment)
        elif args.command == "adopt-revision":
            result = adopt_revision(args.cycle, graph_root=args.graph, node_id=args.node)
        elif args.command == "source-revision":
            ce.keys(request, ("proposal_pin", "description"))
            result = adopt_source_revision(args.cycle, request["proposal_pin"], description=request["description"])
        elif args.command == "revise-premise":
            ce.keys(request, ("id", "statement", "basis", "reason"))
            result = revise_premise(args.cycle, request["id"], request["statement"],
                basis=request["basis"], reason=request["reason"])
        elif args.command == "configure-phases":
            ce.keys(request, ("request_pin", "check_contracts", "preconstruction_checks"))
            result = configure_phases(args.cycle, request["request_pin"],
                check_contracts=request["check_contracts"], preconstruction_checks=request["preconstruction_checks"])
        elif args.command == "record-check":
            result = record_check(args.cycle, args.check)
        elif args.command == "failed-import":
            ce.keys(request, ("id", "document_pin", "premise_ids", "predictions", "historical_cost"))
            result = import_failed_stage(args.cycle, request["id"], request["document_pin"],
                premise_ids=request["premise_ids"], predictions=request["predictions"], historical_cost=request["historical_cost"])
        elif args.command == "failed-attach":
            ce.keys(request, ("document_pin",))
            result = attach_failed_stage(args.cycle, args.experiment, request["document_pin"])
        elif args.command == "diagnostic-feedback":
            ce.keys(request, ("feedback_pin",))
            from . import gate_wiring  # failed_stage_feedback on the attached failed-stage intake.
            row = gate_wiring._campaign_row(args.cycle, args.experiment)
            if row.get("rundir") is None or row.get("failed_intake") is None:
                raise ValueError("diagnostic feedback needs the experiment's run and its attached failed-stage intake")
            gate_wiring.require_failed_feedback(row["rundir"], row["failed_intake"])
            result = diagnostic_feedback(args.cycle, args.experiment, request["feedback_pin"])
        elif args.command == "bind-knowledge":
            ce.keys(request, ("request_pin", "premise_map", "reason"))
            result = bind_knowledge(args.cycle, request["request_pin"],
                premise_map=request["premise_map"], reason=request["reason"])
        elif args.command == "knowledge-next":
            ce.keys(request, ("obligation_designs",))
            result = knowledge_next(args.cycle, obligation_designs=request["obligation_designs"])
        elif args.command == "reuse-adaptation":
            ce.keys(request, ("request_pin", "entry_id", "bindings"))
            result = reuse_adaptation(args.cycle, request["request_pin"],
                entry_id=request["entry_id"], bindings=request["bindings"])
        elif args.command == "continue":
            ce.keys(request, ("new_root", "contract", "reason"))
            result = continue_campaign(args.cycle, _cli_path(request["new_root"], base),
                request["contract"], reason=request["reason"])
        elif args.command == "progress":
            result = progress_synthesis(args.cycle, base_dir=base, report_request=request)
        elif args.command == "synthesize":
            result = synthesize(args.cycle, request, base_dir=base)
        elif args.command == "blueprint-context":
            from . import research_blueprint
            result = research_blueprint.prepare_context(args.cycle, args.out, parent=args.parent)
        elif args.command == "blueprint-admission":
            from . import research_blueprint
            ce.keys(request, ("graph_id", "max_wall_seconds"))
            result = research_blueprint.admission_spec(args.cycle, args.graph, node_id=args.node,
                graph_id=request["graph_id"], max_wall_seconds=request["max_wall_seconds"])
        elif args.command == "adopt-portfolio":
            from . import research_blueprint
            ce.keys(request, ("context_pin",))
            result = research_blueprint.adopt_portfolio(args.cycle, args.graph, node_id=args.node,
                context_pin=request["context_pin"])
        elif args.command == "discussion-prepare":
            from . import research_board_discussion
            ce.keys(request, ("board_root", "output_dir", "arm", "participant_order", "designer",
                "final_reviewers", "observations", "candidates", "max_output_tokens",
                "max_wall_seconds", "reasoning_effort", "adapter"))
            options = deepcopy(request)
            board_root = _cli_path(options.pop("board_root"), base)
            output_dir = _cli_path(options.pop("output_dir"), base)
            result = research_board_discussion.prepare(args.cycle, board_root, output_dir, **options)
        elif args.command == "discussion-run":
            from . import research_board_discussion, agent_host
            ce.keys(request, ("preparation_pin", *(["host_config"] if "host_config" in request else [])))
            host_config_pin = None
            if "host_config" in request:
                from .research_followup import _json
                # A host config names the programs and token commands that run with credentials; one inside
                # the run tree could have been written by a model session, so it is refused.
                named = Path(request["host_config"]["path"])
                if (named if named.is_absolute() else Path(base) / named).resolve().is_relative_to(Path(args.cycle).resolve()):
                    raise ValueError("host config must live outside the research cycle directory")
                resolved = (named if named.is_absolute() else Path(base) / named).resolve()
                host_config_pin = _pin(resolved)
                selected_host = agent_host.AgentHost.from_config(_json(request["host_config"], base))
                if _pin(resolved) != host_config_pin:
                    raise ValueError("host config changed while configuring the host")
            else:
                selected_host = agent_host.AgentHost()
            result = research_board_discussion.run(args.cycle, request["preparation_pin"], host=selected_host)
            if host_config_pin is not None:
                receipt = {"schema_version": 1, "kind": "research-host-config-receipt",
                           "host_config": host_config_pin, "report": result}
                destination = Path(result["path"]).parent / "host-config-receipt.json"
                with destination.open("x") as stream:
                    json.dump(receipt, stream, sort_keys=True, indent=2)
                    stream.write("\n")
        elif args.command == "discussion-adopt":
            from . import research_board_discussion
            ce.keys(request, ("report_pin",))
            result = research_board_discussion.adopt(args.cycle, request["report_pin"])
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return code
    except (OSError, ValueError, HostFailure) as exc:
        parser.exit(2, f"research cycle: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())


def _parent_goal(state):
    """Authenticate a derived original-task snapshot; never a second goal journal."""
    if "goal_binding" not in state["contract"]:
        if "parent_task" in state: raise ValueError("unbound research parent projection")
        return None
    if any(row["id"] == PARENT_PREMISE for row in state["premises"]):
        raise ValueError("reserved original parent task premise")
    from .task_completion import binding_projection
    actual = binding_projection(state["contract"]["goal_binding"], base_dir=state["base_dir"])
    if actual != state.get("parent_task"):
        raise ValueError("parent assignment or authorized scope changed; retain a goal-refresh revision")
    return actual


def refresh_parent_goal(root, *, reason):
    """Record a newly authorized/revoked planned amendment in the same journal.

    The original contract pin/assignment cannot be replaced here. The existing
    task-completion approval binding alone decides whether an amendment is
    effective. No scientific result or final parent acceptance carries over.
    """
    _text(reason)
    with state_io.file_lock(Path(root)/"operation.lock", blocking=False):
        _, state = _load(root, check_parent=False)
        if "goal_binding" not in state["contract"]: raise ValueError("existing bound parent task required")
        from .task_completion import binding_projection
        current = binding_projection(state["contract"]["goal_binding"], base_dir=state["base_dir"])
        previous = state["parent_task"]
        if current == previous: raise ValueError("parent goal already current")
        state["parent_task"] = current
        reopened = _reopen_premise_descendants(state, PARENT_PREMISE, reason)
        for experiment in state["experiments"]:
            if experiment["id"] in reopened:
                experiment["applicability_reopened"].update(
                    before_sha256=ce.digest(previous), after_sha256=ce.digest(current))
        return _commit(Path(root), state, "original_parent_scope_reobserved", reason=reason,
            original_contract=state["contract"]["goal_binding"]["contract"],
            previous_projection_sha256=ce.digest(previous), current_projection_sha256=ce.digest(current),
            affected_experiments=reopened, old_votes_carried=[], execution_authorized=False)


def finalize_manuscript(root,package_pin,bindings,build_binding,final_manifest,completion_request,*,base_dir,rundir):
    """Normal synthesis delivery consumes current parent/CI3; no checkpoint authority."""
    from . import manuscript_production,task_completion
    _,state=_load(root)
    if state.get('parent_task') is None:raise ValueError('final manuscript needs original whole-parent binding')
    result=manuscript_production.finalize(package_pin,bindings,build_binding,final_manifest,completion_request,
        base_dir=base_dir,rundir=rundir)
    if result['parent_task']['request']!=completion_request:raise ValueError('final task request changed')
    request=manuscript_production.integrity._json(manuscript_production.integrity._raw(completion_request,base_dir,{}))
    if request['contract']!=state['parent_task']['contract']:raise ValueError('manuscript final parent differs from current research parent')
    if _load(root)[1]['sha256']!=state['sha256']:raise ValueError('research changed during final manuscript delivery')
    return result


# Register events share the existing hash-linked campaign journal. The board consumes
# these event kinds; neither a model nor the board may supply a status vote.
REGISTER_KINDS = {'hypothesis', 'test', 'transition'}


def _reopening_predicate(value):
    if not isinstance(value, dict) or set(value) != {'kind', 'field', 'op', 'value'}:
        raise ValueError('typed reopening predicate required')
    if value['kind'] not in {'new_evidence', 'changed_input', 'increased_budget'}:
        raise ValueError('typed reopening kind required')
    _text(value['field'])
    if value['op'] not in {'eq', 'ne', 'gt', 'ge'} or isinstance(value['value'], (dict, list)):
        raise ValueError('typed reopening comparison required')


def _reopening_satisfied(predicate, pin, base_dir, snapshots=None):
    if not pin or (base_dir is None and snapshots is None):
        raise ValueError('reopening receipt satisfying typed predicate required')
    receipt = _register_read(pin, base_dir, snapshots)
    if receipt.get('kind') != predicate['kind'] or predicate['field'] not in receipt:
        raise ValueError('reopening receipt does not match typed predicate')
    actual, expected = receipt[predicate['field']], predicate['value']
    try:
        valid = {'eq': lambda: actual == expected, 'ne': lambda: actual != expected,
                 'gt': lambda: type(actual) in (int, float) and actual > expected,
                 'ge': lambda: type(actual) in (int, float) and actual >= expected}[predicate['op']]()
    except TypeError:
        valid = False
    if not valid:
        raise ValueError('reopening receipt does not satisfy typed predicate')


def _register_hypothesis(row, register, base_dir, snapshots=None):
    if 'status' in row:
        raise ValueError('status is code-computed, never model writable')
    allowed = {'id', 'statement', 'identity_signature', 'kill_condition', 'reopening_trigger',
               'operator', 'what_is_new', 'reopening_receipt'}
    if set(row) - allowed or not allowed - {'reopening_receipt'} <= row.keys():
        raise ValueError('complete hypothesis register declaration required')
    ce.identity(row['id']); _text(row['statement'])
    from .research_protocol import validate_operator
    validate_operator(row['operator'])
    if row['id'] in register:
        raise ValueError('immutable hypothesis identity already registered')
    signature = row['identity_signature']
    if not isinstance(signature, dict) or set(signature) != {'observable', 'scope', 'prediction'}:
        raise ValueError('structured hypothesis identity signature required')
    for value in signature.values(): _text(value)
    canonical = lambda value: {k: ' '.join(v.split()).casefold() for k, v in value.items()}
    signature = canonical(signature)
    kill = row['kill_condition']
    if (not isinstance(kill, dict) or set(kill) != {'comparison', 'observable'}
            or kill['comparison'] != 'differs' or ' '.join(kill['observable'].split()).casefold() != signature['observable']):
        raise ValueError('prospective scoped kill_condition required')
    _reopening_predicate(row['reopening_trigger'])
    for previous in register.values():
        if previous['status'] not in {'refuted', 'untestable_within_budget'}:
            continue
        old = canonical(previous['identity_signature'])
        changes = row['what_is_new']
        # A declared reopening must be applied, not merely mentioned in prose.
        if changes:
            if (not isinstance(changes, dict) or set(changes) - set(old)
                    or not all(isinstance(v, str) and v.strip() for v in changes.values())):
                raise ValueError('what_is_new requires signature fields')
            changed = {**old, **canonical(changes)}
            if signature != changed or changed == old:
                raise ValueError('what_is_new must be applied to the new identity signature')
            _reopening_satisfied(previous['reopening_trigger'], row.get('reopening_receipt'), base_dir, snapshots)
        elif signature == old:
            raise ValueError('what_is_new must differ from the refutation signature')
    return {**deepcopy(row), 'identity_signature': signature, 'status': 'active', 'refutation_signature': None,
            'scope_of_negative': None, 'tests': []}


def _register_test(row, observation, base_dir, snapshots=None):
    if 'status' in observation:
        raise ValueError('status is code-computed, never model writable')
    residual = observation.get('residual')
    if not isinstance(residual, dict) or set(residual) != {
            'observable', 'predicted', 'measured', 'interval', 'sign', 'constraint_violated'}:
        raise ValueError('every observation requires structured residual')
    comparison = observation.get('comparison')
    if comparison not in {'matches', 'differs', 'unknown'}:
        raise ValueError('prediction comparison required')
    if observation.get('execution_status') == 'budget_exhausted':
        if not observation.get('budget_receipt') or (base_dir is None and snapshots is None):
            raise ValueError('budget receipt required to park a hypothesis')
        receipt = _register_read(observation['budget_receipt'], base_dir, snapshots)
        if (receipt.get('kind') != 'research-budget-boundary' or type(receipt.get('spent')) not in (int, float)
                or type(receipt.get('cap')) not in (int, float) or receipt['cap'] <= 0 or receipt['spent'] < receipt['cap']):
            raise ValueError('exhausted budget receipt required')
        row['refutation_signature'] = deepcopy(row['identity_signature'])
        row['scope_of_negative'] = 'budget_only'
        return 'untestable_within_budget'
    if ExecutionStatus.normalize(observation.get('execution_status')) != ExecutionStatus.SUCCESS:
        return row['status']  # delivery failure is never an exclusion
    if comparison == 'unknown':
        return row['status']
    if row['status'] == 'refuted':
        return 'refuted'  # reopening always needs a fresh typed hypothesis event
    if comparison == 'matches':
        return 'survived_test'
    comparator, sensitivity = observation.get('comparator'), observation.get('sensitivity')
    if not comparator or not sensitivity:
        return 'weakened'
    if base_dir is None and snapshots is None:
        raise ValueError('source base required to verify comparator and sensitivity receipts')
    compared, checked = _register_read(comparator, base_dir, snapshots), _register_read(sensitivity, base_dir, snapshots)
    signature = row['identity_signature']
    if (compared.get('kind') != 'prediction-comparison' or compared.get('hypothesis_id') != row['id']
            or compared.get('comparison') != row['kill_condition']['comparison']
            or checked.get('kind') != 'sensitivity-check' or checked.get('status') != 'passed'
            or residual['observable'] != signature['observable']):
        raise ValueError('scoped comparator plus sensitivity receipt required for exclusion')
    for evidence in (compared, checked):
        if (evidence.get('scope') != signature['scope'] or evidence.get('observable') != signature['observable']
                or evidence.get('experiment_id') != observation.get('experiment_id')):
            raise ValueError('exclusion receipt scope or experiment differs')
    row['refutation_signature'] = deepcopy(signature)
    row['scope_of_negative'] = signature['scope']
    return 'refuted'


def replay_register(events, *, base_dir=None):
    """Deterministic board projection, rebuilt only from retained journal events."""
    register = {}; pending = None
    for event in events:
        kind = event.get('kind')
        if kind == 'hypothesis':
            row = _register_hypothesis(event['hypothesis'], register, base_dir, event.get('evidence_snapshots'))
            register[row['id']] = row
        elif kind == 'test':
            identity = event['hypothesis_id']
            if identity not in register:
                raise ValueError('test has no prospective hypothesis')
            row = register[identity]; before = row['status']
            row['status'] = _register_test(row, event['observation'], base_dir, event.get('evidence_snapshots'))
            row['tests'].append(deepcopy(event['observation']))
            pending = {'hypothesis_id': identity, 'from': before, 'to': row['status']}
        elif kind == 'transition':
            supplied = {key: event.get(key) for key in ('hypothesis_id', 'from', 'to')}
            if supplied != pending:
                raise ValueError('transition differs from computed register status')
            pending = None
    return register


def _register_proposal(state, row):
    """Strict research-route proposals; legacy non-research declarations retain scope."""
    fields = {'identity_signature', 'kill_condition', 'reopening_trigger', 'operator', 'what_is_new'}
    if not fields <= row.keys():
        if state['contract'].get('research_protocol_required'):
            raise ValueError('research hypothesis requires kill_condition, operator and typed register declaration')
        return
    event = {'kind': 'hypothesis', 'revision': state['revision'] + 1,
             'hypothesis': {key: deepcopy(row[key]) for key in
                {'id', 'statement', *fields, 'reopening_receipt'} if key in row}}
    if row.get('reopening_receipt'):
        event['evidence_snapshots'] = _register_snapshots([row['reopening_receipt']], state['base_dir'])
    replay_register([*state['events'], event], base_dir=state['base_dir'])
    state['events'].append(event)


def structured_residual(experiment, observation):
    """Retain uncertainty/unknown explicitly; no invented interval or significance."""
    observable = experiment.get('observable') or {}
    comparisons = observation.get('prediction_comparison', {})
    return {'observable': observable.get('pointer', observable.get('name', 'unresolved')),
            'predicted': deepcopy(experiment.get('predictions', {})),
            'measured': observation.get('measured'), 'interval': observation.get('interval'),
            'sign': 'different' if 'differs' in comparisons.values() else
                    'matches' if comparisons and set(comparisons.values()) == {'matches'} else 'unknown',
            'constraint_violated': sorted(k for k, v in comparisons.items() if v == 'differs') or None}


def _register_observation(state, experiment):
    observation = experiment['observation']
    observation['residual'] = structured_residual(experiment, observation)
    register = replay_register(state['events'], base_dir=state['base_dir'])
    for identity, comparison in sorted(observation.get('prediction_comparison', {}).items()):
        if identity not in register:
            continue
        residual = deepcopy(observation['residual'])
        residual['observable'] = register[identity]['identity_signature']['observable']
        residual['predicted'] = experiment['predictions'][identity]
        evidence = {'execution_status': observation['execution_status'], 'comparison': comparison,
                    'residual': residual, 'experiment_id': experiment['id'],
                    'comparator': None, 'sensitivity': None}
        event = {'kind': 'test', 'revision': state['revision'] + 1,
                 'hypothesis_id': identity, 'observation': evidence}
        after = replay_register([*state['events'], event], base_dir=state['base_dir'])
        state['events'].extend([event, {'kind': 'transition', 'revision': state['revision'] + 1,
            'hypothesis_id': identity, 'from': register[identity]['status'], 'to': after[identity]['status']}])
        register = after


def register_exclusion_evidence(root, hypothesis_id, experiment_id, *, comparator, sensitivity):
    """Exclusion seam: consume scoped source receipts, never a requested status."""
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        _, state = _load(root)
        experiment = next(e for e in state['experiments'] if e['id'] == experiment_id)
        _current_evidence(state, experiment, accepted=True)
        register = replay_register(state['events'], base_dir=state['base_dir'])
        row = register[hypothesis_id]
        observation = experiment['observation']
        if ExecutionStatus.normalize(observation['execution_status']) != ExecutionStatus.SUCCESS:
            raise ValueError('failed execution cannot produce exclusion')
        residual = deepcopy(observation['residual'])
        residual['observable'] = row['identity_signature']['observable']
        event = {'kind': 'test', 'revision': state['revision'] + 1, 'hypothesis_id': hypothesis_id,
                 'observation': {'execution_status': observation['execution_status'],
                     'comparison': observation['prediction_comparison'][hypothesis_id],
                     'experiment_id': experiment_id, 'residual': residual,
                     'comparator': comparator, 'sensitivity': sensitivity},
                 'evidence_snapshots': _register_snapshots([comparator, sensitivity], state['base_dir'])}
        after = replay_register([*state['events'], event], base_dir=state['base_dir'])
        state['events'].append(event)
        return _commit(Path(root), state, 'transition', hypothesis_id=hypothesis_id,
                       **{'from': row['status'], 'to': after[hypothesis_id]['status']})


def _register_snapshots(pins, base_dir):
    snapshots = {}
    for pin in pins:
        path, _ = _check_pin(pin, base_dir)
        raw = path.read_bytes().decode('utf-8')
        if __import__('hashlib').sha256(raw.encode()).hexdigest() != pin['sha256']:
            raise ValueError('register evidence changed during snapshot')
        snapshots[pin['sha256']] = raw
    return snapshots


def _register_read(pin, base_dir, snapshots):
    if snapshots is None:
        return _read(pin, base_dir)  # original legacy events retain their semantics
    raw = snapshots.get(pin['sha256'])
    if not isinstance(raw, str) or __import__('hashlib').sha256(raw.encode()).hexdigest() != pin['sha256']:
        raise ValueError('register evidence snapshot differs')
    return __import__('json').loads(raw)
