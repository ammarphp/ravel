"""Regression controls for launcher arguments and implicit read access."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p05_refusals import counters, run_tree, spec  # noqa: F401
from test_p05_support import own


@pytest.mark.parametrize('options', [
    {'shell': True}, {'executable': '/bin/sh'}, {'preexec_fn': lambda: None},
    {'pass_fds': (9,)}, {'close_fds': False},
])
def test_SW34_subprocess_options_cannot_replace_or_bypass_sandbox(tmp_path, counters, options):
    from ravel.controller import confine
    run = run_tree(tmp_path)
    with pytest.raises(confine.ConfinementRefused, match='subprocess overrides'):
        confine.popen(spec(run), **options)
    assert counters['started'] == []
    assert list(counters['scratch'].iterdir()) == []


def test_SW34_forged_controller_side_record_does_not_allow_an_authored_command(tmp_path, monkeypatch):
    from ravel.controller import confine
    from ravel.workflow.launch_authorization import _confinement_plan
    run = run_tree(tmp_path)
    own(monkeypatch, tmp_path / 'store', {run: 'run-broker'})
    forged = {'class': 'controller-side', 'entry_point': 'invented', 'reason': 'caller says trusted'}
    with pytest.raises(confine.ConfinementRefused, match='unregistered'):
        _confinement_plan(run, [sys.executable, '-c', 'pass'], {}, forged, {})


def test_C18_C24_cwd_and_search_path_do_not_add_undeclared_read_roots(tmp_path, counters):
    from ravel.controller import confine
    run = run_tree(tmp_path)
    other = (tmp_path / 'other-workspace').resolve()
    (other / 'bin').mkdir(parents=True)
    (other / 'private.txt').write_text('private')
    helper = other / 'bin' / 'helper'
    helper.write_text('#!/bin/sh\nexit 0\n')
    helper.chmod(0o700)
    capsule = {'PATH': str(helper.parent) + os.pathsep + os.defpath, 'PYTHONPATH': str(other)}
    plan = confine.prepare(spec(run, env=capsule))
    assert not any(other == p or other.is_relative_to(p) for p in plan.reads)
    with pytest.raises(confine.ConfinementRefused, match='working directory'):
        confine.prepare(spec(run, cwd=str(other), env=capsule))
    helper_plan = confine.prepare(spec(run, argv=[str(helper)], env=capsule))
    assert helper in helper_plan.reads
    assert not any(helper.parent == p or helper.parent.is_relative_to(p) for p in helper_plan.reads)
    assert counters['started'] == []


def test_C18_changed_input_between_plan_and_start_refuses_before_process(tmp_path, counters):
    from ravel.controller import confine
    run = run_tree(tmp_path)
    source = run / 'inputs' / 'helper'
    source.write_bytes(b'approved')
    plan = confine.prepare(spec(run, input_digests={str(source): hashlib.sha256(b'approved').hexdigest()}))
    source.write_bytes(b'changed')
    with pytest.raises(confine.ConfinementRefused, match=str(source)):
        confine.start(plan)
    assert counters['started'] == []
    assert list(counters['scratch'].iterdir()) == []


def test_SW37_container_environment_is_scrubbed_for_controller_runs(tmp_path, monkeypatch):
    from ravel.workflow.backends.oci_local import OciLocalBackend
    run = run_tree(tmp_path)
    own(monkeypatch, tmp_path / 'store', {run: 'run-container'})
    plan = {'spec': {'image': {'platform': 'linux/amd64', 'reference': 'registry.invalid/image@sha256:' + 'a' * 64},
                     'resources': {'cpus': 1, 'memory_mib': 512}, 'argv': ['tool'],
                     'env': {'SAFE_VALUE': 'ok', 'GH_TOKEN': 'secret', 'RAVEL_ROOT': '/untrusted', 'ANY_UTC': 'old'}},
            'plan_sha256': 'b' * 64, 'inputs': [], 'readonly_trees': []}
    command = OciLocalBackend().create_arguments(plan, {'tag': 't', 'job_dir': str(run / 'job')})
    assert 'SAFE_VALUE=ok' in command
    assert not any(v.startswith(('GH_TOKEN=', 'RAVEL_ROOT=', 'ANY_UTC=')) for v in command)
