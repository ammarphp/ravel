"""Executed, bounded graph slices with scripted peers and literal seat oracles.

The existing worker harnesses materialize and finish inert byte producers.
Interface-fake review credit is identified where used; it grants no science
claim. Expected seats come from the declared route/graph policy, not a trace.
"""
from copy import deepcopy
import json

import pytest

from ravel.controller import schema_errors
from ravel.controller.judgment import planning
from ravel.workflow import agent_worker, graph_substrate as gs
from test_p08_fakes import invoke, judged, plan, step  # noqa: F401


def test_judgment_question_with_no_fixed_route_dispatches_exact_planning_seats(judged):
    frame = judged.frame_doc()
    candidate = plan(frame, [step('derive')])
    judged.steps.documents['judgment-frame-*'] = lambda *a: {'outputs/question-frame.json': frame}
    judged.steps.documents['judgment-decompose-*'] = lambda *a: {'outputs/judgment-plan.json': candidate}
    result = invoke(judged, judged.view())
    assert result['outcome'] == 'ok', result
    assert [(c['step']['id'], c['step']['role']) for c in judged.steps.calls] == [
        ('judgment-frame-1', 'coordinator'), ('judgment-frame-review-1-1', 'plan-critic'),
        ('judgment-decompose-r0-1', 'coordinator')]
    assert planning.check_frame(frame, judged.reading, judged.pins['sha256']) == []
    assert planning.check_plan(candidate, frame, operations={'literal-calculation'}, routes=set()) == []
    assert schema_errors(result['results']['plan'], 'plan.v1') == []
    assert result['results']['plan']['route']['id'] == 'judgment'


@pytest.mark.parametrize('damage', ['missing-field', 'wrong-type', 'foreign-provenance'])
def test_judgment_frame_handoff_refuses_before_any_decomposition(judged, damage):
    frame = judged.frame_doc()
    if damage == 'missing-field':
        del frame['objective']
    elif damage == 'wrong-type':
        frame['deliverables'] = 'one result'
    else:
        frame['request_sha256'] = '0' * 64
    judged.steps.documents['judgment-frame-*'] = lambda *a: {'outputs/question-frame.json': frame}
    result = invoke(judged, judged.view())
    assert result['outcome'] == 'held'
    assert result['status']['reason'].startswith('judgment_planning_held')
    assert [(c['step']['id'], c['step']['role']) for c in judged.steps.calls] == [
        ('judgment-frame-1', 'coordinator'), ('judgment-frame-2', 'coordinator')]
    assert [e['status'] for e in judged.events('frame')] == ['refused', 'refused']
    assert judged.events('plan') == []


