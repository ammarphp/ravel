"""Independent, bounded exact checker for paired normalized group moments.

Input schema 1, kind ``paired_normalized_rows``: basis contains quantity, unit,
normalization (all_events/in_range), role, channels, checked_weight_stream,
representation (integrated/differential), and positive bin_volumes. Records
contain original event_id/group_id/shard_id and baseline/candidate objects with
RAW integrated weighted bins and an arm-specific weighted denominator. Each
arm allows at most one nonzero bin per original event. Groups cannot span shards.
Exposure declares original_events and derived_records (two arms per original).
original_source_sha256 binds separately supplied original_event_census bytes.
The census schema has schema_version, kind, records with only the three IDs.

``derive`` produces an UNVERIFIED exact rational claim. ``verify`` checks a
claim against original rows using group derivatives, with externally expected
checker, input, claim and census hashes. Only standard-library imports are used.
The checker does not establish selection correctness, independent grouping,
statistical coverage, converter provenance or physics validity. Explicit
fixed_iid_groups multiplies group-derivative covariance by G/(G-1); otherwise
poissonized_independent_groups uses the uncorrected second moment. Runtime
metadata is observational; this API does not authenticate actors or environments.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

MAX_BYTES, MAX_ROWS, MAX_CHANNELS = 4_194_304, 20_000, 32
MAX_WORK, MAX_TOKEN, MAX_EXPONENT = 2_000_000, 128, 128


def _decimal(token):
    if len(token) > MAX_TOKEN:
        raise ValueError("numeric token exceeds limit")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not value.is_finite() or abs(value.as_tuple().exponent) > MAX_EXPONENT:
        raise ValueError("nonfinite or oversized decimal exponent")
    return Fraction(value)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def loads(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("input must be bounded JSON bytes")
    def integer(token):
        _decimal(token)
        return int(token)
    def constant(_):
        raise ValueError("nonfinite JSON constant")
    try:
        return json.loads(raw, parse_float=_decimal, parse_int=integer,
                          parse_constant=constant, object_pairs_hook=_pairs)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid or excessively nested JSON") from exc


def _keys(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError("unknown or missing schema fields")


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("invalid or oversized label")
    return value


def _number(value, *, claim=False):
    if type(value) is bool:
        raise ValueError("boolean is not numerical")
    if isinstance(value, Fraction):
        result = value
    elif type(value) is int:
        result = _decimal(str(value))
    elif isinstance(value, Decimal) or (type(value) is float and math.isfinite(value)):
        result = _decimal(str(value))
    elif claim and isinstance(value, str) and len(value) <= 4096:
        if "/" not in value:
            result = _decimal(value)
        else:
            parts = value.split("/")
            if (len(parts) != 2 or any(len(p) > 1024 or not p.lstrip("+-").isascii()
                                      or not p.lstrip("+-").isdigit() for p in parts)):
                raise ValueError("invalid or oversized rational claim")
            try:
                result = Fraction(int(parts[0]), int(parts[1]))
            except (ValueError, ZeroDivisionError) as exc:
                raise ValueError("invalid rational claim") from exc
    else:
        raise ValueError("numerical field is nonfinite or unsupported")
    if max(result.numerator.bit_length(), result.denominator.bit_length()) > 4096:
        raise ValueError("oversized rational")
    return result


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("expected SHA256 must be lowercase hexadecimal")
    return value


def checker_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _version(data, kind):
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1 or data.get("kind") != kind:
        raise ValueError("unsupported schema or kind")


def _identities(rows):
    if not isinstance(rows, list) or not 0 < len(rows) <= MAX_ROWS:
        raise ValueError("invalid original census size")
    identities, ids, shards = [], set(), {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("original row must be an object")
        identity = tuple(_text(row[k]) for k in ("event_id", "group_id", "shard_id"))
        event, group, shard = identity
        if event in ids:
            raise ValueError("duplicate original event ID")
        if group in shards and shards[group] != shard:
            raise ValueError("correlation group spans shards")
        ids.add(event); shards[group] = shard; identities.append(identity)
    return sorted(identities)


def _prepare(payload):
    data = loads(payload) if isinstance(payload, bytes) else payload
    _keys(data, {"schema_version", "kind", "basis", "uncertainty_model", "original_source_sha256", "exposure", "records"})
    _version(data, "paired_normalized_rows")
    _sha(data["original_source_sha256"])
    fields = {"quantity", "unit", "normalization", "role", "channels", "checked_weight_stream", "representation", "bin_volumes"}
    _keys(data["basis"], fields)
    basis = dict(data["basis"])
    for key in fields - {"channels", "bin_volumes"}:
        _text(basis[key])
    if basis["normalization"] not in ("all_events", "in_range") or basis["representation"] not in ("integrated", "differential"):
        raise ValueError("unsupported normalization or representation")
    names = basis["channels"]
    if not isinstance(names, list) or not 0 < len(names) <= MAX_CHANNELS or len(set(map(_text, names))) != len(names):
        raise ValueError("invalid channel list")
    n = len(names)
    if not isinstance(basis["bin_volumes"], list) or len(basis["bin_volumes"]) != n:
        raise ValueError("bin volume dimensions differ")
    volumes = [_number(v) for v in basis["bin_volumes"]]
    if any(v <= 0 for v in volumes):
        raise ValueError("bin volumes must be positive")
    basis["bin_volumes"] = list(map(str, volumes))
    if data["uncertainty_model"] not in ("poissonized_independent_groups", "fixed_iid_groups"):
        raise ValueError("unsupported uncertainty model")
    rows = data["records"]
    identities = _identities(rows)
    if len(rows) * n * n > MAX_WORK:
        raise ValueError("row-channel work budget exceeded")
    _keys(data["exposure"], {"original_events", "derived_records"})
    if any(type(v) is not int for v in data["exposure"].values()) or data["exposure"] != {"original_events": len(rows), "derived_records": 2 * len(rows)}:
        raise ValueError("original versus derived exposure differs")
    groups = {}
    for row in rows:
        _keys(row, {"event_id", "group_id", "shard_id", "baseline", "candidate"})
        pair = groups.setdefault(row["group_id"], [[Fraction(0)] * (n + 1) for _ in range(2)])
        for a, arm in enumerate(("baseline", "candidate")):
            _keys(row[arm], {"bins", "denominator"})
            bins = row[arm]["bins"]
            if not isinstance(bins, list) or len(bins) != n:
                raise ValueError("arm bin dimensions differ")
            values = [_number(v) for v in bins]
            denominator = _number(row[arm]["denominator"])
            nonzero = [v for v in values if v]
            if len(nonzero) > 1:
                raise ValueError("initial witness requires exclusive one-fill shape")
            if basis["normalization"] == "in_range" and sum(values) != denominator:
                raise ValueError("in_range denominator differs from raw bin contributions")
            if nonzero and nonzero[0] != denominator:
                raise ValueError("raw weighted bin differs from original arm denominator")
            for i, value in enumerate([*values, denominator]):
                pair[a][i] += value
    return data, basis, groups, volumes, identities


def derive(payload):
    """Compute an unverified exact rational claim from the declared original rows."""
    data, basis, groups, volumes, _ = _prepare(payload)
    n = len(volumes)
    totals = [[sum((pair[a][i] for pair in groups.values()), Fraction(0)) for i in range(n + 1)] for a in range(2)]
    exposure = {**data["exposure"], "independent_groups": len(groups)}
    result = {"schema_version": 1, "kind": "paired_normalized_moments", "status": "computed",
              "basis": basis, "uncertainty_model": data["uncertainty_model"], "exposure": exposure,
              "denominators": {arm: str(totals[a][-1]) for a, arm in enumerate(("baseline", "candidate"))},
              "values": None, "covariance": None, "physics_validated": False, "arithmetic_verified": False}
    if any(t[-1] <= 0 for t in totals):
        result.update(status="unresolved", reason="Nonpositive signed denominator; no normalized moment or zero uncertainty is inferred.")
        return result
    if data["uncertainty_model"] == "fixed_iid_groups" and len(groups) < 2:
        result.update(status="unresolved", reason="Fixed-IID group covariance requires at least two independent groups.")
        return result
    correction = Fraction(len(groups), len(groups)-1) if data["uncertainty_model"] == "fixed_iid_groups" else Fraction(1)
    fractions = [[t[i] / t[-1] for i in range(n)] for t in totals]
    divisors = volumes if basis["representation"] == "differential" else [Fraction(1)] * n
    values = [[f / divisors[i] for i, f in enumerate(arm)] for arm in fractions]
    derivatives = [[[ (pair[a][i] - fractions[a][i] * pair[a][-1]) / totals[a][-1] / divisors[i]
                       for i in range(n)] for a in range(2)] for pair in groups.values()]
    def covariance(a, b):
        return [[correction * sum((pair[a][i] * pair[b][j] for pair in derivatives), Fraction(0)) for j in range(n)] for i in range(n)]
    ca, cb, cross = covariance(0, 0), covariance(1, 1), covariance(0, 1)
    difference = [[correction * sum(((pair[1][i]-pair[0][i])*(pair[1][j]-pair[0][j]) for pair in derivatives), Fraction(0)) for j in range(n)] for i in range(n)]
    result["values"] = {"baseline": list(map(str, values[0])), "candidate": list(map(str, values[1])),
                        "difference": [str(b-a) for a,b in zip(*values)]}
    result["covariance"] = {name: [[str(v) for v in row] for row in matrix]
                            for name,matrix in (("baseline",ca),("candidate",cb),("cross",cross),("difference",difference))}
    return result


def verify(input_bytes, claim_bytes, *, expected_checker_sha256, expected_input_sha256,
           expected_output_sha256, original_source_bytes, expected_original_source_sha256,
           atol="0", rtol="0"):
    """Check exact/tolerance-bound arithmetic against external custody identities."""
    identities = {"checker_sha256": checker_sha256()}
    if identities["checker_sha256"] != _sha(expected_checker_sha256):
        raise ValueError("checker source identity differs")
    for name, raw, expected in (("input_sha256",input_bytes,expected_input_sha256),
                                ("output_sha256",claim_bytes,expected_output_sha256),
                                ("original_source_sha256",original_source_bytes,expected_original_source_sha256)):
        if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
            raise ValueError("artifact exceeds byte limit")
        identities[name] = hashlib.sha256(raw).hexdigest()
        if identities[name] != _sha(expected):
            raise ValueError(name + " differs from external expected identity")
    census = loads(original_source_bytes)
    _keys(census, {"schema_version", "kind", "records"}); _version(census, "original_event_census")
    for row in census["records"]:
        _keys(row, {"event_id", "group_id", "shard_id"})
    original = _identities(census["records"])
    data, _, _, _, projected = _prepare(input_bytes)
    if data["original_source_sha256"] != identities["original_source_sha256"] or original != projected:
        raise ValueError("projection differs from complete original source census")
    expected, claim = derive(input_bytes), loads(claim_bytes)
    _keys(claim, set(expected)); _version(claim, "paired_normalized_moments")
    absolute, relative = _number(atol, claim=True), _number(rtol, claim=True)
    if not 0 <= absolute <= 1 or not 0 <= relative <= 1:
        raise ValueError("arithmetic tolerances must be between zero and one")
    mismatches = []
    def compare(actual, wanted, location=""):
        if isinstance(wanted, dict):
            if not isinstance(actual, dict) or set(actual) != set(wanted):
                raise ValueError("claim fields differ at " + location)
            for key in wanted:
                compare(actual[key], wanted[key], location + "/" + key)
        elif isinstance(wanted, list):
            if not isinstance(actual, list) or len(actual) != len(wanted):
                raise ValueError("claim dimensions differ at " + location)
            for i,(a,b) in enumerate(zip(actual,wanted)):
                compare(a,b,location + "/" + str(i))
        elif location.startswith(("/values/", "/covariance/", "/denominators/", "/basis/bin_volumes/")):
            a,b = _number(actual,claim=True), _number(wanted,claim=True)
            tolerance = 0 if location.startswith("/basis/") else absolute + relative * abs(b)
            if abs(a-b) > tolerance:
                mismatches.append(location)
        elif type(actual) is not type(wanted) or actual != wanted:
            mismatches.append(location)
    compare(claim,expected)
    status = "mismatch" if mismatches else "unresolved" if expected["status"] == "unresolved" else "verified"
    # Re-read only this owned checker; no producer source is imported or trusted.
    if checker_sha256() != expected_checker_sha256:
        raise ValueError("checker source changed during verification")
    return {"schema_version":1, "kind":"numerical_witness_receipt", "status":status,
            "arithmetic_verified":status == "verified", "physics_validated":False,
            "identities":identities, "mismatches":mismatches, "exposure":expected["exposure"],
            "arithmetic_tolerance":{"atol":str(absolute),"rtol":str(relative)},
            "runtime":{"python":sys.version.split()[0],"executable":sys.executable},
            "limitations":["Arithmetic under supplied grouping, arm contributions and normalization only; no statistical coverage or physics certificate.",
                           "Census bytes are checked; provenance of a converter from raw physics artifacts remains a separate obligation.",
                           "Runtime metadata is observational; interpreter/environment admission and actor authentication are external obligations.",
                           "Tolerance concerns serialization/arithmetic, not Monte Carlo or reference uncertainty."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command",required=True)
    derive_parser = commands.add_parser("derive")
    verify_parser = commands.add_parser("verify")
    for p in (derive_parser,verify_parser):
        p.add_argument("--input",required=True,type=Path); p.add_argument("--out",type=Path)
    verify_parser.add_argument("--claim",required=True,type=Path)
    verify_parser.add_argument("--original-source",required=True,type=Path)
    for flag in ("checker-sha256","input-sha256","claim-sha256","original-source-sha256"):
        verify_parser.add_argument("--"+flag,required=True)
    verify_parser.add_argument("--atol",default="0"); verify_parser.add_argument("--rtol",default="0")
    args = parser.parse_args(argv)
    def read(path):
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("artifact exceeds byte limit")
        return raw
    try:
        if args.command == "derive":
            result = derive(read(args.input))
        else:
            result = verify(read(args.input),read(args.claim),expected_checker_sha256=args.checker_sha256,
                            expected_input_sha256=args.input_sha256,expected_output_sha256=args.claim_sha256,
                            original_source_bytes=read(args.original_source),expected_original_source_sha256=args.original_source_sha256,
                            atol=args.atol,rtol=args.rtol)
        rendered = json.dumps(result,indent=2,allow_nan=False)+"\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(rendered)
        print(rendered,end="")
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,str(exc)+"\n")
    return 0 if args.command == "derive" or result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
