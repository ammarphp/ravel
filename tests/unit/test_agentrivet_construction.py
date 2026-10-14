"""Actual ordinary Graph/Host/source preparation; inert model transport only.

Own synthetic role modules are software fixtures, not original AgentRivet or
physics validation. No provider, compiler, event job or native runtime is run.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import agentrivet_construction as operation, agentrivet_runtime, agent_graph, research_cycle
from ravel.workflow.agentrivet_provider import GraphLLM
from ravel.workflow.state_io import atomic_json,read_json
from agentrivet_construction_fixture import allow_own_source_census, request,host,triplet,MODEL,CODE,pin
from test_agentrivet_source import pure_plan


def prepared(tmp_path):
    raw=request(tmp_path)
    result=operation.prepare(raw,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    return raw,result['request']


def generated(tmp_path,monkeypatch):
    raw,rp=prepared(tmp_path);seen=[];queue=[deepcopy(MODEL),*triplet()]
    actor=host(monkeypatch,queue,seen)
    result=operation.generate(rp,base_dir=tmp_path,host=actor)
    assert not queue
    return raw,rp,result,actor,seen


def test_paper_first_preparation_without_catalogue_or_capsule_preserves_complete_inputs(tmp_path):
    raw,rp=prepared(tmp_path);value=read_json(rp['path'])
    assert Path(value['upstream']['root'])!=Path(raw['upstream']['root'])
    assert value['upstream']['files']==raw['upstream']['files']
    for row in value['upstream']['files']:
        assert (Path(value['upstream']['root'])/row['path']).read_bytes()==(Path(raw['upstream']['root'])/row['path']).read_bytes()
    assert Path(value['paper']['path']).read_bytes()==Path(raw['paper']['path']).read_bytes()
    context=operation.context(rp,base_dir=tmp_path)
    assert context['original_parent']==value['goal_binding']
    assert context['prior_reviews_carried']==[] and not context['physics_validated'] and not context['execution_authorized']
    assert all(not str(p['path']).endswith('head.json') for p in context['source_inputs'])


@pytest.mark.parametrize('change',['missing_python','extra_python','symlink','paper','asset_escape','call_population','scope'])
def test_complete_preparation_adverse_refuses_before_materialization(tmp_path,change):
    raw=request(tmp_path)
    if change=='missing_python':raw['upstream']['files']=[r for r in raw['upstream']['files'] if r['path']!='agentrivet/fixture_models.py']
    elif change=='extra_python':(Path(raw['upstream']['root'])/'agentrivet/new.py').write_text('# Undeclared source\n')
    elif change=='symlink':
        p=Path(raw['upstream']['root'])/'agentrivet/core.py';p.unlink();p.symlink_to(Path(raw['paper']['path']))
    elif change=='paper':Path(raw['paper']['path']).write_text('Changed supplied paper\n')
    elif change=='asset_escape':raw['hepdata']['assets']=[{'path':'../escape','role':'data','input':raw['paper']}]
    elif change=='call_population':raw['provider']['max_calls']=4
    else:raw['max_native_repairs']=3
    with pytest.raises((ValueError,OSError)):operation.prepare(raw,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    assert not (tmp_path/'prepared').exists()


def test_authentication_before_capture_retains_expected_paper_bytes(tmp_path,monkeypatch):
    raw=request(tmp_path);original=Path.write_bytes;fired=[]
    def changed(p,body):
        result=original(p,body)
        if p==tmp_path/'prepared/paper.txt':original(p,b'Unapproved captured paper\n');fired.append(True)
        return result
    monkeypatch.setattr(Path,'write_bytes',changed)
    with pytest.raises(ValueError,match='commitment'):operation.prepare(raw,base_dir=tmp_path,output_dir=tmp_path/'prepared')
    assert fired and Path(raw['paper']['path']).read_bytes().startswith(b'Complete own')


def test_original_role_loop_ordinary_executor_complete_source_study(tmp_path,monkeypatch):
    raw,rp,gp,actor,seen=generated(tmp_path,monkeypatch)
    g=read_json(gp['path']);assert len(seen)==4 and not g['physics_validated']
    assert g['source_study']['task']['backend']=='agentrivet-source'
    spec=read_json(g['source_study']['specification']['path'])
    assert spec['goal_binding']==read_json(rp['path'])['goal_binding']
    graphs=sorted((tmp_path/'prepared/role-graphs').glob('stage-*'))
    assert len(graphs)==4
    for root in graphs:
        state=agent_graph.status(root)
        assert state['usage']['calls']==1 and len(state['calls'])==1
    campaign=research_cycle._load(raw['campaign'])[1]
    assert len(campaign['graphs'])==4 and len(campaign['resource_ledger'])==4
    _,request_doc=operation._load(rp,tmp_path)
    _,observed,memory=operation._generation(request_doc,gp,tmp_path)
    assert memory['code_draft']==[CODE.decode().strip()] and memory['paper_text']==Path(raw['paper']['path']).read_text()
    assert observed['upstream_reviews_carried']==[]
    from ravel.physics import agentrivet_source
    out=tmp_path/'ordinary-source-output';out.mkdir()
    source=agentrivet_source.run(spec['task'],tmp_path,out)
    assert not source['physics_validated'] and source['status']=='passed'
    assert source['domain_obligations'] and not read_json(source['capsule']['path'])['dependency_review']['complete']
    with pytest.raises(ValueError,match='never restart'):operation.generate(rp,base_dir=tmp_path,host=actor)
    assert len(seen)==4


def test_failed_dispatch_is_charged_and_never_reissued(tmp_path,monkeypatch):
    _,rp=prepared(tmp_path);seen=[];actor=host(monkeypatch,[RuntimeError('Own ambiguous transport')],seen)
    with pytest.raises((ValueError,RuntimeError)):operation.generate(rp,base_dir=tmp_path,host=actor)
    assert len(seen)==1
    with pytest.raises(ValueError):operation.generate(rp,base_dir=tmp_path,host=actor)
    assert len(seen)==1 and agent_graph.status(tmp_path/'prepared/role-graphs/stage-00')['usage']['calls']==1


@pytest.mark.parametrize('target',['source','message','provider','call'])
def test_returned_generation_requires_ending_source_and_real_role_receipts(tmp_path,monkeypatch,target):
    _,rp,gp,_,_=generated(tmp_path,monkeypatch);doc=read_json(rp['path']);base=tmp_path/'prepared/role-graphs'
    if target=='source':p=Path(doc['upstream']['root'])/'agentrivet/core.py';p.write_text(p.read_text()+'\n# Changed\n')
    elif target=='message':p=base/'messages-00.json';v=read_json(p);v['user']='Another paper';atomic_json(p,v)
    elif target=='provider':p=base/'provider-contract.json';v=read_json(p);v['max_calls']=10;atomic_json(p,v)
    else:
        p=next((base/'stage-00/calls').glob('*.json'));v=read_json(p);v['result']['value']['beam_energy']='wrong';atomic_json(p,v)
    with pytest.raises(ValueError):operation._generation(doc,gp,tmp_path)


def test_retained_generation_reader_never_has_a_dispatch_host(tmp_path,monkeypatch):
    raw,_,_,_,seen=generated(tmp_path,monkeypatch)
    llm=GraphLLM.retained_campaign(tmp_path/'prepared/role-graphs',raw['campaign'])
    assert agentrivet_runtime.generation_outputs(llm)['calls']==4
    with pytest.raises(ValueError,match='cannot dispatch'):llm.generate([{'role':'user','content':'Do not run'}])
    assert len(seen)==4


def test_real_native_feedback_repair_uses_original_triplet_and_preserves_old_outputs(tmp_path,monkeypatch):
    from ravel.workflow import failed_stage_review
    _,rp,gp,actor,seen=generated(tmp_path,monkeypatch);g=read_json(gp['path']);before=Path(gp['path']).read_bytes()
    # Explicit retained-intake validator stand-in: only this engineering test
    # supplies ordinary failure custody; the real product always calls verify.
    failure={'kind':'failed_stage_diagnostic_intake','run_dir':str(tmp_path/'failed'),
        'source_inputs':{g['raw_request']['translation_unit']['path']:{'files':[{'name':'.','sha256':g['raw_request']['translation_unit']['sha256'],'size':len(CODE)}]}}}
    feedback=tmp_path/'feedback.json';atomic_json(feedback,failure)
    validations=[]
    def verify(value,**kwargs):validations.append(deepcopy(value));return value
    monkeypatch.setattr(failed_stage_review,'verify',verify)
    queue=triplet(CODE.decode()+'\n// feedback revision\n')
    def response(data,parameters,request,control,**kwargs):
        seen.append(json.loads(data));return actor._result(queue.pop(0),parameters,request,observed_model='fixture-model',response_id='own-inert-repair')
    monkeypatch.setattr(actor,'_responses',response)
    new=operation.repair(rp,gp,pin(feedback),base_dir=tmp_path,host=actor)
    assert len(seen)==7 and len(validations)==2 and not queue
    result=read_json(new['path']);memory=read_json(result['raw_request']['memory']['path'])
    assert result['predecessor']==gp and result['native_feedback']==pin(feedback) and result['native_repair_count']==1
    assert 'accepted_code' not in memory and memory['iteration']==2 and len(memory['code_draft'])==2
    assert Path(gp['path']).read_bytes()==before and Path(g['raw_request']['translation_unit']['path']).read_bytes()==CODE.strip()
    assert not result['physics_validated'] and result['upstream_reviews_carried']==[]
    with pytest.raises(ValueError):operation.repair(rp,new,pin(feedback),base_dir=tmp_path,host=actor)
    assert len(seen)==7


def test_changed_intended_result_refuses_without_baselining_mutated_bytes(tmp_path,monkeypatch):
    real=operation.state_io.atomic_json;fired=[]
    def mutate(path,value):
        real(path,value)
        if Path(path).name=='construction-request.json':
            v=read_json(path);v['provider']['max_calls']=10;real(path,v);fired.append(True)
    monkeypatch.setattr(operation.state_io,'atomic_json',mutate)
    with pytest.raises(ValueError,match='commitment'):operation.prepare(request(tmp_path),base_dir=tmp_path,output_dir=tmp_path/'prepared')
    assert fired


def test_fresh_runtime_declaration_uses_new_source_not_an_unrelated_capsule(tmp_path,pure_plan):
    from test_agentrivet_source import materialized,complete_capsule,runtime_template
    from ravel.physics import agentrivet_source
    _,_,result,rp=materialized(tmp_path)
    reviewed,closure=complete_capsule(tmp_path,result)
    template,probe=runtime_template(tmp_path,reviewed)
    declaration=tmp_path/'fresh-runtime.json';atomic_json(declaration,{'schema_version':1,'kind':'agentrivet-runtime-declaration','runtime':read_json(template)['runtime']})
    binding=agentrivet_source.prepare_build(rp,pin(reviewed),pin(closure),pin(declaration),probe=probe,base_dir=tmp_path,output_dir=tmp_path/'fresh-build')
    sealed=read_json(binding['sealed']['path'])
    assert sealed['source_capsule']==str(reviewed) and sealed['recipe']['compile_units']==['TEST.cc']
    assert binding['prior_reviews_carried']==[] and not binding['execution_authorized']


def test_close_cannot_replace_public_parent_gate_by_upstream_acceptance(tmp_path,monkeypatch):
    from ravel.workflow import task_completion
    _,rp,gp,_,_=generated(tmp_path,monkeypatch);g=read_json(gp['path'])
    cp=tmp_path/'final.json';atomic_json(cp,{'schema_version':1,'contract':g['goal_binding']['contract'],'outcomes':[],'parent_review':None,'report':None})
    called=[]
    monkeypatch.setattr(task_completion,'require_final',lambda *a,**k:called.append(True))
    with pytest.raises(ValueError,match='assignment outcome'):operation.close(rp,gp,{**pin(cp),'size':cp.stat().st_size},base_dir=tmp_path)
    assert not called


@pytest.mark.parametrize('relative_inputs',[False,True])
def test_coordinator_selects_fresh_missing_routine_without_a_prespecified_graph(tmp_path,monkeypatch,relative_inputs):
    from ravel.workflow import research_tools
    raw=request(tmp_path);campaign=Path(raw['campaign'])
    if relative_inputs:raw['campaign']='campaign'
    rp=tmp_path/'raw-preparation.json';atomic_json(rp,raw)
    request_pin=pin(rp)
    if relative_inputs:request_pin['path']='raw-preparation.json'
    cp=tmp_path/'choice.json';atomic_json(cp,{'kind':'paper-first','request':request_pin})
    choice={**pin(cp),'size':cp.stat().st_size}
    seen=[];actor=host(monkeypatch,[deepcopy(MODEL),*triplet()],seen)
    result=research_tools.routine_workflow(campaign,choice,campaign/'routine-work',actor,max_wall_seconds=60)
    assert len(seen)==4 and result['kind']=='paper-first-routine-research-handoff'
    assert Path(result['preparation_graph']).is_dir()
    assert result['specification']==read_json(result['generation']['path'])['source_study']['specification']
    assert research_cycle._load(campaign)[1]['graphs'][-1]['complete']
    assert len(research_cycle._load(campaign)[1]['resource_ledger'])==5
    assert not result['execution_authorized'] and not result['physics_validated']
    assert result['operations']['feedback_and_completion']['actions']==['prepare-build','prepare-events','repair','close']


def test_coordinator_reuse_preserves_existing_source_and_makes_no_generation_call(tmp_path,monkeypatch):
    from ravel.workflow import research_tools
    raw,rp,gp,actor,seen=generated(tmp_path,monkeypatch);g=read_json(gp['path'])
    cp=tmp_path/'reuse.json';atomic_json(cp,{'kind':'existing-source','specification':g['source_study']['specification']})
    result=research_tools.routine_workflow(raw['campaign'],{**pin(cp),'size':cp.stat().st_size},Path(raw['campaign'])/'unused',actor,max_wall_seconds=60)
    assert result['generation_calls']==0 and len(seen)==4 and result['specification']==g['source_study']['specification']
    assert not (Path(raw['campaign'])/'unused').exists() and not result['execution_authorized']


def test_coordinator_refuses_unknown_or_foreign_operation_without_any_dispatch(tmp_path,monkeypatch):
    from ravel.workflow import research_tools
    raw=request(tmp_path);rp=tmp_path/'raw.json';atomic_json(rp,raw)
    cp=tmp_path/'choice.json';atomic_json(cp,{'kind':'undocumented','request':pin(rp)})
    seen=[];actor=host(monkeypatch,[],seen)
    with pytest.raises(ValueError):research_tools.routine_workflow(raw['campaign'],{**pin(cp),'size':cp.stat().st_size},Path(raw['campaign'])/'work',actor,max_wall_seconds=60)
    assert not seen and not (Path(raw['campaign'])/'work').exists()


def test_public_cli_context_reads_a_pin_envelope_without_dispatch(tmp_path,capsys):
    _,rp=prepared(tmp_path);envelope=tmp_path/'pin.json';atomic_json(envelope,rp)
    assert operation.main(['context','--request',str(envelope),'--base',str(tmp_path)])==0
    result=json.loads(capsys.readouterr().out)
    assert result['request']==rp and not result['execution_authorized']


@pytest.mark.parametrize('member',['memory.json','generation.json'])
def test_intended_original_loop_json_is_verified_before_dependent_source_materialization(tmp_path,monkeypatch,member):
    _,rp=prepared(tmp_path);seen=[];actor=host(monkeypatch,[deepcopy(MODEL),*triplet()],seen)
    real=operation.state_io.atomic_json;fired=[]
    def changed(path,value):
        real(path,value)
        if Path(path).name==member and Path(path).parent.name=='raw':
            altered=read_json(path)
            if member=='memory.json':altered['paper_text']='Unapproved raw Memory paper'
            else:altered['ordinary_scientific_acceptance']=True
            real(path,altered);fired.append(True)
    monkeypatch.setattr(operation.state_io,'atomic_json',changed)
    with pytest.raises(ValueError,match='consumed bytes|original-loop emission'):
        operation.generate(rp,base_dir=tmp_path,host=actor)
    assert fired and len(seen)==4
    assert not (tmp_path/'prepared/generations/initial/source-study').exists()


def test_role_calls_present_only_messages_contract_and_brief_while_custody_keeps_sources(tmp_path,monkeypatch):
    raw,rp,gp,_,seen=generated(tmp_path,monkeypatch)
    contract=read_json(tmp_path/'prepared/role-graphs/provider-contract.json')
    custody={row['path'] for row in contract['source_inputs']}
    assert rp['path'] in custody and any(p.endswith('agentrivet/core.py') for p in custody)
    assert any(p.endswith('COPYING') for p in custody)
    for child in sorted((tmp_path/'prepared/role-graphs').glob('stage-*')):
        spec,_=agent_graph._load(child)
        assert [ref['id'] for ref in spec['nodes'][0]['inputs']] in (['upstream-user-message','operation-contract'],
            ['upstream-user-message','operation-contract','ravel-brief'])
    for request_body in seen:
        text=json.dumps(request_body)
        assert 'Own test source; no third-party GPL body.' not in text   # COPYING never presented
        assert 'def rivetName' not in text and 'def _materialize' not in text
    # The original system prompt is the model instruction, not an input artifact.
    assert any('Own coder instruction' in json.dumps(r) for r in seen)
    assert read_json(gp['path'])['physics_validated'] is False


@pytest.mark.parametrize('member',['source-request.json','science-spec.json'])
def test_existing_source_preparer_retains_intended_emissions(tmp_path,monkeypatch,member):
    from ravel.physics import agentrivet_source
    from test_agentrivet_candidate import fixture
    request_doc=fixture(tmp_path/'original-input')
    real=agentrivet_source.atomic_json;fired=[]
    def changed(path,value):
        real(path,value)
        if Path(path).name==member:
            altered=read_json(path)
            if member=='source-request.json':altered['routine']='OTHER'
            else:altered['source']='Unapproved replacement preparation source'
            real(path,altered);fired.append(True)
    monkeypatch.setattr(agentrivet_source,'atomic_json',changed)
    from test_agentrivet_source import review_wrapper
    with pytest.raises(ValueError,match='consumed bytes|preparation bytes'):
        agentrivet_source.prepare_source_study(request_doc,base_dir=tmp_path,output_dir=tmp_path/'source-preparation',review_policy=review_wrapper(),approval_mode='scripted_yes')
    assert fired


@pytest.mark.parametrize('member',['build-draft.json','build-sealed.json','build-binding.json'])
def test_existing_build_preparer_retains_intended_emissions(tmp_path,monkeypatch,pure_plan,member):
    from ravel.physics import agentrivet_source
    from test_agentrivet_source import materialized,complete_capsule,runtime_template
    _,_,source,rp=materialized(tmp_path)
    reviewed,closure=complete_capsule(tmp_path,source);runtime,probe=runtime_template(tmp_path,reviewed)
    real=agentrivet_source.atomic_json;fired=[]
    def changed(path,value):
        real(path,value)
        if Path(path).name==member:
            altered=read_json(path)
            if member=='build-binding.json':altered['execution_authorized']=True
            else:altered['recipe']['flags']=['-O1']
            real(path,altered);fired.append(True)
    monkeypatch.setattr(agentrivet_source,'atomic_json',changed)
    with pytest.raises(ValueError,match='consumed bytes|preparation bytes'):
        agentrivet_source.prepare_build(rp,pin(reviewed),pin(closure),pin(runtime),probe=probe,base_dir=tmp_path,output_dir=tmp_path/'build-preparation')
    assert fired
