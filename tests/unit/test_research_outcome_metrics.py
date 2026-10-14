"""Connected pure engineering instrumentation; no native/model/role calls."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from ravel.workflow import agent_graph as graph, research_cycle as cycle
from ravel.workflow import research_outcome_metrics as metrics, state_io
from test_research_cycle import contract, propose, experiment, write
from test_task_completion import goal, request as completion_request
from test_agent_graph import Host, spec, node


def fixture(base, parent=False):
    c = contract(base)
    c['budget']['output_tokens'] = 4096
    if parent:
        _, pin = goal(base)
        c['goal_binding'] = {'contract': pin, 'assignment_id': 'summary-child'}
    root = base / 'cycle'
    cycle.create(root, c, base_dir=base, evaluation_harness=True)
    propose(base, root)
    e = experiment(base, 'separate', grouped=False)
    if parent:
        source = Path(e['study']['path']); document = json.loads(source.read_bytes())
        document['goal_binding'] = c['goal_binding']; e['study'] = write(source, document)
    cycle.design(root, e)
    return root


def commit(root, mutation):
    _, state = cycle._load(root)
    mutation(state)
    return cycle._commit(root, state, 'synthetic_instrumentation_fixture')


def connect_graph(base, root, *, unknown=False):
    gr = base / 'graph'
    plan = spec([node('instrumentation', kind='model', role='proposer')], calls=2, tokens=128)
    plan['budget']['max_wall_seconds'] = 60
    # Inert Host returns a synthetic model_result. No provider or model invoked.
    usage = {'input_tokens': None, 'output_tokens': None, 'total_tokens': None} if unknown else {
        'input_tokens': 11, 'output_tokens': 7, 'total_tokens': 18}
    host = Host(lambda *args: {'kind': 'model_result', 'usage': usage, 'value': {'synthetic': True}})
    cycle.execute_graph(root, gr, plan, host)
    return gr, host


def test_original_parent_denominator_and_missing_designs_in_automatic_status(tmp_path):
    root = fixture(tmp_path, parent=True)
    result = cycle.status(root)['outcome_metrics']
    assert result['original_task']['original_obligation_denominator'] == 4
    assert {r['id'] for r in result['original_task']['original_obligation_census']} == {'original-request', 'atlas', 'cms', 'domain'}
    assert result['component_outcome_counts'] == {'not_designed': 1, 'unresolved': 1, 'failed': 0, 'partial': 0, 'recorded_component_result': 0}
    assert result['scientific_error_metrics']['correct_complete_physics_results'] is None
    assert result['utility'] is None


def test_real_graph_receipts_not_budget_and_reuse_does_not_add_calls(tmp_path):
    root = fixture(tmp_path)
    gr, host = connect_graph(tmp_path, root)
    graph.execute(gr, host, workers=1)
    result = cycle.outcome_metrics(root)
    use = result['resource_use']
    assert use['charged_ceiling']['calls'] == 2 and use['calls']['complete_count'] == 1
    assert use['model_tokens']['output_tokens']['total'] == 7
    assert use['model_tokens']['output_tokens']['total'] != use['graphs'][0]['reserved_output_tokens']
    assert len(use['call_receipts']) == 1
    assert use['cost'] == {'actual': None, 'estimated': None, 'currency': None}
    assert result['physics_validated'] is False


def test_unknown_tokens_not_zero_and_unobserved_reservation_not_observed_usage(tmp_path):
    root = fixture(tmp_path)
    connect_graph(tmp_path, root, unknown=True)
    commit(root, lambda s: s['resource_ledger'].append({'id': 'graph:' + str(tmp_path / 'unissued'),
        'ceiling': {'calls': 2, 'output_tokens': 128, 'wall_seconds': 20, 'native_attempts': 0}, 'basis': {}}))
    use = cycle.outcome_metrics(root)['resource_use']
    assert use['calls']['observed_count'] == 1 and use['calls']['complete_count'] is None
    assert use['model_tokens']['output_tokens']['total'] is None
    assert use['model_tokens']['output_tokens']['unknown_records'] == 1
    assert use['native_calls'] is None


def test_actual_completion_api_keeps_open_original_parent(tmp_path):
    root = fixture(tmp_path, parent=True)
    _, state = cycle._load(root)
    pin = completion_request(tmp_path, state['parent_task']['contract'])
    result = cycle.outcome_metrics(root, completion_request=pin)
    assert result['original_task']['recorded_parent_acceptance'] is False
    assert result['original_task']['state'] == 'unresolved'
    assert len(result['completion_input_pins']) >= 1


def test_completion_cannot_substitute_another_original_task(tmp_path):
    root = fixture(tmp_path, parent=True)
    other = tmp_path / 'other'; other.mkdir()
    _, cp = goal(other)
    pin = completion_request(other, cp)
    with pytest.raises(ValueError, match='exact original task'):
        cycle.outcome_metrics(root, completion_request=pin)


def add_attempts(base, root, mode='scripted_yes'):
    rd = base / 'ordinary'
    for identity, status, seconds in (('old', 'failed', 2), ('new', 'succeeded', 3)):
        write(rd / 'logs/execution/science' / identity / 'record.json', {
            'stage': 'science', 'attempt_id': identity, 'status': status, 'exit_code': 1 if status == 'failed' else 0,
            'started_utc': '2026-10-08T10:00:00+00:00', 'finished_utc': f'2026-10-08T10:00:0{seconds}+00:00'})
    write(rd / 'inputs/science-approval.json', {'approval_mode': mode, 'expert_review': False, 'quote': 'Synthetic fixture assent'})
    old = write(base / 'review.json', {'events': [
        {'event': 'review', 'verdict': 'send_back', 'role': 'physics_critic', 'actor_id': 'machine-fixture'},
        {'event': 'correction', 'redo_number': 1}, {'event': 'review', 'verdict': 'accept', 'claim_scope': 'source_api'}]})
    def update(state):
        e = state['experiments'][0]
        e['rundir'] = str(rd)
        e['observation'] = {'execution_status': 'succeeded', 'outcome': 'defined', 'receipt': None, 'measurement_present': True}
        e['adjudication'] = {'view': {'state': 'accepted'}, 'scope': 'source_api', 'snapshot': old}
    commit(root, update)
    return rd


@pytest.mark.parametrize('mode,classification', [('scripted_yes', 'machine_scripted_assent'), ('physicist', 'declared_physicist_mode')])
def test_retry_sendback_and_machine_or_declared_human_not_physics_truth(tmp_path, mode, classification):
    root = fixture(tmp_path)
    add_attempts(tmp_path, root, mode)
    result = cycle.outcome_metrics(root)
    assert {r['status'] for r in result['resource_use']['ordinary_attempts']} == {'failed', 'succeeded'}
    assert result['resource_use']['ordinary_stage_seconds']['total'] == 5
    assert result['interventions']['send_back_events'] == 1 and result['interventions']['correction_events'] == 1
    assert result['interventions']['approval_observations'][0]['classification'] == classification
    assert result['interventions']['human_interventions'] is None
    assert result['interventions']['physicist_interventions'] is None
    assert result['complete_experiment_census'][0]['recorded_acceptance_scope'] == 'source_api'
    assert result['complete_experiment_census'][0]['independent_correctness'] == 'unknown'


@pytest.mark.parametrize('status,outcome,label', [('failed', None, 'failed'), ('succeeded', None, 'partial'), ('succeeded', 'negative', 'recorded_component_result')])
def test_all_component_outcomes_preserved_without_effectiveness_credit(tmp_path, status, outcome, label):
    root = fixture(tmp_path)
    commit(root, lambda s: s['experiments'][0].update(observation={'execution_status': status, 'outcome': outcome}))
    result = cycle.outcome_metrics(root)
    assert result['complete_experiment_census'][0]['state'] == label
    assert result['complete_experiment_census'][0]['improvement_measured'] is False
    assert all(v is None for k, v in result['scientific_error_metrics'].items() if k != 'reason')


def test_declared_utility_has_original_criteria_and_no_default_reward(tmp_path):
    root = fixture(tmp_path, parent=True)
    _, state = cycle._load(root)
    declaration = {'schema_version': 1, 'kind': 'declared-research-utility',
        'original_contract': state['parent_task']['contract'], 'declaration_source': 'task_declaration',
        'statement': 'Synthetic user/task declaration; no origin authentication.',
        'goals': [{'id': 'full-task', 'statement': 'Preserve both experiments.', 'criteria': {'complete_original_request': True},
            'obligation_ids': ['original-request', 'atlas', 'cms']}]}
    pin = write(tmp_path / 'utility.json', declaration)
    result = cycle.outcome_metrics(root, utility_declaration=pin)
    assert result['utility']['declaration'] == declaration
    assert result['utility']['utility_value'] is None and result['utility']['origin_authenticated'] is False
    declaration['goals'][0]['obligation_ids'] = ['invented']
    with pytest.raises(ValueError, match='original task obligations'):
        cycle.outcome_metrics(root, utility_declaration=write(tmp_path / 'utility-bad.json', declaration))


def test_receipt_mutation_and_unaccounted_call_refuse(tmp_path):
    root = fixture(tmp_path)
    gr, _ = connect_graph(tmp_path, root)
    path = next((gr / 'calls').glob('*.json'))
    original = path.read_bytes()
    row = json.loads(original); row['result']['usage']['output_tokens'] = 999
    state_io.atomic_json(path, row)
    with pytest.raises(ValueError, match='receipt correlation'):
        cycle.outcome_metrics(root)
    path.write_bytes(original)
    state_io.atomic_json(gr / 'calls/extra.json', {'unaccounted': True})
    with pytest.raises(ValueError, match='unaccounted'):
        cycle.outcome_metrics(root)


def test_cli_and_typed_report_are_connected_and_read_only(tmp_path, capsys):
    root = fixture(tmp_path, parent=True)
    head = (root / 'head.json').read_bytes()
    out = tmp_path / 'report'
    assert cycle.main(['metrics', '--cycle', str(root), '--out', str(out)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['kind'] == 'research-outcome-metrics-report'
    assert len(result['files']) == 2
    assert (root / 'head.json').read_bytes() == head
    assert 'Independent physics correctness: unknown' in (out / 'research-outcomes.md').read_text()


def test_ending_source_mutation_and_writer_alias_cannot_claim_success(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    original = state_io.atomic_json
    def altered(path, value):
        original(path, value)
        if Path(path).name == 'research-outcomes.json':
            value['physics_validated'] = True
            Path(path).write_text('{}')
    monkeypatch.setattr(state_io, 'atomic_json', altered)
    with pytest.raises(ValueError, match='report changed'):
        metrics.write_report(root, tmp_path / 'report')
    assert (tmp_path / 'report/research-outcomes.json').exists()


def test_complete_source_port_or_vote_is_not_complete_correct_physics(tmp_path):
    root = fixture(tmp_path, parent=True)
    add_attempts(tmp_path, root)
    commit(root, lambda s: s['experiments'][0]['observation'].update(
        physics_validated=True, improvement_measured=True, self_reported_correct=True))
    result = cycle.outcome_metrics(root)
    assert result['original_task']['state'] == 'unresolved'
    assert result['original_task']['original_obligation_denominator'] == 4
    assert result['scientific_error_metrics']['correct_complete_physics_results'] is None
    assert not result['benefit_measured'] and not result['physics_validated']


def test_boolean_token_usage_is_refused_not_counted_as_one(tmp_path):
    root = fixture(tmp_path)
    gr, _ = connect_graph(tmp_path, root)
    checkpoint = state_io.read_json(gr / graph.STATE)
    identity = next(iter(checkpoint['calls']))
    path = gr / 'calls' / (identity + '.json')
    receipt = state_io.read_json(path)
    receipt['result']['usage']['input_tokens'] = True
    receipt['result_sha256'] = graph.digest(receipt['result'])
    checkpoint['calls'][identity]['receipt_sha256'] = graph.digest(receipt)
    state_io.atomic_json(path, receipt); state_io.atomic_json(gr / graph.STATE, checkpoint)
    with pytest.raises(ValueError, match='receipted input_tokens'):
        cycle.outcome_metrics(root)


def test_ending_receipt_addition_refuses_without_rebasing(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    gr, _ = connect_graph(tmp_path, root)
    original = metrics._Evidence.finish
    def altered(self):
        state_io.atomic_json(gr / 'calls/late.json', {'late': True})
        return original(self)
    monkeypatch.setattr(metrics._Evidence, 'finish', altered)
    with pytest.raises(ValueError, match='membership changed'):
        cycle.outcome_metrics(root)


def test_ending_prior_attempt_addition_cannot_disappear_from_denominator(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    rd = add_attempts(tmp_path, root)
    original = metrics._Evidence.finish
    def altered(self):
        (rd / 'logs/execution/science/late').mkdir()
        return original(self)
    monkeypatch.setattr(metrics._Evidence, 'finish', altered)
    with pytest.raises(ValueError, match='membership changed'):
        cycle.outcome_metrics(root)


def test_missing_attempt_record_stays_unknown_and_present_in_census(tmp_path):
    root = fixture(tmp_path)
    rd = add_attempts(tmp_path, root)
    (rd / 'logs/execution/science/interrupted-before-record').mkdir()
    result = cycle.outcome_metrics(root)
    assert len(result['resource_use']['unobserved_attempt_records']) == 1
    assert result['resource_use']['ordinary_stage_seconds']['total'] is None
    assert result['resource_use']['ordinary_stage_seconds']['observed_subtotal'] == 5


def test_unknown_graph_prevents_false_zero_token_or_time_total(tmp_path):
    root = fixture(tmp_path)
    commit(root, lambda s: s['resource_ledger'].append({'id': 'graph:' + str(tmp_path / 'unissued'),
        'ceiling': {'calls': 2, 'output_tokens': 100, 'wall_seconds': 20, 'native_attempts': 0}, 'basis': {}}))
    use = cycle.outcome_metrics(root)['resource_use']
    assert use['model_tokens']['output_tokens']['total'] is None
    assert use['call_seconds']['total'] is None
    assert use['calls']['complete_count'] is None


def test_synthesis_automatically_attaches_readout_to_ordinary_report(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    from ravel.workflow import scientific_report
    ctx = tmp_path / 'cycle/synthesis-context'
    _, state = cycle._load(root)
    cp = write(ctx / (state['context']['context_sha256'] + '.json'), state['context'])
    monkeypatch.setattr(cycle, 'status', lambda r: {'connected_task_complete': True, 'question': 'Synthetic report join', 'staged_protocol': None})
    # Only report delivery/authority is inert; the actual synthesis and metrics
    # composition run on real cycle state. No scientific worker or role invoked.
    monkeypatch.setattr(scientific_report, 'compose', lambda *a, **k: {'requested_quantity_completion': True,
        'requested_quantity_census': [{'exposed_fact_ids': ['one']}], 'report_text': 'Synthetic delivered quantity.', 'task_completion': None})
    result = cycle.synthesize(root, {'context': cp}, base_dir=tmp_path)
    assert result['outcome_metrics'] == result['report']['outcome_metrics']
    assert 'Research outcome instrumentation' in result['report']['report_text']
    assert result['physics_validated'] is False


def test_real_quantity_bound_report_consumes_metrics_without_new_dispatch(tmp_path, monkeypatch):
    root = fixture(tmp_path, parent=True)
    from ravel.workflow import scientific_context as context
    from test_research_cycle import report_request
    rd = tmp_path / 'supplied-report-source'
    supplied = write(rd / 'outputs/attempt-1/result.json', {'quantities': {'covariance': [[1.0]]}})
    def attach(state):
        state['context'] = context.apply_step(state['context'], {'id': 'supplied',
            'outputs': {'measurement': {k: supplied[k] for k in ('path', 'sha256')}},
            'code_status': 'success', 'actor_complete': False,
            'question': 'Synthetic delivered quantity from an inert fixture, not a worker.',
            'next_experiment': {'hypothesis': 'No physical claim.', 'change': 'None.',
                'measurement': 'Full supplied quantity.', 'if_supported': 'Retain scope.', 'if_not_supported': 'Retain failure.'}}, tmp_path)
    commit(root, attach)
    # Only the absent scientific-role authority is synthetic. Actual report
    # facts/context/task-completion/metrics composition and custody all execute.
    monkeypatch.setattr(cycle, 'status', lambda r: {'connected_task_complete': True,
        'question': 'Synthetic scope', 'staged_protocol': None})
    request = report_request(tmp_path, root, rd)
    request['artifact_request']['basis'][0]['path'] = 'context-request.json'
    request['artifact_request']['tools']['study']['path'] = str((rd / 'outputs/attempt-1/result.json').relative_to(tmp_path))
    result = cycle.synthesize(root, request, base_dir=tmp_path)
    assert '| 1.0 |' in result['report']['report_text']
    assert result['report']['requested_quantity_completion'] is True
    assert result['outcome_metrics']['original_task']['original_obligation_denominator'] == 4
    assert result['outcome_metrics']['original_task']['state'] == 'unresolved'
    assert result['parent_task_accepted'] is False


def test_actual_top_level_cli_routes_to_readout(tmp_path, capsys):
    root = fixture(tmp_path)
    from ravel import cli
    assert cli.main(['research-cycle', 'metrics', '--cycle', str(root)]) == 0
    assert json.loads(capsys.readouterr().out)['kind'] == 'research-outcome-metrics'


def test_copied_graph_or_alias_is_not_double_actual_usage(tmp_path):
    root = fixture(tmp_path)
    gr, _ = connect_graph(tmp_path, root)
    import shutil
    copy = tmp_path / 'copied-graph'; shutil.copytree(gr, copy)
    commit(root, lambda s: s['graphs'].append({'root': str(copy), 'usage': {'calls': 1}, 'complete': True}))
    with pytest.raises(ValueError, match='Graph instance'):
        cycle.outcome_metrics(root)


def test_existing_complete_report_text_cap_is_preserved(tmp_path, monkeypatch):
    root = fixture(tmp_path)
    from ravel.workflow import scientific_report
    _, state = cycle._load(root)
    cp = write(root / 'synthesis-context' / (state['context']['context_sha256'] + '.json'), state['context'])
    monkeypatch.setattr(cycle, 'status', lambda r: {'connected_task_complete': True, 'question': 'Synthetic cap', 'staged_protocol': None})
    monkeypatch.setattr(scientific_report, 'compose', lambda *a, **k: {'requested_quantity_completion': True,
        'requested_quantity_census': [{'exposed_fact_ids': ['one']}],
        'report_text': 'a' * scientific_report.MAX_TEXT_BYTES, 'task_completion': None})
    with pytest.raises(ValueError, match='existing text budget'):
        cycle.synthesize(root, {'context': cp}, base_dir=tmp_path)
