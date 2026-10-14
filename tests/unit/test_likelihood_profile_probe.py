import copy,hashlib,json,math,time
from pathlib import Path
import numpy as np
import pytest
from ravel.validation import likelihood_profile_probe as p
from diagnostic_plan_fixture import TOLERANCES, PROFILE_LIMITS, metadata


def test_budget_escape_is_not_swallowed_as_numerical_failure():
    assert not issubclass(p.ProbeBudget,Exception)
    counter=p.Counter(time.monotonic()+10,1);counter.check('one')
    with pytest.raises(p.ProbeBudget,match='call budget'):counter.check('two')
    assert counter.calls==1 and counter.categories=={'one':1}


def test_wall_budget_refuses_before_an_evaluation():
    counter=p.Counter(time.monotonic()-1,10)
    with pytest.raises(p.ProbeBudget,match='wall budget'):counter.check('not_called')
    assert counter.calls==0


def test_retained_numpy_values_remain_json_and_nonfinite_remains_explicit():
    value={'x':np.array([1.,math.nan]),'n':np.int64(3),'flag':np.bool_(True)}
    encoded=json.dumps(p.json_safe(value),allow_nan=False)
    assert json.loads(encoded)=={'x':[1.,{'nonfinite':'nan'}],'n':3,'flag':True}


def test_fd_all_coordinates_and_step_convergence_are_required():
    rows=[{'index':0,'rule':'fixed','h_gradient':None,'half_gradient':None},
          {'index':1,'rule':'central','h_gradient':0.,'half_gradient':0.}]
    assert p.finite_difference_gradient(rows,TOLERANCES)==([0.,0.],True)
    rows[1]['h_gradient']=.01
    assert p.finite_difference_gradient(rows,TOLERANCES)==([0.,0.],False)
    with pytest.raises(ValueError,match='every'):p.finite_difference_gradient(rows[1:],TOLERANCES)


def fixture():
    seed=[0.]*5;seed[1]=seed[2]=1.;starts=[seed.copy() for _ in range(3)];starts[1][0]=.1;starts[2][0]=-.1
    data=[2.]*5;names=['p'+str(i) for i in range(5)];fixed=[i==1 for i in range(5)]
    compiled=dict(npars=5,nmaindata=2,nauxdata=3,parameter_names=names,parameter_order=names,model_compact_sha256='m',data_compact_sha256='d',observed_and_auxiliary_data=data,fixed=fixed)
    probe=dict(profile_call_index=5,evaluation_index=1,data=data,bounds=[[-5.,5.]]*5,fixed_coordinates=[[1,1.],[2,1.]],ordered_starts=starts,ordered_starts_compact_sha256=hashlib.sha256(json.dumps(starts,separators=(',',':')).encode()).hexdigest())
    retained=dict(conditional_probe=probe,parameter_names=names,parameter_order=names,model_sha256='m',data_sha256='d',source_suggested_fixed=fixed)
    return retained,copy.deepcopy(compiled)


def test_literal_retained_5_coordinate_portfolio_is_not_retuned():
    retained,compiled=fixture();assert p.validate_probe(retained,compiled,{'probe_selector':{'profile_call_index':5,'evaluation_index':1}})==retained['conditional_probe']
    retained['conditional_probe']['ordered_starts'][1][0]+=.00001
    with pytest.raises(ValueError,match='digest'):p.validate_probe(retained,compiled,{'probe_selector':{'profile_call_index':5,'evaluation_index':1}})


@pytest.mark.parametrize('change',['data_order','parameter_order','fixed_mask','fixed_mu','duplicate_start'])
def test_semantic_changes_to_retained_problem_refuse(change):
    retained,compiled=copy.deepcopy(fixture())
    if change=='data_order':retained['conditional_probe']['data'][0]=3.
    elif change=='parameter_order':retained['parameter_order']=list(reversed(retained['parameter_order']))
    elif change=='fixed_mask':retained['source_suggested_fixed'][0]=True
    elif change=='fixed_mu':retained['conditional_probe']['fixed_coordinates'][1][1]=2.
    elif change=='duplicate_start':retained['conditional_probe']['ordered_starts'][1]=retained['conditional_probe']['ordered_starts'][0]
    # Rehashing cannot disguise a duplicate portfolio or change in fixed data.
    starts=retained['conditional_probe']['ordered_starts'];retained['conditional_probe']['ordered_starts_compact_sha256']=hashlib.sha256(json.dumps(starts,separators=(',',':')).encode()).hexdigest()
    with pytest.raises(ValueError):p.validate_probe(retained,compiled,{'probe_selector':{'profile_call_index':5,'evaluation_index':1}})


