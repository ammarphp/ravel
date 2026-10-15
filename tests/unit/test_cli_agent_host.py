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


@pytest.mark.parametrize('agent,program,stub', [
    ('claude', 'claude', CLAUDE_STUB), ('codex', 'codex', CODEX_STUB),
    ('gemini', 'gemini', GOOGLE_STUB), ('antigravity', 'agy', GOOGLE_STUB)],
    ids=['cli-primary', 'cli-rollout', 'cli-json', 'cli-argv'])
def test_prompt_record_retains_exact_transmitted_text_and_model_fields(stub_path, agent, program, stub):
    from datetime import datetime
    from ravel.workflow import transport_receipt as receipts
    install_stub(stub_path, program, stub.replace('sys.stdin.read()', "sys.stdin.buffer.read().decode('utf-8')"),
                 {'text': '{"status": "supported"}'})
    parameters = dict(PARAMETERS, instructions='Read μ and λ.\r\nKeep trailing spaces.  \n')
    result = cah.invoke(agent, parameters, {'identifier': 'ANA-0001'}, timeout=30)
    call = calls(stub_path)[-1]
    transmitted = call['argv'][1] if agent == 'antigravity' else call['prompt']
    assert result['prompt_text'] == transmitted
    receipt = result['receipt']
    assert receipt['content']['prompt_text'] == transmitted
    assert receipts.sha256_bytes(transmitted.encode('utf-8')) == receipt['content']['prompt_sha256']
    assert datetime.fromisoformat(receipt['process']['started_utc'].replace('Z', '+00:00')).tzinfo is not None
    for record in (result, receipt['cli_reported']):
        assert record['model_requested'] == parameters['model']
        assert record['model_reported'] == receipt['cli_reported']['observed_model']
        assert record['cli_version'] == 'stub-cli 1.0.0'
        assert record['model_build_exact'] is False
    assert receipt['cli_reported']['usage']['total_tokens'] > 0


@pytest.mark.parametrize('model,exact', [
    ('model-alias', False), ('model-2026-10-01', True), ('model-20261001', True),
    ('model-2026-02-30', False), ('model-1202610012', False)])
def test_prompt_record_uses_only_reported_calendar_snapshot(stub_path, model, exact):
    install_stub(stub_path, 'codex', CODEX_STUB,
                 {'text': '{"status": "supported"}', 'rollout_model': model})
    result = cah.invoke('codex', PARAMETERS, {}, timeout=30)
    assert result['model_reported'] == model
    assert result['model_build_exact'] is exact
    assert result['receipt']['cli_reported']['model_reported'] == model
    assert result['receipt']['cli_reported']['model_build_exact'] is exact


def test_prompt_record_reads_claude_response_message_model(stub_path):
    stub = CLAUDE_STUB.replace("'modelUsage': {{'claude-stub-build-1': {{'outputTokens': 15}}, 'claude-small-stub': {{'outputTokens': 2}}}}",
                              "'modelUsage': {{}}")
    stub = stub.replace('print(json.dumps(result))',
                        "print(json.dumps([{{'type': 'assistant', 'message': {{'model': 'model-20261001'}}}}, result]))")
    install_stub(stub_path, 'claude', stub, {'text': '{"status": "supported"}'})
    result = cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert result['model_reported'] == result['observed_model'] == 'model-20261001'
    assert result['model_build_exact'] is True


def test_prompt_record_ignores_placeholder_message_model(stub_path):
    # A CLI-generated message names a placeholder, not a served build; the metered model stays reported.
    stub = CLAUDE_STUB.replace('print(json.dumps(result))',
                               "print(json.dumps([{{'type': 'assistant', 'message': {{'model': '<synthetic>'}}}}, result]))")
    install_stub(stub_path, 'claude', stub, {'text': '{"status": "supported"}'})
    result = cah.invoke('claude', PARAMETERS, {}, timeout=30)
    assert result['model_reported'] == result['observed_model'] == 'claude-stub-build-1'
    assert '<synthetic>' not in result['all_models']


def test_prompt_record_refuses_oversize_text_before_spending(stub_path, monkeypatch):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    monkeypatch.setattr(cah, 'MAX_STORED_PROMPT_BYTES', 512, raising=False)
    with pytest.raises(cah.AgentCLIError, match='prompt.*bound'):
        cah.invoke('claude', dict(PARAMETERS, instructions='μ' * 512), {}, timeout=30)
    assert not (stub_path / 'calls.jsonl').exists()


