"""Unexecuted software controls. Synthetic campaign/model receipts are explicit.

Real image-to-native-wire/source/PDF page qualification uses the original actual
visual controls separately. No fabricated reference is a scientific result.
"""
from copy import deepcopy
from pathlib import Path
import json
import pytest
from ravel.workflow import manuscript_workflow as mw, manuscript_production as mp
from ravel.workflow import agent_graph, manuscript_format, scientific_report, research_cycle
from test_manuscript_production import setup, put, pin, loc


def case(root,monkeypatch,*,missing=False,context_bytes=250000):
    production,state,final=setup(root,monkeypatch)
    # Only an expressly selected connected fixture changes its declared capacity.
    # The original 250000-byte setup/default and every production limit stay exact.
    if context_bytes!=250000:production['runtime']['max_context_bytes']=context_bytes
    state['contract']['budget']={'calls':20,'output_tokens':100000,'wall_seconds':2000,'native_attempts':0}
    state['resource_ledger']=[]
    monkeypatch.setattr(scientific_report,'compose',lambda *a,**k:{'report_text':'Requested score: 4; failed fit unresolved.\n',
        'requested_quantity_completion':False,'expected_slots':{'score':{'fact_id':'score','value':4,'unit':'1','scope':'toy','population':'whole supplied toy'}},'facts':[]})
    obligation=[]
    if missing:
        production['citations']=[]
        source=put(root,'obligation.txt','The current method needs its missing Toy squares primary citation; no acquisition has occurred.')
        obligation=[{'id':'toy','kind':'citation','description':'Acquire exact located bibliography, retain acquisition failure.',
            'located':loc(source,Path(source['path']).read_text())}]
    prod=put(root,'production.json',production)
    kinds=['story','citation-scout','caption','section','coherence','editorial-revision','synthesis'];slots=[]
    for i,kind in enumerate(kinds):slots.append({'id':'phase'+str(i),'kind':kind,'depends_on':[] if i==0 else [s['id'] for s in slots] if kind=='synthesis' else ['phase0'], 'runtime':deepcopy(production['runtime'])})
    request={'schema_version':2,'kind':'staged-manuscript-request','production_request':prod,'missing':obligation,'phase_slots':slots,
        'budget':{'max_calls':7,'max_input_tokens':112000,'max_output_tokens':28672,'max_wall_seconds':420,'max_context_bytes':context_bytes,'max_revisions':1}}
    req=put(root,'staged.json',request)
    final['paragraphs'][-1]['text']+=' Scope: whole supplied toy. Not a scientific/model outcome.'
    return req,request,production,state,final


def plan(current):
    p=mw._population(current);sections=sorted(p['section']);missing=list(current['missing'])
    return {'claim_map':[{'id':'main','text':'A source-grounded toy claim with failed fit retained.','status':'conditional','scope':'whole supplied toy',
        'evidence_ids':sorted(p['evidence']),'counterevidence_ids':[],'method_ids':sorted(p['method']),'quantity_ids':sorted(p['quantity']),
        'citation_ids':sorted(p['citation']),'limitations':['Not a scientific/model outcome.'],'section_ids':sections}],
        'plotting_plan':[],'intro_related_work_plan':[{'id':'macro','macro_context':'Toy only','methodology_cluster':'pure square',
        'located_citation_ids':list(current['loaded']['citations']),'limitation_hypothesis':'No inference beyond toy','counterevidence_ids':[],
        'bridge':'Source-only engineering example','acquisition_obligation_ids':[i for i,r in current['missing'].items() if r['kind']=='citation']}],
        'section_plan':[{'id':s,'purpose':'Source-located section','claim_ids':['main'],'method_ids':sorted(p['method']),
        'evidence_ids':sorted(p['evidence']),'citation_ids':sorted(p['citation']),'figure_ids':[],'dependency_section_ids':[],
        'content_bullets':['Use exact supplied evidence; no numeric invention.']} for s in sections],
        'phases':[{'id':s['id'],'section_ids':(['title','abstract','methods','results','limitations'] if s['kind']=='section' else sections),
            'claim_ids':['main'],'figure_ids':[],'obligation_ids':missing} for s in current['slots']],
        'unresolved':missing}


