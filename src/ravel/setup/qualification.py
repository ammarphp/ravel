"""Installation observations and explicitly supplied, scoped receipt comparisons.

Matching receipt bytes and scope grants no launch or scientific acceptance authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


class MissingQualificationInput(ValueError):
    """There is no built-in qualification receipt or operation scope."""
    reason = "missing_qualification_input"


def installation_label(group, status, label):
    """Project setup observations without promoting installation to qualification."""
    declared = group.get("qualification") or {}
    recorded = declared.get("status", "built-unqualified")
    qualification = "built-unqualified" if recorded in ("qualified", "tester-qualification") else recorded
    return {"label": label, "installation": {"status": status, "label": label},
            "qualification": qualification,
            "qualification_basis": ("Installation detection only; supply an operation, version and condition-bound receipt."
                                    if qualification == "built-unqualified" else declared.get("basis", "No receipt supplied")),
            "qualification_scope": [], "scientific_acceptance": False}


def census_status(readiness):
    """An installation probe alone cannot qualify a numerical operation."""
    if readiness == "excluded":
        return "excluded"
    if readiness in ("missing", "manual_required", "unsupported", "remote_route"):
        return "not_installed"
    return "built_but_unqualified"


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scope(scope):
    required = {"tool", "versions", "platform", "operation", "conditions"}
    if not isinstance(scope, dict) or set(scope) != required:
        raise MissingQualificationInput("explicit tool, versions, platform, operation and conditions required")
    for key in ("tool", "platform", "operation"):
        if not isinstance(scope[key], str) or not scope[key].strip():
            raise MissingQualificationInput("explicit " + key + " required")
    if (not isinstance(scope["versions"], dict) or not scope["versions"]
            or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v
                   for k, v in scope["versions"].items())):
        raise MissingQualificationInput("complete named versions required")
    if not isinstance(scope["conditions"], dict) or not scope["conditions"]:
        raise MissingQualificationInput("explicit tested conditions required")
    _canonical(scope)


def compare_receipt(receipt=None, request=None):
    """Compare a selected receipt with an exact requested scope, without executing.

    Each check binds a caller-selected evidence file. Failed and unexecuted checks
    remain failed or unexecuted. A scope match is not a current runtime test.
    """
    if not isinstance(request, dict) or set(request) != {"scope", "output_format"}:
        raise MissingQualificationInput("scope and output_format required")
    _scope(request["scope"])
    if request["output_format"] not in ("json", "jsonl"):
        raise ValueError("qualification output_format must be json or jsonl")
    if (not isinstance(receipt, dict) or set(receipt) != {"schema_version", "scope", "checks"}
            or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1):
        raise MissingQualificationInput("selected qualification receipt schema1 required")
    _scope(receipt["scope"])
    if _canonical(receipt["scope"]) != _canonical(request["scope"]):
        raise ValueError("qualification receipt scope differs from requested conditions or versions")
    checks = receipt["checks"]
    if not isinstance(checks, list) or not checks:
        raise MissingQualificationInput("executed check population required")
    names = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"name", "status", "evidence"}:
            raise MissingQualificationInput("complete check and evidence binding required")
        if not isinstance(check["name"], str) or not check["name"] or check["name"] in names:
            raise ValueError("distinct named checks required")
        names.add(check["name"])
        if check["status"] not in ("passed", "failed", "not_run"):
            raise ValueError("explicit passed, failed or not_run check status required")
        evidence = check["evidence"]
        if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
                or not isinstance(evidence["path"], str) or not evidence["path"]
                or not re.fullmatch(r"[0-9a-f]{64}", str(evidence["sha256"]))):
            raise MissingQualificationInput("selected evidence path and sha256 required")
        path = Path(evidence["path"])
        if not path.is_file():
            raise MissingQualificationInput("selected qualification evidence file missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]:
            raise ValueError("qualification evidence digest differs")
    statuses = {check["status"] for check in checks}
    result = {"schema_version": 1, "status": "failed" if "failed" in statuses else
              "not_run" if "not_run" in statuses else "matched",
              "scope": receipt["scope"], "checks": checks,
              "output_format": request["output_format"], "scientific_acceptance": False}
    result["rendered"] = json.dumps(result, indent=2 if request["output_format"] == "json" else None,
                                    allow_nan=False) + "\n"
    return result
