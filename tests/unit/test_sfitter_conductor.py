"""Real Graph/Host with supplied transport outputs, never live models/natives."""
import copy
import json
from pathlib import Path
import pytest
from ravel.workflow import sfitter_conductor as c, agent_graph as graph
from ravel.workflow.agent_host import AgentHost
from test_sfitter_adapter import workflow_fixture, save, pin


class SuppliedHost(AgentHost):
    def __init__(self,value):
        super().__init__(api_key='not-used');self.value=value;self.requests=[]
    def _responses(self,data,parameters,request,control):
        self.requests.append(json.loads(data))
        return self._result(copy.deepcopy(self.value),parameters,request,usage={'input_tokens':1,'output_tokens':1})


def fixture(tmp,phase='extraction'):
    request,docs,_=workflow_fixture(tmp)
    for p in c.workflow.PHASES[:c.workflow.PHASES.index(phase)]:
        request['handoffs'][p]=save(tmp/(p+'.json'),docs[p])
    rp=save(tmp/'request.json',request)
    return request,docs,rp


def proposal(request,phase,disposition='source_draft',handoff=None):
    return {'kind':'sfitter_conductor_proposal','phase':phase,
        'target_sha256':graph.digest(request['target']),'disposition':disposition,'owning_phase':phase,
        'handoff_json':json.dumps(handoff) if handoff else '',
        'documentation_markdown':'# Exact supplied source draft\nOriginal pinned extraction inputs; review pending.\n',
        'findings':[] if disposition=='source_draft' else ['Current stage lacks the required observed production evidence.'],
        'production':[], 'review_approved':False,'execution_authorized':False}


def lead(tmp,request_pin,value,consultations=None):
    cp=c.prepare(request_pin,tmp,tmp/'lead-context',consultations=consultations)
    spec=c.lead_graph(cp,tmp,graph_id='actual_supplied_lead',
        model={'name':'explicit-mock','reasoning_effort':'high','max_output_tokens':4096},max_wall_seconds=60)
    root=tmp/'lead-graph';graph.create(root,spec);host=SuppliedHost(value)
    assert graph.execute(root,host,workers=1)['complete']
    return cp,root,host


def test_actual_consultant_to_conductor_to_phase_file_and_documentation(tmp_path):
    request,docs,rp=fixture(tmp_path)
    consultants=tmp_path/'consultants';spec=c.consultant_graph(request,tmp_path,rp,max_reworks=1)
    graph.create(consultants,spec);ch=SuppliedHost({'claims':['Explicit synthetic advisory return; source facts unqualified']})
    assert graph.execute(consultants,ch,workers=1)['complete']
    cp,root,host=lead(tmp_path,rp,proposal(request,'extraction',handoff=docs['extraction']),consultants)
    context=json.loads(Path(cp['path']).read_bytes())
    assert len(context['consultations'])==3
    assert all(x['review_authority'] is False for x in context['consultations'])
    assert 'sf-reinterpret/SKILL.md' in ''.join(context['skill_texts'])
    assert 'reconcile' in host.requests[0]['instructions'].lower()
    result=c.adopt(root,cp,tmp_path,tmp_path/'adopted')
    new=json.loads(Path(result['workflow_draft']['path']).read_bytes())
    assert set(new['handoffs'])=={'extraction'} and c.workflow._resolve(new,tmp_path)[1]=='sm_template'
    assert result['review_approved'] is False and result['calls_dispatched_by_adoption']==0
    assert (tmp_path/'adopted/documentation/extraction/extraction.md').is_file()
    assert len(graph.status(consultants)['calls'])==3 and len(graph.status(root)['calls'])==1


def test_source_send_back_rewinds_only_owning_phase_suffix_without_dispatch(tmp_path):
    request,docs,rp=fixture(tmp_path,'parameterization')
    value=proposal(request,'parameterization','send_back');value['owning_phase']='sm_template'
    cp,root,_=lead(tmp_path,rp,value)
    result=c.adopt(root,cp,tmp_path,tmp_path/'send-back')
    new=json.loads(Path(result['workflow_draft']['path']).read_bytes())
    assert set(new['handoffs'])=={'extraction'}
    assert request['handoffs'].keys()=={'extraction','sm_template'}
    assert json.loads(Path(rp['path']).read_bytes())==request
    assert graph.status(root)['usage']['calls']==1 and result['calls_dispatched_by_adoption']==0
    assert result['disposition']=='send_back' and result['review_approved'] is False


