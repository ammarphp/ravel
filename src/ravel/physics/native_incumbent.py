"""Private prospective native-incumbent capture; composes existing RAVEL evidence.

Positive source-only revisions retain the accepted native incumbent. The same
AgentHost graph lineage accounts for every turn; ordinary materialization, build and
event input admission bind the lineage. No previous approval or votes authorize
a challenger. Historical qualifications use the existing detached gate.
"""
from copy import deepcopy
from pathlib import Path
import hashlib, math, time
from ravel import analysis_sources as sources
from ravel.physics import existing_events, native_construction, routine_build
from ravel.workflow import agent_graph, execution, physics_review, science
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json, read_json


def pin(path):
    path=regular(path,Path.cwd())
    return {'path':str(path),'sha256':sources.digest(path)}
def bound(fact,base):
    if type(fact) is not dict or set(fact)!={'path','sha256'}:
        raise ValueError('exact ordinary artifact pin required')
    path=regular(fact['path'],base)
    if sources.digest(path)!=fact['sha256']:raise ValueError('native incumbent artifact changed')
    return path
def same_bound_pin(left, left_base, right, right_base):
    """Compare exact artifact identity across authenticated original bases."""
    return left['sha256'] == right['sha256'] and bound(left,left_base) == bound(right,right_base)
def fresh(path):
    path=Path(path).absolute()
    if path.exists() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('fresh ordinary immutable round/output required')
    return path
def _objective(objective,metric,base):
    if type(objective) is not str or not objective.strip() or len(objective)>16000:
        raise ValueError('explicit bounded scientific improvement objective required')
    if type(metric) is not dict or set(metric)!={'name','direction','incumbent_score','measurement','location','scope'}:
        raise ValueError('closed declared metric with actual measurement pin/location/scope required')
    if metric['direction'] not in ('minimize','maximize') or any(type(metric[k]) is not str or not metric[k].strip() or len(metric[k])>16000 for k in ('name','location','scope')):
        raise ValueError('explicit metric semantics required')
    try:
        if type(metric['incumbent_score']) not in (int,float) or not math.isfinite(metric['incumbent_score']):raise ValueError('finite metric required')
    except OverflowError:raise ValueError('representable finite metric required') from None
    return bound(metric['measurement'],base)

def _admission(rd, qualification=None):
    if qualification is not None:
        if type(qualification) is not dict or set(qualification)!={'contract','receipt'}:
            raise ValueError('explicit historical contract/receipt pins required')
        from ravel.workflow import historical_qualification as history
        contract_path=bound(qualification['contract'],rd);contract=read_json(contract_path)
        history.validate(contract)
        child=history.verify_receipt(contract,qualification['receipt'])
        if Path(contract['run_directory']).resolve()!=Path(rd).resolve():
            raise ValueError('historical qualification belongs to another incumbent')
        snapshot=child['snapshot'];reg,events=snapshot['registration'],snapshot['events']
        view=physics_review._view(reg,events)
        scope=contract['required_admission']['claim_scope']
        if scope!='diagnostic' or view['state']!='accepted':
            raise ValueError('source-correct accepted diagnostic incumbent required')
        status={'state':'accepted','claim_scope':scope,'live_errors':[],
                'cycle_id':view['cycle']['cycle_id']}
        paths=[contract_path,bound(qualification['receipt'],rd),*history.inputs(contract,qualification['receipt'])]
        return status,view,paths
    science.verify_plan(rd,approved=True)
    if execution.stage_errors(rd,'science') or physics_review.gate_errors(rd,'reuse'):
        raise ValueError('accepted native incumbent requires current public execution and review custody')
    live=physics_review.status(rd)
    status={k:live[k] for k in ('state','claim_scope','live_errors','cycle_id')}
    reg,events=physics_review._read(rd);view=physics_review._view(reg,events)
    return status,view,[]


def _measured_parent(rundir,construction,packet,graph_root,parent_qualification=None):
    rd=Path(rundir).resolve();task_path=rd/'inputs/science-execution-task.json';task=read_json(task_path)['task']
    loaded=native_construction._load(construction);panel=read_json(bound(packet,loaded['path'].parent))
    if panel!=native_construction._source_packet(loaded):raise ValueError('original native source request changed')
    # Refuse an accepted baseline transplanted onto an unrelated model candidate
    # before touching any graph/accounting state or producing a round file.
    if task.get('backend')!='rivet-built' or task.get('routine')!=loaded['config']['target_routine']:
        raise ValueError('actual native endpoint must execute the exact model candidate routine')
    status,view,qualification_paths=_admission(rd,parent_qualification)
    if status['state']!='accepted' or status['claim_scope']!='diagnostic' or status['live_errors']:
        raise ValueError('actual scoped three-role diagnostic acceptance required')
    state=execution.load_execution(rd)['stages']['science']
    if state['status']!='succeeded' or state['exit_code']!=0 or execution.receipt_digest(state)!=state['receipt_sha256']:
        raise ValueError('actual successful supervisor receipt required')
    out=rd/'outputs/attempt-1';result=read_json(out/'result.json')
    if result.get('status')!='passed' or result.get('rebuild') is not False or result.get('physics_validated') is not False or result.get('routine')!=task['routine']:
        raise ValueError('completed same-source native diagnostic required')
    rp,pp,receipt,plan,_,_,binary=existing_events._built_evidence(task,rd)
    selected=routine_build.bound_routine(receipt,plan,rp.parent,task['routine'])
    saved,model_receipt,model_request,responses=native_construction._proposal_receipt(graph_root,packet)
    raw=saved['result']['value'];source_hash=hashlib.sha256(raw['translation_unit'].encode()).hexdigest()
    if raw['routine_name']!=task['routine'] or len(selected['source_files'])!=1 or selected['source_files'][0]['sha256']!=source_hash:
        raise ValueError('accepted compiled source differs from actual model translation unit')
    if result['plugin_sha256']!=sources.digest(binary) or result['build_receipt_sha256']!=sources.digest(rp):
        raise ValueError('native event result/build identity differs')
    obs_path=out/'analysis/loader-event-observation.json';obs=read_json(obs_path)
    routine_build.verify_loader_observation(obs,binary,task['routine'],obs['environment'],Path(obs['cwd']),(out/'analysis/rivet.log').read_bytes(),'')
    if {r['role'] for r in view['reviews']}!={'physics_critic','skeptical_verifier','physics_decider'} or any(r['verdict']!='accept' or r['claim_scope']!='diagnostic' for r in view['reviews']):
        raise ValueError('three distinct actual accepted roles required')
    if {c['id'] for c in view['cycle']['checks']}!={'integrity','complete-source-endpoint'} or any(c['status']!='pass' for c in view['cycle']['checks']):
        raise ValueError('full prospectively declared endpoint checks must pass')
    protected=[rd/science.SPEC,rd/science.PLAN,rd/science.APPROVAL,task_path,out/'result.json',out/'checkin2.json',obs_path,pp,rp,binary,model_receipt,model_request,*responses,loaded['path'],bound(packet,rd),*[regular(f['path'],rd) for f in view['cycle']['snapshots']],*[regular(p,rd) for p in existing_events.inputs(task,rd)],*sorted((rd/'logs/physics_review/events').glob('*.json')),regular(state['attempt_record'],rd),*qualification_paths]
    return {'rd':rd,'task':task,'result_path':out/'result.json','result':result,'selected':selected,'raw':raw,'state':state,'status':status,'view':view,'loaded':loaded,'saved':saved,'model_receipt':model_receipt,'protected':list(dict.fromkeys(protected))}

