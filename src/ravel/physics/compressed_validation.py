"""Event-bound diagnostics for the compressed slepton selection.

Physics predicates are recorded by the production selection, never reconstructed
here. Public cutflow comparisons remain diagnostic when reference predicates or
the inclusive/generated-sample denominator cannot be matched.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

PREFIX = ("bad_jet_veto", "baseline_lepton", "signal_jet")
COMMON = ("two_signal_leptons", "jpsi_veto", "min_jet_met_dphi", "leading_jet_met_dphi",
          "mll_window", "lepton_separation", "leading_lepton_pt", "jet_count",
          "leading_jet_pt", "b_veto", "mtautau_veto", "same_flavour", "opposite_charge", "met_preselection")
MT2 = tuple(f"mt2_lt_{x}" for x in (140, 130, 120, 110, 105, 102, 101, "100p5"))
UNAVAILABLE = {"generator_filter": "No matching ATLAS generator-filter event population",
               "trigger": "No measured trigger decision or efficiency in Delphes2SA",
               "author16_veto": "ATLAS lepton author unavailable in Delphes2SA",
               "truth_matching": "Delphes2SA mother pointers do not retain truth matches"}
PREDICATES = tuple(dict.fromkeys((*PREFIX, *COMMON, "mt2_gt_100", *MT2,
    *(f"{quantity}_{band}" for band in ("high", "low") for quantity in ("met", "risr", "subleading_pt")),
    *UNAVAILABLE)))
REFERENCE_ROWS = {0: "inclusive_normalization", 1: "generator_filter", 2: "trigger",
    3: "two_signal_leptons", 4: "jpsi_veto", 5: "author16_veto",
    6: "min_jet_met_dphi", 7: "leading_jet_met_dphi", 8: "truth_matching",
    9: "mll_window", 10: "lepton_separation", 11: "leading_lepton_pt",
    12: "jet_count", 13: "leading_jet_pt", 14: "b_veto", 15: "mtautau_veto", 16: "same_flavour"}


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def new_event(event_id, weight):
    if type(event_id) is not int or not math.isfinite(float(weight)):
        raise ValueError("trace needs an integer event ID and finite original weight")
    return {"event_id": event_id, "weight_pb": float(weight),
            "predicates": dict.fromkeys(PREDICATES), "objects": {}, "kinematics": {},
            "rjr_status": "not_reached", "origin_state": None, "accepted_regions": []}


def _validated(record):
    if type(record.get("event_id")) is not int:
        raise ValueError("trace event ID must be an integer")
    value = record.get("weight_pb")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("trace weight must be finite")
    predicates = record.get("predicates")
    if not isinstance(predicates, dict) or set(predicates) != set(PREDICATES):
        raise ValueError("trace predicate population is incomplete or unknown")
    if any(value is not None and type(value) is not bool for value in predicates.values()):
        raise ValueError("trace predicates must be boolean or null")
    if any(predicates[key] is not None for key in UNAVAILABLE):
        raise ValueError("unrepresented ATLAS predicates cannot be promoted to measured decisions")
    regions = record.get("accepted_regions")
    if (not isinstance(regions, list) or any(not isinstance(x, str) for x in regions)
            or len(set(regions)) != len(regions)):
        raise ValueError("trace region membership must contain unique names")
    json.dumps(record, allow_nan=False)
    return record


def write_trace(path, records, metadata):
    """Write deterministic gzip JSONL; reject duplicates and nonfinite evidence."""
    path = Path(path)
    seen = set()
    with path.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as stream:
        header = {"kind": "header", "schema_version": 1, "level": "reco",
                  "weight_unit": "pb", "metadata": metadata, "unavailable": UNAVAILABLE}
        stream.write((json.dumps(header, sort_keys=True, allow_nan=False)+"\n").encode())
        for record in records:
            _validated(record)
            if record["event_id"] in seen:
                raise ValueError("duplicate trace event ID")
            seen.add(record["event_id"])
            stream.write((json.dumps(record, sort_keys=True, allow_nan=False)+"\n").encode())


def _and(left, right):
    return False if left is False or right is False else (None if left is None or right is None else True)


def _moments():
    return {"count": 0, "sumw_pb": 0.0, "sumw2_pb2": 0.0, "unknown_count": 0}


def _add(moment, weight, passed):
    if passed is True:
        moment["count"] += 1
        moment["sumw_pb"] += weight
        moment["sumw2_pb2"] += weight*weight
    elif passed is None:
        moment["unknown_count"] += 1


def _ratio(numerator, denominator):
    # Nested masks share events: Cov(sumw_pass,sumw_before) = sumw2_pass.
    d, n = denominator["sumw_pb"], numerator["sumw_pb"]
    if d == 0 or numerator["unknown_count"] or denominator["unknown_count"]:
        return {"status": "unresolved", "ratio": None, "mc_standard_error": None}
    ratio = n/d
    if numerator["count"] == 0 or numerator["sumw2_pb2"] == 0:
        return {"status": "zero_selected_precision_unresolved", "ratio": ratio,
                "mc_standard_error": None, "method": "No finite-MC upper bound inferred from zero selected weight"}
    variance = (numerator["sumw2_pb2"]*(1-2*ratio)
                + ratio*ratio*denominator["sumw2_pb2"])/(d*d)
    return {"status": "estimated", "ratio": ratio,
            "mc_standard_error": math.sqrt(max(0.0, variance)),
            "method": "delta method with shared-event covariance; no reference uncertainty included"}


def summarize_trace(path, reference_directory=None):
    rows = {band: [*PREFIX, *COMMON, f"met_{band}", f"risr_{band}",
                    f"subleading_pt_{band}", "mt2_gt_100", *MT2]
            for band in ("high", "low")}
    moments = {band: {key: _moments() for key in keys} for band, keys in rows.items()}
    all_events, seen, selected = _moments(), set(), {}
    with gzip.open(path, "rt") as stream:
        header = json.loads(next(stream))
        if (header.get("schema_version") != 1 or header.get("kind") != "header"
                or header.get("level") != "reco" or header.get("weight_unit") != "pb"):
            raise ValueError("unsupported trace header")
        for line in stream:
            record = _validated(json.loads(line))
            event_id, weight = record["event_id"], record["weight_pb"]
            if event_id in seen:
                raise ValueError("duplicate trace event ID")
            seen.add(event_id)
            _add(all_events, weight, True)
            for region in record["accepted_regions"]:
                _add(selected.setdefault(region, _moments()), weight, True)
            for band, keys in rows.items():
                mask = True
                for key in keys:
                    mask = _and(mask, record["predicates"][key])
                    _add(moments[band][key], weight, mask)
                # Any one exclusive bin implies exactly the regional mT2<140 mask.
                inclusive_mask = True
                for key in keys[:keys.index("mt2_lt_140")+1]:
                    inclusive_mask = _and(inclusive_mask, record["predicates"][key])
                matches = [name for name in record["accepted_regions"] if name.startswith(f"SR_S_{band}_eMT2")]
                if (len(matches) > 1 or (matches and inclusive_mask is None)
                        or (inclusive_mask is not None and bool(matches) != inclusive_mask)):
                    raise ValueError("trace predicates disagree with production slepton membership")
    if not seen:
        raise ValueError("empty event trace")
    expected = header["metadata"].get("input_events")
    if expected is not None and (type(expected) is not int or expected != len(seen)):
        raise ValueError("trace event population disagrees with declared input count")
    cutflows = {}
    for band, keys in rows.items():
        previous = all_events
        cutflows[band] = []
        for key in keys:
            current = moments[band][key]
            cutflows[band].append({"predicate": key, **current, "conditional": _ratio(current, previous),
                                  "cumulative": _ratio(current, all_events)})
            previous = current
    result = {"schema_version": 1, "trace_sha256": file_hash(path), "source_metadata": header["metadata"],
        "level": "reco", "all_events": all_events, "cutflows": cutflows, "regions": selected,
        "unknown_reference_predicates": UNAVAILABLE, "truth_acceptance": {"status": "unavailable"},
        "input_population_status": "verified_count" if expected is not None else "input_count_not_declared",
        "earliest_unrepresented_reference_stage": "generator_filter",
        "first_comparable_reference_divergence": None,
        "comparison_status": "No exact public-cutflow comparison: generator/trigger/author/truth predicates unavailable",
        "reference_discrepancies": ["Table22 RISR label lacks the (mT2-100) subtraction present in paper Table5 and code",
            "Generic table mll>1 label omits the code's ee>3 floor",
            "Opposite-charge and production object preconditions have no separately matched table rows"],
        "weight_scope": "Original normalized SA weights in pb; generated-sample total is not automatically inclusive4"}
    if reference_directory is not None:
        if header["metadata"].get("masses_gev") != [150, 140]:
            raise ValueError("public cutflow comparison requires declared m150/140 metadata")
        import yaml
        comparisons = {}
        for band, filename in (("high", "table_22.yaml"), ("low", "table_23.yaml")):
            source = Path(reference_directory)/filename
            table = yaml.safe_load(source.read_text())
            weighted = [float(row["value"]) for row in table["dependent_variables"][0]["values"]]
            if len(weighted) != 28 or any(not math.isfinite(x) or x < 0 for x in weighted):
                raise ValueError("unexpected public m150/140 cutflow population")
            mapping = REFERENCE_ROWS | {17: f"met_{band}", 18: f"risr_{band}", 19: f"subleading_pt_{band}"}
            mapping.update({20+i: key for i, key in enumerate(MT2)})
            comparisons[band] = {"source_sha256": file_hash(source), "source_filename": filename,
                "reference_luminosity_pb_inverse": 140000,
                "rows": [{"reference_row_index": index, "predicate": key,
                    "reference_weighted_events": weighted[index],
                    "reference_conditional_ratio": weighted[index]/weighted[index-1] if index and weighted[index-1] else None,
                    "native_cumulative_weighted_events_at_reference_lumi":
                        moments[band][key]["sumw_pb"]*140000 if key in moments[band] else None,
                    "status": "diagnostic_only_unmatched_prior_predicates"}
                    for index, key in sorted(mapping.items())]}
        result["reference_cutflows"] = comparisons
    json.dumps(result, allow_nan=False)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--reference-directory")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = summarize_trace(args.trace, args.reference_directory)
    Path(args.out).write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
