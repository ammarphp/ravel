"""Portable fabricated source/trace controls; no native execution qualification."""
import copy,gzip,hashlib,json,math,os
from pathlib import Path
import pytest
from ravel.physics import native_group_fills as n

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def block(kind,path,body):return 'BEGIN YODA_'+kind+'_V3 '+path+'\n'+body+'\nEND YODA_'+kind+'_V3\n\n'
def fixture(tmp_path,monkeypatch,mode='NU'):
 source=tmp_path/'source.cc';source.write_text('Fabricated portable source fill defaults1; no physical source acceptance.\n'+'\n'.join('fill_'+str(i)+'();' for i in range(4)))
 sha=pin(source)['sha256']
 naming=[]
 for i in range(3):
  q=tmp_path/('naming'+str(i)+'.hh');q.write_text('Fabricated option namespace source '+str(i));naming.append(pin(q))
 units=tmp_path/'Units.hh';units.write_text('constexpr double gigaelectronvolt = 1.;\nconstexpr double GeV = gigaelectronvolt;\n')
 event=tmp_path/'events.hepmc';event.write_text('Fabricated independent supplied event identity only.\n')
 alias='ANA-0001'+':LMODE='+mode;y=2 if mode=='NU' else 4;prefix='_' if mode=='NU' else ''
 outputs=[{'id':'d'+str(i),'site':i-1,'path':'/'+alias+'/'+prefix+'d%02d-x01-y%02d'%(i,y),'edges':[0.,1.,2.],'axis_unit':'RAD' if i==4 else 'GEV','unit':'1','source_fill_weight':1,'source_fill_fraction':1,'reference_path':'/ANA-0001/d%02d-x01-y%02d'%(i,y)} for i in range(1,5)]
 ref=tmp_path/'ref.yoda.gz';ref.write_bytes(gzip.compress(''.join(block('ESTIMATE1D','/REF/'+'ANA-0001'+'/d%02d-x01-y%02d'%(i,y),'Edges(A1): [0.0, 1.0, 2.0]\n---') for i in range(1,5)).encode()))
 names=[{'id':'nominal','native':'','raw_suffix':''},{'id':'up','native':'up','raw_suffix':'[up]'}]
 weights=[[2.,3.],[-1.,0.],[0.,-2.]];fills=[[{'site':i,'coordinates':[.5]} for i in range(4)],[{'site':0,'coordinates':[1.5]}],[]]
 events=[{'input_sha256':pin(event)['sha256'],'encounter_ordinal':i,'event_number':10+i,'selected_weights':w} for i,w in enumerate(weights)]
 trace=[{'schema':'ravel-native-fills/v1','routine':'ANA-0001','original_source_sha256':sha,'ordinal':i,'event_number':10+i,'pid':42,'unwinding':False,'native_weight_names':['','up'],'weights':w,'fills':fills[i]} for i,w in enumerate(weights)]
 tp=tmp_path/'trace.jsonl';tp.write_text('\n'.join(json.dumps(t) for t in trace)+'\n')
 text=''
 for wi,w in enumerate(names):
  suffix=w['raw_suffix']
  for o in outputs:
   a=weights[0][wi];b=weights[1][wi] if o['site']==0 else 0.;entries=1 if o['site']==0 else 0
   rows=[[0,0,0,0,0],[a,a*a,a*.5,a*.25,1],[b,b*b,b*1.5,b*2.25,entries],[0,0,0,0,0]]
   text+=block('HISTO1D','/RAW'+o['path']+suffix,'Edges(A1): [0.0, 1.0, 2.0]\n---\n# sumW sumW2 sumW(A1) sumW2(A1) numEntries\n'+'\n'.join(' '.join(format(v,'.17e') for v in row) for row in rows))
   text+=block('ESTIMATE1D',o['path']+suffix,'---\nnan -inf inf undefined')
  W=sum(v[wi] for v in weights);Q=sum(v[wi]**2 for v in weights)
  text+=block('COUNTER','/RAW/_EVTCOUNT'+suffix,'---\n# sumW sumW2 numEntries\n'+' '.join(format(v,'.17e') for v in (W,Q,3)))
  if mode=='NU':
   for i in range(1,5):
    path='/'+alias+'/d%02d-x01-y01'%i+suffix
    text+=block('ESTIMATE1D',path,'---\nnan undefined zero-denominator')+block('ESTIMATE1D','/RAW'+path,'---\nnan undefined zero-denominator')
 text+=block('ESTIMATE0D','/_XSEC','---\n1 0 0')
 yp=tmp_path/'whole.yoda';yp.write_text(text)
 contract={'schema_version':2,'routine':'ANA-0001','native_analysis_alias':alias,'native_plugin_identity':'ANA-0001','native_namespace_sources':naming,'original_source_sha256':sha,'group_rule':'independent_single_subevent','native_weight_cap':0,'same_process_pid':42,'events':events,'weight_mapping':names,'outputs':outputs,'reference':pin(ref),'analysis_options':{'LMODE':mode},'runtime_units':pin(units),'native_object_inventory':n.native_inventory(text)}
 contract['fill_schema']={'schema_version':1,'routine':'ANA-0001','native_analysis_alias':alias,'source':pin(source),'sources':[*naming,pin(units)],'sites':[{'id':i,'arity':1,'anchor':'fill_'+str(i)+'();','count':1,'max_per_event':1} for i in range(4)],'outputs':copy.deepcopy(outputs),'rules':[{'kind':'equal_count','sites':[1,2,3]},{'kind':'ordered','sites':[0,1,2,3]}],'native_object_paths':[row['path'] for row in contract['native_object_inventory']],'study':{'study_id':'ANA-0001','parameter_grid':[{'coordinate':1}],'datasets':['DATA-0001'],'output':{'stem':'native-group-acquisition-report','formats':['json','markdown']}}}
 cp=tmp_path/'original.json';cp.write_text(json.dumps(contract))
 evidence=tmp_path/'custody.json';evidence.write_text('{"scope":"fabricated portable source only","native_qualified":false}')
 request={'schema_version':1,'operation':'acquire-groups','contract':pin(cp),'trace':pin(tp),'raw_yoda':pin(yp),'source_evidence':pin(source),'event_inputs':[pin(event)],'execution_evidence':[pin(evidence)]}
 rp=tmp_path/'request.json';rp.write_text(json.dumps(request));task={'schema_version':1,'input':str(rp),'request_sha256':pin(rp)['sha256']}
 return task,request,contract,tp,yp

