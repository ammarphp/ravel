"""Codex CLI adapter (WP08) against SYNTHETIC recorded-format streams and a mock executable.

No test invokes a real ``codex`` binary or any model: the "host" is a generated Python script
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

from governance.adapters import codex_cli
from governance.adapters.base import HostDriftError
from governance.adapters.codex_cli import CodexCliAdapter
from governance.canonical import ContractError, sha256_file

FIXTURES = Path(__file__).parent / "fixtures" / "host_streams"
THREAD = "0199a213-0000-7000-8000-00000000c0de"
CHILD = "0199a213-0000-7000-8000-0000000c41d0"
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
    """Write a SYNTHETIC stand-in executable: prints a fixture stream, records argv/stdin/env."""
    exe = directory / "codex"
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
    exe = mock_host(tmp_path / "bin", "codex-cli 0.155.0-alpha.16.4")

    def make(**overrides):
        args = dict(executable=exe, expected_version="0.155.0-alpha.16.4", expected_sha256=sha256_file(exe),
                    model="synthetic-model", codex_home=tmp_path / "codex-home", synthetic=True,
                    launcher=plain_launch)
        args.update(overrides)
        return CodexCliAdapter(**args)

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


def test_argv_matches_installed_exec_help_and_reads_prompt_from_stdin(host):
    workspace = host.tmp / "subject"
    argv = host().build_argv(workspace)
    assert argv[:3] == [str(host.exe), "exec", "--json"] and argv[-1] == "-"
    configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert configs == ['approval_policy="never"', 'web_search="disabled"', "features.memories=false",
                       "check_for_update_on_startup=false", "analytics.enabled=false"]
    pairs = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i] in ("-C", "-s", "-m", "--color")}
    assert pairs == {"-C": str(workspace), "-s": "danger-full-access", "-m": "synthetic-model", "--color": "never"}
    assert {"--ignore-user-config", "--ignore-rules", "--skip-git-repo-check"} <= set(argv)
    assert "-a" not in argv and "--search" not in argv and "--ephemeral" not in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert PROMPT not in " ".join(argv)
    assert "--ephemeral" in host(ephemeral=True).build_argv(workspace)


@pytest.mark.parametrize("change", [
    {"codex_home": Path.home() / ".codex"},
    {"codex_home": Path.home() / ".codex" / "sub"},
    {"codex_home": Path.home()},
    {"codex_home": "relative/home"},
    {"sandbox_mode": "yolo"},
    {"approval_policy": "untrusted"},
    {"executable": "codex"},
    {"sandbox": "none"},
    {"sandbox": "none_test_only"},  # with the default danger-full-access: never outside the outer profile
    {"synthetic": 1},
])
def test_constructor_refuses_unsafe_configuration(host, change):
    with pytest.raises(ContractError):
        host(**change)


@pytest.mark.parametrize("sandbox_mode", ["danger-full-access", "workspace-write", "read-only"])
def test_outer_profile_is_required_for_every_codex_sandbox_mode(host, sandbox_mode):
    with pytest.raises(ContractError, match="outer sandbox profile"):
        host.run(host(sandbox_mode=sandbox_mode), "synthetic_codex_0.155_success.jsonl", profile=None)
    assert not (host.tmp / "run-record.json").exists()


def test_test_only_unsandboxed_run_is_invalid(host):
    adapter = host(sandbox_mode="workspace-write", sandbox="none_test_only")
    with pytest.raises(ContractError, match="without a profile"):
        host.run(adapter, "synthetic_codex_0.155_success.jsonl", name="both")
    result, _ = host.run(adapter, "synthetic_codex_0.155_success.jsonl", profile=None)
    assert result.status_hint == "exited" and result.details["sandbox"] == "none_test_only"
    assert result.validity == {"ok": False, "invalidating": ["sandbox_none_test_only"]}


def test_success_stream_is_normalized(host):
    result, record = host.run(host(), "synthetic_codex_0.155_success.jsonl")
    assert record["argv"] == host().build_argv(host.tmp / "subject") and record["stdin"] == PROMPT
    assert record["env"]["CODEX_HOME"] == str(host.tmp / "codex-home")
    assert result.adapter == "codex_cli" and result.synthetic is True and result.host_version == "0.155.0-alpha.16.4"
    assert result.validity == VALID and result.details["schema_errors"] == []
    assert (result.status_hint, result.exit_code, result.parse_errors) == ("exited", 0, [])
    assert result.session_ids == [THREAD] and result.final_text.endswith("0.16666666666666666 fb.")
    assert result.cost == {"usd": None, "provenance": "tokens_only", "semantics": "unknown"}
    assert result.usage["total"] == {"input_tokens": 24763, "cached_input_tokens": 24448,
                                     "cache_write_input_tokens": 0, "output_tokens": 122,
                                     "reasoning_output_tokens": 64}
    assert result.details["is_error"] is False and result.details["web_search_items"] == 0
    assert result.details["flags"] == [] and result.subagents == [] and result.permission_denials == []
    assert [e["kind"] for e in result.events] == ["synthetic_marker", "init", "turn", "tool_call", "tool_call",
                                                  "reasoning", "message", "usage"]
    json.dumps(result.as_dict())


def test_children_web_search_and_declined_commands_are_flagged(host):
    result, _ = host.run(host(), "synthetic_codex_collab_web.jsonl")
    assert result.session_ids == [THREAD, CHILD]
    assert result.subagents == [{"id": CHILD, "spawned_by_item": "item_0", "tools": ["spawn_agent"],
                                 "status": "completed", "usage": None, "usage_verified": False}]
    assert result.permission_denials == [{"tool_name": "command_execution", "item_id": "item_2",
                                          "command": "cat /outside", "source": "item"}]
    assert {"web_search_item_present", "subagent_usage_unverified", "permission_denied"} <= set(result.details["flags"])
    assert result.validity == {"ok": False, "invalidating": ["web_search_item_present"]}
    total = result.usage["total"]
    assert total["input_tokens"] == 25763 and total["cache_write_input_tokens"] is None  # missing in turn 1 -> null
    assert len(result.usage["turns"]) == 2


def test_failed_turn_and_truncated_stream_after_a_claim_are_retained(host):
    result, _ = host.run(host(), "synthetic_codex_turn_failed.jsonl", exit_code=1)
    assert (result.status_hint, result.exit_code) == ("exited", 1)
    assert result.final_text == "Delivered: the observed limit is 0.25 fb."
    assert result.details["is_error"] is True and len(result.details["failures"]) == 2
    assert result.parse_errors[0]["truncated"] is True and result.parse_errors[0]["line"] == 7
    assert result.usage is None and "no_usage" in result.details["flags"]


def test_timeout_keeps_the_stream_prefix(host):
    result, _ = host.run(host(), "synthetic_codex_turn_failed.jsonl", sleep=30, timeout_s=2)
    assert result.status_hint == "timeout" and result.wall_seconds < 20
    assert result.final_text == "Delivered: the observed limit is 0.25 fb."


def test_version_drift_refuses_launch(host):
    exe = mock_host(host.tmp / "bin", "codex-cli 0.156.0")
    with pytest.raises(HostDriftError, match="0.156.0"):
        host.run(host(executable=exe, expected_sha256=sha256_file(exe)), "synthetic_codex_0.155_success.jsonl")
    assert not (host.tmp / "run-record.json").exists()
    with pytest.raises(HostDriftError, match="sha256"):
        host(expected_sha256="f" * 64).preflight()
    failing = mock_host(host.tmp / "bin", "codex-cli 0.155.0-alpha.16.4", version_exit=1)
    with pytest.raises(HostDriftError, match="exit 1"):
        host(executable=failing, expected_sha256=sha256_file(failing)).preflight()


def test_type_drift_never_raises_and_invalidates(host):
    result, _ = host.run(host(), "synthetic_codex_type_drift.jsonl")
    assert [e["line"] for e in result.details["schema_errors"]] == [4, 5, 6]
    assert [e["kind"] for e in result.events] == ["synthetic_marker", "init", "turn", "unnormalized", "unnormalized",
                                                  "unnormalized", "message", "other", "usage"]
    assert result.final_text.endswith("fb.") and result.session_ids == [THREAD]
    assert result.usage["total"]["input_tokens"] is None and result.usage["total"]["output_tokens"] == 122
    assert result.validity == {"ok": False, "invalidating": ["schema_errors"]}
    json.dumps(result.as_dict())


def test_parser_failure_keeps_records_and_invalidates(host, monkeypatch):
    def broken(records, **kwargs):
        raise RuntimeError("SYNTHETIC parser defect")

    monkeypatch.setattr(codex_cli, "parse_stream", broken)
    result, _ = host.run(host(), "synthetic_codex_0.155_success.jsonl")
    assert result.validity == {"ok": False, "invalidating": ["normalization_failed"]}
    assert len(result.events) == 8 and result.cost["usd"] is None


def test_synthetic_stream_in_a_nonsynthetic_run_invalidates(host):
    result, _ = host.run(host(synthetic=False), "synthetic_codex_0.155_success.jsonl")
    assert result.synthetic is False
    assert result.validity == {"ok": False, "invalidating": ["synthetic_marker_in_nonsynthetic_run"]}


def test_codex_home_must_be_fresh_except_for_seeded_auth(host):
    home = host.tmp / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text('{"synthetic": true}')
    result, _ = host.run(host(), "synthetic_codex_0.155_success.jsonl", name="seeded")
    assert result.status_hint == "exited"
    (home / "config.toml").write_text("")
    with pytest.raises(ContractError, match="fresh"):
        host.run(host(), "synthetic_codex_0.155_success.jsonl", name="dirty")


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_seeded_auth_must_not_link_to_user_credentials(host, link):
    real = host.tmp / "user-codex" / "auth.json"  # SYNTHETIC stand-in for ~/.codex/auth.json
    real.parent.mkdir()
    real.write_text('{"synthetic": true}')
    home = host.tmp / "codex-home"
    home.mkdir()
    (home / "auth.json").symlink_to(real) if link == "symlink" else os.link(real, home / "auth.json")
    with pytest.raises(ContractError, match="regular file with one link"):
        host.run(host(), "synthetic_codex_0.155_success.jsonl")
    assert not (host.tmp / "run-record.json").exists()


def test_raw_streams_must_stay_outside_the_workspace(host):
    with pytest.raises(ContractError, match="outside the subject workspace"):
        host().run(prompt=PROMPT, workspace=host.tmp / "subject", env={"PATH": "/usr/bin:/bin"}, profile=PROFILE,
                   timeout_s=30, out_dir=host.tmp / "subject" / "raw")
    assert not (host.tmp / "subject" / "raw").exists()


def test_orchestrator_env_is_refused(host):
    with pytest.raises(ContractError, match="orchestrator"):
        host.run(host(), "synthetic_codex_0.155_success.jsonl", env={"CLAUDE_CODE_MESSAGING_SOCKET": "/synthetic"})
