"""Bounded, read-only evaluation of prospective scientific contrast contracts.

The engine checks evidence and declared criteria; it does not certify physics or
authorize compute. A contradicted hypothesis can be a useful scientific outcome.
Intervals are supplied-moment diagnostic envelopes, without coverage claims.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

from .execution import digest, file_hash


def keys(value, required, label):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError(f"{label} requires exactly {sorted(required)}")


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonblank trimmed string")
    return value


def number(value, label):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite and numeric")
    return float(value)


def integer(value, label, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f"{label} must be an integer >= {0 if zero else 1}")


def unique(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a nonempty list")
    for value in values:
        text(value, label)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


def binding(value):
    keys(value, {"path", "sha256"}, "artifact binding")
    text(value["path"], "artifact path")
    sha = value["sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("artifact sha256 must be lowercase hexadecimal")


def bound_file(pin, base_dir):
    binding(pin)
    path = Path(pin["path"]).expanduser()
    path = path if path.is_absolute() else Path(base_dir) / path
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError(f"artifact must be a regular file without symlinks: {pin['path']}")
    if file_hash(path) != pin["sha256"]:
        raise ValueError(f"artifact bytes changed: {pin['path']}")
    return path.resolve()


def read_json(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out
    def constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=constant)


def pointer(value, path):
    if path == "":
        return value
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("field pointer must be an RFC6901 JSON pointer")
    for part in path[1:].split("/"):
        # Reject Python's negative/leading-zero indexes and malformed escapes;
        # otherwise a purported field pointer can silently name another field.
        if any(part[i + 1:i + 2] not in ("0", "1") for i, char in enumerate(part) if char == "~"):
            raise ValueError("malformed RFC6901 pointer escape")
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isascii() or not part.isdecimal() or (len(part) > 1 and part.startswith("0")):
                raise ValueError("JSON pointer array index must be canonical nonnegative decimal")
            value = value[int(part)]
        else:
            value = value[part]
    return value


def basis(value):
    keys(value, {"quantity", "unit", "normalization", "role", "definition", "channels"}, "comparison basis")
    for key in set(value) - {"channels"}:
        text(value[key], "basis " + key)
    unique(value["channels"], "basis channels")


def validate(plan):
    keys(plan, {"schema_version", "source", "question", "manipulation", "fixed_artifacts", "comparison",
                "hypotheses", "precision", "data_use", "budget", "stopping", "applicability", "capacity"}, "diagnostic plan")
    if type(plan["schema_version"]) is not int or plan["schema_version"] not in (1, 2):
        raise ValueError("diagnostic schema_version must be integer 1 or 2")
    for key in ("source", "question"):
        text(plan[key], key)
    keys(plan["manipulation"], {"variable", "baseline", "candidate"}, "manipulation")
    for key, value in plan["manipulation"].items():
        text(value, "manipulation " + key)
    if not isinstance(plan["fixed_artifacts"], list) or not plan["fixed_artifacts"]:
        raise ValueError("at least one fixed source artifact is required")
    for pin in plan["fixed_artifacts"]:
        binding(pin)
    comp = plan["comparison"]
    if type(comp) is not dict:
        raise ValueError("comparison must be an object")
    comparison_keys = {"kind", "baseline", "candidate", "basis", "require_complete_exposure"}
    if plan["schema_version"] == 2 and comp.get("kind") == "independent":
        comparison_keys.add("uncertainty_relationship")
    keys(comp, comparison_keys, "comparison")
    if comp["kind"] not in ("paired_events", "independent") or comp["require_complete_exposure"] is not True:
        raise ValueError("comparison requires paired_events/independent and complete exposure")
    for role in ("baseline", "candidate"):
        binding(comp[role])
    basis(comp["basis"])
    if "uncertainty_relationship" in comp:
        relationship = comp["uncertainty_relationship"]
        if type(relationship) is not dict:
            raise ValueError("uncertainty relationship must be an object")
        status = relationship.get("status")
        if status == "unavailable":
            keys(relationship, {"status", "reason"}, "unavailable uncertainty relationship")
            text(relationship["reason"], "uncertainty relationship reason")
        elif status in ("uncorrelated", "supplied"):
            keys(relationship, {"status", "artifact"}, "bound uncertainty relationship")
            binding(relationship["artifact"])
        else:
            raise ValueError("uncertainty relationship status must be unavailable/uncorrelated/supplied")
    if not isinstance(plan["hypotheses"], list) or not plan["hypotheses"]:
        raise ValueError("at least one hypothesis is required")
    ids = []
    covered = set()
    for hypothesis in plan["hypotheses"]:
        keys(hypothesis, {"id", "statement", "channels", "direction", "relative_tolerance"}, "hypothesis")
        ids.append(text(hypothesis["id"], "hypothesis id"))
        text(hypothesis["statement"], "hypothesis statement")
        unique(hypothesis["channels"], "hypothesis channels")
        if not set(hypothesis["channels"]) <= set(comp["basis"]["channels"]):
            raise ValueError("hypothesis names an unknown channel")
        covered.update(hypothesis["channels"])
        if hypothesis["direction"] not in ("equivalent", "increase", "decrease"):
            raise ValueError("direction must be equivalent/increase/decrease")
        if number(hypothesis["relative_tolerance"], "relative tolerance") < 0:
            raise ValueError("relative tolerance must be nonnegative")
    unique(ids, "hypothesis ids")
    if covered != set(comp["basis"]["channels"]):
        raise ValueError("every declared channel needs a hypothesis; aggregate agreement cannot hide shape changes")
    precision = plan["precision"]
    keys(precision, {"max_relative_mc_error", "envelope_sigma", "reference_covariance"}, "precision")
    if not 0 < number(precision["max_relative_mc_error"], "MC precision") <= 1:
        raise ValueError("max_relative_mc_error must be in (0,1]")
    if not 0 < number(precision["envelope_sigma"], "envelope sigma") <= 10:
        raise ValueError("envelope_sigma must be in (0,10]")
    if precision["reference_covariance"] not in ("required", "exact_reference"):
        raise ValueError("reference_covariance must be required or exact_reference")
    if not isinstance(plan["data_use"], list) or not plan["data_use"]:
        raise ValueError("data-use history is required")
    populations, artifacts = defaultdict(set), defaultdict(set)
    for use in plan["data_use"]:
        keys(use, {"population_id", "role", "artifact"}, "data-use record")
        population = text(use["population_id"], "population id")
        if use["role"] not in ("calibration", "validation"):
            raise ValueError("data role must be calibration or validation")
        binding(use["artifact"])
        populations[population].add(use["role"])
        artifacts[use["artifact"]["sha256"]].add(use["role"])
    if any(len(roles) > 1 for roles in [*populations.values(), *artifacts.values()]):
        raise ValueError("calibration and validation reuse the same declared population or artifact bytes")
    keys(plan["budget"], {"max_attempts", "max_seconds", "max_new_events"}, "budget")
    integer(plan["budget"]["max_attempts"], "attempt budget")
    integer(plan["budget"]["max_seconds"], "time budget")
    integer(plan["budget"]["max_new_events"], "event budget", zero=True)
    keys(plan["stopping"], {"success", "failure", "unresolved"}, "stopping")
    if plan["stopping"] != {"success": "all_criteria_supported", "failure": "any_criterion_contradicted",
                            "unresolved": "stop_without_conclusion"}:
        raise ValueError("stopping policy must preserve contradicted and unresolved outcomes")
    keys(plan["applicability"], {"status", "reason"}, "applicability")
    if plan["applicability"]["status"] not in ("established", "unresolved"):
        raise ValueError("applicability must be established or unresolved")
    text(plan["applicability"]["reason"], "applicability reason")
    if plan["capacity"] is not None:
        keys(plan["capacity"], {"artifact", "lower_pointer", "upper_pointer", "target_pointer", "reason"}, "capacity")
        binding(plan["capacity"]["artifact"])
        for key in ("lower_pointer", "upper_pointer", "target_pointer"):
            text(plan["capacity"][key], key)
        text(plan["capacity"]["reason"], "capacity reason")
    return json.loads(json.dumps(plan, allow_nan=False))


def _matrix(value, size):
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != size or any(not isinstance(row, list) or len(row) != size for row in value):
        raise ValueError("covariance dimensions do not match declared channels")
    import numpy as np
    matrix = np.asarray([[number(x, "covariance") for x in row] for row in value])
    scale = max(float(abs(matrix).max()), 1e-300)
    if not np.allclose(matrix, matrix.T, rtol=0, atol=1e-12 * scale):
        raise ValueError("covariance is not symmetric")
    eigenvalues = np.linalg.eigvalsh(matrix)
    if not np.isfinite(eigenvalues).all():
        raise ValueError("covariance eigensystem is not finite")
    if float(eigenvalues.min()) < -1e-12 * scale:
        raise ValueError("covariance is not positive semidefinite")
    return matrix.tolist()


def _independent_covariance(comp, left, right, base_dir):
    """Never infer zero cross covariance from distinct population/file identities.

    Version 1 did not bind an uncertainty relationship. It remains readable as
    historical evidence, with that relationship explicitly unavailable.
    """
    relationship = comp.get("uncertainty_relationship", {
        "status": "unavailable", "reason": "Legacy schema version 1 has no bound uncertainty relationship."})
    if relationship["status"] == "unavailable":
        return None, None, {**relationship, "scope": "No zero cross covariance inferred."}
    pin = relationship["artifact"]
    source = read_json(bound_file(pin, base_dir))
    keys(source, {"schema_version", "kind", "status", "rationale", "basis", "baseline", "candidate",
                  "cross_covariance"}, "uncertainty relationship evidence")
    if type(source["schema_version"]) is not int or source["schema_version"] != 1:
        raise ValueError("uncertainty relationship evidence schema_version must be integer 1")
    if source["kind"] != "uncertainty_relationship" or source["status"] != relationship["status"]:
        raise ValueError("uncertainty relationship evidence differs from the declared disposition")
    text(source["rationale"], "uncertainty relationship rationale")
    basis(source["basis"])
    for role in ("baseline", "candidate"):
        binding(source[role])
        if source[role] != comp[role]:
            raise ValueError("uncertainty relationship evidence binds a different comparison artifact")
    if source["basis"] != comp["basis"]:
        raise ValueError("uncertainty relationship evidence binds a different comparison basis")
    size = len(comp["basis"]["channels"])
    if relationship["status"] == "uncorrelated":
        if source["cross_covariance"] is not None:
            raise ValueError("uncorrelated assumption cannot conceal supplied cross covariance")
        cross = [[0.0] * size for _ in range(size)]
        scope = "Source-bound uncorrelated assumption; independence is not established by file hashes."
    else:
        raw = source["cross_covariance"]
        if (not isinstance(raw, list) or len(raw) != size or
                any(not isinstance(row, list) or len(row) != size for row in raw)):
            raise ValueError("cross covariance dimensions do not match declared channels")
        cross = [[number(value, "cross covariance") for value in row] for row in raw]
        scope = "Supplied cross covariance; no uncertainty relationship inferred from population labels."
    description = {"status": relationship["status"], "artifact": pin,
                   "rationale": source["rationale"], "scope": scope}
    # Validate the joint block, not the cross block: the latter need not be
    # symmetric or positive semidefinite, including negative shared responses.
    if left is None or right is None:
        return None, cross, description
    joint = [lrow + crow for lrow, crow in zip(left, cross)]
    joint += [[cross[j][i] for j in range(size)] + right[i] for i in range(size)]
    _matrix(joint, 2 * size)
    difference = [[number(left[i][j] + right[i][j] - cross[i][j] - cross[j][i],
                          "contrast covariance") for j in range(size)] for i in range(size)]
    bound_file(pin, base_dir)
    return _matrix(difference, size), cross, description


def _dataset(value, expected_basis, kind):
    common = {"schema_version", "kind", "basis", "population_id", "expected_exposure", "uncertainty_scope"}
    fields = {"actual_exposure", "values", "covariance", "covariance_status"} if kind == "independent" else {"records", "scale"}
    keys(value, common | fields, "contrast dataset")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("dataset schema_version must be integer 1")
    if value["kind"] != ("estimates" if kind == "independent" else "events"):
        raise ValueError("dataset kind differs from comparison")
    basis(value["basis"])
    if value["basis"] != expected_basis:
        raise ValueError("dataset comparison basis/channels/observed-expected role differs")
    text(value["population_id"], "dataset population")
    text(value["uncertainty_scope"], "uncertainty scope")
    integer(value["expected_exposure"], "expected exposure")
    size = len(expected_basis["channels"])
    if kind == "independent":
        integer(value["actual_exposure"], "actual exposure")
        if value["actual_exposure"] != value["expected_exposure"]:
            raise ValueError("partial or unexpected event exposure")
        if not isinstance(value["values"], list) or len(value["values"]) != size:
            raise ValueError("missing or unexpected channel estimates")
        values = [number(x, "estimate") for x in value["values"]]
        covariance = _matrix(value["covariance"], size)
        if value["covariance_status"] not in ("supplied", "unavailable", "exact"):
            raise ValueError("unknown covariance status")
        if (covariance is None) != (value["covariance_status"] == "unavailable"):
            raise ValueError("covariance status does not describe supplied covariance")
        if value["covariance_status"] == "exact" and any(x != 0 for row in covariance for x in row):
            raise ValueError("exact quantity has nonzero covariance")
        return values, covariance, None
    scale = number(value["scale"], "event scale")
    if scale <= 0:
        raise ValueError("event scale must be positive")
    records = value["records"]
    if not isinstance(records, list) or len(records) != value["expected_exposure"]:
        raise ValueError("partial or unexpected event exposure")
    events, groups = {}, defaultdict(list)
    for record in records:
        keys(record, {"event_id", "group_id", "weight", "bins"}, "paired event")
        event_id = text(record["event_id"], "event ID")
        text(record["group_id"], "group ID")
        if event_id in events:
            raise ValueError("duplicate event ID")
        weight = number(record["weight"], "original weight")
        if not isinstance(record["bins"], list) or len(record["bins"]) != size:
            raise ValueError("event bins differ from channel population")
        vector = [number(weight * scale * number(x, "bin contribution"), "weighted contribution") for x in record["bins"]]
        events[event_id] = (record["group_id"], weight, vector)
        groups[record["group_id"]].append(vector)
    vectors = [[math.fsum(v[i] for v in group) for i in range(size)] for group in groups.values()]
    values = [math.fsum(v[i] for v in vectors) for i in range(size)]
    covariance = [[math.fsum(v[i] * v[j] for v in vectors) for j in range(size)] for i in range(size)]
    return values, _matrix(covariance, size), events


def evaluate(plan, base_dir="."):
    """Evaluate only supplied, pinned evidence. Never run generators or fitters."""
    plan = validate(plan)
    outcomes, checks, capacity = [], [], None
    result = {"schema_version": 1, "kind": "controlled_diagnostic", "plan_sha256": digest(plan),
              "review_required": True, "physics_validated": False, "criterion_outcomes": outcomes,
              "integrity_checks": checks, "capacity": None, "budget": plan["budget"],
              "limitations": ["No compute authorization or paper-reproduction certificate.",
                              "Diagnostic moment envelopes do not establish statistical coverage.",
                              "Declared population identities and fixed-variable semantics require scientific review."]}
    try:
        pins = [*plan["fixed_artifacts"], *[x["artifact"] for x in plan["data_use"]]]
        for pin in pins:
            bound_file(pin, base_dir)
        comp = plan["comparison"]
        data = [read_json(bound_file(comp[role], base_dir)) for role in ("baseline", "candidate")]
        left, lcov, levents = _dataset(data[0], comp["basis"], comp["kind"])
        right, rcov, revents = _dataset(data[1], comp["basis"], comp["kind"])
        comparison_roles = []
        for value, role in zip(data, ("baseline", "candidate")):
            expected = comp[role]
            uses = [use for use in plan["data_use"] if use["population_id"] == value["population_id"]
                    and use["artifact"] == expected]
            if not uses:
                raise ValueError("each comparison dataset needs its own matching data-use binding")
            comparison_roles.append(uses[0]["role"])
        result["data_role_status"] = "exploratory_calibration" if "calibration" in comparison_roles else "declared_validation"
        if comp["kind"] == "independent":
            if data[0]["population_id"] == data[1]["population_id"] or comp["baseline"]["sha256"] == comp["candidate"]["sha256"]:
                raise ValueError("independent estimates reuse a declared population or identical artifact")
            delta_cov, cross_cov, relationship = _independent_covariance(comp, lcov, rcov, base_dir)
            result["cross_covariance"] = cross_cov
            result["uncertainty_relationship"] = relationship
            checks.append({"status": "unresolved" if relationship["status"] == "unavailable" else "supported",
                           "criterion": "bound_uncertainty_relationship",
                           "scope": relationship["scope"]})
        else:
            if data[0]["population_id"] != data[1]["population_id"] or set(levents) != set(revents):
                raise ValueError("paired comparison lacks identical complete event IDs/population")
            groups = defaultdict(list)
            for event_id, (group, weight, vector) in levents.items():
                other_group, other_weight, other = revents[event_id]
                if group != other_group or weight != other_weight:
                    raise ValueError("paired event original weights or correlation groups differ")
                groups[group].append([b-a for a,b in zip(vector,other)])
            size = len(left)
            vectors = [[math.fsum(v[i] for v in rows) for i in range(size)] for rows in groups.values()]
            delta_cov = [[math.fsum(v[i]*v[j] for v in vectors) for j in range(size)] for i in range(size)]
        delta_cov = _matrix(delta_cov, len(left))
        result["comparison_covariance"] = delta_cov
        checks.append({"status": "supported", "criterion": "source_bytes_basis_complete_exposure_and_population"})
        if plan["capacity"] is not None:
            record = plan["capacity"]
            source = read_json(bound_file(record["artifact"], base_dir))
            lo, hi, target = [number(pointer(source, record[key]), key) for key in ("lower_pointer", "upper_pointer", "target_pointer")]
            if lo > hi:
                raise ValueError("capacity bounds are reversed")
            capacity = {"lower": lo, "upper": hi, "target": target,
                        "status": "supported" if lo <= target <= hi else "contradicted", "reason": record["reason"]}
            result["capacity"] = capacity
        for hypothesis in plan["hypotheses"]:
            rows = []
            for channel in hypothesis["channels"]:
                i = comp["basis"]["channels"].index(channel)
                before, after = left[i], right[i]
                delta = number(after-before, "contrast difference")
                row = {"channel": channel, "baseline": before, "candidate": after, "difference": delta,
                       "relative_difference": number(delta / abs(before), "relative difference") if before else None,
                       "status": "unresolved", "envelope": None}
                reason = None
                if result["data_role_status"] == "exploratory_calibration":
                    reason = "Comparison uses calibration populations; an independent validation population is required for confirmation."
                elif plan["applicability"]["status"] == "unresolved":
                    reason = plan["applicability"]["reason"]
                elif lcov is None or rcov is None or delta_cov is None:
                    if result.get("uncertainty_relationship", {}).get("status") == "unavailable":
                        reason = "Uncertainty relationship is unavailable; cross covariance is not replaced by zero."
                    else:
                        reason = "Required supplied reference or candidate covariance is unavailable; not replaced by zero."
                elif plan["precision"]["reference_covariance"] == "exact_reference" and data[0].get("covariance_status") != "exact":
                    reason = "The declared exact reference has no explicit exact covariance evidence."
                elif before == 0 or after == 0:
                    reason = "Zero estimate has unresolved relative precision; no upper bound inferred."
                else:
                    relative_errors = [number(math.sqrt(max(0, cov[i][i]))/abs(v), "relative MC error")
                                       for cov,v in ((lcov,before),(rcov,after))]
                    row["relative_mc_errors"] = relative_errors
                    if max(relative_errors) > plan["precision"]["max_relative_mc_error"]:
                        reason = "Declared relative MC precision target is unmet."
                    else:
                        error = number(plan["precision"]["envelope_sigma"] * math.sqrt(max(0, delta_cov[i][i])), "contrast envelope width")
                        lo, hi = number(delta-error, "envelope lower"), number(delta+error, "envelope upper")
                        row["envelope"] = [lo,hi]
                        margin = number(abs(before)*hypothesis["relative_tolerance"], "hypothesis margin")
                        if hypothesis["direction"] == "equivalent":
                            row["status"] = "supported" if lo >= -margin and hi <= margin else "contradicted" if lo > margin or hi < -margin else "unresolved"
                        elif hypothesis["direction"] == "increase":
                            row["status"] = "supported" if lo > margin else "contradicted" if hi <= margin else "unresolved"
                        else:
                            row["status"] = "supported" if hi < -margin else "contradicted" if lo >= -margin else "unresolved"
                        reason = "Prespecified directional criterion on supplied-moment envelope."
                row["reason"] = reason
                rows.append(row)
            states = [row["status"] for row in rows]
            status = "contradicted" if "contradicted" in states else "unresolved" if "unresolved" in states else "supported"
            outcomes.append({"id": hypothesis["id"], "statement": hypothesis["statement"], "status": status, "channels": rows})
        states = [x["status"] for x in outcomes] + ([capacity["status"]] if capacity else [])
        relationship_pin = comp.get("uncertainty_relationship", {}).get("artifact")
        for pin in [*pins, comp["baseline"], comp["candidate"]] + ([plan["capacity"]["artifact"]] if plan["capacity"] else []) + ([relationship_pin] if relationship_pin else []):
            bound_file(pin, base_dir)
        result["status"] = "contradicted" if "contradicted" in states else "unresolved" if "unresolved" in states else "supported"
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
        checks.append({"status": "contradicted", "criterion": "evidence_integrity", "reason": str(exc)})
        result["status"] = "contradicted"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate(read_json(args.plan), args.plan.resolve().parent)
        rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(rendered)
        print(rendered, end="")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"diagnostic plan: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
