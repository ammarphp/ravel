"""Declared host operations: actor/path admission and host output receipts.

The executor registry's coordinator role owns its host declarations. They are
controller launches, never production-worker assignments. Receipt evidence is
re-read from the protected launch journal at adoption and at every later use.
"""
from __future__ import annotations

from copy import deepcopy

from .services import StepHold, digest, records


DECISION = 'host-operation-decision'
RECEIPT = 'host-operation-receipt'
ACQUISITION_BACKEND = 'controller-acquisition'


def identity(step):
    """The approved scientific identity of a host step: the engagement decision's applied view (seats, folds,
    correction bounds) is pinned by its own digest and may be re-applied after an escalation; the receipt binds
    the step the approved plan states, as the plan record stores it."""
    from .spec import scientific_step
    return digest(scientific_step(step))


def declaration(operation, table=None):
    if table is None:
        from .operations import executors
        table = executors()
    hosts = table.get('host_operations', {})
    if operation not in hosts:
        return None
    role = (table.get('coordinator') or {}).get('role')
    if not isinstance(role, str) or not role or not isinstance(hosts[operation], str) or not hosts[operation]:
        raise StepHold('host_operation_declaration_invalid', 'a host declaration needs its actor and reason')
    from ravel.workflow import role_registry
    if role_registry.load(role)['family'] != 'coordination':
        raise StepHold('host_operation_declaration_invalid', 'the declared host actor must be a coordination role')
    return {'operation': operation, 'role': role, 'reason': hosts[operation]}


def admission_errors(step, table=None, *, branch=None):
    declared = declaration(step.get('operation'), table)
    if declared is None:
        return []
    from .spec import branch as step_branch
    errors = []
    if step.get('role') not in (None, declared['role']):
        errors.append({'code': 'host_operation_role_mismatch', 'required': declared['role'],
                       'named': step.get('role'), 'operation': declared['operation']})
    # An omitted actor denotes the registry's host actor; it never denotes an arbitrary worker.
    if step.get('kind') not in ('acquire', 'operate') or (branch or step_branch(step)) != 'launch':
        errors.append({'code': 'host_operation_path_mismatch', 'operation': declared['operation']})
    return errors


def admit(store, step, attempt, *, branch='launch'):
    declared = declaration(step.get('operation'))
    if declared is None:
        return None
    errors = admission_errors(step, branch=branch)
    status = 'refused' if errors else 'admitted'
    record = store.append(DECISION, {'schema_version': 1, 'step_id': step['id'], 'attempt': attempt,
        'step_sha256': identity(step), 'declaration': declared, 'declaration_sha256': digest(declared),
        'branch': branch, 'status': status, 'errors': errors})
    if errors:
        raise StepHold(errors[0]['code'], 'use the declared host actor and controller launch path',
                       evidence={'record': record, 'errors': errors})
    return record


def _body(row):
    return {k: deepcopy(v) for k, v in row.items() if k != '_record_id'}


def _observed(store, step, attempt, launch):
    errors = admission_errors(step, branch='launch')
    if errors:
        raise StepHold(errors[0]['code'], 'host output adoption must preserve its actor and path')
    declared = declaration(step.get('operation'))
    starts = [r for r in records(store, 'step-launch') if r.get('_record_id') == launch.get('journal_id')]
    if len(starts) != 1:
        raise StepHold('host_operation_receipt_missing', 'the protected host launch start is required')
    start = starts[0]
    decisions = [r for r in records(store, DECISION) if r.get('_record_id') == start.get('host_decision')]
    if len(decisions) != 1 or any(decisions[0].get(k) != v for k, v in {
            'step_id': step['id'], 'attempt': attempt, 'step_sha256': identity(step), 'status': 'admitted',
            'branch': 'launch', 'declaration': declared, 'declaration_sha256': digest(declared)}.items()):
        raise StepHold('host_operation_receipt_changed', 'the host admission decision must bind this exact launch')
    if (start.get('phase') != 'started' or start.get('step_id') != step['id'] or start.get('attempt') != attempt
            or not start.get('launch_sha256') or start.get('launch_sha256') != launch.get('launch_sha256')):
        raise StepHold('host_operation_receipt_changed', 'the host launch start differs from its adoption')
    finishes = [r for r in records(store, 'step-launch') if r.get('started') == start['_record_id']
                and r.get('phase') == 'finished']
    if len(finishes) != 1:
        raise StepHold('host_operation_receipt_missing', 'exactly one protected host launch completion is required')
    finish = finishes[0]
    failed = (finish.get('step_id') != step['id'] or finish.get('attempt') != attempt
              or finish.get('exit_status') != 0 or finish.get('timed_out') is not False
              or not finish.get('backend')
              or finish.get('inventory') != launch.get('inventory') or launch.get('exit_status') != 0
              or launch.get('backend') != finish['backend'])
    extra = {}
    if finish.get('backend') == ACQUISITION_BACKEND and step.get('kind') == 'acquire':
        # The governed in-process acquisition is not a confined launch: its own completed
        # acquisition evidence replaces the confined plan, qualification and confinement rows.
        acquired = finish.get('acquisition')
        if (failed or type(acquired) is not dict or acquired.get('exit_status') != 0
                or type(acquired.get('members')) is not list
                or type(acquired.get('source_admission')) is not dict):
            raise StepHold('host_operation_receipt_changed', 'a successful governed acquisition host receipt is required')
        extra = {'acquisition_sha256': digest(acquired)}
    else:
        plan, confined = finish.get('plan') or {}, finish.get('confinement')
        qualification = plan.get('qualification') or {}
        if (failed or plan.get('kind') != 'confined'
                or qualification.get('confirmed') is not True or qualification.get('backend') != finish['backend']
                or type(confined) is not dict or confined.get('errors') != []):
            raise StepHold('host_operation_receipt_changed', 'a successful qualified confined host receipt is required')
    return {'schema_version': 1, 'step_id': step['id'], 'attempt': attempt,
            'step': deepcopy(step), 'step_sha256': identity(step), 'declaration': declared,
            'declaration_sha256': digest(declared), 'decision': decisions[0]['_record_id'],
            'journal_id': start['_record_id'], 'launch_sha256': start['launch_sha256'],
            'finished_id': finish['_record_id'], 'finished_sha256': digest(_body(finish)),
            'backend': finish['backend'], 'inventory': deepcopy(finish['inventory']), **extra}


