"""Synthetic protocol boundaries; no native, provider or physics execution."""
from copy import deepcopy
import json

import pytest

from ravel.workflow import research_protocol as p, research_cycle as cycle
from test_research_protocol import make
from test_research_default_protocol import write


def selection(root, *, k=1):
    trials = []
    for i, value in enumerate([3.0, 0.0]):
        result = write(root, f'trial-{i}.json', {'candidate': f'c{i}', 'value': value,
            'cells': ['select'], 'seeds': [11+i], 'generation': 'selection-data', 'status': 'success'})
        trials.append({'id': f't{i}', 'candidate': f'c{i}', 'result': result})
    return {'rule': {'direction': 'maximize', 'metric': 'response', 'k': k, 'alpha': .05},
            'trials': trials, 'regime': 'closed_scored'}


def test_full_refuses_withheld_cell(tmp_path, monkeypatch):
    root, protocol = make(tmp_path, monkeypatch)
    protocol['cells'][1]['exposure'] = 'withheld_confirmation'
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p.validate(protocol, base_dir=tmp_path, state=cycle._load(root)[1])


def test_confirm_read_without_selection_refused():
    assert 'confirm_read_before_selection' in p.confirmation_errors(None, [], {'candidate': 'c0'})


def test_confirm_once_and_selected_k(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path, k=2), base_dir=tmp_path)
    reads = [{'candidate': 'c0', 'selection_sha256': receipt['sha256']}]
    assert 'confirm_reads_exceed_k' in p.confirmation_errors(receipt, reads, {'candidate': 'c0'})
    assert not p.confirmation_errors(receipt, reads, {'candidate': 'c1'})
    assert 'confirm_reads_exceed_k' in p.confirmation_errors(receipt, reads, {'candidate': 'other'})


def test_holm_stepdown():
    assert p.holm([.01, .04, .03], alpha=.05) == [True, False, False]


def test_claim_missing_trials_refused(tmp_path):
    with pytest.raises(ValueError, match='trials_unreported'):
        p.validate_stage_artifact('acceptance', {'claims': [{'id': 'c', 'kind': 'performance',
            'verdict': 'exploratory'}]}, base_dir=tmp_path, regime='closed_scored')


