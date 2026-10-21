"""The interfaces the governed step consumes, resolved when a node runs.

Each interface belongs to its own package: the run store (``ravel.controller.store``), the
obligation ledger, the instruction catalogue, confined execution, the authority service and
the review-independence decision. The step imports them inside node bodies, never at import
time, so an absent interface is a typed hold of the step that needs it and never a silent
pass. Nothing here installs a replacement: a test substitutes a module only through the
interpreter's own module table, never through a hook this package offers.

The store is the run's protected store. ``step.run`` binds the live store object for the
duration of its call; a node reached through the controller graph's fan-out resolves the same
run's store from the run handle carried in its state (the run id and the operator store root).
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import threading

from ravel.workflow.graph_nodes import RecoveryHold

# Interface name -> module (pairs, so no mapping key reads as instruction text to the agent census).
INTERFACES = dict((
    ('store', 'ravel.controller.store'),
    ('ledger', 'ravel.controller.ledger'),
    ('instructions', 'ravel.controller.instructions'),
    ('confine', 'ravel.controller.confine'),
    ('authority', 'ravel.controller.authority'),
    ('independence', 'ravel.workflow.review_independence'),
))

_LIVE: dict[str, object] = {}
_LIVE_LOCK = threading.Lock()


class StepHold(RecoveryHold):
    """The step cannot proceed; it ends in a typed hold with the reason and what would release it."""

    def __init__(self, reason, would_make_possible=None, *, evidence=None):
        super().__init__(reason, would_make_possible)
        self.evidence = deepcopy(evidence) if evidence is not None else None


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def module(name):
    """The named interface module, or a typed hold naming it."""
    target = INTERFACES[name]
    try:
        return importlib.import_module(target)
    except ImportError as exc:
        if exc.name not in (target, target.rsplit('.', 1)[0], 'ravel.controller'):
            raise
        raise StepHold('interface_unavailable:' + name,
                       f'install the {target} interface; the governed step does not run without it') from None


# ---- the run store ---------------------------------------------------------------------------

def handle(store, *, run_dir, store_root=None) -> dict:
    """The JSON-safe run handle a step's state carries: the run id, its store root and run directory."""
    run_id = getattr(store, 'run_id', None)
    if type(run_id) is not str or not run_id:
        raise ValueError('the run store names no run id')
    root = store_root if store_root is not None else getattr(store, 'store_root', None)
    return {'run_id': run_id, 'store_root': str(root) if root is not None else None,
            'run_dir': str(Path(run_dir).absolute())}


@contextmanager
def bound(store):
    """Make ``store`` the live store of its run in this process for the duration of a call."""
    run_id = getattr(store, 'run_id', None)
    if type(run_id) is not str or not run_id:
        raise ValueError('the run store names no run id')
    with _LIVE_LOCK:
        previous = _LIVE.get(run_id)
        _LIVE[run_id] = store
    try:
        yield store
    finally:
        with _LIVE_LOCK:
            if previous is None:
                _LIVE.pop(run_id, None)
            else:
                _LIVE[run_id] = previous


def store_for(run):
    """The live store of the run named by the handle, else the run store the operator configured."""
    if type(run) is not dict or type(run.get('run_id')) is not str:
        raise StepHold('run_handle_invalid', 'the step state carries the run id of its store')
    with _LIVE_LOCK:
        live = _LIVE.get(run['run_id'])
    if live is not None:
        return live
    store = module('store')
    root = run.get('store_root')
    return store.RunStore(run['run_id'], root=Path(root) if root else None)


def unwrap(row):
    """A store row as the record this package appended, with its store id when the row carries one."""
    if type(row) is dict and type(row.get('record')) is dict and set(row) - {'record'}:
        found = deepcopy(row['record'])
        identifier = row.get('id') or row.get('record_id')
        if identifier is not None:
            found.setdefault('_record_id', identifier)
        return found
    return deepcopy(row)


def records(store, kind):
    return [unwrap(row) for row in store.scan(kind)]


def lock_path(store, name):
    return Path(store.path('locks', name + '.lock'))
