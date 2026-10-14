"""Finite allocator guarantees and an independent exhaustive policy oracle."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

from ravel.workflow import experiment_allocator as allocator


BASE = Path(__file__).resolve().parents[2] / "tests/fixtures/physics-review/prototypes"


def fixture():
    return allocator.read_json(BASE / "experiment-allocation-case.json")


def benchmark():
    spec = importlib.util.spec_from_file_location("allocation_controls", BASE / "run_experiment_allocator.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observe(action="b-balanced", outcome="left"):
    return {"action_id": action, "outcome": outcome, "evidence_digest": "a" * 64}


def test_frozen_benchmark_cost_objective_and_advisory_boundary():
    case = fixture()
    original = deepcopy(case)
    report = benchmark().run(case)
    assert report["exact_policy_match"] is True
    assert report["allocator"]["unique_class_count"] == 7
    assert report["allocator"]["hypothesis_count"] == 8
    assert report["allocator"]["policy"] == {
        "first_action": "b-balanced", "then": {"left": None, "right": None},
        "guaranteed_eliminated_classes": 3, "worst_case_retained_classes": 4,
        "worst_case_cost": 2, "score_fraction": [3, 2]}
    assert report["independent_exhaustive_oracle"]["policies_examined"] > report["allocator"]["policies_examined"]
    assert report["baselines"]["cheapest_first"]["selected_action"] == "a-cheap"
    assert report["baselines"]["cheapest_first"]["score_fraction"] == [1, 1]
    assert report["baselines"]["largest_nominal_change"]["selected_action"] == "z-repeat"
    assert report["baselines"]["largest_nominal_change"]["score_fraction"] == [0, 1]
    for value in (report, report["allocator"], allocator.update(case, [])):
        assert value["status"] == "ADVISORY"
        assert value["advisory_only"] is True
        assert value["physics_validated"] is value["execution_authorized"] is False
    assert case == original


def test_reorder_relabel_and_exact_clone_preserve_choice_without_clone_credit():
    case = fixture()
    expected = allocator.recommend(case)["policy"]
    case["actions"].reverse()
    case["hypotheses"].reverse()
    for i, hypothesis in enumerate(case["hypotheses"]):
        hypothesis["id"] = f"renamed-{i}"
        hypothesis["predictions"] = dict(reversed(list(hypothesis["predictions"].items())))
        hypothesis["provenance"] = ["different provenance retains same prediction vector"]
    for action in case["actions"]:
        action["outcomes"].reverse()
    assert allocator.recommend(case)["policy"] == expected
    clone = deepcopy(case["hypotheses"][0])
    clone["id"] = "many-clone"
    case["hypotheses"].append(clone)
    report = allocator.recommend(case)
    assert report["policy"] == expected
    assert report["unique_class_count"] == 7
    assert sum(len(c["members"]) for c in report["classes"]) == 9


def test_tie_break_is_declared_and_action_relabel_only_changes_tied_choice():
    case = fixture()
    case["horizon"] = 1
    assert allocator.recommend(case)["policy"]["first_action"] == "b-balanced"
    for action in case["actions"]:
        if action["id"] == "c-orthogonal":
            action["id"] = "a-orthogonal"
    for hypothesis in case["hypotheses"]:
        hypothesis["predictions"]["a-orthogonal"] = hypothesis["predictions"].pop("c-orthogonal")
    result = allocator.recommend(case)
    assert result["policy"]["first_action"] == "a-orthogonal"
    assert result["policy"]["score_fraction"] == [3, 2]


def test_budget_and_no_information_cause_abstention():
    case = fixture()
    case["budget"] = 0
    assert allocator.recommend(case)["policy"] is None
    assert allocator.recommend(case)["stop_reason"]
    case["budget"] = 1
    assert allocator.recommend(case)["policy"]["first_action"] == "a-cheap"
    for h in case["hypotheses"]:
        h["predictions"] = {a["id"]: None for a in case["actions"]}
    assert allocator.recommend(case)["policy"] is None
    case = fixture()
    for h in case["hypotheses"]:
        h["predictions"] = {a["id"]: a["outcomes"][0] for a in case["actions"]}
    assert allocator.recommend(case)["policy"] is None


def test_unknown_survives_all_declared_observations_and_never_refutes():
    case = fixture()
    for action in case["actions"]:
        for outcome in action["outcomes"]:
            result = allocator.update(case, [observe(action["id"], outcome)])
            assert "h7" in result["retained_hypothesis_ids"]
            assert all(r["hypothesis"]["id"] != "h7" for r in result["refutations"])
            assert all(r["predicted_outcome"] is not None for r in result["refutations"])
    result = allocator.update(case, [observe("z-repeat", "changed")])
    assert result["retained_hypothesis_ids"] == ["h7"]
    assert result["all_declared_predictions_incompatible"] is False
    with pytest.raises(ValueError, match="outside frozen"):
        allocator.update(case, [observe(outcome="unexpected")])


def test_exact_negative_objects_retained_with_scope_digest_and_reopening_trigger():
    case = fixture()
    first = allocator.update(case, [observe()])
    previous = deepcopy(first["refutations"])
    result = allocator.update(case, [observe(), observe("c-orthogonal", "odd")], prior_refutations=previous)
    assert previous == first["refutations"]
    assert result["refutations"][:len(previous)] == previous
    assert result["prior_refutations_are_new_evidence"] is False
    for record in result["refutations"]:
        assert record["scope"] == case["scope"]
        assert record["evidence_digest"] == "a" * 64
        original = next(h for h in case["hypotheses"] if h["id"] == record["hypothesis"]["id"])
        assert record["hypothesis"] == original
        assert record["reopening_trigger"] == original["reopening_trigger"]
    without_unknown = deepcopy(case)
    without_unknown["hypotheses"] = [h for h in case["hypotheses"] if h["id"] != "h7"]
    empty = allocator.update(without_unknown, [observe("z-repeat", "changed")])
    assert empty["all_declared_predictions_incompatible"] is True
    assert empty["physics_validated"] is False


def test_independent_exhaustive_oracle_matches_small_random_finite_cases():
    rng = random.Random(60206)
    oracle = benchmark().exhaustive_oracle
    for _ in range(40):
        case = fixture()
        case["actions"] = [{"id": f"a{i}", "cost": rng.randint(1, 3),
                            "outcomes": ["x", "y", "z"], "nominal_change": i} for i in range(4)]
        case["hypotheses"] = [{"id": f"h{i}", "predictions": {a["id"]: rng.choice(["x", "y", "z", None])
                                                                for a in case["actions"]},
                                "provenance": ["random hypothetical toy"], "reopening_trigger": "mapping changes"}
                               for i in range(6)]
        case["budget"] = rng.randint(0, 5)
        for horizon in (1, 2):
            assert allocator.recommend(case, horizon=horizon)["policy"] == oracle(case, horizon=horizon)["policy"]


@pytest.mark.parametrize("mutate", [
    lambda c: c.update(horizon=3),
    lambda c: c.update(budget=-1),
    lambda c: c.update(budget=True),
    lambda c: c["actions"][0].update(cost=0),
    lambda c: c["actions"][0].update(nominal_change=float("nan")),
    lambda c: c["actions"][0].update(nominal_change=10 ** 1000),
    lambda c: c["actions"][0].update(outcomes=["x"] * 5),
    lambda c: c["hypotheses"][0]["predictions"].update({"a-cheap": {"common": 0.5, "rare": 0.5}}),
    lambda c: c["hypotheses"][0]["predictions"].pop("a-cheap"),
    lambda c: c["hypotheses"][0].update(provenance=[]),
    lambda c: c["hypotheses"].append(deepcopy(c["hypotheses"][0])),
])
def test_malformed_or_probability_predictions_rejected(mutate):
    case = fixture()
    mutate(case)
    with pytest.raises(ValueError):
        allocator.recommend(case)


def test_explicit_raw_unique_and_action_bounds():
    case = fixture()
    for i in range(33):
        clone = deepcopy(case["hypotheses"][0])
        clone["id"] = f"clone{i}"
        case["hypotheses"].append(clone)
    with pytest.raises(ValueError, match="32"):
        allocator.recommend(case)
    case = fixture()
    for i in range(13):
        h = deepcopy(case["hypotheses"][0])
        h["id"] = f"distinct-{i}"
        h["predictions"]["a-cheap"] = [None, "common", "rare"][i % 3]
        h["predictions"]["b-balanced"] = [None, "left", "right"][(i // 3) % 3]
        h["predictions"]["c-orthogonal"] = [None, "odd", "even"][i // 9]
        case["hypotheses"].append(h)
    with pytest.raises(ValueError, match="12 distinct"):
        allocator.recommend(case)
    case = fixture()
    case["actions"] *= 2
    with pytest.raises(ValueError, match="8"):
        allocator.recommend(case)


def test_cli_report_and_strict_json_do_not_execute_or_overwrite(tmp_path):
    output = tmp_path / "report.json"
    subprocess.run([sys.executable, "-m", "ravel.workflow.experiment_allocator", "--case",
                    str(BASE / "experiment-allocation-case.json"), "--out", str(output)],
                   check=True, capture_output=True, text=True)
    result = json.loads(output.read_text())
    assert result["execution_authorized"] is False
    original = output.read_bytes()
    failed = subprocess.run([sys.executable, "-m", "ravel.workflow.experiment_allocator", "--case",
                             str(BASE / "experiment-allocation-case.json"), "--out", str(output)],
                            capture_output=True, text=True)
    assert failed.returncode == 1
    assert output.read_bytes() == original
    bad = tmp_path / "bad.json"
    for content in ('{"budget":1,"budget":2}', '{"nominal_change":NaN}'):
        bad.write_text(content)
        with pytest.raises(ValueError):
            allocator.read_json(bad)


def diagnosis_case(root):
    from test_research_default_protocol import write
    rows = [('z-replay', 2, 'calculation', 'pilot_cost'),
            ('a-stream', 2, 'stream', 'cost_preflight'),
            ('generation', 5, 'generation', 'pilot_cost'),
            ('heldout', 1, 'calculation', 'cost_preflight')]
    actions = []
    for identity, cost, cost_class, source in rows:
        measured = ({'kind': 'supervised_pilot_observation', 'wall_seconds': cost} if source == 'pilot_cost'
                    else {'schema_version': 3, 'generated_by': 'cost_preflight.py',
                          'calibration_status': 'measured', 'walltime_h': [cost/3600, cost/3600]})
        measured['cost_class'] = cost_class
        actions.append({'id': identity, 'cost': cost, 'outcomes': ['yes', 'no'], 'nominal_change': 0,
            'cost_class': cost_class, 'cost_measurement': write(root, identity+'-cost.json', measured),
            'exposure': 'withheld_confirmation' if identity == 'heldout' else 'adaptive_full'})
    return {'schema_version': 1, 'scope': 'Synthetic residual diagnosis',
        'prediction_basis': 'supplied_unvalidated', 'budget': 12, 'horizon': 1, 'actions': actions,
        'hypotheses': [{'id': 'h'+str(i), 'provenance': ['supplied'], 'reopening_trigger': 'new supplied evidence',
            'predictions': {a['id']: ('no' if i == j % 3 else 'yes') for j, a in enumerate(actions)}} for i in range(3)]}


def diagnosis_policy():
    return {'validation_reservation': 1, 'confirmation_reservation': 0, 'reserve_budget': 0,
            'coverage': {}, 'starvation_rounds': 2, 'rounds_since_exploration': 0}


def test_diagnosis_epoch_orders_measured_information_and_reserves_heldout(tmp_path):
    case = diagnosis_case(tmp_path)
    result = allocator.allocate(case, diagnosis_policy(), base_dir=tmp_path)
    assert result['policy']['first_action'] == 'z-replay'
    assert result['selection_order'] == ['z-replay', 'a-stream', 'generation']
    assert result['reserved_actions'] == ['heldout']
    assert result['reserved']['confirmation'] == 1
    assert all(s['action_id'] != 'heldout' for s in result['reserve_seats'])
    assert result['remaining_selection_budget'] == 10
    # Neither allocator nor coverage exploration schedules a withheld read.
    case['horizon'] = 2
    policy = diagnosis_policy(); policy.update(reserve_budget=3, rounds_since_exploration=2)
    result = allocator.allocate(case, policy, base_dir=tmp_path)
    assert result['policy']['first_action'] != 'heldout'
    assert 'heldout' not in result['policy']['then'].values()
    assert all(s['action_id'] != 'heldout' for s in result['reserve_seats'])


@pytest.mark.parametrize('mutation', ['class', 'cost', 'unmeasured', 'changed_pin'])
def test_measured_allocation_refuses_unbound_cost(tmp_path, mutation):
    case = diagnosis_case(tmp_path)
    action = case['actions'][0]
    if mutation == 'class': action['cost_class'] = 'generation'
    if mutation == 'cost': action['cost'] = 1
    if mutation == 'unmeasured':
        from test_research_default_protocol import write
        action['cost_measurement'] = write(tmp_path, 'uncalibrated.json', {'generated_by': 'cost_preflight.py',
            'calibration_status': 'uncalibrated', 'cost_class': 'calculation', 'walltime_h': [0, 1]})
    if mutation == 'changed_pin': Path(action['cost_measurement']['path']).write_text('{}')
    with pytest.raises(ValueError, match='cost|changed'):
        allocator.allocate(case, diagnosis_policy(), base_dir=tmp_path)


def test_unclassified_action_never_wins_measured_class_tie(tmp_path):
    case = diagnosis_case(tmp_path)
    legacy = {k: v for k, v in case['actions'][0].items() if k not in {'cost_class', 'cost_measurement'}}
    legacy['id'] = 'a-legacy'
    case['actions'].append(legacy)
    for hypothesis in case['hypotheses']:
        hypothesis['predictions']['a-legacy'] = hypothesis['predictions']['z-replay']
    result = allocator.allocate(case, diagnosis_policy(), base_dir=tmp_path)
    assert result['policy']['first_action'] == 'z-replay'
    assert result['selection_order'][:2] == ['z-replay', 'a-stream']
