"""The public CI test matrix runs every test file exactly once, split into deterministic shards."""
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ci_shards', ROOT / 'scripts/maintenance/ci_shards.py')
ci_shards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_shards)
WORKFLOW = ROOT / '.github/workflows/ci.yml'


def matrix_shards():
    """The shard count and indices the CI test job declares."""
    text = WORKFLOW.read_text()
    job = text[text.index('\n  tests:\n'):]
    job = job[:re.search(r'\n  [\w-]+:\n', job[1:]).start() + 1]
    count = int(re.search(r'--count (\d+)', job).group(1))
    indices = [int(i) for i in re.search(r'shard: \[([\d, ]+)\]', job).group(1).split(',')]
    return job, count, indices


def long_job():
    """The CI job that runs each long test file on a runner of its own."""
    text = WORKFLOW.read_text()
    job = text[text.index('\n  long-tests:\n'):]
    match = re.search(r'\n  [\w-]+:\n', job[1:])
    return job[:match.start() + 1] if match else job


def test_the_shards_partition_the_full_test_file_list():
    job, count, indices = matrix_shards()
    files = ci_shards.test_files(ROOT)
    assert count == ci_shards.SHARDS and indices == list(range(count))
    shards = [ci_shards.shard(ci_shards.sharded(files), i, count) for i in indices]
    assert all(shards)
    combined = [f for s in shards for f in s] + list(ci_shards.LONG)
    assert sorted(combined) == files and len(combined) == len(set(combined))     # every file exactly once
    assert ci_shards.test_files(ROOT) == files and ci_shards.shard(ci_shards.sharded(files), 3, count) == shards[3]   # deterministic
    for index in indices:
        assert ci_shards.selected(index=index, count=count) == shards[index]


def test_each_long_file_runs_in_its_own_job_with_a_bounded_file_time():
    job = long_job()
    declared = re.search(r'file: \[([^\]]+)\]', job).group(1).split(',')
    assert [name.strip() for name in declared] == list(ci_shards.LONG)
    assert set(ci_shards.LONG) <= set(ci_shards.test_files(ROOT))
    assert 'tests/unit/test_wms_retry.py' in ci_shards.LONG
    limit = int(re.search(r'timeout-minutes: (\d+)', job).group(1))
    file_seconds = int(re.search(r'--long \$\{\{ matrix.file \}\} --run --file-timeout (\d+)', job).group(1))
    assert file_seconds + 20 * 60 <= limit * 60      # the file stops, and reports, before the job limit
    assert 'fail-fast: false' in job and 'sandbox.probe(' in job
    assert 'python -m pip install --require-hashes -r requirements-replay.lock' in job
    assert_complete_profile_install(job)
    assert 'bash scripts/maintenance/install-git-hooks.sh' in job
    for index in range(ci_shards.SHARDS):
        assert not set(ci_shards.LONG) & set(ci_shards.selected(index=index, count=ci_shards.SHARDS))


def test_a_long_selection_must_name_a_declared_long_file():
    with pytest.raises(ValueError):
        ci_shards.selected(long='tests/unit/test_ci_shards.py')
    assert ci_shards.selected(long=ci_shards.LONG[0]) == [ci_shards.LONG[0]]


def test_the_file_list_is_what_pytest_collects_below_tests():
    files = set(ci_shards.test_files(ROOT))
    expected = {p.relative_to(ROOT).as_posix() for pattern in ('test_*.py', '*_test.py')
                for p in (ROOT / 'tests').rglob(pattern)
                if not any(part.startswith('.') for part in p.relative_to(ROOT).parts)}
    assert files == expected
    assert 'tests/unit/test_ci_shards.py' in files and all(f.startswith('tests/') for f in files)


