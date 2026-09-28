"""Real-host (live) campaign support: what a synthetic engineering smoke with the Claude Code CLI needs beyond the
fake host (docs/development/evaluation-study/smoke-request.md and the smoke implementation spec, §9 steps 5-7).

- Foundations: the pinned (binary, model) pair (``HostPin``), the approval checks and the store's single-use
  approval ledger (R9), the names that may never reach a real host, the credential variable each real adapter
  declares and the byte check that the pinned binary knows the model id (R2).
- The launch declaration and the Claude binding: ``default_host_launch`` (``coordinator/config.json``
  ``host_launch``), ``claude_host_config`` (§4.2), ``claude_adapter`` (the one adapter both the build-time binding
  and every launch are made from, R20) and ``claude_factory``; ``build_live_campaign`` (WI-1).
- Host attribution for the per-launch proxy (``socket_owned_by``: proc_pidinfo, R6), the keychain residue check
  (``keychain_residue``, LC-21) and the sandbox-denial collector (``sandbox_denials``, best effort, F14).
- ``validate_credential`` (the run-start validation: read and discarded; a failure is a pause, R8) and
  ``preflight`` (WI-2).
- ``code_signature``: the pin's hardened runtime without get-task-allow, required at build and in preflight (E-90).
- ``host_probe`` (HP-01 to HP-13, WI-7c): every probe launch goes through isolation.launch with its start recorded
  under ``coordinator/host_probe/<n>/<id>/`` and is censused by that record if a coordinator loses it, or again while
  its census is unclean (R12c, E-96).
- ``live_checks`` (LC-01 to LC-23, WI-7d), ``costs`` (§5) and the stop rules (``STOP_RULES``, ``stop_reason``,
  §4); the S10a gate (``go_no_go_problem``, ``record_go_no_go``: run 1 is reviewed and signed before run 2, E-92).

The credential: nothing here reads the real token except ``validate_credential`` (through credentials.py, value
discarded). The host probes inject a DUMMY token they generate and sweep for it afterwards; they never read the
declared file. Every record names variables, never values. Nothing here signals by name or pattern: the probe
servers (proxy, echo, mock API, task service) are threads of this process stopped by handle, and a lost probe
launch is censused only through its own recorded start (isolation.census_launch). Standard library only.
"""
from __future__ import annotations

import contextlib
import ctypes
import fcntl
import functools
import hashlib
import json
import os
import re
import secrets
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import allowlist_proxy, campaign_manifest, canonical, contracts, credentials, isolation, runner
from .adapters import claude_cli
from .canonical import ContractError, require

APPROVAL_LEDGER = "live-approvals.jsonl"   # one line per approval ever consumed, in the per-user LEDGER_DIR
# The approval ledger is per user, never per store (E-77): an approval consumed by a campaign in one store cannot build
# another campaign in any other store. It has a directory of its own (E-89), which the first claim creates 0700: the
# procedure's `mkdir -p` of the pinned copy's directory (smoke-request S3) leaves ~/.local/share/ravel-eval with the
# umask's mode (0755), so that directory is only the ledger directory's parent, which must be this user's and carry
# no group or other write bit. Tests point LEDGER_DIR at a scratch directory; nothing else changes it.
LEDGER_DIR = "~/.local/share/ravel-eval/approvals"
LEDGER_DIR_MODE = 0o700
# The credential variable each real adapter declares, and the init apiKeySource it expects (F6).
CREDENTIAL_ENV_NAMES = {"claude_cli": {"CLAUDE_CODE_OAUTH_TOKEN": "none"}}
# Names that may never be present in a real host's environment (smoke spec §1.3), nor in the coordinator's own
# environment at preflight: other credentials and endpoints (every ANTHROPIC_*), the fd credential variant, bare
# mode (which ignores the OAuth token), an orchestrating session's markers, the keychain-name override, remote
# and third-party provider switches, custom OAuth endpoints, and runtime injection (NODE_OPTIONS, BUN_*).
NEVER_PRESENT = frozenset({"CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_ENTRYPOINT",
                           "CLAUDECODE", "CLAUDE_SECURESTORAGE_CONFIG_DIR", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
                           "CLAUDE_CODE_CUSTOM_OAUTH_URL", "CLAUDE_CODE_OAUTH_CLIENT_ID", "NODE_OPTIONS"})
NEVER_PRESENT_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_REMOTE", "CLAUDE_CODE_USE_", "BUN_")
MODEL_QUOTES = (b'"', b"'", b"`")   # a model id in the bundle's JavaScript is a quoted string literal
LEDGER_LOCK_S = 30.0                 # how long a ledger read or claim waits for another holder, then refuses
SCAN_BLOCK = 8 << 20


@dataclass(frozen=True)
class HostPin:
    """The real host a live campaign pins: adapter, the harness-owned executable (the inner binary of a copied
    ``.app``), its sha256 and version, the full model id (no ``[1m]`` suffix) and the ``--effort`` level."""
    adapter: str
    executable: str
    executable_sha256: str
    version: str
    model: str
    effort: str

    def __post_init__(self):
        require(self.adapter in CREDENTIAL_ENV_NAMES, f"HostPin.adapter: one of {sorted(CREDENTIAL_ENV_NAMES)}")
        require(isinstance(self.executable, str) and os.path.isabs(self.executable)
                and os.path.normpath(self.executable) == self.executable,
                "HostPin.executable: normalized absolute path")
        require(canonical.is_sha256(self.executable_sha256), "HostPin.executable_sha256: SHA-256 required")
        for name in ("version", "model"):
            value = getattr(self, name)
            require(isinstance(value, str) and value.strip() == value and value, f"HostPin.{name}: nonempty string")
        require("[" not in self.model and not any(c.isspace() for c in self.model),
                "HostPin.model: a full model id without a context suffix such as [1m]")
        efforts = claude_cli.EFFORTS
        require(self.effort in efforts, f"HostPin.effort: one of {list(efforts)}")

    def fields(self) -> dict:
        """The host fields an approval's ``scope.host`` names."""
        return {"adapter": self.adapter, "version": self.version, "executable_sha256": self.executable_sha256,
                "model": self.model, "effort": self.effort}


def never_present(names) -> list:
    """The sorted names in ``names`` that may never reach a real host (NEVER_PRESENT, NEVER_PRESENT_PREFIXES)."""
    return sorted(n for n in names if n in NEVER_PRESENT or n.startswith(NEVER_PRESENT_PREFIXES))


def model_in_binary(executable, model) -> bool:
    """Whether the model id appears as a quoted string literal in the pinned binary's bytes (R2). Necessary, not
    sufficient: HP-13 must still show the pin prices the model with its own entry. Reads the file in blocks."""
    require(isinstance(model, str) and model and model.isascii() and not any(c in model for c in "\"'`\\")
            and not any(c.isspace() for c in model), "model_in_binary: a plain ASCII model id is required")
    needles = [q + model.encode() + q for q in MODEL_QUOTES]
    keep = max(len(n) for n in needles) - 1
    tail = b""
    with open(executable, "rb") as handle:
        for block in iter(lambda: handle.read(SCAN_BLOCK), b""):
            window = tail + block
            if any(n in window for n in needles):
                return True
            tail = window[-keep:]
    return False


CODESIGN = "/usr/bin/codesign"
CODESIGN_COMMAND = (CODESIGN,)       # the argv prefix of every signature read (tests: a synthetic stand-in)
CS_RUNTIME = 0x10000                 # the CodeDirectory flag of the hardened runtime
GET_TASK_ALLOW = "com.apple.security.get-task-allow"
CODE_DIRECTORY_FLAGS = re.compile(r"^CodeDirectory v=\S+ size=\S+ flags=(0x[0-9a-fA-F]+)", re.MULTILINE)


