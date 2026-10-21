"""A controller run's batch jobs: the scheduler observer, its typed recovery decision and the stop's own drain.

A run's batch jobs are exactly the scheduler jobs its controller journalled (``study-site-job``: each admitted
submission's handle) and the remote driver attempts it tracks (``study-remote``). Nothing else is observed or
cancelled: the scheduler is addressed only by the journalled job ids, never by name, owner or tag.

Observer (``observe`` then ``decide``). Every journalled job not yet seen terminal is observed once per call:

- **held** (the scheduler holds it): the operator is told through the run's ``jobs_held`` condition (one wait,
  one notification) and the decision is ``await_release``. The controller never releases, edits or resubmits a
  held job; the job may continue once the operator or the facility releases it. A hold that outlasts the
  operator's wait bound becomes ``end_qualified``: the step holds with the typed reason ``batch_jobs_held`` and the
  run's bounded ending drains every journalled job.
- **removed** (cancelled at the scheduler by someone other than this run's own drain or stop): the operator is told
  through the ``jobs_removed`` condition and the decision is ``recover``. The step holds with the typed reason
  ``batch_jobs_removed``, which the runtime recovery classifies as recoverable: a judgment recovery plan may propose
  another method (a new submission only through a replanned, approved plan and its own capability), an
  approximation or a descope. Its effects are admitted only after the operator acknowledged the removal
  (``ravel operator resume --run``), because a facility removal can signal a policy breach only a human can judge.
- a job seen running or pending again after a hold clears the condition this observer opened.

Each decision is a ``batch-recovery-decision`` store record with its code, the jobs, the observations and the
remedy; a decision identical to the latest one for the same jobs is not recorded again.

Stop (``stop_jobs``). ``ravel operator stop|revoke --run`` drains the run's batch jobs itself, after recording the
control: only with an operator (or controller-terminal) stop or revoke as the run's current control; every
journalled job and remote attempt is observed, cancelled when not terminal, and observed again until it is
terminal or the bound passes. The ``batch-stop`` record lists each job's state before, the cancellation request and
the state after; ``verified`` is true only when every job was observed terminal. A second stop is idempotent: jobs
already observed terminal are not cancelled again, and the record says so. Child controller runs frozen under this
run are drained the same way. The pause command does not cancel batch jobs itself (cancelling would discard work).
"""
from __future__ import annotations

from copy import deepcopy
import time

OBSERVATION = 'batch-observation'
DECISION = 'batch-recovery-decision'
STOP = 'batch-stop'
DECISIONS = ('await_release', 'end_qualified', 'recover')
HOLD_CODES = ('batch_jobs_held', 'batch_jobs_removed')
STOP_CONTROLS = ('stop', 'revoke')
REMEDIES = {
    'await_release': 'release the held jobs at the scheduler (or let the facility release them) and acknowledge with '
                     '`ravel operator resume --run <run>`, or end the run with `ravel operator stop --run <run>`; '
                     'the controller never releases or resubmits a held job',
    'end_qualified': 'the hold outlasted the operator\'s wait bound; the run ends qualified and its jobs are drained',
    'recover': 'acknowledge the removal with `ravel operator resume --run <run>`; the run then asks for a governed '
               'recovery plan (a new submission only through an approved plan), or stop the run',
}


class BatchJobsHold(ValueError):
    """A step that waits on batch jobs holds for a typed observer reason (``code`` in ``HOLD_CODES``)."""

    def __init__(self, code, detail):
        if code not in HOLD_CODES:
            raise ValueError('a batch-job hold is ' + ', '.join(HOLD_CODES))
        self.code, self.detail = code, detail
        super().__init__(f'{code}: {detail}')


def _records(store, kind):
    """The bodies of ``kind``. Only a store holding none reads empty; a journal that does not verify
    (``StoreTampered``) or cannot be read propagates, so a job census or a stop's drain never reads it as no jobs."""
    scan = getattr(store, 'scan', None)
    if scan is None:  # a store without records holds nothing
        return []
    try:
        rows = scan(kind)
    except KeyError:  # a mapping-backed store without the kind holds nothing
        return []
    return [deepcopy(row['record'] if type(row.get('record')) is dict else row) for row in rows]


