"""Execution backends for supervised stages.

A stage can run as a native subprocess on this machine, in a local OCI container
(podman), on a Magnus site, or as an HTCondor/SLURM batch job. Every backend
follows the same life cycle:

1. ``prepare(spec)`` turns a stage specification into an immutable plan. The plan
   pins the image by digest, any source repository by full commit, each input by
   sha256, the declared outputs and quantities, and the resource ceilings. Its
   canonical JSON digest (``plan_sha256``) joins the stage fingerprint, so a
   changed image, site or resource request invalidates an earlier receipt.
2. ``submit(plan, attempt_dir)`` writes ``backend-handle.json`` before anything is
   dispatched. The handle carries a deterministic tag, so a crash between dispatch
   and the record can be recovered by looking the tag up.
3. ``observe``, ``logs``, ``cancel`` and ``recover`` act on that handle only.
4. ``fetch`` copies the outputs into a fresh attempt-scoped staging directory,
   hashes them, checks every requested quantity, and only then moves them to the
   declared destinations. An existing destination is never replaced.

Approvals stay where they are. The supervised stage runs
``python -m ravel.workflow.execution_backend worker`` as its command; the stage
supervisor, CHECK-IN approval and launch authorization see that command and the
plan file as an ordinary pinned input. Local backends take the machine lease, so
only one native scientific job runs on this machine at a time. Remote backends
take a slot under a separate remote ceiling (default 1, set by the owner).

Credentials are never read or recorded. Logs and client output are redacted for
token patterns before they are written to any record.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
import inspect
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import sys
import time

from .state_io import atomic_json, read_json

SCHEMA_VERSION = 1
HANDLE_NAME = 'backend-handle.json'
OBSERVATIONS_NAME = 'observations.jsonl'
RECEIPT_NAME = 'fetch-receipt.json'
STATES = ('pending', 'running', 'succeeded', 'failed', 'cancelled', 'unknown')
TERMINAL = frozenset(('succeeded', 'failed', 'cancelled'))
UNRESOLVED_HANDLE_STATES = ('dispatching', 'dispatch-unknown', 'submitted')

_STAGE = re.compile(r'^[a-z][a-z0-9_-]{0,79}$')
_ENV_NAME = re.compile(r'^[A-Z_][A-Z0-9_]{0,63}$')
_CREDENTIAL = re.compile(r'TOKEN|SECRET|PASSW|CREDENTIAL|API_?KEY|PRIVATE_?KEY|AUTH', re.I)
_DIGEST_REFERENCE = re.compile(r'^[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}$')
_IMAGE_ID = re.compile(r'^sha256:[0-9a-f]{64}$')
_COMMIT = re.compile(r'^[0-9a-f]{40}$')
PLATFORMS = ('linux/arm64', 'linux/amd64')
_SECRET_PATTERNS = (
    re.compile(r'sk-[A-Za-z0-9_\-]{8,}'),
    re.compile(r'(?i)((?:[A-Z0-9_]*TOKEN|[A-Z0-9_]*SECRET|password|passwd|api[_-]?key)\s*[=:]\s*)\S+'),
    re.compile(r'(?i)(authorization:\s*bearer\s+)\S+'),
)

ADAPTERS = {
    'native': ('ravel.workflow.backends.native', 'NativeBackend',
               'run on this machine as a supervised subprocess'),
    'oci-local': ('ravel.workflow.backends.oci_local', 'OciLocalBackend',
                  'run in a digest-pinned podman container on this machine'),
    'site': ('ravel.workflow.backends.site_batch', 'SiteBackend',
             'submit to an HTCondor or SLURM site with shared-filesystem staging'),
}


# ---------------------------------------------------------------- utilities
def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def redact(text):
    """Remove token-shaped secrets from text before it reaches any record."""
    if text is None:
        return text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + '[redacted]', text)
        else:
            text = pattern.sub('[redacted]', text)
    return text


def identity(path):
    """Content identity of a regular file or a directory tree (no symlinks)."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f'symlinked input refused: {path}')
    if path.is_file():
        return {'path': str(path), 'kind': 'file', 'sha256': file_sha256(path), 'size': path.stat().st_size}
    if path.is_dir():
        rows, total = [], 0
        for item in sorted(path.rglob('*')):
            if item.is_symlink():
                raise ValueError(f'symlink inside input tree refused: {item}')
            if item.is_file():
                size = item.stat().st_size
                rows.append([item.relative_to(path).as_posix(), size, file_sha256(item)])
                total += size
            elif not item.is_dir():
                raise ValueError(f'special file inside input tree refused: {item}')
        return {'path': str(path), 'kind': 'directory', 'sha256': digest(rows), 'size': total, 'files': len(rows)}
    raise ValueError(f'input does not exist: {path}')


def _relative(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f'{label} must be a nonempty relative path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')) or p.as_posix() != value:
        raise ValueError(f'{label} must be a normalized relative path: {value!r}')
    return value


def _integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer in [{low}, {high}]')
    return value


def _keys(value, required, optional, label):
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be an object')
    missing = set(required) - set(value)
    if missing:
        raise ValueError(f'{label} is missing ' + ', '.join(sorted(missing)))
    extra = set(value) - set(required) - set(optional)
    if extra:
        raise ValueError(f'{label} has unknown fields ' + ', '.join(sorted(extra)))


def json_pointer(document, pointer):
    if pointer == '':
        return document
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('quantity pointer must be a JSON pointer starting with /')
    value = document
    for raw in pointer[1:].split('/'):
        key = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and key in value:
            value = value[key]
        elif isinstance(value, list) and key.isdigit() and int(key) < len(value):
            value = value[int(key)]
        else:
            raise KeyError(pointer)
    return value


# ---------------------------------------------------------------- validation
def validate_image(image):
    _keys(image, ('platform',), ('reference', 'id', 'emulation'), 'image')
    if 'reference' not in image and 'id' not in image:
        raise ValueError('image needs a digest reference (name@sha256:...) or a local image id (sha256:...)')
    if 'reference' in image and not (isinstance(image['reference'], str) and _DIGEST_REFERENCE.fullmatch(image['reference'])):
        raise ValueError('image reference must be pinned by digest (name@sha256:<64 hex>); tags such as :latest are refused')
    if 'id' in image and not (isinstance(image['id'], str) and _IMAGE_ID.fullmatch(image['id'])):
        raise ValueError('local image id must be sha256:<64 hex> digest')
    if image['platform'] not in PLATFORMS:
        raise ValueError(f'image platform must be one of {PLATFORMS}')
    if 'emulation' in image and type(image['emulation']) is not bool:
        raise ValueError('image emulation must be true or false')
    return deepcopy(image)


def validate_source(source):
    _keys(source, ('repository', 'commit'), ('subdirectory',), 'source')
    if not isinstance(source['repository'], str) or not source['repository']:
        raise ValueError('source repository required')
    if not isinstance(source['commit'], str) or not _COMMIT.fullmatch(source['commit']):
        raise ValueError('source commit must be a full 40-character commit SHA; HEAD and branch names are refused')
    return deepcopy(source)


SPEC_REQUIRED = ('schema_version', 'backend', 'stage', 'argv', 'outputs', 'resources')
SPEC_OPTIONAL = ('inputs', 'readonly_trees', 'quantities', 'env', 'image', 'source', 'site', 'workdir', 'description',
                 'inherit_runtime_environment')


