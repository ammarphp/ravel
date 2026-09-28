"""Host adapter contract (slice design §9, §13): AdapterResult, Adapter and raw-stream helpers.

Standard library only. An adapter launches one host (the synthetic fake subject, the Claude
Code CLI or the Codex CLI) through an injected launcher with the ``isolation.launch``
signature, keeps the raw stdout/stderr bytes on disk as the authoritative record, and
normalizes the event stream without dropping anything: a line that is not UTF-8, not strict
JSON or not an object is reported in ``parse_errors`` with its line number and byte offset,
and parsing continues with the next line. A line that parses but whose fields have types the
adapter's model of the pinned host does not expect is kept as an ``unnormalized`` event and
reported in ``details['schema_errors']``. Unknown values are ``None``, never a guessed zero.

Validity (proposed §9 addition, pending the integration owner's agreement): every result
carries ``validity = {"ok", "invalidating"}``, derived by ``AdapterResult`` itself from
``details['flags']``. ``ok`` is false when any flag in ``INVALIDATING_FLAGS`` is present: the
run is then not a clean observation of the declared host configuration (web tools offered or
used, MCP servers or plugins loaded, a different session or host version than launched,
process-group survivors, records the adapter could not normalize, unlabeled synthetic records,
a synthetic fixture stream in a run labeled non-synthetic, a mocked host run without the
outer sandbox, or System V IPC objects a sandboxed launch left behind or could not account for). The
runner seals every invalidating flag in run.json ``validity_flags``, and the audit turns each one into
an integrity item, which makes the run's v1 ``unsupported_claim`` null (never false); that is all it
changes. The run's status, ``refusal_valid``, ``fidelity_error`` and the valid-completion reading are
still scored from its record (whether an invalidating flag should also null those is an open human
decision, decisions.md H-08). Every other flag is informational (status and cost facts the audit scores by
its own rules).

System V IPC residue (``details['launch']['ipc_residue']``, ``isolation.LaunchResult.ipc_residue``).
No Seatbelt rule stops a subject creating System V objects, which outlive it and whose existence a
later subject can probe, so the launcher lists them before and after a sandboxed launch and removes
what the launch left. The flag is conservative: a sandboxed launch is flagged ``ipc_residue``
(invalidating, so its ``unsupported_claim`` is null) whenever its launcher reports anything but an
empty residue, i.e. the subject created an object (even one the launcher then removed: the subject
used a cross-run channel), or the residue is unknown (``None``: the listing after the launch failed,
or a launcher that does not report it). An unsandboxed launch (profile None) is never listed and
never flagged. A launch_error is left to the runner, which knows whether the subject may have started.
The flag marks only the run that left the residue; a later run that could have probed an object the
launcher did not clear is not flagged (open: reader-side gap, slice design §8).
"""
from __future__ import annotations

import dataclasses
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..canonical import ContractError, finite_number, is_sha256, require, sha256_bytes, sha256_file, strict_loads

