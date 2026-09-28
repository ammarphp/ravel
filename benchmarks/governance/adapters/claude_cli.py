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
  live smoke must confirm that the token reaches a Bash child before any scored run. Off is sent as
  an explicit "0": an unset scrub turns on under CLAUDE_CODE_ENTRYPOINT=local-agent, and a truthy one
  forces the permission mode to default (decisions.md E-44). The live smoke's settings (effort, env
  pins, shell, certificate store, per-run temp dir) and stream checks are decisions E-53 and E-54.

Cost (RUNTIME_06): ``cost.usd`` is always this invocation's own spend, so ``cost.semantics`` is
``per_call`` when usd is known and ``unknown`` when it is null; the host's total_cost_usd
semantics for the pinned version is ``details['cost_accounting']['host_semantics']``.
"""
from __future__ import annotations

import re
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
# How system/init names a mode (its external name): "manual" is the alias of "default" (help text, F2).
PERMISSION_MODE_EXTERNAL = {"manual": "default"}
SETTING_SOURCES = ("project", "local")  # "user" would load the user's settings, plugins and skills
# Paid paths a subscription token can reach (fast mode, a server-suggested or refusal model fallback, 1M-context
# credits): disabled for every launch (smoke spec R3, F18).
PAID_PATH_ENV = {"CLAUDE_CODE_DISABLE_FAST_MODE": "1", "CLAUDE_CODE_NO_MODEL_FALLBACK": "1",
                 "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}
ISOLATION_ENV = {"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                 "DISABLE_AUTOUPDATER": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "DISABLE_TELEMETRY": "1",
                 "DISABLE_ERROR_REPORTING": "1", **PAID_PATH_ENV}
SCRUB_ENV = "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"
SHELL_ENV, CERT_STORE_ENV = "CLAUDE_CODE_SHELL", "CLAUDE_CODE_CERT_STORE"
PER_RUN_ENV = ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_TMPDIR")   # per-run directories, compared by path (never bound)
EFFORTS = ("low", "medium", "high", "xhigh", "max")        # --effort choices in 2.1.233 and 2.1.281 (F2)
SHELLS = ("/bin/zsh", "/bin/bash")                          # the Bash tool accepts bash or zsh (CLAUDE_CODE_SHELL)
CERT_STORES = ("bundled",)                                  # the CLI's own CA bundle: no keychain trust lookup (R1)
# The only variables a campaign may pin on top of ISOLATION_ENV (smoke spec §1.3): the paid-path switches (which
# ISOLATION_ENV already sets; a pin may only repeat them), the background-task, advisor, retry and Bash timeout
# settings (R14), the rc-file neutralizers zsh and git would otherwise read from the subject-writable HOME (R4),
# the Bash tool's working directory reset after every command (so no host-internal helper runs where a subject put a
# repository: H-23, E-75) and the 5-minute prompt-cache TTL (the recompute prices cache writes at one measured rate:
# E-76; FORCE_PROMPT_CACHING_5M and CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR are read by the 2.1.281 bundle).
ENV_PIN_NAMES = (*PAID_PATH_ENV, "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "CLAUDE_CODE_DISABLE_ADVISOR_TOOL",
                 "CLAUDE_CODE_MAX_RETRIES", "BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS", "ZDOTDIR",
                 "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR",
                 "FORCE_PROMPT_CACHING_5M")
ACTIVITY_KINDS = ("message", "tool_call", "tool_result", "task")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
MODEL_USAGE_FIELDS = ("inputTokens", "outputTokens", "cacheReadInputTokens", "cacheCreationInputTokens",
                      "webSearchRequests", "costUSD")
# Live checks (smoke spec WI-7a). The task client's message when its token did not reach the shell, and the whole
# line it prints (usage_error prefixes "ravel-task: "; the client's source holds only the unprefixed text, so a subject
# that reads or cats the client is not mistaken for a shell without its token): only a Bash result line counts.
TOKEN_MISSING = "RAVEL_TASK_ENDPOINT and RAVEL_TASK_TOKEN must be set"
TOKEN_MISSING_LINE = re.compile(r"^\s*ravel-task: " + re.escape(TOKEN_MISSING) + r"\s*$", re.MULTILINE)
# Plugins a pinned binary ships and loads whatever the settings (recorded in details['builtin_plugins'], never
# flagged): exactly these init entries, compared whole. 2.1.281 lists agents-md, which reads a project's AGENTS.md
# as instructions where it has no CLAUDE.md; no AGENTS.md may be on a subject workspace's ancestor path
# (isolation.SUBJECT_ANCESTOR_MARKERS). Any other plugin, or another shape of this one, is plugins_present (H-26).
BUILTIN_PLUGINS = ({"name": "agents-md", "path": "builtin", "source": "agents-md@builtin"},)
# Skills and agents a pinned version ships in its own bytes and lists in system/init whatever the settings (E-91),
# the other two extension surfaces init declares: any name outside the pin's set is init_skills_unexpected or
# init_agents_unexpected (S3), and a version without a recorded set allows none. For 2.1.281: every name the pin
# itself listed in its zero-cost runs on 2026-09-26/27 (HP-09's dry start, 15 skills; HP-13's sessions and the
# offline rehearsal, which reach an API, 16: "schedule" appears then), plus every skill its bundle registers by a
# literal or a resolved string constant in its bundled-skill registry (the 2.1.281 bundle's `qo({name:...})`), since
# the list varies with runtime state. A subject cannot add to either list at init: the config directory and HOME are
# fresh per run and the workspace root is not writable; invoking a skill or an agent needs the Skill or Agent tool,
# which init_tools_unexpected already stops.
BUILTIN_SKILLS = {"2.1.281": frozenset({
    "artifact-capabilities", "artifact-components", "artifact-pr-review", "batch", "claude-api", "claude-in-chrome",
    "code-review", "dataviz", "debug", "deep-research", "design-sync", "doctor", "explain-usage",
    "fewer-permission-prompts", "keybindings-help", "loop", "memory-types", "prototype", "run", "run-skill-generator",
    "schedule", "setup-claude", "simplify", "update-config", "verify", "whiteboard", "workflow-authoring"})}
BUILTIN_AGENTS = {"2.1.281": frozenset({"claude", "Explore", "general-purpose", "Plan", "statusline-setup"})}
# 2.1.281 system subtypes model_fallback, model_consent_fallback and model_refusal_fallback; any other subtype
# or record type naming a model switch or change counts too.
MODEL_SWITCH = re.compile(r"model.*(fallback|switch|change)|(fallback|switch).*model", re.IGNORECASE)
DATED = re.compile(r".+-20[0-9]{6}")
# The model field of an assistant message the CLI builds itself rather than receives from the API (an API error, a
# login or quota notice): the constant lc in the 2.1.281 bundle, which its error-message builder T8t sets. Such a
# message is counted, never read as another model answering.
LOCAL_MODEL = "<synthetic>"
LIMIT_ERRORS = ("rate_limit", "billing_error")
AUTH_TEXT = re.compile(r"not logged in|/login|invalid (api key|bearer|x-api-key|token)|authentication|"
                       r"unauthori[sz]ed|oauth token|\b40[13]\b", re.IGNORECASE)
LIMIT_TEXT = re.compile(r"usage limit|limit reached|rate[ _]limit|out of (extra )?usage|credit balance",
                        re.IGNORECASE)


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
                 permission_mode, setting_sources, disallowed_tools, config_dir, *, tmp_dir=None, shell="/bin/zsh",
                 cert_store=None, effort=None, env_pins=None, expected_tools=None, expected_api_key_source=None,
                 allowed_tools=(), tools=None, bare=False, session_id=None, resume_session_id=None,
                 prior_session_total_usd=None, sandbox="seatbelt", subprocess_env_scrub=True, synthetic=False,
                 launcher=None):
        """``tmp_dir``: the per-run CLAUDE_CODE_TMPDIR (absolute, fresh, never under ~/.claude; the CLI's default
        is /tmp, which the profile does not let a subject write). ``shell``: CLAUDE_CODE_SHELL. ``cert_store``:
        CLAUDE_CODE_CERT_STORE ("bundled": no keychain trust lookup) or None (unset). ``effort``: ``--effort``.
        ``env_pins``: further settings from ENV_PIN_NAMES only (a paid-path switch may only repeat its
        ISOLATION_ENV value). ``expected_tools`` (default: ``tools``) and ``expected_api_key_source`` are what
        system/init must report; the model and permission mode are always checked against the pin."""
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
        if tmp_dir is not None:
            require(Path(tmp_dir).is_absolute(), "tmp_dir: absolute per-run path required")
            refuse_user_home_dir(tmp_dir, ".claude", "tmp_dir")
            tmp, config = Path(tmp_dir).resolve(), Path(config_dir).resolve()
            require(tmp != config and tmp not in config.parents and config not in tmp.parents,
                    "tmp_dir: must be separate from config_dir")
        require(shell in SHELLS, f"shell: expected one of {list(SHELLS)}")
        require(cert_store is None or cert_store in CERT_STORES, f"cert_store: None or one of {list(CERT_STORES)}")
        require(effort is None or effort in EFFORTS, f"effort: None or one of {list(EFFORTS)}")
        pins = _checked_env_pins(env_pins)
        require(expected_tools is None or (isinstance(expected_tools, (list, tuple))
                                           and all(isinstance(t, str) and t for t in expected_tools)),
                "expected_tools: tool names required")
        require(expected_api_key_source is None or (isinstance(expected_api_key_source, str)
                                                    and expected_api_key_source.strip()),
                "expected_api_key_source: nonempty string or None")
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
        self.tmp_dir = None if tmp_dir is None else Path(tmp_dir)
        self.shell, self.cert_store, self.effort, self.env_pins = shell, cert_store, effort, pins
        self.expected_tools = None if expected_tools is None else list(expected_tools)
        self.expected_api_key_source = expected_api_key_source
        self.executor_id = f"claude_cli/{expected_version}/{model}"

    def isolation_env(self) -> dict:
        """What the adapter adds besides the per-run directories: ISOLATION_ENV, the campaign's pins, the scrub
        decision as an explicit "1" or "0" (a truthy value forces the permission mode to default, F3), the shell
        and, when set, the certificate store."""
        env = {**ISOLATION_ENV, **self.env_pins, SCRUB_ENV: "1" if self.subprocess_env_scrub else "0",
               SHELL_ENV: self.shell}
        if self.cert_store is not None:
            env[CERT_STORE_ENV] = self.cert_store
        return env

    def expected_tool_names(self):
        return self.expected_tools if self.expected_tools is not None else self.tools

    def build_argv(self, *, session_id=None) -> list:
        """Structured argv; the prompt is supplied on stdin and never appears here."""
        argv = [self.executable, "-p", "--output-format", "stream-json", "--verbose", "--model", self.model]
        if self.effort is not None:
            argv += ["--effort", self.effort]
        argv += ["--max-turns", str(self.max_turns),
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
        if self.tmp_dir is not None:
            fresh_dir(self.tmp_dir, "tmp_dir")
        identity = self.preflight()
        session_id = None if self.resume_session_id else str(self.session_id or uuid.uuid4())
        argv = self.build_argv(session_id=session_id)
        assert_prompt_not_in_argv(argv, prompt)
        per_run = {"CLAUDE_CONFIG_DIR": str(self.config_dir)}
        if self.tmp_dir is not None:
            per_run["CLAUDE_CODE_TMPDIR"] = str(self.tmp_dir)
        run_env = merge_env(env, {**self.isolation_env(), **per_run})
        launched = launch_host(self.launcher or default_launcher(), argv, cwd=workspace, env=run_env,
                               profile=profile, timeout_s=timeout_s, out_dir=out_dir, stdin_bytes=prompt.encode())
        capture = capture_stream(launched.stdout_path, launched.stderr_path)
        common = base_fields(launched, capture)
        parsed = guarded_parse(parse_stream, capture.records, version=identity["version"],
                               resumed=self.resume_session_id is not None,
                               prior_session_total_usd=self.prior_session_total_usd,
                               expected_session_id=session_id or self.resume_session_id, expected_model=self.model,
                               expected_tools=self.expected_tool_names(),
                               expected_permission_mode=PERMISSION_MODE_EXTERNAL.get(self.permission_mode,
                                                                                     self.permission_mode),
                               expected_api_key_source=self.expected_api_key_source,
                               run_cap_usd=self.max_budget_usd)
        flags = common.pop("flags") + parsed["flags"] + sandbox
        if parsed["details"].get("synthetic_marker") and not self.synthetic:
            flags.append("synthetic_marker_in_nonsynthetic_run")
        details = {**common.pop("details"), **parsed["details"], "executor_id": self.executor_id,
                   "identity": identity, "argv": argv, "sandbox": self.sandbox,
                   "profile_sha256": profile_sha256(profile), "subprocess_env_scrub": self.subprocess_env_scrub,
                   "effort": self.effort, "isolation_env": self.isolation_env(), "flags": flags}
        cost = parsed["cost"] or {"usd": None, "provenance": "host_reported", "semantics": "unknown"}
        return AdapterResult(adapter="claude_cli", **common, events=parsed["events"],
                             session_ids=parsed["session_ids"], final_text=parsed["final_text"],
                             cost=cost, usage=parsed["usage"], subagents=parsed["subagents"],
                             permission_denials=parsed["permission_denials"], host_version=identity["version"],
                             synthetic=self.synthetic, details=details)


def _checked_env_pins(env_pins) -> dict:
    """The campaign's env pins: names from ENV_PIN_NAMES only, string values without NUL that name no arm,
    no credential-looking name, and a paid-path switch only at its ISOLATION_ENV value."""
    if env_pins is None:
        return {}
    require(isinstance(env_pins, dict), "env_pins: a mapping of variable names to strings required")
    from .. import isolation, treatment   # lazily: the adapters package imports without them
    for name, value in env_pins.items():
        require(name in ENV_PIN_NAMES, f"env_pins: {name!r} is not one of the documented pins {list(ENV_PIN_NAMES)}")
        require(not isolation.SECRET_NAME.search(name), f"env_pins: {name} looks like a credential variable")
        require(isinstance(value, str) and "\0" not in value, f"env_pins: {name} must be a string without NUL")
        require(ISOLATION_ENV.get(name, value) == value,
                f"env_pins: {name} may only repeat the adapter's {ISOLATION_ENV.get(name)!r}")
        terms = treatment.arm_identifying_terms(value)
        require(not terms, f"env_pins: {name} names {terms}")
    return dict(sorted(env_pins.items()))


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


def parse_stream(records, *, version, resumed=False, prior_session_total_usd=None, expected_session_id=None,
                 expected_model=None, expected_tools=None, expected_permission_mode=None, expected_api_key_source=None,
                 run_cap_usd=None) -> dict:
    """Normalize a stream-json trajectory into AdapterResult pieces. Missing values stay None.

    Identifiers are used as keys only when they are strings. A record whose fields have types
    this parser cannot interpret (or a tool_use without a string name, which could hide a web
    tool) is kept as an ``unnormalized`` event and listed in ``details['schema_errors']``.

    Live checks (smoke spec WI-7a), each applied when its expectation is given: the init model, tool set,
    permission mode and apiKeySource; a main-model substitution (an assistant ``message.model`` other than the
    pin or a dated snapshot of it, or a system event announcing a model fallback or switch; a message the CLI
    generated itself, ``model`` LOCAL_MODEL, is counted in ``local_messages`` instead); fast speed in any
    usage record; auth and usage-limit failures; a Bash tool that never succeeded; the task client's
    missing-token message; cost facts against ``run_cap_usd``; and the CLI's price basis per model
    (``costBasis``, 2.1.281: "unknown" means no price row, so costUSD is a guess).
    """
    events, sessions, flags, schema_errors = [], [], [], []
    init = result = last_text = None
    results = markers = 0
    seen_messages, per_message, stream_denials, tool_uses = set(), [], [], []
    subagents, task_keys, retries = {}, {}, 0
    models_seen, system_subtypes, switches, assistant_errors, retry_statuses = set(), {}, [], [], []
    tool_results, usages, denial_hits, token_missing, local_messages = {}, [], 0, False, 0
    use_names = {}

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
            if typ == "system" and isinstance(sub, str):
                system_subtypes[sub] = system_subtypes.get(sub, 0) + 1
                if _names_model_switch(sub):
                    switches.append(sub)
            elif isinstance(typ, str) and _names_model_switch(typ):
                switches.append(typ)
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
                status = obj.get("error_status")
                retry_statuses.append(status if type(status) is int else None)
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
                        if use_id is not None:
                            use_names[use_id] = name
                        if name in SUBAGENT_TOOLS and use_id:
                            spec = block.get("input") if isinstance(block.get("input"), dict) else {}
                            subagent(use_id, tool_use_id=use_id, tool=name,
                                     description=str_or_none(spec.get("description"))
                                     or str_or_none(spec.get("subagent_type")))
                    elif block.get("type") == "tool_result":
                        kind = "tool_result"
                        text = _result_text(block.get("content"))
                        use_id = str_or_none(block.get("tool_use_id"))
                        if use_id is not None:
                            tool_results[use_id] = block.get("is_error") is True
                        denial_hits += text.count("Operation not permitted")
                        token_missing = token_missing or (use_names.get(use_id) == "Bash"
                                                          and TOKEN_MISSING_LINE.search(text) is not None)
                if typ == "assistant":
                    if message.get("model") == LOCAL_MODEL:
                        local_messages += 1
                    elif isinstance(message.get("model"), str):
                        models_seen.add(message["model"])
                    if isinstance(message.get("usage"), dict):
                        usages.append(message["usage"])
                    if isinstance(obj.get("error"), str):
                        assistant_errors.append((obj["error"], _text_blocks(content)))
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
        if init.get("mcp_servers"):
            flags.append("mcp_servers_present")
        plugins = init.get("plugins")
        builtin = [p for p in plugins if p in BUILTIN_PLUGINS] if isinstance(plugins, list) else []
        info["builtin_plugins"] = [p["source"] for p in builtin]
        if plugins and (not isinstance(plugins, list) or len(builtin) != len(plugins)):
            flags.append("plugins_present")
        for field, shipped, flag in (("skills", BUILTIN_SKILLS, "init_skills_unexpected"),
                                     ("agents", BUILTIN_AGENTS, "init_agents_unexpected")):
            listed, allowed = init.get(field), shipped.get(version, frozenset())
            extra = sorted({str(n) for n in listed if not isinstance(n, str) or n not in allowed}) \
                if isinstance(listed, list) else ([repr(listed)[:80]] if listed else [])
            info[f"{field}_unexpected"] = extra[:50]
            if extra:
                flags.append(flag)
        if expected_model is not None and init.get("model") != expected_model:
            flags.append("init_model_mismatch")
        if expected_tools is not None and (names is None or set(names) != set(expected_tools)):
            flags.append("init_tools_unexpected")
        if expected_permission_mode is not None and init.get("permissionMode") != expected_permission_mode:
            flags.append("init_permission_mode_mismatch")
        if expected_api_key_source is not None and init.get("apiKeySource") != expected_api_key_source:
            flags.append("init_api_key_source_unexpected")
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
    live, live_flags = _live_facts(result, by_model, per_message, usages, tool_uses, tool_results, models_seen,
                                   switches, system_subtypes, assistant_errors, retry_statuses, denial_hits,
                                   token_missing, expected_model=expected_model, run_cap_usd=run_cap_usd,
                                   is_error=is_error, subtype=subtype, local_messages=local_messages)
    flags += live_flags

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
               if children else None, **live}
    return {"events": events, "session_ids": sessions, "final_text": final_text, "cost": cost, "usage": usage,
            "subagents": children, "permission_denials": denials, "flags": flags, "details": details}


def _live_facts(result, by_model, per_message, usages, tool_uses, tool_results, models_seen, switches,
                system_subtypes, assistant_errors, retry_statuses, denial_hits, token_missing, *, expected_model,
                run_cap_usd, is_error, subtype, local_messages=0) -> tuple:
    """(details entries, flags) of the live checks that follow the whole stream (smoke spec WI-7a). ``models_seen``
    holds the models that answered; messages the CLI generated itself (LOCAL_MODEL) are only counted."""
    flags = []
    substituted = sorted(m for m in models_seen if expected_model is not None and not same_model(m, expected_model))
    if substituted or switches:
        flags.append("main_model_substituted")
    if system_subtypes.get("model_refusal_no_fallback"):
        flags.append("model_refusal_reported")
    model_usage = result.get("modelUsage") if isinstance(result.get("modelUsage"), dict) else {}
    if expected_model is not None and any(not same_model(name, expected_model) for name in model_usage):
        flags.append("auxiliary_model_usage")
    records = [result.get("usage")] + list(usages) + list(model_usage.values())
    fast = any(_reports_fast(r) for r in records)
    if fast:
        flags.append("fast_mode_used")
    # Cache writes at the 1-hour TTL (priced at another rate than the 5-minute one HP-13 measures; the pinned
    # FORCE_PROMPT_CACHING_5M should keep them at zero) and the inference geography the API reported (the 2.1.281
    # bundle multiplies a "us" request's cost: LC-16 applies HP-13's measured multiplier).
    usage_records = [r for r in [result.get("usage")] + list(usages) if isinstance(r, dict)]
    cache_1h = [number_or_none(r["cache_creation"].get("ephemeral_1h_input_tokens")) for r in usage_records
                if isinstance(r.get("cache_creation"), dict)]
    if any(n for n in cache_1h if n):
        flags.append("cache_write_1h_reported")
    geo = sorted({r["inference_geo"] for r in usage_records if isinstance(r.get("inference_geo"), str)
                  and r["inference_geo"]})
    basis = {name: v.get("costBasis") for name, v in model_usage.items()
             if isinstance(v, dict) and isinstance(v.get("costBasis"), str)}
    if any(b != "list" for b in basis.values()):
        flags.append("cost_basis_not_list")
    auth = any(kind == "authentication_failed" for kind, _ in assistant_errors) \
        or any(status in (401, 403) for status in retry_statuses) \
        or (is_error is True and AUTH_TEXT.search(str(result.get("result") or "")) is not None) \
        or any(AUTH_TEXT.search(text) for kind, text in assistant_errors if kind in ("unknown", "invalid_request"))
    if auth:
        flags.append("host_auth_failed")
    limited = any(kind in LIMIT_ERRORS for kind, _ in assistant_errors) \
        or (is_error is True and LIMIT_TEXT.search(str(result.get("result") or "")) is not None) \
        or any(LIMIT_TEXT.search(text) for _, text in assistant_errors)
    if limited:
        flags.append("host_usage_limited")
    bash_ids = [u["id"] for u in tool_uses if u["name"] == "Bash"]
    bash = {"calls": len(bash_ids), "ok": sum(1 for i in bash_ids if i in tool_results and not tool_results[i]),
            "errors": sum(1 for i in bash_ids if tool_results.get(i) is True)}
    if bash["calls"] and not bash["ok"]:
        flags.append("shell_tool_failed")
    if token_missing:
        flags.append("task_token_missing_in_shell")
    if denial_hits:
        flags.append("sandbox_denial_in_tool_output")
    reported = number_or_none(result.get("total_cost_usd"))
    tokens = sum((number_or_none((result.get("usage") or {}).get(k)) or 0) for k in USAGE_FIELDS) \
        if isinstance(result.get("usage"), dict) else 0
    tokens += sum((number_or_none(v.get(k)) or 0) for v in model_usage.values() if isinstance(v, dict)
                  for k in MODEL_USAGE_FIELDS[:4])
    tokens += sum(m.get("input_tokens") or 0 for m in per_message)
    if reported == 0 and tokens > 0:
        flags.append("cost_zero_with_usage")
    overshoot = None
    if reported is not None and run_cap_usd is not None and reported > run_cap_usd:
        overshoot = reported - run_cap_usd
        flags.append("cost_over_run_cap")
    if subtype == "error_max_budget_usd":
        flags.append("host_budget_exhausted")
    details = {"models_seen": sorted(models_seen), "local_messages": local_messages, "model_switch_events": switches,
               "system_subtypes": dict(sorted(system_subtypes.items())), "fast_mode": fast, "cost_basis": basis,
               "bash": bash, "sandbox_denials_in_tool_output": denial_hits, "api_retry_statuses": retry_statuses,
               "assistant_errors": sorted({kind for kind, _ in assistant_errors}), "cost_overshoot_usd": overshoot,
               "cache_write_1h_tokens": max([n for n in cache_1h if n is not None], default=None),
               "inference_geo": geo}
    return details, flags


def same_model(observed, pinned) -> bool:
    """Whether a reported model id is the pinned one or a dated snapshot of it (``<pin>-YYYYMMDD``)."""
    return isinstance(observed, str) and (observed == pinned or DATED.fullmatch(observed) is not None
                                          and observed.rsplit("-", 1)[0] == pinned)


def _names_model_switch(name) -> bool:
    """A stream record type or system subtype announcing a model fallback, switch or change (R3); the one that
    announces a refusal WITHOUT a fallback is recorded apart (model_refusal_reported)."""
    return name != "model_refusal_no_fallback" and MODEL_SWITCH.search(name) is not None


def _reports_fast(usage) -> bool:
    return isinstance(usage, dict) and (str(usage.get("speed")).lower() == "fast" or usage.get("fast_mode") is True
                                        or usage.get("fastMode") is True)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


__all__ = ["ClaudeCliAdapter", "HostDriftError", "claude_cost", "cost_semantics", "parse_stream", "same_model"]
