"""Portable real-entry and adverse source controls; no provider/native workers."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import json,hashlib,threading
import pytest
from ravel.workflow import public_source_tools as tools,scientific_task_delivery as delivery,scientific_artifact as typed
from ravel.workflow import agent_host as host,agent_graph as graph,execution

def write(p,v):
 p.write_text(v if type(v) is str else json.dumps(v,allow_nan=False)+'\n');return {'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size}
def program(tmp):
 prompt=write(tmp/'prompt.txt','Compute success-only mean; keep every row and failure.\nINPUT FILE: table.txt\n```text\nx state\n1 ok\n2 failed\n3 ok\n```\n')
 policy=write(tmp/'policy.txt','exact arithmetic and structural constants')
 request={'schema_version':1,'prompt':prompt,'policy':policy,'bindings':[{'id':'rows','expression':{'op':'table','source':'table.txt','pattern':r'(\S+) (\S+)','row_prefix':r'^\d','columns':['x','state'],'region':{'header':'x state'}}}],
 'outputs':{'all_rows':{'op':'ref','id':'rows'},'fraction':{'op':'div','left':{'op':'number','value':{'op':'literal','value':'1','source':'policy','quote':'constants'}},'right':{'op':'number','value':{'op':'literal','value':'3','source':'policy','quote':'constants'}}}}}
 return request

def artifact_request(tmp,facts,interpret=True,fmt='json'):
 tool=write(tmp/'tool.json',facts)
 fields=[{'field':'fraction','type':'number','source':{'kind':'direct','tool_id':'source','pointer':'/facts/fraction'}}] if fmt=='json' else [{'field':'lines','type':{'type':'array','items':'string','max_items':16},'source':{'kind':'direct','tool_id':'source','pointer':'/facts/lines'}}]
 return {'schema_version':1,'format':fmt,'artifact_request':{'schema_version':1,'basis':[write(tmp/'task.txt','Requested whole output, with status not specified.')],
 'tools':{'source':tool},'contract':{'source_scope':'Supplied source calculation only.','tool_fields':fields,'interpretation_fields':['status'] if interpret else [],'unresolved_semantics':[{'field':'status','reason':'Public vocabulary unspecified.'}] if interpret else [],'max_artifact_bytes':4096},'interpretation':{'status':'synthetic'} if interpret else {}}}

def test_complete_failed_row_census_and_exact_rational_delivery(tmp_path):
 p=program(tmp_path);facts=tools.calculate(p,base_dir=tmp_path)
 assert len(facts['facts']['all_rows'])==3 and facts['facts']['all_rows'][1]['state']=='failed'
 assert facts['facts']['fraction']=='1/3'
 out=delivery.deliver(artifact_request(tmp_path,facts),base_dir=tmp_path)
 assert out['artifact']['fraction']==float(Fraction(1,3)) and not out['artifact_text'].startswith('```')
 assert out['complete_task_semantics_claimed'] is False and out['tool_report_truth_verified'] is False

@pytest.mark.parametrize('line',['2 failed EXTRA','surprise row','2'])
def test_unparsed_row_in_complete_region_refuses(tmp_path,line):
 p=program(tmp_path);text=(tmp_path/'prompt.txt').read_text().replace('2 failed',line);p['prompt']=write(tmp_path/'prompt.txt',text)
 with pytest.raises(ValueError):tools.calculate(p,base_dir=tmp_path)

@pytest.mark.parametrize('op',['eval','shell','import','execute'])
def test_unimplemented_operation_never_executes_code(tmp_path,op):
 p=program(tmp_path);p['outputs']['fraction']={'op':op,'value':'open("secret")'}
 with pytest.raises(ValueError):tools.calculate(p,base_dir=tmp_path)

@pytest.mark.parametrize('variant',['duplicate_input','duplicate_binding','missing_quote','missing_binding','zero_division','changed_prompt'])
def test_source_program_ambiguity_and_stale_bytes_refuse(tmp_path,variant):
 p=program(tmp_path)
 if variant=='duplicate_input':p['prompt']=write(tmp_path/'prompt.txt',(tmp_path/'prompt.txt').read_text()+'INPUT FILE: table.txt\n```text\nother\n```\n')
 elif variant=='duplicate_binding':p['bindings'].append(deepcopy(p['bindings'][0]))
 elif variant=='missing_quote':p['outputs']['fraction']['left']['value']['quote']='absent phrase'
 elif variant=='missing_binding':p['outputs']['all_rows']['id']='never_produced'
 elif variant=='zero_division':p['outputs']['fraction']['right']['value']['value']='0'
 else:(tmp_path/'prompt.txt').write_text('changed')
 with pytest.raises(ValueError):tools.calculate(p,base_dir=tmp_path)

def test_unique_selection_does_not_choose_an_arbitrary_tie(tmp_path):
 p=program(tmp_path);p['outputs']['winner']={'op':'extreme','rows':{'op':'ref','id':'rows'},'expression':{'op':'literal','value':1,'source':'policy','quote':'constants'}}
 with pytest.raises(ValueError,match='tied'):tools.calculate(p,base_dir=tmp_path)

@pytest.mark.parametrize('fmt,lines',[('madgraph_commands',['generate p p > x x~','output chosen']),('madgraph_run_card',['20 = nevents','3 = iseed'])])
def test_requested_text_format_served_without_json_proxy(tmp_path,fmt,lines):
 req=artifact_request(tmp_path,{'facts':{'lines':lines}},False,fmt);out=delivery.deliver(req,base_dir=tmp_path)
 assert out['artifact_text']=='\n'.join(lines)+'\n' and out['typed_internal_artifact']=={'lines':lines}
 assert not out['generator_or_native_execution_performed'] and out['requested_format_served']

@pytest.mark.parametrize('line',['x\ny','```text',' ', 'set ebeam1 500'])
def test_card_fences_multiline_and_run_card_command_proxy_refuse(tmp_path,line):
 req=artifact_request(tmp_path,{'facts':{'lines':[line]}},False,'madgraph_run_card')
 with pytest.raises(ValueError):delivery.deliver(req,base_dir=tmp_path)

def test_nullable_requires_observed_json_null_not_missing_source(tmp_path):
 req=artifact_request(tmp_path,{'facts':{'fraction':None}},False);req['artifact_request']['contract']['tool_fields'][0]['type']={'type':'nullable','item':'number'}
 assert delivery.deliver(req,base_dir=tmp_path)['artifact']['fraction'] is None
 req['artifact_request']['tools']['source']=write(tmp_path/'tool.json',{'facts':{}})
 with pytest.raises(ValueError):delivery.deliver(req,base_dir=tmp_path)

@pytest.mark.parametrize('value',[False,'nan','1/0'])
def test_nullable_is_not_a_mistype_escape(tmp_path,value):
 req=artifact_request(tmp_path,{'facts':{'fraction':value}},False);req['artifact_request']['contract']['tool_fields'][0]['type']={'type':'nullable','item':'number'}
 with pytest.raises(ValueError):delivery.deliver(req,base_dir=tmp_path)

def test_raw_reply_only_supplies_declared_interpretation(tmp_path):
 req=artifact_request(tmp_path,{'facts':{'fraction':'1/3'}})
 reply=write(tmp_path/'reply.txt',{'fraction':999,'status':'my_unvalidated_label','scientific_acceptance':True})
 out=delivery.from_response(req,reply,base_dir=tmp_path)
 assert out['artifact']=={'fraction':float(Fraction(1,3)),'status':'my_unvalidated_label'}
 assert out['model_response_pin']==reply and out['model_response_is_authority_for_tool_values'] is False
 assert out['actual_provider_call_provenance_checked'] is False
 assert out['model_fields_not_used_for_tool_values']==['fraction','scientific_acceptance']

@pytest.mark.parametrize('raw',['```json\n{"status":"x"}\n```','{"status":"x","status":"y"}','{"fraction":1}','{"status":1}'])
def test_missing_or_non_raw_interpretation_refuses_without_model_reply_rewrite(tmp_path,raw):
 req=artifact_request(tmp_path,{'facts':{'fraction':'1/3'}});reply=write(tmp_path/'reply.txt',raw)
 with pytest.raises((ValueError,json.JSONDecodeError)):delivery.from_response(req,reply,base_dir=tmp_path)
 assert (tmp_path/'reply.txt').read_text()==raw

def test_no_interpretation_does_not_attribute_model_arithmetic(tmp_path):
 req=artifact_request(tmp_path,{'facts':{'fraction':'1/3'}},False);reply=write(tmp_path/'reply.txt','unusable model text')
 out=delivery.from_response(req,reply,base_dir=tmp_path)
 assert out['artifact']=={'fraction':float(Fraction(1,3))} and out['model_interpretation_fields_consumed']==[]

class Control:
 def __init__(self):self.cancel=threading.Event();self.calls=[]
 def check_cancelled(self):pass
 def cancelled(self):return False
 def call(self,label,kind,request,function,output_tokens=0):self.calls.append((label,kind));return function()
def graph_pin(path,name):return {'id':name,'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def host_node(tmp,spec,action,role='improver',reply=None):
 request=tmp/'request.json';write(request,spec)
 module=tools if action=='public-source-facts' else delivery
 pins=[graph_pin(request,'request')]+[graph_pin(tmp/p['path'],'p'+str(i)) for i,p in enumerate(module.input_pins(spec,base_dir=tmp))]
 parameters={'request_input':'request'}
 if reply is not None:pins.append(graph_pin(reply,'reply'));parameters['response_input']='reply'
 node={'id':'task','kind':'tool','role':role,'depends_on':[],'inputs':pins,'packet':None,'action':action,'parameters':parameters,'max_attempts':1}
 record={'schema_version':1,'graph_id':'task','graph_revision':'a'*64,'node_id':'task','generation':1,'node_sha256':execution.digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(pins),'packet':None,'dependencies':[]}
 return node,record

@pytest.mark.parametrize('action',['public-source-facts','scientific-task-delivery','scientific-task-response'])
def test_real_host_entry_once_and_complete_input_obligation(tmp_path,action):
 spec=program(tmp_path) if action=='public-source-facts' else artifact_request(tmp_path,{'facts':{'fraction':'1/3'}})
 reply=tmp_path/'reply.txt';write(reply,{'status':'source-only interpretation'})
 node,record=host_node(tmp_path,spec,action,reply=reply if action=='scientific-task-response' else None);control=Control()
 out=host.AgentHost().execute(node,record,control)
 assert len(control.calls)==1 and out['execution_authorized'] is False
 assert out['value']['facts']['fraction']=='1/3' if action=='public-source-facts' else out['value']['artifact']['fraction']==float(Fraction(1,3))
 node['inputs']=node['inputs'][:-1];record['input_artifacts']=deepcopy(node['inputs']);record['node_sha256']=execution.digest(node);control=Control()
 with pytest.raises(host.HostFailure):host.AgentHost().execute(node,record,control)
 assert not control.calls

@pytest.mark.parametrize('role',['critic','verifier','physics_critic','skeptical_verifier'])
def test_blind_roles_do_not_construct_task_outputs(tmp_path,role):
 node,record=host_node(tmp_path,program(tmp_path),'public-source-facts',role);control=Control()
 with pytest.raises(host.HostFailure):host.AgentHost().execute(node,record,control)
 assert not control.calls

def test_ordinary_graph_source_calculation_then_delivery_and_reuse(tmp_path):
 calc=tmp_path/'calculation';calc.mkdir();node,_=host_node(calc,program(calc),'public-source-facts')
 plan={'schema_version':1,'graph_id':'source-facts','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':0,'max_wall_seconds':30,'max_reworks':0},'nodes':[node]}
 root=tmp_path/'source-graph';graph.create(root,plan);agent=host.AgentHost();first=graph.execute(root,agent)
 assert first['complete'];result=json.loads((root/first['nodes']['task']['result']['path']).read_text())
 delivered=tmp_path/'delivery';delivered.mkdir();spec=artifact_request(delivered,result['result']['value'])
 node,_=host_node(delivered,spec,'scientific-task-delivery');plan['graph_id']='whole-delivery';plan['nodes']=[node]
 root2=tmp_path/'delivery-graph';graph.create(root2,plan);second=graph.execute(root2,agent)
 assert second['complete'];raw=(root2/second['nodes']['task']['result']['path']).read_bytes()
 third=graph.execute(root2,agent);assert third['usage']==second['usage']=={'calls':1,'reserved_output_tokens':0}
 assert (root2/third['nodes']['task']['result']['path']).read_bytes()==raw
 (delivered/'tool.json').write_text('changed')
 with pytest.raises(ValueError):graph.execute(root2,agent)
