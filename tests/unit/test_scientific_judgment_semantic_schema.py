"""Public schema to strict finite-case consumer controls; synthetic only."""
from copy import deepcopy

from pathlib import Path

import ast,hashlib,json

import pytest

from ravel.workflow import scientific_judgment as j, decision_case, agent_host, agent_graph as graph, execution, physics_review as review

from ravel.workflow.state_io import read_json, atomic_json

@pytest.fixture(autouse=True)
def inert_platform_identity(monkeypatch):
    monkeypatch.setattr(execution.platform,'platform',lambda:'synthetic-fixed-platform-no-query')

def value(case,decision='supported',disposition='accepted',verdict='accept'):
    return {'schema_version':1,'kind':'scientific_review','subject_sha256':'a'*64,'verdict':verdict,'summary':'Synthetic format fixture only; no actual scientific vote.',
        'findings':[],'closes':[],'claim_scope':'diagnostic','audit':{'case_sha256':execution.digest(case),
        'nodes':[{'id':n['id'],'decision':decision,'reason':'Synthetic supplied anchor judgment','assumptions':[{'disposition':disposition,'reason':'Synthetic applicability declaration'} for a in n['assumptions']]} for n in case['nodes']],
        'edges':[{'parent':e['parent'],'child':e['child'],'decision':decision,'reason':'Synthetic edge judgment'} for e in case['edges']]},'proposal':None,'proposal_verdict':None}

@pytest.fixture
def finite_case(tmp_path):
    anchor=tmp_path/'anchor.json';atomic_json(anchor,{'synthetic':1})
    pin={'path':str(anchor),'sha256':execution.file_hash(anchor)}
    node=lambda id:{'id':id,'author_id':'synthetic-proposer','assertion':'Synthetic fixture '+id,'rationale':'Schema test only','material':True,'assumptions':[{'statement':'Synthetic fixture convention','disposition':'unresolved','reason':'pending'}],
        'unknowns':[],'anchors':[{'kind':'invariant','artifact':pin,'format':'json','location':'/synthetic','value':1}],
        'review':{'reviewer_id':'pending','decision':'unresolved','reason':'Pending independent control'}}
    return {'schema_version':1,'action':'Synthetic format check','root':'root','triggers':[{'kind':'unsupported_step','reason':'Synthetic source control'}],'budget':{'max_nodes':2,'max_depth':1},'nodes':[node('root'),node('support')],
        'edges':[{'parent':'root','child':'support','author_id':'synthetic-proposer','rationale':'Synthetic edge','review':{'reviewer_id':'pending','decision':'unresolved','reason':'pending'},'request':{'kind':'evidence','description':'Synthetic evidence request'}}]}

@pytest.mark.parametrize('decision,expected',[('supported','supported'),('unresolved','unresolved'),('contradicted','contradicted')])
def test_every_declared_decision_survives_schema_to_real_consumer(finite_case,tmp_path,decision,expected):
    v=value(finite_case,decision=decision)
    admitted=agent_host.validate_public_result(v,j.output_schema())
    result=j._audit(finite_case,admitted['audit'],'independent-control',tmp_path)
    assert result['status']==expected

@pytest.mark.parametrize('disposition,expected',[('accepted','supported'),('unresolved','unresolved'),('rejected','contradicted')])
def test_every_declared_assumption_survives_schema_consumer(finite_case,tmp_path,disposition,expected):
    v=agent_host.validate_public_result(value(finite_case,disposition=disposition),j.output_schema())
    assert j._audit(finite_case,v['audit'],'independent-control',tmp_path)['status']==expected

@pytest.mark.parametrize('field,bad',[('node','accept'),('node','send_back'),('edge','stop'),('edge','accepted'),('assumption','supported'),('assumption','accept')])
def test_foreign_semantic_labels_refuse_before_delivery(finite_case,field,bad):
    v=value(finite_case)
    # Establish a valid control before changing only the semantic label.
    agent_host.validate_public_result(v,j.output_schema())
    if field=='node':v['audit']['nodes'][0]['decision']=bad
    elif field=='edge':v['audit']['edges'][0]['decision']=bad
    else:v['audit']['nodes'][0]['assumptions'][0]['disposition']=bad
    with pytest.raises(agent_host.HostFailure,match='conditional output alternatives'):agent_host.validate_public_result(v,j.output_schema())

def test_overall_accept_remains_distinct_from_audit_labels(finite_case):
    assert agent_host.validate_public_result(value(finite_case),j.output_schema())['verdict']=='accept'
    assert j.output_schema()['properties']['audit']['properties']['nodes']['items']['properties']['decision']['enum']==list(decision_case.STATUSES)
