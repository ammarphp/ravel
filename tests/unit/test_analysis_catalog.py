"""Adversarial discovery tests; no simulator, model calls, or physics claims."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from ravel import analysis_catalog as ac, cli
spec=importlib.util.spec_from_file_location('catalog_builder',ROOT/'scripts/catalogue/build_analysis_catalog.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


@pytest.fixture(scope='module')
def catalog():
    return ac.load_catalog()


def test_complete_defined_inventory(catalog):
    assert catalog['summary']['by_framework']=={'rivet':554,'simpleanalysis':79}
    assert catalog['sources']['rivet']['all_info_files']==2058
    assert catalog['sources']['rivet']['unmatched_lhc_source_files']==[]
    assert catalog['sources']['simpleanalysis']['sources_without_registration']==[]
    assert not any(r['name'].startswith(('MC_','SND_')) for r in catalog['entries'])
    assert catalog['summary']['new_physics_validations']==0
    assert all(r['physics_validated_by_ravel'] is False for r in catalog['entries'])


@pytest.mark.parametrize('identity',['SUSY-2018-16','ATLAS-SUSY-2018-16','SUSY-2018-22'])
def test_paper_with_multiple_routines_requires_selection(catalog,identity):
    with pytest.raises(ValueError,match='ambiguous'): ac.resolve(catalog,identity)


def test_case_and_arxiv_aliases_resolve(catalog):
    assert ac.resolve(catalog,'rivet:cms_2021_i1972986')['name']=='CMS_2021_I1972986'
    assert ac.resolve(catalog,'arXiv:2111.10431')['name']=='CMS_2021_I1972986'
    assert ac.resolve(catalog,'https://arxiv.org/abs/2111.10431/')['name']=='CMS_2021_I1972986'
    with pytest.raises(ValueError,match='not in'): ac.resolve(catalog,'made-up-analysis')


def test_filters_intersect_and_never_truncate(catalog):
    rows=ac.search(catalog,'2018',experiment='atlas',framework='simpleanalysis',family='search-recast')
    assert rows and all(r['framework']=='simpleanalysis' and r['family']=='search-recast' for r in rows)
    assert ac.search(catalog,'this-is-not-a-paper')==[]
    assert len(ac.search(catalog))==633
    assert len(ac.search(catalog,experiment='CMS'))==155  # combined CMS/TOTEM included


@pytest.mark.parametrize('kwargs',[{'family':'made-up'},{'framework':'unknown'}])
def test_invalid_filter_is_not_silent_empty(catalog,kwargs):
    with pytest.raises(ValueError): ac.search(catalog,**kwargs)


def test_upstream_metadata_conflict_preserved(catalog):
    row=ac.resolve(catalog,'CMS_2018_I1646260')
    assert row['experiment']=='CMS' and row['metadata']['Experiment']=='ATLAS'
    assert any('conflicts' in x for x in row['metadata_issues'])


def test_missing_source_and_nonstandard_status_are_visible(catalog):
    packet=ac.adaptation_packet(catalog,ac.resolve(catalog,'ATLAS_2012_I1093734'))
    assert any('unresolved' in x for x in packet['blockers'])
    row=copy.deepcopy(ac.resolve(catalog,'ATLAS_2019_I1734263'))
    row['upstream_status']='VALIDATED NOTREENTRY SINGLEWEIGHT'
    packet=ac.adaptation_packet(catalog,row)
    assert any('unqualified' in x for x in packet['blockers'])
    assert any('SINGLEWEIGHT' in x for x in packet['requirements'])
    assert any('finalize' in x for x in packet['requirements'])


def test_index_presence_and_registration_do_not_approve(catalog):
    row=ac.resolve(catalog,'EwkCompressed2018'); packet=ac.adaptation_packet(catalog,row)
    assert packet['registered_native_adapter'] and packet['probability_model_index_matches']
    assert packet['compute_authorized'] is False and packet['physics_validated'] is False
    assert packet['reference_content_verified'] is False
    assert any('workspace' in x for x in packet['requirements'])
    assert row['features']['restframes']


def test_all_packets_preserve_boundaries(catalog):
    for row in catalog['entries']:
        packet=ac.adaptation_packet(catalog,row)
        assert packet['compute_authorized'] is False and packet['physics_validated'] is False
        assert packet['blockers'] and len(packet['requirements'])>=7
        assert all('/-/blob/' in u for u in packet['source_urls'])
        for asset in row.get('external_assets',[]):
            if len(asset['matches'])!=1: assert any(asset['literal'] in s for s in packet['blockers'])


@pytest.mark.parametrize('identity,family',[
    ('ATLAS_2016_I1494075','fiducial-measurement'), # ZZ with neutrinos is not a neutrino-beam experiment
    ('LHCB_2019_I1720413','heavy-ion'),
    ('LHCB_2021_I1913240','heavy-ion'),
    ('LHCB_2022_I2694685','heavy-ion'),
    ('TOTEM_2014_I1328627','forward'), # displaced interaction point is not an LLP search
    ('FASER_2024_I2855783','neutrino'),
    ('ATLAS_PBPB_CENTRALITY','calibration'),
    ('DisappearingTrack2018','long-lived'),
])
def test_domain_false_friends(catalog,identity,family):
    assert ac.resolve(catalog,identity)['family']==family


@pytest.mark.parametrize('mutation',[
    lambda c: c['entries'].append(copy.deepcopy(c['entries'][0])),
    lambda c: c['entries'][0].update(physics_validated_by_ravel=True),
    lambda c: c['entries'][0].update(family='search-recast' if c['entries'][0]['family']!='search-recast' else 'forward'),
    lambda c: c['sources']['rivet'].update(revision='main'),
    lambda c: c['entries'][0]['source_files'][0].update(path='../../outside.cc'),
    lambda c: c['entries'][0]['source_files'][0].update(path='/outside.cc'),
    lambda c: c['entries'][0]['source_files'][0].update(git_blob='not-a-hash'),
    lambda c: c['summary'].update(entries=1),
    lambda c: c['sources']['rivet'].update(selected_info_files=1),
])
def test_malformed_or_promoted_catalogue_rejected(catalog,mutation):
    c=copy.deepcopy(catalog); mutation(c)
    with pytest.raises(ValueError): ac.validate_catalog(c)


def test_duplicate_json_keys_rejected(tmp_path):
    p=tmp_path/'bad.json';p.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError,match='duplicate'): ac.load_catalog(p)


def test_metadata_parser_does_not_invent_yaml_repair():
    raw=b'Name: TEST\nStatus: True\nReferences:\n - arXiv:1234.56789\nDescription:\n\'unindented malformed prose\nReleaseTests:\n - test\n'
    values,issues=builder.metadata(raw)
    assert values['Status']=='True' and values['ReleaseTests']==['test'] and not issues
    assert 'Description' not in values


def test_dependency_scanning_ignores_comments_preserves_strings():
    text='// DefineAnalysis(Fake) RestFrames\n/* addONNX("x","fake.onnx"); */\nDefineAnalysis(Actual)\naddONNX("x","actual.onnx");\nLabRecoFrame* LAB;'
    code=builder.strip_comments(text)
    assert 'Fake' not in code and 'fake.onnx' not in code and 'actual.onnx' in code
    features=builder.feature_signals(text,'Leading jet production')
    assert 'onnx' in features and 'restframes' in features and 'heavy-ion-domain' not in features


@pytest.mark.parametrize('text',['Pb+Pb','p--Pb',"['p+', 'Pb']",'Nuclear modification','lead-lead'])
def test_nuclear_domain_cues(text):
    assert 'heavy-ion-domain' in builder.feature_signals('',text)


def _git(root,*args):
    env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1'}
    return subprocess.check_output(['git','-C',str(root),*args],env=env).decode().strip()


def test_source_verification_rejects_dirty_bytes_wrong_head_and_symlink(tmp_path):
    root=tmp_path/'upstream';root.mkdir(); _git(root,'init','-q')
    _git(root,'config','user.name','Test');_git(root,'config','user.email','test@example.invalid')
    p=root/'routine.cc';p.write_text('original fixture\n')
    _git(root,'add','.');_git(root,'commit','-qm','fixture')
    rev=_git(root,'rev-parse','HEAD'); blob=_git(root,'hash-object','routine.cc')
    row={'id':'rivet:TEST','source_id':'rivet','source_files':[{'path':'routine.cc','git_blob':blob,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}]}
    c={'sources':{'rivet':{'revision':rev}}}
    assert ac.verify_source(c,row,root)['status']=='PASS'
    p.write_text('tampered\n'); assert ac.verify_source(c,row,root)['status']=='FAIL'
    p.write_text('original fixture\n'); _git(root,'commit','--allow-empty','-qm','other')
    assert ac.verify_source(c,row,root)['status']=='FAIL'
    _git(root,'checkout','-q',rev); outside=tmp_path/'outside.cc';outside.write_text(p.read_text());p.unlink();p.symlink_to(outside)
    result=ac.verify_source(c,row,root); assert result['status']=='FAIL' and any('symlink' in i for i in result['issues'])
    assert not result['compute_authorized'] and not result['physics_validated']


def test_cli_needs_no_simulation_dependencies(capsys,monkeypatch):
    def no_launch(*a,**k): raise AssertionError('unexpected subprocess')
    monkeypatch.setattr(subprocess,'run',no_launch)
    assert cli.main(['analyses','summary'])==0
    data=json.loads(capsys.readouterr().out); assert data['entries']==633 and data['compute_authorized'] is False
    assert cli.main(['analyses','show','EwkCompressed2018'])==0
    assert json.loads(capsys.readouterr().out)['physics_validated'] is False
    assert cli.main(['analyses','show','SUSY-2018-16'])==2
    assert 'ambiguous' in capsys.readouterr().err
    assert cli.main(['analyses','list','--query','impossible-key','--json'])==0
    assert json.loads(capsys.readouterr().out)['matches']==0


def test_browser_data_is_bound_to_catalogue(catalog):
    import csv
    import re
    audit=ROOT/'evidence/audits/2026-09-26-analysis-landscape'
    with (audit/'routines.csv').open() as f: csv_rows=list(csv.DictReader(f))
    assert {r['id'] for r in csv_rows}=={r['id'] for r in catalog['entries']}
    page=(audit/'index.html').read_text()
    content=re.search(r'<script id="data" type="application/json">(.*?)</script>',page,re.S)[1]
    embedded=json.loads(content)
    assert len(embedded)==633
    for item in embedded:
        current=ac.adaptation_packet(catalog,ac.resolve(catalog,item['id']))
        # This immutable survey predates the supplied-event executor. Compare
        # its discovery facts and check the newly added operational route apart.
        route=current.pop('supplied_event_route')
        assert route['backend'] in ('rivet','simpleanalysis')
        assert route['guide']=='docs/workflow/reference/scientific-studies.md'
        assert item['packet']==current
    assert '<script src=' not in page and 'fetch(' not in page


def test_frozen_bundle_rejects_mutation_and_omission(tmp_path):
    import shutil
    base=ROOT/'evidence/audits/2026-09-26-analysis-landscape'
    spec=importlib.util.spec_from_file_location('landscape_verify',base/'verify.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.verify(base)['status']=='PASS'
    copy_to=tmp_path/'bundle';shutil.copytree(base,copy_to)
    csv_path=copy_to/'routines.csv';original=csv_path.read_bytes();csv_path.write_bytes(original+b'\n')
    assert module.verify(copy_to)['status']=='FAIL'
    csv_path.write_bytes(original);(copy_to/'retrieval.json').unlink()
    assert module.verify(copy_to)['status']=='FAIL'
