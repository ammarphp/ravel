"""Conformance: reference-withheld CHECK-IN records contain only unblinded waypoints."""
import json
from copy import deepcopy

import pytest

import synthetic_identifiers as syn

from ravel.validation import validate_checkin as vc



def waypoint(kind='cutflow-monotone'):
    return {'kind': kind, 'counts': [100, 70, 20]} if kind == 'cutflow-monotone' else {
        'kind': 'mc-precision', 'relative_errors': [0.1, 0.2], 'target': 0.25}


def record():
    return {'schema_version': 1, 'kind': 'checkin1', 'variant': 'reference_withheld', 'sections': {
        'i': 'Supplied prediction.', 'i-b': 'Allowed source census.', 'iv': 'Bounded plan.',
        'v': [{'id': 'F1', 'text': 'Declared precision target.'}], 'vi': ['answer', 'ask', 'propose'],
        'withheld_waypoints': [waypoint(), waypoint('mc-precision')]}}


def contract(tmp_path, kind='blinded', identifiers=None, quantities=None, task_mode='reproduce'):
    row = {'kind': kind, 'statement': 'Withhold comparison values.', 'evidence': [],
           'identifiers': identifiers if identifiers is not None else {'inspire': ['ins1004']}}
    if quantities: row['scope'] = {'quantities': quantities}
    doc = {'task_mode': task_mode, 'targets': {'inspire': ['ins1004']}, 'forbidden_sources': [row]}
    (tmp_path / 'inputs').mkdir(exist_ok=True)
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(doc))
    return doc


def errors(doc, tmp_path=None):
    if tmp_path:
        doc['sections']['sources'] = [{'none': 'No external values are read.'}]
    return vc.validate(doc, base_dir=str(tmp_path) if tmp_path else None)


def test_missing_withheld_waypoints_refused():
    doc = record(); del doc['sections']['withheld_waypoints']
    assert any('withheld_waypoints' in e for e in errors(doc))


@pytest.mark.parametrize('field,value', [('ii', 'Published gallery'), ('iii', {'figure_id': '1'}),
    ('gallery', ['fictional-note.pdf']), ('figure_target', {'figure_id': '1'}),
    ('comparison', {'published_value': 2}), ('plan', {'nested': {'published_value': 2}})])
def test_reference_material_refused(field, value):
    doc = record(); doc['sections'][field] = value
    assert any('withheld' in e and ('published' in e or 'gallery' in e or 'target' in e) for e in errors(doc))


@pytest.mark.parametrize('kind', ['blinded', 'blinded-data', 'no-value-extraction'])
def test_restricted_reproduction_requires_named_variant(tmp_path, kind):
    contract(tmp_path, kind)
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii={'waypoint': 'published values'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))


@pytest.mark.parametrize('bad', [None, [], [{'kind': 'unknown'}], [{'kind': 'cutflow-monotone'}],
    [{'kind': 'cutflow-monotone', 'counts': [10, 20]}],
    [{'kind': 'mc-precision', 'relative_errors': [0.4], 'target': 0.2}],
    [{'kind': 'sigma-br-lumi', 'sigma_pb': -1, 'br': 0.5, 'lumi_fb': 1, 'expected_events': 10}],
    [{'kind': 'generator-closure', 'generator_sigma_pb': 1, 'table_sigma_pb': 2}],
    [{'kind': 'invisible-census', 'detector_particles': [1], 'spectrum_particles': [2]}]])
def test_uncheckable_waypoint_refused(bad):
    doc = record(); doc['sections']['withheld_waypoints'] = bad
    assert any('waypoint' in e for e in errors(doc))


@pytest.mark.parametrize('missing', ['result_sealed_first', 'label', 'phase'])
def test_unsealed_or_unlabelled_comparison_refused(missing):
    doc = record()
    doc['post_sealing_comparison'] = {'result_sealed_first': True, 'phase': 'after-delivery',
                                     'label': 'after-sealing', 'published_value': 2}
    del doc['post_sealing_comparison'][missing]
    assert any('sealing' in e for e in errors(doc))