ADAPTERS = ("fake", "claude_cli", "codex_cli")
STATUS_HINTS = ("exited", "timeout", "launch_error")
COST_PROVENANCE = ("none_synthetic", "host_reported", "tokens_only")
COST_SEMANTICS = ("per_call", "cumulative", "unknown")
SANDBOX_MODES = ("seatbelt", "none_test_only")  # host configuration §4.2 ``sandbox``
# Variables of an orchestrating Claude session that must never reach a subject (Phase 0 host audit §1).
ORCHESTRATOR_ENV = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH")
ORCHESTRATOR_ENV_PREFIXES = ("CLAUDE_CODE_MESSAGING_",)
EXCERPT_BYTES = 120
SYNTHETIC_MARKER = "x_synthetic_fixture"  # header record type of the synthetic host-stream fixtures
INVALIDATING_FLAGS = frozenset({
    "web_tools_in_init",                      # claude: WebSearch/WebFetch offered in system/init tools
    "web_tool_used",                          # claude: a WebSearch/WebFetch tool_use
    "web_requests_reported",                  # claude: result usage reports web search/fetch requests
    "web_search_item_present",                # codex: a web_search item despite web_search="disabled"
    "mcp_servers_present", "plugins_present",  # claude: init lists MCP servers or plugins
    "init_skills_unexpected", "init_agents_unexpected",   # claude: init lists a skill or agent the pin does not ship
    "init_tools_unrecognized",                # claude: init tools missing or not names; web tools unverifiable
    "init_unverified",                        # claude: model activity without a system/init record
    "session_id_mismatch",                    # claude: init session differs from the launched/resumed one
    "init_version_mismatch",                  # claude: init claude_code_version differs from the verified binary
    "survivors_after_kill",                   # launcher census found process-group members after the kill
    "census_incomplete",                      # the sandbox census became unusable: only the group was searched
    "schema_errors",                          # a parsed record had field types the adapter cannot normalize
    "normalization_failed",                   # the stream parser failed; records kept unnormalized
    "unlabeled_synthetic_records",            # fake: a record not labeled synthetic by this executor
    "synthetic_marker_in_nonsynthetic_run",   # a synthetic fixture stream in a run labeled non-synthetic
    "sandbox_none_test_only",                 # a CLI host run without the outer sandbox (mocked hosts only)
    "ipc_residue",                            # a sandboxed launch left System V IPC objects, or its residue is unknown
    # Real-host live checks (smoke spec WI-7a): the run did not observe the declared host configuration.
    "init_model_mismatch",                    # claude: init model differs from the pinned model
    "main_model_substituted",                 # claude: an assistant message from another model, or a fallback event
    "init_tools_unexpected",                  # claude: init tools differ from the declared tool set
    "init_permission_mode_mismatch",          # claude: init permissionMode differs from the declared mode
    "init_api_key_source_unexpected",         # claude: init apiKeySource differs from the declared credential's
    "task_token_missing_in_shell",            # the task client reported its endpoint or token missing in the shell
})
SCHEMA_ERRORS = (TypeError, ValueError, KeyError, IndexError, AttributeError)


class HostDriftError(ContractError):
    """The installed host differs from its frozen identity (RUNTIME_12); the launch is refused."""


def validity_of(flags) -> dict:
    """``{"ok", "invalidating"}``: the sorted INVALIDATING_FLAGS present in ``flags``."""
    invalidating = sorted(set(flags) & INVALIDATING_FLAGS)
    return {"ok": not invalidating, "invalidating": invalidating}


@dataclass
class AdapterResult:
    """One host invocation. §9 fields plus ``details`` (host-specific facts §9 has no slot for)
    and ``validity`` (derived from ``details['flags']``; a supplied value must equal it)."""
    adapter: str
    status_hint: str
    exit_code: int | None
    wall_seconds: float | None
    raw_stdout: str
    raw_stderr: str
    events: list
    parse_errors: list
    session_ids: list
    final_text: str | None
    cost: dict
    usage: dict | None
    subagents: list
    permission_denials: list
    host_version: str | None
    synthetic: bool
    details: dict = field(default_factory=dict)
    validity: dict | None = None

    def __post_init__(self):
        require(self.adapter in ADAPTERS, f"adapter: unknown {self.adapter!r}")
        require(self.status_hint in STATUS_HINTS, f"status_hint: unknown {self.status_hint!r}")
        require(self.exit_code is None or type(self.exit_code) is int, "exit_code: int or null")
        require(self.wall_seconds is None or finite_number(self.wall_seconds), "wall_seconds: number or null")
        require(isinstance(self.cost, dict) and set(self.cost) == {"usd", "provenance", "semantics"},
                "cost: fields must be ['provenance', 'semantics', 'usd']")
        require(self.cost["usd"] is None or finite_number(self.cost["usd"]), "cost.usd: number or null")
        require(self.cost["provenance"] in COST_PROVENANCE, f"cost.provenance: {self.cost['provenance']!r}")
        require(self.cost["semantics"] in COST_SEMANTICS, f"cost.semantics: {self.cost['semantics']!r}")
        require(type(self.synthetic) is bool, "synthetic: bool required")
        require(self.adapter != "fake" or self.synthetic, "synthetic: the fake adapter is always synthetic")
        for name in ("events", "parse_errors", "session_ids", "subagents", "permission_denials"):
            require(isinstance(getattr(self, name), list), f"{name}: list required")
        require(isinstance(self.details, dict), "details: dict required")
        flags = self.details.get("flags", [])
        require(isinstance(flags, list) and all(isinstance(f, str) for f in flags), "details.flags: list of strings")
        derived = validity_of(flags)
        require(self.validity is None or self.validity == derived, "validity: must equal the verdict of details.flags")
        self.validity = derived

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


class Adapter:
    """Launch one host for one assignment. Subclasses set ``name`` and ``executor_id``."""
    name = None
    executor_id = None

    def run(self, *, prompt: str, workspace, env: dict, profile: str | None, timeout_s, out_dir) -> AdapterResult:
        raise NotImplementedError


