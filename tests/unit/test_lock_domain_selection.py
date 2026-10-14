"""Only the test harness or a selftest selects a test lock domain; nothing a worker or shell sets does.

The test lock domain serves a lease without an approved binding and a run location without
steering custody. A process outside the test runner must not reach it with variables, a marker
file or an argument, and must not fall back to the machine directory either: every probe below
runs in a fresh interpreter whose machine directory would lie in a temporary home, and that home
stays empty. The real per-user directory is never resolved for writing.
"""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys

import pytest

from ravel.workflow import machine_lease as ml

SRC = str(Path(__file__).resolve().parents[2] / 'src')

# A fresh interpreter that is not a test: its password-database home is a temporary directory, so a
# fallback to the machine directory would be visible there instead of in the real home.
PROBE = r'''
import json, os, pwd, sys
home, run, program = sys.argv[1:4]
real = pwd.getpwuid
class Entry:
    def __init__(self, entry):
        self.entry = entry
    def __getattr__(self, name):
        return home if name == 'pw_dir' else getattr(self.entry, name)
pwd.getpwuid = lambda uid: Entry(real(uid))
from ravel.workflow import gate_wiring as gw, machine_lease as ml, rdj_custody, transport_registry as tr
out = {}
def attempt(name, operation):
    try:
        out[name] = ['permitted', repr(operation())]
    except Exception as exc:
        out[name] = ['refused', type(exc).__name__, str(exc)]
attempt('domain', ml.domain)
attempt('machine_dir', ml.ensure_machine_dir)
attempt('unbound_lease', lambda: ml.release(ml.acquire('forged-probe', wait_seconds=0)))
attempt('custody', lambda: rdj_custody.root(run))
def launch():
    with gw.steering_dispatch(run, 'node'):
        return 'launched'
attempt('launch', launch)
attempt('trusted_program', lambda: tr.check_executable_location(program))
print(json.dumps(out))
'''


def _program(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'cli'
    path.write_text('#!/bin/sh\nexit 0\n')
    path.chmod(0o755)
    return path


def _probe(tmp_path, extra):
    """Run PROBE in a fresh process that is not a test, with only ``extra`` added to a plain environment."""
    home, run = tmp_path / 'home', tmp_path / 'run'
    home.mkdir(exist_ok=True)
    (run / 'inputs').mkdir(parents=True, exist_ok=True)
    (run / 'inputs/task_contract.json').write_text('{}')
    # A program in temporary storage is refused unless the test-program exemption applies.
    program = _program(tmp_path / 'tmp/worker-bin')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'PYTHONPATH': SRC, 'PYTHONDONTWRITEBYTECODE': '1',
           'RAVEL_STATE_DIR': str(tmp_path / 'state'), 'TMPDIR': str(tmp_path / 'tmp'), **extra}
    done = subprocess.run([sys.executable, '-B', '-c', PROBE, str(home), str(run), str(program)], env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.splitlines()[-1]), home


def _worker_domain(tmp_path):
    """The directory and marker file a worker creates to imitate a test lock domain."""
    forged = tmp_path / 'worker-domain'
    forged.mkdir()
    (forged / ml.TEST_MARKER).write_text('made by a worker\n')
    return forged


def _assert_refused_everywhere(outcome, home, forged):
    for name in ('domain', 'machine_dir', 'unbound_lease', 'custody', 'launch', 'trusted_program'):
        assert outcome[name][0] == 'refused', (name, outcome[name])
    # Nothing was written in the forged domain, and the machine directory was never created.
    assert sorted(p.name for p in forged.iterdir()) == [ml.TEST_MARKER]
    assert not (home / '.local').exists()


def test_forged_variables_and_a_worker_made_marker_are_refused_in_a_fresh_process(tmp_path):
    forged = _worker_domain(tmp_path)
    outcome, home = _probe(tmp_path, {ml.TEST_ENV: str(forged), ml.RUNNER_ENV: 'forged::test (call)',
                                      'RAVEL_TEST_TRUSTED_BIN': str(tmp_path / 'tmp/worker-bin')})
    _assert_refused_everywhere(outcome, home, forged)
    assert 'no longer selects' in outcome['domain'][2]
    assert outcome['launch'][1] == 'SteeringRefused'


@pytest.mark.parametrize('variables', ['runner-only', 'grant-without-server', 'grant-to-a-plain-file'])
def test_a_forged_runner_variable_or_grant_is_refused_in_a_fresh_process(tmp_path, variables):
    forged = _worker_domain(tmp_path)
    extra = {ml.RUNNER_ENV: 'forged::test (call)', 'RAVEL_TEST_TRUSTED_BIN': str(tmp_path / 'tmp/worker-bin')}
    if variables == 'grant-without-server':
        extra[ml.GRANT_ENV] = f'{forged}/grant.sock#{"0" * 64}'
    elif variables == 'grant-to-a-plain-file':
        private = tmp_path / 'private'
        private.mkdir(mode=0o700)
        (private / 'grant.sock').write_text(json.dumps({'domain': str(forged)}))
        extra[ml.GRANT_ENV] = f'{private}/grant.sock#{"0" * 64}'
    outcome, home = _probe(tmp_path, extra)
    _assert_refused_everywhere(outcome, home, forged)


