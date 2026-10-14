"""Pure declared laws and supplied native facades, no ROOT/fit/runtime calls."""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace as NS
import ast
import hashlib
import json
import math
import pytest
from ravel.physics import regional_calibration as c, statistical_construction as r, regional_expected as e, full_auxiliary_calibration as a, native_likelihood as n
from test_regional_expected import fixture as expected_fixture, Workspace, Data, Var, Collection
from test_native_likelihood import fixture as runtime_fixture


def fixture(tmp_path, *, mc=True, trials=2):
    d=expected_fixture(tmp_path,True);d.pop('expected_data')
    if mc:
        d=r.poisson_template_auxiliary(d,[{'bin':'MC','rate':'beta','observed':3,'exposure':'3','source':'s','observation_id':'independentMC'}],statement='Explicit artificial independent unweighted Poissonized MC experiment',independence='Artificial distinct SR/CR/MC repeated measurements at fixed truth',source='s')
    request={'kind':c.KIND,'estimand':c.ESTIMAND,'source':'s','statement':'Synthetic fixed-truth independent Poisson SR/CR and complete MC+Gaussian repeated experiment, not a nuisance prior',
        'truths':[{'id':'truth1','point':{'mu':'1','beta':'1','ravel_aux_0':'1/2'}}], 'trials_per_truth':trials,'auxiliary_mode':'unconditional','seed':17,'critical_q':'384/100','confidence_level':'95/100','numerical_margin':'1/1000000','nll_absolute_tolerance':'1/100000','nll_relative_tolerance':'1/1000000','reservation_seconds_per_toy':1,'maximum_unresolved_fraction':'0'}
    r.validate(d);c.validate(request,d)
    return d,request


