"""Read an initial retained result under its own immutable commitments.

This is evidence reuse, not a launch/redo approval or a compatibility claim for
the importing package. No prior package is imported. Current study admission
continues to use science.verify_plan and the ordinary fresh execution gates.
This explicit inspection route supports an initial, one-attempt immutable schema2 study. It cannot launch, reopen or correct work.
Local journals declare role separation; they do not authenticate human identity.
"""
import hashlib
from pathlib import Path

from . import execution, launch_authorization, physics_review as review, science
from .launch_authorization import parse_utc


def _inspect(root, *, pending_only, _session=None):
    """Validate fresh located bytes of one retained initial science attempt.

The historical input population and runtime capsule come from its approved
plan and successful retained execution receipt. They are never regenerated with this package's
adapter inventory or replaced by today's process runtime. A fresh observation
still checks all original file bytes/path membership, policy, journal/head,
retained snapshots, ledger, receipt and output/log inventories before return.
    """
    literal = Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (literal, *literal.parents)):
        raise ValueError('prior run must not traverse a symlink')
    root = review._root(literal)
    owned = _session is None
    session = execution._validation_session(root) if owned else _session
    execution._check_validation_session(root, session)
    try:
        session.require_inventory(root / review.DIRECTORY / 'events')
        session.require_inventory(root / review.DIRECTORY / 'snapshots')
        def read(value):
            path = review._path(root, str(value), _session=session)
            session.require_regular(path)
            return session.read_document(path)
        reg, events = review._read(root, _session=session)
        history = {'schema_version':1, 'registration':reg, 'events':events,
                   'checkpoint':read(review.HEAD), 'action':'review_only', 'stage':None}
        errors = review.validate_snapshot(history, require_admission=False)
        if errors:
            raise ValueError('retained review journal is invalid: ' + '; '.join(errors))
        view = review._view(reg, events)
        if pending_only and view['state'] not in {'awaiting_review', 'send_back'}:
            raise ValueError('retained result is not pending review')
        if view['state'] not in {'awaiting_review', 'send_back', 'stopped', 'accepted', 'scientific_hold'}:
            raise ValueError('retained result has an unsupported review state')
        cycle = view['cycle']
        if (cycle['correction_id'] is not None or cycle['checkpoint']
                or any(e['event'] in ('correction','correction_failed') for e in events)
                or len([e for e in events if e['event']=='cycle']) != 1):
            raise ValueError('retained review supports only one immutable initial science cycle')
        if read(review.POLICY) != reg['policy']:
            raise ValueError('prior registered policy changed')
        review._live_pins(root, reg['bindings'], allow_empty=review._empty_input_paths(reg), _session=session)
        review._live_pins(root, cycle['snapshots'], allow_empty=review._empty_artifact_paths(reg, cycle), _session=session)
        review._judgments_live(root, view, _session=session)
        for hold in view['holds']:
            review._live_pins(root, hold['snapshots'], _session=session)

        spec, plan = read(science.SPEC), read(science.PLAN)
        approval, checkin = read(science.APPROVAL), read('inputs/checkin1.json')
        science.validate(spec)
        science._keys(plan, {'schema_version','mode','base_dir','stages','stage_binding','max_seconds',
            'max_attempts','approval_mode','expert_review','execution_task','mutable_inputs','mutable_paths'} | ({'prepared_runtime'} if 'prepared_runtime' in plan else set()), 'prior science plan')
        from . import prepared_runtime
        if pending_only:
            prepared_runtime.validate_plan(plan)
        elif 'prepared_runtime' in plan:
            # Reader identity is separate. The historical interpreter's exact
            # located bytes are still checked with all original inputs below.
            prepared_runtime.validate(plan['prepared_runtime'], plan['stage_binding'], live_interpreter=False)
        science._v2_approval_keys(approval, 'prior science approval')
        if (spec['schema_version'] != 2 or plan['schema_version'] != 2
                or plan['mode'] != spec['mode'] or spec['max_attempts'] != 1
                or plan['max_attempts'] != 1 or plan['mutable_inputs'] or plan['mutable_paths']
                or spec['review_policy']['correction_contract'] != {'input_slots':[], 'task_fields':[]}
                or plan['execution_task'] != spec['task']
                or read(science.EXECUTION_TASK) != {'schema_version':1,'task':spec['task']}
                or spec['review_policy']['policy'] != reg['policy']
                or plan['max_seconds'] != spec['max_seconds']
                or plan['approval_mode'] != spec['approval_mode'] or plan['expert_review'] is not False
                or any((root/p).exists() for p in ('inputs/native_execution_plan.json','inputs/checkin1_approval.json','inputs/task_contract.json'))):
            raise ValueError('prior study is outside the immutable initial science envelope')
        registered = {p['path']:p['sha256'] for p in reg['bindings']}
        # A method decision, when present, is the last approved input.
        approved_paths = (science.PLAN, science.SPEC, 'inputs/checkin1.json', science.REVIEW_POLICY,
                          *((science.METHOD_DECISION,) if science.METHOD_DECISION in registered else ()))
        for value in (*approved_paths, science.APPROVAL):
            if registered.get(value) != session.hash_file(review._path(root, value, _session=session)):
                raise ValueError('prior approval document lacks its original registered pin')
        if (type(approval['schema_version']) is not int or approval['schema_version'] != 2
                or approval['generated_by'] != 'ravel.workflow.science.approve'
                or approval['expert_review'] is not False or not isinstance(approval['quote'],str)
                or not approval['quote'].strip() or approval['approval_mode'] != spec['approval_mode']
                or approval['plan_sha256'] != registered[science.PLAN]
                or approval['checkin_sha256'] != registered['inputs/checkin1.json']
                or approval['input_fingerprint'] != hashlib.sha256(''.join(registered[v] for v in approved_paths).encode()).hexdigest()):
            raise ValueError('prior recorded science approval changed')
        if len(plan['stages']) != 1:
            raise ValueError('prior study must contain exactly one science stage')
        stage, = plan['stages']; binding = plan['stage_binding']
        if checkin != science.make_checkin(spec, registered[science.PLAN], stage, base=plan['base_dir'], method_decision=(read(science.METHOD_DECISION) if science.METHOD_DECISION in approved_paths else None)):
            raise ValueError('prior check-in differs from the original declared study')
        ledger = read(execution.STATE_NAME)
        if (type(ledger.get('schema_version')) is not int or ledger['schema_version'] != 1
                or type(ledger.get('revision')) is not int or ledger['revision'] < 1
                or set(ledger.get('stages',{})) != {'science'}):
            raise ValueError('prior closed execution ledger changed')
        record = ledger['stages']['science']
        attempt_id = record.get('attempt_id')
        if 'runtime_environment' not in record:
            raise ValueError('retained review requires the original runtime environment capsule')
        execution._validate_runtime_environment(record)
        if ('prepared_runtime' in plan
                and plan['prepared_runtime']['environment'] != record['runtime_environment']):
            raise ValueError('prior prepared runtime differs from its original successful receipt environment')
        if ('helper_declaration' in record or 'operation_resources' in record
                or record.get('stage') != 'science' or record.get('status') != 'succeeded'
                or type(record.get('exit_code')) is not int or record['exit_code'] != 0
                or record.get('attempt_id') != attempt_id or read(record['attempt_record']) != record):
            raise ValueError('prior original successful attempt differs or uses an unsupported authority class')
        keys = ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')
        if (set(binding) != {*keys,'fingerprint',*execution.stage_metadata_fields(binding)}
                or any(record[k] != binding[k] for k in keys)
                or execution.stage_metadata_fields(record) != execution.stage_metadata_fields(binding)
                or binding['fingerprint'] != execution.digest({k:v for k,v in binding.items() if k!='fingerprint'})
                or record['fingerprint'] != binding['fingerprint']
                or record['receipt_sha256'] != execution.receipt_digest(record)
                or binding['parents'] or stage.get('depends_on') != []
                or stage.get('stage') != 'science' or stage['command'] != binding['command']
                or stage['cwd'] != str(root) or binding['cwd'] != str(root)
                or stage['outputs'] != ['outputs/attempt-1'] or record['outputs'] != stage['outputs']
                or record['log'] != stage['log']
                or not set(stage['inputs']) <= set(binding['inputs'])
                or execution.stage_metadata_fields(stage) != execution.stage_metadata_fields(binding)):
            raise ValueError('prior approved stage/receipt commitments differ')
        token = read('execution_attempt.json')
        if (token != read('logs/science-attempts/00000001.json') or type(token.get('attempt')) is not int or token['attempt'] != 1
                or token.get('plan_sha256') != registered[science.PLAN]
                or type(token.get('budget_seconds')) is not int
                or token.get('budget_seconds') != spec['max_seconds']
                or token.get('correction_id') is not None or token.get('correction_plan_sha256') is not None
                or not parse_utc(approval['utc']) <= parse_utc(token['started_utc']) <= parse_utc(record['started_utc']) <= parse_utc(record['finished_utc']) <= parse_utc(cycle['utc'])):
            raise ValueError('prior spent attempt identity, timing or budget changed')
        authorization_directory = root / 'logs/authorization'
        session.require_inventory(authorization_directory)
        authorizations = launch_authorization._events(root)
        authorization_paths = [authorization_directory/f'{e["sequence"]:08d}.json' for e in authorizations]
        for path, event in zip(authorization_paths, authorizations):
            if read(path) != event:
                raise ValueError('prior launch authorization changed during observation')
        authorization_errors = launch_authorization.audit_launches(root,
            plan_sha256=registered[science.PLAN], require_science=True)
        if authorization_errors:
            raise ValueError('prior original launch is not authorized: '+'; '.join(authorization_errors))
        if (len(authorizations) != 2 or authorizations[0]['event'] != 'authorized'
                or authorizations[1]['event'] != 'launched'
                or authorizations[0]['authorization']['stage_binding'] != binding
                or record.get('child_pid') is None
                or not parse_utc(record['started_utc']) <= parse_utc(authorizations[0]['utc']) <= parse_utc(authorizations[1]['utc']) <= parse_utc(record['finished_utc'])):
            raise ValueError('prior immutable attempt needs its sole exact original launch')
        authorization_pins = launch_authorization._authorization_pins(authorizations[0]['authorization'])
        for pin in authorization_pins:
            path = session.regular_file(pin['path'], root)
            if session.hash_file(path) != pin['sha256']:
                raise ValueError('prior located launch input differs from its original retained authorization')
        receipt, = cycle['receipts']
        if (receipt['stage'] != 'science' or receipt['attempt_id'] != attempt_id
                or receipt['receipt_sha256'] != record['receipt_sha256']
                or review._identity(root, review._path(root, record['attempt_record'])) != receipt['path']
                or receipt['inputs'] != [review._identity(root, review._path(root,p,allow_empty=True)) for p in record['inputs']]
                or receipt['outputs'] != [str(execution.resolve_path(root,p)) for p in record['outputs']]):
            raise ValueError('pending review is not bound to this original attempt')
        if session.snapshot(record['inputs']) != record['input_snapshot']:
            raise ValueError('prior approved input bytes or population changed')
        if session.snapshot(record['outputs'], outputs=True, **execution.output_snapshot_fields(record)) != record['output_snapshot']:
            raise ValueError('prior output bytes or population changed')
        if 'log_snapshot' not in record or session.snapshot([str(execution.log_path(root,record['log']))]) != record['log_snapshot']:
            raise ValueError('prior original execution log changed')
        if not pending_only:
            # Read the original delivered postconditions, without regenerating
            # a plan or running the historical package/adapter.
            out = root / 'outputs/attempt-1'
            result = read(out / 'result.json')
            verification = read(out / 'verification.json')
            read(out / 'recipe.json')
            from ravel.validation.validate_checkin import validate as check
            errors = check(read(out / 'checkin2.json'))
            if errors:
                raise ValueError('prior CHECK-IN 2 is invalid: ' + '; '.join(errors))
            if result.get('status') != 'passed' or result.get('physics_validated') is not False:
                raise ValueError('prior scientific adapter postconditions did not pass')
            if (verification.get('passed') is not True or verification.get('scope') != spec['mode']
                    or verification.get('physics_validated') is not False or verification.get('expert_review') is not False
                    or verification.get('result_sha256') != session.hash_file(out / 'result.json')):
                raise ValueError('prior verification does not bind passed scoped delivery')
        command = record['command']
        if (len(command) != 6 or command[2:] != ['ravel.physics.science_worker',str(root),'--attempt','1']
                or Path(command[1]).name != '_bootstrap.py' or not Path(command[1]).is_absolute()
                or str(Path(command[0]).resolve()) not in record['input_snapshot']):
            raise ValueError('prior command is not the exact source-bound ordinary science worker')
        bootstrap = session.regular_file(command[1],root); package = bootstrap.parent
        if package.name != 'ravel' or package.parent.name != 'src':
            raise ValueError('prior worker source root differs')
        session.require_inventory(package)
        sources = {str(p) for p in package.rglob('*.py')}
        declared_sources = {p for p in record['input_snapshot'] if Path(p).is_relative_to(package) and Path(p).suffix=='.py'}
        if sources != declared_sources or str(bootstrap) not in declared_sources:
            raise ValueError('prior framework source membership changed')
        framework = {p:record['input_snapshot'][p] for p in sorted(declared_sources)}
        paths = [review.POLICY, science.APPROVAL, review.REGISTRATION, review.HEAD, execution.STATE_NAME,
                 'execution_attempt.json','logs/science-attempts/00000001.json', record['attempt_record'],record['log']]
        paths += [f'{review.DIRECTORY}/events/{e["sequence"]:08d}.json' for e in events]
        paths += authorization_paths
        paths += [pin['path'] for pin in authorization_pins]
        paths += [p['snapshot'] for e in events for p in e.get('snapshots',[]) if p.get('snapshot')]
        paths += [p['path'] for p in reg['bindings']] + [p['path'] for p in cycle['snapshots']]
        paths += [p['path'] for hold in view['holds'] for p in hold['snapshots']]
        paths += [p['path'] for event in view['reviews'] for p in event.get('supporting_artifacts', [])]
        paths += list(record['input_snapshot']) + list(record['output_snapshot'])
        # Consumers bind files. Original directory membership is already checked
        # against the retained snapshots above and again at this session's end.
        bound_files = []
        for value in paths:
            path = execution.resolve_path(root,value)
            bound_files.extend(sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path])
        if owned:
            errors = session.finish()
            if errors:raise ValueError('prior evidence changed during validation: '+'; '.join(errors))
        return {'schema_version':1,'kind':'retained-pending-review-proof' if pending_only else 'retained-initial-study-proof','cycle_id':cycle['cycle_id'],
                'cycle_sha256':cycle['sha256'], 'source_plan_sha256':registered[science.PLAN],
                'attempt_id':attempt_id,'receipt':record,'review':history, 'review_state':view['state'], 'mode':spec['mode'],
                'bound_framework_inputs_sha256':execution.digest(framework),
                'framework_root':str(package),'paths':list(dict.fromkeys(str(p) for p in bound_files)),
                'historical_runtime':record['runtime'],'current_runtime_requalified':False,
                'execution_authority_granted':False, 'scientific_acceptance_granted':False,'attestation':review.ATTESTATION}
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('malformed prior immutable science evidence') from exc
    finally:
        if owned: session.close()


