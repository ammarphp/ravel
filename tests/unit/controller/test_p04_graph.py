"""``controller.step`` end to end with the inert worker: one step attempt from reservation to outcome."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_p04_support import (graphs, inert_worker, make_step, records, run_env, run_step,  # noqa: F401
                              services_installed)


def test_registered_structure_equals_the_built_graphs(graphs):
    from ravel.workflow import graph_registry, graph_substrate as gs
    rows = {row['id']: row for row in graphs}
    assert set(rows) == {'controller.step', 'controller.seat'}
    assert rows['controller.step']['subgraphs'] == [{'id': 'controller.seat', 'version': rows['controller.seat']['version']}]
    for graph_id in rows:
        ctx = gs.BuildContext(scope_root=Path('/nonexistent'), graph_id=graph_id, version=rows[graph_id]['version'],
                              instance={'run_id': 'run-p04-fixture'}, row=graph_registry.get(graph_id))
        compiled = gs.build(graph_id, ctx)
        assert compiled.structure_sha256 == rows[graph_id]['structure_sha256']


def test_a_step_runs_from_reservation_to_an_adopted_accepted_outcome(run_env, inert_worker, graphs):
    step = make_step('s1')
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    store = run_env.store
    # The declared output and, for a card with a sidecar, the final record beside it.
    assert sorted(o['artifact'] for o in outcome['outputs']) == ['s1:final-record.json', 's1:outputs/result.json']
    adopted = run_env.run_dir / 'steps/s1/outputs/result.json'
    assert json.loads(adopted.read_text()) == {'value': 1, 'path': 'outputs/result.json'}
    custody = [r for r in records(store, 'custody') if r['artifact'] == 's1:outputs/result.json']
    assert [r['status'] for r in custody] == ['staged', 'accepted']
    reservation = records(store, 'budget-reservation')
    settlement = records(store, 'budget-settlement')
    assert len(reservation) == 1 and reservation[0]['amounts']['children'] == 1
    assert settlement[0]['status'] == 'settled' and settlement[0]['charged']['children'] == 1
    delivered = records(store, 'instruction-delivery')
    assert delivered[0]['kind'] == 'instruction-delivery' and delivered[-1]['session'].startswith('sess-')
    assert records(store, 'step-observation')[0]['attestation'] == 'transport_attested'
    statuses = run_env.fakes['ledger'].statuses(store)
    assert any(key.startswith('B01@') and value == 'satisfied' for key, value in statuses.items())
    assert statuses.get('I01@run-p04-fixture/step=s1/seat=producer/attempt=1') == 'satisfied'


def _custody(store, artifact):
    return [r for r in records(store, 'custody') if r['artifact'] == artifact]


def test_I01_a_missing_acknowledgement_row_fails_the_step_and_adopts_nothing(run_env, inert_worker, graphs):
    inert_worker.scenario(ack='omit_row')
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'instruction_ack' in outcome['reason']
    assert _custody(run_env.store, 's1:outputs/result.json') == []
    statuses = run_env.fakes['ledger'].statuses(run_env.store)
    assert statuses['I01@run-p04-fixture/step=s1/seat=producer/attempt=1'] == 'violated'


def test_I01_an_acknowledgement_of_another_manifest_fails_the_step(run_env, inert_worker, graphs):
    inert_worker.scenario(ack='wrong_manifest')
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'instruction_ack' in outcome['reason']


def test_CF01_a_final_record_without_the_escalation_field_fails(run_env, inert_worker, graphs):
    inert_worker.scenario(drop=['escalation'])
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'escalation_field_missing' in outcome['reason']
    assert _custody(run_env.store, 's1:outputs/result.json') == []


@pytest.mark.parametrize('kind, status, kept', [('stop', 'escalated', 'step-escalation'),
                                                ('checkin_flag', 'completed', 'checkin-flag'),
                                                ('decision_block', 'escalated', 'rdj-request'),
                                                ('new_experiment_required', 'escalated', 'replan-request')])
def test_CF01_each_escalation_value_is_handled_by_the_controller(run_env, inert_worker, graphs, kind, status, kept):
    inert_worker.scenario(escalation=[{'kind': kind, 'statement': 'a fixture condition', 'evidence': ['final_record#/kind']}])
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == status and outcome['escalation'] == kind
    assert records(run_env.store, kept)
    rows = records(run_env.store, 'step-escalation')
    assert [r['kind'] for r in rows] == [kind]
    if kind == 'checkin_flag':
        assert records(run_env.store, 'checkin-flag')[0]['number'] == 1
    if kind == 'new_experiment_required':
        assert outcome['replan']['statement'] == 'a fixture condition'
    if kind == 'stop':
        assert rows[0]['action'] == 'halt_and_notify'


def test_a_blocked_checklist_row_holds_the_step(run_env, inert_worker, graphs):
    inert_worker.scenario(ack='blocked')
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'held' and outcome['reason'] == 'checklist_blocked'


def test_T02_unregistered_tools_and_a_generic_delegate_are_denied_before_invocation(run_env, inert_worker, graphs):
    inert_worker.scenario(calls=[{'name': 'shell', 'arguments': {'command': 'true'}},
                                 {'name': 'delegate', 'arguments': {'role': 'baseline-producer', 'task': 'x'}},
                                 {'name': 'read', 'arguments': {'path': 'inputs/packet.md'}}])
    outcome = run_step(run_env, make_step('s1'))
    rows = records(run_env.store, 'broker-evidence')
    refused = {r['action']: r['error'] for r in rows if r['status'] == 'refused'}
    assert refused == {'tool:shell': 'not_allowlisted', 'tool:delegate': 'not_allowlisted',
                       'tool:read': 'not_allowlisted'}
    assert outcome['status'] == 'completed'


def test_I04_a_native_write_outside_the_broker_is_not_credited_and_nothing_is_adopted(run_env, inert_worker, graphs):
    inert_worker.scenario(writes=[], native_writes=[{'path': 'outputs/result.json', 'content': '{"value": 1}'}])
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'worker_receipt_failed' in outcome['reason']
    assert _custody(run_env.store, 's1:outputs/result.json') == []
    assert not (run_env.run_dir / 'steps/s1/outputs/result.json').exists()


def test_I05_a_reused_session_earns_nothing(run_env, inert_worker, graphs):
    inert_worker.scenario(session='sess-fixed')
    step = make_step('s1')
    first = run_step(run_env, step)
    assert first['status'] == 'completed'
    from test_p04_support import context, install_plan
    from ravel.controller import step as governed
    plan_sha = install_plan(run_env.store, [step], revision=1)
    second = governed.run(run_env.store, step, context(run_env.store, run_env.run_dir, plan_sha, attempt=2))
    assert second['status'] == 'failed' and 'session' in second['reason']


def test_I08_a_substituted_model_refuses_the_step(run_env, inert_worker, graphs):
    inert_worker.scenario(model='claude-substitute-model')
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'model_model_substituted' in outcome['reason']
    statuses = run_env.fakes['ledger'].statuses(run_env.store)
    assert statuses['I08@run-p04-fixture/step=s1/seat=producer/attempt=1'] == 'violated'


def test_review_seats_are_dispatched_fresh_and_credited(run_env, inert_worker, graphs):
    step = make_step('s1', review=['integrity-auditor'])
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    review = outcome['review']
    assert review['credited'] is True and [s['role'] for s in review['seats']] == ['integrity-auditor']
    observations = records(run_env.store, 'step-observation')
    sessions = [r['session_id'] for r in observations]
    assert len(sessions) == 2 and len(set(sessions)) == 2
    assert observations[1]['seat'] == 'seat:integrity-auditor:1'
    assert run_env.fakes['independence'].queries[0]['role'] == 'integrity-auditor'


def test_an_uncredited_review_seat_holds_the_step(run_env, inert_worker, graphs):
    run_env.fakes['independence'].independent = False
    step = make_step('s1', review=['integrity-auditor'])
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'held' and outcome['reason'] == 'review_uncredited'
    assert outcome['review']['seats'][0]['reasons'] == ['independence:fixture_advice']


@pytest.mark.parametrize('kind, status, kept', [('stop', 'escalated', 'step-escalation'),
                                                ('checkin_flag', 'completed', 'checkin-flag'),
                                                ('decision_block', 'escalated', 'rdj-request'),
                                                ('new_experiment_required', 'escalated', 'replan-request')])
def test_CF01_a_review_seats_escalation_is_handled_by_the_controller(run_env, inert_worker, graphs, kind, status,
                                                                     kept):
    # Only the reviewer (a findings record) raises it; the producer raises nothing.
    inert_worker.scenario(findings_escalation=[{'kind': kind, 'statement': 'a fixture review condition',
                                                'evidence': ['final_record#/kind']}])
    outcome = run_step(run_env, make_step('s1', review=['integrity-auditor']))
    assert outcome['status'] == status and outcome['escalation'] == kind, outcome
    rows = records(run_env.store, 'step-escalation')
    assert [(r['kind'], r['seat']) for r in rows] == [(kind, 'seat:integrity-auditor:1')]
    assert records(run_env.store, kept)
    assert rows[0]['subject'] == [{'artifact': o['artifact'], 'sha256': o['sha256']} for o in outcome['outputs']]


@pytest.mark.parametrize('independent, status, reason', [(True, 'completed', None), (False, 'held', 'review_uncredited')])
def test_a_review_step_whose_own_review_is_uncredited_holds(run_env, inert_worker, graphs, independent, status, reason):
    run_env.fakes['independence'].independent = independent
    # The auditor's check has a real subject: the audit record and the result it covers, named by the step itself.
    (run_env.run_dir / 'inputs' / 'assumption-audit.json').write_text(json.dumps({
        'audit': {'kind': 'assumption-audit', 'schema_version': 1,
                  'items': [{'id': 'A1', 'severity': 1, 'controlled': True}]},
        'result': {'assumptions_reported': []}}))
    check = {'check:validation.assumption_audit.check': {'document': 'inputs/assumption-audit.json'}}
    step = make_step('r1', kind='review', role='assumption-auditor', outputs=(('outputs/findings.json', 'findings'),),
                     parameters={'check_inputs': check})
    document = {'audit': {'kind': 'assumption-audit', 'schema_version': 1, 'items': [
        {'id': 'A1', 'statement': 'first', 'severity': 9, 'controlled': False, 'locators': []},
        {'id': 'A2', 'statement': 'second', 'severity': 3, 'controlled': False, 'locators': []},
        {'id': 'A3', 'statement': 'third', 'severity': 9, 'controlled': True,
         'locators': ['inputs/check.json']}]}, 'result': {'assumptions_reported': ['A1']}}
    (run_env.run_dir / 'inputs/assumption-audit.json').write_text(json.dumps(document))
    step['parameters']['check_inputs'] = {'check:validation.assumption_audit.check': {
        'document': 'inputs/assumption-audit.json'}}
    outcome = run_step(run_env, step)
    assert (outcome['status'], outcome['reason']) == (status, reason), outcome
    assert outcome['review']['credited'] is independent and outcome['review']['seats'] == []


def test_required_review_seats_beyond_the_seat_limit_hold_before_dispatch(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import graph as step_graph
    monkeypatch.setattr(step_graph, 'MAX_SEATS', 1)
    outcome = run_step(run_env, make_step('s1', review=['integrity-auditor', 'assumption-auditor']))
    assert outcome['status'] == 'held' and outcome['reason'] == 'review_seats_exceed_limit', outcome
    assert records(run_env.store, 'step-dispatch') == []


def _qualified_blind_worker(monkeypatch):
    """Stand in for the qualified blind-capable restricted CLI worker (the review-liveness fix)."""
    from ravel.workflow import transport_registry as tr
    monkeypatch.setattr(tr, 'blind_admissible', lambda document, capabilities=None: True)


def test_a_card_reviewer_seat_is_added_from_reviewed_by(run_env, inert_worker, graphs, monkeypatch):
    _qualified_blind_worker(monkeypatch)
    step = _consulting_step(run_env, monkeypatch)
    outcome = run_step(run_env, step)
    # The card's reviewer seat is derived and dispatched; its spec-denied profile sees only the controller's
    # projection of the step's inputs (never the producer's raw outputs), so the seat runs and its review credits.
    assert [s['role'] for s in outcome['review']['seats']] == ['ml-reviewer']
    assert [r['seat'] for r in records(run_env.store, 'step-dispatch')] == [None, 'seat:ml-reviewer:1']
    dispatches = records(run_env.store, 'step-dispatch')
    observations = records(run_env.store, 'step-observation')
    assert dispatches[0]['step_id'] == step['id']
    assert dispatches[1]['step_id'] != step['id']
    assert dispatches[1]['parent_step'] == step['id']
    assert {(r['node_id'], r['step_id']) for r in dispatches} == {
        (r['node_id'], r['step_id']) for r in observations}
    assert records(run_env.store, 'step-refusal') == []
    assert outcome['status'] == 'completed' and outcome['review']['credited'] is True, outcome


def test_a_blind_reviewer_seat_holds_while_no_admitted_transport_is_blind_capable(run_env, inert_worker, graphs, monkeypatch):
    # A qualified sandbox worker is blind-capable where the sandbox is available; this case has none that is.
    from ravel.workflow import transport_registry as tr
    monkeypatch.setattr(tr, 'blind_admissible', lambda document, capabilities=None: False)
    step = _consulting_step(run_env, monkeypatch)
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'held' and outcome['reason'] == 'review_uncredited'
    refusals = records(run_env.store, 'step-refusal')
    assert refusals[0]['reason'] == 'transport_unavailable' and 'blind' in refusals[0]['detail']


def _consulting_step(run_env, monkeypatch):
    from ravel.workflow import review_independence
    from test_p13_ml_stage_wiring import numerical_observations
    previous = review_independence.controller_store
    monkeypatch.setattr(review_independence, 'controller_store', lambda run:
        run_env.store if Path(run) == run_env.run_dir else previous(run))
    step = make_step('t1', role='ml-trainer', outputs=(('outputs/ml/receipt.json', 'ml-receipt'),))
    # Executed numerical plugin controls exercise the observation interface only.
    step['parameters']['check_inputs'] = numerical_observations(
        run_env.run_dir, run_env.store, {'id': step['id']}, 'good')
    return step


def test_CF04_a_fired_consult_trigger_dispatches_the_consult_role_first(run_env, inert_worker, graphs, monkeypatch):
    _qualified_blind_worker(monkeypatch)
    outcome = run_step(run_env, _consulting_step(run_env, monkeypatch), contested=True)
    consults = records(run_env.store, 'step-consult')
    assert [(c['role'], c['trigger'], c['status']) for c in consults] == [
        ('consult-inference', 'contested_node:consult-inference', 'completed')]
    dispatched = [r['seat'] for r in records(run_env.store, 'step-dispatch')]
    assert dispatched[:2] == ['consult:consult-inference:1', None]
    producer = [r for r in records(run_env.store, 'step-observation') if r['seat'] is None]
    assert len(producer) == 1 and producer[0]['status'] == 'ok'
    # The producer's packet is rebuilt with the consult record as an input by digest.
    assert run_env.fakes['instructions'].calls.count(('packet', 't1')) == 2
    assert outcome['status'] == 'completed'  # its spec-denied reviewer seat runs on its projection (see above)


def test_CF04_a_consult_that_does_not_complete_holds_the_step(run_env, inert_worker, graphs, monkeypatch):
    _qualified_blind_worker(monkeypatch)
    inert_worker.scenario(ack='omit_row')
    outcome = run_step(run_env, _consulting_step(run_env, monkeypatch), contested=True)
    assert outcome['status'] == 'held' and outcome['reason'] == 'consult_missing'
    assert [r['seat'] for r in records(run_env.store, 'step-dispatch')] == ['consult:consult-inference:1']


def test_an_ask_step_is_returned_to_the_controller_graph(run_env, inert_worker, graphs):
    step = make_step('q1', kind='ask', role=None, outputs=())
    step['question'] = 'Which fixture option should the run take?'
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'escalated' and outcome['escalation'] == 'ask'
    assert outcome['request']['question'] == step['question']
    # The step states no options, so the controller graph's parent request holds it, typed.
    assert outcome['request']['options'] == [] and outcome['request']['default'] is None
    assert records(run_env.store, 'step-dispatch') == []


def test_R13_SW39_a_step_whose_parent_has_not_completed_is_held_before_dispatch(run_env, inert_worker, graphs):
    step = make_step('s2', depends_on=['s1'])
    outcome = run_step(run_env, step, plan_steps=[make_step('s1'), step])
    assert outcome['status'] == 'held' and outcome['reason'] == 'parent_incomplete'
    assert records(run_env.store, 'step-dispatch') == []
    settled = records(run_env.store, 'budget-settlement')
    assert settled[0]['status'] == 'released'


def test_a_stop_holds_before_any_effect(run_env, inert_worker, graphs):
    run_env.fakes['authority'].stop = 'stop_requested'
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'stopped'
    assert records(run_env.store, 'budget-reservation') == []


def test_B01_an_exhausted_envelope_ends_the_step_before_dispatch(run_env, inert_worker, graphs):
    run_env.fakes['authority'].budgets['children'] = 0
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'budget_exhausted'
    assert records(run_env.store, 'step-dispatch') == []


def _launch_tool(tmp):
    module = tmp / 'tools' / 'p04_launch_tool.py'
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text('import json, sys\nfrom pathlib import Path\n'
                      'Path("grid.json").write_text(json.dumps({"points": int(sys.argv[1])}))\n')
    return module.parent


def _signature():
    return {'summary': 'fixture', 'implementation': {'kind': 'command', 'module': 'p04_launch_tool'},
            'consumes': [], 'produces': [{'slot': 'grid', 'kind': 'table'}], 'effects': [],
            'cost': {'unit': 'points', 'forecast': None, 'ceiling_pointer': None}, 'critical_fields': ['/points'],
            'basis': {'adds': [], 'passes': []}, 'tools': [], 'stages': [], 'review': {'checks': []}, 'fidelity_rank': 1}


def _launch_step(tools, *, argv_points='3', role=None):
    import sys
    return make_step('g1', kind='operate', role=role, operation='fixture-operation', outputs=(('grid.json', 'table'),),
                     budget={'wall_seconds': 60, 'events': 0},
                     parameters={'task': {'points': 3},
                                 'launch': {'argv': [sys.executable, '-B', '-m', 'p04_launch_tool', argv_points],
                                            'env': {'PYTHONPATH': str(tools)}}})


def test_CF11_T03_a_confined_launch_runs_exactly_the_approved_argv(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import operations
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    tools = _launch_tool(run_env.root)
    step = _launch_step(tools)
    outcome = run_step(run_env, step)
    assert outcome['status'] == 'completed', outcome
    launched = run_env.fakes['confine'].launched
    assert len(launched) == 1 and launched[0]['argv'] == step['parameters']['launch']['argv']
    assert launched[0]['writes'] == [str(run_env.run_dir / 'steps/g1/attempts/1/outputs')]
    assert json.loads((run_env.run_dir / 'steps/g1/grid.json').read_text()) == {'points': 3}
    journal = records(run_env.store, 'step-launch')
    assert [r['phase'] for r in journal] == ['started', 'finished'] and journal[1]['exit_status'] == 0


def test_T03_a_launch_changed_after_approval_is_refused_before_it_starts(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import operations
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    tools = _launch_tool(run_env.root)
    approved = _launch_step(tools)
    changed = _launch_step(tools, argv_points='4')
    outcome = run_step(run_env, changed, plan_steps=[approved])
    assert outcome['status'] == 'held' and outcome['reason'] == 'plan_step_changed'
    assert run_env.fakes['confine'].launched == []


def test_I04_a_write_outside_the_workspace_outputs_is_refused_by_the_broker(run_env, inert_worker, graphs):
    inert_worker.scenario(calls=[{'name': 'ws_write', 'arguments': {'path': '../escape.txt', 'content': 'x'}},
                                 {'name': 'ws_write', 'arguments': {'path': 'inputs/packet.md', 'content': 'x'}}])
    outcome = run_step(run_env, make_step('s1'))
    refused = [r['error'] for r in records(run_env.store, 'broker-evidence') if r['status'] == 'refused']
    assert refused == ['write_outside_workspace', 'write_outside_workspace']
    assert outcome['status'] == 'completed'
    assert not (run_env.run_dir.parent / 'escape.txt').exists()


def test_CF02_a_worker_past_the_cards_turn_limit_ends_its_attempt(run_env, inert_worker, graphs):
    inert_worker.scenario(turns=10 ** 4)
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'failed' and 'worker_receipt_failed' in outcome['reason']
    validation = records(run_env.store, 'step-validation')[0]
    assert validation['errors'][0]['checks']['budgets'] is False


def test_E30_an_ambiguous_start_stays_charged_and_the_next_attempt_waits_for_reconciliation(run_env, inert_worker,
                                                                                           graphs):
    from test_p04_support import context, install_plan
    from ravel.controller import step as governed
    inert_worker.scenario(kill=True)
    step = make_step('s1')
    first = run_step(run_env, step)
    assert first['status'] == 'held' and first['interrupts'][0]['kind'] == 'reconcile_evidence'
    assert records(run_env.store, 'budget-settlement') == []   # the reservation stays charged in full
    plan_sha = install_plan(run_env.store, [step], revision=1)
    second = governed.run(run_env.store, step, context(run_env.store, run_env.run_dir, plan_sha, attempt=2))
    assert second['status'] == 'held' and second['reason'] == 'prior_attempt_unreconciled'
    assert len(records(run_env.store, 'step-dispatch')) == 1   # never re-dispatched


def test_G13_M25_the_store_mirror_is_the_evidence_and_an_edited_copy_is_refused(run_env, inert_worker, graphs):
    from ravel.controller.step import evidence
    from ravel.workflow import agent_worker
    inert_worker.scenario(calls=[{'name': 'knowledge_find', 'arguments': {'text': 'fixture'}}])
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'completed'
    rows = records(run_env.store, 'broker-evidence')
    assert {r['action'] for r in rows} >= {'knowledge query', 'write'}
    workspace = agent_worker.workspace(run_env.run_dir, 'ctl.s1', 1)
    receipt = next(p for p in sorted((workspace / 'calls').glob('*.json')))
    receipt.write_text(receipt.read_text().replace('"ok"', '"refused"'))
    with pytest.raises(ValueError, match='custody'):
        evidence.mirror(run_env.store, run_env.run_dir, step_id='s1', attempt=1, node_id='ctl.s1', worker_attempt=1)
    assert records(run_env.store, 'broker-evidence') == rows


def test_authority_admits_each_effect_by_its_rung(run_env, inert_worker, graphs):
    run_env.fakes['authority'].refuse = ('full',)
    outcome = run_step(run_env, make_step('s1', rung='full'))
    assert outcome['status'] == 'held' and outcome['reason'] == 'authority_refused'
    effect = [c[1] for c in run_env.fakes['authority'].calls if c[0] == 'authorize_effect'][0]
    assert effect['rung'] == 'full' and effect['pins']['plan_sha256']
    assert records(run_env.store, 'step-dispatch') == []


def test_a_seat_is_probed_against_its_admitted_inventory_before_it_starts(run_env, inert_worker, graphs):
    import os
    from ravel.workflow import agent_worker
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'completed', outcome
    kind, target = run_env.fakes['confine'].probes[0]
    workspace = agent_worker.workspace(run_env.run_dir, 'ctl.s1', 1)
    assert kind == 'worker' and target['workspace'] == str(workspace) and target['run_dir'] == str(run_env.run_dir)
    dispatched = records(run_env.store, 'step-dispatch')[0]
    assert target['admitted']['tools'] == target['tools'] == dispatched['admitted_tools']
    # The admitted set is what the broker serves: the structured-output final record is no broker tool.
    assert 'submit_final' not in dispatched['admitted_tools']
    assert {os.path.realpath(workspace / 'outputs'), os.path.realpath(workspace / 'scratch')} <= set(
        target['admitted']['writable'])
    assert records(run_env.store, 'step-observation')[0]['tool_inventory']['equal'] is True


@pytest.mark.parametrize('extra', [{'tools': ['undeclared_fixture_tool']}, {'writable': ['/fixture/extra-mount']}],
                         ids=['extra-tool', 'extra-mount'])
def test_a_seat_whose_probed_inventory_differs_holds_and_its_child_never_starts(run_env, inert_worker, graphs, extra):
    from ravel.workflow import agent_worker
    run_env.fakes['confine'].extra = {'worker': extra}
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'held' and outcome['reason'] == 'inventory_probe_mismatch', outcome
    receipt = agent_worker.load_receipt(run_env.run_dir, 'ctl.s1', 1)
    assert receipt['status'] == 'refused' and receipt['failure']['missing'] == sorted(extra)
    assert not (agent_worker.workspace(run_env.run_dir, 'ctl.s1', 1) / 'scratch/prompt.txt').exists()
    assert [r['status'] for r in records(run_env.store, 'budget-settlement')] == ['released']
    assert outcome['outputs'] == [] and records(run_env.store, 'custody') == []


def test_a_seat_holds_when_the_inventory_probe_fails(run_env, inert_worker, graphs):
    run_env.fakes['confine'].probe_error = 'inventory program failed under the profile'
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'held' and outcome['reason'] == 'inventory_probe_failed'


def test_a_launch_whose_probed_inventory_differs_holds_and_never_starts(run_env, inert_worker, graphs, monkeypatch):
    import os
    from ravel.controller.step import operations
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    run_env.fakes['confine'].extra = {'launch': {'writable': ['/fixture/extra-mount']}}
    outcome = run_step(run_env, _launch_step(_launch_tool(run_env.root)))
    assert outcome['status'] == 'held' and outcome['reason'] == 'inventory_probe_mismatch'
    assert run_env.fakes['confine'].launched == [] and records(run_env.store, 'step-launch') == []
    kind, target = run_env.fakes['confine'].probes[0]
    outputs = run_env.run_dir / 'steps/g1/attempts/1/outputs'
    assert kind == 'launch' and target['admitted'] == {'writable': [os.path.realpath(outputs)], 'network': 'none'}
    assert target['run_dir'] == str(run_env.run_dir) and target['limits'] == {'wall_seconds': 60, 'cpus': 1}


def test_a_launch_the_confinement_package_holds_is_not_an_ambiguous_start(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import operations
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    run_env.fakes['confine'].hold = 'sandbox_unavailable'
    outcome = run_step(run_env, _launch_step(_launch_tool(run_env.root)))
    assert outcome['status'] == 'held' and outcome['reason'] == 'confined_launch_held', outcome
    assert not outcome.get('interrupts')   # refused before any effect: never a reconciliation
    assert [r['phase'] for r in records(run_env.store, 'step-launch')] == ['started', 'refused']
    assert records(run_env.store, 'step-launch')[1]['evidence']['reason'] == 'sandbox_unavailable'
    assert [r['status'] for r in records(run_env.store, 'budget-settlement')] == ['released']


def test_a_hold_inside_the_launch_effect_is_recorded_as_not_dispatched(run_env):
    from ravel.controller.step import graph
    from ravel.controller.step.services import bound
    run_env.fakes['authority'].stop = 'stop_requested'
    state = {'context': {'run_id': run_env.store.run_id, 'store_root': str(run_env.store.store_root)}}
    with bound(run_env.store), pytest.raises(graph.LaunchNotStarted) as held:
        graph._launch(state, {})
    assert held.value.reason == 'run_stopped' and held.value.not_dispatched is True


def test_a_science_mode_is_admitted_by_its_signature_and_executor_and_recorded(run_env, inert_worker, graphs,
                                                                               monkeypatch):
    from copy import deepcopy
    from ravel.controller.step import operations
    from ravel.workflow import production_executor
    signature = {**_signature(), 'implementation': {'kind': 'science-mode', 'mode': 'fixture-mode',
                                                     'module': 'p04_launch_tool'}}
    table = deepcopy(production_executor.executors())
    table['operations']['fixture-operation'] = 'calculation'   # a science mode runs only through its production role
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': signature})
    monkeypatch.setattr(operations, 'executors', lambda: table)
    rows = [f'{row}@{run_env.store.run_id}/step=g1' for row in ('MODE-fixture-mode', 'TOOL-fixture-operation',
                                                                'EXEC-fixture-operation')]
    for key in rows:   # the plan stage materialised the step-scope rows
        run_env.store.append('ledger', {'entry_id': key, 'status': 'pending', 'stage': 'plan'})
    run_step(run_env, _launch_step(_launch_tool(run_env.root), role='calculation'))
    assert all(('record', key, 'satisfied') in run_env.fakes['ledger'].calls for key in rows)
    assert run_env.fakes['confine'].launched   # admitted: the launch ran
    unregistered = deepcopy(table)
    del unregistered['operations']['fixture-operation']
    monkeypatch.setattr(operations, 'executors', lambda: unregistered)
    held = run_step(run_env, _launch_step(_launch_tool(run_env.root), role='calculation'), attempt=2)
    assert held['status'] == 'held' and held['reason'] == 'executor_role_missing'


def test_a_single_point_step_materialises_its_point_scope(run_env, inert_worker, graphs):
    outcome = run_step(run_env, make_step('s1'), point='p-0003')
    assert outcome['status'] == 'completed', outcome
    materialised = [c for c in run_env.fakes['ledger'].calls if c[0] == 'materialise']
    assert materialised and all(c[2]['point'] == 'p-0003' for c in materialised)


def test_a_confined_launch_runs_inside_the_controller_dispatch_and_is_finished(run_env, inert_worker, graphs,
                                                                               monkeypatch):
    import sys
    from contextlib import contextmanager
    from ravel.controller.step import operations
    from ravel.workflow import wms_policy
    order = []

    @contextmanager
    def controller_dispatch(rundir):
        order.append(('enter', str(rundir)))
        yield
        order.append(('exit', str(rundir)))

    confine = sys.modules['ravel.controller.confine']
    real = confine.popen
    monkeypatch.setattr(wms_policy, 'controller_dispatch', controller_dispatch, raising=False)
    monkeypatch.setattr(confine, 'popen', lambda spec, **kw: order.append(('popen', spec['run_dir'])) or real(spec, **kw))
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    outcome = run_step(run_env, _launch_step(_launch_tool(run_env.root)))
    assert outcome['status'] == 'completed', outcome
    run = str(run_env.run_dir)
    assert order == [('enter', run), ('popen', run), ('exit', run)]
    assert run_env.fakes['confine'].finished == [0]
    finished = records(run_env.store, 'step-launch')[-1]
    assert finished['phase'] == 'finished' and finished['plan']['kind'] == 'confined'
    assert finished['confinement']['errors'] == []


def test_SW38_the_worker_launch_and_broker_layers_are_reached_only_inside_the_agent_node(run_env, inert_worker, graphs,
                                                                                        monkeypatch):
    from ravel.workflow import agent_tripwire
    monkeypatch.setenv(agent_tripwire.ENV, '1')
    monkeypatch.setattr(agent_tripwire, 'OBSERVED', [])
    outcome = run_step(run_env, make_step('s1'))
    assert outcome['status'] == 'completed', outcome
    verdicts = agent_tripwire.OBSERVED
    assert {'agent_worker.launch', 'broker.call'} <= {v['layer'] for v in verdicts}
    assert all(v['ok'] and v['context']['ravel_kind'] == 'agent' for v in verdicts), verdicts


def test_native_effect_rechecks_workflow_custody_before_start(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import operations
    from ravel.workflow import wms_policy
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    def refuse(root):
        raise ValueError('current workflow custody refused')
    monkeypatch.setattr(wms_policy, 'require_custody', refuse)
    outcome = run_step(run_env, _launch_step(_launch_tool(run_env.root)))
    assert outcome['status'] == 'held' and outcome['reason'] == 'workflow_custody_refused', outcome
    assert run_env.fakes['confine'].launched == []


def test_native_effect_retains_the_actual_workflow_custody_check(run_env, inert_worker, graphs, monkeypatch):
    from ravel.controller.step import operations
    from ravel.workflow import wms_policy
    monkeypatch.setattr(operations, 'signatures', lambda: {'fixture-operation': _signature()})
    checked=[]
    original=wms_policy.require_custody
    def require(root):
        checked.append(str(root));return original(root)
    monkeypatch.setattr(wms_policy, 'require_custody', require)
    outcome = run_step(run_env, _launch_step(_launch_tool(run_env.root)))
    assert outcome['status']=='completed',outcome
    assert checked==[str(run_env.run_dir)]
    proof=[r for r in records(run_env.store,'step-fact') if r.get('mechanism')=='wms_policy.require_custody']
    assert len(proof)==1 and proof[0]['step_id']=='g1'
