"""Pure reference/accounting and real ordinary caller with inert native boundary.
No ROOT import, fitted data, optimizer or calibration qualification.
"""
from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
from types import SimpleNamespace as NS
import ast,hashlib,json,math,shutil,sys
import pytest
from ravel.physics import regional_calibration as c,statistical_construction as r
from ravel.physics import continuous_dijet_shapes as k,full_auxiliary_calibration as a,native_likelihood as n
from test_full_auxiliary_calibration import fixture as base,configuration as base_config,fake
from test_continuous_shape_calibration import bundle
from test_regional_expected import e


def fixture(tmp_path, *, count=2, response=False):
    d,q=base(tmp_path,trials=1)
    names=['alpha']+['beta'+str(i) for i in range(1,count)]
    for name in names:
        d['parameters'].append({'name':name,'role':'coefficient','initial':'0','bounds':['-1/4','1/4'],'fixed':False,'meaning':'Artificial dimensionless density coefficient','source':'s'})
        q['truths'][0]['point'][name]='0'
    shape={'kind':k.KIND,'sqrt_s':'10','domain':['1','8'],'bin_windows':[['1','2'],['3','5'],None],
           'parameters':names,'parameter_response':[['1/100' if response else '0'] for _ in names],
           'integration':{'native':{'engine':'RooIntegrator1D','absolute_tolerance':'1e-12','relative_tolerance':'1e-10','max_steps':16},
           'reference':{'absolute_tolerance':'1e-14','relative_tolerance':'1e-12','max_depth':20,'max_evaluations':100000,'maximum_probability_error':'1e-10','maximum_gradient_error':'1e-8'}}}
    d['terms'][0].update(coefficients=['50','50','0'],shape=shape)
    d['terms'].append({'id':'signed','basis':'interference','coefficients':['-1/2','-1/2','0'],'powers':{'mu':1},'log_response':[['0'],['0'],['0']],'source':'s'})
    q['reference_budget']={'admission_reserved_evaluations':1000000,'toy_reserved_evaluations':3000000,'validation_reserved_evaluations':10000000}
    q['reference_admissibility']={name:'1/10' for name in ('fraction_of_existing_mean_band','fraction_of_existing_nll_band','fraction_of_existing_q_margin')}
    return d,q


def config(tmp_path):
    cp,cfg,_,_=base_config(tmp_path);d,q=fixture(tmp_path)
    source=tmp_path/'dijet.json';source.write_text(json.dumps(d));card=tmp_path/'dijet.txt';card.write_bytes(r.datacard(d))
    pin=lambda p:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    cfg['model']['construction']=pin(source);cfg['model']['files']=[{**pin(card),'staged_path':cfg['model']['card']}]
    cfg['calibration']=q;cp.write_text(json.dumps(cfg));return cp,cfg,d,q


def facade(tmp_path,d,q):
    root,w,mc,data,calls=fake(tmp_path,d)
    def point():return {x:str(F(w.var(x).getVal())) for x in r.coordinates(d)}
    def observation():return {'counts':{b['id']:int(v) for b,v in zip(d['bins'],data.rows[0])},'globals':{'ravel_aux_'+str(i)+'_In':w.var('ravel_aux_'+str(i)+'_In').getVal() for i in range(len(d['auxiliary']['names']))}}
    class NLL:
        def getVal(self):return c.source_nll(d,point(),observation(),reference=c.ReferenceAudit(q,d,'toy'))+37.25
    class PDF:
        def createNLL(self,data,opts):calls.append(('create_nll',deepcopy(observation())));return NLL()
    mc.GetPdf=lambda:PDF()
    return root,w,mc,data,calls


def delivery(tmp_path):
    d,q=fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0'
    root,w,mc,data,calls=facade(tmp_path,d,q)
    result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'journal.json',10.)
    assert all(row['status']=='included' for row in result['rows']),result['rows']
    return d,q,result,calls


