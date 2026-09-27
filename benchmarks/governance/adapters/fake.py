"""Synthetic fake host adapter (WP06): runs ``fake_subject.py`` through the common launcher.

The subject script is staged byte-for-byte into the workspace's ``tmp/`` (so any profile
that lets the subject read its own workspace lets it read its own code) and run as
``<python> -I -B <workspace>/tmp/fake_subject.py <behavior>`` with the workspace as cwd and
the prompt on stdin. It uses the real client and broker. Everything it produces is
synthetic: executor id ``synthetic-fake:<behavior>``, cost 0.0 USD with provenance
``none_synthetic``, ``AdapterResult.synthetic`` true, no model, no credentials.

Interpreter: ``python`` defaults to the resolved path of the orchestrator's interpreter
(``os.path.realpath(sys.executable)``), because a virtual-environment ``bin/python`` symlink
inside the repository is not executable under the WP04 deny-default profile (exit 71,
"execvp() ... Operation not permitted"). The runner must put that resolved interpreter's
prefix in the profile's read roots, or pass its own pinned interpreter here. The subject runs
with ``-I`` and imports only the standard library.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from ..canonical import require, sha256_bytes
from . import fake_subject
from .base import (Adapter, AdapterResult, base_fields, capture_stream, default_launcher, event, guarded_parse,
                   launch_host, profile_sha256, refuse_orchestrator_env, str_or_none)

SUBJECT_SCRIPT = Path(fake_subject.__file__)
BEHAVIORS = fake_subject.BEHAVIORS
KINDS = {"synthetic_init": "init", "synthetic_tool_call": "tool_call", "synthetic_message": "message",
         "synthetic_probe": "probe", "result": "result"}


class FakeAdapter(Adapter):
    name = "fake"

    def __init__(self, behavior, launcher=None, *, python=None):
        require(behavior in BEHAVIORS, f"behavior: expected one of {list(BEHAVIORS)}")
        self.behavior = behavior
        self.executor_id = fake_subject.EXECUTOR_PREFIX + behavior
        self.launcher = launcher
        self.python = python or os.path.realpath(sys.executable)
        require(Path(self.python).is_absolute(), "python: absolute interpreter path required")

    def build_argv(self, script) -> list:
        return [str(self.python), "-I", "-B", str(script), self.behavior]

    def run(self, *, prompt: str, workspace, env: dict, profile: str | None, timeout_s, out_dir) -> AdapterResult:
        require(isinstance(prompt, str), "prompt: string required")
        refuse_orchestrator_env(env)
        workspace = Path(workspace)
        require(workspace.is_absolute() and workspace.is_dir(), "workspace: existing absolute directory required")
        script_bytes = SUBJECT_SCRIPT.read_bytes()
        staged = workspace / "tmp" / SUBJECT_SCRIPT.name
        require(not staged.exists() and not staged.is_symlink(), f"refusing to overwrite {staged}")
        staged.parent.mkdir(exist_ok=True)
        staged.write_bytes(script_bytes)
        launched = launch_host(self.launcher or default_launcher(), self.build_argv(staged), cwd=workspace,
                               env=dict(env), profile=profile, timeout_s=timeout_s, out_dir=out_dir,
                               stdin_bytes=prompt.encode())
        capture = capture_stream(launched.stdout_path, launched.stderr_path)
        common = base_fields(launched, capture)
        parsed = guarded_parse(parse_stream, capture.records, executor_id=self.executor_id)
        details = {**common.pop("details"), **parsed["details"], "executor_id": self.executor_id,
                   "behavior": self.behavior, "subject_sha256": sha256_bytes(script_bytes),
                   "python": str(self.python), "profile_sha256": profile_sha256(profile),
                   "flags": common.pop("flags") + parsed["flags"]}
        return AdapterResult(adapter="fake", **common, events=parsed["events"], session_ids=parsed["session_ids"],
                             final_text=parsed["final_text"],
                             cost={"usd": 0.0, "provenance": "none_synthetic", "semantics": "per_call"},
                             usage=None, subagents=[], permission_denials=[],
                             host_version="fake_subject-sha256:" + sha256_bytes(script_bytes), synthetic=True,
                             details=details)


def parse_stream(records, executor_id) -> dict:
    """Normalize the fake subject's stream; flag records not labeled synthetic or from another executor."""
    events, sessions, flags = [], [], []
    result, last_message = None, None
    unlabeled = 0
    for line, obj in records:
        typ = obj.get("type")
        kind = KINDS.get(typ, "other") if isinstance(typ, str) else "other"
        if obj.get("synthetic") is not True or obj.get("executor") != executor_id:
            unlabeled += 1
        session = str_or_none(obj.get("session_id"))
        if session and session not in sessions:
            sessions.append(session)
        if kind == "message" and isinstance(obj.get("text"), str):
            last_message = obj["text"]
        if kind == "result":
            if result is not None:
                flags.append("multiple_result_events")
            result = obj
        events.append(event(line, kind, obj, session_id=session))
    if unlabeled:
        flags.append("unlabeled_synthetic_records")
    if result is None:
        flags.append("no_result_event")
        final_text, source = last_message, "last_message" if last_message is not None else None
        is_error = None
    else:
        final_text = result.get("final_text") if isinstance(result.get("final_text"), str) else None
        source = "result" if final_text is not None else None
        is_error = result.get("is_error") if type(result.get("is_error")) is bool else None
    return {"events": events, "session_ids": sessions, "final_text": final_text, "flags": flags,
            "details": {"is_error": is_error, "final_text_source": source, "unlabeled_records": unlabeled}}
