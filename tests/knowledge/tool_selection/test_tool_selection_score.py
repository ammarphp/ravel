"""Tool-selection battery: restraint plans, synthetic siblings, scorer metrics.

Product CI scores only the exported synthetic battery in this directory. The held-out battery
is reachable only through an interface that a caller outside this package implements.
"""
import copy
import json
from pathlib import Path

import pytest

from ravel.validation import tool_selection_score as ts

HERE = Path(__file__).resolve().parent
RESTRAINT = HERE / 'restraint.json'
SIBLINGS = HERE / 'siblings.json'
REPO = HERE.parents[2]
NATIVE = ts.native_operations()


@pytest.fixture(scope='module')
def battery():
    return ts.load_battery(HERE)


def _by_kind(plans, *kinds):
    return [p for p in plans if p['kind'] in kinds]


# 1. restraint plans and twins ------------------------------------------------------------------
def test_at_least_six_restraint_plans_with_paired_twins(battery):
    restraint = _by_kind(battery, 'negative', 'minimal')
    twins = {p['twin_of']: p for p in _by_kind(battery, 'twin')}
    assert len(restraint) >= 6
    for plan in restraint:
        assert plan['case_id'] in twins, plan['case_id']
        assert twins[plan['case_id']]['expected_operations'], 'a twin must need a tool'


def test_restraint_plans_cover_the_required_situations(battery):
    tags = {p['situation'] for p in _by_kind(battery, 'negative', 'minimal')}
    assert {'conventions-shard', 'closed-form-width', 'published-limit-direct', 'must-hold',
            'recasting-inapplicable'} <= tags


def test_negative_plans_expect_no_native_operation(battery):
    for plan in _by_kind(battery, 'negative'):
        flat = ts.flatten_operations(plan['expected_operations'])
        assert not set(flat) & NATIVE, plan['case_id']
    for plan in _by_kind(battery, 'minimal'):
        assert not set(ts.flatten_operations(plan['expected_operations'])) & NATIVE


def test_every_plan_validates(battery):
    assert ts.validate_plans(battery) == []


def test_validation_refuses_a_twin_without_its_negative(battery):
    broken = [p for p in battery if p['kind'] != 'negative']
    assert any('twin_of' in e for e in ts.validate_plans(broken))


# 2. synthetic siblings and the identifier scan -------------------------------------------------
def test_one_sibling_per_reference_structure(battery):
    siblings = _by_kind(battery, 'sibling')
    assert len(siblings) == 27
    assert len({p['case_id'] for p in battery}) == len(battery)
    for plan in siblings:
        assert plan['shape'] == ts.shape_of(plan), plan['case_id']
        assert plan['shape']['operations'] >= 4


def test_identifier_scan_finds_nothing_in_the_exported_battery(battery):
    assert ts.scan_identifiers(battery) == []


# Identifier shapes are assembled at run time with fictional values, so this file names no paper.
@pytest.mark.parametrize('text', [
    'reproduce arXiv:' + '2101' + '.01234', 'see ' + '2012' + '.12345' + ' for details',
    '-'.join(['ATLAS', 'FAKE', '2099', '16']) + ' limit', '-'.join(['XYZ', '98', '006']) + ' result',
    'doi 10.' + '1007/JHEP01(2099)123', 'record ins' + '9999999'])
def test_identifier_scan_flags_paper_identifiers(battery, text):
    planted = copy.deepcopy(battery)
    planted[0]['notes'] = text
    assert ts.scan_identifiers(planted), text


def test_identifier_scan_flags_supplied_digests_by_meaning_free_hash(battery):
    planted = copy.deepcopy(battery)
    planted[0]['request'] = 'The zorblax quantity of the frobnicated sector.'
    blocked = ts.digest_terms('frobnicated sector')
    assert ts.scan_identifiers(battery, blocked_digests=blocked) == []
    assert ts.scan_identifiers(planted, blocked_digests=blocked)


def test_source_tree_names_no_held_out_location():
    text = (REPO / 'src/ravel/validation/tool_selection_score.py').read_text()
    for needle in ('evaluation-design', 'reference-plans', 'ravel-eval'):
        assert needle not in text


# 3. scorer metrics -----------------------------------------------------------------------------
def test_oracle_scores_clean(battery):
    report = ts.score_battery(battery, [ts.stub_oracle(p) for p in battery])
    assert report['unnecessary_native_operation_rate'] == 0
    assert report['unnecessary_consults']['total'] == 0
    assert report['cost_weighted_precision'] == 1.0
    assert report['under_call_rate_on_twins'] == 0
    assert report['fields']['operations']['recall'] == 1.0
    assert report['fields']['operations']['precision'] == 1.0
    assert report['must_ask_recall'] == 1.0


def test_overcaller_is_caught_on_negative_plans(battery):
    native = sorted(NATIVE)[0]
    subs = [ts.stub_overcall(p, native) for p in battery]
    report = ts.score_battery(battery, subs)
    assert report['restraint']['native_overcalls'] >= 6
    assert report['unnecessary_native_operation_rate'] > 0
    assert report['cost_weighted_precision'] < 1.0


def test_unnecessary_consults_exceed_one_per_plan(battery):
    plan = _by_kind(battery, 'negative')[0]
    sub = ts.stub_oracle(plan)
    sub['consults'] = 3
    result = ts.score_case(plan, sub)
    assert result['unnecessary_consults'] == 3 - plan['expected_consults_max']
    report = ts.score_battery([plan], [sub])
    assert report['unnecessary_consults']['plans_over_limit'] == 1


