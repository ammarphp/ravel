"""Upstream routine names bind to generic native adapters through a supplied alias file."""
import json

import pytest

from ravel.physics import native_capabilities as nc

@pytest.fixture(autouse=True)
def supplied_package(tmp_path, monkeypatch):
    from analysis_package_fixtures import native_package
    native_package(tmp_path / 'package', 'ANA-0001', ['selected'], models=['c1n2-wz'])
    monkeypatch.setenv('RAVEL_ANALYSIS_PACKAGES', str(tmp_path))



def _aliases(tmp_path, rows):
    path = tmp_path / 'aliases.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'native-routine-aliases', 'aliases': rows}))
    return path


def test_no_upstream_routine_is_registered_without_an_alias(monkeypatch):
    monkeypatch.delenv(nc.ALIAS_ENV, raising=False)
    with pytest.raises(ValueError, match='supply an analysis package'):
        nc.adapter_for('FakeSearchZ')


def test_an_alias_reaches_its_adapter_and_keeps_its_identity(tmp_path, monkeypatch):
    adapter = next(iter(nc.discover_capabilities()))
    row = nc.discover_capabilities()[adapter]
    monkeypatch.setenv(nc.ALIAS_ENV, str(_aliases(tmp_path, {'FakeSearchZ': {'adapter': adapter,
                                                                                'analysis_ids': ['XYZ-9030-01']}})))
    assert nc.adapter_for('FakeSearchZ') == adapter
    capability = nc.resolve_capability('FakeSearchZ', row['models'][0], row['preparations'][0], row['detector'],
                                       row['statistics'][0], analysis_id='XYZ-9030-01')
    assert capability['routine'] == adapter and capability['upstream_routine'] == 'FakeSearchZ'
    with pytest.raises(ValueError, match='disagrees'):
        nc.resolve_capability('FakeSearchZ', row['models'][0], row['preparations'][0], row['detector'],
                              row['statistics'][0], analysis_id='XYZ-9031-01')


@pytest.mark.parametrize('rows', [{'FakeSearchZ': {'adapter': 'no-such-adapter'}},
                                  {'FakeSearchZ': {'adapter': 'x', 'extra': 1}}])
def test_malformed_alias_files_are_refused(tmp_path, rows):
    with pytest.raises(ValueError):
        nc.load_aliases(_aliases(tmp_path, rows))


def test_an_alias_cannot_shadow_an_adapter(tmp_path):
    adapter = next(iter(nc.discover_capabilities()))
    with pytest.raises(ValueError, match='shadows'):
        nc.load_aliases(_aliases(tmp_path, {adapter: {'adapter': adapter}}))
