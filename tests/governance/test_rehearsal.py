"""HP-13 offline rehearsal harness (smoke spec WI-7c, R2-R5, R14) and the mock Messages API it runs against.

No test runs a real host or reaches a network: the "CLI" is tests/governance/mock_claude_cli.py, a SYNTHETIC
stand-in that speaks to tests/governance/mock_messages_api.py on 127.0.0.1, and every credential is a dummy.
The end-to-end rehearsal runs under the Seatbelt profile where sandbox-exec works and unsandboxed elsewhere
(the harness's verdicts are under test here, not the profile). It models the macOS host: the adapter binds that
host's shell, /bin/zsh, and the mock CLI runs every Bash call with it, so a rehearsal whose sessions call Bash
skips where /bin/zsh is absent (the public CI's ubuntu-24.04 image has no zsh).
"""
from __future__ import annotations

import http.client
import itertools
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

import pytest

from governance import isolation, rehearsal
from governance.adapters.claude_cli import ClaudeCliAdapter
from governance.canonical import sha256_file

HERE = Path(__file__).resolve().parent
PYTHON = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
PREFIX = os.path.realpath(sys.base_prefix)
CLIENT = HERE.parents[1] / "benchmarks" / "governance" / "client" / "ravel_task.py"
MODEL, VERSION, CAP = "claude-synthetic-5", "2.1.281", 2.0
TOOLS = ["Bash", "Read", "Write", "Edit"]
PINS = {"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1",
        "CLAUDE_CODE_MAX_RETRIES": "3", "BASH_DEFAULT_TIMEOUT_MS": "120000", "BASH_MAX_TIMEOUT_MS": "300000",
        "ZDOTDIR": "/var/empty", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR": "1", "FORCE_PROMPT_CACHING_5M": "1"}
SANDBOXED = isolation.sandbox_available() and isolation.census_available() and PYTHON.startswith(PREFIX + "/")
BOUND_SHELL = "/bin/zsh"                                        # ClaudeCliAdapter's default, the macOS host's shell
BASH_SESSIONS = {"tool_path", "planted_rc", "settings", "retries"}   # the rehearsal sessions that call the Bash tool
mock_api = rehearsal.load_mock()


def dummy_token() -> str:
    return "sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16)


# ---------------------------------------------------------------- the mock Messages API

def post(port, path, body, headers=None, method="POST"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=json.dumps(body).encode(),
                           headers={"content-type": "application/json", **(headers or {})})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_mock_messages_api_logs_header_names_only():
    token = dummy_token()
    with mock_api.MockMessagesAPI([mock_api.tool("Bash", {"command": "true"}), mock_api.text("done")]) as mock:
        body = {"model": MODEL, "max_tokens": 64, "stream": True, "system": "SYNTHETIC SYSTEM PROMPT",
                "messages": [{"role": "user", "content": "SYNTHETIC USER TEXT"}],
                "tools": [{"name": t, "input_schema": {}} for t in TOOLS], "output_config": {"effort": "high"},
                "metadata": {"user_id": "SYNTHETIC-USER-ID"}}
        status, data = post(mock.port, "/v1/messages?beta=true", body,
                            {"authorization": f"Bearer {token}", "x-api-key": token, "anthropic-beta": "synthetic-1"})
        log = mock.requests()
    assert status == 200
    events = mock_api.parse_sse(data)
    assert [name for name, _ in events][:2] == ["message_start", "content_block_start"]
    assert events[1][1]["content_block"]["name"] == "Bash" and events[-1][0] == "message_stop"
    assert len(log) == 1
    entry = log[0]
    assert entry["path"] == "/v1/messages" and entry["role"] == "main" and entry["position"] == 0
    assert {"authorization", "x-api-key", "anthropic-beta"} <= set(entry["header_names"])
    assert entry["tools"] == sorted(TOOLS) and entry["output_config"] == {"effort": "high"}
    assert entry["model"] == MODEL and entry["messages"] == 1 and "system" in entry["body_keys"]
    text = json.dumps(log)
    for secret in (token, token[:20], "SYNTHETIC SYSTEM PROMPT", "SYNTHETIC USER TEXT", "SYNTHETIC-USER-ID",
                   "synthetic-1"):
        assert secret not in text


def test_mock_answers_positions_overloads_auxiliary_and_other_paths():
    turns = [mock_api.text("first", overloaded=2, usage={"input_tokens": 7, "output_tokens": 3, "speed": "x"}),
             mock_api.text("second")]
    with mock_api.MockMessagesAPI(turns) as mock:
        main = {"model": MODEL, "max_tokens": 8, "tools": [{"name": "Bash"}],
                "messages": [{"role": "user", "content": "x"}]}
        statuses = [post(mock.port, "/v1/messages", main)[0] for _ in range(3)]
        _, first = post(mock.port, "/v1/messages", main)
        later = dict(main, messages=main["messages"] + [{"role": "assistant", "content": "a"},
                                                         {"role": "user", "content": "b"}])
        _, second = post(mock.port, "/v1/messages", later)
        _, aux = post(mock.port, "/v1/messages", {"model": "synthetic-small", "max_tokens": 8, "messages": []})
        status_404, _ = post(mock.port, "/api/oauth/profile", {}, method="GET")
        _, count = post(mock.port, "/v1/messages/count_tokens", main)
        log = mock.requests()
    assert statuses == [529, 529, 200]
    assert json.loads(first)["content"][0]["text"] == "first" and json.loads(first)["usage"]["input_tokens"] == 7
    assert json.loads(second)["content"][0]["text"] == "second"
    assert json.loads(aux)["content"][0]["text"] == "SYNTHETIC auxiliary reply"
    assert status_404 == 404 and json.loads(count) == {"input_tokens": 100}
    assert [e["role"] for e in log] == ["main"] * 5 + ["auxiliary", "other", "count_tokens"]
    assert [e.get("answered") for e in log[:5]] == [529, 529, 200, 200, 200]
    assert [e["position"] for e in log[:5]] == [0, 0, 0, 0, 1]


def test_the_streamed_usage_never_double_counts():
    """message_start carries the input and cache counts, message_delta only the final output count."""
    turn = mock_api.text("x", usage={"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_input_tokens": 5})
    with mock_api.MockMessagesAPI([turn]) as mock:
        _, data = post(mock.port, "/v1/messages", {"model": MODEL, "stream": True, "tools": [{"name": "Bash"}],
                                                   "messages": []})
    events = dict(mock_api.parse_sse(data))
    assert events["message_start"]["message"]["usage"]["input_tokens"] == 1_000_000
    assert events["message_delta"]["usage"] == {"output_tokens": 0}


# ---------------------------------------------------------------- verdict helpers (no host)

def test_pricing_differential_rejects_an_unpriced_model():
    pinned = {"input_tokens": 2.0, "output_tokens": 10.0, "cache_creation_input_tokens": 2.5,
              "cache_read_input_tokens": 0.2}
    fallback = {"input_tokens": 5.0, "output_tokens": 25.0, "cache_creation_input_tokens": 6.25,
                "cache_read_input_tokens": 0.5}
    ok, detail = rehearsal.pricing_eligibility({MODEL: pinned, rehearsal.CONTROL_MODEL: fallback}, MODEL)
    assert ok and detail["differs"]
    same, _ = rehearsal.pricing_eligibility({MODEL: fallback, rehearsal.CONTROL_MODEL: dict(fallback)}, MODEL)
    assert same is False                                   # priced at the fallback: the pin does not know it
    partial, detail = rehearsal.pricing_eligibility({MODEL: {"input_tokens": 2.0},
                                                     rehearsal.CONTROL_MODEL: fallback}, MODEL)
    assert partial is False and detail["complete"] is False
    missing, _ = rehearsal.pricing_eligibility({MODEL: {**pinned, "output_tokens": None},
                                                rehearsal.CONTROL_MODEL: fallback}, MODEL)
    assert missing is False
    # H-27: a located catalog entry makes equal rates eligible only when it equals what the pin measurably applies
    located, detail = rehearsal.pricing_eligibility({MODEL: pinned, rehearsal.CONTROL_MODEL: dict(pinned)}, MODEL,
                                                    catalog_rates=dict(pinned))
    assert located is True and detail["differs"] is False and detail["catalog_matches_measured"] is True
    for catalog in ({"input_tokens": 2.0}, {**pinned, "output_tokens": 10.5}, {}):   # partial or different: refused
        refused, detail = rehearsal.pricing_eligibility({MODEL: pinned, rehearsal.CONTROL_MODEL: dict(pinned)}, MODEL,
                                                        catalog_rates=catalog)
        assert refused is False and detail["catalog_matches_measured"] is False


def test_budget_turns_stay_far_below_a_context_window():
    """Each budget turn reports at most BUDGET_TURN_CEILING tokens (no compaction), and crosses the cap on the target
    turn when the rates allow it, later otherwise; without measured rates there is no crossing to check against."""
    usage, cost, crossing = rehearsal.budget_usage(2.0, {"input_tokens": 15.0, "output_tokens": 75.0})
    assert sum(usage.values()) <= rehearsal.BUDGET_TURN_CEILING and crossing == rehearsal.BUDGET_TARGET_TURN
    assert cost * (crossing - 1) < 2.0 <= cost * crossing
    usage, cost, crossing = rehearsal.budget_usage(2.0, {"input_tokens": 1.0, "output_tokens": 5.0})
    assert sum(usage.values()) <= rehearsal.BUDGET_TURN_CEILING + 1 and crossing > rehearsal.BUDGET_TARGET_TURN
    assert crossing + 1 < rehearsal.BUDGET_TURNS and cost * (crossing - 1) < 2.0 <= cost * crossing
    assert rehearsal.budget_usage(2.0, {"input_tokens": 2.0})[1:] == (None, None)
    assert rehearsal.budget_usage(2.0, {"input_tokens": 2.0, "output_tokens": None})[1:] == (None, None)


def test_tool_calls_pair_uses_with_results():
    events = [{"data": {"message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                 "input": {"command": "true"}}]}}},
              {"data": {"message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True,
                                                 "content": [{"type": "text", "text": "boom"}]}]}}},
              {"data": {"message": {"content": [{"type": "tool_use", "id": "t2", "name": "Read", "input": {}}]}}}]
    assert rehearsal.tool_calls({"events": events}) == [
        {"name": "Bash", "input": {"command": "true"}, "text": "boom", "is_error": True},
        {"name": "Read", "input": {}, "text": None, "is_error": None}]


