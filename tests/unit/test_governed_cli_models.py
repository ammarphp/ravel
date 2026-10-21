"""Governed CLI composition with inert executables and the real sandbox/MCP path."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from ravel.controller.step import seats
from ravel.workflow import agent_worker as worker, broker, sandbox, transport_registry as tr
from ravel.workflow.transports import cli_worker
from test_cli_worker_adapter import (FAKE_CLAUDE, cli, install, preferences, probe,
                                     qualification_record, real_sandbox_or_skip, spec)


CLAUDE = FAKE_CLAUDE.replace("'input_tokens': 100, 'output_tokens': 20",
                            "'input_tokens': 100, 'cache_creation_input_tokens': 3, "
                            "'cache_read_input_tokens': 5, 'output_tokens': 20")
CODEX = FAKE_CLAUDE.split('print(json.dumps(')[0].replace(
    "entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']",
    """config_text = (Path(os.environ['CODEX_HOME']) / 'config.toml').read_text()
entry = {{}}
for line in config_text.split('[mcp_servers.ravel]')[1].splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        entry[key.strip()] = json.loads(value.strip())
Path('scratch/codex-config.txt').write_text(config_text)
Path('scratch/codex-home.txt').write_text(os.environ['CODEX_HOME'])""") + '''
session = (here / 'session.txt').read_text().strip()
rollout = json.dumps({{'type': 'turn_context', 'payload': {{'model': 'gpt-served-fixture'}}}}) + '\\n'
sessions = Path(os.environ['CODEX_HOME']) / 'sessions'
sessions.mkdir(exist_ok=True)
(sessions / ('rollout-fixture-' + session + '.jsonl')).write_text(rollout)
Path('scratch/codex-rollout.jsonl').write_text(rollout)
for event in [{{'type': 'thread.started', 'thread_id': session}}, {{'type': 'turn.started'}},
              {{'type': 'item.completed', 'item': {{'type': 'agent_message', 'text': json.dumps(
                  {{'completed': True, 'summary': 'conformance written'}})}}}},
              {{'type': 'turn.completed', 'usage': {{'input_tokens': 100, 'cached_input_tokens': 5,
                                                   'output_tokens': 20}}}}]:
    print(json.dumps(event))
'''


# The hostile qualification mode names a native tool explicitly.
CLAUDE = CLAUDE.replace('synced-skill-example', 'Bash')
CODEX = CODEX.replace('synced-skill-example', 'Bash')

@pytest.fixture
def gemini_subscription(cli, monkeypatch):
    """A test-only login declaration; the shipped API declaration remains untouched."""
    document = deepcopy(tr.load('gemini-cli-worker'))
    document.update(id='fixture-gemini-subscription', billing='subscription')
    document['auth'].update(kind='login', env_names=[])
    document['pass_env'] = []
    routes = cli / 'routes'
    routes.mkdir()
    (routes / (document['id'] + '.json')).write_text(json.dumps(document))
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(routes))
    return document


def prepared(cli, monkeypatch, agent, *, document=None):
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    tid = document['id'] if document else agent + '-cli-worker'
    record = probe(tid, install(cli, agent, CODEX if agent == 'codex' else CLAUDE))
    qualification_record(tid, record)
    preferences(cli, tid, model='requested-fixture')
    s = spec(cli, transport=tid)
    ws = worker.materialize(cli / 'run', s)
    selected = {'transport_id': tid, 'model': 'requested-fixture', 'effort': None,
                'probe_sha256': tr.digest(record)}
    d = cli_worker.prepare_launch(cli / 'run', s, ws, selection=selected)
    return s, ws, d


@pytest.mark.parametrize('agent', ['claude', 'codex', 'gemini'])
def test_seat_admission_requires_restricted_template_and_surface(agent, gemini_subscription):
    document = deepcopy(gemini_subscription if agent == 'gemini' else tr.load(agent + '-cli-worker'))
    assert seats.admission_problem(document) is None
    missing = deepcopy(document)
    flag = seats.LAUNCHER_RESTRICTIONS[agent]['flags'][0]
    missing['argv_template'].remove(flag)
    assert seats.admission_problem(missing) == 'unrestricted:' + flag
    wrong = deepcopy(document)
    wrong['worker_surface']['mcp']['config'] = 'probe_required'
    assert seats.admission_problem(wrong) == 'unrestricted:worker_surface.mcp'
    document['transport_kind'] = 'cli-oneshot'
    assert seats.admission_problem(document) == 'transport_kind:cli-oneshot'


def assert_codex_restrictions(text):
    for setting in ('web_search = "disabled"', '[features]', 'shell_tool = false',
                    'apply_patch_freeform = false', 'collab = false', 'apps = false',
                    '[tools]', 'view_image = false', '[mcp_servers.ravel]'):
        assert setting in text


def test_codex_generated_configuration_disables_native_surfaces(cli, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-ambient-fixture-key')
    source = cli / 'home/.codex'
    source.mkdir()
    (source / 'auth.json').write_text('{"synthetic": true}')
    (source / 'AGENTS.md').write_text('hostile user instructions')
    _, ws, d = prepared(cli, monkeypatch, 'codex')
    home = Path(d['transport']['launch_env']['CODEX_HOME'])
    assert home != source and sorted(p.name for p in home.iterdir()) == ['auth.json', 'config.toml']
    config = home / 'config.toml'
    assert_codex_restrictions(config.read_text())
    assert config.stat().st_mode & 0o777 == 0o400
    assert d['argv'][d['argv'].index('--sandbox') + 1] == 'read-only'
    assert d['argv'][d['argv'].index('--output-schema') + 1] == str(ws / 'inputs/final-schema.json')
    assert d['transport']['user_configuration_declared_loaded'] is False
    assert 'OPENAI_API_KEY' not in d['transport']['launch_env'] and 'OPENAI_API_KEY' not in d['pass_env_names']


def _assert_private_subscription_refusal(root, failed, agent, secret):
    assert failed.value.missing == ['subscription_auth:' + agent]
    assert 'subscription login' in str(failed.value) and 'budgeted HTTP' in str(failed.value)
    assert secret not in str(failed.value) and failed.value.__context__ is None
    ws = worker.workspace(root / 'run', 'cli.worker', 1)
    home = sandbox.cli_home_for(ws)
    if agent == 'codex' and home.exists():
        assert (home / 'codex/auth.json').is_file()
        assert not (home / 'codex/config.toml').exists()
    else:
        assert not home.exists()


@pytest.mark.parametrize('api_auth', [
    {'OPENAI_API_KEY': 'private-codex-fixture-key'},
    {'auth_mode': 'apikey', 'tokens': {'access_token': 'private-codex-fixture-key'}},
    {'auth_mode': 'api_key', 'tokens': {'access_token': 'private-codex-fixture-key'}},
    {'auth_mode': 'api-key', 'tokens': {'access_token': 'private-codex-fixture-key'}},
])
def test_codex_subscription_refuses_api_login_status_before_mcp(cli, monkeypatch, capsys, api_auth):
    from ravel.workflow import broker_mcp
    source = cli / 'home/.codex'
    source.mkdir()
    original = source / 'auth.json'
    original.write_text(json.dumps(api_auth))
    before = original.read_bytes()
    read_text = Path.read_text
    def private_read(path, *args, **kwargs):
        if path == original:
            pytest.fail('subscription validation uses CLI status and file metadata')
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', private_read)
    monkeypatch.setattr(broker_mcp, 'client_config', lambda *a, **k: pytest.fail('auth refusal must precede MCP writing'))
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        prepared(cli, monkeypatch, 'codex')
    _assert_private_subscription_refusal(cli, failed, 'codex', 'private-codex-fixture-key')
    assert original.read_bytes() == before
    output = capsys.readouterr()
    assert 'private-codex-fixture-key' not in output.out + output.err


@pytest.mark.parametrize('damage', ['malformed', 'not-object', 'unreadable'])
def test_codex_subscription_login_errors_are_sanitized_and_preserved(cli, monkeypatch, damage):
    source = cli / 'home/.codex'
    source.mkdir()
    original = source / 'auth.json'
    secret = 'private-invalid-auth-fixture'
    original.write_text('[' + secret if damage == 'malformed' else json.dumps([secret])
                        if damage == 'not-object' else json.dumps({'synthetic': secret}))
    before = original.read_bytes()
    read_text = Path.read_text
    def private_read(path, *args, **kwargs):
        if path == original:
            pytest.fail('subscription validation uses CLI status and file metadata')
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', private_read)
    if damage == 'unreadable':
        original.chmod(0)
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        prepared(cli, monkeypatch, 'codex')
    _assert_private_subscription_refusal(cli, failed, 'codex', secret)
    original.chmod(0o600)
    assert original.read_bytes() == before


def test_gemini_subscription_settings_exclude_native_tools_and_user_context(cli, monkeypatch, gemini_subscription):
    monkeypatch.setenv('GEMINI_API_KEY', 'unrelated-ambient-fixture-key')
    monkeypatch.setenv('GOOGLE_API_KEY', 'unrelated-ambient-fixture-key')
    original = cli / 'home/.gemini'
    original.mkdir()
    (original / 'settings.json').write_text(json.dumps({'security': {'auth': {'selectedType': 'oauth-personal'}},
                                                       'mcpServers': {'hostile': {}}, 'context': {'fileName': ['GEMINI.md']}}))
    (original / 'GEMINI.md').write_text('hostile user instructions')
    (original / 'oauth_creds.json').write_text('{"fixture": "opaque-login"}')
    (original / 'google_accounts.json').write_text('{"fixture": "opaque-account"}')
    adc = cli / 'home/.config/gcloud/application_default_credentials.json'
    adc.parent.mkdir(parents=True)
    adc.write_text('{"fixture": "opaque-vertex-credential"}')
    before = (original / 'settings.json').read_bytes()
    cli_home = cli_worker._cli_home
    def owner_home(*args, **kwargs):
        configured = cli_home(*args, **kwargs)
        assert not (configured[-1] / '.config/gcloud/application_default_credentials.json').exists()
        return configured
    monkeypatch.setattr(cli_worker, '_cli_home', owner_home)
    _, _, d = prepared(cli, monkeypatch, 'gemini', document=gemini_subscription)
    from ravel.workflow.provider_policy import account_class
    assert account_class(tr.load(gemini_subscription['id'])) == 'login:subscription'
    home = Path(d['transport']['launch_env']['HOME'])
    settings = json.loads((home / '.gemini/settings.json').read_text())
    assert settings['security']['auth']['selectedType'] == 'oauth-personal'
    assert settings['tools']['core'] == []
    assert set(settings['tools']['exclude']) >= {'run_shell_command', 'read_file', 'write_file', 'replace',
                                                'web_fetch', 'google_web_search', 'activate_skill', 'save_memory'}
    assert settings['context']['fileName'] == [] and list(settings['mcpServers']) == ['ravel']
    assert not (home / '.gemini/GEMINI.md').exists()
    assert not (home / '.config/gcloud/application_default_credentials.json').exists()
    assert adc.read_text() == '{"fixture": "opaque-vertex-credential"}'
    assert (original / 'settings.json').read_bytes() == before
    for credential in ('oauth_creds.json', 'google_accounts.json'):
        assert not (home / '.gemini' / credential).exists()
        assert (original / credential).is_file()
    assert settings['model']['maxSessionTurns'] == 8
    assert d['transport']['user_configuration_declared_loaded'] is False
    assert not {'GEMINI_API_KEY', 'GOOGLE_API_KEY'}.intersection(d['transport']['launch_env'])
    assert not {'GEMINI_API_KEY', 'GOOGLE_API_KEY'}.intersection(d['pass_env_names'])


@pytest.mark.parametrize('layout', ['security', 'legacy'])
@pytest.mark.parametrize('mode', ['vertex-ai', 'gemini-api-key'])
def test_gemini_subscription_refuses_explicit_api_mode_before_mcp(
        cli, monkeypatch, gemini_subscription, capsys, layout, mode):
    from ravel.workflow import broker_mcp
    original = cli / 'home/.gemini/settings.json'
    original.parent.mkdir()
    settings = {'security': {'auth': {'selectedType': mode}}} if layout == 'security' else {'selectedAuthType': mode}
    original.write_text(json.dumps(settings))
    before = original.read_bytes()
    monkeypatch.setattr(broker_mcp, 'client_config', lambda *a, **k: pytest.fail('auth refusal must precede MCP writing'))
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        prepared(cli, monkeypatch, 'gemini', document=gemini_subscription)
    _assert_private_subscription_refusal(cli, failed, 'gemini', mode)
    assert original.read_bytes() == before
    output = capsys.readouterr()
    assert mode not in output.out + output.err


def test_gemini_missing_auth_mode_is_forced_to_oauth_in_generated_settings(cli, monkeypatch, gemini_subscription):
    _, _, descriptor = prepared(cli, monkeypatch, 'gemini', document=gemini_subscription)
    home = Path(descriptor['transport']['launch_env']['HOME'])
    settings = json.loads((home / '.gemini/settings.json').read_text())
    assert settings['security']['auth']['selectedType'] == 'oauth-personal'
    assert settings['context']['fileName'] == []
    assert settings['tools']['core'] == [] and 'run_shell_command' in settings['tools']['exclude']


@pytest.mark.parametrize(('agent', 'selector'), [
    ('codex', 'OPENAI_API_KEY'), ('codex', 'AZURE_OPENAI_API_KEY'),
    ('gemini', 'GEMINI_API_KEY'), ('gemini', 'GOOGLE_API_KEY'),
    ('gemini', 'GOOGLE_APPLICATION_CREDENTIALS'), ('gemini', 'GEMINI_USE_VERTEXAI'),
])
def test_subscription_refuses_generated_api_credential_selectors(cli, monkeypatch, gemini_subscription, agent, selector):
    cli_home = cli_worker._cli_home
    secret = 'private-generated-api-selector'
    def redirected_home(*args, **kwargs):
        copied = cli_home(*args, **kwargs)
        copied[2][selector] = secret
        return copied
    monkeypatch.setattr(cli_worker, '_cli_home', redirected_home)
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        prepared(cli, monkeypatch, agent, document=gemini_subscription if agent == 'gemini' else None)
    _assert_private_subscription_refusal(cli, failed, agent, secret)


@pytest.mark.parametrize(('agent', 'selector'), [('codex', 'OPENAI_API_KEY'), ('gemini', 'GEMINI_USE_VERTEXAI'),
                                               ('gemini', 'GOOGLE_APPLICATION_CREDENTIALS')])
def test_subscription_refuses_declared_scalar_or_relocated_api_passthrough(
        cli, monkeypatch, gemini_subscription, agent, selector):
    document = deepcopy(gemini_subscription if agent == 'gemini' else tr.load('codex-cli-worker'))
    document['id'] = 'fixture-' + agent + '-subscription-passthrough'
    document['pass_env'] = [selector]
    routes = cli / 'routes'
    routes.mkdir(exist_ok=True)
    (routes / (document['id'] + '.json')).write_text(json.dumps(document))
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(routes))
    secret = 'private-declared-api-selector'
    credential = cli / 'api-credential.json'
    credential.write_text(json.dumps({'fixture': secret}))
    monkeypatch.setenv(selector, str(credential) if selector == 'GOOGLE_APPLICATION_CREDENTIALS' else secret)
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        prepared(cli, monkeypatch, agent, document=document)
    _assert_private_subscription_refusal(cli, failed, agent, secret)
    assert credential.read_text() == json.dumps({'fixture': secret})


def test_api_billed_gemini_cli_still_refuses_unenforceable_cost(cli, monkeypatch):
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    document = tr.load('gemini-cli-worker')
    assert document['billing'] == 'api'
    s = spec(cli, transport=document['id'], cost=1.0)
    ws = worker.materialize(cli / 'run', s)
    with pytest.raises(cli_worker.LaunchRefused) as failed:
        cli_worker.prepare_launch(cli / 'run', s, ws, selection={
            'transport_id': document['id'], 'model': 'gemini-requested-fixture', 'effort': None})
    assert failed.value.missing == ['cost_unenforceable:' + document['id']]


def result(agent, with_model):
    final = {'completed': True, 'summary': 'done'}
    if agent == 'claude':
        return json.dumps({'type': 'result', 'session_id': 'observed-session', 'num_turns': 1,
            'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 2, 'cache_read_input_tokens': 3, 'output_tokens': 4},
            'modelUsage': {'served-fixture': {'outputTokens': 4}} if with_model else {}, 'structured_output': final})
    if agent == 'gemini':
        return json.dumps({'session_id': 'observed-session', 'response': json.dumps(final),
                           'model': 'served-fixture' if with_model else None,
                           'stats': {'models': {'served-fixture': {'api': {'totalRequests': 1},
                                'tokens': {'prompt': 15, 'cached': 3, 'candidates': 3, 'thoughts': 1}}}}} if with_model else
                          {'session_id': 'observed-session', 'response': json.dumps(final)})
    return '\n'.join(json.dumps(e) for e in [
        {'type': 'thread.started', 'thread_id': 'observed-session'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(final)}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 15, 'cached_input_tokens': 3, 'output_tokens': 4}}])


@pytest.mark.parametrize('agent', ['claude', 'codex', 'gemini'])
@pytest.mark.parametrize('with_model', [False, True])
def test_observed_identity_has_no_requested_model_fallback(cli, monkeypatch, gemini_subscription, agent, with_model):
    s, ws, d = prepared(cli, monkeypatch, agent, document=gemini_subscription if agent == 'gemini' else None)
    raw = result(agent, with_model)
    worker.capture_path(cli / 'run', s['node_id'], s['attempt'], 'stdout').write_text(raw)
    if agent == 'codex' and not with_model:
        foreign = cli / 'home/.codex/sessions'
        foreign.mkdir(parents=True)
        (foreign / 'rollout-foreign-observed-session.jsonl').write_text(json.dumps(
            {'type': 'turn_context', 'payload': {'model': 'foreign-model-must-not-count'}}))
    if agent == 'codex' and with_model:
        home = Path(d['transport']['launch_env']['CODEX_HOME'])
        (home / 'sessions').mkdir()
        (home / 'sessions/rollout-fixture-observed-session.jsonl').write_text(json.dumps(
            {'type': 'turn_context', 'payload': {'model': 'served-fixture'}}))
    observed = cli_worker.observe(cli / 'run', d, ws, s, {'exit_status': 0, 'isolation': {
        'profile': 'ravel-sandbox', 'user_configuration_loaded': False, 'evidence': {'confirmed': True}}})
    assert observed['model']['requested'] == 'requested-fixture'
    assert observed['model']['observed'] == ('served-fixture' if with_model else None)
    if agent != 'gemini' or with_model:
        usage = observed['transport']['observation']['provider_usage']
        assert usage['status'] == 'reported'
        assert sum(usage['usage'].values()) == 19
        assert observed['usage']['turns'] == 1 and observed['usage']['input_tokens'] == 15
        assert usage['usage']['cache_creation_input_tokens'] == (2 if agent == 'claude' else 0)
        assert usage['split_basis']


@pytest.mark.parametrize('agent,body,served', [('claude', CLAUDE, 'claude-fixture-model'),
                                             ('codex', CODEX, 'gpt-served-fixture')], ids=['claude', 'codex'])
def test_full_sandboxed_cli_launch_uses_broker_mcp_and_provider_metadata(cli, agent, body, served):
    real_sandbox_or_skip(cli)
    tid = agent + '-cli-worker'
    record = probe(tid, install(cli, agent, body))
    qualification_record(tid, record)
    preferences(cli, tid, model='requested-fixture')
    prefs = cli / 'run/inputs/agent_preferences.json'
    value = json.loads(prefs.read_text())
    value['model_families'] = {'requested-fixture': 'anthropic' if agent == 'claude' else 'openai'}
    prefs.write_text(json.dumps(value))
    s = spec(cli, transport=tid)
    receipt = worker.launch(cli / 'run', s)
    assert receipt['status'] == 'ok', receipt['failure']
    ws = worker.workspace(cli / 'run', s['node_id'], s['attempt'])
    assert (ws / 'outputs/conformance.txt').read_text() == 'n-0123456789'
    assert receipt['model']['requested'] == 'requested-fixture' and receipt['model']['observed'] == served
    usage = receipt['transport']['observation']['provider_usage']
    assert usage['status'] == 'reported' and usage['usage']['cache_read_input_tokens'] == 5
    assert usage['split_basis'] and usage['requests'] == (3 if agent == 'claude' else 1)
    assert receipt['attestation'] == 'transport_attested'
    calls = [r['record'] for r in broker.ledger(cli / 'run', 'broker')]
    assert len(calls) == 2
    if agent == 'codex':
        assert_codex_restrictions((ws / 'scratch/codex-config.txt').read_text())
        assert receipt['transport']['model_rollout_sha256'] == broker.sha(ws / 'scratch/codex-rollout.jsonl')
        assert str(cli / 'home/.codex') != (ws / 'scratch/codex-home.txt').read_text()


@pytest.mark.parametrize('agent,body', [('claude', CLAUDE), ('codex', CODEX)], ids=['claude', 'codex'])
@pytest.mark.parametrize('leak', [False, True])
def test_qualification_path_admits_broker_surface_and_rejects_native_leak(cli, agent, body, leak):
    real_sandbox_or_skip(cli)
    tid = agent + '-cli-worker'
    probe(tid, install(cli, agent, body))
    if leak:
        (cli / 'bin/mode.txt').write_text('skills_leak')
        with pytest.raises(cli_worker.QualificationFailed) as failed:
            cli_worker.qualify(tid, rundir=cli / 'qualification', model='requested-fixture')
        assert failed.value.failed == ['surface_ravel_only']
        assert not tr.qualification_path(tid).exists()
    else:
        record = cli_worker.qualify(tid, rundir=cli / 'qualification', model='requested-fixture')
        assert record['status'] == 'live_qualified' and all(step['passed'] for step in record['steps'])
        assert record['observed']['surface']['unexpected'] == []
        assert record['observed']['model'] != record['observed']['requested_model']


GEMINI = CLAUDE.split('print(json.dumps(')[0].replace(
    "entry = json.loads(Path(args[args.index('--mcp-config') + 1]).read_text())['mcpServers']['ravel']",
    """settings_text = (Path(os.environ['HOME']) / '.gemini/settings.json').read_text()
