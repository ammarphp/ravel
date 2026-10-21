"""Inert P09 requests at the P04/P05 boundary; no scientific execution is claimed.

The binding-only step service below owns a fictional confinement handoff. It does
not stand in for qualification of the real step service, launcher or native tools.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ravel.controller.routes import analysis
from ravel.controller.routes.analysis import execution, scan
from ravel.controller.ledger import population_equality as _population_equality
from test_p04_support import graphs, run_env, services_installed  # noqa: F401
from p09_support import (Store, adopt_prepare, compile_plan, context, contract,
                              digest, grant, outcome, reading)


DATA = Path(__file__).resolve().parents[3] / 'src/ravel/data'


def _governed_launch_setup(env, monkeypatch):
    from ravel.controller import routes
    from ravel.controller.step.services import module
    from test_p04_support import context as step_context
    monkeypatch.setattr(module('ledger'), 'population_equality', _population_equality, raising=False)
    read, con = reading(), contract()
    from p09_support import route_analysis
    route = routes.find('analysis')
    plan = routes.compile(route, read, con, parameters=analysis.parameters(
        route, read, con, route_analysis=route_analysis()))
    states = adopt_prepare(env.store, env.run_dir, plan)
    blob = env.store.put_blob(json.dumps(plan, sort_keys=True).encode())
    env.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'revision': plan['revision']})
    # The fake operator commits the same declared inputs and installed materializer as production.
    reading_path = env.run_dir / 'inputs/reading.json'
    reading_path.write_text(json.dumps(read, sort_keys=True))
    from ravel.controller.confine import commitments
    commitments.create(env.store, plan, env.run_dir)
    return plan, _step(plan, 'recast.smoke'), step_context(
        env.store, env.run_dir, plan['sha256'], plan=plan, reading=read, contract=con,
        state={'steps': states})


def _inert_materializer(monkeypatch, seen):
    def materialize(step, ctx):
        assert ctx['store'].run_id == ctx['run_id']
        assert ctx['plan_sha256'] == ctx['plan']['sha256']
        scope = {'step_id': step['id'], 'operation': step['operation'], 'role': step['role'],
                 'plan_sha256': ctx['plan_sha256'], 'rung': step['rung'],
                 'reading_sha256': digest(ctx['reading']), 'contract_sha256': digest(ctx['contract']),
                 'point': None, 'coordinates': {}, 'grid_sha256': None,
                 'task_sha256': digest(step['parameters']['task']), 'outputs': deepcopy(step['outputs'])}
        seen.append((deepcopy(step), scope))
        return {'argv': ['/bin/true', '@input:' + step['inputs'][0]['artifact']],
                'env': {}, 'reads': [], 'stage': 'analyze', 'scope': scope}
    monkeypatch.setattr(analysis, 'materialize_launch', materialize, raising=False)


def test_first_dispatch_of_the_analysis_route_is_a_governed_launch(run_env, graphs, monkeypatch):
    from ravel.controller import step as governed
    from ravel.controller.step import spec
    plan, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    original = deepcopy(plan)
    seen = []
    _inert_materializer(monkeypatch, seen)
    assert spec.branch(step) == 'launch'
    result = governed.run(run_env.store, step, ctx)
    assert len(seen) == 1, result
    confine = run_env.fakes['confine']
    assert len(confine.probes) == len(confine.launched) == 1, result
    capsule = confine.launched[0]
    source = run_env.run_dir / 'steps/inputs.route/outputs/route_analysis.json'
    sweep = run_env.run_dir / 'steps/inputs.traps/outputs/trap_sweep.json'
    output = run_env.run_dir / 'steps/recast.smoke/attempts/1/outputs'
    assert capsule['argv'] == ['/bin/true', str(source)]
    assert capsule['reads'] == [str(source), str(sweep)] and capsule['writes'] == [str(output)]
    assert capsule['env'] == {} and capsule['cwd'] == str(output)
    assert capsule['input_digests'] == {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                      for path in (source, sweep)}
    assert capsule['controller']['scope'] == seen[0][1]
    effects = [row[1] for row in run_env.fakes['authority'].calls if row[0] == 'authorize_effect']
    assert len(effects) == 3 and all(row['stage'] == 'analyze' for row in effects)
    assert all(row['pins']['plan_sha256'] == plan['sha256'] for row in effects)
    identity = {'id': step['id'], 'pins': {'plan_sha256': plan['sha256']},
                'rung': step['rung'], 'plan': step['rung'], 'stage': 'analyze', 'budget': effects[0]['budget']}
    assert all({key: effect[key] for key in identity} == identity for effect in effects)
    timestamps = [effect['started_ns'] for effect in effects]
    assert all(type(value) is int and value > 0 for value in timestamps)
    assert all(before < after for before, after in zip(timestamps, timestamps[1:]))
    launches = run_env.store.records('step-launch')
    assert len([row for row in launches if row['phase'] == 'started']) == 1
    assert launches[0]['scope'] == seen[0][1]
    assert launches[0]['argv_sha256'] == digest(capsule['argv'])
    assert launches[-1]['exit_status'] == 0
    assert not run_env.store.records('step-dispatch')
    # The inert command produces no science outputs; the ordinary output check still refuses it.
    assert result['status'] == 'failed' and result['outputs'] == []
    assert plan == original and seen[0][0] == step and spec.launch(step) is None


@pytest.mark.parametrize('materializer', ['absent', 'empty', 'invalid', 'refused'])
def test_operation_without_a_materialised_launch_holds(run_env, graphs, monkeypatch, materializer):
    from ravel.controller import step as governed
    from ravel.controller.step.services import StepHold
    _, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    if materializer == 'absent':
        monkeypatch.delattr(analysis, 'materialize_launch', raising=False)
    else:
        def derive(*args):
            if materializer == 'refused':
                raise StepHold('launch_unmaterialised', 'a prepared executor input is required')
            return None if materializer == 'empty' else {'argv': []}
        monkeypatch.setattr(analysis, 'materialize_launch', derive, raising=False)
    result = governed.run(run_env.store, step, ctx)
    assert (result['status'], result['reason']) == ('held', 'launch_unmaterialised'), result
    assert not run_env.fakes['confine'].launched and not run_env.store.records('step-dispatch')
    assert not run_env.store.records('step-launch')


def test_materialised_launch_rechecks_authority_before_popen(run_env, graphs, monkeypatch):
    from ravel.controller import step as governed
    from test_p04_support import AuthorityRefused
    _, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    _inert_materializer(monkeypatch, [])
    authority = run_env.fakes['authority']
    original = authority.authorize_effect
    effects = []

    def authorize(store, effect):
        effects.append(deepcopy(effect))
        if len(effects) == 3:
            raise AuthorityRefused('the authorization was withdrawn after the probe')
        return original(store, effect)
    from ravel.controller.step.services import module
    monkeypatch.setattr(module('authority'), 'authorize_effect', authorize)
    result = governed.run(run_env.store, step, ctx)
    assert (result['status'], result['reason']) == ('held', 'authority_refused'), result
    assert len(effects) == 3 and all(row['stage'] == 'analyze' for row in effects)
    assert not run_env.fakes['confine'].launched and not run_env.store.records('step-dispatch')


def test_materialised_launch_gate_rechecks_authority_before_immediate_effect_boundary(run_env, graphs, monkeypatch):
    from ravel.controller import step as governed
    from test_p04_support import AuthorityRefused
    _, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    _inert_materializer(monkeypatch, [])
    authority = run_env.fakes['authority']
    original = authority.authorize_effect
    effects = []

    def authorize(store, effect):
        effects.append(deepcopy(effect))
        if len(effects) == 2:
            raise AuthorityRefused('the authorization was withdrawn at the mandatory native gate')
        return original(store, effect)
    from ravel.controller.step.services import module
    monkeypatch.setattr(module('authority'), 'authorize_effect', authorize)
    result = governed.run(run_env.store, step, ctx)
    assert (result['status'], result['reason']) == ('held', 'native_authority_refused'), result
    assert len(effects) == 2 and all(row['stage'] == 'analyze' for row in effects)
    assert not run_env.fakes['confine'].launched and not run_env.store.records('step-dispatch')
    assert not run_env.store.records('step-launch')


@pytest.mark.parametrize('reason', ['launch_request_changed', 'launch_input_invalid'])
def test_materializer_request_and_custody_refusals_hold_before_launch(run_env, graphs, monkeypatch, reason):
    from ravel.controller import step as governed
    from ravel.controller.step.services import StepHold
    _, step, ctx = _governed_launch_setup(run_env, monkeypatch)

    def materialize(*args):
        raise StepHold(reason, 'the retained request or declared input no longer matches')
    monkeypatch.setattr(analysis, 'materialize_launch', materialize, raising=False)
    result = governed.run(run_env.store, step, ctx)
    assert (result['status'], result['reason']) == ('held', reason), result
    assert not run_env.fakes['confine'].probes and not run_env.fakes['confine'].launched
    assert not run_env.store.records('step-dispatch') and not run_env.store.records('step-launch')


@pytest.mark.parametrize('fault', ['undeclared-input', 'extra-reads'])
def test_materialised_launch_reads_only_the_verified_input_census(run_env, graphs, monkeypatch, fault):
    from ravel.controller import step as governed
    _, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    _inert_materializer(monkeypatch, [])
    materialize = analysis.materialize_launch

    def unsafe(*args):
        launch = materialize(*args)
        if fault == 'undeclared-input':
            launch['argv'][1] = '@input:inputs/undeclared.json'
        else:
            launch['reads'] = [str(run_env.run_dir)]
        return launch
    monkeypatch.setattr(analysis, 'materialize_launch', unsafe)
    result = governed.run(run_env.store, step, ctx)
    assert (result['status'], result['reason']) == ('held', 'launch_input_invalid'), result
    assert not run_env.fakes['confine'].probes and not run_env.fakes['confine'].launched
    assert not run_env.store.records('step-dispatch') and not run_env.store.records('step-launch')


def test_explicit_approved_launch_keeps_its_governed_path(run_env, graphs, monkeypatch):
    from ravel.controller import step as governed
    plan, step, ctx = _governed_launch_setup(run_env, monkeypatch)
    step['parameters']['launch'] = {'argv': ['/bin/true'], 'stage': 'analyze'}
    _pin(plan)
    blob = run_env.store.put_blob(json.dumps(plan, sort_keys=True).encode())
    run_env.store.append('plan', {'plan_sha256': plan['sha256'], 'blob': blob, 'revision': plan['revision']})
    ctx['plan_sha256'] = plan['sha256']
    from ravel.controller.confine import commitments
    commitments.create(run_env.store, plan, run_env.run_dir)
    monkeypatch.setattr(analysis, 'materialize_launch', lambda *a: pytest.fail('explicit launch replaced'), raising=False)
    result = governed.run(run_env.store, step, ctx)
    assert len(run_env.fakes['confine'].launched) == 1, result
    assert run_env.fakes['confine'].launched[0]['argv'] == ['/bin/true']
    assert run_env.store.records('step-launch')[-1]['exit_status'] == 0


@pytest.mark.parametrize('approved', [False, True])
def test_explicit_operation_launch_obeys_current_mode_authority(run_env, graphs, approved):
    from ravel.controller import graph as controller, step as governed
    from test_p04_support import context as step_context, install_plan
    from test_p12_modes import inference_plan
    plan, step = inference_plan()
    step['depends_on'] = []
    step['budget'] = {'wall_seconds': 60, 'events': 0}
    step['parameters'] = {'launch': {'argv': ['/bin/true']}}
    plan['steps'] = [step]
    plan['deliverables'][0].update(step=step['id'], output=step['outputs'][0]['path'])
    install_plan(run_env.store, [step])
    stored = run_env.store.records('plan')[-1]
    _pin(plan)
    pin = stored['plan_sha256'] = plan['sha256']
    stored['blob'] = run_env.store.put_blob(json.dumps(plan).encode())
    run_env.store.append('plan', stored)
    from ravel.controller.confine import commitments
    commitments.create(run_env.store, plan, run_env.run_dir)
    asked = []

    def chain(store, pins):
        asked.append((store, pins))
        return ({'id': 'approval', 'subject': {'pins': {'plan_sha256': 'old'}}},
                {'id': 'amendment', 'subject': {'pins': pins}}) if approved else (None, None)
    authority = SimpleNamespace(plan_authority=chain, current=lambda *a, **k: None)
    with controller.services(authority=authority):
        result = governed.run(run_env.store, step, step_context(run_env.store, run_env.run_dir, pin))
    assert asked and asked[0][1] == {'plan_sha256': pin}, result
    if approved:
        assert result['reason'] != 'mode_authority_missing', result
        assert run_env.store.records('step-launch') and run_env.fakes['confine'].launched
    else:
        assert (result['status'], result['reason']) == ('held', 'mode_authority_missing'), result
        assert not run_env.store.records('step-launch') and not run_env.fakes['confine'].launched


def _setup(tmp_path, *, scan_mode=False, prepare=True):
    store = Store(root=tmp_path / 'store')
    read, con = reading(scan=scan_mode), contract('scan' if scan_mode else 'reproduce')
    plan = compile_plan('analysis.scan' if scan_mode else 'analysis', read, con)
    states = adopt_prepare(store, tmp_path, plan, cost_mode='scan' if scan_mode else 'full') if prepare else {}
    plan = analysis.bind(plan, context(store, tmp_path, plan, read, con, states)) or plan
    return store, plan, context(store, tmp_path, plan, read, con, states)


def _step(plan, name):
    return next(s for s in plan['steps'] if s['id'] == name or
                (name == 'scan.point' and s['id'].startswith('scan.point.')))


def _pin(plan):
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})


def _service(monkeypatch, run):
    import ravel.controller as controller
    module = ModuleType('ravel.controller.step')
    module.run = run
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(controller, 'step', module, raising=False)


@pytest.mark.parametrize('step_id', ['inputs.census', 'acquire.data'])
def test_R07_P04_approved_acquisition_request_preserves_task_and_outputs(tmp_path, monkeypatch, step_id):
    store, plan, ctx = _setup(tmp_path)
    grant(store, 'approve_plan', plan=plan)
    step = _step(plan, step_id)
    seen = []

    def run(actual_store, actual_step, actual_context):
        seen.append((actual_store, actual_step, actual_context))
        return outcome(actual_step)

    _service(monkeypatch, run)
    result = execution.dispatch(store, step, ctx)
    actual_store, actual_step, forwarded = seen.pop()
    assert actual_store is store and actual_step == step and actual_step is not step
    request = forwarded['operation_request']
    assert request['acquisition'] is True
    assert request['operation'] == step['operation']
    assert request['role'] == step.get('role')
    assert request['task'] == step['parameters'].get('task', {})
    assert request['inputs'] == step['inputs']
    assert request['plan_sha256'] == plan['sha256']
    assert request['point'] is None and 'store' not in forwarded
    assert result['outputs'] == outcome(step)['outputs']


def _launch_input(tmp_path, step):
    path = tmp_path / 'verified/input.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"fictional": true}\n')
    artifact = 'fictional:outputs/input.json'
    step['inputs'] = [{'artifact': artifact, 'required': True}]
    step['budget'] = {**step.get('budget', {}), 'wall_seconds': 7}
    step['parameters']['launch'] = {'argv': ['fictional-native', '--input', '@input:' + artifact,
                                           '--output', 'result.json'],
                                     'memory_mib': 4}
    return [{'artifact': artifact, 'destination': 'verified/input.json',
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]


@pytest.mark.parametrize('scan_mode', [False, True], ids=['full', 'scan'])
def test_P04_E22_E23_native_request_keeps_singleton_and_verified_launch(tmp_path, monkeypatch, scan_mode):
    store, plan, ctx = _setup(tmp_path, scan_mode=scan_mode)
    step = _step(plan, 'scan.point' if scan_mode else 'run.full')
    inputs = _launch_input(tmp_path, step)
    _pin(plan)
    grant(store, 'approve_plan', plan=plan)
    grant(store, 'go', decision='go', plan=plan)
    output = tmp_path / 'attempt/outputs'
    output.mkdir(parents=True)
    calls = []
    fake_confine = SimpleNamespace(
        backends=lambda: {'bwrap': 'available'},
        probe=lambda kind, target: {'backend': kind, 'target': str(target), 'confirmed': True})

    def popen(spec, **kwargs):
        calls.append((deepcopy(spec), kwargs))
        return SimpleNamespace(returncode=0)

    fake_confine.popen = popen
    received = []

    def run(actual_store, actual_step, forwarded):
        assert actual_store is store
        received.append(forwarded)
        assert fake_confine.backends() == {'bwrap': 'available'}
        assert fake_confine.probe('bwrap', output) == {
            'backend': 'bwrap', 'target': str(output), 'confirmed': True}
        launch = execution.resolve_launch(actual_step, forwarded, output_root=output, inputs=inputs)
        spec = {'argv': launch['argv'], 'env': launch.get('env', {}),
                'reads': launch['reads'], 'writes': [str(output.resolve())],
                'limits': {'wall_seconds': actual_step['budget']['wall_seconds'],
                           'memory_mib': launch['memory_mib']}, 'backend': 'bwrap'}
        fake_confine.popen(spec, cwd=launch['cwd'])
        return outcome(actual_step)

    _service(monkeypatch, run)
    result = execution.dispatch(store, step, ctx)
    assert len(received) == len(calls) == 1
    request = received[0]['operation_request']
    point, coordinates = scan.point_of(step)
    assert request['operation'] == step['operation'] and request['task'] == step['parameters']['task']
    assert request['point'] == point and request['coordinates'] == coordinates
    if scan_mode:
        assert step['points'] == [point] and received[0]['point'] == point
        assert request['grid_sha256'] == step['parameters']['grid_sha256']
    spec, kwargs = calls[0]
    assert spec['argv'] == ['fictional-native', '--input', str(tmp_path / 'verified/input.json'),
                            '--output', 'result.json']
    assert spec['reads'] == [str(tmp_path / 'verified/input.json')]
    assert spec['writes'] == [str(output.resolve())] and spec['env'] == {}
    assert spec['backend'] == 'bwrap' and kwargs == {'cwd': str(output.resolve())}
    assert spec['limits'] == {'wall_seconds': 7, 'memory_mib': 4}
    assert result['outputs'] == outcome(step)['outputs']


@pytest.mark.parametrize('prepare', [False, True], ids=['inputs-absent', 'checkin1-absent'])
def test_R07_dispatch_refused_before_step_or_fake_popen(tmp_path, monkeypatch, prepare):
    store, plan, ctx = _setup(tmp_path, prepare=prepare)
    _service(monkeypatch, lambda *a: pytest.fail('step service reached before R07 evidence'))
    result = execution.dispatch(store, _step(plan, 'recast.smoke'), ctx)
    assert result['status'] == 'held' and result['outputs'] == []
    assert 'CHECK-IN 1' in result['reason']


@pytest.mark.parametrize('scan_mode', [False, True], ids=['full', 'scan'])
def test_A08_full_and_scan_refused_before_CI2_and_fake_popen(tmp_path, monkeypatch, scan_mode):
    store, plan, ctx = _setup(tmp_path, scan_mode=scan_mode)
    grant(store, 'approve_plan', plan=plan)
    step = _step(plan, 'scan.point' if scan_mode else 'run.full')
    _service(monkeypatch, lambda *a: pytest.fail('step service reached before CI2 GO'))
    result = execution.dispatch(store, step, ctx)
    assert result['status'] == 'held' and result['outputs'] == []
    assert 'CHECK-IN 2' in result['reason']


@pytest.mark.parametrize('mode', ['formula-grid', 'llp-plane-recipe', 'sfitter-scan-extraction'],
                         ids=['MODE-formula-grid', 'MODE-llp-plane-recipe', 'MODE-sfitter-scan-extraction'])
def test_MODE_registered_operation_task_and_outputs_reach_binding_service(tmp_path, monkeypatch, mode):
    signatures = json.loads((DATA / 'operation_signatures.json').read_text())['operations']
    executors = json.loads((DATA / 'roles/executors.json').read_text())['operations']
    assert signatures[mode]['implementation']['mode'] == mode
    store, plan, ctx = _setup(tmp_path)
    step = _step(plan, 'run.full')
    step['operation'], step['role'] = mode, executors[mode]
    from p09_support import adopt, evidence_set
    inventory = evidence_set()['env']['outputs/environment.json']
    inventory['operations'].append(mode)
    adopt(store, tmp_path, 'env', 'outputs/environment.json', inventory)
    step['outputs'] = [{'path': f'outputs/fictional-{index}.json', 'kind': row['kind'],
                        'required': True}
                       for index, row in enumerate(signatures[mode]['produces'])]
    step['parameters']['task'] = {'mode': mode, 'input': 'fictional-declared-input.json',
                                'output': 'outputs/fictional-result.json'}
    _pin(plan)
    grant(store, 'approve_plan', plan=plan)
    grant(store, 'go', decision='go', plan=plan)
    received = []

    def run(actual_store, actual_step, forwarded):
        received.append((actual_store, actual_step, forwarded))
        return outcome(actual_step)

    _service(monkeypatch, run)
    result = execution.dispatch(store, step, ctx)
    assert len(received) == 1
    actual_store, actual_step, forwarded = received[0]
    assert actual_store is store
    assert actual_step['operation'] == mode and actual_step['role'] == executors[mode]
    assert [row['kind'] for row in actual_step['outputs']] == [
        row['kind'] for row in signatures[mode]['produces']]
    assert forwarded['operation_request']['task'] == step['parameters']['task']
    assert forwarded['operation_request']['operation'] == mode
    assert forwarded['operation_request']['plan_sha256'] == plan['sha256']
    assert result['outputs'] == outcome(step)['outputs']


@pytest.mark.parametrize('fault', ['undeclared', 'tampered', 'symlink', 'extra-reads'])
def test_P04_verified_input_tokens_refuse_unsafe_census(tmp_path, fault):
    store, plan, ctx = _setup(tmp_path)
    step = deepcopy(_step(plan, 'run.full'))
    inputs = _launch_input(tmp_path, step)
    path = tmp_path / 'verified/input.json'
    if fault == 'undeclared':
        step['parameters']['launch']['argv'][2] = '@input:unlisted:outputs/input.json'
    elif fault == 'tampered':
        path.write_bytes(b'changed')
    elif fault == 'symlink':
        original = tmp_path / 'original.json'
        path.rename(original)
        path.symlink_to(original)
    else:
        step['parameters']['launch']['reads'] = [str(tmp_path)]
    with pytest.raises(ValueError):
        execution.resolve_launch(step, ctx, output_root=tmp_path / 'outputs', inputs=inputs)


@pytest.mark.parametrize('fault', ['point-context', 'plan-context', 'point-population'])
def test_P04_E22_E23_request_refuses_another_point_or_plan(tmp_path, fault):
    store, plan, ctx = _setup(tmp_path, scan_mode=True)
    step = deepcopy(_step(plan, 'scan.point'))
    if fault == 'point-context':
        ctx['point'] = 'other-point'
    elif fault == 'plan-context':
        ctx['plan_sha256'] = '0' * 64
    else:
        step['points'] = [scan.point_of(step)[0], 'other-point']
    with pytest.raises(ValueError):
        execution.request(step, ctx)


def _acquisition_source_inputs(store, step):
    declared = {row['artifact'] for row in step['inputs']}
    return [row['record'] for row in store.scan('custody')
            if row['record'].get('artifact') in declared and row['record'].get('status') == 'accepted']


@pytest.mark.parametrize('step_id', ['inputs.census', 'acquire.data'])
def test_E04_governed_acquisition_preserves_complete_adoptable_source(tmp_path, monkeypatch, step_id):
    from ravel.workflow import resource_census
    store, plan, ctx = _setup(tmp_path)
    step = _step(plan, step_id)
    read_path = tmp_path / 'inputs/reading.json'
    read_path.parent.mkdir(parents=True, exist_ok=True)
    read_path.write_text(json.dumps(ctx['reading']))
    inputs = [{'artifact': 'inputs/reading.json', 'path': 'inputs/reading.json',
               'sha256': hashlib.sha256(read_path.read_bytes()).hexdigest()}]
    output = tmp_path / 'attempt/outputs'
    seen = []

    def acquire(args):
        seen.append(args)
        if step_id == 'inputs.census':
            assert args[:2] == ['--reading', str(read_path)]
            target = Path(args[3]); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'rungs': {'metadata': {'status': 'OK'}},
                                          'records': [{'rungs': {'metadata': {'status': 'OK'}}}]}))
        else:
            assert args[0] == '--fetch-published-data'
            folder = Path(args[4]); folder.mkdir(parents=True)
            (folder / 'hepdata_manifest.json').write_text(json.dumps({'tables': ['table.json']}))
            (folder / 'table.json').write_bytes(b'{"values":[1,2]}')
        return 0

    monkeypatch.setattr(resource_census, 'main', acquire)
    inputs += _acquisition_source_inputs(store, step)
    result = execution.acquire(step, ctx, output_root=output, inputs=inputs)
    assert result['exit_status'] == 0 and result['bytes'] > 0 and seen
    assert all(row['sha256'] for row in result['members'])
    if step_id == 'acquire.data':
        data = json.loads((output / 'hepdata/hepdata_manifest.json').read_text())
        member, = data['acquired_member_manifest']['members']
        assert member['path'] == 'table.json'
        assert (output / 'hepdata' / member['blob']).read_bytes() == b'{"values":[1,2]}'
        assert member['sha256'] == hashlib.sha256(b'{"values":[1,2]}').hexdigest()


@pytest.mark.parametrize('fault', ['source-restricted', 'exit-failure', 'byte-ceiling'])
def test_E04_acquisition_policy_and_failures_cannot_be_adopted(tmp_path, monkeypatch, fault):
    from ravel.workflow import resource_census, restriction_guard
    store, plan, ctx = _setup(tmp_path)
    step = _step(plan, 'acquire.data')
    inputs = _acquisition_source_inputs(store, step)
    seen = []

    def acquire(args):
        seen.append(args)
        folder = Path(args[4]); folder.mkdir(parents=True)
        (folder / 'hepdata_manifest.json').write_text(json.dumps({'tables': ['t1']}))
        return 2 if fault == 'exit-failure' else 0

    monkeypatch.setattr(resource_census, 'main', acquire)
    if fault == 'source-restricted':
        def refuse(*args, **kwargs):
            raise restriction_guard.SourceRestricted('fictional source restriction')
        monkeypatch.setattr(restriction_guard, 'require', refuse)
        with pytest.raises(restriction_guard.SourceRestricted):
            execution.acquire(step, ctx, output_root=tmp_path / 'outputs', inputs=inputs)
        assert seen == []
    elif fault == 'exit-failure':
        assert execution.acquire(step, ctx, output_root=tmp_path / 'outputs', inputs=inputs)['exit_status'] == 2
    else:
        step['parameters']['task']['max_bytes'] = 1
        with pytest.raises(ValueError, match='byte ceiling'):
            execution.acquire(step, ctx, output_root=tmp_path / 'outputs', inputs=inputs)


def test_A06_C03_plan_critic_must_check_each_route_item_before_credit(tmp_path):
    from ravel.controller.routes.analysis import checkins
    store, plan, ctx = _setup(tmp_path)
    items = checkins.approve_plan(ctx)['review_items']
    critic = {'id': 'plan_review', 'kind': 'review', 'role': 'plan-critic',
              'parameters': {'review_items': items}}
    complete = {'item_verdicts': [{'item': item['id'], 'verdict': 'pass', 'evidence': ['artifact:plan']}
                                 for item in items]}
    assert execution.review_errors(critic, complete) == []
    incomplete = deepcopy(complete); incomplete['item_verdicts'].pop()
    assert any('missing' in e for e in execution.review_errors(critic, incomplete))
    hollow = deepcopy(complete); hollow['item_verdicts'][0]['evidence'] = []
    assert execution.review_errors(critic, hollow)
    for verdict in ('fail', 'unresolved'):
        negative = deepcopy(complete); negative['item_verdicts'][0]['verdict'] = verdict
        assert execution.review_errors(critic, negative)


def test_E22_E23_prepared_native_argv_is_pinned_before_CI1(tmp_path):
    from p09_support import adopt, route_analysis
    store, plan, ctx = _setup(tmp_path, scan_mode=True)
    point = _step(plan, 'scan.point')
    launch = {'argv': ['fictional-native', '--point', point['parameters']['point_id']], 'reads': []}
    source = route_analysis(launches={point['id']: launch})
    adopt(store, tmp_path, 'inputs.route', 'outputs/route_analysis.json', source)
    bound = analysis.bind(plan, ctx)
    assert bound is not None and bound['sha256'] != plan['sha256']
    assert _step(bound, point['id'])['parameters']['launch'] == launch
    assert _step(bound, 'inputs.route') == _step(plan, 'inputs.route')
    assert not _step(plan, point['id'])['parameters'].get('launch')
    with pytest.raises(ValueError, match='unplanned or preparation'):
        execution.bind_launches(plan, {'launches': {'unplanned-point': launch}})
    with pytest.raises(ValueError, match='declared step inputs'):
        execution.bind_launches(plan, {'launches': {point['id']: dict(launch, reads=['/'])}})


MATERIALIZED_OPERATIONS = (
    'lifecycle-routine-recast', 'analysis-lifecycle', 'lifecycle-scan-aggregation', 'figure-comparison')


def _materialization(tmp_path, operation):
    from ravel.controller.step import operations
    store, plan, ctx = _setup(tmp_path, scan_mode=operation == 'lifecycle-scan-aggregation')
    names = {'lifecycle-routine-recast': 'recast.smoke', 'analysis-lifecycle': 'run.full',
             'lifecycle-scan-aggregation': 'scan.assemble', 'figure-comparison': 'visualize.final'}
    step = _step(plan, names[operation])
    source = 'inputs/scan_manifest.json' if operation == 'lifecycle-scan-aggregation' else 'inputs/executor.json'
    path = tmp_path / source
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"synthetic": true}\n')
    step['inputs'] = [{'artifact': source, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                       'required': True}]
    executor = ({'execution_plan': source} if operation in MATERIALIZED_OPERATIONS[:2] else
                {'manifest': source} if operation == 'lifecycle-scan-aggregation' else
                {'action': 'plane', 'specification': source})
    step['parameters']['task']['executor'] = executor
    step['role'] = operations.executors()['operations'][operation]
    plan['reading_sha256'], plan['contract_sha256'] = digest(ctx['reading']), digest(ctx['contract'])
    _pin(plan)
    ctx['plan_sha256'] = plan['sha256']
    return step, ctx, path


@pytest.mark.parametrize('operation', MATERIALIZED_OPERATIONS)
def test_registered_task_materializes_closed_launch_with_custody(tmp_path, monkeypatch, operation):
    from ravel.controller.step import operations, spec
    import subprocess
    step, ctx, path = _materialization(tmp_path, operation)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('materialization started a process'))
    before = deepcopy(step)
    launch = analysis.materialize_launch(step, ctx)
    assert step == before and 'launch' not in step['parameters']
    assert spec.branch(step) == 'launch'
    policy = operations.ANALYSIS_LAUNCHES[operation]
    assert launch['argv'][:len(policy['argv'])] == list(policy['argv'])
    assert '@input:' + step['inputs'][0]['artifact'] in launch['argv']
    assert launch['stage'] == policy['stage'] and launch['env'] == {} and launch['reads'] == []
    assert launch['scope']['operation'] == operation and launch['scope']['step_id'] == step['id']
    assert launch['scope']['plan_sha256'] == ctx['plan']['sha256']
    assert launch['scope']['reading_sha256'] == digest(ctx['reading'])
    assert launch['scope']['contract_sha256'] == digest(ctx['contract'])
    assert launch['input_custody'] == [{'artifact': step['inputs'][0]['artifact'],
                                      'path': str(path.relative_to(tmp_path)),
                                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    materialized = deepcopy(step)
    materialized['parameters']['launch'] = launch
    resolved = execution.resolve_launch(materialized, ctx, output_root=tmp_path / 'attempt/outputs',
                                        inputs=launch['input_custody'])
    assert resolved['reads'] == [str(path)] and str(path) in resolved['argv']


@pytest.mark.parametrize('fault', ['unknown-task', 'unregistered', 'request-pin', 'reading-pin',
                                  'contract-pin', 'role', 'task-changed', 'input-changed', 'symlink'])
def test_materializer_refuses_unbound_operation_before_process(tmp_path, monkeypatch, fault):
    import subprocess
    from ravel.controller.step.services import StepHold
    step, ctx, path = _materialization(tmp_path, 'lifecycle-routine-recast')
    if fault == 'unknown-task':
        step['parameters']['task']['shell'] = 'unregistered-command'
        _pin(ctx['plan']); ctx['plan_sha256'] = ctx['plan']['sha256']
    elif fault == 'unregistered':
        step['operation'] = 'unregistered-operation'
    elif fault == 'request-pin':
        ctx['plan_sha256'] = '0' * 64
    elif fault == 'reading-pin':
        ctx['reading']['constraints'].append({'id': 'changed'})
    elif fault == 'contract-pin':
        ctx['contract']['stat_mode'] = 'changed'
    elif fault == 'role':
        step['role'] = 'inference'
    elif fault == 'task-changed':
        step = deepcopy(step); step['parameters']['task']['analysis'] = 'changed'
    elif fault == 'input-changed':
        path.write_text('changed')
    else:
        other = tmp_path / 'original.json'; path.rename(other); path.symlink_to(other)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('refusal started a process'))
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


def test_materializer_requires_prepared_executor_and_matching_request(tmp_path):
    from ravel.controller.step.services import StepHold
    from p09_support import adopt, route_analysis
    step, ctx, _ = _materialization(tmp_path, 'lifecycle-routine-recast')
    del step['parameters']['task']['executor']
    _pin(ctx['plan']); ctx['plan_sha256'] = ctx['plan']['sha256']
    with pytest.raises(StepHold) as held:
        analysis.materialize_launch(step, ctx)
    assert held.value.reason == 'launch_unmaterialised'
    requested = {'type': 'final_state', 'value': {'final_state': 'different final state'}}
    ctx['reading']['constraints'].append(requested)
    source = route_analysis()
    adopt(ctx['store'], tmp_path, 'inputs.route', 'outputs/route_analysis.json', source)
    from ravel.controller.routes.analysis import evidence
    route = _step(ctx['plan'], 'inputs.route')
    assert 'route_final_state_mismatch' in {e['code'] for e in evidence.route_analysis(route, outcome(route), ctx)}


@pytest.mark.parametrize('field,value', [('argv', ['unregistered']), ('action', 'unregistered')])
def test_materializer_rejects_unknown_lifecycle_executor_fields(tmp_path, field, value):
    from ravel.controller.step.services import StepHold
    step, ctx, _ = _materialization(tmp_path, 'analysis-lifecycle')
    step['parameters']['task']['executor'][field] = value
    _pin(ctx['plan']); ctx['plan_sha256'] = ctx['plan']['sha256']
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


def test_materializer_rejects_unknown_figure_action(tmp_path):
    from ravel.controller.step.services import StepHold
    step, ctx, _ = _materialization(tmp_path, 'figure-comparison')
    step['parameters']['task']['executor']['action'] = 'unregistered'
    _pin(ctx['plan']); ctx['plan_sha256'] = ctx['plan']['sha256']
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


@pytest.mark.parametrize('fault', ['absent', 'module-changed'])
def test_materializer_checks_live_signature_despite_allowlist(tmp_path, monkeypatch, fault):
    from ravel.controller.step import operations
    from ravel.controller.step.services import StepHold
    operation = 'analysis-lifecycle'
    step, ctx, _ = _materialization(tmp_path, operation)
    signatures = deepcopy(operations.signatures())
    if fault == 'absent':
        del signatures[operation]
    else:
        signatures[operation]['implementation']['module'] = 'unregistered.module'
    monkeypatch.setattr(operations, 'signatures', lambda: signatures)
    assert operation in operations.ANALYSIS_LAUNCHES
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


def test_materializer_rejects_symlink_parent_in_predecessor_custody(tmp_path):
    from ravel.controller.step.services import StepHold
    from p09_support import adopt
    step, ctx, _ = _materialization(tmp_path, 'analysis-lifecycle')
    sha = adopt(ctx['store'], tmp_path, 'inputs.route', 'outputs/executor.json', {'synthetic': True})
    artifact = 'inputs.route:outputs/executor.json'
    step['inputs'] = [{'artifact': artifact, 'sha256': sha, 'required': True}]
    step['parameters']['task']['executor'] = {'execution_plan': artifact}
    parent = tmp_path / 'steps/inputs.route/outputs'
    target = parent.with_name('retained-outputs'); parent.rename(target); parent.symlink_to(target)
    _pin(ctx['plan']); ctx['plan_sha256'] = ctx['plan']['sha256']
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


def test_materializer_scan_point_scope_and_context_are_singleton(tmp_path):
    from ravel.controller.step import operations
    from ravel.controller.step.services import StepHold
    store, plan, ctx = _setup(tmp_path, scan_mode=True)
    step = _step(plan, 'scan.point')
    path = tmp_path / 'inputs/executor.json'; path.parent.mkdir(exist_ok=True); path.write_text('{}')
    step['inputs'] = [{'artifact': 'inputs/executor.json', 'required': True,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    step['parameters']['task']['executor'] = {'execution_plan': 'inputs/executor.json'}
    step['role'] = operations.executors()['operations'][step['operation']]
    plan['reading_sha256'], plan['contract_sha256'] = digest(ctx['reading']), digest(ctx['contract'])
    _pin(plan); ctx['plan_sha256'] = plan['sha256']
    point, coordinates = scan.point_of(step)
    scope = analysis.materialize_launch(step, ctx)['scope']
    assert scope['point'] == point and scope['coordinates'] == coordinates
    assert scope['grid_sha256'] == step['parameters']['grid_sha256'] and step['points'] == [point]
    ctx['point'] = 'different-point'
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, ctx)


@pytest.mark.parametrize('pin', ['constraint', 'plan'])
def test_request_matching_rejects_routine_mismatch_and_accepts_exact_request(pin):
    from ravel.controller.routes.analysis import evidence
    document = {'routine': {'id': 'routine-a'}, 'final_state': 'state-a'}
    ctx = {'reading': {'constraints': [{'type': 'final_state', 'value': {'final_state': 'state-a'}}]},
           'plan': {'request_pins': {}}}
    if pin == 'constraint':
        ctx['reading']['constraints'].append({'type': 'routine', 'value': {'routine': 'routine-b'}})
    else:
        ctx['plan']['request_pins']['routine'] = 'routine-b'
    assert 'route_routine_mismatch' in {e['code'] for e in evidence.request_match_errors(document, ctx)}
    document['routine']['id'] = 'routine-b'
    assert evidence.request_match_errors(document, ctx) == []


def test_assembly_frontend_forwards_verified_manifest_parent_and_output(tmp_path, monkeypatch):
    from ravel.controller.routes.analysis import evidence
    from ravel.workflow import scan_orchestrator
    manifest = tmp_path / 'scan_manifest.json'; manifest.write_text('{}')
    seen = []
    monkeypatch.setattr(scan_orchestrator, 'cmd_assemble', lambda args: seen.append(args))
    assert evidence.main(['assemble', '--manifest', str(manifest), '--out', 'assembled.json']) == 0
    args, = seen
    assert args.scandir == str(tmp_path.resolve()) and args.out == 'assembled.json'
    assert args.normalization_contract is None



def test_materializer_reads_pinned_context_from_store_for_step_caller(tmp_path, monkeypatch):
    step, ctx, _ = _materialization(tmp_path, 'analysis-lifecycle')
    blobs = {digest(document): json.dumps(document, sort_keys=True, separators=(',', ':')).encode()
             for document in (ctx['reading'], ctx['contract'])}
    blobs['plan-blob'] = json.dumps(ctx['plan']).encode()
    ctx['store'].append('plan', {'plan_sha256': ctx['plan']['sha256'], 'blob': 'plan-blob'})
    monkeypatch.setattr(ctx['store'], 'get_blob', lambda pin: blobs[pin], raising=False)
    minimal = {key: ctx[key] for key in ('store', 'run_dir', 'plan_sha256')}
    assert analysis.materialize_launch(step, minimal) == analysis.materialize_launch(step, ctx)
    blobs[ctx['plan']['reading_sha256']] = b'{"changed": true}'
    from ravel.controller.step.services import StepHold
    with pytest.raises(StepHold):
        analysis.materialize_launch(step, minimal)


def test_acquisition_consumer_identity_survives_source_binding(tmp_path):
    store = Store(root=tmp_path / 'store')
    read, con = reading(), contract()
    original = compile_plan('analysis', read, con)
    ctx = context(store, tmp_path, original, read, con, adopt_prepare(store, tmp_path, original))
    bound = analysis.bind(original, ctx)
    assert bound is not None
    assert _step(original, 'acquire.data') == _step(bound, 'acquire.data')
    assert _step(bound, 'acquire.data')['parameters']['launch']['argv'][4:6] == [
        '--record-source', '@input:inputs.route:outputs/route_analysis.json']


@pytest.mark.parametrize('record', [None, '', {}, [], True, '-unexpected', 'record with spaces'])
def test_acquisition_record_source_requires_an_identifier(tmp_path, monkeypatch, record):
    from ravel.workflow import resource_census
    store, plan, ctx = _setup(tmp_path)
    step = _step(plan, 'acquire.data')
    inputs = _acquisition_source_inputs(store, step)
    row = next(r for r in inputs if r['artifact'] == 'inputs.route:outputs/route_analysis.json')
    path = tmp_path / row['destination']
    data = json.loads(path.read_text()); data['hepdata_record'] = record
    path.write_text(json.dumps(data)); row['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(resource_census, 'main', lambda _: pytest.fail('invalid identifier reached source reader'))
    with pytest.raises(ValueError, match='publication record identifier'):
        execution.acquire(step, ctx, output_root=tmp_path / 'attempt/outputs', inputs=inputs)