@pytest.mark.parametrize('count',[2,3,4,5])
def test_complete_coefficient_laws_full_domain_reference_diagnostics(tmp_path,count):
    d,q=fixture(tmp_path,count=count);audit=c.ReferenceAudit(q,d,'admission');got=c.means(d,q['truths'][0]['point'],reference=audit)
    theta=1.25
    assert got==pytest.approx({'SR':50*math.exp(theta/10)/7+1.5,'CR':100*math.exp(-theta/10)/7+2.5,'MC':3})
    raw=audit.evidence['calls'][0]['result']
    assert raw['fractions']==pytest.approx([1/7,2/7,0]) and sum(raw['fractions'])<1
    assert len(raw['gradient'][0])==count and len(raw['estimated_gradient_error'][0])==count
    assert audit.evidence['reserved_evaluations']==100000 and audit.evidence['known_successful_evaluations']==raw['evaluations']
    assert 'not certified' in raw['error_semantics'] and not raw['clipping_applied']


def test_correlated_effective_coefficients_full_mc_and_source_nll(tmp_path):
    d,q=fixture(tmp_path,response=True);audit=c.ReferenceAudit(q,d,'toy');point=q['truths'][0]['point'];o=c.toy(q,d,q['truths'][0],0,reference=audit)
    raw=audit.evidence['calls'][0];assert list(map(F,raw['effective_coefficients']))==[F(1,80)]*2
    assert set(o['counts'])=={'SR','CR','MC'} and o['physical_gaussian_measurement']['theta']==pytest.approx(.25+2*o['globals']['ravel_aux_0_In'])
    direct=sum(v-o['counts'][b]*math.log(v)+math.lgamma(o['counts'][b]+1) for b,v in o['means_at_fixed_truth'].items())+.5*(.5-o['globals']['ravel_aux_0_In'])**2
    assert c.source_nll(d,point,o,reference=audit)==pytest.approx(direct)
    q['auxiliary_mode']='conditional';z=c.toy(q,d,q['truths'][0],0,reference=c.ReferenceAudit(q,d,'toy'))
    assert z['counts']['MC']==3 and z['globals']=={'ravel_aux_0_In':0.}
    assert z['component_seeds']==o['component_seeds']


@pytest.mark.parametrize('change',[lambda q:q.pop('reference_budget'),lambda q:q.pop('reference_admissibility'),lambda q:q['reference_budget'].update(toy_reserved_evaluations=True),lambda q:q['reference_budget'].update(admission_reserved_evaluations=99999),lambda q:q['reference_budget'].update(validation_reserved_evaluations=100000001),lambda q:q['reference_admissibility'].update(fraction_of_existing_mean_band='0'),lambda q:q['reference_admissibility'].update(fraction_of_existing_nll_band='1/9'),lambda q:q['reference_admissibility'].update(fraction_of_existing_q_margin=0.1)])
def test_prospective_policy_refusals(tmp_path,change):
    d,q=fixture(tmp_path);change(q)
    with pytest.raises((ValueError,KeyError)):c.validate(q,d)


def test_no_unbudgeted_dijet_means(tmp_path):
    d,q=fixture(tmp_path)
    with pytest.raises(ValueError,match='explicit prospective'):c.means(d,q['truths'][0]['point'])


def test_before_call_reservation_and_unknown_failure_count(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);audit=c.ReferenceAudit(q,d,'toy');seen=[]
    def failed(*args):
        seen.append(deepcopy(audit.evidence));raise ValueError('located synthetic quadrature refusal')
    monkeypatch.setattr(k,'reference',failed)
    with pytest.raises(ValueError,match='located'):c.means(d,q['truths'][0]['point'],reference=audit)
    assert seen[0]['reserved_evaluations']==100000 and seen[0]['calls'][0]['status']=='reserved'
    assert audit.evidence['calls'][0]['status']=='failed' and audit.evidence['calls'][0]['actual_evaluations'] is None
    assert audit.evidence['known_successful_evaluations']==0


def test_cost_unavailability_never_calls_kernel(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);q['reference_budget']['toy_reserved_evaluations']=100000;audit=c.ReferenceAudit(q,d,'toy');c.means(d,q['truths'][0]['point'],reference=audit)
    monkeypatch.setattr(k,'reference',lambda *args:(_ for _ in ()).throw(AssertionError('must not execute')))
    with pytest.raises(ValueError,match='reservation unavailable'):c.means(d,q['truths'][0]['point'],reference=audit)
    assert audit.evidence['calls'][-1]['reserved_evaluations']==0 and len(audit.evidence['calls'])==2


