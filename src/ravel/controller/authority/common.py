"""Shared vocabulary of the controller authority service.

Authority for a controller-owned run comes only from sources outside the workers' reach: the
operator's configuration and authenticated operator commands. The controller captures
terminal responses as unattested evidence, never as authenticated human approval. Every decision is an ``authority-record.v1`` in the run's
protected store, stamped with the controller clock. Files in the run directory are never read
as authority. Labels state the evidence, never an identity: no record authenticates a person.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import secrets
import time

SCHEMA = 'authority-record.v1'
REQUEST_SCHEMA = 'authority-request.v1'
MODE_SCHEMA = 'operating-mode.v1'
OBSERVATION_SCHEMA = 'stop-observation.v1'

# Store kinds (P01 RunStore.append/read/scan).
AUTHORITY = 'authority'
REQUESTS = 'authority-request'
MODE = 'mode'
OBSERVATIONS = 'stop-observation'

# Record kinds. Check-in decisions authorize effects; the final disposition, steering and the
# controls never install a plan or credit review.
KINDS = ('approve_plan', 'go', 'deviation', 'final', 'r3_action', 'escalation', 'steering',
         'stop', 'pause', 'resume', 'revoke')
ALIASES = {'ci1': 'approve_plan', 'checkin1': 'approve_plan', 'ci2': 'go', 'checkin2': 'go',
           'ci3': 'final', 'checkin3': 'final', 'deviation_checkin': 'deviation', 'r3': 'r3_action'}
CONTROLS = ('stop', 'pause', 'resume', 'revoke')
CHECKINS = ('approve_plan', 'go', 'deviation', 'final', 'escalation')

# Decisions a record can carry, per kind. ADJUST, REVISE and REJECT never authorize an effect.
DECISIONS = {
    'approve_plan': ('approve', 'adjust', 'reject'),
    'go': ('go', 'adjust', 'stop'),
    'deviation': ('approve', 'reject'),
    'final': ('accept', 'rework', 'reject'),
    'r3_action': ('approve', 'reject', 'default'),
    'escalation': ('answer', 'reject', 'default'),
    'steering': ('approve', 'reject'),
    'stop': ('confirm',), 'pause': ('confirm',), 'resume': ('confirm',), 'revoke': ('confirm',),
}
POSITIVE = {'approve_plan': 'approve', 'go': 'go', 'deviation': 'approve', 'final': 'accept',
            'r3_action': 'approve', 'escalation': 'answer', 'steering': 'approve'}

# Labels by evidence (CONTROLLER-SPEC 10.1). ``terminal_operator_unattested`` is the legacy label.
TERMINAL = 'physicist_terminal_response'
MACHINE = 'operator_configured_machine'
DELEGATED = 'delegated_machine'
OPERATOR_COMMAND = 'operator_command'
LEGACY_TERMINAL = 'terminal_operator_unattested'
LABELS = (TERMINAL, MACHINE, DELEGATED, OPERATOR_COMMAND)

MODES = ('physicist-in-the-loop', 'autonomous')
R3_POLICIES = ('escalate_and_wait', 'conservative_default')


class AuthorityRefused(ValueError):
    """No authority was granted; nothing was recorded as approval."""


def now_ns():
    """The controller clock. No environment variable or caller value changes it."""
    return time.time_ns()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def nonce(groups=2, size=4):
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return '-'.join(''.join(secrets.choice(alphabet) for _ in range(size)) for _ in range(groups))


def uid():
    return secrets.token_hex(16)


def kind_of(kind):
    """The record kind for a requested kind or its check-in alias."""
    value = ALIASES.get(kind, kind)
    if value not in KINDS:
        raise ValueError(f'unknown authority kind {kind!r}')
    return value


# ------------------------------------------------------------------ store access

def _unwrap(entry):
    """``(store id or None, body)`` from a scanned or read store entry.

    Bodies written here always carry ``schema`` and ``uid``; a store that wraps them under
    ``record`` or adds its own ``id`` is read either way.
    """
    if not isinstance(entry, dict):
        raise ValueError('store entry must be an object')
    record = entry.get('record')
    if isinstance(record, dict) and 'schema' in record and 'schema' not in entry:
        return entry.get('id'), record
    body = {k: v for k, v in entry.items() if k != 'id'} if 'schema' in entry and 'id' in entry else entry
    return entry.get('id'), body


def _row(identifier, body):
    return {**deepcopy(body), 'id': identifier}


def scan(store, kind, schema=None):
    """Authenticate every record, its store binding, order and external append anchor."""
    from . import issuer
    context = issuer.context(store, kind)
    entries = store.scan(kind)
    anchors = issuer.journal(context)
    if len(entries) != len(anchors):
        raise AuthorityRefused('authority store membership differs from the issuer journal')
    rows = []
    for entry, anchor in zip(entries, anchors):
        identifier, body = _unwrap(entry)
        issuer.authenticate(body, context)
        if (anchor['sha256'] != digest(body) or anchor['uid'] != body.get('uid')
                or (identifier is not None and identifier != anchor['id'])):
            raise AuthorityRefused('authority record order or store id differs from issuer custody')
        if schema is not None and body.get('schema') != schema:
            raise AuthorityRefused('authority record has an unexpected schema')
        rows.append(_row(anchor['id'], body))
    return rows


def read(store, kind, record_id, schema=None):
    """Read a canonical RunStore id, authenticating the whole decision history first."""
    for row in scan(store, kind, schema):
        if record_id == row['id']:
            _, body = _unwrap(store.read(kind, record_id))
            if digest(body) != digest({k: v for k, v in row.items() if k != 'id'}):
                raise AuthorityRefused('RunStore read disagrees with authenticated scan')
            return row
    raise KeyError(f'no {kind} record {record_id!r} in the controller store')


def append(store, kind, body):
    """Issue a MACed record and anchor the actual id returned by RunStore.append."""
    from . import issuer
    from ravel.workflow.state_io import file_lock
    if type(body.get('uid')) is not str or body.get('run_id') != run_id(store):
        raise AuthorityRefused('a controller body must bind its uid and run')
    context = issuer.context(store, kind)
    issuer._key()
    with file_lock(issuer.journal_path(context).with_suffix('.lock')):
        scan(store, kind)
        anchors = issuer.journal(context)
        issued = issuer.seal(body, context)
        identifier = store.append(kind, deepcopy(issued))
        if type(identifier) is not str or not identifier:
            raise AuthorityRefused('RunStore.append returned no canonical id')
        anchors.append({'id': identifier, 'uid': body['uid'], 'sha256': digest(issued)})
        issuer.anchor(context, anchors)
        return _row(identifier, issued)


def run_id(store):
    value = getattr(store, 'run_id', None)
    if isinstance(value, str) and value:
        return value
    return store.path().name


# ------------------------------------------------------------------ run ownership (P01)

_OWNERSHIP = None  # P01's controller_owned, or False when the controller core is not installed


def owned_run(run_dir):
    """The controller run id when the controller owns ``run_dir``; None for every other run.

    Without the controller core installed no run can be controller-owned. Any other import
    failure propagates: a broken controller never makes a run look legacy.
    """
    global _OWNERSHIP
    if _OWNERSHIP is None:
        try:
            from ravel.controller.store import controller_owned
        except ModuleNotFoundError as exc:
            if exc.name not in ('ravel.controller.store', 'ravel.controller'):
                raise
            _OWNERSHIP = False
        else:
            _OWNERSHIP = controller_owned
    if _OWNERSHIP is False:
        return None
    from pathlib import Path
    return _OWNERSHIP(Path(run_dir))


def open_store(identifier):
    """P01's store of an existing controller run, under the operator-configured store root.

    A mistyped run id never creates a store: the run's directory must already exist.
    """
    from pathlib import Path
    import re
    if type(identifier) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', identifier):
        raise AuthorityRefused('a controller run id is a plain name')
    from .operator import operator_config
    root = Path(operator_config()['store_root'])
    if not (root / identifier).is_dir():
        raise AuthorityRefused(f'no controller run {identifier!r} under the configured store root {root}')
    try:
        from ravel.controller.store import RunStore
    except ModuleNotFoundError as exc:
        if exc.name not in ('ravel.controller.store', 'ravel.controller'):
            raise
        raise AuthorityRefused('the controller core is not installed; no controller run can be opened') from None
    # The binding store takes the store root and keeps the run at ``root/run_id``.
    return RunStore(identifier, root=root)


def refuse_legacy(run_dir, action):
    """Refuse a legacy authority command for a controller-owned run (``NOT GOVERNED`` paths stay for others)."""
    identifier = owned_run(run_dir)
    if identifier is not None:
        raise AuthorityRefused(
            f'{action} is refused: run {identifier} is controller-owned, and its authority comes only from the '
            'controller (the physicist at the controller terminal, or the operator configuration and '
            '`ravel operator` commands). Nothing was recorded.')
