"""Read-only conformance checks over two requester-supplied fictional policies."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

import pytest

from ravel import cli

GIT = '/usr/bin/git'


def engine():
    return importlib.import_module('ravel.workflow.submission_conformance')


def git(repo, *args):
    return subprocess.run([GIT, '-C', str(repo), *args], check=True, capture_output=True).stdout


def write(repo, path, value):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value)
    return target


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def commit(repo):
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Synthetic files')


@pytest.fixture
def supplied(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    instruction = write(repo, 'PROJECT.md', 'Fictional project instructions.\n')
    digest = sha(instruction)
    prompt = {'session_id': 'ANA-0001', 'prompt': 'Inspect supplied fictional data.',
              'model': 'synthetic-build-1', 'model_build_exact': True,
              'timestamp': '2026-01-01T00:00:00Z', 'usage_reported': True,
              'usage': {'input_tokens': 2, 'cached_input_tokens': 0, 'cache_creation_input_tokens': 0,
                        'output_tokens': 1, 'total_tokens': 3}, 'instruction_sha256': digest}
    write(repo, 'audit.json', {'records': [prompt], 'gaps': []})
    write(repo, 'stages.json', {'stages': [{'id': 'compute', 'attempt': 'a1', 'executed': True}]})
    write(repo, 'launches.json', {'receipts': [{'stage': 'compute', 'attempt': 'a1',
          'manager': 'synthetic-manager', 'policy_sha256': 'a' * 64}]})
    write(repo, 'guard.json', {'policy_sha256': 'a' * 64, 'complete': True,
          'commands': [{'allowed': True, 'within_policy': True}]})
    from ravel.workflow import env_snapshot
    runtime = env_snapshot.capture(packages=[{'name': 'fictional-pkg', 'version': '1.0'}])
    runtime.update(stage='compute', attempt='a1')
    runtime['snapshot_id'] = env_snapshot.snapshot_id(runtime)
    write(repo, 'runtime/compute-a1.json', runtime)
    write(repo, 'requirements.txt', 'fictional-pkg==1.0\n')
    write(repo, 'availability.json', {'distributions': [{'name': 'fictional-pkg', 'version': '1.0',
          'public': True, 'url': 'https://packages.example.invalid/pkg.whl', 'sha256': 'b' * 64}]})
    write(repo, 'invoked.json', {'executables': ['synthetic-tool'], 'distributions': ['fictional-pkg']})
    write(repo, 'skills/tool.md', 'Instructions for the fictional executable.\n')
    write(repo, 'skills/package.md', 'Instructions for the fictional distribution.\n')
    write(repo, 'coverage.json', {'skills': [
        {'kind': 'executable', 'name': 'synthetic-tool', 'path': 'skills/tool.md'},
        {'kind': 'distribution', 'name': 'fictional-pkg', 'path': 'skills/package.md'}]})
    write(repo, 'workflow.json', {'rules': [{'id': 'calculate', 'kind': 'compute'},
          {'id': 'verify', 'kind': 'quantity-comparison', 'tolerances': 'tolerances.json'}]})
    write(repo, 'tolerances.json', {'absolute': 0.01})
    write(repo, 'intermediates.json', {'artifacts': [{'sha256': 'c' * 64, 'storage_path': '/storage/fictional'}]})
    write(repo, 'note.pdf', '%PDF synthetic fixture\n')
    write(repo, 'note.aux', '\\zref@newlabel{ravel-reference-start}{\\abspage{3}}\n'
          '\\zref@newlabel{main-start}{\\abspage{1}}\n'
          '\\zref@newlabel{main-end}{\\abspage{2}}\n'
          '\\zref@newlabel{ref-start}{\\abspage{3}}\n'
          '\\zref@newlabel{ref-end}{\\abspage{4}}\n')
    write(repo, 'segments.json', [{'id': 'body', 'section': 'main', 'start': 'main-start',
          'end': 'main-end', 'counted': True}, {'id': 'refs', 'section': 'references',
          'start': 'ref-start', 'end': 'ref-end', 'counted': False}])
    commit(repo)
    git(repo, 'tag', 'synthetic-submission')
    rules = [
        ('instructions', 'instruction_hash', {'path': 'PROJECT.md', 'sha256': digest}),
        ('sessions', 'session_instructions', {'path': 'audit.json', 'sha256': digest}),
        ('prompts', 'prompt_log', {'path': 'audit.json'}),
        ('launch', 'workflow_launches', {'stages': 'stages.json', 'receipts': 'launches.json',
          'guard_log': 'guard.json', 'policy_sha256': 'a' * 64, 'manager': 'synthetic-manager'}),
        ('tracked', 'tracked_clean', {'paths': ['PROJECT.md']}),
        ('environment', 'environment', {'stages': 'stages.json', 'runtime_directory': 'runtime',
          'requirements': 'requirements.txt', 'installability': 'availability.json'}),
        ('skills', 'skill_coverage', {'invoked': 'invoked.json', 'coverage': 'coverage.json'}),
        ('compare', 'rerun_comparison', {'workflow': 'workflow.json', 'tolerances': 'tolerances.json'}),
        ('size', 'size_budget', {'max_file_bytes': 50 * 1024 * 1024 - 1, 'intermediates': 'intermediates.json'}),
        ('pages', 'note_limits', {'pdf': 'note.pdf', 'aux': 'note.aux', 'segments': 'segments.json', 'max_main_pages': 2}),
        ('tag', 'submission_tag', {'tag': 'synthetic-submission'}),
    ]
    pack = {'schema_version': 1, 'kind': 'conformance-rule-pack',
            'rules': [{'id': identity, 'check': kind, 'params': params} for identity, kind, params in rules]}
    return repo, pack


def statuses(report):
    return {r['id']: r['status'] for r in report['rules']}


def one(pack, identity):
    value = deepcopy(pack)
    value['rules'] = [r for r in value['rules'] if r['id'] == identity]
    return value


def fake_pdfinfo(monkeypatch):
    module = engine()
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/fictional/pdfinfo')
    original = module.subprocess.run
    def run(argv, **kwargs):
        if argv[0] == '/fictional/pdfinfo':
            return subprocess.CompletedProcess(argv, 0, 'Pages: 4\n', '')
        return original(argv, **kwargs)
    monkeypatch.setattr(module.subprocess, 'run', run)


def test_command_available_and_four_planted_failures(supplied, tmp_path):
    repo, pack = supplied
    write(repo, 'PROJECT.md', 'Modified instructions.\n')
    write(repo, 'requirements.txt', 'unpublished-fictional==9.0\n')
    write(repo, 'availability.json', {'distributions': [{'name': 'unpublished-fictional', 'version': '9.0', 'public': False}]})
    write(repo, 'workflow.json', {'rules': [{'id': 'calculate', 'kind': 'compute'}]})
    with (repo / 'large.bin').open('wb') as stream:
        stream.truncate(50 * 1024 * 1024)
    commit(repo)
    rulefile = write(tmp_path, 'rules.json', pack)
    out = tmp_path / 'report.json'
    assert cli.main(['conformance', 'check', '--repo', str(repo), '--rules', str(rulefile), '--out', str(out)]) == 1
    report = json.loads(out.read_text())
    assert all(statuses(report)[key] == 'FAIL' for key in ('instructions', 'environment', 'compare', 'size'))
    assert all(r['evidence'] and r['fix_hint'] for r in report['rules'] if r['status'] == 'FAIL')


@pytest.mark.parametrize('mutation', ['receipt', 'gap', 'text', 'model', 'timestamp', 'tokens'])
def test_missing_prompt_evidence_fails(supplied, mutation):
    repo, pack = supplied
    audit = json.loads((repo / 'audit.json').read_text())
    row = audit['records'][0]
    if mutation == 'receipt':
        del row['instruction_sha256']
    elif mutation == 'gap':
        audit['gaps'].append({'session_id': 'ANA-0002'})
    elif mutation == 'tokens':
        row['usage']['input_tokens'] = None
    else:
        row[{'text': 'prompt', 'model': 'model', 'timestamp': 'timestamp'}[mutation]] = None
    write(repo, 'audit.json', audit)
    kind = 'sessions' if mutation == 'receipt' else 'prompts'
    assert statuses(engine().check(repo, one(pack, kind)))[kind] == 'FAIL'


@pytest.mark.parametrize('mutation', ['no_receipt', 'direct', 'outside_policy', 'wrong_attempt'])
def test_launch_violation_fails(supplied, mutation):
    repo, pack = supplied
    launches = json.loads((repo / 'launches.json').read_text())
    if mutation == 'no_receipt':
        launches['receipts'] = []
    elif mutation == 'direct':
        launches['receipts'].append({'stage': 'other', 'attempt': 'a2', 'manager': 'direct'})
    elif mutation == 'wrong_attempt':
        launches['receipts'][0]['attempt'] = 'a2'
    else:
        guard = json.loads((repo / 'guard.json').read_text())
        guard['commands'][0]['within_policy'] = False
        write(repo, 'guard.json', guard)
    write(repo, 'launches.json', launches)
    assert statuses(engine().check(repo, one(pack, 'launch')))['launch'] == 'FAIL'


@pytest.mark.parametrize('mutation', ['dirty', 'staged', 'untracked', 'deleted'])
def test_tracking_violations_fail(supplied, mutation):
    repo, pack = supplied
    if mutation == 'untracked':
        write(repo, 'other.py', '# fictional code\n')
        pack = one(pack, 'tracked')
        pack['rules'][0]['params']['paths'] = ['other.py']
    elif mutation == 'deleted':
        (repo / 'PROJECT.md').unlink()
    else:
        write(repo, 'PROJECT.md', 'Changed.\n')
        if mutation == 'staged':
            git(repo, 'add', 'PROJECT.md')
            write(repo, 'PROJECT.md', 'Fictional project instructions.\n')
    assert statuses(engine().check(repo, one(pack, 'tracked')))['tracked'] == 'FAIL'


@pytest.mark.parametrize('identity, path', [('prompts', 'audit.json'), ('launch', 'guard.json'),
    ('environment', 'runtime/compute-a1.json'), ('skills', 'invoked.json'), ('pages', 'note.pdf')])
def test_absent_source_is_never_pass(supplied, identity, path):
    repo, pack = supplied
    (repo / path).unlink()
    report = engine().check(repo, one(pack, identity))
    assert statuses(report)[identity] == 'NOT-CHECKABLE'
    assert path in json.dumps(report['rules'][0]['evidence'])


def test_unknown_installability_is_not_checkable(supplied):
    repo, pack = supplied
    write(repo, 'availability.json', {'distributions': []})
    assert statuses(engine().check(repo, one(pack, 'environment')))['environment'] == 'NOT-CHECKABLE'


def test_runtime_wrong_attempt_fails(supplied):
    repo, pack = supplied
    path = repo / 'runtime/compute-a1.json'
    record = json.loads(path.read_text())
    record['attempt'] = 'a2'
    from ravel.workflow.env_snapshot import snapshot_id
    record['snapshot_id'] = snapshot_id(record)
    write(repo, 'runtime/compute-a1.json', record)
    assert statuses(engine().check(repo, one(pack, 'environment')))['environment'] == 'FAIL'


def test_untracked_skill_fails(supplied):
    repo, pack = supplied
    write(repo, 'new.md', 'Fictional skill\n')
    coverage = json.loads((repo / 'coverage.json').read_text())
    coverage['skills'][0]['path'] = 'new.md'
    write(repo, 'coverage.json', coverage)
    assert statuses(engine().check(repo, one(pack, 'skills')))['skills'] == 'FAIL'


def test_tag_must_point_at_head(supplied):
    repo, pack = supplied
    write(repo, 'other.txt', 'Another fictional revision\n')
    commit(repo)
    assert statuses(engine().check(repo, one(pack, 'tag')))['tag'] == 'FAIL'


@pytest.mark.parametrize('path', ['../escape', '/tmp/escape', '.git/config'])
def test_unsafe_evidence_paths_fail(supplied, path):
    repo, pack = supplied
    value = one(pack, 'instructions')
    value['rules'][0]['params']['path'] = path
    assert statuses(engine().check(repo, value))['instructions'] == 'FAIL'


def test_symlink_evidence_fails(supplied, tmp_path):
    repo, pack = supplied
    original = repo / 'PROJECT.md'
    target = tmp_path / 'outside.md'
    original.rename(target)
    original.symlink_to(target)
    assert statuses(engine().check(repo, one(pack, 'instructions')))['instructions'] == 'FAIL'


def test_report_inside_inspected_repository_refused(supplied, tmp_path):
    repo, pack = supplied
    rulefile = write(tmp_path, 'rules.json', pack)
    out = repo / 'report.json'
    assert cli.main(['conformance', 'check', '--repo', str(repo), '--rules', str(rulefile), '--out', str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize('mutation', ['unknown', 'duplicate', 'empty', 'version', 'params'])
def test_invalid_rule_pack_refused(supplied, mutation):
    repo, pack = supplied
    if mutation == 'unknown':
        pack['rules'][0]['check'] = 'execute-shell'
    elif mutation == 'duplicate':
        pack['rules'].append(deepcopy(pack['rules'][0]))
    elif mutation == 'empty':
        pack['rules'] = []
    elif mutation == 'version':
        pack['schema_version'] = 2
    else:
        pack['rules'][0]['params']['shell'] = 'touch ignored'
    with pytest.raises(ValueError):
        engine().check(repo, pack)


def tree_digest(root):
    """Include git metadata, untracked files and all regular file bytes."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_symlink():
            digest.update(str(path.readlink()).encode())
        elif path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_all_supplied_evidence_passes_without_tree_writes(supplied, monkeypatch):
    repo, pack = supplied
    fake_pdfinfo(monkeypatch)
    before = tree_digest(repo)
    report = engine().check(repo, pack)
    assert set(statuses(report).values()) == {'PASS'}, report
    assert report['passed'] and report['counts']['PASS'] == 11
    assert tree_digest(repo) == before
    assert 'PASS' in engine().render_markdown(report)