def journalled(store, launch_id=None):
    """Every scheduler job the run journalled (``{launch_id, job, scheduler}``), each job once, in order."""
    seen, rows = set(), []
    for row in _records(store, 'study-site-job'):
        job = row.get('job')
        if type(job) is not str or row.get('scheduler') != 'htcondor' or job in seen:
            continue
        if launch_id is not None and row.get('launch_id') != launch_id:
            continue
        seen.add(job)
        rows.append({'launch_id': row.get('launch_id'), 'job': job, 'scheduler': row['scheduler']})
    return rows


def _terminal_seen(store):
    """Jobs already observed terminal (``cancelled`` or ``exited``) by any reconciliation, drain or stop."""
    from .routes.study.site import JOB_TERMINAL
    return {row.get('job') for row in _records(store, 'study-site-job-state')
            if (row.get('observation') or {}).get('state') in JOB_TERMINAL}


def own_cancellations(store):
    """Jobs this run itself asked the scheduler to remove (a drain or a stop); their removal is not a condition."""
    found = {row.get('job') for row in _records(store, 'study-site-job-state') if 'cancel' in row}
    for record in _records(store, STOP):
        found.update(row.get('job') for row in record.get('jobs') or () if row.get('cancel'))
    return found


def classify(store, rows, *, hold_reason=None):
    """``{jobs, held, removed, active}`` for observed rows ``{launch_id, job, observation}`` (no store write).

    A held job's observation gains the scheduler's hold reason; a cancelled job counts as removed only when this
    run never asked for its removal.
    """
    from ravel.workflow import wms_site
    hold_reason = hold_reason or wms_site.hold_reason
    own = own_cancellations(store)
    rows = [{'launch_id': r.get('launch_id'), 'job': r.get('job'), 'observation': deepcopy(r.get('observation') or {})}
            for r in rows if type(r.get('job')) is str]
    for row in rows:
        if row['observation'].get('state') == 'held' and 'hold' not in row['observation']:
            try:
                row['observation']['hold'] = hold_reason(row['job'])
            except Exception as exc:
                row['observation']['hold'] = {'error': f'{type(exc).__name__}: {exc}'[:300]}
    held = [r for r in rows if r['observation'].get('state') == 'held']
    removed = [r for r in rows if r['observation'].get('state') == 'cancelled' and r['job'] not in own]
    active = [r for r in rows if r['observation'].get('state') in ('pending', 'running')]
    return {'jobs': rows, 'held': held, 'removed': removed, 'active': active}


def observe(store, *, launch_id=None, observe_job=None, hold_reason=None):
    """Observe every journalled, not yet terminal job once and classify it (``classify``; no store write)."""
    from ravel.workflow import wms_site
    observe_job = observe_job or wms_site.observe_job
    done = _terminal_seen(store)
    rows = []
    for row in journalled(store, launch_id):
        if row['job'] in done:
            continue
        try:
            observation = observe_job(row['job'])
        except Exception as exc:  # one unobservable job never hides the others; unknown is never success
            observation = {'state': 'unknown', 'error': f'{type(exc).__name__}: {exc}'[:300]}
        rows.append({**row, 'observation': observation})
    return classify(store, rows, hold_reason=hold_reason)


def _latest_condition(store, code):
    from .authority import autonomy
    found = None
    for when, _, record in autonomy._scan(store, autonomy.CONDITION):
        if record.get('code') == code:
            found = (when, record)
    return found


