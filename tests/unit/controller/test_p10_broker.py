"""The controller submission broker of a confined workflow child, with inert scheduler commands.

The child-side client runs as a real subprocess over the broker's Unix socket. The capability
module and run store are real; condor_submit, condor_q, condor_history and condor_rm are inert
scripts on PATH that only record their calls.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

import ravel
from ravel.controller.confine import capability as real_capability
from ravel.controller.routes.study import contracts, runtime, site
from ravel.controller.store import RunStore
from ravel.workflow import site_profiles, wms_broker, wms_policy, wms_site
from ravel.workflow.site_profiles.options import normalize
from ravel.workflow.wms_broker_client import BROKER_ENV, PYTHON_ENV

SOURCE_ROOT = str(Path(ravel.__file__).resolve().parents[1])


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _records(store, kind):
    return [row.get('record', row) for row in store.scan(kind)]


def _client(*args, broker=None):
    environment = {k: v for k, v in os.environ.items() if k not in (wms_policy.CAPABILITY_ENV, BROKER_ENV)}
    environment['PYTHONPATH'] = SOURCE_ROOT + os.pathsep + environment.get('PYTHONPATH', '')
    if broker is not None:
        environment[BROKER_ENV] = broker
    return subprocess.run([sys.executable, '-m', 'ravel.workflow.wms_broker_client', *args],
                          env=environment, capture_output=True, text=True, timeout=60)


@pytest.fixture
def brokered(tmp_path, monkeypatch):
    from ravel.controller import authority
    from ravel.controller.confine import runs
    root = tmp_path.resolve()
    store = RunStore('broker-run', root=root / 'protected')
    run = root / 'run'
    workflow = run / 'workflow'
    workflow.mkdir(parents=True)
    scripts = []
    for index in range(3):
        script = workflow / f'job-{index}.sh'
        script.write_text(f'# properties = {{"rule": "task_unit", "threads": 1}}\n# member {index}\nexit 0\n')
        scripts.append(script)
    tools = root / 'bin'
    tools.mkdir()
    calls, removed = root / 'submit-calls', root / 'removed'
    queue, history = root / 'queue', root / 'history'
    queue.write_text('')
    history.write_text('')
    programs = {
        'condor_submit': f'#!/bin/sh\necho "$2" >> "{calls}"\nn=$(wc -l < "{calls}")\n'
                         'printf "%d.0\\n" $((100 + $n))\n',
        'condor_q': f'#!/bin/sh\ngrep "^$1 " "{queue}" | cut -d" " -f2-\nexit 0\n',
        'condor_history': f'#!/bin/sh\ngrep "^$1 " "{history}" | cut -d" " -f2-\nexit 0\n',
        'condor_rm': f'#!/bin/sh\necho "$1" >> "{removed}"\nexit 0\n',
    }
    for name, text in programs.items():
        (tools / name).write_text(text)
        (tools / name).chmod(0o700)
    monkeypatch.setenv('PATH', str(tools) + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv(wms_policy.CAPABILITY_ENV, raising=False)
    monkeypatch.setattr(runs, 'owner_of', lambda path: ('broker-run', run))
    monkeypatch.setattr(runs, 'store', lambda run_id: pytest.fail('bound store must not use the default root'))
    state = {'stop': 'running'}
    monkeypatch.setattr(authority, 'stop_state', lambda store: state['stop'])
    written = site_profiles.write_profile(root / 'profiles', 'htcondor', options={
        'workflow_dir': str(workflow), 'submission': 'broker', 'mem_mb': 64, 'runtime': 1})
    folder = Path(written['path'])
    pin = wms_site.profile_pin(folder)
    approved = {'workflow_dir': str(workflow), 'max_jobs': 2, 'profile_sha256': pin['sha256']}
    token = real_capability.mint_capability(store, 'launch-one', approved)
    pins = [{'path': str(s), 'sha256': _sha(s)} for s in scripts[:2]]
    scope = {'jobscripts': pins, 'capability': approved}
    return {'store': store, 'run': run, 'workflow': workflow, 'scripts': scripts, 'calls': calls,
            'removed': removed, 'queue': queue, 'history': history, 'state': state, 'folder': folder,
            'token': token, 'scope': scope, 'pins': pins}


def _published(descriptor):
    """The published job script a recorded condor_submit description runs."""
    text = Path(descriptor).read_text()
    wrapper = re.search(r"^arguments = \"'(.+)'\"$", text, re.MULTILINE).group(1)
    return Path(wrapper).parent / 'job.sh'


def test_broker_submits_each_pin_once_and_answers_status_and_cancel(brokered):
    env = brokered
    store, scripts, state, token = env['store'], env['scripts'], env['state'], env['token']
    outputs = []

    def client(*args, broker=None):
        done = _client(*args, broker=broker)
        outputs.append(done.stdout + done.stderr)
        return done

    with site.trusted_launch(store, 'launch-one', token, env['scope']):
        broker = wms_broker.SubmissionBroker(profile=None, store=store, profile_dir=str(env['folder']),
                                             publish_dir=str(env['run'] / '.ravel-controller-submissions'))
    # The serving thread re-enters the captured launch; the caller's scope has ended.
    socket_path = broker.start()
    try:
        assert Path(socket_path).is_socket() and len(socket_path) <= wms_broker.SOCKET_PATH_LIMIT
        assert Path(socket_path).stat().st_mode & 0o777 == 0o600
        assert Path(socket_path).parent.stat().st_mode & 0o777 == 0o700

        first = client('submit', str(scripts[0]), broker=socket_path)
        assert first.returncode == 0, first.stderr
        assert first.stdout.strip() == '101.0'

        state['stop'] = 'stop_requested'
        stopped = client('submit', str(scripts[1]), broker=socket_path)
        assert stopped.returncode == 1 and 'operator state' in stopped.stderr
        state['stop'] = 'running'

        second = client('submit', str(scripts[1]), broker=socket_path)
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == '102.0'

        again = client('submit', str(scripts[0]), broker=socket_path)
        assert again.returncode == 1 and 'already submitted' in again.stderr
        stray = client('submit', str(scripts[2]), broker=socket_path)
        assert stray.returncode == 1 and 'not one of the approved' in stray.stderr
        absent = client('submit', str(scripts[1]))
        assert absent.returncode == 1 and absent.stdout == ''

        calls = env['calls'].read_text().splitlines()
        assert len(calls) == 2, 'refusals reach no scheduler command'
        assert [_sha(_published(path)) for path in calls] == [pin['sha256'] for pin in env['pins']]
        assert all(_published(path).parent.parent == env['run'] / '.ravel-controller-submissions'
                   for path in calls)

        env['queue'].write_text('101.0 2 undefined\n')
        assert client('status', '101.0', broker=socket_path).stdout.strip() == 'running'
        env['queue'].write_text('')
        env['history'].write_text('101.0 4 0\n102.0 4 1\n')
        assert client('status', '101.0', broker=socket_path).stdout.strip() == 'success'
        assert client('status', '102.0', broker=socket_path).stdout.strip() == 'failed'
        env['history'].write_text('')
        unknown = client('status', '101.0', broker=socket_path)
        assert unknown.returncode == 0 and unknown.stdout.strip() == 'failed'
        foreign = client('status', '999.0', broker=socket_path)
        assert foreign.stdout.strip() == 'failed' and 'not a submission of this launch' in foreign.stderr
        unreachable = client('status', '101.0')
        assert unreachable.returncode == 0 and unreachable.stdout.strip() == 'failed'

        refused = client('cancel', '101.0', '999.0', broker=socket_path)
        assert refused.returncode == 1 and not env['removed'].exists()
        cancelled = client('cancel', '101.0', '102.0', broker=socket_path)
        assert cancelled.returncode == 0, cancelled.stderr
        assert env['removed'].read_text().splitlines() == ['101.0', '102.0']
    finally:
        broker.stop()
    assert not os.path.lexists(socket_path) and not os.path.lexists(os.path.dirname(socket_path))

    assert len(_records(store, 'wms-submission')) == 2
    jobs = _records(store, 'study-site-job')
    assert [(r['job'], r['jobscript_sha256'], r['launch_id']) for r in jobs] == [
        ('101.0', env['pins'][0]['sha256'], 'launch-one'), ('102.0', env['pins'][1]['sha256'], 'launch-one')]
    journal = _records(store, wms_broker.JOURNAL)
    assert [(r['op'], r['reply_ok']) for r in journal] == [
        ('submit', True), ('submit', False), ('submit', True), ('submit', False), ('submit', False),
        ('status', True), ('status', True), ('status', True), ('status', True), ('status', False),
        ('cancel', False), ('cancel', True)]
    assert 'operator state' in journal[1]['error'] and 'already submitted' in journal[3]['error']
    assert journal[0]['request'] == {'op': 'submit', 'jobscript': str(scripts[0])}
    recorded = json.dumps([_records(store, kind) for kind in (
        wms_broker.JOURNAL, 'wms-submission', 'study-site-job', real_capability.KIND)])
    assert token not in recorded and not any(token in text for text in outputs)


def test_broker_refuses_construction_outside_a_launch_or_for_an_executor_profile(brokered, tmp_path):
    env = brokered
    with pytest.raises(ValueError, match='trusted launch'):
        wms_broker.SubmissionBroker(profile=None, store=env['store'], profile_dir=str(env['folder']))
    executor = site_profiles.write_profile(tmp_path / 'executor', 'htcondor',
                                           options={'workflow_dir': str(env['workflow'])})
    with site.trusted_launch(env['store'], 'launch-one', env['token'], env['scope']):
        with pytest.raises(ValueError, match='brokered site profile'):
            wms_broker.SubmissionBroker(profile=None, store=env['store'], profile_dir=executor['path'])
        with pytest.raises(ValueError, match='publication'):
            wms_broker.SubmissionBroker(profile=None, store=env['store'], profile_dir=str(env['folder']),
                                        publish_dir=str(env['workflow'] / 'published'))
        with pytest.raises(ValueError, match='site_broker'):
            wms_broker.from_parameters(env['store'], {'profile_dir': str(env['folder'])})
    assert env['store'].scan(wms_broker.JOURNAL) == []


def test_broker_refuses_unknown_and_malformed_requests_without_effects(brokered):
    env = brokered
    with site.trusted_launch(env['store'], 'launch-one', env['token'], env['scope']):
        broker = wms_broker.from_parameters(env['store'], {
            'profile_dir': str(env['folder']),
            'publish_dir': str(env['run'] / '.ravel-controller-submissions')})
    assert broker.handle({'op': 'execute', 'jobscript': str(env['scripts'][0])})['ok'] is False
    assert broker.handle({'op': 'submit', 'jobscript': 'job-0.sh'})['ok'] is False
    assert broker.handle({'op': 'submit', 'jobscript': str(env['scripts'][0]), 'capability': 'x'})['ok'] is False
    assert broker.handle({'op': 'cancel', 'jobs': []})['ok'] is False
    assert not env['calls'].exists() and env['store'].scan('wms-submission') == []
    assert len(env['store'].scan(wms_broker.JOURNAL)) == 4


def test_dispatch_starts_the_broker_around_the_child_and_withholds_the_capability(brokered, monkeypatch):
    from ravel.controller import confine
    env = brokered
    store = env['store']
    capsule = {'argv': [sys.executable, '-m', runtime.ADAPTER, 'run'], 'env': {'PATH': '/usr/bin'},
               'reads': [], 'writes': [], 'limits': {'wall_seconds': 5}, 'backend': 'auto'}
    seen = []

    class Process:
        pid = None
        returncode = None

        def communicate(self, timeout):
            self.returncode = 0
            return '', ''

    def popen(spec, **kwargs):
        seen.append({'spec': deepcopy(spec), 'socket_live': Path(spec['channels'][0]).is_socket()})
        return Process()
    monkeypatch.setattr(runtime, 'preflight', lambda store, step, context: {
        'capsule': capsule, 'launch_sha256': contracts.digest(capsule),
        'output_root': str(env['run'] / 'outputs'), 'inventory': {'equal': True}})
    monkeypatch.setattr(confine, 'popen', popen)
    monkeypatch.setattr(confine, 'finish', lambda process: None, raising=False)
    step = {'id': 'operate', 'budget': {'wall_seconds': 5}, 'parameters': {'site_broker': {
        'profile_dir': str(env['folder']), 'publish_dir': str(env['run'] / '.ravel-controller-submissions')}}}
    with site.trusted_launch(store, 'launch-one', env['token'], env['scope']):
        outcome = runtime.dispatch(store, step, {'attempt': 1})
    assert outcome['exit_status'] == 0 and len(seen) == 1 and seen[0]['socket_live']
    launched = seen[0]['spec']
    channel = launched['channels'][0]
    assert launched['env'] == {'PATH': '/usr/bin', BROKER_ENV: channel, PYTHON_ENV: capsule['argv'][0]}
    assert wms_policy.CAPABILITY_ENV not in launched['env'], 'a brokered child never holds the capability'
    assert not os.path.lexists(channel), 'the broker stops when the child ends'
    assert _records(store, 'study-operation-capability') == [
        {'key': 'operate:1', 'launch_sha256': contracts.digest(capsule),
         'passed': sorted([BROKER_ENV, PYTHON_ENV]), 'channels': [channel]}]
    assert env['token'] not in json.dumps(_records(store, 'study-operation-capability'))


def test_brokered_profile_render_and_pin_roster(tmp_path):
    from ravel.controller.confine import environment
    brokered = site_profiles.render('htcondor', options={'submission': 'broker', 'workflow_dir': '/fictional'})
    assert set(brokered['scripts']) == {'ravel-submit.sh', 'ravel-status.sh', 'ravel-cancel.sh'}
    for command in ('submit', 'status', 'cancel'):
        text = brokered['scripts']['ravel-' + command + '.sh']
        assert '-m ravel.workflow.wms_broker_client ' + command + ' "$@"' in text
        assert PYTHON_ENV in text and 'ravel-wms-condor' not in text and 'condor_' not in text
    assert brokered['config']['cluster-generic-cancel-cmd'] == 'ravel-cancel.sh'
    assert brokered['options']['submission'] == 'broker'
    executor = site_profiles.render('htcondor', options={'workflow_dir': '/fictional'})
    assert set(executor['scripts']) == {'ravel-submit.sh', 'ravel-status.sh'}
    assert executor['config']['cluster-generic-cancel-cmd'] == 'condor_rm'
    assert 'submission' not in executor['options']
    assert executor == site_profiles.render('htcondor', options={'workflow_dir': '/fictional',
                                                                 'submission': 'executor'})
    with pytest.raises(ValueError, match='submission'):
        normalize({'submission': 'direct'})
    assert BROKER_ENV in environment.passed_channels() and PYTHON_ENV in environment.passed_channels()

    folder = Path(site_profiles.write_profile(tmp_path / 'b', 'htcondor',
                                              options={'submission': 'broker'})['path'])
    pin = wms_site.profile_pin(folder)
    assert [Path(row['path']).name for row in pin['files']] == [
        'config.yaml', 'profile.json', 'ravel-submit.sh', 'ravel-status.sh', 'ravel-cancel.sh']
    (folder / 'ravel-cancel.sh').unlink()
    with pytest.raises(ValueError, match='members changed'):
        wms_site.profile_pin(folder)

    plain = Path(site_profiles.write_profile(tmp_path / 'e', 'htcondor')['path'])
    assert len(wms_site.profile_pin(plain)['files']) == 4
    extra = plain / 'ravel-cancel.sh'
    extra.write_text('#!/bin/sh\nexit 0\n')
    extra.chmod(0o755)
    with pytest.raises(ValueError, match='members changed'):
        wms_site.profile_pin(plain)