def test_second_pack_changes_policy_identity_parameters_and_paths(supplied, tmp_path, monkeypatch):
    repo, first = supplied
    fake_pdfinfo(monkeypatch)
    second = {'schema_version': 1, 'kind': 'conformance-rule-pack', 'rundirs': ['runs/ANA-0002'], 'rules': [
        {'id': 'ANA-0002-file', 'check': 'instruction_hash', 'scope': 'runs',
         'params': {'path': 'POLICY.txt', 'sha256': 'd' * 64}},
        {'id': 'ANA-0002-size', 'check': 'size_budget', 'params': {'max_file_bytes': 1}},
        {'id': 'ANA-0002-disabled', 'check': 'submission_tag', 'enabled': False,
         'params': {'tag': 'another-fictional-tag'}},
    ]}
    instruction = write(repo, 'runs/ANA-0002/POLICY.txt', 'A different fictional policy.\n')
    second['rules'][0]['params']['sha256'] = sha(instruction)
    commit(repo)
    report = engine().check(repo, second)
    assert statuses(report) == {'ANA-0002-file': 'PASS', 'ANA-0002-size': 'FAIL',
                                'ANA-0002-disabled': 'NOT-CHECKABLE'}
    assert statuses(engine().check(repo, one(first, 'instructions')))['instructions'] == 'PASS'
    assert not any((Path(engine().__file__).parents[1] / 'data/submission').glob('rule-packs/*'))


