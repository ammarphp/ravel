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
                "validation/validate_run_state.py", "validation/validate_task_contract.py")
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
    """The `enforcement` object for a delivery."""
    project = project_root(rundir) if project is None else Path(project)
    return {"pre_execution_guards": pre_execution_guards(project),
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
