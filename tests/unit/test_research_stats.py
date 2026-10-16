"""Synthetic search, paired arithmetic and predictive allocation controls."""
import math

import pytest

from ravel.physics import research_comparison as comparison
from ravel.workflow import experiment_allocator as allocator
from test_research_default_protocol import write


def comparison_task(root, left=(2., 4.), right=(3., 3.), *, intervals=False):
    fixed = write(root, 'rule.json', {'schema_version': 1, 'metric': 'loss', 'unit': '1',
        'direction': 'minimize', 'min_gain': .1, 'tolerance': .01,
        'uncertainty': 'supplied_intervals' if intervals else 'deterministic', 'reduction': 'all_cells'})
    sources = [write(root, side + '.json', {'values': list(values), 'quality': True,
        'intervals': [[v-1, v+1] for v in values]}) for side, values in [('left', left), ('right', right)]]
    cells = [{'id': 'cell-' + str(i), 'metric': 'loss', 'unit': '1', 'exposure': 'adaptive_full',
        **{side: {'source': source, 'value_pointer': '/values/' + str(i),
                 'interval_pointer': '/intervals/' + str(i), 'quality_pointer': '/quality'}
           for side, source in zip(('left', 'right'), sources)}} for i in range(len(left))]
    request = {'schema_version': 1, 'protocol_sha256': 'a'*64, 'comparison_id': 'contrast',
               'rule': fixed, 'cells': cells, 'dependencies': []}
    return request


def calculate(root, request):
    return comparison.calculate({'schema_version': 1, 'request': write(root, 'request.json', request)}, root)


@pytest.mark.parametrize('left,right,intervals,decision,frontier', [
    ((2, 4), (3, 3), False, 'unknown', ['left', 'right']),
    ((2, 2), (3, 3), False, 'better', ['left']),
    ((4, 4), (3, 3), False, 'worse', ['right']),
    ((2, 2), (3, 3), True, 'unknown', ['left', 'right']),
    ((2, 3), (3, 3), False, 'better', ['left']),
    ((2.95, 2.95), (3, 3), False, 'unknown', ['left']),
])
def test_frontier_is_separate_from_uniform_claim(tmp_path, left, right, intervals, decision, frontier):
    result = calculate(tmp_path, comparison_task(tmp_path, left, right, intervals=intervals))
    assert result['decision'] == decision
    retained = comparison.search_retention([r['gain_interval'] for r in result['cells']],
                                           [result['rule']['tolerance']] * len(result['cells']))
    assert retained['frontier'] == frontier
    assert retained['claim_authorized'] is False


def paired_request(root, *, covariance=True):
    request = comparison_task(root, (2.,), (3.,), intervals=True)
    # A joint event-group Gram, retaining the actual cross product.
    groups = [[1., 0.], [.8, .6]]
    matrix = [[math.fsum(x*y for x, y in zip(a, b)) for b in groups] for a in groups]
    joint = write(root, 'joint.json', {'values': [2., 3.], 'output_covariance': matrix if covariance else None})
    cell = request['cells'][0]
    record = {'construction': 'same_events', 'population': write(root, 'events.json', {'ids': ['g0', 'g1']}),
        **{side: {key: cell[side][key] for key in ('source', 'value_pointer')} for side in ('left', 'right')},
        'covariance_source': joint, 'covariance_pointer': '/output_covariance', 'values_pointer': '/values',
        'indices': [0, 1], 'interval_multiplier': 1., 'interval_prescription': 'symmetric_covariance'}
    cell['paired_evaluation'] = {'source': write(root, 'evaluation.json', {'paired': record}), 'pointer': '/paired'}
    return request, record


def test_actual_paired_positive_covariance_narrows_difference(tmp_path):
    request, _ = paired_request(tmp_path)
    result = calculate(tmp_path, request)
    row = result['cells'][0]
    assert row['gain_interval'] == pytest.approx([1-math.sqrt(.4), 1+math.sqrt(.4)])
    assert row['interval_construction'] == 'paired_covariance'
    # Covariance coordinates need not be emitted in comparison order.
    fixed = comparison.document(request['rule'], tmp_path); fixed['direction'] = 'maximize'
    request['rule'] = write(tmp_path, 'maximize.json', fixed)
    assert calculate(tmp_path, request)['cells'][0]['gain_interval'] == pytest.approx([-1-math.sqrt(.4), -1+math.sqrt(.4)])


