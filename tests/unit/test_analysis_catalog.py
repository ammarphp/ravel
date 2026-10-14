"""Adversarial discovery tests on a catalogue built from synthetic upstream checkouts.

RAVEL ships no list of upstream analyses: the catalogue is built from the user's own checkouts.
No simulator, model call or physics claim is involved.
"""
import synthetic_identifiers as syn
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ravel import analysis_catalog as ac, cli
from ravel.workflow import analysis_catalog_build as builder
from synthetic_catalog import build, checkout

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    return build(tmp_path_factory.mktemp('catalogue'))


@pytest.fixture
def catalog(built):
    return copy.deepcopy(built[1])


def test_no_catalogue_is_shipped_and_its_absence_is_explained(tmp_path, monkeypatch):
    assert not (ROOT / 'src/ravel/data/analysis-catalog.json').exists()
    monkeypatch.setenv(ac.CATALOG_ENV, str(tmp_path / 'absent.json'))
    with pytest.raises(ac.CatalogUnavailable, match='ravel catalogue'):
        ac.load_catalog()


def test_catalogue_path_defaults_to_the_user_cache(monkeypatch, tmp_path):
    monkeypatch.delenv(ac.CATALOG_ENV, raising=False)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    assert ac.catalog_path() == tmp_path / 'ravel' / 'analysis-catalog.json'


def test_complete_defined_inventory(catalog):
    assert catalog['summary']['by_framework'] == {'rivet': 4, 'simpleanalysis': 3}
    assert catalog['sources']['rivet']['all_info_files'] == 5
    assert catalog['sources']['rivet']['excluded_non_lhc_metadata'] == 1
    assert catalog['sources']['simpleanalysis']['sources_without_registration'] == []
    assert not any(r['name'].startswith('MC_') for r in catalog['entries'])
    assert catalog['summary']['new_physics_validations'] == 0
    assert all(r['physics_validated_by_ravel'] is False for r in catalog['entries'])


def test_a_single_source_builds_a_valid_catalogue(tmp_path):
    rivet = checkout(tmp_path / 'r', {'analyses/pluginCMS/CMS_9009_I0009.info':
                                      'Name: CMS_9009_I0009\nSummary: x\nExperiment: CMS\nCollider: LHC\n',
                                      'analyses/pluginCMS/CMS_9009_I0009.cc': 'class A {};\n'})
    catalog = builder.build(rivet_root=rivet, retrieved='9001-01-01')
    assert set(catalog['sources']) == {'rivet'} and catalog['summary']['entries'] == 1
    with pytest.raises(ValueError, match='supply'):
        builder.build()


def test_paper_with_multiple_routines_requires_selection(catalog):
    with pytest.raises(ValueError, match='ambiguous'):
        ac.resolve(catalog, 'FAKE-9006-01')


def test_case_code_and_arxiv_aliases_resolve(catalog):
    assert ac.resolve(catalog, 'rivet:atlas_9001_i0001')['name'] == 'ATLAS_9001_I0001'
    assert ac.resolve(catalog, ('arXiv:' + syn.arxiv(1)))['name'] == 'ATLAS_9001_I0001'
    assert ac.resolve(catalog, ('https://arxiv.org/abs/' + syn.arxiv(1) + '/'))['name'] == 'ATLAS_9001_I0001'
    assert ac.resolve(catalog, 'ATLAS-FAKE-9001-01')['name'] == 'ATLAS_9001_I0001'
    assert ac.resolve(catalog, 'ins0003')['name'] == 'CMS_9003_I0003'
    with pytest.raises(ValueError, match='not in'):
        ac.resolve(catalog, 'made-up-analysis')


def test_filters_intersect_and_never_truncate(catalog):
    rows = ac.search(catalog, 'fake', experiment='atlas', framework='simpleanalysis', family='search-recast')
    assert rows and all(r['framework'] == 'simpleanalysis' and r['family'] == 'search-recast' for r in rows)
    assert ac.search(catalog, 'this-is-not-a-paper') == []
    assert len(ac.search(catalog)) == 7
    assert len(ac.search(catalog, experiment='CMS')) == 2