def validate_spec(spec):
    _keys(spec, SPEC_REQUIRED, SPEC_OPTIONAL, 'backend stage specification')
    if spec['schema_version'] != SCHEMA_VERSION:
        raise ValueError('backend stage specification schema_version 1 required')
    if spec['backend'] not in ADAPTERS:
        raise ValueError(f"unknown execution backend {spec['backend']!r}")
    if not isinstance(spec['stage'], str) or not _STAGE.fullmatch(spec['stage']):
        raise ValueError('stage name must match [a-z][a-z0-9_-]*')
    argv = spec['argv']
    if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or not a or '\x00' in a for a in argv):
        raise ValueError('argv must be a nonempty list of nonempty strings')
    resources = spec['resources']
    _keys(resources, ('cpus', 'memory_mib', 'wall_seconds'), ('disk_mib',), 'resources')
    _integer(resources['cpus'], 1, 512, 'resources.cpus')
    _integer(resources['memory_mib'], 16, 1 << 22, 'resources.memory_mib')
    _integer(resources['wall_seconds'], 1, 30 * 86400, 'resources.wall_seconds')
    if 'disk_mib' in resources:
        _integer(resources['disk_mib'], 1, 1 << 30, 'resources.disk_mib')
    for field in ('inputs', 'readonly_trees'):
        rows = spec.get(field, [])
        if not isinstance(rows, list):
            raise ValueError(f'{field} must be a list')
        for row in rows:
            _keys(row, ('path',), ('mount', 'env', 'sha256'), field[:-1])
            if not isinstance(row['path'], str) or not row['path']:
                raise ValueError(f'{field} path required')
            if 'mount' in row and (not isinstance(row['mount'], str) or not row['mount'].startswith('/')):
                raise ValueError(f'{field} mount must be an absolute guest path')
            if 'env' in row:
                _env_name(row['env'])
    names = set()
    if not isinstance(spec['outputs'], list):
        raise ValueError('outputs must be a list')
    for row in spec['outputs']:
        _keys(row, ('name',), ('destination', 'kind', 'remote_uri', 'required'), 'output')
        _relative(row['name'], 'output name')
        if row['name'] in names:
            raise ValueError(f"duplicate output {row['name']}")
        names.add(row['name'])
        if row.get('kind', 'file') not in ('file', 'directory'):
            raise ValueError('output kind must be file or directory')
        if 'destination' in row:
            _relative(row['destination'], 'output destination')
        if 'remote_uri' in row and (not isinstance(row['remote_uri'], str) or not row['remote_uri']):
            raise ValueError('output remote_uri must be a nonempty string')
        if 'destination' not in row and 'remote_uri' not in row:
            raise ValueError(f"output {row['name']} needs a destination or a declared remote_uri")
        if 'required' in row and type(row['required']) is not bool:
            raise ValueError('output required must be true or false')
    destinations = [row['destination'] for row in spec['outputs'] if 'destination' in row]
    if len(set(destinations)) != len(destinations):
        raise ValueError('two outputs share one destination')
    for row in spec.get('quantities', []):
        _keys(row, ('name', 'output', 'pointer'), (), 'quantity')
        if row['output'] not in names:
            raise ValueError(f"quantity {row['name']} must read a declared output")
        if not isinstance(row['pointer'], str) or not row['pointer'].startswith('/'):
            raise ValueError('quantity pointer must start with /')
    env = spec.get('env', {})
    if not isinstance(env, dict):
        raise ValueError('env must be an object')
    for name, value in env.items():
        _env_name(name)
        if not isinstance(value, str) or '\x00' in value:
            raise ValueError(f'environment value for {name} must be a string')
    if 'image' in spec:
        validate_image(spec['image'])
    if 'source' in spec:
        validate_source(spec['source'])
    if 'workdir' in spec and (not isinstance(spec['workdir'], str) or not spec['workdir'].startswith('/')):
        raise ValueError('workdir must be an absolute guest path')
    if 'inherit_runtime_environment' in spec and spec['inherit_runtime_environment'] is not True:
        raise ValueError('inherit_runtime_environment must be true when present')
    if 'site' in spec and not isinstance(spec['site'], dict):
        raise ValueError('site must be an object')
    return deepcopy(spec)


def _env_name(name):
    if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
        raise ValueError(f'invalid environment name {name!r}')
    if _CREDENTIAL.search(name):
        raise ValueError(f'credential-like environment variable {name} refused; credentials stay in the tool\'s own configuration')
    return name


# ---------------------------------------------------------------- registry
_INSTANCES = {}


def kinds():
    return tuple(ADAPTERS)


def get(kind):
    if kind not in ADAPTERS:
        raise ValueError(f'unknown execution backend {kind!r}; known: {", ".join(ADAPTERS)}')
    if kind not in _INSTANCES:
        module, name, _ = ADAPTERS[kind]
        _INSTANCES[kind] = getattr(importlib.import_module(module), name)()
    return _INSTANCES[kind]


class Backend:
    """Base adapter. Subclasses override the remote operations."""

    kind = 'base'
    local = True

    def validate(self, spec):
        return spec

    def describe(self, spec):
        return {'kind': self.kind, 'local': self.is_local(spec)}

    def is_local(self, spec):
        """True when this specification runs on this machine (it then takes the machine lease)."""
        return self.local

    def doctor(self):
        return {'backend': self.kind, 'ready': True, 'checks': []}

    def submit(self, plan, handle):
        raise NotImplementedError

    def observe(self, plan, handle):
        raise NotImplementedError

    def logs(self, plan, handle):
        return ''

    def cancel(self, plan, handle):
        raise NotImplementedError

    def find(self, plan, handle):
        """Return the remote identity for this handle's tag, or None if never dispatched."""
        return None

    def dispatch_evidence(self, plan, handle):
        """True when a dispatch may have started although no remote identity was recorded."""
        return False

    def settle_unidentified(self, plan, handle):
        """For a dispatch with evidence but no identity: 'never-started' when it provably started
        nothing, else None (it stays unknown until an operator resolves it)."""
        return None

    def verify(self, plan):
        """Re-check what the plan pins about the backend itself (for example an executable)."""
        return None

    def retrieve(self, plan, handle, staging):
        raise NotImplementedError

    def stat_remote(self, plan, handle, output):
        raise ValueError(f'{self.kind} backend has no remote outputs')

    def release(self, plan, handle):
        return None


# ---------------------------------------------------------------- plans
def prepare(spec, *, base=None):
    """Validate a stage specification and pin it as an immutable backend plan."""
    spec = validate_spec(spec)
    backend = get(spec['backend'])
    spec = backend.validate(spec)
    root = Path(base).resolve() if base is not None else Path.cwd()

    def facts(rows):
        out = []
        for row in rows:
            path = Path(row['path'])
            path = path if path.is_absolute() else root / path
            fact = identity(path.resolve())
            if 'sha256' in row and row['sha256'] != fact['sha256']:
                raise ValueError(f"input {row['path']} differs from its declared sha256")
            for key in ('mount', 'env'):
                if key in row:
                    fact[key] = row[key]
            out.append(fact)
        return out
    plan = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-backend-plan', 'spec': spec,
            'inputs': facts(spec.get('inputs', [])), 'readonly_trees': facts(spec.get('readonly_trees', [])),
            'backend': backend.describe(spec)}
    plan['plan_sha256'] = digest(plan)
    return plan