def test_two_different_waypoints_pass():
    assert errors(record()) == []


@pytest.mark.parametrize('task_mode', ['reproduce', 'reinterpret', 'projection', 'scan', 'no_routine', 'research', 'unsupported'])
def test_withheld_admitted_for_reproduction_modes(tmp_path, task_mode):
    contract(tmp_path, task_mode=task_mode)
    assert errors(record(), tmp_path) == []


def test_all_waypoint_kinds_pass():
    doc = record()
    doc['sections']['withheld_waypoints'] += [
        {'kind': 'generator-closure', 'generator_sigma_pb': 2, 'table_sigma_pb': 2.1,
         'order_difference': 'Declared perturbative order difference.', 'relative_tolerance': 0.1,
         'source': {'path': 'xsec/fictional-rates.json'}},
        {'kind': 'sigma-br-lumi', 'sigma_pb': 2, 'br': 0.5, 'lumi_fb': 3, 'expected_events': 3000},
        {'kind': 'invisible-census', 'detector_particles': [1, 2], 'spectrum_particles': [2, 1]}]
    assert errors(doc) == []


def test_comparison_after_delivery_is_labelled_after_sealing():
    doc = record(); doc['post_sealing_comparison'] = {
        'result_sealed_first': True, 'phase': 'after-delivery', 'label': 'after-sealing', 'published_value': 2}
    assert errors(doc) == []


def test_unrestricted_reproduction_unchanged(tmp_path):
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii={'waypoint': 'comparison'})
    del doc['sections']['withheld_waypoints']
    assert vc.validate(doc) == []


def test_unrelated_identity_or_quantity_does_not_require_withheld(tmp_path):
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii={'waypoint': 'comparison'})
    contract(tmp_path, identifiers={'inspire': ['ins1008']})
    assert errors(deepcopy(doc), tmp_path) == []
    contract(tmp_path, kind='no-value-extraction', quantities=['text'])
    assert errors(deepcopy(doc), tmp_path) == []


def test_path_restricted_comparison_requires_withheld(tmp_path):
    contract(tmp_path)
    path = tmp_path / 'inputs/task_contract.json'
    data = json.loads(path.read_text())
    data['forbidden_sources'] = [{'kind': 'no-value-extraction', 'paths': ['fictional-note.pdf'],
        'origin': 'harness', 'statement': 'Withhold numeric comparisons.', 'evidence': []}]
    path.write_text(json.dumps(data))
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii={'source': {'path': 'inputs/fictional-note.pdf'}, 'waypoint': 'comparison'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))


def test_unrestricted_automatic_reproduction_keeps_variant_selection():
    contract = {'task_mode': 'reproduce'}
    assert vc.checkin1_variant({'sections': {}}, contract) == 'reproduction'


def test_absolute_path_restricted_comparison_requires_withheld(tmp_path):
    contract(tmp_path)
    path = tmp_path / 'inputs/task_contract.json'
    data = json.loads(path.read_text())
    data['forbidden_sources'] = [{'kind': 'no-value-extraction', 'paths': ['fictional-note.pdf'],
        'origin': 'harness', 'statement': 'Withhold numeric comparisons.', 'evidence': []}]
    path.write_text(json.dumps(data))
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii={'source': {'path': str(tmp_path / 'inputs/fictional-note.pdf')}, 'waypoint': 'comparison'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))


@pytest.mark.parametrize('task_mode,variant', [('research', 'calculation'), ('no_routine', 'new_search')])
def test_restriction_selects_the_variant_only_in_place_of_reproduction(tmp_path, task_mode, variant):
    contract(tmp_path, 'blinded', identifiers={}, task_mode=task_mode)
    doc = record(); doc['variant'] = variant
    assert not any('use reference_withheld' in e for e in errors(doc, tmp_path))


# Review findings: required selection, published material and allowed internal content.

def _reproduction(iii):
    doc = record(); doc['variant'] = 'reproduction'
    doc['sections'].update(ii='gallery', iii=iii)
    return doc