def default_launcher():
    """``governance.isolation.launch`` (WP04), imported lazily so adapters import without it."""
    try:
        from .. import isolation
    except ImportError as exc:
        raise ContractError("no launcher injected and governance.isolation is unavailable") from exc
    return isolation.launch


def refuse_orchestrator_env(env: dict):
    for name in env:
        require(name not in ORCHESTRATOR_ENV and not name.startswith(ORCHESTRATOR_ENV_PREFIXES),
                f"env: orchestrator variable {name} must not reach a subject")


def merge_env(env: dict, extra: dict) -> dict:
    """Return env plus the adapter's variables; a conflicting caller value is refused."""
    for name, value in extra.items():
        require(env.get(name, value) == value, f"env: {name} conflicts with the adapter's isolation value")
    return {**env, **extra}


def assert_prompt_not_in_argv(argv, prompt: str):
    """The prompt travels on stdin only: never as an argv element, nor inside one."""
    require(isinstance(argv, list) and argv and all(isinstance(a, str) and "\0" not in a for a in argv),
            "argv: nonempty list of strings without NUL (no shell)")
    text = prompt.strip()
    require(all(a.strip() != text for a in argv), "argv: contains the prompt")
    require(len(text) < 16 or all(text not in a for a in argv), "argv: embeds the prompt")


def sandbox_flags(sandbox: str, profile) -> list:
    """Enforce the host configuration's ``sandbox`` against the launch profile; return implied flags.

    ``seatbelt`` requires a profile string (the launcher applies it). ``none_test_only`` is for
    mocked hosts: it takes no profile and marks the result invalid (``sandbox_none_test_only``).
    """
    if sandbox == "seatbelt":
        require(isinstance(profile, str) and profile.strip(),
                "profile: the outer sandbox profile is required (sandbox 'seatbelt'); "
                "sandbox='none_test_only' exists for mocked hosts only")
        return []
    require(sandbox == "none_test_only", f"sandbox: expected one of {list(SANDBOX_MODES)}")
    require(profile is None, "profile: sandbox 'none_test_only' launches without a profile")
    return ["sandbox_none_test_only"]


def profile_sha256(profile):
    return None if profile is None else sha256_bytes(profile.encode())


def fresh_dir(path, label, *, allowed=()):
    """Create a per-run directory; refuse one holding anything except the named entries.

    A named entry that is present must be a regular file with a single link: a symlink or a
    hardlink to the user's real credentials would let the host write through to them.
    """
    path = Path(path)
    require(path.is_absolute(), f"{label}: absolute path required")
    require(not path.is_symlink(), f"{label}: must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    extra = sorted(p.name for p in path.iterdir() if p.name not in allowed)
    require(not extra, f"{label}: must be fresh for this run; found {extra}")
    for name in allowed:
        entry = path / name
        if os.path.lexists(entry):
            info = entry.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                    f"{label}: {name} must be a regular file with one link (not a symlink or hardlink)")
    return path


def refuse_user_home_dir(path, name, label):
    """Refuse the user's real host configuration directory (``~/.claude``, ``~/.codex``) or a parent of it."""
    path = Path(path).expanduser().resolve()
    real = (Path.home() / name).resolve()
    require(path != real and real not in path.parents and path not in real.parents,
            f"{label}: must not be, contain or lie inside {real}")


# ---------------------------------------------------------------- host identity (RUNTIME_12)

def version_token(text: str, pattern: str):
    match = re.search(pattern, text)
    return match.group(1) if match else None