def code_signature(executable, *, timeout_s=30) -> dict:
    """The pinned binary's code signature as the kernel enforces it (E-90): {hardened_runtime, get_task_allow, flags,
    entitlements, problems}, read with ``codesign -d`` (display only; the binary is never executed). The profile allows
    ``mach-priv-task-port`` and ``process-info*`` within the one sandbox the host shares with the subject, so only
    the hardened runtime without get-task-allow keeps a subject's process from the host's task port and memory, where
    the token lives (F1); ``problems`` is empty only when the signature shows exactly that."""
    problems, found = [], {"hardened_runtime": None, "get_task_allow": None, "flags": None, "entitlements": None}
    env = {"PATH": "/usr/bin:/bin"}
    try:
        shown = subprocess.run([*CODESIGN_COMMAND, "-d", "--verbose=2", os.fspath(executable)], env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s, close_fds=True)
        listed = subprocess.run([*CODESIGN_COMMAND, "-d", "--entitlements", "-", "--xml", os.fspath(executable)],
                                env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s,
                                close_fds=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return {**found, "problems": [f"codesign could not read the signature: {type(exc).__name__}: {exc}"]}
    if shown.returncode != 0:
        problems.append(f"codesign -d exited {shown.returncode}: the binary is not validly signed "
                        f"({(shown.stderr or b'').decode('utf-8', 'replace').strip()[-200:]})")
    else:
        match = CODE_DIRECTORY_FLAGS.search((shown.stdout + shown.stderr).decode("utf-8", "replace"))
        if match is None:
            problems.append("codesign -d printed no CodeDirectory flags")
        else:
            found["flags"] = match.group(1)
            found["hardened_runtime"] = bool(int(match.group(1), 16) & CS_RUNTIME)
            if not found["hardened_runtime"]:
                problems.append(f"the binary is not signed with the hardened runtime (flags {match.group(1)})")
    if listed.returncode != 0:
        problems.append(f"codesign -d --entitlements exited {listed.returncode}")
    else:
        import plistlib
        data = listed.stdout.strip()
        try:
            entitlements = plistlib.loads(data) if data else {}
            require(isinstance(entitlements, dict), "not a dictionary")
        except Exception as exc:   # noqa: BLE001 - an entitlement list that cannot be read is refused
            problems.append(f"the entitlements cannot be read ({type(exc).__name__}: {exc})")
        else:
            found["entitlements"] = sorted(entitlements)
            found["get_task_allow"] = entitlements.get(GET_TASK_ALLOW) is True
            if GET_TASK_ALLOW in entitlements:
                problems.append(f"the binary carries {GET_TASK_ALLOW}: any same-sandbox process could read the "
                                "host's memory")
    return {**found, "problems": problems}


# ---------------------------------------------------------------- approval (R9, WI-1)

def approval_digest(approval: dict) -> str:
    """The ledger key of an approval: the sha256 of its canonical JSON, so a reformatted copy of the same
    approval (other whitespace or key order, hence other file bytes) is the same approval. The campaign's
    authorization.reference_sha256 separately names the exact frozen bytes."""
    return canonical.digest(approval)


def _ledger_entries(data: bytes, label) -> list:
    """Every line of a ledger's bytes, strictly parsed and validated; a torn or foreign line fails closed."""
    require(not data or data.endswith(b"\n"), f"{label}: the last line is torn (no newline); a human must repair it")
    entries = []
    for number, raw in enumerate(data.split(b"\n")[:-1] if data else [], start=1):
        try:
            entry = canonical.strict_loads(raw.decode("utf-8"))
            contracts.validate_approval_ledger_entry(entry, f"{label} line {number}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ContractError(f"{label} line {number}: not a ledger entry ({exc})") from None
        entries.append(entry)
    return entries


def _open_ledger(path: Path, flags) -> int:
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and not info.st_mode & 0o077):
        os.close(fd)
        raise ContractError(f"{path}: the approval ledger must be a regular file of this user with one link and "
                            "mode 0600")
    return fd


def _lock(fd, kind, path, wait_s=None) -> None:
    """flock with a bounded wait: a ledger held longer (another build, or this process holding a claim, since
    two descriptors of one file conflict even within one process) is refused, never waited on forever."""
    deadline = time.monotonic() + (LEDGER_LOCK_S if wait_s is None else wait_s)
    while True:
        try:
            fcntl.flock(fd, kind | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise ContractError(f"{path}: the approval ledger is locked by another build") from None
            time.sleep(0.05)


def ledger_dir(directory=None) -> Path:
    """The directory of the approval ledger: ``directory`` when given (tests), else the per-user LEDGER_DIR."""
    return Path(os.path.expanduser(LEDGER_DIR if directory is None else os.fspath(directory)))


def _ledger_parent_problem(parent: Path):
    """None when the ledger directory's parent is a real directory of this user that no group or other user can write
    (0755 is fine: the ledger directory itself is 0700); else why. A writable parent would let another user rename the
    ledger directory away and put an empty one in its place."""
    try:
        info = os.lstat(parent)
    except OSError as exc:
        return f"the approval ledger's parent {parent} cannot be inspected ({exc.strerror}); it must exist"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        return (f"the approval ledger's parent {parent} must be a directory of this user without group or other "
                f"write bits (mode {stat.S_IMODE(info.st_mode):04o})")
    return None


def _ledger_dir_problem(directory: Path):
    """None when the ledger directory is a real directory of this user with no group or other bits, in a parent
    _ledger_parent_problem accepts; else why."""
    problem = _ledger_parent_problem(directory.parent)
    if problem is not None:
        return problem
    try:
        info = os.lstat(directory)
    except OSError as exc:
        return f"the approval ledger directory {directory} cannot be inspected ({exc.strerror})"
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        return (f"the approval ledger directory {directory} must be a directory of this user with mode 0700 "
                f"(mode {stat.S_IMODE(info.st_mode):04o})")
    return None


def read_approval_ledger(directory=None, *, wait_s=None) -> list:
    """The per-user approval ledger's entries ([] when it does not exist yet), read under a shared lock (refused
    after LEDGER_LOCK_S while a claim holds it, including a claim of this same process). ``directory``: the
    ledger's directory (default LEDGER_DIR, whatever the store: E-77)."""
    root = ledger_dir(directory)
    path = root / APPROVAL_LEDGER
    if not os.path.lexists(path):
        return []
    problem = _ledger_dir_problem(root)
    require(problem is None, problem)
    fd = _open_ledger(path, os.O_RDONLY)
    try:
        _lock(fd, fcntl.LOCK_SH, path, wait_s)
        with os.fdopen(os.dup(fd), "rb") as handle:
            return _ledger_entries(handle.read(), path)
    finally:
        os.close(fd)


@contextlib.contextmanager
def claim_approval(directory=None, *, approval_sha256, campaign_id, created_utc, wait_s=None):
    """Consume one approval for one campaign (R9): under an exclusive lock on the per-user ledger
    (``<LEDGER_DIR>/live-approvals.jsonl``, mode 0600 in a 0700 directory created here when absent, whose existing
    parent no group or other user may write: E-89), refuse an approval already listed (``approval_sha256`` is
    ``approval_digest(approval)``), append {approval_sha256, campaign_id, created_utc} and yield the entry while the
    lock is held (the builder renames its campaign into place there). If the body raises, the line is removed under
    the same lock (the file is cut back to its length before the append) and the exception propagates: a failed
    build consumes nothing."""
    entry = {"approval_sha256": approval_sha256, "campaign_id": campaign_id, "created_utc": created_utc}
    contracts.validate_approval_ledger_entry(entry, "approval ledger entry")
    root = ledger_dir(directory)
    if not os.path.lexists(root):
        problem = _ledger_parent_problem(root.parent)
        require(problem is None, problem)
        try:
            os.mkdir(root, LEDGER_DIR_MODE)
            os.chmod(root, LEDGER_DIR_MODE)   # the umask never widens it, but make the mode exact
        except FileExistsError:
            pass
    problem = _ledger_dir_problem(root)
    require(problem is None, problem)
    path = root / APPROVAL_LEDGER
    fd = _open_ledger(path, os.O_RDWR | os.O_CREAT)
    try:
        _lock(fd, fcntl.LOCK_EX, path, wait_s)
        size = os.fstat(fd).st_size
        data = os.pread(fd, size, 0) if size else b""
        used = {e["approval_sha256"]: e["campaign_id"] for e in _ledger_entries(data, path)}
        require(approval_sha256 not in used, f"the approval {approval_sha256} was already used by campaign "
                                             f"{used.get(approval_sha256)!r}: an approval is single-use")
        line = canonical.canonical_bytes(entry) + b"\n"
        written = os.pwrite(fd, line, size)
        require(written == len(line), "approval ledger: short write")
        os.fsync(fd)
        try:
            yield entry
        except BaseException:
            os.ftruncate(fd, size)
            os.fsync(fd)
            raise
    finally:
        os.close(fd)


def approval_problems(approval: dict, *, spec, host, budget, arms, ledger) -> list:
    """Why ``approval`` does not authorize this campaign ([] when it does). ``spec`` is the v1 spec (its task
    ids and seeds), ``host`` the pinned host fields (``HostPin.fields()`` or a mapping with adapter, version,
    executable_sha256, model and effort), ``budget`` the manifest budget, ``arms`` the campaign's arm names and
    ``ledger`` the store's ledger entries. The caps must equal the budget exactly (canonical bytes: 2.0 is not 2),
    runs and assignments must equal the roster (every task x seed in every arm), the scope must be the spec's, the
    host fields (effort included) the pin's, shared quota accepted, and the approval's sha256 unused."""
    try:
        contracts.validate_smoke_approval(approval)
    except ContractError as exc:
        return [str(exc)]
    problems = []
    for name in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap"):
        if name not in budget or canonical.canonical_bytes(approval["caps"][name]) != canonical.canonical_bytes(
                budget[name]):
            problems.append(f"caps.{name} {approval['caps'][name]!r} differs from the campaign budget's "
                            f"{budget.get(name)!r}")
    tasks = [t["id"] for t in spec["tasks"]]
    roster = len(tasks) * len(spec["seeds"]) * len(list(arms))
    scope = approval["scope"]
    for name, mine, theirs in (("tasks", scope["tasks"], tasks), ("seeds", scope["seeds"], spec["seeds"]),
                               ("arms", scope["arms"], list(arms))):
        if sorted(mine) != sorted(theirs):
            problems.append(f"scope.{name} {sorted(mine)} differs from the campaign's {sorted(theirs)}")
    if scope["assignments"] != roster or approval["caps"]["runs"] != roster:
        problems.append(f"scope.assignments/caps.runs {scope['assignments']}/{approval['caps']['runs']} differ from "
                        f"the {roster} assignments of the roster")
    for name in contracts.SMOKE_HOST_FIELDS:
        if scope["host"][name] != host.get(name):
            problems.append(f"scope.host.{name} {scope['host'][name]!r} differs from the pinned host's "
                            f"{host.get(name)!r}")
    if approval["account_preconditions"]["shared_quota_accepted"] is not True:
        problems.append("account_preconditions.shared_quota_accepted: the budget owner has not accepted runs "
                        "drawing on the shared subscription quota")
    expected = CREDENTIAL_ENV_NAMES.get(scope["host"]["adapter"], {})
    if approval["credential"]["env_name"] not in expected:
        problems.append(f"credential.env_name {approval['credential']['env_name']!r} is not the "
                        f"{scope['host']['adapter']} credential variable {sorted(expected)}")
    sha = approval_digest(approval)
    if any(e["approval_sha256"] == sha for e in ledger):
        problems.append(f"the approval (canonical sha256 {sha}) is already in the approval ledger: single-use")
    return problems


# ---------------------------------------------------------------- the launch declaration and the Claude binding

PROXY_ALLOW = ("api.anthropic.com:443",)     # the one upstream a live host reaches (R6); nothing refreshes a token
NO_PROXY = "127.0.0.1,localhost,::1"
CLAUDE_TOOLS = ("Bash", "Read", "Write", "Edit")                               # E-44: Glob, Grep not offered (E-51)
CLAUDE_DISALLOWED = ("WebSearch", "WebFetch", "Task", "Agent", "NotebookEdit")
# E-46 and smoke spec §1.3: the pins every live launch binds (paid paths off, background tasks and the advisor
# off, retries, the Bash timeouts, the rc-file neutralizers for the subject-writable HOME, the Bash tool's working
# directory reset to the workspace after every command (E-75: no host helper runs git where a subject cd'd to) and
# the 5-minute prompt-cache TTL (E-76: LC-16 prices cache writes at HP-13's one measured rate)).
CLAUDE_ENV_PINS = {"CLAUDE_CODE_DISABLE_FAST_MODE": "1", "CLAUDE_CODE_NO_MODEL_FALLBACK": "1",
                   "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                   "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1", "CLAUDE_CODE_MAX_RETRIES": "3",
                   "BASH_DEFAULT_TIMEOUT_MS": "120000", "BASH_MAX_TIMEOUT_MS": "300000", "ZDOTDIR": "/var/empty",
                   "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                   "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1", "FORCE_PROMPT_CACHING_5M": "1"}
CLAUDE_SETTINGS = {"max_turns": 100, "permission_mode": "dontAsk", "setting_sources": "project,local",
                   "subprocess_env_scrub": False, "shell": "/bin/zsh", "cert_store": "bundled"}
LIVE_FLAG = "RAVEL_EVAL_LIVE"


def _require_live(what):
    require(os.environ.get(LIVE_FLAG) == "1", f"{what}: refused without {LIVE_FLAG}=1 (a real host is involved)")


def app_bundle(executable):
    """The copied ``.app`` bundle holding a pinned executable (``<name>.app/Contents/MacOS/<binary>``), else None."""
    path = Path(executable)
    bundle = path.parent.parent.parent
    if path.parent.name == "MacOS" and path.parent.parent.name == "Contents" and bundle.suffix == ".app":
        return str(bundle)
    return None


def credential_env(adapter="claude_cli") -> tuple:
    """(env_name, expected apiKeySource) of the credential a real adapter declares."""
    [(name, source)] = CREDENTIAL_ENV_NAMES[adapter].items()
    return name, source


def default_host_launch(*, host_state_root, credential_file, pin, claude=None) -> dict:
    """The real host's launch declaration (``coordinator/config.json`` ``host_launch``, schema 2; smoke spec WI-1):
    the host-state root, the pinned binary's read access (one literal, or the copied ``.app`` as one root), the
    proxy allowlist (api.anthropic.com:443, leader-pid attribution), the credential's variable NAME and file, the
    Claude settings (``claude`` overrides single fields; its ``env_pins`` are merged over CLAUDE_ENV_PINS), the
    removed keychain mach services and the deny roots (the credential directory, ~/Library/Keychains,
    ~/.claude.json). Validated (contracts.validate_host_launch)."""
    require(isinstance(pin, HostPin), "pin: a HostPin is required")
    home = os.path.realpath(os.path.expanduser("~"))
    credential_file = os.path.normpath(os.fspath(credential_file))
    require(os.path.isabs(credential_file), "credential_file: an absolute path is required")
    settings = {**CLAUDE_SETTINGS, "effort": pin.effort, "tools": list(CLAUDE_TOOLS),
                "allowed_tools": list(CLAUDE_TOOLS), "disallowed_tools": list(CLAUDE_DISALLOWED),
                "env_pins": dict(CLAUDE_ENV_PINS)}
    overrides = dict(claude or {})
    unknown = sorted(set(overrides) - set(contracts.HOST_LAUNCH_CLAUDE_FIELDS))
    require(not unknown, f"claude: unknown settings {unknown}")
    pins = overrides.pop("env_pins", None)
    settings.update(overrides)
    if pins is not None:
        settings["env_pins"] = {**CLAUDE_ENV_PINS, **pins}
    require(settings["effort"] == pin.effort, "claude.effort: the pinned effort is the approval's (HostPin.effort)")
    app = app_bundle(pin.executable)
    name, source = credential_env(pin.adapter)
    record = {"schema_version": 2, "host_state_root": os.fspath(host_state_root),
              "binary_access": {"read_literals": [] if app else [pin.executable], "read_roots": [app] if app else []},
              "proxy": {"allow": list(PROXY_ALLOW), "no_proxy": NO_PROXY, "attribution": "leader_pid"},
              "credential": {"env_name": name, "file": credential_file, "expected_api_key_source": source},
              "claude": settings, "mach_services_removed": list(contracts.KEYCHAIN_MACH_SERVICES),
              "deny_roots": [os.path.dirname(credential_file), os.path.join(home, "Library", "Keychains"),
                             os.path.join(home, ".claude.json")]}
    contracts.validate_host_launch(record)
    return record


def claude_host_config(pin, *, environment_sha256, tools) -> dict:
    """The §4.2 host configuration of a pinned Claude Code CLI: the binary, version and model pinned, reasoning
    pinned through ``--effort`` (recorded as ``--effort <level>``), sampling unknown, the allowlist proxy, Seatbelt
    and host-reported cost."""
    host = {"schema_version": 1, "adapter": pin.adapter, "executable": pin.executable,
            "executable_sha256": pin.executable_sha256, "version": pin.version, "model": pin.model,
            "reasoning": f"--effort {pin.effort}", "sampling": None,
            "context_policy": "fresh workspace, HOME, config and temp directories and session per assignment",
            "memory_policy": "none (auto memory disabled, no session resumed)", "subagent_policy": "none",
            "tool_allowlist": list(tools), "network": "allowlist_proxy", "sandbox": "seatbelt",
            "environment_manifest_sha256": environment_sha256, "cost_source": "host_reported",
            "unknown_fields": ["sampling"]}
    contracts.validate_host_config(host)
    return host


def claude_adapter(host, host_launch, budget, state_dir, launcher) -> claude_cli.ClaudeCliAdapter:
    """The Claude CLI adapter of one assignment, from the frozen campaign alone (R20: the builder writes the
    binding from exactly this, with a placeholder state directory). ``state_dir`` holds its per-run config/ and
    tmp/; the spend ceiling is the campaign's usd_per_run; every live campaign is synthetic in this slice."""
    require(host["adapter"] == "claude_cli", f"claude_adapter: a claude_cli host required, got {host['adapter']!r}")
    c, state = host_launch["claude"], Path(state_dir)
    return claude_cli.ClaudeCliAdapter(
        host["executable"], host["version"], host["executable_sha256"], host["model"], c["max_turns"],
        budget["usd_per_run"], c["permission_mode"], c["setting_sources"], list(c["disallowed_tools"]),
        state / runner.HOST_STATE_SUBDIRS[0], tmp_dir=state / runner.HOST_STATE_SUBDIRS[1], shell=c["shell"],
        cert_store=c["cert_store"], effort=c["effort"], env_pins=dict(c["env_pins"]), expected_tools=list(c["tools"]),
        expected_api_key_source=host_launch["credential"]["expected_api_key_source"],
        allowed_tools=list(c["allowed_tools"]), tools=list(c["tools"]),
        subprocess_env_scrub=c["subprocess_env_scrub"], sandbox=host["sandbox"], synthetic=True, launcher=launcher)


def claude_factory(campaign):
    """The runtime adapter factory of a Claude CLI campaign: the bound adapter for the assignment's opaque host-state
    directory and recording launcher. The arm never reaches it (R0.5, E-25)."""
    def factory(assignment):
        return claude_adapter(campaign.host, campaign.config["host_launch"], campaign.budget,
                              Path(assignment["host_state_dir"]), assignment["launcher"])
    return factory


def build_live_campaign(store, *, campaign_id, created_utc, seeds, schedule_seed, subjects_root, host_state_root,
                        tasks, pin, credential_file, approval_bytes, budget, claude=None, source=None,
                        extra_forbidden_roots=()):
    """Freeze a synthetic engineering campaign with a real host (smoke spec WI-1) at
    ``<store>/synthetic/<campaign_id>/``. Requires RAVEL_EVAL_LIVE=1. ``approval_bytes`` is the budget owner's
    approval record (strict UTF-8 JSON, schema 2), frozen byte for byte as ``approval_record`` and named by the
    authorization's reference_sha256; it must match the campaign exactly (live.approval_problems) and is consumed
    once (the approval ledger). ``budget`` holds the manifest budget fields (defaults as for the fake host: global
    caps runs x per-run caps). The credential file is never opened. Every failure leaves nothing behind."""
    _require_live("build-live")
    require(isinstance(pin, HostPin), "pin: a HostPin is required")
    require(isinstance(approval_bytes, bytes) and approval_bytes, "approval: the approval record's bytes are required")
    try:
        approval = canonical.strict_loads(approval_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError(f"approval: not strict UTF-8 JSON ({exc})") from None
    contracts.validate_smoke_approval(approval)
    host_launch = default_host_launch(host_state_root=host_state_root, credential_file=credential_file, pin=pin,
                                      claude=claude)
    reference = canonical.sha256_bytes(approval_bytes)
    authorization = {"kind": "synthetic_engineering", "reference_sha256": reference,
                     "reference": (f"SYNTHETIC engineering smoke with a real host (not a pilot, no treatment effect): "
                                   f"the budget owner's single-use approval, frozen as {campaign_manifest.APPROVAL} "
                                   f"(canonical sha256 {approval_digest(approval)})")}
    return runner._build_campaign(
        store, campaign_id=campaign_id, created_utc=created_utc, seeds=seeds, schedule_seed=schedule_seed,
        subjects_root=subjects_root, tasks=tasks, sandbox="seatbelt", budget=budget,
        make_host=lambda python, environment_sha256, sandbox: claude_host_config(
            pin, environment_sha256=environment_sha256, tools=host_launch["claude"]["tools"]),
        authorization=authorization, approval_record=approval_bytes, host_launch=host_launch, source=source,
        extra_forbidden_roots=extra_forbidden_roots, pin=pin, approval=approval)


def load_host_launch(campaign_dir) -> dict:
    """The campaign's host_launch from coordinator/config.json (validated; a fake host's is refused)."""
    config = canonical.strict_load(Path(campaign_dir) / runner.COORDINATOR / "config.json")
    host_launch = config.get("host_launch") if isinstance(config, dict) else None
    require(host_launch is not None, "this campaign has no real host (host_launch is null)")
    contracts.validate_host_launch(host_launch)
    return host_launch


# ---------------------------------------------------------------- proxy attribution, keychain, denial log

PROC_PIDLISTFDS, PROC_PIDFDSOCKETINFO, PROX_FDTYPE_SOCKET = 1, 3, 2
SOCKINFO_IN, SOCKINFO_TCP = 1, 2
SOCKET_INFO_BUFFER = 4096


class _FdInfo(ctypes.Structure):          # <sys/proc_info.h> struct proc_fdinfo
    _fields_ = [("proc_fd", ctypes.c_int32), ("proc_fdtype", ctypes.c_uint32)]


class _FileInfo(ctypes.Structure):        # struct proc_fileinfo
    _fields_ = [("fi_openflags", ctypes.c_uint32), ("fi_status", ctypes.c_uint32), ("fi_offset", ctypes.c_int64),
                ("fi_type", ctypes.c_int32), ("fi_guardflags", ctypes.c_uint32)]


class _VinfoStat(ctypes.Structure):       # struct vinfo_stat
    _fields_ = [("vst_dev", ctypes.c_uint32), ("vst_mode", ctypes.c_uint16), ("vst_nlink", ctypes.c_uint16),
                ("vst_ino", ctypes.c_uint64), ("vst_uid", ctypes.c_uint32), ("vst_gid", ctypes.c_uint32),
                ("vst_atime", ctypes.c_int64), ("vst_atimensec", ctypes.c_int64), ("vst_mtime", ctypes.c_int64),
                ("vst_mtimensec", ctypes.c_int64), ("vst_ctime", ctypes.c_int64), ("vst_ctimensec", ctypes.c_int64),
                ("vst_birthtime", ctypes.c_int64), ("vst_birthtimensec", ctypes.c_int64),
                ("vst_size", ctypes.c_int64), ("vst_blocks", ctypes.c_int64), ("vst_blksize", ctypes.c_int32),
                ("vst_flags", ctypes.c_uint32), ("vst_gen", ctypes.c_uint32), ("vst_rdev", ctypes.c_uint32),
                ("vst_qspare", ctypes.c_int64 * 2)]


class _SockbufInfo(ctypes.Structure):     # struct sockbuf_info
    _fields_ = [("sbi_cc", ctypes.c_uint32), ("sbi_hiwat", ctypes.c_uint32), ("sbi_mbcnt", ctypes.c_uint32),
                ("sbi_mbmax", ctypes.c_uint32), ("sbi_lowat", ctypes.c_uint32), ("sbi_flags", ctypes.c_short),
                ("sbi_timeo", ctypes.c_short)]


class _InSockinfoHead(ctypes.Structure):  # the leading fields of struct in_sockinfo (ports in network order)
    _fields_ = [("insi_fport", ctypes.c_int), ("insi_lport", ctypes.c_int), ("insi_gencnt", ctypes.c_uint64),
                ("insi_flags", ctypes.c_uint32), ("insi_flow", ctypes.c_uint32), ("insi_vflag", ctypes.c_uint8),
                ("insi_ip_ttl", ctypes.c_uint8), ("rfu_1", ctypes.c_uint32)]


class _SocketInfoHead(ctypes.Structure):  # struct socket_info up to the start of soi_proto
    _fields_ = [("soi_stat", _VinfoStat), ("soi_so", ctypes.c_uint64), ("soi_pcb", ctypes.c_uint64),
                ("soi_type", ctypes.c_int), ("soi_protocol", ctypes.c_int), ("soi_family", ctypes.c_int),
                ("soi_options", ctypes.c_short), ("soi_linger", ctypes.c_short), ("soi_state", ctypes.c_short),
                ("soi_qlen", ctypes.c_short), ("soi_incqlen", ctypes.c_short), ("soi_qlimit", ctypes.c_short),
                ("soi_timeo", ctypes.c_short), ("soi_error", ctypes.c_ushort), ("soi_oobmark", ctypes.c_uint32),
                ("soi_rcv", _SockbufInfo), ("soi_snd", _SockbufInfo), ("soi_kind", ctypes.c_int),
                ("rfu_1", ctypes.c_uint32), ("soi_proto", _InSockinfoHead)]


class _SocketFdInfoHead(ctypes.Structure):   # struct socket_fdinfo, verified 2026-09-26 on macOS 15.5 (792 bytes)
    _fields_ = [("pfi", _FileInfo), ("psi", _SocketInfoHead)]


@functools.lru_cache(maxsize=None)
def _libproc():
    lib = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    lib.proc_pidinfo.restype = ctypes.c_int
    lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    lib.proc_pidfdinfo.restype = ctypes.c_int
    lib.proc_pidfdinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    return lib


def _socket_fds(pid):
    """The socket descriptors of ``pid`` (PROC_PIDLISTFDS), or None when they cannot be listed."""
    lib = _libproc()
    size = lib.proc_pidinfo(pid, PROC_PIDLISTFDS, 0, None, 0)
    if size <= 0:
        return None
    buffer = (_FdInfo * (size // ctypes.sizeof(_FdInfo) + 32))()
    got = lib.proc_pidinfo(pid, PROC_PIDLISTFDS, 0, ctypes.byref(buffer), ctypes.sizeof(buffer))
    if got <= 0:
        return None
    return [e.proc_fd for e in buffer[:got // ctypes.sizeof(_FdInfo)] if e.proc_fdtype == PROX_FDTYPE_SOCKET]


def _tcp_ports(pid, fd):
    """(local port, remote port) of a TCP socket descriptor of ``pid``, or None (not TCP, gone, unreadable)."""
    buffer = ctypes.create_string_buffer(SOCKET_INFO_BUFFER)
    got = _libproc().proc_pidfdinfo(pid, fd, PROC_PIDFDSOCKETINFO, buffer, SOCKET_INFO_BUFFER)
    if got < ctypes.sizeof(_SocketFdInfoHead):
        return None
    head = _SocketFdInfoHead.from_buffer_copy(buffer.raw[:ctypes.sizeof(_SocketFdInfoHead)])
    if head.psi.soi_family not in (socket.AF_INET, socket.AF_INET6) or \
            head.psi.soi_kind not in (SOCKINFO_IN, SOCKINFO_TCP):
        return None
    proto = head.psi.soi_proto
    return socket.ntohs(proto.insi_lport & 0xFFFF), socket.ntohs(proto.insi_fport & 0xFFFF)


def socket_owned_by(pid, local_port, remote_port):
    """Whether process ``pid`` holds the TCP socket from ``local_port`` to ``remote_port`` (the proxy's client
    connection seen from the client's side: R6). True: it does; False: it holds no such socket (another process
    connected); None: the lookup failed (no pid yet, the process is gone or not inspectable, not macOS), which the
    proxy treats as a denial (owner_unknown, fail closed). Reads only (proc_pidinfo, proc_pidfdinfo)."""
    if type(pid) is not int or pid <= 1 or sys.platform != "darwin":
        return None
    try:
        fds = _socket_fds(pid)
        if fds is None:
            return None
        return any(_tcp_ports(pid, fd) == (local_port, remote_port) for fd in fds)
    except (OSError, AttributeError, ValueError):
        return None


SECURITY = "/usr/bin/security"
SECURITY_COMMAND = (SECURITY,)                 # the argv prefix of every security query (tests: a synthetic one)
KEYCHAIN_SERVICE = "Claude Code-credentials"   # F7: suffixed with -<sha256(config dir)[:8]> for a set config dir
KEYCHAIN_NOT_FOUND = 44                        # security find-generic-password: the item could not be found
KEYCHAIN_LOCKED_OR_OK = (0, 36)                # show-keychain-info: shown, or the keychain is locked (reachable)
NOT_RUN = (126, 127)                           # the shell's "cannot execute" and "not found": no evidence either way


def keychain_service(config_dir) -> str:
    """The keychain service name the CLI uses for a CLAUDE_CONFIG_DIR (F7)."""
    return f"{KEYCHAIN_SERVICE}-{hashlib.sha256(os.fspath(config_dir).encode()).hexdigest()[:8]}"


def login_keychain() -> str:
    """The resolved path of the user's login keychain file (HP-06 names it; nothing reads its content)."""
    return os.path.realpath(os.path.join(os.path.realpath(os.path.expanduser("~")), "Library", "Keychains",
                                         "login.keychain-db"))


def _security(*args, env=None, cwd=None, timeout_s=30):
    """Exit code of one unsandboxed ``security`` query (never an item change: find and show only), None when it
    cannot run. Output is discarded unread. ``env`` defaults to the user's HOME, so the default keychain search list
    applies (LC-21); HP-06 passes the probe's own environment for its control."""
    env = {"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~")} if env is None else dict(env)
    try:
        return subprocess.run([*SECURITY_COMMAND, *args], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_s,
                              close_fds=True).returncode
    except (OSError, subprocess.SubprocessError):
        return None


def keychain_residue(config_dir) -> dict:
    """LC-21, outside the sandbox: whether a keychain item named for the run's config dir exists, for the path as
    passed and its realpath. ``persisted`` is True unless every lookup answered "not found" (exit 44): an item, or
    a lookup that could not decide, is credential_persisted_keychain (S2). Nothing is ever added or deleted."""
    checked = []
    for path in dict.fromkeys([os.fspath(config_dir), os.path.realpath(config_dir)]):
        service = keychain_service(path)
        checked.append({"config_dir": path, "service": service,
                        "exit": _security("find-generic-password", "-s", service)})
    return {"checked": checked, "persisted": any(c["exit"] != KEYCHAIN_NOT_FOUND for c in checked)}


LOG = "/usr/bin/log"
DENIAL_WALL_S = 60.0          # the collector's wall bound (WI-7b)
DENIAL_OUTPUT_CAP = 8 << 20
SUBJECT_MARKER = "ravel-subject"   # the message of the subject profile's deny-default rule (isolation.seatbelt_profile)
# Every clause needs the Sandbox kext as the sender: the log tool records its own invocation with its arguments
# ("log run noninteractively ... args: ... --predicate ..."), so a clause on the marker alone matched the collector
# itself (the smoke's LC-18, E-162).
DENIAL_PREDICATE = (f'sender == "Sandbox" AND (eventMessage CONTAINS "deny" '
                    f'OR eventMessage CONTAINS "{SUBJECT_MARKER}")')
PID_DENIAL_PREDICATE = 'sender == "Sandbox" AND eventMessage CONTAINS "deny" AND eventMessage CONTAINS "({pid})"'
_SANDBOX_REPORT = re.compile(r"Sandbox: (.+?)\((\d+)\) deny\(")
DENIAL_PROCESS_NAMES_CAP = 32


def _local_time(utc):
    return datetime.fromisoformat(utc.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def denial_reports(data, *, pid=None) -> list:
    """The Seatbelt reports among ``log show --style ndjson`` lines, restating the predicate on the parsed fields:
    a JSON object whose sender image is the Sandbox kext (``.../Sandbox``), whose process and sender images are not
    the log tool (any image named ``log``), and whose message is a deny report or carries the subject marker; with
    ``pid``, a deny report naming that process id. Returns the reporting process's name for each (None when the
    message does not parse). The log tool's own record of its invocation (subsystem com.apple.log) quotes the
    predicate, so it is never a denial whatever it contains (E-162). Trailers, partial and unparsable lines are
    skipped."""
    found = []
    for line in data.splitlines():
        line = line.strip()
        if not line.startswith(b"{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        message = event.get("eventMessage") if isinstance(event, dict) else None
        if not isinstance(message, str):
            continue
        images = [event.get("processImagePath"), event.get("senderImagePath")]
        if not all(isinstance(image, str) for image in images) or os.path.basename(images[1]) != "Sandbox" \
                or any(image == LOG or os.path.basename(image) == "log" for image in images):
            continue
        report = _SANDBOX_REPORT.search(message)
        if pid is not None:
            if report is None or int(report.group(2)) != pid:
                continue
        elif "deny" not in message and SUBJECT_MARKER not in message:
            continue
        found.append(report.group(1) if report else None)
    return found


def sandbox_denials(start_utc, end_utc, *, pid=None, timeout_s=DENIAL_WALL_S, max_bytes=DENIAL_OUTPUT_CAP) -> dict:
    """Seatbelt denials in the unified log over one window (``log show --style ndjson``), bounded by ``timeout_s``
    and ``max_bytes``: {available, count, truncated, error, processes}. Only Seatbelt's own reports count
    (``denial_reports``), never the log tool's record of this very call (E-162); ``processes`` counts them by the
    reporting process's name (no path; at most DENIAL_PROCESS_NAMES_CAP names). Without ``pid`` the count is
    machine-wide: any process's denial in the window counts, a system daemon's included. With ``pid`` only the
    denials Seatbelt reports for that process ("<name>(<pid>) deny(...)") are counted (HP-11). Best effort (F14):
    an unavailable or blind collector is recorded (sandbox_denials_unavailable), never a stop; HP-11 found no
    report for a sandboxed process's denied read on the smoke's host, so the breach evidence is the canary scan,
    the proxy log and the credential checks (E-49)."""
    require(pid is None or (type(pid) is int and pid > 1), "sandbox_denials: pid must be a process id or None")
    predicate = DENIAL_PREDICATE if pid is None else PID_DENIAL_PREDICATE.format(pid=pid)
    argv = [LOG, "show", "--style", "ndjson", "--start", _local_time(start_utc), "--end", _local_time(end_utc),
            "--predicate", predicate]
    try:
        done = subprocess.run(argv, env={"PATH": "/usr/bin:/bin"}, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout_s, close_fds=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "count": None, "truncated": False, "error": f"{type(exc).__name__}: {exc}"}
    if done.returncode != 0:
        return {"available": False, "count": None, "truncated": False,
                "error": f"log show exited {done.returncode}: {done.stderr[-200:].decode(errors='replace')}"}
    reports = denial_reports(done.stdout[:max_bytes], pid=pid)
    names = {}
    for name in reports:
        name = name if name is not None else "(unparsed)"
        if name in names or len(names) < DENIAL_PROCESS_NAMES_CAP:
            names[name] = names.get(name, 0) + 1
    return {"available": True, "count": len(reports), "truncated": len(done.stdout) > max_bytes, "error": None,
            "processes": dict(sorted(names.items()))}


def user_sysv_objects() -> list:
    """The System V IPC objects this user created or owns (preflight check 13, R12a): [{kind, id, key}]."""
    names = isolation._user_names()
    return [{"kind": isolation.IPC_KIND_NAMES[kind], "id": ident, "key": row["KEY"]}
            for (kind, ident), row in sorted(isolation._sysv_objects().items())
            if row["CREATOR"] in names or row["OWNER"] in names]


# ---------------------------------------------------------------- credential validation and preflight

def validate_credential(campaign_dir) -> None:
    """The run-start credential validation (R8): the declared file is read through credentials.read_credential and
    the value discarded at once. A failure is runner.CredentialPause (a pause: nothing journaled, no stop), with
    the generic message only."""
    host_launch = load_host_launch(campaign_dir)
    try:
        credentials.read_credential(host_launch["credential"]["file"])   # the value is never bound
    except credentials.CredentialError as exc:
        raise runner.CredentialPause(f"paused: the host credential cannot be used ({exc}); fix the file (smoke "
                                     "spec S8) and run the same command again") from None


PREFLIGHT_IDS = {"live_flag": "PF-01", "coordinator_env": "PF-02", "credential_file": "PF-03", "pinned_host": "PF-04",
                 "behavioral_gate": "PF-05", "host_probe": "PF-06", "no_stop": "PF-07", "proxy_allowlist": "PF-08",
                 "host_state_root": "PF-09", "budget": "PF-10", "sandbox": "PF-11", "core_limit": "PF-12",
                 "sysv_ipc": "PF-13", "go_no_go": "PF-14"}


def preflight(campaign_dir, *, campaign=None) -> dict:
    """{"ok", "checks": [{id, name, ok, detail}]}: every condition for a paid launch (smoke spec WI-2), each checked
    and reported whatever the others show. Stat-only for the credential (never opened). ``campaign``: an already
    loaded runner._Campaign (run_campaign passes its own)."""
    checks = []

    def check(name, fn):
        try:
            ok, detail = fn()
        except Exception as exc:   # noqa: BLE001 - a check that cannot run fails, with its reason
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        checks.append({"id": PREFLIGHT_IDS[name], "name": name, "ok": bool(ok), "detail": detail})

    check("live_flag", lambda: (os.environ.get(LIVE_FLAG) == "1", f"{LIVE_FLAG}={os.environ.get(LIVE_FLAG)!r}"))
    if campaign is None:
        try:
            campaign = runner._Campaign(campaign_dir)
        except Exception as exc:   # noqa: BLE001
            checks.append({"id": "PF-00", "name": "campaign", "ok": False, "detail": f"{type(exc).__name__}: {exc}"})
            return {"ok": False, "checks": checks}
    require(campaign.real, "preflight: this campaign has no real host")
    host_launch, name = campaign.host_launch, campaign.host_launch["credential"]["env_name"]

    def coordinator_env():
        found = never_present(os.environ) + ([name] if name in os.environ else [])
        return not found, {"never_present_names": found}
    check("coordinator_env", coordinator_env)

    def credential_file():
        found = credentials.check_credential_file(host_launch["credential"]["file"])
        return found["ok"], found
    check("credential_file", credential_file)

    def pinned_host():
        adapter = claude_adapter(campaign.host, host_launch, campaign.budget,
                                 campaign.host_state_dir_for(None), launcher=None)
        identity = adapter.preflight()
        signature = code_signature(campaign.host["executable"])
        return not signature["problems"], {"version": identity["version"], "sha256": identity["sha256"],
                                           "hardened_runtime": signature["hardened_runtime"],
                                           "get_task_allow": signature["get_task_allow"],
                                           "problems": signature["problems"]}
    check("pinned_host", pinned_host)

    def behavioral():
        problem, sha = runner.behavioral_record(campaign.dir, campaign.campaign_sha256, campaign.manifest["arms"])
        return problem is None, problem or {"record_sha256": sha}
    check("behavioral_gate", behavioral)

    def probe():
        problem = host_probe_problem(campaign.dir, host_launch["credential"]["file"])
        return problem is None, problem or "the latest host-probe record passes HP-06, HP-09 and HP-13 and prices the pin"
    check("host_probe", probe)

    def no_stop():
        stop = runner.read_stop(campaign.dir)
        if stop is not None:
            return False, {"stop": stop}
        pending = [t for t in derive_stops(campaign.dir, write=False) if t["stop"] is not None]
        return not pending, pending or "no coordinator/stop.json and no sealed run whose re-derived stop rules fire"
    check("no_stop", no_stop)
    check("proxy_allowlist", lambda: (bool(allowlist_proxy.parse_allow(host_launch["proxy"]["allow"])),
                                      host_launch["proxy"]["allow"]))

    def state_root():
        problems = [p for p in (runner.host_root_problem(campaign.host_state_root),
                                runner.host_root_problem(campaign.subjects_root)) if p]
        return not problems, problems or "both roots are private directories of this user"
    check("host_state_root", state_root)

    def budget():
        (usd, seconds), b = campaign.spent_exact(), campaign.budget
        remaining = {"usd": float(runner.exact(b["global_usd_cap"]) - usd),
                     "seconds": float(runner.exact(b["global_seconds_cap"]) - seconds)}
        return remaining["usd"] >= b["usd_per_run"] and remaining["seconds"] >= b["seconds_per_run"], remaining
    check("budget", budget)
    check("sandbox", lambda: (isolation.sandbox_available() and isolation.census_available(),
                              "sandbox-exec and its census"))
    check("core_limit", lambda: (runner.core_limit_problem() is None, runner.core_limit_problem() or "hard limit 0"))

    def ipc():
        found = user_sysv_objects()
        return not found, found or "none of this user's"
    check("sysv_ipc", ipc)

    def go_no_go():
        problem = go_no_go_problem(campaign.dir)
        return problem is None, problem or "no run launched yet, or run 1's recorded go (S10a)"
    check("go_no_go", go_no_go)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# ---------------------------------------------------------------- host probes (WI-7c)

HOST_PROBE_DIR = "host_probe"                 # coordinator/host_probe/<n>/: result.json and one directory per launch
PROBE_TIMEOUT_S = 60.0
DRY_START_TIMEOUT_S = 120.0
REHEARSAL_SESSION_TIMEOUT_S = 240.0
REQUIRED_PROBES = ("HP-01", "HP-02", "HP-03", "HP-04", "HP-05", "HP-06", "HP-07", "HP-08")
GATE_PROBES = ("HP-06", "HP-09", "HP-13")      # the latest record must hold these, passing, before any paid launch
DUMMY_PREFIX = "sk-ant-oat01-SYNTHETIC-"
PROBE_READ_CAP = 1 << 20
DEAD_PORT = 1                                  # a profile needs one localhost port; nothing listens on 1
HOOK_OUTPUT = "probe-hook-env-names.txt"
HOOK_CODE = "import os,sys; sys.stdout.write(chr(10).join(sorted(os.environ)))"
CREDENTIAL_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR")

WRITE_PROBE = r'''
import json, sys
out = {}
for key, path in json.loads(sys.argv[1]).items():
    try:
        with open(path, "w") as handle:
            handle.write("SYNTHETIC host probe")
        out[key] = "ok"
    except OSError as exc:
        out[key] = f"{exc.__class__.__name__}:{exc.errno}"
print(json.dumps(out))
'''
TERMINAL_PROBE = r'''
import json, pty, sys
out = {}
try:
    open("/dev/tty").close()
    out["dev_tty"] = "opened"
except OSError as exc:
    out["dev_tty"] = f"{exc.__class__.__name__}:{exc.errno}"
try:
    pty.openpty()
    out["openpty"] = "opened"
except OSError as exc:
    out["openpty"] = f"{exc.__class__.__name__}:{exc.errno}"
out["stdin_isatty"] = sys.stdin.isatty()
print(json.dumps(out))
'''
STAT_PROBE = r'''
import json, os, sys
out = {}
for key, path in json.loads(sys.argv[1]).items():
    try:
        os.stat(path)
        out[key] = "stat"
    except OSError as exc:
        out[key] = f"{exc.__class__.__name__}:{exc.errno}"
print(json.dumps(out))
'''
READ_PROBE = r'''
import json, sys
path = json.loads(sys.argv[1])["path"]
try:
    open(path, "rb").close()
    print(json.dumps({"read": "opened"}))
except OSError as exc:
    print(json.dumps({"read": f"{exc.__class__.__name__}:{exc.errno}"}))
'''
PROXY_PROBE = r'''
import json, socket, subprocess, sys
a = json.loads(sys.argv[1])

def connect(target, payload=b""):
    try:
        sock = socket.create_connection(("127.0.0.1", a["proxy"]), timeout=10)
    except OSError as exc:
        return f"{exc.__class__.__name__}:{exc.errno}", ""
    with sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        status = sock.recv(128).split(b"\r\n")[0].decode(errors="replace")
        echoed = b""
        if " 200 " in status + " " and payload:
            sock.sendall(payload)
            echoed = sock.recv(128)
    return status, echoed.decode(errors="replace")

if a.get("child"):
    print(connect(a["echo_target"])[0])
    sys.exit(0)
out = {"leader": connect(a["echo_target"], b"ravel-probe-ping")}
child = subprocess.run([sys.executable, "-I", "-c", a["script"], json.dumps({**a, "child": True})],
                       capture_output=True, text=True, timeout=30)
out["child"] = child.stdout.strip()
out["not_allowlisted"] = connect("api.example.invalid:443")[0]
try:
    socket.create_connection(("127.0.0.1", a["echo"]), timeout=5).close()
    out["direct"] = "connected"
except OSError as exc:
    out["direct"] = f"{exc.__class__.__name__}:{exc.errno}"
try:
    socket.create_connection(("::1", a["proxy"]), timeout=5).close()
    out["v6"] = "connected"
except OSError as exc:
    out["v6"] = f"{exc.__class__.__name__}:{exc.errno}"
try:
    socket.getaddrinfo("example.com", 443)
    out["dns"] = "resolved"
except OSError as exc:
    out["dns"] = exc.__class__.__name__
print(json.dumps(out))
'''
MULTIPROCESSING_PROBE = r'''
import json
try:
    import multiprocessing
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    child = ctx.Process(target=queue.put, args=(42,))
    child.start()
    child.join(10)
    print(json.dumps({"result": queue.get(timeout=5)}))
except Exception as exc:
    print(json.dumps({"error": f"{exc.__class__.__name__}: {str(exc)[:200]}"}))
'''
EPERM = "PermissionError:1"


def dummy_token() -> str:
    """A DUMMY credential for the probes (never the declared file's)."""
    return DUMMY_PREFIX + secrets.token_hex(16)


def _probe_parent(campaign_dir) -> Path:
    return Path(campaign_dir) / runner.COORDINATOR / HOST_PROBE_DIR


def latest_host_probe(campaign_dir) -> tuple:
    """(n, record) of the latest host-probe run (largest n); (None, None) without one; record None when that
    run has no readable result.json (a probe run that died)."""
    numbered = runner._numbered(_probe_parent(campaign_dir))
    if not numbered:
        return None, None
    n, root = numbered[-1]
    try:
        record = canonical.strict_load(root / "result.json")
        require(isinstance(record, dict) and isinstance(record.get("probes"), list), "not a host-probe record")
    except (ContractError, OSError, ValueError):
        record = None
    return n, record


def host_probe_problem(campaign_dir, credential_file=None):
    """None when the latest host-probe record (largest n) is ok, holds every required probe and HP-06, HP-09 and
    HP-13 passing, HP-13 shows the pin prices the pinned model with its own entry (R1, R2, R5) and, once the
    credential file exists (``credential_file``: the campaign's, lstat only), HP-07 saw it present and denied (a
    probe run before the token was minted is superseded: smoke-request S8b); else why."""
    n, record = latest_host_probe(campaign_dir)
    if n is None:
        return "no host probe was recorded (cli.py host-probe --campaign C --dry-start --rehearse)"
    label = f"coordinator/{HOST_PROBE_DIR}/{n}"
    if record is None:
        return f"the latest host probe ({label}) has no readable result.json"
    probes = {p.get("id"): p for p in record["probes"] if isinstance(p, dict)}
    missing = [i for i in (*REQUIRED_PROBES, *GATE_PROBES) if i not in probes]
    failed = sorted(i for i, p in probes.items() if p.get("required") and p.get("ok") is not True)
    unclean = record.get("unclean_launches")
    if not isinstance(unclean, list) or unclean:   # E-96: a record without the field predates the check
        return (f"the latest host probe ({label}) has probe launches whose census is unclean or unrecorded "
                f"({unclean!r}): {PROBE_CENSUS_REMEDY}")
    if record.get("ok") is not True or missing or failed:
        return f"the latest host probe ({label}) is not a passing gate: missing {missing}, failed {failed}"
    if not isinstance(probes["HP-13"].get("detail"), dict) or probes["HP-13"]["detail"].get("pricing_eligible") \
            is not True:
        return f"the latest host probe ({label}): HP-13 does not show the pin pricing its model with its own entry"
    if credential_file is not None and credentials.check_credential_file(credential_file)["present"]:
        hp07 = probes["HP-07"].get("detail") if isinstance(probes["HP-07"].get("detail"), dict) else {}
        if hp07.get("file_present") is not True:
            return (f"the latest host probe ({label}) ran before the credential file existed, so HP-07 could not "
                    "show a sandboxed stat of it denied: run host-probe again now that it is minted "
                    "(smoke-request S8b)")
    return None


RECENSUS = "recensus-{k}.json"   # coordinator/host_probe/<n>/<launch>/: a later census of an unclean probe launch
PROBE_CENSUS_REMEDY = ("a probe launch's census left survivors or could not search: every host-probe and run "
                       "censuses it again by its record (coordinator/host_probe/<n>/<launch>/process_started.json, "
                       "through isolation.census_launch) until it is clean; a human finds what is left through that "
                       "record, never by name or pattern (E-68, E-96)")


def census_unclean(census) -> bool:
    """Whether a probe launch's census (a lost launch's, a later one's, or a completed launch's close) is incomplete or
    left survivors: its processes may still run, so no probe record and no run may pass over it (E-96)."""
    if not isinstance(census, dict):
        return True
    complete = census.get("complete", census.get("census_complete"))
    return complete is not True or bool(census.get("survivors"))


def _probe_census(started) -> dict:
    try:
        return isolation.census_launch(canonical.strict_load(started))
    except (ContractError, OSError, ValueError) as exc:
        return {"complete": False, "note": f"the recorded start cannot be censused: {exc}"}


def _last_census(launch: Path):
    """The latest census on record for one probe launch: its latest recensus, else a lost close's census, else a
    completed close (survivors and census_complete); None without a close."""
    later = sorted((int(p.stem.split("-")[1]), p) for p in launch.glob("recensus-*.json")
                   if p.stem.split("-")[1].isdigit())
    if later:
        record = canonical.strict_load(later[-1][1])
        return record.get("census") if isinstance(record, dict) else None
    closed = launch / "closed.json"
    if not os.path.lexists(closed):
        return None
    record = canonical.strict_load(closed)
    if not isinstance(record, dict):
        return {"complete": False, "note": "closed.json is not a record"}
    if record.get("lost"):
        return record.get("census")
    if "error" in record and "survivors" not in record:   # nothing started (closed before a start was recorded)
        return {"complete": True, "survivors": []}
    return {"complete": record.get("census_complete"), "survivors": record.get("survivors")}


def census_lost_probes(campaign_dir) -> list:
    """Before any new probe or run (R12c, E-96): every probe launch whose start is recorded without a closing record
    is censused by exactly that record (isolation.census_launch, which signals only processes proven to belong to that
    launch) and closed; every probe launch whose latest census is unclean (census_unclean: a lost launch's census, or a
    completed launch that left survivors or lost its census) is censused again by its record, and the result written
    as recensus-<k>.json. Returns what was censused: [{launch, census, recensus?}]; census_problems says which remain
    unclean."""
    found = []
    for n, root in runner._numbered(_probe_parent(campaign_dir)):
        for launch in sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink()):
            started, closed = launch / "process_started.json", launch / "closed.json"
            if not started.is_file():
                continue
            if not os.path.lexists(closed):
                census = _probe_census(started)
                canonical.write_once(closed, runner._pretty({"lost": True, "census": census}))
                found.append({"launch": f"{n}/{launch.name}", "census": census})
                continue
            try:
                unclean = census_unclean(_last_census(launch))
            except (ContractError, OSError, ValueError):
                unclean = True
            if not unclean:
                continue
            k = 1 + max([int(p.stem.split("-")[1]) for p in launch.glob("recensus-*.json")
                         if p.stem.split("-")[1].isdigit()] or [0])
            census = _probe_census(started)
            canonical.write_once(launch / RECENSUS.format(k=k), runner._pretty({"census": census}))
            found.append({"launch": f"{n}/{launch.name}", "census": census, "recensus": k})
    return found


def census_problems(found) -> list:
    """The probe launches whose census in ``found`` (census_lost_probes) is still unclean: [launch]."""
    return [f["launch"] for f in found if census_unclean(f["census"])]


def _capped(path) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(PROBE_READ_CAP)
    except OSError:
        return b""


def _last_json(data: bytes):
    for line in reversed(data.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


class _EchoServer:
    """A TCP echo on 127.0.0.1 for HP-08 (a thread of this process, stopped by handle)."""

    def __init__(self):
        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(10)
                try:
                    data = self.request.recv(4096)
                    if data:
                        self.request.sendall(data)
                except OSError:
                    pass

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            allow_reuse_address = True

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05},
                                       name="ravel-probe-echo", daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)


class _ProbeRun:
    """One host-probe invocation: its record directory (coordinator/host_probe/<n>/), fresh probe workspaces under
    the subjects root and probe state under the host-state root (``probe-<n>-<hex>``), and its launches, each
    through isolation.launch under the real-host profile with its start and close recorded (R12c)."""

    def __init__(self, campaign, n):
        self.campaign, self.n = campaign, n
        self.record_dir = _probe_parent(campaign.dir) / str(n)
        self.record_dir.mkdir(mode=0o700)
        tag = f"probe-{n}-{secrets.token_hex(4)}"
        self.subjects, self.states = campaign.subjects_root / tag, campaign.host_state_root / tag
        for root in (self.subjects, self.states):
            os.mkdir(root, 0o700)
        self.python = campaign.config["subject_python"]
        self.executable = campaign.host["executable"]
        self.credential_name = campaign.host_launch["credential"]["env_name"]

    def workspace(self, label) -> Path:
        ws = self.subjects / label
        isolation.materialize({"request.md": b"SYNTHETIC host probe workspace. Not a task.\n",
                               "tools.md": self.campaign.tool_guide, "bin/ravel-task": self.campaign.client,
                               "output/": b"", "tmp/": b"", "home/": b""}, ws)
        return ws

    def state(self, label, *, make=True) -> Path:
        state = self.states / label
        os.mkdir(state, 0o700)
        if make:
            for name in runner.HOST_STATE_SUBDIRS:
                os.mkdir(state / name, 0o700)
        return state

    def adapter(self, state, *, host=None, host_launch=None, launcher=None):
        return claude_adapter(host or self.campaign.host, host_launch or self.campaign.host_launch,
                              self.campaign.budget, state, launcher)

    def env(self, ws, *, proxy=None, task_endpoint="http://127.0.0.1:9/op", task_token=None, extra=None) -> dict:
        extra = {"RAVEL_TASK_ENDPOINT": task_endpoint, "RAVEL_TASK_TOKEN": task_token or f"probe-{secrets.token_hex(8)}",
                 **(extra or {})}
        if proxy is not None:
            url, no_proxy = f"http://127.0.0.1:{proxy.port}", self.campaign.host_launch["proxy"]["no_proxy"]
            extra.update({"HTTPS_PROXY": url, "https_proxy": url, "NO_PROXY": no_proxy, "no_proxy": no_proxy})
        return isolation.subject_env(workspace=ws, home=ws / "home",
                                     path_dirs=[os.path.dirname(self.python), "/usr/bin", "/bin", str(ws / "bin")],
                                     extra=extra)

    def host_env(self, ws, state, **kw) -> dict:
        """The subject environment plus what the bound adapter adds (its isolation env and per-run directories)."""
        return {**self.env(ws, **kw), **self.adapter(state).isolation_env(),
                "CLAUDE_CONFIG_DIR": str(state / runner.HOST_STATE_SUBDIRS[0]),
                "CLAUDE_CODE_TMPDIR": str(state / runner.HOST_STATE_SUBDIRS[1])}

    def profile(self, ws, ports, state) -> str:
        return self.campaign._profile(ws, list(ports), host_state_dir=state)

    def fake_profile(self, ws) -> str:
        """The fake host's profile for this workspace (no host access, the keychain services not removed): HP-06
        records the same query under it, to show what the real-host profile's removals change."""
        return isolation.seatbelt_profile(runner.launch_policy(
            workspace=ws, subject_prefix=self.campaign.config["subject_prefix"],
            forbidden=self.campaign.forbidden_roots, port=DEAD_PORT))

    def proxy(self, allow, label):
        proxy = allowlist_proxy.AllowlistProxy(allow, log_path=self.record_dir / f"{label}.proxy.jsonl")
        proxy.owner_check = lambda address: socket_owned_by(proxy.owner_pid, address[1], proxy.port)
        proxy.start()
        return proxy

    def launch(self, probe_id, argv, *, cwd, env, profile, timeout_s=PROBE_TIMEOUT_S, stdin=None, proxy=None,
               stdout_path=None, stderr_path=None, stdin_path=None, record_dir=None):
        """One recorded probe launch: process_started.json at the start (and the proxy's owner); closed.json only
        after isolation.launch returned, or when nothing started. A launch that raised after its start (an
        interrupt may have cut its kill short) is left without closed.json (its error in error.json), so the next
        probe or run censuses it by its record (census_lost_probes, R12c). Returns the LaunchResult facts (or the
        error) with the capped streams."""
        directory = record_dir or self.record_dir / probe_id
        directory.mkdir(mode=0o700, exist_ok=record_dir is not None)
        stdout_path = stdout_path or directory / "stdout.txt"
        stderr_path = stderr_path or directory / "stderr.txt"
        if stdin is not None:
            stdin_path = directory / "stdin.txt"
            Path(stdin_path).write_bytes(stdin)

        def on_start(started):
            if proxy is not None:
                proxy.owner_pid = started["pid"]
            canonical.write_once(directory / "process_started.json", runner._pretty(started))
        outcome, result = {}, None
        try:
            result = isolation.launch(list(argv), cwd=str(cwd), env=env, profile=profile, timeout_s=timeout_s,
                                      stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                                      stdin_path=None if stdin_path is None else str(stdin_path), on_start=on_start,
                                      remove_unattributed_ipc=False)
            outcome = {"exit_code": result.exit_code, "timed_out": result.timed_out, "killed": result.killed,
                       "survivors": result.survivors, "census_complete": result.census_complete,
                       "ipc_residue": result.ipc_residue, "wall_seconds": round(result.wall_seconds, 3)}
            canonical.write_once(directory / "closed.json", runner._pretty(outcome))
        except BaseException as exc:
            outcome = {"error": f"{type(exc).__name__}: {exc}"}
            if os.path.lexists(directory / "process_started.json"):   # censused by its record later, never closed
                canonical.atomic_write_bytes(directory / "error.json", runner._pretty(outcome))
            else:                                                      # nothing started: nothing to census
                canonical.write_once(directory / "closed.json", runner._pretty(outcome))
            raise
        finally:
            if proxy is not None:   # the leader is gone (or never known): no later client is ever its owner
                proxy.owner_pid = None
        return result if record_dir is not None else \
            {**outcome, "stdout": _capped(stdout_path), "stderr": _capped(stderr_path)}

    def python_probe(self, probe_id, script, args, *, ws, state, ports=(DEAD_PORT,), env=None, proxy=None):
        out = self.launch(probe_id, [self.python, "-I", "-c", script, json.dumps(args)], cwd=ws,
                          env=env or self.env(ws), profile=self.profile(ws, ports, state), proxy=proxy)
        return out, _last_json(out["stdout"])


def _probe(pid, required, ok, detail) -> dict:
    return {"id": pid, "required": required, "ok": bool(ok), "detail": detail}


def _hp01(pr):
    ws, state = pr.workspace("hp01"), pr.state("hp01")
    out = pr.launch("HP-01", [pr.executable, "--version"], cwd=ws, env=pr.host_env(ws, state),
                    profile=pr.profile(ws, [DEAD_PORT], state))
    from .adapters.base import version_token
    version = version_token(out["stdout"].decode("utf-8", "replace"), claude_cli.VERSION_PATTERN)
    return _probe("HP-01", True, out.get("exit_code") == 0 and version == pr.campaign.host["version"],
                  {"exit_code": out.get("exit_code"), "version": version, "error": out.get("error")})


def _hp02(pr):
    ws, state = pr.workspace("hp02"), pr.state("hp02")
    sibling = pr.states / "hp02-sibling"
    os.mkdir(sibling, 0o700)
    targets = {"config": str(state / "config" / "hp02.txt"), "tmp": str(state / "tmp" / "hp02.txt"),
               "state_root": str(pr.campaign.host_state_root / f"hp02-{secrets.token_hex(4)}.txt"),
               "probe_state": str(state / "hp02.txt"), "sibling": str(sibling / "hp02.txt")}
    out, found = pr.python_probe("HP-02", WRITE_PROBE, targets, ws=ws, state=state)
    found = found or {}
    ok = found.get("config") == "ok" and found.get("tmp") == "ok" and all(
        found.get(k) == EPERM for k in ("state_root", "probe_state", "sibling"))
    return _probe("HP-02", True, ok, {"writes": found, "exit_code": out.get("exit_code")})


def _hp03(pr):
    ws, state = pr.workspace("hp03"), pr.state("hp03")
    out, found = pr.python_probe("HP-03", TERMINAL_PROBE, {}, ws=ws, state=state)
    found = found or {}
    ok = bool(found) and found.get("dev_tty") != "opened" and found.get("openpty") != "opened" \
        and found.get("stdin_isatty") is False
    return _probe("HP-03", True, ok, {"terminal": found, "exit_code": out.get("exit_code")})


def _hp04(pr):
    ws, state = pr.workspace("hp04"), pr.state("hp04")
    env = pr.host_env(ws, state)
    shell = pr.launch("HP-04-shell", ["/bin/zsh", "-l", "-c", 'echo ravel-probe-ok; echo "PATH=$PATH"; '
                                                              'command -v python3 || true'],
                      cwd=ws, env=env, profile=pr.profile(ws, [DEAD_PORT], state))
    python = pr.launch("HP-04-python", [pr.python, "-I", "-c", "import sys; print(sys.executable)"], cwd=ws,
                       env=env, profile=pr.profile(ws, [DEAD_PORT], state))
    text = shell["stdout"].decode("utf-8", "replace")
    ok = shell.get("exit_code") == 0 and "ravel-probe-ok" in text and python.get("exit_code") == 0
    return _probe("HP-04", True, ok, {"shell_exit": shell.get("exit_code"), "shell_output": text[-2000:],
                                      "zdotdir": env.get("ZDOTDIR"), "python_exit": python.get("exit_code"),
                                      "python": python["stdout"].decode("utf-8", "replace").strip()[-300:]})


def _hp05(pr):
    ws, state = pr.workspace("hp05"), pr.state("hp05")
    mark = secrets.token_hex(16)
    env = pr.env(ws, extra={"RAVEL_PROBE_MARK": mark})
    out = pr.launch("HP-05", ["/bin/zsh", "-c", "ps -wwE -p $$ 2>&1; echo rc=$?"], cwd=ws, env=env,
                    profile=pr.profile(ws, [DEAD_PORT], state))
    seen = mark.encode() in out["stdout"] + out["stderr"]
    return _probe("HP-05", True, not seen and "error" not in out,
                  {"value_visible_to_child": seen, "exit_code": out.get("exit_code")})


def _hp06(pr):
    """The keychain gate (R1; E-42 as amended by E-73; B-05's alternative evidence, no canary): (1) a sandboxed stat
    of the login keychain gets EPERM; (2) ``security show-keychain-info <login keychain>``, which names the keychain
    file and touches no item, exits 0 or 36 (reachable) unsandboxed and otherwise (not 0, 36, 126 or 127) under the
    real-host profile. The control and the probe run in the same environment, the probe's (HOME the probe's own):
    HOME alone changes security's search list and default keychain, so an implicit query contrasted across two
    HOMEs proves nothing (the H-28 diagnostic did that). Recorded, not required: the same query under the fake
    host's profile (it exits otherwise when the removed mach services matter), and the lookup of a random
    nonexistent service sandboxed and not (both exit 44; only the message differs). Nothing is added, changed or
    deleted in any keychain, and no item is read."""
    ws, state = pr.workspace("hp06"), pr.state("hp06")
    keychain = login_keychain()
    _, found = pr.python_probe("HP-06-stat", STAT_PROBE, {"login_keychain": keychain}, ws=ws, state=state)
    env = pr.env(ws)
    control = _security("show-keychain-info", keychain, env=env, cwd=str(ws))
    real = pr.launch("HP-06-show", [*SECURITY_COMMAND, "show-keychain-info", keychain], cwd=ws, env=env,
                     profile=pr.profile(ws, [DEAD_PORT], state))
    fake = pr.launch("HP-06-show-fake", [*SECURITY_COMMAND, "show-keychain-info", keychain], cwd=ws, env=env,
                     profile=pr.fake_profile(ws))
    service = f"ravel-probe-{secrets.token_hex(12)}"
    baseline = _security("find-generic-password", "-s", service, env=env, cwd=str(ws))
    lookup = pr.launch("HP-06-find", [*SECURITY_COMMAND, "find-generic-password", "-s", service], cwd=ws, env=env,
                       profile=pr.profile(ws, [DEAD_PORT], state))
    stat_ok = (found or {}).get("login_keychain") == EPERM
    contrast_ok = control in KEYCHAIN_LOCKED_OR_OK and real.get("exit_code") not in (
        *KEYCHAIN_LOCKED_OR_OK, *NOT_RUN, None)
    return _probe("HP-06", True, stat_ok and contrast_ok,
                  {"login_keychain_stat": (found or {}).get("login_keychain"),
                   "show_keychain_info_exit": {"unsandboxed": control, "real_host_profile": real.get("exit_code"),
                                               "fake_host_profile": fake.get("exit_code")},
                   "mach_removal_changes_the_answer": fake.get("exit_code") != real.get("exit_code"),
                   "nonexistent_service_lookup_exit": {"unsandboxed": baseline, "real_host_profile":
                                                       lookup.get("exit_code")},
                   "canary": "declined (E-42); B-05 alternative (E-73): the login keychain named explicitly is "
                             "reachable unsandboxed and not under the real-host profile, in the same environment"})


def _hp07(pr):
    """HP-07: a sandboxed ``os.stat`` of the credential directory (it must exist: smoke-request S2) and, once the token
    is minted, of the credential file, each EPERM. An absent path under a deny root answers ENOENT, which shows
    nothing, so the directory is required and the file is checked only when the coordinator's lstat finds it
    (``file_present``; never opened). A record made before the file existed is superseded (host_probe_problem)."""
    ws, state = pr.workspace("hp07"), pr.state("hp07")
    path = pr.campaign.host_launch["credential"]["file"]
    directory = os.path.dirname(path)
    directory_present = os.path.isdir(directory) and not os.path.islink(directory)
    file_present = os.path.lexists(path)
    targets = {"directory": directory, **({"credential": path} if file_present else {})}
    _, found = pr.python_probe("HP-07", STAT_PROBE, targets, ws=ws, state=state)
    found = found or {}
    ok = directory_present and found.get("directory") == EPERM and (not file_present
                                                                     or found.get("credential") == EPERM)
    return _probe("HP-07", True, ok, {"directory_present": directory_present, "file_present": file_present,
                                      "stat": found})


def _hp08(pr):
    ws, state = pr.workspace("hp08"), pr.state("hp08")
    echo = _EchoServer()
    proxy = pr.proxy([f"127.0.0.1:{echo.port}"], "HP-08")
    try:
        args = {"proxy": proxy.port, "echo": echo.port, "echo_target": f"127.0.0.1:{echo.port}", "script": PROXY_PROBE}
        out, found = pr.python_probe("HP-08", PROXY_PROBE, args, ws=ws, state=state, ports=[proxy.port], proxy=proxy)
    finally:
        proxy.stop()
        echo.stop()
    found = found or {}
    decisions = [(d["decision"], d["reason"], d.get("attribution"), d["target"]) for d in proxy.decisions]
    target = f"127.0.0.1:{echo.port}"
    ok = (found.get("leader") == ["HTTP/1.1 200 Connection Established", "ravel-probe-ping"]
          and found.get("child", "").startswith("HTTP/1.1 403") and found.get("not_allowlisted", "").startswith(
              "HTTP/1.1 403") and found.get("direct") == EPERM and found.get("dns") not in (None, "resolved")
          and found.get("v6") not in (None, "connected")   # [::1]:<proxy port> is reserved by the proxy, never served
          and ("allow", "allowlisted", "owner", target) in decisions
          and ("deny", "subject_client", "other", target) in decisions
          and ("deny", "not_allowlisted", "owner", "api.example.invalid:443") in decisions)
    return _probe("HP-08", True, ok, {"probe": found, "decisions": decisions, "stop_error": proxy.stop_error,
                                      "exit_code": out.get("exit_code")})


HP09_INIT_FLAGS = ("init_model_mismatch", "init_tools_unexpected", "init_permission_mode_mismatch",
                   "init_api_key_source_unexpected", "init_version_mismatch", "web_tools_in_init",
                   "init_tools_unrecognized", "plugins_present", "mcp_servers_present", "init_skills_unexpected",
                   "init_agents_unexpected")   # every init flag a paid run would stop on (H-26, E-91)


def _hp09(pr):
    """The dry host start (WI-7c): the real pinned binary with the campaign's argv plus a SessionStart hook that
    lists its environment NAMES, a DUMMY token, a probe task token, a deny-all allowlist with attribution, 120 s.
    Checks the hook env, not the Bash tool env; at least one CONNECT, each the leader's to the API; and the init
    flags a paid run would stop on (HP09_INIT_FLAGS, including an unexpected plugin or MCP server)."""
    ws, state = pr.workspace("hp09"), pr.state("hp09")
    proxy = pr.proxy(["127.0.0.1:9"], "HP-09")
    token = dummy_token()
    adapter = pr.adapter(state)
    session = str(uuid.uuid4())
    hook = f"{pr.python} -I -c '{HOOK_CODE}' > \"$CLAUDE_CODE_TMPDIR/{HOOK_OUTPUT}\""
    settings = json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": hook}]}]}})
    argv = adapter.build_argv(session_id=session) + ["--settings", settings]
    task_token = f"probe-{secrets.token_hex(8)}"
    env = {**pr.host_env(ws, state, proxy=proxy, task_token=task_token), pr.credential_name: token}
    try:
        out = pr.launch("HP-09", argv, cwd=ws, env=env, profile=pr.profile(ws, [proxy.port], state),
                        timeout_s=DRY_START_TIMEOUT_S, stdin=b"SYNTHETIC probe", proxy=proxy)
    finally:
        proxy.stop()
    from .adapters.base import parse_jsonl
    records, _ = parse_jsonl(out["stdout"])
    parsed = claude_cli.parse_stream(records, version=pr.campaign.host["version"], expected_session_id=session,
                                     expected_model=adapter.model, expected_tools=adapter.expected_tool_names(),
                                     expected_permission_mode=claude_cli.PERMISSION_MODE_EXTERNAL.get(
                                         adapter.permission_mode, adapter.permission_mode),
                                     expected_api_key_source=adapter.expected_api_key_source)
    init_flags = sorted(set(parsed["flags"]) & set(HP09_INIT_FLAGS))
    names_text = _capped(state / "tmp" / HOOK_OUTPUT).decode("utf-8", "replace")
    names = set(names_text.split())
    swept = credentials.sweep({"workspace": str(ws), "state": str(state), "record": str(pr.record_dir / "HP-09")},
                              token.encode(), redact=False)
    keychain = keychain_residue(state / "config")
    connects = [{"target": d["target"], "attribution": d.get("attribution"), "reason": d["reason"]}
                for d in proxy.decisions]
    checks = {"connects_seen": bool(connects),   # zero CONNECTs would pass the next check vacuously
              "connects_only_api_from_the_leader": all(c["target"] == PROXY_ALLOW[0] and c["attribution"] == "owner"
                                                       for c in connects),
              "hook_ran": bool(names), "hook_sees_task_token": "RAVEL_TASK_TOKEN" in names,
              "hook_lacks_credential": not names & set(CREDENTIAL_NAMES),
              "dummy_token_nowhere": not swept["hits"] and not swept["incomplete"],
              "no_keychain_item": not keychain["persisted"], "init_matches": not init_flags}
    return _probe("HP-09", True, all(checks.values()),
                  {"checks": checks, "connects": connects, "init_present": parsed["details"]["init"] is not None,
                   "init": parsed["details"]["init"], "init_flags": init_flags, "exit_code": out.get("exit_code"),
                   "timed_out": out.get("timed_out"), "sweep": {"hits": swept["hits"], "incomplete": swept["incomplete"]},
                   "keychain": keychain, "hook_names": sorted(names)})


def _hp10(pr):
    ws, state = pr.workspace("hp10"), pr.state("hp10")
    out, found = pr.python_probe("HP-10", MULTIPROCESSING_PROBE, {}, ws=ws, state=state)
    return _probe("HP-10", False, (found or {}).get("result") == 42,
                  {"outcome": found, "expected": "FAIL (E-45: multiprocessing stays unavailable)"})


def _hp11(pr):
    """HP-11 (recorded, not required): a sandboxed open of an EXISTING file under a deny root (the login keychain:
    EPERM, never read; an absent path answers ENOENT and logs no denial), then the collector filtered to that
    launch's pid, so other processes' denials cannot make a blind collector look working."""
    ws, state = pr.workspace("hp11"), pr.state("hp11")
    start = runner.utc_now()
    _, found = pr.python_probe("HP-11", READ_PROBE, {"path": login_keychain()}, ws=ws, state=state)
    time.sleep(1.0)
    try:
        pid = canonical.strict_load(pr.record_dir / "HP-11" / "process_started.json")["pid"]
    except (ContractError, OSError, ValueError, KeyError, TypeError):
        pid = None
    denials = sandbox_denials(start, runner.utc_now(), pid=pid) if pid else \
        {"available": False, "count": None, "truncated": False, "error": "the probe launch recorded no pid"}
    return _probe("HP-11", False, (found or {}).get("read") == EPERM and denials["available"]
                  and (denials["count"] or 0) > 0,
                  {"denied_read": (found or {}).get("read"), "pid": pid, "collector": denials})


def _hp12(pr):
    ws, state = pr.workspace("hp12"), pr.state("hp12")
    env = pr.env(ws)
    found = {}
    for label, argv in (("python3", ["/usr/bin/python3", "-V"]), ("git", ["/usr/bin/git", "--version"])):
        out = pr.launch(f"HP-12-{label}", argv, cwd=ws, env=env, profile=pr.profile(ws, [DEAD_PORT], state))
        found[label] = {"exit_code": out.get("exit_code"), "timed_out": out.get("timed_out"),
                        "output": (out["stdout"] + out["stderr"]).decode("utf-8", "replace").strip()[-300:]}
    return _probe("HP-12", False, all(v["exit_code"] == 0 for v in found.values()), found)


class _RehearsalHost:
    """HP-13's session host (rehearsal.rehearse): each session a fresh probe workspace, HOME, config and tmp
    directory and an outside directory; one launch of the pinned CLI through the bound adapter with the model and
    pins of the session, the mock as ANTHROPIC_BASE_URL (probe configuration only), the probe task service, a
    deny-all proxy with attribution, the DUMMY credential injected by the launcher, and the real-host profile
    (task service, mock and proxy ports). Every launch's start and close are recorded (R12c)."""

    def __init__(self, pr, token):
        self.pr, self.token, self.count = pr, token, 0

    def prepare(self, name):
        self.count += 1
        label = f"hp13-{self.count:02d}-{name.replace(':', '-')}"
        ws, state = self.pr.workspace(label), self.pr.state(label, make=False)
        outside = self.pr.states / f"{label}-outside"
        os.mkdir(outside, 0o700)
        from . import rehearsal
        return rehearsal.SessionContext(
            workspace=ws, home=ws / "home", outside=outside, config_dir=state / runner.HOST_STATE_SUBDIRS[0],
            sweep_roots={"workspace": ws, "state": state, "outside": outside,
                         "streams": self.pr.record_dir / f"HP-13-{label}"})

    def run(self, ctx, *, prompt, model, env, credential_mode, base_url, mock_port, task_endpoint, task_token):
        pr, state = self.pr, ctx.config_dir.parent
        streams = Path(ctx.sweep_roots["streams"])
        streams.mkdir(mode=0o700)
        proxy = pr.proxy(["127.0.0.1:9"], streams.name)
        secret_name = pr.credential_name if credential_mode == "oauth" else "ANTHROPIC_API_KEY"
        host = {**pr.campaign.host, "model": model}
        host_launch = {**pr.campaign.host_launch,
                       "claude": {**pr.campaign.host_launch["claude"],
                                  "env_pins": {**pr.campaign.host_launch["claude"]["env_pins"], **env}}}

        def launcher(argv, *, cwd, env, profile, timeout_s, stdout_path, stderr_path, stdin_path=None):
            return pr.launch(streams.name, argv, cwd=cwd, env={**env, secret_name: self.token}, profile=profile,
                             timeout_s=timeout_s, proxy=proxy, stdout_path=stdout_path, stderr_path=stderr_path,
                             stdin_path=stdin_path, record_dir=streams)
        try:
            adapter = pr.adapter(state, host=host, host_launch=host_launch, launcher=launcher)
            adapter.expected_api_key_source = "none" if credential_mode == "oauth" else "ANTHROPIC_API_KEY"
            task_port = int(task_endpoint.rsplit(":", 1)[1].split("/")[0])
            subject = pr.env(ctx.workspace, proxy=proxy, task_endpoint=task_endpoint, task_token=task_token,
                             extra={"ANTHROPIC_BASE_URL": base_url})
            profile = pr.profile(ctx.workspace, [task_port, mock_port, proxy.port], state)
            result = adapter.run(prompt=prompt, workspace=ctx.workspace, env=subject, profile=profile,
                                 timeout_s=REHEARSAL_SESSION_TIMEOUT_S, out_dir=streams)
        finally:
            proxy.stop()
        return result.as_dict()


# The model catalog a Claude Code bundle carries (2.1.281: `{id:"<model>",...,pricing:"tier_2_10",...}` and
# `pricing_tiers:{tier_2_10:{input:2,output:10,cache_write_5m:2.5,cache_write_1h:4,cache_read:0.2,...}}`), and how
# its price fields map onto the usage kinds HP-13 measures.
CATALOG_KINDS = {"input": "input_tokens", "output": "output_tokens", "cache_write_5m": "cache_creation_input_tokens",
                 "cache_read": "cache_read_input_tokens"}
CATALOG_SPAN = 8192          # bytes after a model entry's opening searched for its pricing tier
NUMBER = rb"[0-9]+(?:\.[0-9]+)?(?:e[0-9]+)?"


def catalog_entry(executable, model):
    """The pinned binary's own catalog price for ``model`` (H-27): {tier, rates {kind: USD per Mtok}, entries,
    tables, other_occurrences}, or None when no catalog entry (an ``{id:"<model>",...}`` object naming a ``pricing``
    tier before the next ``{id:``) or its tier's rates can be located, or two catalog entries or tables disagree.
    Objects of the same id without a pricing tier (the bundle's UI model lists, effort defaults) are counted in
    ``other_occurrences`` and otherwise ignored. Reads the binary (memory-mapped); nothing is executed. HP-13 accepts
    the rates only when they equal the measured ones."""
    import mmap
    require(isinstance(model, str) and model and model.isascii() and '"' not in model, "catalog_entry: a model id")
    entry = re.compile(rb'\{id:"' + re.escape(model.encode()) + rb'",')
    tier_of = re.compile(rb'pricing:"(tier_[a-z0-9_]+)"')
    tiers, rates, entries, others = set(), [], 0, 0
    with open(executable, "rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
        for found in entry.finditer(data):
            span = data[found.end():found.end() + CATALOG_SPAN]
            nxt = span.find(b'{id:"')
            match = tier_of.search(span if nxt < 0 else span[:nxt])
            if match:
                entries += 1
                tiers.add(match.group(1))
            else:
                others += 1
        if len(tiers) != 1:
            return None
        [tier] = tiers
        table = re.compile(rb'pricing_tiers:\{[^;]{0,4096}?\b' + re.escape(tier) + rb':\{([^{}]{1,512})\}')
        for found in table.finditer(data):
            fields = dict(re.findall(rb"([a-z0-9_]+):(" + NUMBER + rb")", found.group(1)))
            try:
                rates.append({CATALOG_KINDS[k]: float(fields[k.encode()]) for k in CATALOG_KINDS})
            except KeyError:
                return None
    if not rates or any(r != rates[0] for r in rates):
        return None
    return {"tier": tier.decode(), "rates": rates[0], "entries": entries, "tables": len(rates),
            "other_occurrences": others}


def _hp13(pr, catalog=False):
    """The offline rehearsal (R2-R5, R14) through rehearsal.rehearse; rerun with a dummy API key when the pinned CLI
    refuses the OAuth token with a custom base URL (recorded: apiKeySource is then checked by HP-09 or run 1). With
    ``catalog`` (``host-probe --catalog-rates``) the pinned binary's own catalog entry for the model is located
    (catalog_entry) and offered to the pricing check, which accepts it only when it equals the measured rates."""
    from . import rehearsal
    token, mock = dummy_token(), rehearsal.load_mock()
    c = pr.campaign.host_launch["claude"]
    located = catalog_entry(pr.executable, pr.campaign.host["model"]) if catalog else None
    kw = {"pinned_model": pr.campaign.host["model"], "effort": c["effort"], "tools": c["tools"],
          "cap_usd": pr.campaign.budget["usd_per_run"], "max_retries": int(c["env_pins"].get("CLAUDE_CODE_MAX_RETRIES",
                                                                                            "3")),
          "catalog_rates": None if located is None else located["rates"]}
    record = rehearsal.rehearse(_RehearsalHost(pr, token), mock, token=token, **kw)
    first = None
    if rehearsal.oauth_refused(record):
        first, token = record, dummy_token()
        record = rehearsal.rehearse(_RehearsalHost(pr, token), mock, token=token, credential_mode="api_key", **kw)
    detail = {**record, "oauth_attempt": None if first is None else {"ok": first["ok"], "refused": True},
              "catalog": {"requested": bool(catalog), "located": located}}
    return _probe("HP-13", True, record["ok"] and record["pricing_eligible"] is True, detail)


BASE_PROBES = (_hp01, _hp02, _hp03, _hp04, _hp05, _hp06, _hp07, _hp08)
EXTRA_PROBES = (_hp10, _hp11, _hp12)


def _run_probe(fn, *args) -> dict:
    pid = f"HP-{fn.__name__[3:]}"
    try:
        return fn(*args)
    except Exception as exc:   # noqa: BLE001 - a probe that cannot run fails, with its reason
        return _probe(pid, pid not in ("HP-10", "HP-11", "HP-12"), False, {"error": f"{type(exc).__name__}: {exc}"})


def host_probe(campaign_dir, *, dry_start=False, rehearse=False, catalog=False) -> dict:
    """``cli.py host-probe``: non-model, no egress (the probes reach only 127.0.0.1 servers of this process). Takes
    the campaign lock, censuses every lost or unclean probe launch first, runs HP-01..HP-08 and HP-10..HP-12, HP-09
    with ``dry_start`` and HP-13 with ``rehearse`` (each the user's go-ahead, E-43; ``catalog``: HP-13 may accept the
    pinned binary's located catalog entry, ``--catalog-rates``), censuses again any of this run's launches that left
    survivors or lost their census, and writes ``coordinator/host_probe/<n>/result.json``. The record is ok only when
    every required probe passed and no probe launch's census is unclean (E-96: ``unclean_launches``). A paid run
    needs the latest record ok with HP-06, HP-09 and HP-13 passing (host_probe_problem)."""
    campaign_dir = Path(campaign_dir).resolve()
    with runner.campaign_lock(campaign_dir):
        campaign = runner._Campaign(campaign_dir)
        require(campaign.real, "host-probe: the campaign has no real host")
        lost = census_lost_probes(campaign_dir)
        parent = _probe_parent(campaign_dir)
        parent.mkdir(mode=0o700, exist_ok=True)
        numbered = runner._numbered(parent)
        pr = _ProbeRun(campaign, numbered[-1][0] + 1 if numbered else 1)
        probes = [_run_probe(fn, pr) for fn in BASE_PROBES]
        if dry_start:
            probes.append(_run_probe(_hp09, pr))
        probes += [_run_probe(fn, pr) for fn in EXTRA_PROBES]
        if rehearse:
            probes.append(_run_probe(_hp13, pr, catalog))
        after = census_lost_probes(campaign_dir)   # this run's own launches that left survivors or lost their census
        unclean = sorted(set(census_problems(lost)) | set(census_problems(after)))
        ok = all(p["ok"] for p in probes if p["required"]) and not unclean
        ids = {p["id"] for p in probes}
        record = {"schema_version": 1, "probe_run": pr.n, "campaign_sha256": campaign.campaign_sha256,
                  "time_utc": runner.utc_now(), "dry_start": dry_start, "rehearse": rehearse, "catalog": catalog,
                  "lost_probe_launches": lost, "censused_after": after, "unclean_launches": unclean, "ok": ok,
                  "complete": all(i in ids for i in GATE_PROBES), "probes": probes}
        path = pr.record_dir / "result.json"
        canonical.write_once(path, runner._pretty(record))
    return {"ok": ok, "complete": record["complete"], "record": str(path),
            "probes": [{"id": p["id"], "required": p["required"], "ok": p["ok"]} for p in probes],
            "failed": [p["id"] for p in probes if p["required"] and not p["ok"]], "unclean_launches": unclean,
            **({"remedy": PROBE_CENSUS_REMEDY} if unclean else {})}


def _hp13_detail(campaign_dir) -> dict:
    _, record = latest_host_probe(campaign_dir)
    probe = next((p for p in (record or {}).get("probes", []) if isinstance(p, dict) and p.get("id") == "HP-13"), None)
    detail = (probe or {}).get("detail")
    return detail if isinstance(detail, dict) else {}


def cli_price_per_mtok(campaign_dir) -> dict:
    """The pinned CLI's measured rates per million tokens from the latest HP-13 record ({model: {kind: usd}}), or {}."""
    rates = _hp13_detail(campaign_dir).get("cli_price_per_mtok")
    return rates if isinstance(rates, dict) else {}


def cli_geo_multiplier(campaign_dir) -> dict:
    """The pinned CLI's measured cost multiplier per inference geography ({"us": x}) from the latest HP-13, or {}."""
    found = _hp13_detail(campaign_dir).get("cli_geo_multiplier")
    return {k: v for k, v in found.items() if canonical.finite_number(v)} if isinstance(found, dict) else {}


# ---------------------------------------------------------------- stop rules (§4), live checks (WI-7d), costs (§5)

# Flags (sealed validity flags, the adapter's recorded flags, the coordinator's journaled notes and the live checks'
# own) and the stop rule each triggers. The default is inverted (E-74): a flag stops the campaign unless it is listed
# in OUTCOME_FLAGS, so a flag nobody classified (a new one, or one this table missed) stops it under S7 as
# "unclassified". Every invalidating flag (adapters.base.INVALIDATING_FLAGS) has its own rule here.
STOP_RULES = {
    "host_auth_failed": "S1", "host_usage_limited": "S1",
    "credential_exposed": "S2", "credential_visible_to_subject": "S2", "credential_sweep_incomplete": "S2",
    "credential_persisted_keychain": "S2", "init_api_key_source_unexpected": "S2",
    "host_config_credential_shaped": "S2",
    "proxy_denied_connect": "S3", "proxy_owner_unknown": "S3", "canary_in_transcript": "S3",
    "web_tools_in_init": "S3", "init_tools_unexpected": "S3", "web_tool_used": "S3", "web_requests_reported": "S3",
    "mcp_servers_present": "S3", "plugins_present": "S3", "init_permission_mode_mismatch": "S3",
    "init_skills_unexpected": "S3", "init_agents_unexpected": "S3",
    "survivors_after_kill": "S3", "census_incomplete": "S3", "ipc_residue": "S3",
    "init_tools_unrecognized": "S3", "web_search_item_present": "S3", "sandbox_none_test_only": "S3",
    "subject_outlived_coordinator": "S3",
    "code_drift_during_run": "S4", "kernel_fingerprint_mismatch": "S4", "stage_worker_mismatch": "S4",
    "interpreter_mismatch": "S4", "broker_internal_error": "S4",
    "cost_recompute_mismatch": "S5", "fast_mode_used": "S5", "cost_zero_with_usage": "S5",
    "cache_write_1h_reported": "S5", "cost_overshoot_beyond_turn": "S5",
    "init_model_mismatch": "S6", "main_model_substituted": "S6", "init_version_mismatch": "S6",
    "init_unverified": "S6", "shell_tool_failed": "S6", "task_token_missing_in_shell": "S6",
    "no_init_event": "S6", "session_id_mismatch": "S6", "multiple_init_events": "S6",
    "multiple_result_events": "S6", "subagent_usage_unverified": "S6",
    "coordinator_interrupted": "S7", "adapter_error": "S7", "proxy_upstream_error": "S7", "proxy_stop_failed": "S7",
    "broker_stop_failed": "S7", "raw_streams_missing": "S7", "launch_unrecorded": "S7",
    "normalization_failed": "S7", "schema_errors": "S7", "parse_errors": "S7",
    "synthetic_marker_in_nonsynthetic_run": "S7", "unlabeled_synthetic_records": "S7", "custody_missing": "S7",
    "custody_malformed": "S7", "stdin_mismatch": "S7", "prompt_in_argv": "S7", "clock_stepped_back": "S7",
    "host_version_mismatch": "S7",
}
# The flags that are outcomes, scored as usual and never a stop (smoke spec §4): a timeout or crash without a result,
# budget and turn exhaustion, unknown or overshooting cost (charged at the cap), permission denials, a subject's
# network attempt or refusal, a subject's odd output files, and the informational live-check notes (H-22).
OUTCOME_FLAGS = frozenset({
    "no_result_event", "is_error_overrides_success_subtype", "cost_zeroed_on_error", "cost_unverified",
    "cost_unverified_auxiliary", "permission_denied", "permission_denials_best_effort_only", "model_refusal_reported",
    "auxiliary_model_usage", "cost_basis_not_list", "sandbox_denial_in_tool_output", "cost_over_run_cap",
    "host_budget_exhausted", "subject_network_attempt", "shell_snapshot_missing", "sandbox_denials_unavailable",
    "subject_output_violations",
})
UNCLASSIFIED_RULE = "S7"
# not_started codes (runner journals them) and their rule; every not_started of a live campaign stops it (a smoke
# stops at any anomaly, E-67), a code missing here under UNCLASSIFIED_RULE. E-6x records the codes the spec does not
# name. A resume that finds an admission_failed record without its not_started (the coordinator died between the two
# writes) closes the run with the admission STAGE as its code (runner._Campaign._resume), so each stage maps to the
# rule of the code its first close records: workspace (code admission), broker (broker_preparation) and proxy
# (proxy_start_failed); the other stages are their own codes (E-70, E-71). STOP_CLOSURE_CODE is the code of a run the
# stop itself closed: it never triggers anything.
NOT_STARTED_RULES = {"credential_unavailable": "S1", "global_budget": "S5", "treatment": "S4",
                     "host_drift": "S6", "binding_mismatch": "S6", "host": "S6", "proxy_start_failed": "S7",
                     "admission": "S3", "environment": "S3", "prompt": "S3", "launch_refused": "S3",
                     "materialization": "S7", "profile": "S7", "broker_preparation": "S7",
                     "adapter_before_launch": "S7", "interrupted_before_launch": "S7",
                     "workspace": "S3", "broker": "S7", "proxy": "S7"}
STOP_CLOSURE_CODE = "stopped"
SEVERITY = ("S2", "S3", "S1", "S4", "S6", "S5", "S7", "S8")
RULE_NAMES = {"S1": "host auth or quota", "S2": "credential", "S3": "isolation", "S4": "kernel or treatment",
              "S5": "spend", "S6": "host configuration", "S7": "harness", "S8": "human"}
LIVE_CHECKS = "live_checks.json"   # runs/<run_id>/live_checks.json, outside sealed/
RECOMPUTE_TOLERANCE = 0.01         # LC-16: |recomputed - reported| above 1% of reported is cost_recompute_mismatch
BREAKDOWN_TOLERANCE = 1e-6
USAGE_KINDS = {"inputTokens": "input_tokens", "outputTokens": "output_tokens",
               "cacheCreationInputTokens": "cache_creation_input_tokens",
               "cacheReadInputTokens": "cache_read_input_tokens"}
MAX_OUTPUT_FALLBACK = 128_000      # §5 worst case: output tokens of one turn when modelUsage names no maxOutputTokens
REVOKE = ("REVOKE THE TOKEN NOW: claude.ai > Settings > Claude Code (or the account's security settings) lists the "
          "setup-token; revoke it, then delete ~/.config/ravel-eval/claude-oauth-token (E-50: retention ends on any "
          "credential flag)")
CENSUS_REMEDY = ("a survivor or an incomplete census leaves processes a human must find through the launch's recorded "
                 "start: isolation.census_launch(<the process_started record in runs/<run_id>/journal.jsonl>) searches "
                 "exactly that launch's sandbox marker and group; never kill by name or pattern (E-68)")


def _rates_for(rates, model):
    if model in rates:
        return rates[model]
    return next((v for k, v in rates.items() if claude_cli.same_model(model, k)), None)


def _model_cost(usage, rate, multiplier=1.0):
    """One modelUsage entry's tokens x its measured rates x the geography multiplier, or None when unknown."""
    if not isinstance(usage, dict) or not isinstance(rate, dict) or not canonical.finite_number(multiplier):
        return None
    total = 0.0
    for field, kind in USAGE_KINDS.items():
        tokens, per = usage.get(field) or 0, rate.get(kind)
        if not canonical.finite_number(tokens) or not canonical.finite_number(per):
            return None
        total += tokens * per / 1_000_000
    return total * multiplier


def recompute_cost(model_usage, rates, multiplier=1.0):
    """``modelUsage`` tokens x the pinned CLI's measured rates (HP-13 cli_price_per_mtok) x ``multiplier`` (the
    measured inference-geography multiplier), or None when a model's rates or tokens are unknown. No provider price
    is ever assumed (§5)."""
    if not isinstance(model_usage, dict) or not model_usage:
        return None
    parts = [_model_cost(usage, _rates_for(rates, model), multiplier) for model, usage in model_usage.items()]
    return None if any(p is None for p in parts) else sum(parts)


def geo_multiplier(geos, measured):
    """The cost multiplier for the inference geographies a run's usage reported: 1.0 for none, HP-13's measured
    multiplier for exactly one it measured, else None (unverifiable: the recompute is then not compared)."""
    geos = sorted(set(geos or []))
    if not geos:
        return 1.0
    if len(geos) == 1 and canonical.finite_number((measured or {}).get(geos[0])):
        return float(measured[geos[0]])
    return None


def _result_model_usage(result):
    for event in reversed(result.get("events") or []):
        data = event.get("data") if isinstance(event, dict) else None
        if isinstance(data, dict) and data.get("type") == "result" and isinstance(data.get("modelUsage"), dict):
            return data["modelUsage"]
    return None


def _cost_facts(result, details, rates, multipliers, pinned):
    """LC-16's recompute: {reported, recomputed (total, or None), pinned_share {model: [recomputed, reported]},
    unpriced (models without measured rates), multiplier, geo} and the flags it sets: cost_recompute_mismatch when
    the pinned model's own share or the whole total differs from the CLI's by more than RECOMPUTE_TOLERANCE, and
    cost_unverified_auxiliary when another model's share has no measured rates (its share is then not compared, but
    the pinned model's still is)."""
    flags = set()
    reported = (details.get("cost_accounting") or {}).get("reported_total_cost_usd")
    model_usage = _result_model_usage(result)
    multiplier = geo_multiplier(details.get("inference_geo"), multipliers)
    facts = {"reported": reported, "recomputed": None, "pinned_share": {}, "unpriced": [], "multiplier": multiplier,
             "geo": details.get("inference_geo"), "rates_from": "HP-13 cli_price_per_mtok"}

    def differs(a, b):
        return canonical.finite_number(a) and canonical.finite_number(b) and \
            abs(a - b) > RECOMPUTE_TOLERANCE * max(b, 1e-12)
    if not isinstance(model_usage, dict) or not model_usage or multiplier is None:
        return facts, flags
    for model, usage in model_usage.items():
        cost = _model_cost(usage, _rates_for(rates, model), multiplier)
        if cost is None:
            facts["unpriced"].append(model)
            continue
        if claude_cli.same_model(model, pinned):
            share = (usage or {}).get("costUSD") if isinstance(usage, dict) else None
            facts["pinned_share"][model] = [cost, share]
            if differs(cost, share):
                flags.add("cost_recompute_mismatch")
    if facts["unpriced"]:
        if any(not claude_cli.same_model(m, pinned) for m in facts["unpriced"]):
            flags.add("cost_unverified_auxiliary")
    else:
        facts["recomputed"] = recompute_cost(model_usage, rates, multiplier)
        if differs(facts["recomputed"], reported):
            flags.add("cost_recompute_mismatch")
    return facts, flags


def _overshoot_facts(result, details, rates, multipliers, pinned, cap):
    """LC-16's ceiling check (E-93): {reported, cap, overshoot_usd, turn_bound_usd, subtype, beyond_one_turn} and the
    flag it sets. The host checks --max-budget-usd between messages, so a run may overshoot c by the one turn that
    crossed it (an outcome, cost_over_run_cap); an overshoot larger than one turn's bound (_turn_bound at the measured
    rates, times the run's geography multiplier or, when HP-13 did not measure it, the largest one measured) means the
    ceiling did not hold: cost_overshoot_beyond_turn (S5). Without measured rates there is no bound, and any overshoot
    whose result is not error_max_budget_usd is taken as beyond one turn (fail closed)."""
    reported = (details.get("cost_accounting") or {}).get("reported_total_cost_usd")
    subtype = details.get("result_subtype")
    facts = {"reported": reported, "cap": cap, "overshoot_usd": None, "turn_bound_usd": None, "subtype": subtype,
             "beyond_one_turn": False}
    if not canonical.finite_number(reported) or not canonical.finite_number(cap) or reported <= cap:
        return facts, set()
    multiplier = geo_multiplier(details.get("inference_geo"), multipliers)
    if multiplier is None:
        multiplier = max([1.0, *(float(v) for v in (multipliers or {}).values() if canonical.finite_number(v))])
    turn = _turn_bound(result, rates, multiplier, pinned)
    overshoot = reported - cap
    beyond = subtype != "error_max_budget_usd" if turn is None else overshoot > turn
    facts.update(overshoot_usd=overshoot, turn_bound_usd=turn, beyond_one_turn=beyond)
    return facts, {"cost_overshoot_beyond_turn"} if beyond else set()


def _sealed_json(sealed, name):
    path = sealed / name
    return canonical.strict_load(path) if path.is_file() and not path.is_symlink() else None


def _custody_facts(sealed):
    lines, _ = canonical.read_jsonl(sealed / "broker" / "custody.jsonl")
    subject = [x for x in lines if isinstance(x, dict) and x.get("op") not in ("register_inputs", "create_prior")]
    internal = [x.get("seq") for x in lines if isinstance(x, dict) and isinstance(x.get("incident"), dict)
                and x["incident"].get("kind") == "internal_error"]
    return {"subject_operations": len(subject), "authenticated_operations": sum(1 for x in subject if x.get("ok")),
            "internal_errors": internal}


def live_checks(campaign_dir, run_id, *, write=True) -> dict:
    """LC-01..LC-23 of one sealed run (WI-7d) from the sealed evidence, the journal and the latest HP-13 record only;
    written to ``runs/<run_id>/live_checks.json`` (outside sealed/) unless ``write`` is False (preflight). Each check is
    pass, fail, warn, info or na; ``flags`` is every flag on record (sealed, recorded by the adapter, journaled,
    derived here); ``stop`` is stop_reason's."""
    campaign_dir = Path(campaign_dir).resolve()
    rdir = campaign_dir / "runs" / run_id
    journal = runner.read_journal(rdir / "journal.jsonl")
    digest, problem = runner.seal_problem(rdir)
    require(problem is None, f"live checks read only a reconciled seal: run {run_id}: {problem}")
    sealed = rdir / "sealed"
    run = canonical.strict_load(sealed / "run.json")
    manifest = canonical.strict_load(campaign_dir / campaign_manifest.MANIFEST)
    host_launch, host = load_host_launch(campaign_dir), manifest["host"]
    closing = next((r["details"] for r in reversed(journal)
                    if r["state"] in ("exited", "interrupted_crash", "not_started")), {})
    result = _sealed_json(sealed, "adapter_result.json") or {}
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    flags = set(run["validity_flags"]) | set(details.get("flags") or []) | set(closing.get("info_flags") or [])
    checks = []

    def add(cid, status, detail):
        checks.append({"id": cid, "status": status, "detail": detail})

    def gate(cid, bad, detail, *, warn=()):
        found = sorted(flags & set(bad))
        warned = sorted(flags & set(warn))
        add(cid, "fail" if found else "warn" if warned else "pass", {"flags": found + warned, **detail})

    def finish(record):
        record["stop"] = stop_reason(record, journal)
        if record["stop"] is not None and "S2" in record["stop"]["triggers"]:
            record["action"] = REVOKE
        if write:
            canonical.atomic_write_bytes(rdir / LIVE_CHECKS, runner._pretty(record))
        return record

    if run["status_hint"] == "not_started":
        code = closing.get("code")
        for i in range(1, 24):
            add(f"LC-{i:02d}", "na", {"not_started": run["not_started_reason"], "code": code})
        return finish({"schema_version": 1, "run_id": run_id, "status_hint": "not_started", "evidence_sha256": digest,
                       "not_started_code": code, "checks": checks, "flags": sorted(flags)})
    init = details.get("init") if isinstance(details.get("init"), dict) else None
    claude = host_launch["claude"]
    gate("LC-01", ("no_init_event", "init_unverified", "init_version_mismatch", "multiple_init_events",
                   "session_id_mismatch"),
         {"init_present": init is not None, "version": (init or {}).get("claude_code_version"),
          "pinned": host["version"]})
    gate("LC-02", ("init_tools_unexpected", "init_tools_unrecognized", "web_tools_in_init"),
         {"tools": (init or {}).get("tools"), "declared": claude["tools"]})
    gate("LC-03", ("init_permission_mode_mismatch",), {"permission_mode": (init or {}).get("permissionMode")})
    gate("LC-04", ("init_model_mismatch", "main_model_substituted"),
         {"init_model": (init or {}).get("model"), "models_seen": details.get("models_seen"),
          "model_usage": sorted(((result.get("usage") or {}).get("by_model") or {}))}, warn=("auxiliary_model_usage",))
    gate("LC-05", ("init_api_key_source_unexpected",), {"api_key_source": (init or {}).get("apiKeySource"),
                                                         "expected": host_launch["credential"]["expected_api_key_source"]})
    gate("LC-06", ("mcp_servers_present", "plugins_present", "init_skills_unexpected", "init_agents_unexpected"),
         {"builtin_plugins": (init or {}).get("builtin_plugins"), "skills": (init or {}).get("skills"),
          "agents": (init or {}).get("agents"), "skills_unexpected": (init or {}).get("skills_unexpected"),
          "agents_unexpected": (init or {}).get("agents_unexpected")})
    gate("LC-07", ("web_tools_in_init", "web_tool_used", "web_requests_reported"), {})
    gate("LC-08", ("host_auth_failed", "host_usage_limited"), {"assistant_errors": details.get("assistant_errors")})
    bash = details.get("bash") or {}
    gate("LC-09", ("shell_tool_failed",), {"bash": bash})
    custody = _custody_facts(sealed)
    if custody["internal_errors"]:
        flags.add("broker_internal_error")
    status = "fail" if "task_token_missing_in_shell" in flags else "pass" if custody["authenticated_operations"] \
        else "warn"
    add("LC-10", status, {"flags": sorted(flags & {"task_token_missing_in_shell"}), **custody})
    reports, _ = canonical.read_jsonl(sealed / "broker" / "client_env.jsonl")
    gate("LC-11", ("credential_visible_to_subject",), {"reports": len(reports),
                                                       "journal": closing.get("client_env")})
    redactions = _sealed_json(sealed, runner.REDACTIONS)
    gate("LC-12", ("credential_exposed", "credential_sweep_incomplete", "host_config_credential_shaped"),
         {"sweep": closing.get("credential_sweep"), "redactions": redactions or [],
          "host_config_credential_shaped": (closing.get("host_config") or {}).get("credential_shaped"),
          "quarantined": closing.get("quarantined_streams")})
    decisions, _ = canonical.read_jsonl(sealed / "proxy.jsonl")
    gate("LC-13", ("proxy_denied_connect", "proxy_owner_unknown", "proxy_upstream_error", "proxy_stop_failed"),
         {"summary": closing.get("proxy"), "logged": len(decisions),
          "by_attribution": {a: sum(1 for d in decisions if d.get("attribution") == a)
                             for a in ("owner", "other", "unknown")}})
    gate("LC-14", ("canary_in_transcript",), {"scan": closing.get("canary_scan")})
    receipts = sorted(p.relative_to(sealed).as_posix() for p in (sealed / "broker" / runner.RECEIPTS).rglob(
        "execution_state.json")) if (sealed / "broker" / runner.RECEIPTS).is_dir() else []
    gate("LC-15", ("kernel_fingerprint_mismatch", "interpreter_mismatch", "stage_worker_mismatch"),
         {"receipts": receipts})
    by_model = (result.get("usage") or {}).get("by_model") if isinstance(result.get("usage"), dict) else None
    rates, multipliers = cli_price_per_mtok(campaign_dir), cli_geo_multiplier(campaign_dir)
    lc16, cost_flags = _cost_facts(result, details, rates, multipliers, host["model"])
    lc16["ceiling"], ceiling_flags = _overshoot_facts(result, details, rates, multipliers, host["model"],
                                                      manifest["budget"]["usd_per_run"])
    flags |= cost_flags | ceiling_flags
    lc16["by_model_cost"] = {k: (v or {}).get("costUSD") for k, v in (by_model or {}).items()}
    lc16["cache_write_1h_tokens"] = details.get("cache_write_1h_tokens")
    verified = lc16["recomputed"] is not None or bool(lc16["pinned_share"])
    gate("LC-16", ("cost_recompute_mismatch", "cost_zero_with_usage", "cache_write_1h_reported",
                   "cost_overshoot_beyond_turn"), lc16,
         warn=("cost_unverified_auxiliary",) + (() if verified else ("cost_unverified",)))
    if not verified and checks[-1]["status"] == "pass":
        checks[-1]["status"] = "warn"
    add("LC-17", "warn" if "shell_snapshot_missing" in flags else "pass", {"snapshot": closing.get("shell_snapshot")})
    denials = closing.get("sandbox_denials") or {}
    add("LC-18", "warn" if "sandbox_denials_unavailable" in flags or (denials.get("count") or 0) else "pass",
        {"denials": denials})
    census_flags = ("survivors_after_kill", "census_incomplete", "ipc_residue", "subject_outlived_coordinator")
    gate("LC-19", census_flags, {"census": closing.get("census"),
                                 **({"remedy": CENSUS_REMEDY} if flags & set(census_flags) else {})})
    add("LC-20", "info", {"permission_denials": len(result.get("permission_denials") or [])})
    gate("LC-21", ("credential_persisted_keychain",), {"keychain": closing.get("keychain")})
    gate("LC-22", ("fast_mode_used", "main_model_substituted"), {"fast_mode": details.get("fast_mode")})
    add("LC-23", "info", {"subject_network_attempts": (closing.get("proxy") or {}).get("subject_clients", 0),
                          "host_config_keys": closing.get("host_config")})
    return finish({"schema_version": 1, "run_id": run_id, "status_hint": run["status_hint"], "evidence_sha256": digest,
                   "not_started_code": None, "checks": checks, "flags": sorted(flags)})


def stop_reason(checks, journal):
    """The stop rule a run's live checks and journal trigger (§4), or None: {rule, name, reason, triggers}. Fail
    closed (E-74): every flag not in OUTCOME_FLAGS triggers its STOP_RULES rule, or UNCLASSIFIED_RULE as
    "unclassified:<flag>"; every not_started code but STOP_CLOSURE_CODE triggers its NOT_STARTED_RULES rule, or
    UNCLASSIFIED_RULE; a live check that failed without any trigger of its own triggers UNCLASSIFIED_RULE; a lost
    launch is S7; a host auth failure beside a host-attributed proxy deny is isolation (S3), not auth (S1). The most
    severe rule wins (SEVERITY)."""
    flags = set(checks.get("flags") or [])
    triggers = {}
    for flag in sorted(flags - OUTCOME_FLAGS):
        rule = STOP_RULES.get(flag, UNCLASSIFIED_RULE)
        if flag == "host_auth_failed" and "proxy_denied_connect" in flags:
            rule = "S3"
        triggers.setdefault(rule, []).append(flag if flag in STOP_RULES else f"unclassified:{flag}")
    code = checks.get("not_started_code")
    if code is not None and code != STOP_CLOSURE_CODE:
        triggers.setdefault(NOT_STARTED_RULES.get(code, UNCLASSIFIED_RULE), []).append(f"not_started:{code}")
    elif code is None and checks.get("status_hint") == "not_started":
        triggers.setdefault(UNCLASSIFIED_RULE, []).append("not_started:without_code")
    covered = {f for fs in triggers.values() for f in fs}
    for check in checks.get("checks") or []:
        own = set((check.get("detail") or {}).get("flags") or []) if isinstance(check.get("detail"), dict) else set()
        if check.get("status") == "fail" and not own & covered:
            triggers.setdefault(UNCLASSIFIED_RULE, []).append(f"live_check_failed:{check.get('id')}")
    if any(r["state"] == "interrupted_crash" for r in journal):
        triggers.setdefault("S7", []).append("interrupted_crash")
    if not triggers:
        return None
    rule = next(r for r in SEVERITY if r in triggers)
    return {"rule": rule, "name": RULE_NAMES[rule], "reason": ", ".join(triggers[rule]),
            "triggers": {r: triggers[r] for r in SEVERITY if r in triggers}}


def evaluation_failed(run_id, exc) -> dict:
    """The stop of a sealed run whose live checks could not be evaluated: S7, fail closed (never a skipped rule)."""
    reason = f"live_checks_failed:{type(exc).__name__}"
    return {"rule": UNCLASSIFIED_RULE, "name": RULE_NAMES[UNCLASSIFIED_RULE], "reason": reason,
            "triggers": {UNCLASSIFIED_RULE: [reason]}, "error": f"{type(exc).__name__}: {exc}"[:500]}


def derive_stops(campaign_dir, *, write=True) -> list:
    """The stop rules of every sealed run of a live campaign, re-derived from its sealed evidence and journal (E-78):
    [{run_id, stop, action?}] in registry order. A run whose live checks raise is an S7 stop (evaluation_failed).
    run_campaign calls this before any launch, so a stop the coordinator lost between a seal and its stop.json (an
    interrupt, a crash, an exception in the checks) is never skipped on resume; preflight (PF-07) with write=False."""
    campaign_dir = Path(campaign_dir).resolve()
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    out = []
    for run in registry["runs"]:
        rid = run["run_id"]
        if not any(r["state"] == "sealed" for r in runner.read_journal(campaign_dir / "runs" / rid / "journal.jsonl")):
            continue
        try:
            checked = live_checks(campaign_dir, rid, write=write)
            entry = {"run_id": rid, "stop": checked["stop"]}
            if "action" in checked:
                entry["action"] = checked["action"]
        except Exception as exc:   # noqa: BLE001 - an evaluation that cannot run fails closed
            entry = {"run_id": rid, "stop": evaluation_failed(rid, exc)}
        out.append(entry)
    return out


# ---------------------------------------------------------------- the S10a go/no-go gate (E-92)

GO_NO_GO = "go_no_go.json"   # coordinator/: the recorded review of the first launched run, written once
GO_NO_GO_FIELDS = ("schema_version", "time_utc", "run_id", "evidence_sha256", "decision", "decided_by", "reason",
                   "lc16_status", "accepted_unverified_cost", "host_config", "host_state_files")
GO_DECISIONS = ("go", "no-go")


def first_launched_run(campaign_dir):
    """(run_id, sealed) of the first run in registry order whose journal records a launch, or (None, False)."""
    campaign_dir = Path(campaign_dir)
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    for run in registry["runs"]:
        states = {r["state"] for r in runner.read_journal(campaign_dir / "runs" / run["run_id"] / "journal.jsonl")}
        if "launched" in states:
            return run["run_id"], "sealed" in states
    return None, False


def read_go_no_go(campaign_dir):
    """coordinator/go_no_go.json (validated), or None. A malformed record fails closed."""
    path = Path(campaign_dir) / runner.COORDINATOR / GO_NO_GO
    if not os.path.lexists(path):
        return None
    require(path.is_file() and not path.is_symlink(), f"coordinator/{GO_NO_GO}: not a regular file")
    record = canonical.strict_load(path)
    require(isinstance(record, dict) and set(record) == set(GO_NO_GO_FIELDS) and record["schema_version"] == 1
            and record["decision"] in GO_DECISIONS and canonical.is_sha256(record["run_id"])
            and canonical.is_sha256(record["evidence_sha256"]) and isinstance(record["decided_by"], str)
            and record["decided_by"].strip() and isinstance(record["reason"], str) and record["reason"].strip(),
            f"coordinator/{GO_NO_GO}: not a go/no-go record ({list(GO_NO_GO_FIELDS)}); a human must repair it")
    return record


def go_no_go_problem(campaign_dir):
    """None when a real host's campaign may launch another run as far as S10a is concerned (E-92): nothing was launched
    yet (run 1 may launch), or the first launched run is sealed and a recorded ``go`` names exactly its run id and its
    sealed evidence. Otherwise why: the paid run 1 is the first run that authenticates, so what the zero-cost probes
    could not observe (the host's config and state after authentication, the real API's costs, geography and ceiling)
    is reviewed and signed before runs 2 to 8 (smoke-request.md S10a: ``cli.py go-no-go``)."""
    rid, sealed = first_launched_run(campaign_dir)
    if rid is None or not sealed:   # unsealed: a lost run 1, which `run` resumes (and stops, S7) before any launch
        return None
    record = read_go_no_go(campaign_dir)
    if record is None:
        return (f"S10a: run 1 ({rid}) was launched; no further run launches until its go/no-go review is recorded: "
                f"live-checks, then `cli.py go-no-go --campaign C --decision go --by NAME --reason TEXT` "
                "(smoke-request.md S10a)")
    evidence = runner.sealed_evidence(Path(campaign_dir) / "runs" / rid)
    if record["run_id"] != rid or record["evidence_sha256"] != evidence:
        return f"S10a: coordinator/{GO_NO_GO} does not name the first launched run {rid} and its sealed evidence"
    if record["decision"] != "go":
        return f"S10a: the recorded decision on run 1 ({rid}) is {record['decision']!r}"
    return None


def record_go_no_go(campaign_dir, *, decision, decided_by, reason, accept_unverified_cost=None) -> dict:
    """``cli.py go-no-go`` (S10a, E-92): record the review of the first launched run, once (written exclusively, like
    stop.json). A ``go`` is refused unless that run is sealed, its live checks (re-derived now and written) show no
    failed check and no stop, no stop is in place, LC-16 passed (the cost recompute verified against the measured
    rates, the ceiling held) or the operator names the recorded decision that accepts an unverified recompute
    (``accept_unverified_cost``; a failed LC-16 is never accepted), and the host's config holds no credential-shaped
    key name (``host_config_credential_shaped``, S2, is already a stop). The record keeps the host config's key names
    and the host-state file list the reviewer saw. A ``no-go`` is recorded whatever the checks show and writes a
    human stop (S8)."""
    require(decision in GO_DECISIONS, f"decision: one of {list(GO_DECISIONS)}")
    require(isinstance(decided_by, str) and decided_by.strip(), "decided_by: the reviewer's name is required")
    require(isinstance(reason, str) and reason.strip(), "reason: required")
    require(accept_unverified_cost is None or (isinstance(accept_unverified_cost, str)
                                               and accept_unverified_cost.strip()),
            "accept_unverified_cost: a recorded decision id, or None")
    campaign_dir = Path(campaign_dir).resolve()
    rid, sealed = first_launched_run(campaign_dir)
    require(rid is not None, "go-no-go: no run of this campaign was launched yet (S10 runs run 1 first)")
    require(sealed, f"go-no-go: the first launched run {rid} is not sealed; resume it first")
    require(read_go_no_go(campaign_dir) is None, f"go-no-go: coordinator/{GO_NO_GO} is already recorded")
    checks = live_checks(campaign_dir, rid)
    lc16 = next((c for c in checks["checks"] if c["id"] == "LC-16"), {"status": "na"})
    closing = next((r["details"] for r in reversed(runner.read_journal(campaign_dir / "runs" / rid / "journal.jsonl"))
                    if r["state"] in ("exited", "interrupted_crash", "not_started")), {})
    manifest_path = campaign_dir / "runs" / rid / "sealed" / runner.HOST_STATE_MANIFEST
    state = canonical.strict_load(manifest_path) if manifest_path.is_file() else {"files": []}
    if decision == "go":
        problems = []
        if checks["stop"] is not None:
            problems.append(f"run 1's live checks trigger {checks['stop']['rule']} ({checks['stop']['reason']})")
        failed = [c["id"] for c in checks["checks"] if c["status"] == "fail"]
        if failed:
            problems.append(f"run 1's live checks failed: {failed}")
        stop = runner.read_stop(campaign_dir)
        if stop is not None:
            problems.append(f"a stop is in place ({stop['rule']})")
        if lc16["status"] != "pass" and not (lc16["status"] == "warn" and accept_unverified_cost):
            problems.append(f"LC-16 is {lc16['status']}: the cost recompute is not verified against the measured "
                            "rates (for example an inference geography HP-13 did not measure); a go needs LC-16 pass, "
                            "or --accept-unverified-cost naming the recorded decision that accepts it")
        require(not problems, "go-no-go: refusing go: " + "; ".join(problems))
    record = {"schema_version": 1, "time_utc": runner.utc_now(), "run_id": rid,
              "evidence_sha256": runner.sealed_evidence(campaign_dir / "runs" / rid), "decision": decision,
              "decided_by": decided_by.strip(), "reason": reason.strip(), "lc16_status": lc16["status"],
              "accepted_unverified_cost": accept_unverified_cost if lc16["status"] != "pass" else None,
              "host_config": closing.get("host_config"),
              "host_state_files": [f.get("path") for f in state.get("files", []) if isinstance(f, dict)][:500]}
    require(runner.write_exclusive(campaign_dir / runner.COORDINATOR / GO_NO_GO, runner._pretty(record)),
            f"go-no-go: coordinator/{GO_NO_GO} was recorded meanwhile; nothing changed")
    if decision == "no-go":
        runner.record_stop(campaign_dir, run_id=rid, rule="S8", reason=f"S10a no-go: {reason.strip()}",
                           set_by=f"cli.py go-no-go ({decided_by.strip()})")
    return record


def live_checks_all(campaign_dir) -> list:
    """live_checks of every sealed run of a live campaign, in registry order."""
    campaign_dir = Path(campaign_dir).resolve()
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    out = []
    for run in registry["runs"]:
        journal = runner.read_journal(campaign_dir / "runs" / run["run_id"] / "journal.jsonl")
        if any(r["state"] == "sealed" for r in journal):
            out.append(live_checks(campaign_dir, run["run_id"]))
    return out


def _turn_bound(result, rates, multiplier, pinned):
    """An upper bound of one turn's cost for §5's worst case: the largest per-message input and cache tokens at the
    measured rates plus a full maxOutputTokens (modelUsage; MAX_OUTPUT_FALLBACK without it) at the output rate, x the
    geography multiplier; None without measured rates. Per-message output counts are placeholders in stream-json, so
    the output side is the ceiling, never an observed count."""
    rate = _rates_for(rates, pinned)
    if not isinstance(rate, dict) or not all(canonical.finite_number(rate.get(k)) for k in USAGE_KINDS.values()):
        return None
    model_usage = _result_model_usage(result) or {}
    maxima = [v.get("maxOutputTokens") for k, v in model_usage.items() if isinstance(v, dict)
              and claude_cli.same_model(k, pinned) and canonical.finite_number(v.get("maxOutputTokens"))]
    output = max(maxima) if maxima else MAX_OUTPUT_FALLBACK
    per = ((result.get("usage") or {}).get("per_message") or []) if isinstance(result.get("usage"), dict) else []
    inputs = [((m.get("input_tokens") or 0) * rate["input_tokens"]
               + (m.get("cache_creation_input_tokens") or 0) * rate["cache_creation_input_tokens"]
               + (m.get("cache_read_input_tokens") or 0) * rate["cache_read_input_tokens"]) / 1_000_000
              for m in per if isinstance(m, dict)]
    return (max(inputs, default=0.0) + output * rate["output_tokens"] / 1_000_000) * (multiplier or 1.0)


def costs(campaign_dir) -> dict:
    """§5 cost reconciliation from the sealed streams, the journal and HP-13's measured rates: per run the reported
    total, the sum of modelUsage costUSD, the recompute, the ceiling check (_overshoot_facts), tokens, turns, retried
    requests, subtype, terminal reason and the charge; the campaign's spend against its caps and the worst case
    G + (k+1+r)T (k runs charged the cap at unknown cost, r requests the host retried, whose partial responses
    total_cost_usd does not count, T one crossing turn: the larger of the largest observed average per turn and the
    per-turn bound of _turn_bound), the envelope every approval states (contracts.SMOKE_SPEND_ENVELOPE, E-94). USD is
    the CLI's own estimate: for a subscription token, quota usage."""
    campaign_dir = Path(campaign_dir).resolve()
    registry = canonical.strict_load(campaign_dir / campaign_manifest.REGISTRY)
    manifest = canonical.strict_load(campaign_dir / campaign_manifest.MANIFEST)
    budget, rates = manifest["budget"], cli_price_per_mtok(campaign_dir)
    multipliers, pinned = cli_geo_multiplier(campaign_dir), manifest["host"]["model"]
    rows, spent_usd, spent_s, unknown, per_turn, bound, retried = [], 0.0, 0.0, 0, 0.0, None, 0
    for run in registry["runs"]:
        rdir = campaign_dir / "runs" / run["run_id"]
        journal = runner.read_journal(rdir / "journal.jsonl")
        closing = next((r for r in reversed(journal) if r["state"] in ("exited", "interrupted_crash", "not_started")),
                       None)
        charge = (closing or {}).get("details", {}).get("charge")
        row = {"run_id": run["run_id"], "task_id": run["task_id"], "arm": run["arm"],
               "state": closing["state"] if closing else "unprocessed", "charge": charge, "checks": []}
        if charge and closing["state"] != "not_started":
            spent_usd += charge["usd"]
            spent_s += charge["seconds"]
            unknown += charge["usd_basis"] == "per_run_cap_unknown"
        result = _sealed_json(rdir / "sealed", "adapter_result.json") if (rdir / "sealed").is_dir() else None
        if result:
            details = result.get("details") or {}
            by_model = (result.get("usage") or {}).get("by_model") or {}
            reported = (details.get("cost_accounting") or {}).get("reported_total_cost_usd")
            summed = sum((v or {}).get("costUSD") or 0 for v in by_model.values()) if by_model else None
            facts, cost_flags = _cost_facts(result, details, rates, multipliers, pinned)
            ceiling, ceiling_flags = _overshoot_facts(result, details, rates, multipliers, pinned,
                                                      budget["usd_per_run"])
            turns = details.get("num_turns")
            retries = details.get("api_retries") if type(details.get("api_retries")) is int else 0
            retried += retries
            row.update(reported_total_cost_usd=reported, model_usage_cost_usd=summed,
                       recomputed_cost_usd=facts["recomputed"], recompute=facts, ceiling=ceiling,
                       main_loop_tokens=(result.get("usage") or {}).get("main_loop"), turns=turns,
                       api_retries=retries, subtype=details.get("result_subtype"),
                       terminal_reason=details.get("terminal_reason"))
            if canonical.finite_number(reported) and summed is not None and abs(summed - reported) > BREAKDOWN_TOLERANCE:
                row["checks"].append("cost_breakdown_mismatch (warn)")
            row["checks"] += sorted(cost_flags | ceiling_flags)
            if canonical.finite_number(reported) and reported > budget["usd_per_run"]:
                row["checks"].append(f"cost_over_run_cap (overshoot {reported - budget['usd_per_run']:.6f} USD)")
            if "fast_mode_used" in (details.get("flags") or []):
                row["checks"].append("fast_mode_used")
            if canonical.finite_number(reported) and isinstance(turns, int) and turns > 0:
                per_turn = max(per_turn, reported / turns)
            turn = _turn_bound(result, rates, facts["multiplier"], pinned)
            if turn is not None:
                bound = turn if bound is None else max(bound, turn)
        rows.append(row)
    t = max(per_turn, bound or 0.0)
    return {"runs": rows, "spent": {"usd": spent_usd, "seconds": spent_s},
            "caps": {k: budget[k] for k in ("usd_per_run", "seconds_per_run", "global_usd_cap", "global_seconds_cap")},
            "worst_case": {"formula": "G + (k+1+r)*T", "G": budget["global_usd_cap"], "k": unknown, "r": retried,
                           "T_estimate_usd": t, "T_average_usd": per_turn, "T_bound_usd": bound,
                           "usd": budget["global_usd_cap"] + (unknown + 1 + retried) * t,
                           "envelope": contracts.SMOKE_SPEND_ENVELOPE},
            "rates_per_mtok": rates, "geo_multiplier": multipliers,
            "residuals": ["partial responses of streams the CLI interrupted and retried (CLAUDE_CODE_MAX_RETRIES) are "
                          "billed by the API but not counted in total_cost_usd; the worst case adds one turn T per "
                          "retried request (r)",
                          "T_bound uses a full maxOutputTokens turn, not an observed one (per-message output counts "
                          "are placeholders in stream-json)"],
            "meaning": "USD are the pinned CLI's own estimates; for a subscription token they are quota usage, not "
                       "billed dollars (F12, F18)"}
