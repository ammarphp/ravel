"""Use the source package when testing a checkout.

Subprocesses (supervised workers, backend launchers and payloads) import the same
source: ``PYTHONPATH`` is exported, so a passing run never depends on which
``ravel`` the interpreter has installed. Each test holds the machine lease in its
own marked test lock domain, never the machine's. Fixtures of module or session
scope run before the test's own domain exists; they get a domain of their scope.

The harness selects each domain in this process (``machine_lease._TEST_DOMAIN``) and
exports a grant that this process's grant server validates, so a child process works in
the domain of the fixture or test that started it. No variable or marker file selects a
domain by itself. From import until the session's domain exists, the process works in a
domain of its own, so nothing reaches the machine directory before a fixture runs.
"""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

import pytest

# LangGraph reads strict msgpack at import (R4); the graph substrate refuses to run
# without it, so the test process sets it before any test imports LangGraph.
os.environ["LANGGRAPH_STRICT_MSGPACK"] = "true"

ROOT = Path(__file__).resolve().parents[1]
SRC = str(ROOT / "src")
sys.path.insert(0, SRC)
if str(ROOT / "tests") not in sys.path:
    sys.path.append(str(ROOT / "tests"))  # machine_state_guard, importable from every test directory
os.environ["PYTHONPATH"] = os.pathsep.join([SRC, *[p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep)
                                                   if p and p != SRC]])

# A test never inherits the host session of the agent or shell that runs it: `ravel initiate`
# would otherwise register that session's run (R-50 registry) and make its enforcement surface
# read-only. Tests that need a session set one explicitly.
from ravel.workflow.approval_authority import AGENT_MARKERS

for _name in AGENT_MARKERS:
    os.environ.pop(_name, None)


from ravel.workflow import machine_lease as _machine_lease

_IMPORT_DOMAIN = Path(tempfile.mkdtemp(prefix="ravel-import-domain-"))
(_IMPORT_DOMAIN / _machine_lease.TEST_MARKER).write_text("test lock domain\n")
_machine_lease.test_domain_grants().enter(_IMPORT_DOMAIN)
atexit.register(shutil.rmtree, _IMPORT_DOMAIN, ignore_errors=True)


def _lock_domain(tmp_path_factory, name):
    path = tmp_path_factory.mktemp(name)
    (path / _machine_lease.TEST_MARKER).write_text("test lock domain\n")
    return path


def enter_lock_domain(patch, path):
    """Make ``path`` the test lock domain of this process and of the children it starts, until ``patch`` undoes it."""
    grant = _machine_lease.test_domain_grants().issue(path)
    patch.setattr(_machine_lease, "_TEST_DOMAIN", str(path))
    patch.setenv(_machine_lease.GRANT_ENV, grant)
    return path


@pytest.fixture(scope="session", autouse=True)
def _machine_lease_session_domain(tmp_path_factory):
    """The lock domain of session-scoped fixtures: pytest sets them up before any narrower fixture."""
    with pytest.MonkeyPatch.context() as patch:
        yield enter_lock_domain(patch, _lock_domain(tmp_path_factory, "machine-domain-session"))


@pytest.fixture(scope="module", autouse=True)
def _machine_lease_module_domain(tmp_path_factory, _machine_lease_session_domain):
    """The lock domain of one module's module- and class-scoped fixtures."""
    with pytest.MonkeyPatch.context() as patch:
        yield enter_lock_domain(patch, _lock_domain(tmp_path_factory, "machine-domain-module"))


@pytest.fixture(autouse=True)
def _machine_lease_test_domain(tmp_path_factory, monkeypatch, _machine_lease_module_domain):
    yield enter_lock_domain(monkeypatch, _lock_domain(tmp_path_factory, "machine-domain"))


@pytest.fixture
def lock_domain_at(monkeypatch):
    """Enter another marked test lock domain for the rest of one test."""
    return lambda path: enter_lock_domain(monkeypatch, path)


import machine_state_guard  # noqa: E402


def _record_temporary_roots():
    """Every temporary directory this process makes (``tempfile.mkdtemp`` and all built on it) is a
    root of this session: a run below one is this session's run, wherever the directory lies."""
    import tempfile
    if getattr(tempfile.mkdtemp, "ravel_recording", False):
        return
    original = tempfile.mkdtemp

    def mkdtemp(*args, **kwargs):
        path = original(*args, **kwargs)
        machine_state_guard.TEMP_ROOTS.append(path)
        return path
    mkdtemp.ravel_recording = True
    tempfile.mkdtemp = mkdtemp


_record_temporary_roots()


@pytest.fixture(autouse=True)
def _account_machine_state_untouched(tmp_path_factory, _machine_lease_test_domain):
    """Guard: no test writes into the account's real machine-state directory.

    The whole tree is stamped before the test: custody stores and their ledgers, the run
    index, the lease, its fence and the exposure ledger. Afterwards every new or changed
    entry is checked against this session's temporary roots (pytest's base directory and
    every directory ``tempfile`` made) and its process. The directory is shared with real
    runs and other sessions; a change tied to neither is theirs and is left alone.
    """
    real = machine_state_guard.account_machine_dir()
    before = machine_state_guard.tree_stamp(real)
    yield
    roots = [tmp_path_factory.getbasetemp(), *machine_state_guard.TEMP_ROOTS]
    leaks = machine_state_guard.leaks_since(real, before, roots, pids={os.getpid()})
    if leaks:
        pytest.fail("this test wrote into the account's machine-state directory; pass the test lock domain "
                    "(the validated grant of machine_lease.child_env) to every child process: " + "; ".join(leaks))


@pytest.fixture
def in_process_backend_seam(monkeypatch):
    """Explicit test-only seam: ``backend_driver.drive`` with an in-process double runs without a supervised stage.

    Production code has no such bypass; ``drive`` always requires the calling stage's
    approval. Tests that drive a double request this fixture by name.
    """
    from ravel.physics import backend_driver
    monkeypatch.setattr(backend_driver, "calling_authority",
                        lambda: {"rundir": None, "stage": None, "test_seam": "in-process backend double"})


@pytest.fixture
def engineering_session(monkeypatch):
    """Explicit inert process tests carry no host agent session or scientific authority."""
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for marker in AGENT_MARKERS:
        monkeypatch.delenv(marker, raising=False)
