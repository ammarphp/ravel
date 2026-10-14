"""Evaluator process memory: blinded artifacts are never persisted on disk.

A qualified, producer-denied evaluator store may replace this in a future integration.
Until then a process exit loses sealed artifacts and replay fails closed.
No permission bits or directory names are treated as an isolation boundary.
"""
import hashlib
import io
import json
import secrets
import numpy as np

_STORE = {}
_BYTES = 0
LIMIT = 256*1024**2


def put(value, *, arrays=False):
    global _BYTES
    if arrays:
        buf=io.BytesIO(); np.savez(buf,**value); raw=buf.getvalue()
    else: raw=json.dumps(value,sort_keys=True,allow_nan=False).encode()
    if _BYTES+len(raw)>LIMIT: raise ValueError('sealed memory ceiling exhausted; qualified evaluator-private store required')
    path='sealed://'+secrets.token_hex(24)
    _STORE[path]=raw; _BYTES+=len(raw)
    return {'path':path,'sha256':hashlib.sha256(raw).hexdigest()}


def read(pin):
    raw=_STORE.get(pin['path'])
    if raw is None: raise ValueError('sealed artifacts unavailable: durable evaluator custody required; receipt cannot validate')
    if hashlib.sha256(raw).hexdigest()!=pin['sha256']: raise ValueError('sealed artifact pin changed')
    return raw


def discard(pins):
    global _BYTES
    for pin in pins:
        raw=_STORE.pop(pin['path'],None)
        if raw is not None: _BYTES-=len(raw)
