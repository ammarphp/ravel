"""The composed ordinary Host consumes the same bytes it authenticates."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,threading
import pytest
from ravel.workflow import agent_host as host,execution,public_source_tools

class Control:
    def __init__(self):self.cancel=threading.Event();self.calls=[]
    def check_cancelled(self):assert not self.cancel.is_set()
    def cancelled(self):return False
    def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()
def pin(p,identity):return {'id':identity,'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def source(p):return {'path':p.name,'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def prepare(tmp_path):
    p=tmp_path/'prompt.txt';p.write_text('Total: 10\n');policy=tmp_path/'policy.txt';policy.write_text('Literal extract only.\n')
    req={'schema_version':1,'prompt':source(p),'policy':source(policy),'bindings':[],
         'outputs':{'total':{'op':'extract','source':'instruction','pattern':r'^Total: (\d+)$','group':1}}}
    path=tmp_path/'request.json';path.write_text(json.dumps(req))
    pins=[pin(path,'request')]+[pin(tmp_path/x['path'],'input'+str(i)) for i,x in enumerate(public_source_tools.input_pins(req,base_dir=tmp_path))]
    n={'id':'task','kind':'tool','role':'improver','depends_on':[],'inputs':pins,'packet':None,
       'action':'public-source-facts','parameters':{'request_input':'request'},'max_attempts':1}
    r={'schema_version':1,'graph_id':'source','graph_revision':'a'*64,'node_id':'task','generation':1,
       'node_sha256':execution.digest(n),'request_id':'b'*64,'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
    return path,req,n,r
def test_request_program_ABA_does_not_supply_unverified_parsed_instruction(tmp_path,monkeypatch):
    path,req,n,r=prepare(tmp_path);original=path.read_bytes();calls=[];old=host.read_json
    def swapped(p):
        if p==path:
            calls.append('unverified request read');changed=deepcopy(req);changed['outputs']['total']={'op':'literal','value':'99'}
            path.write_text(json.dumps(changed))
            try:return old(p)
            finally:path.write_bytes(original)
        return old(p)
    monkeypatch.setattr(host,'read_json',swapped);c=Control();result=host.AgentHost().execute(n,r,c)
    assert result['value']['facts']['total']=='10' and calls==[] and len(c.calls)==1
    assert path.read_bytes()==original
def test_substituted_request_descriptor_refuses_before_tool_call(tmp_path,monkeypatch):
    path,req,n,r=prepare(tmp_path);other=tmp_path/'other.json';other.write_text(json.dumps(req));old=Path.open
    def swapped(self,*args,**kwargs):return old(other,*args,**kwargs) if self==path and args==('rb',) else old(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',swapped);c=Control()
    with pytest.raises(host.HostFailure):host.AgentHost().execute(n,r,c)
    assert c.calls==[]
