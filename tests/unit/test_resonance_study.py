"""Supplied synthetic source/returned-format fixtures; zero native/scientific jobs."""
from copy import deepcopy
import hashlib,json,sqlite3
from pathlib import Path
import pytest
from ravel.workflow import resonance_study as rs,science,route_prompt,task_completion,execution,agent_host,agent_graph
from ravel.physics import contur_import
from ravel.workflow.state_io import atomic_json,read_json

PROMPT='Assuming toponium is actually a new resonance (for example, a heavy Higgs), produce a summary plot that assesses the limits on this signal from other analyses/searches at the LHC.'
def write(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);atomic_json(p,v);return pin(p)
def pin(p):return {'path':str(p.absolute()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def put(p,text):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return pin(p)
def policy():
 return {'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],'required_checks':[{'id':'integrity','kind':'integrity'}],'claim_scopes':{'diagnostic':{'checks':['integrity'],'actions':['delivery','reuse']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}
def parent(base):
 c=route_prompt.route(PROMPT);r=task_completion.initial_requirements(PROMPT)
 r['assignments']=[{'id':'resonance-child','purpose':'A finite component retaining the whole original P2 request.','coverage':[{'obligation_id':'original-request','criteria':r['obligations'][0]['criteria']}]}];c['task_requirements']=r
 q=base/'parent/inputs/task_contract.json';write(q,c);return {**pin(q),'size':q.stat().st_size}
def cached(base):
 p=base/'db.sqlite';p.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(p) as c:
  c.execute('CREATE TABLE model_point (id INTEGER PRIMARY KEY,model_id INTEGER,run_point TEXT,yoda_files TEXT)')
  c.execute('CREATE TABLE parameter_value (model_point_id INTEGER,name TEXT,value DOUBLE)')
  c.execute('CREATE TABLE run (id INTEGER PRIMARY KEY,model_point_id INTEGER,map_id INTEGER,events_num INTEGER,stat_type TEXT,combined_exclusion DOUBLE,nll DOUBLE,llr DOUBLE,mu_lower_limit DOUBLE,mu_upper_limit DOUBLE,mu_hat DOUBLE,addition_argument TEXT)')
  c.execute('CREATE TABLE exclusions (id INTEGER PRIMARY KEY,run_id INTEGER,pool_name TEXT,stat_type TEXT,exclusion DOUBLE,histos TEXT,nll DOUBLE,llr DOUBLE,mu_lower_limit DOUBLE,mu_upper_limit DOUBLE,mu_hat DOUBLE)')
  c.execute("INSERT INTO model_point VALUES (1,1,'0000',\"['/synthetic/retained.yoda']\")")
  c.execute("INSERT INTO parameter_value VALUES (1,'mass',400)")
  for i,m in enumerate(contur_import.MODES,1):
   c.execute('INSERT INTO run VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(i,1,1,5,m,.95,3.,2.,None,None,None,'SYNTHETIC'))
   c.execute('INSERT INTO exclusions VALUES (?,?,?,?,?,?,?,?,?,?,?)',(i,i,'synthetic_pool',m,.9,'/synthetic',2.,1.,None,None,None))
 src={'version':contur_import.VERSION,'commit':contur_import.COMMIT}
 for role in contur_import.SOURCE_ROLES:src[role]=put(base/(role+'.py'),'# Explicitly synthetic source fixture, not installed Contur\n'+role)
 d={'schema_version':1,'database':pin(p),'source':src,'modes':list(contur_import.MODES),'run_selection':{'policy':'latest_id_per_point_and_stat_type'},'scope':'Synthetic complete cached-format engineering control; no resonance constraint claim.'}
 return write(base/'input.json',d)
def fixture(base,two_searches=False):
 pp=parent(base);model=put(base/'model.txt','Explicitly synthetic physical interpretation source; no generated model.\n');source=put(base/'search.txt','Synthetic source applicability/format control only, no published measurement.\n')
 hs=[]
 for i,cp in enumerate(('even','odd')):
  hs.append({'id':'H'+str(i),'interpretation':'Declared neutral scalar alternative; not toponium physics validation.','spin':0,'cp':cp,'mass_gev':400.,'width_gev':20.,'energy_tev':13.,'production':['gg'],'decays':[{'products':[6,-6],'branching_ratio':1.}], 'couplings':[{'name':'yt','real':1.,'imag':0.,'unit':'1','convention':'Supplied synthetic vertex coefficient.'}], 'interference':'included_signed','basis':'sm_plus_bsm','model':model,'sources':[model],'missing':[]})
 searches=[{'id':'synthetic_search','experiment':'Synthetic','version':'Source-format control v1','source':source,'routine_ids':['synthetic_ttbar'],'applicability':{'mass_gev':[350.,750.],'width_over_mass':[.005,.25],'energy_tev':13.,'spins':[0],'cp':['even','odd'],'production':['gg'],'decays':[[6,-6]],'bases':['sm_plus_bsm','bsm']},'observable':{'quantity':'source exclusion confidence','unit':'1','confidence':'Source-defined cached confidence, not newly derived CLs','scope':'Synthetic existing import mechanics only'},'missing':[]}]
 if two_searches:searches.append({**deepcopy(searches[0]),'id':'other_search'})
 stages=[];pairs=[]
 for h in hs:
  for s in searches:
   cfg=cached(base/(h['id']+'_'+s['id']));study={'schema_version':2,'mode':'contur-import','source':'Explicitly synthetic complete native-format import control','assumptions':['No provider/native/physics execution or inferred resonance limit.'],'max_seconds':15,'approval_mode':'scripted_yes','max_attempts':1,'review_policy':policy(),'goal_binding':{'contract':pp,'assignment_id':'resonance-child'},'task':{'schema_version':1,'input':cfg['path']}}
   sp=write(base/(h['id']+'_'+s['id'])/'study.json',study);sid=h['id']+'_'+s['id']
   stages.append({'id':sid,'hypothesis':h['id'],'search':s['id'],'role':'constraint','study':sp,'documents':[{'id':'native_input','task_key':'input','source':cfg}], 'links':[],'exports':{'result':'result.json'},'claim_scope':'diagnostic','missing':[]})
   mapping={'hypothesis':h['id'],'search':s['id'],'hypothesis_sha256':rs._digest(h),'search_sha256':rs._digest(s),'basis':h['basis'],'observable':s['observable'],'sources':[model,source],'limitations':[]}
   mp=write(base/(sid+'-mapping.json'),mapping)
   pairs.append({'hypothesis':h['id'],'search':s['id'],'mapping':mp,'stages':[sid],'backend_portfolio':None,'missing':[]})
 req={'schema_version':1,'parent_contract':pp,'census_scope':'Complete supplied synthetic two-alternative × search fixture; not a literature census or scientific validation.','hypotheses':hs,'searches':searches,'correlations':[{'searches':[s['id'] for s in searches],'state':'unknown','sources':[],'meaning':'Cross-search correlations are unknown; no union.'}] if two_searches else [],'stages':stages,'pairs':pairs}
 path=base/'recipe.json';write(path,req);return path,req

@pytest.fixture(autouse=True)
def no_children(monkeypatch):
 import subprocess
 monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(OSError('source-only controls prohibit external processes')))
 monkeypatch.setattr(execution,'runtime_context',lambda:{'source_control_inert_runtime':True,'environment_sha256':execution.digest(execution.runtime_environment())})

def test_complete_two_physical_hypotheses_and_real_adapter_plan(tmp_path):
 p,r=fixture(tmp_path/'inputs');a=rs.assess(p)
 assert len(a['hypotheses'])==2 and len(a['pairs'])==2 and not any(x['blockers'] for x in a['pairs'])
 b=rs.prepare_stage(p,r['stages'][0]['id'],{},tmp_path/'prepared')
 spec=read_json(b['specification']['path']);assert spec['mode']=='contur-import' and spec['goal_binding']['contract']==r['parent_contract']
 assert Path(p) in science.task_inputs(spec,Path(b['specification']['path']).parent)
 rd=tmp_path/'ordinary';science.plan(rd,b['specification']['path']);science.verify_plan(rd,approved=False)
 assert not (rd/science.APPROVAL).exists() and not (rd/'execution_attempt.json').exists()
 assert not b['execution_authorized']

def test_unexecuted_whole_report_uses_actual_strict_report_and_parent(tmp_path):
 p,r=fixture(tmp_path/'inputs',two_searches=True);res=rs.collect(p,{},tmp_path/'report')
 assert len(res['pairs'])==4 and len(res['stages'])==4 and all(x['state']=='incomplete' for x in res['pairs'])
 assert res['cross_search_combination'] is None and res['correlations'][0]['state']=='unknown'
 assert not res['parent_completion']['parent_task_accepted']
 text=(tmp_path/'report/REPORT.md').read_text();assert PROMPT in text and 'H0--synthetic_search' in text and 'H1--other_search' in text

@pytest.mark.parametrize('fault',['duplicate_hyp','rename_only','drop_pair','drop_correlation','energy','production','decay','cp','width','unknown_interference','positive_basis','stale_mapping','scope','other_parent','extra_stage'])
def test_physical_basis_census_and_authority_adversaries(tmp_path,fault):
 p,r=fixture(tmp_path/'inputs',two_searches=True)
 if fault=='duplicate_hyp':r['hypotheses'][1]['id']='H0'
 elif fault=='rename_only':r['hypotheses'][1]={**deepcopy(r['hypotheses'][0]),'id':'H1'}
 elif fault=='drop_pair':r['pairs'].pop()
 elif fault=='drop_correlation':r['correlations']=[]
 elif fault in ('energy','production','decay','cp','width'):
  h=r['hypotheses'][0]
  if fault=='energy':h['energy_tev']=14.
  if fault=='production':h['production']=['qq']
  if fault=='decay':h['decays']=[{'products':[22,22],'branching_ratio':1.}]
  if fault=='cp':h['cp']='mixed'
  if fault=='width':h['width_gev']=200.
  for pair in r['pairs']:
   if pair['hypothesis']=='H0':
    q=Path(pair['mapping']['path']);m=read_json(q);m['hypothesis_sha256']=rs._digest(h);pair['mapping']=write(q,m)
  write(p,r);a=rs.assess(p);assert any(x['blockers'] for x in a['pairs'] if x['hypothesis']=='H0')
  with pytest.raises(ValueError,match='blockers'):rs.prepare_stage(p,r['stages'][0]['id'],{},tmp_path/'out')
  return
 elif fault=='unknown_interference':r['hypotheses'][0]['interference']='unknown'
 elif fault=='positive_basis':r['hypotheses'][0]['basis']='bsm'
 elif fault=='stale_mapping':r['hypotheses'][0]['couplings'][0]['real']=2.
 elif fault=='scope':r['stages'][0]['claim_scope']='global_physics'
 elif fault=='other_parent':
  q=Path(r['stages'][0]['study']['path']);s=read_json(q);s['goal_binding']['contract']=parent(tmp_path/'unrelated');r['stages'][0]['study']=write(q,s)
 elif fault=='extra_stage':r['stages'].append({**deepcopy(r['stages'][0]),'id':'unassigned'})
 write(p,r)
 with pytest.raises(ValueError):rs.assess(p)

def test_signed_interference_cannot_use_positive_signal_template(tmp_path):
 p,r=fixture(tmp_path/'inputs');stage=deepcopy(r['stages'][0]);stage['id']='bad_template';stage['role']='template';stage['documents']=[]
 s=read_json(stage['study']['path']);s['mode']='signal-template';s['task']={'input':r['stages'][0]['documents'][0]['source']['path']};stage['study']=write(tmp_path/'bad-study.json',s)
 r['stages'].append(stage);r['pairs'][0]['stages'].insert(0,'bad_template');write(p,r)
 assert 'positive pyhf' in ' '.join(rs.assess(p)['pairs'][0]['blockers'])
 with pytest.raises(ValueError):rs.prepare_stage(p,'bad_template',{},tmp_path/'out')

def test_fresh_ending_request_and_generated_files_not_recaptured(tmp_path,monkeypatch):
 p,r=fixture(tmp_path/'inputs');original=rs._write
 def mutate(out,name,value,capture):
  pin_=original(out,name,value,capture)
  if name=='preparation.json':(out/'native_input.json').write_text('{}')
  return pin_
 monkeypatch.setattr(rs,'_write',mutate)
 with pytest.raises(ValueError):rs.prepare_stage(p,r['stages'][0]['id'],{},tmp_path/'out')

def test_output_dotdot_and_original_run_preservation(tmp_path):
 p,r=fixture(tmp_path/'inputs')
 with pytest.raises(ValueError):rs.prepare_stage(p,r['stages'][0]['id'],{},tmp_path/'x/../out')
 assert not (tmp_path/'out').exists()

def test_explicit_predecessor_required_and_other_hypothesis_rejected(tmp_path):
 p,r=fixture(tmp_path/'inputs');cfg=Path(r['stages'][1]['documents'][0]['source']['path']);d=read_json(cfg)
 r['stages'][1]['links']=[{'document':'native_input','pointer':'/database','from_stage':r['stages'][0]['id'],'export':'result'}];write(p,r)
 with pytest.raises(ValueError,match='another physical'):rs.assess(p)
 # Same hypothesis requires actual accepted custody, never substitute commands.
 r['stages'][1]['hypothesis']='H0';r['pairs'][1]['stages']=[];r['pairs'][0]['stages'].append(r['stages'][1]['id']);write(p,r)
 with pytest.raises(ValueError,match='predecessor'):rs.prepare_stage(p,r['stages'][1]['id'],{},tmp_path/'out')

class Control:
 def __init__(self):self.calls=[]
 def cancelled(self):return False
 def check_cancelled(self):pass
 def call(self,label,kind,request,function,output_tokens=0):self.calls.append(label);return function()
def host_request(paths,action='resonance-assess',parameters=None,role='designer'):
 inputs=[{'id':str(i),**pin(p)} for i,p in enumerate(paths)];node={'id':'resonance','kind':'tool','role':role,'depends_on':[],'inputs':inputs,'packet':None,'action':action,'parameters':parameters or {'request_input':'0'},'max_attempts':1}
 req={'schema_version':1,'graph_id':'source-control','graph_revision':'a'*64,'node_id':'resonance','generation':1,'node_sha256':execution.digest(node),'request_id':'b'*64,'input_artifacts':deepcopy(inputs),'packet':None,'dependencies':[]};return node,req

def test_actual_host_requires_whole_graph_census_and_blocks_blind_role(tmp_path):
 p,r=fixture(tmp_path/'inputs');c=Control();n,req=host_request([p])
 with pytest.raises(agent_host.HostFailure,match='custody'):agent_host.AgentHost().execute(n,req,c)
 assert not c.calls
 deps=[Path(x['path']) for x in rs.input_pins(p) if Path(x['path'])!=p];n,req=host_request([p,*deps]);result=agent_host.AgentHost().execute(n,req,c)
 assert result['value']['kind']=='whole-resonance-recipe' and len(c.calls)==1
 n,req=host_request([p,*deps],role='skeptical_verifier')
 with pytest.raises(agent_host.HostFailure):agent_host.AgentHost().execute(n,req,Control())

def test_real_host_prepares_original_adapter_not_mirrored_result(tmp_path):
 p,r=fixture(tmp_path/'inputs');choice=tmp_path/'choice.json';write(choice,{'stage_id':r['stages'][0]['id'],'runs':{}})
 deps=[Path(x['path']) for x in rs.preparation_pins(p,r['stages'][0]['id'],{}) if Path(x['path'])!=p];paths=[p,choice,*deps]
 n,req=host_request(paths,'resonance-prepare',{'request_input':'0','selection_input':'1','output_dir':str(tmp_path/'prepared')})
 value=agent_host.AgentHost(bound_roots=[tmp_path]).execute(n,req,Control())['value']
 assert read_json(value['specification']['path'])['mode']=='contur-import'
 assert not value['execution_authorized']

def test_real_graph_and_central_cli_source_route(tmp_path,capsys):
 from ravel import cli
 p,r=fixture(tmp_path/'inputs');deps=[Path(x['path']) for x in rs.input_pins(p) if Path(x['path'])!=p]
 n,_=host_request([p,*deps]);graph={'schema_version':1,'graph_id':'real_source_resonance','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':10000,'max_wall_seconds':20,'max_reworks':0},'nodes':[n]}
 root=tmp_path/'graph';agent_graph.create(root,graph);status=agent_graph.execute(root,agent_host.AgentHost(),workers=1)
 assert status['complete'] and status['usage']['calls']==1
 # Actual parser includes the explicitly attributed reviewed tuple repair.
 assert cli.parser().parse_args(['resonance-study']).command=='resonance-study'
 assert cli.main(['resonance-study','assess','--request',str(p)])==0
 assert 'whole-resonance-recipe' in capsys.readouterr().out

def mocked_returned_run(tmp_path,request,recipe,monkeypatch,stage_index=0,state='succeeded',review_state='accepted'):
 stage=recipe['stages'][stage_index];prepared=rs.prepare_stage(request,stage['id'],{},tmp_path/'prepared')
 spec=read_json(prepared['specification']['path']);rd=tmp_path/'run'
 science.plan(rd,prepared['specification']['path']);(rd/'outputs/attempt-1').mkdir(parents=True);write(rd/'outputs/attempt-1/result.json',{'status':'passed','source_limit':2.5,'all_regions':['SR','CR'],'limitation':'Synthetic supplied returned-format fixture, not execution or a physical exclusion.'})
 source=read_json(stage['documents'][0]['source']['path'])['database']['path']
 (rd/'outputs/attempt-1/returned.sqlite').write_bytes(Path(source).read_bytes())
 monkeypatch.setattr(science,'verify_plan',lambda *a,**k:None)
 monkeypatch.setattr(science,'execution_spec',lambda target:read_json(Path(target)/science.SPEC))
 monkeypatch.setattr(science,'packet',lambda *a,**k:{'errors':[],'execution':{'status':state}})
 monkeypatch.setattr(science,'_selected',lambda *a,**k:({'outputs':['outputs/attempt-1']},None,None))
 monkeypatch.setattr(rs.physics_review,'status',lambda *a,**k:{'state':review_state,'claim_scope':'diagnostic','live_errors':[]})
 monkeypatch.setattr(rs.physics_review,'snapshot',lambda *a,**k:{'explicit_synthetic_returned_format_admission':True})
 monkeypatch.setattr(rs.physics_review,'validate_snapshot',lambda *a,**k:[])
 return rd

def test_actual_handoff_injects_authenticated_returned_bytes(tmp_path,monkeypatch):
 p,r=fixture(tmp_path/'inputs')
 # Same physical hypothesis; separate later study consumes exact earlier raw DB.
 downstream=deepcopy(r['stages'][0]);downstream['id']='later_constraint';downstream['links']=[{'document':'native_input','pointer':'/database','from_stage':r['stages'][0]['id'],'export':'database'}]
 r['stages'][0]['exports']['database']='returned.sqlite';r['stages'].insert(1,downstream);r['pairs'][0]['stages'].append('later_constraint');write(p,r)
 rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch)
 out=rs.prepare_stage(p,'later_constraint',{r['stages'][0]['id']:str(rd)},tmp_path/'linked')
 doc=read_json(tmp_path/'linked/native_input.json')
 assert doc['database']==pin(rd/'outputs/attempt-1/returned.sqlite')
 assert out['accepted_predecessors'][0]['exports']['database']==doc['database']
 # Generated commands and late changed returned bytes cannot be substituted.
 (rd/'outputs/attempt-1/returned.sqlite').write_bytes(b'changed')
 with pytest.raises(ValueError):rs.handoff_inputs(read_json(out['specification']['path']),tmp_path/'linked')

@pytest.mark.parametrize('state,review_state',[('failed','accepted'),('succeeded','scientific_hold'),('succeeded','open')])
def test_failures_unreviewed_and_held_keep_full_denominator_and_outputs(tmp_path,monkeypatch,state,review_state):
 p,r=fixture(tmp_path/'inputs');r['stages'][0]['quantities']=[{'id':'limit','pointer':'/source_limit','unit':'pb','meaning':'Synthetic returned numeric field; no physical unit validation.'}];write(p,r)
 rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch,state=state,review_state=review_state)
 result=rs.collect(p,{r['stages'][0]['id']:str(rd)},tmp_path/'report')
 row=result['stages'][0];assert row['result']['source_limit']==2.5 and len(row['full_output_inventory'])==2
 assert row['state'] in ('failed','unreviewed_or_held') and result['pairs'][0]['state']=='incomplete'
 assert '2.5' in (tmp_path/'report/REPORT.md').read_text() and 'pb' in (tmp_path/'report/REPORT.md').read_text()
 assert result['cross_search_combination'] is None and not result['parent_task_accepted']

