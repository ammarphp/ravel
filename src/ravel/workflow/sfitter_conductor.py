"""Source-bound SFitterAgents phase conduction on the existing AgentGraph.

Reuse original lead/phase disciplines and actual consultant returns. Drafts,
documentation and production requests are concrete files, never approval. The
original Claude/Apptainer/SLURM application is a distinct backend.
"""
import copy
import hashlib
from pathlib import Path

from ravel.physics.ma5_saf import Capture
from . import agent_graph as graph, sfitter_workflow as workflow
from .state_io import atomic_json


LEAD_SOURCES = (
    'sfitteragents/prompts/lead-discipline.md',
    'sfitteragents/prompts/sf-discipline.md',
    'sfitteragents/.claude/skills/sf-reinterpret/SKILL.md',
    'sfitteragents/.claude/skills/sf-document/SKILL.md',
    'sfitteragents/.claude/rules/sf-documentation.md',
    'sfitteragents/.claude/rules/sf-tool-fidelity.md',
    'sfitteragents/.claude/rules/ma-outcome-not-evidence.md',
    'sfitteragents/.claude/rules/ma-wiki-as-evidence.md',
)
PRODUCTION_SKILLS = (
    'sfitteragents/.claude/skills/mg-setup/SKILL.md',
    'sfitteragents/.claude/skills/mg-probe/SKILL.md',
    'sfitteragents/.claude/skills/cluster-submission/SKILL.md',
    'sfitteragents/.claude/skills/sf-fit/SKILL.md',
)
LIMITS = (
    'The original skills are scientific workflow context, not permission to '
    'start containers/SLURM/MadGraph/model calls or change memory/configuration. '
    'Every compute request must become an ordinary admitted scientific task. '
    'Native exact polynomial normalization overrides conflicting Taylor prose. '
    'A source draft and its documentation are not reviewer-approved phase '
    'completion; the SFitter domain judgment and ordinary review remain required.'
)


def _json(raw):
    return workflow._strict_document(raw)


def _fresh(value):
    out = Path(value).absolute()
    if '..' in out.parts or out.exists() or out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError('fresh ordinary conductor destination required')
    return out


def _protect(out, *roots):
    if any(root is not None and out.is_relative_to(Path(root)) for root in roots):
        raise ValueError('conductor output must preserve original source/Graph/context directories')


def consultant_graph(request, base, request_pin, *, max_reworks=0, source_packet=None):
    """Retain the ordinary graph's cumulative calls/reworks; no dispatch."""
    workflow.sfitter_native._integer(max_reworks, 'explicit consultant reworks', 0, 16)
    spec = workflow.phase_graph(request, base, request_pin,source_packet=source_packet)
    count = len(spec['nodes'])
    spec['budget'].update(max_reworks=max_reworks, max_calls=count*(1+max_reworks),
                          max_output_tokens=count*(1+max_reworks)*request['model']['max_output_tokens'])
    return graph.validate(spec)


def _consultations(root, request, request_pin, base, capture):
    root = workflow.custody._regular(root, base, directory=True)
    spec, state = graph._load(root)
    if state['cancelled'] or spec['graph_id'] != request['id']+'_'+workflow._resolve(request,base)[1]:
        raise ValueError('consultations belong to another phase or cancelled graph')
    phase = workflow._resolve(request, base)[1]
    expected=consultant_graph(request,base,request_pin,max_reworks=spec['budget']['max_reworks'],
        source_packet=spec['nodes'][0]['packet'])
    if spec!=expected:raise ValueError('whole owning-phase specialist graph differs from current workflow')
    for name, expected in ((graph.SPEC, spec), (graph.STATE, state)):
        _, raw = capture.read(root/name, root)
        if _json(raw) != expected:raise ValueError('consultant checkpoint changed')
    returns = []
    for node in spec['nodes']:
        graph._artifact_checks(node)
        for p in node['inputs']:capture.pin({k:p[k] for k in ('path','sha256')}, base)
        current = state['nodes'][node['id']]
        if current['status'] != 'completed':
            raise ValueError('all specialist returns must be complete; failures remain in the original graph')
        ref = current['result'];document = graph._result(root, ref)
        _, raw = capture.read(root/ref['path'], root)
        if _json(raw) != document:raise ValueError('consultant return changed')
        expected = graph._request(spec,state,node,ref['host_sha256'])
        if document['request'] != expected or current['generation'] != document['request']['generation']:
            raise ValueError('consultant return no longer belongs to current inputs/generation')
        if node['kind'] != 'model' or node['role'] != 'designer' or document['result'].get('kind') != 'model_result':
            raise ValueError('actual ordinary advisory model returns required')
        returns.append({'role':node['id'],'graph_id':spec['graph_id'],
            'result_pin':workflow._pin(root/ref['path']), 'result':document['result'],
            'review_authority':False})
    return returns


