"""Prospective software controls; no author execution.

The lifecycle uses existing expressly synthetic campaign/model fixtures. Real
ordinary consumer functions and current pins run only in root controls. These
are neither independent scientific judgments nor a provider/native result.
"""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_claim_disposition as cd
from ravel.workflow import manuscript_workflow as mw, manuscript_production as mp
from ravel.workflow import report_integrity as ri
from test_staged_manuscript_authoring import consumed_story, complete, plan, case
from test_manuscript_production import put, pin


def contract():
    originals=[]
    for identity,status,scope,limit in [('universal','conditional','whole held-out population','Validation is not a general guarantee.'),
                                      ('negative','contradicted','independent held-out cell','The held-out error is worse.')]:
        originals.append({'id':identity,'text':'A proposed guarantee, with the actual negative cell retained.','status':status,
            'scope':scope,'evidence_ids':['validation'],'counterevidence_ids':['heldout'],'method_ids':[],
            'quantity_ids':[],'citation_ids':[],'limitations':[limit],'section_ids':['limitations']})
    text='The held-out negative result remains unresolved. whole held-out population; independent held-out cell. Validation is not a general guarantee. The held-out error is worse.'
    value={'paragraphs':[{'id':'negative-note','section':'limitations','kind':'claim','text':text,
        'method_ids':[],'citation_ids':[],'evidence_ids':['validation','heldout'],'uncertainties':[]}],'figures':[]}
    rows=[{'planned_claim_id':c['id'],'original':deepcopy(c),'disposition':'qualified' if c['id']=='universal' else 'withdrawn',
        'paragraph_ids':['negative-note'],'figure_ids':[],'related_claim_ids':[],
        'reason':'The held-out negative result remains unresolved.','evidence_ids':['validation'],'counterevidence_ids':['heldout'],
        'unresolved_evidence_ids':[],'limitations':[{'index':0,'text':c['limitations'][0],'paragraph_ids':['negative-note'],'figure_ids':[]}]} for c in originals]
    return {'claim_map':originals},rows,value,{'validation':{},'heldout':{}}


@pytest.mark.parametrize('disposition',['retained','qualified','withdrawn','unresolved'])
def test_complete_negative_and_conditional_census_requires_no_fictitious_success(disposition):
    story,rows,value,evidence=contract();rows[1]['disposition']=disposition
    result=cd.validate(story,rows,value,evidence,final=True)
    assert [r['planned_claim_id'] for r in result]==['universal','negative']
    assert result[1]['original']['status']=='contradicted' and result[1]['counterevidence_ids']==['heldout']
    assert result[1]['limitations'][0]['text']=='The held-out error is worse.'


@pytest.mark.parametrize('fault',['missing','duplicate','reordered','foreign','status','scope','counterevidence',
    'limit-drop','limit-index','limit-rewrite','target','target-method','scope-prose','reason-prose','limit-prose','target-counterevidence'])
def test_final_claim_population_and_literal_qualifiers_cannot_vanish(fault):
    story,rows,value,evidence=contract()
    if fault=='missing':rows.pop()
    elif fault=='duplicate':rows[1]=deepcopy(rows[0])
    elif fault=='reordered':rows.reverse()
    elif fault=='foreign':rows[1]['planned_claim_id']='foreign'
    elif fault=='status':rows[1]['original']['status']='supported-in-supplied-record'
    elif fault=='scope':rows[1]['original']['scope']='validation-only'
    elif fault=='counterevidence':rows[1]['counterevidence_ids']=[]
    elif fault=='limit-drop':rows[1]['limitations']=[]
    elif fault=='limit-index':rows[1]['limitations'][0]['index']=1
    elif fault=='limit-rewrite':rows[1]['limitations'][0]['text']='Everything succeeded.'
    elif fault=='target':rows[1]['paragraph_ids']=[];rows[1]['limitations'][0]['paragraph_ids']=[]
    elif fault=='target-method':value['paragraphs'][0]['kind']='method'
    elif fault=='scope-prose':value['paragraphs'][0]['text']=value['paragraphs'][0]['text'].replace('independent held-out cell','validation')
    elif fault=='reason-prose':rows[1]['reason']='A different unsupported explanation.'
    elif fault=='limit-prose':value['paragraphs'][0]['text']=value['paragraphs'][0]['text'].replace('The held-out error is worse.','The result is good.')
    else:value['paragraphs'][0]['evidence_ids']=['validation']
    with pytest.raises(ValueError):cd.validate(story,rows,value,evidence,final=True)


