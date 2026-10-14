"""Portable public adapter/planning controls with supplied synthetic origins.

Planning does not approve or execute a scientific job. Worker controls substitute
only authority/spec retrieval; the actual adapter and renderer deliver files.
"""
import copy,hashlib,json,re
from pathlib import Path
import pytest
from ravel.physics import group_composition as c
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json,read_json
from test_group_composition import sample,measurement_contract,pin,save


def specification(task,version=2):
    spec={'schema_version':version,'mode':'group-composition',
          'source':'Explicit synthetic coordinate/group control, no native qualification',
          'assumptions':['Supplied independent-single-subevent Poissonized group covariance only'],
          'max_seconds':30,'approval_mode':'scripted_yes','task':task}
    if version==2:
        spec.update(max_attempts=1,review_policy={'schema_version':1,'policy':{'schema_version':1,
            'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic',
                      'skeptical_verifier':'skeptic','physics_decider':'decider'},
            'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
            'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
            'claim_scopes':{'supplied_same_event_delta':{'checks':['integrity','scientific'],'actions':['delivery','reuse']}}},
            'correction_contract':{'task_fields':[],'input_slots':[]}})
    return spec


@pytest.mark.parametrize('change',[{'schema_version':True},{'schema_version':2},{'operation':'fit'},
    {'extra':'unbound'},{'input':''},{'contract_sha256':'A'*64},{'contract_sha256':'a'*63}])
def test_closed_task_refuses(sample,tmp_path,change):
    task,_,_=measurement_contract(sample,tmp_path)
    with pytest.raises(ValueError):c.validate({**task,**change})


def test_planning_complete_nested_inputs_and_v2_requirement(sample,tmp_path,monkeypatch):
    task,_,_=measurement_contract(sample,tmp_path)
    assert science.adapter(specification(task)) is c and science._new_capability(specification(task))
    monkeypatch.setattr(c.n,'normalize',lambda *_a,**_k:pytest.fail('planning evaluated normalization'))
    files=c.inputs(task,tmp_path);assert len(files)==len(set(files))==19
    specpath=tmp_path/'v1.json';atomic_json(specpath,specification(task,1))
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'refused-v1',specpath)
    assert not (tmp_path/'refused-v1').exists()
    specpath=tmp_path/'v2.json';atomic_json(specpath,specification(task))
    proposal=science.plan(tmp_path/'prepared-only',specpath)
    assert set(map(str,files))<=set(proposal['stages'][0]['inputs'])
    assert not (tmp_path/'prepared-only'/science.APPROVAL).exists()
    assert not (tmp_path/'prepared-only'/'outputs/attempt-1').exists()
    source=Path(sample[1][1]['sources'][0]['path']);source.write_bytes(source.read_bytes()+b'changed')
    with pytest.raises(ValueError):science.verify_plan(tmp_path/'prepared-only')


@pytest.mark.parametrize('identity',['routine','trace','RAW','original','acquired'])
def test_each_original_origin_refuses_mutation_before_planning(sample,tmp_path,identity):
    task,_,_=measurement_contract(sample,tmp_path)
    source=Path(next(p['path'] for p in sample[1][1]['sources'] if p['id']==identity))
    source.write_bytes(source.read_bytes()+b' ')
    with pytest.raises(ValueError):c.inputs(task,tmp_path)


@pytest.mark.parametrize('raw',['{"schema_version":1,"schema_version":1}', '{"value":NaN}', '[]'])
def test_outer_resealed_json_refuses(sample,tmp_path,raw):
    task,_,_=measurement_contract(sample,tmp_path);path=Path(task['input']);path.write_text(raw)
    task['contract_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):c.inputs(task,tmp_path)


def test_outer_relative_path_and_symlink_ancestry(sample,tmp_path):
    task,_,_=measurement_contract(sample,tmp_path);task['input']=Path(task['input']).name
    assert len(c.inputs(task,tmp_path))==19
    alias=tmp_path/'alias';alias.symlink_to(tmp_path,target_is_directory=True)
    refusal=f"input path traverses a symlink: {alias/task['input']}"
    with pytest.raises(ValueError,match=re.escape(refusal)):c.inputs({**task,'input':str(alias/task['input'])},tmp_path)


def test_actual_real_adapter_renderer_worker_lifecycle(sample,tmp_path,monkeypatch):
    from ravel.physics import science_worker
    task,_,_=measurement_contract(sample,tmp_path);spec=specification(task)
    rd=tmp_path/'worker-run';rd.mkdir()
    proposal={'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':[]}}
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal)
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';nested=out/'group-composition'
    actual=read_json(out/'result.json')
    assert actual==read_json(nested/'group-composition.json')
    assert actual['measurement_components']==read_json(nested/'measurement-components.json')
    assert len(read_json(nested/'measurement-components.json')['joint_prediction_covariance'])==48
    assert read_json(nested/'normalized-joint.json')['uncertainty']['kind']=='supplied_covariance'
    assert read_json(out/'figures.json')['status']=='not_applicable'
    assert read_json(out/'verification.json')['physics_validated'] is False
    assert read_json(out/'checkin2.json')['sections']['waypoint']['scope']=='group-composition'
    assert not actual['native_acquisition_qualified'] and actual['experimental_independence'] is None
    before={p.relative_to(out).as_posix():p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
    assert before=={p.relative_to(out).as_posix():p.read_bytes() for p in out.rglob('*') if p.is_file()}