def prepare(request_pin, base, output, *, consultations=None):
    """Build the next lead context from original skills and actual artifacts."""
    out = _fresh(output);capture = Capture()
    path, raw = capture.pin(request_pin, base);request = _json(raw)
    capture=workflow._source_capture(request,path.parent,capture)
    for module in (__file__,workflow.__file__):capture.pin(workflow._pin(Path(module)),base)
    docs, phase = workflow._resolve(request,path.parent)
    if phase is None:raise ValueError('card source phases complete; use ordinary native planning and review')
    root, _ = workflow._knowledge(request,path.parent,phase)
    _protect(out,root,workflow.custody._regular(consultations,path.parent,directory=True) if consultations is not None else None)
    pins = workflow.input_pins(request,path.parent)
    for pin in pins:capture.pin(pin,path.parent)
    declared = workflow._known()
    rels = [*LEAD_SOURCES, 'sfitteragents/.claude/skills/'+workflow.SKILLS[phase]+'/SKILL.md']
    if phase in ('sm_template','parameterization'):rels += list(PRODUCTION_SKILLS)
    for rel in dict.fromkeys(rels):
        capture.pin({'path':str(root/rel),'sha256':declared[rel]}, root)
    returns = _consultations(consultations,request,workflow._pin(path),path.parent,capture) if consultations is not None else []
    original = {'request':workflow._pin(path),'phase':phase,'target':request['target'],
        'completed_source_drafts':list(docs),'consultations':returns,
        'consultation_graph':str(workflow.custody._regular(consultations,path.parent,directory=True)) if consultations is not None else None,
        'upstream_commit':workflow.sfitter_native.COMMIT,
        'upstream_skills':list(dict.fromkeys(rels)),
        'next_required_gate':'domain review + current documentation + actual native parser where applicable',
        'execution_authorized':False,'physics_validated':False,'limitations':[LIMITS,workflow.BOUNDARY]}
    if workflow.input_pins(request,path.parent) != pins:raise ValueError('phase source inputs changed')
    capture.finish()
    # Context contains the exact captured skill text, not a reread after validation.
    original['skill_texts']={rel:capture.files[root/rel][1].decode('utf-8') for rel in dict.fromkeys(rels)}
    original['inputs']=[{'path':str(p),'sha256':hashlib.sha256(v[1]).hexdigest()} for p,v in sorted(capture.files.items())]
    out.mkdir(parents=True)
    import json
    written=(json.dumps(original,indent=2,allow_nan=False)+'\n').encode('utf-8')
    atomic_json(out/'context.json', original)
    generated=Capture();generated.read(out/'context.json',out,hashlib.sha256(written).hexdigest())
    capture.finish();generated.finish()
    return {'path':str(out/'context.json'),'sha256':hashlib.sha256(written).hexdigest()}


