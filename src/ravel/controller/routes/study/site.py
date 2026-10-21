"""Controller-side site lifecycle, separate from workers and scheduler clients.

The shared step launcher owns submission. This module reserves durable attempt
identity before dispatch, requests launch capabilities and reconciles recorded
remote handles. It never interprets scheduler disappearance as success.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import hmac
import inspect
import json
import math
import os
from pathlib import Path
import re

from ravel.workflow.state_io import file_lock

from .contracts import digest, records, relative

TERMINAL = frozenset(('succeeded', 'failed', 'cancelled'))
JOB_TERMINAL = frozenset(('cancelled', 'exited'))


def _lock(store):
    path = store.path('locks', 'study-site.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    return file_lock(path)


def _rows(store, launch_id):
    return [r for r in records(store, 'study-site') if r.get('launch_id') == launch_id]


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


_launch = ContextVar('study_site_launch', default=None)


@contextmanager
def trusted_launch(store, launch_id, token, scope):
    """Bind the trusted scheduler boundary to one admitted launch and script."""
    bound = {'store': store, 'run_id': store.run_id, 'launch_id': launch_id,
             'token': token, 'scope': deepcopy(scope)}
    current = _launch.get()
    if current is not None and current != bound:
        raise ValueError('nested conflicting launch scope')
    marker = _launch.set(bound)
    try:
        yield
    finally:
        _launch.reset(marker)


def _durable_launch():
    """Rebuild executor custody from the bearer token and protected journals."""
    from ravel.workflow.wms_policy import CAPABILITY_ENV
    token = os.environ.get(CAPABILITY_ENV, '')
    if not token.startswith('rwc1.'):
        return None
    from ravel.controller.confine import capability, runs
    match = capability.TOKEN.fullmatch(token)
    if match is None:
        return None
    store = runs.store(match.group(1))
    launch_id = match.group(2)
    minted = [r for r in records(store, capability.KIND) if r.get('launch_id') == launch_id]
    if (len(minted) != 1 or not hmac.compare_digest(minted[0]['sha256'], capability.digest(token))
            or any(r.get('launch_id') == launch_id for r in records(store, capability.REVOKED))):
        return None
    rows = _rows(store, launch_id)
    reserved = [r for r in rows if r.get('event') == 'reserved']
    if (len(reserved) != 1 or not any(r.get('event') == 'dispatch_started' for r in rows)
            or any(r.get('event') == 'outcome' for r in rows)):
        return None
    original = reserved[0]
    if 'batch' in original:
        scripts = {'batch': original['batch']}
    elif 'jobscripts' in original:
        scripts = {'jobscripts': [{'path': str(Path(original['run_dir']) / relative(pin['path'])),
                                   'sha256': pin['sha256']} for pin in original['jobscripts']]}
    else:
        pin = original['jobscript']
        scripts = {'jobscript': {'path': str(Path(original['run_dir']) / relative(pin['path'])),
                                 'sha256': pin['sha256']}}
    return {'store': store, 'run_id': store.run_id, 'launch_id': launch_id, 'token': token,
            'scope': {**scripts, 'capability': minted[0]['scope']}}


def active_launch(*, run_id=None):
    """Observe trusted in-process launch custody without consuming admission.

    Executor subprocesses rebuild this view from protected durable state.
    """
    bound = _launch.get() or _durable_launch()
    return bound is not None and (run_id is None or bound['run_id'] == run_id)


def submission_environment():
    """Trusted launchers may pass the bearer token to their scheduler executor."""
    from ravel.workflow.wms_policy import CAPABILITY_ENV
    bound = _launch.get() or _durable_launch()
    return {CAPABILITY_ENV: bound['token']} if bound is not None else {}


def launch_options(workflow, exports):
    """Pass the parent's existing capability to the live WMS launch, without consuming it."""
    bound = _launch.get() or _durable_launch()
    if bound is None:
        return {}
    scope = bound['scope']['capability']
    if (Path(workflow).resolve() != Path(scope['workflow_dir']).resolve()
            or ('tasks' in scope and not set(exports) <= set(scope['tasks']))):
        raise ValueError('WMS launch differs from its parent capability scope')
    return {'capability': bound['token'], 'controller_run': bound['run_id']}


def _pinned_member(bound, path):
    """The one plan-pinned jobscript of a multi-submission scope that ``path`` presents."""
    presented = str(path.absolute())
    pins = [pin for pin in bound['scope']['jobscripts'] if pin['path'] == presented]
    if len(pins) != 1 or path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('scheduler jobscript is not one of the approved pinned jobscripts')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != pins[0]['sha256']:
        raise ValueError('scheduler jobscript differs from approved exact bytes')
    return pins[0]


def require_credential(path=None):
    """Observe the consumed proxy and apply the trusted controller's condition guard."""
    from ravel.controller.credential_status import require_proxy
    bound = _launch.get() or _durable_launch()
    return require_proxy(bound['store'] if bound is not None else None, path)


