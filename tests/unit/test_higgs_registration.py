"""Registration of scalar-sector fragments into the shared registries."""
import json

import pytest

from registration_tree import ROOT, command_operation, fragment, merger, snapshot, tree


def test_a_mode_without_a_signature_is_refused_and_nothing_registers(tmp_path):
    root = tree(tmp_path)
    _, descriptor = command_operation('fictional-scalar-fit')
    fragment(root, 'higgs', 'fictional', {'schema_version': 1,
             'mode_descriptors': {'fictional-scalar-fit': descriptor},
             'manifest_operations': [{'mode': 'fictional-scalar-fit', 'groups': ['python-host']}]})
    before = snapshot(root)
    reports, changed = merger().merge(root, ['higgs'])
    refused = [r for report in reports for r in report['not_applied'] if r.get('mode') == 'fictional-scalar-fit']
    assert refused and 'declares no operation signature' in refused[0]['reasons'][0]
    assert changed == [] and snapshot(root) == before


def test_a_fragment_naming_a_registered_mode_with_another_implementation_collides(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('figure-comparison', module='ravel.fictional_module')
    fragment(root, 'higgs', 'fictional', {'schema_version': 1,
             'operation_signatures': {'figure-comparison': signature},
             'mode_descriptors': {'figure-comparison': descriptor}})
    before = snapshot(root)
    m = merger()
    with pytest.raises(m.Collision, match='figure-comparison'):
        m.merge(root, ['higgs'])
    assert m.main(['--root', str(root), '--domain', 'higgs']) == 2
    assert snapshot(root) == before


def test_a_conforming_operation_registers_once_and_a_second_run_is_byte_identical(tmp_path):
    root = tree(tmp_path)
    signature, descriptor = command_operation('fictional-scalar-fit')
    fragment(root, 'higgs', 'fictional', {'schema_version': 1,
             'operation_signatures': {'fictional-scalar-fit': signature},
             'mode_descriptors': {'fictional-scalar-fit': descriptor},
             'manifest_operations': [{'mode': 'fictional-scalar-fit', 'groups': ['python-host']}]})
    m = merger()
    _, changed = m.merge(root, ['higgs'])
    assert 'src/ravel/data/operation_signatures.json' in changed
    signatures = json.loads((root / 'src/ravel/data/operation_signatures.json').read_text())['operations']
    assert signatures['fictional-scalar-fit'] == signature
    manifest = json.loads((root / 'native/setup/toolchain-manifest.json').read_text())
    assert {'mode': 'fictional-scalar-fit', 'groups': ['python-host']} in manifest['operations']
    after = snapshot(root)
    assert m.merge(root, ['higgs'])[1] == [] and snapshot(root) == after
    assert m.main(['--root', str(root), '--check']) == 0


@pytest.mark.parametrize('main_list', [True, False])
def test_a_withheld_group_makes_the_registered_operation_unreleased(tmp_path, main_list):
    root = tree(tmp_path)
    main = root / 'native/setup/toolchain-manifest.json'
    if not main_list:
        # A released main file carries no withheld list; the merger starts one for a held fragment group.
        document = json.loads(main.read_text()); document.pop('unreleased', None)
        main.write_text(json.dumps(document, indent=1) + '\n')
    # A fictional group fragment that carries its own release hold.
    held = {'id': 'fictional-held', 'title': 'fictional-held', 'depends_on': ['python-host'], 'size_gb': 0.25,
            'minutes': 1, 'steps': [{'id': 'write', 'kind': 'write_file', 'path': '{P}/fictional',
                                     'content': 'fictional'}],
            'checks': [{'id': 'fictional-held-ready', 'kind': 'file', 'path': '{P}/fictional'}]}
    (root / 'native/setup/groups').mkdir(parents=True, exist_ok=True)
    (root / 'native/setup/groups/fictional-held.json').write_text(json.dumps({'group': held, 'unreleased': {
        'groups': [{'id': 'fictional-held', 'check': 'fictional-held-ready', 'reason': 'fictional hold'}],
        'operations': []}}, indent=1) + '\n')
    signature, descriptor = command_operation('fictional-scalar-fit')
    fragment(root, 'higgs', 'fictional', {'schema_version': 1,
             'operation_signatures': {'fictional-scalar-fit': signature},
             'mode_descriptors': {'fictional-scalar-fit': descriptor},
             'manifest_operations': [{'mode': 'fictional-scalar-fit', 'groups': ['python-host', 'fictional-held']}]})
    reports, _ = merger().merge(root, ['higgs'])
    assert 'fictional-scalar-fit' in [mode for report in reports for mode in report['applied']]
    manifest = json.loads(main.read_text())
    assert {'mode': 'fictional-scalar-fit', 'groups': ['fictional-held']} in manifest['unreleased']['operations']


def test_the_repository_registries_reflect_every_applicable_fragment():
    """The shipped registries are current: a merge of the shipped fragments changes nothing."""
    m = merger()
    reports, changed = m.merge(ROOT, write=False)
    assert changed == []
    by_fragment = {r['fragment']: r for r in reports}
    likelihood = by_fragment['src/ravel/data/higgs/registration/higgs-published-likelihood.json']
    assert likelihood['applied'] == [] and likelihood['not_applied'][0]['mode'] == 'higgs-published-likelihood'
    census = json.loads((ROOT / 'src/ravel/data/backends/census.json').read_text())
    row = next(r for r in census['tools'] if r['id'] == 'census-higgstools-lilith')
    assert row['status'] == 'not_installed' and {'higgstools', 'lilith'} <= set(row['installer_groups'])


def test_signature_conformance_holds_after_the_merge():
    from ravel.validation.signature_conformance import conformance
    assert conformance() == []
