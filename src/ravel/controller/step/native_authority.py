"""Consequential native launch decisions through observed RDJ and operator authority."""
from __future__ import annotations

from copy import deepcopy

from . import launch_gate, spec
from .services import StepHold


def active(rundir, action):
    """An authenticated historical exact context selects this bridge, even after revocation.

    History is deliberate: superseding a decision must hold, never revive a legacy path.
    Caller markers and a two-pin cost context cannot select this mechanism.
    """
    from ravel.controller.store import RunStore, controller_owned
    from ravel.controller.authority import common, retained
    owner = controller_owned(rundir)
    if owner is None:
        return False
    store = RunStore(owner)
    if store.check_binding(rundir) or store.verify():
        raise ValueError('native authority selection needs a bound verified controller journal')
    # The verified append-only journal establishes genuine absence without opening issuer state.
    if not store.scan(retained.KIND):
        return False
    pins = action.get('view_pins') if type(action) is dict else None
    if type(pins) is not dict or set(pins) != launch_gate.PIN_FIELDS:
        return False
    return any(row.get('kind') == 'r3_action' and row.get('view', {}).get('pins') == pins
               for row in common.scan(store, retained.KIND, retained.SCHEMA))


def _approved(store, plan, step, proof):
    from ravel.controller.authority import rdj, retained
    from ravel.workflow import rdj_approval
    approved = retained.current(store, 'approve_plan')
    pins = approved['view']['pins']
    if pins.get('plan_sha256') != plan['sha256'] or approved['plan'].get('sha256') != plan['sha256']:
        raise ValueError('the retained approval covers another current plan')
    missing, mapped = rdj_approval.evaluate(store.run_dir, rdj.approval_action(pins))
    if missing:
        raise ValueError('native action requires current plan review: ' + '; '.join(missing))
    launch_gate._scientific_review(store, plan, step, proof)
    return approved, mapped


def verified_operator(store, pins, identifier=None):
    """Authenticate the canonical current exact operator admit; no machine default is credit."""
    from ravel.controller.authority import common, service
    if identifier is None:
        current = service.current(store, 'r3_action', subject=pins)
        identifier = (current or {}).get('id')
    if type(identifier) is not str or not identifier:
        raise ValueError('native R3 requires current authenticated operator authority')
    record = service.verify(store, identifier, kind='r3_action', subject=pins)
    if (type(record) is not dict or record.get('id') != identifier or record.get('kind') != 'r3_action'
            or record.get('label') != common.OPERATOR_COMMAND or record.get('source') != 'operator_cli'
            or record.get('authorizes_effects') is not True or record.get('decision') != 'approve'
            or record.get('option') != 'admit' or (record.get('subject') or {}).get('pins') != pins):
        raise ValueError('native R3 requires exact verified operator_cli approve/admit authority')
    return record


def evaluate(rundir, action):
    """Read-only exact launch evaluator; never calls launch_gate.approval recursively."""
    from ravel.controller.authority import rdj
    return rdj.evaluate_native(rundir, action)


def prepare(store, step, context, preflight):
    """Capture the exact native decision, dispatch its ordinary critic and request authority."""
    from ravel.controller.authority import common, retained, rdj, service
    from ravel.workflow import rdj_loop
    action = launch_gate.action(step, context, preflight, preflight.get('native_preflight'))
    actual_store, plan, actual, proof = launch_gate.load(store.run_dir, action)
    required, factors = rdj_loop.compute_class(store.run_dir, 'launch', action)
    result = {'action': action, 'class': required}
    if launch_gate.preparation_implementation(actual) is not None and required not in ('R0', 'R1'):
        raise ValueError('bounded preparation mapping is limited to at-most-R1 actions')
    if rdj_loop.RANK[required] <= rdj_loop.RANK['R2']:
        return result
    approved, _ = _approved(actual_store, plan, actual, proof)
    reading = deepcopy(approved['reading'])
    reading['flags'] += [{'kind': 'risk', 'text': 'Consequential native launch requires an exact observed critic '
                         'and current authenticated operator authority; class ' + required + '.'}]
    view = {'run_id': actual_store.run_id, 'pins': deepcopy(action['view_pins']),
        'sections': [
            {'id': 'preamble', 'title': 'Consequential native action',
             'lines': ['Decide the exact protected native launch at consequence class ' + required + '.',
                       'Computed factors: ' + common.canonical(factors)]},
            {'id': 'action', 'title': 'Action', 'lines': [
                'Step: ' + common.canonical(actual), 'Launch: ' + common.canonical(spec.launch(actual)),
                'Attempt: ' + action['view_pins']['attempt'],
                'Protected preflight: ' + common.canonical(proof),
                'Resources: ' + common.canonical(action['budget'])]}],
        'flags': deepcopy(reading['flags']), 'items': retained.view_items(plan, reading),
        'options': [{'id': 'admit', 'text': 'Admit this exact native action within its reserved budget', 'effect': True},
                    {'id': 'hold', 'text': 'Hold this native action', 'effect': False}]}
    view = retained.capture(actual_store, 'r3_action', plan=plan, reading=reading, view=view)['view']
    rdj.dispatch_native(actual_store, action, context)
    bounds = _bounds(actual, proof)
    found = service.request(actual_store, 'r3_action', {'view': view, 'conservative_default': 'hold'}, bounds)
    if 'pending' in found:
        pending = found['pending']
        if type(pending) is dict and pending.get('errors'):
            raise StepHold('authority_request_invalid',
                'the native check-in did not validate against run state: ' + '; '.join(map(str, pending['errors'])),
                evidence={'pending': pending})
        return {**result, 'pending': deepcopy(found['pending'])}
    verified = verified_operator(actual_store, action['view_pins'], found.get('id'))
    return {**result, 'authority': verified['id']}


def _bounds(step, proof):
    from ravel.controller.authority.operator import BUDGET_KEYS, _number, budget_integer
    mapped = {}
    for key, value in proof['budget'].items():
        if key == 'attempts' or value is None:
            continue
        dimension = 'model_calls' if key == 'broker_calls' else key
        if dimension not in BUDGET_KEYS or not _number(value, integer=budget_integer(dimension)):
            raise ValueError('native authority requires finite numeric reserved resource bounds')
        mapped[dimension] = mapped.get(dimension, 0) + value
    stage = proof.get('stage') or (spec.launch(step) or {}).get('stage') or step.get('operation') or step['kind']
    return {'rung': step.get('rung') or 'none', 'stages': [stage], 'budget': mapped}