def capture_incumbent(rundir,construction,source_packet,graph_root,output_path,*,objective,metric,max_output_tokens=16000,parent_qualification=None):
    """Freeze an actual accepted native candidate before a positive revision.

    The metric declaration and its evidence location are retained, not treated
    as independent verification of the caller's numerical interpretation.
    """
    output=fresh(output_path);measurement=_objective(objective,metric,Path(rundir))
    if type(max_output_tokens) is not int or not 16<=max_output_tokens<=32000:raise ValueError('bounded positive-turn output reservation required')
    parent=_measured_parent(rundir,construction,source_packet,graph_root,parent_qualification);graph=agent_graph.status(graph_root)
    protected=[*parent['protected'],measurement]
    if not 1<=len(protected)<=4096:raise ValueError('bounded complete native evidence population required')
    record={'schema_version':2,'kind':'successful-native-incumbent-improvement','rundir':str(parent['rd']),'construction':pin(parent['loaded']['path']),'source_packet':deepcopy(source_packet),'graph_root':str(Path(graph_root).resolve()),'parent_qualification':deepcopy(parent_qualification),'graph_id':graph['graph_id'],'graph_instance_id':graph['instance_id'],'parent_result':pin(parent['result_path']),'parent_model_receipt':pin(parent['model_receipt']),'source_routine':parent['task']['routine'],'translation_unit_sha256':hashlib.sha256(parent['raw']['translation_unit'].encode()).hexdigest(),'accepted_cycle_id':parent['view']['cycle']['cycle_id'],'review_state':parent['status'],'parent_call_receipts':deepcopy(parent['saved']['call_receipts']),'calls_at_capture':graph['usage']['calls'],'budget_at_capture':graph['budget'],'source_scope':parent['result']['scope'],'event_population':deepcopy(parent['result']['census']),'protected_inputs':[pin(p) for p in dict.fromkeys(protected)],'objective':objective,'metric':deepcopy(metric),'model_cost_bound':{'max_additional_calls':1,'max_output_tokens':max_output_tokens,'native_attempts_approved':0},'evaluation_contract':{'fresh_held_out_required':True,'full_case_required':True,'expected_answers_withheld_from_proposer':True,'failed_challenger_retains_incumbent':True},'prior_votes_carried':[],'model_executed':False,'execution_authorized':False,'physics_validated':False,'worker_lineage_admission_implemented':True,'limitations':['Metric interpretation is caller-declared despite an exact actual measurement pin.','Native endpoint acceptance is scoped history, not authority for the new source or broader physics.','Fresh challenger materialization/build/event admission is separately planned and requires new ordinary approval/reviews.']}
    atomic_json(output,record);return pin(output)

