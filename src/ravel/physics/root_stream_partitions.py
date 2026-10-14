"""Master coverage, persisted ordinary completion, resume and raw ROOT merge.

All master/partition records are machine-private. This is a source-bound data
partitioner using the existing science/site authority, not a new scheduler.
"""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
from pathlib import Path
from ravel.physics import root_stream_core as c, root_stream_partition_core as pc

MAX_MASTER=64*1024**2
FILES=('root_stream.py','root_stream_core.py','root_stream_worker.py','root_stream_partitions.py','root_stream_partition_core.py','root_stream_statistics.py')


def sources():
    result={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in FILES}
    for name in ('research_cycle.py','execution.py','science.py','state_io.py'):
        result['workflow/'+name]=hashlib.sha256((Path(__file__).parents[1]/'workflow'/name).read_bytes()).hexdigest()
    return result


def config(value):
    c.keys(value,('schema_version','dataset','analysis','bundle','runtime','site','limits','partitioning'),'partitioned ROOT config')
    old=deepcopy(value);p=old.pop('partitioning');old['schema_version']=1;c.config(old)
    c.require(type(value['schema_version']) is int and value['schema_version']==2,'partitioned ROOT schema2 required')
    c.keys(p,('master','operation','partition_id','completions'),'partition/merge identity');c.pin(p['master'])
    c.require(Path(p['master']['path']).is_absolute(),'absolute original master pin required')
    c.require(p['operation'] in ('partition','merge'),'actual partition or full merge required')
    c.require(type(p['completions']) is list and len(p['completions'])<=10000,'bounded complete completion records required')
    for row in p['completions']:c.pin(row)
    if p['operation']=='partition':
        c.text(p['partition_id']);c.require(not p['completions'],'partition does not consume aggregate completions')
    else:c.require(p['partition_id'] is None and p['completions'],'merge requires the complete original completion roster')
    return deepcopy(value)


def _cover(ds,intervals):
    members=[(s,m) for s in ds['samples'] for m in s['members']];order={(s['id'],m['id']):i for i,(s,m) in enumerate(members)}
    rows=sorted(intervals,key=lambda x:(order.get((x['sample'],x['member']),-1),x['start'],x['stop']))
    index=0;offset=0
    for row in rows:
        c.require(index<len(members),'extra original interval')
        s,m=members[index]
        c.require(type(row['start']) is int and type(row['stop']) is int and (row['sample'],row['member'],row['start'])==(s['id'],m['id'],offset) and
                  (offset<row['stop']<=m['entries'] or offset==row['stop']==m['entries']==0),'full original population gap/overlap/alias')
        offset=row['stop']
        if offset==m['entries']:index+=1;offset=0
    c.require(index==len(members) and offset==0,'incomplete original source population')
    return rows


def partition_population(ds,grouping,group_document,entries,max_parts):
    c.integer(entries,1,10**15,'prospective partition entries');c.integer(max_parts,1,10000,'prospective partition population')
    lookup={(s['id'],m['id']):(s,m) for s in ds['samples'] for m in s['members']};units=[];groups=[]
    if grouping['kind']=='declared_groups':
        c.keys(group_document,('schema_version','kind','groups'),'complete physical group source')
        c.require(type(group_document['schema_version']) is int and group_document['schema_version']==1 and group_document['kind']=='physical-event-groups' and
                  type(group_document['groups']) is list and len(group_document['groups'])<=1000000,'bounded complete physical group identity required')
        seen=set()
        for group in group_document['groups']:
            c.keys(group,('id','sample','spans'),'original physical group');c.text(group['id']);c.text(group['sample'])
            c.require(group['id'] not in seen and type(group['spans']) is list and group['spans'],'unique full group spans required');seen.add(group['id'])
            spans=[]
            for row in group['spans']:
                c.keys(row,('member','start','stop'),'physical group span')
                s,m=lookup.get((group['sample'],row['member']),(None,None));c.require(s is not None,'group cannot cross undeclared samples/normalizations')
                c.integer(row['start'],0,m['entries'],'group start');c.integer(row['stop'],1,m['entries'],'group stop')
                c.require(row['start']<row['stop'],'nonempty original group span required')
                spans.append({'sample':s['id'],**row,'group':group['id']})
            c.require(sum(x['stop']-x['start'] for x in spans)<=entries,'complete physical group exceeds prospective partition allocation; never split it')
            units.append((spans,[group['id']]));groups.append(deepcopy(group))
        for s,m in lookup.values():
            if m['entries']==0:units.append(([{'sample':s['id'],'member':m['id'],'start':0,'stop':0,'group':None}],[]))
    else:
        c.require(group_document is None,'independent entries do not adopt caller grouping')
        for s,m in lookup.values():
            for start in (range(0,m['entries'],entries) if m['entries'] else [0]):
                units.append(([{'sample':s['id'],'member':m['id'],'start':start,'stop':min(start+entries,m['entries']),'group':None}],[]))
    _cover(ds,[x for spans,_ in units for x in spans])
    parts=[];intervals=[];ids=[];size=0
    def emit():
        nonlocal intervals,ids,size
        if not intervals:return
        identity='p-'+c.digest({'intervals':intervals,'group_ids':ids})[:32]
        parts.append({'id':identity,'intervals':intervals,'group_ids':ids});intervals=[];ids=[];size=0
        c.require(len(parts)<=max_parts,'complete partition count exceeds declared allocation; no truncation')
    for spans,gids in units:
        n=sum(x['stop']-x['start'] for x in spans)
        if intervals and size+n>entries:emit()
        intervals.extend(spans);ids.extend(gids);size+=n
    emit();return parts,groups