def input_document(tmp_path):
    from ravel.workflow.execution import digest
    def pinned(name,value):
        path=tmp_path/(name+'.json');path.write_text(json.dumps(value))
        return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    sources={key:pinned(key,{'source':key}) for key in ('published_input','retained_inputs','compiled_reference','runtime_inventory')}
    parity_input=pinned('parity-input',sources)
    cycle=dict(event='cycle',checkpoint=False,sequence=1,run_id='same-run',cycle_id='same',previous_sha256='registration',snapshots=[dict(path=row['path'],sha256=row['sha256']) for row in [parity_input,*sources.values()]])
    cycle['sha256']=digest(cycle);cycle_pin=pinned('cycle',cycle);previous=cycle
    votes=[]
    for index,(role,actor) in enumerate([('physics_critic','/root/critic'),('skeptical_verifier','/root/verifier'),('physics_decider','/root')]):
        vote=dict(event='review',role=role,actor_id=actor,verdict='accept',claim_scope='fixed_vector_numerics',cycle_id='same',run_id='same-run',sequence=index+2,previous_sha256=previous['sha256'])
        vote['sha256']=digest(vote);votes.append(pinned(role,vote));previous=vote
    d=dict(plan={**metadata(file='likelihood_profile_probe.json'),'review_actors':{'physics_critic':'/root/critic','skeptical_verifier':'/root/verifier','physics_decider':'/root'},'probe_selector':{'profile_call_index':5,'evaluation_index':1},'reference_selector':{'evaluation_index':1,'fit_role':'fixed_poi_fit_to_data','data_role':'observed','mu':1.},'engine_sha256':'a'*64,'optimizer_maxiter':1000},schema_version=1,parity_input=parity_input,parity_acceptance=votes,parity_cycle=cycle_pin,grounding=[],limits=PROFILE_LIMITS,tolerances=TOLERANCES,initial_escalation={'numpy':True,'jax':False})
    path=tmp_path/'input.json';path.write_text(json.dumps(d));return path,d


def test_three_genuine_role_assignments_and_same_cycle_prerequisite(tmp_path):
    path,d=input_document(tmp_path);assert p.document({'input':str(path)},tmp_path)[1]==d
    row=d['parity_acceptance'][2];q=Path(row['path']);v=json.loads(q.read_text());v['actor_id']='/root/unassigned';q.write_text(json.dumps(v));row['sha256']=hashlib.sha256(q.read_bytes()).hexdigest();path.write_text(json.dumps(d))
    with pytest.raises(ValueError,match='prerequisite'):p.document({'input':str(path)},tmp_path)


def test_gradient_reference_returns_true_fixed_mask_and_stationary_quadratic():
    rows=p.parity.finite_difference(lambda x:x[0]**2+2*x[1]**2,[0.,1.],[[-2.,2.],[-2.,2.]],[[1,1.]])
    gradient,converged=p.finite_difference_gradient(rows,TOLERANCES)
    assert converged and gradient==[0.,0.] and rows[1]['rule']=='fixed'