def validate_lineage(lineage,base=Path.cwd()):
    path=bound(lineage,base);record=read_json(path)
    required={'schema_version','kind','rundir','construction','source_packet','graph_root','parent_qualification','graph_id','graph_instance_id','parent_result','parent_model_receipt','source_routine','translation_unit_sha256','accepted_cycle_id','review_state','parent_call_receipts','calls_at_capture','budget_at_capture','source_scope','event_population','protected_inputs','objective','metric','model_cost_bound','evaluation_contract','prior_votes_carried','model_executed','execution_authorized','physics_validated','worker_lineage_admission_implemented','limitations'}
    if type(record) is not dict or set(record)!=required or type(record['schema_version']) is not int or record['schema_version']!=2 or record['kind']!='successful-native-incumbent-improvement' or record['prior_votes_carried']!=[] or any(record[k] is not False for k in ('model_executed','execution_authorized','physics_validated')):
        raise ValueError('closed prospective native-incumbent lineage required')
    cost=record['model_cost_bound']
    if (record['worker_lineage_admission_implemented'] is not True or type(cost) is not dict
            or set(cost)!={'max_additional_calls','max_output_tokens','native_attempts_approved'}
            or type(cost['max_additional_calls']) is not int or cost['max_additional_calls']!=1
            or type(cost['max_output_tokens']) is not int or not 16<=cost['max_output_tokens']<=32000
            or type(cost['native_attempts_approved']) is not int or cost['native_attempts_approved']!=0):
        raise ValueError('one bounded positive call and no inherited native authority required')
    if type(record['protected_inputs']) is not list or not 1<=len(record['protected_inputs'])<=4096:raise ValueError('bounded native evidence population required')
    if type(record['calls_at_capture']) is not int or record['calls_at_capture']<1:
        raise ValueError('exact integer accounted incumbent calls required')
    for fact in record['protected_inputs']:bound(fact,path.parent)
    _objective(record['objective'],record['metric'],path.parent)
    rd=Path(record['rundir']);status,view,_=_admission(rd,record['parent_qualification'])
    if status!=record['review_state'] or view['cycle']['cycle_id']!=record['accepted_cycle_id']:
        raise ValueError('native incumbent source-correct scoped custody changed')
    parent=read_json(bound(record['parent_result'],path.parent));saved=read_json(bound(record['parent_model_receipt'],path.parent))
    if parent['routine']!=record['source_routine'] or hashlib.sha256(saved['result']['value']['translation_unit'].encode()).hexdigest()!=record['translation_unit_sha256']:
        raise ValueError('retained parent native/source identity differs')
    graph=agent_graph.status(record['graph_root'])
    if graph['graph_id']!=record['graph_id'] or graph['instance_id']!=record['graph_instance_id'] or graph['budget']!=record['budget_at_capture'] or graph['usage']['calls']<record['calls_at_capture']:raise ValueError('cumulative parent graph identity/accounting cannot reset')
    for ref in record['parent_call_receipts']:
        call=read_json(Path(record['graph_root'])/'calls'/(ref['call_id']+'.json'))
        if agent_graph.digest(call)!=ref['sha256'] or call['status']!='completed':raise ValueError('immutable completed parent invocation changed')
    if record['evaluation_contract']!={'fresh_held_out_required':True,'full_case_required':True,'expected_answers_withheld_from_proposer':True,'failed_challenger_retains_incumbent':True}:raise ValueError('fresh full-case evaluation and retention required')
    return record


def input_paths(lineage, base=Path.cwd()):
    record = validate_lineage(lineage, base)
    return list(dict.fromkeys([bound(lineage, base), Path(__file__).resolve(),
        *[bound(fact, base) for fact in record['protected_inputs']]]))


def _event_fingerprints(path):
    """Conservative HepMC3 content census excluding identity labels/order.

    Particle/vertex graphs retain PDG, binary64 momenta, statuses, ancestry,
    attributes, event weights and units. Colour refinement is only a reuse
    refusal: identical signatures refuse novelty; differing signatures do not
    establish statistical independence, blinding or detector validity.
    """
    import re
    path=regular(path,Path.cwd())
    if path.stat().st_size>16_000_000:raise ValueError('bounded held-out ASCII event file required')
    text=path.read_text()
    if 'HepMC::Asciiv3-START_EVENT_LISTING' not in text:
        raise ValueError('native improvement novelty requires explicit ASCII HepMC3 records')
    def normalized(token):
        try:value=float(token)
        except ValueError:return token
        if not math.isfinite(value):raise ValueError('finite event fields required')
        return '0' if value==0 else value.hex()
    def canonical(rows):
        nodes={};links=[];attributes=[];global_rows=[]
        for row in rows:
            tag=row[0]
            if tag=='E':global_rows.append(['E',*[normalized(v) for v in row[2:]]])
            elif tag=='P':
                identity=row[1]
                if identity in nodes:raise ValueError('duplicate event node')
                nodes[identity]=['P',*[normalized(v) for v in row[3:]]]
                if row[2]!='0':links.append((row[2],identity))
            elif tag=='V':
                identity=row[1]
                if identity in nodes:raise ValueError('duplicate event node')
                incoming=next((v for v in row[3:] if v.startswith('[') and v.endswith(']')),None)
                if incoming is None:raise ValueError('explicit complete vertex input list required')
                nodes[identity]=['V',normalized(row[2]),*[normalized(v) for v in row[3:] if v!=incoming]]
                for parent in re.findall(r'-?[0-9]+',incoming):links.append((parent,identity))
            elif tag=='A' and row[1]!='0':attributes.append((row[1],row[2:]))
            else:global_rows.append([tag,*[normalized(v) for v in row[1:]]])
        if not 1<=len(nodes)<=4096:raise ValueError('bounded complete event graph required')
        incoming={k:[] for k in nodes};outgoing={k:[] for k in nodes}
        for parent,child in links:
            if parent not in nodes or child not in nodes:raise ValueError('missing event ancestry node')
            incoming[child].append(parent);outgoing[parent].append(child)
        for owner,values in attributes:
            if owner not in nodes:raise ValueError('missing attribute owner')
            nodes[owner].append(['A',*[normalized(v) for v in values]])
        labels={k:agent_graph.digest(v) for k,v in nodes.items()}
        for _ in range(min(len(nodes),32)):
            labels={k:agent_graph.digest({'attributes':nodes[k],
                'incoming':sorted(labels[p] for p in incoming[k]),
                'outgoing':sorted(labels[p] for p in outgoing[k])}) for k in nodes}
        return agent_graph.digest({'global':sorted(global_rows,key=lambda x:str(x)),
            'graph':sorted(labels.values())})
    events=[];current=None
    for line in text.splitlines():
        fields=line.split()
        if not fields:continue
        if fields[0]=='E':
            if current is not None:events.append(canonical(current))
            current=[fields]
        elif current is not None and not fields[0].startswith('HepMC::'):
            current.append(fields)
    if current is not None:events.append(canonical(current))
    return events


