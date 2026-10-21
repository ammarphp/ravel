"""The default independence resolver reads only what RAVEL's dispatchers recorded.

Workers run through the real launch and supervise path with inert seams; graph roles run
through the graph runner with an inert transport. A receipt and registration written by hand,
a host completion, a weak observation, a control transport, a missing projection and a lost
record earn no credit. Fictional runs and plans only: no model, network or native call.
"""
import hashlib
import json

import pytest

from ravel.workflow import (agent_graph, agent_worker as worker, rdj_custody, review_dispatch,
                            review_independence as ri, review_points as rp, scientific_judgment)
from test_physics_review import run, opened  # noqa: F401
from test_review_actor_identity import CLAIM, CRITIC, SPECIALIST, FINAL, review_spec
from test_review_points import receipt, run as point_run
from test_scientific_judgment import prepare, FakeHost, observed_role_boundary  # noqa: F401
from worker_supervision import review_packet, supervised


@pytest.fixture
def study(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = tmp_path / 'study'
    root.mkdir()
    point_run(root, claims=[CLAIM])
    return root


def record(root, node):
    return next(r for r in rp._receipt_records(root, rp._facts(root)) if r['node_id'] == node)


def query(root, node, point_id):
    rec = record(root, node)
    point = next(p for p in rp.derive(rp._facts(root)) if p['id'] == point_id)
    sha = hashlib.sha256((root / rec['_path']).read_bytes()).hexdigest()
    return ri.worker_query(root, rec, sha, subject_sha256=rp.review_subject(rp._facts(root), point)['sha256'])


def dispatched(root, node, point_id, role, *, session=None, packet=True, **options):
    s = review_spec(root, node, point_id, role)
    return supervised(root, s, final=FINAL, session=session or 'session-' + node,
                      **({'packet': review_packet(root, point_id, role)} if packet else {}), **options)


# ---------------------------------------------------------------- worker route

def test_a_supervised_review_with_its_projection_is_credited_from_launch_custody(study):
    done = dispatched(study, 'specialist', SPECIALIST, 'discrepancy-attributor')
    assert done['status'] == 'ok' and done['attestation'] == 'transport_attested'
    proof = review_dispatch.lookup(query(study, 'specialist', SPECIALIST))
    assert proof['context_id'] == 'worker-session:synthetic-cli:session-specialist'
    assert proof['packet']['builder'] == review_dispatch.PROJECTION and proof['read_boundary'] == 'packet_only'
    assert proof['exposure']['author_rationale'] == 'withheld'
    assert ri.decide(query(study, 'specialist', SPECIALIST))['independent']
    assert rp._receipt_report(record(study, 'specialist'))['independent'] and rp.satisfied(study, SPECIALIST)
    # An installed controller replaces the default for its scope only.
    with ri.authority_session(lambda _: None):
        assert not rp.satisfied(study, SPECIALIST)
    assert rp.satisfied(study, SPECIALIST)


def test_a_receipt_and_registration_written_by_hand_earn_no_credit(study):
    receipt(study, SPECIALIST, 'discrepancy-attributor')
    rec = record(study, 'discrepancy-attributor1')
    assert rec['_label'] == 'transport_attested' and rec['_actor'] is not None
    assert rec['_independence']['advisory'] == 'trusted_dispatch_missing_or_changed'
    assert not rp.satisfied(study, SPECIALIST)


def test_a_review_without_the_ravel_projection_is_advice(study):
    dispatched(study, 'bare', SPECIALIST, 'discrepancy-attributor', packet=False)
    assert not ri.decide(query(study, 'bare', SPECIALIST))['independent']
    assert not rp.satisfied(study, SPECIALIST)


def test_an_input_beside_the_projection_is_possible_author_framing(study):
    (study / 'inputs/author-summary.md').write_text('The author says the result is correct.\n')
    s = review_spec(study, 'framed', SPECIALIST, 'discrepancy-attributor')
    pin = {'path': 'inputs/author-summary.md',
           'sha256': hashlib.sha256((study / 'inputs/author-summary.md').read_bytes()).hexdigest()}
    s['inputs'] = [{'pin': pin, 'as': 'inputs/summary.md'}]
    supervised(study, s, final=FINAL, session='session-framed',
               packet=review_packet(study, SPECIALIST, 'discrepancy-attributor'))
    assert not ri.decide(query(study, 'framed', SPECIALIST))['independent']


def test_a_weak_observation_or_unconfirmed_sandbox_is_advice(study):
    dispatched(study, 'weak', CRITIC, 'physics-critic', attestation='host_attested')
    assert not ri.decide(query(study, 'weak', CRITIC))['independent']
    unconfirmed = {'isolation': {'profile': 'ravel-sandbox', 'user_configuration_loaded': False,
                                 'evidence': {'confirmed': False}}}
    dispatched(study, 'open', SPECIALIST, 'discrepancy-attributor', observed=unconfirmed)
    assert not ri.decide(query(study, 'open', SPECIALIST))['independent']


def test_a_host_completion_without_a_supervised_launch_is_advice(study):
    s = review_spec(study, 'host-done', SPECIALIST, 'discrepancy-attributor')
    worker.materialize(study, s, packet=review_packet(study, SPECIALIST, 'discrepancy-attributor'))
    worker.bind_actor(study, 'host-done', 1, transport_id='synthetic-cli', model_id='synthetic-model')
    worker.finish(study, s, final=FINAL, execution={
        'exit_status': 0, 'session_id': 'host-session', 'attestation': 'transport_attested',
        'transport': {'id': 'synthetic-cli', 'transport_kind': 'cli-worker', 'declaration_sha256': None,
                      'probe_sha256': None},
        'isolation': {'profile': 'ravel-sandbox', 'user_configuration_loaded': False, 'evidence': {'confirmed': True}}})
    assert not ri.decide(query(study, 'host-done', SPECIALIST))['independent']


def test_a_changed_review_output_withdraws_the_credit(study):
    dispatched(study, 'changed', SPECIALIST, 'discrepancy-attributor')
    before = query(study, 'changed', SPECIALIST)
    assert ri.decide(before)['independent']
    final = study / 'agent-work/changed/1/final.json'
    final.write_text(json.dumps({**FINAL, 'disposition': 'not_supported'}))
    assert ri.decide(before)['advisory'] == 'review_output_changed'
    assert not rp.satisfied(study, SPECIALIST)


def test_one_session_cannot_fill_two_review_seats(study):
    dispatched(study, 'first', CRITIC, 'physics-critic', session='shared-session')
    dispatched(study, 'second', SPECIALIST, 'discrepancy-attributor', session='shared-session')
    assert ri.decide(query(study, 'first', CRITIC))['advisory'] == 'review_context_reused'
    assert ri.decide(query(study, 'second', SPECIALIST))['advisory'] == 'review_context_reused'


def test_an_advisory_host_dispatch_record_for_the_attempt_denies_credit(study):
    dispatched(study, 'held', SPECIALIST, 'discrepancy-attributor')
    q = query(study, 'held', SPECIALIST)
    assert ri.decide(q)['independent']
    path = worker._record_path(study, 'held', 1).with_name(worker._key('held', 1) + '.role-dispatch.json')
    path.write_text(json.dumps({'identity': {'mode': 'advisory', 'role': 'discrepancy-attributor'}, 'result': None}))
    assert not ri.decide(q)['independent']


# ---------------------------------------------------------------- graph route

def graph_query(root, binding):
    receipt = agent_graph.role_receipt(binding['graph_root'], binding['node_id'],
                                       expected_subject_sha256=binding['subject_sha256'],
                                       expected_packet_sha256=binding['context_manifest_sha256'],
                                       allowed_roles={binding['node_id']})
    return ri.graph_query(root, receipt), receipt


def test_the_graph_runner_records_an_observed_dispatch_for_the_exact_binding(run, tmp_path, observed_role_boundary):
    root, _ = run; opened(run)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    q, receipt = graph_query(root, binding)
    kept = review_dispatch.graph_record(q['receipt_sha256'])
    assert kept['observation'] == 'remote_transport_observed' and kept['read_boundary'] == 'tools_disabled'
    assert kept['packet_builder'] == review_dispatch.JUDGMENT and kept['role'] == 'critic'
    assert ri.decide(q)['independent']
    for field, value in (('role', 'verifier'), ('subject_sha256', 'e' * 64), ('output_sha256', 'e' * 64),
                         ('packet_sha256', 'e' * 64), ('run', str(tmp_path / 'other'))):
        assert not ri.decide({**q, field: value})['independent'], field
    review_dispatch._store().joinpath(q['receipt_sha256'] + '.json').unlink()
    assert not ri.decide(q)['independent']


def test_a_control_transport_records_no_credit(run, tmp_path):
    root, _ = run; opened(run)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    q, _ = graph_query(root, binding)
    assert review_dispatch.graph_record(q['receipt_sha256'])['observation'] == 'control_only'
    assert not ri.decide(q)['independent']


def test_an_observed_request_with_tools_is_advice(run, tmp_path, monkeypatch):
    root, _ = run; opened(run)
    original = agent_graph.Control.call
    def call(self, label, kind, request, function, output_tokens=0, downstream=None):
        def tooled():
            result = function()
            return {**result, 'transport': {**result['transport'], 'execution_mode': 'responses_http'}}
        return original(self, label, kind, request, tooled, output_tokens=output_tokens, downstream=downstream)
    monkeypatch.setattr(agent_graph.Control, 'call', call)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    q, receipt = graph_query(root, binding)
    assert receipt['execution_observation'] == 'remote_transport_observed'
    kept = review_dispatch.graph_record(q['receipt_sha256'])
    assert kept['read_boundary_verified'] is False and not ri.decide(q)['independent']


def test_a_hand_written_graph_record_cannot_rebind_another_result(run, tmp_path, observed_role_boundary):
    root, _ = run; opened(run)
    binding = prepare(root, tmp_path, 'critic')
    scientific_judgment.execute_role(binding, FakeHost())
    q, _ = graph_query(root, binding)
    kept = review_dispatch.graph_record(q['receipt_sha256'])
    # A record copied under another receipt digest names the original receipt and binds nothing else.
    forged = review_dispatch._store() / ('f' * 64 + '.json')
    forged.write_text(json.dumps(kept))
    assert not ri.decide({**q, 'receipt_sha256': 'f' * 64})['independent']
    assert rdj_custody.rows(root, 'workers') == []


def test_rdj_graph_roles_and_the_pinned_edge_payload_are_credited_from_runner_records(tmp_path, monkeypatch):
    pytest.importorskip('langgraph')
    from rdj_fixtures import Run, critic, reviewer, two_level_r2, verifier
    from test_rdj_loop import GraphHost
    from ravel.workflow import rdj_loop
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = Run(tmp_path / 'run')
    host = GraphHost({'edge_reviewer': reviewer(), 'critic': critic(), 'verifier': verifier()})
    rdj_custody.register_host(run.root, host.identity)
    case_id = two_level_r2(run, roles=rdj_loop.AgentHostDispatcher(host, model='m'))
    rdj_loop.run_roles(run.root, case_id, rdj_loop.AgentHostDispatcher(host, model='m'))
    records = [json.loads(p.read_text()) for p in review_dispatch._store().glob('*.json')]
    edge = [r for r in records if r['role'] == 'rdj_edge_reviewer']
    assert edge and all(r['packet'] is None and r['packet_builder'] == review_dispatch.RDJ for r in edge)
    assert {r['packet_builder'] for r in records} == {review_dispatch.RDJ}
    case, state, _ = rdj_loop._load(run.root, case_id)
    summary = rdj_loop._attestation_summary(run.root, case, state)
    assert summary['independent'] and set(summary['edge_reviewers']) == {'transport_attested'}
    # Without the runner's records every role call is a self check again.
    for path in review_dispatch._store().glob('*.json'):
        path.unlink()
    summary = rdj_loop._attestation_summary(run.root, case, state)
    assert not summary['independent'] and set(summary['edge_reviewers']) == {'self_attested'}
