"""Per-launch capabilities for facility submission.

A supervised WMS launch mints one capability for the jobs its approved task may submit. The
token is a secret the launch hands to its own executor; the store keeps only its sha256 and
the scope. ``verify_capability`` admits a job script only while the capability is current,
for a rule of the scoped tasks, inside the scoped workflow, and within the job count. A
direct call of the submit script, a stale or revoked token, another workflow's token or a
job outside the scope is refused, and each admitted submission is recorded.

The rwc1 wire format supports run and launch identifiers without dots only; dotted
identifiers need a future versioned encoding to avoid ambiguous token boundaries.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from ravel.workflow.state_io import file_lock

TOKEN = re.compile(r'rwc1\.([A-Za-z0-9][A-Za-z0-9_-]{0,127})\.([A-Za-z0-9][A-Za-z0-9_-]{0,127})\.([A-Za-z0-9_-]{32,128})\Z')
KIND, REVOKED, SUBMITTED = 'wms-capability', 'wms-capability-revoked', 'wms-submission'
_TASK_ABSENT = object()
SCOPE_KEYS = frozenset({'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256',
                        'jobscript_sha256', 'resource_maxima', 'reads', 'read_sha256'})
RESOURCE_KEYS = frozenset({'threads', 'mem_mb', 'runtime', 'disk_mb'})


class CapabilityRefused(ValueError):
    """No valid capability admits this submission; nothing was submitted."""


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _rows(store, kind):
    """The appended records of ``kind`` (a store may return them bare or under ``record``)."""
    rows = []
    for row in store.scan(kind):
        value = row.get('record', row) if isinstance(row, dict) else None
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _scope(scope):
    if not isinstance(scope, dict) or set(scope) - SCOPE_KEYS or 'workflow_dir' not in scope:
        raise ValueError('a capability scope names workflow_dir and optional tasks/rules/max_jobs/profile_sha256/jobscript_sha256/resource_maxima')
    if not isinstance(scope['workflow_dir'], str) or not os.path.isabs(scope['workflow_dir']):
        raise ValueError('the capability workflow_dir must be absolute')
    for key in ('tasks', 'rules'):
        if key in scope and (not isinstance(scope[key], list) or not all(isinstance(v, str) and v for v in scope[key])):
            raise ValueError(f'capability {key} must be a list of names')
    if 'max_jobs' in scope and (type(scope['max_jobs']) is not int or scope['max_jobs'] < 1):
        raise ValueError('capability max_jobs must be a positive integer')
    for key in ('profile_sha256', 'jobscript_sha256'):
        if key in scope and (not isinstance(scope[key], str) or not re.fullmatch(r'[0-9a-f]{64}', scope[key])):
            raise ValueError(f'capability {key} must be a sha256 digest')
    if 'resource_maxima' in scope:
        maxima = scope['resource_maxima']
        if (type(maxima) is not dict or not maxima or set(maxima) - RESOURCE_KEYS
                or any(type(v) is not int or v < 1 for v in maxima.values())):
            raise ValueError('capability resource_maxima requires positive integer threads/mem_mb/runtime/disk_mb')
    if 'reads' in scope:
        if (type(scope['reads']) is not list or any(not isinstance(v, str) for v in scope['reads'])
                or len(set(scope['reads'])) != len(scope['reads'])):
            raise ValueError('capability reads must list distinct ordinary absolute files')
        for value in scope['reads']:
            ordinary_input(value)
    if 'read_sha256' in scope:
        pins = scope['read_sha256']
        if (type(pins) is not dict or set(pins) != set(scope.get('reads', []))
                or any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in pins.values())):
            raise ValueError('capability read_sha256 must pin each declared read')
    result = json.loads(json.dumps(scope, allow_nan=False))
    result['workflow_dir'] = os.path.realpath(scope['workflow_dir'])
    return result


def mint_capability(store, launch_id, scope):
    """Record a capability and return its secret token.

    Scope is a restriction, not evidence of approval. The trusted WMS generator owns
    script construction; its caller must supply approved resource maxima. Optional
    ``jobscript_sha256`` pins the complete generated payload. A matching properties
    comment by itself does not certify script contents.
    """
    if not isinstance(launch_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', launch_id):
        raise ValueError('a capability launch id is a short identifier without dots (rwc1)')
    run_id = getattr(store, 'run_id', None)
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', run_id):
        raise ValueError('a capability is minted into a controller run store with an identifier without dots (rwc1)')
    scope = _scope(scope)
    # Batch jobs read the workflow directory from the shared filesystem; the store stays off it.
    from .locations import overlaps, real, credential_paths
    if overlaps(real(store.path()), [Path(scope['workflow_dir'])]):
        raise ValueError('the run store overlaps the workflow directory its batch jobs read; nothing was minted')
    if 'reads' in scope:
        protected = [real(store.path()), *credential_paths()]
        if any(overlaps(real(value), protected) for value in scope['reads']):
            raise ValueError('capability reads cannot expose the run store or credentials')
        from ravel.workflow.execution import file_hash
        pins = {value: file_hash(value) for value in scope['reads']}
        if 'read_sha256' in scope and scope['read_sha256'] != pins:
            raise ValueError('capability read inputs differ from their supplied digests')
        scope['read_sha256'] = pins
    token = f'rwc1.{run_id}.{launch_id}.{secrets.token_urlsafe(32)}'
    with file_lock(store.path('wms-capability.lock')):
        if any(r.get('launch_id') == launch_id for r in _rows(store, KIND)):
            raise CapabilityRefused('this launch already minted a capability; nothing was minted')
        store.append(KIND, {'launch_id': launch_id, 'sha256': digest(token), 'scope': scope})
    return token


def revoke_capability(store, launch_id):
    """End a launch's capability; later submissions with it are refused."""
    with file_lock(store.path('wms-capability.lock')):
        store.append(REVOKED, {'launch_id': launch_id})


