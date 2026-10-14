"""Install state, the single-installer lock, logs and receipts under the prefix."""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import os
from pathlib import Path
import socket
import tempfile

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows is not a supported install platform
    fcntl = None


class LockedError(RuntimeError):
    """Another installer holds the prefix lock."""


def utc_stamp():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(value, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)


class InstallState:
    """Per-step status keyed by ``group/step`` with the step fingerprint."""

    def __init__(self, prefix):
        self.path = Path(prefix) / "state/install-state.json"
        self.data = {"schema_version": 1, "steps": {}, "licenses_accepted": {}}
        if self.path.is_file():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("schema_version") == 1:
                self.data = loaded
                self.data.setdefault("steps", {})
                self.data.setdefault("licenses_accepted", {})

    def get(self, key):
        return self.data["steps"].get(key)

    def record(self, key, **values):
        values["updated"] = utc_stamp()
        self.data["steps"][key] = values
        self.save()

    def save(self):
        write_json_atomic(self.path, self.data)

    def failed(self):
        return {k: v for k, v in self.data["steps"].items() if v.get("status") == "failed"}


@contextlib.contextmanager
def install_lock(prefix):
    """Hold ``state/install.lock`` for this process; released automatically on exit."""
    path = Path(prefix) / "state/install.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                handle.seek(0)
                holder = handle.read().strip() or "another process"
                raise LockedError(f"another installer is running on this prefix ({holder}); "
                                  f"wait for it to finish") from error
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid {os.getpid()} on {socket.gethostname()} since {utc_stamp()}\n")
        handle.flush()
        yield path
    finally:
        if fcntl is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class RunLog:
    """One directory of per-step logs plus a summary for each installer run."""

    def __init__(self, prefix, stamp=None):
        self.directory = Path(prefix) / "logs" / (stamp or utc_stamp())
        self.directory.mkdir(parents=True, exist_ok=True)
        self.events = []

    def step_log(self, key):
        return self.directory / (key.replace("/", ".") + ".log")

    def event(self, key, status, **detail):
        row = {"step": key, "status": status, **detail}
        self.events.append(row)
        return row

    def write_summary(self, **extra):
        write_json_atomic(self.directory / "summary.json", {"events": self.events, **extra})
        return self.directory / "summary.json"


def write_receipt(prefix, group_id, receipt):
    path = Path(prefix) / "receipts" / (group_id + ".json")
    write_json_atomic(path, receipt)
    return path
