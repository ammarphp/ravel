"""Authored/unrun. Full source-to-mocked-wire transport, never model efficacy.

Real cycle/history/Graph accounting and writer verifiers are retained. Only the
HTTP transport returns declared synthetic prose/usage, as in the original case.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_production as mp, manuscript_workflow as mw
from ravel.workflow import agent_host, research_cycle as cycle, state_io
from test_manuscript_production import setup, put
from test_manuscript_historical_origin import actual_campaign_setup
from test_provider_transport import install_http
from test_visual_presentation import provider_host


def test_actual_complete_phase_transcript_uses_full_artifact_provider_context(tmp_path,monkeypatch):
    import test_manuscript_historical_origin as historical
    from test_manuscript_objection_actions import test_complete_actual_phase_transcript_origin_after_context_advance as original
    wires=[];install=historical.install_http
    def capture(*args,**kwargs):
        seen=install(*args,**kwargs);wires.append(seen);return seen
    monkeypatch.setattr(historical,'install_http',capture)
    original(tmp_path,monkeypatch)  # exact original complete/history assertions
    assert len(wires)==7 and all(len(w)==1 for w in wires)
    for i,seen in enumerate(wires):
        root=tmp_path/'workflow/issued'/('phase'+str(i));body=seen[0]['body']
        binding=state_io.read_json(root/'binding.json')
        assert binding['context_transport']=='source-artifact-v1'
        assert len(body['instructions'])<100000
        sent=json.loads(body['input'][0]['content'])['input_artifacts']
        assert {r['id'] for r in sent}=={'context','request'}
        for row in sent:
            pin=binding['presentation' if row['id']=='context' else 'request']
            assert row['sha256']==pin['sha256']
            assert row['content']==Path(pin['path']).read_text()
    binding=state_io.read_json(tmp_path/'workflow/issued/phase6/binding.json')
    complete=json.loads(next(r['content'] for r in sent if r['id']=='context'))
    transcript=complete['writing_transcript']
    assert [p['phase_id'] for p in transcript['actual_prior_phases']]==['phase'+str(i) for i in range(6)]
    for pin,product in zip(transcript['phase_products'],transcript['actual_prior_phases']):
        assert product==state_io.read_json(pin['path'])
        assert {'output','actual_receipt','actual_calls','actual_usage','input_pins','source_epoch','visual_presentation'}<=set(product)
    assert len(mp._instructions({'author_id':'toy-writer'},complete))>100000
    assert binding_request(binding)['runtime']['max_context_bytes']==400000
    assert mp._context_bound(binding_request(binding)['runtime'],binding['spec']['nodes'][0]['parameters']['instructions'],
        binding['presentation'],binding['request'],tmp_path,context_transport=binding['context_transport'])<=binding_request(binding)['runtime']['max_context_bytes']


def binding_request(binding):return state_io.read_json(binding['request']['path'])


def test_large_complete_ordinary_source_is_sent_as_data_not_instructions(tmp_path,monkeypatch):
    request,value,campaign,_=actual_campaign_setup(tmp_path,monkeypatch)
    source='Complete retained method context.\n'+('Known source data; unresolved fit.\n'*4000)+'END-WHOLE-SOURCE'
    request['skills'].append(put(tmp_path/'source','large-method.md',source))
    binding=mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path/'source',campaign=campaign)
    response={'status':'completed','model':'observed-snapshot','id':'synthetic-full-context',
        'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value)}]}],
        'usage':{'input_tokens':10,'output_tokens':7,'total_tokens':17}}
    seen=install_http(monkeypatch,response)
    state=mp.execute_writer(binding,provider_host('responses'))
    assert state['complete'] and len(seen)==1
    body=seen[0]['body'];context=json.loads(body['input'][0]['content'])
    text=next(r['content'] for r in context['input_artifacts'] if r['id']=='context')
    assert text==Path(binding['presentation']['path']).read_text()
    assert source in json.loads(text)['skills'] and source not in body['instructions']
    assert len(mp._instructions(request,json.loads(text)))>100000 and len(body['instructions'])<100000
    assert mp.collect(binding,tmp_path/'note')['package']['scientific_acceptance'] is False


@pytest.mark.parametrize('kind',['writer','phase'])
def test_artifact_transport_bounds_complete_data_before_any_host_call(tmp_path,monkeypatch,kind):
    if kind=='writer':
        request,state,_=setup(tmp_path,monkeypatch)
        request['skills'].append(put(tmp_path,'large.md','Whole required source.\n'*5000))
        request['runtime']['max_context_bytes']=8000
        with pytest.raises(ValueError,match='whole author context exceeds'):
            mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    else:
        from test_staged_manuscript_authoring import case
        pin,document,production,_,_=case(tmp_path/'staged',monkeypatch)
        production['skills'].append(put(tmp_path/'staged','large.md','Whole required source.\n'*5000))
        production['runtime']['max_context_bytes']=8000
        document['production_request']=put(tmp_path/'staged','bounded-production.json',production)
        for slot in document['phase_slots']:slot['runtime']['max_context_bytes']=8000
        document['budget']['max_context_bytes']=8000
        changed=put(tmp_path/'staged','tiny.json',document)
        with pytest.raises(ValueError,match='whole author context exceeds'):
            mw.prepare_story(changed,tmp_path/'workflow',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert not list(tmp_path.rglob('calls/*.json'))


@pytest.mark.parametrize('fault',['unknown-version','omitted-version','changed-data'])
def test_phase_transport_version_and_complete_data_are_reconstructed(tmp_path,monkeypatch,fault):
    from test_staged_manuscript_authoring import consumed_story
    story,_,_,_,_,_,_=consumed_story(tmp_path,monkeypatch)
    prepared=mw.prepare_phase(story,'phase1',tmp_path/'workflow/issued/phase1',base_dir=tmp_path,
        campaign=tmp_path/'campaign',prior_products=[story])
    binding=deepcopy(prepared['binding'])
    if fault=='unknown-version':binding['context_transport']='hashes-only'
    elif fault=='omitted-version':binding.pop('context_transport')
    else:
        path=Path(binding['presentation']['path']);context=state_io.read_json(path)
        context['prior_actual_products'][0]['output']['claim_map'][0]['text']='Changed complete evidence.'
        path.write_text(json.dumps(context));binding['presentation']=mp._pin(path)
    saved=Path(binding['graph']).parent/'binding.json';saved.write_text(json.dumps(binding))
    with pytest.raises(ValueError):mw._phase_state(binding,require_complete=False)
    assert not (saved.parent/'consumed').exists()


@pytest.mark.parametrize('kind',['writer','phase'])
def test_legacy_inline_bindings_keep_exact_instruction_reconstruction(tmp_path,monkeypatch,kind):
    if kind=='writer':
        from test_manuscript_production import completed
        request,state,value=setup(tmp_path,monkeypatch)
        binding=mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
        binding.pop('context_transport')
        binding['spec']['nodes'][0]['parameters']['instructions']=mp._instructions(request,state_io.read_json(binding['presentation']['path']))
        state_io.atomic_json(Path(binding['graph'])/'graph_spec.json',binding['spec'])
        state_io.atomic_json(Path(binding['graph']).parent/'binding.json',binding)
        completed(binding,state,value,monkeypatch)
        mp.collect(binding,tmp_path/'legacy-note')
        assert 'Toy squares' in binding['spec']['nodes'][0]['parameters']['instructions']
    else:
        from test_staged_manuscript_authoring import case
        pin,_,_,_,_=case(tmp_path,monkeypatch)
        prepared=mw.prepare_story(pin,tmp_path/'workflow',base_dir=tmp_path,campaign=tmp_path/'campaign')
        binding=prepared['binding'];binding.pop('context_transport')
        binding['spec']['nodes'][0]['parameters']['instructions']=mw._instructions(state_io.read_json(binding['presentation']['path']))
        state_io.atomic_json(Path(binding['graph'])/'graph_spec.json',binding['spec'])
        state_io.atomic_json(Path(binding['graph']).parent/'binding.json',binding)
        mw._phase_state(binding,require_complete=False)
        assert 'known_sources' in binding['spec']['nodes'][0]['parameters']['instructions']


@pytest.mark.parametrize('fault',['unknown-version','changed-context'])
def test_writer_context_version_and_hash_refuse_before_charge(tmp_path,monkeypatch,fault):
    request,_,campaign,state=actual_campaign_setup(tmp_path,monkeypatch)
    binding=mp.prepare_writer(request,tmp_path/'writer',base_dir=tmp_path/'source',campaign=campaign)
    if fault=='unknown-version':binding['context_transport']='incomplete-summary'
    else:
        path=Path(binding['presentation']['path']);path.write_text(path.read_text()+' Changed evidence.')
    before=cycle._load(campaign)[1]
    with pytest.raises(ValueError):mp.execute_writer(binding,object())
    assert cycle._load(campaign)[1]==before and cycle._usage(before)['calls']==0