def test_accepted_separate_quantity_is_reported_without_combining_or_closing_parent(tmp_path,monkeypatch):
 p,r=fixture(tmp_path/'inputs');r['stages'][0]['quantities']=[{'id':'limit','pointer':'/source_limit','unit':'pb','meaning':'Synthetic returned scalar only.'}];write(p,r)
 rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch)
 result=rs.collect(p,{r['stages'][0]['id']:str(rd)},tmp_path/'report')
 assert result['pairs'][0]['state']=='accepted_scoped_deliveries' and result['pairs'][1]['state']=='incomplete'
 assert result['stages'][0]['result']['all_regions']==['SR','CR']
 assert not result['parent_completion']['ready_for_parent_review']

def test_ending_review_hold_and_output_census_refuse(tmp_path,monkeypatch):
 p,r=fixture(tmp_path/'inputs');rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch);original=rs._write
 def late(out,name,value,capture):
  pinned=original(out,name,value,capture)
  if name=='report.json':(rd/'outputs/attempt-1/unbound.json').write_text('{}')
  return pinned
 monkeypatch.setattr(rs,'_write',late)
 with pytest.raises(ValueError,match='membership'):rs.collect(p,{r['stages'][0]['id']:str(rd)},tmp_path/'report')

def test_unknown_published_domain_is_preserved_and_blocks_preparation(tmp_path):
 p,r=fixture(tmp_path/'inputs');r['searches'][0]['applicability']['mass_gev']=None;r['searches'][0]['applicability']['width_over_mass']=None
 for pair in r['pairs']:
  mp=Path(pair['mapping']['path']);m=read_json(mp);m['search_sha256']=rs._digest(r['searches'][0]);pair['mapping']=write(mp,m)
 write(p,r);a=rs.assess(p)
 assert all('mass domain not supplied' in x['blockers'] and 'width domain not supplied' in x['blockers'] for x in a['pairs'])
 with pytest.raises(ValueError,match='blockers'):rs.prepare_stage(p,r['stages'][0]['id'],{},tmp_path/'out')

