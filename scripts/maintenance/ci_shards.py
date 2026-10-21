"""Deterministic test-file shards for the public CI test matrix.

The CI "test suite" job runs ``python -m pytest`` once per file. Shards greedily
balance committed measured file durations from the test files pytest collects
(``test_*.py`` and ``*_test.py`` below ``tests/``, skipping the directories pytest
does not enter by default), leaving out the ``LONG`` files.
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
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TIMINGS = ROOT / 'tests/file_timings.json'
# pytest's default norecursedirs; a directory starting with "." is skipped as well.
SKIPPED = ('*.egg', '.*', '_darcs', 'build', 'CVS', 'dist', 'node_modules', 'venv', '{arch}')
# Files that alone take a large part of a shard's time limit (about 27 to 71 minutes
# each on the project cluster). Each runs in its own CI job; the shards leave them out.
LONG = ('tests/unit/test_fresh_replication.py', 'tests/unit/test_wms_retry.py',
        'tests/unit/test_research_full_cycle.py', 'tests/unit/test_research_full_cycle_outer.py',
        'tests/unit/test_research_full_cycle_receipt.py')
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


def measured_seconds(path=TIMINGS):
    """Read measured wall seconds; absent files keep the conservative unknown cost."""
    record = json.loads(Path(path).read_text())
    if (not isinstance(record, dict) or record.get('schema_version') != 1
            or not isinstance(record.get('seconds'), dict)):
        raise ValueError('invalid measured timing census')
    for file, seconds in record['seconds'].items():
        if (not isinstance(file, str) or not file.startswith('tests/')
                or '..' in Path(file).parts or not file.endswith('.py')
                or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0):
            raise ValueError(f'invalid measured file duration: {file}')
    return record['seconds']


def prune_timings(root=ROOT):
    """Retain historical measurements for the current declared public test population."""
    import importlib.util
    root = Path(root)
    path = root / 'tests/file_timings.json'
    measured_seconds(path)
    specification = importlib.util.spec_from_file_location('public_timing_layout', ROOT / 'src/ravel/evidence_layout.py')
    layout = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(layout)
    public = {target for source, target in layout.selected_files(root) if source == target}
    allowed = public & set(test_files(root))
    record = json.loads(path.read_text())
    before = len(record['seconds'])
    record['seconds'] = {file: seconds for file, seconds in sorted(record['seconds'].items()) if file in allowed}
    path.write_text(json.dumps(record, indent=2) + '\n')
    return {'retained': len(record['seconds']), 'removed': before - len(record['seconds'])}


def shard(files, index, count, durations=None):
    """Longest-first greedy packing, with stable path and shard-index tie breaks.

    Unknown files cost at least 60 seconds and at least the longest measured
    ordinary file. A new file cannot silently look cheap or disappear.
    """
    if type(count) is not int or count < 1 or type(index) is not int or not 0 <= index < count:
        raise ValueError('shard index must satisfy 0 <= index < count')
    durations = measured_seconds() if durations is None else durations
    files = list(files)
    if len(files) != len(set(files)):
        raise ValueError('duplicate test file')
    fallback = max([60.0, *(value for file, value in durations.items() if file not in LONG)])
    bins, totals = [[] for _ in range(count)], [0.0] * count
    for file in sorted(files, key=lambda file: (-durations.get(file, fallback), file)):
        target = min(range(count), key=lambda i: (totals[i], i))
        bins[target].append(file)
        totals[target] += durations.get(file, fallback)
    return bins[index]


def tier_files(root=ROOT, durations=None, manifest=None):
    """Partition every file once; unmeasured files and dedicated long jobs are slow."""
    files = test_files(root)
    durations = measured_seconds(Path(root) / 'tests/file_timings.json') if durations is None else durations
    if manifest is None:
        try:
            manifest = json.loads((Path(root) / 'tests/test_tiers.json').read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f'invalid test tier manifest: {exc}') from exc
    if not isinstance(manifest, dict):
        raise ValueError('invalid test tier manifest: expected an object')
    fast = manifest.get('fast')
    threshold = manifest.get('medium_max_seconds')
    if (manifest.get('schema_version') != 1 or not isinstance(fast, list)
            or any(not isinstance(file, str) for file in fast) or len(fast) != len(set(fast))
            or set(fast) - set(files) or set(fast) & set(LONG)
            or type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold <= 0):
        raise ValueError('invalid test tier manifest')
    result = {name: [] for name in ('fast', 'medium', 'slow')}
    for file in files:
        tier = ('fast' if file in fast else 'medium'
                if file not in LONG and file in durations and durations[file] <= threshold else 'slow')
        result[tier].append(file)
    return result


def sharded(files):
    """The files the eight shards divide: every file except the ``LONG`` ones."""
    return [f for f in files if f not in LONG]


def selected(index=None, count=None, long=None, root=ROOT, tier=None):
    """The files one CI job runs: a shard of the ordinary files, or one declared long file."""
    if tier is not None:
        if long is not None or index is not None or count is not None:
            raise ValueError('a tier cannot be combined with a shard or long selection')
        return tier_files(root)[tier]
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
    parser.add_argument('--tier', choices=('fast', 'medium', 'slow'), help='opt-in developer file tier')
    parser.add_argument('--run', action='store_true', help='run one pytest process per selected file')
    parser.add_argument('--prune-timings', action='store_true', help='retain measured timings for current public test files')
    parser.add_argument('--file-timeout', type=int, help='seconds before a file is stopped and counted failed')
    args = parser.parse_args(argv)
    if args.prune_timings:
        if any(value is not None for value in (args.index, args.count, args.long, args.tier, args.file_timeout)) or args.run:
            parser.error('--prune-timings is a separate maintenance action')
        print(json.dumps(prune_timings(), sort_keys=True))
        return 0
    if args.tier is None and (args.long is None) == (args.index is None or args.count is None):
        parser.error('give either --index and --count, or --long')
    try:
        files = selected(args.index, args.count, args.long, tier=args.tier)
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
