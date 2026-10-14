"""Real Host request/parser, fully inert HTTP implementation; no sockets."""
from copy import deepcopy
import json
import pytest
from ravel.workflow import agent_host as h,scientific_judgment as j
from review_responses_fixture import Control,node,request,response,SCHEMA

@pytest.mark.parametrize('variant',['conditional','legacy','missing-wrapper','extra-wrapper','invalid-nonaccept'])
def test_actual_responses_branch_preserves_flat_record_and_strict_conditions(monkeypatch,variant):
    conditional=variant!='legacy'
    s=j.output_schema() if conditional else deepcopy(SCHEMA)
    value={'answer':'synthetic'}
    if conditional:
        value={k:None for k in s['properties']};value.update(schema_version=1,kind='scientific_review',subject_sha256='a'*64,verdict='stop',summary='Synthetic public stop; no actual scientific vote',findings=[],closes=[],claim_scope=None,audit=None)
    if variant=='invalid-nonaccept':value['claim_scope']='scope'
    wire={'public_record':value} if conditional else value
    if variant=='missing-wrapper':wire=value
    if variant=='extra-wrapper':wire['extra']='forbidden'
    raw=json.dumps(response(wire)).encode();seen=[]
    class R:
        status=200
        def read(self,limit):return raw[:limit]
        def close(self):pass
    class C:
        sock=None
        def __init__(self,*args,**kw):pass
        def connect(self):pass
        def request(self,method,path,body,headers):seen.append(json.loads(body))
        def getresponse(self):return R()
        def close(self):pass
    monkeypatch.setattr(h.http.client,'HTTPConnection',C)
    n=node(parameters={'instructions':'Explicit fabricated public response; no provider', 'model':'synthetic','reasoning_effort':'low','max_output_tokens':2048,'output_schema':s})
    host=h.AgentHost(endpoint='http://127.0.0.1/v1/responses');ctrl=Control()
    if variant in {'missing-wrapper','extra-wrapper','invalid-nonaccept'}:
        with pytest.raises(h.HostFailure):host.execute(n,request(n),ctrl)
    else:
        result=host.execute(n,request(n),ctrl)
        assert result['value']==value and len(ctrl.calls)==1
    body=seen[0];root=body['text']['format']['schema']
    assert 'anyOf' not in root and root['type']=='object'
    if conditional:
        assert root['required']==['public_record'] and root['properties']['public_record']==s
        assert 'wire format wraps' in body['instructions']
    else:assert root==s