def _context(context, base, capture, context_path):
    workflow._closed(context,('request','phase','target','completed_source_drafts','consultations',
        'consultation_graph','upstream_commit','upstream_skills','next_required_gate',
        'execution_authorized','physics_validated','limitations','skill_texts','inputs'),'conductor context')
    path,raw=capture.pin(context['request'],base);request=_json(raw)
    capture=workflow._source_capture(request,path.parent,capture)
    for module in (__file__,workflow.__file__):capture.pin(workflow._pin(Path(module)),base)
    docs,phase=workflow._resolve(request,path.parent)
    if (phase is None or context['phase']!=phase or context['target']!=request['target'] or
        context['completed_source_drafts']!=list(docs) or context['upstream_commit']!=workflow.sfitter_native.COMMIT or
        context['execution_authorized'] is not False or context['physics_validated'] is not False or
        context['limitations']!=[LIMITS,workflow.BOUNDARY] or context['next_required_gate']!=
        'domain review + current documentation + actual native parser where applicable'):
        raise ValueError('conductor scientific population/phase/authority differs')
    root,_=workflow._knowledge(request,path.parent,phase)
    for pin in workflow.input_pins(request,path.parent):capture.pin(pin,path.parent)
    rels=[*LEAD_SOURCES,'sfitteragents/.claude/skills/'+workflow.SKILLS[phase]+'/SKILL.md']
    if phase in ('sm_template','parameterization'):rels+=list(PRODUCTION_SKILLS)
    rels=list(dict.fromkeys(rels))
    if context['upstream_skills']!=rels:raise ValueError('whole current original skill population required')
    for rel in rels:capture.pin({'path':str(root/rel),'sha256':workflow._known()[rel]},root)
    if context['skill_texts']!={rel:capture.files[root/rel][1].decode('utf-8') for rel in rels}:
        raise ValueError('conductor skill text differs from original source bytes')
    returns=_consultations(context['consultation_graph'],request,workflow._pin(path),path.parent,capture) if context['consultation_graph'] is not None else []
    if returns!=context['consultations']:raise ValueError('actual consultant returns differ from current graph')
    expected=[{'path':str(p),'sha256':hashlib.sha256(v[1]).hexdigest()} for p,v in sorted(capture.files.items()) if p!=context_path]
    if context['inputs']!=expected:raise ValueError('complete current conductor input population differs')
    return request,path,capture


def proposal_schema(phase, target_sha, catalogue_size=None):
    """Closed lead disposition; JSON handoff text is separately strictly parsed."""
    def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
    string={'type':'string','maxLength':262144}
    schema=obj({'kind':{'type':'string','const':'sfitter_conductor_proposal'},
        'phase':{'type':'string','const':phase}, 'target_sha256':{'type':'string','const':target_sha},
        'disposition':{'type':'string','enum':['source_draft','request_production','send_back','unresolved']},
        'owning_phase':{'type':'string','enum':list(workflow.PHASES)},
        'handoff_json':string,'documentation_markdown':string,
        'findings':{'type':'array','items':{'type':'string','minLength':1,'maxLength':8000},'maxItems':64},
        'production':{'type':'array','maxItems':64,'items':obj({
            'operation':{'type':'string','enum':['measurement_extraction','madgraph_sm','madgraph_scan','native_datacard_roundtrip','native_fit']},
            'reason':{'type':'string','minLength':1,'maxLength':8000},
            'artifact_input_ids':{'type':'array','items':{'type':'string','minLength':1,'maxLength':80},'maxItems':catalogue_size or 128}})},
        'review_approved':{'type':'boolean','const':False},'execution_authorized':{'type':'boolean','const':False}})
    if catalogue_size is not None:
        schema['properties']['disposition']['enum'].append('request_context')
        schema['properties']['context_pages']={'type':'array','maxItems':32,'items':obj({
            'input_id':{'type':'string','minLength':1,'maxLength':80},
            'offset':{'type':'integer','minimum':0},'max_bytes':{'type':'integer','minimum':1,'maximum':65536}})}
        schema['required'].append('context_pages')
    return schema