def test_each_shard_job_runs_isolated_files_with_a_time_limit_and_the_install_steps():
    job, count, _ = matrix_shards()
    assert re.search(r'timeout-minutes: 150\b', job)
    assert 'fail-fast: false' in job
    assert count == ci_shards.SHARDS and f'(shard ${{{{ matrix.shard }}}} of {count})' in job
    assert re.search(rf'ci_shards.py --index \$\{{\{{ matrix.shard \}}\}} --count {count} --run --file-timeout \d+', job)
    file_seconds = int(re.search(rf'--count {count} --run --file-timeout (\d+)', job).group(1))
    assert file_seconds + 20 * 60 <= 150 * 60
    assert 'python -m pip install --require-hashes -r requirements-replay.lock' in job
    assert_complete_profile_install(job)
    assert 'sudo apt-get install -y bubblewrap' in job
    assert 'sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0' in job
    assert 'sandbox.probe(' in job
    assert 'bash scripts/maintenance/install-git-hooks.sh' in job


def assert_complete_profile_install(job):
    """The full profile installs the checkout; no second package build is needed."""
    assert 'python -m pip freeze > "$RUNNER_TEMP/replay-constraints.txt"' in job
    assert job.count('python -m pip install -c "$RUNNER_TEMP/replay-constraints.txt" -r "$RUNNER_TEMP/requirements-ci.txt"') == 1
    requirements = (ROOT / 'requirements-full.txt').read_bytes()
    assert requirements.splitlines().count(b'.') == 1
    projection = [line.strip() for line in job.splitlines() if 'sed ' in line]
    assert len(projection) == 1
    command, destination = projection[0].split(' > ')
    assert destination == '"$RUNNER_TEMP/requirements-ci.txt"'
    projected = subprocess.run(shlex.split(command), cwd=ROOT, capture_output=True, check=True).stdout
    # Execute CI's actual projection: every other requirement and comment stays
    # byte-identical, and isolated workers retain their source installation.
    assert projected == requirements.replace(b'\n.\n', b'\n-e .\n')
    assert projected.splitlines().count(b'-e .') == 1
    installs = [line.strip() for line in job.splitlines() if 'python -m pip install ' in line]
    assert len(installs) == 2  # locked statistics layer, then complete profile and editable package
    assert 'python -m pip check' in job


# Seconds of a job before its pytest step starts: checkout, installs and the sandbox probe took about
# three to five minutes on the hosted runners.
SETUP_SECONDS = 300


def test_each_shard_is_expected_to_finish_at_least_thirty_percent_under_its_limits():
    """Hosted-runner seconds per file (``ci_seconds``) bound each shard, each ordinary file and each long file."""
    job, count, indices = matrix_shards()
    job_limit = int(re.search(r'timeout-minutes: (\d+)', job).group(1)) * 60
    file_limit = int(re.search(r'--count \d+ --run --file-timeout (\d+)', job).group(1))
    long_job_text = long_job()
    long_job_limit = int(re.search(r'timeout-minutes: (\d+)', long_job_text).group(1)) * 60
    long_file_limit = int(re.search(r'--run --file-timeout (\d+)', long_job_text).group(1))
    durations = ci_shards.ci_seconds()
    files = [f for f in ci_shards.sharded(ci_shards.test_files(ROOT)) if f in durations]
    assert len(files) > 1000
    loads = [sum(durations[f] for f in ci_shards.shard(files, i, count, durations)) for i in indices]
    assert max(loads) + SETUP_SECONDS <= 0.7 * job_limit, [round(load) for load in loads]
    assert max(durations[f] for f in files) <= 0.7 * file_limit
    for file in ci_shards.LONG:
        assert durations.get(file, 0) + SETUP_SECONDS <= 0.7 * min(long_job_limit, long_file_limit), file


def test_hosted_durations_come_from_ci_seconds_then_scaled_cluster_seconds(tmp_path):
    record = tmp_path / 'file_timings.json'
    record.write_text(json.dumps({'schema_version': 1, 'seconds': {'tests/a.py': 10, 'tests/b.py': 20},
                                  'ci_seconds': {'tests/b.py': 300.5, 'tests/c.py': 7}}))
    assert ci_shards.ci_seconds(record) == {'tests/a.py': 10 * ci_shards.CI_SCALE, 'tests/b.py': 300.5, 'tests/c.py': 7}
    assert ci_shards.measured_seconds(record) == {'tests/a.py': 10, 'tests/b.py': 20}
    record.write_text(json.dumps({'schema_version': 1, 'seconds': {'tests/a.py': 10}, 'ci_seconds': {'tests/../x.py': 5}}))
    with pytest.raises(ValueError):
        ci_shards.ci_seconds(record)
    record.write_text(json.dumps({'schema_version': 1, 'seconds': {'tests/a.py': 10}, 'ci_seconds': []}))
    with pytest.raises(ValueError):
        ci_shards.ci_seconds(record)


