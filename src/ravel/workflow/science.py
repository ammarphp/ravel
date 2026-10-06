"""Approved, bounded execution for supplied-event and scientific-adapter studies.

The existing stage supervisor owns process cleanup and byte custody. A completed
study is a delivered computation within its declared scope, never paper closure.
"""
from pathlib import Path
import os

from ravel.paths import module_command
from ravel.workflow import execution
from ravel.workflow.state_io import atomic_json, file_lock, read_json

MODES = ('analyze', 'quantities', 'measurement', 'domain')
SPEC = 'inputs/science.json'
PLAN = 'inputs/science-plan.json'
APPROVAL = 'inputs/science-approval.json'


def regular(value, base):
    p = Path(value).expanduser()
    p = p if p.is_absolute() else Path(base) / p
    if any(part.is_symlink() for part in (p, *p.parents)) or not p.is_file():
        raise ValueError(f'expected a regular input without symlinks: {p}')
    return p.resolve()


def validate(spec):
    required = {'schema_version', 'mode', 'source', 'assumptions', 'max_seconds', 'approval_mode', 'task'}
    if not isinstance(spec, dict) or set(spec) != required or spec['schema_version'] != 1:
        raise ValueError('science specification requires exactly ' + ', '.join(sorted(required)))
    if spec['mode'] not in MODES or spec['approval_mode'] not in ('physicist', 'scripted_yes'):
        raise ValueError('invalid science mode or approval mode')
    if not isinstance(spec['source'], str) or not spec['source'].strip():
        raise ValueError('a scientific source or explicitly synthetic-control description is required')
    if not isinstance(spec['assumptions'], list) or not spec['assumptions'] or any(
            not isinstance(x, str) or not x.strip() for x in spec['assumptions']):
        raise ValueError('at least one explicit assumption is required')
    if type(spec['max_seconds']) is not int or not 1 <= spec['max_seconds'] <= 86400:
        raise ValueError('max_seconds must be an integer from 1 to 86400')
    if not isinstance(spec['task'], dict):
        raise ValueError('task must be an object')
    task = spec['task']
    if spec['mode'] == 'analyze':
        from ravel.physics.existing_events import validate as check
        check(task)
    elif spec['mode'] == 'quantities':
        if set(task) != {'contract', 'records'}:
            raise ValueError('quantities requires contract and records paths')
    else:
        from importlib import import_module
        module = import_module('ravel.physics.' + ('measurement' if spec['mode'] == 'measurement' else 'domain_adapters'))
        module.validate(task)


def task_inputs(spec, base):
    mode, task = spec['mode'], spec['task']
    if mode == 'quantities':
        from ravel.physics.quantities import validate as check
        files = [regular(task[k], base) for k in ('contract', 'records')]
        check(read_json(files[0]))
        return files
    from importlib import import_module
    module = import_module('ravel.physics.' + {'analyze': 'existing_events', 'measurement': 'measurement', 'domain': 'domain_adapters'}[mode])
    return [Path(p).resolve() for p in module.inputs(task, base)]


def root(value):
    rd = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)) or not rd.is_dir():
        raise ValueError('run directory must exist and not traverse a symlink')
    for p in ('inputs', 'outputs', 'work', 'logs', 'execution_state.json', 'execution_attempt.json'):
        if (rd / p).is_symlink():
            raise ValueError('run state and artifact roots must not be symlinks')
    return rd.resolve()


def make_checkin(spec, plan_sha256):
    return {'schema_version': 1, 'kind': 'checkin1', 'sections': {
            'i': {'source': spec['source'], 'scope': spec['mode']},
            'i-b': {'task': spec['task'], 'plan_sha256': plan_sha256},
            'ii': {'deliverable': 'Audited machine quantities and adapter evidence; figures only for declared plottable quantities.',
                   'reference': 'Only supplied, bound references are comparison evidence.'},
            'iii': {'waypoint': 'One bounded supplied-data calculation, followed by CHECK-IN 2; no automatic larger run.'},
            'iv': {'max_seconds': spec['max_seconds'], 'workers': 1, 'attempts': 1, 'new_generated_events': 0},
            'v': [{'id': f'F{i+1}', 'assumption': a} for i, a in enumerate(spec['assumptions'])],
            'vi': [{'mode': m, 'text': t} for m, t in [('answer', 'Approve the exact recipe and assumptions'),
                   ('ask', 'Clarify the scientific inputs'), ('propose', 'Revise the proposal in a new study')]]}}


def stage_outputs(spec):
    return ['outputs', 'work'] if spec['mode'] == 'analyze' and spec['task']['backend'] == 'rivet' else ['outputs']


