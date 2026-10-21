"""The protected run store: the controller's records, checkpoints and custody for one run.

A controller run keeps two directories. The run directory holds artifacts and reading copies
(``request.txt``, ``inputs/``, step outputs, ``delivery/``). The store holds everything that
decides what happens next: the request bytes and their pins, the append-only record journal
(ledger, authority, custody, budgets, judgments, receipts), the graph checkpoints and the stop
flag. The store lies outside the run directory and outside every sandbox mount, under the root
the operator configured (``authority.operator_config()["store_root"]``; by default
``~/.local/state/ravel-controller/runs`` of the account in the password database). Directories are
mode 0700 and files 0600. ``RAVEL_STATE_DIR``, ``RAVEL_WORK_ROOT`` and ``HOME`` never move it
(switch SW20).

Records are appended to one hash chain (``journal.jsonl``), stamped with the controller's own
clock (``time.time_ns``; no clock variable is read) and identified as ``<kind>-<seq>-<digest>``.
An edited, reordered, truncated or inserted line is detected on the next read (``StoreTampered``).

A run directory is bound to its store at creation: the store records the directory's absolute
path, device and inode, writes a marker (``controller-run.json``) into the directory and an index
entry under the store root. ``controller_owned`` reports the run id for any path inside a run
directory or a run's store, through symlink aliases, so the command policy can refuse
state-writing commands for it. ``RunStore.check_binding`` refuses a copied, moved or replaced
directory (C41); resume never reinitializes a run.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import sqlite3
import stat
import threading
import time

RUN_MARKER = "controller-run.json"
DEFAULT_RELATIVE = ".local/state/ravel-controller/runs"  # the authority service keeps operator/ beside runs/
RUN_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
KIND = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
PART = re.compile(r"[A-Za-z0-9_.:@+=-]{1,200}\Z")
# Environment variables that relocate legacy custody; the controller store never reads them (SW20).
IGNORED_ENVIRONMENT = ("RAVEL_STATE_DIR", "RAVEL_WORK_ROOT")
GENESIS = "0" * 64
JOURNAL = "journal.jsonl"
JOURNAL_LOCK = "journal.lock"
HEAD = "head.json"
RUN = "run.json"
INDEX = "index"
BLOBS = "blobs"
GRAPH_SCOPE = "graph"
CHECKPOINTS = "framework/graphs.sqlite"  # the substrate's checkpoint file, inside the run's graph scope
SCHEMA_VERSION = 1

_STATES: dict = {}
_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


class StoreError(ValueError):
    """The store is absent, misplaced, unreadable or refuses the operation."""


class StoreTampered(StoreError):
    """The record journal does not verify: an edited, reordered, inserted or truncated record."""


class ControllerOwnershipUnknown(StoreError):
    """A controller-run marker that cannot be read: ownership is unknown, so every caller fails closed."""


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _line(entry):
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"


def _json_safe(value, path="$"):
    """Raise unless ``value`` is plain JSON: dicts with string keys, lists, strings, finite numbers."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise StoreError(f"{path} is not a finite number")
        return
    if type(value) is list:
        for i, item in enumerate(value):
            _json_safe(item, f"{path}[{i}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise StoreError(f"{path} has a non-string key")
            _json_safe(item, f"{path}.{key}")
        return
    raise StoreError(f"{path} holds {type(value).__name__}, which is not JSON")


# ---- where the store lives ----------------------------------------------------------------

def default_store_root():
    """``~/.local/state/ravel-controller/runs`` of this account, from the password database (not ``HOME``)."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / DEFAULT_RELATIVE


def _operator_config():
    from importlib import import_module
    try:
        authority = import_module(__package__ + ".authority")
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + ".authority":
            raise
        return {}  # the authority service is not installed: the built-in default applies
    config = authority.operator_config()
    return config if type(config) is dict else {}


def store_root():
    """The operator-configured store root, else the default. No environment variable moves it.

    The root is resolved once (the operator's configuration is trusted); every path below it is real.
    """
    configured = _operator_config().get("store_root")
    if configured in (None, ""):
        return Path(os.path.realpath(default_store_root()))
    if type(configured) is not str or not Path(configured).is_absolute():
        raise StoreError("the operator's store_root must be an absolute path")
    return Path(os.path.realpath(configured))


def protected_roots():
    """Paths no sandbox may mount or write: the store root (for the confined launcher, P05)."""
    return [store_root()]


def new_run_id():
    return time.strftime("run-%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4)


def _within(path, root):
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        return False


def _private_dir(path):
    """Create ``path`` (and missing parents) as 0700 directories owned by this account."""
    path = Path(path)
    missing = []
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            break
        missing.append(candidate)
    for candidate in reversed(missing):
        try:
            os.mkdir(candidate, 0o700)
        except FileExistsError:
            pass
        os.chmod(candidate, 0o700)
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise StoreError(f"store path {path} must be a directory, not a link")
    if info.st_uid != os.getuid():
        raise StoreError(f"store directory {path} belongs to another account")
    if info.st_mode & 0o077:
        if path in missing:
            os.chmod(path, 0o700)
        else:
            raise StoreError(f"store directory {path} is readable or writable by others (mode "
                             f"{oct(info.st_mode & 0o777)}); restore 0700")
    return path


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise StoreError("private file write made no progress")
        remaining = remaining[written:]


def _write_private(path, data, *, exclusive=False):
    """Write all bytes durably, publishing replacements atomically."""
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, data)
        os.fsync(fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    if exclusive:
        try:
            os.link(temporary, path, follow_symlinks=False)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        os.replace(temporary, path)
    _fsync_directory(path.parent)


class _JournalState:
    def __init__(self):
        self.entries = []
        self.by_id = {}
        self.by_kind = {}
        self.offset = 0
        self.head = GENESIS
        self.signature = None
        self.hasher = hashlib.sha256()
        self.snapshot_depth = 0


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _thread_lock(path):
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


class _FileLock:
    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        import fcntl
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        import fcntl
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)
        self.fd = None


# ---- the run store ------------------------------------------------------------------------

class RunStore:
    """One run's store at ``<store root>/<run_id>``: records, blobs, checkpoints and its binding.

    ``RunStore(run_id)`` opens (creating the private directory when absent) the store of a run
    under the operator-configured root; ``root`` names another store root (tests, the harness's
    trusted side). ``RunStore.create(run_dir)`` starts a controller run: it binds a new run
    directory to a new store. Records returned by ``read`` and ``scan`` are envelopes
    ``{id, kind, seq, time_ns, prev, digest, record, schema_version}``.
    """

    def __init__(self, run_id: str, *, root: Path | None = None):
        if type(run_id) is not str or not RUN_ID.fullmatch(run_id):
            raise StoreError(f"invalid run id {run_id!r}")
        base = Path(os.path.realpath(Path(root).expanduser())) if root is not None else store_root()
        self.run_id = run_id
        self.store_root = _private_dir(base)
        self.root = _private_dir(self.store_root / run_id)
        self._lock = _thread_lock(self.root)
        with self._lock:
            self._state = _STATES.setdefault(str(self.root), _JournalState())
        self._connections: list = []
        # Fresh handles may reuse parsed state only after checking all journal
        # bytes; the metadata-only fast path is never sufficient.
        self._needs_verify = self._state.signature is None

    # Keep the established private views available to controller tests and diagnostics.
    def _get_state(self):
        if not hasattr(self, "_state"):
            self._state = _JournalState()  # compatibility with isolated __new__ audit readers
        return self._state

    _entries = property(lambda self: self._get_state().entries,
                        lambda self, value: setattr(self._get_state(), "entries", value))
    _by_id = property(lambda self: self._get_state().by_id,
                      lambda self, value: setattr(self._get_state(), "by_id", value))
    _by_kind = property(lambda self: self._get_state().by_kind)
    _offset = property(lambda self: self._get_state().offset,
                       lambda self, value: setattr(self._get_state(), "offset", value))
    _head = property(lambda self: self._get_state().head,
                     lambda self, value: setattr(self._get_state(), "head", value))

    @contextmanager
    def _guard(self):
        with self._lock:
            if self._get_state().snapshot_depth:
                yield
            else:
                with _FileLock(self.root / JOURNAL_LOCK):
                    yield

    @contextmanager
    def snapshot(self):
        """Verify once and hold both locks for a group of indexed reads.

        Outside a snapshot every refresh streams a content fingerprint, because
        some filesystems can hide same-length edits behind unchanged timestamps.
        Cooperative writers cannot append during the snapshot; returned data is
        still copied. Full verify/recovery always reads the entire chain.
        """
        with self._guard():
            self._refresh()
            self._check_head()
            self._state.snapshot_depth += 1
            try:
                yield self
            finally:
                self._state.snapshot_depth -= 1

    # -- creation and binding --

    @classmethod
    def create(cls, run_dir, *, root=None, run_id=None, origin=None):
        """Create a controller run: a new run directory bound to a new store (refuses existing ones)."""
        named = Path(os.path.abspath(Path(run_dir).expanduser()))
        if named.exists() or named.is_symlink():
            raise StoreError(f"the run directory must be new: {named} exists")
        # The directory is bound by its real path: an alias that reaches it later resolves to it (C25).
        directory = Path(os.path.realpath(named.parent)) / named.name
        base = Path(os.path.realpath(Path(root).expanduser())) if root is not None else store_root()
        if _within(base, directory) or _within(directory, base):
            raise StoreError("the store and the run directory must not contain each other")
        from ravel.workflow.private_files import mkdir
        mkdir(named.parent)
        directory = Path(os.path.realpath(named.parent)) / named.name
        run_id = run_id or new_run_id()
        if (base / run_id).exists():
            raise StoreError(f"run {run_id} already has a store")
        store = cls(run_id, root=base)
        os.mkdir(directory, 0o700)
        info = os.stat(directory)
        record = {"schema_version": SCHEMA_VERSION, "kind": "controller-run", "run_id": run_id,
                  "run_dir": str(directory), "dev": info.st_dev, "ino": info.st_ino,
                  "store_root": str(store.store_root), "origin": deepcopy(origin) if origin is not None else None}
        identifier = store.append("run", record)
        envelope = store.read("run", identifier)
        _write_private(store.root / RUN, (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode(),
                       exclusive=True)
        index = _private_dir(store.store_root / INDEX)
        entry = {"run_id": run_id, "run_dir": str(directory), "dev": info.st_dev, "ino": info.st_ino}
        _write_private(index / f"path-{_path_key(directory)}.json", (json.dumps(entry, sort_keys=True) + "\n").encode())
        marker = {"schema_version": SCHEMA_VERSION, "kind": "controller-run-marker", "run_id": run_id,
                  "store_root": str(store.store_root), "run_record_sha256": envelope["digest"],
                  "note": "This run belongs to the RAVEL controller; its state lives in the store, not here."}
        _write_private(directory / RUN_MARKER, (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode(),
                       exclusive=True)
        return store

    @property
    def initialized(self):
        return bool(self.scan("run"))

    def run_record(self):
        """Current authenticated restoration binding, else the original run binding."""
        with self.snapshot():
            restored = self.latest("run-restoration")
            if restored is not None:
                return restored["record"]
            rows = self.scan("run")
            return rows[0]["record"] if rows else None

    @property
    def run_dir(self):
        record = self.run_record()
        return Path(record["run_dir"]) if record else None

    def check_binding(self, run_dir=None):
        """Problems that refuse resuming this run from ``run_dir`` (default: the bound directory)."""
        if (self.root / "RESTORE-FAILED").exists():
            return [f"run {self.run_id}: restoration failed; the partial store cannot resume"]
        if (self.root / "RESTORE-PENDING").exists():
            return [f"run {self.run_id}: restoration is incomplete; preserve the partial run and store "
                    "separately, then restore the verified bundle into the absent original paths"]
        record = self.run_record()
        if record is None:
            return [f"run {self.run_id} has no binding record in its store"]
        bound = Path(record["run_dir"])
        problems = []
        if run_dir is not None:
            named = Path(os.path.realpath(Path(run_dir).expanduser()))
            if named != Path(os.path.realpath(bound)):
                problems.append(f"{run_dir} is not the run's directory ({bound}); a copied or renamed run "
                                "directory is never resumed")
        if bound.is_symlink() or not bound.is_dir():
            problems.append(f"the run directory {bound} is missing or replaced by a link; the run was moved, "
                            "renamed or deleted")
            return problems
        info = os.stat(bound)
        if (info.st_dev, info.st_ino) != (record["dev"], record["ino"]):
            problems.append(f"the directory at {bound} is not the run's original directory (a copy or "
                            "replacement); its custody stays with the original")
        marker = bound / RUN_MARKER
        try:
            claim = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            claim = None
        if type(claim) is not dict or claim.get("run_id") != self.run_id:
            problems.append(f"the run directory's {RUN_MARKER} is missing or names another run")
        elif "identity" in record and claim.get("restoration_identity") != record["identity"]:
            problems.append(f"the run directory's {RUN_MARKER} does not match its restoration identity")
        return problems

    # -- records --

    def _accept(self, entry, size):
        self._entries.append(entry)
        self._by_id[entry["id"]] = entry
        self._by_kind.setdefault(entry["kind"], []).append(entry)
        self._head = entry["digest"]
        self._offset += size

    def _fresh(self):
        fresh = object.__new__(type(self))
        fresh.run_id, fresh.store_root, fresh.root = self.run_id, self.store_root, self.root
        fresh._state = _JournalState()
        return fresh

    def _refresh(self, *, recover_partial=False, force=False):
        """Fingerprint the verified prefix and parse only a fully validated new tail.

        Outside snapshots every prefix byte is checked, including when metadata
        is unchanged. New entries remain isolated until every complete tail line
        validates. Forced audit/recovery retains the full-chain parsing path.
        """
        if self._get_state().snapshot_depth and not force:
            return b""
        force = force or getattr(self, "_needs_verify", True)
        self._get_state()
        path = self.root / JOURNAL
        if not path.exists() and not path.is_symlink():
            if self._offset:
                raise StoreTampered(f"run {self.run_id}: the record journal disappeared")
            self._needs_verify = False
            return b""
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise StoreTampered(f"run {self.run_id}: the record journal is not a regular file")
        if not force:
            if info.st_size < self._offset:
                raise StoreTampered(f"run {self.run_id}: the record journal was truncated")
            fingerprint = hashlib.sha256()
            with path.open("rb") as stream:
                remaining = self._offset
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise StoreTampered(f"run {self.run_id}: the record journal was truncated")
                    fingerprint.update(chunk)
                    remaining -= len(chunk)
                data = stream.read()
            if _signature(os.lstat(path)) != _signature(info):
                raise StoreTampered(f"run {self.run_id}: the record journal changed during verification")
            if fingerprint.digest() != self._state.hasher.digest():
                raise StoreTampered(f"run {self.run_id}: the verified journal prefix changed")
            boundary = data.rfind(b"\n") + 1
            tail = data[boundary:]
            if tail and not recover_partial:
                raise StoreTampered(f"run {self.run_id}: the record journal has an incomplete last record")
            fresh = self._fresh()
            fresh._prefix_sequence = len(self._entries)
            fresh._head, fresh._offset = self._head, self._offset
            sizes = []
            for raw in data[:boundary].splitlines(keepends=True):
                try:
                    entry = json.loads(raw)
                except ValueError as exc:
                    sequence = fresh._prefix_sequence + len(fresh._entries) + 1
                    raise StoreTampered(f"run {self.run_id}: unreadable record at sequence {sequence}") from exc
                fresh._verify_entry(entry)
                fresh._accept(entry, len(raw))
                sizes.append(len(raw))
            # No shared index changes occur until the whole new suffix verifies.
            for entry, size in zip(fresh._entries, sizes):
                self._accept(entry, size)
            fingerprint.update(data[:boundary])
            self._state.hasher = fingerprint
            self._state.signature = None if tail else _signature(info)
            self._needs_verify = False
            return tail
        data = path.read_bytes()
        if _signature(os.lstat(path)) != _signature(info):
            raise StoreTampered(f"run {self.run_id}: the record journal changed during verification")
        boundary = data.rfind(b"\n") + 1
        tail = data[boundary:]
        if tail and not recover_partial:
            raise StoreTampered(f"run {self.run_id}: the record journal has an incomplete last record")
        fresh = self._fresh()
        for raw in data[:boundary].splitlines(keepends=True):
            try:
                entry = json.loads(raw)
            except ValueError as exc:
                raise StoreTampered(f"run {self.run_id}: unreadable record at sequence "
                                    f"{len(fresh._entries) + 1}") from exc
            fresh._verify_entry(entry)
            fresh._accept(entry, len(raw))
        if len(fresh._entries) < len(self._entries):
            raise StoreTampered(f"run {self.run_id}: the record journal was truncated")
        if any(old["digest"] != new["digest"]
               for old, new in zip(self._entries, fresh._entries)):
            raise StoreTampered(f"run {self.run_id}: the verified journal prefix changed")
        # Do not publish partial snapshots: a normal reader must still refuse the tail.
        if not tail:
            fresh._state.signature = _signature(info)
        fresh._state.hasher = hashlib.sha256(data[:boundary])
        fresh._state.snapshot_depth = self._state.snapshot_depth
        self._state.__dict__.update(fresh._state.__dict__)
        self._needs_verify = False
        return tail

    def _verify_entry(self, entry):
        expected_seq = getattr(self, "_prefix_sequence", 0) + len(self._entries) + 1
        if type(entry) is not dict or set(entry) != {"schema_version", "seq", "kind", "time_ns", "prev", "record",
                                                       "id", "digest"}:
            raise StoreTampered(f"run {self.run_id}: malformed record at sequence {expected_seq}")
        if entry["seq"] != expected_seq or entry["prev"] != self._head:
            raise StoreTampered(f"run {self.run_id}: the chain breaks at sequence {expected_seq} "
                                "(a record was inserted, removed or reordered)")
        body = {k: v for k, v in entry.items() if k not in ("id", "digest")}
        if entry["id"] != f"{entry['kind']}-{entry['seq']:06d}-{_digest(body)[:12]}":
            raise StoreTampered(f"run {self.run_id}: record {entry.get('id')!r} does not match its content")
        if entry["digest"] != _digest({k: v for k, v in entry.items() if k != "digest"}):
            raise StoreTampered(f"run {self.run_id}: record {entry['id']} was edited")

    def _check_head(self, *, repair=False):
        """The head file names the last record; one record past it is an append the head missed (a crash)."""
        path = self.root / HEAD
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise StoreTampered(f"run {self.run_id}: the journal head is not a regular file")
        if not path.exists():
            head = {"seq": 0, "digest": GENESIS}
        else:
            try:
                head = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise StoreTampered(f"run {self.run_id}: the journal head is unreadable") from exc
        last = {"seq": len(self._entries), "digest": self._head}
        if head == last:
            return False
        previous = self._entries[-2]["digest"] if len(self._entries) >= 2 else GENESIS
        if head == {"seq": len(self._entries) - 1, "digest": previous}:
            if repair:
                _write_private(path, (json.dumps(last, sort_keys=True) + "\n").encode())
            return True
        raise StoreTampered(f"run {self.run_id}: the journal head does not match its last record "
                            "(a record was removed or the head was edited)")

    def recover(self):
        """Trusted crash recovery; arbitrary chain/head damage refuses without mutation.

        A durable intent closes the crash window between truncation and recording the
        repair. Complete events are retained; only an incomplete unacknowledged tail
        may be removed. Repeated calls emit exactly one record for each repair.
        """
        with self._guard():
            tail = self._refresh(recover_partial=True, force=True)
            self._check_head()  # Only the exact head or one complete record behind is admissible.
            current = {"seq": len(self._entries), "digest": self._head}
            head_path = self.root / HEAD
            head = json.loads(head_path.read_text()) if head_path.exists() else {"seq": 0, "digest": GENESIS}
            pending = self.root / "journal-recovery.json"
            if pending.exists():
                if pending.is_symlink() or not pending.is_file():
                    raise StoreTampered("invalid journal recovery intent")
                try:
                    saved = json.loads(pending.read_text())
                    intent, prepared = saved["record"], saved["entry"]
                    if set(saved) != {"record", "entry"} or set(intent) != {
                        "cause", "head_before", "head_after", "tail_blob", "tail_bytes", "interrupted_recovery_tails"
                    }:
                        raise ValueError("malformed intent")
                    blob = self.get_blob(intent["tail_blob"])
                    if len(blob) != intent["tail_bytes"]:
                        raise ValueError("invalid tail size")
                    for digest in intent["interrupted_recovery_tails"]:
                        self.get_blob(digest)
                    matches = self._by_kind.get("journal-recovery", [])
                    completed = bool(matches and matches[-1] == prepared)
                    if not completed:
                        if (current != intent["head_after"] or prepared["record"] != intent
                                or prepared["kind"] != "journal-recovery"):
                            raise ValueError("recovery head changed")
                        self._verify_entry(prepared)
                    if tail and completed:
                        raise ValueError("unexpected tail after completed recovery")
                    if tail and tail != blob and hashlib.sha256(tail).hexdigest() not in intent["interrupted_recovery_tails"]:
                        if not _line(prepared).encode().startswith(tail):
                            raise ValueError("recovery tail changed")
                        # Preserve an interrupted repair append as well as the original tail.
                        intent["interrupted_recovery_tails"].append(self.put_blob(tail))
                        prepared = self._prepare_entry("journal-recovery", intent)
                        _write_private(pending, _line({"record": intent, "entry": prepared}).encode())
                except (ValueError, KeyError, TypeError) as exc:
                    raise StoreTampered(f"invalid journal recovery intent: {exc}") from exc
                if completed:
                    self._check_head(repair=True)
                    pending.unlink()
                    _fsync_directory(self.root)
                    return None
            else:
                if not tail and head == current:
                    return None
                intent = {"cause": "incomplete-tail" if tail else "head-lag",
                          "head_before": head, "head_after": current,
                          "tail_blob": self.put_blob(tail), "tail_bytes": len(tail),
                          "interrupted_recovery_tails": []}
                prepared = self._prepare_entry("journal-recovery", intent)
                _write_private(pending, _line({"record": intent, "entry": prepared}).encode())
            journal = self.root / JOURNAL
            if tail:
                fd = os.open(journal, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    os.ftruncate(fd, self._offset)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                _fsync_directory(self.root)
            self._check_head(repair=True)
            identifier = self._append_locked("journal-recovery", intent, prepared=prepared)
            pending.unlink()
            _fsync_directory(self.root)
            return identifier

    def _prepare_entry(self, kind, record):
        body = {"schema_version": SCHEMA_VERSION, "seq": len(self._entries) + 1, "kind": kind,
                "time_ns": time.time_ns(), "prev": self._head, "record": deepcopy(record)}
        entry = {**body, "id": f"{kind}-{body['seq']:06d}-{_digest(body)[:12]}"}
        entry["digest"] = _digest(entry)
        return entry

    def _append_locked(self, kind, record, *, prepared=None):
        entry = prepared if prepared is not None else self._prepare_entry(kind, record)
        data = _line(entry).encode()
        fd = os.open(self.root / JOURNAL, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
                     0o600)
        try:
            os.fchmod(fd, 0o600)
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        _fsync_directory(self.root)
        self._accept(entry, len(data))
        self._state.hasher.update(data)
        self._state.signature = _signature(os.lstat(self.root / JOURNAL))
        _write_private(self.root / HEAD, (json.dumps({"seq": entry["seq"], "digest": entry["digest"]},
                                                     sort_keys=True) + "\n").encode())
        return entry["id"]

    def append(self, kind: str, record: dict) -> str:
        """Append a JSON record; recover interrupted appends through the trusted path."""
        if type(kind) is not str or not KIND.fullmatch(kind):
            raise StoreError(f"invalid record kind {kind!r}")
        if type(record) is not dict:
            raise StoreError("a store record must be a JSON object")
        _json_safe(record)
        with self._guard():
            try:
                self._refresh()
                lag = self._check_head()
            except StoreTampered:
                # recover takes the same reentrant thread lock, but never reacquire flock.
                pass
            else:
                if not lag and not (self.root / "journal-recovery.json").exists():
                    return self._append_locked(kind, record)
        self.recover()
        with self._guard():
            self._refresh()
            self._check_head(repair=True)
            return self._append_locked(kind, record)

    def read(self, kind: str, record_id: str) -> dict:
        with self._guard():
            self._refresh()
            self._check_head()
            entry = self._by_id.get(record_id)
        if entry is None or entry["kind"] != kind:
            raise StoreError(f"run {self.run_id} has no {kind} record {record_id!r}")
        return deepcopy(entry)

    def scan(self, kind: str) -> list[dict]:
        with self._guard():
            self._refresh()
            self._check_head()
            return deepcopy(self._by_kind.get(kind, []))

    def latest(self, kind):
        with self._guard():
            self._refresh()
            self._check_head()
            rows = self._by_kind.get(kind, [])
            return deepcopy(rows[-1]) if rows else None

    def count(self, kind):
        """Number of verified records of this kind, without copying their payloads."""
        with self._guard():
            self._refresh()
            self._check_head()
            return len(self._by_kind.get(kind, []))

    def head(self):
        """``{seq, digest}`` of the last record (the ledger head for receipts)."""
        with self._guard():
            self._refresh()
            self._check_head()
            return {"seq": len(self._entries), "digest": self._head}

    def verify(self):
        """Re-verify the whole chain from its first record; returns problems (empty when intact)."""
        try:
            with self._guard():
                self._refresh(force=True)
                self._check_head()
        except (StoreTampered, OSError, ValueError) as exc:
            return [str(exc)]
        return []

    # -- files in the store --

    def path(self, *parts: str) -> Path:
        """A path inside this run's store (the run's store directory itself without parts).

        Never inside the run directory or a sandbox mount; parts are single plain names.
        """
        if any(type(p) is not str or not PART.fullmatch(p) or p in (".", "..") for p in parts):
            raise StoreError(f"invalid store path parts {parts!r}")
        if not parts:
            return self.root
        target = self.root.joinpath(*parts)
        record = None
        try:
            record = self.run_record()
        except StoreError:
            record = None
        if record is not None and _within(target, Path(record["run_dir"])):
            raise StoreError("a store path cannot lie inside the run directory")
        return target

    def put_blob(self, data: bytes) -> str:
        """Store ``data`` write-once under its sha256; returns the digest."""
        if type(data) is not bytes:
            raise StoreError("a blob is bytes")
        digest = hashlib.sha256(data).hexdigest()
        directory = _private_dir(self.root / "blobs")
        target = directory / digest
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise StoreTampered(f"run {self.run_id}: blob {digest} was altered")
            return digest
        _write_private(target, data, exclusive=True)
        return digest

    def get_blob(self, digest: str) -> bytes:
        if type(digest) is not str or not SHA.fullmatch(digest):
            raise StoreError("invalid blob digest")
        target = self.root / "blobs" / digest
        if target.is_symlink() or not target.is_file():
            raise StoreError(f"run {self.run_id} has no blob {digest}")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise StoreTampered(f"run {self.run_id}: blob {digest} was altered")
        return data

    def graph_scope(self) -> Path:
        """The substrate scope root of the run's graphs: checkpoints, events, effects and the stop flag."""
        return _private_dir(self.root / GRAPH_SCOPE)

    def checkpointer(self):
        """A ``SqliteSaver`` over the run's checkpoint database in the store (closed by ``close``)."""
        from ..workflow import graph_environment  # noqa: F401  (strict msgpack before LangGraph)
        from langgraph.checkpoint.sqlite import SqliteSaver
        from ..workflow.graph_substrate import strict_serializer
        scope = self.graph_scope()
        _private_dir(scope / "framework")
        database = scope / CHECKPOINTS
        if database.is_symlink() or (database.exists() and not database.is_file()):
            raise StoreError("the checkpoint database must be a regular file")
        if not database.exists():
            os.close(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        connection = sqlite3.connect(str(database), check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        self._connections.append(connection)
        return SqliteSaver(connection, serde=strict_serializer())

    def close(self):
        for connection in self._connections:
            connection.close()
        self._connections.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _path_key(directory):
    return hashlib.sha256(str(directory).encode()).hexdigest()


# ---- ownership --------------------------------------------------------------------------

def _marker_claim(directory):
    marker = directory / RUN_MARKER
    try:
        if not marker.is_symlink() and not marker.exists():
            return None
        if marker.is_symlink() or not marker.is_file():
            raise ValueError("not a regular file")
        claim = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ControllerOwnershipUnknown(f"{marker} cannot be read ({exc}); the directory's controller "
                                         "ownership is unknown") from None
    run_id = claim.get("run_id") if type(claim) is dict else None
    if type(run_id) is not str or not RUN_ID.fullmatch(run_id):
        raise ControllerOwnershipUnknown(f"{marker} names no valid run; the directory's controller ownership "
                                         "is unknown")
    return run_id


def _index_claim(directory, root):
    entry_path = root / INDEX / f"path-{_path_key(directory)}.json"
    try:
        if not entry_path.is_file():
            return None
        entry = json.loads(entry_path.read_text(encoding="utf-8"))
        info = os.stat(directory)
    except (OSError, ValueError):
        return None
    if type(entry) is not dict or not RUN_ID.fullmatch(str(entry.get("run_id"))):
        return None
    # A directory recreated at a run's old path, without the run's marker, is not that run.
    return entry["run_id"] if (info.st_dev, info.st_ino) == (entry.get("dev"), entry.get("ino")) else None


def previous_claim(directory, root=None):
    """The run an earlier controller run recorded at this exact path, whatever now stands there, or None.

    A new run may start at the path of a run whose directory was deleted (G4); the new run records this
    earlier claim, and the earlier run never resumes from the new directory (``check_binding``).
    """
    base = Path(os.path.realpath(Path(root).expanduser())) if root is not None else store_root()
    real = Path(os.path.realpath(Path(directory).expanduser()))
    entry_path = base / INDEX / f"path-{_path_key(real)}.json"
    try:
        entry = json.loads(entry_path.read_text(encoding="utf-8")) if entry_path.is_file() else None
    except (OSError, ValueError):
        return None
    if type(entry) is not dict or not RUN_ID.fullmatch(str(entry.get("run_id"))):
        return None
    return {"run_id": entry["run_id"], "store_exists": (base / entry["run_id"] / RUN).is_file()}


def controller_owned(run_dir: Path) -> str | None:
    """The run id if the controller owns ``run_dir`` or a directory containing it, else None.

    Symlink aliases are resolved, so a path that reaches a controller run through a link is
    reported too (C25). A path inside a run's store is owned by that run. A copy of a run
    directory carries the run's marker and is reported as that run (C41): no state-writing
    command may treat it as a fresh legacy run, and ``check_binding`` refuses to resume it. A
    damaged marker raises ``ControllerOwnershipUnknown``: a claim that cannot be read is still a
    claim, and every caller fails closed.
    """
    try:
        real = Path(os.path.realpath(Path(run_dir).expanduser()))
    except (OSError, ValueError, TypeError):
        return None
    try:
        roots = [store_root()]
    except (StoreError, OSError, ValueError, KeyError):
        roots = []
    for root in roots:
        real_root = Path(os.path.realpath(root))
        if _within(real, real_root) and real != real_root:
            first = real.relative_to(real_root).parts[0]
            if RUN_ID.fullmatch(first):
                return first
    for candidate in (real, *real.parents):
        claim = _marker_claim(candidate)
        if claim:
            return claim
        if RUN_ID.fullmatch(candidate.name) and (candidate / RUN).is_file() and (candidate / JOURNAL).is_file():
            return candidate.name  # a run's own store directory (under any store root)
        for root in roots:
            claim = _index_claim(candidate, root)
            if claim:
                return claim
    return None


def store_for(run_dir, *, root=None):
    """The ``RunStore`` a run directory's marker names (for the controller entry and resume checks)."""
    real = Path(os.path.realpath(Path(run_dir).expanduser()))
    claim = _marker_claim(real)
    if not claim:
        raise StoreError(f"{run_dir} carries no controller-run marker")
    return RunStore(claim, root=root)