def lead_graph(context_pin, base, *, graph_id, model, max_wall_seconds, goal_binding=None, packet_pin=None, max_context_reworks=0):
    capture = Capture();path,raw = capture.pin(context_pin,base);context = _json(raw)
    request,_,capture=_context(context,base,capture,path)
    action=workflow.model_action(request['model'])
    workflow.model_action(model)
    if 'adapter' in model and model['adapter']!=action:
        raise ValueError('lead adapter differs from the authenticated workflow model declaration')
    pins = [workflow._pin(path),*context['inputs']]
    workflow.sfitter_native._integer(max_context_reworks,'explicit context reworks',0,16)
    catalogue_size=None
    if packet_pin is not None:
        from . import sfitter_source_context as transport
        raw_node={'packet':packet_pin,'role':'designer','inputs':[{'id':'input0',**workflow._pin(path)}]}
        mapping,_=transport.verified_lead_sources(raw_node,workflow._pin(path),base)
        catalogue_size=len(mapping)-1; pins=[workflow._pin(path)]
    elif len(pins)>128:
        raise ValueError('complete large lead context requires prepare_lead_packet and its exact packet_pin; no truncation permitted')
    elif max_context_reworks:
        raise ValueError('context reworks require explicit source packet')
    instructions = (LIMITS+'\nConduct sf-reinterpret at current phase '+context['phase']+
        '. Reconcile the supplied actual consultant returns; request missing owning-slice evidence rather than invent it. '
        'Return the closed proposal. With an indexed source packet, request_context uses context_pages with original input IDs, offsets and byte limits. It cannot draft a handoff, production or approval. All necessary pages must be selected again in the final stateless call. Source-draft handoff must preserve the entire target population and exact sources. '
        'Keep unresolved/revision binding and route to its owning phase. Production records name actual supplied '
        'artifact input IDs, never guessed outputs. Documentation is a draft provenance bucket, not review clearance. '
        'Do not Taylor-normalize the native exact polynomial or zero unknown supplied terms.')
    spec={'schema_version':1,'graph_id':graph_id,'budget':{'max_nodes':1,'max_calls':1+max_context_reworks,
        'max_output_tokens':(1+max_context_reworks)*model['max_output_tokens'],'max_wall_seconds':max_wall_seconds,'max_reworks':max_context_reworks},
        'nodes':[{'id':'sfitter_lead','kind':'model','role':'designer','depends_on':[],
        'inputs':[{'id':'input'+str(i),**p} for i,p in enumerate(pins)],'packet':packet_pin,'action':action,
        'parameters':{'instructions':instructions,'model':model['name'],'reasoning_effort':model['reasoning_effort'],
            'max_output_tokens':model['max_output_tokens'],
            'output_schema':proposal_schema(context['phase'],graph.digest(context['target']),catalogue_size)},'max_attempts':1}]}
    if goal_binding is not None:
        from . import task_completion
        for pin in task_completion.binding_projection(goal_binding,base_dir=base)['input_pins']:
            capture.read(pin['path'],base,pin['sha256'])
        spec['goal_binding']=copy.deepcopy(goal_binding)
    capture.finish()
    return graph.validate(spec)


