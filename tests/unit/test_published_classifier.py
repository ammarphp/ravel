"""Synthetic source arithmetic/accounting; no actual inference provider loaded."""
import copy, hashlib, json
from pathlib import Path
from fractions import Fraction
import pytest
from ravel.physics import published_classifier as m, classifier_inputs as ci, domain_adapters as domains


def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def write(p,v):p.write_text(json.dumps(v,allow_nan=False));return pin(p)
def var(n):
 out=b''
 while n>127:out+=bytes([(n&127)|128]);n>>=7
 return out+bytes([n])
def f(n,v):return var(n*8)+var(v) if type(v) is int else var(n*8+2)+var(len(v))+v
def tensor(name,width):return f(1,name.encode())+f(2,f(1,f(1,1)+f(2,f(1,f(1,1))+f(1,f(1,width)))))

def case(tmp_path):
 source=tmp_path/'source.cc';source.write_text('float input[]={x,y}; auto out=nn(input); fill(out[0]); // source declaration\n')
 model=tmp_path/'model.onnx';model.write_bytes(f(1,9)+f(7,f(11,tensor('input',2))+f(12,tensor('output',3))))
 c={'kind':'source-classifier-feature-contract/v2','routine':'FABRICATED_SOURCE',
 'source':pin(source),'model':pin(model),'model_static':ci.inspect(model.read_bytes()),
 'source_excerpts':[{'file':pin(source),'start':1,'end':1,'text':source.read_text().rstrip()}],
 'features':[{'id':x,'source_expression':x,'operation':'identity','cast':'float32','arithmetic':'binary32_each'} for x in ('x','y')],
 'feature_preprocessing_state':'declared_source_scalar_arithmetic','routing':{'kind':'supplied_fixed_model','event_route_qualified':False},
 'runtime_obligations':['Actual reconstruction/runtime/source parity unqualified'],
 'source_output_operation':{'kind':'scalar_index','index':0,'complete_model_output_width':3,'unused_output_indices':[1,2],'downstream_categorical_lowering':'literal H/L/Any boundaries','source_fill_weight':'complete original event weights'},
 'event_reconstruction_qualified':False,'native_runtime_qualified':False,'source_arithmetic_not_native_bitwise_equivalence':True}
 md={'id':'m','contract':c,'feature_units':{'x':'1','y':'GeV'},'score_unit':'1','score_range':[0,2],
 'eligibility':{'source_expression':'all recorded admitted events except explicit veto','source_excerpt':0},
 'controls':[{'id':'ref','values':{'x':.25,'y':0},'expected_outputs':[.25,0,.25],'atol':1e-8,'rtol':1e-8}]}
 bins=[{'id':name,'model':'m','conditions':[{'op':op,'value':v}],'source_expression':name+' exact predicate','source_excerpt':0} for name,op,v in [('H','>',.5),('L','<=',.5),('Any','>=',0)]]
 q={'schema_version':1,'axes':[{'name':'source_category','unit':'1'}],'bins':[{'id':b['id'],'low':[i],'high':[i+1]} for i,b in enumerate(bins)],'weight_names':['nominal','variation'],'input_weight_unit':'event_weight','representation':'integrated','normalization':{'kind':'absolute','scale':1,'unit':'event_weight'}}
 rows=[]
 for i,(x,w,alt,g) in enumerate([(.8,2,3,'g1'),(.2,-1,4,'g1'),(.5,0,0,'g2'),(None,3,-2,'g3'),(.9,-2,1,'g4')]):
  rows.append({'event_id':'e'+str(i),'event_number':i,'source_selected':{'m':x is not None},'group_id':g,'shard_id':'s','weights':{'nominal':w,'variation':alt},'eligible':{'m':x is not None},'features':{'m':{'x':x,'y':0} if x is not None else None}})
 ev={'kind':'published-classifier-events/v1','event_ids':[r['event_id'] for r in rows],'weight_names':q['weight_names'],'feature_units':{'m':copy.deepcopy(md['feature_units'])},'events':rows}
 ep=tmp_path/'events.json';write(ep,ev)
 doc={'kind':'published-classifier-composition/v1','route':'supplied-onnx','models':[md],'events':pin(ep),'score_bins':bins,'quantities':q,'source_semantics':'Explicit fabricated scalar/source/accounting control; not paper validation'}
 p=tmp_path/'composition.json';write(p,doc);task={'schema_version':1,'input':str(p),'input_sha256':pin(p)['sha256']}
 return task,doc,ev,p,ep