def prepare_agent_request(loaded, packet_pin, graph_root, *, model,
                          reasoning_effort, max_output_tokens, max_calls):
    """Reserve one positive turn on the exact incumbent graph, without dispatch.

    Reservation is an accounted graph effect; callers must prospectively admit
    the concrete call. Failed/unknown challenges never replace the incumbent.
    """
    record = validate_lineage(loaded['config']['improvement_lineage'], loaded['path'].parent)
    root = Path(graph_root).resolve()
    if 'continuation_campaign' in loaded['config']:
        campaign = validate_campaign(loaded['config']['continuation_campaign'],loaded['path'].parent,
                                     loaded['config']['improvement_lineage'])
        if (root != Path(campaign['graph_root']) or root.exists()
                or max_calls != campaign['cumulative_ceiling']['max_calls']
                or type(max_output_tokens) is not int
                or not 16<=max_output_tokens<=campaign['remaining_budget']['max_output_tokens']):
            raise ValueError('fresh continuation graph and remaining cumulative call/token budget required')
        panel=read_json(bound(packet_pin,loaded['path'].parent))
        node={'id':'construct','kind':'model','role':'improver','depends_on':[],
            'inputs':[{'id':'native-source',**packet_pin}],'packet':None,
            'action':'external','max_attempts':1,
            'parameters':{'instructions':panel['instructions'],'model':model,
                'reasoning_effort':reasoning_effort,'max_output_tokens':max_output_tokens,
                'output_schema':native_construction.output_schema(loaded['config'],loaded['capsule']['routine'])}}
        specification={'schema_version':1,'graph_id':'native-incumbent-continuation',
            'budget':{'max_nodes':1,'max_calls':campaign['remaining_budget']['max_calls'],
                'max_output_tokens':campaign['remaining_budget']['max_output_tokens'],
                'max_wall_seconds':campaign['phase_seconds'],'max_reworks':0},'nodes':[node]}
        agent_graph.create(root,specification)
        # Invoke only at the separately authorized external-host dispatch. No
        # graph/call is reserved by write_source_packet or campaign preparation.
        request=agent_graph.prepare_external(root,'construct')
        return {**request,'packet_pin':deepcopy(packet_pin),
            'continuation_campaign':deepcopy(loaded['config']['continuation_campaign']),
            'inherited_usage':deepcopy(campaign['inherited_usage']),
            'cumulative_ceiling':deepcopy(campaign['cumulative_ceiling']),
            'phase_seconds':campaign['phase_seconds'],'model_executed':False,
            'original_end_to_end_deadline_compliance_claimed':False,'execution_authorized':False}
    state = agent_graph.status(root)
    if (root != Path(record['graph_root']).resolve() or not state['complete']
            or state['usage']['calls'] != record['calls_at_capture']
            or state['instance_id'] != record['graph_instance_id']
            or state['budget'] != record['budget_at_capture']
            or max_calls != state['budget']['max_calls']):
        raise ValueError('same complete incumbent graph and exact cumulative budget required')
    ceiling = record['model_cost_bound']['max_output_tokens']
    if (type(max_output_tokens) is not int or not 16 <= max_output_tokens <= ceiling
            or state['usage']['calls'] + 1 > state['budget']['max_calls']
            or state['usage']['reserved_output_tokens'] + max_output_tokens > state['budget']['max_output_tokens']
            or state['reworks'] >= state['budget']['max_reworks']):
        raise ValueError('native improvement cumulative call/token/rework budget exhausted')
    specification, current = agent_graph._load(root)
    agent_graph._deadline(specification, current)
    panel = read_json(bound(packet_pin, loaded['path'].parent))
    node = {'id':'construct','kind':'model','role':'improver','depends_on':[],
        'inputs':[{'id':'native-source',**packet_pin}], 'packet':None,
        'action':'external','max_attempts':1,
        'parameters':{'instructions':panel['instructions'],'model':model,
            'reasoning_effort':reasoning_effort,'max_output_tokens':max_output_tokens,
            'output_schema':native_construction.output_schema(loaded['config'], loaded['capsule']['routine'])}}
    new = {'schema_version':1,'graph_id':state['graph_id'],'budget':state['budget'],'nodes':[node]}
    agent_graph.revise(root, new, reason='Prospective successful native-incumbent improvement; original outcome retained')
    return {**agent_graph.prepare_external(root,'construct'),
        'packet_pin':deepcopy(packet_pin), 'improvement_lineage':deepcopy(loaded['config']['improvement_lineage']),
        'prior_calls_retained':record['calls_at_capture'],'model_executed':False,
        'execution_authorized':False}


