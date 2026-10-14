"""Software-only controls: all native calls/approval callbacks explicitly mocked."""
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
from types import SimpleNamespace
import pytest
from ravel.physics import sfitter_native as n, sfitter_results as e, sfitter_inputs as i
from ravel.workflow import sfitter_workflow as w, science, agent_graph
from ravel.workflow.state_io import atomic_json,read_json

# Portable exact235-file fixture; no upstream imports or network required.
import os
import tempfile
import zipfile
_ARCHIVE=Path(__file__).resolve().parents[1]/'fixtures/sfitteragents-6072a79e.zip'
_SESSION=tempfile.TemporaryDirectory(prefix='ravel-sfitter-source-')
UP=Path(_SESSION.name).resolve()
with zipfile.ZipFile(_ARCHIVE) as stream:
    for member in stream.infolist():
        path=Path(member.filename)
        if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe fixed test archive')
        target=UP/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(stream.read(member));target.chmod((member.external_attr>>16)&0o777)
# The snapshot is the reviewed upstream tree with its prose generalized; a local census pins its bytes.
_PACKAGED=read_json(Path(n.__file__).parents[1]/'data/sfitter/upstream-source.json')
_CENSUS=Path(_SESSION.name+'-census.json')
_CENSUS.write_text(json.dumps({**_PACKAGED,'files':{rel:hashlib.sha256((UP/rel).read_bytes()).hexdigest() for rel in _PACKAGED['files']}}))
os.environ[n.UPSTREAM_CENSUS_ENV]=str(_CENSUS)
BASIS=i.native_basis(UP)
def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
def save(path,value):atomic_json(path,value);return pin(path)
class Array:
    def __init__(self,shape,values=None):
        self.dtype=SimpleNamespace(str='<f8');self.shape=tuple(shape)
        count=1
        for d in shape:count*=d
        self.raw=b''.join(struct.pack('<d',x) for x in (values if values is not None else [1.]*count))
    def tobytes(self,order='C'):assert order=='C';return self.raw

def arr(shape):return e.array(Array(shape))
def fixture(tmp):
    manifest=tmp/'source.json';save(manifest,read_json(n.upstream_census_path())['files'])
    save(manifest,{'schema_version':1,'files':read_json(manifest)})
    evidence=tmp/'evidence.txt';evidence.write_text('Explicit engineering-only source; no model or scientific result.')
    obs={'ID':'control','name':'engineering_only','bin_widths':[1.], 'Meas':{'data':[1.],'modifiers':[{'name':'Pois','type':'pois','data':[0.]},{'name':'stat','type':'stat','data':[1.]}]},'Bkg':{'data':[0.],'modifiers':[]},'modifiers':[]}
    card={'observations':[obs],'predictions':[{'ID':'control','name':'engineering_only','data':[1.],'modifiers':[{'name':x,'data':[0.1 if x=='D6tg' else 0.]} for x in BASIS]}]}
    cp=tmp/'sfitter/data/control.json';cp.parent.mkdir(parents=True);save(cp,card)
    rp=tmp/'sfitter/params/control.yaml';rp.parent.mkdir()
    rp.write_text((UP/'sfitter/params/top_fit.yaml').read_text().replace('top_first_fit','engineering_control').replace('data/Top_Full.json','data/control.json'))
    sem={'schema_version':1,'purpose':'analytic_qualification','observables':[{'ID':'control','name':'engineering_only','bins':['bin1'],'representation':'integrated','normalization':'absolute','unit':'pb'}],
         'eft':{'target_basis':BASIS,'source_basis':'native_top_D6','flavour':'native_top_22','coefficient_unit':'TeV^-2','lambda_unit':'TeV','source_scale_gev':1000.,'target_scale_gev':1000.,'rge_policy':'not_applied_same_scale','conversion':'identity_native_basis','linear':True,'quadratic':False,'mixed_pairs':[],'domain':'Engineering transport only','evidence':[pin(evidence)]},
         'uncertainty_policy':'native_top_percent_sources_RFit_component_clamp_named_correlation_capped_shrinkage','interval_policy':'raw_native_arrays_no_qualified_intervals','sources':[pin(evidence)]}
    sp=tmp/'semantic.json';save(sp,sem)
    asset=tmp/'site/runtime.txt';asset.parent.mkdir();asset.write_text('fake runtime asset, never imported')
    python=Path(sys.executable).resolve()
    c={'schema_version':1,'operation':'fixed-vector-qualification','purpose':'analytic_qualification','source':'explicit synthetic source control',
       'upstream_tree':{'root':str(UP),'manifest':pin(manifest)},'trusted_upstream_python':True,
       'runtime':{'python':pin(python),'site_roots':[str(asset.parent)],'assets':[pin(asset)],'versions':{x:'control-only' for x in n.RUNTIME_PACKAGES},'device':'cpu'},
       'datacard':pin(cp),'run_card':pin(rp),'semantic_manifest':pin(sp),'vectors':[[0.]*22,[1.]+[0.]*21],
       'max_seconds':20,'max_ram_mib':1024,'max_export_bytes':16*1024*1024}
    config=tmp/'config.json';save(config,c)
    return {'config':str(config)},c,card,sem,evidence