def claim_fixture(binding,value):
    """Explicit inert model output for the new claim schema; not acceptance."""
    context=json.loads(Path(binding['presentation']['path']).read_text())
    if binding.get('kind')=='manuscript-phase-binding':
        if binding['plan'] is None:return
        story=json.loads(Path(binding['plan']['path']).read_text())['output']
        roster=next(r for r in story['phases'] if r['id']==binding['phase_id'])['claim_ids']
        available=context['known_sources']['sources']
        final=False
    elif 'planned_claim_context' in context:
        story=context['planned_claim_context']['plan'];roster=[r['id'] for r in story['claim_map']]
        available=context['sources'];final=True
    else:return
    if final:
        note=next(p for p in value['paragraphs'] if p['section']=='limitations')
        for claim in story['claim_map']:
            for text in [claim['scope'],*claim['limitations']]:
                if text not in note['text']:note['text']+=' '+text
            for identity in claim['evidence_ids']+claim['counterevidence_ids']:
                if identity not in note['evidence_ids']:note['evidence_ids'].append(identity)
    rows=[]
    for claim in story['claim_map']:
        if claim['id'] not in roster:continue
        targets=[p['id'] for p in value['paragraphs'] if p['kind']=='claim' and claim['scope'] in p['text']]
        reason=claim['scope'] if targets else 'No conclusion in this phase; the source-qualified claim remains unresolved.'
        rows.append({'planned_claim_id':claim['id'],'original':deepcopy(claim),'disposition':'qualified' if targets else 'unresolved',
            'paragraph_ids':targets,'figure_ids':[],'related_claim_ids':[],'reason':reason,
            'evidence_ids':deepcopy(claim['evidence_ids']),'counterevidence_ids':deepcopy(claim['counterevidence_ids']),
            'unresolved_evidence_ids':[i for i in dict.fromkeys(claim['evidence_ids']+claim['counterevidence_ids']) if i not in available],
            'limitations':[{'index':i,'text':text,'paragraph_ids':[p['id'] for p in value['paragraphs'] if p['id'] in targets and text in p['text']],'figure_ids':[]} for i,text in enumerate(claim['limitations'])]})
    value['claim_dispositions']=rows


def complete(prepared,state,value,monkeypatch,registry):
    b=prepared['binding'];claim_fixture(b,value)
    graph=b['graph'];state['graphs'].append({'root':graph,'complete':True})
    state['sha256']=mp.ce.digest({'synthetic_completed_graphs':state['graphs']})
    receipt={'execution_observation':'remote_transport_observed','public_value':deepcopy(value),'transport':{'observed_model':'synthetic-build','actor_id':'toy-writer'}}
    saved={'result':{'usage':{'input_tokens':100,'output_tokens':200,'total_tokens':300},'transport':deepcopy(receipt['transport'])},'call_receipts':[]}
    call={'kind':'model','status':'completed','result':deepcopy(saved['result']),'output_tokens_reserved':4096}
    callpath=Path(graph)/'calls/synthetic.json';callpath.parent.mkdir(exist_ok=True);callpath.write_text(json.dumps(call)+'\n')
    saved['call_receipts']=[{'call_id':'synthetic','sha256':mp.ce.digest(call)}]
    registry[graph]=(receipt,saved)
    monkeypatch.setattr(agent_graph,'role_receipt',lambda g,*a,**k:deepcopy(registry[str(g)][0]))
    monkeypatch.setattr(agent_graph,'status',lambda g,*a,**k:{'nodes':{'author':{'result':'inert','status':'completed'}},'started_epoch':100.0,'calls':{},'usage':{'calls':1,'reserved_output_tokens':4096}})
    monkeypatch.setattr(agent_graph,'_result',lambda g,*a,**k:deepcopy(registry[str(g)][1]))
    return registry[graph]


def consumed_story(root,monkeypatch,*,missing=False,context_bytes=250000):
    req,d,r,state,final=case(root,monkeypatch,missing=missing,context_bytes=context_bytes);current=mw._load(req,root)
    prepared=mw.prepare_story(req,root/'workflow',base_dir=root,campaign=root/'campaign');registry={}
    complete(prepared,state,plan(current),monkeypatch,registry)
    result=mw.consume_phase(prepared,root/'workflow/issued/phase0/consumed',base_dir=root)
    return result['product'],req,d,r,state,final,registry


