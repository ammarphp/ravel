"""Synthetic scope and tradeoff controls; no scientific or provider execution."""
from copy import deepcopy

import pytest

from ravel.workflow import experiment_allocator as allocator
from ravel.workflow import research_protocol as protocol


def objective(kind='regional_improvement', ids=('a',), requirements=None):
    return {'id': 'target', 'kind': kind, 'scope': 'Only the supplied named cells',
            'cell_ids': list(ids), 'requirements': requirements or [requirement(ids=ids)]}


def requirement(comp='contrast', ids=('a',), candidate='changed', axis='performance', allowed=('better', 'equivalent')):
    return {'comparison_id': comp, 'cell_ids': list(ids), 'preferred_candidate': candidate,
            'axis': axis, 'allowed_decisions': list(allowed)}


def supplied(kind='regional_improvement', ids=('a',)):
    p = {'cells': [{'id': i, 'metric': 'loss', 'unit': '1', 'exposure': 'adaptive_full'} for i in ('a', 'b')],
         'stages': [{'id': side, 'purpose': 'full', 'candidate': candidate,
                     'cells': [{'cell_id': i} for i in ('a', 'b')]}
                    for side, candidate in [('left', 'changed'), ('right', 'original')]],
         'comparisons': [{'id': 'contrast', 'left_stage': 'left', 'right_stage': 'right'}],
         'objectives': [objective(kind, ids)]}
    measured = {'contrast': {'status': 'accepted_current', 'decision': 'unknown',
        'objective': {'metric': 'loss', 'unit': '1', 'direction': 'minimize'},
        'objective_rule': {'min_gain': .1, 'tolerance': .01},
        'cell_decisions': [{'cell_id': 'a', 'decision': 'better', 'gain_interval': [1., 1.]},
                           {'cell_id': 'b', 'decision': 'worse', 'gain_interval': [-1., -1.]}]}}
    return p, measured


def test_regional_conclusion_does_not_extrapolate_or_change_global_decision():
    p, measured = supplied()
    row = protocol.objective_conclusions(p, measured)[0]
    assert row['status'] == 'supported_in_declared_scope'
    assert row['kind'] == 'regional_improvement' and row['cell_ids'] == ['a']
    assert [e['cell_id'] for e in row['evidence']] == ['a']
    assert row['claim_authorized'] is row['extrapolation_authorized'] is False
    assert measured['contrast']['decision'] == 'unknown'


@pytest.mark.parametrize('kind', ['regional_improvement', 'uniform_improvement', 'complementary_portfolio'])
def test_improvement_cannot_allow_regression(kind):
    p, measured = supplied(kind)
    p['objectives'][0]['requirements'][0]['allowed_decisions'].append('worse')
    with pytest.raises(ValueError, match='nonworsening'):
        protocol.objective_conclusions(p, measured)


def test_uniform_rejects_a_region_with_an_uncovered_full_cell():
    p, measured = supplied('uniform_improvement')
    with pytest.raises(ValueError, match='every full stage cell'):
        protocol.objective_conclusions(p, measured)


def test_uniform_keeps_every_cell_and_rejects_tradeoff():
    p, measured = supplied('uniform_improvement', ('a', 'b'))
    row = protocol.objective_conclusions(p, measured)[0]
    assert row['status'] == 'requirements_not_met'
    assert row['tradeoff_observed'] is True
    measured['contrast']['cell_decisions'][1] = {'cell_id': 'b', 'decision': 'equivalent', 'gain_interval': [0, 0]}
    assert protocol.objective_conclusions(p, measured)[0]['status'] == 'supported_in_declared_scope'
    measured['contrast']['cell_decisions'].pop()
    row = protocol.objective_conclusions(p, measured)[0]
    assert row['status'] == 'unresolved' and row['cell_ids'] == ['a', 'b']


@pytest.mark.parametrize('mutation', ['scope', 'unknown_cell', 'duplicate', 'screen', 'withheld', 'candidate', 'pending'])
def test_scope_and_missing_evidence_refusals(mutation):
    p, measured = supplied()
    if mutation == 'pending':
        measured['contrast']['status'] = 'pending'
        assert protocol.objective_conclusions(p, measured)[0]['status'] == 'unresolved'
        return
    if mutation == 'scope': p['objectives'][0]['cell_ids'].append('b')
    if mutation == 'unknown_cell': p['objectives'][0]['requirements'][0]['cell_ids'] = ['missing']
    if mutation == 'duplicate': p['objectives'][0]['requirements'] *= 2
    if mutation in {'screen', 'withheld'}:
        p['cells'][0]['exposure'] = 'adaptive_screen' if mutation == 'screen' else 'withheld_confirmation'
    if mutation == 'candidate': p['objectives'][0]['requirements'][0]['preferred_candidate'] = 'missing'
    with pytest.raises(ValueError): protocol.objective_conclusions(p, measured)


