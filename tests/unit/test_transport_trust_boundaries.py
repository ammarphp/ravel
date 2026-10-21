"""Transport trust boundaries: host-written receipts, executor binding and refusals before launch.

Every case uses stub programs and synthetic declarations; no real agent CLI or model runs.
"""
import io
import json
import os
from pathlib import Path
import stat
import sys
import time

import pytest

from ravel.workflow import agent_graph as graph, cli_agent_host as cah, provider_transport as pt
from ravel.workflow import transport_receipt as trc, transport_registry as tr
from ravel.workflow.agent_host import AgentHost, HostFailure
from ravel.workflow.state_io import atomic_json, read_json
from test_agent_graph import role_packet, external_node, spec, node
from test_cli_agent_host import (CLAUDE_STUB, CODEX_STUB, GOOGLE_STUB, PARAMETERS, SCHEMA, calls, install_stub,
                                 stub_path)

ZERO = '0' * 64


def write_program(path, body):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(f'#!{sys.executable}\n' + body)
    path.chmod(0o700)
    return path


def model_node(tmp_path, role='proposer', identity='propose'):
    packet, sha = role_packet(tmp_path / f'{identity}-packet', role, {'x': 1})
    model = node(identity, kind='model', role=role)
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    return model, packet, sha


def run_graph(tmp_path, host, role='proposer'):
    model, packet, sha = model_node(tmp_path, role)
    root = tmp_path / 'graph'
    graph.create(root, spec([model], calls=1, tokens=256))
    return root, graph.execute(root, host), packet, sha


def saved_result(root, state, identity='propose'):
    return graph._result(root, state['nodes'][identity]['result'])['result']


def claimed_isolation(transport_id='claude-cli-oneshot', **changes):
    value = {'transport_id': transport_id, 'declaration_sha256': tr.declaration_sha256(tr.load(transport_id)),
             'argv_sha256': 'a' * 64, 'cli_version': 'stub 1', 'config': 'verified-flags',
             'config_overriding_arguments': [], 'env_names': ['HOME', 'PATH'], 'effort_transmitted': True,
             'user_configuration_loaded': False, 'basis': 'claimed by the child'}
    value.update(changes)
    return value


def printing_command(tmp_path, document_extra):
    """A command that echoes a valid result plus whatever isolation evidence the test plants."""
    program = write_program(tmp_path / 'forger' / 'forge.py', f'''
import json, sys
request = json.loads(sys.stdin.read())
extra = json.loads({json.dumps(json.dumps(document_extra))})
print(json.dumps({{'request_id': request['request_id'], 'value': {{'status': 'supported'}},
                  'usage': {{'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}},
                  'observed_model': 'claude-forged', **extra}}))
''')
    return [sys.executable, str(program)]


# ------------------------------------------------------------ critical: T1, T2, T3

def test_command_evidence_with_foreign_transport_id_refused(stub_path, tmp_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'codex', 'timeout_seconds': 120})
    assert host.transport['id'] == 'codex-cli-oneshot'
    host.command = tuple(printing_command(tmp_path, {'isolation': claimed_isolation('http-anthropic')}))
    root, state, _, _ = run_graph(tmp_path, host)
    assert not state['complete'] and 'not bound to this command' in json.dumps(state)


def test_command_evidence_zero_declaration_digest_refused(tmp_path):
    forged = claimed_isolation('codex-cli-oneshot', declaration_sha256=ZERO)
    host = AgentHost.from_config({'type': 'command', 'command': printing_command(tmp_path, {'isolation': forged})})
    root, state, _, _ = run_graph(tmp_path, host)
    assert not state['complete'] and 'declaration digest does not match' in json.dumps(state)


def test_command_without_host_receipt_is_never_independent(tmp_path):
    host = AgentHost.from_config({'type': 'command', 'command': printing_command(tmp_path, {'isolation': claimed_isolation()})})
    root, state, packet, sha = run_graph(tmp_path, host)
    assert state['complete']
    saved = saved_result(root, state)
    assert saved['isolation']['independent'] is False and saved['transport']['attestation'] == 'self_attested'
    assert saved['transport']['execution_mode'] == 'trusted_command_json'
    assert saved['isolation']['child_claims']['transport_id'] == 'claude-cli-oneshot'
    reviewed = graph.role_receipt(root, 'propose', expected_subject_sha256=sha, expected_packet_sha256=packet['manifest_sha256'],
                                  allowed_roles={'proposer'})
    assert reviewed['attestation'] == 'self_attested' and reviewed['execution_observation'] == 'unestablished'


def test_command_host_with_http_label_refused():
    with pytest.raises(HostFailure, match='not bound to this command'):
        AgentHost.from_config({'type': 'command', 'command': ['/bin/cat'], 'transport': 'http-responses'})


def test_command_host_with_worker_label_blind_critic_refused_before_spawn(tmp_path):
    log = tmp_path / 'spawned.log'
    program = write_program(tmp_path / 'worker' / 'w.py', f'open({str(log)!r}, "a").write("ran\\n")\n')
    with pytest.raises(HostFailure, match='not bound to this command'):
        AgentHost.from_config({'type': 'command', 'command': [sys.executable, str(program)],
                               'transport': 'claude-cli-worker'})
    assert not log.exists()


def _prepared_critic(tmp_path, identity='review', role='critic'):
    packet, _ = role_packet(tmp_path / f'{identity}-packet', role, {'x': 1})
    return external_node(packet, identity=identity, role=role)


def _response(root, identity, path, *, version, actor='fresh-critic', **changes):
    current = graph.status(root)['nodes'][identity]
    document = read_json(root / current['external_request']['path'])
    value = {'schema_version': version, 'request_id': document['request']['request_id'],
             'request_sha256': document['sha256'], 'invocation_id': 'hand-written', 'actor_id': actor,
             'observed_model': 'test-external-model', 'fresh_context': True, 'parent_transcript_supplied': False,
             'value': {'status': 'request_evidence'}}
    if version >= 2:
        value['usage_report'] = {'state': 'unknown', 'source': None,
                                 'tokens': {'input_tokens': None, 'output_tokens': None, 'total_tokens': None}}
    if version == 3:
        value.update(user_configuration_loaded=False, isolation=claimed_isolation())
    value.update(changes)
    atomic_json(path, value)
    return path


