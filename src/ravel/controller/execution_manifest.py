"""Immutable controller execution identity, checked before admission or checkpoint lookup."""
from __future__ import annotations

import hashlib
from importlib import metadata
import os
from pathlib import Path
import shlex
import sys

KIND = 'execution-manifest'


class ExecutionRefused(ValueError):
    code = 'execution_environment_mismatch'

    def __init__(self, message, remedy):
        self.remedy = remedy
        super().__init__(message + '; ' + remedy)


def dependencies():
    """Installed distribution identities, including wheel member manifests.

    RECORD identifies the installed dependency build; this is not a scientific
    validation or a certificate of all native libraries on the host.
    """
    rows = []
    for dist in metadata.distributions():
        name = dist.metadata.get('Name')
        if not name:
            continue
        records = {name: hashlib.sha256((dist.read_text(name) or '').encode()).hexdigest()
                   for name in ('RECORD', 'direct_url.json')}
        rows.append({'name': name.lower().replace('_', '-'), 'version': dist.version,
                     'metadata': records})
    return sorted(rows, key=lambda row: (row['name'], row['version'], str(row['metadata'])))


def current(run_id, graph_id):
    from .confine.identity import code_identity
    from ..workflow import graph_substrate
    source = code_identity()
    return {'schema_version': 1, 'source': source, 'dependencies': dependencies(),
            'python': {'executable': os.path.abspath(sys.executable), 'prefix': sys.prefix,
                       'version': sys.version},
            'graph_id': graph_id,
            'closure': graph_substrate.closure(graph_id),
            'runtime': graph_substrate.identity(),
            'thread_id': graph_substrate.thread_id(graph_id, {'run_id': run_id})}


def original(store):
    rows = store.scan(KIND)
    if len(rows) > 1:
        raise ExecutionRefused('execution manifest has multiple intake identities',
                               'restore the protected store from its verified backup')
    return rows[0].get('record', rows[0]) if rows else None


def resume_command(store, manifest):
    executable = manifest['python']['executable']
    return shlex.join([executable, '-m', 'ravel', 'drive', '--resume', store.run_id])


def ensure(store, graph_id, *, resume=False):
    """Freeze once; never invent an intake identity for an already executed legacy run."""
    from ..workflow.state_io import file_lock
    with file_lock(store.path('execution-manifest.lock')):
        pin = original(store)
        if pin is None and (store.latest('code-identity') or
                            any((store.root / 'graph' / 'framework' / 'threads').glob('*.json'))):
            raise ExecutionRefused('the executed run has no original execution manifest',
                                   'use the original installation to finish this run; export its evidence '
                                   'for inspection; automatic baseline adoption is refused')
        try:
            live = current(store.run_id, graph_id)
        except (OSError, ValueError, metadata.PackageNotFoundError) as exc:
            remedy = ('restore the pinned environment and run: ' + resume_command(store, pin)) if pin else (
                'repair the installed dependencies, then retry the original command')
            raise ExecutionRefused(f'execution identity is unavailable ({type(exc).__name__}: {exc})', remedy) from exc
        if pin is None:
            store.append(KIND, live)
            return live
        if live != pin:
            changed = ', '.join(key for key in pin if pin.get(key) != live.get(key))
            raise ExecutionRefused(f'run {store.run_id} requires its original execution environment '
                                   f'({changed} changed); manifest: {store.root / "journal.jsonl"}',
                                   'restore the pinned environment and run: ' + resume_command(store, pin))
        return pin


def check_admission(store, admitted):
    """Admission cannot install a new epoch as the intake baseline."""
    pin = original(store)
    rows = store.scan('code-identity')
    baseline = pin['source'] if pin else (rows[0].get('record', rows[0]) if rows else None)
    if baseline is None:
        return
    baseline = baseline.get('identity', baseline)
    keys = ('digest', 'package_dir', 'version', 'kind', 'selectors', 'distribution_record_sha256')
    if any(admitted.get(key) != baseline.get(key) for key in keys):
        run_id = getattr(store, 'run_id', None)
        command = (resume_command(store, pin) if pin else
                   shlex.join(['ravel', 'drive', '--resume', run_id]) if run_id else
                   'ravel drive --request-file <request-file> --rundir <new-run-directory>')
        raise ExecutionRefused('admission differs from the original source identity',
                               'restore the pinned installation and run: ' + command)