@pytest.mark.parametrize('outcome,expected',[('clean',True),('nonzero',False),('timeout',False),('end_custody',False)])
def test_completed_json_requires_clean_actual_child_exit(tmp_path,monkeypatch,outcome,expected):
    """Tiny real children write convincing results, then exit/fail/linger."""
    import subprocess,sys
    path,d=input_document(tmp_path)
    monkeypatch.setattr(p,'document',lambda task,base:(path,d))
    monkeypatch.setattr(p.parity,'_pin',lambda pin,base:(path,{'runtime_inventory':{}}))
    custody_calls=[]
    def check_runtime(inventory):
        custody_calls.append(None)
        if outcome=='end_custody' and len(custody_calls)==2:raise ValueError('synthetic runtime mutation')
        return []
    monkeypatch.setattr(p.parity,'runtime_files',check_runtime)
    real_popen=subprocess.Popen
    processes=[]
    def launch(argv,**kwargs):
        backend,target=argv[5],Path(argv[6])
        result={'status':'completed','starts_finished':True,'finite_stationary_best':True,'reference_guard_passed':True,'best':{'objective':10.},'numpy_best_crosscheck':{'stationary':True,'independent_density_residual':0.}}
        code='from pathlib import Path;import json,sys,time;p=Path(sys.argv[1]);p.mkdir();(p/"profile.json").write_text(sys.argv[2]);'
        code+=('time.sleep(30)' if outcome=='timeout' else 'raise SystemExit('+('7' if outcome=='nonzero' else '0')+')')
        process=real_popen([sys.executable,'-B','-c',code,str(target),json.dumps(result)],**kwargs)
        original_wait=process.wait
        if outcome=='timeout':
            def short_wait(timeout=None):
                # Deterministic file-publication barrier precedes the timeout.
                deadline=time.monotonic()+2
                while not (target/'profile.json').is_file() and time.monotonic()<deadline:time.sleep(.005)
                assert (target/'profile.json').is_file(), 'synthetic completed report never published'
                return original_wait(timeout=min(timeout or 2,.05))
            process.wait=short_wait
        processes.append(process)
        return process
    monkeypatch.setattr(p.subprocess,'Popen',launch)
    report=p.run({'input':str(path)},tmp_path,tmp_path/'out')
    if outcome=='end_custody':assert report['status']=='failed' and report['error']['message']=='synthetic runtime mutation'
    else:assert report['status']=='passed' and report['diagnostic_delivery_complete']
    assert report['comparison_passed'] is expected
    assert report['backend_commands_clean'] is (outcome in ('clean','end_custody'))
    assert all(process.poll() is not None for process in processes)
    assert all(row['result_present'] for row in report['backend_commands'])
    for row in report['backend_commands']:
        header=json.loads((tmp_path/'out'/(row['backend']+'.log')).read_text().splitlines()[0])
        assert header==dict(event='backend_command_planned',backend=row['backend'],argv=row['argv'],timeout_seconds=PROFILE_LIMITS['per_backend_seconds'])
    if outcome=='nonzero':assert all(row['returncode']==7 for row in report['backend_commands'])
    if outcome=='timeout':assert all(row['timed_out'] and row['returncode']!=0 for row in report['backend_commands'])


def test_existing_scalar_optimizer_result_interface_on_tiny_quadratic():
    from ravel.physics import pyhf_exclude as engine
    from scipy.optimize import minimize
    optimizer=engine.robust_optimizer(maxiter=200000,tolerance=TOLERANCES['fit_requested'])
    optimizer.begin_model();engine.robust_optimizer.escalated=True
    try:
        result=optimizer._minimize_once(minimize,lambda x:(x[0]-.3)**2+2*(x[1]-1.)**2,np.asarray([1.,1.]),False,[[-2.,2.],[-2.,2.]],[[1,1.]],{})
        witness=p.json_safe(engine.robust_optimizer._result_witness(result))
        assert witness['success'] and abs(witness['parameters'][0]-.3)<1e-3 and witness['parameters'][1]==1.
        assert witness['objective']<1e-6
        # This exact source API has no module-level result extraction helper.
        assert not hasattr(engine,'_result_witness')
        source=Path(p.__file__).read_text()
        assert 'engine._result_witness(' not in source
    finally:engine.robust_optimizer.escalated=False


