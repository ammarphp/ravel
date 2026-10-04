"""HP-13, the offline rehearsal (smoke spec WI-7c; R2, R3, R4, R5, R14): scripted sessions a pinned Claude Code
CLI runs, headless, against a local mock Messages API before any token is minted, and the verdicts drawn from them.

The pinned binary runs with the campaign's exact argv, environment and profile, with three changes that the
caller (``cli.py host-probe --rehearse``) makes: ``ANTHROPIC_BASE_URL`` points at the mock (its port joins the
probe profile and ``NO_PROXY``), the credential is a DUMMY the recording launcher injects, and the proxy allowlist
denies everything. Nothing here spends, and nothing reaches a network beyond 127.0.0.1.

Sessions (each a fresh workspace, HOME, config and tmp directory, and session id):

- ``tool_path`` (a): Bash writes the environment NAMES its children see; Bash runs ``bin/ravel-task inputs``
  against a probe broker; Bash lists the config directory's shell snapshots while the session runs; Write, Read
  and Edit of a workspace file; Read and Write outside the working directory (recorded). Required:
  RAVEL_TASK_TOKEN reaches the shell and neither CLAUDE_CODE_OAUTH_TOKEN nor its descriptor variant does; the task
  call succeeds; a shell snapshot existed during the session or exists after it (2.1.281 unlinks its session
  snapshot at exit, so only the listing taken during the session can see it there); system/init matches (tools,
  permission mode, model, apiKeySource, and no plugin, MCP server, skill or agent a paid run would stop on); every
  main request offers exactly the declared tools, carries the pinned effort, no fast speed and no 1-hour cache TTL;
  and a Bash search of the host's config and temp directories DURING the session finds no copy of the dummy token
  (a copy the host writes and removes again is invisible to the sweep after the run). Recorded: which ``python3``
  the Bash tool's PATH resolves and its version (the login-shell snapshot runs path_helper: E-49's residual).
- ``planted_rc`` (b): Bash plants zsh, bash and git configuration hooks in the subject-writable HOME (and the
  XDG git config) that log environment NAMES; then Bash changes into output/ and makes a repository there whose
  repo-level config (core.fsmonitor, core.pager, an alias) and hooks (core.hooksPath) log environment NAMES too, as
  a subject could where the host's own helpers run git (F20, H-23); more Bash, Read, Write and Edit calls follow.
  Required: no logged name list holds CLAUDE_CODE_OAUTH_TOKEN. Which hooks fired, and whether the Bash tool's
  working directory was reset to the workspace after the ``cd`` (CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR), are
  recorded.
- ``pricing`` (d): one-turn sessions report 1,000,000 tokens of one kind (input, output, cache write, cache read)
  for the pinned model and for the unknown control id ``claude-ravel-unknown-0``; the CLI's total is its rate per
  million tokens. Required: the pinned model's rates differ from the control's (an unknown model is priced at a
  fallback, never zero: F12), unless the caller located the pin's catalog entry in the pinned binary and it equals
  the measured rates exactly (H-27). Recorded as cli_price_per_mtok. One more session per geography in GEOS
  reports 1,000,000 input tokens with that ``inference_geo``: "us" (the 2.1.281 bundle multiplies a "us" request's
  cost) and "not_available" (what the service reported in every smoke run, E-203). The ratio of each to the plain
  input session is recorded in cli_geo_multiplier ({geo: ratio}); LC-16 applies the ratio measured for the one
  geography a run's usage reports. A geography whose ratio cannot be measured is left out (LC-16 then warns),
  and the non-required check d.geo_multipliers records which were measured.
- ``budget`` (c): turns whose usage crosses the per-run cap on a known turn (sized from the measured input and
  output rates, at most BUDGET_TURN_CEILING tokens per turn so no turn approaches a context window and triggers a
  compaction). Required: error_max_budget_usd after at most one more answered request.
- ``settings`` (e) and ``retries``: a background Bash run, a Bash timeout above a lowered BASH_MAX_TIMEOUT_MS,
  and HTTP 529 answers against CLAUDE_CODE_MAX_RETRIES; each recorded as effective, ignored or unobserved.

Finally the dummy token and its variants are swept for in every session's roots (required: nowhere).

The caller supplies a session host with ``prepare(name)`` (a fresh ``SessionContext``) and ``run(context, *,
prompt, model, env, credential_mode, base_url, mock_port, task_endpoint, task_token)`` (one launch of the pinned
CLI with the campaign's argv for that model, its environment with ``env`` overriding the pins, the mock as
ANTHROPIC_BASE_URL, the probe task service, the dummy credential, and the probe profile; it returns
``AdapterResult.as_dict()``), and the mock server module (tests/governance/mock_messages_api.py,
``load_mock``). If the pinned CLI refuses an OAuth token with a custom base URL, the rehearsal is rerun with
``credential_mode="api_key"`` (a dummy ANTHROPIC_API_KEY) and records that apiKeySource is then checked only by
HP-09 or the first paid run. Standard library only.
"""
from __future__ import annotations

import hmac
import http.server
import importlib.util
import json
import math
import secrets
import socketserver
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

from . import credentials
from .canonical import require, sha256_file

