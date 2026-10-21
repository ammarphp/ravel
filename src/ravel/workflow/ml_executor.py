"""Controller bridge for staged training; no launch bypass and no implied study validators.

The ordinary route dispatches each approved stage through ``controller.step.run``. A host may
also bind the same plan for ``ml.study``'s staged profile. Extended method studies retain their
original S1-S16 executor/validator seam and hold until those genuine prerequisites are supplied.
A binding is trusted process state, never checkpoint, request, worker data or execution authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

PREREQUISITE_HOLD = 'awaits the staged ML executor interface'
_ACTIVE = ContextVar('ml_controller_binding', default=None)
EXTENDED_INTERFACE = ('stage', 'binding', 'train', 'select', 'confirm', 'attribute')


@dataclass(frozen=True)
class Binding:
    store: object
    run_dir: Path
    plan: dict
    context: dict
    extended: object | None = None


@contextmanager
def bound(binding):
    if not isinstance(binding, Binding):
        raise TypeError('a controller-owned ML Binding is required')
    if binding.context.get('plan_sha256') != binding.plan.get('sha256'):
        raise ValueError('the ML binding pins the current plan digest')
    token = _ACTIVE.set(binding)
    try:
        yield binding
    finally:
        _ACTIVE.reset(token)


def active():
    return _ACTIVE.get()


def current(ctx=None):
    """The extended study service, when actually supplied; forwarding stubs grant no support."""
    binding = active()
    service = binding.extended if binding is not None else None
    if service is None or any(not callable(getattr(service, name, None)) for name in EXTENDED_INTERFACE):
        return None
    return service


def prerequisites(*, profile='staged'):
    if profile == 'study' and current() is None:
        return [{'id': 'staged_ml_executor', 'profile': 'extended', 'reason': PREREQUISITE_HOLD,
                 'missing': ['approved per-item stage mapping', 'source-bound S1-S16 validator artifacts']}]
    return []


def run_step(store, step, context):
    """Run exactly one planned stage through the governed step, then validate its adopted receipt.

    The governed step owns approval, confinement, budgets, checkpoint adoption and independent review. This bridge
    neither supplies authority nor starts a subprocess. A failed bridge check records a qualified
    ending; the outer controller remains the only delivery caller.
    """
    from ravel.controller.routes.ml import staged, training
    plan = context['plan']
    matches = [row for row in plan['steps'] if row.get('id') == step.get('id')]
    if len(matches) != 1 or matches[0] != step or context.get('plan_sha256') != plan.get('sha256'):
        raise ValueError('the ML stage must equal its pinned plan step')
    errors = staged.admit(step, {**context, 'store': store})
    if errors:
        return {'step_id': step['id'], 'status': 'held', 'reason': errors[0]['code'], 'errors': errors}
    try:
        from ravel.controller.step import run
    except ModuleNotFoundError as exc:
        if exc.name != 'ravel.controller.step':
            raise
        return {'step_id': step['id'], 'status': 'held', 'reason': 'ml_controller_step_unavailable'}
    outcome = run(store, deepcopy(step), {k: v for k, v in context.items() if k != 'plan'})
    if outcome.get('status') != 'completed':
        return outcome
    persisted = [r for r in staged.records(store, 'step-outcome') if r.get('step_id') == step['id']]
    if not persisted or persisted[-1].get('status') != 'completed':
        return {'step_id': step['id'], 'status': 'held', 'reason': 'ml_step_unreceipted'}
    problems = staged.step(step, outcome, {**context, 'store': store})
    if problems:
        receipt_rows = [r for r in staged.records(store, staged.STAGE_RECORD) if r.get('step_id') == step['id']]
        status = receipt_rows[-1].get('status') if receipt_rows else None
        # A crashed stage is a typed failure, never a hold or a refusal; budget exhaustion is qualified.
        return {**outcome, 'status': RECEIPT_OUTCOMES.get(status, 'held'), 'reason': problems[0], 'problems': problems}
    return outcome


RECEIPT_OUTCOMES = {'budget_exhausted': 'qualified', 'failed': 'failed'}
TERMINALS = {'qualified': 'budget_exhausted', 'budget_exhausted': 'budget_exhausted', 'failed': 'failed'}


def stage_node(ctx):
    """One graph node over the bound plan. The governed step journals each dispatched effect."""
    from . import graph_nodes as nodes
    from ravel.controller.routes.ml import staged

    def dispatch(state):
        binding = active()
        if binding is None or binding.extended is not None:
            raise nodes.RecoveryHold('ml_controller_binding_missing', 'bind the approved staged plan before resuming')
        if Path(state['meta']['scope_root']).resolve() != Path(binding.run_dir).resolve():
            raise nodes.RecoveryHold('ml_controller_binding_wrong_run')
        stages = [row for row in binding.plan['steps'] if staged.stage_of(row)]
        if {staged.stage_of(row) for row in stages} != set(staged.RECORDS):
            raise nodes.RecoveryHold('ml_stage_population_incomplete', 'the plan must include every typed stage')
        index = state.get('ml_index', 0)
        if type(index) is not int or not 0 <= index < len(stages):
            raise nodes.RecoveryHold('ml_stage_cursor_invalid')
        step = stages[index]
        context = {**binding.context, 'plan': binding.plan, 'run_dir': str(binding.run_dir)}
        outcome = run_step(binding.store, step, context)
        status = outcome.get('status', 'held')
        update = {'ml_index': index + 1, 'ml_status': status, 'ml_reason': str(outcome.get('reason') or ''),
                  'results': {step['id']: outcome}}
        if status != 'completed':
            update['status'] = {'phase': 'ml_staged', 'terminal': TERMINALS.get(status, 'hold'),
                                'reason': update['ml_reason'], 'would_make_possible': None}
            update['results']['ending'] = staged.ending(update['ml_reason'], {'store': binding.store,
                                                                           'plan': binding.plan})
        return update
    return nodes.Node(kind='subgraph', function=dispatch)


def next_stage(state):
    binding = active()
    count = len([row for row in binding.plan['steps'] if (row.get('parameters') or {}).get('ml_stage')]) if binding else 0
    return 'next' if state['ml_status'] == 'completed' and state['ml_index'] < count else 'end'
