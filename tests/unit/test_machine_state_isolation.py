"""Test isolation of the machine-state directory.

RAVEL keeps the native-job lease and each run's custody ledgers in one fixed per-user
directory. A test runs in its own marked lock domain; these tests show that both supervisors
hand that domain to their children as a validated grant and that the conftest guard reports a run store written
into the account's directory. Inert children only.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import machine_state_guard as guard
from machine_state_guard import account_machine_dir, leaks_since, machine_state_leaks, tree_stamp

from ravel.workflow import agent_worker as worker, machine_lease, rdj_custody


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'run'
    root.mkdir()
    return root


def test_the_worker_supervisor_resolves_custody_in_the_test_domain(study):
    """A real child started with the supervisor's environment registers nothing in the account's directory."""
    ws = study / 'ws'
    (ws / 'scratch').mkdir(parents=True)
    env = worker.supervisor_env(worker.broker.ordinary(study), ws, {}, [])
    assert env[machine_lease.GRANT_ENV] == os.environ[machine_lease.GRANT_ENV]
    assert 'HOME' in env and env['HOME'] != os.environ.get('HOME')
    code = ('from ravel.workflow import machine_lease, rdj_custody\n'
            'print(machine_lease.domain()); print(rdj_custody._state())\n')
    out = subprocess.run([sys.executable, '-B', '-c', code], env=env, capture_output=True, text=True, check=True)
    domain, state = out.stdout.split()
    assert domain == 'test' and Path(state) == Path(machine_lease.machine_dir()) / 'rdj'
    assert not Path(state).is_relative_to(account_machine_dir())


# The stage supervisor's children inherit the grant from this process's environment; the grant
# itself (child_env) is covered by tests/unit/test_lock_domain_selection.py.


def test_the_guard_reports_a_run_store_written_under_the_machine_state_directory(tmp_path):
    """The conftest guard: a custody store or binding of a test's run inside the account directory is a leak."""
    real, runs = tmp_path / 'account-machine', tmp_path / 'tmp-root'
    rundir = runs / 'case' / 'run'
    rundir.mkdir(parents=True)
    (real / 'rdj').mkdir(parents=True)
    foreign = real / 'rdj' / hashlib.sha256(b'/somewhere/else/run').hexdigest()[:32]
    foreign.mkdir()
    assert machine_state_leaks(real, [runs]) == []
    leaked = real / 'rdj' / hashlib.sha256(str(rundir.resolve()).encode()).hexdigest()[:32]
    leaked.mkdir()
    [found] = machine_state_leaks(real, [runs])
    assert str(leaked) in found and str(rundir.resolve()) in found
    leaked.rmdir()
    (real / 'rdj/runs.jsonl').write_text(json.dumps({'record': {'run_id': 'r', 'path': str(rundir.resolve())}}) + '\n'
                                         + json.dumps({'record': {'run_id': 'q', 'path': '/somewhere/else/run'}}) + '\n')
    [bound] = machine_state_leaks(real, [runs])
    assert 'binding' in bound and str(rundir.resolve()) in bound


def test_this_run_resolves_the_test_domain_not_the_account_directory(study):
    """Every test holds its own marked domain; custody of a run written here lands there."""
    assert machine_lease.domain() == 'test' and machine_lease.machine_dir() != account_machine_dir()
    rdj_custody.append(study, 'checks', {'check_id': 'probe', 'path': 'x', 'sha256': '0' * 64})
    store = rdj_custody.root(study)
    assert store.is_relative_to(Path(machine_lease.machine_dir())) and not store.is_relative_to(account_machine_dir())
    assert machine_state_leaks(account_machine_dir(), [study]) == []


# ---------------------------------------------------------------- the guard covers the whole machine-state tree

def store_of(real, rundir):
    return real / 'rdj' / hashlib.sha256(str(Path(rundir).resolve()).encode()).hexdigest()[:32]


@pytest.fixture
def machine(tmp_path):
    """A stand-in account directory with another run's custody store and ledger already in it."""
    real = tmp_path / 'account-machine'
    foreign = store_of(real, '/somewhere/else/run')
    foreign.mkdir(parents=True)
    (foreign / 'checks.jsonl').write_text('{"row": 1}\n')
    return real


def append(path, text):
    with path.open('a') as stream:
        stream.write(text)


def test_the_guard_sees_a_write_into_an_existing_nested_ledger(tmp_path, machine):
    """An appended ledger changes neither the store directory nor the run index; the tree stamp still sees it."""
    rundir = tmp_path / 'tmp-root/case/run'
    rundir.mkdir(parents=True)
    ledger = store_of(machine, rundir) / 'checks.jsonl'
    ledger.parent.mkdir()
    ledger.write_text('{"row": 1}\n')
    top = [(machine / 'rdj').stat().st_mtime_ns, (machine / 'rdj').stat().st_size]
    before = tree_stamp(machine)
    assert leaks_since(machine, before, [tmp_path / 'tmp-root']) == []
    append(ledger, '{"row": 2}\n')
    append(store_of(machine, '/somewhere/else/run') / 'checks.jsonl', '{"row": 2}\n')
    assert [(machine / 'rdj').stat().st_mtime_ns, (machine / 'rdj').stat().st_size] == top
    assert not (machine / 'rdj/runs.jsonl').exists()
    [found] = leaks_since(machine, before, [tmp_path / 'tmp-root'])
    assert str(ledger.parent) in found and str(rundir.resolve()) in found
    # Another run's ledger changed too; it is not this session's and is not reported.
    assert leaks_since(machine, before, [tmp_path / 'unrelated']) == []
    assert leaks_since(machine, tree_stamp(machine), [tmp_path / 'tmp-root']) == []


