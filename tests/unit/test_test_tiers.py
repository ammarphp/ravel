"""Measured scheduling, complete file tiers and opt-in collection controls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('tier_runner', ROOT / 'scripts/maintenance/ci_shards.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_tiers_partition_every_file_once_and_keep_long_jobs():
    tiers = runner.tier_files()
    combined = [file for files in tiers.values() for file in files]
    assert sorted(combined) == runner.test_files()
    assert len(combined) == len(set(combined))
    assert all(tiers.values())
    assert set(runner.LONG) <= set(tiers['slow'])
    assert runner.selected(tier='fast') == tiers['fast']


def test_new_files_are_slow_until_they_have_a_measurement(tmp_path):
    (tmp_path / 'tests').mkdir()
    for name in ('test_core.py', 'test_known.py', 'test_new.py', 'test_heavy.py'):
        (tmp_path / 'tests' / name).touch()
    manifest = {'schema_version': 1, 'fast': ['tests/test_core.py'], 'medium_max_seconds': 60}
    tiers = runner.tier_files(tmp_path, {'tests/test_known.py': 20, 'tests/test_heavy.py': 61}, manifest)
    assert tiers == {'fast': ['tests/test_core.py'], 'medium': ['tests/test_known.py'],
                     'slow': ['tests/test_heavy.py', 'tests/test_new.py']}


@pytest.mark.parametrize('change', [
    {'fast': ['tests/unit/test_ci_shards.py'] * 2},
    {'fast': ['tests/test_absent.py']}, {'fast': [None]},
    {'fast': [runner.LONG[0]]}, {'medium_max_seconds': False},
    {'medium_max_seconds': float('inf')}, {'schema_version': 2},
])
def test_invalid_manifest_is_refused(change):
    manifest = {'schema_version': 1, 'fast': [], 'medium_max_seconds': 60, **change}
    with pytest.raises(ValueError, match='tier manifest'):
        runner.tier_files(manifest=manifest)


def test_greedy_packing_balances_measured_work_and_is_order_independent():
    durations = {'a': 9, 'b': 8, 'c': 7, 'd': 6}
    shards = [runner.shard(durations, i, 2, durations) for i in range(2)]
    assert shards == [['a', 'd'], ['b', 'c']]
    assert runner.shard(reversed(durations), 0, 2, durations) == shards[0]
    assert [sum(durations[f] for f in s) for s in shards] == [15, 15]


def test_unknown_duration_is_conservative_and_ties_are_stable():
    assert runner.shard(['c', 'a', 'b'], 0, 2, {'b': 2}) == ['a', 'b']
    assert runner.shard(['c', 'a', 'b'], 1, 2, {'b': 2}) == ['c']
    assert runner.shard(['b', 'a'], 0, 2, {}) == ['a']
    assert runner.shard(['new', 'known'], 0, 2, {'known': 100}) == ['known']
    with pytest.raises(ValueError, match='duplicate'):
        runner.shard(['a', 'a'], 0, 2, {})


@pytest.mark.parametrize('seconds', [True, -1, 0, '2', float('nan'), float('inf')])
def test_invalid_measured_duration_is_refused(tmp_path, seconds):
    path = tmp_path / 'timings.json'
    path.write_text(json.dumps({'schema_version': 1, 'seconds': {'tests/test_example.py': seconds}}))
    with pytest.raises(ValueError, match='duration'):
        runner.measured_seconds(path)


@pytest.mark.parametrize('record', [None, [], 'invalid', 1])
def test_non_object_timing_census_is_refused(tmp_path, record):
    path = tmp_path / 'timings.json'
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='timing census'):
        runner.measured_seconds(path)


def test_committed_census_has_measured_provenance_and_positive_seconds():
    record = json.loads(runner.TIMINGS.read_text())
    assert len(record['provenance']['source_sha256']) == 64
    assert 'measured' in record['provenance']['source']
    assert runner.measured_seconds()


@pytest.mark.parametrize('kwargs', [{'index': 0, 'count': 8}, {'long': runner.LONG[0]}])
def test_tier_selection_cannot_silently_drop_another_selection(kwargs):
    with pytest.raises(ValueError, match='combined'):
        runner.selected(tier='fast', **kwargs)


def test_collection_filters_before_import_and_marks_files(request):
    plugin = request.config.pluginmanager.get_plugin(str(ROOT / 'tests/conftest.py'))
    tiers = runner.tier_files()
    config = SimpleNamespace(_ravel_file_tiers={file: tier for tier, files in tiers.items() for file in files},
                             getoption=lambda option: 'fast')
    fast, other = ROOT / tiers['fast'][0], ROOT / tiers['slow'][0]
    assert plugin.pytest_ignore_collect(other, config) is True
    assert plugin.pytest_ignore_collect(fast, config) is None
    assert plugin.pytest_ignore_collect(ROOT / 'tests', config) is None
    deselected = []
    config.hook = SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items))
    marks = []
    items = [SimpleNamespace(path=fast, add_marker=marks.append),
             SimpleNamespace(path=other, add_marker=marks.append)]
    plugin.pytest_collection_modifyitems(config, items)
    assert len(items) == len(deselected) == 1
    assert [mark.name for mark in marks] == ['fast', 'slow']
    config.getoption = lambda option: None
    assert plugin.pytest_ignore_collect(other, config) is None
    original = [*items, *deselected]
    plugin.pytest_collection_modifyitems(config, original)
    assert len(original) == 2


@pytest.fixture
def synthetic_tier_checkout(tmp_path, monkeypatch, request):
    plugin = request.config.pluginmanager.get_plugin(str(ROOT / 'tests/conftest.py'))
    (tmp_path / 'scripts/maintenance').mkdir(parents=True)
    (tmp_path / 'scripts/maintenance/ci_shards.py').write_text(Path(runner.__file__).read_text())
    (tmp_path / 'tests').mkdir()
    for name in ('core', 'known', 'new'):
        (tmp_path / f'tests/test_{name}.py').touch()
    (tmp_path / 'tests/file_timings.json').write_text(json.dumps({
        'schema_version': 1, 'seconds': {'tests/test_known.py': 20}}))
    manifest = tmp_path / 'tests/test_tiers.json'
    manifest.write_text(json.dumps({
        'schema_version': 1, 'fast': ['tests/test_core.py'], 'medium_max_seconds': 60}))
    monkeypatch.setattr(plugin, 'ROOT', tmp_path)
    return plugin, tmp_path, manifest


def _collection_config(tier=None, markexpr=''):
    warnings, deselected = [], []
    config = SimpleNamespace(
        getoption=lambda option: tier if option == '--test-tier' else markexpr,
        issue_config_time_warning=lambda warning, stacklevel: warnings.append(warning),
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)))
    return config, warnings, deselected


def _break_tier_manifest(manifest, failure):
    if failure == 'missing-manifest':
        manifest.unlink()
    else:
        manifest.write_text({
            'malformed-json': '{',
            'non-object': '[]',
            'missing-fast-file': json.dumps({
                'schema_version': 1, 'fast': ['tests/test_removed.py'], 'medium_max_seconds': 60}),
        }[failure])


@pytest.mark.parametrize('failure', [
    'malformed-json', 'non-object', 'missing-fast-file', 'missing-manifest'])
def test_invalid_manifest_keeps_ordinary_collection_complete(synthetic_tier_checkout, failure):
    plugin, root, manifest = synthetic_tier_checkout
    _break_tier_manifest(manifest, failure)
    config, warnings, deselected = _collection_config()
    plugin.pytest_configure(config)
    assert len(warnings) == 1
    assert isinstance(warnings[0], pytest.PytestConfigWarning)
    assert 'tier manifest' in str(warnings[0])
    assert 'collecting all requested tests without tier marks' in str(warnings[0])
    files = [root / file for file in runner.test_files(root)]
    for requested in (files, [files[0]]):  # full and explicit-file collection
        marks = []
        items = [SimpleNamespace(path=file, add_marker=marks.append) for file in requested]
        assert all(plugin.pytest_ignore_collect(file, config) is None for file in requested)
        plugin.pytest_collection_modifyitems(config, items)
        assert [item.path for item in items] == requested
        assert not marks and not deselected
    # The completeness control still rejects the same input; no fallback partition.
    with pytest.raises(ValueError, match='tier manifest'):
        runner.tier_files(root)


@pytest.mark.parametrize('failure', [
    'malformed-json', 'non-object', 'missing-fast-file', 'missing-manifest'])
@pytest.mark.parametrize('tier', ['fast', 'medium', 'slow'])
def test_explicit_tier_refuses_invalid_manifest(synthetic_tier_checkout, failure, tier):
    plugin, root, manifest = synthetic_tier_checkout
    _break_tier_manifest(manifest, failure)
    config, warnings, _ = _collection_config(tier)
    with pytest.raises(pytest.UsageError, match='tier manifest'):
        plugin.pytest_configure(config)
    assert not warnings
    with pytest.raises(ValueError, match='tier manifest'):
        runner.selected(root=root, tier=tier)


@pytest.mark.parametrize('markexpr', ['fast', 'medium', 'slow', 'not fast', 'slow or custom'])
def test_tier_marker_expression_refuses_invalid_manifest(synthetic_tier_checkout, markexpr):
    plugin, _, manifest = synthetic_tier_checkout
    _break_tier_manifest(manifest, 'missing-fast-file')
    config, warnings, _ = _collection_config(markexpr=markexpr)
    with pytest.raises(pytest.UsageError, match='tier manifest'):
        plugin.pytest_configure(config)
    assert not warnings


def test_valid_manifest_marks_every_ordinary_file_without_omissions(synthetic_tier_checkout):
    plugin, root, _ = synthetic_tier_checkout
    config, warnings, deselected = _collection_config()
    plugin.pytest_configure(config)
    files = [root / file for file in runner.test_files(root)]
    marks = []
    items = [SimpleNamespace(path=file, add_marker=marks.append) for file in files]
    assert all(plugin.pytest_ignore_collect(file, config) is None for file in files)
    plugin.pytest_collection_modifyitems(config, items)
    assert [item.path for item in items] == files
    assert [mark.name for mark in marks] == ['fast', 'medium', 'slow']
    assert not warnings and not deselected


@pytest.mark.parametrize('record', [None, [], 'invalid', 1])
def test_invalid_timing_census_keeps_ordinary_collection_complete(synthetic_tier_checkout, record):
    plugin, root, _ = synthetic_tier_checkout
    (root / 'tests/file_timings.json').write_text(json.dumps(record))
    config, warnings, deselected = _collection_config()
    plugin.pytest_configure(config)
    assert len(warnings) == 1
    assert 'timing census' in str(warnings[0])
    files = [root / file for file in runner.test_files(root)]
    for requested in (files, [files[0]]):
        marks = []
        items = [SimpleNamespace(path=file, add_marker=marks.append) for file in requested]
        assert all(plugin.pytest_ignore_collect(file, config) is None for file in requested)
        plugin.pytest_collection_modifyitems(config, items)
        assert [item.path for item in items] == requested
        assert not marks and not deselected
    with pytest.raises(ValueError, match='timing census'):
        runner.tier_files(root)
    for tier in ('fast', 'medium', 'slow'):
        selected, _, _ = _collection_config(tier)
        with pytest.raises(pytest.UsageError, match='timing census'):
            plugin.pytest_configure(selected)
        with pytest.raises(ValueError, match='timing census'):
            runner.selected(root=root, tier=tier)
    selected, _, _ = _collection_config(markexpr='slow')
    with pytest.raises(pytest.UsageError, match='timing census'):
        plugin.pytest_configure(selected)
