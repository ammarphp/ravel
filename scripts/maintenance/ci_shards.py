"""Deterministic test-file shards for the public CI test matrix.

The CI "test suite" job runs ``python -m pytest`` once per shard. A shard is every
``count``-th file of the sorted list of test files that ``pytest tests`` collects
(``test_*.py`` and ``*_test.py`` below ``tests/``, skipping the directories pytest
does not enter by default), starting at ``index``. Together the shards partition
that list: every file runs in exactly one shard.

    python scripts/maintenance/ci_shards.py --index 3 --count 8
"""
import argparse
from fnmatch import fnmatch
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# pytest's default norecursedirs; a directory starting with "." is skipped as well.
SKIPPED = ('*.egg', '.*', '_darcs', 'build', 'CVS', 'dist', 'node_modules', 'venv', '{arch}')


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--count', type=int, required=True)
    args = parser.parse_args(argv)
    selected = shard(test_files(), args.index, args.count)
    if not selected:
        parser.error('empty shard')
    print('\n'.join(selected))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
