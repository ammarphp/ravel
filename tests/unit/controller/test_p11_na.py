"""Stage-observation controls; no fixture claims whole-campaign completion.

Peer authority readers are isolated here. The observer, stage action, authenticated
artifact reads, and role/session/family comparison run their original code.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.workflow import research_architecture as architecture, review_points
from ravel.workflow import research_cycle as cycle, research_protocol as protocol
from ravel.workflow import research_coordinator_decisions as decisions
from ravel.workflow import state_io


@pytest.fixture
def na_observation(tmp_path, monkeypatch):
    child, root = tmp_path / 'ordinary-child', tmp_path / 'campaign'
    child.mkdir()
    root.mkdir()
    state_io.atomic_json(child / cycle.CHILD_CONTRACT_ORIGIN,
                         {'root': str(root), 'experiment_id': 'not-executed'})

    def pin(name, value):
        target = root / name
        state_io.atomic_json(target, value)
        return cycle._pin(target)

    artifact = pin('declared-screen-na.json', {'status': 'not_applicable',
        'reason': 'Local observation control: the supplied route requires no screening population.'})
    definition = protocol.default_protocol()
    screen = next(row for row in definition['stages'] if row['id'] == 'screen')
    pins = {}
    # Actual pin-backed peer observations; no synthetic acceptance/authority labels.
    for role in sorted({role for row in definition['stages'] for role in row['roles']}):
        pins[role] = pin(role + '-observation.json', {
            'transport': {'actor_id': 'actor-' + role, 'invocation_id': 'session-' + role,
                          'observed_model': 'gpt-5'},
            'context_manifest_sha256': cycle.ce.digest({'role': role}),
            'context_transport_separated': True})
    declared = {'id': 'screen', 'status': 'not_applicable', 'applicability': 'declared',
                'roles': list(screen['roles']), 'bound': deepcopy(screen['bound']),
                'worker_receipts': {role: pins[role] for role in screen['roles']}, 'artifact': artifact}
    computed = {'id': 'acceptance', 'status': 'not_applicable', 'applicability': 'computed',
                'roles': [], 'worker_receipts': {}}
    record = {'stages': [computed, declared]}
    state = {'base_dir': str(root), 'experiments': [], 'methodology': record}
    calls = {'bound': [], 'computed': [], 'authorization': [], 'origin': []}

    def origin(path):
        calls['origin'].append(str(path))
        assert Path(path).resolve() == child

    def bound(campaign, role, *, stage_id=None, state=None):
        assert Path(campaign) == root
        calls['bound'].append((role, stage_id))
        if stage_id is not None:
            assert stage_id == 'screen' and state is not None
            return protocol._method_json(declared['worker_receipts'][role], root)
        return protocol._method_json(pins[role], root)

    def inapplicable(stage_id, campaign):
        calls['computed'].append(stage_id)
        assert Path(campaign) == root
        return stage_id == 'acceptance'

    action = protocol.stage_action('screen', artifact)
    decision_pin = pin('screen-decision-observation.json', {'kind': 'fixture-decision-observation',
                                                          'action': action})

    def authorization(campaign, gate, proposed):
        assert Path(campaign) == root and gate == 'research_choice' and proposed == action
        calls['authorization'].append(deepcopy(proposed))
        return {'receipt_sha256': decision_pin['sha256'],
                'receipt': protocol._method_json(decision_pin, root)}

    monkeypatch.setattr(cycle, 'verify_experiment_contract', origin)
    monkeypatch.setattr(cycle, '_load', lambda campaign: (root, state))
    monkeypatch.setattr(protocol, 'methodology_status', lambda campaign: {'complete': True, 'record': record})
    monkeypatch.setattr(review_points, '_facts', lambda campaign: {'agent_layer_epoch': 2})
    monkeypatch.setattr(decisions, 'bound_stage_receipt', bound)
    monkeypatch.setattr(protocol, 'stage_inapplicable', inapplicable)
    monkeypatch.setattr(protocol, 'decision_errors', lambda campaign, proposed: [])
    monkeypatch.setattr(architecture.rdj_loop, 'authorizing_receipt', authorization)
    return {'child': child, 'root': root, 'record': record, 'declared': declared,
            'pins': pins, 'decision': decision_pin, 'calls': calls}


def observe(control):
    return architecture.observe(control['child'], [], {'governed': False, 'artifacts': []})


def test_STAGE_screen_declared_na_retains_roles_bound_receipts_family_and_decision(na_observation):
    control = na_observation
    before = deepcopy(control['record'])
    result = observe(control)
    assert result['status'] == 'unknown' and result['complete'] is False
    assert result['errors'] == ['research has no ordinary experiment population']
    assert result['scientific_acceptance'] == 'not_assessed' and result['parent_task_accepted'] is False
    computed, declared = result['stages']
    assert computed == {'stage': 'acceptance', 'status': 'computed_not_applicable', 'roles': []}
    assert declared['stage'] == 'screen' and declared['status'] == 'observed'
    assert declared['roles'] == [{'role': role, 'receipt': control['pins'][role], 'observed_model': 'gpt-5'}
                                 for role in control['declared']['roles']]
    for role in control['declared']['roles']:
        assert (role, 'screen') in control['calls']['bound']
        family = declared['families'][role]
        assert family['session_check'] == 'distinct'
        assert family['family_check'] == 'same'
        assert family['family_label'] == 'separate session, same model family'
    assert declared['decision_receipt_sha256'] == control['decision']['sha256']
    assert declared['nested_decisions'] == []
    assert control['calls']['authorization'] == [protocol.stage_action('screen', control['declared']['artifact'])]
    assert control['calls']['computed'] == ['acceptance']
    assert control['record'] == before


def test_STAGE_acceptance_computed_na_has_no_role_or_decision_dispatch(na_observation, monkeypatch):
    control = na_observation
    control['record']['stages'] = [control['record']['stages'][0]]
    result = observe(control)
    assert result['stages'] == [{'stage': 'acceptance', 'status': 'computed_not_applicable', 'roles': []}]
    assert control['calls']['bound'] == [] and control['calls']['authorization'] == []
    assert result['complete'] is False and result['errors'] == ['research has no ordinary experiment population']


def test_STAGE_screen_declared_na_refuses_missing_current_worker_receipt(na_observation):
    control = na_observation
    Path(control['pins'][control['declared']['roles'][0]]['path']).unlink()
    result = observe(control)
    assert result['status'] == 'unknown' and result['complete'] is False
    assert [row['stage'] for row in result['stages']] == ['acceptance']
    assert result['errors'] and 'ordinary experiment population' not in result['errors'][0]
    assert control['calls']['authorization'] == []


def test_STAGE_screen_declared_na_refuses_missing_current_decision_authorization(na_observation, monkeypatch):
    monkeypatch.setattr(architecture.rdj_loop, 'authorizing_receipt', lambda *args: None)
    result = observe(na_observation)
    assert result['status'] == 'unknown' and result['complete'] is False
    assert result['errors'] == ['stage has no current registered decision authorization']
    assert [row['stage'] for row in result['stages']] == ['acceptance']