def _report(store, code, jobs, evidence):
    """Open ``code`` for ``jobs`` (unless the same open report stands unacknowledged) and its operator wait.

    The wait is recorded and notified once (``autonomy.open_wait``: run name and state code only) while the step is
    still waiting on its jobs, not only at the next wave guard. Returns ``{reported, wait, notification_error}``.
    """
    from .authority import autonomy
    subject = 'jobs ' + ','.join(sorted(jobs))
    latest, reported = _latest_condition(store, code), True
    if latest is not None:
        when, record = latest
        if (record.get('phase') == 'open' and record.get('subject') == subject
                and when > autonomy._acknowledged_ns(store)):
            reported = False
    if reported:
        autonomy.report_condition(store, code, phase='open', subject=subject, evidence=evidence)
    found = {'reported': reported, 'wait': None, 'notification_error': None}
    try:
        for row in autonomy.condition_findings(store):
            if row['code'] == code:
                found['wait'] = autonomy.open_wait(store, row).get('id')
    except Exception as exc:  # a run without a frozen mode has no operator wait; the decision still holds
        found['notification_error'] = f'{type(exc).__name__}: {exc}'[:300]
    return found


def _clear(store, code, evidence):
    from .authority import autonomy
    latest = _latest_condition(store, code)
    if latest is not None and latest[1].get('phase') == 'open':
        autonomy.report_condition(store, code, phase='cleared', subject=latest[1].get('subject'), evidence=evidence)
        return True
    return False


def _held_since(store, jobs):
    """When the observer first recorded the current hold of exactly ``jobs`` (ns), else None."""
    latest = [r for r in _records(store, DECISION) if r.get('code') == 'batch_jobs_held']
    if not latest or latest[-1].get('decision') not in ('await_release', 'end_qualified'):
        return None
    if sorted(latest[-1].get('jobs') or []) != sorted(jobs):
        return None
    return latest[-1].get('first_held_ns')


def _holding(store):
    """Whether this observer's latest held-job decision still awaits a release (it opened ``jobs_held``)."""
    latest = [r for r in _records(store, DECISION) if r.get('code') == 'batch_jobs_held']
    return bool(latest) and latest[-1].get('decision') in ('await_release', 'end_qualified')


def _wait_bound(store):
    try:
        from .authority import mode as mode_mod
        bound = (mode_mod.frozen(store, required=False) or {}).get('wait_bound_seconds')
    except Exception:  # without a frozen mode only the step's own ceiling bounds the wait
        return None
    return bound if type(bound) in (int, float) and bound >= 0 else None


def decide(store, observed, *, now_ns=None):
    """The typed recovery decision for an observation (``observe``): a list of decision rows (may be empty).

    Records the conditions (``jobs_held``, ``jobs_removed``) and each new decision (``batch-recovery-decision``).
    """
    now_ns = time.time_ns() if now_ns is None else now_ns
    decisions = []
    held = sorted(r['job'] for r in observed['held'])
    if held:
        evidence = {'jobs': [{'job': r['job'], 'launch_id': r['launch_id'], 'observation': r['observation']}
                             for r in observed['held']]}
        reported = _report(store, 'jobs_held', held, evidence)
        since = _held_since(store, held) or now_ns
        bound = _wait_bound(store)
        expired = bound is not None and now_ns - since >= bound * 1e9
        decisions.append({'code': 'batch_jobs_held', 'condition': 'jobs_held', 'jobs': held,
                          'decision': 'end_qualified' if expired else 'await_release', 'first_held_ns': since,
                          'wait_bound_seconds': bound, 'recoverable_by_replan': False, 'wait': reported['wait'],
                          'notification_error': reported['notification_error'],
                          'controller_never': ['release', 'edit', 'resubmit'], 'evidence': evidence})
    elif _holding(store) and _clear(store, 'jobs_held', {'jobs': [{'job': r['job'], 'observation': r['observation']}
                                              for r in observed['active']]}):
        decisions.append({'code': 'batch_jobs_held', 'condition': 'jobs_held', 'jobs': [], 'decision': 'released',
                          'recoverable_by_replan': False, 'evidence': {'active': [r['job'] for r in observed['active']]}})
    removed = sorted(r['job'] for r in observed['removed'])
    if removed:
        evidence = {'jobs': [{'job': r['job'], 'launch_id': r['launch_id'], 'observation': r['observation']}
                             for r in observed['removed']]}
        reported = _report(store, 'jobs_removed', removed, evidence)
        decisions.append({'code': 'batch_jobs_removed', 'condition': 'jobs_removed', 'jobs': removed,
                          'decision': 'recover', 'recoverable_by_replan': True, 'wait': reported['wait'],
                          'notification_error': reported['notification_error'],
                          'controller_never': ['resubmit without an approved plan'], 'evidence': evidence})
    previous = {}
    for record in _records(store, DECISION):
        previous[record.get('code')] = record
    for row in decisions:
        row['remedy'] = REMEDIES.get(row['decision'], 'none needed')
        last = previous.get(row['code'])
        if last is None or (last.get('decision'), sorted(last.get('jobs') or [])) != (row['decision'], row['jobs']):
            store.append(DECISION, {'schema_version': 1, **deepcopy(row), 'time_ns': now_ns})
    return decisions