def test_editorial_merge_retains_each_original_counterevidence_and_literal_limit():
    story,rows,value,evidence=contract()
    for row in rows:row.update(disposition='merged',related_claim_ids=['universal','negative'])
    actual=cd.validate(story,rows,value,evidence,final=True)
    assert len(actual)==2 and all(r['paragraph_ids']==['negative-note'] for r in actual)
    assert [r['limitations'][0]['text'] for r in actual]==[r['limitations'][0] for r in story['claim_map']]


@pytest.mark.parametrize('fault',['missing-original','partial-group','unshared-target','negative-limit'])
def test_merge_cannot_swallow_failed_claim(fault):
    story,rows,value,evidence=contract()
    for row in rows:row.update(disposition='merged',related_claim_ids=['universal','negative'])
    if fault=='missing-original':rows.pop()
    elif fault=='partial-group':rows[1]['related_claim_ids']=['negative']
    elif fault=='unshared-target':rows[1]['paragraph_ids']=[];rows[1]['limitations'][0]['paragraph_ids']=[]
    else:rows[1]['limitations']=[]
    with pytest.raises(ValueError):cd.validate(story,rows,value,evidence,final=True)


def test_caption_only_claim_has_real_caption_qualifier_targets():
    story,rows,value,evidence=contract();caption=value['paragraphs'][0]['text']
    value={'paragraphs':[],'figures':[{'id':'all','caption':caption,'citation_ids':[],'uncertainties':[]}]}
    for row in rows:
        row['paragraph_ids']=[];row['figure_ids']=['all']
        row['limitations'][0].update(paragraph_ids=[],figure_ids=['all'])
    assert cd.validate(story,rows,value,evidence,final=True,figures={'all':{'evidence_ids':['validation','heldout']}})==rows


def test_missing_original_source_can_plan_a_scout_without_acquisition_credit():
    story,rows,value,evidence=contract();evidence.pop('heldout')
    for row in rows:row['unresolved_evidence_ids']=['heldout']
    assert cd.validate(story,rows,value,evidence,final=False)==rows
    with pytest.raises(ValueError):cd.validate(story,rows,value,evidence,final=True)


@pytest.mark.parametrize('path',['section','phase','terminal'])
def test_story_requires_complete_original_claim_processing_paths(tmp_path,monkeypatch,path):
    req,_,_,_,_=case(tmp_path,monkeypatch);current=mw._load(req,tmp_path);value=plan(current)
    field='section_plan' if path=='section' else 'phases'
    if path=='terminal':value[field][-1]['claim_ids']=[]
    else:
        for row in value[field]:row['claim_ids']=[]
    with pytest.raises(ValueError):mw._plan(value,current)


def episode(root,monkeypatch,*,final_fault=None,phase_fault=False,context_bytes=300000,fault_reached=None):
    # Explicit prospective software-fixture capacity, not an implicit engine change.
    # Full transcript and intentional planned-claim mirrors are retained unaltered.
    story,req,d,r,state,final,registry=consumed_story(root,monkeypatch,context_bytes=context_bytes)
    resolution=mw.resolve_sources(story,pin(root/'production.json'),root/'resolution',base_dir=root,campaign=root/'campaign')['resolution']
    products=[story]
    for i in range(1,6):
        out=root/('workflow/issued/phase'+str(i))
        prepared=mw.prepare_phase(story,'phase'+str(i),out,base_dir=root,campaign=root/'campaign',prior_products=[story],resolution_pin=resolution)
        value={'paragraphs':deepcopy(final['paragraphs']) if i in (3,4,5) else [],'figures':[],'tasks':[],'unresolved':[]}
        complete(prepared,state,value,monkeypatch,registry)
        if phase_fault and i==1:
            registry[prepared['binding']['graph']][0]['public_value']['claim_dispositions']=[]
            if fault_reached is not None:fault_reached.append('phase')
        products.append(mw.consume_phase(prepared,out/'consumed',base_dir=root)['product'])
    synthesis=mw.prepare_phase(story,'phase6',root/'workflow/issued/phase6',base_dir=root,campaign=root/'campaign',prior_products=products,resolution_pin=resolution)
    binding=synthesis['binding']['author_binding'];complete({'binding':binding},state,final,monkeypatch,registry)
    if final_fault=='omit':
        registry[binding['graph']][0]['public_value']['claim_dispositions']=[]
        if fault_reached is not None:fault_reached.append('omit')
    elif final_fault=='limit':
        registry[binding['graph']][0]['public_value']['claim_dispositions'][0]['limitations']=[]
        if fault_reached is not None:fault_reached.append('limit')
    result=mw.assemble(story,products,root/'note',base_dir=root,campaign=root/'campaign',synthesis_binding=synthesis)
    return result,binding,r


