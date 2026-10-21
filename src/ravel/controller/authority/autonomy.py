"""Autonomy boundaries of a controller run: the operator's grant, its bounds and the waits for a human.

An autonomous run acts only inside the operator's grant: the operator ledger entry frozen at
intake, its expiry, the project trees it covers, its deadline and the run's own budgets. Every
boundary (the wave guard, the driver start and resume, every check-in and every effect
admission) reads ``findings``: what currently ends the run (``end``) or holds it for a human
(``wait``). Nothing here grants authority; it only withholds it.

- ``end`` findings (``authority_expired``, ``authority_revoked``, ``deadline_margin``): new work stops
  and the run ends through the sink's qualified ending, which names the boundary.
- ``wait`` findings (``authority_invalid``, ``authority_missing``, ``project_scope``,
  ``instruction_changed``, ``paused``, ``disk_exhausted``, ``launch_failures`` and the conditions
  a launch reports: ``proxy_expired``, ``jobs_held``, ``jobs_removed``): the run waits at the
  boundary. Each new wait is recorded once and notifies the operator once, with the run name and the
  state code only (the reason stays in the store and on the controller's terminal). A wait clears
  when its condition clears, or (for conditions only the operator can judge) when the operator
  acknowledges it with ``ravel operator resume --run``. A wait past the operator's wait bound ends
  the run qualified.

What the grant protects against, and what it does not (recorded in every receipt through
``boundary_statement``): the ledger and every authority record are MACed with the operator's key,
which lies outside every sandboxed worker's mounts, so a confined worker cannot create, widen,
re-date or copy a grant; an edited or replaced ledger refuses at intake and at every admission.
A process running unconfined under the operator's own uid can read that key; only a separate OS
identity or an external issuer closes that path.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys

from . import common

WAIT = 'autonomy-wait'
BOUNDARY = 'autonomy-boundary'
CONDITION = 'autonomy-condition'
END_CODES = ('authority_expired', 'authority_revoked', 'deadline_margin')
WAIT_CODES = ('authority_invalid', 'authority_missing', 'project_scope', 'instruction_changed', 'paused',
              'disk_exhausted', 'launch_failures', 'proxy_expired', 'jobs_held', 'jobs_removed')
# Conditions a launch observer reports; they clear when the observer reports them cleared or the operator
# acknowledges them.
CONDITIONS = ('proxy_expired', 'jobs_held', 'jobs_removed')
# Waits only the operator can judge: they clear on an operator resume recorded after them.
ACKNOWLEDGED = ('launch_failures', *CONDITIONS)
LAUNCH_FAILURE_LIMIT = 3
PROJECT_DECLARATION = '.ravel/project-instructions.json'
REMEDIES = {
    'authority_invalid': 'the operator inspects the ledger with `ravel operator show` from their own terminal; '
                         'an edited ledger never authenticates again',
    'authority_missing': 'the operator ledger was replaced; start a new run under a new grant',
    'authority_expired': 'the grant expired; the run ends qualified',
    'authority_revoked': 'the operator revoked the grant; the run ends qualified',
    'project_scope': 'the run directory is outside the grant\'s project scope; move it back or start a new run',
    'deadline_margin': 'the deadline margin is reached; the run ends qualified',
    'instruction_changed': 'the operator re-pins the instruction document from their own terminal: '
                           '`ravel project-instructions repin --rundir <run> --approved-by ... --statement ...`',
    'paused': 'the operator resumes the run: `ravel operator resume --run <run> --reason ...`',
    'disk_exhausted': 'free space below the operator\'s floor; free space, then the run continues',
    'launch_failures': 'repeated launch failures; the operator inspects them and acknowledges with '
                       '`ravel operator resume --run <run> --reason ...`',
    'proxy_expired': 'renew the credential, then acknowledge with `ravel operator resume --run <run> --reason ...`',
    'jobs_held': 'inspect the held batch jobs, then acknowledge with `ravel operator resume --run <run> --reason ...`',
    'jobs_removed': 'inspect the removed batch jobs, then acknowledge with `ravel operator resume --run <run> '
                    '--reason ...`',
}


def boundary_statement():
    """What a same-uid process can still cross; carried by receipts and the operator status."""
    return {'grant_authentication': 'hmac-sha256 under the operator key outside every worker mount',
            'confined_worker_can_write_grant': False,
            'unconfined_same_uid_can_forge': True,
            'closing_that_path_requires': 'a separate OS identity or an external issuer'}


def _now():
    return common.now_ns() / 1e9


def _real(path):
    return Path(os.path.realpath(Path(path).expanduser()))


def in_scope(run_dir, scope):
    """Whether ``run_dir`` lies inside one of the absolute project paths of ``scope`` (None: every path)."""
    if scope is None:
        return True
    if run_dir is None:
        return False
    real = _real(run_dir)
    return any(real == _real(p) or _real(p) in real.parents for p in scope)


def intake_refusal(config, run_dir):
    """Refuse a run the grant does not cover: expired, or outside the project scope (N1).

    Applies when the configuration grants machine authority (autonomous mode or request-stated
    delegation); a physicist-in-the-loop configuration grants nothing to refuse.
    """
    from .operator import parse_utc
    if config.get('mode') != 'autonomous' and not config.get('allow_request_delegation'):
        return
    expires = config.get('expires_at')
    if expires is not None and parse_utc(expires) <= _now():
        raise common.AuthorityRefused(f'authority_expired: the operator grant expired at {expires}; the operator '
                                      'renews it with `ravel operator set --expires-at <UTC time>`')
    if run_dir is not None and not in_scope(run_dir, config.get('project_scope')):
        raise common.AuthorityRefused(f'project_scope: run directory {run_dir} is outside the operator grant\'s project '
                                      'scope; start the run under a covered project or the operator widens the scope')


# ---- the project instruction document (N3) -------------------------------------------------------

def declared_document(config, run_dir):
    """The instruction document the operator configuration or the project declares, or None."""
    if config.get('instruction_document'):
        return Path(config['instruction_document'])
    if run_dir is None:
        return None
    for folder in _real(run_dir).parents:
        declaration = folder / PROJECT_DECLARATION
        if declaration.is_file() and not declaration.is_symlink():
            try:
                value = json.loads(declaration.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise common.AuthorityRefused(f'instruction_declaration_invalid: {declaration}: {exc}') from None
            if (type(value) is not dict or value.get('schema_version') != 1
                    or value.get('kind') != 'project-instructions-declaration' or type(value.get('path')) is not str):
                raise common.AuthorityRefused(f'instruction_declaration_invalid: {declaration} is not a declaration')
            return folder / value['path']
    return None


def instruction_pin(config, run_dir):
    """``{path, sha256, bytes, source}`` of the declared document at intake, or None when none is declared."""
    from ravel.workflow import project_instructions
    document = declared_document(config, run_dir)
    if document is None:
        return None
    try:
        pinned = project_instructions.pin(document)
    except project_instructions.ProjectInstructionsError as exc:
        raise common.AuthorityRefused(f'instruction_document_unavailable: {exc}') from None
    return {**pinned, 'source': 'operator' if config.get('instruction_document') else 'project'}


def pin_instructions(store, run_dir, mode):
    """Pin the frozen document into the run (``ravel project-instructions pin``) once, at intake."""
    from ravel.workflow import project_instructions
    frozen = (mode or {}).get('instruction_pin')
    if not frozen or run_dir is None:
        return None
    try:
        if project_instructions.declared(run_dir) is None:
            project_instructions.declare(run_dir, frozen['path'])
        return project_instructions.for_run(run_dir)
    except project_instructions.ProjectInstructionsError:
        return None  # the boundary check reports the changed document as a wait


def instruction_finding(store, mode, run_dir):
    """A wait when the run's document no longer matches its pin, or was re-pinned without an approval."""
    from ravel.workflow import project_instructions
    frozen = (mode or {}).get('instruction_pin')
    if not frozen or run_dir is None:
        return None
    try:
        pinned = project_instructions.declared(run_dir)
        if pinned is None:
            return None  # intake pins it; nothing was delivered yet
        project_instructions.text_of({**pinned, 'rundir': str(run_dir)})
    except project_instructions.ProjectInstructionsError as exc:
        return _finding('instruction_changed', 'wait', str(exc)[:600], subject=frozen['sha256'])
    if pinned['sha256'] != frozen['sha256'] and not pinned.get('approval'):
        return _finding('instruction_changed', 'wait', 'the run pins another document than the one frozen at '
                        'intake, without an approval', subject=pinned['sha256'])
    return None


