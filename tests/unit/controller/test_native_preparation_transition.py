"""A bounded preparation edge uses protected source/authority/binding, without CI1 credit."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.controller import authority, ledger
from ravel.controller.store import RunStore
from ravel.controller.ledger import gates
from ravel.controller.step import binding, graph, launch_gate, operations, spec
from ravel.controller.step.services import digest
from ravel.controller.routes.analysis.execution import acquisition_implementation
from ravel.workflow import decision_gate
from p02_support import fixture_catalogue, row, satisfy, use_catalogue
from test_p04_support import make_step
from test_p06_support import autonomous, operator_home  # noqa: F401


@pytest.fixture
def protected_preparation(tmp_path, monkeypatch, operator_home):
    # Only the fictional obligation catalogue is isolated. Store binding, journal,
    # signature, custody, authority issuer/replay and plan-bind checks are production.
    rows = [row('X-ADMISSION', 'controller.intake', 'intake', 'run'),
            row('X-ROUTE', 'controller.route_select', 'intake', 'run'),
            row('CHECKIN-1', 'authority.ci1', 'plan', 'run', select={'checkin': '1'}),
            row('GATE-approve_plan', 'ledger.gate[approve_plan]', 'plan', 'run', select={'gate': 'approve_plan'}),
            row('R13', 'step.plan_bind', 'plan', 'step'),
            row('I05', 'step.seat_derivation', 'plan', 'step'),
            row('GATE-launch', 'ledger.gate[launch]', 'plan', 'step', select={'gate': 'launch', 'launches': True}),
            row('X-CLEAN', 'confine.launch', 'seat', 'seat', select={'seat_kind': ['launch']})]
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    autonomous()
    store = RunStore.create(tmp_path / 'run')
    authority.freeze_mode(store, {'prompt': 'Read bounded publication metadata.'})
    step = make_step('bounded.source', kind='acquire', operation='acquire-published', role='coordinator',
        rung='none', budget={'wall_seconds': 7, 'events': 0}, outputs=(('outputs/census.json', 'document'),),
        parameters={'phase': 'prepare', 'effects': ['acquires_published'], 'task': {'max_bytes': 4096},
            'launch': {'argv': ['python', '-m', 'ravel.workflow.resource_census', '--reading', 'input.json',
                                '--controller-output', 'census.json'], 'stage': 'bounded-metadata'}})
    plan = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
            'route': {'id': 'analysis', 'version': 1, 'spec_sha256': None}, 'parameters': {},
            'steps': [step], 'deliverables': [], 'waypoints': [], 'checkins': [], 'obligations': [],
            'open_obligations': [], 'instruction_sources': []}
    plan['sha256'] = digest(plan)
    store.append('plan', {'plan_sha256': plan['sha256'], 'revision': 0,
                          'blob': store.put_blob(json.dumps(plan, sort_keys=True).encode())})
    ledger.materialise(store, 'intake', {'run_id': store.run_id, 'deliverables': []})
    ledger.materialise(store, 'plan', {'plan': plan})
    counts = binding.record_plan_rows(store, plan, contract_sha256=None, ledger=ledger)
    assert counts['refused'] == [] and counts['recorded'] == 2
    assert binding.unverified(ledger, store, step) == []
    proof = {'step_id': step['id'], 'seat': None, 'attempt': 1, 'mechanism': 'native-launch-preflight',
             'plan_sha256': plan['sha256'], 'step_sha256': spec.step_sha256(step),
             'launch_sha256': 'b' * 64, 'passed': True, 'budget': deepcopy(step['budget']),
             'stage': 'bounded-metadata', 'depends_on': [], 'correction': None,
             'preparation_implementation': acquisition_implementation(step),
             'log': str(store.run_dir / 'steps/bounded.source/attempts/1/logs/stdout'),
             'capsule': {'argv': step['parameters']['launch']['argv'], 'reads': [], 'writes': [],
                         'cwd': str(store.run_dir)}}
    preflight = store.append('step-fact', proof)
    context = {'run_id': store.run_id, 'run_dir': str(store.run_dir), 'plan_sha256': plan['sha256'], 'attempt': 1}
    graph._authorize(store, context, step, deepcopy(step['budget']), stage=proof['stage'])
    action = launch_gate.action(step, context, {'launch_sha256': proof['launch_sha256'],
                                              'budget': proof['budget']}, preflight)
    yield SimpleNamespace(store=store, step=step, plan=plan, proof=proof, action=action, context=context,
                          monkeypatch=monkeypatch)
    ledger._state.forget(store)


def select(n):
    return gates.transition_for(n.store, 'launch', n.action)


def test_real_protected_preparation_selects_only_its_own_preapproval_edge(protected_preparation):
    n = protected_preparation
    before = n.store.scan('step-authority')
    assert launch_gate.load(n.store.run_dir, n.action)[2] == n.step
    assert select(n) == ('prepare_launch[bounded.source]', frozenset({'GATE-launch'}))
    assert n.store.scan('step-authority') == before
    assert gates.decision_transition('launch', n.action) == ('launch[bounded.source]', frozenset({'GATE-launch'}))
    assert not any('authority.ci1' == r.get('node') for r in ledger.gate(n.store, select(n)[0]))


def test_preparation_edge_retains_real_intake_route_and_step_clean_requirements(protected_preparation):
    n = protected_preparation
    transition, own = select(n)
    unmet = ledger.gate(n.store, transition)
    assert {r['id'] for r in unmet} == {'X-ADMISSION', 'X-ROUTE'}
    assert all(r['id'] != 'GATE-launch' for r in unmet)
    satisfy(n.store, [r['entry'] for r in unmet])
    assert ledger.gate(n.store, transition) == []
    keys = ledger.materialise(n.store, 'dispatch', {'step': n.step['id'], 'seat': 'producer',
        'seat_kind': 'launch', 'attempt': 1})
    key = next(key for key in keys if key.startswith('X-CLEAN@'))
    ledger.record(n.store, key, 'violated', {'mechanism': 'negative-control', 'reason': 'negative-control'})
    assert any(r['id'] == 'X-CLEAN' and r['status'] == 'violated' for r in ledger.gate(n.store, transition))


def test_real_decision_ledger_path_uses_context_edge_but_does_not_mint_gate_credit(protected_preparation):
    n = protected_preparation
    assert {e.code for e in decision_gate._ledger_errors(n.store.run_id, 'launch', n.action)} == {'ledger_pending'}
    satisfy(n.store, [r['entry'] for r in ledger.gate(n.store, 'route_select→plan')])
    assert decision_gate._ledger_errors(n.store.run_id, 'launch', n.action) == []
    assert ledger.current(n.store, step=n.step['id'], node='ledger.gate[launch]')[0]['status'] == 'pending'


@pytest.mark.parametrize('fault', ['caller_flags', 'changed_code', 'missing_authority', 'stale_binding', 'R3',
                                   'wrong_store', 'missing_binding'])
def test_unproved_preparation_stays_on_ordinary_ci1_transition(protected_preparation, fault):
    n = protected_preparation
    if fault == 'caller_flags':
        n.action['phase'] = 'prepare'; n.action['preparation'] = True
    if fault == 'changed_code':
        current = deepcopy(acquisition_implementation(n.step))
        current['code'][next(iter(current['code']))] = '0' * 64
        from ravel.controller.routes.analysis import execution
        n.monkeypatch.setattr(execution, 'acquisition_implementation', lambda step: current)
    if fault == 'missing_authority':
        # A later exact step-authority row with no passed authority may not reuse an earlier check.
        latest = deepcopy(n.store.scan('step-authority')[-1]['record']); latest['authority'] = {}
        n.store.append('step-authority', latest)
    if fault == 'stale_binding':
        key = ledger.current(n.store, node='step.plan_bind', step=n.step['id'])[0]['entry']
        ledger.record(n.store, key, 'satisfied', {'step_sha256': '0' * 64, 'mechanism': 'negative-control'})
    if fault == 'R3':
        from ravel.workflow import rdj_loop
        n.monkeypatch.setattr(rdj_loop, 'compute_class', lambda *args, **kwargs: ('R3', {}))
    if fault == 'wrong_store':
        n.store = RunStore('different-unbound-run')
    if fault == 'missing_binding':
        n.monkeypatch.setattr(ledger, 'current', lambda *args, **kwargs: [])
    assert select(n) == gates.decision_transition('launch', n.action)
    assert gates.requirements('launch')[-2]['own'] == ('GATE-approve_plan',)


def test_other_decisions_keep_the_public_transition(protected_preparation):
    n = protected_preparation
    for gate in gates.DECISION_TRANSITIONS:
        if gate != 'launch':
            assert gates.transition_for(n.store, gate, n.action) == gates.decision_transition(gate, n.action)


def test_plan_binding_commits_its_checked_population_in_one_event(protected_preparation):
    n = protected_preparation
    status = [row['record']['body'] for row in n.store.scan('ledger')
              if row['record']['body']['event'] == 'status']
    assert len(status) == 1
    changes = status[0]['changes']
    current = [row for node in binding.PLAN_BIND_NODES
               for row in ledger.current(n.store, node=node, step=n.step['id'])]
    assert {row['key'] for row in changes} == {row['entry'] for row in current}
    assert len(changes) == len(current) == 2
    assert binding.unverified(ledger, n.store, n.step) == []
    for change in changes:
        proof = change['evidence']
        assert proof['sha256'] == n.plan['sha256']
        assert proof['step_sha256'] == digest(n.step)
        assert n.store.read(binding.FACT, proof['record'])['record']['step_sha256'] == digest(n.step)


def test_plan_binding_retains_each_refusal_after_an_atomic_batch_refusal(protected_preparation):
    n = protected_preparation
    rebound = deepcopy(n.plan)
    rebound['steps'][0]['budget']['wall_seconds'] += 1
    counts = binding.record_plan_rows(n.store, rebound, contract_sha256=None, ledger=ledger)
    assert counts['recorded'] == 1
    assert len(counts['refused']) == 1
    assert counts['refused'][0]['entry'].startswith('I05@')
    assert 'cannot go from not_applicable to not_applicable' in counts['refused'][0]['reason']
    rows = {row['id']: row for node in binding.PLAN_BIND_NODES
            for row in ledger.current(n.store, node=node, step=n.step['id'])}
    assert rows['I05']['status'] == 'not_applicable'
    assert rows['I05']['evidence']['step_sha256'] == digest(n.step)
    assert rows['R13']['status'] == 'satisfied'
    assert rows['R13']['evidence']['step_sha256'] == digest(rebound['steps'][0])
    assert n.store.scan(binding.FACT + '-refused')[-1]['record']['refused'] == counts['refused']


def test_plan_binding_verifies_one_locked_prefix_and_releases_it(protected_preparation):
    import os
    from ravel.controller.store import JOURNAL, StoreTampered
    n = protected_preparation
    rebound = deepcopy(n.plan)
    rebound['steps'][0]['budget']['wall_seconds'] += 1
    journal = n.store.root / JOURNAL
    opened = []
    original = Path.open

    def open_path(path, *args, **kwargs):
        if path == journal and args and args[0] == 'rb':
            opened.append(path)
        return original(path, *args, **kwargs)

    n.monkeypatch.setattr(Path, 'open', open_path)
    result = binding.record_plan_rows(n.store, rebound, contract_sha256=None, ledger=ledger)
    assert result['recorded'] == 1 and len(result['refused']) == 1
    assert len(opened) == 1, 'one verified locked prefix covers the complete checked population'
    assert n.store.verify() == []
    info, raw = journal.stat(), journal.read_bytes()
    changed = raw.replace(digest(n.step).encode(), b'0' * 64, 1)
    assert changed != raw and len(changed) == len(raw)
    journal.write_bytes(changed)
    os.utime(journal, ns=(info.st_atime_ns, info.st_mtime_ns))
    with pytest.raises(StoreTampered):
        n.store.latest(binding.FACT)
