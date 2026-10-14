"""Source-bound ROOT read outcomes, not a new execution or provenance authority.

The admitted reader owns this output. Roles come from the original pinned
acquisition declaration; these documentary bindings do not prove detector truth,
actor identity or server immutability. Original intervals and signed normalization
survive unsuccessful reading. No partial moment or synthetic replacement is made.
"""
from copy import deepcopy
from pathlib import Path
import hashlib
from ravel.physics import root_stream_core as core

ROLES = ('observed', 'supplied_mc', 'generated_simulation', 'calibration', 'software_fixture')
STATES = ('read_complete', 'read_partial', 'read_failed', 'acquisition_missing')
CONTRACT = 'root-data-read-contract'



def _capture_artifact(declaration, base, capture):
    """Bridge ordinary path/hash artifacts to the unchanged strict pin3 capture.

    Only these existing plan/result edges admit pin2. Supplied pin3 sizes remain
    authoritative and checked; source/acquisition contracts remain strict pin3.
    A bounded current read authenticates the original hash before adding the
    observed complete byte count. Capture then rereads that exact identity and
    owns the ordinary ending check, without inventing historical size authority.
    """
    if type(declaration) is dict and set(declaration)=={'path','sha256','size'}:
        return capture.read(declaration,base)
    core.keys(declaration,('path','sha256'),'ordinary plan/result artifact pin')
    # Validate the existing path/hash syntax with the strict schema. The zero is
    # only a validation placeholder; it is never passed to Capture or retained.
    core.pin({**declaration,'size':0})
    from ravel.physics.dataset_query_quantities_core import MAX_DOCUMENT
    from ravel.workflow.research_cycle import _bounded_source_snapshot
    requested=Path(declaration['path'])
    path,raw=_bounded_source_snapshot(requested if requested.is_absolute() else Path(base)/requested,MAX_DOCUMENT)
    core.require(hashlib.sha256(raw).hexdigest()==declaration['sha256'],
                 'ordinary artifact bytes differ from admitted hash')
    return capture.read({'path':str(path),'sha256':declaration['sha256'],'size':len(raw)},path.parent)

def bound_contract(declaration, task, config, dataset, analysis, base, capture):
    """Compare the complete original source contract, never caller role guesses."""
    value = capture.document(declaration, base)
    core.keys(value, ('schema_version', 'kind', 'source_authority', 'config', 'dataset',
                     'analysis', 'original_goal'), 'data read contract')
    core.require(type(value['schema_version']) is int and value['schema_version'] == 1
                 and value['kind'] == CONTRACT, 'finite original ROOT read contract required')
    for name, actual in (('config', task['config']), ('dataset', config['dataset']),
                         ('analysis', config['analysis']), ('original_goal', analysis['original_goal'])):
        core.require(value[name] == actual, 'read contract changed original ' + name)
        # _load already read the task config in its original caller base. Other
        # scientific pins use the config document's own base, as the reader does.
        if name != 'config': capture.read(value[name], base)
    authority = validate_authority(value['source_authority'], dataset, analysis, base, capture)
    return deepcopy(value), deepcopy(authority)


def validate_authority(declaration, dataset, analysis, base, capture):
    authority = capture.document(declaration, base)
    core.keys(authority, ('schema_version', 'kind', 'original_goal_sha256', 'sources'), 'original acquisition authority')
    core.require(type(authority['schema_version']) is int and authority['schema_version'] == 1
                 and authority['kind'] == 'data-acquisition-source-authority'
                 and authority['original_goal_sha256'] == analysis['original_goal']['sha256'],
                 'original acquisition goal differs')
    expected = [(s, m) for s in dataset['samples'] for m in s['members']]
    core.require(type(authority['sources']) is list and len(authority['sources']) == len(expected),
                 'complete original source-role population required')
    for row, (sample, member) in zip(authority['sources'], expected):
        core.keys(row, ('sample', 'member', 'role', 'availability', 'acquisition_source',
                        'version', 'identity_authority', 'provenance'), 'source acquisition lineage')
        core.require((row['sample'], row['member']) == (sample['id'], member['id'])
                     and row['role'] in ROLES and row['availability'] in ('supplied', 'missing'),
                     'exact ordered source role/availability required')
        core.text(row['acquisition_source']); core.text(row['version'])
        core.require(row['identity_authority'] == member['checksum']['authority'],
                     'role declaration is not bound to original member identity authority')
        capture.read(row['identity_authority'], base)
        core.require(row['role'] != 'observed' or sample['kind'] == 'data',
                     'MC cannot acquire observed identity')
        core.require(row['role'] not in ('supplied_mc', 'generated_simulation') or sample['kind'] != 'data',
                     'original data cannot acquire MC identity')
        core.require(type(row['provenance']) is list and row['provenance'],
                     'original documentary acquisition/generation/calibration provenance required')
        for p in row['provenance']:
            capture.read(p, base)
    return deepcopy(authority)


