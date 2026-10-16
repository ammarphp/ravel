"""Deterministic test-file shards for the public CI test matrix.

The CI "test suite" job runs ``python -m pytest`` once per file. A shard is every
``count``-th file of the sorted list of test files that ``pytest tests`` collects
(``test_*.py`` and ``*_test.py`` below ``tests/``, skipping the directories pytest
does not enter by default), starting at ``index``, leaving out the ``LONG`` files.
Each ``LONG`` file runs in a CI job of its own. Together the shards and the long
files partition that list: every file runs in exactly one job.

Every file has a time limit (``--file-timeout``). A file that reaches it is stopped
with its whole process group, reported as ``exit=timeout`` and counted as failed, so
a hung test cannot hold its job until the job limit.

    python scripts/maintenance/ci_shards.py --index 3 --count 8
    python scripts/maintenance/ci_shards.py --long tests/unit/test_wms_retry.py --run
"""
import argparse
from fnmatch import fnmatch
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# pytest's default norecursedirs; a directory starting with "." is skipped as well.
SKIPPED = ('*.egg', '.*', '_darcs', 'build', 'CVS', 'dist', 'node_modules', 'venv', '{arch}')
# Files that alone take a large part of a shard's time limit (about 69 and 27 minutes
# on the project cluster). Each runs in its own CI job; the shards leave them out.
LONG = ('tests/unit/test_fresh_replication.py', 'tests/unit/test_wms_retry.py')
# A test still running this many seconds before its file's time limit dumps every
# thread's traceback once, so a stopped file names the test and the line where it waited.
# The dump comes only near the limit: an asynchronous dump reads the frames of a running
# thread, which CPython does not make safe, and repeated dumps in a legitimately long
# test have crashed the test process (SIGSEGV).
TRACEBACK_MARGIN = 120


def traceback_seconds(file_timeout):
    """The per-test faulthandler delay for a file limit; none without a limit."""
    if file_timeout is None:
        return None
    return max(1, file_timeout - min(TRACEBACK_MARGIN, file_timeout // 4))


def test_files(root=ROOT):
    """Sorted POSIX paths, relative to ``root``, of every test file below ``root/tests``."""
    root = Path(root)
    found = []
    for directory, subdirectories, files in os.walk(root / 'tests'):
        subdirectories[:] = sorted(d for d in subdirectories if not any(fnmatch(d, p) for p in SKIPPED))
        for name in files:
            if name.endswith('.py') and (name.startswith('test_') or name.endswith('_test.py')):
                found.append((Path(directory) / name).relative_to(root).as_posix())
    return sorted(found)


def shard(files, index, count):
    """The ``index``-th of ``count`` shards: every ``count``-th file, starting at ``index``."""
    if type(count) is not int or count < 1 or type(index) is not int or not 0 <= index < count:
        raise ValueError('shard index must satisfy 0 <= index < count')
    return list(files)[index::count]


def sharded(files):
    """The files the eight shards divide: every file except the ``LONG`` ones."""
    return [f for f in files if f not in LONG]


def selected(index=None, count=None, long=None, root=ROOT):
    """The files one CI job runs: a shard of the ordinary files, or one declared long file."""
    if long is not None:
        if long not in LONG or long not in test_files(root):
            raise ValueError(f'not a declared long test file: {long}')
        return [long]
    return shard(sharded(test_files(root)), index, count)


def _stop_group(process, grace):
    """Interrupt the file's process group, then kill whatever is left after ``grace`` seconds."""
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def run_files(files, file_timeout=None, grace=60):
    """Run all selected files independently, preserving failures and a short socket root.

    Each file gets a fresh pytest process in a new session. At ``file_timeout``
    seconds the file's process group is interrupted (pytest prints its summary),
    killed after ``grace`` seconds, and the file counts as failed. Child processes
    use umask 0002 to expose permission assumptions, even on a restrictive host.
    """
    failed = []
    timed_out = 0
    started = time.monotonic()
    # /tmp is short on Linux and resolves to /private/tmp on macOS. Do not inherit
    # a long runner TMPDIR: AF_UNIX names have a small platform-dependent limit.
    with tempfile.TemporaryDirectory(prefix='rv-ci-', dir=Path('/tmp').resolve()) as temporary:
        env = {**os.environ, 'TMPDIR': temporary, 'PYTHONDONTWRITEBYTECODE': '1'}
        for file in files:
            before = time.monotonic()
            print(f'CI_FILE_START {file}', flush=True)
            dump = traceback_seconds(file_timeout)
            options = ['-o', f'faulthandler_timeout={dump}'] if dump else []
            process = subprocess.Popen([sys.executable, '-m', 'pytest', '-q', '-rs', *options, file],
                                       cwd=ROOT, env=env, start_new_session=True, umask=0o002)
            try:
                status = process.wait(timeout=file_timeout)
            except subprocess.TimeoutExpired:
                print(f'CI_FILE_TIMEOUT {file} after {file_timeout} seconds; stopping its process group',
                      flush=True)
                _stop_group(process, grace)
                status = 'timeout'
                timed_out += 1
            else:
                # Children the file left behind (servers, sockets) end with it.
                _stop_group(process, 0)
            if status:
                failed.append(file)
            print(f'CI_FILE_END {file} exit={status} seconds={time.monotonic()-before:.2f}', flush=True)
    print(f'CI_SHARD_TOTAL files={len(files)} failed={len(failed)} timed_out={timed_out} '
          f'seconds={time.monotonic()-started:.2f}', flush=True)
    for file in failed:
        print(f'CI_FILE_FAILED {file}', flush=True)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--index', type=int)
    parser.add_argument('--count', type=int)
    parser.add_argument('--long', help='select one declared long test file instead of a shard')
    parser.add_argument('--run', action='store_true', help='run one pytest process per selected file')
    parser.add_argument('--file-timeout', type=int, help='seconds before a file is stopped and counted failed')
    args = parser.parse_args(argv)
    if (args.long is None) == (args.index is None or args.count is None):
        parser.error('give either --index and --count, or --long')
    try:
        files = selected(args.index, args.count, args.long)
    except ValueError as exc:
        parser.error(str(exc))
    if not files:
        parser.error('empty shard')
    if args.run:
        return run_files(files, file_timeout=args.file_timeout)
    print('\n'.join(files))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