def qualify(request):
    b=len(request['basis']);v=request['config']['vectors']
    tensors={'smeft_coeffs':arr([1,b,b+1]),'smeft_offset':arr([1]),'measurements':arr([1]),'err_theo':arr([1]),'err_gauss':arr([1]),'corr':arr([1,1]),'corr_inv':arr([1,1]),'bin_widths':arr([1]),'norm_indices':arr([1]),'norm_start':arr([1])}
    return {'schema_version':1,'kind':'sfitter_fixed_vectors','parameters':request['basis'],'vectors':v,'scores':arr([len(v)]),'native_tensors':tensors,'score_convention':'native_score=-Q','predictions':None,'prediction_reason':'Native function returns scores only','physics_validated':False}

def fake_native(command,out,document):
    assert command[1:3]==['-I','-B'];request=read_json(out/'request.json')
    delivery=qualify(request)
    save(out/'delivery.json',delivery)
    source=next(p for p in request['source_files'] if p.endswith('/likelihood/full_likelihood.py'))
    save(out/'initialized-state.json',{'schema_version':1,'kind':'sfitter_initialized_state','parameters':request['basis'],'dims_nuisance':0,'native_origin':{'path':source,'sha256':request['source_files'][source]},'native_tensors':delivery['native_tensors'],'native_scalars':{'corr_shrinkage':e.scalar(0.0123456789012345),'syst_rho':e.scalar(.99),'n_blocks_substituted':1},'tensor_meanings':e.INITIALIZED_MEANINGS.copy(),'physics_validated':False,'independent_consistency':'unknown'})
    source=next(p for p in request['source_files'] if p.endswith('/likelihood/full_likelihood.py'))
    save(out/'runtime.json',{'schema_version':1,'versions':request['config']['runtime']['versions'],'device':'cpu','precision':'double','imports':{'sfitter.likelihood.full_likelihood':{'path':source,'sha256':request['source_files'][source]}},'source_files':request['source_files'],'runtime_assets':request['runtime_assets'],'randomness':'synthetic no native calculation','physics_validated':False})
    save(out/'progress.json',{'phase':'complete','error':None,'physics_validated':False})
    (out/'native-stdout.log').write_text('synthetic native callback; zero actual native calls')
    return {'exit_code':0,'control_only':True}

def bypass_approval(monkeypatch,out):
    monkeypatch.setattr(n,'_approved',lambda *_:{'max_seconds':30,'output_directory':str(out)})

def test_registry_and_complete_inventory(tmp_path):
    task,c,*_=fixture(tmp_path)
    assert science.adapter({'mode':'sfitter-native-fit','task':task}) is n
    assert science._new_capability({'mode':'sfitter-native-fit','task':task})
    files=n.inputs(task,tmp_path);assert len([p for p in files if p.is_relative_to(UP)])==235
    assert UP/'sfitter/data/Top_Full.json' in files

@pytest.mark.parametrize('mutation', ['unknown','subset','short','wrong_id','numerical_yaml','scale','absolute_group','extra_config','evidence_not_pin'])
def test_input_adversaries(tmp_path,mutation):
    task,c,card,sem,_=fixture(tmp_path)
    if mutation=='unknown':card['predictions'][0]['modifiers'][0]['name']='D6qq18x6qt8'
    if mutation=='short':card['observations'][0]['Meas']['modifiers'][1]['data']=[]
    if mutation=='wrong_id':card['predictions'][0]['ID']='false'
    if mutation in ('unknown','short','wrong_id'):c['datacard']=save(Path(c['datacard']['path']),card)
    if mutation in ('subset','numerical_yaml'):
        p=Path(c['run_card']['path']);p.write_text(p.read_text()+('parameter_names: [D6tg]\n' if mutation=='subset' else 'syst_correlation_rho: 0.0\n'));c['run_card']=pin(p)
    if mutation=='scale':sem['eft']['target_scale_gev']=2000.
    if mutation=='absolute_group':sem['observables'][0]['bins']=['one','two']
    if mutation=='evidence_not_pin':sem['sources']=[{'claim':'reviewed'}]
    if mutation in ('scale','absolute_group','evidence_not_pin'):c['semantic_manifest']=save(Path(c['semantic_manifest']['path']),sem)
    if mutation=='extra_config':c['approved']=True
    save(Path(task['config']),c)
    with pytest.raises((ValueError,KeyError)):n.inputs(task,tmp_path)

def test_original_default_card_is_not_corrected():
    card=read_json(UP/'sfitter/data/Top_Full.json')
    with pytest.raises(ValueError,match='pairing'):i.inspect_datacard(card,BASIS)
    assert card['predictions'][3]['modifiers'][33]['name']=='D6qq18x6qt8'

def test_duplicate_card_json_refused(tmp_path):
    task,c,*_=fixture(tmp_path);p=Path(c['datacard']['path']);p.write_text('{"observations":[],"observations":[],"predictions":[]}');c['datacard']=pin(p);save(Path(task['config']),c)
    with pytest.raises(ValueError,match='duplicate'):n.inputs(task,tmp_path)

