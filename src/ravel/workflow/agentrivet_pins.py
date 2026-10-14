"""Compatible external AgentRivet censuses and the no-subprocess generation guard.

The paper-first bridge runs the original external ReviewLoop. Its invariants
(a fresh Analyst, then per iteration one coder call followed by both reviews,
or, for a compile-gated commit, no reviews after a draft whose RAVEL-observed
compile failed) are checked against the commits recorded here. This module
records, as facts, the file SHA-256 census of each upstream commit the bridge
accepts. Nothing from the GPL source is copied: only commit identifiers, paths
and hashes.

The guard refuses process creation and file creation in the working directory
while original upstream code runs. It is one audit hook, installed once, and is
active only in the context that entered it. Nothing process-wide is patched.
"""
from __future__ import annotations

from contextlib import contextmanager
import contextvars
import os
import sys
import threading

DEFAULT_COMMIT = "e4d12eccb6aee546d993481c75576c0df4e2b037"

_SHARED = {
    "COPYING": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
    "README.md": "f1bfb773c1d1d26b20e2081da875d5e6dabfa84ff34d5267893cae00f3ced1ec",
    "agentrivet/__init__.py": "4af44c606e3c340909a9f5ee7ea997e80d15bc1fbdc6c9c382ee488ce9eb2d10",
    "agentrivet/analyst_agent.py": "4407fa28a3e77d178fcd66ecd41e39d0948c4fcb57f3ecbe284c054c96dbdcf7",
    "agentrivet/code_reviewer_agent.py": "3f57490cd2c47f66537c34723b115605206d377899722f742a3934ec07077f30",
    "agentrivet/coder_agent.py": "9fea8065c1908d30e1da80422279142bcc72df3874b4632b68467d101c6727af",
    "agentrivet/core.py": "11c2339b754dc8e779fbb40fae12f7ca0902a07d110abedba58a44ac9337d74b",
    "agentrivet/memory.py": "5be28f8013e68e437068c9dc16fe9e8b75b9855503e96646a0602cdabd0e3ffd",
    "agentrivet/physics_reviewer_agent.py": "47bac4d68e91e77d5831d39d35c04dd699edae27685a47aa68ff3a24782af723",
    "agentrivet/providers/anthropic_backend.py": "f7251378e5229fd48929e7cd52b846d26d51a17b4825e7f1518e22cd9f44c7af",
    "agentrivet/providers/google_backend.py": "3b7494a1092f428faa4b6be2f7db73c9ebd5f1561b8e2acdab8c85bbf69ebdbc",
    "agentrivet/providers/openai_backend.py": "e9b86a63c46a3d585350b92b7f0ad877b484b401576bd6ecf7aa28d4bcbb4671",
    "docs/code-structure.md": "6e7200d7fb6058547f5f40bd712e54e719672952a1e97ca3e146882c22c76df1",
    "pyproject.toml": "dd8007caa5e3a82b981d5257df05301f16a16df88dc26e4de69589fb1c7acc24",
}

# Accepted upstream commits. cebc8e9 differs from the tag only in cli.py,
# utils.py and the added CHANGELOG.md; its core, Memory and four role files are
# byte-identical to agent-rivet-0.2.0, and its core does not import utils.
# 89903d0 adds a compile gate inside ReviewLoop: its core imports utils (for
# detect_rivet) and build (build_routine, BuildResult). The bridge binds both
# touchpoints to RAVEL's observed compile probe (see compile_gate below).
COMPILE_GATED_COMMIT = "89903d02c3f5fa10e327d532da175a0e94382fc2"

