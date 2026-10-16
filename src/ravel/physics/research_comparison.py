"""Complete-cell comparisons of source-bound supplied scalar/interval results.

This is finite arithmetic, not a causal or coverage estimator. Ordinary science
owns execution/review. Covariance is used only from a pinned same-event evaluation
with an explicit interval prescription. Search retention never grants a claim.
"""
from copy import deepcopy
import math
import hashlib
import os
from pathlib import Path
from ravel.workflow import candidate_experiments as ce

MAX_CELLS = 32
MAX_SOURCE_BYTES = 8 * 1024**2
MAX_TOTAL_BYTES = 64 * 1024**2


def _snapshot(pin, base, *, limit=MAX_SOURCE_BYTES):
    """Read the exact pinned bytes from one bounded descriptor-backed snapshot."""
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    _pin(pin)
    if pin['size'] > limit:raise ValueError('source exceeds this content-consumption bound')
    path=Path(pin['path']);path=path if path.is_absolute() else Path(base)/path
    try:
        # The snapshot compares change times; let the stamping clock pass the source's first.
        from ravel.workflow.validation_io import settled
        settled(path.lstat)
    except OSError as exc:
        raise ValueError('ordinary bounded research source or path unavailable') from exc
    path,raw=_bounded_source_snapshot(path,limit)
    if len(raw)!=pin['size'] or hashlib.sha256(raw).hexdigest()!=pin['sha256']:
        raise ValueError('authenticated source bytes or path custody changed')
    return path,raw,{'path':str(path),'sha256':pin['sha256'],'size':len(raw)}


def document(pin, base):
    from ravel.workflow.agent_host import _loads
    return _loads(_snapshot(pin,base,limit=ce.MAX_BYTES)[1])


_json = document


def _text(value):
    if type(value) is not str or not value.strip() or len(value.encode()) > 4096:
        raise ValueError("bounded literal comparison text required")


def _number(value):
    try:
        ok = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        ok = False
    if not ok:
        raise ValueError("finite scalar comparison value required")
    return value


def rule(value):
    ce.keys(value, ("schema_version", "metric", "unit", "direction", "min_gain", "tolerance", "uncertainty", "reduction"))
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("research comparison rule/v1 required")
    for k in ("metric", "unit"): _text(value[k])
    if value["direction"] not in {"minimize", "maximize"} or value["uncertainty"] not in {"deterministic", "supplied_intervals"} or value["reduction"] != "all_cells":
        raise ValueError("explicit finite direction/uncertainty and whole-cell reduction required")
    for k in ("min_gain", "tolerance"):
        if _number(value[k]) < 0: raise ValueError("nonnegative prospective thresholds required")
    return deepcopy(value)


def _pin(pin):
    ce.keys(pin, ("path", "sha256", "size")); ce.sha(pin["sha256"])
    _text(pin["path"])
    if type(pin["size"]) is not int or not 0 <= pin["size"] <= MAX_SOURCE_BYTES:
        raise ValueError("explicit bounded comparison source pin required")


def _census(pins, base, *, max_entries=256, max_unique=256):
    """Admit the unique declared byte population before opening its payloads."""
    if (type(max_entries) is not int or not 1 <= max_entries <= 8192 or
        type(max_unique) is not int or not 1 <= max_unique <= 256 or
        type(pins) is not list or len(pins) > max_entries):
        raise ValueError("bounded complete source census required")
    unique = {}
    for pin in pins:
        _pin(pin)
        path = Path(pin['path']); path = path if path.is_absolute() else Path(base) / path
        key = os.path.normpath(str(path.absolute()))
        actual = {**pin, 'path': key}
        if key in unique and unique[key] != actual:
            raise ValueError("incompatible source aliases in comparison")
        unique[key] = actual
    if len(unique) > max_unique or sum(p['size'] for p in unique.values()) > MAX_TOTAL_BYTES:
        raise ValueError("bounded unique comparison source population required")
    return list(unique.values())


def _pointer(value):
    if type(value) is not str or not value.startswith("/") or len(value.encode()) > 4096:
        raise ValueError("literal bounded comparison pointer required")


