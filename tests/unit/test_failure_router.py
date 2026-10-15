"""Deterministic routing controls; every recorded observation is synthetic."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parents[1] / 'fixtures/failures/synthetic.json').read_text())['failures']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_recorded_synthetic_failure_classification(case):
    from ravel.workflow.failure_router import classify
    result = classify(case['observations'])
    assert result['class_id'] == case['expected_class']
    assert result['consult_role'] == case['expected_role']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_suggestion_cannot_override_observed_class(case):
    from ravel.workflow.failure_router import classify
    changed = deepcopy(case['observations'])
    changed.update(suggestion={'class_id': 'infra.lease', 'role': 'coordinator'})
    assert classify(changed)['class_id'] == classify(case['observations'])['class_id']


def test_infrastructure_precedes_tool_prose_and_counts_separately():
    from ravel.workflow.failure_router import classify, denominators
    item = {'tool': 'pythia', 'exit_status': 1, 'stderr': 'PYTHIA abort', 'supervisor': {'lease_conflict': True}}
    result = classify(item)
    assert result['class_id'] == 'infra.lease' and not result['agent_required']
    counts = denominators([result, classify({'tool': 'pythia', 'exit_status': 1, 'stderr': 'PYTHIA abort'})])
    assert counts['infrastructure'] == counts['tool'] == 1 and counts['total'] == 2


def test_success_warning_does_not_open_a_failure():
    from ravel.workflow.failure_router import classify
    with pytest.raises(ValueError, match='failure'):
        classify({'tool': 'pythia', 'exit_status': 0, 'stderr': 'previous abort warning'})


@pytest.mark.parametrize('observations', [
    {'tool': 'pythia', 'exit_status': True},
    {'tool': 'rivet', 'exit_status': 1, 'failed_checks': 'validate_cutflow'},
    {'tool': 'rivet', 'exit_status': 1, 'signal': -1},
])
def test_malformed_observations_refused(observations):
    from ravel.workflow.failure_router import classify
    with pytest.raises(ValueError):
        classify(observations)


def test_twelve_bindings_resolve_readonly_cards_and_tool_groups():
    from ravel.workflow.consults import bindings
    from ravel.workflow import role_registry
    rows = bindings()['consults']
    assert len(rows) == 13 and list(rows)[12:] == ['consult-higgs']
    groups = {g for row in rows.values() for g in row['manifest_groups']}
    assert {'madgraph', 'rivet-shower', 'recast-base', 'site-access', 'finite-integrals'} <= groups
    for row in rows.values():
        card = role_registry.load(row['role'])
        assert card['requires']['tools'] == 'broker-readonly'
        assert card['independence']['kind'] == 'advisory'


def test_supervisor_translation_retains_missing_exit_and_recovery_is_advisory():
    from ravel.workflow.failure_router import classify, from_supervisor, recovery_packet
    source = {'generated_by': 'stage_supervisor.py', 'stage': 'rivet', 'reason': 'worker failed'}
    observed = from_supervisor(source, stderr='fatal error: compilation terminated')
    assert observed['exit_status'] is None and classify(observed)['class_id'] == 'tool.rivet.compile'
    proposal = recovery_packet(observed, evidence=[{'path': 'outputs/sibling.json', 'sha256': '1' * 64}])
    assert proposal['retry_authorized'] is proposal['failure_closed'] is proposal['physics_validated'] is False
    assert proposal['evidence'][0]['path'] == 'outputs/sibling.json'


def test_recovery_route_ranking_cannot_override_failure_class(monkeypatch):
    from ravel.workflow import failure_router, recast_route
    called = []
    def ranked(**facts):
        called.append(facts)
        return {'routes': [{'id': 'sibling-route'}]}
    monkeypatch.setattr(recast_route, 'rank_routes', ranked)
    result = failure_router.recovery_routes({'tool': 'pyhf', 'exit_status': 1, 'stderr': 'Invalid patch'},
                                            signal_basis='supplied_events', routine_ids=['sibling'])
    assert result['failure']['class_id'] == 'tool.fit.pyhf.patch'
    assert result['prospective_routes']['routes'][0]['id'] == 'sibling-route'
    assert result['retry_authorized'] is False and called