def prepare(task, authority_pin, base, destination):
    """Default stronger producer for newly prepared ordinary ROOT acquisitions.

    Returns the existing root-stream task/context. It does not approve or run a
    service. Missing acquisitions may be drafted from source metadata without
    pretending to possess ROOT files; ordinary execution still enforces inputs.
    """
    from ravel.physics import root_stream
    core.require(set(task) == {'config'}, 'prepare from the original plain ROOT task')
    cap = core.Capture(); path, config, ds, a = root_stream._load(task, base, cap)
    actual_base = root_stream.source_base(config, path.parent)
    value = {'schema_version': 1, 'kind': CONTRACT, 'source_authority': deepcopy(authority_pin),
             'config': deepcopy(task['config']), 'dataset': deepcopy(config['dataset']),
             'analysis': deepcopy(config['analysis']), 'original_goal': deepcopy(a['original_goal'])}
    # Validate all original documentary declarations before publication.
    out = Path(destination).absolute()
    core.require(not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)),
                 'fresh ordinary read preparation destination required')
    # A temporary value cannot masquerade as an input: source declaration is
    # committed with existing canonical write_new then independently rebound.
    authority = validate_authority(authority_pin, ds, a, actual_base, cap); cap.finish()
    out.mkdir(parents=False)
    # The new prepared task lives outside the original spec directory. Preserve
    # bytes while making its config path absolute, avoiding an invented base.
    config_pin={**deepcopy(task['config']),'path':str(path)}
    value['config']=config_pin
    contract_pin = root_stream.write_new(out / 'read-contract.json', value)
    enriched = {'config':config_pin, 'read_contract': contract_pin}
    second = core.Capture()
    bound_contract(contract_pin, enriched, config, ds, a, actual_base, second)
    task_pin = root_stream.write_new(out / 'task.json', enriched)
    context = root_stream.context(enriched, base)
    second.finish(); cap.finish()
    return {'task': task_pin, 'read_contract': contract_pin,
            'context': context,
            'acquisitions_available': all(row['availability'] == 'supplied' for row in authority['sources']),
            'read_requirements': {q['id']: {'contract':contract_pin,'quantity_id':q['id'],
                'roles':list(dict.fromkeys(row['role'] for row in authority['sources'])),
                'purpose':'original_quantity'} for q in a['quantities']},
            'acquisition_state':'available_not_read' if all(row['availability']=='supplied' for row in authority['sources']) else 'acquisition_missing',
            'original_requested_quantities':[{'id':q['id'],'state':'unresolved',
                'reason':'No ordinary read has run; original full scientific obligation remains'} for q in a['quantities']],
            'execution_authorized': False, 'scientific_acceptance': False}


def _intervals(coverage, dataset):
    """Keep every original member, including zero entries, with gap-free prefixes."""
    members = {(s['id'], m['id']): m for s in dataset['samples'] for m in s['members']}
    result = {key: [] for key in members}
    original_order=list(members);index=0
    core.require(type(coverage) is list, 'actual reader interval list required')
    for row in coverage:
        core.keys(row, ('sample', 'member', 'start', 'stop'), 'actual original read interval')
        key = row['sample'], row['member']
        core.require(index<len(original_order) and key==original_order[index],
                     'actual read interval differs from the original member order')
        start, stop = row['start'], row['stop']
        core.require(type(start) is int and type(stop) is int
                     and 0 <= start <= stop <= members[key]['entries']
                     and (start < stop or members[key]['entries'] == 0), 'invalid original read range')
        prefix = result[key][-1]['stop'] if result[key] else 0
        core.require(start == prefix, 'read interval gaps/duplicates cannot certify a prefix')
        result[key].append(deepcopy(row))
        if stop==members[key]['entries']:index+=1
    return result


