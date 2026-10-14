"""Prospective actual ordinary-plan consumer controls; AUTHOR HAS NOT RUN THEM.

The actual science.plan/validate/task_inputs/verify_plan/approve APIs are untouched.
Only the existing build fixture's author-review stand-in and inert synthetic
runtime bytes are used. No writer, TeX process, ordinary worker or model runs.
Engineering approval receipts, when exercised, are explicit synthetic machine
records and must never be described as human or physics review.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import manuscript_build as mb, reinterpret_db
from ravel.workflow import manuscript_production as mp, report_integrity as ri
from ravel.workflow import science, task_completion as tc, route_prompt, publication_runtime as pr
from test_manuscript_build import fixture, put
from test_physics_review import policy


def preparation_inputs(root,monkeypatch):
    task,config,package=fixture(root,monkeypatch)
    prompt='Prepare a source-bound synthetic manuscript build plan only; do not run a compiler or infer any physics acceptance.'
    contract=route_prompt.route(prompt);requirements=tc.initial_requirements(prompt)
    requirements['assignments']=[{'id':'publication-build','purpose':'Bound the original synthetic manuscript preparation without execution.',
        'coverage':[{'obligation_id':r['id'],'criteria':deepcopy(r['criteria'])} for r in requirements['obligations']]}]
    contract['task_requirements']=requirements
    goal={'contract':put(root,'parent/inputs/task_contract.json',contract),'assignment_id':'publication-build'}
    assert tc.binding_projection(goal,base_dir=root)['original_request']==prompt
    p=policy();p.update(max_redos=0,allowed_changed_paths=[],allowed_stages=['science'])
    p['claim_scopes']={mb.SCOPE:{'checks':['integrity'],'actions':['delivery']}}
    review={'schema_version':1,'policy':p,'correction_contract':{'task_fields':[],'input_slots':[]}}
    calls=[]
    def forbidden(*a,**k):
        calls.append((a,k));raise AssertionError('Planning/approval software control must never dispatch a worker or native effect')
    monkeypatch.setattr(reinterpret_db,'execute_native',forbidden)
    monkeypatch.setattr(mb,'run',forbidden)
    monkeypatch.setattr(science,'run',forbidden)
    return config,goal,review,calls


def prepare(root,monkeypatch,**selection):
    config,goal,review,calls=preparation_inputs(root,monkeypatch)
    actual_plan=science.plan
    value=mp.prepare_build(config['package'],root/'prepared',base_dir=root,
        runtime=config['runtime'],review_policy=review,goal_binding=goal,max_seconds=30,**selection)
    assert science.plan is actual_plan # No plan/validation/intake/authority double.
    rd=root/'prepared/ordinary'
    return value,rd,calls


@pytest.mark.parametrize('bad',['artifact','delegated_machine','autonomous','',None,True,1])
def test_invalid_public_proposal_modes_refuse_before_creating_preparation(tmp_path,monkeypatch,bad):
    config,goal,review,calls=preparation_inputs(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='physicist or scripted_yes'):
        mp.prepare_build(config['package'],tmp_path/'prepared',base_dir=tmp_path,
            runtime=config['runtime'],review_policy=review,goal_binding=goal,max_seconds=30,approval_mode=bad)
    assert not (tmp_path/'prepared').exists() and calls==[]


def test_pinned_dependency_size_drift_keeps_original_changed_refusal(tmp_path):
    p=tmp_path/'source.bin';p.write_bytes(b'original')
    pin={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
    p.write_bytes(b'changed original size')
    with pytest.raises(ValueError,match='changed: pinned size differs'):
        ri._dependency(pin,tmp_path,ri.CustodyInputs())


def test_explicit_inventory_policy_keeps_selected_limits_over_legacy_defaults(tmp_path,monkeypatch):
    root=tmp_path/'assets';root.mkdir()
    (root/'one.sty').write_bytes(b'12345');(root/'two.sty').write_bytes(b'67890')
    monkeypatch.setattr(pr,'MAX_FILES',1);monkeypatch.setattr(pr,'MAX_BYTES',1)
    selected={'max_files':2,'max_bytes':10,'max_metadata_bytes':4096}
    value=pr.inventory(root,tmp_path/'selected.json',limits=selected)
    assert value['file_count']==2 and value['asset_bytes']==10
    assert set(json.loads((tmp_path/'selected.json').read_text())['files'])=={'one.sty','two.sty'}


@pytest.mark.parametrize('field',['max_files','max_bytes'])
def test_explicit_inventory_limit_still_refuses_full_excess_population(tmp_path,field):
    root=tmp_path/'assets';root.mkdir()
    (root/'one.sty').write_bytes(b'12345');(root/'two.sty').write_bytes(b'67890')
    selected={'max_files':2,'max_bytes':10,'max_metadata_bytes':4096};selected[field]=1
    with pytest.raises(ValueError,match='budget'):
        pr.inventory(root,tmp_path/'refused.json',limits=selected)
    assert not (tmp_path/'refused.json').exists()


@pytest.mark.parametrize('missing',['base','selected'])
def test_tool_environment_missing_state_refuses_without_creation_and_keeps_cause(tmp_path,missing):
    from test_publication_runtime_v2 import request
    req,out,_,_=request(tmp_path);runtime=pr.materialize(req,out)
    work=tmp_path/'work'
    if missing=='base':
        with pytest.raises(ValueError,match='work directory is missing') as raised:
            pr.tool_environment(runtime,'compiler',work,create=False)
        assert not work.exists()
    else:
        work.mkdir();environment=pr.tool_environment(runtime,'compiler',work)
        target=Path(environment['TMPDIR']);target.rmdir()
        with pytest.raises(ValueError,match='work state is missing') as raised:
            pr.tool_environment(runtime,'compiler',work,create=False)
        assert not target.exists()
    assert isinstance(raised.value.__cause__,FileNotFoundError)


def test_pinned_operational_metadata_size_drift_keeps_original_changed_refusal(tmp_path):
    p=tmp_path/'source.json';p.write_bytes(b'{"original":true}\n')
    pin={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
    p.write_bytes(b'{"changed":true,"longer":true}\n')
    with pytest.raises(ValueError,match='changed: pinned size differs'):
        ri._operational_json(pin,tmp_path,ri.CustodyInputs())