CONTROL_MODEL = "claude-ravel-unknown-0"
PRICE_KINDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
MTOK = 1_000_000
EFFECTIVE, IGNORED, UNOBSERVED = "effective", "ignored", "unobserved"
CREDENTIAL_MODES = ("oauth", "api_key")
PROBE_DIR = "rehearsal"                  # <workspace>/tmp/rehearsal: what the scripted commands write
SNAPSHOT_LISTING = "shell-snapshots.txt"   # the config dir's shell-snapshots/ as listed during session (a)
TOKEN_NAMES = ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR")
INIT_FLAGS = ("no_init_event", "init_unverified", "init_model_mismatch", "init_tools_unexpected",
              "init_permission_mode_mismatch", "init_api_key_source_unexpected", "init_version_mismatch",
              "init_tools_unrecognized", "plugins_present", "mcp_servers_present", "init_skills_unexpected",
              "init_agents_unexpected")
# The inference geographies whose cost multiplier the pricing sessions measure (E-76, E-203): "us", which the 2.1.281
# bundle prices at 1.1 (``ZA``: 1.1 when inference_geo is exactly "us", else 1), and "not_available", the value the
# service reported in every smoke run.
GEOS = ("us", "not_available")
MIDRUN_SCAN = "midrun-token-scan.txt"      # session (a): files under the host state holding the dummy token, mid-run
CWD_AFTER = "cwd-after-cd.txt"             # session (b): the Bash tool's working directory one command after a cd
BASH_PYTHON = "bash-python.txt"            # session (a): which python3 the Bash tool's PATH resolves, and its version
# The hooks the planted repository in output/ installs (core.hooksPath): the index, checkout, commit, reference and
# maintenance hooks a host helper's git could run, each logging environment names.
REPO_HOOKS = ("post-index-change", "post-checkout", "pre-commit", "post-commit", "reference-transaction",
              "fsmonitor-watchman", "pre-auto-gc", "repo-fsmonitor", "repo-pager", "repo-alias")


def home_hooks(fired) -> list:
    """The fired hook labels planted in HOME (rc files and the HOME git configs), not the output/ repository's: with
    ZDOTDIR and GIT_CONFIG_* pinned none of them may fire; the repository's may (the subject's own git runs them)."""
    return [f for f in fired if f.split(":", 1)[-1] not in REPO_HOOKS]
WEB_TOOLS = ("WebSearch", "WebFetch")
MOCK_PATH = Path(__file__).resolve().parents[2] / "tests" / "governance" / "mock_messages_api.py"
MOCK_MODULE = "ravel_mock_messages_api"
BUDGET_TURNS = 16                        # scripted turns in the budget session (it must stop well before)
BUDGET_TARGET_TURN = 4                   # the turn on which the CLI's estimate should cross the cap
BUDGET_TURN_CEILING = 120_000            # tokens one budget turn reports: far below a 200k context window
SETTINGS_TIMEOUTS = {"BASH_DEFAULT_TIMEOUT_MS": "1000", "BASH_MAX_TIMEOUT_MS": "2000"}   # lowered for (e)
OVERLOADS = 10                           # 529 answers the retry probe gives before a success
# Environment names, never values, and NUL-safe: zsh lists its exported parameters, bash its exported names.
NAMES = ('{ if [ -n "$ZSH_VERSION" ]; then print -rl -- ${(k)parameters[(R)*export*]}; '
         'else compgen -e; fi; } | LC_ALL=C sort')
SH_NAMES = r"export -p | sed -nE 's/^(declare -x|export) ([A-Za-z_][A-Za-z0-9_]*).*/\2/p'"


