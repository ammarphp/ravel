"""Output contracts and the toolchain execution gate."""
import json

import pytest

from columnar_fixtures import random_events, write_delphes
from production_fixtures import write_empty_delphes, write_lhe
from ravel.validation import output_postconditions as oc
from ravel.workflow import output_gate as gate


def delphes(tmp_path, name='events.root', n=20, weight=None):
    if n == 0:
        return write_empty_delphes(tmp_path / name)
    events = random_events(n, seed=3)
    if weight is not None:
        for ev in events:
            ev['Weight'] = weight
    return write_delphes(tmp_path / name, events)


def contract(path, **extra):
    return {'name': 'detector events', 'kind': 'delphes-root', 'path': str(path), 'min_events': 1,
            'required': ['Jet.PT', 'MissingET.MET'], **extra}


def codes(result):
    return {f['code'] for f in result['failures']}


def test_complete_delphes_file_passes_with_weight_sums(tmp_path):
    result = oc.check(contract(delphes(tmp_path), expected_events=20, forbid_constant=['MissingET.MET']))
    assert result['passed'], result['failures']
    assert result['observed']['entries'] == 20 and result['observed']['sum_weights'] > 0


def test_zero_entry_tree_all_zero_weights_and_missing_branches_fail(tmp_path):
    assert {'empty_tree', 'too_few_events'} <= codes(oc.check(contract(delphes(tmp_path, 'empty.root', n=0))))
    assert 'all_zero_weights' in codes(oc.check(contract(delphes(tmp_path, 'zero.root', weight=0.0))))
    assert 'missing_branches' in codes(oc.check(contract(delphes(tmp_path), required=['Tower.ET'])))
    assert 'event_count_mismatch' in codes(oc.check(contract(delphes(tmp_path, 'a.root'), expected_events=21)))
    assert 'missing_output' in codes(oc.check(contract(tmp_path / 'absent.root')))
    assert 'constant_values' in codes(oc.check(contract(delphes(tmp_path, 'c.root', weight=1.0), forbid_constant=['Event.Weight'])))


def test_near_copy_of_a_reference_fails(tmp_path):
    reference = delphes(tmp_path, 'reference.root')
    copy = delphes(tmp_path, 'copy.root')
    result = oc.check(contract(copy, reference={'path': str(reference)}))
    assert 'near_copy_of_reference' in codes(result)
    other = write_delphes(tmp_path / 'other.root', random_events(20, seed=9))
    assert oc.check(contract(other, reference={'path': str(reference)}))['passed']


def test_freshness_uses_the_attempt_snapshot(tmp_path):
    old = delphes(tmp_path, 'old.root')
    new = tmp_path / 'new.root'
    snap = oc.snapshot([old, new])
    write_delphes(new, random_events(5, seed=2))
    assert 'stale_output' in codes(oc.check(contract(old), snapshot_before=snap))
    assert oc.check(contract(new), snapshot_before=snap)['passed']
    other = delphes(tmp_path, 'unlisted.root')
    assert 'not_in_snapshot' in codes(oc.check(contract(other), snapshot_before=snap))


def test_lhe_contract_delegates_to_the_existing_reader(tmp_path):
    good = write_lhe(tmp_path / 'good.lhe', n=4)
    assert oc.check({'name': 'lhe', 'kind': 'lhe', 'path': str(good), 'expected_events': 4})['passed']
    truncated = tmp_path / 'truncated.lhe'
    truncated.write_text(good.read_text().replace('</LesHouchesEvents>\n', ''))
    assert 'invalid_lhe' in codes(oc.check({'name': 'lhe', 'kind': 'lhe', 'path': str(truncated)}))
    zero = write_lhe(tmp_path / 'zero.lhe', n=3, weights=[0.0, 0.0, 0.0])
    assert 'all_zero_weights' in codes(oc.check({'name': 'lhe', 'kind': 'lhe', 'path': str(zero)}))