def test_fresh_seed_fluctuation_not_promoted_and_null_delivers(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    assert receipt['N'] == 2 and receipt['selected'] == ['c0']
    confirm = write(tmp_path, 'confirm.json', {'candidate': 'c0', 'value': 0., 'p_value': .5,
        'cells': ['confirm'], 'seeds': [31], 'generation': 'fresh-data', 'status': 'success'})
    result = p.selection_report(receipt, [confirm], base_dir=tmp_path)
    assert result['N'] == 2 and result['promoted'] == [] and result['status'] == 'null_funnel'
    assert result['deliverable'] and result['selected_result_on_confirm'][0]['value'] == 0.


@pytest.mark.parametrize('field,value', [('cells', ['select']), ('seeds', [11]), ('generation', 'selection-data')])
def test_confirmation_disjoint_from_all_selection_inputs(tmp_path, field, value):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    measured = {'candidate': 'c0', 'value': 4., 'p_value': .001, 'cells': ['confirm'],
                'seeds': [31], 'generation': 'fresh-data', 'status': 'success'}
    measured[field] = value
    pin = write(tmp_path, 'confirm.json', measured)
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p.selection_report(receipt, [pin], base_dir=tmp_path)


def test_research_route_without_binding_refused():
    state = {'contract': {'route': 'research'}, 'events': []}
    assert p.eligibility(state, 'action') == ['protocol_unbound']


def test_every_mandatory_protocol_is_bound(tmp_path):
    record = p.bind_default(tmp_path)
    assert {r['id'] for r in record['mandatory_protocols']} == {f'P{i:02}' for i in range(1, 18)}
    record['mandatory_protocols'].pop()
    (tmp_path/'research/protocol.json').write_text(json.dumps(record))
    with pytest.raises(ValueError, match='mandatory'):
        p.methodology_status(tmp_path)


@pytest.mark.parametrize('config', [
    {'properties': {'enable_p08': {'type': 'boolean'}}},
    {'properties': {'protocols': {'properties': {'P01': {'type': 'boolean'}}}}},
    {'--disable-confirmation': {'action': 'store_true'}},
    {'board_enabled': True},
])
def test_mandatory_protocol_toggle_scan(config):
    with pytest.raises(ValueError, match='mandatory_protocol_toggle'):
        p.validate_protocol_controls(config)
    assert p.validate_protocol_controls(config, evaluation_harness=True) is None


def hypothesis():
    return {'id': 'h0', 'statement': 'A positive response survives the declared test.',
        'identity_signature': {'observable': 'response', 'scope': 'declared domain', 'prediction': 'positive'},
        'kill_condition': {'comparison': 'differs', 'observable': 'response'},
        'reopening_trigger': {'kind': 'new_evidence', 'field': 'sensitivity', 'op': 'gt', 'value': .8},
        'operator': 'limitation_fix', 'what_is_new': None}


def register_events():
    h = hypothesis()
    return [{'kind': 'hypothesis', 'hypothesis': h}]


def observation(**changes):
    return {'execution_status': 'success', 'comparison': 'differs',
        'residual': {'observable': 'response', 'predicted': 'positive', 'measured': 'zero',
                     'interval': None, 'sign': 'different', 'constraint_violated': 'positive'},
        'comparator': None, 'sensitivity': None, **changes}


def test_register_replay_is_byte_identical_and_status_not_model_writable():
    events = register_events()
    events.append({'kind': 'test', 'hypothesis_id': 'h0', 'observation': observation()})
    a = json.dumps(cycle.replay_register(events), sort_keys=True, separators=(',', ':')).encode()
    assert a == json.dumps(cycle.replay_register(deepcopy(events)), sort_keys=True, separators=(',', ':')).encode()
    assert cycle.replay_register(events)['h0']['status'] == 'weakened'
    events[0]['hypothesis']['status'] = 'refuted'
    with pytest.raises(ValueError, match='status'):
        cycle.replay_register(events)


def test_mismatch_and_failed_execution_do_not_exclude():
    events = register_events()
    for status, expected in [('success', 'weakened'), ('failed', 'active')]:
        test = {'kind': 'test', 'hypothesis_id': 'h0', 'observation': observation(execution_status=status)}
        assert cycle.replay_register(events+[test])['h0']['status'] == expected


def test_register_requires_residual_and_typed_reopening():
    events = register_events()
    events[0]['hypothesis']['reopening_trigger'] = 'try again later'
    with pytest.raises(ValueError, match='typed'):
        cycle.replay_register(events)
    obs = observation(); del obs['residual']
    with pytest.raises(ValueError, match='residual'):
        cycle.replay_register(register_events()+[{'kind': 'test', 'hypothesis_id': 'h0', 'observation': obs}])


def test_refutation_requires_comparator_sensitivity_and_typed_reopening_receipt(tmp_path):
    comparator = write(tmp_path, 'comparator.json', {'kind': 'prediction-comparison', 'hypothesis_id': 'h0',
        'comparison': 'differs', 'scope': 'declared domain', 'observable': 'response', 'experiment_id': 'e0'})
    sensitivity = write(tmp_path, 'sensitivity.json', {'kind': 'sensitivity-check', 'status': 'passed',
        'experiment_id': 'e0', 'observable': 'response', 'scope': 'declared domain'})
    test = {'kind': 'test', 'hypothesis_id': 'h0', 'observation': observation(
        experiment_id='e0', comparator=comparator, sensitivity=sensitivity)}
    events = register_events()+[test]
    register = cycle.replay_register(events, base_dir=tmp_path)
    assert register['h0']['status'] == 'refuted'
    assert register['h0']['scope_of_negative'] == 'declared domain'
    h = hypothesis(); h['id'] = 'h1'
    with pytest.raises(ValueError, match='what_is_new'):
        cycle.replay_register(events+[{'kind': 'hypothesis', 'hypothesis': h}], base_dir=tmp_path)
    h['what_is_new'] = {'scope': 'new domain'}
    h['identity_signature']['scope'] = 'new domain'
    with pytest.raises(ValueError, match='reopening receipt'):
        cycle.replay_register(events+[{'kind': 'hypothesis', 'hypothesis': h}], base_dir=tmp_path)
    h['reopening_receipt'] = write(tmp_path, 'reopen.json', {'kind': 'new_evidence', 'sensitivity': .9})
    assert cycle.replay_register(events+[{'kind': 'hypothesis', 'hypothesis': h}], base_dir=tmp_path)['h1']['status'] == 'active'


def stop_trace(root):
    result = write(root, 'select-result.json', {'kind': 'research-select-result', 'exposure': 'adaptive_full', 'candidate': 'c0',
        'family': 'f0', 'status': 'success', 'decision': 'better', 'cost': 1})
    return {'stop': {'successes': 1, 'max_rounds': 3, 'budget': 4, 'coverage_floor': 1,
                     'families': ['f0', 'f1'], 'reason': 'successes'},
            'rounds': [{'round': 1, 'candidates': ['c0'], 'successes': 1, 'results': [result]}]}


@pytest.mark.parametrize('mutation', ['reason', 'counter', 'floor'])
def test_stops_are_computed_and_coverage_floor_holds(tmp_path, mutation):
    value = stop_trace(tmp_path)
    if mutation == 'reason': value['stop']['reason'] = 'agent_done'
    if mutation == 'counter': value['rounds'][0]['successes'] = 20
    if mutation == 'floor': value['stop']['coverage_floor'] = 2
    with pytest.raises(ValueError, match='stop|success|coverage'):
        p.computed_stop(value, base_dir=tmp_path)


def test_success_budget_and_round_stops(tmp_path):
    value = stop_trace(tmp_path)
    assert p.computed_stop(value, base_dir=tmp_path)['reason'] == 'successes'
    value['stop'].update(successes=2, max_rounds=1, reason='max_rounds')
    assert p.computed_stop(value, base_dir=tmp_path)['reason'] == 'max_rounds'
    value['stop'].update(max_rounds=3, budget=1, reason='budget')
    assert p.computed_stop(value, base_dir=tmp_path)['reason'] == 'budget'


def ideas_artifact(root):
    from test_research_default_protocol import synthetic_artifacts
    artifact = synthetic_artifacts(root)['ideas']
    for row in artifact['ideas']: row['operator'] = 'limitation_fix'
    artifact['dispatch_receipts'] = {}
    for stream in ('a', 'b'):
        rows = [row for row in artifact['ideas'] if row['stream'] == stream]
        artifact['dispatch_receipts'][stream] = write(root, f'dispatch-{stream}.json', {
            'kind': 'research-idea-dispatch', 'stream': stream,
            'ideas_sha256': p.ce.digest(rows), 'committed_sequence': 1,
            'execution_observation': 'host_attested_external'})
    artifact['tests'] = []
    artifact['operator_yield'] = {'limitation_fix': {'ideas': 2, 'screen': {'tested': 0, 'passed': 0},
                                                  'full': {'tested': 0, 'passed': 0}}}
    return artifact


@pytest.mark.parametrize('mutation', ['operator', 'dispatch', 'exposure', 'yield'])
def test_operator_seed_to_test_guards(tmp_path, mutation):
    artifact = ideas_artifact(tmp_path)
    if mutation == 'operator': del artifact['ideas'][0]['operator']
    if mutation == 'dispatch': artifact['dispatch_receipts'].pop('b')
    if mutation == 'yield': artifact['operator_yield']['limitation_fix']['screen']['passed'] = 1
    if mutation == 'exposure':
        artifact['tests'] = [{'idea': 'Ia', 'stage': 'screen', 'exposure_sequence': 0,
            'result': write(tmp_path, 'test.json', {'idea': 'Ia', 'status': 'success', 'decision': 'better'})}]
    with pytest.raises(ValueError, match='operator|stream|prediction|yield'):
        p.seed_to_test(artifact, base_dir=tmp_path)


def test_operator_yield_from_results(tmp_path):
    artifact = ideas_artifact(tmp_path)
    artifact['tests'] = [{'idea': 'Ia', 'stage': 'screen', 'exposure_sequence': 2,
        'result': write(tmp_path, 'test.json', {'idea': 'Ia', 'status': 'success', 'decision': 'better'})}]
    artifact['operator_yield']['limitation_fix']['screen'] = {'tested': 1, 'passed': 1}
    assert p.seed_to_test(artifact, base_dir=tmp_path) == artifact['operator_yield']


def test_feedback_transform_is_evaluator_only():
    with pytest.raises(ValueError, match='evaluation'):
        p.feedback_arm({'residual': {}}, transform=lambda value: {})
    assert p.feedback_arm({'residual': {}}, transform=lambda value: {}, evaluation_harness=True) == {}


def test_producer_report_missing_checks_and_modules(tmp_path):
    report = p.protocol_producers_present()
    assert report['mode'] == 'report' and not report['valid']
    # The board checks are registered; the evidence queue, RCA and RDJ producers remain pending.
    assert {'P04', 'P06', 'P17'} <= {r['id'] for r in report['missing']}
    assert not {'P01', 'P02'} & {r['id'] for r in report['missing']}
    report = p.protocol_producers_present(bindings=[{'id': 'P03', 'checks': ['check:absent'],
        'producers': ['ravel.workflow.research_protocol']}])
    assert report['missing'][0]['checks'] == ['check:absent']


def test_six_checks_are_registered():
    from ravel.validation import check_research_protocol
    assert set(check_research_protocol.CHECKS) == {'obligation_coverage', 'allocation', 'seed_to_test',
        'excluded_has_signature', 'confirmation_separation', 'protocol_producers_present'}


def allocation_case():
    return {'schema_version': 1, 'scope': 'categorical supplied diagnostic',
        'prediction_basis': 'supplied_unvalidated', 'budget': 5, 'horizon': 1,
        'actions': [{'id': x, 'cost': 1, 'outcomes': ['yes', 'no'], 'nominal_change': 0} for x in ('a', 'b')],
        'hypotheses': [{'id': f'h{i}', 'predictions': {'a': a, 'b': b}, 'provenance': ['supplied'],
                        'reopening_trigger': 'new declared inputs'}
            for i, (a, b) in enumerate([('yes','yes'), ('yes','no'), ('no','yes'), ('yes','yes')])]}


def allocation_policy():
    return {'validation_reservation': 2, 'confirmation_reservation': 2, 'reserve_budget': 1,
            'coverage': {}, 'starvation_rounds': 2, 'rounds_since_exploration': 2}


def test_allocation_requires_recommendation_and_protects_reservations():
    from ravel.workflow import experiment_allocator as a
    case, policy = allocation_case(), allocation_policy()
    with pytest.raises(ValueError, match='allocator_recommendation'):
        a.check_allocation(case, policy, {})
    result = a.allocate(case, policy)
    assert result['reserved'] == {'validation': 2, 'confirmation': 2}
    assert result['exploration_cost'] <= 1
    assert len(result['reserve_seats']) == 1
    assert len({r['class_key'] for r in result['reserve_seats']}) == len(result['reserve_seats'])
    item = {'allocator_recommendation': a.recommend(case)['input_digest'], 'allocation': result}
    assert a.check_allocation(case, policy, item) == result
    assert result['physics_validated'] is False


def test_ec2_requires_prior_and_evaluation_boundary():
    from ravel.workflow import experiment_allocator as a
    with pytest.raises(ValueError, match='prior'):
        a.validate_evaluation_arm({'policy': 'ec2'}, evaluation_harness=True)
    with pytest.raises(ValueError, match='evaluation'):
        a.validate_evaluation_arm({'policy': 'ec2', 'prior': {'h0': 1.}})


@pytest.mark.parametrize('mutation', ['missing_cell', 'missing_bon'])
def test_family_operator_evaluation_is_factorial(tmp_path, mutation):
    config = {'families': ['f0', 'f1'], 'operators': ['fix', 'transfer'],
        'arms': ['operator', 'best_of_n'], 'evaluations_per_arm': 4, 'cells': [
            {'family': f, 'operator': o, 'qualification_receipt': None} for f in ('f0','f1') for o in ('fix','transfer')]}
    if mutation == 'missing_cell': config['cells'].pop()
    if mutation == 'missing_bon': config['arms'].pop()
    with pytest.raises(ValueError, match='factorial|best_of_n'):
        p.family_operator_evaluation(config, base_dir=tmp_path)


def test_unqualified_family_cells_advisory(tmp_path):
    config = {'families': ['f0'], 'operators': ['fix'], 'arms': ['operator', 'best_of_n'], 'evaluations_per_arm': 4,
              'cells': [{'family': 'f0', 'operator': 'fix', 'qualification_receipt': None}]}
    assert p.family_operator_evaluation(config, base_dir=tmp_path)['cells'][0]['status'] == 'advisory'


def test_screen_launch_without_r1_refused(tmp_path, monkeypatch):
    root, protocol = make(tmp_path, monkeypatch)
    assert 'screen_launch_requires_r1' in p.eligibility(cycle._load(root)[1], 'new-screen')


@pytest.mark.parametrize('payload', [None, {}, {'value': ''}])
def test_missing_or_empty_required_output_fails(tmp_path, payload):
    plan = {'required_outputs': [{'id': 'measurement', 'format': 'json', 'pointer': '/value'}]}
    outputs = {} if payload is None else {'measurement': write(tmp_path, 'output.json', payload)}
    with pytest.raises(ValueError, match='obligation'):
        p.obligation_coverage(plan, [], outputs, base_dir=tmp_path)


def test_obligations_include_claim_outputs_and_accept_zero(tmp_path):
    plan = {'required_outputs': [{'id': 'measurement', 'format': 'json', 'pointer': '/value'}]}
    claims = [{'required_outputs': [{'id': 'uncertainty', 'format': 'json', 'pointer': '/value'}]}]
    outputs = {'measurement': write(tmp_path, 'output.json', {'value': 0})}
    with pytest.raises(ValueError, match='uncertainty'):
        p.obligation_coverage(plan, claims, outputs, base_dir=tmp_path)
    outputs['uncertainty'] = write(tmp_path, 'uncertainty.json', {'value': 0})
    assert p.obligation_coverage(plan, claims, outputs, base_dir=tmp_path)['covered'] == ['measurement', 'uncertainty']


def test_precision_target_required_for_anomaly_and_method_sizing():
    with pytest.raises(ValueError, match='precision'):
        p.precision_size({'task_kind': 'anomaly_search', 'events': 100})
    a = p.precision_size({'task_kind': 'method_study', 'precision_target': {
        'kind': 'mean_standard_error', 'sigma_bound': 2., 'absolute_error': .1}})
    b = p.precision_size({'task_kind': 'method_study', 'precision_target': {
        'kind': 'mean_standard_error', 'sigma_bound': 2., 'absolute_error': .05}})
    assert a['samples'] == 400 and b['samples'] == 1600


def test_forged_register_transition_refused():
    with pytest.raises(ValueError, match='transition'):
        cycle.replay_register(register_events()+[{'kind': 'transition', 'hypothesis_id': 'h0',
            'from': 'active', 'to': 'refuted'}])


def test_budget_park_is_scoped_and_requires_receipt(tmp_path):
    obs = observation(execution_status='budget_exhausted', comparison='unknown')
    with pytest.raises(ValueError, match='budget receipt'):
        cycle.replay_register(register_events()+[{'kind': 'test', 'hypothesis_id': 'h0', 'observation': obs}], base_dir=tmp_path)
    obs['budget_receipt'] = write(tmp_path, 'budget.json', {'kind': 'research-budget-boundary', 'spent': 4, 'cap': 4})
    register = cycle.replay_register(register_events()+[{'kind': 'test', 'hypothesis_id': 'h0', 'observation': obs}], base_dir=tmp_path)
    assert register['h0']['status'] == 'untestable_within_budget'
    assert register['h0']['scope_of_negative'] == 'budget_only'


def test_completion_claim_without_receipts_is_counted():
    records = [{'worker': 'w0', 'model_cell': 'm0', 'complete': True, 'required_outputs': ['a','b'],
                'output_receipts': {'a': {'sha256': 'a'*64}}}]
    report = p.completion_disclosure(records)
    assert not report['valid']
    assert report['completion_claimed_without_receipts'] == {'workers': {'w0': 1}, 'model_cells': {'m0': 1}}


def test_performance_claim_cannot_report_selection_peak_as_confirmation(tmp_path):
    claim = {'id': 'c0', 'kind': 'performance', 'verdict': 'exploratory', 'N': 2}
    with pytest.raises(ValueError, match='selection.*report'):
        p.validate_stage_artifact('acceptance', {'claims': [claim]}, base_dir=tmp_path, regime='closed_scored')


def test_allocation_required_on_live_research_eligibility():
    state = {'contract': {'research_protocol_required': True},
        'methodology': {'stages': [{'id': 'limitation_census', 'status': 'done'}, {'id': 'ideas', 'status': 'done'}],
                        'preregistration': {'path': 'bound'}}, 'events': [],
        'hypotheses': [{'id': 'h0'}, {'id': 'h1'}],
        'experiments': [{'id': 'a', 'observation': None, 'cost': {'wall_seconds': 1}, 'predictions': {'h0': 'yes', 'h1': 'no'}},
                        {'id': 'b', 'observation': None, 'cost': {'wall_seconds': 1}, 'predictions': {'h0': 'no', 'h1': 'yes'}}]}
    assert 'allocator_recommendation_required' in p.eligibility(state, 'a')


def test_source_schemas_accept_declarations_and_refuse_status(tmp_path):
    p.validate_followup_schema('selection_request', selection(tmp_path))
    p.validate_followup_schema('hypothesis', hypothesis())
    with pytest.raises(ValueError, match='status'):
        p.validate_followup_schema('hypothesis', {**hypothesis(), 'status': 'refuted'})


def test_production_config_and_cli_schemas_have_no_protocol_toggles():
    import ast
    from pathlib import Path
    package = Path(p.__file__).parents[1]
    for path in (package/'data/research').glob('*.json'):
        p.validate_protocol_controls(json.loads(path.read_text()))
    # Every package CLI, not only the top-level one; a valued option is not a switch.
    switches = {'store_true', 'store_false', 'store_const', 'BooleanOptionalAction'}
    for path in package.rglob('*.py'):
        flags = {}
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                action = next((k.value for k in node.keywords if k.arg == 'action'), None)
                name = (action.value if isinstance(action, ast.Constant) else
                        action.attr if isinstance(action, ast.Attribute) else None)
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith('--'):
                        flags[arg.value] = {'action': 'store_true'} if name in switches else {'type': 'string'}
        p.validate_protocol_controls(flags)


@pytest.mark.parametrize('field,value', [('seeds', [11]), ('generation', 'select-data')])
def test_staged_protocol_refuses_shared_confirmation_generation_or_seeds(tmp_path, monkeypatch, field, value):
    root, protocol = make(tmp_path, monkeypatch, confirmation=True)
    protocol['cells'][-1][field] = value
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p.validate(protocol, base_dir=tmp_path, state=cycle._load(root)[1])


def test_staged_selection_refuses_authored_aggregate_receipts(tmp_path, monkeypatch):
    from test_research_protocol import baseline_screen_full
    root, protocol = baseline_screen_full(tmp_path, monkeypatch, new_full=(1,2), confirmation=True)
    request = {'rule': {'direction': 'minimize', 'metric': 'loss', 'k': 1, 'alpha': .05},
        'regime': 'closed_scored', 'trials': []}
    for i, candidate in enumerate(('original', 'changed')):
        result = write(root, f'trial-{i}.json', {'candidate': candidate, 'value': 2-i,
            'cells': ['full-a','full-b'], 'seeds': [11,12], 'generation': 'select-data', 'status': 'success'})
        request['trials'].append({'id': f't{i}', 'candidate': candidate, 'result': result})
    # Presence of accepted staged evidence cannot authenticate a substituted score.
    with pytest.raises(ValueError, match='observ|evaluation|execution cost'):
        p.commit_selection(root, write(root, 'selection-request.json', request))


def test_confirmation_gate_exposes_exact_codes(tmp_path, monkeypatch):
    import sys
    from dataclasses import make_dataclass
    from types import SimpleNamespace
    error = make_dataclass('GateError', [(key, str) for key in ('code','gate','provider','message','fix')])
    monkeypatch.setitem(sys.modules, 'ravel.workflow.decision_gate', SimpleNamespace(GateError=error))
    p.bind_default(tmp_path)
    state = {'events': []}
    monkeypatch.setattr(cycle, '_load', lambda root: (root, state))
    assert p.gate_errors(tmp_path, 'research_choice', {'purpose': 'confirm', 'candidate': 'c0'})[0].code == 'confirm_read_before_selection'
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    state['events'].append({'kind': 'research_selection', 'receipt': receipt})
    action = {'purpose': 'confirm', 'candidate': 'c0', 'cells': ['select'], 'seeds': [30], 'generation': 'fresh'}
    assert p.gate_errors(tmp_path, 'research_choice', action)[0].code == 'confirm_cell_in_selection_inputs'
    state['events'].append({'kind': 'research_confirm_read', 'read': {'candidate': 'c0'}})
    assert p.gate_errors(tmp_path, 'research_choice', {'purpose': 'confirm', 'candidate': 'c0'})[0].code == 'confirm_reads_exceed_k'


def test_register_is_visible_in_world_digest(tmp_path, monkeypatch):
    from test_research_default_protocol import governed_cycle
    root = governed_cycle(tmp_path)
    rows = [{**hypothesis(), 'stream': 'speculative', 'premise_ids': [], 'source_basis': [], 'parents': []}]
    pin = write(tmp_path, 'hypothesis.json', rows)
    cycle.propose(root, rows, origin={'kind': 'supplied_source', 'pin': pin, 'description': 'Synthetic declared hypothesis.'})
    assert p.world_digest(root)['hypothesis_register']['h0']['status'] == 'active'


def test_next_work_item_rebuilt_from_journal_is_byte_identical(tmp_path, monkeypatch):
    from test_research_protocol import design
    root, protocol = make(tmp_path, monkeypatch)
    design(tmp_path, root, protocol, 'base-screen', [1])
    first = json.dumps(cycle.select(root), sort_keys=True, separators=(',', ':')).encode()
    assert first == json.dumps(cycle.select(root), sort_keys=True, separators=(',', ':')).encode()


def test_registered_obligation_validator_executes_content_check(tmp_path):
    from ravel.validation.check_research_protocol import validate
    value = {'plan': {'required_outputs': [{'id': 'result', 'format': 'json', 'pointer': '/value'}]},
             'claims': [], 'outputs': {}}
    assert not validate('check:obligation_coverage', value, base_dir=tmp_path)['valid']


def test_family_comparison_requires_equal_evaluation_budget(tmp_path):
    config = {'families': ['f0'], 'operators': ['fix'], 'arms': ['operator', 'best_of_n'],
              'cells': [{'family': 'f0', 'operator': 'fix', 'qualification_receipt': None}]}
    with pytest.raises(ValueError, match='equal evaluation'):
        p.family_operator_evaluation(config, base_dir=tmp_path)


def test_selection_report_labels_optimistic_value_and_oracle_is_evaluation_only(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    confirm = write(tmp_path, 'confirmation.json', {'candidate': 'c0', 'value': 0., 'p_value': .5,
        'cells': ['confirm'], 'seeds': [31], 'generation': 'fresh-data', 'status': 'success'})
    report = p.selection_report(receipt, [confirm], base_dir=tmp_path)
    assert report['best_of_N_select'] == {'label': 'optimistic', 'candidate': 'c0', 'value': 3.}
    with pytest.raises(ValueError, match='evaluation'):
        p.selection_oracle_gap(receipt, {'c0': 0., 'c1': 1.})
    assert p.selection_oracle_gap(receipt, {'c0': 0., 'c1': 1.}, evaluation_harness=True) == 1.


@pytest.mark.parametrize('order', ['missing_selection', 'missing_read', 'read_before_selection'])
def test_default_methodology_requires_journaled_selection_before_read(tmp_path, order):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    selected = {'kind': 'research_selection', 'receipt': receipt}
    read = {'kind': 'research_confirm_read', 'read': {'candidate': 'c0', 'cells': ['confirm'],
        'seeds': [31], 'generation': 'fresh-data', 'selection_sha256': receipt['sha256']}}
    events = {'missing_selection': [read], 'missing_read': [selected],
              'read_before_selection': [read, selected]}[order]
    with pytest.raises(ValueError, match='confirm_read_before_selection|confirmation_read_receipt_missing'):
        p.verify_selection_journal({'events': events, 'base_dir': tmp_path}, receipt)


def test_default_methodology_refuses_unobserved_committed_read_sequence(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    read = {'candidate': 'c0', 'cells': ['confirm'], 'seeds': [31], 'generation': 'fresh-data',
            'selection_sha256': receipt['sha256']}
    state = {'events': [{'kind': 'research_selection', 'receipt': receipt},
                        {'kind': 'research_confirm_read', 'read': read}], 'base_dir': tmp_path}
    with pytest.raises(ValueError, match='observ|evaluation|census'):
        p.verify_selection_journal(state, receipt)


def test_screened_candidate_stays_in_N_without_competing_as_full_fidelity(tmp_path):
    request = selection(tmp_path)
    request['trials'].append({'id': 't2', 'candidate': 'screened', 'result': write(tmp_path, 'screened.json', {
        'candidate': 'screened', 'value': 30., 'status': 'success', 'exposure': 'adaptive_screen',
        'cells': ['screen'], 'seeds': [15], 'generation': 'screen-data'})})
    receipt = p.selection_receipt(request, base_dir=tmp_path)
    assert receipt['N'] == 3 and receipt['selected'] == ['c0']


@pytest.mark.parametrize('mode', ['reproduce', 'reinterpret'])
def test_parent_modes_bind_protocol_without_unbound(tmp_path, monkeypatch, mode):
    from test_research_cycle import contract
    from ravel.workflow import task_completion
    # Exercise the ordinary cycle binding seam with a synthetic parent projection.
    monkeypatch.setattr(task_completion, 'binding_projection', lambda *a, **k: {'synthetic': True})
    parent = write(tmp_path, 'parent.json', {'task_mode': mode})
    request = contract(tmp_path)
    request['goal_binding'] = {'contract': parent, 'assignment_id': 'child'}
    root = tmp_path/'run'
    cycle.create(root, request, base_dir=tmp_path, evaluation_harness=True)
    state = cycle._load(root)[1]
    assert state['contract'].get('research_protocol_required') is True
    assert state.get('methodology') and 'protocol_unbound' not in p.eligibility(state, 'unplanned')
    assert p.required_for({'task_kind': mode})


@pytest.mark.parametrize('key', ['kind', 'claim_kind'])
def test_agreement_claim_binds_without_mode(key):
    assert p.required_for({'claims': [{key: 'agreement'}]})


@pytest.mark.parametrize('field,value', [('cells', ['select']), ('seeds', [11]),
                                          ('generation', 'selection-data')])
def test_agreement_claim_refuses_shared_confirmation(tmp_path, field, value):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    row = {'candidate': 'c0', 'value': 4., 'p_value': .001, 'cells': ['confirm'],
           'seeds': [31], 'generation': 'fresh-data', 'status': 'success'}
    row[field] = value
    result = write(tmp_path, 'agreement-confirm.json', row)
    claim = {'id': 'claim', 'kind': 'agreement', 'verdict': 'accepted', 'N': 2,
        'selection_receipt': write(tmp_path, 'selection.json', receipt),
        'selection_report': write(tmp_path, 'claimed-report.json', {
            'selected_result_on_confirm': [{'result': result}]})}
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p.validate_selection_claim(claim, base_dir=tmp_path)


def test_agreement_adoption_requires_selection_before_read(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    claim = {'kind': 'agreement', 'selection_receipt': write(tmp_path, 'selection.json', receipt),
             'selection_report': write(tmp_path, 'unread-report.json', {})}
    with pytest.raises(ValueError, match='confirmation_read_receipt_missing'):
        p._methodology_journal_guard({'events': [{'kind': 'research_selection', 'receipt': receipt}],
            'base_dir': tmp_path}, 'acceptance', {'claims': [claim]}, base_dir=tmp_path, regime='closed_scored')


@pytest.mark.parametrize('purpose', ['baseline', 'ablation', 'objection_test'])
def test_calibration_heldout_refused_for_every_selection_purpose(tmp_path, monkeypatch, purpose):
    root, protocol = make(tmp_path, monkeypatch)
    stage = next(s for s in protocol['stages'] if s['purpose'] == ('baseline' if purpose == 'objection_test' else purpose))
    stage['purpose'] = purpose
    cell = next(c for c in protocol['cells'] if c['id'] == stage['cells'][0]['cell_id'])
    cell['exposure'] = 'withheld_confirmation'
    with pytest.raises(ValueError, match='confirm_cell_in_selection_inputs'):
        p.validate(protocol, base_dir=tmp_path, state=cycle._load(root)[1])


def test_agreement_acceptance_uses_fresh_report_and_committed_read(tmp_path):
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    row = {'candidate': 'c0', 'value': 4., 'p_value': .001, 'cells': ['confirm'],
           'seeds': [31], 'generation': 'fresh-data', 'status': 'success'}
    confirmation = write(tmp_path, 'confirm.json', row)
    report = p.selection_report(receipt, [confirmation], base_dir=tmp_path)
    claim = {'kind': 'agreement', 'id': 'claim', 'N': 2, 'verdict': 'exploratory',
        'selection_receipt': write(tmp_path, 'selected.json', receipt),
        'selection_report': write(tmp_path, 'report.json', report)}
    p.validate_stage_artifact('acceptance', {'claims': [claim]}, base_dir=tmp_path, regime='closed_scored')
    state = {'base_dir': tmp_path, 'events': [{'kind': 'research_selection', 'receipt': receipt},
        {'kind': 'research_confirm_read', 'read': {**row, 'selection_sha256': receipt['sha256']}}]}
    with pytest.raises(ValueError, match='observ|evaluation|census'):
        p._methodology_journal_guard(state, 'acceptance', {'claims': [claim]}, base_dir=tmp_path, regime='closed_scored')


def test_stage_cost_schema_requires_measurement(tmp_path):
    from test_experiment_allocator import diagnosis_case
    action = diagnosis_case(tmp_path)['actions'][0]
    p.validate_followup_schema('allocation_action', action)
    del action['cost_measurement']
    with pytest.raises(ValueError, match='cost_measurement'):
        p.validate_followup_schema('allocation_action', action)


def test_registered_allocation_consumes_relative_cost_pins(tmp_path):
    from test_experiment_allocator import diagnosis_case, diagnosis_policy
    from ravel.workflow import experiment_allocator as a
    from ravel.validation.check_research_protocol import validate
    case = diagnosis_case(tmp_path)
    for action in case['actions']:
        action['cost_measurement']['path'] = action['id']+'-cost.json'
    result = a.allocate(case, diagnosis_policy(), base_dir=tmp_path)
    item = {'allocator_recommendation': result['allocator_recommendation'], 'allocation': result}
    assert validate('check:allocation', {'case': case, 'policy': diagnosis_policy(), 'work_item': item},
                    base_dir=tmp_path) == {'valid': True, 'errors': []}


@pytest.mark.parametrize('hypothesis_count', [1, 3])
def test_live_diagnosis_reservation_refuses_prefreeze_dispatch(tmp_path, hypothesis_count):
    from test_experiment_allocator import diagnosis_case, diagnosis_policy
    from ravel.workflow import experiment_allocator as a
    case = diagnosis_case(tmp_path)
    case['hypotheses'] = case['hypotheses'][:hypothesis_count]
    result = a.allocate(case, diagnosis_policy(), base_dir=tmp_path)
    items = {row['id']: {'allocator_recommendation': result['allocator_recommendation'],
             'allocation': result, 'candidate': 'c0'} for row in case['actions']}
    state = {'contract': {'budget': {'wall_seconds': 12}}, 'base_dir': tmp_path,
        'hypotheses': case['hypotheses'], 'experiments': [
            {'id': row['id'], 'observation': None, 'cost': {'wall_seconds': row['cost']},
             'predictions': {h['id']: h['predictions'][row['id']] for h in case['hypotheses']}}
            for row in case['actions']], 'events': [{'kind': 'research_allocation',
                'case': write(tmp_path, 'case.json', case), 'policy': write(tmp_path, 'policy.json', diagnosis_policy()),
                'work_items': items}]}
    assert p._allocation_errors(state, 'heldout') == ['confirm_read_before_selection']
    expected = [] if result['selection_order'][:1] == ['z-replay'] else ['allocator_action_not_next']
    assert p._allocation_errors(state, 'z-replay') == expected
    receipt = p.selection_receipt(selection(tmp_path), base_dir=tmp_path)
    state['events'].append({'kind': 'research_selection', 'receipt': receipt})
    assert p._allocation_errors(state, 'heldout') == []
    state['events'].append({'kind': 'research_confirm_read', 'read': {'candidate': 'c0'}})
    assert p._allocation_errors(state, 'heldout') == ['confirm_reads_exceed_k']
