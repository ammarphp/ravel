"""Controller-adopted method, cost and child planning inputs."""
from copy import deepcopy
from hashlib import sha256
from importlib.resources import files
import json

from .records import digest, latest, rows

METHOD_KIND = 'method-decision'
COST_KIND = 'method-cost-forecast'
CHILD_INPUT = 'engagement-child-input'


def prepare_outputs(steps):
    """Use existing preparation authors for request-bound method and cost records."""
    result = deepcopy(steps)
    authors = [s for s in result if (s.get('parameters') or {}).get('phase') == 'prepare'
               and s.get('role') and s['kind'] in ('author', 'derive', 'synthesize')]
    if not authors:
        return result
    for kind, filename in ((METHOD_KIND, 'method-decision.json'), (COST_KIND, 'method-cost-forecast.json')):
        if any(o.get('kind') == kind for s in result for o in s.get('outputs', [])):
            continue
        # A cost-producing preparation step already sees the selected method inputs.
        target = next((s for s in authors if kind == COST_KIND and any(
            o.get('kind') == 'cost-record' for o in s.get('outputs', []))), authors[-1])
        target.setdefault('outputs', []).append({'path': 'outputs/' + filename, 'kind': kind, 'required': True})
        target.setdefault('parameters', {})[kind] = {
            'schema': (json.loads(files('ravel').joinpath('data/methods/method-decision.schema.json').read_text())
                       if kind == METHOD_KIND else COST_KIND),
            'instruction': ('Write the cheapest sufficient validated method decision for the exact request. '
                            'Bind request_digest and every original obligation; state the cost forecast and stopping rule.'
                            if kind == METHOD_KIND else
                            'Write {schema_version: 1, kind: "method-cost-forecast", request_digest, '
                            'method_sha256, cost_forecast}. Use the canonical method digest and the same complete '
                            'cost_forecast as the selected method decision; retain unknown values explicitly.')}
    return result


def adopted_output(context, artifact):
    """Recheck a completed declared preparation producer and its accepted custody chain."""
    from ravel.controller.routes.study.contracts import adopted_json
    from ravel.controller.step import custody
    store, plan = context['store'], context['plan']
    sid, path = artifact.split(':', 1)
    producers = [s for s in plan['steps'] if s['id'] == sid
                 and (s.get('parameters') or {}).get('phase') == 'prepare'
                 and any(o.get('path') == path for o in s.get('outputs', []))]
    if len(producers) != 1:
        raise ValueError('planning output requires its declared preparation producer')
    outcome = custody.outcomes(store).get(sid) or {}
    if outcome.get('status') != 'completed':
        raise ValueError('planning producer requires a completed protected outcome')
    consumer = {'inputs': [{'artifact': artifact}], 'depends_on': [sid]}
    problems, pins, _ = custody.input_errors(store, consumer, context['run_dir'])
    if problems or len(pins) != 1 or pins[0].get('attempt') != outcome.get('attempt'):
        raise ValueError('planning output requires current accepted custody')
    return adopted_json(context, artifact)


def check_method(method, cost, request_digest):
    """Validate the installed ladder and the separate forecast's exact method binding."""
    from ravel.workflow.method_selection import validate_method_decision
    if validate_method_decision(method):
        raise ValueError('method_decision_invalid')
    if method['request_digest'] != request_digest:
        raise ValueError('method_decision_other_request')
    if (type(cost) is not dict or set(cost) != {'schema_version', 'kind', 'request_digest',
                                               'method_sha256', 'cost_forecast'}
            or type(cost['schema_version']) is not int or cost['schema_version'] != 1
            or cost['kind'] != COST_KIND or cost['request_digest'] != request_digest
            or cost['method_sha256'] != digest(method) or cost['cost_forecast'] != method['cost_forecast']):
        raise ValueError('method_cost_forecast_mismatch')
    return deepcopy(method)


def adopted_method(state, store, plan, request_digest):
    context = {'store': store, 'run_dir': state['run']['run_dir'], 'plan': plan}
    selected, sources = {}, {}
    for kind in (METHOD_KIND, COST_KIND):
        matches = [(s, o) for s in plan['steps'] for o in s.get('outputs', []) if o.get('kind') == kind]
        if len(matches) != 1:
            raise ValueError('planned_method_outputs_missing_or_ambiguous')
        step, output = matches[0]
        selected[kind], sources[kind] = adopted_output(context, step['id'] + ':' + output['path'])
    method = check_method(selected[METHOD_KIND], selected[COST_KIND], request_digest)
    if set(method['obligation_ids']) != {d['id'] for d in plan.get('deliverables', [])}:
        raise ValueError('method_obligations_differ_from_plan')
    adoption = {'plan_sha256': plan['sha256'], 'method_sha256': digest(method),
        'request_sha256': request_digest, 'sources': {k: {f: row[f] for f in ('artifact', 'sha256', 'destination')}
                                                    for k, row in sources.items()}}
    previous = latest(store, 'engagement-method-adoption') or {}
    if {k: v for k, v in previous.items() if k != 'record_id'} != adoption:
        store.append('engagement-method-adoption', adoption)
    return method


