#!/usr/bin/env python3
"""Freeze a crossed experiment roster and score independently adjudicated outcomes.

Standard library only. No agent execution, physics oracle, statistical inference,
or claim that a digest establishes prospective registration. See README.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
from pathlib import Path
from statistics import median


ARMS = {
    "baseline": {"instructions": False, "enforcement": False},
    "instructions": {"instructions": True, "enforcement": False},
    "enforcement": {"instructions": False, "enforcement": True},
    "full": {"instructions": True, "enforcement": True},
}
STATUSES = {"completed", "refused", "timeout", "crash", "not_started"}
NUMERIC = ("fidelity_error", "cost_usd", "wall_seconds", "interventions")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected, label):
    require(isinstance(value, dict), f"{label}: expected object")
    require(set(value) == set(expected), f"{label}: fields must be {sorted(expected)}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def load_json(path):
    def object_from_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")

    return json.loads(path.read_text(), object_pairs_hook=object_from_pairs,
                      parse_constant=invalid_constant)


def is_hash(value, length=64):
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def number(value, name, integer=False):
    require(type(value) in ((int,) if integer else (int, float))
            and math.isfinite(value) and value >= 0, f"{name}: expected finite nonnegative number")


def validate_spec(spec):
    keys(spec, {"experiment_id", "protocol_sha256", "code_commit", "environment_sha256",
                "model", "runtime", "schedule_seed", "seeds", "tasks", "budget"}, "spec")
    for name in ("experiment_id", "model", "runtime"):
        require(nonempty(spec[name]), f"{name}: required")
    for name in ("protocol_sha256", "environment_sha256"):
        require(is_hash(spec[name]), f"{name}: expected SHA-256")
    require(is_hash(spec["code_commit"], 40), "code_commit: expected full Git SHA-1")
    number(spec["schedule_seed"], "schedule_seed", integer=True)
    seeds = spec["seeds"]
    require(isinstance(seeds, list) and seeds, "seeds: nonempty list required")
    for seed in seeds:
        number(seed, "seed", integer=True)
    require(len(set(seeds)) == len(seeds), "seeds: duplicates")
    keys(spec["budget"], {"usd_per_run", "seconds_per_run"}, "budget")
    for name, value in spec["budget"].items():
        number(value, name)
        require(value > 0, f"{name}: must be positive")
    require(isinstance(spec["tasks"], list) and spec["tasks"], "tasks: nonempty list required")
    ids = set()
    for task in spec["tasks"]:
        keys(task, {"id", "expected", "prompt_sha256", "oracle_sha256", "fidelity_tolerance"}, "task")
        require(nonempty(task["id"]) and task["id"] not in ids, "task id: empty or duplicate")
        ids.add(task["id"])
        require(task["expected"] in {"complete", "refuse"}, "task expected: complete or refuse")
        for name in ("prompt_sha256", "oracle_sha256"):
            require(is_hash(task[name]), f"task {name}: expected SHA-256")
        if task["fidelity_tolerance"] is not None:
            number(task["fidelity_tolerance"], "fidelity_tolerance")
        require(task["expected"] != "refuse" or task["fidelity_tolerance"] is None,
                "refusal task: fidelity_tolerance must be null")
    require({t["expected"] for t in spec["tasks"]} == {"complete", "refuse"},
            "include both completion and refusal controls")


def freeze(spec):
    """Return a deterministic full factorial roster. Never remove failed assignments."""
    validate_spec(spec)
    campaign_digest = digest(spec)
    runs = []
    for task in spec["tasks"]:
        for seed in spec["seeds"]:
            for arm in ARMS:
                run = {"task_id": task["id"], "seed": seed, "arm": arm}
                runs.append({"run_id": digest({"spec_sha256": campaign_digest, **run}), **run})
    random.Random(spec["schedule_seed"]).shuffle(runs)
    body = {"schema_version": 1, "spec": spec, "arms": ARMS, "runs": runs}
    return {**body, "registry_sha256": digest(body)}


def validate_registry(registry):
    keys(registry, {"schema_version", "spec", "arms", "runs", "registry_sha256"}, "registry")
    require(type(registry["schema_version"]) is int and registry["schema_version"] == 1,
            "registry schema_version: expected 1")
    expected = freeze(registry["spec"])
    require(registry == expected, "registry altered, incomplete, or not in canonical schedule order")


def validate_outcome(row):
    keys(row, {"run_id", "status", "unsupported_claim", "refusal_valid", "fidelity_error",
               "cost_usd", "wall_seconds", "interventions", "executor_id", "scorer_id",
               "evidence_sha256", "notes"}, "outcome")
    require(is_hash(row["run_id"]), "outcome run_id: invalid")
    require(row["status"] in STATUSES, "outcome status: invalid")
    require(nonempty(row["notes"]), "outcome notes: required, including missingness explanation")
    for name in ("unsupported_claim", "refusal_valid"):
        require(row[name] is None or type(row[name]) is bool, f"{name}: boolean or null")
    for name in NUMERIC:
        if row[name] is not None:
            number(row[name], name, integer=name == "interventions")
    if row["status"] == "not_started":
        require(all(row[n] is None for n in ("unsupported_claim", "refusal_valid", "fidelity_error",
                    "executor_id", "scorer_id", "evidence_sha256")), "not_started: no empirical findings")
        require(all(row[n] == 0 for n in ("cost_usd", "wall_seconds", "interventions")),
                "not_started: resource usage must be explicitly zero")
        return
    require(nonempty(row["executor_id"]), "started run requires executor_id")
    require(is_hash(row["evidence_sha256"]), "started run requires evidence manifest SHA-256")
    require(row["scorer_id"] is None or nonempty(row["scorer_id"]), "scorer_id: string or null")
    judged = any(row[n] is not None for n in ("unsupported_claim", "refusal_valid", "fidelity_error"))
    if judged:
        require(nonempty(row["scorer_id"]) and row["scorer_id"] != row["executor_id"],
                "independent scorer identity required")
    require(row["status"] == "refused" or row["refusal_valid"] is None,
            "refusal_valid only applies to refused outcomes")
    require(row["status"] == "completed" or row["fidelity_error"] is None,
            "fidelity_error only applies to completed outcomes")
    require(not (row["refusal_valid"] is True and row["unsupported_claim"] is True),
            "valid refusal cannot contain an unsupported claim")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def score(registry, outcomes):
    """Descriptive scores only, with fixed denominators and sharp missingness bounds."""
    validate_registry(registry)
    keys(outcomes, {"schema_version", "registry_sha256", "outcomes"}, "outcomes document")
    require(type(outcomes["schema_version"]) is int and outcomes["schema_version"] == 1,
            "outcomes schema_version: expected 1")
    require(outcomes["registry_sha256"] == registry["registry_sha256"], "outcomes registry mismatch")
    require(isinstance(outcomes["outcomes"], list), "outcomes: expected list")
    by_id = {}
    for row in outcomes["outcomes"]:
        validate_outcome(row)
        require(row["run_id"] not in by_id, "duplicate outcome run_id")
        by_id[row["run_id"]] = row
    planned = {r["run_id"] for r in registry["runs"]}
    require(set(by_id) == planned,
            f"complete accounting required: missing={len(planned - set(by_id))}, "
            f"unplanned={len(set(by_id) - planned)}")
    tasks = {t["id"]: t for t in registry["spec"]["tasks"]}
    summary = {}
    for arm in ARMS:
        assignments = [r for r in registry["runs"] if r["arm"] == arm]
        rows = [by_id[r["run_id"]] for r in assignments]
        n = len(rows)
        invalid = sum(r["unsupported_claim"] is True for r in rows)
        unknown = sum(r["unsupported_claim"] is None for r in rows)
        supported = [(by_id[r["run_id"]], tasks[r["task_id"]]) for r in assignments
                     if tasks[r["task_id"]]["expected"] == "complete"]
        refusal = [by_id[r["run_id"]] for r in assignments
                   if tasks[r["task_id"]]["expected"] == "refuse"]
        success = sum(r["status"] == "completed" and r["unsupported_claim"] is False
                      and (t["fidelity_tolerance"] is None or
                           (r["fidelity_error"] is not None and r["fidelity_error"] <= t["fidelity_tolerance"]))
                      for r, t in supported)
        valid_refusals = sum(r["status"] == "refused" and r["refusal_valid"] is True
                            and r["unsupported_claim"] is False for r in refusal)
        summary[arm] = {
            "planned": n, "status_counts": {s: sum(r["status"] == s for r in rows) for s in sorted(STATUSES)},
            "unsupported_claims": invalid, "unadjudicated": unknown,
            "unsupported_claim_rate": ratio(invalid, n) if unknown == 0 else None,
            "unsupported_claim_rate_bounds": [invalid / n, (invalid + unknown) / n],
            "completion_controls": len(supported), "verified_completions": success,
            "verified_completion_rate": ratio(success, len(supported)),
            "refusals_on_completion_controls": sum(r["status"] == "refused" for r, _ in supported),
            "refusal_controls": len(refusal), "verified_valid_refusals": valid_refusals,
            "verified_valid_refusal_rate": ratio(valid_refusals, len(refusal)),
            "fidelity_scored": sum(r["fidelity_error"] is not None for r, _ in supported),
        }
        # Different tasks may use different error metrics/units. Never pool their errors.
        summary[arm]["fidelity_by_task"] = {}
        for task_id, task in tasks.items():
            if task["expected"] != "complete":
                continue
            task_rows = [r for r, t in supported if t["id"] == task_id]
            values = [r["fidelity_error"] for r in task_rows if r["fidelity_error"] is not None]
            summary[arm]["fidelity_by_task"][task_id] = {
                "planned": len(task_rows), "scored": len(values),
                "median_known": median(values) if values else None,
                "tolerance": task["fidelity_tolerance"],
            }
        for name in ("cost_usd", "wall_seconds", "interventions"):
            known = [r[name] for r in rows if r[name] is not None]
            summary[arm][name] = {"known_sum": sum(known), "known_runs": len(known),
                                  "missing_runs": n - len(known), "mean_known": ratio(sum(known), len(known))}
    return {"schema_version": 1, "registry_sha256": registry["registry_sha256"],
            "interpretation": "descriptive_only_no_causal_or_population_inference", "arms": summary}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("freeze")
    p.add_argument("spec", type=Path)
    p = commands.add_parser("score")
    p.add_argument("registry", type=Path)
    p.add_argument("outcomes", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze(load_json(args.spec))
        else:
            result = score(load_json(args.registry), load_json(args.outcomes))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"experiment error: {exc}\n")


if __name__ == "__main__":
    main()