class Session:
 def __init__(self,width=3,mutate=None):self.width=width;self.calls=[];self.mutate=mutate
 def run(self,names,feed):
  import numpy as np
  row=feed['input'][0];self.calls.append(row.tolist())
  if self.mutate:self.mutate()
  return [np.asarray([[row[0],row[1],row[0]+row[1]][:self.width]],dtype='float32')]


def engine(monkeypatch,session=None,shape=None):
 import numpy as np
 session=session or Session()
 def load(raw,**kwargs):
  assert raw and kwargs=={'input_name':'input','output_name':'output','dtype':'float32','feature_count':2}
  return np,session,shape or [1,2],'synthetic-session'
 monkeypatch.setattr(domains,'onnx_session',load)
 return session


def test_full_public_adapter_grouped_signed_joint_covariance(tmp_path,monkeypatch):
 t,d,ev,p,ep=case(tmp_path);s=engine(monkeypatch)
 r=m.run(t,tmp_path,tmp_path/'out')
 assert r['status']=='passed' and r['population']=={'events':5,'groups':4,'weight_names':['nominal','variation'],'models':1,'bins':3,'unselected_events':1}
 assert r['quantities']['values']=={'nominal':[0,-1,-1],'variation':[4,4,8]}
 cv=r['quantities']['covariance'];assert cv[0][0]==8 and cv[0][1]==-2 and cv[0][2]==6 and cv[0][5]==12
 assert r['quantities']['state']['counts']['records']==5 and r['quantities']['state']['counts']['empty_records']==1
 assert r['events'][3]['inference']['m'] is None and r['quantity_records'][3]['fills']==[]
 assert all(len(row['inference']['m']['complete_outputs'])==3 for row in r['events'] if row['eligible']['m'])
 assert len(s.calls)==5 and r['runtime'][0]['calls']==5
 assert json.loads((tmp_path/'out/published-classifier.json').read_text())==r
 assert not r['physics_validated'] and not r['training_executed']
 with pytest.raises(ValueError,match='fresh'):m.run(t,tmp_path,tmp_path/'out')


def test_normalized_all_event_denominator_includes_veto_zero_negative(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch);d['quantities']['normalization']={'kind':'normalized','scope':'all_events'};t['input_sha256']=write(p,d)['sha256']
 r=m.run(t,tmp_path,tmp_path/'out');q=r['quantities']
 assert q['denominators']['nominal']['sumw']==2 and q['denominators']['variation']['sumw']==6
 assert q['values']['nominal']==[0,-.5,-.5]
 # Independent Fraction Jacobian witness, including unselected group's denominator.
 hs=[(2,1), (0,0), (0,3),(-2,-2)]
 assert q['covariance'][0][0]==float(sum((Fraction(h,2))**2 for h,den in hs))


