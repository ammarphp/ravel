"""Every fixture scope works in a test lock domain, never in the machine's lease directory.

pytest sets up session- and module-scoped fixtures before a test's own
function-scoped lock domain exists. A supervised stage such a fixture runs (in
this process or in a child) must not reach the per-user machine directory.
"""
import os
from pathlib import Path
import pwd
import subprocess
import sys

import pytest

from ravel.workflow import machine_lease as ml

MACHINE = Path(pwd.getpwuid(os.getuid()).pw_dir) / '.local/state/ravel/machine'
PROBE = ('from ravel.workflow import machine_lease as ml\n'
         'print(ml.domain()); print(ml.machine_dir())\n')


def _here():
    return ml.domain(), Path(ml.machine_dir())


def _child():
    lines = subprocess.run([sys.executable, '-B', '-c', PROBE], check=True, capture_output=True, text=True,
                           timeout=120).stdout.splitlines()
    return lines[0], Path(lines[1])


@pytest.fixture(scope='session')
def session_scope():
    return _here(), _child()


@pytest.fixture(scope='module')
def module_scope():
    with ml.held('module-scoped fixture') as lease:
        record = ml.holder()
    assert record['lease_id'] == lease.lease_id and record['domain'] == 'test'
    return _here(), _child()


class TestClassScope:
    @pytest.fixture(scope='class')
    def class_scope(self):
        return _here(), _child()

    def test_a_class_scoped_fixture_uses_the_module_domain(self, class_scope, module_scope):
        assert class_scope == module_scope


def _assert_test_domain(observed):
    domain, path = observed
    assert domain == 'test'
    assert (path / ml.TEST_MARKER).is_file()
    assert path != MACHINE and not path.is_relative_to(MACHINE) and not MACHINE.is_relative_to(path)


def test_every_fixture_scope_works_in_a_test_lock_domain(session_scope, module_scope):
    function_scope = _here(), _child()
    for in_process, child in (session_scope, module_scope, function_scope):
        _assert_test_domain(in_process)
        assert child == in_process  # a child process works in the domain of the fixture that started it
    # pytest sets a session-scoped fixture up when a test first asks for it; by then a module's
    # domain may already be current. Either way it is not the domain of a single test.
    assert function_scope[0][1] not in (session_scope[0][1], module_scope[0][1])


def test_the_session_the_module_and_the_test_each_have_a_domain(
        _machine_lease_session_domain, _machine_lease_module_domain, _machine_lease_test_domain, module_scope):
    domains = [_machine_lease_session_domain, _machine_lease_module_domain, _machine_lease_test_domain]
    assert len({str(path) for path in domains}) == 3
    for path in domains:
        _assert_test_domain(('test', Path(path)))
    assert module_scope[0][1] == Path(_machine_lease_module_domain)
    assert Path(ml.machine_dir()) == Path(_machine_lease_test_domain)


def test_a_lease_taken_by_a_module_scoped_fixture_is_recorded_in_its_domain(module_scope):
    directory = module_scope[0][1]
    assert (directory / ml.LOCK_NAME).is_file()
    assert not (Path(ml.machine_dir()) / ml.LOCK_NAME).exists()  # this test's own domain was not touched


def test_the_domain_of_a_wider_scope_returns_after_a_test(module_scope, monkeypatch):
    # The function-scoped domain is undone at teardown; this process and its children then work in the module's again.
    current, grant = ml._TEST_DOMAIN, os.environ[ml.GRANT_ENV]
    assert Path(current) == Path(ml.machine_dir()) != module_scope[0][1]
    monkeypatch.undo()
    try:
        assert Path(ml.machine_dir()) == module_scope[0][1]
        assert _child() == ('test', module_scope[0][1])
    finally:
        monkeypatch.setattr(ml, '_TEST_DOMAIN', current)
        monkeypatch.setenv(ml.GRANT_ENV, grant)
