"""Operator cost tolerance and result-backed admission within current resource ceilings."""
from copy import deepcopy

from ravel.controller.step import custody, spec
from ravel.controller.step.operations import current_plan
from ravel.controller.step.services import StepHold, module, records
from .records import digest

KIND = 'compute-policy-admission'
MODES = ('bounded', 'generous', 'adaptive')
DEFAULT = {'mode': 'bounded'}


def _rows(store, kind):
    return [{**row, 'record_id': row.get('record_id', row.get('_record_id'))} for row in records(store, kind)]


def validate(value):
    if type(value) is not dict or set(value) != {'mode'} or value['mode'] not in MODES:
        raise ValueError('compute_policy requires mode: bounded, generous or adaptive')
    return deepcopy(value)


def grant(store):
    authority = module('authority')
    frozen = authority.frozen(store, required=False)
    if frozen is None:
        return None, deepcopy(DEFAULT)
    return frozen, validate(frozen.get('compute_policy', DEFAULT))


def _adopted(store, context, plan, artifact, *, document=True):
    from ravel.controller.routes.study.contracts import adopted_json
    if type(artifact) is not str or artifact.count(':') != 1:
        raise ValueError('compute evidence names a declared artifact')
    sid, path = artifact.split(':', 1)
    producers = [s for s in plan['steps'] if s['id'] == sid
                 and any(o.get('path') == path for o in s.get('outputs') or [])]
    outcome = custody.outcomes(store).get(sid) or {}
    if len(producers) != 1 or outcome.get('status') != 'completed':
        raise ValueError('compute evidence requires its completed declared producer')
    consumer = {'inputs': [{'artifact': artifact}], 'depends_on': [sid]}
    problems, pins, _ = custody.input_errors(store, consumer, context['run_dir'])
    if problems or len(pins) != 1 or pins[0].get('attempt') != outcome.get('attempt'):
        raise ValueError('compute evidence requires current accepted custody')
    if not document:
        return None, pins[0]
    return adopted_json({**context, 'store': store, 'plan': plan}, artifact)


def justification(store, step, context):
    """Check the chosen spend against the current plan and completed result artifacts."""
    artifact = (step.get('parameters') or {}).get('compute_justification')
    plan = current_plan(store, context)
    value, source = _adopted(store, context, plan, artifact)
    required = {'schema_version', 'kind', 'plan_sha256', 'step_sha256', 'decision',
                'expected_gain', 'cost_justification', 'evidence_artifacts'}
    if (type(value) is not dict or set(value) != required or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['kind'] != 'compute-justification'
            or value['plan_sha256'] != context.get('plan_sha256')
            or value['step_sha256'] != spec.step_sha256(step) or value['decision'] != 'continue'
            or any(type(value[k]) is not str or not value[k].strip() or len(value[k]) > 16000
                   for k in ('expected_gain', 'cost_justification'))):
        raise ValueError('adaptive cost needs the current result-backed continuation decision')
    artifacts = value['evidence_artifacts']
    if (type(artifacts) is not list or not 1 <= len(artifacts) <= 128
            or any(type(a) is not str for a in artifacts) or len(set(artifacts)) != len(artifacts)
            or artifact in artifacts or any(a.split(':', 1)[0] == step['id'] for a in [artifact, *artifacts])):
        raise ValueError('adaptive cost needs distinct completed result evidence')
    evidence = [_adopted(store, context, plan, a, document=False)[1] for a in artifacts]
    if not set(artifacts) <= set(source.get('inputs') or []):
        raise ValueError('the adopted decision carries its consumed result receipts')
    # A decision and its result records each retain their source bytes and controller custody.
    return {'artifact': artifact, 'decision': value, 'source': source, 'evidence': evidence}


def admit(store, step, amounts, context):
    """Use the frozen operator grant; existing reservation checks enforce every ceiling."""
    frozen, policy = grant(store)
    mode = policy['mode']
    if mode == 'bounded':
        return None
    proof = None
    if mode == 'adaptive':
        try:
            proof = justification(store, step, context)
        except (ValueError, KeyError, OSError, TypeError):
            return None
    if frozen is None:
        return None
    body = {'schema_version': 1, 'kind': KIND, 'mode': mode, 'mode_record': frozen['id'],
            'grant_sha256': digest({'policy': policy, 'budgets': frozen['budgets'],
                                   'agent_preferences': frozen.get('agent_preferences')}),
            'pins': {'plan_sha256': context.get('plan_sha256'), 'step_sha256': spec.step_sha256(step)},
            'amounts': deepcopy(amounts), 'justification': proof}
    for prior in _rows(store, KIND):
        if all(prior.get(k) == v for k, v in body.items()):
            return prior
    identifier = store.append(KIND, body)
    return {**body, 'record_id': identifier}


def verify(store, reservation_id, pins, context):
    """Recheck frozen grant, exact reservation and source receipts immediately before dispatch."""
    reservations = [r for r in _rows(store, 'budget-reservation') if r.get('record_id') == reservation_id]
    if len(reservations) != 1:
        raise StepHold('compute_policy_changed', 'compute admission requires its protected reservation')
    reserved = reservations[0]
    identifier = (reserved.get('basis') or {}).get('compute_policy')
    matches = [r for r in _rows(store, KIND) if r.get('record_id') == identifier]
    if len(matches) != 1 or matches[0]['pins'] != pins or matches[0]['amounts'] != reserved['amounts']:
        raise StepHold('compute_policy_changed', 'compute admission binds the current step and allocation')
    frozen, policy = grant(store)
    found = matches[0]
    if (frozen is None or found['mode_record'] != frozen['id'] or policy['mode'] != found['mode']
            or found['grant_sha256'] != digest({'policy': policy, 'budgets': frozen['budgets'],
                                              'agent_preferences': frozen.get('agent_preferences')})):
        raise StepHold('compute_policy_changed', 'compute admission requires the current frozen operator grant')
    if found['mode'] == 'adaptive':
        try:
            plan = current_plan(store, context)
            step = next(s for s in plan['steps'] if spec.step_sha256(s) == pins['step_sha256'])
            if justification(store, step, context) != found['justification']:
                raise ValueError('adaptive evidence changed')
        except (ValueError, KeyError, OSError, TypeError, StopIteration):
            raise StepHold('compute_policy_changed', 'adaptive compute requires its current result receipts') from None
    elif found['mode'] != 'generous':
        raise StepHold('compute_policy_changed', 'the frozen policy supplies cost admission')
    return found