def receipt(store, step, attempt, launch):
    if declaration(step.get('operation')) is None:
        return None
    body = _observed(store, step, attempt, launch)
    identifier = store.append(RECEIPT, body)
    return {'operation': step['operation'], 'host_role': body['declaration']['role'],
            'host_receipt': identifier, 'host_receipt_sha256': digest(body)}


def _planned_step(store, step_id):
    import json
    for plan in reversed(records(store, 'plan')):
        if plan.get('source') == 'judgment-planning':
            continue
        if not plan.get('blob'):
            return None
        try:
            steps = json.loads(store.get_blob(plan['blob'])).get('steps', [])
        except (ValueError, KeyError, OSError, TypeError, AttributeError):
            return None  # an older plan cannot replace an unreadable current plan
        return next((s for s in steps if s.get('id') == step_id), None)
    return None


def custody_errors(store, record):
    """Recheck the protected receipt, including records whose producer fields were stripped."""
    producer = record.get('producer') or {}
    step = _planned_step(store, record.get('step_id'))
    observed = [r for r in records(store, DECISION) if r.get('step_id') == record.get('step_id')
                and r.get('attempt') == record.get('attempt') and r.get('status') == 'admitted']
    operation = (((observed[-1].get('declaration') or {}).get('operation') if observed else None)
                 or producer.get('operation') or (step or {}).get('operation'))
    if declaration(operation) is None:
        return []
    try:
        if step is None or step.get('operation') != operation:
            raise StepHold('host_operation_receipt_changed', 'the current approved plan must retain its host step')
        matching = [r for r in records(store, RECEIPT) if r.get('_record_id') == producer.get('host_receipt')]
        if len(matching) != 1:
            raise StepHold('host_operation_receipt_missing', 'host custody needs its protected receipt')
        row = matching[0]
        body = _body(row)
        if (digest(body) != producer.get('host_receipt_sha256') or producer.get('kind') != 'launch'
                or row.get('attempt') != record.get('attempt') or row.get('step_id') != record.get('step_id')
                or record.get('owner_role') != (row.get('declaration') or {}).get('role')
                or step is not None and identity(step) != row.get('step_sha256')):
            raise StepHold('host_operation_receipt_changed', 'host custody differs from its approved receipt')
        observed = _observed(store, row['step'], row['attempt'], {
            'journal_id': row['journal_id'], 'launch_sha256': row['launch_sha256'],
            'inventory': row['inventory'], 'exit_status': 0, 'backend': row['backend']})
        if observed != body or producer.get('journal_id') != row['journal_id']:
            raise StepHold('host_operation_receipt_changed', 'the protected host completion changed')
        source_path = record.get('source_path') or record.get('path')
        if not any(r.get('path') == source_path and r.get('sha256') == record.get('sha256')
                   for r in row['inventory']):
            raise StepHold('host_operation_receipt_changed', 'host output bytes are outside its receipt')
    except (StepHold, KeyError, ValueError, TypeError) as exc:
        return [{'code': getattr(exc, 'reason', 'host_operation_receipt_changed'), 'artifact': record.get('artifact')}]
    return []