@pytest.mark.parametrize('name', [machine_lease.RECORD_NAME, machine_lease.FENCE_NAME, machine_lease.ACTIONS_NAME,
                                  'ml-exposure/ledger.jsonl'])
def test_the_guard_sees_a_lease_or_ledger_file_this_session_wrote(tmp_path, machine, name):
    rundir = tmp_path / 'tmp-root/run'
    rundir.mkdir(parents=True)
    target = machine / name
    target.parent.mkdir(parents=True, exist_ok=True)
    before = tree_stamp(machine)
    # Another holder's record, for another run: a change, and not this session's.
    target.write_text(json.dumps({'pid': 1, 'rundir': '/somewhere/else/run'}) + '\n')
    assert leaks_since(machine, before, [tmp_path / 'tmp-root'], pids={os.getpid()}) == []
    # A record that names a run of this session, whoever holds it.
    target.write_text(json.dumps({'pid': 1, 'rundir': str(rundir.resolve())}) + '\n')
    [found] = leaks_since(machine, before, [tmp_path / 'tmp-root'], pids={os.getpid()})
    assert str(target) in found and str((tmp_path / 'tmp-root').resolve()) in found
    # A record this process holds, for a run somewhere else.
    target.write_text(json.dumps({'pid': os.getpid(), 'rundir': '/somewhere/else/run'}) + '\n')
    [held] = leaks_since(machine, before, [tmp_path / 'tmp-root'], pids={os.getpid()})
    assert str(target) in held and 'process of this session' in held


def test_a_run_outside_pytests_base_directory_is_a_candidate(tmp_path, machine):
    """The session records every temporary directory it makes; a run under one of them is its own."""
    import tempfile
    made = Path(tempfile.mkdtemp())
    with tempfile.TemporaryDirectory() as scoped:
        assert str(made) in guard.TEMP_ROOTS and scoped in guard.TEMP_ROOTS
    assert not made.resolve().is_relative_to(tmp_path.resolve())
    rundir = made / 'run'
    rundir.mkdir()
    before = tree_stamp(machine)
    store_of(machine, rundir).mkdir()
    assert leaks_since(machine, before, [tmp_path / 'unrelated']) == []
    [found] = leaks_since(machine, before, [tmp_path / 'unrelated', *guard.TEMP_ROOTS])
    assert str(rundir.resolve()) in found


def test_a_run_made_long_before_the_test_is_still_a_candidate(tmp_path, machine):
    """A run from a session- or module-scoped fixture is old when the test starts; no time window drops it."""
    rundir = tmp_path / 'tmp-root/shared-fixture/run'
    rundir.mkdir(parents=True)
    for path in (rundir, rundir.parent, rundir.parent.parent):
        os.utime(path, (1_000_000_000, 1_000_000_000))
    before = tree_stamp(machine)
    store_of(machine, rundir).mkdir()
    [found] = leaks_since(machine, before, [tmp_path / 'tmp-root'])
    assert str(rundir.resolve()) in found


LEAKING_TESTS = '''
import hashlib, json, os, tempfile
from pathlib import Path

REAL = Path(os.environ['STAND_IN_ACCOUNT_MACHINE'])
RUN = Path(tempfile.mkdtemp()) / 'run'
RUN.mkdir()
STORE = REAL / 'rdj' / hashlib.sha256(str(RUN.resolve()).encode()).hexdigest()[:32]
STORE.mkdir(parents=True, exist_ok=True)
(STORE / 'checks.jsonl').write_text('{"row": 1}' + chr(10))


def test_clean():
    assert REAL.is_dir()


def test_appends_to_an_existing_nested_ledger():
    with (STORE / 'checks.jsonl').open('a') as stream:
        stream.write('{"row": 2}' + chr(10))


def test_writes_the_lease_record():
    (REAL / 'native-job.json').write_text(json.dumps({'pid': os.getpid(), 'rundir': '/somewhere/else/run'}))


def test_clean_again():
    assert REAL.is_dir()
'''

STAND_IN_PLUGIN = '''
import os
from pathlib import Path
import machine_state_guard

machine_state_guard.account_machine_dir = lambda: Path(os.environ['STAND_IN_ACCOUNT_MACHINE'])
'''


def test_the_conftest_guard_fails_exactly_the_tests_that_touch_the_machine_state_tree(tmp_path):
    """End to end: the repository's own conftest, loaded as a plugin, over a stand-in account directory."""
    tests = Path(__file__).resolve().parents[1]
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'test_leaks.py').write_text(LEAKING_TESTS)
    (project / 'stand_in_account.py').write_text(STAND_IN_PLUGIN)
    real = tmp_path / 'account-machine'
    real.mkdir()
    env = {**os.environ, 'STAND_IN_ACCOUNT_MACHINE': str(real),
           'PYTHONPATH': os.pathsep.join([str(project), str(tests), os.environ['PYTHONPATH']])}
    done = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-p', 'stand_in_account',
                           '-p', 'conftest', '--rootdir', str(project), '--basetemp', str(tmp_path / 'base'),
                           '-rE', str(project / 'test_leaks.py')], env=env, cwd=project, capture_output=True, text=True)
    out = done.stdout + done.stderr
    assert done.returncode == 1, out
    assert '4 passed, 2 errors' in out, out
    failed = sorted(line.split('::')[1].split(' ')[0] for line in out.splitlines() if line.startswith('ERROR '))
    assert failed == ['test_appends_to_an_existing_nested_ledger', 'test_writes_the_lease_record'], out
    assert "wrote into the account's machine-state directory" in out