@pytest.mark.parametrize('kwargs', [{'family': 'made-up'}, {'framework': 'unknown'}])
def test_invalid_filter_is_not_silent_empty(catalog, kwargs):
    with pytest.raises(ValueError):
        ac.search(catalog, **kwargs)


def test_upstream_metadata_conflict_preserved(catalog):
    row = ac.resolve(catalog, 'CMS_9003_I0003')
    assert row['experiment'] == 'CMS' and row['metadata']['Experiment'] == 'ATLAS'
    assert any('conflicts' in x for x in row['metadata_issues'])


def test_missing_source_and_nonstandard_status_are_visible(catalog):
    packet = ac.adaptation_packet(catalog, ac.resolve(catalog, 'CMS_9004_I0004'))
    assert any('unresolved' in x for x in packet['blockers'])
    row = copy.deepcopy(ac.resolve(catalog, 'CMS_9003_I0003'))
    row['upstream_status'] = 'VALIDATED NOTREENTRY SINGLEWEIGHT'
    packet = ac.adaptation_packet(catalog, row)
    assert any('unqualified' in x for x in packet['blockers'])
    assert any('SINGLEWEIGHT' in x for x in packet['requirements'])
    assert any('finalize' in x for x in packet['requirements'])


def test_index_presence_does_not_approve(catalog):
    row = ac.resolve(catalog, 'FakeSearchA')
    packet = ac.adaptation_packet(catalog, row)
    assert packet['probability_model_index_matches']
    assert packet['compute_authorized'] is False and packet['physics_validated'] is False
    assert packet['reference_content_verified'] is False
    assert any('workspace' in x for x in packet['requirements'])
    assert row['features']['restframes'] and row['features']['onnx']
    assert [a['literal'] for a in row['external_assets']] == ['model.onnx']


def test_all_packets_preserve_boundaries(catalog):
    for row in catalog['entries']:
        packet = ac.adaptation_packet(catalog, row)
        assert packet['compute_authorized'] is False and packet['physics_validated'] is False
        assert packet['blockers'] and len(packet['requirements']) >= 7
        assert all('/-/blob/' in u for u in packet['source_urls'])


@pytest.mark.parametrize('identity,family', [
    ('ATLAS_9001_I0001', 'search-recast'),
    ('ATLAS_9002_I0002', 'heavy-ion'),
    ('CMS_9003_I0003', 'fiducial-measurement'),
    ('CMS_9004_I0004', 'long-lived'),
    ('FakeSearchB', 'search-recast'),
])
def test_conservative_family_triage(catalog, identity, family):
    assert ac.resolve(catalog, identity)['family'] == family


@pytest.mark.parametrize('mutation', [
    lambda c: c['entries'].append(copy.deepcopy(c['entries'][0])),
    lambda c: c['entries'][0].update(physics_validated_by_ravel=True),
    lambda c: c['entries'][0].update(family='forward' if c['entries'][0]['family'] != 'forward' else 'neutrino'),
    lambda c: c['sources']['rivet'].update(revision='main'),
    lambda c: c['entries'][0]['source_files'][0].update(path='../../outside.cc'),
    lambda c: c['entries'][0]['source_files'][0].update(path='/outside.cc'),
    lambda c: c['entries'][0]['source_files'][0].update(git_blob='not-a-hash'),
    lambda c: c['summary'].update(entries=1),
    lambda c: c['sources']['rivet'].update(selected_info_files=1),
    lambda c: c['sources'].pop('simpleanalysis'),
])
def test_malformed_or_promoted_catalogue_rejected(catalog, mutation):
    mutation(catalog)
    with pytest.raises(ValueError):
        ac.validate_catalog(catalog)


def test_duplicate_json_keys_rejected(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match='duplicate'):
        ac.load_catalog(p)


def test_builder_refuses_to_overwrite_without_force(built, tmp_path):
    path = built[0]
    rivet = tmp_path / 'r'
    checkout(rivet, {'analyses/pluginCMS/CMS_9009_I0009.info': 'Name: CMS_9009_I0009\nSummary: x\nExperiment: CMS\n'
                                                               'Collider: LHC\n'})
    with pytest.raises(FileExistsError):
        builder.main(['--rivet', str(rivet), '--out', str(path)])


