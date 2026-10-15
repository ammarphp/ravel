"""Fictional planted errors and clean twins for general scalar-fit traps."""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).with_name('fixtures') / 'higgs-traps.json'


@pytest.mark.parametrize('trap_id', ['TH' + str(i) for i in range(1, 13)])
def test_planted_trap_is_caught(trap_id):
    from ravel.validation import higgs_checks
    twins = json.loads(FIXTURES.read_text())[trap_id]
    result = higgs_checks.check_trap(trap_id, twins['planted'])
    assert result['status'] == 'failed'
    assert result['findings'][0]['code'] == trap_id
    assert higgs_checks.check_trap(trap_id, twins['clean'])['status'] == 'passed'


@pytest.mark.parametrize('trap_id', ['TH' + str(i) for i in range(1, 13)])
def test_missing_trap_evidence_is_inconclusive(trap_id):
    from ravel.validation import higgs_checks
    assert higgs_checks.check_trap(trap_id, {})['status'] == 'inconclusive'


def test_trap_rows_are_registered_without_changing_legacy_ids():
    from ravel.workflow import premises, trap_sweep
    from ravel.validation import higgs_checks
    rows = premises.registry()['premises']
    assert tuple(r['id'][5:] for r in rows if r['id'][5:] in trap_sweep.TRAP_IDS) == trap_sweep.TRAP_IDS
    for identity in ('TH' + str(i) for i in range(1, 13)):
        row = next(r for r in rows if r['id'] == 'trap:' + identity)
        assert callable(higgs_checks.resolve(row['obligations'][0]['check']))


def test_premise_firing_and_cold_bundle(tmp_path):
    from ravel.workflow import premises, role_registry, knowledge_bundles
    assert 'trap:TH1' in {r['id'] for r in premises.firing({'tags': ['higgs', 'combination']})}
    card = role_registry.load('higgs-combination-reviewer')
    bundle = knowledge_bundles.materialize(card, {'node_id': 'N-0001', 'tags': ['higgs', 'combination']}, {'workspace': tmp_path})
    assert 'trap:TH1' in bundle['served_ids']


def twin(trap_id, kind='clean'):
    return json.loads(FIXTURES.read_text())[trap_id][kind]


def status(trap_id, doc):
    from ravel.validation import higgs_checks
    return higgs_checks.check_trap(trap_id, doc)['status']


def test_any_shared_event_set_needs_a_joint_likelihood():
    doc = twin('TH1', 'planted')
    doc['measurements'][0]['representation'] = 'differential'
    assert status('TH1', doc) == 'failed'
    doc['measurements'][1]['representation'] = 'differential'
    assert status('TH1', doc) == 'failed'
    doc['joint_likelihoods'] = [{'left': 'ANA-0002', 'right': 'ANA-0001', 'source': 'SRC-003'}]
    assert status('TH1', doc) == 'passed'
    doc['measurements'][1]['id'] = 'ANA-0001'
    assert status('TH1', doc) == 'inconclusive'


def test_partial_decorrelation_needs_located_evidence():
    doc = twin('TH2')
    doc['theory_components'][0]['correlation'] = [[1, 0.5], [0.5, 1]]
    assert status('TH2', doc) == 'failed'
    doc['theory_components'][0]['decorrelation_evidence'] = 'SRC-003, second section'
    assert status('TH2', doc) == 'passed'


def test_flat_direction_names_are_case_insensitive_and_cover_split_couplings():
    doc = twin('TH5', 'planted')
    doc['parameterization']['free'] = ['BR_undet', 'kappa_W', 'kappa_Z']
    assert status('TH5', doc) == 'failed'
    doc['parameterization']['width_constraint'] = 'SRC-004 supplied width measurement'
    assert status('TH5', doc) == 'passed'


@pytest.mark.parametrize('trap_id,path', [
    ('TH6', ('likelihood', 'approximation')), ('TH9', ('exclusion', 'method')),
    ('TH9', ('exclusion', 'interpretation')), ('TH11', ('dataset_release', 'claim')),
])
def test_undeclared_vocabulary_is_inconclusive(trap_id, path):
    for kind in ('clean', 'planted'):
        doc = twin(trap_id, kind)
        doc[path[0]][path[1]] = 'synthetic-unknown'
        assert status(trap_id, doc) == 'inconclusive'


def test_confidence_region_dimension_counts_parameters_of_interest():
    doc = twin('TH10')
    assert 'free_parameters' not in doc['gof']
    doc['gof'].update(dof=5, parameters_of_interest=2)
    assert status('TH10', doc) == 'failed'
    doc['gof']['free_parameters'] = doc['gof'].pop('parameters_of_interest')
    assert status('TH10', doc) == 'inconclusive'


def test_goodness_of_fit_dimension_is_the_residual():
    gof = {'statistic': 'chi2', 'purpose': 'goodness-of-fit', 'dof': 8, 'observables': 10,
           'fitted_parameters': 2, 'p_value': 0.3}
    assert status('TH10', {'gof': gof}) == 'passed'
    assert status('TH10', {'gof': {**gof, 'dof': 10}}) == 'failed'
    assert status('TH10', {'gof': {**gof, 'fitted_parameters': 10}}) == 'inconclusive'


@pytest.mark.parametrize('role,traps', [
    ('higgs-coupling-analyst', range(1, 7)), ('extended-scalar-modeler', range(7, 10)),
    ('higgs-combination-reviewer', range(1, 13)),
])
def test_roles_can_run_the_checks_of_traps_they_must_read(role, traps):
    from ravel.workflow import review_projection_checks, role_registry
    card = role_registry.load(role)
    for number in traps:
        assert 'trap:TH%d' % number in card['knowledge']['must_read']
        assert review_projection_checks.permitted(card, 'check:higgs.trap_TH%d' % number)
    outsider = role_registry.load('consult-higgs')
    assert not review_projection_checks.permitted(outsider, 'check:higgs.trap_TH1')


def test_validator_rows_describe_their_input_document():
    from ravel.workflow import review_projection_checks
    rows = {r['id']: r for r in review_projection_checks.allowlist()['validators']}
    descriptions = [rows['check:higgs.trap_TH%d' % i]['description'] for i in range(1, 13)]
    assert len(set(descriptions)) == 12 and all('Input:' in d for d in descriptions)
