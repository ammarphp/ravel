"""A relocatable submission package of an accepted RAVEL analysis."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

from ravel import cli
from ravel.workflow import submission_export as se
from test_task_completion import review_run

GIT = '/usr/bin/git' if Path('/usr/bin/git').exists() else shutil.which('git')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def accepted_analysis(tmp_path, monkeypatch, *, capture=True):
    rd = tmp_path / 'run'
    result = rd / 'inputs/result.json'
    result.parent.mkdir(parents=True)
    result.write_text(json.dumps({'schema_version': 1, 'kind': 'binned_values', 'bins': []}))
    review_run(rd, [str(result)] if capture else [], monkeypatch)
    from ravel.workflow import env_snapshot as es, environment_export as ee
    from test_environment_export import fixture_lock
    environment = es.capture(packages=[{'name': 'numpy', 'version': '1.0'}])
    environment.update(stage='analysis', attempt='a1')
    environment['snapshot_id'] = es.snapshot_id(environment)
    recorded = rd / 'logs/environment'; recorded.mkdir(parents=True)
    (recorded / 'analysis-a1.json').write_text(json.dumps(environment))
    lock = fixture_lock(tmp_path)
    export_environment = ee.write
    monkeypatch.setattr(ee, 'write', lambda package, pins:
                        export_environment(package, pins, lock, allow_fixture_lock=True))
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'yields.png').write_bytes(b'\x89PNG synthetic')
    (work / 'note.pdf').write_bytes(b'%PDF-1.5 synthetic')
    (work / 'recipe.json').write_text('{"regions": ["SR"]}\n')
    (work / 'selection.py').write_text('def select(event):\n    return True\n')
    (work / 'ntuple.root').write_bytes(b'root bytes')
    (work / 'prompts.jsonl').write_text(json.dumps({
        'event': 'prompt_submitted', 'timestamp': '2026-10-11T00:00:00.000Z', 'agent': 'claude-code',
        'session_id': 's1', 'prompt': 'Run the search', 'transcript_path': None, 'cwd': None}) + '\n')
    request = {
        'schema_version': 1, 'kind': 'ravel-submission-request', 'title': 'Synthetic search',
        'rundir': str(rd), 'claim_scope': 'diagnostic',
        'results': [str(result)], 'figures': ['yields.png'], 'note': ['note.pdf'],
        'recipe': ['recipe.json'], 'code': ['selection.py'], 'environment': [],
        'inputs': [{'name': 'signal ntuple', 'path': 'ntuple.root'},
                   {'name': 'background ntuple', 'uri': 'root://eos.example//bkg.root', 'sha256': 'a' * 64, 'size': 10}],
        'audit': {'logs': ['prompts.jsonl'], 'transcripts': []},
        'partitions': [], 'site_workflow': None, 'code_repository': None}
    path = work / 'request.json'
    path.write_text(json.dumps(request))
    return path, rd


def test_export_writes_a_relative_self_contained_package(tmp_path, monkeypatch):
    request, rd = accepted_analysis(tmp_path, monkeypatch)
    repo = tmp_path / 'repo'
    repo.mkdir()
    out = se.export(request, repo)
    package = Path(out['package'])
    manifest = json.loads((package / se.MANIFEST).read_text())
    acceptance = manifest['acceptance']
    assert manifest['kind'] == 'ravel-submission' and acceptance['review_accepted'] is True
    # A diagnostic scope never carries the scientific acceptance label.
    assert acceptance['claim_scope'] == 'diagnostic' and acceptance['delivery_label'] == 'diagnostic'
    assert acceptance['accepted'] is False and acceptance['notices']
    # The package records the decision, never the local receipt with its machine paths.
    assert 'architecture_receipt' not in acceptance and len(acceptance['architecture_receipt_sha256']) == 64
    for row in manifest['files']:
        assert not Path(row['path']).is_absolute() and '..' not in Path(row['path']).parts
        assert sha(package / row['path']) == row['sha256']
    categories = {row['category'] for row in manifest['files']}
    assert {'results', 'figures', 'note', 'recipe', 'code', 'run', 'environment', 'audit', 'workflow'} <= categories
    # Inputs are referenced with checksums, never copied.
    assert not any(row['path'].endswith('ntuple.root') for row in manifest['files'])
    inputs = json.loads((package / 'inputs.json').read_text())['inputs']
    assert inputs[0]['sha256'] == sha(tmp_path / 'work/ntuple.root') and inputs[0]['reference'] == 'local'
    assert inputs[1]['uri'].startswith('root://') and inputs[1]['sha256'] == 'a' * 64
    code = manifest['code_version']
    assert code['ravel_version'] and 'source_commit' in code
    assert (package / 'environment/analysis-requirements.txt').read_text() == 'numpy==1.0\n'
    assert (package / 'environment/runtime/analysis-a1.json').is_file()
    dag = json.loads((package / 'workflow/dag.json').read_text())
    stage = next(n for n in dag['nodes'] if n['id'] == 'stage:detector')
    assert stage['status'] == 'succeeded' and 'run/inputs/result.json' in stage['inputs']
    assert all(not Path(v).is_absolute() for v in stage['inputs'] + stage['outputs'])
    summary = json.loads((package / 'audit/agent-audit.json').read_text())
    assert [g['prompt'] for g in summary['gaps']] == ['Run the search']
    assert 'Run the search' in (package / 'audit/hook-log.jsonl').read_text()
    assert (package / 'REPRODUCE.md').read_text().count('ravel export-submission verify') == 1
    report = se.verify(package)
    assert report['passed'], report['errors']


@pytest.mark.parametrize('change, error', [
    ('no_review', 'the package does not record an accepted review'),
    ('promoted', 'the package delivery label differs from its accepted claim scope'),
    ('scope', 'the package delivery label differs from its accepted claim scope'),
    ('unknown', 'the package delivery label differs from its accepted claim scope'),
])
def test_package_label_must_match_its_accepted_review_and_scope(tmp_path, monkeypatch, change, error):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    path = package / se.MANIFEST
    manifest = json.loads(path.read_text())
    acceptance = manifest['acceptance']
    if change == 'no_review':
        acceptance.pop('review_accepted')
    elif change == 'promoted':
        acceptance['accepted'] = True
    elif change == 'scope':
        acceptance['claim_scope'] = 'computed'
    else:
        acceptance['delivery_label'] = 'governed'
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    report = se._check(package)
    assert not report['passed'] and error in report['errors']


def test_submission_exports_stage_runtime_instead_of_exporter(tmp_path, monkeypatch):
    from ravel.workflow import env_snapshot as es
    request, rd = accepted_analysis(tmp_path, monkeypatch)
    value = es.capture(packages=[{'name': 'numpy', 'version': '1.0'}])
    value.update(stage='analysis', attempt='a1')
    value['snapshot_id'] = es.snapshot_id(value)
    directory = rd / 'logs/environment'; directory.mkdir(parents=True, exist_ok=True)
    (directory / 'analysis-a1.json').write_text(json.dumps(value))
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    assert (package / 'environment/analysis-requirements.txt').read_text() == 'numpy==1.0\n'
    note = (package / 'REPRODUCE.md').read_text()
    assert '.venv-analysis' in note and '.venv-wms' in note and 'environment/setup.sh' in note
    assert se._check(package)['passed']


def test_unaccepted_result_is_refused(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch, capture=False)
    with pytest.raises(ValueError, match='accepted review'):
        se.export(request, tmp_path / 'repo')


def test_existing_package_is_never_overwritten(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    repo = tmp_path / 'repo'
    (repo / 'submission').mkdir(parents=True)
    (repo / 'submission/keep.txt').write_text('owner file')
    with pytest.raises(ValueError, match='new or empty'):
        se.export(request, repo)
    assert (repo / 'submission/keep.txt').read_text() == 'owner file'


def test_remote_input_requires_a_supplied_checksum(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    value = json.loads(request.read_text())
    del value['inputs'][1]['sha256']
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='sha256'):
        se.export(request, tmp_path / 'repo')


def test_verify_detects_changed_and_extra_absolute_references(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    (package / 'figures/yields.png').write_bytes(b'changed')
    report = se.verify(package)
    assert not report['passed'] and any('figures/yields.png' in e for e in report['errors'])


def test_package_names_its_own_location_nowhere(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    (package / 'note/extra.txt').write_text(f'see {package}/figures')
    report = se.verify(package)
    assert not report['passed'] and any('not listed' in e for e in report['errors'])


def test_rule_pack_requirements_are_checked(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    rules = tmp_path / 'rules.json'
    rules.write_text(json.dumps({'schema_version': 1, 'kind': 'submission-rules', 'required': ['note', 'figures', 'audit'],
                                 'note_suffixes': ['.pdf'], 'max_file_bytes': 4, 'max_total_bytes': None}))
    with pytest.raises(ValueError, match='larger than'):
        se.export(request, tmp_path / 'repo', rules=rules)
    value = json.loads(rules.read_text())
    value['max_file_bytes'] = 10 ** 7
    value['required'].append('partitions')
    rules.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='partitions'):
        se.export(request, tmp_path / 'repo2', rules=rules)


@pytest.mark.skipif(GIT is None, reason='git is required for the fresh-clone check')
def test_fresh_clone_dry_run_finds_files_git_would_drop(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    repo = tmp_path / 'repo'
    repo.mkdir()
    env = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@x',
           'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin'}
    git = lambda *a: subprocess.run([GIT, '-C', str(repo), *a], check=True, capture_output=True, env=env)
    git('init', '-q')
    (repo / '.gitignore').write_text('*.png\n')
    package = Path(se.export(request, repo)['package'])
    git('add', '-A')
    git('commit', '-q', '-m', 'submission')
    report = se.verify(package, fresh_clone=True)
    assert not report['passed'] and any('yields.png' in e for e in report['errors'])
    assert report['fresh_clone']['method'] == 'git clone'
    (repo / '.gitignore').write_text('')
    git('add', '-A', '-f')
    git('commit', '-q', '-m', 'figures')
    report = se.verify(package, fresh_clone=True)
    assert report['passed'], report['errors']


def test_fresh_copy_check_without_git(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'plain')['package'])
    report = se.verify(package, fresh_clone=True)
    assert report['passed'] and report['fresh_clone']['method'] == 'copy'


def test_uncommitted_package_is_reported_before_cloning(tmp_path, monkeypatch):
    if GIT is None:
        pytest.skip('git required')
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run([GIT, '-C', str(repo), 'init', '-q'], check=True)
    package = Path(se.export(request, repo)['package'])
    report = se.verify(package, fresh_clone=True)
    assert not report['passed'] and any('commit' in e for e in report['errors'])


def test_partition_outputs_are_consumed_through_the_public_summary(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    work = tmp_path / 'partitions'
    (work / 'merged').mkdir(parents=True)
    merged = work / 'merged/yields.json'
    merged.write_text('{"kind": "counts"}')
    receipt = {'schema_version': 1, 'kind': 'ravel-partition-merge', 'name': 'signal', 'specification_sha256': 'b' * 64,
               'partitions': [{'partition': 'p0000'}, {'partition': 'p0001'}],
               'merged': [{'name': 'yields.json', 'merge': 'counts', 'path': str(merged), 'sha256': sha(merged)}]}
    (work / 'merge-receipt.json').write_text(json.dumps(receipt))
    fake = types.ModuleType('ravel.workflow.partitioned_execution')
    fake.MERGE_RECEIPT = 'merge-receipt.json'
    fake.summary = lambda w: {'name': 'signal', 'partitions': 2, 'succeeded': 2, 'failed': [], 'pending': [], 'status': 'complete'}
    monkeypatch.setitem(sys.modules, 'ravel.workflow.partitioned_execution', fake)
    value = json.loads(request.read_text())
    value['partitions'] = [str(work)]
    request.write_text(json.dumps(value))
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    assert json.loads((package / 'partitions/signal/yields.json').read_text()) == {'kind': 'counts'}
    dag = json.loads((package / 'workflow/dag.json').read_text())
    node = next(n for n in dag['nodes'] if n['id'] == 'partitions:signal')
    assert node['partitions'] == 2 and node['outputs'] == ['partitions/signal/yields.json']
    fake.summary = lambda w: {'name': 'signal', 'partitions': 2, 'succeeded': 1, 'failed': ['p0001'], 'pending': [], 'status': 'incomplete'}
    with pytest.raises(ValueError, match='incomplete'):
        se.export(request, tmp_path / 'repo2')


def test_site_workflow_is_verified_through_its_public_check(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    site = tmp_path / 'site'
    site.mkdir()
    for name in ('workflow.json', 'Snakefile', 'export-closure.json'):
        (site / name).write_text(name)
    from ravel.workflow import site_workflow
    calls = []
    monkeypatch.setattr(site_workflow, 'verify', lambda path, digest: calls.append((Path(path), digest)) or {'tasks': [{'id': 't1'}]})
    value = json.loads(request.read_text())
    value['site_workflow'] = {'export': str(site), 'sha256': sha(site / 'workflow.json')}
    request.write_text(json.dumps(value))
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    assert calls == [(site / 'workflow.json', sha(site / 'workflow.json'))]
    assert (package / 'workflow/site/Snakefile').read_text() == 'Snakefile'


def test_cli_one_liner(tmp_path, monkeypatch, capsys):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    assert cli.main(['export-submission', '--request', str(request), '--into', str(tmp_path / 'repo')]) == 0
    package = json.loads(capsys.readouterr().out)['package']
    assert cli.main(['export-submission', 'verify', '--package', package]) == 0


def test_fresh_check_runs_a_snakemake_dry_run_over_the_package(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'plain')['package'])
    assert 'submission.json' in (package / 'Snakefile').read_text()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    stub = bin_dir / 'snakemake'
    stub.write_text('#!/bin/sh\n'
                    'test "$1" = "-n" || exit 3\n'
                    'test -f Snakefile && test -f submission.json || exit 4\n'
                    'case "$PWD" in *ravel-fresh-*) exit 0;; *) exit 5;; esac\n')
    stub.chmod(0o755)
    monkeypatch.delenv('RAVEL_SNAKEMAKE', raising=False)
    monkeypatch.delenv('RAVEL_TEST_SNAKEMAKE', raising=False)
    monkeypatch.setenv('PATH', f"{bin_dir}:{__import__('os').environ['PATH']}")
    report = se.verify(package, fresh_clone=True)
    assert report['passed'], report['errors']
    assert report['fresh_clone']['snakemake']['status'] == 'passed'
    stub.write_text('#!/bin/sh\necho "MissingInputException: figures/yields.png"\nexit 1\n')
    report = se.verify(package, fresh_clone=True)
    assert not report['passed'] and any('MissingInput' in e for e in report['errors'])


def test_snakemake_dry_run_finds_snakemake_through_ravel_snakemake(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    package = Path(se.export(request, tmp_path / 'plain')['package'])
    stub = tmp_path / 'elsewhere' / 'snakemake'
    stub.parent.mkdir()
    stub.write_text('#!/bin/sh\necho dry\nexit 0\n')
    stub.chmod(0o755)
    empty = tmp_path / 'empty-bin'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))
    monkeypatch.delenv('RAVEL_SNAKEMAKE', raising=False)
    monkeypatch.delenv('RAVEL_TEST_SNAKEMAKE', raising=False)
    assert se.snakemake_dry_run(package)['status'] == 'not-installed'
    monkeypatch.setenv('RAVEL_SNAKEMAKE', str(stub))
    assert se.snakemake_dry_run(package)['status'] == 'passed'


def test_submission_automatically_includes_every_worker_transcript(tmp_path, monkeypatch):
    from test_worker_audit import worker
    request, rd = accepted_analysis(tmp_path, monkeypatch)
    for role in ('production', 'reviewer', 'consult', 'rdj', 'research-coordinator'):
        worker(rd, role)
    package = Path(se.export(request, tmp_path / 'repo')['package'])
    records = [json.loads(line) for line in (package / 'audit/agent-audit.jsonl').read_text().splitlines()]
    assert {r['ravel']['role_id'] for r in records} == {'production', 'reviewer', 'consult', 'rdj', 'research-coordinator'}
    assert (package / 'procedure/procedure.md').is_file()
    assert len(json.loads((package / 'audit/worker-audit.json').read_text())['sessions']) == 5