def read_master(declaration,base,cap=None):
    owned=cap is None;cap=c.Capture() if owned else cap
    _,raw=cap.read(declaration,base,MAX_MASTER);m=c.strict(raw)
    c.keys(m,('schema_version','kind','base_spec','base_config','dataset_sha256','analysis_sha256','source_contract','grouping','groups','partition_entries','max_partitions','partitions','budget','owner','inputs'),'original partition master')
    c.require(type(m['schema_version']) is int and m['schema_version']==1 and m['kind']=='root-stream-partition-master' and m['source_contract']==sources(),'original master/source/schema/selection changed')
    c.pin(m['base_spec']);c.pin(m['base_config']);c.require(type(m['inputs']) is list,'full original master input pins required')
    for p in m['inputs']:cap.read(p,base,max(8*1024**2,p['size']))
    c.keys(m['grouping'],('kind','source','statement'),'physical independence/group premise')
    c.require(m['grouping']['kind'] in ('independent_entries','declared_groups'),'explicit source-bound independence or complete grouping required')
    c.pin(m['grouping']['source']);c.text(m['grouping']['statement'])
    cap.read(m['grouping']['source'],base,MAX_MASTER)
    m['master_sha256']=declaration['sha256'];m['master_pin']=deepcopy(declaration)
    _,state=owner_state(m);master_claims(m,state)
    if owned:cap.finish()
    return m


def bound_master(value,ds,a,base,cap):
    m=read_master(value['partitioning']['master'],base,cap)
    original=c.strict(cap.read(m['base_config'],base)[1]);c.config(original)
    c.require(original['schema_version']==1 and c.digest(ds)==m['dataset_sha256'] and c.digest(a)==m['analysis_sha256'],'master full member/analysis/weight/normalization identity differs')
    compared={k:v for k,v in value.items() if k not in ('schema_version','partitioning')};expected={k:v for k,v in original.items() if k!='schema_version'}
    compared=deepcopy(compared);expected=deepcopy(expected)
    seconds=compared['limits'].pop('max_seconds');total=expected['limits'].pop('max_seconds')
    c.require(compared==expected,'partition changed original schema/selection/runtime/weight/normalization/site')
    grouping=m['grouping'];doc=None if grouping['kind']=='independent_entries' else c.strict(cap.read(grouping['source'],base,MAX_MASTER)[1])
    parts,groups=partition_population(ds,grouping,doc,m['partition_entries'],m['max_partitions'])
    c.require(parts==m['partitions'] and groups==m['groups'],'original complete group/partition population differs')
    budget=m['budget'];c.keys(budget,('partition_seconds','merge_seconds','max_total_seconds'),'original aggregate budget')
    for v in budget.values():c.integer(v,1,86400,'finite original seconds')
    c.require(len(parts)*budget['partition_seconds']+budget['merge_seconds']<=budget['max_total_seconds']<=total,'partitioning cannot multiply original approved resource ceiling')
    p=value['partitioning']
    if p['operation']=='partition':
        c.require(seconds==budget['partition_seconds'] and any(x['id']==p['partition_id'] for x in parts),'exact original partition/budget required')
    else:c.require(seconds==budget['merge_seconds'] and len(p['completions'])==len(parts),'one complete original merge population and budget required')
    return m


def prepare(request,base,output):
    from ravel.physics import root_stream as s
    from ravel.workflow import science
    c.keys(request,('schema_version','specification','partition_entries','max_partitions','grouping','budget','owner'),'partition preparation request')
    c.require(type(request['schema_version']) is int and request['schema_version']==1,'partition planner schema1 required')
    cap=c.Capture();spec_path,spec_raw=cap.read(request['specification'],base);spec=c.strict(spec_raw);science.validate(spec)
    c.require(spec['schema_version']==2 and spec['mode']=='root-stream','actual ordinary root-stream scientific specification required')
    p,config0,ds,a=s._load(spec['task'],spec_path.parent,cap);c.require(config0['schema_version']==1,'master starts from full original stream, not a subset/replay')
    grouping=request['grouping'];c.keys(grouping,('kind','source','statement'),'source-bound independence/grouping')
    c.require(grouping['kind'] in ('independent_entries','declared_groups'),'physical entry law must be supplied, not inferred')
    c.text(grouping['statement']);gp,raw=cap.read(grouping['source'],base,MAX_MASTER)
    grouping=deepcopy(grouping);grouping['source']={**grouping['source'],'path':str(gp)}
    doc=None if grouping['kind']=='independent_entries' else c.strict(raw)
    parts,groups=partition_population(ds,grouping,doc,request['partition_entries'],request['max_partitions'])
    budget=request['budget'];c.keys(budget,('partition_seconds','merge_seconds','max_total_seconds'),'original partition budget')
    for v in budget.values():c.integer(v,1,86400,'original seconds')
    c.require(len(parts)*budget['partition_seconds']+budget['merge_seconds']<=budget['max_total_seconds']<=config0['limits']['max_seconds']<=spec['max_seconds'],'full partition/merge resources must fit original source plan')
    owner=owner_binding(request['owner'],base)
    owner['attempt_journal']={'directory':str(Path(owner['cycle'])/'root-stream-attempts'/request['specification']['sha256']),
        'capacity':len(parts)+1}
    out=Path(output).absolute();c.require(not out.exists(),'fresh immutable master required');s.custody._ordinary(out.parent,base,directory=True);out.mkdir()
    m={'schema_version':1,'kind':'root-stream-partition-master','base_spec':{**request['specification'],'path':str(spec_path)},
       'base_config':{**spec['task']['config'],'path':str(p)},'dataset_sha256':c.digest(ds),'analysis_sha256':c.digest(a),'source_contract':sources(),
       'grouping':deepcopy(grouping),'groups':groups,'partition_entries':request['partition_entries'],'max_partitions':request['max_partitions'],
       'partitions':parts,'budget':deepcopy(budget),'owner':owner,'inputs':list(cap.rows.values())}
    c.require(len(s.encoded(m))<=MAX_MASTER,'complete master exceeds declared metadata allocation')
    master=s.write_new(out/'master.json',m);reserve_master({**m,'master_pin':master});publications=[master];tasks=[]
    for part in parts:
        q=deepcopy(config0);q['schema_version']=2;q['limits']['max_seconds']=budget['partition_seconds']
        q['partitioning']={'master':master,'operation':'partition','partition_id':part['id'],'completions':[]}
        cp=s.write_new(out/(part['id']+'-config.json'),q);prospective=deepcopy(spec);prospective['task']={'config':cp};prospective['max_seconds']=budget['partition_seconds']
        sp=s.write_new(out/(part['id']+'-spec.json'),prospective);tasks.append({'partition_id':part['id'],'specification':sp});publications.extend([cp,sp])
    closure=s.write_new(out/'partition-plan-closure.json',{'schema_version':1,'kind':'root-stream-private-partition-plan','master':master,'files':publications})
    cap.finish();s.custody.asset_check({x['path']:x for x in [*publications,closure]})
    return {'master':master,'partition_specifications':tasks,'closure':closure,'machine_private':True,'execution_authorized':False,'scientific_acceptance_inferred':False}



