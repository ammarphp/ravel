#!/usr/bin/env python3
"""SYNTHETIC stand-in for the Claude Code CLI on the runner's live path (smoke spec WI-2), used only by the tests of
the real-host launch: build-live pins it as the host binary, the coordinator launches it under the real-host profile
with a DUMMY credential, and it behaves like ``claude -p --output-format stream-json --verbose``. It contacts only
127.0.0.1 (the task service and, in the proxy modes, the launch's allowlist proxy); it never reaches a model.

What it models: ``--version``; the prompt on stdin; ``system/init`` from its argv (apiKeySource "none" with an OAuth
token in its environment); a shell snapshot under CLAUDE_CONFIG_DIR; one Bash call (``/bin/zsh -c``, the OAuth token
removed from the child's environment as the CLI's P1 does) that runs ``bin/ravel-task inputs`` and one that submits
a minimal refusal; the assistant and result records with ``total_cost_usd`` from its own price table and
``modelUsage``. The test writes this file with its interpreter's shebang (``-I``) and a version in place of the
placeholder. The mode is read from ``inputs/mock-mode.txt`` in the workspace (a test plants it; "clean" without):

- ``clean``: as above.
- ``leak_child``: the Bash child keeps the OAuth token (the task client then reports its name).
- ``leak_stdout``: the token appears in an assistant message. ``leak_config``: the token is written to
  ``.credentials.json`` in the config dir. ``leak_hex``: its hex encoding is written into the config dir.
  ``leak_name``: a file in output/ is NAMED with the token. ``leak_proxy``: the token is sent as a CONNECT target.
- ``auth_fail``: a "Not logged in" error from the CLI itself (model ``<synthetic>``), an is_error result.
- ``web``: init lists WebSearch. ``extra_tool``: init lists Glob. ``model_swap``: an assistant message from another
  model. ``fast_mode``: the result reports fast speed. ``extra_plugin``: init lists a plugin besides the builtin
  agents-md one every 2.1.281 init lists. ``extra_skill`` and ``extra_agent``: init lists a skill or an agent that
  2.1.281 does not ship (by default it lists some of the builtin ones, as the real pin does). ``read_client``: the
  subject Reads bin/ravel-task (whose source holds the task client's missing-token text) before its Bash calls
  succeed.
- ``account_config``: the host writes account fields into its config directory's ``.claude.json`` (an
  ``oauthAccount`` object), as a CLI could after authenticating. ``spend <usd>``: the result reports that cost (and
  modelUsage tokens that price to it) with a success subtype; ``spend_capped <usd>`` the same with
  ``error_max_budget_usd``, the host's own ceiling.
- ``proxy_other <target>``: CONNECT to a non-allowlisted target through HTTPS_PROXY. ``proxy_ok <target>``: CONNECT to
  the allowlisted target, send a line and read the echo. ``proxy_child <target>``: a child process, not the leader,
  CONNECTs to the allowlisted target.
- ``fifo_in_state``: plants a FIFO in the config dir. ``rlimit``: writes its core-file limits to output/rlimit.json.
- ``sleep``: starts a sleeping child and sleeps (a coordinator interrupted mid-launch).

The dry start (HP-09): with ``--settings``, whatever the mode, it runs the SessionStart hook commands (``/bin/sh -c``,
the OAuth token removed as for any child), then tries the API as the real CLI would, a CONNECT to api.anthropic.com:443
through HTTPS_PROXY (HP-09's allowlist denies everything, so nothing leaves 127.0.0.1), and ends with an error result.
Without ``--settings`` it never names that host (the runner's proxy allowlists it). Standard library only.
"""
import json
import os
import socket
import subprocess
import sys
import time
import uuid

VERSION = "__MOCK_VERSION__"
MODELS = ["claude-synthetic-5"]                 # the model ids this SYNTHETIC binary "knows" (model_in_binary)
PRICES = {"claude-synthetic-5": (2.0, 10.0)}    # USD per million input and output tokens
FALLBACK = (5.0, 25.0)
TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
USAGE = {"input_tokens": 1000, "output_tokens": 100}
LOCAL_MODEL = "<synthetic>"
BUILTIN_PLUGINS = [{"name": "agents-md", "path": "builtin", "source": "agents-md@builtin"}]   # as 2.1.281 lists it
BUILTIN_SKILLS = ["dataviz", "loop", "schedule"]                          # some of the skills 2.1.281 lists
BUILTIN_AGENTS = ["claude", "Explore", "general-purpose", "Plan", "statusline-setup"]   # the agents 2.1.281 lists


