"""Normal research deliverable: accounted author -> full census -> ordinary build.

The original task and evolving current quantity context are inputs, not a manually
written manuscript. Prose comes from a real accounted Graph role. Numerical tables
are composed by the existing report engine; source/figure/claim evidence survives
revisions. Existing independent judgment, visual review and CI3 retain authority.
"""
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from ravel.physics import manuscript_assets
import re
from . import agent_graph, candidate_experiments as ce, report_integrity as integrity
from . import scientific_report, state_io, manuscript_format

SECTIONS = ('title', 'abstract', 'strategy', 'background', 'validation', 'methods',
            'results', 'discovery-sensitivity', 'run2-comparison', 'limitations', 'appendix',
            'authors', 'affiliations', 'data-availability', 'code-availability',
            'acknowledgements', 'funding', 'author-contributions', 'competing-interests',
            'additional-information','extended-data-legends')
PROFILES = manuscript_format.PROFILES
MAX_PARAGRAPHS = 160
MAX_REVISION_ANCESTORS = integrity.MAX_ITEMS
_REVISION_VERIFICATION = ContextVar("manuscript_revision_verification", default=None)


def _pin(path):
    path = integrity._ordinary(path); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _fresh(out):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('fresh versioned manuscript output required')
    out.mkdir(parents=True); return out


def _write(path, raw):
    raw = bytes(raw); path = Path(path)
    if not raw or len(raw) > integrity.MAX_BYTES or path.exists(): raise ValueError('bounded fresh note artifact required')
    expected = {'path':str(path.absolute()), 'sha256':hashlib.sha256(raw).hexdigest(), 'size':len(raw)}
    with path.open('xb') as stream: stream.write(raw)
    integrity._raw(expected, path.parent, {})
    return expected


def _writer_policy(runtime):
    """Prospective accounting policy; unknown measurement is never a token estimate."""
    policy = runtime.get('usage_policy', 'strict_reported')
    if policy not in ('strict_reported', 'reserved_unknown'):
        raise ValueError('explicit strict_reported/reserved_unknown writer usage policy required')
    bound = runtime.get('max_output_bytes', 2_000_000)
    if type(bound) is not int or not 1 <= bound <= 15_934_464:
        raise ValueError('positive finite complete writer public-output byte bound required')
    if policy == 'reserved_unknown' and (runtime['action'] != 'external' or 'max_output_bytes' not in runtime):
        raise ValueError('unknown usage requires an external writer and explicit public-output byte bound')
    return {'usage_policy': policy, 'max_output_bytes': bound}


def _writer_completion_parameters(runtime):
    if not any(k in runtime for k in ('usage_policy', 'max_output_bytes')):
        return {} # Preserve the original strict request/node envelope.
    bound = _writer_policy(runtime)['max_output_bytes']
    return {'completion_limits': {'public_value_bytes': bound, 'response_file_bytes': bound + 65_536}}


def _writer_accounting(runtime, receipt, saved, checkpoint, calls):
    from .agent_host import _usage, _json_bytes, HostFailure
    policy = _writer_policy(runtime)
    usage = saved['result']['usage']; transport = saved['result']['transport']
    try:
        ce.keys(usage, ['input_tokens', 'output_tokens', 'total_tokens'])
        measured = _usage(usage)
    except (HostFailure, ValueError, TypeError) as exc:
        raise ValueError('invalid complete writer token telemetry') from exc
    unknown = all(v is None for v in measured.values())
    if not unknown and any(v is None for v in measured.values()):
        raise ValueError('note requires complete token telemetry or explicitly unknown usage')
    if unknown:
        if policy['usage_policy'] != 'reserved_unknown':
            raise ValueError('note requires actual token telemetry; unknown remains unknown')
        proof = receipt.get('external_completion_evidence')
        if (receipt['execution_observation'] != 'host_attested_external'
                or transport.get('execution_mode') != 'host_mediated_external'
                or type(proof) is not dict or proof.get('calls') != 1
                or proof.get('reserved_output_tokens') != runtime['max_output_tokens']
                or len(calls) != 1 or len(checkpoint.get('calls', {})) != 1
                or checkpoint.get('usage') != {'calls': 1, 'reserved_output_tokens': runtime['max_output_tokens']}
                or calls[0]['receipt'].get('output_tokens_reserved') != runtime['max_output_tokens']
                or calls[0]['receipt'].get('result') != saved['result']):
            raise ValueError('unknown writer usage lacks its whole consumed external reservation')
    elif measured['input_tokens'] > runtime['max_input_tokens'] or measured['output_tokens'] > runtime['max_output_tokens']:
        raise ValueError('writer output ceiling violated')
    value = receipt['public_value']
    if len(_json_bytes(value)) > policy['max_output_bytes']:
        raise ValueError('complete writer public value exceeds byte bound; no truncation')
    return {**policy, 'usage': measured,
        'usage_observation': transport.get('usage_observation', 'unknown' if unknown else 'receipt_reported'),
        'external_usage_evidence': transport.get('usage_report'),
        'external_completion_evidence': receipt.get('external_completion_evidence'),
        'reserved_output_tokens': runtime['max_output_tokens'],
        'reservation_refunded': False, 'input_token_ceiling_verified': not unknown,
        'output_token_ceiling_verified': not unknown,
        'inference_token_ceiling_enforced': transport.get('inference_token_ceiling_enforced'),
        'limit': 'Reservations are consumed budget, not measured inference. External telemetry is host-reported; null counts remain unknown.'}



def _revision_origin(previous, base, consumed):
    """Reconsume the actual prior writer and products before any improver exposure.

    The cache lives only inside this verification operation. Every reuse rereads
    its exact dependencies; neither an honestly rehashed copy nor saved metadata
    can replace the original producer. Active producer identity rejects cycles.
    """
    session = _REVISION_VERIFICATION.get()
    token = None
    if session is None:
        session = {'active': [], 'verified': {}}
        token = _REVISION_VERIFICATION.set(session)
    try:
        origin = str(integrity._artifact_path(previous['author_binding'], base))
        key = (origin, ce.digest(previous))
        if origin in session['active']:
            raise ValueError('cyclic previous manuscript author ancestry')
        if len(session['active']) >= MAX_REVISION_ANCESTORS:
            raise ValueError('previous manuscript ancestry exceeds finite verification bound')
        session['active'].append(origin)
        try:
            if key not in session['verified']:
                proof = {}
                binding = integrity._json(integrity._raw(previous['author_binding'], base, proof))
                integrity._raw(binding['presentation'], base, proof)
                graph = Path(binding['graph'])
                for name in (agent_graph.SPEC, agent_graph.STATE):
                    integrity._raw(_pin(graph/name), base, proof)
                checkpoint = agent_graph.status(graph)
                reference = checkpoint['nodes']['author']['result']
                if type(reference) is dict:
                    integrity._raw(_pin(graph/reference['path']), base, proof)
                for ref in agent_graph._result(graph, reference)['call_receipts']:
                    integrity._raw(_pin(graph/'calls'/(ref['call_id']+'.json')), base, proof)
                verify_author_origin(previous, base_dir=base, consumed=proof)
                session['verified'][key] = list(proof.values())
            # Cached deterministic bytes are not cached authority. Reconsume all
            # live role/external/packet-membership/source-review/campaign guards.
            # Mutable campaign heads are deliberately NOT permanent input pins.
            for pin in session['verified'][key]:
                integrity._dependency(pin, base, consumed)
            binding = integrity._json(integrity._raw(previous['author_binding'], base, {}))
            request=integrity._json(integrity._raw(binding['request'],base,{}))
            loaded=_load(request,binding['base_dir'])
            view=_origin_view(binding,loaded)
            _author_state(binding,_origin=view)
            if view is not None:view.close()
            for pin in session['verified'][key]:
                integrity._dependency(pin, base, consumed)
        finally:
            session['active'].pop()
    finally:
        if token is not None:
            _REVISION_VERIFICATION.reset(token)



class _OriginView:
    """Operation-local authenticated history, never a supplied old campaign state."""
    def __init__(self, binding, loaded):
        from . import research_cycle as cycle
        self.root=cycle._ordinary(binding['campaign']).resolve(strict=True)
        self.head=_pin(self.root/'head.json')
        root,self.current=cycle._load(self.root)
        head=integrity._json(integrity._raw(self.head,self.root,{}))
        if cycle._read(head,self.root)!=self.current:
            raise ValueError('historical origin changed campaign head during capture')
        count=self.current['revision']
        if type(count) is not int or not 0<=count<cycle.MAX_REVISIONS:
            raise ValueError('historical origin requires finite ordinary campaign history')
        parent=cycle._parent_goal(self.current)
        self.parent_pins=[] if parent is None else deepcopy(parent['input_pins'])
        for pin in self.parent_pins:integrity._dependency(pin,self.current['base_dir'],{})
        self.pins=[];self.records=[]
        for index in range(count+1):
            pin=_pin(self.root/'history'/f'{index:04d}.json')
            record=integrity._json(integrity._raw(pin,self.root,{}))
            content=deepcopy(record);checksum=content.pop('sha256')
            if (record['revision']!=index or checksum!=ce.digest(content)
                    or record['parent_sha256']!=(None if index==0 else self.records[-1]['sha256'])):
                raise ValueError('historical origin campaign ancestry differs')
            self.pins.append(pin);self.records.append(record)
        if self.records[-1]!=self.current:
            raise ValueError('historical origin is not the authenticated current chain')
        self.cutoff=count
        self.owner=None
        q=loaded['documents']['quantitative_report']
        context=scientific_report._context(q['context'],integrity._artifact_path(loaded['request']['quantitative_report'],loaded['source_base']).parent)
        self.owner=self.select(campaign=binding['campaign'],prepared_sha256=binding['research_state_sha256'],
            graph_root=binding['graph'],graph_spec=binding['spec'],checkpoint=agent_graph.status(binding['graph']),
            quantitative_context=context)
        self.cutoff=self.owner['revision']
        self.close()

    def select(self, *, campaign, prepared_sha256, graph_root, graph_spec, checkpoint, quantitative_context):
        from . import research_cycle as cycle
        if cycle._ordinary(campaign).resolve(strict=True)!=self.root:
            raise ValueError('historical origin cannot borrow another campaign')
        graph_root=cycle._ordinary(graph_root).resolve(strict=True)
        if not checkpoint.get('complete') or checkpoint.get('spec_sha256')!=ce.digest(graph_spec):
            raise ValueError('historical origin requires the exact live completed Graph')
        preparations=[r for r in self.records[:self.cutoff+1] if r['sha256']==prepared_sha256]
        if len(preparations)!=1:
            raise ValueError('historical origin preparation is absent from original campaign')
        prepared=preparations[0]
        if prepared['context']!=quantitative_context:
            raise ValueError('historical origin preparation differs from replayed quantities')
        keys=('kind','contract','original_request','original_obligations','assignment','parent_acceptance_scope')
        def identity(state):
            parent=state.get('parent_task')
            return None if parent is None else {k:parent[k] for k in keys}
        expected_parent=identity(self.current)
        if (prepared['contract']!=self.current['contract'] or prepared['base_dir']!=self.current['base_dir']
                or identity(prepared)!=expected_parent
                or graph_spec.get('goal_binding')!=prepared['contract'].get('goal_binding')):
            raise ValueError('historical origin changed original contract or parent assignment')
        if expected_parent is not None:
            # The original prompt is independently authenticated by the current
            # parent loader; a historical effective scope grants no permission.
            cycle._parent_goal(self.current)
        def reservation(state):
            rows=[r for r in state['resource_ledger'] if r['id']=='graph:'+str(graph_root)]
            if len(rows)!=1:raise ValueError('historical origin requires original one-time Graph reservation')
            return rows[0]
        selected=None
        for record in self.records[prepared['revision']+1:self.cutoff+1]:
            event=record['events'][-1]
            if (event.get('revision')!=record['revision'] or event.get('kind')!='ordinary_graph_observed'
                    or event.get('graph_root')!=str(graph_root)):
                continue
            rows=[r for r in record['graphs'] if r['root']==str(graph_root)]
            if len(rows)!=1 or not rows[0].get('complete'):continue
            row=rows[0]
            if (row.get('revision')!=ce.digest(graph_spec) or row.get('usage')!=checkpoint['usage']
                    or record['context']!=quantitative_context):
                raise ValueError('historical completion differs from exact live Graph or replayed quantities')
            selected=record;break
        if selected is None:
            raise ValueError('historical origin lacks actual post-preparation completed Graph observation')
        if selected['contract']!=prepared['contract'] or identity(selected)!=expected_parent:
            raise ValueError('historical completion changed original parent or contract')
        charged=reservation(selected)
        if reservation(self.current)!=charged:
            raise ValueError('historical original Graph reservation changed in live campaign')
        reserves=[r for r in self.records[prepared['revision']+1:selected['revision']]
            if r['events'][-1].get('kind')=='ordinary_graph_reserved'
            and r['events'][-1].get('graph_root')==str(graph_root)
            and reservation(r)==charged]
        if len(reserves)!=1:
            raise ValueError('historical completion lacks its unique original post-preparation charge')
        cycle.validate_graph_reservation(selected,graph_root,graph_spec)
        cycle.validate_graph_reservation(self.current,graph_root,graph_spec)
        for key in ('started_epoch','deadline_epoch','policy'):
            if selected['timing'][key]!=self.current['timing'][key]:
                raise ValueError('historical origin cannot reset original campaign timing')
        if prepared['timing']['started_epoch'] is not None and prepared['timing']!=selected['timing']:
            raise ValueError('historical completion changed an already-started campaign timer')
        if self.owner is not None:
            owned=[r for r in self.owner['graphs'] if r['root']==str(graph_root)]
            if len(owned)!=1 or any(owned[0].get(k)!=row.get(k) for k in ('usage','revision','complete')):
                raise ValueError('historical phase is not complete in its original owner completion')
        self.close()
        return deepcopy(selected)

    def close(self):
        from . import research_cycle as cycle
        integrity._raw(self.head,self.root,{})
        for pin in self.pins:integrity._raw(pin,self.root,{})
        for pin in self.parent_pins:integrity._dependency(pin,self.current['base_dir'],{})
        if cycle._load(self.root)[1]!=self.current:
            raise ValueError('historical origin campaign or live parent changed during verification')
        integrity._raw(self.head,self.root,{})
        for pin in self.pins:integrity._raw(pin,self.root,{})
        for pin in self.parent_pins:integrity._dependency(pin,self.current['base_dir'],{})


