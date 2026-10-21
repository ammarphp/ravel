"""Hostile authored scripts under the confined launcher, in the host's real OS sandbox.

Linux runs on the cluster nodes (bwrap); the same file runs once on macOS (sandbox-exec). Each
attempt is made by the script itself and must fail inside the sandbox; the effect counters
are read outside it, and the positive control writes its declared output (SW34-SW38, T04,
T05, C11, C24, E16).
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from test_p05_support import operator, own, sandboxed  # noqa: F401 (fixture)

HOSTILE = r'''
import json, os, socket, subprocess, sys, time
paths = json.loads(sys.argv[1])
result = {}
def attempt(name, action):
    try:
        action()
        result[name] = 'ALLOWED'
    except (OSError, subprocess.SubprocessError) as error:
        result[name] = 'denied'
def write(path, mode='w'):
    with open(path, mode) as stream:
        stream.write('hostile')
def read(path):
    with open(path, 'rb') as stream:
        return stream.read()
attempt('write_store', lambda: write(paths['store'], 'a'))
attempt('read_store', lambda: read(paths['store']))
attempt('write_custody', lambda: write(paths['custody'], 'a'))
attempt('write_install', lambda: write(paths['install_new']))
attempt('write_role_card', lambda: write(paths['role_card'], 'a'))
attempt('write_project_policy', lambda: write(paths['policy'], 'a'))
attempt('write_approval', lambda: write(paths['approval']))
attempt('create_governed_name', lambda: write(paths['governed_name']))
attempt('read_credential', lambda: read(paths['credential']))
attempt('read_config_token', lambda: read(paths['config_token']))
attempt('read_other_workspace', lambda: read(paths['other_workspace']))
attempt('read_withheld', lambda: read(paths['withheld']))
def connect():
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(('127.0.0.1', paths['port']))
    finally:
        s.close()
attempt('connect_host_port', connect)
def model_cli():
    # Any start counts as allowed, whatever the program then manages to do.
    subprocess.run([paths['model_cli'], '--version'], capture_output=True, timeout=10, check=False)
attempt('start_model_cli', model_cli)
result['environment'] = sorted(name for name in paths['forbidden_names'] if name in os.environ)
with open(paths['output'], 'w') as stream:
    stream.write('declared result')
attempt('write_undeclared', lambda: write(paths['junk']))
if paths.get('orphan'):
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            # A daemon detaches from the launch's output, so nothing waits for it.
            null = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null, fd)
            time.sleep(1.5)
            with open(paths['orphan'], 'w') as stream:
                stream.write('survived')
        os._exit(0)
print(json.dumps(result))
'''
FORBIDDEN = ('WORKFLOW_STATE_UTC', 'GATE_TIMESTAMP', 'LHE_CHECK_UTC', 'GH_TOKEN', 'ANTHROPIC_API_KEY',
             'HTTPS_PROXY', 'https_proxy', 'CLAUDECODE', 'CODEX_THREAD_ID', 'RAVEL_SESSION_ID', 'RAVEL_ROOT',
             'RAVEL_STATE_DIR', 'RAVEL_ADDON_PATH', 'RAVEL_NATIVE_BIN', 'SSH_AUTH_SOCK', 'AWS_SECRET_ACCESS_KEY')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    home = base / 'home'
    (home / '.ssh').mkdir(parents=True)
    (home / '.ssh' / 'id_canary').write_text('credential-canary-7f1c')
    (home / '.config' / 'tool').mkdir(parents=True)
    (home / '.config' / 'tool' / 'token').write_text('token-canary-41aa')
    state = base / 'state'
    (state / 'workers').mkdir(parents=True)
    (state / 'workers' / 'custody.jsonl').write_text('{"custody": 1}\n')
    workspaces = base / 'workspaces'
    (workspaces / 'peer' / 'outputs').mkdir(parents=True)
    (workspaces / 'peer' / 'outputs' / 'secret.txt').write_text('peer-canary-90be')
    project = base / 'project'
    (project / '.ravel').mkdir(parents=True)
    (project / '.ravel' / 'provider-policy.json').write_text('{"providers": []}')
    run = project / 'trial-runs' / 'run'
    (run / 'inputs').mkdir(parents=True)
    (run / 'inputs' / 'checkin1_approval.json').write_text('{"approved_plan": "full"}')
    (run / 'reference').mkdir()
    (run / 'reference' / 'withheld.json').write_text('{"withheld": "reference-canary-5d2e"}')
    (run / 'outputs').mkdir()
    store_root = base / 'controller-store'
    stores = own(monkeypatch, store_root, {run: 'run-hostile'})
    stores['run-hostile'].append('journal', {'event': 'original'})
    operator(monkeypatch, {'store_root': str(store_root)})
    bin_dir = base / 'bin'
    bin_dir.mkdir()
    model = bin_dir / 'claude'
    model.write_text(f'#!/bin/sh\necho called > {base / "model-called"}\n')
    model.chmod(0o755)
    import ravel
    install = Path(ravel.__file__).resolve().parent
    cards = sorted((install / 'data' / 'roles' / 'cards').glob('*.json'))
    for name, value in (('HOME', str(home)), ('RAVEL_STATE_DIR', str(state)), ('RAVEL_WORK_ROOT', str(workspaces)),
                        ('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z'), ('GATE_TIMESTAMP', '2001-01-01T00:00:00Z'),
                        ('LHE_CHECK_UTC', '2001-01-01T00:00:00Z'), ('GH_TOKEN', 'x'), ('ANTHROPIC_API_KEY', 'x'),
                        ('HTTPS_PROXY', 'http://proxy.invalid'), ('https_proxy', 'http://proxy.invalid'),
                        ('CLAUDECODE', '1'), ('CODEX_THREAD_ID', 'x'), ('RAVEL_SESSION_ID', 'x'),
                        ('RAVEL_ROOT', str(project)), ('RAVEL_ADDON_PATH', str(project)),
                        ('RAVEL_NATIVE_BIN', str(bin_dir)), ('SSH_AUTH_SOCK', str(base / 'agent.sock')),
                        ('AWS_SECRET_ACCESS_KEY', 'x'), ('PATH', str(bin_dir) + os.pathsep + os.environ['PATH'])):
        monkeypatch.setenv(name, value)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(0.3)
    yield {'base': base, 'run': run, 'store_file': store_root / 'run-hostile' / 'journal.jsonl',
           'custody': state / 'workers' / 'custody.jsonl', 'install': install, 'card': cards[0],
           'policy': project / '.ravel' / 'provider-policy.json', 'listener': listener, 'model': model,
           'paths': {'store': str(store_root / 'run-hostile' / 'journal.jsonl'),
                     'custody': str(state / 'workers' / 'custody.jsonl'),
                     'install_new': str(install / 'hostile_planted.py'), 'role_card': str(cards[0]),
                     'policy': str(project / '.ravel' / 'provider-policy.json'),
                     'approval': str(run / 'inputs' / 'checkin1_approval.json'),
                     'governed_name': str(run / 'task_contract.json'),
                     'credential': str(home / '.ssh' / 'id_canary'),
                     'config_token': str(home / '.config' / 'tool' / 'token'),
                     'other_workspace': str(workspaces / 'peer' / 'outputs' / 'secret.txt'),
                     'withheld': str(run / 'reference' / 'withheld.json'),
                     'port': listener.getsockname()[1], 'model_cli': str(model),
                     'forbidden_names': list(FORBIDDEN),
                     'output': str(run / 'outputs' / 'result.txt'), 'junk': str(run / 'junk.txt')}}
    listener.close()


def launch(world, extra_paths=None, writes=None):
    from ravel.controller import confine
    script = world['run'] / 'hostile.py'
    script.write_text(HOSTILE)
    paths = {**world['paths'], **(extra_paths or {})}
    spec = {'argv': [sys.executable, str(script), json.dumps(paths)], 'run_dir': str(world['run']),
            'stage': 'hostile', 'cwd': str(world['run']), 'reads': [str(world['run'])],
            'writes': writes or [str(world['run'] / 'outputs'), str(world['run'] / 'summary.json')],
            'withheld': [str(world['run'] / 'reference')]}
    before = {'store': digest(world['store_file']), 'custody': digest(world['custody']),
              'card': digest(world['card']), 'policy': digest(world['policy']),
              'approval': digest(world['run'] / 'inputs' / 'checkin1_approval.json')}
    process = confine.popen(spec, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    out, err = process.communicate(timeout=120)
    finished = confine.finish(process)
    return process, json.loads(out.decode().strip().splitlines()[-1]) if out.strip() else None, err.decode(), \
        finished, before


def test_T04_C11_C24_SW34_hostile_attempts_fail_and_declared_output_is_written(sandboxed, world):
    process, seen, err, finished, before = launch(world)
    assert process.returncode == 0, err
    # On Linux a new name in the run root lands in the launch's private staging copy and is never
    # adopted; the effect counter below (no such file in the run) is the check that matters there.
    staged = {'create_governed_name', 'write_undeclared'} if sandboxed == 'linux' else set()
    denied = {k: v for k, v in seen.items() if k != 'environment' and k not in staged}
    assert set(denied.values()) == {'denied'}, denied
    assert seen['environment'] == [], 'forbidden variables reached the launch'
    # Effect counters, read outside the sandbox.
    assert digest(world['store_file']) == before['store'] and digest(world['custody']) == before['custody']
    assert digest(world['card']) == before['card'] and digest(world['policy']) == before['policy']
    assert digest(world['run'] / 'inputs' / 'checkin1_approval.json') == before['approval']
    assert not (world['install'] / 'hostile_planted.py').exists()
    assert not (world['run'] / 'task_contract.json').exists()
    assert not (world['base'] / 'model-called').exists()
    with pytest.raises(socket.timeout):
        world['listener'].accept()
    # Positive control and quarantine.
    assert (world['run'] / 'outputs' / 'result.txt').read_text() == 'declared result'
    assert not (world['run'] / 'junk.txt').exists()
    if sandboxed == 'linux':
        assert str(world['run'] / 'junk.txt') in finished['quarantined']
    record = process.ravel_confinement.record
    assert record['kind'] == 'confined' and record['network'] == 'none'
    assert set(FORBIDDEN).isdisjoint(record['environment_names'])
    assert str(world['model']) in record['agent_programs_refused'] or str(world['model'].resolve()) in record[
        'agent_programs_refused']


def test_an_orphan_does_not_outlive_its_launch(sandboxed, world):
    marker = world['run'] / 'outputs' / 'orphan.txt'
    process, seen, err, finished, _ = launch(world, {'orphan': str(marker)})
    assert process.returncode == 0, err
    time.sleep(2.5)
    assert not marker.exists(), 'a process of the launch survived its finish'
    if sandboxed == 'macos':
        assert finished['orphans_ended'], 'the macOS launch must end its survivors by their custody secret'


def test_a_new_output_is_created_only_under_its_declared_name(sandboxed, world):
    script = world['run'] / 'writer.py'
    script.write_text('import sys\nopen(sys.argv[1], "w").write("summary")\ntry:\n open(sys.argv[2], "w").write("other")\nexcept OSError: pass\n')
    from ravel.controller import confine
    process = confine.popen({'argv': [sys.executable, str(script), str(world['run'] / 'summary.json'),
                                      str(world['run'] / 'other.json')],
                             'run_dir': str(world['run']), 'stage': 'writer', 'cwd': str(world['run']),
                             'reads': [str(world['run'])], 'writes': [str(world['run'] / 'summary.json')]},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    out, err = process.communicate(timeout=60)
    finished = confine.finish(process)
    assert process.returncode == 0, err.decode()
    assert (world['run'] / 'summary.json').read_text() == 'summary'
    assert not (world['run'] / 'other.json').exists()
    if sandboxed == 'linux':
        assert str(world['run'] / 'other.json') in finished['quarantined']


def test_T05_E16_domain_launch_cannot_request_a_tcp_exception(tmp_path):
    from ravel.controller import confine
    with pytest.raises(confine.ConfinementRefused, match='no network'):
        confine.prepare({'argv': [sys.executable, '-c', 'pass'], 'tcp_ports': [443]})


def test_the_launch_sees_no_network_without_a_declared_port(sandboxed, tmp_path):
    from ravel.controller import confine
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    server.settimeout(0.3)
    out = tmp_path.resolve() / 'out'
    out.mkdir()
    program = ('import socket, sys\ntry:\n    s = socket.socket(); s.settimeout(2)\n'
               '    s.connect(("127.0.0.1", int(sys.argv[1])))\n    print("connected")\nexcept OSError:\n'
               '    print("refused")\n')
    process = confine.popen({'argv': [sys.executable, '-c', program, str(server.getsockname()[1])],
                             'writes': [str(out)]}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=60)
    confine.finish(process)
    assert stdout.decode().strip() == 'refused', stderr.decode()
    with pytest.raises(socket.timeout):
        server.accept()
    server.close()


def test_C18_only_committed_inputs_are_readable(sandboxed, tmp_path):
    from ravel.controller import confine
    inputs = (tmp_path / 'inputs-dir').resolve()
    inputs.mkdir()
    (inputs / 'committed.json').write_text('{"committed": 1}')
    (inputs / 'helper.sh').write_text('echo unlisted helper\n')
    out = (tmp_path / 'out').resolve()
    out.mkdir()
    program = ('import json, sys\nr = {}\nfor name in ("committed.json", "helper.sh"):\n'
               '    try:\n        open(sys.argv[1] + "/" + name).read(); r[name] = "read"\n'
               '    except OSError:\n        r[name] = "denied"\nprint(json.dumps(r))\n')
    process = confine.popen({'argv': [sys.executable, '-c', program, str(inputs)],
                             'reads': [str(inputs / 'committed.json')], 'writes': [str(out)], 'cwd': str(out),
                             'input_digests': {str(inputs / 'committed.json'):
                                               hashlib.sha256(b'{"committed": 1}').hexdigest()}},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate(timeout=60)
    confine.finish(process)
    assert json.loads(stdout.decode().strip().splitlines()[-1]) == {'committed.json': 'read', 'helper.sh': 'denied'}, \
        stderr.decode()
