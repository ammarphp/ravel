"""Subject isolation: fresh workspace materialization, admission, Seatbelt profile, launcher.

Standard library only (ctypes reaches libSystem's process list and sandbox_check on macOS).
Seatbelt path rules are bypassed by a hardlink made outside the sandbox and by an inherited
file descriptor (Phase 0, host-and-sandbox §4.1 T6b/T7), so materialization never copies or
links, admission rejects any file with more than one link, and the launcher closes every
inherited descriptor and gives the subject pipes, never a coordinator file. `(deny default)`
alone does not stop sysctl reads of other processes' argv, environment and process table, so
the profile carries explicit process-info, kern.procargs and kern.proc denials. The profile opens
no terminal (no /dev tree, no tty or pty: the user's terminals are theirs, mode 0620) and no POSIX
shared memory or named semaphore (they outlive a run: a channel to later subjects). System V IPC
objects outlive a run too, and no profile can deny creating one (XNU asks the sandbox only about
existing objects), so a sandboxed launch lists them before and after and removes the ones the launch
left behind (LaunchResult.ipc_residue): existence at an agreed key would otherwise reach a later
subject in any workspace or arm. A subject can
leave its process group (setsid), so a sandboxed launch also finds and kills every process in
its own sandbox, however many: no count turns that census off (a member older than the launch
does, as a broken census, and the launch then reports census_complete False).
``launch(on_start=...)`` hands the coordinator the launch's {pid, pgid, marker, started_at,
leader_start} before it waits, so a restarted coordinator can census exactly that launch
(``census_launch``): the recorded sandbox marker, or the recorded process group once its leader
is proven to be the launch's; never a command-line match. See evaluation-study/slice-design.md
§8 and §10a.
"""
from __future__ import annotations

import contextlib
import ctypes
import errno
import functools
import hashlib
import os
import pwd
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .canonical import ContractError, finite_number, is_sha256, require

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
NETWORK_MODES = ("none", "localhost")
TERM_GRACE_S = 2.0       # SIGTERM -> SIGKILL grace for the subject's processes
KILL_WAIT_S = 5.0        # SIGSTOP+SIGKILL rounds repeat this long against a forking tree
CENSUS_WAIT_S = 5.0      # how long the post-kill census waits for every subject process to go
QUIET_S = 0.05           # group and sandbox must stay empty this long (then a full rescan agrees)
LEADER_WAIT_S = KILL_WAIT_S + CENSUS_WAIT_S   # after the kill rounds, how long the launcher waits to reap the leader

DRAIN_S = 1.0            # stream copying continues at most this long after the census
OUTPUT_LIMIT = 64 << 20  # read_output_tree: default cap on the total bytes read
SANDBOX_FILTER_PATH, SANDBOX_CHECK_NO_REPORT = 1, 0x40000000   # libsystem_sandbox sandbox_check
# The sandbox census has no count limit: a launch's subject may run as many processes as the per-user
# limit allows, and any count it can reach would be a switch that turns the census off (as the former
# 128-match limit was). Its sanity signal is one a subject cannot produce: every member of the launch's
# sandbox started after the launch, so a member that predates it means the membership test is broken.
#
# Start times. macOS proc_pidinfo reports the start stored at fork, in microseconds: exact and never
# moved. Linux /proc gives a start in clock ticks since boot plus the boot time in whole wall-clock seconds
# (/proc/stat btime), both truncated, so a start time read there is early by up to 1 + 1/CLK_TCK s, which
# every comparison with the wall clock allows for. btime is the wall clock less the time since boot: a
# wall-clock step (settimeofday, an NTP or chrony step, VM time sync) moves it, and with it every later read
# of every process, by whole seconds. A Linux start time therefore identifies no process across a step: the
# launcher compares _identity (boot id and start ticks, never moved by the wall clock) instead, and
# census_launch, which holds only the recorded wall-clock leader_start, treats a start time that differs from
# it by whole seconds as unprovable (START_STEPS_WHOLE_SECONDS).
PROC_ROOT = "/proc"                    # Linux: process reads come from here when /proc/self exists
LINUX_GONE_STATES = ("Z", "X", "x")   # /proc/<pid>/stat states of a zombie or dead task: not a live process
START_STEPS_WHOLE_SECONDS = os.path.isdir(f"{PROC_ROOT}/self")
START_READ_ERROR_S = 1.0 + 1.0 / os.sysconf("SC_CLK_TCK") if START_STEPS_WHOLE_SECONDS else 0.0
START_SLACK_S = 0.05 + START_READ_ERROR_S   # a subject process starts after the launch began (wall clock)
PROC_PIDTBSDINFO = 3
SZOMB = 5                # <sys/proc.h> p_stat of a zombie (pbi_status)
SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|AUTH|CREDENTIAL", re.IGNORECASE)
SECRET_NAME_ALLOWLIST = frozenset({"RAVEL_TASK_TOKEN", "RAVEL_TASK_ENDPOINT"})
# Orchestrator session variables observed in Phase 0 (§1): never inherited by a subject.
HOST_SESSION_NAME = re.compile(r"CLAUDECODE|CLAUDE_CODE_(ENTRYPOINT|EXECPATH|SESSION_ID|MESSAGING_.*)")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ANCESTOR_MARKERS = (".git", "CLAUDE.md", "AGENTS.md")   # hosts load parent-directory instructions
# What no ancestor of a subject-visible root may hold: the instruction files hosts load from parent directories
# plus Claude Code's project settings directory and local memory file (smoke spec WI-6). runner.lab_root keeps
# ANCESTOR_MARKERS: the user's home holds ~/.claude, which must not make the home directory the lab root.
SUBJECT_ANCESTOR_MARKERS = ANCESTOR_MARKERS + (".claude", "CLAUDE.local.md")
CANARY_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")   # compressed or transformed copies are not detected
ALLOW_DEFAULT = re.compile(r"\(\s*allow\s+default\b")
SYSTEM_READ_ROOTS = (
    "/usr", "/bin", "/sbin", "/System", "/Library/Frameworks", "/Library/Preferences",
    "/Library/Developer/CommandLineTools", "/Library/Apple", "/private/etc", "/etc",
    "/private/var/db/timezone", "/private/var/db/dyld", "/private/var/select", "/var/select",
    "/private/var/db/xcode_select_link", "/System/Volumes/Preboot/Cryptexes",
)
METADATA_ONLY = ("/var", "/tmp", "/etc", "/private", "/private/var", "/private/tmp", "/dev")
# Claude Code 2.1.233 template list minus appleevents, lsopen, pasteboard and launchd submission.
MACH_SERVICES = (
    "com.apple.audio.systemsoundserver", "com.apple.distributed_notifications@Uv3",
    "com.apple.FontObjectsServer", "com.apple.fonts", "com.apple.logd", "com.apple.lsd.mapdb",
    "com.apple.PowerManagement.control", "com.apple.system.logger",
    "com.apple.system.notification_center", "com.apple.system.opendirectoryd.libinfo",
    "com.apple.system.opendirectoryd.membership", "com.apple.bsd.dirhelper",
    "com.apple.securityd.xpc", "com.apple.SecurityServer", "com.apple.trustd.agent",
)
# The only devices a subject may open: no terminal of any kind. /dev is not readable as a tree: every
# pty slave (/dev/ttys*) is owned by the user, so read access to it (or the old ^/dev/ttys rule) let a
# subject open any of the operator's terminals by name, read the keystrokes typed there and write into
# it. /dev/tty, /dev/ptmx and pseudo-tty allocation are denied too: a launch is setsid'd with pipes and
# has no controlling terminal, so /dev/tty could only ever reach one that a future change let it inherit,
# and a pty the subject allocated itself would need the same by-name slave access. A host that needs a
# pty requires a reviewed profile change (an explicit, per-adapter capability with its residual recorded).
# /dev/dtracehelper is denied as well: dyld's DTrace helper registration through it is best effort (python,
# sh, env and subprocess run without it; verified 2026-09-25 on macOS 15.5), and its ioctl reaches kernel DOF
# parsing, attack surface a subject does not need. /dev/fd (and /dev/stdin, /dev/stdout, /dev/stderr, links
# into it) lists and reopens the subject's own descriptors only.
# Unverified on a live host: only the fake subject, python and sh have run under these device and IPC rules.
# A pty-backed shell tool (Codex's exec), a CLI that opens /dev/tty (EPERM, not ENXIO) and multiprocessing
# (named semaphores, below) fail under them. The live smoke before any G1 run must exercise each host's shell
# tool and a multiprocessing script under this profile; a host that needs either gets a reviewed capability.
DEVICES = '(literal "/dev/null") (literal "/dev/zero") (literal "/dev/random") (literal "/dev/urandom")'
OWN_DESCRIPTORS = ('(literal "/dev/fd") (regex #"^/dev/fd/[0-9]+$") (literal "/dev/stdin") (literal "/dev/stdout") '
                   '(literal "/dev/stderr")')
# POSIX shared memory and named semaphores outlive a run (until unlinked or reboot) and are not
# enumerable, so a subject could leave state for later subjects in other workspaces and arms: creating,
# writing or opening any is denied, as are named semaphores. Only the read-only system objects Apple's
# system.sb grants every process stay readable (libnotify's and cfprefsd's, written by those daemons alone).
SYSTEM_SHM_READ = '(ipc-posix-name "apple.shm.notification_center") (ipc-posix-name-prefix "apple.cfprefs.")'
# Other processes' argv/env (kern.procargs*) and process table (kern.proc.*: pid, ppid, uid,
# command name) stay readable under deny-default until these close the profile.
PROCESS_DENIALS = (
    "(deny process-info*)",
    "(allow process-info* (target same-sandbox))",
    '(deny sysctl-read (sysctl-name-prefix "kern.procargs"))',
    '(deny sysctl-read (sysctl-name-prefix "kern.proc."))',
)


def _clean_path(value, label, *, resolve=True) -> str:
    require(isinstance(value, (str, os.PathLike)), f"{label}: expected a path")
    text = os.fspath(value)
    require(isinstance(text, str) and os.path.isabs(text), f"{label}: expected an absolute path: {text!r}")
    require(not any(ord(c) < 32 or ord(c) == 127 for c in text), f"{label}: control character in {text!r}")
    return os.path.realpath(text) if resolve else os.path.normpath(text)


def _within(path: str, root: str) -> bool:
    """True when path equals or lies below root (also compared case-folded: APFS default)."""
    for a, b in ((path, root), (path.casefold(), root.casefold())):
        if a == b or a.startswith(b.rstrip("/") + "/"):
            return True
    return False


