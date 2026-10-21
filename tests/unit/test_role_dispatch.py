"""Fictional dispatch requests and inert delegates; no model calls."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import agent_worker as worker, broker, gate_wiring, role_registry
from ravel.workflow.agent_host import dispatch_role
from ravel.workflow.transports import generic_delegate as delegate, host_subagent as dispatch


def spec(role='analysis-author', host='claude', attempt=1):
    card = role_registry.load(role)
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': 'fictional.build', 'attempt': attempt,
            'role': {'id': role, 'version': card['version'], 'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': ['host-subagent-' + host], 'inputs': [], 'declared_outputs': [],
            'budgets': {'max_turns': 3, 'max_wall_seconds': 30, 'max_broker_calls': 2, 'max_cost_usd': None},
            'final_record_schema': 'producer.v1', 'work_order': None, 'rdj_challenges': None,
            'parent': {'review_point_id': None, 'map_id': None, 'rca_ticket': None}}


def tool(host='claude', name='fictional_child'):
    schema = delegate.schemas()
    return {'name': name, 'inputSchema': schema['input'], 'outputSchema': schema['output'],
            '_meta': {delegate.CONTRACT_KEY: {'schema_version': 1, 'kind': 'role-dispatch-adapter',
                      'host': host, 'fresh_context': True, 'attestation': 'host_attested',
                      'isolation': 'cli-policy', 'blind_capable': False}}}


def response(request, session='fictional-child'):
    return {'session_id': session, 'request_sha256': broker.digest(request),
            'final': {'completed': True, 'summary': 'Fictional computation observed.'}, 'instructions_sha256': None}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    result = tmp_path / 'fictional-run'
    result.mkdir()
    return result


def call(run, s, **options):
    return dispatch_role(run, s, node_id=s['node_id'], role=s['role']['id'],
                         subject=dispatch.subject_for(s), **options)


@pytest.mark.parametrize('field', ['node', 'role', 'subject', 'card'])
def test_binding_mismatch_refuses_before_delegate(run, field):
    s = spec()
    args = {'node_id': s['node_id'], 'role': s['role']['id'], 'subject': dispatch.subject_for(s)}
    if field == 'card':
        s['role']['card_sha256'] = '0' * 64
    else:
        args[{'node': 'node_id', 'role': 'role', 'subject': 'subject'}[field]] = 'wrong'
    with pytest.raises(dispatch.LaunchRefused):
        dispatch_role(run, s, **args)
    assert not list(run.rglob('*.host-brief.json'))


@pytest.mark.parametrize('field', ['_meta', 'inputSchema', 'outputSchema'])
def test_generic_contract_not_tool_name(field):
    t = tool(name='any_ordinary_name')
    t.pop(field)
    with pytest.raises(dispatch.LaunchRefused):
        delegate.DelegateAdapter(t, lambda _: pytest.fail('called'))


@pytest.mark.parametrize('key,value', [('fresh_context', False), ('attestation', 'transport_verified'),
                                      ('blind_capable', True), ('isolation', 'sandbox')])
def test_host_contract_cannot_promote_its_claims(key, value):
    t = tool()
    t['_meta'][delegate.CONTRACT_KEY][key] = value
    with pytest.raises(dispatch.LaunchRefused):
        delegate.DelegateAdapter(t, lambda _: pytest.fail('called'))


def test_required_generic_delegate_refuses_without_model_call(run):
    adapter = delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    r = call(run, spec(), adapter=adapter)
    assert r['status'] == 'refused' and not r['required_role_satisfied']
    assert 'attestation' in r['missing'] and 'independence:unproven' in r['missing']
    assert not list(run.rglob('*.host-brief.json'))


@pytest.mark.parametrize('role', ['physics-critic', 'skeptical-verifier', 'physics-decider'])
def test_blind_or_voting_role_never_exposed_even_in_advisory_mode(run, role):
    adapter = delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    r = call(run, spec(role), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert r['status'] == 'refused' and 'isolation' in r['missing']
    assert not list(run.rglob('*.host-brief.json'))


@pytest.mark.parametrize('name', ['arbitrary_delegate_a', 'arbitrary_delegate_b'])
def test_advisory_generic_is_bound_labelled_and_never_a_required_receipt(run, name):
    seen = []
    def invoke(arguments):
        request = arguments['request']
        seen.append(request)
        assert request['rundir'] == str(run)
        assert request['role_card'] == role_registry.load('analysis-author')
        assert request['brief']['subject'] == request['subject']
        assert gate_wiring.admitted_work(run)
        return {'structuredContent': response(request)}
    adapter = delegate.DelegateAdapter(tool(name=name), invoke)
    s = spec()
    r = call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert r['status'] == 'advisory' and r['label'].startswith('ADVISORY')
    assert not r['required_role_satisfied'] and r['worker_receipt'] is None
    assert r['attestation'] == 'host_attested' and r['isolation']['profile'] == 'cli-policy'
    assert call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent') == r
    assert len(seen) == 1 and r['request_sha256'] == broker.digest(seen[0])
    with pytest.raises(ValueError, match='no receipt'):
        worker.load_receipt(run, s['node_id'], 1)


@pytest.mark.parametrize('bad', ['parent', 'digest', 'shape', 'error'])
def test_bad_completion_is_ambiguous_and_never_retried(run, bad):
    calls = []
    def invoke(arguments):
        calls.append(arguments)
        r = response(arguments['request'])
        if bad == 'parent': r['session_id'] = 'fictional-parent'
        if bad == 'digest': r['request_sha256'] = '0' * 64
        if bad == 'shape': del r['final']
        if bad == 'error': raise RuntimeError('sensitive provider response must not be recorded')
        return r
    adapter = delegate.DelegateAdapter(tool(), invoke)
    r = call(run, spec(), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert r['status'] == 'ambiguous' and not r['required_role_satisfied']
    assert call(run, spec(), adapter=adapter, mode='advisory', parent_session_id='fictional-parent') == r
    assert len(calls) == 1 and 'sensitive' not in json.dumps(r)


def test_child_cannot_fill_two_attempts(run):
    adapter = delegate.DelegateAdapter(tool(), lambda a: response(a['request']))
    assert call(run, spec(), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')['status'] == 'advisory'
    r = call(run, spec(attempt=2), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert r['status'] == 'ambiguous'


@pytest.mark.parametrize('host', ['claude', 'codex'])
def test_native_bridge_uses_fresh_child_and_canonical_request(run, host):
    seen = []
    def spawn(arguments):
        if host == 'codex':
            assert arguments['fork_turns'] == 'none'
            assert arguments['task_name'].startswith('ravel_')
            seen.append(json.loads(arguments['message']))
        else:
            assert arguments['subagent_type'] == 'general-purpose'
            seen.append(json.loads(arguments['prompt']))
        return 'fictional-native-child'
    def collect(child):
        assert child == 'fictional-native-child'
        return response(seen[-1], session=child)
    adapter = delegate.NativeDelegateAdapter(host, spawn, collect)
    r = call(run, spec(host=host), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert r['status'] == 'advisory' and len(seen) == 1
    assert seen[0]['role'] == 'analysis-author'


def test_unknown_delegate_is_not_a_parent_fallback(run):
    assert call(run, spec(), adapter=lambda _: {})['missing'] == ['delegate:contract']
    assert call(run, spec(attempt=2))['missing'] == ['delegate:unavailable']


def test_cli_worker_path_preserves_existing_supervisor(run, monkeypatch):
    s = spec()
    s['transport_preference'] = ['codex-cli-worker']
    seen = []
    def inert(run_arg, spec_arg, **options):
        seen.append((run_arg, spec_arg, options))
        return {'status': 'refused', 'failure': {'code': 'fictional_unavailable'}}
    monkeypatch.setattr(worker, 'dispatch', inert)
    r = call(run, s)
    assert r['status'] == 'refused' and r['worker_receipt']['failure']['code'] == 'fictional_unavailable'
    assert len(seen) == 1


def test_advisory_requires_parent_identity_and_explicit_route(run):
    adapter = delegate.DelegateAdapter(tool(host='codex'), lambda _: pytest.fail('called'))
    assert call(run, spec(), adapter=adapter, mode='advisory')['missing'] == ['transport_preference']
    adapter = delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    assert call(run, spec(attempt=2), adapter=adapter, mode='advisory')['missing'] == ['parent_session_id']


def test_subject_prefers_review_subject_and_then_work_order():
    s = spec()
    s['parent'].update({'review_point_id': 'fictional-review',
                       'review_subject': {'scope': 'fictional-value', 'sha256': 'a' * 64}})
    assert dispatch.subject_for(s) == s['parent']['review_subject']
    s['parent'].pop('review_subject')
    s['work_order'] = {'path': 'inputs/fictional-order.json', 'sha256': 'b' * 64}
    assert dispatch.subject_for(s) == {'scope': 'inputs/fictional-order.json', 'sha256': 'b' * 64}


def test_cli_rejects_missing_bindings_and_accepts_exact_public_arguments():
    parser = dispatch.dispatch_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(['dispatch', '--role', 'analysis-author'])
    args = parser.parse_args(['dispatch', '--rundir', '/fictional/run', '--node', 'fictional.build',
                              '--role', 'analysis-author', '--subject', 'subject.json', '--spec', 'spec.json'])
    assert args.node == 'fictional.build'


def test_advisory_cannot_be_upgraded_via_low_level_completion(run):
    adapter = delegate.DelegateAdapter(tool(), lambda a: response(a['request']))
    s = spec()
    assert call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent')['status'] == 'advisory'
    packet_path = worker.workspace(run, s['node_id'], 1) / 'inputs/host-brief.json'
    with pytest.raises(dispatch.LaunchRefused, match='advisory'):
        dispatch.complete(run, s, json.loads(packet_path.read_text()), final=response({})['final'])


def test_changed_packet_cannot_reuse_an_attempt(run):
    adapter = delegate.DelegateAdapter(tool(), lambda a: response(a['request']))
    s = spec()
    assert call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent')['status'] == 'advisory'
    with pytest.raises(dispatch.LaunchRefused, match='bound differently'):
        call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent', graph={'changed': True})


def test_reserved_host_attempt_is_not_invoked_again(run):
    calls = []
    def interrupted(arguments):
        calls.append(arguments)
        raise RuntimeError('fictional interrupted completion')
    adapter = delegate.DelegateAdapter(tool(), interrupted)
    s = spec()
    # Produce a real reservation identity, then emulate a host process dying
    # between reservation and completion without fabricating an accepted record.
    first = call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    target = broker.custody(run) / (worker._key(s['node_id'], 1) + '.role-dispatch.json')
    kept = json.loads(target.read_text())
    kept['result'] = None
    target.write_text(json.dumps(kept))
    second = call(run, s, adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert first['status'] == second['status'] == 'ambiguous'
    assert len(calls) == 1


def test_public_dispatch_main_returns_labelled_missing_adapter(run, capsys):
    s = spec()
    spec_path, subject_path = run / 'spec.json', run / 'subject.json'
    spec_path.write_text(json.dumps(s))
    subject_path.write_text(json.dumps(dispatch.subject_for(s)))
    code = dispatch.main(['dispatch', '--rundir', str(run), '--node', s['node_id'],
                          '--role', s['role']['id'], '--spec', str(spec_path), '--subject', str(subject_path)])
    result = json.loads(capsys.readouterr().out)
    assert code == 1 and result['status'] == 'refused'
    assert result['missing'] == ['delegate:unavailable']
    kept = json.loads(next(broker.custody(run).glob('*.role-dispatch.json')).read_text())
    assert kept['result'] == result


@pytest.mark.parametrize('metadata', [None, [], 'fictional-invalid'])
def test_invalid_metadata_is_a_named_contract_refusal(metadata):
    t = tool()
    t['_meta'] = metadata
    with pytest.raises(dispatch.LaunchRefused) as refused:
        delegate.DelegateAdapter(t, lambda _: pytest.fail('called'))
    assert refused.value.missing == ['delegate:contract']


def test_pause_refuses_host_before_any_invocation(run):
    gate_wiring.record_steering(run, 'Pause fictional work.', effect='pause')
    adapter = delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    with pytest.raises(ValueError, match='steer|pause'):
        call(run, spec(), adapter=adapter, mode='advisory', parent_session_id='fictional-parent')
    assert not list(run.rglob('*.host-brief.json'))


def test_cli_dispatch_reattaches_after_pending_and_keeps_named_refusals(run, monkeypatch):
    s = spec()
    s['transport_preference'] = ['codex-cli-worker']
    replies = iter([{'status': 'running'}, {'status': 'refused', 'failure': {'missing': ['fictional-capability']}}])
    monkeypatch.setattr(worker, 'dispatch', lambda *a, **k: next(replies))
    assert call(run, s)['status'] == 'running'
    second = call(run, s)
    assert second['status'] == 'refused' and second['missing'] == ['fictional-capability']


def test_refused_host_role_cannot_be_completed_by_parent_via_legacy_primitive(run):
    s = spec()
    adapter = delegate.DelegateAdapter(tool(), lambda _: pytest.fail('called'))
    assert call(run, s, adapter=adapter)['status'] == 'refused'
    packet = dispatch.brief(run, s, worker.materialize(run, s), transport_id='host-subagent-claude')
    with dispatch.serve_broker(run, s, packet):
        pass
    with pytest.raises(dispatch.LaunchRefused, match='refused host'):
        dispatch.complete(run, s, packet, final=response({})['final'])
    with pytest.raises(ValueError, match='no receipt'):
        worker.load_receipt(run, s['node_id'], 1)
