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
