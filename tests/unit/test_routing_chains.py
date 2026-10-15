"""Synthetic obligation-chain controls; no execution or source acquisition."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import re

import pytest

from ravel.workflow import capability_routing as cr
from ravel.workflow.request_reading import document


PROMPT = (
    'Implement the search in the attached paper and predict the binned signal yield of observable X '
    'for a 700 GeV chargino with a 150 GeV LSP at 60 fb^-1; fill the attached template.json; '
    'do not take values from the published tables.'
)
MODES = ['model-events', 'event-production', 'columnar-analysis', 'cross-section',
         'normalization-ledger', 'fill-template']


def selected(result):
    return [c for c in result['candidates'] if c['selection'] == 'declared_chain_requires_host_review']


def test_exclusion_does_not_select_prediction_chain():
    result = cr.plan('Reinterpret the attached search for a 700 GeV chargino with a 150 GeV LSP '
                     'at 60 fb^-1 and report the 95% CLs exclusion limit.')
    assert selected(result) == []


@pytest.mark.parametrize('prompt', [
    'Write a document for a 700 GeV chargino and fill the attached template.',
    'From supplied LHE events, predict binned yields for a 700 GeV chargino and fill the template.',
    'Predict binned signal yields for a 700 GeV chargino; do not generate events; fill the template.',
    'Predict binned signal yields for a 700 GeV chargino; do not simulate the detector; fill the template.',
])
def test_other_deliverables_supplied_events_and_negated_stages_do_not_select_chain(prompt):
    assert selected(cr.plan(prompt)) == []


def test_prediction_chain_is_complete_ordered_and_not_admitted():
    result = cr.plan(PROMPT)
    chain = selected(result)
    assert [c['mode'] for c in chain] == MODES
    assert [c['chain_step'] for c in chain] == list(range(1, 7))
    assert all(c['chain'] == 'binned-yield-prediction' and c['scope'] == 'component' for c in chain)
    assert all(c['obligation_ids'] and c['preconditions'] for c in chain)
    columnar = chain[2]
    assert columnar['required_task_fields'] == ['analysis_spec']
    assert 'analysis_spec' in columnar['operation']['contract']
    assert all(c['conditions']['generation_effect'] == 'unresolved_requires_host_review' for c in chain)
    assert all(c['conditions']['routine_reuse'] == 'unresolved_requires_resource_census' for c in chain)
    assert not result['compute_authorized'] and not result['physics_validated']
    assert result['original_request'] == PROMPT and not result['parent_goal_replaced']
    assert result['parent_goal_acceptance'] == 'not_assessed'


def test_explicit_generation_and_reported_routine_gap_remain_planning_conditions():
    prompt = 'Generate events for a 700 GeV chargino; predict the binned signal yield and fill the template.'
    result = cr.plan(prompt, findings=[{'kind': 'no-routine', 'detail': 'Supplied synthetic resource census.', 'evidence': []}])
    chain = selected(result)
    assert [c['mode'] for c in chain] == MODES
    assert all(c['conditions'] == {'generation_effect': 'requested', 'routine_reuse': 'reported_no_routine'} for c in chain)
    assert not result['compute_authorized']


def test_obligations_select_chain_without_descriptor_or_prompt_terms(monkeypatch):
    original = cr.plan(PROMPT)
    contract = deepcopy(original['legacy_draft'])
    reading = deepcopy(document(PROMPT))
    monkeypatch.setattr(cr, 'suggest', lambda *a, **k: [])
    result = cr.plan(PROMPT, contract=contract, reading=reading)
    assert [c['mode'] for c in selected(result)] == MODES
    # A template alone cannot turn a scalar calculation into an event prediction.
    for c in contract['task_requirements']['obligations']:
        if c['criteria'].get('claim_kind') == 'prediction': c['criteria']['claim_kind'] = 'calculation'
    reading['deliverables'] = []
    assert selected(cr.plan(PROMPT, contract=contract, reading=reading)) == []


def test_declared_tools_resolve_from_cli_without_becoming_science_modes():
    catalog = cr.catalogue()
    assert not {'normalization-ledger', 'fill-template'} & {o['mode'] for o in catalog['operations']}
    tools = {t['mode']: t for t in catalog['planning_tools']}
    assert tools['normalization-ledger']['module'] == 'ravel.physics.normalization_ledger'
    assert tools['fill-template']['module'] == 'ravel.workflow.result_templates'
    assert all(t['dispatch_surface'] == 'focused-command' and t['status'] == 'source_present_not_admitted'
               for t in tools.values())


def test_host_candidate_is_retained_without_reordering_or_duplicate_modes():
    intent = {'mode': 'columnar-analysis', 'scope': 'component',
              'basis': {'start': 0, 'end': len(PROMPT), 'text': PROMPT}}
    result = cr.plan(PROMPT, intents=[intent])
    assert [c['mode'] for c in result['candidates']][:6] == MODES
    assert len({c['mode'] for c in result['candidates']}) == len(result['candidates'])
    assert selected(result)[2]['host_intent']['basis'] == intent['basis']


def test_chain_registry_is_bound_to_current_source_bytes():
    catalog = cr.catalogue()
    path = Path(cr.__file__).resolve().parents[1] / cr.CHAINS
    expected = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert expected in catalog['source_pins']
    assert catalog['declared_chains'] == json.loads(path.read_text())['chains']


@pytest.mark.parametrize('fault', ['version', 'extra-field', 'duplicate-chain', 'unknown-mode', 'duplicate-mode',
                                  'unknown-requirement', 'task-field-mode', 'task-field-empty', 'precondition'])
def test_malformed_chain_registry_refuses(fault):
    data = json.loads((Path(cr.__file__).resolve().parents[1] / cr.CHAINS).read_text())
    row = data['chains'][0]
    if fault == 'version': data['schema_version'] = 2
    elif fault == 'extra-field': row['hidden_route'] = True
    elif fault == 'duplicate-chain': data['chains'].append(deepcopy(row))
    elif fault == 'unknown-mode': row['modes'][0] = 'unknown-operation'
    elif fault == 'duplicate-mode': row['modes'].append(row['modes'][0])
    elif fault == 'unknown-requirement': row['requires']['opaque_key'] = 'opaque'
    elif fault == 'task-field-mode': row['task_fields']['unknown-operation'] = ['analysis_spec']
    elif fault == 'task-field-empty': row['task_fields']['columnar-analysis'] = ['']
    else: row['preconditions'] = ['']
    with pytest.raises(ValueError): cr._chains(data, set(MODES))


def test_chain_decision_data_and_new_tests_have_no_named_source_identities():
    root = Path(cr.__file__).resolve().parents[3]
    paths = [Path(cr.__file__), root / 'src/ravel/data/routing/chains.json',
             Path(__file__), root / 'tests/unit/test_initiate_yield_requests.py']
    # Generic publication/record identifier shapes; no named example is needed.
    identifier = re.compile(r'\b[A-Z]{3,5}-[A-Z]{2,6}-\d{2,4}-\d{2,4}\b|'
                            r'\b\d{4}\.\d{4,5}\b|\bins\d{6,}\b')
    for path in paths:
        assert not identifier.search(path.read_text()), path
    tree = ast.parse(Path(cr.__file__).read_text())
    selector = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_chain_candidates')
    assert not any(isinstance(n, ast.Name) and n.id in ('prompt', 'active', 'matching_text', 'suggest')
                   for n in ast.walk(selector))
