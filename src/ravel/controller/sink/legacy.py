"""Legacy delivery writers and the controller: for a controller-owned run, only the sink delivers.

The result pack, requester delivery, submission export, template fill, task completion, whole-task
artifact delivery and procedure export keep working on runs the controller does not own; their
outputs carry ``NOT GOVERNED`` (``architecture_receipt``). For a run the controller owns they refuse
before writing anything, unless the sink itself runs one as a stage of its delivery (``stage``,
a scope in the controller's own process that no file, variable or argument can open).
Ownership that cannot be read refuses as well: a damaged claim is still a claim.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from . import common
from .common import SinkRefused

_STAGE = ContextVar('ravel_sink_stage', default=None)


@contextmanager
def stage(name):
    """Run a legacy writer as a named stage of the sink's own delivery (controller process only)."""
    if type(name) is not str or not name.strip():
        raise ValueError('a sink stage is named')
    token = _STAGE.set(name)
    try:
        yield name
    finally:
        _STAGE.reset(token)


def current_stage():
    return _STAGE.get()


def owner(path):
    """The controller run id that owns ``path``, or None (no controller core installed owns nothing)."""
    if path is None:
        return None
    store = common.module('store')
    if store is None or not hasattr(store, 'controller_owned'):
        return None
    return store.controller_owned(Path(path))


def refuse_controller_owned(path, writer):
    """Refuse ``writer`` for a controller-owned ``path`` outside a sink stage; returns the owner (or None)."""
    run = owner(path)
    if run is not None and _STAGE.get() is None:
        raise SinkRefused(f'{writer} is refused for the controller-owned run {run}: only the controller\'s sole sink '
                          f'delivers its results (continue it with `ravel drive --resume {run}`); nothing was '
                          'written. Legacy commands keep working on runs the controller does not own, labelled '
                          f'{common.NOT_GOVERNED}.')
    return run
