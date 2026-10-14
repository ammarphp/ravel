"""Adverse external landscape intake controls; no source/native execution."""
import synthetic_identifiers as syn
import copy
import hashlib
import json
from pathlib import Path

import pytest

from ravel import analysis_sources
from ravel.coverage_landscape import load_landscape


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write_artifact(root, kind, document):
    path=root/(kind+'.json');path.write_text(json.dumps(document,sort_keys=True)+'\n')
    return {'path':path.name,'sha256':digest(path),'bytes':path.stat().st_size}


def package(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'models').mkdir()
    (source/'main.cc').write_text('int main() { return 0; }\n')
    (source/'models/model.json').write_text('{"calibration":"unqualified"}\n')
    scope={'cpp':{'repository':'supplied','revision':None,'submodules':[]}}
    identity={'analysis_ids':['ANALYSIS-ALPHA'],'primary_inspire_ids':['123','999'],'official_arxiv_ids':[(syn.arxiv(224))]}
    alpha={'routine_id':'cpp:Alpha','framework':'cpp','name':'Alpha','eligible_implementation':True,
           'identity':identity,'source_files':[{'path':'main.cc','sha256':digest(source/'main.cc')}],
           'source_semantic_requirements':[{'primitive':'detector_response','state':'unknown'}]}
    beta=copy.deepcopy(alpha);beta.update(routine_id='cpp:Beta',name='Beta',identity={'analysis_ids':[], 'primary_inspire_ids':['999'], 'official_arxiv_ids':[]})
    alias=copy.deepcopy(alpha);alias.update(routine_id='cpp:Alias',name='Alias',eligible_implementation=False,identity={'analysis_ids':[], 'primary_inspire_ids':[], 'official_arxiv_ids':[]},source_files=[])
    seed={'schema_version':1,'kind':'analysis-source-capsule','framework':'cpp','routine':'Alpha',
          'source':{'repository':'supplied','revision':None,'description':'Structural fixture; no physics/source closure'},
          'root':'.','files':[{'path':'main.cc','sha256':digest(source/'main.cc'),'role':'compile'}, {'path':'models/model.json','sha256':digest(source/'models/model.json'),'role':'preprocessing'}],
          'layout':{'include_dirs':[],'asset_dirs':['models']},
          'dependencies':[{'name':'native closure','kind':'runtime','status':'unresolved','files':[],'reason':'Not qualified'}],
          'dependency_review':{'complete':False,'description':'Unresolved runtime and scientific source review'},'submodules':[]}
    documents={'atlas':{'schema_version':1,'source_scope':scope,'routines':[alpha,beta,alias]},
               'capsules':{'schema_version':1,'records':[{'routine_id':'cpp:Alpha','capsule':seed}]},
               'resources':{'schema_version':1,'recovery_population_complete':True,'routines':[{'routine_id':'cpp:Alpha','exact_hepdata_metadata_matches':[{'record':321,'numeric_contents':'unknown'}],'metadata_labels':['covariance']}]},
               'native_records':{'schema_version':1,'records':[{'record_id':'cms-record','cms_analysis_ids':[(syn.analysis(27))],'analysis_inspire_ids':['444'],'analysis_arxiv_ids':[(syn.arxiv(679))]}]},
               'native_contracts':{'schema_version':1,'records':[{'record_id':'cms-record','requirements':[{'primitive':'discrete_model','state':'unknown'}]}]},
               'measurements':{'schema_version':1,'records':[{'routine_id':'cpp:Alpha','experimental_covariance':'unknown','execution_or_physics_validated':False}]}}
    manifest={'schema_version':1,'kind':'analysis-coverage-landscape','source_scope':scope,
              'population':{'raw_rows':3,'eligible_rows':2,'all_lhc_paper_census_complete':False},
              'artifacts':{kind:write_artifact(tmp_path,kind,doc) for kind,doc in documents.items()}}
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest)+'\n')
    return path,source,manifest,documents


def repin(path, manifest, kind, document):
    manifest['artifacts'][kind]=write_artifact(path.parent,kind,document)
    path.write_text(json.dumps(manifest)+'\n')