@pytest.mark.parametrize('fault',['missing_event','duplicate_event','weight_missing','unit_drift','unknown_model','feature_missing','imputed_veto','bool_weight','group_split','wrong_bins','malformed_condition','range','extra_task','missing_control_output','source_drift','model_drift','source_excerpt','nonfinite','duplicate_json','unqualified_claim'])
def test_complete_population_and_source_refusals(tmp_path,monkeypatch,fault):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch)
 if fault=='missing_event':e['events'].pop()
 if fault=='duplicate_event':e['event_ids'][1]=e['event_ids'][0]
 if fault=='weight_missing':e['events'][0]['weights'].pop('variation')
 if fault=='unit_drift':e['feature_units']['m']['x']='MeV'
 if fault=='unknown_model':d['score_bins'][0]['model']='foreign'
 if fault=='feature_missing':e['events'][0]['features']['m'].pop('x')
 if fault=='imputed_veto':e['events'][3]['features']['m']={'x':0,'y':0}
 if fault=='bool_weight':e['events'][0]['weights']['nominal']=True
 if fault=='group_split':e['events'][1]['shard_id']='other'
 if fault=='wrong_bins':d['quantities']['bins'][0]['high']=[3]
 if fault=='malformed_condition':d['score_bins'][0]['conditions'][0]['op']='=='
 if fault=='range':d['models'][0]['score_range']=[0,.5]
 if fault=='extra_task':t['hidden_inference']=True
 if fault=='missing_control_output':d['models'][0]['controls'][0]['expected_outputs'].pop()
 if fault=='source_drift':(tmp_path/'source.cc').write_text('changed')
 if fault=='model_drift':(tmp_path/'model.onnx').write_bytes(b'changed')
 if fault=='source_excerpt':d['models'][0]['contract']['source_excerpts'][0]['text']='foreign'
 if fault=='unqualified_claim':d['models'][0]['contract']['event_reconstruction_qualified']=True
 d['events']=write(ep,e);t['input_sha256']=write(p,d)['sha256']
 if fault=='duplicate_json':p.write_text('{"kind":0,"kind":1}');t['input_sha256']=pin(p)['sha256']
 if fault=='nonfinite':p.write_text('{"kind":NaN}');t['input_sha256']=pin(p)['sha256']
 with pytest.raises(ValueError):m.run(t,tmp_path,tmp_path/'out')


def test_failed_reference_retains_complete_delivery_without_acceptance(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch);d['models'][0]['controls'][0]['expected_outputs'][0]=1;t['input_sha256']=write(p,d)['sha256']
 r=m.run(t,tmp_path,tmp_path/'out');assert r['status']=='failed' and len(r['events'])==5
 assert not r['reference_checks'][0]['passed']


@pytest.mark.parametrize('operation',['difference','strict_score_threshold'])
def test_source_output_interpretations_and_unchanged_full_outputs(tmp_path,monkeypatch,operation):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch)
 d['models'][0]['contract']['source_output_operation']=({'kind':'difference','positive_index':0,'negative_index':1,'complete_model_output_width':3,'unused_output_indices':[2]} if operation=='difference' else {'kind':'strict_score_threshold','index':0,'complete_model_output_width':3,'nn_enabled_required':True,'threshold':.5})
 t['input_sha256']=write(p,d)['sha256'];r=m.run(t,tmp_path,tmp_path/'out')
 assert r['quantities']['values']['nominal']==[0,-1,-1]
 if operation=='strict_score_threshold':assert r['events'][2]['inference']['m']['threshold_selected'] is False


def test_source_arithmetic_before_cast_vs_each_float_operand(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);s=engine(monkeypatch)
 f0=d['models'][0]['contract']['features'][0];f0.update(operation='normalize',offset=16777216,scale=1)
 for row in e['events']:
  if row['eligible']['m']:row['features']['m']['x']=16777217
 d['models'][0]['controls'][0].update(values={'x':16777217,'y':0},expected_outputs=[0,0,0]);d['events']=write(ep,e);t['input_sha256']=write(p,d)['sha256']
 r=m.run(t,tmp_path,tmp_path/'out');assert all(row[0]==0 for row in s.calls)