def current_instruction_sha256(run_dir):
    """The sha256 of the document the run currently pins, or None."""
    from ravel.workflow import project_instructions
    try:
        pinned = project_instructions.declared(run_dir) if run_dir is not None else None
    except project_instructions.ProjectInstructionsError:
        return None
    return None if pinned is None else pinned['sha256']


# ---- findings ------------------------------------------------------------------------------------

def _finding(code, kind, reason, *, subject=None):
    return {'code': code, 'kind': kind, 'reason': reason, 'remedy': REMEDIES.get(code, ''),
            'subject': subject}


def _scan(store, kind):
    """``[(time_ns, id, body)]`` of ``kind``: a store wraps bodies under ``record``; a bare store returns them.

    Only a store that holds no records of ``kind`` reads empty. A journal that does not verify (``StoreTampered``)
    or cannot be read propagates: a stop, wait or failure census never reads a broken ledger as "nothing recorded".
    """
    scan = getattr(store, 'scan', None)
    if scan is None:  # a store without records holds nothing
        return []
    try:
        entries = scan(kind)
    except KeyError:  # a mapping-backed store without the kind holds nothing
        return []
    rows = []
    for entry in entries:
        body = entry.get('record') if type(entry.get('record')) is dict else entry
        rows.append((entry.get('time_ns') or body.get('time_ns') or 0, entry.get('id'), body))
    return rows