def test_v2_relay_critic_delivered_as_self_attested_not_independent(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path)], calls=1, tokens=256))
    graph.prepare_external(root, 'review')
    state = graph.deliver_external(root, 'review', _response(root, 'review', tmp_path / 'r.json', version=2))
    saved = saved_result(root, state, 'review')
    assert saved['transport']['attestation'] == 'self_attested' and saved['isolation']['independent'] is False


def test_v3_relay_zero_declaration_digest_refused(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path)], calls=1, tokens=256))
    graph.prepare_external(root, 'review')
    forged = _response(root, 'review', tmp_path / 'r.json', version=3,
                       isolation=claimed_isolation(declaration_sha256=ZERO))
    with pytest.raises(graph.GraphError, match='declaration digest'):
        graph.deliver_external(root, 'review', forged)


def test_v3_isolation_block_retained_in_saved_result(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'x': 1})
    root = tmp_path / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    saved = saved_result(root, graph.status(root), 'verify')
    evidence = saved['isolation']['transport_evidence']
    assert evidence['transport_id'] == 'claude-cli-oneshot' and evidence['cli_session_id'] == 'claude-session-1'
    assert evidence['declaration_sha256'] == tr.declaration_sha256(tr.load('claude-cli-oneshot'))
    assert 'PATH' in evidence['env_names'] and saved['isolation']['user_configuration_loaded'] is False
    assert saved['transport']['attestation'] == 'self_attested'


def test_same_session_id_different_actor_refused_for_second_reviewer(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path, 'first'), _prepared_critic(tmp_path, 'second', 'verifier')],
                            calls=2, tokens=512))
    graph.prepare_external(root, 'first')
    graph.prepare_external(root, 'second')
    shared = claimed_isolation(cli_session_id='session-shared')
    graph.deliver_external(root, 'first', _response(root, 'first', tmp_path / 'a.json', version=3,
                                                    actor='critic-a', isolation=shared))
    with pytest.raises(graph.GraphError, match='CLI session'):
        graph.deliver_external(root, 'second', _response(root, 'second', tmp_path / 'b.json', version=3,
                                                         actor='verifier-b', isolation=shared))


# ------------------------------------------------------------ T4: launched CLI maps to a transport observation

def test_verified_cli_receipt_maps_to_transport_observation_and_relay_does_not(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    root, state, packet, sha = run_graph(tmp_path, host)
    assert state['complete']
    saved = saved_result(root, state)
    assert saved['transport']['execution_mode'] == 'transport_attested_cli' and saved['isolation']['independent']
    pin = saved['transport']['session_receipt_pin']
    assert trc.read(root, pin)['launcher_receipt']['executable']['sha256'] == tr.file_sha256(stub_path / 'claude')
    reviewed = graph.role_receipt(root, 'propose', expected_subject_sha256=sha, expected_packet_sha256=packet['manifest_sha256'],
                                  allowed_roles={'proposer'})
    assert reviewed['execution_observation'] == 'transport_attested_cli' and reviewed['attestation'] == 'transport_attested'
    assert reviewed['session']['cli_session_id'] == 'claude-session-1'

    vpacket, vsha = role_packet(tmp_path / 'verifier', 'verifier', {'x': 1})
    relay = tmp_path / 'relay'
    graph.create(relay, spec([external_node(vpacket)], calls=1, tokens=256))
    graph.prepare_external(relay, 'verify')
    cah.answer_graph(relay, agent='claude', actor_id='fresh-verifier', timeout=30)
    relayed = graph.model_receipt(relay, 'verify', expected_subject_sha256=vsha, expected_packet_sha256=vpacket['manifest_sha256'])
    assert relayed['execution_observation'] == 'host_attested_external' and relayed['attestation'] == 'self_attested'


def test_tampered_session_record_is_not_transport_attested(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    root, state, packet, sha = run_graph(tmp_path, host)
    pin = saved_result(root, state)['transport']['session_receipt_pin']
    path = root / pin['path']
    path.chmod(0o600)
    record = json.loads(path.read_text())
    record['launcher_receipt']['cli_reported']['session_id'] = 'edited'
    path.write_text(json.dumps(record))
    reviewed = graph.role_receipt(root, 'propose', expected_subject_sha256=sha, expected_packet_sha256=packet['manifest_sha256'],
                                  allowed_roles={'proposer'})
    assert reviewed['attestation'] == 'self_attested' and reviewed['execution_observation'] == 'unestablished'


# ------------------------------------------------------------ T5, T14: argv inputs

@pytest.mark.parametrize('agent,stub,extra', [
    ('claude', CLAUDE_STUB, ['--tools', 'Bash']),
    ('claude', CLAUDE_STUB, ['--permission-mode', 'bypassPermissions']),
    ('claude', CLAUDE_STUB, ['--append-system-prompt', 'x']),
    ('codex', CODEX_STUB, ['-c', 'mcp_servers.x.command=sh']),
    ('codex', CODEX_STUB, ['-C/tmp']),
    ('codex', CODEX_STUB, ['--sandbox', 'danger-full-access']),
    ('codex', CODEX_STUB, ['--oss'])])
def test_extra_args_reenabling_tools_or_config_refused(stub_path, agent, stub, extra):
    install_stub(stub_path, agent, stub, {'text': '{"status": "supported"}'})
    with pytest.raises(cah.AgentCLIError):
        cah.invoke(agent, PARAMETERS, {}, timeout=30, extra_args=extra)
    assert not (stub_path / 'calls.jsonl').exists()


@pytest.mark.parametrize('agent,name,stub', [('claude', 'claude', CLAUDE_STUB), ('codex', 'codex', CODEX_STUB),
                                             ('gemini', 'gemini', GOOGLE_STUB), ('antigravity', 'agy', GOOGLE_STUB)])
def test_dash_led_model_refused_before_render(stub_path, agent, name, stub):
    install_stub(stub_path, name, stub, {'text': '{"status": "supported"}'})
    with pytest.raises(cah.AgentCLIError, match='model id'):
        cah.invoke(agent, {**PARAMETERS, 'model': '--yolo'}, {}, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


# ------------------------------------------------------------ T6, T16, T17, T19: tools, environment and HOME

def test_critic_refused_on_codex_oneshot_with_shell_tool(stub_path, tmp_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path)], calls=1, tokens=256))
    graph.prepare_external(root, 'review')
    request = root / graph.status(root)['nodes']['review']['external_request']['path']
    with pytest.raises(cah.AgentCLIError, match='tools broker-readonly'):
        cah.answer(request, tmp_path / 'out.json', agent='codex', timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_independent_review_card_refuses_gemini_and_agy_before_spawn(stub_path, tmp_path):
    install_stub(stub_path, 'gemini', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    install_stub(stub_path, 'agy', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    card = {'id': 'synthetic-review', 'family': 'review', 'requires': {'attestation_min': 'transport'},
            'model': {'tier': 'judgment', 'effort': None}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences',
                   'families': {'review': ['gemini-cli-oneshot', 'antigravity-cli-oneshot']},
                   'tier_models': {'judgment': {'gemini-cli-oneshot': 'gemini-x', 'antigravity-cli-oneshot': 'gemini-x'}}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences)
    assert 'attestation' in refused.value.missing
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path)], calls=1, tokens=256))
    graph.prepare_external(root, 'review')
    request = root / graph.status(root)['nodes']['review']['external_request']['path']
    for agent in ('gemini', 'antigravity'):
        with pytest.raises(cah.AgentCLIError, match='attestation host'):
            cah.answer(request, tmp_path / f'{agent}.json', agent=agent, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_proxy_credentials_and_pythonpath_not_passed():
    source = {'PATH': '/bin', 'HOME': '/h', 'HTTPS_PROXY': 'http://user:planted-pw@proxy.invalid:8080',
              'PYTHONPATH': '/elsewhere', 'XDG_CONFIG_HOME': '/xdg'}
    env, names = tr.child_environment(tr.load('claude-cli-oneshot'), source)
    assert env['HTTPS_PROXY'] == 'http://proxy.invalid:8080' and 'planted-pw' not in json.dumps(env)
    assert 'PYTHONPATH' not in env and 'XDG_CONFIG_HOME' not in env


def test_symlinked_auth_json_refused(tmp_path):
    user = tmp_path / 'codex-user'
    user.mkdir()
    (tmp_path / 'elsewhere.json').write_text('{"synthetic": "login"}')
    (user / 'auth.json').symlink_to(tmp_path / 'elsewhere.json')
    with pytest.raises(cah.AgentCLIError, match='symbolic link'):
        cah.fresh_codex_home(tmp_path / 'fresh', {'CODEX_HOME': str(user)})


DOTENV_STUB = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0'); sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read()); sys.exit(0)
seen = {{}}
for name in ('.env', '.gemini/.env'):
    path = os.path.join(os.environ['HOME'], name)
    seen[name] = open(path).read() if os.path.exists(path) else None
with open(os.path.join(here, 'calls.jsonl'), 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'home': os.environ['HOME'], 'seen': seen,
                          'home_entries': sorted(os.listdir(os.environ['HOME']))}}) + '\\n')