def test_conforming_available_sources_missing_pdfinfo_is_not_checkable(supplied, monkeypatch):
    repo, pack = supplied
    monkeypatch.setattr(engine().shutil, 'which', lambda _: None)
    report = engine().check(repo, pack)
    assert statuses(report)['pages'] == 'NOT-CHECKABLE'
    assert all(status == 'PASS' for identity, status in statuses(report).items() if identity != 'pages')
    assert 'pdfinfo' in json.dumps(report['rules'][9]['evidence'])


def test_prompt_log_inexact_build_lists_row(supplied):
    repo, pack = supplied
    audit = json.loads((repo / 'audit.json').read_text())
    audit['records'][0]['model_build_exact'] = False
    write(repo, 'audit.json', audit)
    report = engine().check(repo, one(pack, 'prompts'))
    assert statuses(report)['prompts'] == 'NOT-CHECKABLE'
    assert any(e.get('row') == 1 and e.get('field') == 'model_build_exact' for e in report['rules'][0]['evidence'])


def test_cli_markdown_and_incomplete_exit_code(supplied, tmp_path, monkeypatch):
    repo, pack = supplied
    monkeypatch.setattr(engine().shutil, 'which', lambda _: None)
    rules = write(tmp_path, 'rules.json', one(pack, 'pages'))
    out = tmp_path / 'report.md'
    before = tree_digest(repo)
    assert cli.main(['conformance', 'check', '--repo', str(repo), '--rules', str(rules), '--out', str(out)]) == 3
    assert 'NOT-CHECKABLE' in out.read_text() and 'pdfinfo' in out.read_text()
    assert tree_digest(repo) == before