@pytest.mark.parametrize('missing_kind', ['null_matrix', 'missing_matrix', 'no_covariance_record'])
def test_absent_covariance_or_unrecorded_pairing_uses_exact_marginal_construction(tmp_path, missing_kind):
    request, record = paired_request(tmp_path, covariance=False)
    if missing_kind == 'missing_matrix':
        record['covariance_source'] = write(tmp_path, 'joint.json', {'values': [2., 3.]})
    if missing_kind == 'no_covariance_record':
        for key in ('covariance_source', 'covariance_pointer', 'values_pointer', 'indices',
                    'interval_multiplier', 'interval_prescription'): record.pop(key)
    request['cells'][0]['paired_evaluation']['source'] = write(tmp_path, 'evaluation.json', {'paired': record})
    missing = calculate(tmp_path, request)['cells'][0]
    assert missing['gain_interval'] == [-1., 3.]
    request['cells'][0].pop('paired_evaluation')
    unrecorded = calculate(tmp_path, request)['cells'][0]
    assert missing == unrecorded


@pytest.mark.parametrize('mutation', ['construction', 'operand', 'matrix', 'population'])
def test_invalid_pairing_never_grants_precision(tmp_path, mutation):
    request, record = paired_request(tmp_path)
    if mutation == 'construction': record['construction'] = 'unrecorded'
    if mutation == 'operand': record['left']['value_pointer'] = '/values/1'
    if mutation == 'matrix':
        record['covariance_source'] = write(tmp_path, 'invalid.json', {'values': [2., 3.], 'output_covariance': [[1, 2], [2, 1]]})
    if mutation == 'population':
        from pathlib import Path
        Path(record['population']['path']).write_text('{}')
    request['cells'][0]['paired_evaluation']['source'] = write(tmp_path, 'evaluation.json', {'paired': record})
    with pytest.raises(ValueError): calculate(tmp_path, request)


def allocation_case():
    return {'schema_version': 1, 'scope': 'Synthetic finite predictive controls',
        'prediction_basis': 'supplied_unvalidated', 'budget': 4, 'horizon': 1,
        'actions': [{'id': 'informative', 'cost': 2, 'outcomes': ['yes', 'no'], 'nominal_change': 0},
                    {'id': 'constant', 'cost': 1, 'outcomes': ['same'], 'nominal_change': 0}],
        'hypotheses': [{'id': 'h0', 'predictions': {'informative': 'yes', 'constant': None},
                        'provenance': ['synthetic'], 'reopening_trigger': 'new evidence'},
                       {'id': 'h1', 'predictions': {'informative': None, 'constant': None},
                        'provenance': ['synthetic'], 'reopening_trigger': 'new evidence'}]}


def model_case(root):
    case = allocation_case()
    groups = {g['members'][0]['id']: g['class_key'] for g in allocator.canonicalize(case)}
    model = {'schema_version': 1, 'kind': 'calibrated_record', 'scope': case['scope'],
        'method': 'Synthetic exact joint frequencies',
        'sources': [write(root, 'counts.json', {'counts': [2, 1, 1], 'synthetic': True})],
        'distribution': [{'class_key': groups[h], 'probability': p,
                          'outcomes': {'informative': outcome, 'constant': 'same'}}
                         for h, outcome, p in [('h0', 'yes', .5), ('h1', 'yes', .25), ('h1', 'no', .25)]]}
    case.update(allocation_policy='expected_information', predictive_model=write(root, 'model.json', model))
    return case, model


def test_expected_information_requires_declared_predictive_evidence():
    case = allocation_case(); case['allocation_policy'] = 'expected_information'
    with pytest.raises(ValueError, match='declared source-backed predictive model'): allocator.recommend(case)