def owner_binding(declaration,base):
    """Bind an existing original campaign, without creating or renewing it."""
    from ravel.workflow import research_cycle as cycle
    c.keys(declaration,('kind','cycle'),'original aggregate owner')
    c.require(declaration['kind']=='research_cycle','existing charged research-cycle owner required')
    root=Path(declaration['cycle']);root=root if root.is_absolute() else Path(base)/root
    root,state=cycle._load(root)
    return {'kind':'research_cycle','cycle':str(root),'contract_sha256':c.digest(state['contract']),
            'context_request_sha256':state['context']['request_sha256']}


def reservation_id(master):return 'root-stream-master:'+master['base_spec']['sha256']


def reservation(master):
    return {'id':reservation_id(master),'ceiling':{'calls':0,'output_tokens':0,
        'wall_seconds':master['budget']['max_total_seconds'],'native_attempts':len(master['partitions'])+1},
        'basis':deepcopy(master['master_pin'])}



def owner_phase_guard(state):
    """Do not spend master allocation through a pending existing phase gate."""
    from ravel.workflow import research_cycle as cycle
    phase=cycle._phase_allocation(state)
    if phase is None:return
    completed=set(phase['ordinary_current_completed_check_ids'])
    required={identity for identities in state['phase_policy']['preconstruction_checks'].values() for identity in identities}
    c.require(not any(phase['actual_usage_overrun'].values()) and not any(phase['check_reservation_deficits'].values()) and
        not required-completed,'original campaign scientific checking reservations remain incomplete')


def owner_state(master):
    from ravel.workflow import research_cycle as cycle
    owner=master['owner'];c.keys(owner,('kind','cycle','contract_sha256','context_request_sha256','attempt_journal'),'original bound campaign')
    c.require(owner['kind']=='research_cycle' and Path(owner['cycle']).is_absolute(),'original absolute owner required')
    root,state=cycle._load(owner['cycle'])
    c.require(c.digest(state['contract'])==owner['contract_sha256'] and
        state['context']['request_sha256']==owner['context_request_sha256'],'original aggregate owner changed')
    rows=[x for x in state['resource_ledger'] if x['id']==reservation_id(master)]
    c.require(rows==[reservation(master)],'original complete master reservation missing/changed; no fresh owner or allocation')
    cycle._check_pin(master['master_pin'],root);owner_phase_guard(state)
    journal=owner['attempt_journal'];c.keys(journal,('directory','capacity'),'typed master attempt capacity')
    c.require(journal['directory']==str(root/'root-stream-attempts'/master['base_spec']['sha256']) and
        journal['capacity']==len(master['partitions'])+1 and 2<=journal['capacity']<=10001,
        'complete canonical typed attempt journal required')
    return root,state


def reserve_master(master):
    """Debit the whole allocation once through the existing durable journal.

    Failure/unknown status never refunds this ceiling. Re-preparing the same
    original specification in another directory under this owner refuses.
    """
    from ravel.workflow import research_cycle as cycle,state_io
    owner=master['owner'];root=Path(owner['cycle'])
    with state_io.file_lock(root/'operation.lock',blocking=False):
        _,state=cycle._load(root)
        c.require(c.digest(state['contract'])==owner['contract_sha256'] and
            state['context']['request_sha256']==owner['context_request_sha256'],'original owner changed before reservation')
        owner_phase_guard(state)
        # One ordinary campaign reservation; bounded claim transport does not
        # consume one generic role/campaign revision per partition.
        row=reservation(master);cycle._check_pin(row['basis'],root)
        cycle._charge(state,row['id'],row['ceiling'],row['basis'])
        c.require(state['revision']+2<cycle.MAX_REVISIONS,'original owner needs reservation and first-clock revision capacity')
        directory=Path(owner['attempt_journal']['directory']);cycle._ordinary(directory)
        c.require(not directory.exists(),'original attempt journal cannot be replaced or reset')
        directory.parent.mkdir(exist_ok=True);directory.mkdir();(directory/'history').mkdir()
        from ravel.physics import root_stream as stream
        genesis=stream.write_new(directory/'history/00000.json',{'schema_version':1,'kind':'root-stream-master-attempt-genesis',
            'revision':0,'master':deepcopy(master['master_pin']),'capacity':owner['attempt_journal']['capacity']})
        state_io.atomic_json(directory/'head.json',genesis)
        cycle._commit(root,state,'root_stream_master_reserved',master=deepcopy(row['basis']),reservation_id=row['id'],attempt_genesis=genesis)
    owner_state(master)


