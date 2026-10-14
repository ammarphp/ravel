"""Portable fabricated source/tensor controls; no upstream corpus or inference."""
import copy,hashlib,json,struct
from pathlib import Path
import pytest
from ravel.physics import classifier_inputs as m

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def var(n):
 out=b''
 while n>127:out+=bytes([(n&127)|128]);n>>=7
 return out+bytes([n])
def f(n,v):return var(n*8)+(var(v)) if type(v) is int else var(n*8+2)+var(len(v))+v
def tensor(name,width,batch):
 dims=f(1,batch)+f(1,f(1,width));shape=f(2,dims);typ=f(1,f(1,1)+shape)
 return f(1,name.encode())+f(2,typ)

def setup(tmp_path,batch=None):
 batch=b'' if batch is None else f(2,batch.encode())
 raw=f(1,9)+f(7,f(11,tensor('input',2,batch))+f(12,tensor('output',3,batch)))
 model=tmp_path/'model.onnx';model.write_bytes(raw);src=tmp_path/'source.cc';src.write_text('input={x,y}; result=score[1]-score[0];\n')
 c={'kind':'source-classifier-feature-contract/v2','routine':'FABRICATED_PORTABLE_SOURCE','model':pin(model),'source':pin(src),'model_static':m.inspect(raw),'source_excerpts':[{'file':pin(src),'start':1,'end':1,'text':src.read_text().rstrip()}],'features':[{'id':v,'source_expression':v,'operation':'identity','cast':'float32','arithmetic':'binary32_each'} for v in ('x','y')],'feature_preprocessing_state':'declared_source_scalar_arithmetic','routing':{'kind':'supplied_fixed_model','event_route_qualified':False},'runtime_obligations':['Actual runtime and event projection require separate qualification'],'source_output_operation':{'kind':'difference','positive_index':1,'negative_index':0,'complete_model_output_width':3,'unused_output_indices':[2]},'event_reconstruction_qualified':False,'native_runtime_qualified':False,'source_arithmetic_not_native_bitwise_equivalence':True}
 p=tmp_path/'input.json';p.write_text(json.dumps({'kind':'source-classifier-input/v1','contract':c,'values':{'x':1.25,'y':2.75}}))
 t={'schema_version':1,'operation':'prepare-features','input':p.name,'input_sha256':pin(p)['sha256']}
 return t,c,p

def rewrite(t,p,doc):p.write_text(json.dumps(doc));t['input_sha256']=pin(p)['sha256']
def test_complete_normal_graph_literal_preparation_fresh_output(tmp_path):
 t,c,p=setup(tmp_path);before={x.name:x.read_bytes() for x in tmp_path.iterdir()}
 assert {x.name for x in m.inputs(t,tmp_path)}=={'input.json','source.cc','model.onnx'}
 r=m.run(t,tmp_path,tmp_path/'out');assert r['values']==[1.25,2.75]
 assert r['model_static']['outputs'][0]['shape']==[{'unknown':True},{'value':3}]
 assert r['source_output_operation']['unused_output_indices']==[2]
 assert not r['physics_validated'] and not r['inference_executed'] and r['model_scores'] is None
 assert before=={x.name:x.read_bytes() for x in tmp_path.iterdir() if x.is_file()}
 saved=(tmp_path/'out/classifier-inputs.json').read_bytes()
 with pytest.raises(ValueError,match='fresh'):m.run(t,tmp_path,tmp_path/'out')
 assert saved==(tmp_path/'out/classifier-inputs.json').read_bytes()

def test_symbolic_batch_remains_distinct(tmp_path):
 t,c,p=setup(tmp_path,'batch');r=m.run(t,tmp_path,tmp_path/'out')
 assert r['model_static']['inputs'][0]['shape'][0]=={'symbol':'batch'} and not r['symbolic_batch_resolved']

def test_static_census_admits_unlowered_features_without_claiming_scalars(tmp_path):
 t,c,p=setup(tmp_path);doc=json.loads(p.read_text());doc['values']={};doc['contract']['features']=[];doc['contract']['source_output_operation']=None
 rewrite(t,p,doc);t['operation']='static-census';r=m.run(t,tmp_path,tmp_path/'out')
 assert 'values' not in r and r['source_output_operation'] is None
 t['operation']='prepare-features'
 with pytest.raises(ValueError):m.inputs(t,tmp_path)

