"""Immutable syntax facts, reused only for exactly equal source bytes.

The caller must read and authenticate the current file on every invocation.
This cache retains no paths, file metadata, pins, admission or execution proof.
It never returns a shared AST or mutable catalogue. Large sources are parsed
normally without caching; these limits bound reuse, not source admission.
"""
from __future__ import annotations

import ast
from collections import OrderedDict
import sys
from threading import RLock

CACHE_ENTRIES = 128
MAX_CACHED_SOURCE_BYTES = 262_144
MAX_CACHE_BYTES = 16_777_216
_CACHE = OrderedDict()
_CACHE_BYTES = 0
_LOCK = RLock()


def _derive(raw):
    tree = ast.parse(raw.decode('utf-8'))
    functions = tuple(sorted(n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))))
    constants = tuple(sorted({n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and type(n.value) is str}))
    return ast.get_docstring(tree) or '', functions, constants


def _cached(raw):
    global _CACHE_BYTES
    with _LOCK:
        if raw in _CACHE:
            result, _ = _CACHE[raw]
            _CACHE.move_to_end(raw)
            return result
    result = _derive(raw)
    # Charge every retained object, conservatively including repeated strings
    # and a per-entry allowance for the key/value/OrderedDict bookkeeping.
    charge = sys.getsizeof(raw) + sys.getsizeof(result) + 1024
    charge += sys.getsizeof(result[0])
    charge += sum(sys.getsizeof(values) + sum(sys.getsizeof(v) for v in values)
                  for values in result[1:])
    if charge > MAX_CACHE_BYTES:
        return result
    with _LOCK:
        if raw in _CACHE:
            result, _ = _CACHE[raw]
            _CACHE.move_to_end(raw)
            return result
        while _CACHE and (len(_CACHE) >= CACHE_ENTRIES
                          or _CACHE_BYTES + charge > MAX_CACHE_BYTES):
            _, (_, old_charge) = _CACHE.popitem(last=False)
            _CACHE_BYTES -= old_charge
        _CACHE[raw] = result, charge
        _CACHE_BYTES += charge
    return result


def facts(raw, *, filename='<unknown>'):
    """Return immutable docstring/function/string facts for current UTF-8 bytes.

    Exceptions are not cached and preserve the actual caller's path. At most
    At most 128 keys of at most 256 KiB share a 16 MiB retained-object charge
    budget. Larger inputs use the same parser without caching.
    """
    if type(raw) is not bytes:
        raise TypeError('syntax facts require exact immutable source bytes')
    try:
        return _cached(raw) if len(raw) <= MAX_CACHED_SOURCE_BYTES else _derive(raw)
    except SyntaxError as exc:
        exc.filename = str(filename)
        raise
    except UnicodeDecodeError as exc:
        exc.add_note('source path: ' + str(filename))
        raise
