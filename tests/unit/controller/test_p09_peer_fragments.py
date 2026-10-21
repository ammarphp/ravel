"""Inert composition proofs for the exact P04 integration fragment.

These tests use real peer admission/launch nodes after integration. The package's
binding-only tests remain runnable independently of peer source availability.
"""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

peer = pytest.importorskip('ravel.controller.step.graph')
from ravel.controller.step import operations  # noqa: E402
from ravel.controller.routes import analysis  # noqa: E402
from ravel.controller.routes.analysis import common  # noqa: E402
from p09_support import (Store, adopt_prepare, compile_plan, context, contract, reading)  # noqa: E402


def _setup(tmp_path, *, scan=False):
    store = Store(root=tmp_path / 'store')
    read, con = reading(scan=scan), contract('scan' if scan else 'reproduce')
    plan = compile_plan('analysis.scan' if scan else 'analysis', read, con)
    ctx = context(store, tmp_path, plan, read, con, adopt_prepare(store, tmp_path, plan,
                                                                    cost_mode='scan' if scan else 'full'))
    plan = analysis.bind(plan, ctx) or plan
    ctx.update(plan=plan, plan_sha256=plan['sha256'], run_id=store.run_id, attempt=1)
    return store, plan, ctx


def test_E04_every_route_operation_and_context_slot_passes_real_peer_admission(tmp_path):
    store, plan, ctx = _setup(tmp_path, scan=True)
    for step in plan['steps']:
        if not step.get('operation'):
            continue
        assert operations.executor_errors(step) == [], step['id']
        found = [{'artifact': i['artifact'], 'kind': i['kind']} for i in step['inputs'] if i.get('kind')]
        assert operations.admission_errors(step, approved=step, inputs_custody=found) == [], step['id']
        bad = deepcopy(step); bad['outputs'].append({'path': 'outputs/foreign', 'kind': 'undeclared-kind'})
        assert operations.admission_errors(bad), step['id']


def _services(monkeypatch, store, ctx, step, *, refused=False):
    checks = []
    def authorize(actual, effect):
        assert actual is store
        assert effect['pins']['plan_sha256'] == ctx['plan_sha256']
        assert effect['id'] == step['id']
        checks.append(effect)
        return {'approve_plan': 'ci1-fixture', 'go': 'ci2-fixture'}
    # The fixture run's frozen mode and current resource envelope (no retained-disk ceiling): storage
    # admission of governed acquisitions reads them from the same authority service as the launch gate.
    mode = {'id': 'mode-fixture', 'run_id': store.run_id, 'disk_free_floor_bytes': 0}
    authority = SimpleNamespace(authorize_effect=authorize, stop_state=lambda store: 'running',
                                frozen=lambda actual, *, required=True: deepcopy(mode),
                                effective_bounds=lambda actual: {'budgets': {}, 'bounds': {},
                                                                 'mode_record': mode['id']})
    gate_calls = []
    def decide(actual, rundir, gate, action):
        # This declared peer boundary records native admission; real provider gates
        # have their own protected-store controls, rather than this interface fake.
        assert actual is store and Path(rundir) == Path(ctx['run_dir']) and gate == 'launch'
        assert action['step'] == action['node_id'] == step['id']
        current = operations.current_plan(store, ctx)
        assert current['sha256'] == ctx['plan_sha256']
        pins = action['view_pins']
        assert pins['plan_sha256'] == ctx['plan_sha256']
        attempt = ctx['attempt']
        assert type(attempt) is int and attempt > 0 and pins['attempt'] == str(attempt)
        assert pins['step_sha256'] == peer.spec.step_sha256(step)
        proof = store.read('step-fact', pins['native_preflight'])['record']
        assert proof['mechanism'] == 'native-launch-preflight' and proof['passed'] is True
        assert proof['step_id'] == step['id'] and type(proof['attempt']) is int and proof['attempt'] == attempt
        assert all(proof[key] == pins[key] for key in ('plan_sha256', 'step_sha256', 'launch_sha256'))
        assert action['budget'] == proof['budget'] and action['digest'] == common.digest(pins)
        gate_calls.append(deepcopy(action))
        return [{'code': 'unresolved_review'}] if refused else []
    confine = SimpleNamespace(gate_calls=gate_calls)
    ledger = SimpleNamespace(decide=decide)
    services = {'authority': authority, 'confine': confine, 'ledger': ledger}
    monkeypatch.setattr(peer, '_store', lambda state: store)
    monkeypatch.setattr(peer, 'module', lambda name: services[name])
    # Resource admission resolves the authority service itself; it must see the same declared fake.
    from ravel.controller.step import services as step_services
    resolve = step_services.module
    monkeypatch.setattr(step_services, 'module', lambda name: services[name] if name in services else resolve(name))
    monkeypatch.setattr(peer, '_probe', lambda kind, target: {'network': 'none', 'writable': target['writes']})
    monkeypatch.setattr(peer, '_controller_dispatch', lambda run_dir: nullcontext())
    return confine, checks


