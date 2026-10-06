"""Artifact-bound reference comparisons, with policy pinned in the approved contract.

This certifies a declared comparison, not the truth of a publication, detector model,
or statistical coverage. References and dependencies are pinned BEFORE comparison;
predictions and served subjects are fingerprinted when the certificate is produced.
Live consumers also verify the existing CHECK-IN approval binding (integrity, not
human identity). Old reports remain readable but cannot grant new certification.

Portable source invocation: python scripts/run.py ravel.validation.certificates --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


KINDS = ("r5", "acceptance")
# These are annotations derived from a detached certificate, never scientific values.
ANNOTATIONS = {"r5_status", "r5_evidence", "r5_certificate", "certification"}


class CertificateError(ValueError):
    pass


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CertificateError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _finite_tree(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise CertificateError("non-finite JSON number")
    if isinstance(value, dict):
        for item in value.values():
            _finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            _finite_tree(item)
    return value


def read_json(path):
    try:
        return _finite_tree(json.loads(Path(path).read_text(), object_pairs_hook=_unique,
                                      parse_constant=lambda x: (_ for _ in ()).throw(
                                          CertificateError(f"non-finite JSON literal {x}"))))
    except RecursionError as exc:
        raise CertificateError("JSON nesting exceeds the supported depth") from exc


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _number(value, name, *, positive=False):
    try:
        valid = type(value) in (int, float) and math.isfinite(float(value)) and value >= 0
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise CertificateError(f"{name} must be a finite nonnegative number")
    if positive and value == 0:
        raise CertificateError(f"{name} must be positive")
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise CertificateError(f"{name} must be a nonblank string")
    return value


def _keys(value, required, optional=(), name="object"):
    if type(value) is not dict:
        raise CertificateError(f"{name} must be an object")
    missing, extra = set(required) - value.keys(), value.keys() - set(required) - set(optional)
    if missing or extra:
        raise CertificateError(f"{name}: missing={sorted(missing)}, unknown={sorted(extra)}")


def local_path(root, relative):
    """No traversal, absolute paths or symlink aliases in portable evidence bindings."""
    rel = _relative(relative)
    base = Path(root).resolve()
    path = base / rel
    if path != path.resolve() or not path.is_file():
        raise CertificateError(f"artifact absent or symlinked: {relative}")
    if not path.resolve().is_relative_to(base):
        raise CertificateError(f"artifact escapes run directory: {relative}")
    return path


def _relative(relative):
    _text(relative, "artifact path")
    rel = Path(relative)
    if rel.is_absolute() or "\\" in relative or any(p in ("", ".", "..") for p in relative.split("/")):
        raise CertificateError(f"artifact path must be relative without traversal: {relative}")
    return rel


def digest(path, *, scientific=False):
    if scientific:
        value = read_json(path)
        if not isinstance(value, dict):
            raise CertificateError("scientific JSON artifact must be an object")
        data = _canonical({k: v for k, v in value.items() if k not in ANNOTATIONS})
    else:
        data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


def binding(root, relative, *, scientific=False):
    return {"path": relative, "sha256": digest(local_path(root, relative), scientific=scientific),
            "mode": "scientific-json" if scientific else "bytes"}


def _check_binding(root, record, *, byte_only=False):
    _keys(record, ("path", "sha256"), ("mode",), "artifact binding")
    if record.get("mode", "bytes") not in ("bytes", "scientific-json"):
        raise CertificateError("unknown artifact digest mode")
    if byte_only and record.get("mode", "bytes") != "bytes":
        raise CertificateError("references, plans and dependencies require a full byte hash")
    if not isinstance(record["sha256"], str) or len(record["sha256"]) != 64 or any(
            c not in "0123456789abcdef" for c in record["sha256"]):
        raise CertificateError("artifact sha256 must be 64 lowercase hexadecimal characters")
    path = local_path(root, record["path"])
    if digest(path, scientific=record.get("mode") == "scientific-json") != record["sha256"]:
        raise CertificateError(f"changed artifact: {record['path']}")
    return path


def _pointer(value, pointer):
    if pointer == "":
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise CertificateError("record_pointer must be a JSON pointer")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(part)] if isinstance(value, list) and part.isdigit() else value[part]
        except (KeyError, IndexError, TypeError, ValueError):
            raise CertificateError(f"JSON pointer not found: {pointer}") from None
    return value


def _parameters(value):
    if type(value) is not dict or not value:
        raise CertificateError("parameters must be a nonempty object of numeric coordinates")
    for key, item in value.items():
        _text(key, "parameter name")
        _number(item, f"parameter {key}")
    return value


def _basis(value):
    if type(value) is not dict or not value:
        raise CertificateError("basis must be a nonempty object of explicit conventions")
    for key, item in value.items():
        _text(key, "basis key")
        _text(item, "basis convention")
    return value


def load_plan(root, pin, *, kind=None):
    path = _check_binding(root, pin, byte_only=True)
    plan = read_json(path)
    _keys(plan, ("schema_version", "kind", "analysis_id", "quantity", "units", "basis",
                 "policy", "dependencies", "subjects", "comparisons"), name="certification plan")
    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise CertificateError("certification plan schema_version must be integer 1")
    if plan["kind"] not in KINDS or (kind is not None and plan["kind"] != kind):
        raise CertificateError("certification plan kind mismatch")
    for field in ("analysis_id", "quantity", "units"):
        _text(plan[field], field)
    _basis(plan["basis"])
    policy = plan["policy"]
    _keys(policy, ("claim", "relative_tolerance"),
          ("max_relative_uncertainty", "sigma_factor"), "comparison policy")
    if policy["claim"] not in ("central-value", "precision"):
        raise CertificateError("claim must be central-value or precision; coverage/calibration requires a separate study")
    if _number(policy["relative_tolerance"], "relative_tolerance", positive=True) > 1:
        raise CertificateError("relative_tolerance must not exceed 1")
    if policy["claim"] == "precision":
        _number(policy.get("max_relative_uncertainty"), "max_relative_uncertainty", positive=True)
        _number(policy.get("sigma_factor"), "sigma_factor", positive=True)
    elif set(policy) != {"claim", "relative_tolerance"}:
        raise CertificateError("central-value policy cannot contain precision fields")
    if not isinstance(plan["dependencies"], list) or not plan["dependencies"]:
        raise CertificateError("plan needs at least one predeclared input/implementation dependency")
    seen = set()
    for item in plan["dependencies"]:
        _check_binding(root, item, byte_only=True)
        if item["path"] in seen:
            raise CertificateError("duplicate dependency")
        seen.add(item["path"])
    if not isinstance(plan["subjects"], list) or not plan["subjects"] or any(
            not isinstance(s, str) or not s.strip() for s in plan["subjects"]):
        raise CertificateError("subjects must name the served scientific output artifacts")
    if len(set(plan["subjects"])) != len(plan["subjects"]):
        raise CertificateError("duplicate subject")
    for subject in plan["subjects"]:
        _relative(subject)
    comparisons = plan["comparisons"]
    minimum = 2 if plan["kind"] == "r5" else 1
    if not isinstance(comparisons, list) or len(comparisons) < minimum:
        raise CertificateError(f"{plan['kind']} requires at least {minimum} planned comparisons")
    identities, coordinates, reference_rows = set(), set(), set()
    for item in comparisons:
        _keys(item, ("point_id", "parameters", "reference_id", "prediction", "reference"), name="comparison")
        identity = _text(item["point_id"], "point_id")
        if identity in identities:
            raise CertificateError("duplicate comparison point identity")
        identities.add(identity)
        parameters = _parameters(item["parameters"])
        if plan["kind"] == "r5" and "mass_gev" not in parameters:
            raise CertificateError("R5 parameters must explicitly identify mass_gev")
        coordinate = parameters.get("mass_gev") if plan["kind"] == "r5" else _canonical(parameters)
        if plan["kind"] == "r5" and coordinate in coordinates:
            raise CertificateError("R5 requires distinct parameter/mass points")
        coordinates.add(coordinate)
        _text(item["reference_id"], "reference_id")
        for side in ("prediction", "reference"):
            operand = item[side]
            _keys(operand, ("path", "record_pointer") + (("sha256",) if side == "reference" else ()), name=side)
            _relative(operand["path"])
            if not isinstance(operand["record_pointer"], str):
                raise CertificateError("record_pointer must be a string")
            if side == "reference":
                _check_binding(root, {"path": operand["path"], "sha256": operand["sha256"]}, byte_only=True)
                key = (operand["path"], operand["record_pointer"])
                if key in reference_rows:
                    raise CertificateError("duplicate reference row identity")
                reference_rows.add(key)
    return plan


def _point(root, operand, expected, plan, *, reference):
    document = read_json(local_path(root, operand["path"]))
    value = _pointer(document, operand["record_pointer"])
    required = ("point_id", "parameters", "analysis_id", "quantity", "units", "basis", "value")
    _keys(value, required + (("reference_id",) if reference else ()),
          ("uncertainty", "role", "node") + (() if reference else ("reference_id",)), "measurement point")
    for field in ("point_id", "parameters"):
        if value[field] != expected[field]:
            raise CertificateError(f"{expected['point_id']}: {field} mismatch in {'reference' if reference else 'prediction'}")
    _parameters(value["parameters"])
    for field in ("analysis_id", "quantity", "units", "basis"):
        if value[field] != plan[field]:
            raise CertificateError(f"{expected['point_id']}: {field} mismatch")
    if reference and value["reference_id"] != expected["reference_id"]:
        raise CertificateError(f"{expected['point_id']}: reference identity mismatch")
    if "node" in value and value["node"] != "exact":
        raise CertificateError("certification requires the exact planned reference point; interpolation needs its own validated policy")
    _number(value["value"], "measurement value", positive=reference)
    if not reference and isinstance(document, dict):
        producer = document.get("certification_producer")
        if producer is not None:
            _keys(producer, ("module", "sha256"), name="comparison producer")
            _text(producer["module"], "producer module")
            allowed = {"ravel.physics.shape_fit", "ravel.validation.certify_acceptance",
                       "ravel.validation.validate_cutflow"}
            if producer["module"] not in allowed:
                raise CertificateError("unknown comparison producer")
            from importlib.util import find_spec
            spec = find_spec(producer["module"])
            if spec is None or digest(spec.origin) != producer["sha256"]:
                raise CertificateError("comparison producer implementation changed")
        module = producer["module"] if producer else None
        shape = document.get("generator") == "shape_fit.py" or module == "ravel.physics.shape_fit"
        acceptance = module in ("ravel.validation.certify_acceptance", "ravel.validation.validate_cutflow") or "validation_points" in document
        if shape:
            if (module != "ravel.physics.shape_fit" or document.get("generator") != "shape_fit.py"
                    or value["quantity"] not in ("mu95_exp", "mu95_obs")):
                raise CertificateError("shape prediction needs current producer evidence and a mu95 quantity")
            primary = _number(document.get(value["quantity"]), "shape primary value")
            if primary != value["value"]:
                raise CertificateError("shape comparison value disagrees with the primary fitted limit")
            from ravel.limits import read_limits
            try:
                limits = read_limits(document, source="new")
                curve = limits.curve("observed" if value["quantity"] == "mu95_obs" else "expected")
                if curve.status in ("below_scan", "above_scan", "missing") or curve.value != primary:
                    raise ValueError("a scan bound or missing value is not a fitted comparison root")
            except ValueError as exc:
                raise CertificateError(f"shape primary limit representation is inconsistent: {exc}") from exc
        if acceptance:
            if module not in ("ravel.validation.certify_acceptance", "ravel.validation.validate_cutflow") or shape:
                raise CertificateError("acceptance prediction needs current producer evidence")
            if not isinstance(document.get("rows"), list) or any(type(row) is not dict for row in document["rows"]):
                raise CertificateError("acceptance report rows must be objects")
            matching = [row for row in document["rows"] if row.get("sr") == value.get("role")]
            if len(matching) != 1 or _number(matching[0].get("mine"), "acceptance primary value") != value["value"]:
                raise CertificateError("acceptance comparison disagrees with its unique computed SR row")
            if not str(matching[0].get("node", "")).startswith("grid node"):
                raise CertificateError("acceptance primary row is not an exact reference grid node")
    return value


def compare_plan(root, plan):
    rows = []
    for expected in plan["comparisons"]:
        prediction = _point(root, expected["prediction"], expected, plan, reference=False)
        reference = _point(root, expected["reference"], expected, plan, reference=True)
        mine, published = prediction["value"], reference["value"]
        residual = abs(mine / published - 1)
        if not math.isfinite(residual):
            raise CertificateError("comparison residual is not finite")
        tolerance = plan["policy"]["relative_tolerance"]
        row = {"point_id": expected["point_id"], "parameters": expected["parameters"],
               "reference_id": expected["reference_id"], "prediction": mine, "reference": published,
               "relative_residual": residual, "within_tolerance": residual <= tolerance}
        if plan["policy"]["claim"] == "precision":
            errors = []
            for point in (prediction, reference):
                unc = point.get("uncertainty")
                _keys(unc, ("standard", "source", "independence_group"), name="precision uncertainty")
                errors.append(_number(unc["standard"], "standard uncertainty"))
                _text(unc["source"], "uncertainty source")
                _text(unc["independence_group"], "uncertainty independence_group")
            if prediction["uncertainty"]["independence_group"] == reference["uncertainty"]["independence_group"]:
                raise CertificateError("correlated uncertainties are not supported by this precision policy")
            combined = math.hypot(*errors) / published
            if not math.isfinite(combined):
                raise CertificateError("combined relative uncertainty is not finite")
            row["combined_relative_uncertainty"] = combined
            row["within_tolerance"] = (combined <= plan["policy"]["max_relative_uncertainty"] and
                                       residual + plan["policy"]["sigma_factor"] * combined <= tolerance)
        rows.append(row)
    return rows


def _result(root, pin, plan):
    predictions = sorted({x["prediction"]["path"] for x in plan["comparisons"]})
    rows = compare_plan(root, plan)
    return {"schema_version": 1, "kind": plan["kind"], "plan": pin,
            "implementation_sha256": digest(__file__),
            "predictions": [binding(root, p, scientific=True) for p in predictions],
            "subjects": [binding(root, p, scientific=True) for p in plan["subjects"]],
            "comparisons": rows, "verdict": "PASS" if all(x["within_tolerance"] for x in rows) else "FAIL",
            "claim": plan["policy"]["claim"],
            "scope": "Declared central-value agreement; no detector or coverage certification" if
                     plan["policy"]["claim"] == "central-value" else
                     "Declared precision comparison with independent supplied standard uncertainties; no coverage certification"}


def create_certificate(root, plan_path, out_path):
    pin = {k: v for k, v in binding(root, plan_path).items() if k != "mode"}
    plan = load_plan(root, pin)
    record = _result(root, pin, plan)
    output = Path(root).resolve() / _relative(out_path)
    if output != output.resolve():
        raise CertificateError("certificate output cannot traverse a symlink")
    protected = {plan_path, "inputs/task_contract.json", *plan["subjects"],
                 *(x["path"] for x in record["predictions"]),
                 *(x["path"] for x in plan["dependencies"]),
                 *(x["reference"]["path"] for x in plan["comparisons"])}
    if out_path in protected or _relative(out_path).parts[0] == "inputs":
        raise CertificateError("certificate cannot overwrite an input or scientific artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
    return record


def measurement(context, value, *, quantity):
    """Attach explicit identity to a producer-computed value; never accept a supplied value."""
    required = ("point_id", "parameters", "analysis_id", "quantity", "units", "basis")
    _keys(context, required, ("reference_id", "uncertainty"), "measurement context")
    if context["quantity"] != quantity:
        raise CertificateError(f"measurement context quantity must be {quantity}")
    _parameters(context["parameters"])
    _basis(context["basis"])
    for key in ("point_id", "analysis_id", "units"):
        _text(context[key], key)
    return {**context, "value": _number(value, "producer measurement"), "node": "exact"}


def acceptance_points(rows, contexts):
    """Normalize exact computed SR values for an explicitly identified comparison plan."""
    if type(contexts) is not dict or set(contexts) != {row["sr"] for row in rows}:
        raise CertificateError("acceptance contexts must identify every reported SR exactly once")
    if len(rows) != len(contexts):
        raise CertificateError("duplicate acceptance SR")
    result = []
    for row in rows:
        point = measurement(contexts[row["sr"]], row["mine"], quantity="acceptance")
        point["node"] = "exact" if str(row.get("node", "")).startswith("grid node") else "unmatched"
        point["role"] = row["sr"]
        result.append(point)
    return result


def validate_certificate(root, path, *, kind, contract=None, required_subjects=(), live=False):
    """Return recomputed evidence or errors. Stored verdict/booleans never grant closure."""
    try:
        cert = read_json(local_path(root, path))
        _keys(cert, ("schema_version", "kind", "plan", "implementation_sha256", "predictions",
                     "subjects", "comparisons", "verdict", "claim", "scope"), name="certificate")
        if type(cert["schema_version"]) is not int or cert["schema_version"] != 1 or cert["kind"] != kind:
            raise CertificateError("certificate kind/version mismatch")
        if contract is not None:
            pin = (contract.get("certification_plans") or {}).get(kind)
            if pin != cert["plan"]:
                raise CertificateError(f"{kind} certificate policy/reference plan is not pinned by the current task contract")
        plan = load_plan(root, cert["plan"], kind=kind)
        if contract is not None and plan["analysis_id"] not in (contract.get("targets") or {}).get("analysis", []):
            raise CertificateError("certificate analysis identity does not match the task contract")
        for record in cert["predictions"] + cert["subjects"]:
            _check_binding(root, record)
        if not set(required_subjects).issubset(plan["subjects"]):
            raise CertificateError("certificate does not bind every current served output")
        if live:
            if contract is None:
                raise CertificateError("live certification needs the current approved task contract")
            from ravel.workflow import workflow_state
            actual = read_json(local_path(root, "inputs/task_contract.json"))
            if actual != contract:
                raise CertificateError("supplied contract differs from the approved run contract")
            errors = workflow_state.verify_approval(str(root))
            if errors:
                raise CertificateError("certification approval binding: " + "; ".join(errors))
        recomputed = _result(root, cert["plan"], plan)
        if _canonical(cert) != _canonical(recomputed):
            raise CertificateError("certificate differs from recomputed artifact comparisons or bindings")
        return {"status": recomputed["verdict"], "errors": [] if recomputed["verdict"] == "PASS" else
                ["one or more planned comparisons fail the approved policy"], "evidence": recomputed}
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        return {"status": "FAIL", "errors": [str(exc)], "evidence": None}


def validate_pack_certificates(rundir, exclusion_path, cert_path=None):
    """Validate live scientific authority before emitting a pack; no source mutation.

    Paths may be absolute inside the run or run-relative. The caller chooses whether
    it is assembling an archive with no live task contract; this function requires one.
    """
    from ravel.validation.validate_task_contract import validate
    from ravel.validation.validate_run_state import CERT_REQUIRED_STAT_MODES
    root = Path(rundir).resolve()
    contract = read_json(local_path(root, "inputs/task_contract.json"))
    errors = validate(contract)
    if errors:
        raise CertificateError("invalid live task contract: " + "; ".join(errors))

    def relative(path):
        value = Path(path)
        if value.is_absolute():
            value = value.relative_to(root)
        text = value.as_posix()
        local_path(root, text)
        return text

    subject = relative(exclusion_path)
    scientific = read_json(local_path(root, subject))
    requested = []
    if contract.get("stat_mode") == "shape-fit" or Path(subject).name in ("fold_result.json", "replane.json"):
        requested.append(("r5", scientific.get("r5_certificate") or "outputs/r5-certificate.json", [subject]))
    if contract.get("stat_mode") in CERT_REQUIRED_STAT_MODES:
        report = relative(cert_path) if cert_path else None
        report_doc = read_json(local_path(root, report)) if report else {}
        requested.append(("acceptance", report_doc.get("certification") or "outputs/acceptance-certificate.json",
                          [subject] + ([report] if report else [])))
    evidence = {}
    for kind, certificate, subjects in requested:
        result = validate_certificate(root, certificate, kind=kind, contract=contract,
                                      required_subjects=subjects, live=True)
        if result["status"] != "PASS":
            raise CertificateError(f"{kind} live certification: " + "; ".join(result["errors"]))
        evidence[kind] = {"path": certificate, "claim": result["evidence"]["claim"],
                          "scope": result["evidence"]["scope"]}
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "check", "pin-plan"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--rundir", required=True)
        if name in ("create", "pin-plan"):
            cmd.add_argument("--plan", required=True, help="relative path to the explicit comparison plan")
        if name == "create":
            cmd.add_argument("--out", required=True, help="detached certificate path relative to the run")
        if name == "check":
            cmd.add_argument("--certificate", required=True)
            cmd.add_argument("--kind", choices=KINDS, required=True)
            cmd.add_argument("--live", action="store_true", help="also require the current approval binding")
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            record = create_certificate(args.rundir, args.plan, args.out)
            print(json.dumps(record, indent=2))
            return 0 if record["verdict"] == "PASS" else 1
        if args.command == "pin-plan":
            pin = {k: v for k, v in binding(args.rundir, args.plan).items() if k != "mode"}
            plan = load_plan(args.rundir, pin)
            path = local_path(args.rundir, "inputs/task_contract.json")
            contract = read_json(path)
            contract.setdefault("certification_plans", {})[plan["kind"]] = pin
            from ravel.validation.validate_task_contract import validate
            errors = validate(contract)
            if errors:
                raise CertificateError("; ".join(errors))
            path.write_text(json.dumps(contract, indent=2) + "\n")
            print("Plan pinned. Existing approval is stale; record the actual renewed CHECK-IN approval before live serving.")
            return 0
        contract = read_json(local_path(args.rundir, "inputs/task_contract.json"))
        result = validate_certificate(args.rundir, args.certificate, kind=args.kind,
                                      contract=contract, live=args.live)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except (OSError, ValueError) as exc:
        parser.exit(2, f"certificates: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