def test_lossless_nonfinite_signed_zero_and_corrupt_bytes():
    value=e.array(Array([3],[float('nan'),float('inf'),-0.]))
    assert e.validate_array(value)[-8:]==struct.pack('<d',-0.)
    value['base64']=base64.b64encode(b'wrong').decode()
    with pytest.raises(ValueError):e.validate_array(value)

def test_closed_results_no_authority_or_missing_pair():
    result=SimpleNamespace(parameters=BASIS)
    pairs={(a,b) for i,a in enumerate(BASIS) for b in BASIS[i+1:]}
    for key in e.ARRAY_MAPS:setattr(result,key,{x:Array([1,1] if isinstance(x,tuple) else ([2] if key.endswith('_bins') else [1])) for x in (pairs if key in ('marginal_2d','profile_2d') else BASIS)})
    for key in e.WEIGHTS:setattr(result,key,Array([2] if key.startswith('w_bins') else [1]))
    result.marginal_effective_size=Array([])
    doc=e.fit_result(result,BASIS);assert e.validate_result(doc,BASIS)
    bad=copy.deepcopy(doc);bad['physics_validated']=True
    with pytest.raises(ValueError,match='authority'):e.validate_result(bad,BASIS)
    doc['maps']['profile_2d'].pop()
    with pytest.raises(ValueError,match='population'):e.validate_result(doc,BASIS)

def test_real_adapter_fake_native_and_no_reuse(tmp_path,monkeypatch):
    task,c,*_=fixture(tmp_path);out=tmp_path/'output';bypass_approval(monkeypatch,out)
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db,'execute_native',fake_native)
    result=n.run(task,tmp_path,out)
    assert result['status']=='passed' and result['physics_validated'] is False and result['coverage_calibration']=='unknown'
    assert read_json(out/'sfitter-raw-census.json')['before_semantic_adjudication']
    before={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    with pytest.raises(FileExistsError):n.run(task,tmp_path,out)
    assert before=={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}

@pytest.mark.parametrize('kind',['failure_partial','original_ABA','copied_mode','missing_runtime','wrong_scores','false_authority','source_addition'])
def test_native_postcondition_adversaries(tmp_path,monkeypatch,kind):
    task,c,*_=fixture(tmp_path);out=tmp_path/'output';bypass_approval(monkeypatch,out)
    from ravel.physics import reinterpret_db
    def returned(command,native,document):
        receipt=fake_native(command,native,document)
        if kind=='failure_partial':(native/'partial.txt').write_text('actual partial control');raise ValueError('native failed')
        if kind=='original_ABA':
            p=Path(c['datacard']['path']);raw=p.read_bytes();p.unlink();p.write_bytes(raw)
        if kind=='copied_mode':(native/'upstream/LICENSE').chmod(0o600)
        if kind=='missing_runtime':(native/'runtime.json').unlink()
        if kind=='source_addition':(native/'upstream/new.py').write_text('unexpected')
        if kind in ('wrong_scores','false_authority'):
            doc=read_json(native/'delivery.json')
            if kind=='wrong_scores':doc['scores']=arr([1])
            else:doc['physics_validated']=True
            save(native/'delivery.json',doc)
        return receipt
    monkeypatch.setattr(reinterpret_db,'execute_native',returned)
    result=n.run(task,tmp_path,out)
    assert result['status']=='failed' and result['physics_validated'] is False
    assert (out/'native/delivery.json').is_file() and (out/'sfitter-raw-census.json').is_file()
    if kind=='failure_partial':assert (out/'native/partial.txt').read_text()=='actual partial control'

def test_no_ordinary_approval_no_output(tmp_path):
    task,*_=fixture(tmp_path);out=tmp_path/'output'
    with pytest.raises(ValueError,match='approved ordinary'):n.run(task,tmp_path,out)
    assert not out.exists()

def test_approval_policy_does_not_allow_reuse(tmp_path,monkeypatch):
    task,*_=fixture(tmp_path);rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True);save(rd/'inputs/science-plan.json',{})
    out=rd/'outputs/attempt-1'
    spec={'schema_version':2,'mode':'sfitter-native-fit','task':task,'max_attempts':1,'review_policy':{'policy':{'max_redos':0,'claim_scopes':{n.SCOPE:{'actions':['delivery','reuse']}}}}}
    monkeypatch.setattr(science,'verify_worker',lambda _:{'max_seconds':30,'output_directory':'outputs/attempt-1'})
    monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    with pytest.raises(ValueError,match='delivery-only'):n._approved(task,out)