def source_binding(lineage, capsule, base):
    """Bind the new source to this lineage and its actual completed Host reply."""
    record = validate_lineage(lineage, base)
    root, paths = sources.source_files(capsule, base)
    facts = {f['path']:f for f in capsule['files']}
    p = 'provenance/improvement-lineage.json'
    if (capsule['routine'] == record['source_routine'] or p not in facts
            or facts[p]['sha256'] != lineage['sha256']):
        raise ValueError('distinct challenger and exact copied incumbent lineage required')
    config = read_json(root/'provenance/configuration.json')
    panel_path = root/'provenance/source-request.json'
    panel = read_json(panel_path)
    receipt_path = root/'provenance/model-receipt.json'
    saved = read_json(receipt_path)
    artifacts = saved['request']['input_artifacts']
    if len(artifacts) != 1 or artifacts[0]['id'] != 'native-source':
        raise ValueError('one exact improvement source packet required')
    packet_pin = {k:artifacts[0][k] for k in ('path','sha256')}
    if (config.get('improvement_lineage') != lineage or config['target_routine'] != capsule['routine']
            or panel.get('improvement_lineage') != lineage
            or panel.get('revision_type') != 'improve_successful_native_incumbent'
            or panel.get('failure_trigger') is not None
            or sources.digest(panel_path) != packet_pin['sha256']):
        raise ValueError('challenger source/configuration/positive request differ')
    graph_root=record['graph_root']
    if 'continuation_campaign' in config:
        campaign=validate_campaign(config['continuation_campaign'],base,lineage)
        graph_root=campaign['graph_root']
        if panel.get('continuation_campaign')!=config['continuation_campaign']:
            raise ValueError('completed reply must retain the exact continuation campaign')
        state=agent_graph.status(graph_root)
        if (state['budget']['max_calls']!=campaign['remaining_budget']['max_calls']
                or state['budget']['max_output_tokens']!=campaign['remaining_budget']['max_output_tokens']
                or state['budget']['max_wall_seconds']!=campaign['phase_seconds']
                or state['usage']['calls']+campaign['inherited_usage']['calls']>campaign['cumulative_ceiling']['max_calls']
                or state['usage']['reserved_output_tokens']+campaign['inherited_usage']['reserved_output_tokens']>campaign['cumulative_ceiling']['max_output_tokens']):
            raise ValueError('actual continuation exceeds retained cumulative budget')
    actual, actual_path, request_path, responses = native_construction._proposal_receipt(graph_root, packet_pin)
    if actual != saved or sources.digest(actual_path) != sources.digest(receipt_path):
        raise ValueError('challenger lacks its current accounted Host invocation')
    raw = saved['result']['value']
    expected = {capsule['routine']+'.cc':raw['translation_unit'].encode(),
        capsule['routine']+'.info':raw['metadata_info'].encode(),
        capsule['routine']+'.plot':raw['metadata_plot'].encode()}
    expected.update({row['path']:row['text'].encode() for row in raw['supporting_files']})
    if (raw['routine_name'] != capsule['routine'] or
            {f['path'] for f in capsule['files'] if f['role']=='compile'}!={capsule['routine']+'.cc'} or
            any(p not in facts or (root/p).read_bytes() != content for p,content in expected.items())):
        raise ValueError('new candidate source/assets differ from actual improved public reply')
    return record, list(dict.fromkeys(input_paths(lineage,base)+paths+[actual_path,request_path,*responses,
        bound(packet_pin,base)]))


def prepare_continuation_campaign(lineage, output_path, graph_root, *, phase_seconds=900):
    """Declare a new phase, debit past calls, and leave the old graph untouched.

    This does not reserve a Host call. The original elapsed deadline is reported
    separately, never relabelled as satisfied by the new phase wall ceiling.
    """
    import time
    record=validate_lineage(lineage)
    if type(phase_seconds) is not int or not 1<=phase_seconds<=7200:
        raise ValueError('explicit bounded new-phase wall budget required')
    new=fresh(graph_root)
    state=agent_graph.status(record['graph_root'])
    if not state['complete'] or state['usage']['calls']!=record['calls_at_capture']:
        raise ValueError('unchanged complete historical graph required for continuation')
    budget=record['budget_at_capture'];usage=state['usage']
    calls=budget['max_calls']-usage['calls'];tokens=budget['max_output_tokens']-usage['reserved_output_tokens']
    if calls!=1 or not 16<=tokens<=record['model_cost_bound']['max_output_tokens']:
        raise ValueError('exactly one remaining bounded positive call required')
    old=Path(record['graph_root'])
    pins=[pin(old/agent_graph.SPEC),pin(old/agent_graph.STATE)]
    pins += [pin(old/'calls'/(ref['call_id']+'.json')) for ref in record['parent_call_receipts']]
    document={'schema_version':1,'kind':'native-incumbent-continuation-campaign',
        'improvement_lineage':deepcopy(lineage),'graph_root':str(new),
        'historical_graph':str(old),'historical_instance_id':state['instance_id'],
        'historical_ledger':pins,'inherited_usage':deepcopy(usage),
        'cumulative_ceiling':{'max_calls':budget['max_calls'],'max_output_tokens':budget['max_output_tokens']},
        'remaining_budget':{'max_calls':calls,'max_output_tokens':tokens},
        'original_wall_ceiling_seconds':budget['max_wall_seconds'],
        'original_elapsed_seconds_at_capture':None if state['started_epoch'] is None else time.time()-state['started_epoch'],
        'phase_seconds':phase_seconds,'phase_clock':'starts at explicitly authorized external-host request reservation; inference timing telemetry unavailable',
        'original_end_to_end_deadline_compliance_claimed':False,
        'model_executed':False,'execution_authorized':False,'prior_reviews_carried':[]}
    output=fresh(output_path);atomic_json(output,document);return pin(output)


