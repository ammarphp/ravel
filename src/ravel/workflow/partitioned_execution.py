"""Partitioned execution: run one stage over a split input population and merge.

A declared input population (local files or remote URIs such as ``root://``) is
split into ordered, disjoint partitions. Each partition runs as its own backend
job (native processes on local cores, podman containers, or HTCondor/SLURM jobs)
and returns its outputs with a sha256 fetch receipt. A failed partition does not
affect the others; it is retried up to ``max_attempts`` times, each attempt in a
new directory with the earlier one kept. Additive outputs are then merged:

- ``binned_values``: equal axes, units and bin edges; values, ``sumw2``, overflow
  and underflow add; per-bin ``uncertainty`` adds in quadrature;
- ``cutflow``: equal region and cut order; weighted counts, raw counts and
  ``sumw2`` add;
- ``counts``: a flat object of numbers with equal keys; values add;
- ``none``: kept per partition and listed in the merge receipt (for example skims).

Partition outputs must be unnormalized weighted sums. Normalization by
cross section, luminosity and the full sum of weights belongs after the merge.
A document carrying any normalization other than ``unnormalized`` or an
absolute scale of 1 is refused.

``ravel partitions run`` and ``run()`` run only for the worker of an approved
supervised stage whose inputs pin the specification
(``execution_backend.require_approved_stage``). The approval bounds the work: the
entries of the partitions this run selects, times their remaining attempts, may
not exceed the stage's approved events, and those attempts must fit the stage's
wall-clock ceiling. An approval that bounds neither is refused (a scientific
study stage is bounded by its approved study plan instead of an event count). Every local path member
carries a ``sha256:<hex>`` checksum, verified before each submission, so member
data are bound to the approved specification; on resume each partition's
``inputs.json`` is checked against the specification.

Local backends run one partition at a time under the stage's machine lease (one
native scientific job on this machine); ``max_concurrent`` applies to remote
slots under the owner-set remote ceiling. A partition whose cancellation is not
observed to finish is marked unresolved and never resubmitted, and no further local partition starts while
it may still run (the machine lease admits one computation at a time). A changed
specification is refused on resume; only operational fields (concurrency and
attempt bound) may change between runs.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time

from . import execution_backend as eb, gate_wiring, machine_lease
from .state_io import atomic_json, read_json

SCHEMA_VERSION = 1
LEDGER = 'partition-ledger.json'
MERGE_RECEIPT = 'merge-receipt.json'
MERGE_KINDS = ('binned_values', 'columnar-partial', 'cutflow', 'counts', 'none')
_NAME = re.compile(r'^[a-z][a-z0-9-]{0,40}$')
_CHECKSUM = re.compile(r'^sha256:[0-9a-f]{64}$')
MAX_PARTITIONS = 10000
PARTITION_INPUTS_GUEST = '/ravel/partition/inputs.json'


# ---------------------------------------------------------------- specification
def validate(spec):
    eb._keys(spec, ('schema_version', 'name', 'population', 'partitioning', 'stage', 'outputs'),
             ('max_concurrent', 'max_attempts', 'description'), 'partitioned execution')
    if spec['schema_version'] != SCHEMA_VERSION:
        raise ValueError('partitioned execution schema_version 1 required')
    if not isinstance(spec['name'], str) or not _NAME.fullmatch(spec['name']):
        raise ValueError('name must be lowercase letters, digits and dashes')
    population = spec['population']
    eb._keys(population, ('members',), ('authority',), 'population')
    members = population['members']
    if not isinstance(members, list) or not members:
        raise ValueError('population needs a nonempty member list')
    seen = set()
    for member in members:
        eb._keys(member, (), ('path', 'uri', 'entries', 'size_bytes', 'checksum', 'id'), 'population member')
        location = member.get('path') or member.get('uri')
        if bool(member.get('path')) == bool(member.get('uri')):
            raise ValueError('each population member needs exactly one of path or uri')
        if location in seen:
            raise ValueError(f'population member {location} appears twice')
        seen.add(location)
        if 'entries' in member:
            eb._integer(member['entries'], 0, 10 ** 15, 'member entries')
        if member.get('path') and not (isinstance(member.get('checksum'), str)
                                       and _CHECKSUM.fullmatch(member['checksum'])):
            raise ValueError(f"local population member {member['path']} needs a checksum sha256:<64 hex>")
    partitioning = spec['partitioning']
    eb._keys(partitioning, (), ('members_per_partition', 'partitions'), 'partitioning')
    if len(partitioning) != 1:
        raise ValueError('partitioning takes exactly one of members_per_partition or partitions')
    if 'members_per_partition' in partitioning:
        eb._integer(partitioning['members_per_partition'], 1, 10 ** 6, 'members_per_partition')
    else:
        eb._integer(partitioning['partitions'], 1, MAX_PARTITIONS, 'partitions')
    stage = spec['stage']
    eb._keys(stage, ('backend', 'argv', 'resources'), ('inputs', 'readonly_trees', 'env', 'image', 'source',
                                                       'site', 'workdir', 'quantities'), 'stage template')
    if not any('{partition_inputs}' in a for a in stage['argv']):
        raise ValueError('stage argv must pass {partition_inputs} to the payload')
    outputs = spec['outputs']
    if not isinstance(outputs, list) or not outputs:
        raise ValueError('outputs must be a nonempty list')
    for row in outputs:
        eb._keys(row, ('name', 'merge'), ('kind',), 'partition output')
        eb._relative(row['name'], 'output name')
        if row['merge'] not in MERGE_KINDS:
            raise ValueError(f'merge must be one of {MERGE_KINDS}')
    eb._integer(spec.get('max_concurrent', 1), 1, 1024, 'max_concurrent')
    eb._integer(spec.get('max_attempts', 1), 1, 5, 'max_attempts')
    return deepcopy(spec)


def specification_digest(spec):
    return eb.digest({k: spec[k] for k in ('schema_version', 'name', 'population', 'partitioning', 'stage', 'outputs')})


def plan_partitions(spec):
    members = spec['population']['members']
    partitioning = spec['partitioning']
    if 'members_per_partition' in partitioning:
        size = partitioning['members_per_partition']
    else:
        size = math.ceil(len(members) / partitioning['partitions'])
    groups = [members[i:i + size] for i in range(0, len(members), size)]
    if len(groups) > MAX_PARTITIONS:
        raise ValueError(f'more than {MAX_PARTITIONS} partitions')
    parts = []
    for index, group in enumerate(groups):
        parts.append({'id': f'p{index:05d}', 'members': deepcopy(group), 'sha256': eb.digest(group),
                      'entries': sum(m.get('entries', 0) for m in group),
                      'size_bytes': sum(m.get('size_bytes', 0) for m in group)})
    return parts


def _stage_spec(spec, part, work):
    template = spec['stage']
    pdir = work / 'partitions' / part['id']
    inputs_file = pdir / 'inputs.json'
    guest = template['backend'] == 'oci-local'
    token = PARTITION_INPUTS_GUEST if guest else str(inputs_file)
    argv = [a.replace('{partition_inputs}', token).replace('{partition_id}', part['id']) for a in template['argv']]
    inputs = deepcopy(template.get('inputs', []))
    inputs.append({'path': str(inputs_file), **({'mount': PARTITION_INPUTS_GUEST} if guest else {})})
    stage = {'schema_version': 1, 'backend': template['backend'], 'stage': f"{spec['name']}-{part['id']}",
             'argv': argv, 'inputs': inputs, 'resources': deepcopy(template['resources']),
             'outputs': [{'name': o['name'], 'destination': o['name'],
                          **({'kind': o['kind']} if 'kind' in o else {})} for o in spec['outputs']]}
    for key in ('readonly_trees', 'env', 'image', 'source', 'site', 'workdir', 'quantities'):
        if key in template:
            stage[key] = deepcopy(template[key])
    return stage


# ---------------------------------------------------------------- ledger
def _ledger(work):
    path = Path(work) / LEDGER
    return read_json(path) if path.is_file() else None


def _save(work, ledger):
    ledger['updated_utc'] = eb.utc_now()
    atomic_json(Path(work) / LEDGER, ledger)


def _check_work(spec, work):
    """Read-only: an existing work directory must belong to this specification.

    Runs before recovery, so nothing is fetched or saved into a directory created
    for another specification or whose partition manifests were edited.
    """
    work = Path(work)
    ledger = _ledger(work)
    if ledger is None:
        return
    if ledger.get('specification_sha256') != specification_digest(spec):
        raise ValueError('the partitioned specification changed since this work directory was created; '
                         'use a new work directory')
    for p in plan_partitions(spec):
        path = work / 'partitions' / p['id'] / 'inputs.json'
        if not path.is_file() or read_json(path) != {'partition': p['id'], 'members': p['members']}:
            raise ValueError(f"partition {p['id']} inputs.json differs from the specification; use a new work directory")


def _open(spec, work):
    work = Path(work)
    ledger = _ledger(work)
    digest = specification_digest(spec)
    parts = plan_partitions(spec)
    if ledger is None:
        work.mkdir(parents=True, exist_ok=True)
        ledger = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-partition-ledger', 'name': spec['name'],
                  'specification_sha256': digest, 'specification': spec, 'created_utc': eb.utc_now(),
                  'partitions': {p['id']: {'members_sha256': p['sha256'], 'entries': p['entries'],
                                           'size_bytes': p['size_bytes'], 'status': 'pending', 'attempts': []}
                                 for p in parts}}
        for p in parts:
            pdir = work / 'partitions' / p['id']
            pdir.mkdir(parents=True, exist_ok=True)
            atomic_json(pdir / 'inputs.json', {'partition': p['id'], 'members': p['members']})
        _save(work, ledger)
    else:
        _check_work(spec, work)
        ledger['specification'] = spec
    return ledger, parts


# ---------------------------------------------------------------- run
class _Interrupted(Exception):
    pass


def _verify_members(part):
    for member in part['members']:
        if member.get('path') and 'sha256:' + eb.file_sha256(member['path']) != member['checksum']:
            raise ValueError(f"population member {member['path']} differs from its approved checksum")


def _within_approval(spec, parts, authority, *, attempts=1, consumed=0, adopted=()):
    """The selected work fits the approved stage: entries times attempts, and the wall-clock ceiling.

    ``parts`` are the partitions this run may start; ``attempts`` is their remaining
    attempt count (an int, or a dict by partition id). ``consumed`` is the entries of
    attempts this work directory already spent, which the approved events also cover.
    ``adopted`` holds the seconds left to each remote job this run adopts and observes.
    """
    def remaining(part):
        return attempts.get(part['id'], 0) if isinstance(attempts, dict) else attempts
    events, ceiling = authority.get('events'), authority.get('max_seconds')
    science = authority.get('required_plan') == 'science'
    if not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool) or ceiling <= 0:
        raise ValueError('the approved stage does not bound this work: it records no wall-clock ceiling')
    if type(events) is int and events > 0:
        if any('entries' not in m for part in parts for m in part['members']):
            raise ValueError('declare entries for every population member so the volume can be held to the approved events')
        total = consumed + sum(remaining(part) * sum(m['entries'] for m in part['members']) for part in parts)
        if total > events:
            raise ValueError(f'the selected partitions and attempts declare {total} entries, with the attempts '
                             f'already spent; '
                             f'the approved stage covers {events} events')
    elif not science:
        raise ValueError('the approved stage does not bound this work: it records no approved event count')
    local = eb.get(spec['stage']['backend']).is_local(spec['stage'])
    lanes = 1 if local else spec.get('max_concurrent', 1)
    wall = spec['stage']['resources']['wall_seconds']
    need = math.ceil(sum(remaining(part) for part in parts) / lanes) * wall + max(adopted, default=0)
    if need > ceiling:
        raise ValueError(f'{len(parts)} partitions of up to {wall} s need {need} s; '
                         f'the approved stage ceiling is {ceiling:g} s')


NEVER_STARTED = ('never-dispatched', 'never-started')


def _used(row):
    """Attempts that count against max_attempts: an attempt that provably started nothing does not."""
    return sum(1 for attempt in row['attempts'] if attempt.get('state') != 'never-started')


def _elapsed(entry, handle, plan):
    """Seconds since the attempt started; its full wall allowance when no start was recorded."""
    from datetime import datetime
    for stamp in (entry.get('started_utc'), handle.get('submitted_utc'), handle.get('created_utc')):
        try:
            return max(0.0, (datetime.now(datetime.fromisoformat(stamp).tzinfo)
                             - datetime.fromisoformat(stamp)).total_seconds())
        except (TypeError, ValueError):
            continue
    return float(plan['spec']['resources']['wall_seconds'])


def _reconcile(work, max_attempts):
    """Resolve partitions an earlier run left running or unresolved, from their backend handles.

    A job that ended is adopted (a success is fetched; a failure or cancellation is
    settled like any other attempt). A launch that provably started nothing does not
    count as an attempt. A job that may still run stays unresolved; a remote one is
    returned for this run to keep observing. Nothing is resubmitted over it.
    """
    ledger = _ledger(work)
    if ledger is None:
        return []
    adopt = []
    for pid, row in ledger['partitions'].items():
        if row['status'] not in ('running', 'unresolved') or not row['attempts']:
            continue
        entry = row['attempts'][-1]
        attempt = Path(entry['attempt_dir'])
        note = {'reconciled_utc': eb.utc_now()}
        if not (attempt / eb.HANDLE_NAME).is_file():
            entry.update(state='never-started', detail='no backend handle was written; nothing was dispatched', **note)
            row['status'] = 'pending' if _used(row) < max_attempts else 'failed'
            continue
        plan = eb.load_plan(attempt / 'plan.json', verify_inputs=False)
        handle = eb.read_handle(attempt)
        if handle.get('remote') is None and handle.get('resolution') is None:
            handle = eb.recover(plan, handle)['handle']
        resolution = handle.get('resolution')
        if resolution == 'operator-cleared':
            # An operator resolved it, with or without a recorded identity: settled, never observed again.
            entry.update(state='failed', detail='an operator cleared this job; it may have run', **note)
            row['status'] = 'pending' if _used(row) < max_attempts else 'failed'
            continue
        if handle.get('remote') is None:
            if resolution in NEVER_STARTED:
                entry.update(state='never-started', detail=f'recovery: {resolution}', **note)
                row['status'] = 'pending' if _used(row) < max_attempts else 'failed'
            else:
                entry.update(state='unresolved', detail='a dispatch left no identity; it may still run', **note)
                row['status'] = 'unresolved'
            continue
        if handle.get('state') == 'fetched' and (attempt / eb.RECEIPT_NAME).is_file():
            entry.update(state='succeeded', receipt=str(attempt / eb.RECEIPT_NAME),
                         receipt_sha256=eb.file_sha256(attempt / eb.RECEIPT_NAME), **note)
            row['status'] = 'succeeded'
            continue
        observation = eb.observe(plan, handle)
        if observation['state'] not in eb.TERMINAL:
            entry.update(state='unresolved', detail=f"reconciliation observed {observation['state']}", **note)
            row['status'] = 'unresolved'
            if not eb.is_local(plan):
                adopt.append((pid, plan, handle, _elapsed(entry, handle, plan)))
            continue
        entry.update(state=observation['state'], exit_code=observation.get('exit_code'), **note)
        row['status'] = 'pending' if _used(row) < max_attempts else 'failed'
        if observation['state'] == 'succeeded':
            try:
                eb.fetch(plan, handle, work / 'partitions' / pid)
                entry.update(receipt=str(attempt / eb.RECEIPT_NAME),
                             receipt_sha256=eb.file_sha256(attempt / eb.RECEIPT_NAME))
                row['status'] = 'succeeded'
            except ValueError as exc:
                entry.update(state='failed', detail=str(exc))
    _save(work, ledger)
    return adopt


def _selection(spec, work, only):
    """Partitions this run may start, their remaining attempts, and the entries already spent."""
    ledger = _ledger(Path(work).resolve()) or {'partitions': {}}
    max_attempts = spec.get('max_attempts', 1)
    selected, attempts, consumed = [], {}, 0
    for part in plan_partitions(spec):
        row = ledger['partitions'].get(part['id'], {'status': 'pending', 'attempts': []})
        consumed += _used(row) * sum(m.get('entries') or 0 for m in part['members'])
        left = max_attempts - _used(row)
        if row['status'] in ('succeeded', 'unresolved') or left <= 0 or (only is not None and part['id'] not in only):
            continue
        selected.append(part)
        attempts[part['id']] = left
    return selected, attempts, consumed


def run(spec, work, *, poll=5.0, only=None, cancel_wait=8.0, authority=None):
    """Run every unfinished partition; never stops early because one failed.

    Runs only for the worker of an approved supervised stage: ``authority`` names
    the run and stage and ``spec`` names the stage's pinned specification file; both
    are verified here (execution_backend.require_approved_stage) and the supplied
    specification must be that file's, before anything is written. The verified
    authority joins the ledger. Attempts already spent in the work directory and
    adopted remote jobs count against the approval.
    """
    spec = validate(spec)
    if not isinstance(authority, dict) or not authority.get('rundir') or not authority.get('stage'):
        raise ValueError('partitions run only inside an approved supervised stage; pass its authority')
    if not authority.get('spec'):
        raise ValueError('pass the pinned specification file of the approved stage as authority["spec"]; '
                         'nothing was started')
    pinned = Path(authority['spec']).resolve()
    authority = eb.require_approved_stage(authority['rundir'], authority['stage'], pinned=[pinned])
    if specification_digest(validate(read_json(pinned))) != specification_digest(spec):
        raise ValueError('the supplied specification differs from the pinned specification of the approved stage; '
                         'nothing was started')
    max_attempts = spec.get('max_attempts', 1)
    _check_work(spec, Path(work).resolve())
    adopted = _reconcile(Path(work).resolve(), max_attempts)
    selected, attempts, consumed = _selection(spec, work, only)
    wall = spec['stage']['resources']['wall_seconds']
    _within_approval(spec, selected, authority, attempts=attempts, consumed=consumed,
                     adopted=[max(0.0, wall - elapsed) for *_, elapsed in adopted])
    work = Path(work).resolve()
    ledger, parts = _open(spec, work)
    ledger['authority'] = authority
    _save(work, ledger)
    queue = [p for p in parts if ledger['partitions'][p['id']]['status'] not in ('succeeded', 'unresolved')
             and _used(ledger['partitions'][p['id']]) < max_attempts
             and (only is None or p['id'] in only)]
    if any(row['status'] == 'unresolved' for row in ledger['partitions'].values()) and eb.is_local(
            {'spec': spec['stage']}):
        # A local job that may still run holds the machine: nothing else local starts in this run.
        queue = []
    for p in parts:
        row = ledger['partitions'][p['id']]
        if row['status'] == 'failed' and _used(row) < max_attempts:
            row['status'] = 'pending'
    active = {}
    stop = {'signal': None}

    def interrupted(signum, frame):
        stop['signal'] = signum
        raise _Interrupted()
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)} \
        if _main_thread() else {}
    try:
        with ExitStack() as stack:
            concurrency = _capacity(stack, spec, work, authority)
            by_id = {p['id']: p for p in parts}
            for pid, plan, handle, elapsed in adopted:
                # A remote job from an earlier run that may still run: observe it here, never resubmit it.
                # It keeps the deadline it started with.
                ledger['partitions'][pid]['status'] = 'running'
                active[pid] = (by_id[pid], plan, handle, time.monotonic() - elapsed)
            while queue or active:
                while queue and len(active) < concurrency:
                    part = queue.pop(0)
                    row = ledger['partitions'][part['id']]
                    _verify_members(part)
                    plan = eb.prepare(_stage_spec(spec, part, work), base=work)
                    attempt = work / 'partitions' / part['id'] / f"attempt-{len(row['attempts']) + 1}"
                    entry = {'attempt_dir': str(attempt), 'plan_sha256': plan['plan_sha256'], 'state': 'submitted',
                             'started_utc': eb.utc_now()}
                    row['attempts'].append(entry)
                    row['status'] = 'running'
                    _save(work, ledger)
                    try:
                        handle = eb.submit(plan, attempt, authority=(authority['rundir'], authority['stage']))
                    except gate_wiring.SteeringRefused as exc:
                        # Live steering (a pause, a veto or a hold) refused this submission before
                        # anything was written: the partition stays pending and keeps its attempts,
                        # no further partition is submitted, and the running ones drain.
                        row['attempts'].pop()
                        row['status'] = 'pending'
                        ledger.setdefault('blocked', []).append({'utc': eb.utc_now(), 'detail': eb.redact(str(exc)),
                                                                 'steering': True})
                        queue.clear()
                        _save(work, ledger)
                        continue
                    except (machine_lease.LeaseBusy, ValueError, OSError) as exc:
                        if _settle_partial_submit(plan, attempt, entry, row, cancel_wait):
                            # The submission wrote an identity before it failed and the job may still
                            # run: it stays fenced and unresolved, never retried over.
                            if eb.is_local(plan) or isinstance(exc, machine_lease.LeaseBusy):
                                queue.clear()
                            _save(work, ledger)
                            continue
                        if not isinstance(exc, machine_lease.LeaseBusy) or (attempt / eb.HANDLE_NAME).is_file():
                            entry.update(state='failed', detail=eb.redact(str(exc)), finished_utc=eb.utc_now())
                            _settle(ledger, part, row, queue, max_attempts)
                            _save(work, ledger)
                            continue
                        # An earlier job of this lease may still run: nothing started; stop dispatching.
                        row['attempts'].pop()
                        row['status'] = 'pending'
                        ledger.setdefault('blocked', []).append({'utc': eb.utc_now(), 'detail': eb.redact(str(exc))})
                        queue.clear()
                        _save(work, ledger)
                        continue
                    entry['tag'] = handle['tag']
                    active[part['id']] = (part, plan, handle, time.monotonic())
                    _save(work, ledger)
                for pid in list(active):
                    part, plan, handle, started = active[pid]
                    row = ledger['partitions'][pid]
                    entry = row['attempts'][-1]
                    observation = eb.observe(plan, handle)
                    if observation['state'] not in eb.TERMINAL:
                        if observation.get('payload_exited') or time.monotonic() - started > plan['spec']['resources']['wall_seconds']:
                            reason = observation.get('detail') if observation.get('payload_exited') else 'wall-clock ceiling reached'
                            observation = eb.cancel(plan, handle, wait_seconds=cancel_wait)
                            if observation['state'] not in eb.TERMINAL:
                                # Never retry over a job that may still run: it stays fenced and unresolved.
                                del active[pid]
                                entry.update(state='unresolved', finished_utc=eb.utc_now(),
                                             detail=f"{reason}; cancellation observed {observation['state']}")
                                row['status'] = 'unresolved'
                                if eb.is_local(plan):
                                    # It may still run and holds the machine: no further local partition starts.
                                    queue.clear()
                                _save(work, ledger)
                                continue
                            observation = {**observation, 'state': 'failed', 'detail': reason}
                        else:
                            continue
                    del active[pid]
                    entry.update(state=observation['state'], exit_code=observation.get('exit_code'),
                                 finished_utc=eb.utc_now())
                    if observation.get('detail'):
                        entry['detail'] = observation['detail']
                    if observation['state'] == 'succeeded':
                        try:
                            eb.fetch(plan, handle, work / 'partitions' / pid)
                            entry['receipt'] = str(Path(handle['attempt_dir']) / eb.RECEIPT_NAME)
                            entry['receipt_sha256'] = eb.file_sha256(entry['receipt'])
                            row['status'] = 'succeeded'
                        except ValueError as exc:
                            entry.update(state='failed', detail=str(exc))
                    if row['status'] != 'succeeded':
                        _settle(ledger, part, row, queue, max_attempts)
                    _save(work, ledger)
                if active:
                    time.sleep(poll)
    except _Interrupted:
        _cancel_active(active, ledger, cancel_wait, 'interrupted')
        _save(work, ledger)
        raise KeyboardInterrupt('partitioned execution interrupted; active partitions were cancelled')
    except BaseException as exc:
        _cancel_active(active, ledger, cancel_wait, f'cancelled after an error: {eb.redact(str(exc))}')
        _save(work, ledger)
        raise
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return summary(work)


def _settle_partial_submit(plan, attempt, entry, row, cancel_wait):
    """After a failed submission: True when it left a job that may still run (now unresolved).

    A handle with a recorded identity is cancelled; one without an identity is
    recovered. Only a job observed terminal, or a launch proven to start nothing,
    leaves the attempt to the ordinary failure path.
    """
    if not (Path(attempt) / eb.HANDLE_NAME).is_file():
        return False
    try:
        handle = eb.read_handle(attempt)
        if handle.get('remote') is None:
            handle = eb.recover(plan, handle)['handle']
            if handle.get('remote') is None and handle.get('resolution') in NEVER_STARTED:
                return False
            observation = {'state': 'unknown', 'detail': 'the failed submission left no identity'}
        if handle.get('remote') is not None:
            observation = eb.cancel(plan, handle, wait_seconds=cancel_wait)
    except Exception as exc:
        observation = {'state': 'unknown', 'detail': eb.redact(str(exc))}
    if observation['state'] in eb.TERMINAL:
        return False
    entry.update(state='unresolved', finished_utc=eb.utc_now(),
                 detail=f"the submission failed after writing its handle; cancellation observed {observation['state']}")
    row['status'] = 'unresolved'
    return True


def _cancel_active(active, ledger, cancel_wait, detail):
    for pid, (part, plan, handle, _) in active.items():
        try:
            observation = eb.cancel(plan, handle, wait_seconds=cancel_wait)
        except Exception as exc:
            observation = {'state': 'unknown', 'detail': eb.redact(str(exc))}
        ledger['partitions'][pid]['attempts'][-1].update(state=observation['state'], detail=detail)
        ledger['partitions'][pid]['status'] = ('interrupted' if observation['state'] in eb.TERMINAL else 'unresolved')
    active.clear()


def _main_thread():
    import threading
    return threading.current_thread() is threading.main_thread()


def _capacity(stack, spec, work, authority):
    concurrency = spec.get('max_concurrent', 1)
    stage = spec['stage']
    holder = f'partitioned:{work}'
    local = eb.get(stage['backend']).is_local(stage)
    if local:
        # One native scientific job at a time: local partitions run one after another. A driver that
        # is itself the payload of the stage's backend job nests in that job; otherwise it is the
        # stage worker's handoff.
        from .execution import BACKEND_JOB_ENV
        stack.enter_context(eb.machine_lease(holder, rundir=authority['rundir'], node_id=authority['stage'],
                                             nested=bool(os.environ.get(BACKEND_JOB_ENV))))
        return 1
    slots = 0
    for _ in range(concurrency):
        try:
            stack.enter_context(eb.remote_slot(holder))
            slots += 1
        except ValueError:
            break
    if slots == 0:
        raise ValueError('no remote job slot is free under the owner-set remote ceiling')
    return slots


def _settle(ledger, part, row, queue, max_attempts):
    if _used(row) < max_attempts:
        row['status'] = 'pending'
        queue.append(part)
    else:
        row['status'] = 'failed'


def summary(work):
    ledger = _ledger(work)
    if ledger is None:
        raise ValueError('no partition ledger in this work directory')
    rows = ledger['partitions']
    failed = sorted(pid for pid, r in rows.items() if r['status'] == 'failed')
    succeeded = sum(r['status'] == 'succeeded' for r in rows.values())
    return {'name': ledger['name'], 'partitions': len(rows), 'succeeded': succeeded, 'failed': failed,
            'unresolved': sorted(pid for pid, r in rows.items() if r['status'] == 'unresolved'),
            'pending': sorted(pid for pid, r in rows.items() if r['status'] in ('pending', 'running', 'interrupted')),
            'status': 'complete' if succeeded == len(rows) else 'incomplete'}


# ---------------------------------------------------------------- merge
def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value


def _fsum(values):
    if all(type(v) is int for v in values):
        return sum(values)
    return math.fsum(values)


def _check_normalization(document):
    norm = document.get('normalization')
    if norm is None:
        return
    if not (isinstance(norm, dict) and (norm.get('kind') == 'unnormalized' or
                                         (norm.get('kind') == 'absolute' and norm.get('scale') == 1.0))):
        raise ValueError('partition output carries a normalization; merge unnormalized sums and normalize afterwards')


def merge_documents(kind, documents):
    if not documents:
        raise ValueError('nothing to merge')
    if kind == 'columnar-partial':
        from ravel.physics.columnar.engine import merge
        return merge(documents)
    if kind == 'counts':
        keys = set(documents[0])
        for d in documents:
            if set(d) != keys:
                raise ValueError('count documents have different keys')
        return {k: _fsum([_number(d[k], k) for d in documents]) for k in documents[0]}
    if kind == 'binned_values':
        first = documents[0]
        for d in documents:
            _check_normalization(d)
            if d.get('kind') != 'binned_values':
                raise ValueError('binned_values merge needs binned_values documents')
            for key in set(first) | set(d):
                if key in ('bins', 'overflow', 'underflow', 'sumw2', 'covariance'):
                    continue
                if d.get(key) != first.get(key):
                    raise ValueError(f'partition documents differ in {key}')
            if [(b['low'], b['high']) for b in d['bins']] != [(b['low'], b['high']) for b in first['bins']]:
                raise ValueError('partition documents have different bin edges')
            if [set(b) for b in d['bins']] != [set(b) for b in first['bins']]:
                raise ValueError('partition documents carry different per-bin fields')
            if ('overflow' in d) != ('overflow' in first) or ('underflow' in d) != ('underflow' in first):
                raise ValueError('partition documents differ in overflow/underflow fields')
        merged = deepcopy(first)
        for i, b in enumerate(merged['bins']):
            b['value'] = _fsum([_number(d['bins'][i]['value'], 'value') for d in documents])
            if 'sumw2' in b:
                b['sumw2'] = _fsum([_number(d['bins'][i]['sumw2'], 'sumw2') for d in documents])
            if 'uncertainty' in b:
                b['uncertainty'] = math.sqrt(math.fsum(_number(d['bins'][i]['uncertainty'], 'uncertainty') ** 2 for d in documents))
        for key in ('overflow', 'underflow'):
            if key in merged:
                merged[key] = _fsum([_number(d[key], key) for d in documents])
        if 'sumw2' in first:
            from ravel.physics.binned_values import validate
            for d in documents:
                validate(d)
            merged['sumw2'] = [math.fsum(d['sumw2'][i] for d in documents) for i in range(len(first['bins']))]
        if 'covariance' in first:
            from ravel.physics.binned_values import validate
            for d in documents:
                validate(d)
            n = len(first['bins'])
            merged['covariance'] = [[math.fsum(d['covariance'][i][j] for d in documents) for j in range(n)] for i in range(n)]
        return merged
    if kind == 'cutflow':
        first = documents[0]
        shape = [(r['name'], [c['name'] for c in r['cuts']]) for r in first['regions']]
        for d in documents:
            _check_normalization(d)
            if [(r['name'], [c['name'] for c in r['cuts']]) for r in d['regions']] != shape:
                raise ValueError('partition cutflows have different region or cut order')
            for key in set(first) | set(d):
                if key != 'regions' and d.get(key) != first.get(key):
                    raise ValueError(f'partition cutflows differ in {key}')
        merged = deepcopy(first)
        for ri, region in enumerate(merged['regions']):
            for ci, cut in enumerate(region['cuts']):
                for field in ('weighted', 'raw', 'sumw2'):
                    if field in cut:
                        cut[field] = _fsum([_number(d['regions'][ri]['cuts'][ci][field], field) for d in documents])
        return merged
    raise ValueError(f'unknown merge kind {kind}')


def merge(work):
    work = Path(work).resolve()
    ledger = _ledger(work)
    if ledger is None:
        raise ValueError('no partition ledger in this work directory')
    status = summary(work)
    if status['status'] != 'complete':
        raise ValueError('cannot merge: partitions not succeeded: ' + ', '.join(status['failed'] + status['pending']))
    spec = ledger['specification']
    out = work / 'merged'
    if out.exists() or (work / MERGE_RECEIPT).exists():
        raise ValueError('merged outputs already exist in this work directory')
    partitions, documents = [], {o['name']: [] for o in spec['outputs']}
    for pid in sorted(ledger['partitions']):
        row = ledger['partitions'][pid]
        entry = row['attempts'][-1]
        receipt_path = Path(entry['receipt'])
        if eb.file_sha256(receipt_path) != entry['receipt_sha256']:
            raise ValueError(f'fetch receipt of {pid} changed')
        receipt = read_json(receipt_path)
        record = {'partition': pid, 'members_sha256': row['members_sha256'], 'receipt': str(receipt_path),
                  'receipt_sha256': entry['receipt_sha256'], 'outputs': {}}
        for output in receipt['outputs']:
            path = Path(output['destination'])
            current = eb.identity(path)
            if current['sha256'] != output['sha256']:
                raise ValueError(f"partition output {pid}/{output['name']} differs from its receipt")
            record['outputs'][output['name']] = output['sha256']
            documents[output['name']].append(path)
        partitions.append(record)
    out.mkdir()
    merged_rows = []
    for o in spec['outputs']:
        if o['merge'] == 'none':
            merged_rows.append({'name': o['name'], 'merge': 'none', 'members': [str(p) for p in documents[o['name']]]})
            continue
        value = merge_documents(o['merge'], [read_json(p) for p in documents[o['name']]])
        target = out / o['name']
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(target, value)
        merged_rows.append({'name': o['name'], 'merge': o['merge'], 'path': str(target), 'sha256': eb.file_sha256(target)})
    receipt = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-partition-merge', 'name': ledger['name'],
               'specification_sha256': ledger['specification_sha256'], 'partitions': partitions,
               'merged': merged_rows, 'merged_utc': eb.utc_now()}
    atomic_json(work / MERGE_RECEIPT, receipt)
    return receipt


# ---------------------------------------------------------------- cost
def forecast(work):
    """Wall and core-hour forecast from measured partitions (a pilot)."""
    ledger = _ledger(work)
    if ledger is None:
        raise ValueError('no partition ledger in this work directory')
    from datetime import datetime
    spec = ledger['specification']
    measured, remaining = [], []
    for pid, row in sorted(ledger['partitions'].items()):
        done = [a for a in row['attempts'] if a['state'] == 'succeeded' and 'finished_utc' in a]
        if row['status'] == 'succeeded' and done:
            a = done[-1]
            seconds = (datetime.fromisoformat(a['finished_utc']) - datetime.fromisoformat(a['started_utc'])).total_seconds()
            measured.append((pid, seconds, row['entries'], row['size_bytes']))
        else:
            remaining.append(row)
    cpus = spec['stage']['resources']['cpus']
    concurrency = spec.get('max_concurrent', 1)
    if not measured:
        return {'calibration': 'uncalibrated', 'pilot_partitions': [], 'remaining_partitions': len(remaining),
                'note': 'run one partition first (run --only p00000) to measure a pilot'}
    total_seconds = sum(m[1] for m in measured)
    measured_entries = sum(m[2] for m in measured)
    measured_bytes = sum(m[3] for m in measured)
    if measured_entries:
        rate, basis = total_seconds / measured_entries, 'entries'
        need = sum(r['entries'] for r in remaining) * rate
    elif measured_bytes:
        rate, basis = total_seconds / measured_bytes, 'bytes'
        need = sum(r['size_bytes'] for r in remaining) * rate
    else:
        rate, basis = total_seconds / len(measured), 'partitions'
        need = len(remaining) * rate
    return {'calibration': 'measured pilot', 'pilot_partitions': [m[0] for m in measured], 'basis': basis,
            'seconds_per_unit': rate, 'remaining_partitions': len(remaining),
            'estimated_core_hours': need * cpus / 3600.0,
            'estimated_wall_hours': need / max(1, concurrency) / 3600.0,
            'max_concurrent': concurrency, 'cpus_per_partition': cpus}


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel partitions', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan', help='show the partitions of a specification; runs nothing')
    p.add_argument('--spec', type=Path, required=True)
    r = sub.add_parser('run', help='run unfinished partitions through the declared backend')
    r.add_argument('--spec', type=Path, required=True)
    r.add_argument('--workdir', type=Path, required=True)
    r.add_argument('--poll', type=float, default=5.0)
    r.add_argument('--only', action='append', help='partition id to run (repeatable), for a pilot')
    r.add_argument('--merge', action='store_true', help='merge when every partition succeeded')
    r.add_argument('--rundir', type=Path, help='run whose approved supervised stage runs these partitions (required)')
    r.add_argument('--stage', help='the supervised stage running these partitions (required)')
    for name, text in (('status', 'summarize the partition ledger'), ('merge', 'merge additive outputs'),
                       ('forecast', 'forecast wall time and core hours from measured partitions')):
        c = sub.add_parser(name, help=text)
        c.add_argument('--workdir', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'plan':
            spec = validate(read_json(args.spec))
            parts = plan_partitions(spec)
            print(json.dumps({'name': spec['name'], 'partitions': len(parts), 'specification_sha256': specification_digest(spec),
                              'rows': [{k: p[k] for k in ('id', 'sha256', 'entries', 'size_bytes')} | {'members': len(p['members'])}
                                       for p in parts]}, indent=2))
            return 0
        if args.command == 'run':
            eb.require_approved_stage(args.rundir, args.stage, pinned=[args.spec])
            spec = read_json(args.spec)
            result = run(spec, args.workdir, poll=args.poll, only=args.only,
                         authority={'rundir': args.rundir, 'stage': args.stage, 'spec': args.spec})
            if args.merge and result['status'] == 'complete':
                merge(args.workdir)
            print(json.dumps(result, indent=2))
            return 0 if result['status'] == 'complete' or args.only else 1
        if args.command == 'status':
            print(json.dumps(summary(args.workdir), indent=2))
            return 0
        if args.command == 'merge':
            print(json.dumps(merge(args.workdir), indent=2))
            return 0
        if args.command == 'forecast':
            print(json.dumps(forecast(args.workdir), indent=2))
            return 0
    except (OSError, ValueError) as exc:
        print(f'ravel partitions: {exc}', file=sys.stderr)
        return 2
    return 2


if __name__ == '__main__':
    sys.exit(main())
