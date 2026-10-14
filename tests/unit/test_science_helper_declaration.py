"""Prospective helper metadata transport; no historical gates or child processes."""

from method_decision_fixture import admit_method
from copy import deepcopy
from pathlib import Path
import sys
import pytest
from ravel.workflow import science, execution, helper_registration as registration, physics_review
from ravel.workflow.state_io import atomic_json, read_json
from test_science_review_envelope import specification, token


@pytest.fixture
def helper_plan(tmp_path, monkeypatch):
    spec=specification(tmp_path)
    implementation=science.adapter(spec)
    source=tmp_path/'helper.py';source.write_text('# supplied marker; never executed\n')
    contract={'old_runtime':{'interpreter_invocation':sys.executable,'interpreter_binary':registration.binary_pin(Path(sys.executable).resolve())},
              'boundary_source':registration.pin(source)}
    def hook(task,base,out,*,_session=None):
        return registration.declaration(contract,{p:Path(out)/'historical-qualification'/p for p in ('initial','final')})
    monkeypatch.setattr(implementation,'helper_declaration',hook,raising=False)
    path=tmp_path/'spec.json';atomic_json(path,spec)
    rd=tmp_path/'run';proposal=science.plan(rd,path); admit_method(rd)
    return rd,proposal,hook


def test_prospective_science_plan_checkin_and_binding_include_same_helper_declaration(helper_plan):
    rd,p,_=helper_plan;s=p['stages'][0];d=s['helper_declaration']
    assert p['stage_binding']['helper_declaration']==d
    assert read_json(rd/'inputs/checkin1.json')['sections']['i-b']['helper_declaration']==d
    assert set(execution.helper_input_paths(d))<=set(p['stage_binding']['inputs'])
    assert science.verify_plan(rd)==p


@pytest.mark.parametrize('target',['stage','binding','checkin'])
def test_helper_omission_cannot_erase_prospective_science_authority(helper_plan,target):
    rd,p,_=helper_plan
    if target=='checkin':
        doc=read_json(rd/'inputs/checkin1.json');del doc['sections']['i-b']['helper_declaration'];atomic_json(rd/'inputs/checkin1.json',doc)
    else:
        selected=p['stages'][0] if target=='stage' else p['stage_binding'];del selected['helper_declaration'];atomic_json(rd/science.PLAN,p)
    with pytest.raises(ValueError):science.verify_plan(rd)


def test_helper_binary_hash_and_root_escape_refuse_before_process_or_approval(helper_plan):
    rd,p,_=helper_plan;d=deepcopy(p['stages'][0]['helper_declaration'])
    d['helpers'][0]['interpreter_binary']['sha256']='0'*64
    with pytest.raises(ValueError,match='bytes changed'):execution.plan_stage(rd,'x',[sys.executable,'-c','pass'],[],['outputs/x'],[],rd,helper_declaration=d)
    d=deepcopy(p['stages'][0]['helper_declaration']);d['helpers'][0]['request_root']=str(rd/'outside')
    with pytest.raises(ValueError,match='outside'):execution.relocate_helper_fields({'helper_declaration':d},rd/'outputs/attempt-1',rd/'outputs/attempt-2')


def test_exact_correction_root_is_recomputed_and_preserved_by_review_stage_spec(helper_plan):
    rd,p,_=helper_plan
    s=science._stage(rd,p['stages'][0]['inputs'],2,correction_sha256='a'*64)
    d=s['helper_declaration']
    assert all(Path(row['request_root']).is_relative_to(rd/'outputs/attempt-2') for row in d['helpers'])
    assert execution.relocate_helper_fields(p['stages'][0],rd/'outputs/attempt-1',rd/'outputs/attempt-2')=={'helper_declaration':d}
    assert physics_review._stage_spec(rd,s)['helper_declaration']==d


def test_initial_launch_captures_helper_declaration_and_detached_context_cannot_omit_it(helper_plan):
    from ravel.workflow import launch_authorization as launch
    rd,p,_=helper_plan
    science.approve(rd,'Synthetic source-only helper transport approval',scripted=True)
    token(rd)
    stage,binding,budget=science._selected(rd,p)
    ctx={'kind':'science-stage','stage':'science','review_action':'bulk','max_seconds':budget,'events':0,
         'plan_sha256':execution.file_hash(rd/science.PLAN),
         'stage_spec':physics_review._stage_spec(rd,{**stage,'inputs':binding['inputs']})}
    snap=launch._capture(rd,'science',command=stage['command'],context=ctx)
    event={'authorization':snap,'command':stage['command'],'context':ctx,'utc':launch.operational_utc()}
    assert science.validate_authorization_snapshot(snap,event)==[]
    del ctx['stage_spec']['helper_declaration']
    assert science.validate_authorization_snapshot(snap,event)
