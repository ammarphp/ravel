"""WP04 isolation: materialization, admission, Seatbelt profile, launcher and allowlist proxy.

Every workspace, canary, secret and process here is synthetic engineering material, not an
agent result. Seatbelt integration tests run only where macOS sandbox-exec works (they skip on
Linux CI) and pair each denial with a positive control: the same probe succeeds, or fails
differently, without the sandbox, so a missing file, a refused connection or a timeout can
never pass as a sandbox denial. Probes whose target may be absent on a host (~/.claude,
~/.codex, a non-loopback address, a git checkout) are separate tests that skip with a reason.
Runaway test processes are self-limiting (they exit on their own within 30 s).
"""
import errno
import itertools
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from governance import allowlist_proxy, isolation
from governance.canonical import ContractError, read_jsonl, sha256_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
PREFIX = os.path.realpath(sys.base_prefix)
CANARY = "SYNTHETIC-ORACLE-CANARY-4e7b1f"
SECRET = "SYNTHETIC-ARGV-SECRET-9d21c3"
SANDBOX_ERRNOS = {errno.EPERM, errno.EACCES}
needs_sandbox = pytest.mark.skipif(
    not (isolation.sandbox_available() and PYTHON.startswith(PREFIX + "/")),
    reason="needs a working macOS sandbox-exec (not Linux CI, not nested in another sandbox) and an "
           "interpreter inside sys.base_prefix")

PROBE = r'''
"""Synthetic isolation probe: reports ok/errno per operation, never file contents."""
import ctypes, ctypes.util, fcntl, json, os, socket, struct, subprocess, sys

def sysctl(mib):
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    mib, size = (ctypes.c_int * len(mib))(*mib), ctypes.c_size_t(0)
    if libc.sysctl(mib, len(mib), None, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl")
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, len(mib), buf, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl")
    return buf.raw[:size.value]

def fd_path(fd):                             # F_GETPATH on macOS, /proc elsewhere
    if hasattr(fcntl, "F_GETPATH"):
        return fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
    return os.readlink(f"/proc/self/fd/{fd}")

def outcome(call):
    try:
        return {"ok": call()}
    except OSError as exc:
        return {"errno": exc.errno}

def run(op, arg, needle):
    if op == "read":
        with open(arg, "rb") as handle:
            return {"found": needle in handle.read()}
    if op == "list":
        return {"entries": len(os.listdir(arg))}
    if op == "stat":
        os.stat(arg)
        return {}
    if op == "write":
        with open(arg, "xb") as handle:
            handle.write(b"synthetic probe write\n")
        return {}
    if op == "symlink":
        os.symlink(*arg.split(" "))
        return {}
    if op == "connect":
        host, port = arg.rsplit(":", 1)
        socket.create_connection((host, int(port)), timeout=5).close()
        return {}
    if op == "proxy":
        port, target = arg.split(" ")
        with socket.create_connection(("127.0.0.1", int(port)), timeout=5) as sock:
            sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
            return {"status": sock.recv(64).split(b" ")[1].decode()}
    if op == "fd":
        return {"found": needle in os.read(int(arg), 4096)}
    if op == "procargs":                     # CTL_KERN, KERN_PROCARGS2: argv and environment
        return {"found": needle in sysctl([1, 49, int(arg)])}
    if op == "kinfo":                        # CTL_KERN, KERN_PROC, KERN_PROC_ALL: the process table
        data = sysctl([1, 14, 0])            # struct kinfo_proc is 648 bytes, p_pid at offset 40
        return {"listed": int(arg) in [struct.unpack_from("i", data, o + 40)[0] for o in range(0, len(data), 648)]}
    if op == "pids":
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        pids = (ctypes.c_int * 8192)()
        count = libproc.proc_listallpids(pids, ctypes.sizeof(pids))
        return {"count": count, "listed": int(arg) in pids[:max(count, 0)]}
    if op == "ps":
        out = subprocess.run(["/bin/ps", "-Aww", "-o", "pid=,command="], capture_output=True, timeout=30)
        return {"found": needle in out.stdout + out.stderr}
    if op == "open":                         # open and close a device by path: "<path> rw|ro|wo"
        path, mode = arg.rsplit(" ", 1)
        flags = {"rw": os.O_RDWR, "ro": os.O_RDONLY, "wo": os.O_WRONLY}[mode]
        os.close(os.open(path, flags | os.O_NOCTTY | os.O_NONBLOCK))
        return {}
    if op == "ttyread":                      # what is waiting on a terminal's input queue (keystrokes)
        fd = os.open(arg, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            return {"found": needle in os.read(fd, 4096)}
        finally:
            os.close(fd)
    if op == "openpty":                      # allocate a pseudo-terminal of its own
        for fd in os.openpty():
            os.close(fd)
        return {}
    if op == "shm_create":                   # leave state in a named POSIX shared-memory object
        import _posixshmem, mmap
        fd = _posixshmem.shm_open(arg, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        try:
            os.ftruncate(fd, 4096)
            with mmap.mmap(fd, 4096) as shared:
                shared[:len(needle)] = needle
        finally:
            os.close(fd)
        return {}
    if op == "shm_read":                     # pick up state an earlier process left
        import _posixshmem, mmap
        fd = _posixshmem.shm_open(arg, os.O_RDONLY, 0)
        try:
            with mmap.mmap(fd, 4096, prot=mmap.PROT_READ) as shared:
                return {"found": needle in shared[:]}
        finally:
            os.close(fd)
    if op == "sem_create":                   # a named semaphore (what multiprocessing locks open)
        import _multiprocessing
        _multiprocessing.SemLock(1, 1, 1, arg, False)
        return {}
    if op in ("sysv_create", "sysv_lookup"):   # a System V object at an agreed key: "<shm|msg|sem> <key>"
        kind, key = arg.split(" ")
        libc = ctypes.CDLL(None, use_errno=True)
        libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
        create = op == "sysv_create"
        flags = 0o1000 | 0o600 if create else 0                          # IPC_CREAT, owner read-write
        ident = {"shm": lambda: libc.shmget(int(key), 4096 if create else 0, flags),
                 "msg": lambda: libc.msgget(int(key), flags),
                 "sem": lambda: libc.semget(int(key), 1 if create else 0, flags)}[kind]()
        if ident < 0:
            raise OSError(ctypes.get_errno(), f"{op} {arg}")
        return {"id": ident}
    if op == "stdio":                        # what the subject can do to its own stream descriptors
        report = {}
        for fd in (0, 1, 2):
            report[f"seek{fd}"] = outcome(lambda: os.lseek(fd, 0, os.SEEK_SET))
            report[f"truncate{fd}"] = outcome(lambda: os.ftruncate(fd, 0))
            report[f"path{fd}"] = outcome(lambda: fd_path(fd))
        return report
    raise SystemExit(f"unknown probe {op}")

request = json.load(sys.stdin)
results = []
for op, arg in request["probes"]:
    try:
        results.append({"ok": True, **run(op, arg, request["needle"].encode())})
    except OSError as exc:
        results.append({"ok": False, "errno": exc.errno})
print(json.dumps(results))
'''

DOUBLE_FORK = r'''
import os, signal, sys, time
pidfile = sys.argv[1]
if os.fork() == 0:
    if os.fork() == 0:                       # grandchild: ignores SIGTERM, outlives its parent
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(pidfile + ".tmp", "w") as handle:
            handle.write(str(os.getpid()))
        os.rename(pidfile + ".tmp", pidfile)
        deadline = time.time() + 30
        while time.time() < deadline:
            time.sleep(0.05)
        os._exit(0)
    os._exit(0)
os.wait()
while not os.path.exists(pidfile):
    time.sleep(0.01)
time.sleep(30)
'''

SETSID_CHILD = r'''
import os, sys, time
if os.fork() == 0:                           # child leaves the launcher's session and group
    os.setsid()
    with open(sys.argv[1] + ".tmp", "w") as handle:
        handle.write(str(os.getpid()))
    os.rename(sys.argv[1] + ".tmp", sys.argv[1])
    time.sleep(30)
    os._exit(0)
while not os.path.exists(sys.argv[1]):       # the leader then exits normally: its group is empty
    time.sleep(0.01)
'''

FORK_CHAIN = r'''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
mode, log = sys.argv[1], sys.argv[2]
with open(log + ".tmp", "w") as handle:      # first record: the leader's pid and process group
    handle.write(f"{os.getpid()} {os.getpgrp()}\n")
os.rename(log + ".tmp", log)
deadline = time.time() + 20                  # self-limiting if a test fails
for chain in range(int(sys.argv[3])):
    if os.fork() == 0:
        generation = 0
        while time.time() < deadline:        # each generation forks its successor and exits
            if os.fork():
                os._exit(0)
            generation += 1
            if mode == "setsid":
                os.setsid()                  # every generation in a new session and group
            if generation % 64 == 0:         # progress evidence: pid and process group
                with open(log, "a") as handle:
                    handle.write(f"{os.getpid()} {os.getpgrp()}\n")
        os._exit(0)
time.sleep(30)
'''


def denied(result):
    return result["ok"] is False and result["errno"] in SANDBOX_ERRNOS


@pytest.fixture
def lab(tmp_path):
    """Synthetic layout: a subject workspace, an oracle in a sibling dir, a note in the parent
    dir, a repository-like dir, a packet-like dir, an outside dir and coordinator storage."""
    base = Path(os.path.realpath(tmp_path))
    subjects = base / "subjects"
    subjects.mkdir()
    ws = subjects / "s-5c1e0f"
    isolation.materialize({"request.md": b"Synthetic isolation test request.\n",
                           "inputs/workspace.json": b'{"synthetic": true}\n',
                           "probe.py": PROBE.encode(), "output/": b"", "tmp/": b""}, ws)
    home = base / "home-5c1e0f"
    home.mkdir()
    oracle = subjects / "s-oracle" / "oracle.json"
    oracle.parent.mkdir()
    oracle.write_text(json.dumps({"synthetic": True, "canary": CANARY}))
    (subjects / "parent-note.txt").write_text(f"synthetic parent note {CANARY}\n")
    repo = base / "repo-like"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text(f"ref: refs/heads/{CANARY}\n")
    (repo / "AGENTS.md").write_text(f"synthetic instructions {CANARY}\n")
    packet = base / "packet-like"
    packet.mkdir()
    (packet / "README.md").write_text(f"synthetic packet {CANARY}\n")
    (base / "outside").mkdir()
    (base / "coordinator").mkdir()
    env = isolation.subject_env(workspace=ws, home=home, path_dirs=["/usr/bin", "/bin"],
                                extra={"RAVEL_TASK_ENDPOINT": "http://127.0.0.1:9/op",
                                       "RAVEL_TASK_TOKEN": "synthetic-task-token"})
    return SimpleNamespace(base=base, subjects=subjects, ws=ws, home=home, oracle=oracle, repo=repo, packet=packet,
                           outside=base / "outside", coord=base / "coordinator", env=env, n=itertools.count())


def profile_for(lab, *, network="none", ports=(), **extra):
    policy = isolation.SandboxPolicy(read_roots=[lab.ws, PREFIX],
                                     write_roots=[lab.ws / "output", lab.ws / "tmp", lab.home],
                                     network=network, localhost_ports=list(ports), **extra)
    return isolation.seatbelt_profile(policy)


def probe(lab, probes, *, profile, needle=CANARY, launched=None):
    """Run PROBE once; returns (results, raw output). `launched` (a list) also receives the LaunchResult."""
    n = next(lab.n)
    request = lab.coord / f"request-{n}.json"
    request.write_text(json.dumps({"needle": needle, "probes": probes}))
    out, err = lab.coord / f"out-{n}.json", lab.coord / f"err-{n}.txt"
    result = isolation.launch([PYTHON, "-I", "-S", "-B", str(lab.ws / "probe.py")], cwd=lab.ws, env=lab.env,
                              profile=profile, timeout_s=60, stdout_path=out, stderr_path=err, stdin_path=request)
    assert result.exit_code == 0 and not result.timed_out and result.survivors == [], err.read_text()
    if launched is not None:
        launched.append(result)
    return json.loads(out.read_text()), out.read_text() + err.read_text()


def admit(root, env, **kw):
    kw.setdefault("forbidden_sha256", {"0" * 64})
    kw.setdefault("canaries", [CANARY])
    return isolation.admission_check(root, env=env, **kw)


def codes(report):
    return {(v["code"], v["where"]) for v in report["violations"]}


def gone(pid, timeout=2.0):
    """True once pid no longer exists (a killed orphan may linger briefly until launchd reaps it)."""
    def absent():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    return wait_for(absent, timeout)