def verify_host(executable, *, expected_version: str, expected_sha256: str, version_pattern: str,
                env_for=None, timeout_s=30) -> dict:
    """Check the pinned binary's bytes and ``--version`` against the frozen identity.

    Raises HostDriftError (never launches the host) on any mismatch. ``env_for(tmpdir)`` builds
    the minimal environment for the ``--version`` probe; the probe runs in a throwaway directory
    so it cannot seed a per-run configuration directory. A replacement between this check and
    the launch is not excluded (time-of-check race); the frozen hash is recorded either way.
    """
    require(isinstance(expected_version, str) and expected_version.strip(), "expected_version: required")
    require(is_sha256(expected_sha256), "expected_sha256: expected SHA-256")
    path = Path(executable)
    require(path.is_absolute(), "executable: absolute path required")
    if path.is_symlink():
        raise HostDriftError(f"executable {path} is a symlink; pin the versioned binary path")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise HostDriftError(f"executable {path} is missing or not executable")
    observed_sha = sha256_file(path)
    if observed_sha != expected_sha256:
        raise HostDriftError(f"executable sha256 {observed_sha} differs from frozen {expected_sha256}")
    with tempfile.TemporaryDirectory(prefix="ravel-host-version-") as tmp:
        env = env_for(tmp) if env_for else {"PATH": "/usr/bin:/bin", "HOME": tmp}
        try:
            proc = subprocess.run([str(path), "--version"], cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=timeout_s, close_fds=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HostDriftError(f"executable {path} --version failed: {exc}") from exc
    text = proc.stdout.decode("utf-8", "replace").strip()
    observed = version_token(text, version_pattern)
    if proc.returncode != 0 or observed != expected_version:
        raise HostDriftError(f"host version {observed!r} (exit {proc.returncode}, output {text[:80]!r}) "
                             f"differs from frozen {expected_version!r}")
    return {"executable": str(path), "sha256": observed_sha, "version": observed, "version_output": text}


# ---------------------------------------------------------------- launch and raw capture

@dataclass
class Launched:
    status_hint: str
    exit_code: int | None
    wall_seconds: float | None
    stdout_path: Path
    stderr_path: Path
    stdin_sha256: str
    launch: dict
    sandboxed: bool = False   # launched under a Seatbelt profile (its launcher lists System V IPC objects)


def launch_host(launcher, argv, *, cwd, env, profile, timeout_s, out_dir, stdin_bytes: bytes) -> Launched:
    """Run argv through the launcher with the prompt bytes as stdin; raw streams go to out_dir.

    out_dir is coordinator-owned, must lie outside the subject workspace (``cwd``) and must not
    already hold raw streams (no overwrite). A launcher failure (OSError, ContractError/ValueError,
    SubprocessError) becomes ``launch_error`` with the message appended to the raw stderr file;
    other exceptions propagate.
    """
    require(isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv), "argv: list of str")
    require(finite_number(timeout_s) and timeout_s > 0, "timeout_s: positive number required")
    out_dir, workspace = Path(out_dir), Path(cwd).resolve()
    resolved = out_dir.resolve()
    require(resolved != workspace and workspace not in resolved.parents,
            f"out_dir: raw streams must stay outside the subject workspace {workspace}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout, stderr, stdin = out_dir / "stdout.jsonl", out_dir / "stderr.txt", out_dir / "stdin.txt"
    for path in (stdout, stderr, stdin):
        require(not path.exists() and not path.is_symlink(), f"refusing to reuse {path}")
    stdin.write_bytes(stdin_bytes)
    stdin.chmod(0o400)
    try:
        result = launcher(list(argv), cwd=str(cwd), env=dict(env), profile=profile, timeout_s=timeout_s,
                          stdout_path=str(stdout), stderr_path=str(stderr), stdin_path=str(stdin))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        with open(stderr, "ab") as handle:
            handle.write(f"launch_error: {type(exc).__name__}: {exc}\n".encode())
        stdout.touch()
        return Launched("launch_error", None, None, stdout, stderr, sha256_bytes(stdin_bytes),
                        {"error": f"{type(exc).__name__}: {exc}"}, profile is not None)
    for path in (stdout, stderr):
        path.touch()
    survivors, residue = getattr(result, "survivors", None), getattr(result, "ipc_residue", None)
    launch = {"timed_out": bool(result.timed_out), "killed": getattr(result, "killed", None),
              "survivors": list(survivors) if isinstance(survivors, (list, tuple, set)) else survivors,
              "census_complete": getattr(result, "census_complete", None),
              # a list the launcher reported (entries copied), else None: unknown, never guessed empty
              "ipc_residue": [dict(e) if isinstance(e, dict) else repr(e) for e in residue]
              if isinstance(residue, (list, tuple)) else None}
    return Launched("timeout" if result.timed_out else "exited", result.exit_code, result.wall_seconds,
                    stdout, stderr, sha256_bytes(stdin_bytes), launch, profile is not None)


def ipc_residue_flagged(launch: dict) -> bool:
    """Whether a sandboxed launch's reported System V IPC residue invalidates its run (module docstring): the
    launcher reported something other than an empty list (objects left, even if removed, or unknown)."""
    return launch.get("ipc_residue") != []


def parse_jsonl(data: bytes):
    """Return ([(line, object)], [error]) for JSONL bytes without dropping any line.

    Blank lines (JSON whitespace only: space, tab, CR) carry no data and are skipped. Every
    other line either parses strictly (duplicate keys and NaN/Infinity rejected) to a JSON
    object or yields one error record {line, offset, bytes, sha256, truncated, error, excerpt};
    ``truncated`` marks a final line without a terminating newline (a host that exited mid-record).
    """
    records, errors = [], []
    lines = data.split(b"\n")
    offset = 0
    for number, raw in enumerate(lines, start=1):
        start, offset = offset, offset + len(raw) + 1
        body = raw[:-1] if raw.endswith(b"\r") else raw
        if not body.strip(b" \t\r"):
            continue
        try:
            value = strict_loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError(f"expected a JSON object, got {type(value).__name__}")
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            errors.append({"line": number, "offset": start, "bytes": len(raw), "sha256": sha256_bytes(raw),
                           "truncated": number == len(lines), "error": f"{type(exc).__name__}: {exc}",
                           "excerpt": raw[:EXCERPT_BYTES].decode("utf-8", "backslashreplace")})
            continue
        records.append((number, value))
    return records, errors


@dataclass
class StreamCapture:
    records: list
    parse_errors: list
    facts: dict


def capture_stream(stdout_path, stderr_path) -> StreamCapture:
    """Parse the raw stdout file and record both raw files' digests; the files stay untouched."""
    data = Path(stdout_path).read_bytes()
    records, errors = parse_jsonl(data)
    facts = {"raw_stdout_sha256": sha256_bytes(data), "raw_stdout_bytes": len(data),
             "raw_stderr_sha256": sha256_file(stderr_path), "raw_stderr_bytes": Path(stderr_path).stat().st_size,
             "unterminated_final_line": bool(data) and not data.endswith(b"\n")}
    return StreamCapture(records, errors, facts)


def event(line, kind, obj, *, session_id=None, parent_id=None) -> dict:
    """Normalized event: the parsed object is kept whole under ``data``."""
    return {"line": line, "kind": kind, "type": obj.get("type") if isinstance(obj.get("type"), str) else None,
            "session_id": session_id, "parent_id": parent_id, "data": obj}


def number_or_none(value):
    return value if finite_number(value) and type(value) is not bool else None


def str_or_none(value):
    """Only a string is used as an identifier (a dict key or set member); anything else is unknown."""
    return value if isinstance(value, str) else None


def schema_error(line, exc) -> dict:
    return {"line": line, "error": f"{type(exc).__name__}: {exc}"}


def guarded_parse(parse, records, **kwargs) -> dict:
    """Run a stream parser after the host ran; a parser failure must not lose the result.

    The parsers catch field-type drift per record (``schema_errors``). Anything that still
    escapes them keeps every record as an ``unnormalized`` event and invalidates the run
    (``normalization_failed``) instead of raising after the host has already run and spent.
    """
    try:
        return parse(records, **kwargs)
    except Exception as exc:  # deliberate catch-all: the raw stream is on disk and the run is invalidated
        return {"events": [event(line, "unnormalized", obj) for line, obj in records], "session_ids": [],
                "final_text": None, "cost": None, "usage": None, "subagents": [], "permission_denials": [],
                "flags": ["normalization_failed"], "details": {"normalization_error": f"{type(exc).__name__}: {exc}"}}


def base_fields(launched: Launched, capture: StreamCapture) -> dict:
    """AdapterResult fields shared by every adapter, and the common ``details`` entries."""
    details = {"launch": launched.launch, "stdin_sha256": launched.stdin_sha256, **capture.facts}
    flags = []
    if launched.launch.get("survivors"):
        flags.append("survivors_after_kill")
    if launched.launch.get("census_complete") is False:
        flags.append("census_incomplete")
    if launched.sandboxed and launched.status_hint != "launch_error" and ipc_residue_flagged(launched.launch):
        flags.append("ipc_residue")   # a launch_error's residue is judged by the runner, which knows if it started
    if capture.parse_errors:
        flags.append("parse_errors")
    return {"status_hint": launched.status_hint, "exit_code": launched.exit_code,
            "wall_seconds": launched.wall_seconds, "raw_stdout": str(launched.stdout_path),
            "raw_stderr": str(launched.stderr_path), "parse_errors": capture.parse_errors,
            "details": details, "flags": flags}
