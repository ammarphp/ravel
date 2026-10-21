"""Observed decision justification for controller approval and final-task actions.

The plan review and its per-step cases remain mandatory. Above R2 for approval,
and at final-task decisions, a governed critic seat decides the exact action digest. Review credit
never supplies operator authority; the authority service authenticates that too.
"""
from __future__ import annotations

from copy import deepcopy

from . import common

FINAL_GATES = ('final_task', 'delivery', 'report_integrity')


def approval_action(pins):
    """The same exact action at the request and at the read-only approval gate."""
    return {'kind': 'controller.approve_plan', 'digest': common.digest(pins),
            'summary': 'controller approve_plan', 'pins': [], 'node_id': None,
            'rung': None, 'scope': None, 'view_pins': deepcopy(pins)}


def final_action(pins):
    """The final-task action at CHECK-IN 3 and at the sink's repeated decision."""
    return {**approval_action(pins), 'kind': 'controller.final_task', 'summary': 'controller final_task'}


def final_task_action(store):
    """Sink interface: the same authenticated retained action the authority reviewed."""
    from . import retained
    return final_action(retained.current(store, 'final')['view']['pins'])


def review_final_task(store, state, context):
    """Controller interface: dispatch the retained final action through its ordinary RDJ seat."""
    return dispatch(store, state, final_task_action(store), context)


def review_deviation(store, state, action, context):
    """Controller interface: dispatch the exact deviation action (a replan, a recovery) through its ordinary RDJ
    seat before the deviation authority is asked."""
    return dispatch(store, state, action, context)


def classification(store, pins, gate='approve_plan'):
    from ravel.workflow.rdj_loop import compute_class
    action = final_action(pins) if gate == 'final_task' else approval_action(pins)
    return compute_class(getattr(store, 'run_dir', None) or store.path(), gate, action)


def dispatch(store, state, action, context):
    """Run one bounded, ordinary RDJ review seat on this approval action, before asking authority.

    Re-entering the authority node or polling it never manufactures another vote.
    A failed or revising seat stays failed; a new action gets a new seat.
    """
    from ravel.controller.judgment import graph, steps
    from ravel.workflow import rdj_loop
    from . import retained

    if action.get('kind') == 'controller.checkin2_accept':
        gate, kind = 'checkin2_accept', 'go'
    elif action.get('kind') == 'controller.deviation':
        gate, kind = 'deviation', 'deviation'
    else:
        gate = 'final_task' if action.get('kind') == 'controller.final_task' else 'approve_plan'
        kind = 'final' if gate == 'final_task' else 'approve_plan'
    cls, factors = rdj_loop.compute_class(store.run_dir, gate, action)
    if gate == 'approve_plan' and rdj_loop.RANK[cls] <= rdj_loop.RANK['R2']:
        return
    step_id = 'authority-rdj-' + action['digest'][:40]
    if any(row['record'].get('step_id') == step_id for row in store.scan('step-outcome')):
        return
    planning = {'request': deepcopy(state.get('request') or {}), 'context': deepcopy(context)}
    request = graph._request(planning, store)
    material_name = ('checkpoint-action' if gate == 'checkin2_accept' else 'deviation-action' if gate == 'deviation' else
                     'final-task-action' if gate == 'final_task' else 'approval-action')
    material = graph._context_file(planning, material_name, {
        'kind': 'controller-' + material_name, 'action': action, 'class': cls,
        'approval_view': retained.current(store, kind)['view'],
        'computed_factors': factors, 'policy': rdj_loop.anchor_check.policy_pin()})
    inputs = graph._base_inputs(graph._inputs(planning, store, request)) + [material]
    step = steps.rdj_step(step_id, subject={'kind': material_name, 'sha256': action['digest']},
                          must_check=[{'id': material_name, 'row': 'JR06',
                                       'text': f'Decide whether to approve this exact {gate} action, its view pins, '
                                               f'computed class {cls}, risks and justification. A revise verdict '
                                               'withholds approval; review cannot grant operator authority.'}],
                          inputs=inputs, purpose=f'Justify the exact consequential {gate} action.')
    graph._run_planning_steps(store, planning, request, material_name, [step])