def test_actual_sm_production_handoff_preserves_mg_and_cluster_contract(tmp_path):
    request,_,rp=fixture(tmp_path,'sm_template')
    value=proposal(request,'sm_template','request_production')
    value['production']=[{'operation':'madgraph_sm','reason':'Need source-bound same-order SM template and systematics weights',
                           'artifact_input_ids':['input1']}]
    cp,root,_=lead(tmp_path,rp,value)
    ctx=json.loads(Path(cp['path']).read_bytes())
    assert any('mg-setup' in key for key in ctx['skill_texts'])
    assert any('cluster-submission' in key for key in ctx['skill_texts'])
    result=c.adopt(root,cp,tmp_path,tmp_path/'production-request')
    assert result['production']==value['production'] and result['execution_authorized'] is False
    assert set(json.loads(Path(result['workflow_draft']['path']).read_bytes())['handoffs'])=={'extraction'}


@pytest.mark.parametrize('change',['target','authority','skill','input_census'])
def test_rehashed_context_cannot_change_science_original_skill_or_whole_inputs(tmp_path,change):
    request,_,rp=fixture(tmp_path)
    cp=c.prepare(rp,tmp_path,tmp_path/'lead-context');ctx=json.loads(Path(cp['path']).read_bytes())
    if change=='target':ctx['target']['process']='different requested physics'
    elif change=='authority':ctx['physics_validated']=True
    elif change=='skill':ctx['skill_texts'][next(iter(ctx['skill_texts']))]+='\nForged original skill.\n'
    else:ctx['inputs'].pop()
    cp=save(Path(cp['path']),ctx)
    with pytest.raises(ValueError):c.lead_graph(cp,tmp_path,graph_id='bad',model=request['model'],max_wall_seconds=60)


@pytest.mark.parametrize('change',['missing_doc','unseen_evidence','future_sendback','unbound_production','false_review'])
def test_no_completion_from_missing_doc_unseen_source_or_false_review(tmp_path,change):
    request,docs,rp=fixture(tmp_path)
    doc=copy.deepcopy(docs['extraction']);value=proposal(request,'extraction',handoff=doc)
    if change=='missing_doc':value['documentation_markdown']=''
    elif change=='unseen_evidence':
        unseen=save(tmp_path/'unseen.json',{'not_presented_to_model':True});doc['sources'].append(unseen)
        value['handoff_json']=json.dumps(doc)
    elif change=='future_sendback':
        value=proposal(request,'extraction','send_back');value['owning_phase']='parameterization'
    elif change=='unbound_production':
        value=proposal(request,'extraction','request_production');value['production']=[{
            'operation':'measurement_extraction','reason':'Missing source evidence','artifact_input_ids':['absent']}]
    else:value['review_approved']=True
    cp=c.prepare(rp,tmp_path,tmp_path/'lead-context')
    spec=c.lead_graph(cp,tmp_path,graph_id='bad-lead',model=request['model'],max_wall_seconds=60)
    root=tmp_path/'lead-graph';graph.create(root,spec)
    status=graph.execute(root,SuppliedHost(value),workers=1)
    with pytest.raises((ValueError,RuntimeError)):c.adopt(root,cp,tmp_path,tmp_path/'refused')
    assert not (tmp_path/'refused/adoption-receipt.json').exists()


def test_consultants_must_refer_to_current_phase_target_and_completed_generation(tmp_path):
    request,_,rp=fixture(tmp_path)
    consultants=tmp_path/'consultants';graph.create(consultants,c.consultant_graph(request,tmp_path,rp))
    with pytest.raises(ValueError):c.prepare(rp,tmp_path,tmp_path/'pending-context',consultations=consultants)
    graph.execute(consultants,SuppliedHost({'claims':['Explicit synthetic return']}),workers=1)
    changed=copy.deepcopy(request);changed['target']['process']='other process';rp2=save(tmp_path/'other-request.json',changed)
    with pytest.raises(ValueError):c.prepare(rp2,tmp_path,tmp_path/'wrong-context',consultations=consultants)


def test_late_generated_workflow_mutation_cannot_emit_adoption_receipt(tmp_path,monkeypatch):
    request,docs,rp=fixture(tmp_path)
    cp,root,_=lead(tmp_path,rp,proposal(request,'extraction',handoff=docs['extraction']))
    out=tmp_path/'adopted';original=c.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='proposal.json':
            p=out/'workflow-draft.json';p.write_bytes(p.read_bytes()+b'\n')
    monkeypatch.setattr(c,'atomic_json',mutate)
    with pytest.raises(ValueError):c.adopt(root,cp,tmp_path,out)
    assert not (out/'adoption-receipt.json').exists()


