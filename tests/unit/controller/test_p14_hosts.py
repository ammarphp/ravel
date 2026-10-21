"""P14: unrestricted hosts keep working, their hooks are honest detection and their results are labelled.

Each test is named after its coverage row. Hooks import the installed RAVEL only (SW18), fail
closed and label when the gate cannot run (SW19, SW32), local settings are protected and a
disabled hook table is noticed at the next RAVEL call (SW14), controller processes always run
the tripwire (SW15), releases and guard-less installs are labelled (SW10, SW11), a turn with
no resolvable run is labelled (SW31) and every unrestricted-host delivery carries the label (CT08).
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow import active_run, agent_surface, agent_tripwire, host_governance as hg, host_hooks
from ravel.workflow import stop_dispatch

REPO = Path(__file__).resolve().parents[3]
HOOKS = REPO / ".claude/hooks"


@pytest.fixture(autouse=True)
def _isolated_host(tmp_path, monkeypatch):
    """Per-test host: its own state directory, home and user settings; no inherited session."""
    monkeypatch.setenv("RAVEL_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home/.claude"))
    for name in ("CLAUDE_PROJECT_DIR", "RAVEL_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDECODE",
                 "RAVEL_AGENT_TRIPWIRE"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "home").mkdir()


def _env(project, tmp_path, **values):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), RAVEL_PYTHON=sys.executable,
               RAVEL_STATE_DIR=str(tmp_path / "state"), HOME=str(tmp_path / "home"),
               CLAUDE_CONFIG_DIR=str(tmp_path / "home/.claude"))
    env.update(values)
    return env


def _hook(name, data, project, tmp_path, **env):
    return subprocess.run(["bash", str(HOOKS / name)], input=json.dumps(data), text=True,
                          capture_output=True, env=_env(project, tmp_path, **env), cwd=project)


def _events(tmp_path):
    path = tmp_path / "state" / hg.HOST_LEDGER
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def _plant(root):
    """A package copy whose guards would allow everything."""
    for name in ("host_gate.py", "host_guards.py"):
        target = root / "src/ravel/workflow" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('print("allow")\nraise SystemExit(0)\n')
    for init in (root / "src/ravel/__init__.py", root / "src/ravel/workflow/__init__.py"):
        init.write_text("")


def _broken_python(tmp_path):
    path = tmp_path / "broken-python"
    path.write_text("#!/bin/sh\nexit 1\n")
    path.chmod(0o755)
    return path


def _run(tmp_path, session="S-RUN"):
    rd = tmp_path / "project" / "trial-runs" / "r1"
    rd.mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps({"session_id": session}))
    return rd


# ---------------------------------------------------------------- SW18 code identity

def test_SW18_planted_project_gate_is_never_imported_by_the_bash_hook(tmp_path):
    project = tmp_path / "project"
    _plant(project)
    data = {"tool_name": "Bash", "session_id": "S-1", "cwd": str(project),
            "tool_input": {"command": "mg5_aMC cards.dat"}}
    done = _hook("pretooluse-bash.sh", data, project, tmp_path)
    assert done.returncode == 2 and "BLOCKED" in done.stderr, done.stdout + done.stderr
    assert "unavailable" not in done.stderr  # the real gate ran and refused
    # Positive control: an ordinary command is allowed by the same real gate.
    data["tool_input"]["command"] = "ls -la"
    assert _hook("pretooluse-bash.sh", data, project, tmp_path).returncode == 0


def test_SW18_planted_guards_never_open_the_enforcement_write_guard(tmp_path):
    project = tmp_path / "project"
    _plant(project)
    (project / "logs").mkdir()
    (project / "logs/.route-pending-S-1").touch()
    data = {"tool_name": "Write", "session_id": "S-1", "cwd": str(project),
            "tool_input": {"file_path": str(project / ".claude/settings.local.json")}}
    done = _hook("protect-enforcement.sh", data, project, tmp_path)
    assert done.returncode == 2 and "read-only" in done.stderr, done.stdout + done.stderr


def test_SW18_hooks_never_prefer_a_project_copy_of_the_package():
    for path in sorted(HOOKS.glob("*.sh")):
        text = path.read_text()
        assert '[ -d "$REPO/src/ravel" ] && HOOK_SRC="$REPO/src"' not in text, path
        assert "PYTHONSAFEPATH=1" in text, path
    for host in ("codex", "gemini"):
        for phase in ("pre", "post", "prompt"):
            command = host_hooks.command(host, phase)
            assert "unset RAVEL_PYTHON PYTHONPATH PYTHONHOME PYTHONSTARTUP" in command
            assert "PYTHONSAFEPATH=1" in command
    plugin = next(iter(host_hooks.render("opencode").values()))
    assert "delete env[name]" in plugin and "PYTHONSAFEPATH" in plugin
    assert "process.env.RAVEL_PYTHON || runtime.python" not in plugin


def test_SW18_generated_hook_ignores_a_nested_planted_project(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    agent_surface.install(outer, skills_from=REPO, include_software=False)
    nested = outer / "nested"
    _plant(nested)
    (nested / ".claude").mkdir()
    (nested / ".claude/settings.json").write_text("{}")
    (nested / ".claude/hooks").mkdir()
    (nested / ".claude/hooks/pretooluse-bash.sh").write_text("")
    for name in ("host_guards.py", "host_gate.py"):  # a copy in the working directory itself
        (nested / "ravel/workflow").mkdir(parents=True, exist_ok=True)
        (nested / "ravel/workflow" / name).write_text('print("allow")\nraise SystemExit(0)\n')
    (nested / "ravel/__init__.py").write_text("")
    (nested / "ravel/workflow/__init__.py").write_text("")
    data = {"tool_name": "Bash", "tool_input": {"command": "mg5_aMC cards.dat"}}
    done = subprocess.run(["/bin/sh", "-c", host_hooks.command("codex", "pre")], input=json.dumps(data),
                          cwd=nested, text=True, capture_output=True,
                          env=_env(nested, tmp_path, RAVEL_PYTHON=sys.executable))
    # The nested copy is not a repository top level and the working directory is never searched,
    # so neither copy loads: the installed guard refuses, or cannot run and blocks; never allows.
    assert done.returncode == 2 and "BLOCKED" in done.stderr, done.stdout + done.stderr
    assert "allow" not in done.stdout


def test_SW18_changed_hook_runtime_is_detected(tmp_path):
    project = tmp_path / "installed"
    project.mkdir()
    agent_surface.install(project, skills_from=REPO, include_software=False)
    assert hg.runtime_findings(project) == []  # positive control: the installer's own runtime
    runtime = project / hg.HOOK_RUNTIME
    original = runtime.read_text()
    runtime.write_text(original + "exit 0\n")
    assert [f["code"] for f in hg.runtime_findings(project)] == ["hook_runtime_modified"]
    copy = tmp_path / "copy/src"
    copy.mkdir(parents=True)
    lines = original.splitlines()
    runtime.write_text("\n".join(lines[:3] + [f"export PYTHONPATH={copy}" + "${PYTHONPATH:+:$PYTHONPATH}"]) + "\n")
    assert [f["code"] for f in hg.runtime_findings(project)] == ["hook_runtime_package"]


# ---------------------------------------------------------------- SW19 / SW32 fail closed

def test_SW19_broken_gate_blocks_every_command_and_labels_the_session(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    data = {"tool_name": "Bash", "session_id": "S-BROKEN", "cwd": str(project),
            "tool_input": {"command": "ls -la"}}
    done = _hook("pretooluse-bash.sh", data, project, tmp_path, RAVEL_PYTHON=str(_broken_python(tmp_path)))
    assert done.returncode == 2 and "NOT GOVERNED" in done.stderr, done.stdout + done.stderr
    (event,) = _events(tmp_path)
    assert event["kind"] == "hook_failure" and event["hook"] == "pretooluse-bash"
    assert event["session"] == "S-BROKEN"
    rd = _run(tmp_path, session="S-BROKEN")
    label = hg.governance_label(rd, project)
    assert label["label"] == "NOT GOVERNED" and "hook_failure" in label["reasons"]


@pytest.mark.parametrize("name", ["pretooluse-mcp.sh", "pretooluse-skill.sh", "pre-generate-guard.sh"])
def test_SW19_other_pre_hooks_fail_closed_and_label(tmp_path, name):
    project = tmp_path / "project"
    project.mkdir()
    tool = {"pretooluse-mcp.sh": "mcp__x__y", "pretooluse-skill.sh": "Skill", "pre-generate-guard.sh": "Bash"}[name]
    data = {"tool_name": tool, "session_id": "S-PRE", "cwd": str(project),
            "tool_input": {"command": "mg5_aMC cards.dat", "file_path": str(project / "x.txt"), "skill": "x"}}
    broken = _broken_python(tmp_path)
    if name == "pre-generate-guard.sh":
        # Its command extraction uses the interpreter too; break only the guard module run.
        broken.write_text('#!/bin/sh\ncase "$*" in *resource_census*) exit 1 ;; esac\nexec '
                          + sys.executable + ' "$@"\n')
    done = _hook(name, data, project, tmp_path, RAVEL_PYTHON=str(broken))
    assert done.returncode == 2, done.stdout + done.stderr
    assert any(e["kind"] == "hook_failure" for e in _events(tmp_path))


def test_SW32_prompt_routing_failure_blocks_and_labels(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    data = {"session_id": "S-PROMPT", "prompt": "compute the limit for this model"}
    done = _hook("userpromptsubmit-router.sh", data, project, tmp_path,
                 RAVEL_PYTHON=str(_broken_python(tmp_path)))
    assert done.returncode == 2 and "NOT GOVERNED" in done.stderr
    assert [e["hook"] for e in _events(tmp_path)] == ["userpromptsubmit-router"]
    # Positive control: with a working interpreter the router never blocks the prompt.
    assert _hook("userpromptsubmit-router.sh", data, project, tmp_path).returncode == 0


@pytest.mark.parametrize("host", ("codex", "gemini"))
def test_SW32_generated_prompt_hook_blocks_and_labels(host, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    agent_surface.install(project, skills_from=REPO, include_software=False)
    runtime = project / hg.HOOK_RUNTIME
    lines = runtime.read_text().splitlines()
    broken = _broken_python(tmp_path)
    runtime.write_text("\n".join([lines[0], f'if [ -z "${{RAVEL_PYTHON:-}}" ]; then RAVEL_PYTHON={broken}; fi',
                                  *lines[2:]]) + "\n")
    done = subprocess.run(["/bin/sh", "-c", host_hooks.command(host, "prompt")], cwd=project,
                          input='{"prompt": "x"}', text=True, capture_output=True, env=_env(project, tmp_path))
    assert done.returncode == 2 and "NOT GOVERNED" in done.stderr
    assert [e["hook"] for e in _events(tmp_path)] == [f"{host}-prompt"]


@pytest.mark.parametrize("host", ("codex", "gemini"))
def test_SW19_generated_hook_failure_labels_the_sessions_run(host, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    agent_surface.install(project, skills_from=REPO, include_software=False)
    runtime = project / hg.HOOK_RUNTIME
    lines = runtime.read_text().splitlines()
    runtime.write_text("\n".join([lines[0], f'if [ -z "${{RAVEL_PYTHON:-}}" ]; then RAVEL_PYTHON={_broken_python(tmp_path)}; fi',
                                  *lines[2:]]) + "\n")
    data = {"session_id": "S-GEN", "tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    done = subprocess.run(["/bin/sh", "-c", host_hooks.command(host, "pre")], cwd=project,
                          input=json.dumps(data), text=True, capture_output=True, env=_env(project, tmp_path))
    assert done.returncode == 2 and "NOT GOVERNED" in done.stderr, done.stdout + done.stderr
    (event,) = _events(tmp_path)
    assert event["hook"] == f"{host}-pre" and event["session"] == "S-GEN"
    # The failure reaches the delivery label of the session's run, not of another session's run.
    assert "hook_failure" in hg.governance_label(_run(tmp_path, session="S-GEN"), project)["reasons"]
    other = tmp_path / "project/trial-runs/r2"
    other.mkdir()
    (other / "run_state.json").write_text(json.dumps({"session_id": "S-OTHER"}))
    assert "hook_failure" not in hg.governance_label(other, project)["reasons"]


def test_SW32_guard_exceptions_are_distinct_from_refusals(tmp_path):
    done = subprocess.run([sys.executable, "-m", "ravel.workflow.host_guards", "--host", "codex",
                           "--phase", "pre", "--project", str(tmp_path)], input="[]", text=True,
                          capture_output=True)
    assert done.returncode == 3 and "unavailable" in done.stderr
    refused = subprocess.run([sys.executable, "-m", "ravel.workflow.host_guards", "--host", "codex",
                              "--phase", "pre", "--project", str(tmp_path)],
                             input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "mg5_aMC c"}}),
                             text=True, capture_output=True)
    assert refused.returncode == 2


# ---------------------------------------------------------------- SW14 settings

def test_SW14_local_settings_write_is_blocked_in_a_physics_session(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    (project / "logs/.route-pending-S-1").touch()
    for rel in (".claude/settings.local.json", ".ravel/agent-surface.local.json", ".codex/config.toml"):
        data = {"tool_name": "Edit", "session_id": "S-1", "cwd": "", "tool_input": {"file_path": str(project / rel)}}
        assert _hook("protect-enforcement.sh", data, project, tmp_path).returncode == 2, rel
    # Positive control: an ordinary file is writable, and a development session may edit settings.
    data = {"tool_name": "Edit", "session_id": "S-1", "cwd": "", "tool_input": {"file_path": str(project / "notes.md")}}
    assert _hook("protect-enforcement.sh", data, project, tmp_path).returncode == 0
    data = {"tool_name": "Edit", "session_id": "S-DEV", "cwd": "",
            "tool_input": {"file_path": str(project / ".claude/settings.local.json")}}
    assert _hook("protect-enforcement.sh", data, project, tmp_path).returncode == 0


def test_SW14_registry_ledger_and_user_settings_are_protected_in_a_physics_session(tmp_path):
    project = tmp_path / "project"
    (project / "logs").mkdir(parents=True)
    (project / "logs/.route-pending-S-1").touch()
    for path in (tmp_path / "state/active-runs/x.json", tmp_path / "state/host-integrity/events.jsonl",
                 tmp_path / "config/settings.json"):
        data = {"tool_name": "Write", "session_id": "S-1", "cwd": "", "tool_input": {"file_path": str(path)}}
        done = _hook("protect-enforcement.sh", data, project, tmp_path, CLAUDE_CONFIG_DIR=str(tmp_path / "config"))
        assert done.returncode == 2, path


def test_SW14_disabled_hooks_are_detected_at_the_next_ravel_call_and_label_the_run(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude/settings.json").write_text(json.dumps({"hooks": {}}))
    rd = _run(tmp_path)
    assert hg.host_findings(project) == []  # positive control
    local = project / ".claude/settings.local.json"
    local.write_text(json.dumps({"disableAllHooks": True}))
    monkeypatch.setenv("RAVEL_SESSION_ID", "S-RUN")
    found = hg.observe_host(project, source="cli")
    assert [f["code"] for f in found] == ["hooks_disabled"]
    # Reverting the switch after the fact does not erase what was observed for this session.
    local.unlink()
    label = hg.governance_label(rd, project)
    assert label["label"] == "NOT GOVERNED" and "hooks_disabled" in label["reasons"]
    assert label["host_findings"] == []


def test_SW14_user_settings_and_injected_variables_are_detected(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    user = tmp_path / "home/.claude"
    user.mkdir(parents=True)
    (user / "settings.json").write_text(json.dumps({"disableAllHooks": True}))
    (project / ".claude").mkdir()
    (project / ".claude/settings.local.json").write_text(json.dumps({"env": {"RAVEL_PYTHON": "/elsewhere"}}))
    codes = sorted(f["code"] for f in hg.host_findings(project))
    assert codes == ["hooks_disabled", "settings_environment"]
    (project / ".claude/settings.local.json").write_text("{not json")
    assert "settings_unreadable" in {f["code"] for f in hg.host_findings(project)}


def test_SW14_pre_execution_guards_are_not_credited_with_hooks_disabled(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude/settings.json").write_text(json.dumps({"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash x/pretooluse-bash.sh"}]}]}}))
    env = {"CLAUDECODE": "1"}
    assert hg.pre_execution_guards(project, env) == "host-hooks"
    (project / ".claude/settings.local.json").write_text(json.dumps({"disableAllHooks": True}))
    assert hg.pre_execution_guards(project, env) == "none"


# ---------------------------------------------------------------- SW15 tripwire

def _layer():
    return next(iter(agent_tripwire._layers()))


@pytest.mark.parametrize("requested", ["", "0", "report"])
def test_SW15_controller_process_tripwire_blocks_whatever_the_environment(requested, monkeypatch):
    monkeypatch.setenv("RAVEL_AGENT_TRIPWIRE", requested)
    if requested in ("", "0"):
        assert agent_tripwire.check(_layer()) is None  # positive control: off outside the controller
    with agent_tripwire.controller_scope("run-1"):
        with pytest.raises(agent_tripwire.TripwireViolation):
            agent_tripwire.check(_layer())
    assert agent_tripwire.OBSERVED[-1]["requested_mode"] == requested
    assert agent_tripwire.controller_process() is False


def test_SW15_declared_controller_process_cannot_lower_the_tripwire():
    code = ("import os; os.environ['RAVEL_AGENT_TRIPWIRE'] = '0'\n"
            "from ravel.workflow import agent_tripwire as t\n"
            "t.declare_controller_process('run-1')\n"
            "os.environ['RAVEL_AGENT_TRIPWIRE'] = ''\n"
            "layer = next(iter(t._layers()))\n"
            "try:\n    t.check(layer)\nexcept t.TripwireViolation:\n    raise SystemExit(7)\n")
    done = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True,
                          env=dict(os.environ, RAVEL_AGENT_TRIPWIRE="0"))
    assert done.returncode == 7, done.stdout + done.stderr


@pytest.mark.parametrize('layer', ['provider_transport.request', 'cli_agent_host.launch', 'effect_ledger.call'])
@pytest.mark.parametrize('requested', ['', '0', 'report'])
def test_SW15_real_boundaries_refuse_a_declared_controller_with_hooks_off(tmp_path, layer, requested):
    code = '''
import os, sys
from ravel.workflow import agent_tripwire, cli_agent_host, effect_ledger, provider_transport
agent_tripwire.declare_controller_process('fixture-run')
os.environ['RAVEL_AGENT_TRIPWIRE'] = sys.argv[2]
try:
    if sys.argv[1] == 'provider_transport.request':
        provider_transport.request(None, None, None, None, None, None, None, None)
    elif sys.argv[1] == 'cli_agent_host.launch':
        cli_agent_host._run([], '', cwd='.', env={}, timeout=1)
    else:
        effect_ledger.call(None, graph=None, path=None, kind=None, identity=None,
                           provisioning=None, function=lambda: None)
except agent_tripwire.TripwireViolation:
    assert agent_tripwire.OBSERVED[-1]['mode'] == 'block'
    raise SystemExit(7)
raise SystemExit('unauthorized boundary returned')
'''
    env = dict(os.environ, RAVEL_AGENT_TRIPWIRE='0', CLAUDE_CODE_DISABLE_ALL_HOOKS='1')
    done = subprocess.run([sys.executable, '-B', '-c', code, layer, requested], cwd=tmp_path,
                          text=True, capture_output=True, env=env)
    assert done.returncode == 7, done.stdout + done.stderr


# ---------------------------------------------------------------- SW10 / SW11 labels

def test_SW10_install_without_the_guard_is_detected_and_labelled(tmp_path):
    project = tmp_path / "project"
    (project / "workflow").mkdir(parents=True)
    (project / "workflow/policy.json").write_text(json.dumps(
        {"schema_version": 1, "wms_required": True, "engine": "snakemake"}))
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"schema_version": 1, "action": "wms-guard-opt-out", "approved": True,
                                    "approved_by": "operator", "reason": "fixture",
                                    "project": str(project)}))
    report = agent_surface.install(project, skills_from=REPO, include_software=False, wms_guard=False,
                                   guard_approval=approval)
    assert report["notices"] and report["notices"][0].startswith("NOT GOVERNED")
    assert [f["code"] for f in hg.wms_guard_findings(project)] == ["wms_guard_absent"]
    rd = project / "trial-runs/r1"
    rd.mkdir(parents=True)
    label = hg.governance_label(rd, project)
    assert "wms_guard_absent" in label["reasons"]
    # Positive control: the default install keeps the guard and reports nothing.
    report = agent_surface.install(project, skills_from=REPO, include_software=False)
    assert report["notices"] == [] and hg.wms_guard_findings(project) == []


def test_SW11_release_is_recorded_and_labels_the_run(tmp_path):
    rd = _run(tmp_path, session="S-REL")
    active_run.register(rd, "S-REL", by="test")
    assert active_run.release("S-REL") is True
    (event,) = _events(tmp_path)
    assert event["kind"] == "registration_released" and event["rundir"] == str(rd.absolute())
    label = hg.governance_label(rd, tmp_path / "project")
    assert "registration_released" in label["reasons"]
    done = subprocess.run([sys.executable, "-m", "ravel.workflow.active_run", "release", "--session", "S-NONE"],
                          text=True, capture_output=True)
    assert done.returncode == 0 and "no registration" in done.stdout


def test_SW11_controller_owned_registration_is_not_released(tmp_path, monkeypatch):
    rd = _run(tmp_path, session="S-CTL")
    active_run.register(rd, "S-CTL", by="test")
    monkeypatch.setattr(hg, "controller_owned", lambda rundir: "run-1")
    with pytest.raises(active_run.ReleaseRefused):
        active_run.release("S-CTL")
    assert active_run.lookup("S-CTL") == rd.absolute()
    assert _events(tmp_path) == []


# ---------------------------------------------------------------- SW31 / CT08 delivery labels

def test_SW31_turn_without_a_resolvable_run_is_labelled_not_blocked(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "project"
    repo.mkdir()
    code = stop_dispatch.main(["--repo", str(repo), "--session", "S-STOP", "--transcript", "",
                               "--last-message", "Here is the results deck."])
    out = capsys.readouterr().out
    assert code == 0 and "NOT GOVERNED" in json.loads(out)["systemMessage"]
    assert [e["kind"] for e in _events(tmp_path)] == ["stop_unresolved"]
    # Positive control: an ordinary development turn stays silent.
    code = stop_dispatch.main(["--repo", str(repo), "--session", "S-STOP", "--transcript", "",
                               "--last-message", "Edited the function."])
    assert code == 0 and capsys.readouterr().out == ""


def test_SW31_routed_physics_session_without_a_run_is_labelled(tmp_path, capsys):
    repo = tmp_path / "project"
    (repo / "logs").mkdir(parents=True)
    (repo / "logs/.route-pending-S-PHYS").touch()
    assert stop_dispatch.main(["--repo", str(repo), "--session", "S-PHYS", "--transcript", "",
                               "--last-message", "Done."]) == 0
    assert "NOT GOVERNED" in capsys.readouterr().out


def test_CT08_every_unrestricted_host_delivery_carries_the_label(tmp_path, monkeypatch):
    rd = _run(tmp_path)
    record = hg.enforcement_record(rd, project=tmp_path / "project")
    assert record["governance"]["label"] == "NOT GOVERNED"
    assert record["governance"]["reasons"][0] == "unrestricted_host"
    (rd / "outputs/claims").mkdir(parents=True)
    (rd / "outputs/claims/c1.json").write_text(json.dumps({"id": "c1"}))
    hg.stamp_claims(rd, record)
    claim = json.loads((rd / "outputs/claims/c1.json").read_text())
    assert claim["enforcement"]["governance"]["label"] == "NOT GOVERNED"
    # Positive control: a run the controller owns takes its label from the controller.
    monkeypatch.setattr(hg, "controller_owned", lambda rundir: "run-1")
    owned = hg.enforcement_record(rd, project=tmp_path / "project")["governance"]
    assert owned["label"] is None and owned["controller_run"] == "run-1"


def test_CT08_malformed_ledger_rows_never_break_the_label(tmp_path):
    rd = _run(tmp_path, session="S-RUN")
    ledger = tmp_path / "state" / hg.HOST_LEDGER
    ledger.parent.mkdir(parents=True)
    rows = [{"kind": "hook_failure", "session": ["S-RUN"]}, {"kind": "hook_failure", "rundir": 5},
            {"kind": "observed", "session": "S-RUN", "codes": 3},
            {"kind": "observed", "session": "S-RUN", "codes": [["x"]]}, ["not", "an", "object"],
            {"kind": "hook_failure", "session": "S-RUN", "hook": "pretooluse-bash"}]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
    label = hg.governance_label(rd, tmp_path / "project")
    assert label["label"] == "NOT GOVERNED" and "hook_failure" in label["reasons"]
    assert [event["hook"] for event in label["host_events"]] == ["pretooluse-bash"]
    assert hg.observe_host(tmp_path / "project", source="cli") == []


# ---------------------------------------------------------------- render keeps project instructions

def test_render_keeps_project_instructions_unless_replacement_is_explicit(tmp_path):
    project = tmp_path / "fork"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Project rules\nKeep these.\n")
    (project / "CLAUDE.md").write_text("Project notes.\n")
    done = subprocess.run([sys.executable, "-m", "ravel", "agent-surface", "render", "--project", str(project)],
                          text=True, capture_output=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (project / "AGENTS.md").read_text() == "# Project rules\nKeep these.\n"
    assert (project / "CLAUDE.md").read_text() == "Project notes.\n"
    assert sorted(json.loads(done.stdout)["preserved"]) == ["AGENTS.md", "CLAUDE.md"]
    assert (project / "GEMINI.md").is_file()  # absent documents are still rendered
    # RAVEL's own generated text is refreshed; an explicit flag replaces a project's own text.
    generated = agent_surface.render_surfaces(project, replace_instructions=True)
    assert "AGENTS.md" in generated["written"] and generated["preserved"] == []
    assert agent_surface._generated_instructions((project / "AGENTS.md").read_bytes())
    (project / "AGENTS.md").write_text((project / "AGENTS.md").read_text() + "stale\n")
    assert "AGENTS.md" in agent_surface.render_surfaces(project)["written"]
