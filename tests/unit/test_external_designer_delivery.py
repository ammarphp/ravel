"""Host-mediated planning delivery, role-named refusals and stuck-node recovery."""
import json
import subprocess
import sys

import pytest

from ravel.workflow import agent_graph as graph
from ravel.workflow.state_io import read_json
from test_agent_graph import spec, pin, external_node, external_response, role_packet


def designer_graph(tmp_path, *, calls=1, attempts=1):
    request = tmp_path / 'request.json'
    request.write_text('{"request": "plan a bounded study"}')
    designer = external_node(None, identity='plan', role='designer')
    designer['inputs'] = [pin(request, 'intake-request')]
    designer['max_attempts'] = attempts
    root = tmp_path / 'graph'
    graph.create(root, spec([designer], calls=calls, tokens=256, reworks=0))
    return root


def test_designer_accepts_host_context_and_is_labelled_not_independent(tmp_path):
    root = designer_graph(tmp_path)
    prepared = graph.prepare_external(root, 'plan')
    reply = external_response(prepared, tmp_path / 'reply.json', actor_id='host-session',
                              fresh_context=False, parent_transcript_supplied=True)
    state = graph.deliver_external(root, 'plan', reply)
    assert state['complete'] and state['nodes']['plan']['status'] == 'completed'
    saved = graph._result(root, state['nodes']['plan']['result'])
    isolation = saved['result']['isolation']
    assert isolation['fresh_context'] is False
    assert isolation['parent_transcript_supplied'] is True
    assert isolation['independence'] == 'host-designed, not independent'
    subject = graph.validate(read_json(root / graph.SPEC))['nodes'][0]['inputs'][0]['sha256']
    receipt = graph.role_receipt(root, 'plan', expected_subject_sha256=subject, allowed_roles={'designer'})
    assert receipt['role'] == 'designer'
    assert receipt['independence'] == 'host-designed, not independent'
    assert receipt['context_transport_separated'] is False
    with pytest.raises(graph.GraphError, match='allowed model role'):
        graph.model_receipt(root, 'plan', expected_subject_sha256=subject)


def test_designer_with_fresh_context_is_not_labelled_host_designed(tmp_path):
    root = designer_graph(tmp_path)
    prepared = graph.prepare_external(root, 'plan')
    graph.deliver_external(root, 'plan', external_response(prepared, tmp_path / 'reply.json'))
    saved = graph._result(root, graph.status(root)['nodes']['plan']['result'])
    assert saved['result']['isolation']['independence'] == 'fresh context attested by host'


@pytest.mark.parametrize('role', ['critic', 'verifier'])
def test_review_roles_stay_strict_and_the_error_names_the_role(tmp_path, role):
    packet, _ = role_packet(tmp_path / 'packet', role, {'quantity': 2})
    root = tmp_path / 'graph'
    graph.create(root, spec([external_node(packet, role=role)], calls=1, tokens=256))
    prepared = graph.prepare_external(root, 'verify')
    with pytest.raises(graph.GraphError, match=f'^external {role} requires an attested fresh context') as refusal:
        graph.deliver_external(root, 'verify', external_response(
            prepared, tmp_path / 'reply.json', fresh_context=False))
    assert 'reviewer' not in str(refusal.value).split(';')[0]
    assert 'release-external' in str(refusal.value)


def test_refused_delivery_keeps_the_attempt_for_a_corrected_delivery(tmp_path):
    root = designer_graph(tmp_path)
    prepared = graph.prepare_external(root, 'plan')
    before = graph.status(root)
    with pytest.raises(graph.GraphError, match='output schema'):
        graph.deliver_external(root, 'plan', external_response(prepared, tmp_path / 'bad.json', value={'status': 7}))
    after = graph.status(root)
    assert after == before
    assert after['nodes']['plan']['status'] == 'awaiting_external'
    state = graph.deliver_external(root, 'plan', external_response(prepared, tmp_path / 'good.json',
                                                                  fresh_context=False))
    assert state['complete']


def test_release_returns_a_stuck_node_to_pending_and_refunds_the_attempt(tmp_path):
    root = designer_graph(tmp_path, calls=1, attempts=1)
    first = graph.prepare_external(root, 'plan')
    state = graph.release_external(root, 'plan', reason='the host could not produce a valid response')
    node = state['nodes']['plan']
    assert node['status'] == 'pending' and node['generation_attempts'] == 0
    assert node['external_releases'] == 1
    assert state['usage'] == {'calls': 0, 'reserved_output_tokens': 0}
    released = [e for e in state['history'] if e['event'] == 'external_released']
    assert released and released[0]['reason'] == 'the host could not produce a valid response'
    call = read_json(root / 'calls' / (released[0]['call_id'] + '.json'))
    assert call['status'] == 'released' and call['release']['truth_authenticated'] is False
    second = graph.prepare_external(root, 'plan')
    assert second['request_id'] != first['request_id']
    with pytest.raises(graph.GraphError, match='different request'):
        graph.deliver_external(root, 'plan', external_response(first, tmp_path / 'stale.json'))
    state = graph.deliver_external(root, 'plan', external_response(second, tmp_path / 'fresh.json',
                                                                  fresh_context=False))
    assert state['complete']


def test_release_requires_an_awaiting_node_and_a_reason(tmp_path):
    root = designer_graph(tmp_path)
    with pytest.raises(graph.GraphError, match='awaiting_external'):
        graph.release_external(root, 'plan', reason='nothing prepared')
    graph.prepare_external(root, 'plan')
    with pytest.raises(graph.GraphError, match='reason'):
        graph.release_external(root, 'plan', reason='  ')


def test_release_is_bounded_per_node(tmp_path):
    root = designer_graph(tmp_path)
    for _ in range(graph.MAX_EXTERNAL_RELEASES):
        graph.prepare_external(root, 'plan')
        graph.release_external(root, 'plan', reason='retry the host planning call')
    graph.prepare_external(root, 'plan')
    with pytest.raises(graph.GraphError, match='release budget'):
        graph.release_external(root, 'plan', reason='one more retry')


def test_release_command_line(tmp_path):
    root = designer_graph(tmp_path)
    graph.prepare_external(root, 'plan')
    done = subprocess.run([sys.executable, '-m', 'ravel.workflow.agent_graph', 'release-external',
                           '--graph', str(root), '--node', 'plan', '--reason', 'host response unusable'],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)['nodes']['plan']['status'] == 'pending'