def test_accepted_failed_diagnostic_keeps_failed_return_without_constraint_claim(tmp_path,monkeypatch):
 p,r=fixture(tmp_path/'inputs')
 r['stages'][0]['quantities']=[{'id':'limit','pointer':'/source_limit','unit':'pb','meaning':'Declared returned scalar, unavailable in this diagnostic.'}]
 write(p,r);rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch);write(rd/'outputs/attempt-1/result.json',{'status':'failed','source_limit':None,'reason':'Synthetic failure retained.'})
 value=rs.collect(p,{r['stages'][0]['id']:str(rd)},tmp_path/'report')
 assert value['pairs'][0]['state']=='accepted_scoped_deliveries'
 exposed=json.loads(value['pairs'][0]['constraint_states'])[0]
 assert exposed['result_status']=='failed' and exposed['quantities'][0]['availability']=='source_null'
 assert not value['physics_validated'] and not value['parent_task_accepted']


"""Actual source compiler connection, explicitly artificial counts/coefficients."""
import json
from ravel.workflow import resonance_study as rs
from ravel.physics import statistical_construction as sc

def law(base):
 source=put(base/'law.txt','Artificial full mean b + c*I + c^2*S; no measurement or event sample.\n')
 d={'schema_version':1,'model_id':'resonance','question':'Source construction of a signed resonance and complete controls.',
 'sources':[{'id':'s',**source}],
 'parameters':[{'name':'c','role':'poi','initial':'0','bounds':['-2','2'],'fixed':False,'meaning':'Supplied amplitude coordinate','source':'s'}],
 'bins':[{'id':b,'role':r,'observed':n,'observation_id':'artificial/'+b,'source':'s'} for b,r,n in [('SR','signal_region',10),('CR','control_region',5)]],
 'terms':[{'id':name,'basis':basis,'coefficients':values,'powers':powers,'log_response':[[],[]],'source':'s'} for name,basis,values,powers in [('background','background',['10','5'],{}),('signed','interference',['-3','1'],{'c':1}),('square','bsm',['2','1'],{'c':2})]],
 'auxiliary':{'kind':'supplied_gaussian_factor','names':[],'observed':[],'factor':[],'eta_bounds':[],'source':'s'},
 'partition':{'kind':'declared_disjoint_poisson_counts','source':'s','statement':'Artificial disjoint SR and CR counts.'},
 'prediction':{'units':'expected_events','energy':'13 TeV artificial source','luminosity':'already normalized artificial counts','basis':'supplied amplitude c and full interference','scale':'declared artificial tree scheme','domain_statement':'Positive total means on declared c box; no physical applicability proof.','source':'s'},
 'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Fixed artificial coefficients; no finite-MC law invented.','source':'s'},
 'assumptions':[{'id':'premise','statement':'Artificial full law only; runtime and inference unqualified.','source':'s','status':'assumed'}]}
 return write(base/'law.json',d),d

