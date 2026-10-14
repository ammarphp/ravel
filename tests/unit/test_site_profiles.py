"""Scheduler profile rendering and inert HTCondor transport controls."""
from pathlib import Path
import subprocess

import pytest


def test_condor_submit_wraps_jobscript_and_checks_status_with_mock_tools(tmp_path, monkeypatch):
    from ravel.workflow.site_profiles import htcondor as hc, render
    script = tmp_path / 'job script.sh'; script.write_text('#!/bin/sh\n# properties = {"threads": 2}\nexit 0\n')
    calls = []
    def fake(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, '12.0 - 12.0\n' if argv[0] == 'condor_submit' else '4 0\n', '')
    monkeypatch.setattr(hc.subprocess, 'run', fake)
    assert hc.submit(script) == '12.0'
    descriptor = next((tmp_path / '.ravel-condor').glob('*.sub')).read_text()
    assert 'request_cpus = 2' in descriptor and 'executable = /bin/sh' in descriptor
    assert 'job script.sh' in descriptor
    assert hc.status('12.0') == 'success' and len(calls) == 2
    assert 'site_profiles.htcondor submit' in render('htcondor')['config']['cluster-generic-submit-cmd']
    with pytest.raises(ValueError): hc.status('12.0; unsafe')


def test_condor_unknown_or_nonzero_exit_is_never_success(monkeypatch):
    from ravel.workflow.site_profiles import htcondor as hc
    monkeypatch.setattr(hc.subprocess, 'run', lambda argv, **k: subprocess.CompletedProcess(argv, 0, '4 1\n', ''))
    assert hc.status('1.0') == 'failed'
    monkeypatch.setattr(hc.subprocess, 'run', lambda argv, **k: subprocess.CompletedProcess(argv, 0, '', ''))
    assert hc.status('1.0') == 'running'