def _origin_campaign(view, *, campaign, prepared_sha256, graph_root, graph_spec, checkpoint, quantitative_context):
    """Read-only staged phase selection from the internally derived owner chain."""
    if type(view) is not _OriginView:
        raise ValueError('internally authenticated historical origin view required')
    return view.select(campaign=campaign,prepared_sha256=prepared_sha256,graph_root=graph_root,
        graph_spec=graph_spec,checkpoint=checkpoint,quantitative_context=quantitative_context)


def _origin_view(binding, loaded):
    from . import research_cycle
    _,current=research_cycle._load(binding['campaign'])
    q=loaded['documents']['quantitative_report']
    replayed=scientific_report._context(q['context'],integrity._artifact_path(loaded['request']['quantitative_report'],loaded['source_base']).parent)
    # Select deliberately, never recover from a failed current verifier.
    if replayed==current['context']:return None
    view=_OriginView(binding,loaded)
    parent=view.current.get('parent_task')
    if parent is not None and parent['original_request']!=loaded['documents']['original_task']:
        raise ValueError('historical author changed original parent task')
    return view


def _revision_campaign(loaded, campaign):
    """A revision consumes its authenticated original campaign, never a new budget."""
    if loaded['revision'] is None:
        return
    previous = loaded['revision']['previous']
    binding = integrity._json(integrity._raw(previous['author_binding'], loaded['source_base'], {}))
    if Path(binding['campaign']).resolve() != Path(campaign).resolve():
        raise ValueError('revision changed original authenticated author campaign')

def _load(request, base, *, planning=False):
    """Complete, current public context; no unobserved missing inputs invented."""
    request = deepcopy(request)
    ce.keys(request, ['schema_version','profile','author_id','original_task','quantitative_report',
        'source_manifest','environment','code_manifest','skills','methods','citations','figures',
        'runtime','revision','challenge_requirements','template','formatting']
        +[k for k in ('blinding_policy','blinding_sources','source_review','author_visuals') if k in request])
    if type(request['schema_version']) is not int or request['schema_version'] != 1 or request['profile'] not in PROFILES:
        raise ValueError('explicit manuscript production/v1 profile required')
    ce.identity(request['author_id']); consumed = {}
    documents = {}
    formatting=manuscript_format.load(request['formatting'],base,consumed)
    if formatting['profile']!=request['profile']:raise ValueError('format profile cannot silently replace requested venue')
    template=None
    if request['template'] is not None:
        template=integrity._raw(request['template'],base,consumed).decode()
        if template.count('%RAVEL_BODY%')!=1: raise ValueError('authenticated template needs exactly one explicit body slot')
    for key in ('original_task','source_manifest','environment','code_manifest','quantitative_report'):
        raw = integrity._raw(request[key], base, consumed)
        documents[key] = raw.decode() if key == 'original_task' else integrity._json(raw)
    if not documents['original_task'].strip(): raise ValueError('literal whole original task required')
    manifest=documents['source_manifest']; ce.keys(manifest,['schema_version','evidence'])
    evidence={}
    for row in integrity._rows(manifest['evidence'],'complete source evidence'):
        ce.keys(row,['id','description','located']); ce.identity(row['id']); integrity._text(row['description'])
        if row['id'] in evidence: raise ValueError('duplicate evidence id')
        evidence[row['id']]={**row,'located':integrity._located(row['located'],base,consumed)}
    # Environments and all workflow code must be source-bound, not author assertions.
    environment=documents['environment']; ce.keys(environment,['schema_version','description','assets'])
    for pin in integrity._rows(environment['assets'],'environment assets',empty=False): integrity._dependency(pin,base,consumed)
    code=documents['code_manifest']; ce.keys(code,['schema_version','git_commit','dirty','files'])
    if type(code['dirty']) is not bool or not re.fullmatch('[0-9a-f]{40}',code['git_commit']): raise ValueError('literal git revision/dirty provenance required')
    for pin in integrity._rows(code['files'],'whole used workflow code',empty=False): integrity._raw(pin,base,consumed)
    skills=[]
    for pin in integrity._rows(request['skills'],'used software skills',empty=False):
        skills.append(integrity._raw(pin,base,consumed).decode())
    report_base=integrity._artifact_path(request['quantitative_report'],base).parent
    quantitative=scientific_report.compose(documents['quantitative_report'],base_dir=report_base)
    for pin in scientific_report.input_pins(documents['quantitative_report'],base_dir=report_base): integrity._raw(pin,report_base,consumed)
    methods={}; citations={}; figures={}
    for row in integrity._rows(request['methods'],'complete used methods'):
        ce.keys(row,['id','description','operations','citation_ids','uncertainties']); ce.identity(row['id'])
        integrity._text(row['description'])
        for value in integrity._rows(row['uncertainties'],'method uncertainties'):integrity._text(value)
        for cid in integrity._rows(row['citation_ids'],'method citation IDs'):ce.identity(cid)
        if row['id'] in methods: raise ValueError('duplicate method')
        operations=[];operation_ids=set()
        for op in integrity._rows(row['operations'],'method operations',empty=False):
            ce.keys(op,['id','description','code','execution','results','differences'])
            ce.identity(op['id']);integrity._text(op['description'])
            if op['id'] in operation_ids:raise ValueError('duplicate method operation')
            operation_ids.add(op['id'])
            for value in integrity._rows(op['differences'],'method concomitant differences'):integrity._text(value)
            code=[integrity._located(e,base,consumed) for e in integrity._rows(op['code'],'complete operation code',empty=False)]
            results=[integrity._located(e,base,consumed) for e in integrity._rows(op['results'],'complete operation results')]
            operations.append({**op,'execution_evidence':integrity._executed(op['execution'],code,results,base,consumed)})
        methods[row['id']]={**row,'presented_operations':operations}
    for row in integrity._rows(request['citations'],'complete bibliography'):
        ce.keys(row,['id','bibliography','identity_evidence','uncertainties']); ce.identity(row['id'])
        if row['id'] in citations: raise ValueError('duplicate citation')
        ce.keys(row['bibliography'],['title','authors','year','identifiers'])
        for key in ('title','year'):integrity._text(row['bibliography'][key])
        for key in ('authors','identifiers'):
            for value in integrity._rows(row['bibliography'][key],'bibliography '+key,empty=False):integrity._text(value)
        for value in integrity._rows(row['uncertainties'],'citation uncertainties'):integrity._text(value)
        for source in integrity._rows(row['identity_evidence'],'bibliography identity evidence',empty=False):
            ce.keys(source,['source_role','source_url','located'])
            if source['source_role'] not in {'primary-paper','author-repository','publisher-metadata','secondary'}:raise ValueError('explicit bibliography evidence role required')
            integrity._text(source['source_url']);integrity._located(source['located'],base,consumed)
        citations[row['id']]=row
    for row in integrity._rows(request['figures'],'complete figures'):
        ce.keys(row,['id','image','contract','evidence_ids','comparison']); ce.identity(row['id'])
        if row['id'] in figures or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',row['id']): raise ValueError('distinct TeX-safe figure id required')
        if not set(row['evidence_ids']) <= set(evidence): raise ValueError('figure scientific-source evidence missing')
        image=integrity._artifact_path(row['image'],base)
        if image.suffix.lower() not in {'.png','.jpg','.jpeg','.pdf','.svg'}: raise ValueError('portable figure asset required')
        integrity._raw(row['image'],base,consumed); integrity._json(integrity._raw(row['contract'],base,consumed))
        if row['comparison'] is not None:
            ce.keys(row['comparison'],['reference','generated','composite'])
            for pin in row['comparison'].values(): integrity._raw(pin,base,consumed)
            if row['image'] != row['comparison']['composite']: raise ValueError('comparison figure must expose actual composite pixels')
        figures[row['id']]=row
    if not planning and any(not set(row['citation_ids'])<=set(citations) for row in methods.values()): raise ValueError('method bibliography incomplete')
    challenge=None
    if request['challenge_requirements'] is not None:
        challenge=integrity._json(integrity._raw(request['challenge_requirements'],base,consumed))
    if challenge is None and manuscript_format.note_requirements(formatting,base)['requires_supplied_requirements']:
        raise ValueError('this note rule pack needs the complete supplied requirements document')
    if request.get('blinding_policy') is not None:
        integrity._json(integrity._raw(request['blinding_policy'],base,consumed))
        if request.get('blinding_sources') is None:raise ValueError('blinded author needs actual upstream public projection proof before its charged call')
        integrity._json(integrity._raw(request['blinding_sources'],base,consumed))
    elif request.get('blinding_sources') is not None:raise ValueError('public projection proof needs the original blind policy')
    census_reserve=len(methods)+sum(len(m['operations']) for m in methods.values())+len(citations)+len(figures)+len(formatting['rules'])
    # Reserve enough material case nodes for every possible author paragraph;
    # an oversize known source population refuses before the charged call.
    if census_reserve+MAX_PARAGRAPHS+(1 if request.get('blinding_policy') is not None else 0)>integrity.MAX_ITEMS:
        raise ValueError('whole method/citation/figure/format case exceeds finite author envelope; no truncation')
    runtime=request['runtime']; ce.keys(runtime,['model','model_build','action','reasoning_effort','max_output_tokens','max_input_tokens','max_context_bytes','max_wall_seconds']
        +[k for k in ('usage_policy','max_output_bytes') if k in runtime])
    _writer_policy(runtime)
    for name in ('model','model_build','reasoning_effort'): integrity._text(runtime[name])
    if runtime['action'] not in {'model','external'}: raise ValueError('existing explicit Graph model transport required')
    if any(type(runtime[k]) is not int or runtime[k]<=0 for k in ('max_output_tokens','max_input_tokens','max_context_bytes','max_wall_seconds')):
        raise ValueError('positive prospective call/token/wall bounds required')
    revision=None
    if request['revision'] is not None:
        from . import scientific_judgment
        ce.keys(request['revision'],['previous_package','feedback_binding'])
        previous=integrity._json(integrity._raw(request['revision']['previous_package'],base,consumed))
        _revision_origin(previous,base,consumed)
        feedback=scientific_judgment.verify_binding(request['revision']['feedback_binding'])
        if feedback['receipt']['role'] not in {'critic','verifier'} or feedback['value']['verdict']!='send_back':
            raise ValueError('revision requires actual independent material send-back')
        if (previous['original_task']!=request['original_task'] or previous['author_id']!=request['author_id']):
            raise ValueError('revision changed original task or author')
        # Full exact request identity is an actual case anchor, not a keyword lookup.
        case=scientific_judgment._read_pin(feedback['contract']['case_pin'])
        anchors=next(n for n in case['nodes'] if n['id']==case['root'])['anchors']
        if not any(a['format']=='json' and a['location']=='' and ce.digest(a['value'])==previous['integrity_request_sha256'] for a in anchors):
            raise ValueError('send-back is not about the exact prior manuscript request')
        for pin in feedback['supporting_artifacts']:
            p=Path(feedback['contract']['rundir'])/pin['path'] if not Path(pin['path']).is_absolute() else Path(pin['path'])
            integrity._raw(_pin(p),base,consumed)
        revision={'previous':previous,'actual_feedback':feedback['value']}
    if request.get('author_visuals') is not None:
        _visual_inputs(request,base,consumed)
    result={'request':request,'source_base':str(Path(base).absolute()),'documents':documents,'evidence':evidence,'methods':methods,'citations':citations,'figures':figures,
        'skills':skills,'formatting':formatting,'template':template,'quantitative_report':quantitative,'challenge':challenge,'revision':revision,'input_pins':list(consumed.values())}
    for pin in result['input_pins']: integrity._dependency(pin,base,{})
    if request.get('blinding_policy') is not None:
        from . import final_results_review
        census=_blinding_census(result,base)
        proof=integrity._json(integrity._raw(request['blinding_sources'],base,{}))
        if any(r.get('producer',{}).get('kind') in {'authored_manuscript','manuscript_build'} for r in proof['lineage'] if r.get('producer') is not None):
            raise ValueError('writer source proof cannot recursively borrow future manuscript authority')
        policy={k:census['policy'][k] for k in ('path','sha256')}
        for pin in final_results_review._source_blinding(Path(base),proof,policy,
                [{k:p[k] for k in ('path','sha256')}|{'role':'source_output'} for p in census['data']]):
            path=integrity._artifact_path(pin,base);integrity._dependency({**pin,'size':path.stat().st_size},base,{})
    return result