def test_prompt_record_is_persisted_by_external_answer(stub_path, tmp_path):
    from ravel.workflow import transport_receipt as receipts
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    from ravel.workflow.agent_graph import digest
    request = {'kind': 'external_agent_request',
               'request': {'request_id': 'request-1'}, 'parameters': PARAMETERS, 'context': {}}
    request['sha256'] = digest(request)  # a prepared request matches its own digest
    request_path = tmp_path / 'supplied.json'
    request_path.write_text(json.dumps(request))
    out = tmp_path / 'answer.json'
    result = cah.answer(request_path, out, agent='claude', timeout=30)
    receipt = read_json(result['receipt']['path'])
    raw = out.with_name('answer.receipt.prompt.txt').read_bytes()
    assert raw == calls(stub_path)[-1]['prompt'].encode('utf-8')
    assert receipts.sha256_bytes(raw) == receipt['content']['prompt_sha256']
    assert result['prompt']['sha256'] == receipt['content']['prompt_sha256']
    assert result['model_requested'] == PARAMETERS['model']
    assert result['model_reported'] == receipt['cli_reported']['observed_model']


def test_prompt_record_survives_command_host_receipt_storage(stub_path, tmp_path):
    import io
    from types import SimpleNamespace
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    request = {'request_id': 'request-1', 'parameters': PARAMETERS, 'context': {}}
    data = json.dumps(request).encode('utf-8')
    output = io.StringIO()
    cah.serve(io.StringIO(data.decode('utf-8')), output, agent='claude', timeout=30)
    document = json.loads(output.getvalue())
    root = tmp_path / 'graph'
    # Exercise the actual verification/storage seam with inert wrapper process facts.
    saved = {'transport': {}, 'isolation': {}}
    host._session_receipt(document, data, saved, request, SimpleNamespace(root=root, attempt_id='attempt-1'),
                          SimpleNamespace(pid=123, returncode=0), output.getvalue().encode('utf-8'))
    session = saved['transport']['session_receipt']
    persisted = read_json(root / saved['transport']['session_receipt_pin']['path'])
    assert persisted == session
    receipt = persisted['launcher_receipt']
    assert receipt['content']['prompt_text'] == calls(stub_path)[-1]['prompt']
    assert receipt['cli_reported']['model_requested'] == PARAMETERS['model']


def test_prompt_record_tampering_fails_receipt_verification(stub_path):
    from ravel.workflow import transport_receipt as receipts
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    receipt = cah.invoke('claude', PARAMETERS, {}, timeout=30)['receipt']
    receipt['content']['prompt_text'] = 'changed'
    assert any('prompt' in reason for reason in receipts.verify(receipt, declaration=tr.load(cah.ONESHOT['claude'])))


def test_prompt_record_preserves_legacy_receipt_shape(stub_path):
    from ravel.workflow import transport_receipt as receipts
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    receipt = cah.invoke('claude', PARAMETERS, {}, timeout=30)['receipt']
    receipt['content'].pop('prompt_text')
    for key in ('model_requested', 'model_reported', 'model_build_exact', 'cli_version'):
        receipt['cli_reported'].pop(key)
    assert receipts.verify(receipt, declaration=tr.load(cah.ONESHOT['claude'])) == []


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


# ------------------------------------------------------------ declared project instructions

PROJECT_TEXT = 'Project rule 1: cite every number.\nProject rule 2: write plainly.\n'
RAVEL_OPENING = 'You are a fresh, independent session answering one structured request from RAVEL.'


def declared_run(tmp_path):
    """A run directory that pins a synthetic instruction document held in a separate project folder."""
    from ravel.workflow import project_instructions
    (tmp_path / 'project').mkdir()
    (tmp_path / 'run/inputs').mkdir(parents=True)
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT)
    return tmp_path / 'run', project_instructions.declare(tmp_path / 'run', tmp_path / 'project/AGENTS.md')


