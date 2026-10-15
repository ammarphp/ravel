"""Declared MCP site-tool admission and content-free observations.

Hookless hosts use ``python -m ravel.workflow.site_tools check|observe`` with
the host tool-call JSON on stdin. This is an explicit adapter, not a host hook.
"""
import argparse
from copy import deepcopy
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import sys

from ravel.paths import package_data_path
from . import active_run, host_gate, host_governance
from .state_io import atomic_json, file_lock, read_json

MATCHER = "mcp__.*"
SCOPE_PATH = "inputs/site-tools.json"
ROUTE = ("Use RAVEL's governed route (docs/workflow/start.md): declare the exact site call "
         "in CHECK-IN 1 sections.site_tools, obtain scope-covering approval, then check again.")


def _validate(value, name):
    from jsonschema import Draft202012Validator
    schema = read_json(package_data_path("site_tools", name + ".schema.json"))
    Draft202012Validator(schema).validate(value)
    return value


def policy():
    return _validate(read_json(package_data_path("site_tools", "policy.json")), "policy")


def approval_input_paths(rundir):
    path = Path(rundir) / SCOPE_PATH
    return [str(path)] if path.exists() else []


def checkin_section(context):
    root = context.get("rundir") or context.get("base_dir")
    if root is None:
        return None
    path = Path(root) / SCOPE_PATH
    return _validate(read_json(path), "scope") if path.exists() else None


def refresh_checkin(rundir):
    """Disclose the prospective scope through the ordinary section registry."""
    from ravel.validation.validate_checkin import with_registered_sections
    rd = Path(rundir)
    _validate(read_json(rd / SCOPE_PATH), "scope")
    document = read_json(rd / "inputs/checkin1.json")
    if document.get("kind") != "checkin1":
        raise ValueError("site scope requires an existing CHECK-IN 1")
    document["sections"].pop("site_tools", None)
    spec = read_json(rd / "inputs/science.json") if (rd / "inputs/science.json").exists() else None
    atomic_json(rd / "inputs/checkin1.json", with_registered_sections(document, rd, context={"rundir": rd, "spec": spec}))


def classify(tool_name, *, document=None):
    """Server/tool globs; any effectful match wins; no match is effectful."""
    doc = policy() if document is None else _validate(document, "policy")
    parts = tool_name.split("__", 2)
    matches = []
    if len(parts) == 3 and parts[0] == "mcp" and all(parts[1:]):
        matches = [row for row in doc["rules"] if fnmatchcase(parts[1], row["server"])
                   and fnmatchcase(parts[2], row["tool"])]
    effects = sorted({row["effect"] for row in matches if row["classification"] == "effectful"})
    if effects:
        return {"classification": "effectful", "effects": effects}
    if matches:
        return {"classification": "read-only", "effects": []}
    return {"classification": "effectful", "effects": ["unknown"]}


def input_digest(tool_input):
    if type(tool_input) is not dict:
        raise ValueError("tool_input must be an object")
    json.dumps(tool_input, allow_nan=False)
    return host_governance.digest(tool_input)


def _run(data, project, rundir=None):
    return (Path(rundir) if rundir is not None else
            active_run.resolve(data.get("session_id") or "", data.get("cwd") or "", project))


def check(data, *, project, rundir=None):
    """Reuse the heavy-compute approval verifier and live launch steering check."""
    if type(data) is not dict or not isinstance(data.get("tool_name"), str):
        raise ValueError("site tool call must name a tool")
    name = data["tool_name"]
    if not name.startswith("mcp__"):
        raise ValueError("site tool call must use mcp__<server>__<tool>")
    call_sha = input_digest(data.get("tool_input", {}))
    result = {"schema_version": 1, "kind": "site-tool-verdict", "tool_name": name,
              "tool_input_sha256": call_sha, **classify(name), "decision": "allow",
              "errors": [], "approval_sha256": None}
    if result["classification"] == "read-only":
        return result
    rd = _run(data, project, rundir)
    if rd is None:
        result["errors"].append("no active run with CHECK-IN 1 approval")
    else:
        try:
            # Read scope before verification and recheck bytes afterward. The
            # existing verifier binds this entire CHECK-IN for both run kinds.
            path = rd / "inputs/checkin1.json"
            before = path.read_bytes()
            scope = _validate(read_json(path).get("sections", {}).get("site_tools"), "scope")
            covered = any(row["tool_name"] == name and row["tool_input_sha256"] == call_sha
                          and set(result["effects"]) <= set(row["effects"]) for row in scope["calls"])
            if not covered:
                result["errors"].append("CHECK-IN 1 scope does not cover this tool, arguments and effects")
            approval = rd / ("inputs/science-approval.json" if (rd / "inputs/science.json").is_file()
                             else "inputs/checkin1_approval.json")
            approval_before = approval.read_bytes() if approval.is_file() else b""
            result["errors"].extend(host_gate._approval_errors(rd, None))
            from . import gate_wiring
            result["errors"].extend(gate_wiring.launch_errors(rd, None, [], {}))
            if before != path.read_bytes() or approval_before != approval.read_bytes():
                result["errors"].append("CHECK-IN 1 or approval changed during site admission")
            if not result["errors"]:
                result["approval_sha256"] = hashlib.sha256(approval_before).hexdigest()
        except Exception as exc:
            # Policy, schema, scope and approval errors must never fail open.
            result["errors"].append("missing, invalid or unapproved site-tool scope (" + type(exc).__name__ + ")")
    if result["errors"]:
        result["decision"] = "deny"
        result["errors"] = [message + ". " + ROUTE for message in result["errors"]]
    return result