def require_capability(jobscript, *, run_id=None, launch_id=None,
                       profile_sha256=None, resource_defaults=None, authorized_tasks=None):
    """Verify at the final scheduler effect, using only the binding API.

    A single-jobscript scope admits its exact pinned bytes. A multi-submission
    scope admits each of its plan-pinned jobscripts at most once, only while the
    operator state is running; the capability's job count bounds the total.
    """
    from ravel.controller import confine
    bound = _launch.get() or _durable_launch()
    if bound is None:
        raise ValueError('scheduler submission requires a trusted launch capability')
    if ((run_id is not None and run_id != bound['run_id'])
            or (launch_id is not None and launch_id != bound['launch_id'])):
        raise ValueError('scheduler launch scope differs from trusted scope')
    path = Path(jobscript)
    multi = 'jobscripts' in bound['scope']
    batch = 'batch' in bound['scope']
    job = None
    if batch:
        job = _batch_member(bound, path)
    if multi or batch:
        if multi:
            pin = _pinned_member(bound, path)
        from ravel.controller import authority
        state = authority.stop_state(bound['store'])
        if state != 'running':
            raise ValueError('scheduler submission refused: operator state: ' + state)
    else:
        pin = bound['scope']['jobscript']
        if (str(path.absolute()) != pin['path'] or path.is_symlink()
                or any(p.is_symlink() for p in path.parents)
                or hashlib.sha256(path.read_bytes()).hexdigest() != pin['sha256']):
            raise ValueError('scheduler jobscript differs from approved exact bytes')
    approved = bound['scope'].get('capability', {})
    expected_profile = approved.get('profile_sha256')
    if expected_profile is not None and profile_sha256 != expected_profile:
        raise ValueError('actual scheduler profile differs from approved profile')
    # These are documented optional P05 inputs, never inferred from maxima or
    # job payloads. Exact two-argument bindings remain usable without extras.
    optional = {'store': bound['store'], 'profile_sha256': profile_sha256, 'resource_defaults': resource_defaults,
                'authorized_tasks': authorized_tasks}
    signature = inspect.signature(confine.verify_capability)
    kwargs = {key: value for key, value in optional.items()
              if value is not None and key in signature.parameters
              and signature.parameters[key].kind in
              (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
    if not multi and not batch:
        return confine.verify_capability(bound['token'], path, **kwargs)
    # Distinctness and admission share one lock, so concurrent presentations of
    # the same pinned bytes (or the same batch job) cannot both pass the check.
    with _lock(bound['store']):
        if multi and any(r.get('launch_id') == bound['launch_id'] and r.get('jobscript_sha256') == pin['sha256']
                         for r in records(bound['store'], 'wms-submission')):
            raise ValueError('this pinned jobscript was already submitted under its capability')
        if batch:
            key = _job_key(job['rule'], job['output'])
            if any(r.get('launch_id') == bound['launch_id'] and r.get('job_key') == key
                   for r in records(bound['store'], BATCH_JOB)):
                raise ValueError('this batch job (rule and outputs) was already submitted under its capability')
        admission = confine.verify_capability(bound['token'], path, **kwargs)
        if batch:
            bound['store'].append(BATCH_JOB, {
                'launch_id': bound['launch_id'], 'job_key': key, 'rule': job['rule'], 'output': job['output'],
                'jobscript_sha256': admission.get('jobscript_sha256') if isinstance(admission, dict) else None})
        return admission


BATCH_JOB = 'study-site-batch-job'


def _batch_member(bound, path):
    """The batch job a generated jobscript presents, read from its properties comment.

    The workflow manager writes each jobscript at run time inside the approved workflow directory;
    its job is the rule and output set it declares. The rule must be one the approved scope names.
    """
    from ravel.controller.confine import capability
    workflow = Path(bound['scope']['capability']['workflow_dir'])
    if (not path.is_absolute() or path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or not path.is_file() or not path.resolve().is_relative_to(workflow.resolve())):
        raise ValueError('scheduler jobscript is not an ordinary file of the approved workflow directory')
    properties = capability.job_properties(path)
    rule, output = properties.get('rule'), properties.get('output')
    if (type(rule) is not str or not rule or type(output) is not list or not output
            or any(type(name) is not str or not name for name in output)):
        raise ValueError('scheduler jobscript declares no rule and output in its properties')
    rules = bound['scope']['capability'].get('rules')
    if rules is not None and rule not in rules:
        raise ValueError('scheduler jobscript runs rule ' + rule + ', which the approved scope does not name')
    return {'rule': rule, 'output': sorted(output)}


def record_submission(admission, job):
    """Journal one admitted scheduler submission and its returned handle.

    The record lets reconciliation observe and drain the job later. This is
    custody of a scheduler handle, not evidence that the job ran or succeeded.
    A bound store without a journal interface (an inert stand-in) records nothing.
    """
    bound = _launch.get() or _durable_launch()
    if bound is None:
        raise ValueError('scheduler submission record requires a trusted launch')
    store = bound['store']
    if not callable(getattr(store, 'append', None)):
        return None
    try:
        json.dumps(job, allow_nan=False)
        value = job if isinstance(job, (str, int, dict, list)) else repr(job)
    except (TypeError, ValueError):
        value = repr(job)
    scheduler = 'htcondor' if isinstance(job, str) and re.fullmatch(r'\d+\.\d+', job) else None
    return store.append('study-site-job', {
        'launch_id': bound['launch_id'], 'run_id': bound['run_id'],
        'jobscript_sha256': admission['jobscript_sha256'], 'submissions': admission.get('submissions'),
        'job': value, 'scheduler': scheduler})


def _held(launch_id, reason):
    return {'status': 'held', 'reason': reason, 'launch_id': launch_id}


def _withdrawn(rows):
    events = [r['event'] for r in rows if r['event'] in ('reserved', 'withdrawn', 'reactivated')]
    return bool(events) and events[-1] == 'withdrawn'


def _ordinary_pinned(path, sha256):
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError('jobscript must be an ordinary pinned file')
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        raise ValueError('jobscript bytes changed before capability admission')


def _batch(count):
    """Validate a batch site step's approved job count."""
    if type(count) is not int or count < 1:
        raise ValueError('a batch site step names its positive approved job count')
    return count


def _job_key(rule, output):
    return json.dumps([rule, sorted(output)], separators=(',', ':'))


def _pinned_jobscripts(pins, run_dir):
    """Validate a plan's distinct jobscript pins; return their run-relative paths."""
    if (type(pins) is not list or not pins
            or any(type(pin) is not dict or set(pin) != {'path', 'sha256'} for pin in pins)):
        raise ValueError('a multi-submission site step needs a non-empty list of exact jobscript pins')
    paths = [Path(run_dir) / relative(pin['path']) for pin in pins]
    if any(type(pin['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', pin['sha256']) for pin in pins):
        raise ValueError('each pinned jobscript needs a lowercase sha256 digest')
    if (len({pin['path'] for pin in pins}) != len(pins)
            or len({pin['sha256'] for pin in pins}) != len(pins)):
        raise ValueError('pinned jobscripts need distinct paths and distinct exact bytes')
    for path, pin in zip(paths, pins):
        _ordinary_pinned(path, pin['sha256'])
    return paths


def dispatch(store, step, context, invoke):
    """Dispatch one capability-bound WMS step through ``controller.step``.

    Reserves the complete prospective cost, even on an interrupted call. An
    unresolved dispatch is reconciled by its original remote identity; it is
    never submitted a second time by a restarted controller. The integration
    must supply the pinned, approved jobscript and propagate the capability
    to the shared launcher's scheduler boundary. A step may instead pin a list
    of N distinct jobscripts under one capability with ``max_jobs`` N; each
    pinned script is then admitted at most once.
    """
    from ravel.controller import authority, confine
    if not callable(invoke):
        raise TypeError('the parent must supply its substrate child invocation')
    launch_id = step['id']
    stop = authority.stop_state(store)
    if stop == 'pause_requested':
        return _held(launch_id, 'operator paused before reservation')
    if stop != 'running':
        return bounded_end(store, 'operator state: ' + stop)
    launch = (step.get('parameters') or {}).get('launch') or {}
    if 'jobscript' in launch and 'jobscripts' in launch:
        raise ValueError('a site step declares either one jobscript or a jobscripts list, never both')
    if 'batch' in launch and ('jobscript' in launch or 'jobscripts' in launch):
        raise ValueError('a batch site step declares its job count and no jobscript pins')
    multi = 'jobscripts' in launch
    batch = 'batch' in launch
    if batch:
        count = _batch(launch['batch'])
    elif multi:
        pins = launch['jobscripts']
        paths = _pinned_jobscripts(pins, context['run_dir'])
    else:
        pin = launch.get('jobscript')
        if type(pin) is not dict or set(pin) != {'path', 'sha256'}:
            raise ValueError('a capability-bound WMS step needs its exact approved jobscript pin')
        path = Path(context['run_dir']) / relative(pin['path'])
        _ordinary_pinned(path, pin['sha256'])
    ceiling = context.get('site_budget')
    cost = step.get('budget', {}).get('wall_seconds')
    if not _number(ceiling) or not _number(cost) or cost <= 0:
        raise ValueError('a finite original site budget and positive prospective cost are required')
    # The binding accepts only its documented WMS scope. Exact path and
    # controller identities stay in the trusted local context, outside the token.
    scope = deepcopy((step.get('parameters') or {}).get('wms_scope') or {})
    allowed = {'workflow_dir', 'tasks', 'rules', 'max_jobs', 'profile_sha256', 'resource_maxima'}
    if set(scope) - allowed or not scope.get('workflow_dir'):
        raise ValueError('approved wms_scope with workflow_dir is required')
    if batch:
        # A batch workflow: the workflow manager generates each jobscript at run time, so the
        # capability bounds the job count, the rules the adoption declares and the site profile;
        # every submission must be a distinct (rule, outputs) job, and its frozen bytes are journalled.
        if type(scope.get('max_jobs')) is not int or scope['max_jobs'] != count:
            raise ValueError('a batch site step declares max_jobs equal to its approved job count')
        rules = scope.get('rules')
        if (type(rules) is not list or not rules or any(type(rule) is not str or not rule for rule in rules)
                or len(set(rules)) != len(rules)):
            raise ValueError('a batch site step declares the distinct rules its adopted workflow names')
        if type(scope.get('profile_sha256')) is not str or len(scope['profile_sha256']) != 64:
            raise ValueError('a batch site step pins its site profile')
        pinned = {'batch': count}
        scripts = {'batch': count}
    elif multi:
        if type(scope.get('max_jobs')) is not int or scope['max_jobs'] != len(pins):
            raise ValueError('a multi-submission site step declares max_jobs equal to its pinned jobscript count')
        scope['max_jobs'] = len(pins)
        pinned = {'jobscripts': deepcopy(pins)}
        scripts = {'jobscripts': [{'path': str(p.absolute()), 'sha256': pin['sha256']}
                                  for p, pin in zip(paths, pins)]}
    else:
        if type(scope.get('max_jobs', 1)) is not int or scope.get('max_jobs', 1) != 1:
            raise ValueError('a parent site step authorizes one scheduler submission')
        scope['max_jobs'] = 1
        scope['jobscript_sha256'] = pin['sha256']
        pinned = {'jobscript': deepcopy(pin)}
        scripts = {'jobscript': {'path': str(path.absolute()), 'sha256': pin['sha256']}}
    binding = digest({'step': step, 'plan_sha256': context.get('plan_sha256'), 'ceiling': ceiling,
                      'run_id': store.run_id, 'run_dir': str(Path(context['run_dir']).absolute())})
    with _lock(store):
        previous = _rows(store, launch_id)
        if previous:
            if previous[0]['binding'] != binding:
                raise ValueError('a restart cannot change the original launch, budget or plan')
            completed = [r for r in previous if r['event'] == 'outcome']
            if completed:
                return deepcopy(completed[-1]['outcome'])
            if any(r['event'] == 'dispatch_started' for r in previous):
                return _held(launch_id, 'reconcile the original dispatch; no resubmission')
        reservations = [r for r in records(store, 'study-site') if r.get('event') == 'reserved']
        if reservations and any(r['ceiling'] != ceiling for r in reservations):
            raise ValueError('site budget is immutable across controller restarts')
        active_cost = sum(r['cost'] for r in reservations
                          if r['launch_id'] != launch_id and not _withdrawn(_rows(store, r['launch_id'])))
        exhausted = active_cost + cost > ceiling
        if not exhausted:
            if not previous:
                store.append('study-site', {'event': 'reserved', 'launch_id': launch_id, 'binding': binding,
                                            'cost': cost, 'ceiling': ceiling, **pinned,
                                            'run_dir': str(Path(context['run_dir']).absolute())})
            elif _withdrawn(previous):
                store.append('study-site', {'event': 'reactivated', 'launch_id': launch_id, 'binding': binding})
    if exhausted:
        return bounded_end(store, 'site budget exhausted')
    saved = [r for r in records(store, 'study-site-capability') if r['launch_id'] == launch_id]
    try:
        if saved:
            if saved[0]['scope'] != scope:
                raise ValueError('restart cannot change the capability scope')
            token = saved[0]['token']
        else:
            token = confine.mint_capability(store, launch_id, scope)
            # Protected controller state only; never part of worker inputs.
            store.append('study-site-capability', {'launch_id': launch_id, 'scope': scope, 'token': token})
    except Exception:
        with _lock(store):
            store.append('study-site', {'event': 'withdrawn', 'launch_id': launch_id,
                                        'binding': binding, 'reason': 'capability mint refused'})
        raise
    stop = authority.stop_state(store)
    if stop != 'running':
        with _lock(store):
            store.append('study-site', {'event': 'withdrawn', 'launch_id': launch_id,
                                        'binding': binding, 'reason': 'operator state: ' + stop})
        if stop == 'pause_requested':
            return _held(launch_id, 'operator paused before dispatch')
        return bounded_end(store, 'operator stop before dispatch')
    with _lock(store):
        # Durable uncertainty boundary: no restarted controller may submit again.
        if any(r['event'] == 'dispatch_started' for r in _rows(store, launch_id)):
            return _held(launch_id, 'reconcile the original dispatch; no resubmission')
        store.append('study-site', {'event': 'dispatch_started', 'launch_id': launch_id, 'binding': binding})
    internal = {**scripts, 'capability': scope}
    try:
        with trusted_launch(store, launch_id, token, internal):
            outcome = invoke()
    finally:
        # Source execution journals survive a child interruption. Capture their
        # actual handle before any ending or restarted dispatch can run.
        from . import remote
        errors = remote.capture({**context, 'store': store})
        store.append('study-site-capture', {'launch_id': launch_id, 'errors': errors})
    if errors:
        return _held(launch_id, 'source backend handle needs reconciliation: ' + str(errors))
    with _lock(store):
        store.append('study-site', {'event': 'outcome', 'launch_id': launch_id, 'binding': binding,
                                    'outcome': deepcopy(outcome)})
    if outcome.get('status') in ('budget_exhausted', 'stopped'):
        return bounded_end(store, outcome.get('reason') or outcome['status'])
    return outcome


def track(store, launch_id, plan, handle):
    """Retain the actual supervised backend handle; workers cannot supply one."""
    if not _rows(store, launch_id):
        raise ValueError('remote handle has no reserved controller launch')
    if (not plan.get('plan_sha256') or handle.get('plan_sha256') != plan['plan_sha256']
            or not handle.get('backend')):
        raise ValueError('remote handle differs from its supervised backend plan')
    with _lock(store):
        existing = [r for r in records(store, 'study-remote') if r['launch_id'] == launch_id]
        if existing and (existing[-1]['plan'] != plan or existing[-1]['handle'] != handle):
            raise ValueError('remote identity is immutable; reconcile its recorded handle')
        if not existing:
            store.append('study-remote', {'launch_id': launch_id, 'plan': deepcopy(plan), 'handle': deepcopy(handle)})


def _adoption_outputs(backend, plan, receipt, base):
    declared = {row['name']: row for row in plan['spec']['outputs'] if 'destination' in row}
    seen = set()
    for pin in receipt['outputs']:
        name = pin['name']
        if name not in declared or name in seen:
            raise ValueError('fetched output is not a unique declared output')
        seen.add(name)
        path = base / relative(declared[name]['destination'])
        if pin['destination'] != str(path) or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('adoption output escapes its original declared root')
        current = backend.identity(path)
        if any(current[key] != pin[key] for key in ('kind', 'sha256', 'size')):
            raise ValueError('adopted output pin changed after backend fetch')
    if any(row.get('required', True) and name not in seen for name, row in declared.items()):
        raise ValueError('a required declared output is absent from the fetch receipt')


def adopt(store, launch_id, *, base: Path):
    """Fetch only a recorded successful remote attempt; preserve verified pins.

    This is artifact custody, not scientific acceptance. Interrupted fetches
    remain unresolved rather than overwriting or repeating a remote fetch.
    """
    from ravel.workflow import execution_backend as backend
    base = Path(base)
    if (not base.is_absolute() or '..' in base.parts
            or any(p.is_symlink() for p in (base, *base.parents))):
        raise ValueError('adoption requires an ordinary absolute original root')
    base = base.resolve()
    protected = store.path().resolve()
    if base.is_relative_to(protected) or protected.is_relative_to(base):
        raise ValueError('adoption root overlaps the protected controller store')
    with _lock(store):
        reservations = [r for r in _rows(store, launch_id) if r.get('event') == 'reserved']
        tracked = [r for r in records(store, 'study-remote') if r['launch_id'] == launch_id]
        if not reservations or len(tracked) != 1:
            raise ValueError('adoption requires one reserved, recorded remote launch')
        original_root = reservations[0].get('run_dir')
        if original_root is None:
            raise ValueError('original launch is missing its trusted adoption root binding')
        source_bindings = [r for r in records(store, 'study-backend-binding') if r['launch_id'] == launch_id]
        if source_bindings:
            source_binding = source_bindings[-1]
            child = Path(source_binding['rundir'])
            root = Path(original_root).resolve()
            if (source_binding.get('run_dir') != str(root) or not child.is_absolute()
                    or '..' in child.parts or any(p.is_symlink() for p in (child, *child.parents))
                    or (child != root and not child.is_relative_to(root / 'children'))):
                raise ValueError('trusted source child escapes its original launch root')
            original_root = str(child)
        if base != Path(original_root).resolve():
            raise ValueError('adoption cannot widen or change the original launch root')
        plan, original = deepcopy(tracked[0]['plan']), deepcopy(tracked[0]['handle'])
        if original.get('plan_sha256') != plan.get('plan_sha256'):
            raise ValueError('recorded remote handle differs from its original plan')
        if source_bindings and (source_bindings[-1].get('plan_sha256') != plan['plan_sha256']
                or source_bindings[-1].get('handle_sha256') != digest(original)):
            raise ValueError('source binding differs from the recorded remote attempt')
        binding = digest({'plan': plan, 'handle': original})
        previous = [r for r in records(store, 'study-adoption') if r['launch_id'] == launch_id]
        if previous:
            record = previous[-1]
            if record['base'] != str(base) or record['remote_binding'] != binding:
                raise ValueError('restart cannot change the adoption root or remote identity')
            if 'receipt' not in record:
                raise ValueError('reconcile the interrupted original fetch; never refetch')
            _adoption_outputs(backend, plan, record['receipt'], base)
            return deepcopy(record['receipt'])
        # Validate every destination before the backend can create or move it.
        for row in plan['spec']['outputs']:
            if 'destination' in row:
                path = base / relative(row['destination'])
                if any(p.is_symlink() for p in (path, *path.parents)):
                    raise ValueError('adoption destination traverses a symbolic link')
        recovered = backend.recover(plan, deepcopy(original))
        handle = recovered['handle']
        if recovered['observation']['state'] != 'succeeded':
            raise ValueError('only observed succeeded remote attempts can be adopted')
        if (handle.get('plan_sha256') != plan['plan_sha256'] or handle.get('backend') != original['backend']
                or (original.get('remote') is not None and handle.get('remote') != original['remote'])
                or (original.get('tag') is not None and handle.get('tag') != original['tag'])):
            raise ValueError('recovered handle differs from the original remote plan')
        record = {'launch_id': launch_id, 'base': str(base), 'remote_binding': binding,
                  'plan_sha256': plan['plan_sha256'], 'handle': deepcopy(handle)}
        store.append('study-adoption', {**record, 'event': 'fetch_started'})
        receipt = backend.fetch(plan, handle, base)
        if (receipt.get('plan_sha256') != plan['plan_sha256']
                or receipt.get('remote') != handle.get('remote')
                or receipt.get('backend') != handle.get('backend')):
            raise ValueError('backend fetch receipt differs from its recorded attempt')
        _adoption_outputs(backend, plan, receipt, base)
        store.append('study-adoption', {**record, 'event': 'fetched', 'receipt': deepcopy(receipt)})
        return deepcopy(receipt)


def reconcile(store, *, drain=False, wait_seconds=10):
    """Recover, observe and optionally cancel every recorded remote attempt.

    Unknown or still-running handles remain unresolved. Terminal cancellation
    is a bounded ending, never a successful scientific result. The existing
    backend owns local reaping and remote terminal-state verification. Scheduler
    jobs journalled by ``record_submission`` are observed the same way and,
    on drain, cancelled; an exited job is custody of its handle, not acceptance.
    """
    from ravel.workflow import execution_backend as backend
    if not _number(wait_seconds) or wait_seconds > 30:
        raise ValueError('remote reconciliation wait is bounded to thirty seconds')
    results = []
    for row in records(store, 'study-remote'):
        plan, handle = deepcopy(row['plan']), deepcopy(row['handle'])
        previous = [r for r in records(store, 'study-reconciliation')
                    if r.get('launch_id') == row['launch_id'] and r.get('handle')]
        if previous:
            handle = deepcopy(previous[-1]['handle'])
        try:
            fetched = [r for r in records(store, 'study-adoption')
                       if r['launch_id'] == row['launch_id'] and r.get('event') == 'fetched']
            if fetched:
                adopt(store, row['launch_id'], base=Path(fetched[-1]['base']))
                handle = deepcopy(fetched[-1]['handle'])
                observation = {'state': 'succeeded', 'detail': 'source fetch receipt and local output pins reverified'}
            else:
                recovered = backend.recover(plan, handle)
                original = row['handle']
                if (recovered['handle'].get('plan_sha256') != plan['plan_sha256']
                        or recovered['handle'].get('backend') != original.get('backend')
                        or any(original.get(k) is not None and recovered['handle'].get(k) != original[k]
                               for k in ('remote', 'tag', 'attempt_dir', 'job_dir'))):
                    raise ValueError('recovered remote identity differs from the original attempt')
                handle = recovered['handle']
                observation = recovered['observation']
            if drain and observation['state'] not in TERMINAL:
                observation = backend.cancel(plan, handle, wait_seconds=wait_seconds)
            resolved = observation['state'] in TERMINAL
            result = {'launch_id': row['launch_id'], 'observation': observation, 'resolved': resolved,
                      'drain': drain, 'handle': handle}
        except Exception as exc:
            result = {'launch_id': row['launch_id'], 'resolved': False, 'drain': drain, 'handle': handle,
                      'error': str(exc), 'error_type': type(exc).__name__}
        store.append('study-reconciliation', result)
        results.append(result)
    jobs = _reconcile_jobs(store, drain=drain, wait_seconds=wait_seconds)
    return {'resolved': all(r['resolved'] for r in results) and all(j['resolved'] for j in jobs),
            'attempts': results, 'jobs': jobs}


def _reconcile_jobs(store, *, drain, wait_seconds):
    """Observe, and on drain cancel, every journalled scheduler job not yet seen terminal.

    A disappeared or unobservable job is unknown, never success. Errors are
    recorded per job and leave that job unresolved.
    """
    import time
    from ravel.workflow import wms_site
    jobs = []
    states = records(store, 'study-site-job-state')
    for row in records(store, 'study-site-job'):
        job = row.get('job')
        if row.get('scheduler') != 'htcondor' or type(job) is not str:
            continue
        if any(r.get('launch_id') == row.get('launch_id') and r.get('job') == job
               and (r.get('observation') or {}).get('state') in JOB_TERMINAL for r in states):
            continue
        result = {'launch_id': row.get('launch_id'), 'job': job, 'drain': drain, 'cancelled': False}
        try:
            observation = wms_site.observe_job(job)
            if drain and observation.get('state') != 'cancelled':
                # A drain reaps every journalled job: a queued or running one is interrupted, an
                # exited one's removal is an idempotent request the scheduler answers harmlessly.
                cancel = wms_site.cancel_job(job)
                result['cancel'] = cancel
                result['cancelled'] = cancel.get('returncode') == 0
                observation = wms_site.observe_job(job)
                deadline = time.monotonic() + wait_seconds
                while (result['cancelled'] and observation.get('state') not in JOB_TERMINAL
                       and time.monotonic() < deadline):
                    time.sleep(1)
                    observation = wms_site.observe_job(job)
            result['observation'] = observation
        except Exception as exc:  # one unobservable job never hides the others
            result.update(error=str(exc), error_type=type(exc).__name__)
        try:
            store.append('study-site-job-state', result)
        except Exception as exc:
            result.update(error=str(exc), error_type=type(exc).__name__)
        result['resolved'] = (result.get('observation') or {}).get('state') in JOB_TERMINAL and 'error' not in result
        jobs.append(result)
    return jobs


def _exit_code(observation):
    raw = str((observation or {}).get('raw') or '').split()
    return int(raw[1]) if len(raw) >= 2 and re.fullmatch(r'-?\d+', raw[1]) else None


def await_batch(store, step, context, *, poll_seconds=1.0, sleep=None):
    """Wait, bounded by the study ceiling, for every journalled batch job of the site step; then adopt.

    Runs in the controller before the reconciliation worker: the operator state is honoured
    on every poll, a job that exited nonzero or was lost holds the step, and the workflow's
    outputs are copied from the working directory into the reconciliation attempt's own
    directory and journalled as the adoption (``study-adoption``, with pins). The output names
    are the adoption's declared outputs, else the ones the operation's own dry-run inspection
    lists (read through the operate step's adopted receipt and its pins).
    This is artifact custody, not scientific acceptance.
    """
    import shutil
    import time as clock
    from ravel.controller import authority, batch_jobs
    from .contracts import adopted_json
    from .runtime import StudyHold
    sleep = clock.sleep if sleep is None else sleep
    preparation, _ = adopted_json({**context, 'store': store}, 'prepare-child:outputs/preparation.json')
    launch = preparation.get('site_launch')
    if not launch:
        return None  # no batch submission to await (a local site delivered inside its own stage)
    operate = next((row for row in context['plan']['steps'] if row['id'] == 'operate'), None)
    binding = (context['plan'].get('parameters') or {}).get('study_binding') or {}
    ceiling = binding.get('max_seconds')
    if not _number(ceiling) or ceiling <= 0:
        raise StudyHold('the batch wait needs the study ceiling the plan bound')
    launch_id = operate['id'] if operate else 'operate'
    previous = [r for r in records(store, 'study-adoption') if r.get('launch_id') == launch_id and r.get('event') == 'fetched']
    if previous:
        return deepcopy(previous[-1])  # a restart never fetches twice
    journalled = [r for r in records(store, 'study-site-job') if r.get('launch_id') == launch_id]
    expected = launch['batch']
    if len(journalled) != expected:
        raise StudyHold(f'{len(journalled)} batch job(s) were journalled; the approved plan bounds the run to {expected}')
    deadline = clock.monotonic() + ceiling
    while True:
        state = authority.stop_state(store)
        if state != 'running':
            raise StudyHold('operator state: ' + state)
        result = reconcile(store, drain=False)
        # The scheduler observer: a held job waits for its release within the operator's wait bound; a job removed
        # by someone other than this run holds the step for a governed recovery (typed, ``batch_jobs``).
        observed = batch_jobs.classify(store, [row for row in result['jobs'] if row.get('launch_id') == launch_id])
        hold = batch_jobs.hold_for(batch_jobs.decide(store, observed))
        if hold is not None:
            raise hold
        jobs = {row['job']: row for row in result['jobs']}
        for row in records(store, 'study-site-job-state'):
            if row.get('launch_id') == launch_id and (row.get('observation') or {}).get('state') in JOB_TERMINAL:
                jobs.setdefault(row['job'], row)
        if all(str(r['job']) in jobs and (jobs[str(r['job'])].get('observation') or {}).get('state') in JOB_TERMINAL
               for r in journalled):
            break
        if clock.monotonic() >= deadline:
            raise StudyHold('batch jobs are still running past the study ceiling; the run stays unresolved')
        sleep(poll_seconds)
    failed = []
    for r in journalled:
        observation = jobs[str(r['job'])].get('observation') or {}
        if observation.get('state') != 'exited' or _exit_code(observation) != 0:
            failed.append({'job': r['job'], 'observation': observation})
    # A removal observed before a restart is still the observer's typed decision, not a plain failure.
    hold = batch_jobs.hold_for(batch_jobs.decide(store, batch_jobs.classify(
        store, [{'launch_id': launch_id, **row} for row in failed])))
    if hold is not None:
        store.append('study-adoption', {'launch_id': launch_id, 'event': 'failed', 'jobs': failed, 'hold': hold.code})
        raise hold
    if failed:
        store.append('study-adoption', {'launch_id': launch_id, 'event': 'failed', 'jobs': failed})
        raise StudyHold('batch jobs ended without success: ' + json.dumps(failed)[:800])
    workflow_root = Path(preparation['workflow_root'])
    adoption = workflow_root / 'adoption' / 'adoption.json'
    if hashlib.sha256(adoption.read_bytes()).hexdigest() != (preparation.get('adoption') or {}).get('sha256'):
        raise StudyHold('the adoption record changed after preparation')
    record = json.loads(adoption.read_bytes())
    work = Path(record['workdir']).resolve()
    if record.get('outputs') is not None:
        names = list(record['outputs'])
    else:
        receipt, _ = adopted_json({**context, 'store': store}, 'operate:outputs/result.json')
        pin = ((receipt or {}).get('result') or {}).get('inspection')
        if type(pin) is not dict or not {'path', 'sha256'} <= set(pin) or not Path(str(pin['path'])).is_absolute():
            raise StudyHold('the operation receipt names no inspection of the workflow it ran')
        raw = Path(pin['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise StudyHold('the inspection document changed after the operation')
        inspection = json.loads(raw)
        names = sorted({row['output_file'] for row in inspection['summary']})
    base = Path(context['run_dir']) / 'steps' / step['id'] / 'attempts' / str(context.get('attempt', 1)) / 'delivered'
    if any(p.is_symlink() for p in (base, *base.parents)):
        raise StudyHold('the delivery directory must not traverse links')
    base.mkdir(parents=True, exist_ok=True)
    outputs, absent = [], []
    for name in names:
        source = (work / name)
        if os.path.isabs(name) or '..' in Path(name).parts or not source.resolve().is_relative_to(work) or not source.is_file():
            absent.append(name)
            continue
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        raw = target.read_bytes()
        if hashlib.sha256(source.read_bytes()).hexdigest() != hashlib.sha256(raw).hexdigest():
            raise StudyHold('output ' + name + ' changed while it was copied')
        outputs.append({'name': name, 'destination': str(target), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)})
    if absent:
        store.append('study-adoption', {'launch_id': launch_id, 'event': 'failed', 'absent_outputs': absent})
        raise StudyHold('declared workflow outputs are absent after the batch jobs exited: ' + ', '.join(absent))
    receipt = {'kind': 'batch-fetch-receipt', 'backend': 'site-batch', 'workdir': str(work), 'outputs': outputs,
               'jobs': [{'job': r['job'], 'jobscript_sha256': r.get('jobscript_sha256')} for r in journalled]}
    adoption = {'launch_id': launch_id, 'event': 'fetched', 'base': str(base), 'receipt': receipt,
                'scientific_acceptance_inferred': False}
    store.append('study-adoption', adoption)
    return adoption


def bounded_end(store, reason):
    """Notify within the operator's bound, drain, and use the sole qualified sink."""
    from ravel.controller import authority, sink
    remote = reconcile(store, drain=True)
    # Only a durable dispatch_started record can describe an escaped effect.
    # Absence of its handle is not evidence that no remote job started.
    reservations = [r for r in records(store, 'study-site') if r.get('event') == 'reserved']
    tracked = {r['launch_id'] for r in records(store, 'study-remote')}
    unresolved = [r['launch_id'] for r in reservations if r['launch_id'] not in tracked
                  and any(x.get('event') == 'dispatch_started' for x in _rows(store, r['launch_id']))
                  and not any(x.get('event') == 'outcome' for x in _rows(store, r['launch_id']))]
    summary = {'reason': reason, 'reconciliation': remote, 'unresolved_dispatches': unresolved}
    ending_id = store.append('study-site-ending', summary)
    subject = {'view': {'run_id': store.run_id, 'pins': {'site_ending': ending_id},
        'summary': reason, 'sections': [
            {'id': 'preamble', 'title': 'Qualified ending', 'lines': [reason]},
            {'id': 'question', 'title': 'Unfinished work',
             'lines': ['The bounded study has ended. Inspect unresolved obligations and remote attempts before any new authority.']}],
        'options': [{'id': 'inspect', 'text': 'Inspect the retained qualified result and unresolved work.', 'effect': False}]}}
    try:
        notification = authority.request(store, 'escalation', subject, {})
        store.append('study-site-notification', {'ending': ending_id, 'authority': notification})
    except Exception as exc:  # notification failure must never hide a bounded result
        store.append('study-site-notification', {'ending': ending_id, 'error_type': type(exc).__name__})
    return sink.bounded_end(store, reason)


__all__ = ['adopt', 'await_batch', 'bounded_end', 'dispatch', 'reconcile', 'track', 'trusted_launch', 'require_capability',
           'record_submission', 'active_launch', 'submission_environment', 'launch_options']