@pytest.mark.parametrize('horizon', [1, 2])
def test_predictive_information_selects_uncertain_action_while_default_abstains(tmp_path, horizon):
    case, _ = model_case(tmp_path); case['horizon'] = horizon
    result = allocator.recommend(case, base_dir=tmp_path)
    assert result['allocation_policy'] == 'expected_information'
    assert result['policy']['first_action'] == 'informative'
    assert set(result['policy']['then'].values()) == {None}
    assert result['policy']['expected_information_bits'] == pytest.approx(.31127812445913283)
    assert result['policy']['information_per_cost'] == pytest.approx(.31127812445913283/2)
    assert result['predictive_basis']['kind'] == 'calibrated_record'
    assert result['selection_reason'] and result['execution_authorized'] is False
    case.pop('allocation_policy')
    guaranteed = allocator.recommend(case, base_dir=tmp_path)
    assert guaranteed['allocation_policy'] == 'guaranteed'
    assert guaranteed['policy'] is None
    assert guaranteed['predictive_basis'] is None


@pytest.mark.parametrize('mutation', ['confidence', 'sources', 'normalization', 'class', 'outcome', 'contradiction', 'changed_source'])
def test_predictive_admission_refuses_unsupported_laws(tmp_path, mutation):
    case, model = model_case(tmp_path)
    if mutation == 'confidence': model['kind'] = 'agent_confidence'
    if mutation == 'sources': model['sources'] = []
    if mutation == 'normalization': model['distribution'][0]['probability'] = .9
    if mutation == 'class': model['distribution'][0]['class_key'] = 'unknown'
    if mutation == 'outcome': model['distribution'][0]['outcomes'].pop('constant')
    if mutation == 'contradiction': model['distribution'][0]['outcomes']['informative'] = 'no'
    if mutation == 'changed_source':
        from pathlib import Path
        Path(model['sources'][0]['path']).write_text('{}')
    case['predictive_model'] = write(tmp_path, 'model.json', model)
    with pytest.raises(ValueError): allocator.recommend(case, base_dir=tmp_path)


def test_expected_policy_reservations_and_selection_order(tmp_path):
    case, _ = model_case(tmp_path)
    result = allocator.allocate(case, {'validation_reservation': 1, 'confirmation_reservation': 0,
        'reserve_budget': 0, 'coverage': {}, 'starvation_rounds': 2, 'rounds_since_exploration': 0}, base_dir=tmp_path)
    assert result['allocation_policy'] == 'expected_information'
    assert result['policy']['first_action'] == 'informative'
    assert result['selection_order'] == ['informative']
    assert result['remaining_selection_budget'] == 3


def test_information_cli_selects_recorded_policy(tmp_path):
    import json
    import subprocess
    import sys
    case, _ = model_case(tmp_path); case.pop('allocation_policy')
    pin = write(tmp_path, 'case.json', case)
    response = subprocess.run([sys.executable, '-m', 'ravel.workflow.experiment_allocator',
        '--case', pin['path'], '--policy', 'expected_information'], capture_output=True, text=True, check=True)
    result = json.loads(response.stdout)
    assert result['allocation_policy'] == 'expected_information'
    assert result['policy']['first_action'] == 'informative'


def test_joint_law_preserves_information_only_available_in_two_outcomes(tmp_path):
    case = allocation_case(); case.update(horizon=2, budget=2)
    case['actions'] = [{'id': key, 'cost': cost, 'outcomes': ['yes', 'no'], 'nominal_change': 0}
                       for key, cost in [('a', 1), ('b', 1), ('marker', 9)]]
    for i, h in enumerate(case['hypotheses']):
        h['predictions'] = {'a': None, 'b': None, 'marker': 'yes' if i == 0 else None}
    groups = {g['members'][0]['id']: g['class_key'] for g in allocator.canonicalize(case)}
    model = {'schema_version': 1, 'kind': 'source_backed_predictive_model', 'scope': case['scope'],
        'method': 'Synthetic exact joint law', 'sources': [write(tmp_path, 'law.json', {'equal': 'h0', 'unequal': 'h1'})],
        'distribution': [{'class_key': groups['h0' if a == b else 'h1'], 'probability': .25,
                          'outcomes': {'a': a, 'b': b, 'marker': 'yes'}}
                         for a in ('yes', 'no') for b in ('yes', 'no')]}
    case.update(allocation_policy='expected_information', predictive_model=write(tmp_path, 'joint-model.json', model))
    result = allocator.recommend(case, base_dir=tmp_path)
    assert result['policy']['first_action'] == 'a'
    assert set(result['policy']['then'].values()) == {'b'}
    assert result['policy']['expected_information_bits'] == pytest.approx(1.)
    assert result['policy']['expected_cost'] == pytest.approx(2.)
    assert allocator.recommend(case, horizon=1, base_dir=tmp_path)['policy'] is None
    queued = allocator.allocate(case, {'validation_reservation': 0, 'confirmation_reservation': 0,
        'reserve_budget': 0, 'coverage': {}, 'starvation_rounds': 2, 'rounds_since_exploration': 0}, base_dir=tmp_path)
    assert queued['selection_order'] == ['a']
    assert queued['policy']['first_action'] == 'a'