def emit(contract_pin, contract, authority, config, dataset, analysis, *, coverage,
         reader_succeeded, source_custody_current, reader_binding, parents):
    """Reader-owned outcome; partial values are never completed or renormalized."""
    by_member = _intervals(coverage, dataset)
    population = []
    for declared, (sample, member) in zip(authority['sources'],
            [(s, m) for s in dataset['samples'] for m in s['members']]):
        rows = by_member[sample['id'], member['id']]
        processed = rows[-1]['stop'] if rows else 0
        if declared['availability'] == 'missing':
            core.require(not rows, 'missing original acquisition cannot inherit read intervals')
            outcome, reason = 'acquisition_missing', 'original source acquisition declared missing'
        elif not source_custody_current:
            outcome, reason = 'read_failed', 'ending source custody refused; attempted intervals are not qualified'
        elif reader_succeeded and rows and processed == member['entries']:
            outcome, reason = 'read_complete', None
        elif rows and processed > 0:
            outcome, reason = 'read_partial', 'reader did not deliver the full original member population'
        else:
            outcome, reason = 'read_failed', 'no authenticated completed original source interval'
        population.append({'sample': sample['id'], 'member': member['id'],
            'role': declared['role'], 'source': deepcopy(member), 'lineage': deepcopy(declared),
            'expected_entries': member['entries'], 'attempted_intervals': rows,
            'attempted_entries': processed, 'remaining_interval': [processed, member['entries']],
            'outcome': outcome, 'reason': reason})
    states = [p['outcome'] for p in population]
    overall = ('read_complete' if all(x == 'read_complete' for x in states) else
               'read_partial' if any(x in ('read_complete', 'read_partial') for x in states) else
               'acquisition_missing' if all(x == 'acquisition_missing' for x in states) else 'read_failed')
    quantities = [{'id': q['id'], 'outcome': overall,
        'state': 'resolved' if overall == 'read_complete' else 'partial' if overall == 'read_partial' else 'unresolved',
        'reason': None if overall == 'read_complete' else 'original read obligation not completely delivered',
        'contract': deepcopy(q['contract'])} for q in analysis['quantities']]
    return {'schema_version': 1, 'kind': 'typed-data-read-outcomes', 'contract': deepcopy(contract_pin),
        'source_authority': deepcopy(contract['source_authority']), 'reader': deepcopy(reader_binding),
        'parents': deepcopy(parents), 'population': population, 'outcome': overall,
        'requested_quantities': quantities,
        'representation': {'branch_contract': deepcopy(analysis['branch_contract']),
                           'quantities': deepcopy(analysis['quantities']), 'blinding': deepcopy(analysis['blinding'])},
        'normalization': [{'sample': s['id'], 'kind': s['kind'], 'normalization': deepcopy(s['normalization']),
                           'weight_contract': deepcopy(analysis['weight_contract'])} for s in dataset['samples']],
        'subset_renormalized': False, 'synthetic_substitution': False, 'physics_validated': False,
        'limits': ['Source-role provenance is a pinned documentary claim, not actor authentication or detector truth.',
                   'Attempted read intervals do not certify partial scientific values or a new normalization.',
                   'Read completion is separate from quantity checks, blinding, scientific acceptance and physics.']}


def reader_record(task, base, config, dataset, analysis, *, out, run_directory, plan,
                  native_delivery, native_request, native_receipt, input_hashes, errors):
    """Called by the existing approved root_stream.run, including failed output."""
    from ravel.physics import root_stream
    cap = core.Capture()
    # The isolated native request may spell source-relative runtime site roots
    # absolutely. Keep the immutable original config convention in this record;
    # the exact actual request is retained separately and bound below.
    path,config,dataset,analysis=root_stream._load(task,base,cap)
    base=root_stream.source_base(config,path.parent)
    contract, authority = bound_contract(task['read_contract'], task, config, dataset, analysis, base, cap)
    coverage = actual_coverage(native_delivery, out, config, cap)
    parents = [{'path': p, 'sha256': h} for p, h in sorted(input_hashes.items())]
    from ravel.workflow import science
    plan_path = Path(run_directory) / science.PLAN
    plan_pin = {'path':str(plan_path),'sha256':hashlib.sha256(plan_path.read_bytes()).hexdigest()}
    _capture_artifact(plan_pin, plan_path.parent, cap)
    binding = {'function': 'ravel.physics.root_stream.run', 'config': deepcopy(task['config']),
        'run_directory': str(Path(run_directory).absolute()), 'ordinary_plan': plan_pin,
        'ordinary_output_directory': plan['output_directory'],
        'native_request': deepcopy(native_request), 'native_receipt': deepcopy(native_receipt),
        'runtime': deepcopy(config['runtime']), 'kernel': deepcopy(config['bundle'])}
    value = emit(task['read_contract'], contract, authority, config, dataset, analysis,
        coverage=coverage, reader_succeeded=not errors, source_custody_current='ending_custody_refused' not in errors,
        reader_binding=binding, parents=parents)
    cap.finish()
    return value


