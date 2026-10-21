"""Executed low-level admission controls with inert calls and process-owned scope."""
import sys
from types import SimpleNamespace

import pytest

from ravel.validation import check_agent_paths
from ravel.workflow import agent_tripwire, cli_agent_host, effect_ledger, graph_nodes, provider_transport


LAYERS = ('provider_transport.request', 'cli_agent_host.launch', 'effect_ledger.call')


def invoke_layer(layer, root):
    """Exercise a real boundary without a provider connection or scientific program."""
    if layer == 'provider_transport.request':
        body, path = provider_transport.request(
            'chat_completions', {'model': 'fixture-model', 'max_output_tokens': 16,
                                 'reasoning_effort': None, 'instructions': 'Return the public record.'},
            'synthetic context', {'type': 'object'},
            {'max_context_bytes': 1024, 'max_output_tokens': 16, 'reasoning_efforts': [],
             'token_limit_field': 'max_tokens', 'output_mode': 'tool_call'},
            SimpleNamespace(path='/v1/messages'), 'public', [])
        assert body['model'] == 'fixture-model' and path == '/v1/messages'
    elif layer == 'cli_agent_host.launch':
        out, facts = cli_agent_host._run([sys.executable, '-I', '-S', '-B', '-c', 'print("inert")'], '',
                                       cwd=root, env={'PATH': '/usr/bin:/bin'}, timeout=10)
        assert out.strip() == 'inert' and facts['exit_status'] == 0
    else:
        result = effect_ledger.call(root, graph={'id': 'fixture.graph', 'version': 1}, path='fixture-call',
                                    kind='model', identity={'input': 'synthetic'}, provisioning={},
                                    function=lambda: {'observed': True})
        assert result == {'observed': True}


@pytest.mark.parametrize('layer', LAYERS)
def test_lowest_layers_assert_substrate_context(tmp_path, monkeypatch, layer):
    monkeypatch.setenv(agent_tripwire.ENV, '0')
    token = graph_nodes.TRIPWIRE.set(None)
    try:
        with agent_tripwire.controller_scope('fixture-run'):
            before = len(agent_tripwire.OBSERVED)
            with pytest.raises(agent_tripwire.TripwireViolation, match=layer):
                invoke_layer(layer, tmp_path)
            verdict = agent_tripwire.OBSERVED[before:]
            assert len(verdict) == 1 and verdict[0]['reason'] == 'no_substrate_context'
            assert verdict[0]['requested_mode'] == '0' and verdict[0]['mode'] == 'block'
            assert list(tmp_path.iterdir()) == []
            gate = graph_nodes.TRIPWIRE.set({'ravel_kind': 'gate', 'graph_id': 'fixture.graph', 'node': 'gate'})
            try:
                with pytest.raises(agent_tripwire.TripwireViolation, match='kind gate may not reach'):
                    invoke_layer(layer, tmp_path)
            finally:
                graph_nodes.TRIPWIRE.reset(gate)
            allowed = graph_nodes.TRIPWIRE.set({'ravel_kind': 'agent', 'graph_id': 'fixture.graph', 'node': 'actor'})
            try:
                invoke_layer(layer, tmp_path)
                assert agent_tripwire.OBSERVED[-1]['ok'] is True
            finally:
                graph_nodes.TRIPWIRE.reset(allowed)
    finally:
        graph_nodes.TRIPWIRE.reset(token)
    assert not agent_tripwire.controller_process()


def test_tripwire_coverage_has_no_missing_layer():
    assert check_agent_paths.tripwire_coverage()['missing'] == []


@pytest.mark.parametrize('layer', LAYERS)
def test_unrestricted_calls_remain_available_with_the_tripwire_off(tmp_path, monkeypatch, layer):
    monkeypatch.setenv(agent_tripwire.ENV, '0')
    token = graph_nodes.TRIPWIRE.set(None)
    try:
        invoke_layer(layer, tmp_path)
    finally:
        graph_nodes.TRIPWIRE.reset(token)