def _ancestors(path: str) -> list[str]:
    out = [path]
    while path != "/":
        path = os.path.dirname(path)
        out.append(path)
    return out


# --------------------------------------------------------------------------- Seatbelt profile

@dataclass(frozen=True)
class SandboxPolicy:
    """What a sandboxed subject may touch; paths are made absolute and resolved (Seatbelt
    matches resolved paths).

    read_roots: subtrees readable (workspace, interpreter prefix, pinned host binary dir).
    write_roots: subtrees readable and writable (workspace output/ and tmp/, per-run HOME).
    read_literals: single readable files. network: "none" or "localhost"; the latter needs
    localhost_ports, exactly the reachable TCP ports (broker, allowlist proxy). deny_roots:
    subtrees denied for read and write even inside an allowed root. darwin_user_temp: the
    host's DARWIN_USER_TEMP_DIR, whose xcrun_db cache /usr/bin developer shims need; None
    denies it. forbidden_roots: the store, packet and DSRLab roots; with the defaults of
    `default_forbidden_roots()` added, no read, write or literal root may lie in or contain one,
    and the profile denies each explicitly. mach_services_removed: names from MACH_SERVICES the
    profile does not let the subject look up (a real host's policy removes the keychain services
    com.apple.SecurityServer and com.apple.securityd.xpc: smoke spec R1); empty keeps them all.
    """
    read_roots: tuple = ()
    write_roots: tuple = ()
    read_literals: tuple = ()
    network: str = "none"
    localhost_ports: tuple = ()
    deny_roots: tuple = ()
    darwin_user_temp: str | None = None
    forbidden_roots: tuple = ()
    mach_services_removed: tuple = ()

    def __post_init__(self):
        for name in ("read_roots", "write_roots", "read_literals", "deny_roots", "forbidden_roots"):
            values = getattr(self, name)
            require(isinstance(values, (list, tuple, set, frozenset)), f"{name}: expected a list of paths")
            paths = {_clean_path(v, name) for v in values}
            if name == "forbidden_roots":
                paths |= set(default_forbidden_roots())
            require("/" not in paths, f"{name}: the filesystem root is not a sandbox root")
            object.__setattr__(self, name, tuple(sorted(paths)))
        for granted in self.read_roots + self.write_roots + self.read_literals:
            clash = [f for f in self.forbidden_roots if _within(granted, f) or _within(f, granted)]
            require(not clash, f"sandbox root {granted} overlaps forbidden root {clash[0] if clash else ''}")
        require(self.network in NETWORK_MODES, f"network: expected one of {NETWORK_MODES}")
        require(isinstance(self.localhost_ports, (list, tuple, set, frozenset)), "localhost_ports: expected a list")
        ports = tuple(sorted(set(self.localhost_ports)))
        require(all(type(p) is int and 0 < p < 65536 for p in ports), "localhost_ports: expected TCP ports")
        require(bool(ports) == (self.network == "localhost"),
                "localhost_ports: required for network 'localhost' and forbidden for 'none'")
        object.__setattr__(self, "localhost_ports", ports)
        if self.darwin_user_temp is not None:
            object.__setattr__(self, "darwin_user_temp", _clean_path(self.darwin_user_temp, "darwin_user_temp"))
        removed = self.mach_services_removed
        require(isinstance(removed, (list, tuple, set, frozenset)) and all(isinstance(n, str) for n in removed),
                "mach_services_removed: expected a list of mach service names")
        unknown = sorted(set(removed) - set(MACH_SERVICES))
        require(not unknown, f"mach_services_removed: {unknown} are not among the profile's mach services")
        require(len(set(removed)) < len(MACH_SERVICES), "mach_services_removed: at least one service stays")
        object.__setattr__(self, "mach_services_removed", tuple(sorted(set(removed))))


def _q(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _paths(kind: str, paths) -> str:
    return " ".join(f"({kind} {_q(p)})" for p in paths)


def seatbelt_profile(policy: SandboxPolicy) -> str:
    """Deny-default SBPL profile for one subject; deterministic for a given policy.

    Later rules win in SBPL, so explicit denials follow the allowances they narrow, and the
    process-info, kern.procargs and kern.proc denials close the profile.
    """
    require(isinstance(policy, SandboxPolicy), "seatbelt_profile: expected a SandboxPolicy")
    readable = policy.read_roots + policy.write_roots
    visible = set(SYSTEM_READ_ROOTS) | set(readable) | set(policy.read_literals)
    ancestors = sorted({a for p in visible for a in _ancestors(p)})
    lines = [
        "(version 1)",
        '(deny default (with message "ravel-subject"))',
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow process-info* (target same-sandbox))",
        "(allow signal (target same-sandbox))",
        "(allow mach-priv-task-port (target same-sandbox))",
        "(allow user-preference-read)",
        "(allow mach-lookup " + " ".join(f"(global-name {_q(s)})" for s in MACH_SERVICES
                                         if s not in policy.mach_services_removed) + ")",
        f"(allow ipc-posix-shm-read* {SYSTEM_SHM_READ})",
        '(allow iokit-open (iokit-registry-entry-class "IOSurfaceRootUserClient") '
        '(iokit-registry-entry-class "RootDomainUserClient") (iokit-user-client-class "IOSurfaceSendRight"))',
        "(allow iokit-get-properties)",
        "(allow system-socket (require-all (socket-domain AF_SYSTEM) (socket-protocol 2)))",
        "(allow sysctl-read)",
        *PROCESS_DENIALS[2:],
        "(allow distributed-notification-post)",
        f"(allow file-ioctl {DEVICES})",
        f"(allow file-read* file-write-data {DEVICES} {OWN_DESCRIPTORS})",
        '(allow file-read* (literal "/"))',
        f"(allow file-read-metadata {_paths('literal', METADATA_ONLY)})",
        f"(allow file-read* {_paths('subpath', SYSTEM_READ_ROOTS)})",
    ]
    if readable:
        lines.append(f"(allow file-read* {_paths('subpath', readable)})")
    if policy.read_literals:
        lines.append(f"(allow file-read* {_paths('literal', policy.read_literals)})")
    lines.append(f"(allow file-read-metadata {_paths('literal', ancestors)})")
    if policy.darwin_user_temp:
        lines.append(f"(allow file-read-metadata (literal {_q(policy.darwin_user_temp)}))")
        xcrun_db = _q("^" + re.escape(policy.darwin_user_temp) + "/xcrun_db")
        lines.append(f"(allow file-read* file-write* (regex {xcrun_db}))")
    if policy.write_roots:
        lines.append(f"(allow file-write* {_paths('subpath', policy.write_roots)})")
    denied = sorted(set(policy.deny_roots) | set(policy.forbidden_roots))
    lines.append(f"(deny file-read* file-write* {_paths('subpath', denied)})")
    lines.append("(allow system-socket (socket-domain AF_INET) (socket-domain AF_INET6))")
    lines.append('(allow network-outbound (literal "/private/var/run/syslog"))')
    for port in policy.localhost_ports:
        lines.append(f'(allow network-outbound (remote tcp "localhost:{port}"))')
    lines += PROCESS_DENIALS
    return "\n".join(lines) + "\n"


@functools.lru_cache(maxsize=None)
def sandbox_available() -> bool:
    """True when sandbox-exec exists, applies a profile here (not nested) and enforces a denial."""
    if sys.platform != "darwin" or not os.access(SANDBOX_EXEC, os.X_OK):
        return False

    def status(profile):
        return subprocess.run([SANDBOX_EXEC, "-p", profile, "/usr/bin/true"], env={}, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode
    try:
        return (status("(version 1)(allow default)") == 0
                and status('(version 1)(allow default)(deny process-exec (literal "/usr/bin/true"))') != 0)
    except (OSError, subprocess.SubprocessError):
        return False


# --------------------------------------------------------------------------- materialization

def _relative_parts(name) -> tuple:
    require(isinstance(name, str) and name, "materialize: names must be nonempty strings")
    body = name[:-1] if name.endswith("/") else name
    require(body and not body.startswith("/"), f"materialize: absolute or empty name: {name!r}")
    require(not any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in body),
            f"materialize: control character or backslash in {name!r}")
    parts = tuple(body.split("/"))
    require(all(p not in ("", ".", "..") for p in parts), f"materialize: traversal or empty component: {name!r}")
    require(all(p.casefold() != ".git" for p in parts), f"materialize: .git entry: {name!r}")
    return parts


def _fold(parts) -> str:
    return unicodedata.normalize("NFD", "/".join(parts)).casefold()