ALLOWED = {
    DEFAULT_COMMIT: {
        "label": "agent-rivet-0.2.0 (tag, 2026-06-18)",
        "compile_gate": False, "analysis_id_in_prompts": False,
        "files": {**_SHARED,
                  "agentrivet/cli.py": "6a8371184854900cdd079f55a24f5f2ac4fc93afdb2d5333025df3b1a73c76ad",
                  "agentrivet/utils.py": "f125349d284cf6632923d36761730d66931a474689ead9daf631055220210a63"},
    },
    "cebc8e93a6c9cb48a23d07f5b2f6038613d260b7": {
        "label": "main cebc8e9 (2026-10-03; core and role files identical to the tag)",
        "compile_gate": False, "analysis_id_in_prompts": False,
        "files": {**_SHARED,
                  "CHANGELOG.md": "e7bff527f67804e7d475d55f428388e7c8d39e0d63cd577cb694e2807dfb3dd1",
                  "agentrivet/cli.py": "60466f6124894ba13ba96694ef3ab14edfc84a06acb916c84723b174e9f39673",
                  "agentrivet/utils.py": "3eab99f95b57f8bf89bcaa49f66479d148f888e82468613394a4da8de665cd68"},
    },
    COMPILE_GATED_COMMIT: {
        "label": "main 89903d0 (2026-10-10, compile gate inside ReviewLoop)",
        "compile_gate": True, "analysis_id_in_prompts": True,
        "files": {
            "CHANGELOG.md": "e7fea673103f23f1caa214a3bee4dee1f47d0c34fa252380341a5d87e50ac99e",
            "COPYING": "8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903",
            "README.md": "38a7873bfedbdd2c1d8fa66301987006e66a6d52f0b584e13d95d9b62a88c6ba",
            "agentrivet/__init__.py": "4af44c606e3c340909a9f5ee7ea997e80d15bc1fbdc6c9c382ee488ce9eb2d10",
            "agentrivet/analyst_agent.py": "4407fa28a3e77d178fcd66ecd41e39d0948c4fcb57f3ecbe284c054c96dbdcf7",
            "agentrivet/build.py": "6aa2b2a4d22dff7a0edd8fbbdddd2a855d163f7d5273ed948fd50795247f7c06",
            "agentrivet/cli.py": "aa6d3c0352ed84b8f8869c3f4618f6c5f4b6aab4e4a5e061c437deb262867301",
            "agentrivet/code_reviewer_agent.py": "e94dad563ab146125a7b4f87e73159fd84bb4a20aaf3ee9d46a9904aa9c55fc6",
            "agentrivet/coder_agent.py": "7fa8b8a57b391b69fb3c22a58552f203e8fd7771f378fc5d02a5161514135145",
            "agentrivet/core.py": "a003609ba231ebe2a283049ca9a29ddc10d4ae120e618546be6717681e059a2c",
            "agentrivet/memory.py": "319a5017cf4ccd6b2c1e9701c9f518ec49b9c51bb57c9932d7b80990d40fd0d6",
            "agentrivet/physics_reviewer_agent.py": "47bac4d68e91e77d5831d39d35c04dd699edae27685a47aa68ff3a24782af723",
            "agentrivet/providers/anthropic_backend.py": _SHARED["agentrivet/providers/anthropic_backend.py"],
            "agentrivet/providers/google_backend.py": _SHARED["agentrivet/providers/google_backend.py"],
            "agentrivet/providers/openai_backend.py": _SHARED["agentrivet/providers/openai_backend.py"],
            "agentrivet/utils.py": "8e2a3e35ee7146b050c2c4b0fcfa91da3b1f5aa42a5fe6c03560596f2ff1a317",
            "docs/code-structure.md": "ead1c00149e4ccd1de08e5c8e88d6c57cf85c34f149229437560631858f9b087",
            "pyproject.toml": "018934eaa23c3584e2139d168c2fa6d4c955ff4bd7ae5b7ca983308d29d76c06",
        },
    },
}

# Known incompatible commits, named so a refusal can say why. Entries carry
# "label", "reason" and "files" (path -> SHA-256 of the Python members).
REFUSED = {}

ROLE_FILES = {"core": "agentrivet/core.py", "analyst": "agentrivet/analyst_agent.py",
              "coder": "agentrivet/coder_agent.py", "code_reviewer": "agentrivet/code_reviewer_agent.py",
              "physics_reviewer": "agentrivet/physics_reviewer_agent.py", "memory": "agentrivet/memory.py",
              "build": "agentrivet/build.py"}


class UpstreamCensusRefused(ValueError):
    """The supplied upstream tree is not an allowed AgentRivet commit."""


class UpstreamExecutionRefused(RuntimeError):
    """Original upstream code tried to start a process or create a file in cwd."""


def allowlist_message():
    rows = "; ".join(f"{commit[:7]} {entry['label']}" for commit, entry in ALLOWED.items())
    return f"allowed AgentRivet upstream commits: {rows}"


def _python(files):
    return {k: v for k, v in files.items() if k.startswith("agentrivet/") and k.endswith(".py")}


def _matches(census, entry):
    files = entry["files"]
    return (_python(census) == _python(files)
            and all(files.get(path) == sha for path, sha in census.items()))


def admit_census(rows):
    """Return the allowed commit whose census the declared members match.

    ``rows`` is the bridge's declared member list (``path``/``sha256``) whose
    bytes the caller has already verified. Python members must equal one
    allowed commit exactly; every other declared member must carry that
    commit's hash.
    """
    census = {}
    for row in rows:
        if type(row) is not dict or set(row) != {"path", "sha256"}:
            raise UpstreamCensusRefused("AgentRivet census rows need exactly path and sha256")
        census[row["path"]] = row["sha256"]
    for commit, entry in ALLOWED.items():
        if _matches(census, entry):
            return commit
    for commit, entry in REFUSED.items():
        python = _python(census)
        if python and all(entry["files"].get(path) == sha for path, sha in python.items()):
            raise UpstreamCensusRefused(
                f"AgentRivet {commit[:7]} ({entry['label']}) is not supported: {entry['reason']}. "
                + allowlist_message())
    nearest = ALLOWED[DEFAULT_COMMIT]["files"]
    differ = sorted(p for p in set(_python(census)) | set(_python(nearest))
                    if census.get(p) != nearest.get(p))
    raise UpstreamCensusRefused(
        "AgentRivet source census matches no allowed upstream commit (members differing from "
        f"{DEFAULT_COMMIT[:7]}: {', '.join(differ) or 'non-Python members'}). " + allowlist_message())


