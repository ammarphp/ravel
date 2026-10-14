"""Generated shims forward unchanged gate argv and exit status to a stub CLI."""
import importlib
import json
import os
import subprocess
from pathlib import Path

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
