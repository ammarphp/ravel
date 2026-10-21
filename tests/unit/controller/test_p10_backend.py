"""Read source-pinned handles without performing any backend operation."""
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from ravel.controller.routes.study import backend
from ravel.workflow import execution, execution_backend as source


class Store:
    run_id = 'inert-bridge'

    def __init__(self, root):
        self.root = root
        self.rows = []

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def scan(self, kind):
        return deepcopy([r for r in self.rows if r['kind'] == kind])

    def append(self, kind, record):
        identifier = str(len(self.rows) + 1)
        self.rows.append({'id': identifier, 'kind': kind, 'record': deepcopy(record)})
        return identifier


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = Store(tmp_path / 'protected')
    root = tmp_path / 'run'
    rd = root / 'children' / 'ordinary'
    (rd / 'inputs').mkdir(parents=True)
    stage, attempt_id = 'calculate', 'attempt-001'
    spec = {'schema_version': 1, 'backend': 'native', 'stage': stage, 'argv': [sys.executable, '-c', 'raise SystemExit(99)'],
            'outputs': [{'name': 'result.json', 'destination': 'outputs/result.json'}],
            'resources': {'cpus': 1, 'memory_mib': 16, 'wall_seconds': 1}}
    plan = source.prepare(spec, base=rd)
    path = rd / 'inputs' / 'backend-plan.json'
    path.write_text(json.dumps(plan, sort_keys=True))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    record = {'attempt_id': attempt_id, 'status': 'running',
              'input_snapshot': {str(path): {'kind': 'file', 'files': [{'sha256': sha}]}}}
    (rd / execution.STATE_NAME).write_text(json.dumps({'schema_version': execution.VERSION,
                                                    'revision': 1, 'stages': {stage: record}}))
    attempt = source.attempt_backend_dir(rd, stage, attempt_id)
    attempt.mkdir(parents=True)
    handle = {'attempt_dir': str(attempt), 'plan_sha256': plan['plan_sha256'],
              'plan_file_sha256': sha, 'backend': plan['backend']['kind'],
              'tag': source.handle_tag(plan, attempt), 'remote': 'inert-recorded-remote'}
    (attempt / source.HANDLE_NAME).write_text(json.dumps(handle))
    store.append('study-site', {'event': 'reserved', 'launch_id': 'launch-a', 'run_dir': str(root)})
    # Any accidental effects fail immediately; parsing, pinning and reading are real.
    def forbidden(*args, **kwargs):
        pytest.fail('source bridge must never perform backend effects')
    for name in ['submit', 'recover', 'fetch']:
        monkeypatch.setattr(source, name, forbidden)
    return store, rd, stage, path, attempt, handle


def call(env):
    store, rd, stage, path, *_ = env
    return backend.track(store, 'launch-a', rundir=rd, stage=stage, plan_path=path)


