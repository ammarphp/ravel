#!/usr/bin/env python3
"""Recheck the pilot's serialized counting models and reported roots.

Independent invocation of pyhf, not an independent statistical implementation.
Run with the replay dependencies (pyhf 0.7.6) from any directory.
"""
import hashlib
import json
import math
from pathlib import Path

import pyhf


def verify(root):
    pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=1e-9), precision="64b")
    reference = pyhf.simplemodels.uncorrelated_background([1.0], [283.0], [24.0])
    results = {}
    for name in ("ravel", "collideragent"):
        folder = root / name / "counting"
        payload = (folder / "likelihood.json").read_bytes()
        spec = json.loads(payload)
        workspace = pyhf.Workspace(spec)
        model = workspace.model()
        data = workspace.data(model)
        report = json.loads((folder / "reported-limits.json").read_text())
        checks = {
            "specified_channels": spec["channels"] == reference.spec["channels"],
            "specified_observations": data == [263.0, (283.0 / 24.0) ** 2],
            "poi_is_signal_events": model.config.poi_name == "mu",
        }
        roots = {}
        for label, index in (("observed", 0), ("median_expected", 1)):
            signal = report[label]["signal_events"]
            visible = report[label]["visible_cross_section_fb"]
            if not math.isfinite(signal) or signal <= 0:
                raise ValueError(f"{name}: nonphysical reported limit")
            samples = []
            for value in (signal - 0.01, signal, signal + 0.01):
                observed, expected = pyhf.infer.hypotest(value, data, model, test_stat="qtilde", return_expected_set=True)
                samples.append(float((observed, expected[2])[index]))
            low, high = model.config.suggested_bounds()[model.config.poi_index]
            checks[f"{label}_interior"] = low < signal - 0.01 < signal + 0.01 < high
            checks[f"{label}_crossing"] = samples[0] > 0.05 > samples[2]
            checks[f"{label}_root_residual"] = abs(samples[1] - 0.05) < 1e-5
            checks[f"{label}_units"] = math.isclose(visible, signal / 3.2, rel_tol=1e-10)
            roots[label] = {"signal_events": signal, "cls_minus_delta": samples[0], "cls_at_root": samples[1],
                            "cls_plus_delta": samples[2], "residual": samples[1] - 0.05}
        results[name] = {"passed": all(checks.values()), "checks": checks, "roots": roots,
                         "workspace_sha256": hashlib.sha256(payload).hexdigest()}
    return {"scope": "input transport, units and numerical roots in the declared single-bin approximation; no coverage or detector validation",
            "pyhf_version": pyhf.__version__, "delta_signal_events": 0.01, "results": results,
            "passed": all(row["passed"] for row in results.values())}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    result = verify(root)
    (root / "independent-counting-audit.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": sum(len(row["checks"]) for row in result["results"].values())}))
    raise SystemExit(0 if result["passed"] else 1)
