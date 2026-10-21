"""Research route planning and evidence checks on the controller side.

The route declares the existing research loop as a governed subgraph, ordinary
children as governed routes, and separate final review/integrity/completion steps.
These hooks never dispatch, approve, or label a scientific result as accepted.
"""
from copy import deepcopy
from pathlib import Path

from ravel.workflow import research_cycle as cycle, research_protocol as protocol
from ravel.workflow.graph_nodes import RecoveryHold


def parameters(spec, reading, contract, supplied):
    children = contract.get('research_children', [])
    if type(children) is not list:
        raise ValueError('explicit research child request population required')
    ids = []
    for child in children:
        if type(child) is not dict or not {'id', 'contract', 'reading'} <= set(child):
            raise ValueError('every research child retains its typed contract and reading')
        cycle.ce.identity(child['id'])
        ids.append(child['id'])
    if len(ids) != len(set(ids)):
        raise ValueError('research child identities must be distinct')
    return {'research_children': deepcopy(children),
            'research_request': {'reading': deepcopy(reading), 'contract': deepcopy(contract),
                                 'supplied': deepcopy(list(supplied))}}


def _root(context):
    return cycle._ordinary(Path(context['run_dir']) / 'campaign')


def _require_parent_contract(request, context):
    """Tie the worker's request to the controller run's exact retained contract."""
    try:
        own = cycle._pin(Path(context['run_dir']) / 'inputs' / 'task_contract.json')
        value = cycle._read(request, context['run_dir'])
        if value.get('parent_contract') != own:
            raise ValueError('campaign parent_contract must equal this run\'s task_contract.json pin '
                             '(path, sha256 and size)')
        if 'contract' in context and cycle._read(own, context['run_dir']) != context['contract']:
            raise ValueError('retained task_contract.json differs from the controller context contract')
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise RecoveryHold('research_contract_mismatch',
                           'Retain this run\'s original task contract and prepare a campaign bound to it: '
                           + str(exc)) from exc


def admit(step, context):
    """Require a current adopted campaign contract before governed dispatch."""
    if step['id'] == 'campaign':
        try:
            from ravel.workflow import research_coordinator_decisions as decisions
            pin = step.get('parameters', {}).get('research_request')
            if not pin:
                raise ValueError('research campaign request has not been adopted')
            _require_parent_contract(pin, context)
            cycle._check_pin(pin, context['run_dir'])
            decisions.request(pin)
        except RecoveryHold as exc:
            return [{'code': exc.reason, 'message': exc.would_make_possible}]
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return [{'code': 'research_request_unbound', 'message': str(exc)}]
    return []


DESIGN_KIND = 'research-campaign-design'
DESIGN_KEYS = frozenset(('schema_version', 'kind', 'campaign', 'evidence', 'candidate_modes', 'review',
                         'max_decisions', 'max_output_tokens', 'max_wall_seconds', 'research_regime'))


def _seat_model(store):
    """The model the frozen operator preferences name for the research seats (judgment tier, else agent)."""
    from ravel.controller.authority import frozen
    preferences = (frozen(store) or {}).get('agent_preferences') or {}
    order = [t for t in preferences.get('transport_preference') or () if type(t) is str]
    tiers = preferences.get('tier_models') or {}
    for tier in ('judgment', 'agent'):
        row = tiers.get(tier) if type(tiers.get(tier)) is dict else {}
        for transport in order:
            if type(row.get(transport)) is str and row[transport]:
                return row[transport]
    raise ValueError('the frozen operator preferences name no model for the research seats')


def campaign_request(pin, context):
    """The adopted campaign request pin; a campaign design is derived into one by the trusted producer.

    A preparing worker proposes the campaign (identity, budget, experiments, premises), its evidence by
    staged run input, candidate modes, review and decision bounds (``research-campaign-design/v1``). The
    controller supplies what custody rests on: this run's own pinned task contract and its handoff, the
    run-input pins, the seat model from the frozen operator preferences and the planning context
    (``research_orchestrator.prepare_open``), in a directory named by the design's digest, so a resumed
    bind adopts the same request. A complete open research request is validated as before.
    """
    run_dir = Path(context['run_dir'])
    design = cycle._read(pin, run_dir)
    if type(design) is not dict or design.get('kind') != DESIGN_KIND:
        return pin
    if design.get('schema_version') != 1 or set(design) - DESIGN_KEYS or DESIGN_KEYS - {'research_regime'} - set(design):
        raise ValueError(DESIGN_KIND + '/v1 names exactly ' + ', '.join(sorted(DESIGN_KEYS)))
    inputs = (run_dir / 'inputs').resolve()
    if type(design['evidence']) is not list:
        raise ValueError('campaign design evidence must list staged run inputs')
    evidence = []
    for row in design['evidence']:
        if type(row) is not dict or set(row) != {'input', 'purpose'} or type(row['input']) is not str:
            raise ValueError('campaign design evidence rows name one staged run input and its purpose')
        path = (inputs / row['input']).resolve()
        if not path.is_relative_to(inputs) or path == inputs or not path.is_file():
            raise ValueError('campaign design evidence must name a staged run input: ' + row['input'])
        evidence.append({'pin': cycle._pin(path), 'purpose': row['purpose']})
    store = context.get('store')
    if store is None:
        raise ValueError('the campaign request is derived inside the controller')
    runtime = {'model': _seat_model(store), 'reasoning_effort': 'high', 'adapter': 'model',
               'max_output_tokens': design['max_output_tokens'], 'max_wall_seconds': design['max_wall_seconds']}
    out = run_dir / 'research-request' / cycle.ce.digest(design)[:24]
    if (out / 'request.json').is_file():
        return cycle._pin(out / 'request.json')
    from ravel.workflow import research_orchestrator
    return research_orchestrator.prepare_open(
        cycle._pin(run_dir / 'inputs' / 'task_contract.json'), out, base_dir=run_dir, campaign=design['campaign'],
        runtime=runtime, evidence=evidence, candidate_modes=design['candidate_modes'], review=design['review'],
        max_decisions=design['max_decisions'], research_regime=design.get('research_regime', 'open_exploratory'))


