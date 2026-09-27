"""Claude Code CLI host adapter (WP09). Tested with mocked executables only; no live call here.

Interfaces were read from the installed help texts (2.1.233 on PATH and the Desktop-bundled
2.1.281, captured under ``local-runs/evaluation-slice/phase0/scratch/host-and-sandbox/``) and
from the official documentation as captured on 2026-09-25 by the Phase 0 host audit (local
copies in that directory's ``docs/``; not re-fetched by this module's author):
https://code.claude.com/docs/en/cli-reference, https://code.claude.com/docs/en/headless,
https://code.claude.com/docs/en/agent-sdk/typescript (SDKSystemMessage, SDKAssistantMessage,
SDKResultMessage, SDKPermissionDenial, SDKPermissionDeniedMessage, SDKTaskStartedMessage,
SDKTaskNotificationMessage, ModelUsage) and https://code.claude.com/docs/en/agent-sdk/cost-tracking.

Facts this adapter relies on:
- ``-p --output-format stream-json`` requires ``--verbose``; with no positional prompt the
  prompt is read from stdin, so the prompt never appears in argv.
- ``system/init`` carries session_id, claude_code_version, tools, mcp_servers, plugins, skills.
- ``result`` carries is_error (authoritative: a ``success`` subtype with ``is_error: true``
  exists, e.g. "Not logged in"), num_turns, total_cost_usd, usage (main loop only, excludes
  subagents), modelUsage (includes subagents), permission_denials (authoritative; the
  ``system/permission_denied`` stream event is best-effort).
- total_cost_usd after ``--resume`` covers only the call before v2.1.277 and the restored
  session total from v2.1.277; summing cumulative values double-counts (RUNTIME_06).
- An ``error_during_execution`` result after a crash may carry zeroed cost fields.
- Per-message ``output_tokens`` is a placeholder; parallel tool calls repeat ``message.id``.
- Subagent messages carry ``parent_tool_use_id``; ``task_notification`` usage has tokens but
  no cost, so subagent spend is never attributable per child (RUNTIME_07).
- ``CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`` (env-vars.md) strips "any other variable that Claude
  Code recognizes as a credential" from Bash, hook and MCP children. Whether that includes
  ``RAVEL_TASK_TOKEN`` is undocumented, so the scrub is a constructor choice (default on, as the
  Phase 0 host audit recommends) recorded in ``details['subprocess_env_scrub']``; the authorized
  live smoke must confirm that the token reaches a Bash child before any scored run.

Cost (RUNTIME_06): ``cost.usd`` is always this invocation's own spend, so ``cost.semantics`` is
``per_call`` when usd is known and ``unknown`` when it is null; the host's total_cost_usd
semantics for the pinned version is ``details['cost_accounting']['host_semantics']``.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from ..canonical import finite_number, require
from .base import (SANDBOX_MODES, SCHEMA_ERRORS, SYNTHETIC_MARKER, Adapter, AdapterResult, HostDriftError,
                   assert_prompt_not_in_argv, base_fields, capture_stream, default_launcher, event, fresh_dir,
                   guarded_parse, launch_host, merge_env, number_or_none, profile_sha256, refuse_orchestrator_env,
                   refuse_user_home_dir, sandbox_flags, schema_error, str_or_none, verify_host)

VERSION_PATTERN = r"^\s*(\d+\.\d+\.\d+\S*)\s*\(Claude Code\)"
CUMULATIVE_FROM = (2, 1, 277)
WEB_TOOLS = ("WebSearch", "WebFetch")
SUBAGENT_TOOLS = ("Agent", "Task")
# 2.1.233 help choices, minus bypassPermissions (packet: least host permissions, no blanket bypass).
PERMISSION_MODES = ("acceptEdits", "auto", "manual", "dontAsk", "plan")
SETTING_SOURCES = ("project", "local")  # "user" would load the user's settings, plugins and skills
ISOLATION_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                 "DISABLE_AUTOUPDATER": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
SCRUB_ENV = "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"
ACTIVITY_KINDS = ("message", "tool_call", "tool_result", "task")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
MODEL_USAGE_FIELDS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                      "webSearchRequests", "costUSD")


def version_tuple(version):
    try:
        return tuple(int(part) for part in str(version).split("-")[0].split(".")[:3])
    except ValueError:
        return None


def cost_semantics(version) -> str:
    parsed = version_tuple(version)
    if parsed is None or len(parsed) != 3:
        return "unknown"
    return "cumulative" if parsed >= CUMULATIVE_FROM else "per_call"


def claude_cost(total_cost_usd, *, version, resumed=False, prior_session_total_usd=None, zeroed=False):
    """Return (cost, accounting) for one invocation's reported total (RUNTIME_06).

    ``cost.usd`` is this invocation's own spend, labeled ``per_call``, or None (labeled
    ``unknown``) when it cannot be verified: a missing or zeroed-on-crash total, a cumulative
    total after a resume without a verified prior session total (or below it), or an unknown
    version after a resume. It never adds a cumulative total to the prior total. The host's
    semantics for the version is ``accounting['host_semantics']``.
    """
    semantics = cost_semantics(version)
    reported = number_or_none(total_cost_usd)
    prior = number_or_none(prior_session_total_usd)
    usd, session_total, reason = None, None, None
    if reported is None:
        reason = "total_cost_usd missing from the result event"
    elif zeroed:
        reason = "error_during_execution reported zero cost after model usage; zeroed totals are unverifiable"
    elif not resumed:
        usd = session_total = reported
    elif semantics == "per_call":
        usd = reported
        session_total = None if prior is None else prior + reported
    elif semantics == "cumulative":
        session_total = reported
        if prior is None:
            reason = "cumulative total after resume without a verified prior session total; increment unknown"
        elif reported < prior:
            reason = "cumulative total below the prior session total; increment unknown"
        else:
            usd = reported - prior
    else:
        reason = "unknown host version after resume; cost semantics unverifiable"
    accounting = {"reported_total_cost_usd": reported, "resumed": resumed, "prior_session_total_usd": prior,
                  "session_total_usd": session_total, "host_semantics": semantics, "unverified_reason": reason}
    label = "unknown" if usd is None else "per_call"
    return {"usd": usd, "provenance": "host_reported", "semantics": label}, accounting


class ClaudeCliAdapter(Adapter):
    name = "claude_cli"

    def __init__(self, executable, expected_version, expected_sha256, model, max_turns, max_budget_usd,
                 permission_mode, setting_sources, disallowed_tools, config_dir, *, allowed_tools=(), tools=None,
                 bare=False, session_id=None, resume_session_id=None, prior_session_total_usd=None,
                 sandbox="seatbelt", subprocess_env_scrub=True, synthetic=False, launcher=None):
        require(Path(executable).is_absolute(), "executable: absolute path to the pinned versioned binary")
        require(isinstance(model, str) and model.strip(), "model: required")
        require(type(max_turns) is int and max_turns > 0, "max_turns: positive integer required")
        require(finite_number(max_budget_usd) and max_budget_usd > 0, "max_budget_usd: positive number required")
        require(permission_mode in PERMISSION_MODES, f"permission_mode: expected one of {list(PERMISSION_MODES)}")
        require(isinstance(setting_sources, str), "setting_sources: string required")
        sources = setting_sources.split(",") if setting_sources else []
        require(all(s in SETTING_SOURCES for s in sources) and len(set(sources)) == len(sources),
                f"setting_sources: comma list drawn from {list(SETTING_SOURCES)} or empty")
        disallowed = list(disallowed_tools)
        require(all(isinstance(t, str) and t for t in disallowed) and set(WEB_TOOLS) <= set(disallowed),
                f"disallowed_tools: must include {list(WEB_TOOLS)}")
        require(all(isinstance(t, str) and t for t in allowed_tools), "allowed_tools: tool names required")
        require(not set(WEB_TOOLS) & set(allowed_tools) and (tools is None or not set(WEB_TOOLS) & set(tools)),
                "allowed_tools/tools: web tools must stay disabled")
        require(Path(config_dir).is_absolute(), "config_dir: absolute per-run path required")
        refuse_user_home_dir(config_dir, ".claude", "config_dir")
        require(session_id is None or resume_session_id is None, "session_id and resume_session_id are exclusive")
        for value, label in ((session_id, "session_id"), (resume_session_id, "resume_session_id")):
            require(value is None or _is_canonical_uuid(value),
                    f"{label}: canonical (lowercase, hyphenated) UUID required")
        require(prior_session_total_usd is None or resume_session_id is not None,
                "prior_session_total_usd: only meaningful with resume_session_id")
        require(sandbox in SANDBOX_MODES, f"sandbox: expected one of {list(SANDBOX_MODES)}")
        require(type(subprocess_env_scrub) is bool and type(synthetic) is bool,
                "subprocess_env_scrub/synthetic: bool required")
        self.executable, self.expected_version, self.expected_sha256 = str(executable), expected_version, expected_sha256
        self.model, self.max_turns, self.max_budget_usd = model, max_turns, max_budget_usd
        self.permission_mode, self.setting_sources = permission_mode, setting_sources
        self.disallowed_tools, self.allowed_tools = disallowed, list(allowed_tools)
        self.tools = None if tools is None else list(tools)
        self.config_dir, self.bare = Path(config_dir), bool(bare)
        self.session_id, self.resume_session_id = session_id, resume_session_id
        self.prior_session_total_usd = prior_session_total_usd
        self.sandbox, self.subprocess_env_scrub, self.synthetic = sandbox, subprocess_env_scrub, synthetic
        self.launcher = launcher
        self.executor_id = f"claude_cli/{expected_version}/{model}"

    def isolation_env(self) -> dict:
        return {**ISOLATION_ENV, SCRUB_ENV: "1"} if self.subprocess_env_scrub else dict(ISOLATION_ENV)

    def build_argv(self, *, session_id=None) -> list:
        """Structured argv; the prompt is supplied on stdin and never appears here."""
        argv = [self.executable, "-p", "--output-format", "stream-json", "--verbose",
                "--model", self.model, "--max-turns", str(self.max_turns),
                "--max-budget-usd", repr(float(self.max_budget_usd)),
                "--permission-mode", self.permission_mode, "--setting-sources", self.setting_sources,
                "--strict-mcp-config", "--disallowedTools", *self.disallowed_tools]
        if self.allowed_tools:
            argv += ["--allowedTools", *self.allowed_tools]
        if self.tools is not None:
            argv += ["--tools", ",".join(self.tools)]
        if self.bare:
            argv.append("--bare")
        if self.resume_session_id:
            argv += ["--resume", str(self.resume_session_id)]
        else:
            require(session_id is not None, "session_id: required for a new session")
            argv += ["--session-id", str(session_id)]
        return argv

    def preflight(self) -> dict:
        """Verify the pinned binary before any launch; HostDriftError on drift (RUNTIME_12)."""
        return verify_host(self.executable, expected_version=self.expected_version,
                           expected_sha256=self.expected_sha256, version_pattern=VERSION_PATTERN,
                           env_for=lambda tmp: {"PATH": "/usr/bin:/bin", "HOME": tmp, "CLAUDE_CONFIG_DIR": tmp,
                                                **self.isolation_env()})

    def run(self, *, prompt: str, workspace, env: dict, profile: str | None, timeout_s, out_dir) -> AdapterResult:
        require(isinstance(prompt, str) and prompt.strip(), "prompt: nonempty string required")
        sandbox = sandbox_flags(self.sandbox, profile)
        refuse_orchestrator_env(env)
        require(self.subprocess_env_scrub or SCRUB_ENV not in env,
                f"env: {SCRUB_ENV} is decided by the adapter's subprocess_env_scrub")
        if self.resume_session_id:
            require(self.config_dir.is_dir(), "config_dir: resuming needs the session's existing config dir")
        else:
            fresh_dir(self.config_dir, "config_dir")
        identity = self.preflight()
        session_id = None if self.resume_session_id else str(self.session_id or uuid.uuid4())
        argv = self.build_argv(session_id=session_id)
        assert_prompt_not_in_argv(argv, prompt)
        run_env = merge_env(env, {**self.isolation_env(), "CLAUDE_CONFIG_DIR": str(self.config_dir)})
        launched = launch_host(self.launcher or default_launcher(), argv, cwd=workspace, env=run_env,
                               profile=profile, timeout_s=timeout_s, out_dir=out_dir, stdin_bytes=prompt.encode())
        capture = capture_stream(launched.stdout_path, launched.stderr_path)
        common = base_fields(launched, capture)
        parsed = guarded_parse(parse_stream, capture.records, version=identity["version"],
                               resumed=self.resume_session_id is not None,
                               prior_session_total_usd=self.prior_session_total_usd,
                               expected_session_id=session_id or self.resume_session_id)
        flags = common.pop("flags") + parsed["flags"] + sandbox
        if parsed["details"].get("synthetic_marker") and not self.synthetic:
            flags.append("synthetic_marker_in_nonsynthetic_run")
        details = {**common.pop("details"), **parsed["details"], "executor_id": self.executor_id,
                   "identity": identity, "argv": argv, "sandbox": self.sandbox,
                   "profile_sha256": profile_sha256(profile), "subprocess_env_scrub": self.subprocess_env_scrub,
                   "flags": flags}
        cost = parsed["cost"] or {"usd": None, "provenance": "host_reported", "semantics": "unknown"}
        return AdapterResult(adapter="claude_cli", **common, events=parsed["events"],
                             session_ids=parsed["session_ids"], final_text=parsed["final_text"],
                             cost=cost, usage=parsed["usage"], subagents=parsed["subagents"],
                             permission_denials=parsed["permission_denials"], host_version=identity["version"],
                             synthetic=self.synthetic, details=details)


def _is_canonical_uuid(value):
    """Only the canonical form reaches ``--session-id`` and the init session comparison."""
    try:
        return isinstance(value, str) and value == str(uuid.UUID(value))
    except ValueError:
        return False


def _tool_names(tools):
    """Init ``tools`` as names (strings or ``{name}`` objects) and the count of unrecognized entries."""
    names, unrecognized = [], 0
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else tool
        if isinstance(name, str):
            names.append(name)
        else:
            unrecognized += 1
    return names, unrecognized


def _text_blocks(content):
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                   and isinstance(b.get("text"), str))


def _subset(obj, names):
    return {name: number_or_none(obj.get(name)) for name in names} if isinstance(obj, dict) else None


def parse_stream(records, *, version, resumed=False, prior_session_total_usd=None, expected_session_id=None) -> dict:
    """Normalize a stream-json trajectory into AdapterResult pieces. Missing values stay None.

    Identifiers are used as keys only when they are strings. A record whose fields have types
    this parser cannot interpret (or a tool_use without a string name, which could hide a web
    tool) is kept as an ``unnormalized`` event and listed in ``details['schema_errors']``.
    """
    events, sessions, flags, schema_errors = [], [], [], []
    init = result = last_text = None
    results = markers = 0
    seen_messages, per_message, stream_denials, tool_uses = set(), [], [], []
    subagents, task_keys, retries = {}, {}, 0

    def subagent(key, **fields):
        entry = subagents.setdefault(key, {"id": key, "tool_use_id": None, "task_id": None, "tool": None,
                                           "task_type": None, "description": None, "spawn_depth": None,
                                           "status": None, "messages": 0, "usage": None, "usage_verified": False})
        entry.update({k: v for k, v in fields.items() if v is not None})
        return entry

    for line, obj in records:
        typ, sub = obj.get("type"), obj.get("subtype")
        session, parent = str_or_none(obj.get("session_id")), str_or_none(obj.get("parent_tool_use_id"))
        kind = "other"
        try:
            if session and session not in sessions:
                sessions.append(session)
            if typ == SYNTHETIC_MARKER:
                kind, markers = "synthetic_marker", markers + 1
            elif typ == "system" and sub == "init":
                kind = "init"
                if init is not None:
                    flags.append("multiple_init_events")
                init = init or obj
            elif typ == "system" and sub == "permission_denied":
                kind = "permission_denial"
                stream_denials.append({k: obj.get(k) for k in ("tool_name", "tool_use_id", "agent_id",
                                                                 "decision_reason_type", "decision_reason", "message")})
            elif typ == "system" and sub in ("task_started", "task_notification", "task_progress", "task_updated"):
                kind = "task"
                task_id, tool_use_id = str_or_none(obj.get("task_id")), str_or_none(obj.get("tool_use_id"))
                key = tool_use_id or task_keys.get(task_id) or task_id
                is_agent = obj.get("task_type") in ("local_agent", "remote_agent") or key in subagents
                if key and is_agent:
                    if task_id:
                        task_keys[task_id] = key
                    status = str_or_none(obj.get("status")) or ("started" if sub == "task_started" else None)
                    entry = subagent(key, task_id=task_id, task_type=str_or_none(obj.get("task_type")),
                                     description=str_or_none(obj.get("description")),
                                     spawn_depth=number_or_none(obj.get("spawn_depth")), tool_use_id=tool_use_id,
                                     status=status)
                    if isinstance(obj.get("usage"), dict):
                        entry["usage"] = _subset(obj["usage"], ("total_tokens", "tool_uses", "duration_ms"))
            elif typ == "system" and sub == "api_retry":
                kind, retries = "retry", retries + 1
            elif typ == "system":
                kind = "system"
            elif typ in ("assistant", "user"):
                message = obj.get("message") if isinstance(obj.get("message"), dict) else {}
                content = message.get("content") if isinstance(message.get("content"), list) else []
                kind = "message"
                if parent:
                    subagent(parent)["messages"] += 1
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        kind = "tool_call"
                        name, use_id = block.get("name"), str_or_none(block.get("id"))
                        if not isinstance(name, str):
                            raise TypeError(f"tool_use name: expected a string, got {type(name).__name__}")
                        tool_uses.append({"line": line, "name": name, "id": use_id, "parent_id": parent})
                        if name in SUBAGENT_TOOLS and use_id:
                            spec = block.get("input") if isinstance(block.get("input"), dict) else {}
                            subagent(use_id, tool_use_id=use_id, tool=name,
                                     description=str_or_none(spec.get("description"))
                                     or str_or_none(spec.get("subagent_type")))
                    elif block.get("type") == "tool_result":
                        kind = "tool_result"
                if typ == "assistant":
                    if parent is None and _text_blocks(content):
                        last_text = _text_blocks(content)
                    message_id = str_or_none(message.get("id"))
                    if isinstance(message.get("usage"), dict) and message_id not in seen_messages:
                        if message_id is not None:
                            seen_messages.add(message_id)
                        usage = message["usage"]
                        per_message.append({"line": line, "message_id": message_id, "parent_id": parent,
                                            **_subset(usage, ("input_tokens", "cache_creation_input_tokens",
                                                              "cache_read_input_tokens")),
                                            "output_tokens_placeholder": number_or_none(usage.get("output_tokens"))})
            elif typ == "result":
                kind, results, result = "result", results + 1, obj
            elif typ == "stream_event":
                kind = "partial"
        except SCHEMA_ERRORS as exc:
            kind = "unnormalized"
            schema_errors.append(schema_error(line, exc))
        events.append(event(line, kind, obj, session_id=session, parent_id=parent))

    if results > 1:
        flags.append("multiple_result_events")
    if schema_errors:
        flags.append("schema_errors")
    info = None
    if init is not None:
        tools = init.get("tools")
        names, unrecognized = _tool_names(tools) if isinstance(tools, list) else (None, 0)
        info = {name: init.get(name) for name in ("claude_code_version", "model", "cwd", "permissionMode",
                                                  "apiKeySource", "mcp_servers", "plugins", "skills", "agents")}
        info["tools"], info["tools_unrecognized"] = names, unrecognized
        info["web_tools_present"] = None if names is None else bool(set(WEB_TOOLS) & set(names))
        if info["web_tools_present"]:
            flags.append("web_tools_in_init")
        if names is None or unrecognized:
            flags.append("init_tools_unrecognized")
        if init.get("claude_code_version") != version:
            flags.append("init_version_mismatch")
        if expected_session_id and init.get("session_id") != expected_session_id:
            flags.append("session_id_mismatch")
        for name in ("mcp_servers", "plugins"):
            if init.get(name):
                flags.append(f"{name}_present")
    else:
        flags.append("no_init_event")
        if any(e["kind"] in ACTIVITY_KINDS for e in events):
            flags.append("init_unverified")
    if any(use["name"] in WEB_TOOLS for use in tool_uses):
        flags.append("web_tool_used")

    result = result or {}
    subtype = str_or_none(result.get("subtype"))
    is_error = result.get("is_error") if type(result.get("is_error")) is bool else None
    if not result:
        flags.append("no_result_event")
    if subtype == "success" and is_error:
        flags.append("is_error_overrides_success_subtype")
    num_turns = result.get("num_turns") if type(result.get("num_turns")) is int else None
    if isinstance(result.get("result"), str):
        final_text, source = result["result"], "result"
    else:
        final_text, source = last_text, "last_assistant_message" if last_text is not None else None

    main_loop = _subset(result.get("usage"), USAGE_FIELDS)
    server = result["usage"].get("server_tool_use") if isinstance(result.get("usage"), dict) else None
    by_model = None
    if isinstance(result.get("modelUsage"), dict):
        by_model = {name: _subset(values, MODEL_USAGE_FIELDS) for name, values in result["modelUsage"].items()}
    web_requests = [number_or_none(server.get(k)) for k in ("web_search_requests", "web_fetch_requests")] \
        if isinstance(server, dict) else []
    web_requests += [values["webSearchRequests"] for values in (by_model or {}).values() if values]
    if any(n for n in web_requests if n):
        flags.append("web_requests_reported")
    usage = None
    if result or per_message:
        usage = {"source": "result_event" if result else "assistant_messages", "main_loop": main_loop,
                 "by_model": by_model, "per_message": per_message,
                 "scope": "main_loop excludes subagents; by_model includes them (host estimate)"}

    had_usage = any((m.get("input_tokens") or 0) > 0 for m in per_message) or bool(num_turns)
    zeroed = subtype == "error_during_execution" and number_or_none(result.get("total_cost_usd")) == 0 and had_usage
    cost, accounting = claude_cost(result.get("total_cost_usd"), version=version, resumed=resumed,
                                   prior_session_total_usd=prior_session_total_usd, zeroed=zeroed)
    if zeroed:
        flags.append("cost_zeroed_on_error")
    if cost["usd"] is None:
        flags.append("cost_unverified")

    denials = []
    if isinstance(result.get("permission_denials"), list):
        denials = [{**d, "source": "result"} for d in result["permission_denials"] if isinstance(d, dict)]
    known = {str_or_none(d.get("tool_use_id")) for d in denials} - {None}
    denials += [{**d, "source": "stream_event"} for d in stream_denials
                if str_or_none(d.get("tool_use_id")) not in known]
    if denials:
        flags.append("permission_denied")
    if stream_denials and not result:
        flags.append("permission_denials_best_effort_only")

    children = list(subagents.values())
    if children:
        flags.append("subagent_usage_unverified")
    details = {"init": info, "is_error": is_error, "result_subtype": subtype, "num_turns": num_turns,
               "stop_reason": result.get("stop_reason"), "terminal_reason": result.get("terminal_reason"),
               "errors": result.get("errors") if isinstance(result.get("errors"), list) else None,
               "duration_ms": number_or_none(result.get("duration_ms")),
               "final_text_source": source, "api_retries": retries, "tool_uses": tool_uses,
               "cost_accounting": accounting, "schema_errors": schema_errors, "synthetic_marker": markers > 0,
               "subagent_cost_note": "total_cost_usd includes subagents per host docs; per-child spend unobservable"
               if children else None}
    return {"events": events, "session_ids": sessions, "final_text": final_text, "cost": cost, "usage": usage,
            "subagents": children, "permission_denials": denials, "flags": flags, "details": details}


__all__ = ["ClaudeCliAdapter", "HostDriftError", "claude_cost", "cost_semantics", "parse_stream"]