# ---------------------------------------------------------------- the rehearsal against the mock CLI

class MockHost:
    """A SessionHost for the mock CLI: fresh workspace (with the real task client), HOME, config, tmp and an
    outside directory per session; the campaign-shaped adapter; the dummy credential injected by the launcher;
    the Seatbelt profile (mock and task ports only, keychain services removed) where sandbox-exec works."""

    def __init__(self, base: Path, mode: str, token: str):
        self.base, self.token, self.n = base, token, itertools.count()
        pins = base / "pins"
        pins.mkdir()
        self.exe = pins / "claude"
        source = (HERE / "mock_claude_cli.py").read_text()
        body = source.split("\n", 1)[1].replace("__MOCK_VERSION__", VERSION).replace("__MOCK_MODE__", mode)
        self.exe.write_text(f"#!{PYTHON} -I\n" + body)
        self.exe.chmod(0o555)
        self.client = f"#!{PYTHON} -I\n".encode() + CLIENT.read_bytes().split(b"\n", 1)[1]

    def prepare(self, name):
        root = self.base / f"{next(self.n):02d}-{name.replace(':', '-')}"
        root.mkdir()
        ws = root / "ws"
        isolation.materialize({"request.md": b"SYNTHETIC rehearsal request\n", "bin/ravel-task": self.client,
                               "output/": b"", "tmp/": b"", "home/": b""}, ws)
        (root / "state" / "outside").mkdir(parents=True)
        return rehearsal.SessionContext(workspace=ws, home=ws / "home", outside=root / "state" / "outside",
                                        config_dir=root / "state" / "config",
                                        sweep_roots={"workspace": ws, "state": root / "state",
                                                     "streams": root / "streams"})

    def run(self, ctx, *, prompt, model, env, credential_mode, base_url, mock_port, task_endpoint, task_token):
        state = ctx.config_dir.parent
        secret_name = "CLAUDE_CODE_OAUTH_TOKEN" if credential_mode == "oauth" else "ANTHROPIC_API_KEY"

        def launcher(argv, *, env, **kw):   # the recording launcher's injection, with a dummy
            return isolation.launch(argv, env={**env, secret_name: self.token}, **kw)

        adapter = ClaudeCliAdapter(
            self.exe, VERSION, sha256_file(self.exe), model, 100, CAP, "dontAsk", "project,local",
            ["WebSearch", "WebFetch", "Task", "Agent", "NotebookEdit"], ctx.config_dir, tmp_dir=state / "tmp",
            effort="high", env_pins={**PINS, **env}, cert_store="bundled", tools=TOOLS, allowed_tools=TOOLS,
            expected_api_key_source="none" if credential_mode == "oauth" else "ANTHROPIC_API_KEY",
            session_id=str(uuid.uuid4()), subprocess_env_scrub=False, synthetic=True,
            sandbox="seatbelt" if SANDBOXED else "none_test_only", launcher=launcher)
        subject = isolation.subject_env(
            workspace=ctx.workspace, home=ctx.home, path_dirs=["/usr/bin", "/bin", str(ctx.workspace / "bin")],
            extra={"RAVEL_TASK_ENDPOINT": task_endpoint, "RAVEL_TASK_TOKEN": task_token,
                   "ANTHROPIC_BASE_URL": base_url, "NO_PROXY": "127.0.0.1,localhost,::1",
                   "no_proxy": "127.0.0.1,localhost,::1", "HTTPS_PROXY": "http://127.0.0.1:9",
                   "https_proxy": "http://127.0.0.1:9"})
        profile = None
        if SANDBOXED:
            port = int(task_endpoint.rsplit(":", 1)[1].split("/")[0])
            policy = isolation.SandboxPolicy(
                read_roots=[ctx.workspace, PREFIX], read_literals=[self.exe],
                write_roots=[ctx.workspace / "output", ctx.workspace / "tmp", ctx.home, state],
                network="localhost", localhost_ports=[mock_port, port],
                mach_services_removed=["com.apple.SecurityServer", "com.apple.securityd.xpc"])
            profile = isolation.seatbelt_profile(policy)
        result = adapter.run(prompt=prompt, workspace=ctx.workspace, env=subject, profile=profile, timeout_s=120,
                             out_dir=state.parent / "streams")
        return result.as_dict()


