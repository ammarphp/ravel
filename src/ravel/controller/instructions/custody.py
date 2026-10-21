"""Read-only instruction evidence resolver over controller-held attempt observations.

The step controller records worker-session, step-attempt and worker-completion in RunStore and
copies observed output bytes to instruction-artifacts/<session>/<relative output path>.
Workers never supply this scope or write the store. This module reads it, checks current attempt
identity and recomputes packet, final-record and artifact validity before giving credit.
No filename list or caller-provided acknowledgement verdict grants custody.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import PurePosixPath
import re

from . import compiler

BINDING = ('run_id', 'step', 'attempt', 'manifest_sha256', 'packet_sha256')
_CURRENT = ContextVar('instruction_completion', default=None)


def _body(row):
    """Read a store envelope, retaining its controller-issued record identity."""
    if not isinstance(row, dict):
        raise ValueError('invalid controller record')
    if 'record' in row:
        if not isinstance(row['record'], dict) or not isinstance(row.get('id'), str):
            raise ValueError('invalid controller record envelope')
        return {**row['record'], 'id': row['id']}
    return row


def _read(store, kind, identity):
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(f'missing controller {kind} identity')
    try:
        row = store.read(kind, identity)
    except (AttributeError, KeyError, OSError, ValueError) as exc:
        raise ValueError(f'no controller {kind} record: {identity}') from exc
    if not isinstance(row, dict):
        raise ValueError(f'invalid controller {kind} record: {identity}')
    return _body(row)


def session_observation(store, session: str, manifest: dict) -> dict:
    """Validate a controller-held session against the current attempt and rebuilt packet."""
    from .delivery import check_packet, PacketRefused
    row = _read(store, 'worker-session', session)
    if any(row.get(k) in (None, '') for k in BINDING):
        raise ValueError('worker session lacks its run, step, attempt or instruction pins')
    if not isinstance(row['attempt'], int) or isinstance(row['attempt'], bool) or row['attempt'] < 1:
        raise ValueError('invalid worker attempt')
    if getattr(store, 'run_id', row['run_id']) != row['run_id']:
        raise ValueError('worker session belongs to a different run')
    # The current attempt of this seat: check-in seats share one step id and attempt, each with its own session.
    active = [r for r in map(_body, store.scan('step-attempt'))
              if r.get('step') == row['step'] and r.get('seat') == row.get('seat')]
    if not active or active[-1].get('session') != session or any(active[-1].get(k) != row[k] for k in BINDING):
        raise ValueError('worker session is not the current controller-observed attempt')
    if row['step'] != manifest.get('step') or row['manifest_sha256'] != manifest.get('sha256'):
        raise ValueError('worker session names a different step or manifest')
    try:
        # The packet is rebuilt under the budget the controller derived for this seat and held with it; the
        # rebuilt bytes must equal the observed packet, so a budget cannot change what was delivered.
        budget = row['packet'].get('budget')
        if budget is not None and (type(budget) is not dict or budget.get('kind') != 'instruction-packet-budget'
                                   or type(budget.get('packet_tokens')) is not int or budget['packet_tokens'] <= 0):
            raise ValueError('worker session packet budget is malformed')
        problems = check_packet(row['packet'], manifest, row['card'], row['step_spec'], row['inputs'],
                                **({'budget': budget} if budget is not None else {}))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('worker session lacks a valid observed packet') from exc
    if row['packet'].get('sha256') != row['packet_sha256']:
        problems.append('worker session packet pin differs')
    if problems:
        raise PacketRefused(problems)
    return row


def completion_observation(store, session: str, manifest: dict, completion_id: str | None = None) -> dict:
    observed = session_observation(store, session, manifest)
    matches = [r for r in map(_body, store.scan('worker-completion')) if r.get('session') == session]
    if len(matches) != 1:
        raise ValueError('exactly one controller-observed worker completion is required')
    completion = matches[0] if completion_id is None else _read(store, 'worker-completion', completion_id)
    if completion != matches[0] or any(completion.get(k) != observed[k] for k in BINDING):
        raise ValueError('worker completion differs from the current session binding')
    if not isinstance(completion.get('final_record'), dict) or not isinstance(completion.get('artifacts'), list):
        raise ValueError('worker completion lacks its observed final record or artifacts')
    return completion


def _relative(path):
    return (isinstance(path, str) and bool(path) and not PurePosixPath(path).is_absolute()
            and '\\' not in path and '#' not in path and all(p not in ('', '.', '..') for p in path.split('/')))


class CompletionScope:
    def __init__(self, store, session, completion_id):
        self.store, self.session, self.completion_id = store, session, completion_id
        self.completion, self.artifacts, self.cache = None, {}, {}

    def validate(self, manifest, record):
        self.cache, self.artifacts = {}, {}
        self.completion = completion_observation(self.store, self.session, manifest, self.completion_id)
        if compiler.digest_value(record) != compiler.digest_value(self.completion['final_record']):
            raise ValueError('final record differs from the controller-observed completion')
        for artifact in self.completion['artifacts']:
            path = artifact.get('path') if isinstance(artifact, dict) else None
            if not _relative(path) or not re.fullmatch(r'[0-9a-f]{64}', str(artifact.get('sha256', ''))):
                raise ValueError('invalid controller-observed artifact descriptor')
            if path in self.artifacts:
                raise ValueError('duplicate controller-observed artifact path')
            self.artifacts[path] = artifact

    def read(self, path):
        if path not in self.artifacts:
            raise ValueError('names no controller-observed output in this attempt')
        if path not in self.cache:
            if not _relative(self.session):
                raise ValueError('invalid controller session path')
            root = self.store.path()
            target = self.store.path('instruction-artifacts', self.session, *path.split('/'))
            if root not in target.parents or any(p.is_symlink() for p in (target, *target.parents)
                                                if p == root or root in p.parents) or not target.is_file():
                raise ValueError('controller-observed output is missing or is not a regular file')
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != self.artifacts[path]['sha256']:
                raise ValueError('controller-observed output bytes changed')
            self.cache[path] = raw
        return self.cache[path]


@contextmanager
def observed_completion(store, *, session: str, completion_id: str | None = None):
    """Root the unchanged check_ack(..., outputs: list[str]) API in controller custody.

    This is a controller-only call. Validation happens at each check, including re-reading
    the active attempt; nested scopes restore the previous scope even on failure.
    """
    scope = CompletionScope(store, session, completion_id)
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        _CURRENT.reset(token)


def current_scope():
    return _CURRENT.get()


def json_document(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('ambiguous duplicate JSON member')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)