def test_existing_signed_total_mean_to_native_bundle(tmp_path):
 p,d=law(tmp_path/'source');value=rs.construct_regional(p,{}, {'method':'MultiDimFit','data':'observed'},tmp_path/'bundle',base_dir=tmp_path,max_seconds=30)
 assert not value['build_or_fit_executed'] and not value['native_parity_qualified']
 out=json.loads((tmp_path/'bundle/native-input.json').read_text())
 assert out['model']['regions']==[{'channel':'SR','role':'signal_region'},{'channel':'CR','role':'control_region'}]
 assert sc.mean_jet(d,{'c':'1'})['means']==[9,7]
 assert sc.mean_jet(d,{'c':'1'})['term_values'][0]==[10,-3,2]
 assert out['model']['construction']==value['construction']

def test_ending_constructed_handoff_mismatch_refuses(tmp_path,monkeypatch):
 import pytest
 p,d=law(tmp_path/'source');original=sc.write_native_bundle
 def drift(*a,**k):
  result=original(*a,**k);q=tmp_path/'bundle/handoff.json';raw=json.loads(q.read_text());raw['build_or_fit_executed']=True;q.write_text(json.dumps(raw));return result
 monkeypatch.setattr(sc,'write_native_bundle',drift)
 with pytest.raises(ValueError,match='handoff changed'):rs.construct_regional(p,{}, {'method':'MultiDimFit','data':'observed'},tmp_path/'bundle',base_dir=tmp_path,max_seconds=30)