def test_source_backend_handle_is_tracked_only_from_pinned_stage_attempt(env):
    store, rd, stage, path, attempt, handle = env
    binding = call(env)
    assert binding['rundir'] == str(rd) and binding['stage'] == stage
    assert binding['attempt_id'] == 'attempt-001'
    assert binding['plan_file_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert store.scan('study-remote')[0]['record']['handle'] == handle
    assert call(env) == binding
    assert len(store.scan('study-remote')) == len(store.scan('study-backend-binding')) == 1


def test_changed_pinned_plan_bytes_refused(env):
    env[3].write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        call(env)
    assert env[0].scan('study-remote') == []


@pytest.mark.parametrize('field,value', [('remote', None), ('tag', 'forged'), ('backend', 'forged'),
    ('plan_file_sha256', 'f' * 64), ('plan_sha256', 'f' * 64), ('attempt_dir', '/forged/attempt')])
def test_forged_source_handle_fields_refused(env, field, value):
    store, _, _, _, attempt, handle = env
    (attempt / source.HANDLE_NAME).write_text(json.dumps({**handle, field: value}))
    with pytest.raises(ValueError, match='pinned source attempt'):
        call(env)
    assert store.scan('study-remote') == []


def test_wrong_current_attempt_is_not_replaced_by_older_handle(env):
    store, rd, stage, _, *_ = env
    state = json.loads((rd / execution.STATE_NAME).read_text())
    state['stages'][stage]['attempt_id'] = 'attempt-002'
    (rd / execution.STATE_NAME).write_text(json.dumps(state))
    with pytest.raises(ValueError, match='no ordinary backend handle'):
        call(env)
    assert store.scan('study-remote') == []


def test_wrong_stage_and_unreserved_launch_refused(env):
    store, rd, _, path, *_ = env
    with pytest.raises(ValueError, match='current attempt'):
        backend.track(store, 'launch-a', rundir=rd, stage='another-stage', plan_path=path)
    with pytest.raises(ValueError, match='reserved'):
        backend.track(store, 'unreserved', rundir=rd, stage='calculate', plan_path=path)
    assert store.scan('study-remote') == []


def test_symlink_and_root_escape_refused(env):
    store, rd, stage, path, *_ = env
    linked = rd / 'inputs/linked.json'
    linked.symlink_to(path)
    with pytest.raises(ValueError, match='links'):
        backend.track(store, 'launch-a', rundir=rd, stage=stage, plan_path=linked)
    with pytest.raises(ValueError, match='escapes'):
        backend.track(store, 'launch-a', rundir=rd.parent.parent.parent, stage=stage, plan_path=path)
    with pytest.raises(ValueError, match='without links'):
        backend.track(store, 'launch-a', rundir=rd / '..', stage=stage, plan_path=path)
    assert store.scan('study-remote') == []



def fetched_source(env):
    store, rd, stage, path, attempt, handle = env
    output = rd / 'outputs/result.json'
    output.parent.mkdir(parents=True)
    output.write_text('{"value":61,"units":"GeV"}')
    plan = source.load_plan_bytes(path.read_bytes())
    fact = source.identity(output)
    receipt = {'kind': 'ravel-backend-fetch-receipt', 'plan_sha256': plan['plan_sha256'],
               'backend': handle['backend'], 'remote': handle['remote'], 'tag': handle['tag'],
               'outputs': [{'name': 'result.json', 'destination': str(output),
                            **{k: fact[k] for k in ('kind', 'sha256', 'size')}}],
               'remote_outputs': [], 'quantities': {'literal': 61}}
    handle['state'] = 'fetched'
    (attempt / source.HANDLE_NAME).write_text(json.dumps(handle))
    (attempt / source.RECEIPT_NAME).write_text(json.dumps(receipt))
    return output, receipt


def test_source_fetched_receipt_is_adopted_and_reconciled_without_backend_effects(env):
    from ravel.controller.routes.study import site
    output, receipt = fetched_source(env)
    store, rd, *_ = env
    call(env)
    assert site.adopt(store, 'launch-a', base=rd) == receipt
    assert call(env)['rundir'] == str(rd)
    assert len(store.scan('study-adoption')) == 1
    assert site.reconcile(store, drain=True)['resolved'] is True
    output.write_text('drift')
    result = site.reconcile(store, drain=True)
    assert result['resolved'] is False
    assert result['attempts'][0]['error_type'] == 'ValueError'


@pytest.mark.parametrize('change', ['receipt', 'output'])
def test_source_fetched_drift_refuses_adoption(env, change):
    output, receipt = fetched_source(env)
    store, _, _, _, attempt, _ = env
    if change == 'receipt':
        receipt['remote'] = 'forged-remote'
        (attempt / source.RECEIPT_NAME).write_text(json.dumps(receipt))
    else:
        output.write_text('mutated')
    with pytest.raises(ValueError, match='receipt|pin changed'):
        call(env)
    assert store.scan('study-adoption') == []


def test_current_record_cannot_use_plan_for_a_different_stage(env):
    store, rd, stage, path, *_ = env
    state = json.loads((rd / execution.STATE_NAME).read_text())
    state['stages']['other-stage'] = deepcopy(state['stages'][stage])
    (rd / execution.STATE_NAME).write_text(json.dumps(state))
    with pytest.raises(ValueError, match='different stage'):
        backend.track(store, 'launch-a', rundir=rd, stage='other-stage', plan_path=path)
    assert store.scan('study-remote') == []


def test_source_fetched_child_binding_cannot_escape_parent_on_restart(env):
    from ravel.controller.routes.study import site
    fetched_source(env)
    store, rd, *_ = env
    call(env)
    binding = next(r for r in store.rows if r['kind'] == 'study-backend-binding')
    binding['record']['rundir'] = str(rd.parent.parent.parent)
    with pytest.raises(ValueError, match='escapes'):
        site.adopt(store, 'launch-a', base=rd)



def test_source_status_evolution_retains_original_remote_identity_and_adopts_once(env):
    from ravel.controller.routes.study import site
    store, rd, _, _, attempt, handle = env
    handle['state'] = 'submitted'
    (attempt / source.HANDLE_NAME).write_text(json.dumps(handle))
    first = call(env)
    original = store.scan('study-remote')[0]['record']['handle']
    _, receipt = fetched_source(env)
    assert call(env) == first
    assert store.scan('study-remote')[0]['record']['handle'] == original
    assert store.scan('study-adoption')[0]['record']['handle'] == original
    assert site.adopt(store, 'launch-a', base=rd) == receipt
    assert len(store.scan('study-remote')) == 1


@pytest.mark.parametrize('placed,approved', [(False, False), (True, False), (True, True)])
def test_remote_capture_authenticates_approval_for_a_placed_attempt(tmp_path, monkeypatch, placed, approved):
    from types import SimpleNamespace
    from ravel.controller.routes.study import remote, runtime
    child = tmp_path / 'children' / 'ordinary'
    (child / 'inputs').mkdir(parents=True)
    specification = child / 'inputs/science.json'
    specification.write_text(json.dumps({'execution': {'backend': 'native'}}))
    (child / execution.STATE_NAME).write_text(json.dumps({
        'schema_version': execution.VERSION, 'revision': 1,
        'stages': {'science': {'attempt_id': 'placed-attempt'}} if placed else {}}))
    store = Store(tmp_path / 'protected')
    operation = {'id': 'operate', 'parameters': {'ordinary': {'kind': 'science'}}}
    context = {'store': store, 'plan': {'steps': [operation]}}
    calls, tracked = [], []

    def ordinary(step, given, *, approved=True):
        assert step == operation and given == context
        calls.append(approved)
        if approved and not approved_input[0]:
            raise ValueError('the placed attempt requires its current child approval')
        return {'kind': 'science'}, child, SimpleNamespace(SPEC='inputs/science.json'), {}

    approved_input = [approved]
    monkeypatch.setattr(runtime, '_ordinary', ordinary)
    monkeypatch.setattr(backend, 'track', lambda *args, **kwargs: tracked.append((args, kwargs)))
    errors = remote.capture(context)
    assert calls[0] is False, 'prepared identity is checked before placed-attempt authority'
    if not placed:
        assert errors == [] and calls == [False] and tracked == []
    elif not approved:
        assert errors and errors[0]['code'] == 'site_backend_binding_invalid'
        assert 'current child approval' in errors[0]['message'] and tracked == []
    else:
        assert errors == [] and calls == [False, True]
        assert len(tracked) == 1 and tracked[0][1]['rundir'] == child
