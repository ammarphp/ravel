#!/usr/bin/env python3
"""SYNTHETIC stand-in for the Claude Code CLI in ``-p --output-format stream-json`` mode, driven by the mock
Messages API (tests/governance/mock_messages_api.py). It exists to exercise the HP-13 rehearsal harness
(benchmarks/governance/rehearsal.py) without a real host; it contacts nothing but ``ANTHROPIC_BASE_URL``.

What it models, from the smoke spec's facts: ``--version``; the prompt on stdin; a ``system/init`` record built
from its argv and credential (apiKeySource "none" for CLAUDE_CODE_OAUTH_TOKEN, "ANTHROPIC_API_KEY" for a key); a
shell snapshot under CLAUDE_CONFIG_DIR; one streamed request per turn offering the ``--tools`` set with the
``--effort`` level; retries of HTTP 529 up to CLAUDE_CODE_MAX_RETRIES; Bash (CLAUDE_CODE_SHELL, the OAuth token
removed from the child environment as the CLI's P1 does, BASH_DEFAULT_TIMEOUT_MS and BASH_MAX_TIMEOUT_MS,
background runs refused into the foreground under CLAUDE_CODE_DISABLE_BACKGROUND_TASKS), Read, Write and Edit;
a cost estimate from its own price table (a model it does not know is priced at the fallback rates, costBasis
"unknown"); the ``--max-budget-usd`` check between messages; and the result record. The test writes this file
with its interpreter's shebang, a version and a MODE in place of the placeholders below. The modes other than
"clean" each break one expectation the rehearsal must catch: "leak_child" keeps the OAuth token in the Bash
child's environment, "no_effort" sends no effort, "no_snapshot" writes no shell snapshot, "flat_prices" prices
every model at the fallback rates, "ignore_budget" never stops at the cap and "leak_file" writes the token into
its config directory. "snapshot_cleanup" is no fault: it removes its shell snapshot when the session ends, as the
real 2.1.281 does (observed 2026-09-26), so only a listing taken during the session can see it. "equal_rates" is
no fault either: it prices an unknown model at the pinned model's rates, as the real 2.1.281 prices an unknown id at
its default model's tier (observed 2026-09-26, H-27), so only the catalog entry below can make the pin eligible.
"cache_1h" asks for the 1-hour prompt-cache TTL whatever FORCE_PROMPT_CACHING_5M says. "extra_plugin" and
"extra_skill" list a plugin or a skill in system/init that 2.1.281 does not ship. Like 2.1.281 it lists the
builtin agents-md plugin in system/init, multiplies a request's cost by 1.1 when its usage reports inference_geo
"us", and carries a model catalog in its bytes (CATALOG, the 2.1.281 shape). Standard library only.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

VERSION = "__MOCK_VERSION__"
MODE = "__MOCK_MODE__"
# USD per million tokens: input, output, cache write, cache read. The fallback is the one IHs applies (F12).
PRICES = {"claude-synthetic-5": (2.0, 10.0, 2.5, 0.2)}
FALLBACK = (5.0, 25.0, 6.25, 0.5)
GEO_MULTIPLIER = {"us": 1.1}
BUILTIN_PLUGINS = [{"name": "agents-md", "path": "builtin", "source": "agents-md@builtin"}]
# The model catalog as the 2.1.281 bundle carries it (live.catalog_entry locates the tier and its rates in these bytes).
CATALOG = ('{id:"claude-synthetic-5",family:"synthetic",display_name:"Synthetic 5",pricing:"tier_2_10",'
           'capabilities:["effort"]} pricing_tiers:{tier_2_10:{input:2,output:10,cache_write_5m:2.5,cache_write_1h:4,'
           'cache_read:0.2,web_search:0.01},tier_5_25:{input:5,output:25,cache_write_5m:6.25,cache_write_1h:10,'
           'cache_read:0.5,web_search:0.01}}')
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def emit(record):
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def options(argv):
    opts = {"tools": "", "effort": None, "max_turns": 100, "max_budget_usd": None, "permission_mode": "default",
            "session_id": None, "model": None}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("--disallowedTools", "--allowedTools"):
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                i += 1
            continue
        if arg in ("--model", "--effort", "--max-turns", "--max-budget-usd", "--permission-mode", "--session-id",
                   "--tools", "--setting-sources", "--output-format"):
            opts[arg[2:].replace("-", "_")] = argv[i + 1]
            i += 2
            continue
        i += 1
    return opts


def price(model, usage):
    unknown = PRICES["claude-synthetic-5"] if MODE == "equal_rates" else FALLBACK
    rates = FALLBACK if MODE == "flat_prices" else PRICES.get(model, unknown)
    cost = sum(usage.get(k, 0) * r for k, r in zip(("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                                    "cache_read_input_tokens"), rates)) / 1e6
    return cost * GEO_MULTIPLIER.get(usage.get("inference_geo"), 1.0)


def parse_sse(data):
    events = []
    for chunk in data.decode("utf-8").split("\n\n"):
        name, payload = None, []
        for line in chunk.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                payload.append(line[5:].strip())
        if name is not None:
            events.append((name, json.loads("\n".join(payload)) if payload else None))
    return events


def message_from(events):
    message, blocks, partial = None, {}, {}
    for name, data in events:
        if name == "message_start":
            message = data["message"]
        elif name == "content_block_start":
            blocks[data["index"]] = dict(data["content_block"])
            partial[data["index"]] = ""
        elif name == "content_block_delta":
            delta = data["delta"]
            if delta["type"] == "text_delta":
                blocks[data["index"]]["text"] += delta["text"]
            elif delta["type"] == "input_json_delta":
                partial[data["index"]] += delta["partial_json"]
        elif name == "message_delta":
            message["stop_reason"] = data["delta"]["stop_reason"]
            message["usage"] = {**message["usage"], **data["usage"]}
    for index, block in blocks.items():
        if block["type"] == "tool_use":
            block["input"] = json.loads(partial[index] or "{}")
    message["content"] = [blocks[i] for i in sorted(blocks)]
    return message


def truthy(name):
    return os.environ.get(name, "").strip().lower() not in ("", "0", "false", "no", "off")


def run_tool(block):
    name, spec = block["name"], block["input"]
    try:
        if name == "Bash":
            default = int(os.environ.get("BASH_DEFAULT_TIMEOUT_MS", "120000"))
            ceiling = int(os.environ.get("BASH_MAX_TIMEOUT_MS", "600000"))
            timeout = min(int(spec.get("timeout") or default), ceiling) / 1000
            note = ""
            if spec.get("run_in_background"):
                if not truthy("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"):
                    return "Command running in background with ID: bash_synthetic_1", False
                note = "(background tasks are disabled: ran in the foreground)\n"
            child_env = {k: v for k, v in os.environ.items()
                         if k != "CLAUDE_CODE_OAUTH_TOKEN" or MODE == "leak_child"}   # P1 strips the token
            shell = os.environ.get("CLAUDE_CODE_SHELL", "/bin/zsh")
            try:
                done = subprocess.run([shell, "-c", spec["command"]], env=child_env, stdin=subprocess.DEVNULL,
                                      capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                return f"{note}Command timed out after {timeout * 1000:.0f}ms", True
            out = (done.stdout + done.stderr).decode("utf-8", "replace")
            if done.returncode:
                return f"{note}{out}\nExit code {done.returncode}", True
            return note + out, False
        if name == "Read":
            with open(spec["file_path"], encoding="utf-8") as handle:
                return handle.read(), False
        if name == "Write":
            with open(spec["file_path"], "w", encoding="utf-8") as handle:
                handle.write(spec["content"])
            return f"File created successfully at: {spec['file_path']}", False
        if name == "Edit":
            with open(spec["file_path"], encoding="utf-8") as handle:
                current = handle.read()
            if spec["old_string"] not in current:
                return "String to replace not found in file.", True
            with open(spec["file_path"], "w", encoding="utf-8") as handle:
                handle.write(current.replace(spec["old_string"], spec["new_string"], 1))
            return f"The file {spec['file_path']} has been updated.", False
        return f"No such tool available: {name}", True
    except (OSError, KeyError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}", True


def main():
    if sys.argv[1:] == ["--version"]:
        print(f"{VERSION} (Claude Code)")
        return 0
    opts = options(sys.argv[1:])
    prompt = sys.stdin.read()
    base, oauth, key = (os.environ.get(n) for n in ("ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
                                                    "ANTHROPIC_API_KEY"))
    model, session = opts["model"], opts["session_id"]
    tools = [t for t in opts["tools"].split(",") if t]
    emit({"type": "system", "subtype": "init", "session_id": session, "claude_code_version": VERSION,
          "cwd": os.getcwd(), "tools": tools, "mcp_servers": [], "model": model,
          "permissionMode": opts["permission_mode"], "apiKeySource": "ANTHROPIC_API_KEY" if key else "none",
          "plugins": BUILTIN_PLUGINS + ([{"name": "synthetic-extra", "path": "/synthetic/plugin",
                                          "source": "synthetic-extra@local"}] if MODE == "extra_plugin" else []),
          "skills": ["dataviz", "loop"] + (["synthetic-planted-skill"] if MODE == "extra_skill" else []),
          "agents": ["general-purpose"], "slash_commands": []})
    snapshots = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "shell-snapshots")
    snapshot = os.path.join(snapshots, "snapshot-zsh-synthetic.sh")
    os.makedirs(snapshots, exist_ok=True)
    if MODE != "no_snapshot":
        with open(snapshot, "w") as handle:
            handle.write("# SYNTHETIC mock shell snapshot\nexport PATH=/usr/bin:/bin\n")
    if MODE == "leak_file" and oauth:
        with open(os.path.join(os.environ["CLAUDE_CONFIG_DIR"], ".credentials.json"), "w") as handle:
            json.dump({"claudeAiOauth": {"accessToken": oauth}}, handle)
    totals, cost, turns, final = dict.fromkeys(USAGE_KEYS, 0), 0.0, 0, None
    cap = float(opts["max_budget_usd"]) if opts["max_budget_usd"] else None

    def finish(subtype, is_error, text, code, **extra):
        if MODE == "snapshot_cleanup" and os.path.exists(snapshot):   # 2.1.281 unlinks its session snapshot at exit
            os.remove(snapshot)
        emit({"type": "result", "subtype": subtype, "is_error": is_error, "num_turns": turns, "result": text,
              "session_id": session, "total_cost_usd": cost, "usage": totals, "stop_reason": None,
              "modelUsage": {model: {"inputTokens": totals["input_tokens"], "outputTokens": totals["output_tokens"],
                                     "cacheReadInputTokens": totals["cache_read_input_tokens"],
                                     "cacheCreationInputTokens": totals["cache_creation_input_tokens"],
                                     "webSearchRequests": 0, "costUSD": cost,
                                     "costBasis": "list" if model in PRICES else "unknown"}},
              "permission_denials": [], **extra})
        return code

    if not base or not (oauth or key):
        return finish("success", True, "Not logged in · Please run /login", 1)
    messages = [{"role": "user", "content": prompt}]
    retries = int(os.environ.get("CLAUDE_CODE_MAX_RETRIES", "10"))
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if oauth:
        headers["authorization"] = "Bearer " + oauth
    else:
        headers["x-api-key"] = key
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while True:
        ttl = "1h" if MODE == "cache_1h" or not truthy("FORCE_PROMPT_CACHING_5M") else "5m"
        body = {"model": model, "max_tokens": 32000, "stream": True, "messages": messages,
                "system": [{"type": "text", "text": "SYNTHETIC system", "cache_control": {"type": "ephemeral",
                                                                                          "ttl": ttl}}],
                "tools": [{"name": t, "input_schema": {"type": "object"}} for t in tools]}
        if opts["effort"] and MODE != "no_effort":
            body["output_config"] = {"effort": opts["effort"]}
        attempt = 0
        while True:
            request = urllib.request.Request(base.rstrip("/") + "/v1/messages", data=json.dumps(body).encode(),
                                             headers=headers, method="POST")
            try:
                with opener.open(request, timeout=60) as response:
                    data = response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 529 and attempt < retries:
                    attempt += 1
                    emit({"type": "system", "subtype": "api_retry", "attempt": attempt, "max_retries": retries,
                          "error_status": 529, "error": "overloaded", "session_id": session})
                    time.sleep(0.02)
                    continue
                return finish("error_during_execution", True, f"API Error: {exc.code}", 1)
            except OSError as exc:
                return finish("error_during_execution", True, f"API Error: {exc}", 1)
        message = message_from(parse_sse(data))
        usage = {k: int(message["usage"].get(k) or 0) for k in USAGE_KEYS}
        for k in USAGE_KEYS:
            totals[k] += usage[k]
        cost += price(model, {**usage, "inference_geo": message["usage"].get("inference_geo")})
        turns += 1
        emit({"type": "assistant", "session_id": session, "parent_tool_use_id": None, "message": message})
        texts = [b["text"] for b in message["content"] if b["type"] == "text"]
        final = texts[-1] if texts else final
        if cap is not None and cost >= cap and MODE != "ignore_budget":
            return finish("error_max_budget_usd", True, None, 1, terminal_reason="budget_exhausted")
        calls = [b for b in message["content"] if b["type"] == "tool_use"]
        if message["stop_reason"] != "tool_use" or not calls:
            return finish("success", False, final, 0)
        if turns >= int(opts["max_turns"]):
            return finish("error_max_turns", True, None, 1)
        results = []
        for block in calls:
            output, failed = run_tool(block)
            results.append({"type": "tool_result", "tool_use_id": block["id"], "content": output,
                            **({"is_error": True} if failed else {})})
        emit({"type": "user", "session_id": session, "parent_tool_use_id": None,
              "message": {"role": "user", "content": results}})
        messages += [{"role": "assistant", "content": message["content"]}, {"role": "user", "content": results}]


if __name__ == "__main__":
    sys.exit(main())