def attempt_history(master,state):
    """Bounded constant-size predecessor records; no quadratic snapshots.

    The existing campaign reservation anchors genesis. Missing/truncated history,
    rollback with retained later records, changed ancestry or capacity refuses.
    """
    from ravel.workflow import research_cycle as cycle
    directory=cycle._ordinary(master['owner']['attempt_journal']['directory'])
    cap=c.Capture();head_path=directory/'head.json'
    head=cap.document(cycle._pin(head_path),directory)
    c.pin(head);path=Path(head['path'])
    c.require(path.parent==directory/'history' and path.name.endswith('.json'),'canonical current attempt head required')
    revision=int(path.stem);capacity=master['owner']['attempt_journal']['capacity']
    c.require(0<=revision<=capacity and path.name==f'{revision:05d}.json','complete bounded attempt history required')
    actual=[]
    for item in sorted((directory/'history').iterdir()):
        c.require(not item.is_symlink() and item.is_file(),'ordinary complete attempt history members required')
        actual.append(item.name)
    c.require(actual==[f'{i:05d}.json' for i in range(revision+1)],'missing, extra or rolled-back original attempt history')
    pins=[];records=[]
    for i in range(revision+1):
        pin=cycle._pin(directory/'history'/f'{i:05d}.json');record=cap.document(pin,directory)
        if i==0:
            c.keys(record,('schema_version','kind','revision','master','capacity'),'attempt genesis')
            c.require(record=={'schema_version':1,'kind':'root-stream-master-attempt-genesis','revision':0,
                'master':master['master_pin'],'capacity':capacity},'original typed attempt genesis changed')
            anchors=[e for e in state['events'] if e['kind']=='root_stream_master_reserved' and e['master']==master['master_pin']]
            c.require(len(anchors)==1 and anchors[0]['attempt_genesis']==pin,'original campaign must authenticate attempt genesis')
        else:
            c.keys(record,('schema_version','kind','revision','master','parent','claim'),'retained original attempt record')
            c.require(type(record['schema_version']) is int and record['schema_version']==1 and
                record['kind']=='root-stream-master-attempt-claim' and record['revision']==i and
                record['master']==master['master_pin'] and record['parent']==pins[-1],'original attempt ancestry differs')
        pins.append(pin);records.append(record)
    c.require(pins[-1]==head,'actual head differs from retained original attempt')
    cap.finish();return directory,head,records


def master_claims(master,state):
    _,_,history=attempt_history(master,state);rows=[deepcopy(e['claim']) for e in history[1:]]
    expected={x['id']:master['budget']['partition_seconds'] for x in master['partitions']}
    expected['merge']=master['budget']['merge_seconds'];seen=set();rundirs=set()
    for row in rows:
        c.keys(row,('master','task_id','rundir','attempt_id','fingerprint','seconds','started_epoch','deadline_epoch'),'retained attempt claim')
        c.require(row['master']==master['master_pin'] and row['task_id'] in expected and row['task_id'] not in seen and row['rundir'] not in rundirs and
            row['seconds']==expected[row['task_id']],'canonical partition/merge attempt allocation changed')
        c.require(row['deadline_epoch']==rows[0]['deadline_epoch'] and
            row['deadline_epoch']==rows[0]['started_epoch']+master['budget']['max_total_seconds'],
            'original master deadline cannot be renewed')
        seen.add(row['task_id']);rundirs.add(row['rundir'])
    c.require(sum(x['seconds'] for x in rows)<=master['budget']['max_total_seconds'],'retained failed/unknown spend exceeds master')
    return rows



def campaign_reservation(spec,base,root,cost):
    """Attribute an exact branch to its already charged original campaign master.

    No caller token or held-lock inference supplies authority. The selected
    source, full master, reservation, current phase and input population are
    authenticated through the same readers used by the worker.
    """
    from ravel.physics import root_stream as stream
    from ravel.workflow import research_cycle as cycle
    if spec.get('mode')!='root-stream':return None
    cap=c.Capture();path,value,ds,a=stream._load(spec['task'],base,cap)
    if value['schema_version']!=2:cap.finish();return None
    master=bound_master(value,ds,a,stream.source_base(value,path.parent),cap)
    c.require(Path(master['owner']['cycle'])==cycle._ordinary(root),
        'partition experiment must use its original aggregate campaign owner')
    c.require(spec['max_seconds']==value['limits']['max_seconds'] and
        cost['wall_seconds']>=spec['max_seconds'] and cost['native_attempts']==1,
        'original exact branch ceiling and one operation cost required')
    incremental=deepcopy(cost);incremental['wall_seconds']-=spec['max_seconds']
    incremental['native_attempts']=0
    cap.finish()
    return {'master':deepcopy(master['master_pin']),'incremental_cost':incremental}


def campaign_attempt(master,state,rundir):
    """Repeat the actual campaign's parent/phase admission in the worker lock.

    Standalone ordinary studies still use the same master claim authority.
    A registered experiment additionally requires the exact durable campaign
    dispatch boundary; a direct worker cannot substitute a planning record.
    """
    from ravel.workflow import research_cycle as cycle,science
    actual=science.root(rundir)
    # Authenticate each retained ordinary directory, including legacy lexical
    # '..' spellings. An invalid/aliased roster cannot prove standalone status.
    matches=[e for e in state['experiments'] if e['rundir'] is not None and science.root(e['rundir'])==actual]
    if not matches:return
    c.require(len(matches)==1,'one actual campaign experiment must own the run')
    e=cycle._experiment_dispatch_admission(state,matches[0]['id'])
    allocation=cycle._experiment_reservation(state,e,master['owner']['cycle'])
    c.require(allocation is not None and allocation['master']==master['master_pin'],
        'current original master must fund this campaign experiment')
    event=next((x for x in reversed(state['events']) if x['kind']=='ordinary_study_dispatch_boundary' and
        x['experiment_id']==e['id']),None)
    c.require(event is not None and event.get('partition_master')==master['master_pin'] and
        event.get('plan')==e['plan'] and event.get('study')==e['study'],
        'actual current campaign dispatch admission required before partition claim')
    reservation_row=[r for r in state['resource_ledger'] if r['id']=='experiment:'+e['id']]
    c.require(reservation_row==[{'id':'experiment:'+e['id'],'ceiling':allocation['incremental_cost'],
        'basis':e['study']}],'exact attributed experiment cost cannot be replaced or renewed')

