"""Delphes card parsing, the invisible-state gate, derived and skimmed cards, and the model census."""
import json
import os
from pathlib import Path

import pytest

from production_fixtures import SYNTHETIC_CARD
from ravel.physics import detector_card as dc

NATIVE_CMS = Path(os.environ.get('RAVEL_NATIVE_BUILD', '/nonexistent')) / 'tools/delphes/cards/delphes_card_CMS.tcl'


@pytest.fixture
def card(tmp_path):
    path = tmp_path / 'card.tcl'
    path.write_text(SYNTHETIC_CARD)
    return path


def test_parse_reads_execution_path_modules_and_fractions(card):
    parsed = dc.parse_card(card)
    assert parsed.execution_path[0] == 'ParticlePropagator' and parsed.execution_path[-1] == 'TreeWriter'
    assert parsed.modules['HCal'].cls == 'SimpleCalorimeter'
    assert dc.effective_fraction(parsed.modules['HCal'], 1000039)[:2] == ((1.0,), 'default {0} entry')
    assert dc.effective_fraction(parsed.modules['HCal'], -1000022)[:2] == ((0.0,), 'explicit')
    assert dc.tree_branches(parsed) == ['Particle', 'Jet', 'GenJet', 'MissingET', 'Photon']


def test_declared_neutralino_is_consistent(card):
    assert dc.gate(card, {'invisible': [1000022]})['consistent']


def test_gravitino_with_stock_card_is_refused(card):
    report = dc.gate(card, {'invisible': [1000039]})
    codes = {(f['code'], f['module']) for f in report['findings']}
    assert not report['consistent']
    assert ('calorimeter_deposit', 'HCal') in codes
    assert ('generator_level_includes_invisible', 'GenJetFinder') in codes
    assert ('generator_level_includes_invisible', 'GenMissingET') in codes
    assert ('calorimeter_deposit', 'ECal') not in codes          # {0} default is zero in ECal
    assert not any(f['module'] in ('MissingET', 'FastJetFinder') for f in report['findings'])


def test_derived_card_passes_and_its_diff_holds_only_declared_lines(card, tmp_path):
    record = dc.derive_card(card, tmp_path / 'derived.tcl', invisible=[1000039, 1000022])
    assert record['consistent'] and dc.gate(tmp_path / 'derived.tcl', {'invisible': [1000039]})['consistent']
    added, removed = dc.diff_lines(record['diff'])
    assert removed == []
    content = [l.strip() for l in added if not l.startswith('#')]
    assert sorted(content) == sorted(['add EnergyFraction {1000039} {0.0}', 'add PdgCode {1000039}', 'add PdgCode {-1000039}'])
    assert dc.undeclared_changes(record) == []
    assert all(e['reason'] for e in record['edits'])
    assert record['source_card']['sha256'] == dc.sha256(card)


def test_calorimeter_class_with_two_fractions_uses_its_built_in_default(tmp_path):
    text = SYNTHETIC_CARD.replace('module SimpleCalorimeter HCal {', 'module Calorimeter HCal {') \
        .replace('add EnergyFraction {0} {1.0}', '').replace('add EnergyFraction {11} {0.0}', 'add EnergyFraction {11} {1.0 0.0}') \
        .replace('add EnergyFraction {22} {0.0}', 'add EnergyFraction {22} {1.0 0.0}') \
        .replace('add EnergyFraction {12} {0.0}\n  add EnergyFraction {1000022} {0.0}\n}', 'add EnergyFraction {12} {0.0 0.0}\n}')
    path = tmp_path / 'calo.tcl'
    path.write_text(text)
    report = dc.gate(path, {'invisible': [1000022]})
    deposit = [f for f in report['findings'] if f['code'] == 'calorimeter_deposit']
    assert deposit and deposit[0]['fractions'] == [0.0, 1.0] and deposit[0]['origin'] == 'Delphes built-in default'
    record = dc.derive_card(path, tmp_path / 'calo-derived.tcl', invisible=[1000022])
    assert record['consistent'] and any('{0.0 0.0}' in e['text'] for e in record['edits'])


def test_skimmed_card_differs_only_in_the_tree_writer(card, tmp_path):
    record = dc.derive_card(card, tmp_path / 'skim.tcl', keep_branches=['Jet', 'MissingET'])
    assert {e['module'] for e in record['edits']} == {'TreeWriter'}
    assert dc.tree_branches(dc.parse_card(tmp_path / 'skim.tcl')) == ['Jet', 'MissingET']
    with pytest.raises(ValueError, match='not written by the card'):
        dc.derive_card(card, tmp_path / 'skim2.tcl', keep_branches=['Jet', 'Tower'])


def test_declared_override_is_recorded(card, tmp_path):
    record = dc.derive_card(card, tmp_path / 'o.tcl', overrides=[
        {'module': 'PhotonEfficiency', 'set': 'EfficiencyFormula', 'value': '{1.0}',
         'reason': 'photon efficiency applied later from a published map'}])
    assert [e['text'].strip() for e in record['edits']] == ['set EfficiencyFormula {1.0}']
    assert dc.parse_card(tmp_path / 'o.tcl').modules['PhotonEfficiency'].sets('EfficiencyFormula') == '1.0'
    with pytest.raises(ValueError, match='unknown module'):
        dc.derive_card(card, tmp_path / 'p.tcl', overrides=[{'module': 'Nope', 'set': 'X', 'value': '1', 'reason': 'r'}])