def test_absolute_signed_total_error_never_cancels(tmp_path):
    d,q=fixture(tmp_path);t=deepcopy(d['terms'][0]);t.update(id='negative',basis='interference',coefficients=['-49','-49','0']);d['terms'].append(t)
    audit=c.ReferenceAudit(q,d,'toy');got=c.means(d,q['truths'][0]['point'],reference=audit)
    check=audit.evidence['mean_checks'][-1];errors=audit.evidence['calls'][0]['result']['estimated_probability_error']
    assert got['SR']==pytest.approx(math.exp(.125)/7+1.5)
    assert check['estimated_mean_error']['SR']==pytest.approx(99*math.exp(.125)*errors[0])
    assert check['absolute_signed_term_contributions']['SR'][1]['signed_full_domain_coefficient']<0


def test_small_positive_mean_poisson_sensitivity_and_domain():
    got=c.estimated_nll_error({'SR':1e-4},{'SR':1e-6},{'SR':100})
    assert got==pytest.approx((1+100/(1e-4-1e-6))*1e-6) and got>1
    with pytest.raises(ValueError,match='positive-mean'):c.estimated_nll_error({'SR':1e-4},{'SR':1e-4},{'SR':100})


def test_accuracy_refusal_does_not_inflate_actual_mean_band(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);original=k.reference
    def inaccurate(*args):
        result=original(*args);result['estimated_probability_error'][0]=1e-7;return result
    monkeypatch.setattr(k,'reference',inaccurate);audit=c.ReferenceAudit(q,d,'toy')
    with pytest.raises(ValueError,match='accuracy screen'):c.means(d,q['truths'][0]['point'],reference=audit)
    assert audit.evidence['mean_checks'][-1]['status']=='unresolved'
    with pytest.raises(ValueError,match='differs'):c._check_means({'SR':1.0001},{'SR':1.},'unchanged band')


def test_full_inert_lifecycle_complete_audit_and_existing_profiles(tmp_path):
    d,q,result,calls=delivery(tmp_path);audit=c.ReferenceAudit(q,d,'validation')
    assert c.validate_delivery(result,r.response(d),q,e,reference=audit) is result
    row=result['rows'][0];assert row['reference_audit']['reserved_evaluations']==700000
    accuracy=row['reference_accuracy'];assert accuracy['estimated_contrast_error']==sum(accuracy['estimated_source_nll_error'].values())
    assert accuracy['estimated_q_error']==2*accuracy['estimated_contrast_error'] and accuracy['certified_bound'] is False
    assert result['top_level_profile_requests']==2 and [x[0] for x in calls]==['create_nll','fit','fit']
    assert len(audit.evidence['calls'])==16 # admission + observation + classify six + raw admission/row eight
    assert result['initial_state']==result['final_state'] and result['original_counts']==result['final_counts']
    assert result['coverage_qualified'] is False and json.loads((tmp_path/'journal.json').read_bytes())==result


@pytest.mark.parametrize('field',['estimated_probability_error','fractions','gradient'])
def test_forged_retained_reference_output_refuses(tmp_path,field):
    d,q,result,_=delivery(tmp_path);raw=result['rows'][0]['reference_audit']['calls'][0]['result']
    if field=='gradient':raw[field][0][0]+=1e-8
    else:raw[field][0]+=1e-8
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)


def test_toy_cost_failure_keeps_original_denominator_without_redraw(tmp_path):
    d,q=fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0';q['reference_budget']['toy_reserved_evaluations']=100000
    root,w,mc,data,_=facade(tmp_path,d,q);result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'cost.json',10.)
    row=result['rows'][0];assert row['status']=='unissued' and row['reason']=='complete_toy_reference_reservation_unavailable'
    assert result['top_level_profile_requests']==0 and 'reference_audit' not in row
    assert result['summary']['cohorts'][0]['scheduled']==1 and result['summary']['cohorts'][0]['identification_interval']==[0,1]
    assert 'observation' not in row