def claim_dispatch(value,ds,a,base,rundir):
    """Actual worker boundary, also reached by direct science.run (not just WMS)."""
    from ravel.workflow import research_cycle as cycle,state_io,science,execution
    import time
    cap=c.Capture();master=bound_master(value,ds,a,base,cap);root=Path(master['owner']['cycle'])
    with state_io.file_lock(root/'operation.lock',blocking=False):
        _,state=owner_state(master);campaign_attempt(master,state,rundir);rows=master_claims(master,state)
        task_id=value['partitioning']['partition_id'] if value['partitioning']['operation']=='partition' else 'merge'
        rd=science.root(rundir);selected=science.verify_worker(rd);record=execution.load_execution(rd)['stages']['science']
        spec=science.execution_spec(rd)
        c.require(spec['mode']=='root-stream','actual ordinary ROOT mode required');cap_config(value,rd)
        c.require(record['status']=='running' and record['fingerprint']==selected['stage_binding']['fingerprint'],
            'current approved registered ordinary attempt required')
        c.require(task_id not in {x['task_id'] for x in rows} and str(rd) not in {x['rundir'] for x in rows},
            'original partition/merge claim already charged; failed/unknown attempts cannot renew through another run')
        now=time.time();deadline=rows[0]['deadline_epoch'] if rows else now+master['budget']['max_total_seconds']
        seconds=value['limits']['max_seconds']
        c.require(seconds<=deadline-now,'original master deadline cannot fit the declared branch')
        first_clock=state['timing']['started_epoch'] is None
        refusal=cycle._clock(state,seconds)
        if refusal is not None:
            state['operational_boundaries'].append({'operation':reservation_id(master),**refusal})
            cycle._commit(root,state,'operational_boundary_retained',operation=reservation_id(master))
            raise cycle.OperationalBoundaryError('original campaign cannot fit partition branch')
        claim={'master':deepcopy(master['master_pin']),'task_id':task_id,'rundir':str(rd),
            'attempt_id':record['attempt_id'],'fingerprint':record['fingerprint'],'seconds':seconds,
            'started_epoch':now,'deadline_epoch':deadline}
        if first_clock:state=cycle._commit(root,state,'root_stream_master_first_dispatch',master=deepcopy(master['master_pin']))
        directory,head,history=attempt_history(master,state);revision=len(history)
        c.require(revision<=master['owner']['attempt_journal']['capacity'],'complete original attempt capacity exhausted')
        cap.finish()
        from ravel.physics import root_stream as stream
        pin=stream.write_new(directory/'history'/f'{revision:05d}.json',{'schema_version':1,
            'kind':'root-stream-master-attempt-claim','revision':revision,'master':deepcopy(master['master_pin']),
            'parent':head,'claim':claim})
        # An interrupted publication has an extra retained history member and
        # refuses; it cannot silently renew the slot through the old head.
        state_io.atomic_json(directory/'head.json',pin)
    # A crash after source-committed claim publication remains charged/unknown.
    _,state=owner_state(master);c.require(claim in master_claims(master,state),'ending original attempt claim differs')
    return claim



def dispatch_current(value,ds,a,base,rundir):
    """Recheck the retained claim and both fixed deadlines after runtime setup."""
    from ravel.workflow import execution,science
    import time
    cap=c.Capture();master=bound_master(value,ds,a,base,cap);_,state=owner_state(master)
    campaign_attempt(master,state,rundir)
    task_id=value['partitioning']['partition_id'] if value['partitioning']['operation']=='partition' else 'merge'
    rows=[x for x in master_claims(master,state) if x['task_id']==task_id]
    record=execution.load_execution(rundir)['stages']['science']
    c.require(len(rows)==1 and rows[0]['rundir']==str(science.root(rundir)) and
        rows[0]['attempt_id']==record['attempt_id'] and rows[0]['fingerprint']==record['fingerprint'] and
        record['status']=='running','actual original charged running partition/merge required')
    cap.finish();now=time.time();seconds=value['limits']['max_seconds']
    c.require(state['timing']['deadline_epoch'] is not None and seconds<=state['timing']['deadline_epoch']-now and
        seconds<=rows[0]['deadline_epoch']-now,'original aggregate/owner deadline cannot fit native branch')
    return rows[0]


@contextmanager
def effect_dispatch(value,ds,a,base,rundir):
    """Worker-owned final admission and effect; parent is already unlocked.

    Runtime/input staging precedes this lock. The ROOT reader child does not
    acquire the campaign claim lock; the merge only reads its source evidence.
    A late refused branch retains its already published charged claim.
    """
    from ravel.workflow import state_io
    cap=c.Capture();master=bound_master(value,ds,a,base,cap)
    root=Path(master['owner']['cycle'])
    with state_io.file_lock(root/'operation.lock',blocking=False):
        cap.finish()
        claim=dispatch_current(value,ds,a,base,rundir)
        yield claim


def cap_config(value,rundir):
    from ravel.workflow import science
    declaration=science.execution_spec(rundir)['task']['config'];cap=c.Capture()
    path,raw=cap.read(declaration,rundir,MAX_MASTER)
    c.require(c.strict(raw)==value,'actual selected source configuration differs');cap.finish();return path


def require_claim(master,rundir,task_id,receipt):
    from ravel.workflow import execution
    _,state=owner_state(master);rows=master_claims(master,state)
    record=execution.load_execution(rundir)['stages']['science']
    selected=[x for x in rows if x['task_id']==task_id]
    c.require(len(selected)==1 and selected[0]['rundir']==str(Path(rundir).absolute()) and
        selected[0]['attempt_id']==record['attempt_id'] and selected[0]['fingerprint']==receipt['fingerprint'] and
        record['status']=='succeeded','original master charged successful ordinary attempt required')
    return selected[0]


def dispatch_identity(task,base,cap):
    from ravel.physics import root_stream as s
    _,value,ds,a=s._load(task,base,cap)
    if value['schema_version']==1:return None
    master=bound_master(value,ds,a,base,cap)
    return (master['owner']['cycle'],reservation_id(master),
        value['partitioning']['partition_id'] if value['partitioning']['operation']=='partition' else 'merge')