def _run_dir(store):
    try:
        found = store.run_dir
    except Exception:
        return None
    return Path(found) if found is not None else None


def grant_findings(store, mode, run_dir):
    """The operator grant this run was frozen under, read again from the authenticated ledger."""
    from .operator import grant_history, parse_utc
    if mode.get('mode') != 'autonomous':
        return []
    rows = []
    if mode.get('operator_source') == 'operator_ledger':
        later, problem = grant_history(mode.get('operator_entry'))
        if problem is not None:
            return [_finding(problem[0], 'wait', problem[1])]
        digest = (mode.get('operator_entry') or {}).get('digest')
        for row in later:
            record = row['record']
            if record.get('action') == 'revoke' and digest in (record.get('revokes') or ()):
                rows.append(_finding('authority_revoked', 'end', 'the operator revoked the grant this run was frozen '
                                     'under (ledger entry ' + str(row['seq']) + ')'))
                break
    expires = mode.get('expires_at')
    if expires is not None and parse_utc(expires) <= _now():
        rows.append(_finding('authority_expired', 'end', f'the operator grant expired at {expires}'))
    if not in_scope(run_dir, mode.get('project_scope')):
        rows.append(_finding('project_scope', 'wait', f'the run directory {run_dir} is outside the grant\'s project '
                             'scope'))
    return rows


def _launch_failures(store, since_ns):
    """Consecutive refused or failed launches since the last success or operator acknowledgement."""
    streak = 0
    for when, _, record in _scan(store, 'step-launch'):
        if when <= since_ns:
            continue
        if record.get('phase') == 'refused' or (record.get('phase') == 'finished'
                                                and (record.get('exit_status') != 0 or record.get('timed_out'))):
            streak += 1
        elif record.get('phase') == 'finished':
            streak = 0
    return streak


def _acknowledged_ns(store):
    """When the operator last resumed (acknowledged) the run; 0 when never."""
    try:
        rows = common.scan(store, common.AUTHORITY, common.SCHEMA)
    except Exception:
        return 0
    found = [r['time_ns'] for r in rows if r.get('kind') == 'resume' and r.get('label') == common.OPERATOR_COMMAND]
    return max(found) if found else 0