entry = json.loads(settings_text)['mcpServers']['ravel']
Path('scratch/gemini-settings.json').write_text(settings_text)""") + '''
print(json.dumps({{'session_id': (here / 'session.txt').read_text().strip(),
    'response': json.dumps({{'completed': True, 'summary': 'conformance written'}}),
    'stats': {{'models': {{'gemini-served-fixture': {{'api': {{'totalRequests': 3}},
        'tokens': {{'prompt': 100, 'cached': 5, 'candidates': 18, 'thoughts': 2, 'total': 120}}}}}},
        'tools': {{'totalCalls': 2}}}}}}))
'''


@pytest.mark.parametrize('leak', [False, True], ids=['broker-only', 'native-leak'])
def test_gemini_subscription_real_qualifier_uses_broker_and_instruction_custody(cli, gemini_subscription, leak):
    real_sandbox_or_skip(cli)
    tid = gemini_subscription['id']
    probe(tid, install(cli, 'gemini', GEMINI))
    instruction = cli / 'project-instructions.md'
    instruction.write_text('Use the supplied fictional inputs exactly.\n')
    if leak:
        (cli / 'bin/mode.txt').write_text('skills_leak')
        with pytest.raises(cli_worker.QualificationFailed) as failed:
            cli_worker.qualify(tid, rundir=cli / 'qualification', model='gemini-requested-fixture',
                               instructions=instruction)
        assert failed.value.failed == ['surface_ravel_only']
        assert not tr.qualification_path(tid).exists()
        receipt = failed.value.receipt
    else:
        record = cli_worker.qualify(tid, rundir=cli / 'qualification', model='gemini-requested-fixture',
                                    instructions=instruction)
        assert record['status'] == 'live_qualified' and all(step['passed'] for step in record['steps'])
        assert record['observed']['surface']['unexpected'] == []
        assert {'step': 'project_instructions_recorded', 'passed': True} in record['steps']
        receipt = json.loads(Path(record['receipt']['path']).read_text())
        assert record['receipt']['digest'] == broker.digest(receipt)
    assert receipt['status'] == 'ok' and receipt['attestation'] == 'transport_attested'
    assert receipt['model']['observed'] == 'gemini-served-fixture'
    assert receipt['model']['requested'] == 'gemini-requested-fixture'
    assert receipt['usage']['turns'] == 3 and receipt['usage']['input_tokens'] == 100
    assert receipt['usage']['output_tokens'] == 20
    assert receipt['transport']['project_instructions']['sha256'] == broker.sha(instruction)
    counter = receipt['transport']['observation']['provider_usage']
    assert counter['status'] == 'reported' and counter['requests'] == 3
    assert counter['usage'] == {'input_tokens': 95, 'cache_creation_input_tokens': 0,
                                'cache_read_input_tokens': 5, 'output_tokens': 20}
    assert counter['split_basis'][0]['kind'] == 'cache_resource_creation_separate_operation'
    spec = cli_worker.conformance_spec(cli_worker.conformance_card())
    ws = worker.workspace(cli / 'qualification', spec['node_id'], spec['attempt'])
    nonce = json.loads((cli / 'qualification/inputs/conformance.json').read_text())['nonce']
    assert (ws / 'outputs/conformance.txt').read_text() == nonce
    seen = json.loads((ws / 'scratch/seen.json').read_text())
    assert seen['prompt'].startswith('===== PROJECT INSTRUCTIONS =====')
    assert instruction.read_text() in seen['prompt']
    settings = json.loads((ws / 'scratch/gemini-settings.json').read_text())
    assert settings['tools']['core'] == [] and settings['context']['fileName'] == []
    assert list(settings['mcpServers']) == ['ravel']
    calls = [r['record'] for r in broker.ledger(cli / 'qualification', 'broker')]
    assert len(calls) == 3  # nonce read/write and the broker-written surface reply
