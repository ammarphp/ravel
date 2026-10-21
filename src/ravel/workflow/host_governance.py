"""Host governance records: gates in code for every host, with or without hooks.

- `development_prompt` tells the prompt router that a prompt is a development request
  (repository work), so it never routes it as a physics request (R-50 item 3, S1-14).
- `enforcement_surface_sha256` fingerprints the enforcement surface (hook table, hook scripts
  and gate modules). `record_checkin1_surface` keeps the CHECK-IN 1 fingerprint in the run.
- `pre_execution_guards` names what checked commands before they ran on this host:
  `host-hooks` (Claude Code with the governance hooks wired), `broker` (a custody-recorded
  worker session) or `none` (a host without hooks: only the gates in code apply).
- `raw_launch_errors` is the raw-launch invariant: generation output without a launch-journal
  entry bound to an approval makes delivery refuse. It defers to the `raw_launch` provider;
  an absent provider refuses delivery.
- `enforcement_record` is the delivery enforcement record.

Hook governance itself covers Claude Code only; see docs/workflow/hooks.md.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
from typing import Callable

# --------------------------------------------------------------------------- #
#  Development prompts (the router must stay silent on them)
# --------------------------------------------------------------------------- #

# One strong signal is enough: these phrases describe work on the repository itself.
_STRONG = {
    "worktree": re.compile(r"\bworktrees?\b|\bgit\s+(?:checkout|branch|rebase|merge|commit|push|stash|diff|log|worktree)\b", re.I),
    "brief": re.compile(r"\bacceptance (?:tests?|criteria)\b|\bowns \(may edit\)|\bmust not edit\b"
                        r"|\bstop conditions\b|\bcompletion record\b|\bstream brief\b|\bwork package\b"
                        r"|\bdevelopment (?:request|session|brief|task)\b", re.I),
    "dev_task": re.compile(r"\b(?:refactor\w*|typo|pytest|unit tests?|regression tests?|lint(?:er|ing)?|"
                           r"traceback|stack trace|pre-commit|code review|merge conflict|docstrings?|"
                           r"README|CHANGELOG|pull request)\b", re.I),
}
# Weak signals need a second, different one.
_WEAK = {
    "source_path": re.compile(r"(?:^|[\s`'\"(])(?:src|tests|scripts|docs|\.claude|\.codex|\.gemini|\.github)/[\w./*-]+"),
    "source_file": re.compile(r"\b[\w-]+\.(?:py|sh|toml|ya?ml|json)\b"),
    "branch_name": re.compile(r"\b(?:release|feature|fix|dev)/[\w.-]+"),
    "code_verb": re.compile(r"\b(?:implement|fix|debug|patch)\s+(?:the\s+)?(?:bug|hook|function|module|class|test|cli|command|script|code)\b", re.I),
}


def development_signals(prompt):
    """The development signals present in a prompt, strong ones first."""
    text = prompt or ""
    strong = [name for name, rx in _STRONG.items() if rx.search(text)]
    weak = [name for name, rx in _WEAK.items() if rx.search(text)]
    return strong, weak


def development_prompt(prompt):
    """True when the prompt is a development request rather than a physics request."""
    strong, weak = development_signals(prompt)
    return bool(strong) or len(weak) >= 2


def conversational_reply(prompt):
    """A short reply inside an ongoing session ("yes", "go ahead", "thanks"): never a new request.

    An explicit "Initiate:" request is never a reply, however short.
    """
    text = (prompt or "").strip()
    return len(text.split()) < 4 and not text.lower().startswith("initiate")


# --------------------------------------------------------------------------- #
#  Enforcement surface
# --------------------------------------------------------------------------- #

GATE_MODULES = ("workflow/host_gate.py", "workflow/host_governance.py", "workflow/active_run.py",
                "workflow/site_tools.py", "data/site_tools/*.json", "data/agent_surface/hooks.json",
                "data/checkin/sections.json", "workflow/science.py", "validation/validate_checkin.py",
                "workflow/launch_authorization.py", "workflow/workflow_state.py",
                "workflow/stop_dispatch.py", "workflow/decision_gate.py", "workflow/raw_launch.py",
                "workflow/transport_receipt.py", "workflow/transport_registry.py", "workflow/cli_agent_host.py",
                "workflow/agent_host.py", "workflow/provider_transport.py",
                "data/transports/*.json", "data/gates/providers.json",
                "validation/validate_run_state.py", "validation/validate_task_contract.py",
                "workflow/architecture_receipt.py")
HOST_TABLES = (".claude/settings.json",)
# Each extension takes the project (None for the installed package) and returns {label: path};
# an optional extension.metadata(project) adds fields to the CHECK-IN 1 surface row.
SURFACE_EXTENSIONS: tuple[Callable[[Path | None], dict[str, Path]], ...] = ()
CHECKIN1_SURFACE = "logs/enforcement-surface.jsonl"


def digest(value):
    """The shared digest of a JSON value."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _package_dir():
    return Path(__file__).resolve().parents[1]


