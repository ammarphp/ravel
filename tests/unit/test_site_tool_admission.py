"""Inert MCP host calls and real local approval receipts; no site or physics job."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator, ValidationError

from ravel.paths import package_data_path
from ravel.workflow import agent_surface, host_governance, role_registry, site_tools
from ravel.workflow.state_io import read_json
from test_host_governance import _env, _run, _ravel, VALID_CHECKIN1

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    for key in ('CLAUDE_CODE_SESSION_ID', 'RAVEL_SESSION_ID', 'CLAUDECODE', 'CLAUDE_PROJECT_DIR'):
        monkeypatch.delenv(key, raising=False)


def call(name='submit_job', **arguments):
    return {'tool_name': 'mcp__ravel-site-example__' + name, 'tool_input': arguments}


def scope(data):
    return {'schema_version': 1, 'calls': [{'tool_name': data['tool_name'],
            'tool_input_sha256': site_tools.input_digest(data['tool_input']),
            'effects': site_tools.classify(data['tool_name'])['effects']}]}


def approve(tmp_path, data, *, declared=None):
    rd = _run(tmp_path, compute_plan='smoke', task_mode='reproduce')
    ci = deepcopy(VALID_CHECKIN1)
    if declared is not False:
        ci['sections']['site_tools'] = scope(data if declared is None else declared)
    (rd / 'inputs/checkin1.json').write_text(json.dumps(ci))
    (rd / 'inputs/cost_preflight.json').write_text(json.dumps(
        {'schema_version': 1, 'generated_by': 'cost_preflight.py', 'mode': 'smoke', 'walltime_h': [0.5, 1]}))
    result = _ravel(tmp_path, 'approve', '--rundir', rd, '--quote', 'Approve the declared synthetic site-call scope')
    assert result.returncode == 0, result.stdout + result.stderr
    return rd


def hook(script, data, project, tmp_path, **env):
    return subprocess.run(['bash', str(REPO / '.claude/hooks' / script)],
                          input=json.dumps(data), text=True, capture_output=True,
                          cwd=tmp_path, env=_env(tmp_path, CLAUDE_PROJECT_DIR=str(project), **env))


def test_policy_and_schemas_validate_and_effects_win():
    doc = site_tools.policy()
    for name in ('policy', 'scope'):
        Draft202012Validator.check_schema(read_json(package_data_path('site_tools', name + '.schema.json')))
    row = deepcopy(doc['rules'][0]); row.update(classification='effectful', effect='transfer')
    doc['rules'].append(row)
    assert site_tools.classify('mcp__af-uchicago__rucio_list_dids', document=doc)['effects'] == ['transfer']
    doc['default'] = 'read-only'
    with pytest.raises(ValidationError):
        site_tools.classify('mcp__unknown__lookup', document=doc)


@pytest.mark.parametrize('name', ['lookup_dataset', 'query_metadata', 'job_status', 'list_files', 'read_file'])
def test_read_only_passes_and_is_observed_without_a_run(tmp_path, name):
    data = call(name, query='synthetic')
    assert hook('pretooluse-mcp.sh', data, tmp_path, tmp_path).returncode == 0
    assert hook('posttooluse-observer.sh', {**data, 'tool_response': {'result': 'synthetic'}}, tmp_path, tmp_path).returncode == 0
    row = json.loads((tmp_path / 'logs/site-tools.jsonl').read_text())
    assert row['tool_name'] == data['tool_name'] and row['classification'] == 'read-only'
    assert row['current_decision'] == 'allow' and row['approval_sha256'] is None
    assert 'tool_input' not in row and 'tool_response' not in row
    assert 'synthetic' not in json.dumps(row)


@pytest.mark.parametrize('name,effect', [('download_dataset', 'download'), ('transfer_data', 'transfer'),
    ('submit_job', 'job-submit'), ('cancel_job', 'job-cancel'), ('execute_cell', 'notebook-execute'),
    ('write_file', 'file-write'), ('mystery', 'unknown')])
def test_effectful_and_unknown_refuse_without_run(tmp_path, name, effect):
    data = call(name)
    result = site_tools.check(data, project=tmp_path)
    assert result['decision'] == 'deny' and result['effects'] == [effect]
    refused = hook('pretooluse-mcp.sh', data, tmp_path, tmp_path)
    assert refused.returncode == 2 and 'governed route' in refused.stderr


def test_real_approval_covers_exact_call_and_records_approval(tmp_path):
    data = call(dataset='synthetic', jobs=2)
    rd = approve(tmp_path, data)
    data['cwd'] = str(rd)
    result = site_tools.check(data, project=tmp_path)
    assert result['decision'] == 'allow', result['errors']
    assert len(result['approval_sha256']) == 64
    assert hook('pretooluse-mcp.sh', data, tmp_path, tmp_path).returncode == 0
    assert hook('posttooluse-observer.sh', data, tmp_path, tmp_path).returncode == 0
    row = json.loads((rd / 'logs/site-tools.jsonl').read_text())
    assert row['approval_sha256'] == result['approval_sha256'] and row['current_decision'] == 'allow'
    changed = {**data, 'tool_input': {'dataset': 'other', 'jobs': 10}}
    assert site_tools.check(changed, project=tmp_path)['decision'] == 'deny'
    assert site_tools.check(call('cancel_job', dataset='synthetic', jobs=2), project=tmp_path, rundir=rd)['decision'] == 'deny'
    ci = read_json(rd / 'inputs/checkin1.json')
    ci['sections']['site_tools'] = scope(changed)
    (rd / 'inputs/checkin1.json').write_text(json.dumps(ci))
    result = site_tools.check(changed, project=tmp_path)
    assert result['decision'] == 'deny' and any('approval' in e.lower() for e in result['errors'])


def test_approval_without_site_scope_does_not_authorize_effect(tmp_path):
    data = call()
    rd = approve(tmp_path, data, declared=False)
    result = site_tools.check(data, project=tmp_path, rundir=rd)
    assert result['decision'] == 'deny'


def test_unapproved_run_with_scope_refuses(tmp_path):
    data = call()
    rd = _run(tmp_path, compute_plan='smoke')
    ci = deepcopy(VALID_CHECKIN1); ci['sections']['site_tools'] = scope(data)
    (rd / 'inputs/checkin1.json').write_text(json.dumps(ci))
    result = site_tools.check(data, project=tmp_path, rundir=rd)
    assert result['decision'] == 'deny'


def test_unknown_server_never_gets_read_allowlist(tmp_path):
    data = call('lookup_dataset'); data['tool_name'] = 'mcp__unreviewed__lookup_dataset'
    assert site_tools.check(data, project=tmp_path)['effects'] == ['unknown']


def test_unknown_can_only_be_allowed_as_exact_approved_unknown_effect(tmp_path):
    data = call('new_operation', value=1)
    rd = approve(tmp_path, data)
    assert site_tools.check(data, project=tmp_path, rundir=rd)['decision'] == 'allow'


def test_policy_failure_and_missing_interpreter_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(site_tools, 'policy', lambda: (_ for _ in ()).throw(ValueError('invalid policy')))
    with pytest.raises(ValueError):
        site_tools.check(call('lookup_dataset'), project=tmp_path)
    refused = hook('pretooluse-mcp.sh', call('lookup_dataset'), tmp_path, tmp_path, RAVEL_PYTHON='/nonexistent')
    assert refused.returncode == 2 and 'governed route' in refused.stderr


def test_scope_schema_rejects_wildcards_and_checkin_rejects_invalid_scope():
    from ravel.validation.validate_checkin import validate
    ci = deepcopy(VALID_CHECKIN1); ci['sections']['site_tools'] = scope(call())
    ci['sections']['site_tools']['calls'][0]['tool_name'] = 'mcp__*__*'
    with pytest.raises(ValidationError):
        site_tools._validate(ci['sections']['site_tools'], 'scope')
    assert any('site_tools' in e for e in validate(ci))


def test_generated_declarations_and_claude_settings_include_matchers():
    settings = read_json(REPO / '.claude/settings.json')
    assert site_tools.merge_claude_settings(settings) == settings
    for event in ('PreToolUse', 'PostToolUse'):
        assert any(group['matcher'] == 'mcp__.*' for group in settings['hooks'][event])
    for host in role_registry.SURFACES:
        rel = '.ravel/site-tools/' + host + '.json'
        declared = json.loads(role_registry.render(host)[rel])
        assert declared['matcher'] == 'mcp__.*' and declared['default'] == 'effectful'
        assert declared['native_hooks'] is (host == 'claude')
        assert read_json(REPO / rel) == declared
    merged = agent_surface._merge_hooks({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': []}]}}, 'audit')
    assert merged['hooks']['PreToolUse'][0]['matcher'] == 'Bash'
    for event, action in [('PreToolUse', 'check'), ('PostToolUse', 'observe')]:
        assert any(group['matcher'] == 'mcp__.*' and f'site_tools {action}' in group['hooks'][0]['command']
                   for group in merged['hooks'][event])


def test_enforcement_surface_covers_policy_and_schema():
    files = host_governance.surface_files(REPO)
    for name in ('policy.json', 'policy.schema.json', 'scope.schema.json'):
        assert 'ravel/data/site_tools/' + name in files
    assert '.claude/hooks/pretooluse-mcp.sh' in files
    assert '.ravel/site-tools/codex.json' in files


def test_non_mcp_arguments_do_not_get_mcp_observation(tmp_path):
    data = {'tool_name': 'Bash', 'tool_input': {'command': 'echo mcp__example__lookup'}}
    assert hook('posttooluse-observer.sh', data, tmp_path, tmp_path).returncode == 0
    assert not (tmp_path / 'logs/site-tools.jsonl').exists()
    assert not (tmp_path / 'logs/hook-failures.log').exists()


def test_science_approval_uses_the_same_scope_and_verifier(tmp_path):
    from ravel.workflow import science
    from test_science_review_envelope import specification
    from method_decision_fixture import admit_method
    rd, spec = tmp_path / 'run', tmp_path / 'spec.json'
    spec.write_text(json.dumps(specification(tmp_path)))
    science.plan(rd, spec); admit_method(rd)
    data = call('download_dataset', dataset='synthetic')
    (rd / site_tools.SCOPE_PATH).write_text(json.dumps(scope(data)))
    site_tools.refresh_checkin(rd)
    science.approve(rd, 'Approve the declared synthetic scope', scripted=True)
    result = site_tools.check(data, project=tmp_path, rundir=rd)
    assert result['decision'] == 'allow', result['errors']


def test_scope_file_is_a_registered_section_and_approval_input(tmp_path):
    from ravel.workflow import workflow_state
    data = call()
    rd = _run(tmp_path)
    (rd / site_tools.SCOPE_PATH).write_text(json.dumps(scope(data)))
    assert site_tools.checkin_section({'rundir': rd}) == scope(data)
    assert str(rd / site_tools.SCOPE_PATH) in workflow_state.approval_input_paths(rd)
    assert site_tools.checkin_section({'rundir': tmp_path / 'other'}) is None


@pytest.mark.parametrize('raw', ['{"tool_name":"mcp__ravel-site-example__lookup_dataset","tool_input":{"x":1,"x":2}}',
                                '{"tool_name":"mcp__ravel-site-example__lookup_dataset","tool_input":{"x":NaN}}'])
def test_invalid_host_json_fails_closed(tmp_path, raw):
    result = subprocess.run([sys.executable, '-m', 'ravel.workflow.site_tools', 'check', '--project', str(tmp_path)],
                            input=raw, text=True, capture_output=True, env=_env(tmp_path))
    assert result.returncode == 2 and 'governed route' in result.stderr


def test_failed_observation_reports_without_content(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'ravel.workflow.site_tools', 'observe', '--project', str(tmp_path)],
                            input='{"tool_name":"invalid","tool_input":{"content":"synthetic-private-value"}}',
                            text=True, capture_output=True, env=_env(tmp_path))
    assert result.returncode == 2
    assert 'synthetic-private-value' not in result.stderr
    assert (tmp_path / 'logs/hook-failures.log').read_text() == 'site-tool observation unavailable\n'


def test_condor_submit_validation_only_arguments_are_read_only(tmp_path):
    data = call('condor_submit', arguments=['-dry-run', '/dev/null', 'kept/job.sub'])
    result = site_tools.check(data, project=tmp_path)
    assert result['decision'] == 'allow' and result['classification'] == 'read-only'
    assert site_tools.classify(data['tool_name'])['classification'] == 'effectful'
    for arguments in ([], ['job.sub'], ['-terse', 'job.sub'], ['-dry-run', 'out', 'job.sub'],
                      ['-dry-run', '/dev/null', 'job.sub', '-queue', '2'],
                      ['-dry-run', '/dev/null', 'x=y'], '-dry-run /dev/null job.sub'):
        assert site_tools.check(call('condor_submit', arguments=arguments), project=tmp_path)['decision'] == 'deny'
    assert site_tools.check({**data, 'tool_input': {**data['tool_input'], 'submit': True}}, project=tmp_path)['decision'] == 'deny'
    assert site_tools.check({**data, 'tool_name': 'mcp__unknown__condor_submit'}, project=tmp_path)['decision'] == 'deny'
    doc = site_tools.policy()
    doc['rules'].append({'server': 'ravel-site-example', 'tool': 'condor_submit', 'classification': 'effectful',
                         'effect': 'file-write', 'source': 'synthetic', 'note': 'additional effect'})
    assert site_tools.classify(data['tool_name'], document=doc, tool_input=data['tool_input'])['classification'] == 'effectful'