def write_plan(plan, path):
    path = Path(path)
    if path.exists():
        raise ValueError(f'plan file already exists: {path}')
    atomic_json(path, plan)
    return path


def check_plan(plan):
    body = {k: v for k, v in plan.items() if k != 'plan_sha256'}
    if plan.get('kind') != 'ravel-backend-plan' or plan.get('plan_sha256') != digest(body):
        raise ValueError('backend plan digest does not match its content')
    validate_spec(plan['spec'])
    # Locality and kind come from the adapter, never from the plan's own description.
    adapter = get(plan['spec']['backend'])
    described = plan.get('backend')
    if (not isinstance(described, dict) or described.get('kind') != adapter.kind
            or described.get('local') is not adapter.is_local(plan['spec'])):
        raise ValueError(f"backend plan describes its backend differently from the {adapter.kind} adapter")
    return plan


def is_local(plan):
    return get(plan['spec']['backend']).is_local(plan['spec'])


def _verify(plan):
    for fact in [*plan['inputs'], *plan['readonly_trees']]:
        current = identity(fact['path'])
        if current['sha256'] != fact['sha256']:
            raise ValueError(f"input {fact['path']} changed since the plan was prepared")
    get(plan['spec']['backend']).verify(plan)
    return plan


def load_plan(path, *, verify_inputs=True):
    plan = check_plan(read_json(path))
    return _verify(plan) if verify_inputs else plan


def load_plan_bytes(data, *, verify_inputs=True):
    """A plan parsed from exactly these bytes (the caller checked their digest)."""
    plan = check_plan(json.loads(data))
    return _verify(plan) if verify_inputs else plan


# ---------------------------------------------------------------- handles
def handle_tag(plan, attempt_dir):
    return 'ravel-' + plan['plan_sha256'][:12] + '-' + hashlib.sha256(str(Path(attempt_dir).resolve()).encode()).hexdigest()[:12]


def read_handle(attempt_dir):
    return read_json(Path(attempt_dir) / HANDLE_NAME)


def write_handle(handle):
    atomic_json(Path(handle['attempt_dir']) / HANDLE_NAME, handle)


def _journal(handle, row):
    path = Path(handle['attempt_dir']) / OBSERVATIONS_NAME
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def dispatch_authority(plan, authority=None, plan_bytes=None):
    """The approved job a dispatch belongs to; refuse before anything is written otherwise.

    A local job is dispatched only by a process that works under the machine lease
    (it acquired the lease for an approved stage, or holds a proven delegation of
    one). A remote job needs the same lease, a proven descendant of its holder, or
    ``authority=(rundir, stage)`` naming the approved supervised stage whose proven
    worker this process is.

    A lease alone is not enough: every dispatch re-verifies the approval the lease
    was taken for and binds the submitted plan to it (``_bind_plan``).
    """
    from . import machine_lease, method_selection
    if authority is not None:
        method_selection.require_launch(authority[0])
    lease = machine_lease.working()
    if lease is None and not is_local(plan):
        # A remote job needs no machine lease of its own; a proven process of an approved stage's job suffices.
        lease = machine_lease.inherited()
    if lease is not None:
        method_selection.require_launch(lease.rundir)
        bound = _bind_plan(plan, lease, authority, plan_bytes)
        return {'lease_id': lease.lease_id, 'rundir': lease.rundir, 'node_id': lease.node_id, **bound}
    if not is_local(plan) and authority is not None:
        verified = require_approved_stage(*authority)
        method_selection.require_launch(verified['rundir'], verified.get('required_plan'))
        return {'lease_id': None, 'rundir': verified['rundir'], 'node_id': verified['stage'],
                'bound': 'approved-stage-worker', 'attempt_id': verified['attempt_id']}
    raise ValueError('a backend job is dispatched only inside an approved supervised stage (the machine lease of an '
                     'approved stage, or its proven worker); nothing was started')


def _bind_plan(plan, lease, authority, plan_bytes):
    """Re-verify the lease's approved stage now and bind ``plan`` to it.

    The plan is bound in one of two ways: its exact bytes are a pinned input of the
    running attempt of the lease's own stage (the supervised backend worker), or the
    caller is the proven worker of an approved supervised stage
    (``require_approved_stage``), which derived plans (partitions, sub-stages) need.
    Only the test lock domain admits a lease taken without a binding.
    """
    from . import execution, machine_lease
    record = machine_lease._read_record() or {}
    if record.get('lease_id') != lease.lease_id:
        raise ValueError('the machine lease this process works under is no longer held; nothing was started')
    binding = record.get('binding')
    if isinstance(binding, dict) and binding.get('route') == 'test-domain':
        if machine_lease.domain() != 'test':
            raise ValueError('a test-domain lease cannot dispatch in the machine domain; nothing was started')
        return {'bound': 'test-domain'}
    if not isinstance(binding, dict):
        raise ValueError('the machine lease carries no approved stage binding; nothing was started')
    verify_stage_binding(binding)  # the approval must hold now, not only when the lease was taken
    if plan_bytes is not None:
        scope = None if authority is None else (str(Path(authority[0]).resolve()), authority[1])
        if scope is None or scope != (lease.rundir, lease.node_id):
            raise ValueError('the pinned plan names another stage than the lease it is dispatched under; '
                             'nothing was started')
        stage = execution.load_execution(scope[0])['stages'].get(scope[1]) or {}
        if stage.get('status') != 'running':
            raise ValueError(f'stage {scope[1]} has no running supervised attempt; nothing was started')
        sha = hashlib.sha256(plan_bytes).hexdigest()
        pinned = any(isinstance(entry, dict) and entry.get('kind') == 'file' and len(entry.get('files', [])) == 1
                     and entry['files'][0].get('sha256') == sha
                     for entry in (stage.get('input_snapshot') or {}).values())
        if not pinned or json.loads(plan_bytes).get('plan_sha256') != plan['plan_sha256']:
            raise ValueError(f'the plan is not a pinned input of the running attempt of stage {scope[1]}; '
                             'nothing was started')
        return {'bound': 'pinned-plan', 'binding_route': binding['route'], 'attempt_id': stage.get('attempt_id'),
                'plan_file_sha256': sha}
    target = authority if authority is not None else (binding['rundir'], binding['node_id'])
    verified = require_approved_stage(*target)
    return {'bound': 'approved-stage-worker', 'binding_route': binding['route'], 'attempt_id': verified['attempt_id'],
            'authority_stage': verified['stage']}


