"""Read-only coordinator MCP server for governed chat.

Start it from a restricted host, for example
``claude --restricted --strict-mcp-config --mcp-config <file>`` with a server entry running
``python -m ravel.controller.frontend --root <runs directory>``. It answers four questions
about runs under the given roots: status, check-in display, explanations of the workflow, and
the delivery listing with its governance label.

It has no tool that approves, answers a check-in, executes, launches, stops, submits a request
or writes a file. Requests and answers go through the physicist's own terminal (``ravel ask``,
``ravel drive``), so their text never passes through a model. Every path argument is resolved
inside a configured root; a symbolic link or ``..`` that leaves it is refused. Stdio JSON-RPC,
one message per line, stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from ravel import __version__
from ravel.paths import package_data_path

PROTOCOL_VERSION = "2025-06-18"
MAX_TEXT = 20000
# Topics answered from the packaged workflow documents; nothing else is read for explanations.
TOPICS = {
    "start": ("workflow", "docs", "workflow", "start.md"),
    "hooks": ("workflow", "docs", "workflow", "hooks.md"),
    "check-ins": ("workflow", "docs", "workflow", "checklists", "check-ins.md"),
    "verification-panel": ("workflow", "docs", "workflow", "checklists", "verification-panel.md"),
}
CHECKIN_PATTERNS = ("CHECKIN*.md", "checkin*.md", "inputs/checkin*.json", "check-ins/*")
DELIVERY_DIRS = ("delivery", "outputs/completion")
_RUN = {"type": "object", "properties": {"run": {"type": "string", "description": "run directory name under a root"}},
        "required": ["run"], "additionalProperties": False}
TOOLS = [
    {"name": "run_status", "description": "Progress of a run: current step, next required item, ownership and label.",
     "inputSchema": _RUN},
    {"name": "checkin_show", "description": "Show a run's check-in documents exactly as recorded (read only).",
     "inputSchema": _RUN},
    {"name": "deliveries_list", "description": "List a run's delivered files with digests and the governance label.",
     "inputSchema": _RUN},
    {"name": "explain", "description": "Explain a workflow topic from RAVEL's packaged documents.",
     "inputSchema": {"type": "object", "properties": {"topic": {"type": "string", "enum": sorted(TOPICS)}},
                     "required": ["topic"], "additionalProperties": False}},
]


class Refused(ValueError):
    """A request the read-only front-end does not serve."""


def _inside(root, path):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def run_dir(roots, name):
    """The run directory ``name`` under one of ``roots``; never a path outside them."""
    if not isinstance(name, str) or not name.strip() or Path(name).is_absolute():
        raise Refused("run must be a directory name under a configured root")
    for root in roots:
        root = Path(root).resolve()
        candidate = (root / name).resolve()
        if _inside(root, candidate) and candidate.is_dir() and any(
                (candidate / rel).is_file() for rel in ("current_state.json", "run_state.json")):
            return candidate
    raise Refused(f"no run named {name!r} under the configured roots")


def _read_json(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


def _files(rd, patterns):
    found = []
    for pattern in patterns:
        for path in sorted(rd.glob(pattern)):
            real = path.resolve()
            if path.is_file() and _inside(rd, real) and real not in found:
                found.append(real)
    return found


def _label(rd):
    from ravel.workflow import host_governance
    owner = host_governance.controller_owned(rd)
    return {"controller_run": owner, "label": None if owner else host_governance.NOT_GOVERNED}


def run_status(roots, run):
    rd = run_dir(roots, run)
    state = _read_json(rd / "current_state.json") or {}
    legacy = _read_json(rd / "run_state.json") or {}
    return {"run": rd.name, "current_step": state.get("current_step", legacy.get("current_step")),
            "next_required": state.get("next_required", legacy.get("next_required")), **_label(rd)}


def checkin_show(roots, run):
    rd = run_dir(roots, run)
    documents = []
    for path in _files(rd, CHECKIN_PATTERNS):
        text = path.read_text(encoding="utf-8", errors="replace")
        documents.append({"path": path.relative_to(rd).as_posix(), "truncated": len(text) > MAX_TEXT,
                          "text": text[:MAX_TEXT]})
    return {"run": rd.name, "documents": documents,
            "answer": "answer check-ins in your own terminal; this front-end records nothing"}


def deliveries_list(roots, run):
    rd = run_dir(roots, run)
    rows = []
    for path in _files(rd, [d + "/**/*" for d in DELIVERY_DIRS] + ["result.json"]):
        rows.append({"path": path.relative_to(rd).as_posix(), "bytes": path.stat().st_size,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    result = _read_json(rd / "result.json") or {}
    recorded = ((result.get("enforcement") or {}).get("governance") or {}).get("label")
    return {"run": rd.name, "files": rows, "recorded_label": recorded, **_label(rd)}


def explain(topic):
    if not isinstance(topic, str) or topic not in TOPICS:
        raise Refused(f"unknown topic {topic!r}; choose one of {', '.join(sorted(TOPICS))}")
    text = package_data_path(*TOPICS[topic]).read_text(encoding="utf-8")
    return {"topic": topic, "truncated": len(text) > MAX_TEXT, "text": text[:MAX_TEXT]}


def call(roots, name, arguments):
    arguments = arguments if isinstance(arguments, dict) else {}
    if name == "explain":
        return explain(arguments.get("topic"))
    handler = {"run_status": run_status, "checkin_show": checkin_show,
               "deliveries_list": deliveries_list}.get(name) if isinstance(name, str) else None
    if handler is None:
        raise Refused(f"no tool {name!r}: this front-end only reads (status, check-ins, explanations, deliveries)")
    return handler(roots, arguments.get("run"))


def handle(roots, message):
    """One JSON-RPC response for ``message``, or None for a notification."""
    if not isinstance(message, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    ident, method = message.get("id"), message.get("method")
    if ident is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "ravel-coordinator", "version": __version__}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        try:
            payload, error = call(roots, params.get("name"), params.get("arguments")), False
        except (Refused, OSError) as exc:
            payload, error = {"refused": str(exc)}, True
        result = {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}],
                  "isError": error}
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(roots, stdin=None, stdout=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            response = handle(roots, message)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m ravel.controller.frontend", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, action="append", required=True,
                        help="directory whose run directories may be read (repeatable)")
    args = parser.parse_args(argv)
    roots = [root.resolve() for root in args.root]
    missing = [str(root) for root in roots if not root.is_dir()]
    if missing:
        parser.error("not a directory: " + ", ".join(missing))
    return serve(roots)


if __name__ == "__main__":
    raise SystemExit(main())
