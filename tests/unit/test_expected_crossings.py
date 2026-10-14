from copy import deepcopy
import json,math,ast
import pytest
from ravel.physics import regional_expected as e, native_likelihood as n
from expected_crossing_fixture import known_document,setup,roots

def execute(tmp_path,d,rows=None):
 args=setup(tmp_path,d,rows);out=e.qualify_crossings(*args,tmp_path/'crossings.json')
 e.check_limits(args[-1]['inference'],args[-1]['fit'],out,args[-2],args[-1]['preparation'])
 return args,out

def test_actual_helper_fifteen_profiles_full_state_and_source_law(tmp_path):
 args,out=execute(tmp_path,known_document(tmp_path))
 assert len(out['profiles'])==15 and all(not x['fit']['performed'] for x in out['profiles'])
 assert out['initial_state']==out['final_state']
 assert len(args[-1]['inference']['resolved_quantiles'])==5
 assert all(x['passed'] for x in out['original_crossings'])
 assert json.loads((tmp_path/'crossings.json').read_text())==out

def test_auxiliary_profiles_retain_raw_result_census_and_full_covariance(tmp_path):
 args,out=execute(tmp_path,known_document(tmp_path,auxiliary=True))
 assert len(list(tmp_path.glob('ravel_expected_profile_*.root')))==15
 assert all(row['fit']['covariance']==[[1.]] for row in out['profiles'])
 assert all(row['globals']['ravel_aux_0_In']['value']==.5 for row in out['profiles'])

@pytest.mark.parametrize('mutation',[
 lambda x:x['profiles'][0].update(nll=x['profiles'][0]['nll']+.1),
 lambda x:x['profiles'][0]['start_state']['mu'].update(value=.1),
 lambda x:x['profiles'][0]['counts'].update(SR=99.),
 lambda x:x['profiles'][0]['state']['mu'].update(constant=False),
 lambda x:x['profiles'][0]['state']['mu'].update(maximum=25.),
 lambda x:x['profiles'][0].update(mu=99.),
 lambda x:x['profiles'].pop(),
 lambda x:x['solutions'].pop(),
 lambda x:x['solutions'][0].update(endpoint=1.),
 lambda x:x['solutions'][0].update(upper_index=14),
 lambda x:x.update(optimizer_globality_qualified=True),
 lambda x:x['reference'].update(nll=x['reference']['nll']-.3),
 lambda x:x.update(final_nll=x['final_nll']+.01),
 lambda x:x['original_crossings'][0].update(passed=False),
])
def test_material_crossing_or_state_adversaries(tmp_path,mutation):
 args,out=execute(tmp_path,known_document(tmp_path));bad=deepcopy(out);mutation(bad)
 with pytest.raises(ValueError):e.check_limits(deepcopy(args[-1]['inference']),args[-1]['fit'],bad,args[-2],args[-1]['preparation'])

@pytest.mark.parametrize('field,value',[('status',1),('cov_qual',2),('edm',.1),('invalid_nll',1),('hesse_status',1)])
def test_profile_optimizer_failure_retained_before_admission(tmp_path,field,value):
 args=setup(tmp_path,known_document(tmp_path,auxiliary=True));root=args[0];klass=root.RooMinimizer
 methods={'status':'status','cov_qual':'covQual','edm':'edm','invalid_nll':'numInvalidNLL'}
 class Bad(klass):
  def hesse(self):return value if field=='hesse_status' else 0
  def save(self):
   fr=super().save()
   if field in methods:setattr(fr,methods[field],lambda:value)
   return fr
 root.RooMinimizer=Bad
 with pytest.raises(ValueError):e.qualify_crossings(*args,tmp_path/'crossings.json')
 raw=json.loads((tmp_path/'crossings.json').read_text())
 assert raw['status']=='failed' and len(raw['profiles'])==1 and raw['profiles'][0]['fit'][field]==value
 assert (tmp_path/'ravel_expected_profile_0.root').exists()

def bad_rows(b,s,maximum):
 # Literal released bisection search logic, independent from the repair.
 from statistics import NormalDist
 import struct
 rows=roots(b,s);normal=NormalDist();median=rows[2]['limit'];sigma=median/normal.inv_cdf(.975)
 result=rows[:3]
 for p,proposal in ((.84,median+2*sigma),(.975,median+4*sigma)):
  lo=result[-1]['limit'];hi=min(proposal,maximum);target=(normal.inv_cdf(p)+normal.inv_cdf(1-.05*p))**2
  x=(lo+hi)/2;err=(hi-lo)/2
  while err>max(.005*x,.0005):
   q=2*(x*s-b*math.log1p(x*s/b))
   if abs(q/2-target/2)<.05*.001:break
   if q<target:lo=x
   else:hi=x
   x=(lo+hi)/2;err=(hi-lo)/2
  result.append({'quantileExpected':p,'limit':struct.unpack('f',struct.pack('f',x))[0]})
 return result

