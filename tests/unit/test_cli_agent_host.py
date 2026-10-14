"""Fresh agent-CLI host: stub claude/codex/agy/gemini programs, never a real model."""
import json
import os
from pathlib import Path
import stat
import sys
import textwrap

import pytest

from ravel.workflow import agent_graph as graph, cli_agent_host as cah, transport_registry as tr
from ravel.workflow.agent_host import AgentHost
from ravel.workflow.state_io import read_json
from test_agent_graph import role_packet, external_node, spec, node

SCHEMA = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['request_evidence', 'supported']}},
          'required': ['status'], 'additionalProperties': False}

CLAUDE_STUB = '''#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0')
    sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read())
    sys.exit(0)
prompt = sys.stdin.read()
with open(os.path.join(here, 'calls.jsonl'), 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'cwd_entries': os.listdir('.'), 'prompt': prompt,
                          'env': dict(os.environ)}}) + '\\n')
config = json.load(open(os.path.join(here, 'answer.json')))
time.sleep(config.get('sleep', 0))
result = {{'type': 'result', 'subtype': 'success', 'is_error': False, 'num_turns': 1,
    'result': config['text'], 'session_id': 'claude-session-1',
    'usage': {{'input_tokens': 7, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 300, 'output_tokens': 15}},
    'modelUsage': {{'claude-stub-build-1': {{'outputTokens': 15}}, 'claude-small-stub': {{'outputTokens': 2}}}}}}
if config.get('report_user_config'):
    print(json.dumps([{{'type': 'system', 'subtype': 'init', 'memory_paths': {{'user': '~/.claude/CLAUDE.md'}}}}, result]))
else:
    print(json.dumps(result))
'''

CODEX_STUB = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0')
    sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read())
    sys.exit(0)
prompt = sys.stdin.read()
argv = sys.argv[1:]
home = os.environ.get('CODEX_HOME', '')
auth = os.path.join(home, 'auth.json')
with open(os.path.join(here, 'calls.jsonl'), 'a') as log:
    log.write(json.dumps({{'argv': argv, 'cwd': os.getcwd(), 'prompt': prompt, 'codex_home': home,
                          'home_entries': sorted(os.listdir(home)) if home else None,
                          'auth': open(auth).read() if home and os.path.exists(auth) else None,
                          'env': dict(os.environ)}}) + '\\n')
config = json.load(open(os.path.join(here, 'answer.json')))
out = argv[argv.index('--output-last-message') + 1]
open(out, 'w').write(config['text'])
if config.get('rollout_model') and home:
    rollout = os.path.join(home, 'sessions', '2026', '10', '10', 'rollout-2026-10-10T10-00-00-thread-42.jsonl')
    os.makedirs(os.path.dirname(rollout))
    open(rollout, 'w').write(json.dumps({{'type': 'turn_context', 'payload': {{'model': config['rollout_model']}}}}) + '\\n')
print(json.dumps({{'type': 'thread.started', 'thread_id': 'thread-42'}}))
print(json.dumps({{'type': 'item.completed', 'item': {{'type': 'agent_message', 'text': config['text']}}}}))
print(json.dumps({{'type': 'turn.completed', 'usage': {{'input_tokens': 900, 'cached_input_tokens': 600, 'output_tokens': 33}}}}))
'''

GOOGLE_STUB = '''#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
if sys.argv[1:] == ['--version']:
    print('stub-cli 1.0.0')
    sys.exit(0)
if '--help' in sys.argv[1:]:
    print(open(os.path.join(here, 'help.txt')).read())
    sys.exit(0)
prompt = sys.stdin.read()
with open(os.path.join(here, 'calls.jsonl'), 'a') as log:
    log.write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'prompt': prompt, 'env': dict(os.environ)}}) + '\\n')
config = json.load(open(os.path.join(here, 'answer.json')))
print(json.dumps({{'response': config['text'], 'session_id': 'google-session-7',
    'stats': {{'models': {{'gemini-stub-pro': {{'tokens': {{'prompt': 40, 'candidates': 9, 'thoughts': 3, 'total': 52}}}}}}}}}}))
