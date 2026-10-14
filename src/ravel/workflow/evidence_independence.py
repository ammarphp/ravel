"""Bounded numerical-copy reporting, without certifying source independence.

``report({artifact_id: json_bytes})`` accepts diagnostic ``estimates`` or
``paired_normalized_rows`` (schema 1). Numerical digests omit ALL labels and
prose, including channel names and basis.definition. Semantic digests retain
machine-readable basis fields. Equal numbers create a review obligation;
different numbers never establish independently generated evidence. No files
are modified or quarantined. JSON decimals are interpreted exactly as written.
"""
from __future__ import annotations

from collections import defaultdict
import argparse
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

MAX_BYTES, MAX_ROWS, MAX_CHANNELS = 4_194_304, 20_000, 32
MAX_ARTIFACTS, MAX_TOKEN, MAX_EXPONENT = 64, 128, 128


def _token(token):
    if len(token) > MAX_TOKEN:
        raise ValueError("numeric token exceeds limit")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal token") from exc
    if not value.is_finite() or abs(value.as_tuple().exponent) > MAX_EXPONENT:
        raise ValueError("nonfinite or oversized decimal exponent")
    return Fraction(value)


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def loads(raw):
    """Read bounded strict JSON, preserving exact decimal numerical values."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("input must be bounded JSON bytes")
    def constant(_):
        raise ValueError("nonfinite JSON constant")
    def integer(token):
        _token(token)
        return int(token)
    try:
        return json.loads(raw, parse_float=_token, parse_int=integer,
                          parse_constant=constant, object_pairs_hook=_pairs)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid or excessively nested JSON") from exc


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("unknown or missing schema fields")


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("invalid or oversized label")
    return value


def _number(value):
    if type(value) is bool:
        raise ValueError("boolean is not a numerical value")
    if isinstance(value, Fraction):
        number = value
    elif type(value) is int:
        number = _token(str(value))
    elif type(value) is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite number")
        number = _token(str(value))
    elif isinstance(value, Decimal):
        number = _token(str(value))
    else:
        raise ValueError("numerical fields require numbers, not strings")
    if max(number.numerator.bit_length(), number.denominator.bit_length()) > 1024:
        raise ValueError("oversized rational value")
    return str(number)


def _count(value):
    if type(value) is not int or not 0 < value <= MAX_ROWS * 2:
        raise ValueError("invalid exposure")
    return value


def _basis(value, paired):
    fields = {"quantity", "unit", "normalization", "role", "channels"}
    if paired:
        fields.update({"checked_weight_stream", "representation", "bin_volumes"})
    if isinstance(value, dict) and "definition" in value:
        fields.add("definition")
    _keys(value, fields)
    for key in fields - {"channels", "bin_volumes"}:
        _text(value[key])
    channels = value["channels"]
    if (not isinstance(channels, list) or not 0 < len(channels) <= MAX_CHANNELS
            or len(set(map(_text, channels))) != len(channels)):
        raise ValueError("invalid channels")
    semantic = {key: value[key] for key in fields - {"definition"}}
    if paired:
        volumes = value["bin_volumes"]
        if (value["representation"] not in ("integrated", "differential")
                or not isinstance(volumes, list) or len(volumes) != len(channels)):
            raise ValueError("invalid representation or bin volumes")
        semantic["bin_volumes"] = [_number(v) for v in volumes]
        if any(Fraction(v) <= 0 for v in semantic["bin_volumes"]):
            raise ValueError("bin volumes must be positive")
    return semantic


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def fingerprints(raw):
    """Return numerical/semantic identities for one explicitly supported schema."""
    data = loads(raw)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    kind = data.get("kind")
    if kind == "estimates":
        _keys(data, {"schema_version", "kind", "basis", "population_id", "expected_exposure",
                     "actual_exposure", "uncertainty_scope", "values", "covariance", "covariance_status"})
        semantic = _basis(data["basis"], False)
        _text(data["population_id"]); _text(data["uncertainty_scope"])
        size = len(data["basis"]["channels"])
        values, covariance = data["values"], data["covariance"]
        if not isinstance(values, list) or len(values) != size:
            raise ValueError("estimate channel count differs")
        numeric = {"schema": kind, "channels": size, "values": [_number(v) for v in values],
                   "exposure": [_count(data[k]) for k in ("expected_exposure", "actual_exposure")]}
        if data["covariance_status"] not in ("supplied", "unavailable", "exact"):
            raise ValueError("unknown covariance status")
        if (covariance is None) != (data["covariance_status"] == "unavailable"):
            raise ValueError("covariance availability disagrees with status")
        if covariance is not None:
            if (not isinstance(covariance, list) or len(covariance) != size
                    or any(not isinstance(row, list) or len(row) != size for row in covariance)):
                raise ValueError("covariance dimensions differ")
            covariance = [[_number(v) for v in row] for row in covariance]
            if data["covariance_status"] == "exact" and any(Fraction(v) for row in covariance for v in row):
                raise ValueError("exact quantity has nonzero covariance")
        numeric["covariance"] = covariance
        semantic["covariance_status"] = data["covariance_status"]
        zero = all(Fraction(v) == 0 for v in numeric["values"])
    elif kind == "paired_normalized_rows":
        _keys(data, {"schema_version", "kind", "basis", "uncertainty_model", "original_source_sha256", "exposure", "records"})
        semantic = _basis(data["basis"], True)
        if semantic["normalization"] not in ("all_events", "in_range") or data["uncertainty_model"] not in ("poissonized_independent_groups", "fixed_iid_groups"):
            raise ValueError("unsupported normalization or uncertainty model")
        semantic["uncertainty_model"] = data["uncertainty_model"]
        source_sha = data["original_source_sha256"]
        if not isinstance(source_sha, str) or len(source_sha) != 64 or any(c not in "0123456789abcdef" for c in source_sha):
            raise ValueError("original source SHA256 must be lowercase hexadecimal")
        _keys(data["exposure"], {"original_events", "derived_records"})
        rows, size = data["records"], len(data["basis"]["channels"])
        if not isinstance(rows, list) or not 0 < len(rows) <= MAX_ROWS:
            raise ValueError("invalid row census")
        exposure = [_count(data["exposure"][k]) for k in ("original_events", "derived_records")]
        if exposure != [len(rows), 2 * len(rows)]:
            raise ValueError("original versus derived exposure differs")
        groups, ids, shards = defaultdict(list), set(), {}
        zero = True
        for row in rows:
            _keys(row, {"event_id", "group_id", "shard_id", "baseline", "candidate"})
            event = _text(row["event_id"])
            if event in ids:
                raise ValueError("duplicate original event ID")
            ids.add(event)
            shard, group = _text(row["shard_id"]), _text(row["group_id"])
            if group in shards and shards[group] != shard:
                raise ValueError("correlation group spans shards")
            shards[group] = shard
            vector = []
            for arm in ("baseline", "candidate"):
                _keys(row[arm], {"bins", "denominator"})
                bins = row[arm]["bins"]
                if not isinstance(bins, list) or len(bins) != size:
                    raise ValueError("arm channel count differs")
                vector.extend(_number(v) for v in bins)
                vector.append(_number(row[arm]["denominator"]))
            zero = zero and all(Fraction(v) == 0 for v in vector)
            groups[group].append(vector)
        # Group membership matters. Names, row order and group order do not.
        grouped = [sorted(vectors, key=lambda v: json.dumps(v)) for vectors in groups.values()]
        numeric = {"schema": kind, "channels": size, "exposure": exposure,
                   "groups": sorted(grouped, key=lambda v: json.dumps(v)), "bin_volumes": semantic["bin_volumes"]}
    else:
        raise ValueError("unsupported numerical-content schema")
    return {"numerical_sha256": _digest(numeric), "semantic_sha256": _digest(semantic),
            "source_sha256": hashlib.sha256(raw).hexdigest(), "all_zero_values": zero}


def report(artifacts):
    """Report copy obligations; NEVER assert independence or change source files."""
    if not isinstance(artifacts, dict) or not 0 < len(artifacts) <= MAX_ARTIFACTS:
        raise ValueError("artifacts must be a bounded nonempty ID-to-bytes mapping")
    entries, groups = [], defaultdict(list)
    for artifact_id, raw in artifacts.items():
        entry = {"id": _text(artifact_id), **fingerprints(raw), "independence_status": "unresolved"}
        entries.append(entry); groups[entry["numerical_sha256"]].append(entry)
    obligations = [{"kind": "numerical_duplicate_independence", "artifact_ids": [e["id"] for e in group],
                    "semantic_identity_equal": len({e["semantic_sha256"] for e in group}) == 1,
                    "reason": "Same numerical content cannot automatically count as another independent anchor; review source, producer, runtime and population evidence."}
                   for group in groups.values() if len(group) > 1]
    return {"schema_version": 1, "kind": "evidence_independence_report", "status": "unresolved",
            "artifacts": entries, "obligations": obligations, "physics_validated": False,
            "independence_certified": False, "quarantine_applied": False,
            "limitations": ["Numerical equality does not prove dependent sampling; independent deterministic controls can coincide.",
                            "Different numerical content does not establish source or sampling independence.",
                            "Digests cover the declared schema and ordered numerical axes; semantic/provenance review remains required."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", action="append", required=True, metavar="ID=PATH")
    parser.add_argument("--out",type=Path)
    args = parser.parse_args(argv)
    try:
        artifacts = {}
        for argument in args.artifact:
            artifact_id, separator, name = argument.partition("=")
            if not separator or artifact_id in artifacts:
                raise ValueError("artifact needs a unique ID=PATH")
            path = Path(name)
            with path.open("rb") as stream:
                artifacts[artifact_id] = stream.read(MAX_BYTES + 1)
        result = report(artifacts)
        rendered = json.dumps(result,indent=2,allow_nan=False)+"\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(rendered)
        print(rendered,end="")
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,str(exc)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
