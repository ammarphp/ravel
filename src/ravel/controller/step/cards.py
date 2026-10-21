"""Every field of the effective role card, applied where the step acts on it.

- identity: the card is the installed registry's effective card for a registered role, and the
  registry digest equals the one the run pinned at intake, so a registration fragment dropped
  later (a new role, a repointed alias) changes nothing for this run (G01, SW28);
- ``stop``: the worker's turns, wall seconds, broker calls and cost come from the card,
  narrowed by the step's budget share, never widened by an executor or graph default (CF02);
- ``output``: the card's declared outputs join the step's, every required one must be credited,
  and the final record is the card's schema with the controller's acknowledgement fields (CF05,
  CF06); ``sidecar`` adopts the final record beside the outputs;
- ``ownership``: an output that sets a quantity is the card's own quantity, and an input that
  carries another role's quantity is one the card declares it consumes or judges (CF07);
- ``knowledge.consult``: each trigger that fires for the step requires its consult (CF04);
- ``tools.exec_argv_prefixes``: grants nothing; no worker has an exec tool and a launch runs
  only the plan-approved argv (CF11);
- ``model``: tier and effort are requested at dispatch and compared with what ran (I08);
- ``escalation``: the escalation values the role may raise (CF01).
"""
from __future__ import annotations

from copy import deepcopy
from .services import StepHold

# The acknowledging form of each card output family (the instruction package's closed schemas).
CONTROLLER_SCHEMAS = {'producer': 'producer.v2', 'findings': 'findings.v3'}
TRIGGERS = ('before_first_smoke', 'on_use', 'failure', 'contested_node')
WORKER_LIMITS = (1, 100000)


def engagement_card(card, declared):
    """Apply the declared seat's restriction union without changing its catalogue card."""
    result = deepcopy(card)
    constraints = (declared or {}).get('constraints') or {}
    independence = result.setdefault('independence', {})
    sees = result.setdefault('sees', {})
    for field in ('distinct_actor_from',):
        independence[field] = sorted(set(independence.get(field) or []) | set(constraints.get(field) or []))
    independence['fresh_session'] = bool(independence.get('fresh_session') or constraints.get('fresh_session'))
    for field in ('forbidden_inputs', 'required_inputs'):
        sees[field] = sorted(set(sees.get(field) or []) | set(constraints.get(field) or []))
    forbidden = set(sees['forbidden_inputs']) | set((result.get('knowledge') or {}).get('forbidden') or [])
    if forbidden & set(sees['required_inputs']):
        raise StepHold('engagement_constraint_conflict', 'a seat cannot require a forbidden input')
    if constraints.get('blind'):
        independence['blind'] = sees['blind'] = True
        result.setdefault('requires', {})['blind'] = True
    return result


def resolve(role, context):
    """``(card, card_sha256, registry_sha256)`` for a registered role under the run's pinned registry."""
    from ravel.workflow import role_registry
    pinned = (context or {}).get('registry_sha256')
    if type(pinned) is not str or len(pinned) != 64:
        raise StepHold('role_registry_unpinned', 'intake pins the installed role registry digest for the run')
    try:
        document = role_registry.registry_document()
        current = role_registry.registry_sha256(document=document)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise StepHold('role_registry_unreadable', str(exc)[:500]) from None
    if current != pinned:
        raise StepHold('role_registry_changed', 'the installed role registry differs from the digest the run pinned '
                       'at intake; a registration added or repointed after intake is not this run\'s registry')
    if type(role) is not str or not role:
        raise StepHold('role_unregistered', 'the step names no role')
    if role not in document['roles']:
        # A step names a canonical role id; an alias is a host convenience, never a seat identity.
        reason = 'role_alias_not_canonical' if role in document.get('aliases', {}) else 'role_unregistered'
        raise StepHold(reason, f'role {role!r} is not a registered canonical role id')
    card = role_registry.load(role, document=document)
    if card.get('id') != role:
        raise StepHold('role_identity_changed', f'the effective card of {role} names another identity')
    return card, role_registry.card_sha256(role, document=document), current


def _narrow(card_value, share):
    if share is None:
        return card_value
    if card_value is None:
        return share
    return min(card_value, share)


