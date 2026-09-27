"""Codex CLI host adapter (WP08) for ``codex exec --json``. Tested with mocked executables only.

Interfaces were read from the installed help of the app-bundled ``codex-cli 0.155.0-alpha.16.4``
(``local-runs/evaluation-slice/phase0/scratch/host-and-sandbox/codex_help.txt``) and from the
official documentation and event source as captured on 2026-09-25 by the Phase 0 host audit
(local copies in that directory's ``docs/codex/``; not re-fetched by this module's author):
the Codex pages "Non-interactive mode" (JSONL events) and "Configuration Reference"
(``approval_policy``, ``web_search``, ``features.memories``), indexed at
https://learn.chatgpt.com/llms.txt, and ``codex-rs/exec/src/exec_events.rs`` at openai/codex
main ``c98e263f``.

Facts this adapter relies on:
- ``codex exec`` reads the prompt from stdin when the prompt argument is ``-``.
- The installed ``codex exec --help`` offers ``-s/--sandbox`` but no ``-a/--ask-for-approval``;
  the approval policy is therefore set with ``-c approval_policy="never"``.
- ``web_search`` defaults to ``"cached"``, and to ``"live"`` under full-access sandbox
  settings, so ``-c web_search="disabled"`` is always passed and any ``web_search`` item in
  the stream is flagged.
- Events: ``thread.started{thread_id}``, ``turn.started``, ``turn.completed{usage}``,
  ``turn.failed{error}``, ``item.started|updated|completed{item}``, ``error{message}``. Usage
  covers one turn; there is no USD field, so cost is tokens only (usd null). Whether child
  (collab) thread usage is included in the parent's usage is unknown (RUNTIME_07).
- ``CODEX_HOME`` holds config, rules, memories and auth; a fresh per-run directory (optionally
  seeded with ``auth.json`` only, a regular single-link file, never a link to ``~/.codex``)
  isolates the subject from ``~/.codex``.
- Codex's own sandbox does not keep the subject from reading outside the workspace (Phase 0
  §0.3 read the oracle canary), so the outer Seatbelt profile is required (``sandbox``
  "seatbelt"); ``none_test_only`` exists for mocked hosts and invalidates the result.
"""
from __future__ import annotations

from pathlib import Path

from ..canonical import require
from .base import SANDBOX_MODES as OUTER_SANDBOXES
from .base import (SCHEMA_ERRORS, SYNTHETIC_MARKER, Adapter, AdapterResult, assert_prompt_not_in_argv, base_fields,
                   capture_stream, default_launcher, event, fresh_dir, guarded_parse, launch_host, merge_env,
                   number_or_none, profile_sha256, refuse_orchestrator_env, refuse_user_home_dir, sandbox_flags,
                   schema_error, str_or_none, verify_host)

VERSION_PATTERN = r"codex-cli\s+(\S+)"
SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
APPROVAL_POLICIES = ("never", "on-request")
USAGE_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
                "reasoning_output_tokens")
FIXED_CONFIG = ('web_search="disabled"', "features.memories=false", "check_for_update_on_startup=false",
                "analytics.enabled=false")
ITEM_KINDS = {"agent_message": "message", "reasoning": "reasoning", "command_execution": "tool_call",
              "file_change": "tool_call", "mcp_tool_call": "tool_call", "collab_tool_call": "subagent",
              "web_search": "web_search", "todo_list": "plan", "error": "error"}