def test_without_a_declared_document_a_reviewer_prompt_holds_no_project_text(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    (tmp_path / 'project').mkdir()
    (tmp_path / 'run/inputs').mkdir(parents=True)
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT)  # present on disk, pinned by no run
    assert cah.run_instructions(None) is None and cah.run_instructions(tmp_path / 'run') is None
    answer = cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=cah.run_instructions(tmp_path / 'run'))
    prompt = calls(stub_path)[-1]['prompt']
    assert PROJECT_TEXT not in prompt and prompt.startswith(RAVEL_OPENING)
    assert 'project_instructions' not in answer['receipt']['configuration']
    assert 'project_instructions' not in answer['isolation'] and 'project instruction' not in answer['isolation']['basis']


@pytest.mark.parametrize('name,stub', [('claude', CLAUDE_STUB), ('codex', CODEX_STUB), ('gemini', GOOGLE_STUB)])
def test_every_cli_family_receives_the_declared_document_ahead_of_the_ravel_prompt(stub_path, tmp_path, monkeypatch,
                                                                                   name, stub):
    from ravel.workflow import project_instructions, transport_receipt
    from ravel.workflow.agent_host import _transport_isolation
    monkeypatch.setenv('GEMINI_API_KEY', 'placeholder-not-a-key')
    install_stub(stub_path, name, stub, {'text': '{"status": "supported"}'})
    run, pinned = declared_run(tmp_path)
    parameters = dict(PARAMETERS, reasoning_effort='high' if cah.EFFORTS[AGENT_OF[name]] else None)
    answer = cah.invoke(AGENT_OF[name], parameters, {'evidence': [1]}, timeout=30,
                        instructions=cah.run_instructions(run))
    call = calls(stub_path)[-1]
    prompt = call['prompt']
    assert prompt.startswith('===== PROJECT INSTRUCTIONS =====')
    assert 0 < prompt.index(PROJECT_TEXT) < prompt.index(RAVEL_OPENING) < prompt.index('Check the supplied covariance.')
    assert PROJECT_TEXT not in ' '.join(call['argv'])
    record = answer['receipt']['configuration']['project_instructions']
    assert record['sha256'] == pinned['sha256'] and record['bytes'] == len(PROJECT_TEXT.encode())
    assert record['mechanism'] == 'prompt_first_block' and record['position'] == 'before_ravel_instructions'
    assert project_instructions.receipt_problem(answer['receipt'], cah.run_instructions(run)) is None
    assert answer['receipt']['content']['prompt_sha256'] == transport_receipt.sha256_bytes(prompt.encode())
    # The isolation block says a declared document was supplied; that is not loaded user configuration.
    isolation = answer['isolation']
    assert isolation['project_instructions'] == {'sha256': pinned['sha256'], 'bytes': pinned['bytes'],
                                                 'mechanism': 'prompt_first_block'}
    assert 'one declared project instruction document; it is not user configuration' in isolation['basis']
    assert isolation['user_configuration_loaded'] is (name == 'gemini')  # unchanged by the injection
    _transport_isolation(isolation)  # the host accepts the block
    if name == 'claude':
        assert call['cwd_entries'] == []  # the working directory stays empty


def test_a_receipt_without_the_record_is_named_by_the_credit_check(stub_path, tmp_path):
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)
    bare = cah.invoke('claude', PARAMETERS, {}, timeout=30)  # the caller named no run
    assert project_instructions.receipt_problem(bare['receipt'], cah.run_instructions(run)) \
        == 'project_instructions:not-recorded'


def test_changed_document_refuses_the_reviewer_before_any_process(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)
    pinned = cah.run_instructions(run)
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT + 'Project rule 3: slipped in.\n')
    before = len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=pinned)
    assert refused.value.code == 'refused' and 'ravel project-instructions repin --rundir' in str(refused.value)
    assert (len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0) == before
    (run / 'inputs/project_instructions.json').write_text('{}')  # a pin edited by hand pins nothing
    with pytest.raises(cah.AgentCLIError, match='pin-changed'):
        cah.run_instructions(run)


