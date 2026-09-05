"""Intake is portable draft routing, with no fabricated approval or execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from ravel import cli, validate_task_contract
from ravel.validation.validate_task_contract import load_contract
from ravel.workflow import provenance, route_prompt, workflow_state

PROMPT = "Reproduce Figure 3 of ATLAS SUSY-2018-16 for a slepton-bino model."


def test_initiate_creates_valid_draft_without_approval_or_execution(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    def forbid_compute(*args, **kwargs):
        pytest.fail("intake must not launch a subprocess")

    monkeypatch.setattr(cli.subprocess, "call", forbid_compute)
    assert cli.main(["initiate", "--prompt", PROMPT, "--out", "run"]) == 0
    output = tmp_path / "run"
    assert sorted(str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()) == [
        "inputs/task_contract.json", "request.txt", "run_state.json"]
    contract_path = output / "inputs/task_contract.json"
    contract = load_contract(contract_path)
    assert contract == route_prompt.route(PROMPT)
    assert validate_task_contract(contract) == []
    assert contract["approval_required"] is True
    assert contract["compute_plan"] == "scan"
    assert (output / "request.txt").read_text() == PROMPT
    state = json.loads((output / "run_state.json").read_text())
    assert state["routed"] is False and state["current_step"] is None
    assert state["session_id"] == "" and state["ladder_rung"] is None
    assert all(state[key] == [] for key in workflow_state.LIST_KEYS)
    assert provenance.verify_pair(state, "workflow_state.py", [str(contract_path)])[0]
    text = capsys.readouterr().out
    assert "compute_authorized=false" in text
    assert "deterministic" in text and "draft" in text
    assert "CHECK-IN 1" in text and "No compute was launched" in text


def test_prompt_file_preserves_utf8_and_line_endings(tmp_path):
    request = tmp_path / "request.txt"
    content = "  Survey ATLAS searches for Z′ → WW.\r\nKeep the assumptions explicit.\r\n"
    request.write_bytes(content.encode("utf-8"))
    output = tmp_path / "nested" / "run"
    assert cli.main(["initiate", "--prompt-file", str(request), "--out", str(output)]) == 0
    assert (output / "request.txt").read_bytes() == request.read_bytes()
    assert load_contract(output / "inputs/task_contract.json")["prompt"] == content


@pytest.mark.parametrize("kind", ["directory", "empty-directory", "file", "symlink", "dangling-symlink"])
def test_existing_output_is_never_overwritten_or_redirected(tmp_path, kind, capsys):
    output = tmp_path / "prior"
    target = tmp_path / "target"
    if kind in ("directory", "empty-directory"):
        output.mkdir()
        if kind == "directory":
            (output / "evidence.json").write_bytes(b"retained evidence\x00")
    elif kind == "file":
        output.write_bytes(b"retained evidence\x00")
    else:
        if kind == "symlink":
            target.mkdir()
            (target / "evidence.json").write_bytes(b"retained evidence\x00")
        output.symlink_to(target, target_is_directory=True)
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob("*") if p.is_file()}
    assert cli.main(["initiate", "--prompt", PROMPT, "--out", str(output)]) == 2
    after = {str(p.relative_to(tmp_path)): p.read_bytes()
             for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert not (output / "inputs").exists()
    if kind == "dangling-symlink":
        assert output.is_symlink() and not target.exists()
    assert "exists" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("prompt", ["", "  \n\t "])
def test_blank_requests_create_no_output(tmp_path, prompt, capsys):
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt", prompt, "--out", str(output)]) == 2
    assert not output.exists()
    assert "must not be blank" in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, b"\xff", b" \r\n\t"])
def test_unreadable_or_blank_request_file_creates_no_output(tmp_path, content):
    request = tmp_path / "request.txt"
    if content is not None:
        request.write_bytes(content)
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt-file", str(request), "--out", str(output)]) == 2
    assert not output.exists()


@pytest.mark.parametrize("args", [[], ["--prompt", PROMPT], ["--out", "run"],
    ["--prompt", PROMPT, "--prompt-file", "request.txt", "--out", "run"]])
def test_exactly_one_request_and_explicit_output_are_required(args):
    with pytest.raises(SystemExit) as exc:
        cli.main(["initiate", *args])
    assert exc.value.code == 2


@pytest.mark.parametrize("prompt", ["Discover a new particle at 5 sigma.", "Hello there."])
def test_unsupported_or_unmatched_route_creates_no_output(tmp_path, prompt, capsys):
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt", prompt, "--out", str(output)]) == 1
    assert not output.exists()
    assert "unsupported request; compute_authorized=false" in capsys.readouterr().err


def test_validator_rejects_router_regression_before_output_creation(tmp_path, monkeypatch, capsys):
    contract = route_prompt.route(PROMPT)
    contract["approval_required"] = False
    monkeypatch.setattr(route_prompt, "route", lambda prompt: contract)
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt", PROMPT, "--out", str(output)]) == 1
    assert not output.exists()
    assert "approval_required" in capsys.readouterr().err


def test_unresolved_inputs_remain_flagged_in_draft(tmp_path):
    output = tmp_path / "run"
    prompt = "Reproduce the analysis and tell me if my model is excluded."
    assert cli.main(["initiate", "--prompt", prompt, "--out", str(output)]) == 0
    contract = load_contract(output / "inputs/task_contract.json")
    assert "analysis identifier" in " ".join(contract["required_user_inputs"])
    assert contract["stat_mode"] == "TBD-judgment"
    assert contract["targets"]["analysis"] == []
    assert contract["approval_required"] is True


def test_state_write_failure_is_not_reported_as_success(tmp_path, monkeypatch, capsys):
    def denied(*args):
        raise PermissionError("ledger write denied")

    monkeypatch.setattr(workflow_state, "write_state", denied)
    output = tmp_path / "run"
    assert cli.main(["initiate", "--prompt", PROMPT, "--out", str(output)]) == 2
    assert (output / "inputs/task_contract.json").is_file()
    assert (output / "request.txt").is_file()
    assert not (output / "run_state.json").exists()
    captured = capsys.readouterr()
    assert not captured.out
    assert "intake did not complete" in captured.err and "ledger write denied" in captured.err
    assert "compute_authorized=false" in captured.err
    # The failed attempt is evidence too, and cannot be silently reused.
    assert cli.main(["initiate", "--prompt", PROMPT, "--out", str(output)]) == 2


def _run_isolated_intake(package_parent, tmp_path):
    output = tmp_path / "isolated-run"
    code = ("import sys, runpy; sys.path.insert(0, sys.argv[1]); "
            "sys.argv = ['ravel', 'initiate', '--prompt', sys.argv[2], '--out', sys.argv[3]]; "
            "runpy.run_module('ravel', run_name='__main__')")
    result = subprocess.run([sys.executable, "-I", "-S", "-c", code,
                             str(package_parent), PROMPT, str(output)],
                            cwd=tmp_path, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compute_authorized=false" in result.stdout
    assert json.loads((output / "run_state.json").read_text())["compute_launched"] == []


def test_package_entry_point_works_outside_checkout_without_dependencies(tmp_path):
    _run_isolated_intake(REPO / "src", tmp_path)


def test_documented_source_launcher_works_outside_checkout(tmp_path):
    request = tmp_path / "request.txt"
    request.write_text(PROMPT)
    output = tmp_path / "source-run"
    result = subprocess.run([sys.executable, "-I", "-S", str(REPO / "scripts/run.py"),
                             "ravel.__main__", "initiate", "--prompt-file", str(request),
                             "--out", str(output)],
                            cwd=tmp_path, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compute_authorized=false" in result.stdout
    assert load_contract(output / "inputs/task_contract.json")["prompt"] == PROMPT


def test_built_wheel_intake_needs_no_source_checkout_or_dependencies(tmp_path):
    wheel = os.environ.get("RAVEL_TEST_WHEEL")
    if not wheel:
        pytest.skip("release check: set RAVEL_TEST_WHEEL to a freshly built wheel")
    installed = tmp_path / "installed"
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(installed)
    _run_isolated_intake(installed, tmp_path)
    assert not any(p.name == "run_state.json" for p in installed.rglob("*"))
