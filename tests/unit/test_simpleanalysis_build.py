"""Pure native source/graph admission controls; no compiler or ATLAS witness."""
import base64
import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from ravel.physics.simpleanalysis_build import verify_compiler_graph
from ravel.physics import simpleanalysis_build as build
from ravel.physics import routine_build


def fixture(tmp_path):
    out=tmp_path/'build';guest=out/'container-output';reply=guest/'cmake-reply';reply.mkdir(parents=True)
    staged=out/'container-input/work/source/Framework';staged.mkdir(parents=True)
    raw=b'DefineAnalysis(ActualSourceControl)\n';(staged/'real.cxx').write_bytes(raw)
    source='/tmp/ravel-work/source/Framework/real.cxx';generated='/tmp/ravel-work/build/generated-dictionary.cxx'
    driver={'path':'/qualified/compiler/g++','sha256':'a'*64}
    (out/'container-input/source-contract.json').write_text(json.dumps({'guest':{'tools':{'compiler':driver}}}))
    active={'path':'Framework/real.cxx','role':'compile','sha256':hashlib.sha256(raw).hexdigest()}
    excluded={'path':'SimpleAnalysisFramework/util/slimMaker.cxx','role':'compile','sha256':'b'*64}
    plan={'source_inventory':{'files':[active,excluded]},'recipe':{'compile_units':['Framework/real.cxx']}}
    (reply/'index-1.json').write_text(json.dumps({'reply':{'codemodel-v2':{'jsonFile':'model.json'}}}))
    model={'paths':{'build':'/tmp/ravel-work/build'},'configurations':[{'targets':[{'jsonFile':'exe.json'},{'jsonFile':'lib.json'}]}]}
    (reply/'model.json').write_text(json.dumps(model))
    (reply/'exe.json').write_text(json.dumps({'name':'simpleAnalysis','sources':[]}))
    (reply/'lib.json').write_text(json.dumps({'name':'SimpleAnalysisFrameworkLib','sources':[{'path':generated,'isGenerated':True,'compileGroupIndex':0}]}))
    commands=[];rows=[]
    for pid,path,contents in [(10,source,raw),(11,generated,b'generated dictionary control\n')]:
        argv=[driver['path'],'-O2','-o',str(pid)+'.o','-c',path]
        commands.append({'directory':'/tmp/ravel-work/build','file':path,'arguments':argv})
        rows.append({'schema_version':1,'pid':pid,'driver_path':driver['path'],'driver_sha256':driver['sha256'],
            'argv':argv,'cwd':'/tmp/ravel-work/build','environment':{'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'},
            'compile_inputs':[{'path':path,'sha256':hashlib.sha256(contents).hexdigest(),'content_base64':base64.b64encode(contents).decode()}]})
    (guest/'compile_commands.json').write_text(json.dumps(commands))
    (guest/'compiler-invocations.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    return out,guest,reply,plan,rows,commands


def test_observed_full_target_sources_and_generated_dictionary_are_separate_from_alternate_target(tmp_path):
    out,_,_,plan,_,_=fixture(tmp_path)
    proof=verify_compiler_graph(plan,out)
    assert proof['source_units_declared']==2 and proof['source_units_compiled']==1
    assert proof['excluded_unbuilt_target_sources']==['SimpleAnalysisFramework/util/slimMaker.cxx']
    assert len(proof['observed_generated_units'])==1 and proof['physics_validated'] is False


@pytest.mark.parametrize('defect',['wrong_driver','changed_source','missing_unit','duplicate_unit','missing_dictionary','unbound_generated','argv_flags','wrong_cwd','workers','missing_full_target','escaped_target_reference'])
def test_whole_target_admission_refuses_incomplete_or_rehashed_source_process_graph(tmp_path,defect):
    out,guest,reply,plan,rows,commands=fixture(tmp_path)
    if defect=='wrong_driver':rows[0]['driver_sha256']='c'*64
    elif defect=='changed_source':
        new=b'changed source';rows[0]['compile_inputs'][0].update(content_base64=base64.b64encode(new).decode(),sha256=hashlib.sha256(new).hexdigest())
    elif defect=='missing_unit':rows.pop(0)
    elif defect=='duplicate_unit':rows.append(copy.deepcopy(rows[0]))
    elif defect=='missing_dictionary':rows.pop(1)
    elif defect=='unbound_generated':
        d=json.loads((reply/'lib.json').read_text());d['sources'][0]['isGenerated']=False;(reply/'lib.json').write_text(json.dumps(d))
    elif defect=='argv_flags':rows[0]['argv'].insert(1,'-DUNREVIEWED_SELECTION=1')
    elif defect=='wrong_cwd':rows[0]['cwd']='/other/build'
    elif defect=='workers':rows[0]['environment']['OMP_NUM_THREADS']='2'
    elif defect=='missing_full_target':(reply/'exe.json').write_text(json.dumps({'name':'slimMaker','sources':[]}))
    elif defect=='escaped_target_reference':
        d=json.loads((reply/'model.json').read_text());d['configurations'][0]['targets'][0]['jsonFile']='../escaped.json';(reply/'model.json').write_text(json.dumps(d))
    (guest/'compiler-invocations.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    with pytest.raises(ValueError):verify_compiler_graph(plan,out)


def configured_fixture(tmp_path):
    # Supplied protocol controls only; none of these records are an ATLAS image
    # acquisition or native compiler attestation.
    from test_simpleanalysis_recipe import fixture as recipe_fixture
    from test_simpleanalysis_container import fixture as container_fixture
    from ravel.physics.simpleanalysis_recipe import prepare_inputs
    from ravel.physics import simpleanalysis_container as transport
    root,capsule,externals,guest=recipe_fixture(tmp_path)
    _,config,_,_=container_fixture(tmp_path)
    qualifier=Path(config['qualification']['path']);observed=json.loads(qualifier.read_text());observed['source_acquisitions']=[]
    for name,entry in externals.items():
        archive=tmp_path/(name+'.archive');archive.write_bytes(('explicit archive control '+name).encode())
        entry['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
        extracted=tmp_path/(name+'-source');project=extracted/(name+'-'+entry['source_commit'])
        shutil.copytree(entry['root'],project);entry['root']=str(project)
        census=transport.tree_facts(extracted);census_path=tmp_path/(name+'-source-files.json');census_path.write_text(json.dumps(census))
        observed['source_acquisitions'].append({'name':name,'commit':entry['source_commit'],'sha256':entry['archive_sha256'],'path':str(archive),
            'extracted_root':str(extracted),'ordinary_files':len(census),'source_files_sha256':hashlib.sha256(census_path.read_bytes()).hexdigest()})
    qualifier.write_text(json.dumps(observed));config['qualification'].update(sha256=hashlib.sha256(qualifier.read_bytes()).hexdigest(),size=qualifier.stat().st_size)
    guest['qualification_sha256']=config['qualification']['sha256']
    prepared=tmp_path/'native-prepared';prepare_inputs(capsule,tmp_path,prepared,external_sources=externals,guest=guest)
    job=transport.make_plan(config,prepared,max_seconds=120)
    (tmp_path/'native-job.json').write_text(json.dumps(job));(tmp_path/'capsule.json').write_text(json.dumps(capsule))
    specification={'schema_version':3,'source_capsule':'capsule.json','recipe':{'name':'simpleanalysis-analysisbase','compile_units':['Framework/real.cxx'],'output':guest['binary_relative'],'flags':[]},'container_plan':'native-job.json'}
    (tmp_path/'build.json').write_text(json.dumps(specification))
    return {'backend':'routine-build','input':'build.json'},prepared,job


def test_native_configuration_inputs_and_plan_are_read_only_and_bind_exact_offline_source(tmp_path,monkeypatch):
    task,prepared,_=configured_fixture(tmp_path)
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:pytest.fail('native preparation executed a process'))
    plan=build.build_plan(task,tmp_path,tmp_path/'output')
    facts=build.inputs(task,tmp_path)
    assert plan['schema_version']==3 and plan['framework']=='simpleanalysis'
    assert plan['compute_authorized'] is False and plan['physics_validated'] is False
    assert set(plan['routine_bindings'])=={'RealAnalysis'}
    assert prepared/'native-observer.c' in facts and tmp_path/'HepMC3.archive' in facts
    assert tmp_path/'HepMC3-source-files.json' in facts
    assert tmp_path/('HepMC3-source/HepMC3-'+'c'*40+'/source.txt') in facts
    assert not (tmp_path/'output').exists()
    assert routine_build.build_plan(task,tmp_path,tmp_path/'output')==plan
    assert routine_build.inputs(task,tmp_path)==facts
    assert routine_build.seal_configuration(task,tmp_path)['schema_version']==3
    with pytest.raises(ValueError,match='legacy'):
        routine_build.build_plan(task,tmp_path,tmp_path/'output',_legacy=True)


@pytest.mark.parametrize('defect',['prepared_script','original_source','observer','archive','unresolved'])
def test_source_or_qualification_drift_refuses_before_a_native_client_runs(tmp_path,monkeypatch,defect):
    task,prepared,_=configured_fixture(tmp_path)
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:pytest.fail('changed native input executed a process'))
    if defect=='prepared_script':(prepared/'run.sh').write_text('altered script')
    elif defect=='original_source':(tmp_path/'source/Framework/real.cxx').write_text('altered source')
    elif defect=='observer':(prepared/'native-observer.c').write_text('altered observer')
    elif defect=='archive':(tmp_path/'HepMC3.archive').write_text('altered archive')
    elif defect=='unresolved':
        path=tmp_path/'capsule.json';capsule=json.loads(path.read_text());capsule['dependency_review']['complete']=False;path.write_text(json.dumps(capsule))
    with pytest.raises(ValueError):build.build_plan(task,tmp_path,tmp_path/'output')


def _rebind_prepared_control(tmp_path, prepared, job):
    """Rehash producer-owned declarations without altering qualification."""
    from ravel.physics import simpleanalysis_container as transport
    updated=transport.make_plan(job['transport'],prepared,max_seconds=job['resources']['max_seconds'],memory_mib=job['resources']['memory_mib'])
    (tmp_path/'native-job.json').write_text(json.dumps(updated))
    return updated


@pytest.mark.parametrize('defect',['different_tree_rehashed','same_bytes_other_root','partial_project_root','qualified_file_changed','qualified_file_removed','qualified_extra_file','census_missing','census_changed','census_count','duplicate_acquisition','multiple_project_roots'])
def test_offline_dependencies_rebind_complete_qualified_extraction_not_self_declared_trees(tmp_path,monkeypatch,defect):
    task,prepared,job=configured_fixture(tmp_path)
    monkeypatch.setattr('subprocess.run',lambda *args,**kwargs:pytest.fail('source custody refusal executed a native client'))
    contract_path=prepared/'source-contract.json';contract=json.loads(contract_path.read_text());entry=contract['external_sources']['HepMC3']
    root=Path(entry['root']);qualified=root/'source.txt';census_path=tmp_path/'HepMC3-source-files.json'
    if defect in ('different_tree_rehashed','same_bytes_other_root'):
        other=tmp_path/'other-project';shutil.copytree(root,other)
        if defect=='different_tree_rehashed':
            (other/'source.txt').write_text('unqualified altered dependency')
            (prepared/'work/externals/HepMC3/source.txt').write_text('unqualified altered dependency')
        entry.update(root=str(other),files=build.container.tree_facts(other));contract_path.write_text(json.dumps(contract));_rebind_prepared_control(tmp_path,prepared,job)
    elif defect=='partial_project_root':
        inner=root/'unqualified-subtree';inner.mkdir();(inner/'source.txt').write_text('partial')
        entry.update(root=str(inner),files=build.container.tree_facts(inner));contract_path.write_text(json.dumps(contract));_rebind_prepared_control(tmp_path,prepared,job)
    elif defect=='qualified_file_changed':qualified.write_text('qualified path drift')
    elif defect=='qualified_file_removed':qualified.unlink()
    elif defect=='qualified_extra_file':(root/'added.txt').write_text('undeclared')
    elif defect=='census_missing':census_path.unlink()
    elif defect=='census_changed':census_path.write_text('{}')
    else:
        qp=Path(job['transport']['qualification']['path']);q=json.loads(qp.read_text())
        if defect=='census_count':q['source_acquisitions'][0]['ordinary_files']+=1
        elif defect=='duplicate_acquisition':q['source_acquisitions'].append(copy.deepcopy(q['source_acquisitions'][0]))
        elif defect=='multiple_project_roots':
            extra=root.parent/'extra-project';extra.mkdir();(extra/'alien.txt').write_text('foreign')
            census=build.container.tree_facts(root.parent);census_path.write_text(json.dumps(census));q['source_acquisitions'][0].update(ordinary_files=len(census),source_files_sha256=hashlib.sha256(census_path.read_bytes()).hexdigest())
        qp.write_text(json.dumps(q));job['transport']['qualification'].update(sha256=hashlib.sha256(qp.read_bytes()).hexdigest(),size=qp.stat().st_size)
        contract['guest']['qualification_sha256']=job['transport']['qualification']['sha256'];contract_path.write_text(json.dumps(contract));_rebind_prepared_control(tmp_path,prepared,job)
    with pytest.raises(ValueError):build.build_plan(task,tmp_path,tmp_path/'output')
    assert not (tmp_path/'output').exists()