def pending(root, *, _session=None):
    """Review-role submission remains limited to awaiting_review/send_back."""
    return _inspect(root, pending_only=True, _session=_session)


def observe(root, *, action=None, stage=None, _session=None):
    """One fresh observation; only original-policy delivery/reuse is admissible.

    An accepted snapshot never authorizes computation, migration, correction,
    bulk work or a new claim. Every consumer needs its own prospectively admitted
    plan. This route does not requalify the historical runtime under this reader.
    """
    if action not in (None, 'delivery', 'reuse') or stage is not None:
        raise ValueError('retained study supports only original scoped delivery/reuse without a stage')
    literal = Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (literal, *literal.parents)):
        raise ValueError('prior run must not traverse a symlink')
    owned = _session is None
    session = execution._validation_session(literal) if owned else _session
    try:
        proof = _inspect(literal, pending_only=False, _session=session)
        if action is not None:
            history = {**proof['review'], 'action':action, 'stage':None}
            errors = review.validate_snapshot(history)
            if errors:
                raise ValueError('retained review does not authorize ' + action + ': ' + '; '.join(errors))
            proof['review'] = history
        reader = Path(__file__).absolute()
        session.require_regular(reader)
        reader_package = reader.parent.parent
        reader_sources = session.snapshot([str(reader_package)])
        proof['current_reader'] = {'module':__name__, 'path':str(reader), 'sha256':session.hash_file(reader),
            'framework_root':str(reader_package), 'source_snapshot_sha256':execution.digest(reader_sources),
            'runtime':session.runtime}
        if owned:
            errors = session.finish()
            if errors:
                raise ValueError('prior evidence changed during validation: ' + '; '.join(errors))
        return proof
    finally:
        if owned: session.close()


