from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ravel.physics import contur_population as cp,contur_yoda as cy,contur_import as ci

@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
 import subprocess,socket,os
 def denied(*a,**k):raise AssertionError('source-only worker forbids external calls')
 monkeypatch.setattr(subprocess,'Popen',denied);monkeypatch.setattr(socket,'socket',denied);monkeypatch.setattr(os,'system',denied)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def settings(profile='default3',operation='grid'):
 s=dict(cy.FIXED)
 s.update({k:False for k in cy.BOOL_FLAGS});s.update({k:True for k in cy.INVERSE_FLAGS})
 s.update(stat_types=list(cp.PROFILES[profile]),offline=False,npyscripts=0 if operation=='grid' else -1,
  keep_unscaled_aos=operation=='single',use_spey=False,min_num_sys=2,min_num_sys_sm=2,
  add_sqrt_evtcount_signal_error=True,flat_uncertainty=None,only_analyses=[],veto_analyses=[],weight='',sorting_metric='LLR')
 return s
def doc(profile='default3',operation='grid'):
 return {'schema_version':3,'operation':operation,'profile':profile,'settings':settings(profile,operation)}
def fixture(tmp_path):
 root=tmp_path/'original';root.mkdir();points=[]
 for ident,value in [('0000','1.5'),('0001','4.5')]:
  inputs=[]
  for beam in ['7TeV','13_6TeV']:
   d=root/beam/ident;d.mkdir(parents=True);(d/'params.dat').write_text('m = '+value+'\nc = 0.25\n')
   rel=beam+'/'+ident+'/runpoint_'+ident+'.yoda.gz';(root/rel).write_bytes(b'explicit inert source YODA')
   inputs.append({'beam':beam,'source_yodas':[rel],'native_yodas':[rel],'expected_events':{rel:17}})
  points.append({'id':ident,'parameters':{'m':value,'c':'0.25'},'inputs':inputs})
 m=tmp_path/'grid.json';m.write_text(json.dumps({'schema_version':1,'kind':'contur-input-grid','root':str(root),'files':cy._workspace_inventory(root)}))
 return {'manifest':pin(m),'beams':['7TeV','13_6TeV'],'beam_selection':'all','tag':'runpoint','points':points},root

@pytest.mark.parametrize('profile',cp.PROFILES)
def test_profiles_and_literal_cli(profile):
 d=doc(profile);d['grid']={'beam_selection':'all','beams':['7TeV'],'tag':'runpoint'}
 args=cp.arguments(d,Path('/owned'))
 assert '--grid' in args and '--nomultip' in args and '--offline' not in args
 assert ('--no-exp' in args)==(profile=='no-exp2')
 assert ('--databg' in args)==(profile=='full4')
 assert args[args.index('--csv')+1]=='native.csv'
 d['settings']['offline']=True;assert '--offline' in cp.arguments(d,'/owned')

def test_single_original_two_mode_flags():
 d=doc('no-exp2','single');d['yoda']={'path':'run.yoda'}
 args=cp.arguments(d,'/owned');assert args[0]=='/owned/input/run.yoda' and '--grid' not in args and '--no-exp' in args

@pytest.mark.parametrize('bad',[['SMBG'],['SMBG','HLEXP','EXP'],['UNKNOWN','EXP','HLEXP']])
def test_profile_mismatch(bad):
 d=doc();d['settings']['stat_types']=bad
 with pytest.raises(ValueError):cp.settings(d)

def test_grid_complete_all_parameters(tmp_path):
 g,root=fixture(tmp_path);manifest,actual,files=cp.grid_admission(g,tmp_path)
 assert actual==root and len(files)==9 and manifest['files']==cy._workspace_inventory(root)
 assert len(g['points'])==2 and all(len(p['parameters'])==2 for p in g['points'])

