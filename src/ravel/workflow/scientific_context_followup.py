"""Finite pages from an already role-projected packet; no model or review authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from . import review_context, execution


def policy(reworks, selections):
    if type(reworks) is not int or not 0 <= reworks <= 8:
        raise ValueError('finite context reworks must be predeclared in 0..8')
    if selections is None: selections=[]
    if type(selections) is not list or len(selections)>32:
        raise ValueError('at most 32 explicit context page selections per presentation')
    return {'schema_version':1,'revision':0,'max_reworks':reworks,
            'max_pages':32*(reworks+1),'max_source_bytes':65536*32*(reworks+1),
            'used_pages':0,'used_source_bytes':0,'selections':deepcopy(selections),
            'presented_pages':[],'predecessor':None,'max_host_request_bytes':2_000_000}


def pages(packet, manifest_sha, selections):
    if type(selections) is not list or len(selections)>32:
        raise ValueError('at most 32 exact requested context pages')
    out=[]; seen=set()
    for s in selections:
        if type(s) is not dict or s.get('kind') not in {'artifact','index'}:
            raise ValueError('closed artifact or index selection required')
        s=deepcopy(s)
        if set(s)=={'kind','artifact_id','section','offset','max_bytes','query'}:
            unused=('section','query') if s['kind']=='artifact' else ('artifact_id',)
            if any(s[k] is not None for k in unused):raise ValueError('unused page selection fields must be null')
            for k in unused:del s[k]
        if s['kind']=='artifact':
            if set(s)!={'kind','artifact_id','offset','max_bytes'}:
                raise ValueError('closed exact artifact page selection required')
            v=review_context.read_artifact_page(packet,s['artifact_id'],expected_manifest_sha256=manifest_sha,
                                              offset=s['offset'],max_bytes=s['max_bytes'])
            size=v['bytes']
        else:
            if set(s)!={'kind','section','offset','max_bytes','query'}:
                raise ValueError('closed exact index page selection required')
            v=review_context.read_index_page(packet,expected_manifest_sha256=manifest_sha,
                        section=s['section'],offset=s['offset'],max_bytes=s['max_bytes'],query=s['query'])
            size=len(json.dumps(v['entries'],sort_keys=True).encode())
        k=execution.digest(s)
        if k in seen:raise ValueError('duplicate context page selection')
        seen.add(k)
        out.append({'selection':deepcopy(s),'payload':v,'source_bytes':size,
                    'source_packet_manifest_sha256':manifest_sha,'content_credit':s['kind']=='artifact'})
    return out


def add_pages(packet, manifest, budget, selected, add):
    if budget['used_pages']+len(selected)>budget['max_pages']:
        raise ValueError('original cumulative context selection budget exhausted')
    amount=sum(v['source_bytes'] for v in selected)
    if budget['used_source_bytes']+amount>budget['max_source_bytes']:
        raise ValueError('original cumulative selected source-byte budget exhausted')
    prior={execution.digest(v['selection']) for v in budget['presented_pages']}
    for v in selected:
        if execution.digest(v['selection']) in prior:raise ValueError('context selection already presented')
        identity='anchor_context_page'+str(len(budget['presented_pages'])).zfill(4)
        sha=add(packet,manifest,identity,v)
        budget['presented_pages'].append({'id':identity,'sha256':sha,'selection':v['selection'],
                                        'source_bytes':v['source_bytes'],'content_credit':v['content_credit']})
    budget['used_pages']+=len(selected);budget['used_source_bytes']+=amount


def _explicit_presentation(isolation, index, required, bound_inputs=()):
    """Opt-in content credit uses an actual Host observation, never inline intent.

    The Host also records the node's own bound input artifacts as presented;
    ``bound_inputs`` admits exactly those digests beside the packet's subjects.
    """
    from . import agent_graph as graph
    observation=isolation.get('evidence_presentation') if type(isolation) is dict else None
    if (type(observation) is not dict or set(observation)!={'manifest_sha256','context_sha256','presented_subject_sha256s','presentation','deferred_content_read'}
            or observation.get('manifest_sha256')!=index.manifest['sha256']
            or type(observation.get('context_sha256')) is not str or not graph.SHA.fullmatch(observation['context_sha256'])
            or observation.get('deferred_content_read') is not False):
        raise ValueError('explicit well-formed current Host evidence_presentation required')
    actual=observation['presented_subject_sha256s'];presentation=observation['presentation']
    if (type(actual) is not list or any(type(v) is not str or not graph.SHA.fullmatch(v) for v in actual)
            or len(set(actual))!=len(actual) or type(presentation) is not dict
            or type(presentation.get('schema_version')) is not int or presentation.get('schema_version')!=1
            or presentation.get('kind')!='bounded_indexed_role_evidence'
            or presentation.get('all_indexed_bytes_retained') is not True
            or presentation.get('omissions_preserved_in_manifest') is not True
            or presentation.get('all_content_read_by_model') is not False):
        raise ValueError('explicit well-formed current Host evidence_presentation required')
    inline=presentation.get('inline_ids')
    if (type(inline) is not list or any(type(v) is not str or v not in index.entries for v in inline)
            or len(set(inline))!=len(inline)):
        raise ValueError('explicit well-formed current Host evidence_presentation required')
    subjects={v['sha256'] for v in index.entries.values()}|{v['source_sha256'] for v in index.entries.values() if v.get('source_sha256')}
    if not set(actual)<=subjects|set(bound_inputs) or not required<=set(actual):
        raise ValueError('prior/latest mandatory core and all selected pages must actually be presented')
    if not required<={index.entries[v]['sha256'] for v in inline}:
        raise ValueError('mandatory core and selected pages lack explicit inline presentation')
    return set(actual)


def verify_presentation(contract, receipt, value, packet):
    from . import scientific_judgment as judgment
    from collections import Counter
    budget=contract['context_read']
    initial=judgment._read_pin(budget['initial_action_request'])
    if set(budget)!=set(policy(budget['max_reworks'],[]))|{'initial_action_request','origin_manifest'}:
        raise ValueError('closed finite context allowance required')
    if any(type(budget[k]) is not int or budget[k]<0 for k in ('revision','max_reworks','max_pages','max_source_bytes','used_pages','used_source_bytes','max_host_request_bytes')):
        raise ValueError('literal nonnegative finite context accounting required')
    immutable={k:v for k,v in contract.items() if k not in {'context_read','core_sha256'}}
    if immutable!={k:v for k,v in initial.items() if k not in {'context_read','core_sha256'}}:
        raise ValueError('context followup cannot change scientific scope, actor, cycle or action')
    for k in ('max_reworks','max_pages','max_source_bytes','max_host_request_bytes'):
        if budget[k]!=initial['context_read'][k]:raise ValueError('original context allowance changed')
    if (not 0<=budget['revision']<=budget['max_reworks']
            or budget['used_pages']!=len(budget['presented_pages'])
            or budget['used_pages']>budget['max_pages']
            or budget['used_source_bytes']!=sum(v['source_bytes'] for v in budget['presented_pages'])
            or budget['used_source_bytes']>budget['max_source_bytes']):
        raise ValueError('cumulative context-read accounting changed')
    origin=judgment._read_pin(budget['origin_manifest'])
    # The original full projected manifest is immutable; wrappers never authorize
    # reading the unprojected run or a peer role's private packet.
    if execution.digest({k:v for k,v in origin.items() if k!='sha256'})!=origin['sha256']:
        raise ValueError('original projected context census changed')
    index=review_context._PacketIndex(packet,receipt['context_manifest_sha256'])
    preserved=Counter(a['sha256'] for a in index.manifest['artifacts'])
    original=Counter(a['sha256'] for a in origin['artifacts'])
    if original-preserved:
        raise ValueError('context continuation dropped original projected evidence')
    contents={identity:index.read(entry) for identity,entry in index.entries.items()}
    required={v['sha256'] for v in budget['presented_pages']}
    required.add(contract['core_sha256'])
    actual=_explicit_presentation(receipt.get('isolation'),index,required)
    if type(receipt.get('presented_subject_sha256s')) is not list or actual!=set(receipt['presented_subject_sha256s']):
        raise ValueError('receipt presentation differs from explicit current Host observation')
    index.finish()
    allowed={v['id']:v['sha256'] for v in budget['presented_pages'] if v['content_credit']}
    allowed['anchor_context_core']=contract['core_sha256']
    if value['kind']=='scientific_review' and not value['citations']:
        raise ValueError('current context review requires located presented-content citations')
    for citation in value['citations']:
        if (type(citation) is not dict or set(citation)!={'artifact_id','sha256','location'}
                or allowed.get(citation['artifact_id'])!=citation['sha256']
                or type(citation['location']) is not str or not citation['location'].strip()):
            raise ValueError('context citation must refer to actually presented scientific core/artifact content')
        from .decision_case import pointer
        pointer(review_context._strict_json_bytes(contents[citation['artifact_id']]),citation['location'])


def preflight(spec, graph_root):
    from . import agent_host, agent_graph
    node=spec['nodes'][0]
    host=agent_host.AgentHost.from_config({'type':'responses','endpoint':'https://example.invalid/v1/responses',
                                        'max_request_bytes':2_000_000})
    _, state=agent_graph._load(Path(graph_root))
    state=deepcopy(state);state['nodes'][node['id']]['attempt_id']='0'*32
    prepared=host.prepare_model_context(node,agent_graph._request(spec,state,node,'0'*64))
    packet=prepared['context']['review_packet']
    ids=(set(packet['presentation']['inline_ids']) if 'presentation' in packet else
         {v['id'] for v in packet['artifacts']})
    manifest=review_context.verify_packet(node['packet']['path'],expected_manifest_sha256=node['packet']['manifest_sha256'])
    required={a['id'] for a in manifest['artifacts'] if a['id'].startswith('anchor_context_')}
    if not required<=ids:raise ValueError('required context pages/core exceed actual Host presentation budget')
    parameters=prepared['parameters']
    context=prepared['context']
    body={'model':parameters['model'],'reasoning':{'effort':parameters['reasoning_effort']},
          'instructions':'Return only public JSON claims, evidence and concise public rationales. Do not return private reasoning traces.\n'+parameters['instructions'],
          'input':[{'role':'user','content':agent_host._json_bytes(context).decode()}],
          'max_output_tokens':parameters['max_output_tokens'],'store':False,'stream':False,'tools':[],
          'text':{'format':{'type':'json_schema','name':'public_record','strict':True,
                           'schema':agent_host._responses_output_schema(parameters['output_schema'])}}}
    if body['text']['format']['schema'] is not parameters['output_schema']:
        body['instructions'] += '\nThe wire format wraps the entire requested public JSON record in exactly one public_record field; preserve all original conditional constraints inside it.'
    if len(agent_host._json_bytes(body))>host.max_request:
        raise ValueError('serialized current Responses context exceeds predeclared Host byte bound')
    return {'presented_ids':sorted(ids),'serialized_request_bytes':len(agent_host._json_bytes(body)),
            'maximum':host.max_request,'model_calls':0}


def _prior_receipt(root, spec, state, node, saved, subject, index, contents):
    """Replay the existing role receipt law against the retained exact checkpoint."""
    from . import agent_graph as g
    from .research_presentation import document
    result=saved['result'];transport=result.get('transport',{});isolation=result.get('isolation',{})
    if state['cancelled'] or state['nodes'][node['id']]['status']!='completed':
        raise ValueError('current completed uncancelled nonvoting predecessor required')
    if g._request(spec,state,node,saved['host_sha256'])!=saved['request']:
        raise ValueError('context request belongs to a superseded Graph/node/generation')
    required={subject}
    if index.manifest.get('kind')=='sfitter_designer_source_packet_v1':
        required.add(index.entries['public_case']['sha256'])
        required.update(index.entries['selected_page'+str(i)]['sha256'] for i in range(len(index.manifest['selections'])))
    else:
        contract=review_context._strict_json_bytes(contents['judgment_request'])
        if index.entries['anchor_context_core']['sha256']!=contract['core_sha256']:
            raise ValueError('prior core differs from exact scientific action')
        required.add(contract['core_sha256'])
        for page in contract['context_read']['presented_pages']:
            if index.entries[page['id']]['sha256']!=page['sha256']:
                raise ValueError('prior selected page differs from retained scientific request')
            required.add(page['sha256'])
    presented=_explicit_presentation(isolation,index,required,{pin['sha256'] for pin in node['inputs']})
    accounted=[]
    for ref in saved.get('call_receipts',[]):
        path=Path(root)/'calls'/(ref['call_id']+'.json')
        from .research_cycle import _pin
        call=document(_pin(path),root,8*1024**2)
        if g.digest(call)!=ref['sha256'] or state['calls'].get(ref['call_id'],{}).get('receipt_sha256')!=ref['sha256']:
            raise ValueError('predecessor model-call receipt changed')
        if call['kind']=='model' and call['status']=='completed':accounted.append(ref)
    if (not accounted or result.get('kind')!='model_result' or subject not in presented
            or transport.get('request_id')!=saved['request']['request_id']):
        raise ValueError('actual presented accounted context request required')
    mode=transport.get('execution_mode','unestablished')
    observation=('host_attested_external' if mode=='host_mediated_external' else 'remote_transport_observed' if mode in {'responses_http','provider_http'} else 'local_transport_observed' if mode=='provider_http_local' else 'control_only' if mode=='responses_http_loopback_control' else 'unestablished')
    receipt={'schema_version':1,'kind':'agent_model_receipt','node_id':node['id'],'role':node['role'],
        'subject_sha256':subject,'exact_subject_presented':True,'presented_subject_sha256s':sorted(presented),
        'context_manifest_sha256':node['packet']['manifest_sha256'],'request_id':transport['request_id'],
        'deferred_content_read':False,
        'receipt_sha256':state['nodes'][node['id']]['result']['sha256'],'host_sha256':saved['host_sha256'],
        'transport':transport,'isolation':isolation,'execution_observation':observation,'public_value':result['value'],
        'public_value_sha256':g.digest(result['value']),'context_transport_separated':bool(isolation.get('fresh_request') and isolation.get('parent_transcript_supplied') is False and node['packet']),
        'actor_identity_authenticated':False,'scientific_independence_proven':False,'physics_validated':False,'execution_authorized':False,
        'limitations':[g.LIMITATION,'Transport custody does not establish the truth of a review judgment.']}
    # The same computed attestation and session fields agent_graph.role_receipt adds.
    receipt['attestation'],receipt['session']=g._receipt_attestation(root,transport,observation,isolation)
    if mode=='transport_attested_cli':
        observation='transport_attested_cli' if receipt['attestation']=='transport_attested' else 'unestablished'
        receipt['execution_observation']=observation
    g._require_declared_instructions(root, isolation)
    if observation=='unestablished' or not receipt['context_transport_separated']:
        raise ValueError('nonvoting request has no fresh separated observed transport')
    return receipt


def authorize_revision(graph_root, before, after, checkpoint, predecessor_pin):
    """Source-defined nonvoting request and exact pages; no caller authority flag."""
    from . import research_cycle as cycle, agent_graph as graph, agent_host, scientific_judgment as judgment
    from .research_presentation import document
    from collections import Counter
    node_id=cycle._context_revision(before,after)
    old=next(n for n in before['nodes'] if n['id']==node_id);new=next(n for n in after['nodes'] if n['id']==node_id)
    ref=checkpoint['nodes'][node_id]['result']
    if ref is None or cycle._pin(Path(graph_root)/ref['path'])!=predecessor_pin:
        raise ValueError('exact retained actual context predecessor required')
    saved=document(predecessor_pin,graph_root,8*1024**2)
    if graph.digest(saved)!=ref['sha256'] or graph.digest(saved['result'])!=ref['result_sha256']:
        raise ValueError('context predecessor result differs from retained Graph checkpoint')
    agent_host.validate_public_result(saved['result']['value'],old['parameters']['output_schema'])
    value=saved['result']['value']
    a=review_context._PacketIndex(old['packet']['path'],old['packet']['manifest_sha256'])
    b=review_context._PacketIndex(new['packet']['path'],new['packet']['manifest_sha256'])
    ar={k:a.read(v) for k,v in a.entries.items()};br={k:b.read(v) for k,v in b.entries.items()}
    if value.get('kind')=='scientific_context_request':
        if (value.get('schema_version')!=2 or any(value.get(k) is not None for k in ('verdict','claim_scope','proposal','proposal_verdict'))
                or value.get('findings')!=[] or value.get('closes')!=[] or set(value.get('context_request',{}))!={'selections'}):
            raise ValueError('actual source-defined nonvoting scientific page request required')
        selections=value['context_request']['selections']
        if not selections:raise ValueError('actual finite page selections required')
        old_contract=review_context._strict_json_bytes(ar['judgment_request'])
        new_contract=review_context._strict_json_bytes(br['judgment_request'])
        receipt=_prior_receipt(graph_root,before,checkpoint,old,saved,a.entries['judgment_request']['sha256'],a,ar)
        if value['subject_sha256']!=a.entries['judgment_request']['sha256']:
            raise ValueError('context request subject differs from actual prior action')
        if {k:v for k,v in old_contract.items() if k not in {'context_read','core_sha256'}}!={k:v for k,v in new_contract.items() if k not in {'context_read','core_sha256'}}:
            raise ValueError('new context replaced original actor/case/anchors/cycle/source/action')
        before_budget=old_contract['context_read'];budget=deepcopy(before_budget)
        budget['revision']+=1
        if budget['revision']>budget['max_reworks']:raise ValueError('original context-read rework allowance exhausted')
        selected=pages(old['packet']['path'],old['packet']['manifest_sha256'],selections)
        expected_pages=[]
        seen={execution.digest(p['selection']) for p in budget['presented_pages']}
        for page in selected:
            if execution.digest(page['selection']) in seen:raise ValueError('context page already presented')
            seen.add(execution.digest(page['selection']))
            identity='anchor_context_page'+str(len(budget['presented_pages'])).zfill(4)
            raw=(json.dumps(page,indent=2,allow_nan=False)+'\n').encode()
            sha=hashlib.sha256(raw).hexdigest()
            if br.get(identity)!=raw:raise ValueError('new page differs from exact requested projected source bytes/range')
            expected_pages.append(raw)
            budget['presented_pages'].append({'id':identity,'sha256':sha,'selection':page['selection'],'source_bytes':page['source_bytes'],'content_credit':page['content_credit']})
        budget['used_pages']+=len(selected);budget['used_source_bytes']+=sum(p['source_bytes'] for p in selected)
        if budget['used_pages']>budget['max_pages'] or budget['used_source_bytes']>budget['max_source_bytes']:
            raise ValueError('original cumulative page/source-byte allowance exhausted')
        actual_budget=new_contract['context_read'];pred=actual_budget['predecessor']
        original_binding={'schema_version':1,'request':{'path':a.entries['judgment_request']['source_path'],'sha256':a.entries['judgment_request']['sha256']},
            'graph_root':str(graph_root),'node_id':node_id,'context_manifest_sha256':old['packet']['manifest_sha256'],'subject_sha256':a.entries['judgment_request']['sha256']}
        if (judgment._read_pin(pred['binding'])!=original_binding or pred['result']!=predecessor_pin or pred['generation']!=checkpoint['nodes'][node_id]['generation']):
            raise ValueError('new context budget does not bind exact previous action/result/generation')
        budget['predecessor']=deepcopy(pred)
        if actual_budget!=budget:raise ValueError('context-read accounting is not exact predecessor plus requested pages')
        core=review_context._strict_json_bytes(br['anchor_context_core'])
        expected_core={'kind':'ordinary_scientific_role_context_core','current_action':{k:deepcopy(v) for k,v in new_contract.items() if k not in {'context_read','core_sha256'}},
            'original_context_limits':{k:budget[k] for k in ('max_reworks','max_pages','max_source_bytes')},
            'original_projected_population':budget['origin_manifest'],'prior_actual_nonvoting_request':value,'prior_receipt':receipt,
            'selected_content_disclosure':'Only current core and authenticated selected pages are mandatory content; inventory custody is not all-content reading.'}
        if core!=expected_core or new_contract['core_sha256']!=b.entries['anchor_context_core']['sha256']:
            raise ValueError('new scientific core changed the actual predecessor or scientific action')
        expected=Counter(hashlib.sha256(raw).hexdigest() for raw in ar.values())
        expected.update(hashlib.sha256(raw).hexdigest() for raw in expected_pages)
        expected.update([b.entries['anchor_context_core']['sha256'],b.entries['judgment_request']['sha256']])
        if expected!=Counter(e['sha256'] for e in b.entries.values()):
            raise ValueError('context revision changed/dropped/added unauthorized projected evidence')
        if {k:v for k,v in a.manifest.items() if k not in {'artifacts','sha256'}}!={k:v for k,v in b.manifest.items() if k not in {'artifacts','sha256'}}:
            raise ValueError('context revision changed original role/cycle/projected manifest')
        if new['parameters']['instructions']!=old['parameters']['instructions'].replace(a.entries['judgment_request']['sha256'],b.entries['judgment_request']['sha256']):
            raise ValueError('context revision changed instructions beyond exact action subject')
        selected_count=len(selected);source_bytes=sum(p['source_bytes'] for p in selected)
    elif value.get('kind')=='sfitter_conductor_proposal':
        if (value.get('disposition')!='request_context' or value.get('handoff_json')!='' or value.get('documentation_markdown')!=''
                or value.get('production')!=[] or not value.get('findings') or not value.get('context_pages')):
            raise ValueError('actual source-defined nonvoting SFitter context request required')
        if a.manifest.get('kind')!='sfitter_designer_source_packet_v1' or b.manifest.get('kind')!=a.manifest['kind']:
            raise ValueError('source-defined SFitter source packet required')
        # _PacketIndex's source hook reconstructs every selected wrapper from
        # the original captured input source; this is not a caller-provided flag.
        if {k:v for k,v in a.manifest.items() if k not in {'artifacts','sha256','selections'}}!={k:v for k,v in b.manifest.items() if k not in {'artifacts','sha256','selections'}}:
            raise ValueError('SFitter followup changed original context/catalogue/source/role')
        if b.manifest['selections']!=value['context_pages'] or new['parameters']['instructions']!=old['parameters']['instructions']:
            raise ValueError('SFitter revision differs from exact requested pages or instructions')
        base_a={k:v for k,v in ar.items() if not k.startswith('selected_page')};base_b={k:v for k,v in br.items() if not k.startswith('selected_page')}
        if base_a!=base_b:raise ValueError('SFitter followup changed original full input census/core')
        _prior_receipt(graph_root,before,checkpoint,old,saved,a.entries['public_case']['sha256'],a,ar)
        from . import sfitter_source_context
        # Explicit invocation also rejects a missing specialized index hook.
        for index in (a,b):
            capture=sfitter_source_context.packet_capture(index)
            capture.finish()
        core=review_context._strict_json_bytes(ar['public_case'])
        context=core['context']
        if (a.manifest['purpose']!='lead' or old['role']!='designer'
                or value['phase']!=context['phase'] or value['owning_phase']!=context['phase']
                or value['target_sha256']!=graph.digest(context['target'])):
            raise ValueError('SFitter request must retain the exact original phase/target and lead role')
        selected_count=len(value['context_pages']);source_bytes=sum(review_context._strict_json_bytes(br['selected_page'+str(i)])['bytes'] for i in range(selected_count))
    else:
        raise ValueError('Graph revision requires an actual supported nonvoting context request, not a vote or arbitrary packet')
    a.finish();b.finish()
    return {'kind':value['kind'],'actual_request_sha256':execution.digest(value),
        'predecessor_sha256':predecessor_pin['sha256'],'old_packet_sha256':old['packet']['manifest_sha256'],
        'new_packet_sha256':new['packet']['manifest_sha256'],'selected_pages':selected_count,'selected_source_bytes':source_bytes,
        'original_graph_budget':deepcopy(before['budget']),'actor_identity_authenticated':False,'execution_authorized':False}