def test_cli_pass_json_and_explicit_run_root(supplied, tmp_path):
    repo, pack = supplied
    rules = one(pack, 'instructions')
    rules['rules'][0]['scope'] = 'runs'
    external_run = tmp_path / 'run'
    external_run.mkdir()
    write(external_run, 'PROJECT.md', 'Fictional project instructions.\n')
    path = write(tmp_path, 'rules.json', rules)
    out = tmp_path / 'report.json'
    before = tree_digest(repo), tree_digest(external_run)
    assert cli.main(['conformance', 'check', '--repo', str(repo), '--rules', str(path),
                     '--rundir', str(external_run), '--out', str(out)]) == 0
    assert json.loads(out.read_text())['passed']
    assert (tree_digest(repo), tree_digest(external_run)) == before


def test_schema_matches_runtime_and_two_pack_validation(supplied):
    import jsonschema
    repo, pack = supplied
    module = engine()
    path = Path(module.__file__).parents[1] / 'data/submission/rule-pack.schema.json'
    schema = json.loads(path.read_text())
    assert schema == module.rule_pack_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(pack, schema)
    jsonschema.validate(one(pack, 'size'), schema)


@pytest.mark.xfail(strict=True, reason='awaits HB-02')
def test_prompt_producer_supplies_instruction_receipt(supplied):
    from ravel.workflow import agent_audit
    repo, pack = supplied
    row = agent_audit._record('synthetic-agent', {}, {'id': 'ANA-0001'},
          {'id': 'main', 'sidechain': False}, 1, '2026-01-01T00:00:00Z', 'Fictional prompt.')
    write(repo, 'audit.json', {'records': [row], 'gaps': []})
    assert statuses(engine().check(repo, one(pack, 'sessions')))['sessions'] == 'PASS'