@pytest.mark.parametrize('attack',['missing_beam','missing_param','duplicate_point','extra_yoda','changed_bytes','unknown_point','source_swap'])
def test_grid_refusals(tmp_path,attack,monkeypatch):
 g,root=fixture(tmp_path)
 if attack=='missing_beam':g['points'][0]['inputs'].pop()
 if attack=='missing_param':g['points'][0]['parameters'].pop('c')
 if attack=='duplicate_point':g['points'][1]['id']='0000'
 if attack=='extra_yoda':(root/'extra.yoda').write_text('x')
 if attack=='changed_bytes':(root/'7TeV/0000/params.dat').write_text('m = 99\nc = 0.25\n')
 if attack=='unknown_point':g['points'].pop()
 if attack=='source_swap':
  old=cp.source_bytes
  def swap(p,h):return b'm = 99\nc = 0.25\n' if str(p).endswith('params.dat') else old(p,h)
  monkeypatch.setattr(cp,'source_bytes',swap)
 with pytest.raises(ValueError):cp.grid_admission(g,tmp_path)

def test_source_buffer_admission(tmp_path):
 p=tmp_path/'source';p.write_bytes(b'A');h=sha(p);assert cp.source_bytes(p,h)==b'A'
 p.write_bytes(b'B')
 with pytest.raises(ValueError):cp.source_bytes(p,h)

def test_group_exact_all_beams_not_independent_runs(tmp_path):
 g,root=fixture(tmp_path);d=doc();d['grid']=g;work=tmp_path/'work';target=work/'input/grid'
 import shutil
 shutil.copytree(root,target)
 jobs={p['id']:{'params':p['parameters'],'yoda_files':[str(target/r) for i in reversed(p['inputs']) for r in i['native_yodas']]} for p in g['points']}
 rows=cp.check_jobs(jobs,d,work)
 assert len(rows)==2 and all(len(r['native_yoda_order'])==2 for r in rows.values())
 jobs['0000']['yoda_files'].pop()
 with pytest.raises(ValueError):cp.check_jobs(jobs,d,work)

def point(d,paths,ident='0000'):
 return SimpleNamespace(runpoint=ident,parameter_values={'m':'1.5','c':'0.25'},yoda_paths=paths,
  yoda_info={p:{'num_events':17,'xsec':.25} for p in paths},
  full_likelihood_results={m:{'CLs':.75,'NLL':None,'LLR':None,'mu_hat':None,'mu_lower_limit':None,'mu_upper_limit':None} for m in cp.modes(d)},
  sorted_blocks_results={m:{'pool':{'CLs':.5,'histos':'h'}} for m in cp.modes(d)},get_dominant_pool=lambda m:'pool',get_dominant_hist_name=lambda m:'h')

def test_first_entry_is_ordered_not_summed_exposure(tmp_path):
 g,_=fixture(tmp_path);d=doc();d['grid']=g;work=tmp_path/'work'
 paths=[str(work/'input/grid'/i['native_yodas'][0]) for i in reversed(g['points'][0]['inputs'])]
 w=cp.point_witness(point(d,paths),d,work)
 assert w['native_first_entry']['path']==paths[0] and w['native_first_entry']['num_events']==17
 assert [r['path'] for r in w['ordered_yoda_info']]==paths

@pytest.mark.parametrize('bad',['missing','unknown','none','empty_pool','missing_event'])
def test_native_population_refuses_missing_results(tmp_path,bad):
 g,_=fixture(tmp_path);d=doc();d['grid']=g;work=tmp_path/'work';paths=[str(work/'input/grid'/i['native_yodas'][0]) for i in g['points'][0]['inputs']];p=point(d,paths)
 if bad=='missing':p.full_likelihood_results.pop('EXP')
 if bad=='unknown':p.full_likelihood_results['UNKNOWN']={}
 if bad=='none':p.full_likelihood_results['EXP']['CLs']=None
 if bad=='empty_pool':p.sorted_blocks_results['EXP']={}
 if bad=='missing_event':p.yoda_info[paths[0]]['num_events']=None
 with pytest.raises(ValueError):cp.point_witness(p,d,work)