def test_review_point_dispatches_exact_first_pass_verifier_and_decider(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    from test_review_points_graph import Workers, plan as review_plan, run_review
    root = Run(tmp_path / 'review', snapshot=False).root
    review_plan(root, delegated=True)
    workers = Workers(root)
    observation = run_review(root, monkeypatch, workers)
    assert observation['terminal'] is None and not observation['next'], observation
    # The first pass is the core point's four roles plus the claim's conditional absolute-yield staffing
    # (spawn row K5: two re-derivers and a second normalization auditor; K6: the comparative reviewer).
    assert workers.rounds() == {
        0: sorted(['discrepancy-attributor', 'normalization-auditor', 'physics-critic', 'trap-auditor',
                   're-deriver', 're-deriver', 'normalization-auditor', 'comparative-reviewer']),
        1: ['skeptical-verifier'], 2: ['physics-decider']}
    assert len(workers.calls) == 10
    # Every packet is bound to the exact selected claim, not another point.
    assert all(c['packet']['at'] == 'checkin2:C1' for c in workers.calls)
    assert all(len(c['packet']['subject_sha256']) == 64 for c in workers.calls)


def test_review_handoff_foreign_approval_refuses_before_next_panel(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    from test_review_points_graph import Workers, plan as review_plan, run_review, state, write
    root = Run(tmp_path / 'review', snapshot=False).root
    review_plan(root, delegated=False)
    workers = Workers(root)
    first = run_review(root, monkeypatch, workers)
    pending, = [i for i in first['interrupts'] if i['schema_id'] == 'checkin2_response']
    before = deepcopy(workers.calls)
    pin = write(root / 'inputs/science-approval.json', {'schema_version': 2, 'generated_by': 'foreign-source', 'quote': 'yes'})
    response = {'decision': 'approve', 'record': {'path': 'inputs/science-approval.json', 'sha256': pin['sha256']}}
    refused = run_review(root, monkeypatch, workers, responses={pending['id']: response})
    assert refused['terminal']['status'] == 'hold'
    assert refused['terminal']['reason'] == 'review_gate_refused'
    assert [e['code'] for e in state(root, refused)['gates']['checkin2_accept']['errors']] == ['science_approve_invalid']
    assert workers.calls == before


@pytest.mark.parametrize('foreign', [False, True], ids=['original-source', 'foreign-source'])
def test_literature_retrieval_dispatches_scout_then_cards_and_consumes_original_source(tmp_path, monkeypatch, foreign):
    from ravel.workflow.graphs import literature as lg
    from test_literature_graphs import _spec, _consume
    from test_knowledge_broker import setup
    from test_evidence_card import card
    from test_agent_worker import put, result as worker_result
    _, source_broker, _ = setup(tmp_path, monkeypatch)
    root = source_broker.rundir
    raw, evidence = card()
    (source_broker.workspace / 'inputs/paper.txt').write_bytes(raw)
    if foreign:
        evidence['locator']['doc']['sha256'] = '0' * 64
    calls, posts, acquires = [], [], []

    def dispatch(run, worker, **options):
        calls.append((worker['node_id'], worker['role']['id']))
        workspace = agent_worker.materialize(run, worker)
        payload = {'cards': [evidence]} if worker['node_id'] in ('cards', 'revised_cards') else {'sources': []}
        put(run, workspace, 'outputs/result.txt', json.dumps(payload))
        return agent_worker.finish(run, worker, final=worker_result(), execution={'exit_status': 0})

    monkeypatch.setattr(agent_worker, 'dispatch', dispatch)
    services = lg.Services(epoch='1' * 64, worker_spec=_spec,
        consume_worker=lambda role, receipt, state: _consume(root, receipt), source_items=lambda state: [],
        acquire=lambda state: acquires.append(state), extract=lambda state: pytest.fail('empty map extracted'),
        reextract=lambda state: {'retry': 'source'},
        card_population=lambda state: state['work'].get('revised_cards', state['work']['cards'])['cards'],
        post=lambda state, report: posts.append(report) or {'journal': 'recorded-post'}, broker=source_broker)
    with lg.services(services):
        observation = gs.run(root, lg.SCOUT, {'request_id': 'source'}, input={'request': {}}, max_steps=40)
    assert observation['terminal'] is None, observation
    assert acquires == []
    if foreign:
        assert calls == [('scout', 'literature-scout'), ('cards', 'literature-scout')]
        # Refused provenance stays visible in the census, and reaches no anchor consumer.
        assert len(posts) == 1 and posts[0]['anchor_ids'] == []
        assert posts[0]['census'][0]['status'] == 'refused'
        assert posts[0]['census'][0]['reason'] == 'source_changed'
        assert source_broker.verify_ledger()[-1]['status'] == 'refused'
    else:
        assert calls == [('scout', 'literature-scout'), ('cards', 'literature-scout')]
        assert len(posts) == 1 and posts[0]['anchor_ids'] == ['card-a']
        assert posts[0]['census'][0]['status'] == 'checked'


def test_lean_needed_tool_executes_and_malformed_tool_handoff_has_no_write(tmp_path, monkeypatch):
    from ravel.controller import instructions
    from ravel.controller.engagement import policy
    from ravel.workflow import role_registry, toolbelt
    from test_toolbelt import make_broker
    card = role_registry.load('analysis-author')
    lean_scope = policy.load_policy()['packet_scope']['lean']
    assert lean_scope == {'deferred_reads': 'logged', 'duty_units': 'all', 'effective_card': 'full',
                          'inline_context_tokens': 0, 'must_read': 'all'}
    row = {'id': 'lean-tool', 'kind': 'author', 'role': 'analysis-author',
           'inputs': [], 'outputs': [{'path': 'outputs/value.txt', 'kind': 'document', 'required': True}],
           'depends_on': [], 'engagement': lean_scope, 'parameters': {'seat_kind': 'analysis'}}
    manifest = instructions.manifest(row, card)
    packet = instructions.packet(manifest, card, row, [])
    assert instructions.check_packet(packet, manifest, card, row, []) == []
    tools = toolbelt.for_card(card)
    broker = make_broker(tmp_path, monkeypatch, tools, card)
    target = broker.workspace / 'outputs/value.txt'
    refused = broker.call(toolbelt.to_request(tools, 'ws_write', {'path': 'outputs/value.txt', 'content': []}, 'bad'))
    assert refused['status'] == 'refused' and not target.exists()
    assert refused['error']['code'] == 'not_allowlisted'
    result = broker.call(toolbelt.to_request(tools, 'ws_write', {'path': 'outputs/value.txt', 'content': 'generic value'}, 'good'))
    assert result['status'] == 'ok' and target.read_text() == 'generic value'
    assert [r['status'] for r in broker.verify_ledger()] == ['refused', 'ok']