def workflow_fixture(tmp):
    task,c,card,sem,proof=fixture(tmp)
    request={'schema_version':1,'id':'full_control','upstream_tree':c['upstream_tree'],'sources':[pin(proof)],
      'target':{'observables':sem['observables'],'eft':{'basis':BASIS,'quadratic':False,'mixed_pairs':[],'source_scale_gev':1000.,'target_scale_gev':1000.,'coefficient_unit':'TeV^-2','lambda_unit':'TeV','flavour':'native_top_22'},'process':'explicit control','perturbative_order':'declared NLO control','model_source':'explicit proof'},
      'handoffs':{},'model':{'name':'not-called','reasoning_effort':'high','max_output_tokens':1000},'max_wall_seconds':60}
    def doc(phase,payload):return {'schema_version':1,'phase':phase,'target_sha256':agent_graph.digest(request['target']),'sources':[pin(proof)],'payload':payload,'physics_validated':False,'execution_authorized':False}
    sem['purpose']='supplied_full_study';save(Path(c['semantic_manifest']['path']),sem)
    docs={'extraction':doc('extraction',{'rows':card['observations']}),
          'sm_template':doc('sm_template',{'rows':[{'ID':'control','name':'engineering_only','data':[1.],'theory_modifiers':[],'perturbative_order':'declared NLO control','evidence':pin(proof)}]}),
          'parameterization':doc('parameterization',{'rows':[{'ID':'control','name':'engineering_only','modifiers':card['predictions'][0]['modifiers'],'scan_evidence':pin(proof),'coupling_sanity_evidence':pin(proof),'fit_diagnostics':pin(proof)}]}),
          'conventions':doc('conventions',{'semantic_manifest':pin(Path(c['semantic_manifest']['path']))}),
          'datacard':doc('datacard',{'datacard':c['datacard'],'run_card':c['run_card'],'semantic_manifest':pin(Path(c['semantic_manifest']['path']))})}
    return request,docs,c

def test_specialist_graph_actual_context_no_calls(tmp_path):
    request,docs,c=workflow_fixture(tmp_path);rp=save(tmp_path/'workflow.json',request)
    graph=w.phase_graph(request,tmp_path,rp)
    assert len(graph['nodes'])==3
    from ravel.workflow.agent_host import AgentHost
    host=AgentHost(api_key='control-only',bound_roots=[str(tmp_path),str(UP)])
    node=graph['nodes'][0];prepared=host.prepare_model_context(node,{'request_id':'control','packet':None,'input_artifacts':node['inputs']})
    assert 'measurement-extractor' in node['id']
    assert any('SFitter' in row['content'] for row in prepared['context']['input_artifacts'])
    assert 'RFit' in prepared['parameters']['instructions']
    assert all(n['role']=='designer' for n in graph['nodes'])

def test_full_phase_handoffs_to_native_card(tmp_path):
    request,docs,c=workflow_fixture(tmp_path)
    for phase in w.PHASES:
        receipt=w.apply_handoff(request,docs[phase],tmp_path)
        assert receipt['accepted_as']=='source_bound_draft' and not receipt['execution_authorized']
        request['handoffs'][phase]=save(tmp_path/(phase+'.json'),docs[phase])
    value=w.context(request,tmp_path)
    assert value['phase']=='native_plan_required' and value['model_calls_observed']==0
    assert value['native_input']['native_profile']=='exp(-Q)'
    with pytest.raises(ValueError,match='complete'):w.apply_handoff(request,docs['datacard'],tmp_path)

@pytest.mark.parametrize('kind',['skipped','partial','missing_wc','bad_order','authority','stale_premise','changed_card'])
def test_specialist_scientific_handoff_adversaries(tmp_path,kind):
    request,docs,c=workflow_fixture(tmp_path)
    if kind=='skipped':request['handoffs']['parameterization']=save(tmp_path/'parameterization.json',docs['parameterization'])
    if kind=='partial':docs['extraction']['payload']['rows']=[]
    if kind=='authority':docs['extraction']['execution_authorized']=True
    if kind=='stale_premise':docs['extraction']['target_sha256']='0'*64
    if kind in ('partial','authority','stale_premise'):
        with pytest.raises(ValueError):w.apply_handoff(request,docs['extraction'],tmp_path)
        return
    if kind=='skipped':
        with pytest.raises(ValueError):w.context(request,tmp_path)
        return
    if kind=='missing_wc':docs['parameterization']['payload']['rows'][0]['modifiers'].pop()
    if kind=='bad_order':docs['sm_template']['payload']['rows'][0]['perturbative_order']='LO'
    for phase in w.PHASES:
        if (kind=='missing_wc' and phase=='parameterization') or (kind=='bad_order' and phase=='sm_template'):
            with pytest.raises(ValueError):w.apply_handoff(request,docs[phase],tmp_path)
            return
        request['handoffs'][phase]=save(tmp_path/(phase+'.json'),docs[phase])
    p=Path(c['datacard']['path']);p.write_text(p.read_text()+'\n')
    with pytest.raises(ValueError):w.context(request,tmp_path)

def test_blind_review_uses_real_existing_packet_gate(tmp_path):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    graph=w.review_graph({'path':str(tmp_path/'not-a-packet'),'manifest_sha256':'0'*64},{'path':str(tmp_path/'none'),'manifest_sha256':'1'*64},{'name':'not-called','reasoning_effort':'high','max_output_tokens':1000},graph_id='review_control',max_wall_seconds=60)
    node=graph['nodes'][0];host=AgentHost(api_key='control-only')
    with pytest.raises(HostFailure):host.prepare_model_context(node,{'request_id':'control','packet':node['packet'],'input_artifacts':[]})


