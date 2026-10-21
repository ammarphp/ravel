"""The controller's handling of a worker's ``escalation`` field (CF01).

Whether a worker raises an escalation is its judgment; what happens next is the controller's:

- ``stop``: the step halts and its outcome is escalated, so the controller graph notifies the
  physicist or operator; nothing the worker produced is consumed downstream;
- ``checkin_flag``: a numbered flag is appended for the next check-in and the step continues;
- ``decision_block``: an RDJ case request naming the adopted subject is appended and the step
  holds as escalated until the case resolves;
- ``new_experiment_required``: a replan request is appended and returned to the controller graph.

Every raised escalation is a record in the run store, whatever its kind.
"""
from __future__ import annotations

from copy import deepcopy

from ravel.workflow.state_io import file_lock

from .services import digest, lock_path, records

ESCALATION = 'step-escalation'
FLAG = 'checkin-flag'
RDJ_REQUEST = 'rdj-request'
REPLAN = 'replan-request'
HALTING = ('stop', 'decision_block', 'new_experiment_required')


def handle(store, *, step, attempt, seat, escalations, adopted=()):
    """Record and act on every raised escalation; return the outcome fields they set."""
    if not escalations:
        return {'escalation': None, 'replan': None, 'flags': [], 'records': [], 'halts': False}
    subject = [{'artifact': row['artifact'], 'sha256': row['sha256']} for row in adopted]
    written, flags, replan = [], [], None
    for item in escalations:
        key = digest({'step': step['id'], 'attempt': attempt, 'seat': seat, 'item': item['record_sha256']})
        if any(row.get('key') == key for row in records(store, ESCALATION)):
            continue
        base = {'schema_version': 1, 'key': key, 'step_id': step['id'], 'attempt': attempt, 'seat': seat,
                'kind': item['kind'], 'statement': item.get('statement'), 'evidence': deepcopy(item.get('evidence')),
                'options': deepcopy(item.get('options')), 'subject': deepcopy(subject)}
        if item['kind'] == 'stop':
            base['action'] = 'halt_and_notify'
        elif item['kind'] == 'checkin_flag':
            with file_lock(lock_path(store, 'checkin-flags')):
                number = len(records(store, FLAG)) + 1
                flag = {'schema_version': 1, 'number': number, 'step_id': step['id'], 'attempt': attempt,
                        'seat': seat, 'statement': item.get('statement'), 'evidence': deepcopy(item.get('evidence'))}
                flag['record_id'] = store.append(FLAG, flag)
            flags.append(flag)
            base['action'], base['flag'] = 'checkin_flag', number
        elif item['kind'] == 'decision_block':
            request = {'schema_version': 1, 'step_id': step['id'], 'attempt': attempt, 'seat': seat,
                       'subject': deepcopy(subject), 'question': item.get('statement'),
                       'options': deepcopy(item.get('options')), 'evidence': deepcopy(item.get('evidence'))}
            base['action'], base['rdj_request'] = 'open_rdj_case', store.append(RDJ_REQUEST, request)
        else:
            replan = {'schema_version': 1, 'step_id': step['id'], 'attempt': attempt, 'seat': seat,
                      'statement': item.get('statement'), 'evidence': deepcopy(item.get('evidence')),
                      'subject': deepcopy(subject)}
            replan['record_id'] = store.append(REPLAN, replan)
            base['action'], base['replan_request'] = 'replan', replan['record_id']
        base['record_id'] = store.append(ESCALATION, base)
        written.append(base)
    from .validate import primary
    kind = primary(escalations)
    return {'escalation': kind, 'replan': replan, 'flags': flags, 'records': [r['record_id'] for r in written],
            'halts': kind in HALTING}