def plan(rundir, specification):
    source = regular(specification, Path.cwd())
    spec = read_json(source)
    validate(spec)
    inputs = sorted(set(str(p) for p in task_inputs(spec, source.parent)))
    rd = Path(rundir).expanduser().absolute()
    if any(p.is_symlink() for p in (rd, *rd.parents)):
        raise ValueError('run directory must not traverse symlinks')
    # A typed specification is the explicit intake for these supplied-data studies.
    # An older routed request is never silently reinterpreted.
    rd.mkdir(parents=True, exist_ok=False)
    rd = root(rd)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        atomic_json(rd / SPEC, spec)
        stage = {'stage': 'science', 'command': module_command('ravel.physics.science_worker', rd),
                 'cwd': str(rd), 'inputs': [SPEC, *inputs], 'outputs': stage_outputs(spec), 'depends_on': []}
        binding = execution.plan_stage(rd, stage['stage'], stage['command'], stage['inputs'], stage['outputs'], [], rd)
        proposal = {'schema_version': 1, 'mode': spec['mode'], 'base_dir': str(source.parent),
                    'stages': [stage], 'stage_binding': binding, 'max_seconds': spec['max_seconds'],
                    'max_attempts': 1, 'approval_mode': spec['approval_mode'], 'expert_review': False}
        atomic_json(rd / PLAN, proposal)
        checkin = make_checkin(spec, execution.file_hash(rd / PLAN))
        from ravel.validation.validate_checkin import validate as check
        errors = check(checkin)
        if errors:
            raise ValueError('; '.join(errors))
        atomic_json(rd / 'inputs/checkin1.json', checkin)
        (rd / 'CHECKIN1.md').write_text('# Supplied-data scientific study\n\n' + spec['source'] +
            '\n\nReview `inputs/checkin1.json` and `inputs/science.json`. One worker, one attempt, '
            f'{spec["max_seconds"]} seconds. Approval: {spec["approval_mode"]}. '
            'Scripted assent is not expert review. No event generation or paper-reproduction certification.\n')
        (rd / 'DEVIATIONS.md').write_text('# Deviations\n\nNone. A changed specification requires a new plan.\n')
    packet(rd, write=True)
    return proposal


def verify_plan(rundir, approved=False):
    rd = root(rundir)
    proposal, spec = read_json(rd / PLAN), read_json(rd / SPEC)
    validate(spec)
    inputs = [SPEC, *sorted(set(str(p) for p in task_inputs(spec, proposal['base_dir'])))]
    stage = {'stage': 'science', 'command': module_command('ravel.physics.science_worker', rd),
             'cwd': str(rd), 'inputs': inputs, 'outputs': stage_outputs(spec), 'depends_on': []}
    if proposal['stages'] != [stage] or proposal['mode'] != spec['mode']:
        raise ValueError('study plan or scientific input inventory changed')
    if proposal['max_seconds'] != spec['max_seconds'] or proposal['max_attempts'] != 1 or proposal['approval_mode'] != spec['approval_mode']:
        raise ValueError('study budget or approval mode changed')
    binding = execution.plan_stage(rd, stage['stage'], stage['command'], inputs, stage['outputs'], [], rd)
    if binding != proposal['stage_binding']:
        raise ValueError('stale study: runtime, source or scientific input bytes changed')
    if read_json(rd / 'inputs/checkin1.json') != make_checkin(spec, execution.file_hash(rd / PLAN)):
        raise ValueError('check-in does not describe the current scientific proposal')
    if approved:
        receipt = read_json(rd / APPROVAL)
        if (receipt.get('plan_sha256') != execution.file_hash(rd / PLAN)
                or receipt.get('checkin_sha256') != execution.file_hash(rd / 'inputs/checkin1.json')
                or receipt.get('approval_mode') != spec['approval_mode'] or not receipt.get('quote', '').strip()
                or receipt.get('expert_review') is not False):
            raise ValueError('missing or stale study approval')
    return proposal


def approve(rundir, quote, *, scripted=False):
    rd = root(rundir)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd)
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError('actual assent text required')
        if scripted != (p['approval_mode'] == 'scripted_yes'):
            raise ValueError('approval mode must match the proposal; scripted assent is not expert review')
        if (rd / APPROVAL).exists():
            raise ValueError('approval already recorded; preserve the original receipt')
        from ravel.validation.validate_checkin import validate as check
        errors = check(read_json(rd / 'inputs/checkin1.json'))
        if errors:
            raise ValueError('; '.join(errors))
        atomic_json(rd / APPROVAL, {'schema_version': 1, 'quote': quote, 'approval_mode': p['approval_mode'],
            'expert_review': False, 'plan_sha256': execution.file_hash(rd / PLAN),
            'checkin_sha256': execution.file_hash(rd / 'inputs/checkin1.json'), 'utc': execution.utc_now()})
    packet(rd, write=True)
    return 0