def _write_bytes_durably(path, data):
    tmp = path.with_name('.' + path.name + '.tmp')
    with open(tmp, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def submit(plan, attempt_dir, *, backend=None, plan_bytes=None, authority=None):
    """Write the durable handle, then dispatch. Never resubmits.

    Refused before anything is written unless the caller works inside an approved
    supervised stage (``dispatch_authority``). ``plan_bytes`` are the verified bytes
    of the pinned plan file; the attempt keeps exactly those bytes as ``plan.json``
    so the custody chain can check them.
    """
    check_plan(plan)
    granted = dispatch_authority(plan, authority, plan_bytes)
    backend = backend or get(plan['spec']['backend'])
    attempt_dir = Path(attempt_dir).resolve()
    if (attempt_dir / HANDLE_NAME).exists():
        raise ValueError('this attempt already has a backend handle; recover it instead of submitting again')
    # The stage was authorized when it launched; live steering is decided again at each
    # submission and held across it, so a pause that commits first stops this job from being
    # written or dispatched and one that commits later finds it running (it drains).
    with _steering_admission(granted):
        return _submit_admitted(plan, attempt_dir, backend, plan_bytes, granted)


@contextmanager
def _steering_admission(granted):
    """The steering transaction of one submission, on the run and stage that own the job."""
    from . import gate_wiring
    if granted.get('rundir') is None:
        if granted.get('bound') != 'test-domain':
            raise gate_wiring.SteeringRefused('the dispatch names no owning run for live steering; nothing was started')
        yield  # only a test-domain lease is taken without a run
        return
    with gate_wiring.steering_dispatch(granted['rundir'], granted.get('node_id')):
        yield


def _submit_admitted(plan, attempt_dir, backend, plan_bytes, granted):
    attempt_dir.mkdir(parents=True, exist_ok=True)
    if not (attempt_dir / 'plan.json').exists():
        if plan_bytes is None:
            atomic_json(attempt_dir / 'plan.json', plan)
        else:
            if json.loads(plan_bytes).get('plan_sha256') != plan['plan_sha256']:
                raise ValueError('plan bytes do not hold this plan')
            _write_bytes_durably(attempt_dir / 'plan.json', plan_bytes)
    handle = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-backend-handle', 'backend': backend.kind,
              'plan_sha256': plan['plan_sha256'], 'plan_file_sha256': file_sha256(attempt_dir / 'plan.json'),
              'tag': handle_tag(plan, attempt_dir),
              'attempt_dir': str(attempt_dir), 'job_dir': str(attempt_dir / 'job'),
              'state': 'dispatching', 'created_utc': utc_now(), 'remote': None,
              'cancel_requested': False, 'resolution': None, 'authority': granted}
    write_handle(handle)
    try:
        remote = backend.submit(plan, handle)
    except BaseException as exc:
        handle['state'] = 'dispatch-unknown'
        handle['dispatch_error'] = redact(f'{type(exc).__name__}: {exc}')
        try:
            found = backend.find(plan, handle)
        except Exception:
            found = None
        if found is not None:
            # The job started before the submission failed: record its identity so the caller
            # can cancel it and recovery can observe it.
            handle['remote'] = found
            handle['state'] = 'submitted'
            handle['adopted_after_dispatch_error'] = True
        write_handle(handle)
        raise
    handle['remote'] = remote
    handle['state'] = 'submitted'
    handle['submitted_utc'] = utc_now()
    write_handle(handle)
    return handle


def observe(plan, handle):
    backend = get(handle['backend'])
    if handle['remote'] is None:
        observation = {'state': 'unknown', 'exit_code': None, 'detail': 'no remote identity recorded; run recover'}
    else:
        observation = backend.observe(plan, handle)
    if observation['state'] not in STATES:
        raise ValueError(f"backend returned an unknown state {observation['state']!r}")
    observation = {**observation, 'observed_utc': utc_now()}
    if 'detail' in observation:
        observation['detail'] = redact(str(observation['detail']))
    _journal(handle, {'event': 'observe', **observation})
    if observation['state'] in TERMINAL and handle.get('resolution') != observation['state']:
        handle['resolution'] = observation['state']
        write_handle(handle)
    return observation


def logs(plan, handle, since=0):
    if handle['remote'] is None:
        return '', since
    text = redact(get(handle['backend']).logs(plan, handle) or '')
    return text[since:], len(text)


def cancel(plan, handle, *, wait_seconds=30.0, poll=0.25):
    """Request cancellation, then wait (bounded) for an observed terminal state."""
    handle['cancel_requested'] = True
    handle['cancel_requested_utc'] = utc_now()
    write_handle(handle)
    backend = get(handle['backend'])
    if handle['remote'] is not None:
        # Escalation fits inside the caller's wait, so a supervisor that waits for
        # this cancel never outlives a payload that ignores SIGTERM.
        kwargs = ({'grace': max(0.1, min(5.0, wait_seconds / 2))}
                  if 'grace' in inspect.signature(backend.cancel).parameters else {})
        try:
            result = backend.cancel(plan, handle, **kwargs)
            if isinstance(result, dict):
                _journal(handle, {'event': 'cancel', **{k: redact(str(v)) if isinstance(v, str) else v
                                                        for k, v in result.items()}})
        except Exception as exc:  # recorded; the observation below decides
            _journal(handle, {'event': 'cancel-error', 'detail': redact(str(exc))})
    deadline = time.monotonic() + wait_seconds
    while True:
        observation = observe(plan, handle)
        if observation['state'] in TERMINAL or time.monotonic() >= deadline:
            return observation
        time.sleep(poll)


def recover(plan, handle):
    """Adopt a dispatched job by its tag; never submits again."""
    backend = get(handle['backend'])
    if handle['remote'] is None:
        remote = backend.find(plan, handle)
        handle['recovery'] = {'searched_utc': utc_now(), 'found': remote is not None}
        if remote is not None:
            handle['remote'] = remote
            handle['state'] = 'submitted'
        write_handle(handle)
    if handle['remote'] is not None:
        return {'handle': handle, 'observation': observe(plan, handle)}
    if backend.dispatch_evidence(plan, handle):
        # A launch may be running without a recorded identity: never call that "never dispatched"
        # unless the backend proves it started nothing.
        if backend.settle_unidentified(plan, handle) == 'never-started':
            handle['resolution'] = 'never-started'
            handle['recovery'] = {**handle.get('recovery', {}), 'settled_utc': utc_now()}
            write_handle(handle)
            return {'handle': handle, 'observation': {
                'state': 'unknown', 'exit_code': None,
                'detail': 'the launch recorded no identity and no process of it remains; the payload never started'}}
        return {'handle': handle, 'observation': {
            'state': 'unknown', 'exit_code': None,
            'detail': ('a dispatch started but recorded no identity, and a process may still hold it; stop it, '
                       'or clear its fence entry with "ravel lease clear-fence --token T --reason R --operator O", '
                       'which resolves this handle')}}
    handle['resolution'] = 'never-dispatched'
    write_handle(handle)
    return {'handle': handle, 'observation': {
        'state': 'unknown', 'exit_code': None, 'detail': 'no job with this tag was found; nothing was dispatched'}}


def handle_resolved(handle):
    return handle.get('resolution') is not None or handle.get('state') not in UNRESOLVED_HANDLE_STATES


