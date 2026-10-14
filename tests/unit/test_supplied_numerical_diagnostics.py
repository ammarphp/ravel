"""Complete synthetic contract flows with injected numerical engines only."""
import copy
import hashlib
import json
import math
from pathlib import Path
import types
import numpy as np
import pytest
from ravel.validation import diagnostic_plan as plans
from ravel.validation import likelihood_profile_probe as profile
from ravel.validation import likelihood_candidate_check as candidate
from ravel.validation import likelihood_step_refinement as refine
from diagnostic_plan_fixture import metadata, TOLERANCES, PROFILE_LIMITS, CANDIDATE_LIMITS, REFINE_LIMITS, CRITERIA


def write(root,name,value):
    path=root/(name+'.json');path.write_text(json.dumps(value))
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def snapshot(pins):
    return {pin['path']:{'kind':'file','files':[{'name':'.','sha256':pin['sha256']}]} for pin in pins}


def receipt(root,name,inputs,outputs):
    from ravel.workflow.execution import receipt_digest
    value={'fingerprint':'synthetic-bound-attempt','status':'succeeded','exit_code':0,'input_snapshot':snapshot(inputs),'output_snapshot':snapshot(outputs)}
    value['receipt_sha256']=receipt_digest(value)
    return write(root,name,value)


def contracts(root,n,count,meta):
    root.mkdir(parents=True)
    from ravel.workflow.execution import digest
    from ravel.physics import pyhf_exclude as engine
    data=[2.]+[0.]*n;names=['PAR-'+str(i) for i in range(n)]
    data_hash=hashlib.sha256(json.dumps(data,separators=(',',':')).encode()).hexdigest()
    bounds=[[-2.,2.] for _ in range(n)]
    compiled={k:[] for k in candidate.IDENTITY_KEYS}
    compiled.update(npars=n,nmaindata=1,nauxdata=n,parameter_names=names,parameter_order=names,model_compact_sha256='a'*64,data_compact_sha256=data_hash,observed_and_auxiliary_data=data,bounds=bounds,fixed=[False]*n,inits=[0.]*n)
    layout=[{'pdf':'normal','parameter_index':i,'factor':1.,'sigma':1.} for i in range(n)]
    objective=lambda point:profile.parity.scalar_density([2.],[float(x) for x in point],data,layout)['twice_nll']
    seeds=[[j*.1]*n for j in range(count)]
    probe={'profile_call_index':count,'evaluation_index':n,'data':data,'bounds':bounds,'fixed_coordinates':[],'ordered_starts':seeds,'ordered_starts_compact_sha256':hashlib.sha256(json.dumps(seeds,separators=(',',':')).encode()).hexdigest(),'recorded_best_twice_nll':objective([0.]*n)}
    retained={'conditional_probe':probe,'parameter_names':names,'parameter_order':names,'model_sha256':'a'*64,'data_sha256':data_hash,'source_suggested_fixed':[False]*n,'saved_fixed_vector_references':[{'id':'reference','parameters':[0.]*n,'data':data,'fit_bounds':bounds}]}
    sources={k:write(root,k,value) for k,value in [('published_input',{'id':meta['study_identity']}),('retained_inputs',retained),('compiled_reference',compiled),('runtime_inventory',{'schema_version':1,'files':[]})]}
    parity_input=write(root,'parity',sources)
    cycle={'event':'cycle','checkpoint':False,'sequence':1,'run_id':'RUN-0001','cycle_id':'CYCLE-0001','previous_sha256':'registration','snapshots':[{'path':p['path'],'sha256':p['sha256']} for p in [parity_input,*sources.values()]]}
    cycle['sha256']=digest(cycle);cycle_pin=write(root,'cycle',cycle);previous=cycle;votes=[]
    actors={role:'ACTOR-'+str(i) for i,role in enumerate(('physics_critic','skeptical_verifier','physics_decider'))}
    for i,(role,actor) in enumerate(actors.items()):
        vote={'event':'review','role':role,'actor_id':actor,'verdict':'accept','claim_scope':'fixed_vector_numerics','cycle_id':cycle['cycle_id'],'run_id':cycle['run_id'],'sequence':i+2,'previous_sha256':previous['sha256']}
        vote['sha256']=digest(vote);votes.append(write(root,role,vote));previous=vote
    pp={'plan':{**meta,'review_actors':actors,'probe_selector':{'profile_call_index':count,'evaluation_index':n},'reference_selector':{'id':'reference'},'engine_sha256':hashlib.sha256(Path(engine.__file__).read_bytes()).hexdigest(),'optimizer_maxiter':1000},'schema_version':1,'parity_input':parity_input,'parity_cycle':cycle_pin,'parity_acceptance':votes,'grounding':[],'limits':PROFILE_LIMITS,'tolerances':TOLERANCES,'initial_escalation':{'numpy':False,'jax':False}}
    profile_pin=write(root,'profile',pp)
    identity={'model_sha256':compiled['model_compact_sha256'],'data_sha256':data_hash,'bounds':bounds,'fixed_coordinates':[],'ordered_starts':seeds}
    children={}
    for backend in ('numpy','jax'):
        trials=[{'seed_index':i,'seed':seed,'status':'succeeded','result':{'parameters':seed,'objective':objective(seed),'success':True}} for i,seed in enumerate(seeds)]
        children[backend]={'backend':backend,'compiled_identity':identity,'seed_denominator':count,'trials':trials,'best':trials[0]['result']}
    child_pins={backend:write(root,backend,value) for backend,value in children.items()}
    commands=[{'backend':backend,'returncode':0,'timed_out':False} for backend in children]
    origin={'status':'passed','diagnostic_delivery_complete':True,'comparison_passed':True,'runtime_before_passed':True,'runtime_after_passed':True,'backend_results':children,'backend_commands':commands}
    origin_pin=write(root,'origin',origin);source=write(root,'source',{'files':[]})
    execution=receipt(root,'execution',[profile_pin,source],[origin_pin,*child_pins.values()])
    cp={'plan':{**meta,'candidate_selectors':[[backend,i] for backend in children for i in range(count)],'trial_statuses':{backend:['succeeded']*count for backend in children},'origin_properties':{'comparison_passed':True},'origin_commands':commands},'schema_version':1,'operation':'retained_profile_candidates_no_refit','profile_input':profile_pin,'origin_execution':execution,'origin_result':origin_pin,'origin_numpy':child_pins['numpy'],'origin_jax':child_pins['jax'],'origin_source':source,'grounding':[],'limits':{**CANDIDATE_LIMITS,'evaluator_calls':1000},'tolerances':TOLERANCES}
    candidate_pin=write(root,'candidate',cp)
    return profile_pin,candidate_pin,compiled,probe,layout,objective,source