def review_status(root, *, _session=None):
    """Existing review-state projection after retained custody validation."""
    try:
        proof = observe(root, _session=_session)
        history = proof['review']
        view = review._view(history['registration'], history['events'])
        return {'schema_version':1, 'state':view['state'], 'cycle_id':proof['cycle_id'],
            'correction_id':None, 'claim_scope':view['reviews'][0]['claim_scope'] if view['state']=='accepted' else None,
            'held_claim_scope':view['holds'][-1]['claim_scope'] if view['holds'] else None,
            'scientific_hold_sha256':view['holds'][-1]['sha256'] if view['holds'] else None,
            'unresolved_findings':view['findings'], 'redos_used':0,
            'redos_remaining':view['redos_remaining'], 'events':len(history['events']),
            'live_errors':review.validate_snapshot({**history, 'action':'delivery'}),
            'next_correction_stage':None, 'completed_correction_stages':[], 'correction_stages':[],
            'retained_study':True, 'current_reader':proof['current_reader'],
            'current_runtime_requalified':False, 'execution_authority_granted':False,
            'attestation':review.ATTESTATION}
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        return {'schema_version':1, 'state':'invalid', 'errors':[str(exc)],
            'retained_study':True, 'execution_authority_granted':False, 'attestation':review.ATTESTATION}



