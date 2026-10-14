"""Pure domain algorithms and actual existing Graph/journal controls; zero jobs."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import sfitter_review_protocol as p, sfitter_workflow as w
from ravel.workflow import scientific_judgment as j, agent_host, agent_graph, execution, physics_review as review
from ravel.workflow.state_io import read_json
from test_sfitter_adapter import workflow_fixture, save, pin, BASIS, Array, UP
from test_physics_review import run, opened, finding
# A vote counts only through an observed, separated transport. The accounted fake transport is a
# software control, so tests of what follows a counted vote request the shared observed-boundary
# fixture; the control refusal itself is covered where the fixture is not requested.
from test_scientific_judgment import observed_role_boundary
class FakeHost:
    identity = {"fixture": "accounted fake transport; zero native/model/network calls"}
    def __init__(self, *, verdict='accept', proposal=None, proposal_verdict='adequate_for_bounded_test', mutate=None, closes=()):
        self.verdict, self.proposal, self.pverdict, self.mutate = verdict, proposal, proposal_verdict, mutate
        self.closes=list(closes)
    def execute(self,node,request,control):
        packet=Path(node['packet']['path']); manifest=read_json(packet/'manifest.json')
        subject=next(a['sha256'] for a in manifest['artifacts'] if a['id']=='judgment_request')
        contract=read_json(next(packet/a['path'] for a in manifest['artifacts'] if a['id']=='judgment_request'))
        case=read_json(contract['case_pin']['path'])
        audit={'case_sha256':execution.digest(case),'nodes':[{'id':n['id'],'decision':'supported','reason':'Synthetic evidence review only',
            'assumptions':[{'disposition':'accepted','reason':'Synthetic domain check'} for a in n['assumptions']]} for n in case['nodes']],
            'edges':[{'parent':e['parent'],'child':e['child'],'decision':'supported','reason':'Synthetic located link'} for e in case['edges']]}
        value={'schema_version':1,'kind':'scientific_review','subject_sha256':subject,'verdict':self.verdict,'summary':'Synthetic finite source control only',
            'findings':[finding()] if self.verdict=='send_back' else [],'closes':self.closes,'claim_scope':contract['claim_scope'] if self.verdict=='accept' else None,
            'audit':audit,'proposal':None,'proposal_verdict':None}
        if contract['phase']=='improvement':
            value.update(kind='scientific_repair_proposal',verdict=None,claim_scope=None,findings=[],proposal=deepcopy(self.proposal))
        if contract['phase']=='repair_design':
            value.update(kind='scientific_repair_design_review',verdict=None,claim_scope=None,findings=[],proposal_verdict=self.pverdict)
        if self.mutate:self.mutate(value,contract)
        agent_host.validate_public_result(value,node['parameters']['output_schema'])
        result={'kind':'model_result','value':value,'transport':{'request_id':request['request_id'],'execution_mode':'responses_http_loopback_control'},
                'isolation':{'fresh_request':True,'parent_transcript_supplied':False},'physics_validated':False,'execution_authorized':False}
        return control.call('synthetic_response','model',{'request_id':request['request_id']},lambda:result,output_tokens=16)

def ref(pin_, location=''): return {'artifact':pin_,'location':location}
def concern(report,name): return next(c for c in report['concerns'] if c['id']==name)

def setup(tmp, *, all_phases=True):
    tmp.mkdir(exist_ok=True)
    wf,docs,_=workflow_fixture(tmp)
    for phase in (w.PHASES if all_phases else ('extraction',)):
        wf['handoffs'][phase]=save(tmp/(phase+'.json'),docs[phase])
    wp=save(tmp/'workflow.json',wf)
    source=save(tmp/'primary.json',{'value':1,'criterion':'Explicit artificial source-control criterion',
        'independence':'Explicit source-control independent components','acceptance':'total','model':'Source control only','limits':[]})
    regime=save(tmp/'regime.json',{'schema_version':1,'observables':[{'ID':'control','acceptance':'total','source':ref(source,'/acceptance')}],'sources':[source]})
    located=save(tmp/'located.json',{'rows':[{'observable':'control','bin':'bin1','source':ref(source,'/value'),'confidence':'strong'}]})
    request={'schema_version':1,'id':'domain_control','workflow':wp,'stage':'datacard' if all_phases else 'extraction','regime':regime,
        'checks':[{'id':'trace','concern':'traceability','observables':['control'],'method':'traceability','data':ref(located)}],
        'required_concerns':['traceability'],'check_mapping':{'traceability':['agreement']},'claim_scope':'reproduction'}
    return request,source,wf,docs

def add(tmp,request,concern_,method,data):
    cp=save(tmp/(method+'-data.json'),data)
    request['checks'].append({'id':method,'concern':concern_,'observables':['control'],'method':method,'data':ref(cp)})
    return cp

def criterion(source):return {'absolute':1e-12,'relative':0.,'justification':ref(source,'/criterion')}

def test_whole_context_preserves_warnings_and_no_authority(tmp_path):
    request,_,_,_=setup(tmp_path);report=p.context(request,tmp_path)
    assert len(report['concerns'])==9 and concern(report,'traceability')['status']=='pass'
    assert len(report['warnings'])==8 and not report['execution_authorized'] and not report['physics_validated']
    assert report['old_votes_carried']==[] and report['upstream_commit']==w.sfitter_native.COMMIT

@pytest.mark.parametrize('kind',['unknown_confidence','missing_bin','wrong_method','partial_regime','stale_source','false_authority'])
def test_context_adversaries(tmp_path,kind):
    request,source,_,_=setup(tmp_path)
    if kind=='unknown_confidence':
        cp=request['checks'][0]['data']['artifact'];data=read_json(cp['path']);data['rows'][0]['confidence']='unknown';request['checks'][0]['data']=ref(save(Path(cp['path']),data))
        assert concern(p.context(request,tmp_path),'traceability')['status']=='inconclusive';return
    if kind=='missing_bin':
        cp=request['checks'][0]['data']['artifact'];request['checks'][0]['data']=ref(save(Path(cp['path']),{'rows':[]}))
        assert concern(p.context(request,tmp_path),'traceability')['status']=='inconclusive';return
    if kind=='wrong_method':request['checks'][0]['method']='quadrature'
    if kind=='partial_regime':request['regime']=save(tmp_path/'regime.json',{'schema_version':1,'observables':[],'sources':[source]})
    if kind=='stale_source':Path(source['path']).write_text('changed')
    if kind=='false_authority':request['execution_authorized']=True
    with pytest.raises((ValueError,KeyError)):p.context(request,tmp_path)

def test_quadrature_recomputed_against_source_bound_criterion(tmp_path):
    request,source,_,_=setup(tmp_path);raw=save(tmp_path/'errors.json',{'a':[3.],'b':[4.],'total':[5.]})
    data={'components':[ref(raw,'/a'),ref(raw,'/b')],'total':ref(raw,'/total'),'criterion':criterion(source),'independence':ref(source,'/independence')}
    cp=add(tmp_path,request,'uncertainty_roundtrip','quadrature',data)
    result=concern(p.context(request,tmp_path),'uncertainty_roundtrip')['checks'][0]['recomputation']
    assert result['computed']==[5.] and result['residual']==[0.]
    data['total']=ref(save(tmp_path/'bad-total.json',[7.]));request['checks'][-1]['data']=ref(save(Path(cp['path']),data))
    assert concern(p.context(request,tmp_path),'uncertainty_roundtrip')['status']=='fail'

def test_unknown_regime_and_normalized_luminosity_remain_unresolved(tmp_path):
    request,source,wf,_=setup(tmp_path)
    row={**{k:wf['target']['observables'][0][k] for k in ('ID','representation','normalization','unit')},'acceptance':'unknown','luminosity_included':False,'source':ref(source,'/acceptance')}
    add(tmp_path,request,'observable_semantics','regime_consistency',{'rows':[row]})
    assert concern(p.context(request,tmp_path),'observable_semantics')['status']=='inconclusive'
    target=deepcopy(wf['target']);target['observables'][0].update(bins=['a','b'],normalization='normalized')
    row.update(acceptance='total',normalization='normalized',luminosity_included=True)
    assert p._compute('regime_consistency',{'rows':[row]},target,['control'],tmp_path,{})[0]=='fail'

def test_baseline_actual_handoff_and_independent_source(tmp_path):
    request,source,_,_=setup(tmp_path);actual=save(tmp_path/'sm.json',[1.]);reference=save(tmp_path/'reference.json',[1.])
    data={'actual':ref(actual),'reference':ref(reference),'criterion':criterion(source)};cp=add(tmp_path,request,'sm_baseline','vector_agreement',data)
    assert concern(p.context(request,tmp_path),'sm_baseline')['status']=='pass'
    data['reference']=ref(actual);request['checks'][-1]['data']=ref(save(Path(cp['path']),data))
    with pytest.raises(ValueError,match='separate reference'):p.context(request,tmp_path)
    data.update(actual=ref(save(tmp_path/'wrong-sm.json',[2.])),reference=ref(reference));request['checks'][-1]['data']=ref(save(Path(cp['path']),data))
    with pytest.raises(ValueError,match='actual handed-off'):p.context(request,tmp_path)

def test_exact_normalized_signed_polynomial_no_taylor_or_universal_r2(tmp_path):
    _,source,wf,_=setup(tmp_path);target=deepcopy(wf['target'])
    target['observables'][0].update(bins=['a','b'],normalization='normalized');target['eft'].update(quadratic=True,mixed_pairs=[[BASIS[0],BASIS[1]]])
    linear={b:[0.,0.] for b in BASIS};linear[BASIS[0]]=[1.,-1.]
    square={b:[0.,0.] for b in BASIS};square[BASIS[1]]=[.5,.25]
    mixed={BASIS[0]+'x'+BASIS[1]:[-.75,.5]};x=[1.,2.]+[0.]*20
    raw=[2.+1.+2.-1.5,3.-1.+1.+1.];norm=raw[0]*2+raw[1]
    data={'observable':'control','offset':[2.,3.],'linear':linear,'square':square,'mixed':mixed,'points':[{'coefficients':x,'observed':[v/norm for v in raw]}],'bin_widths':[2.,1.],'criterion':criterion(source)}
    status,out=p._compute('polynomial',data,target,['control'],tmp_path,{})
    assert status=='pass' and out['points'][0]['normalization']==11. and 'Taylor' in out['normalization']
    data['points'][0]['observed'][0]+=0.1
    assert p._compute('polynomial',data,target,['control'],tmp_path,{})[0]=='fail'

def test_missing_native_roundtrip_is_prescribed_not_pass(tmp_path):
    request,_,_,_=setup(tmp_path);add(tmp_path,request,'datacard_roundtrip','datacard_composition',{})
    c=concern(p.context(request,tmp_path),'datacard_roundtrip')
    assert c['status']=='inconclusive' and c['checks'][0]['recomputation']['structural_composition']=='pass'

@pytest.mark.parametrize('kind',['clean','unexpected','unmapped','nonzero','qcd_labeled_eft'])
def test_generated_coupling_and_zeroing_census(tmp_path,kind):
    request,source,wf,_=setup(tmp_path);matrix=tmp_path/'matrix.f';matrix.write_text('C GC_900 comment only\n      AMP=GC_1+GC_2 ! GC_901\n')
    mapping={'GC_1':{'kind':'qcd','operators':[]},'GC_2':{'kind':'eft','operators':[BASIS[0]]}};allowed=[BASIS[0]];values={'DIM6a':0.,'DIM6b':0.}
    if kind=='unexpected':allowed=[]
    if kind=='unmapped':mapping.pop('GC_2')
    if kind=='nonzero':values['DIM6b']=1.
    if kind=='qcd_labeled_eft':mapping['GC_2']['kind']='qcd'
    card=tmp_path/'param_card.dat';card.write_text('BLOCK DIM6\n 1 '+str(values['DIM6a'])+'\n 2 '+str(values['DIM6b'])+'\n')
    mp=save(tmp_path/'map.json',mapping);zp=save(tmp_path/'zeroing.json',{'model_source':wf['target']['model_source'],'stage':'pre_activation','provenance':'constructed_input','parameter_card':pin(card),'execution':None,
        'dim6_parameters':list(values),'parameter_locations':{'DIM6a':{'block':'DIM6','indices':[1]},'DIM6b':{'block':'DIM6','indices':[2]}},
        'parameter_operators':{'DIM6a':[BASIS[0]],'DIM6b':[BASIS[1]]},'active_values':{}})
    add(tmp_path,request,'coupling_contamination','coupling_census',{'matrix_sources':[pin(matrix)],'coupling_map':ref(mp),'allowed_operators':allowed,'zeroing_record':ref(zp)})
    if kind=='qcd_labeled_eft':
        with pytest.raises(ValueError,match='coupling meaning'):p.context(request,tmp_path)
    else:
        c=concern(p.context(request,tmp_path),'coupling_contamination');assert c['status']=={'clean':'inconclusive','unexpected':'fail','unmapped':'inconclusive','nonzero':'fail'}[kind]
        assert c['checks'][0]['recomputation']['couplings']==['GC_1','GC_2']

def test_physical_theory_source_doublecount_not_name_based(tmp_path):
    request,source,_,_=setup(tmp_path)
    def row(channel,name,phys):return {'physical_source':phys,'channel':channel,'name':name,'observables':['control'],'source':ref(source,'/criterion'),'included_independently':True}
    data={'rows':[row('experimental','unfolding','shared_scale'),row('theory','scale_variation','shared_scale')]};cp=add(tmp_path,request,'theory_doublecount','uncertainty_inventory',data)
    assert concern(p.context(request,tmp_path),'theory_doublecount')['status']=='fail'
    data['rows'][1].update(name='unfolding',physical_source='independent_PDF');request['checks'][-1]['data']=ref(save(Path(cp['path']),data))
    assert concern(p.context(request,tmp_path),'theory_doublecount')['status']=='pass'

@pytest.fixture
def cycle(run):opened(run);return run[0]

def prepared(cycle,tmp_path,role='critic',request=None):
    if request is None:request,*_=setup(tmp_path/'domain')
    rp=save(tmp_path/('request-'+role+'.json'),request);actor={'critic':'critic','verifier':'skeptic','synthesizer':'physicist','improver':'improver'}[role]
    return p.prepare_role(cycle,rp,tmp_path/('prepared-'+role),role=role,actor_id=actor,model='control-only',reasoning_effort='high',max_output_tokens=1024,max_wall_seconds=20,allow_control=True)

def test_actual_role_chain_original_sources_and_later_drift(cycle,tmp_path,observed_role_boundary):
    request,source,*_=setup(tmp_path/'domain')
    for role in ('critic','verifier','synthesizer'):
        b=prepared(cycle,tmp_path,role,request);j.execute_role(b['judgment'],FakeHost());p.consume(cycle,b,allow_control=True)
    assert review.status(cycle)['state']=='accepted' and review.gate_errors(cycle,'delivery')==[]
    assert any(source in r.get('supporting_artifacts',[]) for r in review._view(*review._read(cycle))['reviews'])
    Path(source['path']).write_text('later scientific reference drift')
    assert review.gate_errors(cycle,'delivery') and review.gate_errors(cycle,'reuse')

def test_control_transport_vote_never_enters_the_journal(cycle,tmp_path):
    request,*_=setup(tmp_path/'domain')
    for verdict in ('accept','send_back'):
        b=prepared(cycle,tmp_path/verdict,request=request);j.execute_role(b['judgment'],FakeHost(verdict=verdict))
        for options in ({},{'allow_control':True}):
            with pytest.raises(ValueError,match='self-attested review is advisory|control transport is not scientific review'):
                p.consume(cycle,b,**options)
    assert review.status(cycle)['state']=='awaiting_review' and len(review._read(cycle)[1])==1

def test_unknown_required_check_cannot_be_accepted_by_model_label(cycle,tmp_path,observed_role_boundary):
    request,source,*_=setup(tmp_path/'domain');request['required_concerns'].append('coupling_contamination');request['check_mapping']['coupling_contamination']=['agreement']
    b=prepared(cycle,tmp_path,request=request);j.execute_role(b['judgment'],FakeHost())
    with pytest.raises(ValueError,match='unresolved'):p.consume(cycle,b,allow_control=True)
    assert review.status(cycle)['state']=='awaiting_review'

def test_actual_sendback_rewinds_phase_without_mutation_or_authority(cycle,tmp_path,observed_role_boundary):
    request,_,wf,_=setup(tmp_path/'domain');before=Path(request['workflow']['path']).read_bytes()
    b=prepared(cycle,tmp_path,request=request);j.execute_role(b['judgment'],FakeHost(verdict='send_back'));p.consume(cycle,b,allow_control=True)
    out=p.rework(cycle,b,tmp_path/'rework',allow_control=True)
    assert out['owner_phase']=='extraction' and out['retained_handoffs']==[] and len(out['invalidated_handoffs'])==5
    assert out['old_votes_carried']==[] and not out['execution_authorized'] and Path(request['workflow']['path']).read_bytes()==before
    assert read_json(out['phase_graph']['path'])['nodes'][0]['role']=='designer' and review.status(cycle)['state']=='send_back'
    with pytest.raises(FileExistsError):p.rework(cycle,b,tmp_path/'rework',allow_control=True)

def test_unrecorded_sendback_cannot_rework(cycle,tmp_path,observed_role_boundary):
    b=prepared(cycle,tmp_path);j.execute_role(b['judgment'],FakeHost(verdict='send_back'))
    with pytest.raises(ValueError,match='current actual send-back'):p.rework(cycle,b,tmp_path/'no-work',allow_control=True)
    assert not (tmp_path/'no-work').exists()

def test_changed_artifact_refuses_freshness(cycle,tmp_path):
    request,source,*_=setup(tmp_path/'domain');b=prepared(cycle,tmp_path,request=request);j.execute_role(b['judgment'],FakeHost())
    Path(source['path']).write_text('changed before review consumption')
    with pytest.raises(ValueError):p.consume(cycle,b,allow_control=True)

def test_host_context_explicit_dependencies_and_blinded_refusal(tmp_path):
    request,_,_,_=setup(tmp_path/'domain');rp=save(tmp_path/'request.json',request);report=p.context(request,tmp_path)
    op=save(tmp_path/'operation.json',{'operation':'context','rundir':None,'request':rp,'arguments':{}})
    pins={str(i):(Path(q['path']),q['sha256']) for i,q in enumerate([op,rp,*report['inputs']])}
    assert p.host_tool({'request_input':'0'},pins)==report
    pins.pop(str(len(pins)-1))
    with pytest.raises(ValueError,match='explicitly presented'):p.host_tool({'request_input':'0'},pins)
    host=agent_host.AgentHost(api_key='control-only');node={'role':'critic','action':'sfitter-review-protocol','parameters':{'request_input':'0'}}
    with pytest.raises(agent_host.HostFailure,match='separate caller'):host._tool(node,{},None,pins)

def test_cli_alias_and_context_no_process(tmp_path,capsys):
    from ravel import cli
    request,_,_,_=setup(tmp_path);rp=save(tmp_path/'request.json',request)
    assert cli.FOCUSED_COMMANDS['sfitter-review'][0]=='workflow.sfitter_review_protocol'
    assert p.main(['context','--request',rp['path']])==0 and json.loads(capsys.readouterr().out)['kind']=='sfitter_domain_review'

@pytest.mark.parametrize('kind',['exact','changed_coefficient','foreign_output','failed_stage'])
def test_actual_native_parser_read_only_branch_fake_execution_only(tmp_path,monkeypatch,kind):
    """Actual tensor exporter/parser path; ordinary admission/stage mocked explicitly."""
    from ravel.workflow import science
    request,_,wf,docs=setup(tmp_path/'domain');base=tmp_path/'domain'
    root=tmp_path/'synthetic-ordinary';out=root/'outputs/attempt';native=out/'native';native.mkdir(parents=True)
    (root/'inputs').mkdir();plan={'output_directory':'outputs/attempt'};save(root/'inputs/science-plan.json',plan)
    config_path=base/'config.json';spec={'mode':'sfitter-native-fit','task':{'config':str(config_path)}}
    c=read_json(config_path);origin={'path':str(UP/'sfitter/sfitter/likelihood/full_likelihood.py'),'sha256':pin(UP/'sfitter/sfitter/likelihood/full_likelihood.py')['sha256']}
    card=read_json(c['datacard']['path']);width=22*23;coeff=[0.]*width
    for term in card['predictions'][0]['modifiers']:coeff[BASIS.index(term['name'])*23+22]=term['data'][0]
    if kind=='changed_coefficient':coeff[22]+=1.
    exporter=w.sfitter_native.sfitter_results
    def arr(shape,values=None):return exporter.array(Array(shape,values))
    tensors={k:arr(shape) for k,shape in {'smeft_coeffs':[1,22,23],'smeft_offset':[1],'measurements':[1],'err_theo':[1],'err_gauss':[1],'corr':[1,1],'corr_inv':[1,1],'bin_widths':[1],'norm_indices':[1],'norm_start':[1]}.items()}
    tensors['smeft_coeffs']=arr([1,22,23],coeff);tensors['bin_widths']=arr([1],[0.])
    initialized={'schema_version':1,'kind':'sfitter_initialized_state','parameters':BASIS,'dims_nuisance':0,'native_origin':origin,
        'native_tensors':tensors,'native_scalars':{'corr_shrinkage':exporter.scalar(0.),'syst_rho':exporter.scalar(.99),'n_blocks_substituted':0},
        'tensor_meanings':exporter.INITIALIZED_MEANINGS.copy(),'physics_validated':False,'independent_consistency':'unknown'}
    ip=save(native/'initialized-state.json',initialized)
    raw={'basis':BASIS,'source_files':{origin['path']:origin['sha256']},'runtime_assets':{},'config':c,'output':str(native),'exporter_sha256':pin(Path(exporter.__file__))['sha256'],'driver_sha256':'0'*64}
    np=save(native/'request.json',raw)
    runtime={'schema_version':1,'versions':c['runtime']['versions'],'device':'cpu','precision':'double','imports':{'sfitter.likelihood.full_likelihood':origin},
        'source_files':raw['source_files'],'runtime_assets':{},'randomness':'Synthetic source control only','physics_validated':False}
    rp=save(native/'runtime.json',runtime);record={'attempt_id':'fake-only','attempt_record':'record.json'};save(root/'record.json',record)
    monkeypatch.setattr(science,'verify_plan',lambda _:plan);monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    monkeypatch.setattr(p.execution,'stage_errors',lambda *_:['failed synthetic attempt'] if kind=='failed_stage' else [])
    monkeypatch.setattr(p.execution,'load_execution',lambda _:{'stages':{'science':record}})
    if kind=='foreign_output':ip=save(tmp_path/'foreign-state.json',initialized)
    data={'rundir':str(root),'initialized_state':ip,'native_request':np,'runtime':rp}
    if kind in ('foreign_output','failed_stage'):
        with pytest.raises(ValueError):p._native_roundtrip(data,wf,base,{})
    else:
        status,result=p._native_roundtrip(data,wf,base,{})
        assert status==('pass' if kind=='exact' else 'fail') and result['native_state']['independent_consistency']=='unknown'

def test_native_regime_triggers_and_same_scale_policy(tmp_path):
    request,_,_,_=setup(tmp_path);report=p.context(request,tmp_path)
    assert 'total_rate_SM_baseline_no_efficiency_inference' in report['regime_triggers'][0]['prescribed_probes']
    assert report['regime_triggers'][-1]['eft_truncation']=='linear_only' and 'no implicit RGE' in report['regime_triggers'][-1]['scale_policy']

def test_non_extraction_owner_retains_unaffected_handoff_prefix(cycle,tmp_path,observed_role_boundary):
    request,source,*_=setup(tmp_path/'domain')
    add(tmp_path/'domain',request,'sm_baseline','vector_agreement',{'actual':ref(save(tmp_path/'actual-sm.json',[1.])),
        'reference':ref(save(tmp_path/'independent-sm.json',[1.])),'criterion':criterion(source)})
    request['required_concerns']=['sm_baseline'];request['check_mapping']={'sm_baseline':['agreement']}
    b=prepared(cycle,tmp_path,request=request);j.execute_role(b['judgment'],FakeHost(verdict='send_back'));p.consume(cycle,b,allow_control=True)
    out=p.rework(cycle,b,tmp_path/'sm-rework',allow_control=True)
    assert out['owner_phase']=='sm_template' and out['retained_handoffs']==['extraction']
    assert out['invalidated_handoffs']==['sm_template','parameterization','conventions','datacard']
    assert read_json(out['workflow']['path'])['handoffs']['extraction']==read_json(request['workflow']['path'])['handoffs']['extraction']

def test_exhausted_original_redo_yields_fresh_study_draft_only(cycle,tmp_path,observed_role_boundary):
    request,_,*_=setup(tmp_path/'domain');b=prepared(cycle,tmp_path,request=request)
    j.execute_role(b['judgment'],FakeHost(verdict='send_back'));p.consume(cycle,b,allow_control=True)
    original=j._live
    def exhausted(root, **kwargs):
        r,reg,events,view=original(root, **kwargs);return r,reg,events,{**view,'redos_remaining':0}
    # Only derived-bound fixture is mocked; no policy or journal mutation.
    from unittest.mock import patch
    with patch.object(j,'_live',exhausted):out=p.rework(cycle,b,tmp_path/'fresh-study',allow_control=True)
    assert out['admission_route']=='fresh_study_required_original_redo_bound_exhausted' and not out['execution_authorized']

def test_revised_artifact_requires_new_report_and_case(cycle,tmp_path):
    request,source,*_=setup(tmp_path/'domain');b=prepared(cycle,tmp_path,request=request)
    j.execute_role(b['judgment'],FakeHost());old_report=read_json(b['report']['path'])
    changed=save(tmp_path/'revised-primary.json',{'value':2,'criterion':'Fresh independent artificial criterion','acceptance':'total'})
    raw=read_json(request['checks'][0]['data']['artifact']['path']);raw['rows'][0]['source']=ref(changed,'/value')
    request['checks'][0]['data']=ref(save(tmp_path/'revised-location.json',raw))
    fresh=p.context(request,tmp_path)
    assert fresh['request_sha256']!=old_report['request_sha256'] and fresh['old_votes_carried']==[]
    rp=save(tmp_path/'new-request.json',request);altered={**b,'request':rp}
    with pytest.raises(ValueError,match='changed'):p.verify_binding(altered,allow_control=True)

@pytest.mark.parametrize('kind',['active_allowed','inactive_nonzero','wrong_active_value','construction_only','outside_scanned_axis','partial_DIM6','wrong_output'])
def test_explicit_final_card_activation_semantics(tmp_path,monkeypatch,kind):
    _,_,wf,_=setup(tmp_path/'domain');root=tmp_path/'fake-native';out=root/'outputs';out.mkdir(parents=True)
    values=[2.,0.] if kind!='inactive_nonzero' else [2.,1.]
    card=out/'param_card.dat';card.write_text('BLOCK DIM6\n 1 '+str(values[0])+'\n 2 '+str(values[1])+'\n')
    record={'attempt_record':'record.json','outputs':['outputs'],'status':'succeeded','attempt_id':'fake-no-native-call'};rp=save(root/'record.json',record)
    monkeypatch.setattr(p.execution,'stage_errors',lambda *_:[]);monkeypatch.setattr(p.execution,'load_execution',lambda _:{'stages':{'generation':record}})
    data={'model_source':wf['target']['model_source'],'stage':'final_scan','provenance':'returned_parameter_card','parameter_card':pin(card),
        'execution':{'rundir':str(root),'stage':'generation','attempt_record':rp},'dim6_parameters':['c1','c2'],
        'parameter_locations':{'c1':{'block':'DIM6','indices':[1]},'c2':{'block':'DIM6','indices':[2]}},
        'parameter_operators':{'c1':[BASIS[0]],'c2':[BASIS[1]]},'active_values':{'c1':2.}}
    if kind=='wrong_active_value':data['active_values']['c1']=3.
    if kind=='construction_only':data.update(provenance='constructed_input',execution=None)
    if kind=='outside_scanned_axis':data['parameter_operators']['c1']=[BASIS[1]]
    if kind=='partial_DIM6':data['dim6_parameters']=['c1'];data['parameter_locations'].pop('c2');data['parameter_operators'].pop('c2')
    if kind=='wrong_output':card=tmp_path/'not-returned.dat';card.write_text('BLOCK DIM6\n 1 2.\n 2 0.\n');data['parameter_card']=pin(card)
    if kind in ('outside_scanned_axis','partial_DIM6','wrong_output'):
        with pytest.raises(ValueError):p._zeroing(data,wf['target'],[BASIS[0]],tmp_path,{})
    else:
        result=p._zeroing(data,wf['target'],[BASIS[0]],tmp_path,{})
        assert result['native_observed']==(kind!='construction_only')
        assert bool(result['unexpected_parameter_values'])==(kind in ('inactive_nonzero','wrong_active_value'))

@pytest.mark.parametrize('outside',[False,True])
def test_coupling_matrix_requires_same_returned_native_custody(tmp_path,monkeypatch,outside):
    _,_,wf,_=setup(tmp_path/'domain');root=tmp_path/'fake-native';out=root/'outputs';out.mkdir(parents=True)
    card=out/'param_card.dat';card.write_text('BLOCK DIM6\n 1 2.\n 2 0.\n')
    record={'attempt_record':'record.json','outputs':['outputs'],'status':'succeeded','attempt_id':'fake-no-native'};rp=save(root/'record.json',record)
    monkeypatch.setattr(p.execution,'stage_errors',lambda *_:[]);monkeypatch.setattr(p.execution,'load_execution',lambda _:{'stages':{'generation':record}})
    observation={'model_source':wf['target']['model_source'],'stage':'final_scan','provenance':'returned_parameter_card','parameter_card':pin(card),
        'execution':{'rundir':str(root),'stage':'generation','attempt_record':rp},'dim6_parameters':['c1','c2'],
        'parameter_locations':{'c1':{'block':'DIM6','indices':[1]},'c2':{'block':'DIM6','indices':[2]}},
        'parameter_operators':{'c1':[BASIS[0]],'c2':[BASIS[1]]},'active_values':{'c1':2.}}
    zp=save(tmp_path/'observation.json',observation);mp=save(tmp_path/'couplings.json',{'GC_1':{'kind':'qcd','operators':[]},'GC_2':{'kind':'eft','operators':[BASIS[0]]}})
    matrix=(tmp_path if outside else out)/'matrix.f';matrix.write_text('      AMP=GC_1+GC_2\n')
    data={'matrix_sources':[pin(matrix)],'coupling_map':ref(mp),'allowed_operators':[BASIS[0]],'zeroing_record':ref(zp)}
    if outside:
        with pytest.raises(ValueError,match='actual output'):p._compute('coupling_census',data,wf['target'],['control'],tmp_path,{})
    else:
        status,result=p._compute('coupling_census',data,wf['target'],['control'],tmp_path,{})
        assert status=='pass' and result['parameter_card_check']['native_observed']
