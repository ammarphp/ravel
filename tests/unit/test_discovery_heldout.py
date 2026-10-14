"""Prospective fabricated arithmetic/API controls; no native import/execution.

RS1 hand oracles are expected values, not a qualified native fit run.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
import pytest
from ravel.physics import discovery_heldout as d,regional_expected as e


def cell():
    return {'law':{'parameters':[{'name':'mu','role':'poi','initial':'1','bounds':['0','4'],'fixed':False}],
        'bins':[{'id':'SR'}],'auxiliary':{'eta_bounds':[],'observed':[]},'sources':[{'id':'source'}]},
        'parameters':[],'expected_data':{'conditioning':'supplied_nominal','point':{'mu':'1'}}}


def request():
    return {'kind':d.KIND,'convention':'physical_nonnegative_domain','starts':{'free':[{'mu':'1'}],'null':[{'mu':'0'}]},
        'profile_policy':deepcopy(e.PROFILE_POLICY),'max_fit_calls':2,'max_readbacks':5,
        'absolute_nll_band':'1/100000000','relative_nll_band':'0','source':'source','statement':'fabricated mathematical source'}


@pytest.mark.parametrize('q',[2*(12*math.log(4/3)-3),2*(F(11,4)*math.log(11/9)-F(1,2)),
    0,40*math.log(9/8),2*(6*math.sqrt(3)-12+12*math.log(12/(6*math.sqrt(3)))+(6*math.sqrt(3)-9)**2/18)])
def test_rs1_known_poisson_fractional_cr_signal_degeneracy_and_normal_oracles(q):
    # Exact supplied fit minima; this tests common-NLL contrast semantics, not
    # minimization or nuisance profiling of these laws.
    result=d.contrast(0,float(q)/2,1+float(q)/2,1,request())
    assert math.isclose(result['q0_asimov'],float(q),rel_tol=1e-13,abs_tol=1e-13)
    assert result['observed_significance'] is None and result['global_significance'] is None


def test_common_offset_and_best_known_free_candidates():
    result=d.contrast(F(41,4).__float__(),F(49,4).__float__(),14,1,request())
    assert result['q0_asimov']==4
    with pytest.raises(ValueError,match='worse'):d.contrast(15,12,14,1,request())


def test_signed_small_negative_retained_but_material_negative_refuses():
    r=request();result=d.contrast(1+1e-9,1,2,0,r)
    assert result['q0_asimov']==0 and result['signed_common_nll_contrast']<0 and result['negative_contrast_clipped_within_band']
    with pytest.raises(ValueError):d.contrast(1.1,1,2,0,r)


@pytest.mark.parametrize('mutate',[
    lambda r:r['starts']['null'][0].__setitem__('mu','1'),
    lambda r:r.__setitem__('max_fit_calls',1),
    lambda r:r.__setitem__('max_readbacks',4),
    lambda r:r['starts']['free'][0].__setitem__('mu','5'),
    lambda r:r.__setitem__('profile_policy',{**r['profile_policy'],'strategy':2}),
    lambda r:r.__setitem__('absolute_nll_band','1'),
    lambda r:r['starts']['null'][0].__setitem__('invented_nuisance','0')])
def test_complete_source_start_and_closed_work_budget_refusals(mutate):
    r=request();mutate(r)
    with pytest.raises(ValueError):d.validate(r,cell(),e.PROFILE_POLICY)


def test_full_request_and_negative_unconstrained_poi_remain_distinct():
    assert d.validate(request(),cell(),e.PROFILE_POLICY)==request()
    c=cell();c['law']['parameters'][0]['bounds'][0]='-4'
    with pytest.raises(ValueError,match='nonnegative'):d.validate(request(),c,e.PROFILE_POLICY)
    with pytest.raises(ValueError,match='physical'):d.contrast(0,1,2,-1,request())


def test_roleless_graph_coordinates_join_the_start_census_and_cannot_be_the_poi():
    # A cell's graph coordinates are closed name/domain rows without a role.
    graph={'name':'shape','initial':'1/2','bounds':['0','1'],'fixed':False,'unit':'1','member':'fabricated'}
    c=cell();c['parameters']=[graph];c['expected_data']['point']['shape']='1/2'
    r=request();r['starts']['free'][0]['shape']='1/4';r['starts']['null'][0]['shape']='3/4'
    assert d.validate(r,c,e.PROFILE_POLICY)==r
    missing=deepcopy(r);missing['starts']['null'][0].pop('shape')
    with pytest.raises(ValueError,match='complete original start coordinates'):d.validate(missing,c,e.PROFILE_POLICY)
    outside=deepcopy(r);outside['starts']['free'][0]['shape']='2'
    with pytest.raises(ValueError,match='outside original domain'):d.validate(outside,c,e.PROFILE_POLICY)
    fixed=deepcopy(c);fixed['parameters'][0]['fixed']=True
    with pytest.raises(ValueError,match='fixed source coordinate'):d.validate(r,fixed,e.PROFILE_POLICY)
    # A role written onto a graph coordinate does not make a second, or a replacement, POI.
    labelled=deepcopy(c);labelled['parameters'][0]['role']='poi'
    assert d.validate(r,labelled,e.PROFILE_POLICY)==r
    orphan=deepcopy(labelled);orphan['law']['parameters'][0]['role']='coefficient'
    with pytest.raises(ValueError,match='one original POI'):d.validate(r,orphan,e.PROFILE_POLICY)


def test_ordinary_registry_uses_same_native_executor_without_new_backend():
    from ravel.workflow.science import adapter
    from ravel.physics import asimov_sensitivity as s
    assert adapter({'mode':'asimov-sensitivity','task':{'input':'fabricated'}}) is s
    assert s.native is __import__('ravel.physics.native_likelihood',fromlist=['run'])


class Var:
    def __init__(self):self.value=1.;self.constant=False;self.error=None
    def GetName(self):return 'mu'
    def getVal(self):return self.value
    def setVal(self,x):self.value=float(x)
    def isConstant(self):return self.constant
    def setConstant(self,x):self.constant=bool(x)
    def hasMin(self):return True
    def hasMax(self):return True
    def getMin(self):return 0.
    def getMax(self):return 4.
    def hasError(self):return self.error is not None
    def getError(self):return self.error or 0.
    def setError(self,x):self.error=x
    def removeError(self):self.error=None
    def hasAsymError(self):return False
    def getAsymErrorLo(self):return 0.
    def getAsymErrorHi(self):return 0.
    def removeAsymError(self):pass


def protocol(tmp_path,failed_role=None,reset_drift=False):
    """Inert facade; no RooFit result/optimizer/version qualification."""
    from types import SimpleNamespace
    import hashlib,json
    v=Var();w=SimpleNamespace(allVars=lambda:[v],var=lambda name:v)
    w.function=lambda name:SimpleNamespace(getVal=lambda:10+v.value)
    nll=SimpleNamespace(getVal=lambda:(v.value-1)**2+7)
    data=SimpleNamespace(weight=lambda:1.)
    mc=object();state=lambda *_:{'mu':{'value':v.value,'minimum':0.,'maximum':4.,'constant':v.constant}}
    errors=lambda *_:{'mu':{k:x for k,x in d.snapshot(w)['mu'].items() if k in ('has_error','error','has_asymmetric_error','low','high')}}
    source=cell();source.update(id='case',components=[])
    response={'kind':'native-source-graph/v1','cell':'case','recipe':{'cells':[source]},'coordinates':['mu'],
        'document':{'bins':[{'id':'SR'}]}}
    prep={'kind':'source-graph-asimov/v1','status':'passed','request':source['expected_data'],
        'dataset_counts':{'SR':11.},'generated_globals':{},'final_state':state()}
    meta={'observables':[]}
    def capture(*_):
        return {'parameters':[{'name':'mu','kind':'continuous','value':v.value,'constant':v.constant}], 'categories':[], 'model_config':meta}
    def restore(*args):
        row=args[-1]['parameters'][0];v.setVal(row['value']);v.setConstant(row['constant'])
        if reset_drift:v.setConstant(not v.constant)
    gs=SimpleNamespace(capture=capture,restore=restore,data_census=lambda _: {'fabricated_counts':11.},
        model_config=lambda _:meta,global_source_semantics=lambda *_:{'fabricated':True},components=lambda *_:{'fabricated':True})
    def fit(ROOT,nll,w,response,path,start):
        role='null' if v.constant else 'free'
        if role==failed_role:raise ValueError('inert '+role+' fit failure')
        if v.constant:return {'performed':False,'reason':'no_floating_nuisance'}
        v.setVal(1);v.setError(1)
        raw=b'FABRICATED RAW FIT WITNESS; NOT ROOT';path.write_bytes(raw)
        return {'performed':True,'floating_parameters':[{'name':'mu','value':1.,'error':1.}],
            'constant_parameters':[],'covariance':[[1.]],'min_nll':nll.getVal(),
            'raw_result':{'basename':path.name,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}}
    optimizer=SimpleNamespace(PROFILE_POLICY=e.PROFILE_POLICY,_state=state,_counts=lambda *_:{'SR':11.},_globals=lambda *_:{},
        _json_evidence=lambda x:x,_profile_fit=fit,_errors=errors,source_graph_integrals=lambda *_:[],conditioning_check=lambda *_:None)
    ROOT=SimpleNamespace(gROOT=SimpleNamespace(GetVersion=lambda:'6.22/00'))
    return ROOT,w,mc,data,nll,response,request(),prep,tmp_path/'journal.json',optimizer,gs,60


def test_same_dataset_inert_protocol_full_raw_state_errors_and_reset(tmp_path):
    args=protocol(tmp_path);result=d.execute(*args)
    assert result['fit_calls']==2 and result['readback_calls']==5 and result['diagnostic']['q0_asimov']==2
    assert result['ending_whole_state']==result['initial_whole_state']
    assert result['profiles'][0]['whole_state']['mu']['error']==1
    assert result['profiles'][1]['fit']['performed'] is False
    import json
    assert json.loads((tmp_path/'journal.json').read_text())==result
    bad=deepcopy(result);bad['profiles'][0]['state']['mu']['value']=2
    with pytest.raises(ValueError):d.validate_delivery(bad,args[5],args[6],args[9])


def test_failed_profile_retains_whole_unissued_denominator(tmp_path):
    args=protocol(tmp_path,failed_role='free');args[6]['starts']['null'].append({'mu':'0'})
    args[6]['max_fit_calls']=3;args[6]['max_readbacks']=7
    with pytest.raises(ValueError,match='inert free'):d.execute(*args)
    import json
    failed=json.loads((tmp_path/'journal.json').read_text())
    assert [r['status'] for r in failed['profiles']]==['failed','unissued','unissued']
    assert failed['status']=='failed' and failed['fit_calls']==1 and failed['readback_calls']==1
    with pytest.raises(ValueError):d.validate_delivery(failed,args[5],args[6],args[9])


def test_native_reset_drift_does_not_become_success_or_retry(tmp_path):
    with pytest.raises(ValueError,match='restoration'):d.execute(*protocol(tmp_path,reset_drift=True))
    import json
    failed=json.loads((tmp_path/'journal.json').read_text())
    assert failed['status']=='failed' and failed['fit_calls']==0 and all(x['status']=='unissued' for x in failed['profiles'])


def test_contrast_band_is_common_offset_invariant():
    r=request();r['relative_nll_band']='1/100000000'
    first=d.contrast(10.25,12.25,14.,1,r)
    second=d.contrast(110.25,112.25,114.,1,r)
    assert first==second