def test_actual_story0_preparation_is_not_consumed_plan(tmp_path,monkeypatch):
    req,d,r,state,final=case(tmp_path,monkeypatch,missing=True)
    prepared=mw.prepare_story(req,tmp_path/'workflow',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert prepared['binding']['plan'] is None and not (tmp_path/'workflow/issued/phase0/consumed').exists()
    source_context=Path(prepared['binding']['presentation']['path']).read_text()
    assert 'missing_obligations' in source_context
    assert 'retain acquisition failure' in source_context
    with pytest.raises((ValueError,KeyError)):mw.verify_story(prepared['binding_pin'],base_dir=tmp_path,campaign=tmp_path/'campaign')


def test_initial_incomplete_bibliography_plans_but_final_loader_refuses(tmp_path,monkeypatch):
    req,d,r,state,final=case(tmp_path,monkeypatch,missing=True)
    assert mw._load(req,tmp_path)['missing']['toy']['kind']=='citation'
    with pytest.raises(ValueError,match='bibliography incomplete'):mp._load(r,tmp_path)


@pytest.mark.parametrize('change',['citation','method','quantity','evidence','section','phase','unresolved','claim-foreign','plot-foreign'])
def test_complete_original_story_populations_cannot_be_dropped_or_forged(tmp_path,monkeypatch,change):
    req,d,r,state,final=case(tmp_path,monkeypatch,missing=True);current=mw._load(req,tmp_path);v=plan(current)
    if change in {'citation','method','quantity','evidence'}:
        field=change+'_ids';v['claim_map'][0][field]=[]
        for section in v['section_plan']:
            if field in section:section[field]=[]
    elif change=='section':v['section_plan'].pop()
    elif change=='phase':v['phases'].pop()
    elif change=='unresolved':v['unresolved']=[]
    elif change=='claim-foreign':v['claim_map'][0]['method_ids']=['foreign']
    else:v['plotting_plan']=[{'id':'fake'}]
    with pytest.raises(ValueError):mw._plan(v,current)


@pytest.mark.parametrize('change',['duplicate','reorder','missing-story','missing-terminal','drop-dependency','calls','output','wall','policy','missing-obligation'])
def test_fixed_phase_and_original_budget_refusals(tmp_path,monkeypatch,change):
    req,d,r,state,final=case(tmp_path,monkeypatch,missing=True)
    if change=='duplicate':d['phase_slots'][1]['id']='phase0'
    elif change=='reorder':d['phase_slots'][1]['depends_on']=['phase2']
    elif change=='missing-story':d['phase_slots'][0]['kind']='section'
    elif change=='missing-terminal':d['phase_slots'][-1]['kind']='coherence'
    elif change=='drop-dependency':d['phase_slots'][-1]['depends_on']=['phase0']
    elif change=='calls':d['budget']['max_calls']=6
    elif change=='output':d['budget']['max_output_tokens']=1
    elif change=='wall':d['budget']['max_wall_seconds']=1
    elif change=='policy':d['phase_slots'][1]['runtime'].update(usage_policy='reserved_unknown',max_output_bytes=10000)
    elif change=='missing-obligation':d['missing']=[]
    req=put(tmp_path,'staged.json',d)
    with pytest.raises(ValueError):mw._load(req,tmp_path)


def test_actual_story_phase_scope_and_unique_issuance(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    prepared=mw.prepare_phase(story,'phase1',tmp_path/'workflow/issued/phase1',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])
    assert prepared['binding']['plan']==story and prepared['binding']['spec']['budget']['max_calls']==1
    with pytest.raises(ValueError,match='fresh'):mw.prepare_phase(story,'phase1',tmp_path/'workflow/issued/phase1',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])
    with pytest.raises(ValueError,match='exact original slot'):mw.prepare_phase(story,'phase2',tmp_path/'foreign',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])


