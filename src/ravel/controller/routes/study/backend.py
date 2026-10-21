"""Bind a source-owned supervised attempt to the controller's remote journal."""
from __future__ import annotations

import hashlib
from pathlib import Path

from ravel.workflow.state_io import file_lock, read_json

from .contracts import digest, records, relative
from . import site


def _ordinary(path):
    path = Path(path)
    if (not path.is_absolute() or '..' in path.parts
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise ValueError('source backend paths must be ordinary absolute paths without links')
    return path


def track(store, launch_id, *, rundir: Path, stage: str, plan_path: Path):
    """Track only the handle read from the current source-pinned stage attempt.

    No handle or remote identity is accepted from the caller. This bridge
    neither submits nor recovers work and confers no scientific acceptance.
    """
    from ravel.workflow import execution, execution_backend as backend
    rundir, plan_path = _ordinary(rundir), _ordinary(plan_path)
    if type(stage) is not str or len(relative(stage).parts) != 1:
        raise ValueError('one original source stage is required')
    reserved = [r for r in records(store, 'study-site')
                if r.get('launch_id') == launch_id and r.get('event') == 'reserved']
    if len(reserved) != 1 or not reserved[0].get('run_dir'):
        raise ValueError('a reserved launch with its trusted original root is required')
    root = _ordinary(reserved[0]['run_dir'])
    if rundir != root and not rundir.is_relative_to(root / 'children'):
        raise ValueError('source run escapes the original root and its children')
    if (not rundir.is_dir() or not plan_path.is_file()
            or not plan_path.is_relative_to(rundir / 'inputs')):
        raise ValueError('the source plan must be an existing ordinary input of this run')
    protected = store.path().resolve()
    if rundir.is_relative_to(protected) or protected.is_relative_to(rundir):
        raise ValueError('source run overlaps the protected controller store')
    record = execution.load_execution(rundir)['stages'].get(stage)
    if type(record) is not dict or not record.get('attempt_id'):
        raise ValueError('the selected source stage has no current attempt')
    attempt_id = record['attempt_id']
    if type(attempt_id) is not str or len(relative(attempt_id).parts) != 1:
        raise ValueError('the source attempt identity escapes its stage')
    data = backend.pinned_plan_bytes(record, plan_path)
    plan = backend.load_plan_bytes(data)
    if plan['spec']['stage'] != stage:
        raise ValueError('the pinned backend plan names a different stage')
    attempt = _ordinary(backend.attempt_backend_dir(rundir, stage, attempt_id))
    handle_path = _ordinary(attempt / backend.HANDLE_NAME)
    if not handle_path.is_file():
        raise ValueError('the current attempt has no ordinary backend handle')
    handle = backend.read_handle(attempt)
    sha = hashlib.sha256(data).hexdigest()
    if (handle.get('attempt_dir') != str(attempt)
            or handle.get('plan_sha256') != plan['plan_sha256']
            or handle.get('plan_file_sha256') != sha
            or handle.get('backend') != plan['backend']['kind']
            or handle.get('tag') != backend.handle_tag(plan, attempt)
            or handle.get('remote') is None):
        raise ValueError('backend handle differs from the current pinned source attempt')
    tracked = [r for r in records(store, 'study-remote') if r['launch_id'] == launch_id]
    original = tracked[-1]['handle'] if tracked else handle
    identity_fields = ('backend', 'plan_sha256', 'plan_file_sha256', 'tag', 'attempt_dir', 'job_dir', 'remote')
    if tracked and (tracked[-1]['plan'] != plan or any(original.get(k) != handle.get(k) for k in identity_fields)):
        raise ValueError('backend immutable remote identity changed from its original attempt')
    binding = {'launch_id': launch_id, 'run_dir': str(root), 'rundir': str(rundir),
               'stage': stage, 'attempt_id': attempt_id, 'plan_path': str(plan_path),
               'plan_file_sha256': sha, 'plan_sha256': plan['plan_sha256'],
               'handle_sha256': digest(original)}
    lock = store.path('locks', 'study-backend.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock):
        previous = [r for r in records(store, 'study-backend-binding') if r['launch_id'] == launch_id]
        if previous and previous[0] != binding:
            raise ValueError('the tracked source stage and attempt binding is immutable')
        if not tracked:
            site.track(store, launch_id, plan, handle)
        if not previous:
            store.append('study-backend-binding', binding)
        if handle.get('state') == 'fetched':
            receipt_path = _ordinary(attempt / backend.RECEIPT_NAME)
            if not receipt_path.is_file():
                raise ValueError('fetched source handle has no ordinary fetch receipt')
            receipt = read_json(receipt_path)
            if any(receipt.get(key) != handle.get(key) for key in ('backend', 'remote', 'tag', 'plan_sha256')):
                raise ValueError('source fetch receipt differs from its pinned attempt')
            site._adoption_outputs(backend, plan, receipt, rundir)
            adoption = {'launch_id': launch_id, 'base': str(rundir),
                        'remote_binding': digest({'plan': plan, 'handle': original}),
                        'plan_sha256': plan['plan_sha256'], 'handle': original,
                        'event': 'fetched', 'receipt': receipt}
            with site._lock(store):
                fetched = [r for r in records(store, 'study-adoption') if r['launch_id'] == launch_id]
                if fetched and fetched[-1] != adoption:
                    raise ValueError('source fetch adoption identity is immutable')
                if not fetched:
                    store.append('study-adoption', adoption)
    return binding


__all__ = ['track']