def test_admission_failure_retains_reserved_audit_in_actual_journal(tmp_path):
    d,q=fixture(tmp_path);q['truths'].append({'id':'truth2','point':{**q['truths'][0]['point'],'alpha':'1/10'}})
    q['reference_budget']['admission_reserved_evaluations']=100000
    root,w,mc,data,_=facade(tmp_path,d,q);path=tmp_path/'admission-failed.json'
    with pytest.raises(ValueError,match='reservation unavailable'):c.execute(root,w,mc,data,r.response(d),q,e,path,10.)
    obj=json.loads(path.read_bytes());audit=obj['reference_admission']['reference_audit']
    assert obj['status']=='failed' and len(obj['rows'])==2 and all(r['status']=='unissued' for r in obj['rows'])
    assert audit['reserved_evaluations']==100000 and audit['calls'][-1]['actual_evaluations'] is None


def test_copied_finite_dijet_source_executes_authenticated_bytes(tmp_path):
    d,q=fixture(tmp_path);root,binding=bundle(tmp_path,d);assert 'physics/continuous_dijet_shapes.py' in binding['files']
    saved={name:module for name,module in sys.modules.items() if name=='ravel' or name.startswith('ravel.')}
    for name in saved:sys.modules.pop(name)
    try:
        c.bind_shape_sources(root,binding)
        source=sys.modules['ravel.physics.continuous_dijet_shapes'];assert Path(source.__file__).is_relative_to(root)
        assert c.reference_admission(q,d)['truth_means'][0]['means']['MC']==3
        assert not list(root.rglob('*.pyc'))
    finally:
        for name in list(sys.modules):
            if name=='ravel' or name.startswith('ravel.'):sys.modules.pop(name)
        sys.modules.update(saved)


def test_current_ordinary_context_and_source_dependency(tmp_path):
    cp,cfg,d,q=config(tmp_path);got=a.context({'input':str(cp)},tmp_path)
    assert got['scheduled_toys']==1 and got['toys_generated']==got['fits_performed']==0
    assert got['reference_admission']['reference_audit']['reserved_evaluations']==100000
    assert Path(k.__file__) in a.inputs({'input':str(cp)},tmp_path)
    assert got['execution_authorized'] is False


def test_actual_graph_host_context_and_missing_dijet_source_refusal(tmp_path):
    from ravel.workflow import agent_graph as g
    from ravel.workflow.agent_host import AgentHost
    cp,cfg,d,q=config(tmp_path);task={'input':str(cp)};tp=tmp_path/'task.json';tp.write_text(json.dumps(task))
    gs=a.graph(task,tmp_path,{'path':str(tp),'sha256':hashlib.sha256(tp.read_bytes()).hexdigest()});rd=tmp_path/'graph';g.create(rd,gs)
    assert g.execute(rd,AgentHost(api_key='unused'),workers=1)['complete']
    _,state=g._load(rd);value=g._result(rd,state['nodes']['context']['result'])['result']['value']
    assert value['reference_admission']['reference_audit']['calls'][0]['result']['gradient']
    broken=deepcopy(gs);broken['graph_id']='missing_dijet';broken['nodes'][0]['inputs']=[p for p in broken['nodes'][0]['inputs'] if p['path']!=k.__file__]
    other=tmp_path/'badgraph';g.create(other,broken);assert not g.execute(other,AgentHost(api_key='unused'),workers=1)['complete']


