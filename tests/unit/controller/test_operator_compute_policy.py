"""Operator cost grants preserve ceilings and bind adaptive spending to adopted results."""
from copy import deepcopy
from hashlib import sha256
import importlib
import json
import sys

import pytest

from ravel.controller.authority import cli, freeze_child, freeze_mode, operator
from ravel.controller.step import budget, graph, services, spec
from ravel.controller.step.services import StepHold
from test_p04_reserve import _reserve_state, _top_step
from test_p04_support import records, run_env, services_installed  # noqa: F401
from test_p06_support import new_store, operator_home  # noqa: F401


@pytest.mark.parametrize('mode', ['bounded', 'generous', 'adaptive'])
def test_operator_cli_policy_is_frozen_with_existing_budgets(operator_home, tmp_path, mode):
    assert cli.main(['init', '--mode', 'autonomous', '--compute-policy',
                     json.dumps({'mode': mode}), '--budget', 'cost_usd=null']) == 0
    original = freeze_mode(new_store(tmp_path), {'prompt': 'Calculate a fictional scalar.', 'route': 'calculation'})
    assert original['compute_policy'] == {'mode': mode}
    assert original['budgets']['cost_usd'] is None
    child = freeze_child(new_store(tmp_path, 'child'), new_store(tmp_path), {'prompt': 'Compute one child point.'})
    assert child['compute_policy'] == original['compute_policy']
    assert child['agent_preferences'] == original['agent_preferences']
    operator.set_values({'compute_policy': {'mode': 'bounded'}, 'budgets': {'cost_usd': 1}})
    assert freeze_mode(new_store(tmp_path), {'prompt': 'Calculate a fictional scalar.', 'route': 'calculation'}) == original


def test_policy_vocabulary_and_budget_ownership(operator_home):
    assert operator.default_config()['compute_policy'] == {'mode': 'bounded'}
    for value in ({'mode': 'automatic'}, {'mode': 'generous', 'budgets': {'tokens': None}}, None):
        with pytest.raises(ValueError):
            operator.validate({**operator.default_config(), 'compute_policy': value})


def test_disclosed_policy_keeps_the_closed_decision_contract():
    from jsonschema import Draft202012Validator
    from ravel.controller.engagement.records import data
    schema = data('schemas/engagement-decision.v1.json')['properties']['compute_policy']
    validator = Draft202012Validator(schema)
    for mode in ('bounded', 'generous', 'adaptive'):
        validator.validate({'mode': mode})
    for value in ({'mode': 'automatic'}, {'mode': 'generous', 'budgets': {}}, {}):
        assert list(validator.iter_errors(value))


def configure(env, monkeypatch, mode):
    frozen = {'id': 'frozen-grant', 'compute_policy': {'mode': mode},
              'budgets': deepcopy(env.fakes['authority'].budgets), 'agent_preferences': None}
    monkeypatch.setattr(sys.modules['ravel.controller.authority'], 'frozen', lambda *_a, **_k: frozen, raising=False)
    return frozen


@pytest.mark.parametrize('mode,admitted', [('bounded', False), ('generous', True), ('adaptive', False)])
def test_cost_grant_controls_the_actual_reservation(run_env, monkeypatch, mode, admitted):
    configure(run_env, monkeypatch, mode)
    state = _reserve_state(run_env, _top_step())
    with services.bound(run_env.store):
        if admitted:
            result = graph.reserve(state)
            assert result['reservation']['record_id']
            receipt = records(run_env.store, 'compute-policy-admission')[-1]
            assert receipt['mode'] == mode and receipt['amounts']['events'] == 100
            assert records(run_env.store, 'authority') == []
            replay = graph.reserve(state)
            assert replay['reservation'] == result['reservation']
            assert len(records(run_env.store, 'compute-policy-admission')) == 1
            gate = graph.cost_authority({**state, **result})
            assert gate['gates']['cost_authority']['errors'] == []
        else:
            with pytest.raises(StepHold):
                graph.reserve(state)
            assert records(run_env.store, 'budget-reservation') == []


@pytest.mark.parametrize('mode', ['bounded', 'generous', 'adaptive'])
def test_every_policy_keeps_the_operator_ceiling(run_env, monkeypatch, mode):
    configure(run_env, monkeypatch, mode)
    run_env.fakes['authority'].budgets['events'] = 99
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.reserve(_reserve_state(run_env, _top_step()))
    assert held.value.reason == 'budget_exhausted'
    assert records(run_env.store, 'budget-reservation') == []


