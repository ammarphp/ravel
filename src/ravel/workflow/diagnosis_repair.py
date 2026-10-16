"""Evidence-bound discrepancy, contrast, correction and graph-rework handoffs.

These operations never launch a stage or grant approval. Bounds are supplied
scientific inputs, not inferred from acceptance residuals or endpoint samples.
Constructive results are recomputed with the existing diagnostic engine before
any correction is offered to the ordinary graph revision/rework APIs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ravel.validation import residual_decomposition as residual
from ravel.validation import validate_cutflow
from ravel.workflow import agent_graph, constructive_contrast as contrast
from ravel.workflow import diagnostic_plan as dp
from ravel.workflow.execution import digest

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 256


def _bounded(value):
    raw = json.dumps(value, allow_nan=False, sort_keys=True).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError("diagnosis record exceeds byte bound")
    return json.loads(raw)


def _read(pin, base_dir):
    dp.binding(pin)
    path = Path(pin["path"]).expanduser()
    path = path if path.is_absolute() else Path(base_dir) / path
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("diagnosis evidence requires a regular file without symlinks")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("diagnosis evidence exceeds byte bound")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
        raise ValueError("diagnosis evidence bytes changed")
    return raw


def _json(pin, base_dir):
    raw = _read(pin, base_dir)
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate diagnosis evidence JSON key")
            out[key] = value
        return out
    def constant(value):
        raise ValueError("nonfinite diagnosis evidence JSON constant")
    def floating(value):
        return dp.number(float(value), "diagnosis evidence JSON number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


def _observation(reference, base_dir):
    dp.keys(reference, {"artifact", "pointer"}, "evidence reference")
    value = dp.pointer(_json(reference["artifact"], base_dir), reference["pointer"])
    return _bounded(value)


def _seal(value):
    result = deepcopy(value)
    result["sha256"] = digest(value)
    return result


def _intact(value, kind):
    if type(value) is not dict or value.get("kind") != kind:
        raise ValueError("expected " + kind)
    data = {key: val for key, val in value.items() if key != "sha256"}
    if value.get("sha256") != digest(data):
        raise ValueError("diagnosis record changed")


def _nodes(values):
    dp.unique(values, "changed graph nodes")
    if len(values) > MAX_ROWS:
        raise ValueError("too many graph nodes")
    return deepcopy(values)


def _row(identity, reference, graph_nodes, effect, base_dir):
    dp.text(identity, "discrepancy id")
    return {"id": identity, "status": "open", "source": deepcopy(reference),
            "observation": _observation(reference, base_dir),
            "graph_nodes": _nodes(graph_nodes), "effect": deepcopy(effect)}


def _fresh_row(row, base_dir):
    row = _bounded(row)
    dp.keys(row, {"id", "status", "source", "observation", "graph_nodes", "effect"}, "discrepancy row")
    dp.text(row["id"], "discrepancy id")
    if row["status"] != "open":
        raise ValueError("repair requires an open discrepancy")
    _nodes(row["graph_nodes"])
    if _observation(row["source"], base_dir) != row["observation"]:
        raise ValueError("discrepancy source observation changed")
    return deepcopy(row)


def cutflow_discrepancies(report_pin, *, graph_nodes, effects=None, base_dir="."):
    """Retain supplied failed/missing cutflow comparisons without causal claims.

    Node mappings and optional final-quantity effects are supplied judgments.
    Legacy impact fields remain observations and never become effect bounds.
    Ratios are recomputed from measured values; ``ok`` is the producer's supplied
    tier verdict, not a threshold verdict independently reconstructed here.
    """
    report = _json(report_pin, base_dir)
    rows = report.get("rows")
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError("bounded cutflow comparison rows required")
    results, seen = [], set()
    for index, row in enumerate(rows):
        identity = dp.text(row.get("sr"), "cutflow row id")
        if identity in seen:
            raise ValueError("duplicate cutflow row id")
        seen.add(identity)
        ratio = validate_cutflow.comparison_ratio(row.get("mine"), row.get("pub"))
        if ratio != row.get("ratio") or type(row.get("ok")) is not bool:
            raise ValueError("cutflow ratio or verdict differs from measured comparison")
        if row["ok"] and ratio is not None:
            continue
        reference = {"artifact": report_pin, "pointer": f"/rows/{index}"}
        results.append(_row(identity, reference, graph_nodes[identity], (effects or {}).get(identity), base_dir))
    return results


def residual_discrepancies(record_pin, claims, *, graph_nodes, effects=None, base_dir="."):
    """Normalize only claims accepted by the existing above-noise check.

    The decomposition's hash/noise check is a diagnostic check, not independent
    custody certification or proof that an attributed term is a cause.
    """
    record = _json(record_pin, base_dir)
    if type(claims) is not list or not 1 <= len(claims) <= MAX_ROWS:
        raise ValueError("bounded nonempty attribution claims required")
    checked = residual.check_attribution_above_noise(record, claims)
    if checked["status"] != "passed":
        raise ValueError("attribution not above noise: " + json.dumps(checked["refusals"]))
    results, seen = [], set()
    for claim in claims:
        identity = claim.get("scope", "all") + ":" + claim["term"]
        if claim.get("fingerprint") is not None:
            identity += ":" + claim["fingerprint"]
        if identity in seen:
            raise ValueError("duplicate residual discrepancy")
        seen.add(identity)
        row = _row(identity, {"artifact": record_pin, "pointer": ""}, graph_nodes[identity],
                   (effects or {}).get(identity), base_dir)
        # Keep the actual supplied claim in the observation's provenance by
        # selecting a distinct id; full source bytes remain bound on replay.
        results.append(row)
    return results


def first_divergence(stages, *, base_dir="."):
    """Compare pinned stage quantities in a caller-declared causal order.

    Each stage is {id, comparison: {artifact, pointer}}; the selected object has
    observed, expected and absolute_tolerance. Expectations must be computed
    independently by the caller. A downstream mismatch is not a second cause.
    """
    if type(stages) is not list or not 1 <= len(stages) <= MAX_ROWS:
        raise ValueError("bounded nonempty ordered stages required")
    outcomes, seen = [], set()
    for stage in stages:
        dp.keys(stage, {"id", "comparison"}, "stage comparison")
        identity = dp.text(stage["id"], "stage id")
        if identity in seen:
            raise ValueError("duplicate stage id")
        seen.add(identity)
        item = _observation(stage["comparison"], base_dir)
        dp.keys(item, {"observed", "expected", "absolute_tolerance"}, "stage quantities")
        observed = dp.number(item["observed"], "observed quantity")
        expected = dp.number(item["expected"], "independent expectation")
        tolerance = dp.number(item["absolute_tolerance"], "absolute tolerance")
        if tolerance < 0:
            raise ValueError("absolute tolerance must be nonnegative")
        difference = dp.number(observed - expected, "stage difference")
        outcomes.append({"id": identity, "difference": difference,
                         "passed": abs(difference) <= tolerance,
                         "comparison": deepcopy(stage["comparison"]), **item})
    return {"kind": "first_divergence", "first": next((r["id"] for r in outcomes if not r["passed"]), None),
            "comparisons": outcomes, "ordering": "supplied causal order", "cause_established": False,
            "execution_authorized": False}


def rank_discrepancies(rows, requested_quantity, *, base_dir="."):
    """Rank open issues by supplied final-quantity enclosures; retain unknowns.

    An effect reference selects {quantity, unit, lower, upper, kind, basis,
    enclosure_evidence}. Only supplied_enclosure with separately pinned evidence
    is called a supplied bound. endpoint_sensitivity is an unbounded diagnostic
    span. No interval is promoted to a certified mathematical/physical bound.
    """
    dp.keys(requested_quantity, {"id", "unit"}, "requested quantity")
    for key, value in requested_quantity.items():
        dp.text(value, key)
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError("bounded discrepancy rows required")
    ranked, seen = [], set()
    for original in rows:
        row = _fresh_row(original, base_dir)
        if row["id"] in seen:
            raise ValueError("duplicate discrepancy id")
        seen.add(row["id"])
        bound, span, evidence = None, None, None
        if row["effect"] is not None:
            evidence = _observation(row["effect"], base_dir)
            dp.keys(evidence, {"quantity", "unit", "lower", "upper", "kind", "basis", "enclosure_evidence"}, "quantity effect")
            if evidence["quantity"] != requested_quantity["id"] or evidence["unit"] != requested_quantity["unit"]:
                raise ValueError("effect quantity or unit differs from requested final quantity")
            lower, upper = (dp.number(evidence[k], "effect " + k) for k in ("lower", "upper"))
            if lower > upper:
                raise ValueError("effect interval is reversed")
            dp.text(evidence["basis"], "effect basis")
            span = max(abs(lower), abs(upper))
            if evidence["kind"] == "supplied_enclosure":
                if evidence["enclosure_evidence"] is None:
                    raise ValueError("supplied enclosure needs separate enclosure evidence")
                proof = _observation(evidence["enclosure_evidence"], base_dir)
                if not proof or evidence["enclosure_evidence"]["artifact"] == row["effect"]["artifact"]:
                    raise ValueError("enclosure evidence must be nonempty and separately pinned")
                bound = span
            elif evidence["kind"] != "endpoint_sensitivity" or evidence["enclosure_evidence"] is not None:
                raise ValueError("unknown effect kind or endpoint evidence claiming an enclosure")
        ranked.append({"discrepancy": row, "effect_evidence": evidence, "max_abs_supplied_bound": bound,
                       "sensitivity_span": span, "bound_status": "supplied_not_certified" if bound is not None else "unknown",
                       "needs_effect_measurement": bound is None})
    # Unknown bounds cannot be silently assigned zero or placed below known
    # harmless effects. Within known bounds use descending worst-case magnitude.
    ranked.sort(key=lambda r: (r["max_abs_supplied_bound"] is not None,
                              -(r["max_abs_supplied_bound"] or 0), r["discrepancy"]["id"]))
    return {"kind": "discrepancy_priorities", "requested_quantity": deepcopy(requested_quantity), "rows": ranked,
            "ordering": "unknown bounds first, then descending supplied bound", "execution_authorized": False}


def prepare_experiment(discrepancy, constructive_request, *, base_dir="."):
    row = _fresh_row(discrepancy, base_dir)
    preparation = contrast.prepare(constructive_request, base_dir)
    if preparation["request"]["finding"]["id"] != row["id"]:
        raise ValueError("constructive finding must identify the discrepancy")
    if preparation["evaluation_contract_sha256"] is None or not preparation["discriminating_predictions"]:
        raise ValueError("repair requires a frozen discriminating experiment")
    return _seal({"kind": "diagnosis_experiment", "discrepancy": row, "preparation": preparation,
                  "execution_authorized": False, "review_required": True})


def _fresh_experiment(experiment, base_dir):
    _intact(experiment, "diagnosis_experiment")
    fresh = prepare_experiment(experiment["discrepancy"], experiment["preparation"]["request"], base_dir=base_dir)
    if fresh != experiment:
        raise ValueError("diagnosis experiment changed")
    return fresh


def evaluate_experiment(experiment, completed_plan=None, *, base_dir="."):
    fresh = _fresh_experiment(experiment, base_dir)
    application = contrast.apply_results(fresh["preparation"], completed_plan, base_dir)
    unique = application["status"] != "unresolved" and len(application["surviving_rivals"]) == 1
    eligible = unique and application["next_action"]["action"] == "propose_challenger_review"
    return _seal({"kind": "diagnosis_evaluation", "experiment": fresh, "completed_plan": deepcopy(completed_plan),
                  "application": application, "state": "correction_review_required" if eligible else "needs_discriminating_evidence",
                  "execution_authorized": False, "review_required": True, "discrepancy_resolved": False})


def _fresh_evaluation(evaluation, base_dir):
    _intact(evaluation, "diagnosis_evaluation")
    fresh = evaluate_experiment(evaluation["experiment"], evaluation["completed_plan"], base_dir=base_dir)
    if fresh != evaluation:
        raise ValueError("diagnosis evaluation changed")
    return fresh


def prepare_correction(evaluation, correction_pin, *, base_dir="."):
    """Bind a separately materialized source correction to measured discrimination.

    The correction record contains discrepancy_id, rival_id, changed_nodes,
    before, after and reason. This verifies source bytes, not semantic validity,
    source consumption, independent review, or scientific closure.
    """
    fresh = _fresh_evaluation(evaluation, base_dir)
    if fresh["state"] != "correction_review_required":
        raise ValueError("unresolved or nondiscriminating evidence cannot select a correction")
    record = _json(correction_pin, base_dir)
    dp.keys(record, {"discrepancy_id", "rival_id", "changed_nodes", "before", "after", "reason"}, "correction record")
    row, prep = fresh["experiment"]["discrepancy"], fresh["experiment"]["preparation"]
    if record["discrepancy_id"] != row["id"] or record["rival_id"] != fresh["application"]["surviving_rivals"][0]:
        raise ValueError("correction does not match the measured surviving rival")
    nodes = _nodes(record["changed_nodes"])
    if not set(nodes) <= set(row["graph_nodes"]):
        raise ValueError("correction names graph nodes outside the discrepancy")
    dp.text(record["reason"], "correction reason")
    before, after = _read(record["before"], base_dir), _read(record["after"], base_dir)
    if record["before"] != prep["request"]["baseline"] or hashlib.sha256(after).hexdigest() != prep["controlled_source_sha256"]:
        raise ValueError("correction source differs from the measured controlled alternative")
    if before == after:
        raise ValueError("correction must change source bytes")
    return _seal({"kind": "diagnosis_correction", "evaluation": fresh, "correction_pin": deepcopy(correction_pin),
                  "correction": record, "execution_authorized": False, "review_required": True,
                  "source_consumption_verified": False, "discrepancy_resolved": False})


def request_rework(correction, graph_root, *, revised_spec=None, base_dir="."):
    """Invalidate descendants using existing budgets and active-call safeguards.

    A supplied replacement spec uses ordinary graph revision. Callers retain
    responsibility for review, source-to-node mapping and supervised execution.
    No rerun is dispatched here and a pending rerun never closes the discrepancy.
    """
    _intact(correction, "diagnosis_correction")
    fresh = prepare_correction(correction["evaluation"], correction["correction_pin"], base_dir=base_dir)
    if correction != fresh:
        raise ValueError("diagnosis correction changed")
    record = fresh["correction"]
    root = Path(graph_root).resolve()
    baseline = _bounded(agent_graph.status(root))
    old_spec = _current_spec(root, baseline)
    by_id = {node["id"]: node for node in old_spec["nodes"]}
    for identity in record["changed_nodes"]:
        if identity not in by_id or not any(
                all(pin.get(key) == record["before"][key] for key in ("path", "sha256"))
                for pin in by_id[identity]["inputs"]):
            raise ValueError("correction graph node must bind the original source")
    reason = "Discrepancy " + record["discrepancy_id"] + ": " + record["reason"]
    if revised_spec is None:
        state = agent_graph.rework(graph_root, record["changed_nodes"], reason=reason)
    else:
        # Bind the checked predecessor through the existing revision fence;
        # a concurrent revision must not turn this into an unrelated repair.
        path = Path(graph_root) / agent_graph.SPEC
        old_pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        old = _json(old_pin, ".")
        new = agent_graph.validate(revised_spec)
        if {k: v for k, v in old.items() if k != "nodes"} != {k: v for k, v in new.items() if k != "nodes"}:
            raise ValueError("correction cannot change graph metadata or budgets")
        before = {n["id"]: n for n in old["nodes"]}
        after = {n["id"]: n for n in new["nodes"]}
        changed = {key for key in before if before[key] != after.get(key)}
        if changed != set(record["changed_nodes"]):
            raise ValueError("revision must change exactly the correction graph nodes")
        for key in changed:
            if not any(all(pin.get(field) == record["after"][field] for field in ("path", "sha256"))
                       for pin in after[key]["inputs"]):
                raise ValueError("changed graph node must bind the corrected source")
        state_path = root / agent_graph.STATE
        checked_state = _json({"path": str(state_path), "sha256": hashlib.sha256(state_path.read_bytes()).hexdigest()}, ".")
        if any(baseline.get(key) != value for key, value in checked_state.items()):
            raise ValueError("graph changed before correction revision")
        state = agent_graph.revise(graph_root, new, reason=reason, expected_spec_sha256=digest(old),
                                   expected_state_sha256=digest(checked_state))
    new_spec = _current_spec(root, state)
    affected = sorted(set(_descendants(old_spec, record["changed_nodes"])) |
                      set(_descendants(new_spec, record["changed_nodes"])))
    if (state["reworks"] != baseline["reworks"] + 1 or
            state["graph_revision"] != baseline["graph_revision"] + 1):
        raise ValueError("graph changed concurrently with correction rework")
    for identity, prior in baseline["nodes"].items():
        current = state["nodes"][identity]
        if identity in affected:
            if current["generation"] != prior["generation"] + 1 or current["status"] != "pending":
                raise ValueError("correction descendants were not freshly invalidated")
        elif current != prior:
            raise ValueError("unrelated graph node changed during correction rework")
    return _seal({"kind": "diagnosis_rerun_handoff", "correction_sha256": fresh["sha256"],
                  "correction": fresh, "graph_root": str(root), "baseline_graph": baseline,
                  "affected_nodes": affected, "graph": state, "rerun_required": True,
                  "execution_authorized": False, "source_consumption_verified": False,
                  "discrepancy_resolved": False})


def _current_spec(root, state):
    path = Path(root) / agent_graph.SPEC
    spec = _json({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, ".")
    spec = agent_graph.validate(spec)
    if digest(spec) != state["spec_sha256"] or len(spec["nodes"]) > MAX_ROWS:
        raise ValueError("graph specification differs from bounded checkpoint")
    return spec


def _descendants(spec, changed):
    selected = set(changed)
    if not selected <= {n["id"] for n in spec["nodes"]}:
        raise ValueError("correction names absent graph nodes")
    for _ in spec["nodes"]:
        newer = selected | {n["id"] for n in spec["nodes"] if selected.intersection(n["depends_on"])}
        if newer == selected:
            return sorted(selected)
        selected = newer
    return sorted(selected)


def _completed_receipt(root, state, node, spec):
    current = state["nodes"][node["id"]]
    reference = current["result"]
    if current["status"] != "completed" or reference is None:
        raise ValueError("rerun node has no completed receipt")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("attempts",):
        raise ValueError("rerun receipt escaped graph custody")
    path = Path(root) / relative
    byte_pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    receipt = _json(byte_pin, ".")
    request = receipt["request"]
    expected_request = agent_graph._request(spec, state, node, receipt["host_sha256"])
    if request != expected_request:
        raise ValueError("rerun receipt does not bind its current node and generation request")
    for artifact in node["inputs"]:
        _read({key: artifact[key] for key in ("path", "sha256")}, ".")
    dependencies = [{"node_id": key, "result_sha256": state["nodes"][key]["result"]["result_sha256"]}
                    for key in node["depends_on"]]
    if (digest(receipt) != reference["sha256"] or digest(receipt["result"]) != reference["result_sha256"] or
            receipt["node_id"] != node["id"] or receipt["attempt_id"] != current["attempt_id"] or
            request["node_id"] != node["id"] or request["graph_id"] != state["graph_id"] or
            request["generation"] != current["generation"] or request["node_sha256"] != digest(node) or
            request["input_artifacts"] != node["inputs"] or request["dependencies"] != dependencies or
            request["binding_sha256"] != reference["binding_sha256"] or
            receipt["host_sha256"] != reference["host_sha256"]):
        raise ValueError("rerun receipt does not bind its current node and generation")
    calls = receipt.get("call_receipts")
    if type(calls) is not list or not 1 <= len(calls) <= MAX_ROWS:
        raise ValueError("rerun receipt needs bounded accounted dispatch receipts")
    identities = [call.get("call_id") for call in calls if type(call) is dict]
    if len(identities) != len(calls) or any(type(identity) is not str for identity in identities) or len(set(identities)) != len(calls):
        raise ValueError("rerun dispatch receipts must be unique")
    expected_calls = {identity for identity, call in state["calls"].items()
                      if call["attempt_id"] == current["attempt_id"] and call["status"] == "completed"}
    if set(identities) != expected_calls:
        raise ValueError("rerun dispatch receipt population differs from accounted attempt")
    call_pins = []
    executable = False
    for call in calls:
        dp.keys(call, {"call_id", "sha256"}, "dispatch receipt reference")
        identity = call["call_id"]
        if type(identity) is not str or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("invalid accounted dispatch receipt identity")
        accounted = state["calls"].get(identity)
        if (not accounted or accounted["status"] != "completed" or
                accounted["node_id"] != node["id"] or accounted["attempt_id"] != current["attempt_id"] or
                accounted["receipt_sha256"] != call["sha256"]):
            raise ValueError("rerun dispatch is not accounted to its current attempt")
        path = Path(root) / "calls" / (identity + ".json")
        measured_pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        measured = _json(measured_pin, ".")
        call_pins.append(measured_pin)
        if (any(measured.get(key) != value for key, value in accounted.items() if key != "receipt_sha256") or
                digest(measured) != call["sha256"] or measured.get("status") != "completed" or
                measured.get("call_id") != identity or digest(measured["result"]) != measured.get("result_sha256")):
            raise ValueError("rerun accounted dispatch receipt changed")
        executable |= measured.get("kind") == ("tool" if node["kind"] in {"agent", "map"} else node["kind"])
    if not executable:
        raise ValueError("rerun receipt has no accounted executable host dispatch")
    return receipt, byte_pin, call_pins


def verify_rerun(handoff, graph_root, *, final_node, quantity_pointer, reference, base_dir="."):
    """Verify an externally executed rerun and its actual final-node quantity.

    ``quantity_pointer`` selects {quantity, unit, value} within the final node's
    receipted result. The separately pinned ``reference`` selects {quantity,
    unit, expected, absolute_tolerance}. This compares supplied scientific choices;
    it does not establish their independence, applicability or physical validity.
    """
    _intact(handoff, "diagnosis_rerun_handoff")
    root = Path(graph_root).resolve()
    if str(root) != handoff["graph_root"]:
        raise ValueError("rerun belongs to a different graph root")
    correction = handoff["correction"]
    fresh = prepare_correction(correction["evaluation"], correction["correction_pin"], base_dir=base_dir)
    if correction != fresh or correction["sha256"] != handoff["correction_sha256"]:
        raise ValueError("rerun correction evidence changed")
    state = _bounded(agent_graph.status(root))
    prior, pending = handoff["baseline_graph"], handoff["graph"]
    for key in ("graph_id", "instance_id", "spec_sha256", "graph_revision", "reworks", "budget"):
        if state[key] != pending[key]:
            raise ValueError("rerun graph was revised or reworked after the handoff")
    if not state["complete"] or state["cancelled"]:
        raise ValueError("rerun graph is not complete")
    if set(state["nodes"]) != set(prior["nodes"]):
        raise ValueError("rerun graph population changed")
    spec = _current_spec(root, state)
    nodes = {node["id"]: node for node in spec["nodes"]}
    retained_path = root / "specs" / (prior["spec_sha256"] + ".json")
    retained_pin = {"path": str(retained_path), "sha256": hashlib.sha256(retained_path.read_bytes()).hexdigest()}
    retained = _json(retained_pin, ".")
    old_spec = agent_graph.validate(retained)
    if digest(old_spec) != prior["spec_sha256"]:
        raise ValueError("rerun predecessor specification changed")
    changed = correction["correction"]["changed_nodes"]
    affected = sorted(set(_descendants(old_spec, changed)) | set(_descendants(spec, changed)))
    if affected != handoff["affected_nodes"]:
        raise ValueError("rerun affected nodes differ from correction descendants")
    if (pending["reworks"] != prior["reworks"] + 1 or
            pending["graph_revision"] != prior["graph_revision"] + 1):
        raise ValueError("rerun handoff is not a single correction revision")
    if final_node not in affected:
        raise ValueError("final quantity must come from a corrected descendant")
    receipts = {}
    for identity, current in state["nodes"].items():
        before = prior["nodes"][identity]
        if identity not in affected:
            if current != before:
                raise ValueError("untouched node receipt or generation changed")
            continue
        if (current["generation"] != before["generation"] + 1 or
                current["generation"] != pending["nodes"][identity]["generation"] or
                current["attempt_id"] == before["attempt_id"] or current["result"] == before["result"]):
            raise ValueError("corrected descendant did not produce a fresh generation receipt")
        receipts[identity] = _completed_receipt(root, state, nodes[identity], spec)
    for identity in correction["correction"]["changed_nodes"]:
        corrected_pin = correction["correction"]["after"]
        inputs = receipts[identity][0]["request"]["input_artifacts"]
        if not any(all(item.get(key) == corrected_pin[key] for key in ("path", "sha256")) for item in inputs):
            raise ValueError("rerun receipt did not declare the corrected source")
    receipt, actual_pin, _ = receipts[final_node]
    if receipt["request"]["graph_revision"] != pending["graph_revision"]:
        raise ValueError("final quantity receipt is from a stale graph revision")
    expected_path = Path(reference["artifact"]["path"]).expanduser()
    expected_path = expected_path if expected_path.is_absolute() else Path(base_dir) / expected_path
    if expected_path.resolve().is_relative_to(root / "attempts"):
        raise ValueError("expected reference must be separately pinned from graph output receipts")
    expected = _observation(reference, base_dir)
    actual = _bounded(dp.pointer(receipt["result"], quantity_pointer))
    dp.keys(actual, {"quantity", "unit", "value"}, "rerun final quantity")
    dp.keys(expected, {"quantity", "unit", "expected", "absolute_tolerance"}, "rerun reference")
    for key in ("quantity", "unit"):
        dp.text(actual[key], "final " + key)
        if actual[key] != expected[key]:
            raise ValueError("rerun final quantity or unit differs from reference")
    observed = dp.number(actual["value"], "rerun quantity")
    target = dp.number(expected["expected"], "reference quantity")
    tolerance = dp.number(expected["absolute_tolerance"], "reference tolerance")
    if tolerance < 0:
        raise ValueError("reference tolerance must be nonnegative")
    difference = dp.number(observed - target, "corrected quantity difference")
    # A checkpoint can remain unchanged while a retained dispatch file changes.
    # Reobserve every byte pin rather than treating a durable state label as custody.
    for saved, receipt_pin, call_pins in receipts.values():
        _read(receipt_pin, ".")
        for call_pin in call_pins:
            _read(call_pin, ".")
        for artifact in saved["request"]["input_artifacts"]:
            _read({key: artifact[key] for key in ("path", "sha256")}, ".")
    # The measured discrimination and predecessor also remain part of the
    # verification basis after the output/reference comparison has been read.
    _read(retained_pin, ".")
    if prepare_correction(correction["evaluation"], correction["correction_pin"], base_dir=base_dir) != fresh:
        raise ValueError("rerun correction evidence changed during verification")
    # Recheck both durable populations after reading all source and output bytes.
    if _bounded(agent_graph.status(root)) != state or _observation(reference, base_dir) != expected:
        raise ValueError("rerun evidence changed during verification")
    return _seal({"kind": "diagnosis_rerun_verification", "handoff_sha256": handoff["sha256"],
                  "graph_instance": state["instance_id"], "graph_revision": state["graph_revision"],
                  "affected_nodes": affected, "final_node": final_node,
                  "final_receipt": actual_pin, "quantity_pointer": quantity_pointer,
                  "reference": deepcopy(reference), "quantity": actual["quantity"], "unit": actual["unit"],
                  "observed": observed, "expected": target, "difference": difference,
                  "absolute_tolerance": tolerance, "comparison_passed": abs(difference) <= tolerance,
                  "rerun_completed": True, "execution_authorized": False,
                  "source_consumption_verified": False, "discrepancy_resolved": False,
                  "limitations": ["Graph receipts bind declared inputs and accounted host dispatch; native source consumption is not established.",
                                  "Reference independence, physical applicability and scientific closure require separate review."]})