def test_staged_search_frontier_keeps_tradeoff_and_cannot_complete_claim(tmp_path, monkeypatch):
    import test_research_protocol as staged
    from ravel.workflow import research_protocol
    staged.no_process.__wrapped__(monkeypatch)
    root, p = staged.make(tmp_path, monkeypatch)
    for identity, values in [('base-screen', [5]), ('base-full', [2, 3]),
                             ('new-screen', [1]), ('new-full', [1, 4])]:
        staged.design(tmp_path, root, p, identity, values)
    for identity in ('base-screen', 'base-full', 'new-screen'):
        staged.accepted_fixture(root, identity)
    staged.complete_comparator(tmp_path, root, 'screen-contrast')
    staged.accepted_fixture(root, 'new-full')
    staged.complete_comparator(tmp_path, root, 'full-contrast')
    result = research_protocol.status(root)
    assert result['comparisons']['full-contrast']['decision'] == 'unknown'
    assert result['incumbent_options']['search_frontier_candidate_ids'] == ['changed', 'original']
    assert result['incumbent_options']['frontier_authorizes_claim'] is False
    assert result['complete_scientific_evidence'] is False


def test_missing_objective_keeps_both():
    assert comparison.search_retention([[1, 2], None])['frontier'] == ['left', 'right']


def test_staged_missing_objectives_retain_search_candidates_without_selection_authority(tmp_path, monkeypatch):
    import test_research_protocol as staged
    from ravel.workflow import research_protocol
    staged.no_process.__wrapped__(monkeypatch)
    root, _ = staged.make(tmp_path, monkeypatch)
    result = research_protocol.status(root)['incumbent_options']
    assert result['search_frontier_candidate_ids'] == ['changed', 'original']
    assert result['search_pending_candidate_ids'] == ['changed', 'original']
    assert result['valid_full_candidate_ids'] == result['undominated_candidate_ids'] == []


def test_staged_preparation_consumes_embedded_joint_evaluation(tmp_path, monkeypatch):
    from ravel.workflow import research_protocol as protocol
    request = comparison_task(tmp_path, (2.,), (3.,), intervals=True)
    cell = request['cells'][0]
    population = write(tmp_path, 'population.json', {'ids': ['g0', 'g1']})
    record = {'construction': 'same_events', 'population': population,
        'left': {'source': 'self', 'value_pointer': '/values/0'},
        'right': {'source': 'self', 'value_pointer': '/values/1'},
        'covariance_source': 'self', 'covariance_pointer': '/output_covariance',
        'values_pointer': '/values', 'indices': [0, 1], 'interval_multiplier': 1.,
        'interval_prescription': 'symmetric_covariance'}
    joint = write(tmp_path, 'joint.json', {'values': [2., 3.], 'intervals': [[1., 3.], [2., 4.]],
        'quality': True, 'output_covariance': [[1., .8], [.8, 1.]],
        'paired_evaluations': {cell['id']: record}})
    stages = [{'id': side, 'candidate': side, 'cells': [{'cell_id': cell['id'],
        'value_pointer': '/values/'+str(i), 'interval_pointer': '/intervals/'+str(i),
        'quality_pointer': '/quality'}]} for i, side in enumerate(('left', 'right'))]
    comp = {'id': 'paired-contrast', 'left_stage': 'left', 'right_stage': 'right', 'rule': request['rule']}
    p = {'stages': stages, 'cells': [{**{k: cell[k] for k in ('id', 'metric', 'unit', 'exposure')},
         'population': population, 'normalization': write(tmp_path, 'normalization.json', {'scale': 1})}],
         'candidates': [{'id': side, 'components': {}, 'invariant_inputs': []} for side in ('left', 'right')]}
    monkeypatch.setattr(protocol, '_stage_rows', lambda *args: [{'cell_id': cell['id'], 'status': 'accepted_current', 'result': joint}])
    generated = protocol._comparison_request({'base_dir': str(tmp_path)}, p, {}, comp)
    assert generated['cells'][0]['paired_evaluation'] == {'source': joint, 'pointer': '/paired_evaluations/cell-0'}
    assert calculate(tmp_path, generated)['cells'][0]['gain_interval'] == pytest.approx([1-math.sqrt(.4), 1+math.sqrt(.4)])


