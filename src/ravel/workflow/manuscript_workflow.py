"""Source-bound staged authoring through existing charged Graph services.

The story is an actual consumed model result. Planning can retain missing
acquisition/plot obligations; final assembly cannot replace them with prose.
Each slot is issued once as an immutable ordinary Graph binding. Campaign
accounting, effect recovery, scientific review and native jobs remain their
existing services. This module supplies no scheduler or editorial vote.

Claims and bibliography remain source-backed proposals.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from . import manuscript_claim_disposition as claim_disposition
from . import agent_graph, candidate_experiments as ce, manuscript_production as mp
from . import report_integrity as integrity, research_cycle as cycle, state_io

KINDS=('story','citation-scout','caption','section','coherence','editorial-revision','synthesis')
MISSING_KINDS=('citation','figure','method','evidence')
MAX_PHASES=48
MAX_CLAIMS=160


def _rows(rows,name,*,empty=True,limit=255):
    if type(rows) is not list or len(rows)>limit or (not empty and not rows):raise ValueError('complete bounded '+name+' required')
    return rows


def _ids(rows,name,*,allowed=None,empty=True):
    rows=_rows(rows,name,empty=empty)
    if len(set(rows))!=len(rows):raise ValueError('duplicate '+name)
    for identity in rows:ce.identity(identity)
    if allowed is not None and not set(rows)<=set(allowed):raise ValueError('foreign '+name)
    return rows


def _canon(pin,base,consumed):
    integrity._raw(pin,base,consumed)
    return {**pin,'path':str(integrity._artifact_path(pin,base))}


def _read(pin,base,consumed=None):
    return integrity._json(integrity._raw(pin,base,{} if consumed is None else consumed))


def _source_epoch():
    from . import agent_host, scientific_report, manuscript_format, review_context, visual_presentation, research_protocol
    modules=(mp,agent_graph,agent_host,cycle,scientific_report,manuscript_format,review_context,visual_presentation,research_protocol,claim_disposition,integrity)
    return {m.__name__:mp._pin(m.__file__) for m in modules}|{__name__:mp._pin(__file__)}


def _runtime(runtime):
    ce.keys(runtime,['model','model_build','action','reasoning_effort','max_output_tokens','max_input_tokens','max_context_bytes','max_wall_seconds']
        +[k for k in ('usage_policy','max_output_bytes') if k in runtime])
    for k in ('model','model_build','reasoning_effort'):integrity._text(runtime[k])
    if runtime['action'] not in {'model','external'}:raise ValueError('ordinary configured model/external transport required')
    for k in ('max_output_tokens','max_input_tokens','max_context_bytes','max_wall_seconds'):
        if type(runtime[k]) is not int or runtime[k]<=0:raise ValueError('positive phase resource bound required')
    mp._writer_policy(runtime)
    return deepcopy(runtime)


def _budget(budget,slots):
    ce.keys(budget,['max_calls','max_input_tokens','max_output_tokens','max_wall_seconds','max_context_bytes','max_revisions'])
    if any(type(v) is not int or v<0 for v in budget.values()) or any(budget[k]<=0 for k in budget if k!='max_revisions'):
        raise ValueError('one explicit finite original authoring allocation required')
    total={'max_calls':len(slots),'max_input_tokens':sum(s['runtime']['max_input_tokens'] for s in slots),
        'max_output_tokens':sum(s['runtime']['max_output_tokens'] for s in slots),
        'max_wall_seconds':sum(s['runtime']['max_wall_seconds'] for s in slots),
        'max_context_bytes':max(s['runtime']['max_context_bytes'] for s in slots),
        'max_revisions':sum(s['kind']=='editorial-revision' for s in slots)}
    if any(total[k]>budget[k] for k in total):raise ValueError('whole phase reservation exceeds original allocation; no per-phase reset')
    return total


def _load(request_pin,base):
    consumed={};request_pin=_canon(request_pin,base,consumed);d=_read(request_pin,base,consumed)
    ce.keys(d,['schema_version','kind','production_request','missing','phase_slots','budget'])
    if type(d['schema_version']) is not int or d['schema_version']!=2 or d['kind']!='staged-manuscript-request':raise ValueError('staged manuscript/v2 request required')
    base=Path(request_pin['path']).parent
    prodpin=_canon(d['production_request'],base,consumed);production=_read(prodpin,base,consumed)
    loaded=mp._load(production,Path(prodpin['path']).parent,planning=True)
    for pin in loaded['input_pins']:integrity._dependency(pin,loaded['source_base'],consumed)
    missing={};known={'citation':set(loaded['citations']),'figure':set(loaded['figures']),'method':set(loaded['methods']),'evidence':set(loaded['evidence'])}
    for row in _rows(d['missing'],'located missing acquisition/plot obligations'):
        ce.keys(row,['id','kind','description','located']);ce.identity(row['id']);integrity._text(row['description'])
        if row['kind'] not in MISSING_KINDS or row['id'] in missing or row['id'] in known[row['kind']]:raise ValueError('distinct source-declared missing obligation required')
        located=integrity._located(row['located'],base,consumed)
        if production.get('blinding_policy') is not None:
            known_paths={p['path'] for p in loaded['input_pins']}
            if str(integrity._artifact_path(located['artifact'],base)) not in known_paths:raise ValueError('blinded planning obligation needs the existing authenticated public source census; acquire/review it first')
        missing[row['id']]=deepcopy(row)
    absent={c for m in loaded['methods'].values() for c in m['citation_ids']} - known['citation']
    if not absent<=set(k for k,r in missing.items() if r['kind']=='citation'):raise ValueError('every missing method citation needs a located acquisition obligation')
    slots=[];seen=set()
    for row in _rows(d['phase_slots'],'complete ordered phase slots',empty=False,limit=MAX_PHASES):
        ce.keys(row,['id','kind','depends_on','runtime']);ce.identity(row['id'])
        if row['id'] in seen or row['kind'] not in KINDS:raise ValueError('distinct source-defined phase slot required')
        _ids(row['depends_on'],'phase dependencies',allowed=seen)
        if slots and not row['depends_on']:raise ValueError('every later phase must depend on consumed original story')
        if slots and slots[0]['id'] not in row['depends_on']:
            ancestors=set(row['depends_on'])
            for prior in reversed(slots):
                if prior['id'] in ancestors:ancestors.update(prior['depends_on'])
            if slots[0]['id'] not in ancestors:raise ValueError('phase lacks original story lineage')
        runtime=_runtime(row['runtime'])
        if mp._writer_policy(runtime)['usage_policy']!=mp._writer_policy(production['runtime'])['usage_policy']:raise ValueError('every phase must retain original selected accounting policy')
        slots.append({**deepcopy(row),'runtime':runtime});seen.add(row['id'])
    if slots[0]['kind']!='story' or slots[0]['depends_on'] or slots[-1]['kind']!='synthesis' or any(s['kind']=='story' for s in slots[1:]) or any(s['kind']=='synthesis' for s in slots[:-1]):raise ValueError('exact initial story and terminal synthesis slots required')
    if set(slots[-1]['depends_on'])!=set(s['id'] for s in slots[:-1]):raise ValueError('final synthesis must consume every original phase, including failures/unresolved')
    reserved=_budget(d['budget'],slots)
    for pin in consumed.values():integrity._dependency(pin,base,{})
    return {'request':d,'request_pin':request_pin,'production_pin':prodpin,'production':production,'loaded':loaded,
        'missing':missing,'slots':slots,'reservation':reserved,'input_pins':list(consumed.values()),'source_epoch':_source_epoch()}


def _campaign(current,campaign,*,_origin=None,_binding=None):
    loaded=current['loaded'];q=loaded['documents']['quantitative_report']
    if q.get('context') is None:raise ValueError('current original quantitative context required')
    from . import scientific_report
    quantitative_context=scientific_report._context(q['context'],integrity._artifact_path(current['production']['quantitative_report'],loaded['source_base']).parent)
    if _origin is None:
        _,state=cycle._load(campaign)
    else:
        if _binding is None:raise ValueError('historical context is only for an authenticated completed writing phase')
        state=mp._origin_campaign(_origin,campaign=campaign,prepared_sha256=_binding['prepared_campaign_sha256'],
            graph_root=_binding['graph'],graph_spec=_binding['spec'],checkpoint=agent_graph.status(_binding['graph']),
            quantitative_context=quantitative_context)
    if quantitative_context!=state['context']:
        raise ValueError('writer stages cannot borrow a foreign or stale campaign quantity context')
    if state.get('parent_task') is not None:
        parent=cycle._read(state['parent_task']['contract'],Path(campaign))
        if parent['prompt']!=loaded['documents']['original_task']:raise ValueError('staged writer changed original parent task')
    return state


def _object(props):return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}

def _list(item,max_items=255,min_items=0):return {'type':'array','items':item,'maxItems':max_items,'minItems':min_items}

def story_schema():
    text={'type':'string','minLength':1,'maxLength':16000};identity={'type':'string','minLength':1,'maxLength':64};ids=_list(identity)
    claim=_object({'id':identity,'text':text,'status':{'type':'string','enum':['supported-in-supplied-record','contradicted','conditional','unknown','proposed']},
        'scope':text,'evidence_ids':ids,'counterevidence_ids':ids,'method_ids':ids,'quantity_ids':ids,'citation_ids':ids,'limitations':_list(text),'section_ids':ids})
    plot=_object({'id':identity,'objective':text,'evidence_ids':ids,'quantity_ids':ids,'comparison_scope':text,'caption_claim_ids':ids,'missing_obligation_ids':ids})
    related=_object({'id':identity,'macro_context':text,'methodology_cluster':text,'located_citation_ids':ids,'limitation_hypothesis':text,'counterevidence_ids':ids,'bridge':text,'acquisition_obligation_ids':ids})
    section=_object({'id':identity,'purpose':text,'claim_ids':ids,'method_ids':ids,'evidence_ids':ids,'citation_ids':ids,'figure_ids':ids,'dependency_section_ids':ids,'content_bullets':_list(text)})
    phase=_object({'id':identity,'section_ids':ids,'claim_ids':ids,'figure_ids':ids,'obligation_ids':ids})
    return _object({'claim_map':_list(claim,MAX_CLAIMS,1),'plotting_plan':_list(plot,64),
        'intro_related_work_plan':_list(related),'section_plan':_list(section),'phases':_list(phase,MAX_PHASES,1),'unresolved':ids})


def phase_schema(kind,loaded):
    if kind=='story':return story_schema()
    if kind=='synthesis':return mp.output_schema(loaded['formatting'],has_template=loaded['template'] is not None,planned_claims=True)
    base=mp.output_schema(loaded['formatting'],has_template=False)['properties']
    base['paragraphs']=deepcopy(base['paragraphs']);base['paragraphs']['minItems']=0
    text={'type':'string','minLength':1,'maxLength':16000};ids=_list({'type':'string'})
    return _object({'paragraphs':base['paragraphs'],'figures':base['figures'],
        'tasks':_list(_object({'obligation_id':{'type':'string'},'query':text,'source_scope':text,'claim_ids':ids,'failure_or_missing':text})),
        'unresolved':ids,'claim_dispositions':claim_disposition.schema()})


def _population(current):
    loaded=current['loaded'];missing=current['missing']
    return {kind:set(loaded[field])|{k for k,r in missing.items() if r['kind']==kind}
        for kind,field in [('evidence','evidence'),('method','methods'),('citation','citations'),('figure','figures')]}|{
        'quantity':set(loaded['quantitative_report']['expected_slots']),
        'section':set(s['id'] for s in mp.manuscript_format.section_layout(loaded['formatting']))}


def _plan(value,current):
    ce.keys(value,['claim_map','plotting_plan','intro_related_work_plan','section_plan','phases','unresolved'])
    p=_population(current);claims={};coverage={k:set() for k in p}
    for row in _rows(value['claim_map'],'complete claim/evidence/counterevidence map',empty=False,limit=MAX_CLAIMS):
        ce.keys(row,['id','text','status','scope','evidence_ids','counterevidence_ids','method_ids','quantity_ids','citation_ids','limitations','section_ids'])
        ce.identity(row['id'])
        if row['id'] in claims or row['status'] not in {'supported-in-supplied-record','contradicted','conditional','unknown','proposed'}:raise ValueError('distinct explicit claim status required')
        for k in ('text','scope'):integrity._text(row[k])
        for k in ('limitations',):
            for x in _rows(row[k],k):integrity._text(x)
        for field,kind in [('evidence_ids','evidence'),('counterevidence_ids','evidence'),('method_ids','method'),('quantity_ids','quantity'),('citation_ids','citation'),('section_ids','section')]:
            _ids(row[field],field,allowed=p[kind]);coverage[kind].update(row[field])
        claims[row['id']]=row
    plots={}
    for row in _rows(value['plotting_plan'],'whole plotting plan',limit=64):
        ce.keys(row,['id','objective','evidence_ids','quantity_ids','comparison_scope','caption_claim_ids','missing_obligation_ids'])
        if row['id'] not in p['figure'] or row['id'] in plots:raise ValueError('whole original figure plan required')
        for k in ('objective','comparison_scope'):integrity._text(row[k])
        _ids(row['evidence_ids'],'plot evidence',allowed=p['evidence']);_ids(row['quantity_ids'],'plot quantities',allowed=p['quantity'])
        _ids(row['caption_claim_ids'],'caption claims',allowed=claims);_ids(row['missing_obligation_ids'],'plot obligations',allowed=current['missing'])
        plots[row['id']]=row
    if set(plots)!=p['figure']:raise ValueError('planning cannot omit known or missing figure population')
    related=set()
    for row in _rows(value['intro_related_work_plan'],'source-located macro/micro context'):
        ce.keys(row,['id','macro_context','methodology_cluster','located_citation_ids','limitation_hypothesis','counterevidence_ids','bridge','acquisition_obligation_ids'])
        ce.identity(row['id'])
        if row['id'] in related:raise ValueError('duplicate related-work task')
        related.add(row['id'])
        for k in ('macro_context','methodology_cluster','limitation_hypothesis','bridge'):integrity._text(row[k])
        _ids(row['located_citation_ids'],'located prior work',allowed=current['loaded']['citations']);_ids(row['counterevidence_ids'],'related counterevidence',allowed=p['evidence'])
        _ids(row['acquisition_obligation_ids'],'related acquisition obligations',allowed=[i for i,r in current['missing'].items() if r['kind']=='citation'])
    sections={}
    for row in _rows(value['section_plan'],'whole source-defined section plan',empty=False):
        ce.keys(row,['id','purpose','claim_ids','method_ids','evidence_ids','citation_ids','figure_ids','dependency_section_ids','content_bullets'])
        if row['id'] not in p['section'] or row['id'] in sections:raise ValueError('source-defined complete section plan required')
        integrity._text(row['purpose']);_ids(row['claim_ids'],'section claims',allowed=claims)
        for field,kind in [('method_ids','method'),('evidence_ids','evidence'),('citation_ids','citation'),('figure_ids','figure'),('dependency_section_ids','section')]:
            _ids(row[field],field,allowed=p[kind]);coverage[kind].update(row[field])
        for x in _rows(row['content_bullets'],'source-located content bullets',empty=False):integrity._text(x)
        sections[row['id']]=row
    if set(sections)!=p['section']:raise ValueError('outline dropped a source-defined section')
    if coverage['method']!=p['method'] or coverage['quantity']!=p['quantity'] or coverage['evidence']!=p['evidence'] or coverage['citation']!=p['citation']:
        raise ValueError('story must retain every original method, quantity, source and citation obligation')
    phase_ids=[s['id'] for s in current['slots']];schedule=[];caption_population=set()
    for row in _rows(value['phases'],'complete fixed phase plan',empty=False,limit=MAX_PHASES):
        ce.keys(row,['id','section_ids','claim_ids','figure_ids','obligation_ids'])
        if row['id'] not in phase_ids:raise ValueError('foreign original phase slot')
        _ids(row['section_ids'],'phase sections',allowed=p['section']);_ids(row['claim_ids'],'phase claims',allowed=claims)
        _ids(row['figure_ids'],'phase figures',allowed=p['figure']);_ids(row['obligation_ids'],'phase obligations',allowed=current['missing']);schedule.append(row['id'])
        if next(s['kind'] for s in current['slots'] if s['id']==row['id'])=='caption':caption_population.update(row['figure_ids'])
    for row in [*value['section_plan'],*value['phases']]:
        if row['claim_ids']!=[i for i in claims if i in row['claim_ids']]:raise ValueError('allocated claims must preserve original source order')
    if set(i for row in value['section_plan'] for i in row['claim_ids'])!=set(claims) or set(i for row in value['phases'] for i in row['claim_ids'])!=set(claims):
        raise ValueError('every original planned claim needs a section and phase processing path')
    if value['phases'][-1]['claim_ids']!=list(claims):raise ValueError('terminal synthesis must reconcile the complete ordered original claim roster')
    inherited=mp._claim_context(current['loaded'],None,None)
    if inherited is not None and value['claim_map'][:len(inherited['plan']['claim_map'])]!=inherited['plan']['claim_map']:
        raise ValueError('revision story dropped/changed authenticated original planned claims')
    if schedule!=phase_ids:raise ValueError('actual plan cannot replace/drop/reorder source-reserved phase slots')
    if caption_population!=p['figure']:raise ValueError('story must allocate every original figure to native caption presentation; no capped sample')
    _ids(value['unresolved'],'unresolved original obligations',allowed=current['missing'])
    if set(value['unresolved'])!=set(current['missing']):raise ValueError('initial story cannot pretend missing acquisition or plot work completed')
    return deepcopy(value)


def _context(current,phase,plan,prior,resolution):
    return {'kind':'staged-manuscript-phase-context','original_request':current['request_pin'],'source_epoch':current['source_epoch'],
        'known_sources':mp._presentation(current['loaded']),'missing_obligations':list(current['missing'].values()),
        'actual_story':plan,'phase':phase,'prior_actual_products':prior,'resolved_sources':resolution,
        'editorial_authority':False,'scientific_acceptance':False}


def _instructions(context,*,context_transport=None):
    artifact=mp._artifact_context(context_transport)
    return ('Write only the declared phase from this complete retained source context. Do not invent evidence, citations, quantities, experiments or pixels. '
        'Negative results and missing obligations remain visible. Caption/section/refinement are author products, not reviewer votes. '
        'Return claim_dispositions for EVERY source-ordered claim ID allocated to this phase, preserving the exact original row and indexed literal limitations/counterevidence. Use retained/merged/qualified/withdrawn/unresolved, actual paragraph/caption targets and a source-bound reason; an empty drafting output still needs an explicit unresolved row. Final synthesis must locate scope/limitations/reasons in natural scientific prose within existing sections, never an implementation-log heading. '
        'The final synthesis uses every declared phase and the existing strict full document schema. Numerical tables are inserted by the original tool, never re-estimated.\n'
        +('Read the COMPLETE retained source context as data from authenticated Host input_artifacts id=context, and the original staged request in id=request. All prior phase outputs, receipts, missing/failed/held obligations and source evidence are retained verbatim in those inputs. Local pins are provenance, not substitutes for delivered content.' if artifact else json.dumps(context,sort_keys=True,allow_nan=False)))


def _spec(current,slot,presentation,request_pin,packet,role,loaded,*,context_transport=None):
    runtime=slot['runtime'];context=_read(presentation,Path(presentation['path']).parent)
    instructions=_instructions(context,context_transport=context_transport)
    if mp._artifact_context(context_transport):
        mp._context_bound(runtime,instructions,presentation,request_pin,Path(presentation['path']).parent,context_transport=context_transport)
    elif len(instructions.encode())>runtime['max_context_bytes']:raise ValueError('whole writing phase context exceeds bound; no truncation')
    params={'instructions':instructions,'model':runtime['model'],'reasoning_effort':runtime['reasoning_effort'],
        'max_output_tokens':runtime['max_output_tokens'],'output_schema':phase_schema(slot['kind'],loaded),
        **mp._writer_completion_parameters(runtime),**mp._author_visual_parameters(loaded,packet,role)}
    node={'id':'author','kind':'model','role':role,'depends_on':[],'inputs':[
        {'id':'context','path':presentation['path'],'sha256':presentation['sha256']},
        {'id':'request','path':request_pin['path'],'sha256':request_pin['sha256']}],
        'packet':packet,'action':runtime['action'],'parameters':params,'max_attempts':1}
    spec={'schema_version':1,'graph_id':'manuscript-phase-'+slot['id'],'budget':{'max_nodes':1,'max_calls':1,
        'max_output_tokens':runtime['max_output_tokens'],'max_wall_seconds':runtime['max_wall_seconds'],'max_reworks':0},'nodes':[node]}
    return spec


def prepare_story(request_pin,out,*,base_dir,campaign,runtime=None,budget=None):
    current=_load(request_pin,base_dir);state=_campaign(current,campaign)
    if runtime is not None and runtime!=current['slots'][0]['runtime']:raise ValueError('story runtime differs from original reservation')
    if budget is not None and budget!=current['request']['budget']:raise ValueError('story cannot reset original budget')
    prospective={'calls':current['reservation']['max_calls'],'output_tokens':current['reservation']['max_output_tokens'],'wall_seconds':current['reservation']['max_wall_seconds']}
    for k,v in prospective.items():
        if k not in state['contract'].get('budget',{}) or v+cycle._usage(state)[k]>state['contract']['budget'][k]:raise ValueError('complete story/phase allocation cannot fit original campaign budget')
    mp._check_source_review(current['loaded']);root=mp._fresh(out);(root/'issued').mkdir()
    currentpin=integrity._new(root/'initial-source.json',{'request':current['request_pin'],'source_epoch':current['source_epoch'],'input_pins':current['input_pins']})
    return _prepare(current,current['slots'][0],root/'issued'/current['slots'][0]['id'],campaign,
        workflow_root=root,plan_pin=None,prior=[],resolution_pin=None,state=state,initial=currentpin)


def _visual_scope(current,slot,loaded,plan):
    # Planning/scout make no author-pixel claim. Native media work is explicit
    # in source-reserved caption/section phases, not hidden capped sampling.
    ids=[] if plan is None or slot['kind'] in {'story','citation-scout'} else next(r['figure_ids'] for r in plan['phases'] if r['id']==slot['id'])
    if not set(ids)<=set(loaded['figures']):raise ValueError('declared phase images await actual acquisition/conversion')
    selected=deepcopy(loaded);selected['figures']={i:loaded['figures'][i] for i in ids}
    selected['request']['figures']=[f for i in ids for f in loaded['request']['figures'] if f['id']==i]
    if 'author_visuals' in selected['request']:selected['request']['author_visuals']=[r for r in selected['request']['author_visuals'] if r['figure_id'] in ids]
    return selected


def _prepare(current,slot,out,campaign,*,workflow_root,plan_pin,prior,resolution_pin,state,initial):
    root=mp._fresh(out);role='improver' if slot['kind']=='editorial-revision' or current['production']['revision'] else 'proposer'
    plan=None if plan_pin is None else verify_story(plan_pin,base_dir=workflow_root,campaign=campaign)['plan']
    resolution=None if resolution_pin is None else verify_resolution(plan_pin,resolution_pin,base_dir=workflow_root,campaign=campaign)
    loaded=current['loaded'] if resolution is None else resolution['loaded']
    prior_actual=_products(prior,workflow_root,campaign,plan_pin) if plan_pin is not None else []
    context=_context(current,slot,plan,prior_actual,None if resolution is None else resolution['record'])
    presented=integrity._new(root/'phase-context.json',context)
    visual_loaded=_visual_scope(current,slot,loaded,plan)
    packet=mp._author_packet(root/'author-packet',visual_loaded,role=role)
    context_transport='source-artifact-v1'
    spec=_spec(current,slot,presented,current['request_pin'],packet,role,visual_loaded,context_transport=context_transport)
    if 'goal_binding' in state['contract']:spec['goal_binding']=deepcopy(state['contract']['goal_binding'])
    graph=root/'graph';agent_graph.create(graph,spec)
    binding={'schema_version':2,'kind':'manuscript-phase-binding','request':current['request_pin'],'source_epoch':current['source_epoch'],
        'input_pins':current['input_pins'],'workflow_root':str(Path(workflow_root).absolute()),'initial':initial,'campaign':str(Path(campaign).absolute()),
        'prepared_campaign_sha256':state['sha256'],'phase_id':slot['id'],'plan':plan_pin,'prior_products':prior,'resolution':resolution_pin,
        'presentation':presented,'packet':packet,'spec':spec,'graph':str(graph),'author_id':current['production']['author_id'],'context_transport':context_transport,'execution_authorized':False}
    binding_pin=integrity._new(root/'binding.json',binding)
    if _load(current['request_pin'],Path(current['request_pin']['path']).parent)!=current:raise ValueError('whole source changed during phase preparation')
    return {'binding':binding,'binding_pin':binding_pin,'execution_authorized':False}


def _binding(value,base):
    if type(value) is dict and set(value)=={'binding','binding_pin','execution_authorized'}:
        current=_read(value['binding_pin'],base)
        if current!=value['binding'] or value['execution_authorized'] is not False:raise ValueError('prepared phase wrapper differs from actual binding')
        return current
    return _read(value,base)


def execute_phase(binding,host):
    binding=_binding(binding,Path.cwd())
    if binding.get('kind')=='manuscript-synthesis-slot':return mp.execute_writer(binding['author_binding'],host)
    _phase_state(binding,require_complete=False)
    return cycle.execute_graph(binding['campaign'],binding['graph'],binding['spec'],host,prepared=True)


def _phase_state(binding,*,require_complete=True,_origin=None):
    if _origin is not None and not require_complete:
        raise ValueError('historical origin never authorizes preparation or execution')
    ce.keys(binding,['schema_version','kind','request','source_epoch','input_pins','workflow_root','initial','campaign','prepared_campaign_sha256',
        'phase_id','plan','prior_products','resolution','presentation','packet','spec','graph','author_id','execution_authorized']
        +(['context_transport'] if 'context_transport' in binding else []))
    mp._artifact_context(binding.get('context_transport'))
    if binding['schema_version']!=2 or binding['kind']!='manuscript-phase-binding' or binding['execution_authorized'] is not False:raise ValueError('actual source-defined phase binding required')
    current=_load(binding['request'],binding['workflow_root'])
    state=_campaign(current,binding['campaign']) if _origin is None else _campaign(current,binding['campaign'],_origin=_origin,_binding=binding)
    if current['source_epoch']!=binding['source_epoch'] or current['input_pins']!=binding['input_pins']:raise ValueError('phase source epoch/input population changed')
    initial=_read(binding['initial'],binding['workflow_root'])
    if initial!={'request':current['request_pin'],'source_epoch':current['source_epoch'],'input_pins':current['input_pins']}:raise ValueError('phase initial source commitment changed')
    slot=next((s for s in current['slots'] if s['id']==binding['phase_id']),None)
    if slot is None or slot['kind']=='synthesis':raise ValueError('unknown or wrong phase consumer')
    root=Path(binding['workflow_root'])/'issued'/slot['id']
    if binding['graph']!=str(root/'graph') or _read(mp._pin(root/'binding.json'),root)!=binding:raise ValueError('phase is not its unique original issued slot')
    prior=_products(binding['prior_products'],binding['workflow_root'],binding['campaign'],binding['plan'],_origin=_origin) if binding['plan'] is not None else []
    if [p['phase_id'] for p in prior]!=slot['depends_on']:raise ValueError('actual complete phase dependencies differ')
    plan=None if binding['plan'] is None else verify_story(binding['plan'],base_dir=root,campaign=binding['campaign'],_origin=_origin)['plan']
    if slot['kind']=='story' and (binding['plan'] is not None or prior or binding['resolution'] is not None):raise ValueError('story0 cannot borrow a prepared/speculative plan')
    resolution=None if binding['resolution'] is None else verify_resolution(binding['plan'],binding['resolution'],base_dir=root,campaign=binding['campaign'],_origin=_origin)
    loaded=current['loaded'] if resolution is None else resolution['loaded']
    context=_context(current,slot,plan,prior,None if resolution is None else resolution['record'])
    if _read(binding['presentation'],root)!=context:raise ValueError('phase changed full retained source/plan/dependency context')
    role='improver' if slot['kind']=='editorial-revision' or current['production']['revision'] else 'proposer'
    visual_loaded=_visual_scope(current,slot,loaded,plan)
    spec=_spec(current,slot,binding['presentation'],current['request_pin'],binding['packet'],role,visual_loaded,
        context_transport=binding.get('context_transport'))
    if 'goal_binding' in state['contract']:spec['goal_binding']=deepcopy(state['contract']['goal_binding'])
    if spec!=binding['spec'] or state_io.read_json(root/'graph'/agent_graph.SPEC)!=spec:raise ValueError('phase prompt/schema/reservation changed')
    mp._check_source_review(loaded)
    if not require_complete:return current,slot,loaded,None,None,None,None
    receipt=agent_graph.role_receipt(binding['graph'],'author',expected_subject_sha256=binding['presentation']['sha256'],
        expected_packet_sha256=binding['packet']['manifest_sha256'] if binding['packet'] else None,require_exact_subject=True,allowed_roles={role})
    if receipt['execution_observation'] in {'control_only','unestablished'}:raise ValueError('actual writing phase cannot be asserted from control or unestablished transport')
    if state['sha256']==binding['prepared_campaign_sha256'] or not any(r['root']==binding['graph'] and r.get('complete') for r in state['graphs']):raise ValueError('phase lacks its completed charged campaign step')
    checkpoint=agent_graph.status(binding['graph']);saved=agent_graph._result(Path(binding['graph']),checkpoint['nodes']['author']['result'])
    if saved['result']['transport'].get('observed_model')!=slot['runtime']['model_build']:raise ValueError('actual phase model build differs or remains unknown')
    if slot['runtime']['action']=='external' and saved['result']['transport'].get('actor_id')!=binding['author_id']:raise ValueError('phase external author differs')
    calls=[]
    for ref in saved['call_receipts']:
        path=Path(binding['graph'])/'calls'/(ref['call_id']+'.json');call=state_io.read_json(path)
        if ce.digest(call)!=ref['sha256']:raise ValueError('phase call transcript changed')
        calls.append({'pin':mp._pin(path),'receipt':call})
    if len(calls)!=1:raise ValueError('each actual writing phase requires its own single accounted call; no aggregate receipt')
    accounting=mp._writer_accounting(slot['runtime'],receipt,saved,checkpoint,calls)
    vision=mp._verify_author_vision(receipt,visual_loaded,binding['packet'],'author',role)
    return current,slot,loaded,receipt,calls,accounting,vision


def _value(value,slot,current,loaded,plan):
    if slot['kind']=='story':return _plan(value,current)
    ce.keys(value,['paragraphs','figures','tasks','unresolved']+(['claim_dispositions'] if 'claim_dispositions' in value else []))
    roster=next(r for r in plan['phases'] if r['id']==slot['id']);p=_population(current)
    actual_citations=set(loaded['citations']);actual_evidence=set(loaded['evidence']);actual_methods=set(loaded['methods'])
    seen=set()
    for row in _rows(value['paragraphs'],'actual section/refinement paragraphs',limit=mp.MAX_PARAGRAPHS):
        ce.keys(row,['id','section','kind','text','method_ids','citation_ids','evidence_ids','uncertainties']);ce.identity(row['id']);integrity._text(row['text'])
        if row['id'] in seen or row['section'] not in roster['section_ids'] or row['kind'] not in {'claim','method'}:raise ValueError('phase paragraph lies outside actual story scope')
        seen.add(row['id'])
        _ids(row['method_ids'],'paragraph methods',allowed=actual_methods);_ids(row['citation_ids'],'paragraph citations',allowed=actual_citations)
        _ids(row['evidence_ids'],'paragraph evidence',allowed=actual_evidence)
        for x in _rows(row['uncertainties'],'paragraph uncertainties'):integrity._text(x)
    if slot['kind']=='section' and {r['section'] for r in value['paragraphs']}!=set(roster['section_ids']):
        raise ValueError('section phase dropped its complete declared section population')
    figs=set()
    for row in _rows(value['figures'],'actual captions',limit=64):
        ce.keys(row,['id','caption','citation_ids','uncertainties']);integrity._text(row['caption'])
        if row['id'] in figs or row['id'] not in roster['figure_ids'] or row['id'] not in loaded['figures']:raise ValueError('caption lacks its declared actual figure')
        figs.add(row['id']);_ids(row['citation_ids'],'caption citations',allowed=actual_citations)
        for x in _rows(row['uncertainties'],'caption uncertainties'):integrity._text(x)
    if slot['kind']=='caption' and figs!=set(roster['figure_ids']):raise ValueError('caption phase dropped figure population')
    tasks=set()
    for row in _rows(value['tasks'],'actual bounded citation/acquisition tasks'):
        ce.keys(row,['obligation_id','query','source_scope','claim_ids','failure_or_missing'])
        if row['obligation_id'] not in roster['obligation_ids'] or row['obligation_id'] in tasks:raise ValueError('foreign/duplicate acquisition task')
        tasks.add(row['obligation_id']);_ids(row['claim_ids'],'task claims',allowed=[r['id'] for r in plan['claim_map']])
        for k in ('query','source_scope','failure_or_missing'):integrity._text(row[k])
    if slot['kind']=='citation-scout' and tasks!=set(roster['obligation_ids']):raise ValueError('scout dropped missing acquisition obligations')
    _ids(value['unresolved'],'actual unresolved obligations',allowed=current['missing'])
    # A model task describes acquisition. It never supplies acquired bytes or claims resolution.
    if slot['kind']=='citation-scout' and not tasks<=set(value['unresolved']):raise ValueError('scout cannot self-certify acquired bibliography')
    claim_disposition.validate(plan,value.get('claim_dispositions'),value,actual_evidence,expected_ids=roster['claim_ids'])
    return deepcopy(value)


def consume_phase(binding,out,*,base_dir):
    binding=_binding(binding,base_dir)
    if binding.get('kind')=='manuscript-synthesis-slot':
        raise ValueError('terminal synthesis is materialized only by assemble after every phase is verified')
    current,slot,loaded,receipt,calls,accounting,vision=_phase_state(binding)
    plan=None if binding['plan'] is None else verify_story(binding['plan'],base_dir=base_dir,campaign=binding['campaign'])['plan']
    value=_value(receipt['public_value'],slot,current,loaded,plan)
    record={'schema_version':2,'kind':'manuscript-story' if slot['kind']=='story' else 'manuscript-phase-product',
        'binding':mp._pin(Path(binding['graph']).parent/'binding.json'),'request':current['request_pin'],'plan':binding['plan'],
        'phase_id':slot['id'],'source_epoch':current['source_epoch'],'input_pins':current['input_pins'],
        'graph':binding['graph'],'node':'author','packet':binding['packet'],'actual_receipt':receipt,'actual_calls':calls,
        'actual_usage':accounting,'visual_presentation':vision,'output':value,'scientific_acceptance':False,'execution_authorized':False}
    expected=Path(binding['graph']).parent/'consumed'
    if Path(out).absolute()!=expected:raise ValueError('actual phase product must use its unique retained consumption slot')
    root=mp._fresh(out);pin=integrity._new(root/'product.json',record)
    verify_product(pin,base_dir=root,campaign=binding['campaign'])
    return {'product':pin,'phase_id':slot['id'],'unresolved':deepcopy(value.get('unresolved',[])),'execution_authorized':False}


def phase_destination(story_pin,phase_id,*,base_dir,campaign):
    """Exact reserved output, derived from the actual consumed story."""
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign)
    if phase_id not in {s['id'] for s in story['current']['slots'][1:]}:
        raise ValueError('known later original phase required')
    return Path(story['binding']['workflow_root'])/'issued'/phase_id


def consumption_destination(binding,*,base_dir):
    """Exact consumption slot; arbitrary model output paths have no authority."""
    binding=_binding(binding,base_dir)
    _phase_state(binding,require_complete=False)
    return Path(binding['graph']).parent/'consumed'


def verify_product(pin,*,base_dir,campaign,_origin=None):
    d=_read(pin,base_dir);binding=_read(d['binding'],base_dir)
    if binding['campaign']!=str(Path(campaign).absolute()):raise ValueError('foreign phase campaign')
    current,slot,loaded,receipt,calls,accounting,vision=_phase_state(binding) if _origin is None else _phase_state(binding,_origin=_origin)
    plan=None if binding['plan'] is None else verify_story(binding['plan'],base_dir=base_dir,campaign=campaign,_origin=_origin)['plan']
    value=_value(receipt['public_value'],slot,current,loaded,plan)
    expected={'schema_version':2,'kind':'manuscript-story' if slot['kind']=='story' else 'manuscript-phase-product',
        'binding':mp._pin(Path(binding['graph']).parent/'binding.json'),'request':current['request_pin'],'plan':binding['plan'],
        'phase_id':slot['id'],'source_epoch':current['source_epoch'],'input_pins':current['input_pins'],
        'graph':binding['graph'],'node':'author','packet':binding['packet'],'actual_receipt':receipt,'actual_calls':calls,
        'actual_usage':accounting,'visual_presentation':vision,'output':value,'scientific_acceptance':False,'execution_authorized':False}
    if d!=expected:raise ValueError('phase product differs from its actual current receipt/source/visual wire')
    for p in [d['binding'],*d['input_pins'],*[r['pin'] for r in calls]]:integrity._raw(p,base_dir,{})
    return d


def verify_story(pin,*,base_dir,campaign,_origin=None):
    product=verify_product(pin,base_dir=base_dir,campaign=campaign,_origin=_origin)
    if product['kind']!='manuscript-story' or product['plan'] is not None:raise ValueError('consumed original story0 required; prepared plan is insufficient')
    binding=_read(product['binding'],base_dir)
    return {'product':product,'plan':product['output'],'binding':binding,'current':_load(product['request'],base_dir)}


def _products(pins,base,campaign,story_pin,*,_origin=None):
    rows=[];seen=set()
    for pin in _rows(pins,'actual full phase product pins',limit=MAX_PHASES):
        d=verify_product(pin,base_dir=base,campaign=campaign,_origin=_origin)
        if d['phase_id'] in seen or (d['kind']=='manuscript-story' and _canon(pin,base,{})!=_canon(story_pin,base,{})) or (d['kind']!='manuscript-story' and d['plan']!=story_pin):raise ValueError('duplicate/foreign actual story phase')
        seen.add(d['phase_id']);rows.append(d)
    return rows


def resolve_sources(story_pin,resolved_request_pin,out,*,base_dir,campaign):
    """Bind existing actual acquisition/plot products to every missing obligation.

    Citation records contain located identity evidence; figure records contain
    actual plot contracts/source evidence. No scout result supplies new bytes.
    This is preparation only, never source applicability or scientific approval.
    """
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign)
    record=_resolution_record(story,resolved_request_pin,base_dir)
    root=mp._fresh(out);pin=integrity._new(root/'resolved-sources.json',record)
    verify_resolution(story_pin,pin,base_dir=root,campaign=campaign)
    return {'resolution':pin,'execution_authorized':False,'scientific_acceptance':False}


def _bound_record(value,base):
    if type(value) is dict:
        if set(value)=={'path','sha256','size'}:return _canon(value,base,{})
        return {k:_bound_record(v,base) for k,v in value.items()}
    if type(value) is list:return [_bound_record(v,base) for v in value]
    return value


def _resolution_record(story,resolved_pin,base):
    current=story['current'];resolved_pin=_canon(resolved_pin,base,{})
    request=_read(resolved_pin,base);loaded=mp._load(request,Path(resolved_pin['path']).parent)
    original=current['production'];mutable={'citations','figures','methods','source_manifest','source_review','author_visuals'}
    if _bound_record({k:v for k,v in request.items() if k not in mutable},loaded['source_base'])!=_bound_record({k:v for k,v in original.items() if k not in mutable},current['loaded']['source_base']):raise ValueError('source acquisition changed original task/context/runtime/format/approval')
    mappings={};before=current['loaded']
    for kind,field in [('citation','citations'),('figure','figures'),('method','methods'),('evidence','evidence')]:
        known=before[field];after=loaded[field]
        missing={k for k,r in current['missing'].items() if r['kind']==kind}
        if set(after)!=set(known)|missing:raise ValueError('resolved sources dropped/added undeclared original population')
        for k in known:
            # Rebase each request with its own authenticated document parent,
            # then compare actual complete source-bound records, not path labels.
            if _bound_record(after[k],loaded['source_base'])!=_bound_record(known[k],before['source_base']):raise ValueError('resolution rewrote an existing source record')
        for k in missing:mappings[k]={'kind':kind,'actual_record':deepcopy(after[k])}
    # Old method citation references may become available, but their definitions
    # and exact executed/source records cannot be rewritten during acquisition.
    for p in before['input_pins']:integrity._dependency(p,before['source_base'],{})
    mp._check_source_review(loaded)
    return {'schema_version':2,'kind':'manuscript-source-resolution','story_binding':story['product']['binding'],
        'request':current['request_pin'],'source_epoch':current['source_epoch'],'resolved_request':resolved_pin,
        'complete_original_obligations':list(current['missing']),'resolved':mappings,'input_pins':loaded['input_pins'],
        'scientific_acceptance':False,'execution_authorized':False}


def verify_resolution(story_pin,pin,*,base_dir,campaign,_origin=None):
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign,_origin=_origin);record=_read(pin,base_dir)
    expected=_resolution_record(story,record['resolved_request'],base_dir)
    if record!=expected:raise ValueError('missing obligation resolution changed or used a foreign epoch')
    loaded=mp._load(_read(record['resolved_request'],base_dir),Path(record['resolved_request']['path']).parent)
    return {'record':record,'loaded':loaded}


def prepare_phase(story_pin,phase_id,out,*,base_dir,campaign,prior_products,resolution_pin=None):
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign);current=story['current'];state=_campaign(current,campaign)
    slot=next((s for s in current['slots'] if s['id']==phase_id),None)
    if slot is None or slot['kind']=='story':raise ValueError('known later story phase required')
    root=Path(story['binding']['workflow_root']);expected=root/'issued'/phase_id
    if Path(out).absolute()!=expected:raise ValueError('each reserved phase is issued once at its exact original slot')
    products=_products(prior_products,base_dir,campaign,story_pin)
    if [p['phase_id'] for p in products]!=slot['depends_on']:raise ValueError('whole ordered actual phase dependency population required')
    if slot['kind']=='synthesis':
        if resolution_pin is None:raise ValueError('final synthesis requires complete acquired/plot source resolution')
        resolution=verify_resolution(story_pin,resolution_pin,base_dir=base_dir,campaign=campaign)
        request=deepcopy(resolution['loaded']['request'])
        if request['runtime']!=slot['runtime']:raise ValueError('final synthesis runtime must equal original strict production/runtime binding')
        stages={'story':story_pin,'resolution':resolution_pin,'products':prior_products}
        author=mp.prepare_writer(request,out,base_dir=resolution['loaded']['source_base'],campaign=campaign,stages=stages)
        value={'schema_version':2,'kind':'manuscript-synthesis-slot','phase_id':phase_id,'story':story_pin,
            'resolution':resolution_pin,'products':prior_products,'campaign':str(Path(campaign).absolute()),'author_binding':author,'execution_authorized':False}
        pin=integrity._new(Path(out)/'synthesis-slot.json',value)
        return {'binding':value,'binding_pin':pin,'execution_authorized':False}
    return _prepare(current,slot,out,campaign,workflow_root=root,plan_pin=story_pin,prior=prior_products,resolution_pin=resolution_pin,state=state,initial=story['binding']['initial'])


def verify_transcript(stages,loaded,campaign,*,_origin=None):
    ce.keys(stages,['story','resolution','products'])
    story=verify_story(stages['story'],base_dir=loaded['source_base'],campaign=campaign,_origin=_origin);current=story['current']
    resolution=verify_resolution(stages['story'],stages['resolution'],base_dir=loaded['source_base'],campaign=campaign,_origin=_origin)
    if resolution['loaded']!=loaded:raise ValueError('terminal author changed fully resolved original source request')
    products=_products(stages['products'],loaded['source_base'],campaign,stages['story'],_origin=_origin)
    if [p['phase_id'] for p in products]!=[s['id'] for s in current['slots'][:-1]]:raise ValueError('final author cannot omit pending/failed/unissued original phase slots')
    # Every actual figure has a current native caption-phase presentation.
    # Each helper verification above checks all pages and raster/wire bytes.
    # Final synthesis is a distinct text synthesis of these consumed products.
    required=mp._visual_inputs(loaded['request'],loaded['source_base'],{})
    seen_figures=set();seen_sources=[]
    for product in products:
        slot=next(s for s in current['slots'] if s['id']==product['phase_id'])
        if slot['kind']!='caption':continue
        scoped=_visual_scope(current,slot,loaded,story['plan'])
        ids=set(scoped['figures']);seen_figures.update(ids)
        expected=mp._visual_inputs(scoped['request'],scoped['source_base'],{})
        visual=product['visual_presentation']
        if expected and (visual is None or visual['required_sources']!=expected):raise ValueError('caption omitted native actual source/page/wire evidence')
        for p in expected:
            if p not in seen_sources:seen_sources.append(p)
    if seen_figures!=set(loaded['figures']) or {(p['path'],p['sha256'],p['size']) for p in seen_sources}!={(p['path'],p['sha256'],p['size']) for p in required}:raise ValueError('whole original author figure population was not actually presented across caption phases')
    reservation=_budget(current['request']['budget'],current['slots'])
    accounting=[p['actual_usage'] for p in products]
    measured={k:(sum(r['usage'][k] for r in accounting) if all(r['usage'][k] is not None for r in accounting) else None)
        for k in ('input_tokens','output_tokens','total_tokens')}
    return {'schema_version':2,'kind':'actual-manuscript-writing-transcript','original_request':current['request_pin'],
        'source_epoch':current['source_epoch'],'story':stages['story'],'resolution':stages['resolution'],
        'phase_products':deepcopy(stages['products']),'complete_original_slots':current['slots'],
        'actual_prior_phases':products,'prior_measured_usage':measured,'prior_reserved_output_tokens':sum(r['reserved_output_tokens'] for r in accounting),
        'complete_prospective_reservation':reservation,'final_synthesis_included_here':False,
        'final_synthesis_receipt':'separate actual manuscript_production author receipt; never a forged aggregate call',
        'complete_author_visual_sources':required,'actual_caption_viewing_is_not_final_synthesis_viewing':True,'all_phase_scientific_acceptance':False,
        'original_claim_plan':deepcopy(story['plan']),
        'original_claim_evidence':_bound_record(story['current']['loaded']['evidence'],story['current']['loaded']['source_base']),
        'original_missing_claim_sources':_bound_record(story['current']['missing'],Path(current['request_pin']['path']).parent),
        'complete_phase_claim_census':[{'phase_id':p['phase_id'],'claim_dispositions':deepcopy(p['output']['claim_dispositions'])}
            for p in products if p['phase_id']!=current['slots'][0]['id']]}


def transcript_pins(stages,loaded,campaign,*,_origin=None):
    transcript=verify_transcript(stages,loaded,campaign,_origin=_origin);pins=[stages['story'],stages['resolution'],*stages['products']]
    for p in transcript['actual_prior_phases']:
        pins.extend([p['binding'],*p['input_pins'],*[r['pin'] for r in p['actual_calls']]])
    return list({_canon(p,loaded['source_base'],{})['path']:_canon(p,loaded['source_base'],{}) for p in pins}.values())


def assemble(story_pin,phase_products,out,*,base_dir,campaign,synthesis_binding):
    """Materialize the actual final synthesis plus every real earlier phase."""
    binding=_binding(synthesis_binding,base_dir)
    ce.keys(binding,['schema_version','kind','phase_id','story','resolution','products','campaign','author_binding','execution_authorized'])
    if binding['kind']!='manuscript-synthesis-slot' or binding['story']!=story_pin or binding['products']!=phase_products or binding['campaign']!=str(Path(campaign).absolute()):raise ValueError('foreign final writing population/campaign')
    author=binding['author_binding'];loaded,receipt,saved,checkpoint,calls=mp._author_state(author)
    transcript=verify_transcript(author['stages'],loaded,campaign)
    final=mp._writer_accounting(loaded['request']['runtime'],receipt,saved,checkpoint,calls)
    if len(calls)!=1:raise ValueError('terminal synthesis requires its own genuine accounted call')
    all_usage=[p['actual_usage'] for p in transcript['actual_prior_phases']]+[final]
    aggregate={'measured':{k:sum(x['usage'][k] for x in all_usage) if all(x['usage'][k] is not None for x in all_usage) else None for k in ('input_tokens','output_tokens','total_tokens')},
        'reserved_output_tokens':sum(x['reserved_output_tokens'] for x in all_usage),'calls':sum(len(p['actual_calls']) for p in transcript['actual_prior_phases'])+len(calls),
        'policies':[x['usage_policy'] for x in all_usage],'unknowns_preserved':True}
    if aggregate['calls']>transcript['complete_prospective_reservation']['max_calls'] or aggregate['reserved_output_tokens']>transcript['complete_prospective_reservation']['max_output_tokens']:raise ValueError('aggregate authoring exceeded original reservation')
    result=mp.collect(author,out)
    record={'schema_version':2,'kind':'staged-manuscript-assembly','package':result['package_pin'],'story':story_pin,
        'resolution':binding['resolution'],'phase_products':phase_products,'synthesis':mp._pin(Path(author['graph']).parent/'synthesis-slot.json'),
        'aggregate_usage':aggregate,'final_integrity_build_CI3_original_task_required':True,'scientific_acceptance':False}
    result['staged_assembly']=integrity._new(Path(out)/'writing-assembly.json',record)
    # Original final integrity/native/CI3/whole-parent consumers still own delivery.
    mp.verify_author(result['package'],base_dir=base_dir)
    return result


def prepare_revision(package_pin,review_bindings,out,*,base_dir,campaign,budget):
    """Actual independent objections become retained tasks, never editorial approval."""
    from . import scientific_judgment
    consumed={};package=_read(package_pin,base_dir,consumed)
    mp.verify_author_origin(package,base_dir=base_dir,consumed=consumed)
    author=_read(package['author_binding'],base_dir,consumed)
    original_campaign=Path(author['campaign']).resolve()
    if Path(campaign).resolve()!=original_campaign:
        raise ValueError('revision must retain the authenticated original author campaign')
    production=_read(author['request'],base_dir,consumed)
    loaded=mp._load(production,author['base_dir'])
    current={'production':production,'loaded':loaded}
    request=_read(package['integrity_request'],base_dir,consumed);assessment=integrity.assess(request,review_bindings,base_dir=package['source_base'])
    if not assessment['complete_actual_independent_roles']:raise ValueError('complete actual critic/verifier/synthesizer population required')
    objections=[];pins=[]
    for binding in review_bindings:
        verified=scientific_judgment.verify_binding(binding)
        if verified['contract']['actor_id']==package['author_id']:raise ValueError('author cannot independently review own writing')
        pins.extend(integrity.assessment_pins(request,[binding],base_dir=package['source_base']))
        if verified['value']['verdict']=='send_back':
            for row in verified['value']['audit']['nodes']:
                if row['decision']!='supported' or any(a['disposition']!='accepted' for a in row['assumptions']):objections.append({'role':verified['contract']['role'],'current_audit_item':deepcopy(row),
                    'scientific_response_required':True,'resolution':'unresolved'})
            for row in verified['value']['audit']['edges']:
                if row['decision']!='supported':objections.append({'role':verified['contract']['role'],'current_support_edge':deepcopy(row),
                    'scientific_response_required':True,'resolution':'unresolved'})
    if not objections:raise ValueError('revision needs actual located material objections, not a score/passbit')
    # Exact ordinary protocol handles scientific candidate/evidence invalidation.
    # This output only prepares those requests; it does not execute experiments.
    _,campaign_state=cycle._load(original_campaign)
    if campaign_state.get('parent_task') is not None:
        parent=cycle._read(campaign_state['parent_task']['contract'],original_campaign)
        if parent['prompt']!=loaded['documents']['original_task']:
            raise ValueError('revision must retain the authenticated current parent task')
    if type(budget) is not dict or set(budget)!=set(campaign_state['contract']['budget']):raise ValueError('actual remaining original campaign budget required')
    for k,v in budget.items():
        if type(v) is not int or v<0 or v>campaign_state['contract']['budget'][k]-cycle._usage(campaign_state)[k]:raise ValueError('revision cannot replenish original campaign reservation')
    root=mp._fresh(out)
    criticism=_criticism_identity(package,review_bindings,base_dir)
    campaign_state=_allocate_revision(original_campaign,campaign_state,criticism,budget)
    record={'schema_version':2,'kind':'manuscript-revision-obligations','prior_package':_canon(package_pin,base_dir,{}),
        'original_task':package['original_task'],'campaign':str(original_campaign),'source_epoch':_source_epoch(),
        'author_binding':_canon(package['author_binding'],base_dir,consumed),
        'campaign_state_sha256':campaign_state['sha256'],
        'campaign_context_sha256':ce.digest(campaign_state['context']),
        'actual_review_bindings':deepcopy(review_bindings),'actual_review_pins':pins,'objections':objections,
        'dependency_invalidation':['affected evidence/method/quantity/citation/figure','affected sections/captions/summary','native build','compiled CI3'],
        'ordinary_scientific_actions':['research_protocol additional_evidence','research_protocol candidate_revision','fresh_replication.prepare_replication_request'],
        'remaining_budget':deepcopy(budget),'unresolved':deepcopy(objections),'scientific_acceptance':False,'execution_authorized':False}
    pin=integrity._new(root/'revision-obligations.json',record)
    for p in [*pins,*consumed.values()]:integrity._dependency(p,base_dir,{})
    mp.verify_author_origin(package,base_dir=base_dir,consumed=consumed)
    if cycle._load(original_campaign)[1]!=campaign_state:
        raise ValueError('original campaign changed during revision preparation; recompute its remaining budget')
    return {'revision':pin,'scientific_acceptance':False,'execution_authorized':False}


def prepare_story_source_review(request_pin,out,*,base_dir):
    current=_load(request_pin,base_dir);loaded=current['loaded']
    if loaded['request'].get('blinding_policy') is None:raise ValueError('original-policy source review requested only for a blind manuscript')
    root=mp._fresh(out)
    presentation=integrity._new(root/'source-context.json',mp._presentation(loaded))
    request=mp._source_review_ir(loaded,presentation)
    preparation=integrity.prepare(request,base_dir=loaded['source_base'])
    pin=integrity._new(root/'source-review.json',request)
    return {'request':pin,'preparation':preparation,'initial_request':current['request_pin'],'execution_authorized':False}


def prepare_story_source_role(request_pin,source_request,out,*,base_dir,**arguments):
    current=_load(request_pin,base_dir);loaded=current['loaded']
    request=_read(source_request,base_dir)
    if request!=mp._source_review_ir(loaded,request['manuscript']):raise ValueError('partial planning source review changed complete known source context')
    return integrity.prepare_role(request,out,base_dir=loaded['source_base'],**arguments)


def consume_story_source_role(request_pin,source_request,binding,*,base_dir):
    current=_load(request_pin,base_dir);loaded=current['loaded'];request=_read(source_request,base_dir)
    if request!=mp._source_review_ir(loaded,request['manuscript']):raise ValueError('planning source context changed before review consumption')
    return integrity.consume_role(request,binding,base_dir=loaded['source_base'])


def prepare_literature(story_pin,scout_product_pin,literature_request_pin,out,*,base_dir,campaign):
    """Invoke only the existing located-literature producer after a real scout.

    Its source/extraction/acquisition failures remain in the returned product.
    A bibliography is not inferred from search snippets or an author task.
    """
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign)
    scout=verify_product(scout_product_pin,base_dir=base_dir,campaign=campaign)
    slot=next(s for s in story['current']['slots'] if s['id']==scout['phase_id'])
    if slot['kind']!='citation-scout' or scout['plan']!=story_pin:raise ValueError('actual current source-bound scout required')
    from . import literature_context
    issued=_read(literature_request_pin,base_dir)
    if issued.get('acquisition_tasks')!=scout['output']['tasks']:raise ValueError('literature acquisition request must retain every actual ordered scout task')
    result=literature_context.prepare(literature_request_pin,out,base_dir=base_dir)
    actual=literature_context.consume(result['product'],base_dir=base_dir)
    if actual!=result or actual['context'].get('acquisition_tasks')!=scout['output']['tasks']:raise ValueError('located acquisition/extraction product changed or lost original scout tasks')
    return {'scout':_canon(scout_product_pin,base_dir,{}),'story':story_pin,'located_product':result,
        'complete_scout_tasks':scout['output']['tasks'],'bibliography_accepted':False,'execution_authorized':False}


def prepare_supplementary(revision_pin,method_id,check_contract_pin,out,*,base_dir):
    """Material scientific objections use the ordinary fresh replication producer."""
    revision=_read(revision_pin,base_dir)
    if revision.get('kind')!='manuscript-revision-obligations' or not revision.get('objections'):raise ValueError('actual material revision request required')
    package=_read(revision['prior_package'],base_dir);mp.verify_author(package,base_dir=base_dir)
    request=_read(package['integrity_request'],base_dir)
    actual=integrity.assess(request,revision['actual_review_bindings'],base_dir=package['source_base'])
    if not actual['complete_actual_independent_roles']:raise ValueError('current full independent revision population required')
    if revision['source_epoch']!=_source_epoch() or revision['original_task']!=package['original_task']:raise ValueError('revision changed original source/parent')
    from . import scientific_judgment
    expected=[]
    for binding in revision['actual_review_bindings']:
        reviewed=scientific_judgment.verify_binding(binding)
        if reviewed['value']['verdict']!='send_back':continue
        for row in reviewed['value']['audit']['nodes']:
            if row['decision']!='supported' or any(a['disposition']!='accepted' for a in row['assumptions']):expected.append({'role':reviewed['contract']['role'],'current_audit_item':deepcopy(row),'scientific_response_required':True,'resolution':'unresolved'})
        for row in reviewed['value']['audit']['edges']:
            if row['decision']!='supported':expected.append({'role':reviewed['contract']['role'],'current_support_edge':deepcopy(row),'scientific_response_required':True,'resolution':'unresolved'})
    if revision['objections']!=expected or revision['unresolved']!=expected:raise ValueError('supplementary work cannot replace or self-resolve actual material objections')
    if method_id not in {m['id'] for m in request['methods']}:raise ValueError('supplementary method lies outside actual original report')
    from . import fresh_replication
    product=fresh_replication.prepare_replication_request(revision['campaign'],package['integrity_request'],method_id,out,check_contract_pin=check_contract_pin)
    return {'revision':_canon(revision_pin,base_dir,{}),'fresh_request':product,
        'prior_objections_resolved':False,'execution_authorized':False,'scientific_acceptance':False}


def phase_status(story_pin,*,base_dir,campaign):
    """Full source-defined slot census, retaining failed/pending/unissued attempts.

    Unknown-started effects are not redrawn or reissued here. This readback is
    diagnostic; only consume_phase authenticates completed author products.
    """
    story=verify_story(story_pin,base_dir=base_dir,campaign=campaign);current=story['current'];root=Path(story['binding']['workflow_root'])
    rows=[]
    actual_names={p.name for p in (root/'issued').iterdir()}
    if not actual_names<=set(s['id'] for s in current['slots']):raise ValueError('undeclared original phase namespace')
    for slot in current['slots']:
        owned=root/'issued'/slot['id'];bindingpath=owned/('synthesis-slot.json' if slot['kind']=='synthesis' else 'binding.json')
        row={'phase_id':slot['id'],'kind':slot['kind'],'reservation':deepcopy(slot['runtime']),'state':'unissued','binding':None,'graph_state':None,'consumed_product':None}
        if owned.exists():
            if owned.is_symlink():raise ValueError('phase slot alias')
            if not bindingpath.exists():row['state']='interrupted_preparation_unresolved'
            else:
                pin=mp._pin(bindingpath);binding=_read(pin,owned)
                if slot['kind']=='synthesis':
                    graph=binding['author_binding']['graph']
                else:
                    _phase_state(binding,require_complete=False);graph=binding['graph']
                checkpoint=agent_graph.status(graph);row.update(binding=pin,graph_state=checkpoint,state=checkpoint['nodes']['author']['status'])
                product=owned/'consumed/product.json'
                if product.exists():
                    row['consumed_product']=mp._pin(product);verify_product(row['consumed_product'],base_dir=owned,campaign=campaign)
        rows.append(row)
    return {'kind':'complete-manuscript-phase-status','story':story_pin,'complete_original_denominator':len(rows),'slots':rows,
        'unknown_started_effect_reissued':False,'scientific_acceptance':False,'execution_authorized':False}




def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def _method_semantics(row, base_dir):
    """Source/operation law; new observations do not themselves alter a method."""
    row=deepcopy(row)
    for operation in row['operations']:
        for field in ('execution','results','differences'):operation.pop(field,None)
    return _bound_record(row,base_dir)


def _criticism_identity(package, bindings, base_dir):
    """Authenticated complete review identity; copied file locators do not reset it."""
    from . import scientific_judgment
    author=_canon(package['author_binding'],base_dir,{})
    subject=_canon(package['integrity_request'],base_dir,{})
    reviews=[]
    for binding in bindings:
        actual=scientific_judgment.verify_binding(binding)
        reviews.append({'role':actual['contract']['role'],
            'contract':actual['contract'],'receipt':actual['receipt'],'value':actual['value']})
    reviews.sort(key=lambda r:(r['role'],ce.digest(r)))
    return ce.digest({'author':{k:author[k] for k in ('sha256','size')},
        'integrity_request':{k:subject[k] for k in ('sha256','size')},
        'reviews':reviews})


def _history_state(campaign, current, *, revision=None, sha256=None):
    """Select only from the ordinary already-authenticated immutable chain."""
    if revision is not None:
        if type(revision) is not int or not 0<=revision<=current['revision']:raise ValueError('actual campaign history revision required')
        records=[revision]
    else:
        if type(sha256) is not str:raise ValueError('actual campaign history identity required')
        records=range(current['revision']+1)
    for index in records:
        record=state_io.read_json(Path(campaign)/'history'/f'{index:04d}.json')
        content=deepcopy(record);checksum=content.pop('sha256')
        if checksum!=ce.digest(content) or record['revision']!=index:raise ValueError('campaign history commitment differs')
        if revision is not None or checksum==sha256:return record
    raise ValueError('revision preparation is absent from authenticated current campaign ancestry')


def _revision_allocation(campaign, state, criticism):
    matches=[e for e in state['events'] if e['kind']=='manuscript_revision_allocated' and e['criticism_sha256']==criticism]
    if not matches:raise ValueError('actual first criticism allocation required')
    event=matches[0]
    if len(matches)!=1:raise ValueError('same criticism cannot replenish its revision allocation')
    ce.keys(event,['revision','kind','criticism_sha256','preparation_state_sha256','usage','budget'])
    allocated=_history_state(campaign,state,revision=event['revision'])
    before=_history_state(campaign,state,revision=event['revision']-1)
    if (allocated['events']!=before['events']+[event] or allocated['parent_sha256']!=before['sha256']
            or before['sha256']!=event['preparation_state_sha256']
            or allocated['resource_ledger']!=before['resource_ledger']
            or state['resource_ledger'][:len(before['resource_ledger'])]!=before['resource_ledger']
            or _encoded(event['usage'])!=_encoded(cycle._usage(before))):
        raise ValueError('original charged revision baseline differs from actual preparation history')
    ce.keys(event['budget'],before['contract']['budget'])
    if any(type(v) is not int or v<0 or v>before['contract']['budget'][k]-event['usage'][k] for k,v in event['budget'].items()):
        raise ValueError('original finite revision reservation required')
    return deepcopy(event)


def _allocate_revision(campaign, expected, criticism, budget):
    """One ordinary journal commitment, never a new account or global allowance."""
    with state_io.file_lock(Path(campaign)/'operation.lock',blocking=False):
        _,state=cycle._load(campaign)
        if state!=expected:raise ValueError('campaign changed before criticism allocation')
        existing=[e for e in state['events'] if e['kind']=='manuscript_revision_allocated' and e['criticism_sha256']==criticism]
        if existing:
            original=_revision_allocation(campaign,state,criticism)
            if _encoded(original['budget'])!=_encoded(budget):raise ValueError('same criticism cannot replenish its revision allocation')
            return state
        return cycle._commit(Path(campaign),state,'manuscript_revision_allocated',criticism_sha256=criticism,
            preparation_state_sha256=state['sha256'],usage=cycle._usage(state),budget=deepcopy(budget))


def _register_action_graph(action_plan_pin, graph_root, spec, *, base_dir, campaign, kind):
    """Bind a prepared ordinary graph to its existing revision suballocation."""
    if kind not in {'meta','writer'}:raise ValueError('ordinary manuscript graph kind required')
    with state_io.file_lock(Path(campaign)/'operation.lock',blocking=False):
        current=verify_actions(action_plan_pin,base_dir=base_dir,campaign=campaign);state=current['state']
        if kind=='meta' and not any(r['kind'] in {'empirical','core-method'} for r in current['plan']['actions']):
            raise ValueError('no scientific meta call for purely editorial actions')
        bound=deepcopy(spec)
        if 'goal_binding' in state['contract']:bound['goal_binding']=deepcopy(state['contract']['goal_binding'])
        bound=agent_graph.validate(bound);budget=bound['budget']
        needed={'calls':budget['max_calls'],'output_tokens':budget['max_output_tokens'],'wall_seconds':budget['max_wall_seconds'],'native_attempts':0}
        _action_allowance(current,needed)
        graph_root=str(cycle._ordinary(graph_root))
        if any(e['kind']=='manuscript_action_graph_prepared' and e['graph_root']==graph_root for e in state['events']):
            raise ValueError('manuscript graph preparation already registered')
        return cycle._commit(Path(campaign),state,'manuscript_action_graph_prepared',graph_root=graph_root,
            specification_sha256=ce.digest(bound),action_plan=current['pin'],graph_kind=kind)


def _action_graph_admission(campaign, state, graph_root, spec, amount, *, reserved, require_registered=False):
    """Optional ordinary dispatch check; retained reservations never charge twice."""
    graph_root=str(graph_root)
    matches=[e for e in state['events'] if e['kind']=='manuscript_action_graph_prepared' and e['graph_root']==graph_root]
    if not matches:
        # Actual authenticated context decides admission. Copying the packet,
        # relabeling its graph or moving its root cannot erase its allocation.
        from . import review_context
        for node in spec['nodes']:
            packet=node.get('packet')
            if packet is None:continue
            index=review_context._PacketIndex(Path(packet['path']),expected_manifest_sha256=packet['manifest_sha256'])
            for entry in index.entries.values():
                raw=index.read(entry)
                try:value=review_context._strict_json_bytes(raw)
                except (UnicodeError,ValueError):continue  # Ordinary prose/binary is not an action context.
                actions=value.get('manuscript_actions') if type(value) is dict else None
                if type(actions) is dict and actions.get('action_plan') is not None:require_registered=True
            index.finish()
        if require_registered:raise ValueError('original manuscript graph preparation registration required')
        return
    if len(matches)!=1:raise ValueError('one original manuscript graph preparation required')
    event=matches[0]
    prepared=_history_state(campaign,state,revision=event['revision'])
    if prepared['events'][-1]!=event or event['specification_sha256']!=ce.digest(spec):raise ValueError('original manuscript graph specification changed')
    current=verify_actions(event['action_plan'],base_dir=state['base_dir'],campaign=campaign)
    if current['state']!=state:raise ValueError('campaign changed during manuscript dispatch admission')
    if not reserved:
        _action_allowance(current,amount)
        return
    identity='graph:'+graph_root
    row=next(r for r in state['resource_ledger'] if r['id']==identity)
    charges=[e for e in state['events'] if e['kind']=='ordinary_graph_reserved' and e['graph_root']==graph_root]
    if len(charges)!=1 or charges[0]['revision']<=event['revision']:raise ValueError('original manuscript graph charge ancestry required')
    before=_history_state(campaign,state,revision=charges[0]['revision']-1)
    charged=_history_state(campaign,state,revision=charges[0]['revision'])
    if (charged['events']!=before['events']+[charges[0]] or charged['resource_ledger']!=before['resource_ledger']+[row]
            or _encoded(row['ceiling'])!=_encoded(amount)):
        raise ValueError('original manuscript graph reservation changed')
    # Judge its original full reservation at the actual charge boundary. Later
    # unrelated charges cannot authorize a new call or erase this retained one.
    _action_allowance({**current,'state':before},amount)


def _revision_inputs(revision_pin, base_dir, campaign):
    """Authenticate the saved criticism; a new research epoch may change context."""
    from . import scientific_judgment
    consumed={};revision_pin=_canon(revision_pin,base_dir,consumed)
    revision=_read(revision_pin,base_dir,consumed)
    ce.keys(revision,['schema_version','kind','prior_package','original_task','campaign','source_epoch','author_binding',
        'campaign_state_sha256','campaign_context_sha256','actual_review_bindings','actual_review_pins','objections',
        'dependency_invalidation','ordinary_scientific_actions','remaining_budget','unresolved','scientific_acceptance','execution_authorized'])
    if revision.get('schema_version')!=2 or revision.get('kind')!='manuscript-revision-obligations':
        raise ValueError('actual manuscript revision obligations required')
    if revision['source_epoch']!=_source_epoch() or revision['campaign']!=str(Path(campaign).resolve()):
        raise ValueError('revision source/campaign changed')
    package=_read(revision['prior_package'],base_dir,consumed)
    mp.verify_author_origin(package,base_dir=base_dir,consumed=consumed)
    author=_read(package['author_binding'],base_dir,consumed)
    if (Path(author['campaign']).resolve()!=Path(campaign).resolve()
            or revision['author_binding']!=_canon(package['author_binding'],base_dir,consumed)
            or revision['original_task']!=package['original_task']):
        raise ValueError('revision original author/task lineage changed')
    production=_read(author['request'],base_dir,consumed)
    loaded=mp._load(production,author['base_dir'])
    for pin in loaded['input_pins']:integrity._dependency(pin,loaded['source_base'],consumed)
    ir=_read(package['integrity_request'],base_dir,consumed)
    assessed=integrity.assess(ir,revision['actual_review_bindings'],base_dir=package['source_base'])
    if not assessed['complete_actual_independent_roles']:raise ValueError('whole actual original review required')
    objections=[]
    for binding in revision['actual_review_bindings']:
        reviewed=scientific_judgment.verify_binding(binding)
        if reviewed['contract']['actor_id']==package['author_id']:raise ValueError('independent original reviewer required')
        for pin in integrity.assessment_pins(ir,[binding],base_dir=package['source_base']):integrity._dependency(pin,base_dir,consumed)
        if reviewed['value']['verdict']!='send_back':continue
        for row in reviewed['value']['audit']['nodes']:
            if row['decision']!='supported' or any(a['disposition']!='accepted' for a in row['assumptions']):
                objections.append({'role':reviewed['contract']['role'],'current_audit_item':deepcopy(row),
                    'scientific_response_required':True,'resolution':'unresolved'})
        for row in reviewed['value']['audit']['edges']:
            if row['decision']!='supported':objections.append({'role':reviewed['contract']['role'],
                'current_support_edge':deepcopy(row),'scientific_response_required':True,'resolution':'unresolved'})
    if not objections or revision['objections']!=objections or revision['unresolved']!=objections:
        raise ValueError('every actual unresolved objection must remain exact')
    _,state=cycle._load(campaign)
    if revision['scientific_acceptance'] is not False or revision['execution_authorized'] is not False:raise ValueError('revision record cannot grant scientific authority')
    if state.get('parent_task') is not None and cycle._read(state['parent_task']['contract'],Path(campaign))['prompt']!=loaded['documents']['original_task']:
        raise ValueError('original parent task changed')
    allocation=_revision_allocation(campaign,state,_criticism_identity(package,revision['actual_review_bindings'],base_dir))
    if _encoded(revision['remaining_budget'])!=_encoded(allocation['budget']):
        raise ValueError('original finite revision reservation differs from authenticated criticism allocation')
    prepared=_history_state(campaign,state,sha256=revision['campaign_state_sha256'])
    if prepared['revision']<allocation['revision'] or ce.digest(prepared['context'])!=revision['campaign_context_sha256']:
        raise ValueError('revision preparation must retain an actual post-allocation campaign context')
    return revision,package,loaded,ir,state,consumed


def _objection_dependencies(objection, ir, loaded, *, _claim_census=None):
    """Literal audit identities, with the complete dependent manuscript population."""
    row=objection.get('current_audit_item',objection.get('current_support_edge'))
    identity=row.get('id',row.get('child'))
    claims={c['id']:c for c in ir['claims']};methods=set(loaded['methods']);citations=set(loaded['citations'])
    cs=set();ms=set();rs=set()
    if identity.startswith('planned-claim.'):
        if _claim_census is None:
            if 'planned_claim_census' not in ir:raise ValueError('planned claim objection requires its actual census')
            _claim_census=_read(ir['planned_claim_census'],loaded['source_base'])
        disposition=next((r for r in _claim_census['rows'] if 'planned-claim.'+r['planned_claim_id']==identity),None)
        if disposition is None:raise ValueError('objection has no original planned claim')
        cs.update(disposition['paragraph_ids']);cs.update('figure-'+i for i in disposition['figure_ids'])
        ms.update(disposition['original']['method_ids']);rs.update(disposition['original']['citation_ids'])
    elif identity.startswith('claim.') and identity[6:] in claims:cs.add(identity[6:])
    elif identity.startswith('method.') and identity[7:] in methods:ms.add(identity[7:])
    elif identity.startswith('operation.') and identity[10:].split('.')[0] in methods:ms.add(identity[10:].split('.')[0])
    elif identity.startswith('citation.') and identity[9:] in citations:rs.add(identity[9:])
    elif identity=='manuscript-integrity' or identity.startswith('format.') or identity=='blinding-source-census':
        cs.update(claims);ms.update(methods);rs.update(citations)
    else:raise ValueError('objection has no current manuscript audit identity')
    ms.update(m for m,r in loaded['methods'].items() if rs.intersection(r['citation_ids']))
    cs.update(c for c,r in claims.items() if ms.intersection(r['method_ids']) or rs.intersection(r['citation_ids']))
    evidence={ce.digest(e) for c in cs for e in claims[c]['evidence']}
    fs={f for f,r in loaded['figures'].items() if any(ce.digest(loaded['evidence'][i]['located']) in evidence for i in r['evidence_ids'])}
    # Every response writes a fresh complete document. No old section/caption,
    # native build or CI3 result is exportable as the successor's final evidence.
    return {'claim_ids':sorted(cs),'method_ids':sorted(ms),'citation_ids':sorted(rs),'figure_ids':sorted(fs),
        'section_ids':[s['id'] for s in mp.manuscript_format.section_layout(loaded['formatting'])]}


def _action_rows(rows, revision, ir, loaded, protocol):
    from . import research_protocol as rp
    rows=_rows(rows,'complete manuscript objection actions',empty=False,limit=integrity.MAX_ITEMS)
    if len(rows)!=len(revision['objections']):raise ValueError('whole original objection denominator required')
    claim_census=None if 'planned_claim_census' not in ir else _read(ir['planned_claim_census'],loaded['source_base'])
    seen=set();claims={} if protocol is None else {c['id']:c for c in protocol['claims']}
    stages={} if protocol is None else {s['id']:s for s in protocol['stages']}
    comps={} if protocol is None else {c['id']:c for c in protocol['comparisons']}
    experiments={r['experiment_id'] for s in stages.values() for r in s['cells']}|{r['experiment_id'] for r in comps.values()}
    out=[]
    for row in rows:
        ce.keys(row,['objection_index','kind','response','protocol_claim_ids','protocol_stage_ids','required_experiment_ids'])
        index=row['objection_index']
        if type(index) is not int or not 0<=index<len(rows) or index in seen:raise ValueError('distinct exact objection index required')
        seen.add(index);integrity._text(row['response'])
        if row['kind'] not in {'editorial','citation','empirical','core-method'}:raise ValueError('typed manuscript action required')
        _ids(row['protocol_claim_ids'],'affected protocol claims',allowed=claims)
        _ids(row['protocol_stage_ids'],'affected protocol stages',allowed=stages)
        _ids(row['required_experiment_ids'],'fresh objection experiments',allowed=experiments)
        if row['kind'] in {'editorial','citation'}:
            if any(row[k] for k in ('protocol_claim_ids','protocol_stage_ids','required_experiment_ids')):
                raise ValueError('editorial/citation preparation cannot silently change scientific stages')
        else:
            if not row['protocol_claim_ids']:raise ValueError('material action needs actual affected protocol claims')
            permitted={s for c in row['protocol_claim_ids'] for s in claims[c]['stage_ids']}|{
                comps[i][k] for c in row['protocol_claim_ids'] for i in claims[c]['comparison_ids'] for k in ('left_stage','right_stage')}
            if row['kind']=='core-method':
                # The declared claim/comparison, not a chosen favorable stage,
                # determines its connected baseline and ablation population.
                changed=True
                while changed:
                    before=set(permitted)
                    for identity in list(permitted):
                        stage=stages[identity]
                        permitted.update(stage.get('requires_stages',[]))
                        permitted.update(comps[r['comparison_id']][k] for r in stage.get('requires',[]) for k in ('left_stage','right_stage'))
                    candidates={stages[s]['candidate'] for s in permitted}
                    for stage in stages.values():
                        if stage['ablation'] is not None and stage['ablation']['parent_candidate'] in candidates:candidates.add(stage['candidate'])
                    permitted.update(s['id'] for s in stages.values() if s['candidate'] in candidates and s['purpose'] in {'baseline','full','ablation'})
                    changed=before!=permitted
            if not set(row['protocol_stage_ids'])<=permitted:raise ValueError('foreign affected scientific stage')
            if row['kind']=='empirical' and not row['required_experiment_ids']:raise ValueError('empirical objection requires a fresh ordinary observation')
            if row['kind']=='core-method':
                if not row['protocol_stage_ids']:raise ValueError('core method needs actual full stage dependencies')
                # All original baseline/full/ablation stages of the implicated
                # candidate family are requalified, not an advantageous subset.
                whole={s for s in permitted if stages[s]['purpose'] in {'baseline','full','ablation'}}
                if not whole<=set(row['protocol_stage_ids']):raise ValueError('core change must retain full baseline/ablation reexecution population')
        out.append({**deepcopy(row),'affected_manuscript':_objection_dependencies(revision['objections'][index],ir,loaded,_claim_census=claim_census),
            'objection':deepcopy(revision['objections'][index]),'resolution':'unresolved'})
    if [r['objection_index'] for r in out]!=list(range(len(rows))):raise ValueError('ordered complete objection action census required')
    return out


def prepare_actions(revision_pin, actions, out, *, base_dir, campaign):
    """Compile actual objections into existing editorial and research services."""
    from . import research_protocol as rp
    revision,package,loaded,ir,state,consumed=_revision_inputs(revision_pin,base_dir,campaign)
    bound=rp._bound(state);protocol=None if bound is None else bound[0]
    rows=_action_rows(actions,revision,ir,loaded,protocol)
    if state['sha256']!=revision['campaign_state_sha256'] or ce.digest(state['context'])!=revision['campaign_context_sha256']:
        raise ValueError('prepare actions from the actual current criticism epoch before research effects')
    allocation=_revision_allocation(campaign,state,_criticism_identity(package,revision['actual_review_bindings'],base_dir))
    remaining=deepcopy(allocation['budget'])
    if any(remaining[k]-(cycle._usage(state)[k]-allocation['usage'][k])<0 for k in remaining):
        raise ValueError('original campaign allowance exhausted')
    value={'schema_version':1,'kind':'manuscript-objection-action-plan','revision':_canon(revision_pin,base_dir,consumed),
        'campaign':str(Path(campaign).resolve()),'protocol':None if bound is None else _canon(bound[1]['protocol'],state['base_dir'],consumed),
        'actions':rows,'remaining_budget':remaining,'usage_at_prepare':deepcopy(allocation['usage']),'original_task':revision['original_task'],
        'invalidated_writing':['whole successor story/sections/captions','native manuscript build','compiled final CI3'],
        'scientific_acceptance':False,'execution_authorized':False}
    root=mp._fresh(out);pin=integrity._new(root/'action-plan.json',deepcopy(value))
    if cycle._load(campaign)[1]!=state:raise ValueError('campaign changed during action preparation')
    for p in [pin,*consumed.values()]:integrity._dependency(p,base_dir,{})
    return {'action_plan':pin,'unresolved_count':len(rows),'execution_authorized':False,'scientific_acceptance':False}


def verify_actions(action_plan_pin, *, base_dir, campaign):
    from . import research_protocol as rp
    consumed={};pin=_canon(action_plan_pin,base_dir,consumed);plan=_read(pin,base_dir,consumed)
    ce.keys(plan,['schema_version','kind','revision','campaign','protocol','actions','remaining_budget','usage_at_prepare','original_task',
        'invalidated_writing','scientific_acceptance','execution_authorized'])
    if type(plan['schema_version']) is not int or plan['schema_version']!=1 or plan['kind']!='manuscript-objection-action-plan':raise ValueError('typed manuscript action plan required')
    revision,package,loaded,ir,state,inputs=_revision_inputs(plan['revision'],base_dir,campaign);consumed.update(inputs)
    if plan['campaign']!=str(Path(campaign).resolve()) or plan['original_task']!=revision['original_task']:
        raise ValueError('action plan changed original campaign/task')
    protocol=None if plan['protocol'] is None else _read(plan['protocol'],base_dir,consumed)
    if protocol is not None:
        rp.validate(protocol,base_dir=state['base_dir'],state=state,check_sources=False)
        current=rp._bound(state)
        if current is None:raise ValueError('bound scientific protocol required')
        for field in ('candidates','cells','stages','comparisons','claims'):
            now={r['id']:r for r in current[0][field]}
            if any(now.get(r['id'])!=r for r in protocol[field]):raise ValueError('original full protocol obligation changed')
    raw=[{k:r[k] for k in ('objection_index','kind','response','protocol_claim_ids','protocol_stage_ids','required_experiment_ids')} for r in plan['actions']]
    if ce.digest(plan['actions'])!=ce.digest(_action_rows(raw,revision,ir,loaded,protocol)):raise ValueError('action map lost/rebound actual objection or dependencies')
    if (plan['scientific_acceptance'] is not False or plan['execution_authorized'] is not False
            or plan['invalidated_writing']!=['whole successor story/sections/captions','native manuscript build','compiled final CI3']):
        raise ValueError('prepared actions cannot grant review or carry old build authority')
    allocation=_revision_allocation(campaign,state,_criticism_identity(package,revision['actual_review_bindings'],base_dir))
    if _encoded(plan['remaining_budget'])!=_encoded(allocation['budget']):raise ValueError('revision allocation cannot be renewed')
    if _encoded(plan['usage_at_prepare'])!=_encoded(allocation['usage']):raise ValueError('original charged revision baseline required')
    for p in consumed.values():integrity._dependency(p,base_dir,{})
    return {'plan':plan,'pin':pin,'revision':revision,'package':package,'loaded':loaded,'integrity_request':ir,
        'state':state,'allocation':allocation,'input_pins':list(consumed.values())}


def action_context(action_plan_pin, *, base_dir, campaign):
    current=verify_actions(action_plan_pin,base_dir=base_dir,campaign=campaign)
    return {'action_plan':current['pin'],'original_objections':current['revision']['objections'],
        'actions':current['plan']['actions'],'remaining_revision_allocation':current['plan']['remaining_budget'],
        'scientific_acceptance':False},current['input_pins']


def validate_action_meta(action_plan_pin, value, *, base_dir, campaign):
    """Only an actual protocol result may open/resolve material action holds."""
    current=verify_actions(action_plan_pin,base_dir=base_dir,campaign=campaign)
    rows=[r for r in current['plan']['actions'] if r['kind'] in {'empirical','core-method'}]
    if not rows:raise ValueError('editorial/citation actions need a writer, not a scientific meta call')
    claims={i for r in rows for i in r['protocol_claim_ids']};stages={i for r in rows for i in r['protocol_stage_ids']}
    experiments={i for r in rows for i in r['required_experiment_ids']}
    if value['action']=='resolve_objections':
        prior=[e for e in current['state']['events'] if e['kind']=='protocol_meta_review_applied'
            and e.get('manuscript_action_plan')==current['pin'] and e['action']!='resolve_objections']
        if not prior or not {e['revision'] for e in prior}<=set(value['resolves_meta_revisions']):raise ValueError('resolve the actual linked manuscript research actions')
    elif value['action']!=('candidate_revision' if any(r['kind']=='core-method' for r in rows) else 'additional_evidence'):
        raise ValueError('scientific objection cannot become report-only or editorial closure')
    if not claims<=set(value['affected_claim_ids']) or not stages<=set(value['affected_stage_ids']) or not experiments<=set(value['required_experiment_ids']):
        raise ValueError('whole mapped manuscript scientific obligation required')
    return current['pin']


def _action_allowance(current, needed):
    state=current['state'];plan=current['plan'];used=cycle._usage(state)
    if any(needed[k]>min(plan['remaining_budget'][k]-(used[k]-plan['usage_at_prepare'][k]),state['contract']['budget'][k]-used[k]) for k in needed):
        raise ValueError('whole revision/campaign allocation exhausted; no per-action reset')


def prepare_action_meta(action_plan_pin, out, *, base_dir, campaign, **runtime):
    from . import research_protocol as rp
    current=verify_actions(action_plan_pin,base_dir=base_dir,campaign=campaign)
    if not any(r['kind'] in {'empirical','core-method'} for r in current['plan']['actions']):raise ValueError('no scientific meta call for purely editorial actions')
    _action_allowance(current,{'calls':1,'output_tokens':runtime['max_output_tokens'],'wall_seconds':runtime['max_wall_seconds'],'native_attempts':0})
    return rp.prepare_meta_review(campaign,out,manuscript_action_plan=current['pin'],**runtime)


def _material_actions_complete(current):
    from . import research_protocol as rp
    pin=current['pin'];state=current['state'];view=rp.status_state(state)
    material=[r for r in current['plan']['actions'] if r['kind'] in {'empirical','core-method'}]
    if not material:return []
    events=[e for e in state['events'] if e['kind']=='protocol_meta_review_applied' and e.get('manuscript_action_plan')==pin]
    opened=[e for e in events if e['action'] not in {'resolve_objections','report_only'}]
    resolved=[e for e in events if e['action']=='resolve_objections']
    if not opened or not {e['revision'] for e in opened}<={i for e in resolved for i in e['resolves_meta_revisions']}:
        raise ValueError('actual linked fresh scientific replacement resolution required before new writing')
    affected={i for r in material for i in r['protocol_claim_ids']}
    if any(rp._active_holds(state,i) for i in affected):raise ValueError('current scientific manuscript hold remains open')
    for row in material:
        for identity in row['required_experiment_ids']:
            e=next((e for e in state['experiments'] if e['id']==identity),None)
            if e is None:raise ValueError('actual requested observation required')
            cycle._current_evidence(state,e,accepted=True)
        if row['kind']=='core-method' and any(i not in view['replacement_obligations']['stages'] for i in row['protocol_stage_ids']):
            raise ValueError('all changed-method baseline/ablation stages need current full replacements')
    return events


def prepare_successor(action_plan_pin, replacement_request_pin, out, *, base_dir, campaign):
    """Bind current replacement sources into a real ordinary improver request.

    The generated response evidence is retained in the writer's normal full
    source manifest. Preparing/issuing a writer does not close any objection.
    """
    current=verify_actions(action_plan_pin,base_dir=base_dir,campaign=campaign);state=current['state'];events=_material_actions_complete(current)
    consumed={};replacement_request_pin=_canon(replacement_request_pin,base_dir,consumed)
    request=_read(replacement_request_pin,base_dir,consumed);newbase=Path(replacement_request_pin['path']).parent
    before=current['loaded'];old=before['request']
    # Same requested task, account policy, author and immutable venue contract;
    # only actual source/result replacements and the revision binding may vary.
    stable=set(old)-{'quantitative_report','source_manifest','environment','code_manifest','skills','methods','citations','figures','revision','source_review','author_visuals','blinding_sources'}
    if _bound_record({k:request.get(k) for k in stable},newbase)!=_bound_record({k:old[k] for k in stable},before['source_base']):
        raise ValueError('successor changed original task/author/runtime/format/policy')
    feedback=request['revision']
    if feedback is None or _canon(feedback['previous_package'],newbase,{})!=current['revision']['prior_package'] or feedback['feedback_binding'] not in current['revision']['actual_review_bindings']:
        raise ValueError('successor must consume the actual prior package and original send-back')
    loaded=mp._load(request,newbase)
    _campaign({'production':request,'loaded':loaded},campaign)
    for kind in ('methods','citations','figures','evidence'):
        if not set(before[kind])<=set(loaded[kind]):raise ValueError('successor dropped original source/method/figure/citation population')
    oldslots=before['quantitative_report'].get('expected_slots',{})
    newslots=loaded['quantitative_report'].get('expected_slots',{})
    if not oldslots.keys()<=newslots.keys():raise ValueError('successor dropped original quantitative report slots')
    for identity,slot in oldslots.items():
        if ce.digest({k:v for k,v in slot.items() if k!='value'})!=ce.digest({k:v for k,v in newslots[identity].items() if k!='value'}):
            raise ValueError('successor changed original quantity unit/scope/population identity')
    material=any(r['kind'] in {'empirical','core-method'} for r in current['plan']['actions'])
    allowed={k:{i for r in current['plan']['actions'] for i in r['affected_manuscript'][k]} for k in ('method_ids','citation_ids','figure_ids')}
    changed_methods={row['id'] for row in old['methods'] if _method_semantics(row,before['source_base'])!=
        _method_semantics(next(r for r in request['methods'] if r['id']==row['id']),newbase)}
    changed_methods.update(set(loaded['methods'])-set(before['methods']))
    core_methods={i for r in current['plan']['actions'] if r['kind']=='core-method' for i in r['affected_manuscript']['method_ids']}
    if not changed_methods<=core_methods:
        raise ValueError('actual changed method requires mapped core-method full baseline/ablation reexecution')
    for field,key in [('methods','method_ids'),('citations','citation_ids'),('figures','figure_ids')]:
        for row in old[field]:
            after=next(r for r in request[field] if r['id']==row['id'])
            if (not material and field=='methods') or row['id'] not in allowed[key]:
                if _bound_record(row,before['source_base'])!=_bound_record(after,newbase):raise ValueError('unaffected scientific source changed')
    if not material and _canon(old['quantitative_report'],before['source_base'],{})!=_canon(request['quantitative_report'],newbase,{}):
        raise ValueError('editorial/citation action cannot replace empirical quantities')
    if material:
        # Every changed method operation must carry actual current ordinary
        # execution, not just new code text or a caller's declared status.
        from . import research_protocol as rp
        bound=rp._bound(current['state']);stage_ids={i for e in events if e['action']=='resolve_objections' for i in e['replacement_stage_ids']}
        experiment_ids={r['experiment_id'] for s in bound[0]['stages'] if s['id'] in stage_ids for r in s['cells']}|{i for r in current['plan']['actions'] for i in r['required_experiment_ids']}
        evidence=[e for e in current['state']['experiments'] if e['id'] in experiment_ids]
        for e in evidence:cycle._current_evidence(current['state'],e,accepted=True)
        actual_receipts={(str(integrity._artifact_path(e['observation']['receipt'],state['base_dir'])),e['observation']['receipt']['sha256']) for e in evidence}
        required_methods=core_methods|changed_methods
        for mid in required_methods:
            for op in loaded['methods'][mid]['presented_operations']:
                proof=op['execution_evidence']
                if proof['state']!='current_successful_stage' or (str(integrity._artifact_path(op['execution']['receipt'],newbase)),op['execution']['receipt']['sha256']) not in actual_receipts:
                    raise ValueError('changed method operation lacks the actual linked replacement observation')
    # Prospective writer is still charged by the original campaign Graph.
    remaining={k:state['contract']['budget'][k]-cycle._usage(state)[k] for k in state['contract']['budget']}
    needed={'calls':1,'output_tokens':request['runtime']['max_output_tokens'],'wall_seconds':request['runtime']['max_wall_seconds'],'native_attempts':0}
    _action_allowance(current,needed)
    response={'schema_version':1,'kind':'manuscript-action-response','action_plan':current['pin'],
        'prior_package':current['revision']['prior_package'],'replacement_request':replacement_request_pin,
        'actual_protocol_events':deepcopy(events),'actions':deepcopy(current['plan']['actions']),
        'objections_closed':False,'new_independent_review_required':True,'scientific_acceptance':False}
    root=mp._fresh(out);response_pin=integrity._new(root/'response-lineage.json',deepcopy(response))
    manifest=deepcopy(loaded['documents']['source_manifest']);identity='manuscript-response-'+response_pin['sha256'][:16]
    if identity in loaded['evidence']:raise ValueError('response lineage identity collision')
    manifest['evidence'].append({'id':identity,'description':'Actual original objections, action map and replacement lineage; no scientific acceptance',
        'located':{'artifact':response_pin,'format':'json','location':'','value':deepcopy(response)}})
    final=deepcopy(_bound_record(request,newbase))
    for method in final['methods']:
        for op in method['operations']:
            if op['execution'] is not None:
                rd=Path(op['execution']['rundir']);op['execution']['rundir']=str(rd if rd.is_absolute() else newbase/rd)
    manifest=_bound_record(manifest,newbase)
    final['source_manifest']=integrity._new(root/'source-manifest.json',manifest)
    finalpin=integrity._new(root/'production-request.json',final)
    writer=mp.prepare_writer(final,root/'writer',base_dir=root,campaign=campaign)
    state=_register_action_graph(current['pin'],writer['graph'],writer['spec'],base_dir=base_dir,campaign=campaign,kind='writer')
    handoff={'schema_version':1,'kind':'manuscript-action-successor','action_plan':current['pin'],'response':response_pin,
        'production_request':writer['request'],'writer_binding':mp._pin(root/'writer/binding.json'),
        'response_evidence_id':identity,'objections_closed':False,'scientific_acceptance':False,'execution_authorized':False}
    handoff_pin=integrity._new(root/'successor.json',deepcopy(handoff))
    if cycle._load(campaign)[1]!=state:raise ValueError('campaign changed during successor preparation')
    for p in [*consumed.values(),*current['input_pins'],response_pin,finalpin,handoff_pin,writer['request'],writer['presentation'],handoff['writer_binding']]:integrity._dependency(p,base_dir,{})
    return {'successor':handoff_pin,'writer':writer,'objections_closed':False,'execution_authorized':False}


def resolve_actions(successor_pin, package_pin, review_bindings, out, *, base_dir, campaign):
    """Read fresh actual independent review; no author/self-issued closure."""
    successor=_read(successor_pin,base_dir);ce.keys(successor,['schema_version','kind','action_plan','response','production_request','writer_binding',
        'response_evidence_id','objections_closed','scientific_acceptance','execution_authorized'])
    if (type(successor['schema_version']) is not int or successor['schema_version']!=1
            or successor['kind']!='manuscript-action-successor' or successor['objections_closed'] is not False
            or successor['scientific_acceptance'] is not False or successor['execution_authorized'] is not False):
        raise ValueError('prepared action successor required')
    current=verify_actions(successor['action_plan'],base_dir=base_dir,campaign=campaign);events=_material_actions_complete(current)
    response=_read(successor['response'],base_dir)
    if (response['action_plan']!=current['pin'] or ce.digest(response['actual_protocol_events'])!=ce.digest(events)
            or ce.digest(response['actions'])!=ce.digest(current['plan']['actions']) or response['objections_closed'] is not False):
        raise ValueError('current complete action response lineage required')
    package=_read(package_pin,base_dir);mp.verify_author(package,base_dir=base_dir)
    if (_canon(package['author_binding'],base_dir,{})!=_canon(successor['writer_binding'],base_dir,{})
            or _canon(package['production_request'],base_dir,{})!=_canon(successor['production_request'],base_dir,{})):
        raise ValueError('replacement manuscript is not the exact prepared ordinary writer')
    author=_read(package['author_binding'],base_dir);loaded=mp._load(_read(author['request'],base_dir),author['base_dir'])
    _campaign({'production':loaded['request'],'loaded':loaded},campaign)
    row=loaded['evidence'].get(successor['response_evidence_id'])
    if row is None or row['located']!={'artifact':successor['response'],'format':'json','location':'','value':response}:
        raise ValueError('actual new writer must consume the whole action response evidence')
    request=_read(package['integrity_request'],base_dir);assessment=integrity.assess(request,review_bindings,base_dir=package['source_base'])
    if not assessment['scoped_integrity_review_complete']:raise ValueError('fresh actual complete independent integrity review required before objection closure')
    pins=integrity.assessment_pins(request,review_bindings,base_dir=package['source_base'])
    value={'schema_version':1,'kind':'manuscript-action-resolution','successor':_canon(successor_pin,base_dir,{}),
        'action_plan':current['pin'],'prior_package':current['revision']['prior_package'],'replacement_package':_canon(package_pin,base_dir,{}),
        'actual_review_bindings':deepcopy(review_bindings),'actual_review_pins':pins,
        'resolved_objection_indices':[r['objection_index'] for r in current['plan']['actions']],
        'scope':'Current manuscript integrity response only; native build, compiled CI3 and whole parent completion remain required',
        'scientific_acceptance':False,'parent_task_accepted':False}
    root=mp._fresh(out);pin=integrity._new(root/'action-resolution.json',deepcopy(value))
    for p in [pin,*pins,*current['input_pins']]:integrity._dependency(p,base_dir,{})
    if cycle._load(campaign)[1]!=current['state']:raise ValueError('campaign changed during action resolution')
    mp.verify_author(package,base_dir=base_dir)
    return {'resolution':pin,'resolved_objection_count':len(value['resolved_objection_indices']),'scientific_acceptance':False,'parent_task_accepted':False}