def load_mock(path=MOCK_PATH):
    """The mock Messages API module, loaded from its file (it lives with the tests) and registered under
    MOCK_MODULE (its dataclasses need their module registered); its sha256 is recorded with each rehearsal."""
    loaded = sys.modules.get(MOCK_MODULE)
    if loaded is not None and getattr(loaded, "__file__", None) == str(path):
        return loaded
    spec = importlib.util.spec_from_file_location(MOCK_MODULE, path)
    require(spec is not None and spec.loader is not None, f"rehearsal: cannot load the mock API from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MOCK_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(MOCK_MODULE, None)
        raise
    return module


def _q(text: str) -> str:
    """A POSIX shell single-quoted word."""
    return "'" + text.replace("'", "'\\''") + "'"


@dataclass
class SessionContext:
    """One session's fresh places: the workspace (the CLI's cwd, holding bin/ravel-task), its writable probe
    directory, the subject-writable HOME, a writable directory outside the workspace, the CLI's config directory,
    and the roots swept for the dummy token."""
    workspace: Path
    home: Path
    outside: Path
    config_dir: Path
    sweep_roots: dict = field(default_factory=dict)

    @property
    def probe(self) -> Path:
        return self.workspace / "tmp" / PROBE_DIR


@dataclass
class Session:
    name: str
    turns: list
    model: str | None = None                  # None: the pinned model
    env: dict = field(default_factory=dict)   # overrides for this session only (recorded)
    prompt: str = ""


# ---------------------------------------------------------------- the probe task service

class _BrokerHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ravel-probe-broker"
    sys_version = ""
    timeout = 30   # a connection that sends nothing is dropped, so stop() never waits on it for long

    def log_message(self, *args):
        pass

    def do_POST(self):
        broker = self.server.broker
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        raw = self.rfile.read(max(0, min(length, 1 << 20)))
        token = self.headers.get("X-Ravel-Task-Token") or ""
        ok = hmac.compare_digest(token.encode(), broker.token.encode())
        try:
            op = json.loads(raw.decode("utf-8")).get("op")
        except (UnicodeDecodeError, ValueError, AttributeError):
            op = None
        report = self.headers.get("X-Ravel-Client-Env")
        names = None if report is None else (report if report.startswith("!") else report.split(","))
        broker._log({"authenticated": ok, "op": op if isinstance(op, str) else None,
                     "header_names": sorted({k.lower() for k in self.headers.keys()}), "client_env_names": names})
        body = json.dumps({"ok": True, "result": {"probe": "SYNTHETIC rehearsal task service"}} if ok else
                          {"ok": False, "error": {"code": "unauthorized", "message": "missing or invalid token"}})
        payload = body.encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _BrokerServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class ProbeBroker:
    """A task service stand-in on 127.0.0.1: ``POST /op`` with its token answers ok. Records per call whether it
    authenticated, the op, the header NAMES and the client's reported environment names (never a value)."""

    def __init__(self):
        self.token = "probe-" + secrets.token_hex(16)
        self._calls, self._lock, self._server, self._thread = [], threading.Lock(), None, None

    def start(self) -> str:
        server = _BrokerServer(("127.0.0.1", 0), _BrokerHandler)
        server.broker = self
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                        name="ravel-probe-broker", daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{server.server_address[1]}/op"

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def stop(self, join_timeout=10.0) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(join_timeout)
            self._server = self._thread = None

    def _log(self, entry):
        with self._lock:
            self._calls.append({"seq": len(self._calls) + 1, **entry})

    def calls(self) -> list:
        with self._lock:
            return [dict(c) for c in self._calls]

    def clear(self) -> None:
        with self._lock:
            self._calls = []


# ---------------------------------------------------------------- scripted sessions

def _split_word(token: str) -> str:
    """The token as ONE shell word written in two quoted halves: the shell joins them, while the command text (which
    the host keeps in its transcript) never holds the token, so the search cannot find itself."""
    half = len(token) // 2
    return _q(token[:half]) + _q(token[half:])


def tool_path_session(mock, ctx: SessionContext, token: str = "") -> Session:
    probe, ws = ctx.probe, ctx.workspace
    target, outside = ws / "output" / "rehearsal-file.txt", ctx.outside / "rehearsal-outside.txt"
    turns = [
        mock.tool("Bash", {"command": f"{NAMES} > {_q(str(probe / 'bash-env-names.txt'))}",
                           "description": "SYNTHETIC rehearsal: list environment names"}),
        mock.tool("Bash", {"command": f"{_q(str(ws / 'bin' / 'ravel-task'))} inputs > "
                                      f"{_q(str(probe / 'ravel-task.out'))} 2>&1; "
                                      f"echo $? > {_q(str(probe / 'ravel-task.rc'))}",
                           "description": "SYNTHETIC rehearsal: call the task service"}),
        mock.tool("Bash", {"command": f"ls -1 {_q(str(ctx.config_dir / 'shell-snapshots'))} > "
                                      f"{_q(str(probe / SNAPSHOT_LISTING))} 2>&1; true",
                           "description": "SYNTHETIC rehearsal: list the shell snapshots during the session"}),
        mock.tool("Bash", {"command": f"{{ command -v python3; python3 -c 'import sys; print(sys.version.split()[0])'; "
                                      f"}} > {_q(str(probe / BASH_PYTHON))} 2>&1; true",
                           "description": "SYNTHETIC rehearsal: the python3 the Bash tool's PATH finds"}),
        mock.tool("Bash", {"command": f"grep -rlF -e {_split_word(token)} {_q(str(ctx.config_dir.parent))} > "
                                      f"{_q(str(probe / MIDRUN_SCAN))} 2>/dev/null; echo scanned >> "
                                      f"{_q(str(probe / MIDRUN_SCAN))}",
                           "description": "SYNTHETIC rehearsal: search the host state for the dummy token mid-run"}),
        mock.tool("Write", {"file_path": str(target), "content": "SYNTHETIC rehearsal"}),
        mock.tool("Read", {"file_path": str(target)}),
        mock.tool("Edit", {"file_path": str(target), "old_string": "SYNTHETIC rehearsal",
                           "new_string": "SYNTHETIC rehearsal EDITED"}),
        mock.tool("Read", {"file_path": str(ctx.outside / "rehearsal-planted.txt")}),
        mock.tool("Write", {"file_path": str(outside), "content": "SYNTHETIC outside write"}),
        mock.text("SYNTHETIC rehearsal (a) done."),
    ]
    return Session("tool_path", turns, prompt="SYNTHETIC probe: rehearsal session (a), tool path. Not a task.")


def planted_rc_session(mock, ctx: SessionContext) -> Session:
    log, home = ctx.probe / "planted.log", ctx.home
    hook = home / "rehearsal-hook.sh"
    zsh = lambda tag: f"{{ echo '== {tag}'; print -rl -- ${{(k)parameters[(R)*export*]}}; }} >> {_q(str(log))}\n"
    bash = lambda tag: f"{{ echo '== {tag}'; compgen -e; }} >> {_q(str(log))}\n"
    files = {".zshenv": zsh("zshenv"), ".zprofile": zsh("zprofile"), ".zshrc": zsh("zshrc"), ".zlogin": zsh("zlogin"),
             ".bash_profile": bash("bash_profile"), ".bashrc": bash("bashrc"), ".profile": bash("profile"),
             "rehearsal-hook.sh": f"#!/bin/sh\n{{ echo \"== git-hook:$(basename \"$0\")\"; {SH_NAMES}; }} >> "
                                  f"{_q(str(log))} 2>/dev/null\nexit 0\n"}
    gitconfig = (f"[core]\n\tfsmonitor = {hook}\n\tpager = {hook}\n\teditor = {hook}\n"
                 f"[credential]\n\thelper = {hook}\n[alias]\n\tst = !{hook}\n\tci = !{hook}\n")
    commands = [f"mkdir -p {_q(str(home / '.config' / 'git'))}"]
    for name, content in files.items():
        commands.append(f"printf %s {_q(content)} > {_q(str(home / name))}")
    commands.append(f"chmod 755 {_q(str(hook))}")
    for path in (home / ".gitconfig", home / ".config" / "git" / "config"):
        commands.append(f"printf %s {_q(gitconfig)} > {_q(str(path))}")
    commands.append(f"(mkdir .git 2>&1 || true) > {_q(str(ctx.probe / 'workspace-git.txt'))}")
    output = ctx.workspace / "output"
    hooks = home / "rehearsal-git-hooks"
    repo_config = (f"[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tfsmonitor = {hooks / 'repo-fsmonitor'}\n"
                   f"\tpager = {hooks / 'repo-pager'}\n\thooksPath = {hooks}\n[alias]\n\tst = !{hooks / 'repo-alias'}\n")
    repo = [f"mkdir -p {_q(str(hooks))}"]
    for name in REPO_HOOKS:
        repo.append(f"cp {_q(str(hook))} {_q(str(hooks / name))}")
    repo += ["cd output",
             "(git init -q . 2>/dev/null || { mkdir -p .git/objects .git/refs/heads && "
             "printf 'ref: refs/heads/main\\n' > .git/HEAD; })",
             f"printf %s {_q(repo_config)} > .git/config", "printf 'SYNTHETIC tracked\\n' > tracked.txt",
             "git add tracked.txt 2>/dev/null; true"]
    turns = [
        mock.tool("Bash", {"command": " && ".join(commands), "description": "SYNTHETIC rehearsal: plant rc hooks"}),
        mock.tool("Bash", {"command": "git --version; git status 2>&1 | head -1; true",
                           "description": "SYNTHETIC rehearsal: run git"}),
        mock.tool("Bash", {"command": " && ".join(repo), "description": "SYNTHETIC rehearsal: a repository in output/"}),
        mock.tool("Bash", {"command": f"pwd > {_q(str(ctx.probe / CWD_AFTER))}; git status 2>&1 | head -1; true",
                           "description": "SYNTHETIC rehearsal: where the next command runs"}),
        mock.tool("Write", {"file_path": str(output / "rehearsal-planted.txt"), "content": "SYNTHETIC planted"}),
        mock.tool("Read", {"file_path": str(output / "rehearsal-planted.txt")}),
        mock.tool("Edit", {"file_path": str(output / "rehearsal-planted.txt"), "old_string": "SYNTHETIC planted",
                           "new_string": "SYNTHETIC planted EDITED"}),
        mock.tool("Bash", {"command": "ls -a; true", "description": "SYNTHETIC rehearsal: another command"}),
        mock.tool("Read", {"file_path": str(ctx.workspace / "request.md")}),
        mock.text("SYNTHETIC rehearsal (b) done."),
    ]
    return Session("planted_rc", turns, prompt="SYNTHETIC probe: rehearsal session (b), planted rc. Not a task.")


def pricing_session(mock, kind: str, model: str, *, geo=None) -> Session:
    require(kind in PRICE_KINDS, f"pricing: unknown usage kind {kind!r}")
    usage = {k: (MTOK if k == kind else 0) for k in PRICE_KINDS}
    if geo is not None:
        usage["inference_geo"] = geo
    name = f"pricing:{model}:{kind}" + ("" if geo is None else f":geo_{geo}")
    return Session(name, [mock.text("SYNTHETIC pricing turn.", usage=usage)], model=model,
                   prompt=f"SYNTHETIC probe: pricing session ({kind}). Not a task.")


def budget_usage(cap_usd, rates: dict) -> tuple:
    """(per-turn usage, per-turn cost, crossing turn) for the budget session from the pinned model's measured
    rates: input and output tokens 4:1, scaled so the CLI's estimate crosses the cap on BUDGET_TARGET_TURN but
    never above BUDGET_TURN_CEILING tokens a turn (the crossing then comes later). Without both measured rates the
    usage is a fixed guess and the cost and crossing are None (the budget check then fails)."""
    in_rate, out_rate = rates.get("input_tokens"), rates.get("output_tokens")
    if not all(isinstance(r, (int, float)) and not isinstance(r, bool) and r > 0 for r in (in_rate, out_rate)):
        return {"input_tokens": 80_000, "output_tokens": 20_000}, None, None
    unit = (4 * in_rate + out_rate) / MTOK                   # the cost of four input tokens and one output token
    units = min(cap_usd / (BUDGET_TARGET_TURN - 0.5) / unit, BUDGET_TURN_CEILING / 5)
    usage = {"input_tokens": max(1, math.floor(4 * units)), "output_tokens": max(1, math.floor(units))}
    cost = (usage["input_tokens"] * in_rate + usage["output_tokens"] * out_rate) / MTOK
    return usage, cost, math.ceil(cap_usd / cost - 1e-9)


def budget_session(mock, usage: dict) -> Session:
    turns = [mock.tool("Bash", {"command": "true", "description": "SYNTHETIC rehearsal: budget turn"}, usage=usage)
             for _ in range(BUDGET_TURNS)] + [mock.text("SYNTHETIC rehearsal (c) should never get here.")]
    return Session("budget", turns, prompt="SYNTHETIC probe: rehearsal session (c), budget. Not a task.")


def settings_session(mock, ctx: SessionContext) -> Session:
    turns = [
        mock.tool("Bash", {"command": "echo ravel-background-probe", "run_in_background": True,
                           "description": "SYNTHETIC rehearsal: background run"}),
        mock.tool("Bash", {"command": "sleep 6; echo ravel-timeout-probe", "timeout": 10000,
                           "description": "SYNTHETIC rehearsal: timeout above the maximum"}),
        mock.text("SYNTHETIC rehearsal (e) done."),
    ]
    return Session("settings", turns, env=dict(SETTINGS_TIMEOUTS),
                   prompt="SYNTHETIC probe: rehearsal session (e), settings. Not a task.")


def retries_session(mock) -> Session:
    return Session("retries", [mock.text("SYNTHETIC rehearsal retries done.", overloaded=OVERLOADS)],
                   prompt="SYNTHETIC probe: rehearsal session (e), retries. Not a task.")


# ---------------------------------------------------------------- reading one session

def tool_calls(result: dict) -> list:
    """[{name, input, text, is_error}] for every tool_use in a result's events, paired with its tool_result
    (text None when none came back)."""
    uses, answers = [], {}
    for event in result.get("events") or []:
        message = (event.get("data") or {}).get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                uses.append(block)
            elif block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                body = block.get("content")
                if isinstance(body, list):
                    body = "\n".join(b.get("text", "") for b in body if isinstance(b, dict))
                answers[block["tool_use_id"]] = (body if isinstance(body, str) else "", block.get("is_error") is True)
    out = []
    for use in uses:
        text, is_error = answers.get(use.get("id"), (None, None))
        out.append({"name": use.get("name"), "input": use.get("input"), "text": text, "is_error": is_error})
    return out


def _read(path: Path, limit=1 << 20):
    try:
        with open(path, "rb") as handle:
            return handle.read(limit).decode("utf-8", "replace")
    except OSError:
        return None


def _flags(result) -> list:
    return list((result.get("details") or {}).get("flags") or [])


def _summary(result: dict, requests: list) -> dict:
    details = result.get("details") or {}
    init = details.get("init") or {}
    return {"status_hint": result.get("status_hint"), "exit_code": result.get("exit_code"), "flags": _flags(result),
            "init": {k: init.get(k) for k in ("model", "permissionMode", "apiKeySource", "tools",
                                              "claude_code_version")} if init else None,
            "result_subtype": details.get("result_subtype"), "is_error": details.get("is_error"),
            "reported_total_cost_usd": (details.get("cost_accounting") or {}).get("reported_total_cost_usd"),
            "cost_basis": details.get("cost_basis"), "models_seen": details.get("models_seen"),
            "requests": requests}


def _effort_of(request: dict):
    """The effort a request body carries: output_config.effort, thinking.effort or a top-level effort."""
    for holder in (request.get("output_config"), request.get("thinking"), request):
        if isinstance(holder, dict) and isinstance(holder.get("effort"), str):
            return holder["effort"]
    return None


def check(checks, check_id, ok, detail, *, required=True):
    checks.append({"id": check_id, "required": required, "ok": bool(ok), "detail": detail})


# ---------------------------------------------------------------- the rehearsal

def rehearse(host, mock_module, *, pinned_model, effort, tools, cap_usd, max_retries, token, broker=None,
             credential_mode="oauth", catalog_rates=None, sessions=None) -> dict:
    """Run the scripted sessions through ``host`` against a fresh mock and return the HP-13 record
    {schema_version, probe, ok, credential_mode, api_key_source_checked, checks, sessions, cli_price_per_mtok,
    pricing_eligible, settings, cli_geo_multiplier, catalog_rates, mock_sha256}. ``ok`` is true when every required
    check passed. ``token`` is the DUMMY credential the host injects (swept for afterwards, and searched for during
    session (a)); ``catalog_rates`` ({kind: rate}, the entry live.catalog_entry located in the pinned binary) makes
    the pin eligible when it equals the measured rates exactly. ``sessions`` limits the run to named sessions
    (tests)."""
    require(credential_mode in CREDENTIAL_MODES, f"rehearsal: credential_mode one of {list(CREDENTIAL_MODES)}")
    require(isinstance(token, str) and credentials.TOKEN.fullmatch(token), "rehearsal: a dummy token is required")
    wanted = set(sessions or ("tool_path", "planted_rc", "pricing", "budget", "settings", "retries"))
    tools = list(tools)
    checks, record_sessions, roots = [], {}, {}
    mock = mock_module.MockMessagesAPI()
    own_broker = broker is None
    broker = broker or ProbeBroker()
    base = mock.start()
    try:   # both servers are threads of this process, stopped by handle in the finally
        endpoint = broker.start() if own_broker else getattr(broker, "endpoint", None)

        def launch(session: Session, ctx: SessionContext) -> dict:
            ctx.probe.mkdir(parents=True, exist_ok=True)
            mock.set_script(session.turns)
            broker.clear()
            result = host.run(ctx, prompt=session.prompt, model=session.model or pinned_model, env=session.env,
                              credential_mode=credential_mode, base_url=base, mock_port=mock.port,
                              task_endpoint=endpoint, task_token=broker.token)
            requests = mock.requests()
            record_sessions[session.name] = {**_summary(result, requests), "task_calls": broker.calls(),
                                             "env_overrides": dict(session.env)}
            for label, root in ctx.sweep_roots.items():
                roots[f"{session.name}:{label}"] = str(root)
            return result

        rates = {}
        settings = {}
        if "tool_path" in wanted:
            ctx = host.prepare("tool_path")
            (ctx.outside / "rehearsal-planted.txt").write_text("SYNTHETIC outside file\n")
            result = launch(tool_path_session(mock_module, ctx, token), ctx)
            _tool_path_checks(checks, result, record_sessions["tool_path"], ctx, tools=tools, effort=effort)
            found = (_read(ctx.probe / BASH_PYTHON) or "").split()
            settings["bash_python3"] = {"path": found[0] if found else None,
                                        "version": found[1] if len(found) > 1 else None}
        if "planted_rc" in wanted:
            ctx = host.prepare("planted_rc")
            result = launch(planted_rc_session(mock_module, ctx), ctx)
            _planted_checks(checks, result, record_sessions["planted_rc"], ctx)
            settings["bash_cwd_reset"] = _cwd_outcome(ctx)
        geo_multipliers = None
        if "pricing" in wanted:
            for model in (pinned_model, CONTROL_MODEL):
                for kind in PRICE_KINDS:
                    ctx = host.prepare(f"pricing-{kind}")
                    result = launch(pricing_session(mock_module, kind, model), ctx)
                    reported = record_sessions[f"pricing:{model}:{kind}"]["reported_total_cost_usd"]
                    rates.setdefault(model, {})[kind] = reported
            eligible, detail = pricing_eligibility(rates, pinned_model, catalog_rates)
            check(checks, "d.pricing_differs_from_unknown", eligible, detail)
            measured = {}
            for geo in GEOS:
                ctx = host.prepare(f"pricing-geo-{geo}")
                launch(pricing_session(mock_module, "input_tokens", pinned_model, geo=geo), ctx)
                measured[geo] = _geo_multiplier(
                    record_sessions[f"pricing:{pinned_model}:input_tokens:geo_{geo}"]["reported_total_cost_usd"],
                    (rates.get(pinned_model) or {}).get("input_tokens"))
            geo_multipliers = {g: m for g, m in measured.items() if m is not None}
            check(checks, "d.geo_multipliers", len(geo_multipliers) == len(GEOS), {"measured": measured},
                  required=False)
        if "budget" in wanted:
            usage, per_turn_cost, crossing = budget_usage(cap_usd, rates.get(pinned_model) or {})
            ctx = host.prepare("budget")
            result = launch(budget_session(mock_module, usage), ctx)
            _budget_checks(checks, result, record_sessions["budget"], usage=usage, per_turn_cost=per_turn_cost,
                           crossing=crossing)
        if "settings" in wanted:
            ctx = host.prepare("settings")
            result = launch(settings_session(mock_module, ctx), ctx)
            settings.update(_settings_outcomes(result))
        if "retries" in wanted:
            ctx = host.prepare("retries")
            launch(retries_session(mock_module), ctx)
            settings["max_retries"] = _retry_outcome(record_sessions["retries"]["requests"], max_retries)
    finally:
        mock.stop()
        if own_broker:
            broker.stop()
    swept = credentials.sweep(roots, token.encode(), redact=False) if roots else None
    if swept is not None:
        check(checks, "sweep.dummy_token_nowhere", not swept["hits"] and not swept["incomplete"],
              {"hits": swept["hits"], "incomplete": swept["incomplete"], "skipped": swept["skipped"][:20]})
    record = {"schema_version": 1, "probe": "HP-13", "credential_mode": credential_mode,
              "api_key_source_checked": credential_mode == "oauth", "pinned_model": pinned_model,
              "effort": effort, "cap_usd": cap_usd, "checks": checks, "sessions": record_sessions,
              "cli_price_per_mtok": rates, "pricing_eligible": None, "settings": settings,
              "cli_geo_multiplier": geo_multipliers or None,
              "catalog_rates": catalog_rates, "mock_sha256": _module_sha256(mock_module)}
    pricing = next((c for c in checks if c["id"] == "d.pricing_differs_from_unknown"), None)
    record["pricing_eligible"] = None if pricing is None else pricing["ok"]
    record["ok"] = all(c["ok"] for c in checks if c["required"]) and bool(checks)
    return record


def oauth_refused(record: dict) -> bool:
    """Whether every session of an OAuth rehearsal failed authentication before any main request: the cue to
    rerun it with credential_mode="api_key" (and record that apiKeySource goes unchecked until HP-09 or run 1)."""
    sessions = list(record["sessions"].values())
    return record["credential_mode"] == "oauth" and bool(sessions) and all(
        "host_auth_failed" in s["flags"] and not any(r.get("role") == "main" for r in s["requests"])
        for s in sessions)


# ---------------------------------------------------------------- verdicts

def _tool_path_checks(checks, result, summary, ctx, *, tools, effort):
    names = _read(ctx.probe / "bash-env-names.txt")
    listed = set(names.split()) if names is not None else set()
    check(checks, "a.bash_env_names", names is not None and "RAVEL_TASK_TOKEN" in listed
          and not listed & set(TOKEN_NAMES),
          {"listed": names is not None, "task_token": "RAVEL_TASK_TOKEN" in listed,
           "credential_names": sorted(listed & set(TOKEN_NAMES))})
    rc = (_read(ctx.probe / "ravel-task.rc") or "").strip()
    calls = summary["task_calls"]
    check(checks, "a.task_call", rc == "0" and any(c["authenticated"] and c["op"] == "inputs" for c in calls),
          {"rc": rc or None, "calls": [{k: c[k] for k in ("authenticated", "op")} for c in calls]})
    reported = [c["client_env_names"] for c in calls if isinstance(c.get("client_env_names"), list)]
    check(checks, "a.client_env_report", not any(set(r) & set(TOKEN_NAMES) for r in reported),
          {"reports": len(reported)}, required=False)
    snapshots = sorted((ctx.config_dir / "shell-snapshots").glob("snapshot-*")) \
        if (ctx.config_dir / "shell-snapshots").is_dir() else []
    listing = _read(ctx.probe / SNAPSHOT_LISTING)
    during = sorted(n for n in (listing or "").split() if n.startswith("snapshot-"))
    check(checks, "a.shell_snapshot", bool(snapshots) or bool(during),
          {"snapshots": len(snapshots), "during_session": during, "listed": listing is not None})
    flags = set(_flags(result))
    check(checks, "a.init_matches", not flags & set(INIT_FLAGS), {"init": summary["init"],
                                                                "flags": sorted(flags & set(INIT_FLAGS))})
    main = [r for r in summary["requests"] if r.get("role") == "main"]
    offered = [r.get("tools") for r in main]
    check(checks, "a.request_tools", bool(main) and all(o == sorted(tools) for o in offered),
          {"main_requests": len(main), "offered": sorted({tuple(o or ()) for o in offered})})
    check(checks, "a.no_web_tools", not any(set(o or ()) & set(WEB_TOOLS) for o in offered), {})
    efforts = sorted({str(_effort_of(r)) for r in main})
    check(checks, "a.request_effort", bool(main) and efforts == [effort],
          {"efforts": efforts, "body_keys": sorted({k for r in main for k in (r.get("body_keys") or [])})})
    fast = [r.get("speed") for r in main if r.get("speed") is not None]
    check(checks, "a.no_fast_speed", "fast_mode_used" not in flags and "fast" not in fast, {"speeds": fast})
    ttls = sorted({t for r in summary["requests"] for t in (r.get("cache_ttls") or [])})
    check(checks, "a.cache_ttl_not_1h", "1h" not in ttls and "cache_write_1h_reported" not in flags,
          {"cache_ttls": ttls, "pinned": "FORCE_PROMPT_CACHING_5M"})
    scan = _read(ctx.probe / MIDRUN_SCAN)
    holding = [line for line in (scan or "").splitlines() if line.strip() and line.strip() != "scanned"]
    check(checks, "a.no_token_copy_mid_run", scan is not None and "scanned" in scan.split() and not holding,
          {"ran": scan is not None, "files_holding_the_dummy_token": len(holding)})
    edited = _read(ctx.workspace / "output" / "rehearsal-file.txt")
    check(checks, "a.file_tools", edited == "SYNTHETIC rehearsal EDITED", {"content_ok": edited ==
                                                                          "SYNTHETIC rehearsal EDITED"})
    outside = [c for c in tool_calls(result) if c["name"] in ("Read", "Write")
               and str((c["input"] or {}).get("file_path", "")).startswith(str(ctx.outside))]
    check(checks, "a.outside_cwd_recorded", True, {"calls": [{"name": c["name"], "is_error": c["is_error"]}
                                                            for c in outside]}, required=False)
    check(checks, "a.other_endpoints_recorded", True,
          {"paths": sorted({r["path"] for r in summary["requests"] if r.get("role") == "other"})}, required=False)


def _planted_checks(checks, result, summary, ctx):
    log = _read(ctx.probe / "planted.log") or ""
    fired = sorted({line[3:].split()[0] for line in log.splitlines() if line.startswith("== ") and line[3:].split()})
    names = {line.strip() for line in log.splitlines() if line and not line.startswith("== ")}
    check(checks, "b.no_credential_name_in_hooks", not names & set(TOKEN_NAMES),
          {"hooks_fired": fired, "home_hooks_fired": home_hooks(fired),
           "credential_names": sorted(names & set(TOKEN_NAMES))})
    check(checks, "b.workspace_git_denied", True, {"attempt": (_read(ctx.probe / "workspace-git.txt") or "")[:200]},
          required=False)
    repo = ctx.workspace / "output" / ".git" / "config"
    check(checks, "b.output_repository_planted", repo.is_file(),
          {"repo_config": repo.is_file(), "repo_hooks_fired": [f for f in fired if f not in home_hooks(fired)]})


def _cwd_outcome(ctx) -> dict:
    """Whether the Bash tool's working directory went back to the workspace one command after a ``cd output``
    (CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR effective) or stayed in output/ (ignored)."""
    seen = (_read(ctx.probe / CWD_AFTER) or "").strip()
    if not seen:
        return {"outcome": UNOBSERVED}
    import os
    workspace = os.path.realpath(ctx.workspace)
    real = os.path.realpath(seen)
    return {"outcome": EFFECTIVE if real == workspace else IGNORED if real == os.path.join(workspace, "output")
            else UNOBSERVED, "cwd": "workspace" if real == workspace else "output"
            if real == os.path.join(workspace, "output") else "other"}


def _geo_multiplier(geo_cost, input_rate):
    """The CLI's cost of 1,000,000 input tokens reported with one inference_geo over its plain input rate, or None."""
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (geo_cost, input_rate)) \
            or input_rate <= 0:
        return None
    return round(geo_cost / input_rate, 9)


