"""Local diagnostic records. RunStore owns their identity, order and custody."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path

EXPECTED = 'diagnostics-expected'
CONFIG = 'diagnostics-config'
TRANSCRIPT = 'diagnostics-transcript'
FAULT = 'diagnostics-fault'
FAULT_RESULT = 'diagnostics-fault-result'
# These are execution boundaries, rather than planning or journal writes.
EFFECT_KINDS = ('step-dispatch', 'step-launch', 'launch', 'launch-effect', 'broker-call',
                'broker-calls', 'broker-event', 'broker-evidence', 'broker-model-call',
                'broker', 'broker-reservations', 'broker-receipt',
                'step-observation', 'step-outcome', 'step-result', 'worker-start',
                'worker-session', 'worker-completion', FAULT)


class DiagnosticsRefused(ValueError):
    """Required evidence or a prospective diagnostic configuration is missing."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value):
    return sha256(canonical(value)).hexdigest()


def seal(body):
    body = deepcopy(body)
    body['sha256'] = digest(body)
    return body


def verify(body):
    if body.get('sha256') != digest({k: v for k, v in body.items() if k != 'sha256'}):
        raise DiagnosticsRefused('diagnostic content digest mismatch')


def entries(store, kind):
    """Use the binding journal envelopes; never silently accept worker-authored bodies."""
    result = store.scan(kind)
    for row in result:
        if not isinstance(row.get('record'), dict) or not row.get('id') or type(row.get('seq')) is not int:
            raise DiagnosticsRefused('invalid RunStore journal envelope: ' + kind)
    return result


def latest(store, kind):
    found = entries(store, kind)
    return deepcopy(found[-1]['record']) if found else None


def before_effects(store):
    for kind in EFFECT_KINDS:
        if entries(store, kind):
            raise DiagnosticsRefused('diagnostics must be pinned before the first effect: ' + kind)


def pinned(store):
    found = entries(store, EXPECTED)
    if len(found) != 1:
        raise DiagnosticsRefused('exactly one expected-run pin is required')
    pin = found[0]
    verify(pin['record'])
    for kind in EFFECT_KINDS:
        if any(row['seq'] < pin['seq'] for row in entries(store, kind)):
            raise DiagnosticsRefused('expected-run pin follows an execution effect')
    return deepcopy(pin)


def pin_expected(store, expected):
    """Append the immutable expectation before dispatch. Reopening the same pin is harmless."""
    verify(expected)
    if expected.get('schema') != 'expected-run.v1':
        raise DiagnosticsRefused('expected-run.v1 required')
    found = entries(store, EXPECTED)
    if found:
        pin = pinned(store)
        if pin['record'] != expected:
            raise DiagnosticsRefused('expected run is already pinned; a revision needs its own prospective run')
        return pin['id']
    before_effects(store)
    return store.append(EXPECTED, deepcopy(expected))


def require_expected(store, plan_sha256=None):
    pin = pinned(store)
    if plan_sha256 is not None and pin['record']['plan_sha256'] != plan_sha256:
        raise DiagnosticsRefused('execution plan differs from the expected-run pin')
    return pin['id']


def private_file(store, parts, content):
    """Exclusive 0600 artifact under RunStore, with no caller-selected output path."""
    path = Path(store.path(*parts))
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Store.path refuses traversal; this also refuses a symlink at the final name.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return path