def test_hepmc_yoda_json_and_workspace_contracts(tmp_path):
    hepmc = tmp_path / 'e.hepmc'
    hepmc.write_text('HepMC::Version 3.02.06\nHepMC::Asciiv3-START_EVENT_LISTING\nW Weight\nE 0 1 1\nW 1.0\nE 1 1 1\nW 1.0\n')
    assert 'incomplete_listing' in codes(oc.check({'name': 'h', 'kind': 'hepmc', 'path': str(hepmc)}))
    hepmc.write_text(hepmc.read_text() + 'HepMC::Asciiv3-END_EVENT_LISTING\n')
    assert oc.check({'name': 'h', 'kind': 'hepmc', 'path': str(hepmc), 'expected_events': 2})['passed']
    yoda = tmp_path / 'r.yoda'
    yoda.write_text('BEGIN YODA_HISTO1D_V2 /A/h1\n0 1 2.0 0.1\nEND YODA_HISTO1D_V2\n')
    assert oc.check({'name': 'y', 'kind': 'yoda', 'path': str(yoda), 'required': ['/A/h1']})['passed']
    assert 'missing_objects' in codes(oc.check({'name': 'y', 'kind': 'yoda', 'path': str(yoda), 'required': ['/A/h2']}))
    doc = tmp_path / 'r.json'
    doc.write_text(json.dumps({'sigma': {'value_pb': 0.2}, 'bins': [1.0, float('nan')]}))
    assert 'missing_key' in codes(oc.check({'name': 'j', 'kind': 'json', 'path': str(doc), 'required': ['/sigma/unit']}))
    assert 'nonfinite_values' in codes(oc.check({'name': 'j', 'kind': 'json', 'path': str(doc)}))
    ws = tmp_path / 'ws.json'
    ws.write_text(json.dumps({'channels': [], 'observations': [], 'measurements': [], 'version': '1.0.0'}))
    assert 'empty_workspace' in codes(oc.check({'name': 'w', 'kind': 'pyhf-workspace', 'path': str(ws)}))
    with pytest.raises(ValueError, match='unknown output contract kind'):
        oc.check({'name': 'x', 'kind': 'csv', 'path': str(ws)})


def test_zero_cross_section_needs_three_confirmations():
    signatures = gate.markers('madgraph')['zero_cross_section']
    log = 'INFO: Cross-section :   0 +- 0 pb\n'
    assert oc.zero_cross_section_status(banner_sigma_pb=0.0, log_text=log, events_written=0, signatures=signatures)['status'] == 'confirmed'
    assert oc.zero_cross_section_status(banner_sigma_pb=0.0, log_text=log, events_written=10, signatures=signatures)['status'] == 'suspicious'
    assert oc.zero_cross_section_status(banner_sigma_pb=None, log_text='done', events_written=0, signatures=signatures)['status'] == 'suspicious'
    assert oc.zero_cross_section_status(banner_sigma_pb=1.2, log_text='', events_written=5, signatures=signatures)['status'] == 'not_zero'


def test_gate_classes(tmp_path):
    good = [contract(delphes(tmp_path))]
    assert gate.evaluate('delphes', returncode=0, contracts=good, toolchains=['delphes'])['verdict'] == 'accepted'
    assert gate.evaluate('delphes', returncode=1, contracts=good, toolchains=['delphes'])['failure_class'] == 'tool_failed'
    marked = gate.evaluate('delphes', returncode=0, log_text='** ERROR: cannot find module X\n', contracts=good,
                           toolchains=['delphes'])
    assert marked['failure_class'] == 'hard_error_marker' and marked['markers']['hard_errors'][0]['line'].startswith('** ERROR')
    blocked = gate.evaluate('shower', returncode=134, log_text='dyld[123]: Library not loaded: libHepMC3.dylib\n',
                            toolchains=['pythia'])
    assert blocked['failure_class'] == 'environment_blocked'
    empty = [contract(delphes(tmp_path, 'empty.root', n=0))]
    assert gate.evaluate('delphes', returncode=0, contracts=empty)['failure_class'] == 'contract_failed'
    warned = gate.evaluate('madgraph', returncode=0, log_text='WARNING: the fit failed for one channel\n', toolchains=['madgraph'])
    assert warned['verdict'] == 'accepted' and warned['markers']['warnings']


def test_downstream_requires_an_accepted_unchanged_upstream(tmp_path):
    path = delphes(tmp_path)
    verdict = gate.evaluate('detector', returncode=0, contracts=[contract(path)])
    gate.record(tmp_path / 'gate', verdict)
    assert gate.require_accepted(tmp_path / 'gate', ['detector'])
    with pytest.raises(ValueError, match='no gate verdict'):
        gate.require_accepted(tmp_path / 'gate', ['shower'])
    write_delphes(path, random_events(3, seed=8))
    with pytest.raises(ValueError, match='changed after its gate verdict'):
        gate.require_accepted(tmp_path / 'gate', ['detector'])
    refused = gate.evaluate('analysis', returncode=2, contracts=[])
    gate.record(tmp_path / 'gate', refused)
    with pytest.raises(ValueError, match='was refused'):
        gate.require_accepted(tmp_path / 'gate', ['analysis'])
    with pytest.raises(ValueError, match='already recorded'):
        gate.record(tmp_path / 'gate', refused)


def test_command_line(tmp_path, capsys):
    path = delphes(tmp_path)
    (tmp_path / 'contracts.json').write_text(json.dumps([contract(path)]))
    assert gate.main(['check', '--stage', 'detector', '--contracts', str(tmp_path / 'contracts.json'), '--returncode', '0']) == 0
    assert json.loads(capsys.readouterr().out)['verdict'] == 'accepted'
    assert gate.main(['markers']) == 0