@pytest.mark.parametrize('fault',['source_change','source_ABA','events_change','output_shape','static_batch','nonfinite_output'])
def test_post_inference_custody_and_executor_refusal(tmp_path,monkeypatch,fault):
 t,d,e,p,ep=case(tmp_path);source=tmp_path/'source.cc';old=source.read_bytes()
 def mutate():
  if fault=='source_change':source.write_bytes(b'changed')
  if fault=='source_ABA':source.write_bytes(b'changed');source.write_bytes(old)
  if fault=='events_change':ep.write_bytes(b'changed')
 s=Session(width=2 if fault=='output_shape' else 3,mutate=mutate)
 if fault=='nonfinite_output':
  import numpy as np
  s.run=lambda *_:[np.asarray([[float('nan'),0,0]])]
 engine(monkeypatch,s,shape=[2,2] if fault=='static_batch' else None)
 with pytest.raises(ValueError):m.run(t,tmp_path,tmp_path/'out')
 assert not (tmp_path/'out/published-classifier.json').exists()


def test_public_worker_result_checkin2_report_and_mode_reachability(tmp_path,monkeypatch):
 from ravel.physics import science_worker
 from ravel.plotting import science_figures
 from ravel.workflow import science
 from ravel.workflow.state_io import atomic_json,read_json
 from test_science_capability_integration import specification
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch);spec=specification('published-classifier',t)
 assert science.adapter(spec) is m and science._new_capability(spec) and len(science.task_inputs(spec,tmp_path))==4
 rd=tmp_path/'ordinary';(rd/'inputs').mkdir(parents=True)
 atomic_json(rd/'inputs/science.json',spec);atomic_json(rd/'inputs/science-plan.json',{'schema_version':2,'execution_task':t,'mutable_inputs':[]});atomic_json(rd/'inputs/science-execution-task.json',{'schema_version':1,'task':t})
 monkeypatch.setattr(science_worker,'verify_worker',lambda _:{'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
 assert science_worker.main([str(rd),'--attempt','1'])==0
 out=rd/'outputs/attempt-1';r=read_json(out/'result.json');assert r==read_json(out/'published-classifier/published-classifier.json')
 assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
 assert read_json(out/'verification.json')['passed'] is True and (out/'published-classifier-report.json').exists()
 assert 'published-classifier' in science.MODES
 with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])


def native_case(tmp_path,monkeypatch):
 from ravel.physics import existing_events as native
 t,d,e,p,ep=case(tmp_path)
 task={'backend':'rivet-built','routine':'FABRICATED_SOURCE','build_receipt':'r','build_plan':'p','events':'events.hepmc','metadata':'m','runtime':{'python':'p','version':'4.1.4'},'observables':[{'path':'/FABRICATED/d01','axes':[{'name':'x','unit':'1'}],'representation':'integrated','normalization':'absolute','unit':'pb'}],'options':{},'seed':19,'native_weight_cap':0}
 d={'kind':'published-classifier-composition/v1','route':'native-rivet','native_task':task,'source_bindings':[{'role':role,'provider':'TMVA','pin':pin(tmp_path/name),'source_expression':'original native inference declaration'} for role,name in [('source','source.cc'),('model','model.onnx')]],'native_output_paths':['/FABRICATED/d01'],'native_per_event_scores':'not_published_by_this_handoff','source_semantics':'Original whole source and all assets via ordinary reviewed build'}
 t['input_sha256']=write(p,d)['sha256'];monkeypatch.setattr(native,'inputs',lambda *_:[tmp_path/'source.cc',tmp_path/'model.onnx'])
 return t,d,p,native