def search_retention(gains, tolerances=None):
    """Robust two-candidate frontier over every declared, oriented objective.

    Overlap or an unresolved cell cannot establish dominance, and neither can a
    gain inside its rule's declared equivalence tolerance. The claim minimum gain
    deliberately plays no part in retaining candidates for further search.
    """
    tolerances = [0] * len(gains) if tolerances is None else tolerances
    complete = bool(gains) and len(tolerances) == len(gains) and all(g is not None for g in gains)
    left = complete and all(g[0] >= 0 for g in gains) and any(g[0] > t for g, t in zip(gains, tolerances))
    right = complete and all(g[1] <= 0 for g in gains) and any(g[1] < -t for g, t in zip(gains, tolerances))
    return {"frontier": [s for s, dropped in (("left", right), ("right", left)) if not dropped],
            "dominates": "left" if left else "right" if right else None,
            "claim_authorized": False}


def _pairing(cell, base):
    """Authenticate actual paired coordinates, including retained group matrices."""
    from ravel.workflow.research_cycle import _pointer as extract
    descriptor = cell['paired_evaluation']
    ce.keys(descriptor, ('source', 'pointer'))
    _pin(descriptor['source']); _pointer(descriptor['pointer'])
    record = deepcopy(extract(_json(descriptor['source'], base), descriptor['pointer']))
    covariance_fields = ('covariance_source', 'covariance_pointer', 'values_pointer',
                         'indices', 'interval_multiplier', 'interval_prescription')
    ce.keys(record, ('construction', 'population', 'left', 'right',
                     *(covariance_fields if any(k in record for k in covariance_fields) else ())))
    if record['construction'] != 'same_events':
        raise ValueError('recorded same_events construction required')
    # A joint evaluation can name its own output without a circular file digest.
    for side in ('left', 'right'):
        if type(record[side]) is dict and record[side].get('source') == 'self':
            record[side]['source'] = descriptor['source']
    if record.get('covariance_source') == 'self':
        record['covariance_source'] = descriptor['source']
    for side in ('left', 'right'):
        if record[side] != {k: cell[side][k] for k in ('source', 'value_pointer')}:
            raise ValueError('paired evaluation operands differ from comparison')
    pins = [descriptor['source'], record['population']]
    for pin in pins: _pin(pin)
    if 'covariance_source' not in record:
        return record, pins
    pins.append(record['covariance_source'])
    for pin in pins: _pin(pin)
    if record['interval_prescription'] != 'symmetric_covariance':
        raise ValueError('supplied symmetric_covariance interval prescription required')
    for key in ('covariance_pointer', 'values_pointer'): _pointer(record[key])
    indices = record['indices']
    if (type(indices) is not list or len(indices) != 2 or
            any(type(i) is not int or not 0 <= i < 768 for i in indices) or indices[0] == indices[1]):
        raise ValueError('two distinct paired covariance coordinates required')
    if _number(record['interval_multiplier']) <= 0:
        raise ValueError('positive supplied interval multiplier required')
    return record, pins


def _paired_gain(cell, values, direction, base):
    from ravel.workflow.research_cycle import _pointer as extract
    record, _ = _pairing(cell, base)
    if 'covariance_source' not in record:
        return None
    source = _json(record['covariance_source'], base)
    try:
        matrix = extract(source, record['covariance_pointer'])
    except (KeyError, IndexError):
        matrix = None
    # Null covariance is an explicit missing observation, never independence.
    if matrix is None:
        return None
    central = extract(source, record['values_pointer'])
    i, j = record['indices']
    if (type(central) is not list or not 2 <= len(central) <= 768 or max(i, j) >= len(central) or
            [central[i], central[j]] != [v['value'] for v in values]):
        raise ValueError('paired covariance central coordinates differ from operands')
    if (type(matrix) is not list or len(matrix) != len(central) or
            any(type(row) is not list or len(row) != len(central) for row in matrix)):
        raise ValueError('complete paired covariance matrix required')
    vl, vr, cov, reverse = [_number(x) for x in (matrix[i][i], matrix[j][j], matrix[i][j], matrix[j][i])]
    if vl < 0 or vr < 0 or cov != reverse or abs(cov) > math.sqrt(vl) * math.sqrt(vr):
        raise ValueError('invalid paired covariance block')
    variance = _number(math.fsum((vl, vr, -2 * cov)))
    if variance < 0: raise ValueError('negative paired difference variance')
    width = _number(record['interval_multiplier'] * math.sqrt(variance))
    center = values[0]['value'] - values[1]['value']
    if direction == 'minimize': center = -center
    return [_number(center - width), _number(center + width)]


