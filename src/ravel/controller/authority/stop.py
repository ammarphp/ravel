"""Stop, pause, resume and revocation, kept in the run's protected store.

The operator (``ravel operator stop|pause|resume|revoke --run``) or the physicist at the
controller terminal writes a control record; nothing in the run directory, no worker and no
flag clears one. Every effect checks the state first. A stop or revocation drains the run to its
bounded ending; a pause drains and waits. The state reads ``stop_requested`` (or
``pause_requested``) until the supervisor records that it is draining, then ``draining``, then
``stopped`` once every descendant is observed reaped. Revocation also withdraws machine
authority for the rest of the run: a later resume restores execution, never delegation.
"""
from __future__ import annotations

from . import common

STATES = ('running', 'pause_requested', 'stop_requested', 'draining', 'stopped')
PHASES = ('draining', 'stopped')


def _controls(store):
    rows = common.scan(store, common.AUTHORITY, common.SCHEMA)
    return [r for r in rows if r.get('kind') in common.CONTROLS and r.get('run_id') == common.run_id(store)]


def _local_control(store):
    """The run's control view: ``state``, the latest ``request`` and its record, and ``revoked``."""
    controls = _controls(store)
    revoked = next((r for r in controls if r['kind'] == 'revoke'), None)
    latest = controls[-1] if controls else None
    if latest is None or latest['kind'] == 'resume':
        return {'state': 'running', 'request': None, 'record': latest['id'] if latest else None,
                'since_ns': latest['time_ns'] if latest else None,
                'revoked': revoked is not None, 'revocation': revoked['id'] if revoked else None}
    observations = [o for o in common.scan(store, common.OBSERVATIONS, common.OBSERVATION_SCHEMA)
                    if o.get('control') == latest['id']]
    phases = {o['phase'] for o in observations}
    state = ('stopped' if 'stopped' in phases else 'draining' if 'draining' in phases
             else 'pause_requested' if latest['kind'] == 'pause' else 'stop_requested')
    return {'state': state, 'request': 'stop' if latest['kind'] == 'revoke' else latest['kind'],
            'record': latest['id'], 'since_ns': latest['time_ns'], 'revoked': revoked is not None,
            'revocation': revoked['id'] if revoked else None}


def control(store, _seen=()):
    if common.run_id(store) in _seen or len(_seen) >= 64:
        raise common.AuthorityRefused('cyclic or excessive authority ancestry')
    view = _local_control(store)
    from .mode import frozen
    mode = frozen(store, required=False)
    parent = (mode or {}).get('parent')
    if parent is not None:
        ancestor = common.open_store(parent['run_id'])
        if frozen(ancestor)['id'] != parent['mode_record']:
            raise common.AuthorityRefused('ancestor mode dependency changed')
        inherited = control(ancestor, (*_seen, common.run_id(store)))
        if inherited['state'] != 'running':
            return {**inherited, 'ancestor': parent['run_id']}
        if inherited['revoked']:
            view.update(revoked=True, revocation=inherited['revocation'], ancestor=parent['run_id'])
    return view


def stop_state(store):
    """``running``, ``pause_requested``, ``stop_requested``, ``draining`` or ``stopped``."""
    return control(store)['state']


def check(store, action='effect'):
    """Refuse ``action`` unless the run is running. Called before every effect and nested submission."""
    view = control(store)
    if view['state'] != 'running' or (view.get('ancestor') and view['revoked']):
        raise common.AuthorityRefused(f'{action} refused: the run is {view["state"].replace("_", " ")} '
                                      f'(control record {view["record"]}); only the operator or the physicist at '
                                      'the controller terminal can resume it')
    return view


def observe(store, phase, evidence=None):
    """Record what the supervisor observed after a stop or pause: ``draining``, then ``stopped``.

    ``stopped`` means every descendant was observed reaped; it needs a ``draining`` record first.
    Returns the observation, or None when no stop or pause is pending.
    """
    if phase not in PHASES:
        raise ValueError('a stop observation is draining or stopped')
    view = control(store)
    if view['request'] is None:
        return None
    if phase == 'stopped' and view['state'] in ('stop_requested', 'pause_requested'):
        raise common.AuthorityRefused('stopped is observed only after draining began')
    body = {'schema': common.OBSERVATION_SCHEMA, 'uid': common.uid(), 'run_id': common.run_id(store),
            'control': view['record'], 'phase': phase, 'evidence': evidence or {}, 'time_ns': common.now_ns()}
    return common.append(store, common.OBSERVATIONS, body)


def record_control(store, action, *, label, source, evidence, reason):
    """Append a control record (stop, pause, resume or revoke) and return it."""
    if action not in common.CONTROLS:
        raise ValueError('a control is stop, pause, resume or revoke')
    if label != common.OPERATOR_COMMAND and not (label == common.LEGACY_TERMINAL and action in ('stop', 'pause', 'revoke')):
        raise common.AuthorityRefused('only the operator or the physicist at the controller terminal controls a run')
    if type(reason) is not str or not reason.strip():
        raise ValueError('a control record states its reason')
    view = _local_control(store)
    if action == 'resume' and view['state'] == 'running':
        from . import autonomy
        # A running run's resume acknowledges a wait only the operator can judge (repeated launch failures,
        # a reported credential or batch-job condition); with none open there is nothing to resume.
        if not any(w.get('code') in autonomy.ACKNOWLEDGED for w in autonomy.open_waits(store)):
            raise common.AuthorityRefused('the run is running; there is nothing to resume')
    body = {'schema': common.SCHEMA, 'schema_version': 1, 'uid': common.uid(), 'run_id': common.run_id(store),
            'kind': action, 'decision': 'confirm', 'option': None, 'comment': None, 'request': None,
            'subject': {'run_id': common.run_id(store), 'previous_control': view['record']},
            'subject_sha256': None, 'bounds': {}, 'source': source, 'label': label, 'evidence': evidence,
            'reason': reason.strip(), 'mode_record': None, 'supersedes': view['record'],
            'authorizes_effects': action == 'resume' and label == common.OPERATOR_COMMAND, 'review_credit': False,
            'human_identity_authenticated': False, 'time_ns': common.now_ns()}
    body['subject_sha256'] = common.digest(body['subject'])
    return common.append(store, common.AUTHORITY, body)