"""Existing published-summary operation connection; artificial source curves only."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
from ravel.physics import published_summary as operation
from ravel.workflow import resonance_study as rs,science
def curve_fixture(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('FABRICATED source. No measured limit or experimental acceptance.')
    survey = {'schema_version': 1, 'survey_target': 'fabricated', 'candidates': [
        {'id': 'A', 'experiment': 'ATLAS', 'final_state': 'l-nu-qq',
         'mass_range_gev': [250, 1000], 'provenance': 'digitized',
         'disposition': {'state': 'plotted', 'reason': 'fabricated in-window', 'reviewer': 'synthetic'}},
        {'id': 'B', 'experiment': 'CMS', 'final_state': 'l-nu-qq',
         'mass_range_gev': [600, 1000], 'provenance': 'digitized',
         'disposition': {'state': 'excluded', 'reason_class': 'out-of-range',
                         'reason': 'above window', 'reviewer': 'synthetic'}}]}
    manifest = {'schema_version': 1, 'window_gev': [150, 500],
        'target_basis': {'quantity': '95% CL UL [pb]', 'model': 'Synthetic hypothesis', 'sqrt_s': '13 TeV'},
        'curves': [{'survey_id': 'A', 'source': 'A l-nu-qq', 'draw': 'primary', 'provenance': 'digitized',
                    'lumi_fb': 1, 'native_basis': 'digitized fabricated pb', 'transformation': 'IDENTITY',
                    'identity_check': 'NONE', 'resolved': {'mass_gev': [250, 300, 450, 500, 1000],
                        'obs': [8, 4, 1, .8, .1], 'exp': [None, 3, None, .7, .2],
                        'theory': [None, None, None, None, .15], 'theory_label': 'out-of-window'}}],
        'coverage_gaps': [{'lo_gev': 150, 'hi_gev': 250, 'note': 'No retained curve in supplied census'}]}
    contract = {'schema_version': 1, 'kind': 'published-limit-summary/v1',
        'survey': write(tmp_path / 'survey.json', survey),
        'manifest': write(tmp_path / 'manifest.json', manifest),
        'source_assets': {'source': pin(source)}, 'candidate_sources': [
            {'survey_id': c['id'], 'mass_range_gev': list(c['mass_range_gev']), 'source_ids': ['source'], 'energy_tev':13}
            for c in survey['candidates']],
        'resolved_series_sha256': {'A': operation.digest(manifest['curves'][0]['resolved'])},
        'window': {'lo_gev': 150, 'hi_gev': 500, 'upper_inclusive': False},
        'energy_tev':13,
        'census_scope': 'Fabricated bounded census; current completeness unknown.',
        'precision_scope': 'Fabricated source-only controls, no physics.'}
    return survey, manifest, contract

def mapped_summary(base):
 p,r=fixture(base/'inputs');curve=base/'curve';curve.mkdir()
 _,manifest,contract=curve_fixture(curve)
 h,s=r['hypotheses'][0],r['searches'][0]
 # Source-only confidence curves now say exactly what their pair declares;
 # the original pb/other-model positive remains immutable in the V1 package.
 manifest['target_basis']['quantity']='source exclusion confidence [1]'
 manifest['target_basis']['model']=h['interpretation']
 row=manifest['curves'][0];row['native_basis']='digitized FABRICATED source confidence [1]'
 for key in ('obs','exp','theory'):
  row['resolved'][key]=[None if x is None else x/10 for x in row['resolved'][key]]
 contract['manifest']=write(curve/'manifest.json',manifest)
 contract['resolved_series_sha256']['A']=operation.digest(row['resolved'])
 cp=write(curve/'contract.json',contract)
 original=r['stages'][0];stage=deepcopy(original);stage['id']='published_plot';stage['role']='summary'
 spec=json.loads(Path(original['study']['path']).read_text());spec['mode']='published-summary'
 spec['task']={'schema_version':1,'input':cp['path'],'input_sha256':cp['sha256']}
 stage['study']=write(curve/'study.json',spec)
 stage['documents']=[{'id':'curve_input','task_key':'input','source':cp}]
 from ravel.physics.ma5_pad import InputCapture
 capture=InputCapture();projection=rs._summary_target(spec,curve,capture);capture.finish()
 mapping={'schema_version':1,'original_study':stage['study'],
  'hypothesis_sha256':rs._digest(h),'search_sha256':rs._digest(s),
  'projected_target':projection,'correspondence':{'model':h['interpretation'],
  'observable':s['observable'],'basis':h['basis'],
  'meaning':'Located artificial source confidence [1] with the same declared model at13TeV; no numerical transformation/model qualification.'},
  'sources':[h['model'],s['source'],contract['source_assets']['source']], 'limitations':[]}
 stage['target_mapping']=write(curve/'target-map.json',mapping)
 r['stages'].append(stage);r['pairs'][0]['stages'].append(stage['id']);write(p,r)
 return p,r,stage,contract,mapping

def test_actual_summary_preparation_preserves_labels_and_rebinds_copied_input_digest(tmp_path):
 p,r,stage,_,_=mapped_summary(tmp_path)
 a=rs.assess(p);target=a['pairs'][0]['stage_targets'][-1]
 assert target['semantic_status']=='located_correspondence_premise'
 assert target['projection']['targets'][0]['energy_tev']==13
 assert target['projection']['targets'][0]['quantity_unit'] is None
 value=rs.prepare_stage(p,stage['id'],{},tmp_path/'prepared')
 spec=json.loads(Path(value['specification']['path']).read_text())
 cp=stage['documents'][0]['source']
 assert spec['task']['input_sha256']==pin(tmp_path/'prepared/curve_input.json')['sha256']
 assert spec['task']['input_sha256']!=cp['sha256']
 paths=science.task_inputs(spec,tmp_path/'prepared');assert tmp_path/'prepared/curve_input.json' in paths
 assert Path(stage['target_mapping']['path']) in paths
 science.plan(tmp_path/'planned',value['specification']['path']);science.verify_plan(tmp_path/'planned',approved=False)
 assert not (tmp_path/'planned'/science.APPROVAL).exists()

"""Narrow scientific-source controls; no models or numerical engines run."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import resonance_study as rs