def test_native_delegates_task_clock_and_outputs_unchanged_no_fabricated_scores(tmp_path,monkeypatch):
 t,d,p,n=native_case(tmp_path,monkeypatch)
 original={'status':'passed','physics_validated':False,'census':{'weight_names':['zero','negative','nominal'],'events':5},'quantities':'observables.json','limitations':['no full covariance in marginal YODA']}
 seen=[]
 def run(task,base,out,*,worker_started):
  seen.append((task,worker_started));out.mkdir();(out/'observables.json').write_text('{"actual":"unchanged native output"}');return copy.deepcopy(original)
 monkeypatch.setattr(n,'run_in_worker',run)
 r=m.run_in_worker(t,tmp_path,tmp_path/'out',worker_started=123)
 assert r['native']==original and seen==[(d['native_task'],123)] and r['per_event_scores'] is None
 assert (tmp_path/'out/native/observables.json').read_text()=='{"actual":"unchanged native output"}'
 with pytest.raises(ValueError,match='clock'):m.run(t,tmp_path,tmp_path/'other')


@pytest.mark.parametrize('fault',['weight_cap','foreign_source','output_omission','score_fabrication','model_role'])
def test_native_closure_and_scope_refusals(tmp_path,monkeypatch,fault):
 t,d,p,n=native_case(tmp_path,monkeypatch)
 if fault=='weight_cap':d['native_task']['native_weight_cap']=1
 if fault=='foreign_source':monkeypatch.setattr(n,'inputs',lambda *_:[])
 if fault=='output_omission':d['native_output_paths']=[]
 if fault=='score_fabrication':d['native_per_event_scores']='available'
 if fault=='model_role':d['source_bindings'][1]['role']='configuration'
 t['input_sha256']=write(p,d)['sha256']
 with pytest.raises(ValueError):m.inputs(t,tmp_path)


def test_two_models_preserve_cross_model_bin_covariance(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch)
 m2=copy.deepcopy(d['models'][0]);m2['id']='second';d['models'].append(m2)
 for row in e['events']:
  for key in ('source_selected','eligible','features'):row[key]['second']=copy.deepcopy(row[key]['m'])
 e['feature_units']['second']=copy.deepcopy(e['feature_units']['m'])
 d['score_bins'].append({'id':'secondH','model':'second','conditions':[{'op':'>','value':.5}],'source_expression':'second exact high bin','source_excerpt':0})
 d['quantities']['bins'].append({'id':'secondH','low':[3],'high':[4]})
 d['events']=write(ep,e);t['input_sha256']=write(p,d)['sha256'];r=m.run(t,tmp_path,tmp_path/'out')
 assert r['quantities']['covariance'][0][3]==8
 assert r['population']['models']==2 and len(r['events'])==5


@pytest.mark.parametrize('number,branch',[(-3,'even'),(-2,'even'),(-1,'even'),(0,'even'),(1,'odd'),(2,'even'),(3,'odd')])
def test_actual_cxx_signed_remainder_model_routing(number,branch):
 c={'routing':{'kind':'event_number_cxx_modulo','modulus':2,'odd_only_remainder':1,'otherwise':'even','selected':branch}}
 assert m._route(c,number,True)
 c['routing']['selected']='odd' if branch=='even' else 'even';assert not m._route(c,number,True)


def test_parity_route_does_not_drop_vetoed_or_wrong_branch_event(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch)
 d['models'][0]['contract']['routing']={'kind':'event_number_cxx_modulo','modulus':2,'odd_only_remainder':1,'otherwise':'even','selected':'even'}
 e['events'][1]['eligible']['m']=False;e['events'][1]['features']['m']=None
 d['events']=write(ep,e);t['input_sha256']=write(p,d)['sha256'];r=m.run(t,tmp_path,tmp_path/'out')
 assert r['population']['events']==5 and r['population']['unselected_events']==2
 assert r['events'][1]['inference']['m'] is None
 e['events'][1]['eligible']['m']=True;e['events'][1]['features']['m']={'x':.2,'y':0}
 d['events']=write(ep,e);t['input_sha256']=write(p,d)['sha256']
 with pytest.raises(ValueError,match='routing'):m.run(t,tmp_path,tmp_path/'wrong')


