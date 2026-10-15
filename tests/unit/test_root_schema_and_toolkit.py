"""Read-only ROOT schema inspection, draft contracts, and the authored-code toolkit."""
import json
import math
import os

import awkward as ak
import numpy as np
import pytest
import uproot

from columnar_fixtures import random_events, write_delphes
from ravel import toolkit
from ravel.physics import root_schema
from ravel.physics.columnar import formats


def _ntuple(path, *, mass=True, weights=(1.0, 2.0, 0.5)):
    n = len(weights)
    counts = [2, 0, 1][:n]
    total = sum(counts)
    data = {'el_pt': ak.unflatten(np.linspace(20e3, 60e3, total), counts),
            'el_eta': ak.unflatten(np.zeros(total), counts),
            'el_phi': ak.unflatten(np.zeros(total), counts),
            'met_met': np.array([30e3, 40e3, 50e3][:n]), 'met_phi': np.zeros(n),
            'weight_mc': np.array(weights), 'weight_pileup': np.ones(n)}
    if mass:
        data['el_m'] = ak.unflatten(np.full(total, 511.0), counts)
    with uproot.recreate(path) as f:
        f['analysis'] = data
    return path


def _snapshot(directory):
    return sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in directory.iterdir())


def test_inspection_reads_types_ranges_and_weights_and_writes_nothing(tmp_path):
    path = _ntuple(tmp_path / 'ntuple.root')
    before = _snapshot(tmp_path)
    report = root_schema.inspect(path, max_entries=2)
    assert _snapshot(tmp_path) == before and report['writes'] == 'none'
    tree = report['trees'][0]
    assert tree['name'] == 'analysis' and tree['entries'] == 3 and tree['entries_read'] == 2
    branches = {b['name']: b for b in tree['branches']}
    assert branches['el_pt']['jagged'] and branches['el_pt']['length'] == {'min': 0, 'max': 2}
    assert not branches['met_met']['jagged'] and branches['met_met']['range'] == [30e3, 40e3]
    assert branches['weight_mc']['weight'] == {'sum': 3.0, 'sum_of_squares': 5.0, 'negative_fraction': 0.0}
    assert branches['met_phi']['zero_fraction'] == 1.0 and branches['el_pt']['finite_fraction'] == 1.0


def test_draft_contract_is_a_valid_descriptor_once_reviewed(tmp_path):
    path = _ntuple(tmp_path / 'ntuple.root')
    draft = root_schema.draft_contract(root_schema.inspect(path))
    assert draft['status'] == 'draft_requires_review'
    contract = draft['branch_contract']
    assert contract['collections']['el']['fields'] == {'pt': 'el_pt', 'eta': 'el_eta', 'phi': 'el_phi', 'mass': 'el_m'}
    assert contract['met'] == {'magnitude': 'met_met', 'phi': 'met_phi'}
    assert any('MeV' in u for u in draft['unresolved'])
    assert any('several weight branches' in u for u in draft['unresolved'])
    assert draft['weight_contract']['sums_cover_all_entries'] is True
    descriptor = formats.Descriptor(contract)
    assert descriptor.check_file(path)['entries'] == 3


def test_draft_names_what_it_cannot_decide(tmp_path):
    path = _ntuple(tmp_path / 'ntuple.root', mass=False, weights=(0.0, 0.0, 0.0))
    draft = root_schema.draft_contract(root_schema.inspect(path))
    text = ' '.join(draft['unresolved'])
    assert "collection 'el': no mass branch" in text and 'every value read is zero' in text
    assert 'mass' not in draft['branch_contract']['collections']['el']['fields']


