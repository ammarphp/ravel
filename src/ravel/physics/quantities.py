"""Signed, grouped event moments with explicit bin and quantity semantics.

Each record is a subevent with zero or more fills. Its weight contributes once
to the inclusive denominator; each fill contributes to a half-open rectangular
bin or to flow. Correlated subevents share a globally unique ``group_id``.
Uncertainty is the Poissonized independent-group second moment, not a fixed-N
sample covariance or a generator integration error. Normalized covariance uses
the shared-denominator delta method, including correlations between weights.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict


def _keys(value, required, optional=(), label="object"):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise ValueError(f"{label} requires {sorted(required)}; unknown or missing fields")


def _number(value, label):
    try:
        finite = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{label} must be finite and numeric, not boolean")
    return float(value)


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{label} must be a nonempty trimmed string")
    return value


def _unique(values, label):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a nonempty list")
    for value in values:
        _text(value, label)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_binning(axes, bins):
    """Validate disjoint ND rectangles; return their hypervolumes in axis units."""
    if not isinstance(axes, list) or not axes:
        raise ValueError("axes must be a nonempty list")
    names = []
    for axis in axes:
        _keys(axis, ("name", "unit"), label="axis")
        names.append(_text(axis["name"], "axis name"))
        _text(axis["unit"], "axis unit (use '1' for dimensionless)")
    _unique(names, "axis names")
    if not isinstance(bins, list) or not bins:
        raise ValueError("bins must be a nonempty list")
    ids, volumes = [], []
    for bin_ in bins:
        _keys(bin_, ("id", "low", "high"), label="bin")
        ids.append(_text(bin_["id"], "bin id"))
        for edge in ("low", "high"):
            if not isinstance(bin_[edge], list) or len(bin_[edge]) != len(axes):
                raise ValueError("bin edges must match the number of axes")
            for x in bin_[edge]:
                _number(x, "bin edge")
        widths = [hi - lo for lo, hi in zip(bin_["low"], bin_["high"])]
        if any(width <= 0 for width in widths):
            raise ValueError("every bin must have positive width on every axis")
        volume = math.prod(widths)
        if not math.isfinite(volume) or volume <= 0:
            raise ValueError("bin volume must be finite and positive")
        volumes.append(volume)
    _unique(ids, "bin ids")
    for i, left in enumerate(bins):
        for right in bins[i + 1:]:
            if all(max(a, b) < min(c, d) for a, b, c, d in zip(left["low"], right["low"], left["high"], right["high"])):
                raise ValueError(f"overlapping bins: {left['id']} and {right['id']}")
    return volumes


def validate(contract):
    """Return a detached contract; reject implicit normalization or bin units."""
    _keys(contract, ("schema_version", "axes", "bins", "weight_names", "input_weight_unit", "representation", "normalization"), label="quantity contract")
    if type(contract["schema_version"]) is not int or contract["schema_version"] != 1:
        raise ValueError("unsupported quantity schema_version")
    validate_binning(contract["axes"], contract["bins"])
    _unique(contract["weight_names"], "weight_names")
    _text(contract["input_weight_unit"], "input_weight_unit")
    if contract["representation"] not in ("integrated", "differential"):
        raise ValueError("representation must be integrated or differential")
    normalization = contract["normalization"]
    if not isinstance(normalization, dict):
        raise ValueError("normalization must be an object")
    if normalization.get("kind") == "absolute":
        _keys(normalization, ("kind", "scale", "unit"), label="absolute normalization")
        if _number(normalization["scale"], "absolute scale") <= 0:
            raise ValueError("absolute scale must be positive")
        _text(normalization["unit"], "absolute output unit")
    elif normalization.get("kind") == "normalized":
        _keys(normalization, ("kind", "scope"), label="normalized quantity")
        if normalization["scope"] not in ("in_range", "all_events"):
            raise ValueError("normalization scope must be in_range or all_events")
    else:
        raise ValueError("normalization kind must be absolute or normalized")
    return json.loads(json.dumps(contract, allow_nan=False))


def _unit(contract):
    norm = contract["normalization"]
    unit = norm["unit"] if norm["kind"] == "absolute" else "1"
    dimensions = [axis["unit"] for axis in contract["axes"] if axis["unit"] != "1"]
    return unit + "/(" + "*".join(dimensions) + ")" if dimensions and contract["representation"] == "differential" else unit


def _sum(values):
    try:
        result = math.fsum(values)
    except (ValueError, OverflowError) as error:
        raise ValueError("nonfinite accumulated moment") from error
    return _number(result, "accumulated moment")


def _project(contract, state, *, finalize=True):
    """Apply scaling/Jacobians only after all additive moments have been merged."""
    bins, names = contract["bins"], contract["weight_names"]
    n, stride = len(bins), len(bins) + 2
    raw, moment = state["sumw"], state["second_moment"]
    volumes = validate_binning(contract["axes"], bins)
    payload = {"contract": contract, "state": state}
    base = {"schema_version": 1, "kind": "weighted_quantities", "contract": contract,
            "contract_sha256": _digest(contract), "state": state, "state_sha256": _digest(payload)}
    if not finalize:
        return {**base, "finalization_pending": True, "physics_validated": False}
    rows, values, denominators = [], [], {}
    for k, name in enumerate(names):
        offset = k * stride
        norm = contract["normalization"]
        if norm["kind"] == "normalized":
            denominator = raw[offset + n + 1]
            if denominator <= 0:
                raise ValueError(f"normalized denominator for {name} must be positive; signed cancellation is unresolved")
            denominators[name] = {"sumw": denominator, "sumw2": moment[offset+n+1][offset+n+1],
                                  "relative_standard_error": math.sqrt(moment[offset+n+1][offset+n+1]) / denominator}
        for i, volume in enumerate(volumes):
            divisor = volume if contract["representation"] == "differential" else 1.0
            if norm["kind"] == "absolute":
                factor = norm["scale"] / divisor
                rows.append({offset+i: factor})
                values.append(_number(raw[offset+i] * factor, "absolute quantity"))
            else:
                value = raw[offset+i] / denominator / divisor
                rows.append({offset+i: 1.0 / denominator / divisor, offset+n+1: -value / denominator})
                values.append(_number(value, "normalized quantity"))
    covariance = [[_sum(a * moment[i][j] * b for i, a in left.items() for j, b in right.items())
                   for right in rows] for left in rows]
    # Roundoff can leave a tiny negative diagonal after exact cancellations.
    for i in range(len(covariance)):
        if covariance[i][i] < 0:
            scale = _sum(abs(a * moment[k][j] * b) for k, a in rows[i].items() for j, b in rows[i].items())
            if covariance[i][i] < -1e-12 * max(scale, 1e-300):
                raise ValueError("negative propagated variance")
            covariance[i][i] = 0.0
    return {**base, "finalization_pending": False,
            "bin_ids": [b["id"] for b in bins], "bin_volumes": volumes, "unit": _unit(contract),
            "values": {name: values[k*n:(k+1)*n] for k, name in enumerate(names)},
            "covariance_order": [{"weight": name, "bin_id": b["id"]} for name in names for b in bins],
            "covariance": covariance, "covariance_unit": f"({_unit(contract)})^2", "denominators": denominators,
            "flow": {name: {"sumw": raw[k*stride+n], "sumw2": moment[k*stride+n][k*stride+n],
                            "unit": contract["input_weight_unit"]}
                     for k, name in enumerate(names)},
            "uncertainty_scope": "Poissonized independent-group moments; normalized quantities use first-order shared-denominator propagation",
            "limitations": ["No fixed-N, integration, detector, theory, luminosity or scale uncertainty is inferred.",
                            "Weight variations retain covariance but are not automatically a systematic uncertainty envelope.",
                            "Normalized uncertainty can be unreliable when its supplied signed denominator is poorly determined."],
            "physics_validated": False}


def calculate(contract, records, *, finalize=True):
    """Calculate moments from iterable records, preserving complete event exposure.

    Required record fields are ``event_id``, ``group_id``, ``shard_id``,
    ``weights`` and ``fills``. IDs are globally unique strings; group IDs may
    repeat only within one shard. All bins include low edges and exclude high
    edges. Multiple fills per subevent are correlated, including their flow.
    Use ``finalize=False`` for additive shards with zero/negative denominators;
    ``merge`` applies normalization after their moments have been combined.
    """
    contract = validate(contract)
    bins, names = contract["bins"], contract["weight_names"]
    n, stride = len(bins), len(bins) + 2
    dimensions = stride * len(names)
    groups, group_shards = {}, {}
    events, shards = set(), set()
    negative = dict.fromkeys(names, 0)
    counts = dict.fromkeys(("records", "fills", "in_range", "flow", "empty_records"), 0)
    for record in records:
        _keys(record, ("event_id", "group_id", "shard_id", "weights", "fills"), label="event record")
        event, group, shard = (_text(record[key], key) for key in ("event_id", "group_id", "shard_id"))
        if event in events:
            raise ValueError(f"duplicate event_id: {event}")
        if group in group_shards and group_shards[group] != shard:
            raise ValueError("correlated group is split across independent shards")
        events.add(event)
        shards.add(shard)
        group_shards[group] = shard
        counts["records"] += 1
        _keys(record["weights"], names, label="event weights")
        weights = [_number(record["weights"][name], "event weight") for name in names]
        fills = record["fills"]
        if not isinstance(fills, list):
            raise ValueError("fills must be a list, possibly empty")
        counts["empty_records"] += not fills
        entries = defaultdict(int)
        for fill in fills:
            if not isinstance(fill, list) or len(fill) != len(contract["axes"]):
                raise ValueError("fill dimensionality does not match axes")
            for coordinate in fill:
                _number(coordinate, "fill coordinate")
            index = next((i for i, b in enumerate(bins) if all(lo <= x < hi for x, lo, hi in zip(fill, b["low"], b["high"]))), n)
            entries[index] += 1
            counts["fills"] += 1
            counts["flow" if index == n else "in_range"] += 1
        vector = groups.setdefault(group, defaultdict(list))
        denominator_multiplicity = sum(v for k, v in entries.items() if k < n) if contract["normalization"].get("scope") == "in_range" else 1
        for k, (name, weight) in enumerate(zip(names, weights)):
            negative[name] += weight < 0
            for i, multiplicity in entries.items():
                vector[k*stride+i].append(_number(weight * multiplicity, "weighted fill"))
            vector[k*stride+n+1].append(_number(weight * denominator_multiplicity, "denominator weight"))
    if not events:
        raise ValueError("at least one event record is required")
    sums, products = defaultdict(list), defaultdict(list)
    for sparse in groups.values():
        vector = {i: _sum(weights) for i, weights in sparse.items()}
        for i, value in vector.items():
            sums[i].append(value)
            for j, other in vector.items():
                if j >= i:
                    products[i, j].append(_number(value * other, "group product"))
    moments = [[0.0]*dimensions for _ in range(dimensions)]
    for (i, j), values in products.items():
        moments[i][j] = moments[j][i] = _sum(values)
    state = {"sumw": [_sum(sums[i]) for i in range(dimensions)], "second_moment": moments,
             "event_ids": sorted(events), "group_ids": sorted(groups), "shard_ids": sorted(shards),
             "counts": counts, "negative_weight_records": negative}
    return _project(contract, state, finalize=finalize)


def merge(results):
    """Merge disjoint additive shards, then normalize; never average densities.

    Shards containing parts of the same correlated group are deliberately
    rejected: their missing cross-shard products cannot be reconstructed.
    Result hashes check accidental state mutation; source authentication belongs
    to the workflow's input receipts, not to this self-contained checksum.
    """
    results = list(results)
    if not results:
        raise ValueError("at least one quantity result is required")
    contract = validate(results[0]["contract"])
    states, identities = [], {key: set() for key in ("event_ids", "group_ids", "shard_ids")}
    for result in results:
        if result.get("schema_version") != 1 or result.get("kind") != "weighted_quantities":
            raise ValueError("not a supported quantity result")
        if result.get("contract_sha256") != _digest(contract) or result.get("contract") != contract:
            raise ValueError("quantity contracts differ; scaling or bin definitions cannot be merged")
        state = result["state"]
        if result.get("state_sha256") != _digest({"contract": contract, "state": state}):
            raise ValueError("quantity additive state has changed")
        for key, seen in identities.items():
            _unique(state[key], key)
            if seen.intersection(state[key]):
                raise ValueError(f"overlapping {key}; shards are not independent")
            seen.update(state[key])
        states.append(state)
    size = len(states[0]["sumw"])
    state = {"sumw": [_sum(s["sumw"][i] for s in states) for i in range(size)],
             "second_moment": [[_sum(s["second_moment"][i][j] for s in states) for j in range(size)] for i in range(size)],
             **{key: sorted(value) for key, value in identities.items()},
             "counts": {key: sum(s["counts"][key] for s in states) for key in states[0]["counts"]},
             "negative_weight_records": {key: sum(s["negative_weight_records"][key] for s in states) for key in contract["weight_names"]}}
    return _project(contract, state)
