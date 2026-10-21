"""Local acquisition routes must never consult a network transport."""
import json
from pathlib import Path
import shutil
import socket
import subprocess
import urllib.request

import pytest

from ravel.workflow import discovery_http
from ravel.workflow import hepdata_fetch as fetch
from ravel.workflow import resource_census as census

FIXTURE = Path(__file__).parents[1] / 'fixtures/statistics-core/offline'
NOT_CONSULTED = 'offline: network egress unavailable; not consulted'
NO_COPY = 'offline: network egress unavailable; no local mirror copy'


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('offline acquisition attempted a network transport')

    monkeypatch.setattr(fetch, '_open', forbidden)
    monkeypatch.setattr(discovery_http, 'open_url', forbidden)
    monkeypatch.setattr(discovery_http, 'fetch_hepdata_record', forbidden)
    monkeypatch.setattr(discovery_http, 'search_hepdata', forbidden)
    monkeypatch.setattr(discovery_http, 'search_inspire', forbidden)
    monkeypatch.setattr(census, '_get_json', forbidden)
    monkeypatch.setattr(fetch, '_tables_via_hepdata_cli', forbidden)
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(subprocess, 'run', forbidden)
    import pyhf.contrib.utils
    monkeypatch.setattr(pyhf.contrib.utils, 'download', forbidden)


@pytest.fixture
def mirror(tmp_path):
    root = tmp_path / 'mirror'
    shutil.copytree(FIXTURE, root / 'hepdata/ins1001')
    return root


def test_analysis_without_mirror_keeps_local_lookup(capsys):
    expected = census.rung_routines(['ins1001', None])
    assert census.main(['--offline', '--inspire', '1001']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['offline'] is True and record['mirror'] is None
    assert record['rungs']['R1_hepdata'] == {'status': 'SKIPPED', 'reason': NO_COPY}
    assert record['rungs']['R2_routines'] == expected
    for name in ('R3_arxiv', 'R4_github', 'R5_citations'):
        assert record['rungs'][name] == {'status': 'SKIPPED', 'reason': NOT_CONSULTED}


def test_mirror_record_exposes_only_keys(mirror, capsys, monkeypatch):
    monkeypatch.chdir(mirror.parent)
    assert census.main(['--offline', '--mirror', 'mirror', '--inspire', 'ins1001',
                        '--arxiv', 'fictional-source']) == 0
    record = json.loads(capsys.readouterr().out)
    assert record['mirror'] == str(mirror)
    path = mirror / 'hepdata/ins1001/record.json'
    assert record['rungs']['R1_hepdata'] == {
        'status': 'OK', 'source': 'local-mirror', 'path': str(path),
        'keys': sorted(json.loads(path.read_text()))}
    assert record['rungs']['R3_arxiv']['reason'] == NOT_CONSULTED


@pytest.mark.parametrize('contents', [None, '[]', 'null', '{', '1', '"text"'])
def test_missing_or_invalid_record_is_skipped(mirror, contents):
    path = mirror / 'hepdata/ins1001/record.json'
    if contents is None:
        path.unlink()
    else:
        path.write_text(contents)
    record = census.census_one('1001', offline=True, mirror=str(mirror))
    assert record['rungs']['R1_hepdata'] == {'status': 'SKIPPED', 'reason': NO_COPY}


def test_no_walked_rungs_still_writes_offline_output(tmp_path, monkeypatch):
    def unavailable(*args):
        return {'status': 'ERROR', 'reason': 'local lookup unavailable'}
    monkeypatch.setattr(census, 'rung_routines', unavailable)
    assert census.main(['--offline', '--inspire', '1001', '--rundir', str(tmp_path)]) == 0
    record = json.loads((tmp_path / 'inputs/resource_census/ins1001.json').read_text())
    index = json.loads((tmp_path / 'inputs/resource_census.json').read_text())
    assert record['rungs_ok'] == []
    assert index['offline'] is True and index['mirror'] is None
    assert index['entries'][0]['id'] == 'ins1001'


def test_controller_embeds_analysis_and_keyword_records(tmp_path, mirror):
    output = tmp_path / 'controller.json'
    assert census.main(['--offline', '--mirror', str(mirror), '--analysis', 'inspire=1001',
                        '--analysis', 'inspire=1002', '--keyword', 'fictional topic',
                        '--controller-output', str(output)]) == 0
    doc = json.loads(output.read_text())
    assert doc['offline'] is True and doc['mirror'] == str(mirror)
    assert len(doc['records']) == 3
    assert len(doc['rungs']) == 12
    for record in doc['records']:
        assert record['offline'] is True and record['mirror'] == str(mirror)
    search = doc['records'][-1]
    assert search['candidates'] == [] and search['rungs_ok'] == []
    for value in (*search['searches'].values(), *search['rungs'].values()):
        assert value['status'] == 'SKIPPED' and value['reason'] == NOT_CONSULTED


def test_keyword_only_offline_writes_index_and_markdown(tmp_path, capsys):
    assert census.main(['--offline', '--keyword', 'fictional topic', '--rundir', str(tmp_path),
                        '--markdown']) == 0
    output = capsys.readouterr()
    assert 'EVERY rung failed' not in output.err
    assert 'Offline' in output.out and 'not consulted' in output.out
    assert 'ERROR' not in output.out
    index = json.loads((tmp_path / 'inputs/resource_census.json').read_text())
    assert index['entries'] == [] and len(index['searches']) == 1


def test_analysis_markdown_records_unconsulted_rungs(mirror, capsys):
    assert census.main(['--offline', '--mirror', str(mirror), '--inspire', '1001',
                        '--markdown']) == 0
    output = capsys.readouterr().out
    assert '(offline)' in output and 'local-mirror' in output
    for name in ('R3_arxiv', 'R4_github', 'R5_citations'):
        assert f'{name}: SKIPPED; {NOT_CONSULTED}' in output
    assert '(searched; none' not in output


def test_census_mirror_requires_offline(tmp_path):
    with pytest.raises(SystemExit) as exc:
        census.main(['--mirror', str(tmp_path), '--inspire', '1001'])
    assert exc.value.code == 2


def test_debug_cannot_bypass_offline():
    assert census.main(['--offline', '--debug', 'recipe-search', '--tool', 'tool',
                        '--model', 'model']) == 2


@pytest.mark.parametrize('identifier', ['1001', 'ins1001'])
def test_fetch_mirror_copies_tables_and_models(tmp_path, mirror, identifier):
    out = tmp_path / 'out'
    fetch.main(['--offline-mirror', str(mirror), '--inspire', identifier, '--tables',
                '--download-likelihood', '--out', str(out)])
    manifest = json.loads((out / 'hepdata_manifest.json').read_text())
    assert manifest['status'] == 'OK'
    assert manifest['source'] == 'local-mirror' and manifest['network_access'] is False
    assert manifest['tables_route'] == 'offline-fixture'
    assert len(manifest['table_files']) == 1
    assert (out / 'models/patchset.json').is_file()
    assert manifest['likelihoods'][0]['downloaded']


def test_missing_mirror_record_errors_without_fallback(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-mirror', str(tmp_path), '--inspire', '1001',
                    '--out', str(tmp_path / 'out')])
    assert exc.value.code == 1
    assert capsys.readouterr().err.strip() == 'ERROR: offline mirror has no record for ins1001'