def test_delphes_trees_and_command_line(tmp_path, capsys):
    from ravel import cli
    path = write_delphes(tmp_path / 'delphes.root', random_events(5))
    report = root_schema.inspect(path)
    names = {b['name'] for b in report['trees'][0]['branches']}
    assert 'Electron.PT' in names and report['trees'][0]['name'] == 'Delphes'
    assert cli.main(['root-schema', '--input', str(_ntuple(tmp_path / 'n.root')), '--draft']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['draft']['branch_contract']['tree'] == 'analysis'


def test_toolkit_kinematics_selection_normalisation_and_significance():
    pt = ak.Array([[50.0, 50.0], [30.0]])
    eta = ak.Array([[0.0, 0.0], [0.0]])
    phi = ak.Array([[0.0, math.pi], [0.0]])
    mass = ak.Array([[0.0, 0.0], [0.0]])
    np.testing.assert_allclose(toolkit.invariant_mass(pt, eta, phi, mass), [100.0, 0.0], atol=1e-9)
    keep = toolkit.overlap_mask(eta, phi, ak.Array([[0.05], []]), ak.Array([[0.0], []]), 0.1)
    assert keep.tolist() == [[False, True], [True]]
    assert toolkit.leading(ak.zip({'pt': ak.Array([[1.0, 3.0, 2.0]])}), 2).pt.tolist() == [[3.0, 2.0]]
    scale = toolkit.event_scale(cross_section_pb=2.0, cross_section_source='declared', luminosity_ifb=10.0,
                                luminosity_source='declared', sum_of_weights=4.0)
    assert scale['scale'] == pytest.approx(5000.0)
    with pytest.raises(ValueError, match='source'):
        toolkit.event_scale(cross_section_pb=1.0, cross_section_source='', luminosity_ifb=1.0,
                            luminosity_source='x', sum_of_weights=1.0)
    # Large background: Z_A approaches s / sqrt(b).
    assert toolkit.asimov_significance(10.0, 1e6) == pytest.approx(10.0 / 1e3, rel=1e-3)
    exact = math.sqrt(2 * ((5 + 2) * math.log(1 + 5 / 2) - 5))
    assert toolkit.asimov_significance(5.0, 2.0) == pytest.approx(exact)
    assert toolkit.asimov_significance(5.0, 2.0, 1e-6) == pytest.approx(exact, rel=1e-6)
    assert toolkit.asimov_significance(5.0, 2.0, 1.0) < exact
    assert set(toolkit.FUNCTIONS) <= set(dir(toolkit))


def _multipart_ntuple(path, suffix):
    data = {}
    # Nested complete prefixes must retain distinct collections; incomplete ones remain fields.
    for prefix, mass_field in [('obj', 'e'), ('obj_truth', 'e'), ('obj_large', 'm')]:
        for field, value in {'pt': 50., 'eta': 0., 'phi': 1., mass_field: 60.,
                             'select_loose': 1, 'effsf_id_up': .98, 'trigmatched_chain_a': 1}.items():
            data[f'{prefix}_{field}{suffix}'] = ak.Array([[value], []])
    data[f'met_met{suffix}'] = np.array([30., 0.])
    data[f'met_phi{suffix}'] = np.array([0., 1.])
    with uproot.recreate(path) as root:
        root.mktree('events', {name: value.type if isinstance(value, ak.Array) else value.dtype
                              for name, value in data.items()})
        root['events'].extend(data)
    return path


@pytest.mark.parametrize('suffix', ['_NOSYS', '_NOMINAL', ''])
def test_draft_keeps_multipart_fields_and_proposes_energy_mass(tmp_path, suffix):
    path = _multipart_ntuple(tmp_path / 'multipart.root', suffix)
    report = root_schema.inspect(path)
    draft = root_schema.draft_contract(report, nominal_suffix=suffix)
    collections = draft['branch_contract']['collections']
    assert set(collections) == {'obj', 'obj_truth', 'obj_large'}
    for prefix, collection in collections.items():
        fields = collection['fields']
        for key in ('pt', 'eta', 'phi', 'select_loose', 'effsf_id_up', 'trigmatched_chain_a'):
            assert fields[key] == f'{prefix}_{key}{suffix}'
        if prefix == 'obj_large':
            assert fields['mass'] == f'{prefix}_m{suffix}'
        else:
            assert fields['energy'] == f'{prefix}_e{suffix}'
            assert fields['mass'] == {'from_energy': f'{prefix}_e{suffix}'}
            assert any(prefix in choice and 'from_energy' in choice and 'confirm' in choice
                       for choice in draft['unresolved'])
    descriptor = formats.Descriptor(draft['branch_contract'])
    assert descriptor.check_file(path)['entries'] == 2
    chunk = next(descriptor.read(path, collections=list(collections), event_fields=[], step=2))
    view = descriptor.view(chunk)
    assert view.collections['obj_truth'].mass[0, 0] == pytest.approx(math.sqrt(60 ** 2 - 50 ** 2))
    assert view.collections['obj_large'].mass[0, 0] == 60.


def test_nominal_suffix_cli_parameter(tmp_path, capsys):
    path = _multipart_ntuple(tmp_path / 'multipart.root', '_NOMINAL')
    assert root_schema.main(['--input', str(path), '--draft', '--nominal-suffix', '_NOMINAL']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['draft']['branch_contract']['collections']['obj']['fields']['pt'] == 'obj_pt_NOMINAL'


@pytest.mark.parametrize('suffix', [None, 42])
def test_nominal_suffix_must_be_text(suffix):
    with pytest.raises(ValueError, match='nominal_suffix'):
        root_schema.draft_contract({'trees': []}, nominal_suffix=suffix)


def test_draft_preserves_dotted_and_mixed_prefixes_and_colliding_fields(tmp_path):
    path = tmp_path / 'dotted.root'
    data = {}
    for prefix, separator in [('Objects', '.'), ('truth.Objects', '_')]:
        for key in ('pt', 'eta', 'phi', 'm', 'mass', 'select_loose', 'effsf_id_up', 'trigmatched_chain'):
            data[f'{prefix}{separator}{key}'] = ak.Array([[1.], []])
    with uproot.recreate(path) as root:
        root.mktree('events', {name: value.type for name, value in data.items()})
        root['events'].extend(data)
    draft = root_schema.draft_contract(root_schema.inspect(path))
    collections = draft['branch_contract']['collections']
    assert set(collections) == {'objects', 'truth_objects'}
    assert {branch for collection in collections.values() for branch in collection['fields'].values()} == set(data)
    assert any('colliding field names' in choice for choice in draft['unresolved'])
    formats.Descriptor(draft['branch_contract']).check_file(path)
