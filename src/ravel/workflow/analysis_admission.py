"""Open, source-bound analysis admission and prospective reference arithmetic.

An unfamiliar analysis name is not a refusal. Evidence requirements follow the
requested task and physical input. This module executes no source or reviewer,
and never confers physics certification. It verifies custody, complete output
bases and supplied scoped check receipts; interpretation of their scientific
premises remains an independent review obligation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from .science import regular
from .state_io import atomic_json, read_json


PURPOSES = {"routine-evaluation", "reference-reproduction", "measurement-comparison",
            "exclusion", "projection", "method-study"}
LEVELS = {"particle", "reconstructed", "truth", "non-event"}
BASE_CHECKS = {"source-closure", "build", "exposure", "output-completeness"}
PHYSICS_CHECKS = {"definitions", "semantics", "normalization", "reference"}
KINDS = BASE_CHECKS | PHYSICS_CHECKS | {"response", "uncertainty", "statistics",
            "independent-review", "projection-calibration", "data-use", "method-calibration"}
MAX_ARTIFACTS, MAX_OUTPUTS = 256, 4096


def _keys(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(label + " has missing or unknown fields")


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise ValueError("invalid " + label)
    return value


def _names(values, label, *, empty=False):
    if not isinstance(values, list) or (not empty and not values):
        raise ValueError("invalid " + label)
    if len(set(map(lambda x: _text(x, label), values))) != len(values):
        raise ValueError("duplicate " + label)
    return values


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("artifact needs exact lowercase SHA256")
    return value


def _number(value, label, *, nonnegative=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and (not nonnegative or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("invalid " + label)
    return value


def _output(value):
    _keys(value, {"name", "quantity", "unit", "normalization", "representation", "weight", "definition", "bin"}, "output")
    for key, item in value.items():
        if key == "bin":
            continue
        _text(item, "output " + key)
    if value["representation"] not in {"integrated", "differential", "scalar"}:
        raise ValueError("declare integrated, differential or scalar output")
    if value["normalization"] not in {"absolute", "all-events", "in-range", "conditional"}:
        raise ValueError("declare output normalization")
    if value["bin"] is not None:
        _keys(value["bin"], {"axes"}, "bin geometry")
        axes = value["bin"]["axes"]
        if not isinstance(axes, list) or not 0 < len(axes) <= 8:
            raise ValueError("bounded explicit bin axes required")
        names = set()
        for axis in axes:
            _keys(axis, {"name", "unit", "lower", "upper"}, "bin axis")
            name = _text(axis["name"], "axis name"); _text(axis["unit"], "axis unit")
            if name in names:
                raise ValueError("duplicate bin axis")
            names.add(name)
            low = _number(axis["lower"], "lower bin edge")
            high = _number(axis["upper"], "upper bin edge")
            if low >= high:
                raise ValueError("bin edges must increase")
    elif value["representation"] == "differential":
        raise ValueError("differential output requires explicit bin geometry")


def requirements(specification):
    """Derive prerequisites from the requested task, never from analysis names."""
    request = specification["request"]
    needed = set(BASE_CHECKS)
    if request["input_level"] == "non-event":
        needed.remove("exposure")
    if request["purpose"] != "routine-evaluation":
        needed |= PHYSICS_CHECKS
        if request["target_level"] == "reconstructed":
            needed.add("response")
    if request["purpose"] in {"measurement-comparison", "exclusion", "projection"}:
        needed |= {"uncertainty", "statistics", "independent-review"}
    if request["purpose"] == "projection":
        needed.add("projection-calibration")
    if request["purpose"] == "method-study":
        needed |= {"data-use", "method-calibration", "independent-review"}
    return sorted(needed)


def validate_specification(specification):
    _keys(specification, {"schema_version", "kind", "analysis_id", "implementation", "request", "artifacts",
                         "subjects", "definitions", "outputs", "checks"}, "analysis specification")
    if type(specification["schema_version"]) is not int or specification["schema_version"] != 1 or specification["kind"] != "analysis_specification":
        raise ValueError("unsupported analysis specification")
    _text(specification["analysis_id"], "analysis identity")
    request = specification["request"]
    _keys(request, {"purpose", "input_level", "target_level", "scope"}, "request")
    if request["purpose"] not in PURPOSES or request["input_level"] not in LEVELS or request["target_level"] not in LEVELS:
        raise ValueError("unsupported requested task or physical input level")
    if not isinstance(request["scope"], dict) or not request["scope"]:
        raise ValueError("explicit scientific applicability scope required")
    # Scope is a source-bound declaration, not a catalogued-model whitelist.
    _digest(request["scope"])
    artifacts = specification["artifacts"]
    if not isinstance(artifacts, list) or not 0 < len(artifacts) <= MAX_ARTIFACTS:
        raise ValueError("bounded artifact census required")
    ids = set()
    for artifact in artifacts:
        _keys(artifact, {"id", "path", "sha256", "role"}, "artifact")
        name = _text(artifact["id"], "artifact identity")
        if name in ids:
            raise ValueError("duplicate artifact identity")
        ids.add(name)
        _text(artifact["path"], "artifact path"); _text(artifact["role"], "artifact role")
        _hash(artifact["sha256"])
    subjects = _names(specification["subjects"], "subject artifacts")
    if not set(subjects) <= ids:
        raise ValueError("unknown subject artifact")
    implementation = specification["implementation"]
    _keys(implementation, {"framework", "routine", "artifact"}, "implementation")
    _text(implementation["framework"], "implementation framework")
    _text(implementation["routine"], "implementation routine")
    if implementation["artifact"] not in subjects:
        raise ValueError("implementation must be one of the bound subject artifacts")
    definitions = specification["definitions"]
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("source-backed object/selection/output definitions required")
    definition_ids = set()
    for definition in definitions:
        _keys(definition, {"id", "role", "definition", "artifact", "locator"}, "definition")
        name = _text(definition["id"], "definition identity")
        if name in definition_ids:
            raise ValueError("duplicate definition identity")
        definition_ids.add(name)
        for key in ("role", "definition", "locator"):
            _text(definition[key], "definition " + key)
        if definition["artifact"] not in ids:
            raise ValueError("definition points to unknown source artifact")
    outputs = specification["outputs"]
    if not isinstance(outputs, list) or not 0 < len(outputs) <= MAX_OUTPUTS:
        raise ValueError("complete bounded requested output denominator required")
    for output in outputs:
        _output(output)
        if output["definition"] not in definition_ids:
            raise ValueError("output has no source-bound selection/observable definition")
    if len({o["name"] for o in outputs}) != len(outputs):
        raise ValueError("duplicate requested output")
    checks = specification["checks"]
    if not isinstance(checks, list):
        raise ValueError("checks must be a list; missing checks remain obligations")
    seen = set()
    for check in checks:
        if not isinstance(check, dict) or check.get("kind") not in KINDS or check["kind"] in seen:
            raise ValueError("unknown or duplicate admission check")
        seen.add(check["kind"])
        if check.get("method") == "receipt":
            _keys(check, {"kind", "method", "artifact"}, "receipt check")
            if check["artifact"] not in ids:
                raise ValueError("check receipt points to unknown artifact")
        elif check.get("method") == "build-receipt" and check["kind"] == "build":
            _keys(check, {"kind", "method", "artifact", "plan", "capsule", "binary"}, "build receipt check")
            if not {check[k] for k in ("artifact", "plan", "capsule", "binary")} <= ids:
                raise ValueError("build check points to unknown plan/capsule/output artifact")
        elif check.get("method") == "graph-model" and check["kind"] == "independent-review":
            _keys(check, {"kind", "method", "graph", "node_id", "subject", "packet_sha256"}, "host model check")
            _text(check["graph"], "host graph path"); _text(check["node_id"], "host node identity")
            if not Path(check["graph"]).is_absolute():
                raise ValueError("host graph root must be an explicit absolute path")
            _hash(check["packet_sha256"])
            if check["subject"] not in ids:
                raise ValueError("host review subject is not a bound artifact")
        elif check.get("method") == "comparison" and check["kind"] == "reference":
            _keys(check, {"kind", "method", "prediction", "reference", "criteria"}, "reference comparison")
            if check["prediction"] not in ids or check["reference"] not in ids or check["prediction"] == check["reference"]:
                raise ValueError("comparison needs distinct bound prediction/reference artifacts")
            _keys(check["criteria"], {"atol", "rtol"}, "prospective comparison criteria")
            for key, value in check["criteria"].items():
                _number(value, key, nonnegative=True)
        else:
            raise ValueError("unsupported admission evidence method")
    return specification


def validate(task):
    _keys(task, {"specification"}, "admission task")
    _text(task["specification"], "specification path")


def _load(task, base):
    validate(task)
    path = regular(task["specification"], base)
    specification = validate_specification(read_json(path))
    paths = {a["id"]: regular(a["path"], path.parent) for a in specification["artifacts"]}
    for artifact in specification["artifacts"]:
        if hashlib.sha256(paths[artifact["id"]].read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("changed artifact: " + artifact["id"])
    return path, specification, paths


def inputs(task, base):
    path, specification, paths = _load(task, base)
    files = [path, *paths.values()]
    for check in specification["checks"]:
        if check["method"] == "build-receipt":
            from ravel.physics.routine_build import inputs as build_inputs
            plan = read_json(paths[check["plan"]])
            receipt = read_json(paths[check["artifact"]])
            files += build_inputs({"backend": "routine-build", "input": plan["input"]["path"]}, plan["base_dir"])
            out = paths[check["artifact"]].parent
            files += [regular("source-inventory.json", out), *[regular(f["path"], out) for f in receipt["logs"].values()]]
            files += [regular(str(out / "work/source" / f["path"]), out) for f in plan["source_inventory"]["files"]]
            _build(check, specification, paths)
        elif check["method"] == "graph-model":
            graph = Path(check["graph"])
            graph_spec = read_json(regular("graph_spec.json", graph))
            files += [regular(str(p), graph) for p in graph.rglob("*") if p.is_file() and p.name != "state.lock"]
            for node in graph_spec["nodes"]:
                files += [regular(pin["path"], graph) for pin in node["inputs"]]
                if node["packet"]:
                    packet = Path(node["packet"]["path"])
                    files += [regular(str(p), packet) for p in packet.rglob("*") if p.is_file()]
    return list(dict.fromkeys(files))


def _binding(specification):
    ids = set(specification["subjects"])
    ids.update(d["artifact"] for d in specification["definitions"])
    return {a["id"]: a["sha256"] for a in specification["artifacts"] if a["id"] in ids}


def review_subject(specification):
    """Public source-only subject to freeze in a fresh critic/verifier role packet."""
    validate_specification(specification)
    check_basis = [c for c in specification["checks"] if c["kind"] != "independent-review"]
    identities = set(specification["subjects"])
    identities.update(d["artifact"] for d in specification["definitions"])
    for check in check_basis:
        identities.update(check[key] for key in ("artifact", "plan", "capsule", "binary", "prediction", "reference")
                          if key in check)
    closure = {a["id"]: a["sha256"] for a in specification["artifacts"] if a["id"] in identities}
    return {"schema_version": 1, "kind": "analysis-review-subject",
            "analysis_id": specification["analysis_id"], "implementation": specification["implementation"],
            "request": specification["request"], "subjects": closure,
            "definitions": specification["definitions"], "outputs": specification["outputs"],
            "check_basis": check_basis}


def _receipt(check, specification, paths):
    receipt = read_json(paths[check["artifact"]])
    fields = {"schema_version", "kind", "check", "analysis_id", "scope_sha256", "request_sha256", "implementation_sha256",
                   "subjects", "definitions_sha256", "outputs_sha256", "status", "producer",
                   "method", "limitations"}
    if check["kind"] == "independent-review":
        fields.add("host_receipt")
    _keys(receipt, fields, "source-bound admission receipt")
    if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
            or receipt["kind"] != "analysis_check_receipt" or receipt["check"] != check["kind"]
            or receipt["analysis_id"] != specification["analysis_id"]
            or receipt["scope_sha256"] != _digest(specification["request"]["scope"])
            or receipt["request_sha256"] != _digest(specification["request"])
            or receipt["implementation_sha256"] != _digest(specification["implementation"])
            or receipt["subjects"] != _binding(specification)
            or receipt["definitions_sha256"] != _digest(specification["definitions"])
            or receipt["outputs_sha256"] != _digest(specification["outputs"])):
        raise ValueError("receipt is stale or describes another analysis/scope/output basis")
    if receipt["status"] not in {"passed", "failed", "blocked", "unknown"}:
        raise ValueError("unsupported receipt status")
    _keys(receipt["producer"], {"identity", "role", "context_id"}, "check producer")
    for value in receipt["producer"].values():
        _text(value, "check producer")
    _text(receipt["method"], "check method")
    _names(receipt["limitations"], "receipt limitations", empty=True)
    if check["kind"] == "independent-review" and receipt["producer"]["role"] != "independent-verifier":
        raise ValueError("independent review requires a distinct verifier role")
    if check["kind"] == "independent-review":
        host = receipt["host_receipt"]
        artifacts = {a["id"]: a for a in specification["artifacts"]}
        if host not in artifacts or artifacts[host]["role"] != "review-host":
            raise ValueError("independent review requires a separately bound host receipt")
    status, limitations = receipt["status"], list(receipt["limitations"])
    if check["kind"] == "independent-review" and status == "passed":
        # A caller's role/host-artifact label is not an executed host observation.
        # Until the live host verifier supplies subject+response+invocation custody,
        # this junction remains unresolved even with a correctly hashed assertion.
        status = "unknown"
        limitations.append("Bound host bytes have not been verified as an actual invocation/response on the current subject packet.")
    return {"kind": check["kind"], "status": status, "method": "supplied-bound-receipt",
            "producer": receipt["producer"], "limitations": limitations,
            "host_invocation_verified": False if check["kind"] == "independent-review" else None}


def _values(path, specification, *, prediction):
    values = read_json(path)
    _keys(values, {"schema_version", "kind", "analysis_id", "scope_sha256", "request_sha256", "implementation_sha256", "definitions_sha256", "subjects",
                   "source", "outputs"}, "analysis reference values")
    if (type(values["schema_version"]) is not int or values["schema_version"] != 1
            or values["kind"] != "analysis_reference_values"
            or values["analysis_id"] != specification["analysis_id"]
            or values["scope_sha256"] != _digest(specification["request"]["scope"])
            or values["request_sha256"] != _digest(specification["request"])
            or values["implementation_sha256"] != _digest(specification["implementation"])
            or values["definitions_sha256"] != _digest(specification["definitions"])):
        raise ValueError("reference values have a different analysis or physical scope")
    _text(values["source"], "comparison source")
    if prediction and values["subjects"] != _binding(specification):
        raise ValueError("prediction was not calculated from the bound current subjects")
    if not isinstance(values["subjects"], dict) or not values["subjects"]:
        raise ValueError("comparison needs attributable physical source identities")
    artifacts = {a["id"]: a["sha256"] for a in specification["artifacts"]}
    for identity, digest in values["subjects"].items():
        if identity not in artifacts or artifacts[identity] != _hash(digest):
            raise ValueError("comparison source identity is fictional, stale or unbound")
    rows = values["outputs"]
    if not isinstance(rows, list) or len(rows) != len(specification["outputs"]):
        raise ValueError("comparison omitted requested outputs")
    result = {}
    expected = {o["name"]: o for o in specification["outputs"]}
    for row in rows:
        _keys(row, {"basis", "value"}, "comparison output")
        _output(row["basis"])
        name = row["basis"]["name"]
        if name in result or name not in expected or row["basis"] != expected[name]:
            raise ValueError("comparison output basis differs, is duplicate or unrequested")
        result[name] = _number(row["value"], "reference value")
    return result


def _compare(check, specification, paths):
    actual = _values(paths[check["prediction"]], specification, prediction=True)
    reference = _values(paths[check["reference"]], specification, prediction=False)
    atol, rtol = check["criteria"]["atol"], check["criteria"]["rtol"]
    rows = []
    for name in sorted(actual):
        difference = _number(actual[name] - reference[name], "derived comparison difference")
        tolerance = _number(atol + rtol * abs(reference[name]), "derived comparison tolerance", nonnegative=True)
        rows.append({"name": name, "prediction": actual[name], "reference": reference[name],
                     "difference": difference, "tolerance": tolerance,
                     "passed": abs(difference) <= tolerance})
    return {"kind": "reference", "status": "passed" if all(r["passed"] for r in rows) else "failed",
            "method": "complete-bound-output-comparison", "outputs": rows,
            "criteria": check["criteria"], "limitations": [
                "Numerical comparison does not independently verify the reference extraction or detector response.",
                "These prospective thresholds are supplied scientific criteria, not inferred confidence intervals."]}


def _build(check, specification, paths):
    """Consume the actual direct builder's read-only custody verifier."""
    from ravel.physics.routine_build import verify_receipt
    plan_path, capsule_path = paths[check["plan"]], paths[check["capsule"]]
    plan, receipt = read_json(plan_path), read_json(paths[check["artifact"]])
    implementation = specification["implementation"]
    if (implementation["artifact"] != check["capsule"] or plan["routine"] != implementation["routine"]
            or plan["framework"] != implementation["framework"]):
        raise ValueError("build receipt belongs to a different declared implementation")
    if regular(plan["source_capsule"]["path"], plan_path.parent) != capsule_path:
        raise ValueError("build check capsule differs from the actual plan")
    out = paths[check["artifact"]].parent
    if regular(receipt["binary"]["path"], out) != paths[check["binary"]]:
        raise ValueError("build check binary differs from actual receipt output")
    verified = verify_receipt(receipt, plan, plan["base_dir"], out)
    return {"kind": "build", "status": "passed", "method": "observed-build-receipt",
            "verification": verified, "limitations": [
                "Build/probe custody does not authenticate a supplied stage or calibrate physical response."]}


