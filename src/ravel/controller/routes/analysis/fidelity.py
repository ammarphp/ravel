"""Detector fidelity pinned at intake and compared with what the plan and the result actually use (C26).

The request's reading is pinned in the run store at intake. A demand for full detector simulation
is recorded there as a held boundary ("never silently downgraded"); a named detector stage or level
is a constraint or fact. This module derives the requested fidelity from those pinned records only
and ranks every detector mode the task contract admits. A plan or a delivered result whose fidelity
ranks below the request is refused: the unsupported scope stays held until a revised request
authorizes a different fidelity. Nothing here infers fidelity from prose a worker wrote.
"""
from __future__ import annotations

from .common import error

FULL_SIMULATION = "full-simulation"
LEVELS = ("parton", "particle", "smeared", "fast-response", FULL_SIMULATION)
# A requested detector stage needs some detector response; smearing or efficiency-map folding
# supplies it as well as a fast simulation. Only a full-simulation demand asks for more.
DETECTOR_RESPONSE = "smeared"
RANK = {name: index for index, name in enumerate(LEVELS)}
# Task-contract detector modes (validate_task_contract.DETECTOR_MODES) by the fidelity they supply.
DETECTOR_MODES = {
    "parton-level": "parton",
    "particle-level": "particle",
    "rivet-smearing": "smeared",
    "effmap-folded": "smeared",
    "simpleanalysis-delphes-native": "fast-response",
    "delphes-custom-uncertified": "fast-response",
    "container": "fast-response",
    "none": None,
    "TBD-judgment": None,
}
# The reading's boundary statement for a full-simulation demand (request_reading.boundaries).
FULL_SIMULATION_STATEMENT = "Full simulation of the detector is requested"


def level_of(detector_mode):
    """The fidelity a detector mode supplies; None when it supplies none or is undecided."""
    if not isinstance(detector_mode, str):
        return None
    if detector_mode in DETECTOR_MODES:
        return DETECTOR_MODES[detector_mode]
    return FULL_SIMULATION if detector_mode == FULL_SIMULATION else None


def requested(reading, contract) -> dict:
    """``{"level", "evidence"}``: the fidelity the pinned request demands (None when it names none)."""
    reading = reading if isinstance(reading, dict) else {}
    evidence, level = [], None
    for row in reading.get("boundaries") or ():
        if isinstance(row, dict) and str(row.get("statement") or "").startswith(FULL_SIMULATION_STATEMENT):
            level = FULL_SIMULATION
            evidence.append({"kind": "boundary", "id": row.get("id")})
    if level is None:
        for row in reading.get("constraints") or ():
            if isinstance(row, dict) and row.get("type") == "requested_stage" \
                    and (row.get("value") or {}).get("stage") in ("detector", "detector-simulation"):
                level, evidence = DETECTOR_RESPONSE, evidence + [{"kind": "constraint", "id": row.get("id")}]
                break
    if level is None:
        for row in reading.get("facts") or ():
            if isinstance(row, dict) and row.get("type") == "level":
                stated = str((row.get("value") or {}).get("level") or "").lower()
                if stated in ("parton", "particle"):
                    level, evidence = stated, evidence + [{"kind": "fact", "id": row.get("id")}]
                    break
    return {"level": level, "evidence": evidence}


def planned(plan) -> dict:
    """``{step id: level}`` from each step's detector mode; a requested label cannot upgrade it."""
    found = {}
    for step in (plan or {}).get("steps") or ():
        params = step.get("parameters") or {}
        task = params.get("task") if isinstance(params.get("task"), dict) else {}
        mode = task.get("detector_mode") or params.get("detector_mode")
        level = level_of(mode)
        if level is not None:
            found[step["id"]] = level
    return found


def below(actual, wanted) -> bool:
    """True when ``actual`` supplies less fidelity than ``wanted`` (an absent level never satisfies a demand)."""
    if wanted is None:
        return False
    if actual is None:
        return True
    return RANK.get(actual, -1) < RANK[wanted]


def plan_errors(reading, contract, plan, *, gate=None) -> list:
    """Refusals when the plan's detector steps supply less fidelity than the pinned request."""
    want = requested(reading, contract)
    if want["level"] is None:
        return []
    levels = planned(plan)
    errors = []
    if not levels and RANK[want["level"]] >= RANK[DETECTOR_RESPONSE]:
        errors.append(error("fidelity_unplanned", f"the request demands {want['level']} detector fidelity and no "
                            "plan step declares a detector mode", gate=gate, row="C26",
                            fix="plan a detector step with the requested fidelity or revise the request"))
    for step_id, level in sorted(levels.items()):
        if below(level, want["level"]):
            errors.append(error("fidelity_downgraded", f"step {step_id} supplies {level} detector fidelity; the "
                                f"request demands {want['level']}. The scope stays held until a revised request "
                                "authorizes another fidelity.", gate=gate, row="C26", step=step_id,
                                fix="supply the requested fidelity or obtain a revised request",
                                pins=[e.get("id") for e in want["evidence"] if e.get("id")]))
    return errors


def result_errors(reading, contract, delivered, *, gate=None) -> list:
    """Refusals when a delivered result's detector mode is below the pinned request."""
    want = requested(reading, contract)
    if want["level"] is None:
        return []
    errors = []
    if not delivered:
        errors.append(error("fidelity_result_missing", "no delivered detector result supports the requested "
                            f"{want['level']} fidelity", gate=gate, row="C26"))
    for name, mode in sorted((delivered or {}).items()):
        level = level_of(mode)
        if below(level, want["level"]):
            errors.append(error("fidelity_delivered_below_request", f"{name} was produced with {mode or 'no'} "
                                f"detector response ({level or 'none'}); the request demands {want['level']}",
                                gate=gate, row="C26", fix="deliver only results at the requested fidelity"))
    return errors
