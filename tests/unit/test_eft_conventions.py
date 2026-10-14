"""Exact algebra/software controls; no model, provider, native or fit jobs."""
import copy
from fractions import Fraction as F
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from ravel.physics import eft_conventions as e
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json, read_json

def pin(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
def save(p,v):atomic_json(p,v);return pin(p)
def convention(axes,basis):
    return {'basis':basis,'axes':axes,'flavour':'supplied_real_flavour','coefficient_unit':'TeV^-2',
            'lambda_unit':'TeV','lambda_gev':'1000','renormalization_scale_gev':'1000','coefficient_kind':'real'}
def fixture(tmp):
    proof=tmp/'proof.txt';proof.parent.mkdir(parents=True,exist_ok=True);proof.write_text('Explicit artificial coordinate algebra; no physical basis equivalence.')
    original=convention(['c1','c2'],'artificial_source');target=convention(['a','b'],'artificial_target')
    row={'ID':'test','name':'signed_response','bins':['one'],'unit':'pb','sm':['5'],
        'linear':[{'axis':'c1','data':['3']},{'axis':'c2','data':['-2']}],
        'quadratic':[{'axes':['c1','c1'],'data':['4']},{'axes':['c1','c2'],'data':['-7']},{'axes':['c2','c2'],'data':['2']}]}
    poly={'schema_version':1,'convention':original,'quadratic':True,'observables':[row],'sources':[pin(proof)]}
    def box(axes,lower,upper):return [{'axis':x,'lower':lower,'upper':upper} for x in axes]
    mapping={'schema_version':1,'source_convention':original,'target_convention':target,
        'direction':'source_coefficients=matrix*target_coefficients','matrix':[['1','2'],['-1','1']],
        'source_domain':box(original['axes'],'-3','3'),'target_domain':box(target['axes'],'-1','1'),
        'rge_policy':'not_applied_same_scale','sources':[pin(proof)]}
    request={'schema_version':1,'source':'Explicit artificial source-only algebra fixture',
        'polynomial':save(tmp/'poly.json',poly),'map':save(tmp/'map.json',mapping),
        'binary64_policy':'nearest_recorded','max_abs_coefficient_rounding':'1/1000000000000'}
    save(tmp/'request.json',request)
    return {'request':str(tmp/'request.json')},request,poly,mapping
def resave(tmp,request,poly,mapping):
    request['polynomial']=save(tmp/'poly.json',poly);request['map']=save(tmp/'map.json',mapping);save(tmp/'request.json',request)
def value(row,axes,point):
    # Direct monomial evaluation independent of matrix/substitution implementation.
    result=F(row['sm'][0])
    for term in row['linear']:result+=F(term['data'][0])*point[axes.index(term['axis'])]
    for term in row['quadratic']:result+=F(term['data'][0])*point[axes.index(term['axes'][0])]*point[axes.index(term['axes'][1])]
    return result

def test_signed_cross_factor_and_complete_coordinate_parity(tmp_path):
    task,_,poly,_=fixture(tmp_path);result=e.compile_transport(task,tmp_path);row=result['observables'][0]
    assert [x['data'][0] for x in row['linear']]==['5/1','4/1']
    assert [x['data'][0] for x in row['quadratic']]==['13/1','19/1','4/1']
    for a,b in ((F(-1),F(1)),(F(0),F(0)),(F(1,3),F(-2,7)),(F(1),F(1))):
        assert value(poly['observables'][0],['c1','c2'],[a+2*b,-a+b])==value(row,['a','b'],[a,b])
    assert result['inverse_matrix']==[['1/3','-2/3'],['1/3','1/3']]
    assert not result['normalization_applied'] and not result['rge_applied']
    assert result['physical_basis_equivalence']=='unknown' and result['physics_validated'] is False

@pytest.mark.parametrize('mutation',['rge','unit','singular','projection','float','omitted','alias','domain','authority','complex'])
def test_closed_scientific_scope_adversaries(tmp_path,mutation):
    task,r,p,m=fixture(tmp_path)
    if mutation=='rge':m['target_convention']['renormalization_scale_gev']='2000'
    if mutation=='unit':m['target_convention']['coefficient_unit']='GeV^-2'
    if mutation=='singular':m['matrix']=[['1','0'],['1','0']]
    if mutation=='projection':m['target_convention']['axes']=['a']
    if mutation=='float':p['observables'][0]['linear'][0]['data']=[.1]
    if mutation=='omitted':p['observables'][0]['quadratic'].pop()
    if mutation=='alias':p['observables'][0]['quadratic'][1]['axes']=['c2','c1']
    if mutation=='domain':m['source_domain'][0]['upper']='1'
    if mutation=='authority':r['physics_validated']=True
    if mutation=='complex':m['target_convention']['coefficient_kind']='complex'
    resave(tmp_path,r,p,m)
    with pytest.raises(ValueError):e.compile_transport(task,tmp_path)

def test_decimal_projection_residual_and_box_bound(tmp_path):
    task,r,p,m=fixture(tmp_path);p['observables'][0]['linear'][0]['data']=['1/10'];resave(tmp_path,r,p,m)
    result=e.compile_transport(task,tmp_path);projected=result['binary64_projection'][0]
    for exact,rounded in zip([result['observables'][0]['sm'],*[x['data'] for x in result['observables'][0]['linear']],*[x['data'] for x in result['observables'][0]['quadratic']]],projected['terms']):
        assert abs(F.from_float(rounded['data'][0])-F(exact[0]))<=F(r['max_abs_coefficient_rounding'])
    assert F(result['rounding'][0]['absolute_response_error_bound_on_declared_box'][0])>0
    r['max_abs_coefficient_rounding']='0';resave(tmp_path,r,p,m)
    with pytest.raises(ValueError,match='rounding'):e.compile_transport(task,tmp_path)

def test_stale_map_or_self_rehashed_result_is_refused(tmp_path):
    task,r,p,m=fixture(tmp_path);result=e.compile_transport(task,tmp_path)
    assert e.verify_result(task,tmp_path,result)
    m['matrix'][0][1]='1';resave(tmp_path,r,p,m)
    with pytest.raises(ValueError,match='current exact source'):e.verify_result(task,tmp_path,result)
    result=e.compile_transport(task,tmp_path);result['physics_validated']=True
    with pytest.raises(ValueError):e.verify_result(task,tmp_path,result)

def specification(task):
    return {'schema_version':2,'mode':'eft-convention-transport','source':'Explicit artificial algebra fixture',
      'assumptions':['Coordinate algebra only; no physical basis equivalence or fit'],'max_seconds':30,'approval_mode':'scripted_yes','task':task,'max_attempts':1,
      'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'p','executor':'e','physics_critic':'c','skeptical_verifier':'v','physics_decider':'d'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
       'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
       'claim_scopes':{e.SCOPE:{'checks':['integrity'],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}

def test_public_ordinary_plan_and_no_reuse_guard(tmp_path):
    from ravel import cli
    task,*_=fixture(tmp_path);spec=specification(task);source=tmp_path/'study.json';save(source,spec)
    assert cli.main(['plan','--rundir',str(tmp_path/'planned'),'--spec',str(source)])==0
    assert science.adapter(spec) is e and science._new_capability(spec)
    assert not (tmp_path/'planned/inputs/science-approval.json').exists()
    spec['review_policy']['policy']['claim_scopes'][e.SCOPE]['actions'].append('reuse');save(source,spec)
    with pytest.raises(ValueError,match='delivery-only'):science.plan(tmp_path/'invalid',source)

def test_real_common_worker_with_mocked_admission_no_process(tmp_path,monkeypatch):
    from ravel.physics import science_worker
    task,*_=fixture(tmp_path);spec=specification(task);rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    plan={'schema_version':2,'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','max_seconds':30,'stage_binding':{'input_snapshot':{}}}
    save(rd/'inputs/science-plan.json',plan);save(rd/'inputs/science.json',spec)
    for module in (science,science_worker):
        monkeypatch.setattr(module,'verify_worker',lambda _:plan);monkeypatch.setattr(module,'execution_spec',lambda _:spec)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
    assert result==read_json(out/'eft-convention-transport.json') and not result['physics_validated']
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status_scope']==e.SCOPE
    assert (out/'eft-convention-report.md').is_file() and 'unknown' in (out/'RESULT.md').read_text()

def test_no_approval_and_mutation_between_read_and_final_identity(tmp_path,monkeypatch):
    task,*_=fixture(tmp_path);out=tmp_path/'run/outputs/attempt-1'
    with pytest.raises(ValueError,match='approved ordinary'):e.run(task,tmp_path,out)
    assert not out.exists()
    rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True);save(rd/'inputs/science-plan.json',{})
    plan={'output_directory':'outputs/attempt-1'};spec=specification(task)
    monkeypatch.setattr(science,'verify_worker',lambda _:plan);monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    original=e.compile_transport
    def raced(*args):
        result=original(*args);p=tmp_path/'poly.json';raw=p.read_bytes();p.unlink();p.write_bytes(raw);return result
    monkeypatch.setattr(e,'compile_transport',raced)
    with pytest.raises(ValueError,match='identity changed'):e.run(task,tmp_path,out)
    assert not (out/'eft-convention-transport.json').exists()

def sf_fixture(tmp):
    here=Path(__file__).resolve().parent;path=here/'test_sfitter_adapter.py'
    if not path.is_file():path=here.parent/'candidate-package/tests/unit/test_sfitter_adapter.py'
    spec=importlib.util.spec_from_file_location('sfitter_control_helpers',path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod,mod.workflow_fixture(tmp)

def sf_transport(tmp,mod,c):
    n=len(mod.BASIS);proof=tmp/'map-proof.txt';proof.write_text('Artificial sign-convention map; no SMEFT equivalence claim.')
    source=convention(mod.BASIS,'artificial_reflected_native_basis');source['flavour']='native_top_22'
    target=copy.deepcopy(source);target['basis']='native_top_D6'
    poly={'schema_version':1,'convention':source,'quadratic':False,'sources':[pin(proof)],
          'observables':[{'ID':'control','name':'engineering_only','bins':['bin1'],'unit':'pb','sm':['1'],
           'linear':[{'axis':x,'data':['-1/10' if j==0 else '0']} for j,x in enumerate(mod.BASIS)],'quadratic':[]}]}
    box=[{'axis':x,'lower':'-1','upper':'1'} for x in mod.BASIS]
    m={'schema_version':1,'source_convention':source,'target_convention':target,
       'direction':'source_coefficients=matrix*target_coefficients','matrix':[[str((-1 if i==0 else 1) if i==j else 0) for j in range(n)] for i in range(n)],
       'source_domain':box,'target_domain':box,'rge_policy':'not_applied_same_scale','sources':[pin(proof)]}
    r={'schema_version':1,'source':'Artificial sign convention control','polynomial':save(tmp/'poly.json',poly),'map':save(tmp/'map.json',m),'binary64_policy':'nearest_recorded','max_abs_coefficient_rounding':'1/1000000000000'}
    rp=save(tmp/'transport-request.json',r);result=e.compile_transport({'request':rp['path']},tmp);op=save(tmp/'transport-result.json',result)
    sem=read_json(Path(c['semantic_manifest']['path']));sem['eft']['source_basis']=source['basis'];sem['eft']['conversion']='preconverted_source_bound_card'
    sp=save(Path(c['semantic_manifest']['path']),sem)
    return rp,op,sp

def test_complete_specialist_convention_to_native_card_and_changed_result(tmp_path):
    mod,(request,docs,c)=sf_fixture(tmp_path);rp,op,sp=sf_transport(tmp_path,mod,c)
    docs['conventions']['payload']={'semantic_manifest':sp,'transport_request':rp,'transport_result':op}
    docs['datacard']['payload']['semantic_manifest']=sp
    for phase in mod.w.PHASES:request['handoffs'][phase]=save(tmp_path/(phase+'.json'),docs[phase])
    result=mod.w.context(request,tmp_path)
    assert result['native_input']['datacard']==c['datacard'] and not result['execution_authorized']
    assert Path(rp['path']) in [Path(p['path']) for p in mod.w.input_pins(request,tmp_path)]
    result_path=Path(op['path']);changed=read_json(result_path);changed['observables'][0]['linear'][0]['data']=['999/1']
    docs['conventions']['payload']['transport_result']=save(result_path,changed)
    request['handoffs']['conventions']=save(tmp_path/'conventions.json',docs['conventions'])
    with pytest.raises(ValueError,match='current exact source'):mod.w.context(request,tmp_path)

def test_host_handoff_requires_map_polynomial_and_evidence_as_inputs(tmp_path):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    mod,(request,docs,c)=sf_fixture(tmp_path);rp,op,sp=sf_transport(tmp_path,mod,c)
    for phase in ('extraction','sm_template','parameterization'):
        request['handoffs'][phase]=save(tmp_path/(phase+'.json'),docs[phase])
    docs['conventions']['payload']={'semantic_manifest':sp,'transport_request':rp,'transport_result':op}
    request_pin=save(tmp_path/'workflow.json',request);handoff_pin=save(tmp_path/'conventions.json',docs['conventions'])
    pins=[request_pin,handoff_pin,*mod.w.input_pins(request,tmp_path),*list(mod.w._refs(docs['conventions']))]
    inputs=[{'id':'p'+str(i),**p} for i,p in enumerate(pins)]
    node={'id':'handoff','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'sfitter-handoff',
          'parameters':{'request_input':'p0','handoff_input':'p1'},'max_attempts':1}
    host=AgentHost(api_key='control-only',bound_roots=[str(tmp_path),str(mod.UP)])
    control=SimpleNamespace(cancelled=lambda:False,call=lambda action,kind,request,operation:operation())
    with pytest.raises(HostFailure,match='custody'):host.execute(node,{'request_id':'control','packet':None,'input_artifacts':inputs},control)
    for p in e.inputs({'request':rp['path']},tmp_path):
        if str(p) not in {x['path'] for x in inputs}:inputs.append({'id':'extra'+str(len(inputs)),**pin(p)})
    node['inputs']=inputs
    assert host.execute(node,{'request_id':'control','packet':None,'input_artifacts':inputs},control)['value']['accepted_as']=='source_bound_draft'
