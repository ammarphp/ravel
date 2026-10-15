"""Registration of measurement-sector fragments into the shared registries."""
import json

import pytest

from registration_tree import ROOT, census_row, command_operation, fragment, merger, snapshot, tree


def test_an_operation_name_that_collides_with_a_registered_one_fails_the_merge(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('measurement', module='ravel.fictional_module')
    fragment(root, 'sm', 'fictional', {'schema_version': 1,
             'operation_signatures': {'measurement': signature}, 'mode_descriptors': {'measurement': descriptor}})
    before = snapshot(root)
    m = merger()
    with pytest.raises(m.Collision):
        m.merge(root, ['sm'])
    assert snapshot(root) == before


def test_running_the_merge_twice_yields_no_diff(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('fictional-measurement-step')
    fragment(root, 'sm', 'fictional', {'schema_version': 1,
             'operation_signatures': {'fictional-measurement-step': signature},
             'mode_descriptors': {'fictional-measurement-step': descriptor},
             'manifest_operations': [{'mode': 'fictional-measurement-step', 'groups': ['python-host']}],
             'curation': {'id': 'op:fictional-measurement-step', 'op': {
                 'use_when': ['Fictional supplied table.'], 'do_not_use_when': ['Fictional refusal.'],
                 'examples': [{'phrase': 'Fictional phrase.', 'spec': {'mode': 'fictional-measurement-step'}}]}}})
    m = merger()
    m.merge(root, ['sm'])
    assert (root / 'src/ravel/data/knowledge/curation/fictional-measurement-step.json').is_file()
    after = snapshot(root)
    assert m.merge(root, ['sm'])[1] == [] and snapshot(root) == after


def test_a_science_mode_is_offered_only_with_its_dispatch_curation_and_document(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('fictional-measurement-mode')
    signature['implementation'] = {'kind': 'science-mode', 'mode': 'fictional-measurement-mode',
                                   'module': 'ravel.physics.fictional_measurement_mode'}
    fragment(root, 'sm', 'fictional', {'schema_version': 1,
             'operation_signatures': {'fictional-measurement-mode': signature},
             'mode_descriptors': {'fictional-measurement-mode': descriptor}})
    reports, changed = merger().merge(root, ['sm'])
    reasons = [x for r in reports for row in r['not_applied'] for x in row['reasons']]
    assert changed == [] and any('no registered science mode' in x for x in reasons)


def test_every_shipped_measurement_operation_is_registered_or_reported_with_its_reason():
    reports, changed = merger().merge(ROOT, ['sm'], write=False)
    assert changed == []
    signatures = json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations']
    descriptors = json.loads((ROOT / 'src/ravel/data/mode_descriptors.json').read_text())['modes']
    for report in reports:
        for mode in report['applied'] + report['reflected']:
            if mode in signatures:
                assert mode in descriptors
                if signatures[mode]['implementation']['kind'] == 'science-mode':
                    assert (ROOT / 'src/ravel/data/knowledge/curation' / (mode + '.json')).is_file()
        for row in report['not_applied']:
            assert row['reasons'] and row.get('mode') not in signatures


def test_census_rows_carry_not_installed_until_a_qualification_receipt_exists(tmp_path):
    root = tree(tmp_path)
    fragment(root, 'sm', 'census-rows', {'schema_version': 1, 'rows': [
        census_row('fictional-generator'), census_row('fictional-fitter', 'qualified')]})
    reports, _ = merger().merge(root, ['sm'])
    census = {r['id']: r for r in json.loads((root / 'src/ravel/data/backends/census.json').read_text())['tools']}
    assert census['census-fictional-generator']['status'] == 'not_installed'
    assert 'census-fictional-fitter' not in census
    reasons = [x for row in reports[0]['not_applied'] for x in row['reasons']]
    assert any('pinned qualification receipt' in x for x in reasons)
    mirror = {r['id'] for r in json.loads((root / 'src/ravel/data/knowledge/qualification.json').read_text())['tools']}
    assert 'census-fictional-generator' in mirror
