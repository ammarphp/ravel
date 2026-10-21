"""Research-protocol enforcement negative controls. Inert outputs, no physics/provider processes."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import research_cycle as c, research_protocol as p, science, physics_review, research_evaluation
from test_research_cycle import contract, write
from test_research_protocol_followup import hypothesis, selection, stop_trace


def campaign(tmp_path, regime=None, *, budget=None):
    root = tmp_path/'cycle'
    value = contract(tmp_path)
    if budget is not None:
        value['budget'].update(budget)
    if regime is not None:
        value['research_regime'] = regime
    c.create(root, value, base_dir=tmp_path, evaluation_harness=True)
    return root


def observed(tmp_path, monkeypatch, measured=0, *, max_rounds=3, hidden_ids=None, budget=None):
    root = campaign(tmp_path, 'closed_scored', budget=budget)
    p.bind_default(root, regime='closed_scored')
    rule = {'direction': 'maximize', 'metric': 'response', 'k': 1, 'alpha': .05}
    prereg = write(root/'prospective.json', {'schema_version': 1, 'kind': 'research-preregistration',
        'selection_rule': rule, 'stop_rule': {'successes': 2, 'max_rounds': max_rounds, 'budget': 30,
                                           'coverage_floor': 1, 'families': ['f0']},
        'withheld_cells': [{'id': 'confirm', 'population': write(tmp_path/'hidden.json',
            {'ids': ['new-data'] if hidden_ids is None else hidden_ids})}],
        'approximations': [], 'expected_effect': {'statement': 'synthetic'},
        'evaluator_not_applicable': {k: 'pure control' for k in
            ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    p.preregister(root, prereg, {}, evaluation_harness=True)
    _, state = c._load(root)
    h = hypothesis()
    state['events'].append({'kind': 'hypothesis', 'hypothesis': h})
    rd = tmp_path/'run'
    write(rd/'attempt.json', {'status': 'succeeded', 'wall_seconds': 2})
    write(rd/'outputs/attempt-1/result.json', {'metric': measured, 'p': .5, 'decision': 'worse'})
    e = {'id': 'e0', 'rundir': str(rd), 'observation': None, 'premise_bindings': {},
         'study': write(tmp_path/'study.json', {'synthetic': True}), 'input_pins': [], 'plan': None,
         'observable': {'pointer': '/metric', 'outcomes': {'positive': 1, 'zero': 0}},
         'predictions': {'h0': 'positive'}, 'context_outputs': {}, 'question': 'measure', 'change': 'measure',
         'evaluation': {'candidate': 'c0', 'family': 'f0', 'round': 1, 'purpose': 'full',
                        'cells': ['select'], 'seeds': [11], 'generation': 'g0',
                        'value_pointer': '/metric', 'p_value_pointer': '/p', 'decision_pointer': '/decision'}}
    state['experiments'].append(e)
    c._commit(root, state, 'fixture_prepared')
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **k: None)
    monkeypatch.setattr(science, 'packet', lambda *a, **k: {'execution': {'status': 'succeeded'}, 'errors': []})
    monkeypatch.setattr(science.execution, 'load_execution', lambda *a, **k: {'stages': {'science': {
        'status': 'succeeded', 'attempt_id': 'attempt-1', 'attempt_record': 'attempt.json'}}})
    state = c.observe(root, 'e0')
    return root, state


@pytest.mark.parametrize('measured,expected', [(0, 'weakened'), (1, 'survived_test')])
def test_live_observe_changes_register(tmp_path, monkeypatch, measured, expected):
    _, state = observed(tmp_path, monkeypatch, measured)
    assert c.replay_register(state['events'], base_dir=tmp_path)['h0']['status'] == expected


def test_live_observe_can_be_refuted(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch)
    monkeypatch.setattr(c, '_current_evidence', lambda *a, **k: None)  # independent review seam only
    comparator = write(tmp_path/'comparison.json', {'kind': 'prediction-comparison', 'hypothesis_id': 'h0',
        'comparison': 'differs', 'scope': 'declared domain', 'observable': 'response', 'experiment_id': 'e0'})
    sensitivity = write(tmp_path/'power.json', {'kind': 'sensitivity-check', 'status': 'passed',
        'scope': 'declared domain', 'observable': 'response', 'experiment_id': 'e0'})
    state = c.register_exclusion_evidence(root, 'h0', 'e0', comparator=comparator, sensitivity=sensitivity)
    assert c.replay_register(state['events'], base_dir=tmp_path)['h0']['status'] == 'refuted'


def test_commit_refuses_invented_trial(tmp_path):
    root = campaign(tmp_path)
    request = write(tmp_path/'selection.json', selection(tmp_path))
    with pytest.raises(ValueError, match='observ|evaluation|census'):
        p.commit_selection(root, request)


def test_observation_produces_evaluation_record(tmp_path, monkeypatch):
    _, state = observed(tmp_path, monkeypatch)
    rows = [e['evaluation'] for e in state['events'] if e['kind'] == 'research_evaluation_observed']
    assert len(rows) == 1 and rows[0]['value'] == 0 and rows[0]['cost'] == 2
    assert rows[0]['p_value'] == .5 and rows[0]['source'] == state['experiments'][0]['observation']['result']


def test_default_confirmation_dispatch_is_not_noop(tmp_path):
    root = campaign(tmp_path)
    _, state = c._load(root)
    state['experiments'].append({'id': 'confirm', 'evaluation': {'candidate': 'c0', 'purpose': 'confirm',
        'cells': ['withheld'], 'seeds': [31], 'generation': 'fresh'}})
    with pytest.raises(ValueError, match='confirm_read_before_selection'):
        p.record_confirmation_dispatch(root, state, 'confirm')


def test_seed_alias_is_same_exposure(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    assert p.confirmation_errors(receipt, [], {'candidate': 'c0', 'cells': ['fresh'],
        'seeds': ['11'], 'generation': 'fresh'}) == ['confirm_cell_in_selection_inputs']


def test_gate_missing_provider_refuses_instead_of_crash(tmp_path, monkeypatch):
    from ravel.workflow import research_admission
    monkeypatch.setattr(research_admission, 'decision_provider', lambda: None)
    errors = p.gate_errors(tmp_path, 'research_choice', {'purpose': 'confirm'})
    assert errors and errors[0].code == 'decision_gate_unavailable'


def test_real_decision_gate_seam(tmp_path):
    from ravel.workflow import decision_gate as dg
    errors = p.decision_errors(tmp_path, {'scope': 'validate'})
    assert errors and all(isinstance(e, dg.GateError) for e in errors)
    # The registry already composes the research provider; the seam must not repeat it.
    assert len(errors) == len(set(errors))


@pytest.mark.parametrize('mode', ['reproduce', 'reinterpret'])
def test_ordinary_delivery_cannot_bypass_protocol(tmp_path, mode):
    write(tmp_path/'inputs/task_contract.json', {'task_mode': mode})
    errors = physics_review.gate_errors(tmp_path, 'delivery')
    assert any('protocol_unbound' in e for e in errors)


@pytest.mark.parametrize('stage', ['baseline', 'validate', 'acceptance'])
def test_reason_alone_cannot_disable_stage(tmp_path, stage):
    with pytest.raises(ValueError, match='applicab'):
        p.validate_stage_artifact(stage, {'status': 'not_applicable', 'reason': 'not needed'},
                                  base_dir=tmp_path, regime='closed_scored')


def test_claim_acceptance_refuses_pending_producer(tmp_path):
    with pytest.raises(ValueError, match='producer_pending:P'):
        p.validate_stage_artifact('acceptance', {'claims': [{'id': 'claim', 'kind': 'finding',
            'N': 0, 'verdict': 'accepted'}]}, base_dir=tmp_path, regime='closed_scored')


def test_plain_agreement_does_not_invent_selection(tmp_path):
    pin = write(tmp_path/'agreement.json', {'source': 'synthetic agreement ledger'})
    claim = {'kind': 'agreement', 'N': 0, 'verdict': 'exploratory', 'agreement_ledger': pin, 'noise_model': pin}
    p.validate_selection_claim(claim, base_dir=tmp_path)


def test_first_stop_boundary_is_enforced(tmp_path):
    value = stop_trace(tmp_path)
    extra = write(tmp_path/'extra.json', {'kind': 'research-select-result', 'exposure': 'adaptive_full',
        'candidate': 'c1', 'family': 'f1', 'status': 'success', 'decision': 'worse', 'cost': 1})
    value['rounds'].append({'round': 2, 'candidates': ['c1'], 'successes': 0, 'results': [extra]})
    with pytest.raises(ValueError, match='past.*stop|after.*stop'):
        p.computed_stop(value, base_dir=tmp_path)


def test_n_counts_repeat_evaluations(tmp_path):
    request = selection(tmp_path)
    repeat = write(tmp_path/'repeat.json', {'candidate': 'c0', 'value': 1., 'status': 'success',
        'cells': ['select-2'], 'seeds': [13], 'generation': 'selection-2'})
    request['trials'].append({'id': 'repeat', 'candidate': 'c0', 'result': repeat})
    receipt = p.selection_receipt(request, base_dir=tmp_path)
    assert receipt['N'] == 3 and receipt['candidates_considered'] == 2
    assert receipt['candidate_values']['c0'] == 2.0


def test_status_boolean_is_not_disable_switch():
    p.validate_protocol_controls({'normalization_ledger_present': True})


def test_invalid_operator_refused():
    h = hypothesis(); h['operator'] = 'made_up'
    with pytest.raises(ValueError, match='operator'):
        c.replay_register([{'kind': 'hypothesis', 'hypothesis': h}])


def test_finding_with_metric_cannot_bypass_selection(tmp_path):
    with pytest.raises(ValueError, match='selection|trials'):
        p.validate_selection_claim({'kind': 'finding', 'N': 999, 'metric': 'score'}, base_dir=tmp_path)


def test_shared_ledger_rejects_cross_campaign_and_ml_reads(tmp_path, monkeypatch):
    from ravel.physics import ml_exposure as exposure
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(tmp_path/'state'))
    population = {'sha256': 'a'*64, 'byte_sha256': 'b'*64,
                  'event_ids': ['event-1'], 'group_ids': ['group-1'], 'value_hashes': ['value-1']}
    action = {'candidate': 'c0', 'cells': ['confirm'], 'seeds': [31], 'generation': 'fresh',
              'populations': [population]}
    p.reserve_study_exposure('study-1', action, selection_sha256='c'*64)
    with pytest.raises(ValueError, match='claimed|read|spent'):
        p.reserve_study_exposure('study-2', action, selection_sha256='d'*64)
    with pytest.raises(ValueError, match='claimed|read|spent'):
        exposure.Study('e'*64).claim(population, 'test_split', schedule={population['sha256']: ['x']})


def test_concurrent_confirmation_reserves_once(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(tmp_path/'state'))
    action = {'candidate': 'c0', 'cells': ['confirm'], 'seeds': [31], 'generation': 'fresh',
              'populations': [{'sha256': 'a'*64, 'byte_sha256': 'b'*64,
                              'event_ids': ['e'], 'group_ids': ['g'], 'value_hashes': ['v']}]}
    def attempt(i):
        try:
            p.reserve_study_exposure(str(i), action, selection_sha256='c'*64)
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, [0, 1])) == [False, True]


def test_stop_blocks_next_dispatch_from_observed_journal(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch)
    state['methodology'] = {'preregistration': write(tmp_path/'prereg.json', {'stop_rule': {
        'successes': 2, 'max_rounds': 1, 'budget': 4, 'coverage_floor': 1, 'families': ['f0']}})}
    state['experiments'].append({'id': 'e1', 'evaluation': {**state['experiments'][0]['evaluation'], 'round': 2}})
    with pytest.raises(ValueError, match='stop'):
        p.enforce_dispatch_stop(state, 'e1')


def test_substituted_result_cannot_be_selected(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch)
    forged = write(tmp_path/'forged.json', {'candidate': 'c0', 'value': 99, 'status': 'success',
        'cells': ['select'], 'seeds': [11], 'generation': 'g0'})
    request = {'rule': selection(tmp_path)['rule'], 'regime': 'closed_scored',
               'trials': [{'id': 'e0', 'candidate': 'c0', 'result': forged}]}
    with pytest.raises(ValueError, match='observ|evaluation|census'):
        p.commit_selection(root, write(tmp_path/'request.json', request))


def test_signature_whitespace_does_not_reopen_refuted(tmp_path):
    h = hypothesis()
    previous = {**h, 'status': 'refuted', 'refutation_signature': h['identity_signature']}
    h = deepcopy(h); h['id'] = 'h1'; h['identity_signature']['scope'] += '  '
    with pytest.raises(ValueError, match='what_is_new'):
        c._register_hypothesis(h, {'h0': previous}, tmp_path)


def test_signature_change_must_be_applied(tmp_path):
    h = hypothesis()
    previous = {**h, 'status': 'refuted', 'refutation_signature': h['identity_signature']}
    h = deepcopy(h); h['id'] = 'h1'; h['what_is_new'] = {'scope': 'new domain'}
    h['reopening_receipt'] = write(tmp_path/'reopen.json', {'kind': 'new_evidence', 'sensitivity': .9})
    with pytest.raises(ValueError, match='applied|signature'):
        c._register_hypothesis(h, {'h0': previous}, tmp_path)


def test_disjoint_confirmation_cells_can_run_separately(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    reads = [{'candidate': 'c0', 'cells': ['a'], 'seeds': [31], 'generation': 'fresh-a'}]
    assert p.confirmation_errors(receipt, reads, {'candidate': 'c0', 'cells': ['b'],
        'seeds': [32], 'generation': 'fresh-b'}) == []


def test_deterministic_confirmation_needs_no_invented_pvalue(tmp_path):
    request = selection(tmp_path)
    request['rule']['confirmation_criterion'] = {'op': 'ge', 'value': 0.5}
    receipt = p.selection_receipt(request, base_dir=tmp_path)
    pin = write(tmp_path/'confirm.json', {'candidate': 'c0', 'value': 1., 'status': 'success',
        'cells': ['fresh'], 'seeds': [31], 'generation': 'fresh'})
    report = p.selection_report(receipt, [pin], base_dir=tmp_path)
    assert report['promoted'] == ['c0']
    assert report['selected_result_on_confirm'][0].get('p_value') is None


def test_coverage_unmet_cap_is_deliverable(tmp_path):
    value = stop_trace(tmp_path)
    value['stop'].update(coverage_floor=2, max_rounds=1, reason='coverage_unmet')
    result = p.computed_stop(value, base_dir=tmp_path)
    assert result['reason'] == 'coverage_unmet' and result['uncovered_families'] == ['f1']


def test_read_recovery_requires_failed_observation_without_result(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='failed|confirmation'):
        p.void_confirmation(root, 'e0')


def test_replay_uses_exclusion_snapshots(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch)
    monkeypatch.setattr(c, '_current_evidence', lambda *a, **k: None)
    comparator = write(tmp_path/'comparison.json', {'kind': 'prediction-comparison', 'hypothesis_id': 'h0',
        'comparison': 'differs', 'scope': 'declared domain', 'observable': 'response', 'experiment_id': 'e0'})
    sensitivity = write(tmp_path/'power.json', {'kind': 'sensitivity-check', 'status': 'passed',
        'scope': 'declared domain', 'observable': 'response', 'experiment_id': 'e0'})
    state = c.register_exclusion_evidence(root, 'h0', 'e0', comparator=comparator, sensitivity=sensitivity)
    Path(comparator['path']).unlink(); Path(sensitivity['path']).unlink()
    assert c.replay_register(state['events'], base_dir=tmp_path)['h0']['status'] == 'refuted'


def test_stage_preparation_calls_real_gate_seam(tmp_path, monkeypatch):
    root = campaign(tmp_path); p.bind_default(root)
    artifact = write(tmp_path/'stage.json', {'limitations': [{'id': 'L1'}]})
    # The real aggregator refuses a campaign without its pinned run inputs.
    with pytest.raises(ValueError, match='gate_inputs_invalid'):
        p.prepare_stage(root, 'limitation_census', artifact, tmp_path/'out', model='fixture')
    from ravel.workflow import research_admission
    monkeypatch.setattr(research_admission, 'decision_provider', lambda: None)
    with pytest.raises(ValueError, match='decision_gate_unavailable'):
        p.prepare_stage(root, 'limitation_census', artifact, tmp_path/'out', model='fixture')


@pytest.mark.parametrize('mode', ['reproduce', 'reinterpret'])
def test_ordinary_intake_binds_protocol_without_research_child(tmp_path, mode):
    from ravel.workflow import workflow_state
    from ravel.validation.validate_run_state import _base_contract
    contract = _base_contract(task_mode=mode)
    write(tmp_path/'inputs/task_contract.json', contract)
    assert workflow_state.main(['init', '--rundir', str(tmp_path)]) == 0
    assert p.methodology_status(tmp_path)['record']['kind'] == 'research-protocol'
    assert not (tmp_path/'head.json').exists()


def test_missing_preregistered_rules_refused_before_compute(tmp_path):
    from test_research_default_protocol import governed_cycle
    root = governed_cycle(tmp_path)
    pin = write(root/'prereg.json', {'schema_version': 1, 'kind': 'research-preregistration',
        'approximations': [], 'expected_effect': {'statement': 'fixture'},
        'evaluator_not_applicable': {k: 'not relevant' for k in
            ('limit_setter', 'likelihood_builder', 'cutflow_comparator')}})
    with pytest.raises(ValueError, match='selection_rule|stop'):
        p.preregister(root, pin, {}, evaluation_harness=True)


def test_observe_selection_dispatch_confirmation_report(tmp_path, monkeypatch):
    """Real cycle journal and evaluator; ordinary executor and decision provider are inert seams."""
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'ledger'))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(tmp_path/'ledger'))
    monkeypatch.setattr(p, 'decision_errors', lambda *a, **k: [])
    root, state = observed(tmp_path, monkeypatch)
    rule = selection(tmp_path)['rule']
    selected_source = state['experiments'][0]['observation']['result']
    request = {'rule': rule, 'regime': 'closed_scored',
               'trials': [{'id': 'e0', 'candidate': 'c0', 'result': selected_source}]}
    receipt = p.commit_selection(root, write(root/'select.json', request))
    assert receipt['N'] == 1 and receipt['candidate_values']['c0'] == 0
    _, state = c._load(root)
    population = write(tmp_path/'hidden.json', {'ids': ['new-data']})
    e = deepcopy(state['experiments'][0]); e.update(id='confirm', observation=None)
    rd = tmp_path/'confirm-run'; e['rundir'] = str(rd)
    e['input_pins'] = [population]
    e['evaluation'].update(purpose='confirm', cells=['confirm'], seeds=[31], generation='g1', population_pins=[population])
    write(rd/'attempt.json', {'status': 'succeeded', 'wall_seconds': 1})
    write(rd/'outputs/attempt-1/result.json', {'metric': 1, 'p': .001, 'decision': 'better'})
    state['experiments'].append(e)
    state = c._commit(root, state, 'fixture_confirmation_prepared')
    research_evaluation.prepare_dispatch_action(root, 'confirm')
    state = p.record_confirmation_dispatch(root, state, 'confirm')
    state = c.observe(root, 'confirm')
    report = p.selection_report(receipt, [state['experiments'][-1]['observation']['result']], base_dir=root, state=state)
    assert report['promoted'] == ['c0'] and report['selected_result_on_confirm'][0]['p_value'] == .001
    reads = p.verify_selection_journal(state, receipt)
    assert len(reads) == 1 and reads[0]['ledger']['records']
    with pytest.raises(ValueError, match='confirm_reads_exceed_k'):
        p.record_confirmation_dispatch(root, state, 'confirm')


def test_unrecommended_allocator_action_refused(tmp_path):
    from test_experiment_allocator import diagnosis_case, diagnosis_policy
    from ravel.workflow import experiment_allocator as allocator
    case = diagnosis_case(tmp_path)
    recommendation = allocator.allocate(case, diagnosis_policy(), base_dir=tmp_path)
    items = {a['id']: {'allocator_recommendation': recommendation['allocator_recommendation'],
             'allocation': recommendation, 'candidate': 'c0'} for a in case['actions']}
    state = {'base_dir': tmp_path, 'contract': {'budget': {'wall_seconds': 12}},
             'hypotheses': case['hypotheses'], 'experiments': [
                 {'id': a['id'], 'observation': None, 'cost': {'wall_seconds': a['cost']},
                  'predictions': {h['id']: h['predictions'][a['id']] for h in case['hypotheses']}}
                 for a in case['actions']], 'events': [{'kind': 'research_allocation',
                 'case': write(tmp_path/'case.json', case), 'policy': write(tmp_path/'policy.json', diagnosis_policy()),
                 'work_items': items}]}
    assert p._allocation_errors(state, 'generation') == ['allocator_action_not_next']


def test_screen_overlap_cannot_be_omitted_from_selection(tmp_path):
    state = {'events': [], 'methodology': {'stages': [{'id': 'screen', 'artifact': write(tmp_path/'screen.json',
        {'subset': {'cells': ['hidden']}})}]}}
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p._methodology_journal_guard(state, 'validate', {'withheld_cells': ['hidden']},
                                    base_dir=tmp_path, regime='closed_scored')


def test_failed_confirmation_has_one_typed_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path/'ledger'))
    monkeypatch.setenv('RAVEL_ML_TEST_NAMESPACE', str(tmp_path/'ledger'))
    monkeypatch.setattr(p, 'decision_errors', lambda *a, **k: [])
    root, state = observed(tmp_path, monkeypatch, hidden_ids=['fresh'])
    request = {'rule': selection(tmp_path)['rule'], 'regime': 'closed_scored', 'trials': [
        {'id': 'e0', 'candidate': 'c0', 'result': state['experiments'][0]['observation']['result']}]}
    p.commit_selection(root, write(root/'select.json', request))
    _, state = c._load(root)
    population = write(tmp_path/'hidden.json', {'ids': ['fresh']})
    e = deepcopy(state['experiments'][0]); e.update(id='confirm', observation=None)
    rd = tmp_path/'failed'; e['rundir'] = str(rd); e['input_pins'] = [population]
    e['evaluation'].update(purpose='confirm', cells=['confirm'], seeds=[31], generation='fresh', population_pins=[population])
    write(rd/'attempt.json', {'status': 'failed', 'wall_seconds': 1})
    state['experiments'].append(e); state = c._commit(root, state, 'fixture_failed_prepared')
    research_evaluation.prepare_dispatch_action(root, 'confirm')
    p.record_confirmation_dispatch(root, state, 'confirm')
    monkeypatch.setattr(science.execution, 'load_execution', lambda *a, **k: {'stages': {'science': {
        'status': 'failed', 'attempt_id': 'attempt-1', 'attempt_record': 'attempt.json'}}})
    monkeypatch.setattr(science, 'packet', lambda *a, **k: {'execution': {'status': 'failed'}, 'errors': []})
    c.observe(root, 'confirm')
    state = p.void_confirmation(root, 'confirm')
    assert state['events'][-1]['kind'] == 'research_confirmation_void'
    from ravel.physics.ml_exposure import verify_research_read
    verify_research_read(state['events'][-1]['read'])  # still spent, never erased
    with pytest.raises(ValueError, match='already consumed'):
        p.void_confirmation(root, 'confirm')


def test_stop_continuation_requires_exact_recorded_decision(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch, max_rounds=1)
    e = deepcopy(state['experiments'][0]); e.update(id='next', observation=None); e['evaluation']['round'] = 2
    state['experiments'].append(e); state = c._commit(root, state, 'fixture_stopped')
    with pytest.raises(ValueError, match='stop'):
        p.enforce_dispatch_stop(state, 'next')
    from ravel.workflow.research_evaluation import stop_state
    stop = stop_state(state); rule = {**stop['rule'], 'max_rounds': 2}
    action = {'scope': 'validate', 'operation': 'continue_after_stop', 'stop_sha256': stop['sha256'], 'stop_rule': rule}
    case = write(root/'case.json', {'schema_version': 2, 'synthetic': True})
    receipt = write(root/'decision.json', {'schema_version': 1, 'kind': 'rdj-receipt', 'outcome': 'authorize',
        'gate': 'research_choice', 'action_digest': p.ce.digest(action), 'class': 'R2', 'open_a_findings': 0,
        'unresolved_branches': 0, 'case': case, 'case_sha256': case['sha256']})
    monkeypatch.setattr(p, 'decision_errors', lambda *a, **k: [])  # separate provider boundary tested independently
    state = p.authorize_stop_continuation(root, rule, {'rdj_receipt': receipt})
    p.enforce_dispatch_stop(state, 'next')
    assert state['events'][-1]['kind'] == 'research_stop_continuation'


ORDINARY_PROMPTS = {
    'reproduce': 'Reproduce the published 95% CLs exclusion limit of a synthetic search for a heavy scalar decaying to two jets.',
    'reinterpret': 'Reinterpret a synthetic published search for a new vector boson model.'}


@pytest.mark.parametrize('mode', ['reproduce', 'reinterpret'])
def test_cli_intake_writer_binds_common_protocol(tmp_path, mode):
    from ravel import cli
    root = tmp_path/'run'
    assert cli.main(['initiate', '--prompt', ORDINARY_PROMPTS[mode], '--out', str(root)]) == 0
    assert json.loads((root/'inputs/task_contract.json').read_text())['task_mode'] == mode
    assert p.methodology_status(root)['record']['kind'] == 'research-protocol'


def test_deleted_dispatch_marker_cannot_bypass_bound_plan(tmp_path):
    from ravel.workflow.research_evaluation import verify_run_dispatch
    write(tmp_path/'inputs/science-plan.json', {'research_binding': {'root': str(tmp_path/'cycle'), 'experiment_id': 'e'}})
    with pytest.raises(ValueError, match='binding|reservation'):
        verify_run_dispatch(tmp_path)


def test_science_plan_pins_research_dispatch_binding(tmp_path):
    from test_research_cycle import propose, experiment
    root = tmp_path/'campaign'
    c.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    propose(tmp_path, root)
    c.design(root, experiment(tmp_path, 'e', grouped=False))
    rd = tmp_path/'planned'
    binding = {'root': str(root), 'experiment_id': 'e'}
    c.prepare_experiment(root, 'e', rd)
    plan = science.verify_plan(rd)
    assert plan['research_binding'] == binding
    assert str(rd/'inputs/research-experiment.json') in plan['stage_binding']['input_snapshot']
    (rd/'inputs/research-experiment.json').unlink()
    with pytest.raises((OSError, ValueError)):
        science.verify_plan(rd)


def test_stop_trace_cannot_replace_prospective_rule(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch, max_rounds=1)
    artifact = p.validation_trace(root)
    artifact['stop']['budget'] += 1
    with pytest.raises(ValueError, match='prospective|rule'):
        p.computed_stop(artifact, base_dir=state['base_dir'], state=state)


def test_stop_dispatch_and_report_agree_when_caps_coincide(tmp_path, monkeypatch):
    root, state = observed(tmp_path, monkeypatch, max_rounds=1)
    # Actual elapsed time is set at observation, never an authored stop receipt.
    from ravel.workflow.research_evaluation import stop_state
    prereg = p._method_json(state['methodology']['preregistration'], state['base_dir'])
    prereg['stop_rule']['budget'] = 2
    # Exercise pure stop arithmetic on a copied state without changing the journal.
    state['methodology']['preregistration'] = write(tmp_path/'prospective-coincident.json', prereg)
    stop = stop_state(state)
    assert stop['reason'] == 'max_rounds'


def test_common_rebind_preserves_existing_regime(tmp_path):
    from ravel.workflow.research_admission import admission
    write(tmp_path/'inputs/task_contract.json', {'task_mode': 'reproduce'})
    p.bind_default(tmp_path, regime='closed_scored')
    assert admission(tmp_path, 'approve_plan', bind=True) == []
    assert p.methodology_status(tmp_path)['record']['regime'] == 'closed_scored'


@pytest.mark.parametrize('broken', [None, {}, {'purpose': 'full'},
    {'candidate': 'c0', 'family': 'f0', 'round': 0, 'purpose': 'full', 'cells': ['a'], 'seeds': [1],
     'generation': 'g', 'population_pins': [{'path': 'p.json', 'sha256': '0'*64}], 'value_pointer': '/m'},
    {'candidate': 'c0', 'family': 'f0', 'round': 1, 'purpose': 'full', 'cells': ['a'], 'seeds': [1],
     'generation': 'g', 'population_pins': [{'path': 'p.json', 'sha256': '0'*64}], 'value_pointer': 'm'},
    {'candidate': 'c0', 'family': 'f0', 'round': 1, 'purpose': 'full', 'cells': ['a'], 'seeds': [1],
     'generation': 'g', 'population_pins': [], 'value_pointer': '/m'}])
def test_design_refuses_malformed_evaluation_before_execution(tmp_path, broken):
    root = campaign(tmp_path)
    _, state = c._load(root)
    experiment = {key: None for key in ('question', 'premise_ids', 'parent', 'change', 'study', 'cost',
        'predictions', 'observable', 'context_outputs', 'acceptance_scope', 'exploratory')}
    experiment.update(id='e9', evaluation=broken)
    with pytest.raises(ValueError, match='evaluation'):
        c._append_design(state, experiment)