def validate_partial(value,m,part,ds,a,limits):
    c.keys(value,('schema_version','status','delivery','identities','physics_validated'),'original partition native result')
    c.require(type(value['schema_version']) is int and value['schema_version']==1 and value['status']=='passed' and value['physics_validated'] is False,'partition delivery only')
    d=value['delivery'];c.keys(d,('schema_version','kind','master_sha256','partition_id','sampling_law','coverage','coverage_sha256','group_ids','samples','normalization_applied','physics_validated'),'raw partition moments')
    law=pc.GROUP_LAW if m['grouping']['kind']=='declared_groups' else pc.ENTRY_LAW
    c.require(d['kind']=='root-stream-partition-moments' and type(d['schema_version']) is int and d['schema_version']==1 and d['master_sha256']==m['master_sha256'] and d['partition_id']==part['id'] and d['sampling_law']==law and d['group_ids']==part['group_ids'] and d['normalization_applied'] is False and d['physics_validated'] is False,'partition source/group/normalization correspondence differs')
    c.require(type(d['coverage']) is list and len(d['coverage'])<=limits['max_chunks'] and d['coverage_sha256']==c.digest(d['coverage']),'full partition coverage commitment required')
    i=0;offset=part['intervals'][0]['start']
    for row in d['coverage']:
        c.keys(row,('sample','member','start','stop'),'partition chunk')
        c.require(i<len(part['intervals']),'replayed partition chunk');target=part['intervals'][i]
        c.require(type(row['start']) is int and type(row['stop']) is int and (row['sample'],row['member'],row['start'])==(target['sample'],target['member'],offset) and
                  (offset<row['stop']<=target['stop'] or offset==row['stop']==target['stop']==0) and row['stop']-offset<=limits['chunk_entries'],'partition original interval gap/overlap/change')
        offset=row['stop']
        if offset==target['stop']:
            i+=1;offset=part['intervals'][i]['start'] if i<len(part['intervals']) else 0
    c.require(i==len(part['intervals']),'partition missing original intervals')
    selected={x['member'] for x in part['intervals']};members=[x for s in ds['samples'] for x in s['members'] if x['id'] in selected]
    c.require([x['member'] for x in value['identities']]==[x['id'] for x in members],'full unique touched member identity roster required')
    for member,row in zip(members,value['identities']):
        c.keys(row,('member','before','after','evidence_scope'),'original member identity');c.text(row['evidence_scope'])
        expected={'guid':member['guid'],'size_bytes':member['size_bytes'],'checksum':{k:member['checksum'][k] for k in ('algorithm','value')},'entries':member['entries']}
        c.require(row['before']==row['after']==expected,'partition source changed between original reads')
    c.require([r['id'] for r in d['samples']]==[s['id'] for s in ds['samples']],'partition full sample schema/order differs')
    group_samples={g['id']:g['sample'] for g in m['groups']}
    for sample,row in zip(ds['samples'],d['samples']):
        c.keys(row,('id','raw_mc_partials','quantities'),'partition raw sample')
        c.require(set(row['quantities'])=={q['id'] for q in a['quantities']},'all partition quantity/variation schemas required')
        entries=sum(x['stop']-x['start'] for x in part['intervals'] if x['sample']==sample['id'])
        records=sum(group_samples[g]==sample['id'] for g in part['group_ids']) if m['grouping']['kind']=='declared_groups' else entries
        for q in a['quantities']:
            moment=pc.restore_moments(row['quantities'][q['id']],q['contract'])
            c.require(moment.counts['records']==records if sample['kind']!='data' else moment.counts['records']<=records,'full physical-group/entry count differs')
        if sample['kind']=='data':c.require(row['raw_mc_partials'] is None,'DATA cannot acquire MC record weights')
        else:
            c.keys(row['raw_mc_partials'],('sumw','sumw2','record_sumw2'),'complete raw generator moments')
            for key,values in row['raw_mc_partials'].items():
                c.require(type(values) is list and len(values)<=2048,'full generator expansion required');total=c.Adder()
                for x in values:total.add(c.scalar(x))
                if key!='sumw':c.require(total.value()>=0,'nonnegative original second moment required')
    return value


def input_base(value,default):
    if value.get('schema_version')!=2:return Path(default)
    m=read_master(value['partitioning']['master'],default)
    return Path(m['base_config']['path']).parent


def public_partial(value,m,part,ds,a,limits):
    validate_partial(value,m,part,ds,a,limits)
    rows=[]
    for sample,row in zip(ds['samples'],value['delivery']['samples']):
        if sample['kind']=='data':rows.append({'id':sample['id'],'kind':'data','restricted_completion_sha256':c.digest(row),'visibility':'partition_machine_record_only_no_DATA_counts'})
        else:
            quantities={}
            for q in a['quantities']:
                quantities[q['id']]=pc.restore_moments(row['quantities'][q['id']],q['contract']).result(1.)
            rows.append({'id':sample['id'],'kind':sample['kind'],'dsid':sample['dsid'],'raw_quantities':quantities,'normalization_applied':False})
    return {'schema_version':1,'kind':'root-stream-public-partition','master_sha256':m['master_sha256'],'partition_id':part['id'],'samples':rows,
            'complete_original_study':False,'normalization_applied':False,'physics_validated':False}