'''


AGENT_OF = {'claude': 'claude', 'codex': 'codex', 'agy': 'antigravity', 'gemini': 'gemini'}
HELP = '\n'.join(sorted({f for agent in cah.ONESHOT.values() for f in tr.template_flags(tr.load(agent))}))


def install_stub(bin_dir, name, text, answer, *, probe=True):
    """A stub CLI that answers --version and --help, then probed so the launcher accepts it."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(text.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    (bin_dir / 'answer.json').write_text(json.dumps(answer))
    (bin_dir / 'help.txt').write_text('Usage: stub\n' + HELP + '\n')
    if probe:
        record = tr.probe(cah.ONESHOT[AGENT_OF[name]], executable=str(path))
        assert record['unusable'] == [], record
    return path


@pytest.fixture
def stub_path(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'trusted-bin'
    monkeypatch.setenv('RAVEL_TEST_TRUSTED_BIN', str(bin_dir))
    monkeypatch.setenv('PATH', str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    return bin_dir


def calls(bin_dir):
    return [json.loads(l) for l in (bin_dir / 'calls.jsonl').read_text().splitlines()]


PARAMETERS = {'model': 'requested-model', 'reasoning_effort': 'high', 'max_output_tokens': 256,
              'instructions': 'Check the supplied covariance.', 'output_schema': SCHEMA}


def test_claude_fresh_session_answer_model_and_usage(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '```json\n{"status": "supported"}\n```'})
    answer = cah.invoke('auto', PARAMETERS, {'evidence': [1, 2]}, timeout=30)
    assert answer['agent'] == 'claude' and answer['value'] == {'status': 'supported'}
    assert answer['observed_model'] == 'claude-stub-build-1' and answer['cli_session_id'] == 'claude-session-1'
    assert answer['usage'] == {'input_tokens': 327, 'output_tokens': 15, 'total_tokens': 342}
    call = calls(stub_path)[-1]  # auto-detection first asks for --version
    assert call['argv'][:5] == ['-p', '--output-format', 'json', '--model', 'requested-model']
    assert not {'--resume', '--continue', '-c', '-r'} & set(call['argv'])
    assert call['cwd_entries'] == [] and 'ravel-agent-cli-' in call['cwd']
    assert 'Check the supplied covariance.' in call['prompt'] and '"evidence"' in call['prompt'] and '"enum"' in call['prompt']


def test_codex_answer_uses_reported_usage_and_own_rollout_model(stub_path, tmp_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "request_evidence"}', 'rollout_model': 'gpt-stub-served'})
    answer = cah.invoke('codex', PARAMETERS, {}, timeout=30)
    assert answer['value'] == {'status': 'request_evidence'} and answer['cli_session_id'] == 'thread-42'
    assert answer['observed_model'] == 'gpt-stub-served'
    assert answer['usage'] == {'input_tokens': 900, 'output_tokens': 33, 'total_tokens': 933}
    argv = calls(stub_path)[0]['argv']
    assert argv[0] == 'exec' and '--json' in argv and argv[-1] == '-' and 'model_reasoning_effort="high"' in argv


def test_unreported_model_is_labelled_not_invented(stub_path, tmp_path):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}'})
    answer = cah.invoke('codex', PARAMETERS, {}, timeout=30)
    assert answer['observed_model'].startswith('not reported by codex')


@pytest.mark.parametrize('text', ['no json here', '{"status": "maybe"}', '[1, 2]'])
def test_answer_outside_schema_refused(stub_path, text):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': text})
    with pytest.raises(cah.AgentCLIError):
        cah.invoke('claude', PARAMETERS, {}, timeout=30)


def test_timeout_stops_only_its_own_process_group(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}', 'sleep': 30})
    with pytest.raises(cah.AgentCLIError, match='timeout'):
        cah.invoke('claude', PARAMETERS, {}, timeout=1)


def test_no_cli_installed_is_a_clear_refusal(tmp_path, monkeypatch):
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    with pytest.raises(cah.AgentCLIError, match='no agent CLI'):
        cah.choose('auto')


def test_external_request_answered_and_delivered_into_graph(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = tmp_path / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    assert [d['node_id'] for d in result['delivered']] == ['verify']
    state = graph.status(root)
    assert state['complete'] and state['nodes']['verify']['status'] == 'completed'
    response = read_json(result['delivered'][0]['response']['path'])
    assert response['fresh_context'] is True and response['parent_transcript_supplied'] is False
    assert response['usage_report']['state'] == 'host_reported' and response['observed_model'] == 'claude-stub-build-1'
    reviewed = graph.model_receipt(root, 'verify', expected_subject_sha256=sha, expected_packet_sha256=packet['manifest_sha256'])
    assert reviewed['execution_observation'] == 'host_attested_external' and not reviewed['actor_identity_authenticated']
    assert 'human' not in json.dumps(result).replace('not human', '')


def test_answer_graph_prepares_ready_nodes_and_reads_declared_actor(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    packet, _ = role_packet(tmp_path / 'critic', 'critic', {'x': 1})
    out = tmp_path / 'role'
    out.mkdir()
    root = out / 'graph'
    graph.create(root, spec([external_node(packet, role='critic')], calls=1, tokens=256))
    (out / 'binding.json').write_text(json.dumps({'graph_root': str(root), 'actor_id': 'declared-critic'}))
    result = cah.answer_graph(root, agent='claude', timeout=30, prepare_pending=True)
    response = read_json(result['delivered'][0]['response']['path'])
    assert response['actor_id'] == 'declared-critic'


def test_host_config_runs_command_adapter_with_observed_model(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    assert host.adapter == 'command' and 'ravel.workflow.cli_agent_host' in host.command
    packet, _ = role_packet(tmp_path / 'proposer', 'proposer', {'x': 1})
    model = node('propose', kind='model', role='proposer')
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    root = tmp_path / 'graph'
    graph.create(root, spec([model], calls=1, tokens=256))
    state = graph.execute(root, host)
    assert state['complete']
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    assert saved['transport']['observed_model'] == 'claude-stub-build-1'
    assert saved['usage'] == {'input_tokens': 327, 'output_tokens': 15, 'total_tokens': 342}


def test_host_config_rejects_unknown_fields():
    with pytest.raises(ValueError):
        cah.host_config({'type': 'agent-cli', 'agent': 'claude', 'api_key': 'x'})


# ------------------------------------------------------------ isolation, environment, truthful configuration

def test_claude_golden_argv_carries_every_isolation_flag(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    answer = cah.invoke('claude', PARAMETERS, {}, timeout=30)
    argv = calls(stub_path)[-1]['argv']
    assert argv == ['-p', '--output-format', 'json', '--model', 'requested-model', '--effort', 'high',
                    '--json-schema', json.dumps(SCHEMA, sort_keys=True), '--setting-sources', 'project', '--safe-mode',
                    '--strict-mcp-config', '--no-session-persistence', '--tools', '']
    assert '--bare' not in argv
    isolation = answer['isolation']
    assert isolation['transport_id'] == 'claude-cli-oneshot' and isolation['config'] == 'verified-flags'
    assert isolation['user_configuration_loaded'] is False and isolation['effort_transmitted'] is True


def test_unsupported_effort_is_refused_not_dropped(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    with pytest.raises(cah.AgentCLIError, match='effort'):
        cah.invoke('claude', {**PARAMETERS, 'reasoning_effort': 'minimal'}, {}, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_planted_secrets_never_reach_the_child_or_any_record(stub_path, tmp_path, monkeypatch):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    monkeypatch.setenv('FOO_API_KEY', 'planted-foo-secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'planted-openai-secret')
    monkeypatch.setenv('ANTHROPIC_AUTH_TOKEN', 'planted-anthropic-secret')
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'claude-config'))
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'x': 1})
    root = tmp_path / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    env = calls(stub_path)[-1]['env']
    assert not {'FOO_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_AUTH_TOKEN'} & set(env)
    assert env['CLAUDE_CONFIG_DIR'] == str(tmp_path / 'claude-config')
    response_path = Path(result['delivered'][0]['response']['path'])
    written = ''.join(p.read_text() for p in response_path.parent.iterdir()) + json.dumps(result)
    for secret in ('planted-foo-secret', 'planted-openai-secret', 'planted-anthropic-secret'):
        assert secret not in written
    response = read_json(response_path)
    assert response['schema_version'] == 3 and 'CLAUDE_CONFIG_DIR' in response['isolation']['env_names']
    assert 'FOO_API_KEY' not in response['isolation']['env_names']


def test_reported_user_configuration_is_recorded_and_not_independent(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}', 'report_user_config': True})
    answer = cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert answer['isolation']['user_configuration_loaded'] is True
    packet, _ = role_packet(tmp_path / 'critic', 'critic', {'x': 1})
    root = tmp_path / 'graph'
    graph.create(root, spec([external_node(packet, role='critic')], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    request = root / graph.status(root)['nodes']['verify']['external_request']['path']
    out = tmp_path / 'response.json'
    written = cah.answer(request, out, agent='claude', actor_id='critic-session', timeout=30)
    response = read_json(out)
    assert written['user_configuration_loaded'] is True
    assert response['user_configuration_loaded'] is True and response['fresh_context'] is False
    assert response['isolation']['basis'].startswith('user-level configuration may have been loaded')
    with pytest.raises(graph.GraphError, match='fresh context'):
        graph.deliver_external(root, 'verify', out)


def test_extra_arguments_that_reload_user_settings_are_refused(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    with pytest.raises(cah.AgentCLIError, match='--setting-sources'):
        cah.invoke('claude', PARAMETERS, {}, timeout=30, extra_args=['--setting-sources=user,project'])
    assert not (stub_path / 'calls.jsonl').exists()


def test_codex_runs_in_a_fresh_home_with_copied_login_only(stub_path, tmp_path, monkeypatch):
    install_stub(stub_path, 'codex', CODEX_STUB, {'text': '{"status": "supported"}', 'rollout_model': 'gpt-stub-served'})
    user_home = tmp_path / 'user-codex'
    user_home.mkdir()
    (user_home / 'auth.json').write_text('{"synthetic": "login"}')
    (user_home / 'AGENTS.md').write_text('user instructions')
    (user_home / 'config.toml').write_text('model_provider = "user-provider"')
    monkeypatch.setenv('CODEX_HOME', str(user_home))
    answer = cah.invoke('codex', PARAMETERS, {}, timeout=30)
    call = calls(stub_path)[-1]
    assert call['codex_home'] != str(user_home) and call['home_entries'] == ['auth.json', 'config.toml']
    assert call['auth'] == '{"synthetic": "login"}'
    assert answer['isolation']['config'] == 'fresh-home' and answer['isolation']['user_configuration_loaded'] is False
    assert answer['observed_model'] == 'gpt-stub-served' and not Path(call['codex_home']).exists()
    assert (user_home / 'config.toml').read_text() == 'model_provider = "user-provider"'


def test_antigravity_headless_answer_and_recorded_configuration(stub_path):
    install_stub(stub_path, 'agy', GOOGLE_STUB, {'text': '{"status": "request_evidence"}'})
    answer = cah.invoke('antigravity', PARAMETERS, {'evidence': [3]}, timeout=30)
    call = calls(stub_path)[-1]
    argv = call['argv']
    assert argv[0] == '-p' and 'Check the supplied covariance.' in argv[1] and call['prompt'] == ''
    assert argv[2:] == ['--output-format', 'json', '--model', 'requested-model', '--effort', 'high', '--json-schema',
                        json.dumps(SCHEMA, sort_keys=True), '--mode', 'plan', '--disable-slash-commands',
                        '--print-timeout', '25s']
    assert answer['agent'] == 'antigravity' and answer['value'] == {'status': 'request_evidence'}
    assert answer['observed_model'] == 'gemini-stub-pro' and answer['cli_session_id'] == 'google-session-7'
    assert answer['usage'] == {'input_tokens': 40, 'output_tokens': 12, 'total_tokens': 52}
    assert answer['isolation']['user_configuration_loaded'] is True
    assert answer['isolation']['transport_id'] == 'antigravity-cli-oneshot'


def test_gemini_cli_passes_only_its_declared_key(stub_path, monkeypatch):
    install_stub(stub_path, 'gemini', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    monkeypatch.setenv('GEMINI_API_KEY', 'declared-gemini-key')
    monkeypatch.setenv('FOO_API_KEY', 'planted-foo-secret')
    answer = cah.invoke('gemini', PARAMETERS, {}, timeout=30)
    call = calls(stub_path)[-1]
    assert call['env']['GEMINI_API_KEY'] == 'declared-gemini-key' and 'FOO_API_KEY' not in call['env']
    assert call['argv'][:2] == ['-p', 'Answer the request given on standard input.'] and 'covariance' in call['prompt']
    assert 'GEMINI_API_KEY' in answer['isolation']['env_names']
    assert 'declared-gemini-key' not in json.dumps(answer)


def test_auto_detects_antigravity_when_it_is_the_only_cli(stub_path, monkeypatch):
    install_stub(stub_path, 'agy', GOOGLE_STUB, {'text': '{"status": "supported"}'})
    monkeypatch.setenv('PATH', str(stub_path))
    assert cah.choose('auto') == 'antigravity'


def test_blind_role_on_cli_policy_transport_refused_before_any_process(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    assert host.transport['id'] == 'claude-cli-oneshot'
    packet, _ = role_packet(tmp_path / 'critic', 'critic', {'x': 1})
    model = node('criticize', kind='model', role='critic')
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    root = tmp_path / 'graph'
    graph.create(root, spec([model], calls=1, tokens=256))
    state = graph.execute(root, host)
    assert not state['complete']
    assert 'lacks capability blind' in json.dumps(state)
    assert not (stub_path / 'calls.jsonl').exists()


def test_command_adapter_records_transport_isolation_evidence(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}', 'report_user_config': True})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    packet, _ = role_packet(tmp_path / 'proposer', 'proposer', {'x': 1})
    model = node('propose', kind='model', role='proposer')
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    root = tmp_path / 'graph'
    graph.create(root, spec([model], calls=1, tokens=256))
    state = graph.execute(root, host)
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    assert saved['isolation']['user_configuration_loaded'] is True and saved['isolation']['independent'] is False
    assert saved['isolation']['transport_evidence']['transport_id'] == 'claude-cli-oneshot'


def test_default_agent_cli_host_config_ships_and_loads(stub_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    shipped = Path(cah.__file__).resolve().parents[1] / 'data' / 'transports' / 'hosts' / 'agent-cli.json'
    host = AgentHost.from_config(json.loads(shipped.read_text()))
    assert host.adapter == 'command' and host.command[host.command.index('--agent') + 1] == 'claude'
    assert host.transport['id'] == 'claude-cli-oneshot' and 'auto' not in host.command


# ------------------------------------------------------------ answer_graph is a map over awaiting nodes

def _three_awaiting(tmp_path):
    nodes = []
    for identity in ('verify-a', 'verify-b', 'verify-c'):
        packet, _ = role_packet(tmp_path / identity, 'proposer', {'item': identity})
        nodes.append(external_node(packet, identity=identity, role='proposer'))
    root = tmp_path / 'graph'
    graph.create(root, spec(nodes, calls=3, tokens=768))
    for identity in ('verify-a', 'verify-b', 'verify-c'):
        graph.prepare_external(root, identity)
    return root


def test_answer_graph_map_contains_a_crashed_item_and_reruns_only_it(stub_path, tmp_path, monkeypatch):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    root = _three_awaiting(tmp_path)
    real, answered, crashed = cah.answer, [], []

    def flaky(request_file, out, **options):
        answered.append(out.name)
        if 'verify-b' in out.name and not crashed:
            crashed.append(out.name)
            raise RuntimeError('synthetic crash while answering one item')
        return real(request_file, out, **options)
    monkeypatch.setattr(cah, 'answer', flaky)
    first = cah.answer_graph(root, agent='claude', actor_id='fresh-proposer', timeout=30)
    assert sorted(d['node_id'] for d in first['delivered']) == ['verify-a', 'verify-c'], first['failed']
    assert [f['node_id'] for f in first['failed']] == ['verify-b']
    assert first['items'] == [{'key': 'verify-a', 'outcome': 'ok'}, {'key': 'verify-b', 'outcome': 'failed'},
                              {'key': 'verify-c', 'outcome': 'ok'}]
    answered.clear()
    second = cah.answer_graph(root, agent='claude', actor_id='fresh-proposer', timeout=30)
    assert len(answered) == 1 and [d['node_id'] for d in second['delivered']] == ['verify-b']
    assert graph.status(root)['complete']


def test_answer_graph_join_digest_is_order_invariant(tmp_path):
    from ravel.workflow import graph_nodes
    rows = [{'key': k, 'outcome': o, 'result': {'response_sha256': k * 2}} for k, o in
            (('verify-a', 'ok'), ('verify-b', 'failed'), ('verify-c', 'ok'))]
    digests = {graph_nodes.join_sha256(order) for order in (rows, rows[::-1], [rows[1], rows[2], rows[0]])}
    assert len(digests) == 1
    concurrent = graph_nodes.map_items(['c', 'a', 'b'], str, lambda item: {'v': item}, workers=3)
    serial = graph_nodes.map_items(['a', 'b', 'c'], str, lambda item: {'v': item}, workers=1)
    assert [r['key'] for r in concurrent] == ['a', 'b', 'c']
    assert graph_nodes.join_sha256(concurrent) == graph_nodes.join_sha256(serial)