@pytest.mark.parametrize('b,s,maximum',[(20.25,3.5,4.5),(.01,1.,20.)])
def test_both_original_material_counterexamples_refuse_verification(tmp_path,b,s,maximum):
 rows=bad_rows(b,s,maximum);args=setup(tmp_path,known_document(tmp_path,b,s,maximum),rows)
 with pytest.raises(ValueError,match='unbracketed'):e.qualify_crossings(*args,tmp_path/'crossings.json')
 out=json.loads((tmp_path/'crossings.json').read_text())
 assert out['status']=='failed' and len(out['profiles'])==15 and out['original_crossings'][-1]['passed'] is False
 assert args[-1]['inference']['rows']==rows

def test_low_count_constructive_refinement_retains_failed_original_and_all_five(tmp_path):
 b=.01;s=1.;rows=bad_rows(b,s,20.)
 args,out=execute(tmp_path,known_document(tmp_path,b,s,20.,refine=True),rows)
 result=args[-1]['inference']
 assert result['rows']==rows and out['original_crossings'][-1]['passed'] is False
 assert out['solutions'][-1]['source']=='bounded_native_profile_refinement'
 assert abs(result['resolved_quantiles']['plus2sigma']/roots(b,s)[-1]['limit']-1)<.005
 assert 15<len(out['profiles'])<=100

def test_no_crossing_within_physical_domain_retains_failed_refinement(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,20.25,3.5,4.5,refine=True),bad_rows(20.25,3.5,4.5))
 with pytest.raises(ValueError,match='original physical domain'):e.qualify_crossings(*args,tmp_path/'crossings.json')
 out=json.loads((tmp_path/'crossings.json').read_text());assert out['status']=='failed'
 assert max(x['mu'] for x in out['profiles'])==4.5

def test_total_profile_cap_is_enforced_without_fabricated_solution(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,.01,1.,20.,refine=True,cap=16),bad_rows(.01,1.,20.))
 with pytest.raises(ValueError,match='budget exhausted'):e.qualify_crossings(*args,tmp_path/'crossings.json')
 out=json.loads((tmp_path/'crossings.json').read_text());assert out['status']=='failed' and len(out['profiles'])==16 and len(out['solutions'])<5

def test_python38_staged_helper_has_no_mandatory_ravel_or_root_import():
 from pathlib import Path
 tree=ast.parse(Path(e.__file__).read_text(),feature_version=(3,8));ast.parse(n.NATIVE_PROBE,feature_version=(3,8))
 for node in tree.body:
  if isinstance(node,ast.Import):assert all(x.name!='ROOT' for x in node.names)
 assert '--qualify-expected' in n.NATIVE_PROBE and "source_check=False" in Path(e.__file__).read_text()

def test_all_five_false_endpoints_refined_without_replacing_originals(tmp_path):
 rows=roots(20.25,3.5)
 for row in rows:row['limit']*=.6
 args,out=execute(tmp_path,known_document(tmp_path,refine=True,cap=150),rows)
 assert not any(x['passed'] for x in out['original_crossings'])
 assert all(x['source']=='bounded_native_profile_refinement' for x in out['solutions'])
 for sol,exact in zip(out['solutions'],roots(20.25,3.5)):assert abs(sol['endpoint']/exact['limit']-1)<.005
 assert args[-1]['inference']['rows']==rows

@pytest.mark.parametrize('policy',[{'mode':'silently_extend','max_profile_evaluations':100},{'mode':'verify_only','max_profile_evaluations':16},{'mode':'verify_or_refine','max_profile_evaluations':201},{'mode':'verify_or_refine','max_profile_evaluations':True}])
def test_refinement_requires_explicit_finite_source_policy(tmp_path,policy):
 from ravel.physics import statistical_construction as r
 d=known_document(tmp_path);d['expected_data']['crossing']=policy
 with pytest.raises(ValueError):r.validate(d)