def completion(declaration,base,master,ds,a,cap):
    from ravel.physics import root_stream as s
    _,raw=cap.read(declaration,base,MAX_MASTER);record=c.strict(raw)
    c.keys(record,('schema_version','kind','master','partition_id','rundir','task','outputs','raw_native','closure','fingerprint'),'persisted ordinary partition completion')
    c.require(record['schema_version']==1 and type(record['schema_version']) is int and record['kind']=='root-stream-ordinary-partition-completion' and record['master']==master['master_pin'],'original persisted master correspondence differs')
    part=next((x for x in master['partitions'] if x['id']==record['partition_id']),None);c.require(part is not None,'foreign/replayed partition identity')
    canonical=Path(master['master_pin']['path']).parent/'completed'/(record['partition_id']+'.json')
    c.require(Path(declaration['path']).absolute()==canonical,'original canonical completion record required')
    rd=Path(record['rundir']).absolute();receipt=s.ordinary_delivery(rd,expected_task=record['task']);require_claim(master,rd,part['id'],receipt)
    _,config0,actual_ds,actual_a=s._load(record['task'],rd,cap)
    c.require(actual_ds==ds and actual_a==a,'completion original scientific source changed')
    c.require(config0.get('partitioning')=={'master':record['master'],'operation':'partition','partition_id':part['id'],'completions':[]} and
              receipt['outputs']==record['outputs'] and receipt['fingerprint']==record['fingerprint'],'completion is not current original succeeded partition attempt')
    out=Path(receipt['output_directory'])/'root-stream';g=s.guard(receipt['result'],out);full,req=s.private_delivery(g)
    c.require(g.native_pin==record['raw_native'] and receipt['result']['commitment']==record['closure'] and req['dataset']==ds and req['analysis']==a,'original native/raw/closure/full scientific source correspondence differs')
    validate_partial(full,master,part,ds,a,config0['limits']);g.finish(receipt['result'],common=out.parent)
    from ravel.workflow import science
    for path in science.review_waypoint_paths(rd):
        p=Path(path);cap.read({'path':str(p),'sha256':s.custody.custody._hash(p),'size':p.stat().st_size},rd,max(8*1024**2,p.stat().st_size))
    cap.read(record['raw_native'],rd,max(8*1024**2,record['raw_native']['size']));c.require(record['closure']['size']<=MAX_MASTER,'complete closure allocation exceeded');cap.read(record['closure'],rd,max(8*1024**2,record['closure']['size']))
    return record,full,receipt


def record(master_pin,partition_id,rundir,output):
    from ravel.physics import root_stream as s
    cap=c.Capture();master=read_master(master_pin,Path(rundir),cap);rd=Path(rundir).absolute()
    receipt=s.ordinary_delivery(rd);require_claim(master,rd,partition_id,receipt);task=s.ordinary_plan_destination(rd)[1]['task'];_,cfg,ds,a=s._load(task,rd,cap)
    c.require(cfg['partitioning']=={'master':master_pin,'operation':'partition','partition_id':partition_id,'completions':[]},'exact original succeeded partition task required')
    part=next((x for x in master['partitions'] if x['id']==partition_id),None);c.require(part is not None,'foreign partition')
    destination=Path(receipt['output_directory'])/'root-stream';g=s.guard(receipt['result'],destination);full,req=s.private_delivery(g)
    validate_partial(full,master,part,ds,a,cfg['limits'])
    value={'schema_version':1,'kind':'root-stream-ordinary-partition-completion','master':deepcopy(master_pin),'partition_id':partition_id,
           'rundir':str(rd),'task':deepcopy(task),'outputs':deepcopy(receipt['outputs']),'raw_native':deepcopy(g.native_pin),
           'closure':deepcopy(receipt['result']['commitment']),'fingerprint':receipt['fingerprint']}
    path=Path(output).absolute();c.require(path.parent==Path(master_pin['path']).parent/'completed' and path.name==partition_id+'.json','canonical master completion path required')
    path.parent.mkdir(exist_ok=True);g.finish(receipt['result'],common=destination.parent);cap.finish();pin=s.write_new(path,value)
    completion(pin,path.parent,master,ds,a,cap);cap.finish();return pin


def resume(master_pin,records,base):
    from ravel.physics import root_stream as s
    cap=c.Capture();m=read_master(master_pin,base,cap);cfg=cap.document(m['base_config'],base)
    _,_,ds,a=s._load({'config':m['base_config']},base,cap);seen=set();origins=[]
    for declaration in records:
        row,_,receipt=completion(declaration,base,m,ds,a,cap)
        c.require(row['partition_id'] not in seen and row['rundir'] not in {x[0] for x in origins},'duplicate/replayed original completion')
        seen.add(row['partition_id']);origins.append((row['rundir'],receipt))
    _,state=owner_state(m);claims=master_claims(m,state)
    claimed={row['task_id'] for row in claims}
    cap.finish()
    for rd,receipt in origins:c.require(s.ordinary_delivery(rd)==receipt,'ending persisted completion authority differs')
    cap.finish()
    return {'master_sha256':master_pin['sha256'],'complete_partition_ids':[x['id'] for x in m['partitions'] if x['id'] in seen],
            'pending_partition_ids':[x['id'] for x in m['partitions'] if x['id'] not in seen and x['id'] not in claimed],
            'blocked_claimed_partition_ids':[x['id'] for x in m['partitions'] if x['id'] not in seen and x['id'] in claimed],
            'retained_attempt_claims':deepcopy(claims),'reserved_master_seconds':m['budget']['max_total_seconds'],
            'charged_attempt_seconds':sum(row['seconds'] for row in claims),'machine_private':True,
            'execution_authorized':False,'failed_attempt_renewed':False,'scientific_acceptance_inferred':False}


def _completions(value,ds,a,base,cap):
    m=bound_master(value,ds,a,base,cap);p=value['partitioning']
    c.require(p['operation']=='merge','complete merge operation required')
    seen=set();runs=set();records=[];origins=[]
    for declaration in p['completions']:
        record,raw,receipt=completion(declaration,base,m,ds,a,cap)
        c.require(record['partition_id'] not in seen and record['rundir'] not in runs,'duplicate/replayed partition completion refused')
        seen.add(record['partition_id']);runs.add(record['rundir']);records.append((record,raw));origins.append((record['rundir'],receipt))
    c.require(seen=={x['id'] for x in m['partitions']},'complete original partition roster required before normalization')
    rank={x['id']:i for i,x in enumerate(m['partitions'])};records.sort(key=lambda x:rank[x[0]['partition_id']])
    return m,records,origins


def merge(value,ds,a,base):
    """Recompute complete raw expansions, then apply ONE original DSID scale.

    Called by the existing ordinary root-stream worker and source guard. No
    incomplete partition is a complete scientific study or normalized consumer.
    """
    from ravel.physics import root_stream as s
    cap=c.Capture();m,records,origins=_completions(value,ds,a,base,cap)
    result=_aggregate(m,records,ds,a,value['limits'])
    # Full current attempt/approval/result/source checks AFTER all aggregate reads.
    for rd,receipt in origins:c.require(s.ordinary_delivery(rd)==receipt,'ending ordinary partition completion changed')
    cap.finish();return result


