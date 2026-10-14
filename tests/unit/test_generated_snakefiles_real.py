"""Every generated Snakefile is parsed by real Snakemake when RAVEL_TEST_SNAKEMAKE is set."""
import os
from pathlib import Path
import re
import subprocess

import pytest

from ravel.workflow import wms_runtime
from root_stream_fixture import pin

SKIP = 'set RAVEL_TEST_SNAKEMAKE to run real Snakemake'


def snakemake():
    argv = wms_runtime.snakemake_argv()
    if not argv or not os.environ.get('RAVEL_TEST_SNAKEMAKE'):
        pytest.skip(SKIP)
    return argv


def dry_run(argv, directory, env=None):
    done = subprocess.run([*argv, '-n', '--cores', '1', '--snakefile', 'Snakefile'], cwd=directory,
                          capture_output=True, text=True, timeout=180, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout + done.stderr


def rule_count(output):
    """Jobs listed in the dry-run summary table, excluding the total line."""
    rows = re.findall(r'^(\S+)\s+(\d+)\s*$', output.split('Job stats:')[1].split('\n\n')[0], re.M)
    return {name: int(n) for name, n in rows if name not in ('job', 'total')}


def test_procedure_export_dry_run(tmp_path):
    argv = snakemake()
    from test_procedure_export import run
    from ravel.workflow import procedure_export as pe
    out = tmp_path / 'export'
    pe.export(run(tmp_path / 'run'), out)
    counts = rule_count(dry_run(argv, out))
    assert sum(v for k, v in counts.items() if k.startswith('node_')) == 4 and counts['all'] == 1


def test_site_workflow_dry_run_and_no_parse_time_python(tmp_path, monkeypatch):
    argv = snakemake()
    from test_site_workflow import workflow_fixture
    from ravel.workflow import site_workflow as w
    request, _, _ = workflow_fixture(tmp_path, monkeypatch)
    log = tmp_path / 'invocations.log'
    recorder = tmp_path / 'analysis-python'
    recorder.write_text('#!/bin/sh\necho "$@" >> ' + str(log) + '\nexit 0\n')
    recorder.chmod(0o755)
    request['python'] = pin(recorder)
    result = w.export(request, tmp_path, tmp_path / 'export')
    out = tmp_path / 'export'
    snake = (out / 'Snakefile').read_text()
    assert 'subprocess' not in snake and 'rule ravel_verify_export' in snake and 'rule task_analyze' in snake
    fake = tmp_path / 'fakebin'
    fake.mkdir()
    for name in ('python', 'python3'):
        (fake / name).write_text('#!/bin/sh\necho "$@" >> ' + str(log) + '\nexit 0\n')
        (fake / name).chmod(0o755)
    (out / 'workflow.json').chmod(0)
    try:
        env = {**os.environ, 'PATH': f"{fake}:{os.environ['PATH']}"}
        counts = rule_count(dry_run(argv, out, env))
    finally:
        (out / 'workflow.json').chmod(0o644)
    assert counts == {'all': 1, 'ravel_verify_export': 1, 'task_analyze': 1}
    assert not log.exists(), 'a dry run must not start any RAVEL process'
    assert result['manifest']['sha256'] in snake


def test_submission_package_dry_run(tmp_path, monkeypatch):
    argv = snakemake()
    from test_submission_export import accepted_analysis
    from ravel.workflow import submission_export as se
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'plain')['package'])
    counts = rule_count(dry_run(argv, package))
    assert counts == {'all': 1, 'verify': 1}