@pytest.mark.parametrize('source', [[], ['--routine', 'SYN_9009_I1001'],
                                    ['--offline-fixture', str(FIXTURE)],
                                    ['--inspire', '../1001']])
def test_fetch_mirror_requires_valid_inspire(tmp_path, source):
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-mirror', str(tmp_path), *source, '--out', str(tmp_path / 'out')])
    assert exc.value.code == 2


@pytest.mark.parametrize('member', ['record.json', 'tables/1.json', 'models/patchset.json'])
def test_incomplete_mirror_fails_closed(tmp_path, mirror, member):
    (mirror / 'hepdata/ins1001' / member).unlink()
    out = tmp_path / 'out'
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-mirror', str(mirror), '--inspire', '1001', '--tables',
                    '--download-likelihood', '--out', str(out)])
    assert exc.value.code == 1
    manifest = json.loads((out / 'hepdata_manifest.json').read_text())
    assert manifest['status'] == 'ERROR' and manifest['source'] == 'local-mirror'
    assert manifest['network_access'] is False and manifest['errors']


def test_mirror_retains_restriction_guard(tmp_path, mirror, monkeypatch):
    def deny(*args, **kwargs):
        raise fetch.SourceRestricted('local source refused')
    monkeypatch.setattr(fetch, '_require', deny)
    with pytest.raises(fetch.SourceRestricted, match='local source refused'):
        fetch.main(['--offline-mirror', str(mirror), '--inspire', '1001',
                    '--out', str(tmp_path / 'out')])


def test_mirror_likelihood_path_escape_is_refused(tmp_path, mirror):
    path = mirror / 'hepdata/ins1001/likelihoods.json'
    path.write_text(json.dumps({'https://example.invalid/model': ['../outside.json']}))
    with pytest.raises(SystemExit) as exc:
        fetch.main(['--offline-mirror', str(mirror), '--inspire', '1001',
                    '--download-likelihood', '--out', str(tmp_path / 'out')])
    assert exc.value.code == 1


def test_mirror_checks_each_member_restriction(tmp_path, mirror, monkeypatch):
    original = fetch._require
    def deny_table(tool, descriptor, **kwargs):
        if str(descriptor.get('path', '')).endswith('tables/1.json'):
            raise fetch.SourceRestricted('table source refused')
        return original(tool, descriptor, **kwargs)
    monkeypatch.setattr(fetch, '_require', deny_table)
    with pytest.raises(fetch.SourceRestricted, match='table source refused'):
        fetch.main(['--offline-mirror', str(mirror), '--inspire', '1001', '--tables',
                    '--out', str(tmp_path / 'out')])


def test_controller_reading_offline(tmp_path):
    reading = tmp_path / 'reading.json'
    reading.write_text(json.dumps({'facts': [{'type': 'identifier',
                                            'value': {'scheme': 'inspire', 'id': 'ins1001'}}]}))
    output = tmp_path / 'output.json'
    assert census.main(['--offline', '--reading', str(reading),
                        '--controller-output', str(output)]) == 0
    doc = json.loads(output.read_text())
    assert doc['offline'] is True and doc['mirror'] is None
    assert doc['records'][0]['inspire'] == '1001'
