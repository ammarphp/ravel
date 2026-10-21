"""Inert login controls exercise metadata admission and retained worker diagnostics."""
import json
import os
from pathlib import Path
import shutil

import pytest

from ravel.workflow import agent_worker as worker, sandbox, transport_registry as tr
from ravel.workflow.transports import cli_worker
from test_cli_worker_adapter import FAKE_CLAUDE, cli, install, probe, ready, real_sandbox_or_skip, spec
from test_setup_doctor import make_doctor


def test_expired_auth_refuses_before_worker_prompt_and_preserves_owner_files(cli):
    ready(cli)
    (cli / 'bin/mode.txt').write_text('auth_expired')
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused, match='OAuth session expired') as failure:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert 'CLAUDE_CONFIG_DIR=' + str(cli / 'claude-login') + ' claude' in str(failure.value)
    assert '/login' in str(failure.value)
    assert not (ws / 'scratch/seen.json').exists()
    assert (sandbox.cli_home_for(ws) / 'claude/.credentials.json').is_file()


def test_login_preflight_uses_the_dedicated_login_without_ambient_api_credentials(cli, monkeypatch):
    body = FAKE_CLAUDE.replace("if args == ['auth', 'status', '--json']:",
        "if args == ['auth', 'status', '--json']:\n"
        "    assert 'ANTHROPIC_API_KEY' not in os.environ\n"
        "    assert 'CLAUDE_CODE_OAUTH_TOKEN' not in os.environ\n"
        "    assert 'CLAUDE_CODE_USE_BEDROCK' not in os.environ\n"
        "    assert 'RAVEL_WMS_CAPABILITY' not in os.environ")
    ready(cli, body=body)
    for name in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN', 'CLAUDE_CODE_USE_BEDROCK',
                 'RAVEL_WMS_CAPABILITY'):
        monkeypatch.setenv(name, 'ambient-sentinel')
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    descriptor = cli_worker.prepare_launch(cli / 'run', s, ws)
    assert descriptor['transport']['login_preflight']['status'] == 'authenticated'
    cli_worker.remove_home(ws, descriptor)


def test_nonzero_worker_retains_redacted_error_tail_and_login_remedy(cli):
    ready(cli)
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    descriptor = cli_worker.prepare_launch(cli / 'run', s, ws)
    stderr = worker.capture_path(cli / 'run', s['node_id'], s['attempt'], 'stderr')
    stderr.parent.mkdir(parents=True, exist_ok=True)
    stderr.write_text('discarded\n' * 40 + 'OAuth session expired and could not be refreshed\n'
                      'accessToken=private-token\n')
    result = cli_worker.observe(cli / 'run', descriptor, ws, s, {'exit_status': 1})
    cli_worker.remove_home(ws, descriptor)
    diagnostics = result['transport']['observation']['failure_diagnostic']
    assert 'OAuth session expired' in diagnostics['stderr_tail']
    assert 'private-token' not in json.dumps(diagnostics)
    assert len(diagnostics['stderr_tail'].splitlines()) <= 20
    assert 'CLAUDE_CONFIG_DIR=' + str(cli / 'claude-login') + ' claude' in diagnostics['remedy']
    assert '/login' in diagnostics['remedy']


def test_qualification_cli_prints_worker_error_and_remedy(monkeypatch, capsys, tmp_path):
    diagnostic = {'stderr_tail': 'OAuth session expired', 'remedy': 'Use the login command, then /login.'}
    receipt = {'status': 'failed', 'transport': {'observation': {'failure_diagnostic': diagnostic}}}
    def fail(*args, **kwargs):
        raise cli_worker.QualificationFailed('qualification failed', ['receipt_ok'], receipt)
    monkeypatch.setattr(cli_worker, 'qualify', fail)
    assert cli_worker.main(['claude-cli-worker', '--rundir', str(tmp_path), '--model', 'fixture']) == 4
    printed = json.loads(capsys.readouterr().out)
    assert printed['failure_diagnostic'] == diagnostic


@pytest.mark.parametrize('state', ['authenticated', 'expired', 'missing', 'os-store-only'])
def test_doctor_observes_file_metadata_and_cli_status(cli, monkeypatch, state):
    from ravel.controller.step import seats
    ready(cli)
    if state in ('missing', 'os-store-only'):
        (cli / 'claude-login/.credentials.json').unlink()
    if state == 'expired':
        (cli / 'bin/mode.txt').write_text('auth_expired')
    monkeypatch.setattr(seats, 'wired_transports', lambda: {'wired': ['claude-cli-worker']})
    monkeypatch.setattr(tr, 'qualification_status', lambda *a: 'live_qualified')
    monkeypatch.setattr(tr, 'read_qualification', lambda *a: {'observed': {
        'model': 'claude-fixture-model', 'requested_model': 'claude-fixture-model'}})
    monkeypatch.setattr(tr, '_store_qualification_valid', lambda *a: True)
    doctor = make_doctor(cli, environ=dict(os.environ), which=shutil.which)
    result = doctor._agent_cli_check({})
    if state == 'authenticated':
        assert result['status'] == 'ready' and result['authentication']['status'] == 'authenticated'
    else:
        assert result['authentication'] == 'login_required'
        assert 'CLAUDE_CONFIG_DIR=' + str(cli / 'claude-login') + ' claude' in result['fix']
        assert '/login' in result['fix'] and 'your own setup step' in result['fix']