@pytest.mark.parametrize('change',['unrelated_parity_input','source_pin_change','unrelated_cycle','broken_chain'])
def test_valid_role_labels_cannot_substitute_unaccepted_parity_source(tmp_path,change):
    path,d=input_document(tmp_path)
    if change=='unrelated_parity_input':
        old=Path(d['parity_input']['path']);new=tmp_path/'other-parity-input.json';new.write_bytes(old.read_bytes());d['parity_input']['path']=str(new)
    elif change=='source_pin_change':
        old=Path(d['parity_input']['path']);content=json.loads(old.read_text());content['compiled_reference']['sha256']='0'*64;old.write_text(json.dumps(content));d['parity_input']['sha256']=hashlib.sha256(old.read_bytes()).hexdigest()
    else:
        row=d['parity_acceptance'][2];vote=json.loads(Path(row['path']).read_text())
        if change=='unrelated_cycle':vote['cycle_id']='different'
        else:vote['previous_sha256']='0'*64
        from ravel.workflow.execution import digest
        vote['sha256']=digest({k:v for k,v in vote.items() if k!='sha256'});Path(row['path']).write_text(json.dumps(vote));row['sha256']=hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError):p.document({'input':str(path)},tmp_path)


def test_known_feasible_reference_rejects_two_agreeing_worse_basins_but_allows_improvement():
    reference=lambda point:10.
    assert p.reference_guard(reference,[0.],10.,10.000001,TOLERANCES)['passed']
    assert p.reference_guard(reference,[0.],10.,9.,TOLERANCES)['passed']
    assert not p.reference_guard(reference,[0.],10.,10.01,TOLERANCES)['passed']
    assert not p.reference_guard(reference,[0.],9.99,10.,TOLERANCES)['passed']


@pytest.mark.parametrize('change',['bounds','data','fixed','point','role'])
def test_retained_reference_must_be_feasible_in_exact_observed_problem(change):
    retained,compiled=fixture();probe=retained['conditional_probe'];probe['recorded_best_twice_nll']=10.
    row=dict(evaluation_index=1,fit_role='fixed_poi_fit_to_data',data_role='observed',mu=1.,data=copy.deepcopy(probe['data']),fit_bounds=copy.deepcopy(probe['bounds']),parameters=copy.deepcopy(probe['ordered_starts'][0]))
    retained['saved_fixed_vector_references']=[row]
    assert p.retained_reference(retained,probe,{'reference_selector':{'evaluation_index':1,'fit_role':'fixed_poi_fit_to_data','data_role':'observed','mu':1.}})==row['parameters']
    if change=='bounds':row['fit_bounds'][0][0]-=1
    elif change=='data':row['data'][0]+=1
    elif change=='fixed':row['parameters'][2]=1.1
    elif change=='point':row['parameters'][0]=6.
    elif change=='role':row['data_role']='saved_asimov'
    with pytest.raises(ValueError):p.retained_reference(retained,probe,{'reference_selector':{'evaluation_index':1,'fit_role':'fixed_poi_fit_to_data','data_role':'observed','mu':1.}})


def test_backend_child_reserves_failure_retention_time(tmp_path,monkeypatch):
    d={'limits':dict(PROFILE_LIMITS),'tolerances':TOLERANCES,'initial_escalation':{'numpy':True,'jax':False},'plan':{}}
    monkeypatch.setattr(p,'document',lambda *args:(tmp_path/'input.json',d))
    seen=[]
    class Stop(Exception):pass
    def counter(deadline,calls):
        seen.append(deadline-time.monotonic());raise Stop
    monkeypatch.setattr(p,'Counter',counter)
    with pytest.raises(Stop):p.child_backend(tmp_path/'input.json','numpy',tmp_path/'out',None)
    assert seen[0]<=PROFILE_LIMITS['per_backend_seconds']-p.RETAIN_SECONDS


def test_backend_child_retains_input_refusal(tmp_path,monkeypatch):
    def refuse(*args):raise ValueError('synthetic refused input')
    monkeypatch.setattr(p,'document',refuse)
    assert p.child_backend(tmp_path/'input.json','numpy',tmp_path/'out',None)==3
    report=json.loads((tmp_path/'out/profile.json').read_text())
    assert report['status']=='failed' and report['error']['message']=='synthetic refused input'
    assert report['seed_denominator'] is None and report['unattempted_seed_indices']==[]
