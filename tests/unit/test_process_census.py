"""The job-token process census reads process environments on Linux and on macOS.

The Linux ``ps`` rejects ``-E``, so the census reads ``/proc/<pid>/environ``
there. The process table is injected as a synthetic tree, so these tests give the
same verdict on every platform.
"""
import os
import subprocess
import sys
import time
import uuid

import pytest

from ravel.workflow import machine_lease as ml


def _process(root, pid, *entries, mode=0o600):
    directory = root / str(pid)
    directory.mkdir()
    path = directory / 'environ'
    path.write_bytes(b''.join(entry.encode() + b'\0' for entry in entries))
    path.chmod(mode)
    return path


@pytest.fixture
def table(tmp_path, monkeypatch):
    """A synthetic Linux process table; the BSD ``ps`` answers as the Linux one does to ``-E``."""
    root = tmp_path / 'proc'
    root.mkdir()
    _process(root, os.getpid(), 'PATH=/usr/bin')
    monkeypatch.setattr(ml, '_PROCFS', str(root))
    monkeypatch.setattr(ml, '_ps_environments', lambda: None)
    return root


def test_the_census_reads_job_tokens_from_the_linux_process_table(table):
    first, second = uuid.uuid4().hex, uuid.uuid4().hex
    _process(table, 4101, 'PATH=/usr/bin', f'{ml.JOB_ENV}={first}', 'LANG=C')
    _process(table, 4102, f'{ml.JOB_ENV}={first}')
    _process(table, 4103, 'HOME=/nonexistent', f'{ml.JOB_ENV}={second}')
    _process(table, 4104, 'PATH=/usr/bin')
    _process(table, 4105)  # a kernel thread or a zombie: an empty environment
    (table / 'self').mkdir()
    (table / 'cpuinfo').write_text('not a process\n')
    census = ml.token_census()
    assert {token: sorted(pids) for token, pids in census.items()} == {first: [4101, 4102], second: [4103]}


def test_the_census_never_counts_the_calling_process(table):
    token = uuid.uuid4().hex
    (table / str(os.getpid()) / 'environ').write_bytes(f'{ml.JOB_ENV}={token}'.encode() + b'\0')
    _process(table, 4201, f'{ml.JOB_ENV}={token}')
    assert ml.token_census() == {token: [4201]}


def test_only_the_variable_itself_names_a_token(table):
    token = uuid.uuid4().hex
    _process(table, 4301, f'NOTE={ml.JOB_ENV}={token}')
    _process(table, 4302, f'{ml.JOB_ENV}={token}0')  # 33 hexadecimal digits: not a job token
    _process(table, 4303, f'{ml.JOB_ENV}=not-a-token')
    _process(table, 4304, f'X{ml.JOB_ENV}={token}')
    assert ml.token_census() == {}


def test_an_unreadable_or_ended_process_proves_nothing(table):
    token = uuid.uuid4().hex
    _process(table, 4401, f'{ml.JOB_ENV}={token}')
    hidden = _process(table, 4402, f'{ml.JOB_ENV}={token}', mode=0o000)
    (table / '4403').mkdir()  # the process ended between the listing and the read
    try:
        hidden.read_bytes()
    except PermissionError:
        pass
    else:
        pytest.fail('this test needs an unprivileged user: the unreadable environment was read')
    assert ml.token_census() == {token: [4401]}


def test_a_missing_process_table_makes_the_census_unknown(table, tmp_path, monkeypatch):
    monkeypatch.setattr(ml, '_PROCFS', str(tmp_path / 'absent'))
    assert ml.token_census() is None


def test_a_table_without_the_calling_process_makes_the_census_unknown(table):
    token = uuid.uuid4().hex
    _process(table, 4501, f'{ml.JOB_ENV}={token}')
    (table / str(os.getpid()) / 'environ').unlink()
    (table / str(os.getpid())).rmdir()
    assert ml.token_census() is None


def test_an_unknown_census_keeps_a_token_entry_fenced_and_a_known_one_frees_it(table):
    token = uuid.uuid4().hex
    entry = {'token': token}
    assert ml.job_processes(entry) == {}
    _process(table, 4601, f'{ml.JOB_ENV}={token}')
    assert ml.job_processes(entry) == {'token': [4601]}
    (table / str(os.getpid()) / 'environ').unlink()
    (table / str(os.getpid())).rmdir()
    assert ml.job_processes(entry) == {'token_unknown': 'census unavailable'}


def test_the_platform_selects_the_process_table():
    assert ml._PROCFS == ('/proc' if sys.platform.startswith('linux') else None)


def test_the_census_of_this_platform_finds_a_live_process_by_its_token():
    token = uuid.uuid4().hex
    proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                            env={**os.environ, ml.JOB_ENV: token})
    try:
        deadline = time.monotonic() + 20
        census = ml.token_census()
        while proc.pid not in (census or {}).get(token, []) and time.monotonic() < deadline:
            time.sleep(0.05)
            census = ml.token_census()
        assert census is not None, 'the process census is unavailable on this platform'
        assert census.get(token) == [proc.pid]
    finally:
        proc.kill()
        proc.wait()
    assert token not in ml.token_census()