def test_external_request_inside_a_declaring_run_is_answered_with_the_document_and_delivered(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, pinned = declared_run(tmp_path)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'  # the graph sits inside the run, so the pin is found from the request file
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    assert [d['node_id'] for d in result['delivered']] == ['verify'], result['failed']
    assert PROJECT_TEXT in calls(stub_path)[-1]['prompt']
    response = read_json(result['delivered'][0]['response']['path'])
    assert response['isolation']['project_instructions']['sha256'] == pinned['sha256']
    assert response['fresh_context'] is True and response['user_configuration_loaded'] is False
    receipt = read_json(Path(result['delivered'][0]['response']['path']).with_suffix('.receipt.json'))
    assert receipt['configuration']['project_instructions']['sha256'] == pinned['sha256']
    assert graph.status(root)['complete']


def test_host_config_names_the_run_and_the_wrapper_delivers_its_document(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, pinned = declared_run(tmp_path)
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120, 'rundir': str(run)})
    assert host.command[host.command.index('--rundir') + 1] == str(run)
    assert host.transport['id'] == 'claude-cli-oneshot'  # still recognised as the RAVEL launcher
    assert cah.wrapper_agent(host.command, host.environment) == 'claude'
    packet, _ = role_packet(tmp_path / 'proposer', 'proposer', {'x': 1})
    model = node('propose', kind='model', role='proposer')
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    root = tmp_path / 'graph'
    graph.create(root, spec([model], calls=1, tokens=256))
    state = graph.execute(root, host)
    assert state['complete'], state
    prompt = calls(stub_path)[-1]['prompt']
    assert prompt.startswith('===== PROJECT INSTRUCTIONS =====') and PROJECT_TEXT in prompt
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    evidence = saved['isolation']['transport_evidence']
    assert evidence['project_instructions']['sha256'] == pinned['sha256']
    assert saved['isolation']['user_configuration_loaded'] is False and saved['isolation']['independent'] is True
    record = saved['transport']['session_receipt']['launcher_receipt']['configuration']['project_instructions']
    assert record['sha256'] == pinned['sha256'] and record['mechanism'] == 'prompt_first_block'


def _model_graph(tmp_path, root, *, packet='proposer'):
    packet, sha = role_packet(tmp_path / ('packet-' + packet), 'proposer', {'x': 1})
    model = node('propose', kind='model', role='proposer')
    model.update(packet=packet, action='model', parameters=dict(PARAMETERS))
    graph.create(root, spec([model], calls=2, tokens=512))
    return packet, sha


def test_a_graph_inside_a_declaring_run_gets_the_document_without_a_configured_run(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, pinned = declared_run(tmp_path)
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    assert '--rundir' not in host.command  # the host configuration names no run
    root = run / 'graph'
    _model_graph(tmp_path, root)
    state = graph.execute(root, host)
    assert state['complete'], state
    prompt = calls(stub_path)[-1]['prompt']
    assert prompt.startswith('===== PROJECT INSTRUCTIONS =====') and PROJECT_TEXT in prompt
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    record = saved['transport']['session_receipt']['launcher_receipt']['configuration']['project_instructions']
    assert record['sha256'] == pinned['sha256']


def test_a_host_that_cannot_deliver_the_document_sends_nothing_for_a_declaring_run(stub_path, tmp_path):
    run, _ = declared_run(tmp_path)
    marker = tmp_path / 'command-ran'
    script = tmp_path / 'plain-host.py'
    script.write_text(f'import pathlib\npathlib.Path({str(marker)!r}).write_text("ran")\n')
    hosts = {'command': AgentHost(adapter='command', command=[sys.executable, str(script)]),
             'responses': AgentHost(endpoint='http://127.0.0.1:1/v1/responses', api_key='TEST-KEY')}
    for name, host in hosts.items():
        root = run / ('graph-' + name)
        _model_graph(tmp_path, root, packet=name)
        state = graph.execute(root, host)
        assert not state['complete'] and state['nodes']['propose']['status'] != 'completed', state
        assert not marker.exists()
        assert not any(read_json(p).get('status') == 'completed' for p in (root / 'calls').glob('*.json'))
    # The same plain command host runs the node of a run that declares nothing.
    (tmp_path / 'plain/inputs').mkdir(parents=True)
    _model_graph(tmp_path, tmp_path / 'plain/graph', packet='plain')
    graph.execute(tmp_path / 'plain/graph', hosts['command'])
    assert marker.exists()


def test_a_configured_run_that_differs_from_the_graph_run_is_refused(stub_path, tmp_path):
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)
    (tmp_path / 'other/inputs').mkdir(parents=True)
    (tmp_path / 'other-project').mkdir()
    (tmp_path / 'other-project/AGENTS.md').write_text('Another project rule.\n')
    project_instructions.declare(tmp_path / 'other', tmp_path / 'other-project/AGENTS.md')
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120,
                                  'rundir': str(tmp_path / 'other')})
    root = run / 'graph'
    _model_graph(tmp_path, root)
    before = len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0
    state = graph.execute(root, host)
    assert not state['complete']
    assert (len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0) == before