class CodexCliAdapter(Adapter):
    name = "codex_cli"

    def __init__(self, executable, expected_version, expected_sha256, model, codex_home, *,
                 sandbox_mode="danger-full-access", approval_policy="never", ephemeral=False, sandbox="seatbelt",
                 synthetic=False, launcher=None):
        require(Path(executable).is_absolute(), "executable: absolute path to the pinned binary")
        require(isinstance(model, str) and model.strip(), "model: required")
        require(sandbox_mode in SANDBOX_MODES, f"sandbox_mode: expected one of {list(SANDBOX_MODES)}")
        require(approval_policy in APPROVAL_POLICIES, f"approval_policy: expected one of {list(APPROVAL_POLICIES)}")
        require(Path(codex_home).is_absolute(), "codex_home: absolute per-run path required")
        refuse_user_home_dir(codex_home, ".codex", "codex_home")
        require(sandbox in OUTER_SANDBOXES, f"sandbox: expected one of {list(OUTER_SANDBOXES)}")
        require(sandbox == "seatbelt" or sandbox_mode != "danger-full-access",
                "danger-full-access is allowed only inside the outer sandbox profile (E-09)")
        require(type(synthetic) is bool, "synthetic: bool required")
        self.executable, self.expected_version, self.expected_sha256 = str(executable), expected_version, expected_sha256
        self.model, self.codex_home = model, Path(codex_home)
        self.sandbox_mode, self.approval_policy, self.ephemeral = sandbox_mode, approval_policy, bool(ephemeral)
        self.sandbox, self.synthetic = sandbox, synthetic
        self.launcher = launcher
        self.executor_id = f"codex_cli/{expected_version}/{model}"

    def build_argv(self, workspace) -> list:
        """Structured argv; ``-`` makes codex read the prompt from stdin."""
        argv = [self.executable, "exec", "--json", "--color", "never", "--ignore-user-config", "--ignore-rules",
                "--skip-git-repo-check", "-C", str(workspace), "-s", self.sandbox_mode, "-m", self.model,
                "-c", f'approval_policy="{self.approval_policy}"']
        for item in FIXED_CONFIG:
            argv += ["-c", item]
        if self.ephemeral:
            argv.append("--ephemeral")
        return argv + ["-"]

    def preflight(self) -> dict:
        """Verify the pinned binary before any launch; HostDriftError on drift (RUNTIME_12)."""
        return verify_host(self.executable, expected_version=self.expected_version,
                           expected_sha256=self.expected_sha256, version_pattern=VERSION_PATTERN,
                           env_for=lambda tmp: {"PATH": "/usr/bin:/bin", "HOME": tmp, "CODEX_HOME": tmp})

    def run(self, *, prompt: str, workspace, env: dict, profile: str | None, timeout_s, out_dir) -> AdapterResult:
        require(isinstance(prompt, str) and prompt.strip(), "prompt: nonempty string required")
        sandbox = sandbox_flags(self.sandbox, profile)
        refuse_orchestrator_env(env)
        fresh_dir(self.codex_home, "codex_home", allowed=("auth.json",))
        identity = self.preflight()
        argv = self.build_argv(workspace)
        assert_prompt_not_in_argv(argv, prompt)
        launched = launch_host(self.launcher or default_launcher(), argv, cwd=workspace,
                               env=merge_env(env, {"CODEX_HOME": str(self.codex_home)}), profile=profile,
                               timeout_s=timeout_s, out_dir=out_dir, stdin_bytes=prompt.encode())
        capture = capture_stream(launched.stdout_path, launched.stderr_path)
        common = base_fields(launched, capture)
        parsed = guarded_parse(parse_stream, capture.records)
        flags = common.pop("flags") + parsed["flags"] + sandbox
        if parsed["details"].get("synthetic_marker") and not self.synthetic:
            flags.append("synthetic_marker_in_nonsynthetic_run")
        details = {**common.pop("details"), **parsed["details"], "executor_id": self.executor_id,
                   "identity": identity, "argv": argv, "sandbox": self.sandbox,
                   "profile_sha256": profile_sha256(profile), "flags": flags}
        return AdapterResult(adapter="codex_cli", **common, events=parsed["events"],
                             session_ids=parsed["session_ids"], final_text=parsed["final_text"],
                             cost={"usd": None, "provenance": "tokens_only", "semantics": "unknown"},
                             usage=parsed["usage"], subagents=parsed["subagents"],
                             permission_denials=parsed["permission_denials"], host_version=identity["version"],
                             synthetic=self.synthetic, details=details)


def _sum_usage(turns):
    """Per-field totals across turns; a field missing (or non-numeric) in any turn totals to None."""
    if not turns:
        return None
    return {name: (sum(t[name] for t in turns) if all(t[name] is not None for t in turns) else None)
            for name in USAGE_FIELDS}