# ---------------------------------------------------------------- outputs
def fetch(plan, handle, base):
    """Stage, hash and move declared outputs into place; refuse to overwrite."""
    base = Path(base).resolve()
    observation = observe(plan, handle)
    if observation['state'] != 'succeeded':
        raise ValueError(f"job has not succeeded (observed {observation['state']}); outputs are not fetched")
    attempt = Path(handle['attempt_dir'])
    staging = attempt / 'staging'
    if staging.exists():
        raise ValueError('staging directory already exists for this attempt; outputs were fetched before')
    staging.mkdir()
    backend = get(handle['backend'])
    backend.retrieve(plan, handle, staging)
    spec = plan['spec']
    outputs, remote_outputs, moves = [], [], []
    for row in spec['outputs']:
        required = row.get('required', True)
        if 'destination' not in row:
            stat = backend.stat_remote(plan, handle, row)
            if required and not stat.get('exists'):
                raise ValueError(f"declared remote output {row['name']} was not found at {row['remote_uri']}")
            remote_outputs.append({'name': row['name'], 'remote_uri': row['remote_uri'], **stat})
            continue
        staged = staging / row['name']
        kind = row.get('kind', 'file')
        present = staged.is_file() if kind == 'file' else staged.is_dir()
        if not present:
            if required:
                raise ValueError(f"declared output {row['name']} is missing after the job reported success")
            continue
        if staged.is_symlink():
            raise ValueError(f"declared output {row['name']} is a symlink")
        fact = identity(staged)
        destination = base / row['destination']
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'output destination already exists: {destination}')
        moves.append((staged, destination, fact, row))
    quantities = {}
    for row in spec.get('quantities', []):
        source = next(m for m in moves if m[3]['name'] == row['output']) if any(m[3]['name'] == row['output'] for m in moves) else None
        if source is None:
            raise ValueError(f"requested quantity {row['name']} cannot be read: output {row['output']} is absent")
        try:
            document = read_json(source[0])
            value = json_pointer(document, row['pointer'])
        except (KeyError, ValueError, OSError) as exc:
            raise ValueError(f"requested quantity {row['name']} is missing from {row['output']}") from exc
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError(f"requested quantity {row['name']} is missing from {row['output']}")
        quantities[row['name']] = value
    for staged, destination, fact, row in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(destination))
        after = identity(destination)
        if after['sha256'] != fact['sha256']:
            raise ValueError(f'output {destination} changed while it was moved')
        outputs.append({'name': row['name'], 'destination': str(destination), 'kind': fact['kind'],
                        'sha256': fact['sha256'], 'size': fact['size']})
    receipt = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-backend-fetch-receipt',
               'plan_sha256': plan['plan_sha256'], 'tag': handle['tag'], 'backend': handle['backend'],
               'remote': handle['remote'], 'outputs': outputs, 'remote_outputs': remote_outputs,
               'quantities': quantities, 'fetched_utc': utc_now()}
    atomic_json(attempt / RECEIPT_NAME, receipt)
    handle['state'] = 'fetched'
    write_handle(handle)
    try:
        backend.release(plan, handle)
    except Exception as exc:
        _journal(handle, {'event': 'release-error', 'detail': redact(str(exc))})
    return receipt


# ---------------------------------------------------------------- leases
def state_dir():
    from .machine_lease import state_dir as lease_state_dir
    return lease_state_dir()


@contextmanager
def _flock(path, message):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(message) from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def machine_lease(holder, *, wait_seconds=0.0, rundir=None, node_id=None, nested=False):
    """One native scientific job on this machine at a time (see machine_lease).

    A proven descendant of the holder works under the lease only for the same job.
    """
    from . import machine_lease as lease
    with lease.held(holder, wait_seconds=wait_seconds, rundir=rundir, node_id=node_id, nested=nested) as held:
        yield held


def remote_ceiling():
    configured = os.environ.get('RAVEL_REMOTE_JOB_CEILING')
    if configured is None:
        path = state_dir() / 'remote-ceiling.json'
        configured = read_json(path).get('max_jobs') if path.is_file() else 1
    value = int(configured)
    if value < 1:
        raise ValueError('remote job ceiling must be at least 1')
    return value


@contextmanager
def remote_slot(holder):
    ceiling = remote_ceiling()
    leases = state_dir() / 'leases'
    for index in range(ceiling):
        lock = leases / f'remote-slot-{index}.lock'
        try:
            manager = _flock(lock, 'busy')
            manager.__enter__()
        except ValueError:
            continue
        try:
            atomic_json(leases / f'remote-slot-{index}.json', {'holder': holder, 'pid': os.getpid(), 'since_utc': utc_now()})
            yield index
        finally:
            manager.__exit__(None, None, None)
        return
    raise ValueError(f'the remote job ceiling of {ceiling} is reached; the owner sets it with RAVEL_REMOTE_JOB_CEILING '
                     f'or {state_dir() / "remote-ceiling.json"}')


@contextmanager
def capacity(plan, holder, *, lease_held=False, rundir=None, node_id=None, nested=False):
    """Machine lease for local backends; a remote slot for remote ones.

    ``rundir``/``node_id`` name the job; a worker under a proven holder receives
    the lease only for that same job (``machine_lease``). Locality comes from the
    adapter, not from the plan.
    """
    if is_local(plan):
        # lease_held is accepted for compatibility only: an inherited lease is
        # proven by machine_lease (holder record and process ancestry), never assumed.
        with machine_lease(holder, rundir=rundir, node_id=node_id, nested=nested):
            yield
    else:
        with remote_slot(holder):
            yield


# ---------------------------------------------------------------- approved compute drivers
BINDING_ROUTES = ('checkin1', 'native-plan', 'science', 'scoped-likelihood')


def approved_binding(rundir, stage, route, rung=None):
    """The approved stage a machine lease is taken for, verified now (machine_lease.acquire re-verifies it)."""
    binding = {'rundir': str(Path(rundir).resolve()), 'node_id': stage, 'route': route, 'rung': rung}
    verify_stage_binding(binding)
    return binding


def verify_stage_binding(binding):
    """Refuse a stage binding whose approval does not hold now."""
    from . import workflow_state
    route, rung = binding.get('route'), binding.get('rung')
    root = Path(binding.get('rundir') or '')
    if route not in BINDING_ROUTES or not binding.get('rundir') or not binding.get('node_id') or not root.is_dir():
        raise ValueError('the stage binding names no approved run stage; nothing was started')
    if route == 'checkin1':
        if rung not in ('smoke', 'full', 'scan'):
            raise ValueError('a CHECK-IN 1 stage binding needs the smoke, full or scan rung')
        errors = workflow_state.verify_approval(str(root), required_plan=rung)
        if errors:
            raise ValueError('the stage is not approved: ' + '; '.join(errors))
    elif route == 'native-plan':
        from ravel.physics.native_pipeline import load_plan as load_native_plan, verify_execution_approval
        verify_execution_approval(load_native_plan(root / 'inputs/native_execution_plan.json'))
    elif route == 'science':
        from . import physics_review, science
        if not (physics_review._science_run(root) and (root / science.PLAN).is_file()):
            raise ValueError('the stage is not an approved scientific study stage')
        _verify_science_receipt(root)
    else:
        plan = root / 'inputs/scoped-plan.json'
        if not plan.is_file() or read_json(plan).get('mode') != 'likelihood' \
                or not (root / 'inputs/checkin1_approval.json').is_file():
            raise ValueError('the stage is not an approved scoped likelihood stage')
        from . import scoped
        scoped.verify_plan(root, require_approval=True)  # the pinned plan and its full CHECK-IN 1 approval, now
    return binding