def hold_for(decisions):
    """The typed hold a waiting step raises for these decisions, else None (wait on)."""
    for row in decisions:
        if row['decision'] == 'recover':
            return BatchJobsHold('batch_jobs_removed', 'the scheduler removed batch jobs this run did not cancel: '
                                 + ', '.join(row['jobs']) + '; ' + row['remedy'])
    for row in decisions:
        if row['decision'] == 'end_qualified':
            return BatchJobsHold('batch_jobs_held', 'batch jobs stayed held past the operator\'s wait bound: '
                                 + ', '.join(row['jobs']) + '; ' + row['remedy'])
    return None


# ---- the operator stop's own drain -------------------------------------------------------------------------

def _descendants(store, _seen=()):
    """Controller runs frozen as children of ``store``'s run (any depth), read from the operator's store root."""
    from pathlib import Path
    from .authority import common, mode as mode_mod
    from .authority.operator import operator_config
    run_id = common.run_id(store)
    if run_id in _seen or len(_seen) >= 64:
        return []
    try:
        root = Path(operator_config()['store_root'])
        names = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name != run_id)
    except (OSError, KeyError, ValueError, common.AuthorityRefused):
        return []
    found = []
    for name in names:
        try:
            child = common.open_store(name)
            parent = (mode_mod.frozen(child, required=False) or {}).get('parent') or {}
        except Exception:  # an unreadable or foreign directory is not this run's child
            continue
        if parent.get('run_id') == run_id:
            found.append(child)
            found.extend(_descendants(child, (*_seen, run_id)))
    return found


def _current_stop(store):
    from .authority import common, stop
    view = stop._local_control(store)
    if view['request'] != 'stop' or view['record'] is None:
        return None
    record = next((r for r in common.scan(store, common.AUTHORITY, common.SCHEMA) if r.get('id') == view['record']),
                  None)
    if record is None or record.get('kind') not in STOP_CONTROLS:
        return None
    if record.get('label') not in (common.OPERATOR_COMMAND, common.LEGACY_TERMINAL):
        return None
    return record


def _inherited_stop(store, control):
    """``control`` (an ancestor's operator stop) when ``store``'s run is stopped through that ancestry, else None."""
    from .authority import stop
    view = stop.control(store)
    if view['state'] == 'running' or not view.get('ancestor') or view.get('request') != 'stop':
        return None
    return control


