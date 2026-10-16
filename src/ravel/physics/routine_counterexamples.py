"""Finite synthetic boundary cases and independent-oracle disagreement reduction.

No rule is inferred from a candidate program. Thresholds, flow edges and overlap
radii must be supplied from a separately reconstructed rule or expert check.
These reconstructed-object cases do not represent a physical event sample or
truth-level decay histories. Oracle provenance is declared, not authenticated.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import re


KINDS = ("electron", "muon", "jet")
FIELDS = ("pt", "eta", "phi", "mass")
TEMPLATE = {"pt": 0.0, "eta": 0.0, "phi": 0.0, "mass": 0.0,
            "charge": 0, "idbits": 0}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _bound(value, lower, upper, label):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError("bounded " + label + " required")
    return value


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("finite supplied boundary required")
    try:
        converted = float(value)
    except OverflowError as exc:
        raise ValueError("finite supplied boundary required") from exc
    if not math.isfinite(converted):
        raise ValueError("finite supplied boundary required")
    return converted


def validate_event(event, max_objects=1024):
    """Validate the inert reconstructed-object transport without executing IR."""
    if type(event) is not dict or set(event) != {"event_id", "group_id", "weights", "objects", "met"}:
        raise ValueError("complete synthetic event required")
    for key in ("event_id", "group_id"):
        if type(event[key]) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", event[key]):
            raise ValueError("bounded synthetic event identity required")
    if type(event["weights"]) is not dict or not event["weights"]:
        raise ValueError("explicit synthetic weight streams required")
    if any(type(name) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,127}", name)
           for name in event["weights"]):
        raise ValueError("bounded string weight stream names required")
    for value in event["weights"].values():
        _number(value)
    if type(event["objects"]) is not dict or set(event["objects"]) != set(KINDS):
        raise ValueError("complete synthetic collections required")
    count = 0
    for kind in KINDS:
        rows = event["objects"][kind]
        if type(rows) is not list:
            raise ValueError("synthetic collection must be an array")
        count += len(rows)
        for row in rows:
            if type(row) is not dict or set(row) != set(TEMPLATE):
                raise ValueError("complete synthetic object required")
            values = {key: _number(row[key]) for key in FIELDS}
            if (values["pt"] < 0 or values["mass"] < 0
                    or abs(values["eta"]) > 20 or abs(values["phi"]) > math.pi):
                raise ValueError("synthetic object outside numerical domain")
            if type(row["charge"]) is not int or row["charge"] not in (-1, 0, 1):
                raise ValueError("synthetic object charge outside domain")
            if type(row["idbits"]) is not int or row["idbits"] < 0:
                raise ValueError("synthetic object flags outside domain")
    if count > max_objects:
        raise ValueError("synthetic object bound exceeded; truncation is forbidden")
    if type(event["met"]) is not dict or set(event["met"]) != {"pt", "phi"}:
        raise ValueError("explicit synthetic missing vector required")
    if _number(event["met"]["pt"]) < 0 or abs(_number(event["met"]["phi"])) > math.pi:
        raise ValueError("synthetic missing vector outside numerical domain")
    return event


def generate_boundary_events(seed, *, thresholds=(), multiplicities=(0, 1, 2),
                             overlap_radii=(), flow_edges=(), max_events=256,
                             max_objects=16, pairwise_edges=False):
    """Return deterministic cases with explicit category/edge labels.

    Threshold/flow records are ``collection, field, value``. A collection can
    also be ``met`` for its pt/phi fields. Edges use the adjacent binary64
    values as well as exact equality. Unrepresentable/domain-exterior neighbors
    are reported as refused rather than silently clipped or changed.
    ``pairwise_edges`` additionally probes every distinct supplied target pair
    at all nine adjacent/equal combinations. It is opt-in and does not combine
    multiplicity, ordering or overlap factors.
    All requested cases must fit: bounds never select a convenient prefix.
    """
    _bound(max_events, 1, 4096, "synthetic event count")
    _bound(max_objects, 2, 1024, "synthetic object count")
    validate_event(seed, max_objects)
    counts = list(multiplicities)
    if len(counts) > 32:
        raise ValueError("bounded multiplicity census required")
    for count in counts:
        _bound(count, 0, max_objects, "multiplicity")
    if type(pairwise_edges) is not bool:
        raise ValueError("explicit boolean pairwise edge option required")
    cases, refused, edges = [], [], []

    def emit(category, event, detail):
        row = deepcopy(event)
        identity = "synthetic-" + str(len(cases) + len(refused))
        row["event_id"] = row["group_id"] = identity
        try:
            validate_event(row, max_objects)
        except ValueError as exc:
            refused.append({"category": category, "detail": detail, "reason": str(exc)})
            return
        if len(cases) >= max_events:
            raise ValueError("complete boundary population exceeds event bound; truncation is forbidden")
        cases.append({"category": category, "detail": detail, "event": row})

    emit("seed", seed, "original synthetic seed")
    empty = deepcopy(seed)
    empty["objects"] = {kind: [] for kind in KINDS}
    emit("empty_collections", empty, "all collections empty")
    for category, records in (("threshold", thresholds), ("flow_bin", flow_edges)):
        records = list(records)
        if len(records) > 128:
            raise ValueError("bounded supplied edge census required")
        for edge in records:
            if type(edge) is not dict or set(edge) != {"collection", "field", "value"}:
                raise ValueError("explicit supplied edge fields required")
            kind, field = edge["collection"], edge["field"]
            if kind not in (*KINDS, "met") or field not in (("pt", "phi") if kind == "met" else FIELDS):
                raise ValueError("unsupported supplied boundary field")
            value = _number(edge["value"])
            edges.append((category, deepcopy(edge), value))
            for label, probe in (("below", math.nextafter(value, -math.inf)),
                                 ("equal", value), ("above", math.nextafter(value, math.inf))):
                event = deepcopy(seed)
                if kind == "met":
                    event["met"][field] = probe
                else:
                    if not event["objects"][kind]:
                        event["objects"][kind] = [deepcopy(TEMPLATE)]
                    event["objects"][kind][0][field] = probe
                emit(category, event, {**edge, "position": label})
    if pairwise_edges:
        for left_index, left in enumerate(edges):
            for right in edges[left_index + 1:]:
                # A scalar target cannot simultaneously occupy two edges.
                if (left[1]["collection"], left[1]["field"]) == (right[1]["collection"], right[1]["field"]):
                    continue
                for left_position, left_value in (("below", math.nextafter(left[2], -math.inf)),
                                                  ("equal", left[2]), ("above", math.nextafter(left[2], math.inf))):
                    for right_position, right_value in (("below", math.nextafter(right[2], -math.inf)),
                                                        ("equal", right[2]), ("above", math.nextafter(right[2], math.inf))):
                        event, detail = deepcopy(seed), []
                        for (category, edge, _), position, value in (
                                (left, left_position, left_value), (right, right_position, right_value)):
                            kind, field = edge["collection"], edge["field"]
                            if kind == "met":
                                event["met"][field] = value
                            else:
                                if not event["objects"][kind]:
                                    event["objects"][kind] = [deepcopy(TEMPLATE)]
                                event["objects"][kind][0][field] = value
                            detail.append({"category": category, **edge, "position": position})
                        emit("edge_pair", event, detail)
    for kind in KINDS:
        for count in counts:
            event = deepcopy(empty)
            template = seed["objects"][kind][0] if seed["objects"][kind] else TEMPLATE
            event["objects"][kind] = [deepcopy(template) for _ in range(count)]
            emit("multiplicity", event, {"collection": kind, "count": count})
        event = deepcopy(empty)
        a = deepcopy(seed["objects"][kind][0] if seed["objects"][kind] else TEMPLATE)
        b = {**a, "phi": -a["phi"] if a["phi"] else 0.5, "charge": -a["charge"]}
        event["objects"][kind] = [a, b]
        emit("ordering_tie", event, {"collection": kind, "order": "forward"})
        event["objects"][kind].reverse()
        emit("ordering_tie", event, {"collection": kind, "order": "reverse"})
    radii = list(overlap_radii)
    if len(radii) > 32:
        raise ValueError("bounded overlap radius census required")
    prototype = next((rows[0] for rows in seed["objects"].values() if rows), TEMPLATE)
    for radius in radii:
        radius = _number(radius)
        if not 0 <= radius < 20:
            raise ValueError("supported nonnegative overlap radius required")
        for label, probe in (("below", math.nextafter(radius, -math.inf)),
                             ("equal", radius), ("above", math.nextafter(radius, math.inf))):
            if probe < 0:
                refused.append({"category": "overlap_removal", "detail": label,
                                "reason": "negative separation outside domain"})
                continue
            event = deepcopy(empty)
            event["objects"]["electron"] = [{**prototype, "eta": 0.0, "phi": 0.0}]
            event["objects"]["jet"] = [{**prototype, "eta": probe, "phi": 0.0}]
            emit("overlap_removal", event, {"radius": radius, "position": label})
    for stream in seed["weights"]:
        for value in (-1.0, -0.0, 1.0):
            event = deepcopy(seed)
            event["weights"][stream] = value
            emit("signed_weight", event, {"stream": stream, "value": value})
    # Unusual visible configurations, not invented truth decay records.
    for charges in ((1, 1), (1, -1), (0, 0)):
        event = deepcopy(empty)
        event["objects"]["electron"] = [{**prototype, "eta": 0.0, "phi": 0.0, "charge": charge}
                                          for charge in charges]
        emit("visible_decay_configuration", event, {"charges": list(charges), "collinear": True})
    return {"cases": cases, "refused_cases": refused, "complete_requested_population": True,
            "physics_validated": False, "truth_decay_coverage": False,
            "limitations": [("Pairwise supplied scalar edges do not exhaust higher-order or other factor interactions."
                 if pairwise_edges else "One-factor cases do not exhaust interacting boundary combinations."),
                "Flow-edge inputs require a separately supplied output oracle; histogram filling is not implemented here.",
                "Visible charge and collinear configurations do not test truth ancestry or decay dynamics."]}


@dataclass(frozen=True)
class IndependentOracle:
    """Separately authored rules or expert evaluator; never a candidate replay.

    The evaluator takes only an event and returns regions and named observables.
    A source pin binds its declared basis; it does not authenticate authorship
    or prove implementation independence for an arbitrary Python callback.
    """
    evaluate: object
    source_capsule_sha256: str
    basis: str
    author: str
    kind: str = "source_reconstructed_rules"

    def validate(self):
        if (not callable(self.evaluate) or self.kind not in ("source_reconstructed_rules", "expert_check")
                or type(self.source_capsule_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", self.source_capsule_sha256)
                or any(type(value) is not str or not value.strip() or len(value) > 8000
                       for value in (self.basis, self.author))):
            raise ValueError("explicit independent oracle source, author and basis required")
        if getattr(self.evaluate, "__module__", "").startswith(
                ("ravel.physics.analysis_ir", "ravel.validation.analysis_witness", "ravel.physics.routine_candidate")):
            raise ValueError("candidate implementation replay cannot be an independent oracle")


def _finite_json(value, depth=0):
    """Reject coercions, opaque values, cycles and nonfinite nested numbers."""
    if depth > 64:
        raise ValueError("bounded finite JSON nesting required")
    if value is None or type(value) in (bool, str, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("finite JSON observable numbers required")
        return
    if type(value) is list:
        for item in value:
            _finite_json(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("string JSON observable keys required")
            _finite_json(item, depth + 1)
        return
    raise ValueError("finite JSON observables cannot contain opaque values")


def _equal_json(left, right):
    """Compare validated JSON recursively without boolean/numeric coercion."""
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is list:
        return len(left) == len(right) and all(_equal_json(a, b) for a, b in zip(left, right))
    if type(left) is dict:
        return set(left) == set(right) and all(_equal_json(left[key], right[key]) for key in left)
    return left == right


def observation(value):
    _finite_json(value)
    if type(value) is not dict or set(value) != {"regions", "observables"}:
        raise ValueError("oracle observation requires regions and named observables")
    if (type(value["regions"]) is not list or any(type(v) is not str for v in value["regions"])
            or len(set(value["regions"])) != len(value["regions"])
            or type(value["observables"]) is not dict
            or any(type(name) is not str for name in value["observables"])):
        raise ValueError("bounded observable interface required")
    if len(value["regions"]) > 128 or len(value["observables"]) > 256:
        raise ValueError("bounded oracle output required")
    if len(json.dumps(value, allow_nan=False).encode()) > 1000000:
        raise ValueError("bounded oracle output bytes required")
    return deepcopy(value)


def disagreement(expected, actual):
    """Exact finite JSON comparisons preserve equality and adjacent-float faults."""
    expected, actual = observation(expected), observation(actual)
    if not expected["observables"]:
        raise ValueError("independent oracle requires named observable assertions")
    keys = []
    if set(expected["regions"]) != set(actual["regions"]):
        keys.append("regions")
    for name, value in expected["observables"].items():
        if name not in actual["observables"] or not _equal_json(value, actual["observables"][name]):
            keys.append("observable:" + name)
    return tuple(sorted(keys))


def minimize_disagreement(event, oracle, candidate, *, max_evaluations=64):
    """Greedy bounded deletion/simplification; retain the initial mismatch keys.

    Each admitted trial reevaluates both independent oracle and candidate on
    separate deep copies. Exceptions are domain refusals, never disagreements.
    The result is only a bounded local reduction, with the original preserved.
    """
    oracle.validate()
    if oracle.evaluate is candidate:
        raise ValueError("independent oracle cannot be the candidate callback")
    _bound(max_evaluations, 1, 4096, "minimization evaluations")
    validate_event(event)
    original, current = deepcopy(event), deepcopy(event)
    calls, refused = 0, 0
    interface = None

    def evaluate(row):
        nonlocal calls, interface
        calls += 1
        expected = observation(oracle.evaluate(deepcopy(row)))
        names = set(expected["observables"])
        if interface is None:
            interface = names
        elif names != interface:
            raise ValueError("minimization oracle changed required observable interface")
        actual = observation(candidate(deepcopy(row)))
        return expected, actual, disagreement(expected, actual)

    expected, actual, required = evaluate(current)
    if not required:
        raise ValueError("minimization requires a genuine independent oracle disagreement")

    def trials(row):
        # Large-to-small contiguous chunks can preserve a disagreement when
        # deleting any one object alone would remove it. Include cross-kind
        # chunks; this remains bounded local reduction, not global search.
        objects = [(kind, index) for kind in KINDS
                   for index in range(len(row["objects"][kind]))]
        width = len(objects)
        while width >= 2:
            for start in range(0, len(objects), width):
                removed = objects[start:start + width]
                if len(removed) < 2:
                    continue
                trial = deepcopy(row)
                for kind, index in reversed(removed):
                    del trial["objects"][kind][index]
                yield trial
            width = (width + 1) // 2 if width > 2 else 1
        for kind in KINDS:
            for index in range(len(row["objects"][kind]) - 1, -1, -1):
                trial = deepcopy(row)
                del trial["objects"][kind][index]
                yield trial
        for kind in KINDS:
            for index, obj in enumerate(row["objects"][kind]):
                for field in (*FIELDS, "charge", "idbits"):
                    if obj[field] != 0:
                        trial = deepcopy(row)
                        trial["objects"][kind][index][field] = 0
                        yield trial
        for field in ("pt", "phi"):
            if row["met"][field] != 0:
                trial = deepcopy(row); trial["met"][field] = 0
                yield trial
        for stream, weight in row["weights"].items():
            simple = -1.0 if weight < 0 else 0.0 if weight == 0 else 1.0
            if weight != simple:
                trial = deepcopy(row); trial["weights"][stream] = simple
                yield trial

    exhausted = False
    while calls < max_evaluations:
        changed = False
        for trial in trials(current):
            if calls >= max_evaluations:
                exhausted = True
                break
            try:
                target, measured, keys = evaluate(trial)
            except (ValueError, KeyError, IndexError, ZeroDivisionError):
                refused += 1
                continue
            if set(required) <= set(keys):
                current, expected, actual = trial, target, measured
                changed = True
                break
        if not changed:
            break
    if calls >= max_evaluations:
        exhausted = True
    return {"original_event": original, "original_event_sha256": digest(original),
            "minimized_event": current, "minimized_event_sha256": digest(current),
            "expected": expected, "actual": actual, "preserved_disagreement_keys": list(required),
            "evaluations": calls, "domain_refusals": refused, "budget_exhausted": exhausted,
            "globally_minimal": False, "physics_validated": False}