def validate(task):
    ce.keys(task, ("schema_version", "request"))
    if type(task["schema_version"]) is not int or task["schema_version"] != 1:
        raise ValueError("research comparison task/v1 required")
    _pin(task["request"])
    return deepcopy(task)


def _request(task, base, *, _readonly=None):
    task = validate(task); request = _json(task["request"], base)
    ce.keys(request, ("schema_version", "protocol_sha256", "comparison_id", "rule", "cells", "dependencies", *(["replication_request"] if "replication_request" in request else [])))
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("complete comparison request/v1 required")
    ce.sha(request["protocol_sha256"]); ce.identity(request["comparison_id"]); _pin(request["rule"])
    r = rule(_json(request["rule"], base))
    cells = request["cells"]
    if type(cells) is not list or not 1 <= len(cells) <= MAX_CELLS:
        raise ValueError("complete bounded cell matrix required")
    ids = set(); pins = [task["request"], request["rule"]]
    for cell in cells:
        ce.keys(cell, ("id", "metric", "unit", "exposure", "left", "right",
                       *(['paired_evaluation'] if 'paired_evaluation' in cell else [])))
        ce.identity(cell["id"])
        if cell["id"] in ids: raise ValueError("duplicate comparison cell")
        ids.add(cell["id"])
        if cell["metric"] != r["metric"] or cell["unit"] != r["unit"]:
            raise ValueError("comparison metric/unit must match the fixed rule")
        if cell["exposure"] not in {"adaptive_screen", "adaptive_full", "withheld_confirmation"}:
            raise ValueError("explicit actual evaluation exposure required")
        for side in ("left", "right"):
            row = cell[side]
            ce.keys(row, ("source", "value_pointer", "interval_pointer", "quality_pointer"))
            _pin(row["source"])
            for k in ("value_pointer", "quality_pointer"): _pointer(row[k])
            if row["interval_pointer"] is not None: _pointer(row["interval_pointer"])
            pins.append(row["source"])
        if 'paired_evaluation' in cell:
            pins.extend(_pairing(cell, base)[1])
    if type(request["dependencies"]) is not list or len(request["dependencies"]) > 128:
        raise ValueError("bounded complete held source/cohort dependencies required")
    pins.extend(request["dependencies"])
    unique = _census(pins, base)
    for pin in unique: _snapshot(pin, base)
    if 'replication_request' in request:
        from ravel.workflow import fresh_replication
        operational = fresh_replication.check_comparison(request, base, extra_pins=unique,
            **({} if _readonly is None else {"_producer_scope": fresh_replication._readonly_producer(_readonly)}))
        # Operational trees are bounded and streamed separately; their large
        # binary leaves never become presented scalar/interval payloads.
        unique = operational
    return request, r, unique


def inputs(task, base_dir, *, _readonly=None):
    return [Path(p["path"]) for p in _request(task, base_dir,
        **({} if _readonly is None else {'_readonly': _readonly}))[2]]


