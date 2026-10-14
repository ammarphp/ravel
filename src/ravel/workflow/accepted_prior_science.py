"""Read a closed prior science result under its own immutable commitments.

This is evidence reuse, not a launch/redo approval or a compatibility claim for
the importing package. No prior package is imported. Current study admission
continues to use science.verify_plan and the ordinary fresh execution gates.
Only an initial, one-attempt, immutable schema2 science study is supported here.
Local journals declare role separation; they do not authenticate human identity.
"""
import hashlib
from pathlib import Path

from . import execution, launch_authorization, physics_review as review, science
from .launch_authorization import parse_utc


def accepted(root, *, claim_scope, mode, attempt_id):
    """Validate fresh located bytes of one prior accepted science attempt.

The historical input population and runtime capsule come from its approved
plan and accepted receipt. They are never regenerated with this package's
adapter inventory or replaced by today's process runtime. A fresh observation
still checks all original file bytes/path membership, policy, journal/head,
retained snapshots, ledger, receipt and output/log inventories before return.
    """
    literal = Path(root).expanduser().absolute()
    if any(p.is_symlink() for p in (literal, *literal.parents)):
        raise ValueError('prior run must not traverse a symlink')
    root = review._root(literal)
    session = execution._validation_session(root)
    try:
        session.require_inventory(root / review.DIRECTORY / 'events')
        session.require_inventory(root / review.DIRECTORY / 'snapshots')
        def read(value):
            path = review._path(root, str(value), _session=session)
            session.require_regular(path)
            return session.read_document(path)
        reg, events = review._read(root, _session=session)
        history = {'schema_version':1, 'registration':reg, 'events':events,
                   'checkpoint':read(review.HEAD), 'action':'reuse', 'stage':None}
        errors = review.validate_snapshot(history)
        if errors:
            raise ValueError('prior review does not authorize reuse: ' + '; '.join(errors))
        view = review._view(reg, events)
        if view['reviews'][0]['claim_scope'] != claim_scope:
            raise ValueError('prior accepted claim scope differs')
        cycle = view['cycle']
        if (cycle['correction_id'] is not None or cycle['checkpoint']
                or any(e['event'] in ('correction','correction_failed') for e in events)
                or len([e for e in events if e['event']=='cycle']) != 1):
            raise ValueError('prior reuse supports only one immutable initial science cycle')
        if read(review.POLICY) != reg['policy']:
            raise ValueError('prior registered policy changed')
        review._live_pins(root, reg['bindings'], allow_empty=review._empty_input_paths(reg), _session=session)
        review._live_pins(root, cycle['snapshots'], allow_empty=review._empty_artifact_paths(reg, cycle), _session=session)

        spec, plan = read(science.SPEC), read(science.PLAN)
        approval, checkin = read(science.APPROVAL), read('inputs/checkin1.json')
        science.validate(spec)
        science._keys(plan, {'schema_version','mode','base_dir','stages','stage_binding','max_seconds',
            'max_attempts','approval_mode','expert_review','execution_task','mutable_inputs','mutable_paths'}
            | ({'prepared_runtime'} if 'prepared_runtime' in plan else set()), 'prior science plan')
        if 'prepared_runtime' in plan:
            from .prepared_runtime import validate as validate_prepared_runtime
            validate_prepared_runtime(plan['prepared_runtime'], plan['stage_binding'], live_interpreter=False)
        science._v2_approval_keys(approval, 'prior science approval')
        if (spec['schema_version'] != 2 or plan['schema_version'] != 2
                or spec['mode'] != mode or plan['mode'] != mode or spec['max_attempts'] != 1
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
        if checkin != science.make_checkin(spec, registered[science.PLAN], stage, method_decision=(read(science.METHOD_DECISION) if science.METHOD_DECISION in approved_paths else None)):
            raise ValueError('prior check-in differs from the original declared study')
        ledger = read(execution.STATE_NAME)
        if (type(ledger.get('schema_version')) is not int or ledger['schema_version'] != 1
                or type(ledger.get('revision')) is not int or ledger['revision'] < 1
                or set(ledger.get('stages',{})) != {'science'}):
            raise ValueError('prior closed execution ledger changed')
        record = ledger['stages']['science']
        if 'runtime_environment' not in record:
            raise ValueError('prior reuse requires the original runtime environment capsule')
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
            raise ValueError('accepted review is not bound to this original attempt')
        if session.snapshot(record['inputs']) != record['input_snapshot']:
            raise ValueError('prior approved input bytes or population changed')
        if session.snapshot(record['outputs'], outputs=True, **execution.output_snapshot_fields(record)) != record['output_snapshot']:
            raise ValueError('prior output bytes or population changed')
        if 'log_snapshot' not in record or session.snapshot([str(execution.log_path(root,record['log']))]) != record['log_snapshot']:
            raise ValueError('prior original execution log changed')
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
        paths += list(record['input_snapshot']) + list(record['output_snapshot'])
        # Consumers bind files. Original directory membership is already checked
        # against the retained snapshots above and again at this session's end.
        bound_files = []
        for value in paths:
            path = execution.resolve_path(root,value)
            bound_files.extend(sorted(p for p in path.rglob('*') if p.is_file()) if path.is_dir() else [path])
        errors = session.finish()
        if errors:raise ValueError('prior evidence changed during validation: '+'; '.join(errors))
        return {'schema_version':1,'claim_scope':claim_scope,'cycle_id':cycle['cycle_id'],
                'attempt_id':attempt_id,'receipt':record,'review':history,
                'bound_framework_inputs_sha256':execution.digest(framework),
                'framework_root':str(package),'paths':list(dict.fromkeys(str(p) for p in bound_files)),
                'historical_runtime':record['runtime'],'current_runtime_requalified':False,
                'execution_authority_granted':False,'attestation':review.ATTESTATION}
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('malformed prior immutable science evidence') from exc
    finally:
        session.close()