def observe(data, *, project, rundir=None):
    """Observe a completed call, including calls with no run. Never store content.

    An observation is host-reported custody, not a supervised process launch or
    evidence of remote success. Approval status here is checked at observation time.
    """
    if (type(data) is not dict or not isinstance(data.get("tool_name"), str)
            or not data["tool_name"].startswith("mcp__")):
        raise ValueError("observation requires an MCP tool call")
    rd = _run(data, project, rundir)
    try:
        verdict = check(data, project=project, rundir=rd)
    except Exception:
        verdict = {"classification": "effectful", "effects": ["unknown"],
                   "decision": "deny", "approval_sha256": None}
    from .execution import utc_now
    row = {"schema_version": 1, "kind": "site-tool-observation", "recorded_utc": utc_now(),
           "tool_name": data["tool_name"], "tool_input_sha256": input_digest(data.get("tool_input", {})),
           "classification": verdict["classification"], "effects": verdict["effects"],
           "approval_sha256": verdict["approval_sha256"], "current_decision": verdict["decision"],
           "tool_response_sha256": host_governance.digest(data.get("tool_response")),
           "policy_sha256": hashlib.sha256(package_data_path("site_tools", "policy.json").read_bytes()).hexdigest()}
    path = (rd if rd is not None else Path(project)) / "logs/site-tools.jsonl"
    with file_lock(path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    return row


def declaration(host):
    table = read_json(package_data_path("agent_surface", "hooks.json"))["site_tools"]
    return {"schema_version": 1, "kind": "site-tool-adapter", "host": host,
            "native_hooks": host == "claude", **table}


def merge_claude_settings(settings, *, python_command=None):
    """Generate only MCP groups, preserving every unrelated project hook."""
    result = deepcopy(settings)
    hooks = result.setdefault("hooks", {})
    for event, action, script in (("PreToolUse", "check", "pretooluse-mcp.sh"),
                                  ("PostToolUse", "observe", "posttooluse-observer.sh")):
        command = (f"{python_command} -m ravel.workflow.site_tools {action} --project \"$CLAUDE_PROJECT_DIR\""
                   if python_command else f'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/{script}"')
        groups = hooks.setdefault(event, [])
        existing = next((g for g in groups if g.get("matcher") == MATCHER and
                         any("ravel.workflow.site_tools" in h.get("command", "") or script in h.get("command", "")
                             for h in g.get("hooks", []))), None)
        if existing is None:
            groups.append({"matcher": MATCHER, "hooks": [{"type": "command", "command": command}]})
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("check", "observe", "render", "refresh-checkin"))
    ap.add_argument("--project", type=Path, default=Path.cwd())
    ap.add_argument("--rundir", type=Path)
    ap.add_argument("--hook", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.action == "refresh-checkin":
            if args.rundir is None:
                ap.error("refresh-checkin requires --rundir")
            refresh_checkin(args.rundir)
            return 0
        if args.action == "render":
            path = args.project / ".claude/settings.json"
            settings = merge_claude_settings(read_json(path) if path.exists() else {})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(settings, indent=2) + "\n")
            return 0
        from .state_io import _unique
        def reject_nonfinite(value):
            raise ValueError("non-finite host JSON")
        data = json.load(sys.stdin, object_pairs_hook=_unique, parse_constant=reject_nonfinite)
        result = (check if args.action == "check" else observe)(data, project=args.project, rundir=args.rundir)
        if args.hook:
            print("allow" if result["decision"] == "allow" else "block:" + result["errors"][0])
        else:
            print(json.dumps(result, sort_keys=True))
        return 2 if args.action == "check" and result["decision"] == "deny" else 0
    except Exception:
        # Do not echo host arguments or validation values (possibly credentials).
        print("block:site-tool admission or observation unavailable. " + ROUTE, file=sys.stderr)
        if args.action == "observe":
            try:
                path = args.project / "logs/hook-failures.log"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write("site-tool observation unavailable\n")
            except OSError:
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