def test_actual_phase_synthesis_assembly_and_independent_integrity_input_carry_census(tmp_path,monkeypatch):
    result,binding,r=episode(tmp_path,monkeypatch);package=result['package']
    ir=mw._read(package['integrity_request'],tmp_path);prepared=ri.prepare(ir,base_dir=tmp_path)
    rows=[i for i in prepared['items'] if i['kind']=='planned-claim-disposition']
    assert len(rows)==1 and rows[0]['original']['status']=='conditional'
    assert rows[0]['literal_limit_locations'][0]['text']=='Not a scientific/model outcome.'
    assert rows[0]['located_final_targets'] and rows[0]['current_evidence'] and rows[0]['original_evidence']
    presentation=put(tmp_path,'actual-integrity-input.json',prepared)
    ordinary_case=ri._case(prepared,ir,presentation,package['integrity_request'])
    node=next(n for n in ordinary_case['nodes'] if n['id']=='planned-claim.main')
    assert node['material'] and node['anchors'][0]['value']==rows[0]
    assert any(e['child']==node['id'] for e in ordinary_case['edges'])
    actual=mp._author_state(binding)[1]['public_value']
    assert actual['claim_dispositions'][0]==rows[0]['declared']
    assert mp.verify_author(package,base_dir=tmp_path)['public_value']==actual
    census=mw._read(package['planned_claim_census'],tmp_path)
    assert len(census['phase_censuses'])==5 and census['independent_review_required']
    assessment=ri.assess(ir,[],base_dir=tmp_path)
    assert any(r['id']=='planned-claim.main' for r in assessment['item_census']) and not assessment['scoped_integrity_review_complete']
    with pytest.raises(ValueError,match='complete actual ordinary integrity'):ri.manuscript(ir,base_dir=tmp_path,final=True)
    assert not package['scientific_acceptance'] and not package['parent_task_accepted']


@pytest.mark.parametrize('fault',['phase','omit','limit'])
def test_real_consumers_refuse_omitted_phase_or_terminal_claims(tmp_path,monkeypatch,fault):
    reason='complete indexed literal limitation census required' if fault=='limit' else 'complete ordered planned claim disposition census required'
    reached=[]
    with pytest.raises(ValueError,match='^'+reason+'$'):
        episode(tmp_path,monkeypatch,final_fault=None if fault=='phase' else fault,phase_fault=fault=='phase',fault_reached=reached)
    assert reached==[fault], 'The actual claim corruption must be reached; a prerequisite failure is not this refusal.'


def synthesis_input(issued):
    """Complete actual synthesis input: both source artifacts plus the instructions."""
    context_pin=pin(issued/'writer-context.json');request_pin=pin(issued/'production-request.json')
    context=json.loads((issued/'writer-context.json').read_text())
    request=json.loads((issued/'production-request.json').read_text())
    instructions=mp._instructions(request,context,context_transport='source-artifact-v1')
    return context_pin,request_pin,context,request,instructions,context_pin['size']+request_pin['size']+len(instructions.encode())


def test_original_connected_context_ceiling_refuses_full_untruncated_claim_payload(tmp_path,monkeypatch):
    # The ceiling is a property of the complete actual input, so it is measured from an
    # admitted episode of this fixture and never assumed. Sibling roots of equal name
    # length carry the same byte counts.
    episode(tmp_path/'ample',monkeypatch)
    *_,ample_request,_,measured=synthesis_input(tmp_path/'ample/workflow/issued/phase6')
    assert 100000<=measured<ample_request['runtime']['max_context_bytes']==300000
    reached=[]
    with pytest.raises(ValueError,match='^whole author context exceeds explicit bound; no truncation$'):
        episode(tmp_path/'bound',monkeypatch,context_bytes=measured-1,fault_reached=reached)
    assert reached==[]
    issued=tmp_path/'bound/workflow/issued/phase6'
    context_pin,request_pin,context,request,instructions,full_size=synthesis_input(issued)
    # One byte below the complete input is refused at the synthesis itself: every earlier
    # phase was admitted, and nothing was truncated to fit.
    assert request['runtime']['max_context_bytes']==measured-1 and full_size==measured>measured-1
    assert not (tmp_path/'bound/note').exists()
    transcript=context['writing_transcript'];claims=context['planned_claim_context']
    assert len(transcript['actual_prior_phases'])==6 and len(claims['phase_censuses'])==5
    assert claims['plan']==transcript['original_claim_plan']
    assert claims['phase_censuses']==transcript['complete_phase_claim_census']
    assert claims['original_evidence']==transcript['original_claim_evidence']
    # The exact bounded primitive still counts all actual input bytes plus instructions.
    boundary={**request['runtime'],'max_context_bytes':full_size}
    assert mp._context_bound(boundary,instructions,context_pin,request_pin,issued,context_transport='source-artifact-v1')==full_size
    with pytest.raises(ValueError,match='^whole author context exceeds explicit bound; no truncation$'):
        mp._context_bound({**boundary,'max_context_bytes':full_size-1},instructions,context_pin,request_pin,issued,context_transport='source-artifact-v1')
    # The same complete input is admitted at exactly its own size.
    result,_,_=episode(tmp_path/'exact',monkeypatch,context_bytes=measured)
    assert synthesis_input(tmp_path/'exact/workflow/issued/phase6')[-1]==measured
    assert not result['package']['scientific_acceptance']