def test_portfolio_retains_complementary_members_and_missing_regions():
    p, measured = supplied()
    p['objectives'] = [objective('complementary_portfolio', ('a', 'b'),
        [requirement(ids=('a',)), requirement(ids=('b',), candidate='original')])]
    rows = protocol.objective_conclusions(p, measured)
    assert rows[0]['status'] == 'supported_in_declared_scope'
    advice = allocator.objective_advice(rows)
    assert advice['retained_candidate_ids'] == ['changed', 'original']
    assert advice['scalarization'] is None and advice['combination_authorized'] is False
    measured['contrast']['cell_decisions'].pop()
    rows = protocol.objective_conclusions(p, measured)
    assert rows[0]['status'] == 'unresolved'
    assert len(rows[0]['evidence']) == 2
    advice = allocator.objective_advice(rows)
    assert advice['retained_candidate_ids'] == ['changed', 'original']
    assert advice['unresolved_objective_ids'] == ['target']


def test_reversed_candidate_must_clear_minimum_gain():
    p, measured = supplied()
    p['objectives'][0]['requirements'][0]['preferred_candidate'] = 'original'
    measured['contrast']['cell_decisions'][0] = {'cell_id': 'a', 'decision': 'worse', 'gain_interval': [-.05, -.05]}
    assert protocol.objective_conclusions(p, measured)[0]['status'] == 'unresolved'


@pytest.mark.parametrize('gain', [-1., -.05, .05, 1.])
@pytest.mark.parametrize('reverse_operands', [False, True])
def test_candidate_claim_preference_recomputes_both_minimum_gains(gain, reverse_operands):
    p, measured = supplied('uniform_improvement', ('a', 'b'))
    comp = p['comparisons'][0]
    comp.update(rule={'path': 'supplied-rule'}, acceptance_scope='supplied')
    if reverse_operands:
        comp['left_stage'], comp['right_stage'] = comp['right_stage'], comp['left_stage']
    current = measured['contrast']
    current.update(decision='better' if gain > .11 else 'worse' if gain < -.01 else 'unknown',
                   objective_gains=[[gain, gain]] * 2, objective_tolerance=.01)
    _, claims, search = protocol._full_preferences(p, measured, {'changed', 'original'},
        retained_rules={'contrast': current['objective_rule']})
    left = 'original' if reverse_operands else 'changed'
    preferred = left if gain > 0 else ({'changed', 'original'} - {left}).pop()
    assert search[0]['preferred_candidate'] == preferred
    if abs(gain) > .11:
        assert claims[0]['preferred_candidate'] == preferred
    else:
        assert claims == []


def test_portfolio_requires_a_strict_gain_from_each_member():
    p, measured = supplied()
    p['objectives'] = [objective('complementary_portfolio', ('a', 'b'),
        [requirement(ids=('a',)), requirement(ids=('b',), candidate='original')])]
    measured['contrast']['cell_decisions'][1] = {'cell_id': 'b', 'decision': 'equivalent', 'gain_interval': [0, 0]}
    row = protocol.objective_conclusions(p, measured)[0]
    assert row['status'] == 'requirements_not_met'
    assert row['candidate_ids'] == ['changed', 'original']
    assert allocator.objective_advice([row])['retained_candidate_ids'] == ['changed', 'original']


def test_cost_accuracy_retains_unequal_cost_without_scalarization():
    p, measured = supplied()
    p['cells'][1].update(metric='duration', unit='seconds')
    for side in ('left', 'right'):
        p['stages'].append({**deepcopy(next(s for s in p['stages'] if s['id'] == side)),
                            'id': side+'-cost', 'cells': [{'cell_id': 'b'}]})
        next(s for s in p['stages'] if s['id'] == side)['cells'] = [{'cell_id': 'a'}]
    p['comparisons'].append({'id': 'cost', 'left_stage': 'left-cost', 'right_stage': 'right-cost'})
    measured['cost'] = {**deepcopy(measured['contrast']),
        'objective': {'metric': 'duration', 'unit': 'seconds', 'direction': 'minimize'},
        'cell_decisions': [{'cell_id': 'b', 'decision': 'worse', 'gain_interval': [-100, -100]}]}
    p['objectives'] = [objective('cost_accuracy', ('a', 'b'), [requirement(axis='accuracy'),
        requirement('cost', ('b',), axis='cost', allowed=('worse',))])]
    row = protocol.objective_conclusions(p, measured)[0]
    assert row['status'] == 'supported_in_declared_scope' and row['tradeoff_observed']
    assert [r['gain_interval'] for r in row['evidence']] == [[1., 1.], [-100, -100]]
    assert allocator.objective_advice([row])['scalarization'] is None
    p['objectives'][0]['requirements'][1]['allowed_decisions'] = ['better', 'equivalent']
    assert protocol.objective_conclusions(p, measured)[0]['status'] == 'requirements_not_met'