@pytest.mark.parametrize('index,count', [(-1, 8), (8, 8), (0, 0), (1, 1)])
def test_an_impossible_shard_is_refused(index, count):
    with pytest.raises(ValueError):
        ci_shards.shard(['a'], index, count)


def test_run_files_continues_after_failure_and_gives_each_file_a_fresh_process(monkeypatch):
    calls = []
    class Process:
        def __init__(self, argv, **kwargs):
            calls.append((argv, kwargs)); self.pid = 0
            assert Path(kwargs['env']['TMPDIR']).is_dir()
            assert len(kwargs['env']['TMPDIR'].encode()) < 60
            assert kwargs['start_new_session'] is True
            assert kwargs['umask'] == 0o002
        def wait(self, timeout=None):
            return 1 if len(calls) == 1 else 0
    monkeypatch.setattr(ci_shards.subprocess, 'Popen', Process)
    monkeypatch.setattr(ci_shards, '_stop_group', lambda process, grace: None)
    assert ci_shards.run_files(['tests/a.py', 'tests/b.py']) == 1
    assert [c[0][-1] for c in calls] == ['tests/a.py', 'tests/b.py']
    assert all(c[0][1:5] == ['-m', 'pytest', '-q', '-rs'] for c in calls)
    assert all(c[1]['env']['PYTHONDONTWRITEBYTECODE'] == '1' for c in calls)
    assert not Path(calls[0][1]['env']['TMPDIR']).exists()
    assert ci_shards.run_files(['tests/a.py']) == 0


def test_tracebacks_are_dumped_once_shortly_before_the_file_limit(monkeypatch):
    """No repeated mid-file dumps in a long test: one dump before the stop names a hung test."""
    assert ci_shards.traceback_seconds(None) is None
    assert ci_shards.traceback_seconds(2400) == 2280
    assert ci_shards.traceback_seconds(16200) == 16080
    assert 0 < ci_shards.traceback_seconds(8) < 8
    calls = []
    class Process:
        def __init__(self, argv, **kwargs):
            calls.append(argv); self.pid = 0
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(ci_shards.subprocess, 'Popen', Process)
    monkeypatch.setattr(ci_shards, '_stop_group', lambda process, grace: None)
    assert ci_shards.run_files(['tests/a.py'], file_timeout=2400) == 0
    assert calls[-1][-3:] == ['-o', 'faulthandler_timeout=2280', 'tests/a.py']
    assert ci_shards.run_files(['tests/a.py']) == 0
    assert not any('faulthandler' in str(arg) for arg in calls[-1])


def test_a_hung_file_is_stopped_at_its_time_limit_reported_and_counted_failed(tmp_path, capfd):
    """A real child pytest process that never finishes: the runner stops it and the next file still runs."""
    import time
    hung = tmp_path / 'test_hung.py'
    hung.write_text('import time\n\ndef test_waits_forever():\n    time.sleep(600)\n')
    quick = tmp_path / 'test_quick.py'
    quick.write_text('def test_passes(tmp_path):\n'
                     '    output = tmp_path / "mode-check"\n'
                     '    output.write_text("child umask control")\n'
                     '    assert output.stat().st_mode & 0o777 == 0o664\n')
    started = time.monotonic()
    assert ci_shards.run_files([str(hung), str(quick)], file_timeout=8, grace=3) == 1
    assert time.monotonic() - started < 120
    out = capfd.readouterr().out
    assert f'CI_FILE_END {hung} exit=timeout' in out
    assert f'CI_FILE_END {quick} exit=0' in out
    assert 'CI_SHARD_TOTAL files=2 failed=1 timed_out=1' in out