def packet(root, *, write=False):
    """Serialize a retained status write with real review/hold writers."""
    if type(write) is not bool:raise ValueError('write must be explicit')
    rd=Path(root).expanduser().absolute()
    if not write:return _packet(rd)
    lock=rd/review.DIRECTORY/'write.lock'
    if (not rd.is_dir() or not lock.parent.is_dir()
            or any(p.is_symlink() for p in (lock,*lock.parents))
            or lock.exists() and not lock.is_file()):
        raise ValueError('retained status write requires the ordinary existing review lock')
    from .state_io import file_lock
    with file_lock(lock):
        session=execution._validation_session(rd)
        try:return _packet(rd,write=True,_session=session)
        finally:session.close()

def _packet(root, *, write=False, _session=None):
    """Explicit current-reader status; writing refreshes current_state.json only."""
    rd = Path(root).expanduser().absolute()
    result = {'schema_version':2, 'rundir':str(rd), 'task_mode':None,
        'execution':{'status':'invalid'}, 'lifecycle_verdict':'FAIL', 'errors':[], 'review_errors':[],
        'retained_study':True, 'physics_validated':False, 'current_runtime_requalified':False,
        'execution_authority_granted':False, 'scientific_acceptance_granted':False,
        'scope':'Exact retained initial-study review scope; not physical closure, new execution or authenticated human review',
        'next_required':'Inspect invalid or changed evidence without overwriting the retained study'}
    proof = None
    try:
        proof = observe(rd, _session=_session)
        history = proof['review']
        view = review._view(history['registration'], history['events'])
        errors = review.validate_snapshot({**history, 'action':'delivery'})
        state = view['state']
        result.update(task_mode=proof['mode'], errors=[], review_errors=errors,
            execution={'status':'completed' if state=='accepted' and not errors else state},
            lifecycle_verdict='PASS' if state=='accepted' and not errors else 'PENDING',
            review_state=state, claim_scope=view['reviews'][0]['claim_scope'] if state=='accepted' else None,
            held_claim_scope=view['holds'][-1]['claim_scope'] if view['holds'] else None,
            scientific_hold_sha256=view['holds'][-1]['sha256'] if view['holds'] else None,
            unresolved_findings=view['findings'], events=len(history['events']),
            cycle_id=proof['cycle_id'], cycle_sha256=proof['cycle_sha256'], review_checkpoint=history['checkpoint'],
            original_execution={'attempt_id':proof['attempt_id'], 'plan_sha256':proof['source_plan_sha256'],
                'receipt_sha256':proof['receipt']['receipt_sha256'],
                'input_snapshot_sha256':execution.digest(proof['receipt']['input_snapshot']),
                'output_snapshot_sha256':execution.digest(proof['receipt']['output_snapshot']),
                'framework_root':proof['framework_root'], 'framework_inputs_sha256':proof['bound_framework_inputs_sha256'],
                'runtime':proof['historical_runtime']}, current_reader=proof['current_reader'],
            accepted_actions=history['registration']['policy']['claim_scopes'][view['reviews'][0]['claim_scope']]['actions'] if state=='accepted' else [],
            retained_route_actions=[a for a in ('delivery', 'reuse') if state=='accepted'
                and a in history['registration']['policy']['claim_scopes'][view['reviews'][0]['claim_scope']]['actions']],
            next_required='Only the original accepted scope may be delivered/reused after a fresh retained gate; new computation or consumers need separate plans'
                if state=='accepted' else 'Retain the recorded review state and findings; no execution, correction or hold-lift authority is granted')
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        result['errors'] = [str(exc)]
    if write:
        # Do not traverse an alias even when the observational packet is invalid.
        target = rd / 'current_state.json'
        if not rd.is_dir() or any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('retained status write requires an ordinary existing run directory and target')
        if proof is None or result['errors'] or str(target) in proof['paths']:
            raise ValueError('retained status cannot overwrite evidence or write without valid original commitments')
        import json
        committed = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode('utf-8')
        from .state_io import atomic_json
        # Keep the validated original journal/evidence epoch through target
        # protection. A real cooperative review writer cannot enter this lock.
        if _session is None:raise ValueError('retained write requires its locked validation session')
        errors=_session.finish()
        if errors:raise ValueError('retained evidence changed before status write: '+'; '.join(errors))
        atomic_json(target, result)
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ValueError('retained status target changed to an alias')
        with target.open('rb') as stream:
            if stream.read(len(committed) + 1) != committed:
                raise ValueError('written retained status differs from its intended observational packet')
    return result

