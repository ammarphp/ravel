"""The scan grid a request states, as named finite axes and their complete point population.

A scan route plans one governed step per grid point, so the grid must be fixed before CHECK-IN 1
approves the plan. The grid comes from the request's reading (``parameter_values`` lists and
``parameter_range`` facts that state a step) or from a grid document the route analysis wrote
(``{"axes": [{"name", "values", "unit"}]}``). A range without a step or point count, or a grid
above the point ceiling, is not completed by guesswork: it stays a problem that keeps the grid
open. Points are ordered Cartesian products of the axes; a point's identity is the scan
orchestrator's tag of its coordinates, so the controller and the legacy scan tools agree.
"""
from __future__ import annotations

import math
import re

from .common import digest

MAX_POINTS = 1024
MAX_VALUES_PER_RANGE = 1024
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,80}")


def _name(raw, index, used):
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw or "")).strip("_")
    if not text or not text[0].isalpha():
        text = f"axis{index + 1}" + (f"_{text}" if text else "")
    text = text[:80]
    base, n = text, 2
    while text in used:
        text = f"{base[:76]}_{n}"
        n += 1
    used.add(text)
    return text


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _clean(value):
    """A coordinate without binary noise: integers stay integers, floats keep twelve significant digits."""
    if float(value).is_integer() and abs(value) < 2 ** 53:
        return int(value)
    return float(f"{value:.12g}")


def range_values(low, high, step):
    """``low, low + step, ... <= high`` (inclusive within a relative tolerance), or a problem string."""
    if not all(_number(v) for v in (low, high, step)):
        return None, "the range needs numeric low, high and step"
    if step <= 0:
        return None, "the range step must be positive"
    if high < low:
        low, high = high, low
    count = math.floor((high - low) / step + 1e-9) + 1
    if count > MAX_VALUES_PER_RANGE:
        return None, f"the range has {count} values, above the ceiling of {MAX_VALUES_PER_RANGE}"
    return [_clean(low + k * step) for k in range(count)], None


def _fact_axis(fact, index, used):
    """``(axis, problem)`` for one reading fact."""
    value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
    label = value.get("variable") or value.get("symbol") or value.get("text")
    if fact.get("type") == "parameter_values":
        values = value.get("values")
        if not isinstance(values, list) or not values or not all(_number(v) for v in values):
            return None, f"{fact.get('id')}: the stated values are not a finite numeric list"
        if len(set(values)) != len(values):
            return None, f"{fact.get('id')}: the stated values repeat"
        return {"name": _name(value.get("variable") or value.get("symbol"), index, used),
                "values": list(values), "unit": value.get("unit"), "fact": fact.get("id"),
                "label": label}, None
    step = value.get("step")
    step_value = step.get("value") if isinstance(step, dict) else step
    if step_value is None:
        return None, (f"{fact.get('id')}: the range '{value.get('text')}' states no step or point count; the grid "
                      "stays open until the requester or a cited source fixes it")
    values, problem = range_values(value.get("low"), value.get("high"), step_value)
    if problem:
        return None, f"{fact.get('id')}: {problem}"
    return {"name": _name(value.get("variable") or value.get("symbol"), index, used), "values": values,
            "unit": value.get("unit") or value.get("low_unit"), "fact": fact.get("id"), "label": label}, None


def axes_from_reading(reading) -> tuple[list, list]:
    """``(axes, problems)`` from the reading's grid facts, in reading order."""
    axes, problems, used = [], [], set()
    facts = [f for f in (reading or {}).get("facts") or ()
             if isinstance(f, dict) and f.get("type") in ("parameter_values", "parameter_range")]
    for index, fact in enumerate(facts):
        axis, problem = _fact_axis(fact, index, used)
        if problem:
            problems.append(problem)
        else:
            axes.append(axis)
    return axes, problems