def specification(task):
    return {'schema_version':2,'mode':'sfitter-native-fit','source':'Explicit synthetic engineering control',
       'assumptions':['No SFitter numerical/scientific result or approval is inferred'],'max_seconds':30,'approval_mode':'scripted_yes','task':task,'max_attempts':1,
       'review_policy':{'schema_version':1,'policy':{'schema_version':1,'actors':{'proposer':'producer','executor':'executor','physics_critic':'critic','skeptical_verifier':'skeptic','physics_decider':'decider'},'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
       'required_checks':[{'id':'integrity','kind':'integrity'},{'id':'scientific','kind':'scientific'}],
       'claim_scopes':{n.SCOPE:{'checks':['integrity'],'actions':['delivery']}}},'correction_contract':{'task_fields':[],'input_slots':[]}}}


def test_real_common_worker_and_report_no_process(tmp_path,monkeypatch):
    from ravel.physics import science_worker,reinterpret_db
    task,c,*_=fixture(tmp_path);rd=tmp_path/'ordinary';(rd/'inputs').mkdir(parents=True)
    spec=specification(task);science.validate(spec)
    plan={'schema_version':2,'base_dir':str(tmp_path),'attempt':1,'output_directory':'outputs/attempt-1','max_seconds':30,'stage_binding':{'input_snapshot':{}}}
    save(rd/'inputs/science-plan.json',plan);save(rd/'inputs/science.json',spec)
    monkeypatch.setattr(science,'verify_worker',lambda _:plan)
    monkeypatch.setattr(science,'execution_spec',lambda _:spec)
    monkeypatch.setattr(science_worker,'verify_worker',lambda _:plan)
    monkeypatch.setattr(science_worker,'execution_spec',lambda _:spec)
    monkeypatch.setattr(reinterpret_db,'execute_native',fake_native)
    assert science_worker.main([str(rd),'--attempt','1'])==0
    out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
    assert result==read_json(out/'sfitter-native.json') and result['status']=='passed'
    assert read_json(out/'verification.json')['physics_validated'] is False
    assert read_json(out/'checkin2.json')['sections']['waypoint']['status_scope']==n.SCOPE
    assert 'unknown' in (out/'RESULT.md').read_text() and (out/'sfitter-native-report.md').is_file()
    with pytest.raises(FileExistsError):science_worker.main([str(rd),'--attempt','1'])


def test_genuine_plan_source_and_public_legacy_guard(tmp_path):
    task,*_=fixture(tmp_path);spec=specification(task);source=tmp_path/'study.json';save(source,spec)
    # Actual plan creation/worker registration, no approval or worker dispatch.
    from ravel import cli
    assert cli.main(['plan','--rundir',str(tmp_path/'planned'),'--spec',str(source)])==0
    assert (tmp_path/'planned/inputs/science-plan.json').is_file()
    assert not (tmp_path/'planned/inputs/science-approval.json').exists()
    bad=copy.deepcopy(spec);bad['schema_version']=1;bad.pop('review_policy');bad.pop('max_attempts');save(source,bad)
    with pytest.raises(ValueError,match='version 2'):science.plan(tmp_path/'legacy',source)
    assert not (tmp_path/'legacy').exists()