print(json.dumps({{'response': '{{"status": "supported"}}', 'stats': {{}}}}))
'''


def test_planted_home_dotenv_secret_not_visible_to_gemini_child(stub_path, tmp_path):
    install_stub(stub_path, 'gemini', DOTENV_STUB, {'text': ''})
    home = Path(os.environ['HOME'])
    (home / '.gemini').mkdir(parents=True)
    (home / '.env').write_text('GEMINI_API_KEY=planted-dotenv-secret\n')
    (home / '.gemini' / '.env').write_text('GOOGLE_API_KEY=planted-dotenv-secret\n')
    answer = cah.invoke('gemini', PARAMETERS, {}, timeout=30)
    call = calls(stub_path)[-1]
    assert call['home'] != str(home) and call['seen'] == {'.env': None, '.gemini/.env': None}
    assert 'planted-dotenv-secret' not in json.dumps(answer)
    receipt = answer['receipt']
    assert receipt['invocation']['home_mode'] == 'fresh'
    assert receipt['invocation']['dotenv_paths'] == sorted([str(home / '.env'), str(home / '.gemini' / '.env')])
    assert answer['cli_session_id'] is None and 'local-' not in json.dumps(answer)


VERSION_ENV_STUB = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, 'version-env.jsonl'), 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'env': sorted(os.environ)}}) + '\\n')
print('stub-cli 1.0.0')
'''


def test_planted_foo_api_key_absent_from_detect_version_calls(stub_path, monkeypatch):
    for name in ('claude', 'codex', 'agy', 'gemini'):
        install_stub(stub_path, name, VERSION_ENV_STUB, {'text': ''}, probe=False)
    monkeypatch.setenv('FOO_API_KEY', 'planted-foo-secret')
    found = cah.detect()
    assert all(found[a] for a in cah.AGENTS)
    rows = [json.loads(l) for l in (stub_path / 'version-env.jsonl').read_text().splitlines()]
    assert len(rows) == 4 and not any('FOO_API_KEY' in r['env'] for r in rows)


# ------------------------------------------------------------ T7, T8, T12, T13: probes and declarations

def _user_declaration(directory, identity, **capabilities):
    document = {'schema_version': 1, 'kind': 'transport', 'id': identity, 'transport_kind': 'cli-oneshot',
                'launcher': 'stubcli', 'argv_template': ['stubcli', '-p', '--model', '{model}'],
                'models': [{'id': '{configured}', 'family': 'anthropic', 'tiers': ['judgment']}],
                'auth': {'kind': 'login', 'env_names': [], 'command': None, 'header_style': None},
                'pass_env': [], 'billing': 'subscription',
                'capabilities': {'tools': 'none', 'isolation': 'cli-policy', 'attestation': 'transport',
                                 'structured_output': False, 'blind_capable': False, 'effort_control': False,
                                 'session_id': True, 'usage_report': True, **capabilities},
                'max_concurrent': 1, 'qualification': {'status': 'live_qualified', 'record': None}}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f'{identity}.json').write_text(json.dumps(document))
    return document


