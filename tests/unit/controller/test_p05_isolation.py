"""Actual confined controls for committed inputs, resource bounds and launch seams."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_p05_support import operator, own, sandboxed  # noqa: F401
from test_p05_refusals import counters, run_tree, spec  # noqa: F401


def test_C18_C24_stage_capsule_excludes_unlisted_run_files_and_install(tmp_path, monkeypatch, sandboxed):
    from ravel.controller import confine
    from ravel.workflow import execution
    import ravel
    run = run_tree(tmp_path)
    own(monkeypatch, tmp_path / 'store', {run: 'run-capsule'})
    # A controller-owned run's launch reads the operator's current resource envelope (no retained-disk ceiling).
    operator(monkeypatch, {})
    source = run / 'inputs' / 'declared.txt'
    source.write_text('approved')
    withheld = run / 'withheld.txt'
    withheld.write_text('never admitted')
    program = '''import json,sys,pathlib
seen=[]
for p in sys.argv[1:]:
 try: seen.append(pathlib.Path(p).read_text())
 except OSError: seen.append('denied')
pathlib.Path('outputs/result.json').write_text(json.dumps(seen))
'''
    context = {'stage': 'read', 'stage_spec': {'inputs': [str(source)], 'outputs': [str(run / 'outputs')]},
               'environment_capsule': {'PATH': os.defpath}, 'input_snapshot': execution.snapshot(run, [str(source)])}
    capsule = confine.spec_for_stage(run, [sys.executable, '-c', program, str(source), str(withheld),
                                          str(Path(ravel.__file__))], context=context, cwd=run)
    assert str(run) not in capsule['reads']
    process = confine.popen(capsule, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = process.communicate(timeout=30)
    confine.finish(process)
    assert process.returncode == 0, err.decode()
    assert json.loads((run / 'outputs/result.json').read_text()) == ['approved', 'denied', 'denied']


def test_C18_input_mount_keeps_captured_bytes_after_host_mutation(tmp_path, sandboxed):
    if sandboxed != 'linux':
        pytest.skip('Linux private input-copy mount; macOS uses OS read denial and final digest check')
    from ravel.controller import confine
    source = tmp_path / 'source'
    source.mkdir()
    data = source / 'data'
    data.write_text('approved')
    output = tmp_path / 'output'
    output.mkdir()
    program = '''import pathlib,sys,time
print('ready',flush=True)
time.sleep(.5)
source=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2])
out.write_text(source.read_text() + '|' + ','.join(sorted(p.name for p in source.parent.iterdir())))
'''
    process = confine.popen({'argv': [sys.executable, '-c', program, str(data), str(output / 'result')],
                            'reads': [str(source)], 'writes': [str(output)],
                            'input_digests': {str(data): hashlib.sha256(b'approved').hexdigest()}},
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline() == b'ready\n'
        data.write_text('changed')
        (source / 'added-after-admission').write_text('unapproved')
        _, err = process.communicate(timeout=30)
    finally:
        confine.finish(process)
    assert process.returncode == 0, err.decode()
    assert (output / 'result').read_text() == 'approved|data'


def test_E06_launcher_enforces_wall_limit_without_caller_timeout(tmp_path, sandboxed):
    from ravel.controller import confine
    output = tmp_path / 'output'
    output.mkdir()
    process = confine.popen({'argv': [sys.executable, '-c', 'import time; time.sleep(60)'],
                            'writes': [str(output)], 'limits': {'wall_seconds': .3}},
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.communicate(timeout=10)
    confine.finish(process)
    assert process.returncode != 0
    assert process.ravel_confinement.record['wall_limit_exceeded'] is True


def test_SW34_hardlink_output_alias_refuses_before_effect(tmp_path, counters):
    from ravel.controller import confine
    run = run_tree(tmp_path)
    protected = tmp_path / 'protected'
    protected.write_text('original')
    os.link(protected, run / 'outputs' / 'alias')
    with pytest.raises(confine.ConfinementRefused, match='hard links'):
        confine.popen(spec(run))
    assert protected.read_text() == 'original' and counters['started'] == []


@pytest.mark.parametrize('mode', ['', '0', 'report'])
def test_SW38_controller_tripwire_cannot_be_disabled(tmp_path, monkeypatch, mode):
    from ravel.workflow import agent_tripwire, launch_authorization
    run = run_tree(tmp_path)
    store = own(monkeypatch, tmp_path / 'store', {run: 'run-tripwire'})['run-tripwire']
    monkeypatch.setenv('RAVEL_AGENT_TRIPWIRE', mode)
    monkeypatch.setattr(agent_tripwire, 'context', lambda: None)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **kw: pytest.fail('spawn reached'))
    with pytest.raises(agent_tripwire.TripwireViolation):
        launch_authorization.authorized_popen(run, 'full', ['inert'], context={})
    assert store.scan('tripwire')[0]['record']['ok'] is False


def test_SW16_SW37_broker_environment_has_no_startup_overrides(tmp_path):
    from ravel.controller.confine import brokers, locations
    env = brokers.environment({'PATH': os.defpath, 'GH_TOKEN': 'secret', 'BASH_ENV': '/bad',
                               'PYTHONPATH': '/bad', 'LD_LIBRARY_PATH': '/bad', 'GATE_TIMESTAMP': 'old',
                               'CLOCK_UTC': 'old', 'RAVEL_ROOT': '/bad'})
    assert env == {'PATH': os.defpath, 'PYTHONPATH': str(locations.package_root()),
                   'PYTHONNOUSERSITE': '1', 'PYTHONSAFEPATH': '1'}


def test_SW35_construction_payload_cannot_write_sibling_or_read_store(tmp_path, monkeypatch, sandboxed):
    from ravel.controller import confine
    from ravel.workflow import agentrivet_checks
    run = run_tree(tmp_path)
    store = own(monkeypatch, tmp_path / 'store', {run: 'run-build'})['run-build']
    operator(monkeypatch, {})
    marker = store.path('protected')
    marker.write_text('original')
    session = agentrivet_checks.Session.__new__(agentrivet_checks.Session)
    session.root = run / 'construction'
    work = session.root / 'work'
    work.mkdir(parents=True)
    session.checks = {'runtime': {'python': {'path': sys.executable}}, 'sample': None}
    program = '''import pathlib,sys
for p in sys.argv[1:]:
 try: pathlib.Path(p).write_text('bad');raise RuntimeError('write escaped')
 except OSError: pass
pathlib.Path('positive').write_text('ok')
'''
    plan = session._confinement([sys.executable, '-c', program, str(marker), str(session.root / 'sibling')],
                                work, {'PATH': os.defpath})
    proc = confine.start(plan, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = proc.communicate(timeout=30)
    confine.finish(proc)
    assert proc.returncode == 0, err.decode()
    assert marker.read_text() == 'original' and (work / 'positive').read_text() == 'ok'
    assert not (session.root / 'sibling').exists()