def _graph(check, specification, paths):
    from ravel.workflow.agent_graph import model_receipt
    subject_path = paths[check["subject"]]
    if read_json(subject_path) != review_subject(specification):
        raise ValueError("host review subject does not describe the current request/implementation/definitions/output basis")
    subject_sha = hashlib.sha256(subject_path.read_bytes()).hexdigest()
    host = model_receipt(check["graph"], check["node_id"], expected_subject_sha256=subject_sha,
                         expected_packet_sha256=check["packet_sha256"], require_exact_subject=True)
    if host.get("exact_subject_presented") is not True:
        raise ValueError("actual host packet does not present the exact current full subject bytes")
    result = {"kind": "independent-review", "status": "unknown", "method": "observed-graph-model",
              "producer": {"identity": host["node_id"], "role": "independent-verifier",
                           "context_id": host["request_id"]}, "host": host,
              "host_invocation_verified": False, "limitations": list(host["limitations"])}
    if (host["execution_observation"] not in {"remote_transport_observed", "local_transport_observed", "host_attested_external"}
            or host["context_transport_separated"] is not True):
        result["limitations"].append("A control/unestablished transport or nonseparated context cannot close independent review.")
        return result
    value = host.get("public_value")
    if value is None:
        result["limitations"].append("Actual host public verdict has not been supplied by the verified graph API.")
        return result
    if host.get("public_value_sha256") != _digest(value):
        raise ValueError("public host response differs from its actual result digest")
    _keys(value, {"schema_version", "kind", "analysis_id", "subject_sha256", "status", "findings", "limitations"}, "host analysis review verdict")
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["kind"] != "analysis_review_verdict" or value["analysis_id"] != specification["analysis_id"]
            or value["subject_sha256"] != subject_sha):
        raise ValueError("actual host verdict refers to another analysis or scientific subject")
    if value["status"] not in {"passed", "failed", "blocked", "unknown"}:
        raise ValueError("invalid actual host verdict status")
    if not isinstance(value["findings"], list):
        raise ValueError("actual host verdict needs its full findings denominator")
    _names(value["limitations"], "actual host limitations", empty=True)
    seen = set()
    for finding in value["findings"]:
        _keys(finding, {"id", "summary"}, "host finding")
        name = _text(finding["id"], "host finding identity")
        _text(finding["summary"], "host finding summary")
        if name in seen:
            raise ValueError("duplicate actual host finding")
        seen.add(name)
    result.update(status="blocked" if value["findings"] else value["status"], host_invocation_verified=True,
                  findings=value["findings"], limitations=[*result["limitations"], *value["limitations"]])
    return result