def actual_coverage(native_delivery, out, config, capture):
    if native_delivery is not None: return deepcopy(native_delivery['delivery']['coverage'])
    ledger=Path(out)/'native/completed-intervals.jsonl'
    if not ledger.exists(): return []
    core.require(not ledger.is_symlink() and ledger.is_file(),'ordinary actual read ledger required')
    declaration={'path':str(ledger),'sha256':hashlib.sha256(ledger.read_bytes()).hexdigest(),
                 'size':ledger.stat().st_size}
    _,raw=capture.read(declaration,ledger.parent,config['limits']['max_output_bytes'])
    return [core.strict(line) for line in raw.splitlines() if line]


def public_summary(record):
    """No original DATA entry counts, intervals, member identities or SR values."""
    return {'kind':'data-read-summary','outcome':record['outcome'],
        'roles':list(dict.fromkeys(row['role'] for row in record['population'])),
        'requested_quantities':[{'id':q['id'],'state':q['state'],'reason':q['reason']}
            for q in record['requested_quantities']],
        'subset_renormalized':False,'synthetic_substitution':False,
        'scientific_acceptance':False,'physics_validated':False}


def requirement_pins(requirement, base):
    from ravel.physics import root_stream
    requirement=validate_requirement(requirement)
    cap=core.Capture();value=cap.document(requirement['contract'],base)
    task={'config':value['config'],'read_contract':requirement['contract']}
    path,config,ds,a=root_stream._load(task,base,cap)
    core.require(requirement['quantity_id'] in {q['id'] for q in a['quantities']},
                 'read requirement not in original quantity roster')
    _,authority=bound_contract(requirement['contract'],task,config,ds,a,
        root_stream.source_base(config,path.parent),cap)
    core.require(set(row['role'] for row in authority['sources']) <= set(requirement['roles']),
                 'original requested source roles differ from original acquisition')
    cap.finish();return list(cap.rows.values())