def input_pins(request, *, base_dir):
    loaded=_load(request,base_dir);pins=deepcopy(loaded['input_pins'])
    if request.get('source_review') is not None:
        _check_source_review(loaded);binding=request['source_review']
        ir=integrity._json(integrity._raw(binding['request'],base_dir,{}))
        pins.extend([binding['request'],*integrity.assessment_pins(ir,binding['bindings'],base_dir=base_dir)])
    return list({str(integrity._artifact_path(p,base_dir)):{**p,'path':str(integrity._artifact_path(p,base_dir))} for p in pins}.values())


def output_schema(formatting=None, *, has_template=False, planned_claims=False):
    def obj(props): return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    text={'type':'string','minLength':1,'maxLength':16000}
    ids={'type':'array','items':{'type':'string'},'maxItems':255}
    paragraph=obj({'id':{'type':'string'},'section':{'type':'string','enum':[x['id'] for x in manuscript_format.section_layout(formatting)] if formatting is not None else list(SECTIONS)},
        'kind':{'type':'string','enum':['claim','method']},'text':text,'method_ids':ids,
        'citation_ids':ids,'evidence_ids':ids,'uncertainties':{'type':'array','items':text,'maxItems':32}})
    figure=obj({'id':{'type':'string'},'caption':text,'citation_ids':ids,'uncertainties':{'type':'array','items':text,'maxItems':32}})
    properties={'schema_version':{'type':'integer','enum':[1]},'paragraphs':{'type':'array','items':paragraph,'minItems':1,'maxItems':MAX_PARAGRAPHS},
        'figures':{'type':'array','items':figure,'maxItems':64}}
    if has_template:
        properties['template_units']={'type':'array','minItems':1,'maxItems':MAX_PARAGRAPHS,'items':obj({
            'id':{'type':'string'},'kind':{'type':'string','enum':['claim','other']},
            'start':{'type':'integer','minimum':0},'end':{'type':'integer','minimum':1},
            'rendered_section':{'type':['null','string'],'anyOf':[{'type':'null'},{'type':'string','enum':[x['id'] for x in manuscript_format.section_layout(formatting)]}]},
            'evidence_ids':ids,'citation_ids':ids,'method_ids':ids,'uncertainties':{'type':'array','items':text,'maxItems':32}})}
    if planned_claims:
        from . import manuscript_claim_disposition
        properties['claim_dispositions']=manuscript_claim_disposition.schema()
    return obj(properties)


def _visual_inputs(request, base, consumed):
    """Full author-media correspondence. Declared source pins alone never prove conversion."""
    figures={f['id']:f for f in request['figures']}; rows=request.get('author_visuals',[])
    if rows:
        if type(rows) is not list or len(rows)!=len(figures):raise ValueError('whole author figure-view census required')
        if len({r.get('figure_id') for r in rows})!=len(rows):raise ValueError('duplicate author figure view')
    supplied={r['figure_id']:r for r in rows}; sources=[]
    for identity,figure in figures.items():
        source=figure['image']; path=integrity._artifact_path(source,base)
        if path.suffix.lower() in {'.png','.pdf'}:
            if identity in supplied:
                ce.keys(supplied[identity],['figure_id','source','image','conversion'])
                if supplied[identity]!={'figure_id':identity,'source':source,'image':source,'conversion':None}:raise ValueError('native author image cannot substitute source')
            view=source
        else:
            if identity not in supplied:raise ValueError('JPEG/SVG author figure requires an actual complete ordinary conversion; prepare a PNG/PDF view without inventing pixels')
            row=supplied[identity];ce.keys(row,['figure_id','source','image','conversion'])
            if row['source']!=source or row['conversion'] is None:raise ValueError('author view changed source or lacks conversion custody')
            view=row['image'];target=integrity._artifact_path(view,base)
            if target.suffix.lower() not in {'.png','.pdf'}:raise ValueError('native PNG/PDF author view required')
            integrity._raw(source,base,consumed);integrity._raw(view,base,consumed)
            proof=integrity._executed(row['conversion'],[{'artifact':source,'location':'','statement':'exact original figure'}],
                [{'artifact':view,'location':'','statement':'complete native author view'}],base,consumed)
            if proof['state']!='current_successful_stage':raise ValueError('author figure conversion failed or remains unresolved')
            # Conversion is an ordinary actual stage subject to the same original
            # scientific/visual review; custody does not certify its pixel equivalence.
        integrity._raw(view,base,consumed)
        canonical={**view,'path':str(integrity._artifact_path(view,base))}
        if canonical not in sources:sources.append(canonical)
    if set(supplied)-set(figures):raise ValueError('foreign author figure view')
    return sources


def _author_packet(root, loaded, *, role):
    from . import review_context
    from ravel.physics import root_stream
    sources=_visual_inputs(loaded['request'],loaded['source_base'],{})
    if not sources:return None
    root=Path(root);root.mkdir();(root/'artifacts').mkdir()
    artifacts=[]
    for index,pin in enumerate(sources):
        raw=integrity._raw(pin,loaded['source_base'],{})
        root_stream.model_artifact_source(pin['path'],pin['sha256'])
        identity='writer_visual%04d'%index;relative='artifacts/'+identity+Path(pin['path']).suffix.lower()
        _write(root/relative,raw)
        artifacts.append({'id':identity,'path':relative,'sha256':pin['sha256'],'size':pin['size'],
            'source_path':pin['path'],'source_sha256':pin['sha256'],'projection':'exact bytes','presentation':'inline'})
    manifest={'schema_version':1,'kind':'manuscript-author-visual-packet','role':role,'artifacts':artifacts,
        'omissions':[],'index_limits':review_context._index_limits(),'scientific_review':False}
    manifest['sha256']=ce.digest(manifest);integrity._new(root/'manifest.json',manifest)
    packet={'path':str(root.absolute()),'manifest_sha256':manifest['sha256']}
    _verify_author_packet(packet,loaded,role=role)
    return packet


def _verify_author_packet(packet,loaded,*,role):
    from . import review_context
    sources=_visual_inputs(loaded['request'],loaded['source_base'],{})
    if not sources:
        if packet is not None:raise ValueError('foreign empty-population author packet')
        return []
    if packet is None:raise ValueError('all author figure pixels must be bound to the actual node packet')
    index=review_context._PacketIndex(packet['path'],packet['manifest_sha256'])
    if index.manifest.get('kind')!='manuscript-author-visual-packet' or index.manifest.get('role')!=role or index.manifest.get('omissions')!=[]:raise ValueError('author packet role/population changed')
    expected=[]
    for i,pin in enumerate(sources):
        identity='writer_visual%04d'%i;expected.append({'id':identity,'path':'artifacts/'+identity+Path(pin['path']).suffix.lower(),
            'sha256':pin['sha256'],'size':pin['size'],'source_path':pin['path'],'source_sha256':pin['sha256'],
            'projection':'exact bytes','presentation':'inline'})
    if index.manifest['artifacts']!=expected:raise ValueError('whole source figure/page roster changed or omitted')
    for row,pin in zip(expected,sources):
        if index.read(row)!=integrity._raw(pin,loaded['source_base'],{}):raise ValueError('author packet source bytes changed')
    index.finish();return sources


def _author_visual_parameters(loaded,packet,role):
    sources=_verify_author_packet(packet,loaded,role=role)
    return {'visual_sources':sources} if sources else {}


def _verify_author_vision(receipt,loaded,packet,node_id,role):
    from . import visual_presentation
    sources=_verify_author_packet(packet,loaded,role=role)
    if sources:
        return visual_presentation.verify_visual_presentation(receipt,expected_sources=sources,
            expected_packet_sha256=packet['manifest_sha256'],expected_node_id=node_id)
    return None


def prepare_writer(request, out, *, base_dir, campaign, stages=None):
    from . import research_cycle
    loaded=_load(request,base_dir); _revision_campaign(loaded,campaign)
    root=_fresh(out); request=loaded['request']
    _check_source_review(loaded)
    _,state=research_cycle._load(campaign)
    quantitative=loaded['documents']['quantitative_report']
    if state.get('parent_task') is not None:
        parent=research_cycle._read(state['parent_task']['contract'],Path(campaign))
        if parent['prompt']!=loaded['documents']['original_task']: raise ValueError('note authoring changed the original parent request')
    if quantitative.get('context') is None: raise ValueError('normal research note needs its current quantity context')
    if scientific_report._context(quantitative['context'],integrity._artifact_path(request['quantitative_report'],base_dir).parent)!=state['context']:
        raise ValueError('writer cannot borrow another or stale research context')
    presentation=_production_presentation(loaded,stages,campaign)
    presented=integrity._new(root/'writer-context.json',presentation)
    saved_request=integrity._new(root/'production-request.json',request)
    inputs=[{'id':'context','path':presented['path'],'sha256':presented['sha256']},
        {'id':'request','path':saved_request['path'],'sha256':saved_request['sha256']}]
    context_transport='source-artifact-v1'
    instructions=_instructions(request,presentation,context_transport=context_transport)
    runtime=request['runtime']
    _context_bound(runtime,instructions,presented,saved_request,root,context_transport=context_transport)
    role='improver' if request['revision'] else 'proposer'
    visual_loaded=_synthesis_visual_scope(loaded,stages,campaign)
    packet=_author_packet(root/'author-packet',visual_loaded,role=role)
    node={'id':'author','kind':'model','role':'improver' if request['revision'] else 'proposer','depends_on':[],
        'inputs':inputs,'packet':packet,'action':runtime['action'],'parameters':{'instructions':instructions,'model':runtime['model'],
        'reasoning_effort':runtime['reasoning_effort'],'max_output_tokens':runtime['max_output_tokens'],'output_schema':output_schema(loaded['formatting'],has_template=loaded['template'] is not None,planned_claims=_has_claim_plan(loaded,stages)),**_writer_completion_parameters(runtime),**_author_visual_parameters(visual_loaded,packet,role)},'max_attempts':1}
    spec={'schema_version':1,'graph_id':'manuscript-author','budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':runtime['max_output_tokens'],
        'max_wall_seconds':runtime['max_wall_seconds'],'max_reworks':0},'nodes':[node]}
    if 'goal_binding' in state['contract']: spec['goal_binding']=deepcopy(state['contract']['goal_binding'])
    graph=root/'graph'; agent_graph.create(graph,spec)
    binding={'schema_version':1,'kind':'manuscript-author-binding','campaign':str(Path(campaign).absolute()),'research_state_sha256':state['sha256'],
        'request':saved_request,'base_dir':str(Path(base_dir).absolute()),'presentation':presented,'graph':str(graph),'spec':spec,
        'author_id':request['author_id'],'packet':packet,'input_pins':loaded['input_pins'],'context_transport':context_transport,'execution_authorized':False}
    if stages is not None:binding['stages']=deepcopy(stages)
    integrity._new(root/'binding.json',binding)
    if _load(request,base_dir)!=loaded: raise ValueError('writer source changed during Graph preparation')
    return binding


def _synthesis_visual_scope(loaded,stages,campaign,*,_origin=None):
    if stages is None:return loaded
    from . import manuscript_workflow
    manuscript_workflow.verify_transcript(stages,loaded,campaign,**({'_origin':_origin} if _origin is not None else {}))
    # The full earlier author caption-wire census is separately retained.
    # Do not claim that a fresh synthesis call saw images from another call.
    selected=deepcopy(loaded);selected['figures']={};selected['request']['figures']=[]
    if 'author_visuals' in selected['request']:selected['request']['author_visuals']=[]
    return selected