def refresh(task,request):
 p=Path(task['input']);p.write_text(json.dumps(request));task['request_sha256']=pin(p)['sha256']

@pytest.mark.parametrize('mode',['NU','EL'])
def test_signed_zero_complete_groups_flows_and_separate_estimators(tmp_path,monkeypatch,mode):
 task,r,c,t,y=fixture(tmp_path,monkeypatch,mode);out=n.run(task,tmp_path,tmp_path/'delivery');a=out['acquired']
 assert len(a['basis'])==32 and len(a['uncertainty']['groups'])==3 and a['raw_primitive_cells_checked']==166
 assert a['normalization_counter_by_weight']['nominal']['sumw']==1 and a['normalization_counter_by_weight']['nominal']['sumw2']==5
 assert a['normalization_counter_by_weight']['up']['sumw']==1 and a['normalization_counter_by_weight']['up']['sumw2']==13
 assert [x['weights'] for x in a['normalization_event_weights']]==[{'nominal':2.,'up':3.},{'nominal':-1.,'up':0.},{'nominal':0.,'up':-2.}]
 assert len(out['native_object_inventory'])==(35 if mode=='NU' else 19)
 assert out['native_object_inventory']==c['native_object_inventory'] and not out['native_values_errors_status_reinterpreted']
 assert not out['actual_native_execution_authenticated'] and not out['physics_validated']
 assert a==json.loads((tmp_path/'delivery/acquired.json').read_text())
 # Shared-event cross-output moment differs from any marginal per-fill error.
 g=a['uncertainty']['groups'][0]['values'];assert g[1]*g[5]==4