def adopt(graph_root, context_pin, base, output):
    """Materialize an actual current lead result; retain send-backs and drafts."""
    out = _fresh(output);capture = Capture();cp, raw = capture.pin(context_pin,base);context = _json(raw)
    request,request_path,capture=_context(context,base,capture,cp)
    root = workflow.custody._regular(graph_root,base,directory=True)
    _protect(out,root,cp.parent,workflow.custody._regular(request['upstream_tree']['root'],request_path.parent,directory=True),context['consultation_graph'])
    spec,state = graph._load(root)
    if state['cancelled'] or len(spec['nodes'])!=1 or spec['nodes'][0]['id']!='sfitter_lead':
        raise ValueError('current complete ordinary lead graph required')
    node=spec['nodes'][0];current=state['nodes'][node['id']]
    for name,expected in ((graph.SPEC,spec),(graph.STATE,state)):
        _,raw=capture.read(root/name,root)
        if _json(raw)!=expected:raise ValueError('lead checkpoint changed')
    if current['status']!='completed':raise ValueError('lead response is not complete')
    ref=current['result'];doc=graph._result(root,ref)
    _,raw=capture.read(root/ref['path'],root)
    if _json(raw)!=doc or doc['request']!=graph._request(spec,state,node,ref['host_sha256']):
        raise ValueError('lead result does not belong to current inputs/generation')
    for p in node['inputs']:capture.pin({k:p[k] for k in ('path','sha256')},base)
    expected=lead_graph(context_pin,base,graph_id=spec['graph_id'],
        model={'name':node['parameters']['model'],'reasoning_effort':node['parameters']['reasoning_effort'],'max_output_tokens':node['parameters']['max_output_tokens']},
        max_wall_seconds=spec['budget']['max_wall_seconds'],goal_binding=spec.get('goal_binding'),
        packet_pin=node['packet'],max_context_reworks=spec['budget']['max_reworks'])
    if expected!=spec:raise ValueError('lead graph differs from original conductor specification')
    if doc['result'].get('kind')!='model_result':raise ValueError('ordinary public model result required')
    from .agent_host import validate_public_result
    proposal=validate_public_result(doc['result']['value'],node['parameters']['output_schema'])
    from . import sfitter_source_context as transport
    available,full_presented=transport.verified_lead_sources(node,workflow._pin(cp),base,model_result=doc['result'])
    if proposal['disposition']=='request_context':
        raise ValueError('context request is unresolved; use followup_context on the same budgeted Graph')
    if proposal.get('context_pages'):
        raise ValueError('only request_context may request byte pages')
    if workflow._resolve(request,request_path.parent)[1]!=context['phase']:
        raise ValueError('phase advanced or changed since lead context')
    next_request=copy.deepcopy(request);handoff=None
    if proposal['disposition']=='source_draft':
        if proposal['owning_phase']!=context['phase'] or not proposal['handoff_json'] or not proposal['documentation_markdown'].strip() or proposal['findings'] or proposal['production']:
            raise ValueError('complete source draft requires its handoff/documentation and no unresolved production/findings')
        handoff=workflow._absolute_pins(_json(proposal['handoff_json']),request_path.parent)
        workflow._handoff(request,handoff,request_path.parent,context['phase'])
        presented={(p['path'],p['sha256']) for p in available.values() if (p['path'],p['sha256']) in full_presented}
        if any((str(workflow.custody._pin(p,request_path.parent)),p['sha256']) not in presented for p in workflow._refs(handoff)):
            raise ValueError('lead handoff claims evidence not actually supplied to the model')
    else:
        if proposal['handoff_json'] or not proposal['findings']:
            raise ValueError('noncomplete disposition must preserve missing/revision findings without handoff')
        if proposal['disposition']=='request_production' and not proposal['production']:
            raise ValueError('production request must state actual operation/inputs')
        if proposal['disposition']=='send_back':
            index=workflow.PHASES.index(proposal['owning_phase'])
            if index>workflow.PHASES.index(context['phase']):raise ValueError('send-back cannot advance to a future phase')
            next_request['handoffs']={p:v for p,v in request['handoffs'].items() if workflow.PHASES.index(p)<index}
    for p in proposal['production']:
        if (not p['artifact_input_ids'] or len(set(p['artifact_input_ids']))!=len(p['artifact_input_ids']) or
            not set(p['artifact_input_ids'])<=set(available)):
            raise ValueError('production must reference unique authentic original source IDs')
    capture.finish();out.mkdir(parents=True)
    generated=Capture()
    def write_json(path,value):
        import json
        raw=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode('utf-8')
        atomic_json(path,value);generated.read(path,out,hashlib.sha256(raw).hexdigest())
    def write_text(path,value):
        raw=value.encode('utf-8');path.write_bytes(raw)
        generated.read(path,out,hashlib.sha256(raw).hexdigest())
    if handoff is not None:
        write_json(out/'phase-handoff.json',handoff)
        next_request=workflow._absolute_pins(request,request_path.parent)
        next_request['upstream_tree']['root']=str(workflow.custody._regular(request['upstream_tree']['root'],request_path.parent,directory=True))
        next_request['handoffs'][context['phase']]=workflow._pin(out/'phase-handoff.json')
        bucket=out/'documentation'/context['phase'];bucket.mkdir(parents=True)
        write_text(bucket/(context['phase']+'.md'),proposal['documentation_markdown'])
        write_json(bucket/'source-artifacts.json',{'sources':context['inputs'],
            'lead_result':workflow._pin(root/ref['path']),'review_approved':False})
    next_request=workflow._absolute_pins(next_request,request_path.parent)
    next_request['upstream_tree']['root']=str(workflow.custody._regular(request['upstream_tree']['root'],request_path.parent,directory=True))
    if handoff is not None and context['phase']=='datacard':workflow.ready_native(next_request,out)
    write_json(out/'workflow-draft.json',next_request)
    write_json(out/'proposal.json',proposal)
    capture.finish();generated.finish()
    receipt={'kind':'sfitter_conductor_adoption','phase':context['phase'],'disposition':proposal['disposition'],
        'owning_phase':proposal['owning_phase'],'workflow_draft':workflow._pin(out/'workflow-draft.json'),
        'lead_result':workflow._pin(root/ref['path']),'review_approved':False,
        'next_required_action':'domain judgment + documentation review; source drafts do not authorize phase completion',
        'production':proposal['production'],'findings':proposal['findings'],
        'execution_authorized':False,'physics_validated':False,'calls_dispatched_by_adoption':0}
    write_json(out/'adoption-receipt.json',receipt)
    capture.finish();generated.finish()
    return receipt