def evaluate(rundir, action, required, factors, gate='approve_plan'):
    """Read current observed critic credit and independently authenticated R3 authority.

    Returns (missing reasons, evidence). Approval callers also check the plan mapping.
    No custody receipt or caller-supplied independence label can discharge this case.
    """
    from ravel.controller.store import RunStore, controller_owned
    from ravel.workflow import rdj_approval, role_registry
    from ravel.controller.judgment.steps import rdj_role
    from . import service

    try:
        if gate in FINAL_GATES and action.get('kind') != 'controller.final_task':
            return ['the final-task action has no controller final-task identity'], None
        if gate == 'checkin2_accept' and action.get('kind') != 'controller.checkin2_accept':
            return ['the checkpoint action has no controller checkin2 identity'], None
        if gate == 'deviation' and action.get('kind') != 'controller.deviation':
            return ['the deviation action has no controller deviation identity'], None
        # Also verifies that the action digest commits to its claimed view pins.
        plan_sha256 = rdj_approval.approved_plan(action)
        waypoint_reviews = {}
        if gate == 'checkin2_accept':
            from ravel.controller import graph
            from ravel.workflow import review_points
            from . import retained
            store, plan = rdj_approval.controller_plan(rundir)
            if plan_sha256 != plan['sha256']:
                return ['the checkpoint action binds a different current plan'], None
            if retained.current(store, 'go')['view']['pins'] != action['view_pins']:
                return ['the checkpoint action differs from the current retained GO view'], None
            waypoints = plan.get('waypoints') or []
            if (not waypoints or len(waypoints) != len(set(waypoints))
                    or action.get('waypoint') != ','.join(waypoints)):
                return ['the checkpoint action names a different current waypoint population'], None
            for role in graph.checkin_seats(plan, 'checkin2', graph.CI2_SEATS):
                review, reason = review_points._waypoint_review(store, plan, action, role)
                if reason is not None:
                    return [f'the checkpoint waypoint seat {role}: {reason}'], None
                waypoint_reviews[role] = review
        else:
            owner = controller_owned(rundir)
            if owner is None:
                return ['the action is not in a controller-owned run'], None
            store = RunStore(owner)
        case, reason = rdj_approval._case(store, action['digest'])
        if reason is not None:
            return [reason], None
        if not role_registry.same_card(case['role'], rdj_role()):
            return ['the action case was not decided by the RDJ critic card'], None
        authority = None
        if required == 'R3':
            if gate in FINAL_GATES:
                authority = current_final(store, action['view_pins'])
            else:
                authority = service.current(store, {'checkin2_accept': 'go', 'deviation': 'deviation'}.get(
                    gate, 'approve_plan'), subject=action['view_pins'])
            if authority is None or (authority.get('label') != common.OPERATOR_COMMAND and not (
                    gate in FINAL_GATES and service.delegated_final(store, authority))):
                return [f'{required} approval requires current renewed attested operator authority on these exact '
                        'view pins'], None
        if factors.get('irreversible') and (authority or {}).get('human_identity_authenticated') is not True:
            return ['an irreversible action requires recorded human approval; operator identity is unattested'], None
        return [], {'subject_sha256': action['digest'], 'class': required, **case,
                    'authority': authority['id'] if authority else None,
                    'authority_label': authority['label'] if authority else None,
                    **({'waypoint_reviews': waypoint_reviews} if gate == 'checkin2_accept' else {})}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f'the action case or authority is unreadable: {type(exc).__name__}: {exc}'[:500]], None


def current_final(store, pins):
    """A final disposition is not effect authority; authenticate it through its own reader."""
    from . import service
    for record in reversed(service.records(store)):
        if record['kind'] == 'final':
            try:
                current = service.disposition(store, record['id'], kind='final', subject=pins)
                return current if current['decision'] == 'accept' else None
            except common.AuthorityRefused:
                return None
    return None


def dispatch_native(store, action, context):
    """Dispatch one ordinary observed critic for a protected exact R3 native launch."""
    from ravel.controller.judgment import graph, steps
    from ravel.controller.step import launch_gate
    from ravel.workflow import rdj_loop
    from . import retained
    launch_gate.load(store.run_dir, action)
    cls, factors = rdj_loop.compute_class(store.run_dir, 'launch', action)
    if cls != 'R3':
        raise ValueError('native critic dispatch requires the actual R3 launch class')
    step_id = 'native-rdj-' + action['digest'][:40]
    if any(row['record'].get('step_id') == step_id for row in store.scan('step-outcome')):
        return
    intake = store.latest('intake')['record']
    planning = {'request': {'sha256': intake['request_sha256'], 'reading_sha256': intake['reading_blob'],
                            'contract_sha256': intake['contract_blob']}, 'context': deepcopy(context)}
    request = graph._request(planning, store)
    material = graph._context_file(planning, 'native-launch-action', {
        'kind': 'controller-native-launch-action', 'action': action, 'class': cls,
        'approval_view': retained.current(store, 'r3_action')['view'],
        'computed_factors': factors, 'policy': rdj_loop.anchor_check.policy_pin()})
    inputs = graph._base_inputs(graph._inputs(planning, store, request)) + [material]
    step = steps.rdj_step(step_id, subject={'kind': 'native-launch-action', 'sha256': action['digest']},
        must_check=[{'id': 'native-launch-action', 'row': 'JR06',
                     'text': 'Decide this exact consequential native launch, all five view pins, attempt, '
                             'resources, risks and justification. Revise withholds approval. '
                             'Review cannot grant operator authority.'}],
        inputs=inputs, purpose='Justify the exact consequential native launch action.')
    graph._run_planning_steps(store, planning, request, 'native-launch-action', [step])


def evaluate_native(rundir, action):
    """The same observed critic and authenticated operator mechanism, bound to native launch."""
    from ravel.controller.step import launch_gate, native_authority
    from ravel.workflow import rdj_approval, rdj_loop, role_registry
    from ravel.controller.judgment.steps import rdj_role
    try:
        store, plan, step, proof = launch_gate.load(rundir, action)
        required, factors = rdj_loop.compute_class(rundir, 'launch', action)
        if required != 'R3':
            return ['native R3 evaluation requires the actual R3 launch class'], None
        if not native_authority.active(rundir, action):
            return ['native R3 requires its exact authenticated retained action context'], None
        native_authority._approved(store, plan, step, proof)
        case, reason = rdj_approval._case(store, action['digest'])
        if reason is not None:
            return [reason], None
        if not role_registry.same_card(case['role'], rdj_role()):
            return ['the native action case was not decided by the RDJ critic card'], None
        authority = native_authority.verified_operator(store, action['view_pins'])
        if factors.get('irreversible') and authority.get('human_identity_authenticated') is not True:
            return ['an irreversible action requires recorded human approval; operator identity is unattested'], None
        return [], {'subject_sha256': action['digest'], 'class': required, **case,
                    'authority': authority['id'], 'authority_label': authority['label']}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return [f'the native action case or authority is unreadable: {type(exc).__name__}: {exc}'[:1500]], None