def merge_specification(master_pin,records,base,output):
    from ravel.physics import root_stream as s
    cap=c.Capture();m=read_master(master_pin,base,cap)
    _,original,ds,a=s._load({'config':m['base_config']},base,cap)
    spec=cap.document(m['base_spec'],base);cfg=deepcopy(original);cfg['schema_version']=2;cfg['limits']['max_seconds']=m['budget']['merge_seconds']
    cfg['partitioning']={'master':deepcopy(master_pin),'operation':'merge','partition_id':None,'completions':deepcopy(records)}
    # Consume actual complete succeeded ordinary delivery before writing a merge
    # draft; no caller-created completion file or merely passed bit is admitted.
    _,_,origins=_completions(cfg,ds,a,base,cap)
    out=Path(output).absolute();c.require(not out.exists(),'fresh merge draft directory required');s.custody._ordinary(out.parent,base,directory=True);out.mkdir()
    cp=s.write_new(out/'merge-config.json',cfg);spec['task']={'config':cp};spec['max_seconds']=m['budget']['merge_seconds']
    sp=s.write_new(out/'merge-specification.json',spec)
    closure=s.write_new(out/'merge-plan-closure.json',{'schema_version':1,'kind':'root-stream-private-merge-plan','master':master_pin,'files':[cp,sp]})
    for rd,receipt in origins:c.require(s.ordinary_delivery(rd)==receipt,'ending original partition delivery changed')
    cap.finish();s.custody.asset_check({x['path']:x for x in (cp,sp,closure)})
    return {'specification':sp,'closure':closure,'machine_private':True,'execution_authorized':False,'scientific_acceptance_inferred':False}


def _aggregate(m,records,ds,a,limits):
    """Internal exact raw-moment reduction; no execution-origin authority."""
    c.require(c.digest(ds)==m['dataset_sha256'] and c.digest(a)==m['analysis_sha256'],'original complete population/selection/normalization/weight identity required')
    c.require([record['partition_id'] for record,raw in records]==[part['id'] for part in m['partitions']],'exact original disjoint partition order and population required')
    for (record,raw),part in zip(records,m['partitions']):validate_partial(raw,m,part,ds,a,limits)
    moments={sample['id']:{q['id']:c.Moments(q['contract']) for q in a['quantities']} for sample in ds['samples']}
    generator={sample['id']:{name:c.Adder() for name in ('sumw','sumw2','record_sumw2')} for sample in ds['samples'] if sample['kind']!='data'}
    coverage=[];identities={}
    for record,raw in records:
        coverage.extend(deepcopy(raw['delivery']['coverage']))
        for row in raw['identities']:
            old=identities.get(row['member']);c.require(old is None or old==row,'shared original member identity changed across partitions')
            identities[row['member']]=deepcopy(row)
        for sample,row in zip(ds['samples'],raw['delivery']['samples']):
            for q in a['quantities']:pc.merge_moments(moments[sample['id']][q['id']],row['quantities'][q['id']])
            if sample['kind']!='data':
                for name,partials in row['raw_mc_partials'].items():
                    for part in partials:generator[sample['id']][name].add(part)
    coverage=_cover(ds,coverage);c.require(len(coverage)<=limits['max_chunks'],'full aggregate chunk allocation exceeded')
    member_order=[member['id'] for sample in ds['samples'] for member in sample['members']]
    c.require(set(identities)==set(member_order),'complete original file identity census required')
    grouped=m['grouping']['kind']=='declared_groups';samples=[]
    for sample in ds['samples']:
        quantities={}
        for q in a['quantities']:
            result=moments[sample['id']][q['id']].result(c.scale(sample))
            if grouped:result['identity_scope']=pc.IDENTITY
            quantities[q['id']]=result
        raw=None if sample['kind']=='data' else {
            'sumw':generator[sample['id']]['sumw'].value(),'sumw2':generator[sample['id']]['sumw2'].value(),
            'scope':'analyzed original entries; retained full denominator is separate'}
        if grouped and raw is not None:
            raw['record_sumw2']=generator[sample['id']]['record_sumw2'].value()
            raw['scope']='complete declared physical groups; record_sumw2 retains original entry squares; full denominator is separate'
        samples.append({'id':sample['id'],'kind':sample['kind'],'dsid':sample['dsid'],'normalization':deepcopy(sample['normalization']),
            'raw_mc_weights':raw,'weight_contract':deepcopy(a['weight_contract']),'quantities':quantities})
    delivery={'schema_version':1,'kind':'root-stream-moments','samples':samples,'coverage':coverage,'coverage_sha256':c.digest(coverage),
        'sampling_law':pc.GROUP_LAW if grouped else pc.ENTRY_LAW,
        'blinding':'Restricted machine census; public DATA projection requires original allowed-model-fields policy','physics_validated':False}
    if grouped:delivery['physical_grouping']={'master':deepcopy(m['master_pin']),'source':deepcopy(m['grouping']['source']),
        'group_ids':[g['id'] for g in m['groups']],'statement':m['grouping']['statement']}
    result={'schema_version':1,'status':'passed','delivery':delivery,'identities':[identities[x] for x in member_order],'physics_validated':False}
    return result


def private_source(path,digest):
    """Fixed original planner namespace is machine-only, including role copies.

    The original source path/digest is supplied by the existing Host provenance
    path. Arbitrary out-of-band text copying is not a hostile-code sandbox.
    """
    import os
    source=Path(path).absolute()
    for owner in source.parents:
        if owner.parent.name=='root-stream-attempts' and any(os.path.lexists(owner/name) for name in ('head.json','history')):
            raise ValueError('restricted original partition attempt journal cannot enter model context')
        if any(os.path.lexists(owner/name) for name in ('master.json','partition-plan-closure.json','merge-plan-closure.json')):
            raise ValueError('restricted original partition master/completion/input namespace cannot enter model context')
    return False
