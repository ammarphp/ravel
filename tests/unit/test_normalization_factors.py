"""Branching and filter factors derived from declared decay settings."""
import hashlib
import json

import pytest

from ravel.physics import native_normalization as norm

# Synthetic Z table used only as a test fixture; real runs pin a cited table.
Z_TABLE = {'source': 'synthetic fixture', 'complete': True, 'channels': [
    {'daughters': [11, -11], 'br': 0.034}, {'daughters': [13, -13], 'br': 0.034},
    {'daughters': [15, -15], 'br': 0.034}, {'daughters': [12, -12], 'br': 0.2},
    {'daughters': [1, -1], 'br': 0.698}]}


def settings(**changes):
    document = {'schema_version': 1, 'produced': [23, 23], 'decay_tables': {'23': Z_TABLE},
                'pythia': ['23:onMode = off', '23:onIfAny = 11 13'], 'sigma_includes_decays': False,
                'filters': [], 'sigma_after_filter': False}
    document.update(changes)
    return document


def test_forced_z_to_light_leptons_gives_product_of_branching_fractions():
    record = norm.decay_factors(settings())
    assert record['branching_factor'] == pytest.approx(0.068 ** 2)
    assert record['total_factor'] == pytest.approx(0.068 ** 2)
    assert record['per_particle'][0]['open_channels'] == [[-11, 11], [-13, 13]]


def test_command_order_matters_like_pythia():
    reversed_order = norm.decay_factors(settings(pythia=['23:onIfAny = 11 13', '23:onMode = off']))
    assert reversed_order['branching_factor'] == 0.0 and reversed_order['status'] == 'no_open_channels'


def test_all_match_and_off_variants():
    record = norm.decay_factors(settings(produced=[23], pythia=['23:offIfAny = 1 12']))
    assert record['branching_factor'] == pytest.approx(0.102)
    record = norm.decay_factors(settings(produced=[23], pythia=['23:onMode = off', '23:onIfMatch = 15 15']))
    assert record['branching_factor'] == pytest.approx(0.034)


def test_particle_antiparticle_modes():
    table = {'source': 'synthetic', 'complete': True, 'channels': [
        {'daughters': [-11, 12], 'br': 0.1}, {'daughters': [1, -2], 'br': 0.9}]}
    record = norm.decay_factors(settings(produced=[24, -24], decay_tables={'24': table},
                                         pythia=['24:onMode = off', '24:onPosIfAny = 11']))
    assert record['branching_factor'] == pytest.approx(0.1 * 0.0)
    record = norm.decay_factors(settings(produced=[24, -24], decay_tables={'24': table},
                                         pythia=['24:onMode = off', '24:onIfAny = 11']))
    assert record['branching_factor'] == pytest.approx(0.01)


def test_one_channel_uses_the_physical_table():
    record = norm.decay_factors(settings(produced=[23], pythia=['23:oneChannel = 1 1.0 0 13 -13']))
    assert record['branching_factor'] == pytest.approx(0.034)
    with pytest.raises(ValueError, match='physical'):
        norm.decay_factors(settings(produced=[23], pythia=['23:oneChannel = 1 1.0 0 22 22']))


def test_slha_decay_table_source(tmp_path):
    card = tmp_path / 'card.slha'
    card.write_text('BLOCK MODSEL\n 1 1\nDECAY 1000023 1.0\n 0.25 2 1000022 23\n 0.75 2 1000022 25\n')
    pin = {'path': str(card), 'sha256': hashlib.sha256(card.read_bytes()).hexdigest()}
    record = norm.decay_factors({'schema_version': 1, 'produced': [1000023], 'slha': pin, 'decay_tables': {},
                                 'pythia': ['1000023:onMode = off', '1000023:onIfAny = 23'],
                                 'sigma_includes_decays': False, 'filters': [], 'sigma_after_filter': False},
                                base_dir=tmp_path)
    assert record['branching_factor'] == pytest.approx(0.25)
    assert record['sources'][0]['sha256'] == pin['sha256']


def test_double_counting_is_refused():
    with pytest.raises(ValueError, match='double'):
        norm.decay_factors(settings(sigma_includes_decays=True))
    with pytest.raises(ValueError, match='double'):
        norm.decay_factors(settings(madspin={'decays': ['decay z > l+ l-'], 'cross_section_includes_branching': True}))
    with pytest.raises(ValueError, match='double'):
        norm.decay_factors(settings(pythia=[], filters=[{'name': 'lepton filter', 'n_pass': 5, 'n_total': 10,
                                                          'source': 'generator log'}], sigma_after_filter=True))


def test_madspin_decays_without_rescaling_use_the_declared_table():
    record = norm.decay_factors(settings(pythia=[], madspin={'decays': ['decay z > l+ l-'],
                                                             'cross_section_includes_branching': False}))
    assert record['branching_factor'] == pytest.approx(0.068 ** 2)
    included = norm.decay_factors(settings(pythia=[], produced=[23],
                                           madspin={'decays': ['decay z > l+ l-'], 'cross_section_includes_branching': True}))
    assert included['branching_factor'] == 1.0 and included['per_particle'][0]['already_in_cross_section']


def test_filter_efficiency_from_counts_and_declared_source():
    record = norm.decay_factors(settings(pythia=[], produced=[], filters=[
        {'name': 'two-lepton filter', 'n_pass': 250, 'n_total': 1000, 'source': 'generator log'}]))
    assert record['filter_factor'] == pytest.approx(0.25)
    with pytest.raises(ValueError, match='source'):
        norm.decay_factors(settings(pythia=[], produced=[], filters=[{'name': 'x', 'efficiency': 0.3}]))


def test_incomplete_table_is_refused():
    table = dict(Z_TABLE, complete=False)
    with pytest.raises(ValueError, match='complete'):
        norm.decay_factors(settings(decay_tables={'23': table}))


def test_unknown_pythia_command_is_refused():
    with pytest.raises(ValueError, match='supported'):
        norm.decay_factors(settings(pythia=['23:mayDecay = off', '23:rescaleBR = 0.5']))


def test_frequency_closure_passes_and_fails():
    record = norm.decay_factors(settings(produced=[23]))
    good = norm.decay_frequency_closure(record, {'23': {'11 -11': 503, '13 -13': 497}}, z_max=5)
    assert good['passed']
    bad = norm.decay_frequency_closure(record, {'23': {'11 -11': 900, '13 -13': 100}}, z_max=5)
    assert not bad['passed']
    closed = norm.decay_frequency_closure(record, {'23': {'11 -11': 500, '13 -13': 480, '15 -15': 20}}, z_max=5)
    assert not closed['passed'] and closed['particles'][0]['closed_channels_observed']


def test_combined_cross_section_applies_each_factor_once(tmp_path):
    record = norm.decay_factors(settings())
    combined = norm.combine_cross_section({'status': 'resolved', 'applied_cross_section_pb': 2.0,
                                           'luminosity_applied': False}, record)
    assert combined['cross_section_times_factors_pb'] == pytest.approx(2.0 * 0.068 ** 2)
    with pytest.raises(ValueError, match='once'):
        norm.combine_cross_section(dict(combined), record)


def test_cli_factors(tmp_path, capsys):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(settings()))
    assert norm.main(['factors', '--settings', str(path), '--out', str(tmp_path / 'factors.json')]) == 0
    assert json.loads((tmp_path / 'factors.json').read_text())['branching_factor'] == pytest.approx(0.068 ** 2)