def ordinary_outcome(record, result, common):
    """Authenticate current admitted producer; failed delivery remains diagnostic.

    Existing failed attempts do not necessarily commit ordinary output snapshots.
    We keep that distinction, validating their actual retained token, input/runtime,
    launch and reader publication closure, without turning them into successes.
    """
    from ravel.workflow import science, execution
    from ravel.workflow.launch_authorization import audit_launches
    rd=science.root(record['reader']['run_directory'])
    task={'config':record['reader']['config'],'read_contract':record['contract']}
    with science._validation_scope(rd) as session:
        plan=science.verify_plan(rd,approved=True,_session=session)
        stage,binding,_=science._selected(rd,plan,_session=session)
        spec=science.execution_spec(rd,_proposal=plan,_session=session)
        core.require(spec['mode']=='root-stream' and spec['task']==task
            and Path(common).absolute()==(rd/stage['outputs'][0]).absolute(),
            'exact actual ordinary ROOT task/output required')
        core.require(record['reader']['ordinary_output_directory']==stage['outputs'][0],
                     'original selected output directory differs')
        cap=core.Capture();_capture_artifact(record['reader']['ordinary_plan'],rd,cap)
        core.require(record['reader']['ordinary_plan']['path']==str(rd/science.PLAN),
                     'original admitted plan path differs')
        state=session.read_document(rd/execution.STATE_NAME)
        actual=state['stages'].get('science',{})
        core.require(set(state['stages'])=={'science'} and actual.get('fingerprint')==binding['fingerprint']
            and actual.get('status') in ('succeeded','failed') and actual.get('finished_utc'),
            'actual terminal selected ordinary attempt required')
        committed={k:actual[k] for k in ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')}
        committed.update(execution.stage_metadata_fields(actual))
        core.require(execution.digest(committed)==actual['fingerprint'],
                     'terminal ordinary record specification differs')
        core.require(not audit_launches(rd,plan_sha256=execution.file_hash(rd/science.PLAN),require_science=True),
                     'original ordinary launch authorization differs')
        if result['status']=='passed':
            receipt=root_stream_delivery(rd, common, task)
            core.require(receipt['result']==result,'current successful result differs')
        else:
            core.require(actual['status']=='failed' and type(actual.get('exit_code')) is int
                and actual['exit_code']!=0 and actual.get('parents')=={},'actual failed source attempt required')
            core.require(actual.get('runtime')==session.runtime
                and session.snapshot(actual['inputs'])==actual['input_snapshot'],
                'failed diagnostic input/runtime custody differs')
            execution._validate_runtime_environment(actual)
            if 'operation_resources' in actual:
                from ravel.workflow.operation_resources import check_record
                check_record(rd,actual)
        cap.finish()
    return {'execution_status':actual['status'],'scientific_acceptance':False,
        'failed_output_snapshot_authenticated':False if actual['status']=='failed' else None}


def root_stream_delivery(rd, common, task):
    from ravel.physics import root_stream
    return root_stream.ordinary_delivery(rd,expected_output=common,expected_task=task)


def validate_requirement(value):
    core.keys(value, ('contract', 'quantity_id', 'roles', 'purpose'), 'original data read requirement')
    core.pin(value['contract']); core.text(value['quantity_id'])
    core.require(type(value['roles']) is list and value['roles'] and len(set(value['roles'])) == len(value['roles'])
                 and set(value['roles']) <= set(ROLES), 'explicit original source roles required')
    core.require(value['purpose'] in ('original_quantity', 'partial_diagnostic'), 'explicit read-completion purpose required')
    return deepcopy(value)


def consume(result_pin, requirement, base):
    """Reconstruct the reader-owned record before using exact original quantities.

    Failure/partial diagnostics remain available. Such a value cannot complete an
    original quantity. This verifies the existing ROOT guard, not scientific review.
    """
    from ravel.physics import root_stream
    requirement = validate_requirement(requirement)
    cap = core.Capture(); path, raw = _capture_artifact(result_pin, base, cap)
    result = core.strict(raw)
    core.require(result.get('kind') == 'root-stream-result' and type(result.get('read_outcomes')) is dict,
                 'actual typed ROOT reader result required; synthetic array is not a read outcome')
    record = cap.document(result['read_outcomes'],path.parent)
    core.require(record['contract'] == requirement['contract'], 'original read contract cannot be replaced')
    task = {'config': record['reader']['config'], 'read_contract': record['contract']}
    cfg_path, config, ds, a = root_stream._load(task, base, cap)
    source_base = root_stream.source_base(config, cfg_path.parent)
    contract, authority = bound_contract(record['contract'], task, config, ds, a, source_base, cap)
    core.require(record['representation'] == {'branch_contract': a['branch_contract'], 'quantities': a['quantities'],
                 'blinding': a['blinding']}, 'known original source representation/unit convention differs')
    destination = path.parent / 'root-stream' if (path.parent / 'root-stream').is_dir() else path.parent
    core.require(Path(result['read_outcomes']['path']).absolute()==destination/'native/read-outcomes.json',
                 'actual restricted reader output path differs')
    guard=root_stream.guard(result, destination)
    guard.finish(result, common=path.parent if path.parent != destination else None)
    receipt=ordinary_outcome(record,result,destination.parent)
    full=None if result['status']!='passed' else root_stream.private_delivery(guard)[0]
    coverage=actual_coverage(full,destination,config,cap)
    expected = emit(record['contract'], contract, authority, config, ds, a,
        coverage=coverage,
        reader_succeeded=result['status'] == 'passed',
        source_custody_current='ending_custody_refused' not in result['errors'],
        reader_binding=record['reader'], parents=record['parents'])
    core.require(record == expected, 'typed role/population/normalization/read state differs')
    closure=guard.closure()
    core.require(record['parents']==[{'path':p,'sha256':h} for p,h in sorted(closure['inputs'].items())]
        and record['reader']['native_request']==closure['request_pin']
        and record['reader']['native_receipt']==result['native_receipt']
        and record['reader']['function']=='ravel.physics.root_stream.run'
        and record['reader']['runtime']==config['runtime'] and record['reader']['kernel']==config['bundle'],
        'original parent/transform/runtime/reader binding differs')
    core.require(result['read_summary']==public_summary(record),'public read summary differs')
    core.require(set(p['role'] for p in record['population']) <= set(requirement['roles']),
                 'authenticated original source role conflicts with requested observation/calibration role')
    rows = [q for q in record['requested_quantities'] if q['id'] == requirement['quantity_id']]
    core.require(len(rows) == 1, 'original requested quantity absent')
    outcome = rows[0]['outcome']
    usable = outcome == 'read_complete' or (requirement['purpose'] == 'partial_diagnostic'
                                           and outcome in ('read_partial', 'read_failed', 'acquisition_missing'))
    cap.finish()
    return {'passed': usable, 'outcome': outcome, 'role_population': [p['role'] for p in record['population']],
            'reader_receipt':receipt, 'summary':public_summary(record),
            'reason': None if usable else rows[0]['reason'],
            'original_scientific_obligation_complete': outcome == 'read_complete',
            'scientific_acceptance': False}
