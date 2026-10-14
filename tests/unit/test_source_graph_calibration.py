"""Actual original loop and ordinary APIs with inert native boundaries only."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib,json,math,random,pytest,ast
from ravel.physics import source_graph_calibration as s,regional_calibration as c,regional_expected as e
from ravel.physics import native_statistical_construction as g,native_likelihood as n,combine_derivatives as cd,full_auxiliary_calibration as a
from ravel.workflow import science
from test_source_graph_coverage import recipe,rebind,fake_graph,graph_probe
from source_graph_coverage_fixture import Collection

def calibration_recipe(tmp_path,monkeypatch,population=False):
 monkeypatch.setattr(n.platform,'platform',lambda:'inert supplied source host')
 d=recipe(tmp_path,monkeypatch,population=population,expected=False)
 for cell in d['cells']:
  cell['fit']['saved_fit']['maximum_edm']=.00001
  point={p['name']:p['initial']for p in cell['law']['parameters']+cell['parameters']};point.update({'slope':'1/2','ravel_aux_0':'1/4','ravel_aux_1':'-1/4'})
  cell['calibration']={'kind':s.KIND,'estimand':c.ESTIMAND,'source':'s','statement':'Synthetic complete native-model experiment; inert test, no physical generating-law claim',
   'truths':[{'id':'truth1','point':point}],'trials_per_truth':2,'auxiliary_mode':'unconditional','seed':17,'critical_q':'384/100','confidence_level':'95/100','numerical_margin':'1/1000000',
   'nll_absolute_tolerance':'1/100000','nll_relative_tolerance':'1/1000000','reservation_seconds_per_toy':1,'maximum_unresolved_fraction':'0',
   'native_readback_budget':{'max_snapshots':7,'max_integral_reads':7*14},'count_sampler':{'kind':s.SAMPLER,'max_state_bytes':s.MAX_STATE_BYTES}}
 for stem in ('libMathCore','libRIO'):
  path=tmp_path/(stem+'.so');path.write_bytes(b'Explicit inert runtime API placeholder, never loaded');d['runtime']['artifacts'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 d['runtime']['expected']['custom_classes']+=['TRandom3','TBufferJSON'];rebind(d,tmp_path);return d

def façade(tmp_path,response,large=False,fail_profile=False):
 root,w,mc,data,*_=fake_graph(tmp_path,response);d=response['document'];cell=s.cell(response)
 names=[p['name']for p in d['parameters']]+['ravel_aux_'+str(i)for i in range(len(d['auxiliary']['names']))]+['ravel_aux_'+str(i)+'_In'for i in range(len(d['auxiliary']['names']))]+[o['name']for o in cell['observables']]+['n_obs_bin'+b['id']for b in d['bins']]
 vars_=[w.var(name)for name in names];w.allVars=lambda:vars_;w.allCats=lambda:[];w.cat=lambda name:None
 for i in range(len(d['auxiliary']['names'])):
  v=w.var('ravel_aux_'+str(i)+'_In');v.lo=-float('inf');v.hi=float('inf')
 for o in cell['observables']:w.var(o['name']).setVal(float(F(o['bounds'][0]))/2+float(F(o['bounds'][1]))/2)
 for b in d['bins']:w.var('n_obs_bin'+b['id']).hi=1e9
 functions={};old_function=w.function
 for j,t in enumerate(cell['components']):
  for k,b in enumerate(d['bins']):
   integral=old_function('ravel_graph_int_'+str(j)+'_'+str(k));integral.getVal=lambda j=j,k=k:(2.+j+k/4)*(1+w.var('slope').getVal()/4)
   functions['ravel_graph_term_'+str(j)+'_'+str(k)]=NS(getVal=lambda j=j,k=k:contribution(j,k))
 def point():return {name:w.var(name).getVal()for name in response['coordinates']}
 def contribution(j,k):
  t=cell['components'][j];p=point();aux=d['auxiliary'];physical=[float(F(aux['observed'][i]))+sum(float(F(v))*p['ravel_aux_'+str(l)]for l,v in enumerate(aux['factor'][i]))for i in range(len(aux['names']))]
  den=old_function('ravel_graph_den_'+str(j)).getVal()if t['normalization']=='full_domain'else 1
  return float(F(t['coefficients'][k]))*math.prod(p[name]**power for name,power in t['powers'].items())*math.exp(sum(float(F(v))*x for v,x in zip(t['log_response'][k],physical)))*old_function('ravel_graph_int_'+str(j)+'_'+str(k)).getVal()/den
 def base(i):return (2000. if large and i in(0,2)else 30.+i)+w.var('beta').getVal()/5
 def total(i):return base(i)+math.fsum(contribution(j,i)for j in range(len(cell['components'])))
 for i,b in enumerate(d['bins']):
  functions['ravel_base_mean_'+str(i)]=NS(getVal=lambda i=i:base(i));functions['ravel_mean_'+str(i)]=NS(getVal=lambda i=i:total(i))
 w.function=lambda name:functions.get(name)or old_function(name)
 class NLL:
  def getVal(self):return s.mean_nll(point(),{'counts':{b['id']:int(v)for b,v in zip(d['bins'],data.rows[0])},'globals':{f'ravel_aux_{i}_In':w.var(f'ravel_aux_{i}_In').getVal()for i in range(len(d['auxiliary']['names']))}},{b['id']:total(i)for i,b in enumerate(d['bins'])},len(d['auxiliary']['names']))+37.25
 class PDF:
  def GetName(self):return 'model_s'
  def ClassName(self):return 'RooProdPdf'
  def getStringAttribute(self,key):return None
  def createNLL(self,*args):return NLL()
 mc.GetName=lambda:'ModelConfig';mc.GetPdf=lambda:PDF();mc.GetParametersOfInterest=lambda:Collection([w.var('c')]);mc.GetNuisanceParameters=lambda:Collection([w.var(name)for name in response['coordinates']if name!='c'and not w.var(name).isConstant()]);mc.GetGlobalObservables=lambda:Collection([w.var(f'ravel_aux_{i}_In')for i in range(len(d['auxiliary']['names']))]);mc.GetConditionalObservables=lambda:Collection()
 class Mini:
  def __init__(self,nll):self.nll=nll
  def setErrorLevel(self,x):assert x==.5
  def setStrategy(self,x):assert x==1
  def setEps(self,x):assert x==.00001
  def setMaxFunctionCalls(self,x):assert x==50000
  def setMaxIterations(self,x):assert x==10000
  def minimize(self,*args):
   if fail_profile:raise ValueError('retained inert profile refusal')
   return 0
  def hesse(self):return 0
  def save(self):
   floats=Collection([w.var(name)for name in response['coordinates']if not w.var(name).isConstant()]);const=Collection([w.var(name)for name in response['coordinates']if w.var(name).isConstant()]);size=len(floats)
   return NS(status=lambda:0,covQual=lambda:3,edm=lambda:1e-6,minNll=self.nll.getVal,numInvalidNLL=lambda:0,numStatusHistory=lambda:2,statusLabelHistory=lambda i:['Migrad','Hesse'][i],statusCodeHistory=lambda i:0,floatParsFinal=lambda:floats,constPars=lambda:const,covarianceMatrix=lambda:[[.01 if i==j else 0. for j in range(size)]for i in range(size)])
 class File:
  def __init__(self,path):self.path=Path(path)
  def WriteTObject(self,obj,name):self.path.write_bytes(b'inert result, no ROOT/optimization')
  def Close(self):pass
 class Linked(list):
  def Add(self,x):self.append(x)
 class NativeRNG:
  def __init__(self,seed):self.seed=seed;self.position=0;self.means=[]
  def PoissonD(self,mu):self.means.append(mu);self.position+=1;return float(int(mu)) # explicit deterministic facade, NOT sampler validation
 root.RooMinimizer=Mini;root.TFile=NS(Open=lambda path,*args:File(path));root.RooLinkedList=Linked;root.RooFit=NS(Constrain=lambda v:('constraints',v),GlobalObservables=lambda v:('globals',v));root.TRandom3=NativeRNG
 root.TBufferJSON=NS(ConvertToJSON=lambda rng,compact:json.dumps({'_typename':'TRandom3','fMt':[rng.seed]*624,'fCount624':rng.position}))
 return root,w,mc,data

def delivery(tmp_path,monkeypatch,*,large=False,fail_profile=False,budget=None):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');request=d['cells'][0]['calibration']
 if budget is not None:request['native_readback_budget']['max_snapshots']=budget
 root,w,mc,data=façade(tmp_path,response,large,fail_profile);law=s.GraphLaw(root,w,mc,response,request,e,c,cd)
 result=c.execute(root,w,mc,data,response,request,e,tmp_path/'journal.json',20.,_graph_law=law)
 return d,response,request,result,(root,w,mc,data)

@pytest.mark.parametrize('large',[False,True])
def test_original_loop_complete_native_truth_profiles_resets_and_whole_large_rng_states(tmp_path,monkeypatch,large):
 d,response,request,result,_=delivery(tmp_path,monkeypatch,large=large);s.validate_delivery(result,response,request,e,c)
 assert all(row['status']=='included' and row['raw_q']==0 for row in result['rows'])
 assert result['top_level_profile_requests']==4 and result['native_readback_cost']['returned_snapshots']==7
 assert result['initial_native_state']==result['final_native_state'] and result['native_truth_admission'][0]['snapshot']['point']['slope']=='1/2'
 for snapshot in result['native_readback_cost']['snapshots']:g.integration_witness(snapshot['integrals'],response)
 assert all(len(row['native_sampler']['draws'])==(2 if large else 0)for row in result['rows'])
 assert len(list(tmp_path.glob('ravel_calibration_rng_*')))==(8 if large else 0)
 for row in result['rows']:
  for draw in row['native_sampler']['draws']:
   assert draw['internal_proposals']is None and draw['status']=='checked'
   for phase in ('before','after'):s.validate_rng_bytes((tmp_path/draw[phase]['basename']).read_bytes())
 assert result['coverage_qualified']is result['numerical_equivalence_qualified']is False

@pytest.fixture(scope='module')
def retained_native_receipt(tmp_path_factory):
 with pytest.MonkeyPatch.context()as monkeypatch:
  _,response,request,result,_=delivery(tmp_path_factory.mktemp('one_complete_native_model_receipt'),monkeypatch,large=True)
 return response,request,result

@pytest.mark.parametrize('mutation',[
 lambda r:r['native_truth_admission'].pop(),lambda r:r['native_readback_cost']['snapshots'].pop(),
 lambda r:r['rows'][0]['source_graph_truth_readback']['point'].update(slope='0'),lambda r:r['native_readback_cost'].update(reserved_snapshots=6),
 lambda r:r['rows'][0].update(native_mean_q=99),lambda r:r['rows'][0]['observation']['counts'].pop('D'),lambda r:r.update(numerical_equivalence_qualified=True),
 lambda r:r['rows'][0]['native_sampler']['draws'].pop(),lambda r:r['rows'][0]['native_sampler']['draws'][0].update(return_=0),
 lambda r:r.update(native_sampler_state_bytes=0),lambda r:r.update(final_native_state={}),lambda r:r['rows'].pop(),
])
def test_full_delivery_refuses_omissions_changed_state_rawq_and_false_certification(retained_native_receipt,mutation):
 response,request,raw=retained_native_receipt;result=deepcopy(raw);mutation(result)
 with pytest.raises((ValueError,KeyError)):s.validate_delivery(result,response,request,e,c)

@pytest.mark.parametrize('budget,fail,expected_status',[(1,False,'unissued'),(7,True,'unresolved')])
def test_whole_toy_reservation_precedes_draws_and_failed_profiles_retain_full_denominator(tmp_path,monkeypatch,budget,fail,expected_status):
 _,response,request,result,_=delivery(tmp_path,monkeypatch,budget=budget,fail_profile=fail);s.validate_delivery(result,response,request,e,c)
 assert [r['status']for r in result['rows']]==[expected_status]*2 and result['summary']['cohorts'][0]['identification_interval']==[0.,1.]
 assert result['native_readback_cost']['attempted_snapshots']==(1 if expected_status=='unissued'else 3)
 if fail:assert all(r['error']['message']=='retained inert profile refusal'for r in result['rows'])

def test_original_small_count_rng_sequence_and_gaussian_law_remain_exact(tmp_path,monkeypatch):
 _,response,request,result,_=delivery(tmp_path,monkeypatch)
 for row in result['rows']:
  means=row['observation']['means_at_fixed_truth']
  for name,value in row['observation']['counts'].items():assert value==c.poisson(means[name],random.Random(c.seed_for(request,row['truth_id'],row['ordinal'],'count:'+name)))
  for i in range(2):assert row['observation']['globals'][f'ravel_aux_{i}_In']==float(F(request['truths'][0]['point'][f'ravel_aux_{i}']))+random.Random(c.seed_for(request,row['truth_id'],row['ordinal'],'gaussian:'+str(i))).gauss(0.,1.)

@pytest.mark.parametrize('change',[lambda q:q['truths'][0]['point'].pop('slope'),lambda q:q['truths'][0]['point'].update(kappa='0'),lambda q:q['count_sampler'].update(kind='Gaussian'),lambda q:q.update(reference_budget={})])
def test_closed_full_truth_sampler_domains_and_no_guessed_source_reference(tmp_path,monkeypatch,change):
 d=calibration_recipe(tmp_path,monkeypatch);change(d['cells'][0]['calibration'])
 with pytest.raises((ValueError,KeyError)):g.validate_document(d)

def test_full_scheduled_native_seed_collision_preflight_never_reseeds(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);monkeypatch.setattr(s,'native_seed',lambda*a:1)
 with pytest.raises(ValueError,match='collision'):g.validate_document(d)

def test_sixteen_cells_prepare_ordinary_graph_context_without_any_mean_evaluation(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch,population=True);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));result=g.run({'input':str(p)},tmp_path,tmp_path/'bundle')
 assert len(result['cells'])==16 and result['population']==d['population']
 for row in result['cells']:
  task=row['task'];cp=Path(task['input']);cfg=json.loads(cp.read_bytes());assert row['mode']=='full-auxiliary-calibration' and cfg['calibration']==s.cell(g.response(d,row['id']))['calibration']
  inputs=science.task_inputs({'mode':row['mode'],'task':task,'max_seconds':30},cp.parent)
  assert Path(s.__file__)in inputs and Path(cd.__file__)in inputs
 ast.parse(n.NATIVE_PROBE)

def test_actual_ordinary_native_worker_authenticates_copied_helpers_and_raw_state_files(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));prepared=g.run({'input':str(p)},tmp_path,tmp_path/'bundle');task=prepared['cells'][0]['task'];response=g.response(d,'cell0');calls=[]
 action=next(node for node in ast.walk(ast.parse(n.NATIVE_PROBE))if isinstance(node,ast.If)and '--calibrate' in ast.unparse(node.test)and ast.unparse(node.test).endswith("sys.argv[4] == '--calibrate'"))
 code=compile(ast.fix_missing_locations(ast.Module(body=action.body,type_ignores=[])),'actual_unchanged_worker_calibration_action','exec')
 def process(command,cwd,env,log,deadline,**kwargs):
  calls.append(Path(log).name);work=Path(log).parent.parent/'native-work';name=Path(log).name
  if name=='workspace-build.log':(work/'ravel_workspace.root').write_bytes(b'inert workspace');raw='inert build'
  elif name=='combine-version.log':raw=' <<< Combine >>>\n <<< v9.2.1 >>>\nMissing datacard file\nUsage: combine [options]\n'
  elif name=='workspace-probe.log':raw='RAVEL_NATIVE_PROBE='+json.dumps(graph_probe(response))
  elif name=='native-calibration.log':
   root,w,mc,data=façade(work,response,large=True);cfg=json.loads((work/'ravel_native_configuration.json').read_bytes());result={}
   namespace={'ROOT':root,'w':w,'mc':mc,'data':data,'response':response,'cfg':cfg,'result':result,'sys':NS(argv=command[1:]),'__file__':str(work/'ravel_workspace_probe.py'),'file_hash':lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()}
   exec(code,namespace);raw='RAVEL_NATIVE_PROBE='+json.dumps(result)
  else:raw='RAVEL_NATIVE_PROBE={}'if name=='native-identity.log'else'inert boundary'
  Path(log).write_text(raw);return raw
 monkeypatch.setattr(n,'_process',process);monkeypatch.setattr(n,'_check_probe',lambda*a,**k:None);monkeypatch.setattr(n.platform,'platform',lambda:'inert source host')
 result=a.run(task,Path(task['input']).parent,tmp_path/'attempt')
 assert result['status']=='passed',result
 assert calls.count('native-calibration.log')==1 and 'native-fit.log'not in calls
 assert result['inference']['kind']==s.KIND and result['inference']['delivery']['top_level_profile_requests']==4
 assert len([v for v in result['retained_artifacts']if v['path'].endswith('.json')and 'ravel_calibration_rng_'in v['path']])==8
 plan=json.loads((tmp_path/'attempt/native-command-plan.json').read_bytes());assert plan['fit']is None and plan['calibration_resource_contract']['maximum_explicit_all_scalar_reads']==175
 assert result['physics_validated']is False and result['integration_diagnostics']['convergence']=='unknown'

def test_original_graph_host_context_and_public_plan_keep_native_means_pending(tmp_path,monkeypatch):
 from ravel.workflow import agent_graph as graph
 from ravel.workflow.agent_host import AgentHost
 d=calibration_recipe(tmp_path,monkeypatch);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));prepared=g.run({'input':str(p)},tmp_path,tmp_path/'bundle');task=prepared['cells'][0]['task'];cp=Path(task['input']);tp=tmp_path/'task.json';tp.write_text(json.dumps(task));spec=a.graph(task,cp.parent,{'path':str(tp),'sha256':hashlib.sha256(tp.read_bytes()).hexdigest()})
 rd=tmp_path/'graph';graph.create(rd,spec);assert graph.execute(rd,AgentHost(api_key='unused-inert-tool-only'),workers=1)['complete']
 _,state=graph._load(rd);value=graph._result(rd,state['nodes']['context']['result'])['result']['value']
 assert value['truth_means']['reference']is None and value['scheduled_toys']==2 and value['toys_generated']==value['fits_performed']==0
 source={'schema_version':1,'mode':'full-auxiliary-calibration','question':'Synthetic graph source plan only','task':task,'max_seconds':30}
 from test_science_capability_integration import specification
 source=specification('full-auxiliary-calibration',task);source['max_seconds']=30
 sp=tmp_path/'study.json';sp.write_text(json.dumps(source));rd=tmp_path/'ordinary-plan'
 from ravel import cli
 assert cli.main(['plan','--rundir',str(rd),'--spec',str(sp)])==0;science.verify_plan(rd,approved=False)
 assert not(rd/science.APPROVAL).exists()

@pytest.mark.parametrize('phase',['partial_integral','state_after','domain','unsupported_mean'])
def test_failed_raw_prefix_and_return_retained_without_redraw_or_clipping(tmp_path,monkeypatch,phase):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');q=d['cells'][0]['calibration'];root,w,mc,data=façade(tmp_path,response,large=True)
 calls=[]
 if phase=='partial_integral':
  original=e.source_graph_integrals
  def partial(workspace,compiled,**kwargs):
   if calls:
    fn=w.function('ravel_graph_int_0_1');fn.getVal=lambda:(_ for _ in()).throw(ValueError('later original integral failure'))
   calls.append(1);return original(workspace,compiled,**kwargs)
  monkeypatch.setattr(e,'source_graph_integrals',partial)
 elif phase=='state_after':
  original=root.TBufferJSON.ConvertToJSON
  def serialize(rng,compact):
   calls.append(rng.position)
   if rng.position:raise ValueError('retained after-state persistence failure')
   return original(rng,compact)
  root.TBufferJSON.ConvertToJSON=serialize
 elif phase=='domain':w.var('n_obs_binA').hi=1.
 else:
  w.function('ravel_base_mean_0').getVal=lambda:1e9
  w.function('ravel_mean_0').getVal=lambda:1e9+math.fsum(w.function('ravel_graph_term_'+str(j)+'_0').getVal()for j in range(len(s.cell(response)['components'])))
 law=s.GraphLaw(root,w,mc,response,q,e,c,cd)
 if phase=='unsupported_mean':
  with pytest.raises(ValueError,match='scope'):c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law)
  raw=json.loads((tmp_path/'journal.json').read_bytes());assert raw['status']=='failed'and all(row['status']=='unissued'for row in raw['rows'])and raw['failed_ending_native_state']==raw['initial_native_state'];return
 result=c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law);s.validate_delivery(result,response,q,e,c)
 assert all(row['status']=='unresolved'for row in result['rows'])and result['summary']['cohorts'][0]['scheduled']==2
 if phase=='partial_integral':
  failed=[snapshot for snapshot in result['native_readback_cost']['snapshots']if snapshot['status']=='failed'];assert failed and len(failed[0]['integrals'])==2 and failed[0]['scalar_reads'][-1]['status']=='pending'
 elif phase=='state_after':
  assert calls==[0,1,0,1] # no retry of the interrupted same stream/draw
  assert all(row['native_sampler']['draws'][0]['status']=='returned'and row['native_sampler']['draws'][0]['after']['status']=='pending_write'for row in result['rows'])
 else:assert all(row['native_sampler']['draws'][0]['return']>1 for row in result['rows'])

@pytest.mark.parametrize('mode',['conditional','unconditional'])
def test_native_model_complete_mc_exposure_and_common_gaussian_law_once(tmp_path,monkeypatch,mode):
 from ravel.physics import statistical_construction as regional
 d=calibration_recipe(tmp_path,monkeypatch);cell=d['cells'][0]
 cell['law']=regional.poisson_template_auxiliary(cell['law'],[{'bin':'MC','rate':'beta','observed':3,'exposure':'3','source':'s','observation_id':'independentMC'}],statement='Explicit synthetic complete independent Poisson MC law',independence='Distinct toy SR/CR/MC observations',source='s')
 for term in cell['components']:
  term['coefficients'].append('0');term['log_response'].append(['0','0']);term['bin_windows'].append({'massObs':['1','2'],'angleObs':['-1','2']})
 cell['calibration']['auxiliary_mode']=mode;cell['calibration']['native_readback_budget']['max_integral_reads']=1000;rebind(d,tmp_path);response=g.response(d,'cell0');q=cell['calibration'];root,w,mc,data=façade(tmp_path,response)
 for name in ('ravel_base_mean_4','ravel_mean_4'):w.function(name).getVal=lambda:3*w.var('beta').getVal()
 law=s.GraphLaw(root,w,mc,response,q,e,c,cd);result=c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law);s.validate_delivery(result,response,q,e,c)
 for row in result['rows']:
  assert row['observation']['means_at_fixed_truth']['MC']==15 and set(row['observation']['counts'])==set('ABCD')|{'MC'}
  assert len(row['observation']['globals'])==2 and len(row['observation']['component_seeds'])==7
  if mode=='conditional':assert row['observation']['counts']['MC']==3 and all(v==0 for v in row['observation']['globals'].values())
  else:assert row['observation']['counts']['MC']==c.poisson(15,random.Random(c.seed_for(q,'truth1',row['ordinal'],'count:MC')))

def test_later_invalid_cell_is_refused_before_public_population_files(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch,population=True);d['cells'][-1]['calibration']['truths'][0]['point'].pop('slope');rebind(d,tmp_path);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));out=tmp_path/'bundle'
 with pytest.raises(ValueError):g.run({'input':str(p)},tmp_path,out)
 assert not(out/'cells').exists()and not(out/'construction-manifest.json').exists()

def test_full_public_report_names_native_model_algebra_scope_and_unchanged_failures(tmp_path,monkeypatch):
 from ravel.plotting.science_figures import render
 _,response,q,result,_=delivery(tmp_path,monkeypatch,fail_profile=True)
 render({'mode':'full-auxiliary-calibration'},{'inference':{'delivery':result}},tmp_path,tmp_path/'report')
 text=(tmp_path/'report/calibration-report.md').read_text();assert 'Native-model'in text and 'algebra check'in text and 'unqualified'in text and 'Unresolved'in text
 assert json.loads((tmp_path/'report/calibration-summary.json').read_bytes())==result['summary']

def test_hybrid_boundaries_keep_old_1000_draw_and_refuse_gaussian_branch(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');q=s.cell(response)['calibration'];root,w,mc,data=façade(tmp_path,response);law=s.GraphLaw(root,w,mc,response,q,e,c,cd)
 root.TRandom3=lambda *args:(_ for _ in()).throw(AssertionError('native sampler must remain unused at boundary'))
 assert law.poisson(1000.,random.Random(20),'A')==c.poisson(1000.,random.Random(20))
 with pytest.raises(ValueError,match='Gaussian'):law.poisson(1e9,random.Random(20),'A')


def test_zero_state_budget_leaves_all_large_count_slots_unissued(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');q=s.cell(response)['calibration'];q['count_sampler']['max_state_bytes']=0;root,w,mc,data=façade(tmp_path,response,large=True);law=s.GraphLaw(root,w,mc,response,q,e,c,cd)
 result=c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law);s.validate_delivery(result,response,q,e,c)
 assert all(row['status']=='unissued'for row in result['rows'])and result['top_level_profile_requests']==result['native_sampler_state_bytes']==0 and result['native_readback_cost']['returned_snapshots']==1


def test_ambiguous_cutoff_retains_raw_zero_q_and_full_failure_envelope(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');q=s.cell(response)['calibration'];q['critical_q']='0';root,w,mc,data=façade(tmp_path,response);law=s.GraphLaw(root,w,mc,response,q,e,c,cd)
 result=c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law);s.validate_delivery(result,response,q,e,c)
 assert all(row['status']=='unresolved'and row['raw_q']==0 and 'ambiguity'in row['error']['message']for row in result['rows'])and result['summary']['cohorts'][0]['identification_interval']==[0.,1.]


def test_negative_raw_native_q_is_retained_without_clipping_before_factorization_refusal(tmp_path,monkeypatch):
 d=calibration_recipe(tmp_path,monkeypatch);response=g.response(d,'cell0');q=s.cell(response)['calibration'];root,w,mc,data=façade(tmp_path,response)
 original=mc.GetPdf
 def invalid_native_nll():
  pdf=original();create=pdf.createNLL
  def changed(*args):
   nll=create(*args);value=nll.getVal;nll.getVal=lambda:value()+(0 if w.var('c').isConstant()else 1);return nll
  pdf.createNLL=changed;return pdf
 mc.GetPdf=invalid_native_nll;law=s.GraphLaw(root,w,mc,response,q,e,c,cd)
 result=c.execute(root,w,mc,data,response,q,e,tmp_path/'journal.json',20.,_graph_law=law);s.validate_delivery(result,response,q,e,c)
 assert all(row['status']=='unresolved'and row['raw_q']==-2. and 'factorization'in row['error']['message']for row in result['rows'])and result['summary']['cohorts'][0]['identification_interval']==[0.,1.]


def test_full_native_rng_buffers_reject_changed_custody_and_discontinuous_stream(tmp_path,monkeypatch):
 _,response,q,result,_=delivery(tmp_path,monkeypatch,large=True);buffers={p.name:p.read_bytes()for p in tmp_path.glob('ravel_calibration_rng_*')};assert s.validate_rng_states(result,buffers)
 one=next(iter(buffers));changed=dict(buffers);changed[one]=changed[one]+b' '
 with pytest.raises(ValueError,match='subject'):s.validate_rng_states(result,changed)
 changed=deepcopy(result);record=changed['rows'][0]['native_sampler']['draws'][1]['before'];obj=json.loads(buffers[record['basename']]);obj['fCount624']+=1;raw=json.dumps(obj).encode();changed_buffers=dict(buffers);changed_buffers[record['basename']]=raw;record.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
 with pytest.raises(ValueError,match='continuity'):s.validate_rng_states(changed,changed_buffers)
