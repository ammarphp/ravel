"""Shared fixtures for the transport parity suite: synthetic stubs only, never a live call."""
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
for extra in (HERE, HERE.parent / 'unit'):  # reuse the unit suites' synthetic broker and RDJ fixtures
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))


@pytest.fixture
def parity_env(tmp_path, monkeypatch):
    """Isolated state, a deterministic sandbox backend answer and no inherited session."""
    from ravel.workflow import sandbox
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    (tmp_path / 'state').mkdir()
    (tmp_path / 'home').mkdir()
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    # Whether the host has an OS sandbox is machine state; the matrix declares both answers explicitly.
    monkeypatch.setattr(sandbox, 'available', lambda: 'synthetic')
    return tmp_path