def initial(root, *, _session):
    """Validate one successful original attempt before its FIRST real cycle.

    No current adapter inventory, old package import, synthesized review or
    runtime rebinding. The existing pending/status APIs keep their own guards.
    This proof is internal to the locked retained initial-opening operation.
    """
    literal = Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (literal,*literal.parents)):
        raise ValueError('prior run must not traverse a symlink')
    root=review._root(literal);session=_session
    execution._check_validation_session(root,session)
    def read(value):
        path=review._path(root,str(value),_session=session)
        return session.read_document(path)
    try:
        policy=read(review.POLICY)
        if review.validate_policy(policy):raise ValueError('invalid original review policy')
        spec, plan = read(science.SPEC), read(science.PLAN)
        approval, checkin = read(science.APPROVAL), read('inputs/checkin1.json')
        science.validate(spec)
        science._keys(plan, {'schema_version','mode','base_dir','stages','stage_binding','max_seconds',
            'max_attempts','approval_mode','expert_review','execution_task','mutable_inputs','mutable_paths'} | ({'prepared_runtime'} if 'prepared_runtime' in plan else set()), 'prior science plan')
        from . import prepared_runtime
        if 'prepared_runtime' in plan:
            # Reader identity is separate. The historical interpreter's exact
            # located bytes are still checked with all original inputs below.
            prepared_runtime.validate(plan['prepared_runtime'], plan['stage_binding'], live_interpreter=False)
        science._v2_approval_keys(approval, 'prior science approval')
        if (spec['schema_version'] != 2 or plan['schema_version'] != 2
                or plan['mode'] != spec['mode'] or spec['max_attempts'] != 1
                or plan['max_attempts'] != 1 or plan['mutable_inputs'] or plan['mutable_paths']
                or spec['review_policy']['correction_contract'] != {'input_slots':[], 'task_fields':[]}
                or plan['execution_task'] != spec['task']
                or read(science.EXECUTION_TASK) != {'schema_version':1,'task':spec['task']}
                or spec['review_policy']['policy'] != policy
                or plan['max_seconds'] != spec['max_seconds']
                or plan['approval_mode'] != spec['approval_mode'] or plan['expert_review'] is not False
                or any((root/p).exists() for p in ('inputs/native_execution_plan.json','inputs/checkin1_approval.json','inputs/task_contract.json'))):
            raise ValueError('prior study is outside the immutable initial science envelope')
        approved_paths = (science.PLAN, science.SPEC, 'inputs/checkin1.json', science.REVIEW_POLICY,
                          *((science.METHOD_DECISION,) if (root / science.METHOD_DECISION).exists() else ()))
        registered = {v:session.hash_file(review._path(root,v,_session=session)) for v in (*approved_paths,science.APPROVAL)}
        for value in (*approved_paths, science.APPROVAL):
            if registered.get(value) != session.hash_file(review._path(root, value, _session=session)):
                raise ValueError('prior approval document lacks its original registered pin')
        if (type(approval['schema_version']) is not int or approval['schema_version'] != 2
                or approval['generated_by'] != 'ravel.workflow.science.approve'
                or approval['expert_review'] is not False or not isinstance(approval['quote'],str)
                or not approval['quote'].strip() or approval['approval_mode'] != spec['approval_mode']
                or approval['plan_sha256'] != registered[science.PLAN]
                or approval['checkin_sha256'] != registered['inputs/checkin1.json']
                or approval['input_fingerprint'] != hashlib.sha256(''.join(registered[v] for v in approved_paths).encode()).hexdigest()):
            raise ValueError('prior recorded science approval changed')
        if len(plan['stages']) != 1:
            raise ValueError('prior study must contain exactly one science stage')
        stage, = plan['stages']; binding = plan['stage_binding']
        if checkin != science.make_checkin(spec, registered[science.PLAN], stage, base=plan['base_dir'], method_decision=(read(science.METHOD_DECISION) if science.METHOD_DECISION in approved_paths else None)):
            raise ValueError('prior check-in differs from the original declared study')
        ledger = read(execution.STATE_NAME)
        if (type(ledger.get('schema_version')) is not int or ledger['schema_version'] != 1
                or type(ledger.get('revision')) is not int or ledger['revision'] < 1
                or set(ledger.get('stages',{})) != {'science'}):
            raise ValueError('prior closed execution ledger changed')
        record = ledger['stages']['science']
        attempt_id = record.get('attempt_id')
        if 'runtime_environment' not in record:
            raise ValueError('retained review requires the original runtime environment capsule')
        execution._validate_runtime_environment(record)
        if ('prepared_runtime' in plan
                and plan['prepared_runtime']['environment'] != record['runtime_environment']):
            raise ValueError('prior prepared runtime differs from its original successful receipt environment')
        if ('helper_declaration' in record or 'operation_resources' in record
                or record.get('stage') != 'science' or record.get('status') != 'succeeded'
                or type(record.get('exit_code')) is not int or record['exit_code'] != 0
                or record.get('attempt_id') != attempt_id or read(record['attempt_record']) != record):
            raise ValueError('prior original successful attempt differs or uses an unsupported authority class')
        keys = ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')
        if (set(binding) != {*keys,'fingerprint',*execution.stage_metadata_fields(binding)}
                or any(record[k] != binding[k] for k in keys)
                or execution.stage_metadata_fields(record) != execution.stage_metadata_fields(binding)
                or binding['fingerprint'] != execution.digest({k:v for k,v in binding.items() if k!='fingerprint'})
                or record['fingerprint'] != binding['fingerprint']
                or record['receipt_sha256'] != execution.receipt_digest(record)
                or binding['parents'] or stage.get('depends_on') != []
                or stage.get('stage') != 'science' or stage['command'] != binding['command']
                or stage['cwd'] != str(root) or binding['cwd'] != str(root)
                or stage['outputs'] != ['outputs/attempt-1'] or record['outputs'] != stage['outputs']
                or record['log'] != stage['log']
                or not set(stage['inputs']) <= set(binding['inputs'])
                or execution.stage_metadata_fields(stage) != execution.stage_metadata_fields(binding)):
            raise ValueError('prior approved stage/receipt commitments differ')
        token = read('execution_attempt.json')
        if (token != read('logs/science-attempts/00000001.json') or type(token.get('attempt')) is not int or token['attempt'] != 1
                or token.get('plan_sha256') != registered[science.PLAN]
                or type(token.get('budget_seconds')) is not int
                or token.get('budget_seconds') != spec['max_seconds']
                or token.get('correction_id') is not None or token.get('correction_plan_sha256') is not None
                or not parse_utc(approval['utc']) <= parse_utc(token['started_utc']) <= parse_utc(record['started_utc']) <= parse_utc(record['finished_utc'])):
            raise ValueError('prior spent attempt identity, timing or budget changed')
        authorization_directory = root / 'logs/authorization'
        session.require_inventory(authorization_directory)
        authorizations = launch_authorization._events(root)
        authorization_paths = [authorization_directory/f'{e["sequence"]:08d}.json' for e in authorizations]
        for path, event in zip(authorization_paths, authorizations):
            if read(path) != event:
                raise ValueError('prior launch authorization changed during observation')
        authorization_errors = launch_authorization.audit_launches(root,
            plan_sha256=registered[science.PLAN], require_science=True)
        if authorization_errors:
            raise ValueError('prior original launch is not authorized: '+'; '.join(authorization_errors))
        if (len(authorizations) != 2 or authorizations[0]['event'] != 'authorized'
                or authorizations[1]['event'] != 'launched'
                or authorizations[0]['authorization']['stage_binding'] != binding
                or record.get('child_pid') is None
                or not parse_utc(record['started_utc']) <= parse_utc(authorizations[0]['utc']) <= parse_utc(authorizations[1]['utc']) <= parse_utc(record['finished_utc'])):
            raise ValueError('prior immutable attempt needs its sole exact original launch')
        authorization_pins = launch_authorization._authorization_pins(authorizations[0]['authorization'])
        for pin in authorization_pins:
            path = session.regular_file(pin['path'], root)
            if session.hash_file(path) != pin['sha256']:
                raise ValueError('prior located launch input differs from its original retained authorization')
        if session.snapshot(record['inputs']) != record['input_snapshot']:
            raise ValueError('prior approved input bytes or population changed')
        if session.snapshot(record['outputs'], outputs=True, **execution.output_snapshot_fields(record)) != record['output_snapshot']:
            raise ValueError('prior output bytes or population changed')
        if 'log_snapshot' not in record or session.snapshot([str(execution.log_path(root,record['log']))]) != record['log_snapshot']:
            raise ValueError('prior original execution log changed')
        # Read the original delivered postconditions, without regenerating
        # a plan or running the historical package/adapter.
        out = root / 'outputs/attempt-1'
        result = read(out / 'result.json')
        verification = read(out / 'verification.json')
        read(out / 'recipe.json')
        from ravel.validation.validate_checkin import validate as check
        errors = check(read(out / 'checkin2.json'))
        if errors:
            raise ValueError('prior CHECK-IN 2 is invalid: ' + '; '.join(errors))
        if result.get('status') != 'passed' or result.get('physics_validated') is not False:
            raise ValueError('prior scientific adapter postconditions did not pass')
        if (verification.get('passed') is not True or verification.get('scope') != spec['mode']
                or verification.get('physics_validated') is not False or verification.get('expert_review') is not False
                or verification.get('result_sha256') != session.hash_file(out / 'result.json')):
            raise ValueError('prior verification does not bind passed scoped delivery')
        command = record['command']
        if (len(command) != 6 or command[2:] != ['ravel.physics.science_worker',str(root),'--attempt','1']
                or Path(command[1]).name != '_bootstrap.py' or not Path(command[1]).is_absolute()
                or str(Path(command[0]).resolve()) not in record['input_snapshot']):
            raise ValueError('prior command is not the exact source-bound ordinary science worker')
        bootstrap = session.regular_file(command[1],root); package = bootstrap.parent
        if package.name != 'ravel' or package.parent.name != 'src':
            raise ValueError('prior worker source root differs')
        session.require_inventory(package)
        sources = {str(p) for p in package.rglob('*.py')}
        declared_sources = {p for p in record['input_snapshot'] if Path(p).is_relative_to(package) and Path(p).suffix=='.py'}
        if sources != declared_sources or str(bootstrap) not in declared_sources:
            raise ValueError('prior framework source membership changed')
        framework = {p:record['input_snapshot'][p] for p in sorted(declared_sources)}
        bindings=[review._pin(root,v,_session=session) for v in (*approved_paths,science.APPROVAL)]
        receipt={'stage':'science','attempt_id':attempt_id,'receipt_sha256':record['receipt_sha256'],
                 'path':review._identity(root,review._path(root,record['attempt_record'],_session=session)),
                 'inputs':[review._identity(root,review._path(root,v,allow_empty=True,_session=session)) for v in record['inputs']],
                 'outputs':[str(execution.resolve_path(root,v)) for v in record['outputs']]}
        if 'output_policy' in record:
            proof={'schema_version':1};total=0
            proof_files={'specification':science.SPEC,'plan':science.PLAN,'checkin':'inputs/checkin1.json',
                         'approval':science.APPROVAL,'receipt':record['attempt_record']}
            if science.METHOD_DECISION in approved_paths:
                proof_files['method_decision']=science.METHOD_DECISION
            for key,value in proof_files.items():
                path=review._path(root,value,_session=session)
                raw=review._read_raw_proof_document(root,value);total+=len(raw)
                if hashlib.sha256(raw).hexdigest()!=session.hash_file(path):raise ValueError('original raw proof changed during read')
                if len(raw)>review.MAX_INCIDENTAL_DOCUMENT_BYTES or total>review.MAX_INCIDENTAL_PROOF_BYTES:
                    raise ValueError('original raw proof document exceeds bounded retention')
                proof[key]={'path':review._identity(root,path),'sha256':hashlib.sha256(raw).hexdigest(),'text':raw.decode('utf8')}
            receipt['incidental_output_proof']=proof
        empty=review._approved_zero_paths(root,record)
        output_files=[str(root/'outputs/attempt-1'/row['name'])
                      for row in record['output_snapshot'][str(root/'outputs/attempt-1')]['files']]
        return {'root':str(root),'policy':policy,'bindings':bindings,'receipt':receipt,'record':record,
                'output_files':output_files,'empty_paths':empty,'execution_authority_granted':False,
                'scientific_acceptance_granted':False,'current_runtime_requalified':False}
    except (KeyError,TypeError,IndexError) as exc:
        raise ValueError('malformed original immutable initial attempt') from exc