def test_unknown_routing_refuses_before_inference(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);d['models'][0]['contract']['routing']={'kind':'guessed'};t['input_sha256']=write(p,d)['sha256']
 monkeypatch.setattr(domains,'onnx_session',lambda *_a,**_k:pytest.fail('optional inference loaded before refusal'))
 with pytest.raises(ValueError,match='routing'):m.inputs(t,tmp_path)


def test_original_classifier_uses_same_checked_loader_with_batch_semantics(tmp_path,monkeypatch):
 import numpy as np
 class Batch:
  def run(self,names,feed):
   assert names==['output']
   return [np.asarray([[r[0],r[1],r[0]+r[1]] for r in feed['input']],dtype='float32')]
 engine(monkeypatch,Batch(),[None,2])
 task,d,e,p,ep=case(tmp_path)
 old={'units':{'x':'1','y':'GeV'},'events':[{'event_id':'a','values':{'x':.5,'y':0},'weight':-2},{'event_id':'b','values':{'x':.75,'y':0},'weight':3}]}
 controls={**copy.deepcopy(old),'expected_scores':[.5,.75]};write(tmp_path/'old.json',old);write(tmp_path/'controls.json',controls)
 c={'model_file':'model.onnx','events_file':'old.json','controls_file':'controls.json','features':[{'name':'x','unit':'1','mean':0,'scale':1},{'name':'y','unit':'GeV','mean':0,'scale':1}],'dtype':'float32','input_name':'input','output_name':'output','score_index':0,'threshold':.5,'comparison':'>','score_range':[0,1],'atol':1e-6,'rtol':1e-6}
 r,limits=domains._classifier(c,tmp_path)
 assert r['checks_passed'] and r['selected_sumw']==3 and r['selected_sumw2']==9
 assert not r['events'][0]['selected'] and r['events'][0]['weight']==-2
 assert r['runtime']=='synthetic-session'


@pytest.mark.parametrize('fault',['changed','ABA','extra_member'])
def test_native_output_ending_custody_remains_original(tmp_path,monkeypatch,fault):
 t,d,p,n=native_case(tmp_path,monkeypatch);out=tmp_path/'out'
 def run(task,base,folder,*,worker_started):
  folder.mkdir();(folder/'observables.json').write_text('{"native":1}');return {'status':'passed','physics_validated':False}
 monkeypatch.setattr(n,'run_in_worker',run)
 old=m._Custody.finish
 def finishing(self):
  old(self)
  if self.limit==m.LIMIT and (out/'published-classifier.json').exists():
   leaf=out/'native/observables.json';raw=leaf.read_bytes()
   if fault in ('changed','ABA'):leaf.write_bytes(b'{"native":2}')
   if fault=='ABA':leaf.write_bytes(raw)
   if fault=='extra_member':(out/'native/foreign').write_text('unexpected')
 monkeypatch.setattr(m._Custody,'finish',finishing)
 with pytest.raises(ValueError,match='changed'):m.run_in_worker(t,tmp_path,out,worker_started=123)


def test_generated_commitment_drift_after_source_finalization_refuses(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);engine(monkeypatch);out=tmp_path/'out';old=m._Custody.finish
 def finish(self):
  old(self)
  dest=out/'published-classifier.json'
  if dest.exists():dest.write_bytes(b'{"status":"untruthful"}')
 monkeypatch.setattr(m._Custody,'finish',finish)
 with pytest.raises(ValueError,match='commitment changed'):m.run(t,tmp_path,out)


def test_native_helper_declaration_keeps_original_lineage_and_actual_path(tmp_path,monkeypatch):
 from ravel.physics import native_incumbent
 t,d,p,n=native_case(tmp_path,monkeypatch);lineage={'path':'lineage.json','sha256':'0'*64}
 d['native_task']['improvement_lineage']=lineage;d['native_task']['improvement_evaluation']=lineage;t['input_sha256']=write(p,d)['sha256']
 seen=[]
 monkeypatch.setattr(native_incumbent,'helper_declaration',lambda *args,**kw:seen.append((args,kw)) or {'unchanged':'declaration'})
 marker=object();assert m.helper_declaration(t,tmp_path,tmp_path/'attempt',_session=marker)=={'unchanged':'declaration'}
 assert seen==[((lineage,tmp_path,tmp_path/'attempt/published-classifier/native'),{'_session':marker})]


