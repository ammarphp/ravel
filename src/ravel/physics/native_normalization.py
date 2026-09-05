"""Normalization evidence for the bounded unmerged native pipeline (stdlib only).

Cross sections in an LHE init block are pb by the LHE convention. The native
Pythia writer reports mb explicitly. Neither a missing rate nor a missing event
weight has a numerical fallback. This validates normalization bookkeeping, not
the physical accuracy of a generator, detector card or correction.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from decimal import Decimal


def positive(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} is unresolved or not numeric") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def fingerprint(path):
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def weight_summary(weights):
    values = list(map(float, weights))
    if not values or any(not math.isfinite(v) for v in values):
        raise ValueError("nominal event weights must be present and finite")
    try:
        total, squared = math.fsum(values), math.fsum(v*v for v in values)
    except OverflowError as exc:
        raise ValueError("nominal event weight sums overflow") from exc
    # A positive physical cross section may include negative individual weights,
    # but cannot normalize a non-positive total by silently reversing its sign.
    positive(total, "sum of nominal event weights")
    positive(squared, "sum of squared nominal event weights")
    return {"n_events": len(values), "sumw": total, "sumw2": squared,
            "negative_weights": sum(v < 0 for v in values)}


def read_lhe(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    init, weights, rows = [], [], []
    in_init = in_event = False
    closed = False
    with opener(path, "rt") as stream:
        for raw in stream:
            line = raw.split("#", 1)[0].strip()
            if line == "<init>":
                if init:
                    raise ValueError("multiple LHE init blocks")
                in_init = True
            elif line == "</init>":
                in_init = False
            elif in_init and line:
                init.append(line.split())
            elif line == "<event>":
                if in_event:
                    raise ValueError("unterminated LHE event")
                in_event, rows = True, []
            elif line == "</event>":
                if not in_event or not rows:
                    raise ValueError("empty or malformed LHE event")
                header = rows[0]
                try:
                    particles = int(header[0])
                    if particles < 1 or len(rows) < particles + 1:
                        raise ValueError("truncated particle rows")
                    weights.append(float(header[2]))
                except (ValueError, IndexError) as exc:
                    raise ValueError("invalid LHE event header/particle count") from exc
                in_event = False
            elif in_event and line and not line.startswith("<"):
                rows.append(line.split())
            elif line == "</LesHouchesEvents>":
                closed = True
    if in_event or in_init or not closed:
        raise ValueError("truncated LHE document")
    try:
        nprocess = int(init[0][9])
        if nprocess < 1 or len(init) != nprocess + 1:
            raise ValueError("LHE subprocess count does not match init block")
        rates = [positive(row[0], "LHE subprocess cross section (pb)") for row in init[1:]]
        sigma = positive(math.fsum(rates), "LHE cross section (pb)")
    except (IndexError, OverflowError) as exc:
        raise ValueError("missing or malformed LHE cross section") from exc
    return {"cross_section_pb": sigma, **weight_summary(weights)}


def reconcile_weights(raw, normalized, xs_pb, *, rel_tol=2e-6):
    """Check every converted nominal weight, including negative weights."""
    before = weight_summary(raw)
    after = weight_summary(normalized)
    xs_pb = positive(xs_pb, "applied cross section (pb)")
    if len(raw) != len(normalized):
        raise ValueError("conversion changed event count")
    scale = xs_pb / before["sumw"]
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("weight normalization scale is unusable")
    for old, new in zip(raw, normalized):
        expected = float(old) * scale
        if not math.isclose(float(new), expected, rel_tol=rel_tol, abs_tol=abs(scale)*1e-12):
            raise ValueError("converted nominal weights do not match declared cross-section normalization")
    if not math.isclose(after["sumw"], xs_pb, rel_tol=rel_tol):
        raise ValueError("converted weight sum does not reproduce cross section")
    return {"raw": before, "normalized": after, "scale_pb_per_weight": scale,
            "applied_cross_section_pb": xs_pb, "luminosity_applied": False}


def resolve_normalization(lhe, madgraph_log, shower_log, kfactor, nevents):
    evidence = read_lhe(lhe)
    kfactor = positive(kfactor, "explicit kfactor")  # k < 1 is allowed.
    if type(nevents) is not int or nevents < 1:
        raise ValueError("requested event count must be a positive integer")
    if evidence["n_events"] != nevents:
        raise ValueError("generated event count differs from the execution plan")
    # The LHE rate is authoritative. A log is only a corroborating representation
    # and may omit the summary on resumed generator runs.
    rate = evidence["cross_section_pb"]
    text = Path(madgraph_log).read_text(errors="replace")
    records = re.findall(r"Cross-section[^\n]*", text)
    if records:
        match = re.fullmatch(r"Cross-section\s*:\s*(\S+)(?:\s+\+-\s+\S+)?\s+(\w+)\s*", records[-1])
        if not match or match[2] != "pb":
            raise ValueError("MadGraph cross-section summary has unsupported units")
        value = match[1]
        reported = positive(value, "MadGraph cross section")
        precision = float(Decimal(1).scaleb(Decimal(value).as_tuple().exponent))/2
        if not math.isclose(reported, rate, rel_tol=1e-8, abs_tol=precision):
            raise ValueError("MadGraph log and LHE cross sections disagree")
    shower = re.findall(r"pythia_shower:\s*wrote\s+(\d+)\s+events;\s*sigma\s*=\s*([^\s]+)\s+(\w+)",
                        Path(shower_log).read_text(errors="replace"))
    if len(shower) != 1:
        raise ValueError("missing or ambiguous native shower normalization report")
    count, value, unit = shower[0]
    if unit != "mb":
        raise ValueError("native shower cross section must be explicitly in mb")
    shower_pb = positive(value, "shower cross section (mb)") * 1e9
    if int(count) != nevents:
        raise ValueError("unmerged shower did not preserve the generated event count")
    if not math.isfinite(shower_pb) or not math.isclose(rate, shower_pb, rel_tol=1e-4):
        raise ValueError("unmerged shower and LHE cross sections disagree")
    applied = positive(rate * kfactor, "corrected cross section (pb)")
    return {"schema_version": 1, "status": "resolved", "basis": "unmerged_lo_lhe",
            "cross_section_pb": rate, "kfactor": kfactor, "applied_cross_section_pb": applied,
            "correction_applications": 1, "luminosity_applied": False,
            "generation": evidence, "shower": {"n_events": int(count), "cross_section_pb": shower_pb},
            "sources": [fingerprint(p) for p in (lhe, madgraph_log, shower_log)]}


def load_normalization(path):
    record = json.loads(Path(path).read_text())
    if record.get("status") != "resolved" or record.get("luminosity_applied") is not False:
        raise ValueError("normalization is unresolved or luminosity was already applied")
    base = positive(record.get("cross_section_pb"), "cross section (pb)")
    correction = positive(record.get("kfactor"), "explicit correction")
    applied = positive(record.get("applied_cross_section_pb"), "applied cross section (pb)")
    if record.get("correction_applications") != 1 or not math.isclose(base*correction, applied, rel_tol=1e-12):
        raise ValueError("cross-section corrections do not reconcile exactly once")
    for source in record.get("sources", []):
        if fingerprint(source["path"])["sha256"] != source["sha256"]:
            raise ValueError("normalization source changed")
    if not record.get("sources"):
        raise ValueError("normalization lacks source evidence")
    sources=record["sources"]
    if len(sources)!=3 or not isinstance(record.get("generation"),dict):
        raise ValueError("normalization requires LHE, MadGraph and shower evidence")
    expected=resolve_normalization(*(source["path"] for source in sources),correction,record["generation"].get("n_events"))
    if record!=expected:
        raise ValueError("normalization fields do not reconcile with generated/showered evidence")
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("lhe", "madgraph-log", "shower-log", "out"):
        parser.add_argument("--"+name, required=True)
    parser.add_argument("--kfactor", type=float, required=True)
    parser.add_argument("--nevents", type=int, required=True)
    args = parser.parse_args(argv)
    result = resolve_normalization(args.lhe, args.madgraph_log, args.shower_log, args.kfactor, args.nevents)
    Path(args.out).write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")


if __name__ == "__main__":
    main()
