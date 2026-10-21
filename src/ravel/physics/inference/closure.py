"""Closure of a model built here against the analysis's published limits, where they are available.

A constructed or simplified likelihood stands in for the analysis's own likelihood. A reference
document supplies the published signal-strength limits of benchmark signals, with their yields in
every region of the model and the citation they come from:

    {"schema_version": 1, "kind": "reference-limits", "quantity": "signal_strength",
     "source": "<citation>",
     "points": [{"id": "<benchmark>", "signal": {"<region>": <yield>, ...},
                 "expected": <published expected median limit>, "observed": <published observed limit or null>}]}

Each benchmark's yields go through the same model (the same builder, registry and correlation
variant) and its limits are recomputed. The record keeps the published and reproduced values; the
statistics catalogue's ``reference-limit-closure`` check recomputes their relative differences
against its stated tolerance. When the analysis publishes no such limits, the document says so with
its reason and the evidence that was searched:

    {"schema_version": 1, "kind": "reference-limits", "available": false, "reason": "<why>", "evidence": "<searched>"}

The closure compares central values at the declared benchmarks only. It certifies neither the
coverage of the model nor its agreement away from those points.
"""
from __future__ import annotations

from copy import deepcopy
import math

KIND = "reference-limits"
SCHEMA_VERSION = 1
QUANTITY = "signal_strength"


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"reference limits: {field} must be a nonblank string")
    return value.strip()


def _limit(value, field, *, optional=False):
    if value is None and optional:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"reference limits: {field} must be a finite positive signal-strength limit")
    return float(value)


def load(document, regions) -> dict:
    """The validated reference document for a model whose regions are ``regions``."""
    if not isinstance(document, dict) or document.get("kind") != KIND or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"reference limits must be kind {KIND!r} schema_version {SCHEMA_VERSION}")
    if document.get("available") is False:
        if set(document) - {"schema_version", "kind", "available", "reason", "evidence"}:
            raise ValueError("reference limits declared unavailable carry only their reason and evidence")
        return {"schema_version": SCHEMA_VERSION, "kind": KIND, "available": False,
                "reason": _text(document.get("reason"), "reason"), "evidence": _text(document.get("evidence"), "evidence")}
    if set(document) - {"schema_version", "kind", "quantity", "source", "points"}:
        raise ValueError("reference limits carry schema_version, kind, quantity, source and points")
    if document.get("quantity") != QUANTITY:
        raise ValueError(f"reference limits must state quantity {QUANTITY!r} for the benchmark yields given")
    points = document.get("points")
    if not isinstance(points, list) or not points:
        raise ValueError("reference limits need at least one benchmark point")
    names, seen, out = list(regions), set(), []
    for point in points:
        if not isinstance(point, dict) or set(point) - {"id", "signal", "expected", "observed"}:
            raise ValueError("a reference point carries id, signal, expected and observed")
        identity = _text(point.get("id"), "point id")
        if identity in seen:
            raise ValueError(f"reference point {identity!r} is listed twice")
        seen.add(identity)
        signal = point.get("signal")
        if not isinstance(signal, dict) or sorted(signal) != sorted(names):
            raise ValueError(f"reference point {identity!r} must give a signal yield for exactly the regions {names}")
        for region, value in signal.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"reference point {identity!r}: the {region} yield must be finite and nonnegative")
        if not any(value > 0 for value in signal.values()):
            raise ValueError(f"reference point {identity!r} has no signal in any region")
        out.append({"id": identity, "signal": {k: float(v) for k, v in signal.items()},
                    "expected": _limit(point.get("expected"), f"{identity} expected"),
                    "observed": _limit(point.get("observed"), f"{identity} observed", optional=True)})
    return {"schema_version": SCHEMA_VERSION, "kind": KIND, "quantity": QUANTITY,
            "source": _text(document.get("source"), "source"), "points": out}


def evaluate(reference, compute, *, tolerance, calculator="asymptotic") -> dict:
    """The closure record: ``compute(index, signal)`` returns the exclusion result of one benchmark.

    ``calculator`` states how the benchmarks were recomputed; asymptotic CLs is the comparison even
    when the reported limit itself is toy-calibrated.
    """
    from ravel.limits import read_limits
    if reference.get("available") is False:
        return deepcopy(reference)
    rows = []
    for index, point in enumerate(reference["points"]):
        limits = read_limits(compute(index, deepcopy(point["signal"])))
        reproduced = {"expected": {"value": limits.expected[2].value, "status": limits.expected[2].status},
                      "observed": ({"value": limits.observed.value, "status": limits.observed.status}
                                   if point["observed"] is not None else None)}
        difference = {}
        for side in ("expected", "observed"):
            published, found = point[side], reproduced[side]
            value = (found or {}).get("value")
            difference[side] = (None if published is None or value is None
                                else (float(value) - published) / published)
        rows.append({"id": point["id"], "published": {"expected": point["expected"], "observed": point["observed"]},
                     "reproduced": reproduced, "relative_difference": difference})
    return {"schema_version": SCHEMA_VERSION, "kind": "reference-closure", "available": True,
            "source": reference["source"], "quantity": QUANTITY, "tolerance": tolerance, "calculator": calculator,
            "points": rows}
