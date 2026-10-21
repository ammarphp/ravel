"""Deterministic controller binding for a single, non-executing sub-question.

Pending scientific protocol duties remain pending in the qualified synthesis.
This form authorizes one progress decision and no experiment or scientific vote.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import research_cycle as cycle, state_io

LABEL = 'BOUNDED SUB-QUESTION'
BINDING = 'research-bounded-step-binding'


def _write(path, value):
    path = cycle._ordinary(path)
    if path.exists():
        if state_io.read_json(path) != value:
            raise ValueError('bounded research binding bytes changed')
    else:
        state_io.atomic_json(path, value)
    return cycle._pin(path)


def origin(pin):
    value = cycle._read(pin, Path(pin['path']).parent)
    cycle.ce.keys(value, {'schema_version', 'kind', 'step', 'step_sha256', 'plan_sha256',
                          'question', 'outputs', 'contract', 'reading'})
    if (value['schema_version'] != 1 or value['kind'] != 'bounded-research-step'
            or value['step_sha256'] != cycle.ce.digest(value['step'])
            or value['question'] != value['step'].get('description')
            or value['outputs'] != value['step']['outputs']
            or not value['plan_sha256']):
        raise ValueError('bounded research requires exact approved step provenance')
    cycle._text(value['question'])
    for key in ('contract', 'reading'):
        cycle._check_pin(value[key], Path(pin['path']).parent)
    return value


def bounds(value):
    share = value['step']['budget']
    wall = share.get('wall_seconds')
    tokens = share.get('tokens', 2048)
    calls = share.get('broker_calls', share.get('model_calls', 1))
    if (type(wall) is not int or wall < 1 or type(tokens) is not int or tokens < 16
            or type(calls) is not int or calls < 1):
        raise ValueError('bounded research needs one decision within its declared step share')
    return {'model': 'controller-selected', 'reasoning_effort': 'high', 'adapter': 'model',
            # Keep deterministic room for preparation and admission inside the
            # original campaign deadline; a worker cannot reserve that whole deadline.
            'max_output_tokens': min(tokens, 32000), 'max_wall_seconds': min(max(1, wall // 2), 86400)}, {
        'id': 'bounded-' + value['step_sha256'][:24],
        'budget': {'calls': 1, 'output_tokens': min(tokens, 32000), 'wall_seconds': wall,
                   'native_attempts': 0},
        'max_experiments': 0, 'exploration_every': 1, 'required_experiments': [], 'premises': []}


def validate(value):
    """The request schema's additional, narrowing-only bounded-form contract."""
    source = origin(value['bounded_step'])
    runtime, campaign = bounds(source)
    if (value['runtime'] != runtime or value['campaign'] != campaign or value['max_decisions'] != 1
            or value['parent_contract'] != source['contract']
            or value['review'] != {'arguments': {}, 'allow_control': False}
            or any(value[key] is not None for key in ('knowledge', 'context_request', 'direct_mapping'))):
        raise ValueError('bounded research request differs from its approved step bounds')
    return source