@pytest.fixture
def user_transports(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.chdir(tmp_path)
    return tmp_path / '.ravel' / 'transports'


def test_probe_failed_help_exit_confirms_nothing(user_transports, tmp_path, monkeypatch):
    _user_declaration(user_transports, 'stub-failing', session_id=True)
    write_program(tmp_path / 'bin' / 'stubcli', '''import sys
print('Usage: stubcli -p --model')
sys.exit(0 if sys.argv[1:] == ['--version'] else 2)
''')
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(tmp_path / 'bin'))
    monkeypatch.setenv('PATH', str(tmp_path / 'bin') + os.pathsep + os.environ['PATH'])
    record = tr.probe('stub-failing')
    assert 'help:exit' in record['unusable'] and not any(record['capabilities_confirmed'].values())
    assert tr.effective_capabilities(tr.load('stub-failing'), record)[0] is None


def test_forged_minimal_probe_record_rejected():
    document = tr.load('claude-cli-oneshot')
    forged = {'kind': 'transport-probe', 'declaration_sha256': tr.declaration_sha256(document),
              'capabilities_confirmed': {k: True for k in tr.BOOLEAN_CAPABILITIES}}
    capabilities, reasons = tr.effective_capabilities(document, forged)
    assert capabilities is None and reasons == ['probe:shape']


def test_probe_for_other_executable_sha_is_stale(stub_path):
    path = install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    document = tr.load('claude-cli-oneshot')
    record = tr.read_probe('claude-cli-oneshot')
    assert tr.effective_capabilities(document, record, executable_sha256=tr.file_sha256(path))[0] is not None
    capabilities, reasons = tr.effective_capabilities(document, record, executable_sha256='b' * 64)
    assert capabilities is None and reasons == ['probe:stale-executable']


def test_invoke_without_probe_refused(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'}, probe=False)
    with pytest.raises(cah.AgentCLIError, match='probe'):
        cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_binary_swapped_after_probe_refused(stub_path):
    path = install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    path.write_text(path.read_text() + '\n# replaced after the probe\n')
    with pytest.raises(cah.AgentCLIError, match='stale-executable'):
        cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_responses_host_with_xai_label_refused(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic')
    with pytest.raises(HostFailure, match='declares endpoint'):
        AgentHost.from_config({'type': 'responses', 'transport': 'http-xai'})
    monkeypatch.setenv('XAI_KEY_FOR_TEST', 'synthetic')
    with pytest.raises(HostFailure, match='authenticates with'):
        AgentHost.from_config({'type': 'responses', 'transport': 'http-responses', 'api_key_env': 'XAI_KEY_FOR_TEST'})


def test_worker_declared_sandbox_not_blind_admissible_without_sandbox_module():
    for identity in ('claude-cli-worker', 'codex-cli-worker', 'gemini-cli-worker', 'opencode-worker'):
        assert not tr.blind_admissible(tr.load(identity))
    assert tr.blind_admissible(tr.load('http-anthropic'))


def test_voting_role_refuses_declared_qualification():
    card = {'id': 'synthetic.critic', 'family': 'review', 'requires': {}, 'model': {'tier': 'judgment', 'effort': None}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'review': ['http-anthropic']},
                   'tier_models': {'judgment': {'http-anthropic': 'claude-x'}}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences)
    assert 'qualification' in refused.value.missing


def test_cwd_declaration_claiming_os_sandbox_not_blind_admissible(user_transports):
    document = _user_declaration(user_transports, 'stub-sandboxed', isolation='os-sandbox', blind_capable=True)
    assert tr.origin(tr.load('stub-sandboxed')) != 'builtin'
    assert not tr.blind_admissible(tr.load('stub-sandboxed'))
    record = {**{k: None for k in tr.PROBE_KEYS}, 'schema_version': 1, 'kind': 'transport-probe',
              'transport_id': 'stub-sandboxed', 'declaration_sha256': tr.declaration_sha256(document),
              'flags': {'-p': 'confirmed', '--model': 'confirmed'}, 'capabilities_confirmed': {}, 'unusable': [],
              'executable_path': '/x', 'executable_sha256': 'c' * 64, 'exit_status': 0}
    capabilities, _ = tr.effective_capabilities(tr.load('stub-sandboxed'), record)
    assert capabilities['isolation'] == 'cli-policy' and capabilities['blind_capable'] is False


# ------------------------------------------------------------ T9, T10, T11, T25: selection

def test_default_auto_host_config_binds_a_transport_and_declaration_digest(stub_path, monkeypatch):
    monkeypatch.setenv('PATH', str(stub_path))
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    shipped = Path(cah.__file__).resolve().parents[1] / 'data' / 'transports' / 'hosts' / 'agent-cli.json'
    config = cah.host_config(json.loads(shipped.read_text()))
    assert config['transport'] == 'codex-cli-oneshot' and 'auto' not in config['command']
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'review': ['codex-cli-oneshot']}}
    preferred = cah.host_config({'type': 'agent-cli', 'agent': 'auto', 'preferences': preferences})
    assert preferred['transport'] == 'codex-cli-oneshot'
    host = AgentHost(adapter='command', command=preferred['command'], environment=preferred['environment'],
                     transport=preferred['transport'])
    assert host.transport['id'] == 'codex-cli-oneshot'
    assert tr.declaration_sha256(host.transport) == tr.declaration_sha256(tr.load('codex-cli-oneshot'))


def test_grok_model_on_claude_transport_refused(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    card = {'id': 'synthetic-writer', 'family': 'writing', 'requires': {'structured_output': True},
            'model': {'tier': 'judgment', 'effort': 'high'}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'writing': ['claude-cli-oneshot']},
                   'tier_models': {'judgment': {'claude-cli-oneshot': 'grok-4'}}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences)
    assert refused.value.missing == ['model:family']
    preferences['tier_models']['judgment']['claude-cli-oneshot'] = 'claude-x'
    assert tr.select(card, preferences)['family'] == 'anthropic'


def test_unknown_family_is_labelled_not_refused():
    card = {'id': 'critic', 'model': {'distinct_family_from': ['producer']}}
    assert tr.check_distinct_families(card, {'critic': 'mystery-1', 'producer': 'mystery-1'}) == 'unknown'


