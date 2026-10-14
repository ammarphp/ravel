"""Offline CLI controls forbid every acquisition transport."""
import json
from pathlib import Path
import shutil

import pytest

from ravel.workflow import hepdata_fetch as fetch

FIXTURE = Path(__file__).parents[1] / 'fixtures/statistics-core/offline'


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline fetch attempted a network transport')
    monkeypatch.setattr(fetch, '_open', forbidden)
    monkeypatch.setattr(fetch.discovery_http, 'open_url', forbidden)
    monkeypatch.setattr(fetch.discovery_http, 'fetch_hepdata_record', forbidden)
    monkeypatch.setattr(fetch, '_tables_via_hepdata_cli', forbidden)
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    import pyhf.contrib.utils
    monkeypatch.setattr(pyhf.contrib.utils, 'download', forbidden)


def test_missing_offline_table_fails_without_network_fallback(tmp_path):
    fixture = tmp_path / 'fixture'
    shutil.copytree(FIXTURE, fixture)
    (fixture / 'tables/1.json').unlink()
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-fixture', str(fixture), '--tables', '--out', str(tmp_path / 'out')])
    assert exc.value.code == 1
    manifest = json.loads((tmp_path / 'out/hepdata_manifest.json').read_text())
    assert manifest['status'] == 'ERROR'
    assert '1.json' in ' '.join(manifest['errors'])


def test_fixture_cli_fetches_tables_and_likelihood_locally(tmp_path):
    fetch.main(['--offline-fixture', str(FIXTURE), '--tables', '--download-likelihood', '--out', str(tmp_path)])
    manifest = json.loads((tmp_path / 'hepdata_manifest.json').read_text())
    assert manifest['status'] == 'OK'
    assert manifest['tables_route'] == 'offline-fixture'
    assert len(manifest['table_files']) == 1
    assert manifest['network_access'] is False
    assert (tmp_path / 'models/patchset.json').is_file()
    assert manifest['likelihoods'][0]['downloaded']


def test_missing_likelihood_and_path_escape_are_refused(tmp_path):
    fixture = tmp_path / 'fixture'
    shutil.copytree(FIXTURE, fixture)
    index = fixture / 'likelihoods.json'
    for value in ({}, {'https://example.invalid/model':['../outside.json']}):
        index.write_text(json.dumps(value))
        with pytest.raises(SystemExit) as exc:
            fetch.main(['--offline-fixture', str(fixture), '--download-likelihood', '--out', str(tmp_path / 'out')])
        assert exc.value.code == 1


def test_offline_flag_refuses_remote_source(tmp_path):
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline', '--inspire', '7', '--out', str(tmp_path)])
    assert exc.value.code == 2


def test_non_object_likelihood_index_fails_closed(tmp_path):
    fixture = tmp_path / 'fixture'
    shutil.copytree(FIXTURE, fixture)
    (fixture / 'likelihoods.json').write_text('[]')
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-fixture', str(fixture), '--download-likelihood', '--out', str(tmp_path / 'out')])
    assert exc.value.code == 1
    manifest = json.loads((tmp_path / 'out/hepdata_manifest.json').read_text())
    assert 'likelihoods.json' in ' '.join(manifest['errors'])