def verify_worker(rundir):
    rd = root(rundir)
    p = verify_plan(rd, approved=True)
    attempt = read_json(rd / 'execution_attempt.json')
    record = execution.load_execution(rd)['stages'].get('science', {})
    if (attempt.get('attempt') != 1 or attempt.get('plan_sha256') != execution.file_hash(rd / PLAN)
            or record.get('status') != 'running' or record.get('supervisor_pid') != os.getppid()
            or record.get('child_pid') not in (None, os.getpid())
            or record.get('fingerprint') != p['stage_binding']['fingerprint']):
        raise ValueError('scientific worker requires its current approved supervised attempt')
    return p


def packet(rundir, *, write=False):
    rd = root(rundir)
    errors, status, mode = [], 'planned', None
    try:
        p = verify_plan(rd)
        mode = p['mode']
        if (rd / APPROVAL).exists():
            verify_plan(rd, approved=True)
            status = 'approved'
        if (rd / 'execution_attempt.json').exists():
            verify_plan(rd, approved=True)
            attempt = read_json(rd / 'execution_attempt.json')
            if (attempt.get('attempt') != 1 or attempt.get('plan_sha256') != execution.file_hash(rd / PLAN)
                    or attempt.get('budget_seconds') != p['max_seconds']):
                raise ValueError('execution-attempt identity or budget differs from the approved plan')
            running = execution.load_execution(rd)['stages'].get('science', {})
            if running.get('status') == 'running':
                status = 'running'
                raise RunningStudy()
            errors += execution.validate_completed_execution(rd, p['stages'])
            status = 'failed' if errors else 'completed'
            if not errors:
                result = read_json(rd / 'outputs/result.json')
                if result.get('status') != 'passed' or result.get('physics_validated') is not False:
                    errors.append('scientific adapter postconditions did not pass')
                if read_json(rd / 'outputs/verification.json').get('passed') is not True:
                    errors.append('scientific verification did not pass')
                from ravel.validation.validate_checkin import validate as check
                errors += check(read_json(rd / 'outputs/checkin2.json'))
    except RunningStudy:
        pass
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
        status = 'invalid'
    if errors and status == 'completed':
        status = 'failed'
    result = {'schema_version': 1, 'rundir': str(rd), 'task_mode': mode, 'execution': {'status': status},
              'lifecycle_verdict': 'PASS' if status == 'completed' else 'FAIL' if errors else 'PENDING',
              'errors': errors, 'next_required': {'planned': 'Review and approve CHECK-IN 1',
                  'approved': 'Run one supervised attempt', 'completed': 'Review CHECK-IN 2 before any new study',
                  'running': 'Wait for the owned supervised worker; do not start another attempt',
                  'failed': 'Inspect retained failure; changed/retried work needs a new plan',
                  'invalid': 'Resolve stale or missing artifacts without overwriting evidence'}[status],
              'physics_validated': False, 'scope': 'Supplied-data adapter delivery, not scientific closure or independent review'}
    if write:
        atomic_json(rd / 'current_state.json', result)
    return result


class RunningStudy(Exception):
    """Internal control flow: an active study is not a failed completed study."""


def run(rundir, *, resume=False):
    rd = root(rundir)
    with file_lock(rd / 'logs/science.lock', blocking=False):
        p = verify_plan(rd, approved=True)
        if (rd / 'execution_attempt.json').exists() or (rd / 'execution_state.json').exists():
            if resume and packet(rd)['lifecycle_verdict'] == 'PASS':
                return 0
            raise ValueError('the one approved attempt is spent; --resume only verifies valid completed work')
        atomic_json(rd / 'execution_attempt.json', {'attempt': 1, 'plan_sha256': execution.file_hash(rd / PLAN),
                    'budget_seconds': p['max_seconds'], 'started_utc': execution.utc_now()})
        from ravel.workflow.stage_supervisor import supervise
        s = p['stages'][0]
        code = supervise(s['stage'], str(rd), 0, 'logs/science-worker.log', s['command'],
            kill_secs=p['max_seconds'], poll=.2, grace=2, inputs=s['inputs'], outputs=s['outputs'], depends_on=[], cwd=str(rd))
    state = packet(rd, write=True)
    return code or (0 if state['lifecycle_verdict'] == 'PASS' else 3)
