"""Governed research adapters over the binding step, store, judgment and sink APIs.

All dynamic work enters ``step.run``. Domain journals still verify the exact
ordinary contracts and receipts. The adapter never treats a worker's transport
claims, a successful exit, or a completed subgraph as scientific acceptance.
"""
from contextlib import contextmanager
from contextvars import Context, ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

from . import research_cycle as cycle, graph_nodes, state_io

_ACTIVE = ContextVar('research_controller', default=None)
_STORES = {}
_LOCK = threading.RLock()
OBSERVATION = 'step-observation'


def plan_sha256(plan):
    """The controller plan seal: canonical UTF-8 JSON of every field but ``sha256``.

    It matches the plan compiler and judgment planner byte for byte, including
    non-ASCII text, which ``candidate_experiments.digest`` would escape.
    """
    body = {k: v for k, v in plan.items() if k != 'sha256'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _rows(store, kind):
    return [row.get('record', row) for row in store.scan(kind)]


def _service(name):
    from importlib import import_module
    return import_module('ravel.controller.' + name)


@contextmanager
def bound(store, context):
    """Controller-only composition scope; JSON graph state contains no service objects."""
    ctx = deepcopy(context)
    ctx['run_id'] = store.run_id
    if not ctx.get('run_dir'):
        raise ValueError('research controller requires its original run directory')
    if store.path().resolve().is_relative_to(Path(ctx['run_dir']).resolve()):
        raise ValueError('research store must remain outside the original run directory')
    with _LOCK:
        previous = _STORES.get(store.run_id)
        _STORES[store.run_id] = store
    token = _ACTIVE.set((store, ctx))
    try:
        yield
    finally:
        _ACTIVE.reset(token)
        with _LOCK:
            if previous is None:
                _STORES.pop(store.run_id, None)
            else:
                _STORES[store.run_id] = previous


def active():
    return _ACTIVE.get()


def loop_budget_view():
    """The approved research loop budget as the deciding seat sees it, or None outside a controller scope."""
    current = active()
    if current is None or current[1].get('research_loop_budget') is None:
        return None
    from ravel.controller.routes.research import loop_budget
    return loop_budget.view(current[0], current[1]['research_loop_budget'])


def _next_action(node):
    """Whether a model node is the coordinator's next-action decision (one research cycle)."""
    fields = ((node.get('parameters') or {}).get('output_schema') or {}).get('properties') or {}
    return (fields.get('kind') or {}).get('const') == 'research-action'


def _loop_boundary(store, identity, exc):
    """Record the refused admission and end the campaign through its ordinary qualified bounded synthesis."""
    store.append('research-budget-boundary', {'step_id': identity, 'kind': getattr(exc, 'kind', 'research_loop_budget'),
                                              'reason': str(exc)})
    raise cycle.CampaignBudgetExhausted(str(exc)) from exc


def admit_action(origin):
    """Recheck the protected decision at the effect, including a checkpoint that reuses its model result."""
    current = active()
    if current is None:
        return
    store, context = current
    from ravel.controller.routes.research import loop_budget
    budget = loop_budget.verify(context.get('research_loop_budget'))
    calls = [row for row in _rows(store, 'research-call')
             if row['result_sha256'] == cycle.ce.digest(origin['value'])]
    if len(calls) != 1:
        raise ValueError('research action lacks its unique protected observed call')
    identity = calls[0]['step_id']
    decisions = [row for row in _rows(store, loop_budget.DECISION)
                 if row['budget_sha256'] == budget['sha256']]
    rows = [row for row in decisions if row['step_id'] == identity]
    public = origin['value']['value']
    if (len(rows) != 1 or rows[0] != decisions[-1] or not rows[0]['action_admitted']
            or rows[0]['assessment'] != public.get('information_gain') or rows[0]['action'] != public.get('action')
            or cycle._pin(rows[0]['output']['path']) != rows[0]['output']):
        raise ValueError('research effect differs from its current admitted information-gain decision')


def _step(identity, kind, *, role=None, operation=None, outputs=(), inputs=(), budget=None):
    return {'id': identity, 'kind': kind, 'role': role, 'operation': operation,
            'inputs': list(inputs), 'outputs': [{'path': path, 'kind': 'document', 'required': True}
                                               for path in outputs],
            'depends_on': [], 'waypoint': False, 'rung': None, 'budget': deepcopy(budget or {}),
            'protocols': ['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'], 'review': [],
            'instruction_sources': ['docs/workflow/reference/research-orchestration.md',
                                    'docs/workflow/reference/research-protocols.md'],
            'obligations': ['R06', 'GATE-research_choice']}


def _derive_dispatch(store, step, context):
    """Bind bounded inner work to the exact protected parent subgraph entry.

    This publishes custody only. P04 still checks the actual approved parent plan,
    authority, budgets, role, operation, confinement, output and review gates.
    """
    current = active()
    if current is None or current[0] is not store:
        raise ValueError('research dispatch requires its controller composition scope')
    campaign = context.get('research_campaign') or (step.get('parameters') or {}).get('campaign')
    entries = []
    for envelope in store.scan('research-subgraph-entry'):
        entry = envelope.get('record', envelope)
        if (entry['parent_plan_sha256'] == context.get('plan_sha256') and entry['campaign'] == campaign):
            entries.append((envelope['id'], entry))
    if not entries:
        return  # A standalone peer fake may model the parent; real P04 remains fail-closed.
    entry_id, entry = entries[-1]
    cycle._check_pin(entry['request'], context['run_dir'])
    if step['kind'] in {'author', 'operate'}:
        from . import agent_graph
        research = context.get('research') or {}
        graph = Path(research['graph_root'])
        if not graph.resolve().is_relative_to(Path(context['run_dir']).resolve()):
            raise ValueError('research role graph is outside the original parent run')
        spec, state = agent_graph._load(graph)
        node = step['parameters']['research_node']
        found = [row for row in spec['nodes'] if row['id'] == node['id']]
        if (found != [node] or state['nodes'][node['id']]['status'] != 'running'
                or research['node'] != node or research['request'] != step['parameters']['research_request']
                or research['request']['node_sha256'] != cycle.ce.digest(node)):
            raise ValueError('research derived step differs from its active original Graph')
    elif step['kind'] == 'route':
        from . import science
        parameters = step['parameters']
        if (step.get('route') != 'study' or not all(parameters.get(key) is True for key in
                ('own_checkin1', 'inherit_authority', 'inherit_budget'))):
            raise ValueError('research child cannot widen original admission or budget')
        _, state = cycle._load(campaign)
        experiment = parameters['experiment']
        found = [row for row in state['experiments'] if row['id'] == experiment['id']]
        if len(found) != 1 or any(found[0].get(key) != experiment.get(key) for key in ('id', 'study', 'rundir', 'cost')):
            raise ValueError('research child differs from its prospectively admitted experiment')
        science.verify_plan(experiment['rundir'], approved=True)
    else:
        raise ValueError('unsupported inner research step kind')
    sha = cycle.ce.digest(step)
    if not any(row['step_sha256'] == sha and row['parent_entry_id'] == entry_id
               for row in _rows(store, 'research-derived-step')):
        store.append('research-derived-step', {'step': deepcopy(step), 'step_sha256': sha,
            'parent_entry_id': entry_id, 'parent_plan_sha256': entry['parent_plan_sha256']})


def _outcome(store, step, context):
    from .graphs import DeliveryRequired
    key = cycle.ce.digest({'step': step, 'context': context})
    prior = next((row for row in reversed(_rows(store, 'research-step-outcome'))
                  if row['key'] == key and row['outcome']['status'] == 'completed'), None)
    if prior is not None:
        return deepcopy(prior['outcome'])
    _derive_dispatch(store, step, context)
    result = _service('step').run(store, deepcopy(step), deepcopy(context))
    if (type(result) is not dict or result.get('step_id') != step['id']
            or type(result.get('attempt')) is not int):
        raise ValueError('governed step returned an unbound research outcome')
    store.append('research-step-outcome', {'key': key, 'step': step, 'context': context, 'outcome': result})
    status = result.get('status')
    if status == 'budget_exhausted':
        raise cycle.CampaignBudgetExhausted(result.get('reason') or 'governed research step budget exhausted')
    if status == 'stopped':
        raise graph_nodes.RecoveryHold('controller_stop', result.get('reason'))
    if status in {'held', 'escalated'}:
        raise DeliveryRequired({'kind': 'governed-research-step-required', 'step_id': step['id'],
                                'status': status, 'reason': result.get('reason'), 'request': result.get('request')})
    if status != 'completed':
        raise ValueError('governed research step failed: ' + str(result.get('reason')))
    return result


def _read_output(result, context, name):
    candidates = [row for row in result.get('outputs', []) if row.get('path', '').endswith('/' + name)
                  or row.get('path') == name]
    if len(candidates) != 1:
        raise ValueError('governed research output is missing or ambiguous: ' + name)
    pin = candidates[0]
    # A governed step outcome names the plan path and the destination custody adopted it to.
    target = Path(pin.get('destination') or pin['path'])
    run = Path(context['run_dir']).resolve()
    target = target if target.is_absolute() else run / target
    expected = run / 'steps' / result['step_id'] / 'outputs'
    if (not target.resolve().is_relative_to(expected)
            or any(part.is_symlink() for part in (target, *target.parents) if part.is_relative_to(run))):
        raise ValueError('research output is outside its adopted step directory')
    actual = cycle._pin(target)
    if actual['sha256'] != pin.get('sha256'):
        raise ValueError('governed research output changed after adoption')
    return state_io.read_json(target), actual


def _worker_packet(node, identity, context):
    """Carry the original projection, including RDJ's public edge payload seat."""
    if node.get('packet') is not None:
        return deepcopy(node['packet']), None
    inputs = node.get('inputs') or []
    from .review_dispatch import RDJ_EDGE_ROLE
    # The RDJ graph node's registered role (``rdj_loop.AGENT_ROLES``), not the card id.
    if (node.get('role') != RDJ_EDGE_ROLE or len(inputs) != 1
            or inputs[0].get('id') != 'rdj-payload'):
        return None, None
    source = cycle._pin(inputs[0]['path'])
    if source['sha256'] != inputs[0]['sha256']:
        raise ValueError('research edge projection source changed')
    from . import rdj_loop, review_context
    folder = Path(context['run_dir'])/'inputs/research'/(identity+'-packet')
    manifest = folder/'manifest.json'
    if not manifest.exists():
        packet = rdj_loop.AgentHostDispatcher.packet(folder, node['role'], Path(source['path']))
    else:
        value = state_io.read_json(manifest)
        packet = {'path': str(folder), 'manifest_sha256': value['sha256']}
    index = review_context._PacketIndex(packet['path'], packet['manifest_sha256'])
    if (index.manifest.get('kind') != 'rdj_role_packet_v1' or index.manifest.get('role') != node['role']
            or len(index.entries) != 1):
        raise ValueError('research edge projection differs from the original public payload')
    entry = next(iter(index.entries.values()))
    if entry['id'] != 'rdj-payload' or hashlib.sha256(index.read(entry)).hexdigest() != source['sha256']:
        raise ValueError('research edge projection payload changed')
    index.finish()
    return packet, source['sha256']


def governed_call(store, context, function):
    """``function()`` as a run of its own: a fresh context holding only the enclosing substrate node record and
    this controller's protected research scope (``bound``).

    Graph's service boundary deliberately clears ContextVars; a governed step started from inside a charged service
    starts clean too, so the service's runnable configuration and callbacks never reach the step's graph.
    """
    node_record = graph_nodes.TRIPWIRE.get()

    def governed():
        if node_record is not None:
            graph_nodes.TRIPWIRE.set(node_record)
        with bound(store, context):
            return function()
    return Context().run(governed)


class GovernedHost:
    """A Graph/Host compatibility facade whose only dispatcher is controller.step."""
    def __init__(self, store, context):
        self.store, self.context = store, deepcopy(context)

    @property
    def identity(self):
        return {'adapter': 'controller.step', 'run_id': self.store.run_id,
                'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def execute(self, node, request, control):
        identity = 'research-' + cycle.ce.digest({'request': request, 'node': node})[:40]
        model = node['kind'] == 'model'
        role = None
        if model:
            from . import role_registry
            # An explicit registry role is authoritative. Only a node without one resolves its id or
            # graph-role alias. An unknown explicit identity never falls back to another card.
            explicit = node.get('registry_role')
            for candidate in ((explicit,) if explicit is not None else (node['id'], node['role'])):
                if candidate is None:
                    continue
                try:
                    card = role_registry.load(candidate)
                except (KeyError, ValueError):
                    continue
                role = card['id']
                break
            if role is None:
                raise ValueError('research node has no registered governing role')
        else:
            from . import production_executor, role_registry
            assigned = production_executor.executors()['operations'].get(node['action'], 'research-explorer')
            role = role_registry.load(assigned)['id']
        from . import agent_graph
        original_spec, original_state = agent_graph._load(control.root)
        try:
            agent_graph._deadline(original_spec, original_state)
        except agent_graph.GraphError as exc:
            self.store.append('research-budget-boundary', {'step_id': identity, 'graph_root': str(control.root),
                'kind': 'original_graph_wall_exhausted', 'reason': str(exc),
                'started_epoch': original_state['started_epoch'],
                'max_wall_seconds': original_spec['budget']['max_wall_seconds']})
            raise cycle.CampaignBudgetExhausted(str(exc)) from exc
        cycle_admission = None
        if model and _next_action(node):
            # One research cycle: the coordinator's decision must have been shown the approved loop budget, and
            # the cycle's projected high cost must still fit it; otherwise the campaign ends qualified.
            from ravel.controller.routes.research import loop_budget
            budget = self.context.get('research_loop_budget')
            presented = [row for row in node.get('inputs') or () if row.get('id') == 'scientific-core']
            try:
                loop_budget.verify(budget)
                core = cycle._pin(presented[0]['path']) if len(presented) == 1 else None
                shown = state_io.read_json(core['path']) if core and core['sha256'] == presented[0].get('sha256') else {}
                from .research_coordinator_decisions import expand_decision_context
                shown = expand_decision_context(shown)
                prior = [row for row in _rows(self.store, loop_budget.RESERVATION)
                         if row.get('budget_sha256') == budget['sha256'] and row.get('key') == identity]
                expected = prior[0].get('presented_budget') if prior else loop_budget.view(self.store, budget)
                if expected is None or shown.get('loop_budget') != expected:
                    raise loop_budget.LoopBudgetExhausted(
                        'the coordinator decision was not presented the approved research loop budget')
                from ravel.controller import capabilities
                catalogue = (shown.get('capabilities') or {}).get('catalogue') or {}
                supplied = [row for row in node.get('inputs') or () if row.get('sha256') == catalogue.get('sha256')]
                if (catalogue.get('catalogue_sha256') != capabilities.catalogue()['sha256'] or len(supplied) != 1
                        or state_io.read_json(supplied[0]['path']).get('sha256') != catalogue['catalogue_sha256']):
                    raise loop_budget.LoopBudgetExhausted(
                        'the coordinator decision was not presented the current capability catalogue')
                cycle_admission = loop_budget.admit(self.store, budget, 'cycle', identity)
            except loop_budget.LoopBudgetExhausted as exc:
                _loop_boundary(self.store, identity, exc)
        wall = min(original_spec['budget']['max_wall_seconds'],
                   self.context.get('research_max_wall_seconds', original_spec['budget']['max_wall_seconds']))
        step = _step(identity, 'author' if model else 'operate', role=role,
                     operation=None if model else node['action'], outputs=['outputs/public-record.json'],
                     budget={'tokens': node['parameters'].get('max_output_tokens', 0),
                             'wall_seconds': wall})
        if self.context.get('research_step_share') is not None:
            share = self.context['research_step_share']
            for dimension in ('wall_seconds', 'tokens', 'cost_usd', 'broker_calls'):
                if dimension in share:
                    step['budget'][dimension] = min(step['budget'].get(dimension, share[dimension]),
                                                    share[dimension])
        step['parameters'] = {'research_node': deepcopy(node), 'research_request': deepcopy(request),
                              'output_schema': deepcopy(node['parameters'].get('output_schema'))}
        worker_packet, packet_subject = _worker_packet(node, identity, self.context) if model else (None, None)
        step['parameters'].update(research_packet=worker_packet, research_packet_subject_sha256=packet_subject)
        from .agent_host import prepare_model_context
        snapshot = {'node': deepcopy(node), 'request': deepcopy(request),
                    'presentation': prepare_model_context(node, request) if model else None}
        relative = 'inputs/research/' + identity + '.json'
        source = Path(self.context['run_dir']) / relative
        if source.exists() and state_io.read_json(source) != snapshot:
            raise ValueError('research input snapshot differs from its dispatched identity')
        state_io.atomic_json(source, snapshot)
        pin = cycle._pin(source)
        step['inputs'] = [{'artifact': relative, 'sha256': pin['sha256'], 'kind': 'document', 'required': True}]
        context = {**self.context, 'research': {'node': deepcopy(node), 'request': deepcopy(request),
                                              'graph_root': str(control.root)}}

        def dispatch():
            outcome = governed_call(self.store, context, lambda: _outcome(self.store, step, context))
            public, pin = _read_output(outcome, context, 'public-record.json')
            observations = [row for row in _rows(self.store, OBSERVATION)
                if row.get('step_id') == identity and row.get('attempt') == outcome['attempt']
                and row.get('receipt_sha256') in outcome.get('receipts', [])]
            if len(observations) != 1:
                raise ValueError('research call lacks its unique protected step observation')
            observed = observations[0]
            if observed.get('status') not in {'ok', 'completed'}:
                raise ValueError('research worker did not have a successful observed completion')
            if not model:
                return public
            from .agent_host import validate_completion_value
            public = validate_completion_value(public, node['parameters'])
            transport = deepcopy(observed.get('transport_evidence') or {})
            isolation = deepcopy(observed.get('isolation') or {})
            model_observed = observed.get('model') or {}
            if (not observed.get('actor_id') or not observed.get('session_id')
                    or isolation.get('fresh_request') is not True
                    or isolation.get('parent_transcript_supplied') is not False):
                raise ValueError('research worker lacks fresh observed actor and session evidence')
            if type(model_observed.get('requested')) is not str or not model_observed['requested']:
                raise ValueError('research worker requested model is unobserved')
            transport.update(request_id=request['request_id'], actor_id=observed['actor_id'],
                invocation_id=observed['session_id'], requested_model=model_observed['requested'],
                observed_model=model_observed.get('observed'),
                controller_run_id=self.store.run_id,
                context_manifest_sha256=(node.get('packet') or {}).get('manifest_sha256'))
            if not transport.get('execution_mode'):
                raise ValueError('research worker execution mode is unobserved')
            for prior in _rows(self.store, 'research-call'):
                if prior['step_id'] == identity:
                    continue
                previous = prior['observation']
                if (observed['session_id'] == previous['session_id']
                        or observed['actor_id'] == previous['actor_id']):
                    raise ValueError('research worker reused an observed actor or session')
            value = {'kind': 'model_result', 'value': public, 'usage': deepcopy(observed.get('usage') or {}),
                     'transport': transport, 'isolation': isolation}
            if cycle_admission is not None:
                from ravel.controller.routes.research import loop_budget
                try:
                    loop_budget.record_decision(self.store, budget, cycle_admission, public, node.get('inputs') or (),
                        output=pin, observation_sha256=observed['receipt_sha256'])
                except loop_budget.InformationGainStopped as exc:
                    _loop_boundary(self.store, identity, exc)
            self.store.append('research-call', {'step_id': identity, 'request_id': request['request_id'],
                'run_dir': self.context['run_dir'], 'worker_packet': worker_packet,
                'worker_packet_subject_sha256': packet_subject,
                'node': node, 'request': request, 'output': pin, 'outcome': outcome,
                'observation': observed, 'result_sha256': cycle.ce.digest(value)})
            return value
        return control.call('controller-step', 'model' if model else 'tool',
                            {'step_id': identity, 'request_sha256': cycle.ce.digest(request)}, dispatch,
                            output_tokens=node['parameters'].get('max_output_tokens', 0) if model else 0)


def governed_host(host):
    current = active()
    return GovernedHost(*current) if current is not None and not isinstance(host, GovernedHost) else host


def run_child(root, experiment, *, resume=False):
    """One ordinary child route, under its own authority and the parent's bounds."""
    current = active()
    if current is None:
        return None
    store, context = current
    spec = cycle._read(experiment['study'], cycle._load(root)[1]['base_dir'])
    identity = 'research-child-' + experiment['id']
    step = _step(identity, 'route', budget={'wall_seconds': experiment['cost']['wall_seconds'], 'children': 1})
    step['route'] = 'study'
    step['parameters'] = {'specification': spec, 'experiment': deepcopy(experiment),
                          'campaign': str(root), 'resume': resume, 'own_checkin1': True,
                          'inherit_authority': True, 'inherit_budget': True}
    step['obligations'] += ['P03', 'C34', 'MODE-research-comparison']
    from ravel.controller.routes.research import loop_budget
    try:
        # The child's projected cost at its own engagement tier must fit the approved loop budget.
        child = {'id': experiment['id'], 'route': step['route'],
                 'contract': {'deliverables': list(spec.get('outputs') or [])
                              if isinstance(spec.get('outputs'), list) else None}}
        from ravel.controller.routes.research import child_engagement as children
        # This is the exact governed dispatch, including the adopted ordinary specification;
        # it does not replace or approve the child's ordinary scientific plan.
        dispatch_plan = {'route': {'id': step['route']}, 'steps': [deepcopy(step)],
                         'checkins': [], 'deliverables': []}
        dispatch_plan['sha256'] = plan_sha256(dispatch_plan)
        _, decision, applied = children.prepare(store, child, dispatch_plan,
            loop_budget.verify(context.get('research_loop_budget')), identity,
            frozen_mode=context.get('mode') or {})
        step = applied['steps'][0]
    except loop_budget.LoopBudgetExhausted as exc:
        _loop_boundary(store, identity, exc)
    outcome = _outcome(store, step, {**context, 'child_rundir': experiment['rundir'],
                                   'research_child_decision': {'tier': decision['tier'],
                                                               'sha256': decision['sha256']}})
    from . import science
    science.verify_plan(experiment['rundir'], approved=True)
    packet = science.packet(experiment['rundir'])
    executed = science.execution.load_execution(experiment['rundir'])['stages'].get('science')
    if (executed is None or executed.get('status') != 'succeeded'
            or packet['execution']['status'] in {'invalid', 'failed'}):
        raise ValueError('completed research child lacks successful ordinary execution evidence')
    return 0


def invoke(store, step, context):
    """Invoke or resume research.loop as a governed, protected-checkpoint subgraph."""
    from . import graph_substrate, research_orchestrator as orchestrator
    from .graphs import hosts, research_loop
    parameters = step.get('parameters') or {}
    request = parameters.get('research_request', context.get('research_request'))
    from . import bounded_research
    derived_budget = None
    if request is None and 'research_request' not in parameters and 'research_request' not in context:
        request, derived_budget = bounded_research.bind(store, step, context)
    if not isinstance(request, dict) or not {'path', 'sha256'} <= request.keys():
        raise ValueError('research subgraph needs its adopted source-bound request pin')
    bounded_step = bounded_research.bound_record(store, step, request, context)
    campaign = cycle._ordinary(parameters.get('campaign') or (
        bounded_research.campaign_root(context['run_dir'], step) if bounded_step
        else Path(context['run_dir']) / 'campaign'))
    from ravel.controller.routes.research import loop_budget
    # The loop budget CHECK-IN 1 approved travels in the approved step's bytes; none, or a changed one, refuses.
    if bounded_step:
        if parameters.get('research_loop_budget', bounded_step['budget']) != bounded_step['budget']:
            raise ValueError('bounded research loop budget changed')
        budget = loop_budget.verify(derived_budget or bounded_step['budget'])
    else:
        budget = loop_budget.verify(parameters.get('research_loop_budget'))
    output = campaign / 'coordinator'
    runtime = cycle._read(request, Path(request['path']).parent)['runtime']
    context = {**deepcopy(context), 'research_max_wall_seconds': runtime['max_wall_seconds'],
               'research_campaign': str(campaign), 'research_loop_budget': deepcopy(budget)}
    if bounded_step:
        context['research_step_share'] = deepcopy(step['budget'])
    host = GovernedHost(store, context)
    before = len(_rows(store, 'research-step-outcome'))
    before_boundaries = len(_rows(store, 'research-budget-boundary'))
    with bound(store, context), hosts(host) as key:
        plan = orchestrator._open_plan(campaign, request, output, host=host)
        instance = orchestrator._loop_instance(plan, request)
        scope = store.path('research', cycle.ce.digest(instance))
        entry = {'parent_step': deepcopy(step), 'parent_step_sha256': cycle.ce.digest(step),
                 'parent_plan_sha256': context.get('plan_sha256'), 'request': deepcopy(request),
                 'campaign': str(campaign)}
        if entry not in _rows(store, 'research-subgraph-entry'):
            store.append('research-subgraph-entry', entry)
        parent = orchestrator._parent_rundir(plan)
        # The loop's gates decide on its campaign (research protocol) and on the parent run (every other provider).
        # A controller-owned scope carries that binding in the run's protected store, where the installed decision
        # gate reads it (an in-process gate seam is refused there); an uncontrolled scope keeps the explicit gates.
        from . import decision_gate
        scope.mkdir(parents=True, exist_ok=True)
        state_io.atomic_json(scope / decision_gate.RESEARCH_GATE_BINDING, {
            'schema_version': 1, 'kind': 'research-gate-binding', 'run_id': store.run_id,
            'run_dir': str(parent), 'campaign': str(campaign)})
        gates = ({} if graph_substrate.controller_scope(scope) is not None
                 else {'gate_check': orchestrator.campaign_gates(campaign, parent)})
        if context.get('responses'):
            observed = graph_substrate.respond(scope, research_loop.GRAPH_ID, instance,
                context['responses'], **gates)
        else:
            observed = graph_substrate.run(scope, research_loop.GRAPH_ID, instance,
                input={'loop': {'request': request, 'out': str(output), 'host': key,
                               'operation': plan['operation'], 'campaign_root': str(campaign)}, **plan['initial']},
                max_steps=4 * plan['steps'] + 64, **gates)
        result = orchestrator._graph_outcome(scope, plan, instance, observed)
        exhausted = [row for row in _rows(store, 'research-step-outcome')[before:]
                     if row['outcome'].get('status') == 'budget_exhausted']
        if exhausted:
            boundary = exhausted[-1]
            result = cycle.bounded_synthesis(campaign, boundary['outcome'].get('reason') or
                'governed research step budget exhausted', boundary={'step_id': boundary['step']['id'],
                'outcome': deepcopy(boundary['outcome'])})
        boundaries = _rows(store, 'research-budget-boundary')[before_boundaries:]
        if boundaries:
            boundary = boundaries[-1]
            result = cycle.bounded_synthesis(campaign, boundary['reason'], boundary=boundary)
    return _finish(store, step, context, campaign, scope, request, observed, result)


def _finish(store, step, context, campaign, scope, request, observed, result):
    """Retain qualified progress and route actual bounded endings to the sole sink."""
    output = Path(context['run_dir']) / 'steps' / step['id'] / 'outputs/progress.json'
    from . import bounded_research
    bounded = bounded_research.bound_record(store, step, request, context)
    if bounded and result.get('kind') == 'research_bounded_synthesis':
        from . import research_protocol
        result['labels'] = [bounded_research.LABEL]
        result['qualification'] = {'kind': 'bounded_sub_question', 'request': request,
            'scientific_acceptance': False,
            'pending_protocol_stages': research_protocol.methodology_status(campaign)['pending']}
        status = 'completed'
    elif result.get('phase') == 'budget_exhausted':
        key = cycle.ce.digest({'step_id': step['id'], 'result': result})
        prior = next((row for row in _rows(store, 'research-bounded-delivery') if row['key'] == key), None)
        receipt = (prior['receipt'] if prior else _service('sink').bounded_end(store, result['reason']))
        if prior is None:
            store.append('research-bounded-delivery', {'key': key, 'receipt': receipt})
        result['delivery_receipt'] = deepcopy(receipt)
        status = 'budget_exhausted'
    elif result.get('kind') == 'research_progress_synthesis':
        status = 'completed'
    elif result.get('phase') in {'ordinary_effect_required', 'paused', 'hold', 'stopped'}:
        status = 'held'
    else:
        status = 'failed'
    outputs = ([Path(context['run_dir']) / 'steps' / step['id'] / row['path']
                for row in step['outputs']] if bounded and status == 'completed' else [output])
    pins = []
    for output in outputs:
        state_io.atomic_json(output, result)
        pins.append(cycle._pin(output))
    store.append('research-subgraph', {'step_id': step['id'], 'request': request,
        'campaign': str(campaign), 'scope': str(scope), 'observation': observed, 'result': result,
        'output': pins[0], 'status': status, 'outputs': pins})
    return {**result, 'controller_outcome': {'status': status, 'reason': result.get('reason') or result.get('phase'),
                                           'outputs': pins}}


def role_receipt(root, node_id, **kwargs):
    """Keep shared review credit authoritative for controller-launched CLI seats."""
    from . import agent_graph, review_independence
    receipt = agent_graph.role_receipt(root, node_id, **kwargs)
    run_id = receipt['transport'].get('controller_run_id')
    if run_id is None:
        return receipt
    with _LOCK:
        store = _STORES.get(run_id)
    if store is None:
        store = _service('store').RunStore(run_id)
    calls = [row for row in _rows(store, 'research-call')
             if row['request_id'] == receipt['request_id'] and row['node']['id'] == node_id]
    if len(calls) != 1:
        raise ValueError('controller research receipt has no unique protected dispatch')
    call = calls[0]
    public, pin = _read_output(call['outcome'], {'run_dir': call['run_dir']}, 'public-record.json')
    saved = cycle._graph_result(root, node_id)
    if (cycle.ce.digest(public) != receipt['public_value_sha256'] or pin != call['output']
            or cycle.ce.digest(saved['value']) != call['result_sha256']):
        raise ValueError('controller research output differs from protected adoption')
    decision = review_independence.decide(review_independence.graph_query(root, receipt))
    if decision.get('independent', decision.get('credited')) is not True:
        return receipt
    observed = call['observation']
    observation, attestation = receipt['execution_observation'], receipt['attestation']
    if (observation == 'unestablished' and receipt['transport'].get('execution_mode') == 'transport_attested_cli'
            and observed.get('attestation') == 'transport_attested'):
        observation, attestation = 'transport_attested_cli', observed['attestation']
    return {**receipt, 'execution_observation': observation, 'attestation': attestation,
            'controller_credit': decision}


def question_plan(store, request, context):
    """Use the judgment graph's documented request/plan/context input view."""
    from . import graph_registry, graph_substrate
    row = graph_registry.get('judgment.plan')
    scope = store.path('research-question')
    instance = {'run_id': store.run_id}
    with bound(store, context):
        graph = graph_substrate.build('judgment.plan', graph_substrate.BuildContext(
            scope_root=scope, graph_id='judgment.plan', version=row['version'], instance=instance, row=row),
            checkpointer=store.checkpointer())
        final = graph.invoke({'meta': {'graph_id': 'judgment.plan', 'version': row['version'],
                                     'scope_root': str(scope), 'instance': instance, 'path': []},
            'request': deepcopy(request), 'plan': None,
            'context': {**deepcopy(context), 'run_id': store.run_id}},
            config={'configurable': {'thread_id': store.run_id + ':research-question'}})
    plan = (final.get('results') or {}).get('plan')
    steps = plan.get('steps') if type(plan) is dict else None
    kinds = {'acquire', 'operate', 'author', 'derive', 'compare', 'review', 'synthesize',
             'ask', 'decide', 'subgraph', 'route'}
    if (type(steps) is not list or not steps or any(type(row) is not dict or
            type(row.get('id')) is not str or not row['id'] or row.get('kind') not in kinds
            for row in steps) or len({row['id'] for row in steps}) != len(steps)):
        raise ValueError('judgment graph did not produce a typed research plan')
    if (not {'steps', 'deliverables', 'waypoints', 'sha256'} <= set(plan)
            or type(plan['deliverables']) is not list or type(plan['waypoints']) is not list
            or plan['sha256'] != plan_sha256(plan)):
        raise ValueError('judgment graph did not produce a sealed typed research plan')
    store.append('research-question-plan', {'request_sha256': cycle.ce.digest(request), 'plan': plan})
    return plan