def test_sourced_files_are_followed_and_pinned(tmp_path):
    (tmp_path / 'parts').mkdir()
    (tmp_path / 'parts/neutrinos.tcl').write_text('  add PdgCode {14}\n  add PdgCode {-14}\n')
    text = SYNTHETIC_CARD.replace('  add PdgCode {12}\n', '  source parts/neutrinos.tcl\n  add PdgCode {12}\n')
    path = tmp_path / 'main.tcl'
    path.write_text(text)
    parsed = dc.parse_card(path)
    assert 14 in dc.filter_codes(parsed.modules['NeutrinoFilter'])[0]
    record = dc.derive_card(path, tmp_path / 'out.tcl', invisible=[1000022])
    assert any(e['text'].strip() == f'source {(tmp_path / "parts/neutrinos.tcl").resolve()}' for e in record['edits'])
    (tmp_path / 'other.tcl').write_text(text.replace('parts/neutrinos.tcl', 'missing.tcl'))
    with pytest.raises(ValueError, match='not found'):
        dc.parse_card(tmp_path / 'other.tcl')


def _slha(tmp_path, gravitino_width=0.0):
    text = f"""BLOCK MODSEL
    1 1
BLOCK MASS
  1000022 1.0e+02
  1000023 2.0e+02
  1000039 1.0e-09
DECAY 1000023 1.0e-01
  1.0 2 1000022 22
DECAY 1000022 1.0e-03
  1.0 2 1000039 22
DECAY 1000039 {gravitino_width}
"""
    path = tmp_path / 'spectrum.slha'
    path.write_text(text)
    return path


def test_census_refuses_an_undeclared_stable_state_and_a_decaying_invisible(tmp_path):
    slha = _slha(tmp_path)
    with pytest.raises(ValueError, match='neither declared invisible nor declared visible: 1000039'):
        dc.invisible_census({'invisible': [1000022], 'slha': 'spectrum.slha', 'produced': [1000023]}, tmp_path)
    with pytest.raises(ValueError, match='declared invisible state 1000022 decays'):
        dc.invisible_census({'invisible': [1000022, 1000039], 'slha': 'spectrum.slha', 'produced': [1000023]}, tmp_path)
    census = dc.invisible_census({'invisible': [1000039], 'slha': 'spectrum.slha', 'produced': [1000023]}, tmp_path)
    assert census['invisible'] == [1000039] and census['evidence']['slha']['stable_bsm'] == [1000039]
    with pytest.raises(ValueError, match='both invisible and visible'):
        dc.invisible_census({'invisible': [1000039], 'visible_stable': [1000039]})


def test_census_reads_a_decay_closure_report(tmp_path):
    (tmp_path / 'closure.json').write_text(json.dumps({'closure': {'passed': True, 'invisible_census': [1000039],
                                                                    'stable_census': [1000039]}}))
    with pytest.raises(ValueError, match='not declared: 1000039'):
        dc.invisible_census({'invisible': [], 'closure_report': 'closure.json'}, tmp_path)
    assert dc.invisible_census({'invisible': [1000039], 'closure_report': 'closure.json'}, tmp_path)['invisible'] == [1000039]


def test_hepmc_census_lists_stable_bsm_states(tmp_path):
    path = tmp_path / 'e.hepmc'
    path.write_text('HepMC::Asciiv3-START_EVENT_LISTING\nE 0 1 3\nP 1 0 2212 0 0 1 1 0.9 4\nP 2 1 1000039 0 0 1 1 0 1\n'
                    'P 3 1 1000022 0 0 1 1 0 2\nP 4 1 11 0 0 1 1 0 1\nHepMC::Asciiv3-END_EVENT_LISTING\n')
    assert dc.hepmc_census(path) == {'events_read': 1, 'stable_bsm': {'1000039': 1}}
    assert dc.is_bsm(1000022) and dc.is_bsm(52) and not dc.is_bsm(211) and not dc.is_bsm(22)


def test_command_line_check_and_derive(card, tmp_path, capsys):
    assert dc.main(['check', str(card), '--invisible', '1000039']) == 1
    assert dc.main(['derive', str(card), '--invisible', '1000039', '--output', str(tmp_path / 'd.tcl'),
                    '--record', str(tmp_path / 'd.json')]) == 0
    assert json.loads((tmp_path / 'd.json').read_text())['consistent']
    assert dc.main(['check', str(tmp_path / 'd.tcl'), '--invisible', '1000039']) == 0


@pytest.mark.skipif(not NATIVE_CMS.is_file(), reason='installed Delphes cards not present')
def test_installed_cms_card_omits_the_gravitino_and_the_derived_copy_fixes_it(tmp_path):
    report = dc.gate(NATIVE_CMS, {'invisible': [1000039]})
    assert not report['consistent'] and any(f['module'] == 'HCal' for f in report['findings'])
    record = dc.derive_card(NATIVE_CMS, tmp_path / 'cms.tcl', invisible=[1000039, 1000022])
    assert record['consistent'] and dc.undeclared_changes(record) == []