def bind(store, step, context):
    """Pin frozen intake and approved step bytes once; re-entry checks all bytes."""
    records = [row.get('record', row) for row in store.scan('intake')]
    if len(records) != 1:
        raise ValueError('bounded research needs the unique frozen parent intake')
    root = Path(context['run_dir']) / 'inputs' / 'bounded-research' / step['id']
    root.mkdir(parents=True, exist_ok=True)
    # The run's own intake copies, verified against the frozen intake blobs: their relative references
    # (the request plan) resolve from the run's inputs exactly as they do for the research route itself.
    names = {'contract': 'task_contract.json', 'reading': 'reading.json'}
    sources = {}
    for key in ('contract', 'reading'):
        wanted = records[0][key + '_blob']
        raw = store.get_blob(wanted)
        if hashlib.sha256(raw).hexdigest() != wanted:
            raise ValueError('bounded research parent ' + key + ' changed')
        target = cycle._ordinary(Path(context['run_dir']) / 'inputs' / names[key])
        if not target.is_file() or target.read_bytes() != raw:
            raise ValueError('bounded research needs the run\'s unchanged intake ' + key)
        sources[key] = cycle._pin(target)
    source = {'schema_version': 1, 'kind': 'bounded-research-step', 'step': deepcopy(step),
              'step_sha256': cycle.ce.digest(step), 'plan_sha256': context['plan_sha256'],
              'question': step.get('description'), 'outputs': deepcopy(step['outputs']), **sources}
    source_pin = _write(store.path('bounded-research', step['id'] + '.json'), source)
    runtime, campaign = bounds(source)
    from . import intake, research_coordinator_decisions as decisions, research_orchestrator as orch
    handoff = intake.execution_handoff(sources['contract'], base_dir=Path(sources['contract']['path']).parent)
    ids = [row['id'] for row in handoff['obligations']]
    api = cycle._pin(orch.__file__)
    planning = {'schema_version': 1, 'task_id': campaign['id'], 'task': source['question'],
        'source_capsules': [], 'api_documents': [{'id': 'coordinator',
            'pin': {k: api[k] for k in ('path', 'sha256')}, 'language': 'python', 'role': 'api',
            'version': api['sha256'], 'dependencies': []}],
        'queries': [{'id': 'bounded-progress', 'symbol': '_open_plan', 'mode': 'definition',
                     'documents': ['coordinator'], 'required': True}],
        'requested_quantities': [{'id': 'pending-obligations', 'artifact': 'planning-status',
            'pointer': '/obligations', 'check': {'kind': 'symbolic-record-census', 'id_field': 'id',
            'expected_ids': ids, 'text_fields': ['basis']},
            'meaning': 'Planning census only; original scientific obligations remain open.'}],
        'compatibility_groups': [{'id': 'planning-only', 'artifacts': ['planning-status'],
            'carryover': False, 'basis': 'Bounded progress is no scientific acceptance.'}],
        'max_source_bytes': cycle.scientific_context.MAX_SOURCE,
        'max_context_bytes': cycle.scientific_context.MAX_CONTEXT, 'max_steps': 1}
    planning_pin = _write(root / 'planning-context.json', planning)
    value = {'schema_version': 1, 'kind': 'open-research-request', 'parent_contract': sources['contract'],
        'handoff': handoff, 'campaign': campaign, 'runtime': runtime,
        'evidence': [{'pin': sources['reading'], 'purpose': 'model_context'}],
        'candidate_modes': [row['mode'] for row in decisions.catalogue(None)['operations']],
        'review': {'arguments': {}, 'allow_control': False}, 'max_decisions': 1, 'knowledge': None,
        'context_request': None, 'planning_context': planning_pin, 'direct_mapping': None,
        'research_regime': 'open_exploratory', 'bounded_step': source_pin}
    pin = _write(root / 'request.json', value)
    decisions.request(pin)
    from ravel.controller.routes.research import loop_budget
    budget = loop_budget.declare(value, [], tier='lean')
    cost = step['budget'].get('cost_usd')
    if cost is not None:
        budget['cost_ceiling_usd'] = min(budget['cost_ceiling_usd'], cost)
        budget['sha256'] = loop_budget.digest({k: v for k, v in budget.items() if k != 'sha256'})
    record = {'step_id': step['id'], 'origin': source_pin, 'request': pin, 'budget': budget, 'label': LABEL}
    prior = [row.get('record', row) for row in store.scan(BINDING)
             if row.get('record', row).get('step_id') == step['id']]
    if prior and prior != [record]:
        raise ValueError('bounded research protected request or budget changed')
    if not prior:
        store.append(BINDING, record)
    return pin, budget


def campaign_root(run_dir, step):
    """The bounded sub-question's own campaign folder in the parent run (never the whole-goal ``campaign``)."""
    return Path(run_dir) / ('campaign-' + step['id'])


def bound_record(store, step, pin, context=None):
    rows = [row.get('record', row) for row in store.scan(BINDING)
            if row.get('record', row).get('step_id') == step['id']]
    if not rows:
        return None
    if len(rows) != 1 or rows[0]['request'] != pin:
        raise ValueError('bounded research adopted request pin changed')
    source = origin(rows[0]['origin'])
    if source['step'] != step:
        raise ValueError('bounded research approved step changed')
    if context is not None and source['plan_sha256'] != context.get('plan_sha256'):
        raise ValueError('bounded research approved plan changed')
    return rows[0]
