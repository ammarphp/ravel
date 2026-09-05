"""Executable native capability declarations, separate from validation claims.

Registration means an adapter can execute the declared inputs. It never grants
an acceptance certificate or permission to serve a scientific exclusion.
"""
from __future__ import annotations

CAPABILITIES = {
    "EwkCompressed2018": {
        "analysis_ids": ("EwkCompressed2018", "ATLAS-SUSY-2018-16", "ins1767649"),
        "models": ("slepton-bino",),
        "preparations": ("slepton-bino", "explicit-cards"),
        "detector": "simpleanalysis-delphes",
        "statistics": ("yields", "compressed-likelihood", "mapped-likelihood"),
        "routine": "EwkCompressed2018", "needs_restframes": True,
    },
    "EwkThreeLeptonERJR2018": {
        "analysis_ids": ("EwkThreeLeptonERJR2018", "ATLAS-SUSY-2018-06", "ins1771533"),
        "models": ("c1n2-wz",),
        "preparations": ("explicit-cards",),
        "detector": "simpleanalysis-delphes",
        "statistics": ("yields", "mapped-likelihood"),
        "routine": "EwkThreeLeptonERJR2018", "needs_restframes": False,
    },
    "ZeroLeptonDiscovery2018": {
        "analysis_ids": ("ZeroLeptonDiscovery2018", "ATLAS-SUSY-2018-22"),
        "models": ("squark-neutralino", "gluino-neutralino"),
        "preparations": ("explicit-cards",),
        "detector": "simpleanalysis-delphes",
        # The inclusive discovery SRs overlap. Combining them as independent
        # channels would manufacture statistical information.
        "statistics": ("yields",),
        "routine": "ZeroLeptonDiscovery2018", "needs_restframes": False,
    },
}

MODEL_PDGS = {
    "slepton-bino": ((1000011, 2000011, 1000013, 2000013, 1000015, 2000015), 1000022),
    "c1n2-wz": ((1000023, 1000024), 1000022),
    "squark-neutralino": ((1000001, 1000002, 1000003, 1000004, 2000001, 2000002, 2000003, 2000004), 1000022),
    "gluino-neutralino": ((1000021,), 1000022),
}


def resolve_capability(routine, model, preparation, detector, statistics, analysis_id=None):
    try:
        capability = CAPABILITIES[routine]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unregistered native analysis {routine!r}") from exc
    checks = ((model, capability["models"], "model"),
              (preparation, capability["preparations"], "preparation"),
              (detector, (capability["detector"],), "detector"),
              (statistics, capability["statistics"], "statistics"))
    for value, allowed, field in checks:
        if value not in allowed:
            raise ValueError(f"{routine}: unsupported {field} {value!r}; supported: {allowed}")
    if analysis_id is not None and analysis_id not in capability["analysis_ids"]:
        raise ValueError(f"requested analysis {analysis_id!r} disagrees with routine {routine}")
    return {**capability, "model": model, "preparation": preparation,
            "statistics_adapter": statistics, "physics_certified": False}