def test_a_token_the_issuing_process_never_issued_is_refused_by_that_process(tmp_path):
    forged = _worker_domain(tmp_path)
    server = ml.test_domain_grants()
    outcome, home = _probe(tmp_path, {ml.GRANT_ENV: f'{server.address}#{"0" * 64}'})
    _assert_refused_everywhere(outcome, home, forged)
    assert 'not a test lock domain grant' in outcome['domain'][2]


def test_a_grant_from_this_harness_is_the_capability_a_child_needs(tmp_path):
    domain = ml.machine_dir()
    outcome, home = _probe(tmp_path, {ml.GRANT_ENV: os.environ[ml.GRANT_ENV]})
    assert outcome['domain'] == ['permitted', repr('test')]
    assert outcome['machine_dir'] == ['permitted', repr(domain)]
    assert outcome['unbound_lease'][0] == 'permitted'  # the test lock domain admits an unbound holder
    assert not (home / '.local').exists()


ISSUER = r'''
import sys
from pathlib import Path
from ravel.workflow import machine_lease as ml
domain = Path(sys.argv[1])
print(ml.test_domain_grants().issue(domain), flush=True)
sys.stdin.read()
'''


def test_a_grant_is_validated_by_its_live_issuing_process_and_dies_with_it(tmp_path):
    domain = tmp_path / 'issued'
    domain.mkdir()
    (domain / ml.TEST_MARKER).write_text('x')
    env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': SRC, 'PYTHONDONTWRITEBYTECODE': '1', 'HOME': str(tmp_path)}
    issuer = subprocess.Popen([sys.executable, '-B', '-c', ISSUER, str(domain)], env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    try:
        grant = issuer.stdout.readline().strip()
        outcome, _ = _probe(tmp_path, {ml.GRANT_ENV: grant})
        assert outcome['machine_dir'] == ['permitted', repr(domain)]
    finally:
        issuer.stdin.close()
        issuer.wait(timeout=60)
    forged = _worker_domain(tmp_path)
    outcome, home = _probe(tmp_path, {ml.GRANT_ENV: grant})
    _assert_refused_everywhere(outcome, home, forged)


def test_a_child_of_a_test_that_lost_its_grant_does_not_reach_the_machine_directory(tmp_path):
    forged = _worker_domain(tmp_path)
    outcome, home = _probe(tmp_path, {ml.RUNNER_ENV: os.environ[ml.RUNNER_ENV]})
    _assert_refused_everywhere(outcome, home, forged)
    assert 'no test lock domain grant' in outcome['domain'][2]


SELFTEST = r'''
import pwd, runpy, sys
home = sys.argv[1]
real = pwd.getpwuid
class Entry:
    def __init__(self, entry):
        self.entry = entry
    def __getattr__(self, name):
        return home if name == 'pw_dir' else getattr(self.entry, name)
pwd.getpwuid = lambda uid: Entry(real(uid))
sys.argv = ['stage_supervisor', '--selftest']
runpy.run_module('ravel.workflow.stage_supervisor', run_name='__main__')
'''


def test_the_supervisor_selftest_started_outside_the_test_runner_writes_nothing_to_the_machine_directory(tmp_path):
    home = tmp_path / 'home'
    home.mkdir()
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(home), 'PYTHONPATH': SRC, 'PYTHONDONTWRITEBYTECODE': '1',
           'RAVEL_STATE_DIR': str(tmp_path / 'state')}
    done = subprocess.run([sys.executable, '-B', '-c', SELFTEST, str(home)], env=env, capture_output=True,
                          text=True, timeout=300)
    assert 'PASS' in done.stdout, done.stdout + done.stderr
    assert not (home / '.local').exists()


def test_a_supervisor_child_receives_the_grant_and_no_test_runner_variable(tmp_path, monkeypatch):
    assert ml.child_env() == {ml.GRANT_ENV: os.environ[ml.GRANT_ENV]}
    # An in-process location seam cannot be handed on: the child would otherwise use the machine directory.
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    with pytest.raises(ValueError, match='cannot be handed'):
        ml.child_env()
    monkeypatch.setattr(ml, '_LOCATION', None)
    # A grant that names another domain than this process's is not handed on either.
    other = tmp_path / 'other'
    other.mkdir()
    (other / ml.TEST_MARKER).write_text('x')
    monkeypatch.setenv(ml.GRANT_ENV, ml.test_domain_grants().issue(other))
    with pytest.raises(ValueError, match='cannot be handed'):
        ml.child_env()
    source = (Path(SRC) / 'ravel/workflow/agent_worker.py').read_text()
    assert ml.RUNNER_ENV not in source and 'TEST_ENV' not in source