def rehearse(tmp_path, mode="clean", **kw):
    if BASH_SESSIONS & set(kw.get("sessions") or BASH_SESSIONS) and not os.access(BOUND_SHELL, os.X_OK):
        pytest.skip(f"the bound shell {BOUND_SHELL} is absent: the rehearsal models the macOS host")
    token = dummy_token()
    host = MockHost(Path(os.path.realpath(tmp_path)), mode, token)
    record = rehearsal.rehearse(host, mock_api, pinned_model=MODEL, effort="high", tools=TOOLS, cap_usd=CAP,
                                max_retries=3, token=token, **kw)
    return record, token


def by_id(record):
    return {c["id"]: c for c in record["checks"]}


def test_a_clean_rehearsal_passes_every_required_check(tmp_path):
    started = time.monotonic()
    record, token = rehearse(tmp_path)
    assert rehearsal.required_failures(record) == [], json.dumps(record["checks"], indent=1)[:4000]
    assert record["ok"] is True and record["pricing_eligible"] is True and record["api_key_source_checked"] is True
    assert record["cli_price_per_mtok"][MODEL] == {"input_tokens": 2.0, "output_tokens": 10.0,
                                                   "cache_creation_input_tokens": 2.5, "cache_read_input_tokens": 0.2}
    assert record["cli_price_per_mtok"][rehearsal.CONTROL_MODEL]["input_tokens"] == 5.0
    assert record["settings"]["background_tasks"]["outcome"] == rehearsal.EFFECTIVE
    assert record["settings"]["bash_timeout_clamp"]["outcome"] == rehearsal.EFFECTIVE
    assert record["settings"]["max_retries"] == {"outcome": rehearsal.EFFECTIVE, "attempts": 4, "overloaded": 4,
                                                 "max_retries": 3}
    checks = by_id(record)
    budget = checks["c.budget_cutoff"]["detail"]   # 96,000 input + 24,000 output tokens at 2 and 10 USD/Mtok
    assert budget["per_turn_usage"] == {"input_tokens": 96_000, "output_tokens": 24_000}
    assert budget["crossing_turn"] == 5 and budget["answered"] == 5
    planted = checks["b.no_credential_name_in_hooks"]["detail"]
    assert planted["home_hooks_fired"] == [] and planted["credential_names"] == []   # ZDOTDIR and GIT_CONFIG_*
    assert checks["b.output_repository_planted"]["ok"] is True
    assert checks["a.no_token_copy_mid_run"]["ok"] is True and checks["a.cache_ttl_not_1h"]["ok"] is True
    assert checks["a.cache_ttl_not_1h"]["detail"]["cache_ttls"] == ["5m"]
    assert record["settings"]["bash_cwd_reset"]["outcome"] == rehearsal.EFFECTIVE
    # E-203: "us" (x1.1 in the 2.1.281 bundle, as in the mock) and "not_available", the value the smoke's usage reported
    assert record["cli_geo_multiplier"] == {"us": 1.1, "not_available": 1.0}
    assert checks["d.geo_multipliers"] == {"id": "d.geo_multipliers", "required": False, "ok": True,
                                           "detail": {"measured": {"us": 1.1, "not_available": 1.0}}}
    assert record["sessions"][f"pricing:{MODEL}:input_tokens:geo_not_available"]["requests"]
    assert token not in json.dumps(record)
    assert record["sessions"]["tool_path"]["init"]["apiKeySource"] == "none"
    assert time.monotonic() - started < 240