def bind(plan, context):
    """Bind from P04-adopted preparation outputs before original CI1 authority."""
    steps = context.get('state', {}).get('steps', {})
    outputs = (steps.get('prepare') or {}).get('outputs', [])
    def adopted(name):
        rows = [row for row in outputs if row.get('path', '').endswith('/' + name)]
        if len(rows) != 1:
            raise ValueError('research preparation needs one adopted ' + name)
        row = rows[0]
        # The step outcome's adopted destination in the run directory, else its path.
        path = Path(row.get('destination') or row['path'])
        path = path if path.is_absolute() else Path(context['run_dir']) / path
        pin = cycle._pin(path)
        if pin['sha256'] != row.get('sha256'):
            raise ValueError('adopted research preparation bytes changed')
        return pin
    request = campaign_request(adopted('campaign-request.json'), context)
    children_pin = adopted('child-requests.json')
    _require_parent_contract(request, context)
    from ravel.workflow import research_coordinator_decisions as decisions
    value = decisions.request(request)
    children = cycle._read(children_pin, context['run_dir'])
    if any(type(child) is dict and 'engagement_planning' in child for child in children):
        from ravel.controller.engagement.planning import pin_children
        pin_children(context, children, 'prepare:outputs/child-requests.json')
    bound = parameters({}, context['reading'], {'research_children': children}, [])
    result = deepcopy(plan)
    # The loop budget CHECK-IN 1 approves (the plan's digest binds it): cycles, children, ceilings, projections.
    from .loop_budget import declare
    budget = declare(value, children, tier='full', store=context.get('store'), state=context.get('state'))
    result.setdefault('parameters', {}).update(bound, research_request=request,
        research_binding={'request': request, 'children': children_pin}, research_loop_budget=budget)
    planned_children = []
    from ravel.workflow.research_controller import _step
    for child in children:
        row = _step('children.' + child['id'], 'route')
        row.update(route='study', depends_on=['campaign'])
        row['parameters'] = {'item': deepcopy(child), 'own_checkin1': True,
                              'inherit_budget': True, 'inherit_authority': True}
        row['obligations'] += ['P03', 'C34', 'MODE-research-comparison']
        planned_children.append(row)
    result['steps'] = [row for row in result['steps'] if not row['id'].startswith('children.')
                       and row['id'] != 'children']
    index = next(i for i, row in enumerate(result['steps']) if row['id'] == 'campaign')
    result['steps'][index + 1:index + 1] = planned_children
    for row in result['steps']:
        if row['id'] == 'campaign':
            row.setdefault('parameters', {}).update(research_request=request,
                campaign=str(_root(context)), runtime=deepcopy(value['runtime']),
                research_loop_budget=deepcopy(budget))
            row['graph']['instance'] = {'campaign': value['campaign']['id'], 'request': request['sha256']}
            # The campaign step's own wall ceiling is the adopted campaign's; its role calls reserve as child steps.
            row['budget'] = {**(row.get('budget') or {}), 'wall_seconds': value['campaign']['budget']['wall_seconds']}
        elif row['id'] == 'meta-review':
            row['depends_on'] = ['campaign', *[child['id'] for child in planned_children]]
    from ravel.workflow.research_controller import plan_sha256
    result['sha256'] = plan_sha256(result)
    return result


def invoke(store, step, context):
    from ravel.workflow.research_controller import invoke as governed
    return governed(store, step, context)


