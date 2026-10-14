#!/usr/bin/env python3
"""Read-only frozen diagnostic twins. No simulation, fits, or LLM calls."""
import argparse
import json
from pathlib import Path

from ravel.workflow.diagnostic_plan import evaluate, read_json


def run(base=None):
    base = Path(base) if base is not None else Path(__file__).parent
    registry = read_json(base / "cases.json")
    records = []
    for case in registry["cases"]:
        result = evaluate(read_json(base / case["plan"]), base)
        records.append({"id": case["id"], "expected_status": case["expected_status"],
                        "actual_status": result["status"],
                        "expected_review_disposition": case["expected_review_disposition"],
                        "passed": result["status"] == case["expected_status"], "result": result})
    return {"schema_version": 1, "passed": all(r["passed"] for r in records), "cases": records,
            "scope": registry["scope"], "llm_calls": 0, "new_events": 0,
            "physics_validated": False, "review_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run()
    rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x") as stream:
            stream.write(rendered)
    print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