def test_a_named_role_without_an_assignment_is_not_a_family_refusal():
    card = {'id': 'synthetic-reviewer', 'family': 'review', 'requires': {},
            'model': {'tier': 'judgment', 'effort': None, 'distinct_family_from': ['producer']}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'review': ['http-responses']},
                   'tier_models': {'judgment': {'http-responses': 'gpt-x'}}}
    try:
        selected = tr.select(card, preferences)
    except tr.TransportRefusal as refusal:
        assert not any('distinct_family_from' in code for code in refusal.missing)
    else:
        assert selected['family'] == 'openai'
    assert tr.check_distinct_families(card, {'synthetic-reviewer': 'gpt-x'}) == 'unknown'


def test_required_effort_on_effort_less_transport_refused():
    card = {'id': 'synthetic-writer', 'family': 'writing', 'requires': {}, 'model': {'tier': 'judgment', 'effort': 'high'}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'writing': ['http-anthropic']},
                   'tier_models': {'judgment': {'http-anthropic': 'claude-x'}}}
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, preferences)
    assert refused.value.missing == ['effort']


def test_gemini_effort_transmitted_false_when_argv_has_no_effort(stub_path):
    install_stub(stub_path, 'gemini', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    answer = cah.invoke('gemini', PARAMETERS, {}, timeout=30)
    assert '--effort' not in calls(stub_path)[-1]['argv']
    assert answer['receipt']['effort'] == {'requested': 'high', 'transmitted': False}
    assert answer['isolation']['effort_transmitted'] is False


def test_codex_oss_worker_cloud_model_refused_under_local_only():
    document = tr.load('codex-oss-worker')
    record = {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': 'codex-oss-worker',
              'declaration_sha256': tr.declaration_sha256(document), 'unusable': [], 'flags': {},
              'capabilities_confirmed': {k: True for k in tr.BOOLEAN_CAPABILITIES}}
    card = {'id': 'synthetic-writer', 'family': 'writing', 'requires': {}, 'model': {'tier': 'agent', 'effort': None}}
    preferences = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {'writing': ['codex-oss-worker']},
                   'tier_models': {'agent': {'codex-oss-worker': 'llama:cloud'}}}
    with pytest.raises(tr.TransportRefusal):
        tr.select(card, preferences, probes={'codex-oss-worker': record}, local_models=['llama:cloud'])
    local = tr.load('http-local')
    assert tr._local_problem(local, 'llama:cloud', ['llama:cloud']) == 'local_only:cloud-model'
    assert tr._local_problem(document, 'llama', ['llama']) == 'local_only:no-verified-destination'


# ------------------------------------------------------------ T15: session evidence

def test_serve_preserves_cli_session_id(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    raw = json.dumps({'schema_version': 1, 'request_id': 'r-1', 'parameters': PARAMETERS, 'context': {}})
    out = io.StringIO()
    cah.serve(io.StringIO(raw), out, agent='claude', timeout=30)
    document = json.loads(out.getvalue())
    receipt = document['session_receipt']
    assert receipt['cli_reported']['session_id'] == 'claude-session-1'
    assert receipt['invocation']['host_invocation_id'].startswith('host-')
    assert receipt['content']['request_sha256'] == trc.sha256_bytes(raw.encode())


def test_missing_session_id_is_null_not_local_uuid(stub_path):
    install_stub(stub_path, 'gemini', DOTENV_STUB, {'text': ''})
    answer = cah.invoke('gemini', PARAMETERS, {}, timeout=30)
    assert answer['receipt']['cli_reported']['session_id'] is None and answer['cli_session_id'] is None
    assert 'local-' not in json.dumps(answer)


def test_codex_argv_digest_matches_executed_order(stub_path):
    path = install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    answer = cah.invoke('codex', PARAMETERS, {}, timeout=30)
    executed = [str(path.resolve())] + calls(stub_path)[-1]['argv']
    assert answer['receipt']['invocation']['argv_sha256'] == tr.digest(executed)
    assert answer['receipt']['executable'] == {'path': str(path.resolve()), 'sha256': tr.file_sha256(path),
                                               'cli_version': 'stub-cli 1.0.0'}


# ------------------------------------------------------------ T18: process lifecycle

SPAWNING_STUB = '''#!{python}
import os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0'); sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read()); sys.exit(0)
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
open(os.path.join(here, 'grandchild.pid'), 'w').write(str(child.pid))
time.sleep(120)
'''


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_outer_cancel_kills_inner_cli_grandchild(stub_path, tmp_path):
    install_stub(stub_path, 'claude', SPAWNING_STUB, {'text': ''})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 6,
                                  'cli_timeout_seconds': 120})
    pid_file = stub_path / 'grandchild.pid'
    try:
        root, state, _, _ = run_graph(tmp_path, host)
        assert not state['complete']
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 10
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(.1)
        assert not _alive(pid)
    finally:
        if pid_file.exists() and _alive(int(pid_file.read_text())):
            os.kill(int(pid_file.read_text()), 9)


# ------------------------------------------------------------ minor findings

def test_cli_stderr_token_text_not_in_error_or_exit_message(stub_path):
    install_stub(stub_path, 'claude', '''#!{python}
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0'); sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read()); sys.exit(0)
print('auth failed for sk-planted-token-123', file=sys.stderr)
sys.exit(2)
''', {'text': ''})
    with pytest.raises(cah.AgentCLIError) as failed:
        cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert 'sk-planted' not in str(failed.value) and failed.value.code == 'exit'


def test_inner_cli_stdout_over_bound_stops_process(stub_path):
    install_stub(stub_path, 'claude', '''#!{python}
import os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0'); sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read()); sys.exit(0)
sys.stdout.write('x' * 2_000_000)
''', {'text': ''})
    with pytest.raises(cah.AgentCLIError) as failed:
        cah.invoke('claude', PARAMETERS, {}, timeout=30, max_output_bytes=100_000)
    assert failed.value.code == 'output'