def stop_jobs(store, *, wait_seconds=10, children=True, observe_job=None, cancel_job=None, _inherited=None):
    """Drain the run's batch jobs for its current operator stop; returns (and records) the verified result.

    Refuses (``AuthorityRefused``) unless the run's current control is an operator or controller-terminal stop or
    revoke (a descendant run: its ancestor's, which it inherits). Idempotent: jobs already observed terminal are
    listed, never cancelled again.
    """
    from ravel.workflow import wms_site
    from .authority import common
    from .routes.study import site
    observe_job = observe_job or wms_site.observe_job
    cancel_job = cancel_job or wms_site.cancel_job
    if type(wait_seconds) not in (int, float) or not 0 <= wait_seconds <= 30:
        raise ValueError('the stop waits at most thirty seconds per job')
    control = _current_stop(store) if _inherited is None else _inherited_stop(store, _inherited)
    if control is None:
        raise common.AuthorityRefused('batch jobs are drained only for the run\'s current operator stop or revoke')
    done = _terminal_seen(store)
    jobs = []
    for row in journalled(store):
        result = {'launch_id': row['launch_id'], 'job': row['job']}
        if row['job'] in done:
            jobs.append({**result, 'before': 'terminal (recorded)', 'cancel': None, 'after': None, 'verified': True,
                         'already_terminal': True})
            continue
        try:
            before = observe_job(row['job'])
            after, cancel = before, None
            if before.get('state') not in site.JOB_TERMINAL:
                cancel = cancel_job(row['job'])
                after = observe_job(row['job'])
                deadline = time.monotonic() + wait_seconds
                while after.get('state') not in site.JOB_TERMINAL and time.monotonic() < deadline:
                    time.sleep(0.5)
                    after = observe_job(row['job'])
            result.update(before=before, cancel=cancel, after=after,
                          verified=after.get('state') in site.JOB_TERMINAL, already_terminal=cancel is None)
        except Exception as exc:  # one unobservable job never hides the others; it stays unverified
            result.update(error=f'{type(exc).__name__}: {exc}'[:300], verified=False)
        jobs.append(result)
        state = {'launch_id': row['launch_id'], 'job': row['job'], 'drain': True, 'stop': control['id'],
                 'cancelled': bool((result.get('cancel') or {}).get('returncode') == 0),
                 'observation': deepcopy(result.get('after') or result.get('before') or {})}
        if result.get('cancel') is not None:
            state['cancel'] = deepcopy(result['cancel'])
        if 'error' in result:
            state['error'] = result['error']
        store.append('study-site-job-state', state)
    # Remote driver attempts: the backend owns their cancellation and its terminal-state verification.
    attempts = []
    if _records(store, 'study-remote'):
        try:
            remote = site.reconcile(store, drain=True, wait_seconds=min(wait_seconds, 30))
            attempts = [{'launch_id': r.get('launch_id'), 'verified': bool(r.get('resolved')),
                         'state': (r.get('observation') or {}).get('state'), 'error': r.get('error')}
                        for r in remote['attempts']]
        except Exception as exc:
            attempts = [{'error': f'{type(exc).__name__}: {exc}'[:300], 'verified': False}]
    descendants = []
    if children:
        for child in _descendants(store):
            try:
                descendants.append({'run_id': common.run_id(child),
                                    **stop_jobs(child, wait_seconds=wait_seconds, children=False,
                                                observe_job=observe_job, cancel_job=cancel_job, _inherited=control)})
            except common.AuthorityRefused as exc:  # a child not stopped through this run: reported, never drained
                descendants.append({'run_id': common.run_id(child), 'refused': str(exc)[:300], 'verified': False})
    unverified = [j['job'] for j in jobs if not j['verified']] + \
        [a.get('launch_id') for a in attempts if not a['verified']]
    verified = not unverified and all(d.get('verified') for d in descendants)
    record = {'schema_version': 1, 'control': control['id'], 'control_kind': control['kind'],
              'jobs': jobs, 'remote_attempts': attempts, 'descendants': [
                  {k: d.get(k) for k in ('run_id', 'verified', 'record', 'unverified', 'refused')} for d in descendants],
              'unverified': unverified, 'verified': verified, 'time_ns': time.time_ns()}
    record_id = store.append(STOP, record)
    return {'record': record_id, 'verified': verified, 'unverified': unverified, 'jobs': jobs,
            'remote_attempts': attempts, 'descendants': descendants}


__all__ = ['BatchJobsHold', 'DECISIONS', 'HOLD_CODES', 'classify', 'decide', 'hold_for', 'journalled', 'observe',
           'own_cancellations', 'stop_jobs']
