"""Execution-backend core: plans, handles, staging receipts, leases, native adapter."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from ravel.setup import manifest as mf
from ravel.workflow import execution_backend as eb
from shipped_catalogue import shipped_groups


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch, request):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    if 'lease' in request.node.name:
        yield
        return
    # A native job runs only under the machine lease; these tests hold it as its supervisor would.
    with eb.machine_lease('execution-backend unit test'):
        yield


def native_spec(tmp_path, argv=None, **extra):
    data = tmp_path / 'input.txt'
    if not data.exists():
        data.write_text('three\n')
    spec = {
        'schema_version': 1, 'backend': 'native', 'stage': 'count-lines',
        'argv': argv or [sys.executable, '-c',
                         'import json,os,sys;n=len(open(sys.argv[1]).read().splitlines());'
                         'json.dump({"lines":n},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"result.json"),"w"))',
                         str(data)],
        'inputs': [{'path': str(data)}],
        'outputs': [{'name': 'result.json', 'destination': 'outputs/result.json', 'kind': 'file'}],
        'quantities': [{'name': 'lines', 'output': 'result.json', 'pointer': '/lines'}],
        'resources': {'cpus': 1, 'memory_mib': 256, 'wall_seconds': 60},
    }
    spec.update(extra)
    return spec


def wait_terminal(plan, handle, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        observation = eb.observe(plan, handle)
        if observation['state'] in eb.TERMINAL:
            return observation
        time.sleep(0.05)
    raise AssertionError('job did not finish')


def test_registry_lists_all_adapters():
    # The Magnus adapter needs its own toolchain group; a release that withholds the group omits it.
    assert set(eb.kinds()) == {'native', 'oci-local', 'site', *shipped_groups(['magnus'])}
    with pytest.raises(ValueError, match='unknown execution backend'):
        eb.get('cloud-magic')


def test_plan_is_canonical_and_pins_inputs(tmp_path):
    plan = eb.prepare(native_spec(tmp_path))
    again = eb.prepare(native_spec(tmp_path))
    assert plan['plan_sha256'] == again['plan_sha256']
    assert plan['inputs'][0]['sha256'] == eb.file_sha256(tmp_path / 'input.txt')
    path = eb.write_plan(plan, tmp_path / 'plan.json')
    assert eb.load_plan(path)['plan_sha256'] == plan['plan_sha256']
    (tmp_path / 'input.txt').write_text('changed\n')
    with pytest.raises(ValueError, match='input .* changed'):
        eb.load_plan(path)


def test_plan_refuses_tampering(tmp_path):
    path = eb.write_plan(eb.prepare(native_spec(tmp_path)), tmp_path / 'plan.json')
    document = json.loads(path.read_text())
    document['spec']['resources']['wall_seconds'] = 99999
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='plan digest'):
        eb.load_plan(path)


@pytest.mark.parametrize('mutate, message', [
    (lambda s: s['resources'].pop('wall_seconds'), 'wall_seconds'),
    (lambda s: s['resources'].update(cpus=0), 'cpus'),
    (lambda s: s.update(env={'MAGNUS_TOKEN': 'x'}), 'credential'),
    (lambda s: s.update(env={'lower': 'x'}), 'environment name'),
    (lambda s: s['outputs'].append({'name': '../escape', 'destination': 'x', 'kind': 'file'}), 'relative'),
    (lambda s: s.update(argv=[]), 'argv'),
    (lambda s: s['quantities'].append({'name': 'n', 'output': 'missing.json', 'pointer': '/n'}), 'declared output'),
])
def test_spec_validation_refusals(tmp_path, mutate, message):
    spec = native_spec(tmp_path)
    mutate(spec)
    with pytest.raises(ValueError, match=message):
        eb.prepare(spec)


@pytest.mark.parametrize('image, message', [
    ({'reference': 'docker.io/library/fedora:latest', 'platform': 'linux/arm64'}, 'digest'),
    ({'reference': 'fedora', 'platform': 'linux/arm64'}, 'digest'),
    ({'reference': 'fedora@sha256:' + 'a' * 64, 'platform': 'windows/arm64'}, 'platform'),
])
def test_image_must_be_digest_pinned(image, message):
    with pytest.raises(ValueError, match=message):
        eb.validate_image(image)


def test_source_commit_must_be_full_sha():
    with pytest.raises(ValueError, match='commit'):
        eb.validate_source({'repository': 'https://example.org/repo.git', 'commit': 'HEAD'})
    assert eb.validate_source({'repository': 'https://example.org/repo.git', 'commit': 'a' * 40})


def test_native_round_trip_with_receipts(tmp_path):
    plan = eb.prepare(native_spec(tmp_path))
    attempt = tmp_path / 'attempt'
    handle = eb.submit(plan, attempt)
    assert (attempt / eb.HANDLE_NAME).is_file()
    assert handle['tag'].startswith('ravel-' + plan['plan_sha256'][:12])
    observation = wait_terminal(plan, handle)
    assert observation['state'] == 'succeeded'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    receipt = eb.fetch(plan, handle, rundir)
    target = rundir / 'outputs/result.json'
    assert json.loads(target.read_text()) == {'lines': 1}
    assert receipt['outputs'][0]['sha256'] == eb.file_sha256(target)
    assert receipt['quantities'] == {'lines': 1}
    assert json.loads((attempt / 'fetch-receipt.json').read_text()) == receipt


def test_fetch_never_overwrites_an_existing_output(tmp_path):
    plan = eb.prepare(native_spec(tmp_path))
    handle = eb.submit(plan, tmp_path / 'attempt')
    wait_terminal(plan, handle)
    rundir = tmp_path / 'run'
    (rundir / 'outputs').mkdir(parents=True)
    (rundir / 'outputs/result.json').write_text('keep me')
    with pytest.raises(ValueError, match='already exists'):
        eb.fetch(plan, handle, rundir)
    assert (rundir / 'outputs/result.json').read_text() == 'keep me'


def test_exit_zero_without_requested_quantity_fails(tmp_path):
    argv = [sys.executable, '-c',
            'import json,os;json.dump({"other":1},open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"result.json"),"w"))']
    plan = eb.prepare(native_spec(tmp_path, argv=argv))
    handle = eb.submit(plan, tmp_path / 'attempt')
    assert wait_terminal(plan, handle)['state'] == 'succeeded'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    with pytest.raises(ValueError, match='requested quantity lines'):
        eb.fetch(plan, handle, rundir)
    assert not (rundir / 'outputs/result.json').exists()


def test_exit_zero_without_declared_output_fails(tmp_path):
    plan = eb.prepare(native_spec(tmp_path, argv=[sys.executable, '-c', 'pass']))
    handle = eb.submit(plan, tmp_path / 'attempt')
    assert wait_terminal(plan, handle)['state'] == 'succeeded'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    with pytest.raises(ValueError, match='declared output result.json'):
        eb.fetch(plan, handle, rundir)


def test_nonzero_exit_is_failed(tmp_path):
    plan = eb.prepare(native_spec(tmp_path, argv=[sys.executable, '-c', 'raise SystemExit(7)']))
    handle = eb.submit(plan, tmp_path / 'attempt')
    observation = wait_terminal(plan, handle)
    assert observation['state'] == 'failed' and observation['exit_code'] == 7
    with pytest.raises(ValueError, match='succeeded'):
        eb.fetch(plan, handle, tmp_path)


def test_handle_written_before_dispatch_and_crash_is_recoverable(tmp_path, monkeypatch):
    plan = eb.prepare(native_spec(tmp_path))
    backend = eb.get('native')
    seen = {}
    original = backend.submit

    def crashing_submit(plan, handle):
        seen['handle_on_disk'] = json.loads((Path(handle['attempt_dir']) / eb.HANDLE_NAME).read_text())
        original(plan, handle)
        raise RuntimeError('client died after dispatch')
    monkeypatch.setattr(backend, 'submit', crashing_submit)
    with pytest.raises(RuntimeError):
        eb.submit(plan, tmp_path / 'attempt', backend=backend)
    assert seen['handle_on_disk']['state'] == 'dispatching'
    handle = eb.read_handle(tmp_path / 'attempt')
    # The launch recorded itself before the client failed: the handle keeps its identity.
    assert handle['remote'] is not None and handle['adopted_after_dispatch_error'] is True
    assert 'client died' in handle['dispatch_error']
    recovered = eb.recover(plan, handle)
    assert recovered['handle']['remote'] is not None
    assert wait_terminal(plan, recovered['handle'])['state'] == 'succeeded'


def test_native_cancel_stops_the_owned_group(tmp_path):
    argv = [sys.executable, '-c', 'import time; time.sleep(60)']
    plan = eb.prepare(native_spec(tmp_path, argv=argv))
    handle = eb.submit(plan, tmp_path / 'attempt')
    time.sleep(0.3)
    assert eb.observe(plan, handle)['state'] == 'running'
    observation = eb.cancel(plan, handle, wait_seconds=10)
    assert observation['state'] == 'cancelled'
    assert eb.read_handle(tmp_path / 'attempt')['cancel_requested'] is True


def test_logs_are_read_incrementally_and_redacted(tmp_path):
    argv = [sys.executable, '-c', 'print("hello"); print("token sk-abcdefghijklmnop")']
    plan = eb.prepare(native_spec(tmp_path, argv=argv, outputs=[], quantities=[]))
    handle = eb.submit(plan, tmp_path / 'attempt')
    wait_terminal(plan, handle)
    text, offset = eb.logs(plan, handle)
    assert 'hello' in text and 'sk-abcdefghijklmnop' not in text and '[redacted]' in text
    more, again = eb.logs(plan, handle, since=offset)
    assert more == '' and again == offset


def test_machine_lease_allows_one_local_job(tmp_path):
    with eb.machine_lease('first'):
        with pytest.raises(ValueError, match='native scientific job'):
            with eb.machine_lease('second'):
                pass
    with eb.machine_lease('third'):
        pass


def test_remote_slots_follow_the_owner_ceiling(tmp_path, monkeypatch):
    assert eb.remote_ceiling() == 1
    with eb.remote_slot('a'):
        with pytest.raises(ValueError, match='remote job ceiling'):
            with eb.remote_slot('b'):
                pass
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '2')
    with eb.remote_slot('a'), eb.remote_slot('b'):
        pass


def test_redact_removes_tokens():
    text = 'MAGNUS_TOKEN=abc123 sk-0123456789abcdef password: hunter2 ok'
    clean = eb.redact(text)
    assert 'abc123' not in clean and 'sk-0123456789abcdef' not in clean and 'hunter2' not in clean
    assert clean.endswith('ok')


def test_doctor_reports_every_backend(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path))
    report = eb.doctor_all()
    kinds = {row['backend'] for row in report}
    assert kinds == set(eb.released_kinds())
    # The adapter of a withheld toolchain group stays for development dispatch: not offered, never ready.
    held = mf.unreleased_groups(mf.load()[0]) & set(eb.kinds())
    for kind in held:
        assert kind not in kinds
        doctor = eb.get(kind).doctor()
        assert doctor['ready'] is False and any(kind in c['detail'] for c in doctor['checks'])


def test_no_magnus_import_in_package():
    package = Path(eb.__file__).resolve().parents[1]
    offenders = []
    for path in package.rglob('*.py'):
        for line in path.read_text(errors='replace').splitlines():
            stripped = line.strip()
            if stripped.startswith(('import magnus', 'from magnus')):
                offenders.append(str(path))
    assert offenders == []


def test_cli_prepare_and_describe(tmp_path, capsys):
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(native_spec(tmp_path)))
    assert eb.main(['prepare', '--spec', str(spec_path), '--out', str(tmp_path / 'plan.json')]) == 0
    plan = json.loads((tmp_path / 'plan.json').read_text())
    assert plan['kind'] == 'ravel-backend-plan'
    assert eb.main(['list']) == 0
    assert 'oci-local' in capsys.readouterr().out


def test_a_leaderless_group_is_signalled_only_when_a_member_proves_it_is_the_job(tmp_path, monkeypatch):
    """A held job log alone does not prove a reused process group is this job's: a member must carry its token
    or have its log open."""
    from ravel.workflow import machine_lease
    from ravel.workflow.backends import native
    token = 'e' * 32
    job = tmp_path / 'job'
    job.mkdir()
    handle = {'job_dir': str(job), 'remote': {'pid': 4242, 'pgid': 4242, 'identity': 'gone', 'job_token': token}}
    monkeypatch.setattr(native, '_process_identity', lambda pid: None)  # the leader is gone
    monkeypatch.setattr(native, '_group_members', lambda pgid: [4243])
    monkeypatch.setattr(machine_lease, 'hold_busy', lambda hold: True)
    monkeypatch.setattr(native, '_log_holders', lambda path, pids: [9998])
    monkeypatch.setattr(machine_lease, 'token_census', lambda: {token: [9999]})
    assert native.NativeBackend()._owned(handle) is False
    monkeypatch.setattr(machine_lease, 'token_census', lambda: None)  # unknown is not proof
    monkeypatch.setattr(native, '_log_holders', lambda path, pids: None)
    assert native.NativeBackend()._owned(handle) is False
    monkeypatch.setattr(machine_lease, 'token_census', lambda: {token: [4243]})
    assert native.NativeBackend()._owned(handle) is True
    # A member that has the job's log open proves it too (a system binary hides its token from ps).
    monkeypatch.setattr(machine_lease, 'token_census', lambda: {})
    monkeypatch.setattr(native, '_log_holders', lambda path, pids: [4243])
    assert native.NativeBackend()._owned(handle) is True


def test_coordination_locks_retain_identity_and_preserve_output_validation(tmp_path):
    from ravel.workflow import execution
    output = tmp_path / 'outputs'
    output.mkdir()
    artifact = output / 'result.txt'
    artifact.write_text('measured artifact')
    lock = output / 'dispatch.lock'
    with eb._flock(lock, 'dispatch already active'):
        record = json.loads(lock.read_text())
        assert record == {'schema_version': 1, 'kind': 'backend-coordination-lock',
                          'path': str(lock.resolve()), 'purpose': 'dispatch already active', 'locking': 'flock'}
        inode, contents = lock.stat().st_ino, lock.read_bytes()
        with pytest.raises(ValueError, match='dispatch already active'):
            with eb._flock(lock, 'dispatch already active'):
                pytest.fail('concurrent coordination lock admitted')
    with eb._flock(lock, 'dispatch already active'):
        assert lock.stat().st_ino == inode and lock.read_bytes() == contents
    assert execution.snapshot(tmp_path, ['outputs'], outputs=True)
    artifact.write_bytes(b'')
    with pytest.raises(ValueError, match='empty output'):
        execution.snapshot(tmp_path, ['outputs'], outputs=True)
