"""Independent exhaustive toy oracle and explicitly declared allocator baselines.

This benchmark establishes finite algorithm behavior only. It neither measures
physics performance nor establishes the hypothetical categorical predictions.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
from itertools import product
import json
from pathlib import Path


CASE_PATH = Path(__file__).with_name("experiment-allocation-case.json")


def exhaustive_oracle(case, *, horizon=None, first_action=None):
    """Independently enumerate every feasible (including uninformative) policy.

    No production canonicalizer, branch builder, policy scorer, or recommender
    is used. Distinct full prediction tuples are the only countable objects.
    Objective is minimum elimination across leaves / largest path cost. Stop
    is permitted at every branch, with zero additional cost. Repeats cannot
    distinguish a branch and are excluded. Unknown matches every outcome.
    """
    horizon = case["horizon"] if horizon is None else horizon
    action_ids = sorted(a["id"] for a in case["actions"])
    columns = {key: i for i, key in enumerate(action_ids)}
    vectors = set(tuple(h["predictions"][key] for key in action_ids) for h in case["hypotheses"])
    count = len(vectors)
    actions = {a["id"]: a for a in case["actions"]}
    best = None
    examined = 0
    for root_id in action_ids:
        root = actions[root_id]
        if root["cost"] > case["budget"] or (first_action is not None and root_id != first_action):
            continue
        branches = []
        for outcome in sorted(root["outcomes"]):
            survivors = {v for v in vectors if v[columns[root_id]] is None or v[columns[root_id]] == outcome}
            if not survivors:
                continue
            choices = [(None, len(survivors), root["cost"])]
            if horizon == 2:
                for next_id in action_ids:
                    nxt = actions[next_id]
                    cost = root["cost"] + nxt["cost"]
                    if next_id == root_id or cost > case["budget"]:
                        continue
                    leaf_sizes = [sum(v[columns[next_id]] is None or v[columns[next_id]] == label
                                      for v in survivors) for label in nxt["outcomes"]]
                    choices.append((next_id, max(leaf_sizes), cost))
            branches.append((outcome, choices))
        for combination in product(*(options for _, options in branches)):
            examined += 1
            worst = max(size for _, size, _ in combination)
            cost = max(cost for _, _, cost in combination)
            score = Fraction(count - worst, cost)
            followup = {outcome: choice[0] for (outcome, _), choice in zip(branches, combination)}
            tie = (root_id, tuple((key, value or "") for key, value in sorted(followup.items())))
            candidate = {"first_action": root_id, "then": followup,
                         "worst_case_retained_classes": worst, "worst_case_cost": cost,
                         "guaranteed_eliminated_classes": count - worst,
                         "score_fraction": [score.numerator, score.denominator]}
            ordering = (-score, cost, tie)
            if best is None or ordering < best[0]:
                best = (ordering, candidate)
    return {"policy": best[1] if best is not None and best[1]["guaranteed_eliminated_classes"] else None,
            "policies_examined": examined}


def run(case=None):
    from ravel.workflow import experiment_allocator as allocator
    case = allocator.read_json(CASE_PATH) if case is None else case
    report = allocator.recommend(case)
    feasible = [a for a in case["actions"] if a["cost"] <= case["budget"]]
    cheapest = min(feasible, key=lambda a: (a["cost"], a["id"])) if feasible else None
    nominal = min(feasible, key=lambda a: (-a["nominal_change"], a["cost"], a["id"])) if feasible else None
    oracle = exhaustive_oracle(case)
    # Baselines choose exactly one action; they do not inspect prediction maps.
    baselines = {}
    for name, action in (("cheapest_first", cheapest), ("largest_nominal_change", nominal)):
        evaluation = exhaustive_oracle(case, horizon=1, first_action=action["id"]) if action else {"policy": None, "policies_examined": 0}
        policy = evaluation["policy"]
        baselines[name] = {"selected_action": action["id"] if action else None,
                           "evaluation": evaluation,
                           "guaranteed_eliminated_classes": policy["guaranteed_eliminated_classes"] if policy else 0,
                           "cost": action["cost"] if action else 0,
                           "score_fraction": policy["score_fraction"] if policy else [0, 1]}
    return {"schema_version": 1, "status": "ADVISORY", "advisory_only": True,
            "execution_authorized": False, "physics_validated": False,
            "prediction_basis": report["prediction_basis"], "input_digest": report["input_digest"],
            "objective": report["objective"], "cost_unit": "declared integer toy resource units",
            "baseline_definitions": {"cheapest_first": "minimum fixed action cost then action ID",
                                     "largest_nominal_change": "maximum supplied toy nominal_change then cost then ID; no physics meaning"},
            "baselines": baselines, "allocator": report, "independent_exhaustive_oracle": oracle,
            "exact_policy_match": report["policy"] == oracle["policy"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=CASE_PATH)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    from ravel.workflow import experiment_allocator as allocator
    result = run(allocator.read_json(args.case))
    rendered = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.out:
        with args.out.open("x") as stream:
            stream.write(rendered)
    print(rendered, end="")
    return 0 if result["exact_policy_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