def test_P04_E22_E23_real_peer_resolves_inputs_records_point_authority_and_launch_receipt(tmp_path, monkeypatch):
    store, plan, ctx = _setup(tmp_path, scan=True)
    step = next(s for s in plan['steps'] if s['id'].startswith('scan.point.'))
    point = step['parameters']['point_id']; ctx['point'] = point
    path = tmp_path / 'inputs/declared.json'; path.parent.mkdir(exist_ok=True); path.write_text('{}')
    artifact = 'inputs/declared.json'
    step['inputs'] = [{'artifact': artifact, 'sha256': common.file_sha256(path), 'kind': 'document'}]
    step['parameters']['launch'] = {'argv': ['fictional-native', '@input:' + artifact], 'reads': [], 'memory_mib': 4}
    run_inputs = [{'artifact': artifact, 'path': artifact, 'sha256': common.file_sha256(path)}]
    plan['sha256'] = common.digest({key: value for key, value in plan.items() if key != 'sha256'})
    ctx['plan_sha256'] = plan['sha256']
    blob = store.put_blob(json.dumps(plan).encode())
    store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'revision': plan['revision']})
    state = {'step': step, 'acting': step, 'context': ctx, 'branch': 'launch',
             'reservation': {'amounts': {'wall_seconds': 7}}, 'validation': {'passed': True}, 'checks': {}}
    confine, checks = _services(monkeypatch, store, ctx, step)
    state['preflight'] = peer._launch_preflight(state, store, ctx, tmp_path, step, None, [], run_inputs, {})
    state['preflight']['plan_sha256'] = ctx['plan_sha256']
    state['preflight']['budget'] = deepcopy(state['reservation']['amounts'])
    state['preflight']['native_preflight'] = store.append('step-fact', {
        'step_id': step['id'], 'seat': None, 'attempt': ctx['attempt'], 'mechanism': 'native-launch-preflight',
        'plan_sha256': ctx['plan_sha256'], 'step_sha256': peer.spec.step_sha256(step),
        'launch_sha256': state['preflight']['launch_sha256'], 'passed': True,
        'budget': deepcopy(state['preflight']['budget']), 'stage': state['preflight'].get('stage'),
        'correction': deepcopy(ctx.get('correction')), 'depends_on': list(step.get('depends_on') or ()),
        'log': str(Path(state['preflight']['output_root']).parent / 'logs' / 'stdout'),
        'capsule': {key: deepcopy(state['preflight']['capsule'][key]) for key in ('argv', 'reads', 'writes', 'cwd')}})
    calls = []
    def popen(spec, **kwargs):
        assert len(confine.gate_calls) == 1 and len(checks) == 2
        assert confine.gate_calls[0]['budget'] == state['reservation']['amounts']
        calls.append((spec, kwargs))
        assert spec['argv'] == ['fictional-native', str(path)]
        assert spec['reads'] == [str(path)] and spec['writes'] == [state['preflight']['output_root']]
        assert spec['limits'] == {'wall_seconds': 7, 'cpus': 1, 'memory_mib': 4}
        return SimpleNamespace(wait=lambda **kw: 0, ravel_backend='bwrap')
    confine.popen = popen
    state['launch'] = peer._launch(state, {})
    assert len(calls) == 1 and len(checks) == 2
    assert len(confine.gate_calls) == 1
    assert checks[0]["pins"] == checks[1]["pins"]
    effect = common.records(store, 'step-authority')[-1]
    assert effect['point'] == point and effect['step_id'] == step['id']
    assert effect['plan_sha256'] == plan['sha256']
    state['observation'] = {'kind': 'launch', 'measured': {}}
    result = peer.finish(state)['outcome']
    assert result['status'] == 'completed' and result['receipts'] == [state['launch']['journal_id']]


