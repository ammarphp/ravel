"""Make the evaluation harness importable as the `governance` package, and keep its tests from
ever signalling a process they did not start.

The harness launches, times out and kills subject processes. On 2026-09-25 a census defect made a
test kill every process of the logged-in user, twice
(docs/development/evaluation-study/incident-2026-09-25.md). The production launcher now fails
closed; this guard is a second, independent layer for the test process itself: any os.kill or
os.killpg aimed at pid 0/1, the test process's own group or ancestors, or a process that started
before this test session is refused (PermissionError, which the harness treats like EPERM) and
recorded, and the session then fails. Signal 0 (an existence probe) is always allowed.
"""
from pathlib import Path
import os
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
for entry in (ROOT / "benchmarks", ROOT / "src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from governance import isolation  # noqa: E402  (after the path setup above)

SESSION_START = time.time()
REFUSED = []
_REAL_KILL, _REAL_KILLPG = os.kill, os.killpg
# The process reader and its read error, bound once before any test runs: tests replace isolation's readers
# (step_the_wall_clock patches _proc_read; others patch _start_time), and this guard must keep refusing what it
# refuses whatever a test makes the harness see.
_PROC_READ, _READ_ERROR_S = isolation._proc_read, isolation.START_READ_ERROR_S


def _ancestors():
    pids, pid = set(), os.getpid()
    while pid > 1 and pid not in pids:
        pids.add(pid)
        info = _PROC_READ(pid)
        pid = info[0] if info else 0
    return pids


def _refusal(kind, target, sig):
    if sig == 0:
        return None
    if target <= 1:
        return "pid 0/1 or a broadcast"
    if kind == "killpg" and target == os.getpgrp():
        return "the test process's own group"
    if target in _ancestors():
        return "the test process or an ancestor"
    info = _PROC_READ(target)   # its start time is early by up to START_READ_ERROR_S on Linux
    start = None if info is None else info[1]
    if start is not None and start < SESSION_START - _READ_ERROR_S:
        return "a process that predates this test session"
    return None


def _guarded(kind, real):
    def call(target, sig):
        reason = _refusal(kind, target, sig)
        if reason:
            REFUSED.append(f"{kind}({target}, {sig}): {reason}")
            raise PermissionError(1, f"test signal guard refused {kind}({target}, {sig}): {reason}")
        return real(target, sig)
    return call


os.kill, os.killpg = _guarded("kill", _REAL_KILL), _guarded("killpg", _REAL_KILLPG)


def pytest_configure(config):
    # Oracle cross-checks (tests/governance/test_oracle_crosscheck.py). The oracles themselves never
    # import pyhf or ravel; these marks label the tests that do, so they can be selected or excluded.
    config.addinivalue_line("markers", "kernel_crosscheck: compares an independent oracle with the RAVEL "
                            "kernel or stock pyhf (imports them; skips when they are unavailable)")
    config.addinivalue_line("markers", "diagnostic: records a diagnostic measurement (toy MC, sensitivity), "
                            "not a correctness criterion of the oracle or the kernel")


def pytest_sessionfinish(session, exitstatus):
    if REFUSED:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        print(f"\ntest signal guard: {len(REFUSED)} signal(s) to processes the tests did not start were "
              "refused; the harness tried to reach outside its own subjects:", file=sys.stderr)
        for line in REFUSED[:20]:
            print(f"  {line}", file=sys.stderr)