@pytest.mark.parametrize('fault',['extra_key','changed_source','wrong_digest','missing_feature','extra_feature','bool_feature','input_type','output_width','output_index','missing_output','unused_census','source_excerpt','native_claim','static_values','duplicate_json','nonfinite_json'])
def test_adverse_complete_source_and_interpretation(tmp_path,fault):
 t,c,p=setup(tmp_path);d=json.loads(p.read_text())
 if fault=='extra_key':d['hidden_inference']=True
 if fault=='changed_source':(tmp_path/'source.cc').write_text('altered')
 if fault=='wrong_digest':t['input_sha256']='0'*64
 if fault=='missing_feature':d['values'].pop('x')
 if fault=='extra_feature':d['values']['z']=1
 if fault=='bool_feature':d['values']['x']=True
 if fault=='input_type':d['contract']['features'][0]['cast']='float64'
 if fault=='output_width':d['contract']['source_output_operation']['complete_model_output_width']=2
 if fault=='output_index':d['contract']['source_output_operation']['positive_index']=3
 if fault=='missing_output':d['contract']['source_output_operation']=None
 if fault=='unused_census':d['contract']['source_output_operation']['unused_output_indices']=[]
 if fault=='source_excerpt':d['contract']['source_excerpts'][0]['text']='different'
 if fault=='native_claim':d['contract']['native_runtime_qualified']=True
 if fault=='static_values':t['operation']='static-census'
 if fault not in ('changed_source','wrong_digest'):rewrite(t,p,d)
 if fault=='duplicate_json':p.write_text('{"kind":1,"kind":2}');t['input_sha256']=pin(p)['sha256']
 if fault=='nonfinite_json':p.write_text('{"kind":NaN}');t['input_sha256']=pin(p)['sha256']
 with pytest.raises(ValueError):m.inputs(t,tmp_path)

def test_source_float_intermediates_and_log_domain():
 c={'features':[{'id':'x','source_expression':'(x-o)/s','operation':'normalize','cast':'float32','arithmetic':'binary32_each','offset':16777216.0,'scale':1.0}]}
 assert m.prepare_features(c,{'x':16777217.0})['values']==[0]
 c['features'][0]['arithmetic']='binary64_then_cast';assert m.prepare_features(c,{'x':16777217.0})['values']==[1]
 c['features'][0]['operation']='log10'
 with pytest.raises(ValueError):m.prepare_features(c,{'x':0})

def test_real_report_routes_before_optional_plot_imports(tmp_path):
 from ravel.plotting.science_figures import render
 t,c,p=setup(tmp_path);r=m.run(t,tmp_path,tmp_path/'out');report=render({'mode':'classifier-inputs','task':t},r,tmp_path,tmp_path)
 assert report['status']=='passed' and not report['figures']
 assert json.loads((tmp_path/'classifier-input-report.json').read_text())==r
 assert 'unknown' in (tmp_path/'classifier-input-report.md').read_text()

def test_actual_worker_filesystem_and_checkin2(tmp_path,monkeypatch):
 from ravel.physics import science_worker
 from ravel.plotting import science_figures
 from ravel.workflow import science
 from ravel.workflow.state_io import atomic_json,read_json
 from test_science_capability_integration import specification
 t,c,p=setup(tmp_path);s=specification('classifier-inputs',t)
 assert science.adapter(s) is m and science._new_capability(s)
 assert len(science.task_inputs(s,tmp_path))==3
 rd=tmp_path/'worker';(rd/'inputs').mkdir(parents=True)
 atomic_json(rd/'inputs/science.json',s);atomic_json(rd/'inputs/science-plan.json',{'schema_version':2,'execution_task':t,'mutable_inputs':[]});atomic_json(rd/'inputs/science-execution-task.json',{'schema_version':1,'task':t})
 proposal={'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}}
 monkeypatch.setattr(science_worker,'verify_worker',lambda _:proposal);monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
 assert science_worker.main([str(rd),'--attempt','1'])==0
 out=rd/'outputs/attempt-1';assert read_json(out/'result.json')==read_json(out/'classifier-inputs/classifier-inputs.json')
 assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
 saved={str(x.relative_to(out)):x.read_bytes() for x in out.rglob('*') if x.is_file()}
 with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
 assert saved=={str(x.relative_to(out)):x.read_bytes() for x in out.rglob('*') if x.is_file()}

def test_bounded_descriptor_initial_links_and_size(tmp_path):
 p=tmp_path/'big';p.touch()
 with p.open('r+b') as stream:stream.truncate(m.LIMIT+1)
 with pytest.raises(ValueError):m.bounded_read(p)
 q=tmp_path/'link';q.symlink_to(p)
 with pytest.raises(ValueError):m.bounded_read(q)
