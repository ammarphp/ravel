"""Effect counters the adversary cannot reach.

Each counter observes a forbidden effect from outside the confined process: the bytes of protected
files, connections to a listener, invocations of a fake model endpoint, canary bytes in anything a
case can read back, processes left behind. A case asserts the counter's value; it never trusts an
adversary's report of what it managed to do.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import uuid


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Sentinels:
    """A directory of protected files; ``changes()`` lists every added, removed or altered entry."""

    def __init__(self, root, files):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.before = self.snapshot()

    def snapshot(self):
        state = {}
        for path in sorted(self.root.rglob('*')):
            rel = path.relative_to(self.root).as_posix()
            if path.is_symlink():
                state[rel] = 'link:' + os.readlink(path)
            elif path.is_file():
                state[rel] = _digest(path)
            elif path.is_dir():
                state[rel] = 'dir'
        return state

    def changes(self):
        after = self.snapshot()
        return sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k))


class Listener:
    """A loopback TCP listener counting accepted connections (the target of socket attempts)."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('127.0.0.1', 0))
        self.sock.listen(16)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.accepted = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            self.accepted += 1
            conn.close()

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


class Canary:
    """Unique canary text; ``found_in(paths)`` lists every file that carries it."""

    def __init__(self, label):
        self.value = f'nc-canary-{label}-{uuid.uuid4().hex}'

    def found_in(self, *roots):
        hits = []
        needle = self.value.encode()
        for root in roots:
            root = Path(root)
            paths = [root] if root.is_file() else (p for p in root.rglob('*') if p.is_file() and not p.is_symlink())
            for path in paths:
                try:
                    if needle in path.read_bytes():
                        hits.append(str(path))
                except OSError:
                    continue
        return hits


class Processes:
    """Processes whose command line carries a unique marker (observed only; never signalled)."""

    def __init__(self):
        self.marker = f'nc-orphan-{uuid.uuid4().hex}'

    def alive(self):
        listing = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, check=False).stdout
        return [line.split(None, 1)[0] for line in listing.splitlines() if self.marker in line]

    def wait_gone(self, seconds=5.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self.alive():
                return []
            time.sleep(0.1)
        return self.alive()


class Effects:
    """The counters of one case; created lazily, closed with the case."""

    def __init__(self, root):
        self.root = Path(root)
        self._listener = None
        self.canaries = {}

    def sentinels(self, name, files):
        return Sentinels(self.root / 'sentinels' / name, files)

    @property
    def listener(self):
        if self._listener is None:
            self._listener = Listener()
        return self._listener

    def canary(self, label):
        if label not in self.canaries:
            self.canaries[label] = Canary(label)
        return self.canaries[label]

    def processes(self):
        return Processes()

    def close(self):
        if self._listener is not None:
            self._listener.close()