@pytest.mark.parametrize('fault',['custom_domain','external_data','input_type','input_name','input_shape','missing_output',None])
def test_actual_shared_checked_loader_body_with_inert_sdk_interfaces(tmp_path,monkeypatch,fault):
 import types,sys
 class Message:
  def __init__(self,name,domain='',external=False,children=()):
   self.DESCRIPTOR=types.SimpleNamespace(full_name=name);self.domain=domain;self.external_data=[];self.data_location=1 if external else 0;self.children=children
  def ListFields(self):return [(types.SimpleNamespace(message_type=True,is_repeated=True),self.children)] if self.children else []
 node=Message('onnx.NodeProto',domain='foreign' if fault=='custom_domain' else '')
 tensor=Message('onnx.TensorProto',external=fault=='external_data');proto=Message('onnx.ModelProto',children=[node,tensor]);seen=[]
 onnx=types.SimpleNamespace(load_model_from_string=lambda raw:proto,TensorProto=types.SimpleNamespace(EXTERNAL=1),checker=types.SimpleNamespace(check_model=lambda p:seen.append('checked')))
 class Options:pass
 class Loaded:
  def get_inputs(self):return [types.SimpleNamespace(name='foreign' if fault=='input_name' else 'input',type='tensor(int64)' if fault=='input_type' else 'tensor(float)',shape=[1,9] if fault=='input_shape' else [1,2])]
  def get_outputs(self):return [types.SimpleNamespace(name='foreign' if fault=='missing_output' else 'output')]
 def factory(raw,sess_options,providers):
  assert raw==b'held-model' and sess_options.intra_op_num_threads==sess_options.inter_op_num_threads==1 and providers==['CPUExecutionProvider'];seen.append('CPU factory');return Loaded()
 ort=types.SimpleNamespace(SessionOptions=Options,InferenceSession=factory,__version__='synthetic-ORT-interface')
 monkeypatch.setitem(sys.modules,'onnx',onnx);monkeypatch.setitem(sys.modules,'onnxruntime',ort)
 if fault:
  with pytest.raises(ValueError):domains.onnx_session(b'held-model',input_name='input',output_name='output',dtype='float32',feature_count=2)
 else:
  np,s,shape,v=domains.onnx_session(b'held-model',input_name='input',output_name='output',dtype='float32',feature_count=2)
  assert shape==[1,2] and v=='synthetic-ORT-interface' and seen==['checked','CPU factory']


def test_tensor_accounting_ceiling_refuses_before_optional_engine(tmp_path,monkeypatch):
 t,d,e,p,ep=case(tmp_path);monkeypatch.setattr(m,'MAX_EVENTS',4)
 monkeypatch.setattr(domains,'onnx_session',lambda *_a,**_k:pytest.fail('must not load optional inference'))
 with pytest.raises(ValueError,match='census'):m.inputs(t,tmp_path)


def test_existing_public_cli_routes_new_mode_to_same_planner(tmp_path,monkeypatch):
 from types import SimpleNamespace
 from ravel import cli
 from ravel.workflow import science
 t,d,e,p,ep=case(tmp_path);spec=tmp_path/'spec.json';write(spec,{'mode':'published-classifier','task':t});seen=[]
 monkeypatch.setattr(science,'plan',lambda *args:seen.append(args) or {'mode':'published-classifier'})
 rd=tmp_path/'ordinary'
 assert cli._plan(SimpleNamespace(spec=spec,rundir=rd))==0
 assert seen==[(rd,spec)] and not rd.exists()
