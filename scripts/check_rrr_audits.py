#!/usr/bin/env python3
"""Check retained RRR audit integrity and arithmetic, without fitting or simulation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> list[str]:
    folder = root / "evidence/audits/2026-09-05-rrr-diagnosis"
    errors = []
    try:
        provenance = json.loads((folder / "provenance.json").read_text())
        required = {"retained-inputs.json", "diagnosis.json", "points.csv",
                    "signed-residuals.png", "paired-changes.png"}
        if set(provenance["outputs"]) != required:
            errors.append("RRR audit output inventory is incomplete or unexpected")
        for name, expected in provenance["outputs"].items():
            path = folder / name
            if path.parent != folder or not path.is_file() or path.is_symlink():
                errors.append(f"invalid or missing RRR audit output: {name}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                errors.append(f"RRR audit output changed: {name}")
        snapshot_hash = hashlib.sha256((folder / "retained-inputs.json").read_bytes()).hexdigest()
        if provenance["source_snapshot_sha256"] != snapshot_hash:
            errors.append("RRR source snapshot digest disagrees with retained bytes")
        script = folder / "diagnose.py"
        if hashlib.sha256(script.read_bytes()).hexdigest() != provenance["script_sha256"]:
            errors.append("RRR diagnostic code changed without a refreshed audit")
        if errors:
            return errors
        spec = importlib.util.spec_from_file_location("ravel_rrr_audit", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        snapshot = json.loads((folder / "retained-inputs.json").read_text())
        retained = json.loads((folder / "diagnosis.json").read_text())
        if module.analyse(snapshot) != retained:
            errors.append("RRR diagnosis differs from retained-input arithmetic")
        if len(snapshot["sources"]) != provenance["original_sources_count"]:
            errors.append("RRR original-source denominator changed")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"RRR audit unreadable: {type(exc).__name__}: {exc}")
    return errors


if __name__ == "__main__":
    failures = check()
    for failure in failures:
        print(f"[FAIL] {failure}")
    print("RRR archival audit: " + ("FAIL" if failures else "OK (integrity and arithmetic only)"))
    sys.exit(bool(failures))