def materialize(files: dict, root) -> None:
    """Write fresh bytes under a new or empty root; never copy or link.

    `files` maps relative POSIX names to bytes; a name ending in "/" with b"" makes an empty
    directory. Files under a top-level `bin/` are mode 0o555, other files 0o444, directories
    0o755 and the root 0o700. Every file is created with O_EXCL|O_NOFOLLOW and the finished
    tree is re-verified (only the planned regular files and directories, st_nlink == 1, exact
    bytes). On ContractError the root is partially written and must be discarded.
    """
    require(isinstance(files, dict) and files, "materialize: files must be a nonempty dict")
    plan_files, plan_dirs = {}, set()
    for name, data in files.items():
        parts = _relative_parts(name)
        require(type(data) is bytes, f"materialize: {name!r} must map to bytes")
        if name.endswith("/"):
            require(data == b"", f"materialize: directory entry {name!r} must map to b''")
            plan_dirs.add(parts)
        else:
            plan_files[parts] = data
        plan_dirs.update(parts[:i] for i in range(1, len(parts)))
    clash = sorted(set(plan_files) & plan_dirs)
    require(not clash, f"materialize: both file and directory: {'/'.join(clash[0]) if clash else ''}")
    folded = [_fold(p) for p in list(plan_files) + sorted(plan_dirs)]
    require(len(folded) == len(set(folded)), "materialize: names collide on a case-insensitive filesystem")

    root = Path(_clean_path(root, "materialize root", resolve=False))
    try:
        if os.path.lexists(root):
            info = os.lstat(root)
            require(stat.S_ISDIR(info.st_mode) and not os.listdir(root),
                    f"materialize: root not an empty directory: {root}")
            os.chmod(root, 0o700)
        else:
            os.mkdir(root, 0o700)
        for parts in sorted(plan_dirs, key=len):
            path = root.joinpath(*parts)
            os.mkdir(path, 0o755)
            os.chmod(path, 0o755)
        for parts, data in sorted(plan_files.items()):
            mode = 0o555 if parts[0] == "bin" and len(parts) > 1 else 0o444
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
            fd = os.open(root.joinpath(*parts), flags, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                info = os.fstat(handle.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, f"materialize: {'/'.join(parts)} is linked")
                os.fchmod(handle.fileno(), mode)
    except OSError as exc:
        raise ContractError(f"materialize: {exc}") from exc
    _verify_materialized(root, plan_files, plan_dirs)


def _raise(exc):
    raise ContractError(f"materialize: {exc}")


def _verify_materialized(root: Path, plan_files: dict, plan_dirs: set) -> None:
    seen_files, seen_dirs = set(), set()
    for current, dirs, names in os.walk(root, onerror=_raise):
        for name in dirs + names:
            path = os.path.join(current, name)
            parts = tuple(Path(path).relative_to(root).parts)
            info = os.lstat(path)
            if stat.S_ISDIR(info.st_mode):
                seen_dirs.add(parts)
                continue
            require(stat.S_ISREG(info.st_mode), f"materialize: not a regular file: {'/'.join(parts)}")
            require(info.st_nlink == 1, f"materialize: {'/'.join(parts)} has st_nlink={info.st_nlink}")
            with open(path, "rb") as handle:
                require(handle.read() == plan_files.get(parts), f"materialize: unexpected bytes in {'/'.join(parts)}")
            seen_files.add(parts)
    require(seen_files == set(plan_files) and seen_dirs == plan_dirs, "materialize: tree differs from the plan")


# --------------------------------------------------------------------------- admission

def _repository_roots(start=None) -> list[str]:
    """Every checkout enclosing `start` (default: this module), plus the owner of a worktree's
    or submodule's gitdir (a relative `gitdir:` is relative to its .git file)."""
    roots = []
    for ancestor in Path(start or __file__).resolve().parents:
        marker = ancestor / ".git"
        if marker.is_dir():
            roots.append(ancestor)
        elif marker.is_file():
            roots.append(ancestor)
            text = marker.read_text(errors="replace").strip()
            if text.startswith("gitdir:"):
                gitdir = (ancestor / text[len("gitdir:"):].strip()).resolve()
                owner = next((p.parent for p in [gitdir, *gitdir.parents] if p.name == ".git"), None)
                if owner is not None:
                    roots.append(owner)
    return [os.path.realpath(r) for r in roots]


def default_forbidden_roots() -> list[str]:
    """Roots no subject workspace or sandbox root may overlap even when the caller names none.
    The repository part exists only when this module runs from a git checkout."""
    home = os.path.expanduser("~")
    return sorted(set(_repository_roots()) | {os.path.realpath(os.path.join(home, d)) for d in (".claude", ".codex")})


def _walk(root: str, flag):
    """(name, relative path, path, lstat) for every entry under root, sorted; never follows links."""
    for current, dirs, names in os.walk(root, onerror=lambda exc: flag("unreadable", exc.filename, exc)):
        dirs.sort()
        for name in sorted(dirs + names):
            path = os.path.join(current, name)
            rel = os.path.relpath(path, root)
            try:
                info = os.lstat(path)
            except OSError as exc:
                flag("unreadable", rel, exc)
                continue
            yield name, rel, path, info


def _open_same(path: str, expected):
    """Read-only handle on the regular file lstat saw (no link following, no FIFO blocking), or None."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino) or not stat.S_ISREG(info.st_mode):
        os.close(fd)
        return None
    return os.fdopen(fd, "rb")


def _scan_file(path, needles, forbidden_sha256, flag, rel, expected) -> None:
    try:
        handle = _open_same(path, expected)
    except OSError as exc:
        flag("unreadable", rel, str(exc))
        return
    if handle is None:
        flag("changed_during_check", rel, "inode changed between lstat and open")
        return
    with handle:
        keep = max(len(n) for _, n in needles) - 1
        h, tail, found = hashlib.sha256(), b"", set()   # one pass: hash and canary scan see the same bytes
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
            window = tail + block
            found.update(i for i, n in needles if n in window)
            tail = window[-keep:] if keep else b""
    if h.hexdigest() in forbidden_sha256:
        flag("forbidden_content", rel, f"sha256 {h.hexdigest()} is evaluator-private")
    for index in sorted(found):
        flag("canary", rel, f"canary #{index} present")


def admission_check(subject_root, *, forbidden_sha256: set, canaries: list, env: dict,
                    forbidden_roots=()) -> dict:
    """Fail-closed check of a materialized workspace and its launch environment.

    Returns {"ok", "violations"}; each violation is {"code", "where", "detail"}; invalid
    arguments (an empty canary or hash set included) give one "invalid_arguments" violation.
    Rejects symlinks, special files, st_nlink > 1, set-id bits, any `.git` entry,
    evaluator-private content (by sha256), canaries in file names, in file contents (UTF-8 or
    UTF-16; compressed or transformed copies are not detected) or in env, secret-looking or
    orchestrator-session env names (except RAVEL_TASK_TOKEN/RAVEL_TASK_ENDPOINT), env paths or
    coordinator secret values leaking in, a root overlapping a forbidden root (the caller's,
    which should name the store, packet and DSRLab roots, plus `default_forbidden_roots()`),
    and an ancestor holding one of SUBJECT_ANCESTOR_MARKERS. The environment rules are ``env_admission``'s.
    """
    try:
        require(isinstance(forbidden_sha256, (set, frozenset)) and forbidden_sha256
                and all(is_sha256(h) for h in forbidden_sha256), "forbidden_sha256: expected a nonempty set of SHA-256")
        require(isinstance(canaries, (list, tuple)) and canaries and all(isinstance(c, str) and c for c in canaries),
                "canaries: expected a nonempty list of nonempty strings")
        require(isinstance(env, dict), "env: expected a dict")
        require(isinstance(forbidden_roots, (list, tuple, set, frozenset)), "forbidden_roots: expected a list")
        root = _clean_path(subject_root, "subject_root", resolve=False)
        forbidden = sorted({_clean_path(r, "forbidden_roots") for r in forbidden_roots}
                           | set(default_forbidden_roots()))
    except ContractError as exc:
        return {"ok": False, "violations": [{"code": "invalid_arguments", "where": "arguments", "detail": str(exc)}]}
    violations = []

    def flag(code, where, detail):
        violations.append({"code": code, "where": str(where), "detail": str(detail)})

    real = os.path.realpath(root)
    for other in forbidden:
        if _within(real, other) or _within(other, real):
            flag("forbidden_root", real, f"overlaps {other}")
    for ancestor in _ancestors(real)[1:]:
        for marker in SUBJECT_ANCESTOR_MARKERS:
            if os.path.lexists(os.path.join(ancestor, marker)):
                flag("ancestor_marker", ancestor, f"contains {marker}")

    if os.path.islink(root):
        flag("symlink", ".", "subject root is a symlink")
    elif not os.path.isdir(root):
        flag("not_a_directory", ".", "subject root missing or not a directory")
    else:
        needles = [(i, c.encode(enc)) for i, c in enumerate(canaries) for enc in CANARY_ENCODINGS]
        for name, rel, path, info in _walk(root, flag):
            if name.casefold() == ".git":
                flag("git_entry", rel, "version-control metadata")
            for index, canary in enumerate(canaries):
                if canary in name:
                    flag("canary_name", rel, f"canary #{index} in the name")
            if stat.S_ISLNK(info.st_mode):
                flag("symlink", rel, "symbolic link")
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1:
                    flag("hardlink", rel, f"st_nlink={info.st_nlink}")
                if info.st_mode & (stat.S_ISUID | stat.S_ISGID):
                    flag("setid_bit", rel, oct(info.st_mode))
                _scan_file(path, needles, forbidden_sha256, flag, rel, info)
            elif not stat.S_ISDIR(info.st_mode):
                flag("special_file", rel, oct(info.st_mode))

    violations += _env_violations(env, canaries, forbidden, frozenset())
    violations.sort(key=lambda v: (v["code"], v["where"], v["detail"]))
    return {"ok": not violations, "violations": violations}


def env_admission(env: dict, *, canaries: list, forbidden_roots=(), allowed_secret_names=frozenset()) -> dict:
    """The launch-environment half of ``admission_check``: {"ok", "violations"} for ``env`` alone.

    ``allowed_secret_names`` are the credential variables a real-host campaign declares (``host_launch
    .credential.env_name``, smoke spec WI-5): such a name may look like a credential, and its value is never
    split, resolved or echoed. Only name-level checks (orchestrator session names, a canary in the name) and
    value checks that record a code with an empty detail (a canary in the value, a coordinator credential value
    inside it) apply to it; the path checks, which copy a path-like part of a value into their detail and resolve
    it, are skipped. Every other name gets exactly admission_check's rules; the global SECRET_NAME_ALLOWLIST is
    unchanged. Invalid arguments give one "invalid_arguments" violation."""
    try:
        require(isinstance(canaries, (list, tuple)) and canaries and all(isinstance(c, str) and c for c in canaries),
                "canaries: expected a nonempty list of nonempty strings")
        require(isinstance(env, dict), "env: expected a dict")
        require(isinstance(forbidden_roots, (list, tuple, set, frozenset)), "forbidden_roots: expected a list")
        require(isinstance(allowed_secret_names, (list, tuple, set, frozenset))
                and all(isinstance(n, str) and ENV_NAME.fullmatch(n) for n in allowed_secret_names),
                "allowed_secret_names: expected variable names")
        forbidden = sorted({_clean_path(r, "forbidden_roots") for r in forbidden_roots}
                           | set(default_forbidden_roots()))
    except ContractError as exc:
        return {"ok": False, "violations": [{"code": "invalid_arguments", "where": "arguments", "detail": str(exc)}]}
    violations = _env_violations(env, canaries, forbidden, frozenset(allowed_secret_names))
    violations.sort(key=lambda v: (v["code"], v["where"], v["detail"]))
    return {"ok": not violations, "violations": violations}


def _env_violations(env: dict, canaries, forbidden, allowed_secret_names) -> list:
    violations = []

    def flag(code, where, detail):
        violations.append({"code": code, "where": str(where), "detail": str(detail)})

    inherited = {v for k, v in os.environ.items()
                 if SECRET_NAME.search(k) and k not in SECRET_NAME_ALLOWLIST and len(v) >= 8}
    for name, value in sorted(env.items(), key=lambda item: str(item[0])):
        where = f"env:{name}"
        if not (isinstance(name, str) and isinstance(value, str)):
            flag("env_invalid", where, "names and values must be strings")
            continue
        if HOST_SESSION_NAME.fullmatch(name):
            flag("env_host_session", where, "orchestrator session variable")
        if name in allowed_secret_names:   # the declared credential: codes only, the value never echoed
            for index, canary in enumerate(canaries):
                if canary in name:
                    flag("env_canary", where, f"canary #{index} present")
            if any(canary in value for canary in canaries):
                flag("env_canary", where, "")
            if any(secret in value for secret in inherited):
                flag("env_inherited_secret", where, "")
            continue
        if name not in SECRET_NAME_ALLOWLIST and SECRET_NAME.search(name):
            flag("env_secret_name", where, "name looks like a credential")
        for index, canary in enumerate(canaries):
            if canary in name or canary in value:
                flag("env_canary", where, f"canary #{index} present")
        for part in value.split(os.pathsep):
            if part.startswith("/") and any(_within(os.path.realpath(part), r) for r in forbidden):
                flag("env_forbidden_path", where, part)
        if any(secret in value for secret in inherited):
            flag("env_inherited_secret", where, "value contains a coordinator credential value")
    return violations


def read_output_tree(root, *, max_bytes: int = OUTPUT_LIMIT) -> tuple[dict, list]:
    """Read a subject-written tree (output/) for sealing without trusting it.

    Returns ({relative path: bytes}, violations) with admission-shaped violations. Only regular
    files with st_nlink == 1 are read, each opened O_NOFOLLOW|O_NONBLOCK and checked to be the
    inode lstat saw; symlinks (a subject can plant one to an evaluator file), special files,
    hardlinked files and anything past max_bytes in total are reported and never read.
    """
    require(type(max_bytes) is int and max_bytes >= 0, "read_output_tree: max_bytes must be a nonnegative int")
    files, violations, total = {}, [], 0

    def flag(code, where, detail):
        violations.append({"code": code, "where": str(where), "detail": str(detail)})

    root = _clean_path(root, "output root", resolve=False)
    if os.path.islink(root) or not os.path.isdir(root):
        flag("not_a_directory", ".", "output root missing, a symlink or not a directory")
        return files, violations
    for _, rel, path, info in _walk(root, flag):
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            flag("symlink" if stat.S_ISLNK(info.st_mode) else "special_file", rel, oct(info.st_mode))
        elif info.st_nlink != 1:
            flag("hardlink", rel, f"st_nlink={info.st_nlink}")
        elif total + info.st_size > max_bytes:
            flag("too_large", rel, f"{info.st_size} bytes past the {max_bytes}-byte limit")
        else:
            try:
                handle = _open_same(path, info)
            except OSError as exc:
                flag("unreadable", rel, exc)
                continue
            if handle is None:
                flag("changed_during_check", rel, "inode changed between lstat and open")
                continue
            with handle:
                data = handle.read(max_bytes - total + 1)
            if total + len(data) > max_bytes:
                flag("too_large", rel, f"grew past the {max_bytes}-byte limit")
                continue
            files[rel] = data
            total += len(data)
    violations.sort(key=lambda v: (v["code"], v["where"], v["detail"]))
    return files, violations


def subject_env(*, workspace, home, path_dirs, extra: dict) -> dict:
    """Subject environment built from scratch (os.environ is never read): HOME, LANG, PATH,
    TMPDIR=<workspace>/tmp, plus `extra` (broker endpoint/token, adapter variables), which may
    not override those four."""
    workspace = _clean_path(workspace, "workspace")
    require(isinstance(path_dirs, (list, tuple)) and path_dirs, "path_dirs: expected a nonempty list")
    dirs = [_clean_path(d, "path_dirs") for d in path_dirs]
    require(all(os.pathsep not in d for d in dirs), "path_dirs: entries may not contain the path separator")
    env = {"HOME": _clean_path(home, "home"), "LANG": "en_US.UTF-8", "PATH": os.pathsep.join(dirs),
           "TMPDIR": os.path.join(workspace, "tmp")}
    require(isinstance(extra, dict), "extra: expected a dict")
    for name, value in extra.items():
        require(isinstance(name, str) and ENV_NAME.fullmatch(name), f"extra: invalid variable name {name!r}")
        require(isinstance(value, str) and "\0" not in value, f"extra: {name} must be a string without NUL")
        require(name not in env, f"extra: may not override {name}")
        env[name] = value
    return env


# --------------------------------------------------------------------------- launcher

@dataclass(frozen=True)
class LaunchResult:
    """exit_code is the leader's return code (negative: killed by that signal). killed is True
    when the launcher signalled subject processes (timeout, or processes left behind after
    the leader exited). survivors lists subject processes still present after the census:
    group members and, for a sandboxed launch, every process in the launch's sandbox whatever
    its group or session. For profile None only the process group is covered. census_complete
    is False when the sandbox census became unusable during the launch (its marker vanished, or it
    matched a process older than the launch; never because of how many processes the subject ran):
    only the process group was then searched and signalled, so a setsid escapee may have gone unseen.
    ipc_residue (sandboxed launches) lists the System V IPC objects this user created during the launch,
    each {kind ("msg"|"shm"|"sem"), id, key, cleared, note}; cleared is True only when the launcher removed
    it and a fresh listing no longer shows it (see _ipc_residue for what is never removed). Empty: none was
    left. None: not checked (profile None) or unknown (the listing after the launch failed)."""
    exit_code: int
    timed_out: bool
    wall_seconds: float
    killed: bool
    survivors: list
    census_complete: bool = True
    ipc_residue: list | None = None


class CensusUnavailable(ContractError):
    """The sandbox census cannot be trusted right now; nothing was signalled on its account.

    sandbox_check reports a path it cannot resolve as denied for EVERY process. With census-deny
    missing and census-allow present, the membership test would match every unsandboxed process
    on the host; on 2026-09-25 that turned the SIGSTOP+SIGKILL rounds into a kill of the user's
    whole login session (docs/development/evaluation-study/incident-2026-09-25.md)."""


class _ProcBSDInfo(ctypes.Structure):   # <sys/proc_info.h> struct proc_bsdinfo
    _fields_ = [("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32), ("pbi_xstatus", ctypes.c_uint32),
                ("pbi_pid", ctypes.c_uint32), ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
                ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32), ("pbi_rgid", ctypes.c_uint32),
                ("pbi_svuid", ctypes.c_uint32), ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
                ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32), ("pbi_nfiles", ctypes.c_uint32),
                ("pbi_pgid", ctypes.c_uint32), ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
                ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32), ("pbi_start_tvsec", ctypes.c_uint64),
                ("pbi_start_tvusec", ctypes.c_uint64)]


@functools.lru_cache(maxsize=None)
def _libsystem():
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    lib.proc_listallpids.restype = ctypes.c_int
    lib.proc_listallpids.argtypes = [ctypes.c_void_p, ctypes.c_int]
    # sandbox_check(pid, operation, filter type, ...): private libsystem_sandbox SPI (also used by
    # Chromium and WebKit); the path is passed as the variadic argument; 0 allowed, 1 denied.
    lib.sandbox_check.restype = ctypes.c_int
    lib.sandbox_check.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    return lib


@functools.lru_cache(maxsize=None)
def _boot_id(proc: str = PROC_ROOT):
    """Linux: this boot's random id (start ticks restart at every boot), or None if unreadable."""
    try:
        return Path(f"{proc}/sys/kernel/random/boot_id").read_text().strip() or None
    except OSError:
        return None


def _linux_stat_fields(text: str) -> list:
    """The fields of a /proc/<pid>/stat line after "(comm)": state [0], ppid [1], pgrp [2], ... starttime
    [19] (field 22 overall). The command name may itself hold spaces and ")" (a process names itself), so the
    line is split at its LAST ")". Raises IndexError when there is none (a malformed line)."""
    return text.rsplit(")", 1)[1].split()


def _linux_proc_read(pid: int, proc: str = PROC_ROOT):
    """_proc_read from a Linux /proc tree (`proc`, a parameter only so recorded Linux samples can be read on
    any host): (ppid, btime + starttime / CLK_TCK, ("linux", boot id, starttime)), or None for a process that
    is gone, a zombie or dead (state Z, X or the pre-3.14 x), or whose stat line or /proc/stat does not parse."""
    try:
        fields = _linux_stat_fields(Path(f"{proc}/{pid}/stat").read_text())
        if fields[0] in LINUX_GONE_STATES:
            return None
        boot = next(float(line.split()[1]) for line in Path(f"{proc}/stat").read_text().splitlines()
                    if line.startswith("btime "))
        ticks = int(fields[19])
        return int(fields[1]), boot + ticks / os.sysconf("SC_CLK_TCK"), ("linux", _boot_id(proc), ticks)
    except (OSError, IndexError, ValueError, StopIteration):
        return None


def _proc_read(pid: int):
    """(parent pid, start time in seconds since the epoch, identity) of a live process, else None
    (gone, a zombie awaiting its parent's wait, or not ours to inspect). macOS: proc_pidinfo, the start
    stored at fork (microseconds), which is also the identity. Linux: /proc (_linux_proc_read), whole-second
    boot time plus clock ticks since boot, early by up to START_READ_ERROR_S and moved by wall-clock steps; its
    identity is (boot id, start ticks), which no wall-clock step moves."""
    if pid <= 0:
        return None
    if os.path.isdir(f"{PROC_ROOT}/self"):
        return _linux_proc_read(pid)
    try:
        info = _ProcBSDInfo()
        size = _libsystem().proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    except (OSError, AttributeError):
        return None
    if size != ctypes.sizeof(info) or info.pbi_status == SZOMB:
        return None
    sec, usec = int(info.pbi_start_tvsec), int(info.pbi_start_tvusec)
    return int(info.pbi_ppid), sec + usec / 1e6, ("darwin", sec, usec)


def _proc_info(pid: int):
    """(parent pid, start time in seconds since the epoch) of a live process, else None; see _proc_read."""
    info = _proc_read(pid)
    return None if info is None else info[:2]


def _start_time(pid: int):
    info = _proc_read(pid)
    return None if info is None else info[1]


def _identity(pid: int):
    """A live process's clock-independent identity (with its pid it names one process), else None."""
    info = _proc_read(pid)
    return None if info is None else info[2]


def _whole_seconds_apart(a, b) -> bool:
    """True when two unequal start times may still be one process's, so a holder with start `a` proves
    nothing either way about a record of `b` (census_launch: unprovable). That is when they differ by a whole
    number of seconds within 1e-4 s, zero included:
    - zero (a nonzero difference under 1e-4 s, on every platform): finer than any start-time resolution
      (1/CLK_TCK s on Linux, 1 us on macOS), so float noise in one process's start (a record that did not
      round-trip exactly), never proof of a second process. Unreachable while the journal round-trips floats
      exactly; it fails closed rather than calling a possibly live leader foreign;
    - a nonzero whole number (Linux only): a wall-clock step between two reads of one process (start ticks are
      integral and btime whole seconds, so reads of one process can differ only so). Two distinct processes
      differ so only when their ticks happen to be a multiple of CLK_TCK apart, which this cannot rule out.
    On macOS a start is stored at fork and never moves, so any larger difference is another process."""
    if a is None or b is None or a == b:
        return False
    if abs(a - b) < 1e-4:
        return True
    return START_STEPS_WHOLE_SECONDS and abs((a - b) - round(a - b)) < 1e-4


def _protected_pids() -> set:
    """The coordinator and its ancestors: never a subject, whatever any census says."""
    protected, pid = {0, 1}, os.getpid()
    while pid > 1 and pid not in protected:
        protected.add(pid)
        info = _proc_info(pid)
        pid = info[0] if info else 0
    return protected


def _eligible(pid: int, not_before: float) -> bool:
    """A process the launcher may signal: not the coordinator or an ancestor, not pid 0/1, and
    started no earlier than the launch (a process that predates it cannot be its subject)."""
    if pid <= 1 or pid in _protected_pids():
        return False
    start = _start_time(pid)
    return start is not None and start >= not_before


def _all_pids() -> list[int]:
    """Every pid, newest first (kernel process-list order; pids wrap, so numeric order is not age)."""
    lib, size = _libsystem(), 4096
    while True:
        buf = (ctypes.c_int * size)()
        count = lib.proc_listallpids(buf, ctypes.sizeof(buf))
        if count < size:
            return [p for p in buf[:max(count, 0)] if p > 0]
        size *= 2


def _make_marker(directory: str) -> tuple:
    """Two fresh coordinator files for a launch's census: its profile allows metadata reads of
    the first and denies the second, a pair no other sandbox on the host grants."""
    paths = tuple(os.path.join(os.path.realpath(directory), name) for name in ("census-allow", "census-deny"))
    for path in paths:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600))
    return paths