def assess(task, base):
    path, specification, paths = _load(task, base)
    checks = []
    for check in specification["checks"]:
        try:
            operation = {"receipt": _receipt, "comparison": _compare, "graph-model": _graph}
            checks.append(_build(check, specification, paths) if check["method"] == "build-receipt"
                          else operation[check["method"]](check, specification, paths))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            checks.append({"kind": check["kind"], "status": "failed", "reason": str(exc)})
    by_kind = {c["kind"]: c for c in checks}
    required = requirements(specification)
    obligations = [{"kind": name, "status": by_kind.get(name, {}).get("status", "unknown")}
                   for name in required if by_kind.get(name, {}).get("status") != "passed"]
    # Supplied receipts cannot establish context independence by role spelling.
    verifier = by_kind.get("independent-review", {}).get("producer")
    if verifier and any((c.get("producer", {}).get("context_id") == verifier["context_id"]
                         or c.get("producer", {}).get("identity") == verifier["identity"])
                        for c in checks if c["kind"] != "independent-review"):
        obligations.append({"kind": "independent-review", "status": "failed",
                            "reason": "verifier reused another check's producer identity or context"})
    extra_failures = [c for c in checks if c["status"] != "passed" and c["kind"] not in required]
    obligations += [{"kind": c["kind"], "status": c["status"], "reason": "material supplied check did not pass"}
                    for c in extra_failures]
    return {"schema_version": 1, "kind": "analysis_admission_report", "analysis_id": specification["analysis_id"],
            "request": specification["request"], "specification_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "required_checks": required, "checks": checks, "obligations": obligations,
            "evidence_complete": not obligations, "physics_validated": False,
            "admitted_action": "inspect-source-bound-evidence",
            "admitted_claim": "complete census of scoped supplied evidence" if not obligations else "unresolved scoped evidence",
            "scientific_certification": "requires-authoritative-review",
            "status": "evidence-complete" if not obligations else "blocked",
            "limitations": ["This is evidence admission, not automatic physics certification or permission to execute.",
                "Receipt identity/custody and role separation do not authenticate scientific premises or host isolation.",
                "Support is restricted to the bound request, inputs, definitions, outputs and applicability scope."]}


def run(task, base, out):
    result = assess(task, base)
    atomic_json(Path(out) / "analysis-admission.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--specification", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess({"specification": str(args.specification)}, Path.cwd())
        if args.out:
            atomic_json(args.out, result)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result["evidence_complete"] else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
