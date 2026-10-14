"""Read-only world commitments over an explicit journal/receipt/input population.

The controller supplies the complete binding list. Unbound workspace files,
clock time and file metadata never enter the commitment. Workers receive the
returned value as input; this module provides no mutation or publishing API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def read_bound(root, relative):
    """Read confined regular bytes once; the caller hashes that same snapshot."""
    if not isinstance(relative, str):
        raise ValueError('bound input path must be a string')
    name = PurePosixPath(relative)
    if not relative or name.is_absolute() or '..' in name.parts or name.as_posix() != relative or relative == '.':
        raise ValueError('bound input must be a canonical run-relative path')
    root = Path(root).resolve()
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('bound input must be a confined regular file: ' + relative)
    raw = path.read_bytes()
    return raw, hashlib.sha256(raw).hexdigest()


def digest(root, bound_inputs):
    """Return a deterministic content commitment, independent of binding order.

    Bind the controller's journal, resource state, execution receipts and every
    worker input explicitly. This is a content digest, not a scientific verdict.
    """
    names = list(bound_inputs)
    if any(not isinstance(name, str) for name in names) or len(names) != len(set(names)):
        raise ValueError('world bindings require unique path strings')
    bindings = [{'path': name, 'sha256': read_bound(root, name)[1]} for name in sorted(names)]
    value = {'schema_version': 1, 'kind': 'world-digest', 'bound_inputs': bindings}
    return {**value, 'sha256': hashlib.sha256(encode(value)).hexdigest()}