def _verify_science_receipt(root):
    """The study's approval receipt holds now: it binds the current plan, specification, check-in,
    review policy and approval inputs (the full plan check runs at launch)."""
    from . import science
    if science.review_enabled(root):
        science._verify_v2_approval(Path(root), read_json(Path(root) / science.SPEC))
    else:
        science.verify_plan(root, approved=True)


def require_approved_stage(rundir, stage, pinned=()):
    """Admit a compute driver only as the worker of an approved, authorized supervised attempt.

    The caller must be the registered worker (or proven backend payload) of the
    stage's running attempt; the attempt must carry a launch-authorization receipt
    that matches its journal event and the exact supervised command; and every
    pinned file must be a stage input with the same bytes the attempt recorded.
    """
    from . import execution, launch_authorization
    if rundir is None or stage is None:
        raise ValueError('this command runs only as a supervised stage of an approved run; '
                         'pass --rundir and --stage and launch it through the stage supervisor')
    rd = Path(rundir).resolve()
    execution.await_worker_registration(rd, stage)
    record = execution.load_execution(rd)['stages'][stage]
    receipt = record.get('authorization_receipt')
    if not isinstance(receipt, dict):
        raise ValueError(f'stage {stage} was launched without an approved-run launch authorization')
    events = {event['sequence']: event for event in launch_authorization._events(rd)}
    launched = events.get(receipt.get('sequence'))
    if (launched is None or launched.get('event') != 'launched' or launched.get('sha256') != receipt.get('sha256')
            or launched.get('pid') != record.get('child_pid')):
        raise ValueError(f'stage {stage} launch authorization receipt does not match its launch event')
    authorized = events.get(launched.get('authorization_sequence'))
    if (authorized is None or authorized.get('event') != 'authorized'
            or authorized.get('command') != list(map(str, record['command']))
            or authorized.get('context', {}).get('stage') != stage):
        raise ValueError(f'stage {stage} launch authorization does not cover this supervised command')
    rung = (authorized.get('authorization') or {}).get('required_plan')
    # The approval must still hold now, not only at launch (a plan pinned later changes it).
    if rung in ('smoke', 'full', 'scan'):
        from . import workflow_state
        errors = workflow_state.verify_approval(str(rd), required_plan=rung)
    elif rung == 'science':
        from . import physics_review, science
        current = (rd / science.PLAN).is_file() and execution.file_hash(rd / science.PLAN)
        errors = ([] if physics_review._science_run(rd) and science.review_enabled(rd)
                  and current == authorized.get('context', {}).get('plan_sha256')
                  else ['the scientific study plan or its review changed since launch'])
        # A revoked or changed approval receipt with an unchanged plan is caught here.
        if not errors:
            try:
                _verify_science_receipt(rd)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors = [str(exc)]
    else:
        errors = [f'the launch authorization names no compute rung ({rung!r})']
    if errors:
        raise ValueError(f'stage {stage} approval no longer holds: ' + '; '.join(errors))
    recorded = record.get('input_snapshot', {})
    for path, value in execution.snapshot(rd, [str(Path(p).resolve()) for p in pinned]).items():
        if recorded.get(path) != value:
            raise ValueError(f'{path} is not a pinned input of the approved stage {stage}')
    context = authorized.get('context', {})
    return {'rundir': str(rd), 'stage': stage, 'attempt_id': record['attempt_id'],
            'authorization_receipt': receipt,
            'required_plan': (authorized.get('authorization') or {}).get('required_plan'),
            'events': context.get('events'), 'max_seconds': context.get('max_seconds')}


# ---------------------------------------------------------------- doctor
def released_kinds():
    """Default offers follow the toolchain release list; named adapters stay intact."""
    from ravel.setup import manifest as mf
    if mf.manifest_path().is_file():
        manifest = mf.load()[0]
        return [kind for kind in kinds() if not mf.release_mentions(manifest, kind)]
    # Installed packages carry the generated atlas's release-filtered tool offers.
    from .knowledge import load_atlas
    ids = {row['id'] for row in load_atlas()['entries']}
    return [kind for kind in kinds() if kind != 'magnus' or 'tool:magnus' in ids]


def doctor_all():
    rows = []
    for kind in released_kinds():
        try:
            rows.append(get(kind).doctor())
        except Exception as exc:
            rows.append({'backend': kind, 'ready': False, 'checks': [{'name': 'doctor', 'ok': False, 'detail': redact(str(exc))}]})
    return rows


# ---------------------------------------------------------------- supervised worker
def attempt_backend_dir(rundir, stage, attempt_id):
    return Path(rundir).resolve() / 'logs/execution' / stage / attempt_id / 'backend'


def stage_handles(rundir, stage=None):
    root = Path(rundir).resolve() / 'logs/execution'
    pattern = f'{stage}/*/backend/{HANDLE_NAME}' if stage else f'*/*/backend/{HANDLE_NAME}'
    return sorted(root.glob(pattern))


def worker_command(rundir, stage, plan_path, *, python=None, poll=None, cancel_wait=None):
    command = [python or sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker',
               '--rundir', str(Path(rundir).resolve()), '--stage', stage, '--plan', str(Path(plan_path).resolve())]
    if poll is not None:
        command += ['--poll', repr(float(poll))]
    if cancel_wait is not None:
        command += ['--cancel-wait', repr(float(cancel_wait))]
    return command


class _Stop(Exception):
    pass


def pinned_plan_bytes(record, plan_path):
    """The plan file's bytes, refused unless they are exactly the attempt's pinned input."""
    path = Path(plan_path).resolve()
    entry = (record.get('input_snapshot') or {}).get(str(path))
    if not isinstance(entry, dict) or entry.get('kind') != 'file' or len(entry.get('files', [])) != 1:
        raise ValueError('the backend plan is not a pinned input of the supervised attempt')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['files'][0]['sha256']:
        raise ValueError('the backend plan changed after the supervised attempt pinned it')
    return data


def _settle(plan, handle, cancel_wait, stream):
    """Cancel a dispatched job that has not reached an observed terminal state."""
    if handle is None or handle.get('remote') is None or handle.get('resolution') in TERMINAL:
        return None
    observation = cancel(plan, handle, wait_seconds=cancel_wait)
    if observation['state'] not in TERMINAL:
        print(f"backend worker: job {handle['tag']} did not stop (observed {observation['state']}); it stays fenced "
              f"on the machine lease until its process group is gone", file=stream, flush=True)
    return observation