@pytest.mark.parametrize('fault',['missing_event_pin','wrong_source','wrong_trace','wrong_raw','extra_task_key','wrong_cap','bare_alias','missing_native_object','bad_raw_primitive','bool_size','nested_drift','unknown_operation'])
def test_source_graph_and_semantic_adverse(tmp_path,monkeypatch,fault):
 task,r,c,t,y=fixture(tmp_path,monkeypatch)
 if fault=='missing_event_pin':r['event_inputs']=[]
 elif fault=='wrong_source':r['source_evidence']=r['event_inputs'][0]
 elif fault=='wrong_trace':r['trace']['sha256']='0'*64
 elif fault=='wrong_raw':r['raw_yoda']['sha256']='0'*64
 elif fault=='extra_task_key':task['native_qualified']=True
 elif fault=='bool_size':r['trace']['size']=True
 elif fault=='nested_drift':Path(c['native_namespace_sources'][0]['path']).write_text('Changed supplied source')
 elif fault=='unknown_operation':r['operation']='infer-covariance'
 else:
  if fault=='wrong_cap':c['native_weight_cap']=False
  if fault=='bare_alias':c['native_analysis_alias']='ANA-0001'
  if fault=='missing_native_object':c['native_object_inventory'].pop()
  if fault=='bad_raw_primitive':y.write_text(y.read_text().replace('0.00000000000000000e+00','9.00000000000000000e+00',1));c['native_object_inventory']=n.native_inventory(y.read_text());r['raw_yoda']=pin(y)
  cp=Path(r['contract']['path']);cp.write_text(json.dumps(c));r['contract']=pin(cp)
 refresh(task,r)
 with pytest.raises(ValueError):n.inputs(task,tmp_path)
 assert not (tmp_path/'delivery').exists()

def test_full_input_inventory_nested_relative_pins_and_fresh_output(tmp_path,monkeypatch):
 task,r,c,t,y=fixture(tmp_path,monkeypatch)
 for row in c['native_namespace_sources']+[c['reference'],c['runtime_units']]:row['path']=Path(row['path']).name
 cp=Path(r['contract']['path']);cp.write_text(json.dumps(c));r['contract']=pin(cp);refresh(task,r)
 assert {p.name for p in n.inputs(task,tmp_path)}=={'request.json','original.json','trace.jsonl','whole.yoda','source.cc','events.hepmc','custody.json','ref.yoda.gz','Units.hh','naming0.hh','naming1.hh','naming2.hh'}
 out=tmp_path/'delivery';n.run(task,tmp_path,out);before={p.name:p.read_bytes() for p in out.iterdir()}
 with pytest.raises(ValueError,match='fresh'):n.run(task,tmp_path,out)
 assert before=={p.name:p.read_bytes() for p in out.iterdir()}

def test_descriptor_limit_and_reference_expansion_before_parse(tmp_path,monkeypatch):
 task,r,c,t,y=fixture(tmp_path,monkeypatch);monkeypatch.setattr(n,'LIMIT',10)
 with pytest.raises(ValueError,match='bounded'):n.inputs(task,tmp_path)
 monkeypatch.setattr(n,'LIMIT',32*1024*1024);monkeypatch.setattr(n,'REFERENCE_LIMIT',10)
 with pytest.raises(ValueError,match='expanded'):n.inputs(task,tmp_path)

def test_same_content_replacement_and_ending_ancestor_alias_refuse(tmp_path,monkeypatch):
 p=tmp_path/'file';p.write_text('same');cache={};token=n._SNAPSHOT.set(cache)
 try:
  n._read_bytes(p);p.unlink();p.write_text('same')
  with pytest.raises(ValueError,match='changed'):n._ending(cache)
 finally:n._SNAPSHOT.reset(token)
 folder=tmp_path/'folder';folder.mkdir();p=folder/'file';p.write_text('same');cache={};token=n._SNAPSHOT.set(cache)
 try:
  n._read_bytes(p);saved=tmp_path/'saved';folder.rename(saved);folder.symlink_to(saved,target_is_directory=True)
  with pytest.raises(ValueError,match='unlinked'):n._ending(cache)
 finally:n._SNAPSHOT.reset(token)

def test_duplicate_json_and_nonfinite_trace_refuse(tmp_path,monkeypatch):
 task,r,c,t,y=fixture(tmp_path,monkeypatch)
 t.write_text(t.read_text().replace('"pid": 42','"pid": 42, "pid": 42',1));r['trace']=pin(t);refresh(task,r)
 with pytest.raises(ValueError,match='duplicate'):n.inputs(task,tmp_path)


