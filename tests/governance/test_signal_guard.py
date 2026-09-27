"""The test-session signal guard (conftest.py) refuses signals to processes the tests did not start."""
import os
import signal
import subprocess
import sys
import time

import pytest

from governance import isolation


def test_guard_refuses_an_ancestor_and_an_older_process_and_allows_a_child():
    refused = os.kill.__globals__["REFUSED"]                # the record of the guard installed by conftest.py
    before = len(refused)
    try:
        with pytest.raises(PermissionError, match="ancestor"):
            os.kill(os.getppid(), signal.SIGCONT)          # harmless even if it were delivered
        with pytest.raises(PermissionError, match="pid 0/1"):
            os.kill(1, signal.SIGCONT)
        with pytest.raises(PermissionError, match="own group"):
            os.killpg(os.getpgrp(), signal.SIGCONT)
        os.kill(os.getppid(), 0)                            # existence probes stay allowed
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        os.kill(child.pid, signal.SIGKILL)                  # a process this session started: allowed
        assert child.wait() == -signal.SIGKILL
    finally:
        del refused[before:]                                # these refusals were this test's own probes


def test_guard_reads_processes_through_the_reader_it_bound_before_any_test(monkeypatch):
    """Review of eval/fix-isolation (minor 3): the guard resolved isolation._proc_info/_start_time, and through
    them isolation._proc_read, at call time, so a test that patched those readers (step_the_wall_clock, a
    SYNTHETIC census) also changed what the guard refused. It reads through the reader conftest.py bound at
    import now. Nothing is signalled here: _refusal is the guard's decision."""
    refusal = os.kill.__globals__["_refusal"]
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        assert refusal("kill", child.pid, signal.SIGKILL) is None           # this session's child
        parent = os.getppid()
        assert refusal("kill", parent, signal.SIGCONT) == "the test process or an ancestor"
        # SYNTHETIC readers: every process a child of pid 1, started either long ago or just now
        for start in (0.0, time.time()):
            monkeypatch.setattr(isolation, "_proc_read", lambda pid, s=start: (1, s, ("synthetic", pid, 0)))
            monkeypatch.setattr(isolation, "_proc_info", lambda pid, s=start: (1, s))
            monkeypatch.setattr(isolation, "_start_time", lambda pid, s=start: s)
            # before: an ancient-looking child was refused, and a young-looking parent (no longer an ancestor
            # in the patched view) was allowed
            assert refusal("kill", child.pid, signal.SIGKILL) is None
            assert refusal("kill", parent, signal.SIGCONT) == "the test process or an ancestor"
    finally:
        monkeypatch.undo()                                                    # the real readers before cleanup
        child.kill()
        child.wait()