def axes_from_document(document) -> tuple[list, list]:
    """``(axes, problems)`` from a grid document ``{"axes": [{"name", "values", "unit"?}]}``."""
    rows = (document or {}).get("axes") if isinstance(document, dict) else None
    if not isinstance(rows, list) or not rows:
        return [], ["the grid document names no axes"]
    axes, problems, names = [], [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not NAME.fullmatch(row["name"]):
            problems.append(f"axis {index + 1} needs a name of letters, digits and underscores")
            continue
        values = row.get("values")
        if not isinstance(values, list) or not values or not all(_number(v) for v in values) \
                or len(set(values)) != len(values):
            problems.append(f"axis {row['name']} needs distinct finite values")
            continue
        if row["name"] in names:
            problems.append(f"axis {row['name']} repeats")
            continue
        names.add(row["name"])
        axes.append({"name": row["name"], "values": list(values), "unit": row.get("unit"),
                     "fact": row.get("fact"), "label": row.get("label")})
    return axes, problems


def points(axes, *, maximum=MAX_POINTS) -> tuple[list, list]:
    """``(points, problems)``: the ordered Cartesian population with the scan orchestrator's point tags."""
    from ravel.workflow.scan_orchestrator import enumerate_axes, point_tag
    if not axes:
        return [], ["the request states no scan axis"]
    size = math.prod(len(a["values"]) for a in axes)
    if size > maximum:
        return [], [f"the grid has {size} points, above the ceiling of {maximum}; narrow it or split the scan"]
    try:
        coordinates = enumerate_axes([{"name": a["name"], "values": list(a["values"])} for a in axes],
                                     maximum=max(1, min(maximum, 4096)))
    except ValueError as exc:
        return [], [str(exc)]
    rows = [{"id": point_tag(p), "parameters": p} for p in coordinates]
    if len({r["id"] for r in rows}) != len(rows):
        return [], ["two grid points share an identity"]
    return rows, []


def grid(axes, problems=(), *, source) -> dict:
    """The grid record the plan pins: axes, points, digest and any problem that keeps it open."""
    found, more = points(axes) if not problems else ([], [])
    problems = list(problems) + list(more)
    body = {"source": source, "axes": axes, "points": found, "problems": problems}
    body["complete"] = bool(found) and not problems
    body["sha256"] = digest({"axes": axes, "points": [p["id"] for p in found]})
    return body


def from_reading(reading) -> dict:
    axes, problems = axes_from_reading(reading)
    return grid(axes, problems, source="reading")


def from_document(document) -> dict:
    axes, problems = axes_from_document(document)
    return grid(axes, problems, source="route-analysis")


def requested_ranges(reading) -> list:
    """``[(axis name, low, high)]`` of the reading's stated ranges, named as ``axes_from_reading`` names them."""
    ranges, used = [], set()
    facts = [f for f in (reading or {}).get("facts") or ()
             if isinstance(f, dict) and f.get("type") in ("parameter_values", "parameter_range")]
    for index, fact in enumerate(facts):
        value = fact.get("value") if isinstance(fact.get("value"), dict) else {}
        name = _name(value.get("variable") or value.get("symbol"), index, used)
        if fact.get("type") == "parameter_range" and _number(value.get("low")) and _number(value.get("high")):
            low, high = sorted((value["low"], value["high"]))
            ranges.append((name, low, high))
    return ranges


def resolve(reading, document=None) -> dict:
    """The approved grid: the request's own when it fixes one; else the route analysis's, inside the request.

    A route analysis never replaces a grid the request fixes. It may fill a grid the request leaves open
    (a range without a step, or a cited source grid), and then every axis the request ranges over keeps
    its values inside the stated range; an axis the request does not name is refused when the request
    names ranges.
    """
    requested = from_reading(reading)
    if requested["complete"] or not document:
        return requested
    found = from_document(document)
    ranges = requested_ranges(reading)
    fixed = {a["name"]: a for a in requested["axes"]}
    stated = set(fixed) | {name for name, _, _ in ranges}
    given = {a["name"]: a for a in found["axes"]}
    problems = list(found["problems"])
    used = set()
    facts = [f for f in (reading or {}).get("facts") or ()
             if isinstance(f, dict) and f.get("type") in ("parameter_values", "parameter_range")]
    for index, fact in enumerate(facts):
        value = fact.get("value") or {}
        name = _name(value.get("variable") or value.get("symbol"), index, used)
        unit = value.get("unit") or value.get("low_unit")
        if name in given and unit is not None and given[name].get("unit") != unit:
            problems.append(f"the route analysis changes the requested unit of axis {name}")
    for name in sorted(stated - set(given)):
        problems.append(f"the route analysis grid omits the requested axis {name}")
    for name in sorted(set(given) - stated) if stated else ():
        problems.append(f"the route analysis grid names axis {name}, which the request does not name")
    for name, axis in fixed.items():
        if name in given and (given[name]["values"] != axis["values"] or given[name].get("unit") != axis.get("unit")):
            problems.append(f"the route analysis changes the fixed values or unit of requested axis {name}")
    if ranges:
        by_name = {name: (low, high) for name, low, high in ranges}
        for axis in found["axes"]:
            if axis["name"] not in by_name:
                continue
            low, high = by_name[axis["name"]]
            outside = [v for v in axis["values"] if v < low - 1e-9 * max(1, abs(low)) or v > high + 1e-9 * max(1, abs(high))]
            if outside:
                problems.append(f"axis {axis['name']} leaves the requested range [{low}, {high}]: {outside[:5]}")
    if problems:
        found = grid(found["axes"], problems, source="route-analysis")
    return found