def job_properties(jobscript):
    """The Snakemake job properties a job script declares (``# properties = {...}``)."""
    path = Path(jobscript)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise CapabilityRefused('an ordinary absolute job script is required; nothing was submitted')
    return _properties_from_bytes(path.read_bytes())


def _properties_from_bytes(content):
    for line in content.decode('utf-8', errors='replace').splitlines():
        if line.startswith('# properties = '):
            try:
                value = json.loads(line[len('# properties = '):])
            except ValueError as exc:
                raise CapabilityRefused('job properties are not JSON; nothing was submitted') from exc
            if not isinstance(value, dict):
                raise CapabilityRefused('job properties must be an object; nothing was submitted')
            return value
    return {}


def verify_capability(token, jobscript, *, store=None, task=_TASK_ABSENT, profile_sha256=None,
                      resource_defaults=None, authorized_tasks=None):
    """The admitted scope for this job script under ``token``; raises ``CapabilityRefused`` otherwise.

    ``store`` defaults to the run store the token names; ``task`` is the task the job's rule
    belongs to when the submitter has resolved it. Only an omitted task may be derived from
    a generic task_<name> or ravel_verify_<name> rule. ``profile_sha256`` is the digest of the site
    profile the submission uses, which must equal the scope's when the scope names one.
    """
    match = TOKEN.fullmatch(token or '') if isinstance(token, str) else None
    if match is None:
        raise CapabilityRefused('no per-launch capability was presented; nothing was submitted')
    run_id, launch_id = match.group(1), match.group(2)
    if store is None:
        from . import runs
        try:
            store = runs.store(run_id)
        except (OSError, ValueError) as exc:
            raise CapabilityRefused(f'the capability names no readable controller run: {exc}') from exc
    if getattr(store, 'run_id', None) != run_id:
        raise CapabilityRefused('the capability names a different controller run store; nothing was submitted')
    with file_lock(store.path('wms-capability.lock')):
        return _verify_locked(token, jobscript, store, run_id, launch_id, task, profile_sha256,
                              resource_defaults, authorized_tasks)