def test_cost_accuracy_cannot_rename_one_metric_into_two_axes():
    p, measured = supplied()
    p['objectives'] = [objective('cost_accuracy', ('a', 'b'), [requirement(axis='accuracy'),
        requirement(ids=('b',), axis='cost', allowed=('worse',))])]
    with pytest.raises(ValueError, match='distinct supplied metrics'):
        protocol.objective_conclusions(p, measured)


def test_default_protocol_has_no_objective_conclusions():
    p, measured = supplied(); p.pop('objectives')
    assert protocol.objective_conclusions(p, measured) == []


@pytest.mark.parametrize('value', [None, [], 'invalid', 1])
def test_invalid_protocol_type_is_a_typed_refusal(value, tmp_path):
    with pytest.raises(ValueError, match='protocol object'):
        protocol.validate(value, base_dir=tmp_path, state={})


@pytest.mark.parametrize('value', [None, [], 'invalid', {}])
def test_invalid_identified_rows_are_typed_refusals(value):
    with pytest.raises(ValueError, match='identified object'):
        protocol._ids([value], 1, 'synthetic census')


def install_objectives(base, root, p, *, portfolio=False):
    from test_research_cycle import write
    p['objectives'] = [objective(ids=('full-a',), requirements=[requirement('full-contrast', ('full-a',))])]
    if portfolio:
        p['objectives'][0] = objective('complementary_portfolio', ('full-a', 'full-b'), [
            requirement('full-contrast', ('full-a',)),
            requirement('full-contrast', ('full-b',), candidate='original')])
    scoped_claim = deepcopy(p['claims'][0])
    scoped_claim.update(id='scoped-claim', stage_ids=['incumbent-full', 'new-full'],
        comparison_ids=['full-contrast'], objective_ids=['target'], report_slot='scoped-output')
    p['claims'].append(scoped_claim)
    protocol.bind(root, write(base/'scoped-protocol.json', p))


def test_current_ordinary_evidence_supports_only_bound_regional_claim(tmp_path, monkeypatch):
    import test_research_protocol as staged
    staged.no_process.__wrapped__(monkeypatch)
    root, p = staged.make(tmp_path, monkeypatch)
    install_objectives(tmp_path, root, p)
    for identity, values in [('base-screen', [5]), ('base-full', [2, 3]),
                             ('new-screen', [1]), ('new-full', [1, 4])]:
        staged.design(tmp_path, root, p, identity, values)
    for identity in ('base-screen', 'base-full', 'new-screen'):
        staged.accepted_fixture(root, identity)
    staged.complete_comparator(tmp_path, root, 'screen-contrast')
    staged.accepted_fixture(root, 'new-full')
    staged.complete_comparator(tmp_path, root, 'full-contrast')
    result = protocol.status(root)
    assert result['comparisons']['full-contrast']['decision'] == 'unknown'
    claim = next(c for c in result['claims'] if c['id'] == 'scoped-claim')
    assert claim['current_evidence_complete'] is True
    assert claim['conclusion_scopes'][0]['cell_ids'] == ['full-a']
    assert result['complete_scientific_evidence'] is False
    assert result['incumbent_options']['search_frontier_candidate_ids'] == ['changed', 'original']
    assert result['objective_advice']['claim_authorized'] is False


def test_objective_cannot_be_introduced_after_observation(tmp_path, monkeypatch):
    import test_research_protocol as staged
    staged.no_process.__wrapped__(monkeypatch)
    root, p = staged.make(tmp_path, monkeypatch)
    staged.design(tmp_path, root, p, 'base-full', [2, 3])
    staged.accepted_fixture(root, 'base-full')
    with pytest.raises(ValueError, match='precede affected execution evidence'):
        install_objectives(tmp_path, root, p)


def test_bound_scope_cannot_change_on_revision(tmp_path, monkeypatch):
    import test_research_protocol as staged
    from test_research_cycle import write
    staged.no_process.__wrapped__(monkeypatch)
    root, p = staged.make(tmp_path, monkeypatch)
    install_objectives(tmp_path, root, p)
    p['objectives'][0]['scope'] = 'A larger claimed scope'
    with pytest.raises(ValueError, match='objective scopes'):
        protocol.bind(root, write(tmp_path/'changed-scope.json', p))


@pytest.mark.parametrize('mutation', ['extra_comparison', 'missing_operand', 'unknown_objective'])
def test_scoped_claim_cannot_borrow_or_omit_obligations(tmp_path, monkeypatch, mutation):
    import test_research_protocol as staged
    from ravel.workflow import research_cycle as cycle
    staged.no_process.__wrapped__(monkeypatch)
    root, p = staged.make(tmp_path, monkeypatch)
    install_objectives(tmp_path, root, p)
    claim = p['claims'][-1]
    if mutation == 'extra_comparison': claim['comparison_ids'].append('ablation-contrast')
    if mutation == 'missing_operand': claim['stage_ids'].remove('incumbent-full')
    if mutation == 'unknown_objective': claim['objective_ids'] = ['missing']
    with pytest.raises(ValueError):
        protocol.validate(p, base_dir=tmp_path, state=cycle._load(root)[1])
