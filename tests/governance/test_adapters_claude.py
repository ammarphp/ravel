"""Claude Code CLI adapter (WP09) against SYNTHETIC recorded-format streams and a mock executable.

No test invokes a real ``claude`` binary or any model: the "host" is a generated Python script
that answers ``--version`` and otherwise prints a synthetic fixture stream from
``tests/governance/fixtures/host_streams/``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from governance.adapters import claude_cli
from governance.adapters.base import HostDriftError, assert_prompt_not_in_argv
from governance.adapters.claude_cli import ClaudeCliAdapter, claude_cost, cost_semantics, parse_stream
from governance.canonical import ContractError, sha256_bytes, sha256_file

FIXTURES = Path(__file__).parent / "fixtures" / "host_streams"
SESSION = "00000000-0000-4000-8000-00000000aaaa"
RESUMED = "00000000-0000-4000-8000-00000000bbbb"
PROMPT = "SYNTHETIC prompt: produce the current visible-cross-section limit report for SR-A."
PROFILE = "(version 1) ; SYNTHETIC placeholder profile string; the test launcher ignores it"
VALID = {"ok": True, "invalidating": []}


@dataclass
class PlainLaunchResult:
    """SYNTHETIC stand-in for isolation.LaunchResult. It reports an empty System V IPC residue (none left),
    which a sandboxed launch needs to stay valid (adapters.base: anything else is flagged ipc_residue)."""
    exit_code: int | None
    timed_out: bool
    wall_seconds: float
    killed: bool
    survivors: list
    census_complete: bool = True
    ipc_residue: list | None = field(default_factory=list)


def plain_launch(argv, *, cwd, env, profile, timeout_s, stdout_path, stderr_path, stdin_path=None):
    """Unsandboxed test launcher with the isolation.launch signature (profile ignored)."""
    start = time.monotonic()
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err, open(stdin_path or os.devnull, "rb") as inp:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=inp, stdout=out, stderr=err, close_fds=True,
                                start_new_session=True)
        try:
            return PlainLaunchResult(proc.wait(timeout=timeout_s), False, time.monotonic() - start, False, [])
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
            return PlainLaunchResult(proc.returncode, True, time.monotonic() - start, True, [])


def mock_host(directory, version_text, version_exit=0):
    """Write a SYNTHETIC stand-in executable: prints a fixture stream, records argv/stdin/env names."""
    exe = directory / "claude-2.1.x"
    exe.write_text(f"""#!{sys.executable}
# SYNTHETIC mock host CLI for tests: never contacts a model.
import json, os, sys, time
if sys.argv[1:] == ["--version"]:
    print({version_text!r})
    sys.exit({version_exit!r})
prompt = sys.stdin.buffer.read().decode()
record = os.environ.get("FAKE_HOST_RECORD")
if record:
    with open(record, "w") as handle:
        json.dump({{"argv": sys.argv, "stdin": prompt, "cwd": os.getcwd(), "env": dict(os.environ)}}, handle)
fixture = os.environ.get("FAKE_HOST_FIXTURE")
if fixture:
    sys.stdout.buffer.write(open(fixture, "rb").read())
    sys.stdout.flush()