def configuration(tmp_path):
    cp,cfg,card,*_=runtime_fixture(tmp_path);d,request=fixture(tmp_path)
    source=tmp_path/'construction.json';source.write_text(json.dumps(d))
    pin=lambda p:{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    card.write_bytes(r.datacard(d));cfg['model']['files']=[{**pin(card),'staged_path':'source/card.txt'}]
    cfg['model']['regions']=[{'channel':b['id'],'role':b['role']} for b in d['bins']];cfg['model']['construction']=pin(source)
    cfg['schema_version']=2;cfg['max_seconds']=120;cfg['calibration']=request;cfg['runtime']['expected']['root_version']='6.22/00'
    cfg['fit'].update(method='MultiDimFit',poi='mu',domain=['0','20'],data='observed',points=None,fixed_witness_points=['0','1'],reference_quantiles=None,saved_fit={'algorithm':'none','required_object':'multidimfit.ravel.root:fit_mdf','maximum_edm':.00001})
    cp.write_text(json.dumps(cfg));return cp,cfg,d,request


def test_complete_law_and_conditional_auxiliary(tmp_path):
    d,q=fixture(tmp_path);original=deepcopy(d)
    t=c.toy(q,d,q['truths'][0],0)
    assert set(t['counts'])=={'SR','CR','MC'} and set(t['globals'])=={'ravel_aux_0_In'}
    assert t==c.toy(q,d,q['truths'][0],0) and t!=c.toy(q,d,q['truths'][0],1)
    assert t['physical_gaussian_measurement']['theta']==pytest.approx(.25+2*t['globals']['ravel_aux_0_In'])
    q['auxiliary_mode']='conditional';t=c.toy(q,d,q['truths'][0],0)
    assert t['counts']['MC']==3 and t['globals']=={'ravel_aux_0_In':0.} and d==original
    assert t['counts']['SR']==c.toy(q,d,q['truths'][0],0)['counts']['SR']


def test_joint_gaussian_law_and_full_means(tmp_path):
    d,q=fixture(tmp_path,mc=False)
    d['auxiliary'].update(names=['theta','other'],observed=['1/4','2'],factor=[['2','0'],['1','3']],eta_bounds=[['-3','3'],['-5','5']])
    for term in d['terms']:term['log_response']=[x+['0'] for x in term['log_response']]
    q['truths'][0]['point']['ravel_aux_1']='-1';r.validate(d);c.validate(q,d)
    got=c.means(d,q['truths'][0]['point']);j=r.mean_jet(d,q['truths'][0]['point'])
    assert list(got.values())==pytest.approx(j['means'])
    t=c.toy(q,d,q['truths'][0],0)
    assert t['physical_gaussian_measurement']['other']==pytest.approx(2+t['globals']['ravel_aux_0_In']+3*t['globals']['ravel_aux_1_In'])
    assert q['truths'][0]['point']['ravel_aux_1']=='-1'


@pytest.mark.parametrize('mutation',[lambda q,d:q.update(critical_q='-1'),lambda q,d:q.update(trials_per_truth=0),lambda q,d:q['truths'][0]['point'].pop('beta'),lambda q,d:q['truths'][0]['point'].update(ravel_aux_0='4'),lambda q,d:q.update(auxiliary_mode='prior'),lambda q,d:q.update(seed=True),lambda q,d:d['template_statistics'].update(kind='fixed_n_categories'),lambda q,d:d['terms'][0].update(shape={}),lambda q,d:d['bins'][0].update(observed=None),lambda q,d:d['parameters'][0].update(fixed=True)])
def test_invalid_or_unsupported_law_refuses(tmp_path,mutation):
    d,q=fixture(tmp_path);mutation(q,d)
    with pytest.raises(ValueError):c.validate(q,d)


def test_full_source_nll_and_mc_exposure(tmp_path):
    d,q=fixture(tmp_path);o=c.toy(q,d,q['truths'][0],0);point=q['truths'][0]['point'];mu=c.means(d,point)
    expected=sum(v-o['counts'][b]*math.log(v)+math.lgamma(o['counts'][b]+1) for b,v in mu.items())+.5*(.5-o['globals']['ravel_aux_0_In'])**2
    assert c.source_nll(d,point,o)==pytest.approx(expected) and mu['MC']==3
    o['counts'].pop('MC')
    with pytest.raises(ValueError):c.source_nll(d,point,o)


def test_failure_denominator_and_cp_edges(tmp_path):
    d,q=fixture(tmp_path,trials=4)
    rows=[{'truth_id':'truth1','ordinal':i,'status':s} for i,s in enumerate(['included','excluded','unresolved','unissued'])]
    s=c.summarize(q,rows)['cohorts'][0]
    assert s['scheduled']==4 and s['identification_interval']==[.25,.75] and s['resolved_only_fraction']==.5
    assert s['conservative_binomial_interval'][0]==pytest.approx(c.clopper_pearson(1,4,.95)[0])
    assert c.clopper_pearson(0,10,.95)[1]==pytest.approx(1-.025**.1)
    assert c.clopper_pearson(10,10,.95)[0]==pytest.approx(.025**.1)
    with pytest.raises(ValueError):c.summarize(q,rows[:3])


def fake(tmp_path,d):
    w=Workspace(d);data=Data(w,d['bins']);obs=Collection([w.var('n_obs_bin'+b['id']) for b in d['bins']]);calls=[]
    def point():return {x:str(Fraction(w.var(x).getVal())) for x in r.coordinates(d)}
    def observation():return {'counts':{b['id']:int(v) for b,v in zip(d['bins'],data.rows[0])},'globals':{'ravel_aux_'+str(i)+'_In':w.var('ravel_aux_'+str(i)+'_In').getVal() for i in range(len(d['auxiliary']['names']))}}
    class NLL:
        def getVal(self):return c.source_nll(d,point(),observation())+37.25 # irrelevant common offset
    class PDF:
        def createNLL(self,data,opts):calls.append(('create_nll',deepcopy(observation())));return NLL()
    mc=NS(GetObservables=lambda:obs,GetNuisanceParameters=lambda:[w.var('beta'),w.var('ravel_aux_0')],GetGlobalObservables=lambda:[w.var('ravel_aux_0_In')],GetPdf=lambda:PDF())
    class Mini:
        def __init__(self,nll):self.nll=nll;calls.append(('fit',deepcopy(observation())))
        def setErrorLevel(self,x):assert x==.5
        def setStrategy(self,x):assert x==1
        def setEps(self,x):assert x==.00001
        def setMaxFunctionCalls(self,x):assert x==50000
        def setMaxIterations(self,x):assert x==10000
        def minimize(self,*args):return 0 # recording facade, not a minimization result
        def hesse(self):return 0
        def save(self):
            floats=Collection([w.var(x) for x in r.coordinates(d) if not w.var(x).isConstant()]);const=Collection([w.var(x) for x in r.coordinates(d) if w.var(x).isConstant()]);size=len(floats)
            return NS(status=lambda:0,covQual=lambda:3,edm=lambda:1e-6,minNll=self.nll.getVal,numInvalidNLL=lambda:0,numStatusHistory=lambda:2,statusLabelHistory=lambda i:['Migrad','Hesse'][i],statusCodeHistory=lambda i:0,floatParsFinal=lambda:floats,constPars=lambda:const,covarianceMatrix=lambda:[[.01 if i==j else 0. for j in range(size)] for i in range(size)])
    class File:
        def __init__(self,path):self.path=Path(path)
        def WriteTObject(self,obj,name):self.path.write_bytes(b'FAKE raw result; no ROOT or fit')
        def Close(self):pass
    class Linked(list):
        def Add(self,x):self.append(x)
    root=NS(RooMinimizer=Mini,TFile=NS(Open=lambda path,*args:File(path)),RooLinkedList=Linked,RooFit=NS(Constrain=lambda x:('constraints',x),GlobalObservables=lambda x:('globals',x)))
    return root,w,mc,data,calls


def test_complete_native_api_same_toy_two_profiles_and_resets(tmp_path):
    d,q=fixture(tmp_path);root,w,mc,data,calls=fake(tmp_path,d);q['truths'][0]['point']['ravel_aux_0']='0'
    out=tmp_path/'native.json';result=c.execute(root,w,mc,data,r.response(d),q,e,out,10.)
    c.validate_delivery(result,r.response(d),q,e)
    assert result['status']=='delivered' and result['top_level_profile_requests']==4
    assert all(x['status']=='included' and x['raw_q']==0 for x in result['rows'])
    assert [x[0] for x in calls]==['create_nll','fit','fit']*2
    assert calls[0][1]==calls[1][1]==calls[2][1] and calls[3][1]==calls[4][1]==calls[5][1]
    assert result['initial_state']==result['final_state'] and result['original_counts']==result['final_counts']
    assert len(list(tmp_path.glob('ravel_calibration_fit_*.root')))==4
    assert json.loads(out.read_bytes())==result


def test_unissued_slots_and_fit_failure_retained(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);root,w,mc,data,calls=fake(tmp_path,d)
    result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'budget.json',.1)
    assert calls==[] and result['summary']['cohorts'][0]['unresolved']==2
    def fail(*args):raise ValueError('supplied fake failure')
    monkeypatch.setattr(root,'RooMinimizer',fail)
    result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'failure.json',10.)
    assert all(x['status']=='unresolved' and x['error']['message']=='supplied fake failure' for x in result['rows'])
    assert result['summary']['cohorts'][0]['identification_interval']==[0,1]