def test_real_ordinary_worker_filesystem_and_renderer(tmp_path,monkeypatch):
 from ravel.physics import science_worker
 from ravel.plotting import science_figures
 from ravel.workflow import science
 from ravel.workflow.state_io import atomic_json,read_json
 from test_science_capability_integration import specification
 task,r,c,t,y=fixture(tmp_path,monkeypatch);spec=specification('native-group-acquisition',task)
 assert science.adapter(spec).__name__=='ravel.physics.native_group_fills' and science._new_capability(spec)
 rd=tmp_path/'worker';(rd/'inputs').mkdir(parents=True)
 atomic_json(rd/'inputs/science.json',spec);atomic_json(rd/'inputs/science-plan.json',{'schema_version':2,'execution_task':task,'mutable_inputs':[]});atomic_json(rd/'inputs/science-execution-task.json',{'schema_version':1,'task':task})
 monkeypatch.setattr(science_worker,'verify_worker',lambda _:{'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','stage_binding':{'input_snapshot':{}}})
 monkeypatch.setattr(science_figures,'render',lambda *_:{'figures':[],'tables':[]})
 assert science_worker.main([str(rd),'--attempt','1'])==0
 out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
 assert result==read_json(out/'native-group-acquisition/native-group-acquisition.json')
 assert read_json(out/'checkin2.json')['sections']['waypoint']['status']=='passed'
 old={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
 with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])
 assert old=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
 tables=n.write_report(result,tmp_path);assert tables[0]['stem']=='native-group-acquisition-report'


def test_actual_renderer_complete_table(tmp_path,monkeypatch):
 from ravel.plotting.science_figures import render
 task,r,c,t,y=fixture(tmp_path,monkeypatch);result=n.run(task,tmp_path,tmp_path/'delivery')
 report=render({'mode':'native-group-acquisition','task':task},result,tmp_path,tmp_path)
 assert report['status']=='passed' and not report['figures'] and report['tables'][0]['stem']=='native-group-acquisition-report'
 assert (tmp_path/'native-group-acquisition-report.md').is_file()


def test_v1_public_envelope_refuses_before_worker(tmp_path,monkeypatch):
 from ravel.workflow import science
 from test_science_capability_integration import specification
 task,_,_,_,_=fixture(tmp_path,monkeypatch);spec=specification('native-group-acquisition',task)
 spec['schema_version']=1;spec.pop('review_policy');spec.pop('max_attempts')
 source=tmp_path/'legacy-science.json';source.write_text(json.dumps(spec))
 with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'worker',source)
 assert not (tmp_path/'worker').exists()

def test_changed_input_after_inventory_refuses_before_output(tmp_path,monkeypatch):
 task,r,c,t,y=fixture(tmp_path,monkeypatch);n.inputs(task,tmp_path);t.write_text(t.read_text()+'\n')
 with pytest.raises(ValueError,match='digest'):n.run(task,tmp_path,tmp_path/'delivery')
 assert not (tmp_path/'delivery').exists()


def test_aggregate_snapshot_limit_refuses_without_truncation(tmp_path,monkeypatch):
 task,r,c,t,y=fixture(tmp_path,monkeypatch);monkeypatch.setattr(n,'TOTAL_LIMIT',10)
 with pytest.raises(ValueError,match='snapshot graph'):n.inputs(task,tmp_path)
 assert not (tmp_path/'delivery').exists()

def test_two_supplied_fill_contracts_change_identity_grid_datasets_and_report(tmp_path):
 from group_fill_fixture import supplied
 results=[]
 for identity,weights,edges,sites,formats in [('ANA_0001',[2.,-1.,0.],[0,1,3],1,['json']),('ANA_0002',[3.,-2.,1.,0.],[0,2,5,9],2,['markdown'])]:
  c,t,y=supplied(tmp_path/identity,identity,weights,edges,sites,formats)
  result=n.acquire(t,y,c,expected_trace_sha256=pin(t)['sha256'],expected_raw_sha256=pin(y)['sha256']);a=result['acquired']
  assert a['logical_source_routine']==identity and len(a['basis'])==sites*(len(edges)+1) and len(a['uncertainty']['groups'])==len(weights)
  # Independent preservation oracle: repeated fills share one event weight.
  group_values=[g['values'][1] for g in a['uncertainty']['groups']]
  assert group_values==[2*weights[0],*weights[1:]]
  assert sum(v*v for v in group_values)==4*weights[0]**2+sum(w*w for w in weights[1:])
  assert sum(v*v for v in group_values)!=2*weights[0]**2+sum(w*w for w in weights[1:])
  report_dir=tmp_path/(identity+'-report');report_dir.mkdir();tables=n.write_report(result,report_dir)
  assert tables[0]['files']==[identity+'-table.'+('json' if formats==['json'] else 'md')]
  results.append(result)
 assert results[0]!=results[1]
 with pytest.raises(n.NativeGroupFillError) as caught:n.acquire('absent','absent',{},expected_trace_sha256='',expected_raw_sha256='')
 assert caught.value.reason=='missing_input'