def test_silent_agent_under_calls_every_twin(battery):
    subs = [ts.stub_empty(p) for p in battery]
    report = ts.score_battery(battery, subs)
    assert report['under_call_rate_on_twins'] == 1.0
    assert report['unnecessary_native_operation_rate'] == 0


def test_cost_weighting_penalises_native_more_than_cheap_extras(battery):
    plan = _by_kind(battery, 'minimal')[0]
    cheap = ts.stub_oracle(plan)
    cheap['operations'] = cheap['operations'] + ['op:cross-section']
    heavy = ts.stub_oracle(plan)
    heavy['operations'] = heavy['operations'] + [sorted(NATIVE)[0]]
    p_cheap = ts.score_case(plan, cheap)['cost_weighted_precision']
    p_heavy = ts.score_case(plan, heavy)['cost_weighted_precision']
    assert p_heavy < p_cheap < 1.0


def test_per_field_precision_and_recall():
    plan = _plan(expected_operations=['op:a', 'op:b'], expected_checks=['check:x'])
    sub = {'case_id': 'p', 'operations': ['op:a', 'op:c'], 'checks': [], 'roles': [], 'knowledge': [],
           'consults': 0, 'asked': []}
    out = ts.score_case(plan, sub, effects={})
    assert out['fields']['operations'] == {'precision': 0.5, 'recall': 0.5}
    assert out['fields']['checks']['recall'] == 0.0


def test_must_ask_recall_scores_by_meaning_not_string():
    plan = _plan(kind='negative', expected_operations=[],
                 must_ask=[{'id': 'amb-scope', 'accept': ['which energy', 'collision energy']}])
    hit = {'case_id': 'p', 'operations': [], 'asked': ['Could you tell me the Collision Energy?']}
    by_id = {'case_id': 'p', 'operations': [], 'asked': ['amb-scope']}
    miss = {'case_id': 'p', 'operations': [], 'asked': ['What colour should the plot be?']}
    assert ts.score_case(plan, hit, effects={})['must_ask_recall'] == 1.0
    assert ts.score_case(plan, by_id, effects={})['must_ask_recall'] == 1.0
    assert ts.score_case(plan, miss, effects={})['must_ask_recall'] == 0.0


def test_new_entries_score_as_expected_after_landing():
    plan = _plan(expected_operations=['op:a'], expected_knowledge=['conv:units (NEW: SG-99)'])
    sub = {'case_id': 'p', 'operations': ['op:a'], 'knowledge': [], 'asked': []}
    pending = ts.score_case(plan, sub, effects={})
    assert pending['expected_after_landing']['knowledge'] == ['conv:units']
    assert pending['fields']['knowledge']['recall'] is None
    landed = ts.score_case(plan, sub, effects={}, landed={'SG-99'})
    assert landed['fields']['knowledge']['recall'] == 0.0
    assert landed['expected_after_landing']['knowledge'] == []


def test_new_entry_submitted_early_is_not_penalised():
    plan = _plan(expected_operations=['op:a'], expected_knowledge=['conv:units (NEW: SG-99)'])
    sub = {'case_id': 'p', 'operations': ['op:a'], 'knowledge': ['conv:units'], 'asked': []}
    assert ts.score_case(plan, sub, effects={})['fields']['knowledge']['precision'] is None


def test_optional_and_ordered_operations_flatten():
    assert ts.flatten_operations(['op:a → op:b', '(optional) op:c']) == ['op:a', 'op:b', 'op:c']
    assert ts.required_operations(['op:a → op:b', '(optional) op:c']) == {'op:a', 'op:b'}


# 4. stubs --------------------------------------------------------------------------------------
def test_negative_plans_score_zero_native_overcalls_on_stubs(battery):
    negatives = _by_kind(battery, 'negative', 'minimal')
    report = ts.score_battery(negatives, [ts.stub_oracle(p) for p in negatives])
    assert report['restraint']['native_overcalls'] == 0
    assert report['restraint']['plans'] == len(negatives)


def test_scorer_is_deterministic(battery):
    subs = [ts.stub_oracle(p) for p in battery]
    assert json.dumps(ts.score_battery(battery, subs), sort_keys=True) == \
        json.dumps(ts.score_battery(battery, subs), sort_keys=True)


def test_missing_submission_is_refused(battery):
    with pytest.raises(ValueError, match='no submission'):
        ts.score_battery(battery, [ts.stub_oracle(battery[0])])


# 5. held-out loader is an interface only ------------------------------------------------------
def test_held_out_loader_is_abstract_and_never_reads_files():
    with pytest.raises(TypeError):
        ts.HeldOutBattery()

    class Harness(ts.HeldOutBattery):
        def load(self):
            return [_plan()]

    plans = Harness().load()
    report = ts.score_held_out(Harness(), [ts.stub_oracle(plans[0])], effects={})
    assert report['plans'] == 1


def test_product_code_has_no_default_held_out_source():
    assert not hasattr(ts, 'DEFAULT_HELD_OUT_PATH')
    assert ts.HeldOutBattery.__abstractmethods__ == frozenset({'load'})


def _plan(**fields):
    plan = {'case_id': 'p', 'kind': 'sibling', 'request': 'synthetic', 'expected_operations': ['op:a'],
            'expected_checks': [], 'expected_roles': [], 'expected_knowledge': [],
            'forbidden_operations': [], 'expected_consults_max': 1, 'must_ask': [], 'notes': ''}
    plan.update(fields)
    return plan