def validate_campaign(campaign_pin, base, lineage):
    path=bound(campaign_pin,base);doc=read_json(path)
    keys={'schema_version','kind','improvement_lineage','graph_root','historical_graph','historical_instance_id',
        'historical_ledger','inherited_usage','cumulative_ceiling','remaining_budget','original_wall_ceiling_seconds',
        'original_elapsed_seconds_at_capture','phase_seconds','phase_clock','original_end_to_end_deadline_compliance_claimed',
        'model_executed','execution_authorized','prior_reviews_carried'}
    if (type(doc) is not dict or set(doc)!=keys
            or type(doc['schema_version']) is not int or doc['schema_version']!=1
            or doc['kind']!='native-incumbent-continuation-campaign' or doc['improvement_lineage']!=lineage
            or doc['prior_reviews_carried']!=[] or any(doc[k] is not False for k in
                ('original_end_to_end_deadline_compliance_claimed','model_executed','execution_authorized'))):
        raise ValueError('closed declared historical-incumbent continuation campaign required')
    for field,keys in (('inherited_usage',{'calls','reserved_output_tokens'}),
                       ('cumulative_ceiling',{'max_calls','max_output_tokens'}),
                       ('remaining_budget',{'max_calls','max_output_tokens'})):
        if (type(doc[field]) is not dict or set(doc[field])!=keys
                or any(type(v) is not int or v<0 for v in doc[field].values())):
            raise ValueError('exact integer cumulative and remaining budget ledger required')
    record=validate_lineage(lineage,base)
    old=Path(record['graph_root'])
    expected=[pin(old/agent_graph.SPEC),pin(old/agent_graph.STATE)]
    expected += [pin(old/'calls'/(ref['call_id']+'.json')) for ref in record['parent_call_receipts']]
    if doc['historical_ledger']!=expected:
        raise ValueError('complete original graph/spec/state/call ledger required')
    for fact in doc['historical_ledger']:bound(fact,path.parent)
    if (doc['original_wall_ceiling_seconds']!=record['budget_at_capture']['max_wall_seconds']
            or type(doc['original_elapsed_seconds_at_capture']) not in (int,float)
            or not math.isfinite(doc['original_elapsed_seconds_at_capture'])
            or doc['original_elapsed_seconds_at_capture']<0
            or doc['phase_clock']!='starts at explicitly authorized external-host request reservation; inference timing telemetry unavailable'):
        raise ValueError('original and new phase clocks must retain distinct declared scopes')
    state=agent_graph.status(record['graph_root'])
    if (doc['historical_graph']!=record['graph_root'] or doc['historical_instance_id']!=state['instance_id']
            or doc['inherited_usage']!=state['usage'] or doc['cumulative_ceiling']!=
                {k:record['budget_at_capture'][k] for k in ('max_calls','max_output_tokens')}
            or doc['remaining_budget']!={'max_calls':doc['cumulative_ceiling']['max_calls']-state['usage']['calls'],
                'max_output_tokens':doc['cumulative_ceiling']['max_output_tokens']-state['usage']['reserved_output_tokens']}
            or doc['remaining_budget']['max_calls']!=1
            or type(doc['phase_seconds']) is not int or not 1<=doc['phase_seconds']<=7200
            or Path(doc['graph_root']).resolve()==Path(record['graph_root']).resolve()):
        raise ValueError('continuation ledger/remaining budget/phase/identity differs')
    return doc


def event_inputs(task, base):
    """Ordinary native-event input admission after an actual challenger build."""
    record = validate_lineage(task['improvement_lineage'],base)
    rp,pp,receipt,plan,_,_,binary = existing_events._built_evidence(task,base)
    config = read_json(regular(plan['input']['path'],base))
    if config.get('improvement_lineage') != plan.get('improvement_lineage'):
        raise ValueError('event task must retain the actual challenger build lineage')
    capsule_path = regular(plan['source_capsule']['path'],base)
    capsule = sources.load_capsule(capsule_path)
    _,paths = source_binding(plan['improvement_lineage'],capsule,capsule_path.parent)
    if task['routine'] != capsule['routine'] or task['routine'] == record['source_routine']:
        raise ValueError('event task must run the new challenger routine')
    evaluation_path = bound(task['improvement_evaluation'],base)
    evaluation = read_json(evaluation_path)
    fields = {'schema_version','kind','improvement_lineage','partition','events','metadata','checker_inputs'}
    if (type(evaluation) is not dict or set(evaluation)!=fields
            or type(evaluation['schema_version']) is not int or evaluation['schema_version']!=1
            or evaluation['kind']!='native-improvement-evaluation'
            or not same_bound_pin(evaluation['improvement_lineage'],evaluation_path.parent,
                                  task['improvement_lineage'],base)
            or evaluation['partition'] not in ('held_out','full_case')
            or bound(evaluation['events'],evaluation_path.parent)!=regular(task['events'],base)
            or bound(evaluation['metadata'],evaluation_path.parent)!=regular(task['metadata'],base)):
        raise ValueError('explicit fresh held-out or complete full-case evaluation binding required')
    if (type(evaluation['checker_inputs']) is not list or not 1<=len(evaluation['checker_inputs'])<=256):
        raise ValueError('bounded complete evaluation checker inputs required')
    paths += [evaluation_path,bound(evaluation['events'],evaluation_path.parent),
              bound(evaluation['metadata'],evaluation_path.parent)]
    paths += [bound(pin,evaluation_path.parent) for pin in evaluation['checker_inputs']]
    from ravel.physics.event_census import census
    census(regular(task['events'],base),read_json(regular(task['metadata'],base)))
    if evaluation['partition']=='held_out':
        old_task = read_json(Path(record['rundir'])/'inputs/science-execution-task.json')['task']
        old_events = regular(old_task['events'],record['rundir'])
        # Event content novelty is separate from statistical independence. HepMC
        # event-number relabeling does not establish a fresh held-out population.
        old = _event_fingerprints(old_events)
        new = _event_fingerprints(regular(task['events'],base))
        if not new or set(old)&set(new):
            raise ValueError('held-out event content reuses the incumbent population')
    return list(dict.fromkeys(paths))


def prepare_event_task(lineage, build_receipt, build_plan, template, evaluation, output_path,base=Path.cwd()):
    """A real receipt is required; no future binary/result hashes are invented."""
    record=validate_lineage(lineage,base)
    task=deepcopy(template)
    if task.get('backend')!='rivet-built':
        raise ValueError('native incumbent challenger uses the existing built-event adapter')
    task.update(build_receipt=str(bound(build_receipt,base)),build_plan=str(bound(build_plan,base)),
        improvement_lineage=deepcopy(lineage),improvement_evaluation=deepcopy(evaluation))
    existing_events.inputs(task,base)
    output=fresh(output_path);atomic_json(output,task)
    return {'task':pin(output),'new_generated_events':0,'execution_authorized':False,
        'physics_validated':False,'incumbent_retained':record['parent_result']}


