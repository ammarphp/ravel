"""Narrow actual expanded step ceilings within an operator's finite envelope."""
from copy import deepcopy
import math
from pathlib import Path

from . import compiler

FLOAT_DIMENSIONS = frozenset(('cost_usd', 'core_hours'))
RESOURCE_UNITS = {'wall_seconds': 'seconds', 'events': 'events'}


class BudgetInfeasible(ValueError):
    """Declared work minima cannot fit the operator's resource envelope."""

    code = 'plan_budget_infeasible'

    def __init__(self, dimension, required, available, steps):
        self.evidence = {'dimension': dimension, 'required': required, 'available': available,
                         'steps': list(steps)}
        self.remedy = 'reduce the declared work or increase the operator envelope'
        super().__init__(f'{self.code}: {dimension} requires {required}, available {available}; {self.remedy}')


def _number(value, dimension):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'budget {dimension} requires a finite nonnegative number')
    if dimension not in FLOAT_DIMENSIONS and type(value) is not int:
        raise ValueError(f'budget {dimension} requires an integer')


def _nongenerating(step, signatures):
    from ravel.validation.validate_request_plan import EFFECTS
    params = step.get('parameters') or {}
    if 'execution_effects' in params:
        effects = params['execution_effects']
        if (type(effects) is not list or any(type(e) is not str or e not in EFFECTS for e in effects)
                or len(set(effects)) != len(effects)):
            raise ValueError('execution_effects requires an explicit list of distinct registered effects')
    else:
        signature = signatures.get(step.get('operation'))
        if signature is None:
            return False
        effects = signature.get('effects')
        if type(effects) is not list or any(type(e) is not str or e not in EFFECTS for e in effects):
            return False
    return 'generates_events' not in effects


def _operation_ceiling(step, signatures):
    """A resolved resource ceiling and valid requested work; leave invalid requests to admission."""
    from ravel.controller.step import operations
    signature = signatures.get(step.get('operation'))
    if signature is None:
        return None
    cost = signature.get('cost') or {}
    path = cost.get('ceiling_pointer')
    dimension = operations.POINTER_DIMENSIONS.get(path)
    if dimension is None or dimension not in step.get('budget', {}):
        return None
    parameters = step.get('parameters') or {}
    ceiling = operations.pointer(parameters.get('task') or {}, path)
    if type(ceiling) not in (int, float) or not math.isfinite(ceiling) or ceiling < 0:
        return None
    requested = parameters.get('cost')
    minimum = 0
    if requested is not None:
        if (type(requested) is not dict or requested.get('unit') != cost.get('unit')
                or type(requested.get('amount')) not in (int, float)
                or not math.isfinite(requested['amount']) or not 0 <= requested['amount'] <= ceiling):
            return None
        if requested['unit'] == RESOURCE_UNITS.get(dimension):
            minimum = requested['amount']
            if dimension not in FLOAT_DIMENSIONS:
                minimum = math.ceil(minimum)
    return dimension, path, ceiling, minimum


def narrow_plan(plan, envelope, *, frozen_ids=()):
    """Return a copied plan; retain attempts, frozen budgets and undeclared dimensions.

    Envelope keys use authority names (including ``model_calls``). Missing or
    null envelope dimensions are unbounded. Explicit minima use step budget names.
    """
    from ravel.controller.authority.operator import BUDGET_KEYS
    from ravel.workflow.operation_registration import read_signatures

    if type(envelope) is not dict or set(envelope) - set(BUDGET_KEYS):
        raise ValueError('the operator envelope must name authority budget dimensions')
    for dimension, value in envelope.items():
        if value is not None:
            _number(value, dimension)
    changed = deepcopy(plan)
    steps = changed['steps']
    frozen = set(frozen_ids)
    signatures = read_signatures(Path(__file__).resolve().parents[2] / 'data/operation_signatures.json')
    minima, operation_ceilings = {}, {}
    for step in steps:
        budget = step.get('budget', {})
        if type(budget) is not dict:
            raise ValueError('step budget must be an object')
        compiler.authority_budget(budget, step=step['id'])
        for dimension, value in budget.items():
            _number(value, dimension)
        declared = (step.get('parameters') or {}).get('budget_minimum', {})
        if type(declared) is not dict:
            raise ValueError('budget_minimum must be an object')
        compiler.authority_budget(declared, step=step['id'])
        for dimension, value in declared.items():
            _number(value, dimension)
            if dimension == 'attempts' or dimension not in budget:
                raise ValueError('budget_minimum must name a declared resource dimension')
        nongenerating = _nongenerating(step, signatures)
        if nongenerating and step['id'] not in frozen:
            if declared.get('events', 0) > 0:
                raise BudgetInfeasible('events', declared['events'], 0, [step['id']])
            step.setdefault('budget', {})['events'] = 0
            budget = step['budget']
        operation_ceilings[step['id']] = _operation_ceiling(step, signatures)
        step_minima = {}
        for dimension, ceiling in budget.items():
            if dimension == 'attempts':
                continue
            minimum = declared.get(dimension, 0)
            constraint = operation_ceilings[step['id']]
            if constraint is not None and constraint[0] == dimension:
                minimum = max(minimum, constraint[3])
            if dimension == 'wall_seconds':
                minimum = max(minimum, 1)
            if dimension == 'events' and not nongenerating:
                minimum = max(minimum, ceiling)
            if minimum > ceiling:
                raise BudgetInfeasible(dimension, minimum, ceiling, [step['id']])
            step_minima[dimension] = minimum
        minima[step['id']] = step_minima

    for dimension, authority_dimension in compiler.AUTHORITY_BUDGET.items():
        limit = envelope.get(authority_dimension)
        if limit is None:
            continue
        rows = [s for s in steps if dimension in s.get('budget', {})]
        fixed = [s for s in rows if s['id'] in frozen]
        adjustable = [s for s in rows if s['id'] not in frozen]
        reserved = sum(s['budget'][dimension] for s in fixed)
        available = limit - reserved
        required = sum(minima[s['id']][dimension] for s in adjustable)
        if reserved > limit or required > available:
            raise BudgetInfeasible(authority_dimension, reserved + required, limit, [s['id'] for s in rows])
        residuals = [s['budget'][dimension] - minima[s['id']][dimension] for s in adjustable]
        total = sum(residuals)
        allowance = min(total, available - required)
        remaining = available
        for step, residual in zip(adjustable, residuals):
            minimum = minima[step['id']][dimension]
            allocation = min(step['budget'][dimension], minimum + (allowance * residual / total if total else 0))
            # Reserve the later minima even under floating point roundoff.
            required -= minimum
            allocation = min(allocation, remaining - required)
            if dimension not in FLOAT_DIMENSIONS:
                allocation = math.floor(allocation)
            step['budget'][dimension] = allocation
            remaining -= allocation
    for step in steps:
        constraint = operation_ceilings[step['id']]
        if step['id'] in frozen or constraint is None:
            continue
        dimension, path, ceiling, _ = constraint
        # Current mapped pointers name resource ceilings, never inferred scientific task fields.
        from ravel.controller.step.operations import pointer
        parent_path, _, key = path.rpartition('/')
        parent = pointer(step['parameters']['task'], parent_path)
        key = key.replace('~1', '/').replace('~0', '~')
        if type(parent) is dict and key in parent:
            parent[key] = min(ceiling, step['budget'][dimension])
    changed['sha256'] = compiler.plan_sha256(changed)
    return changed