def test_existing_native_body_captures_validation_audit_and_raw_journal(tmp_path,monkeypatch):
    from test_native_likelihood import VERSION_LOG
    cp,cfg,d,q=config(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0';cfg['calibration']=q;cp.write_text(json.dumps(cfg));commands=[]
    monkeypatch.setattr(n,'_check_probe',lambda *args:None);monkeypatch.setattr(n,'_check_workspace',lambda *args:[])
    def supplied(command,cwd,env,log,deadline,**kwargs):
        commands.append(command);log.parent.mkdir(parents=True,exist_ok=True)
        if '--help' in command:value='Explicit inert help'
        elif len(command)==1:value=VERSION_LOG
        elif '-o' in command:Path(command[command.index('-o')+1]).write_bytes(b'FAKE workspace');value='Explicit inert build'
        elif '--calibrate' in command:
            root=Path(command[2]).parent;cfg2=json.loads(Path(command[2]).read_bytes());c.check_shape_sources(root,cfg2['calibration_shape_sources'],imported=False)
            rt,w,mc,data,_=facade(root,d,q);obj=c.execute(rt,w,mc,data,r.response(d),q,e,root/'ravel_calibration_journal.json',float(command[-1]))
            value='RAVEL_NATIVE_PROBE='+json.dumps({'calibration':obj})
        else:value='RAVEL_NATIVE_PROBE='+json.dumps({'identity':'inert supplied value'})
        log.write_text(value+'\n');return value
    monkeypatch.setattr(n,'_process',supplied);out=tmp_path/'attempt';got=a.run({'input':str(cp)},tmp_path,out)
    assert got['status']=='passed',got
    extracted=json.loads((out/'native-calibration.json').read_bytes());assert extracted['validation_reference_audit']['reserved_evaluations']==1600000
    assert extracted['delivery']['coverage_qualified'] is False and sum('--calibrate' in cmd for cmd in commands)==1


def test_nll_estimate_screen_cannot_absorb_discrepancy(tmp_path):
    d,q,result,_=delivery(tmp_path)
    q['reference_admissibility']['fraction_of_existing_nll_band']='1e-100'
    row=deepcopy(result['rows'][0])
    with pytest.raises(ValueError,match='NLL/q accuracy screen'):c.classify(q,d,row,result['initial_state'],e)
    assert row['reference_accuracy']['status']=='unresolved' and row['reference_accuracy']['unchanged_nll_band']==float(F(q['nll_absolute_tolerance']))


def test_nll_sensitivity_fixed_free_bands_unchanged(tmp_path):
    d,q,result,_=delivery(tmp_path);row=deepcopy(result['rows'][0]);row['fixed']['nll']+=.001
    row['fixed']['fit']['min_nll']+=.001
    with pytest.raises(ValueError,match='NLL contrast disagrees'):c.classify(q,d,row,result['initial_state'],e)


def test_returned_validation_audit_is_independent_and_not_old_vote(tmp_path):
    d,q,result,_=delivery(tmp_path);original=deepcopy(result)
    q['reference_budget']['validation_reserved_evaluations']=100000
    audit=c.ReferenceAudit(q,d,'validation')
    # Exact delivery request still must match, so hold a separately prospective
    # validation ceiling in a copy; this is no authority to recertify old output.
    supplied=deepcopy(result);supplied['request']=q
    with pytest.raises(ValueError,match='reservation unavailable'):c.validate_delivery(supplied,r.response(d),q,e,reference=audit)
    assert audit.evidence['reserved_evaluations']==100000 and audit.evidence['calls'][-1]['status']=='reservation_unavailable'
    assert result==original


@pytest.mark.parametrize('change',[lambda row:row['reference_accuracy']['estimated_source_nll_error'].update(free=0.),lambda row:row['reference_accuracy'].update(estimated_contrast_error=0.),lambda row:row['reference_audit']['calls'][0]['effective_coefficients'].__setitem__(0,'1/10'),lambda row:row['reference_audit'].update(reserved_evaluations=0),lambda row:row['reference_accuracy'].update(certified_bound=True)])
def test_retained_accuracy_and_cost_identity_refusals(tmp_path,change):
    d,q,result,_=delivery(tmp_path);change(result['rows'][0])
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)


@pytest.mark.parametrize('change',[lambda row:row['reference_accuracy'].update(unchanged_nll_band=1),lambda row:row['reference_audit']['mean_checks'][0]['estimated_mean_error'].update(SR=0),lambda row:row['reference_audit']['mean_checks'][0]['absolute_signed_term_contributions']['SR'][0].update(signed_full_domain_coefficient=1),lambda row:row['reference_audit']['mean_checks'][0]['point'].update(mu='2')])
def test_complete_retained_mean_and_band_report_refusals(tmp_path,change):
    d,q,result,_=delivery(tmp_path);change(result['rows'][0])
    with pytest.raises(ValueError):c.validate_delivery(result,r.response(d),q,e)



def test_report_roundoff_tolerance_preserves_original_raw_diagnostic(tmp_path):
    d,q,result,_=delivery(tmp_path);check=result['rows'][0]['reference_audit']['mean_checks'][0]
    old=check['means']['SR'];check['means']['SR']=math.nextafter(old,math.inf)
    observed=deepcopy(result)
    c.validate_delivery(result,r.response(d),q,e)
    assert result==observed and check['means']['SR']!=old