def _production_presentation(loaded,stages,campaign,*,_origin=None):
    presentation=_presentation(loaded)
    if stages is not None:
        from . import manuscript_workflow
        presentation['writing_transcript']=manuscript_workflow.verify_transcript(stages,loaded,campaign,**({'_origin':_origin} if _origin is not None else {}))
    context=_claim_context(loaded,stages,campaign,transcript=presentation.get('writing_transcript'))
    if context is not None:
        reserve=len(loaded['methods'])+sum(len(m['operations']) for m in loaded['methods'].values())+len(loaded['citations'])+len(loaded['figures'])+len(loaded['formatting']['rules'])
        if reserve+MAX_PARAGRAPHS+len(context['plan']['claim_map'])+(1 if loaded['request'].get('blinding_policy') is not None else 0)>integrity.MAX_ITEMS:
            raise ValueError('complete planned claim census exceeds the existing finite author/reviewer envelope')
        presentation['planned_claim_context']=context
    return presentation


def _has_claim_plan(loaded,stages):
    return stages is not None or (loaded['revision'] is not None and 'planned_claim_census' in loaded['revision']['previous'])


def _claim_context(loaded,stages,campaign,*,transcript=None):
    if loaded['revision'] is not None and 'planned_claim_census' in loaded['revision']['previous']:
        _claim_revision_change(loaded)
    if stages is not None:
        if transcript is None:
            from . import manuscript_workflow
            transcript=manuscript_workflow.verify_transcript(stages,loaded,campaign)
        return {'plan':deepcopy(transcript['original_claim_plan']),
            'phase_censuses':deepcopy(transcript['complete_phase_claim_census']),
            'original_evidence':deepcopy(transcript['original_claim_evidence']),
            'original_missing':deepcopy(transcript['original_missing_claim_sources']),
            'source_bindings':{'kind':'actual-staged-claim-plan','story':deepcopy(stages['story']),
                'resolution':deepcopy(stages['resolution']),'products':deepcopy(stages['products'])}}
    if not _has_claim_plan(loaded,stages):return None
    # _load authenticated the complete prior package with verify_author_origin.
    # An ordinary direct improver cannot erase that original planned roster.
    pin=loaded['revision']['previous']['planned_claim_census']
    census=integrity._json(integrity._raw(pin,loaded['source_base'],{}))
    return {'plan':deepcopy(census['plan']),'phase_censuses':deepcopy(census['phase_censuses']),
        'original_evidence':deepcopy(census['original_evidence']),'original_missing':deepcopy(census['original_missing']),
        'source_bindings':{'kind':'authenticated-prior-claim-plan','prior_census':deepcopy(pin),
            'previous_package':deepcopy(loaded['request']['revision']['previous_package']),
            'prior_source_bindings':deepcopy(census['source_bindings'])}}


def _claim_revision_change(loaded):
    from . import manuscript_workflow as mw
    previous=loaded['revision']['previous'];base=loaded['source_base']
    oldbinding=integrity._json(integrity._raw(previous['author_binding'],base,{}))
    oldpresentation=integrity._json(integrity._raw(oldbinding['presentation'],base,{}))
    before=mw._bound_record({k:oldpresentation[k] for k in ('sources','methods','current_quantities','figures')},oldbinding['base_dir'])
    actual=_presentation(loaded)
    after=mw._bound_record({k:actual[k] for k in before},base)
    if before==after:return
    responses=[]
    for row in loaded['evidence'].values():
        located=row['located'];value=located['value']
        if located['format']=='json' and located['location']=='' and type(value) is dict and value.get('kind')=='manuscript-action-response':
            if mw._canon(value['prior_package'],base,{})==mw._canon(loaded['request']['revision']['previous_package'],base,{}):responses.append(located)
    if len(responses)!=1:raise ValueError('changed planned-claim science requires the existing authenticated action/protocol response')
    response=responses[0]['value']
    ce.keys(response,['schema_version','kind','action_plan','prior_package','replacement_request','actual_protocol_events','actions',
        'objections_closed','new_independent_review_required','scientific_acceptance'])
    if type(response['schema_version']) is not int or response['schema_version']!=1 or response['objections_closed'] is not False or response['new_independent_review_required'] is not True or response['scientific_acceptance'] is not False:
        raise ValueError('claim response cannot grant scientific acceptance')
    if mw._canon(response['prior_package'],base,{})!=mw._canon(loaded['request']['revision']['previous_package'],base,{}):
        raise ValueError('scientific claim response changed original prior package')
    current=mw.verify_actions(response['action_plan'],base_dir=base,campaign=oldbinding['campaign'])
    events=mw._material_actions_complete(current)
    if response['actions']!=current['plan']['actions'] or response['actual_protocol_events']!=events:
        raise ValueError('planned-claim science lacks complete actual current protocol response')
    replacement=mw._read(response['replacement_request'],base)
    replacement_base=integrity._artifact_path(response['replacement_request'],base).parent
    if mw._bound_record({k:v for k,v in replacement.items() if k!='source_manifest'},replacement_base)!=mw._bound_record({k:v for k,v in loaded['request'].items() if k!='source_manifest'},base):
        raise ValueError('changed planned-claim writer differs from actual prepared scientific replacement')
    previous_loaded=current['loaded']
    for kind in ('methods','citations','figures','evidence'):
        if not set(previous_loaded[kind])<=set(loaded[kind]):raise ValueError('planned successor dropped original scientific population')
    oldslots=previous_loaded['quantitative_report'].get('expected_slots',{})
    newslots=loaded['quantitative_report'].get('expected_slots',{})
    if not oldslots.keys()<=newslots.keys() or any(ce.digest({k:v for k,v in s.items() if k!='value'})!=ce.digest({k:v for k,v in newslots[i].items() if k!='value'}) for i,s in oldslots.items()):
        raise ValueError('planned successor changed original quantitative scope/unit/population')
    material=any(r['kind'] in {'empirical','core-method'} for r in response['actions'])
    allowed={k:{i for r in response['actions'] for i in r['affected_manuscript'][k]} for k in ('method_ids','citation_ids','figure_ids')}
    for field,key in [('methods','method_ids'),('citations','citation_ids'),('figures','figure_ids')]:
        for old in previous_loaded['request'][field]:
            new=next(r for r in loaded['request'][field] if r['id']==old['id'])
            if (not material and field=='methods') or old['id'] not in allowed[key]:
                if mw._bound_record(old,previous_loaded['source_base'])!=mw._bound_record(new,base):raise ValueError('unaffected planned scientific source changed')
    if not material:
        # A located new primary citation and the action-response lineage can be
        # added without pretending an empirical experiment occurred. Every old
        # scientific source and the current quantity population remain exact.
        sources={k:v for k,v in after['sources'].items() if v['located']['value']!=response}
        if any(sources.get(k)!=v for k,v in before['sources'].items()) or before['current_quantities']!=after['current_quantities']:
            raise ValueError('editorial response cannot requalify changed empirical source/quantity')
        citation_sources={ce.digest(mw._bound_record(e['located'],base)) for c in loaded['request']['citations'] if c['id'] in allowed['citation_ids'] for e in c['identity_evidence'] if e['source_role']=='primary-paper'}
        if any(ce.digest(v['located']) not in citation_sources for k,v in sources.items() if k not in before['sources']):
            raise ValueError('nonmaterial new source must be the affected located primary citation')
    changed={i for i in previous_loaded['methods'] if mw._method_semantics(next(r for r in previous_loaded['request']['methods'] if r['id']==i),previous_loaded['source_base'])!=mw._method_semantics(next(r for r in loaded['request']['methods'] if r['id']==i),base)}
    changed.update(set(loaded['methods'])-set(previous_loaded['methods']))
    core={i for r in response['actions'] if r['kind']=='core-method' for i in r['affected_manuscript']['method_ids']}
    if not changed<=core:raise ValueError('changed planned method requires full core-method requalification')
    if material:
        # The same actual linked replacement observation law used by the
        # ordinary successor producer also applies to a direct improver.
        from . import research_protocol as rp, research_cycle as cycle
        state=current['state'];bound=rp._bound(state)
        stage_ids={i for e in events if e['action']=='resolve_objections' for i in e['replacement_stage_ids']}
        experiments={r['experiment_id'] for s in bound[0]['stages'] if s['id'] in stage_ids for r in s['cells']}|{i for r in response['actions'] for i in r['required_experiment_ids']}
        actual=[e for e in state['experiments'] if e['id'] in experiments]
        for e in actual:cycle._current_evidence(state,e,accepted=True)
        receipts={(str(integrity._artifact_path(e['observation']['receipt'],state['base_dir'])),e['observation']['receipt']['sha256']) for e in actual}
        for mid in core|changed:
            for op in loaded['methods'][mid]['presented_operations']:
                if op['execution_evidence']['state']!='current_successful_stage' or (str(integrity._artifact_path(op['execution']['receipt'],base)),op['execution']['receipt']['sha256']) not in receipts:
                    raise ValueError('changed planned method lacks the linked current replacement observation')
    if mw.cycle._load(oldbinding['campaign'])[1]!=current['state']:raise ValueError('claim response campaign changed during observation')
    for pin in [response['replacement_request'],*current['input_pins']]:integrity._dependency(pin,base,{})


def _claim_census(binding,loaded,value,context):
    from . import manuscript_claim_disposition
    for original in context['plan']['claim_map']:
        if not set(original['method_ids'])<=set(loaded['methods']) or not set(original['citation_ids'])<=set(loaded['citations']) or not set(original['quantity_ids'])<=set(loaded['quantitative_report'].get('expected_slots',{})):
            raise ValueError('final planned claim dropped original method/citation/quantity population')
    rows=manuscript_claim_disposition.validate(context['plan'],value.get('claim_dispositions'),value,
        loaded['evidence'],final=True,figures=loaded['figures'])
    return {'schema_version':1,'kind':'actual-planned-manuscript-claim-census',
        'author_binding':_pin(Path(binding['graph']).parent/'binding.json'),
        'plan':deepcopy(context['plan']),'phase_censuses':deepcopy(context['phase_censuses']),
        'original_evidence':deepcopy(context['original_evidence']),'original_missing':deepcopy(context['original_missing']),
        'source_bindings':deepcopy(context['source_bindings']),'current_input_pins':deepcopy(loaded['input_pins']),
        'rows':rows,'paragraphs':deepcopy(value['paragraphs']),'figures':deepcopy(value['figures']),
        'independent_review_required':True,'scientific_acceptance':False}


def _presentation(loaded):
    request=loaded['request']
    return {'kind':'manuscript-author-source-context','original_task':loaded['documents']['original_task'],
        'profile':request['profile'],'sources':loaded['evidence'],'methods':loaded['methods'],'citations':loaded['citations'],
        'figures':loaded['figures'],'current_quantities':loaded['quantitative_report'],'environment':loaded['documents']['environment'],
        'code':loaded['documents']['code_manifest'],'skills':loaded['skills'],'formatting':loaded['formatting'],'template_source':loaded['template'],'challenge':loaded['challenge'],'revision':loaded['revision'],
        'blinding_census':_blinding_census(loaded,Path(loaded['source_base'])) if request.get('blinding_policy') is not None else None,
        **({'writer_accounting_policy':_writer_policy(request['runtime'])} if any(k in request['runtime'] for k in ('usage_policy','max_output_bytes')) else {})}