def worker(rundir, stage, plan_path, *, poll=5.0, register=True, stream=None, cancel_wait=8.0, lease_held=False):
    """Run one backend job as the supervised stage's process.

    Exit codes: 0 success, 1 job failed, 2 refused, 3 implausible success
    (missing outputs or quantities), 124 wall clock, 130 interrupted. Every exit
    after dispatch cancels a job that has not ended; a job that does not stop stays
    fenced on the machine lease.
    """
    from . import execution
    stream = stream or sys.stdout
    rundir = Path(rundir).resolve()
    if register:
        execution.await_worker_registration(rundir, stage)
    record = execution.load_execution(rundir)['stages'].get(stage, {})
    if record.get('status') != 'running' or not record.get('attempt_id'):
        print('backend worker: no running supervised attempt for this stage', file=sys.stderr)
        return 2
    try:
        plan_bytes = pinned_plan_bytes(record, plan_path)
        plan = load_plan_bytes(plan_bytes)
    except (OSError, ValueError) as exc:
        print(f'backend worker: {exc}', file=sys.stderr)
        return 2
    if plan['spec']['stage'] != stage:
        print('backend worker: plan stage differs from the supervised stage', file=sys.stderr)
        return 2
    attempt = attempt_backend_dir(rundir, stage, record['attempt_id'])
    for path in stage_handles(rundir, stage):
        if path.parent == attempt:
            continue
        earlier = read_json(path)
        if not handle_resolved(earlier):
            print(f"backend worker: earlier job {earlier['tag']} is unresolved; run "
                  f"'ravel backend recover --handle {path.parent}' before launching again", file=sys.stderr)
            return 2
    stop = {'signal': None}

    def interrupted(signum, frame):
        stop['signal'] = signum
        raise _Stop()
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)}
    box = {'handle': None}
    try:
        with capacity(plan, f'{rundir}:{stage}:{record["attempt_id"]}', lease_held=lease_held,
                      rundir=str(rundir), node_id=stage):
            # The job is cancelled before the lease scope ends on every exit path.
            try:
                return _drive(plan, plan_bytes, attempt, rundir, box, poll, cancel_wait, stream)
            except _Stop:
                if box['handle'] is not None:
                    observation = _settle(plan, box['handle'], cancel_wait, stream) or observe(plan, box['handle'])
                    print(f"backend worker: interrupted; cancellation observed state {observation['state']}",
                          file=stream, flush=True)
                return 130
            except Exception as exc:
                print(f'backend worker: {redact(str(exc))}', file=sys.stderr)
                try:
                    _settle(plan, box['handle'], cancel_wait, stream)
                except Exception as cancel_exc:
                    print(f'backend worker: cancel after error failed: {redact(str(cancel_exc))}', file=sys.stderr)
                return 2
    except _Stop:
        return 130
    except Exception as exc:
        print(f'backend worker: {redact(str(exc))}', file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _drive(plan, plan_bytes, attempt, rundir, box, poll, cancel_wait, stream):
    try:
        box['handle'] = submit(plan, attempt, plan_bytes=plan_bytes, authority=(rundir, plan['spec']['stage']))
    except BaseException:
        box['handle'] = read_handle(attempt) if (attempt / HANDLE_NAME).is_file() else None
        raise
    handle = box['handle']
    print(f"backend {handle['backend']} job {handle['tag']} submitted: {json.dumps(handle['remote'])}", file=stream, flush=True)
    offset = 0
    started = time.monotonic()
    wall = plan['spec']['resources']['wall_seconds']
    while True:
        text, offset = logs(plan, handle, offset)
        if text:
            stream.write(text)
            stream.flush()
        observation = observe(plan, handle)
        if observation['state'] in TERMINAL:
            break
        if observation.get('payload_exited'):
            print(f"backend worker: {observation['detail']}; cancelling", file=stream, flush=True)
            _settle(plan, handle, cancel_wait, stream)
            return 1
        if time.monotonic() - started > wall:
            print('backend worker: wall-clock ceiling reached; cancelling', file=stream, flush=True)
            _settle(plan, handle, cancel_wait, stream)
            return 124
        time.sleep(poll)
    text, offset = logs(plan, handle, offset)
    if text:
        stream.write(text)
        stream.flush()
    if observation['state'] == 'cancelled':
        return 130
    if observation['state'] == 'failed':
        if observation.get('requires_cancel'):
            cancel(plan, handle, wait_seconds=cancel_wait)
        print(f"backend worker: job failed: {observation.get('detail', '')} exit={observation.get('exit_code')}", file=stream, flush=True)
        return 1
    try:
        receipt = fetch(plan, handle, rundir)
    except ValueError as exc:
        print(f'backend worker: {exc}', file=stream, flush=True)
        return 3
    print('backend worker: outputs fetched: ' + json.dumps([o['destination'] for o in receipt['outputs']]), file=stream, flush=True)
    return 0


# ---------------------------------------------------------------- CLI
def _print(value):
    print(json.dumps(value, indent=2, allow_nan=False))


def _handle_and_plan(directory, plan_path=None):
    directory = Path(directory)
    handle = read_handle(directory)
    if plan_path is None:
        plan_path = directory / 'plan.json'
        if not plan_path.is_file():
            raise ValueError('pass --plan with the backend plan used for this handle')
    plan = load_plan(plan_path, verify_inputs=False)
    if plan['plan_sha256'] != handle['plan_sha256']:
        raise ValueError('plan does not belong to this handle')
    return handle, plan


def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel backend', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='list available execution backends')
    d = sub.add_parser('doctor', help='check backend runtimes without reading credentials')
    d.add_argument('--backend', choices=kinds())
    p = sub.add_parser('prepare', help='pin a stage specification as a backend plan')
    p.add_argument('--spec', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--base', type=Path, help='base directory for relative input paths')
    s = sub.add_parser('describe', help='show a backend plan summary')
    s.add_argument('--plan', type=Path, required=True)
    h = sub.add_parser('handles', help='list backend handles of a run')
    h.add_argument('--rundir', type=Path, required=True)
    h.add_argument('--stage')
    for name, text in (('status', 'observe a backend job'), ('logs', 'print a backend job log'),
                       ('cancel', 'cancel a backend job and wait for a terminal observation'),
                       ('recover', 'adopt an interrupted job by its tag; never resubmits'),
                       ('fetch', 'stage, hash and move outputs of a finished job')):
        c = sub.add_parser(name, help=text)
        c.add_argument('--handle', type=Path, required=True, help='attempt backend directory holding backend-handle.json')
        c.add_argument('--plan', type=Path, help='backend plan (default: plan recorded next to the handle)')
        if name == 'fetch':
            c.add_argument('--base', type=Path, required=True, help='directory the output destinations are relative to')
    w = sub.add_parser('worker', help='supervised stage process (used by the stage supervisor)')
    w.add_argument('--rundir', type=Path, required=True)
    w.add_argument('--stage', required=True)
    w.add_argument('--plan', type=Path, required=True)
    w.add_argument('--poll', type=float, default=5.0)
    w.add_argument('--cancel-wait', type=float, default=8.0)
    m = sub.add_parser('machine', help='podman machine life cycle inside the RAVEL prefix (dry run unless --execute)')
    m.add_argument('action', choices=('init', 'start', 'stop', 'status'))
    m.add_argument('--name', default='ravel')
    m.add_argument('--cpus', type=int, default=4)
    m.add_argument('--memory-mib', type=int, default=8192)
    m.add_argument('--disk-gib', type=int, default=40)
    m.add_argument('--execute', action='store_true')
    i = sub.add_parser('image-build', help='build a local image from a digest-pinned Containerfile (dry run unless --execute)')
    i.add_argument('--containerfile', type=Path, required=True)
    i.add_argument('--context', type=Path, required=True)
    i.add_argument('--tag', required=True)
    i.add_argument('--platform', default=None)
    i.add_argument('--receipt', type=Path, required=True)
    i.add_argument('--connection', default='ravel')
    i.add_argument('--execute', action='store_true')
    lj = sub.add_parser('launcher', help='write a container launcher record for native adapters (podman client and image pinned)')
    lj.add_argument('--image-reference', help='name@sha256:<digest>')
    lj.add_argument('--image-id', help='local image id sha256:<digest> (from an image-build receipt)')
    lj.add_argument('--platform', default=None)
    lj.add_argument('--connection', default='ravel')
    lj.add_argument('--cpus', type=int, default=1)
    lj.add_argument('--memory-mib', type=int, default=4096)
    lj.add_argument('--env', action='append', default=[], help='NAME=VALUE passed into the container (repeatable)')
    lj.add_argument('--out', type=Path, required=True)
    la = sub.add_parser('launch', help='run one command through a container launcher with identical host paths '
                                       '(dry run unless --execute; takes the machine lease)')
    la.add_argument('--launcher', type=Path, required=True)
    la.add_argument('--readonly', action='append', default=[], type=Path)
    la.add_argument('--writable', action='append', default=[], type=Path)
    la.add_argument('--workdir', type=Path, required=True)
    la.add_argument('--execute', action='store_true')
    la.add_argument('--rundir', type=Path, help='run whose approved supervised stage runs this launch (required with --execute)')
    la.add_argument('--stage', help='the supervised stage running this launch (required with --execute)')
    la.add_argument('cmd', nargs=argparse.REMAINDER)
    if 'magnus' in released_kinds():
        b = sub.add_parser('magnus-blueprint', help='export a plan as a generic Magnus blueprint YAML (data only)')
        b.add_argument('--plan', type=Path, required=True)
        b.add_argument('--out', type=Path, required=True)
    f = sub.add_parser('site-submit-file', help='render the HTCondor or SLURM submission for review')
    f.add_argument('--plan', type=Path, required=True)
    f.add_argument('--job-dir', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'list':
            for kind, (_, _, text) in ADAPTERS.items():
                if kind not in released_kinds():
                    continue
                print(f'{kind}: {text}')
            return 0
        if args.command == 'doctor':
            rows = [get(args.backend).doctor()] if args.backend else doctor_all()
            _print(rows)
            return 0 if all(r['ready'] for r in rows) else 1
        if args.command == 'prepare':
            plan = prepare(read_json(args.spec), base=args.base)
            write_plan(plan, args.out)
            _print({'plan': str(args.out), 'plan_sha256': plan['plan_sha256'], 'backend': plan['backend']})
            return 0
        if args.command == 'describe':
            plan = load_plan(args.plan, verify_inputs=False)
            spec = plan['spec']
            _print({'plan_sha256': plan['plan_sha256'], 'backend': plan['backend'], 'stage': spec['stage'],
                    'argv': spec['argv'], 'resources': spec['resources'], 'image': spec.get('image'),
                    'outputs': spec['outputs'], 'inputs': [{k: f[k] for k in ('path', 'sha256')} for f in plan['inputs']]})
            return 0
        if args.command == 'handles':
            rows = []
            for path in stage_handles(args.rundir, args.stage):
                handle = read_json(path)
                rows.append({'handle': str(path.parent), 'tag': handle['tag'], 'backend': handle['backend'],
                             'state': handle['state'], 'resolution': handle.get('resolution'), 'remote': handle['remote']})
            _print(rows)
            return 0
        if args.command == 'worker':
            return worker(args.rundir, args.stage, args.plan, poll=args.poll, cancel_wait=args.cancel_wait)
        if args.command in ('status', 'logs', 'cancel', 'recover', 'fetch'):
            handle, plan = _handle_and_plan(args.handle, args.plan)
            if args.command == 'status':
                _print({'tag': handle['tag'], 'state': handle['state'], **observe(plan, handle)})
            elif args.command == 'logs':
                print(logs(plan, handle)[0], end='')
            elif args.command == 'cancel':
                _print(cancel(plan, handle))
            elif args.command == 'recover':
                result = recover(plan, handle)
                _print({'remote': result['handle']['remote'], **result['observation']})
            else:
                _print(fetch(plan, handle, args.base))
            return 0
        if args.command == 'machine':
            from .backends import oci_local
            result = oci_local.machine(args.action, name=args.name, cpus=args.cpus, memory_mib=args.memory_mib,
                                       disk_gib=args.disk_gib, execute=args.execute)
            _print(result)
            return 0 if result.get('returncode', 0) == 0 else 1
        if args.command == 'image-build':
            from .backends import oci_local
            result = oci_local.build_image(args.containerfile, args.context, args.tag, receipt=args.receipt,
                                           platform=args.platform, connection=args.connection, execute=args.execute)
            _print(result)
            return 0
        if args.command == 'launcher':
            from .backends import oci_local
            if bool(args.image_reference) == bool(args.image_id):
                raise ValueError('pass exactly one of --image-reference or --image-id')
            image = {'platform': args.platform or oci_local.host_platform()}
            image.update({'reference': args.image_reference} if args.image_reference else {'id': args.image_id})
            env = dict(item.split('=', 1) for item in args.env)
            launcher = {'kind': 'oci-local', 'image': image, 'client': oci_local.resolve_client(),
                        'connection': args.connection, 'cpus': args.cpus, 'memory_mib': args.memory_mib}
            if env:
                launcher['env'] = env
            oci_local.validate_launcher(launcher)
            if args.out.exists():
                raise ValueError(f'{args.out} already exists')
            atomic_json(args.out, launcher)
            _print(launcher)
            return 0
        if args.command == 'launch':
            from .backends import oci_local
            import subprocess
            # Refuse before reading anything: --execute runs only inside an approved stage.
            authority = require_approved_stage(args.rundir, args.stage, pinned=[args.launcher]) if args.execute else None
            command = args.cmd[1:] if args.cmd[:1] == ['--'] else args.cmd
            if not command:
                raise ValueError('pass the command after --')
            launcher = read_json(args.launcher)
            name = 'ravel-launch-' + hashlib.sha256(str(args.workdir.resolve()).encode()).hexdigest()[:20]
            argv = oci_local.launcher_command(launcher, command, workdir=args.workdir, readonly=args.readonly,
                                              writable=args.writable, name=name)
            if not args.execute:
                _print({'argv': argv, 'executed': False, 'note': 'dry run; pass --execute after approval'})
                return 0
            from . import gate_wiring
            with machine_lease(f'launch:{args.workdir.resolve()}', rundir=authority['rundir'], node_id=authority['stage']):
                # Steering decides at the container start and is held only across the spawn; a
                # pause after it finds the container running and lets it drain.
                with gate_wiring.steering_dispatch(authority['rundir'], authority['stage']):
                    process = subprocess.Popen(argv)
                try:
                    code = process.wait()
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
                    cleanup = oci_local.cleanup_launch(launcher, name)
            _print({'exit_code': code, 'cleanup': cleanup})
            return code
        if args.command == 'magnus-blueprint':
            from .backends import magnus_cli
            text = magnus_cli.blueprint_yaml(load_plan(args.plan, verify_inputs=False))
            if args.out.exists():
                raise ValueError(f'{args.out} already exists')
            args.out.write_text(text)
            print(str(args.out))
            return 0
        if args.command == 'site-submit-file':
            from .backends import site_batch
            plan = load_plan(args.plan, verify_inputs=False)
            print(site_batch.render(plan, args.job_dir, handle_tag(plan, args.job_dir)), end='')
            return 0
    except (OSError, ValueError) as exc:
        print(f'ravel backend: {exc}', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    sys.exit(main())