def parse_stream(records) -> dict:
    """Normalize a ``codex exec --json`` trajectory into AdapterResult pieces.

    An ``item.*`` event without an item object or a string item type (it could hide a
    ``web_search`` item), or with non-string child thread ids, is kept as an ``unnormalized``
    event and listed in ``details['schema_errors']``.
    """
    events, sessions, flags, schema_errors = [], [], [], []
    turns, failures, denials, children = [], [], [], {}
    threads = web_items = completed_turns = markers = 0
    last_text = None

    def remember(thread):
        if isinstance(thread, str) and thread not in sessions:
            sessions.append(thread)

    for line, obj in records:
        typ = obj.get("type")
        kind, session = "other", None
        try:
            if typ == SYNTHETIC_MARKER:
                kind, markers = "synthetic_marker", markers + 1
            elif typ == "thread.started":
                kind, session, threads = "init", str_or_none(obj.get("thread_id")), threads + 1
                remember(session)
            elif typ == "turn.started":
                kind = "turn"
            elif typ == "turn.completed":
                kind, completed_turns = "usage", completed_turns + 1
                usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
                turns.append({name: number_or_none(usage.get(name)) for name in USAGE_FIELDS})
            elif typ in ("turn.failed", "error"):
                kind = "error"
                error = obj.get("error") if isinstance(obj.get("error"), dict) else obj
                failures.append({"line": line, "type": typ, "message": error.get("message")})
            elif isinstance(typ, str) and typ.startswith("item."):
                item = obj.get("item")
                if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                    raise TypeError(f"{typ}: expected an item object with a string type")
                item_type = item["type"]
                kind = ITEM_KINDS.get(item_type, "other")
                completed = typ == "item.completed"
                if item_type == "agent_message" and completed and isinstance(item.get("text"), str):
                    last_text = item["text"]
                elif item_type == "web_search":
                    web_items += 1
                elif item_type == "command_execution" and item.get("status") == "declined":
                    denials.append({"tool_name": "command_execution", "item_id": item.get("id"),
                                    "command": item.get("command"), "source": "item"})
                elif item_type == "collab_tool_call":
                    remember(item.get("sender_thread_id"))
                    states = item.get("agents_states") if isinstance(item.get("agents_states"), dict) else {}
                    receivers = item.get("receiver_thread_ids")
                    receivers = receivers if isinstance(receivers, list) else []
                    if not all(isinstance(thread, str) for thread in receivers):
                        raise TypeError("collab_tool_call receiver_thread_ids: expected strings")
                    tool = str_or_none(item.get("tool"))
                    for thread in receivers:
                        remember(thread)
                        entry = children.setdefault(thread, {"id": thread, "spawned_by_item": None, "tools": [],
                                                             "status": None, "usage": None, "usage_verified": False})
                        if tool == "spawn_agent":
                            entry["spawned_by_item"] = item.get("id")
                        if tool not in entry["tools"]:
                            entry["tools"].append(tool)
                        state = states.get(thread)
                        if isinstance(state, dict) and state.get("status"):
                            entry["status"] = state["status"]
        except SCHEMA_ERRORS as exc:
            kind = "unnormalized"
            schema_errors.append(schema_error(line, exc))
        events.append(event(line, kind, obj, session_id=session))

    if threads == 0:
        flags.append("no_thread_started")
    if threads > 1:
        flags.append("multiple_thread_started")
    if web_items:
        flags.append("web_search_item_present")
    if schema_errors:
        flags.append("schema_errors")
    if denials:
        flags.append("permission_denied")
    if children:
        flags.append("subagent_usage_unverified")
    if not turns:
        flags.append("no_usage")
    is_error = True if failures else (False if completed_turns else None)
    usage = None if not turns else {"source": "turn.completed", "turns": turns, "total": _sum_usage(turns),
                                    "scope": "per turn; child-thread attribution unknown"}
    details = {"is_error": is_error, "failures": failures, "completed_turns": completed_turns,
               "final_text_source": "last_agent_message" if last_text is not None else None,
               "web_search_items": web_items, "web_search_config": 'web_search="disabled"',
               "schema_errors": schema_errors, "synthetic_marker": markers > 0,
               "budget_note": "codex exec has no host-enforced spend or token cap"}
    return {"events": events, "session_ids": sessions, "final_text": last_text, "usage": usage,
            "subagents": list(children.values()), "permission_denials": denials, "flags": flags,
            "details": details}


__all__ = ["CodexCliAdapter", "parse_stream"]
