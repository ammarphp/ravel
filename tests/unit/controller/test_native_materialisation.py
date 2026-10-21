"""Native packet absence is scoped before actual dispatch checks, never science credit."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ravel.controller import ledger as REAL_LEDGER
from ravel.controller.step import graph, services, spec
from ravel.controller.step.services import StepHold
from test_p04_support import context, make_step, records, run_env, services_installed


@pytest.fixture
def prepared(run_env, monkeypatch):
    env = run_env
    def build(branch='launch'):
        step = make_step('native.materialise', kind={'launch': 'operate', 'subgraph': 'subgraph',
                         'worker': 'author'}[branch], role=None if branch != 'worker' else 'baseline-producer',
                         parameters={'phase': 'prepare', 'evidence_requirements': {'required': True}})
        ctx = context(env.store, env.run_dir, 'a' * 64)
        state = {'step': step, 'acting': step, 'context': ctx, 'branch': branch,
                 'packet': {'kind': branch, 'instruction_entries': ['packet-extra@scope']},
                 'reservation': {'record_id': env.store.append('budget-reservation', {'step_id': step['id']}),
                                 'amounts': {'events': 0}}}
        if branch == 'subgraph': step['graph'] = {'id': 'fictional.graph', 'version': 1}
        if branch == 'worker': state['card'] = {'id': 'baseline-producer'}
        entries = ['CF03@native', 'I01@native', 'ROLE-baseline-producer-purpose@native',
                   'P05@native', 'E22@native', 'NORM@native', 'CUTFLOW@native']
        written = []; calls = []
        ledger = SimpleNamespace(materialise=lambda store, stage, scope: calls.append(
            ('materialise', stage, deepcopy(scope))) or list(entries), current=lambda store: [],
            record=lambda store, entry, status, evidence: written.append((entry, status, deepcopy(evidence))))
        original = graph.module
        monkeypatch.setattr(graph, 'module', lambda name: ledger if name == 'ledger' else original(name))
        monkeypatch.setattr(graph.operations, 'plan_step', lambda *a: (step, ctx['plan_sha256'], 'fixture'))
        monkeypatch.setattr(graph.operations, 'current_plan', lambda *a: {'sha256': ctx['plan_sha256']})
        monkeypatch.setattr(graph.operations, 'route_context', lambda *a: {})
        monkeypatch.setattr(graph.operations, 'route_errors', lambda *a: [])
        monkeypatch.setattr(graph.custody, 'input_errors', lambda *a, **k: ([], [], []))
        monkeypatch.setattr(graph.custody, 'parent_errors', lambda *a: [])
        monkeypatch.setattr(graph, '_seat_roles', lambda *a: [])
        monkeypatch.setattr(graph, '_card', lambda *a, **k: None)
        def dispatch(*args):
            assert calls and calls[0][0] == 'materialise', 'dispatch saw no scoped row population'
            calls.append(('dispatch',))
            return {'launch_sha256': 'b' * 64, 'output_root': str(env.run_dir / 'outputs'),
                    'capsule': {'argv': ['fictional-native'], 'reads': [], 'writes': [], 'cwd': str(env.run_dir)}}
        monkeypatch.setattr(graph, '_launch_preflight', dispatch)
        monkeypatch.setattr(graph, '_worker_preflight', dispatch)
        from ravel.controller.routes.study import runtime
        def science(store, actual, actual_ctx, *, phase):
            assert calls and calls[0][0] == 'materialise'
            assert phase == 'dispatch' and actual_ctx['ledger_scope']['step'] == step['id']
            calls.append(('science',))
            return []
        monkeypatch.setattr(runtime, 'scientific_checks', science)
        return state, entries, written, calls
    return build


@pytest.mark.parametrize('branch', ['launch', 'subgraph', 'worker'])
def test_all_branches_materialise_before_dispatch_and_scientific_checks(run_env, prepared, branch):
    state, entries, written, calls = prepared(branch)
    with services.bound(run_env.store):
        result = graph.preflight(state)
    assert set(entries + ['packet-extra@scope']) <= set(result['preflight']['instruction_entries'])
    assert calls[0][0] == 'materialise' and calls[-1][0] == 'science'
    if branch == 'worker':
        assert written == [] and not records(run_env.store, 'step-fact')[-1].get('packet_kind')
    else:
        assert {entry for entry, _, _ in written} == set(entries[:3])
        facts = [row for row in records(run_env.store, 'step-fact')
                 if row['mechanism'] == 'native-instruction-packet-absence']
        assert len(facts) == 1
        fact = facts[0]
        assert fact['step_sha256'] == spec.step_sha256(state['acting'])
        assert fact['attempt'] == 1 and fact['branch'] == fact['packet_kind'] == branch
        assert fact['reservation'] == state['reservation']['record_id']
        assert all(result['evaluations'][entry.split('@')[0]]['instruction_recorded'] for entry, _, _ in written)
        assert all(status == 'not_applicable' and evidence['record'] for _, status, evidence in written)
        assert not {'P05', 'E22', 'NORM', 'CUTFLOW'} & set(result['evaluations'])


@pytest.mark.parametrize('damage', ['branch', 'packet', 'manifest', 'reservation'])
def test_native_packet_absence_refuses_mismatched_or_unbound_identity(run_env, prepared, damage):
    state, _, written, calls = prepared()
    if damage == 'branch': state['acting']['kind'] = 'author'
    if damage == 'packet': state['packet']['kind'] = 'worker'
    if damage == 'manifest': state['packet']['manifest'] = {'id': 'agent-packet'}
    if damage == 'reservation': state['reservation']['record_id'] = ''
    with services.bound(run_env.store), pytest.raises(StepHold) as held:
        graph.preflight(state)
    assert held.value.reason == 'native_instruction_packet_invalid'
    assert written == [] and not any(row[0] == 'dispatch' for row in calls)


def test_native_packet_absence_records_exact_instances_in_real_protected_ledger(tmp_path, monkeypatch):
    from ravel.controller.store import RunStore
    store = RunStore('run-native-materialisation', root=tmp_path / 'store')
    REAL_LEDGER.materialise(store, 'intake', {'run_id': store.run_id})
    step = make_step('native.real', kind='operate', role=None)
    state = {'step': step, 'acting': step, 'branch': 'launch', 'packet': {'kind': 'launch'},
             'context': {'run_id': store.run_id, 'attempt': 1},
             'reservation': {'record_id': store.append('budget-reservation', {'step_id': step['id']})}}
    monkeypatch.setattr(graph, '_store', lambda actual: store)
    monkeypatch.setattr(graph, 'module', lambda name: REAL_LEDGER)
    stage, scope, _, _ = graph._ledger_binding(state)
    entries = list(REAL_LEDGER.materialise(store, stage, scope))
    assert entries
    exact, evaluations = graph._native_instruction_absence(state, entries)
    assert exact == entries and evaluations
    population = {row['entry']: row for row in REAL_LEDGER.current(store)}
    for entry in entries:
        row = entry.split('@', 1)[0]
        if row in evaluations:
            assert population[entry]['status'] == 'not_applicable'
            fact = store.read('step-fact', population[entry]['evidence']['record'])['record']
            assert fact['mechanism'] == 'native-instruction-packet-absence'
            assert fact['step_id'] == step['id'] and fact['attempt'] == 1
        else:
            assert population[entry]['status'] == 'pending'
    assert all(value['instruction_recorded'] for value in evaluations.values())
