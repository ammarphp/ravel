"""The research loop budget: declared and projected before CHECK-IN 1, enforced at every cycle and child.

A research campaign spends in two places the route's own engagement projection does not count: the
coordinator's decision cycles (one next-action decision plus one protocol-stage review round) and the
ordinary child experiments it admits (each a full route run). ``declare`` builds, from the adopted
campaign request and the installed engagement calibration, a loop budget the plan carries and CHECK-IN 1
approves: the maximum cycles and children, the cost, token and call ceilings, and the projected cost of
one cycle and of each declared child at the child's own engagement tier. The research controller admits
each cycle and child against it (``admit``): a cycle or child whose projected high cost no longer fits the
approved remainder is refused, and the campaign ends qualified through its ordinary bounded synthesis.

Projections use ``engagement.envelope.project`` over code-built sessions with the installed calibration;
they are planning bounds, never measurements. Actual spending stays bounded by every governed step's own
reservation against the operator's envelope.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math

LEVELS = ('low', 'central', 'high')
METRICS = ('sessions', 'calls', 'input_tokens', 'output_tokens', 'cost_usd')
RESERVATION = 'research-loop-reservation'
ADAPTIVE_CHILD = 'adaptive-study-child'
DECISION = 'research-cycle-decision'
STOP_RULE = ('Every action requires information_gain: decision (continue or stop), expected_gain, '
             'cost_justification against loop_budget.per_cycle, and evidence_input_ids naming presented inputs. '
             'Choose continue only when the expected information justifies the projected cost; choose stop and '
             'synthesize or progress otherwise. The controller records and enforces this judgment before the '
             'chosen action, and refuses further cycles or children after stop. It also refuses a cycle or child whose projected '
             'high cost exceeds the approved remainder, and the campaign then ends qualified.')
BASIS = ('engagement.envelope.project over code-built sessions with the installed calibration: a cycle is one '
         'coordinator decision (judgment category, its packet plus the capability catalogue it receives) and one '
         'protocol stage round (one review session per stage role); packet sizes are the installed research route '
         'packets of the same category (median). A child '
         'is its route\'s installed envelope at the tier the engagement policy computes from the child\'s own '
         'code-checked facts. Planning bounds, not measurements.')


class LoopBudgetExhausted(ValueError):
    """The next cycle or child does not fit the approved research loop budget."""


class ChildProjectionMismatch(LoopBudgetExhausted):
    """Execution no longer matches the child's priced reservation."""


class InformationGainStopped(LoopBudgetExhausted):
    """The recorded information gain does not justify further work."""

    kind = 'research_information_gain'