def worker_budgets(card, step):
    """The worker spec budgets from the card's ``stop``, narrowed by the step's share."""
    stop = card['stop']
    share = step.get('budget') or {}
    turns = stop['max_turns']
    wall = _narrow(stop['max_wall_seconds'], share.get('wall_seconds'))
    calls = _narrow(stop['max_broker_calls'], share.get('broker_calls'))
    cost = _narrow(stop['max_cost_usd'], share.get('cost_usd'))
    low, high = WORKER_LIMITS
    budgets = {'max_turns': max(low, min(high, int(turns))), 'max_wall_seconds': max(low, min(high, int(wall))),
               # A card with no broker calls gets a one-call spec over an empty toolbelt: nothing executes.
               'max_broker_calls': max(low, min(high, int(calls))),
               'max_cost_usd': None if cost is None or cost == 0 else cost}
    minimum = (step.get('parameters') or {}).get('budget_minimum') or {}
    effective = {'wall_seconds': wall, 'broker_calls': calls,
                 'cost_usd': cost}
    for dimension, ceiling in effective.items():
        required = minimum.get(dimension, 1 if dimension == 'wall_seconds' else 0)
        if ceiling is not None and required > ceiling:
            raise StepHold('seat_budget_infeasible', 'the seat minimum exceeds its effective card limit',
                           evidence={'dimension': dimension, 'minimum': required, 'ceiling': ceiling})
    applied = {'card_stop': deepcopy(stop), 'step_share': deepcopy(share), 'budgets': budgets,
               'card_broker_calls': stop['max_broker_calls'], 'max_rounds': stop['max_rounds'],
               'evidence_budget': stop.get('evidence_budget', 0)}
    return budgets, applied


def declared_outputs(card, step):
    """The step's outputs and the card's declared outputs, as worker outputs under ``outputs/``.

    Each row keeps the plan path it adopts to (``plan_path``; a card-only output adopts to its own path).
    """
    from .spec import worker_path
    rows = {}
    for row in step['outputs']:
        path = worker_path(row['path'])
        rows[path] = {'path': path, 'plan_path': row['path'], 'kind': row['kind'],
                      'required': row.get('required', True)}
    for row in card['output']['declared_outputs']:
        path = worker_path(row['path'])
        if path in rows:
            rows[path]['required'] = rows[path]['required'] or row['required']
        else:
            rows[path] = {'path': path, 'plan_path': row['path'], 'kind': row['kind'], 'required': row['required']}
    return [rows[p] for p in sorted(rows)]


def worker_outputs(rows):
    """The dispatcher's declared-output rows (``path``, ``kind``, ``required``)."""
    return [{'path': row['path'], 'kind': row['kind'], 'required': row['required']} for row in rows]


def controller_schema(card):
    """The final-record schema id of the card's output in controller mode (acknowledgement fields added)."""
    declared = card['output']['schema']
    family = declared.rpartition('.v')[0]
    if family not in CONTROLLER_SCHEMAS:
        raise StepHold('output_schema_unmapped', f'card {card["id"]} output schema {declared} has no controller form')
    return CONTROLLER_SCHEMAS[family]


def ownership_errors(card, step, inputs_custody=()):
    """Quantities the step's outputs set that the card does not own, and consumed quantities it does not declare."""
    from .spec import quantities
    owns = set(card['ownership']['owns'])
    consumes = set(card['ownership']['inputs']) | set(card['ownership']['judges'])
    errors = []
    for path, quantity in quantities(step).items():
        if quantity is not None and quantity not in owns:
            errors.append({'code': 'ownership_not_owner', 'path': path, 'quantity': quantity,
                           'role': card['id'], 'owns': sorted(owns)})
    for record in inputs_custody:
        quantity = record.get('quantity')
        if quantity is not None and record.get('owner_role') != card['id'] and quantity not in consumes:
            errors.append({'code': 'ownership_input_undeclared', 'artifact': record.get('artifact'),
                           'quantity': quantity, 'role': card['id']})
    return errors


def exec_errors(card, belt=None):
    """``exec_argv_prefixes`` grants nothing: the worker toolbelt has no exec tool."""
    errors = []
    if belt is not None:
        names = {t['name'] for t in belt.get('tools', [])}
        actions = {(t.get('executes_through') or {}).get('action') for t in belt.get('tools', [])}
        if 'exec' in names or 'exec' in actions:
            errors.append({'code': 'exec_tool_present', 'role': card['id']})
    return errors


def consult_triggers(card, step, facts):
    """The card's consult rows whose trigger fires for this step, from controller facts only."""
    from ravel.workflow import consults
    fired = []
    tools = set(facts.get('operation_tools') or ())
    for row in card['knowledge']['consult']:
        when, role = row['when'], row['role']
        if when == 'before_first_smoke':
            hit = step.get('rung') == 'smoke' and not facts.get('smoke_done')
        elif when == 'on_use':
            bound = {t for b in consults.bindings()['consults'].values() if b['role'] == role for t in b['tools']}
            hit = bool(tools & bound)
        elif when == 'failure':
            hit = bool(facts.get('prior_failure'))
        elif when == 'contested_node':
            hit = bool(facts.get('contested'))
        else:
            hit = False
        if hit:
            fired.append({'role': role, 'when': when})
    return fired


def model_request(card):
    model = card['model']
    return {'tier': model['tier'], 'effort': model['effort']}


def escalation_values(card):
    return list(card['escalation'])
