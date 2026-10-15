"""Generated shims forward unchanged gate argv and exit status to a stub CLI."""
import importlib
import json
import os
import subprocess
from pathlib import Path
import sys

import pytest


@pytest.mark.parametrize('action', ['approve_plan', 'launch', 'checkin2_accept', 'final_task'])
@pytest.mark.parametrize('verdict', ['allow', 'refuse'])
def test_host_shims_equal_hookless_gate(action, verdict, tmp_path):
    assert importlib.util.find_spec('ravel.workflow.role_registry'), 'hook renderer missing'
    rr = importlib.import_module('ravel.workflow.role_registry')
    bin_dir = tmp_path / 'bin'; bin_dir.mkdir()
    cli = bin_dir / 'ravel'
    cli.write_text('#!/bin/sh\n[ "$1" = gate ] || exit 9\nshift\nprintf "%s\\n" "$@"\n'
                   f'echo "{verdict}"\nexit {0 if verdict == "allow" else 1}\n')
    cli.chmod(0o755)
    env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH']}
    args = ['--rundir', str(tmp_path / 'run with spaces'), '--action', action, '--json']
    direct = subprocess.run(['ravel', 'gate', *args], env=env, capture_output=True, text=True)
    for host in ('claude', 'codex', 'gemini'):
        rel, body = rr.gate_shim(host)
        target = tmp_path / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(body)
        shim = subprocess.run(['/bin/sh', str(target), *args], env=env, capture_output=True, text=True)
        assert (shim.returncode, shim.stdout, shim.stderr) == (direct.returncode, direct.stdout, direct.stderr)


def test_wms_guard_refuses_direct_run_and_allows_wms(tmp_path):
    from ravel.workflow import agent_surface as surf
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))
    assert surf.guard_command(tmp_path, 'ravel run --rundir x')
    assert surf.guard_command(tmp_path, 'ravel wms launch --project . --task x') is None
    (tmp_path / 'workflow/policy.json').unlink()
    assert surf.guard_command(tmp_path, 'ravel run --rundir x') is None


def test_consult_snakemake_uses_workflow_manager_card():
    from ravel.workflow import role_registry
    card = role_registry.load('consult-Snakemake')
    assert card['id'] == 'consult-workflow-manager'
    text = ' '.join(card['protocol']).lower()
    for topic in ('dag', 'profile', 'retry', 'dry-run', 'failure'):
        assert topic in text


@pytest.mark.parametrize('command', [
    '/local/bin/ravel run --rundir ANA-0001',
    'env MODE=local ravel run --rundir ANA-0001',
    'exec ravel run --rundir ANA-0001',
    'python3 -B -m ravel.workflow.science run --rundir ANA-0001',
    'python -m ravel run --rundir ANA-0001',
    'ravel site-workflow run-step --workflow workflow --task ANA-0001',
    'python -m ravel.workflow.site_workflow run-step --workflow workflow',
    'true && ravel run --rundir ANA-0001',
    "bash -c 'ravel run --rundir ANA-0001'",
    '# start the stage\nravel run --rundir ANA-0001',
    'echo a#b; ravel run --rundir ANA-0001',
    "# it's approved\nravel run --rundir ANA-0001",
    'nohup ravel run --rundir ANA-0001 &',
    'time ravel run --rundir ANA-0001',
    'if true; then ravel run --rundir ANA-0001; fi',
    'for x in 1; do ravel run --rundir ANA-0001; done',
])
def test_guard_common_direct_launch_spellings(tmp_path, command):
    from ravel.workflow import agent_surface as surf
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))
    assert 'ravel wms launch' in surf.guard_command(tmp_path, command)
    assert surf.guard_command(tmp_path, "echo 'ravel run'") is None


@pytest.mark.parametrize('command', [
    "printf '%s\\n' \"it's ready",
    "cat > notes.txt <<EOF\nthe owner's note\nEOF",
    '# a comment about ANA-0001\nls',
    'ravel status --rundir ANA-0001',
])
def test_guard_allows_unrelated_or_unparseable_commands(tmp_path, command):
    from ravel.workflow import agent_surface as surf
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))
    assert surf.guard_command(tmp_path, command) is None


def test_hook_cli_refuses_malformed_policy(tmp_path):
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text('{"wms_required": "false"}')
    result = subprocess.run([sys.executable, '-m', 'ravel.workflow.agent_surface',
        'wms-guard', '--project', str(tmp_path)],
        input=json.dumps({'tool_input': {'command': 'ravel run --rundir ANA-0001'}}),
        text=True, capture_output=True)
    assert result.returncode == 2
    assert 'policy' in result.stderr


def test_policy_owner_integration(tmp_path):
    from ravel.workflow import agent_surface, wms_policy
    (tmp_path / 'workflow').mkdir()
    (tmp_path / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}))
    assert agent_surface._wms_required(tmp_path) == wms_policy.required(tmp_path)