def test_azure_api_version_query_refused_with_v1_guidance(monkeypatch):
    monkeypatch.setenv('AZ_KEY_FOR_TEST', 'synthetic')
    with pytest.raises(HostFailure, match='/openai/v1/'):
        AgentHost.from_config({'type': 'chat_completions', 'api_key_env': 'AZ_KEY_FOR_TEST',
                               'endpoint': 'https://example.openai.azure.com/openai/deployments/d/chat/completions?api-version=2024-10-21'})


@pytest.mark.parametrize('document', [d for d in tr.all_declarations() if d['transport_kind'] in tr.CLI_KINDS],
                         ids=lambda d: d['id'])
def test_select_then_render_composes_for_every_declaration(document):
    names = {n for token in document['argv_template'] for n in tr.PLACEHOLDER.findall(token)}
    values = {n: 'x' for n in names}
    if not document['capabilities']['effort_control']:
        values['effort'] = None
    tr.render_argv(document, values)


def test_azure_codex_route_unavailable_until_provider_generated():
    capabilities, reasons = tr.effective_capabilities(tr.load('codex-cli-worker-azure'), None)
    assert capabilities is None and reasons == ['unimplemented:codex-cli-worker-azure']


def test_antigravity_prompt_cap_accounts_for_environment(stub_path, monkeypatch):
    install_stub(stub_path, 'agy', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    request, room = {'evidence': 'y' * 1024}, 8192
    document = tr.load(cah.ONESHOT['antigravity'])
    passed = lambda: sum(len(k) + len(v) + 2 for k, v in tr.child_environment(document)[0].items())
    # The room for the prompt is ARG_MAX less the margin and the environment the child receives.
    # Measure that environment here, so the result does not depend on how much the host passes on.
    before = passed()
    monkeypatch.setattr(cah, '_arg_max', lambda: cah.ARGV_MARGIN + before + room)
    cah.invoke('antigravity', PARAMETERS, request, timeout=30)
    prompt = calls(stub_path)[-1]['argv'][1]
    assert 1024 < len(prompt.encode()) <= room and len(calls(stub_path)) == 1
    # The same request and the same ARG_MAX: a larger passed environment alone leaves no room.
    assert 'TERM' in tr.BASE_ENVIRONMENT
    monkeypatch.setenv('TERM', 'x' * room)
    assert passed() >= before + room - 64
    with pytest.raises(cah.AgentCLIError, match='ARG_MAX'):
        cah.invoke('antigravity', PARAMETERS, request, timeout=30)
    assert len(calls(stub_path)) == 1


INIT_STUB = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0'); sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read()); sys.exit(0)
config = json.load(open(os.path.join(here, 'answer.json')))
result = {{'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '{{"status": "supported"}}',
          'session_id': 's-1'}}
init = {{'type': 'system', 'subtype': 'init', 'mcp_servers': config['mcp'], 'plugins': []}}
print(json.dumps([init, result] if config['stream'] else result))
'''


def test_claude_config_reported_from_stream_json_init(stub_path):
    install_stub(stub_path, 'claude', INIT_STUB, {'stream': True, 'mcp': [{'name': 'user-server'}]})
    loaded = cah.invoke('claude', PARAMETERS, {}, timeout=30)['receipt']['configuration']
    assert loaded['user_configuration_loaded'] is True and 'stream-json init' in loaded['basis']
    install_stub(stub_path, 'claude', INIT_STUB, {'stream': False, 'mcp': []})
    plain = cah.invoke('claude', PARAMETERS, {}, timeout=30)['receipt']['configuration']
    assert plain['user_configuration_loaded'] is False and 'isolation flags' in plain['basis']


def test_managed_settings_presence_recorded(stub_path, tmp_path, monkeypatch):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    managed = tmp_path / 'managed-settings.json'
    managed.write_text('{"hooks": {}}')
    monkeypatch.setattr(cah, 'MANAGED_SETTINGS', (str(managed),))
    configuration = cah.invoke('claude', PARAMETERS, {}, timeout=30)['receipt']['configuration']
    assert configuration['managed_settings_sha256'] == tr.file_sha256(managed)
    assert 'admin-managed settings' in configuration['basis']


def test_relative_or_world_writable_token_command_refused(tmp_path):
    with pytest.raises(pt.ProviderFailure, match='absolute path'):
        pt.run_token_command(['print-token'])
    program = write_program(tmp_path / 'token' / 'print-token', 'print("synthetic-token")\n')
    assert pt.run_token_command([str(program)]) == 'synthetic-token'
    program.chmod(program.stat().st_mode | stat.S_IWOTH)
    with pytest.raises(pt.ProviderFailure, match='writable'):
        pt.run_token_command([str(program)])


def test_structured_output_false_without_schema_flag():
    for document in tr.all_declarations():
        if document['transport_kind'] in tr.CLI_KINDS and document['capabilities']['structured_output']:
            template = ' '.join(document['argv_template'])
            assert '{schema}' in template or '{schema_file}' in template, document['id']


def test_codex_readonly_rank_below_ravel_sandbox():
    assert tr.ISOLATION.index('cli-policy') < tr.ISOLATION.index('os-sandbox-readonly') < tr.ISOLATION.index('ravel-sandbox')


# ------------------------------------------------------------ P-2: golden argv for every one-shot

def test_codex_golden_argv(stub_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    cah.invoke('codex', PARAMETERS, {}, timeout=30)
    argv = calls(stub_path)[-1]['argv']
    assert argv[:-2] == ['exec', '--json', '--skip-git-repo-check', '--sandbox', 'read-only', '--model',
                         'requested-model', '-c', 'model_reasoning_effort="high"', '--output-last-message']
    assert argv[-2].endswith('/last-message.txt') and argv[-1] == '-'


def test_gemini_golden_argv(stub_path):
    install_stub(stub_path, 'gemini', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    cah.invoke('gemini', PARAMETERS, {}, timeout=30)
    assert calls(stub_path)[-1]['argv'] == ['-p', 'Answer the request given on standard input.', '--output-format',
                                            'json', '--model', 'requested-model']


def test_antigravity_golden_argv_records_prompt_digest_not_prompt(stub_path):
    install_stub(stub_path, 'agy', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    answer = cah.invoke('antigravity', PARAMETERS, {}, timeout=30)
    argv = calls(stub_path)[-1]['argv']
    assert argv[2:] == ['--output-format', 'json', '--model', 'requested-model', '--effort', 'high', '--json-schema',
                        json.dumps(SCHEMA, sort_keys=True), '--mode', 'plan', '--disable-slash-commands',
                        '--print-timeout', '25s']
    receipt = answer['receipt']
    assert receipt['invocation']['prompt_in_argv'] is True
    assert argv[1] not in json.dumps(receipt) and receipt['content']['prompt_sha256'] == trc.sha256_bytes(argv[1].encode())

# Transport regressions: written before the implementation changes.
from types import SimpleNamespace
from test_scientific_judgment import observed_role_boundary
from test_scientific_judgment import cycle, prepare, complete, FakeHost
from test_physics_review import run
from ravel.workflow import scientific_judgment as judgment


class ReceiptHost(FakeHost):
    """Account synthetic role content with real launcher verification or relay evidence."""
    def __init__(self, *, version=None, stub=None, mutate=None):
        super().__init__(mutate=mutate)
        self.version, self.stub = version, stub

    def execute(self, node, request, control):
        def call(action, kind, body, operation, **kwargs):
            def observed():
                result = operation()
                if self.version is not None:
                    result['transport'].update(execution_mode='host_mediated_external',
                        response_schema_version=self.version, attestation='transport_attested')
                    if self.version == 3:
                        result['isolation']['transport_evidence'] = claimed_isolation()
                else:
                    install_stub(self.stub, 'claude', CLAUDE_STUB.replace('claude-session-1', request['request_id']),
                                 {'text': json.dumps(result['value'])})
                    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude'})
                    data = json.dumps({'request_id': request['request_id']}).encode()
                    answer = cah.invoke('claude', node['parameters'], {}, request_sha256=trc.sha256_bytes(data))
                    host._session_receipt({'session_receipt': answer['receipt'], 'value': result['value']},
                        data, result, request, control, SimpleNamespace(pid=1, returncode=0), b'synthetic envelope')
                return result
            return control.call(action, kind, body, observed, **kwargs)
        return super().execute(node, request, SimpleNamespace(call=call))


@pytest.mark.parametrize('version', [1, 2, 3])
@pytest.mark.parametrize('role', ['critic', 'verifier', 'synthesizer'])
def test_m03_relay_refused_at_judgment_acceptance(cycle, tmp_path, version, role, observed_role_boundary):
    if role == 'synthesizer':
        for prior in ('critic', 'verifier'):
            complete(cycle, prepare(cycle, tmp_path / 'prior', prior))
    binding = prepare(cycle, tmp_path / 'role', role, action='external')
    root = Path(binding['graph_root'])
    spec_, _ = graph._load(root)
    model = spec_['nodes'][0]
    # Generate only the synthetic public value, then deliver through the actual relay.
    value = FakeHost().execute(model, {'request_id': 'synthetic'},
        SimpleNamespace(call=lambda action, kind, body, operation, **kw: operation()))['value']
    graph.prepare_external(root, role)
    response = _response(root, role, tmp_path / 'relay.json', version=version,
                         actor=judgment._read_pin(binding['request'])['actor_id'], value=value)
    graph.deliver_external(root, role, response)
    with pytest.raises(ValueError, match='self-attested review is advisory; it does not count as independent'):
        judgment.consume(cycle, binding)
    # B4/M-15F: configuration can reach this switch, so it cannot admit relay votes.
    with pytest.raises(ValueError, match='self-attested review is advisory'):
        judgment.verify_binding(binding, allow_control=True)


def test_m03_handwritten_v3_never_independent(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([_prepared_critic(tmp_path)], calls=1, tokens=256))
    graph.prepare_external(root, 'review')
    response = _response(root, 'review', tmp_path / 'r.json', version=3)
    state = graph.deliver_external(root, 'review', response)
    saved = saved_result(root, state, 'review')
    assert saved['transport']['attestation'] == 'self_attested'
    assert saved['isolation']['independent'] is False
    assert saved['isolation']['transport_evidence'] == claimed_isolation()
    assert 'authorship' in saved['isolation']['limitation']
    path = root / state['nodes']['review']['result']['path']
    stored = read_json(path)
    stored['result']['transport']['attestation'] = 'transport_attested'
    atomic_json(path, stored)
    changed = read_json(path)['result']
    label, _ = graph._receipt_attestation(root, changed['transport'], 'host_attested_external', changed['isolation'])
    assert label == 'self_attested'


def test_m03_verified_cli_critic_passes(cycle, tmp_path, stub_path):
    binding = prepare(cycle, tmp_path / 'role', 'critic')
    judgment.execute_role(binding, ReceiptHost(stub=stub_path))
    assert judgment.consume(cycle, binding)['verdict'] == 'accept'


@pytest.mark.parametrize('required,expected', [('none', 'host_attested'), ('broker-readonly', 'transport_attested')])
def test_m03_tool_policy_attestation(stub_path, required, expected):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    receipt = cah.invoke('codex', PARAMETERS, {})['receipt']
    label, reasons = trc.attestation(receipt, verification=[], tools_required=required)
    assert label == expected
    assert ('tools' in ' '.join(reasons)) if required == 'none' else not reasons


def test_m03_request_tool_policy_reaches_host_receipt(stub_path, tmp_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    request = {'request_id': 'policy', 'parameters': PARAMETERS, 'context': {},
               'role_requires': {'tools': 'broker-readonly'}}
    data = json.dumps(request).encode()
    out = io.StringIO()
    cah.serve(io.StringIO(data.decode()), out, agent='codex', timeout=30)
    document = json.loads(out.getvalue())
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'codex'})
    result = {'isolation': {}, 'transport': {}}
    host._session_receipt(document, data, result, request, SimpleNamespace(root=tmp_path, attempt_id='a'),
                          SimpleNamespace(pid=1, returncode=0), out.getvalue().encode())
    assert result['transport']['attestation'] == 'transport_attested'
    assert document['session_receipt']['configuration']['tools_required'] == 'broker-readonly'
    assert graph._receipt_attestation(tmp_path, result['transport'], 'unestablished')[0] == 'transport_attested'


def test_m03_canonical_voting_status():
    assert tr.is_voting({'id': 'physics-decider', 'independence': {'kind': 'voting'}, 'requires': {'blind': False}})
    assert not tr.is_voting({'id': 'critic', 'independence': {'kind': 'advisory'}, 'voting': True, 'requires': {'blind': True}})
    for card in ({'voting': True}, {'requires': {'blind': True}}, {'id': 'critic'}):
        assert tr.is_voting(card)


def test_m03_wrapper_rejects_extra_pythonpath():
    command = cah.wrapper_prefix() + ['--agent', 'claude', '--timeout', '30']
    assert cah.wrapper_agent(command, {'PYTHONPATH': str(cah.source_root()) + os.pathsep + '/other'}) is None


@pytest.mark.parametrize('location', ['temporary', 'run', 'project', 'TMPDIR'])
def test_m03_probe_refuses_writable_locations(tmp_path, monkeypatch, location):
    monkeypatch.delenv('RAVEL_TEST_TRUSTED_BIN', raising=False)
    root = tmp_path / location
    root.mkdir()
    if location == 'run':
        monkeypatch.chdir(root)
    elif location == 'project':
        (root / 'pyproject.toml').write_text('[project]\nname="synthetic"\n')
        monkeypatch.chdir(root)
    elif location == 'TMPDIR':
        monkeypatch.setenv('TMPDIR', str(root))
    else:
        monkeypatch.delenv('TMPDIR', raising=False)  # macOS sets TMPDIR to the system temporary directory
    program = write_program(root / 'cli', 'print("must not run")\n')
    with pytest.raises(ValueError, match=location):
        tr.probe('claude-cli-oneshot', executable=str(program))


def test_m03_test_bin_override_requires_the_test_lock_domain(tmp_path, monkeypatch):
    from ravel.workflow import machine_lease as ml
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(tmp_path))
    # Machine-domain rules: a forged test-runner variable does not restore the exemption.
    monkeypatch.setattr(ml, '_LOCATION', tmp_path / 'machine')
    monkeypatch.setenv('PYTEST_CURRENT_TEST', 'forged')
    monkeypatch.delenv('TMPDIR', raising=False)
    program = write_program(tmp_path / 'cli', 'print("must not run")\n')
    with pytest.raises(ValueError, match='temporary'):
        tr.probe('claude-cli-oneshot', executable=str(program))


@pytest.fixture
def installed_home():
    """A home directory outside every location the probe rule treats as temporary storage.

    pytest's own directory may lie under /tmp (it does wherever TMPDIR points there), and a
    program under /tmp is refused whatever the test declares. The persistent temporary
    directory is not /tmp on any host; the first one this account can write is used.
    """
    import shutil
    import tempfile
    refused = Path('/tmp').resolve()
    for parent in ('/var/tmp', '/dev/shm'):
        base = Path(parent).resolve()
        if base.is_dir() and os.access(base, os.W_OK | os.X_OK) and not base.is_relative_to(refused):
            root = Path(tempfile.mkdtemp(prefix='ravel-installed-', dir=base)).resolve()
            try:
                yield root / 'home'
            finally:
                shutil.rmtree(root, ignore_errors=True)
            return
    pytest.fail('no writable directory outside /tmp to stand for a user installation')


@pytest.mark.parametrize('start', ['home', 'root'])
def test_m03_probe_from_home_or_root_keeps_user_installed_cli(tmp_path, monkeypatch, start, installed_home):
    # The default run directory is the current one, but a home or filesystem-root cwd is not a run.
    monkeypatch.delenv('RAVEL_TEST_TRUSTED_BIN', raising=False)
    monkeypatch.delenv('TMPDIR', raising=False)
    monkeypatch.setattr(tr.tempfile, 'gettempdir', lambda: str(tmp_path / 'system-tmp'))
    home = installed_home
    assert not home.is_relative_to(Path('/tmp').resolve())
    monkeypatch.setenv('HOME', str(home))
    program = write_program(home / '.local' / 'bin' / 'cli', 'print("never run")\n')
    monkeypatch.chdir(home if start == 'home' else '/')
    tr.check_executable_location(program)
    with pytest.raises(ValueError, match='run'):
        tr.check_executable_location(program, rundir=home / '.local')


def test_m03_explicit_executable_must_match_probe(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    other = write_program(stub_path / 'replacement', 'print("must not run")\n')
    with pytest.raises(cah.AgentCLIError, match='stale-executable'):
        cah.invoke('claude', PARAMETERS, {}, executable=str(other))


@pytest.mark.parametrize('mode', [0o777, 0o770])
def test_m03_token_program_writable_ancestor_refused(tmp_path, mode):
    ancestor = tmp_path / 'unsafe'
    program = write_program(ancestor / 'private' / 'token', 'print("synthetic")\n')
    ancestor.chmod(mode)
    try:
        with pytest.raises(pt.ProviderFailure, match='writable'):
            pt.check_token_program(str(program))
    finally:
        ancestor.chmod(0o700)


def test_m03_research_host_config_receipt(tmp_path, monkeypatch, capsys):
    from ravel.workflow import research_cycle as rc, research_board_discussion as board
    config = tmp_path / 'operator-host.json'
    config.write_text('{"type": "scripted", "responses": {}}')
    root = tmp_path / 'cycle'
    root.mkdir()
    report = tmp_path / 'discussion' / 'report.json'
    report.parent.mkdir()
    report.write_text('{}')
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({'preparation_pin': {'path': 'unused', 'sha256': ZERO, 'size': 0},
                                  'host_config': rc._pin(config)}))
    monkeypatch.setattr(AgentHost, 'from_config', lambda value: SimpleNamespace())
    monkeypatch.setattr(board, 'run', lambda *args, **kwargs: rc._pin(report))
    assert rc.main(['discussion-run', '--cycle', str(root), '--request', str(request)]) == 0
    receipt = read_json(report.parent / 'host-config-receipt.json')
    assert receipt['host_config']['path'] == str(config.resolve())
    assert receipt['host_config']['sha256'] == tr.file_sha256(config)
    assert receipt['report'] == rc._pin(report)