def repin(recipe):
 for pair in recipe['pairs']:
  h=next(h for h in recipe['hypotheses'] if h['id']==pair['hypothesis'])
  s=next(s for s in recipe['searches'] if s['id']==pair['search'])
  p=Path(pair['mapping']['path']);m=json.loads(p.read_bytes())
  m['hypothesis_sha256']=rs._digest(h);m['search_sha256']=rs._digest(s)
  pair['mapping']=write(p,m)

@pytest.mark.parametrize('variant',['daughters','rosters','numeric'])
def test_canonical_physical_rival_identity(tmp_path,variant):
 p,r=fixture(tmp_path/'inputs');h=r['hypotheses'][0]
 h['production']=['gg','qq'];h['decays']=[{'products':[6,-6],'branching_ratio':.5},{'products':[22,22],'branching_ratio':.5}]
 h['couplings'].append(dict(h['couplings'][0],name='other'))
 r['hypotheses'][1]=dict(deepcopy(h),id='H1');same=r['hypotheses'][1]
 if variant=='daughters':same['decays'][0]['products'].reverse()
 if variant=='rosters':
  same['production'].reverse();same['decays'].reverse();same['couplings'].reverse()
  for d in same['decays']:d['products'].reverse()
 if variant=='numeric':
  same['mass_gev']=400;same['width_gev']=20;same['energy_tev']=13
  same['couplings'][0]['real']=1;same['couplings'][0]['imag']=-0.0
 repin(r);write(p,r)
 with pytest.raises(ValueError,match='physically distinct'):rs.assess(p)

