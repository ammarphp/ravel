"""Obligations from the reading."""
import synthetic_identifiers as syn
import json
from pathlib import Path

import pytest

from ravel.validation.validate_task_contract import validate
from ravel.workflow import request_reading as rr, route_prompt, task_completion as tc

CORPUS = syn.load_json(Path(__file__).parent / 'fixtures/intake-corpus/requests.json')
CASES = {row['id']: row['prompt'] for row in CORPUS['cases']}
IDS = [row['id'] for row in CORPUS['cases']]


@pytest.mark.parametrize('case', CORPUS['cases'], ids=IDS)
def test_the_original_request_obligation_is_byte_identical_and_the_contract_validates(case):
    prompt = case['prompt']
    contract = route_prompt.route(prompt)
    assert validate(contract) == []
    census = contract['task_requirements']
    assert census['obligations'][0] == tc.initial_requirements(prompt)['obligations'][0]
    assert json.dumps(census['obligations'][0], sort_keys=True) == json.dumps(
        tc.initial_requirements(prompt)['obligations'][0], sort_keys=True)
    tc.validate_requirements(contract)


@pytest.mark.parametrize('case', CORPUS['cases'], ids=IDS)
def test_every_reading_item_that_binds_the_request_is_an_obligation_with_its_span(case):
    prompt = case['prompt']
    reading = rr.document(prompt)
    census = tc.census_from_reading(prompt, reading)
    by_id = {row['id']: row for row in census['obligations']}
    for c in reading['constraints']:
        if c['type'] in rr.CONSTRAINT_OBLIGATIONS:
            row = by_id[f"{rr.CONSTRAINT_OBLIGATIONS[c['type']][1]}-{c['id']}"]
            assert row['evidence'] == c['evidence'] and row['criteria']['constraint'] == c['type']
        else:
            assert c['type'] in ('delegation', 'identity_context')
            assert not [o for o in census['obligations'] if o['criteria'].get('reading_item') == c['id']]
    for f in reading['facts']:
        if f['type'] in rr.RANGE_FACTS:
            assert by_id[f'range-{f["id"]}']['evidence'] == f['evidence']
    for d in reading['deliverables']:
        for obligation in d['obligation_ids']:
            assert obligation in by_id
    for row in census['obligations'][1:]:
        assert row['evidence'] and all(prompt[s['start']:s['end']] == s['text'] for s in row['evidence'])


def test_requested_stages_tools_statistic_template_and_ranges_reach_the_census():
    census = route_prompt.route(CASES['Q37'])['task_requirements']['obligations']
    criteria = [row['criteria'] for row in census]
    assert {'Powheg', 'Pythia', 'Rivet'} <= {c.get('tool') for c in criteria}
    r12 = route_prompt.route(CASES['R12-prescribed-stat'])['task_requirements']['obligations']
    assert 'significance 2(sqrt(S+B) - sqrt(B))' in [r['criteria'].get('statistic') for r in r12]
    assert any(r['id'].startswith('range-') and r['kind'] == 'coverage' for r in r12)
    r14 = route_prompt.route(CASES['R14-yield-template'])['task_requirements']['obligations']
    kinds = {r['criteria'].get('constraint') for r in r14}
    assert {'template', 'keep_fixed', 'source_restriction', 'requested_stage'} <= kinds


def test_negated_stages_are_obligations_not_to_perform_them():
    rows = route_prompt.route(CASES['R11-parton-shape'])['task_requirements']['obligations']
    negated = [r for r in rows if r['criteria'].get('constraint') == 'negated_stage']
    assert {r['criteria']['stage'] for r in negated} == {'shower', 'detector'}
    assert all(r['kind'] == 'quality' for r in negated)


@pytest.mark.parametrize('prompt', [
    ('Reproduce Figure 3 of ' + syn.analysis(1) + ' for a slepton-bino model.'),
    ('Reproduce the observed 95% CL exclusion contour of the ATLAS compressed-slepton search (arXiv:' + syn.arxiv(32) + ').'),
])
def test_a_published_figure_comparison_is_a_quality_obligation(prompt):
    rows = route_prompt.route(prompt)['task_requirements']['obligations']
    comparison = [r for r in rows if r['id'].startswith('figure-comparison-')]
    assert comparison and all(r['kind'] == 'quality' and r['criteria']['published_figure_comparison']
                              for r in comparison)


def test_the_census_is_written_for_every_request_not_only_whole_goal_kinds():
    contract = route_prompt.route(CASES['R22-generate'])
    assert contract['task_mode'] == 'generate'
    ids = [row['id'] for row in contract['task_requirements']['obligations']]
    assert ids[0] == 'original-request' and len(ids) > 1
    assert contract['task_requirements']['assignments'] == []


def test_a_request_for_exactly_one_thing_keeps_the_whole_request_as_that_obligation():
    prompt = CASES['R01-literal']
    contract = route_prompt.route(prompt)
    assert contract['task_requirements']['obligations'] == tc.initial_requirements(prompt)['obligations']
    reading = rr.document(prompt)
    assert reading['deliverables'][0]['obligation_ids'] == ['original-request']


def test_an_invalid_reading_is_refused_by_the_census():
    prompt = CASES['G1']
    reading = rr.document(prompt)
    reading['facts'][0]['evidence'][0]['text'] = 'not the request'
    with pytest.raises(ValueError, match='reading is invalid'):
        tc.census_from_reading(prompt, reading)