def _marker_rules(marker) -> str:
    return (f"(allow file-read-metadata (literal {_q(marker[0])}))\n"
            f"(deny file-read-metadata (literal {_q(marker[1])}))\n")


def _marker_intact(marker) -> bool:
    """Both census files are regular files that the (unsandboxed) coordinator may read the metadata
    of. sandbox_check answers 'denied' for an unresolvable path for every process, so without this
    check a missing census-deny file makes every process on the host look like a subject."""
    check, me = _libsystem().sandbox_check, os.getpid()
    for path in marker:
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                return False
        except OSError:
            return False
        if check(me, b"file-read-metadata", SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT, path.encode()) != 0:
            return False
    return True


def _scan(marker, signals=(), *, not_before: float) -> list[int]:
    """Processes, in any group or session, inside the sandbox that carries `marker` (sandbox
    membership is inherited and irrevocable, so a subject cannot leave this set), each sent
    `signals` as soon as it is found (a forking chain's live member is signalled microseconds
    after it is seen). Fails closed, raising CensusUnavailable and signalling nothing further: the
    marker must be intact before the scan, before every signal and after the scan, and no member may
    predate `not_before` (the launch start). Every process in the launch's sandbox descends from the
    launch, so an older member means the membership test matches processes that are not the launch's
    (as it did every process on the host on 2026-09-25): a first, signal-free pass looks for one before
    anything is signalled, and the signalling pass stops at one. No count of members is limited: a
    subject cannot start a process older than its launch, but it can start many. Members started at or
    after `not_before` and outside the coordinator's ancestry are returned and signalled; one whose start
    time cannot be read (gone, or a zombie) is neither."""
    if marker is None:
        return []
    check = _libsystem().sandbox_check
    flags = SANDBOX_FILTER_PATH | SANDBOX_CHECK_NO_REPORT
    allow, deny = (m.encode() for m in marker)
    protected = _protected_pids()

    def member(pid):
        return pid not in protected and check(pid, b"file-read-metadata", flags, deny) == 1 \
            and check(pid, b"file-read-metadata", flags, allow) == 0

    def require_intact(when):
        if not _marker_intact(marker):
            raise CensusUnavailable(f"census marker missing, replaced or unreadable ({when}): subject processes "
                                    "cannot be identified by sandbox; nothing further signalled")

    def predates(pid, start, when):
        return CensusUnavailable(f"broken census: process {pid} matched the launch's sandbox but started at "
                                 f"{start:.6f}, before the launch ({not_before:.6f}); the membership test matches "
                                 f"processes that are not the launch's ({when}): nothing further signalled")
    require_intact("before the scan")
    for pid in _all_pids():   # signal-free pass: a member older than the launch means a broken census
        if member(pid):
            start = _start_time(pid)
            if start is not None and start < not_before:
                raise predates(pid, start, "before any signal")
    found = []
    for pid in _all_pids():
        if not member(pid):
            continue
        require_intact("during the scan")
        start = _start_time(pid)
        if start is None:
            continue
        if start < not_before:
            raise predates(pid, start, "during the scan")
        found.append(pid)
        for sig in signals:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                break
    require_intact("after the scan")
    return sorted(found)