@pytest.mark.parametrize('fault',['disposition','paragraph','original'])
def test_repinning_census_does_not_replace_actual_writer_receipt(tmp_path,monkeypatch,fault):
    result,_,_=episode(tmp_path,monkeypatch);package=result['package'];ir=mw._read(package['integrity_request'],tmp_path)
    census=mw._read(package['planned_claim_census'],tmp_path)
    if fault=='disposition':census['rows'][0]['disposition']='withdrawn'
    elif fault=='paragraph':census['paragraphs'][-1]['text']='Everything is proved.'
    else:census['rows'][0]['original']['limitations']=[]
    ir['planned_claim_census']=put(tmp_path,'forged-census.json',census)
    with pytest.raises(ValueError,match='differs from actual'):ri.prepare(ir,base_dir=tmp_path)


def test_direct_improver_inherits_census_and_changed_science_needs_real_action_path(tmp_path,monkeypatch):
    result,binding,r=episode(tmp_path,monkeypatch);loaded=mp._load(r,tmp_path)
    loaded['revision']={'previous':result['package'],'actual_feedback':{'synthetic':True}}
    loaded['request']['revision']={'previous_package':result['package_pin'],'feedback_binding':{'synthetic':True}}
    inherited=mp._claim_context(loaded,None,binding['campaign'])
    assert inherited['plan']['claim_map'][0]['id']=='main'
    assert mp._has_claim_plan(loaded,None)
    schema=mp.output_schema(loaded['formatting'],planned_claims=mp._has_claim_plan(loaded,None))
    assert 'claim_dispositions' in schema['required']
    changed=deepcopy(loaded);changed['quantitative_report']['report_text']='An unsupported new successful result.'
    with pytest.raises(ValueError,match='authenticated action/protocol'):mp._claim_context(changed,None,binding['campaign'])


def test_legacy_unplanned_writer_output_schema_is_unchanged():
    schema=mp.output_schema()
    assert schema['required']==['schema_version','paragraphs','figures']
    assert 'claim_dispositions' not in schema['properties']


def test_complete_claim_schema_reaches_existing_provider_schema_boundary():
    from ravel.workflow import agent_host
    schema=mp.output_schema(planned_claims=True)
    agent_host._schema(schema)
    assert agent_host._responses_output_schema(schema) is schema
    row=schema['properties']['claim_dispositions']['items']
    assert set(row['required'])==set(row['properties']) and row['additionalProperties'] is False
    assert row['properties']['disposition']['enum']==list(cd.DISPOSITIONS)


@pytest.mark.parametrize('fault',[None,'unknown','stale'])
def test_actual_planned_integrity_objection_maps_through_original_action_compiler(tmp_path,monkeypatch,fault):
    result,binding,_=episode(tmp_path,monkeypatch);package=result['package']
    ir=mw._read(package['integrity_request'],tmp_path);prepared=ri.prepare(ir,base_dir=tmp_path)
    item=next(r for r in prepared['items'] if r['id']=='planned-claim.main')
    loaded=mp._author_state(binding)[0]
    # Explicit prospective objection input, never an actual independent vote.
    identity=item['id'] if fault is None else ('planned-claim.foreign' if fault=='unknown' else 'planned-claim.old')
    revision={'objections':[{'current_audit_item':{'id':identity,'decision':'unsupported'}}]}
    rows=[{'objection_index':0,'kind':'editorial','response':'Keep the failed fit and literal limitation visible.',
        'protocol_claim_ids':[],'protocol_stage_ids':[],'required_experiment_ids':[]}]
    if fault is not None:
        with pytest.raises(ValueError,match='no original planned claim'):mw._action_rows(rows,revision,ir,loaded,None)
        return
    actual=mw._action_rows(rows,revision,ir,loaded,None)[0]['affected_manuscript']
    assert set(item['declared']['paragraph_ids'])<=set(actual['claim_ids'])
    assert set(item['original']['method_ids'])<=set(actual['method_ids'])
    assert set(item['original']['citation_ids'])<=set(actual['citation_ids'])
    assert actual['section_ids']==[s['id'] for s in mp.manuscript_format.section_layout(loaded['formatting'])]