def test_the_relay_refuses_a_launcher_receipt_without_the_record_in_a_declaring_run(stub_path, tmp_path):
    """The session ran without the document (a launcher that was told no run): the relay gives it no credit."""
    import hashlib
    import io
    from types import SimpleNamespace
    from ravel.workflow.agent_host import HostFailure
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    root = run / 'graph'
    _model_graph(tmp_path, root)
    body = {'schema_version': 1, 'request_id': 'request-0001', 'parameters': PARAMETERS, 'context': {'x': 1}}
    data = json.dumps(body, sort_keys=True).encode()
    out = io.StringIO()
    cah.serve(io.StringIO(data.decode()), out, agent='claude', timeout=30)  # no run named: no document
    document = json.loads(out.getvalue())
    assert 'project_instructions' not in document['session_receipt']['configuration']
    result = {'transport': {}, 'isolation': {}}
    control = SimpleNamespace(root=root, attempt_id='attempt-0001')
    proc = SimpleNamespace(pid=os.getpid(), returncode=0)
    with pytest.raises(HostFailure, match='project_instructions:not-recorded'):
        host._session_receipt(document, data, result, {'request_id': 'request-0001'}, control, proc,
                              out.getvalue().encode())
    assert result['isolation'].get('independent') is not True
    # The same receipt is accepted for a graph whose run declares nothing.
    (tmp_path / 'plain/inputs').mkdir(parents=True)
    plain = SimpleNamespace(root=tmp_path / 'plain/graph', attempt_id='attempt-0001')
    (tmp_path / 'plain/graph').mkdir()
    host._session_receipt(document, data, result, {'request_id': 'request-0001'}, plain, proc, out.getvalue().encode())
    assert result['transport']['attestation'] == 'transport_attested'


def test_a_review_answered_before_the_pin_earns_no_graph_receipt(stub_path, tmp_path):
    """The shared model-receipt boundary compares the session's record with the run's declaration."""
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    (tmp_path / 'project').mkdir()
    run = tmp_path / 'run'
    (run / 'inputs').mkdir(parents=True)
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT)
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    assert [d['node_id'] for d in result['delivered']] == ['verify'], result['failed']
    kwargs = {'expected_subject_sha256': sha, 'expected_packet_sha256': packet['manifest_sha256']}
    assert graph.model_receipt(root, 'verify', **kwargs)['execution_observation'] == 'host_attested_external'
    project_instructions.declare(run, tmp_path / 'project/AGENTS.md')  # the run now declares a document
    with pytest.raises(graph.GraphError, match='project_instructions:not-recorded'):
        graph.model_receipt(root, 'verify', **kwargs)


def test_a_review_answered_under_a_replaced_pin_earns_no_graph_receipt(stub_path, tmp_path):
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, pinned = declared_run(tmp_path)
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    assert [d['node_id'] for d in result['delivered']] == ['verify'], result['failed']
    kwargs = {'expected_subject_sha256': sha, 'expected_packet_sha256': packet['manifest_sha256']}
    assert graph.model_receipt(root, 'verify', **kwargs)['isolation']['transport_evidence'][
        'project_instructions']['sha256'] == pinned['sha256']
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT + 'Project rule 3: added later.\n')
    project_instructions.repin(run, approved_by='operator-0001', statement='rule 3 added')
    with pytest.raises(graph.GraphError, match='project_instructions:other-document'):
        graph.model_receipt(root, 'verify', **kwargs)


