"""Simplified-model SLHA builder, round trip and decay-closure validator."""
import hashlib
import json

import pytest

from ravel.physics import simplified_spectrum as ss

SM = {'24': 80.4, '23': 91.19, '25': 125.0, '6': 172.5, '5': 4.7, '15': 1.777}


def spec(**changes):
    document = {
        'schema_version': 1,
        'basis': 'generic-SLHA',
        'modsel': {'1': 1},
        'sm_masses_GeV': SM,
        'masses': {'1000022': 100.0, '1000023': 300.0, '1000024': 300.0},
        'decoupled': {'mass_GeV': 5000.0, 'pdgs': [1000021, 1000006]},
        'mixing': {'NMIX': 'identity', 'UMIX': 'identity', 'VMIX': 'identity'},
        'decays': {
            '1000024': {'width_GeV': 0.1, 'channels': [{'br': 1.0, 'daughters': [1000022, 24]}]},
            '1000023': {'width_GeV': 0.1, 'channels': [{'br': 0.5, 'daughters': [1000022, 23]},
                                                       {'br': 0.5, 'daughters': [1000022, 25]}]},
        },
        'invisible': [1000022],
        'produced': [1000024, 1000023],
        'source': 'Synthetic wino-bino simplified model for tests',
    }
    document.update(changes)
    return document


def codes(report):
    return {f['code'] for f in report['findings'] if f['severity'] == 'error'}


def test_build_writes_masses_mixing_decays_and_modsel():
    card = ss.build(spec())
    doc = ss.parse_slha(card)
    assert doc['blocks']['MODSEL']['entries'][(1,)] == 1
    assert doc['blocks']['MASS']['entries'][(1000022,)] == 100.0
    assert doc['blocks']['MASS']['entries'][(1000021,)] == 5000.0
    assert doc['blocks']['NMIX']['entries'][(1, 1)] == 1.0 and doc['blocks']['NMIX']['entries'][(1, 2)] == 0.0
    assert doc['decays'][1000024]['width'] == 0.1
    assert doc['decays'][1000024]['channels'] == [(1.0, (1000022, 24))]
    assert doc['decays'][1000021]['width'] == 0.0
    report = ss.check_card(doc, invisible=[1000022], produced=[1000024, 1000023], sm_masses=SM)
    assert report['passed'], report['findings']
    assert report['invisible_census'] == [1000022]


def test_slha_round_trip_is_stable():
    first = ss.parse_slha(ss.build(spec()))
    again = ss.parse_slha(ss.write_slha(first))
    assert again == first


def test_partial_widths_define_total_and_branching_fractions():
    s = spec()
    s['decays']['1000023'] = {'channels': [{'partial_width_GeV': 0.03, 'daughters': [1000022, 23]},
                                           {'partial_width_GeV': 0.01, 'daughters': [1000022, 25]}]}
    doc = ss.parse_slha(ss.build(s))
    assert doc['decays'][1000023]['width'] == pytest.approx(0.04)
    assert [c[0] for c in doc['decays'][1000023]['channels']] == pytest.approx([0.75, 0.25])


def test_three_body_rows_are_accepted():
    s = spec()
    s['masses']['1000023'] = 150.0
    s['decays']['1000023'] = {'width_GeV': 1e-4, 'channels': [{'br': 0.6, 'daughters': [1000022, 11, -11]},
                                                               {'br': 0.4, 'daughters': [1000022, 1, -1]}]}
    report = ss.check_card(ss.parse_slha(ss.build(s)), invisible=[1000022], produced=[1000023], sm_masses=SM)
    assert report['passed'], report['findings']


def test_width_only_table_fails():
    doc = ss.parse_slha(ss.build(spec()))
    doc['decays'][1000024]['channels'] = []
    assert 'width_only' in codes(ss.check_card(doc, invisible=[1000022], produced=[1000024], sm_masses=SM))


def test_branching_sum_not_one_fails():
    s = spec()
    s['decays']['1000023']['channels'][0]['br'] = 0.4
    with pytest.raises(ValueError, match='sum'):
        ss.build(s)
    doc = ss.parse_slha(ss.build(spec()))
    doc['decays'][1000023]['channels'][0] = (0.4, (1000022, 23))
    assert 'branching_sum' in codes(ss.check_card(doc, invisible=[1000022], produced=[1000023], sm_masses=SM))