def _domain_protocol():
    try:
        from . import sfitter_review_protocol
    except ImportError as error:
        raise ValueError('Separately reviewed SFitter domain protocol is required; no phase approval is inferred') from error
    return sfitter_review_protocol


def prepare_lead_packet(context_pin, base, output, **options):
    """Complete designer source catalogue; selected pages give bounded access."""
    from . import sfitter_source_context
    return sfitter_source_context.prepare_lead_packet(context_pin,base,output,**options)


def followup_context(graph_root, context_pin, base, output, *, campaign=None):
    """Consume a current page request and revise the same bounded lead Graph.

    A campaign must use its existing charged-revision join. No new graph, call,
    approval or read credit is created by preparing a packet or revising it.
    """
    from . import sfitter_source_context as transport
    out=_fresh(output);capture=Capture();cp,raw=capture.pin(context_pin,base);ctx=_json(raw)
    _,_,capture=_context(ctx,base,capture,cp)
    root=workflow.custody._regular(graph_root,base,directory=True)
    _protect(out,root,cp.parent,ctx['consultation_graph'])
    spec,state=graph._load(root)
    if state['cancelled'] or len(spec['nodes'])!=1:raise ValueError('current uncancelled lead Graph required')
    node=spec['nodes'][0];current=state['nodes'].get('sfitter_lead')
    if node['id']!='sfitter_lead' or current is None or current['status']!='completed' or not node['packet']:
        raise ValueError('current completed indexed lead result required')
    ref=current['result'];doc=graph._result(root,ref)
    capture.read(root/ref['path'],root)
    if doc['request']!=graph._request(spec,state,node,ref['host_sha256']) or doc['result'].get('kind')!='model_result':
        raise ValueError('page request belongs to superseded lead context/generation')
    expected=lead_graph(context_pin,base,graph_id=spec['graph_id'],
        model={'name':node['parameters']['model'],'reasoning_effort':node['parameters']['reasoning_effort'],
               'max_output_tokens':node['parameters']['max_output_tokens']},
        max_wall_seconds=spec['budget']['max_wall_seconds'],goal_binding=spec.get('goal_binding'),
        packet_pin=node['packet'],max_context_reworks=spec['budget']['max_reworks'])
    if expected!=spec:raise ValueError('whole current indexed lead specification required')
    from .agent_host import validate_public_result
    proposal=validate_public_result(doc['result']['value'],node['parameters']['output_schema'])
    transport.verified_lead_sources(node,workflow._pin(cp),base,model_result=doc['result'])
    if (proposal['disposition']!='request_context' or proposal['owning_phase']!=ctx['phase'] or
        proposal['handoff_json'] or proposal['documentation_markdown'] or proposal['production'] or
        not proposal['findings'] or not proposal['context_pages']):
        raise ValueError('only a bounded explicit page request without a draft or authority may revise context')
    if state['reworks']>=spec['budget']['max_reworks']:
        raise ValueError('lead context rework budget exhausted; original result remains unresolved')
    manifest=transport.review_context.verify_packet(node['packet']['path'],expected_manifest_sha256=node['packet']['manifest_sha256'])
    core=next(e for e in manifest['artifacts'] if e['id']=='public_case')
    graph.role_receipt(root,node['id'],expected_subject_sha256=core['sha256'],
        expected_packet_sha256=node['packet']['manifest_sha256'],require_exact_subject=True,allowed_roles={'designer'})
    capture.finish();out.mkdir(parents=True)
    packet=prepare_lead_packet(context_pin,base,out/'packet',selections=proposal['context_pages'],
        max_request_bytes=manifest['max_request_bytes'])
    new=copy.deepcopy(spec);new['nodes'][0]['packet']=packet
    predecessor=workflow._pin(root/ref['path']);predecessor['size']=Path(predecessor['path']).stat().st_size
    reason='SFitter source-page request '+predecessor['sha256']
    from . import research_cycle
    result=research_cycle.revise_graph(campaign,root,new,expected_spec_sha256=graph.digest(spec),
        predecessor_result_pin=predecessor,reason=reason)
    capture.finish()
    receipt={'kind':'sfitter_lead_context_revision','graph_root':str(root),
        'before_spec_sha256':graph.digest(spec),'after_spec_sha256':graph.digest(new),
        'predecessor_result':predecessor,'packet':packet,'context_pages':copy.deepcopy(proposal['context_pages']),
        'findings':copy.deepcopy(proposal['findings']),
        'original_budget':copy.deepcopy(spec['budget']),'campaign':str(Path(campaign).absolute()) if campaign else None,
        'execution_authorized':False,'physics_validated':False,'content_read_by_model':False}
    generated=Capture();payload=(__import__('json').dumps(receipt,indent=2,allow_nan=False)+'\n').encode()
    atomic_json(out/'context-revision.json',receipt)
    generated.read(out/'context-revision.json',out,hashlib.sha256(payload).hexdigest())
    capture.finish();generated.finish()
    return copy.deepcopy(receipt)