def test_cached_no_exp_census_and_delivery(tmp_path):
 from test_contur_import import database
 db=tmp_path/'native.db';database(db)
 import sqlite3
 with sqlite3.connect(db) as conn:
  conn.execute("DELETE FROM exclusions WHERE stat_type='EXP'");conn.execute("DELETE FROM run WHERE stat_type='EXP'")
 points=ci.decode_database(db,modes=ci.NO_EXP_MODES)
 assert all([r['raw']['stat_type'] for r in p['runs']]==list(ci.NO_EXP_MODES) for p in points)
 out=tmp_path/'out';out.mkdir();result={'points':points,'physics_validated':False}
 commits=ci.mode_delivery(out,'results.json',result,points,modes=ci.NO_EXP_MODES)
 ci.verify_full_mode_delivery(out,'results.json',result,commits)
 result['physics_validated']=True
 with pytest.raises(ValueError):ci.verify_full_mode_delivery(out,'results.json',result,commits)

def test_effective_no_unsupported_drift():
 d=doc();cfg=SimpleNamespace(**d['settings']);assert not cp.check_effective(d,cfg)['source_observed_offline_fallback']
 cfg.offline=True
 with pytest.raises(ValueError):cp.check_effective(d,cfg)
 with pytest.raises(ValueError):cp.check_effective(d,cfg,[{'source_observed_fallback':True}])
 cfg.flat_uncertainty=.1
 with pytest.raises(ValueError):cp.check_effective(d,cfg,[{'source_observed_fallback':True}])

def test_document_strict_duplicate_overflow(tmp_path):
 p=tmp_path/'bad.json'
 for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":1e1000}'):
  p.write_text(text)
  with pytest.raises(ValueError):cp.document(p)

def native_database(db,d,work):
 import sqlite3
 obs={'points':{},'citation_calls':[],'effective_settings':{'effective':d['settings']},'ending_effective_settings':{'effective':d['settings']}}
 with sqlite3.connect(db) as conn:
  for table,cols in ci.REQUIRED_COLUMNS.items():
   conn.execute('CREATE TABLE '+table+' ('+','.join(x+' '+('TEXT' if x in {'run_point','yoda_files','name','stat_type','addition_argument','pool_name','histos'} else 'INTEGER' if x in {'id','model_id','model_point_id','run_id','map_id','events_num'} else 'DOUBLE') for x in cols)+')')
  for n,p in enumerate(d['grid']['points'],1):
   paths=[str(work/'input/grid'/r) for i in p['inputs'] for r in i['native_yodas']]
   obj=point(d,paths,p['id']);obj.parameter_values=p['parameters']
   w=cp.point_witness(obj,d,work);obs['points'][p['id']]=w
   conn.execute('INSERT INTO model_point VALUES (?,?,?,?)',(n,1,p['id'],repr(paths)))
   conn.executemany('INSERT INTO parameter_value VALUES (?,?,?)',[(n,k,float(v)) for k,v in p['parameters'].items()])
   for j,m in enumerate(cp.modes(d),1):
    rid=n*10+j;conn.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(rid,n,1,17,m,.75,None,None,None,None,None,'INERT SOURCE CONTROL'))
    conn.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(rid,rid,'pool',m,.5,'h',None,None,None,None,None))
 return obs

def runnable_fixture(tmp_path,profile):
 from test_contur_yoda import fixture as old_fixture,write
 task,d=old_fixture(tmp_path);g,_=fixture(tmp_path)
 for key in ('yoda','parameters','expected_events'):d.pop(key)
 d.update(schema_version=3,operation='grid',profile=profile,settings=settings(profile),grid=g)
 write(Path(task['input']),d)
 return task,d

