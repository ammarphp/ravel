"""Portable supplied-source/optional-provider/export controls; no kernel/native."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile
from ravel.workflow import execution

import pytest
from ravel.physics import model_sources as sources
from ravel.workflow import science

def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def write(path,value):path.write_text(json.dumps(value));return path

@pytest.fixture
def setup(tmp_path):
    tree=tmp_path/'supplied';tree.mkdir();(tree/'particles.py').write_text('source fixture, never imported')
    (tree/'configure').write_text('source shell fixture, never executed');(tree/'configure').chmod(0o700)
    manifest=write(tmp_path/'source.json',sources.custody.source_tree(tree))
    c={'schema_version':1,'source':'Synthetic source package only','baseline_kind':'supplied-ufo',
       'assets':[{'id':'model','kind':'ufo-source','source':'attributed fixture','license':'private fixture only',
        'file':None,'tree':{'root':str(tree),'manifest':pin(manifest)}}],
       'symbolic_provider':None,'export_policy':'private_source_cache_only','reuse':None}
    config=write(tmp_path/'config.json',c)
    return tmp_path,config,c,tree

def test_connected_mode_and_actual_source_origin():
    root=Path(__file__).resolve().parents[1]
    expected=root/'candidate/src/ravel/physics/model_sources.py' if (root/'candidate/src').is_dir() else Path(__file__).resolve().parents[2]/'src/ravel/physics/model_sources.py'
    assert Path(sources.__file__).resolve()==expected
    assert science.adapter({'mode':'model-sources','task':{}}) is sources
    assert science._new_capability({'mode':'model-sources'}) is True

def test_baseline_independent_of_wolfram_export_and_reuse(setup):
    base,config,c,tree=setup
    task={'config':str(config)}
    info=sources.inspect(task,base)
    assert info['baseline_available'] and info['symbolic_provider']['configured'] is False
    first=base/'first';answer=sources.materialize(task,base,first)
    assert answer['native_calls']==answer['activation_calls']==0 and answer['physics_validated'] is False
    restored=base/'restored-source'
    sources.restore_source_bundle(pin(first/'source-capsule.json'),base,restored)
    assert stat.S_IMODE((restored/'model/configure').stat().st_mode)==0o700
    consumer=json.loads((first/'asset-inputs.json').read_text())['assets']['model']
    tree_input={'root':str(restored/'model'),'manifest':consumer['bundle']['manifest']}
    root,manifest,files=sources.custody._tree(tree_input,base)
    assert root==restored/'model' and len(files)==2 and consumer['bundle']['restore_required']
    c['reuse']=pin(first/'source-capsule.json');write(config,c)
    assert sources.inspect(task,base)['cache_reusable']
    assert sources.materialize(task,base,base/'second')['cache_reused']

@pytest.mark.parametrize('mutation',['addition','deletion','bytes','mode','alias','contract'])
def test_cache_mutation_is_not_reused(setup,mutation):
    base,config,c,tree=setup;task={'config':str(config)};first=base/'first'
    sources.materialize(task,base,first);c['reuse']=pin(first/'source-capsule.json')
    if mutation=='contract':c['assets'][0]['license']='changed provenance'
    elif mutation=='alias':
        archive=first/'source-assets.zip';other=base/'same.zip';other.write_bytes(archive.read_bytes());archive.unlink();archive.symlink_to(other)
    else:
        mutate_bundle(first,mutation)
        c['reuse']=pin(first/'source-capsule.json')
    write(config,c)
    with pytest.raises(ValueError):sources.inspect(task,base)

def provider(base,present):
    kernel=base/'WolframKernel'
    if present:kernel.write_text('kernel fixture, never executed');kernel.chmod(0o700)
    metadata=base/'Info.plist'
    if present:metadata.write_text('metadata fixture')
    package=base/'symbolic-package';package.mkdir();(package/'FeynRules.m').write_text('symbolic source fixture, never loaded')
    manifest=write(base/'provider-source.json',sources.custody.source_tree(package))
    return {'kind':'wolfram-feynrules','kernel':pin(kernel) if present else {'path':str(kernel),'sha256':'a'*64},
        'application_metadata':pin(metadata) if present else {'path':str(metadata),'sha256':'b'*64},
        'package_source':{'root':str(package),'manifest':pin(manifest)},'last_attempt':None,
        'license_note':'No current license or compatibility qualification; fixture only.'}

@pytest.mark.parametrize('present',[False,True])
def test_optional_provider_detects_presence_without_invocation_or_legal_claim(setup,present,monkeypatch):
    base,config,c,tree=setup;c['symbolic_provider']=provider(base,present);write(config,c)
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:pytest.fail('source detection launched process'))
    info=sources.inspect({'config':str(config)},base)
    assert info['baseline_available']
    assert info['symbolic_provider']['kernel_present'] is present
    assert info['symbolic_provider']['runtime_qualified'] is False
    assert info['symbolic_provider']['license_rights_qualified'] is False
    out=base/'export';sources.materialize({'config':str(config)},base,out)
    assert not any('wolfram' in n.lower() for n in json.loads((out/'source-capsule.json').read_text())['files'])

def test_historical_failure_is_retained_without_current_license_inference(setup):
    base,config,c,tree=setup;c['symbolic_provider']=provider(base,True)
    failed=write(base/'failed.json',{'stage_status':'failed','returncode':63})
    c['symbolic_provider']['last_attempt']=pin(failed);write(config,c)
    observed=sources.inspect({'config':str(config)},base)['symbolic_provider']
    assert observed['last_attempt_is_historical_only'] and observed['runtime_qualified'] is False

@pytest.mark.parametrize('name',['WolframKernel','mathpass','Licensing/password'])
def test_export_excludes_engine_and_credentials_even_without_provider(setup,name):
    base,config,c,tree=setup;p=tree/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('excluded fixture')
    manifest=write(base/'source.json',sources.custody.source_tree(tree));c['assets'][0]['tree']['manifest']=pin(manifest);write(config,c)
    with pytest.raises(ValueError,match='excludes'):sources.inspect({'config':str(config)},base)

def test_cannot_relabel_configured_engine_bytes_as_parameter_card(setup):
    base,config,c,tree=setup;c['symbolic_provider']=provider(base,True)
    disguised=base/'model-card.dat';disguised.write_bytes((base/'WolframKernel').read_bytes())
    c['assets'].append({'id':'card','kind':'parameter-card','source':'fixture','license':'fixture','file':pin(disguised),'tree':None});write(config,c)
    with pytest.raises(ValueError,match='re-labelled'):sources.inspect({'config':str(config)},base)

def test_pregenerated_baseline_and_missing_source_kind(setup):
    base,config,c,tree=setup;c['baseline_kind']='pregenerated-spectrum';write(config,c)
    with pytest.raises(ValueError):sources.inspect({'config':str(config)},base)
    c['assets'][0]['kind']='generated-spectrum-source';write(config,c)
    assert sources.inspect({'config':str(config)},base)['baseline_available']

@pytest.mark.parametrize('mutation',['bytes','addition','alias','untrusted-export','missing-attribution'])
def test_source_identity_and_scope_refuse(setup,mutation):
    base,config,c,tree=setup
    if mutation=='bytes':(tree/'particles.py').write_text('changed')
    elif mutation=='addition':(tree/'new.json').write_text('{}')
    elif mutation=='alias':
        p=tree/'particles.py';other=base/'other';other.write_bytes(p.read_bytes());p.unlink();p.symlink_to(other)
    elif mutation=='untrusted-export':c['export_policy']='redistribute-engine'
    elif mutation=='missing-attribution':c['assets'][0]['license']=''
    write(config,c)
    with pytest.raises(ValueError):sources.inspect({'config':str(config)},base)

def test_unapproved_study_cannot_materialize(setup,monkeypatch):
    base,config,c,tree=setup
    monkeypatch.setattr(sources,'materialize',lambda *a:pytest.fail('unapproved export reached'))
    with pytest.raises(ValueError,match='approved supervised'):sources.run({'config':str(config)},base,base/'out')

def test_approved_worker_exports_only_exact_admitted_task_and_destination(setup,monkeypatch):
    base,config,c,tree=setup;rd=base/'run';(rd/'inputs').mkdir(parents=True)
    (rd/'inputs/science-plan.json').write_text('{}');out=rd/'outputs/attempt-1';task={'config':str(config)}
    monkeypatch.setattr(science,'verify_worker',lambda candidate:{'output_directory':'outputs/attempt-1'})
    monkeypatch.setattr(science,'execution_spec',lambda candidate:{'mode':'model-sources','task':task})
    assert sources.run(task,base,out)['native_calls']==0
    with pytest.raises(ValueError,match='differs from approved'):sources.run({'config':'different.json'},base,out)

def test_export_refuses_overwriting_nonempty_output(setup):
    base,config,c,tree=setup;out=base/'out';out.mkdir();(out/'original').write_text('preserve')
    with pytest.raises(ValueError,match='fresh ordinary'):sources.materialize({'config':str(config)},base,out)

@pytest.mark.parametrize('mutation',['source-bytes','source-addition','source-mode','provider-appears'])
def test_ending_source_census_and_optional_presence_are_bound(setup,mutation,monkeypatch):
    base,config,c,tree=setup
    if mutation=='provider-appears':
        c['symbolic_provider']=provider(base,False)
        c['symbolic_provider']['kernel']['sha256']=hashlib.sha256(b'new exact kernel').hexdigest();write(config,c)
    real=sources.shutil.copyfileobj;done=False
    def changed(source,destination):
        nonlocal done
        answer=real(source,destination)
        if not done:
            done=True
            if mutation=='source-bytes':(tree/'particles.py').write_text('changed after copy')
            elif mutation=='source-addition':(tree/'new.json').write_text('{}')
            elif mutation=='source-mode':(tree/'configure').chmod(0o600)
            else:(base/'WolframKernel').write_bytes(b'new exact kernel')
        return answer
    monkeypatch.setattr(sources.shutil,'copyfileobj',changed)
    with pytest.raises(ValueError):sources.materialize({'config':str(config)},base,base/'out')

def test_source_fifo_cannot_hide_outside_regular_file_census(setup):
    base,config,c,tree=setup;os.mkfifo(tree/'new-asset')
    with pytest.raises(ValueError,match='special files'):sources.inspect({'config':str(config)},base)

def test_output_alias_with_identical_bytes_is_refused(setup,monkeypatch):
    base,config,c,tree=setup;real=sources._write_bundle
    def aliased(bundle,files,modes):
        real(bundle,files,modes);other=base/'identical.zip';other.write_bytes(bundle.read_bytes());bundle.unlink();bundle.symlink_to(other)
    monkeypatch.setattr(sources,'_write_bundle',aliased)
    with pytest.raises(ValueError,match='custody changed'):sources.materialize({'config':str(config)},base,base/'out')

def test_provider_executable_mode_cannot_change_during_export(setup,monkeypatch):
    base,config,c,tree=setup;c['symbolic_provider']=provider(base,True);write(config,c)
    real=sources.shutil.copyfileobj
    def changed(source,destination):
        answer=real(source,destination);(base/'WolframKernel').chmod(0o600);return answer
    monkeypatch.setattr(sources.shutil,'copyfileobj',changed)
    with pytest.raises(ValueError,match='custody changed'):sources.materialize({'config':str(config)},base,base/'out')


def mutate_bundle(output,mutation):
    archive=output/'source-assets.zip'
    with zipfile.ZipFile(archive) as source:
        rows=[(info,source.read(info)) for info in source.infolist()]
    archive.unlink()
    if mutation=='addition':
        info=zipfile.ZipInfo('model/new.json');info.create_system=3;info.external_attr=(stat.S_IFREG|0o600)<<16;rows.append((info,b'{}'))
    elif mutation=='deletion':rows=rows[1:]
    elif mutation=='bytes':rows[0]=(rows[0][0],b'changed bytes')
    elif mutation=='mode':rows[0][0].external_attr=(stat.S_IFREG|0o600)<<16
    elif mutation=='duplicate':rows.append(rows[0])
    elif mutation=='traversal':rows[0][0].filename='../escape'
    elif mutation=='symlink':rows[0][0].external_attr=(stat.S_IFLNK|0o700)<<16
    elif mutation=='compression':rows[0][0].compress_type=zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(archive,'w') as target:
        for info,data in rows:target.writestr(info,data)
    manifest=output/'source-capsule.json';doc=json.loads(manifest.read_text())
    doc['bundle']['sha256']=pin(archive)['sha256'];doc['bundle']['bytes']=archive.stat().st_size
    write(manifest,doc)

@pytest.mark.parametrize('mutation',['duplicate','traversal','symlink','compression'])
def test_rebound_bad_archive_is_refused_before_restore(setup,mutation):
    base,config,c,tree=setup;first=base/'first';sources.materialize({'config':str(config)},base,first)
    mutate_bundle(first,mutation);dest=base/'must-not-exist'
    with pytest.raises(ValueError):sources.restore_source_bundle(pin(first/'source-capsule.json'),base,dest)
    assert not dest.exists()

def test_complete_empty_source_survives_bundle_restore_and_public_output_snapshot(setup):
    base,config,c,tree=setup;(tree/'legitimate-empty.rst').touch()
    manifest=write(base/'source.json',sources.custody.source_tree(tree));c['assets'][0]['tree']['manifest']=pin(manifest);write(config,c)
    out=base/'export';answer=sources.materialize({'config':str(config)},base,out)
    public=execution.snapshot(base,[str(out)],outputs=True)
    assert len(public[str(out)]['files'])==5 and all(p.stat().st_size>0 for p in out.iterdir())
    assert answer['empty_source_members']==['model/legitimate-empty.rst'] and answer['source_files']==3
    restored=base/'full-restored';result=sources.restore_source_bundle(pin(out/'source-capsule.json'),base,restored)
    assert result['files']==3 and (restored/'model/legitimate-empty.rst').read_bytes()==b''
    assert result['approval_inherited'] is False
    consumer=json.loads((out/'asset-inputs.json').read_text())['assets']['model']
    _,_,members=sources.custody._tree({'root':str(restored/'model'),'manifest':consumer['bundle']['manifest']},base)
    assert len(members)==3
    planned=execution.plan_stage(base,'source-custody',[sys.executable,'-c','pass'],[str(restored/p) for p in json.loads((out/'source-capsule.json').read_text())['files']],[str(base/'future-output')],[],str(base))
    admitted={str((restored/p).resolve()) for p in json.loads((out/'source-capsule.json').read_text())['files']}
    assert admitted <= set(planned['input_snapshot'])
    empty=str((restored/'model/legitimate-empty.rst').resolve())
    assert planned['input_snapshot'][empty]['files'][0]['size']==0
    c['reuse']=pin(out/'source-capsule.json');write(config,c)
    second=base/'second';sources.materialize({'config':str(config)},base,second)
    assert (second/'source-assets.zip').read_bytes()==(out/'source-assets.zip').read_bytes()
    execution.snapshot(base,[str(second)],outputs=True)

@pytest.mark.parametrize('kind',['alias','dotdot','existing'])
def test_restore_refuses_noncanonical_or_existing_destination(setup,kind):
    base,config,c,tree=setup;out=base/'bundle';sources.materialize({'config':str(config)},base,out)
    if kind=='alias':
        alias=base/'alias';alias.symlink_to(base,target_is_directory=True);destination=alias/'new'
    elif kind=='dotdot':
        (base/'existing-parent').mkdir();destination=base/'existing-parent'/'..'/'new'
    else:destination=base/'existing';destination.mkdir();(destination/'original').write_text('preserve')
    with pytest.raises(ValueError):sources.restore_source_bundle(pin(out/'source-capsule.json'),base,destination)
    if kind=='existing':assert (destination/'original').read_text()=='preserve'