@pytest.mark.parametrize("mode, failing", [
    ("leak_child", "a.bash_env_names"), ("no_effort", "a.request_effort"), ("no_snapshot", "a.shell_snapshot"),
    ("flat_prices", "d.pricing_differs_from_unknown"), ("ignore_budget", "c.budget_cutoff"),
    ("leak_file", "sweep.dummy_token_nowhere"),
    ("extra_plugin", "a.init_matches"), ("extra_skill", "a.init_matches"),   # H-26, E-91: what a paid run stops on
])
def test_a_rehearsal_catches_each_broken_expectation(tmp_path, mode, failing):
    only = {"a.bash_env_names": ["tool_path"], "a.request_effort": ["tool_path"], "a.shell_snapshot": ["tool_path"],
            "d.pricing_differs_from_unknown": ["pricing"], "c.budget_cutoff": ["pricing", "budget"],
            "sweep.dummy_token_nowhere": ["tool_path"], "a.init_matches": ["tool_path"]}[failing]
    record, token = rehearse(tmp_path, mode, sessions=only)
    assert failing in rehearsal.required_failures(record) and record["ok"] is False
    assert token not in json.dumps(record)
    if failing == "a.init_matches":
        flags = by_id(record)["a.init_matches"]["detail"]["flags"]
        assert flags == [{"extra_plugin": "plugins_present", "extra_skill": "init_skills_unexpected"}[mode]]


