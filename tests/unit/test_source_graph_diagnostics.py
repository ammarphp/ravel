"""Pure source/API controls with explicitly inert native boundaries; no ROOT evidence."""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace as NS
import ast,json,pytest
from ravel.physics import native_statistical_construction as g,native_likelihood as n,regional_expected as e
from ravel.physics import combine_derivatives as cd,native_likelihood_derivatives as kernel
from ravel.workflow import science
from source_graph_coverage_fixture import fixture
from test_source_graph_coverage import recipe as expected_recipe,graph_probe,fake_graph,rebind
from test_combine_derivatives import Real,PDF

def diagnostic_recipe(tmp_path,monkeypatch,expected=False):
 d=expected_recipe(tmp_path,monkeypatch,population=True,expected=expected)
 for cell in d['cells']:
  cell['fit'].pop('saved_fit',None);cell['fit'].update(points=None,minimizer=None,reference_quantiles=None,fixed_witness_points=[])
  cell['derivatives']={'anchor':{'slope':.25},'axes':[{'name':'c','step':.125},{'name':'slope','step':.125}],'max_points':256}
 rebind(d,tmp_path);return d

@pytest.mark.parametrize('expected',[False,True])
def test_complete_constructor_and_ordinary_inputs_bind_explicit_original_cell_diagnostics(tmp_path,monkeypatch,expected):
 d=diagnostic_recipe(tmp_path,monkeypatch,expected);p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));result=g.run({'input':str(p)},tmp_path,tmp_path/'bundle')
 assert len(result['cells'])==16 and result['native_calls']==result['fit_calls']==0
 for row in result['cells']:
  cp=Path(row['task']['input']);cfg=json.loads(cp.read_text());parsed=n._configuration(row['task'],cp.parent)
  assert cfg['schema_version']==3 and cfg['derivatives']==next(c['derivatives']for c in d['cells']if c['id']==row['id'])
  inputs=science.task_inputs({'mode':'native-likelihood','task':row['task'],'max_seconds':30},cp.parent)
  assert Path(cd.__file__)in inputs and Path(kernel.__file__)in inputs
  assert n.commands(cfg,parsed[3],cp.parent,has_response=True)[1] is None
  if expected:assert cfg['fit']['data']=='source_asimov' and all(v is None for v in parsed[8]['source_observations'].values())
  cfg['derivatives']['anchor']['slope']=.5;cp.write_text(json.dumps(cfg))
  with pytest.raises(ValueError,match='original cell operation'):n._configuration(row['task'],cp.parent)

@pytest.mark.parametrize('change',[
 lambda c:c['derivatives']['axes'][1].update(name='massObs'),
 lambda c:c['derivatives']['axes'][1].update(name='kappa'),
 lambda c:c['derivatives']['anchor'].update(slope=3.),
 lambda c:c['fit'].update(fixed_witness_points=['0']),
 lambda c:c['fit'].update(points=3),
])
def test_derivative_recipe_refuses_fixed_integration_or_out_of_domain_axes_and_implicit_extra_calls(tmp_path,monkeypatch,change):
 d=diagnostic_recipe(tmp_path,monkeypatch);change(d['cells'][-1])
 with pytest.raises(ValueError):g.validate_document(d)

def derivative_delivery(compiled,context,selection,counts,recorder):
 cell=next(c for c in compiled['recipe']['cells']if c['id']==compiled['cell']);d=compiled['document'];vars_=[]
 for p in d['parameters']:vars_.append(Real(p['name'],float(F(p['initial'])),p['fixed'],tuple(map(lambda q:float(F(q)),p['bounds']))))
 for i,bounds in enumerate(d['auxiliary']['eta_bounds']):
  vars_ += [Real('ravel_aux_'+str(i),0.,False,tuple(map(lambda q:float(F(q)),bounds))),Real('ravel_aux_'+str(i)+'_In',0.,True,(-float('inf'),float('inf')))]
 for o in cell['observables']:vars_.append(Real(o['name'],1.5,True,tuple(map(lambda q:float(F(q)),o['bounds']))))
 for b in d['bins']:vars_.append(Real('n_obs_bin'+b['id'],float(counts[b['id']]),False,(0.,10000.)))
 for v in vars_:
  if v.name in context['definition'].get('source_graph_initial_state',{}):v.value=context['definition']['source_graph_initial_state'][v.name]['value']
 w=NS(allVars=lambda:vars_,allCats=lambda:[],cat=lambda name:None,var=lambda name:next((v for v in vars_ if v.name==name),None))
 pdf=PDF();mc=NS(GetName=lambda:'ModelConfig',GetPdf=lambda:pdf,GetParametersOfInterest=lambda:[w.var('c')],GetNuisanceParameters=lambda:[w.var(v)for v in compiled['coordinates']if v!='c' and not w.var(v).constant],GetGlobalObservables=lambda:[w.var('ravel_aux_'+str(i)+'_In')for i in range(len(d['auxiliary']['names']))],GetObservables=lambda:[w.var('n_obs_bin'+b['id'])for b in d['bins']],GetConditionalObservables=lambda:[])
 class Data:
  def GetName(self):return 'data_obs'
  def ClassName(self):return 'RooDataSet'
  def numEntries(self):return 1
  def get(self,i):return mc.GetObservables()
  def weight(self):return 1.
  def sumEntries(self):return 1.
 class NLL:
  def GetName(self):return 'original_existing_nll'
  def ClassName(self):return 'RooNLLVar'
  def getVal(self):
   c=w.var('c').getVal();s=w.var('slope').getVal();return 10+2*c+3*s+5*c*c+7*c*s+11*s*s
 return cd.execute(w,mc,Data(),NLL(),selection,context,{'name':'c','bounds':[-2.,2.]},kernel,recorder=recorder)