def condition_findings(store):
    """Open conditions a launch observer reported (credential expiry, held or removed batch jobs)."""
    acknowledged, latest = _acknowledged_ns(store), {}
    for when, _, record in _scan(store, CONDITION):
        code = record.get('code')
        key = (code, str(record.get('subject') or '')) if code == 'proxy_expired' else (code, '')
        latest[key] = (when, record)
    rows = []
    for (code, _), (when, record) in sorted(latest.items()):
        if (code in CONDITIONS and record.get('phase') == 'open'
                and (when > acknowledged or code == 'proxy_expired')):
            rows.append(_finding(code, 'wait', f'a launch reported {code.replace("_", " ")}',
                                 subject=str(record.get('subject') or '')[:200]))
    failures = _launch_failures(store, acknowledged)
    if failures >= LAUNCH_FAILURE_LIMIT:
        rows.append(_finding('launch_failures', 'wait', f'{failures} consecutive launches failed or were refused'))
    return rows


def report_condition(store, code, *, phase='open', subject=None, evidence=None):
    """A launch observer's report of a condition that needs a human (or that it cleared)."""
    if code not in CONDITIONS or phase not in ('open', 'cleared'):
        raise ValueError('a condition is ' + ', '.join(CONDITIONS) + ' and opens or clears')
    return store.append(CONDITION, {'schema_version': 1, 'code': code, 'phase': phase, 'subject': subject,
                                    'evidence': deepcopy(evidence or {}), 'time_ns': common.now_ns()})


def findings(store, *, include_pause=True):
    """Every current end and wait finding of the run (ends first); empty without a frozen mode."""
    from . import mode as mode_mod, stop
    mode = mode_mod.frozen(store, required=False)
    if mode is None:
        return []
    run_dir = _run_dir(store)
    rows = grant_findings(store, mode, run_dir)
    deadline = mode.get('deadline')
    if deadline:
        from .operator import parse_utc
        if _now() >= parse_utc(deadline['at']) - deadline['margin_seconds']:
            rows.append(_finding('deadline_margin', 'end', f'the deadline margin is reached (deadline {deadline["at"]}, '
                                 f'margin {deadline["margin_seconds"]} s)'))
    found = instruction_finding(store, mode, run_dir)
    if found is not None:
        rows.append(found)
    floor = mode.get('disk_free_floor_bytes')
    if floor:
        for path in (run_dir, Path(store.root) if getattr(store, 'root', None) else None):
            try:
                free = shutil.disk_usage(path).free if path is not None else None
            except OSError:
                free = None
            if free is not None and free < floor:
                rows.append(_finding('disk_exhausted', 'wait', f'free space {free} bytes is below the operator\'s '
                                     f'floor {floor} bytes', subject=str(path)))
                break
    rows += condition_findings(store)
    if include_pause:
        view = stop.control(store)
        if view['state'] in ('pause_requested', 'draining') and view.get('request') == 'pause':
            rows.append(_finding('paused', 'wait', 'the operator paused the run', subject=view.get('record')))
    return sorted(rows, key=lambda r: (r['kind'] != 'end', r['code']))


def admit(store, action='effect'):
    """Refuse ``action`` while any finding holds; a new wait is recorded and notified once (N1, N7)."""
    rows = findings(store, include_pause=False)
    if not rows:
        return []
    for row in rows:
        if row['kind'] == 'wait':
            open_wait(store, row)
    first = rows[0]
    raise common.AuthorityRefused(f'{first["code"]}: {action} refused: {first["reason"]}; {first["remedy"]}')


# ---- waits (N7) --------------------------------------------------------------------------------

def _key(row):
    return row['code'] + ':' + str(row.get('subject') or '')


def waits(store):
    """``{key: latest wait record (with id and time_ns)}`` of every wait the run recorded."""
    found = {}
    for when, identifier, record in _scan(store, WAIT):
        found[record.get('key')] = {**record, 'id': identifier, 'time_ns': when}
    return found


def open_waits(store):
    return [w for w in waits(store).values() if w.get('phase') == 'open']