def child_route_errors(state, context):
    errors = []
    declared = {row['id'] for row in context['plan']['parameters'].get('research_children', [])}
    actual = {row['id'] for row in state['experiments']}
    errors.extend('declared ordinary child is missing: ' + identity for identity in sorted(declared - actual))
    # Adaptive children are admitted prospectively by the original campaign,
    # then dispatched as ordinary controller routes. A plan placeholder is no receipt.
    store = context.get('store')
    dispatches = [] if store is None else [record.get('record', record)
                                          for record in store.scan('research-step-outcome')]
    for row in state['experiments']:
        matches = [record for record in dispatches if record['step']['kind'] == 'route'
            and record['step'].get('route') == 'study' and record['outcome'].get('status') == 'completed'
            and all(record['step'].get('parameters', {}).get(key) is True for key in
                    ('own_checkin1', 'inherit_authority', 'inherit_budget'))
            and all((record['step'].get('parameters', {}).get('experiment') or {}).get(key) == row.get(key)
                    for key in ('id', 'rundir', 'study', 'cost'))]
        if not matches:
            errors.append('ordinary child has no completed governed route: ' + row['id'])
    return errors


def checkin(kind, context):
    """CHECK-IN 1 shows the research loop budget its approval binds; the plan critic checks it."""
    if kind != 'approve_plan':
        return {}
    from .loop_budget import checkin_section, verify, LoopBudgetExhausted
    budget = (context['plan'].get('parameters') or {}).get('research_loop_budget')
    try:
        verify(budget)
    except LoopBudgetExhausted as exc:
        return {'errors': [{'code': 'research_loop_budget_missing', 'message': str(exc)}]}
    campaign = [row for row in context['plan']['steps'] if row['id'] == 'campaign']
    if len(campaign) != 1 or (campaign[0].get('parameters') or {}).get('research_loop_budget') != budget:
        return {'errors': [{'code': 'research_loop_budget_unbound',
                            'message': 'the campaign step must carry exactly the plan\'s research loop budget'}]}
    store = context.get('store')
    if store is not None:
        # CHECK-IN 1's own rows: the approval binds the derived campaign request and the loop budget.
        from ..analysis import discharge
        request = (context['plan'].get('parameters') or {}).get('research_request') or {}
        content = [value for value in (request.get('sha256'), budget.get('sha256')) if type(value) is str]
        evidence = {'validator': 'route.research.bind+plan_review', 'sha256': context['plan'].get('sha256'),
                    'mechanism': 'route.research'}
        credit = discharge.checkin1_content(store, context, evidence, content if len(content) == 2 else [])
        if credit is not None:
            # The campaign's premises are its stated result-sensitive assumptions (C14); a request that no longer
            # reads states none, so the row stays with its reviewers.
            from ravel.workflow import research_coordinator_decisions as decisions
            try:
                premises = decisions.request(request)['campaign'].get('premises')
            except (ValueError, OSError, KeyError, TypeError):
                premises = None
            discharge.checkin1_assumptions(store, context, {**evidence, 'request': request['sha256']}, credit,
                                           premises if type(premises) is list else None)
    section = checkin_section(budget)
    flags = []
    if budget['exceeds_operator_envelope']:
        flags.append({'kind': 'risk', 'text': 'The projected central research loop cost exceeds the operator '
                                              'cost ceiling; the loop ends qualified when the ceiling is reached.'})
    return {'sections': [{'id': section['id'], 'title': section['title'], 'lines': section['lines']}],
            'flags': flags, 'pins': {'research_loop_budget_sha256': budget['sha256']},
            'review_items': [{'id': 'research_loop_budget',
                              'text': 'Check the research loop budget: cycles, children, the cost ceiling and the '
                                      'projected cost per cycle and per child against the original request.'}]}


DELIVERY_TRANSITIONS = {'checkin3->deliver', 'deliver', 'checkin3'}


def gate(transition, context):
    """Research evidence must be complete before CHECK-IN 3 releases delivery."""
    if transition not in DELIVERY_TRANSITIONS:
        return []
    try:
        root = _root(context)
        _, state = cycle._load(root)
        status = protocol.methodology_status(root)
        errors = ['required research stage incomplete: ' + row for row in status['pending']]
        errors.extend(child_route_errors(state, context))
        for row in state['experiments']:
            cycle._current_evidence(state, row, accepted=True)
        return errors
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [{'code': 'research_evidence_incomplete', 'message': str(exc)}]


def ending(reason, context):
    """Record honest bounded progress; the controller then invokes its sole sink."""
    record = {'reason': reason, 'open_obligations': deepcopy(context['plan'].get('open_obligations', [])),
              'steps': deepcopy(context.get('state', {}).get('steps', {})),
              'scientific_acceptance_inferred': False}
    try:
        record['synthesis'] = cycle.bounded_synthesis(_root(context), reason)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        record['unavailable_synthesis'] = {'type': type(exc).__name__, 'message': str(exc)}
    context['store'].append('research-ending', record)


__all__ = ['admit', 'bind', 'checkin', 'ending', 'gate', 'invoke', 'parameters']