def _blinding_census(loaded,base):
    """Source-derived complete partition. Data is never promoted by a caller label.

    The original request's located primary citation sources are separately
    presented public-support candidates; actual independent judgments still
    decide that applicability. No classification here establishes noninterference.
    """
    request=loaded['request'];pins={p['path']:deepcopy(p) for p in loaded['input_pins']}
    def names(rows):return {str(integrity._artifact_path(p,base)) for p in rows}
    machine=names(loaded['documents']['code_manifest']['files']+request['skills']+loaded['documents']['environment']['assets'])
    for method in request['methods']:
        for operation in method['operations']:machine.update(names(e['artifact'] for e in operation['code']))
    primary=names(e['located']['artifact'] for c in request['citations'] for e in c['identity_evidence']
        if e['source_role'] in {'primary-paper','author-repository','publisher-metadata'})
    custody_only=set()
    data=set()
    data.update(names(e['located']['artifact'] for e in loaded['documents']['source_manifest']['evidence'])-primary)
    for method in request['methods']:
        for operation in method['operations']:
            data.update(names(e['artifact'] for e in operation['results']))
            snapshot={}
            integrity._executed(operation['execution'],operation['code'],operation['results'],base,snapshot)
            custody_only.update(snapshot)
    for f in request['figures']:
        data.update(names([f['image'],f['contract'],*([] if f['comparison'] is None else f['comparison'].values())]))
    report_base=integrity._artifact_path(request['quantitative_report'],base).parent
    data.update(str(integrity._artifact_path(p,report_base)) for p in scientific_report.input_pins(loaded['documents']['quantitative_report'],base_dir=report_base)
        if not integrity._artifact_path(p,report_base).is_relative_to(Path(__file__).resolve().parents[1]))
    # A value also used analytically always remains data, even if repeated in code/metadata.
    machine-=data;custody_only-=data|machine|primary;support=set(pins)-data-machine-custody_only
    if not (data|machine|custody_only)<=set(pins):raise ValueError('complete author blinding census lost a consumed source')
    policy={**request['blinding_policy'],'path':str(integrity._artifact_path(request['blinding_policy'],base))}
    return {'policy':policy,'data':[pins[x] for x in sorted(data)],'support':[pins[x] for x in sorted(support)],
        'machinery':[pins[x] for x in sorted(machine)],'custody_only':[pins[x] for x in sorted(custody_only)],'complete_inputs':[pins[x] for x in sorted(pins)],
        'limit':'Exact source-derived dataflow plus actual reviewed support/machinery scope; no hash-based secrecy, arbitrary safe pins or noninterference proof.'}


def _artifact_context(context_transport):
    if context_transport is None:return False  # exact historical inline contract
    if context_transport!='source-artifact-v1':raise ValueError('unknown manuscript context transport')
    return True


def _context_bound(runtime,instructions,presentation,request,base,*,context_transport=None):
    # Keep historical verification exact. New preparations count both complete
    # actual input texts and instructions, never just short role instructions.
    size=len(instructions.encode())
    if _artifact_context(context_transport):
        for pin in (presentation,request):
            if type(pin.get('size')) is not int or pin['size']<1:raise ValueError('bounded complete context input required')
            size+=pin['size']
        if size>runtime['max_context_bytes']:raise ValueError('whole author context exceeds explicit bound; no truncation')
        actual=sum(len(integrity._raw(pin,base,{})) for pin in (presentation,request))+len(instructions.encode())
        if actual!=size:raise ValueError('complete context input size differs')
    if size>runtime['max_context_bytes']:raise ValueError('whole author context exceeds explicit bound; no truncation')
    return size


def _instructions(request,presentation,*,context_transport=None):
    artifact=_artifact_context(context_transport)
    return ('Declared writer actor '+request['author_id']+'. Write the requested complete scientific note from the exact public evidence below. Preserve unknowns, failures, scope and competing explanations. '
        'No invented quantities, citations, efficiencies or method execution. Include every used method exactly once as a kind=method paragraph with one method_id. '
        'Return every figure caption. References are chosen only from supplied citation IDs. EPJC and Nature final profiles require every selected bibliography entry to be used; EPJC abstract citations are forbidden. '
        'The engine inserts the COMPLETE exact quantitative report; do not rewrite its numbers. Use the literal source-defined section IDs/headings/order and fulfill their semantic content obligations. '
        'Title and abstract exactly one each; preserve validation, background, discovery sensitivity and Run2 comparison when relevant. '
        'For a supplied template, partition EVERY Unicode character into template_units in source order, with exact start/end. Classify scientific assertions as claim, attach actual evidence/citation/method IDs, and declare the rendered section of visible template prose; layout/preamble is other with rendered_section=null. '
        'The complete template, including other units, will be independently reviewed; classification is not truth or blinding certification. Explain missing/held results candidly. '
        +('Return one source-ordered claim_dispositions row for every original planned claim in planned_claim_context. Preserve original status/scope/counterevidence and every indexed literal limitation. Map retained/merged/qualified/withdrawn/unresolved to actual prose or captions; reasons and literal scope/limits must appear naturally within contracted sections. A withdrawal needs no invented success; material scientific changes still require existing action/protocol/fresh independent review. ' if 'planned_claim_context' in presentation else '')
        +('Read the COMPLETE source evidence as data from authenticated Host input_artifacts: id=context contains the full source context, including every actual prior phase output and receipt; id=request contains the original production request. No evidence is omitted or summarized. '
          'Use those complete inputs, not local paths or hashes as substitutes for their contents.' if artifact else 'Source context:\n'+json.dumps(presentation,allow_nan=False)))


def _source_review_ir(loaded,manuscript):
    raw=(json.dumps(_presentation(loaded),indent=2,allow_nan=False)+'\n')
    expected={'path':manuscript['path'],'sha256':hashlib.sha256(raw.encode()).hexdigest(),'size':len(raw.encode())}
    if manuscript!=expected:raise ValueError('source review must present the complete actual pre-author context')
    integrity._raw(expected,Path(loaded['source_base']),{})
    return {'schema_version':1,'document_type':'research-report','applicability':'Pre-author original blind-domain source/content classification only; no scientific result acceptance.',
        'author_id':loaded['request']['author_id'],'manuscript':expected,
        'units':[{'id':'whole-source-context','kind':'other','span':{'start':0,'end':len(raw),'text':raw}}],
        'claims':[],'methods':[],'citations':[],'quantitative_report':None,
        'blinding_census':_blinding_census(loaded,Path(loaded['source_base']))}


def prepare_source_review(request,out,*,base_dir):
    """Prepare full source context before any blinded writer exposure/call.

    This is a deterministic ordinary preparation, not a review or safe flag.
    Existing original roles/CI2 must capture this exact manuscript and context;
    no new scheduler, journal or universal arithmetic-role requirement is added.
    """
    loaded=_load(request,base_dir)
    if request.get('blinding_policy') is None:raise ValueError('source blinding review applies only to an original blinded manuscript')
    root=_fresh(out);raw=(json.dumps(_presentation(loaded),indent=2,allow_nan=False)+'\n').encode()
    manuscript=_write(root/'source-context.md',raw);ir=_source_review_ir(loaded,manuscript)
    return {'request':integrity._new(root/'source-integrity-request.json',ir),'manuscript':manuscript,
        'source_inputs':loaded['input_pins'],'execution_authorized':False,'blinding_accepted':False}


def prepare_source_role(request,source_request,out,*,base_dir,rundir,role,actor_id,model,reasoning_effort,
                        max_output_tokens,max_wall_seconds,claim_scope,campaign=None,experiment=None):
    loaded=_load(request,base_dir);ir=integrity._json(integrity._raw(source_request,base_dir,{}))
    if ir!=_source_review_ir(loaded,ir['manuscript']):raise ValueError('source role cannot omit the actual complete writer inputs/policy')
    return integrity.prepare_role(ir,out,base_dir=base_dir,rundir=rundir,role=role,actor_id=actor_id,
        model=model,reasoning_effort=reasoning_effort,max_output_tokens=max_output_tokens,max_wall_seconds=max_wall_seconds,
        claim_scope=claim_scope,campaign=campaign,experiment=experiment)


def consume_source_role(request,source_request,binding,*,base_dir):
    loaded=_load(request,base_dir);ir=integrity._json(integrity._raw(source_request,base_dir,{}))
    if ir!=_source_review_ir(loaded,ir['manuscript']):raise ValueError('source feedback belongs to another writer context')
    return integrity.consume_role(ir,binding,base_dir=base_dir)


def _check_source_review(loaded):
    request=loaded['request']
    if request.get('blinding_policy') is None:return None
    binding=request.get('source_review')
    if binding is None:raise ValueError('blinded writer support/template/machinery needs actual pre-author original-role source review')
    ce.keys(binding,['request','bindings']);base=Path(loaded['source_base'])
    ir=integrity._json(integrity._raw(binding['request'],base,{}))
    if ir!=_source_review_ir(loaded,ir['manuscript']):raise ValueError('pre-author source review is not about the exact current complete context')
    assessment=integrity.assess(ir,binding['bindings'],base_dir=base)
    if not assessment['scoped_integrity_review_complete']:raise ValueError('pre-author blind-domain source review remains unresolved')
    for pin in integrity.assessment_pins(ir,binding['bindings'],base_dir=base):integrity._dependency(pin,base,{})
    return assessment


def execute_writer(binding, host):
    """The one charged model step; coordinator invokes outside its campaign lock."""
    from . import research_cycle
    loaded=_load(integrity._json(integrity._raw(binding['request'],Path.cwd(),{})),binding['base_dir'])
    _revision_campaign(loaded,binding['campaign'])
    _,state=research_cycle._load(binding['campaign'])
    q=loaded['documents']['quantitative_report']
    if scientific_report._context(q['context'],integrity._artifact_path(loaded['request']['quantitative_report'],loaded['source_base']).parent)!=state['context']:
        raise ValueError('writer cannot dispatch with stale research quantities')
    if state.get('parent_task') is not None and state['parent_task']['original_request']!=loaded['documents']['original_task']:
        raise ValueError('writer dispatch changed original parent task')
    if loaded['input_pins']!=binding['input_pins'] or state_io.read_json(Path(binding['graph'])/agent_graph.SPEC)!=binding['spec']:
        raise ValueError('writer binding/spec/evidence changed')
    _context_bound(loaded['request']['runtime'],binding['spec']['nodes'][0]['parameters']['instructions'],
        binding['presentation'],binding['request'],binding['base_dir'],context_transport=binding.get('context_transport'))
    return research_cycle.execute_graph(binding['campaign'],binding['graph'],binding['spec'],host,prepared=True)


def _tex(text):
    mapping={'\\':r'\textbackslash{}','{':r'\{','}':r'\}','%':r'\%','$':r'\$','&':r'\&','#':r'\#','_':r'\_','^':r'\textasciicircum{}','~':r'\textasciitilde{}'}
    return ''.join(mapping.get(c,c) for c in text)


def _author_state(binding,*,_origin=None):
    """Current actual accounted call and original complete evidence, not saved assertions."""
    base=Path(binding['base_dir']); request=integrity._json(integrity._raw(binding['request'],base,{})); loaded=_load(request,base)
    _revision_campaign(loaded,binding['campaign'])
    _check_source_review(loaded)
    if loaded['input_pins']!=binding['input_pins']: raise ValueError('author dependencies differ from prepared request')
    from . import research_cycle
    current=research_cycle._load(binding['campaign'])[1]
    if _origin is not None:
        q=loaded['documents']['quantitative_report']
        current=_origin_campaign(_origin,campaign=binding['campaign'],prepared_sha256=binding['research_state_sha256'],
            graph_root=binding['graph'],graph_spec=binding['spec'],checkpoint=agent_graph.status(binding['graph']),
            quantitative_context=scientific_report._context(q['context'],integrity._artifact_path(request['quantitative_report'],base).parent))
    if current['sha256'] == binding['research_state_sha256']:
        # prepare was pure; actual dispatch must charge the campaign and change it.
        raise ValueError('writer has no charged research dispatch')
    presentation=integrity._json(integrity._raw(binding['presentation'],base,{}))
    if presentation!=_production_presentation(loaded,binding.get('stages'),binding['campaign'],_origin=_origin):raise ValueError('writer presentation is not the complete actual source context')
    runtime=request['runtime'];nodes=binding['spec']['nodes'];parameters=nodes[0]['parameters']
    role='improver' if request['revision'] else 'proposer'
    packet=binding.get('packet')
    visual_loaded=_synthesis_visual_scope(loaded,binding.get('stages'),binding['campaign'],_origin=_origin)
    expected_parameters={'instructions':_instructions(request,presentation,context_transport=binding.get('context_transport')),'model':runtime['model'],'reasoning_effort':runtime['reasoning_effort'],
        'max_output_tokens':runtime['max_output_tokens'],'output_schema':output_schema(loaded['formatting'],has_template=loaded['template'] is not None,planned_claims=_has_claim_plan(loaded,binding.get('stages'))),
        **_writer_completion_parameters(runtime),**_author_visual_parameters(visual_loaded,packet,role)}
    _context_bound(runtime,expected_parameters['instructions'],binding['presentation'],binding['request'],base,
        context_transport=binding.get('context_transport'))
    expected_node={'id':'author','kind':'model','role':'improver' if request['revision'] else 'proposer','depends_on':[],
        'inputs':[{'id':'context','path':binding['presentation']['path'],'sha256':binding['presentation']['sha256']},
                  {'id':'request','path':binding['request']['path'],'sha256':binding['request']['sha256']}],
        'packet':packet,'action':runtime['action'],'parameters':expected_parameters,'max_attempts':1}
    expected_budget={'max_nodes':1,'max_calls':1,'max_output_tokens':runtime['max_output_tokens'],'max_wall_seconds':runtime['max_wall_seconds'],'max_reworks':0}
    if nodes!=[expected_node] or binding['spec']['budget']!=expected_budget:
        raise ValueError('actual writer prompt/schema differs from source-defined production')
    role='improver' if request['revision'] else 'proposer'
    receipt=agent_graph.role_receipt(binding['graph'],'author',expected_subject_sha256=binding['presentation']['sha256'],require_exact_subject=True,expected_packet_sha256=packet['manifest_sha256'] if packet else None,allowed_roles={role})
    if receipt['execution_observation'] in {'control_only','unestablished'}: raise ValueError('control transport cannot author a claimed actual research note')
    _verify_author_vision(receipt,visual_loaded,packet,'author',role)
    checkpoint=agent_graph.status(binding['graph'])
    if state_io.read_json(Path(binding['graph'])/agent_graph.SPEC)!=binding['spec']: raise ValueError('actual author graph differs from retained full prompt')
    quantitative=loaded['documents']['quantitative_report']
    if _origin is None:current=research_cycle._load(binding['campaign'])[1]
    if scientific_report._context(quantitative['context'],integrity._artifact_path(request['quantitative_report'],base).parent)!=current['context']:
        raise ValueError('research quantities changed during note authoring')
    if not any(row['root']==binding['graph'] and row.get('complete') for row in current['graphs']): raise ValueError('accounted author graph is not a completed campaign step')
    saved=agent_graph._result(Path(binding['graph']),checkpoint['nodes']['author']['result'])
    usage=saved['result']['usage']; transport=saved['result']['transport']
    if transport.get('observed_model')!=request['runtime']['model_build']:
        raise ValueError('actual model build unavailable or differs; cannot replace with requested alias')
    if request['runtime']['action']=='external' and transport.get('actor_id')!=request['author_id']:
        raise ValueError('actual external writer actor differs from declared author binding')
    calls=[]
    for ref in saved['call_receipts']:
        call_path=Path(binding['graph'])/'calls'/(ref['call_id']+'.json'); call=state_io.read_json(call_path)
        if ce.digest(call)!=ref['sha256']: raise ValueError('actual call changed')
        calls.append({'pin':_pin(call_path),'receipt':call})
    _writer_accounting(runtime,receipt,saved,checkpoint,calls)
    if _origin is not None:_origin.close()
    return loaded,receipt,saved,checkpoint,calls