def test_complete_real_section_phase_consumer_and_source_drift(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    prepared=mw.prepare_phase(story,'phase3',tmp_path/'workflow/issued/phase3',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])
    value={'paragraphs':deepcopy(final['paragraphs']),'figures':[],'tasks':[],'unresolved':[]}
    complete(prepared,state,value,monkeypatch,registry)
    product=mw.consume_phase(prepared,tmp_path/'workflow/issued/phase3/consumed',base_dir=tmp_path)['product']
    verified=mw.verify_product(product,base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert verified['output']['paragraphs']==final['paragraphs'] and verified['actual_usage']['usage']['total_tokens']==300
    (tmp_path/'score.py').write_text('mutated source')
    with pytest.raises(ValueError):mw.verify_product(product,base_dir=tmp_path,campaign=tmp_path/'campaign')


def test_scout_cannot_claim_missing_bibliography_acquired(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch,missing=True)
    current=mw.verify_story(story,base_dir=tmp_path,campaign=tmp_path/'campaign')['current'];slot=current['slots'][1]
    v={'paragraphs':[],'figures':[],'tasks':[{'obligation_id':'toy','query':'Exact toy primary source','source_scope':'located original obligation','claim_ids':['main'],'failure_or_missing':'Not acquired.'}],'unresolved':[]}
    with pytest.raises(ValueError,match='self-certify'):mw._value(v,slot,current,current['loaded'],plan(current))


def test_resolution_requires_all_actual_sources_and_preserves_original_task(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    result=mw.resolve_sources(story,pin(tmp_path/'production.json'),tmp_path/'resolution',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert mw.verify_resolution(story,result['resolution'],base_dir=tmp_path,campaign=tmp_path/'campaign')['loaded']['request']==r
    changed=deepcopy(r);changed['author_id']='foreign-author';foreign=put(tmp_path,'foreign.json',changed)
    with pytest.raises(ValueError,match='original task'):mw.resolve_sources(story,foreign,tmp_path/'foreign-resolution',base_dir=tmp_path,campaign=tmp_path/'campaign')


def test_final_transcript_refuses_unissued_or_omitted_phases(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    resolved=mw.resolve_sources(story,pin(tmp_path/'production.json'),tmp_path/'resolution',base_dir=tmp_path,campaign=tmp_path/'campaign')['resolution']
    loaded=mp._load(r,tmp_path)
    with pytest.raises(ValueError,match='omit'):mw.verify_transcript({'story':story,'resolution':resolved,'products':[story]},loaded,tmp_path/'campaign')


def test_full_phase_to_actual_terminal_materialization_keeps_distinct_receipts(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch,context_bytes=300000)
    resolved=mw.resolve_sources(story,pin(tmp_path/'production.json'),tmp_path/'resolution',base_dir=tmp_path,campaign=tmp_path/'campaign')['resolution'];products=[story]
    for i in range(1,6):
        prepared=mw.prepare_phase(story,'phase'+str(i),tmp_path/('workflow/issued/phase'+str(i)),base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story],resolution_pin=resolved)
        value={'paragraphs':deepcopy(final['paragraphs']) if i in (3,4,5) else [],'figures':[],'tasks':[],'unresolved':[]}
        complete(prepared,state,value,monkeypatch,registry)
        products.append(mw.consume_phase(prepared,tmp_path/('workflow/issued/phase'+str(i)+'/consumed'),base_dir=tmp_path)['product'])
    prepared=mw.prepare_phase(story,'phase6',tmp_path/'workflow/issued/phase6',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=products,resolution_pin=resolved)
    wrapped={'binding':prepared['binding']['author_binding']};complete(wrapped,state,final,monkeypatch,registry)
    result=mw.assemble(story,products,tmp_path/'note',base_dir=tmp_path,campaign=tmp_path/'campaign',synthesis_binding=prepared)
    provenance=json.loads(Path(result['package']['model_provenance']['path']).read_text())
    assert len(provenance['writing_transcript']['actual_prior_phases'])==6 and provenance['final_synthesis_only']
    assert provenance['accounted_model_receipt']['public_value']==final
    assert 'failed fit unresolved' in Path(result['package']['manuscript']['path']).read_text()
    assert not result['package']['parent_task_accepted']


@pytest.mark.parametrize('fault',['null-packet','missing-entry','source-drift','wrong-role','foreign-image'])
def test_whole_author_visual_packet_refusals_before_wire(tmp_path,monkeypatch,fault):
    r,state,value=setup(tmp_path,monkeypatch)
    image=put(tmp_path,'figure.png','PNG synthetic bytes; no image/render qualification')
    r['figures']=[{'id':'all','image':image,'contract':put(tmp_path,'figure-contract.json',{'synthetic':True}), 'evidence_ids':['score'],'comparison':None}]
    loaded=mp._load(r,tmp_path);packet=mp._author_packet(tmp_path/'packet',loaded,role='proposer')
    if fault=='null-packet':packet=None
    elif fault=='source-drift':Path(image['path']).write_bytes(b'changed')
    else:
        path=Path(packet['path'])/'manifest.json';m=json.loads(path.read_text())
        if fault=='missing-entry':m['artifacts']=[]
        elif fault=='wrong-role':m['role']='verifier'
        else:m['artifacts'][0]['source_path']=str(tmp_path/'foreign.png')
        m['sha256']=mp.ce.digest({k:v for k,v in m.items() if k!='sha256'});path.write_text(json.dumps(m));packet['manifest_sha256']=m['sha256']
    with pytest.raises(ValueError):mp._verify_author_packet(packet,loaded,role='proposer')


def test_old_native_figures_still_require_actual_current_wire_at_author_consumer(tmp_path,monkeypatch):
    r,state,value=setup(tmp_path,monkeypatch);image=put(tmp_path,'figure.png','exact synthetic original')
    r['figures']=[{'id':'all','image':image,'contract':put(tmp_path,'figure-contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    b=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert b['spec']['nodes'][0]['packet']==b['packet']
    assert b['spec']['nodes'][0]['parameters']['visual_sources']==[image]
    with pytest.raises((ValueError,KeyError)):mp._verify_author_vision({'isolation':{}},mp._load(r,tmp_path),b['packet'],'author','proposer')


def test_source_only_status_retains_unissued_original_denominator(tmp_path,monkeypatch):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    status=mw.phase_status(story,base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert status['complete_original_denominator']==7
    assert [r['state'] for r in status['slots']][1:]==['unissued']*6
    assert not status['unknown_started_effect_reissued']


def test_coordinator_uses_authenticated_phase_and_consumption_slots(tmp_path,monkeypatch):
    from ravel.workflow import research_coordinator_decisions as decisions
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    dispatched=[];monkeypatch.setattr(mw,'execute_phase',lambda prepared,host:dispatched.append(prepared))
    prepared=decisions.invoke_extension('manuscript-phase',tmp_path/'campaign',
        {'story':story,'phase_id':'phase1','prior_products':[story],'resolution':None},tmp_path/'arbitrary-effect',object(),{})
    assert Path(prepared['binding']['graph']).parent==tmp_path/'workflow/issued/phase1'
    assert dispatched==[prepared] and not (tmp_path/'arbitrary-effect').exists()
    complete(prepared,state,{'paragraphs':[],'figures':[],'tasks':[],'unresolved':[]},monkeypatch,registry)
    result=decisions.invoke_extension('manuscript-consume-phase',tmp_path/'campaign',{'binding':prepared},tmp_path/'foreign-consume',object(),{})
    assert Path(result['product']['path'])==tmp_path/'workflow/issued/phase1/consumed/product.json'
    assert not (tmp_path/'foreign-consume').exists()


def test_complete_26_figure_packet_has_no_upstream_25_image_cap(tmp_path,monkeypatch):
    r,state,value=setup(tmp_path,monkeypatch)
    r['figures']=[{'id':'figure'+str(i),'image':put(tmp_path,'figure'+str(i)+'.png','Synthetic original '+str(i)),
        'contract':put(tmp_path,'contract'+str(i)+'.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None} for i in range(26)]
    loaded=mp._load(r,tmp_path);packet=mp._author_packet(tmp_path/'packet',loaded,role='proposer')
    assert len(mp._verify_author_packet(packet,loaded,role='proposer'))==26
    path=Path(packet['path'])/'manifest.json';manifest=json.loads(path.read_text());manifest['artifacts'].pop()
    manifest.pop('sha256');manifest['sha256']=mp.ce.digest(manifest);path.write_text(json.dumps(manifest));packet['manifest_sha256']=manifest['sha256']
    with pytest.raises(ValueError,match='^review context artifact membership differs from complete index$'):mp._verify_author_packet(packet,loaded,role='proposer')


@pytest.mark.parametrize('extension',['jpg','svg'])
def test_non_native_author_media_needs_actual_source_conversion(tmp_path,monkeypatch,extension):
    r,state,value=setup(tmp_path,monkeypatch)
    r['figures']=[{'id':'all','image':put(tmp_path,'figure.'+extension,'Synthetic non-native original'),
        'contract':put(tmp_path,'contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    with pytest.raises(ValueError,match='actual complete ordinary conversion'):mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')


def test_source_figure_known_producer_namespace_cannot_be_promoted(tmp_path,monkeypatch):
    from ravel.workflow import science
    r,state,value=setup(tmp_path,monkeypatch);restricted=tmp_path/'producer';restricted.mkdir()
    put(restricted,science.SPEC,{'original_retained_producer':True})
    r['figures']=[{'id':'private','image':put(restricted,'hidden.png','Not genuine image data; held private producer namespace'),
        'contract':put(tmp_path,'contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    with pytest.raises(ValueError,match='namespace lacks'):mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign')


@pytest.mark.parametrize('fault',['model-build','telemetry','uncharged','control-transport','missing-call','section-drop'])
def test_current_phase_consumption_checks_actual_model_and_whole_call(tmp_path,monkeypatch,fault):
    story,req,d,r,state,final,registry=consumed_story(tmp_path,monkeypatch)
    prepared=mw.prepare_phase(story,'phase3',tmp_path/'workflow/issued/phase3',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])
    value={'paragraphs':deepcopy(final['paragraphs']),'figures':[],'tasks':[],'unresolved':[]}
    if fault=='section-drop':value['paragraphs'].pop()
    receipt,saved=complete(prepared,state,value,monkeypatch,registry)
    if fault=='model-build':saved['result']['transport']['observed_model']='foreign-build'
    elif fault=='telemetry':saved['result']['usage']['input_tokens']=None
    elif fault=='uncharged':state['graphs'].pop()
    elif fault=='control-transport':receipt['execution_observation']='control_only'
    elif fault=='missing-call':saved['call_receipts']=[]
    with pytest.raises((ValueError,KeyError)):mw.consume_phase(prepared,tmp_path/'workflow/issued/phase3/consumed',base_dir=tmp_path)


def test_author_text_only_capability_is_an_explicit_hold_not_fallback(tmp_path,monkeypatch):
    from ravel.workflow import visual_presentation
    r,state,value=setup(tmp_path,monkeypatch);image=put(tmp_path,'figure.png','Exact synthetic source; decoding must not occur')
    r['figures']=[{'id':'all','image':image,'contract':put(tmp_path,'contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    loaded=mp._load(r,tmp_path);packet=mp._author_packet(tmp_path/'packet',loaded,role='proposer')
    with pytest.raises(visual_presentation.VisualFailure,match='vision'):
        visual_presentation.prepare_visuals(packet,[image],None,'caller-selected-text-model')


def test_unknown_external_phase_usage_retains_nulls_and_full_reservation(tmp_path,monkeypatch):
    req,d,r,state,final=case(tmp_path,monkeypatch)
    r['runtime'].update(usage_policy='reserved_unknown',max_output_bytes=2000000)
    d['production_request']=put(tmp_path,'production.json',r)
    for slot in d['phase_slots']:slot['runtime']=deepcopy(r['runtime'])
    req=put(tmp_path,'staged.json',d);current=mw._load(req,tmp_path)
    prepared=mw.prepare_story(req,tmp_path/'workflow',base_dir=tmp_path,campaign=tmp_path/'campaign');registry={}
    receipt,saved=complete(prepared,state,plan(current),monkeypatch,registry)
    receipt['execution_observation']='host_attested_external'
    receipt['external_completion_evidence']={'calls':1,'reserved_output_tokens':4096}
    saved['result']['usage']={'input_tokens':None,'output_tokens':None,'total_tokens':None}
    saved['result']['transport'].update(execution_mode='host_mediated_external',usage_observation='unknown')
    callpath=Path(prepared['binding']['graph'])/'calls/synthetic.json'
    call=json.loads(callpath.read_text());call['result']=deepcopy(saved['result']);callpath.write_text(json.dumps(call)+'\n')
    saved['call_receipts'][0]['sha256']=mp.ce.digest(call)
    monkeypatch.setattr(agent_graph,'status',lambda *a,**k:{'nodes':{'author':{'result':'inert','status':'completed'}},
        'started_epoch':100.0,'calls':{'synthetic':{'status':'completed'}},'usage':{'calls':1,'reserved_output_tokens':4096}})
    product=mw.consume_phase(prepared,tmp_path/'workflow/issued/phase0/consumed',base_dir=tmp_path)['product']
    observed=mw.verify_product(product,base_dir=tmp_path,campaign=tmp_path/'campaign')['actual_usage']
    assert observed['usage']=={'input_tokens':None,'output_tokens':None,'total_tokens':None}
    assert observed['reserved_output_tokens']==4096 and observed['reservation_refunded'] is False
    assert observed['usage_observation']=='unknown' and not observed['input_token_ceiling_verified']


def revision_case(root,monkeypatch):
    """Actual journal input for revision allocation; prose and HTTP remain inert."""
    from test_research_cycle import contract
    actual_load=research_cycle._load;actual_context=scientific_report._context
    req,declaration,request,_,value=case(root,monkeypatch)
    monkeypatch.setattr(research_cycle,'_load',actual_load)
    monkeypatch.setattr(scientific_report,'_context',actual_context)
    original=contract(root);original['budget']={'calls':20,'output_tokens':100000,'wall_seconds':2000,'native_attempts':0}
    state=research_cycle.create(root/'campaign',original,base_dir=root, evaluation_harness=True)
    context=put(root,'current-context.json',state['context'])
    request['quantitative_report']=put(root,'current-quantities.json',{'context':{**context,'path':Path(context['path']).name},'toy_request':True})
    request['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot')
    declaration['production_request']=put(root,'production-current.json',request)
    for slot in declaration['phase_slots']:slot['runtime']=deepcopy(request['runtime'])
    req=put(root,'staged-current.json',declaration)
    return req,declaration,request,state,value


def revision_completed(prepared,state,value,monkeypatch,registry):
    from test_manuscript_historical_origin import complete_actual
    observed=complete_actual(prepared['binding'],value,monkeypatch)
    state.clear();state.update(observed)


def revision_review(root,role,value,*,actor_id=None):
    """Located explicit synthetic reviewer record, never human/model evidence."""
    subject=put(root,'explicit-synthetic-review-'+role+'.json',value)
    subject={k:subject[k] for k in ('path','sha256')}
    return {'contract':{'role':role,'actor_id':role if actor_id is None else actor_id,'rundir':str(root),'case_pin':subject},
        'receipt':{'role':role,'execution_observation':'explicit_synthetic_review_fixture'},
        'value':value,'audit':value['audit'],'proposal':None,'supporting_artifacts':[],'execution_authorized':False}


@pytest.mark.parametrize('fault',['score-only','same-author','stale-review'])
def test_revision_uses_current_independent_material_objections_not_score(tmp_path,monkeypatch,fault):
    from ravel.workflow import scientific_judgment
    req,d,r,state,final=revision_case(tmp_path,monkeypatch)
    binding=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');registry={}
    revision_completed({'binding':binding},state,final,monkeypatch,registry)
    package=mp.collect(binding,tmp_path/'note')
    monkeypatch.setattr(mw.integrity,'assess',lambda *a,**k:{'complete_actual_independent_roles':True})
    monkeypatch.setattr(mw.integrity,'assessment_pins',lambda *a,**k:[])
    def review(b):
        if fault=='stale-review':raise ValueError('current method/source review subject changed')
        return revision_review(tmp_path,b,{'verdict':'supported' if fault=='score-only' else 'send_back','score':100,
            'audit':{'nodes':[{'id':'material-method','decision':'unresolved','assumptions':[]}],'edges':[]}},
            actor_id='toy-writer' if fault=='same-author' else b)
    monkeypatch.setattr(scientific_judgment,'verify_binding',review)
    with pytest.raises(ValueError):mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'revision',
        base_dir=tmp_path,campaign=tmp_path/'campaign',budget={'calls':1,'output_tokens':4096,'wall_seconds':60,'native_attempts':0})


def test_material_method_sendback_retains_complete_objection_and_invalidation(tmp_path,monkeypatch):
    from ravel.workflow import scientific_judgment
    req,d,r,state,final=revision_case(tmp_path,monkeypatch)
    binding=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');registry={}
    revision_completed({'binding':binding},state,final,monkeypatch,registry);package=mp.collect(binding,tmp_path/'note')
    monkeypatch.setattr(mw.integrity,'assess',lambda *a,**k:{'complete_actual_independent_roles':True})
    monkeypatch.setattr(mw.integrity,'assessment_pins',lambda *a,**k:[])
    monkeypatch.setattr(scientific_judgment,'verify_binding',lambda role:revision_review(tmp_path,role,
        {'verdict':'send_back','audit':{'nodes':[{'id':'method-gap','decision':'unresolved','assumptions':[]}],
            'edges':[{'id':'unsupported-counterevidence','decision':'contradicted'}]}}))
    result=mw.prepare_revision(package['package_pin'],['critic','verifier','synthesizer'],tmp_path/'revision',base_dir=tmp_path,
        campaign=tmp_path/'campaign',budget={'calls':1,'output_tokens':4096,'wall_seconds':60,'native_attempts':0})
    revision=json.loads(Path(result['revision']['path']).read_text())
    assert len(revision['objections'])==6 and revision['unresolved']==revision['objections']
    assert all(row['scientific_response_required'] and row['resolution']=='unresolved' for row in revision['objections'])
    assert 'compiled CI3' in revision['dependency_invalidation'] and not revision['scientific_acceptance']


def test_old_review_cannot_revise_a_changed_actual_method_source(tmp_path,monkeypatch):
    req,d,r,state,final=revision_case(tmp_path,monkeypatch)
    binding=mp.prepare_writer(r,tmp_path/'writer',base_dir=tmp_path,campaign=tmp_path/'campaign');registry={}
    revision_completed({'binding':binding},state,final,monkeypatch,registry);package=mp.collect(binding,tmp_path/'note')
    (tmp_path/'score.py').write_text('def square(x):\n    return x*x+1\n')
    with pytest.raises(ValueError):mw.prepare_revision(package['package_pin'],[],tmp_path/'revision',base_dir=tmp_path,
        campaign=tmp_path/'campaign',budget={'calls':1,'output_tokens':4096,'wall_seconds':60,'native_attempts':0})


@pytest.mark.parametrize('pdf',[False,True])
def test_actual_caption_phase_png_and_all_pdf_pages_use_current_native_wire(tmp_path,monkeypatch,pdf):
    # Actual tiny pixels/PDFium, inert HTTP only, and openly synthetic campaign
    # registration. No scientific model, external provider or real role vote.
    from test_visual_presentation import tiny_pdf, provider_host, vision
    from test_provider_transport import install_http
    original_receipt=agent_graph.role_receipt;original_status=agent_graph.status;original_result=agent_graph._result
    req,d,r,state,final=case(tmp_path,monkeypatch)
    path=tmp_path/('figure.pdf' if pdf else 'figure.png')
    if pdf:tiny_pdf(path)
    else:
        from PIL import Image
        image=Image.new('RGB',(8,6),(0,0,255));image.save(path);image.close()
    r['figures']=[{'id':'actual','image':pin(path),'contract':put(tmp_path,'contract.json',{'synthetic':True}),'evidence_ids':['score'],'comparison':None}]
    r['runtime'].update(action='model',model='fixture-model',model_build='observed-snapshot')
    d['production_request']=put(tmp_path,'production.json',r)
    for slot in d['phase_slots']:slot['runtime']=deepcopy(r['runtime'])
    req=put(tmp_path,'staged.json',d);current=mw._load(req,tmp_path);v=plan(current)
    v['plotting_plan']=[{'id':'actual','objective':'Inspect exact complete toy source','evidence_ids':['score'],'quantity_ids':['score'],
        'comparison_scope':'Synthetic engineering pixels only','caption_claim_ids':['main'],'missing_obligation_ids':[]}]
    v['section_plan'][0]['figure_ids']=['actual'];v['phases'][2]['figure_ids']=['actual']
    prepared=mw.prepare_story(req,tmp_path/'workflow',base_dir=tmp_path,campaign=tmp_path/'campaign');registry={}
    complete(prepared,state,v,monkeypatch,registry);registry[prepared['binding']['graph']][1]['result']['transport']['observed_model']='observed-snapshot'
    story=mw.consume_phase(prepared,tmp_path/'workflow/issued/phase0/consumed',base_dir=tmp_path)['product']
    caption=mw.prepare_phase(story,'phase2',tmp_path/'workflow/issued/phase2',base_dir=tmp_path,campaign=tmp_path/'campaign',prior_products=[story])
    monkeypatch.setattr(agent_graph,'role_receipt',lambda g,*a,**k:deepcopy(registry[str(g)][0]) if str(g) in registry else original_receipt(g,*a,**k))
    monkeypatch.setattr(agent_graph,'status',lambda g,*a,**k:({'nodes':{'author':{'result':'inert','status':'completed'}},'started_epoch':100.0}) if str(g) in registry else original_status(g,*a,**k))
    monkeypatch.setattr(agent_graph,'_result',lambda g,*a,**k:deepcopy(registry[str(g)][1]) if str(g) in registry else original_result(g,*a,**k))
    value={'paragraphs':[],'figures':[{'id':'actual','caption':'Exact toy source; no scientific claim','citation_ids':[],'uncertainties':['Engineering only']}],'tasks':[],'unresolved':[]}
    claim_fixture(caption['binding'],value)
    response={'status':'completed','model':'observed-snapshot','id':'inert-caption','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(value)}]}],
        'usage':{'input_tokens':10,'output_tokens':7,'total_tokens':17}}
    seen=install_http(monkeypatch,response)
    checkpoint=agent_graph.execute(caption['binding']['graph'],provider_host('responses',vision=vision()))
    assert checkpoint['complete'];state['graphs'].append({'root':caption['binding']['graph'],'complete':True});state['sha256']=mp.ce.digest(state['graphs'])
    product=mw.consume_phase(caption,tmp_path/'workflow/issued/phase2/consumed',base_dir=tmp_path)['product']
    current=mw.verify_product(product,base_dir=tmp_path,campaign=tmp_path/'campaign')
    assert current['visual_presentation']['pages']==(2 if pdf else 1) and len(seen)==1
    assert current['actual_receipt']['isolation']['visual_presentation']['wire_request']==seen[0]['body']
    assert not current['scientific_acceptance']