def test_a_run_nested_under_a_declaring_run_never_receives_the_outer_document(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    outer, _ = declared_run(tmp_path)
    inner = outer / 'nested/child-run'
    (inner / 'inputs').mkdir(parents=True)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = inner / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    prepared = graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    before = len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.answer(request_file, tmp_path / 'refused.json', agent='claude', timeout=30)
    assert refused.value.code == 'refused' and 'run-ambiguous' in str(refused.value)
    assert (len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0) == before
    # Naming the run itself answers the request; it declared nothing, so no project text reaches the session.
    answered = cah.answer(request_file, tmp_path / 'answered.json', agent='claude', timeout=30, rundir=inner)
    assert PROJECT_TEXT not in calls(stub_path)[-1]['prompt']
    receipt = read_json(Path(answered['response']['path']).with_suffix('.receipt.json'))
    assert 'project_instructions' not in receipt['configuration'] and prepared


def test_a_request_copied_outside_the_run_still_carries_its_run(stub_path, tmp_path):
    """The prepared request names its run, so the document reaches the session wherever the file is answered."""
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, pinned = declared_run(tmp_path)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    assert read_json(request_file)['project_run'] == str(run.resolve())
    (tmp_path / 'elsewhere').mkdir()
    copy = tmp_path / 'elsewhere/request.json'
    copy.write_bytes(request_file.read_bytes())
    answered = cah.answer(copy, tmp_path / 'elsewhere/response.json', agent='claude', timeout=30)
    assert calls(stub_path)[-1]['prompt'].startswith('===== PROJECT INSTRUCTIONS =====')
    receipt = read_json(Path(answered['response']['path']).with_suffix('.receipt.json'))
    assert receipt['configuration']['project_instructions']['sha256'] == pinned['sha256']
    # A copy whose run was edited no longer matches its own digest: nothing is launched.
    edited = read_json(copy)
    edited['project_run'] = str(tmp_path / 'elsewhere')
    copy.write_text(json.dumps(edited))
    before = len(calls(stub_path))
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.answer(copy, tmp_path / 'elsewhere/second.json', agent='claude', timeout=30)
    assert refused.value.code == 'refused' and len(calls(stub_path)) == before
    # A run named on the command line must be the request's own run.
    copy.write_bytes(request_file.read_bytes())
    with pytest.raises(cah.AgentCLIError, match='belongs to run'):
        cah.answer(copy, tmp_path / 'elsewhere/third.json', agent='claude', timeout=30, rundir=tmp_path / 'elsewhere')
    assert len(calls(stub_path)) == before


def test_a_request_of_a_run_without_a_pin_names_no_run(stub_path, tmp_path):
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    (tmp_path / 'run/inputs').mkdir(parents=True)
    root = tmp_path / 'run/graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    assert 'project_run' not in read_json(request_file)


def _stub_calls(stub_path):
    return len(calls(stub_path)) if (stub_path / 'calls.jsonl').exists() else 0


@pytest.mark.parametrize('damage,item', [('removed', 'pin-removed'), ('edited', 'pin-changed')])
def test_preparing_a_request_under_an_invalid_pin_is_refused_not_read_as_no_declaration(stub_path, tmp_path, damage,
                                                                                         item):
    """A pin that custody knows and the run tree no longer shows is an error, never a run that declares nothing."""
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, _ = declared_run(tmp_path)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    pin_file = run / 'inputs/project_instructions.json'
    kept = pin_file.read_bytes()
    pin_file.unlink() if damage == 'removed' else pin_file.write_text('{}')
    with pytest.raises(graph.GraphError, match=item):
        graph.prepare_external(root, 'verify')
    # Nothing was prepared: no request file exists to copy out of the run and answer without the document.
    assert not list(root.glob('requests/*.json')) and graph.status(root)['nodes']['verify']['status'] == 'pending'
    pin_file.write_bytes(kept)
    graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    assert read_json(request_file)['project_run'] == str(run.resolve())


def test_a_host_that_names_the_inner_run_runs_it_and_its_review_is_credited(stub_path, tmp_path):
    """Naming the run answers the nested-run question at dispatch and again at the graph receipt."""
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    outer, _ = declared_run(tmp_path)
    inner = outer / 'nested/child-run'
    (inner / 'inputs').mkdir(parents=True)
    root = inner / 'graph'
    packet, sha = _model_graph(tmp_path, root)
    # A host that names no run is refused: the outer pin is above an inner run that pins nothing.
    unnamed = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    assert not graph.execute(root, unnamed)['complete'] and _stub_calls(stub_path) == 0
    graph.create(inner / 'graph-2', graph._load(root)[0])
    root = inner / 'graph-2'
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120, 'rundir': str(inner)})
    state = graph.execute(root, host)
    assert state['complete'], state
    assert PROJECT_TEXT not in calls(stub_path)[-1]['prompt']  # the inner run declares nothing
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    assert saved['isolation']['transport_evidence']['project_run'] == str(inner.resolve())
    assert 'project_instructions' not in saved['isolation']['transport_evidence']
    receipt = graph.role_receipt(root, 'propose', expected_subject_sha256=sha,
                                 expected_packet_sha256=packet['manifest_sha256'])
    assert receipt['node_id'] == 'propose'
    # A host configured for the outer run does not own the inner run's graph.
    graph.create(inner / 'graph-3', graph._load(root)[0])
    other = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120, 'rundir': str(outer)})
    before = _stub_calls(stub_path)
    assert not graph.execute(inner / 'graph-3', other)['complete'] and _stub_calls(stub_path) == before