def test_metadata_parser_does_not_invent_yaml_repair():
    raw = ('Name: TEST\nStatus: True\nReferences:\n - arXiv:' + syn.arxiv(9) + '\nDescription:\n'
           "'unindented malformed prose\nReleaseTests:\n - test\n").encode()
    values, issues = builder.metadata(raw)
    assert values['Status'] == 'True' and values['ReleaseTests'] == ['test'] and not issues
    assert 'Description' not in values


def test_dependency_scanning_ignores_comments_preserves_strings():
    text = ('// DefineAnalysis(Fake) RestFrames\n/* addONNX("x","fake.onnx"); */\nDefineAnalysis(Actual)\n'
            'addONNX("x","actual.onnx");\nLabRecoFrame* LAB;')
    code = builder.strip_comments(text)
    assert 'Fake' not in code and 'fake.onnx' not in code and 'actual.onnx' in code
    features = builder.feature_signals(text, 'Leading jet production')
    assert 'onnx' in features and 'restframes' in features and 'heavy-ion-domain' not in features


@pytest.mark.parametrize('text', ['Pb+Pb', 'p--Pb', "['p+', 'Pb']", 'Nuclear modification', 'lead-lead'])
def test_nuclear_domain_cues(text):
    assert 'heavy-ion-domain' in builder.feature_signals('', text)


def _git(root, *args):
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1'}
    return subprocess.check_output(['git', '-C', str(root), *args], env=env).decode().strip()


def test_source_verification_rejects_dirty_bytes_wrong_head_and_symlink(tmp_path):
    root = tmp_path / 'upstream'
    root.mkdir()
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.name', 'Test')
    _git(root, 'config', 'user.email', 'test@example.invalid')
    p = root / 'routine.cc'
    p.write_text('original fixture\n')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', 'fixture')
    rev = _git(root, 'rev-parse', 'HEAD')
    blob = _git(root, 'hash-object', 'routine.cc')
    row = {'id': 'rivet:TEST', 'source_id': 'rivet',
           'source_files': [{'path': 'routine.cc', 'git_blob': blob, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}]}
    c = {'sources': {'rivet': {'revision': rev}}}
    assert ac.verify_source(c, row, root)['status'] == 'PASS'
    p.write_text('tampered\n')
    assert ac.verify_source(c, row, root)['status'] == 'FAIL'
    p.write_text('original fixture\n')
    _git(root, 'commit', '--allow-empty', '-qm', 'other')
    assert ac.verify_source(c, row, root)['status'] == 'FAIL'
    _git(root, 'checkout', '-q', rev)
    outside = tmp_path / 'outside.cc'
    outside.write_text(p.read_text())
    p.unlink()
    p.symlink_to(outside)
    result = ac.verify_source(c, row, root)
    assert result['status'] == 'FAIL' and any('symlink' in i for i in result['issues'])
    assert not result['compute_authorized'] and not result['physics_validated']


def test_cli_reads_the_local_catalogue_and_needs_no_simulation(built, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv(ac.CATALOG_ENV, str(built[0]))

    def no_launch(*a, **k):
        raise AssertionError('unexpected subprocess')
    monkeypatch.setattr(subprocess, 'run', no_launch)
    assert cli.main(['analyses', 'summary']) == 0
    data = json.loads(capsys.readouterr().out)
    assert data['entries'] == 7 and data['compute_authorized'] is False
    assert cli.main(['analyses', 'show', 'FakeSearchA']) == 0
    assert json.loads(capsys.readouterr().out)['physics_validated'] is False
    assert cli.main(['analyses', 'show', 'FAKE-9006-01']) == 2
    assert 'ambiguous' in capsys.readouterr().err
    assert cli.main(['analyses', 'list', '--query', 'impossible-key', '--json']) == 0
    assert json.loads(capsys.readouterr().out)['matches'] == 0
    monkeypatch.setenv(ac.CATALOG_ENV, str(tmp_path / 'absent.json'))
    assert cli.main(['analyses', 'summary']) == 2
    assert 'ravel catalogue' in capsys.readouterr().err