def test_signed_pdg_multiplicity_and_exact_numeric_difference_remain_distinct(tmp_path):
 p,r=fixture(tmp_path/'inputs');h=r['hypotheses'][0]
 h['decays']=[{'products':[22,22],'branching_ratio':1.}]
 r['hypotheses'][1]=dict(deepcopy(h),id='H1')
 r['hypotheses'][1]['decays'][0]['products']=[22,-22]
 repin(r);write(p,r);assert len(rs.assess(p)['hypotheses'])==2
 # A single representable increment is not rounded into the same hypothesis.
 h2=deepcopy(h);h2['mass_gev']=400.00000000000006
 assert rs._physics(h2)!=rs._physics(h)

@pytest.mark.parametrize('variant',['missing','original_study','energy','model','quantity','basis','sources'])
def test_summary_target_mapping_and_actual_fields_refuse(tmp_path,variant):
 p,r,stage,contract,m=mapped_summary(tmp_path)
 if variant=='missing':stage.pop('target_mapping');r['stages'][-1]=stage
 elif variant=='original_study':m['original_study']['sha256']='a'*64
 elif variant in ('model','quantity'):
  manifest_path=Path(contract['manifest']['path']);manifest=json.loads(manifest_path.read_bytes())
  manifest['target_basis'][variant]='Another actual '+variant
  contract['manifest']=write(manifest_path,manifest)
  cp=write(Path(stage['documents'][0]['source']['path']),contract)
  stage['documents'][0]['source']=cp
  sp=Path(stage['study']['path']);spec=json.loads(sp.read_bytes());spec['task']['input_sha256']=cp['sha256']
  stage['study']=write(sp,spec);r['stages'][-1]=stage
  m['original_study']=stage['study']
 elif variant=='energy':m['projected_target']['targets'][0]['energy_tev']=8
 elif variant=='basis':m['correspondence']['basis']='bsm'
 elif variant=='sources':m['sources'][0]['sha256']='a'*64
 if variant!='missing':stage['target_mapping']=write(Path(stage['target_mapping']['path']),m);r['stages'][-1]=stage
 write(p,r);out=tmp_path/'prepared'
 with pytest.raises(ValueError):rs.prepare_stage(p,stage['id'],{},out)
 assert not out.exists()