def kill_quietly(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def chain_records(log):
    """(pid, pgid) records a FORK_CHAIN has written, once they stopped growing for 0.3 s (a
    live chain member appends every 64 generations, i.e. every few tens of milliseconds)."""
    def read():
        rows = (line.split() for line in log.read_text().splitlines())
        return [(int(r[0]), int(r[1])) for r in rows if len(r) == 2 and all(x.isdigit() for x in r)]
    before = read()
    time.sleep(0.3)
    after = read()
    assert after == before, "a chain member is still running"
    return after


class EchoServer:
    """Loopback echo server that counts accepted connections (synthetic network peer)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.1)
        self.port, self.accepted, self._stop = self.sock.getsockname()[1], 0, threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.accepted += 1
            threading.Thread(target=self._echo, args=(conn,), daemon=True).start()

    @staticmethod
    def _echo(conn):
        with conn:
            conn.settimeout(5)
            try:
                while data := conn.recv(4096):
                    conn.sendall(data)
            except OSError:
                pass

    def close(self):
        self._stop.set()
        self.thread.join(2)
        self.sock.close()


def free_fd(start=200):
    """A descriptor number not open in this process (dup2 onto it closes nothing of pytest's)."""
    for fd in range(start, start + 500):
        try:
            os.fstat(fd)
        except OSError:
            return fd
    raise AssertionError("no free descriptor number")


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.02)
    return predicate()


# --------------------------------------------------------------------------- materialize

def test_materialize_writes_fresh_regular_files(tmp_path):
    root = tmp_path / "s-1"
    files = {"request.md": b"synthetic request\n", "inputs/title.txt": b"synthetic title\n",
             "bin/ravel-task": b"#!/bin/sh\nexit 0\n", "output/": b"", "tmp/": b""}
    isolation.materialize(files, root)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name, data in files.items():
        info = os.lstat(root / name)
        if name.endswith("/"):
            assert stat.S_ISDIR(info.st_mode) and not os.listdir(root / name)
            continue
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        assert (root / name).read_bytes() == data
        assert stat.S_IMODE(info.st_mode) == (0o555 if name.startswith("bin/") else 0o444)
    assert stat.S_IMODE(os.lstat(root / "inputs").st_mode) == 0o755


@pytest.mark.parametrize("name", ["/etc/passwd", "../escape", "a/../../b", "a//b", "./a", "a/.", "",
                                  ".git/config", "src/.GIT", "a\\b", "a\nb", "a\0b"])
def test_materialize_rejects_unsafe_names(tmp_path, name):
    with pytest.raises(ContractError):
        isolation.materialize({name: b"synthetic"}, tmp_path / "s-1")
    assert not (tmp_path / "s-1").exists()


@pytest.mark.parametrize("files", [
    {"a": b"x", "a/b": b"y"},                       # file and directory
    {"A.txt": b"x", "a.txt": b"y"},                 # case-insensitive collision
    {"dir/": b"not empty"},                         # directory marker with content
    {"text.txt": "not bytes"},                      # value type
])
def test_materialize_rejects_conflicting_plans(tmp_path, files):
    with pytest.raises(ContractError):
        isolation.materialize(files, tmp_path / "s-1")


def test_materialize_requires_a_fresh_root(tmp_path):
    used = tmp_path / "used"
    used.mkdir()
    (used / "stale.txt").write_bytes(b"synthetic")
    with pytest.raises(ContractError, match="empty directory"):
        isolation.materialize({"a": b"x"}, used)
    empty = tmp_path / "empty"
    empty.mkdir()
    (tmp_path / "link").symlink_to(empty)
    with pytest.raises(ContractError):
        isolation.materialize({"a": b"x"}, tmp_path / "link")
    with pytest.raises(ContractError):
        isolation.materialize({"a": b"x"}, tmp_path / "missing-parent" / "s-1")
    isolation.materialize({"a": b"x"}, empty)       # an existing empty directory is accepted
    assert (empty / "a").read_bytes() == b"x"


# --------------------------------------------------------------------------- admission

def test_admission_accepts_clean_workspace_and_task_credentials(lab):
    report = admit(lab.ws, lab.env, forbidden_sha256={sha256_bytes(lab.oracle.read_bytes())})
    assert report == {"ok": True, "violations": []}


def test_admission_flags_every_planted_workspace_violation(lab):
    ws = lab.ws
    os.symlink(lab.oracle, ws / "inputs" / "link.json")
    os.link(lab.subjects / "parent-note.txt", ws / "output" / "note.txt")
    (ws / "tmp" / ".Git").mkdir()
    (ws / "tmp" / "copy.json").write_bytes(b"synthetic copy with no canary")
    padding = b"x" * ((1 << 20) - 5)                # canary straddles the 1 MiB read boundary
    (ws / "tmp" / "big.bin").write_bytes(padding + CANARY.encode() + b"tail")
    (ws / "tmp" / "wide.txt").write_bytes(f"synthetic {CANARY}".encode("utf-16"))
    (ws / "tmp" / f"{CANARY}.txt").write_bytes(b"synthetic, canary only in the name")
    os.mkfifo(ws / "tmp" / "fifo")
    report = admit(ws, lab.env, forbidden_sha256={sha256_bytes(b"synthetic copy with no canary")})
    assert not report["ok"]
    assert codes(report) >= {("symlink", "inputs/link.json"), ("hardlink", "output/note.txt"),
                             ("canary", "output/note.txt"), ("git_entry", "tmp/.Git"),
                             ("forbidden_content", "tmp/copy.json"), ("canary", "tmp/big.bin"),
                             ("canary", "tmp/wide.txt"), ("canary_name", f"tmp/{CANARY}.txt"),
                             ("special_file", "tmp/fifo")}
    assert all(set(v) == {"code", "where", "detail"} for v in report["violations"])


def test_admission_env_rules(lab, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_PARENT_TOKEN", "synthetic-parent-secret-value")
    env = dict(lab.env, API_KEY="x", my_token="x", Password="x", X_AUTH_HEADER="x",
               AWS_SECRET_ACCESS_KEY="x", GH_CREDENTIALS="x", CLAUDECODE="1",
               CLAUDE_CODE_MESSAGING_SOCKET="/tmp/x.sock", CLAUDE_CODE_SESSION_ID="x",
               NOTE=f"synthetic {CANARY}", PYTHONPATH=f"/usr/lib:{lab.repo / 'src'}",
               COPIED="prefix synthetic-parent-secret-value")
    report = admit(lab.ws, env, forbidden_roots=[lab.repo])
    flagged = codes(report)
    for name in ("API_KEY", "my_token", "Password", "X_AUTH_HEADER", "AWS_SECRET_ACCESS_KEY", "GH_CREDENTIALS"):
        assert ("env_secret_name", f"env:{name}") in flagged
    for name in ("CLAUDECODE", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_SESSION_ID"):
        assert ("env_host_session", f"env:{name}") in flagged
    assert {("env_canary", "env:NOTE"), ("env_forbidden_path", "env:PYTHONPATH"),
            ("env_inherited_secret", "env:COPIED")} <= flagged
    assert not any(where in ("env:RAVEL_TASK_TOKEN", "env:RAVEL_TASK_ENDPOINT") for _, where in flagged)


def test_admission_rejects_forbidden_root_overlap_and_ancestor_instructions(lab, tmp_path):
    inside = admit(lab.ws, lab.env, forbidden_roots=[lab.subjects])
    assert ("forbidden_root", str(lab.ws)) in codes(inside)
    containing = admit(lab.subjects, lab.env, forbidden_roots=[lab.oracle.parent])
    assert ("forbidden_root", str(lab.subjects)) in codes(containing)
    project = Path(os.path.realpath(tmp_path)) / "project"
    project.mkdir()
    (project / "CLAUDE.md").write_text("synthetic parent instructions\n")
    isolation.materialize({"a.txt": b"synthetic"}, project / "s-2")
    assert ("ancestor_marker", str(project)) in codes(admit(project / "s-2", lab.env))
    assert ("not_a_directory", ".") in codes(admit(lab.base / "absent", lab.env))


def test_default_forbidden_roots_include_host_config():
    defaults = isolation.default_forbidden_roots()
    assert {os.path.realpath(Path.home() / d) for d in (".claude", ".codex")} <= set(defaults)


@pytest.mark.skipif(not (REPO_ROOT / ".git").exists(), reason="the repository default needs a git checkout")
def test_default_forbidden_roots_cover_this_checkout(lab):
    assert str(REPO_ROOT) in isolation.default_forbidden_roots()
    repository = admit(REPO_ROOT / "benchmarks" / "governance", lab.env)   # default roots; read-only walk
    assert {code for code, _ in codes(repository)} >= {"forbidden_root", "ancestor_marker"}


def test_repository_roots_resolve_a_relative_gitdir_against_its_git_file(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    (base / "main" / ".git" / "worktrees" / "w").mkdir(parents=True)
    (base / "main" / ".git" / "modules" / "sub").mkdir(parents=True)
    (base / "wt" / "pkg").mkdir(parents=True)
    (base / "wt" / ".git").write_text("gitdir: ../main/.git/worktrees/w\n")      # git worktree --relative-paths
    (base / "main" / "sub" / "pkg").mkdir(parents=True)
    (base / "main" / "sub" / ".git").write_text("gitdir: ../.git/modules/sub\n")   # submodule layout
    monkeypatch.chdir("/")                          # a cwd-relative resolution would find /main
    assert isolation._repository_roots(base / "wt" / "pkg" / "m.py") == [f"{base}/wt", f"{base}/main"]
    assert set(isolation._repository_roots(base / "main" / "sub" / "pkg" / "m.py")) == {f"{base}/main/sub",
                                                                                       f"{base}/main"}


@pytest.mark.parametrize("kw", [{"canaries": []}, {"canaries": [""]}, {"forbidden_sha256": set()},
                                {"forbidden_sha256": {"ABC"}}, {"env": None}, {"forbidden_roots": ["relative"]},
                                {"subject_root": "relative"}])
def test_admission_arguments_fail_closed(lab, kw):
    kw = {"subject_root": lab.ws, "forbidden_sha256": {"0" * 64}, "canaries": [CANARY], "env": lab.env, **kw}
    report = isolation.admission_check(kw.pop("subject_root"), **kw)
    assert report["ok"] is False and [v["code"] for v in report["violations"]] == ["invalid_arguments"]


# --------------------------------------------------------------------------- output reading

def test_read_output_tree_never_follows_links_or_opens_special_files(lab):
    out = lab.ws / "output"
    claims = b'{"synthetic": true}'
    (out / "claims.json").write_bytes(claims)
    (out / "sub").mkdir()
    (out / "sub" / "note.txt").write_bytes(b"synthetic note")
    os.symlink(lab.oracle, out / "evil.json")
    os.symlink(lab.oracle.parent, out / "evil-dir")
    os.link(lab.subjects / "parent-note.txt", out / "linked.txt")
    os.mkfifo(out / "fifo")                         # opening it for reading would block
    files, violations = isolation.read_output_tree(out)
    assert files == {"claims.json": claims, "sub/note.txt": b"synthetic note"}
    assert {(v["code"], v["where"]) for v in violations} == {("symlink", "evil.json"), ("symlink", "evil-dir"),
                                                             ("hardlink", "linked.txt"), ("special_file", "fifo")}
    assert CANARY.encode() in (out / "evil.json").read_bytes()   # positive control: a naive read leaks
    capped, violations = isolation.read_output_tree(out, max_bytes=len(claims) + 1)
    assert capped == {"claims.json": claims} and ("too_large", "sub/note.txt") in codes({"violations": violations})
    assert isolation.read_output_tree(lab.base / "absent")[1][0]["code"] == "not_a_directory"


# --------------------------------------------------------------------------- subject_env

def test_subject_env_is_built_from_scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_LEAK_TOKEN", CANARY)
    monkeypatch.setenv("CLAUDECODE", "1")
    ws = os.path.realpath(tmp_path)
    env = isolation.subject_env(workspace=ws, home=f"{ws}/home", path_dirs=["/usr/bin", f"{ws}/bin"],
                                extra={"RAVEL_TASK_TOKEN": "synthetic-token"})
    assert env == {"HOME": f"{ws}/home", "LANG": "en_US.UTF-8", "PATH": f"/usr/bin:{ws}/bin",
                   "TMPDIR": f"{ws}/tmp", "RAVEL_TASK_TOKEN": "synthetic-token"}


@pytest.mark.parametrize("kw", [{"extra": {"PATH": "/tmp"}}, {"extra": {"A-B": "x"}}, {"extra": {"A": 1}},
                                {"path_dirs": ["usr/bin"]}, {"path_dirs": []}, {"path_dirs": ["/a:/b"]},
                                {"home": "relative"}, {"extra": None}])
def test_subject_env_rejects_bad_input(tmp_path, kw):
    kw = {"workspace": str(tmp_path), "home": str(tmp_path / "h"), "path_dirs": ["/usr/bin"], "extra": {}, **kw}
    with pytest.raises(ContractError):
        isolation.subject_env(**kw)


# --------------------------------------------------------------------------- Seatbelt profile

def test_profile_is_deny_default_and_ends_with_process_denials(tmp_path):
    ws = os.path.realpath(tmp_path)
    policy = isolation.SandboxPolicy(read_roots=[ws, PREFIX], write_roots=[f"{ws}/output"])
    profile = isolation.seatbelt_profile(policy)
    lines = profile.splitlines()
    assert lines[:2] == ["(version 1)", '(deny default (with message "ravel-subject"))']
    assert lines[-4:] == ["(deny process-info*)", "(allow process-info* (target same-sandbox))",
                          '(deny sysctl-read (sysctl-name-prefix "kern.procargs"))',
                          '(deny sysctl-read (sysctl-name-prefix "kern.proc."))']
    assert lines.index('(deny sysctl-read (sysctl-name-prefix "kern.proc."))') > lines.index("(allow sysctl-read)")
    assert "remote tcp" not in profile and "(allow default" not in profile
    assert f'(allow file-write* (subpath "{ws}/output"))' in lines
    reordered = isolation.SandboxPolicy(read_roots=(PREFIX, ws, ws), write_roots=[f"{ws}/output"])
    assert isolation.seatbelt_profile(reordered) == profile


def test_profile_network_localhost_ports_and_deny_roots(tmp_path):
    ws = os.path.realpath(tmp_path)
    (tmp_path / "real").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "real")
    policy = isolation.SandboxPolicy(read_roots=[tmp_path / "alias"], write_roots=[f"{ws}/out"],
                                     deny_roots=[f"{ws}/real/.git"], network="localhost", localhost_ports=[8123, 443],
                                     darwin_user_temp=ws)
    lines = isolation.seatbelt_profile(policy).splitlines()
    assert policy.read_roots == (f"{ws}/real",)
    assert '(allow network-outbound (remote tcp "localhost:443"))' in lines
    assert '(allow network-outbound (remote tcp "localhost:8123"))' in lines
    deny = next(i for i, line in enumerate(lines) if line.startswith("(deny file-read* file-write*"))
    assert f'(subpath "{ws}/real/.git")' in lines[deny]
    allows = ("(allow file-read* (subpath", "(allow file-write*")
    assert deny > max(i for i, line in enumerate(lines) if line.startswith(allows))
    assert any("xcrun_db" in line for line in lines)


def test_policy_follows_the_interface_field_order():
    ws = os.path.realpath("/var/empty")   # any absolute path: never opened
    policy = isolation.SandboxPolicy([ws], [], [], "localhost", [8080])   # §13: read, write, literals, network
    assert (policy.read_roots, policy.network, policy.localhost_ports) == ((ws,), "localhost", (8080,))


def test_policy_roots_may_not_overlap_forbidden_roots(tmp_path):
    base = os.path.realpath(tmp_path)
    store = f"{base}/store"
    for kw in ({"read_roots": [f"{store}/evaluator"]}, {"write_roots": [base]}, {"read_literals": [f"{store}/o.json"]}):
        with pytest.raises(ContractError, match="overlaps forbidden root"):
            isolation.SandboxPolicy(forbidden_roots=[store], **kw)
    with pytest.raises(ContractError, match="overlaps forbidden root"):   # contains the default ~/.claude
        isolation.SandboxPolicy(read_roots=[os.path.realpath(Path.home())])
    policy = isolation.SandboxPolicy(read_roots=[f"{base}/ws"], forbidden_roots=[store])
    assert set(isolation.default_forbidden_roots()) | {store} == set(policy.forbidden_roots)
    deny = next(line for line in isolation.seatbelt_profile(policy).splitlines()
                if line.startswith("(deny file-read* file-write*"))
    assert all(f'(subpath "{root}")' in deny for root in policy.forbidden_roots)


@pytest.mark.parametrize("kw", [{"read_roots": ["relative"]}, {"read_roots": ["/"]}, {"read_roots": "/usr"},
                                {"write_roots": ["/tmp/a\nb"]}, {"network": "internet"},
                                {"network": "localhost"}, {"localhost_ports": [80]},
                                {"network": "localhost", "localhost_ports": [0]},
                                {"network": "localhost", "localhost_ports": [True]},
                                {"forbidden_roots": ["relative"]}])
def test_policy_validation_fails_closed(kw):
    with pytest.raises(ContractError):
        isolation.SandboxPolicy(**kw)


# --------------------------------------------------------------------------- launcher (unsandboxed)

def test_launch_passes_exactly_the_given_environment_and_stdin(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "SYNTHETIC": "value with spaces"}
    result = isolation.launch(["/usr/bin/env", "-0"], cwd=tmp_path, env=env, profile=None, timeout_s=30,
                              stdout_path=tmp_path / "env.out", stderr_path=tmp_path / "env.err")
    assert (result.exit_code, result.timed_out, result.killed, result.survivors) == (0, False, False, [])
    seen = dict(item.split("=", 1) for item in (tmp_path / "env.out").read_text().split("\0") if item)
    assert seen == env
    (tmp_path / "stdin.txt").write_bytes(b"synthetic stdin")
    code = "import sys; data = sys.stdin.buffer.read(); print(len(data)); sys.stderr.write('synthetic'); sys.exit(3)"
    piped = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                             stdout_path=tmp_path / "a.out", stderr_path=tmp_path / "a.err",
                             stdin_path=tmp_path / "stdin.txt")
    assert piped.exit_code == 3 and (tmp_path / "a.out").read_text() == "15\n"
    assert (tmp_path / "a.err").read_text() == "synthetic"
    default = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                               stdout_path=tmp_path / "b.out", stderr_path=tmp_path / "b.err")
    assert default.exit_code == 3 and (tmp_path / "b.out").read_text() == "0\n"   # stdin is /dev/null


def test_launch_streams_large_input_and_output_through_pipes(tmp_path):
    data = bytes(range(256)) * 1200                 # 300 KiB: several pipe buffers each way
    (tmp_path / "in.bin").write_bytes(data)
    code = ("import sys; d = sys.stdin.buffer.read(); sys.stdout.buffer.write(d); "
            "sys.stderr.buffer.write(d[::-1])")
    result = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                              stdout_path=tmp_path / "o", stderr_path=tmp_path / "e", stdin_path=tmp_path / "in.bin")
    assert result.exit_code == 0
    assert (tmp_path / "o").read_bytes() == data and (tmp_path / "e").read_bytes() == data[::-1]


def test_subject_cannot_rewrite_or_name_its_stream_files(tmp_path):
    (tmp_path / "request.json").write_text(json.dumps({"needle": CANARY, "probes": [["stdio", ""]]}))
    (tmp_path / "probe.py").write_text(PROBE)
    argv = [PYTHON, "-I", "-S", "-B", str(tmp_path / "probe.py")]
    result = isolation.launch(argv, cwd=tmp_path, env={}, profile=None, timeout_s=30, stdout_path=tmp_path / "o",
                              stderr_path=tmp_path / "e", stdin_path=tmp_path / "request.json")
    [report] = json.loads((tmp_path / "o").read_text())
    assert result.exit_code == 0 and report["ok"]
    for fd in (0, 1, 2):                            # a pipe: no offset, no size, no coordinator path
        assert report[f"seek{fd}"] == {"errno": errno.ESPIPE} and "ok" not in report[f"truncate{fd}"]
        assert os.path.realpath(tmp_path) not in json.dumps(report[f"path{fd}"])
    with open(tmp_path / "request.json", "rb") as fin, open(tmp_path / "c.out", "wb") as fout:
        subprocess.run(argv, stdin=fin, stdout=fout, stderr=subprocess.DEVNULL, env={}, check=True)
    [control] = json.loads((tmp_path / "c.out").read_text())   # positive control: descriptors of files
    assert control["seek1"] == {"ok": 0} and control["truncate1"] == {"ok": None}
    assert control["path1"] == {"ok": os.path.realpath(tmp_path / "c.out")}


