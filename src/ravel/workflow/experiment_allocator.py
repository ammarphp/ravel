"""Finite categorical experiment allocation, ADVISORY only.

Predictions and costs are declarations, not validated physics or execution authority.
Exact prediction clones count once. Unknown predictions remain compatible with
every declared outcome. The finite minimax objective has no probability model.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
from itertools import product
import json
import math
from pathlib import Path


MAX_ACTIONS = 8
MAX_OUTCOMES = 4
MAX_HYPOTHESES = 32
MAX_CLASSES = 12
COST_CLASSES = ('none', 'calculation', 'stream', 'generation')


def _selection_action(action):
    return action.get('exposure') != 'withheld_confirmation'


def _cost_rank(action):
    # An unmeasured legacy action has no class evidence, so it never wins a tie.
    if 'cost_class' not in action:
        return len(COST_CLASSES)
    return COST_CLASSES.index(action['cost_class'])


def measured_cost(action, *, base_dir):
    """Consume an exact stage-cost PIN, including its declared operation class.

    Stage-cost producers supply the class; elapsed time cannot identify whether
    an operation generates events. Legacy categorical declarations remain advice.
    """
    from .research_protocol import _method_json, _finite_number
    row = _method_json(action['cost_measurement'], base_dir)
    if row.get('cost_class') != action['cost_class']:
        raise ValueError('cost_class differs from pinned stage measurement')
    if row.get('kind') in {'supervised_pilot_observation', 'supervised_pilot_forecast'}:
        wall = row.get('wall_seconds')
    elif (row.get('generated_by') == 'cost_preflight.py' and row.get('schema_version') == 3
          and row.get('calibration_status') == 'measured'):
        hours = row.get('walltime_h')
        if type(hours) is not list or len(hours) != 2:
            raise ValueError('measured cost_preflight walltime_h bounds required')
        wall = [_finite_number(x, 'cost hours') * 3600 for x in hours]
    else:
        raise ValueError('measured pilot_cost or cost_preflight record required')
    if type(wall) is list:
        if len(wall) != 2:
            raise ValueError('measured cost bounds required')
        low, high = [_finite_number(x, 'cost seconds') for x in wall]
        if not 0 <= low <= high:
            raise ValueError('ordered nonnegative cost bounds required')
    else:
        high = _finite_number(wall, 'cost seconds')
        if high < 0:
            raise ValueError('nonnegative measured cost required')
    cost = max(1, math.ceil(high))
    if action['cost'] != cost:
        raise ValueError('action cost must equal rounded-up measured stage seconds')
    return cost


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _keys(value, required, label):
    if type(value) is not dict or set(value) != set(required):
        raise ValueError(f"{label} requires exactly {sorted(required)}")


def _text(value, label):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 4096:
        raise ValueError(f"{label} must be a trimmed nonempty string of at most 4096 characters")


def _integer(value, label, minimum=1):
    if type(value) is not int or not minimum <= value <= 1_000_000:
        raise ValueError(f"{label} must be an integer in [{minimum}, 1000000]")


def _strings(values, label, maximum):
    if type(values) is not list or not 1 <= len(values) <= maximum:
        raise ValueError(f"{label} must contain 1 to {maximum} strings")
    for value in values:
        _text(value, label)
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


def validate_case(case, *, base_dir=None):
    """Reject unbounded or ambiguous declarations before policy enumeration."""
    _keys(case, {"schema_version", "scope", "prediction_basis", "budget", "horizon",
                 "actions", "hypotheses"}, "allocation case")
    if type(case["schema_version"]) is not int or case["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    _text(case["scope"], "scope")
    if case["prediction_basis"] not in ("hypothetical", "supplied_unvalidated"):
        raise ValueError("prediction_basis must be hypothetical or supplied_unvalidated")
    _integer(case["budget"], "budget", 0)
    if type(case["horizon"]) is not int or case["horizon"] not in (1, 2):
        raise ValueError("horizon must be 1 or 2")
    actions = case["actions"]
    if type(actions) is not list or not 1 <= len(actions) <= MAX_ACTIONS:
        raise ValueError(f"actions must contain 1 to {MAX_ACTIONS} declarations")
    for action in actions:
        if type(action) is not dict:
            raise ValueError('action must be an object')
        optional = {'cost_class', 'cost_measurement', 'exposure'}
        _keys({k: v for k, v in action.items() if k not in optional},
              {"id", "cost", "outcomes", "nominal_change"}, "action")
        _text(action["id"], "action id")
        _integer(action["cost"], "action cost")
        _strings(action["outcomes"], "action outcomes", MAX_OUTCOMES)
        if action.get('exposure', 'adaptive_full') not in {'adaptive_screen', 'adaptive_full', 'withheld_confirmation'}:
            raise ValueError('declared action exposure required')
        if 'cost_class' in action or 'cost_measurement' in action:
            if action.get('cost_class') not in COST_CLASSES or not action.get('cost_measurement'):
                raise ValueError('cost_class requires a pinned stage cost measurement')
            measured_cost(action, base_dir=base_dir or Path.cwd())
        change = action["nominal_change"]
        try:
            finite = type(change) in (int, float) and math.isfinite(change)
        except OverflowError:
            finite = False
        if not finite or change < 0:
            raise ValueError("nominal_change must be finite and nonnegative (toy baseline only)")
    ids = [a["id"] for a in actions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate action id")
    by_id = {a["id"]: a for a in actions}
    hypotheses = case["hypotheses"]
    if type(hypotheses) is not list or not 1 <= len(hypotheses) <= MAX_HYPOTHESES:
        raise ValueError(f"hypotheses must contain 1 to {MAX_HYPOTHESES} declarations")
    for hypothesis in hypotheses:
        _keys(hypothesis, {"id", "predictions", "provenance", "reopening_trigger"}, "hypothesis")
        _text(hypothesis["id"], "hypothesis id")
        _strings(hypothesis["provenance"], "provenance", 16)
        _text(hypothesis["reopening_trigger"], "reopening_trigger")
        _keys(hypothesis["predictions"], ids, "predictions")
        for action_id, outcome in hypothesis["predictions"].items():
            if outcome is not None and (type(outcome) is not str or outcome not in by_id[action_id]["outcomes"]):
                raise ValueError(f"prediction must be a declared categorical outcome or null: {action_id}")
    hypothesis_ids = [h["id"] for h in hypotheses]
    if len(hypothesis_ids) != len(set(hypothesis_ids)):
        raise ValueError("duplicate hypothesis id")
    vectors = {tuple(h["predictions"][key] for key in sorted(ids)) for h in hypotheses}
    if len(vectors) > MAX_CLASSES:
        raise ValueError(f"at most {MAX_CLASSES} distinct prediction vectors are supported")


def canonicalize(case, *, base_dir=None):
    """Quotient exact full prediction vectors, retaining all member provenance."""
    validate_case(case, base_dir=base_dir)
    groups = {}
    action_ids = sorted(a["id"] for a in case["actions"])
    for hypothesis in case["hypotheses"]:
        vector = tuple(hypothesis["predictions"][key] for key in action_ids)
        groups.setdefault(vector, {"class_key": _digest(hypothesis["predictions"]), "predictions": deepcopy(hypothesis["predictions"]),
                                "members": []})["members"].append(deepcopy(hypothesis))
    for group in groups.values():
        group["members"].sort(key=lambda h: h["id"])
    return sorted(groups.values(), key=lambda group: json.dumps(group["predictions"], sort_keys=True))


def _compatible(classes, action_id, outcome):
    return [c for c in classes if c["predictions"][action_id] in (None, outcome)]


def _branches(classes, action):
    # Empty branches are impossible under this finite declaration and are omitted.
    return [(outcome, retained) for outcome in sorted(action["outcomes"])
            if (retained := _compatible(classes, action["id"], outcome))]


def _branch_options(classes, actions, budget, used):
    options = [(None, len(classes), 0)]
    for action in actions:
        if not _selection_action(action) or action["id"] in used or action["cost"] > budget:
            continue
        worst = max(len(retained) for _, retained in _branches(classes, action))
        if worst < len(classes):
            options.append((action["id"], worst, action["cost"]))
    return options


def _policy_key(policy):
    # Declared IDs and outcome labels provide a predeclared canonical tie-break.
    return (policy["first_action"], tuple((k, v or "") for k, v in sorted(policy["then"].items())))


def _policies(classes, actions, budget, horizon):
    initial = len(classes)
    for first in actions:
        if not _selection_action(first) or first["cost"] > budget:
            continue
        branches = _branches(classes, first)
        options = [[(None, len(retained), 0)] if horizon == 1 else
                   _branch_options(retained, actions, budget - first["cost"], {first["id"]})
                   for _, retained in branches]
        for choices in product(*options):
            worst = max(choice[1] for choice in choices)
            cost = first["cost"] + max(choice[2] for choice in choices)
            yield {"first_action": first["id"],
                   "then": {outcome: choice[0] for (outcome, _), choice in zip(branches, choices)},
                   "worst_case_retained_classes": worst, "worst_case_cost": cost,
                   "guaranteed_eliminated_classes": initial - worst,
                   "score": Fraction(initial - worst, cost)}


def recommend(case, *, horizon=None, base_dir=None):
    """Return exact finite minimax policy advice, with no authority to execute.

    Horizon one maximizes guaranteed eliminated distinct vectors / action cost.
    Horizon two maximizes guaranteed eliminated vectors / maximum path cost over
    feasible adaptive policies. Every path respects the single declared budget.
    Unknown classes overlap outcome branches, so their existence cannot give
    artificial elimination credit. Zero guaranteed gain causes abstention.
    Equal ratios choose lower worst cost, operation class, then the canonical
    policy ID tuple. Withheld actions are never selection policy branches.
    """
    classes = canonicalize(case, base_dir=base_dir)
    horizon = case["horizon"] if horizon is None else horizon
    if type(horizon) is not int or horizon not in (1, 2):
        raise ValueError("horizon must be 1 or 2")
    actions = sorted(case["actions"], key=lambda a: a["id"])
    policies = list(_policies(classes, actions, case["budget"], horizon))
    ranks = {a['id']: _cost_rank(a) for a in actions}
    best = min(policies, key=lambda p: (-p["score"], p["worst_case_cost"],
        ranks[p['first_action']], tuple(ranks.get(v, -1) for _, v in sorted(p['then'].items())),
        _policy_key(p))) if policies else None
    if best is not None and best["score"] == 0:
        best = None
    if best:
        best = dict(best)
        ratio = best.pop("score")
        best["score_fraction"] = [ratio.numerator, ratio.denominator]
    return {"schema_version": 1, "status": "ADVISORY", "advisory_only": True,
            "execution_authorized": False, "physics_validated": False,
            "scope": case["scope"], "prediction_basis": case["prediction_basis"],
            "input_digest": _digest(case), "budget": case["budget"], "horizon": horizon,
            "hypothesis_count": len(case["hypotheses"]), "unique_class_count": len(classes),
            "classes": classes, "policy": best,
            "stop_reason": None if best else "no informative feasible policy with guaranteed elimination",
            "objective": "guaranteed eliminated prediction classes / maximum path cost",
            "tie_break": "higher exact ratio, lower maximum path cost, operation cost class, lexicographic action/outcome ID tuple",
            "policies_examined": len(policies)}


def update(case, observations, *, prior_refutations=None, base_dir=None):
    """Pure scoped compatibility update; retain exact negative objects as compost.

    Digests are supplied evidence identifiers, not attestations of file integrity.
    Refutation means mismatch with a supplied prediction in this frozen scope.
    Unknown predictions never produce a refutation. No scientific truth is asserted.
    Previous negative objects are preserved verbatim, including reopening triggers.
    """
    classes = canonicalize(case, base_dir=base_dir)
    if type(observations) is not list or len(observations) > 16:
        raise ValueError("observations must be a list of at most 16 records")
    if prior_refutations is not None and (type(prior_refutations) is not list or len(prior_refutations) > 512):
        raise ValueError("prior_refutations must be a list of at most 512 objects")
    refutations = deepcopy(prior_refutations or [])
    if any(type(record) is not dict for record in refutations):
        raise ValueError("prior refutations must be objects")
    actions = {a["id"]: a for a in case["actions"]}
    for observation in observations:
        _keys(observation, {"action_id", "outcome", "evidence_digest"}, "observation")
        action_id, outcome = observation["action_id"], observation["outcome"]
        if type(action_id) is not str or action_id not in actions:
            raise ValueError("observation action must be declared")
        if type(outcome) is not str or outcome not in actions[action_id]["outcomes"]:
            raise ValueError("observation outcome is outside frozen categorical scope")
        sha = observation["evidence_digest"]
        if type(sha) is not str or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("evidence_digest must be a lowercase sha256 identifier")
        retained = _compatible(classes, action_id, outcome)
        for group in classes:
            if group["predictions"][action_id] in (None, outcome):
                continue
            for member in group["members"]:
                refutations.append({"kind": "scoped_prediction_mismatch", "hypothesis": deepcopy(member),
                                    "class_key": group["class_key"], "scope": case["scope"],
                                    "action_id": action_id, "predicted_outcome": group["predictions"][action_id],
                                    "observed_outcome": outcome, "evidence_digest": sha,
                                    "reopening_trigger": member["reopening_trigger"]})
        classes = retained
    unique = {json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False): record for record in refutations}
    return {"status": "ADVISORY", "advisory_only": True, "execution_authorized": False,
            "physics_validated": False, "scope": case["scope"], "classes": classes,
            "refutation_semantics": "categorical mismatch in frozen declared scope, not refutation of a whole theory",
            "prior_refutations_are_new_evidence": False,
            "retained_hypothesis_ids": sorted(m["id"] for c in classes for m in c["members"]),
            "refutations": list(unique.values()), "observations": deepcopy(observations),
            "all_declared_predictions_incompatible": not classes}


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    if Path(path).stat().st_size > 1_000_000:
        raise ValueError("allocation case exceeds 1 MB")
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        rendered = json.dumps(recommend(read_json(args.case), base_dir=args.case.parent), indent=2, allow_nan=False) + "\n"
        if args.out:
            with args.out.open("x") as stream:
                stream.write(rendered)
        print(rendered, end="")
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        parser.exit(1, f"experiment allocator: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def allocate(case, policy, *, base_dir=None):
    """Bounded coverage reserve after protecting validation and confirmation.

    Prediction-vector classes are the family unit. Aliases share a seat and a
    coverage count. Fewer affordable tests than classes is a normal finite plan.
    All values remain advice over declarations, never calibrated probabilities.
    """
    classes = canonicalize(case, base_dir=base_dir)
    _keys(policy, {'validation_reservation', 'confirmation_reservation', 'reserve_budget',
                   'coverage', 'starvation_rounds', 'rounds_since_exploration'}, 'allocation policy')
    for key in ('validation_reservation', 'confirmation_reservation', 'reserve_budget',
                'rounds_since_exploration'):
        _integer(policy[key], key, 0)
    _integer(policy['starvation_rounds'], 'starvation_rounds')
    withheld = [a for a in case['actions'] if not _selection_action(a)]
    reserved = {'validation': policy['validation_reservation'],
                'confirmation': max(policy['confirmation_reservation'], sum(a['cost'] for a in withheld))}
    available = case['budget'] - sum(reserved.values())
    if available < 0:
        raise ValueError('validation/confirmation reservations exceed budget')
    coverage = policy['coverage']
    if not isinstance(coverage, dict) or set(coverage) - {c['class_key'] for c in classes}:
        raise ValueError('coverage must use canonical prediction classes, not aliases')
    for count in coverage.values(): _integer(count, 'coverage count', 0)
    reserve = min(policy['reserve_budget'], available)
    seats, cost = [], 0
    # Reserve used on each round; the starvation flag requires a seat whenever
    # at least one is feasible, but never steals a protected reservation.
    for group in sorted(classes, key=lambda c: (coverage.get(c['class_key'], 0), c['class_key'])):
        actions = [a for a in case['actions'] if _selection_action(a) and group['predictions'][a['id']] is not None
                   and a['cost'] <= reserve - cost]
        if not actions:
            continue
        action = min(actions, key=lambda a: (a['cost'], _cost_rank(a), a['id']))
        seats.append({'class_key': group['class_key'], 'hypothesis_id': group['members'][0]['id'],
                      'action_id': action['id'], 'cost': action['cost']})
        cost += action['cost']
    starved = policy['rounds_since_exploration'] >= policy['starvation_rounds']
    affordable = any(_selection_action(a) and a['cost'] <= available for a in case['actions'])
    if starved and affordable and not seats:
        raise ValueError('starvation trigger requires an affordable exploration reserve seat')
    remainder = deepcopy(case); remainder['budget'] = available - cost
    recommended = recommend(remainder, base_dir=base_dir)
    ranked = []
    for action in case['actions']:
        if not _selection_action(action) or action['cost'] > available-cost:
            continue
        gain = len(classes) - max(len(retained) for _, retained in _branches(classes, action))
        if gain:
            ranked.append((Fraction(gain, action['cost']), action))
    ranked.sort(key=lambda row: (-row[0], row[1]['cost'], _cost_rank(row[1]), row[1]['id']))
    return {'schema_version': 1, 'allocator_recommendation': recommend(case, base_dir=base_dir)['input_digest'],
            'reserved': reserved, 'reserve_seats': seats, 'exploration_cost': cost,
            'reserved_actions': sorted(a['id'] for a in withheld),
            'selection_order': [a['id'] for _, a in ranked],
            'remaining_selection_budget': available-cost, 'policy': recommended['policy'],
            'starvation_triggered': starved, 'advisory_only': True, 'physics_validated': False,
            'execution_authorized': False}


def check_allocation(case, policy, work_item, *, base_dir=None):
    """Require exact current allocator input and computed reservation advice."""
    validate_case(case, base_dir=base_dir)
    required = len(case['hypotheses']) >= 2 and sum(_selection_action(a) and a['cost'] <= case['budget'] for a in case['actions']) >= 2
    digest = recommend(case, base_dir=base_dir)['input_digest']
    if required and work_item.get('allocator_recommendation') != digest:
        raise ValueError('allocator_recommendation must equal current recommend(case).input_digest')
    expected = allocate(case, policy, base_dir=base_dir)
    if work_item.get('allocation') != expected:
        raise ValueError('allocation differs: reservations, reserve, starvation or alias seats')
    return expected


def validate_evaluation_arm(config, *, evaluation_harness=False):
    """Admission only; EC2 execution belongs to the evaluator, not production."""
    if not evaluation_harness:
        raise ValueError('alternative allocator arms are evaluation-only')
    if config.get('policy') == 'ec2':
        prior = config.get('prior')
        if (not isinstance(prior, dict) or not prior or
                any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in prior.values())
                or not math.isclose(sum(prior.values()), 1., abs_tol=1e-12)):
            raise ValueError('EC2 arm requires a declared normalized prior')
    return {'status': 'advisory', 'physics_validated': False, 'execution_authorized': False}
