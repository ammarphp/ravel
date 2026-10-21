"""The governed step: the one subgraph every step of every route runs through.

``controller.step`` (``graph.build``) reserves the budget, builds and delivers the instruction
packet, checks the plan binding, inputs, operation, role card, transport and authority, then
dispatches one sandboxed worker, launches one confined operation or invokes one registered
graph, observes what ran, validates the final record, adopts the declared outputs by digest,
runs the card's validators, dispatches and credits the review seats, records the obligations
and acts on the worker's escalation. ``controller.seat`` (``graph.build_seat``) is the same
machinery for one review or consult seat.

``run(store, step, context)`` is the entry for one step attempt outside the controller graph's
fan-out: it runs the step in its own substrate scope inside the run store and returns the step
outcome (``step_id``, ``attempt``, ``status``, ``outputs``, ``receipts``, ``escalation``,
``replan``, ``budget``, ``judgments``, ``review``, ``reason``).
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

GRAPH_ID = 'controller.step'
SEAT_GRAPH = 'controller.seat'
OUTCOME_KEYS = ('step_id', 'attempt', 'status', 'outputs', 'receipts', 'escalation', 'replan', 'budget', 'judgments',
                'review', 'reason')


def _part(value):
    part = re.sub(r'[^A-Za-z0-9_.:@+=-]', '_', str(value))[:120]
    return part or 'step'


def _controller_scope(run_id):
    """The runtime tripwire's controller scope for this run, where the tripwire module offers one."""
    from contextlib import nullcontext
    from ravel.workflow import agent_tripwire
    scope = getattr(agent_tripwire, 'controller_scope', None)
    return scope(run_id) if callable(scope) else nullcontext()


def run(store, step: dict, context: dict) -> dict:
    """Run one attempt of ``step`` through ``controller.step``; return its outcome."""
    from ravel.workflow import graph_substrate
    from . import spec
    from .custody import OUTCOME
    from .services import bound, records
    ctx = deepcopy(context or {})
    ctx.setdefault('run_id', store.run_id)
    if ctx.get('store_root') is None and getattr(store, 'store_root', None) is not None:
        ctx['store_root'] = str(store.store_root)
    if not ctx.get('run_dir'):
        run_dir = getattr(store, 'run_dir', None)
        if run_dir is None:
            raise ValueError('the step context names the run directory')
        ctx['run_dir'] = str(Path(run_dir).absolute())
    attempt = spec.attempt(ctx)
    scope = store.path('step-scopes', _part(step.get('id')), str(attempt))
    # The step runs as controller work: the lowest layers' tripwire blocks while it runs (SW15).
    with bound(store), _controller_scope(ctx['run_id']):
        observation = graph_substrate.run(scope, GRAPH_ID, {'run_id': ctx['run_id']},
                                          input={'step': deepcopy(step), 'context': ctx})
    found = [row for row in records(store, OUTCOME) if row.get('step_id') == step.get('id')
             and row.get('attempt') == attempt and not row.get('seat')]
    if found and type(found[-1].get('outcome')) is dict:
        return deepcopy(found[-1]['outcome'])
    terminal = observation.get('terminal') or {}
    status = {'stopped': 'stopped', 'budget_exhausted': 'budget_exhausted'}.get(terminal.get('status'), 'held')
    return {'step_id': step.get('id'), 'attempt': attempt, 'status': status, 'outputs': [], 'receipts': [],
            'escalation': None, 'replan': None, 'budget': {}, 'judgments': [], 'review': {},
            'reason': terminal.get('reason') or ('interrupted' if observation.get('interrupts') else 'no_outcome'),
            'interrupts': deepcopy(observation.get('interrupts') or [])}


__all__ = ['GRAPH_ID', 'OUTCOME_KEYS', 'SEAT_GRAPH', 'run']