@pytest.mark.parametrize('profile',cp.PROFILES)
def test_real_outer_adapter_with_inert_complete_native_returns(tmp_path,monkeypatch,profile):
 from ravel.physics import reinterpret_db
 task,d=runnable_fixture(tmp_path,profile);out=tmp_path/'out'
 monkeypatch.setattr(cy,'_approved',lambda *a:(tmp_path,{'max_seconds':60}))
 issued=[]
 def capture(command,output,document):
  issued.append(command);work=out/'contur-work';native=work/'native-output';native.mkdir()
  obs=native_database(native/'results.db',document,work)
  (work/'native-observation.json').write_text(json.dumps(obs))
  points=ci.decode_database(native/'results.db',modes=cp.modes(document))
  (native/'native.csv').write_text(ci.export_csv(points,modes=cp.modes(document)))
  return {'returncode':0,'scope':'inert supplied returns; no Contur/fit/child scientific call'}
 monkeypatch.setattr(reinterpret_db,'execute_native',capture)
 result=cy.run(task,tmp_path,out)
 assert len(issued)==1 and result['profile']==profile and len(result['points'])==2
 assert result['physics_validated'] is False and result['native_csv']['row_count']==2
 assert result['mode_population']==list(cp.PROFILES[profile])
 assert (out/'native-columns.csv').read_text().splitlines()[0].count('CL')==len(cp.PROFILES[profile])

@pytest.mark.parametrize('target',['json','csv','native_db','observation','live_return'])
def test_ending_input_read_cannot_change_output_commitment(tmp_path,monkeypatch,target):
 from ravel.physics import reinterpret_db
 task,d=runnable_fixture(tmp_path,'no-exp2');out=tmp_path/'out';old=cy.inputs;old_delivery=ci.mode_delivery
 delivered=[False];live={}
 def capture(command,output,document):
  work=out/'contur-work';native=work/'native-output';native.mkdir();obs=native_database(native/'results.db',document,work)
  (work/'native-observation.json').write_text(json.dumps(obs));points=ci.decode_database(native/'results.db',modes=cp.modes(document))
  (native/'native.csv').write_text(ci.export_csv(points,modes=cp.modes(document)));return {'returncode':0,'scope':'inert'}
 def delivery(*a,**k):
  commits=old_delivery(*a,**k);delivered[0]=True;live['result']=a[2];return commits
 def inputs(*a,**k):
  result=old(*a,**k)
  if delivered[0]:
   paths={'json':out/'contur-results.json','csv':out/'native-columns.csv','native_db':out/'contur-work/native-output/results.db','observation':out/'contur-work/native-observation.json'}
   if target=='live_return':live['result']['physics_validated']=True
   else:paths[target].write_bytes(b'ending mutation')
  return result
 monkeypatch.setattr(cy,'_approved',lambda *a:(tmp_path,{'max_seconds':60}));monkeypatch.setattr(reinterpret_db,'execute_native',capture)
 monkeypatch.setattr(ci,'mode_delivery',delivery);monkeypatch.setattr(cy,'inputs',inputs)
 with pytest.raises(ValueError):cy.run(task,tmp_path,out)

def test_ordinary_schema2_preparation_no_approval_or_science(tmp_path):
 from test_contur_yoda import write
 task,d=runnable_fixture(tmp_path,'default3')
 policy={'policy':{'schema_version':1,'actors':{'proposer':'source-proposer','executor':'root-executor','physics_critic':'independent-critic','skeptical_verifier':'independent-verifier','physics_decider':'independent-decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'protocol','kind':'scientific'}],'claim_scopes':{'explicit_contur_population':{'checks':['integrity','protocol'],'actions':['delivery']}}},'correction_contract':{'input_slots':[],'task_fields':[]}}
 policy['schema_version']=1
 p=write(tmp_path/'review-policy.json',policy)
 result=cy.prepare(task['input'],p,tmp_path/'ordinary-spec.json',approval_mode='scripted_yes')
 assert result['schema_version']==2 and result['mode']=='contur-yoda' and result['max_attempts']==1
 assert result['task']==task and not (tmp_path/'approval.json').exists()
 assert 'declared grid' in result['assumptions'][0] and 'single-point' not in result['assumptions'][0]



def test_native_integral_float_event_accessor_preserved(tmp_path):
 task,d=runnable_fixture(tmp_path,'default3')
 paths=[str(tmp_path/'work/input/grid'/r) for i in d['grid']['points'][0]['inputs'] for r in i['native_yodas']]
 p=point(d,paths,'0000')
 for v in p.yoda_info.values():v['num_events']=float(v['num_events'])
 w=cp.point_witness(p,d,tmp_path/'work')
 assert type(w['native_first_entry']['num_events']) is float and w['native_first_entry']['num_events']==17.0