def test_exact_routing_boundaries_and_source_population(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:pytest.fail('landscape invoked executable'))
    path,source,manifest,docs=package(tmp_path);landscape=load_landscape(path,expected_sha256=digest(path))
    assert landscape.summary()['population']['eligible_rows']==2
    assert landscape.summary()['eligible_exact_metadata_join_rows']==1
    for identifier in ['Alpha','cpp:Alpha','ANALYSIS-ALPHA','123','ins123',(syn.arxiv(224)),('arXiv:' + syn.arxiv(224))]:
        result=landscape.intake(identifier,'measurement')
        assert result['resolution']=='exact_routine' and result['routines'][0]['name']=='Alpha'
        assert result['physics_coverage_claim'] is False and result['execution_admitted'] is False
        assert result['actual_measurement_source_contracts'][0]['experimental_covariance']=='unknown'
    assert landscape.intake('ins999')['resolution']=='exact_multiple_routines_select_scope'
    assert landscape.intake('tau')['resolution']=='unknown_identifier'
    assert landscape.intake('alpha')['resolution']=='unknown_identifier'
    assert landscape.intake((syn.analysis(27)),'exclusion')['resolution']=='exact_resource_only'
    assert landscape.intake((syn.analysis(27)))['routines']==[]
    with pytest.raises(ValueError,match='objective'):landscape.intake('Alpha','limit')
    for identifier in ['ins999','tau',(syn.analysis(27)),'Alias']:
        with pytest.raises(ValueError):landscape.capsule(identifier,source)


def test_real_source_capsule_schema_and_unresolved_normal_build_refusal(tmp_path):
    from ravel.physics import routine_build
    path,source,_,_=package(tmp_path);seed=load_landscape(path).capsule('Alpha',source)
    analysis_sources.validate_capsule(seed)
    inventory=analysis_sources.inventory(seed,tmp_path)
    assert inventory['declared_files_verified']==2 and inventory['physics_validated'] is False
    assert seed['dependency_review']['complete'] is False
    (tmp_path/'capsule.json').write_text(json.dumps(seed))
    (tmp_path/'routine-build.json').write_text(json.dumps({'schema_version':1,'source_capsule':'capsule.json','recipe':{},'runtime':{},'probe':{}}))
    with pytest.raises(ValueError,match='unresolved declared transitive dependency'):
        routine_build.inputs({'backend':'routine-build','input':'routine-build.json'},tmp_path)
    (source/'models/model.json').write_text('changed')
    with pytest.raises(ValueError,match='bytes differ'):load_landscape(path).capsule('Alpha',source)


def test_cached_evidence_is_not_mutated_by_returned_packet(tmp_path):
    path,_,_,_=package(tmp_path);landscape=load_landscape(path)
    result=landscape.intake('Alpha');result['routines'][0]['name']='Changed';result['population']['eligible_rows']=99
    assert landscape.intake('Alpha')['routines'][0]['name']=='Alpha'
    assert landscape.summary()['population']['eligible_rows']==2


def test_manifest_and_each_consumed_artifact_digest_are_required(tmp_path):
    path,_,manifest,docs=package(tmp_path)
    with pytest.raises(ValueError,match='manifest SHA256'):load_landscape(path,expected_sha256='0'*64)
    (tmp_path/'atlas.json').write_text((tmp_path/'atlas.json').read_text().replace('Alpha','Alphx'))
    with pytest.raises(ValueError,match='SHA256'):load_landscape(path)
    repin(path,manifest,'atlas',docs['atlas']);landscape=load_landscape(path)
    (tmp_path/'resources.json').write_text((tmp_path/'resources.json').read_text().replace('unknown','unknOwn'))
    with pytest.raises(ValueError,match='SHA256'):landscape.intake('Alpha')


@pytest.mark.parametrize('mutation',[
    lambda m:m.update(schema_version=True),
    lambda m:m['population'].update(all_lhc_paper_census_complete=True),
    lambda m:m['population'].update(eligible_rows=True),
    lambda m:m['population'].update(raw_rows=9),
    lambda m:m['artifacts']['atlas'].update(path='../outside.json'),
    lambda m:m['artifacts']['atlas'].update(bytes=100_000_000),
    lambda m:m['artifacts']['atlas'].update(sha256='DEAD'),
    lambda m:m['source_scope']['cpp'].update(revision='a'*40),
    lambda m:m['source_scope']['cpp'].update(repository='https://example.test/source',revision='moving-branch'),
])
def test_manifest_population_paths_sizes_and_source_pins_fail_closed(tmp_path,mutation):
    path,_,manifest,_=package(tmp_path);mutation(manifest);path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):load_landscape(path)