def _same_rate(a, b) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) \
        and not isinstance(b, bool) and abs(a - b) <= 1e-9 * max(1.0, abs(b))


def pricing_eligibility(rates: dict, pinned_model: str, catalog_rates=None) -> tuple:
    """(eligible, detail): the pin prices its model with its own entry when any measured rate differs from the
    unknown control's, or when the catalog entry located in the pinned binary (``catalog_rates``, {kind: rate} for
    every PRICE_KINDS) equals the measured rates of the pinned model exactly (H-27). Equal or unmeasured rates
    without a matching catalog entry are ineligible; so is a catalog entry that differs from what the pin applies."""
    pinned, control = rates.get(pinned_model) or {}, rates.get(CONTROL_MODEL) or {}
    measured = {k: (pinned.get(k), control.get(k)) for k in PRICE_KINDS}
    complete = all(isinstance(a, (int, float)) and isinstance(b, (int, float)) for a, b in measured.values())
    differs = complete and any(not _same_rate(a, b) for a, b in measured.values())
    catalog_matches = None
    if catalog_rates is not None:
        catalog_matches = isinstance(catalog_rates, dict) and all(
            _same_rate(pinned.get(k), catalog_rates.get(k)) for k in PRICE_KINDS)
    detail = {"pinned": pinned, "control": control, "complete": complete, "differs": differs,
              "catalog_rates": catalog_rates, "catalog_matches_measured": catalog_matches}
    return bool(differs or catalog_matches), detail