def test_a_snapshot_removed_at_exit_is_seen_during_the_session(tmp_path):
    """2.1.281 unlinks its session shell snapshot when the session ends (seen on the real pin, 2026-09-26): the
    listing taken during session (a) is the evidence, and a CLI that never writes one still fails."""
    record, _ = rehearse(tmp_path, "snapshot_cleanup", sessions=["tool_path"])
    detail = by_id(record)["a.shell_snapshot"]
    assert detail["ok"] is True and rehearsal.required_failures(record) == []
    assert detail["detail"] == {"snapshots": 0, "during_session": ["snapshot-zsh-synthetic.sh"], "listed": True}
    (tmp_path / "missing").mkdir()
    missing, _ = rehearse(tmp_path / "missing", "no_snapshot", sessions=["tool_path"])
    assert by_id(missing)["a.shell_snapshot"]["detail"] == {"snapshots": 0, "during_session": [], "listed": True}


def test_the_api_key_fallback_is_recorded(tmp_path):
    record, _ = rehearse(tmp_path, credential_mode="api_key", sessions=["tool_path"])
    assert record["credential_mode"] == "api_key" and record["api_key_source_checked"] is False
    assert record["sessions"]["tool_path"]["init"]["apiKeySource"] == "ANTHROPIC_API_KEY"
    assert rehearsal.required_failures(record) == []