def open_wait(store, row):
    """Record a new wait once and notify the operator once (run name and state code only)."""
    from . import mode as mode_mod, service
    key = _key(row)
    existing = waits(store).get(key)
    if existing is not None and existing.get('phase') == 'open':
        return existing
    mode = mode_mod.frozen(store)
    since = common.now_ns()
    notification = service._notify(mode, common.run_id(store), 'WAITING_FOR_HUMAN ' + row['code'])
    record = {'schema_version': 1, 'key': key, 'code': row['code'], 'phase': 'open', 'since_ns': since, 'time_ns': since,
              'reason': row['reason'], 'remedy': row['remedy'], 'subject': row.get('subject'),
              'notification': notification, 'wait_bound_seconds': mode.get('wait_bound_seconds')}
    identifier = store.append(WAIT, record)
    print(f'WAITING FOR A HUMAN since {service._utc(since)}: run {common.run_id(store)}, {row["code"]}: '
          f'{row["reason"]} -- {row["remedy"]}', file=sys.stderr, flush=True)
    return {**record, 'id': identifier}


def settle(store, rows=None):
    """Close each open wait whose condition no longer holds; returns ``(cleared, still open)``."""
    current = {_key(r) for r in (findings(store) if rows is None else rows) if r['kind'] == 'wait'}
    cleared, remaining = [], []
    for wait in open_waits(store):
        if wait['key'] in current:
            remaining.append(wait)
            continue
        store.append(WAIT, {**{k: wait[k] for k in ('key', 'code', 'since_ns', 'subject')}, 'schema_version': 1,
                            'phase': 'resolved', 'resolved_ns': common.now_ns(), 'time_ns': common.now_ns()})
        cleared.append(wait)
    return cleared, remaining


def expire(store, wait):
    """A wait past the operator's wait bound: recorded expired; the run then ends qualified."""
    return store.append(WAIT, {**{k: wait[k] for k in ('key', 'code', 'since_ns', 'subject')}, 'schema_version': 1,
                               'phase': 'expired', 'expired_ns': common.now_ns(), 'time_ns': common.now_ns()})


def expired(store):
    """The expired waits not resolved since (each ends the run qualified)."""
    return [w for w in waits(store).values() if w.get('phase') == 'expired']


def overdue(wait):
    bound = wait.get('wait_bound_seconds')
    return type(bound) in (int, float) and (common.now_ns() - wait['since_ns']) / 1e9 >= bound


# ---- the guard's view (N6) -----------------------------------------------------------------------

def guard(store):
    """``(verdict, finding)`` for the controller's wave guard: ``exhausted`` on an end finding or an expired
    wait, ``wait`` on a wait finding (recorded and notified once), else ``go``."""
    rows = findings(store)
    ends = [r for r in rows if r['kind'] == 'end']
    if ends:
        store.append(BOUNDARY, {'schema_version': 1, **ends[0], 'time_ns': common.now_ns()})
        return 'exhausted', ends[0]
    gone = expired(store)
    if gone:
        row = _finding(gone[0]['code'], 'end', f'waiting for a human past the wait bound ({gone[0]["code"]})')
        store.append(BOUNDARY, {'schema_version': 1, **row, 'time_ns': common.now_ns()})
        return 'exhausted', row
    settle(store, rows)
    pending = [r for r in rows if r['kind'] == 'wait']
    for row in pending:
        open_wait(store, row)
    return ('wait', pending[0]) if pending else ('go', None)


def ending_reason(store, reason):
    """The bounded ending's reason with the boundary it reached named first, when one is recorded."""
    rows = _scan(store, BOUNDARY)
    if rows:
        latest = rows[-1][2]
    else:
        # The run reached its ending elsewhere (a refused admission, a failed node): an end boundary that holds now
        # is still the cause to name.
        try:
            ends = [r for r in findings(store, include_pause=False) if r['kind'] == 'end']
        except Exception:  # naming never blocks the ending
            ends = []
        if not ends:
            return reason
        latest = ends[0]
        store.append(BOUNDARY, {'schema_version': 1, **latest, 'time_ns': common.now_ns()})
    text = f'{latest["reason"]} [{latest["code"]}]'
    return text if str(reason) in ('exhausted', 'drain', 'bounded ending', '') else f'{text}; {reason}'