def test_target_source_ending_mutation_refuses_not_recaptured(tmp_path,monkeypatch):
 p,r,stage,_,_=mapped_summary(tmp_path);original=rs._write
 def mutate(out,name,value,capture):
  result=original(out,name,value,capture)
  if name=='preparation.json':Path(stage['target_mapping']['path']).write_text('{}')
  return result
 monkeypatch.setattr(rs,'_write',mutate)
 with pytest.raises(ValueError):rs.prepare_stage(p,stage['id'],{},tmp_path/'prepared')

def test_unprojected_mode_is_explicit_in_whole_report(tmp_path):
 p,r=fixture(tmp_path/'inputs');result=rs.collect(p,{},tmp_path/'report')
 state=json.loads(result['pairs'][0]['stage_targets'])[0]
 assert state['projection'] is None and state['semantic_status']=='unprojected_source_premise'
 assert 'unprojected_source_premise' in (tmp_path/'report/REPORT.md').read_text()
 assert not result['physics_validated']

def test_effective_predecessor_cannot_retarget_mapped_summary(tmp_path,monkeypatch):
 p,r,stage,contract,_=mapped_summary(tmp_path)
 previous=r['stages'][0];previous['exports']['manifest']='retargeted-manifest.json'
 stage['links']=[{'document':'curve_input','pointer':'/manifest','from_stage':previous['id'],'export':'manifest'}]
 r['stages'][0]=previous;r['stages'][-1]=stage;write(p,r)
 rd=mocked_returned_run(tmp_path/'returned',p,r,monkeypatch)
 manifest=json.loads(Path(contract['manifest']['path']).read_bytes())
 manifest['target_basis']['model']='Other returned model at the SAME energy'
 write(rd/'outputs/attempt-1/retargeted-manifest.json',manifest)
 out=tmp_path/'linked'
 with pytest.raises(ValueError,match='changed the mapped actual study target'):
  rs.prepare_stage(p,stage['id'],{previous['id']:str(rd)},out)
 assert not out.exists()

def test_requested_summary_projects_all_panels_from_captured_bytes(tmp_path):
 from ravel.physics.ma5_pad import InputCapture
 for identity,energy in [('first',13),('second',8)]:
  base=tmp_path/identity;base.mkdir();_,manifest,contract=curve_fixture(base)
  contract['energy_tev']=energy;manifest['target_basis']['sqrt_s']=str(energy)+' TeV'
  for candidate in contract['candidate_sources']:candidate['energy_tev']=energy
  contract['manifest']=write(base/'manifest.json',manifest);write(base/'contract.json',contract)
 cp=write(tmp_path/'requested.json',{'schema_version':2,'kind':'requested-published-summary/v2',
  'panels':[{'id':identity,'summary':pin(tmp_path/identity/'contract.json')} for identity in ('first','second')]})
 spec={'mode':'published-summary','task':{'schema_version':2,'input':cp['path'],'input_sha256':cp['sha256']}}
 capture=InputCapture();projection=rs._summary_target(spec,tmp_path,capture);capture.finish()
 assert [(t['panel_id'],t['energy_tev']) for t in projection['targets']]==[('first',13),('second',8)]
 assert all(t['quantity_unit'] is None and t['prediction_basis'] is None for t in projection['targets'])
 # This tests classification only; full requested-summary adapter intake still
 # requires original parent/figure/census/runtime contracts, never this skeleton.diff --git a/docs/guides/resonance-study.md b/docs/guides/resonance-study.md