def test_observation_clipping_refuses_without_redraw(tmp_path,monkeypatch):
    d,q=fixture(tmp_path);root,w,mc,data,calls=fake(tmp_path,d)
    original=data.add
    def clip(obs):
        original(obs);data.rows[0][0]=0.
    monkeypatch.setattr(data,'add',clip)
    # Ending original restoration also cannot silently clip; actual helper fails.
    with pytest.raises(ValueError,match='readback'):c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'clip.json',10.)
    rows=json.loads((tmp_path/'clip.json').read_bytes())['rows'];assert rows[0]['status']=='unresolved'


@pytest.mark.parametrize('mutation',[lambda row:row['fixed']['counts'].update(SR=99),lambda row:row['fixed']['state']['mu'].update(value=2.),lambda row:row['fixed']['state']['beta'].update(maximum=999.),lambda row:row['fixed'].update(nll=row['free']['nll']-1),lambda row:row['fixed']['fit'].update(status=1)])
def test_raw_result_adversaries(tmp_path,mutation):
    d,q=fixture(tmp_path);q['truths'][0]['point']['ravel_aux_0']='0';root,w,mc,data,_=fake(tmp_path,d)
    result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'raw.json',10.);row=result['rows'][0];mutation(row)
    with pytest.raises(ValueError):c.classify(q,d,row,result['initial_state'],e)