def test_search_frontier_spans_declared_objectives_with_different_claim_rules():
    from ravel.workflow import research_protocol as protocol
    p = {'stages': [], 'comparisons': []}
    measured = {}
    for i in range(2):
        for side in ('left', 'right'):
            p['stages'].append({'id': side+str(i), 'purpose': 'full', 'candidate': side,
                                'cells': [{'cell_id': str(i)}]})
        p['comparisons'].append({'id': str(i), 'left_stage': 'left'+str(i), 'right_stage': 'right'+str(i),
                                'rule': {'objective': str(i)}, 'acceptance_scope': 'supplied'})
        measured[str(i)] = {'status': 'accepted_current', 'decision': 'unknown', 'objective_gains': [[.01, .02]], 'objective_tolerance': .005,
                            'objective': {'metric': 'objective-'+str(i), 'unit': '1', 'direction': 'minimize'}}
    _, claims, search = protocol._full_preferences(p, measured, {'left', 'right'})
    assert claims == []
    assert search == [{'preferred_candidate': 'left', 'other_candidate': 'right',
                       'comparison_ids': ['0', '1'], 'claim_authorized': False}]


def test_unpaired_comparison_result_keeps_its_recorded_schema(tmp_path):
    # Staged status recomputes and compares recorded results exactly.
    result = calculate(tmp_path, comparison_task(tmp_path))
    assert 'search_retention' not in result
    assert set(result['cells'][0]) == {'cell_id', 'exposure', 'operands', 'gain_interval',
                                       'decision', 'unresolved_reasons'}


def test_gain_within_declared_tolerance_cannot_drop_a_candidate():
    assert comparison.search_retention([[.005, .005]], [.01])['frontier'] == ['left', 'right']
    assert comparison.search_retention([[-.005, -.005]], [.01])['frontier'] == ['left', 'right']
    assert comparison.search_retention([[.05, .05]], [.01])['frontier'] == ['left']


def test_staged_preparation_ignores_pairing_in_non_object_result(tmp_path, monkeypatch):
    from ravel.workflow import research_protocol as protocol
    request = comparison_task(tmp_path, (2.,), (3.,), intervals=True)
    cell = request['cells'][0]
    result = write(tmp_path, 'list.json', [2., 3.])
    stages = [{'id': side, 'candidate': side, 'cells': [{'cell_id': cell['id'],
        'value_pointer': '/'+str(i), 'interval_pointer': None, 'quality_pointer': '/0'}]}
        for i, side in enumerate(('left', 'right'))]
    comp = {'id': 'list-contrast', 'left_stage': 'left', 'right_stage': 'right', 'rule': request['rule']}
    p = {'stages': stages, 'cells': [{**{k: cell[k] for k in ('id', 'metric', 'unit', 'exposure')},
         'population': write(tmp_path, 'population.json', {'ids': []}),
         'normalization': write(tmp_path, 'normalization.json', {'scale': 1})}],
         'candidates': [{'id': side, 'components': {}, 'invariant_inputs': []} for side in ('left', 'right')]}
    monkeypatch.setattr(protocol, '_stage_rows', lambda *args: [{'cell_id': cell['id'], 'status': 'accepted_current', 'result': result}])
    generated = protocol._comparison_request({'base_dir': str(tmp_path)}, p, {}, comp)
    assert 'paired_evaluation' not in generated['cells'][0]