def test_launch_closes_inherited_descriptors(tmp_path):
    secret = tmp_path / "oracle.txt"
    secret.write_text(CANARY)
    fd, inherited = os.open(secret, os.O_RDONLY), free_fd()
    os.dup2(fd, inherited, inheritable=True)
    code = (f"import os\ntry:\n    print({CANARY.encode()!r} in os.read({inherited}, 4096))\n"
            "except OSError as exc:\n    print('errno', exc.errno)")
    try:
        result = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                                  stdout_path=tmp_path / "fd.out", stderr_path=tmp_path / "fd.err")
        control = subprocess.run([PYTHON, "-I", "-S", "-c", code], pass_fds=(inherited,), capture_output=True,
                                 text=True)
    finally:
        os.close(inherited)
        os.close(fd)
    assert result.exit_code == 0 and (tmp_path / "fd.out").read_text() == f"errno {errno.EBADF}\n"
    assert control.stdout == "True\n"               # positive control: an inherited fd does leak


def test_timeout_kills_the_group_including_a_double_forked_grandchild(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.5)
    pidfile = tmp_path / "grandchild.pid"
    result = isolation.launch([PYTHON, "-I", "-S", "-c", DOUBLE_FORK, str(pidfile)], cwd=tmp_path, env={},
                              profile=None, timeout_s=1.5, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert result.timed_out and result.killed and result.survivors == []
    assert result.exit_code == -signal.SIGTERM and result.wall_seconds >= 1.5
    assert gone(int(pidfile.read_text()))           # it ran: it wrote its pid before the kill


def test_timeout_escalates_to_sigkill_for_a_leader_ignoring_sigterm(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.3)
    code = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
    result = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=0.5,
                              stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert result.timed_out and result.killed and result.survivors == [] and result.exit_code == -signal.SIGKILL


def test_timeout_stops_a_forking_chain_that_ignores_sigterm(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.2)
    for attempt in range(3):                        # a single SIGKILL lost this race in 5 of 8 runs
        log = tmp_path / f"chain-{attempt}.log"
        try:
            result = isolation.launch([PYTHON, "-I", "-S", "-c", FORK_CHAIN, "group", str(log), "1"], cwd=tmp_path,
                                      env={}, profile=None, timeout_s=0.8, stdout_path=tmp_path / f"o{attempt}",
                                      stderr_path=tmp_path / f"e{attempt}")
            records = chain_records(log)
            assert len(records) > 2                 # the chain was forking when the wall limit came
            assert result.timed_out and result.killed and result.survivors == []
            with pytest.raises(ProcessLookupError):
                os.killpg(records[0][0], 0)
        finally:
            deadline = time.monotonic() + 5         # cleanup, effective only if an assertion failed
            while log.exists() and time.monotonic() < deadline:
                try:
                    os.killpg(int(log.read_text().split()[0]), signal.SIGKILL)
                except ProcessLookupError:
                    break


def test_processes_left_behind_after_a_normal_exit_are_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.3)
    pidfile = tmp_path / "orphan.pid"
    code = ("import os, sys, time\nif os.fork() == 0:\n    open(sys.argv[1], 'w').write(str(os.getpid()))\n"
            "    time.sleep(30)\n    os._exit(0)\n"
            "while not os.path.exists(sys.argv[1]) or not open(sys.argv[1]).read():\n    time.sleep(0.01)\n")
    result = isolation.launch([PYTHON, "-I", "-S", "-c", code, str(pidfile)], cwd=tmp_path, env={}, profile=None,
                              timeout_s=30, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert (result.exit_code, result.timed_out, result.killed, result.survivors) == (0, False, True, [])
    assert gone(int(pidfile.read_text()))


def test_unsandboxed_census_covers_the_process_group_only(tmp_path):
    """Documented limit of profile None: a setsid child is outside the group and outlives the
    launch unseen. Sandboxed launches find it (test_sandboxed_launch_kills_a_setsid_escapee)."""
    pidfile = tmp_path / "escapee.pid"
    try:
        result = isolation.launch([PYTHON, "-I", "-S", "-c", SETSID_CHILD, str(pidfile)], cwd=tmp_path, env={},
                                  profile=None, timeout_s=30, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
        assert (result.exit_code, result.killed, result.survivors) == (0, False, [])
        os.kill(int(pidfile.read_text()), 0)        # still alive: raises ProcessLookupError otherwise
    finally:
        if pidfile.exists():
            kill_quietly(int(pidfile.read_text()))


def test_interrupted_coordinator_still_kills_the_subject(tmp_path, monkeypatch):
    pidfile = tmp_path / "subject.pid"
    code = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"
    real, calls = isolation._terminate, []

    def interrupted(proc, watch, grace):
        calls.append(grace)
        if len(calls) == 1:
            raise KeyboardInterrupt                 # e.g. Ctrl-C while the launcher waits on the grace
        return real(proc, watch, grace)
    monkeypatch.setattr(isolation, "_terminate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        isolation.launch([PYTHON, "-I", "-S", "-c", code, str(pidfile)], cwd=tmp_path, env={}, profile=None,
                         timeout_s=1.0, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert calls == [isolation.TERM_GRACE_S, 0.0] and gone(int(pidfile.read_text()))


def test_census_reports_a_live_group_member():
    proc = subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)"], start_new_session=True)
    try:
        assert isolation._census(isolation._Watch(proc.pid, None, 0.0, None), 0.2) == [proc.pid]   # not vacuous
    finally:
        proc.kill()
        proc.wait()
    assert isolation._census(isolation._Watch(proc.pid, None, 0.0, None), 2.0) == []


BAD_LAUNCH = {
    "shell string": lambda t: {"argv": "echo synthetic"},
    "relative program": lambda t: {"argv": ["echo", "synthetic"]},
    "missing program": lambda t: {"argv": [str(t / "absent")]},
    "non-executable program": lambda t: {"argv": [str(t / "exists")]},
    "empty argv": lambda t: {"argv": []},
    "inherited env": lambda t: {"env": None},
    "zero timeout": lambda t: {"timeout_s": 0},
    "nan timeout": lambda t: {"timeout_s": float("nan")},
    "bool timeout": lambda t: {"timeout_s": True},
    "same outputs": lambda t: {"stderr_path": t / "o"},
    "existing output": lambda t: {"stdout_path": t / "exists"},
    "relative cwd": lambda t: {"cwd": "relative"},
    "missing stdin": lambda t: {"stdin_path": t / "absent"},
    "allow-default profile": lambda t: {"profile": "(version 1)(allow default)"},
    "deny-then-allow-default profile": lambda t: {"profile": "(version 1)(deny default)\n(allow  default)"},
}


@pytest.mark.parametrize("case", sorted(BAD_LAUNCH))
def test_launch_rejects_unsafe_arguments(tmp_path, case):
    (tmp_path / "exists").write_text("synthetic")
    kw = {"argv": ["/bin/echo", "synthetic"], "cwd": tmp_path, "env": {}, "profile": None, "timeout_s": 5,
          "stdout_path": tmp_path / "o", "stderr_path": tmp_path / "e", **BAD_LAUNCH[case](tmp_path)}
    with pytest.raises(ContractError, match="deny-default" if case.endswith("profile") else None):
        isolation.launch(kw.pop("argv"), **kw)
    assert not (tmp_path / "o").exists() or case == "existing output"


def test_sandboxed_launch_refuses_to_run_without_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "sandbox_available", lambda: False)
    profile = isolation.seatbelt_profile(isolation.SandboxPolicy(read_roots=[os.path.realpath(tmp_path)]))
    with pytest.raises(ContractError, match="unavailable"):
        isolation.launch(["/bin/echo"], cwd=tmp_path, env={}, profile=profile, timeout_s=5,
                         stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert not (tmp_path / "o").exists()


# --------------------------------------------------------------------------- allowlist proxy

def connect_via(port, target, payload=None):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        status = sock.recv(4096).split(b"\r\n", 1)[0].decode()
        echoed = None
        if payload is not None and " 200 " in status + " ":
            sock.sendall(payload)
            echoed = sock.recv(4096)
        return status, echoed


def test_proxy_tunnels_only_allowlisted_local_targets(tmp_path):
    allowed, other = EchoServer(), EchoServer()
    log = tmp_path / "proxy.jsonl"
    try:
        with allowlist_proxy.AllowlistProxy([f"127.0.0.1:{allowed.port}"], log_path=log) as proxy:
            assert connect_via(proxy.port, f"127.0.0.1:{allowed.port}", b"synthetic ping") == \
                ("HTTP/1.1 200 Connection Established", b"synthetic ping")
            assert connect_via(proxy.port, f"127.0.0.1:{other.port}")[0] == "HTTP/1.1 403 Forbidden"
            assert connect_via(proxy.port, f"localhost:{allowed.port}")[0] == "HTTP/1.1 403 Forbidden"
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
                sock.sendall(f"GET http://127.0.0.1:{allowed.port}/ HTTP/1.1\r\n\r\n".encode())
                assert sock.recv(64).startswith(b"HTTP/1.1 403")
            assert connect_via(proxy.port, "bad_host!:80")[0] == "HTTP/1.1 400 Bad Request"
            with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
                sock.sendall(b"CONNECT " + b"a" * (allowlist_proxy.MAX_HEADER_BYTES + 10))
                assert sock.recv(64).startswith(b"HTTP/1.1 400")
            assert other.accepted == 0                  # the denied peer never saw a connection ...
            socket.create_connection(("127.0.0.1", other.port), timeout=5).close()
            assert wait_for(lambda: other.accepted == 1)   # ... although it was reachable directly
            assert allowed.accepted == 1
    finally:
        allowed.close()
        other.close()
    records, error = read_jsonl(log)
    assert error is None and records == proxy.decisions
    assert [(r["decision"], r["reason"]) for r in records] == [
        ("allow", "allowlisted"), ("deny", "not_allowlisted"), ("deny", "not_allowlisted"),
        ("deny", "not_connect"), ("deny", "malformed_target"), ("deny", "malformed_or_oversized_request")]
    assert [r["seq"] for r in records] == list(range(1, 7))
    assert records[1]["target"] == f"127.0.0.1:{other.port}"


def test_proxy_logs_one_decision_for_every_request(tmp_path, monkeypatch):
    log = tmp_path / "proxy.jsonl"
    with allowlist_proxy.AllowlistProxy(["127.0.0.1:9"], log_path=log) as proxy:
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
            sock.sendall(b"CONNECT 127.0.0.1:\xb2 HTTP/1.1\r\n\r\n")   # Latin-1 superscript two
            assert sock.recv(64).startswith(b"HTTP/1.1 400")

        def broken(text):
            raise RuntimeError("synthetic parser fault")
        monkeypatch.setattr(allowlist_proxy, "parse_target", broken)
        with socket.create_connection(("127.0.0.1", proxy.port), timeout=5) as sock:
            sock.sendall(b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n")
            assert sock.recv(64) == b""                 # dropped, but not silently
    records = read_jsonl(log)[0]
    assert [(r["decision"], r["reason"]) for r in records] == [
        ("deny", "malformed_target"), ("error", "internal_error: RuntimeError")]


def test_proxy_allowlist_parsing():
    assert allowlist_proxy.parse_allow(["API.Example.org:443", "[::1]:8080"]) == \
        frozenset({("api.example.org", 443), ("::1", 8080)})
    assert allowlist_proxy.parse_target("127.0.0.1:\u00b2") is None
    for bad in (["example.org"], ["example.org:0"], ["example.org:70000"], ["user@example.org:443"], [], "x:1", [7],
                ["example.org:\u00b2"], ["example.org:\u0664\u0664\u0663"]):
        with pytest.raises(ContractError):
            allowlist_proxy.parse_allow(bad)


def test_proxy_command_line_entry_point(tmp_path):
    script = str(REPO_ROOT / "benchmarks" / "governance" / "allowlist_proxy.py")
    log = tmp_path / "cli.jsonl"
    proc = subprocess.Popen([sys.executable, script, "--log", str(log), "127.0.0.1:9"], stdout=subprocess.PIPE,
                            text=True)
    try:
        line = proc.stdout.readline()
        assert line.startswith("listening 127.0.0.1:")
        assert connect_via(int(line.rsplit(":", 1)[1]), "127.0.0.1:10")[0] == "HTTP/1.1 403 Forbidden"
    finally:
        proc.terminate()
        assert proc.wait(timeout=10) == 0
    assert [r["decision"] for r in read_jsonl(log)[0]] == ["deny"]
    bad = subprocess.run([sys.executable, script, "--log", str(log), "example.org:\u00b2"], capture_output=True,
                         text=True, timeout=30)
    assert bad.returncode == 2 and "Traceback" not in bad.stderr and "allow:" in bad.stderr


# --------------------------------------------------------------------------- Seatbelt integration

@needs_sandbox
def test_sandbox_denies_reads_outside_the_workspace(lab):
    targets = [("read", str(lab.oracle)), ("stat", str(lab.oracle)), ("list", str(lab.oracle.parent)),
               ("read", str(lab.subjects / "parent-note.txt")), ("list", str(lab.subjects)),
               ("read", str(lab.repo / "AGENTS.md")), ("read", str(lab.repo / ".git" / "HEAD")),
               ("read", str(lab.packet / "README.md")), ("list", str(lab.packet)),
               ("read", str(REPO_ROOT / "tests" / "governance" / "conftest.py"))]
    for ancestor in [REPO_ROOT, *REPO_ROOT.parents]:   # real repository and parent instruction files
        targets += [("read", str(ancestor / m)) for m in ("CLAUDE.md", "AGENTS.md") if (ancestor / m).is_file()]
    inside, raw = probe(lab, [("read", str(lab.ws / "request.md"))] + targets, profile=profile_for(lab))
    control, _ = probe(lab, targets, profile=None)
    assert inside[0] == {"ok": True, "found": False}   # the probe itself works inside the sandbox
    for target, got, free in zip(targets, inside[1:], control):
        assert free["ok"], f"positive control failed for {target}: {free}"
        assert denied(got), f"not a sandbox denial for {target}: {got}"
    assert [r.get("found") for r in control[:1]] == [True] and CANARY not in raw


@needs_sandbox
@pytest.mark.parametrize("name", [".claude", ".codex"])
def test_sandbox_denies_host_config_dirs(lab, name):
    target = Path.home() / name
    if not target.is_dir():
        pytest.skip(f"{target} is absent on this host, so its denial is not exercised here")
    files = sorted(p for p in target.iterdir() if p.is_file())[:1]   # metadata only: never read host files
    targets = [("list", str(target))] + [("stat", str(p)) for p in files]
    inside, _ = probe(lab, targets, profile=profile_for(lab))
    control, _ = probe(lab, targets, profile=None)
    assert all(free["ok"] for free in control) and all(denied(got) for got in inside), (inside, control)


@needs_sandbox
def test_symlink_escape_is_rejected_by_admission_and_denied_by_the_sandbox(lab):
    os.symlink(lab.oracle, lab.ws / "inputs" / "prior.json")
    assert ("symlink", "inputs/prior.json") in codes(admit(lab.ws, lab.env))
    link = str(lab.ws / "inputs" / "prior.json")
    [inside], _ = probe(lab, [("read", link)], profile=profile_for(lab))
    [free], _ = probe(lab, [("read", link)], profile=None)
    assert denied(inside) and free == {"ok": True, "found": True}


@needs_sandbox
def test_subject_planted_symlink_is_not_followed_when_reading_output(lab):
    claims = lab.ws / "output" / "claims.json"
    [planted], _ = probe(lab, [("symlink", f"{lab.oracle} {claims}")], profile=profile_for(lab))
    assert planted == {"ok": True} and claims.is_symlink()   # the sandbox does not stop this
    files, violations = isolation.read_output_tree(lab.ws / "output")
    assert files == {} and [(v["code"], v["where"]) for v in violations] == [("symlink", "claims.json")]


@needs_sandbox
def test_hardlink_injection_is_rejected_and_would_otherwise_leak(lab):
    os.link(lab.oracle, lab.ws / "inputs" / "prior.json")
    report = admit(lab.ws, lab.env, forbidden_sha256={sha256_bytes(lab.oracle.read_bytes())})
    assert {("hardlink", "inputs/prior.json"), ("canary", "inputs/prior.json"),
            ("forbidden_content", "inputs/prior.json")} <= codes(report)
    # Were it admitted, the sandbox would not stop it: path rules see the workspace name.
    via_link, direct = probe(lab, [("read", str(lab.ws / "inputs" / "prior.json")), ("read", str(lab.oracle))],
                             profile=profile_for(lab))[0]
    assert via_link == {"ok": True, "found": True} and denied(direct)


@needs_sandbox
def test_inherited_descriptor_is_unusable_inside_the_sandbox(lab):
    profile = profile_for(lab)
    fd, inherited = os.open(lab.oracle, os.O_RDONLY), free_fd()
    os.dup2(fd, inherited, inheritable=True)
    request = lab.coord / "fd-request.json"
    request.write_text(json.dumps({"needle": CANARY, "probes": [["fd", str(inherited)]]}))
    try:
        [inside], _ = probe(lab, [("fd", str(inherited))], profile=profile)
        with open(request, "rb") as stdin:              # positive control: same sandbox, fd passed on
            control = subprocess.run([isolation.SANDBOX_EXEC, "-p", profile, PYTHON, "-I", "-S", "-B",
                                      str(lab.ws / "probe.py")], cwd=lab.ws, env=lab.env, stdin=stdin,
                                     pass_fds=(inherited,), capture_output=True, text=True, timeout=60)
    finally:
        os.close(inherited)
        os.close(fd)
    assert inside == {"ok": False, "errno": errno.EBADF}
    assert json.loads(control.stdout) == [{"ok": True, "found": True}]


@needs_sandbox
def test_sandboxed_subject_cannot_rewrite_or_name_its_stream_files(lab):
    [inside], raw = probe(lab, [("stdio", "")], profile=profile_for(lab))
    assert inside["ok"] and all(inside[f"seek{fd}"] == {"errno": errno.ESPIPE} for fd in (0, 1, 2))
    assert not any("ok" in inside[f"{op}{fd}"] for op in ("truncate", "path") for fd in (0, 1, 2))
    request = lab.coord / "stdio-request.json"
    request.write_text(json.dumps({"needle": CANARY, "probes": [["stdio", ""]]}))
    with open(request, "rb") as fin, open(lab.coord / "stdio-control.out", "wb") as fout:   # file descriptors,
        subprocess.run([isolation.SANDBOX_EXEC, "-p", profile_for(lab), PYTHON, "-I", "-S", "-B",   # as before
                        str(lab.ws / "probe.py")], cwd=lab.ws, env=lab.env, stdin=fin, stdout=fout,
                       stderr=subprocess.DEVNULL, timeout=60)
    [control] = json.loads((lab.coord / "stdio-control.out").read_text())
    assert control["seek1"] == {"ok": 0} and control["path1"] == {"ok": str(lab.coord / "stdio-control.out")}
    assert str(lab.coord) not in raw                # positive control above: the sandbox alone does not stop it


@needs_sandbox
def test_other_process_argv_and_process_table_are_invisible(lab):
    outside = subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)", SECRET],
                               env={"SYNTHETIC_ENV": SECRET + "-env"})
    try:
        probes = [("pids", str(outside.pid)), ("procargs", str(outside.pid)), ("ps", ""),
                  ("kinfo", str(outside.pid))]
        inside, raw = probe(lab, probes, profile=profile_for(lab), needle=SECRET)
        control, _ = probe(lab, probes, profile=None, needle=SECRET)
    finally:
        outside.kill()
        outside.wait()
    assert control[0]["listed"] and control[1] == {"ok": True, "found": True} and control[2]["found"]
    assert control[3] == {"ok": True, "listed": True}
    assert inside[0]["ok"] and not inside[0]["listed"]   # proc_listallpids: the pid is not returned
    assert denied(inside[1])                        # KERN_PROCARGS2: argv and environment
    assert denied(inside[2])                        # /bin/ps (setuid) cannot even be executed
    assert denied(inside[3])                        # KERN_PROC_ALL: process table
    assert not any(r.get("found") for r in inside) and SECRET not in raw


@needs_sandbox
def test_network_is_limited_to_declared_localhost_ports(lab):
    allowed, other = socket.socket(), socket.socket()
    for sock in (allowed, other):
        sock.bind(("127.0.0.1", 0))
        sock.listen(16)
    a, b = (f"127.0.0.1:{s.getsockname()[1]}" for s in (allowed, other))
    try:
        none, _ = probe(lab, [("connect", a)], profile=profile_for(lab))
        local, _ = probe(lab, [("connect", a), ("connect", b)],
                         profile=profile_for(lab, network="localhost", ports=[allowed.getsockname()[1]]))
        free, _ = probe(lab, [("connect", a), ("connect", b)], profile=None)
    finally:
        allowed.close()
        other.close()
    assert free[0]["ok"] and free[1]["ok"]          # positive controls: both local servers reachable
    assert all(denied(r) for r in none)
    assert local[0] == {"ok": True} and denied(local[1])


@needs_sandbox
def test_network_denies_a_non_loopback_address(lab):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:   # UDP connect sends no packet
        try:
            udp.connect(("192.0.2.1", 9))
            lan = udp.getsockname()[0]
        except OSError:
            lan = None
    if not lan or lan.startswith("127.") or lan == "0.0.0.0":
        pytest.skip("no non-loopback IPv4 address on this host; the non-local probe is not exercised")
    with socket.socket() as server:                 # our own address: never leaves the host
        server.bind((lan, 0))
        server.listen(4)
        port = server.getsockname()[1]
        target = [("connect", f"{lan}:{port}")]
        none, _ = probe(lab, target, profile=profile_for(lab))
        other, _ = probe(lab, target, profile=profile_for(lab, network="localhost", ports=[port % 65535 + 1]))
        same, _ = probe(lab, target, profile=profile_for(lab, network="localhost", ports=[port]))
        free, _ = probe(lab, target, profile=None)
    assert free == [{"ok": True}]                   # positive control: reachable without the sandbox
    assert denied(none[0]) and denied(other[0])
    # Observed Seatbelt semantics (macOS 15.5): "localhost:<port>" also admits this host's own
    # non-loopback address on that port. Traffic stays on the host; recorded, not relied on.
    assert same == [{"ok": True}]


@needs_sandbox
def test_allowlist_proxy_is_the_only_route_out(lab, tmp_path):
    target, blocked = EchoServer(), EchoServer()
    try:
        with allowlist_proxy.AllowlistProxy([f"127.0.0.1:{target.port}"], log_path=tmp_path / "p.jsonl") as proxy:
            probes = [("proxy", f"{proxy.port} 127.0.0.1:{target.port}"),
                      ("proxy", f"{proxy.port} 127.0.0.1:{blocked.port}"),
                      ("connect", f"127.0.0.1:{target.port}")]
            inside, _ = probe(lab, probes, profile=profile_for(lab, network="localhost", ports=[proxy.port]))
            free, _ = probe(lab, probes[2:], profile=None)
    finally:
        target.close()
        blocked.close()
    assert inside[0] == {"ok": True, "status": "200"} and inside[1] == {"ok": True, "status": "403"}
    assert denied(inside[2]) and free == [{"ok": True}]
    assert blocked.accepted == 0
    assert [r["decision"] for r in proxy.decisions] == ["allow", "deny"]


@needs_sandbox
def test_writes_are_confined_to_write_roots(lab):
    def targets(tag):
        return [("write", str(p / f"probe-{tag}.txt")) for p in
                (lab.outside, lab.ws, lab.ws / "inputs", lab.subjects, lab.ws / "output", lab.ws / "tmp", lab.home)]
    inside, _ = probe(lab, targets("sandboxed"), profile=profile_for(lab))
    free, _ = probe(lab, targets("control"), profile=None)
    assert all(r["ok"] for r in free)                # positive controls: all writable without the sandbox
    assert all(denied(r) for r in inside[:4]), inside
    assert inside[4:] == [{"ok": True}] * 3
    assert not (lab.outside / "probe-sandboxed.txt").exists()


@needs_sandbox
def test_environment_inside_is_exactly_subject_env(lab):
    out, err = lab.coord / "env.out", lab.coord / "env.err"
    result = isolation.launch(["/usr/bin/env", "-0"], cwd=lab.ws, env=lab.env, profile=profile_for(lab),
                              timeout_s=30, stdout_path=out, stderr_path=err)
    assert result.exit_code == 0, err.read_text()
    assert dict(item.split("=", 1) for item in out.read_text().split("\0") if item) == lab.env
    assert admit(lab.ws, lab.env)["ok"]


@needs_sandbox
def test_deny_roots_and_read_literals(lab):
    literal = lab.outside / "allowed.txt"
    literal.write_text(f"synthetic {CANARY}")
    (lab.outside / "neighbour.txt").write_text(f"synthetic {CANARY}")
    profile = profile_for(lab, read_literals=[literal], deny_roots=[lab.ws / "inputs"])
    got, _ = probe(lab, [("read", str(literal)), ("read", str(lab.outside / "neighbour.txt")),
                         ("read", str(lab.ws / "inputs" / "workspace.json"))], profile=profile)
    assert got[0] == {"ok": True, "found": True} and denied(got[1]) and denied(got[2])


@needs_sandbox
def test_subject_cannot_open_the_users_terminals(lab):
    """A pty slave is owned by the user (mode 0620), like every Terminal or Claude Code tab: under the
    former profile (/dev readable as a tree, read-write on ^/dev/ttys) a subject opened one by name, read
    the keystrokes queued on it and wrote into it. SYNTHETIC: the test's own pty pair, a canary line queued
    as typed input. The same probe reads it without the sandbox; inside, every terminal path is denied,
    and so are /dev/tty, pty allocation and listing /dev (which names the live terminals)."""
    master, slave = os.openpty()
    name = os.ttyname(slave)
    try:
        assert os.stat(name).st_uid == os.getuid()        # the user's own terminal, as a real one is
        os.write(master, f"{CANARY}\n".encode())          # "typed": waiting on the slave's input queue
        targets = [("ttyread", name), ("open", f"{name} ro"), ("open", f"{name} wo"), ("stat", name),
                   ("openpty", ""), ("open", "/dev/ptmx rw"), ("list", "/dev")]
        inside, raw = probe(lab, targets + [("open", "/dev/tty rw")], profile=profile_for(lab))
        control, _ = probe(lab, targets + [("open", "/dev/tty rw")], profile=None)
    finally:
        os.close(master)
        os.close(slave)
    assert all(denied(got) for got in inside), inside
    assert CANARY not in raw
    assert control[0] == {"ok": True, "found": True}      # positive control: the keystrokes were still queued
    assert all(free["ok"] for free in control[1:len(targets)]), control
    assert control[-1] == {"ok": False, "errno": errno.ENXIO}   # no controlling terminal: not a denial


@needs_sandbox
def test_subject_devices_are_the_listed_ones_and_its_own_descriptors(lab):
    """What a subject may still open: null, zero, random, urandom and its own descriptors (/dev/fd and
    the /dev/std* links into it); /dev itself only by metadata. /dev/dtracehelper is denied (not needed)."""
    [dtrace], _ = probe(lab, [("open", "/dev/dtracehelper rw")], profile=profile_for(lab))
    [free], _ = probe(lab, [("open", "/dev/dtracehelper rw")], profile=None)
    assert denied(dtrace) and free == {"ok": True}
    targets = [("open", "/dev/null rw"), ("open", "/dev/zero ro"), ("open", "/dev/random ro"),
               ("open", "/dev/urandom ro"), ("open", "/dev/stdout wo"), ("open", "/dev/fd/2 wo"),
               ("list", "/dev/fd"), ("stat", "/dev")]
    inside, _ = probe(lab, targets, profile=profile_for(lab))
    assert all(got["ok"] for got in inside), inside


@needs_sandbox
def test_posix_shared_memory_and_named_semaphores_are_denied(lab):
    """POSIX shared memory and named semaphores outlive a run and cannot be enumerated: under the former
    profile one subject left a canary in a named object and a later subject in another workspace read it.
    SYNTHETIC: the test plays the earlier run (an object holding the canary, made outside the sandbox).
    Without the sandbox the probe reads it and creates both kinds; inside, all three are denied."""
    import _multiprocessing
    import _posixshmem
    import mmap
    tag = os.urandom(5).hex()
    left, made, sem = f"/rv-left-{tag}", f"/rv-made-{tag}", f"/rv-sem-{tag}"
    fd = _posixshmem.shm_open(left, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    try:
        os.ftruncate(fd, 4096)
        with mmap.mmap(fd, 4096) as shared:
            shared[:len(CANARY)] = CANARY.encode()
        os.close(fd)
        targets = [("shm_read", left), ("shm_create", made), ("sem_create", sem)]
        inside, raw = probe(lab, targets, profile=profile_for(lab))
        control, _ = probe(lab, targets, profile=None)
    finally:
        for unlink, name in ((_posixshmem.shm_unlink, left), (_posixshmem.shm_unlink, made),
                             (_multiprocessing.sem_unlink, sem)):
            try:
                unlink(name)
            except OSError:
                pass
    assert all(denied(got) for got in inside), inside
    assert CANARY not in raw
    assert control == [{"ok": True, "found": True}, {"ok": True}, {"ok": True}]   # positive controls


def test_profile_grants_no_terminal_device_tree_or_writable_ipc(tmp_path):
    """Profile text (every platform): no /dev subtree, no terminal or pty rule, no unrestricted POSIX
    shared memory and no named semaphores."""
    profile = isolation.seatbelt_profile(isolation.SandboxPolicy(read_roots=[os.path.realpath(tmp_path)]))
    assert '(subpath "/dev")' not in profile and "ttys" not in profile and "ptmx" not in profile
    assert '"/dev/tty"' not in profile and "pseudo-tty" not in profile and "dtracehelper" not in profile
    assert "ipc-posix-sem" not in profile and "(allow ipc-posix-shm)" not in profile
    ipc = [line for line in profile.splitlines() if "ipc-posix" in line]
    assert ipc == ['(allow ipc-posix-shm-read* (ipc-posix-name "apple.shm.notification_center") '
                   '(ipc-posix-name-prefix "apple.cfprefs."))']


# --------------------------------------------------------------------------- System V IPC residue

SYSV_KINDS = ("shm", "msg", "sem")
SYSV_LETTER = {"shm": "m", "msg": "q", "sem": "s"}

SYSV_SUBJECT = r'''
import ctypes, os, sys, time
libc = ctypes.CDLL(None, use_errno=True)
libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
shm, msg, sem = (int(k) for k in sys.argv[2:5])
ids = [libc.shmget(shm, 4096, 0o1600), libc.msgget(msg, 0o1600), libc.semget(sem, 1, 0o1600)]   # IPC_CREAT|0600
with open(sys.argv[1] + ".tmp", "w") as handle:
    handle.write(" ".join(map(str, ids)))
os.rename(sys.argv[1] + ".tmp", sys.argv[1])
time.sleep(30)
'''

IPCS_SAMPLE = """IPC status from <running system> as of Fri Sep 25 20:58:12 EDT 2026
T  ID  KEY  MODE  OWNER  GROUP  CREATOR  CGROUP CBYTES QNUM QBYTES LSPID LRPID  STIME  RTIME  CTIME
Message Queues:
q 131072 0x0d868121 --rw-r----- subject staff subject staff    0    0  2048     0     0 no-entry no-entry 20:58:12

T  ID  KEY  MODE  OWNER  GROUP  CREATOR  CGROUP NATTCH SEGSZ  CPID  LPID  ATIME  DTIME  CTIME
Shared Memory:
m 196611 0x0d868120 --rw------- subject staff subject staff    0  4096 37378     0 no-entry no-entry  9:58:12

T  ID  KEY  MODE  OWNER  GROUP  CREATOR  CGROUP NSEMS  OTIME  CTIME
Semaphores:
s 131072 0x0d868122 --ra------- subject staff subject staff    3 no-entry 20:58:12

"""   # SYNTHETIC, the columns of macOS 15.5's `ipcs -a` (padding narrowed)


def sysv_keys(count):
    """`count` fresh random System V keys (SYNTHETIC: positive, never IPC_PRIVATE)."""
    base = (int.from_bytes(os.urandom(3), "big") << 4) | 0x10000000
    return [base + i for i in range(count)]


def sysv_with_key(key):
    """(kind, id) of every System V object on the host with this key."""
    return sorted(k for k, row in isolation._sysv_objects().items() if int(row["KEY"], 0) == key)


def remove_sysv_keys(keys):
    """Cleanup of the test's own synthetic objects, by key; kinds with no such key are ignored."""
    for key in keys:
        for flag in ("-M", "-Q", "-S"):
            subprocess.run([isolation.IPCRM, flag, str(key)], capture_output=True, timeout=30, check=False)


def no_ipc_listing():
    raise isolation.IpcUnavailable("SYNTHETIC: no System V IPC listing")


@needs_sandbox
def test_a_subjects_system_v_ipc_objects_never_reach_a_later_launch(lab):
    """R4.2, as reviewed: no profile can deny creating a System V object (XNU asks the sandbox only about existing
    ones), and one outlives its creator. A later sandboxed lookup of an agreed key fails with EPERM when an object
    exists and ENOENT when none does, so existence alone carried a byte from one run to the next (the reviewer's
    probe: run 1 left segments at 4 of 8 keys, run 2 decoded 0xA5). SYNTHETIC: run 1 creates a segment, a queue and
    a semaphore set at random keys; its launcher removes all three before returning (ipc_residue, cleared); run 2
    finds nothing at those keys. The test plays a leftover no launcher removed (objects it creates in an unsandboxed
    probe): run 2 sees each one (EPERM), which is what it saw of run 1's objects before the fix, and no launcher
    removes an object that is older than its launch."""
    made, left = (dict(zip(SYSV_KINDS, sysv_keys(3))) for _ in range(2))

    def at(op, keys):
        return [(op, f"{kind} {key}") for kind, key in keys.items()]
    launched = []
    try:
        planted, _ = probe(lab, at("sysv_create", left), profile=None, launched=launched)   # the leftover (the test's)
        first, _ = probe(lab, at("sysv_create", made), profile=profile_for(lab), launched=launched)   # run 1
        made_after_first = [sysv_with_key(key) for key in made.values()]
        second, _ = probe(lab, at("sysv_lookup", made) + at("sysv_lookup", left), profile=profile_for(lab),
                          launched=launched)                                                 # run 2
        left_after = [sysv_with_key(key) for key in left.values()]
    finally:
        remove_sysv_keys([*made.values(), *left.values()])
    assert all(got["ok"] for got in planted + first), (planted, first)   # creating one is never a sandbox check
    assert second[:3] == [{"ok": False, "errno": errno.ENOENT}] * 3, second   # run 2: nothing where run 1 left any
    assert all(denied(got) for got in second[3:]), second               # positive control: a leftover is seen
    assert made_after_first == [[], [], []]
    ids = {kind: got["id"] for kind, got in zip(SYSV_KINDS, first)}
    residue = launched[1].ipc_residue
    assert sorted((e["kind"], e["id"], int(e["key"], 0), e["cleared"], e["note"]) for e in residue) == sorted(
        (kind, ids[kind], made[kind], True, "removed") for kind in SYSV_KINDS)
    assert left_after == [[(SYSV_LETTER[kind], got["id"])] for kind, got in zip(SYSV_KINDS, planted)]   # kept
    assert launched[0].ipc_residue is None and launched[2].ipc_residue == []


@needs_sandbox
def test_an_interrupted_sandboxed_launch_still_removes_its_ipc_objects(lab):
    """A coordinator failure while the subject runs (here on_start raises once the subject has made its objects)
    kills the subject; its System V objects are removed as well, best effort, before the exception propagates."""
    keys, ready = sysv_keys(3), lab.ws / "tmp" / "sysv.ids"

    def fail_once_made(record):
        assert wait_for(ready.exists, 20), "the subject never made its objects"
        raise RuntimeError("SYNTHETIC coordinator failure")
    try:
        with pytest.raises(RuntimeError, match="SYNTHETIC coordinator failure"):
            isolation.launch([PYTHON, "-I", "-S", "-B", "-c", SYSV_SUBJECT, str(ready), *map(str, keys)], cwd=lab.ws,
                             env=lab.env, profile=profile_for(lab), timeout_s=60, stdout_path=lab.coord / "i.out",
                             stderr_path=lab.coord / "i.err", on_start=fail_once_made)
        made = [int(i) for i in ready.read_text().split()]
        listed = [sysv_with_key(key) for key in keys]
    finally:
        remove_sysv_keys(keys)
    assert len(made) == 3 and all(i >= 0 for i in made), made
    assert listed == [[], [], []]


def test_an_unsandboxed_launch_neither_lists_nor_reports_ipc_objects(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "_sysv_objects", no_ipc_listing)
    result = isolation.launch([PYTHON, "-I", "-S", "-c", "pass"], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                              stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    assert result.exit_code == 0 and result.ipc_residue is None


@needs_sandbox
def test_a_sandboxed_launch_refuses_to_start_without_an_ipc_listing(lab, monkeypatch):
    """Without the listing before the start, the launch's leftovers could not be told from older objects: the
    launch is refused (IpcUnavailable, a ContractError: adapters report launch_error) and nothing starts."""
    monkeypatch.setattr(isolation, "_sysv_objects", no_ipc_listing)
    with pytest.raises(isolation.IpcUnavailable, match="SYNTHETIC"):
        isolation.launch([PYTHON, "-I", "-S", "-c", "pass"], cwd=lab.ws, env=lab.env, profile=profile_for(lab),
                         timeout_s=30, stdout_path=lab.coord / "r.out", stderr_path=lab.coord / "r.err")
    assert not (lab.coord / "r.out").exists() and not (lab.coord / "r.err").exists()


def ipc_row(kind, ident, *, owner="subject", creator="subject", pids=(0, 0), nattch=0):
    """One SYNTHETIC ipcs row: the columns _ipc_residue reads."""
    row = {"T": kind, "ID": str(ident), "KEY": f"0x{0x5e000000 + ident:08x}", "OWNER": owner, "CREATOR": creator}
    row.update(zip(isolation.IPC_PIDS[kind], map(str, pids)))
    if kind == "m":
        row["NATTCH"] = str(nattch)
    return row


def test_ipc_residue_removes_only_what_the_launch_left_and_nothing_in_use(monkeypatch):
    """What the launcher removes after a sandboxed launch, from SYNTHETIC listings (no real object): only objects
    new since the launch began, created and owned by this user, not attached and naming no live process. The
    census has ended every subject process, so a live creator or last user is another program's (or a survivor):
    such an object is reported, never removed. Another user's object is never the launch's: ignored."""
    live = {FAKE_PID + 1}
    before = {("m", 10): ipc_row("m", 10)}
    after = {**before,
             ("m", 11): ipc_row("m", 11, pids=(FAKE_PID, 0)),              # the launch's: its creator is gone
             ("q", 12): ipc_row("q", 12),                                   # a queue nobody used
             ("s", 13): ipc_row("s", 13),                                   # a semaphore set
             ("m", 14): ipc_row("m", 14, pids=(FAKE_PID + 1, 0)),          # its creator is alive: kept
             ("m", 15): ipc_row("m", 15, pids=(FAKE_PID, 0), nattch=1),    # attached: kept
             ("q", 16): ipc_row("q", 16, pids=(FAKE_PID + 1, 0)),          # its last sender is alive: kept
             ("m", 17): ipc_row("m", 17, owner="other", creator="other"),  # another user's: ignored
             ("s", 18): ipc_row("s", 18, owner="other"),                   # given to another user: kept
             ("s", 19): ipc_row("s", 19)}                                   # its removal fails
    listings, removed = [after], []

    def remove(objects):
        objects = list(objects)
        removed.extend(objects)
        listings.append({k: v for k, v in after.items() if k not in objects or k == ("s", 19)})
    monkeypatch.setattr(isolation, "_user_names", lambda: {"subject"})
    monkeypatch.setattr(isolation, "_process_exists", lambda pid: pid in live)
    monkeypatch.setattr(isolation, "_sysv_objects", lambda: listings.pop(0))
    monkeypatch.setattr(isolation, "_ipc_remove", remove)
    residue = isolation._ipc_residue(before)
    assert removed == [("m", 11), ("q", 12), ("s", 13), ("s", 19)]
    outcome = {(e["kind"], e["id"]): (e["cleared"], e["note"].split(" ")[0]) for e in residue}
    assert outcome == {("shm", 11): (True, "removed"), ("msg", 12): (True, "removed"), ("sem", 13): (True, "removed"),
                       ("shm", 14): (False, "in"), ("shm", 15): (False, "in"), ("msg", 16): (False, "in"),
                       ("sem", 18): (False, "owned"), ("sem", 19): (False, "removal")}
    assert all(e["key"] == f"0x{0x5e000000 + e['id']:08x}" for e in residue)

    listings[:] = [after]                        # the listing after the removal fails: nothing is vouched for
    monkeypatch.setattr(isolation, "_ipc_remove", lambda objects: listings.append(None) or list(objects))
    monkeypatch.setattr(isolation, "_sysv_objects", lambda: listings.pop(0) or no_ipc_listing())
    unverified = isolation._ipc_residue(before)
    assert [e["cleared"] for e in unverified] == [False] * 8
    assert {e["note"].split(":")[0] for e in unverified if e["id"] in (11, 12, 13, 19)} == {"removal unverified"}
    monkeypatch.setattr(isolation, "_sysv_objects", no_ipc_listing)   # no listing after the launch: unknown
    assert isolation._ipc_residue(before) is None


def test_the_ipcs_listing_is_parsed_strictly():
    """Every line of `ipcs -a` must be understood; anything else makes the listing unavailable (a sandboxed launch
    is then refused, and a residue after one unknown), never an empty or partial listing."""
    objects = isolation._parse_ipcs(IPCS_SAMPLE)
    assert sorted(objects) == [("m", 196611), ("q", 131072), ("s", 131072)]
    assert (objects[("m", 196611)]["CPID"], objects[("m", 196611)]["NATTCH"]) == ("37378", "0")
    assert objects[("q", 131072)]["KEY"] == "0x0d868121" and objects[("s", 131072)]["CREATOR"] == "subject"
    rows = [line for line in IPCS_SAMPLE.splitlines() if line[:2] in ("q ", "m ", "s ")]
    empty = "\n".join(line for line in IPCS_SAMPLE.splitlines() if line not in rows)
    assert isolation._parse_ipcs(empty) == {}
    queue_header = IPCS_SAMPLE.splitlines()[1]
    for bad in (IPCS_SAMPLE + "Message Queues facility not in system.\n",           # an unknown line
                IPCS_SAMPLE.replace(" 37378 ", " 3737x "),                          # a process id that is no number
                IPCS_SAMPLE.replace(" 20:58:12\n\nT", "\n\nT", 1),                  # a row missing a column
                IPCS_SAMPLE.replace(" 0x0d868120 ", " key "),                       # a key that is no key
                IPCS_SAMPLE.split("\nT", 1)[1],                                     # a row before its header
                "\n".join(IPCS_SAMPLE.splitlines()[:8]),                           # the semaphore section missing
                IPCS_SAMPLE + queue_header + "\nMessage Queues:\n",                 # a section twice
                IPCS_SAMPLE.replace(" CPID ", " XPID ")):                           # a header without its columns
        with pytest.raises(isolation.IpcUnavailable):
            isolation._parse_ipcs(bad)


# --------------------------------------------------------------------------- Linux samples (any host, no signal)
# The public CI runs on Linux: no sandbox-exec, and the launcher reads processes from /proc instead of
# proc_pidinfo and `ps`. These tests read RECORDED Linux-format samples (the kernel's layout, SYNTHETIC pids and
# values) through the very functions the Linux branch calls, so that parsing is exercised on every host. Nothing
# here signals, or even probes, a process.

LINUX_BOOT_ID = "3f1c8f7e-0f4b-4a53-9a5e-2b8d1f0c9a11"
LINUX_PROC_STAT = """cpu  123456 789 45678 9876543 2345 0 1234 0 0 0
cpu0 61728 394 22839 4938271 1172 0 617 0 0 0
intr 98765432 0 9 0 0 0 0 0 0 0 0
ctxt 234567890
btime 1758873600
processes 345678
procs_running 2
procs_blocked 0
softirq 8765432 0 123456 6 789012 0 0 34567 234567 0 890123
"""
# /proc/<pid>/stat of Linux 6.8 (52 fields; starttime, field 22, is 1234567 clock ticks after boot)
LINUX_STAT_SAMPLE = ("4242 (python3) S 4200 4242 4200 0 -1 4194560 1203 0 0 0 5 2 0 0 20 0 1 0 1234567 25165824 "
                     "2345 18446744073709551615 94371826393088 94371829012345 140724423116288 0 0 0 0 16781312 "
                     "134234626 1 0 0 17 3 0 0 0 0 0 94371831111888 94371831234567 94371846012928 140724423122512 "
                     "140724423122564 140724423122564 140724423127017 0\n")
# util-linux 2.39 `ipcs -a` (Ubuntu 24.04), with one shared-memory segment
UTIL_LINUX_IPCS_SAMPLE = """
------ Message Queues --------
key        msqid      owner      perms      used-bytes   messages

------ Shared Memory Segments --------
key        shmid      owner      perms      bytes      nattch     status
0x00000000 3          runner     600        524288     2          dest

------ Semaphore Arrays --------
key        semid      owner      perms      nsems

"""   # trailing padding of each line dropped


def linux_stat(pid, comm, state, ppid, pgrp, starttime, session=None):
    """LINUX_STAT_SAMPLE's layout with this process's pid, command name, state, ppid, pgrp, session (default:
    pgrp) and starttime."""
    fields = LINUX_STAT_SAMPLE.split(") ", 1)[1].split()
    fields[0:4] = [state, str(ppid), str(pgrp), str(pgrp if session is None else session)]
    fields[19] = str(starttime)
    return f"{pid} ({comm}) " + " ".join(fields) + "\n"


def linux_proc(tmp_path, stats):
    """A SYNTHETIC /proc tree: /proc/stat, the boot id, a non-pid entry and {pid: stat text, or None for a
    process whose stat vanished between the listing and the read}."""
    proc = tmp_path / "proc"
    (proc / "sys" / "kernel" / "random").mkdir(parents=True)
    (proc / "sys" / "kernel" / "random" / "boot_id").write_text(LINUX_BOOT_ID + "\n")
    (proc / "stat").write_text(LINUX_PROC_STAT)
    (proc / "self").mkdir()
    (proc / "self" / "stat").write_text(LINUX_STAT_SAMPLE)
    for pid, text in stats.items():
        (proc / str(pid)).mkdir()
        if text is not None:
            (proc / str(pid) / "stat").write_text(text)
    return str(proc)


def test_linux_stat_sample_has_the_kernel_layout():
    assert len(LINUX_STAT_SAMPLE.split()) == 52 and LINUX_STAT_SAMPLE.split()[21] == "1234567"
    assert linux_stat(4242, "python3", "S", 4200, 4242, 1234567, session=4200) == LINUX_STAT_SAMPLE
    assert isolation._linux_stat_fields(LINUX_STAT_SAMPLE)[:3] == ["S", "4200", "4242"]


def test_linux_proc_reads_start_times_identities_and_skips_zombies(tmp_path):
    """A start time is btime plus starttime ticks over CLK_TCK and the identity is (boot id, ticks); a zombie or
    dead task, a vanished or malformed stat line and a missing pid read as no live process. A command name holding
    ") Z 1 1 1 (" (any process may name itself so) cannot pose as a zombie or as a child of pid 1: the name ends
    at the LAST ")"."""
    hz = os.sysconf("SC_CLK_TCK")
    hostile = "a) Z 1 1 1 (b"                                          # 13 bytes: within the 15-byte comm limit
    proc = linux_proc(tmp_path, {4242: LINUX_STAT_SAMPLE, 4243: linux_stat(4243, hostile, "S", 4242, 4242, 1234600),
                                 4244: linux_stat(4244, "sh", "Z", 4242, 4242, 1234650),
                                 4245: linux_stat(4245, "sh", "X", 4242, 4242, 1234660),
                                 4246: linux_stat(4246, "sleep", "S", 1, 5000, 99), 4247: None,
                                 4248: "4248 (truncated) S 1 4248 4248 0\n", 4249: "4249 no-name S 1 4249\n"})
    assert isolation._linux_proc_read(4242, proc) == (4200, 1758873600 + 1234567 / hz,
                                                      ("linux", LINUX_BOOT_ID, 1234567))
    assert isolation._linux_proc_read(4243, proc) == (4242, 1758873600 + 1234600 / hz,
                                                      ("linux", LINUX_BOOT_ID, 1234600))
    assert isolation._linux_proc_read(4246, proc)[:2] == (1, 1758873600 + 99 / hz)
    for gone in (4244, 4245, 4247, 4248, 4249, 4250):   # zombie, dead, vanished, truncated, no name, no such pid
        assert isolation._linux_proc_read(gone, proc) is None
    (Path(proc) / "stat").write_text(LINUX_PROC_STAT.replace("btime ", "boottime "))
    assert isolation._linux_proc_read(4242, proc) is None                     # no btime line: unknown, not zero


def test_linux_group_members_come_from_each_stat_lines_pgrp(tmp_path):
    """Members are read from field 5 (pgrp) after the command name, zombies included as `ps -A` lists them on
    macOS; non-pid entries, vanished and malformed stat lines are skipped. The hostile name's "1 1 1" is never
    read as a process group."""
    proc = linux_proc(tmp_path, {4242: LINUX_STAT_SAMPLE, 4243: linux_stat(4243, "a) Z 1 1 1 (b", "S", 4242, 4242, 5),
                                 4244: linux_stat(4244, "sh", "Z", 4242, 4242, 6),
                                 4246: linux_stat(4246, "sleep", "S", 1, 5000, 7), 4247: None,
                                 4248: "4248 (truncated) S 1\n"})
    assert isolation._linux_group_members(4242, proc) == [4242, 4243, 4244]
    assert isolation._linux_group_members(5000, proc) == [4246]
    assert isolation._linux_group_members(1, proc) == []


def test_util_linux_ipcs_output_is_refused_never_misread():
    """util-linux `ipcs -a` (Linux) has another layout than the BSD listing _parse_ipcs reads. Only a sandboxed
    launch lists System V objects and Linux has no sandbox-exec, so the Linux listing is never needed; if it were
    ever reached, it must make the listing unavailable (the launch refused), never an empty or partial one."""
    with pytest.raises(isolation.IpcUnavailable, match="unexpected line"):
        isolation._parse_ipcs(UTIL_LINUX_IPCS_SAMPLE)


@needs_sandbox
def test_sandboxed_timeout_kills_a_double_forked_grandchild(lab, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.5)
    pidfile = lab.ws / "tmp" / "grandchild.pid"
    result = isolation.launch([PYTHON, "-I", "-S", "-B", "-c", DOUBLE_FORK, str(pidfile)], cwd=lab.ws, env=lab.env,
                              profile=profile_for(lab), timeout_s=1.5, stdout_path=lab.coord / "t.out",
                              stderr_path=lab.coord / "t.err")
    assert result.timed_out and result.killed and result.survivors == [], (lab.coord / "t.err").read_text()
    assert gone(int(pidfile.read_text()))


@needs_sandbox
def test_sandboxed_launch_kills_a_setsid_escapee(lab):
    pidfile = lab.ws / "tmp" / "escapee.pid"
    try:
        result = isolation.launch([PYTHON, "-I", "-S", "-B", "-c", SETSID_CHILD, str(pidfile)], cwd=lab.ws,
                                  env=lab.env, profile=profile_for(lab), timeout_s=30,
                                  stdout_path=lab.coord / "s.out", stderr_path=lab.coord / "s.err")
        assert (result.exit_code, result.timed_out, result.killed, result.survivors) == (0, False, True, []), \
            (lab.coord / "s.err").read_text()
        assert gone(int(pidfile.read_text()))       # unsandboxed, the same child survives (test above)
    finally:
        if pidfile.exists():
            kill_quietly(int(pidfile.read_text()))


MANY = 160   # subject processes: more than the former 128-match census limit, far below the per-user limit

MANY_AND_AN_ESCAPEE = r'''
import os, signal, sys, time
count, base = int(sys.argv[1]), sys.argv[2]
deadline = time.time() + 25                  # self-limiting if a test fails
def linger():
    while time.time() < deadline:
        time.sleep(0.05)
    os._exit(0)
if os.fork() == 0:                           # the escapee: leaves the session, ignores SIGTERM
    os.setsid()
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    with open(base + ".escapee.tmp", "w") as handle:
        handle.write(str(os.getpid()))
    os.rename(base + ".escapee.tmp", base + ".escapee")
    linger()
children = []
for _ in range(count):                       # many processes in the launch's group and sandbox
    pid = os.fork()
    if pid == 0:
        linger()
    children.append(pid)
while not os.path.exists(base + ".escapee"):
    time.sleep(0.01)
with open(base + ".children.tmp", "w") as handle:
    handle.write(" ".join(map(str, children)))
os.rename(base + ".children.tmp", base + ".children")
with open(base + ".leader.tmp", "w") as handle:
    handle.write(str(os.getpid()))
os.rename(base + ".leader.tmp", base + ".leader")
if "stay" in sys.argv[3:]:                   # a lost launch: the leader keeps running
    linger()
'''


def many_pids(base):
    return [int(p) for p in Path(f"{base}.children").read_text().split()]


@needs_sandbox
def test_sandboxed_launch_kills_a_setsid_escapee_among_many_subject_processes(lab, monkeypatch):
    """R4.1: a subject that runs more processes than the former census limit (128) switched the sandbox
    census off for the rest of its launch, and its setsid escapee then outlived the launch (census_complete
    False). No count turns the census off now: the escapee and every process are killed."""
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.3)
    base = lab.ws / "tmp" / "many"
    try:
        result = isolation.launch([PYTHON, "-I", "-S", "-B", "-c", MANY_AND_AN_ESCAPEE, str(MANY), str(base)],
                                  cwd=lab.ws, env=lab.env, profile=profile_for(lab), timeout_s=30,
                                  stdout_path=lab.coord / "m.out", stderr_path=lab.coord / "m.err")
        assert (result.exit_code, result.killed, result.survivors) == (0, True, []), (lab.coord / "m.err").read_text()
        assert result.census_complete is True
        assert len(many_pids(base)) == MANY
        assert gone(int(Path(f"{base}.escapee").read_text()))   # found by its sandbox, outside the group
        assert all(gone(pid) for pid in many_pids(base))
    finally:   # cleanup, effective only if an assertion failed (the children end by themselves)
        if Path(f"{base}.escapee").exists():
            kill_quietly(int(Path(f"{base}.escapee").read_text()))


@needs_sandbox
def test_sandboxed_timeout_stops_a_setsid_forking_chain(lab, monkeypatch):
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.2)
    log = lab.ws / "tmp" / "chain.log"
    result = isolation.launch([PYTHON, "-I", "-S", "-B", "-c", FORK_CHAIN, "setsid", str(log), "3"], cwd=lab.ws,
                              env=lab.env, profile=profile_for(lab), timeout_s=1.2,
                              stdout_path=lab.coord / "c.out", stderr_path=lab.coord / "c.err")
    records = chain_records(log)                    # independent of the launcher's own census
    leader = records[0][0]
    assert len(records) > 2 and any(pgid != leader for _, pgid in records[1:]), records   # it left the group
    assert result.timed_out and result.killed and result.survivors == [], (lab.coord / "c.err").read_text()


@needs_sandbox
def test_census_reports_a_live_process_in_the_launch_sandbox(tmp_path):
    marker = isolation._make_marker(tmp_path)
    empty_group = subprocess.Popen(["/usr/bin/true"], start_new_session=True)   # its group is gone
    empty_group.wait()
    marked = subprocess.Popen([isolation.SANDBOX_EXEC, "-p", "(version 1)(allow default)\n" +
                               isolation._marker_rules(marker), "/bin/sleep", "30"], start_new_session=True)
    try:
        assert wait_for(lambda: isolation._scan(marker, not_before=0.0) == [marked.pid])
        watch = isolation._Watch(empty_group.pid, marker, 0.0, None)
        assert isolation._census(watch, 0.2) == [marked.pid]                    # found by sandbox, not group
    finally:
        marked.kill()
        marked.wait()
    assert isolation._census(isolation._Watch(empty_group.pid, marker, 0.0, None), 2.0) == []


@needs_sandbox
def test_launch_refuses_a_profile_that_does_not_deny(lab):
    permissive = ("(version 1)(deny default)\n(allow file-read*)\n(allow process-exec)\n(allow process-fork)\n"
                  "(allow sysctl-read)\n(allow mach-lookup)\n")
    with pytest.raises(ContractError, match="does not deny"):
        isolation.launch(["/bin/cat", str(lab.oracle)], cwd=lab.ws, env=lab.env, profile=permissive, timeout_s=5,
                         stdout_path=lab.coord / "p.out", stderr_path=lab.coord / "p.err")
    assert not (lab.coord / "p.out").exists()
    control = subprocess.run([isolation.SANDBOX_EXEC, "-p", permissive, "/bin/cat", str(lab.oracle)],
                             capture_output=True, text=True, timeout=30)
    assert CANARY in control.stdout                 # positive control: this profile really leaks


@needs_sandbox
def test_malformed_profile_is_a_launch_error_not_a_subject_crash(lab):
    with pytest.raises(ContractError, match="rejected"):
        isolation.launch(["/usr/bin/true"], cwd=lab.ws, env=lab.env, profile="(version 1)(deny default)(allow bogus)",
                         timeout_s=5, stdout_path=lab.coord / "m.out", stderr_path=lab.coord / "m.err")


# --------------------------------------------------------------------------- on_start and the lost-launch census

LOST_SUBJECT = r'''
import os, sys, time
if os.fork() == 0:                           # an escapee: leaves the launch's session and group
    os.setsid()
    with open(sys.argv[1] + ".escapee.tmp", "w") as handle:
        handle.write(str(os.getpid()))
    os.rename(sys.argv[1] + ".escapee.tmp", sys.argv[1] + ".escapee")
    time.sleep(30)
    os._exit(0)
with open(sys.argv[1] + ".leader.tmp", "w") as handle:
    handle.write(str(os.getpid()))
os.rename(sys.argv[1] + ".leader.tmp", sys.argv[1] + ".leader")
time.sleep(30)
'''

COORDINATOR = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from governance import isolation
spec = json.loads(sys.argv[2])

def started(record):                         # the runner journals exactly this record
    with open(spec["record"] + ".tmp", "w") as handle:
        json.dump(record, handle)
    os.rename(spec["record"] + ".tmp", spec["record"])

isolation.launch(spec["argv"], cwd=spec["cwd"], env=spec["env"], profile=spec["profile"], timeout_s=60,
                 stdout_path=spec["out"], stderr_path=spec["err"], on_start=started)
'''


def lose_a_launch(tmp, *, argv, cwd, env, profile):
    """SYNTHETIC coordinator death: a helper coordinator launches the subject with on_start, is SIGKILLed once
    the subject runs, and leaves its record and a live subject behind. Returns (record, leader, escapee)."""
    spec = {"argv": argv, "cwd": str(cwd), "env": env, "profile": profile, "record": str(tmp / "record.json"),
            "out": str(tmp / "lost.out"), "err": str(tmp / "lost.err")}
    helper = subprocess.Popen([sys.executable, "-I", "-c", COORDINATOR, str(REPO_ROOT / "benchmarks"),
                               json.dumps(spec)], start_new_session=True, stdin=subprocess.DEVNULL)
    pids = Path(argv[-1])
    try:
        assert wait_for(lambda: all(Path(f"{pids}.{n}").exists() for n in ("leader", "escapee"))
                        and (tmp / "record.json").exists(), 20), (tmp / "lost.err").read_text()
    finally:
        os.kill(helper.pid, signal.SIGKILL)
        helper.wait()
    leader, escapee = (int(Path(f"{pids}.{n}").read_text()) for n in ("leader", "escapee"))
    record = json.loads((tmp / "record.json").read_text())
    os.kill(leader, 0)                              # the subject outlived its coordinator
    os.kill(escapee, 0)
    return record, leader, escapee


def test_a_start_time_reads_back_within_the_read_error_and_identically():
    """_proc_info's start time is at most START_READ_ERROR_S earlier than the wall clock just before the
    spawn (Linux /proc: whole-second boot time plus clock ticks; macOS: microseconds), never later than
    just after it, and reads of one process agree while the wall clock does not step (on Linux a step moves
    them by whole seconds: START_STEPS_WHOLE_SECONDS). Its _identity agrees on every read, step or not: the
    launcher compares that before every killpg."""
    before = time.time()
    child = subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)"], stdin=subprocess.DEVNULL)
    try:
        after = time.time()
        start, identity = isolation._start_time(child.pid), isolation._identity(child.pid)
        assert start is not None and before - isolation.START_READ_ERROR_S - 0.001 <= start <= after + 0.001
        assert isolation.START_SLACK_S >= isolation.START_READ_ERROR_S + 0.05
        assert {isolation._start_time(child.pid) for _ in range(20)} == {start}
        assert identity is not None and {isolation._identity(child.pid) for _ in range(20)} == {identity}
        assert identity != isolation._identity(os.getpid())
    finally:
        child.kill()
        child.wait()
    assert isolation._identity(child.pid) is None                  # reaped: no process, no identity


def step_the_wall_clock(monkeypatch, shift, pids, when=None):
    """SYNTHETIC wall-clock step as Linux's /proc shows it: every later start-time read of `pids` (a set, which
    the caller may still fill) comes back `shift` seconds off, once `when` (an Event, default already set) is set;
    a process's _identity (boot id and start ticks) does not move. macOS start times never move; this is Linux's
    case. Never every process: the session signal guard (conftest.py) reads start times through the same
    isolation._proc_read, so shifting a process it did not start would widen or narrow what it refuses."""
    real = isolation._proc_read

    def read(pid):
        info = real(pid)
        if info is None or pid not in pids or (when is not None and not when.is_set()):
            return info
        return info[0], info[1] + shift, info[2]
    monkeypatch.setattr(isolation, "_proc_read", read)


def test_whole_seconds_apart_is_the_shape_of_a_linux_clock_step(monkeypatch):
    monkeypatch.setattr(isolation, "START_STEPS_WHOLE_SECONDS", True)
    hz = 100
    before, after = 1758800000.0 + 123457 / hz, 1758800003.0 + 123457 / hz   # btime + ticks/CLK_TCK, a 3 s step
    assert isolation._whole_seconds_apart(after, before) and isolation._whole_seconds_apart(before, after)
    assert not isolation._whole_seconds_apart(before, before)                # the same read: the same process
    assert not isolation._whole_seconds_apart(before + 1 / hz, before)       # a tick apart: another process
    assert not isolation._whole_seconds_apart(None, before) and not isolation._whole_seconds_apart(before, None)
    monkeypatch.setattr(isolation, "START_STEPS_WHOLE_SECONDS", False)
    assert not isolation._whole_seconds_apart(after, before)                 # macOS: a start never moves
    for steps in (True, False):   # zero whole seconds: a nonzero difference under 1e-4 s is noise in one start,
        monkeypatch.setattr(isolation, "START_STEPS_WHOLE_SECONDS", steps)   # finer than any resolution, never a
        assert isolation._whole_seconds_apart(before + 5e-5, before)         # second process: unprovable
        assert isolation._whole_seconds_apart(before, before + 5e-5)


def test_launch_signals_its_own_group_across_a_wall_clock_step(tmp_path, monkeypatch):
    """R4.3: the launcher compared its leader's start time before every killpg. On Linux a wall-clock step
    moves every start-time read by whole seconds, so after a step it took its own leader for a different
    process and never signalled its group: the subject outlived its wall limit (here it would have slept
    its 20 s). It compares _identity now, which no step moves. Only the leader's reads move (see
    step_the_wall_clock), which is all the former comparison read."""
    monkeypatch.setattr(isolation, "TERM_GRACE_S", 0.3)
    stepped, leader, own = threading.Event(), set(), isolation._start_time(os.getpid())
    step_the_wall_clock(monkeypatch, 1.0, pids=leader, when=stepped)

    def step(record):                               # the step: after the launcher read its leader
        leader.add(record["pid"])
        stepped.set()
    code = "import time; time.sleep(20)"
    result = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=0.5,
                              stdout_path=tmp_path / "o", stderr_path=tmp_path / "e", on_start=step)
    assert stepped.is_set() and result.timed_out and result.killed and result.survivors == []
    assert result.exit_code == -signal.SIGTERM and result.wall_seconds < 10
    assert isolation._start_time(os.getpid()) == own   # no other process's start moved (the signal guard's view)


def test_signal_group_never_signals_a_group_held_by_another_identity():
    other = bystander()                             # SYNTHETIC: leads its own group
    try:
        isolation._signal_group(other.pid, signal.SIGKILL, leader_id=("synthetic", 0, 0))
        time.sleep(0.2)
        assert other.poll() is None                 # a different leader holds the id: never signalled
        isolation._signal_group(other.pid, signal.SIGKILL, leader_id=isolation._identity(other.pid))
        assert other.wait(timeout=10) == -signal.SIGKILL
    finally:
        other.kill()
        other.wait()


@pytest.mark.parametrize("whole_seconds, shift, complete", [
    (True, 1.0, False),      # Linux, a 1 s step forward: the leader, or not; unprovable
    (True, -2.0, False),     # Linux, a 2 s step back: likewise
    (True, 0.37, True),      # Linux, not a whole second: another process holds the id (foreign)
    (False, 1.0, True),      # macOS: a start time never moves, so a larger difference is another process
    (False, 5e-5, False),    # any platform: under 1e-4 s is noise in the leader's own start; unprovable
])
def test_census_treats_a_leader_read_across_a_clock_step_as_unprovable(monkeypatch, whole_seconds, shift, complete):
    """R4.3: census_launch has only the recorded wall-clock leader_start. On Linux a step between the record
    and the census moved the leader's start by whole seconds; the census took the live leader for a later
    process, listed its group foreign, signalled nothing and reported itself complete, so a live subject was
    sealed as a clean lost launch. Such a difference now proves nothing: nothing signalled, incomplete."""
    started_at = time.time()
    leader = bystander()                            # SYNTHETIC unsandboxed lost launch: its leader, still running
    try:
        record = {"pid": leader.pid, "pgid": leader.pid, "marker": None, "started_at": started_at,
                  "leader_start": isolation._start_time(leader.pid)}   # as the launcher records it
        with monkeypatch.context() as patch:        # undone before the cleanup below: a step back makes the
            patch.setattr(isolation, "START_STEPS_WHOLE_SECONDS", whole_seconds)   # leader look older than
            step_the_wall_clock(patch, shift, pids={leader.pid})                   # this session, and the
            found = isolation.census_launch(record, wait_s=0.5)                    # signal guard refuses it
        time.sleep(0.2)
        assert leader.poll() is None                # never signalled
        assert (found["found"], found["killed"], found["survivors"], found["foreign"]) == ([], [], [], [leader.pid])
        assert found["complete"] is complete
        assert found["note"].startswith("the recorded group id" if complete else "group identity unprovable")
    finally:
        leader.kill()
        leader.wait()


def test_on_start_reports_the_running_launch_once_before_the_wait(tmp_path):
    seen = []

    def started(record):
        os.kill(record["pid"], 0)                   # still running: called before the launcher waits
        assert record["leader_start"] == isolation._start_time(record["pid"])   # the leader's identity
        seen.append(record)
    code = "import time; time.sleep(0.3)"
    result = isolation.launch([PYTHON, "-I", "-S", "-c", code], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                              stdout_path=tmp_path / "o", stderr_path=tmp_path / "e", on_start=started)
    assert result.exit_code == 0 and len(seen) == 1
    assert seen[0] == isolation.check_launch_record(seen[0]) and seen[0]["marker"] is None
    assert seen[0]["pid"] == seen[0]["pgid"] != os.getpgrp()


def test_a_failing_on_start_kills_the_subject(tmp_path):
    pidfile = tmp_path / "subject.pid"
    code = "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)"

    def started(record):
        assert wait_for(pidfile.exists)
        raise OSError("SYNTHETIC journal failure")
    with pytest.raises(OSError, match="SYNTHETIC journal failure"):
        isolation.launch([PYTHON, "-I", "-S", "-c", code, str(pidfile)], cwd=tmp_path, env={}, profile=None,
                         timeout_s=30, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e", on_start=started)
    assert gone(int(pidfile.read_text()))
    with pytest.raises(ContractError, match="on_start"):
        isolation.launch([PYTHON, "-I", "-S", "-c", "pass"], cwd=tmp_path, env={}, profile=None, timeout_s=30,
                         stdout_path=tmp_path / "o2", stderr_path=tmp_path / "e2", on_start="not callable")


def test_census_of_an_unsandboxed_lost_launch_kills_its_group_only(tmp_path):
    pids = tmp_path / "subject"
    record, leader, escapee = lose_a_launch(tmp_path, argv=[PYTHON, "-I", "-S", "-c", LOST_SUBJECT, str(pids)],
                                            cwd=tmp_path, env={}, profile=None)
    try:
        assert record["marker"] is None and record["pid"] == record["pgid"] == leader
        found = isolation.census_launch(record)
        assert found["killed"] == [leader] and found["survivors"] == [] and found["complete"] is True
        assert gone(leader)
        os.kill(escapee, 0)                         # documented limit: outside the group, unseen unsandboxed
        assert isolation.census_launch(record, wait_s=0.5)["found"] == []   # the group is gone now
    finally:
        kill_quietly(escapee)


def test_census_never_lists_a_member_it_killed_as_foreign(tmp_path):
    """A killed member stays a zombie until its parent reaps it (here the test process, as for a
    coordinator whose adapter raised after starting the launch itself): it was ours and is killed, not
    foreign and not a survivor, and the census ends without waiting out its deadline."""
    started_at = time.time()
    child = subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)"], start_new_session=True,
                             stdin=subprocess.DEVNULL)
    try:
        begun = time.monotonic()
        found = isolation.census_launch({"pid": child.pid, "pgid": child.pid, "marker": None,
                                         "started_at": started_at, "leader_start": isolation._start_time(child.pid)})
        assert time.monotonic() - begun < isolation.CENSUS_WAIT_S
        assert (found["found"], found["killed"], found["survivors"], found["foreign"]) == (
            [child.pid], [child.pid], [], [])
        assert isolation._proc_info(child.pid) is None          # the unreaped zombie has no start time
        assert child.wait(timeout=10) == -signal.SIGKILL
    finally:
        child.kill()                                    # Popen.kill: a no-op once the child was reaped
        child.wait()


@needs_sandbox
@pytest.mark.parametrize("marker_removed", [False, True])
def test_census_of_a_sandboxed_lost_launch_kills_every_process_in_its_sandbox(lab, marker_removed):
    pids = lab.ws / "tmp" / "subject"
    record, leader, escapee = lose_a_launch(lab.coord, argv=[PYTHON, "-I", "-S", "-B", "-c", LOST_SUBJECT, str(pids)],
                                            cwd=lab.ws, env=lab.env, profile=profile_for(lab))
    marker_dir = Path(record["marker"][0]).parent
    older = bystander()                             # predates the census; must never be signalled
    younger = []
    try:
        assert record["pid"] == record["pgid"] == leader and marker_dir.is_dir()
        if marker_removed:                          # e.g. a temporary-directory cleanup after the crash
            shutil.rmtree(marker_dir)               # (the 2026-09-25 incident: only census-allow came back)
        younger.append(bystander())                 # started after the launch: eligible by age, not a member
        found = isolation.census_launch(record)
        assert older.poll() is None and younger[0].poll() is None
        assert found["killed"] == sorted([leader, escapee]) and found["survivors"] == []
        assert found["foreign"] == [] and found["complete"] is True
        assert gone(leader) and gone(escapee)       # the setsid escapee too: found by its sandbox
        assert marker_dir.exists() is not marker_removed     # a restored marker is removed again
    finally:
        kill_quietly(leader)
        kill_quietly(escapee)
        for proc in [older, *younger]:
            proc.kill()
            proc.wait()
        shutil.rmtree(marker_dir, ignore_errors=True)


@needs_sandbox
def test_census_of_a_sandboxed_lost_launch_kills_many_processes_and_its_escapee(lab):
    """R4.1 for a lost launch: with more than 128 processes in its sandbox the former census signalled
    nothing at all (not even the group) and reported itself incomplete. Every process is killed now."""
    base = lab.ws / "tmp" / "lost-many"
    argv = [PYTHON, "-I", "-S", "-B", "-c", MANY_AND_AN_ESCAPEE, str(MANY), str(base), "stay", str(base)]
    record, leader, escapee = lose_a_launch(lab.coord, argv=argv, cwd=lab.ws, env=lab.env, profile=profile_for(lab))
    children = many_pids(base)
    try:
        found = isolation.census_launch(record)
        assert (found["complete"], found["survivors"], found["foreign"]) == (True, [], []), found["note"]
        assert found["killed"] == sorted([leader, escapee, *children]) and len(children) == MANY
        assert gone(leader) and gone(escapee) and all(gone(pid) for pid in children)
    finally:   # cleanup, effective only if an assertion failed (the children end by themselves)
        kill_quietly(leader)
        kill_quietly(escapee)
        shutil.rmtree(Path(record["marker"][0]).parent, ignore_errors=True)


@needs_sandbox
def test_census_never_kills_by_command_line_or_a_reused_group(tmp_path):
    """A recorded group id now held by an unrelated group, and a process whose argv names the subject root:
    neither is in the launch's sandbox, so neither is signalled (the group members are reported foreign)."""
    root = tmp_path / "subjects" / "0123456789abcdef"
    root.mkdir(parents=True)
    unrelated = subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)", str(root)],
                                 start_new_session=True, stdin=subprocess.DEVNULL)
    marker_dir = tmp_path / "lost-census"
    marker_dir.mkdir()
    marker = [str(p) for p in isolation._make_marker(str(marker_dir))]
    try:
        started_at = time.time()                    # SYNTHETIC lost launch whose leader started (and ended) then
        found = isolation.census_launch({"pid": unrelated.pid, "pgid": unrelated.pid, "marker": marker,
                                         "started_at": started_at, "leader_start": started_at}, wait_s=0.5)
        assert (found["found"], found["killed"], found["survivors"]) == ([], [], [])
        assert found["foreign"] == [unrelated.pid] and found["complete"] is True
        time.sleep(0.2)
        assert unrelated.poll() is None             # alive: the census never matched its command line
    finally:
        unrelated.kill()
        unrelated.wait()


def test_census_refuses_malformed_records_and_the_coordinator_itself():
    good = {"pid": 4242, "pgid": 4242, "marker": None, "started_at": 100.0, "leader_start": 100.0}
    assert isolation.check_launch_record({**good, "leader_start": None})["leader_start"] is None
    early = good["started_at"] - isolation.START_SLACK_S          # the floor, which allows for the read error
    assert isolation.check_launch_record({**good, "leader_start": early})["leader_start"] == early
    for bad in ({**good, "pgid": 4243}, {**good, "pid": 1, "pgid": 1}, {**good, "pid": True, "pgid": True},
                {**good, "marker": ["/tmp/a/census-allow"]}, {**good, "marker": ["/tmp/a/x", "/tmp/a/y"]},
                {**good, "marker": ["/tmp/a/census-allow", "/tmp/b/census-deny"]}, {"pid": 4242, "pgid": 4242},
                {"pid": 4242, "pgid": 4242, "marker": None}, {**good, "started_at": 0},
                {**good, "started_at": float("nan")}, {**good, "started_at": "now"}, {**good, "extra": 1}, None,
                {k: v for k, v in good.items() if k != "leader_start"}, {**good, "leader_start": early - 0.01},
                {**good, "leader_start": True}, {**good, "leader_start": "then"},
                {**good, "leader_start": float("inf")}):
        with pytest.raises(ContractError, match="launch record"):
            isolation.census_launch(bad)
    own = os.getpgrp()
    with pytest.raises(ContractError, match="coordinator itself"):
        isolation.census_launch({"pid": own, "pgid": own, "marker": None, "started_at": 1.0, "leader_start": 1.0})


def test_census_never_kills_a_later_group_that_reused_the_recorded_id():
    """The unsandboxed census binds the recorded group to its leader (pid AND start time). A lost launch
    whose group ended long ago names an id now held by a newer session leader: every member of that newer
    group started after the launch, so the start-time floor alone would have SIGKILLed all of them."""
    newer = bystander()                             # started now, in a new session: holds the id today
    try:
        holder_start = isolation._start_time(newer.pid)
        assert holder_start is not None
        # SYNTHETIC lost launch about a minute ago whose group has ended. Its leader's start is 60.37 s before the
        # holder's start as read, so never a whole number of seconds from it (unprovable on Linux, E-23).
        leader_start = holder_start - 60.37
        record = {"pid": newer.pid, "pgid": newer.pid, "marker": None, "started_at": leader_start - 0.01,
                  "leader_start": leader_start}
        found = isolation.census_launch(record, wait_s=0.5)
        time.sleep(0.2)
        assert newer.poll() is None                 # alive: never signalled
        assert (found["found"], found["killed"], found["survivors"]) == ([], [], [])
        assert found["foreign"] == [newer.pid] and found["complete"] is True
        assert "held by a process other than the launch's leader" in found["note"]
    finally:
        newer.kill()
        newer.wait()


@pytest.mark.parametrize("recorded", ["exact", "none"])
def test_census_signals_nothing_when_the_recorded_group_cannot_be_proven(tmp_path, recorded):
    """A group that outlived its leader cannot be told from a reused id whose new leader also exited: the
    census signals nothing, lists the members foreign and reports itself incomplete."""
    pidfile = tmp_path / "member.pid"
    code = ("import os, sys, time\n"
            "if os.fork() == 0:\n"
            "    open(sys.argv[1] + '.tmp', 'w').write(str(os.getpid()))\n"
            "    os.rename(sys.argv[1] + '.tmp', sys.argv[1])\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "time.sleep(0.5)\n")
    started_at = time.time()
    leader = subprocess.Popen([PYTHON, "-I", "-S", "-c", code, str(pidfile)], start_new_session=True,
                              stdin=subprocess.DEVNULL)
    leader_start = isolation._start_time(leader.pid)   # as the launcher records it, right after the start
    member = []
    try:
        assert leader_start is not None and wait_for(pidfile.exists)
        member.append(int(pidfile.read_text()))
        assert leader.wait(timeout=10) == 0         # the leader exited; its group lives on in the member
        record = {"pid": leader.pid, "pgid": leader.pid, "marker": None, "started_at": started_at,
                  "leader_start": leader_start if recorded == "exact" else None}
        found = isolation.census_launch(record, wait_s=0.5)
        time.sleep(0.2)
        os.kill(member[0], 0)                       # alive: never signalled
        assert (found["found"], found["killed"], found["survivors"]) == ([], [], [])
        assert found["foreign"] == member and found["complete"] is False
        assert found["note"].startswith("group identity unprovable")
    finally:
        leader.kill()
        leader.wait()
        for pid in member:
            kill_quietly(pid)

def test_census_of_a_live_group_it_cannot_list_is_incomplete(monkeypatch):
    """Export review: _group_members skips /proc entries it cannot read or parse, and returns [] when `ps`
    fails; the unsandboxed census took an empty listing of a live group for "no members", signalled nothing
    and reported itself complete. A group that still answers killpg(0) with no member listed now leaves the
    census incomplete, nothing signalled; once the group has ended, the same empty listing is complete."""
    started_at = time.time()
    leader = bystander()                            # SYNTHETIC unsandboxed lost launch: its leader, still running
    try:
        record = {"pid": leader.pid, "pgid": leader.pid, "marker": None, "started_at": started_at,
                  "leader_start": isolation._start_time(leader.pid)}   # as the launcher records it
        with monkeypatch.context() as patch:
            patch.setattr(isolation, "_group_members", lambda pgid: [])   # SYNTHETIC: a listing that found nobody
            found = isolation.census_launch(record, wait_s=0.5)
        time.sleep(0.2)
        assert leader.poll() is None                # never signalled
        assert (found["found"], found["killed"], found["survivors"], found["foreign"]) == ([], [], [], [])
        assert found["complete"] is False
        assert found["note"].startswith(f"group {leader.pid} is alive but none of its members could be listed")
    finally:
        leader.kill()
        leader.wait()
    with monkeypatch.context() as patch:            # the group has ended (its only member was reaped above)
        patch.setattr(isolation, "_group_members", lambda pgid: [])
        ended = isolation.census_launch(record, wait_s=0.5)
    assert (ended["found"], ended["complete"], ended["note"]) == ([], True, None)


def test_census_never_signals_a_proven_group_member_the_floor_excludes(tmp_path, monkeypatch):
    """Every member of a proven group is the launch's (its session holds only the leader's descendants).
    One whose start time reads earlier than the launch (a wrong reading, as Linux's whole-second boot time
    gave before START_SLACK_S allowed for it) is never signalled, is listed as a survivor, and the census
    reports itself incomplete, so the runner flags census_incomplete instead of sealing a clean lost launch."""
    pidfile = tmp_path / "member.pid"
    code = ("import os, sys, time\n"
            "if os.fork() == 0:\n"
            "    open(sys.argv[1] + '.tmp', 'w').write(str(os.getpid()))\n"
            "    os.rename(sys.argv[1] + '.tmp', sys.argv[1])\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "time.sleep(30)\n")
    started_at = time.time()
    leader = subprocess.Popen([PYTHON, "-I", "-S", "-c", code, str(pidfile)], start_new_session=True,
                              stdin=subprocess.DEVNULL)
    member = []
    try:
        record = {"pid": leader.pid, "pgid": leader.pid, "marker": None, "started_at": started_at,
                  "leader_start": isolation._start_time(leader.pid)}   # as the launcher records it
        assert record["leader_start"] is not None and wait_for(pidfile.exists)
        member.append(int(pidfile.read_text()))
        real = isolation._start_time

        def early(pid):                             # SYNTHETIC: the member's start time reads an hour early
            start = real(pid)
            return start - 3600 if start is not None and pid == member[0] else start
        with monkeypatch.context() as patch:
            patch.setattr(isolation, "_start_time", early)
            found = isolation.census_launch(record, wait_s=0.5)
        time.sleep(0.2)
        os.kill(member[0], 0)                       # alive: never signalled
        assert leader.wait(timeout=10) == -signal.SIGKILL
        assert (found["killed"], found["survivors"], found["foreign"]) == ([leader.pid], member, [])
        assert found["found"] == sorted([leader.pid, member[0]]) and found["complete"] is False
        assert found["note"].startswith(f"the proven group {leader.pid} held live member(s) {member}")
    finally:
        leader.kill()
        leader.wait()
        for pid in member:
            kill_quietly(pid)


# --------------------------------------------------------------------------- census fails closed
# Regression for the 2026-09-25 incident (docs/development/evaluation-study/incident-2026-09-25.md):
# sandbox_check reports a path it cannot resolve as denied for EVERY process, so with census-deny
# missing and census-allow present the membership test matched every unsandboxed process on the
# host and the SIGSTOP+SIGKILL rounds killed the user's whole login session. These tests use
# harmless bystanders (sleep processes) and call _scan without signals wherever an unfixed census
# would reach beyond them.

def bystander():
    """An unsandboxed process that is not the subject of any launch (SYNTHETIC)."""
    return subprocess.Popen([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)"], start_new_session=True,
                            stdin=subprocess.DEVNULL)


@needs_sandbox
def test_scan_fails_closed_when_the_deny_marker_is_missing(tmp_path):
    marker = isolation._make_marker(tmp_path)
    other = bystander()
    try:
        assert isolation._scan(marker, not_before=0.0) == []          # intact marker: no process matches
        os.unlink(marker[1])                                           # census-deny gone, census-allow present
        with pytest.raises(isolation.CensusUnavailable, match="census marker"):
            isolation._scan(marker, not_before=0.0)
        os.unlink(marker[0])
        with pytest.raises(isolation.CensusUnavailable):
            isolation._scan(marker, not_before=0.0)
        assert other.poll() is None
    finally:
        other.kill()
        other.wait()


@needs_sandbox
def test_scan_never_signals_a_process_that_started_before_the_launch(tmp_path):
    marker = isolation._make_marker(tmp_path)
    marked = subprocess.Popen([isolation.SANDBOX_EXEC, "-p", "(version 1)(allow default)\n"
                               + isolation._marker_rules(marker), "/bin/sleep", "30"],
                              env={}, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        assert wait_for(lambda: isolation._scan(marker, not_before=0.0) == [marked.pid])
        later = time.time() + 1.0                                      # a launch that began after it started
        with pytest.raises(isolation.CensusUnavailable, match="broken census"):   # a member older than the
            isolation._scan(marker, (signal.SIGKILL,), not_before=later)       # launch: the census is broken
        time.sleep(0.2)
        assert marked.poll() is None                                   # older than the launch: never signalled
        assert isolation._scan(marker, (signal.SIGKILL,), not_before=0.0) == [marked.pid]
        assert wait_for(lambda: marked.poll() is not None)
    finally:
        marked.kill()
        marked.wait()


FAKE_PID = 2 ** 22 + 100   # above every pid_max (macOS 99999, Linux 2**22): never a real process, never protected


def fake_census(tmp_path, monkeypatch, starts):
    """SYNTHETIC census host: an intact marker, and a membership test that matches exactly the fake pids of
    `starts` ({pid: start time}, listed in that order) and never the coordinator. os.kill only records."""
    marker = (str(tmp_path / "census-allow"), str(tmp_path / "census-deny"))
    for path in marker:
        Path(path).touch()
    me, sent = os.getpid(), []

    class FakeLib:
        def sandbox_check(self, pid, operation, flags, path):
            if pid == me:
                return 0                                               # the coordinator is not in the sandbox
            return 1 if path.endswith(b"census-deny") else 0          # every listed pid "matches"
    monkeypatch.setattr(isolation, "_libsystem", lambda: FakeLib())
    monkeypatch.setattr(isolation, "_all_pids", lambda: list(starts))
    monkeypatch.setattr(isolation, "_start_time", lambda pid: starts.get(pid))
    monkeypatch.setattr(isolation.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    return marker, sent


def test_scan_refuses_a_census_that_matches_a_process_older_than_the_launch(tmp_path, monkeypatch):
    """Every member of a launch's sandbox started after the launch, so a matching process that predates it
    means the membership test is broken (on 2026-09-25 it matched every process on the host): nothing is
    signalled, not even the members that started after the launch and are listed before the old one. The
    former count limit let such a census through while it matched no more than 128 processes."""
    launch = time.time()
    starts = {FAKE_PID + i: launch + 1.0 for i in range(5)}             # younger than the launch
    starts[FAKE_PID - 1] = launch - 3600.0                              # an hour older: not the launch's
    marker, sent = fake_census(tmp_path, monkeypatch, starts)
    with pytest.raises(isolation.CensusUnavailable, match=f"broken census: process {FAKE_PID - 1} "):
        isolation._scan(marker, (signal.SIGKILL,), not_before=launch)
    assert sent == []


def test_scan_signals_every_member_however_many_a_subject_starts(tmp_path, monkeypatch):
    """No count turns the census off: the former limit (more than 128 members: CensusUnavailable, the
    sandbox census off for the rest of the launch) was a switch any subject could reach by forking, after
    which a setsid escapee outlived the launch. 1000 members that all started after the launch are each
    found and signalled, in the kernel's listing order."""
    launch = time.time()
    starts = {FAKE_PID + i: launch + 0.5 for i in range(1000)}
    marker, sent = fake_census(tmp_path, monkeypatch, starts)
    assert isolation._scan(marker, (signal.SIGSTOP, signal.SIGKILL), not_before=launch) == sorted(starts)
    assert sent == [(pid, sig) for pid in starts for sig in (signal.SIGSTOP, signal.SIGKILL)]


def test_eligibility_excludes_the_coordinator_its_ancestors_and_old_processes():
    now = time.time()
    assert not isolation._eligible(1, 0.0) and not isolation._eligible(0, 0.0)
    assert not isolation._eligible(os.getpid(), 0.0)
    assert not isolation._eligible(os.getppid(), 0.0)
    assert not isolation._eligible(2 ** 22 + 7, 0.0)                  # no such process: unknown start, refused
    other = bystander()
    try:
        assert isolation._eligible(other.pid, now - 5.0)
        assert not isolation._eligible(other.pid, time.time() + 5.0)
    finally:
        other.kill()
        other.wait()


@needs_sandbox
def test_a_launch_whose_census_marker_vanishes_kills_only_its_own_group(tmp_path, monkeypatch):
    """End to end: census-deny disappears while the subject runs. The launcher must stop trusting the
    sandbox census (reporting it incomplete) and still kill the subject's own process group, and no
    bystander, older or younger than the launch, may be signalled."""
    assert isolation.census_available()                                # warm the cached probe (its own marker)
    older = bystander()
    made = []
    real_make = isolation._make_marker
    monkeypatch.setattr(isolation, "_make_marker", lambda directory: made.append(real_make(directory)) or made[-1])
    younger = []

    def sabotage():
        assert wait_for(lambda: bool(made), 10)
        time.sleep(0.3)
        os.unlink(made[-1][1])                                         # the launch's census-deny vanishes mid-run
        younger.append(bystander())
    helper = threading.Thread(target=sabotage)
    helper.start()
    ws = tmp_path / "ws"
    ws.mkdir()
    try:
        policy = isolation.SandboxPolicy(read_roots=[PREFIX], write_roots=[str(ws)], read_literals=[],
                                         network="none")
        result = isolation.launch([PYTHON, "-I", "-S", "-c", "import time; time.sleep(30)"], cwd=ws, env={},
                                  profile=isolation.seatbelt_profile(policy), timeout_s=1.5,
                                  stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
        helper.join()
        assert result.timed_out and result.killed and result.census_complete is False
        assert older.poll() is None and younger and younger[0].poll() is None
    finally:
        helper.join()
        for proc in [older, *younger]:
            proc.kill()
            proc.wait()


# --------------------------------------------------------------------------- real-host foundations (smoke spec)

KEYCHAIN_SERVICES = ("com.apple.SecurityServer", "com.apple.securityd.xpc")
DUMMY_TOKEN = "sk-ant-oat01-SYNTHETIC-" + "5f" * 16


def env_report(env, **kw):
    kw.setdefault("canaries", [CANARY])
    return isolation.env_admission(env, **kw)


def test_admission_check_env_rules_equal_env_admission(lab, monkeypatch):
    """The factored-out environment half keeps admission_check's verdicts exactly (no allowed secret names)."""
    monkeypatch.setenv("SYNTHETIC_PARENT_TOKEN", "synthetic-parent-secret-value")
    env = dict(lab.env, API_KEY="x", CLAUDECODE="1", NOTE=f"synthetic {CANARY}",
               PYTHONPATH=f"/usr/lib:{lab.repo / 'src'}", COPIED="prefix synthetic-parent-secret-value", BAD=3)
    whole = admit(lab.ws, env, forbidden_roots=[lab.repo])
    half = env_report(env, forbidden_roots=[lab.repo])
    assert [v for v in whole["violations"] if v["where"].startswith("env:")] == half["violations"]
    assert half["ok"] is False and ("env_invalid", "env:BAD") in codes(half)


def test_env_admission_allows_exactly_the_declared_credential_name(lab):
    env = dict(lab.env, CLAUDE_CODE_OAUTH_TOKEN=DUMMY_TOKEN)
    assert ("env_secret_name", "env:CLAUDE_CODE_OAUTH_TOKEN") in codes(env_report(env))
    allowed = env_report(env, allowed_secret_names={"CLAUDE_CODE_OAUTH_TOKEN"})
    assert allowed == {"ok": True, "violations": []}
    other = env_report(dict(env, ANTHROPIC_API_KEY="x"), allowed_secret_names={"CLAUDE_CODE_OAUTH_TOKEN"})
    assert codes(other) == {("env_secret_name", "env:ANTHROPIC_API_KEY")}
    session = env_report(dict(env, CLAUDECODE="1"), allowed_secret_names={"CLAUDECODE"})
    assert ("env_host_session", "env:CLAUDECODE") in codes(session)   # a session marker is never allowed
    assert isolation.SECRET_NAME_ALLOWLIST == frozenset({"RAVEL_TASK_TOKEN", "RAVEL_TASK_ENDPOINT"})


def test_env_admission_never_echoes_a_secret_value(lab, monkeypatch):
    """A declared credential's value is never split, resolved or echoed (R10): a value shaped like a path list
    that names a forbidden root, carries a canary and a coordinator secret gets codes with empty details."""
    monkeypatch.setenv("SYNTHETIC_PARENT_TOKEN", "synthetic-parent-secret-value")
    value = f"{lab.repo}/x:{DUMMY_TOKEN}:{CANARY}:synthetic-parent-secret-value"
    resolved = []
    real = os.path.realpath
    monkeypatch.setattr(os.path, "realpath", lambda p, *a, **k: resolved.append(p) or real(p, *a, **k))
    report = env_report(dict(lab.env, CLAUDE_CODE_OAUTH_TOKEN=value), forbidden_roots=[lab.repo],
                        allowed_secret_names={"CLAUDE_CODE_OAUTH_TOKEN"})
    mine = [v for v in report["violations"] if v["where"] == "env:CLAUDE_CODE_OAUTH_TOKEN"]
    assert {v["code"] for v in mine} == {"env_canary", "env_inherited_secret"}
    assert all(v["detail"] == "" for v in mine)
    text = json.dumps(report)
    assert DUMMY_TOKEN not in text and str(lab.repo) + "/x" not in text and DUMMY_TOKEN[:16] not in text
    assert not any(DUMMY_TOKEN in str(p) or str(p).startswith(f"{lab.repo}/x") for p in resolved)
    plain = env_report(dict(lab.env, SYNTHETIC_PATHS=f"{lab.repo}/x"), forbidden_roots=[lab.repo])
    assert ("env_forbidden_path", "env:SYNTHETIC_PATHS") in codes(plain)   # other names keep the path check


@pytest.mark.parametrize("kw", [{"canaries": []}, {"env": None}, {"forbidden_roots": ["relative"]},
                                {"allowed_secret_names": ["BAD NAME"]}, {"allowed_secret_names": "TOKEN"}])
def test_env_admission_arguments_fail_closed(lab, kw):
    kw = {"env": lab.env, "canaries": [CANARY], **kw}
    report = isolation.env_admission(kw.pop("env"), **kw)
    assert report["ok"] is False and [v["code"] for v in report["violations"]] == ["invalid_arguments"]


@pytest.mark.parametrize("marker", [".claude", "CLAUDE.local.md"])
def test_admission_refuses_a_workspace_below_a_claude_settings_marker(lab, tmp_path, marker):
    project = Path(os.path.realpath(tmp_path)) / "marked"
    project.mkdir()
    (project / marker).mkdir() if marker == ".claude" else (project / marker).write_text("synthetic\n")
    isolation.materialize({"a.txt": b"synthetic"}, project / "s-3")
    assert ("ancestor_marker", str(project)) in codes(admit(project / "s-3", lab.env))
    assert isolation.SUBJECT_ANCESTOR_MARKERS[:3] == isolation.ANCESTOR_MARKERS


def test_mach_services_removed_drops_exactly_those_lookups(tmp_path):
    ws = os.path.realpath(tmp_path)
    kept = isolation.seatbelt_profile(isolation.SandboxPolicy(read_roots=[ws]))
    assert ("(allow mach-lookup " + " ".join(f'(global-name "{s}")' for s in isolation.MACH_SERVICES) + ")"
            in kept.splitlines())   # the fake host's profile is unchanged
    assert isolation.seatbelt_profile(isolation.SandboxPolicy(read_roots=[ws], mach_services_removed=())) == kept
    removed = isolation.SandboxPolicy(read_roots=[ws], mach_services_removed=list(reversed(KEYCHAIN_SERVICES)))
    assert removed.mach_services_removed == tuple(sorted(KEYCHAIN_SERVICES))
    profile = isolation.seatbelt_profile(removed)
    expected = kept
    for service in KEYCHAIN_SERVICES:
        expected = expected.replace(f' (global-name "{service}")', "")
    assert profile == expected and '"com.apple.trustd.agent"' in profile
    for bad in (["com.example.unknown"], "com.apple.SecurityServer", [1], list(isolation.MACH_SERVICES)):
        with pytest.raises(ContractError, match="mach_services_removed"):
            isolation.SandboxPolicy(read_roots=[ws], mach_services_removed=bad)


MACH_PROBE = '''
import ctypes, json, sys
lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
bootstrap = ctypes.c_uint.in_dll(lib, "bootstrap_port").value
port = ctypes.c_uint(0)
print(json.dumps({name: lib.bootstrap_look_up(bootstrap, name.encode(), ctypes.byref(port)) for name in sys.argv[1:]}))
'''


@needs_sandbox
def test_a_removed_mach_service_cannot_be_looked_up(lab):
    """A bootstrap lookup only (no keychain item is read): KERN_SUCCESS (0) under the fake host's profile,
    BOOTSTRAP_NOT_PRIVILEGED (1100) once the real-host policy removes the service; trustd stays reachable."""
    script = lab.ws / "tmp" / "mach_probe.py"
    script.write_text(MACH_PROBE)
    names = [*KEYCHAIN_SERVICES, "com.apple.trustd.agent"]

    def lookups(**extra):
        n = next(lab.n)
        out, err = lab.coord / f"mach-{n}.out", lab.coord / f"mach-{n}.err"
        result = isolation.launch([PYTHON, "-I", "-S", str(script), *names], cwd=lab.ws, env=lab.env,
                                  profile=profile_for(lab, **extra), timeout_s=60, stdout_path=out, stderr_path=err)
        assert result.exit_code == 0, err.read_text()
        return json.loads(out.read_text())

    assert lookups() == {name: 0 for name in names}
    assert lookups(mach_services_removed=KEYCHAIN_SERVICES) == {"com.apple.SecurityServer": 1100,
                                                               "com.apple.securityd.xpc": 1100,
                                                               "com.apple.trustd.agent": 0}


def test_a_real_host_launch_reports_but_does_not_remove_unattributable_ipc(monkeypatch):
    """remove_unattributed=False (a real host's long window, R12a): a queue that records no sender or receiver and
    every new semaphore set are reported for a human, never removed; attributable residue keeps the rules."""
    before = {}
    after = {("m", 11): ipc_row("m", 11, pids=(FAKE_PID, 0)),     # the launch's segment: removed as before
             ("q", 12): ipc_row("q", 12),                          # no recorded process: left for a human
             ("q", 13): ipc_row("q", 13, pids=(FAKE_PID, 0)),     # its sender is gone: removed as before
             ("s", 14): ipc_row("s", 14)}                          # a semaphore set records none: left
    listings, removed = [after], []

    def remove(objects):
        objects = list(objects)
        removed.extend(objects)
        listings.append({k: v for k, v in after.items() if k not in objects})
    monkeypatch.setattr(isolation, "_user_names", lambda: {"subject"})
    monkeypatch.setattr(isolation, "_process_exists", lambda pid: False)
    monkeypatch.setattr(isolation, "_sysv_objects", lambda: listings.pop(0))
    monkeypatch.setattr(isolation, "_ipc_remove", remove)
    residue = isolation._ipc_residue(before, remove_unattributed=False)
    assert removed == [("m", 11), ("q", 13)]
    notes = {(e["kind"], e["id"]): (e["cleared"], e["note"]) for e in residue}
    assert notes == {("shm", 11): (True, "removed"), ("msg", 12): (False, isolation.IPC_UNATTRIBUTABLE),
                     ("msg", 13): (True, "removed"), ("sem", 14): (False, isolation.IPC_UNATTRIBUTABLE)}


def test_launch_passes_the_ipc_choice_through(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(isolation, "_run", lambda *a, **k: seen.append(k["remove_unattributed_ipc"]) or "ran")
    common = dict(cwd=tmp_path, env={}, profile=None, timeout_s=5)
    assert isolation.launch(["/usr/bin/true"], stdout_path=tmp_path / "a", stderr_path=tmp_path / "b",
                            **common) == "ran"
    assert isolation.launch(["/usr/bin/true"], stdout_path=tmp_path / "c", stderr_path=tmp_path / "d",
                            remove_unattributed_ipc=False, **common) == "ran"
    assert seen == [True, False]
    with pytest.raises(ContractError, match="remove_unattributed_ipc"):
        isolation.launch(["/usr/bin/true"], stdout_path=tmp_path / "e", stderr_path=tmp_path / "f",
                         remove_unattributed_ipc=0, **common)
