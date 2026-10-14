"""Explicit custody manifest for the evidence reviewed at CHECK-IN 2."""
from __future__ import annotations

import argparse
from pathlib import Path

from .execution import file_hash
from .state_io import atomic_json, read_json

MANIFEST = "inputs/waypoint_evidence.json"


def resolve(root, value):
    if not isinstance(value, str) or not value.strip() or "://" in value:
        raise ValueError("evidence path must be a nonblank local file path")
    return (Path(root) / value).resolve()


def pin(root, value):
    path = resolve(root, value)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"missing or empty waypoint evidence: {value}")
    root = Path(root).resolve()
    identity = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    return {"path": identity, "sha256": file_hash(path)}


def comparison_result(path):
    result = read_json(path)
    if (not isinstance(result, dict) or result.get("status") not in ("pass", "fail", "warning", "diagnostic")
            or not isinstance(result.get("summary"), str) or not result["summary"].strip()
            or not isinstance(result.get("diagnostics"), dict) or not result["diagnostics"]):
        raise ValueError("comparison needs status (pass/fail/warning/diagnostic), summary and nonempty diagnostics object")
    return result


def create(root, *, produced, reference, comparison, inputs):
    """Pin actual files; a failed comparison remains reviewable and can receive GO."""
    record = {"schema_version": 1, "produced": pin(root, produced), "reference": pin(root, reference),
              "comparison": pin(root, comparison), "inputs": [pin(root, p) for p in inputs]}
    record["result"] = comparison_result(resolve(root, record["comparison"]["path"]))
    errors = validate(root, record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def validate(root, record):
    try:
        if (not isinstance(record, dict) or set(record) != {
                "schema_version", "produced", "reference", "comparison", "inputs", "result"}
                or type(record.get("schema_version")) is not int or record["schema_version"] != 1):
            raise ValueError("waypoint manifest must have schema_version integer 1 and exactly the declared fields")
        if not isinstance(record["inputs"], list) or not record["inputs"]:
            raise ValueError("waypoint manifest needs nonempty input identities")
        entries = [record[role] for role in ("produced", "reference", "comparison")] + record["inputs"]
        identities = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                raise ValueError("waypoint evidence entries need path and sha256")
            actual = pin(root, entry["path"])
            if entry != actual:
                raise ValueError(f"changed or noncanonical waypoint evidence: {entry['path']}")
            identities.append(actual["path"])
        if len(set(identities)) != len(identities):
            raise ValueError("waypoint evidence identities must be distinct")
        if record["result"] != comparison_result(resolve(root, record["comparison"]["path"])):
            raise ValueError("manifest result differs from the hashed comparison")
        return []
    except (ValueError, OSError, TypeError) as exc:
        return [str(exc)]


def load_for_checkin(root):
    checkin = read_json(Path(root) / "inputs/checkin2.json")
    sections = checkin.get("sections") if isinstance(checkin, dict) else None
    value = sections.get("evidence_manifest") if isinstance(sections, dict) else None
    path = resolve(root, value)
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError("waypoint manifest must be inside the run directory")
    record = read_json(path)
    errors = validate(root, record)
    if errors:
        raise ValueError("; ".join(errors))
    return path, record


def bound_paths(root):
    path, record = load_for_checkin(root)
    entries = [record[role] for role in ("produced", "reference", "comparison")] + record["inputs"]
    return [str(path), *[str(resolve(root, entry["path"])) for entry in entries]]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rundir", required=True)
    for name in ("produced", "reference", "comparison"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--input", action="append", required=True, dest="inputs")
    args = parser.parse_args(argv)
    try:
        record = create(args.rundir, produced=args.produced, reference=args.reference,
                        comparison=args.comparison, inputs=args.inputs)
        atomic_json(Path(args.rundir) / MANIFEST, record)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"waypoint evidence: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
