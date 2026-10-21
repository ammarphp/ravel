"""``controller.step``: the governed step every step of every route runs through.

```
reserve → cost_authority → packet → preflight ─┬─ consult ═Send═► consult seats (controller.seat) → consult_join → packet
                              ├─ dispatch (sandboxed worker) ──────────────┐
                              ├─ launch (confined operation) ──────────────┤
                              ├─ subgraph (registered graph) ──────────────┤
                              └─ parent (ask, route) ─────────────────► finish
                                                                           ▼
observe → validate ─┬─ adopt → checks ─┬─ review ═Send═► review seats (controller.seat) → credit ─┐
                    │                  └───────────────────────────────────────────────► credit ─┤
                    └─ (failed or held) ────────────────────────────────────────────────────────┤
                                                       ledger_update → escalation → finish → END
```

The input view is ``{"step": <step.v1>, "context": {...}}`` (the controller graph's fan-out packet);
the step outcome is ``results["step"]``. ``controller.seat`` is the same machinery for one review
or consult seat of a step: reserve → materialise → packet → preflight → dispatch → observe →
validate → adopt (its own outputs, after a passed validation) → ledger_update → finish,
outcome ``results["seat"]``.

An uncalibrated top-rung operation cost takes the cost check-in's conservative default (``pilot_first``) when
the run is unattended or the authority answers with that default: ``reserve`` runs the derived pilot rung
(``budget.pilot_step``) as a nested ``controller.step`` thread of the same plan step in its own scope and
reservation key, through these same nodes but without adoption, records its calibration only when it completes,
and re-enters reservation, which admits the full rung from that matched calibration alone.

Every node reads the run store from the context's run handle, re-derives what it needs from the
store and the installed registries, and records what it did there; graph state carries ids and
digests. A typed refusal is a hold with its reason; a failed attempt is an outcome the controller
graph may retry within the step's attempt limit; an escalation is an outcome the controller graph
acts on. Nothing a worker writes decides any of them.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib import import_module
from ravel.workflow import private_files
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Annotated, TypedDict

from ravel.workflow import graph_nodes as nodes

from . import budget, cards, custody, escalation as escalations, evidence, operations, seats, spec, validate
from . import binding as plan_binding, seat_rows as seat_closure, native_rows, native_checks, subgraph_usage
from .services import StepHold, digest, module, records, store_for, unwrap

GRAPH_ID = 'controller.step'
SEAT_GRAPH = 'controller.seat'
DISPATCH = 'step-dispatch'
OBSERVATION = 'step-observation'
VALIDATION = 'step-validation'
CREDIT = 'step-credit'
REFUSAL = 'step-refusal'
CONSULT = 'step-consult'
LAUNCH = 'step-launch'
REGISTRY_PIN = 'role-registry-pin'
# A blind reviewer that may not see the producer's result derives its own value; the controller compares them.
BLIND_VERIFICATION = 'blind_verification'
INDEPENDENT_VALUE = 'independent-value'
VERIFICATION = 'step-verification'
OUTCOMES = ('completed', 'revise', 'failed', 'held', 'escalated', 'budget_exhausted', 'stopped')
BUDGET_HOLDS = ('budget_exhausted', 'budget_unknown_request', 'budget_ceiling_missing')
STOP_HOLDS = ('run_stopped', 'stop_requested')
MAX_SEATS = 16


def _merge(left, right):
    result = dict(left or {})
    result.update(deepcopy(right or {}))
    return result


class View(TypedDict, total=False):
    meta: dict
    step: dict
    context: dict


class SeatView(TypedDict, total=False):
    meta: dict
    step: dict
    context: dict
    seat: dict


class State(nodes.BaseState, total=False):
    step: dict
    context: dict
    seat: dict
    acting: dict
    branch: str
    card: dict
    reservation: dict
    packet: dict
    preflight: dict
    native_authority: dict
    consult: dict
    worker: dict
    launch: dict
    child: dict
    observation: dict
    validation: dict
    adoption: dict
    checks: dict
    review: dict
    credit: dict
    escalation: dict
    ledger: dict
    outcome: dict
    evaluations: Annotated[dict, _merge]


# ---- state helpers ---------------------------------------------------------------------------

def _ctx(state):
    return state.get('context') or {}


def _store(state):
    ctx = _ctx(state)
    return store_for({'run_id': ctx.get('run_id'), 'store_root': ctx.get('store_root')})


def _run_dir(state):
    value = _ctx(state).get('run_dir')
    if type(value) is not str or not value or not Path(value).is_absolute():
        raise StepHold('run_dir_missing', 'the step context names the absolute run directory')
    return Path(value)


def _attempt(state):
    return spec.attempt(_ctx(state))


def _seat(state):
    return state.get('seat')


def _pilot(state):
    """This attempt is the derived pilot rung of its step (the controller's own nested launch, never a plan step)."""
    return bool(_ctx(state).get('pilot')) and _seat(state) is None


def _seat_key(state):
    """The seat this attempt is: a review or consult seat's key; for a review seat the controller runs as a step of
    its own (a check-in seat, ``parameters.seat_kind`` review), ``seat:<role>:1``, because several cards review
    under one step id and each needs its own worker node, reservation, records and ledger seat; None for a step's
    producer."""
    seat = _seat(state)
    if seat is not None:
        return seat['key']
    if _pilot(state):
        return budget.PILOT_RUNG
    step = state.get('acting') or state.get('step') or {}
    if (step.get('parameters') or {}).get('seat_kind') == 'review' and step.get('role'):
        return f"seat:{step['role']}:1"
    return None


def _node_id(state):
    return spec.worker_node(state['step']['id'], _seat_key(state))


def _card(state, *, constrained=True):
    """The effective card of the acting role, reloaded under the run's pinned registry."""
    info = state.get('card')
    if not info:
        return None
    card, card_sha, _ = cards.resolve(info['id'], {'registry_sha256': info['registry_sha256']})
    if card_sha != info['sha256']:
        raise StepHold('role_identity_changed', f"the card of {info['id']} changed during the step")
    declared = (_seat(state) or {}).get('declared') or _declared_descriptor(state)
    return cards.engagement_card(card, declared) if constrained and declared else card


def _declared_descriptor(state):
    """The applied view's seat descriptor the acting derived review seat carries inline (``engagement_seat``) or names
    by reference (``engagement_seat_ref``, resolved from the pinned applied view and checked against the duties the
    seat carries), else None."""
    acting = state.get('acting') or {}
    parameters = acting.get('parameters') or {}
    if parameters.get('engagement_seat_ref') is None:
        return parameters.get('engagement_seat')
    return operations.referenced_seat(operations.current_plan(_store(state), _ctx(state)), acting)


def _evaluate(state, row, status, **evidence_):
    return {row: {'status': status, 'evidence': deepcopy(evidence_)}}


def _fact(state, mechanism, **facts):
    """Retain the checked facts behind a mechanism assertion in the protected store."""
    record = _store(state).append('step-fact', {
        'step_id': state['step']['id'], 'seat': _seat_key(state), 'attempt': _attempt(state),
        'mechanism': mechanism, **deepcopy(facts)})
    return {'mechanism': mechanism, 'record': record}


def _running(store):
    state = module('authority').stop_state(store)
    if state != 'running':
        raise StepHold('run_stopped', f'the run is {state}; only the operator or the physicist resumes it')


def seat_step(parent, seat):
    """The derived step of one review or consult seat of ``parent`` (never a plan step).

    A blind verification seat (``seat['mode']``) reads the parent's governed inputs, not its outputs, and
    declares one more output: its own value of the quantity the parent's approved ``verification`` names.
    """
    purpose, role, number = seat['purpose'], seat['role'], seat['n']
    kind = 'review-findings' if purpose == 'review' else 'consult-record'
    depends = [parent['id']] if purpose == 'review' else list(parent['depends_on'])
    identity = f"{parent['id'][:80]}.{purpose}.{digest(seat['key'])[:16]}"
    outputs = [{'path': f'outputs/{purpose}-{role}-{number}.json', 'kind': kind, 'required': True}]
    parameters = {'seat_of': parent['id'], 'purpose': purpose, 'subject_sha256': seat['subject']['sha256'],
                  'reviewer_items': deepcopy(seat.get('items') or []), 'trigger': seat.get('trigger')}
    # A seat starts one model session: it shares the session dimensions of its step. Events and core-hours are
    # counted where a launch generates them, so a seat never re-reserves its parent's launch share.
    resource_dimensions = ('wall_seconds', 'broker_calls', 'tokens', 'cost_usd')
    parent_budget = parent.get('budget') or {}
    budget = {dimension: deepcopy(parent_budget[dimension]) for dimension in resource_dimensions
              if dimension in parent_budget}
    parent_minimum = (parent.get('parameters') or {}).get('budget_minimum') or {}
    minimum = {dimension: deepcopy(parent_minimum[dimension]) for dimension in budget
               if dimension in parent_minimum}
    for dimension, amount in minimum.items():
        ceiling = budget[dimension]
        required = max(amount, 1 if dimension == 'wall_seconds' else 0)
        if required > ceiling:
            raise StepHold('seat_budget_infeasible', 'the seat minimum exceeds its inherited resource share',
                           evidence={'dimension': dimension, 'minimum': required, 'ceiling': ceiling})
    if 'wall_seconds' in budget and budget['wall_seconds'] < 1:
        raise StepHold('seat_budget_infeasible', 'a seat needs at least one wall second',
                       evidence={'dimension': 'wall_seconds', 'minimum': 1, 'ceiling': budget['wall_seconds']})
    if minimum:
        parameters['budget_minimum'] = minimum
    if seat.get('mode') == BLIND_VERIFICATION:
        outputs.append({'path': f'outputs/independent-{role}-{number}.json', 'kind': INDEPENDENT_VALUE,
                        'required': True})
        parameters.update(mode=BLIND_VERIFICATION, method=seat.get('method'),
                          verification=deepcopy(seat.get('verification') or {}))
    result = {'id': identity, 'kind': 'review' if purpose == 'review' else 'derive',
            'role': role, 'operation': None,
            'inputs': [{'artifact': a['artifact'], 'sha256': a['sha256']} for a in seat['subject']['artifacts']],
            'outputs': outputs, 'depends_on': depends, 'waypoint': False, 'rung': None, 'budget': budget,
            'protocols': list(parent.get('protocols') or []), 'review': [], 'instruction_sources': [],
            'obligations': [], 'parameters': parameters}
    if purpose == 'review':
        inherited = _seat_check_inputs(parent, seat['subject'])
        if inherited is not None:
            result['parameters']['check_inputs'] = inherited
    if seat.get('declared'):
        result['parameters']['engagement_seat'] = deepcopy(seat['declared'])
        result['engagement'] = deepcopy((seat['declared'].get('step') or {}).get('engagement') or {})
    return result


def _seat_check_inputs(parent, subject):
    """The parent's approved validator parameters as a review seat checks them: a pin naming one of the parent's
    declared outputs (``{"output": <path>}``) is bound to the exact bytes of the reviewed attempt (the seat's
    subject); an output outside that subject stays unbound, naming its producer, so its validator refuses it and the
    seat never binds it to its own outputs. ``None`` when the parent declares no parameter object."""
    declared = (parent.get('parameters') or {}).get('check_inputs')
    if type(declared) is not dict:
        return None
    reviewed = {row['artifact']: row['sha256'] for row in subject.get('artifacts') or ()}

    def bind(value):
        if type(value) is dict and set(value) == {'output'} and type(value['output']) is str:
            sha = reviewed.get(f"{parent['id']}:{value['output']}")
            if sha is None:
                return {'output': value['output'], 'step': parent['id']}
            return {'path': custody.destination(parent['id'], value['output']), 'sha256': sha}
        return deepcopy(value)
    return {check: ({key: bind(value) for key, value in parameters.items()} if type(parameters) is dict
                    else deepcopy(parameters)) for check, parameters in declared.items()}


def registry_pin(store, context):
    """The role-registry digest of the run: the context's pin, else the first step's record in the store."""
    pinned = (context or {}).get('registry_sha256')
    if type(pinned) is str and len(pinned) == 64:
        return pinned
    from ravel.workflow import role_registry
    from ravel.workflow.state_io import file_lock
    from .services import lock_path
    with file_lock(lock_path(store, 'registry-pin')):
        rows = records(store, REGISTRY_PIN)
        if rows:
            return rows[0]['registry_sha256']
        current = role_registry.registry_sha256()
        store.append(REGISTRY_PIN, {'schema_version': 1, 'registry_sha256': current})
        return current


# ---- reserve ---------------------------------------------------------------------------------

# The research loop's role calls enter ``step.run`` as derived child steps (``research_controller``).
ORCHESTRATING_RESEARCH_GRAPH = 'research.loop'


def _subgraph_registration(step):
    from ravel.workflow import graph_registry
    graph_id = (step.get('graph') or {}).get('id')
    return next((row for row in graph_registry.load() if row['id'] == graph_id), {})


def _amounts(step, card, branch, *, subgraph_root=None):
    share = step.get('budget') or {}
    if branch == 'worker':
        budgets, _ = cards.worker_budgets(card, step)
        return {'wall_seconds': budgets['max_wall_seconds'], 'model_calls': budgets['max_turns'],
                'tokens': share.get('tokens'), 'cost_usd': budgets['max_cost_usd'], 'core_hours': 0,
                'events': share.get('events', 0) or 0, 'children': 1}
    if branch == 'launch':
        from .launch_gate import STUDY_ADAPTER
        launch = spec.launch(step) or {}
        signature = operations.signatures().get(step.get('operation')) or {}
        wall = share.get('wall_seconds')
        if spec.parameters(step).get('adapter') != STUDY_ADAPTER:
            wall = operations.launch_wall_seconds(step, wall, signature)
        cpus = launch.get('cpus', 1)
        # Generated events are counted where a launch generates them. A launch that reads supplied data declares
        # its input volume (bytes or files) instead and generates none: no event ceiling applies to it (N2).
        parameters = spec.parameters(step)
        effects = signature.get('effects')
        prepared = 'execution_effects' in parameters
        if prepared:
            declared = parameters['execution_effects']
            if (type(declared) is not list or any(type(effect) is not str for effect in declared)
                    or len(set(declared)) != len(declared) or type(effects) is not list
                    or not set(declared) <= set(effects)):
                raise StepHold('operation_effect_undeclared',
                               'launch execution effects must be distinct effects admitted by its signature')
            effects = declared
        supplied = prepared and 'generates_events' not in effects
        input_files = share.get('input_files')
        if supplied:
            # Every declared artifact is a file in the launch's verified read census. Count that census
            # independently of the route template; a larger explicit allocation stays conservative.
            files = len({row['artifact'] for row in step.get('inputs') or ()})
            input_files = max(input_files, files) if input_files is not None else files
        reads = any(type(share.get(k)) in (int, float) for k in ('input_bytes', 'input_files'))
        nongenerating = ((signature.get('cost') or {}).get('unit') in budget.NON_EVENT_UNITS
                         and signature.get('effects') == [])
        generates = type(effects) is list and 'generates_events' in effects
        events = 0 if supplied else share.get('events', 0 if (reads and not generates) or nongenerating else None)
        return {'wall_seconds': wall, 'model_calls': 0, 'tokens': 0, 'cost_usd': share.get('cost_usd', 0),
                'core_hours': None if wall is None else wall * cpus / 3600.0, 'events': events,
                'children': 1, 'input_bytes': share.get('input_bytes'), 'input_files': input_files,
                'batch_cpu_hours': share.get('batch_cpu_hours', 0)}
    if branch == 'subgraph':
        # These bindings perform controller orchestration; any worker calls reserve through child steps. The
        # research loop also reserves every launch through its child steps, so it spends no core-hours itself.
        graph_id = (step.get('graph') or {}).get('id')
        research = graph_id == ORCHESTRATING_RESEARCH_GRAPH
        own_calls = 0 if graph_id in SUBGRAPH_BINDERS or research else None
        row = _subgraph_registration(step)
        resources = row.get('resources') or {}
        declared = dict(share)
        if 'model_calls' not in declared and 'broker_calls' in declared:
            declared['model_calls'] = declared['broker_calls']
        minimum = {}
        if resources.get('budget_builder'):
            try:
                if subgraph_root is None:
                    raise ValueError('the registered resource bound needs its bound child root')
                derive = getattr(import_module(row['module']), resources['budget_builder'])
                minimum = derive(subgraph_root, (step.get('graph') or {}).get('instance') or {})
            except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
                raise StepHold('subgraph_budget_unavailable', str(exc)[:500]) from None
            # A smaller plan share cannot erase the direct workers' declared minimum.
            for dimension, required in minimum.items():
                if declared.get(dimension) is not None and declared[dimension] < required:
                    raise StepHold('seat_budget_infeasible', 'the declared subgraph share cannot fit its workers',
                                   evidence={'dimension': dimension, 'required': required,
                                             'available': declared[dimension]})
        share = {**minimum, **declared}
        return {'wall_seconds': share.get('wall_seconds'),
                'model_calls': share.get('model_calls', own_calls),
                'tokens': share.get('tokens'), 'cost_usd': share.get('cost_usd'),
                'core_hours': share.get('core_hours',
                    0 if research or resources.get('starts_launches') is False else None),
                'events': share.get('events', 0) or 0, 'children': share.get('children', 1) or 1}
    return {d: 0 for d in budget.DIMENSIONS}


def _verified_cost_signoff(store, identifier, pins):
    """Read current authenticated operator authority; a request or resume is no answer."""
    authority = module('authority')
    if type(identifier) is not str or not identifier:
        raise StepHold('uncalibrated_top_rung_cost', 'cost authority needs its canonical protected record id')
    try:
        found = authority.verify(store, identifier, kind='r3_action', subject=pins)
    except Exception as exc:
        if 'AuthorityRefused' in {cls.__name__ for cls in type(exc).__mro__}:
            raise StepHold('authority_refused', str(exc)[:1500]) from None
        if isinstance(exc, (ValueError, KeyError, OSError, TypeError, AttributeError)):
            raise StepHold('authority_request_invalid', str(exc)[:1500]) from None
        raise
    if (type(found) is not dict or found.get('id') != identifier or found.get('kind') != 'r3_action'
            or found.get('source') != 'operator_cli'
            or found.get('label') != getattr(authority, 'OPERATOR_COMMAND', 'operator_command')
            or found.get('authorizes_effects') is not True or found.get('decision') != 'approve'
            or found.get('option') != 'admit' or (found.get('subject') or {}).get('pins') != pins):
        raise StepHold('uncalibrated_top_rung_cost', 'current authenticated operator cost authority is required')
    return found


def _cost_signoff(store, step, amounts, ctx):
    """The physicist's own authority for an uncalibrated top-rung cost (C02); machine approval is not it.

    The request is an R3 check-in rendered from run state: the step and plan pins, what is asked and
    why, and two options, admitting the cost (the effect) or a matched pilot first (the conservative
    default, which takes no effect). The controller retains the compiler plan and
    reading before requesting authority, preserving their flags and inferred facts.
    """
    authority = module('authority')
    rung, operation = step.get('rung'), step.get('operation')
    reserved = {k: v for k, v in amounts.items() if type(v) in (int, float)}
    pins = {'step_sha256': spec.step_sha256(step)}
    if type(ctx.get('plan_sha256')) is str and ctx['plan_sha256']:
        pins['plan_sha256'] = ctx['plan_sha256']
    view = {'run_id': store.run_id, 'pins': pins,
            'sections': [
                {'id': 'preamble', 'title': 'Uncalibrated top-rung cost',
                 'lines': [f"Step {step['id']} asks for the {rung} rung of {operation}.",
                           'No succeeded pilot of the same process on this machine calibrates its cost.']},
                {'id': 'action', 'title': 'Action',
                 'lines': [f'Admit the {rung} rung of {operation} without a matched pilot, within the reserved budget.',
                           'Reserved: ' + ', '.join(f'{k}={v}' for k, v in sorted(reserved.items()))]}],
            'flags': [{'kind': 'risk', 'text': 'the cost of this rung is not calibrated by a matched pilot'}],
            'options': [{'id': 'admit', 'text': 'admit the uncalibrated cost within the reserved budget', 'effect': True},
                        {'id': 'pilot_first', 'text': 'run a matched pilot first', 'effect': False}]}
    try:
        from ravel.controller.authority import retained
        plan = (operations.current_plan(store, ctx) if pins.get('plan_sha256') else
                {'steps': [deepcopy(step)], 'deliverables': deepcopy(step.get('outputs') or [])})
        previous = (retained.current(store, 'approve_plan') if any(
            row.get('kind') == 'approve_plan' for row in records(store, 'authority-context')) else None)
        if previous is not None and previous['plan'].get('sha256') == plan.get('sha256'):
            reading = deepcopy(previous['reading'])
        else:
            intake = records(store, 'intake')
            source = (json.loads(store.get_blob(intake[-1]['reading_blob'])) if intake else {})
            reading = {'request_pins': {}, 'inferred_critical_facts': [
                deepcopy(f) for f in source.get('facts') or [] if type(f) is dict
                and f.get('authority') == 'inferred' and f.get('physics_critical')],
                'flags': deepcopy(source.get('flags') or []),
                'items': {k: deepcopy(source[k]) for k in ('ambiguities', 'questions', 'assumptions') if k in source}}
        reading['flags'] += deepcopy(view['flags'])
        view['flags'] = deepcopy(reading['flags'])
        view['items'] = retained.view_items(plan, reading)
        view = retained.capture(store, 'r3_action', plan=plan, reading=reading, view=view)['view']
        found = authority.request(store, 'r3_action', {'view': view, 'conservative_default': 'pilot_first'},
                                  {'budget': reserved})
    except Exception as exc:
        if type(exc).__name__ == 'AuthorityRefused':
            raise StepHold('authority_refused', str(exc)[:1500]) from None
        if isinstance(exc, (ValueError, KeyError, OSError, TypeError)):
            raise StepHold('authority_request_invalid', str(exc)[:1500]) from None
        raise
    if 'pending' in found:
        pending = found['pending'] or {}
        if pending.get('errors'):
            raise StepHold('authority_request_invalid', 'the cost check-in did not validate against run state',
                           evidence={'pending': pending})
        raise StepHold('awaiting_authority', 'an uncalibrated top-rung cost waits for the physicist\'s answer',
                       evidence={'pending': pending, 'conservative_default': 'pilot_first'})
    if found.get('option') == 'pilot_first':
        # The recorded conservative default: no effect is admitted; the controller derives the pilot rung.
        raise StepHold('uncalibrated_top_rung_cost', 'the conservative default runs a matched pilot first',
                       evidence={'conservative_default': 'pilot_first', 'taken': True, 'authority': found.get('id'),
                                 'label': found.get('label'), 'decision': found.get('decision')})
    if (found.get('label') != getattr(authority, 'OPERATOR_COMMAND', 'operator_command')
            or found.get('decision') != 'approve' or found.get('option') != 'admit'):
        raise StepHold('uncalibrated_top_rung_cost', 'a top-rung cost needs a matched pilot or authenticated '
                       'operator cost authority; a machine or unattested answer authorizes nothing')
    return _verified_cost_signoff(store, found.get('id'), pins)


def _calibration_id(store, step):
    """The matched pilot calibration that admits a top-rung cost, or None."""
    if step.get('rung') not in budget.TOP_RUNGS or step['kind'] not in spec.OPERATION_KINDS:
        return None
    found = budget.calibration(store, step)
    return None if found is None else (found.get('record_id') or found.get('_record_id'))


def _cost_bound(step, amounts, ceilings, branch):
    if step.get('rung') not in budget.TOP_RUNGS or step['kind'] not in spec.OPERATION_KINDS:
        return None
    signature = operations.signatures().get(step.get('operation')) or {}
    found = budget.reservation_bound(step, amounts, ceilings, branch=branch, signature=signature)
    if found is not None:
        return found
    launch = spec.launch(step)
    policy = operations.ANALYSIS_LAUNCHES.get(step.get('operation')) or {}
    known_launch = ((type(launch) is dict and type(launch.get('argv')) is list and bool(launch['argv']))
                    or (launch is None and bool(policy) and signature.get('implementation') == policy['implementation']
                        and step.get('role') == policy['role']))
    from .launch_gate import STUDY_ADAPTER
    if spec.parameters(step).get('adapter') == STUDY_ADAPTER:
        known_launch = False
    return budget.declared_operation_bound(step, amounts, ceilings, branch=branch, signature=signature,
                                           ceiling=operations.resource_ceiling(step, signature),
                                           known_launch=known_launch)


def reserve(state):
    ctx, store = _ctx(state), _store(state)
    parent = spec.check(state['step'])
    seat = _seat(state)
    acting = spec.check(seat_step(parent, seat)) if seat else parent
    if _pilot(state):
        derived, reason = budget.pilot_step(parent)
        if derived is None:
            raise StepHold('pilot_underivable', f'no bounded pilot derives from step {parent["id"]}: {reason}')
        acting = spec.check(derived)
    attempt = spec.attempt(ctx)
    _running(store)
    if seat is None:
        prior = budget.unsettled_prior(store, parent['id'], attempt)
        if prior:
            raise StepHold('prior_attempt_unreconciled', f"attempt {prior[0]['key']} started without a settled "
                           'outcome; reconcile it before a new attempt, never re-dispatch it', evidence={'prior': prior})
    branch = 'worker' if seat else spec.branch(parent)
    card_info, card = None, None
    if branch == 'worker' or (branch == 'launch' and acting.get('role')):
        pinned = registry_pin(store, ctx)
        card, card_sha, registry = cards.resolve(acting['role'], {'registry_sha256': pinned})
        card_info = {'id': card['id'], 'sha256': card_sha, 'registry_sha256': registry, 'version': card['version']}
    resource_root = None
    if branch == 'subgraph' and (_subgraph_registration(acting).get('resources') or {}).get('budget_builder'):
        try:
            bridge = _runtime_child_context({**state, 'acting': acting}, acting['graph']['id'], None, budget_only=True)
            resource_root = bridge[0] if bridge is not None else _run_dir(state)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise StepHold('subgraph_budget_unavailable', str(exc)[:500]) from None
    amounts = _amounts(acting, card, branch, subgraph_root=resource_root)
    ceilings = budget.envelope(store, ctx)
    for dimension in budget.OPTIONAL_DIMENSIONS:
        if amounts.get(dimension) is None:
            # An undeclared input volume is unknown only against a configured ceiling; it never passes one.
            amounts[dimension] = None if ceilings.get(dimension) is not None else 0
    errors = budget.rung_errors(acting)
    if errors:
        raise StepHold(errors[0]['code'], 'the step requests more than its approved rung ceiling',
                       evidence={'errors': errors})
    budget.check_known_request(store, step_id=parent['id'], attempt=attempt, amounts=amounts,
                               ceilings=ceilings, seat=_seat_key(state))
    upper_bound = _cost_bound(acting, amounts, ceilings, branch)
    calibration = budget.calibration_errors(store, acting, upper_bound=upper_bound, amounts=amounts)
    signoff = None
    policy_admission = None
    if calibration and calibration[0]['code'] == 'uncalibrated_top_rung_cost':
        from ravel.controller.engagement import compute
        policy_admission = compute.admit(store, acting, amounts, ctx)
        if (policy_admission is None and ctx.get('unattended') is True and _seat(state) is None and not _pilot(state)
                and budget.pilot_step(acting)[0] is not None):
            # Select the governed lower rung before opening an operator question. This is
            # no authority for either launch; the nested pilot takes every ordinary gate.
            raise StepHold('uncalibrated_top_rung_cost', 'the unattended default takes the bounded pilot first',
                           evidence={'conservative_default': 'pilot_first', 'taken': True,
                                     'controller_default': True})
        if policy_admission is None:
            signoff = _cost_signoff(store, acting, amounts, ctx)
        calibration = budget.calibration_errors(store, acting, signoff=policy_admission or signoff, amounts=amounts)
    if calibration:
        raise StepHold(calibration[0]['code'], 'the top-rung cost forecast is not admitted',
                       evidence={'errors': calibration})
    record = budget.reserve(store, step_id=parent['id'], attempt=attempt, amounts=amounts, ceilings=ceilings,
                            seat=_seat_key(state), parent=ctx.get('parent_step'),
                            basis={'branch': branch, 'card': card_info, 'signoff': (signoff or {}).get('id'),
                                   'compute_policy': (policy_admission or {}).get('record_id'),
                                   'pilot': _calibration_id(store, acting) if signoff is None else None,
                                   'upper_bound': upper_bound,
                                   'step_sha256': spec.step_sha256(acting),
                                   'plan_sha256': ctx.get('plan_sha256') or None})
    evaluations = {}
    evaluations.update(_evaluate(state, 'B01', 'satisfied', record=record['record_id']))
    evaluations.update(_evaluate(state, 'B02', 'satisfied', record=record['record_id']))
    evaluations.update(_evaluate(state, 'G07', 'satisfied', record=record['record_id']))
    if acting.get('rung') is not None:
        evaluations.update(_evaluate(state, 'A07', 'satisfied', rung=acting['rung'], sha256=spec.step_sha256(acting)))
    if acting.get('rung') in budget.TOP_RUNGS and acting['kind'] in spec.OPERATION_KINDS:
        admitted = _fact(state, 'rung-cost-admitted', step=acting, signoff=policy_admission or signoff,
                         calibration_errors=calibration, calibrations=records(store, budget.CALIBRATION),
                         upper_bound=upper_bound,
                         reservation=record['record_id'])
        evaluations.update(_evaluate(state, 'C02', 'satisfied', **admitted))
        evaluations.update(_evaluate(state, 'C13', 'satisfied', **admitted))
    evaluations.update(_evaluate(state, 'C12', 'satisfied', unknown=[d for d, v in amounts.items() if v is None],
                                 mechanism='unknown-costs-retained', record=record['record_id']))
    for row, value in seat_closure.reserve_rows(acting, branch, record['record_id'], top_rungs=budget.TOP_RUNGS,
                                             operation_kinds=spec.OPERATION_KINDS).items():
        evaluations.setdefault(row, value)
    if card is not None:
        evaluations.update(_evaluate(state, 'G01', 'satisfied', role=card['id'], sha256=card_info['sha256']))
        evaluations.update(_evaluate(state, 'SW28', 'satisfied', sha256=card_info['registry_sha256']))
        evaluations.update(_evaluate(state, f"ROLE-{card['id']}-identity", 'satisfied', sha256=card_info['sha256']))
        evaluations.update(_evaluate(state, f"ROLE-{card['id']}-id", 'satisfied', sha256=card_info['sha256']))
        evaluations.update(_evaluate(state, f"ROLE-{card['id']}-family", 'satisfied', family=card['family'], sha256=card_info['sha256']))
    return {'step': parent, 'acting': acting, 'branch': branch, 'card': card_info,
            'reservation': {'key': record['key'], 'record_id': record.get('record_id'), 'amounts': record['amounts']},
            'evaluations': evaluations}


def _pilot_trigger(state, exc):
    """``unattended`` or ``conservative_default`` when an uncalibrated top-rung cost takes its pilot rung, else None.

    The cost check-in records ``pilot_first`` as its conservative default. An unattended run takes it while the
    request is pending; an attended run takes it only when the authority's answer is that default. An admission
    that is not authenticated operator authority is no default and leads to neither the pilot nor the effect. A
    step from which no bounded pilot derives keeps the existing wait for the operator's answer.
    """
    evidence = exc.evidence or {}
    if _pilot(state) or _seat(state) is not None or evidence.get('conservative_default') != 'pilot_first':
        return None
    if budget.pilot_step(state['step'])[0] is None:
        # No bounded pilot derives from this step: the cost check-in keeps waiting for the operator, or holds.
        return None
    if exc.reason == 'awaiting_authority' and _ctx(state).get('unattended') is True:
        return 'unattended'
    if exc.reason == 'uncalibrated_top_rung_cost' and evidence.get('taken') is True:
        if evidence.get('controller_default') is True and _ctx(state).get('unattended') is True:
            return 'unattended'
        return 'conservative_default'
    return None


def _detached(call):
    """Run ``call`` as its own top-level graph thread: the enclosing node's runnable configuration (checkpoint
    namespace, task and send channels) is not inherited, so the nested thread checkpoints in its own scope."""
    import contextvars
    from langchain_core.runnables.config import var_child_runnable_config

    def body():
        var_child_runnable_config.set(None)
        return call()
    return contextvars.copy_context().run(body)


def _pilot_then_reserve(state, cause, trigger):
    """Run the derived pilot rung as a governed launch attempt of this step, then re-enter reservation.

    The pilot is a nested ``controller.step`` thread of the same plan step in its own scope, at rung ``pilot``
    with its own reservation key (``<step>/<attempt>/pilot``): the same cost gate, preflight, authority,
    confinement, launch journal, observation and validation as any launch; its outputs are not adopted. Only a
    completed pilot calibrates; the full rung is then admitted by ``reserve`` from that matched calibration alone.
    A replayed node resumes the same nested thread, so a pilot is never launched twice for one attempt.
    """
    from ravel.workflow import graph_substrate
    from . import custody as custody_
    ctx, store = _ctx(state), _store(state)
    parent = spec.check(state['step'])
    attempt = spec.attempt(ctx)
    derived, reason = budget.pilot_step(parent)
    if derived is None:
        raise StepHold('pilot_underivable', f'the cost default needs a bounded pilot of step {parent["id"]}: {reason}; '
                       'the operator may admit the cost or approve a plan step that declares its pilot',
                       evidence={'reason': reason, 'cause': cause.reason})
    mine = [r for r in records(store, budget.PILOT_LAUNCH) if r.get('step_id') == parent['id']
            and r.get('attempt') == attempt]
    finished = [r for r in mine if r.get('phase') == 'finished']
    if finished and finished[-1].get('status') != 'completed':
        raise StepHold('pilot_failed', 'the pilot rung of this attempt did not complete; no calibration admits the '
                       'full rung', evidence={'pilot': finished[-1].get('_record_id')})
    if not finished:
        if not [r for r in mine if r.get('phase') == 'started']:
            pending = (cause.evidence or {}).get('pending') or {}
            store.append(budget.PILOT_LAUNCH, {
                'schema_version': 1, 'phase': 'started', 'step_id': parent['id'], 'attempt': attempt,
                'pilot_step_id': derived['id'], 'step_sha256': spec.step_sha256(parent),
                'pilot_step_sha256': spec.step_sha256(derived), 'process_sha256': budget.process_pin(derived),
                'bound': derived['budget']['events'], 'rule': derived['parameters']['pilot_of']['rule'],
                'trigger': trigger, 'label': 'controller_machine_default',
                'cost_request': pending.get('request') or (cause.evidence or {}).get('authority'),
                'reservation_key': budget.key(parent['id'], attempt, budget.PILOT_RUNG)})
        scope = store.path('step-scopes', budget.pilot_id(parent['id']), str(attempt))
        child = {**deepcopy(ctx), 'pilot': {'trigger': trigger, 'step_id': parent['id']}}
        _detached(lambda: graph_substrate.run(scope, GRAPH_ID, {'run_id': store.run_id},
                                              input={'step': deepcopy(parent), 'context': child}))
        outcome = next((r for r in reversed(records(store, custody_.OUTCOME))
                        if r.get('step_id') == derived['id'] and r.get('attempt') == attempt
                        and r.get('seat') == budget.PILOT_RUNG), None) or {}
        calibrated = _calibration_id(store, parent)
        status = outcome.get('status') or 'held'
        if status == 'completed' and calibrated is None:
            status = 'failed'
        recorded = store.append(budget.PILOT_LAUNCH, {
            'schema_version': 1, 'phase': 'finished', 'step_id': parent['id'], 'attempt': attempt,
            'pilot_step_id': derived['id'], 'status': status, 'reason': outcome.get('reason'),
            'outcome': outcome.get('_record_id'), 'calibration': calibrated if status == 'completed' else None,
            'reservation_key': budget.key(parent['id'], attempt, budget.PILOT_RUNG)})
        if status != 'completed':
            raise StepHold('pilot_failed', f"the pilot rung ended {status} ({outcome.get('reason')}); no calibration "
                           'admits the full rung', evidence={'pilot': recorded})
    return reserve(state)


def reserve_point(state):
    """Pause only on a real pending cost request. A resume is exclusively a fresh poll."""
    import math
    from langgraph.types import interrupt as pause
    from ravel.workflow import graph_registry
    polls = 0
    while True:
        try:
            return reserve(state)
        except StepHold as exc:
            trigger = _pilot_trigger(state, exc)
            if trigger is not None:
                return _pilot_then_reserve(state, exc, trigger)
            pending = (exc.evidence or {}).get('pending')
            if (exc.reason != 'awaiting_authority' or type(pending) is not dict
                    or pending.get('kind') != 'r3_action' or type(pending.get('request')) is not str
                    or not pending['request'] or type(pending.get('since_ns')) is not int or pending['since_ns'] <= 0
                    or any(type(pending.get(key)) not in (int, float) or not math.isfinite(pending[key])
                           or pending[key] < 0 for key in ('waited_seconds', 'wait_bound_seconds'))):
                raise
            waited = max(pending['waited_seconds'], (time.time_ns() - pending['since_ns']) / 1e9)
            if polls >= 64 or (_ctx(state).get('unattended') and waited >= pending['wait_bound_seconds']):
                raise
            store = _store(state)
            pause({'kind': 'controller_authority', 'schema_id': 'controller_authority', 'graph_id': GRAPH_ID,
                   'node': 'reserve', 'authority_kind': 'r3_action', 'pending': deepcopy(pending),
                   'approval_from_resume': False, 'operator_answer': {
                       'command': f"ravel operator answer --run {store.run_id} --request {pending['request']} "
                                  '--code <code> --decision admit',
                       'terminal_identity_attested': False}},
                  response_schema=graph_registry.response_schema('controller_authority'))
            polls += 1


def cost_authority(state):
    """Recheck protected reservation, current cost authority and ceilings before a packet."""
    store, ctx = _store(state), _ctx(state)
    errors, pins = [], {}
    try:
        _running(store)
        parent, acting = state['step'], state['acting']
        pins = {'plan_sha256': ctx.get('plan_sha256') or None, 'step_sha256': spec.step_sha256(acting)}
        reservation = state['reservation']
        body = store.read(budget.RESERVATION, reservation['record_id'])['record']
        expected = {'key': budget.key(parent['id'], _attempt(state), _seat_key(state)),
                    'step_id': parent['id'], 'attempt': _attempt(state), 'seat': _seat_key(state),
                    'amounts': reservation['amounts']}
        if (reservation.get('key') != expected['key']
                or any(body.get(key) != value for key, value in expected.items())):
            raise StepHold('reservation_changed', 'the protected cost reservation differs from the current attempt')
        basis = body.get('basis') or {}
        if any(basis.get(key) != value for key, value in pins.items()):
            raise StepHold('reservation_changed', 'the protected reservation binds different step or plan bytes')
        if pins['plan_sha256'] is not None:
            approved, plan_sha, _ = operations.plan_step(store, parent, ctx)
            if _pilot(state):
                approved, _ = budget.pilot_step(approved)
            if (approved is None or plan_sha != pins['plan_sha256']
                    or spec.step_sha256(approved) != pins['step_sha256']):
                raise StepHold('plan_step_changed', 'cost reservation must cover the current protected step')
        elif (spec.step_sha256(parent) != pins['step_sha256']
              or acting['kind'] not in (*spec.WORKER_KINDS, *spec.PARENT_KINDS)
              or acting.get('operation') or spec.launch(acting) or acting.get('rung') in budget.TOP_RUNGS):
            raise StepHold('plan_step_missing', 'only ordinary nongenerating orchestration can precede a bound plan')
        signoff_id = basis.get('signoff')
        signoff = _verified_cost_signoff(store, signoff_id, pins) if signoff_id is not None else None
        if basis.get('compute_policy') is not None:
            from ravel.controller.engagement import compute
            if signoff_id is not None:
                raise StepHold('compute_policy_changed', 'one current source supplies the cost admission')
            signoff = compute.verify(store, reservation['record_id'], pins, ctx)
        ceilings = budget.envelope(store, ctx)
        upper_bound = _cost_bound(acting, body['amounts'], ceilings, state['branch'])
        if basis.get('upper_bound') != upper_bound:
            raise StepHold('cost_bound_changed', 'the protected upper estimate no longer matches its enforcement')
        problems = budget.rung_errors(acting) + budget.calibration_errors(
            store, acting, signoff=signoff, upper_bound=upper_bound, amounts=body['amounts'])
        if problems:
            raise StepHold(problems[0]['code'], 'the current cost forecast is not admitted', evidence={'errors': problems})
        totals = budget.totals(store, ceilings)
        for dimension, ceiling in ceilings.items():
            if ceiling is not None and (totals[dimension]['charged'] > ceiling
                    or (reservation['amounts'][dimension] is None
                        and (dimension not in budget.MEASURED_AFTER or totals[dimension]['charged'] >= ceiling))):
                raise StepHold('budget_exhausted', 'the current operator ceiling no longer covers ' + dimension)
    except StepHold as exc:
        errors = [{'code': exc.reason, 'message': exc.would_make_possible or exc.reason}]
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors = [{'code': 'cost_reservation_invalid', 'message': str(exc)[:1500]}]
    fact = _fact(state, 'cost-authority-gate', passed=not errors, errors=errors, pins=pins,
                 reservation=(state.get('reservation') or {}).get('record_id'))
    update = {'gates': {'cost_authority': {'errors': errors, 'record': fact['record'],
                                         'action_digest': digest(pins), 'sequence': time.time_ns()}}}
    if errors:
        update['status'] = {'phase': 'handler', 'terminal': 'hold', 'reason': errors[0]['code'],
                            'would_make_possible': errors[0]['message']}
    return update


# ---- packet ----------------------------------------------------------------------------------

def _packet_dir(state):
    return Path('inputs') / 'controller' / _node_id(state) / str(_attempt(state))


def _write_once(path, raw):
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise StepHold('packet_copy_changed', f'{path.name} already holds other bytes')
        return
    private_files.write(path, raw, exclusive=True)


def _consult_inputs(store, state):
    """Consult records of this step attempt, as packet inputs by digest."""
    rows = [r for r in records(store, CONSULT) if r.get('step_id') == state['step']['id']
            and r.get('attempt') == _attempt(state) and r.get('status') == 'completed']
    return [{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': 'consult-record'} for r in rows]


PACKET_INLINE = ('card', 'must_read')  # with every duty unit, inline in every packet whatever its engagement scope


def _packet_scope_row(manifest, built, step, commitment):
    """EG13 from the checked packet: its scope deferred only context units, and every duty unit, the effective card
    and its must-read knowledge are inline in it, whatever the step's engagement packet scope."""
    units = manifest.get('units') or []
    kept = {u['id'] for u in units if u.get('kind') == 'duty' or u.get('via') in PACKET_INLINE}
    deferred = list(built.get('deferred') or [])
    evidence = {'record': commitment, 'sha256': built['sha256'], 'mechanism': 'instructions.check_packet',
                'deferred': deferred, 'scope': (step.get('engagement') or {}).get('inline_context_tokens')}
    problems = ([f'kept_unit_deferred:{uid}' for uid in sorted(set(deferred) & kept)]
                + [f'unknown_unit_deferred:{uid}' for uid in sorted(set(deferred) - {u['id'] for u in units})]
                + [f'kept_unit_missing:{uid}' for uid in sorted(kept - set(built.get('units') or ()))])
    if problems:
        return {'status': 'violated', 'evidence': {**evidence, 'reason': ','.join(problems)[:1000]}}
    return {'status': 'satisfied', 'evidence': evidence}


def _packet_budget(state, card):
    """The seat's packet budget from the run's frozen agent preferences and the model catalogue windows."""
    from ravel.controller.instructions import budget as packet_budget
    try:
        return packet_budget.seat_budget(card, _ctx(state).get('agent_preferences'))
    except packet_budget.BudgetUnavailable as exc:
        raise StepHold('packet_budget_unavailable', exc.remedy, evidence={'reason': str(exc)}) from None


def _budgeted(function, *args, budget):
    """Call an instruction provider with the packet budget when it takes one (a test provider may not)."""
    import inspect
    try:
        parameters = inspect.signature(function).parameters
        accepts = 'budget' in parameters or any(p.kind is p.VAR_KEYWORD for p in parameters.values())
    except (TypeError, ValueError):
        accepts = False
    return function(*args, budget=budget) if accepts else function(*args)


def _reference_raw(reference):
    from ravel.controller.instructions.delivery import reference_bytes
    raw = reference_bytes(reference)
    if hashlib.sha256(raw).hexdigest() != reference.get('sha256'):
        raise StepHold('packet_reference_changed', 'a packet reference must keep the digest its packet states')
    return raw


def _reference_inputs(packet_info, *, store, run_dir):
    """The packet's by-reference step values, re-read against the controller-held packet before dispatch."""
    committed = unwrap(store.read('instruction-packet', packet_info['commitment']))
    expected = []
    folder = Path(packet_info['path']).parent
    for reference in committed['packet'].get('references') or ():
        raw = _reference_raw(reference)
        relative = folder / reference['name']
        path = run_dir / relative
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise StepHold('packet_reference_changed', 'a packet reference file must match the protected packet')
        expected.append({'pin': {'path': relative.as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()},
                         'as': 'inputs/' + reference['name']})
    if (packet_info.get('references') or []) != expected:
        raise StepHold('packet_reference_changed', 'packet reference pins must match the protected packet')
    return expected


def packet(state):
    if state['branch'] != 'worker':
        return {'packet': {'kind': state['branch']},
                'evaluations': {'EG13': seat_closure.na(f"{state['branch']}_receives_no_instruction_packet",
                                                        record=state['reservation']['record_id'])}}
    store, run_dir, acting = _store(state), _run_dir(state), state['acting']
    card = _card(state, constrained=False)
    seat = _seat(state)
    ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
    errors, found, run_inputs = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    if errors:
        raise StepHold(errors[0]['code'], 'an input is not a verified accepted artifact', evidence={'errors': errors})
    inputs = ([{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': r.get('kind')} for r in found]
              + [{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': 'run-input'} for r in run_inputs]
              + ([] if seat else _consult_inputs(store, state)))
    instructions = module('instructions')
    budget = _packet_budget(state, card)
    try:
        manifest = instructions.manifest(acting, card)
        built = _budgeted(instructions.packet, manifest, card, acting, inputs, budget=budget)
    except ValueError as exc:
        if getattr(exc, 'code', None) == 'packet_budget_exceeded':
            raise StepHold('packet_budget_exceeded', getattr(exc, 'remedy', None),
                           evidence={'reasons': [str(r) for r in getattr(exc, 'reasons', [exc])], 'budget': budget}) from None
        raise StepHold('instruction_packet_refused', str(exc)[:1500]) from None
    problems = _budgeted(instructions.check_packet, built, manifest, card, acting, inputs, budget=budget)
    if problems:
        raise StepHold('instruction_packet_refused', '; '.join(map(str, problems[:5])),
                       evidence={'problems': [str(p) for p in problems]})
    raw = built['text'].encode('utf-8')
    # Content-addressed: a packet rebuilt after a consult (new inputs) is a new packet, never an overwrite.
    folder = _packet_dir(state) / hashlib.sha256(raw).hexdigest()[:16]
    _write_once(run_dir / folder / 'packet.md', raw)
    from ravel.workflow.capability_catalogue import encode as capability_encode, shards as capability_shards
    capability_raw = capability_encode(built['capability_context'])
    _write_once(run_dir / folder / 'capabilities.json', capability_raw)
    shard_pins = []
    for part in capability_shards(built['capability_context']):
        name = f"capabilities-{part['part']:03d}.json"
        part_raw = capability_encode(part)
        _write_once(run_dir / folder / name, part_raw)
        shard_pins.append({'pin': {'path': (folder / name).as_posix(),
                                   'sha256': hashlib.sha256(part_raw).hexdigest()}, 'as': 'inputs/' + name})
    _write_once(run_dir / folder / 'manifest.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
    reference_pins = []
    for reference in built.get('references') or ():
        reference_raw = _reference_raw(reference)
        _write_once(run_dir / folder / reference['name'], reference_raw)
        reference_pins.append({'pin': {'path': (folder / reference['name']).as_posix(),
                                       'sha256': hashlib.sha256(reference_raw).hexdigest()},
                               'as': 'inputs/' + reference['name']})
    key = digest({'step': acting['id'], 'attempt': _attempt(state), 'packet': built['sha256']})
    committed = [r for r in records(store, 'instruction-packet') if r.get('controller_key') == key]
    if committed:
        commitment = committed[0]['_record_id']
    else:
        commitment = store.append('instruction-packet', {
            'controller_key': key, 'step_id': acting['id'], 'attempt': _attempt(state), 'seat': _seat_key(state),
            'packet': built, 'manifest': manifest, 'card': card, 'step_spec': acting, 'inputs': inputs})
    file_sha = hashlib.sha256(raw).hexdigest()
    return {'packet': {'path': (folder / 'packet.md').as_posix(), 'file_sha256': file_sha, 'sha256': built['sha256'],
                       'manifest': manifest, 'schema': built['schema'], 'schema_id': built.get('schema_id'),
                       'schema_sha256': digest(built['schema']), 'deferred': list(built.get('deferred') or []),
                       'capability_context': {'path': (folder / 'capabilities.json').as_posix(),
                                              'sha256': hashlib.sha256(capability_raw).hexdigest(),
                                              'catalogue_sha256': built['capability_context']['catalogue_sha256'],
                                              'shards': shard_pins},
                       'commitment': commitment, 'inputs': inputs, 'references': reference_pins,
                       'budget': deepcopy(built.get('budget')),
                       'tokens': built.get('tokens', (len(raw) + 3) // 4)},
            'evaluations': {'EG13': _packet_scope_row(manifest, built, acting, commitment)}}


def _capability_inputs(packet_info, *, store, run_dir):
    """Bind the complete metadata attachment to its protected packet before dispatch."""
    from ravel.workflow.capability_catalogue import encode as capability_encode, for_seat, shards
    capability_pin = packet_info.get('capability_context')
    if not isinstance(capability_pin, dict):
        raise StepHold('capability_context_missing', 'every worker receives the current capability catalogue as data')
    committed = unwrap(store.read('instruction-packet', packet_info['commitment']))
    expected = committed['packet'].get('capability_context')
    if not isinstance(expected, dict):
        raise StepHold('capability_context_missing', 'the protected packet must retain its complete capability data')
    expected_raw = capability_encode(expected)
    expected_sha = hashlib.sha256(expected_raw).hexdigest()
    relative = Path(packet_info['path']).parent / 'capabilities.json'
    capability_path = run_dir / relative
    if (relative.is_absolute() or '..' in relative.parts or capability_pin.get('path') != relative.as_posix()
            or capability_pin.get('sha256') != expected_sha
            or capability_pin.get('catalogue_sha256') != expected['catalogue_sha256']
            or any(part.is_symlink() for part in (capability_path, *capability_path.parents))
            or not capability_path.is_file() or capability_path.read_bytes() != expected_raw):
        raise StepHold('capability_context_changed', 'capability data must match the controller-held instruction packet')
    if for_seat(expected['seat_kind']) != expected:
        raise StepHold('capability_context_stale', 'rebuild the packet from the current capability sources')
    expected_pins = []
    for part in shards(expected):
        name = f"capabilities-{part['part']:03d}.json"
        raw = capability_encode(part)
        part_relative = relative.parent / name
        path = run_dir / part_relative
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise StepHold('capability_context_changed', 'capability shard must match the protected instruction packet')
        expected_pins.append({'pin': {'path': part_relative.as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()},
                              'as': 'inputs/' + name})
    if capability_pin.get('shards') != expected_pins:
        raise StepHold('capability_context_changed', 'capability shard pins must match the protected instruction packet')
    return expected_pins


# ---- preflight -------------------------------------------------------------------------------

def _seat_roles(store, parent, card, ctx):
    """The review seats a step requires: its plan ``review`` list and its card's ``reviewed_by``."""
    from ravel.workflow import role_registry
    document = role_registry.registry_document()
    wanted = ([row['role'] for row in parent['seats'] if row.get('kind') == 'review']
              if 'seats' in parent else
              list(parent.get('review') or []) + list((card or {}).get('reviewed_by') or []))
    result = []
    for role in wanted:
        canonical = document['aliases'].get(role, role)
        if 'seats' in parent and canonical not in document['roles']:
            raise StepHold('review_seat_unregistered', f'the declared review seat {role} is not registered')
        if 'seats' in parent and canonical == (card or {}).get('id'):
            raise StepHold('review_seat_actor_conflict', 'a declared review seat cannot be its producer')
        if canonical in document['roles'] and canonical not in result and canonical != (card or {}).get('id'):
            result.append(canonical)
    if len(result) > MAX_SEATS:
        # A required seat is never dropped: the step holds before dispatch instead.
        raise StepHold('review_seats_exceed_limit', f'the step requires {len(result)} review seats; at most '
                       f'{MAX_SEATS} run per step, so split the review across steps', evidence={'roles': result})
    return result


def _copy_inputs(run_dir, folder, rows, *, role=None, write=True, store=None):
    from .member_manifest import copy_lock
    with copy_lock(store if write else None):
        return _copy_inputs_locked(run_dir, folder, rows, role=role, write=write, store=store)


def _copy_inputs_locked(run_dir, folder, rows, *, role=None, write=True, store=None):
    """Screen the entire verified input batch, then copy in bounded chunks."""
    from ravel.workflow import review_projection
    from ..confine.inputs import hash_copy
    from .member_manifest import admit_copies, copy_checked, screen_json_keys
    pending = []
    pins = []
    aliases = {}
    for index, row in enumerate(rows):
        record = row.get('custody') or {}
        source = run_dir / (row['artifact'] if row['kind'] == 'run-input' else record['destination'])
        name = Path(row['artifact'].rsplit(':', 1)[-1]).name
        target = folder / 'artifacts' / f'{index:03d}' / name
        files = [(source, target, row['sha256'], row['artifact'].rsplit(':', 1)[-1],
                  f'inputs/artifacts/{index:03d}/{name}')]
        for member in custody.verified_attachments(record, run_dir):
            files.append((run_dir / member['destination'], target.parent / member['blob'], member['sha256'],
                          member['path'], f"inputs/artifacts/{index:03d}/{member['blob']}"))
        for source, target, expected, logical, alias in files:
            if hash_copy(source)[0] != expected:
                raise StepHold('input_changed', f"{row['artifact']} changed after it was verified")
            if role is not None:
                _, removed = review_projection.screen_inputs(run_dir, role,
                    [logical, str(source.relative_to(run_dir)), target.as_posix()])
                fields = []
                card = review_projection._card(role)
                redact = {key for cls in card['sees'].get('forbidden_inputs', [])
                          for key in review_projection.CLASSES[cls][1]}
                if redact and Path(logical).suffix == '.json':
                    screened_sha, fields = screen_json_keys(source, redact)
                    if screened_sha != expected:
                        raise StepHold('input_changed', 'input changed during field screening')
                if removed or fields:
                    raise StepHold('forbidden_input', 'the seat forbids input paths or fields',
                                   evidence={'removed': removed, 'fields': fields})
            if alias in aliases:
                if aliases[alias] != (source, expected):
                    raise StepHold('input_alias_conflict', 'two declared inputs collide at one worker input path')
                continue
            aliases[alias] = (source, expected)
            pending.append((source, run_dir / target, expected))
            pins.append({'pin': {'path': target.as_posix(), 'sha256': expected}, 'as': alias})
    if write:
        admit_copies(run_dir, pending, store=store)
    created = []
    try:
        for source, target, expected in pending:
            if not write:
                continue
            if target.exists():
                if hash_copy(target)[0] != expected:
                    raise StepHold('input_changed', 'input copy destination already holds other bytes')
                continue
            private_files.mkdir(target.parent)
            actual, mode = copy_checked(source, target)
            created.append(target)
            target.chmod(mode & 0o600)
            if actual != expected:
                raise StepHold('input_changed', 'input changed while copied')
    except BaseException:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return pins


def _authorize(store, ctx, acting, amounts, *, stage=None):
    """The authority service's admission of this effect (rung within CHECK-IN 1, GO for full and scan)."""
    from ravel.controller.authority.operator import BUDGET_KEYS
    authority = module('authority')
    check = getattr(authority, 'authorize_effect', None)
    if check is None:
        raise StepHold('authority_effect_check_unavailable', 'the authority service admits each effect')
    # Same step-to-authority vocabulary as the plan compiler: retry limits are control
    # metadata, broker calls share the model-call resource, and all other resources retain names.
    dimensions = {key: key for key in BUDGET_KEYS}
    dimensions.update(broker_calls='model_calls', attempts=None)
    requested = {}
    for source in (acting.get('budget') or {}, amounts):
        mapped = {}
        for key, value in source.items():
            if key not in dimensions:
                raise StepHold('budget_dimension_unknown', f'the authority budget has no dimension {key!r}')
            dimension = dimensions[key]
            if dimension is not None and type(value) in (int, float):
                mapped[dimension] = mapped.get(dimension, 0) + value
        requested.update(mapped)
    stage = stage or (spec.launch(acting) or {}).get('stage') or acting.get('operation') or acting['kind']
    rung = acting.get('rung') or 'none'
    effect = {'id': acting['id'], 'rung': rung, 'plan': rung,
              'pins': {'plan_sha256': ctx.get('plan_sha256')}, 'go_pins': deepcopy(ctx.get('go_pins') or {}),
              'requires_go': ctx.get('requires_go', True), 'stage': stage,
              'budget': requested,
              'started_ns': time.time_ns()}
    try:
        authorized = check(store, effect)
        store.append('step-authority', {'step_id': acting['id'], 'attempt': ctx.get('attempt', 1),
            'point': ctx.get('point'), 'plan_sha256': ctx.get('plan_sha256'),
            'grid_sha256': (acting.get('parameters') or {}).get('grid_sha256'),
            'effect': deepcopy(effect), 'authority': deepcopy(authorized)})
        return authorized
    except Exception as exc:
        if type(exc).__name__ == 'AuthorityRefused':
            raise StepHold('authority_refused', str(exc)[:1500]) from None
        if isinstance(exc, ValueError):
            raise StepHold('authority_effect_invalid', str(exc)[:1500]) from None
        raise


def _confine_refusal(exc):
    """``(reason, evidence)`` for a refusal the confinement package raised before any effect, else None."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if not (getattr(exc, 'launch_refused', False) or names & {'ConfinementRefused', 'LaunchHeld', 'SandboxUnavailable'}):
        return None
    if 'LaunchHeld' in names:
        return 'confined_launch_held', {'reason': getattr(exc, 'reason', None), 'detail': getattr(exc, 'detail', None)}
    return 'confined_launch_refused', {'detail': str(exc)[:1500]}


def _probe(kind, target):
    """The confinement package's inventory probe (CT05): observed under the very confinement the
    start gets and compared with ``target['admitted']``; any difference holds before the start."""
    probe = getattr(module('confine'), 'probe', None)
    if not callable(probe):
        raise StepHold('inventory_probe_unavailable', 'the confinement package probes each start against its '
                       'admitted sets; the step does not start without it')
    try:
        found = probe(kind, deepcopy(target))
    except Exception as exc:  # the probe is fail-closed: an error is a hold, never a pass
        refusal = _confine_refusal(exc)
        if refusal is not None:
            raise StepHold(refusal[0], 'the launch cannot run confined here', evidence=refusal[1]) from None
        raise StepHold('inventory_probe_failed', f'{type(exc).__name__}: {str(exc)[:1500]}') from None
    if type(found) is not dict or found.get('equal') is not True:
        raise StepHold('inventory_probe_mismatch', 'the probed inventory differs from the admitted set',
                       evidence={'differences': deepcopy((found or {}).get('differences')) if type(found) is dict
                                 else None})
    return found


def _consult_done(store, step_id, attempt, trigger):
    return any(r.get('step_id') == step_id and r.get('attempt') == attempt and r.get('trigger') == trigger
               for r in records(store, CONSULT))


def _facts(store, step, ctx):
    """Controller facts for consult triggers: smoke history, failures and contested status of the step."""
    from .custody import outcomes
    done = outcomes(store)
    signature = operations.signatures().get(step.get('operation')) if step.get('operation') else None
    smoke = any(row.get('rung') == 'smoke' for row in records(store, custody.CUSTODY))
    failed = any(row.get('step_id') == step['id'] and row.get('status') == 'failed'
                 for row in records(store, custody.OUTCOME))
    contested = any(row.get('step_id') == step['id'] and row.get('credited') is False
                    for row in records(store, CREDIT))
    return {'operation_tools': list((signature or {}).get('tools') or ()), 'smoke_done': smoke,
            'prior_failure': failed or bool(ctx.get('prior_failure')), 'contested': contested or bool(ctx.get('contested')),
            'completed': sorted(k for k, v in done.items() if v.get('status') == 'completed')}


def _scientific_step(store, ctx, approved):
    """The scientific plan's own bytes of step ``approved`` under an applied engagement view. ``current_plan`` already
    authenticated both: the scientific blob by its digest, the view as the current decision's application of it."""
    found = [unwrap(row) for row in store.scan('plan')]
    found = [row for row in found if row.get('plan_sha256') == ctx.get('plan_sha256') and row.get('blob')]
    try:
        plan = json.loads(store.get_blob(found[-1]['blob']).decode('utf-8'))
    except (IndexError, KeyError, ValueError, OSError) as exc:
        raise StepHold('plan_unreadable', str(exc)[:500]) from None
    steps = [row for row in plan.get('steps') or () if type(row) is dict and row.get('id') == approved['id']]
    if len(steps) != 1:
        raise StepHold('plan_step_missing', f"step {approved['id']} is not in the scientific plan")
    return steps[0]


def tool_check(store, step_id, plan_sha):
    """The approved ``tool-selection`` record of this plan (its id), after re-checking every tool it bound to the
    step that was available when the plan was approved. A tool lost since then (uninstalled, its licence gone, its
    platform qualification withdrawn) ends the step in the typed hold ``tool_unavailable`` before any effect,
    with the need's other candidates as the alternatives runtime recovery can plan; nothing is substituted here.
    A tool whose availability cannot be observed now is not counted as lost."""
    rows = [row for row in store.scan('tool-selection') if (row.get('record') or {}).get('plan_sha256') == plan_sha]
    if not rows:
        return None
    selection = rows[-1]
    from ravel.setup import environment_profile as ep
    from ravel.workflow import tool_selection
    bound = [(need, c) for need, c in tool_selection.bound(selection['record'], step_id)
             if c.get('kind') == 'tool' and c.get('state') == 'available']
    if not bound:
        return selection['id']
    profile = store.latest('environment-profile')
    prefix = ((((profile or {}).get('record') or {}).get('tools')) or {}).get('prefix')
    try:
        now = {'tools': ep.PROBES['tools'](prefix=prefix, only=sorted({c['id'] for _, c in bound}))}
    except Exception as exc:  # an unrunnable re-check observes nothing; it never invents a loss
        now = {'tools': {'observed': False, 'reason': f'{type(exc).__name__}: {exc}'[:300], 'rows': {}}}
    lost = []
    for need, candidate in bound:
        found = ep.tool_status(now, candidate['id'])
        if found.get('available') is not True and found.get('reason') != 'unobserved':
            lost.append({'need': need, 'candidate': candidate['id'], 'title': candidate.get('title'),
                         'reason': found.get('reason'),
                         'alternatives': tool_selection.alternatives(selection['record'], need,
                                                                     exclude=[candidate['id']])})
    if lost:
        text = '; '.join(f"need {row['need']}: {row['title'] or row['candidate']} was available when the plan was "
                         f"approved and is now {row['reason']}; alternatives: "
                         + (', '.join(a['id'] for a in row['alternatives']) or 'none') for row in lost)
        raise StepHold('tool_unavailable', text[:1500], evidence={'lost': lost, 'selection': selection['id']})
    return selection['id']


def preflight(state):
    ctx, store, run_dir = _ctx(state), _store(state), _run_dir(state)
    parent, acting, seat, branch = state['step'], state['acting'], _seat(state), state['branch']
    attempt = _attempt(state)
    _running(store)
    approved, plan_sha, binding = operations.plan_step(store, parent, ctx)
    evaluations = {'T03': {'status': 'satisfied', 'evidence': {'sha256': plan_sha, 'binding': binding}},
                   'E01': {'status': 'satisfied', 'evidence': {'sha256': plan_sha}}}
    plan_identity = operations.current_plan(store, ctx)
    applied_identity = plan_identity.get('engagement') or {}
    if applied_identity:
        evaluations['T03']['evidence'].update(scientific_sha256=plan_sha,
            applied_sha256=applied_identity['applied_sha256'], decision_id=applied_identity['decision_id'])
    card = _card(state)
    if seat is not None:
        allowed = (_seat_roles(store, parent, _parent_card(state), ctx) if seat['purpose'] == 'review'
                   else [row['role'] for row in cards.consult_triggers(_parent_card(state), parent, _facts(store, parent, ctx))])
        if seat['role'] not in allowed:
            raise StepHold('seat_not_required', f"{seat['role']} is not a seat this step requires")
        if seat['purpose'] == 'review':
            # A review seat's parent is the step it reviews: its work of this attempt is adopted and checked first.
            record_id, report = _parent_checks(store, parent['id'], attempt)
            accepted = [{'artifact': r['artifact'], 'record': r.get('_record_id')}
                        for r in custody.custody_index(store).values()
                        if r.get('step_id') == parent['id'] and r.get('attempt') == attempt
                        and r.get('status') == 'accepted']
            if report is None or report.get('passed') is not True or not accepted:
                raise StepHold('parent_incomplete', f"the work of {parent['id']} this seat reviews is not adopted "
                               'and checked in this attempt', evidence={'validation': record_id})
            evaluations['SW39'] = {'status': 'satisfied', 'evidence': _fact(
                state, 'parent-adopted-and-checked', parent=parent['id'], attempt=attempt, validation=record_id,
                accepted=sorted(accepted, key=lambda r: r['artifact']))}
    else:
        if binding == 'plan_step':
            # The controller recorded the step's plan-bind rows when it bound the plan; they are verified here,
            # for the scientific bytes they bound (an applied view only adds its authenticated engagement fields).
            bound = _scientific_step(store, ctx, approved) if applied_identity else approved
            unbound = plan_binding.unverified(module('ledger'), store, bound)
            if unbound:
                raise StepHold('plan_bind_unverified', 'the plan-bind rows of this step do not show a met discharge '
                               'for its bound bytes', evidence={'rows': unbound[:20]})
        problems = custody.parent_errors(store, parent)
        if problems:
            raise StepHold('parent_incomplete', f"parent {problems[0]['parent']} has not completed",
                           evidence={'parents': problems})
        evaluations['SW39'] = {'status': 'satisfied', 'evidence': _fact(
            state, 'parents-completed', parents=list(parent['depends_on']),
            outcomes=[r for r in records(store, custody.OUTCOME) if r.get('step_id') in parent['depends_on']])}
        # Every review seat the step will require fits its fan-out before anything starts.
        _seat_roles(store, parent, card, ctx)
    if seat is None and any(row.get('plan_sha256') == plan_sha for row in records(store, 'tool-selection')):
        # E01: the step runs the tools its approved capability selection bound, and they are still there.
        evaluations['E01']['evidence']['tool_selection_record'] = tool_check(store, parent['id'], plan_sha)
    ancestors = list(parent['depends_on']) + list(ctx.get('ancestors') or ())
    errors, found, run_inputs = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    if errors:
        raise StepHold(errors[0]['code'], 'an input is not a verified accepted artifact', evidence={'errors': errors})
    input_evidence = _fact(state, 'input-custody-verified', inputs=found, run_inputs=run_inputs)
    evaluations.update({'T07': {'status': 'satisfied', 'evidence': input_evidence},
                        'C19': {'status': 'satisfied', 'evidence': input_evidence}})
    if acting.get('operation'):
        problems = operations.executor_errors(acting)
        if acting['kind'] in spec.OPERATION_KINDS:
            problems += operations.admission_errors(acting, inputs_custody=found, approved=approved,
                context={**ctx, 'store': store, 'run_dir': run_dir, 'plan': plan_identity})
        if problems:
            raise StepHold(problems[0]['code'], 'Operation admission: ' + str(
                problems[0].get('message') or problems[0]['code'])[:1500], evidence={'errors': problems})
        admitted = _fact(state, 'signature-and-executor-admitted', step=acting, plan_sha256=plan_sha)
        evaluations[f"TOOL-{acting['operation']}"] = {'status': 'satisfied', 'evidence': admitted}
        if acting['operation'] in operations.executors()['operations']:
            evaluations[f"EXEC-{acting['operation']}"] = {'status': 'satisfied', 'evidence': {**admitted, 'role': acting.get('role')}}
        evaluations['R13'] = {'status': 'satisfied', 'evidence': {**admitted, 'role': acting.get('role')}}
        implementation = (operations.signatures().get(acting['operation']) or {}).get('implementation') or {}
        if implementation.get('kind') == 'science-mode':
            # A science mode is admitted by the same signature and executor checks, never by its vocabulary.
            evaluations[f"MODE-{implementation.get('mode') or acting['operation']}"] = {
                'status': 'satisfied', 'evidence': {**admitted, 'operation': acting['operation'],
                                                    'role': acting.get('role')}}
    if seat is None:
        route_context = operations.route_context(store, {**ctx, 'run_dir': run_dir})
        problems = operations.route_errors(acting, route_context)
        if problems:
            raise StepHold(problems[0]['code'], 'the route contract is not admitted', evidence={'errors': problems})
    result = {'plan_sha256': plan_sha, 'binding': binding, 'inputs': [r['artifact'] for r in found],
              'run_inputs': run_inputs, 'subject_sha256': _subject(found + run_inputs)['sha256']}
    if 'instruction_entries' in state.get('packet', {}):
        result['instruction_entries'] = list(state['packet']['instruction_entries'])
    stage, seat_context, _, _ = _ledger_binding(state)
    entries = list(module('ledger').materialise(store, stage, seat_context))
    result['instruction_entries'] = list(dict.fromkeys([*result.get('instruction_entries', []), *entries]))
    if branch in ('launch', 'subgraph'):
        packet_info = state.get('packet') or {}
        reservation_id = (state.get('reservation') or {}).get('record_id')
        if (spec.branch(acting) != branch or packet_info.get('kind') != branch or 'manifest' in packet_info
                or type(reservation_id) is not str or not reservation_id):
            raise StepHold('native_instruction_packet_invalid',
                           'native packet absence needs the actual branch and reservation')
        _, absence = _native_instruction_absence(state, entries)
        evaluations.update(absence)
    if branch == 'worker':
        result.update(_worker_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations))
    elif branch == 'launch':
        result.update(_launch_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations))
    elif branch == 'subgraph':
        _authorize(store, ctx, acting, state['reservation']['amounts'])
        result.update({'graph': deepcopy(acting['graph'])})
    if seat is None and branch == 'launch':
        # Dry preparation precedes approval; every later operation verifies its approval commitment.
        if (acting.get('parameters') or {}).get('phase') != 'prepare':
            from ravel.controller.confine import commitments
            try:
                commitment = commitments.verify(store, plan_identity, approved, run_dir)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise StepHold('operation_input_commitment_refused', str(exc)[:1500]) from None
            evaluations['C18'] = {'status': 'satisfied', 'evidence': {'record': commitment}}
    if (spec.parameters(acting).get('evidence_requirements')
            and spec.parameters(acting).get('adapter') != 'ravel.controller.routes.study.runtime'):
        from ravel.controller.routes.study import runtime
        problems = runtime.scientific_checks(store, acting,
            {**ctx, 'run_dir': str(run_dir), 'attempt': attempt,
             'ledger_scope': _ledger_binding(state)[3]}, phase='dispatch')
        if problems:
            raise StepHold('scientific_evidence_unresolved', 'required dispatch evidence is unresolved',
                           evidence={'errors': problems})
    if branch == 'launch':
        # Every launch, the study adapter's included, carries its reserved budget and its
        # preflight fact: the native authority binds the effect to both.
        result['budget'] = deepcopy(state['reservation']['amounts'])
        preparation = {}
        from .launch_gate import preparation_implementation
        try:
            implementation = preparation_implementation(acting)
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise StepHold('native_preparation_refused', str(exc)) from None
        if implementation is not None:
            if type(result['budget'].get('events')) is not int or result['budget']['events'] != 0:
                raise StepHold('native_preparation_refused', 'source preparation requires a zero-event reservation')
            preparation['preparation_implementation'] = implementation
        fact = _fact(state, 'native-launch-preflight', plan_sha256=plan_sha,
                     step_sha256=spec.step_sha256(acting), launch_sha256=result['launch_sha256'],
                     passed=True, budget=result['budget'], stage=result.get('stage'),
                     correction=deepcopy(ctx.get('correction')),
                     depends_on=list(acting.get('depends_on') or ()),
                     log=str(Path(result['output_root']).parent / 'logs' / 'stdout'),
                     capsule={key: deepcopy(result['capsule'].get(key)) for key in ('argv', 'reads', 'writes', 'cwd')},
                     **preparation)
        result['native_preflight'] = fact['record']
    return {'preflight': result, 'evaluations': evaluations}


def _native_instruction_absence(state, entries=None):
    # Preflight checks actual native identity; this helper retains its scoped replay interface.
    ledger = module('ledger')
    if entries is None:
        stage, context, _, _ = _ledger_binding(state)
        entries = list(ledger.materialise(_store(state), stage, context))
    fact = _fact(state, 'native-instruction-packet-absence', branch=state['branch'],
                 packet_kind=(state.get('packet') or {}).get('kind'),
                 step_sha256=spec.step_sha256(state['acting']),
                 reservation=state['reservation']['record_id'])
    evaluations = native_rows.packet_rows(state['branch'], entries, fact['record'])
    current = {row['entry']: row for row in ledger.current(_store(state))}
    for entry in entries:
        row = str(entry).split('@', 1)[0]
        if row in evaluations:
            value = evaluations[row]
            previous = current.get(entry) or {}
            if previous.get('status', 'pending') == 'pending':
                ledger.record(_store(state), entry, value['status'], value['evidence'])
            elif (previous.get('status') == value['status']
                  and (previous.get('evidence') or {}).get('reason') == value['evidence']['reason']
                  and (previous.get('evidence') or {}).get('record')):
                # Replayed preflight reuses the original scoped absence record.
                value['evidence'] = deepcopy(previous['evidence'])
            else:
                raise StepHold('native_packet_absence_conflict', 'the scoped packet obligation has a different disposition')
            value['instruction_recorded'] = True
    return entries, evaluations


def _parent_card(state):
    """The producer step's card (for a seat: the card of the step the seat belongs to)."""
    parent = state['step']
    if not parent.get('role'):
        return None
    pinned = (state.get('card') or {}).get('registry_sha256')
    card, _, _ = cards.resolve(parent['role'], {'registry_sha256': pinned})
    return card


def _ml_observations(state):
    """Project every authenticated ML check for the bound specification, including failures."""
    from ravel.workflow import broker, review_projection_checks as rpc
    acting = state.get('acting') or {}
    parent = state.get('step') or {}
    store = _store(state)
    role = (acting.get('role') or {}).get('id') if type(acting.get('role')) is dict else acting.get('role')
    bindings = {}
    sources = [source for owner in (acting, parent) for source in
               ((owner.get('parameters') or {}).get('check_inputs') or {}, owner.get('check_inputs') or {})]
    for source in sources:
        if type(source) is dict:
            for check_id, binding in source.items():
                if check_id in rpc.ML_RESULT_CHECKS:
                    bindings.setdefault(check_id, binding)
    spec_digests = {row.get('spec_sha256') for row in bindings.values() if type(row) is dict
                    and type(row.get('spec_sha256')) is str}
    references = {}
    for check_id, binding in bindings.items():
        record_id = binding.get('record_id') if type(binding) is dict else None
        references[record_id if type(record_id) is str else 'missing:' + check_id] = (check_id, binding)
    for envelope in store.scan(rpc.ML_OBSERVATION_KIND):
        if type(envelope) is not dict:
            continue
        if type(envelope.get('record')) is dict:
            row = envelope['record']
            record_id = envelope.get('id')
        else:
            row = envelope
            record_id = row.get('_record_id') or row.get('id') or row.get('record_id')
        if row.get('spec_sha256') not in spec_digests or type(record_id) is not str or not record_id:
            continue
        binding = {'record_id': record_id, 'spec_sha256': row.get('spec_sha256'),
                   'subject_sha256': row.get('subject_sha256')}
        references.setdefault(record_id, (row.get('check_id'), binding))
    observations = []
    seen = set()
    for record_id, (check_id, binding) in references.items():
        if type(check_id) is not str or check_id not in rpc.ML_RESULT_CHECKS:
            continue
        if type(record_id) is str and record_id in seen:
            continue
        value = rpc.observed_ml_result(store, binding, check_id=check_id)
        resolved_id = (binding or {}).get('record_id') if type(binding) is dict else None
        if type(resolved_id) is str:
            seen.add(resolved_id)
        observations.append({'check_id': value['check_id'], 'status': value['status'],
                             'diagnostics': deepcopy(value.get('diagnostics') or {}),
                             'result_sha256': broker.digest(value), 'binding': deepcopy(binding)})
    if not observations and role == 'ml-reviewer':
        observations.append({'check_id': None, 'status': 'inconclusive',
                             'diagnostics': {'reason': 'no bound ML computation observations'},
                             'result_sha256': None, 'binding': None})
    return observations


def _worker_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations):
    from ravel.workflow import agent_worker, broker_mcp, transport_registry as tr
    from ravel.workflow.transports import cli_worker
    observations = _ml_observations(state)
    seat = _seat(state)
    attempt = _attempt(state)
    problems = cards.ownership_errors(card, acting, found)
    if problems:
        raise StepHold(problems[0]['code'], 'the step binds a quantity its role does not own or consume',
                       evidence={'errors': problems})
    ownership = _fact(state, 'ownership-checked', card_sha256=state['card']['sha256'], step=acting, inputs=found)
    evaluations['CF07'] = {'status': 'satisfied', 'evidence': {**ownership, 'owns': card['ownership']['owns']}}
    evaluations[f"ROLE-{card['id']}-ownership"] = {'status': 'satisfied', 'evidence': {**ownership, 'owns': card['ownership']['owns']}}
    prefs, kept, dropped = seats.preferences(ctx, card)
    # Without an OS worker sandbox a review seat holds, unless the operator configured the restricted unsandboxed
    # reviewer fallback; it is then selected and recorded as such (``_review_sandbox``), never as human review.
    fallback = _review_fallback(store, seat, acting)
    selection = seats.select(card, prefs, store=store, **({'sandbox_fallback': True} if fallback else {}))
    from ravel.controller.instructions import budget as packet_budget
    window_problem = packet_budget.selected_problem(selection, state['packet'].get('tokens') or 0)
    if window_problem is not None:
        raise StepHold('packet_budget_exceeded', window_problem,
                       evidence={'selection': deepcopy(selection), 'budget': deepcopy(state['packet'].get('budget'))})
    document = tr.load(selection['transport_id'])
    _provider_admission(run_dir, document)
    blind = card['id'] in agent_worker.blind_roles()
    card_blind = not blind and (card.get('requires') or {}).get('blind') is True
    belt = cli_worker.toolbelt_for(card, document, blind,
                                   blind_actions=agent_worker.blind_actions(card) if card_blind else None)
    problems = cards.exec_errors(card, belt)
    if problems:
        raise StepHold('exec_tool_present', 'a controller worker never receives an exec tool')
    for row in ('I03', 'I04', 'T01', 'T02', 'T09', 'CF11', f"ROLE-{card['id']}-dispatch", f"ROLE-{card['id']}-requires",
                f"ROLE-{card['id']}-tools", f"ROLE-{card['id']}-model"):
        evaluations[row] = {'status': 'satisfied', 'evidence': {'sha256': belt['manifest_sha256'], 'transport': selection['transport_id'],
                                                               'dropped': dropped, 'toolbelt': belt['manifest_sha256']}}
    for index, operation in enumerate(card.get('operations') or ()):
        evaluations[f"ROLE-{card['id']}-operations-{index}"] = {
            'status': 'satisfied', 'evidence': {'operation': operation, 'sha256': belt['manifest_sha256']}}
    budgets, applied = cards.worker_budgets(card, acting)
    evaluations['CF02'] = evaluations[f"ROLE-{card['id']}-stop"] = {'status': 'satisfied', 'evidence': {**_fact(state, 'worker-stop-bounds-applied', budgets=budgets, applied=applied), **applied}}
    outputs = cards.declared_outputs(card, acting)
    packet_info = state['packet']
    folder = Path(packet_info['path']).parent
    rows = ([{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': r.get('kind'), 'custody': r} for r in found]
            + [{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': 'run-input'} for r in run_inputs]
            + [{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': 'run-input'}
               for r in (packet_info.get('inputs') or ()) if r.get('kind') == 'consult-record'])
    input_ids = [row['artifact'] for row in rows]
    pins = [{'pin': {'path': packet_info['path'], 'sha256': packet_info['file_sha256']},
             'as': 'inputs/' + cli_worker.CONTROLLER_PACKET}]
    capability_inputs = _capability_inputs(packet_info, store=store, run_dir=run_dir)
    if not _projected(card):
        pins += capability_inputs
    # The packet's own step values by reference reach every seat: they are the controller's step contract.
    pins += _reference_inputs(packet_info, store=store, run_dir=run_dir)
    review = None
    if seat is not None and seat['purpose'] == 'review':
        review = {'point_id': f"controller:{state['step']['id']}:{seat['role']}:{seat['n']}",
                  'scope': f"controller-step:{state['step']['id']}", 'subject_sha256': seat['subject']['sha256']}
    review_packet = None
    if _projected(card):
        # The restricted blind-capable worker (P13): a card that is not a producer sees only RAVEL's
        # code-computed projection of the step's inputs under its ``sees``; no raw copy reaches its
        # workspace beside the controller's own instruction packet. Every input's bytes are re-checked first.
        _copy_inputs(run_dir, folder, rows, write=False)
        review_packet, subject_sha256, point_id = _projection(state, run_dir, acting, card, rows, input_ids, review,
                                                              findings=observations)
        if review is None and acting.get('kind') == 'review':
            review = {'point_id': point_id, 'scope': f"controller-step:{state['step']['id']}",
                      'subject_sha256': subject_sha256}
    else:
        # Raw copies pass the card's own input-path and field screen; a research role packet already projects
        # its node, so only its redundant input snapshot is left out.
        pins += _copy_inputs(run_dir, folder, _research_copy_rows(acting, rows), role=card, store=store)
    evaluations[f"ROLE-{card['id']}-sees"] = {'status': 'satisfied', 'evidence': _fact(
        state, 'worker-input-screened', card_sha256=state['card']['sha256'],
        profile=card['sees'], inputs=rows, projection=review_packet)}
    worker = seats.worker_spec(node_id=_node_id(state), attempt=attempt, card=card,
                               card_sha256=state['card']['sha256'], transports=kept, inputs=pins,
                               outputs=cards.worker_outputs(outputs), budgets=budgets,
                               map_id='controller:' + state['step']['id'], review=review)
    agent_worker._validate(worker)
    pending = []
    fired = cards.consult_triggers(card, acting, _facts(store, acting, ctx)) if seat is None else None
    for trigger in fired or ():
        if not _consult_done(store, acting['id'], attempt, trigger['when'] + ':' + trigger['role']):
            pending.append(trigger)
    if fired == [] or not ((card.get('knowledge') or {}).get('consult')):
        evaluations.update(seat_closure.consult_rows(card, [], _fact(
            state, 'consult-triggers-evaluated', triggers=fired, declared=(card.get('knowledge') or {}).get('consult'))))
    fallback = _review_sandbox(store, seat, acting, **({'selection': selection} if fallback else {}))
    _authorize(store, ctx, acting, state['reservation']['amounts'])
    # The admitted tool set: the toolbelt entries the broker serves (``submit_final`` is the CLI's structured
    # output, never a broker tool); the dispatcher probes the materialized worker against it before the start.
    admitted = {'manifest_sha256': belt['manifest_sha256'],
                'tools': sorted(t['name'] for t in broker_mcp.served(belt['tools']))}
    key = digest({'node': worker['node_id'], 'attempt': attempt})
    # The dispatch record is written when the worker is about to start, after every required consult.
    existing = next((r for r in records(store, DISPATCH) if r.get('key') == key), None)
    dispatch_id = (existing or {}).get('_record_id')
    if not pending and existing is None:
        dispatch_id = store.append(DISPATCH, {'schema_version': 1, 'key': key, 'step_id': acting['id'],
                                'parent_step': state['step']['id'], 'seat': _seat_key(state),
                                'node_id': worker['node_id'], 'attempt': attempt, 'spec_sha256': digest(worker),
                                'selection': deepcopy(selection), 'dropped': dropped, 'card_sha256': state['card']['sha256'],
                                'packet_sha256': packet_info['sha256'], 'packet_tokens': packet_info['tokens'],
                                'purpose': (seat or {}).get('purpose', 'review' if acting['kind'] == 'review' else 'producer'),
                                'budgets': applied,
                                'toolbelt_manifest_sha256': belt['manifest_sha256'], 'admitted_tools': admitted['tools'],
                                'instruction_document_sha256': _instruction_sha256(run_dir)})
    qualification = _qualification_record(store, selection)
    if dispatch_id is not None:
        evaluations.update(seat_closure.selection_rows(selection, dispatch_id, qualification))
    return {'spec': worker, 'spec_sha256': digest(worker), 'selection': selection, 'outputs': outputs,
            'applied': applied, 'consults_pending': pending, 'dispatch_key': key, 'toolbelt': admitted,
            'ml_observations': observations, 'review_packet': review_packet, 'inputs': input_ids,
            'qualification_record': qualification, 'review_sandbox_fallback': fallback}


def _provider_admission(run_dir, document):
    """The run's provider policy (frozen at intake, project floors included) admits the selected transport before
    anything starts; a non-admitted family is refused typed and nothing is dispatched (N4)."""
    from ravel.workflow import provider_policy
    try:
        provider_policy.admission(run_dir, document, provider_policy.account_class(document))
    except provider_policy.PolicyRefused as exc:
        raise StepHold('provider_policy_refused', str(exc)[:1500],
                       evidence={'transport': document.get('id'), 'not_dispatched': True}) from None


REVIEW_FALLBACK = 'review-sandbox-fallback'
REVIEW_FALLBACK_LABEL = 'REVIEW WITHOUT OS SANDBOX (OPERATOR-CONFIGURED FALLBACK)'


def _review_fallback(store, seat, acting):
    """The operator's restricted unsandboxed reviewer fallback for this seat, or None.

    It applies only to a review seat, only when the host has no OS worker sandbox, and only when the run's frozen
    mode carries ``review_sandbox_fallback: restricted-unsandboxed`` (the operator's own configuration at intake,
    narrowing-only for children). The reviewer is still the restricted CLI worker: no built-in tools, the broker's
    read-only toolbelt only, its live qualification required. What the OS sandbox would add (filesystem and network
    confinement, OS-enforced blindness) is absent and recorded as absent."""
    from ravel.workflow import sandbox
    if sandbox.available() is not None:
        return None
    if not ((seat or {}).get('purpose') == 'review' or acting.get('kind') == 'review'):
        return None
    try:
        from ravel.controller.authority import mode as mode_mod
        mode = mode_mod.frozen(store, required=False) or {}
    except Exception:  # without an authenticated frozen mode there is no operator fallback
        return None
    if mode.get('review_sandbox_fallback') != 'restricted-unsandboxed':
        return None
    return {'kind': 'restricted-unsandboxed', 'label': REVIEW_FALLBACK_LABEL, 'mode_record': mode.get('id'),
            'operator_entry': deepcopy(mode.get('operator_entry')), 'reason': 'no OS worker sandbox on this host',
            'isolation': 'cli-policy', 'tools': 'broker-readonly',
            'not_enforced': ['filesystem confinement', 'network confinement', 'OS-enforced blindness'],
            'review_credit': 'machine review, qualified; never human review'}


def _review_sandbox(store, seat, acting, *, selection=None):
    """A worker seat runs only inside the OS worker sandbox. Without one, a review seat holds with the label the
    receipt carries (``INDEPENDENT REVIEW INCOMPLETE``) and the operator's alternative is named: the driver never
    reviews its own work in its place (N5). The one exception is the operator-configured restricted unsandboxed
    reviewer (``_review_fallback``): the seat then proceeds, the fallback is recorded in the store
    (``review-sandbox-fallback``) and returned, and the sink labels the delivery and keeps it qualified.
    Returns the fallback record, or None inside the sandbox."""
    from ravel.workflow import sandbox
    if sandbox.available() is not None:
        return None
    review = (seat or {}).get('purpose') == 'review' or acting.get('kind') == 'review'
    fallback = _review_fallback(store, seat, acting)
    if fallback is not None:
        if (selection or {}).get('sandbox_fallback') is None:
            raise StepHold('review_fallback_unselected', 'the reviewer fallback applies only to a transport selected '
                           'under it', evidence={'fallback': fallback})
        record = {'schema_version': 1, **fallback, 'step_id': acting.get('id'),
                  'seat': (seat or {}).get('role'), 'transport': (selection or {}).get('transport_id'),
                  'relaxed': deepcopy((selection or {}).get('sandbox_fallback'))}
        return {**fallback, 'record': store.append(REVIEW_FALLBACK, record)}
    mode = {}
    try:
        from ravel.controller.authority import mode as mode_mod
        mode = mode_mod.frozen(store, required=False) or {}
    except Exception:  # the hold below stands without the mode's detail
        mode = {}
    raise StepHold('worker_sandbox_unavailable',
                   ('INDEPENDENT REVIEW INCOMPLETE: ' if review else '') + 'no OS worker sandbox on this host; '
                   'run the controller where bubblewrap or sandbox-exec is available' +
                   ('; or the operator sets `ravel operator set --review-sandbox-fallback restricted-unsandboxed` '
                    'for later runs (labelled, qualified delivery)' if review else ''),
                   evidence={'label': 'INDEPENDENT REVIEW INCOMPLETE' if review else None, 'review_seat': review,
                             'operator_allows_unconfined': mode.get('allow_unconfined') is True,
                             'unsandboxed_reviewers': ('operator fallback not configured' if review
                                                       else 'review seats only'),
                             'driver_self_review': 'never'})


def _instruction_sha256(run_dir):
    """The sha256 of the project instruction document this run pins for its workers, or None (N3)."""
    from ravel.controller.authority import autonomy
    return autonomy.current_instruction_sha256(run_dir)


def _qualification_record(store, selection):
    """The store id of the operator-run qualification record the selection counted (SW09), or None."""
    from ravel.workflow import transport_registry as tr
    for entry in store.scan(tr.QUALIFICATION_KIND):
        record = entry.get('record', entry) if type(entry) is dict else None
        if (type(record) is dict and record.get('transport_id') == selection.get('transport_id')
                and record.get('probe_sha256') == selection.get('probe_sha256')
                and record.get('status') == 'live_qualified'):
            return entry.get('id')
    return None


def _projected(card):
    """Whether the card works from a review projection rather than raw copies: every blind card and
    every card whose ``sees`` profile is not a producer's own workspace (P13)."""
    return (card.get('requires') or {}).get('blind') is True or card['sees']['profile'] != 'workspace'


def _step_scoped_contexts():
    """Controller context folders whose files belong to one step: they reach a worker only as its declared input."""
    from ravel.controller.judgment.graph import CONTEXT_DIR
    return (CONTEXT_DIR.rstrip('/') + '/',)


def _projection(state, run_dir, acting, card, rows, input_ids, review, *, findings=()):
    """``(packet binding, subject digest, review point)``: the card's projection of the step's verified inputs.

    The inputs are the projection's subjects; each projected subject must still have the bytes custody
    verified, and a subject the card's ``sees`` forbids refuses the step.
    """
    from ravel.workflow import review_projection
    parameters = acting.get('parameters') or {}
    subject_sha256 = ((review or {}).get('subject_sha256') or parameters.get('subject_plan_sha256')
                      or parameters.get('subject_sha256') or digest(sorted(input_ids)))
    point_id = (review or {}).get('point_id') or f"controller:{acting['id']}:{_attempt(state)}"
    sources = [row['artifact'] if row['kind'] == 'run-input' else row['custody']['destination'] for row in rows]
    try:
        packet = review_projection.project(run_dir, card, key=f"{acting['id']}:{_attempt(state)}",
                                           item={'role': card['id'], 'point_id': point_id,
                                                 'subject_sha256': subject_sha256, 'findings': list(findings)},
                                           subjects=sources, exclude_read_prefixes=_step_scoped_contexts())
        manifest, _ = review_projection.load(packet)
    except (review_projection.ProjectionRefused, OSError, ValueError) as exc:
        raise StepHold('projection_refused', f'the role projection cannot be built: {exc}'[:500],
                       evidence={'code': getattr(exc, 'code', type(exc).__name__)}) from None
    if manifest.get('capability_catalogue_sha256') != state['packet']['capability_context']['catalogue_sha256']:
        raise StepHold('capability_context_changed', 'the code-computed role packet must carry the same capability catalogue')
    projected = {row['source_path']: row['source_sha256'] for row in manifest.get('subjects') or ()}
    for source, row in zip(sources, rows):
        if projected.get(source) != row['sha256']:
            raise StepHold('input_changed', f"{row['artifact']} changed after it was verified")
    return packet, subject_sha256, point_id


def _launch_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations):
    if spec.parameters(acting).get('adapter') == 'ravel.controller.routes.study.runtime':
        from ravel.controller.routes.study import runtime
        return runtime.preflight(store, acting, {**ctx, 'run_dir': str(run_dir),
            'inputs_custody': deepcopy(found), 'run_inputs': deepcopy(run_inputs),
            'reservation': deepcopy(state['reservation']), 'attempt': _attempt(state),
            'ledger_scope': _ledger_binding(state)[3]})
    launch = deepcopy(spec.launch(acting))
    materialised = launch is None and acting['kind'] == 'operate'
    if materialised:
        if spec.parameters(acting).get('operation_task') is not None:
            from ravel.controller import operation_tasks
            materialize = operation_tasks.materialize_launch
        else:
            from ravel.controller.routes import analysis
            materialize = getattr(analysis, 'materialize_launch', None)
        if not callable(materialize):
            raise StepHold('launch_unmaterialised', 'the registered operation needs its route launch adapter')
        try:
            launch = materialize(deepcopy(acting), {**ctx, 'store': store, 'run_dir': run_dir})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            if isinstance(exc, StepHold):
                raise
            raise StepHold('launch_unmaterialised', str(exc)[:1500]) from None
        launch = deepcopy(launch)
    if type(launch) is not dict or type(launch.get('argv')) is not list or not launch['argv'] or not all(
            type(a) is str and a for a in launch['argv']):
        raise StepHold('launch_unmaterialised' if materialised else 'launch_unapproved',
                       'a confined launch needs a materialised argv bound to its approved step')
    # The acting rung's own declared event budget reaches an argv that takes its event count.
    launch['argv'] = budget.resolve_events(launch['argv'], acting)
    if card is not None:
        problems = cards.ownership_errors(card, acting, found)
        if problems:
            raise StepHold(problems[0]['code'], 'the launch sets a quantity its role does not own')
    if card is not None:
        screened = ([{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': r.get('kind'), 'custody': r}
                     for r in found] + [{'artifact': r['artifact'], 'sha256': r['sha256'], 'kind': 'run-input'}
                                       for r in run_inputs])
        _copy_inputs(run_dir, _packet_dir(state), screened, role=card, write=False)
        evaluations[f"ROLE-{card['id']}-sees"] = {'status': 'satisfied', 'evidence': _fact(
            state, 'native-input-screened', card_sha256=state['card']['sha256'],
            profile=card['sees'], inputs=[*found, *run_inputs])}
    attempt = _attempt(state)
    root = run_dir / 'steps' / acting['id'] / 'attempts' / str(attempt)
    outputs_dir = root / 'outputs'
    # Resolve a local launch copy against the step's verified census. The approved step and plan stay intact.
    launched_step = deepcopy(acting)
    launched_step.setdefault('parameters', {})['launch'] = deepcopy(launch)
    if materialised or spec.parameters(acting).get('route_adapter') == 'analysis':
        from ravel.controller.routes.analysis.execution import resolve_launch
        try:
            launch = resolve_launch(launched_step, ctx, output_root=outputs_dir, inputs=[*found, *run_inputs])
        except (ValueError, OSError) as exc:
            raise StepHold('launch_input_invalid', str(exc)[:1500]) from None
        launched_step['parameters']['launch'] = deepcopy(launch)
    launch_sha = operations.launch_digest(launched_step)
    scope = deepcopy(launch.get('scope') or {})
    # Committed inputs are read only and checked against their digests again at the start.
    committed = {**{str(run_dir / r['destination']): r['sha256'] for r in found},
                 **{str(run_dir / r['path']): r['sha256'] for r in run_inputs}}
    for record in found:
        for attachment in custody.verified_attachments(record, run_dir):
            committed[str(run_dir / attachment['destination'])] = attachment['sha256']
    reads = sorted(set(committed) | {str(run_dir / p) for p in launch.get('reads') or ()})
    from ..confine import resource_admission
    authority = module('authority')
    bounds_provider = getattr(authority, 'effective_bounds', None)
    resource_bounds = bounds_provider(store) if callable(bounds_provider) else {}
    retained_ceiling = (resource_bounds.get('budgets') or {}).get('retained_disk_bytes')
    acquisition = acting.get('kind') == 'acquire' and acting.get('operation') == 'acquire-published'
    try:
        limits = resource_admission.launch_limits(
            launch, operations.launch_wall_seconds(acting, state['reservation']['amounts']['wall_seconds']),
            retained_disk_bytes=None if acquisition else retained_ceiling)
    except (ValueError, OSError) as exc:
        raise StepHold(getattr(exc, 'reason', 'resource_limits_invalid'), str(exc)[:1500]) from None
    storage_admission = None
    if acquisition:
        try:
            storage_admission = resource_admission.admit_acquisition(
                store, acting, run_dir, input_paths=committed,
                plan_sha256=ctx.get('plan_sha256'), attempt=attempt, phase='preflight')
        except (ValueError, OSError) as exc:
            raise StepHold('acquisition_storage_refused', str(exc)[:1500]) from None
    # The confinement package's launch spec: the declared outputs directory is the only write root.
    capsule = {'argv': list(launch['argv']), 'env': dict(launch.get('env') or {}), 'reads': reads,
               'writes': [str(outputs_dir)], 'cwd': str(outputs_dir), 'run_dir': str(run_dir),
               'attempt_dir': str(root), 'limits': limits, 'backend': launch.get('backend') or 'auto',
               'input_digests': committed, 'controller': {'run_id': ctx.get('run_id'),
                                                          'launch_id': f"{acting['id']}:{attempt}"}}
    if scope:
        capsule['controller']['scope'] = scope
    authorized = _authorize(store, ctx, acting, state['reservation']['amounts'], stage=launch.get('stage'))
    try:
        source_proof = native_checks.source_admission(
            store, acting, run_dir, [*found, *run_inputs], attempt=attempt)
    except (ValueError, OSError) as exc:
        raise StepHold('source_admission_refused', str(exc)[:1500]) from None
    private_files.mkdir(outputs_dir)
    probed = _probe('launch', {**capsule, 'admitted': {'writable': [os.path.realpath(outputs_dir)],
                                                       'network': 'none'}})
    evaluations['CF11'] = {'status': 'satisfied', 'evidence': {'sha256': launch_sha}}
    evaluations['T06'] = {'status': 'satisfied', 'evidence': {'sha256': launch_sha}}
    return {'verified_inputs': deepcopy([*found, *run_inputs]), 'capsule': capsule, 'launch_sha256': launch_sha, 'scope': scope, 'stage': launch.get('stage'),
            'output_root': str(outputs_dir), 'source_admission': source_proof, 'storage_admission': storage_admission,
            'inventory': deepcopy(probed), 'authority': deepcopy(authorized) if type(authorized) is dict else None,
            'outputs': [{'path': spec.worker_path(r['path']), 'plan_path': r['path'], 'kind': r['kind'],
              'required': r.get('required', True)} for r in acting['outputs']]}


def after_preflight(state):
    if (state.get('preflight') or {}).get('consults_pending'):
        return 'consult'
    return {'worker': 'dispatch', 'launch': 'native_authority', 'subgraph': 'subgraph', 'parent': 'finish'}[state['branch']]


# ---- consult and review seats -----------------------------------------------------------------

def _subject(adopted):
    artifacts = sorted(({'artifact': r['artifact'], 'sha256': r['sha256'], 'attempt': r.get('attempt'),
                         'artifact_id': r.get('artifact_id')} for r in adopted),
                       key=lambda r: r['artifact'])
    return {'artifacts': artifacts, 'sha256': digest(artifacts)}


def consult_items(state):
    pending = (state.get('preflight') or {}).get('consults_pending') or []
    store = _store(state)
    ancestors = list(state['step']['depends_on'])
    _, found, _ = custody.input_errors(store, state['acting'], _run_dir(state), ancestors=ancestors)
    subject = _subject(found)
    return [{'key': f"consult:{row['role']}:{index + 1}", 'purpose': 'consult', 'role': row['role'], 'n': index + 1,
             'subject': subject, 'trigger': row['when'] + ':' + row['role'], 'items': []}
            for index, row in enumerate(pending)]


def consult_join(state):
    store, run_dir = _store(state), _run_dir(state)
    results = state.get('results') or {}
    pending = (state.get('preflight') or {}).get('consults_pending') or []
    written = []
    for index, row in enumerate(pending):
        key = f"consult:{row['role']}:{index + 1}"
        found = ((results.get(key) or {}).get('results') or {}).get('seat') or {}
        trigger = row['when'] + ':' + row['role']
        if found.get('status') != 'completed' or not found.get('record'):
            raise StepHold('consult_missing', f"the {row['role']} consult the card requires ({row['when']}) did not "
                           'complete; the step holds', evidence={'consult': found})
        target = _packet_dir(state) / 'consults' / f"{row['role']}.json"
        raw = (json.dumps(found['record'], indent=2, sort_keys=True) + '\n').encode()
        _write_once(run_dir / target, raw)
        record = {'schema_version': 1, 'step_id': state['step']['id'], 'attempt': _attempt(state), 'trigger': trigger,
                  'role': row['role'], 'status': 'completed', 'artifact': target.as_posix(),
                  'sha256': hashlib.sha256(raw).hexdigest(), 'receipt_sha256': found.get('receipt_sha256')}
        if not _consult_done(store, record['step_id'], record['attempt'], trigger):
            record['record_id'] = store.append(CONSULT, record)
        written.append(record)
    return {'consult': {'records': written},
            'evaluations': {'CF04': {'status': 'satisfied', 'evidence': _fact(state, 'consults-completed', consults=written)}}}


def review_items(state):
    if state.get('branch') != 'worker' and not (state.get('card')):
        return []
    validation = state.get('validation') or {}
    if validation.get('halts'):
        return []
    store = _store(state)
    card = _card(state)
    roles = _seat_roles(store, state['step'], card, _ctx(state))
    adopted = (state.get('checks') or {}).get('accepted') or []
    if not roles or not adopted:
        return []
    instructions = module('instructions')
    manifest = (state.get('packet') or {}).get('manifest') or {'units': []}
    items = []
    for index, role in enumerate(roles):
        reviewer, _, _ = cards.resolve(role, {'registry_sha256': state['card']['registry_sha256']})
        try:
            owed = instructions.reviewer_items(manifest, reviewer)
        except (KeyError, ValueError):
            owed = []
        declared = next((row for row in state['step'].get('engagement_seats') or [] if row['role'] == role), None)
        if declared is not None:
            owed = deepcopy(declared.get('items') or [])
        projection_state = dict(state)
        projection_state['acting'] = {**(state.get('acting') or {}), 'role': role}
        item = {'key': f'seat:{role}:1', 'purpose': 'review', 'role': role, 'n': 1,
                'declared': deepcopy(declared),
                'subject': _subject(adopted), 'items': deepcopy(owed),
                'findings': _ml_observations(projection_state),
                'producer': {'session_id': (state.get('observation') or {}).get('session_id'), 'role': card['id']}}
        withheld = _withheld_headlines(_run_dir(state), reviewer, adopted)
        if withheld:
            ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
            _, found, run_inputs = custody.input_errors(store, state['acting'], _run_dir(state), ancestors=ancestors)
            declared_verification = (state['acting'].get('parameters') or {}).get('verification')
            if type(declared_verification) is dict:
                # The approved step declares a verification: the blind card may not see the producer's result, so it
                # derives its own value from the step's governed inputs and method, and the controller compares the
                # two within the declared tolerance (``credit``).
                item.update(subject=_subject(found + run_inputs), mode=BLIND_VERIFICATION,
                            method=state['acting'].get('description'),
                            verification={k: v for k, v in declared_verification.items() if k in ('pointer', 'unit')})
            else:
                # No verification is declared, so no verification seat is assigned: the blind card keeps its declared
                # review and reviews what it may see (the step's governed inputs and its other outputs).
                visible = [r for r in adopted if r['destination'] not in withheld]
                item.update(subject=_subject(visible + found + run_inputs), method=state['acting'].get('description'))
        items.append(item)
    return items


def _withheld_headlines(run_dir, card, adopted):
    """The adopted outputs a blind reviewer (``review_projection.blind_card``) may not be shown as review subjects
    because they are producer headlines (its projection would refuse them). Empty for a card that is not blind,
    which is shown its subjects as they are and reviews them as before."""
    from ravel.workflow import review_projection
    if not adopted or not review_projection.blind_card(card) \
            or 'producer_headline' not in (card['sees'].get('forbidden_inputs') or ()):
        return set()
    _, removed = review_projection.screen_inputs(run_dir, card['id'], [r['destination'] for r in adopted])
    return {row['path'] for row in removed if row['class'] == 'producer_headline'}


def after_review(state):
    return 'fanout' if review_items(state) else 'credit'


# ---- dispatch, launch and subgraph ------------------------------------------------------------

def _research_packet(acting):
    """The research controller's role packet for this step (its original node packet or edge projection)."""
    parameters = acting.get('parameters') or {}
    return deepcopy(parameters.get('research_packet') or (parameters.get('research_node') or {}).get('packet'))


def _research_copy_rows(acting, rows):
    """Drop the research input snapshot from the raw copies only when the role packet already projects the node.

    That is a node with its own packet and no further inputs (and no different worker packet), or the RDJ edge
    reviewer whose sole original input is the public payload its worker packet projects. Any other row stays.
    """
    parameters = acting.get('parameters') or {}
    node = parameters.get('research_node') or {}
    inputs = node.get('inputs')
    original_packet = node.get('packet')
    edge = (node.get('role') == 'rdj_edge_reviewer' and original_packet is None
            and type(inputs) is list and len(inputs) == 1 and inputs[0].get('id') == 'rdj-payload'
            and inputs[0].get('sha256') == parameters.get('research_packet_subject_sha256')
            and parameters.get('research_packet') is not None)
    if not ((original_packet is not None and inputs == []
             and parameters.get('research_packet') in (None, original_packet)) or edge):
        return rows
    snapshot = 'inputs/research/' + acting['id'] + '.json'
    return [row for row in rows if not (row.get('kind') == 'run-input' and row.get('artifact') == snapshot)]


def _controller_facts(state):
    packet_info, preflight_info = state['packet'], state['preflight']
    parameters = state['acting'].get('parameters') or {}
    return {'schema': deepcopy(packet_info['schema']), 'schema_sha256': packet_info['schema_sha256'],
            'packet_sha256': packet_info['file_sha256'], 'manifest_sha256': packet_info['manifest'].get('sha256'),
            'selection': deepcopy(preflight_info['selection']), 'step_id': state['acting']['id'],
            'seat': _seat_key(state), 'toolbelt': deepcopy(preflight_info['toolbelt']),
            'run_id': _ctx(state)['run_id'],
            'admitted_inventory': deepcopy(_ctx(state).get('admitted_inventory')),
            'research_node': deepcopy(parameters.get('research_node')),
            'research_packet': _research_packet(state['acting']),
            'research_packet_subject_sha256': parameters.get('research_packet_subject_sha256'),
            **({'review_sandbox_fallback': deepcopy(preflight_info['review_sandbox_fallback'])}
               if preflight_info.get('review_sandbox_fallback') else {})}


def _worker_packet(state):
    """The role packet the worker receives: the research controller's packet, else the review projection."""
    research = _research_packet(state['acting'])
    return research if research is not None else state['preflight'].get('review_packet')


def _worker_summary(state, receipt):
    from ravel.workflow import broker
    return {'worker': {'status': receipt['status'], 'node_id': receipt['node_id'], 'attempt': receipt['attempt'],
                       'receipt_sha256': broker.digest(receipt)}}


def _dispatch_node():
    return nodes.agent('controller.step.worker', rundir=lambda s: _run_dir(s),
                       spec=lambda s: s['preflight']['spec'],
                       packet=_worker_packet,
                       segment=lambda s: {'worker': _node_id(s), 'attempt': _attempt(s)},
                       to_state=_worker_summary, controller=_controller_facts, failure_as_data=True)


def _inventory(root):
    rows = []
    base = Path(root)
    for path in sorted(base.rglob('*')) if base.is_dir() else ():
        if path.is_symlink() or not path.is_file():
            continue
        rows.append({'path': path.relative_to(base).as_posix(), 'sha256': custody._sha(path),
                     'bytes': path.stat().st_size})
    return rows


def _controller_dispatch(run_dir):
    """The workflow policy's controller dispatch context around a launch of this run, where the policy has one."""
    from contextlib import nullcontext
    from ravel.workflow import wms_policy
    enter = getattr(wms_policy, 'controller_dispatch', None)
    return enter(run_dir) if callable(enter) else nullcontext()


def _workflow_custody(state):
    from ravel.workflow import wms_policy
    try:
        wms_policy.require_custody(_run_dir(state))
    except ValueError as exc:
        raise LaunchNotStarted('workflow_custody_refused', str(exc)[:1500]) from None
    return _fact(state, 'wms_policy.require_custody')


class LaunchNotStarted(StepHold):
    """A hold inside the launch effect before anything started; the effect ledger records it as not dispatched."""
    not_dispatched = True


def _native_launch_decision(state):
    """Bind every native effect to its actual protected launch decision."""
    store, run_dir = _store(state), _run_dir(state)
    from . import launch_gate
    try:
        native_action = launch_gate.action(state['acting'],
            {**_ctx(state), 'attempt': _attempt(state), 'plan_sha256': state['preflight']['plan_sha256']},
            state['preflight'], state['preflight'].get('native_preflight'))
        problems = list(module('ledger').decide(store, run_dir, 'launch', native_action))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LaunchNotStarted('native_launch_gate_refused', str(exc)[:1500]) from None
    if problems:
        errors = [_plain(row) if isinstance(row, dict) else
                  {'code': getattr(row, 'code', type(row).__name__), 'message': str(row)} for row in problems]
        refused = _fact(state, 'native-launch-decision', passed=False, action=native_action,
                        plan_sha256=state['preflight']['plan_sha256'], errors=errors)
        raise LaunchNotStarted('native_launch_gate_refused', 'the actual launch decision has unresolved providers',
                               evidence={'record': refused['record'], 'errors': errors})
    decision = _fact(state, 'native-launch-decision', passed=True, action=native_action,
                     plan_sha256=state['preflight']['plan_sha256'])
    return decision


def _launch(state, identity):
    """One confined launch of the approved argv (``confine.popen``); its exit is data, not an exception."""
    import subprocess
    store = _store(state)
    try:
        _running(store)
        confine = module('confine')
        run_dir = _run_dir(state)
    except StepHold as exc:
        raise LaunchNotStarted(exc.reason, exc.would_make_possible, evidence=exc.evidence) from None
    if spec.parameters(state['acting']).get('adapter') == 'ravel.controller.routes.study.runtime':
        from ravel.controller.routes.study import runtime
        _authorize(store, _ctx(state), state['acting'], state['reservation']['amounts'],
                   stage=state['preflight'].get('stage'))
        return runtime.dispatch(store, state['acting'], {**_ctx(state), 'run_dir': str(run_dir),
            'attempt': _attempt(state), 'effect_identity': deepcopy(identity),
            'launch_capsule': deepcopy(state['preflight']['capsule']),
            'launch_preflight': deepcopy(state['preflight']),
            'ledger_scope': _ledger_binding(state)[3]})
    if (state['acting'].get('kind') == 'acquire'
            and state['acting'].get('operation') == 'acquire-published'):
        try:
            _authorize(store, _ctx(state), state['acting'], state['reservation']['amounts'],
                       stage=state['preflight'].get('stage'))
        except StepHold as exc:
            raise LaunchNotStarted(exc.reason, exc.would_make_possible, evidence=exc.evidence) from None
        decision = _native_launch_decision(state)
        from ravel.controller.routes.analysis.execution import launch_acquisition
        with _controller_dispatch(run_dir):
            custody_check = _workflow_custody(state)
            launched = launch_acquisition(store, state['acting'], {**_ctx(state), 'attempt': _attempt(state)},
                                         state['preflight'], inventory=_inventory)
        return {**launched, 'custody_check': custody_check, 'gate_check': decision}
    decision = _native_launch_decision(state)
    capsule = deepcopy(state['preflight']['capsule'])
    root = Path(state['preflight']['output_root'])
    private_files.mkdir(root)
    logs = root.parent / 'logs'
    private_files.mkdir(logs)
    from . import host_operations
    host_decision = host_operations.admit(store, state['acting'], _attempt(state), branch=state['branch'])
    journal = store.append(LAUNCH, {'schema_version': 1, 'phase': 'started', 'host_decision': host_decision, 'step_id': state['acting']['id'],
                                    'attempt': _attempt(state), 'launch_sha256': state['preflight']['launch_sha256'],
                                    'argv_sha256': digest(capsule['argv']), 'writes': capsule['writes'],
                                    'scope': deepcopy(state['preflight'].get('scope') or {}),
                                    'native_preflight': state['preflight'].get('native_preflight')})
    began = time.monotonic()
    timed_out = False
    with _controller_dispatch(run_dir), (logs / 'stdout').open('wb') as out, \
            (logs / 'stderr').open('wb') as err:
        try:
            _authorize(store, _ctx(state), state['acting'], state['reservation']['amounts'],
                       stage=state['preflight'].get('stage'))
            custody_check = _workflow_custody(state)
            process = confine.popen(capsule, stdout=out, stderr=err, stdin=subprocess.DEVNULL, cwd=capsule['cwd'])
        except StepHold as exc:
            store.append(LAUNCH, {'schema_version': 1, 'phase': 'refused', 'started': journal,
                                  'step_id': state['acting']['id'], 'attempt': _attempt(state),
                                  'reason': exc.reason, 'evidence': exc.evidence})
            raise LaunchNotStarted(exc.reason, exc.would_make_possible, evidence=exc.evidence) from None
        except Exception as exc:
            refusal = _confine_refusal(exc)
            if refusal is None:
                raise
            store.append(LAUNCH, {'schema_version': 1, 'phase': 'refused', 'started': journal,
                                  'step_id': state['acting']['id'], 'attempt': _attempt(state), 'reason': refusal[0],
                                  'evidence': refusal[1]})
            raise LaunchNotStarted(refusal[0], 'the launch cannot run confined here', evidence=refusal[1]) from None
        try:
            code = process.wait(timeout=capsule['limits']['wall_seconds'])
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            code = process.wait(timeout=30)
    wall = time.monotonic() - began
    # Adopt the declared outputs from the confinement, quarantine anything else and end survivors.
    finish_launch = getattr(confine, 'finish', None)
    confinement = _plain(finish_launch(process)) if callable(finish_launch) else None
    plan = _plain(getattr(getattr(process, 'ravel_confinement', None), 'record', None))
    inventory = _inventory(root)
    backend = getattr(process, 'ravel_backend', None) or (plan or {}).get('backend')
    # The confinement class the package recorded: an operator-allowed unconfined start carries its label.
    label = (plan or {}).get('label_text') if (plan or {}).get('kind') == 'unconfined' else None
    finished = store.append(LAUNCH, {'schema_version': 1, 'phase': 'finished', 'started': journal, 'step_id': state['acting']['id'],
                          'attempt': _attempt(state), 'exit_status': code, 'timed_out': timed_out,
                          'wall_seconds': wall, 'inventory': inventory, 'backend': backend,
                          'confinement': confinement, 'plan': plan, 'custody_check': custody_check})
    return {'journal_id': journal, 'finished_id': finished, 'plan': plan, 'confinement': confinement,
            'custody_check': custody_check, 'gate_check': decision,
            'exit_status': code, 'timed_out': timed_out, 'wall_seconds': wall,
            'inventory': inventory, 'output_root': str(root), 'launch_sha256': state['preflight']['launch_sha256'],
            'backend': backend, 'label': label, 'confinement_errors': list((confinement or {}).get('errors') or ()),
            'quarantined': list((confinement or {}).get('quarantined') or ())}


def _plain(value):
    """A JSON-safe copy of a record a peer package returned (None for anything that is not an object)."""
    if type(value) is not dict:
        return None
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _launch_node():
    return nodes.effect('controller.step.launch', kind='native', run=_launch,
                        segment=lambda s: {'launch': s['acting']['id'], 'attempt': _attempt(s)},
                        identity=lambda s: {'step': s['acting']['id'], 'attempt': _attempt(s),
                                            'launch_sha256': s['preflight']['launch_sha256']},
                        to_state=lambda s, r: {'launch': r})


def _subgraph_root(state, value=None):
    """Only this step's exact attempt directory may supply child output bytes."""
    run = _run_dir(state)
    expected = run / 'steps' / state['acting']['id'] / 'attempts' / str(_attempt(state)) / 'outputs'
    root = expected if value is None else Path(value)
    protected = Path(_store(state).path()).resolve()
    if (root != expected or not root.is_absolute() or not root.resolve().is_relative_to(run.resolve())
            or root.resolve().is_relative_to(protected) or protected.is_relative_to(root.resolve())
            or any(part.is_symlink() for part in (root, *root.parents))):
        raise StepHold('subgraph_output_root_invalid', 'child outputs belong to this step and attempt outside the store')
    return root


def _subgraph_outputs(state, root):
    outputs = []
    for row in state['acting']['outputs']:
        path = row['path']
        target = root / path
        if (not spec.SAFE_PATH.fullmatch(path) or not target.resolve().is_relative_to(root.resolve())
                or any(part.is_symlink() for part in (target, *target.parents))):
            raise StepHold('subgraph_output_path_invalid', 'declared child paths stay inside the attempt output root')
        outputs.append({'path': spec.worker_path(path), 'plan_path': path, 'kind': row['kind'],
                        'required': row.get('required', True)})
    return outputs


def _manuscript_services(state, root):
    from ravel.controller.routes.manuscript import staged
    ctx = {**_ctx(state), 'plan': operations.current_plan(_store(state), _ctx(state)),
           'run_dir': _run_dir(state), 'attempt': _attempt(state)}
    return staged.bind_step(_store(state), state['acting'], ctx, root)


def _study_services(state, root):
    from ravel.workflow import ml_executor
    ctx = {**_ctx(state), 'run_dir': str(_run_dir(state)), 'attempt': _attempt(state), 'output_root': str(root)}
    plan = operations.current_plan(_store(state), ctx)
    return ml_executor.bound(ml_executor.Binding(_store(state), _run_dir(state), plan, ctx))


def _runtime_child_context(state, graph_id, node_runner, *, budget_only=False):
    """Bind registered runtime adapters from their approved, source-pinned inputs."""
    if graph_id == 'intake.plan':
        if budget_only:
            return _run_dir(state), {}
        if not callable(node_runner):
            raise StepHold('intake_runner_unavailable', 'the bounded intake child requires its charged trusted runner')
        return _run_dir(state), {'node_runner': node_runner}
    if graph_id == 'consult.case':
        from ravel.workflow import consults
        try:
            consults.load_request(_run_dir(state), state['acting']['graph']['instance']['request'])
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise StepHold('consult_request_unbound', str(exc)) from None
        return _run_dir(state), {}
    if graph_id == 'review.points':
        if spec.parameters(state['acting']).get('ordinary_review') is not True:
            raise StepHold('ordinary_review_binding_missing', 'the review child requires an approved ordinary binding')
        plan = operations.current_plan(_store(state), _ctx(state))
        parents = set(state['acting'].get('depends_on') or ())
        operations_ = [step for step in plan.get('steps') or () if step.get('id') in parents
                       and spec.parameters(step).get('adapter') == 'ravel.controller.routes.study.runtime'
                       and isinstance(spec.parameters(step).get('ordinary'), dict)]
        if len(operations_) != 1:
            raise StepHold('ordinary_review_binding_missing', 'the review needs one declared prepared ordinary predecessor')
        from ravel.controller.routes.study import runtime
        _, child, _, _ = runtime._ordinary(operations_[0], _ctx(state))
        return child, {}
    return None


# Trusted process bindings only. ``research.loop`` enters through its owned route adapter
# (``_research_subgraph``), which runs the governed research controller over this step.
SUBGRAPH_BINDERS = {'manuscript.build': _manuscript_services, 'ml.study': _study_services}
RESEARCH_GRAPH = 'research.loop'
RESEARCH_OUTCOMES = ('completed', 'held', 'budget_exhausted', 'failed')


def _research_subgraph(state):
    """The research loop through the research route adapter's ``invoke`` (the governed research controller).

    The adapter's mechanical outcome decides only the step's branch: a completed outcome stages its pinned
    outputs through ordinary custody and checks (``custody.subgraph_adoption``); a held or exhausted one is a
    typed hold carrying the adapter's result as evidence. Nothing here accepts a scientific result.
    """
    from ravel.controller.routes import research as route
    graph = state['preflight']['graph']
    try:
        result = route.invoke(_store(state), state['acting'], _ctx(state))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise StepHold('research_request_unbound', f'the research adapter refused the step: {exc}'[:500],
                       evidence={'type': type(exc).__name__}) from None
    outcome = result.get('controller_outcome') if type(result) is dict else None
    if type(outcome) is not dict or outcome.get('status') not in RESEARCH_OUTCOMES:
        raise StepHold('research_outcome_unbound', 'the research adapter must expose its mechanical step outcome')
    status = outcome['status']
    if status in ('held', 'budget_exhausted'):
        raise StepHold('budget_exhausted' if status == 'budget_exhausted' else 'research_effect_required',
                       outcome.get('reason'), evidence={'research': result})
    child = {'outcome': 'ok' if status == 'completed' else 'error', 'status': status,
             'results_sha256': digest(result), 'outputs': deepcopy(outcome.get('outputs') or []),
             'graph_id': graph['id']}
    if result.get('labels'):
        child['labels'] = [{'label': label} for label in result['labels']]
    child['record_id'] = _store(state).append('step-subgraph', {'schema_version': 1,
        'step_id': state['acting']['id'], 'attempt': _attempt(state), **child})
    return {'child': child}


def _research_child(state):
    """Whether this step's child is the research adapter's (its outputs are pins, not an attempt inventory)."""
    return (state.get('child') or {}).get('graph_id') == RESEARCH_GRAPH


def subgraph(state, *, node_runner=None):
    """Invoke an allowlisted, service-bound child with protected checkpoint lineage."""
    from ravel.workflow import graph_registry, graph_substrate
    graph = state['preflight']['graph']
    if graph['id'] == RESEARCH_GRAPH:
        return _research_subgraph(state)
    meta = nodes._meta(state)
    binder = SUBGRAPH_BINDERS.get(graph['id']) if graph['id'] in spec.SUBGRAPHS else None
    bridge = (_runtime_child_context(state, graph['id'], node_runner)
              if graph['id'] in spec.SUBGRAPHS else None)
    if bridge is not None:
        from contextlib import nullcontext
        binder = lambda state, root: nullcontext()
    if not callable(binder):
        raise StepHold('subgraph_services_missing', 'the registered child requires its controller service binder')
    root = _subgraph_root(state)
    outputs = _subgraph_outputs(state, root)
    row = graph_registry.get(graph['id'])
    instance = deepcopy(graph.get('instance') or {})
    graph_registry.check_instance(row, instance)
    scope, extras = bridge if bridge is not None else (_run_dir(state), {})
    usage = None
    extras = dict(extras)
    if (row.get('resources') or {}).get('records_worker_items') is True:
        usage = subgraph_usage.Tracker(_store(state), state['acting'], _attempt(state), scope)
        extras.update(worker_usage_binding=usage.binding, record_worker_items=usage.record)
    ctx = graph_substrate.BuildContext(scope_root=scope, graph_id=graph['id'],
                                       version=row['version'], instance=instance, row=row, extras=extras)
    child_meta = {'graph_id': graph['id'], 'version': row['version'], 'instance': instance,
                  'scope_root': str(ctx.scope_root), 'path': nodes.invocation(meta, {'subgraph': graph['id']})}
    from langgraph.config import get_config
    try:
        config = dict(get_config())
    except RuntimeError:
        config = {}
    configurable = dict(config.get('configurable') or {})
    configurable.pop('checkpoint_id', None)
    if not configurable.get('thread_id'):
        configurable['thread_id'] = graph_substrate.thread_id(meta['graph_id'], meta.get('instance') or {})
    namespace = 'controller-child:' + digest({'path': child_meta['path'], 'attempt': _attempt(state)})
    configurable['checkpoint_ns'] = (configurable.get('checkpoint_ns') or '') + '|' + namespace
    config['configurable'] = configurable
    with binder(state, root):
        private_files.mkdir(root)
        completed = False
        try:
            compiled = graph_substrate.build(graph['id'], ctx, checkpointer=_store(state).checkpointer())
            final = compiled.invoke({'meta': child_meta}, config=config)
            completed = True
        finally:
            if usage is not None:
                usage.finish(completed=completed)
    status = (final or {}).get('status') or {}
    _subgraph_root(state, root)
    _subgraph_outputs(state, root)
    inventory = _inventory(root)
    child = {'outcome': nodes._outcome(final), 'status': deepcopy(status),
             'results': deepcopy((final or {}).get('results') or {}), 'output_root': str(root),
             'outputs': outputs, 'inventory': inventory,
             'checkpoint': {'thread_id': configurable['thread_id'], 'namespace': configurable['checkpoint_ns']}}
    child['results_sha256'] = digest(child['results'])
    child['record_id'] = _store(state).append('step-subgraph', {'schema_version': 1,
        'step_id': state['acting']['id'], 'attempt': _attempt(state), 'graph_id': graph['id'], **child})
    return {'child': child}


# ---- observe ---------------------------------------------------------------------------------

RAW_SPLIT = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')


def _meter(run_dir, receipt):
    """Credit a complete provider split only from a verified supervisor capture."""
    from ravel.workflow import agent_worker, broker
    from ravel.workflow.transports import provider_usage
    usage = deepcopy(receipt.get('usage') or {})
    usage.pop('raw', None)
    transport = receipt.get('transport') or {}
    pinned = (transport.get('observation') or {}).get('stdout_sha256')
    meter = {'split': 'transport_reports_no_split', 'stdout_sha256': pinned}
    if usage.get('reported') is not True:
        return usage, meter
    path = agent_worker.capture_path(broker.ordinary(run_dir), receipt['node_id'], receipt['attempt'], 'stdout')
    if not pinned or path.is_symlink() or not path.is_file() or broker.sha(path) != pinned:
        return usage, {**meter, 'split': 'capture_unverified'}
    decoded = provider_usage.decode(path.read_bytes(), transport.get('agent'))
    if decoded.get('status') != 'reported':
        return usage, {**meter, 'split': 'split_incomplete', 'reason': decoded.get('reason')}
    if decoded.get('session_id') != receipt.get('session_id'):
        return usage, {**meter, 'split': 'capture_unverified'}
    raw = decoded['usage']
    if (any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('input_tokens', 'output_tokens', 'turns'))
            or sum(raw[k] for k in RAW_SPLIT) != usage['input_tokens']
            or raw['output_tokens'] != usage['output_tokens'] or decoded['requests'] != usage['turns']):
        return usage, {**meter, 'split': 'split_inconsistent'}
    usage['raw'] = {k: raw[k] for k in RAW_SPLIT}
    return usage, {**meter, 'split': 'complete', 'split_basis': decoded['split_basis']}


def _usage_row(record, observation_id):
    """EG07 from the session observation: the transport reported its calls, total input (cache included) and output
    for a session it started. Unknown usage is never observed (a violation); a refusal before any session existed
    consumed nothing (not applicable). Usage is read with the engagement monitor's own rule."""
    try:
        from ravel.controller.engagement.envelope import measured
    except ImportError:  # without the engagement monitor the row stays pending
        return {}
    usage = measured(record.get('usage'))
    if record.get('status') == 'refused' and (record.get('usage') or {}).get('reported') is not True:
        return {'EG07': seat_closure.na('refused_before_any_session', record=observation_id)}
    if usage is None or not record.get('session_id'):
        reason = 'session_identity_missing' if usage is not None else 'transport_usage_unreported_or_invalid'
        return {'EG07': {'status': 'violated', 'evidence': {'record': observation_id, 'reason': reason}}}
    return {'EG07': {'status': 'satisfied', 'evidence': {
        'record': observation_id, 'mechanism': 'engagement.envelope.measured', 'calls': usage['calls'],
        'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens'], 'cost_usd': usage['cost_usd'],
        'split': (record.get('meter') or {}).get('split')}}}


def _measured(receipt):
    usage = receipt.get('usage') or {}
    tokens = None
    if usage.get('reported') and type(usage.get('input_tokens')) is int and type(usage.get('output_tokens')) is int:
        tokens = usage['input_tokens'] + usage['output_tokens']
    return {'wall_seconds': receipt.get('wall_seconds'), 'model_calls': usage.get('turns'), 'tokens': tokens,
            'cost_usd': usage.get('cost_usd'), 'core_hours': 0, 'events': 0, 'children': 1}


def _instruction_observation(state, receipt):
    """Retain transport-observed bytes and bind delivery to a protected session record.

    P03 uses the store record id as its custody handle. The transport's canonical session_id
    stays a separate field and is checked for reuse before acknowledgement can discharge rows.
    """
    from ravel.workflow import agent_worker, broker
    store, packet_info = _store(state), state['packet']
    if receipt['status'] == 'refused' or not receipt.get('session_id'):
        return {}
    previous = [r for r in records(store, 'worker-session') if r.get('receipt_sha256') == broker.digest(receipt)]
    if previous:
        session = previous[0]['_record_id']
        deliveries = [r for r in records(store, 'instruction-delivery') if r.get('session') == session
                      and r.get('kind') == 'instruction-delivery']
        completions = [r for r in records(store, 'worker-completion') if r.get('session') == session]
        if len(deliveries) != 1 or len(completions) != 1:
            raise StepHold('instruction_observation_incomplete', 'the observed session needs one delivery and completion')
        return {'instruction_session': session, 'instruction_receipt': deliveries[0]['_record_id'],
                'completion_id': completions[0]['_record_id']}
    committed = unwrap(store.read('instruction-packet', packet_info['commitment']))
    binding = {'run_id': store.run_id, 'step': state['acting']['id'], 'attempt': _attempt(state),
               'manifest_sha256': packet_info['manifest']['sha256'], 'packet_sha256': packet_info['sha256']}
    session = store.append('worker-session', {
        **binding, 'session_id': receipt['session_id'], 'receipt_sha256': broker.digest(receipt),
        'seat': _seat_key(state), **{k: committed[k] for k in ('packet', 'card', 'step_spec', 'inputs')}})
    # The seat names whose attempt this is: check-in seats share one step id and attempt.
    store.append('step-attempt', {**binding, 'session': session, 'session_id': receipt['session_id'],
                                  'seat': _seat_key(state)})
    instructions = module('instructions')
    delivery = instructions.record_delivery(store, packet_info['manifest'], committed['packet'], session=session)
    workspace = agent_worker.workspace(_run_dir(state), receipt['node_id'], _attempt(state))
    final_path = workspace / 'final.json'
    final = json.loads(final_path.read_text()) if final_path.is_file() and not final_path.is_symlink() else {}
    artifacts = []
    for output in receipt.get('credited_outputs') or ():
        path = output['path']
        source = broker.confined(workspace, path)
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != output['sha256']:
            raise StepHold('instruction_output_changed', 'observed output bytes differ from the transport receipt')
        target = store.path('instruction-artifacts', session, *path.split('/'))
        _write_once(target, raw)
        artifacts.append({'path': path, 'sha256': output['sha256']})
    completion = store.append('worker-completion', {**binding, 'session': session,
                                                    'final_record': final, 'artifacts': artifacts})
    # Existing accounting readers consume this projection in the delivery stream.
    store.append('instruction-delivery', {'kind': 'instruction-delivery-session', 'delivery': delivery,
        'manifest_sha256': binding['manifest_sha256'], 'packet_sha256': binding['packet_sha256'],
        'session': receipt['session_id'], 'step_id': binding['step'], 'attempt': binding['attempt'],
        'seat': _seat_key(state), 'node_id': receipt['node_id'], 'packet_tokens': packet_info['tokens']})
    return {'instruction_session': session, 'instruction_receipt': delivery, 'completion_id': completion}


def _capture_session(run_dir, receipt, state, node_id, attempt):
    """Record the worker session this dispatch observed in the controller's store (P13 census).

    Every session counts, producers included, so a reviewer's independence is judged against the
    complete census; a receipt with no child session (a refusal before the start) records nothing.
    Returns ``(the seat's session record or None, its store id or None, every observed session)``.
    """
    from ravel.workflow import review_dispatch, review_independence
    review_store = review_independence.controller_store(run_dir)
    if review_store is None:
        return None, None, []
    reviewer = (_seat(state) or {}).get('purpose') == 'review' or state['acting']['kind'] == 'review'
    seat = f'{node_id}:{attempt}'
    review_dispatch.capture_worker_session(review_store, receipt=receipt, step_id=state['acting']['id'],
                                           seat=seat, role_kind='reviewer' if reviewer else 'producer')
    sessions = records(review_store, review_dispatch.SESSION_KIND)
    mine = [r for r in sessions if r.get('seat') == seat and r.get('step_id') == state['acting']['id']]
    if len(mine) != 1:
        return None, None, sessions
    return mine[0], mine[0].get('_record_id'), sessions


def _session_label(session, sessions):
    """The family label of a separate observed session against the run's other sessions (never a requirement)."""
    from ravel.workflow.review_independence import family_label, family_relation
    others = {f"session:{r.get('session_id')}": {'model': r.get('model')} for r in sessions
              if r.get('session_id') != session.get('session_id')}
    return family_label(family_relation({'reviewer': {'model': session.get('model')}, **others}))


def _observed_isolation(receipt):
    """The receipt's isolation; fresh-request and parent-transcript facts come only from the dispatcher's own
    launch observation (``isolation.launch_context``). Without one they stay absent and earn no credit."""
    isolation = deepcopy(receipt.get('isolation') or {})
    launch_context = isolation.get('launch_context')
    if type(launch_context) is dict:
        isolation['fresh_request'] = bool(launch_context.get('fresh_session') is True
                                          and isolation.get('user_configuration_loaded') is False
                                          and (isolation.get('evidence') or {}).get('confirmed') is True)
        isolation['parent_transcript_supplied'] = (False if launch_context.get('no_parent_transcript_channel') is True
                                                   else None)
    else:
        isolation.pop('fresh_request', None)
        isolation.pop('parent_transcript_supplied', None)
    return isolation


def observe(state):
    from ravel.workflow import agent_worker, broker
    store, run_dir, branch = _store(state), _run_dir(state), state['branch']
    attempt = _attempt(state)
    key = state['reservation']['key']
    if branch == 'worker':
        node_id = state['preflight']['spec']['node_id']
        receipt = agent_worker.load_receipt(run_dir, node_id, attempt)
        session, session_record, sessions = _capture_session(run_dir, receipt, state, node_id, attempt)
        rows = evidence.mirror(store, run_dir, step_id=state['acting']['id'], attempt=attempt, node_id=node_id,
                               worker_attempt=attempt)
        measured = _measured(receipt)
        # A launch refused before its child existed consumed nothing; an ambiguous one stays charged.
        settlement = {'refused': 'released', 'ambiguous': 'ambiguous'}.get(receipt['status'], 'settled')
        budget.settle(store, key, status=settlement, measured=measured,
                      evidence={'receipt_sha256': broker.digest(receipt)})
        # The exact seat identity, packet size and raw meter usage the engagement monitor joins to the dispatch and
        # instruction-delivery records of this attempt (node, seat, attempt).
        usage, meter = _meter(run_dir, receipt)
        record = {'schema_version': 1, 'step_id': state['acting']['id'], 'seat': _seat_key(state), 'attempt': attempt,
                  'node_id': node_id, 'receipt_sha256': broker.digest(receipt), 'status': receipt['status'],
                  'session_id': receipt.get('session_id'), 'actor_id': receipt.get('actor_id'),
                  'attestation': receipt.get('attestation'), 'model': deepcopy(receipt.get('model')),
                  'usage': usage, 'meter': meter, 'packet_sha256': state['packet'].get('sha256'),
                  'packet_tokens': state['packet'].get('tokens'),
                  'final_record_returned': bool((receipt.get('final_record') or {}).get('sha256')),
                  'transport': (receipt.get('transport') or {}).get('id'),
                  'provider_egress': deepcopy((receipt.get('transport') or {}).get('egress')),
                  # Only dispatcher-recorded evidence is copied: the receipt's transport and execution mode, and
                  # its isolation with freshness derived solely from the dispatcher's launch observation.
                  'transport_evidence': {**deepcopy(receipt.get('transport') or {}),
                                         'execution_mode': receipt.get('execution_mode')
                                         or agent_worker.execution_mode(receipt.get('transport'))},
                  'isolation': _observed_isolation(receipt),
                  'calls': evidence.call_counts(rows), 'failure': deepcopy(receipt.get('failure')),
                  'tool_inventory': deepcopy((receipt.get('transport') or {}).get('tool_inventory'))}
        prior = next((r for r in records(store, OBSERVATION) if r.get('receipt_sha256') == record['receipt_sha256']), None)
        observation_id = prior['_record_id'] if prior else store.append(OBSERVATION, record)
        instruction = _instruction_observation(state, receipt)
        evaluations = {'M25': {'status': 'satisfied', 'evidence': {'receipt': record['receipt_sha256'], 'calls': len(rows)}},
                       'G13': {'status': 'satisfied', 'evidence': {'receipt': record['receipt_sha256'], 'mirrored': len(rows)}}}
        evaluations.update(seat_closure.observation_rows(observation_id, record['tool_inventory'], settlement))
        evaluations.update(evidence.comparison_rows(store, run_dir, state['acting'], record, observation_id, rows))
        evaluations.update(native_checks.worker_inventory_rows(observation_id, state['acting'], record, state['preflight']))
        evaluations.update(_usage_row(prior or record, observation_id))
        if session is not None:
            evaluations.update(seat_closure.session_rows(
                _card(state), session, sessions, session_record=session_record,
                transport_kind=(receipt.get('transport') or {}).get('transport_kind'),
                admitted_kinds=seats.ADMITTED_KINDS, label=_session_label(session, sessions)))
        return {'observation': {'kind': 'worker', 'receipt_sha256': record['receipt_sha256'], 'status': receipt['status'],
                                'session_id': receipt.get('session_id'), 'measured': measured,
                                'evidence': [r['receipt_id'] for r in rows], **instruction},
                'evaluations': evaluations}
    if branch == 'launch':
        launch = state['launch']
        measured = {'wall_seconds': launch['wall_seconds'], 'model_calls': 0, 'tokens': 0, 'cost_usd': None,
                    'core_hours': launch['wall_seconds'] * ((state['preflight']['capsule']['limits'] or {}).get('cpus') or 1)
                    / 3600.0, 'events': None, 'children': 1}
        budget.settle(store, key, status='settled', measured=measured, evidence={'journal': launch['journal_id']})
        if state['acting'].get('rung') == 'pilot' and not _pilot(state):
            events = (state['acting'].get('budget') or {}).get('events')
            budget.record_calibration(store, state['acting'],
                                      status='succeeded' if launch['exit_status'] == 0 and not launch['timed_out'] else 'failed',
                                      measured={'wall_seconds': launch['wall_seconds'], 'events': events})
        evaluations = native_rows.observation_rows(launch, state['preflight'].get('inventory'),
                                                     'settled', role=_card(state))
        evaluations.update(native_rows.role_worker_absence(
            _card(state), launch, card_sha256=(state.get('card') or {}).get('sha256'),
            entries=state['preflight'].get('instruction_entries') or ()))
        if (launch.get('custody_check') or {}).get('record'):
            evaluations['SW41'] = {'status': 'satisfied', 'evidence': launch['custody_check']}
        evaluations.update(native_rows.path_absence(launch))
        evaluations.update(native_checks.authority_rows(store, state['acting'], _ctx(state)))
        evaluations.update(native_checks.acquisition_rows(launch, state['preflight'].get('source_admission')))
        evaluations.update(native_checks.gate_rows(
            store, state['acting'], {**_ctx(state), 'attempt': _attempt(state)},
            state['preflight'], launch))
        evaluations.update(native_checks.confinement_rows(
            launch, state['reservation'], state['preflight'].get('inventory')))
        evaluations.update(native_checks.input_rows(
            state['acting'], _ctx(state), state['preflight'].get('source_admission'),
            launch, state['preflight'].get('inventory'), evaluations))
        evaluations['EG07'] = seat_closure.na('launch_runs_no_model_session', record=launch.get('journal_id'))
        if 'P05' not in evaluations:
            evaluations.update(_launch_chain_rows(state, store, launch, evaluations))
        return {'observation': {'kind': 'launch', 'exit_status': launch['exit_status'], 'measured': measured},
                'evaluations': evaluations}
    child = state.get('child') or {}
    measured, usage_record = subgraph_usage.measurement(store, state['acting'], attempt)
    budget.settle(store, key, status='settled', measured=measured,
                  evidence={'child': child, 'subgraph_usage': usage_record})
    # The child graph's own seats observe their sessions; this seat starts none.
    return {'observation': {'kind': 'subgraph', 'outcome': child.get('outcome'), 'measured': measured},
            'evaluations': {'EG07': seat_closure.na('subgraph_seat_starts_no_model_session',
                                                    record=child.get('record_id'))}}


# ---- validate --------------------------------------------------------------------------------

def _seen_sessions(store, own_receipt):
    return {r.get('session_id') for r in records(store, OBSERVATION)
            if r.get('session_id') and r.get('receipt_sha256') != own_receipt}


def _verdict(record, items, observations=()):
    """``accept``, ``revise`` or ``unresolved`` from findings and protected observations."""
    if any(type(row) is dict and row.get('status') == 'failed' for row in observations):
        return 'revise'
    if any(type(row) is not dict or row.get('status') != 'passed' for row in observations):
        return 'unresolved'
    if type(record) is not dict:
        return 'unresolved'
    verdicts = [row.get('verdict') for row in record.get('item_verdicts') or () if type(row) is dict]
    blocking = [row for row in record.get('items') or () if type(row) is dict and row.get('severity') == 'A']
    if 'fail' in verdicts or blocking:
        return 'revise'
    if 'unresolved' in verdicts or (items and len(verdicts) < len(items)):
        return 'unresolved'
    return 'accept'


def _record_judgment(state, receipt, workspace):
    """Only receipt-bound decision bytes enter the judgment service, before adoption."""
    from ravel.controller.graph import service
    from ravel.workflow import broker
    step = state['acting']
    outputs = [row for row in step['outputs'] if row['kind'] == 'judgment-record']
    if len(outputs) != 1:
        return [], [{'code': 'judgment_record_missing' if not outputs else 'judgment_record_ambiguous'}]
    try:
        if step.get('consequence_class') not in ('R0', 'R1', 'R2', 'R3'):
            raise ValueError('a decision needs its planned consequence class')
        path = outputs[0]['path']
        credited = [row for row in receipt.get('credited_outputs') or [] if row['path'] == path]
        if len(credited) != 1:
            raise ValueError('the judgment output has no unique transport credit')
        target = broker.confined(workspace, path)
        if target.is_symlink() or not target.is_file():
            raise ValueError('the judgment output is not a regular file')
        raw = target.read_bytes()
        if hashlib.sha256(raw).hexdigest() != credited[0]['sha256']:
            raise ValueError('the judgment output differs from its transport receipt')
        identifier = service('judgment').record_judgment(_store(state), json.loads(raw), step=step,
                                                        plan_class=step['consequence_class'])
        if type(identifier) is not str or not identifier:
            raise ValueError('the judgment service returned no record id')
        return [identifier], []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [], [{'code': 'judgment_record_invalid', 'detail': str(exc)[:1500]}]


def validate_node(state):
    from ravel.workflow import agent_worker
    branch, store = state['branch'], _store(state)
    if branch == 'launch':
        launch = state['launch']
        errors = []
        if launch['exit_status'] != 0 or launch['timed_out']:
            errors.append({'code': 'launch_failed', 'exit_status': launch['exit_status'], 'timed_out': launch['timed_out']})
        if launch.get('confinement_errors'):
            errors.append({'code': 'confinement_finish_failed', 'errors': launch['confinement_errors'][:20]})
        labels = [{'label': launch['label']}] if launch.get('label') else []
        if launch.get('quarantined'):
            labels.append({'label': 'undeclared_writes_quarantined', 'paths': launch['quarantined'][:50]})
        return {'validation': {'passed': not errors, 'held': [], 'errors': errors, 'labels': labels,
                               'escalations': [], 'halts': False}}
    if branch == 'subgraph':
        child = state.get('child') or {}
        errors = [] if child.get('outcome') == 'ok' else [{'code': 'subgraph_' + str(child.get('outcome'))}]
        if _research_child(state):
            # The research adapter's pins are re-checked byte for byte when custody stages them.
            return {'validation': {'passed': not errors, 'held': [], 'errors': errors,
                                   'labels': deepcopy(child.get('labels') or []),
                                   'escalations': [], 'halts': False}}
        try:
            root = _subgraph_root(state, child['output_root'])
            outputs = _subgraph_outputs(state, root)
            if outputs != child.get('outputs'):
                raise StepHold('subgraph_output_declaration_changed', 'child declarations differ from the approved step')
            if _inventory(root) != child.get('inventory'):
                raise StepHold('adoption_bytes_changed', 'child outputs differ from the observed inventory')
        except StepHold as exc:
            errors.append({'code': exc.reason})
        return {'validation': {'passed': not errors, 'held': [], 'errors': errors, 'labels': [],
                               'escalations': [], 'halts': False}}
    run_dir, card, attempt = _run_dir(state), _card(state), _attempt(state)
    node_id = state['preflight']['spec']['node_id']
    receipt = agent_worker.load_receipt(run_dir, node_id, attempt)
    workspace = agent_worker.workspace(run_dir, node_id, attempt)
    final_path = workspace / 'final.json'
    final = json.loads(final_path.read_text()) if final_path.is_file() and not final_path.is_symlink() else None
    errors, held, labels = [], [], []
    evaluations = {}
    if receipt['status'] == 'refused':
        # Refused before its child existed (a probe difference, a transport refusal): a typed hold, never a
        # retry, and no obligation of the record is evaluated because no record was produced.
        held.append({'code': str((receipt.get('failure') or {}).get('code') or 'worker_refused'),
                     'failure': deepcopy(receipt.get('failure'))})
        store.append(VALIDATION, {'schema_version': 1, 'step_id': state['acting']['id'], 'seat': _seat_key(state),
                                  'attempt': attempt, 'receipt_sha256': (state.get('observation') or {}).get(
                                      'receipt_sha256'), 'errors': [], 'held': deepcopy(held), 'labels': [],
                                  'escalations': []})
        return {'validation': {'passed': False, 'held': held, 'errors': [], 'labels': [], 'escalations': [],
                               'halts': False, 'verdict': None, 'final_sha256': None}}
    if receipt['status'] != 'ok':
        errors.append({'code': 'worker_receipt_' + receipt['status'], 'failure': deepcopy(receipt.get('failure')),
                       'checks': deepcopy((receipt.get('outcome') or {}).get('computed_checks'))})
    packet_info = state['packet']
    ack = ['manifest: final record missing']
    if final is None:
        errors.append({'code': 'final_record_missing'})
        found, escalation_errors = [], []
    else:
        problems = validate.schema_errors(final, packet_info['schema'])
        if problems:
            errors.append({'code': 'final_record_schema', 'errors': problems[:20]})
        schema_id = packet_info.get('schema_id') or cards.controller_schema(card)
        problems = validate.card_schema_errors(card, final, schema_id)
        if problems:
            errors.append({'code': 'card_output_schema', 'schema': schema_id, 'errors': problems[:20]})
        written = [row['path'] for row in receipt.get('credited_outputs') or ()]
        observed = state.get('observation') or {}
        ack = validate.ack_errors(packet_info['manifest'], final, written, store=store,
                                  session=observed.get('instruction_session'),
                                  completion_id=observed.get('completion_id'))
        holding, failing = validate.split_ack(ack)
        held += [{'code': 'checklist_blocked', 'detail': e} for e in holding]
        if failing:
            errors.append({'code': 'instruction_ack', 'errors': failing[:50]})
        found, escalation_errors = validate.escalation(final, card)
        errors += escalation_errors
    session_errors = seats.fresh_session_errors(receipt, _seen_sessions(store, (state.get('observation') or {}).get(
        'receipt_sha256')))
    errors += session_errors
    packet_path = run_dir / packet_info['path']
    if (packet_path.is_symlink() or not packet_path.is_file()
            or hashlib.sha256(packet_path.read_bytes()).hexdigest() != packet_info['file_sha256']):
        errors.append({'code': 'instruction_packet_changed'})
    dispatched = next((r for r in records(store, DISPATCH) if r.get('key') == state['preflight']['dispatch_key']), {})
    model = seats.model_check(card, dispatched, receipt)
    if not model['matches']:
        errors.append({'code': 'model_' + model.get('reason', 'mismatch'), 'model': model})
    card_calls = state['preflight']['applied']['card_broker_calls']
    if (receipt.get('broker') or {}).get('calls', 0) > card_calls:
        errors.append({'code': 'broker_calls_above_card', 'calls': receipt['broker']['calls'], 'card': card_calls})
    labels += evidence.knowledge_labels(final, [r for r in records(store, evidence.EVIDENCE)
                                                if r.get('node_id') == node_id and r.get('worker_attempt') == attempt])
    seat = _seat(state)
    items = (seat or {}).get('items') or []
    if seat is not None and seat['purpose'] == 'review' and final is not None and items:
        problems = module('instructions').check_item_verdicts(items, final)
        if problems:
            errors.append({'code': 'reviewer_item_verdicts', 'errors': [str(p) for p in problems[:50]]})
    judgments = []
    if state['acting']['kind'] == 'decide' and not errors and not held:
        judgments, problems = _record_judgment(state, receipt, workspace)
        errors += problems
        evaluations['JR05'] = {'status': 'satisfied' if judgments else 'violated',
                                'evidence': {'records': judgments}}
        # E28 is review-gated: only the credited, observed RDJ case discharges it (``judgment.checkins``).
    producer_rows = {}
    if seat is None and state['acting']['kind'] != 'review' and receipt['status'] == 'ok':
        producer_rows, refusals = _producer_rows(state, store, card, receipt, packet_info)
        errors += refusals
    codes = {e['code'] for e in errors}
    role = card['id']
    status = lambda bad: 'violated' if bad else 'satisfied'  # noqa: E731
    evaluations.update({
        'I01': {'status': status('instruction_ack' in codes), 'evidence': {'instruction_receipt': (state.get('observation') or {}).get('instruction_receipt')}},
        'M13': {'status': status('instruction_ack' in codes), 'evidence': {'instruction_receipt': (state.get('observation') or {}).get('instruction_receipt')}},
        'CF06': {'status': status('card_output_schema' in codes or 'final_record_schema' in codes), 'evidence': {}},
        f'ROLE-{role}-output': {'status': status(bool({'card_output_schema', 'final_record_schema'} & codes)),
                                'evidence': {'schema': packet_info.get('schema_id')}},
        'I08': {'status': status(not model['matches']), 'evidence': model},
        f'ROLE-{role}-model': {'status': status(not model['matches']), 'evidence': model},
        'I05': {'status': status(bool(session_errors)), 'evidence': {'session': receipt.get('session_id')}},
        'I07': {'status': 'violated' if labels else 'satisfied', 'evidence': {'labels': labels}},
    })
    halts = any(f['kind'] in escalations.HALTING for f in found)
    record = {'schema_version': 1, 'step_id': state['acting']['id'], 'seat': _seat_key(state), 'attempt': attempt,
              'receipt_sha256': (state.get('observation') or {}).get('receipt_sha256'), 'errors': deepcopy(errors),
              'held': deepcopy(held), 'labels': labels, 'escalations': [f['kind'] for f in found],
              'judgments': judgments, 'model': deepcopy(model)}
    validation_id = store.append(VALIDATION, record)
    for value in evaluations.values():
        value['evidence']['validator'] = validation_id
        if value['status'] == 'violated':
            value['evidence']['reason'] = ','.join(sorted(codes)) or 'knowledge_use_unsupported'
    if labels:
        evaluations['I07']['evidence']['label'] = labels[0]['label']
    for row, value in {**seat_closure.packet_rows(packet_info['manifest']),
                       **seat_closure.validate_rows(state['acting'], seat, validation_id)}.items():
        evaluations.setdefault(row, value)
    if seat is not None and seat['purpose'] == 'review':
        evaluations.update(_seat_validate_rows(state, store, card, receipt, final, validation_id))
    for row, value in producer_rows.items():
        evaluations[row] = {**value, 'evidence': {**value['evidence'], 'validator': validation_id}}
    observed = state.get('observation') or {}
    if observed.get('instruction_receipt') and not session_errors and 'instruction_packet_changed' not in codes:
        ledger = module('ledger')
        entries = state['preflight']['instruction_entries']
        catalogue = ledger.load_catalogue() if hasattr(ledger, 'load_catalogue') else None
        instructions = module('instructions')
        stated = instructions.obligations(packet_info['manifest'])
        selected = {}
        for entry in entries:
            row = str(entry).split('@', 1)[0]
            role_row = row.startswith('ROLE-') and (row.endswith(('-purpose', '-knowledge')) or '-protocol-' in row)
            mechanism = row in ('I01', 'I02', 'E29', 'CF03', 'CF13', 'CT02')
            if row == 'E29' and not any(u.get('via') == 'skill' for u in packet_info['manifest']['units']):
                continue
            # A partial acknowledgement never closes any instructed row of this seat.
            if mechanism or (role_row and row in stated and not ack):
                if catalogue and catalogue.rows[row]['class'] == 'I' and ack:
                    continue
                selected[row] = entry
        try:
            def record_instruction(store, entry, status, evidence_):
                ledger.record(store, entry, status, evidence_)
                row = str(entry).split('@', 1)[0]
                evaluations[row] = {'status': status, 'evidence': deepcopy(evidence_), 'instruction_recorded': True}
            instructions.discharge(store, selected, packet_info['manifest'],
                                   receipt_id=observed['instruction_receipt'], record=record_instruction)
        except (ValueError, getattr(ledger, 'LedgerError', ValueError)) as exc:
            errors.append({'code': 'instruction_discharge_refused', 'reason': str(exc),
                           'ledger_code': getattr(exc, 'code', type(exc).__name__)})
            store.append('step-instruction-discharge-refused', {'step_id': state['acting']['id'],
                         'attempt': attempt, 'receipt': observed['instruction_receipt'], 'error': errors[-1]})
    is_review = (seat or {}).get('purpose') == 'review' or state['acting']['kind'] == 'review'
    verdict = (_verdict(final, items, state.get('preflight', {}).get('ml_observations') or [])
               if is_review else None)
    findings = None
    if is_review and final is not None:
        findings = store.append('step-review-findings', {
            'schema_version': 1, 'step_id': state['acting']['id'], 'parent_step': state['step']['id'],
            'seat': _seat_key(state), 'attempt': attempt, 'verdict': verdict,
            'subject_sha256': ((seat or {}).get('subject') or {}).get('sha256') or state['preflight']['subject_sha256'],
            'receipt_sha256': (state.get('observation') or {}).get('receipt_sha256'),
            'validation': validation_id, 'record_sha256': digest(final), 'record': deepcopy(final),
            'valid': not errors and not held})
    return {'validation': {'passed': not errors and not held, 'held': held, 'errors': errors, 'labels': labels,
                           'escalations': found, 'halts': halts, 'verdict': verdict,
                           'final_sha256': digest(final) if final is not None else None,
                           'judgments': judgments, 'model': deepcopy(model), 'findings': findings},
            'evaluations': evaluations}


def _producer_rows(state, store, card, receipt, packet_info):
    """A producer's own rows at its validate node: ``(rows, refusals)``.

    P05: each quantity the producer consumed from an upstream step (an upstream artifact among its verified custody
    inputs whose bytes its broker reads show) is that step's adopted, accepted output, byte for byte; a mismatch
    refuses the step. A producer that consumed no upstream quantity hands none off: not applicable, with what it
    was given and what it read. ``ROLE-<card>-sees``: the card's sees constraint reached the worker in its delivered
    instruction packet (the unit the delivery receipt pins, with the card's current text) and every input it was
    given passes the card's forbidden-input screen, as a review seat's projection is checked.
    """
    from ravel.controller.instructions import compiler
    from ravel.workflow import review_projection
    run_dir, acting = _run_dir(state), state['acting']
    ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
    _, found, run_inputs = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    reads = sorted({(pin['path'], pin['sha256']) for row in records(store, evidence.EVIDENCE)
                    if row.get('node_id') == receipt['node_id'] and row.get('worker_attempt') == receipt['attempt']
                    for pin in row.get('input_pins') or ()})
    read_digests = {sha for _, sha in reads}
    current = custody.custody_index(store)
    handoffs = []
    for record in found:
        now = current.get(record['artifact']) or {}
        if record['sha256'] in read_digests:
            handoffs.append({'artifact': record['artifact'], 'from_step': record['step_id'], 'sha256': record['sha256'],
                             'quantity': record.get('quantity'), 'adopted_sha256': now.get('sha256'),
                             'adopted_status': now.get('status'), 'adopted_record': now.get('_record_id')})
    mismatched = [h for h in handoffs if h['adopted_status'] != 'accepted' or h['adopted_sha256'] != h['sha256']]
    given = _fact(state, 'chain-handoffs-checked', handoffs=handoffs, reads=[{'path': p, 'sha256': s} for p, s in reads],
                  inputs=[{'artifact': r['artifact'], 'sha256': r['sha256']} for r in found],
                  run_inputs=[{'artifact': r['artifact'], 'sha256': r['sha256']} for r in run_inputs])
    if mismatched:
        rows = {'P05': {'status': 'violated', 'evidence': {**given, 'reason': 'chain_handoff_mismatch',
                                                           'label': 'CHAIN HANDOFF MISMATCH'}}}
        refusals = [{'code': 'chain_handoff_mismatch', 'handoffs': mismatched[:20]}]
    elif handoffs:
        rows, refusals = {'P05': {'status': 'satisfied', 'evidence': dict(given)}}, []
    else:
        rows, refusals = {'P05': {'status': 'not_applicable', 'evidence': {
            **given, 'reason': 'not_applicable:no_upstream_quantity_consumed', 'label': 'no chain handoff'}}}, []
    unit_id = f"{compiler.CARD_PATH.format(role=card['id'])}#sees/0"
    expected = compiler.digest_text(json.dumps(card['sees'], sort_keys=True, ensure_ascii=False))
    delivered = next((u for u in (packet_info.get('manifest') or {}).get('units') or () if u.get('id') == unit_id), None)
    paths = [r['destination'] for r in found] + [r['artifact'] for r in run_inputs]
    _, removed = review_projection.screen_inputs(run_dir, card['id'], paths)
    receipt_id = (state.get('observation') or {}).get('instruction_receipt')
    problems = ([] if delivered is not None and delivered.get('sha256') == expected else ['sees_unit_not_delivered'])
    problems += ['forbidden_input_given'] if removed else []
    problems += [] if receipt_id else ['no_instruction_receipt']
    rows[f"ROLE-{card['id']}-sees"] = {'status': 'violated' if problems else 'satisfied', 'evidence': {
        'instruction_receipt': receipt_id, 'manifest_sha256': (packet_info.get('manifest') or {}).get('sha256'),
        'unit': unit_id, 'unit_sha256': expected, 'profile': card['sees'].get('profile'),
        'forbidden_inputs': sorted(card['sees'].get('forbidden_inputs') or []), 'screened': len(paths),
        'removed': removed, **({'reason': ','.join(problems)} if problems else {})}}
    return rows, refusals


def _parent_checks(store, step_id, attempt):
    """``(validation record id, report)`` of the checks a step's producer ran in ``attempt``, or ``(None, None)``."""
    found = next((r for r in reversed(records(store, VALIDATION)) if r.get('step_id') == step_id
                  and r.get('seat') is None and r.get('attempt') == attempt and type(r.get('report')) is dict), None)
    return (found.get('_record_id'), found['report']) if found else (None, None)


def _launch_chain_rows(state, store, launch, enforced):
    """P05 for a confined launch: it consumed exactly its committed input copies (``T04``, confine.prepare_and_finish),
    so each declared upstream input must still be the accepted custody bytes it committed; a launch consuming no
    upstream quantity hands none off. Without the confined-input proof nothing is recorded."""
    proof = enforced.get('T04') or {}
    if proof.get('status') != 'satisfied' or (proof.get('evidence') or {}).get('mechanism') != 'confine.prepare_and_finish':
        return {}
    run_dir, acting = _run_dir(state), state['acting']
    ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
    errors, found, run_inputs = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    current = custody.custody_index(store)
    handoffs = [{'artifact': r['artifact'], 'from_step': r['step_id'], 'sha256': r['sha256'],
                 'quantity': r.get('quantity'), 'adopted_sha256': (current.get(r['artifact']) or {}).get('sha256'),
                 'adopted_status': (current.get(r['artifact']) or {}).get('status')} for r in found]
    given = _fact(state, 'chain-handoffs-checked', handoffs=handoffs, launch=launch.get('finished_id'),
                  committed_inputs=proof.get('evidence'), confined_by='confine.prepare_and_finish',
                  run_inputs=[{'artifact': r['artifact'], 'sha256': r['sha256']} for r in run_inputs])
    mismatched = [h for h in handoffs if h['adopted_status'] != 'accepted' or h['adopted_sha256'] != h['sha256']]
    if errors or mismatched:
        return {'P05': {'status': 'violated', 'evidence': {**given, 'reason': 'chain_handoff_mismatch',
                                                           'label': 'CHAIN HANDOFF MISMATCH',
                                                           'errors': deepcopy(errors[:20])}}}
    if handoffs:
        return {'P05': {'status': 'satisfied', 'evidence': given}}
    return {'P05': {'status': 'not_applicable', 'evidence': {
        **given, 'reason': 'not_applicable:no_upstream_quantity_consumed', 'label': 'no chain handoff'}}}


def _seat_validate_rows(state, store, card, receipt, final, validation_id):
    """A review seat's own rows at its validate node, each from the action that enforces it.

    CF05: the seat's credited outputs are exactly the outputs its spec declares (the card's declared outputs and
    sidecar are read, not assumed). I09 and ``ROLE-<card>-must_check-<i>``: the producer performed this reviewer's
    self-checks on the subject (``role_registry.self_checks`` puts them in its union); their results are the producer's
    validator run of this attempt, which this seat's evidence names. A must_check entry whose check computes nothing is
    owed as this seat's own item verdict (``must_check:<check>``) and is recorded from it.
    """
    rows = {}
    declared = {row['path']: row for row in (state.get('preflight') or {}).get('outputs') or ()}
    credited = sorted(row['path'] for row in receipt.get('credited_outputs') or ())
    missing = sorted(path for path, row in declared.items() if row.get('required') and path not in credited)
    undeclared = sorted(path for path in credited if path not in declared)
    outputs = _fact(state, 'seat-outputs-declared', declared=sorted(declared), credited=credited,
                    sidecar=bool((card or {}).get('output', {}).get('sidecar')))
    rows['CF05'] = {'status': 'violated' if missing or undeclared else 'satisfied',
                    'evidence': {**outputs, **({'reason': 'outputs_differ_from_spec', 'missing': missing,
                                                'undeclared': undeclared} if missing or undeclared else {})}}
    record_id, report = _parent_checks(store, state['step']['id'], _attempt(state))
    runnable, _ = validate.validator_ids(card)
    if report is None:
        reason = {'reason': 'producer_checks_missing', 'seat_validation': validation_id}
        rows['I09'] = {'status': 'violated', 'evidence': reason}
        for index, _check in enumerate(card['must_check']):
            rows[f"ROLE-{card['id']}-must_check-{index}"] = {'status': 'violated', 'evidence': dict(reason)}
        return rows
    performed = [r for r in report.get('results') or () if r.get('check_id') in runnable]
    absent = sorted(set(runnable) - {r['check_id'] for r in performed})
    bad = [r['check_id'] for r in performed if r.get('status') != 'passed']
    rows['I09'] = {'status': 'violated' if absent or bad else 'satisfied', 'evidence': {
        'validator': record_id, 'seat_validation': validation_id, 'checks': sorted(runnable),
        **({'reason': 'reviewer_self_checks_not_performed', 'absent': absent} if absent else
           {'reason': 'reviewer_self_checks_failed', 'failed': bad} if bad else {})}}
    rows.update(must_check_rows(card, performed, record_id))
    verdicts = {v.get('item'): v for v in (final or {}).get('item_verdicts') or () if type(v) is dict}
    for index, check in enumerate(card['must_check']):
        key = f"ROLE-{card['id']}-must_check-{index}"
        if key in rows:
            continue
        from ravel.workflow import role_registry
        if set(role_registry.resolve_self_checks([check])) & set(runnable):
            rows[key] = {'status': 'violated', 'evidence': {'validator': record_id, 'seat_validation': validation_id,
                                                            'reason': f'producer_did_not_run:{check}'}}
            continue
        given = verdicts.get(f'must_check:{check}') or {}
        rows[key] = {'status': 'satisfied' if given.get('verdict') == 'pass' else 'violated', 'evidence': {
            'seat_validation': validation_id, 'item': f'must_check:{check}', 'verdict': given.get('verdict'),
            **({} if given.get('verdict') == 'pass' else {'reason': f"item_verdict_{given.get('verdict') or 'missing'}"})}}
    return rows


def after_validate(state):
    validation = state['validation']
    if validation['passed'] and not _pilot(state):
        return 'adopt'
    # A derived pilot's outputs calibrate its cost only; they are never adopted as the step's outputs.
    return 'ledger_update'


# ---- adopt and checks ------------------------------------------------------------------------

def _adoption_scope(store, step, attempt):
    """Retain logical artifact handles while giving every attempt immutable bytes and identity."""
    physical = deepcopy(step)
    physical['id'] = custody.attempt_step_id(step['id'], attempt)
    def append(kind, record):
        if kind == custody.CUSTODY:
            record['step_id'] = step['id']
            record['artifact'] = f"{step['id']}:{record['path']}"
            record['artifact_id'] = digest({'step': step['id'], 'attempt': attempt, 'path': record['path'],
                                            'sha256': record['sha256'], 'destination': record['destination']})
        return store.append(kind, record)
    class AdoptionStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def append(self, kind, record):
            return append(kind, record)

    return AdoptionStore(), physical

def adopt(state):
    from ravel.workflow import agent_worker
    store, run_dir, branch = _store(state), _run_dir(state), state['branch']
    attempt, card = _attempt(state), _card(state)
    acting = state['acting']
    ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
    _, found, _ = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    try:
        if branch == 'worker':
            node_id = state['preflight']['spec']['node_id']
            receipt = agent_worker.load_receipt(run_dir, node_id, attempt)
            recorded = agent_worker._record(run_dir, node_id, attempt)['spec']
            workspace = agent_worker.workspace(run_dir, node_id, attempt)
            adoption_store, adoption_step = _adoption_scope(store, acting, attempt)
            adopted = custody.worker_adoption(
                adoption_store, run_dir=run_dir, step=adoption_step, attempt=attempt, card=card, receipt=receipt, workspace=workspace,
                sealed_spec_sha256=state['preflight']['spec_sha256'], recorded_spec=recorded,
                outputs=state['preflight']['outputs'], inputs_custody=found, final_path=workspace / 'final.json',
                sidecar=card['output']['sidecar'], sidecar_path=_sidecar_path(state, card))
        elif branch == 'launch':
            adoption_store, adoption_step = _adoption_scope(store, acting, attempt)
            adopted = custody.launch_adoption(adoption_store, run_dir=run_dir, step=adoption_step, attempt=attempt, card=card,
                                              launch=state['launch'], outputs=state['preflight']['outputs'],
                                              inputs_custody=found, host_store=store, host_step=acting)
        elif branch == 'subgraph' and _research_child(state):
            adoption_store, adoption_step = _adoption_scope(store, acting, attempt)
            adopted = custody.subgraph_adoption(adoption_store, run_dir=run_dir, step=adoption_step, attempt=attempt,
                                                card=card, child=state['child'], inputs_custody=found,
                                                source_step_id=acting['id'])
        elif branch == 'subgraph':
            child = state['child']
            root = _subgraph_root(state, child['output_root'])
            outputs = _subgraph_outputs(state, root)
            if outputs != child.get('outputs'):
                raise StepHold('subgraph_output_declaration_changed', 'child declarations changed before adoption')
            adoption_store, adoption_step = _adoption_scope(store, acting, attempt)
            adopted = custody.launch_adoption(adoption_store, run_dir=run_dir, step=adoption_step, attempt=attempt,
                card=card, launch={**child, 'output_root': str(root), 'journal_id': child['record_id'],
                                  'backend': 'subgraph'}, outputs=outputs, inputs_custody=found,
                output_prefix='')
        else:
            adopted = []
    except StepHold as exc:
        return {'adoption': {'refused': exc.reason, 'detail': exc.would_make_possible, 'adopted': []},
                'evaluations': {'CF05': {'status': 'violated', 'evidence': {'reason': exc.reason}},
                                'G08': {'status': 'violated' if exc.reason == 'work_order_fidelity' else 'satisfied',
                                        'evidence': {**_fact(state, 'work-order-checked', reason=exc.reason), 'reason': exc.reason}}}}
    rows = [{'artifact': r['artifact'], 'sha256': r['sha256'], 'record_id': r.get('record_id')} for r in adopted]
    adoption_evidence = {'artifact': rows} if rows else _fact(state, 'artifact-adoption-checked', artifacts=rows,
                                                             branch=branch)
    evaluations = {'CF05': {'status': 'satisfied', 'evidence': adoption_evidence},
                   'G08': {'status': 'satisfied', 'evidence': {'sha256': (state.get('preflight') or {}).get('spec_sha256') or spec.step_sha256(acting)}},
                   'I10': {'status': 'satisfied', 'evidence': _fact(state, 'governed-artifact-adoption', artifacts=rows)},
                   'C19': {'status': 'satisfied', 'evidence': _fact(state, 'input-custody-verified', inputs=found)}}
    host_receipts = [r.get('producer', {}).get('host_receipt') for r in adopted if r.get('producer', {}).get('host_receipt')]
    if host_receipts:
        evaluations[f"HOST-{acting['operation']}"] = {'status': 'satisfied', 'evidence': {
            'record': host_receipts[0], 'mechanism': 'host-operation-receipt', 'sha256': spec.step_sha256(acting)}}
    if card is not None:
        evaluations[f"ROLE-{card['id']}-ownership"] = {'status': 'satisfied', 'evidence': _fact(state, 'owned-artifacts-adopted', artifacts=rows)}
    return {'adoption': {'refused': None, 'adopted': [deepcopy(r) for r in adopted]}, 'evaluations': evaluations}


def seat_adopt(state):
    """A seat's own outputs, adopted under the seat step's sealed spec digest and accepted on its validation (G08, I10).

    The same custody adoption a producer's outputs take: the dispatcher-recorded spec must equal the sealed one, every
    required declared output must be credited, and the bytes must be the ones the dispatcher credited. The seat's
    validate node is its check, so what it adopts after a passed validation is accepted with that evidence.
    """
    from ravel.workflow import agent_worker
    store, run_dir, attempt, card = _store(state), _run_dir(state), _attempt(state), _card(state)
    acting = state['acting']
    ancestors = list(state['step']['depends_on']) + list(_ctx(state).get('ancestors') or ())
    _, found, _ = custody.input_errors(store, acting, run_dir, ancestors=ancestors)
    node_id = state['preflight']['spec']['node_id']
    receipt = agent_worker.load_receipt(run_dir, node_id, attempt)
    try:
        workspace = agent_worker.workspace(run_dir, node_id, attempt)
        # Every attempt adopts immutable bytes of its own, as a producer's does: a correction round's review seat
        # never overwrites the review it corrects.
        adoption_store, adoption_step = _adoption_scope(store, acting, attempt)
        adopted = custody.worker_adoption(
            adoption_store, run_dir=run_dir, step=adoption_step, attempt=attempt, card=card, receipt=receipt,
            workspace=workspace, sealed_spec_sha256=state['preflight']['spec_sha256'],
            recorded_spec=agent_worker._record(run_dir, node_id, attempt)['spec'], outputs=state['preflight']['outputs'],
            inputs_custody=found, final_path=workspace / 'final.json', sidecar=card['output']['sidecar'])
    except StepHold as exc:
        return {'adoption': {'refused': exc.reason, 'detail': exc.would_make_possible, 'adopted': []},
                'evaluations': {'G08': {'status': 'violated' if exc.reason == 'work_order_fidelity' else 'satisfied',
                                        'evidence': {**_fact(state, 'work-order-checked', reason=exc.reason),
                                                     'reason': exc.reason}}}}
    validation = _validation_record(store, _seat_key(state), (state.get('observation') or {}).get('receipt_sha256'))
    accepted = custody.accept(store, adopted, 'accepted',
                              evidence={'seat_validation': (validation or {}).get('_record_id'), 'validators': []})
    rows = [{'artifact': r['artifact'], 'sha256': r['sha256'], 'record_id': r.get('record_id')} for r in accepted]
    return {'adoption': {'refused': None, 'adopted': [deepcopy(r) for r in accepted]},
            'evaluations': {'G08': {'status': 'satisfied', 'evidence': {'sha256': state['preflight']['spec_sha256'],
                                                                        **_fact(state, 'seat-work-order-checked',
                                                                                artifacts=rows)}},
                            'I10': {'status': 'satisfied', 'evidence': _fact(state, 'governed-artifact-adoption',
                                                                             artifacts=rows)}}}


def _sidecar_path(state, card):
    """Where a card's final record is adopted: ``final-record.json`` of the step, or one per card for a check-in seat
    (the cards reviewing under one step id must not share it)."""
    return f"final-record-{card['id']}.json" if _seat_key(state) is not None and _seat(state) is None \
        else 'final-record.json'


def after_adopt(state):
    return 'checks' if not (state.get('adoption') or {}).get('refused') else 'ledger_update'


def must_check_rows(card, results, validation_id):
    """``ROLE-<card>-must_check-<i>`` from every result of its check (one per subject it ran on): violated when a
    result neither passed nor is a typed not-applicable, not applicable (citing the review policy's classification
    record) when every result is, satisfied otherwise."""
    rows = {}
    for index, check in enumerate(card['must_check']):
        mine = [r for r in results if check == r['check_id'] or (check.startswith('trap:') and 'trap_sweep' in r['check_id'])]
        if not mine:
            continue
        bad = [r for r in mine if r['status'] not in ('passed', 'not_applicable')]
        absent = all(r['status'] == 'not_applicable' for r in mine)
        evidence = {'validator': validation_id, **({'result': deepcopy(mine[0])} if len(mine) == 1 else
                                                   {'results': deepcopy(mine)})}
        if bad:
            evidence['reason'] = ','.join(sorted({str(r.get('reason') or r['status']) for r in bad}))
        elif absent:
            evidence.update(reason='not_applicable:policy_not_applicable', classification=deepcopy(mine[0].get('classification')))
        rows[f"ROLE-{card['id']}-must_check-{index}"] = {
            'status': 'violated' if bad else 'not_applicable' if absent else 'satisfied', 'evidence': evidence}
    return rows


CLASSIFICATION = 'review-classification'


def policy_exemptions(store, run_dir, card, subjects, *, step=None):
    """``{check id: evidence}`` of the reviewer card's checks without a subject that the run's review policy classifies
    as not applying (``review_points.check_classification``); the evidence cites the stored ``review-classification``
    record. Empty when the policy classifies none of them or cannot be read: each such check then needs its subject."""
    from ravel.workflow import review_points
    runnable, _ = validate.validator_ids(card)
    wanted = [c for c in runnable if not (subjects or {}).get(c)]
    if not wanted:
        return {}
    try:
        value = review_points.check_classification(run_dir, wanted, **({'step': step} if step is not None else {}))
    except Exception:  # an unreadable policy exempts nothing
        return {}
    exempt = {c: row for c, row in value['checks'].items() if row['applies'] is False}
    if not exempt:
        return {}
    record = {'schema_version': 1, 'card': card['id'], **value}
    record_id = next((r['_record_id'] for r in records(store, CLASSIFICATION)
                      if digest({k: r.get(k) for k in record}) == digest(record)), None) \
        or store.append(CLASSIFICATION, record)
    return {c: {'record': record_id, **deepcopy(row)} for c, row in exempt.items()}


def review_subjects(store, ctx, acting, card):
    """A reviewer's own step: ``{check id: [{"step", "parameters"}]}``, the inputs the approved plan declares for each
    of the card's checks on its other steps (``parameters.check_inputs``), bound to the bytes each step adopted and
    custody accepted. A step without accepted outputs yet (its result does not exist) is no subject."""
    runnable, _ = validate.validator_ids(card)
    plan = operations.current_plan(store, ctx)
    accepted = {}
    for row in custody.custody_index(store).values():
        if row.get('status') == 'accepted':
            accepted.setdefault(row['step_id'], []).append(row)
    found = {}
    for row in plan.get('steps') or ():
        if type(row) is not dict or row.get('id') == acting['id'] or not accepted.get(row.get('id')):
            continue
        bound = _bound_check_inputs(row, accepted[row['id']])
        for check_id in runnable:
            if type(bound.get(check_id)) is dict:
                found.setdefault(check_id, []).append({'step': row['id'], 'parameters': bound[check_id], 'spec': deepcopy(row)})
    return found


def _bound_check_inputs(step, adopted):
    """The validator parameters the plan approved with ``step`` (``parameters.check_inputs``; a step has no other
    place for them). A pin naming one of this step's own declared outputs (``{"output": <declared path>}``) is
    bound to the exact bytes adopted for it in this attempt; an output that was not adopted stays as declared, and
    the validator refuses it. Every other value is passed as the plan states it; a declaration that is not an
    object binds nothing, so every validator that needs parameters stays inconclusive."""
    declared = (step.get('parameters') or {}).get('check_inputs')
    if type(declared) is not dict:
        return {}
    own ={r['path']: {'path': r['destination'], 'sha256': r['sha256']} for r in adopted}

    def bind(value):
        if type(value) is dict and set(value) == {'output'} and type(value['output']) is str:
            return deepcopy(own.get(value['output'], value))
        return deepcopy(value)
    return {check: ({key: bind(value) for key, value in parameters.items()} if type(parameters) is dict
                    else deepcopy(parameters)) for check, parameters in declared.items()}


def _self_check_card(state, card):
    """Run the union owed to every review seat selected by the approved step.

    The role registry supplies defaults; an applied plan can require additional
    reviewers. Its choices add their checks without changing any pinned card.
    """
    checked = deepcopy(card)
    from ravel.workflow import operation_check_policy
    for check in operation_check_policy.classify(state['acting'], operation_check_policy.CHECKS):
        if check not in checked['must_check']:
            checked['must_check'].append(check)
    roles = _seat_roles(_store(state), state['acting'], card, _ctx(state))
    for seat in state['acting'].get('engagement_seats') or ():
        if seat.get('role') in roles:
            roles = sorted(set(roles) | set(seat.get('folded_roles') or ()))
    for role in roles:
        reviewer, _, _ = cards.resolve(role, {'registry_sha256': state['card']['registry_sha256']})
        for check in reviewer['must_check']:
            if check not in checked['must_check']:
                checked['must_check'].append(check)
    return checked


def _certificate_disposition(store, run_dir, acting, adopted, checking_card, exempt, owed):
    """``(exempt, owed)`` for both own-card and reviewer-owed certificate checks.

    Only when declared inputs fail resolution does ``review_points.certificate_classification`` decide
    whether the check applies, citing that record. Supplied resolvable inputs still validate; an applicable
    or unreadable policy still refuses missing input.
    """
    from ravel.workflow import review_points
    certificate = review_points.CERTIFICATE_CHECK
    try:
        if certificate not in validate.validator_ids(checking_card)[0]:
            return exempt, owed
    except ValueError:  # a card outside the registry owes no registry reviewer's checks
        return exempt, owed
    bound = _bound_check_inputs(acting, adopted).get(certificate)
    if type(bound) is not dict:
        return exempt, owed
    from ravel.controller.routes.validator_inputs import resolve_inputs
    from ravel.workflow.review_independence import controller_store
    try:
        source_store = controller_store(run_dir)
    except (OSError, ValueError, LookupError):
        source_store = None
    _, errors = resolve_inputs({certificate: bound}, acting, run_dir=run_dir, store=source_store)
    if certificate not in errors:
        return exempt, owed
    try:
        value = review_points.certificate_classification(run_dir)
    except Exception:  # an unreadable policy decides nothing: the check keeps its declared inputs
        return exempt, owed
    row = value['checks'][certificate]
    if row['applies'] is not False:
        return exempt, sorted(set(owed) | {certificate})
    record = {'schema_version': 1, 'card': checking_card['id'], **value}
    record_id = next((r['_record_id'] for r in records(store, CLASSIFICATION)
                      if digest({k: r.get(k) for k in record}) == digest(record)), None) \
        or store.append(CLASSIFICATION, record)
    return {**(exempt or {}), certificate: {'record': record_id, **deepcopy(row)}}, sorted(set(owed) | {certificate})


def _approved_acting(store, state):
    """The approved plan's step equal to the acting step (or a research loop's derived step bound to its protected
    entry), or None when it cannot be authenticated."""
    try:
        approved = operations.plan_step(store, state['acting'], _ctx(state))[0]
    except StepHold:
        return None
    return approved if digest(approved) == digest(state['acting']) else None


def _scope_dispositions(store, run_dir, card, step, own, exempt):
    """A physical check this step's own declared products cannot carry is not this producer's to discharge.

    ``own`` is the operation check policy's disposition of the step (``operation_check_policy.dispositions``): a
    check it marks not applicable has no subject among the step's declared products (all non-physical, or, for the
    cutflow and acceptance checks, none event-level). When the
    run still owes that check at a review point (``review_points.check_classification``), the point stays owed to
    its specialist reviewer against the claim's own subject; it is never removed. The producer run of this step
    records the step disposition and the run-level row it leaves standing. A check the step can carry still runs.
    """
    from ravel.workflow import review_points
    scoped = [c for c, row in own.items() if row.get('applies') is False and c not in (exempt or {})]
    if not scoped:
        return exempt
    try:
        run_level = review_points.check_classification(run_dir, scoped)['checks']
    except Exception:  # an unreadable policy decides nothing: the checks keep their declared inputs
        return exempt
    record = {'schema_version': 1, 'card': card['id'], 'kind': 'step-product-scope', 'step_id': step['id'],
              'step_sha256': digest(step), 'checks': {c: deepcopy(own[c]) for c in scoped},
              'run_level': {c: deepcopy(run_level.get(c)) for c in scoped}}
    record_id = next((r['_record_id'] for r in records(store, CLASSIFICATION)
                      if digest({k: r.get(k) for k in record}) == digest(record)), None) \
        or store.append(CLASSIFICATION, record)
    return {**(exempt or {}), **{c: {'record': record_id, **deepcopy(own[c]),
                                     'run_level_point_owed': bool((run_level.get(c) or {}).get('applies'))}
                                 for c in scoped}}


def checks(state):
    store, run_dir = _store(state), _run_dir(state)
    adopted = (state.get('adoption') or {}).get('adopted') or []
    card = _card(state)
    if spec.parameters(state['acting']).get('adapter') == 'ravel.controller.routes.study.runtime':
        from ravel.controller.routes.study import runtime
        problems = runtime.validate_outcome(store, state['acting'], deepcopy(state.get('launch') or {}),
            {**_ctx(state), 'run_dir': str(run_dir), 'attempt': _attempt(state), 'allow_staged_evidence': True,
             'ledger_scope': _ledger_binding(state)[3]})
        if problems:
            custody.accept(store, adopted, 'rejected', evidence={'scientific_checks': problems})
            return {'checks': {'passed': False, 'results': problems, 'accepted': []}}
    elif spec.parameters(state['acting']).get('evidence_requirements'):
        from ravel.controller.routes.study import runtime
        problems = runtime.scientific_checks(store, state['acting'],
            {**_ctx(state), 'run_dir': str(run_dir), 'attempt': _attempt(state),
             'allow_staged_evidence': True, 'ledger_scope': _ledger_binding(state)[3]}, phase='adopt')
        if problems:
            custody.accept(store, adopted, 'rejected', evidence={'scientific_checks': problems})
            return {'checks': {'passed': False, 'results': problems, 'accepted': []}}
    if card is None:
        accepted = custody.accept(store, adopted, 'accepted', evidence={'validators': []})
        return {'checks': {'passed': True, 'results': [], 'accepted': accepted}}
    scratch = run_dir / 'steps' / state['acting']['id'] / 'attempts' / str(_attempt(state)) / 'validation'
    if _seat_key(state) is not None and _seat(state) is None:  # a check-in seat: one folder per card
        scratch = scratch / _node_id(state)
    checking_card = _self_check_card(state, card)
    subjects = review_subjects(store, _ctx(state), state['acting'], checking_card) if validate.reviewer(card) else None
    exempt = policy_exemptions(store, run_dir, checking_card, subjects) if subjects is not None else None
    owed = ()
    if subjects is None and checking_card != card:
        # The checks a producer runs for its review seats are decided as those seats decide them: a check the
        # review policy classifies as not applying to this run is not applicable (citing that record), never
        # a failure the producer cannot discharge; every other owed check still needs its declared inputs.
        # A self-check card equal to the producer card owes nothing, so no registry lookup is needed.
        owed = sorted(set(validate.validator_ids(checking_card)[0]) - set(validate.validator_ids(card)[0]))
        if owed:
            exempt = {c: v for c, v in policy_exemptions(store, run_dir, checking_card, {}).items() if c in owed}
    from ravel.workflow import operation_check_policy
    if subjects is not None and state['acting'].get('kind') != 'review':
        # A producer step that a reviewer card executes (decision D1): its checks with no subject in the plan follow
        # the step's own declared outputs; a review step's missing subject stays inconclusive.
        unsubjected = [c for c in validate.validator_ids(checking_card)[0] if not (subjects or {}).get(c)]
        if operation_check_policy.dispositions(state['acting'], unsubjected):
            approved = _approved_acting(store, state)
            own = operation_check_policy.dispositions(approved, unsubjected) if approved is not None else {}
            if own:
                exempt = _scope_dispositions(store, run_dir, checking_card, approved, own, exempt)
    if subjects is None:
        # A producer's own checks use the same stored policy disposition as its
        # reviewer-owed checks. Authenticate the operation against the current plan.
        if operation_check_policy.dispositions(state['acting'], operation_check_policy.CHECKS):
            approved = _approved_acting(store, state)
            if approved is not None:
                own = operation_check_policy.dispositions(approved, validate.validator_ids(checking_card)[0])
                if own:
                    owed = sorted(set(owed) | set(own))
                    classified = policy_exemptions(store, run_dir, checking_card, {}, step=approved)
                    exempt = {**(exempt or {}), **{c: v for c, v in classified.items() if c in owed}}
                    exempt = _scope_dispositions(store, run_dir, checking_card, approved, own, exempt)
    exempt, owed = _certificate_disposition(store, run_dir, state['acting'], adopted, checking_card,
                                            exempt, owed)
    report = validate.run_validators(checking_card, {**state['acting'], 'check_inputs': _bound_check_inputs(state['acting'], adopted)},
                                     run_dir=run_dir, scratch=scratch, subjects=subjects, exempt=exempt,
                                     **({'owed': owed} if owed else {}))
    verdict = 'accepted' if report['passed'] else 'rejected'
    rows = custody.accept(store, adopted, verdict, evidence={'validators': report['results']})
    validation_id = store.append(VALIDATION, {'step_id': state['acting']['id'], 'seat': _seat_key(state),
                                               'attempt': _attempt(state), 'report': report})
    evaluations = must_check_rows(card, report['results'], validation_id)
    absent = sorted({r['check_id'] for r in report['results'] if r['status'] == 'not_applicable'})
    evaluations['I09'] = {'status': 'satisfied' if report['passed'] else 'violated', 'evidence': {
        'validator': validation_id, 'checks': [r['check_id'] for r in report['results']],
        **({'not_applicable': absent} if absent else {}),
        **({'reason': 'validators_failed'} if not report['passed'] else {})}}
    return {'checks': {'passed': report['passed'], 'results': report['results'],
                       'reviewer_items': report['reviewer_items'], 'accepted': rows if report['passed'] else []},
            'evaluations': evaluations}


def after_checks(state):
    return 'review' if (state.get('checks') or {}).get('passed') else 'ledger_update'


def review(state):
    items = review_items(state)
    return {'review': {'seats': [{'key': i['key'], 'role': i['role'], 'subject_sha256': i['subject']['sha256'],
                                  **({'mode': i['mode']} if i.get('mode') else {})} for i in items]}}


# ---- credit ----------------------------------------------------------------------------------

def _decision(run_dir, receipt_sha, receipt, subject_sha):
    """The independence decision of one review receipt (``receipt_sha`` is the controller's own digest of it).

    The decision binding names the receipt as the worker dispatcher's custody pinned and registered it:
    the digest of its published bytes, which is what the review evidence is verified against.
    """
    from ravel.workflow import agent_worker
    independence = module('independence')
    query = {'run': str(Path(run_dir).resolve()), 'role': (receipt.get('role') or {}).get('id'),
             'subject_sha256': subject_sha, 'receipt_sha256': receipt_sha,
             'output_sha256': (receipt.get('final_record') or {}).get('sha256'), 'packet_sha256': None}
    try:
        query['receipt_sha256'] = agent_worker._record(run_dir, receipt['node_id'], receipt['attempt'])['receipt']['sha256']
        # The controller transfers what it observed of this review (verified launch, projection and
        # output) into its own store; the decision reads only that store. Nothing observed, no credit.
        from ravel.workflow import review_dispatch, review_independence
        review_store = review_independence.controller_store(run_dir)
        if review_store is not None:
            review_dispatch.capture_worker_review(review_store, query)
        decided = independence.decide(query)
    except Exception as exc:  # the decision is fail-closed; an error is no credit
        decided = {'independent': False, 'advisory': 'decision_error:' + type(exc).__name__}
    credited = bool(decided.get('independent', decided.get('credited')))
    return {'credited': credited, 'decision': deepcopy(decided),
            'family_relation': decided.get('family_relation'), 'label': decided.get('label'),
            'evidence_boundary': decided.get('evidence_boundary'), 'query': deepcopy(query)}


def _review_closure(store, run_dir, card, decided, credit_id, *, node_id, attempt, packet, qualification,
                    validation):
    """The review rows of one credited (or refused) review: its decision, its review output and its projection."""
    from ravel.workflow import agent_worker, review_dispatch, review_independence, review_projection
    review_store = review_independence.controller_store(run_dir)
    output_id = None
    if review_store is not None and decided.get('query'):
        output_id = next((r.get('_record_id') for r in records(review_store, review_dispatch.REVIEW_KIND)
                          if r.get('binding') == decided['query']), None)
    manifest = None
    if packet:
        try:
            manifest, _ = review_projection.load(packet)
        except (OSError, ValueError, KeyError):
            manifest = None
    receipt = agent_worker.load_receipt(run_dir, node_id, attempt)
    isolation = ((receipt.get('isolation') or {}).get('evidence') or {}).get('confirmed') is True
    errors = (validation or {}).get('errors') or []
    return seat_closure.review_rows(
        card, decided.get('decision'), credit_id=credit_id, review_output_id=output_id, manifest=manifest,
        projection_sha256=(packet or {}).get('manifest_sha256'), qualification_id=qualification,
        isolation_confirmed=isolation, item_problems=[e for e in errors if e.get('code') == 'reviewer_item_verdicts'],
        validation_id=(validation or {}).get('_record_id'))


FOLD_CATEGORIES = {'plan': 'checkin1', 'waypoint': 'checkin2', 'checkin2': 'checkin2', 'final': 'checkin3',
                   'attacks': 'attack', 'integrity': 'integrity'}


def _declared_folds(store, ctx, step):
    """The folded roles the current applied engagement view declares for a derived review seat ``step`` (its role and
    check-in category), or None when no applied view is pinned."""
    try:
        plan = operations.current_plan(store, ctx)
    except StepHold:
        return None
    seats = ((plan.get('engagement') or {}).get('seat_plan') or {}).get('seats')
    if not seats:
        return None
    category = FOLD_CATEGORIES.get((step.get('parameters') or {}).get('purpose'))
    producer = f"producer:{step.get('id')}:{step.get('role')}"  # a plan review step's own seat as a fold target
    return sorted({role for row in seats if not row.get('conditional') and (
        row.get('key') == producer or (category and row.get('role') == step.get('role')
                                       and row.get('category') == category))
        for role in row.get('folded_roles') or ()})


def _fold_row(descriptor, *, credit_id, credited, problems, declared=None):
    """EG04 for one seat: a seat that carries folded roles returns one verdict per folded item under a credited review
    (``problems``: the item-verdict refusals of its record); a seat that carries none is not applicable, reviewed by the
    credit decision of its attempt. ``declared`` lists folded roles the applied view gives this seat when the seat
    itself names no descriptor: such duties never reached the seat, a violation."""
    folded = list((descriptor or {}).get('folded_roles') or [])
    evidence = {'credit': credit_id, 'folded_roles': folded,
                'descriptor_sha256': digest(descriptor) if descriptor is not None else None}
    if not folded and declared:
        return {'status': 'violated', 'evidence': {**evidence, 'folded_roles': list(declared),
                                                    'reason': 'folded_duties_not_delivered:' + ','.join(declared)}}
    if not folded:
        return {'status': 'not_applicable', 'evidence': {**evidence, 'reason': 'not_applicable:seat_carries_no_folded_role'}}
    if not credited:
        return {'status': 'violated', 'evidence': {**evidence, 'reason': 'folded_review_uncredited'}}
    if problems:
        return {'status': 'violated', 'evidence': {**evidence, 'reason': 'folded_item_verdicts:' + str(problems[0])[:300]}}
    return {'status': 'satisfied', 'evidence': {**evidence, 'items': len(descriptor.get('items') or [])}}


def _validation_record(store, seat_key, receipt_sha256):
    return next((r for r in reversed(records(store, VALIDATION))
                 if 'errors' in r and r.get('seat') == seat_key and r.get('receipt_sha256') == receipt_sha256), None)


def credit(state):
    from ravel.workflow import agent_worker, broker
    store, run_dir = _store(state), _run_dir(state)
    results = state.get('results') or {}
    seat_rows, unverified = [], []
    producer_session = (state.get('observation') or {}).get('session_id')
    for item in (state.get('review') or {}).get('seats') or []:
        found = ((results.get(item['key']) or {}).get('results') or {}).get('seat') or {}
        row = {'seat': item['key'], 'role': item['role'], 'status': found.get('status'),
               'verdict': found.get('verdict'), 'receipt_sha256': found.get('receipt_sha256'),
               'session_id': found.get('session_id'), 'credited': False, 'reasons': [],
               'findings': found.get('findings'), 'subject_sha256': found.get('subject_sha256'),
               'attempt': found.get('attempt')}
        if found.get('status') != 'completed':
            row['reasons'].append('seat_' + str(found.get('status')))
        if found.get('session_id') and found.get('session_id') == producer_session:
            row['reasons'].append('seat_reused_producer_session')
        if not found.get('model_matches', False):
            row['reasons'].append('seat_model_mismatch')
        if found.get('attempt') != _attempt(state):
            row['reasons'].append('seat_attempt_mismatch')
        expected = item.get('subject_sha256') or _subject((state.get('checks') or {}).get('accepted') or [])['sha256']
        if found.get('subject_sha256') != expected:
            row['reasons'].append('seat_subject_mismatch')
        if not row['reasons']:
            receipt = agent_worker.load_receipt(run_dir, found['node_id'], found['attempt'])
            decided = _decision(run_dir, found['receipt_sha256'], receipt, found['subject_sha256'])
            row.update(credited=decided['credited'], decision=decided['decision'],
                       family_relation=decided['family_relation'], label=decided['label'],
                       evidence_boundary=decided['evidence_boundary'], query=decided['query'])
            if not decided['credited']:
                row['reasons'].append('independence:' + str(decided['decision'].get('advisory')))
            elif item.get('mode') == BLIND_VERIFICATION:
                verified = _verify_blind(state, store, run_dir, item, found, receipt)
                row['verification'] = {'record': verified['record_id'], 'outcome': verified['outcome']}
                if verified['outcome'] != 'agree':
                    # A disagreement, or a comparison that cannot be made, escalates; it never passes silently.
                    row['credited'] = False
                    row['reasons'].append('verification_' + verified['outcome'])
                    unverified.append({'seat': item['key'], 'escalation': {
                        'kind': 'stop', 'evidence': [verified['record_id']], 'options': None,
                        'record_sha256': digest({k: v for k, v in verified.items() if k != 'record_id'}),
                        'statement': f"the blind verification of {state['step']['id']} by {item['role']} is "
                                     f"{verified['outcome']} against the approved tolerance"}})
        seat_rows.append(row)
    own = None
    if state['acting']['kind'] == 'review' and state['branch'] == 'worker' and _seat(state) is None:
        node_id = state['preflight']['spec']['node_id']
        receipt = agent_worker.load_receipt(run_dir, node_id, _attempt(state))
        subject = digest(sorted(state['preflight'].get('inputs') or []))
        parameters = state['acting'].get('parameters') or {}
        subject = parameters.get('subject_plan_sha256') or parameters.get('subject_sha256') or subject
        own = _decision(run_dir, broker.digest(receipt), receipt, subject)
        own['verdict'] = (state.get('validation') or {}).get('verdict')
        own['findings'] = (state.get('validation') or {}).get('findings')
    verdicts = [r['verdict'] for r in seat_rows]
    record = {'schema_version': 1, 'step_id': state['step']['id'], 'attempt': _attempt(state), 'seats': seat_rows,
              'own': own, 'credited': all(r['credited'] for r in seat_rows) and (own is None or own['credited'])}
    credit_id = store.append(CREDIT, record)
    worst = 'revise' if 'revise' in verdicts else 'unresolved' if 'unresolved' in verdicts else 'accept'
    scientific_errors = []
    if (spec.parameters(state['acting']).get('evidence_requirements')
            and record['credited'] and worst == 'accept' and (own is None or own.get('verdict') == 'accept')):
        from ravel.controller.routes.study import runtime
        scientific_errors = runtime.scientific_checks(store, state['acting'],
            {**_ctx(state), 'run_dir': str(run_dir), 'attempt': _attempt(state),
             'ledger_scope': _ledger_binding(state)[3],
             'review_queries': runtime.scientific_review_queries(store, state['acting'], attempt=_attempt(state))},
            phase='review')
        if scientific_errors:
            custody.accept(store, (state.get('checks') or {}).get('accepted') or [], 'rejected',
                           evidence={'scientific_checks': scientific_errors, 'credit': credit_id})
    evaluations = {}
    if seat_rows or own:
        reused = any('seat_reused_producer_session' in r['reasons'] for r in seat_rows)
        evaluations['I05'] = {'status': 'violated' if reused else 'satisfied',
                              'evidence': {'credit': credit_id,
                                           **({'reason': 'seat_reused_producer_session'} if reused else {})}}
    if own is not None:
        from ravel.controller.routes.study import runtime
        evaluations.update(runtime.review_rows(store, state['acting'], credit_id=credit_id))
        node_id = state['preflight']['spec']['node_id']
        evaluations.update(_review_closure(
            store, run_dir, _card(state), own, credit_id, node_id=node_id, attempt=_attempt(state),
            packet=state['preflight'].get('review_packet'), qualification=state['preflight'].get('qualification_record'),
            validation=_validation_record(store, _seat_key(state), (state.get('observation') or {}).get('receipt_sha256'))))
        descriptor = _declared_descriptor(state)
        problems = []
        if (descriptor or {}).get('folded_roles'):
            path = agent_worker.workspace(run_dir, node_id, _attempt(state)) / 'final.json'
            final = json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else None
            problems = (module('instructions').check_item_verdicts(descriptor.get('items') or [], final)
                        if type(final) is dict else ['final record missing'])
        evaluations['EG04'] = _fold_row(descriptor, credit_id=credit_id, credited=own['credited'], problems=problems,
                                        declared=None if descriptor else _declared_folds(store, _ctx(state), state['acting']))
    elif _seat(state) is None:
        # A producer seat carries no folded review role: its credit decision is the reviewed reason.
        evaluations['EG04'] = _fold_row(None, credit_id=credit_id, credited=record['credited'], problems=[])
    closures = {}
    for item, row in zip((state.get('review') or {}).get('seats') or [], seat_rows):
        found = ((results.get(item['key']) or {}).get('results') or {}).get('seat') or {}
        if 'decision' not in row or not found.get('node_id'):
            continue
        dispatched = next((r for r in records(store, DISPATCH)
                           if (r.get('parent_step') or r.get('step_id')) == state['step']['id']
                           and r.get('seat') == item['key'] and r.get('attempt') == found.get('attempt')), {})
        card, _, _ = cards.resolve(item['role'], {'registry_sha256': state['card']['registry_sha256']})
        decided = {'decision': row['decision'], 'query': row.get('query')}
        validation = _validation_record(store, item['key'], found.get('receipt_sha256'))
        closures[item['key']] = _review_closure(
            store, run_dir, card, decided, credit_id, node_id=found['node_id'], attempt=found['attempt'],
            packet=agent_worker._record(run_dir, found['node_id'], found['attempt']).get('packet'),
            qualification=_qualification_record(store, dispatched.get('selection') or {}),
            validation=validation)
        from ravel.controller.routes.study import runtime
        closures[item['key']].update(runtime.child_review_rows(
            store, state['step'], credit_id=credit_id, seat_key=item['key']))
        # The seat's declared descriptor (the applied view's) carries its folded items; validate checked its verdicts.
        declared = next((r for r in state['step'].get('engagement_seats') or [] if r['role'] == item['role']), None)
        closures[item['key']]['EG04'] = _fold_row(
            declared, credit_id=credit_id, credited=row['credited'],
            problems=[e for e in (validation or {}).get('errors') or () if e.get('code') == 'reviewer_item_verdicts'])
    findings = [row['findings'] for row in seat_rows if row.get('findings')]
    if (own or {}).get('findings'):
        findings.append(own['findings'])
    return {'credit': {'credited': record['credited'], 'seats': seat_rows, 'own': own,
                       'findings': findings, 'record_id': credit_id,
                       'verdict': (own or {}).get('verdict') if own else (worst if seat_rows else None),
                       'seat_closures': closures, 'verification_escalations': unverified, 'scientific_errors': scientific_errors},
            'evaluations': evaluations}


def _verify_blind(state, store, run_dir, item, found, receipt):
    """The controller's comparison of a blind verifier's own value with the producer's result, recorded.

    The quantity, unit and tolerances are the ones the approved plan declares for the step
    (``parameters.verification``); the verifier never saw the producer's value. ``outcome`` is ``agree``,
    ``mismatch`` or ``undecided`` (nothing declared, a value missing or not comparable).
    """
    from ravel.workflow import spawn_rows
    declared = (state['acting'].get('parameters') or {}).get('verification')
    record = {'schema_version': 1, 'step_id': state['step']['id'], 'attempt': _attempt(state), 'seat': item['key'],
              'role': item['role'], 'declared': deepcopy(declared)}
    try:
        if type(declared) is not dict:
            raise ValueError('the approved plan declares no verification for this step')
        adopted = (state.get('adoption') or {}).get('adopted') or []
        producer = next((r for r in adopted if r.get('path') == declared['output']), None)
        if producer is None:
            raise ValueError(f"the declared output {declared['output']} was not adopted")
        mine = [o for o in receipt.get('credited_outputs') or () if o.get('kind') == INDEPENDENT_VALUE]
        if len(mine) != 1:
            raise ValueError('the verifier credited no single independent value')
        # The value the seat adopted under its own sealed spec digest and accepted (never the worker's workspace).
        seat_id = found.get('step_id')  # the seat's own step, the one its adopt node adopted under
        kept = [r for r in custody.custody_index(store).values() if seat_id and r.get('step_id') == seat_id
                and r.get('status') == 'accepted' and r.get('kind') == INDEPENDENT_VALUE
                and r.get('sha256') == mine[0]['sha256']]
        if len(kept) != 1:
            raise ValueError('the seat adopted and accepted no single independent value with the credited bytes')
        independent = {'path': kept[0]['destination'], 'sha256': kept[0]['sha256']}
        record['independent'] = {**independent, 'artifact': kept[0]['artifact']}
        compared = spawn_rows.compare_outputs(
            run_dir, {'path': producer['destination'], 'sha256': producer['sha256']}, independent,
            pointer=declared['pointer'], unit=declared['unit'], relative_tolerance=declared['relative_tolerance'],
            absolute_tolerance=declared.get('absolute_tolerance', 0))
        record.update(comparison=compared, outcome='agree' if compared['passed'] else 'mismatch')
    except (StepHold, OSError, ValueError, KeyError, TypeError) as exc:
        record.update(outcome='undecided', reason=f'{type(exc).__name__}: {exc}'[:300])
    return {**record, 'record_id': store.append(VERIFICATION, record)}


# ---- ledger, escalation and finish -----------------------------------------------------------

def _instance_key(row, run_id, scope):
    try:
        from ravel.controller.ledger.state import instance_key
    except ImportError:
        from urllib.parse import quote
        parts = [f"{row}@{quote(run_id, safe='-_.~:+#')}"]
        for name in ('step', 'point', 'seat', 'attempt'):
            if scope.get(name) is not None:
                parts.append(f"{name}={quote(str(scope[name]), safe='-_.~:+#')}")
        return '/'.join(parts)
    return instance_key(row, run_id, scope)


def _ledger_binding(state):
    ctx = _ctx(state)
    attempt = _attempt(state)
    seat_info = _seat(state)
    seat = _seat_key(state) or 'producer'
    point = ctx.get('point')
    scope_step = {'step': state['step']['id']}
    scope_seat = {**scope_step, 'point': point, 'seat': seat, 'attempt': attempt}
    stage = 'review' if seat_info is not None or state['acting']['kind'] == 'review' else 'dispatch'
    context = {**scope_seat, 'run_id': ctx.get('run_id'),
               # A parent request runs no card: its seat is the plan's declared role for the step, which decides it.
               'role': (state.get('card') or {}).get('id') or (
                   state['acting'].get('role') if state.get('branch') == 'parent' else None),
               'seat_kind': seat_info['purpose'] if seat_info else ('review' if stage == 'review' else state['branch']),
               'review_kind': (seat_info or {}).get('review_kind') or
                              (state['acting'].get('parameters') or {}).get('review_kind') or
                              ('consult' if seat_info and seat_info['purpose'] == 'consult' else
                               'critic' if stage == 'review' else None),
               'step_kind': state['acting']['kind']}
    return stage, context, scope_step, scope_seat


def seat_materialise(state):
    """Pin a seat's own denominator before its worker starts; do not credit any duty."""
    return ledger_update({**state, 'evaluations': {}})


def after_seat_materialise(state):
    return 'finish' if (state.get('ledger') or {}).get('refused') else 'packet'


def ledger_update(state):
    """Record this seat's evaluated mechanisms; a ledger refusal fails the attempt."""
    store, ctx = _store(state), _ctx(state)
    ledger = module('ledger')
    evaluations = dict(state.get('evaluations') or {})
    stage, context, scope_step, scope_seat = _ledger_binding(state)
    seat_info = _seat(state)
    # A review seat the controller derives for a check-in is bound by its subject plan, not as a plan step:
    # like a child seat it has no plan-stage instances of its own, only its seat's.
    derived = (state.get('preflight') or {}).get('binding') == 'derived_review_seat'
    seat, attempt = scope_seat['seat'], scope_seat['attempt']
    recorded, refused = [], []
    materialised = []

    def refuse(exc, **detail):
        refused.append({'code': getattr(exc, 'code', type(exc).__name__), 'reason': str(exc), **detail})

    try:
        dispatched = state.get('preflight') or {}
        materialised = (list(dispatched['instruction_entries']) if 'instruction_entries' in dispatched
                        else list(ledger.materialise(store, stage, context) or []))
    except Exception as exc:
        if not isinstance(exc, (ValueError, KeyError, getattr(ledger, 'LedgerError', ValueError))):
            raise
        refuse(exc, stage=stage, context=context)
    catalogue = ledger.load_catalogue() if not refused and hasattr(ledger, 'load_catalogue') else None
    by_row = {}
    for entry in materialised:
        by_row.setdefault(str(entry).split('@', 1)[0], []).append(entry)
    if not refused:
        for row, value in sorted(evaluations.items()):
            if value.get('instruction_recorded'):
                continue  # P03 has already appended this immutable discharge; never replay a violation.
            definition = catalogue.rows.get(row) if catalogue else None
            if definition and definition['node'].split('[', 1)[0] in plan_binding.PLAN_BIND_NODES:
                continue  # recorded by the controller when it bound the plan; verified at preflight, never written here
            # Instruction acknowledgements belong to the observed-completion discharge.
            if (definition and definition['class'] == 'I') or row == 'CF01' or (
                    row.startswith('ROLE-') and any(tag in row for tag in ('-escalation-', '-protocol-', '-purpose'))):
                continue
            keys = by_row.get(row)
            if keys is None:
                if seat_info is not None or derived:
                    continue  # a child or derived seat never writes plan-scope facts
                if catalogue:
                    if not definition or definition['applicability']['scope'] != 'step':
                        continue  # a selector excludes this execution branch or this role
                    keys = [_instance_key(row, ctx.get('run_id') or '', scope_step)]
                else:
                    keys = [_instance_key(row, ctx.get('run_id') or '', scope_seat),
                            _instance_key(row, ctx.get('run_id') or '', scope_step)]
            for entry in keys:
                payload = {'node': 'controller.seat' if seat_info else 'controller.step',
                           **(value.get('evidence') or {})}
                try:
                    ledger.record(store, entry, value['status'], payload)
                    recorded.append({'entry': entry, 'status': value['status']})
                    break
                except Exception as exc:
                    # A legacy interface fake uses KeyError for an absent candidate.
                    # Every real LedgerError is preserved, including an unknown entry.
                    if isinstance(exc, KeyError) and row not in by_row:
                        continue
                    if not isinstance(exc, (ValueError, KeyError, getattr(ledger, 'LedgerError', ValueError))):
                        raise
                    refuse(exc, entry=entry, row=row, status=value['status'], evidence=payload)
                    break
    # A child review seat's review rows close on the parent's credit decision, after the seat's own update; only
    # the seat's own pending instances are recorded (an interface fake without read access records none).
    closures = (state.get('credit') or {}).get('seat_closures') or {}
    current = getattr(ledger, 'current', None)
    if not refused and seat_info is None and closures and callable(current):
        open_keys = {r['entry'] for r in current(store, step=state['step']['id']) if r['status'] == 'pending'}
        for seat_key, rows in sorted(closures.items()):
            scope = {'step': state['step']['id'], 'point': ctx.get('point'), 'seat': seat_key, 'attempt': attempt}
            for row, value in sorted(rows.items()):
                entry = _instance_key(row, ctx.get('run_id') or '', scope)
                if entry not in open_keys:
                    continue
                payload = {'node': 'controller.seat', **(value.get('evidence') or {})}
                try:
                    ledger.record(store, entry, value['status'], payload)
                    recorded.append({'entry': entry, 'status': value['status']})
                except Exception as exc:
                    if not isinstance(exc, (ValueError, KeyError, getattr(ledger, 'LedgerError', ValueError))):
                        raise
                    refuse(exc, entry=entry, row=row, status=value['status'], evidence=payload)
    if refused:
        store.append('step-ledger-refused', {'step_id': state['step']['id'], 'seat': seat,
                                              'attempt': attempt, 'rows': refused})
    return {'ledger': {'recorded': len(recorded), 'unmaterialised': 0,
                       'materialised': len(materialised), 'refused': refused}}


def _seat_escalations(state):
    """``(seat key, escalations)`` each review seat's worker raised; its seat graph only validates them."""
    results = state.get('results') or {}
    found = []
    for item in (state.get('review') or {}).get('seats') or []:
        seat = ((results.get(item['key']) or {}).get('results') or {}).get('seat') or {}
        if seat.get('escalations'):
            found.append((item['key'], seat['escalations']))
    return found


def _escalation_occurrence(state, store, seat_key, role):
    """An escalation occurred at this seat: its occurrence instantiates the escalation check-in and the seat
    role's escalation duties (CF01, ``ROLE-<role>-escalation-*``), which exist only when an escalation occurs.

    Returns the ledger's refusal (``[]`` when the occurrence was stated); a refusal fails the attempt.
    """
    ledger = module('ledger')
    step_id, attempt = state['step']['id'], _attempt(state)
    context = {'kind': 'escalation', 'id': f'escalation:{step_id}:{seat_key or "producer"}:{attempt}', 'step': step_id,
               'role': role}
    try:
        ledger.materialise(store, 'event', context)
    except Exception as exc:
        if not isinstance(exc, (ValueError, KeyError, getattr(ledger, 'LedgerError', ValueError))):
            raise
        refused = [{'code': getattr(exc, 'code', type(exc).__name__), 'reason': str(exc)[:500], 'stage': 'event',
                    'context': context}]
        store.append('step-ledger-refused', {'step_id': step_id, 'seat': seat_key, 'attempt': attempt, 'rows': refused})
        return refused
    return []


def escalation_node(state):
    """Act on the producer's escalations and on those of every review seat (CF01 for reviewers too)."""
    store = _store(state)
    found = (state.get('validation') or {}).get('escalations') or []
    adopted = (state.get('checks') or {}).get('accepted') or []
    refused = []
    if found:
        refused += _escalation_occurrence(state, store, _seat_key(state), (state.get('card') or {}).get('id'))
    handled = escalations.handle(store, step=state['step'], attempt=_attempt(state), seat=_seat_key(state),
                                 escalations=found, adopted=adopted)
    for key, rows in _seat_escalations(state):
        refused += _escalation_occurrence(state, store, key, next(
            (i['role'] for i in (state.get('review') or {}).get('seats') or () if i['key'] == key), None))
        seat = escalations.handle(store, step=state['step'], attempt=_attempt(state), seat=key, escalations=rows,
                                  adopted=adopted)
        kinds = [{'kind': k} for k in (handled['escalation'], seat['escalation']) if k is not None]
        handled = {'escalation': validate.primary(kinds), 'replan': handled['replan'] or seat['replan'],
                   'flags': handled['flags'] + seat['flags'], 'records': handled['records'] + seat['records'],
                   'halts': handled['halts'] or seat['halts']}
    # The controller's own escalation of a blind verification that disagrees or cannot be decided.
    for row in (state.get('credit') or {}).get('verification_escalations') or ():
        seat = escalations.handle(store, step=state['step'], attempt=_attempt(state), seat=row['seat'],
                                  escalations=[row['escalation']], adopted=adopted)
        kinds = [{'kind': k} for k in (handled['escalation'], seat['escalation']) if k is not None]
        handled = {'escalation': validate.primary(kinds), 'replan': handled['replan'] or seat['replan'],
                   'flags': handled['flags'] + seat['flags'], 'records': handled['records'] + seat['records'],
                   'halts': handled['halts'] or seat['halts']}
    if refused:  # an escalation whose duties the ledger could not instantiate fails the attempt
        ledger = state.get('ledger') or {}
        return {'escalation': handled, 'ledger': {**ledger, 'refused': list(ledger.get('refused') or []) + refused}}
    return {'escalation': handled}


def _status_of(state):
    validation = state.get('validation') or {}
    handled = state.get('escalation') or {}
    refused = (state.get('ledger') or {}).get('refused') or []
    if refused:
        return 'failed', 'ledger_refused:' + refused[0]['code']
    if state['branch'] == 'parent':
        # No worker ran: the step escalates its request to the controller graph (``parent_request``).
        return 'escalated', state['acting']['kind']
    if handled.get('halts'):
        return 'escalated', handled['escalation']
    if validation.get('held'):
        code = validation['held'][0]['code']
        return _hold_status(code), code
    if not validation.get('passed', False):
        codes = [e['code'] for e in validation.get('errors') or ()]
        return 'failed', ','.join(codes) or 'validation_failed'
    adoption = state.get('adoption') or {}
    if adoption.get('refused'):
        return 'failed', 'adoption_refused:' + adoption['refused']
    if not (state.get('checks') or {}).get('passed', True):
        from ravel.controller.recovery import INPUT_INCONCLUSIVE
        failing = [r for r in (state.get('checks') or {}).get('results') or ()
                   if type(r) is dict and r.get('status') not in ('passed', 'not_applicable')]
        if failing and all(r.get('status') == 'inconclusive' and r.get('reason') in INPUT_INCONCLUSIVE for r in failing):
            # Every validator that did not pass lacked an input: a recoverable reason, not a failed check.
            return 'failed', 'validators_inconclusive:' + failing[0]['reason']
        return 'failed', 'validators_failed'
    credit_info = state.get('credit') or {}
    if credit_info.get('scientific_errors'):
        return 'held', 'scientific_evidence_unresolved'
    reviewed = credit_info.get('seats') or credit_info.get('own')
    if reviewed and not credit_info.get('credited'):
        return 'held', 'review_uncredited'
    verdict = credit_info.get('verdict')
    if verdict in ('revise', 'unresolved'):
        findings = credit_info.get('findings') or []
        pointer = ','.join(findings) if isinstance(findings, list) else str(findings)
        return ('revise' if verdict == 'revise' else 'held'), 'review_' + verdict + ':' + (pointer or 'findings_missing')
    return 'completed', None


def _request_options(judgment):
    """The approved plan step's own answer options ``{id, description}`` (``reject`` is every request's own)."""
    return [{'id': o['id'], 'description': ' '.join(str(o.get('description') or o.get('text') or o['id']).split())[:500]}
            for o in judgment.get('options') or () if type(o) is dict and type(o.get('id')) is str
            and o['id'] and o['id'].lower() != 'reject']


def _parent_request(state, attempt, outcome):
    """The typed request a parent step (``ask``, ``route``) passes up, from the approved plan step's bytes only.

    An ``ask`` carries its question, the plan step's options and the P7 default option (only when the plan states
    a P7 ``default`` record for it); a ``route`` carries its route, scope, the budget the plan states for it and
    the child's context lineage. Neither reads a worker: none ran. The controller graph's ``parent_request``
    consumes it and holds, typed, a question without options or a route without its bound child.
    """
    acting, kind = state['acting'], state['acting']['kind']
    judgment = spec.parameters(acting).get('judgment') or {}
    selection = (state.get('preflight') or {}).get('selection') or {}
    request = {'kind': kind, 'status': 'escalated', 'escalation': kind,
               'judgments': deepcopy(outcome.get('judgments') or []),
               # The dispatched tier, only when a selection was made for this attempt.
               'tier': (selection.get('tier') or ((_card(state) or {}).get('model') or {}).get('tier'))
               if selection else None}
    if kind == 'ask':
        options = _request_options(judgment)
        default = judgment.get('default_option') if judgment.get('default') else None
        request.update(question=acting.get('question'), options=options,
                       default=default if default in {o['id'] for o in options} else None)
    else:
        share = acting.get('budget_share')
        if share is None and 'budget_fraction' in judgment:
            share = {'fraction': judgment['budget_fraction']}
        request.update(route=acting.get('route'), scope={'step_id': acting['id'], 'attempt': attempt},
                       budget={'budget': deepcopy(acting.get('budget') or {}), 'budget_share': deepcopy(share)},
                       lineage={'parent_plan_sha256': _ctx(state).get('plan_sha256'),
                                'parent_step_id': state['step']['id'], 'attempt': attempt})
    return request


def _parent_rows(state, store):
    """A parent request (``ask``, ``route``) runs no worker, packet, reservation or launch: its seat's still-pending rows
    are recorded not applicable with that typed reason, so the step a controller answer or a bound child completes
    leaves nothing pending that could never be discharged. Returns ``{'recorded': [...], 'refused': [...]}``."""
    ledger = module('ledger')
    if not all(callable(getattr(ledger, name, None)) for name in ('materialise', 'current', 'record')):
        return {'recorded': [], 'refused': []}
    stage, context, _, scope_seat = _ledger_binding(state)
    kind = state['acting']['kind']
    try:
        keys = set(ledger.materialise(store, stage, context) or [])
    except Exception as exc:  # the ledger's refusal stays visible on the outcome
        return {'recorded': [], 'refused': [{'code': type(exc).__name__, 'reason': str(exc)[:500]}]}
    recorded, refused = [], []
    for row in ledger.current(store, step=state['step']['id']):
        if row['entry'] not in keys or row['status'] != 'pending':
            continue
        evidence = {'reason': f'not_applicable:parent_request:{kind}', 'mechanism': 'step.finish',
                    'request': kind, 'step_id': state['step']['id'], 'attempt': scope_seat['attempt'],
                    'detail': 'a parent request runs no worker, packet, reservation or launch'}
        try:
            ledger.record(store, row['entry'], 'not_applicable', evidence)
            recorded.append(row['entry'])
        except Exception as exc:  # a row the ledger will not mark not applicable stays pending, named here
            refused.append({'entry': row['entry'], 'code': type(exc).__name__, 'reason': str(exc)[:300]})
    return {'recorded': recorded, 'refused': refused}


def finish(state):
    store = _store(state)
    status, reason = _status_of(state)
    attempt = _attempt(state)
    parent_rows = _parent_rows(state, store) if state['branch'] == 'parent' else None
    key = (state.get('reservation') or {}).get('key')
    if key and (state['branch'] == 'parent' or ((state.get('ledger') or {}).get('refused') and
                                               not (state.get('worker') or state.get('launch') or state.get('child')))):
        budget.settle(store, key, status='released', evidence={'reason': reason or 'parent_kind'})
    validation = state.get('validation') or {}
    handled = state.get('escalation') or {}
    accepted = (state.get('checks') or {}).get('accepted') or []
    observation = state.get('observation') or {}
    measured = observation.get('measured') or {}
    seat = _seat(state)
    outcome = {'step_id': state['acting']['id'] if seat else state['step']['id'], 'attempt': attempt, 'status': status,
               # ``path`` is the plan path; ``destination`` is where custody adopted the bytes in the run directory.
               'outputs': [{'artifact': r['artifact'], 'path': r['path'], 'destination': r.get('destination'),
                            'sha256': r['sha256'], 'artifact_id': r.get('artifact_id'), 'attempt': r.get('attempt'),
                            'record_id': r.get('record_id')} for r in accepted],
               'receipts': [x for x in (observation.get('receipt_sha256') or (state.get('launch') or {}).get('journal_id'),) if x],
               'escalation': handled.get('escalation') or (state['acting']['kind'] if state['branch'] == 'parent' else None),
               'replan': deepcopy(handled.get('replan')),
               'budget': {k: v for k, v in measured.items() if type(v) in (int, float)},
               'judgments': deepcopy(validation.get('judgments') or []), 'review': {}, 'reason': reason,
               'model': deepcopy(validation.get('model')), 'reservation_key': key,
               'subject_sha256': _subject(accepted)['sha256']}
    if state['branch'] == 'parent':
        outcome['request'] = _parent_request(state, attempt, outcome)
        outcome['parent_rows'] = parent_rows
    credit_info = state.get('credit') or {}
    if credit_info:
        outcome['review'] = {'credited': credit_info.get('credited'), 'verdict': credit_info.get('verdict'),
                             'seats': deepcopy(credit_info.get('seats')), 'findings': deepcopy(credit_info.get('findings') or []),
                             'record_id': credit_info.get('record_id')}
        reviewed = credit_info.get('seats') or credit_info.get('own')
        if reviewed and not credit_info.get('credited') and status == 'completed':
            outcome['status'], outcome['reason'] = 'held', 'review_uncredited'
    if validation.get('labels'):
        outcome['labels'] = deepcopy(validation['labels'])
    if state.get('ledger'):
        outcome['ledger'] = deepcopy(state['ledger'])
    if _pilot(state):
        return _finish_pilot(state, store, outcome)
    if seat is not None:
        from ravel.workflow import agent_worker
        node_id = (state.get('preflight') or {}).get('spec', {}).get('node_id')
        record = None
        if node_id and status == 'completed':
            path = agent_worker.workspace(_run_dir(state), node_id, attempt) / 'final.json'
            record = json.loads(path.read_text()) if path.is_file() else None
        dispatched = next((r for r in records(store, DISPATCH) if r.get('key') == (state.get('preflight') or {}).get(
            'dispatch_key')), {})
        receipt = agent_worker.load_receipt(_run_dir(state), node_id, attempt) if node_id else {}
        outcome.update({'seat': seat['key'], 'role': seat['role'], 'purpose': seat['purpose'],
                        'node_id': node_id, 'receipt_sha256': observation.get('receipt_sha256'),
                        'session_id': observation.get('session_id'), 'subject_sha256': seat['subject']['sha256'],
                        'verdict': validation.get('verdict'), 'record': record, 'findings': validation.get('findings'),
                        'escalations': deepcopy(validation.get('escalations') or []),
                        'model_matches': seats.model_check(_card(state), dispatched, receipt)['matches'] if node_id else False})
        custody.record_outcome(store, {'id': outcome['step_id']}, attempt, status, seat=seat['key'], reason=reason,
                               outcome={k: v for k, v in outcome.items() if k != 'record'})
        return {'outcome': outcome, 'results': {'seat': outcome},
                'status': {'phase': 'finish', 'terminal': None, 'reason': status, 'would_make_possible': None}}
    outcome = operations.observe_route(state['step'], outcome,
        operations.route_context(store, {**_ctx(state), 'run_dir': _run_dir(state)}))
    custody.record_outcome(store, state['step'], attempt, outcome['status'], reason=outcome['reason'],
                           outputs=outcome['outputs'], escalation=outcome['escalation'], outcome=outcome)
    return {'outcome': outcome, 'results': {'step': outcome},
            'status': {'phase': 'finish', 'terminal': None, 'reason': status, 'would_make_possible': None}}


def _finish_pilot(state, store, outcome):
    """A derived pilot's outcome under its own identity; only a validated, cleanly exited launch calibrates."""
    launch = state.get('launch') or {}
    outcome['step_id'] = state['acting']['id']
    outcome['seat'] = budget.PILOT_RUNG
    # Validation passed; the pilot is not adopted, so its declared required outputs are checked here.
    present = {row.get('path') for row in launch.get('inventory') or ()}
    missing = [row['plan_path'] for row in (state.get('preflight') or {}).get('outputs') or ()
               if row.get('required', True) and not {row['plan_path'], row['plan_path'].removeprefix('outputs/')}
               & present]
    clean = (outcome['status'] == 'completed' and launch.get('exit_status') == 0 and not launch.get('timed_out')
             and not launch.get('confinement_errors') and type(launch.get('wall_seconds')) in (int, float)
             and not missing)
    if outcome['status'] == 'completed' and not clean:
        outcome['status'] = 'failed'
        outcome['reason'] = 'pilot_outputs_missing:' + ','.join(missing) if missing else 'pilot_launch_unclean'
    if clean:
        outcome['calibration'] = budget.record_calibration(store, state['acting'], status='succeeded', measured={
            'wall_seconds': launch['wall_seconds'], 'events': state['acting']['budget']['events'],
            'journal': launch.get('finished_id')})
    custody.record_outcome(store, {'id': state['acting']['id']}, outcome['attempt'], outcome['status'],
                           seat=budget.PILOT_RUNG, reason=outcome['reason'], outcome=deepcopy(outcome))
    return {'outcome': outcome, 'results': {'step': outcome},
            'status': {'phase': 'finish', 'terminal': None, 'reason': outcome['status'], 'would_make_possible': None}}


# ---- holds and decisions ---------------------------------------------------------------------

def _hold_status(reason):
    if reason in BUDGET_HOLDS:
        return 'budget_exhausted'
    if reason in STOP_HOLDS:
        return 'stopped'
    return 'held'


def hold_node(graph_id):
    """The builder's own hold: a typed status, the refusal in the store and a held outcome."""
    def body(state):
        status = dict(state.get('status') or {})
        if status.get('phase') not in ('handler', 'decision'):
            status = {'phase': 'hold', 'terminal': 'hold', 'reason': 'controller_step_hold', 'would_make_possible': None}
        reason = status.get('reason') or 'controller_step_hold'
        if status.get('phase') == 'decision':
            failure = next(reversed((state.get('failures') or {}).values()), {}) if state.get('failures') else {}
            reason = failure.get('error_type') or reason
            status = {'phase': 'hold', 'terminal': 'hold', 'reason': reason,
                      'would_make_possible': failure.get('message')}
        try:
            _record_hold(state, reason, status.get('would_make_possible'))
        except StepHold:
            pass
        status['phase'] = 'hold'
        return {'status': status}
    body.__name__ = 'hold_' + graph_id.replace('.', '_')
    return nodes.Node('hold', body, then=nodes.END)


def _record_hold(state, reason, detail):
    ctx = _ctx(state)
    if not ctx.get('run_id'):
        return
    store = _store(state)
    step = state.get('step') or {}
    if not step.get('id'):
        return
    attempt = spec.attempt(ctx)
    key = (state.get('reservation') or {}).get('key')
    if key:
        started = bool(state.get('worker') or state.get('launch') or state.get('child'))
        measured, usage_record = subgraph_usage.measurement(store, state.get('acting') or step, attempt)
        usage_started = any(r.get('binding') == subgraph_usage.binding(store, state.get('acting') or step, attempt)
                            for r in records(store, subgraph_usage.SESSION))
        budget.settle(store, key, status='settled' if started or usage_started else 'released', measured=measured,
                      evidence={'hold': reason, 'subgraph_usage': usage_record})
    marker = digest({'step': step['id'], 'attempt': attempt, 'seat': _seat_key(state), 'reason': reason})
    if any(r.get('marker') == marker for r in records(store, REFUSAL)):
        return
    store.append(REFUSAL, {'schema_version': 1, 'marker': marker, 'step_id': step['id'], 'attempt': attempt,
                           'seat': _seat_key(state), 'reason': reason, 'detail': detail})
    outcome_status = _hold_status(reason)
    outcome = {'step_id': step['id'], 'attempt': attempt, 'status': outcome_status, 'outputs': [], 'receipts': [],
               'escalation': None, 'replan': None, 'budget': {}, 'judgments': [], 'review': {}, 'reason': reason,
               'detail': detail}
    if _pilot(state):
        pilot = budget.pilot_id(step['id'])
        custody.record_outcome(store, {'id': pilot}, attempt, outcome_status, reason=reason, seat=budget.PILOT_RUNG,
                               outcome={**outcome, 'step_id': pilot})
    elif _seat(state) is None:
        custody.record_outcome(store, step, attempt, outcome_status, reason=reason, detail=detail, outcome=outcome)
    else:
        custody.record_outcome(store, {'id': f"{step['id']}:{_seat_key(state)}"}, attempt, outcome_status, reason=reason,
                               seat=_seat_key(state), outcome=outcome)


def _decide(state, failure):
    """Route a typed failure: a dispatch that closed with a receipt is observed; a refusal holds; others end."""
    if failure.get('node') == 'dispatch' and failure.get('error_type') in ('ReceiptedFailure', 'CallFailed'):
        return 'observe'
    if failure.get('error_type') in ('SeatRefused', 'LaunchRefused', 'ToolbeltError', 'MaterializeRefused'):
        return 'hold'
    return 'abort'


def abort(state):
    """An unexpected failure ends the attempt as failed; its reservation stays charged."""
    failure = next(reversed((state.get('failures') or {}).values()), {}) if state.get('failures') else {}
    store = _store(state)
    step = state['step']
    attempt = _attempt(state)
    reason = 'exception:' + str(failure.get('error_type'))
    outcome = {'step_id': step['id'], 'attempt': attempt, 'status': 'failed', 'outputs': [], 'receipts': [],
               'escalation': None, 'replan': None, 'budget': {}, 'judgments': [], 'review': {}, 'reason': reason,
               'detail': (failure.get('message') or '')[:2000]}
    key = (state.get('reservation') or {}).get('key')
    if key and not (state.get('worker') or state.get('launch')):
        budget.settle(store, key, status='released', evidence={'abort': reason})
    seat_key = _seat_key(state)
    custody.record_outcome(store, step if seat_key is None else {'id': f"{step['id']}:{seat_key}"}, attempt,
                           'failed', reason=reason, outcome=outcome, **({'seat': seat_key} if seat_key else {}))
    channel = 'seat' if _seat(state) is not None else 'step'
    return {'outcome': outcome, 'results': {channel: outcome},
            'status': {'phase': 'abort', 'terminal': None, 'reason': reason, 'would_make_possible': None}}


# ---- builders --------------------------------------------------------------------------------

def _native_authority_context(state):
    return {**_ctx(state), 'attempt': _attempt(state),
            'plan_sha256': state['preflight']['plan_sha256'],
            'reservation': deepcopy(state.get('reservation') or {})}


def native_authority_point(state):
    """An exact native R3 request pauses; every resume only polls current authenticated state."""
    import math
    from langgraph.types import interrupt as pause
    from ravel.workflow import graph_registry
    from . import native_authority
    polls = 0
    while True:
        try:
            prepared = native_authority.prepare(_store(state), state['acting'],
                _native_authority_context(state), state['preflight'])
            if (type(prepared) is not dict or type(prepared.get('action')) is not dict
                    or prepared.get('class') not in ('R0', 'R1', 'R2', 'R3')):
                raise ValueError('native preparation returned no exact action/class')
            if 'pending' not in prepared:
                return {'native_authority': deepcopy(prepared)}
            pending = prepared['pending']
            if (type(pending) is not dict or pending.get('kind') != 'r3_action'
                    or type(pending.get('request')) is not str or not pending['request']
                    or type(pending.get('since_ns')) is not int or pending['since_ns'] <= 0
                    or any(type(pending.get(key)) not in (int, float) or not math.isfinite(pending[key])
                           or pending[key] < 0 for key in ('waited_seconds', 'wait_bound_seconds'))):
                raise ValueError('native authority returned malformed pending request')
            waited = max(pending['waited_seconds'], (time.time_ns() - pending['since_ns']) / 1e9)
            if polls >= 64 or (_ctx(state).get('unattended') and waited >= pending['wait_bound_seconds']):
                raise ValueError('native authority remains pending beyond the bounded wait')
            store = _store(state)
        except (StepHold, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            detail = exc.would_make_possible if isinstance(exc, StepHold) else str(exc)
            raise StepHold('native_authority_refused', str(detail)[:1500]) from None
        pause({'kind': 'controller_authority', 'schema_id': 'controller_authority', 'graph_id': GRAPH_ID,
               'node': 'native_authority', 'authority_kind': 'r3_action', 'pending': deepcopy(pending),
               'approval_from_resume': False, 'operator_answer': {
                   'command': f"ravel operator answer --run {store.run_id} --request {pending['request']} "
                              '--code <code> --decision admit',
                   'terminal_identity_attested': False}},
              response_schema=graph_registry.response_schema('controller_authority'))
        polls += 1


def native_authority_gate(state):
    """Replay exact prepared identity and the real all-provider launch decision before proceeding."""
    from . import launch_gate
    action, decision, errors = None, None, []
    try:
        action = launch_gate.action(state['acting'], _native_authority_context(state),
                                   state['preflight'], state['preflight'].get('native_preflight'))
        prepared = state.get('native_authority')
        if type(prepared) is not dict or prepared.get('action') != action or 'pending' in prepared:
            raise ValueError('native authority preparation does not name this exact current action')
        _authorize(_store(state), _ctx(state), state['acting'], state['reservation']['amounts'],
                   stage=state['preflight'].get('stage'))
        decision = _native_launch_decision(state)
    except (StepHold, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        errors = [{'code': exc.reason if isinstance(exc, StepHold) else 'native_authority_refused',
                   'message': str(exc.would_make_possible if isinstance(exc, StepHold) else exc)[:1500]}]
        if isinstance(exc, StepHold) and (exc.evidence or {}).get('record'):
            decision = {'record': exc.evidence['record']}
    checked = {'errors': errors, 'action_digest': action['digest'] if action else None,
               'record': decision['record'] if decision else None}
    result = {'gates': {'native_authority': checked}}
    if errors:
        result['status'] = {'phase': 'handler', 'terminal': 'hold', 'reason': 'native_authority_refused',
                            'would_make_possible': errors[0]['message']}
    return result


def _common(builder, graph_id):
    add = lambda name, node: nodes.add(builder, name, node, graph_id=graph_id)  # noqa: E731
    add('decision_turn', nodes.decision_turn(graph_id, router=_decide,
                                             path_map={'observe': 'observe', 'hold': 'hold', 'abort': 'abort'}))
    add('reconcile', nodes.reconcile_node())
    add('hold', hold_node(graph_id))
    add('abort', nodes.Node('effect', abort, then=nodes.END))
    return add


def build_seat(ctx):
    """``controller.seat``: one review or consult seat of a step."""
    from langgraph.graph import END, START, StateGraph
    builder = StateGraph(State, input_schema=SeatView)
    add = _common(builder, SEAT_GRAPH)
    add('reserve', nodes.Node('effect', reserve, then='materialise'))
    add('materialise', nodes.Node('effect', seat_materialise, then=nodes.route(
        after_seat_materialise, {'packet': 'packet', 'finish': 'finish'})))
    add('packet', nodes.Node('effect', packet, then='preflight'))
    add('preflight', nodes.Node('effect', preflight, then='dispatch'))
    dispatch_node = _dispatch_node()
    dispatch_node.kind = 'agent'
    add('dispatch', dispatch_node)
    add('observe', nodes.Node('effect', observe, then='validate'))
    add('validate', nodes.Node('effect', validate_node, then=nodes.route(
        after_validate, {'adopt': 'adopt', 'ledger_update': 'ledger_update'})))
    add('adopt', nodes.Node('effect', seat_adopt, then='ledger_update'))
    add('ledger_update', nodes.Node('effect', ledger_update, then='finish'))
    add('finish', nodes.Node('effect', finish, then=END))
    builder.add_edge(START, 'reserve')
    builder.add_edge('dispatch', 'observe')
    return builder


def build(ctx):
    """``controller.step``: the governed step graph (see the module docstring)."""
    from langgraph.graph import END, START, StateGraph
    from ravel.workflow import graph_substrate
    builder = StateGraph(State, input_schema=View)
    add = _common(builder, GRAPH_ID)
    seat_graph = graph_substrate.build(SEAT_GRAPH, ctx, checkpointer=None)
    add('reserve', nodes.Node('interrupt', reserve_point, then='cost_authority', interrupt_kind='controller_authority'))
    add('cost_authority', nodes.Node('gate', cost_authority, gate='cost_authority',
        then=nodes.gate_route('cost_authority', passed='packet', refused='hold')))
    add('packet', nodes.Node('effect', packet, then='preflight'))
    add('preflight', nodes.Node('effect', preflight, then=nodes.route(
        after_preflight, {'consult': 'consult_fanout', 'dispatch': 'dispatch', 'native_authority': 'native_authority',
                          'subgraph': 'subgraph', 'finish': 'finish'})))
    consult_edge, consult_map = nodes.map_node(consult_items, lambda item: item['key'], seat_graph,
                                               lambda state, item: {'step': deepcopy(state['step']),
                                                                    'context': deepcopy(state['context']),
                                                                    'seat': deepcopy(item)}, name='consult')
    add('consult_fanout', nodes.Node('effect', lambda state: {}, then=consult_edge))
    add('consult', consult_map)
    add('consult_join', nodes.Node('effect', consult_join, then='packet'))
    dispatch_node = _dispatch_node()
    dispatch_node.kind = 'agent'
    add('dispatch', dispatch_node)
    add('native_authority', nodes.Node('interrupt', native_authority_point, then='native_authority_gate',
        interrupt_kind='controller_authority'))
    add('native_authority_gate', nodes.Node('gate', native_authority_gate, gate='native_authority',
        then=nodes.gate_route('native_authority', passed='launch', refused='hold')))
    add('launch', _launch_node())
    add('subgraph', nodes.Node('subgraph', lambda state: subgraph(
        state, node_runner=ctx.extras.get('node_runner'))))
    add('observe', nodes.Node('effect', observe, then='validate'))
    add('validate', nodes.Node('effect', validate_node, then=nodes.route(
        after_validate, {'adopt': 'adopt', 'ledger_update': 'ledger_update'})))
    add('adopt', nodes.Node('effect', adopt, then=nodes.route(
        after_adopt, {'checks': 'checks', 'ledger_update': 'ledger_update'})))
    add('checks', nodes.Node('effect', checks, then=nodes.route(
        after_checks, {'review': 'review', 'ledger_update': 'ledger_update'})))
    add('review', nodes.Node('effect', review, then=nodes.route(
        after_review, {'fanout': 'review_fanout', 'credit': 'credit'})))
    review_edge, review_map = nodes.map_node(review_items, lambda item: item['key'], seat_graph,
                                             lambda state, item: {'step': deepcopy(state['step']),
                                                                  'context': deepcopy(state['context']),
                                                                  'seat': deepcopy(item)}, name='seats')
    add('review_fanout', nodes.Node('effect', lambda state: {}, then=review_edge))
    add('seats', review_map)
    add('credit', nodes.Node('effect', credit, then='ledger_update'))
    add('ledger_update', nodes.Node('effect', ledger_update, then='escalation'))
    add('escalation', nodes.Node('effect', escalation_node, then='finish'))
    add('finish', nodes.Node('effect', finish, then=END))
    builder.add_edge(START, 'reserve')
    builder.add_edge('consult', 'consult_join')
    builder.add_edge('dispatch', 'observe')
    builder.add_edge('launch', 'observe')
    builder.add_edge('subgraph', 'observe')
    builder.add_edge('seats', 'credit')
    return builder