def _review_request(adoption_pin, protocol_request_pin, base):
    capture=Capture();_,raw=capture.pin(adoption_pin,base);adoption=_json(raw)
    path,raw=capture.pin(protocol_request_pin,base);request=_json(raw)
    if (adoption.get('kind')!='sfitter_conductor_adoption' or adoption.get('disposition')!='source_draft' or
        adoption.get('review_approved') is not False or adoption.get('execution_authorized') is not False or
        request['stage']!=adoption['phase']):
        raise ValueError('Actual current source draft and matching domain review stage required')
    wp,_=capture.pin(adoption['workflow_draft'],base)
    protocol_workflow,_=capture.pin(request['workflow'],path.parent)
    if wp!=protocol_workflow or adoption['workflow_draft']['sha256']!=request['workflow']['sha256']:
        raise ValueError('Domain review must consume this exact adopted workflow, not another phase/artifact')
    capture.finish()
    return path,request,capture


def _binding_request(binding, path, base, capture):
    workflow._closed(binding,('schema_version','kind','request','report','case','judgment',
        'execution_authorized','physics_validated'),'SFitter domain binding')
    bound,_=capture.pin(binding['request'],base)
    if (binding['schema_version']!=1 or binding['kind']!='sfitter_domain_binding' or
        binding['execution_authorized'] is not False or binding['physics_validated'] is not False or
        bound!=path or binding['request']['sha256']!=workflow._pin(path)['sha256']):
        raise ValueError('Domain judgment binding belongs to another protocol request or authority')


