"""Shared canonical-JSON, hashing and immutable-write helpers for the evaluation harness.

Every module that hashes or persists harness records uses these functions so that a
digest computed by the coordinator, the broker and the evaluator agree byte for byte.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import tempfile
from pathlib import Path


class ContractError(ValueError):
    """A harness record, file or request violates its declared contract."""


def require(condition, message):
    if not condition:
        raise ContractError(message)


def canonical_bytes(value) -> bytes:
    """Canonical JSON bytes: sorted keys, no whitespace, no NaN/Infinity, UTF-8.

    This is the same serialization as ``experiment.digest`` so harness digests of v1
    objects equal the registry's own digests.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False,
                      ensure_ascii=True).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def strict_loads(text):
    """Parse JSON rejecting duplicate keys and NaN/Infinity (mirrors experiment.load_json)."""
    def object_from_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ContractError(f"nonfinite JSON constant: {value}")

    def finite_float(value):
        number = float(value)
        require(math.isfinite(number), f"JSON number overflows to a nonfinite float: {value}")
        return number

    return json.loads(text, object_pairs_hook=object_from_pairs, parse_constant=invalid_constant,
                      parse_float=finite_float)


def strict_load(path):
    return strict_loads(Path(path).read_text())


def is_sha256(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def finite_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def atomic_write_bytes(path, data: bytes, *, mode=0o644):
    """Write via a same-directory temporary file, fsync, then rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path, value, *, mode=0o644):
    atomic_write_bytes(path, json.dumps(value, indent=1, sort_keys=True, allow_nan=False).encode() + b"\n",
                       mode=mode)


def write_once(path, data: bytes, *, mode=0o444):
    """Create a new immutable file; refuse to overwrite anything that already exists."""
    path = Path(path)
    require(not path.exists() and not path.is_symlink(), f"refusing to overwrite {path}")
    atomic_write_bytes(path, data, mode=mode)


def append_jsonl(path, record):
    """Append one canonical JSON line and fsync; the journal is append-only."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_bytes(record) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(path):
    """Return (records, error). A torn or malformed trailing line is reported, not hidden."""
    records, error = [], None
    path = Path(path)
    if not path.exists():
        return records, None
    for number, raw in enumerate(path.read_bytes().split(b"\n"), start=1):
        if not raw:
            continue
        try:
            records.append(strict_loads(raw.decode()))
        except (UnicodeDecodeError, ValueError) as exc:
            error = f"line {number}: {exc}"
            break
    return records, error


def make_read_only(root):
    """Remove write permission from every file and directory under root (not a custody proof)."""
    root = Path(root)
    for current, dirs, files in os.walk(root, topdown=False):
        for name in files:
            p = Path(current) / name
            if not p.is_symlink():
                p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        Path(current).chmod(Path(current).stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def tree_manifest(root):
    """Sorted list of {path, sha256, bytes} for every regular file under root.

    Symlinks and special files are rejected: a sealed evidence tree contains only
    regular files so its manifest digest identifies its content.
    """
    root = Path(root)
    entries = []
    for current, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            p = Path(current) / name
            info = p.lstat()
            require(stat.S_ISREG(info.st_mode), f"not a regular file: {p.relative_to(root)}")
            entries.append({"path": p.relative_to(root).as_posix(), "sha256": sha256_file(p),
                            "bytes": info.st_size})
        for name in dirs:
            require(not (Path(current) / name).is_symlink(), f"symlinked directory: {name}")
    return sorted(entries, key=lambda e: e["path"])
