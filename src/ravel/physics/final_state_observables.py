"""Typed final-state observables over declared particle sets (standard library only).

Shared by the parton-level LHE audit and the optional shower worker, which may
run under a different Python interpreter. A particle is (pdg, px, py, pz, e).
"""
from bisect import bisect_right
import math

KINDS = {"invariant_mass": "GeV", "pt": "GeV", "missing_et": "GeV", "eta": "1", "rapidity": "1", "phi": "1"}
COMBINES = ("system", "leading", "each")
NORMALIZATIONS = ("events", "unit_area", "cross_section")


def check(observables):
    """Return a list of errors for a typed observable declaration list."""
    errors = []
    if not isinstance(observables, list) or not 1 <= len(observables) <= 16:
        return ["observables must be a list of 1 to 16 typed observables"]
    seen = set()
    for row in observables:
        if not isinstance(row, dict):
            errors.append("observable must be an object")
            continue
        allowed = {"id", "kind", "pdg", "abs_pdg", "combine", "count", "min_pt_gev", "max_abs_eta",
                   "bin_edges", "normalization"}
        if set(row) - allowed or not {"id", "kind", "pdg", "bin_edges"} <= set(row):
            errors.append("observable fields: id, kind, pdg, bin_edges and optional abs_pdg, combine, count, "
                          "min_pt_gev, max_abs_eta, normalization")
            continue
        name = row["id"]
        if not isinstance(name, str) or not name.replace("_", "").isalnum() or len(name) > 32 or name in seen:
            errors.append("observable ids must be unique short identifiers")
        seen.add(name)
        if row["kind"] not in KINDS:
            errors.append("unknown observable kind: %r" % (row["kind"],))
        pdg = row["pdg"]
        if not isinstance(pdg, list) or not pdg or any(type(x) is not int or x == 0 for x in pdg):
            errors.append("observable pdg must be a nonempty list of nonzero PDG identifiers")
        if "abs_pdg" in row and type(row["abs_pdg"]) is not bool:
            errors.append("abs_pdg must be a boolean")
        combine = row.get("combine", "system")
        if combine not in COMBINES:
            errors.append("combine must be system, leading or each")
        if row["kind"] == "missing_et" and combine != "system":
            errors.append("missing_et sums its selected particles (combine=system)")
        if "count" in row and (type(row["count"]) is not int or not 1 <= row["count"] <= 16):
            errors.append("count must be an integer from 1 to 16")
        for key in ("min_pt_gev", "max_abs_eta"):
            if key in row and (type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0):
                errors.append(key + " must be a nonnegative number")
        edges = row["bin_edges"]
        if (not isinstance(edges, list) or not 2 <= len(edges) <= 201
                or any(type(x) not in (int, float) or not math.isfinite(x) for x in edges)
                or any(a >= b for a, b in zip(edges, edges[1:]))):
            errors.append("bin_edges must be 2 to 201 strictly increasing finite numbers")
        if row.get("normalization", "events") not in NORMALIZATIONS:
            errors.append("normalization must be events, unit_area or cross_section")
    return errors


def _pt(p):
    return math.hypot(p[1], p[2])


def _eta(p):
    pt = _pt(p)
    if pt == 0:
        return math.copysign(math.inf, p[3])
    return math.asinh(p[3] / pt)


def _selected(particles, row):
    wanted = set(abs(x) for x in row["pdg"]) if row.get("abs_pdg") else set(row["pdg"])
    chosen = []
    for p in particles:
        key = abs(p[0]) if row.get("abs_pdg") else p[0]
        if key not in wanted:
            continue
        if _pt(p) + 1e-9 < row.get("min_pt_gev", 0):
            continue
        if "max_abs_eta" in row and abs(_eta(p)) > row["max_abs_eta"]:
            continue
        chosen.append(p)
    chosen.sort(key=_pt, reverse=True)
    return chosen


def _value(kind, p):
    if kind == "invariant_mass":
        m2 = p[4] ** 2 - p[1] ** 2 - p[2] ** 2 - p[3] ** 2
        if m2 < -1e-6 * max(1.0, p[4] ** 2):
            raise ValueError("spacelike selected system")
        return math.sqrt(max(m2, 0.0))
    if kind in ("pt", "missing_et"):
        return _pt(p)
    if kind == "eta":
        return _eta(p)
    if kind == "rapidity":
        if p[4] <= abs(p[3]):
            return math.copysign(math.inf, p[3])
        return 0.5 * math.log((p[4] + p[3]) / (p[4] - p[3]))
    return math.atan2(p[2], p[1])


def _sum(group):
    return (0,) + tuple(sum(p[i] for p in group) for i in range(1, 5))


def evaluate(particles, observables):
    """Observable values for one event; an event lacking the selection fills nothing."""
    answer = {}
    for row in observables:
        chosen = _selected(particles, row)
        combine = row.get("combine", "system")
        count = row.get("count")
        values = []
        if combine == "each":
            values = [_value(row["kind"], p) for p in (chosen[:count] if count else chosen)]
        elif combine == "leading":
            need = count or 1
            if len(chosen) >= need:
                values = [_value(row["kind"], chosen[need - 1])]
        else:
            if count is not None:
                if len(chosen) >= count:
                    values = [_value(row["kind"], _sum(chosen[:count]))]
            elif chosen or row["kind"] == "missing_et":
                values = [_value(row["kind"], _sum(chosen)) if chosen else 0.0]
        answer[row["id"]] = values
    return answer


def histogram(values, edges, normalization, *, events, cross_section_pb):
    """Counts and normalized values with sqrt(N) MC errors for uniform-weight events."""
    counts = [0] * (len(edges) - 1)
    under = over = 0
    for v in values:
        if v < edges[0]:
            under += 1
        elif v > edges[-1]:
            over += 1
        else:
            counts[min(bisect_right(edges, v) - 1, len(counts) - 1)] += 1
    widths = [b - a for a, b in zip(edges, edges[1:])]
    if normalization == "events":
        scale, unit = [1.0] * len(counts), "events per bin"
    elif normalization == "unit_area":
        total = sum(counts)
        if not total:
            raise ValueError("no in-range entries to normalize")
        scale, unit = [1.0 / (total * w) for w in widths], "1/(observable unit)"
    elif normalization == "cross_section":
        if not events:
            raise ValueError("no generated events")
        scale, unit = [cross_section_pb / (events * w) for w in widths], "pb/(observable unit)"
    else:
        raise ValueError("unknown normalization")
    return {"edges": list(edges), "counts": counts, "underflow": under, "overflow": over,
            "values": [c * s for c, s in zip(counts, scale)],
            "errors": [math.sqrt(c) * s for c, s in zip(counts, scale)],
            "normalization": normalization, "unit": unit,
            "uncertainty": "sqrt(N) Monte Carlo counting only"}