@pytest.mark.xfail(strict=True, reason='awaits HB-03')
def test_prompt_producer_supplies_exact_build_metadata(supplied):
    from ravel.workflow import agent_audit
    repo, pack = supplied
    transcript = repo / 'transcript.jsonl'
    transcript.write_text('\n'.join(json.dumps(row) for row in [
        {'type': 'user', 'sessionId': 'ANA-0001', 'timestamp': '2026-01-01T00:00:00Z',
         'message': {'role': 'user', 'content': 'Fictional prompt.'}},
        {'type': 'assistant', 'message': {'id': 'synthetic-message', 'model': 'synthetic-build',
         'usage': {'input_tokens': 1, 'output_tokens': 1}, 'content': []}},
    ]))
    log = repo / 'hook.jsonl'
    log.write_text('')
    write(repo, 'audit.json', agent_audit.build(log, transcripts=[transcript]))
    assert statuses(engine().check(repo, one(pack, 'prompts')))['prompts'] == 'PASS'


def test_size_budget_includes_newly_staged_files(supplied):
    repo, pack = supplied
    write(repo, 'staged-large.bin', 'x' * 16384)
    git(repo, 'add', 'staged-large.bin')
    value = one(pack, 'size')
    value['rules'][0]['params']['max_file_bytes'] = 8192
    assert statuses(engine().check(repo, value))['size'] == 'FAIL'


def test_size_budget_counts_head_blob_even_if_worktree_truncated(supplied):
    repo, pack = supplied
    write(repo, 'committed-large.bin', 'x' * 16384)
    commit(repo)
    write(repo, 'committed-large.bin', 'x')
    value = one(pack, 'size')
    value['rules'][0]['params']['max_file_bytes'] = 8192
    assert statuses(engine().check(repo, value))['size'] == 'FAIL'


def test_missing_mapped_skill_is_a_violation(supplied):
    repo, pack = supplied
    (repo / 'skills/tool.md').unlink()
    assert statuses(engine().check(repo, one(pack, 'skills')))['skills'] == 'FAIL'


def test_empty_declared_workflow_has_no_comparison(supplied):
    repo, pack = supplied
    write(repo, 'workflow.json', {'rules': []})
    assert statuses(engine().check(repo, one(pack, 'compare')))['compare'] == 'FAIL'


def test_vendored_ravel_requires_license_and_notice_declaration(supplied):
    repo, pack = supplied
    wheel = write(repo, 'vendor/distribution.whl', 'fictional distribution bytes')
    write(repo, 'requirements.txt', 'ravel-hep==1.0\nfictional-pkg==1.0\n')
    value = json.loads((repo / 'availability.json').read_text())
    value['distributions'].append({'name': 'ravel-hep', 'version': '1.0', 'public': False,
                                  'vendored': 'vendor/distribution.whl', 'sha256': sha(wheel)})
    write(repo, 'availability.json', value)
    assert statuses(engine().check(repo, one(pack, 'environment')))['environment'] == 'FAIL'


