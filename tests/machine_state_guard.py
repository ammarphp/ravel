"""Detect a test that wrote into the account's real machine-state directory.

RAVEL keeps machine-wide state (the native-job lease, its fence, the exposure ledger and each
run's custody ledgers) in one fixed per-user directory. Every test runs in its own marked
test lock domain, handed to child processes as a validated grant (``machine_lease.child_env``);
a child process started without it resolves the account's directory instead. ``tests/conftest.py`` runs this check after each test.

The directory is shared with every real run and every other session on the machine, so a
change alone proves nothing about this test. The check stamps the whole tree before a test,
finds every entry that is new or different afterwards, and reports the ones it can tie to
this session: a custody store keyed by a run below one of the session's temporary roots, a
run-index binding of such a run, and any other changed file (a lease record, a fence row, an
exposure ledger) that names one of those roots or this process.
"""
import hashlib
import json
import os
from pathlib import Path
import re

# Temporary directories this process made outside pytest's base directory (``tempfile.mkdtemp``
# and everything built on it); ``tests/conftest.py`` records them for the whole session.
TEMP_ROOTS = []
_MAX_TEXT = 4 * 1024 ** 2


def account_machine_dir():
    """The account's real machine-state directory, from the password database as machine_lease resolves it."""
    import pwd
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/state/ravel/machine"


def tree_stamp(real):
    """``{relative path: (mtime_ns, size)}`` for every file and directory below ``real``.

    An appended ledger changes its own size and time and nothing above it, so the whole tree
    is stamped, not its top level.
    """
    real = Path(real)
    stamps, pending = {}, [real]
    while pending:
        folder = pending.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            stamps[os.path.relpath(entry.path, real)] = (stat.st_mtime_ns, stat.st_size)
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
    return stamps


def changed_entries(before, after):
    """Relative paths that are new or carry another time or size than in ``before``."""
    return sorted(rel for rel, stamp in after.items() if before.get(rel) != stamp)


def _run_digests(roots, depth):
    """Custody-store keys of every directory below ``roots`` (a store is keyed by its run's resolved path)."""
    found = {}
    pending = [(Path(root).resolve(), 0) for root in roots]
    while pending:
        path, level = pending.pop()
        found[hashlib.sha256(str(path).encode()).hexdigest()[:32]] = path
        if level < depth:
            try:
                pending.extend((Path(e.path), level + 1) for e in os.scandir(path) if e.is_dir(follow_symlinks=False))
            except OSError:
                continue
    return found


def _bindings(index, roots):
    leaks = []
    if index.is_file():
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                bound = Path(json.loads(line)["record"]["path"])
            except (ValueError, KeyError, TypeError):
                continue
            if any(bound == root or root in bound.parents for root in roots):
                leaks.append(f"{index} (binding of {bound})")
    return leaks


def machine_state_leaks(real, roots, *, depth=4):
    """Custody stores under machine-state directory ``real`` that belong to a run below ``roots``.

    A run's store is keyed by the digest of its resolved path, or bound to that path in the
    run index. Only entries tied to ``roots`` are reported, so the records of real runs and of
    other sessions on this machine never count.
    """
    store = Path(real) / "rdj"
    if not store.is_dir():
        return []
    roots = [Path(r).resolve() for r in roots]
    leaks = [f"{store / key} (custody of {path})" for key, path in sorted(_run_digests(roots, depth).items())
             if (store / key).exists()]
    return leaks + _bindings(store / "runs.jsonl", roots)


def leaks_since(real, before, roots, *, pids=(), depth=5):
    """What this session wrote below ``real`` since the stamp ``before``; empty when nothing is tied to it.

    ``roots`` are the session's temporary roots (pytest's base directory and ``TEMP_ROOTS``);
    ``pids`` are this session's own processes. Entries that changed for another run or session
    are left alone.
    """
    real = Path(real)
    changed = changed_entries(before, tree_stamp(real))
    if not changed:
        return []
    roots = [Path(r).resolve() for r in roots]
    leaks = []
    stores = {Path(rel).parts[1] for rel in changed
              if Path(rel).parts[0] == "rdj" and len(Path(rel).parts) > 1 and Path(rel).parts[1] != "runs.jsonl"}
    if stores:
        owned = _run_digests(roots, depth)
        leaks += [f"{real / 'rdj' / key} (custody of {owned[key]})" for key in sorted(stores & set(owned))]
    if os.path.join("rdj", "runs.jsonl") in changed:
        leaks += _bindings(real / "rdj" / "runs.jsonl", roots)
    names = [str(root) for root in roots]
    for rel in changed:
        path = real / rel
        if Path(rel).parts[0] == "rdj" or not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > _MAX_TEXT:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        named = next((name for name in names if name in text), None)
        if named is not None:
            leaks.append(f"{path} (names {named})")
        elif any(int(found) in pids for found in re.findall(r'"pid"\s*:\s*(\d+)', text)):
            leaks.append(f"{path} (names a process of this session)")
    return leaks