def fake_engines(monkeypatch,compiled,layout,objective):
    import pyhf
    import jax
    from ravel.physics import published_model
    class Model:
        def expected_actualdata(self,point):return np.asarray([2.])
    monkeypatch.setattr(published_model,'load_published_model',lambda *args:{})
    monkeypatch.setattr(published_model,'compile_published_model',lambda *args:(Model(),None,compiled))
    monkeypatch.setattr(profile.parity,'constraint_layout',lambda *args:layout)
    monkeypatch.setattr(profile.parity,'runtime_files',lambda *args,**kwargs:[])
    monkeypatch.setattr(pyhf,'set_backend',lambda *args,**kwargs:None)
    monkeypatch.setattr(pyhf.infer.mle,'twice_nll',lambda point,*args:np.asarray([objective(point)]))
    monkeypatch.setattr(jax,'devices',lambda:[types.SimpleNamespace(platform='cpu')])
    monkeypatch.setattr(jax,'jit',lambda function:function)
    monkeypatch.setattr(jax,'value_and_grad',lambda function:lambda point:(function(point),2*np.asarray(point)))
    jax.config.update('jax_enable_x64',True)


@pytest.mark.parametrize('mode',['profile','candidate','refinement'])
def test_two_numerical_contracts_and_typed_missing_input(tmp_path,monkeypatch,mode):
    results=[]
    for version,(n,count,format) in enumerate(((2,1,'json'),(3,2,'jsonl'))):
        root=tmp_path/str(version)
        meta=metadata('ANA-000'+str(version+1),count=count,format=format,file='chosen.'+format)
        pp,cp,compiled,probe,layout,objective,source=contracts(root,n,count,meta)
        fake_engines(monkeypatch,compiled,layout,objective)
        if mode=='profile':
            class Process:
                pid=123
                def __init__(self,argv,**kwargs):
                    target=Path(argv[6]);target.mkdir()
                    report={'status':'completed','starts_finished':True,'finite_stationary_best':True,'reference_guard_passed':True,'best':{'objective':objective([0.]*n),'parameters':[0.]*n},'numpy_best_crosscheck':{'stationary':True,'independent_density_residual':0.},'seed_denominator':count}
                    (target/'profile.json').write_text(json.dumps(report))
                def wait(self,**kwargs):return 0
            monkeypatch.setattr(profile.subprocess,'Popen',Process)
            task={'input':pp['path']};adapter=profile
        else:
            task={'input':cp['path']};adapter=candidate
        if mode=='refinement':
            origin=candidate.run(task,root,root/'candidate-output')
            assert origin['status']=='passed',origin.get('error')
            # Plant convergence-only failures in the pinned retained evidence.
            pairs=[]
            for i,row in enumerate(origin['candidates']):
                coordinate=n-1;fd=row['finite_difference'][coordinate]
                fd.update(h_gradient=1e-6-2e-5,half_gradient=1e-6-5e-6)
                row['analytic_gradient'][coordinate]=1e-6
                row['gradient_parity']['coordinates'][coordinate].update(passed=False,masked=False,absolute_residual=4e-6,tolerance=1e-5)
                pairs.append([i,coordinate])
            origin['arithmetic_parity_passed']=False
            op=write(root,'candidate-result',origin)
            execution=receipt(root,'refine-execution',[cp,source],[op])
            doc={'plan':{**meta,'failed_pairs':pairs,'origin_properties':{'arithmetic_parity_passed':False}},'schema_version':1,'operation':'retained_failed_gradient_step_refinement','candidate_input':cp,'origin_execution':execution,'origin_result':op,'origin_source':source,'grounding':[],'limits':{**REFINE_LIMITS,'evaluator_calls':256},'criteria':CRITERIA}
            pin=write(root,'refine',doc);task={'input':pin['path']};adapter=refine
        report=adapter.run(task,root,root/'output')
        assert report['status']=='passed',report.get('error')
        output=root/'output'/meta['output']['file']
        assert json.loads(output.read_text())==report
        assert all(report[k]==meta[k] for k in ('study_identity','parameter_grid','dataset_population'))
        assert report['output_format']==format
        if mode=='candidate':
            assert len(report['candidates'])==2*count
            assert len(report['candidates'][0]['parameters'])==n
            assert report['budget']['calls']==4*n*2*count+3*(2*count+1)
        if mode=='refinement':assert len(report['pairs'])==2*count
        results.append(report)
    assert results[0]['study_identity']!=results[1]['study_identity']
    bad=tmp_path/'missing.json';bad.write_text('{}')
    with pytest.raises(plans.PlanError) as caught:adapter.document({'input':str(bad)},tmp_path)
    assert caught.value.code=='missing_input' and caught.value.field=='plan'


def test_boundary_call_census_is_derived_and_preserves_one_sided_checks(tmp_path,monkeypatch):
    root=tmp_path/'inputs';meta=metadata();pp,cp,compiled,probe,layout,objective,source=contracts(root,2,1,meta)
    rows=[{'parameters':[-2.,0.]}]
    monkeypatch.setattr(candidate,'document',lambda *args:(None,{'limits':{'evaluator_calls':20}},None,None,None,None,None,probe,None,rows))
    bounds=candidate.resource_bounds({},root)
    assert bounds['planned_evaluator_calls']==16


def test_nonfinite_candidate_and_malformed_fixed_coordinates_refuse(tmp_path):
    from test_likelihood_profile_probe import fixture
    retained,compiled=fixture();plan={'probe_selector':{'evaluation_index':1}}
    retained['conditional_probe']['fixed_coordinates'].append([99,0.])
    with pytest.raises(ValueError,match='fixed'):profile.validate_probe(retained,compiled,plan)
