"""Conditional staffing reaches the ordinary governed review dispatcher."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import review_points, spawn_rows
from ravel.workflow.graphs import review
from rdj_fixtures import Run
from test_review_points_graph import Workers, run_review, write


def requests():
    yield 'absolute', {'nodes': [], 'claims': [{'id': 'quantity', 'absolute_yield': True}]}
    for primary in (True, False):
        yield 'analytic-' + str(primary), {
            'nodes': [{'id': 'method', 'kind': 'operation', 'operation': 'formula-grid'}],
            'claims': [{'id': 'quantity', 'inherits': ['method'], 'primary': primary}]}
    yield 'model', {'nodes': [{'id': 'model', 'operation': 'model-sources'}], 'claims': []}
    for row in spawn_rows.catalogue()['rows']:
        if row.get('predicate') == 'declared-domain' and row['mode'] == 'specialist':
            metadata = {'domain_tags': row['tags_all'],
                        'experiments': ['source-' + str(i) for i in range(row['min_experiments'])]}
            yield row['row'], {'nodes': [{'id': 'combination', 'fields': [
                {'pointer': '/review/' + key, 'value': value} for key, value in metadata.items()]}],
                'claims': []}


CASES = list(requests())


def setup(root, request):
    pin = write(root / 'inputs/request_plan.json', {'edges': [], **deepcopy(request)})
    pin['path'] = 'inputs/request_plan.json'
    contract = json.loads((root / 'inputs/task_contract.json').read_text())
    write(root / 'inputs/task_contract.json', {**contract, 'agent_layer_epoch': 2,
          'delegated': True, 'request_plan': pin})
    return [p for p in spawn_rows.derive(review_points._facts(root)) if p['gate'] == 'checkin2_accept']


@pytest.mark.parametrize('name,specification', CASES, ids=[name for name, _ in CASES])
def test_conditional_staffing_is_reserved_dispatched_and_credited(tmp_path, monkeypatch, name, specification):
    root = Run(tmp_path / 'run', snapshot=False).root
    required = setup(root, specification)
    assert required
    derived = review.derive(root, 'checkin2', 0)
    expected = {(p['id'], role['role'], n) for p in required for role in p['roles']
                for n in range(1, role['count'] + 1)}
    actual = {(item['point_id'], item['role'], item['n']) for item in derived['items']}
    assert expected <= actual
    reserved = review.reservation_budget(root, review.instance('checkin2'))
    assert reserved['model_calls'] >= len(expected) * review.MAX_ROUNDS * review.ITEM_BUDGETS['max_turns']
    workers = Workers(root)
    observed = run_review(root, monkeypatch, workers, at='checkin2',
        gate_check=lambda run, gate, action: spawn_rows.gate_errors(run, gate, action))
    assert observed['terminal'] is None and not observed['next'], observed
    dispatched = {(c['packet']['point_id'], c['role'], c['packet']['n']) for c in workers.calls}
    assert expected <= dispatched
    assert not spawn_rows.gate_errors(root, 'checkin2_accept', {})
    before = deepcopy(workers.calls)
    run_review(root, monkeypatch, workers, at='checkin2', attempt=2,
        gate_check=lambda run, gate, action: spawn_rows.gate_errors(run, gate, action))
    assert workers.calls == before


def test_exact_selector_keeps_other_claims_separate(tmp_path):
    root = Run(tmp_path / 'run', snapshot=False).root
    setup(root, {'nodes': [], 'claims': [{'id': 'a'}, {'id': 'ab'}]})
    items = review.derive(root, 'checkin2:a', 0)['items']
    assert items and {item['claim_id'] for item in items} == {'a'}


def test_conditional_packet_authenticates_its_complete_policy(tmp_path):
    root = Run(tmp_path / 'run', snapshot=False).root
    required = setup(root, {'nodes': [], 'claims': [{'id': 'quantity', 'absolute_yield': True}]})
    item = next(item for item in review.derive(root, 'checkin2', 0)['items']
                if item['point_id'] == required[0]['id'])
    review.write_packets(root, [item])
    relative = review.packet_path(item)
    packet = json.loads((root / relative).read_text())
    assert packet['policy'] == required[0]
    assert review.authentic_packet(root, relative, packet)
    for mutation in ('remove', 'change'):
        changed = deepcopy(packet)
        if mutation == 'remove':
            changed.pop('policy')
        else:
            changed['policy']['roles'][0]['count'] += 1
        assert not review.authentic_packet(root, relative, changed)


def test_core_and_conditional_points_share_the_distinct_session_requirement(tmp_path, monkeypatch):
    import worker_supervision
    root = Run(tmp_path / 'run', snapshot=False).root
    setup(root, {'nodes': [], 'claims': [{'id': 'quantity', 'absolute_yield': True}]})
    original = worker_supervision.supervised

    def repeated_session(run, spec, **kwargs):
        if spec['role']['id'] == 'normalization-auditor':
            kwargs['session'] = 'one-observed-review-session'
        return original(run, spec, **kwargs)

    monkeypatch.setattr(worker_supervision, 'supervised', repeated_session)
    run_review(root, monkeypatch, Workers(root), at='checkin2')
    missing = [p for p in [*review_points.pending(root), *spawn_rows.pending(root)]
               if p.get('claim_id') == 'quantity']
    assert any(r['role'] == 'normalization-auditor' for p in missing for r in p['roles'])


def test_advisory_consultation_keeps_its_own_dispatcher(tmp_path):
    root = Run(tmp_path / 'run', snapshot=False).root
    setup(root, {'nodes': [{'id': 'method', 'kind': 'operation', 'operation': 'literal-calculation',
                           'tool': 'symbolic', 'rung': 'smoke', 'authored': {'draft': 'draft.json'}}],
                 'claims': []})
    point = next(point for point in spawn_rows.derive(review_points._facts(root)) if point['mode'] == 'advisory')
    items = review.derive(root, point['when']['at'], 0)['items']
    assert all(item['point_id'] != point['id'] for item in items)
    assert any(p['id'] == point['id'] for p in spawn_rows.pending(root))


@pytest.mark.parametrize('operation', ['theory-uncertainty', 'unfold'])
def test_uninstalled_specialist_has_typed_ending_before_worker_dispatch(tmp_path, monkeypatch, operation):
    from ravel.workflow import agent_worker
    from ravel.workflow.graph_nodes import RecoveryHold
    root = Run(tmp_path / 'run', snapshot=False).root
    required = setup(root, {'nodes': [{'id': 'quantity', 'operation': operation}], 'claims': []})
    assert required
    monkeypatch.setattr(agent_worker, 'dispatch', lambda *a, **kw: pytest.fail('unbound specialist dispatched'))
    with pytest.raises(RecoveryHold, match='review_role_unavailable'):
        review.reservation_budget(root, review.instance('checkin2'))
    observed = review.run(root, 'checkin2')
    assert observed['terminal']['status'] == 'hold'
    assert observed['terminal']['reason'] == 'review_role_unavailable'
    assert all(role['role'] in observed['terminal']['would_make_possible']
               for point in required for role in point['roles'])


@pytest.mark.parametrize('operation', ['theory-uncertainty', 'unfold'])
def test_unavailable_staffing_records_the_effective_registry_qualification(tmp_path, operation):
    from ravel.workflow import role_registry
    root = Run(tmp_path / 'run', snapshot=False).root
    points = setup(root, {'nodes': [{'id': 'quantity', 'operation': operation}], 'claims': []})
    for point in points:
        qualification = point['qualification']
        assert qualification['status'] == 'required-specialist-unavailable'
        assert qualification['registry_sha256'] == role_registry.registry_sha256()
        assert qualification['required_roles'] == sorted(role['role'] for role in point['roles'])
        assert point['blocking'] is True


def test_available_staffing_uses_the_effective_role_registry(monkeypatch):
    from ravel.validation import sm_checks
    from ravel.workflow import role_registry
    original = role_registry.load
    registry_sha = role_registry.registry_sha256()
    monkeypatch.setattr(role_registry, 'registry_sha256', lambda: registry_sha)
    seen = []
    def resolve(identity):
        seen.append(identity)
        return original('physics-critic')
    monkeypatch.setattr(role_registry, 'load', resolve)
    points = sm_checks.derive_review_points({'agent_layer_epoch': 2,
        'nodes': [{'id': 'quantity', 'operation': 'theory-uncertainty'}]})
    assert points and seen
    assert all('qualification' not in point for point in points)