def _verify_locked(token, jobscript, store, run_id, launch_id, task, profile_sha256,
                   resource_defaults, authorized_tasks):
    # The caller holds the capability lock across admission, count and append.
    rows = [r for r in _rows(store, KIND) if r.get('launch_id') == launch_id]
    if len(rows) != 1 or not hmac.compare_digest(rows[0].get('sha256', ''), digest(token)):
        raise CapabilityRefused('the capability is not one this run minted; nothing was submitted')
    if any(r.get('launch_id') == launch_id for r in _rows(store, REVOKED)):
        raise CapabilityRefused('the capability was revoked when its launch ended; nothing was submitted')
    scope = _scope(rows[0]['scope'])
    path = Path(jobscript)
    workflow = Path(scope['workflow_dir'])
    if (not path.is_absolute() or '..' in path.parts or not path.is_relative_to(workflow)
            or not path.resolve().is_relative_to(workflow)):
        raise CapabilityRefused('the job script lies outside the capability workflow; nothing was submitted')
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise CapabilityRefused('a symbolic link job script or ancestor is not admitted; nothing was submitted')
        if ancestor == workflow:
            break
    if not path.is_file():
        raise CapabilityRefused('an ordinary absolute job script is required; nothing was submitted')
    content = path.read_bytes()
    content_sha256 = hashlib.sha256(content).hexdigest()
    if 'jobscript_sha256' in scope and content_sha256 != scope['jobscript_sha256']:
        raise CapabilityRefused('the job script differs from its approved digest; nothing was submitted')
    from ravel.workflow.execution import file_hash
    for value, expected in scope.get('read_sha256', {}).items():
        ordinary_input(value)
        if file_hash(value) != expected:
            raise CapabilityRefused('a declared job input changed after minting; nothing was submitted')
    properties = _properties_from_bytes(content)
    resources = job_resources(properties, resource_defaults)
    if 'resource_maxima' in scope:
        maxima = scope['resource_maxima']
        if any(key not in maxima or value > maxima[key] for key, value in resources.items()):
            raise CapabilityRefused('job resources exceed or lack approved resource maxima; nothing was submitted')
    rule = properties.get('rule')
    if 'rules' in scope and rule not in scope['rules']:
        raise CapabilityRefused(f'rule {rule!r} is outside the capability; nothing was submitted')
    if task is _TASK_ABSENT:
        derived = re.fullmatch(r'(?:task_|ravel_verify_)([A-Za-z0-9_.-]{1,64})', str(rule))
        task = derived.group(1) if derived else None
    if task is _TASK_ABSENT:
        task = None
    if 'tasks' in scope and (task is None or task not in scope['tasks']):
        raise CapabilityRefused(f'task {task!r} is outside the capability; nothing was submitted')
    if authorized_tasks is not None and task not in authorized_tasks:
        raise CapabilityRefused('the job task is outside the live launch; nothing was submitted')
    if 'profile_sha256' in scope and profile_sha256 != scope['profile_sha256']:
        raise CapabilityRefused('the submission\'s site profile differs from the one the capability was minted for; '
                                'nothing was submitted')
    used = [r for r in _rows(store, SUBMITTED) if r.get('launch_id') == launch_id]
    if 'max_jobs' in scope and len(used) >= scope['max_jobs']:
        raise CapabilityRefused(f'the capability admits {scope["max_jobs"]} job(s) and all were submitted')
    # Capture only once. This private evidence is never exported to batch workers.
    folder = Path(tempfile.mkdtemp(prefix='wms-script-', dir=store.path()))
    snapshot = folder / 'job.sh'
    with snapshot.open('xb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    snapshot.chmod(0o400)
    folder.chmod(0o500)
    store.append(SUBMITTED, {'launch_id': launch_id, 'jobscript': str(path), 'rule': rule, 'task': task,
                             'jobscript_sha256': content_sha256, 'snapshot_path': str(snapshot), 'resources': resources})
    return {'run_id': run_id, 'launch_id': launch_id, 'rule': rule, 'task': task, 'scope': scope,
            'submissions': len(used) + 1, 'snapshot_path': str(snapshot), 'store_path': str(Path(store.path()).resolve()),
            'jobscript_sha256': content_sha256, 'properties': properties, 'resources': resources,
            'input_digests': scope.get('read_sha256', {})}


def job_resources(properties, defaults=None):
    """Effective scheduler resources, including the profile defaults HTCondor uses."""
    raw = properties.get('resources', {})
    if type(raw) is not dict:
        raise CapabilityRefused('job resources must be an object; nothing was submitted')
    defaults = defaults or {}
    values = {'threads': properties.get('threads', 1)}
    for key in ('mem_mb', 'runtime', 'disk_mb'):
        if key in raw or key in defaults:
            values[key] = raw.get(key, defaults.get(key))
    if any(type(value) is not int or value <= 0 for value in values.values()):
        raise CapabilityRefused('job resources must be positive integers; nothing was submitted')
    return values


def ordinary_input(value):
    """Only a single absolute ordinary file, with no symlink ancestor or hardlink."""
    if not isinstance(value, str) or not os.path.isabs(value) or '..' in Path(value).parts:
        raise CapabilityRefused('declared job reads must be ordinary absolute files')
    path = Path(value)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise CapabilityRefused('declared job reads cannot traverse symbolic links')
    if not path.is_file() or path.stat().st_nlink != 1:
        raise CapabilityRefused('declared job reads must be ordinary files without hardlinks')
    return path
