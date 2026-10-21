"""Controller ownership, the run store and operator settings, as the confined launcher reads them.

Ownership and the store belong to ``ravel.controller.store`` and the operator configuration to
``ravel.controller.authority``. When a module is not installed, no run is controller-owned and
the operator permits nothing. A module that is present but fails to import raises: an unknown
ownership never selects the unconfined legacy path.
"""
from __future__ import annotations

import importlib
from pathlib import Path


def _module(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name in (name, name.rsplit('.', 1)[0], 'ravel.controller'):
            return None
        raise


def owner(run_dir):
    """The run id when the controller owns exactly ``run_dir``, else None."""
    store = _module('ravel.controller.store')
    if store is None:
        return None
    return store.controller_owned(Path(run_dir).absolute()) or None


def owner_of(path):
    """``(run id, run directory)`` of the controller-owned run that contains ``path``, else None."""
    store = _module('ravel.controller.store')
    if store is None:
        return None
    here = Path(path).absolute()
    for candidate in (here, *here.parents):
        run = store.controller_owned(candidate)
        if run:
            return run, candidate
    return None


def store(run_id):
    """The protected store of a controller run."""
    module = _module('ravel.controller.store')
    if module is None:
        raise ValueError('the controller store is not installed; a controller run cannot be served')
    return module.RunStore(run_id)


def operator_settings():
    """The operator's configuration; empty (nothing permitted) when no authority service is installed."""
    authority = _module('ravel.controller.authority')
    if authority is None:
        return {}
    value = authority.operator_config()
    return value if isinstance(value, dict) else {}


def allow_unconfined():
    """True only when the operator's own configuration says ``allow_unconfined: true``."""
    return operator_settings().get('allow_unconfined') is True