def _budget_checks(checks, result, summary, *, usage, per_turn_cost, crossing):
    answered = [r for r in summary["requests"] if r.get("role") == "main" and r.get("answered") == 200]
    stopped = summary["result_subtype"] == "error_max_budget_usd"
    within = crossing is not None and len(answered) <= crossing + 1
    check(checks, "c.budget_cutoff", stopped and within,
          {"result_subtype": summary["result_subtype"], "answered": len(answered), "crossing_turn": crossing,
           "reported_total_cost_usd": summary["reported_total_cost_usd"], "per_turn_usage": usage,
           "per_turn_cost_usd": per_turn_cost})


def _settings_outcomes(result) -> dict:
    calls = [c for c in tool_calls(result) if c["name"] == "Bash"]
    background = next((c for c in calls if (c["input"] or {}).get("run_in_background")), None)
    timeout = next((c for c in calls if (c["input"] or {}).get("timeout")), None)
    out = {}
    if background is None or background["text"] is None:
        out["background_tasks"] = {"outcome": UNOBSERVED}
    else:
        ran_here = "ravel-background-probe" in background["text"]
        out["background_tasks"] = {"outcome": EFFECTIVE if ran_here or background["is_error"] else IGNORED,
                                   "is_error": background["is_error"], "excerpt": background["text"][:300]}
    if timeout is None or timeout["text"] is None:
        out["bash_timeout_clamp"] = {"outcome": UNOBSERVED}
    else:
        late = "ravel-timeout-probe" in timeout["text"]
        out["bash_timeout_clamp"] = {"outcome": IGNORED if late else EFFECTIVE, "is_error": timeout["is_error"],
                                     "excerpt": timeout["text"][:300], "session_env": dict(SETTINGS_TIMEOUTS)}
    return out


def _retry_outcome(requests, max_retries) -> dict:
    first = [r for r in requests if r.get("role") == "main" and r.get("position") == 0]
    overloaded = sum(1 for r in first if r.get("answered") == 529)
    attempts = len(first)
    if not first:
        return {"outcome": UNOBSERVED, "attempts": 0}
    outcome = EFFECTIVE if 1 < attempts <= max_retries + 1 and overloaded == attempts else \
        IGNORED if attempts > max_retries + 1 else UNOBSERVED
    return {"outcome": outcome, "attempts": attempts, "overloaded": overloaded, "max_retries": max_retries}


def _module_sha256(module):
    """The sha256 of the mock module's file as loaded (None when it has no file)."""
    path = Path(getattr(module, "__file__", None) or "")
    return sha256_file(path) if path.name and path.is_file() else None


def required_failures(record: dict) -> list:
    return [c["id"] for c in record["checks"] if c["required"] and not c["ok"]]


__all__ = ["CONTROL_MODEL", "ProbeBroker", "SessionContext", "budget_usage", "load_mock", "oauth_refused",
           "pricing_eligibility",
           "rehearse", "required_failures", "tool_calls"]