def calculate(task, base_dir, *, _readonly=None):
    from ravel.workflow.research_cycle import _pointer as extract
    request, fixed, pins = _request(task, base_dir,
        **({} if _readonly is None else {'_readonly': _readonly}))
    captured = {}; rows = []
    for cell in request["cells"]:
        values = []; reasons = []
        for side in ("left", "right"):
            row = cell[side]; key = (row["source"]["path"], row["source"]["sha256"])
            if key not in captured: captured[key] = _json(row["source"], base_dir)
            source = captured[key]
            try:
                quality = extract(source, row["quality_pointer"])
                value = extract(source, row["value_pointer"])
                if not (quality is True or (type(quality) is str and quality == "passed")): raise ValueError("quality not established")
                value = _number(value)
                if fixed["uncertainty"] == "deterministic": interval = [value, value]
                else:
                    interval = None if row["interval_pointer"] is None else extract(source, row["interval_pointer"])
                    if type(interval) is not list or len(interval) != 2:
                        raise ValueError("supplied complete interval unavailable")
                    interval = [_number(x) for x in interval]
                    if not interval[0] <= value <= interval[1]: raise ValueError("value outside supplied interval")
                values.append({"value": value, "interval": interval})
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                reasons.append({"side": side, "kind": "quality_measurement_or_uncertainty_unresolved", "detail": str(exc)})
                values.append(None)
        gain = None; decision = "unknown"; paired = None
        if all(x is not None for x in values):
            left, right = values
            if fixed["direction"] == "maximize": gain = [left["interval"][0] - right["interval"][1], left["interval"][1] - right["interval"][0]]
            else: gain = [right["interval"][0] - left["interval"][1], right["interval"][1] - left["interval"][0]]
            if 'paired_evaluation' in cell and fixed['uncertainty'] == 'supplied_intervals':
                paired = _paired_gain(cell, values, fixed['direction'], base_dir)
                if paired is not None: gain = paired
            for x in gain: _number(x)
            t = fixed["tolerance"]
            decision = "better" if gain[0] > fixed["min_gain"] + t else "worse" if gain[1] < -t else "equivalent" if max(abs(x) for x in gain) <= t else "unknown"
        rows.append({"cell_id": cell["id"], "exposure": cell["exposure"], "operands": values,
                     "gain_interval": gain, "decision": decision, "unresolved_reasons": reasons})
        # Marginal rows keep the recorded result schema that staged status recomputes.
        if paired is not None: rows[-1]["interval_construction"] = "paired_covariance"
    decisions = {r["decision"] for r in rows}
    decision = "equivalent" if decisions == {"equivalent"} else "better" if decisions <= {"better", "equivalent"} else "worse" if decisions <= {"worse", "equivalent"} else "unknown"
    if 'replication_request' in request:
        from ravel.workflow import fresh_replication
        fresh_replication.check_comparison(request,base_dir,extra_pins=pins,
            **({} if _readonly is None else {"_producer_scope": fresh_replication._readonly_producer(_readonly)}))
    else:
        for pin in pins: _snapshot(pin,base_dir)
    return {"schema_version": 1, "kind": "source_bound_research_comparison", "status": "passed", "decision": decision,
            "protocol_sha256": request["protocol_sha256"], "comparison_id": request["comparison_id"],
            "request_sha256": task["request"]["sha256"], "rule_sha256": request["rule"]["sha256"], "rule": fixed,
            "cell_count": len(rows), "cells": rows, "complete_original_cell_denominator": [c["id"] for c in request["cells"]],
            "inputs": pins, "physics_validated": False, "scientific_acceptance": False,
            "scope": "Fixed-rule whole-matrix comparison of supplied scalar/interval metrics",
            "limitations": ["Arithmetic delivery, including a worse or unknown result, is not independent scientific acceptance.",
                "Supplied intervals do not establish statistical coverage or covariance; deterministic is a declared law assumption.",
                "Adaptive full evaluation is not automatically held-out confirmation; heterogeneous metric aggregation is unsupported."]}


def run(task, base_dir, output_dir):
    from ravel.workflow.research_cycle import _ordinary
    from ravel.workflow.state_io import atomic_json
    out = _ordinary(output_dir)
    if not out.is_dir(): raise ValueError("ordinary worker-owned comparison output required")
    result = calculate(task, base_dir)
    path = out / "research-comparison.json"
    if path.exists(): raise FileExistsError("comparison result already exists")
    atomic_json(path, result)
    return result


def readonly_inputs(task, base, context):
    return inputs(task, base, _readonly=context)


def readonly_calculate(task, base, context):
    return calculate(task, base, _readonly=context)


def readonly_materialize(result, specification, context):
    from ravel.workflow.readonly_preparation import _bytes
    return (('research-comparison.json', _bytes(result)),)


from ravel.workflow.readonly_preparation import ReadOnlyAdapterV1
READONLY_WORKER_V1 = ReadOnlyAdapterV1(
    (('inputs', inputs), ('_validation_inputs', None), ('run', run), ('calculate', calculate), ('_request', _request),
     ('readonly_inputs', readonly_inputs), ('readonly_calculate', readonly_calculate),
     ('readonly_materialize', readonly_materialize)),
    readonly_inputs, readonly_calculate, readonly_materialize, False)