time.sleep(float(os.environ.get("FAKE_HOST_SLEEP", "0")))
sys.exit(int(os.environ.get("FAKE_HOST_EXIT", "0")))
""")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def host(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "subject").mkdir()
    exe = mock_host(tmp_path / "bin", "2.1.233 (Claude Code)")

    def make(cls=ClaudeCliAdapter, **overrides):
        args = dict(executable=exe, expected_version="2.1.233", expected_sha256=sha256_file(exe),
                    model="synthetic-model", max_turns=30, max_budget_usd=5.0, permission_mode="acceptEdits",
                    setting_sources="project", disallowed_tools=("WebSearch", "WebFetch"),
                    config_dir=tmp_path / "claude-config", session_id=SESSION, synthetic=True, launcher=plain_launch)
        args.update(overrides)
        return cls(**args)

    def run(adapter, fixture, *, exit_code=0, sleep=0, timeout_s=30, env=None, profile=PROFILE, name="run"):
        record = tmp_path / f"{name}-record.json"
        run_env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "FAKE_HOST_RECORD": str(record),
                   "FAKE_HOST_FIXTURE": str(FIXTURES / fixture), "FAKE_HOST_EXIT": str(exit_code),
                   "FAKE_HOST_SLEEP": str(sleep), **(env or {})}
        result = adapter.run(prompt=PROMPT, workspace=tmp_path / "subject", env=run_env, profile=profile,
                             timeout_s=timeout_s, out_dir=tmp_path / name)
        return result, (json.loads(record.read_text()) if record.exists() else None)

    make.run, make.exe, make.tmp = run, exe, tmp_path
    return make


def test_argv_is_structured_prompt_free_and_pins_isolation_flags(host):
    argv = host().build_argv(session_id=SESSION)
    assert argv[:5] == [str(host.exe), "-p", "--output-format", "stream-json", "--verbose"]
    pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
    assert pairs["--model"] == "synthetic-model" and pairs["--max-turns"] == "30"
    assert pairs["--max-budget-usd"] == "5.0" and pairs["--permission-mode"] == "acceptEdits"
    assert pairs["--setting-sources"] == "project" and pairs["--session-id"] == SESSION
    assert "--strict-mcp-config" in argv and "--resume" not in argv
    i = argv.index("--disallowedTools")
    assert argv[i + 1:i + 3] == ["WebSearch", "WebFetch"]
    assert all(isinstance(a, str) for a in argv) and PROMPT not in " ".join(argv)
    resumed = host(session_id=None, resume_session_id=RESUMED).build_argv()
    assert resumed[-2:] == ["--resume", RESUMED] and "--session-id" not in resumed
    assert host(setting_sources="").build_argv(session_id=SESSION)[argv.index("--setting-sources") + 1] == ""


@pytest.mark.parametrize("change", [
    {"disallowed_tools": ("WebSearch",)},
    {"allowed_tools": ("WebFetch",)},
    {"setting_sources": "user,project"},
    {"permission_mode": "bypassPermissions"},
    {"max_turns": 0},
    {"max_budget_usd": 0},
    {"config_dir": Path.home() / ".claude"},
    {"config_dir": Path.home() / ".claude" / "sub"},
    {"config_dir": Path.home()},
    {"config_dir": "relative/config"},
    {"session_id": "not-a-uuid"},
    {"session_id": SESSION.upper()},
    {"session_id": "{" + SESSION + "}"},
    {"session_id": "urn:uuid:" + SESSION},
    {"session_id": SESSION.replace("-", "")},
    {"session_id": None, "resume_session_id": RESUMED.upper()},
    {"prior_session_total_usd": 0.1},
    {"sandbox": "none"},
    {"sandbox": "none_test_only", "subprocess_env_scrub": 1},
    {"synthetic": "yes"},
])
def test_constructor_refuses_unsafe_configuration(host, change):
    with pytest.raises(ContractError):
        host(**change)


def test_success_stream_is_normalized(host):
    result, record = host.run(host(), "synthetic_claude_2.1.233_success.jsonl")
    assert record["argv"] == host().build_argv(session_id=SESSION) and record["stdin"] == PROMPT
    assert record["env"]["CLAUDE_CONFIG_DIR"] == str(host.tmp / "claude-config")
    assert record["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1" and record["env"]["DISABLE_AUTOUPDATER"] == "1"
    assert record["env"]["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "1" and result.details["subprocess_env_scrub"] is True
    assert record["cwd"] == str(host.tmp / "subject")
    assert result.adapter == "claude_cli" and result.synthetic is True and result.validity == VALID
    assert result.details["sandbox"] == "seatbelt"
    assert result.details["profile_sha256"] == sha256_bytes(PROFILE.encode())
    assert (result.status_hint, result.exit_code, result.parse_errors) == ("exited", 0, [])
    assert result.session_ids == [SESSION] and result.host_version == "2.1.233"
    assert result.final_text.endswith("0.16666666666666666 fb.")
    assert result.details["final_text_source"] == "result"
    assert result.details["is_error"] is False and result.details["num_turns"] == 3
    assert result.details["init"]["tools"] == ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
    assert result.details["init"]["web_tools_present"] is False
    assert result.cost == {"usd": 0.0123, "provenance": "host_reported", "semantics": "per_call"}
    assert result.details["cost_accounting"]["host_semantics"] == "per_call"
    assert result.usage["main_loop"]["input_tokens"] == 2700 and result.usage["by_model"]["synthetic-model"]
    assert [m["message_id"] for m in result.usage["per_message"]] == ["msg_synthetic_01", "msg_synthetic_02"]
    assert result.subagents == [] and result.permission_denials == []
    assert result.details["flags"] == [] and result.details["schema_errors"] == []
    assert result.events[0]["kind"] == "synthetic_marker" and result.events[0]["data"]["synthetic"] is True
    assert result.details["synthetic_marker"] is True
    assert [e["kind"] for e in result.events[1:]] == ["init", "tool_call", "tool_call", "tool_result", "message",
                                                      "result"]
    assert result.details["identity"]["sha256"] == sha256_file(host.exe)
    json.dumps(result.as_dict())


def test_is_error_is_authoritative_over_success_subtype(host):
    result, _ = host.run(host(), "synthetic_claude_2.1.233_is_error_success.jsonl", exit_code=1)
    assert result.details["result_subtype"] == "success" and result.details["is_error"] is True
    assert "is_error_overrides_success_subtype" in result.details["flags"]
    assert result.exit_code == 1 and result.final_text.startswith("Not logged in")


@pytest.mark.parametrize("version_text, expected_sha, version_exit", [
    ("2.1.281 (Claude Code)", None, 0), ("2.1.233 (Claude Code)", "0" * 64, 0),
    ("2.1.233 (Claude Code)", None, 1),  # the right version text but a failing probe
])
def test_host_drift_refuses_launch(host, version_text, expected_sha, version_exit):
    exe = mock_host(host.tmp / "bin", version_text, version_exit)
    adapter = host(executable=exe, expected_sha256=expected_sha or sha256_file(exe))
    with pytest.raises(HostDriftError):
        host.run(adapter, "synthetic_claude_2.1.233_success.jsonl")
    assert not (host.tmp / "run-record.json").exists() and not (host.tmp / "run").exists()


def test_symlinked_executable_is_refused(host):
    link = host.tmp / "bin" / "claude"
    link.symlink_to(host.exe)
    with pytest.raises(HostDriftError, match="symlink"):
        host(executable=link).preflight()


def test_timeout_keeps_the_stream_prefix(host):
    result, _ = host.run(host(), "synthetic_claude_crash_after_claim.jsonl", sleep=30, timeout_s=2)
    assert result.status_hint == "timeout" and result.details["launch"]["timed_out"] is True
    assert result.wall_seconds < 20
    assert [e["kind"] for e in result.events][1:] == ["init", "tool_call", "tool_result", "message"]
    assert result.parse_errors[0]["truncated"] is True


def test_nonzero_exit_after_claim_retains_trajectory(host):
    result, _ = host.run(host(), "synthetic_claude_crash_after_claim.jsonl", exit_code=1)
    assert (result.status_hint, result.exit_code) == ("exited", 1)
    assert result.final_text == "Submitted. The observed limit is 0.25 fb."
    assert result.details["final_text_source"] == "last_assistant_message"
    assert len(result.parse_errors) == 1
    error = result.parse_errors[0]
    assert error["truncated"] is True and error["line"] == 6 and error["excerpt"].startswith('{"type":"assistant"')
    assert result.details["unterminated_final_line"] is True
    assert {"no_result_event", "cost_unverified", "parse_errors"} <= set(result.details["flags"])
    assert result.cost["usd"] is None and result.details["is_error"] is None
    assert result.details["tool_uses"][0]["name"] == "Bash"


def test_malformed_lines_are_reported_and_later_lines_parsed(host):
    result, _ = host.run(host(), "synthetic_claude_malformed.jsonl")
    assert [e["line"] for e in result.parse_errors] == [3, 5, 6, 7]
    assert result.events[-1]["kind"] == "result" and result.events[-1]["line"] == 9
    assert result.cost["usd"] == 0.004 and result.final_text.endswith("fb.")


def test_subagents_are_recorded_and_their_usage_is_not_treated_as_verified(host):
    result, _ = host.run(host(), "synthetic_claude_subagent.jsonl")
    assert len(result.subagents) == 1
    child = result.subagents[0]
    assert child["id"] == "toolu_agent_01" and child["task_id"] == "task_synthetic_01"
    assert child["task_type"] == "local_agent" and child["spawn_depth"] == 1 and child["status"] == "completed"
    assert child["usage"] == {"total_tokens": 5000, "tool_uses": 2, "duration_ms": 3000}
    assert child["usage_verified"] is False and child["messages"] == 2
    assert "subagent_usage_unverified" in result.details["flags"]
    assert result.cost["usd"] == 0.05 and result.details["subagent_cost_note"]
    assert set(result.usage["by_model"]) == {"synthetic-model", "synthetic-small-model"}


def test_web_tools_are_flagged_and_invalidate(host):
    result, _ = host.run(host(), "synthetic_claude_web_tools.jsonl")
    assert result.details["init"]["web_tools_present"] is True
    assert result.validity == {"ok": False,
                               "invalidating": ["web_requests_reported", "web_tool_used", "web_tools_in_init"]}


def test_contaminated_init_is_flagged_and_invalidates(host):
    result, _ = host.run(host(), "synthetic_claude_contaminated_init.jsonl")
    assert result.validity == {"ok": False, "invalidating": ["init_version_mismatch", "mcp_servers_present",
                                                             "plugins_present", "session_id_mismatch"]}
    assert result.session_ids == ["00000000-0000-4000-8000-00000000dddd"]
    assert result.details["init"]["claude_code_version"] == "2.1.232"


def test_type_drift_never_raises_and_invalidates(host):
    result, _ = host.run(host(), "synthetic_claude_type_drift.jsonl")
    assert result.status_hint == "exited" and result.parse_errors == []
    assert [e["line"] for e in result.details["schema_errors"]] == [7]
    assert "tool_use name" in result.details["schema_errors"][0]["error"]
    assert [e["kind"] for e in result.events] == ["synthetic_marker", "other", "init", "tool_call", "task",
                                                  "permission_denial", "unnormalized", "other", "result"]
    assert result.details["init"]["tools"] == ["Bash", "Read"] and result.details["init"]["web_tools_present"] is False
    assert result.usage["per_message"][0]["message_id"] is None
    assert result.usage["by_model"] == {"synthetic-model": None}
    assert result.details["tool_uses"][0] == {"line": 4, "name": "Bash", "id": None, "parent_id": None}
    assert result.subagents == [] and result.details["duration_ms"] is None
    assert [(d["tool_name"], d["source"]) for d in result.permission_denials] == [("Write", "result"),
                                                                                  ("Write", "stream_event")]
    assert result.cost == {"usd": 0.004, "provenance": "host_reported", "semantics": "per_call"}
    assert result.validity == {"ok": False, "invalidating": ["schema_errors"]}
    json.dumps(result.as_dict())


@pytest.mark.parametrize("init, flag", [
    ({"tools": [1, {"id": "Bash"}]}, "init_tools_unrecognized"),
    ({"tools": "Bash,Read"}, "init_tools_unrecognized"),
    (None, "init_unverified"),
])
def test_unverifiable_init_invalidates(init, flag):
    records = [] if init is None else [(1, {"type": "system", "subtype": "init", "session_id": SESSION,
                                            "claude_code_version": "2.1.233", **init})]
    records.append((2, {"type": "assistant", "session_id": SESSION, "message": {"content": [{"type": "text",
                                                                                          "text": "SYNTHETIC"}]}}))
    parsed = parse_stream(records, version="2.1.233", expected_session_id=SESSION)
    assert flag in parsed["flags"]


def test_parser_failure_keeps_records_and_invalidates(host, monkeypatch):
    def broken(records, **kwargs):
        raise RuntimeError("SYNTHETIC parser defect")

    monkeypatch.setattr(claude_cli, "parse_stream", broken)
    result, _ = host.run(host(), "synthetic_claude_2.1.233_success.jsonl")
    assert result.validity == {"ok": False, "invalidating": ["normalization_failed"]}
    assert len(result.events) == 7 and {e["kind"] for e in result.events} == {"unnormalized"}
    assert result.cost == {"usd": None, "provenance": "host_reported", "semantics": "unknown"}
    assert "SYNTHETIC parser defect" in result.details["normalization_error"]


def test_synthetic_stream_in_a_nonsynthetic_run_invalidates(host):
    result, _ = host.run(host(synthetic=False), "synthetic_claude_2.1.233_success.jsonl")
    assert result.synthetic is False
    assert result.validity == {"ok": False, "invalidating": ["synthetic_marker_in_nonsynthetic_run"]}


def test_outer_sandbox_is_required_unless_test_only(host):
    with pytest.raises(ContractError, match="outer sandbox profile"):
        host.run(host(), "synthetic_claude_2.1.233_success.jsonl", profile=None)
    assert not (host.tmp / "run-record.json").exists()
    with pytest.raises(ContractError, match="without a profile"):
        host.run(host(sandbox="none_test_only"), "synthetic_claude_2.1.233_success.jsonl", name="both")
    result, _ = host.run(host(sandbox="none_test_only"), "synthetic_claude_2.1.233_success.jsonl", profile=None,
                         name="unsandboxed")
    assert result.status_hint == "exited" and result.details["sandbox"] == "none_test_only"
    assert result.details["profile_sha256"] is None
    assert result.validity == {"ok": False, "invalidating": ["sandbox_none_test_only"]}


def test_subprocess_env_scrub_is_a_recorded_choice(host):
    result, record = host.run(host(subprocess_env_scrub=False), "synthetic_claude_2.1.233_success.jsonl")
    assert "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB" not in record["env"]
    assert result.details["subprocess_env_scrub"] is False and result.validity == VALID
    with pytest.raises(ContractError, match="subprocess_env_scrub"):
        host.run(host(subprocess_env_scrub=False), "synthetic_claude_2.1.233_success.jsonl",
                 env={"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"}, name="conflict")
    with pytest.raises(ContractError, match="conflicts"):
        host.run(host(), "synthetic_claude_2.1.233_success.jsonl", env={"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "0"},
                 name="conflict2")


def test_prompt_in_argv_is_refused_before_launch(host):
    class Leaky(ClaudeCliAdapter):
        def build_argv(self, **kwargs):
            return super().build_argv(**kwargs) + ["--append-system-prompt", PROMPT]

    with pytest.raises(ContractError, match="contains the prompt"):
        host.run(host(Leaky), "synthetic_claude_2.1.233_success.jsonl")
    assert not (host.tmp / "run-record.json").exists() and not (host.tmp / "run").exists()
    with pytest.raises(ContractError, match="embeds the prompt"):
        assert_prompt_not_in_argv(["claude", "--append-system-prompt=" + PROMPT], PROMPT)


def test_permission_denials_are_retained(host):
    result, _ = host.run(host(), "synthetic_claude_permission_denied.jsonl")
    assert [(d["tool_name"], d["source"]) for d in result.permission_denials] == [("Write", "result"),
                                                                                  ("Bash", "stream_event")]
    assert "permission_denied" in result.details["flags"]


def test_zeroed_crash_cost_is_unknown_not_free(host):
    result, _ = host.run(host(), "synthetic_claude_error_zeroed.jsonl", exit_code=1)
    assert result.cost["usd"] is None and "cost_zeroed_on_error" in result.details["flags"]
    assert result.details["errors"] == ["synthetic crash"] and result.details["is_error"] is True
    assert result.usage["main_loop"]["input_tokens"] == 0 and result.usage["per_message"][0]["input_tokens"] == 900


@pytest.mark.parametrize("version, resumed, prior, reported, usd, host_semantics", [
    ("2.1.233", False, None, 0.2, 0.2, "per_call"),
    ("2.1.233", True, 0.5, 0.2, 0.2, "per_call"),          # pre-2.1.277: resumed totals restart at zero
    ("2.1.281", False, None, 0.2, 0.2, "cumulative"),      # a fresh session's total is this call's spend
    ("2.1.281", True, 0.25, 0.30, 0.05, "cumulative"),     # increment = cumulative - prior, never the sum
    ("2.1.281", True, None, 0.30, None, "cumulative"),     # no verified prior: increment unknown
    ("2.1.281", True, 0.40, 0.30, None, "cumulative"),     # inconsistent totals: increment unknown
    ("garbage", True, 0.1, 0.30, None, "unknown"),
    ("garbage", False, None, 0.30, 0.30, "unknown"),
    ("2.1.281", False, None, None, None, "cumulative"),    # missing total: null, never zero
])
def test_resume_cost_never_double_counts(version, resumed, prior, reported, usd, host_semantics):
    cost, accounting = claude_cost(reported, version=version, resumed=resumed, prior_session_total_usd=prior)
    assert cost["provenance"] == "host_reported" and accounting["host_semantics"] == host_semantics
    assert cost["usd"] == pytest.approx(usd) if usd is not None else cost["usd"] is None
    # The label describes cost.usd itself: this invocation's spend, or unknown.
    assert cost["semantics"] == ("per_call" if usd is not None else "unknown")
    assert (accounting["unverified_reason"] is None) == (usd is not None)
    assert cost_semantics("2.1.276") == "per_call" and cost_semantics("2.1.277") == "cumulative"


def test_resumed_run_reports_the_increment(host):
    exe = mock_host(host.tmp / "bin", "2.1.281 (Claude Code)")
    config = host.tmp / "claude-config"
    config.mkdir()
    (config / "synthetic-session-state").write_text("SYNTHETIC")
    adapter = host(executable=exe, expected_sha256=sha256_file(exe), expected_version="2.1.281", session_id=None,
                   resume_session_id=RESUMED, prior_session_total_usd=0.25)
    result, record = host.run(adapter, "synthetic_claude_2.1.281_resumed.jsonl")
    assert record["argv"][-2:] == ["--resume", RESUMED]
    assert result.cost["usd"] == pytest.approx(0.05) and result.cost["semantics"] == "per_call"
    assert result.details["cost_accounting"]["session_total_usd"] == 0.30
    assert result.details["cost_accounting"]["host_semantics"] == "cumulative"
    assert result.session_ids == [RESUMED] and "session_id_mismatch" not in result.details["flags"]


@pytest.mark.parametrize("leak", [{"CLAUDECODE": "1"}, {"CLAUDE_CODE_MESSAGING_TOKEN": "synthetic"},
                                  {"CLAUDE_CONFIG_DIR": "/elsewhere"}])
def test_orchestrator_or_conflicting_env_is_refused(host, leak):
    with pytest.raises(ContractError):
        host.run(host(), "synthetic_claude_2.1.233_success.jsonl", env=leak)
    assert not (host.tmp / "run-record.json").exists()


def test_config_dir_must_be_fresh_for_a_new_session(host):
    (host.tmp / "claude-config").mkdir()
    (host.tmp / "claude-config" / "settings.json").write_text("{}")
    with pytest.raises(ContractError, match="fresh"):
        host.run(host(), "synthetic_claude_2.1.233_success.jsonl")


def test_launch_error_is_reported(host):
    def failing(argv, **kwargs):
        raise OSError("synthetic launcher failure")

    result, _ = host.run(host(launcher=failing), "synthetic_claude_2.1.233_success.jsonl")
    assert result.status_hint == "launch_error" and result.events == [] and result.cost["usd"] is None
    assert "no_result_event" in result.details["flags"]
