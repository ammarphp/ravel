"""Root-only ordinary Host/Graph controls with inert HTTP, no model service.

The existing PNG/PDF caption controls exercise real image transport separately.
These controls authenticate exact sent text; declarations alone cannot pass.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ravel.workflow import agent_graph as graph, agent_host as host
from ravel.workflow.state_io import atomic_json
from test_provider_transport import node, install_http, VALUE
from test_visual_presentation import provider_host, response


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def role_call(tmp_path, monkeypatch, *, adapter='responses', role='proposer', deferred=False, crlf=False):
    source = tmp_path / 'phase-context.json'
    source.write_bytes(b'{"phase":"caption","full_context":"retained"}\r\n' if crlf else
                       b'{"phase":"caption","full_context":"retained"}\n')
    packet_root = tmp_path / 'packet'; packet_root.mkdir(); (packet_root / 'artifacts').mkdir()
    evidence = b'Complete source evidence\n'
    (packet_root / 'artifacts/evidence.txt').write_bytes(evidence)
    artifact = {'id':'evidence','path':'artifacts/evidence.txt','sha256':sha(evidence),
                'source_path':str((packet_root/'artifacts/evidence.txt').absolute()),'source_sha256':sha(evidence)}
    if deferred: artifact['presentation'] = 'on_demand'
    manifest = {'schema_version':1,'role':role,'artifacts':[artifact],'findings':[],'reviews':[]}
    manifest['sha256'] = graph.digest(manifest); atomic_json(packet_root / 'manifest.json', manifest)
    packet = {'path':str(packet_root),'manifest_sha256':manifest['sha256']}
    n = node(role=role, packet=packet)
    n['inputs'] = [{'id':'context','path':str(source),'sha256':sha(source.read_bytes())}]
    root = tmp_path / 'graph'
    graph.create(root, {'schema_version':1,'graph_id':'exact-sent-subject','budget':{
        'max_nodes':1,'max_calls':1,'max_output_tokens':120,'max_wall_seconds':30,'max_reworks':0},'nodes':[n]})
    seen = install_http(monkeypatch,response(adapter))
    state = graph.execute(root,provider_host(adapter))
    assert state['complete'] and state['usage'] == {'calls':1,'reserved_output_tokens':120}
    body = seen[0]['body']
    if adapter == 'responses': text = body['input'][0]['content']
    elif adapter == 'anthropic': text = body['messages'][0]['content']
    elif adapter == 'gemini': text = body['contents'][0]['parts'][0]['text']
    else: text = body['messages'][1]['content']
    return root, packet, source, artifact, json.loads(text), seen


@pytest.mark.parametrize('adapter',['responses','anthropic','gemini','chat_completions'])
def test_current_accounted_host_receipt_includes_exact_sent_input_text(tmp_path,monkeypatch,adapter):
    root,packet,source,artifact,context,seen = role_call(tmp_path,monkeypatch,adapter=adapter)
    r = graph.role_receipt(root,'role',expected_subject_sha256=sha(source.read_bytes()),
        expected_packet_sha256=packet['manifest_sha256'],require_exact_subject=True)
    presentation = r['isolation']['evidence_presentation']
    assert context['input_artifacts'][0]['content'].encode() == source.read_bytes()
    assert presentation['context_sha256'] == graph.digest(context)
    assert set(presentation['presented_subject_sha256s']) == {sha(source.read_bytes()),artifact['sha256']}
    assert len(seen)==1 and r['public_value']==VALUE and r['exact_subject_presented']
    assert not r['physics_validated'] and not r['scientific_independence_proven']


def test_blind_role_input_declaration_does_not_establish_presentation(tmp_path,monkeypatch):
    # The public Graph refuses this declaration before any Host/model call.
    # Expect the actual admission boundary, rather than bypass its blind guard.
    seen = install_http(monkeypatch,response('responses'))
    with pytest.raises(graph.GraphError,match='^blind model roles require a role packet and no extra raw inputs$'):
        role_call(tmp_path,monkeypatch,role='critic')
    assert seen == [] and not (tmp_path/'graph/graph_spec.json').exists()


def test_deferred_packet_declaration_does_not_establish_presentation(tmp_path,monkeypatch):
    root,packet,source,artifact,context,seen = role_call(tmp_path,monkeypatch,deferred=True)
    assert not context['review_packet']['artifacts']
    with pytest.raises(graph.GraphError,match='model review did not present the exact scientific subject'):
        graph.role_receipt(root,'role',expected_subject_sha256=artifact['sha256'],
            expected_packet_sha256=packet['manifest_sha256'],require_exact_subject=True)
    assert len(seen)==1


def test_normalized_input_cannot_claim_original_byte_presentation(tmp_path,monkeypatch):
    root,packet,source,artifact,context,seen = role_call(tmp_path,monkeypatch,crlf=True)
    assert context['input_artifacts'][0]['content'].encode() != source.read_bytes()
    with pytest.raises(graph.GraphError,match='model evidence presentation differs from bound packet'):
        graph.role_receipt(root,'role',expected_subject_sha256=sha(source.read_bytes()),
            expected_packet_sha256=packet['manifest_sha256'],require_exact_subject=True)
    assert len(seen)==1


def test_subject_receipt_recomputes_content_instead_of_trusting_declared_sha():
    actual = 'Actual sent text\n'; declared = sha(b'Content never sent')
    context = {'review_packet':{'manifest_sha256':'a'*64,'artifacts':[]},
        'input_artifacts':[{'id':'context','sha256':declared,'content':actual}]}
    result = {'isolation':{}}
    observed = host.AgentHost._presented_result(result,context)
    assert observed['isolation']['evidence_presentation']['presented_subject_sha256s'] == [sha(actual.encode())]
    assert declared not in observed['isolation']['evidence_presentation']['presented_subject_sha256s']
    assert result == {'isolation':{}}