def compare_challenger(lineage, *, challenger_result, challenger_score, held_out_complete,
                       full_case_complete, independently_accepted,base=Path.cwd()):
    """Advisory comparison only; failed, unknown or unreviewed challengers retain parent."""
    record=validate_lineage(lineage,base)
    for flag in (held_out_complete,full_case_complete,independently_accepted):
        if type(flag) is not bool:raise ValueError('strict evaluation declarations required')
    outcome='retain_incumbent';delta=None
    if challenger_result is not None:
        result=read_json(bound(challenger_result,base))
        if result.get('improvement_lineage')!=lineage or result.get('prior_reviews_carried')!=[]:
            raise ValueError('challenger result belongs to another positive lineage')
        if result.get('status')=='passed' and held_out_complete and full_case_complete and independently_accepted:
            if type(challenger_score) not in (int,float):raise ValueError('finite challenger metric required')
            try:
                if not math.isfinite(challenger_score):raise ValueError('finite challenger metric required')
                delta=challenger_score-record['metric']['incumbent_score']
                if not math.isfinite(delta):raise ValueError('representable paired metric delta required')
            except OverflowError:raise ValueError('representable paired metric delta required') from None
            better=delta>0 if record['metric']['direction']=='maximize' else delta<0
            if better:outcome='request_challenger_scope_review'
    return {'next_action':outcome,'paired_declared_metric_delta':delta,
        'incumbent_retained':record['parent_result'],'automatic_promotion':False,
        'metric_interpretation_independently_verified':False,'execution_authorized':False,
        'physics_validated':False}


def _historical(record, base):
    qualification=record['parent_qualification']
    if qualification is None:return None
    from ravel.workflow import historical_qualification as history
    contract=read_json(bound(qualification['contract'],base))
    history.validate(contract)
    history.verify_receipt(contract,qualification['receipt'])
    return history,contract,qualification['receipt']


def execution_seconds(lineage, base, work_seconds):
    """Pure admission of the complete selected branch, including old gates.

    The supplied native work bound is separate from historical workflow
    qualification. Twenty seconds reserve source/custody work; metadata calls
    are at most ten seconds each. These are ceilings, not completion promises.
    """
    if type(work_seconds) is not int or not 1<=work_seconds<=3600:
        raise ValueError('explicit selected native/source work ceiling required')
    record=validate_lineage(lineage,base);historical=_historical(record,base)
    if historical is None:return work_seconds+20
    history,contract,receipt=historical
    budget=history.hook_resource_bounds(contract,receipt)
    seconds=history.execution_seconds(contract,receipt)
    if (work_seconds+20+20>budget['worker_inner_seconds']
            or budget['solver_work_cutoff_seconds']<work_seconds+20+10
            or budget['initial_capture_compile_gate_seconds']<10
            or budget['final_gate_reservation_seconds']<10
            or type(seconds) not in (int,float) or not math.isfinite(seconds)):
        raise ValueError('historical worker envelope omits selected native branch or metadata/custody reservations')
    return math.ceil(seconds)


class WorkerBoundary:
    """Compose the sole generic historical gate into a new ordinary worker.

    Planning launches zero children. A historically qualified worker performs
    exactly initial/final old-workflow metadata checks with their own receipts;
    neither check authorizes nor validates the new native source or covariance.
    """
    def __init__(self,lineage,base,out,*,work_seconds,worker_started):
        self.lineage,self.base,self.out=lineage,base,Path(out).resolve()
        self.work_seconds=work_seconds;self.proof=None;self.initial=None;self.session=None
        admitted_seconds=execution_seconds(lineage,base,work_seconds)
        worker_start(worker_started)
        self.outer_deadline=worker_started+admitted_seconds
        record=validate_lineage(lineage,base);historical=_historical(record,base)
        self.qualification=record['parent_qualification']
        if historical is not None:
            self.history,self.contract,self.receipt=historical
            self.session=self.history.WorkerSession(self.contract,self.receipt,
                self.out/'historical-qualification',worker_started=worker_started)
            self.initial=self.session.boundary('initial')
        self.work_deadline=min(worker_started+work_seconds+20,
            self.session.work_deadline if self.session is not None else math.inf)
        self.check_work()

    def check_work(self):
        if time.monotonic()>=self.work_deadline:
            raise TimeoutError('native incumbent continuation work deadline exhausted; original retained')

    def finish(self):
        self.check_work()
        if self.session is None:return None
        final=self.session.boundary('final')
        directory=self.out/'historical-qualification'
        facts=[pin(directory/name) for name in ('session.json','initial-started.json',
            'initial-completed.json','final-started.json','final-completed.json')]
        self.proof={'kind':'historical-native-incumbent-worker-boundaries',
            'parent_qualification':deepcopy(self.qualification),'initial':self.initial,'final':final,
            'session_inputs':facts,'selected_work_seconds_ceiling':self.work_seconds,
            'native_runtime_qualified_by_history':False,'new_native_authority_inherited':False}
        verify_worker_boundaries(self.lineage,self.proof,self.base,self.out)
        if time.monotonic()>=self.outer_deadline:
            raise TimeoutError('complete historical native worker ceiling exhausted after custody recheck')
        return self.proof


def verify_worker_boundaries(lineage,proof,base,out):
    record=validate_lineage(lineage,base);historical=_historical(record,base)
    keys={'kind','parent_qualification','initial','final','session_inputs',
        'selected_work_seconds_ceiling','native_runtime_qualified_by_history','new_native_authority_inherited'}
    if (historical is None or type(proof) is not dict or set(proof)!=keys
            or proof['kind']!='historical-native-incumbent-worker-boundaries'
            or proof['parent_qualification']!=record['parent_qualification']
            or any(proof[k] is not False for k in ('native_runtime_qualified_by_history','new_native_authority_inherited'))):
        raise ValueError('exact historical initial/final worker evidence required')
    history,contract,receipt=historical;directory=Path(out).resolve()/'historical-qualification'
    names=('session.json','initial-started.json','initial-completed.json','final-started.json','final-completed.json')
    expected=[pin(directory/name) for name in names]
    if proof['session_inputs']!=expected:
        raise ValueError('complete exact worker boundary ledger required')
    session=read_json(directory/'session.json')
    if (session['contract_sha256']!=history.digest(contract) or session['receipt']!=receipt
            or session['metadata_child_ceiling']!=2 or session['scientific_calls']!=0):
        raise ValueError('historical worker session belongs to another source or receipt')
    phases=[]
    for i,phase in enumerate(('initial','final')):
        path=bound(proof[phase],base)
        if path.parent!=directory/phase:
            raise ValueError('initial/final receipts must be separate fresh worker phase outputs')
        history.verify_receipt(contract,proof[phase]);phases.append(path)
        started=read_json(directory/(phase+'-started.json'))
        completed=read_json(directory/(phase+'-completed.json'))
        if (started['phase']!=phase or started['metadata_child_number']!=i+1
                or completed!={'validation_receipt':proof[phase],'scientific_calls':0}):
            raise ValueError('metadata phase identity/call ledger differs')
    if phases[0]==phases[1]:raise ValueError('old workflow validation cannot be replayed as both worker phases')
    execution_seconds(lineage,base,proof['selected_work_seconds_ceiling'])
    return proof