def child_values(child):
    """Recompute the child's complete facts from its typed plan, method and original scope."""
    from ravel.controller import graph, routes
    from . import facts, policy
    binding = child['engagement_planning']
    if type(binding) is not dict or set(binding) != {'plan', 'method', 'cost'}:
        raise ValueError('child planning requires plan, method and cost')
    plan, reading, contract = binding['plan'], child['reading'], child['contract']
    route = child.get('route') or 'study'
    if ((plan.get('route') or {}).get('id') != route or routes.plan_errors(plan, routes.find(route))
            or plan.get('reading_sha256') != digest(reading) or plan.get('contract_sha256') != digest(contract)
            or plan.get('open_obligations')):
        raise ValueError('child planning requires its complete original route and scope')
    prompt = contract.get('prompt')
    if type(prompt) is not str or not prompt.strip():
        raise ValueError('child planning requires its original request')
    method = check_method(binding['method'], binding['cost'], sha256(prompt.encode()).hexdigest())
    if set(method['obligation_ids']) != {d['id'] for d in plan['deliverables']}:
        raise ValueError('child method obligations differ from its original scope')
    novelty, problem = graph.plan_novelty(plan)
    if problem:
        raise ValueError(problem)
    expected = sorted(d['id'] for d in reading['deliverables'])
    actual = sorted(d['id'] for d in plan['deliverables'] if d.get('status', 'mapped') == 'mapped')
    if expected != actual or len(expected) != len(set(expected)):
        raise ValueError('child planning requires exact deliverable coverage')
    return {'route': route, 'deliverables': len(actual), 'consequence': facts.plan_consequence(plan),
            'compute': facts.plan_compute(method, plan, policy.load_policy()), 'novelty': novelty,
            'special': facts.special_flags(plan, contract, parent='none')}


def pin_children(context, children, artifact):
    """Pin validated child proposals from the parent's adopted preparation output for plan review."""
    value, source = adopted_output(context, artifact)
    if value != children:
        raise ValueError('child requests differ from adopted preparation')
    store = context['store']
    for child in children:
        if 'engagement_planning' not in child:
            continue
        values = child_values(child)
        body = {'child_sha256': digest(child), 'child_id': child['id'], 'values': values,
                'proposal': deepcopy(child),
                'source': {k: source[k] for k in ('artifact', 'destination', 'sha256')},
                'run_dir': str(context['run_dir'])}
        if not any({k: v for k, v in row.items() if k != 'record_id'} == body for row in rows(store, CHILD_INPUT)):
            store.append(CHILD_INPUT, body)


def child_items(store, plan):
    children = (plan.get('parameters') or {}).get('research_children') or []
    identities = {digest(child) for child in children}
    selected = {}
    for row in rows(store, CHILD_INPUT):
        if row.get('child_sha256') in identities:
            selected[row['child_sha256']] = row
    return [{'id': CHILD_INPUT, 'record_id': row['record_id'],
             'subject_sha256': digest({k: v for k, v in row.items() if k != 'record_id'}),
             'must_check': 'Check the child plan, original request, method, forecast and complete engagement facts.'}
            for row in selected.values()]


def child_facts(child, store, *, reviewed=False):
    from ravel.controller.routes.study.contracts import adopted_json
    from .facts import _reviewed, fact
    candidates = [r for r in rows(store, CHILD_INPUT) if r.get('child_sha256') == digest(child)]
    if not candidates:
        return {}
    row = candidates[-1]
    value, source = adopted_json({'store': store, 'run_dir': row['run_dir']}, row['source']['artifact'])
    if (any(source.get(k) != v for k, v in row['source'].items()) or type(value) is not list
            or len([c for c in value if c == child]) != 1 or child_values(child) != row['values']):
        return {}
    if reviewed:
        pin = latest(store, 'plan') or {}
        if not _reviewed(store, row, pin.get('plan_sha256')):
            return {}
    return {name: fact(value, row['record_id'], 'code:child-planning')
            for name, value in row['values'].items()}
