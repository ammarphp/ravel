#!/usr/bin/env python3
"""Independent LHE delivery audit for the bounded SM Drell-Yan control.

This checks the requested event record, not detector fidelity or precision theory.
It deliberately does not import the pipeline or a competitor's analysis code.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re


def _number(value):
    number = float(value.replace("D", "e").replace("d", "e"))
    if not math.isfinite(number):
        raise ValueError("nonfinite LHE number")
    return number


def audit_text(text, *, events=100, seed=1729, beam_gev=6500.0):
    init = re.search(r"<init>\s*(.*?)\s*</init>", text, re.S)
    if not init:
        raise ValueError("LHE init block missing")
    lines = [line.split("#", 1)[0].strip() for line in init[1].splitlines()]
    lines = [line for line in lines if line]
    beam = lines[0].split()
    if len(beam) != 10:
        raise ValueError("invalid LHE init header")
    nprocess = int(beam[9])
    if nprocess < 1:
        raise ValueError("LHE process census must be positive")
    processes = [[_number(x) for x in line.split()] for line in lines[1:] if not line.startswith("<")]
    if len(processes) != nprocess or any(len(row) != 4 for row in processes):
        raise ValueError("LHE process census differs from init header")
    xsec = sum(row[0] for row in processes)
    xerr = math.sqrt(sum(row[1] ** 2 for row in processes))
    checks = {
        "proton_beams": [int(beam[0]), int(beam[1])] == [2212, 2212],
        "beam_energies": all(_number(x) == beam_gev for x in beam[2:4]),
        "positive_cross_section_and_error": xsec > 0 and xerr > 0 and all(row[1] >= 0 for row in processes),
        "cteq6l1_pdf_ids": [int(x) for x in beam[6:8]] == [10042, 10042],
        # MG5 may encode an unweighted sample with constant cross-section
        # weights (IDWTUP=-4). Keep the convention explicit; test the actual
        # weights below instead of requiring unit weights or IDWTUP=3.
        "supported_weight_convention": int(beam[8]) in (3, -3, 4, -4),
    }
    # Inspect the immutable event-file banner, not a working run card whose
    # seed MadGraph may reset after generation.
    header = text.split("</header>", 1)[0]
    checks["seed_in_banner"] = bool(re.search(rf"(?m)^\s*{seed}\s*=\s*iseed\b", header))
    checks["cteq6l1_in_banner"] = bool(re.search(r"(?mi)^\s*['\"]?cteq6l1['\"]?\s*=\s*pdlabel\b", header))
    masses, weights, failed_events = [], [], []
    blocks = re.findall(r"<event(?:\s[^>]*)?>\s*(.*?)</event>", text, re.S)
    checks["complete_event_framing"] = (
        len(re.findall(r"<event(?:\s[^>]*)?>", text)) == len(blocks)
        == text.count("</event>")
        and text.rstrip().endswith("</LesHouchesEvents>")
    )
    for index, block in enumerate(blocks):
        lines = [line.strip() for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if not lines or len(lines[0].split()) != 6:
            raise ValueError("invalid LHE event header")
        event = lines[0].split()
        count = int(event[0])
        if count < 2:
            raise ValueError("invalid LHE particle count")
        weights.append(_number(event[2]))
        if len(lines) < count + 1:
            raise ValueError("truncated LHE particle record")
        particles = [line.split() for line in lines[1:count + 1]]
        if any(len(row) != 13 for row in particles):
            raise ValueError("invalid LHE particle row")
        final = [row for row in particles if int(row[1]) == 1]
        reasons = []
        if sorted(int(row[0]) for row in final) != [-11, 11]:
            reasons.append("final_state")
        else:
            momenta = [[_number(x) for x in row[6:10]] for row in final]
            for px, py, pz, energy in momenta:
                pt = math.hypot(px, py)
                eta = math.asinh(pz / pt) if pt else math.inf
                if not pt > 10.0 - 1e-8:
                    reasons.append("lepton_pt")
                if not abs(eta) < 2.5 + 1e-8:
                    reasons.append("lepton_eta")
                if energy < 0:
                    reasons.append("negative_energy")
            summed = [sum(values) for values in zip(*momenta)]
            m2 = summed[3] ** 2 - sum(p ** 2 for p in summed[:3])
            if m2 < -1e-5:
                reasons.append("spacelike_pair")
            mass = math.sqrt(max(0.0, m2))
            masses.append(mass)
            if not mass > 40.0 - 1e-8:
                reasons.append("dilepton_mass")
        if reasons:
            failed_events.append({"index": index, "reasons": sorted(set(reasons))})
    checks["event_count"] = len(blocks) == events
    checks["positive_constant_weights"] = bool(weights) and min(weights) > 0 and math.isclose(min(weights), max(weights), rel_tol=1e-10)
    checks["final_state_and_cuts"] = not failed_events and len(masses) == len(blocks)
    return {"scope": "LHE delivery and kinematic control only; no precision or detector validation",
            "passed": all(checks.values()), "checks": checks, "events": len(blocks),
            "cross_section_pb": xsec, "integration_error_pb": xerr,
            "dilepton_masses_gev": masses, "failed_events": failed_events,
            "lhe_pdf_ids": [int(x) for x in beam[6:8]], "weight_convention": int(beam[8])}


def audit_file(path):
    path = Path(path)
    payload = path.read_bytes()
    text = (gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload).decode("utf-8")
    return {**audit_text(text), "source_sha256": hashlib.sha256(payload).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lhe", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit_file(args.lhe)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ["passed", "events", "cross_section_pb", "integration_error_pb"]}))
    raise SystemExit(0 if result["passed"] else 1)
