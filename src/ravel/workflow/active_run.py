"""The run registry (R-50): which run a host session works on.

`ravel initiate`, `ravel plan` and `research-orchestrate prepare` register the run they create
or prepare under the host session id. Hooks, `ravel gate` and the Stop dispatcher resolve the
active run from the working directory, then from this registry, then from a run under
`<repo>/trial-runs/` whose run_state.json names the session. They never fall back to the newest
run: a concurrent session must not be blocked or released by another session's run.

Records live under `$RAVEL_STATE_DIR/active-runs/` (one file per session). The registry is a
lookup aid; it authorizes nothing. stdlib-only, so hooks can import it with any python3.

  python -m ravel.workflow.active_run resolve [--session ID] [--cwd DIR] [--repo DIR]
  python -m ravel.workflow.active_run register --rundir RUN [--session ID] [--by LABEL]
  python -m ravel.workflow.active_run release [--session ID]

A development session that runs `ravel initiate` becomes a physics session for that run (its
enforcement surface turns read-only); `release` ends the registration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

RUN_STATE_NAME = "run_state.json"
KIND = "active-run"
# Host session variables, in precedence order. Hosts without one pass --session-id or
# RAVEL_SESSION_ID explicitly.
SESSION_ENV = ("RAVEL_SESSION_ID", "CLAUDE_CODE_SESSION_ID")


def state_dir():
    configured = os.environ.get("RAVEL_STATE_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".local/state/ravel"


def registry_dir():
    return state_dir() / "active-runs"


def session_from_env(environ=None):
    environ = os.environ if environ is None else environ
    for name in SESSION_ENV:
        value = (environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _record_path(session_id):
    return registry_dir() / (hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32] + ".json")


def _is_run(path):
    return path is not None and (Path(path) / RUN_STATE_NAME).is_file()


def register(rundir, session_id, *, by):
    """Bind `session_id` to `rundir`; a blank session id registers nothing and returns None."""
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    record = {"schema_version": 1, "kind": KIND, "session_id": session_id,
              "rundir": str(Path(rundir).expanduser().absolute()), "by": by,
              "registered_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path = _record_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return record


def release(session_id):
    """Remove a session's registration; returns whether one existed."""
    session_id = (session_id or "").strip()
    if not session_id:
        return False
    try:
        _record_path(session_id).unlink()
        return True
    except FileNotFoundError:
        return False


def lookup(session_id):
    """The registered run of a session, when its record is intact and the run still exists."""
    session_id = (session_id or "").strip()
    if not session_id:
        return None
    try:
        record = json.loads(_record_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (type(record) is not dict or record.get("schema_version") != 1 or record.get("kind") != KIND
            or record.get("session_id") != session_id or type(record.get("rundir")) is not str):
        return None
    rundir = Path(record["rundir"])
    return rundir if _is_run(rundir) else None


def rundir_from_cwd(cwd):
    """The nearest directory at or above `cwd` that holds a run_state.json."""
    if not cwd:
        return None
    current = Path(cwd).expanduser().absolute()
    for candidate in (current, *current.parents):
        if _is_run(candidate):
            return candidate
    return None


def _legacy_session_run(session_id, repo):
    """A run under <repo>/trial-runs/ whose run_state.json names this session."""
    if not session_id or not repo:
        return None
    base = Path(repo) / "trial-runs"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return None
    for name in names:
        path = base / name / RUN_STATE_NAME
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("session_id") == session_id:
                return path.parent
        except (OSError, ValueError, AttributeError):
            continue
    return None


def _legacy_cwd_run(cwd, repo):
    """cwd inside <repo>/trial-runs/<name>/: that run, even before its run_state.json exists."""
    if not cwd or not repo:
        return None
    base = (Path(repo) / "trial-runs").absolute()
    current = Path(cwd).expanduser().absolute()
    try:
        rest = current.relative_to(base).parts
    except ValueError:
        return None
    return base / rest[0] if rest and rest[0] not in (".", "..") else None


def resolve(session_id=None, cwd=None, repo=None):
    """Working directory, then the registry, then a session-named trial run; never the newest run."""
    found = (rundir_from_cwd(cwd) or _legacy_cwd_run(cwd, repo) or lookup(session_id)
             or _legacy_session_run(session_id, repo))
    return Path(found) if found is not None else None


def session_runs(session_id, repo=None):
    """Runs tied to the session itself (registry or run_state), ignoring the working directory."""
    found = lookup(session_id) or _legacy_session_run(session_id, repo)
    return Path(found) if found is not None else None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ravel.workflow.active_run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve", help="print the active run of a session or working directory")
    res.add_argument("--session", default=None)
    res.add_argument("--cwd", default=None)
    res.add_argument("--repo", default=None)
    res.add_argument("--session-only", action="store_true", help="ignore the working directory")
    reg = sub.add_parser("register", help="bind a session to a run")
    reg.add_argument("--rundir", required=True)
    reg.add_argument("--session", default=None)
    reg.add_argument("--by", default="manual")
    rel = sub.add_parser("release", help="remove a session's registration")
    rel.add_argument("--session", default=None)
    args = ap.parse_args(argv)
    session = args.session if args.session is not None else session_from_env()
    if args.command == "resolve":
        found = session_runs(session, args.repo) if args.session_only else resolve(session, args.cwd, args.repo)
        if found is not None:
            print(found)
        return 0
    if args.command == "register":
        if not _is_run(args.rundir):
            print(f"active_run: not a run directory (no {RUN_STATE_NAME}): {args.rundir}", file=sys.stderr)
            return 1
        record = register(args.rundir, session, by=args.by)
        if record is None:
            print("active_run: no session id (pass --session or set RAVEL_SESSION_ID)", file=sys.stderr)
            return 1
        print(json.dumps(record, indent=2))
        return 0
    print("released" if release(session) else "no registration")
    return 0


if __name__ == "__main__":
    sys.exit(main())
