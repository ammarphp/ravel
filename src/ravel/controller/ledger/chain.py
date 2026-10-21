"""Ledger events in the run store: append-only, hash-chained, stamped by the controller's clock.

Each event is a ``ledger-entry.v1`` record ``{schema, seq, prev, body, sha256}`` appended to the store's
``ledger`` kind. ``sha256`` covers the canonical JSON of the other four fields; ``prev`` is the previous event's
``sha256`` (64 zeros for the first). The chain is verified independently of the store's own chaining, so a store
that adds bookkeeping fields to a record (or wraps it) does not affect it, and an edited, removed, reordered or
inserted event is detected. A complete rewrite by a process that can write the store is outside what a hash chain
can show; the store lies outside every sandbox and the receipt carries the head digest (CONTROLLER-SPEC 2.2).
Time comes from ``time.time_ns``; no environment variable sets it.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from threading import local as _thread_state
import time

KIND = 'ledger'
EVENT_SCHEMA = 'ledger-entry.v1'
GENESIS = '0' * 64
FIELDS = ('schema', 'seq', 'prev', 'body')
MAX_EVIDENCE_BYTES = 65536


class LedgerError(RuntimeError):
    """A ledger operation was refused. ``code`` names the refusal for callers and receipts."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def json_safe(value, path='$') -> None:
    """Refuse values a JSON round trip would change (tuples, non-string keys, NaN, objects)."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise LedgerError('evidence_invalid', f'{path} is not a finite number')
        return
    if type(value) is list:
        for i, item in enumerate(value):
            json_safe(item, f'{path}[{i}]')
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise LedgerError('evidence_invalid', f'{path} has a non-string key {key!r}')
            json_safe(item, f'{path}.{key}')
        return
    raise LedgerError('evidence_invalid', f'{path} holds a {type(value).__name__}, which is not JSON data')


def clock() -> int:
    return time.time_ns()


def seal(seq: int, prev: str, body: dict) -> dict:
    record = {'schema': EVENT_SCHEMA, 'seq': seq, 'prev': prev, 'body': body}
    record['sha256'] = digest(record)
    return record


def verify(records) -> tuple[list[dict], str | None]:
    """(verified events in order, error). Events after the first fault are not returned."""
    try:
        ordered = sorted(records, key=lambda r: r['seq'] if type(r.get('seq')) is int else -1)
    except (AttributeError, TypeError):
        return [], 'a ledger record is not an object'
    return verify_tail(ordered, 0, GENESIS)


def verify_tail(ordered, start: int, prev: str) -> tuple[list[dict], str | None]:
    """Verify records that must continue a chain at sequence ``start`` after the event digest ``prev``."""
    events, problems = [], None
    for offset, record in enumerate(ordered):
        index = start + offset
        if not isinstance(record, dict):
            problems = f'ledger record {index} is not an object'
            break
        own = {k: record.get(k) for k in FIELDS}
        if own['schema'] != EVENT_SCHEMA or type(own['seq']) is not int or not isinstance(own['body'], dict):
            problems = f'ledger record {index} is not a {EVENT_SCHEMA} event'
            break
        if own['seq'] != index:
            problems = f'ledger event {own["seq"]} is out of sequence (expected {index}): an event is missing or repeated'
            break
        if own['prev'] != prev:
            problems = f'ledger event {index} does not chain to its predecessor'
            break
        try:
            computed = digest(own)
        except (TypeError, ValueError):
            problems = f'ledger event {index} is not canonical JSON'
            break
        if record.get('sha256') != computed:
            problems = f'ledger event {index} was altered after it was written'
            break
        events.append({**own, 'sha256': computed})
        prev = computed
    return events, problems


def unwrap(entry):
    """The record a store entry carries: a store may wrap it as ``{id, kind, seq, ..., record}`` or return it bare."""
    if isinstance(entry, dict) and 'schema' not in entry and isinstance(entry.get('record'), dict):
        return entry['record']
    return entry


def scan(store) -> list:
    records = store.scan(KIND)
    if not isinstance(records, list):
        raise LedgerError('store_invalid', 'the run store returned no record list for the ledger')
    return [unwrap(entry) for entry in records]


def append(store, record: dict) -> str:
    return store.append(KIND, record)


# ---- locking -------------------------------------------------------------------------------------------

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_HELD = _thread_state()   # per-thread re-entry counts


LOCK = 'ledger.lock'


def store_key(store) -> str:
    """The run's lock file path: one key per store whatever object opened it."""
    path = getattr(store, 'path', None)
    if callable(path):
        target = Path(path(LOCK))
        return str(Path(os.path.realpath(target.parent)) / target.name)
    return f'object:{id(store)}'


@contextmanager
def locked(store):
    """Serialise ledger reads and transactions: a thread lock plus a process-shared file lock.

    Re-entrant in one thread: only the outermost holder takes the file lock.
    """
    key = store_key(store)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_HELD, 'keys', None)
        if held is None:
            held = _HELD.keys = {}
        if held.get(key):
            held[key] += 1
            try:
                yield
            finally:
                held[key] -= 1
            return
        handle = None
        path = getattr(store, 'path', None)
        if callable(path):
            try:
                import fcntl
                target = Path(key)
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                handle = os.open(target, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                fcntl.flock(handle, fcntl.LOCK_EX)
            except ImportError:  # pragma: no cover - process safety is required on every supported host
                raise LedgerError('store_unavailable', 'the ledger requires process-shared file locking') from None
            except OSError as exc:
                if handle is not None:
                    os.close(handle)
                raise LedgerError('store_unavailable', f'the ledger lock cannot be taken: {exc}') from None
        held[key] = 1
        try:
            yield
        finally:
            held[key] = 0
            if handle is not None:
                os.close(handle)
