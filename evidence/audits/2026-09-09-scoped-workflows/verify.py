#!/usr/bin/env python3
"""Fresh upstream fits and an independent event reader; no Ravel physics imports."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def verify():
    import pyhf
    pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=1e-9), precision="64b")
    records = {"likelihoods": {}, "events": {}, "comparisons": {}}
    for name, projection in read(ROOT / "card-projection.json").items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == projection["public_sha256"]
    for name in ("counting", "counting-replica", "two-bin"):
        d = ROOT / name
        result = read(d / "result.json")
        ws = pyhf.Workspace(read(d / "workspace.json"))
        spec = read(d / "spec.json")["likelihood"]
        model = ws.model(measurement_name=spec.get("measurement"))
        data = ws.data(model)
        roots = [result["obs_limit"], *result["exp_limits"]]
        assert result["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}
        residuals = []
        for i, root in enumerate(roots):
            observed, expected = pyhf.infer.hypotest(
                root, data, model, test_stat="qtilde", calctype="asymptotics", return_expected_set=True)
            value = float([observed, *expected][i])
            assert abs(value - .05) < 5e-4, (name, i, value)
            residuals.append(value - .05)
        assert roots[1:] == sorted(roots[1:])
        records["likelihoods"][name] = {"roots": roots, "cls_minus_0_05": residuals,
            "max_abs_residual": max(map(abs, residuals)), "optimizer": "upstream pyhf SciPy",
            "passed": True, "scope": "fresh numerical crossing evaluation, not toy coverage"}
    for name in ("drell-yan", "drell-yan-replica", "different-scale", "dimuon", "supplied-card"):
        d = ROOT / name
        result = read(d / "result.json")
        spec = read(d / "spec.json")["generation"]
        raw = gzip.decompress((d / "events.lhe.gz").read_bytes())
        projection = read(ROOT / "event-projection.json")[name]
        assert hashlib.sha256((d / "events.lhe.gz").read_bytes()).hexdigest() == projection["public_file_sha256"]
        tree = ET.fromstring(raw)
        events = tree.findall("event")
        assert tree.tag == "LesHouchesEvents" and len(events) == spec["events"] == 100
        lines = [s.split() for s in tree.find("init").text.splitlines() if s.strip()]
        assert [int(v) for v in lines[0][:2]] == [2212, 2212]
        assert [float(v) for v in lines[0][2:4]] == [6500, 6500]
        assert [int(v) for v in lines[0][6:8]] == [10042, 10042]
        cross_section = sum(float(line[0]) for line in lines[1:])
        assert math.isclose(cross_section, result["cross_section_pb"], rel_tol=1e-12)
        masses, weights = [], []
        for element in events:
            rows = [s.split() for s in element.text.splitlines() if s.strip() and not s.lstrip().startswith("#")]
            assert len(rows) == int(rows[0][0]) + 1
            weights.append(float(rows[0][2]))
            particles = [r for r in rows[1:] if int(r[1]) == 1]
            assert Counter(int(r[0]) for r in particles) == Counter(spec["observable"]["final_state_pdg"])
            p4 = [[float(v) for v in r[6:10]] for r in particles]
            for px, py, pz, energy in p4:
                pt = math.hypot(px, py)
                assert energy > 0 and pt >= 10 - 1e-7 and abs(math.asinh(pz / pt)) <= 2.5 + 1e-7
            total = [sum(v) for v in zip(*p4)]
            mass = math.sqrt(max(0, total[3] ** 2 - sum(p * p for p in total[:3])))
            assert mass >= 40 - 1e-7
            masses.append(mass)
        assert min(weights) > 0 and min(weights) == max(weights)
        assert all(abs(a - b) < 1e-6 for a, b in zip(masses, result["masses_gev"]))
        banner = tree.find("header/MGRunCard").text
        assert re.search(rf"(?m)^\s*{spec['seed']}\s*=\s*iseed\b", banner)
        records["events"][name] = {"events": len(events), "cross_section_pb": cross_section,
            "passed": True, "event_blocks_sha256": hashlib.sha256(
                b"".join(re.findall(rb"<event(?:\s[^>]*)?>.*?</event>", raw, re.S))).hexdigest()}
        assert records["events"][name]["event_blocks_sha256"] == projection["event_blocks_sha256"]
    for filename, expect in (("same-likelihood.json", True), ("different-likelihood.json", False),
                             ("same-physics-new-seed.json", True), ("scale-mismatch.json", False),
                             ("process-mismatch.json", False)):
        outcome = read(ROOT / filename)
        assert outcome["comparable"] is expect and not outcome["errors"]
        records["comparisons"][filename] = {"comparable": expect, "passed": True}
    assert read(ROOT / "scale-mismatch.json")["differences"] == [
        {"field": "recipe.run_settings.dynamical_scale_choice", "left": 4., "right": 3.}]
    bound = read(ROOT / "unresolved-bound/result.json")
    assert bound["limit_status"] == {"observed": "above_scan", "expected": ["above_scan"] * 5}
    assert bound["visible_cross_section_fb"]["observed"] is None
    assert bound["visible_cross_section_fb"]["expected"] == [None] * 5
    records["unresolved_bound"] = {"passed": True, "scope": "retained bound, failed delivery, no converted limit"}
    records["passed"] = True
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = verify()
    if args.out:
        args.out.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2))
