"""The public CI test matrix runs every test file exactly once, split into deterministic shards."""
import importlib.util
from pathlib import Path
import re

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


def test_the_shards_partition_the_full_test_file_list():
    job, count, indices = matrix_shards()
    files = ci_shards.test_files(ROOT)
    assert count == 8 and indices == list(range(count))
    shards = [ci_shards.shard(files, i, count) for i in indices]
    assert all(shards)
    combined = [f for s in shards for f in s]
    assert sorted(combined) == files and len(combined) == len(set(combined))     # every file exactly once
    assert ci_shards.test_files(ROOT) == files and ci_shards.shard(files, 3, count) == shards[3]   # deterministic


def test_the_file_list_is_what_pytest_collects_below_tests():
    files = set(ci_shards.test_files(ROOT))
    expected = {p.relative_to(ROOT).as_posix() for pattern in ('test_*.py', '*_test.py')
                for p in (ROOT / 'tests').rglob(pattern)
                if not any(part.startswith('.') for part in p.relative_to(ROOT).parts)}
    assert files == expected
    assert 'tests/unit/test_ci_shards.py' in files and all(f.startswith('tests/') for f in files)


def test_each_shard_job_runs_one_pytest_process_with_a_time_limit_and_the_install_steps():
    job, count, _ = matrix_shards()
    assert re.search(r'timeout-minutes: 150\b', job)
    assert 'fail-fast: false' in job
    assert job.count('python -m pytest') == 1 and 'ci_shards.py --index ${{ matrix.shard }}' in job
    assert 'python -m pip install -e . pytest==8.3.5' in job
    assert 'bash scripts/maintenance/install-git-hooks.sh' in job


@pytest.mark.parametrize('index,count', [(-1, 8), (8, 8), (0, 0), (1, 1)])
def test_an_impossible_shard_is_refused(index, count):
    with pytest.raises(ValueError):
        ci_shards.shard(['a'], index, count)