def prepare_improvement_packet(lineage,output_directory,*,target_routine,
                               additional_obligations,support_sources,
                               continuation_graph,phase_seconds=900,base=Path.cwd()):
    """Concrete immutable E1 source proposal, with no call or future receipt.

    The original source/claims/obligations stay intact. The new phase debits its
    historical ledger; reservation/dispatch needs separate concrete approval.
    Build/event planning follows only after a real reply and real build receipt.
    """
    record=validate_lineage(lineage,base)
    if (type(target_routine) is not str or not native_construction.NAME.fullmatch(target_routine)
            or target_routine==record['source_routine']):
        raise ValueError('distinct literal improvement routine identity required')
    if type(additional_obligations) is not list or not 1<=len(additional_obligations)<=16:
        raise ValueError('bounded positive scientific obligations required')
    original_path=bound(record['construction'],base)
    original=read_json(original_path);config=deepcopy(original)
    # Relative pins retain their original base. A fresh proposal directory must
    # reference the same original artifacts rather than relocate their meaning.
    config['source_capsule']=pin(bound(original['source_capsule'],original_path.parent))
    config['build_template']=pin(bound(original['build_template'],original_path.parent))
    for row in config['api_sources']:
        row.update(pin(bound({k:row[k] for k in ('path','sha256')},original_path.parent)))
    lineage_pin=pin(bound(lineage,base))
    known={row['id'] for row in config['obligations']}
    for row in additional_obligations:
        if (type(row) is not dict or set(row)!={'id','description'}
                or type(row['id']) is not str or not native_construction.IDENTIFIER.fullmatch(row['id'])
                or row['id'] in known or type(row['description']) is not str
                or not row['description'].strip() or len(row['description'])>16000):
            raise ValueError('new scientific obligations require distinct bounded identities')
        known.add(row['id'])
    output=fresh(output_directory);new_graph=fresh(continuation_graph)
    # Validate caller-supplied public supports before creating this immutable round.
    if type(support_sources) is not list or len(support_sources)>16:
        raise ValueError('bounded source-only support inventory required')
    supports=[]
    for row in support_sources:
        if type(row) is not dict or set(row)!={'path','sha256','description'}:
            raise ValueError('exact source-only support pin/description required')
        if type(row['description']) is not str or not row['description'].strip() or len(row['description'])>16000:
            raise ValueError('bounded source-only support description required')
        supports.append({**pin(bound({k:row[k] for k in ('path','sha256')},base)),
                         'description':row['description']})
    output.mkdir(parents=True)
    campaign=prepare_continuation_campaign(lineage_pin,output/'continuation-campaign.json',
        new_graph,phase_seconds=phase_seconds)
    config.update(target_routine=target_routine,improvement_lineage=lineage_pin,
        continuation_campaign=campaign,support_sources=supports)
    config['obligations'] += deepcopy(additional_obligations)
    config['requested_task']=(original['requested_task']+'\nSuccessful native incumbent improvement: '+record['objective']+
        '\nRetain the incumbent and all source obligations. Produce a distinct complete challenger. '+
        'Treat new public supporting interfaces as unqualified source proposals. Report unserved obligations; '+
        'claim no inherited execution, native-runtime, covariance or physics authority.')
    configuration=output/'configuration.json';atomic_json(configuration,config)
    packet=native_construction.write_source_packet(configuration,output/'source-only-packet.json')
    result={'kind':'native-incumbent-positive-proposal-preparation','configuration':pin(configuration),
        'source_packet':{k:packet[k] for k in ('path','sha256')},'continuation_campaign':campaign,
        'prospective_materialization_task':{'backend':'native-construction','input':str(configuration),
            'source_packet':{k:packet[k] for k in ('path','sha256')},'graph_root':str(new_graph)},
        'retained_incumbent':record['parent_result'],
        'model_calls':0,'native_calls':0,'host_call_reserved':False,
        'fresh_dependency_review_required':True,'fresh_scientific_plan_required':True,
        'future_build_receipt_invented':False,'execution_authorized':False,'physics_validated':False}
    atomic_json(output/'preparation.json',result)
    return result


def worker_start(supplied=None):
    """Preserve the science worker's common monotonic start, never reset it."""
    now=time.monotonic()
    if supplied is None:return now
    if type(supplied) not in (int,float) or not math.isfinite(supplied) or not 0<=supplied<=now:
        raise ValueError('finite observed common worker monotonic start required')
    return supplied


def helper_declaration(lineage, base_dir, output_dir, *, _session=None):
    record=validate_lineage(lineage,base_dir)
    qualified=_historical(record,base_dir)
    if qualified is None:return None
    from ravel.workflow import helper_registration
    _,contract,_=qualified
    directory=Path(output_dir).absolute()/'historical-qualification'
    return helper_registration.declaration(contract,{phase:directory/phase for phase in ('initial','final')})