def test_an_answer_that_names_the_inner_run_is_credited_at_the_graph_receipt(stub_path, tmp_path):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    outer, _ = declared_run(tmp_path)
    inner = outer / 'nested/child-run'
    (inner / 'inputs').mkdir(parents=True)
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = inner / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    # The request says that its run was not settled when it was prepared, and which run to name.
    assert read_json(request_file)['project_run_unresolved'] == str(inner.resolve())
    assert 'project_run' not in read_json(request_file)
    (tmp_path / 'elsewhere').mkdir()
    copy = tmp_path / 'elsewhere/request.json'
    copy.write_bytes(request_file.read_bytes())
    for named in (None, outer):
        with pytest.raises(cah.AgentCLIError) as refused:  # a copy outside the tree still needs the run's own name
            cah.answer(copy, tmp_path / 'elsewhere/refused.json', agent='claude', timeout=30, rundir=named)
        assert refused.value.code == 'refused' and _stub_calls(stub_path) == 0
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30, rundir=inner)
    assert [d['node_id'] for d in result['delivered']] == ['verify'], result['failed']
    assert PROJECT_TEXT not in calls(stub_path)[-1]['prompt']
    reviewed = graph.model_receipt(root, 'verify', expected_subject_sha256=sha,
                                   expected_packet_sha256=packet['manifest_sha256'])
    assert reviewed['isolation']['transport_evidence']['project_run'] == str(inner.resolve())


def test_a_pin_resolved_before_a_repin_launches_nothing(stub_path, tmp_path):
    """The one-shot launch reads the run's declaration again; a pin resolved earlier is not trusted."""
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)
    resolved = cah.run_instructions(run)
    (tmp_path / 'project/RULES.md').write_text(PROJECT_TEXT + 'Project rule 3: agreed.\n')
    # The approved re-pin names another file; the earlier file still holds the earlier bytes.
    project_instructions.repin(run, approved_by='operator-0001', statement='rule 3 was agreed',
                               path=tmp_path / 'project/RULES.md')
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=resolved)
    assert refused.value.code == 'refused' and 'project_instructions:other-document' in str(refused.value)
    assert _stub_calls(stub_path) == 0
    answer = cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=cah.run_instructions(run))
    assert 'Project rule 3: agreed.' in calls(stub_path)[-1]['prompt']
    assert answer['receipt']['configuration']['project_instructions']['sha256'] == cah.run_instructions(run)['sha256']


def test_a_document_changed_while_the_launch_is_assembled_launches_nothing(stub_path, tmp_path, monkeypatch):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    run, _ = declared_run(tmp_path)

    def version_probe_then_change(executable, env):
        # The document was delivered into the prompt already; it changes before the CLI process is created.
        (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT + 'Project rule 3: slipped in.\n')
        return 'stub 1.0'
    monkeypatch.setattr(cah, '_cli_version', version_probe_then_change)
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=cah.run_instructions(run))
    assert refused.value.code == 'refused' and 'project_instructions:changed' in str(refused.value)
    assert _stub_calls(stub_path) == 0


def test_a_run_pinned_after_the_session_was_bound_to_it_launches_nothing(stub_path, tmp_path, monkeypatch):
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    (tmp_path / 'project').mkdir()
    (tmp_path / 'run/inputs').mkdir(parents=True)
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT)

    def version_probe_then_pin(executable, env):
        project_instructions.declare(tmp_path / 'run', tmp_path / 'project/AGENTS.md')
        return 'stub 1.0'
    monkeypatch.setattr(cah, '_cli_version', version_probe_then_pin)
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.invoke('claude', PARAMETERS, {}, timeout=30, instructions=None, project_run=tmp_path / 'run')
    assert refused.value.code == 'refused' and 'project_instructions:not-recorded' in str(refused.value)
    assert _stub_calls(stub_path) == 0