def assessment_schema():
    """A qualitative, source-backed judgment, without a universal numerical gain estimator."""
    text = {'type': 'string', 'minLength': 1, 'maxLength': 16000}
    fields = {'decision': {'type': 'string', 'enum': ['continue', 'stop']},
              'expected_gain': text, 'cost_justification': text,
              'evidence_input_ids': {'type': 'array', 'minItems': 1, 'maxItems': 128,
                                     'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}}}
    return {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}


def record_decision(store, budget, admission, public, inputs, *, output, observation_sha256):
    """Bind the observed judgment to its admitted cycle and refuse a contradicting action before dispatch."""
    from pathlib import Path
    from ravel.validation.core import validate_value
    verify(budget)
    assessment = validate_value(public.get('information_gain'), assessment_schema())
    if not all(assessment[key].strip() for key in ('expected_gain', 'cost_justification')):
        raise ValueError('information-gain judgment requires substantive gain and cost reasons')
    evidence = []
    for identity in assessment['evidence_input_ids']:
        matches = [row for row in inputs if row.get('id') == identity]
        if len(matches) != 1 or identity in [row['id'] for row in evidence]:
            raise ValueError('information-gain evidence must name distinct presented inputs')
        pin = matches[0]
        raw = Path(pin['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('information-gain evidence changed after presentation')
        evidence.append({'id': identity, 'path': pin['path'], 'sha256': pin['sha256'], 'size': len(raw)})
    reservations = [row for row in _rows(store, RESERVATION) if row == admission]
    if (not reservations or admission['kind'] != 'cycle' or admission['budget_sha256'] != budget['sha256']):
        raise ValueError('information-gain decision requires its admitted cycle')
    stopping = assessment['decision'] == 'stop'
    terminal = public.get('action') in {'synthesize', 'progress'}
    record = {'step_id': admission['key'], 'action': public.get('action'), 'reason': public.get('reason'),
              'assessment': deepcopy(assessment), 'evidence': evidence,
              'action_admitted': stopping == terminal, 'output': deepcopy(output),
              'observation_sha256': observation_sha256,
              'projected_high_usd': admission['projected_high_usd'],
              'remaining_before_usd': admission['remaining_before_usd'],
              'budget_sha256': budget['sha256'], 'next_cycle_projection': deepcopy(budget['per_cycle'])}
    prior = [row for row in _rows(store, DECISION) if row.get('budget_sha256') == budget['sha256']
             and row.get('step_id') == admission['key']]
    if prior and prior != [record]:
        raise ValueError('information-gain decision differs from its recorded cycle')
    if not prior:
        store.append(DECISION, record)
    if stopping and not terminal:
        raise InformationGainStopped('recorded information-gain stop: ' + assessment['cost_justification'])
    if not stopping and terminal:
        raise ValueError('information-gain continue contradicts a terminal research action')
    return record


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _installed():
    from ravel.controller.engagement import envelope, policy
    from ravel.controller.engagement.envelope import data
    return envelope.installed_projection(), data('calibration.json'), policy.load_policy()


def _median(values):
    values = sorted(v for v in values if type(v) in (int, float))
    if not values:
        raise ValueError('the installed research route projection has no packets of this category')
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _rounded(row):
    return {m: (round(row[m], 6) if m == 'cost_usd' else math.ceil(row[m])) for m in METRICS}


def cycle_projection(protocol, installed, calibration, tier):
    """Per protocol stage, the projected cost of one cycle that runs it; ``per_cycle`` is the dearest stage."""
    from ravel.controller.engagement.envelope import project
    packets = (installed['packets'].get('research') or {}).get(tier) or []
    sizes = {category: _median([p['packet_tokens'] for p in packets if p['category'] == category])
             for category in ('producer', 'review')}
    units = {category: _median([p['duty_units'] for p in packets if p['category'] == category])
             for category in ('producer', 'review')}
    # The coordinator's decision also receives the whole capability catalogue as a normal input.
    from ravel.controller import capabilities
    from ravel.controller.engagement.builder import math_tokens
    catalogue = math_tokens(json.dumps(capabilities.catalogue(), sort_keys=True, indent=2) + '\n')
    stages = {}
    for stage in protocol['stages']:
        sessions = [{'category': 'judgment', 'packet_tokens': sizes['producer'] + catalogue,
                     'duty_units': units['producer'], 'conditional': False}]
        sessions += [{'category': 'review', 'packet_tokens': sizes['review'], 'duty_units': units['review'],
                      'conditional': False} for _ in stage['roles']]
        projected = project(sessions, calibration)
        stages[stage['id']] = {level: _rounded(projected[level]) for level in LEVELS}
    per_cycle = {level: {m: max(stages[s][level][m] for s in stages) for m in METRICS} for level in LEVELS}
    return {'stages': stages, 'per_cycle': per_cycle}


def child_facts(child, *, store=None, reviewed=False):
    """The engagement facts a child experiment carries that code can check; everything else stays unknown."""
    from ravel.controller.engagement.facts import fact
    route = child.get('route') or 'study'
    facts = {'route': fact(route, 'research child route', 'code:research-child')}
    outputs = (child.get('contract') or {}).get('deliverables')
    if type(outputs) is list:
        facts['deliverables'] = fact(len(outputs), 'research child contract deliverables', 'code:research-child')
    if store is not None:
        from ravel.controller.engagement import planning
        try:
            facts.update(planning.child_facts(child, store, reviewed=reviewed))
        except (ValueError, KeyError, TypeError, OSError):
            pass
    return facts


def child_projection(child, installed, policy_document, *, minimum_tier=None, store=None, reviewed=False):
    """A child's own engagement tier (from its own facts) and its route's installed envelope at that tier."""
    from ravel.controller.engagement.policy import tier as compute_tier, raise_only
    route = child.get('route') or 'study'
    facts = child_facts(child, store=store, reviewed=reviewed)
    computed = compute_tier(facts, policy_document)
    selected = raise_only(computed['tier'], minimum_tier)
    row = (installed['routes'].get(route) or {}).get(selected)
    if not row or row.get('status') != 'ready':
        raise ValueError(f'no installed engagement projection for child route {route!r} at tier {selected!r}')
    return {'id': child['id'], 'route': route, 'tier': selected, 'facts_sha256': digest(facts),
            'policy_sha256': policy_document['sha256'],
            'tier_reasons': [{'fact': r['fact'], 'minimum_tier': r['minimum_tier'], 'rule': r['rule']}
                             for r in computed['reasons']],
            'projected': {level: _rounded(row[level]) for level in LEVELS}}


def check_execution(reservation, projection):
    """A replay or raised tier cannot spend a reservation made for different facts or pricing."""
    admitted = reservation.get('projection')
    if (reservation.get('kind') != 'child' or admitted != projection
            or reservation.get('projected_high_usd') != projection['projected']['high']['cost_usd']):
        raise ChildProjectionMismatch('child execution differs from its admitted tier, facts or cost; '
                                      'renew the approved loop budget and admission before dispatch')


def _envelope(store, state):
    """The operator's frozen envelope ceilings for cost, tokens and calls, or None when the run has none."""
    try:
        from ravel.controller.step import budget
        ceilings = budget.envelope(store, {'mode': (state or {}).get('mode')})
    except Exception:  # no frozen operating mode: the declared projection alone bounds the loop
        return None
    return {'cost_usd': ceilings.get('cost_usd'), 'tokens': ceilings.get('tokens'),
            'model_calls': ceilings.get('model_calls')}


def declare(request, children, *, tier='full', store=None, state=None):
    """The loop budget for an adopted campaign request (``research_coordinator_decisions.request``)."""
    from ravel.workflow.research_protocol import default_protocol
    installed, calibration, policy_document = _installed()
    max_cycles = request['max_decisions']
    max_children = request['campaign']['max_experiments']
    cycles = cycle_projection(default_protocol(), installed, calibration, tier)
    projected_children = [child_projection(child, installed, policy_document, store=store) for child in children]
    # A child the campaign admits later (adaptive) is an ordinary study child; its slot is priced from the facts
    # such a child carries before its own intake, which the policy resolves conservatively.
    adaptive = child_projection({'id': ADAPTIVE_CHILD, 'route': 'study'}, installed, policy_document)
    slots = max(0, max_children - len(projected_children))
    child_high = adaptive['projected']['high']['cost_usd']
    totals = {}
    for level in LEVELS:
        declared = sum(c['projected'][level]['cost_usd'] for c in projected_children)
        totals[level] = round(max_cycles * cycles['per_cycle'][level]['cost_usd'] + declared
                              + slots * adaptive['projected'][level]['cost_usd'], 6)
    envelope = _envelope(store, state) if store is not None else None
    ceiling = totals['high'] if not envelope or envelope.get('cost_usd') is None else min(
        totals['high'], envelope['cost_usd'])
    body = {'schema_version': 1, 'kind': 'research-loop-budget', 'tier': tier,
            'max_cycles': max_cycles, 'max_children': max_children,
            'campaign_ceilings': deepcopy(request['campaign']['budget']),
            'cost_ceiling_usd': ceiling, 'operator_envelope': envelope,
            'per_cycle': cycles['per_cycle'], 'per_stage': cycles['stages'], 'children': projected_children,
            'adaptive_child': adaptive, 'adaptive_child_high_usd': child_high, 'projected_total_usd': totals,
            'exceeds_operator_envelope': bool(envelope and envelope.get('cost_usd') is not None
                                              and totals['central'] > envelope['cost_usd']),
            'stop_rule': STOP_RULE, 'basis': BASIS}
    return {**body, 'sha256': digest(body)}


def verify(budget):
    """Raise unless ``budget`` is a sealed loop budget."""
    if type(budget) is not dict or budget.get('kind') != 'research-loop-budget':
        raise LoopBudgetExhausted('the research step carries no approved loop budget')
    if budget.get('sha256') != digest({k: v for k, v in budget.items() if k != 'sha256'}):
        raise LoopBudgetExhausted('the research loop budget changed after its approval')
    return budget


def _rows(store, kind):
    return [row.get('record', row) for row in store.scan(kind)]


def committed(store, budget):
    """The approved budget's admitted cycles, children and committed projected high cost so far."""
    rows = [r for r in _rows(store, RESERVATION) if r.get('budget_sha256') == budget['sha256']]
    return {'cycles': sum(r['kind'] == 'cycle' for r in rows), 'children': sum(r['kind'] == 'child' for r in rows),
            'cost_usd': round(sum(r['projected_high_usd'] for r in rows), 6), 'keys': {r['key'] for r in rows}}


def admit(store, budget, kind, key, *, child=None, minimum_tier=None):
    """Admit one cycle or child against the approved loop budget, once per key, or raise ``LoopBudgetExhausted``.

    The admission commits the item's projected high cost. A key already admitted (a resumed or replayed call)
    is not charged again.
    """
    verify(budget)
    projection = None
    if kind == 'child':
        projection = child_projection({'id': (child or {}).get('id') or ADAPTIVE_CHILD,
                                      **{k: v for k, v in (child or {}).items() if k != 'id'}},
                                     *_installed()[::2], minimum_tier=minimum_tier, store=store, reviewed=True)
        declared = next((c for c in budget['children'] if c['id'] == projection['id']), None)
        if declared is not None:
            check_execution({'kind': 'child', 'projection': declared,
                             'projected_high_usd': declared['projected']['high']['cost_usd']}, projection)
    used = committed(store, budget)
    decisions = [row for row in _rows(store, DECISION) if row.get('budget_sha256') == budget['sha256']]
    if decisions and decisions[-1]['assessment']['decision'] == 'stop' and not (
            kind == 'cycle' and key == decisions[-1]['step_id']):
        raise InformationGainStopped('recorded information-gain stop: '
                                     + decisions[-1]['assessment']['cost_justification'])
    if key in used['keys']:
        prior = next(r for r in _rows(store, RESERVATION) if r.get('budget_sha256') == budget['sha256']
                     and r['key'] == key)
        if kind == 'child':
            check_execution(prior, projection)
        return prior
    if kind == 'cycle':
        if used['cycles'] >= budget['max_cycles']:
            raise LoopBudgetExhausted(f"approved research loop budget: {budget['max_cycles']} cycles used")
        cycles = [row for row in _rows(store, RESERVATION) if row.get('budget_sha256') == budget['sha256']
                  and row['kind'] == 'cycle']
        if cycles and not any(row['step_id'] == cycles[-1]['key'] and row['action_admitted'] for row in decisions):
            raise LoopBudgetExhausted('the previous research cycle has no admitted information-gain decision')
        cost = budget['per_cycle']['high']['cost_usd']
        projection = None
    elif kind == 'child':
        if used['children'] >= budget['max_children']:
            raise LoopBudgetExhausted(f"approved research loop budget: {budget['max_children']} children used")
        cost = projection['projected']['high']['cost_usd']
    else:
        raise ValueError('a research loop admission is a cycle or a child')
    if used['cost_usd'] + cost > budget['cost_ceiling_usd']:
        raise LoopBudgetExhausted(
            f"approved research loop budget: the next {kind} projects {cost:.2f} USD (high) and only "
            f"{budget['cost_ceiling_usd'] - used['cost_usd']:.2f} USD of {budget['cost_ceiling_usd']:.2f} remain")
    record = {'budget_sha256': budget['sha256'], 'kind': kind, 'key': key, 'projected_high_usd': cost,
              'remaining_before_usd': round(budget['cost_ceiling_usd'] - used['cost_usd'], 6),
              'projection': deepcopy(projection)}
    if kind == 'cycle':
        record['presented_budget'] = view(store, budget)
    store.append(RESERVATION, record)
    return record


def view(store, budget):
    """What the coordinator sees before choosing: the approved budget, what is committed and the stop rule."""
    used = committed(store, budget)
    return {'max_cycles': budget['max_cycles'], 'max_children': budget['max_children'],
            'cycles_used': used['cycles'], 'children_used': used['children'],
            'cost_ceiling_usd': budget['cost_ceiling_usd'], 'committed_high_usd': used['cost_usd'],
            'remaining_usd': round(budget['cost_ceiling_usd'] - used['cost_usd'], 6),
            'per_cycle': deepcopy(budget['per_cycle']), 'children': deepcopy(budget['children']),
            'stop_rule': budget['stop_rule'], 'basis': budget['basis']}


def checkin_section(budget):
    """CHECK-IN 1 material: the loop budget the approval binds."""
    lines = [f"Up to {budget['max_cycles']} coordinator cycles and {budget['max_children']} child experiments.",
             f"Projected cost per cycle (low/central/high): " + ' / '.join(
                 f"{budget['per_cycle'][level]['cost_usd']:.2f}" for level in LEVELS) + ' USD.']
    for child in budget['children']:
        lines.append(f"Child {child['id']} ({child['route']}, tier {child['tier']}): " + ' / '.join(
            f"{child['projected'][level]['cost_usd']:.2f}" for level in LEVELS) + ' USD.')
    lines.append('Projected loop total (low/central/high): ' + ' / '.join(
        f"{budget['projected_total_usd'][level]:.2f}" for level in LEVELS) + ' USD; approved ceiling '
        f"{budget['cost_ceiling_usd']:.2f} USD.")
    lines.append(budget['stop_rule'])
    return {'id': 'research_loop_budget', 'title': 'Research loop budget', 'lines': lines,
            'sha256': budget['sha256']}


__all__ = ['ChildProjectionMismatch', 'InformationGainStopped', 'LoopBudgetExhausted', 'admit', 'assessment_schema',
           'check_execution', 'checkin_section', 'committed', 'declare', 'record_decision', 'verify', 'view']