@functools.lru_cache(maxsize=None)
def census_available() -> bool:
    """True when the sandbox census works here: a marked sandboxed process is found and no
    other process on the host matches its marker (an older one would raise CensusUnavailable).
    Sandboxed launches refuse without it."""
    if not sandbox_available():
        return False
    directory = tempfile.mkdtemp(prefix="ravel-census-")
    try:
        marker = _make_marker(directory)
        floor = time.time() - START_SLACK_S
        proc = subprocess.Popen([SANDBOX_EXEC, "-p", "(version 1)(allow default)\n" + _marker_rules(marker),
                                 "/bin/sleep", "30"], env={}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                found = _scan(marker, not_before=floor)
                if found:
                    return found == [proc.pid]
                time.sleep(0.02)
            return False
        finally:
            proc.kill()
            proc.wait()
    except (OSError, AttributeError, subprocess.SubprocessError, CensusUnavailable):
        return False
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(pgid: int, *signals, leader_id=None) -> None:
    """killpg to the launch's own group only: never pgid 0/1 or the coordinator's group, and never
    a group whose id now belongs to a different leader (the live process with that pid has another
    _identity than the leader had at the launch; a wall-clock step changes no identity)."""
    if pgid <= 1 or pgid == os.getpgrp():
        return
    if leader_id is not None:
        holder = _identity(pgid)
        if holder is not None and holder != leader_id:
            return
    for sig in signals:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            pass


class _Watch:
    """One launch's identity for every signal the launcher sends: its group, its sandbox marker,
    its start time, its leader's start time (recorded for census_launch) and its leader's _identity
    (compared before every killpg). `census` turns False (for good) once the sandbox census proved
    unusable (its marker vanished, or it matched a process older than the launch); the launcher then
    searches and signals the process group only. No number of subject processes turns it off."""

    def __init__(self, pgid, marker, not_before, leader_start, leader_id=None):
        self.pgid, self.marker, self.not_before, self.leader_start = pgid, marker, not_before, leader_start
        self.leader_id = leader_id
        self.census = True

    def scan(self, signals=()):
        if self.marker is None or not self.census:
            return []
        try:
            return _scan(self.marker, signals, not_before=self.not_before)
        except CensusUnavailable:
            self.census = False
            return []


def _remaining(watch: _Watch, wait_s: float, *, signals=(), proc=None) -> list[int]:
    """Subject processes still present. Polls the process group and (sandboxed) the launch's
    sandbox, sending `signals` to whatever it finds, until both have stayed empty for QUIET_S
    (one empty scan can miss a member that forked and exited mid-scan) -> [], or until wait_s
    has passed with something still present -> the survivors. proc: the leader, reaped as it
    goes so its zombie does not count."""
    pgid, quiet_since, deadline = watch.pgid, None, time.monotonic() + wait_s
    while True:
        if proc is not None:
            proc.poll()
        group = _group_alive(pgid)
        if group:
            _signal_group(pgid, *signals, leader_id=watch.leader_id)
        found = watch.scan(signals)
        marker = watch.marker if watch.census else None
        now = time.monotonic()
        if group or found:
            quiet_since = None
            if now >= deadline:
                return sorted(set(found) | set(_group_members(pgid) if group else ())) or [pgid]
        elif marker is None:
            return []
        elif quiet_since is None:
            quiet_since = now
        elif now - quiet_since >= QUIET_S:
            return []
        time.sleep(0.001 if marker else 0.02)


def _terminate(proc, watch: _Watch, grace: float) -> None:
    """SIGTERM to every subject process; after `grace`, SIGSTOP+SIGKILL rounds to whatever is
    left until none remains (a forking chain outruns a single SIGKILL) or KILL_WAIT_S passes."""
    _signal_group(watch.pgid, signal.SIGTERM, leader_id=watch.leader_id)
    watch.scan((signal.SIGTERM,))
    if grace > 0 and not _remaining(watch, grace, proc=proc):
        return
    _remaining(watch, KILL_WAIT_S, signals=(signal.SIGSTOP, signal.SIGKILL), proc=proc)


def _linux_group_members(pgid: int, proc: str = PROC_ROOT) -> list[int]:
    """Every pid under a Linux /proc tree whose stat line names process group `pgid` (zombies included, as
    `ps -A` lists them on macOS); an entry that vanishes or does not parse is skipped. `proc` is a parameter
    only so recorded Linux samples can be read on any host."""
    members = []
    for entry in filter(str.isdigit, os.listdir(proc)):
        try:
            if int(_linux_stat_fields(Path(f"{proc}/{entry}/stat").read_text())[2]) == pgid:
                members.append(int(entry))
        except (OSError, IndexError, ValueError):
            continue
    return sorted(members)


def _group_members(pgid: int) -> list[int]:
    if os.path.isdir(f"{PROC_ROOT}/self"):
        return _linux_group_members(pgid)
    listing = subprocess.run(["/bin/ps", "-A", "-o", "pid=", "-o", "pgid="], capture_output=True, text=True,
                             env={}, timeout=30, check=False).stdout
    rows = (line.split() for line in listing.splitlines())
    return sorted(int(r[0]) for r in rows if len(r) == 2 and r[1].isdigit() and int(r[1]) == pgid)


def _census(watch: _Watch, wait_s: float) -> list[int]:
    """Post-kill census: [] once no subject process is left, else the survivors after wait_s."""
    return _remaining(watch, wait_s)


# --------------------------------------------------------------------------- System V IPC residue
# A sandboxed subject can create System V message queues, shared-memory segments and semaphore sets (shmget,
# msgget or semget with IPC_CREAT): XNU asks the sandbox about looking up, attaching or controlling an
# EXISTING object, never about creating one, so no profile rule prevents it. It cannot attach, read or remove
# one, but the objects outlive it (until removed or reboot), and a later sandboxed lookup of an agreed key
# fails with EPERM when an object exists and ENOENT when none does: existence alone carries data to later
# subjects in any workspace or arm (reproduced 2026-09-25, review of eval/fix-isolation). kern.sysv.shmmni is
# 32 here, so leftovers can also exhaust shared memory for every process of the host. The coordinator, outside
# the sandbox, therefore lists every object before a sandboxed launch and after its census, and removes what
# the launch left (_ipc_residue).

IPCS, IPCRM = "/usr/bin/ipcs", "/usr/bin/ipcrm"
IPC_SECTIONS = {"Message Queues:": "q", "Shared Memory:": "m", "Semaphores:": "s"}   # ipcs -a section titles
IPC_KIND_NAMES = {"q": "msg", "m": "shm", "s": "sem"}
IPC_PIDS = {"q": ("LSPID", "LRPID"), "m": ("CPID", "LPID"), "s": ()}   # the processes ipcs names for an object
IPC_COLUMNS = ("T", "ID", "KEY", "OWNER", "CREATOR")
IPC_REMOVE_BATCH = 256   # ids per ipcrm call
# The note on a System V object a launch with remove_unattributed_ipc=False reports and never removes (R12a).
IPC_UNATTRIBUTABLE = "unattributable over a long window: left for a human"


class IpcUnavailable(ContractError):
    """The host's System V IPC listing failed or did not parse. Before a sandboxed launch this refuses the
    launch (nothing started); after one the launch's residue is unknown (LaunchResult.ipc_residue None)."""


def _sysv_objects() -> dict:
    """Every System V IPC object on the host, from `ipcs -a` (see _parse_ipcs). An id carries a per-slot
    sequence number, so a later object does not reuse the id of one that existed. Raises IpcUnavailable
    unless ipcs exits 0 with output _parse_ipcs accepts."""
    try:
        out = subprocess.run([IPCS, "-a"], env={}, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        text = out.stdout.decode("ascii")
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
        raise IpcUnavailable(f"System V IPC listing failed: {exc}") from exc
    if out.returncode != 0:
        raise IpcUnavailable(f"System V IPC listing failed: ipcs exited {out.returncode}: "
                             f"{out.stderr.decode(errors='replace').strip()}")
    return _parse_ipcs(text)


def _parse_ipcs(text: str) -> dict:
    """{(kind, id): {column: value}} from `ipcs -a` output, kind "q" (message queue), "m" (shared memory) or
    "s" (semaphore set). Raises IpcUnavailable unless every line is the status line, a column header, one of
    the three section titles (each once, under a header naming its columns) or a row of that section's width
    with a numeric id, a key and numeric process ids."""
    header, kind, numeric, sections, objects = None, None, (), set(), {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or line.startswith("IPC status from "):
            continue
        if fields[0] == "T":
            header, kind = fields, None
            continue
        if line.strip() in IPC_SECTIONS and header is not None:
            kind = IPC_SECTIONS[line.strip()]
            numeric = ("ID",) + IPC_PIDS[kind] + (("NATTCH",) if kind == "m" else ())
            if kind in sections or not all(c in header for c in IPC_COLUMNS + numeric):
                raise IpcUnavailable(f"System V IPC listing: unexpected section {line.strip()!r} under {header}")
            sections.add(kind)
            continue
        row = dict(zip(header or (), fields))
        if (kind is None or fields[0] != kind or len(fields) != len(header)
                or not all(row[c].isdigit() for c in numeric) or not re.fullmatch(r"0x[0-9a-fA-F]+|-?\d+", row["KEY"])):
            raise IpcUnavailable(f"System V IPC listing: unexpected line {line!r}")
        objects[(kind, int(row["ID"]))] = row
    if sections != set(IPC_SECTIONS.values()):
        raise IpcUnavailable(f"System V IPC listing: sections {sorted(sections)} instead of all three")
    return objects


def _user_names() -> set:
    """How ipcs names this process's user: its login name, or its uid when it has none."""
    names = {str(os.getuid())}
    try:
        names.add(pwd.getpwuid(os.getuid()).pw_name)
    except KeyError:
        pass
    return names


def _process_exists(pid: int) -> bool:
    """False only when pid is certainly no live process (no such process, or a zombie); a live process of any
    user, including one this process may not inspect, exists. Reads only (proc_pidinfo); never a signal."""
    info = _ProcBSDInfo()
    try:
        size = _libsystem().proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    except (OSError, AttributeError):
        return True
    if size == ctypes.sizeof(info):
        return info.pbi_status != SZOMB
    return ctypes.get_errno() != errno.ESRCH


def _ipc_remove(objects) -> None:
    """IPC_RMID by id (ipcrm -q/-m/-s) on each (kind, id); failures show in the listing that follows."""
    objects = list(objects)
    for i in range(0, len(objects), IPC_REMOVE_BATCH):
        argv = [IPCRM]
        for kind, ident in objects[i:i + IPC_REMOVE_BATCH]:
            argv += [f"-{kind}", str(ident)]
        subprocess.run(argv, env={}, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)


def _ipc_residue(before: dict, *, remove_unattributed: bool = True) -> list | None:
    """The System V IPC objects a launch left behind, removed where that is provably safe; None when the
    host's listing after the launch fails (residue unknown). `before` is the listing taken before the launch.

    Reported: every object listed now and not before (created during the launch window: ids are not reused)
    whose creator is this user (every subject process runs as this user; another user's object is never the
    launch's and is ignored). Removed (IPC_RMID): each reported object that this user also owns, that no
    process has attached (shared memory) and whose recorded processes (creator and last user of a segment,
    last sender and receiver of a queue) are all gone. The census has ended every subject process, so a live
    one belongs to another program (or is a survivor the census reports): its object is never removed, only
    reported. The residual: a message queue or semaphore set that another program of this user creates and has
    not yet used during the window records no live process and is removed. ``remove_unattributed=False``
    (a real host's launch, whose window is long: smoke spec R12a) closes that residual: a new message queue
    that records no sending or receiving process, and every new semaphore set (ipcs records none for one), is
    reported with the note IPC_UNATTRIBUTABLE and never removed. Each entry is {kind, id, key, cleared, note};
    cleared is True only when a fresh listing no longer shows a removed object."""
    try:
        after = _sysv_objects()
    except IpcUnavailable:
        return None
    me, residue, removable = _user_names(), [], []
    for (kind, ident), row in sorted(after.items()):
        if (kind, ident) in before or row["CREATOR"] not in me:
            continue
        entry = {"kind": IPC_KIND_NAMES[kind], "id": ident, "key": row["KEY"], "cleared": False, "note": None}
        recorded = [int(row[c]) for c in IPC_PIDS[kind]]
        live = sorted({p for p in recorded if p > 0 and _process_exists(p)})
        if row["OWNER"] not in me:
            entry["note"] = f"owned by {row['OWNER']}, not this user: not removed"
        elif live or (kind == "m" and int(row["NATTCH"]) > 0):
            entry["note"] = (f"in use (live process(es) {live}, {row.get('NATTCH', '0')} attached): a live process "
                             "is not the launch's once its census ended; not removed")
        elif not remove_unattributed and kind in ("q", "s") and not any(p > 0 for p in recorded):
            entry["note"] = IPC_UNATTRIBUTABLE
        else:
            removable.append(((kind, ident), entry))
        residue.append(entry)
    if removable:
        try:
            _ipc_remove(key for key, _ in removable)
            final = _sysv_objects()
        except (IpcUnavailable, OSError, subprocess.SubprocessError) as exc:
            final, failure = None, str(exc)
        for key, entry in removable:
            if final is None:
                entry["note"] = f"removal unverified: {failure}"
            elif key in final:
                entry["note"] = "removal failed: still listed"
            else:
                entry.update(cleared=True, note="removed")
    return residue


def _check_profile(profile: str) -> None:
    require(isinstance(profile, str) and profile.startswith("(version 1)") and "(deny default" in profile
            and not ALLOW_DEFAULT.search(profile), "launch: profile must be a deny-default SBPL profile")
    require(sandbox_available(), "launch: sandbox-exec is unavailable; refusing to run a sandboxed launch unsandboxed")
    require(census_available(), "launch: the sandbox process census (sandbox_check) is unavailable here")


def _probe_profile(profile: str, directory: str) -> None:
    """The launched profile must load and must deny reading a fresh coordinator-private file."""
    def run(*argv):
        return subprocess.run([SANDBOX_EXEC, "-p", profile, *argv], cwd="/", env={}, stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=30)
    probe = run("/usr/bin/true")
    detail = probe.stderr.decode(errors="replace").strip()
    require(probe.returncode == 0, f"launch: profile rejected by sandbox-exec: {detail}")
    private, nonce = os.path.join(os.path.realpath(directory), "private"), secrets.token_hex(16)
    Path(private).write_text(nonce)
    probe = run("/bin/cat", "/dev/null", private)
    require(nonce.encode() not in probe.stdout and f"{private}: Operation not permitted".encode() in probe.stderr,
            "launch: profile does not deny reading a coordinator-private file")


def _pump(proc, data: bytes, sinks, stop, errors) -> None:
    """Feed stdin and copy the stdout/stderr pipes into coordinator files. The subject holds
    only pipe ends: it cannot seek, truncate or name the raw-stream files (Phase 0 §5)."""
    try:
        with selectors.DefaultSelector() as sel:
            for pipe, sink in sinks:
                sel.register(pipe, selectors.EVENT_READ, sink)
            pending = memoryview(data)
            if proc.stdin is not None:
                if pending:
                    os.set_blocking(proc.stdin.fileno(), False)
                    sel.register(proc.stdin, selectors.EVENT_WRITE)
                else:
                    proc.stdin.close()
            drain_until = None
            while sel.get_map():
                if stop.is_set() and drain_until is None:
                    drain_until = time.monotonic() + DRAIN_S
                events = sel.select(0 if drain_until else 0.05)
                if drain_until is not None and (not events or time.monotonic() > drain_until):
                    return
                for key, _ in events:
                    if key.fileobj is proc.stdin:
                        try:
                            pending = pending[os.write(key.fd, pending[:1 << 16]):]
                        except BlockingIOError:
                            continue
                        except OSError:            # the subject closed its stdin
                            pending = pending[:0]
                        done = not pending
                    else:
                        chunk = os.read(key.fd, 1 << 16)
                        key.data.write(chunk)
                        done = not chunk
                    if done:
                        sel.unregister(key.fileobj)
                        key.fileobj.close()
    except Exception as exc:   # surfaced by launch after cleanup
        errors.append(exc)


def launch(argv, *, cwd, env, profile: str | None, timeout_s, stdout_path, stderr_path,
           stdin_path=None, on_start=None, remove_unattributed_ipc: bool = True) -> LaunchResult:
    """Run argv (no shell) in a new session with only `env`, every other descriptor closed and
    stdin fed from stdin_path (or /dev/null). stdout and stderr are pipes the coordinator
    copies into stdout_path/stderr_path (created exclusively). At the wall limit every subject
    process gets SIGTERM, then after TERM_GRACE_S repeated SIGSTOP+SIGKILL rounds; processes
    left behind by a leader that exited are killed the same way, as is everything when the
    coordinator itself is interrupted; a census then lists survivors (see LaunchResult).

    A sandboxed launch appends two census-marker rules (metadata of two fresh coordinator
    files, nothing else) to `profile`, requires the result to load and to deny reading a
    coordinator-private file, and finds subject processes by that marker in any process group
    or session. It also lists the host's System V IPC objects just before the start (refusing the
    launch, IpcUnavailable, when it cannot) and again after the census, and removes the objects
    the launch left (LaunchResult.ipc_residue, _ipc_residue; with ``remove_unattributed_ipc`` False, as
    for a real host, a message queue or semaphore set no process is recorded for is reported and left for
    a human). profile None runs unsandboxed (tests of the timeout logic only) and covers only the process
    group. Raises ContractError for invalid arguments or profiles and OSError when the program cannot be
    started or its streams cannot be copied.

    ``on_start`` (optional) is called exactly once, right after the child starts and before the
    launcher waits on it, with ``{"pid", "pgid", "marker", "started_at", "leader_start"}`` (pgid
    equals pid: a new session; marker is the two census-marker paths of a sandboxed launch, else None;
    started_at is the wall-clock time taken just before the child was started, the census signal
    floor; leader_start is the leader's kernel start time, which with its pid identifies the group's
    leader (on Linux only until the wall clock steps: see START_STEPS_WHOLE_SECONDS), or None if it had
    already exited): the record a restarted coordinator needs for
    ``census_launch``. If it raises, the subject is killed and the exception propagates.
    """
    require(isinstance(argv, (list, tuple)) and argv and all(isinstance(a, str) and "\0" not in a for a in argv),
            "launch: argv must be a nonempty list of strings")
    require(os.path.isabs(argv[0]) and os.path.isfile(argv[0]) and os.access(argv[0], os.X_OK),
            "launch: argv[0] must be an absolute path to an executable file")
    require(isinstance(env, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()),
            "launch: env must be an explicit dict of strings")
    cwd = _clean_path(cwd, "cwd", resolve=False)
    require(os.path.isdir(cwd), f"launch: cwd is not a directory: {cwd}")
    require(finite_number(timeout_s) and timeout_s > 0, "launch: timeout_s must be a positive finite number")
    require(on_start is None or callable(on_start), "launch: on_start must be callable or None")
    require(type(remove_unattributed_ipc) is bool, "launch: remove_unattributed_ipc must be a bool")
    stdout_path, stderr_path = (_clean_path(p, "output path", resolve=False) for p in (stdout_path, stderr_path))
    require(stdout_path != stderr_path, "launch: stdout_path and stderr_path must differ")
    require(not any(os.path.lexists(p) for p in (stdout_path, stderr_path)), "launch: output files must not exist")
    stdin_data = None
    if stdin_path is not None:
        stdin_path = _clean_path(stdin_path, "stdin_path", resolve=False)
        require(os.path.isfile(stdin_path), f"launch: stdin_path is not a file: {stdin_path}")
        stdin_data = Path(stdin_path).read_bytes()
    command, marker, directory, ipc_before = list(argv), None, None, None
    if profile is not None:
        _check_profile(profile)
    try:
        if profile is not None:
            directory = tempfile.mkdtemp(prefix="ravel-census-")
            marker = _make_marker(directory)
            profile = profile.rstrip("\n") + "\n" + _marker_rules(marker)
            _probe_profile(profile, directory)
            ipc_before = _sysv_objects()   # IpcUnavailable (a ContractError): refused, nothing started
            command = [SANDBOX_EXEC, "-p", profile, *command]
        with open(stdout_path, "xb", buffering=0) as fout, open(stderr_path, "xb", buffering=0) as ferr:
            return _run(command, cwd, env, timeout_s, stdin_data, (fout, ferr), marker, on_start,
                        ipc_before=ipc_before, remove_unattributed_ipc=remove_unattributed_ipc)
    finally:
        if directory is not None:
            shutil.rmtree(directory, ignore_errors=True)


# Deferred interrupts (E-81). The live coordinator's SIGHUP and SIGTERM handlers raise an interrupt in the main thread
# at any bytecode (cli.install_live_handlers). Two windows must not be cut: between starting a subject and recording
# its start (a lost launch without a record could never be censused), and while an interrupted launch is being killed
# (a second signal would leave it running without a wall limit). Inside ``interrupts_deferred`` a handler that calls
# ``interrupt(exc)`` records the interrupt instead of raising it; the outermost section re-raises it when it ends. The
# process signal mask is never touched: a mask blocked across Popen would be inherited by the subject through exec.
_DEFERRAL = {"depth": 0, "pending": None}


@contextlib.contextmanager
def interrupts_deferred():
    """Hold interrupts delivered through ``interrupt`` until the outermost section ends, then raise the first one
    (after the section's own cleanup has run). Only the main thread's sections count: signal handlers run there."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    _DEFERRAL["depth"] += 1
    try:
        yield
    finally:
        _DEFERRAL["depth"] -= 1
        if _DEFERRAL["depth"] == 0 and _DEFERRAL["pending"] is not None:
            pending, _DEFERRAL["pending"] = _DEFERRAL["pending"], None
            raise pending


def interrupt(exc: BaseException) -> None:
    """For a signal handler: raise ``exc`` now, or, inside ``interrupts_deferred``, once the section ends."""
    if _DEFERRAL["depth"] > 0:
        if _DEFERRAL["pending"] is None:
            _DEFERRAL["pending"] = exc
        return
    raise exc


def _reap(proc, wait_s: float) -> bool:
    """Wait at most ``wait_s`` for our own child ``proc`` to exit; whether it did. Every wait on a launch's leader is
    bounded (E-97): a leader stuck in an uninterruptible kernel wait survives SIGKILL, and an unbounded wait there would
    hang the coordinator with its proxy and broker still up."""
    try:
        proc.wait(timeout=wait_s)
        return True
    except subprocess.TimeoutExpired:
        return False


def _run(command, cwd, env, timeout_s, stdin_data, sinks, marker, on_start=None, *, ipc_before=None,
         remove_unattributed_ipc=True) -> LaunchResult:
    start, launched_at = time.monotonic(), time.time()
    proc = watch = pump = None
    timed_out, killed, finished = False, False, False
    stop, errors = threading.Event(), []
    try:
        with interrupts_deferred():   # an interrupt here is raised only once the start is on record
            proc = subprocess.Popen(command, cwd=cwd, env=env, bufsize=0, close_fds=True, start_new_session=True,
                                    stdin=subprocess.DEVNULL if stdin_data is None else subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            pgid = proc.pid
            leader = _proc_read(proc.pid) or (None, None, None)   # read once: recorded start, compared identity
            watch = _Watch(pgid, marker, launched_at - START_SLACK_S, leader[1], leader[2])
            pump = threading.Thread(target=_pump, name="launch-streams", daemon=True,
                                    args=(proc, stdin_data or b"", ((proc.stdout, sinks[0]), (proc.stderr, sinks[1])),
                                          stop, errors))
            if on_start is not None:   # before any wait: a coordinator that dies from here on left a record
                on_start({"pid": proc.pid, "pgid": pgid, "marker": None if marker is None else list(marker),
                          "started_at": launched_at, "leader_start": watch.leader_start})
        pump.start()
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
        if timed_out or _remaining(watch, 0.0):
            killed = True
            _terminate(proc, watch, TERM_GRACE_S)
        unreaped = not _reap(proc, LEADER_WAIT_S)   # a leader that outlived SIGKILL (an uninterruptible wait, E-97)
        wall = time.monotonic() - start
        survivors = _census(watch, CENSUS_WAIT_S)
        if unreaped and proc.poll() is None:   # never waited on forever: reported as a survivor (S3), not hidden
            survivors = sorted(set(survivors) | {proc.pid})
        finished = True
    finally:
        with interrupts_deferred():   # a second interrupt never cuts the kill or the cleanup short
            if proc is not None:
                if not finished and watch is None:   # its start could not even be read: our own child, by handle
                    proc.kill()
                    _reap(proc, LEADER_WAIT_S)
                elif not finished:   # coordinator interrupted: never leave the subject running (or its IPC objects)
                    _terminate(proc, watch, 0.0)
                    if ipc_before is not None:
                        _ipc_residue(ipc_before, remove_unattributed=remove_unattributed_ipc)   # best effort
                stop.set()
                if pump is not None and pump.ident is not None:
                    pump.join(timeout=DRAIN_S + 10)
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    if pipe is not None and (pump is None or not pump.is_alive()):
                        pipe.close()
    ipc_residue = None if ipc_before is None else _ipc_residue(   # after the census: subject gone
        ipc_before, remove_unattributed=remove_unattributed_ipc)
    if errors:
        raise OSError(f"launch: copying the subject's streams failed: {errors[0]!r}") from errors[0]
    return LaunchResult(exit_code=proc.returncode, timed_out=timed_out, wall_seconds=wall, killed=killed,
                        survivors=survivors, census_complete=watch.census, ipc_residue=ipc_residue)


# --------------------------------------------------------------------------- lost-launch census

LAUNCH_RECORD_KEYS = ("pid", "pgid", "marker", "started_at", "leader_start")
MARKER_NAMES = ("census-allow", "census-deny")


def check_launch_record(record) -> dict:
    """The on_start record of one launch: {pid, pgid (== pid), marker (null or the two marker paths),
    started_at (wall-clock seconds just before the launch; no subject process started earlier),
    leader_start (the leader's kernel start time as _proc_info reads it, no earlier than started_at less
    START_SLACK_S, which allows for Linux's read error; or null when the leader had already exited when
    the record was made)}. A pid and its start time identify one process: the group's leader, and
    through it the group (a group id is never reused while the group exists). On Linux a wall-clock step
    moves every later start-time read by whole seconds, which census_launch treats as unprovable."""
    require(isinstance(record, dict) and set(record) == set(LAUNCH_RECORD_KEYS),
            f"launch record: fields must be {list(LAUNCH_RECORD_KEYS)}")
    pid, pgid, marker = record["pid"], record["pgid"], record["marker"]
    require(type(pid) is int and pid > 1 and pgid == pid and type(pgid) is int,
            "launch record: pid and pgid must be one process id above 1 (the launcher starts a new session)")
    require(marker is None or (isinstance(marker, list) and len(marker) == 2
                               and all(isinstance(m, str) and os.path.isabs(m) and "\0" not in m for m in marker)
                               and os.path.dirname(marker[0]) == os.path.dirname(marker[1])
                               and tuple(os.path.basename(m) for m in marker) == MARKER_NAMES),
            "launch record: marker must be null or the launch's two census-marker paths")
    require(finite_number(record["started_at"]) and record["started_at"] > 0,
            "launch record: started_at must be a positive wall-clock time")
    leader = record["leader_start"]
    require(leader is None or (finite_number(leader) and leader >= record["started_at"] - START_SLACK_S),
            "launch record: leader_start must be null or the leader's start time, no earlier than started_at "
            f"less {START_SLACK_S:.2f} s")
    return record


def _restore_marker(marker) -> list:
    """Recreate a lost launch's missing census files, BOTH of them (launch removes its marker
    directory when it returns). The sandbox rules name both paths; sandbox_check reports a missing
    path as denied for every process, so restoring census-allow alone would make every process on
    the host look like a subject (incident-2026-09-25.md). Returns what was created."""
    created, directory = [], os.path.dirname(marker[0])
    if not os.path.lexists(directory):
        os.mkdir(directory, 0o700)
        created.append(directory)
    require(os.path.isdir(directory) and not os.path.islink(directory), f"census: {directory} is not a directory")
    for path in marker:
        if not os.path.lexists(path):
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600))
            created.append(path)
    return created


def census_launch(record, *, wait_s: float = CENSUS_WAIT_S) -> dict:
    """Census of one lost launch from its on_start record, for a coordinator that restarted after
    losing it (or whose adapter raised). Only that launch is searched; nothing matches by command
    line and no process group is signalled as a group (killpg is never used: the recorded id may
    since belong to a group the launcher did not create).

    Sandboxed (a marker): every process inside the launch's sandbox, in any group or session (sandbox
    membership is inherited and irrevocable), gets SIGSTOP+SIGKILL by pid until the sandbox stays
    empty for QUIET_S or ``wait_s`` passes; missing census files are recreated for the scan (both,
    never one) and the scan fails closed exactly as in ``launch``. Members of the recorded group outside
    that sandbox are not the launch's (every subject process runs inside it) and are listed as
    ``foreign``, never signalled.

    Unsandboxed: the recorded group is the launch's only while its id is held by the launch's leader,
    the live process with the recorded pid AND ``leader_start`` (a group id equals its creator's pid,
    and neither is reused while the group or that process exists). On Linux a start time read after a
    wall-clock step differs from the record by whole seconds (START_STEPS_WHOLE_SECONDS), and on any
    platform a nonzero difference under 1e-4 s is float noise (_whole_seconds_apart); such a holder
    cannot be told from a later process, so it proves nothing: nothing further is signalled, the members
    are listed ``foreign`` and the census is incomplete. While the identity holds, every member of
    the group that started no earlier than the launch gets SIGSTOP+SIGKILL by pid until none is left
    or ``wait_s`` passes; the holder is re-checked every round, after the members are listed. A setsid
    escapee is not seen (as in ``launch``). If a different process holds the id, the launch's group
    ended before that process was created: its members are ``foreign`` and nothing is signalled. If no
    live, inspectable process holds the id while the group lives (the leader exited, or ``leader_start``
    was never recorded), the group's identity is unprovable: nothing is signalled, its members are
    listed ``foreign`` and the census is incomplete. The start-time floor alone cannot tell the
    launch's group from a later group with the same id, whose members all started after the launch.
    A proven group holds only the launch's session, so a live member the floor excludes (a wrong start
    time or record) is not signalled, is listed as a survivor and makes the census incomplete.

    Only processes started at or after the recorded ``started_at`` (less START_SLACK_S) are ever
    signalled, and never the coordinator or its ancestors. Returns {method, launch, found, killed,
    survivors, foreign, complete, note}: ``killed`` lists every pid signalled; ``foreign`` lists
    recorded-group members never signalled because they are not proven to be the launch's;
    ``complete`` is false (with a note) when the census could not search the launch's sandbox, list the
    members of a live recorded group, prove its process group or signal a live member of the proven group.
    """
    record = check_launch_record(record)
    me, pgid, marker = os.getpid(), record["pgid"], record["marker"]
    not_before = record["started_at"] - START_SLACK_S
    require(pgid != os.getpgrp() and record["pid"] != me, "census: the launch record names the coordinator itself")
    signals = (signal.SIGSTOP, signal.SIGKILL)
    result = {"launch": record, "found": [], "killed": [], "survivors": [], "foreign": [], "complete": True,
              "note": None}
    if marker is None:
        result["method"] = ("unsandboxed launch: SIGSTOP+SIGKILL by pid to the recorded process group's members "
                            "while the recorded leader (pid and start time) holds the group id")
        leader_start = record["leader_start"]
        seen, remaining, deadline = set(), [], time.monotonic() + wait_s
        foreign, ours, excluded, proven = set(), set(), set(), False
        while True:
            alive = _group_alive(pgid)
            members = [p for p in _group_members(pgid) if p != me] if alive else []
            if not members:
                remaining = []
                # An empty listing proves nothing while the group still answers killpg(0): the listing skipped
                # entries it could not read or parse (Linux /proc) or `ps` failed (macOS). Re-checked, so a
                # group that ended between the probe and the listing still ends the census complete.
                if alive and _group_alive(pgid):
                    result.update(complete=False, note=(
                        f"group {pgid} is alive but none of its members could be listed; nothing further "
                        "signalled, survivors unknown"))
                break
            holder = _start_time(pgid)   # after the listing: those members were the holder's group's
            if _whole_seconds_apart(holder, leader_start):   # the leader across a clock step (or noise), or not
                foreign.update(p for p in members if p not in ours)
                remaining = []
                result.update(complete=False, note=(
                    f"group identity unprovable: the process holding group id {pgid} started {holder}, a whole "
                    f"number of seconds (zero included) from the recorded leader's {leader_start}; a wall-clock step "
                    "moves every Linux start time read by whole seconds, and a difference under 1e-4 s is noise, so "
                    "it may be the launch's leader or a later process; nothing further signalled, survivors unknown"))
                break
            if holder is not None and holder != leader_start:
                foreign.update(p for p in members if p not in ours)
                remaining = []
                result["note"] = (f"the recorded group id {pgid} is held by a process other than the launch's leader "
                                  f"(start time {holder}, recorded {leader_start}): the launch's group ended "
                                  "before it was created; its members are foreign and were not signalled")
                break
            if holder is None and not proven:
                foreign.update(members)
                remaining = []
                result.update(complete=False, note=(
                    f"group identity unprovable: no live process with the recorded leader's pid and start time "
                    f"holds group id {pgid} while the group has members (the leader exited or its start time "
                    "was never recorded); nothing signalled, survivors unknown"))
                break
            proven = True   # a leader that exited since (killed here) leaves the group it proved
            eligible = {p for p in members if _eligible(p, not_before)}
            ours.update(eligible)
            # A member that was eligible and then died (killed here, or exiting by itself) lingers as a
            # zombie until its parent reaps it: no start time, so neither eligible, a survivor nor foreign.
            # A proven group holds only the launch's session (the leader's descendants), so a live member
            # the floor or the protected set excludes means a start time or the record is wrong: it is
            # never signalled (the floor is never overridden) and the census cannot vouch for it.
            others = [p for p in members if p not in eligible and p not in ours and p not in excluded]
            excluded.update(p for p in others if _start_time(p) is not None)
            foreign.update(p for p in others if p not in excluded)
            remaining = sorted(eligible - foreign)
            if not remaining or time.monotonic() >= deadline:
                break
            for pid in remaining:
                for sig in signals:
                    try:
                        os.kill(pid, sig)
                    except (ProcessLookupError, PermissionError):
                        break
                seen.add(pid)
            time.sleep(0.02)
        if excluded:   # live ones are survivors: never signalled, still running
            remaining = sorted(set(remaining) | {p for p in excluded if _start_time(p) is not None})
            note = (f"the proven group {pgid} held live member(s) {sorted(excluded)} that started before the "
                    f"launch's floor ({not_before:.3f}) or are the coordinator's own, which the census may not "
                    "signal: not signalled, survivors unknown")
            result.update(complete=False, note=f"{result['note']}; {note}" if result["note"] else note)
        result.update(found=sorted(seen | set(remaining) | excluded), killed=sorted(seen),
                      survivors=sorted(remaining), foreign=sorted(foreign))
        return result
    result["method"] = ("sandboxed launch: SIGSTOP+SIGKILL by pid to every process in the launch's sandbox "
                        "(found by its census marker); recorded group members outside it are foreign")
    if not census_available():
        result.update(complete=False, note="the sandbox census (sandbox_check) is unavailable here")
        return result
    try:
        created = _restore_marker(marker)
    except (OSError, ContractError) as exc:
        result.update(complete=False, note=f"the census marker could not be restored: {exc}")
        return result
    try:
        seen, survivors, quiet_since, deadline = set(), [], None, time.monotonic() + wait_s
        while True:
            try:
                found = _scan(marker, signals, not_before=not_before)
            except CensusUnavailable as exc:
                result.update(complete=False, note=f"the sandbox census became unusable: {exc}")
                found, survivors = [], []
                break
            now = time.monotonic()
            if found:
                seen.update(found)
                quiet_since = None
                if now >= deadline:
                    survivors = found
                    break
            elif quiet_since is None:
                quiet_since = now
            elif now - quiet_since >= QUIET_S:
                break
            time.sleep(0.001)
        members = [p for p in _group_members(pgid) if p != me and p not in seen] if _group_alive(pgid) else []
        try:   # a member this census killed (a zombie until reaped) is not foreign
            foreign = sorted(set(members) - set(_scan(marker, not_before=not_before)))
        except CensusUnavailable:
            foreign = sorted(members)
    finally:
        for path in reversed(created):
            (os.rmdir if os.path.isdir(path) else os.unlink)(path)
    result.update(found=sorted(seen), killed=sorted(seen), survivors=sorted(survivors), foreign=foreign)
    return result