def test_review_seam_delegates_to_existing_protocol_without_local_verdict(tmp_path,monkeypatch):
    from types import SimpleNamespace
    request,docs,rp=fixture(tmp_path)
    cp,root,_=lead(tmp_path,rp,proposal(request,'extraction',handoff=docs['extraction']))
    c.adopt(root,cp,tmp_path,tmp_path/'adopted')
    ap=pin(tmp_path/'adopted/adoption-receipt.json')
    adopted=json.loads(Path(ap['path']).read_bytes())
    pr=save(tmp_path/'protocol-request.json',{'workflow':adopted['workflow_draft'],'stage':'extraction'})
    binding={'schema_version':1,'kind':'sfitter_domain_binding','request':pr,
             'report':pr,'case':pr,'judgment':{'explicit_control_binding':True},
             'execution_authorized':False,'physics_validated':False}
    calls=[]
    protocol=SimpleNamespace(
        context=lambda request,base:calls.append(('context',request,base)),
        prepare_role=lambda *args,**kwargs:calls.append(('prepare_role',args,kwargs)) or binding,
        consume=lambda *args:calls.append(('consume',args)) or {'existing_judgment':'send_back'},
        rework=lambda *args:calls.append(('rework',args)) or {'existing_judgment':'new_source_draft'})
    monkeypatch.setattr(c,'_domain_protocol',lambda:protocol)
    assert c.prepare_role(ap,pr,tmp_path,tmp_path/'ordinary-study',tmp_path/'role',role='verifier')==binding
    assert c.consume_review(ap,pr,tmp_path,tmp_path/'ordinary-study',binding)['existing_judgment']=='send_back'
    assert c.rework_review(ap,pr,tmp_path,tmp_path/'ordinary-study',binding,tmp_path/'rework')['existing_judgment']=='new_source_draft'
    assert [x[0] for x in calls]==['context','prepare_role','context','consume','context','rework']
    assert graph.status(root)['usage']['calls']==1
    wrong=save(tmp_path/'other-protocol.json',{'workflow':rp,'stage':'extraction'})
    with pytest.raises(ValueError):c.prepare_role(ap,wrong,tmp_path,tmp_path/'study',tmp_path/'role',role='critic')
    bad={**binding,'request':wrong}
    with pytest.raises(ValueError):c.consume_review(ap,pr,tmp_path,tmp_path/'ordinary-study',bad)


def test_conductor_output_cannot_change_original_source_or_graph_directory(tmp_path):
    request,docs,rp=fixture(tmp_path)
    source=Path(request['upstream_tree']['root'])
    original=set(source.rglob('*'))
    with pytest.raises(ValueError):c.prepare(rp,tmp_path,source/'forbidden-conductor')
    assert set(source.rglob('*'))==original
    cp,root,_=lead(tmp_path,rp,proposal(request,'extraction',handoff=docs['extraction']))
    original=set(root.rglob('*'))
    with pytest.raises(ValueError):c.adopt(root,cp,tmp_path,root/'forbidden-adoption')
    assert set(root.rglob('*'))==original


def test_late_context_mutation_cannot_return_a_prepared_context(tmp_path,monkeypatch):
    _,_,rp=fixture(tmp_path);original=c.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='context.json':
            doc=json.loads(Path(path).read_bytes());doc['target']['process']='late altered process'
            Path(path).write_text(json.dumps(doc))
    monkeypatch.setattr(c,'atomic_json',mutate)
    with pytest.raises(ValueError):c.prepare(rp,tmp_path,tmp_path/'context')


@pytest.mark.parametrize('target',['request','workflow'])
def test_final_receipt_callback_cannot_mutate_prior_input_or_generated_output(tmp_path,monkeypatch,target):
    request,docs,rp=fixture(tmp_path);cp,root,_=lead(tmp_path,rp,proposal(request,'extraction',handoff=docs['extraction']))
    output=tmp_path/'adopted';original=c.atomic_json
    def mutate(path,value):
        original(path,value)
        if Path(path).name=='adoption-receipt.json':
            p=Path(rp['path']) if target=='request' else output/'workflow-draft.json'
            p.write_bytes(p.read_bytes()+b'\n')
    monkeypatch.setattr(c,'atomic_json',mutate)
    with pytest.raises(ValueError):c.adopt(root,cp,tmp_path,output)
