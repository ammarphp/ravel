"""UNRUN connected ancestry checks, real Graph receipts with inert supplied responses.

Scientific context/campaign/feedback use disclosed inherited stand-ins. The real
writer/materialization/role/external/packet consumers are never replaced. Model
responses are test data; visual HTTP is a mocked local wire, not model inference.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_production as mp, agent_graph as graph
from ravel.workflow.state_io import atomic_json, read_json
from test_manuscript_production import setup, pin, put
from test_manuscript_revision_origin import revise
from test_external_writer_accounting import author
from test_visual_presentation import provider_host, vision
from test_provider_transport import install_http


def visual_author(root,monkeypatch):
    from PIL import Image
    request,state,value=setup(root/'source',monkeypatch)
    image=root/'source/figure.png'
    with Image.new('RGB',(8,6),(0,0,255)) as pixels:pixels.save(image)
    request['figures']=[{'id':'toy','image':pin(image),'contract':put(root/'source','figure-contract.json',{'synthetic':True}),
        'evidence_ids':['score'],'comparison':None}]
    value['figures']=[{'id':'toy','caption':'Supplied engineering pixels; no scientific claim.','citation_ids':[],'uncertainties':['Fixture only.']}]
    request['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot')
    binding=mp.prepare_writer(request,root/'writer',base_dir=root/'source',campaign=root/'campaign')
    finish_visual(binding,state,value,monkeypatch)
    return request,state,binding,value,None


def finish_visual(binding,state,value,monkeypatch):
    response={'status':'completed','model':'observed-snapshot','id':'inert-author-wire','output':[{'type':'message','role':'assistant',
        'content':[{'type':'output_text','text':json.dumps(value)}]}],'usage':{'input_tokens':10,'output_tokens':7,'total_tokens':17}}
    seen=install_http(monkeypatch,response)
    current=graph.execute(binding['graph'],provider_host('responses',vision=vision()))
    assert current['complete'] and len(seen)==1
    state['graphs'].append({'root':binding['graph'],'complete':True});state['sha256']=mp.ce.digest(state['graphs'])


def finish_external(binding,state,value,root):
    prepared=graph.prepare_external(binding['graph'],'author')
    response={'schema_version':1,'request_id':prepared['request_id'],'request_sha256':prepared['request_sha256'],
        'invocation_id':'supplied-revision-invocation','actor_id':'toy-writer','observed_model':'synthetic-build',
        'fresh_context':True,'parent_transcript_supplied':False,'value':value}
    path=root/'response.json';atomic_json(path,response);graph.deliver_external(binding['graph'],'author',path)
    state['graphs'].append({'root':binding['graph'],'complete':True});state['sha256']=mp.ce.digest(state['graphs'])
    return path


def ancestry(root,monkeypatch,visual):
    request,state,b0,value,response=(visual_author if visual else author)(root,monkeypatch)
    a0=mp.collect(b0,root/'note')
    first=revise(root/'first-input',request,a0['package'],monkeypatch)
    b1=mp.prepare_writer(first,root/'first',base_dir=root/'source',campaign=root/'campaign')
    if visual:finish_visual(b1,state,value,monkeypatch)
    else:finish_external(b1,state,value,root/'first')
    a1=mp.collect(b1,root/'first-note')
    second=revise(root/'second-input',request,a1['package'],monkeypatch)
    return request,state,b0,a0,b1,a1,second,response


def mutate_after_first_ancestor_load(monkeypatch,a0,change):
    original=mp._load;trigger=[]
    def load(request,*args,**kwargs):
        loaded=original(request,*args,**kwargs)
        revision=request.get('revision')
        if (not trigger and revision is not None and mp.ce.digest(read_json(revision['previous_package']['path']))==mp.ce.digest(a0['package'])
                and mp._REVISION_VERIFICATION.get() is not None):
            assert any(k[1]==mp.ce.digest(a0['package']) for k in mp._REVISION_VERIFICATION.get()['verified'])
            trigger.append(True);change()
        return loaded
    monkeypatch.setattr(mp,'_load',load)
    return trigger


@pytest.mark.parametrize('fault',['external-request-change','external-request-missing','external-response-change','external-response-missing',
    'copied-visual-change','copied-visual-missing','packet-extra-member'])
@pytest.mark.parametrize('route',['prepare','execute'])
def test_late_original_authority_mutation_in_public_second_revision_refuses(tmp_path,monkeypatch,fault,route):
    visual=fault.startswith('copied-visual') or fault=='packet-extra-member'
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,visual)
    if route=='execute':b2=mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    if fault.startswith('external-request'):
        checkpoint=graph.status(b0['graph']);target=Path(b0['graph'])/checkpoint['nodes']['author']['external_request']['path']
    elif fault.startswith('external-response'):target=response
    elif fault.startswith('copied-visual'):
        manifest=read_json(Path(b0['packet']['path'])/'manifest.json');target=Path(b0['packet']['path'])/manifest['artifacts'][0]['path']
    else:target=Path(b0['packet']['path'])/'artifacts/foreign.txt'
    initial_usage=graph.status(b0['graph'])['usage']
    def change():
        if fault.endswith('missing'):target.unlink()
        elif fault=='packet-extra-member':target.write_text('Extra unadmitted packet member.')
        elif fault=='external-request-change':
            document=read_json(target)
            document['parameters']['instructions']+=' Altered original author instructions.'
            atomic_json(target,document)
        else:target.write_bytes(target.read_bytes()+b' ')
    trigger=mutate_after_first_ancestor_load(monkeypatch,a0,change)
    with pytest.raises((ValueError,graph.GraphError)):
        if route=='prepare':mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
        else:mp.execute_writer(b2,object())
    assert trigger==[True] and mp._REVISION_VERIFICATION.get() is None
    if route=='prepare':assert not (tmp_path/'second').exists()
    else:assert graph.status(b2['graph'])['usage']=={'calls':0,'reserved_output_tokens':0}
    assert graph.status(b0['graph'])['usage']==initial_usage


def test_distinct_retained_feedback_rejects_foreign_case_without_replacing_verifier(tmp_path,monkeypatch):
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,False)
    wrong=deepcopy(second)
    first_request=read_json(b1['request']['path'])
    wrong['revision']['feedback_binding']=first_request['revision']['feedback_binding']
    with pytest.raises(ValueError,match='exact prior manuscript request'):
        mp.prepare_writer(wrong,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert not (tmp_path/'second').exists()


def test_later_campaign_charge_does_not_become_permanent_ancestor_input_pin(tmp_path,monkeypatch):
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,False)
    state['sha256']='e'*64;state['graphs'].append({'root':str(tmp_path/'other-completed-step'),'complete':True})
    binding=mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert binding['spec']['nodes'][0]['role']=='improver'
    assert all('research_state.json' not in p['path'] for p in binding['input_pins'])
    assert mp._REVISION_VERIFICATION.get() is None


def test_late_live_source_review_refusal_is_not_cached_authority(tmp_path,monkeypatch):
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,False)
    check=mp._check_source_review;late=[]
    def live(loaded):
        if late and loaded['request']['revision'] is None:raise ValueError('late original source-review refusal')
        return check(loaded)
    monkeypatch.setattr(mp,'_check_source_review',live)
    trigger=mutate_after_first_ancestor_load(monkeypatch,a0,lambda:late.append(True))
    with pytest.raises(ValueError,match='late original source-review refusal'):
        mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert trigger==[True] and not (tmp_path/'second').exists()


def test_late_original_completed_campaign_association_is_rechecked(tmp_path,monkeypatch):
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,False)
    def change():state['graphs']=[g for g in state['graphs'] if g['root']!=b0['graph']]
    trigger=mutate_after_first_ancestor_load(monkeypatch,a0,change)
    with pytest.raises(ValueError,match='accounted author graph is not a completed campaign step'):
        mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert trigger==[True] and not (tmp_path/'second').exists()


def test_canonical_external_request_whitespace_preserves_original_semantic_identity(tmp_path,monkeypatch):
    request,state,b0,a0,b1,a1,second,response=ancestry(tmp_path,monkeypatch,False)
    before=graph.status(b0['graph'])
    original_receipt=mp.verify_author_origin(a0['package'],base_dir=tmp_path/'source')
    reference=before['nodes']['author']['external_request']
    target=Path(b0['graph'])/reference['path'];raw=target.read_bytes()
    trigger=mutate_after_first_ancestor_load(monkeypatch,a0,lambda:target.write_bytes(raw+b' '))
    binding=mp.prepare_writer(second,tmp_path/'second',base_dir=tmp_path/'source',campaign=tmp_path/'campaign')
    assert trigger==[True] and mp._REVISION_VERIFICATION.get() is None
    assert target.read_bytes()==raw+b' '
    assert graph.digest(read_json(target))==reference['sha256']
    assert graph.status(b0['graph'])==before
    assert graph.status(binding['graph'])['usage']=={'calls':0,'reserved_output_tokens':0}
    assert mp.verify_author_origin(a0['package'],base_dir=tmp_path/'source')==original_receipt