def test_failed_original_reference_comparison_cannot_be_erased(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,.01,1.,20.,refine=True),bad_rows(.01,1.,20.))
 args[-1]['fit']['reference_quantiles']={'values':{'plus2sigma':roots(.01,1.)[-1]['limit']},'absolute_tolerance':.002,'relative_tolerance':.015}
 args[-1]['inference']=n.extract_rows(args[-1]['inference']['rows'],args[-1]['fit'])
 assert args[-1]['inference']['passed'] is False
 before=deepcopy(args[-1]['inference'])
 out=e.qualify_crossings(*args,tmp_path/'crossings.json')
 result=e.check_limits(args[-1]['inference'],args[-1]['fit'],out,args[-2],args[-1]['preparation'])
 assert result['rows']==before['rows'] and result['combine_result']['quantiles']==before['quantiles']
 assert result['quantiles']==result['resolved_quantiles']
 assert result['combine_result']['reference_comparisons']==before['reference_comparisons']
 assert result['combine_result_passed'] is False and result['passed'] is True

def test_nonfinite_profile_result_and_root_bytes_remain_after_refusal(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,auxiliary=True));root=args[0];klass=root.RooMinimizer
 class Bad(klass):
  def save(self):
   fr=super().save();fr.edm=lambda:float('nan');return fr
 root.RooMinimizer=Bad
 with pytest.raises(ValueError,match='nonfinite'):e.qualify_crossings(*args,tmp_path/'crossings.json')
 out=json.loads((tmp_path/'crossings.json').read_text())
 assert out['profiles'][0]['fit']['edm']=={'nonfinite_native_float':'nan'}
 assert out['status']=='failed' and (tmp_path/'ravel_expected_profile_0.root').is_file()

def test_changed_data_and_globals_cannot_supply_a_crossing(tmp_path):
 args,out=execute(tmp_path,known_document(tmp_path,auxiliary=True));bad=deepcopy(out)
 bad['profiles'][3]['globals']['ravel_aux_0_In']['value']=1.
 with pytest.raises(ValueError,match='observation/global'):e.check_limits(deepcopy(args[-1]['inference']),args[-1]['fit'],bad,args[-2],args[-1]['preparation'])


def test_staged_helper_native_path_runs_without_any_ravel_import(tmp_path,monkeypatch):
 import builtins,importlib.util
 from pathlib import Path
 d=known_document(tmp_path);args=setup(tmp_path,d)
 spec=importlib.util.spec_from_file_location('pure_staged_expected',Path(e.__file__))
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 args[4].getVal=lambda:(20.25+3.5*args[1].var('mu').getVal())-20.25*math.log(20.25+3.5*args[1].var('mu').getVal())
 original=builtins.__import__
 def forbid(name,*a,**k):
  if name=='ravel' or name.startswith('ravel.'):raise AssertionError('native staged helper cannot import installed Ravel')
  return original(name,*a,**k)
 monkeypatch.setattr(builtins,'__import__',forbid)
 result=module.qualify_crossings(*args,tmp_path/'staged-crossings.json')
 assert result['status']=='passed'


@pytest.mark.parametrize('index',[0,1])
def test_unchanged_independent_counterexample_rows_refuse(tmp_path,index):
 from pathlib import Path
 record=json.loads(Path(__file__).with_name('expected_quantile_counterexamples.json').read_text())['cases'][index]
 d=known_document(tmp_path,record['background'],record['signal_per_mu'],record['hard_max'])
 args=setup(tmp_path,d,record['source_algorithm_rows'])
 with pytest.raises(ValueError,match='unbracketed'):e.qualify_crossings(*args,tmp_path/'crossings.json')
 assert args[-1]['inference']['rows']==record['source_algorithm_rows']


def test_fit_error_steps_are_reset_after_every_nuisance_profile(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,auxiliary=True));root=args[0];klass=root.RooMinimizer;seen=[]
 class ChangedError(klass):
  def minimize(self,*a):
   seen.append(args[1].var('ravel_aux_0').getError())
   status=super().minimize(*a);args[1].var('ravel_aux_0').setError(.777);return status
 root.RooMinimizer=ChangedError
 result=e.qualify_crossings(*args,tmp_path/'crossings.json')
 assert seen==[.1]*15 and result['initial_errors']==result['final_errors']
 bad=deepcopy(result);bad['profiles'][4]['start_errors']['ravel_aux_0']['error']=.777
 with pytest.raises(ValueError,match='state/step-error'):e.check_limits(args[-1]['inference'],args[-1]['fit'],bad,args[-2],args[-1]['preparation'])


def test_absent_and_asymmetric_errors_are_restored_exactly(tmp_path):
 args=setup(tmp_path,known_document(tmp_path,auxiliary=True));w=args[1]
 w.var('mu').removeError();w.var('ravel_aux_0').setAsymError(-.2,.3)
 result=e.qualify_crossings(*args,tmp_path/'crossings.json')
 assert not w.var('mu').hasError() and w.var('ravel_aux_0').hasAsymError()
 assert result['initial_errors']==result['final_errors']
 assert result['initial_errors']['ravel_aux_0']['low']==-.2