def capture_initial(root, *, check_results, stage_receipts, effective_settings, session):
    """Freeze the first real cycle after the complete original attempt proof."""
    from .state_io import atomic_json
    proof=initial(root,_session=session);record=proof['record']
    if stage_receipts is not None and stage_receipts!=[record['attempt_record']]:
        raise ValueError('retained opening must use the sole original successful attempt')
    settings=effective_settings or [science.EXECUTION_TASK]
    if settings!=[science.EXECUTION_TASK]:raise ValueError('retained opening uses only original immutable execution task')
    setting_pins=[review._pin(root,value,_session=session) for value in settings]
    receipts=[proof['receipt']]
    checks,checked=review._checks(root,check_results,proof['policy'],receipts,_session=session)
    # Empty markers/source copies are custody, never effective/check evidence.
    empty=set(proof['empty_paths'])
    for value in record['inputs']:
        path=review._path(root,value,allow_empty=True,_session=session)
        empty.update((str(path),review._identity(root,path)))
    # A frozen method decision in the incidental-output proof needs its own retained snapshot.
    decision=(science.METHOD_DECISION,) if 'method_decision' in receipts[0].get('incidental_output_proof',{}) else ()
    values=[review.POLICY,science.APPROVAL,science.PLAN,science.SPEC,'inputs/checkin1.json',*decision,
            *proof['output_files'],*settings,record['attempt_record'],check_results,*checked,*record['inputs']]
    values=list(dict.fromkeys(review._pin(root,str(v),allow_empty=str(v) in empty,_session=session)['path'] for v in values))
    raw_documents={d['path'] for k,d in receipts[0].get('incidental_output_proof',{}).items() if k!='schema_version'}
    snapshots=review._snapshots(root,values,'retained-initial',allow_empty=empty,raw_proof_documents=raw_documents,_session=session)
    regpath=root/review.REGISTRATION
    if review.registered(root):
        reg,events=review._read(root,_session=session)
        if events or reg['policy']!=proof['policy'] or reg['bindings']!=proof['bindings']:
            raise ValueError('retained opening cannot reset or replace an existing review')
    else:
        if (root/review.HEAD).exists() or list((root/review.DIRECTORY/'events').glob('*.json')):
            raise ValueError('retained initial registration cannot replace prior history')
        reg={'schema_version':1,'run_id':review.uuid.uuid4().hex,'policy':proof['policy'],
             'bindings':proof['bindings'],'attestation':review.ATTESTATION}
        reg['sha256']=execution.digest(reg);review._exclusive(regpath,reg)
        atomic_json(root/review.HEAD,{'sequence':0,'sha256':reg['sha256']})
        reg,events=review._read(root,_session=session)
    payload={'event':'cycle','cycle_id':review.uuid.uuid4().hex,'correction_id':None,'checkpoint':False,
             'effective_settings':setting_pins,'receipts':receipts,'checks':checks,'inherited_findings':[],'snapshots':snapshots}
    # Same existing detached family/source proof semantics, before append.
    review._incidental_output_paths(reg,payload)
    return reg,events,payload