def test_closed_channel_fails():
    s = spec()
    s['masses']['1000024'] = 150.0
    report = ss.check_card(ss.parse_slha(ss.build(s, check=False)), invisible=[1000022], produced=[1000024], sm_masses=SM)
    assert 'closed_channel' in codes(report)


def test_undeclared_stable_daughter_fails():
    report = ss.check_card(ss.parse_slha(ss.build(spec())), invisible=[], produced=[1000024], sm_masses=SM)
    assert 'undeclared_stable' in codes(report)
    s = spec()
    s['decays']['1000024']['channels'] = [{'br': 1.0, 'daughters': [1000039, 24]}]
    s['masses']['1000039'] = 1e-9
    report = ss.check_card(ss.parse_slha(ss.build(s, check=False)), invisible=[1000022], produced=[1000024], sm_masses=SM)
    assert 'undeclared_stable' in codes(report)
    report = ss.check_card(ss.parse_slha(ss.build(s, check=False)), invisible=[1000022, 1000039], produced=[1000024], sm_masses=SM)
    assert report['passed'] and 1000039 in report['invisible_census']


def test_missing_modsel_fails():
    doc = ss.parse_slha(ss.build(spec()))
    del doc['blocks']['MODSEL']
    assert 'modsel_missing' in codes(ss.check_card(doc, invisible=[1000022], produced=[1000024], sm_masses=SM))


def test_declared_invisible_with_width_fails():
    s = spec()
    s['decays']['1000022'] = {'width_GeV': 1.0, 'channels': [{'br': 1.0, 'daughters': [22, 12]}]}
    report = ss.check_card(ss.parse_slha(ss.build(s, check=False)), invisible=[1000022], produced=[1000024], sm_masses=SM)
    assert 'invisible_decays' in codes(report)


def test_unknown_sm_mass_is_reported_not_guessed():
    report = ss.check_card(ss.parse_slha(ss.build(spec())), invisible=[1000022], produced=[1000024], sm_masses={})
    assert 'mass_unknown' in codes(report)


def test_base_card_is_preserved_and_overridden(tmp_path):
    base = tmp_path / 'base.slha'
    base.write_text('BLOCK SMINPUTS\n  1 1.279340e+02 # aEWM1\nBLOCK MASS\n  24 8.04e+01\n  1000022 5.0e+01\n'
                    'DECAY 1000022 0.0\n')
    s = spec(base_card={'path': str(base), 'sha256': hashlib.sha256(base.read_bytes()).hexdigest()})
    doc = ss.parse_slha(ss.build(s, base_dir=tmp_path))
    assert doc['blocks']['SMINPUTS']['entries'][(1,)] == pytest.approx(127.934)
    assert doc['blocks']['MASS']['entries'][(1000022,)] == 100.0
    assert doc['blocks']['MASS']['entries'][(24,)] == pytest.approx(80.4)


def test_compare_banner_detects_decay_drift(tmp_path):
    card = ss.build(spec())
    lhe = tmp_path / 'events.lhe'
    lhe.write_text('<LesHouchesEvents version="3.0">\n<header>\n<slha>\n' + card + '</slha>\n</header>\n</LesHouchesEvents>\n')
    assert ss.compare_banner(lhe.read_text(), ss.parse_slha(card))['passed']
    drifted = card.replace('DECAY   1000024   1.000000e-01', 'DECAY   1000024   2.000000e-01')
    assert drifted != card
    lhe.write_text('<LesHouchesEvents version="3.0">\n<header>\n<slha>\n' + drifted + '</slha>\n</header>\n</LesHouchesEvents>\n')
    report = ss.compare_banner(lhe.read_text(), ss.parse_slha(card))
    assert not report['passed'] and report['differences'][0]['pdg'] == 1000024


def test_adapter_run_writes_card_and_report(tmp_path):
    request = tmp_path / 'spectrum.json'
    request.write_text(json.dumps(spec()))
    task = {'request': str(request)}
    assert ss.validate(task) == task
    assert request.resolve() in ss.inputs(task, tmp_path)
    result = ss.run(task, tmp_path, tmp_path / 'out')
    assert result['status'] == 'passed' and result['physics_validated'] is False
    assert (tmp_path / 'out/simplified-spectrum.slha').read_text() == ss.build(spec())
    with pytest.raises(FileExistsError):
        ss.run(task, tmp_path, tmp_path / 'out')
