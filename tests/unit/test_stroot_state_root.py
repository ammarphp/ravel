"""The ML exposure ledger and RDJ custody live under the machine state root, not RAVEL_STATE_DIR."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ravel.physics import ml_exposure
from ravel.workflow import machine_lease, rdj_custody

SRC = str(Path(__file__).resolve().parents[2] / 'src')
PROBE = (
    'import json, sys\n'
    'from ravel.physics import ml_exposure\n'
    'from ravel.workflow import rdj_custody\n'
    'ledger = ml_exposure.root()\n'
    'ledger.mkdir(parents=True, exist_ok=True)\n'
    '(ledger / sys.argv[1]).write_text("x")\n'
    'print(json.dumps({"ledger": str(ledger), "custody": str(rdj_custody._state()),'
    ' "seen": sorted(p.name for p in ledger.iterdir())}))\n'
)


def _probe(label, state_dir, machine_dir):
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(state_dir.parent), 'PYTHONPATH': SRC,
           'RAVEL_STATE_DIR': str(state_dir),
           machine_lease.GRANT_ENV: machine_lease.test_domain_grants().issue(machine_dir)}
    out = subprocess.run([sys.executable, '-c', PROBE, label], env=env, text=True, capture_output=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_two_state_dirs_share_one_ledger_and_one_custody_store(tmp_path, _machine_domain_dir):
    first = _probe('from-first', tmp_path / 'one' / 'state', _machine_domain_dir)
    second = _probe('from-second', tmp_path / 'two' / 'state', _machine_domain_dir)
    assert first['ledger'] == second['ledger'] == str(_machine_domain_dir / 'ml-exposure')
    assert first['custody'] == second['custody'] == str(_machine_domain_dir / 'rdj')
    assert second['seen'] == ['from-first', 'from-second']


def test_the_state_dir_alone_does_not_relocate_either_store(tmp_path, monkeypatch, _machine_domain_dir):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'elsewhere'))
    assert ml_exposure.root() == _machine_domain_dir / 'ml-exposure'
    assert rdj_custody._state() == _machine_domain_dir / 'rdj'


def test_the_retired_namespace_variable_relocates_nothing(tmp_path, monkeypatch, _machine_domain_dir):
    chosen = tmp_path / 'elsewhere'
    monkeypatch.setenv('RAVEL_STATE_DIR', str(chosen))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(chosen.resolve()))
    assert ml_exposure.root() == _machine_domain_dir / 'ml-exposure'


def test_only_the_marked_harness_domain_relocates_the_stores(tmp_path, monkeypatch, lock_domain_at):
    marked = tmp_path / 'marked'
    marked.mkdir()
    (marked / machine_lease.TEST_MARKER).write_text('x')
    lock_domain_at(marked)
    assert ml_exposure.root() == marked / 'ml-exposure'
    assert rdj_custody._state() == marked / 'rdj'
    bare = tmp_path / 'bare'
    bare.mkdir()
    with pytest.raises(ValueError, match=machine_lease.TEST_MARKER):
        lock_domain_at(bare)
    # The retired variable relocates nothing; with no harness domain it is refused.
    monkeypatch.setattr(machine_lease, '_TEST_DOMAIN', None)
    monkeypatch.delenv(machine_lease.GRANT_ENV)
    monkeypatch.setenv(machine_lease.TEST_ENV, str(marked))
    with pytest.raises(ValueError, match='no longer selects'):
        ml_exposure.root()
    with pytest.raises(ValueError, match='no longer selects'):
        rdj_custody._state()


def test_a_custody_store_inside_the_run_is_still_refused(tmp_path, lock_domain_at):
    run = tmp_path / 'run'
    marked = run / 'domain'
    marked.mkdir(parents=True)
    (marked / machine_lease.TEST_MARKER).write_text('x')
    lock_domain_at(marked)
    with pytest.raises(rdj_custody.CustodyError, match='inside the run'):
        rdj_custody.root(run)


def test_provenance_marks_the_test_domain(tmp_path, _machine_domain_dir):
    assert ml_exposure.Study('a' * 64).provenance()['test_namespace'] is True


@pytest.fixture
def _machine_domain_dir():
    return Path(machine_lease.machine_dir())
