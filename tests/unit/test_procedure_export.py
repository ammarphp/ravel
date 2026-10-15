"""Recorded procedures export without launching scientific jobs or schedulers."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_worker_audit import put, worker


def run(root):
    pin = put(root / 'outputs/value.json', {'value': 2})
    put(root / 'execution_state.json', {'schema_version': 1, 'revision': 1, 'stages': {
        'symbolic': {'status': 'succeeded', 'attempt_id': 's1', 'parents': {}, 'inputs': [], 'outputs': ['outputs/value.json'], 'output_snapshot': {'outputs/value.json': pin}},
        'numeric': {'status': 'failed', 'attempt_id': 's2', 'parents': {'symbolic': {}}, 'inputs': ['outputs/value.json'], 'outputs': []},
        'fit': {'status': 'succeeded', 'attempt_id': 's3', 'parents': {'numeric': {}}, 'inputs': [], 'outputs': []}}})
    worker(root, 'production')
    return root


def test_cli_exports_mapped_note_snakefile_and_computed_disclosure(tmp_path, capsys):
    from ravel import cli
    from ravel.workflow import procedure_export as pe
    from test_completion_claims import protocol
    rd = run(tmp_path / 'run'); protocol(rd)
    assert cli.main(['procedure', 'export', '--rundir', str(rd), '--into', str(tmp_path / 'export')]) == 0
    result = json.loads(capsys.readouterr().out); out = Path(result['directory'])
    note = (out / 'procedure.md').read_text(); doc = json.loads((out / 'procedure.json').read_text())
    assert 'synthetic-graph' in note and 'synthetic-thread' in note and 'synthetic-build' in note
    assert 'candidate_funnel' in note and doc['disclosure']['candidate_funnel']['generated'] == 3
    assert doc['execution_authorized'] is False
    snake = (out / 'Snakefile').read_text()
    assert snake.count('\nrule node_') == 4 and 'ravel procedure verify-node' in snake and 'approve' not in snake
    assert sys.executable not in snake
    assert Path(doc['run']).is_absolute()
    assert any('absolute source pins' in line for line in doc['limitations'])
    assert 'failed' in note and doc['environment']['snapshot_id']
    pe.verify(out)
    (rd / 'outputs/value.json').write_text('{"value":99}')
    with pytest.raises(ValueError, match='changed'):
        pe.verify(out)


def test_scheduler_labels_and_theory_chain_templates(tmp_path):
    from ravel.workflow import procedure_export as pe
    from ravel.workflow.site_profiles import render
    local = render('local', cores=3); condor = render('htcondor', cores=3)
    assert local['config']['cores'] == 3 and condor['config']['executor'] == 'cluster-generic'
    assert 'ravel-wms-condor-submit' in condor['config']['cluster-generic-submit-cmd']
    assert condor['release_status'] == 'tester-qualification' and not condor['qualified']
    with pytest.raises(ValueError, match='not available in this release'): render('slurm', cores=3)
    with pytest.raises(ValueError): render('local', retries=1)
    out = tmp_path / 'export'; pe.export(run(tmp_path / 'run'), out)
    theory = (out / 'templates/theory.smk').read_text()
    assert all('rule ' + stage in theory for stage in ('symbolic', 'numeric', 'fit'))
    assert 'symbolic.completed.json' in theory and 'numeric.completed.json' in theory
    assert all((out / 'profiles' / name / 'config.yaml').exists() for name in ('local', 'htcondor'))
    assert not (out / 'profiles/slurm').exists()


def test_snakemake_dry_run_or_structural_validation(tmp_path):
    from ravel.workflow import procedure_export as pe
    out = tmp_path / 'export'; pe.export(run(tmp_path / 'run'), out)
    pe.validate_snakefile((out / 'Snakefile').read_text(), 4)
    from ravel.workflow import wms_runtime
    argv = wms_runtime.snakemake_argv()
    if not os.environ.get('RAVEL_TEST_SNAKEMAKE') or not argv:
        pytest.skip('set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
    result = subprocess.run([*argv, '-n', '--cores', '1', '--snakefile', 'Snakefile'], cwd=out,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_export_refuses_overwrite_and_missing_research_disclosure(tmp_path):
    from ravel.workflow import procedure_export as pe
    rd = run(tmp_path / 'run'); out = tmp_path / 'export'; out.mkdir(); (out / 'keep').write_text('owner')
    with pytest.raises(ValueError, match='fresh'): pe.export(rd, out)
    assert (out / 'keep').read_text() == 'owner'
    put(rd / 'research/binding.json', {'kind': 'research-binding'})
    with pytest.raises((ValueError, OSError)): pe.export(rd, tmp_path / 'other')
    assert not (tmp_path / 'other').exists()


def test_closed_parent_export_is_automatic_and_reusable(tmp_path):
    from ravel.workflow import procedure_export as pe
    rd = run(tmp_path / 'run')
    first = pe.export_for_delivery(rd)
    second = pe.export_for_delivery(rd)
    assert first['directory'] == second['directory']
    assert (Path(first['directory']) / 'procedure.md').exists()
    assert second['reused'] is True


def test_export_does_not_adopt_changed_succeeded_output(tmp_path):
    from ravel.workflow import procedure_export as pe
    from ravel.workflow import execution
    rd = run(tmp_path / 'run')
    state = json.loads((rd / 'execution_state.json').read_text())
    state['stages']['symbolic']['output_snapshot'] = execution.snapshot(rd, ['outputs/value.json'], outputs=True)
    put(rd / 'execution_state.json', state)
    (rd / 'outputs/value.json').write_text('{"value":99}')
    with pytest.raises(ValueError, match='recorded output'): pe.export(rd, tmp_path / 'export')


def test_all_retained_stage_attempts_get_rules(tmp_path):
    from ravel.workflow import procedure_export as pe
    rd = run(tmp_path / 'run')
    put(rd / 'logs/execution/symbolic/old/record.json', {'stage': 'symbolic', 'attempt_id': 'old', 'status': 'failed',
         'command': ['synthetic-tool'], 'inputs': [], 'outputs': [], 'parents': {}})
    out = tmp_path / 'export'; pe.export(rd, out)
    doc = json.loads((out / 'procedure.json').read_text())
    assert len(doc['nodes']) == 5 and any(n['attempt_id'] == 'old' for n in doc['nodes'])


def test_external_disclosure_sources_stay_bound(tmp_path):
    from ravel.workflow import procedure_export as pe
    from test_completion_claims import protocol
    rd = run(tmp_path / 'run'); protocol(rd)
    before = put(tmp_path / 'before.json', {'rows': 10})
    after = put(tmp_path / 'after.json', {'rows': 5})
    put(rd / 'research/dataset_manifest_deltas.json', {'deltas': [{'operation': 'subsampling', 'reason': 'Synthetic reduction', 'before': before, 'after': after}]})
    out = tmp_path / 'export'; pe.export(rd, out)
    Path(before['path']).write_text('{"rows":99}')
    with pytest.raises(ValueError, match='source changed'): pe.verify(out)


def test_host_reuse_identity_tracks_procedure_helpers(tmp_path, monkeypatch):
    from ravel.workflow import agent_host, procedure_export as pe
    host = agent_host.AgentHost(); before = host.identity
    replacement = tmp_path / 'changed-exporter.py'; replacement.write_text(Path(pe.__file__).read_text() + '\n# changed dependency\n')
    monkeypatch.setattr(pe, '__file__', str(replacement))
    assert host.identity != before


def test_status_write_exports_any_closed_parent_and_keeps_open_parent_unexported(tmp_path, monkeypatch):
    from ravel.workflow import current_state
    rd = run(tmp_path / 'run')
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {'parent_task': {'completion': True}, 'lifecycle_verdict': 'PASS'})
    packet = current_state.write_packet(rd)
    assert (Path(packet['procedure_export']['directory']) / 'procedure.md').exists()
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {'parent_task': {'completion': False}, 'lifecycle_verdict': 'FAIL'})
    assert 'procedure_export' not in current_state.write_packet(rd)


def test_status_write_records_refused_export_without_blocking_status(tmp_path, monkeypatch):
    from ravel.workflow import current_state
    rd = run(tmp_path / 'run')
    put(rd / 'research/binding.json', {'kind': 'research-binding'})
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {'parent_task': {'completion': True}, 'lifecycle_verdict': 'PASS'})
    packet = current_state.write_packet(rd)
    assert packet['procedure_export']['status'] == 'refused' and packet['procedure_export']['reason']
    assert json.loads((rd / 'current_state.json').read_text())['procedure_export']['status'] == 'refused'
    assert not (rd / 'procedure-exports').exists() or not any((rd / 'procedure-exports').iterdir())


def recorded_large_run(root):
    import hashlib
    rd = run(root)
    artifact = rd / 'outputs/events.bin'
    with artifact.open('wb') as stream:
        stream.truncate(64 * 1024**2)
    sha = hashlib.sha256()
    with artifact.open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            sha.update(block)
    state = json.loads((rd / 'execution_state.json').read_text())
    state['stages']['symbolic'].update(outputs=['outputs/events.bin'], output_snapshot={
        str(artifact): {'kind': 'file', 'files': [{'name': '.', 'size': artifact.stat().st_size,
                                                'sha256': sha.hexdigest()}]}})
    put(rd / 'execution_state.json', state)
    return rd, artifact


def test_refresh_never_reads_large_recorded_output_and_deep_checks_bytes(tmp_path, monkeypatch, capsys):
    from ravel.workflow import current_state, procedure_export as pe
    rd, artifact = recorded_large_run(tmp_path / 'run')
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', str(1024**2))
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {
        'parent_task': {'completion': True}, 'lifecycle_verdict': 'PASS'})
    original = Path.open
    reads = []

    class Counted:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def read(self, *args):
            value = self.stream.read(*args); reads.append(len(value)); return value

    def counted(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return Counted(stream) if path == artifact and args and args[0] == 'rb' else stream

    monkeypatch.setattr(Path, 'open', counted)
    first = current_state.write_packet(rd)['procedure_export']
    second = current_state.write_packet(rd)['procedure_export']
    assert sum(reads) == 0
    assert first['directory'] == second['directory']
    out = Path(first['directory'])
    doc = pe.verify(out)
    pin = next(p for p in doc['source_pins'] if p['path'] == str(artifact))
    assert pin['reference_only'] is True and pin['sha256']
    assert sum(reads) == 0
    assert pe.main(['verify', '--package', str(out), '--deep']) == 0
    capsys.readouterr()
    assert sum(reads) >= artifact.stat().st_size
    with original(artifact, 'r+b') as stream: stream.write(b'x')
    pe.verify(out)
    with pytest.raises(ValueError, match='source changed'):
        pe.verify(out, deep=True)
    index = next(i for i, node in enumerate(doc['nodes']) if node.get('stage') == 'symbolic')
    with pytest.raises(ValueError, match='source changed'):
        pe.verify_node(out, index, first['procedure_sha256'], out / f'completed/node_{index}.json')
    import ast
    import shlex
    rule = (out / 'Snakefile').read_text().split(f'rule node_{index}:')[1].split('    shell: ')[1].splitlines()[0]
    command = shlex.split(ast.literal_eval(rule))
    # Exercise the generated PATH command with a fixture-only CLI entry point.
    bindir = tmp_path / 'bin'; bindir.mkdir()
    entry = bindir / 'ravel'
    entry.write_text(f'#!{sys.executable}\nfrom ravel.cli import main\nraise SystemExit(main())\n')
    entry.chmod(0o755)
    monkeypatch.setenv('PATH', str(bindir) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(command, cwd=out, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and 'source changed' in result.stderr


def test_refresh_environment_change_reuses_one_export(tmp_path, monkeypatch):
    from ravel.workflow import current_state, env_snapshot, procedure_export as pe
    rd = run(tmp_path / 'run')
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {
        'parent_task': {'completion': True}, 'lifecycle_verdict': 'PASS'})
    before = env_snapshot.capture(packages=[{'name': 'synthetic-package', 'version': '1'}])
    after = env_snapshot.capture(packages=[{'name': 'synthetic-package', 'version': '2'}])
    monkeypatch.setattr(pe.env_snapshot, 'capture', lambda: before)
    first = current_state.write_packet(rd)['procedure_export']
    monkeypatch.setattr(pe.env_snapshot, 'capture', lambda: after)
    second = current_state.write_packet(rd)['procedure_export']
    assert first['directory'] == second['directory'] and second['reused'] is True
    assert len(list((rd / 'procedure-exports').iterdir())) == 1
    assert second['snapshot_id'] == before['snapshot_id']


@pytest.mark.parametrize('verdict,status', [('FAIL', 'failed'), ('ABORTED', 'aborted'), ('INCOMPLETE', 'incomplete')])
def test_closed_nonpass_parent_gets_evidence_only_procedure(tmp_path, monkeypatch, verdict, status):
    from ravel.workflow import current_state, procedure_export as pe
    rd = run(tmp_path / 'run')
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {
        'parent_task': {'completion': True}, 'lifecycle_verdict': verdict})
    result = current_state.write_packet(rd)['procedure_export']
    assert result['procedure_status'] == status
    out = Path(result['directory']); doc = pe.verify(out)
    assert doc['procedure_status'] == status and doc['delivery_authorized'] is False
    assert 'delivered' not in (out / 'procedure.md').read_text().lower()
    snake = (out / 'Snakefile').read_text()
    assert 'verify-node' in snake and 'run-step' not in snake


@pytest.mark.parametrize('cores', [None, 8])
def test_delivery_profile_uses_recorded_cores(tmp_path, cores):
    import yaml
    from ravel.workflow import procedure_export as pe
    rd = run(tmp_path / 'run')
    if cores is not None: put(rd / 'inputs/site-profile.json', {'cores': cores})
    out = Path(pe.export_for_delivery(rd)['directory'])
    assert yaml.safe_load((out / 'profiles/local/config.yaml').read_text())['cores'] == (cores or 1)


def campaign(root):
    import hashlib
    root.mkdir()
    children = [run(root / 'experiments' / name) for name in ('arm-a', 'arm-b')]
    state = {'experiments': [{'id': p.name, 'rundir': str(p)} for p in children], 'base_dir': str(root)}
    pin = put(root / 'history/0000.json', state)
    put(root / 'head.json', pin)
    return children


def test_campaign_exports_stages_of_both_experiments(tmp_path):
    from ravel.workflow import procedure_export as pe
    rd = tmp_path / 'campaign'; children = campaign(rd)
    out = Path(pe.export_for_delivery(rd)['directory']); doc = pe.verify(out)
    stages = [n for n in doc['nodes'] if n['kind'] == 'stage']
    assert len(stages) == 6 and len({n['id'] for n in stages}) == 6
    assert sum(n['kind'] == 'worker' for n in doc['nodes']) == 2
    assert {n['run'] for n in stages} == {str(p) for p in children}
    assert all(set(n['depends_on']) <= {s['id'] for s in stages if s['run'] == n['run']} for n in stages)
    put(children[1] / 'logs/execution/symbolic/old/record.json', {'stage': 'symbolic', 'attempt_id': 'old', 'status': 'failed'})
    with pytest.raises(ValueError, match='roster changed'): pe.verify(out)


def test_report_parent_includes_registered_external_campaign(tmp_path):
    from ravel.workflow import procedure_export as pe
    parent = run(tmp_path / 'parent')
    cycle = tmp_path / 'campaign'; children = campaign(cycle)
    put(parent / 'inputs/completion_sources.json', {'schema_version': 1,
        'research_cycles': [__import__('test_task_completion', fromlist=['pin']).pin(cycle / 'head.json')]})
    completion = put(tmp_path / 'completion.json', {'parent_review': {'rundir': str(parent)}})
    out = Path(pe.attach_to_report(completion, base_dir=tmp_path)['directory'])
    doc = pe.verify(out)
    assert {n['run'] for n in doc['nodes'] if n['kind'] == 'stage'} == {str(parent), *(str(p) for p in children)}
    assert sum(n['kind'] == 'worker' for n in doc['nodes']) == 3


def test_sibling_interfaces_ship_replay_and_bind_runtime_pins(tmp_path, monkeypatch):
    from types import ModuleType
    from ravel import workflow
    from ravel.workflow import env_snapshot, procedure_export as pe
    rd = run(tmp_path / 'run')
    pin = put(rd / 'logs/runtime.json', {'environment': 'synthetic-stage-runtime'})
    module = ModuleType('ravel.workflow.replay')
    module.template_text = lambda: '# synthetic approved replay template\n'
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(workflow, 'replay', module, raising=False)
    monkeypatch.setattr(env_snapshot, 'runtime_snapshots', lambda root: [pin], raising=False)
    first = pe.export_for_delivery(rd)
    out = Path(first['directory']); doc = pe.verify(out)
    assert (out / 'templates/replay.smk').read_text() == module.template_text()
    assert pin in doc['source_pins'] and doc['runtime_snapshots'] == [pin]
    newer = put(rd / 'logs/runtime.json', {'environment': 'changed-stage-runtime'})
    monkeypatch.setattr(env_snapshot, 'runtime_snapshots', lambda root: [newer])
    assert pe.export_for_delivery(rd)['directory'] != first['directory']
    with pytest.raises(ValueError, match='source changed'): pe.verify(out, deep=True)


def test_merged_replay_template_interface(tmp_path):
    import importlib
    from ravel.workflow import procedure_export as pe
    try:
        replay = importlib.import_module('ravel.workflow.replay')
    except ModuleNotFoundError:
        pytest.xfail('awaits SMK-02')
    out = Path(pe.export_for_delivery(run(tmp_path / 'run'))['directory'])
    assert (out / 'templates/replay.smk').read_text() == replay.template_text()


def test_merged_runtime_snapshot_interface(tmp_path):
    from ravel.workflow import env_snapshot, procedure_export as pe
    if not callable(getattr(env_snapshot, 'runtime_snapshots', None)):
        pytest.xfail('awaits SMK-04')
    rd = run(tmp_path / 'run')
    out = Path(pe.export_for_delivery(rd)['directory'])
    doc = pe.verify(out)
    assert doc['runtime_snapshots'] == env_snapshot.runtime_snapshots(rd)


def test_large_unrecorded_input_is_reference_only_without_inventing_digest(tmp_path, monkeypatch):
    from ravel.workflow import procedure_export as pe
    rd = run(tmp_path / 'run'); path = rd / 'inputs/data.bin'; path.parent.mkdir(exist_ok=True)
    with path.open('wb') as stream: stream.truncate(2048)
    state = json.loads((rd / 'execution_state.json').read_text())
    state['stages']['numeric']['inputs'] = ['inputs/data.bin']
    put(rd / 'execution_state.json', state)
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', '1024')
    original = Path.open
    def forbidden_read(candidate, *args, **kwargs):
        if candidate == path and args and args[0] == 'rb': pytest.fail('unrecorded data was read')
        return original(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', forbidden_read)
    out = Path(pe.export_for_delivery(rd)['directory']); doc = pe.verify(out)
    pin = next(p for p in doc['source_pins'] if p['path'] == str(path))
    assert pin['reference_only'] is True and pin['sha256'] is None
    with pytest.raises(ValueError, match='no recorded digest'): pe.verify(out, deep=True)


@pytest.mark.parametrize('ceiling', ['bad', '-1'])
def test_invalid_byte_ceiling_refuses_export(tmp_path, monkeypatch, ceiling):
    from ravel.workflow import procedure_export as pe
    monkeypatch.setenv('RAVEL_PROCEDURE_BYTE_CEILING', ceiling)
    with pytest.raises(ValueError, match='ceiling'): pe.export_for_delivery(run(tmp_path / 'run'))


def test_nonpass_parent_retains_incomplete_disclosure(tmp_path, monkeypatch):
    from ravel.workflow import current_state, procedure_export as pe
    rd = run(tmp_path / 'run'); put(rd / 'research/binding.json', {'kind': 'research-binding'})
    monkeypatch.setattr(current_state, 'build_packet', lambda root: {
        'parent_task': {'completion': True}, 'lifecycle_verdict': 'FAIL'})
    result = current_state.write_packet(rd)['procedure_export']
    doc = pe.verify(result['directory'])
    assert doc['procedure_status'] == 'failed'
    assert doc['disclosure']['kind'] == 'research-disclosure-incomplete'
    assert doc['delivery_authorized'] is False


def test_ended_run_is_detected_from_real_packet_fields(tmp_path, monkeypatch):
    """Real packets carry no top-level status; ended runs are read from stages and review state."""
    from ravel.workflow import current_state
    rd = run(tmp_path / 'run')
    base = {'parent_task': {'completion': False}, 'lifecycle_verdict': 'FAIL'}
    cases = [({'execution': {'stages': {'a': {'status': 'failed'}}}}, 'failed'),
             ({'execution': {'stages': {'a': {'status': 'succeeded'}}}, 'physics_review': {'state': 'stopped'}}, 'aborted'),
             ({'execution': {'stages': {'a': {'status': 'failed'}, 'b': {'status': 'running'}}}}, None),
             ({'execution': {'stages': {'a': {'status': 'succeeded'}}}}, None)]
    for extra, expected in cases:
        monkeypatch.setattr(current_state, 'build_packet', lambda root, extra=extra: {**base, **extra})
        packet = current_state.write_packet(rd)
        if expected is None: assert 'procedure_export' not in packet
        else: assert packet['procedure_export']['procedure_status'] == expected