@pytest.mark.parametrize('refused', [False, True])
def test_E04_real_peer_uses_governed_acquisition_without_domain_network(tmp_path, monkeypatch, refused):
    from ravel.workflow import resource_census
    store, plan, ctx = _setup(tmp_path)
    blob = store.put_blob(json.dumps(plan).encode())
    store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'revision': plan['revision']})
    step = next(s for s in plan['steps'] if s['id'] == 'inputs.census')
    path = tmp_path / 'inputs/reading.json'; path.parent.mkdir(exist_ok=True); path.write_text('{}')
    inputs = [{'artifact': 'inputs/reading.json', 'path': 'inputs/reading.json', 'sha256': common.file_sha256(path)}]
    state = {'step': step, 'acting': step, 'context': ctx, 'branch': 'launch',
             'reservation': {'amounts': {'wall_seconds': 7}}}
    confine, checks = _services(monkeypatch, store, ctx, step, refused=refused)
    confine.popen = lambda *a, **k: pytest.fail('source acquisition reached a domain network launch')
    source_calls = []
    def acquire(args):
        assert not refused
        assert len(confine.gate_calls) == 1 and len(checks) == 2
        assert len([row for row in common.records(store, 'step-fact')
                    if row['mechanism'] == 'native-launch-decision' and row['passed'] is True]) == 1
        source_calls.append(list(args))
        assert args[1] == str(path)
        target = Path(args[3]); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"records":[],"rungs":{"metadata":{"status":"OK"}}}')
        return 0
    monkeypatch.setattr(resource_census, 'main', acquire)
    state['preflight'] = peer._launch_preflight(state, store, ctx, tmp_path, step, None, [], inputs, {})
    prepared = state['preflight']
    prepared['plan_sha256'] = ctx['plan_sha256']
    prepared['budget'] = deepcopy(state['reservation']['amounts'])
    prepared['native_preflight'] = store.append('step-fact', {
        'step_id': step['id'], 'seat': None, 'attempt': ctx['attempt'], 'mechanism': 'native-launch-preflight',
        'plan_sha256': ctx['plan_sha256'], 'step_sha256': peer.spec.step_sha256(step),
        'launch_sha256': prepared['launch_sha256'], 'passed': True,
        'budget': deepcopy(prepared['budget']), 'stage': prepared.get('stage'),
        'correction': deepcopy(ctx.get('correction')), 'depends_on': list(step.get('depends_on') or ()),
        'log': str(Path(prepared['output_root']).parent / 'logs' / 'stdout'),
        'capsule': {key: deepcopy(prepared['capsule'][key]) for key in ('argv', 'reads', 'writes', 'cwd')}})
    if refused:
        with pytest.raises(peer.LaunchNotStarted) as held:
            peer._launch(state, {})
        assert held.value.reason == 'native_launch_gate_refused' and held.value.not_dispatched
        assert source_calls == [] and common.records(store, 'step-launch') == []
    else:
        found = peer._launch(state, {})
        assert found['exit_status'] == 0 and found['backend'] == 'controller-acquisition' and len(checks) == 2
        assert common.records(store, 'step-launch')[-1]['acquisition']['members']
        assert len(source_calls) == 1
        decision = store.read('step-fact', found['gate_check']['record'])['record']
        assert found['gate_check']['mechanism'] == decision['mechanism'] == 'native-launch-decision'
        assert decision['passed'] is True and decision['action'] == confine.gate_calls[0]
    assert len(checks) == 2 and len(confine.gate_calls) == 1
    pins = {'plan_sha256': ctx['plan_sha256'], 'step_sha256': peer.spec.step_sha256(step),
            'launch_sha256': prepared['launch_sha256'], 'attempt': str(ctx['attempt']),
            'native_preflight': prepared['native_preflight']}
    assert confine.gate_calls[0] == {'kind': 'dry_run', 'step': step['id'], 'node_id': step['id'],
        'rung': step.get('rung'), 'floor': step.get('consequence_class', 'R0'),
        'view_pins': pins, 'digest': common.digest(pins), 'budget': state['reservation']['amounts']}


def test_acquisition_rechecks_withdrawn_authority_before_source_effect(tmp_path, monkeypatch):
    from test_p04_support import AuthorityRefused
    from ravel.controller.routes.analysis import execution
    store, plan, ctx = _setup(tmp_path)
    step = next(s for s in plan['steps'] if s['id'] == 'inputs.census')
    path = tmp_path / 'inputs/reading.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text('{}')
    inputs = [{'artifact': 'inputs/reading.json', 'path': 'inputs/reading.json',
               'sha256': common.file_sha256(path)}]
    state = {'step': step, 'acting': step, 'context': ctx, 'branch': 'launch',
             'reservation': {'amounts': {'wall_seconds': 7}}}
    confine, checks = _services(monkeypatch, store, ctx, step)
    state['preflight'] = peer._launch_preflight(state, store, ctx, tmp_path, step, None, [], inputs, {})
    def withdrawn(*args):
        raise AuthorityRefused('the current authority was withdrawn')
    monkeypatch.setattr(peer.module('authority'), 'authorize_effect', withdrawn)
    monkeypatch.setattr(execution, 'acquire', lambda *a, **k: pytest.fail('withdrawn authority reached a source'))
    confine.popen = lambda *a, **k: pytest.fail('acquisition cannot start a domain process')
    with pytest.raises(peer.LaunchNotStarted) as refused:
        peer._launch(state, {})
    assert refused.value.reason == 'authority_refused'
    assert len(checks) == 1 and common.records(store, 'step-launch') == []
    assert confine.gate_calls == []