def test_actual_public_plan_resource_source_and_route(tmp_path):
    from ravel.workflow import science
    cp,cfg,d,q=configuration(tmp_path)
    spec={'mode':'full-auxiliary-calibration','task':{'input':str(cp)},'max_seconds':120}
    assert science.adapter(spec) is a
    with science._validation_scope(tmp_path) as session:
        pins=science.task_inputs(spec,tmp_path,_session=session)
        assert Path(c.__file__) in pins and Path(e.__file__) in pins and cp in pins
    spec['max_seconds']=119
    with pytest.raises(ValueError):science.task_inputs(spec,tmp_path)
    cfg.pop('calibration');cp.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='repeated-sampling'):a.inputs(spec['task'],tmp_path)


def test_real_graph_host_context_and_public_unapproved_plan(tmp_path):
    from ravel.workflow import science,agent_graph as g
    from ravel.workflow.agent_host import AgentHost
    from test_science_capability_integration import specification
    cp,cfg,d,q=configuration(tmp_path);task={'input':str(cp)}
    tp=tmp_path/'task.json';tp.write_text(json.dumps(task));pin={'path':str(tp),'sha256':hashlib.sha256(tp.read_bytes()).hexdigest()}
    gs=a.graph(task,tmp_path,pin);rd=tmp_path/'graph';g.create(rd,gs)
    assert g.execute(rd,AgentHost(api_key='not-used'),workers=1)['complete']
    _,state=g._load(rd);value=g._result(rd,state['nodes']['context']['result'])['result']['value']
    assert value['scheduled_toys']==2 and value['fits_performed']==0 and value['execution_authorized'] is False
    assert value['template_statistics']['kind']=='explicit_independent_poisson_auxiliary'
    bad=deepcopy(gs);bad['nodes'][0]['inputs']=bad['nodes'][0]['inputs'][:-1]
    other=tmp_path/'incomplete-graph';g.create(other,bad)
    assert not g.execute(other,AgentHost(api_key='not-used'),workers=1)['complete']
    spec=specification('full-auxiliary-calibration',task);spec['max_seconds']=120
    sp=tmp_path/'study.json';sp.write_text(json.dumps(spec));study=tmp_path/'ordinary-plan'
    from ravel import cli
    assert cli.main(['plan','--rundir',str(study),'--spec',str(sp)])==0
    science.verify_plan(study,approved=False)
    assert not (study/science.APPROVAL).exists() and json.loads((study/science.PLAN).read_bytes())['max_seconds']==120


def test_failed_native_attempt_preserves_scheduled_slots(tmp_path,monkeypatch):
    cp,cfg,d,q=configuration(tmp_path);out=tmp_path/'attempt';out.mkdir()
    monkeypatch.setattr(n,'run',lambda *args:{'status':'failed','physics_validated':False,'error':{'message':'explicit fake failed native boundary'}})
    result=a.run({'input':str(cp)},tmp_path,out)
    assert result['status']=='failed' and result['calibration_failure_audit']['summary']['cohorts'][0]['scheduled']==2
    assert result['calibration_failure_audit']['summary']['cohorts'][0]['identification_interval']==[0,1]
    assert result['calibration_failure_audit']['scientific_reuse_authorized'] is False


def test_deterministic_constrained_point_and_numerical_margin(tmp_path):
    d,q=fixture(tmp_path,mc=False,trials=1);d['parameters'][1]['fixed']=True
    d['auxiliary'].update(names=[],observed=[],factor=[],eta_bounds=[])
    for t in d['terms']:t['log_response']=[[] for _ in d['bins']]
    q['truths'][0]['point'].pop('ravel_aux_0');r.validate(d);c.validate(q,d)
    root,w,mc,data,calls=fake(tmp_path,d)
    result=c.execute(root,w,mc,data,r.response(d),q,e,tmp_path/'deterministic.json',10.)
    assert result['rows'][0]['fixed']['fit']=={'performed':False,'reason':'no_floating_nuisance'}
    assert len([x for x in calls if x[0]=='fit'])==1 and result['rows'][0]['status']=='included'
    q['critical_q']='0'
    with pytest.raises(ValueError,match='ambiguity'):c.classify(q,d,result['rows'][0],result['initial_state'],e)