# ---- what is still alive (N8) and the audit trail (N10) --------------------------------------------

def alive(store):
    """Registered process groups under the run's store that are still alive, read without signalling them."""
    from ravel.workflow import graph_substrate
    found = []
    root = Path(getattr(store, 'root', '') or '.')
    for registry in sorted(root.glob('**/' + graph_substrate.PROCESSES)) if root.is_dir() else []:
        try:
            entries = json.loads(registry.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            found.append({'registry': str(registry), 'state': 'unreadable'})
            continue
        for entry in (entries.get('processes') if type(entries) is dict else entries) or ():
            if type(entry) is not dict or type(entry.get('pgid')) is not int:
                continue
            groups = [g for g in (entry['pgid'], entry.get('child_pgid')) if type(g) is int]
            if any(graph_substrate._group_alive(g) for g in groups):
                found.append({'registry': str(registry), 'id': entry.get('id'), 'role': entry.get('role'),
                              'pgid': entry['pgid'], 'child_pgid': entry.get('child_pgid')})
    return found


def terminate(store):
    """End every registered process group of the run still alive (``ravel operator stop --now``).

    Only groups the run's own process registries name are signalled, and only while the registered
    process still owns its group (no reused group id); nothing is signalled by name. Returns one row per
    group with whether it is gone; ``alive`` afterwards reports what is still running.
    """
    from ravel.workflow import graph_substrate
    root = Path(getattr(store, 'root', '') or '.')
    ended = []
    for registry in sorted(root.glob('**/' + graph_substrate.PROCESSES)) if root.is_dir() else []:
        scope = registry.parent.parent
        try:
            entries = graph_substrate.processes(scope)
        except (OSError, ValueError, KeyError):
            continue
        for entry in entries:
            if type(entry) is not dict or type(entry.get('pgid')) is not int:
                continue
            groups = [g for g in (entry['pgid'], entry.get('child_pgid')) if type(g) is int]
            if any(graph_substrate._group_alive(g) for g in groups):
                ended.append(graph_substrate._terminate(scope, entry))
    return ended


def audit_rows(store):
    """Machine approvals, judgment calls, escalations and boundaries with time, rule and evidence (N10)."""
    rows = []
    try:
        authority = common.scan(store, common.AUTHORITY, common.SCHEMA)
        requests = common.scan(store, common.REQUESTS, common.REQUEST_SCHEMA)
    except Exception as exc:
        return [{'kind': 'audit_unavailable', 'error': f'{type(exc).__name__}: {exc}'[:300]}]
    for record in authority:
        rows.append({'time_ns': record.get('time_ns'), 'event': 'authority', 'record': record['id'],
                     'kind': record.get('kind'), 'decision': record.get('decision'), 'option': record.get('option'),
                     'label': record.get('label'), 'source': record.get('source'),
                     'rule': f"{record.get('kind')}:{record.get('label')}:{record.get('source')}",
                     'evidence_sha256': common.digest(record.get('evidence')),
                     'operator_entry': (record.get('evidence') or {}).get('operator_entry'),
                     'mode_record': record.get('mode_record')})
    for record in requests:
        rows.append({'time_ns': record.get('since_ns'), 'event': 'escalation', 'record': record['id'],
                     'kind': record.get('kind'), 'rule': record.get('needed'), 'reason': record.get('reason'),
                     'evidence_sha256': record.get('subject_sha256'),
                     'notification': (record.get('notification') or {}).get('status')})
    for kind, event in ((WAIT, 'wait'), (BOUNDARY, 'boundary'), ('judgment-record', 'judgment')):
        for when, identifier, record in _scan(store, kind):
            rows.append({'time_ns': when, 'event': event, 'record': identifier,
                         'kind': record.get('code') or record.get('kind'), 'rule': record.get('phase')
                         or record.get('consequence_class') or record.get('class'),
                         'reason': record.get('reason'), 'evidence_sha256': common.digest(record)})
    return sorted(rows, key=lambda r: (r.get('time_ns') or 0, str(r.get('record'))))
