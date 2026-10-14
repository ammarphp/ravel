"""Real source protocol/judgment join with explicitly synthetic transport.

No review of an actual scientific result or live provider is performed. The
small original review fixture records a manually supplied stdlib output with
mocked approval verification; its exact limitation stays in each receipt.
"""
import functools
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.workflow import sfitter_conductor as c, sfitter_review_protocol as p
from ravel.workflow import scientific_judgment as judgment, physics_review as review, execution
from test_sfitter_conductor import fixture,proposal,lead
from test_sfitter_adapter import save,pin
from test_sfitter_review_protocol import setup,FakeHost
from test_physics_review import run,opened
from test_scientific_judgment import observed_role_boundary


def adopted(tmp):
    parent=tmp/'construction';parent.mkdir()
    wf,docs,rp=fixture(parent)
    cp,root,_=lead(parent,rp,proposal(wf,'extraction',handoff=docs['extraction']))
    adoption=c.adopt(root,cp,parent,parent/'adopted')
    request,*_=setup(tmp/'domain',all_phases=False)
    request['workflow']=adoption['workflow_draft'];request['stage']='extraction'
    return pin(parent/'adopted/adoption-receipt.json'),save(tmp/'protocol.json',request)


def prepare(root,tmp,ap,rp,role):
    actor={'critic':'critic','verifier':'skeptic','synthesizer':'physicist'}[role]
    return c.prepare_role(ap,rp,tmp,root,tmp/('role-'+role),role=role,actor_id=actor,
        model='explicit-source-control-only',reasoning_effort='high',max_output_tokens=1024,
        max_wall_seconds=20,allow_control=True)


def test_real_protocol_preparation_and_public_default_control_refusal(run,tmp_path):
    opened(run);root=run[0];ap,rp=adopted(tmp_path)
    binding=prepare(root,tmp_path,ap,rp,'critic')
    report=json.loads(Path(binding['report']['path']).read_bytes())
    assert binding['request']==rp
    request=json.loads(Path(rp['path']).read_bytes());workflow=json.loads(Path(request['workflow']['path']).read_bytes())
    assert request['workflow']==json.loads(Path(ap['path']).read_bytes())['workflow_draft']
    assert report['request_sha256']==execution.digest(request) and report['workflow_sha256']==execution.digest(workflow)
    assert len(report['concerns'])==9 and not report['execution_authorized']
    assert judgment.execute_role(binding['judgment'],FakeHost())['complete']
    # Default public consumer still rejects explicitly synthetic transport.
    with pytest.raises(ValueError):c.consume_review(ap,rp,tmp_path,root,binding)
    assert review.status(root)['state']=='awaiting_review'


def test_real_protocol_control_sendback_rework_through_conductor_preserves_originals(run,tmp_path,monkeypatch,observed_role_boundary):
    opened(run);root=run[0];ap,rp=adopted(tmp_path)
    adoption=json.loads(Path(ap['path']).read_bytes());before=Path(adoption['workflow_draft']['path']).read_bytes()
    # Only the development transport selector and the observed-boundary stand-in are supplied.
    # Every context, case, binding, recomputation, actual journal and rework uses real code.
    protocol=SimpleNamespace(context=p.context,prepare_role=p.prepare_role,
        consume=functools.partial(p.consume,allow_control=True),
        rework=functools.partial(p.rework,allow_control=True))
    monkeypatch.setattr(c,'_domain_protocol',lambda:protocol)
    binding=prepare(root,tmp_path,ap,rp,'critic')
    assert judgment.execute_role(binding['judgment'],FakeHost(verdict='send_back'))['complete']
    c.consume_review(ap,rp,tmp_path,root,binding)
    assert review.status(root)['state']=='send_back'
    result=c.rework_review(ap,rp,tmp_path,root,binding,tmp_path/'rework')
    assert result['owner_phase']=='extraction' and result['retained_handoffs']==[]
    assert result['old_votes_carried']==[] and not result['execution_authorized']
    assert Path(adoption['workflow_draft']['path']).read_bytes()==before
    assert review.status(root)['state']=='send_back'
