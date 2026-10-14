"""Source-bound diagnostic affordances composed with the finite allocator.

This is an advisory transfer from grounded action selection and constraint
explanations. An available disposition and matching files establish only the
declared prerequisites' local custody, never applicability, scientific validity,
dependency completeness, license authority, or approval to execute.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import experiment_allocator as allocator

MAX_BYTES = 8 * 1024 * 1024
MAX_PREREQUISITES = 64
MAX_TOTAL_PIN_BYTES = 32 * 1024 * 1024
SHA = re.compile(r"^[0-9a-f]{64}$")


def _keys(value, keys, label):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f"{label} requires exactly {sorted(keys)}")


def _text(value, label):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 4096:
        raise ValueError(f"{label} requires bounded nonempty trimmed text")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def assess(case, affordances, *, base_dir):
    """Assess finite disjunctive prerequisite routes without executing tools.

Every alternative is an all-of set of prerequisite IDs. Available prerequisites
require nonempty pinned evidence. Unknown, unavailable and stale prerequisites
block that route. All alternatives and blocker sets remain visible; no missing
premise is silently repaired. File paths must stay inside the supplied root.
    """
    allocator.validate_case(case)
    _keys(affordances, {"schema_version", "scope", "prerequisites", "actions"}, "affordances")
    if type(affordances["schema_version"]) is not int or affordances["schema_version"] != 1:
        raise ValueError("affordance schema_version must be integer 1")
    if affordances["scope"] != case["scope"]:
        raise ValueError("affordance scope must equal the allocation scope")
    rows = affordances["prerequisites"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_PREREQUISITES:
        raise ValueError("prerequisites require a bounded nonempty list")
    root = Path(base_dir).resolve(strict=True)
    observed = {}; total_pin_bytes = 0
    for row in rows:
        _keys(row, {"id", "state", "evidence", "note"}, "prerequisite")
        _text(row["id"], "prerequisite id"); _text(row["note"], "prerequisite note")
        if row["id"] in observed:
            raise ValueError("duplicate prerequisite id")
        if row["state"] not in ("available", "unavailable", "unknown"):
            raise ValueError("prerequisite state must be available, unavailable or unknown")
        pins = row["evidence"]
        if type(pins) is not list or len(pins) > 16 or (row["state"] == "available" and not pins):
            raise ValueError("available prerequisites require bounded nonempty pinned evidence")
        seen = set(); checks = []
        for pin in pins:
            _keys(pin, {"path", "sha256", "size"}, "evidence pin")
            _text(pin["path"], "pin path")
            relative = Path(pin["path"])
            if relative.is_absolute() or ".." in relative.parts or pin["path"] in seen:
                raise ValueError("evidence paths must be distinct relative paths without traversal")
            seen.add(pin["path"])
            if type(pin["sha256"]) is not str or not SHA.fullmatch(pin["sha256"]):
                raise ValueError("pin requires lowercase SHA256")
            if type(pin["size"]) is not int or not 0 <= pin["size"] <= MAX_BYTES:
                raise ValueError("pin size exceeds bounded file size")
            total_pin_bytes += pin["size"]
            if total_pin_bytes > MAX_TOTAL_PIN_BYTES:
                raise ValueError("aggregate evidence pins exceed byte bound")
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("evidence path escapes supplied root")
            matches = False; reason = "missing or nonregular file"
            if path.is_file():
                with path.open("rb") as stream:
                    raw = stream.read(MAX_BYTES + 1)
                matches = len(raw) == pin["size"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
                reason = None if matches else "pinned size or digest differs"
            checks.append({"path": pin["path"], "matches": matches, "reason": reason})
        state = "stale" if any(not check["matches"] for check in checks) else row["state"]
        observed[row["id"]] = {"id": row["id"], "declared_state": row["state"],
                               "observed_state": state, "evidence_checks": checks, "note": row["note"]}
    routes = affordances["actions"]
    ids = {action["id"] for action in case["actions"]}
    if type(routes) is not list or len(routes) != len(ids):
        raise ValueError("every allocation action requires one affordance record")
    dispositions = []; seen = set()
    for route in routes:
        _keys(route, {"id", "alternatives"}, "action affordance")
        if type(route["id"]) is not str or route["id"] not in ids or route["id"] in seen:
            raise ValueError("unknown or duplicate action affordance")
        seen.add(route["id"])
        alternatives = route["alternatives"]
        if type(alternatives) is not list or not 1 <= len(alternatives) <= 8:
            raise ValueError("action requires one to eight alternative prerequisite routes")
        blockers = []; distinct = set()
        for option in alternatives:
            if type(option) is not list or not 1 <= len(option) <= 16:
                raise ValueError("route requires one to sixteen prerequisite IDs")
            if any(type(key) is not str or key not in observed for key in option) or len(set(option)) != len(option):
                raise ValueError("route contains unknown or duplicate prerequisite IDs")
            canonical = tuple(sorted(option))
            if canonical in distinct:
                raise ValueError("duplicate prerequisite route")
            distinct.add(canonical)
            blockers.append([key for key in canonical if observed[key]["observed_state"] != "available"])
        dispositions.append({"id": route["id"], "available": any(not b for b in blockers),
                             "alternative_blocker_sets": blockers})
    return {"prerequisites": sorted(observed.values(), key=lambda row: row["id"]),
            "actions": sorted(dispositions, key=lambda row: row["id"])}


def recommend(case, affordances, *, base_dir):
    """Rank only declared available routes, preserving full prediction classes.

Use the existing allocator's finite policy enumeration and objective. Masking
before canonicalization would incorrectly merge rivals distinguishable only by
a blocked experiment; canonicalization therefore uses the original full case.
The result expires as soon as its bound inputs change and is never a launch gate.
    """
    original = allocator.recommend(case)
    assessment = assess(case, affordances, base_dir=base_dir)
    available = {row["id"] for row in assessment["actions"] if row["available"]}
    actions = sorted((a for a in case["actions"] if a["id"] in available), key=lambda row: row["id"])
    # Reuse the exact same engine, including horizon-two maximum path budgets.
    policies = list(allocator._policies(original["classes"], actions, case["budget"], case["horizon"]))
    best = min(policies, key=lambda p: (-p["score"], p["worst_case_cost"], allocator._policy_key(p))) if policies else None
    if best is not None and best["score"] == 0:
        best = None
    if best:
        best = dict(best); ratio = best.pop("score")
        best["score_fraction"] = [ratio.numerator, ratio.denominator]
    return {**deepcopy(original), "kind": "source_bound_diagnostic_advice", "policy": best,
            "policies_examined": len(policies), "unmasked_policy": original["policy"],
            "affordance_digest": _digest(affordances), "affordance_assessment": assessment,
            "stop_reason": None if best else "no available informative route within declared budget",
            "dependency_closure_complete": False,
            "limitations": ["Prerequisite states are declarations with checked local byte custody, not scientific entailment or availability probes.",
                            "Only enumerated prerequisites are checked; transitive dependency completeness is not established.",
                            "Reassess at use time; this recommendation grants no execution, review or license authority."]}