def test_a_prepared_request_whose_run_was_removed_is_refused(stub_path, tmp_path):
    """Every prepared request is checked against its own digest before a session starts."""
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, _ = declared_run(tmp_path)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    request_file = root / graph.status(root)['nodes']['verify']['external_request']['path']
    (tmp_path / 'elsewhere').mkdir()
    copy = tmp_path / 'elsewhere/request.json'
    stripped = read_json(request_file)
    del stripped['project_run']  # the digest is kept as it was
    copy.write_text(json.dumps(stripped))
    with pytest.raises(cah.AgentCLIError) as refused:
        cah.answer(copy, tmp_path / 'elsewhere/response.json', agent='claude', timeout=30)
    assert refused.value.code == 'refused' and _stub_calls(stub_path) == 0


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def test_an_answered_request_keeps_its_exact_prompt_beside_the_receipt(stub_path, tmp_path):
    """A successful one-shot keeps the full prompt its receipt hashes; a later re-pin does not take it away."""
    from ravel.workflow import project_instructions
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "request_evidence"}'})
    run, _ = declared_run(tmp_path)
    packet, _ = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = run / 'graph'
    graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    graph.prepare_external(root, 'verify')
    result = cah.answer_graph(root, agent='claude', actor_id='fresh-verifier', timeout=30)
    assert [d['node_id'] for d in result['delivered']] == ['verify'], result['failed']
    receipt_file = Path(result['delivered'][0]['response']['path']).with_suffix('.receipt.json')
    kept = receipt_file.with_suffix('.prompt.txt')
    sent = calls(stub_path)[-1]['prompt']
    assert kept.read_text() == sent and sent.startswith('===== PROJECT INSTRUCTIONS =====')
    assert _sha(kept.read_text()) == read_json(receipt_file)['content']['prompt_sha256']
    (tmp_path / 'project/AGENTS.md').write_text(PROJECT_TEXT + 'Project rule 3: added later.\n')
    project_instructions.repin(run, approved_by='operator-0001', statement='rule 3 added')
    assert kept.read_text() == sent and PROJECT_TEXT in kept.read_text()


@pytest.mark.parametrize('pinned', [True, False])
def test_a_relayed_session_keeps_its_exact_prompt_beside_the_session_record(stub_path, tmp_path, pinned):
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    if pinned:
        run, _ = declared_run(tmp_path)
    else:
        run = tmp_path / 'run'
        (run / 'inputs').mkdir(parents=True)
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    root = run / 'graph'
    _model_graph(tmp_path, root)
    state = graph.execute(root, host)
    assert state['complete'], state
    saved = graph._result(root, state['nodes']['propose']['result'])['result']
    record_file = root / saved['transport']['session_receipt_pin']['path']
    kept = record_file.with_suffix('.prompt.txt')
    sent = calls(stub_path)[-1]['prompt']
    assert kept.read_text() == sent and sent.startswith('===== PROJECT INSTRUCTIONS =====') is pinned
    assert _sha(sent) == saved['transport']['session_receipt']['launcher_receipt']['content']['prompt_sha256']


def test_a_session_record_without_a_rebuildable_request_is_still_credited(stub_path, tmp_path):
    """Keeping the prompt never decides credit: a request that is not {parameters, context} keeps none."""
    import io
    from types import SimpleNamespace
    install_stub(stub_path, 'claude', CLAUDE_STUB, {'text': '{"status": "supported"}'})
    data = json.dumps({'request_id': 'request-0001'}).encode()
    answer = cah.invoke('claude', PARAMETERS, {'x': 1}, timeout=30,
                        request_sha256=__import__('hashlib').sha256(data).hexdigest())
    host = AgentHost.from_config({'type': 'agent-cli', 'agent': 'claude', 'timeout_seconds': 120})
    (tmp_path / 'graph').mkdir()
    result = {'transport': {}, 'isolation': {}}
    host._session_receipt({'session_receipt': answer['receipt'], 'value': answer['value']}, data, result,
                          {'request_id': 'request-0001'}, SimpleNamespace(root=tmp_path / 'graph', attempt_id='a1'),
                          SimpleNamespace(pid=os.getpid(), returncode=0), b'synthetic envelope')
    assert result['transport']['attestation'] == 'transport_attested'
    assert not list((tmp_path / 'graph/transport-receipts').glob('*.prompt.txt'))