def surface_files(project=None):
    """{label: path} of the enforcement surface that exists on this host."""
    files = {}
    if project is not None:
        project = Path(project)
        for rel in HOST_TABLES:
            if (project / rel).is_file():
                files[rel] = project / rel
        hooks = project / ".claude/hooks"
        if hooks.is_dir():
            for path in sorted(hooks.glob("*.sh")):
                files[".claude/hooks/" + path.name] = path
        for host in (".claude", ".codex", ".gemini"):
            for path in sorted((project / host).rglob("ravel-gate.sh")):
                if path.is_file():
                    files[str(path.relative_to(project))] = path
    package = _package_dir()
    for pattern in GATE_MODULES:
        for path in sorted(package.glob(pattern)):
            if path.is_file():
                files["ravel/" + str(path.relative_to(package))] = path
    for extension in SURFACE_EXTENSIONS:
        for label, path in extension(project).items():
            if label in files and Path(path) != Path(files[label]):
                raise ValueError("duplicate enforcement surface label: " + label)
            if Path(path).is_file():
                files[label] = Path(path)
    return files


def enforcement_surface(project=None):
    """{label: sha256} over the enforcement surface."""
    out = {}
    for label, path in surface_files(project).items():
        out[label] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return out


def enforcement_surface_sha256(project=None):
    return digest(enforcement_surface(project))