def test_linked_artifact_duplicate_json_and_nonfinite_json_rejected(tmp_path):
    path,_,manifest,docs=package(tmp_path);original=tmp_path/'atlas.json';copy_path=tmp_path/'copy.json';copy_path.write_bytes(original.read_bytes());original.unlink();original.symlink_to(copy_path)
    with pytest.raises(ValueError,match='linked'):load_landscape(path)
    original.unlink();original.write_text('{"schema_version":1,"schema_version":1}')
    manifest['artifacts']['atlas']={'path':'atlas.json','sha256':digest(original),'bytes':original.stat().st_size};path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='duplicate JSON'):load_landscape(path)
    original.write_text('{"a": NaN}')
    manifest['artifacts']['atlas'].update(sha256=digest(original),bytes=original.stat().st_size);path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='nonfinite'):load_landscape(path)


def test_compact_capsule_pool_expands_to_normal_pinned_files(tmp_path):
    path,source,manifest,docs=package(tmp_path);record=docs['capsules']['records'][0];seed=record['capsule'];facts=seed.pop('files');seed['files']=[];record['file_ids']=['compile','model'];docs['capsules']['file_facts']=dict(zip(record['file_ids'],facts))
    repin(path,manifest,'capsules',docs['capsules']);out=load_landscape(path).capsule('Alpha',source)
    assert out['files']==facts and any(d['status']=='unresolved' for d in out['dependencies'])
    record['file_ids'].append('missing');repin(path,manifest,'capsules',docs['capsules'])
    with pytest.raises(ValueError,match='file references'):load_landscape(path).capsule('Alpha',source)


@pytest.mark.parametrize('change',[
    lambda c:c['dependency_review'].update(complete=True),
    lambda c:c.update(routine='Beta'),
    lambda c:c['files'][0].update(sha256='0'*64),
    lambda c:c['files'][0].update(path='../outside.cc'),
    lambda c:c['source'].update(repository='https://example.test/source',revision='a'*40),
])
def test_capsule_cannot_disguise_source_or_dependency_status(tmp_path,change):
    path,source,manifest,docs=package(tmp_path);change(docs['capsules']['records'][0]['capsule']);repin(path,manifest,'capsules',docs['capsules'])
    with pytest.raises(ValueError):load_landscape(path).capsule('Alpha',source)


def test_duplicate_source_and_resource_identities_cannot_inflate_population(tmp_path):
    path,_,manifest,docs=package(tmp_path);docs['atlas']['routines'].append(copy.deepcopy(docs['atlas']['routines'][0]));repin(path,manifest,'atlas',docs['atlas'])
    with pytest.raises(ValueError,match='duplicate'):load_landscape(path)
    docs['atlas']['routines'].pop();repin(path,manifest,'atlas',docs['atlas']);docs['resources']['routines']*=2;repin(path,manifest,'resources',docs['resources'])
    with pytest.raises(ValueError,match='duplicate'):load_landscape(path).summary()


def test_native_identity_strings_cannot_create_character_aliases(tmp_path):
    path,_,manifest,docs=package(tmp_path)
    docs['native_records']['records'][0]['cms_analysis_ids']='tau'
    repin(path,manifest,'native_records',docs['native_records'])
    with pytest.raises(ValueError,match='native exact identifiers'):load_landscape(path).intake('t')


def test_invalid_pooled_file_fact_is_a_closed_intake_refusal(tmp_path):
    path,source,manifest,docs=package(tmp_path)
    record=docs['capsules']['records'][0];record['capsule']['files']=[];record['file_ids']=['bad']
    docs['capsules']['file_facts']={'bad':None}
    repin(path,manifest,'capsules',docs['capsules'])
    with pytest.raises(ValueError,match='pooled file fact'):load_landscape(path).capsule('Alpha',source)


def test_json_numeric_overflow_cannot_evade_nonfinite_rejection(tmp_path):
    path,_,manifest,_=package(tmp_path);artifact=tmp_path/'measurements.json'
    artifact.write_text('{"schema_version":1,"records":[{"routine_id":"cpp:Alpha","x":1e309}]}')
    manifest['artifacts']['measurements'].update(sha256=digest(artifact),bytes=artifact.stat().st_size)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='nonfinite'):load_landscape(path).intake('Alpha')


@pytest.mark.parametrize('change',[
    lambda d:d.update(recovery_population_complete='yes'),
    lambda d:d['routines'][0].update(exact_hepdata_metadata_matches='covariance'),
])
def test_metadata_strings_cannot_inflate_discovery_counts(tmp_path,change):
    path,_,manifest,docs=package(tmp_path);change(docs['resources']);repin(path,manifest,'resources',docs['resources'])
    with pytest.raises(ValueError):load_landscape(path).summary()
