"""A native job executes the verified file and keeps the name it was invoked by.

The interpreter of a virtual environment is a symbolic link to the base
interpreter on Linux. The backend pins and executes the file the link resolves
to; the payload must still start as the environment's interpreter, or it loses
every package of that environment. The environment here is synthetic: a link to
this interpreter with one marker module.
"""
import json
import os
from pathlib import Path
import sys
import time
import venv

import pytest

from ravel.workflow import execution_backend as eb, machine_lease as ml
from ravel.workflow.backends import native

MARKER = 'invoked_name_marker'
PAYLOAD = ('import json, os, sys\n'
           f'import {MARKER}\n'
           'json.dump({"marker": ' + MARKER + '.VALUE, "prefix": sys.prefix, "executable": sys.executable},\n'
           '          open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"], "n.json"), "w"))\n')


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv(ml.ENV, raising=False)
    monkeypatch.delenv(ml.JOB_ENV, raising=False)
    eb._INSTANCES.clear()


@pytest.fixture
def environment(tmp_path):
    """A virtual environment whose interpreter is a symbolic link, with one module of its own."""
    root = tmp_path / 'environment'
    venv.EnvBuilder(symlinks=True, with_pip=False).create(root)
    interpreter = root / 'bin/python'
    assert interpreter.is_symlink(), 'the control needs an interpreter reached through a symbolic link'
    packages = root / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    (packages / f'{MARKER}.py').write_text('VALUE = "module of the linked environment"\n')
    return root, interpreter


def _spec(argv, **extra):
    return {'schema_version': 1, 'backend': 'native', 'stage': 'invoked-name', 'argv': argv,
            'outputs': [{'name': 'n.json', 'destination': 'outputs/n.json'}],
            'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 60}, **extra}


def _run(plan, attempt):
    with ml.held('invoked-name control'):
        handle = eb.submit(plan, attempt)
        deadline = time.monotonic() + 60
        while True:
            observation = eb.observe(plan, handle)
            if observation['state'] in eb.TERMINAL:
                break
            assert time.monotonic() < deadline, observation
            time.sleep(0.05)
    log = eb.get('native').logs(plan, handle)
    assert observation['state'] == 'succeeded', log
    return json.loads((Path(handle['job_dir']) / 'output/n.json').read_text())


def test_a_payload_reached_through_a_linked_interpreter_keeps_its_environment(tmp_path, environment):
    root, interpreter = environment
    plan = eb.prepare(_spec([str(interpreter), '-c', PAYLOAD]))
    # The pin is the file the link resolves to, not the link.
    pinned = plan['backend']['executable']
    assert pinned['path'] == str(interpreter.resolve()) != str(interpreter)
    assert pinned['sha256'] == eb.file_sha256(interpreter.resolve())
    result = _run(plan, tmp_path / 'attempt')
    assert result['marker'] == 'module of the linked environment'
    assert Path(result['prefix']) == root and Path(result['executable']) == interpreter


def test_a_name_found_on_the_job_path_is_the_invoked_name(tmp_path, environment):
    root, interpreter = environment
    job_path = os.pathsep.join([str(interpreter.parent), os.environ.get('PATH', os.defpath)])
    plan = eb.prepare(_spec(['python', '-c', PAYLOAD], env={'PATH': job_path}))
    assert plan['backend']['executable']['path'] == str(interpreter.resolve())
    result = _run(plan, tmp_path / 'attempt')
    assert result['marker'] == 'module of the linked environment' and Path(result['prefix']) == root


def test_the_launcher_executes_the_verified_file_under_the_invoked_name(tmp_path, monkeypatch):
    seen = {}

    class Process:
        pid = os.getpid()

        def wait(self):
            return 0

    def popen(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return Process()
    job = tmp_path / 'attempt/job'
    job.mkdir(parents=True)
    token, lease = 'c' * 32, 'd' * 32
    (job.parent / eb.HANDLE_NAME).write_text(json.dumps({
        'job_dir': str(job), 'state': 'dispatching', 'backend': 'native', 'tag': 'synthetic',
        'authority': {'lease_id': lease}}))
    monkeypatch.setenv(ml.JOB_ENV, token)
    monkeypatch.setenv(ml.ENV, lease)
    monkeypatch.setattr(ml, 'fence_inherited', lambda *a, **k: None)
    # The launcher's own process queries are answered here: only the payload launch reaches Popen.
    monkeypatch.setattr(native, '_process_identity', lambda pid: 'synthetic start identity')
    monkeypatch.setattr(native, '_group_members', lambda pgid: [])
    monkeypatch.setattr(native.subprocess, 'Popen', popen)
    assert native.main(['launch', '--job', str(job), '--argv0', '/linked/name', '--', '/verified/file', 'a', 'b']) == 0
    assert seen == {'argv': ['/linked/name', 'a', 'b'], 'executable': '/verified/file'}
    assert json.loads((job / 'exit.json').read_text()) == {'exit_code': 0}
    # Without a name the verified file is its own name, as before.
    seen.clear()
    (job / 'exit.json').unlink()
    assert native.main(['launch', '--job', str(job), '--', '/verified/file', 'a']) == 0
    assert seen == {'argv': ['/verified/file', 'a'], 'executable': '/verified/file'}


@pytest.mark.parametrize('argv', [
    ['launch', '--job', 'directory'],
    ['launch', '--job', 'directory', '--'],
    ['launch', '--job', 'directory', '--argv0', 'name', '--'],
    ['launch', '--job', 'directory', '--argv0', '--', 'file'],
    ['run', '--job', 'directory', '--', 'file'],
])
def test_the_launcher_refuses_an_incomplete_command_line(argv, capsys):
    assert native.main(argv) == 2
    assert 'usage' in capsys.readouterr().err