def emit(record):
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def options(argv):
    opts = {"tools": "", "model": None, "permission_mode": "default", "session_id": None, "effort": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--disallowedTools", "--allowedTools"):
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                i += 1
            continue
        if arg in ("--model", "--permission-mode", "--session-id", "--tools", "--effort", "--max-turns",
                   "--max-budget-usd", "--setting-sources", "--output-format", "--settings"):
            opts[arg[2:].replace("-", "_")] = argv[i + 1]
            i += 2
            continue
        i += 1
    return opts


def mode():
    try:
        with open(os.path.join(os.getcwd(), "inputs", "mock-mode.txt")) as handle:
            words = handle.read().split()
    except OSError:
        words = []
    return (words[0] if words else "clean"), (words[1] if len(words) > 1 else None)


def connect(target, payload=b""):
    proxy = os.environ.get("HTTPS_PROXY", "")
    port = int(proxy.rsplit(":", 1)[1].strip("/"))
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
        status = sock.recv(128).split(b"\r\n")[0].decode(errors="replace")
        echoed = b""
        if " 200 " in status + " " and payload:
            sock.sendall(payload)
            echoed = sock.recv(128)
    return status, echoed.decode(errors="replace")


def bash(command, env, n):
    """One Bash tool call: the tool_use, the command under /bin/zsh -c, the tool_result."""
    use = f"toolu_mock_{n}"
    emit({"type": "assistant", "message": {"id": f"msg_mock_tool_{n}", "model": MODEL, "role": "assistant",
                                           "content": [{"type": "tool_use", "id": use, "name": "Bash",
                                                        "input": {"command": command}}], "usage": USAGE},
          "parent_tool_use_id": None, "session_id": SESSION})
    done = subprocess.run(["/bin/zsh", "-c", command], env=env, capture_output=True, text=True, timeout=120)
    emit({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": use, "is_error": done.returncode != 0,
         "content": (done.stdout + done.stderr)[-4000:]}]}, "parent_tool_use_id": None, "session_id": SESSION})
    return done


def dry_start(settings):
    """HP-09: the SessionStart hooks, then the API through the proxy (denied), then an error result."""
    hook_env = {k: v for k, v in os.environ.items() if k != TOKEN}
    for group in json.loads(settings).get("hooks", {}).get("SessionStart", []):
        for hook in group.get("hooks", []):
            subprocess.run(["/bin/sh", "-c", hook["command"]], env=hook_env, timeout=30)
    try:
        status = connect("api.anthropic.com:443")[0]
    except OSError as exc:
        status = f"{exc.__class__.__name__}"
    text = f"API Error: Connection error ({status})"
    emit({"type": "result", "subtype": "success", "is_error": True, "num_turns": 0, "total_cost_usd": 0,
          "usage": {"input_tokens": 0, "output_tokens": 0}, "modelUsage": {}, "result": text, "session_id": SESSION,
          "permission_denials": []})
    return 1