def prepare_role(adoption_pin, protocol_request_pin, base, rundir, output, **options):
    """Delegate genuine review preparation; never manufacture a vote or packet."""
    path,request,capture=_review_request(adoption_pin,protocol_request_pin,base)
    protocol=_domain_protocol();protocol.context(request,path.parent)
    result=protocol.prepare_role(rundir,workflow._pin(path),output,**options)
    _binding_request(result,path,base,capture)
    capture.finish()
    return result


def consume_review(adoption_pin, protocol_request_pin, base, rundir, binding):
    """Only the ordinary domain/judgment consumer decides actual disposition."""
    path,request,capture=_review_request(adoption_pin,protocol_request_pin,base)
    _binding_request(binding,path,base,capture)
    protocol=_domain_protocol();protocol.context(request,path.parent)
    result=protocol.consume(rundir,binding)
    capture.finish()
    return result


def rework_review(adoption_pin, protocol_request_pin, base, rundir, binding, output):
    """Owner's actual send-back route, preserving journal and cumulative budgets."""
    path,request,capture=_review_request(adoption_pin,protocol_request_pin,base)
    _binding_request(binding,path,base,capture)
    protocol=_domain_protocol();protocol.context(request,path.parent)
    result=protocol.rework(rundir,binding,output)
    capture.finish()
    return result


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','packet','lead-graph','followup-context','adopt'))
    p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    p.add_argument('--consultations');p.add_argument('--graph');p.add_argument('--graph-id',default='sfitter_lead')
    p.add_argument('--adapter',choices=sorted(workflow.provider_transport.MODEL_ACTIONS))
    p.add_argument('--model');p.add_argument('--reasoning-effort',default='high');p.add_argument('--max-output-tokens',type=int,default=4096)
    p.add_argument('--max-wall-seconds',type=int,default=600)
    p.add_argument('--packet');p.add_argument('--manifest-sha256');p.add_argument('--selections')
    p.add_argument('--packet-purpose',choices=('lead','specialist','assembly'),default='lead')
    p.add_argument('--max-context-reworks',type=int,default=0);p.add_argument('--campaign')
    a=p.parse_args(argv)
    if bool(a.packet)!=bool(a.manifest_sha256):p.error('--packet and --manifest-sha256 must be supplied together')
    pin=workflow._pin(workflow.custody._regular(a.input,Path.cwd()))
    if a.action=='prepare':prepare(pin,Path.cwd(),a.output,consultations=a.consultations)
    elif a.action=='packet':
        selections=[]
        if a.selections:
            cap=Capture();_,raw=cap.read(a.selections,Path.cwd());selections=_json(raw);cap.finish()
        result=prepare_lead_packet(pin,Path.cwd(),a.output,selections=selections,purpose=a.packet_purpose)
        print(__import__('json').dumps(result,indent=2))
    elif a.action=='followup-context':
        if not a.graph:p.error('followup-context requires current ordinary --graph')
        result=followup_context(a.graph,pin,Path.cwd(),a.output,campaign=a.campaign)
        print(__import__('json').dumps(result,indent=2))
    elif a.action=='adopt':
        if not a.graph:p.error('adopt requires current ordinary --graph')
        adopt(a.graph,pin,Path.cwd(),a.output)
    else:
        if not a.model:p.error('lead-graph requires explicit model declaration')
        out=_fresh(a.output)
        atomic_json(out,lead_graph(pin,Path.cwd(),graph_id=a.graph_id,
            model={'name':a.model,'reasoning_effort':a.reasoning_effort,'max_output_tokens':a.max_output_tokens,
                   **({'adapter':a.adapter} if a.adapter is not None else {})},max_wall_seconds=a.max_wall_seconds,
            packet_pin={'path':a.packet,'manifest_sha256':a.manifest_sha256} if a.packet and a.manifest_sha256 else None,
            max_context_reworks=a.max_context_reworks))
    return 0


if __name__=='__main__':raise SystemExit(main())