def adoption(env, artifact, value, *, inputs=()):
    sid, path = artifact.split(':', 1)
    raw = value if type(value) is bytes else json.dumps(value).encode()
    destination = f'steps/{sid}/{path}'
    target = env.run_dir / destination
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    env.store.append('custody', {'artifact': artifact, 'step_id': sid, 'attempt': 1,
        'destination': destination, 'path': path, 'sha256': sha256(raw).hexdigest(), 'status': 'accepted',
        'inputs': list(inputs), 'producer': {'kind': 'worker'}})
    env.store.append('step-outcome', {'step_id': sid, 'attempt': 1, 'status': 'completed'})
    return target


@pytest.mark.parametrize('damage', [None, 'binary', 'stop', 'changed', 'foreign', 'empty_gain', 'unknown_evidence'])
def test_adaptive_cost_uses_result_receipts_and_rechecks_them(run_env, monkeypatch, damage):
    frozen = configure(run_env, monkeypatch, 'adaptive')
    state = _reserve_state(run_env, _top_step(compute_justification='decision:outputs/compute.json'))
    step = state['step']
    evidence = adoption(run_env, 'result:outputs/result.json',
                        b'\x00\x01\x02' if damage == 'binary' else {'value': 1.2})
    value = {'schema_version': 1, 'kind': 'compute-justification',
             'plan_sha256': state['context']['plan_sha256'], 'step_sha256': spec.step_sha256(step),
             'decision': 'continue', 'expected_gain': 'Resolve the observed residual with a larger sample.',
             'cost_justification': 'The additional precision resolves the remaining decision.',
             'evidence_artifacts': ['result:outputs/result.json']}
    if damage == 'stop': value['decision'] = 'stop'
    if damage == 'foreign': value['plan_sha256'] = 'f' * 64
    if damage == 'empty_gain': value['expected_gain'] = ' '
    if damage == 'unknown_evidence': value['evidence_artifacts'] = ['absent:outputs/result.json']
    adoption(run_env, 'decision:outputs/compute.json', value, inputs=['result:outputs/result.json'])
    if damage == 'changed': evidence.write_text('{}')
    plan = {'sha256': state['context']['plan_sha256'], 'steps': [
        {'id': 'result', 'outputs': [{'path': 'outputs/result.json'}]},
        {'id': 'decision', 'outputs': [{'path': 'outputs/compute.json'}]}, step]}
    policy = importlib.import_module('ravel.controller.engagement.compute')
    monkeypatch.setattr(policy, 'current_plan', lambda *_a: plan)
    with services.bound(run_env.store):
        if damage not in (None, 'binary'):
            with pytest.raises(StepHold): graph.reserve(state)
            assert records(run_env.store, 'budget-reservation') == []
            return
        reserved = graph.reserve(state)
        receipt = records(run_env.store, 'compute-policy-admission')[-1]
        assert receipt['mode'] == 'adaptive' and len(receipt['justification']['evidence']) == 1
        assert receipt['justification']['decision']['expected_gain'] == value['expected_gain']
        assert receipt['mode_record'] == frozen['id']
        pins = {'plan_sha256': state['context']['plan_sha256'], 'step_sha256': spec.step_sha256(step)}
        assert policy.verify(run_env.store, reserved['reservation']['record_id'], pins, state['context'])
        gate = graph.cost_authority({**state, **reserved})
        assert gate['gates']['cost_authority']['errors'] == []
        evidence.write_text('{}')
        with pytest.raises(StepHold):
            policy.verify(run_env.store, reserved['reservation']['record_id'], pins, state['context'])


@pytest.mark.parametrize('mutation', ['policy', 'preferences', 'amounts', 'pins'])
def test_generous_admission_replays_current_grant_and_reservation(run_env, monkeypatch, mutation):
    frozen = configure(run_env, monkeypatch, 'generous')
    state = _reserve_state(run_env, _top_step())
    policy = importlib.import_module('ravel.controller.engagement.compute')
    with services.bound(run_env.store):
        reserved = graph.reserve(state)
        pins = {'plan_sha256': state['context']['plan_sha256'],
                'step_sha256': spec.step_sha256(state['step'])}
        assert policy.verify(run_env.store, reserved['reservation']['record_id'], pins, state['context'])
        if mutation == 'policy': frozen['compute_policy'] = {'mode': 'bounded'}
        elif mutation == 'preferences': frozen['agent_preferences'] = {'tier_models': {}}
        elif mutation == 'pins': pins['step_sha256'] = '0' * 64
        else:
            original = records(run_env.store, 'budget-reservation')[-1]
            changed = deepcopy(original)
            changed['amounts']['events'] += 1
            identifier = run_env.store.append('budget-reservation', changed)
            reserved['reservation']['record_id'] = identifier
        with pytest.raises(StepHold):
            policy.verify(run_env.store, reserved['reservation']['record_id'], pins, state['context'])