def main():
    global MODEL, SESSION
    argv = sys.argv[1:]
    if "--version" in argv:
        print(f"{VERSION} (Claude Code)")
        return 0
    opts = options(argv)
    sys.stdin.read()
    name, arg = mode()
    MODEL, SESSION = opts["model"], opts["session_id"] or str(uuid.uuid4())
    tools = [t for t in opts["tools"].split(",") if t] + (["WebSearch"] if name == "web" else []) \
        + (["Glob"] if name == "extra_tool" else [])
    source = "none" if TOKEN in os.environ and "ANTHROPIC_API_KEY" not in os.environ else \
        "ANTHROPIC_API_KEY" if "ANTHROPIC_API_KEY" in os.environ else None
    external = {"manual": "default"}.get(opts["permission_mode"], opts["permission_mode"])
    emit({"type": "system", "subtype": "init", "session_id": SESSION, "claude_code_version": VERSION, "model": MODEL,
          "tools": tools, "permissionMode": external, "apiKeySource": source, "mcp_servers": [],
          "plugins": BUILTIN_PLUGINS + ([{"name": "synthetic-extra", "path": "/synthetic/plugin",
                                          "source": "synthetic-extra@local"}] if name == "extra_plugin" else []),
          "skills": BUILTIN_SKILLS + (["synthetic-planted-skill"] if name == "extra_skill" else []),
          "agents": BUILTIN_AGENTS + (["synthetic-planted-agent"] if name == "extra_agent" else []),
          "cwd": os.getcwd()})
    if opts.get("settings"):
        return dry_start(opts["settings"])
    config, token = os.environ["CLAUDE_CONFIG_DIR"], os.environ.get(TOKEN, "")
    os.makedirs(os.path.join(config, "shell-snapshots"), exist_ok=True)
    with open(os.path.join(config, "shell-snapshots", f"snapshot-zsh-{int(time.time())}.sh"), "w") as handle:
        handle.write("# SYNTHETIC shell snapshot\n")
    if name == "fifo_in_state":
        os.mkfifo(os.path.join(config, "planted.fifo"))
    if name == "leak_config":
        with open(os.path.join(config, ".credentials.json"), "w") as handle:
            json.dump({"claudeAiOauth": {"accessToken": token}}, handle)
    if name == "account_config":
        with open(os.path.join(config, ".claude.json"), "w") as handle:
            json.dump({"numStartups": 1, "oauthAccount": {"emailAddress": "SYNTHETIC@example.invalid"}}, handle)
    if name == "leak_hex":
        with open(os.path.join(config, "cache.bin"), "w") as handle:
            handle.write("SYNTHETIC cache " + token.encode().hex())
    if name == "leak_name":
        with open(os.path.join(os.getcwd(), "output", f"note-{token}.txt"), "w") as handle:
            handle.write("SYNTHETIC note\n")
    if name == "leak_proxy":
        try:
            connect(token)
        except OSError:
            pass
    if name == "rlimit":
        import resource
        with open(os.path.join(os.getcwd(), "output", "rlimit.json"), "w") as handle:
            json.dump({"core": list(resource.getrlimit(resource.RLIMIT_CORE))}, handle)
    if name == "sleep":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], stdin=subprocess.DEVNULL)
        time.sleep(600)
    network = None
    if name in ("proxy_other", "proxy_ok"):
        network = connect(arg, b"SYNTHETIC ping\n" if name == "proxy_ok" else b"")
    if name == "proxy_child":
        code = ("import os, socket; p = int(os.environ['HTTPS_PROXY'].rsplit(':', 1)[1].strip('/')); "
                "s = socket.create_connection(('127.0.0.1', p), timeout=10); "
                f"s.sendall(b'CONNECT {arg} HTTP/1.1\\r\\n\\r\\n'); print(s.recv(128).split(b'\\r\\n')[0].decode())")
        network = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                                 timeout=30).stdout.strip()
    if name == "auth_fail":
        text = "Not logged in · Please run /login"
        emit({"type": "assistant", "message": {"id": "msg_mock_err", "model": LOCAL_MODEL, "role": "assistant",
                                               "content": [{"type": "text", "text": text}],
                                               "usage": {"input_tokens": 0, "output_tokens": 0}},
              "error": "authentication_failed", "parent_tool_use_id": None, "session_id": SESSION})
        emit({"type": "result", "subtype": "success", "is_error": True, "num_turns": 1, "total_cost_usd": 0,
              "usage": {"input_tokens": 0, "output_tokens": 0}, "modelUsage": {}, "result": text,
              "session_id": SESSION, "permission_denials": []})
        return 1
    child_env = dict(os.environ)
    if name != "leak_child":
        child_env.pop(TOKEN, None)
    workspace = os.getcwd()
    if name == "read_client":   # the Read tool's result is the client's source, which holds the missing-token text
        with open(os.path.join(workspace, "bin", "ravel-task")) as handle:
            source = handle.read()
        emit({"type": "assistant", "message": {"id": "msg_mock_read", "model": MODEL, "role": "assistant",
                                               "content": [{"type": "tool_use", "id": "toolu_mock_read", "name": "Read",
                                                            "input": {"file_path": "bin/ravel-task"}}],
                                               "usage": USAGE}, "parent_tool_use_id": None, "session_id": SESSION})
        emit({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_mock_read", "content": source[:20000]}]},
            "parent_tool_use_id": None, "session_id": SESSION})
    bash(f"{workspace}/bin/ravel-task inputs", child_env, 1)
    submission = os.path.join(workspace, "tmp", "mock-submission.json")
    with open(submission, "w") as handle:
        json.dump({"claims": [], "report_text": "SYNTHETIC mock host: no deliverable.",
                   "refusal": {"text": "SYNTHETIC mock host: it declines the request (a test fixture)."},
                   "final": True}, handle)
    bash(f"{workspace}/bin/ravel-task submit {submission}", child_env, 2)
    text = "SYNTHETIC mock host: declined."
    if name == "leak_stdout":
        text += " credential " + token
    if network is not None:
        text += f" network: {network}"
    answered = "claude-other-synthetic-9" if name == "model_swap" else MODEL
    usage = {**USAGE, **({"speed": "fast"} if name == "fast_mode" else {})}
    emit({"type": "assistant", "message": {"id": "msg_mock_text", "model": answered, "role": "assistant",
                                           "content": [{"type": "text", "text": text}], "usage": usage},
          "parent_tool_use_id": None, "session_id": SESSION})
    rates = PRICES.get(MODEL, FALLBACK)
    tokens = {"input": USAGE["input_tokens"], "output": USAGE["output_tokens"]}
    cost = (tokens["input"] * rates[0] + tokens["output"] * rates[1]) / 1e6
    subtype = "success"
    if name in ("spend", "spend_capped"):   # a reported cost, with modelUsage tokens that price to it exactly
        cost, subtype = float(arg), "success" if name == "spend" else "error_max_budget_usd"
        tokens = {"input": round(cost * 1e6 / rates[0]), "output": 0}
    emit({"type": "result", "subtype": subtype, "is_error": subtype != "success", "num_turns": 3,
          "total_cost_usd": cost, "usage": usage,
          "modelUsage": {MODEL: {"inputTokens": tokens["input"], "outputTokens": tokens["output"],
                                 "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0, "webSearchRequests": 0,
                                 "costUSD": cost}},
          "result": text, "session_id": SESSION, "permission_denials": []})
    return 0


if __name__ == "__main__":
    sys.exit(main())