def admit_member_pins(pins):
    """Admit loaded core/role/Memory pins: all from one allowed commit.

    ``pins`` maps a role key (see ROLE_FILES) to ``{'path', 'sha256'}``.
    Returns every allowed commit carrying exactly these bytes (the tag first);
    several commits can share identical core and role files.
    """
    if type(pins) is not dict or not pins or not set(pins) <= set(ROLE_FILES):
        raise UpstreamCensusRefused("AgentRivet core/role pins required")
    commits = [commit for commit, entry in ALLOWED.items()
               if all(type(pin) is dict and entry["files"].get(ROLE_FILES[key]) == pin.get("sha256")
                      for key, pin in pins.items())]
    if commits:
        return commits
    raise UpstreamCensusRefused("loaded AgentRivet core/role files match no allowed upstream commit. "
                                + allowlist_message())


def features(commit):
    """Loop facts of an allowed commit: in-loop compile gate, analysis ID in prompts."""
    entry = ALLOWED.get(commit)
    if entry is None:
        raise UpstreamCensusRefused(f"unknown AgentRivet commit {commit!r}. " + allowlist_message())
    return {"compile_gate": bool(entry.get("compile_gate")),
            "analysis_id_in_prompts": bool(entry.get("analysis_id_in_prompts"))}


# --------------------------------------------------------------- guard

_ACTIVE = contextvars.ContextVar("ravel_agentrivet_upstream_guard", default=None)
_SUSPENDED = contextvars.ContextVar("ravel_agentrivet_suspended_guard", default=None)
_INSTALL = threading.Lock()
_INSTALLED = False
_PROCESS_EVENTS = frozenset({"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork",
                             "os.forkpty", "os.spawn", "os.startfile", "_thread.start_new_thread"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class _Guard:
    __slots__ = ("label", "cwd", "violations")

    def __init__(self, label):
        self.label, self.cwd, self.violations = label, os.path.realpath(os.getcwd()), []


def _in_cwd(guard, path):
    if isinstance(path, int):
        return False
    try:
        target = os.path.abspath(os.fsdecode(path))
    except (TypeError, ValueError):
        return False
    parent = os.path.realpath(os.path.dirname(target))
    return parent in (guard.cwd, os.path.realpath(os.getcwd()))


def _refuse(guard, what):
    message = f"{what} refused while original AgentRivet code runs ({guard.label})"
    guard.violations.append(message)
    raise UpstreamExecutionRefused(message)


def _hook(event, args):
    guard = _ACTIVE.get()
    if guard is None:
        return
    if event in _PROCESS_EVENTS:
        _refuse(guard, "process or thread start " + event)
    elif event == "open" and len(args) >= 3:
        path, mode, flags = args[0], args[1], args[2]
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writes and _in_cwd(guard, path):
            _refuse(guard, f"file creation in the working directory ({os.fsdecode(path)})")
    elif event == "os.mkdir" and args and _in_cwd(guard, args[0]):
        _refuse(guard, f"directory creation in the working directory ({os.fsdecode(args[0])})")


def install():
    """Install the audit hook once per interpreter; inactive outside a guard."""
    global _INSTALLED
    with _INSTALL:
        if not _INSTALLED:
            sys.addaudithook(_hook)
            _INSTALLED = True


@contextmanager
def no_subprocess(label):
    """Run original upstream code with process and cwd-file creation refused.

    A refusal raises inside upstream code. If upstream code swallows it, the
    violation is still recorded and raised again when the block ends.
    """
    install()
    guard = _Guard(label)
    token = _ACTIVE.set(guard)
    try:
        yield guard
    finally:
        _ACTIVE.reset(token)
    if guard.violations:
        raise UpstreamExecutionRefused("; ".join(guard.violations))


@contextmanager
def ravel_service():
    """Suspend the guard for RAVEL's own provider dispatch inside upstream calls."""
    outer = _ACTIVE.get()
    active, suspended = _ACTIVE.set(None), _SUSPENDED.set(outer)
    try:
        yield
    finally:
        _SUSPENDED.reset(suspended)
        _ACTIVE.reset(active)


@contextmanager
def upstream_call():
    """Re-enter a suspended guard for an upstream callable used by a RAVEL service."""
    outer = _SUSPENDED.get()
    if outer is None:
        yield
        return
    token = _ACTIVE.set(outer)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active():
    return _ACTIVE.get() is not None
