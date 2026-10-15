"""The package ships a pinned snapshot of the public Rivet and SimpleAnalysis routine metadata.

Routine lookup works from it with no checkout, no network and no installer run. A catalogue built on
the machine outranks it. Nothing here runs a routine or certifies physics.
"""
import hashlib
import json
import socket

import pytest

from ravel import analysis_catalog as ac
from ravel.workflow import analysis_catalog_build as builder
from ravel.workflow import routine_fetch
from synthetic_catalog import build


@pytest.fixture
def packaged_only(tmp_path, monkeypatch):
    """No environment override, no user cache and no installed catalogue; network use is an error."""
    monkeypatch.delenv(ac.CATALOG_ENV, raising=False)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setattr(ac, 'installed_catalog_path', lambda prefix=None: tmp_path / 'prefix/share/ravel/none.json')

    def refuse(self, *args, **kwargs):
        raise AssertionError('routine lookup must not use the network')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    return tmp_path


def test_the_snapshot_is_packaged_and_valid(packaged_only):
    path = ac.packaged_catalog_path()
    assert path is not None and ac.catalog_path() == path
    catalog = ac.load_catalog()
    assert catalog['summary']['entries'] == 633
    assert catalog['summary']['by_framework'] == {'rivet': 554, 'simpleanalysis': 79}
    assert catalog['summary']['new_physics_validations'] == 0
    assert all(r['physics_validated_by_ravel'] is False for r in catalog['entries'])
    for key in ('rivet', 'simpleanalysis'):
        assert len(catalog['sources'][key]['revision']) == 40


def test_the_snapshot_carries_the_probability_model_index_associations(packaged_only):
    catalog = ac.load_catalog()
    index = ac.packaged_model_index_path()
    source = catalog['sources']['probability-models']
    assert source['sha256'] == hashlib.sha256(index.read_bytes()).hexdigest()
    assert source['entries'] == len(json.loads(index.read_text())) == 45
    matched = [r for r in catalog['entries'] if r['model_index_matches']]
    assert len(matched) == 24 and catalog['summary']['with_model_index_match'] == 24
    for row in matched:
        for match in row['model_index_matches']:
            assert match['status'].startswith('listed-only')
    packet = ac.adaptation_packet(catalog, ac.resolve(catalog, 'simpleanalysis:EwkThreeLeptonERJR2018'))
    assert packet['probability_model_index_matches']
    assert packet['compute_authorized'] is False and packet['physics_validated'] is False


def test_real_routine_identities_resolve_offline(packaged_only):
    absent = packaged_only / 'absent'
    cases = {
        'ins1646686': 'rivet:ATLAS_2018_I1646686',
        'ATLAS_2012_I1083318': 'rivet:ATLAS_2012_I1083318',
        'EwkThreeLeptonERJR2018': 'simpleanalysis:EwkThreeLeptonERJR2018',
        'SUSY-2018-06': 'simpleanalysis:EwkThreeLeptonERJR2018',
    }
    for query, identity in cases.items():
        found = routine_fetch.find_routines(query, rivet_share=absent, sa_src=absent)
        assert found['catalog']['checked'] is True, found['catalog'].get('reason')
        assert identity in [m['id'] for m in found['catalog']['matches']], query
        assert found['rivet']['checked'] is False and found['simpleanalysis']['checked'] is False
    row = ac.resolve(ac.load_catalog(), 'ATLAS_2018_I1646686')
    assert row['framework'] == 'rivet' and row['inspire_id'] == '1646686'
    assert 'TOPQ-2016-09' in row['analysis_ids']


def test_lookup_report_names_the_snapshot_and_never_claims_a_checked_tree(packaged_only, capsys):
    absent = packaged_only / 'absent'
    routine_fetch.main(['--query', 'ins1646686', '--rivet-share', str(absent), '--sa-src', str(absent)])
    out = capsys.readouterr().out
    assert 'ATLAS_2018_I1646686' in out and 'Packaged catalogue snapshot' in out
    assert '0 match' not in out and 'not checked' in out.lower()


def test_a_catalogue_built_here_outranks_the_snapshot(packaged_only, monkeypatch, tmp_path_factory):
    packaged = ac.packaged_catalog_path()
    built, _ = build(tmp_path_factory.mktemp('built'))
    installed = packaged_only / 'prefix/share/ravel/analysis-catalog.json'
    installed.parent.mkdir(parents=True)
    installed.write_text(built.read_text())
    monkeypatch.setattr(ac, 'installed_catalog_path', lambda prefix=None: installed)
    assert ac.catalog_path() == installed != packaged
    cached = ac.user_catalog_path()
    cached.parent.mkdir(parents=True)
    cached.write_text(built.read_text())
    assert ac.catalog_path() == cached
    monkeypatch.setenv(ac.CATALOG_ENV, str(packaged_only / 'named.json'))
    assert ac.catalog_path() == packaged_only / 'named.json'
    with pytest.raises(ac.CatalogUnavailable):
        ac.load_catalog()


def test_the_default_build_target_is_never_the_package(packaged_only):
    assert ac.user_catalog_path() == packaged_only / 'cache/ravel/analysis-catalog.json'
    assert ac.catalog_path() == ac.packaged_catalog_path() != ac.user_catalog_path()


def test_the_builder_uses_the_shipped_model_index_by_default(tmp_path):
    from synthetic_catalog import RIVET, SIMPLEANALYSIS, checkout
    rivet = checkout(tmp_path / 'rivet', RIVET)
    sa = checkout(tmp_path / 'sa', SIMPLEANALYSIS)
    common = ['--rivet', str(rivet), '--simpleanalysis', str(sa), '--retrieved-at', '9001-01-01']
    with_index = tmp_path / 'with.json'
    assert builder.main([*common, '--out', str(with_index)]) == 0
    source = json.loads(with_index.read_text())['sources']['probability-models']
    assert source['sha256'] == hashlib.sha256(ac.packaged_model_index_path().read_bytes()).hexdigest()
    assert source['url'] == builder.PUBLIC_MODEL_INDEX_URL and source['entries'] == 45
    without = tmp_path / 'without.json'
    assert builder.main([*common, '--no-models', '--out', str(without)]) == 0
    assert 'probability-models' not in json.loads(without.read_text())['sources']