@pytest.mark.parametrize('state', ['missing', 'os-store-only'])
def test_worker_requires_an_owner_provided_file_before_any_prompt(cli, monkeypatch, state):
    ready(cli)
    (cli / 'claude-login/.credentials.json').unlink()
    # The inert CLI still reports authenticated; a store-only login supplies no worker file.
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as failure:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert failure.value.missing == ['worker_login_file_required']
    assert 'your own setup step' in str(failure.value) and '/login' in str(failure.value)
    assert not (ws / 'scratch/seen.json').exists()


def test_error_tail_redacts_json_tokens_and_retains_error_text():
    from ravel.workflow.transports.cli_login import safe_error
    error = '{"accessToken":"private-access", "refreshToken": "private-refresh", "error":"login expired"}'
    text = safe_error(error)
    assert 'private-access' not in text and 'private-refresh' not in text
    assert 'login expired' in text


def test_error_tail_redacts_provider_credential_fields_and_quoted_bearer_values():
    from ravel.workflow.transports.cli_login import safe_error
    values = {'AWS_SECRET_ACCESS_KEY': 'credential-value', 'clientSecret': 'client-value',
              'idToken': 'identity-value', 'authorization': 'Bearer bearer-value',
              'error': 'login expired'}
    text = safe_error(json.dumps(values))
    assert all(value not in text for key, value in values.items() if key != 'error')
    assert 'login expired' in text


def test_qualify_retains_real_child_auth_failure_after_private_home_cleanup(cli, capsys):
    real_sandbox_or_skip(cli)
    body = FAKE_CLAUDE.replace('prompt = sys.stdin.read()',
        "sys.stderr.write('OAuth session expired and could not be refreshed\\n'); sys.exit(1)")
    probe('claude-cli-worker', install(cli, 'claude', body))
    result = cli_worker.main(['claude-cli-worker', '--rundir', str(cli / 'qualification'),
                              '--model', 'claude-fixture-model'])
    assert result == 4
    printed = json.loads(capsys.readouterr().out)
    assert 'OAuth session expired' in printed['failure_diagnostic']['stderr_tail']
    assert '/login' in printed['failure_diagnostic']['remedy']
    receipts = list((cli / 'qualification/agent-work').rglob('receipt.json'))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text())
    assert receipt['transport']['observation']['failure_diagnostic'] == printed['failure_diagnostic']
    assert receipt['transport']['login_preflight']['status'] == 'authenticated'
    assert Path(receipt['transport']['cli_home']).is_dir()
    assert (Path(receipt['transport']['cli_home']) / 'claude/.credentials.json').is_file()
    assert not tr.qualification_path('claude-cli-worker').exists()


def test_preflight_observes_metadata_without_opening_login_files(cli, monkeypatch):
    from ravel.workflow.transports.cli_login import preflight
    def byte_access(*args, **kwargs):
        pytest.fail('login admission requires filesystem metadata only')
    with monkeypatch.context() as no_bytes:
        for name in ('read_text', 'read_bytes', 'write_text', 'write_bytes', 'open'):
            no_bytes.setattr(Path, name, byte_access)
        no_bytes.setattr('builtins.open', byte_access)
        no_bytes.setattr(os, 'open', byte_access)
        result = preflight('/inert/claude', cli / 'claude-login',
                           run_probe=lambda *a, **k: (0, '{"loggedIn":true,"authMethod":"claude.ai"}'))
    assert result['status'] == 'authenticated'


def test_unset_login_directory_gives_the_owner_renewal_remedy(cli, monkeypatch):
    ready(cli)
    monkeypatch.delenv('CLAUDE_CONFIG_DIR')
    s = spec(cli)
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        cli_worker.prepare_launch(cli / 'run', s, ws)
    assert failed.value.missing == ['CLAUDE_CONFIG_DIR']
    assert 'CLAUDE_CONFIG_DIR=LOGIN_DIRECTORY claude, then /login' in str(failed.value)
    assert 'your own setup step' in str(failed.value)
    assert not (ws / 'scratch/seen.json').exists()