def test_native_worker_literal_callback_route_and_existing_optimizer_unchanged():
    tree=ast.parse(n.NATIVE_PROBE)
    assert '--calibrate' in n.NATIVE_PROBE and ".execute(ROOT,w,mc,data,response,cfg['calibration']" in n.NATIVE_PROBE
    assert not any(isinstance(node,ast.Import) and any(x.name=='ROOT' for x in node.names) for node in ast.parse(Path(c.__file__).read_text()).body)
    assert c.execute.__code__.co_names.count('_profile_fit')==1
    assert e.PROFILE_POLICY['max_calls']==50000


def test_real_native_adapter_body_uses_declared_callback_and_preserves_raw_files(tmp_path,monkeypatch):
    """Actual adapter/staging body, recording supplied native boundary only."""
    from test_native_likelihood import VERSION_LOG
    cp,cfg,d,q=configuration(tmp_path);cfg['calibration']['truths'][0]['point']['ravel_aux_0']='0';cp.write_text(json.dumps(cfg))
    out=tmp_path/'ordinary-native-attempt';commands=[]
    monkeypatch.setattr(n,'_check_probe',lambda *args:None)
    monkeypatch.setattr(n,'_check_workspace',lambda *args:[])
    def supplied(command,cwd,env,log,deadline,**kwargs):
        commands.append(list(command));log.parent.mkdir(parents=True,exist_ok=True)
        if '--help' in command:value='Explicit supplied help'
        elif len(command)==1:value=VERSION_LOG
        elif '-o' in command:
            Path(command[command.index('-o')+1]).write_bytes(b'FAKE workspace, never opened by ROOT');value='Explicit supplied build'
        elif '--calibrate' in command:
            root=Path(command[2]).parent
            staged=json.loads(Path(command[2]).read_bytes())
            assert hashlib.sha256((root/'ravel_regional_calibration.py').read_bytes()).hexdigest()==staged['calibration_implementation_sha256']
            facade,w,mc,data,_=fake(root,d)
            delivery=c.execute(facade,w,mc,data,r.response(d),staged['calibration'],e,root/'ravel_calibration_journal.json',float(command[-1]))
            value='RAVEL_NATIVE_PROBE='+json.dumps({'calibration':delivery})
        else:value='RAVEL_NATIVE_PROBE='+json.dumps({'supplied_runtime_or_workspace_identity':'explicit fake, qualification check substituted'})
        log.write_text(value+'\n');return value
    monkeypatch.setattr(n,'_process',supplied)
    result=a.run({'input':str(cp)},tmp_path,out)
    assert result['status']=='passed' and result['inference']['delivery']['top_level_profile_requests']==4
    assert len(commands)==6 and sum('--calibrate' in x for x in commands)==1 and not any('-M' in x for x in commands)
    plan=json.loads((out/'native-command-plan.json').read_bytes())
    assert plan['fit'] is None and plan['calibration_resource_contract']['maximum_top_level_profiles']==4
    assert len([x for x in result['retained_artifacts'] if x['path'].endswith('.root')])==5
    assert (out/'native-calibration.json').is_file()


def test_complete_report_uses_full_denominator(tmp_path):
    from ravel.plotting.science_figures import render
    d,q=fixture(tmp_path);rows=[{'truth_id':'truth1','ordinal':i,'status':'unissued'} for i in range(2)]
    summary=c.summarize(q,rows)
    value=render({'mode':'full-auxiliary-calibration','task':{}},{'inference':{'delivery':{'summary':summary}}},tmp_path,tmp_path)
    assert value['status']=='passed' and value['figures']==[]
    assert 'Unresolved' in (tmp_path/'calibration-report.md').read_text() and json.loads((tmp_path/'calibration-summary.json').read_text())==summary


def test_extremely_small_positive_poisson_mean_is_never_negative():
    # exp(-lambda) rounds to 1 at this admitted positive source mean.
    import random
    assert c.poisson(1e-20,random.Random(917))==0
    assert c.poisson(5e-324,random.Random(917))==0
