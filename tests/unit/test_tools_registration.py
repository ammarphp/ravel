"""Registration of tool fragments: operations, census rows and refusal retirements."""
import hashlib
import json

import pytest

from registration_tree import census_row, command_operation, fragment, merger, snapshot, tree


def test_a_fragment_that_redefines_a_registered_operation_is_refused(tmp_path):
    root = tree(tmp_path)
    signature, _ = command_operation('ml-training', module='ravel.fictional_module')
    fragment(root, 'tools', 'fictional', {'schema_version': 1, 'operation_signatures': {'ml-training': signature}})
    before = snapshot(root)
    m = merger()
    with pytest.raises(m.Collision, match='ml-training'):
        m.merge(root, ['tools'])
    assert snapshot(root) == before


def test_the_merge_is_idempotent(tmp_path):
    root = tree(tmp_path)
    fragment(root, 'tools', 'census-rows', {'schema_version': 1, 'rows': [census_row('fictional-sampler')]})
    fragment(root, 'tools', 'refusals', {'schema_version': 1, 'refusal_classes': [{
        'id': 'FX-01', 'title': 'Fictional runtime not qualified', 'refused': 'Fictional runtime execution',
        'why': 'Fictional platform qualification is pending.', 'refused_by': 'ravel.setup.qualification',
        'groups': ['python-host'], 'would_make_it_possible': 'A fictional qualification receipt.'}]})
    m = merger()
    _, changed = m.merge(root, ['tools'])
    assert 'native/setup/toolchain-manifest.json' in changed and 'src/ravel/data/backends/census.json' in changed
    after = snapshot(root)
    assert m.merge(root, ['tools'])[1] == [] and snapshot(root) == after


def test_a_census_row_turns_qualified_only_with_a_pinned_receipt(tmp_path):
    root = tree(tmp_path)
    receipt = root / 'evidence/fictional-receipt.json'
    receipt.parent.mkdir()
    receipt.write_text('{"fictional": true}\n')
    pin = {'path': 'evidence/fictional-receipt.json', 'sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}
    fragment(root, 'tools', 'census-rows', {'schema_version': 1, 'rows': [
        census_row('fictional-unpinned', 'qualified'),
        census_row('fictional-wrong-pin', 'qualified', receipt={**pin, 'sha256': '0' * 64}),
        census_row('fictional-pinned', 'qualified', receipt=pin)]})
    merger().merge(root, ['tools'])
    census = {r['id']: r for r in json.loads((root / 'src/ravel/data/backends/census.json').read_text())['tools']}
    assert 'census-fictional-unpinned' not in census and 'census-fictional-wrong-pin' not in census
    assert census['census-fictional-pinned']['status'] == 'qualified'


def test_a_refusal_retirement_without_its_receipts_is_refused(tmp_path):
    root = tree(tmp_path)
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    identity = manifest['refusal_classes'][0]['id']
    fragment(root, 'tools', 'retire', {'schema_version': 1, 'retire_refusals': [
        {'id': identity, 'requires': ['fictional installation receipt']}]})
    reports, changed = merger().merge(root, ['tools'])
    assert changed == []
    assert any('waits for its pinned' in x for row in reports[0]['not_applied'] for x in row['reasons'])
    receipt = root / 'evidence/fictional-install.json'
    receipt.parent.mkdir()
    receipt.write_text('{}\n')
    fragment(root, 'tools', 'retire', {'schema_version': 1, 'retire_refusals': [
        {'id': identity, 'receipts': [{'path': 'evidence/fictional-install.json',
                                       'sha256': hashlib.sha256(b'{}\n').hexdigest()}]}]})
    merger().merge(root, ['tools'])
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    assert identity not in {r['id'] for r in manifest['refusal_classes']}


def test_a_refusal_class_naming_an_undeclared_group_is_not_applied(tmp_path):
    root = tree(tmp_path)
    fragment(root, 'tools', 'refusals', {'schema_version': 1, 'refusal_classes': [{
        'id': 'FX-02', 'title': 'Fictional', 'refused': 'Fictional', 'why': 'Fictional.',
        'refused_by': 'ravel.setup.qualification', 'groups': ['fictional-group'],
        'would_make_it_possible': 'Fictional.'}]})
    reports, changed = merger().merge(root, ['tools'])
    assert changed == [] and reports[0]['not_applied'][0]['refusal_class'] == 'FX-02'


def test_a_compute_operation_without_its_executor_card_is_not_registered(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('fictional-native-step')
    signature['effects'] = ['executes_native']
    fragment(root, 'tools', 'fictional', {'schema_version': 1,
             'operation_signatures': {'fictional-native-step': signature},
             'mode_descriptors': {'fictional-native-step': descriptor}})
    reports, changed = merger().merge(root, ['tools'])
    assert changed == []
    assert any('executor table names no production card' in x
               for row in reports[0]['not_applied'] for x in row['reasons'])