def test_index_mutation_during_check_cannot_leave_a_pass(supplied, monkeypatch):
    repo, pack = supplied
    module = engine()
    original = module.CHECKS['instruction_hash']
    def mutate(context, root, params, result):
        original(context, root, params, result)
        write(repo, 'unrelated.txt', 'Fictional staged update.\n')
        git(repo, 'add', 'unrelated.txt')
    monkeypatch.setitem(module.CHECKS, 'instruction_hash', mutate)
    assert statuses(module.check(repo, one(pack, 'instructions')))['instructions'] == 'FAIL'


def test_native_ledger_attempt_history_cannot_hide_unreceipted_attempt(supplied):
    repo, pack = supplied
    current = {'stage': 'compute', 'attempt_id': 'a1', 'status': 'succeeded',
               'attempt_record': 'logs/execution/compute/a1/record.json'}
    previous = {'stage': 'compute', 'attempt_id': 'a0', 'status': 'failed',
                'attempt_record': 'logs/execution/compute/a0/record.json'}
    write(repo, 'execution_state.json', {'schema_version': 1, 'revision': 2, 'stages': {'compute': current}})
    write(repo, current['attempt_record'], current)
    write(repo, previous['attempt_record'], previous)
    value = one(pack, 'launch')
    value['rules'][0]['params']['stages'] = 'execution_state.json'
    report = engine().check(repo, value)
    assert statuses(report)['launch'] == 'FAIL'
    assert any(e.get('stage') == 'compute' and e.get('attempt') == 'a0' for e in report['rules'][0]['evidence'])


def test_ledger_with_complete_launch_attempts_passes(supplied):
    repo, pack = supplied
    current = {'stage': 'compute', 'attempt_id': 'a1', 'status': 'succeeded',
               'attempt_record': 'logs/execution/compute/a1/record.json'}
    previous = {'stage': 'compute', 'attempt_id': 'a0', 'status': 'failed',
                'attempt_record': 'logs/execution/compute/a0/record.json'}
    write(repo, 'execution_state.json', {'schema_version': 1, 'revision': 2, 'stages': {'compute': current}})
    write(repo, current['attempt_record'], current)
    write(repo, previous['attempt_record'], previous)
    write(repo, 'launches.json', {'receipts': [
        {'stage': 'compute', 'attempt': attempt, 'manager': 'synthetic-manager', 'policy_sha256': 'a' * 64}
        for attempt in ('a0', 'a1')]})
    value = one(pack, 'launch')
    value['rules'][0]['params']['stages'] = 'execution_state.json'
    report = engine().check(repo, value)
    assert statuses(report)['launch'] == 'PASS', report
    assert any(e.get('path', '').endswith('/a0/record.json') for e in report['rules'][0]['evidence'])


def test_report_preserves_policy_parameters_and_canonical_hash(supplied):
    repo, pack = supplied
    value = one(pack, 'size')
    report = engine().check(repo, value)
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    assert report['rule_pack_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert report['rules'][0]['params'] == value['rules'][0]['params']
    rendered = engine().render_markdown(report)
    assert 'max_file_bytes' in rendered and report['rule_pack_sha256'] in rendered


def test_size_budget_measures_links_and_submodules_without_following(supplied, tmp_path):
    repo, pack = supplied
    outside = tmp_path / 'outside.bin'
    outside.write_bytes(b'x' * 16384)
    (repo / 'link.bin').symlink_to(outside)
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{head},fictional-module')
    commit(repo)
    value = one(pack, 'size')
    value['rules'][0]['params']['max_file_bytes'] = 8192
    report = engine().check(repo, value)
    assert statuses(report)['size'] == 'PASS', report


def test_cli_relative_rundir_is_resolved_from_working_directory(supplied, tmp_path, monkeypatch):
    repo, pack = supplied
    rules = one(pack, 'instructions')
    rules['rules'][0]['scope'] = 'runs'
    write(tmp_path, 'run/PROJECT.md', 'Fictional project instructions.\n')
    path = write(tmp_path, 'rules.json', rules)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'report.json'
    assert cli.main(['conformance', 'check', '--repo', str(repo), '--rules', str(path),
                     '--rundir', 'run', '--out', str(out)]) == 0