def test_oauth_refusal_is_recognized():
    refused = {"credential_mode": "oauth", "sessions": {"tool_path": {"flags": ["host_auth_failed"],
                                                                      "requests": [{"role": "other"}]}}}
    assert rehearsal.oauth_refused(refused)
    served = {"credential_mode": "oauth", "sessions": {"tool_path": {"flags": ["host_auth_failed"],
                                                                     "requests": [{"role": "main"}]}}}
    assert not rehearsal.oauth_refused(served)


PINNED_RATES = {"input_tokens": 2.0, "output_tokens": 10.0, "cache_creation_input_tokens": 2.5,
                "cache_read_input_tokens": 0.2}


def test_equal_rates_need_a_catalog_entry_equal_to_the_measured_rates(tmp_path):
    """H-27: like the real 2.1.281 (an unknown id priced at the default model's tier), the "equal_rates" CLI prices the
    control like the pin, so only a located catalog entry equal to the measured rates makes the pin eligible."""
    record, _ = rehearse(tmp_path, "equal_rates", sessions=["pricing"])
    assert "d.pricing_differs_from_unknown" in rehearsal.required_failures(record)
    for name, catalog, eligible in (("located", dict(PINNED_RATES), True),
                                    ("different", {**PINNED_RATES, "output_tokens": 12.0}, False)):
        (tmp_path / name).mkdir()
        checked, _ = rehearse(tmp_path / name, "equal_rates", sessions=["pricing"], catalog_rates=catalog)
        assert checked["pricing_eligible"] is eligible and checked["catalog_rates"] == catalog
        detail = by_id(checked)["d.pricing_differs_from_unknown"]["detail"]
        assert detail["differs"] is False and detail["catalog_matches_measured"] is eligible


@pytest.mark.parametrize("mode, failing", [("cache_1h", "a.cache_ttl_not_1h"),
                                           ("leak_file", "a.no_token_copy_mid_run")])
def test_the_tool_path_catches_a_one_hour_cache_and_a_token_copy_mid_run(tmp_path, mode, failing):
    record, token = rehearse(tmp_path, mode, sessions=["tool_path"])
    assert failing in rehearsal.required_failures(record) and token not in json.dumps(record)
