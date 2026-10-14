"""Actual dispatch/crash controls for advisory graph custody and shared budgets."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from ravel.workflow import agent_graph as graph
from ravel.workflow.state_io import atomic_json, read_json


def node(identity, depends=(), inputs=(), *, kind='tool', role='executor', attempts=1):
    return {'id': identity, 'kind': kind, 'role': role, 'depends_on': list(depends),
            'inputs': list(inputs), 'packet': None, 'action': 'fixture',
            'parameters': {}, 'max_attempts': attempts}


def spec(nodes, *, calls=30, tokens=1000, reworks=3):
    return {'schema_version': 1, 'graph_id': 'test-science',
            'budget': {'max_nodes': 32, 'max_calls': calls, 'max_output_tokens': tokens,
                       'max_wall_seconds': 3600, 'max_reworks': reworks}, 'nodes': nodes}


def pin(path, identity='data'):
    return {'id': identity, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class Host:
    identity = {'test_fixture': 'counted-advisory-host-v1'}

    def __init__(self, operation=None):
        self.dispatched = []
        self.requests = []
        self.operation = operation

    def execute(self, item, request, control):
        self.requests.append(request)
        def dispatch():
            self.dispatched.append(item['id'])
            return self.operation(item, request, control) if self.operation else {'public': item['id']}
        return control.call('fixture', item['kind'], request, dispatch,
                            output_tokens=64 if item['kind'] == 'model' else 0)


def test_executes_ready_graph_and_reuses_current_receipts_without_peer_payload(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([node('proposal'), node('critic', ['proposal']), node('synthesis', ['critic'])]))
    host = Host()
    state = graph.execute(root, host, workers=2)
    assert state['complete'] and host.dispatched == ['proposal', 'critic', 'synthesis']
    assert state['usage']['calls'] == 3 and state['execution_authorized'] is False
    critique = next(r for r in host.requests if r['node_id'] == 'critic')
    assert critique['dependencies'][0]['node_id'] == 'proposal'
    assert set(critique['dependencies'][0]) == {'node_id', 'result_sha256'}
    assert 'public' not in json.dumps(critique)
    graph.execute(root, host)
    assert host.dispatched == ['proposal', 'critic', 'synthesis']


def test_changed_evidence_is_refused_then_only_affected_slice_recomputed(tmp_path):
    data = tmp_path / 'case.json'; data.write_text('{"measurement": 1}')
    root = tmp_path / 'graph'
    plan = spec([node('case', inputs=[pin(data)]), node('verify', ['case']), node('unrelated')])
    graph.create(root, plan); host = Host(); graph.execute(root, host)
    data.write_text('{"measurement": 2}')
    with pytest.raises(graph.GraphError, match='artifact changed'):
        graph.execute(root, host)
    newer = deepcopy(plan); newer['nodes'][0]['inputs'] = [pin(data)]
    revised = graph.revise(root, newer, reason='new measured artifact')
    assert revised['nodes']['unrelated']['status'] == 'completed'
    assert revised['nodes']['case']['status'] == revised['nodes']['verify']['status'] == 'pending'
    graph.execute(root, host)
    assert host.dispatched.count('unrelated') == 1
    assert host.dispatched.count('case') == host.dispatched.count('verify') == 2
    assert graph.status(root)['usage']['calls'] == 5
    assert len(list((root / 'specs').glob('*.json'))) == 2


def test_rework_retains_all_spent_calls_and_requires_fresh_generation(tmp_path):
    root = tmp_path / 'graph'; graph.create(root, spec([node('repair'), node('verify', ['repair'])], calls=3))
    host = Host(); graph.execute(root, host)
    old = graph.status(root)['nodes']['verify']['result']['binding_sha256']
    graph.rework(root, ['repair'], reason='skeptical verifier requests another check')
    state = graph.execute(root, host)
    assert state['usage']['calls'] == 3
    assert state['nodes']['repair']['status'] == 'completed'
    assert state['nodes']['verify']['status'] == 'failed'
    assert 'budget' in state['nodes']['verify']['error']['message']
    assert old != state['nodes']['repair']['result']['binding_sha256']


def test_shared_call_and_output_reservations_enforced_before_parallel_dispatch(tmp_path):
    root = tmp_path / 'graph'
    graph.create(root, spec([node(str(i), kind='model', role='proposer') for i in range(4)], calls=4, tokens=128))
    host = Host(); state = graph.execute(root, host, workers=4)
    assert len(host.dispatched) == 2 and state['usage'] == {'calls': 2, 'reserved_output_tokens': 128}
    assert sum(v['status'] == 'failed' for v in state['nodes'].values()) == 2


def test_retry_is_explicit_bounded_and_not_reset_by_restart(tmp_path):
    class Transient(RuntimeError):
        retryable = True
        not_dispatched = True  # a definite outage is typed; an untyped raise stays ambiguous
    root = tmp_path / 'graph'; graph.create(root, spec([node('tool', attempts=3)], calls=2))
    host = Host(lambda *args: (_ for _ in ()).throw(Transient('definite outage')))
    state = graph.execute(root, host)
    assert len(host.dispatched) == 2 and state['usage']['calls'] == 2
    assert state['nodes']['tool']['attempts'] == 3  # third cannot dispatch at exhausted graph budget
    assert not state['complete'] and state['nodes']['tool']['retryable'] is False
    graph.execute(root, host)
    assert len(host.dispatched) == 2


def test_cancel_fences_late_result_and_resume_keeps_budget(tmp_path):
    root = tmp_path / 'graph'; graph.create(root, spec([node('one'), node('two', ['one'])]))
    host = Host(lambda item, request, control: (graph.cancel(root, reason='stop work'), {'late': True})[1])
    state = graph.execute(root, host)
    assert state['cancelled'] and not state['complete']
    assert state['nodes']['one']['status'] == 'cancelled'
    assert state['nodes']['two']['status'] == 'pending'
    assert state['usage']['calls'] == 1
    graph.resume(root)
    host.operation = None
    state = graph.execute(root, host)
    assert state['complete'] and state['usage']['calls'] == 2
    assert host.dispatched == ['one', 'two']  # one reused its persisted late response only after explicit resume


def test_host_identity_and_result_mutation_fail_closed(tmp_path):
    root = tmp_path / 'graph'; graph.create(root, spec([node('check')]))
    host = Host(); graph.execute(root, host)
    retained = graph.status(root)
    requests, dispatched = list(host.requests), list(host.dispatched)
    host.identity = {'test_fixture': 'different host source'}
    with pytest.raises(graph.GraphError, match='^completed generation source/request/host differs; explicit rework required$') as refusal:
        graph.execute(root, host)
    assert str(refusal.value) == 'completed generation source/request/host differs; explicit rework required'
    assert graph.status(root) == retained
    assert host.requests == requests and host.dispatched == dispatched
    ref = graph.status(root)['nodes']['check']['result']
    artifact = root / ref['path']; receipt = read_json(artifact)
    receipt['result']['public'] = 'forged'; atomic_json(artifact, receipt)
    with pytest.raises(graph.GraphError, match='receipt changed'):
        graph.status(root)


@pytest.mark.parametrize('bad', ['cycle', 'missing', 'self', 'budget', 'blind'])
def test_invalid_graph_is_rejected_before_any_dispatch(tmp_path, bad):
    plan = spec([node('a'), node('b', ['a'])])
    if bad == 'cycle': plan['nodes'][0]['depends_on'] = ['b']
    if bad == 'missing': plan['nodes'][1]['depends_on'] = ['absent']
    if bad == 'self': plan['nodes'][0]['depends_on'] = ['a']
    if bad == 'budget': plan['budget']['max_calls'] = True
    if bad == 'blind': plan['nodes'][1].update(kind='model', role='critic')
    with pytest.raises(graph.GraphError): graph.create(tmp_path / 'graph', plan)
    assert not (tmp_path / 'graph').exists()


def test_revision_cannot_erase_budget_or_unreconciled_effect(tmp_path):
    root = tmp_path / 'graph'; plan = spec([node('a')]); graph.create(root, plan)
    newer = deepcopy(plan); newer['budget']['max_calls'] += 1
    with pytest.raises(graph.GraphError, match='budget'): graph.revise(root, newer, reason='reset budget')
    state = read_json(root / graph.STATE); state['nodes']['a']['status'] = 'ambiguous'
    atomic_json(root / graph.STATE, state)
    with pytest.raises(graph.GraphError, match='ambiguous'): graph.rework(root, ['a'], reason='hide unknown effect')


@pytest.mark.parametrize('window,expected', [('before-effect', 0), ('after-effect', 1), ('after-receipt', 1)])
def test_actual_subprocess_crash_and_restart_never_blindly_repeats_effect(tmp_path, window, expected):
    root = tmp_path / 'graph'; graph.create(root, spec([node('effect')]))
    helper = tmp_path / 'child.py'
    helper.write_text(textwrap.dedent('''
        import os, sys
        from pathlib import Path
        from ravel.workflow import agent_graph as graph
        from ravel.workflow.state_io import atomic_json, read_json
        root, window = Path(sys.argv[1]), sys.argv[2]
        class Host:
            identity = {'fixture': 'stable tiny process effect'}
            def execute(self, node, request, control):
                def effect():
                    if window == 'before-effect': os._exit(31)
                    path = root / 'counter.json'
                    old = read_json(path)['count'] if path.exists() else 0
                    atomic_json(path, {'count': old + 1})
                    if window == 'after-effect': os._exit(32)
                    return {'count': old + 1}
                result = control.call('count', 'tool', request, effect)
                if window == 'after-receipt': os._exit(33)
                return result
        graph.execute(root, Host())
    '''))
    first = subprocess.run([sys.executable, str(helper), str(root), window], check=False)
    assert first.returncode in {31, 32, 33}
    resumed = subprocess.run([sys.executable, str(helper), str(root), 'resume'], check=False)
    assert resumed.returncode == 0
    count = read_json(root / 'counter.json')['count'] if (root / 'counter.json').exists() else 0
    assert count == expected
    state = graph.status(root)
    assert state['usage']['calls'] == 1
    if window == 'after-receipt': assert state['complete']
    else: assert state['nodes']['effect']['status'] == 'ambiguous' and not state['complete']


def role_packet(root, role, subject):
    root.mkdir(); (root / 'artifacts').mkdir()
    raw = json.dumps(subject, sort_keys=True).encode()
    (root / 'artifacts' / 'evidence.json').write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    manifest = {'schema_version': 1, 'role': role, 'artifacts': [{
        'id': 'evidence', 'path': 'artifacts/evidence.json', 'sha256': sha,
        'source_path': str(root / 'artifacts' / 'evidence.json'),
        'source_sha256': sha, 'projection': 'public tiny covariance control'}],
        'findings': [], 'reviews': []}
    manifest['sha256'] = graph.digest(manifest)
    atomic_json(root / 'manifest.json', manifest)
    return {'path': str(root), 'manifest_sha256': manifest['sha256']}, sha


def external_node(packet, *, identity='verify', role='verifier'):
    n = node(identity, kind='model', role=role)
    n.update(packet=packet, action='external', parameters={
        'instructions': 'Check only the supplied public scientific evidence and return its disposition.',
        'model': 'test-external-model', 'reasoning_effort': 'high', 'max_output_tokens': 256,
        'output_schema': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['request_evidence', 'supported']}},
                          'required': ['status'], 'additionalProperties': False}})
    return n


def external_response(prepared, path, **updates):
    value = {'schema_version': 1, 'request_id': prepared['request_id'],
             'request_sha256': prepared['request_sha256'], 'invocation_id': 'fixture-live-host-invocation',
             'actor_id': 'fresh-verifier', 'observed_model': 'test-external-model',
             'fresh_context': True, 'parent_transcript_supplied': False,
             'value': {'status': 'request_evidence'}}
    value.update(updates); atomic_json(path, value)
    return path


def test_external_budget_reserved_before_dispatch_and_exact_response_receipt(tmp_path):
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'covariance': [[1, 0], [0, 1]]})
    root = tmp_path / 'graph'; graph.create(root, spec([external_node(packet)], calls=1, tokens=256))
    prepared = graph.prepare_external(root, 'verify')
    state = graph.status(root)
    assert not prepared['model_executed'] and state['nodes']['verify']['status'] == 'awaiting_external'
    assert state['usage'] == {'calls': 1, 'reserved_output_tokens': 256}
    doc = read_json(prepared['request_file'])
    assert doc['context']['review_packet']['manifest_sha256'] == packet['manifest_sha256']
    assert 'dependencies' not in doc['context']  # scheduling hashes aren't peer narratives
    with pytest.raises(graph.GraphError, match='different request'):
        graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'wrong.json', request_id='wrong'))
    state = graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'response.json'))
    assert state['complete'] and state['usage']['calls'] == 1
    reviewed = graph.model_receipt(root, 'verify', expected_subject_sha256=sha,
                                   expected_packet_sha256=packet['manifest_sha256'])
    assert reviewed['execution_observation'] == 'host_attested_external'
    assert reviewed['context_transport_separated'] and not reviewed['actor_identity_authenticated']
    assert reviewed['exact_subject_presented'] and reviewed['presented_subject_sha256s'] == [sha]
    assert reviewed['public_value'] == {'status': 'request_evidence'}
    assert reviewed['transport']['inference_token_ceiling_enforced'] is False
    with pytest.raises(graph.GraphError, match='expected scientific subject'):
        graph.model_receipt(root, 'verify', expected_subject_sha256='c'*64)
    with pytest.raises(graph.GraphError, match='not awaiting'):
        graph.deliver_external(root, 'verify', tmp_path / 'response.json')


def test_review_projection_provenance_does_not_prove_exact_subject_presentation(tmp_path):
    packet, projected_sha = role_packet(tmp_path / 'verifier', 'verifier', {'subset': 'public projection'})
    manifest_path = Path(packet['path']) / 'manifest.json'
    manifest = read_json(manifest_path)
    original_subject_sha = hashlib.sha256(b'full subject not presented').hexdigest()
    original = tmp_path / 'full-original-subject.txt'
    original.write_bytes(b'full subject not presented')
    manifest['artifacts'][0]['source_path'] = str(original)
    manifest['artifacts'][0]['source_sha256'] = original_subject_sha
    manifest.pop('sha256')
    manifest['sha256'] = graph.digest(manifest)
    atomic_json(manifest_path, manifest)
    packet['manifest_sha256'] = manifest['sha256']
    root = tmp_path / 'graph'; graph.create(root, spec([external_node(packet)]))
    prepared = graph.prepare_external(root, 'verify')
    graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'response.json'))
    receipt = graph.model_receipt(root, 'verify', expected_subject_sha256=original_subject_sha)
    assert not receipt['exact_subject_presented']
    assert receipt['presented_subject_sha256s'] == [projected_sha]
    with pytest.raises(graph.GraphError, match='did not present the exact'):
        graph.model_receipt(root, 'verify', expected_subject_sha256=original_subject_sha,
                            require_exact_subject=True)
    assert graph.model_receipt(root, 'verify', expected_subject_sha256=projected_sha,
                               require_exact_subject=True)['exact_subject_presented']


def test_external_delivery_cannot_hide_parent_context_private_data_or_schema_fault(tmp_path):
    packet, _ = role_packet(tmp_path / 'critic', 'critic', {'observed': 3})
    root = tmp_path / 'graph'; graph.create(root, spec([external_node(packet, role='critic')]))
    prepared = graph.prepare_external(root, 'verify')
    retained = graph.status(root)
    with pytest.raises(graph.GraphError, match='^external critic requires an attested fresh context without parent transcript;') as refusal:
        graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'parent.json', parent_transcript_supplied=True))
    assert 'release-external' in str(refusal.value)
    assert graph.status(root) == retained
    from ravel.workflow.agent_host import HostFailure
    with pytest.raises(graph.GraphError, match='^private reasoning fields are not public records$') as refusal:
        graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'private.json', value={'private_reasoning': 'forbidden'}))
    assert isinstance(refusal.value.__cause__, HostFailure)
    assert str(refusal.value.__cause__) == 'private reasoning fields are not public records'
    assert graph.status(root) == retained
    with pytest.raises(graph.GraphError, match='^public JSON does not match output schema$') as refusal:
        graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'bad-schema.json', value={'status': 1}))
    assert isinstance(refusal.value.__cause__, HostFailure)
    assert str(refusal.value.__cause__) == 'public JSON does not match output schema'
    assert graph.status(root) == retained
    assert graph.status(root)['nodes']['verify']['status'] == 'awaiting_external'


def test_external_cancel_fences_delivery_and_requires_explicit_resume(tmp_path):
    packet, sha = role_packet(tmp_path / 'verifier', 'verifier', {'observed': 3})
    root = tmp_path / 'graph'; graph.create(root, spec([external_node(packet)]))
    prepared = graph.prepare_external(root, 'verify')
    graph.cancel(root, reason='cancel while external host is working')
    state = graph.deliver_external(root, 'verify', external_response(prepared, tmp_path / 'late.json'))
    assert state['nodes']['verify']['status'] == 'cancelled' and not state['complete']
    with pytest.raises(graph.GraphError, match='cancelled graph'):
        graph.model_receipt(root, 'verify', expected_subject_sha256=sha)
    state = graph.resume(root)
    assert state['nodes']['verify']['status'] == 'completed' and state['complete']
    assert state['usage']['calls'] == 1


def test_host_cannot_complete_node_with_unaccounted_prose_profile(tmp_path):
    class Profile:
        identity = {'fixture': 'prose profile, no invocation'}
        def execute(self, node, request, control):
            return {'kind': 'model_result', 'value': {'status': 'supported'}}
    root = tmp_path / 'graph'; graph.create(root, spec([node('a')]))
    state = graph.execute(root, Profile())
    assert not state['complete'] and state['usage']['calls'] == 0
    assert 'no accounted' in state['nodes']['a']['error']['message']


def test_ambiguous_effect_requires_explicit_pinned_reconciliation_and_keeps_cost(tmp_path):
    class Unknown(RuntimeError):
        ambiguous = True
    root = tmp_path / 'graph'; graph.create(root, spec([node('effect')]))
    host = Host(lambda *args: (_ for _ in ()).throw(Unknown('effect outcome unavailable')))
    state = graph.execute(root, host)
    call_id = next(iter(state['calls']))
    evidence = tmp_path / 'observed.json'; evidence.write_text('{"external_observation": "effect completed"}')
    with pytest.raises(graph.GraphError, match='external evidence'):
        graph.reconcile(root, call_id, outcome='completed', result={'public': 'receipted outcome'}, evidence=[], reason='trust prose')
    graph.reconcile(root, call_id, outcome='completed', result={'public': 'receipted outcome'},
                    evidence=[pin(evidence)], reason='inspected explicit external outcome')
    host.operation = None
    state = graph.execute(root, host)
    assert state['complete'] and state['usage']['calls'] == 1 and host.dispatched == ['effect']
    with pytest.raises(graph.GraphError, match='started/ambiguous'):
        graph.reconcile(root, call_id, outcome='failed', evidence=[pin(evidence)], reason='overwrite completion')