def test_actual_native_child_qualification_body_fake_modules(tmp_path,monkeypatch):
    """Run the real child main in-process with injected fake Torch/SFitter ONLY."""
    import contextlib
    import types
    from ravel.physics import sfitter_worker as child,reinterpret_db
    task,c,*_=fixture(tmp_path);out=tmp_path/'output';bypass_approval(monkeypatch,out)
    def native(command,native,document):
        request=read_json(native/'request.json')
        class Tensor:
            def __init__(self,shape):self.value=Array(shape)
            def detach(self):return self
            def cpu(self):return self
            def numpy(self):return self.value
        class Likelihood:
            parameter_names=BASIS;dims_nuisance=0;corr_shrinkage=0.0123456789012345;syst_rho=.99;n_blocks_substituted=1
            def __init__(self,params,device):
                for name,shape in [('smeft_coeffs',[1,22,23]),('corr',[1,1]),('corr_inv',[1,1])]:setattr(self,name,Tensor(shape))
                for name in set(n.TENSORS)-{'smeft_coeffs','corr','corr_inv'}:setattr(self,name,Tensor([1]))
            def log_likelihood(self,vectors):return Tensor([len(vectors)])
        torch=types.ModuleType('torch');torch.cuda=SimpleNamespace(is_available=lambda:False)
        torch.device=lambda x:x;torch.set_num_threads=lambda _:None;torch.set_default_dtype=lambda _:None;torch.float64='fake-f64'
        torch.tensor=lambda vectors,**_:vectors;torch.no_grad=contextlib.nullcontext
        sf=types.ModuleType('sfitter');sf.__path__=[]
        util=types.ModuleType('sfitter.util');util.__path__=[]
        doc=types.ModuleType('sfitter.util.documenter');doc.Documenter=SimpleNamespace(from_param_file=lambda _:(object(),{'sector':'top'}))
        lik=types.ModuleType('sfitter.likelihood');lik.__path__=[]
        full=types.ModuleType('sfitter.likelihood.full_likelihood');full.ProfileLikelihood=Likelihood
        previous_cwd=Path.cwd();old_path=list(sys.path)
        source=next(p for p in request['source_files'] if p.endswith('/likelihood/full_likelihood.py'))
        with monkeypatch.context() as m:
            import os
            m.setenv('CUDA_VISIBLE_DEVICES',os.environ.get('CUDA_VISIBLE_DEVICES',''))
            for name,module in [('torch',torch),('sfitter',sf),('sfitter.util',util),('sfitter.util.documenter',doc),('sfitter.likelihood',lik),('sfitter.likelihood.full_likelihood',full)]:m.setitem(sys.modules,name,module)
            m.setattr(child.importlib.metadata,'version',lambda _:'control-only')
            m.setattr(child,'_imports',lambda _:{'sfitter.likelihood.full_likelihood':{'path':source,'sha256':request['source_files'][source]}})
            try:assert child.main([str(native/'request.json')])==0
            finally:
                import os
                os.chdir(previous_cwd);sys.path[:]=old_path
                sys.modules.pop('ravel_sfitter_export',None)
        return {'exit_code':0,'control_only':True,'actual_child_main_exercised':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',native)
    result=n.run(task,tmp_path,out)
    assert result['status']=='passed' and result['native_execution']['actual_child_main_exercised']
    assert result['native_return']['predictions'] is None and 'corr_inv' in result['native_return']['native_tensors']
    assert 'torch' not in sys.modules


def test_host_tools_bound_to_actual_domain_inputs(tmp_path):
    from ravel.workflow.agent_host import AgentHost,HostFailure
    request,docs,c=workflow_fixture(tmp_path);rp=save(tmp_path/'workflow.json',request)
    inputs=[{'id':'request',**rp},*[{'id':'p'+str(j),**p} for j,p in enumerate(w.input_pins(request,tmp_path))]]
    node={'id':'domain','kind':'tool','role':'designer','depends_on':[],'inputs':inputs,'packet':None,'action':'sfitter-context','parameters':{'request_input':'request'},'max_attempts':1}
    host=AgentHost(api_key='control-only',bound_roots=[str(tmp_path),str(UP)])
    control=SimpleNamespace(cancelled=lambda:False,call=lambda action,kind,request,operation:operation())
    value=host.execute(node,{'request_id':'control','packet':None,'input_artifacts':inputs},control)
    assert value['value']['specialists']==list(w.ROLES['extraction']) and value['execution_authorized'] is False
    broken=copy.deepcopy(node);broken['inputs'].pop()
    with pytest.raises(HostFailure,match='custody'):host.execute(broken,{'request_id':'control','packet':None,'input_artifacts':broken['inputs']},control)


def test_output_geometry_cannot_look_complete_when_grid_missing():
    result=SimpleNamespace(parameters=BASIS)
    pairs={(a,b) for j,a in enumerate(BASIS) for b in BASIS[j+1:]}
    for key in e.ARRAY_MAPS:setattr(result,key,{x:Array([1,1] if isinstance(x,tuple) else ([2] if key.endswith('_bins') else [1])) for x in (pairs if key in ('marginal_2d','profile_2d') else BASIS)})
    for key in e.WEIGHTS:setattr(result,key,Array([2] if key.startswith('w_bins') else [1]))
    result.marginal_effective_size=Array([])
    result.profile_2d[next(iter(pairs))]=Array([0,1])
    with pytest.raises(ValueError,match='grid'):e.fit_result(result,BASIS)

@pytest.mark.parametrize('failure_stage',[None,'export','train'])
def test_actual_child_fit_preserves_opaque_before_export(tmp_path,monkeypatch,failure_stage):
    import types
    from ravel.physics import sfitter_worker as child,reinterpret_db
    task,c,*_=fixture(tmp_path);c['operation']='fit';c['vectors']=[];save(Path(task['config']),c)
    out=tmp_path/'output';bypass_approval(monkeypatch,out)
    calls=[]
    def native(command,native,document):
        request=read_json(native/'request.json');output=Path(request['package_root'])/'output/control';output.mkdir()
        doc=SimpleNamespace(add_file=lambda name:str(output/name))
        result=SimpleNamespace(parameters=BASIS)
        pairs={(a,b) for j,a in enumerate(BASIS) for b in BASIS[j+1:]}
        for key in e.ARRAY_MAPS:setattr(result,key,{x:Array([1,1] if isinstance(x,tuple) else ([2] if key.endswith('_bins') else [1])) for x in (pairs if key in ('marginal_2d','profile_2d') else BASIS)})
        for key in e.WEIGHTS:setattr(result,key,Array([2] if key.startswith('w_bins') else [1]))
        result.marginal_effective_size=Array([])
        if failure_stage=='export':result.profile_2d.pop(next(iter(pairs)))
        def train():
            calls.append('train')
            if failure_stage=='train':raise ValueError('deliberate later training failure')
        fit=SimpleNamespace(train=train,save=lambda:(output/'model.pth').write_bytes(b'opaque control'),fit=lambda:result)
        class Tensor:
            def __init__(self,shape):self.value=Array(shape)
            def detach(self):return self
            def cpu(self):return self
            def numpy(self):return self.value
        like=SimpleNamespace(parameter_names=BASIS,dims_nuisance=0,corr_shrinkage=0.0123456789012345,syst_rho=.99,n_blocks_substituted=1)
        for name,shape in [('smeft_coeffs',[1,22,23]),('corr',[1,1]),('corr_inv',[1,1])]:setattr(like,name,Tensor(shape))
        for name in set(n.TENSORS)-{'smeft_coeffs','corr','corr_inv'}:setattr(like,name,Tensor([1]))
        torch=types.ModuleType('torch');torch.cuda=SimpleNamespace(is_available=lambda:False);torch.device=lambda x:x
        torch.set_num_threads=lambda _:None;torch.set_default_dtype=lambda _:None;torch.float64='fake-f64'
        sf=types.ModuleType('sfitter');sf.__path__=[]
        util=types.ModuleType('sfitter.util');util.__path__=[]
        docmodule=types.ModuleType('sfitter.util.documenter');docmodule.Documenter=SimpleNamespace(from_param_file=lambda _:(doc,{'sector':'top'}))
        mainmodule=types.ModuleType('sfitter.__main__');mainmodule.init_run=lambda *_:(fit,like)
        mainmodule.Plots=SimpleNamespace(make_plots=lambda *_:calls.append('native_plots'))
        source=next(p for p in request['source_files'] if p.endswith('/likelihood/full_likelihood.py'))
        cwd=Path.cwd();paths=list(sys.path)
        with monkeypatch.context() as m:
            import os
            m.setenv('CUDA_VISIBLE_DEVICES',os.environ.get('CUDA_VISIBLE_DEVICES',''))
            for name,module in [('torch',torch),('sfitter',sf),('sfitter.util',util),('sfitter.util.documenter',docmodule),('sfitter.__main__',mainmodule)]:m.setitem(sys.modules,name,module)
            m.setattr(child.importlib.metadata,'version',lambda _:'control-only')
            m.setattr(child,'_imports',lambda _:{'sfitter.likelihood.full_likelihood':{'path':source,'sha256':request['source_files'][source]}})
            try:
                child.main([str(native/'request.json')])
            except ValueError as exc:
                assert failure_stage
                assert (native/'initialized-state.json').is_file()
                if failure_stage=='export':assert (output/'results.pkl').is_file()
                raise ValueError('native export refused after retained opaque result') from exc
            finally:
                import os
                os.chdir(cwd);sys.path[:]=paths;sys.modules.pop('ravel_sfitter_export',None)
        return {'exit_code':0,'control_only':True}
    monkeypatch.setattr(reinterpret_db,'execute_native',native)
    result=n.run(task,tmp_path,out)
    assert result['status']==('failed' if failure_stage else 'passed')
    pkl=out/'native/upstream/sfitter/output/control/results.pkl'
    assert pkl.is_file()==(failure_stage!='train')
    if pkl.is_file():assert pkl.stat().st_size>0
    assert 'train' in calls and (('native_plots' in calls)==(failure_stage is None))
    assert result['initialized_state']['native_scalars']['corr_shrinkage']==e.scalar(0.0123456789012345)
    if failure_stage is None:assert result['native_return']['raw_log_scores'] is None
    assert 'torch' not in sys.modules


def test_changed_observed_runtime_import_origin_refused(tmp_path):
    task,c,*_=fixture(tmp_path)
    request={'config':c,'source_files':{},'runtime_assets':{},'output':str(tmp_path),'exporter_sha256':'0'*64,'driver_sha256':'0'*64}
    document={'schema_version':1,'versions':c['runtime']['versions'],'device':'cpu','precision':'double','imports':{'torch':{'path':'/unadmitted/torch.py','sha256':'0'*64}},'source_files':{},'runtime_assets':{},'randomness':'unchanged','physics_validated':False}
    with pytest.raises(ValueError,match='unadmitted'):n.validate_runtime(document,request)


def test_full_source_manifest_addition_refused_before_output(tmp_path):
    import shutil
    task,c,*_=fixture(tmp_path);source=tmp_path/'private-upstream';shutil.copytree(UP,source);(source/'unexpected.py').write_text('unadmitted')
    c['upstream_tree']['root']=str(source);save(Path(task['config']),c)
    with pytest.raises(ValueError,match='census'):n.inputs(task,tmp_path)


def test_mixed_term_in_linear_only_semantics_refused(tmp_path):
    task,c,card,sem,_=fixture(tmp_path)
    card['predictions'][0]['modifiers'].append({'name':'D6tgxD6tw','data':[.1]});sem['eft']['mixed_pairs']=[['D6tg','D6tw']]
    with pytest.raises(ValueError,match='truncation'):n.semantic(sem,card,BASIS)


def test_return_byte_bound_is_checked_before_parse(tmp_path,monkeypatch):
    task,c,*_=fixture(tmp_path);out=tmp_path/'output';bypass_approval(monkeypatch,out)
    from ravel.physics import reinterpret_db
    def oversized(command,native,document):
        receipt=fake_native(command,native,document)
        (native/'delivery.json').write_bytes(b'['*(document['max_export_bytes']+1))
        return receipt
    monkeypatch.setattr(reinterpret_db,'execute_native',oversized)
    result=n.run(task,tmp_path,out)
    assert result['status']=='failed' and any('export exceeds bound' in x for x in result['problems'])
    assert (out/'native/delivery.json').stat().st_size==c['max_export_bytes']+1


def test_public_specialist_cli_is_draft_only(tmp_path):
    from ravel import cli
    request,docs,c=workflow_fixture(tmp_path);path=tmp_path/'workflow.json';save(path,request)
    out=tmp_path/'context.json'
    assert cli.main(['sfitter-workflow','context','--request',str(path),'--output',str(out)])==0
    result=read_json(out);assert not result['execution_authorized'] and result['model_calls_observed']==0


def test_public_planning_rejects_native_reuse_policy(tmp_path):
    from ravel import cli
    task,*_=fixture(tmp_path);spec=specification(task)
    spec['review_policy']['policy']['claim_scopes'][n.SCOPE]['actions'].append('reuse')
    source=tmp_path/'science.json';save(source,spec)
    with pytest.raises(ValueError,match='delivery-only'):science.plan(tmp_path/'refused',source)
    assert not (tmp_path/'refused').exists()

@pytest.mark.parametrize('intake',['native','workflow'])
def test_singleton_normalized_is_refused(tmp_path,intake):
    task,c,card,sem,_=fixture(tmp_path)
    sem['observables'][0]['normalization']='normalized'
    with pytest.raises(ValueError,match='singletons'):
        if intake=='native':n.semantic(sem,card,BASIS)
        else:
            request,*_=workflow_fixture(tmp_path/'workflow')
            request['target']['observables'][0]['normalization']='normalized'
            w.validate(request)

def test_exact_native_group_meanings_positive(tmp_path):
    task,c,card,sem,_=fixture(tmp_path)
    assert n.semantic(sem,card,BASIS)
    request,*_=workflow_fixture(tmp_path/'workflow');assert w.validate(request)
    sem['observables'][0]['bins']=['one','two'];sem['observables'][0]['normalization']='normalized'
    card['observations'][0]['Meas']['data']=[1.,2.]
    assert n.semantic(sem,card,BASIS)
    request['target']['observables']=sem['observables'];assert w.validate(request)

@pytest.mark.parametrize('mutation',['missing','source','geometry','authority','tensor_drift'])
def test_initialized_state_refusal_keeps_raw(tmp_path,monkeypatch,mutation):
    task,c,*_=fixture(tmp_path);out=tmp_path/'output';bypass_approval(monkeypatch,out)
    from ravel.physics import reinterpret_db
    def returned(command,native,document):
        receipt=fake_native(command,native,document);p=native/'initialized-state.json'
        if mutation=='missing':p.unlink();return receipt
        state=read_json(p)
        if mutation=='source':state['native_origin']['sha256']='0'*64
        if mutation=='geometry':state['native_tensors']['norm_start']=arr([2])
        if mutation=='authority':state['independent_consistency']='passed'
        if mutation=='tensor_drift':state['native_tensors']['corr_inv']=e.array(Array([1,1],[2.]))
        save(p,state);return receipt
    monkeypatch.setattr(reinterpret_db,'execute_native',returned)
    result=n.run(task,tmp_path,out)
    assert result['status']=='failed' and result['physics_validated'] is False
    assert (out/'native/delivery.json').is_file() and (out/'sfitter-raw-census.json').is_file()
    assert any('state' in problem for problem in result['problems'])

def test_snapshot_exact_scalars_and_distinct_metric_bytes(tmp_path):
    from ravel.physics import sfitter_results as export
    class Tensor:
        def __init__(self,shape,values=None):self.value=Array(shape,values)
        def detach(self):return self
        def cpu(self):return self
        def numpy(self):return self.value
    like=SimpleNamespace(parameter_names=BASIS,dims_nuisance=0,
         corr_shrinkage=0.0123456789012345,syst_rho=.99,n_blocks_substituted=1)
    for name in n.TENSORS:setattr(like,name,Tensor([1]))
    like.smeft_coeffs=Tensor([1,22,23]);like.corr=Tensor([1,1],[1.]);like.corr_inv=Tensor([1,1],[2.])
    origin={'path':'/exact/pinned/full_likelihood.py','sha256':'a'*64}
    state=export.initialized_state(like,BASIS,origin)
    export.validate_initialized_state(state,BASIS,origin,bin_count=1,group_count=1)
    assert export.validate_array(state['native_scalars']['corr_shrinkage'])==struct.pack('<d',like.corr_shrinkage)
    assert state['native_tensors']['corr']!=state['native_tensors']['corr_inv']
    assert state['tensor_meanings']['corr']=='native_pre_shrinkage_correlation'
    assert state['independent_consistency']=='unknown' and state['physics_validated'] is False