@pytest.mark.parametrize('expected',[False,True])
def test_actual_worker_defers_stencil_until_explicit_complete_observed_or_generated_data_action(tmp_path,monkeypatch,expected):
 d=diagnostic_recipe(tmp_path,monkeypatch,expected);d['population']={k:[v[0]]for k,v in d['population'].items()};d['cells']=d['cells'][:1];rebind(d,tmp_path)
 p=tmp_path/'recipe.json';p.write_bytes(g.encoded(d));prepared=g.run({'input':str(p)},tmp_path,tmp_path/'bundle');task=prepared['cells'][0]['task'];compiled=g.response(d,'cell0');calls=[];prep=[]
 def process(cmd,cwd,env,log,deadline,**kwargs):
  name=Path(log).name;calls.append(name);work=Path(log).parent.parent/'native-work'
  if name=='workspace-build.log':(work/'ravel_workspace.root').write_bytes(b'inert observed workspace')
  if name=='combine-version.log':raw=' <<< Combine >>>\n <<< v9.2.1 >>>\nMissing datacard file\nUsage: combine [options]\n'
  elif name=='workspace-probe.log':
   assert not (work/'ravel_derivative_context.json').exists();raw='RAVEL_NATIVE_PROBE='+json.dumps(graph_probe(compiled))
  elif name=='expected-preparation.log':
   assert not (work/'ravel_derivative_context.json').exists();root,w,mc,data,*_=fake_graph(tmp_path,compiled);value=e.prepare_source_graph(root,w,mc,data,object(),compiled,work/'ravel_expected_preparation.json');prep.append(value);(work/'ravel_expected_workspace.root').write_bytes(b'inert generated workspace');raw='RAVEL_NATIVE_PROBE='+json.dumps({'expected_preparation':value})
  elif name=='expected-workspace-probe.log':
   assert not (work/'ravel_derivative_context.json').exists();raw='RAVEL_NATIVE_PROBE='+json.dumps(graph_probe(compiled,prep[0]))
  elif name=='source-graph-diagnostics.log':
   assert cmd[-1]=='--diagnose-source-graph' and Path(cmd[3]).name==('ravel_expected_workspace.root'if expected else 'ravel_workspace.root')
   cfg=json.loads((work/'ravel_native_configuration.json').read_text());ctx=json.loads((work/'ravel_derivative_context.json').read_text());probe=graph_probe(compiled,prep[0]if expected else None)
   rec=cd.JsonlRecorder(work/'ravel_derivative_points.jsonl')
   try:probe['derivatives']=derivative_delivery(compiled,ctx,cfg['derivatives'],probe['construction_observations']['counts'],rec)
   finally:rec.close()
   raw='RAVEL_NATIVE_PROBE='+json.dumps(probe)
  elif name in ('native-identity.log',):raw='RAVEL_NATIVE_PROBE={}'
  else:raw='inert boundary'
  Path(log).write_text(raw);return raw
 monkeypatch.setattr(n,'_process',process);monkeypatch.setattr(n,'_check_probe',lambda*a,**k:None);monkeypatch.setattr(n.platform,'platform',lambda:'inert host metadata')
 result=n.run(task,Path(task['input']).parent,tmp_path/'native-output')
 assert result['status']=='passed',result
 assert calls.count('source-graph-diagnostics.log')==1 and 'native-fit.log'not in calls and 'native-result.log'not in calls
 assert result['inference']['fit_calls']==0 and result['inference']['expected_conditioning_fit_calls']==0
 assert result['inference']['data_semantics']==('generated_source_graph_Asimov_not_observed'if expected else 'original_observed_source_graph_counts')
 estimates=json.loads((tmp_path/'native-output/native-derivative-estimates.json').read_text())
 assert estimates['levels'][0]['gradient']==[3.75,8.5] and estimates['levels'][0]['hessian']==[[10.,7.],[7.,22.]]
 assert result['integration_diagnostics']['convergence']=='unknown' and not result['physics_validated']
 if expected:assert calls.index('expected-workspace-probe.log')<calls.index('source-graph-diagnostics.log')

def test_generated_worker_source_is_syntactically_complete_and_action_gate_is_distinct():
 ast.parse(n.NATIVE_PROBE)
 assert "if derivative_action:" in n.NATIVE_PROBE and "--diagnose-source-graph" in n.NATIVE_PROBE