def collect(binding, out):
    loaded,receipt,saved,checkpoint,calls=_author_state(binding)
    return _materialize(binding,loaded,receipt,saved,checkpoint,calls,out,write=True)


def _materialize(binding,loaded,receipt,saved,checkpoint,calls,out,*,write,consumed=None,_origin=None):
    """Reproducible exact bytes from the actual writer; verification performs no writes."""
    if _origin is not None and write:raise ValueError('historical origin cannot materialize a new manuscript')
    base=Path(binding['base_dir']);request=loaded['request']
    consumed={} if consumed is None else consumed
    emissions={}
    root=_fresh(out) if write else Path(out).absolute()
    def emit(path,raw):
        raw=bytes(raw);expected={'path':str(Path(path).absolute()),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
        if write:_write(path,raw)
        integrity._raw(expected,base,consumed);emissions[str(path)]=expected
        return expected
    def emit_json(path,value):return emit(path,(json.dumps(value,indent=2,allow_nan=False)+'\n').encode())
    usage=saved['result']['usage'];transport=saved['result']['transport']
    value=deepcopy(receipt['public_value']); from .agent_host import validate_public_result
    validate_public_result(value,output_schema(loaded['formatting'],has_template=loaded['template'] is not None,planned_claims=_has_claim_plan(loaded,binding.get('stages'))))
    claim_context=None
    if _has_claim_plan(loaded,binding.get('stages')):
        presented=integrity._json(integrity._raw(binding['presentation'],loaded['source_base'],consumed))
        claim_context=presented['planned_claim_context']
        claim_census=_claim_census(binding,loaded,value,claim_context)
    paragraphs=value['paragraphs']; ids=[p['id'] for p in paragraphs]
    if len(set(ids))!=len(ids): raise ValueError('duplicate manuscript paragraph')
    layout=manuscript_format.section_layout(loaded['formatting']);section_rows={r['id']:r for r in layout}
    semantic_counts={role:sum(role in section_rows[p['section']]['semantics'] for p in paragraphs) for role in manuscript_format.SEMANTICS}
    note_rules=manuscript_format.note_requirements(loaded['formatting'],loaded['source_base']);required=note_rules['required']
    if any(not semantic_counts[r] for r in required) or semantic_counts['title']!=1 or semantic_counts['abstract']!=1:raise ValueError('whole requested note semantic content missing')
    if any(not any(role in section_rows[p['section']]['semantics'] and section_rows[p['section']]['placement']=='main' for p in paragraphs) for role in note_rules['main_text']):raise ValueError('rule-pack main-text content cannot move into an appendix')
    order=[x for r in loaded['formatting']['rules'] if r['kind']=='section_order' for x in r['value']]
    if order:paragraphs.sort(key=lambda p:order.index(p['section']) if p['section'] in order else len(order)+list(section_rows).index(p['section']))
    if request['profile']=='epjc' and any(p['citation_ids'] for p in paragraphs if 'abstract' in section_rows[p['section']]['semantics']):
        raise ValueError('EPJC abstract must not contain unspecified reference citations')
    seen_methods=[]; fig_ids=[f['id'] for f in value['figures']]
    if len(set(fig_ids))!=len(fig_ids) or set(fig_ids)!=set(loaded['figures']): raise ValueError('complete figure population required')
    units=[]; claims=[]; methods=[]; citations=deepcopy(request['citations']); text='';
    render=loaded['formatting']['render'];post=render['post_reference_sections']
    front_roles=['title','authors','affiliations','abstract']
    front_order=[r['id'] for role in front_roles for r in layout if role in r['semantics']]
    citation_front=[p for section in front_order for p in paragraphs if p['section']==section]
    citation_main=[p for p in paragraphs if p['section'] not in set(front_order) and section_rows[p['section']]['placement']=='main']
    citation_post=[p for section in post for p in paragraphs if p['section']==section]
    citation_appendix=[p for p in paragraphs if section_rows[p['section']]['placement']=='appendix']
    template_before=[];template_after=[]
    if loaded['template'] is not None:
        body_at=loaded['template'].index('%RAVEL_BODY%')
        template_before=[{**t,'section':t['rendered_section']} for t in value['template_units'] if t['end']<=body_at]
        template_after=[{**t,'section':t['rendered_section']} for t in value['template_units'] if t['start']>=body_at+len('%RAVEL_BODY%')]
    actual_order=[*template_before,*citation_front,*citation_main,
        *(citation_appendix if render['appendices']=='before-references' else []),
        *value['figures'],*citation_post,
        *(citation_appendix if render['appendices']=='after-references' else []),*template_after]
    citation_order=[];first_section={}
    for row in actual_order:
        for cid in row['citation_ids']:
            if cid not in citation_order:
                citation_order.append(cid);first_section[cid]=row.get('section','figure-legend')
    citation_order.extend(c['id'] for c in citations if c['id'] not in citation_order)
    if (request['profile']=='epjc' or (request['profile']=='nature' and loaded['formatting']['stage']=='final')) and any(c['id'] not in first_section for c in citations):
        raise ValueError('selected native bibliography contains uncited entries; revise the actual bibliography/author request')
    citations.sort(key=lambda c:citation_order.index(c['id']))
    numbers={cid:str(i+1) for i,cid in enumerate(citation_order)}
    def marker(cid):
        if render['citation_style']=='author-year':return '('+loaded['citations'][cid]['bibliography']['authors'][0]+', '+loaded['citations'][cid]['bibliography']['year']+')'
        return '['+numbers[cid]+']'
    def tex_citations(ids):
        if not ids:return ''
        if render['citation_style']=='numeric-superscript':return r'\textsuperscript{'+','.join(numbers[c] for c in ids)+'}'
        return ''.join(' '+_tex(marker(c)) for c in ids)
    value['citations']=citations;value['citation_style']='author-year' if render['citation_style']=='author-year' else 'numeric-appearance';value['quantitative_text']=loaded['quantitative_report']['report_text']
    if loaded['template'] is not None:
        cursor=0;visible=[]
        for row in value['template_units']:
            if type(row['start']) is not int or type(row['end']) is not int or row['start']!=cursor or not cursor<row['end']<=len(loaded['template']):raise ValueError('complete source template partition required before formatting counts')
            cursor=row['end']
            if row['rendered_section'] is not None:visible.append({'section':row['rendered_section'],'text':loaded['template'][row['start']:row['end']]})
        if cursor!=len(loaded['template']):raise ValueError('supplied template word/prose population incomplete')
        value['template_visible_text']=visible
    formatting=manuscript_format.assess(loaded['formatting'],value,template=request['template'])
    if formatting['mechanical_failures']:raise ValueError('author violated literal formatting constraints: '+','.join(formatting['mechanical_failures']))
    occurrences={c['id']:[] for c in citations}; tex=[];front={};appendices=[];legends=[];post_sections={}
    render=loaded['formatting']['render'];page_segments=[]
    def segment(identity,raw,section=None,*,counted=None):
        identity='ravel-segment-'+str(len(page_segments));start=identity+'-start';end=identity+'-end'
        counted=manuscript_format.counted(loaded['formatting'],section,'pages') if counted is None else counted
        page_segments.append({'id':identity,'section':section,'start':start,'end':end,'counted':counted})
        return r'\zlabel{'+start+'}'+raw+r'\zlabel{'+end+'}'
    def append(identity,kind,raw):
        nonlocal text
        start=len(text);text+=raw
        units.append({'id':identity,'kind':kind,'span':{'start':start,'end':len(text),'text':raw}})
        return units[-1]['span']
    for p in paragraphs:
        ce.identity(p['id'])
        if not set(p['evidence_ids'])<=set(loaded['evidence']) or not set(p['citation_ids'])<=set(loaded['citations']): raise ValueError('author invented source or citation')
        if p['kind']=='method':
            if len(p['method_ids'])!=1 or p['method_ids'][0] not in loaded['methods']: raise ValueError('one exact method owner required')
            mid=p['method_ids'][0];seen_methods.append(mid);method=deepcopy(loaded['methods'][mid]);method.pop('presented_operations')
            methods.append({**method,'unit_ids':[p['id']],'description':p['text']})
        elif not set(p['method_ids'])<=set(loaded['methods']): raise ValueError('invented method reference')
        body=p['text']+''.join(' '+marker(c) for c in p['citation_ids'])
        texbody=_tex(p['text'])+tex_citations(p['citation_ids'])
        raw=('\n# '+section_rows[p['section']]['heading']+'\n\n'+body+'\n\n');span=append(p['id'],p['kind'],raw)
        for c in p['citation_ids']:
            token=marker(c);offset=len('\n# '+section_rows[p['section']]['heading']+'\n\n')+len(p['text'])+sum(len(' '+marker(x)) for x in p['citation_ids'][:p['citation_ids'].index(c)])+1
            start=span['start']+offset;occurrences[c].append({'unit_id':p['id'],'span':{'start':start,'end':start+len(token),'text':token}})
        if p['kind']=='claim':claims.append({'id':p['id'],'unit_ids':[p['id']],'statement':p['text'],
            'evidence':[loaded['evidence'][e]['located'] for e in p['evidence_ids']],'citation_ids':p['citation_ids'],'method_ids':p['method_ids'],'uncertainties':p['uncertainties']})
        roles=set(section_rows[p['section']]['semantics'])&set(front_roles)
        if roles:
            if len(roles)!=1:raise ValueError('frontmatter content needs one exact native role')
            front.setdefault(next(iter(roles)),[]).append({'text':body,'latex':segment(p['id'],texbody,p['section'])})
        else:
            rendered=(r'\section{' if request['profile']=='epjc' else r'\section*{')+_tex(section_rows[p['section']]['heading'])+'}\n'+texbody+'\n'
            rendered=segment(p['id'],rendered,p['section'])
            if section_rows[p['section']]['placement']=='appendix':appendices.append(rendered)
            elif section_rows[p['section']]['placement']=='post-references':post_sections.setdefault(p['section'],[]).append(rendered)
            else:tex.append(rendered)
    if len(seen_methods)!=len(set(seen_methods)) or set(seen_methods)!=set(loaded['methods']): raise ValueError('used method population silently omitted/duplicated')
    quantitative=loaded['quantitative_report']['report_text'];qspan=append('quantitative','other',quantitative)
    quantitative_tex=r'\section*{Complete quantitative report}\begingroup\small\ttfamily'+'\n'+'\n'.join(_tex(line)+r'\par' for line in quantitative.splitlines())+r'\endgroup'
    (appendices if render['quantitative_position']=='appendix' else tex).append(segment('quantitative',quantitative_tex,counted=render['quantitative_position']=='main'))
    assets=[]
    for f in value['figures']:
        original=loaded['figures'][f['id']]; pin=original['image']; path=integrity._artifact_path(pin,base)
        filename='figure-'+f['id']+path.suffix.lower();assets.append(emit(root/filename,integrity._raw(pin,base,{})))
        unit='figure-'+f['id'];raw='\nFigure '+f['id']+': '+f['caption']+''.join(' '+marker(c) for c in f['citation_ids'])+'\n\n';span=append(unit,'claim',raw)
        if not set(f['citation_ids'])<=set(loaded['citations']): raise ValueError('invented figure citation')
        for c in f['citation_ids']:
            token=marker(c);offset=len('\nFigure '+f['id']+': ')+len(f['caption'])+sum(len(' '+marker(x)) for x in f['citation_ids'][:f['citation_ids'].index(c)])+1
            start=span['start']+offset;occurrences[c].append({'unit_id':unit,'span':{'start':start,'end':start+len(token),'text':token}})
        claims.append({'id':unit,'unit_ids':[unit],'statement':f['caption'],'evidence':[loaded['evidence'][e]['located'] for e in original['evidence_ids']],
            'citation_ids':f['citation_ids'],'method_ids':[],'uncertainties':f['uncertainties']})
        tex_filename='figure-'+f['id']+'.pdf' if path.suffix.lower()=='.svg' else filename
        if render['graphics']=='inline':
            tex.append(r'\begin{figure}[htbp]'+segment(unit,r'\centering\includegraphics[width=.92\linewidth]{'+tex_filename+r'}\caption{'+(_tex(f['caption'])+tex_citations(f['citation_ids']))+r'}',counted=True)+r'\end{figure}')
        else:legends.append(segment(unit,r'\paragraph{Figure '+_tex(f['id'])+'}'+(_tex(f['caption'])+tex_citations(f['citation_ids'])),counted=True))
    if appendices and render['appendices']=='none':raise ValueError('appendix violates supplied formatting contract')
    if appendices and render['appendices']=='before-references':tex.extend([r'\clearpage\zlabel{ravel-appendix-start}\appendix',*appendices])
    reference_tex=[r'\clearpage\zlabel{ravel-reference-start}\section*{References}']
    method_only=set(c['id'] for c in citations if 'methods' in section_rows.get(first_section.get(c['id']),{}).get('semantics',[])) if request['profile']=='nature' and loaded['formatting']['stage']=='final' else set()
    method_reference_tex=[]
    for c in citations:
        bib=c['bibliography'];raw='\n'+(marker(c['id']) if render['citation_style']=='author-year' else '['+numbers[c['id']]+']')+' '+bib['title']+'. '+', '.join(bib['authors'])+'. '+bib['year']+'. '+', '.join(bib['identifiers'])+'\n'
        c['reference_unit']='ref-'+c['id'];c['occurrences']=occurrences[c['id']];append(c['reference_unit'],'reference',raw)
        (method_reference_tex if c['id'] in method_only else reference_tex).append(_tex(raw)+'\n\n')
    tex.append(segment('references','\n'.join(reference_tex),counted=False))
    # The supplied template is part of the delivered scientific prose census.
    if loaded['template'] is not None:
        template_units=value['template_units'];cursor=0
        if len(template_units)+len(paragraphs)>MAX_PARAGRAPHS:raise ValueError('complete author/template census exceeds the declared finite envelope')
        for t in template_units:
            ce.identity(t['id'])
            if t['id'] in ids or t['id'] in {u['id'] for u in units}:raise ValueError('template census unit identity collides')
            if type(t['start']) is not int or type(t['end']) is not int or t['start']!=cursor or not cursor<t['end']<=len(loaded['template']):raise ValueError('full exact template character partition required')
            cursor=t['end'];fragment=loaded['template'][t['start']:t['end']]
            if not set(t['evidence_ids'])<=set(loaded['evidence']) or not set(t['citation_ids'])<=set(loaded['citations']) or not set(t['method_ids'])<=set(loaded['methods']):raise ValueError('template invented source/method/citation')
            if t['kind']=='claim' and t['rendered_section'] is None:raise ValueError('template assertion needs an explicit physical section')
            raw='\nSupplied template source '+t['id']+':\n'+fragment+''.join(' '+marker(c) for c in t['citation_ids'])+'\n';span=append(t['id'],t['kind'],raw)
            for c in t['citation_ids']:
                token=marker(c);offset=len('\nSupplied template source '+t['id']+':\n')+len(fragment)+sum(len(' '+marker(x)) for x in t['citation_ids'][:t['citation_ids'].index(c)])+1
                at=span['start']+offset;occurrences[c].append({'unit_id':t['id'],'span':{'start':at,'end':at+len(token),'text':token}})
            if t['kind']=='claim':claims.append({'id':t['id'],'unit_ids':[t['id']],'statement':fragment,'evidence':[loaded['evidence'][e]['located'] for e in t['evidence_ids']], 'citation_ids':t['citation_ids'],'method_ids':t['method_ids'],'uncertainties':t['uncertainties']})
        if cursor!=len(loaded['template']):raise ValueError('template prose/layout census cannot omit any character')
    manuscript=emit(root/'manuscript.md',text.encode())
    # Template is portable house source. ATLAS visual style remains a separate required review, not a logo assertion.
    if legends:tex.extend([r'\section*{Figure legends}',*legends])
    for section in render['post_reference_sections']:
        tex.extend(post_sections.get(section,[]))
        if section=='code-availability' and method_reference_tex:tex.append(segment('methods-references',r'\section*{Methods references}'+'\n'+'\n'.join(method_reference_tex),counted=False))
    if appendices and render['appendices']=='after-references':tex.extend([r'\clearpage\zlabel{ravel-appendix-start}\appendix',*appendices])
    body='\n'.join(tex)
    native_template=manuscript_format.template_source(loaded['formatting'],loaded['template'])
    front_tex=manuscript_format.frontmatter(front,loaded['formatting'],escape=_tex)
    if loaded['template'] is not None:
        marker_at=loaded['template'].index('%RAVEL_BODY%')
        for side,edge,select in [('prefix','before',lambda u:u['end']<=marker_at),('suffix','after',lambda u:u['start']>=marker_at+len('%RAVEL_BODY%'))]:
            visible=[u for u in value['template_units'] if select(u) and u['rendered_section'] is not None]
            if visible:
                identity='ravel-template-'+side;count=any(manuscript_format.counted(loaded['formatting'],u['rendered_section'],'pages') for u in visible)
                page_segments.append({'id':identity,'section':'template-'+side,'start':identity+'-start','end':identity+'-end','counted':count})
                hook=r'\AtBeginDocument{\zlabel{'+identity+'-start}}' if side=='prefix' else r'\AtEndDocument{\zlabel{'+identity+'-end}}'
                native_template=hook+'\n'+native_template
                if side=='prefix':front_tex=r'\zlabel{'+identity+'-end}'+front_tex
                else:body+=r'\zlabel{'+identity+'-start}'
        if any(u['rendered_section'] is not None and u['start']<marker_at+len('%RAVEL_BODY%') and u['end']>marker_at for u in value['template_units']):raise ValueError('visible template unit must not straddle the generated body slot')
    latex=emit(root/'note.tex',native_template.replace('%RAVEL_BODY%',front_tex+'\n'+body).encode())
    def emit_template(target,raw):
        if write:
            if target.exists():raise ValueError('duplicate template/figure destination')
            target.parent.mkdir(parents=True,exist_ok=True)
        return emit(target,raw)
    template_assets=manuscript_assets.materialize(loaded['formatting']['template_assets'],base,root,emit_template)
    formatpin=emit_json(root/'formatting-assessment.json',formatting)
    ir={'schema_version':1,'document_type':'manuscript','applicability':request['profile'],'author_id':request['author_id'],
        'manuscript':manuscript,'units':units,'claims':claims,'methods':methods,'citations':citations,
        'quantitative_report':{'request':request['quantitative_report'],'span':qspan},
        'formatting':{'contract':request['formatting'],'assessment':formatpin,'template':request['template']}}
    if request.get('blinding_policy') is not None:ir['blinding_census']=_blinding_census(loaded,base)
    if claim_context is not None:ir['planned_claim_census']=emit_json(root/'planned-claim-census.json',claim_census)
    prepared=integrity.prepare(ir,base_dir=base,**({'_claim_origin':_origin} if _origin is not None else {})); irpin=emit_json(root/'integrity-request.json',ir)
    model_provenance={'exact_graph_spec':binding['spec'],'accounted_model_receipt':receipt,'call_receipts':calls,'usage':usage,
        'writer_accounting':_writer_accounting(request['runtime'],receipt,saved,checkpoint,calls),
        'requested_model_build':request['runtime']['model_build'],'observed_model_build':transport['observed_model'],
        'prompt_fully_retained':True,'prompt_timestamp_evidence':'exact ordinary Graph call receipts; no author-invented time',
        'graph_started_epoch':checkpoint['started_epoch'],'software_skills':request['skills'],'environment':request['environment'],'workflow_code':request['code_manifest']}
    if binding.get('stages') is not None:
        from . import manuscript_workflow
        transcript=manuscript_workflow.verify_transcript(binding['stages'],loaded,binding['campaign'],**({'_origin':_origin} if _origin is not None else {}))
        model_provenance['writing_transcript']=transcript
        model_provenance['final_synthesis_only']=True
    prov=emit_json(root/'model-provenance.json',model_provenance)
    package={'kind':'authored-manuscript-package','schema_version':1,'author_id':request['author_id'],'profile':request['profile'],
        'source_base':str(base.absolute()),'original_task':request['original_task'],'author_binding':_pin(Path(binding['graph']).parent/'binding.json'),'production_request':binding['request'],'integrity_request':irpin,'integrity_request_sha256':ce.digest(ir),
        'manuscript':manuscript,'latex':latex,'figures':assets,'template_assets':template_assets,'formatting_contract':request['formatting'],'formatting_assessment':formatting,'formatting_assessment_pin':formatpin,'model_provenance':prov,'input_pins':loaded['input_pins'],
        'template':request['template'],'page_segments':page_segments,'template_census':deepcopy(value.get('template_units',[])),'scientific_acceptance':False,'visual_style_accepted':False,'parent_task_accepted':False,'execution_authorized':False}
    if claim_context is not None:package['planned_claim_census']=ir['planned_claim_census']
    package_pin=emit_json(root/'package.json',package)
    if _load(request,base)!=loaded: raise ValueError('scientific source changed during note construction')
    if _author_state(binding,_origin=_origin)!=(loaded,receipt,saved,checkpoint,calls):
        raise ValueError('whole accounted writer completion changed during note construction')
    for pin in emissions.values():integrity._raw(pin,base,consumed)
    if _origin is not None:_origin.close()
    return {'package':package,'package_pin':package_pin,'integrity_preparation':prepared}


def prepare_build(package_pin, out, *, base_dir, runtime, review_policy, goal_binding, max_seconds=120, custody_limits=None, approval_mode='physicist'):
    """Ordinary preparation only; delegated/scripted approval remains separate.

    The normal proposal is physicist. Explicit engineering proposals may select
    scripted_yes; neither selection approves execution or establishes a human
    review. Autonomous decisions use the existing source-bound CI1 delegation.
    """
    from . import science
    if type(approval_mode) is not str or approval_mode not in ('physicist','scripted_yes'):
        raise ValueError('prepare_build requires the existing physicist or scripted_yes proposal mode')
    package=integrity._json(integrity._raw(package_pin,base_dir,{}));verify_author(package,base_dir=base_dir);root=_fresh(out)
    package_pin={**package_pin,'path':str(integrity._artifact_path(package_pin,base_dir))}
    config={'schema_version':1,'package':package_pin,'runtime':runtime,'max_seconds':max_seconds,
        'runtime_base':str(Path(base_dir).absolute()),'max_ram_mib':runtime['max_ram_mib'],'max_output_bytes':32*1024*1024,
        'max_main_pages':min([r['rule']['value'] for r in package['formatting_assessment']['rules'] if r['rule']['kind']=='max_main_pages'],default=None)}
    if runtime.get('schema_version')==2:
        config.update({'schema_version':2,'custody_limits':integrity.custody_limits(custody_limits)})
        config_pin=integrity._operational_new(root/'build-config.json',config,limits=config['custody_limits'])
    else:
        if custody_limits is not None:raise ValueError('operational policy requires explicit runtime/v2')
        config_pin=integrity._new(root/'build-config.json',config)
    spec={'schema_version':2,'mode':'manuscript-build','source':'Exact accounted authored manuscript and source-bound figures',
        'assumptions':['Portable article template; ATLAS style/scientific claims/visual comparison await actual independent review.'],
        'max_seconds':max_seconds,'approval_mode':approval_mode,'max_attempts':1,'review_policy':review_policy,
        'goal_binding':goal_binding,'task':{'config':config_pin['path']}}
    spec_pin=integrity._new(root/'science.json',spec)
    return {'specification':spec_pin,'ordinary_plan':science.plan(root/'ordinary',spec_pin['path']),
        'execution_authorized':False,'scientific_acceptance':False}


def prepare_integrity_role(package_pin,out,*,base_dir,rundir,role,actor_id,model,reasoning_effort,
                           max_output_tokens,max_wall_seconds,claim_scope,campaign=None,experiment=None):
    package=integrity._json(integrity._raw(package_pin,base_dir,{}))
    verify_author(package,base_dir=base_dir)
    request=integrity._json(integrity._raw(package['integrity_request'],base_dir,{}))
    return integrity.prepare_role(request,out,base_dir=Path(package['source_base']),rundir=rundir,role=role,actor_id=actor_id,
        model=model,reasoning_effort=reasoning_effort,max_output_tokens=max_output_tokens,
        max_wall_seconds=max_wall_seconds,claim_scope=claim_scope,campaign=campaign,experiment=experiment)


def consume_integrity_role(package_pin,binding,*,base_dir):
    package=integrity._json(integrity._raw(package_pin,base_dir,{}))
    verify_author(package,base_dir=base_dir)
    request=integrity._json(integrity._raw(package['integrity_request'],base_dir,{}))
    return integrity.consume_role(request,binding,base_dir=Path(package['source_base']))



def _verify_author(package,*,base_dir,consumed=None,_origin=None):
    """Authenticate the real producer transport again; never trust saved model metadata."""
    consumed={} if consumed is None else consumed
    binding=integrity._json(integrity._raw(package['author_binding'],base_dir,consumed))
    if package['production_request']!=binding['request']:raise ValueError('package changed actual author request')
    request=integrity._json(integrity._raw(binding['request'],base_dir,consumed));loaded=_load(request,binding['base_dir'])
    if package['input_pins']!=loaded['input_pins'] or binding['input_pins']!=loaded['input_pins']:raise ValueError('author source population changed')
    if state_io.read_json(Path(binding['graph'])/agent_graph.SPEC)!=binding['spec']:raise ValueError('author Graph changed')
    receipt=agent_graph.role_receipt(binding['graph'],'author',expected_subject_sha256=binding['presentation']['sha256'],
        require_exact_subject=True,allowed_roles={'improver' if request['revision'] else 'proposer'})
    if receipt['execution_observation'] in {'control_only','unestablished'}:raise ValueError('saved model metadata cannot replace actual author transport')
    if request['runtime']['action']=='external' and receipt['transport'].get('actor_id')!=request['author_id']:
        raise ValueError('current external writer actor differs from declared author binding')
    loaded,actual,saved,checkpoint,calls=_author_state(binding,_origin=_origin)
    if actual!=receipt:raise ValueError('author receipt changed during materialization verification')
    root=integrity._artifact_path(package['latex'],base_dir).parent
    expected=_materialize(binding,loaded,actual,saved,checkpoint,calls,root,write=False,consumed=consumed,_origin=_origin)
    if package!=expected['package']:raise ValueError('complete package differs from actual authored materialization')
    for pin in loaded['input_pins']:integrity._dependency(pin,base_dir,consumed)
    return receipt



def verify_author(package,*,base_dir,consumed=None):
    """Current author verification for builds, review and final delivery."""
    return _verify_author(package,base_dir=base_dir,consumed=consumed)


def verify_author_origin(package,*,base_dir,consumed=None):
    """Authenticate old actual authorship, never old quantities as current acceptance."""
    binding=integrity._json(integrity._raw(package['author_binding'],base_dir,{}))
    request=integrity._json(integrity._raw(binding['request'],base_dir,{}))
    loaded=_load(request,binding['base_dir'])
    view=_origin_view(binding,loaded)
    try:
        return _verify_author(package,base_dir=base_dir,consumed=consumed,_origin=view)
    finally:
        if view is not None:view.close()


def verified_products(package_pin,bindings,policy,*,base_dir):
    """Authenticate complete actual writer products and independently reviewed blind scope.

    Data pins are returned as requirements, never made safe here. The final
    consumer must join them to its reexecuted original public projections.
    Support/machinery are admitted only by the existing exact actual review
    case, with a material original-policy item and complete content census.
    """
    consumed={};package=integrity._json(integrity._raw(package_pin,base_dir,consumed))
    package_pin={**package_pin,'path':str(integrity._artifact_path(package_pin,base_dir))}
    verify_author(package,base_dir=base_dir,consumed=consumed)
    binding=integrity._json(integrity._raw(package['author_binding'],base_dir,consumed))
    loaded,_,_,_,calls=_author_state(binding);request=loaded['request']
    if request.get('blinding_policy') is None:raise ValueError('writer has no original-policy presentation')
    census=_blinding_census(loaded,Path(binding['base_dir']))
    actual_policy={**policy,'path':str(integrity._artifact_path(policy,base_dir))}
    if census['policy']!=actual_policy:raise ValueError('writer review cannot substitute the original blind policy')
    ir=integrity._json(integrity._raw(package['integrity_request'],base_dir,consumed))
    if ir.get('blinding_census')!=census:raise ValueError('integrity review omits or changes the actual writer source classification')
    assessment=integrity.assess(ir,bindings,base_dir=Path(binding['base_dir']))
    if not assessment['scoped_integrity_review_complete'] or not any(r['id']=='blinding-source-census' for r in assessment['item_census']):
        raise ValueError('actual independent original-policy manuscript integrity review remains unresolved')
    products=[package_pin,package['manuscript'],package['latex'],package['integrity_request'],package['formatting_assessment_pin'],
        package['model_provenance'],package['author_binding'],package['production_request'],binding['presentation'],
        *package['figures'],*manuscript_assets.pins(package['template_assets']),*[r['pin'] for r in calls]]
    if binding.get('stages') is not None:
        from . import manuscript_workflow
        products.extend(manuscript_workflow.transcript_pins(binding['stages'],loaded,binding['campaign']))
    outputs={str(integrity._artifact_path(p,base_dir)):{**p,'path':str(integrity._artifact_path(p,base_dir))} for p in products}
    proof=[*loaded['input_pins'],*products,*integrity.assessment_pins(ir,bindings,base_dir=Path(binding['base_dir']))]
    for pin in proof:integrity._dependency(pin,base_dir,{})
    restricted={p['path'] for p in census['custody_only']}
    # Full private stage captures are rechecked machine-side above, never
    # returned as final model evidence or made safe by source classification.
    public_proof=[p for p in proof if str(integrity._artifact_path(p,base_dir)) not in restricted]
    return {'outputs':outputs,'data':census['data'],'support':census['support'],'machinery':census['machinery'],'custody_only':census['custody_only'],
        'proof_pins':public_proof,'assessment':assessment,
        'limit':'Authenticated actual writer/materialization and scoped independent blind-policy judgments; no arbitrary safe input declaration or correctness/noninterference proof.'}

def finalize(package_pin,bindings,build_binding,final_manifest,completion_request,*,base_dir,rundir):
    """Exact existing integrity + compiled delivery + actual CI3 + whole-parent gates.

    No vote, model call, rendering or acceptance is constructed here. The ordinary
    producer/checkpoints and their actual independent roles own those operations.
    A draft and failed note remain observable; only this final delivery is gated.
    """
    from . import final_results_review,task_completion
    from ravel.physics import manuscript_build
    actual_build=manuscript_build.verified_result(build_binding,base_dir=base_dir)
    limits=integrity.custody_limits(actual_build.get('custody_limits'));budget=integrity.CustodyAccumulator(limits)
    consumed=integrity.CustodyInputs();package=integrity._json(integrity._raw(package_pin,base_dir,consumed))
    package_pin={**package_pin,'path':str(integrity._artifact_path(package_pin,base_dir))}
    verify_author(package,base_dir=base_dir,consumed=consumed)
    ir=integrity._json(integrity._raw(package['integrity_request'],base_dir,consumed))
    reviewed=integrity.manuscript(ir,base_dir=Path(package['source_base']),bindings=bindings,final=True)
    ce.keys(build_binding,['rundir','receipt','result'])
    result=integrity._operational_json(build_binding['result'],base_dir,consumed,limits=limits,accumulator=budget)
    if actual_build['result']!=result:raise ValueError('actual build result changed during finalization')
    for pin in [*actual_build.get('custody_pins',[]),*actual_build['proof_pins']]:integrity._dependency(pin,base_dir,consumed,limits=limits,accumulator=budget)
    if result['package']!=package_pin:raise ValueError('compiled PDF belongs to a different manuscript package')
    integrity._dependency(result['pdf'],base_dir,consumed,limits=limits,accumulator=budget)
    if any(row['state'] in {'mechanically_failed','unmet_actual_template','pending_compiled_page_boundary'} for row in result['formatting_assessment']['rules']):
        raise ValueError('unmet mandatory formatting or compiled boundary cannot be accepted by metadata')
    gate=final_results_review.gate(rundir,{k:final_manifest[k] for k in ('path','sha256')})
    manifest=integrity._json(integrity._raw(final_manifest,base_dir,consumed))
    root=Path(rundir).resolve(strict=True)
    from . import physics_review, finding_routing
    if physics_review.registered(root):
        registration, events = physics_review._read(root)
        census = physics_review._view(registration, events)['limitation_census']
        if census:
            if 'planned_claim_census' not in ir:
                raise ValueError('review limitations require the actual manuscript claim disposition census')
            claim_census = integrity._json(integrity._raw(ir['planned_claim_census'], Path(package['source_base']), consumed))
            finding_routing.require_dispositions([row['finding'] for row in census], claim_census['rows'])

    population={str((root/row['path']).resolve() if not Path(row['path']).is_absolute() else Path(row['path']).resolve()):row for row in manifest['artifacts']}
    required=[package_pin,package['manuscript'],package['latex'],package['integrity_request'],package['model_provenance'],
        package['formatting_assessment_pin'],package['author_binding'],build_binding['result'],result['pdf'],*package['figures'],*manuscript_assets.pins(package['template_assets'])]
    for pin in required:
        path=integrity._artifact_path(pin,base_dir);row=population.get(str(path))
        if row is None or row['sha256']!=pin['sha256']:raise ValueError('CI3 omitted or changed a manuscript/PDF/figure/method/prompt/format artifact')
    pdf=population[str(integrity._artifact_path(result['pdf'],base_dir))]
    if pdf['role']!='figure':raise ValueError('compiled paper must be in the actual CI3 visual presentation population')
    for conversion in result['figure_conversions']:
        preview=population.get(str(integrity._artifact_path(conversion['pdf'],base_dir)))
        if preview is None or preview['role']!='figure' or preview['sha256']!=conversion['pdf']['sha256']:
            raise ValueError('final CI3 omitted an actual source figure visual preview')
    parent=task_completion.require_final(completion_request,base_dir=base_dir)
    from .completion_claims import require_manuscript_disclosure
    require_manuscript_disclosure(rundir, reviewed)
    original=integrity._raw(package['original_task'],Path(package['source_base']),consumed).decode()
    if parent['original_prompt_sha256']!=hashlib.sha256(original.encode()).hexdigest():
        raise ValueError('final parent differs from literal original author task')
    request=integrity._json(integrity._raw(completion_request,base_dir,consumed));p=request.get('parent_review')
    parent_root=Path(p['rundir']) if p is not None else None
    if parent_root is not None and not parent_root.is_absolute():parent_root=Path(base_dir)/parent_root
    if parent_root is None or parent_root.resolve()!=root:raise ValueError('whole-parent review must belong to the same final CI3 root')
    if final_results_review.gate(rundir,{k:final_manifest[k] for k in ('path','sha256')})!=gate:raise ValueError('final review changed during delivery')
    for pin in list(consumed.values()):integrity._dependency(pin,base_dir,consumed,limits=limits,accumulator=budget)
    ending=manuscript_build.verified_result(build_binding,base_dir=base_dir)
    if ending!=actual_build:raise ValueError('complete build/runtime custody changed at final delivery ending')
    return {'kind':'whole-parent-manuscript-delivery','package':deepcopy(package_pin),'pdf':deepcopy(result['pdf']),
        'report_text':reviewed['report_text'],'pages':deepcopy(result['pages']),'integrity':reviewed['integrity'],
        'final_results_review':gate,'parent_task':parent,'parent_task_accepted':True,
        'publisher_acceptance':False,'human_identity_authenticated':False,'physics_correctness_proven':False,
        'custody_limits':limits,'execution_authorized':False,'limit':'Actual scoped reviewer/parent acceptance is not proof of scientific truth or publisher approval.'}