def test_identity_only_comparison_target_requires_withheld(tmp_path):
    data = contract(tmp_path)
    data['targets'] = {}
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(data))
    doc = _reproduction({'identifiers': {'inspire': ['ins1004']}, 'waypoint': 'comparison'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))


@pytest.mark.parametrize('key,declared,target', [('arxiv', syn.arxiv(4), syn.arxiv(4) + 'v2'), ('inspire', 'ins1004', 'ins01004')])
def test_equivalent_identity_spellings_require_withheld(tmp_path, key, declared, target):
    data = contract(tmp_path, identifiers={key: [declared]})
    data['targets'] = {key: [target]}
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(data))
    doc = _reproduction({'waypoint': 'comparison'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))
    data['targets'] = {}
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(data))
    doc = _reproduction({'identifiers': {key: [target]}, 'waypoint': 'comparison'})
    assert any('reference_withheld' in e for e in errors(doc, tmp_path))


def closure(source):
    return {'kind': 'generator-closure', 'generator_sigma_pb': 2, 'table_sigma_pb': 2,
            'order_difference': 'Declared perturbative order difference.', 'relative_tolerance': 0.1,
            'source': source}


def test_generator_closure_from_the_published_comparison_table_refused(tmp_path):
    contract(tmp_path)
    doc = record(); doc['sections']['withheld_waypoints'].append(closure({'identifiers': {'inspire': ['ins1004']}}))
    assert any('waypoint 3' in e for e in errors(doc, tmp_path))
    doc['sections']['withheld_waypoints'][-1] = closure({'identifiers': {'inspire': ['ins01004']}})
    assert any('waypoint 3' in e for e in errors(doc, tmp_path))


def test_generator_closure_requires_a_declared_independent_source(tmp_path):
    contract(tmp_path)
    doc = record(); row = closure(None); del row['source']
    doc['sections']['withheld_waypoints'].append(row)
    assert any('waypoint 3' in e for e in errors(doc, tmp_path))
    doc['sections']['withheld_waypoints'][-1] = closure({'path': 'xsec/fictional-rates.json'})
    assert errors(doc, tmp_path) == []


@pytest.mark.parametrize('field,value', [('gallery', ['fictional-note.pdf']), ('figure_target', {'figure_id': '1'}),
                                         ('published_figure_gallery', ['page1.pdf'])])
def test_post_sealing_comparison_cannot_carry_gallery_or_figure_target(field, value):
    doc = record()
    doc['post_sealing_comparison'] = {'result_sealed_first': True, 'phase': 'after-delivery',
                                      'label': 'after-sealing', 'published_value': 2, field: value}
    assert any('withheld' in e and field in e for e in errors(doc))


def test_internal_generator_comparison_is_not_published_material():
    doc = record(); doc['sections']['comparison'] = {'generator_a': 2, 'generator_b': 2}
    assert errors(doc) == []


def test_internal_diagnostic_gallery_is_not_published_material():
    doc = record(); doc['sections']['gallery'] = ['outputs/diagnostics/cutflow.png', {'path': 'outputs/diagnostics/precision.png'}]
    assert errors(doc) == []


@pytest.mark.parametrize('value', [{'source': {'identifiers': {'inspire': ['ins1004']}}, 'generator_a': 2},
                                   {'reference': {'path': 'inputs/fictional-note.pdf'}, 'generator_a': 2}])
def test_comparison_against_an_external_source_still_refused(value):
    doc = record(); doc['sections']['comparison'] = value
    assert any('withheld' in e and 'comparison' in e for e in errors(doc))


def test_same_named_comparison_file_elsewhere_does_not_require_withheld(tmp_path):
    data = contract(tmp_path)
    data['forbidden_sources'] = [{'kind': 'no-value-extraction', 'paths': ['fictional-note.pdf'],
        'origin': 'harness', 'statement': 'Withhold numeric comparisons.', 'evidence': []}]
    data['targets'] = {}
    (tmp_path / 'inputs/task_contract.json').write_text(json.dumps(data))
    doc = _reproduction({'source': {'path': 'inputs/allowed/fictional-note.pdf'}, 'waypoint': 'comparison'})
    assert errors(doc, tmp_path) == []