def hook_table_wired(project):
    """Whether the project's Claude Code table wires the pre-execution Bash guard."""
    try:
        table = json.loads((Path(project) / ".claude/settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    for block in (table.get("hooks") or {}).get("PreToolUse") or []:
        for hook in block.get("hooks") or []:
            if "pretooluse-bash.sh" in str(hook.get("command", "")):
                return True
    return False


def host_name(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get("CLAUDECODE") == "1" or environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    return "unknown"


def _broker_records_session(project, environ):
    """Broker custody, not an environment declaration, establishes broker use.

    The broker worker-receipts ledger pins the worker receipt carrying its session id.
    Until that producer is installed and a matching receipt exists, report none.
    """
    session = environ.get("RAVEL_SESSION_ID") or environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        return False
    try:
        from . import active_run
        broker = importlib.import_module("ravel.workflow.broker")
        rd = active_run.resolve(session, os.getcwd(), project)
        if rd is None:
            return False
        for row in broker.ledger(rd, "worker-receipts"):
            pin = row["record"]["pin"]
            path = broker.confined(rd, pin["path"])
            if broker.sha(path) != pin["sha256"]:
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if receipt.get("session_id") == session:
                return True
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return False
    return False


def pre_execution_guards(project=None, environ=None):
    """host-hooks | broker | none, derived from host registration and custody evidence."""
    environ = os.environ if environ is None else environ
    host_emitted = environ.get("CLAUDECODE") == "1" or environ.get("CLAUDE_CODE_SESSION_ID")
    if host_emitted and project is not None and hook_table_wired(project):
        # A wired table whose hooks a settings file switches off guards nothing.
        if not any(row["code"] == "hooks_disabled" for row in settings_findings(project, environ)):
            return "host-hooks"
    return "broker" if _broker_records_session(project, environ) else "none"


def project_root(rundir=None):
    """The project whose hook table governs a run: CLAUDE_PROJECT_DIR, the source checkout, or cwd."""
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(os.environ["CLAUDE_PROJECT_DIR"])
    from ravel.paths import repository_root
    for start in ([rundir] if rundir is not None else []) + [None]:
        try:
            found = repository_root(start) if start is not None else repository_root()
        except (OSError, ValueError):
            found = None
        if found is not None:
            return Path(found)
    return Path.cwd()


# --------------------------------------------------------------------------- #
#  Host integrity: detection on unrestricted hosts, never the boundary
# --------------------------------------------------------------------------- #
# A same-user process can switch a host's hooks off (``disableAllHooks``), inject variables
# into hook processes through a settings ``env`` table, redirect the hook runtime to another
# interpreter or package copy, drop the workflow-manager guard, release a run registration
# or break the gate module so a hook fails. RAVEL notices these at its next call, records
# them in the per-user host ledger and labels every delivery of a run the controller does
# not own NOT GOVERNED. A host the agent controls can undo a change after a check; the
# controller boundary (workers with no shell and no write access) is what holds.

NOT_GOVERNED = "NOT GOVERNED"
SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")
USER_SETTINGS_FILES = ("settings.json", "settings.local.json")
HOOK_RUNTIME = ".ravel/hook-runtime.sh"
HOOK_RUNTIME_LOCAL = ".ravel/agent-surface.local.json"
_LOCAL_KEYS = {"schema_version", "python", "guard_approval", "pythonpath"}
_RUNTIME_HEADER = "# Local runtime settings; never commit this file."
_RUNTIME_PYTHON = re.compile(r'if \[ -z "\$\{RAVEL_PYTHON:-\}" \]; then RAVEL_PYTHON=(.+); fi')
_RUNTIME_PATH = re.compile(r"export PYTHONPATH=(.+)\$\{PYTHONPATH:\+:\$PYTHONPATH\}")
# Variables a settings file must not inject into hook and session processes.
GUARDED_ENVIRONMENT = ("RAVEL_PYTHON", "RAVEL_ROOT", "RAVEL_STATE_DIR", "RAVEL_WORK_ROOT",
                       "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH",
                       "RAVEL_AGENT_TRIPWIRE", "RAVEL_AGENT_TRIPWIRE_RECORD", "RAVEL_TRANSPORT_PATH",
                       "RAVEL_PROTECTED_CARD_ROOT")
HOST_LEDGER = "host-integrity/events.jsonl"
# Event kinds the shell hooks and RAVEL calls append to the host ledger.
EVENT_KINDS = ("hook_failure", "registration_released", "stop_unresolved", "observed", "surface_installed")


def _finding(code, detail, path=None):
    return {"code": code, "detail": detail, **({"path": path} if path else {})}


def installed_source():
    """The directory that holds the RAVEL package this process runs (a checkout's ``src`` or site-packages)."""
    return _package_dir().parent


def _same(left, right):
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except (OSError, ValueError, RuntimeError, TypeError):
        return False


def user_settings_dir(environ=None):
    """The host's user-level settings directory (``CLAUDE_CONFIG_DIR`` or ``~/.claude``)."""
    environ = os.environ if environ is None else environ
    configured = environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _settings_paths(project, environ=None):
    paths = [(rel, Path(project) / rel) for rel in SETTINGS_FILES] if project is not None else []
    user = user_settings_dir(environ)
    paths += [("~/" + user.name + "/" + name, user / name) for name in USER_SETTINGS_FILES]
    return paths


def settings_findings(project, environ=None):
    """Settings tables that disable every hook, inject guarded variables or cannot be read."""
    found = []
    for label, path in _settings_paths(project, environ):
        if not path.exists() and not path.is_symlink():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            found.append(_finding("settings_unreadable", f"{label} cannot be read as JSON", label))
            continue
        if type(document) is not dict:
            found.append(_finding("settings_unreadable", f"{label} is not a JSON object", label))
            continue
        if document.get("disableAllHooks"):
            found.append(_finding("hooks_disabled", f"{label} disables every hook (disableAllHooks)", label))
        env = document.get("env")
        names = sorted(set(env) & set(GUARDED_ENVIRONMENT)) if type(env) is dict else []
        if names:
            found.append(_finding("settings_environment",
                                  f"{label} sets {', '.join(names)} for hook and session processes", label))
    return found


def runtime_findings(project):
    """Hook runtime files that differ from what the installer writes, or load another package copy."""
    if project is None:
        return []
    found = []
    source = installed_source()
    path = Path(project) / HOOK_RUNTIME
    if path.exists() or path.is_symlink():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            lines = None
        python = _RUNTIME_PYTHON.fullmatch(lines[1]) if lines and len(lines) > 1 else None
        package = _RUNTIME_PATH.fullmatch(lines[3]) if lines and len(lines) == 4 else None
        canonical = (path.is_file() and not path.is_symlink() and lines is not None and len(lines) in (3, 4)
                     and lines[0] == _RUNTIME_HEADER and python is not None and lines[2] == "export RAVEL_PYTHON"
                     and (len(lines) == 3 or package is not None))
        if not canonical:
            found.append(_finding("hook_runtime_modified", f"{HOOK_RUNTIME} differs from the runtime the "
                                  "installer writes; hooks source it before every guard", HOOK_RUNTIME))
        else:
            import shlex
            try:
                interpreter = shlex.split(python.group(1))
                packages = shlex.split(package.group(1)) if package else []
            except ValueError:
                interpreter, packages = [], [""]
            if len(interpreter) != 1 or not Path(interpreter[0]).is_absolute():
                found.append(_finding("hook_runtime_modified", f"{HOOK_RUNTIME} names no absolute interpreter",
                                      HOOK_RUNTIME))
            if packages and (len(packages) != 1 or not _same(packages[0], source)):
                found.append(_finding("hook_runtime_package", f"{HOOK_RUNTIME} loads RAVEL from "
                                      f"{packages[0]!r}, not the installed {source}", HOOK_RUNTIME))
    path = Path(project) / HOOK_RUNTIME_LOCAL
    if path.exists() or path.is_symlink():
        try:
            local = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            local = None
        if (type(local) is not dict or set(local) - _LOCAL_KEYS or not isinstance(local.get("python"), str)
                or not Path(local["python"]).is_absolute()):
            found.append(_finding("hook_runtime_modified", f"{HOOK_RUNTIME_LOCAL} differs from the settings the "
                                  "installer writes", HOOK_RUNTIME_LOCAL))
        elif local.get("pythonpath") is not None and not _same(local["pythonpath"], source):
            found.append(_finding("hook_runtime_package", f"{HOOK_RUNTIME_LOCAL} loads RAVEL from "
                                  f"{local['pythonpath']!r}, not the installed {source}", HOOK_RUNTIME_LOCAL))
    return found


def wms_guard_findings(project):
    """A project whose policy requires the workflow manager but whose hook table lacks its guard."""
    if project is None:
        return []
    from . import agent_surface
    try:
        required = agent_surface._wms_required(project)
    except (OSError, ValueError) as exc:
        return [_finding("workflow_policy_unreadable", f"workflow policy cannot be read: {exc}")]
    if not required:
        return []
    commands = []
    for _label, path in _settings_paths(project)[:len(SETTINGS_FILES)]:
        try:
            table = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            continue
        for group in ((table.get("hooks") or {}).get("PreToolUse") or []) if type(table) is dict else []:
            commands += [str(hook.get("command", "")) for hook in (group.get("hooks") or []) if type(hook) is dict]
    if any(agent_surface.GUARD_MARK in command for command in commands):
        return []
    return [_finding("wms_guard_absent", "the workflow policy requires the workflow manager and the host's hook "
                     "table has no execution guard (installed with --no-wms-guard, or removed)",
                     ".claude/settings.json")]


def host_findings(project=None, environ=None):
    """Every switch-off or redirection RAVEL can observe on this host now."""
    return settings_findings(project, environ) + runtime_findings(project) + wms_guard_findings(project)


def host_ledger_path():
    from .active_run import state_dir
    return state_dir() / HOST_LEDGER


def record_host_event(kind, **fields):
    """Append one event to the per-user host ledger; never raises (detection must not block work)."""
    if kind not in EVENT_KINDS:
        raise ValueError("unknown host event kind: " + str(kind))
    from datetime import datetime, timezone
    row = {"schema_version": 1, "kind": kind,
           "utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           **{key: (str(value) if isinstance(value, Path) else value) for key, value in fields.items()}}
    try:
        path = host_ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    except OSError:
        return None
    return row


def _well_formed(row):
    """A ledger row with the field types RAVEL and its hooks write; any other row is skipped."""
    if type(row) is not dict or row.get("kind") not in EVENT_KINDS:
        return False
    if any(row.get(key) is not None and not isinstance(row[key], str)
           for key in ("session", "rundir", "project", "hook", "source", "utc")):
        return False
    codes = row.get("codes")
    return codes is None or (isinstance(codes, list) and all(isinstance(code, str) for code in codes))


def host_events(*, project=None, rundir=None, sessions=()):
    """Ledger events tied to a run, its sessions or (when no run is given) a project."""
    try:
        lines = host_ledger_path().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    run = str(Path(rundir).resolve()) if rundir is not None else None
    sessions = {s for s in sessions if s}
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not _well_formed(row):
            continue
        tied =(run is not None and row.get("rundir") and _same(row["rundir"], run)) or \
            (row.get("session") in sessions)
        if run is None and project is not None:
            tied = tied or (row.get("project") and _same(row["project"], project))
        if tied:
            rows.append(row)
    return rows


def observe_host(project=None, *, source, rundir=None, environ=None):
    """The current host findings; a changed set is recorded so a later delivery still sees it."""
    environ = os.environ if environ is None else environ
    try:
        project = project_root(rundir) if project is None else Path(project)
        found = host_findings(project, environ)
    except Exception as exc:  # detection never blocks the call that runs it
        found = [_finding("host_check_failed", f"host integrity could not be checked: {exc}")]
    if found:
        codes = sorted({row["code"] for row in found})
        session = environ.get("RAVEL_SESSION_ID") or environ.get("CLAUDE_CODE_SESSION_ID") or ""
        previous = [row for row in host_events(project=project, sessions=(session,))
                    if row.get("kind") == "observed"]
        if not previous or previous[-1].get("codes") != codes:
            record_host_event("observed", source=source, project=str(project), session=session,
                              rundir=str(Path(rundir).resolve()) if rundir is not None else None,
                              codes=codes, findings=found)
    return found


def controller_owned(rundir):
    """The controller's run id when it owns ``rundir``; None for every other run (or before it ships)."""
    try:
        store = importlib.import_module("ravel.controller.store")
    except ModuleNotFoundError as exc:
        if exc.name not in ("ravel.controller", "ravel.controller.store"):
            raise
        return None
    owner = getattr(store, "controller_owned", None)
    return owner(Path(rundir)) if owner is not None else None


def _run_sessions(rundir):
    sessions = []
    try:
        state = json.loads((Path(rundir) / "run_state.json").read_text(encoding="utf-8"))
        sessions.append(state.get("session_id") or "")
    except (OSError, ValueError, AttributeError):
        pass
    return tuple(s for s in sessions if isinstance(s, str) and s)


def governance_label(rundir, project=None, environ=None):
    """The delivery's governance object: ``NOT GOVERNED`` for every run the controller does not own.

    ``reasons`` names why: ``unrestricted_host`` always for such runs, then each current host
    finding and each recorded host event tied to the run or its session. A controller-owned
    run's label comes from the controller's own receipt; host findings are still listed.
    """
    project = project_root(rundir) if project is None else Path(project)
    owner = controller_owned(rundir)
    current = observe_host(project, source="delivery", rundir=rundir, environ=environ)
    events = [{key: row.get(key) for key in ("kind", "utc", "hook", "codes", "source", "session")
               if row.get(key) is not None}
              for row in host_events(rundir=rundir, sessions=_run_sessions(rundir))
              if row.get("kind") != "surface_installed"]
    reasons = [] if owner else ["unrestricted_host"]
    recorded = {code for row in events if row["kind"] == "observed" for code in row.get("codes") or ()}
    recorded |= {row["kind"] for row in events if row["kind"] != "observed"}
    reasons += sorted({row["code"] for row in current} | recorded)
    return {"label": None if owner else NOT_GOVERNED, "controller_run": owner,
            "reasons": reasons, "host_findings": current, "host_events": events}


def checkin1_surface_rows(rundir):
    """Read and verify the local JSONL hash chain; this is integrity, not authentication."""
    path = Path(rundir) / CHECKIN1_SURFACE
    if not path.exists():
        return []
    rows = []
    previous = ""
    for sequence, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
            valid = (isinstance(row, dict) and type(row.get("sequence")) is int
                     and row["sequence"] == sequence and row.get("prev_sha256") == previous
                     and row.get("sha256") == digest({k: v for k, v in row.items() if k != "sha256"}))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("enforcement surface hash chain changed")
        previous = row["sha256"]
        rows.append(row)
    return rows


def record_checkin1_surface(rundir, project=None):
    """Append a hash-chained JSONL row per change, preserving every earlier byte."""
    from .execution import utc_now
    from .state_io import file_lock
    project = project_root(rundir) if project is None else Path(project)
    path = Path(rundir) / CHECKIN1_SURFACE
    with file_lock(path.with_suffix(".lock")):
        rows = checkin1_surface_rows(rundir)
        current = enforcement_surface_sha256(project)
        if rows and rows[-1].get("enforcement_surface_sha256") == current:
            return rows[-1]
        row = {"schema_version": 1, "sequence": len(rows) + 1,
               "prev_sha256": rows[-1]["sha256"] if rows else "",
               "enforcement_surface_sha256": current,
               "pre_execution_guards": pre_execution_guards(project), "host": host_name(),
               "declared_pre_execution_guards": os.environ.get("RAVEL_PRE_EXECUTION_GUARDS"),
               "declared_host": os.environ.get("RAVEL_HOST"), "recorded_utc": utc_now()}
        for extension in SURFACE_EXTENSIONS:
            metadata = getattr(extension, "metadata", None)
            if metadata is not None:
                fields = metadata(project)
                if set(fields) & set(row):
                    raise ValueError("surface extension metadata may not replace row fields")
                row.update(fields)
        row["sha256"] = digest(row)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return row


# --------------------------------------------------------------------------- #
#  Raw-launch provider (the decision gate owns coverage and approval validation)
# --------------------------------------------------------------------------- #

def _as_dict(error):
    if isinstance(error, dict):
        return {"code": error.get("code", ""), "gate": error.get("gate", ""),
                "provider": error.get("provider", ""), "message": error.get("message", ""),
                "fix": error.get("fix", ""), "pins": list(error.get("pins") or [])}
    return {"code": getattr(error, "code", ""), "gate": getattr(error, "gate", ""),
            "provider": getattr(error, "provider", ""), "message": getattr(error, "message", str(error)),
            "fix": getattr(error, "fix", ""), "pins": list(getattr(error, "pins", ()) or ())}


def raw_launch_errors(rundir, gate="delivery", action=None):
    """Raw-launch errors as dicts; an absent decision-gate provider always refuses."""
    try:
        provider = importlib.import_module("ravel.workflow.raw_launch")
    except ImportError:
        provider = None
    if provider is not None and hasattr(provider, "gate_errors"):
        return [_as_dict(e) for e in provider.gate_errors(Path(rundir), gate, action or {})]
    return [{"code": "provider_inactive", "gate": gate, "provider": "raw_launch",
             "message": "required provider raw_launch is inactive",
             "fix": "install the raw-launch provider", "pins": []}]


# --------------------------------------------------------------------------- #
#  Delivery records
# --------------------------------------------------------------------------- #

def enforcement_record(rundir, project=None):
    """The `enforcement` object for a delivery; ``governance`` carries its NOT GOVERNED label."""
    project = project_root(rundir) if project is None else Path(project)
    return {"governance": governance_label(rundir, project),
            "pre_execution_guards": pre_execution_guards(project),
            "enforcement_surface_sha256": enforcement_surface_sha256(project),
            "host": host_name(),
            "declared_pre_execution_guards": os.environ.get("RAVEL_PRE_EXECUTION_GUARDS"),
            "declared_host": os.environ.get("RAVEL_HOST"),
            "raw_launch": "fail" if raw_launch_errors(rundir) else "pass"}


def stamp_claims(rundir, record):
    """Write the enforcement record into every delivered claim (outputs/claims/<id>.json)."""
    stamped = []
    for path in sorted((Path(rundir) / "outputs/claims").glob("*.json")):
        try:
            claim = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(claim, dict) or claim.get("enforcement") == record:
            continue
        claim["enforcement"] = record
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(claim, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
        stamped.append(str(path))
    return stamped


def delivery_check_errors(rundir, pack):
    """Delivery-check (`delivery_checks.check_delivery`) refusals, when that helper is installed.

    Returns (findings, refusals, installed). A severity-A `fail`, or `missing_input` for a
    delivered absolute yield, refuses the pack.
    """
    try:
        helper = importlib.import_module("ravel.validation.delivery_checks")
    except ImportError:
        return [], [], False
    findings = list(helper.check_delivery(Path(rundir), pack))
    refusals = []
    for row in findings:
        if row.get("status") == "fail" and row.get("severity") == "A":
            refusals.append(f"{row.get('check')}: {row.get('detail', '')}".strip())
        elif row.get("status") == "missing_input" and row.get("check") == "normalization_ledger":
            refusals.append(f"{row.get('check')}: missing input for a delivered absolute yield "
                            f"({row.get('deliverable', '')})")
    return findings, refusals, True
