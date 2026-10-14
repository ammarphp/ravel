"""Full released source fixture and authority-local observational proofs only."""
from pathlib import Path
import copy
import os
import shutil
import pytest
from test_sfitter_adapter import fixture, pin, save
from ravel.physics import sfitter_native as native
from ravel.workflow import execution, science
from ravel.workflow.state_io import read_json


@pytest.fixture
def supplied(tmp_path):
    task,config,*_=fixture(tmp_path)
    original=Path(config['upstream_tree']['root'])
    upstream=tmp_path/'upstream';shutil.copytree(original,upstream)
    config['upstream_tree']['root']=str(upstream)
    asset=Path(config['runtime']['assets'][0]['path'])
    assets=[asset]
    for j in range(7):
        p=asset.with_name('asset'+str(j)+'.bin');p.write_bytes(bytes([j])*4096);assets.append(p)
    config['runtime']['assets']=[pin(p) for p in assets]
    save(Path(task['config']),config)
    return task,config,assets,upstream


def test_full_original_inventory_and_budget_are_identical(supplied,tmp_path):
    task,config,assets,upstream=supplied
    before=native.inputs(task,tmp_path)
    session=execution._validation_session(tmp_path)
    try:
        first=native._validation_inputs(task,tmp_path,session)
        calls=session.hash_calls
        second=native._validation_inputs(task,tmp_path,session)
        assert first==second==before and all(p in first for p in assets)
        assert session.hash_calls==calls
        assert native._validation_execution_seconds(task,tmp_path,session)==native.execution_seconds(task,tmp_path)
        assert session.finish()==[]
        assert not session.proofs and not session.hashes
    finally:session.close()


def test_next_operation_reads_again_and_changed_bytes_refuse(supplied,tmp_path):
    task,config,assets,_=supplied
    sessions=[]
    for _ in range(2):
        s=execution._validation_session(tmp_path);sessions.append(s)
        native._validation_inputs(task,tmp_path,s)
        assert s.hash_calls>=len(assets)
        assert s.finish()==[]
    assert sessions[0] is not sessions[1]
    stat=assets[0].stat();assets[0].write_bytes(b'X'*stat.st_size)
    os.utime(assets[0],ns=(stat.st_atime_ns,stat.st_mtime_ns))
    s=execution._validation_session(tmp_path)
    try:
        with pytest.raises(ValueError,match='source pin changed'):native._validation_inputs(task,tmp_path,s)
    finally:s.close()


@pytest.mark.parametrize('mutation',['same_bytes_replaced','different_bytes_restored_mtime','remove',
                                    'leaf_symlink','parent_symlink'])
def test_reused_input_proof_cannot_return_authority_after_leaf_or_ancestor_change(supplied,tmp_path,mutation):
    task,config,assets,_=supplied;p=assets[0]
    s=execution._validation_session(tmp_path)
    try:
        native._validation_inputs(task,tmp_path,s);stat=p.stat()
        if mutation=='same_bytes_replaced':
            new=tmp_path/'replacement';new.write_bytes(p.read_bytes());new.replace(p)
        elif mutation=='different_bytes_restored_mtime':
            p.write_bytes(b'X'*stat.st_size);os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        elif mutation=='remove':p.unlink()
        elif mutation=='leaf_symlink':
            target=p.with_name('same.bin');p.rename(target);p.symlink_to(target)
        else:
            parent=p.parent;target=parent.with_name(parent.name+'-old');parent.rename(target);parent.symlink_to(target,target_is_directory=True)
        try:native._validation_inputs(task,tmp_path,s)
        except (ValueError,OSError):pass
        else:assert s.finish(), 'ending observation must refuse'
    finally:s.close()


@pytest.mark.parametrize('mutation',['new_file','new_empty_directory','source_file_change','manifest_change'])
def test_source_census_and_blob_checks_remain_at_ending(supplied,tmp_path,mutation):
    task,config,assets,up=supplied
    s=execution._validation_session(tmp_path)
    try:
        native._validation_inputs(task,tmp_path,s)
        if mutation=='new_file':(up/'unexpected.py').write_text('unbound')
        elif mutation=='new_empty_directory':(up/'unexpected-directory').mkdir()
        elif mutation=='source_file_change':(up/'LICENSE').write_text('altered')
        else:Path(config['upstream_tree']['manifest']['path']).write_text('{}')
        assert s.finish()
    finally:s.close()


def test_parsed_request_and_runtime_census_mutation_cannot_reuse_proof(supplied,tmp_path):
    task,config,assets,_=supplied
    s=execution._validation_session(tmp_path)
    try:
        native._validation_inputs(task,tmp_path,s)
        task['config']='another.json'
        assert s.finish()
    finally:s.close()


def test_closed_session_is_not_a_cache(supplied,tmp_path):
    task,*_=supplied;s=execution._validation_session(tmp_path)
    native._validation_inputs(task,tmp_path,s);assert s.finish()==[]
    with pytest.raises(ValueError,match='closed'):native._validation_inputs(task,tmp_path,s)


def test_semantics_changed_between_calls_still_fail(supplied,tmp_path):
    task,config,assets,_=supplied;s=execution._validation_session(tmp_path)
    try:
        native._validation_inputs(task,tmp_path,s)
        c=read_json(task['config']);c['runtime']['assets']=c['runtime']['assets'][:-1]
        save(Path(task['config']),c)
        with pytest.raises(ValueError,match='changed'):native._validation_inputs(task,tmp_path,s)
    finally:s.close()


def test_first_source_callback_cannot_adopt_changed_directory(supplied,tmp_path,monkeypatch):
    task,config,assets,up=supplied
    old=native._source
    def changed(*args):
        result=old(*args)
        (up/'late-unbound.py').write_text('must not adopt a renewed census')
        return result
    monkeypatch.setattr(native,'_source',changed)
    s=execution._validation_session(tmp_path)
    try:
        with pytest.raises(ValueError,match='inventory changed'):native._validation_inputs(task,tmp_path,s)
    finally:s.close()


def test_genuine_public_planning_and_verification_use_the_hook(supplied,tmp_path,monkeypatch):
    from test_physics_review import policy
    task,*_=supplied
    p=policy();p.update(allowed_stages=['science'],allowed_changed_paths=[],max_redos=0)
    p['claim_scopes']={native.SCOPE:{'actions':['delivery'],'checks':['integrity','agreement']}}
    spec={'schema_version':2,'mode':'sfitter-native-fit','source':'explicit synthetic validation-session control',
          'assumptions':['No upstream numerical code or scientific engine is imported'],
          'max_seconds':30,'max_attempts':1,'approval_mode':'scripted_yes','task':task,
          'review_policy':{'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}}
    src=tmp_path/'science.json';save(src,spec)
    rd=tmp_path/'ordinary';science.plan(rd,src)
    calls=[];original=native._validation_inputs
    def observe(*a,**k):calls.append(a[2]);return original(*a,**k)
    monkeypatch.setattr(native,'_validation_inputs',observe)
    planned=science.verify_plan(rd)
    assert planned['mode']=='sfitter-native-fit' and len(calls)==2 and calls[0] is calls[1]
    assert calls[0].closed and not calls[0].proofs
    assert not (rd/'inputs/science-approval.json').exists()
    assert not (rd/'outputs').exists() or not list((rd/'outputs').iterdir())
