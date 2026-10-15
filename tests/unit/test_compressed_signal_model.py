"""Paper-cut transcription and weighted model transport, not ATLAS acceptance validation."""
import copy
import hashlib
import json
import math
import sys
from types import SimpleNamespace

import jsonpatch
import numpy as np
import pyhf
import pytest

from ravel.physics.analysis_packages import load_routine
from analysis_package_fixtures import selected_manifest
native = load_routine(selected_manifest('selection-a'))
from ravel.physics import sa2json_native as converter


def control(**changes):
    values = dict(is2L=True, isOS=True, isee=True, ismm=False, pt1=35., pt2=25.,
                  mll=20., drll=.8, mtautau=-20., met=250., njets=1, nbjets=0,
                  jet1pt=180., min_dphi=2.8, lead_dphi=2.8, mt=40., mt2=110., risr=.75)
    return dict(values, **changes)


@pytest.mark.parametrize("region,changes", [
    ("CR_S_VV_high", {}),
    ("CR_S_VV_low", dict(met=175., risr=.7)),
    ("CR_S_tau_high", dict(mtautau=90., risr=.9)),
    ("CR_S_tau_low", dict(met=175., mtautau=90., risr=.65)),
    ("CR_S_top_high", dict(nbjets=1, risr=.75)),
    ("CR_S_top_low", dict(met=175., nbjets=1, risr=.9)),
])
def test_six_controls_and_all_flavours(region, changes):
    for flavour in [dict(isee=True, ismm=False), dict(isee=False, ismm=True),
                    dict(isee=False, ismm=False)]:
        assert native.select_slepton_controls(**control(**dict(changes, **flavour))) == {region}


@pytest.mark.parametrize("changes", [
    dict(is2L=False), dict(isOS=False), dict(pt1=5), dict(mll=3.1), dict(mll=60),
    dict(drll=.3), dict(jet1pt=100), dict(min_dphi=.4), dict(lead_dphi=2),
    dict(mt2=100), dict(mt2=140), dict(pt2=20), dict(met=200), dict(risr=.7),
    dict(risr=.85), dict(mtautau=130), dict(nbjets=1, risr=.6),
])
def test_control_boundaries_are_explicit_and_do_not_leak(changes):
    assert native.select_slepton_controls(**control(**changes)) == set()


@pytest.mark.parametrize("field", ["met", "mt2", "risr", "mtautau"])
def test_controls_reject_undefined_kinematics(field):
    with pytest.raises(ValueError, match="finite"):
        native.select_slepton_controls(**control(**{field: math.nan}))


def test_low_vv_requires_leading_transverse_mass_and_one_or_two_jets():
    for changes in [dict(mt=30), dict(njets=3), dict(met=150), dict(risr=.8)]:
        assert native.select_slepton_controls(**control(**({'met': 175., 'risr': .7} | changes))) == set()
    assert native.select_slepton_controls(**control(met=175., risr=.7, njets=2)) == {"CR_S_VV_low"}


def test_tau_and_top_controls_replace_only_their_declared_orthogonality_cuts():
    for value in [60, 120, 160]:
        assert native.select_slepton_controls(**control(mtautau=value, risr=.9)) == set()
    assert native.select_slepton_controls(**control(nbjets=1, mtautau=90., risr=.9)) == set()
    assert native.select_slepton_controls(**control(nbjets=1, met=175., risr=.75)) == set()


def test_opposite_flavour_separation_and_no_invented_mass_floor():
    assert native.select_slepton_controls(**control(isee=False, ismm=False, drll=.2)) == set()
    assert native.select_slepton_controls(**control(isee=False, ismm=False, drll=.25, mll=2)) == {"CR_S_VV_high"}
    assert native.select_slepton_controls(**control(isee=True, drll=.25, mll=2)) == set()


def _objects():
    return {'el_pt': [[12.]], 'el_eta': [[.6]], 'el_phi': [[.2]],
            'el_charge': [[-1]], 'el_id': [[0x7fffffff]],
            'mu_pt': [[35.]], 'mu_eta': [[-.6]], 'mu_phi': [[-.2]],
            'mu_charge': [[1]], 'mu_id': [[0x7fffffff]],
            'jet_pt': [[180.]], 'jet_eta': [[0.]], 'jet_phi': [[3.]],
            'jet_id': [[0x000FDF00]], 'jet_m': [[10.]],
            'met_pt': [250.], 'met_phi': [0.]}


def test_mixed_flavour_objects_follow_original_cpp_pt_sorting():
    selected = native.select_objects(_objects(), 0)
    assert [(lep.typ, lep.pt) for lep in selected['signalLeptons']] == [(native.MUON, 35.), (native.ELECTRON, 12.)]


def test_region_driver_uses_actual_mixed_flavour_leading_lepton(monkeypatch):
    selected = native.select_objects(_objects(), 0)
    monkeypatch.setattr(native, 'calcAMT2', lambda *args: 102.)
    monkeypatch.setattr(native, 'calcMTauTau', lambda *args: -20.)
    # Low VV needs mT(l1)>30. The real muon is leading, despite appearing second
    # in the input flavour collection. Record the object sent to the mT helper.
    leading = []
    monkeypatch.setattr(native, 'calcMT', lambda lep, met: leading.append(lep.typ) or 40.)
    selected['met'] = native.Obj(175., 0., 0., 0., 0, 0, 6)
    regions, isee, ismm = native.select_regions(selected, .7, 1.)
    assert regions == {'CR_S_VV_low'} and leading == [native.MUON]
    assert not isee and not ismm
    assert native.select_regions(selected, .7, 1., include_controls=False)[0] == set()


def workspace(names):
    return {'version': '1.0.0', 'channels': [
        {'name': name, 'samples': [{'name': 'background', 'data': [10.], 'modifiers': []}]}
        for name in names], 'observations': [{'name': name, 'data': [10.]} for name in names],
        'measurements': [{'name': 'Measurement', 'config': {'poi': 'fictional_strength', 'parameters': []}}]}


@pytest.mark.parametrize('names', [['fictional_amber','fictional_violet'], ['fictional_a','fictional_b','fictional_c']])
def test_supplied_channel_population_is_complete(names):
    spec=workspace(names)
    mapping={name:{'region':'selected_'+str(i)} for i,name in enumerate(names)}
    assert converter.compressed_channel_map(spec,mapping=mapping)==mapping
    with pytest.raises(ValueError,match='cover every'):
        converter.validate_channel_map(dict(list(mapping.items())[:-1]),spec)


def test_implicit_channel_mapping_fails_without_guessing():
    with pytest.raises(converter.MissingChannelMap,match='channel map'):
        converter.compressed_channel_map(workspace(['fictional_region']))


def test_signed_weight_moments_apply_flavour_mask_without_dropping_negative_weights():
    branches = {'SR': [2., -1., 30., 0.], 'selected_flavour': [1, 1, 0, 1]}
    assert converter.selected_weight_moments(branches, 'SR', 'selected_flavour') == {
        'sumw': 1., 'sumw2': 5., 'nonzero_weights': 2, 'negative_weights': 1}


@pytest.mark.parametrize('weights', [[math.inf], [math.nan], [1e308], [1e308, 1e308]])
def test_nonfinite_or_overflowing_weight_moments_fail(weights):
    with pytest.raises(ValueError):
        converter.selected_weight_moments({'SR': weights}, 'SR')


@pytest.mark.parametrize('policy,constraint', [('shapesys', 'poisson'), ('staterror', 'normal')])
def test_actual_moments_define_independent_mc_constraints_and_scale(policy, constraint):
    spec = workspace(['z', 'a'])  # Raw JSON order is intentionally unsorted.
    branches = {'CR': [2., -1., 0.], 'SR': [0., 0., 3.]}
    mapping = {'z': {'region': 'CR'}, 'a': {'region': 'SR'}}
    original = copy.deepcopy(spec)
    patch, metadata = converter.build_signal_patch(spec, [branches], name='signal',
        mapping=mapping, lumi=10., scale=2., mc_stat=policy)
    assert spec == original
    merged = jsonpatch.apply_patch(spec, patch)
    assert [channel['samples'][-1]['data'][0] for channel in merged['channels']] == [20., 60.]
    errors = [channel['samples'][-1]['modifiers'][1]['data'][0] for channel in merged['channels']]
    assert errors == pytest.approx([math.sqrt(5)*20, 60.])
    model = pyhf.Workspace(merged).model()
    nuisance_names = [row['mc_stat_modifier'] for row in metadata['channels']]
    assert len(set(nuisance_names)) == 2
    assert [model.config.param_set(name).pdf_type for name in nuisance_names] == [constraint]*2
    assert metadata['channels'][0]['effective_events'] == pytest.approx(.2)
    if policy == 'shapesys':
        assert model.config.param_set(nuisance_names[0]).auxdata == pytest.approx([.2])
    assert metadata['detector_trigger_ISR_theory_variations'] == 'not supplied'


def test_supplied_control_signal_preserves_all_event_flavours():
    spec = workspace(['fictional_control'])
    branches = {'selected_control': [1., 2., 3.], 'selected_flavour': [1, 0, 0], 'other_flavour': [0, 1, 0]}
    patch, metadata = converter.build_signal_patch(spec, [branches], name='signal',
        mapping={'fictional_control':{'region':'selected_control'}}, lumi=1., mc_stat='none')
    assert patch[0]['value']['data'] == [6.]
    assert metadata['channels'][0]['sumw2'] == 14.


def test_missing_cr_branch_cannot_be_treated_as_zero():
    spec = workspace(['fictional_control', 'fictional_signal'])
    with pytest.raises(ValueError, match='missing or invalid SR branch'):
        converter.build_signal_patch(spec, [{'selected_signal': [1.], 'selected_flavour': [1]}],
            name='signal', mapping={'fictional_control':{'region':'selected_control'},'fictional_signal':{'region':'selected_signal','flavour':'selected_flavour'}}, lumi=1., mc_stat='none')


def test_supplied_signal_omission_is_explicit_and_labeled():
    spec = workspace(['fictional_control', 'fictional_signal'])
    patch, metadata = converter.build_signal_patch(spec, [{'selected_signal': [1.], 'selected_flavour': [1]}],
        name='signal', mapping={'fictional_control':None,'fictional_signal':{'region':'selected_signal','flavour':'selected_flavour'}}, lumi=1., mc_stat='none')
    assert len(patch) == 1 and patch[0]['path'].startswith('/channels/1/')
    assert metadata['channels'][0]['status'] == 'declared-signal-omission'
    assert metadata['mc_stat_interpretation'] == 'omitted'


@pytest.mark.parametrize('policy', ['shapesys', 'staterror'])
def test_zero_selected_bin_never_becomes_a_certified_zero_error(policy):
    patch, metadata = converter.build_signal_patch(workspace(['a']), [{'SR': [0., 0.]}],
        name='signal', mapping={'a': {'region': 'SR'}}, lumi=1., mc_stat=policy)
    assert patch[0]['value']['data'] == [0.]
    assert len(patch[0]['value']['modifiers']) == 1
    assert metadata['channels'][0]['precision_status'] == 'zero-selected/precision-unresolved'
    assert metadata['channels'][0]['effective_events'] is None


@pytest.mark.parametrize('policy', ['shapesys', 'staterror'])
def test_signed_cancellation_does_not_silently_disable_mc_uncertainty(policy):
    with pytest.raises(ValueError, match='zero net yield but positive sumw2'):
        converter.build_signal_patch(workspace(['a']), [{'SR': [1., -1.]}], name='signal',
            mapping={'a': {'region': 'SR'}}, lumi=1., mc_stat=policy)


def test_overlapping_channels_cannot_get_independent_mc_constraints():
    with pytest.raises(ValueError, match='disjoint model channels'):
        converter.build_signal_patch(workspace(['a', 'b']), [{'A': [2.], 'B': [2.]}],
            name='signal', mapping={'a': {'region': 'A'}, 'b': {'region': 'B'}}, lumi=1., mc_stat='shapesys')


def test_existing_background_nuisance_cannot_be_reused_for_native_mc():
    spec = workspace(['a'])
    collision = 'native_signal_mcstat_' + hashlib.sha256(b'signal\0a').hexdigest()[:20]
    spec['channels'][0]['samples'][0]['modifiers'] = [{'name': collision, 'type': 'normfactor', 'data': None}]
    with pytest.raises(ValueError, match='collides'):
        converter.build_signal_patch(spec, [{'SR': [1.]}], name='signal',
            mapping={'a': {'region': 'SR'}}, lumi=1., mc_stat='shapesys')


def _fake_root(monkeypatch, values):
    class File:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __getitem__(self, key): return SimpleNamespace(arrays=lambda: values)
    monkeypatch.setitem(sys.modules, 'uproot', SimpleNamespace(open=lambda path: File()))


def test_cli_binds_patch_and_moments_to_actual_input_bytes(tmp_path, monkeypatch):
    root = tmp_path/'input.root'; root.write_bytes(b'fixture ROOT handled by read-only fake')
    bkg = tmp_path/'background.json'; bkg.write_text(json.dumps(workspace(['fictional_control'])))
    mapping=tmp_path/'mapping.json';mapping.write_text(json.dumps({'fictional_control':{'region':'selected_control'}}))
    patch = tmp_path/'patch.json'; metadata = tmp_path/'signal_model.json'
    _fake_root(monkeypatch, {'selected_control': np.array([2., -1.])})
    converter.main(['-i', str(root), '-b', str(bkg), '-o', str(patch), '-n', 'signal', '-l', '10',
                    '--channel-map', str(mapping), '--mc-stat', 'shapesys', '--signal-metadata', str(metadata)])
    record = json.loads(metadata.read_text())
    assert record['patch']['sha256'] == hashlib.sha256(patch.read_bytes()).hexdigest()
    assert record['inputs'][0]['sha256'] == hashlib.sha256(root.read_bytes()).hexdigest()
    assert record['channel_map']['sha256'] == hashlib.sha256(mapping.read_bytes()).hexdigest()
    assert record['channels'][0]['sumw2'] == 5.


def test_cli_rejects_duplicate_content_even_at_different_paths(tmp_path, monkeypatch):
    first, second = tmp_path/'first.root', tmp_path/'copy.root'
    first.write_bytes(b'same retained input'); second.write_bytes(first.read_bytes())
    bkg = tmp_path/'bkg.json'; bkg.write_text(json.dumps(workspace(['fictional_control'])))
    mapping=tmp_path/'mapping.json';mapping.write_text(json.dumps({'fictional_control':{'region':'selected_control'}}))
    out = tmp_path/'patch.json'
    _fake_root(monkeypatch, {})
    with pytest.raises(ValueError, match='duplicate signal input content'):
        converter.main(['-i', str(first), '-i', str(second), '-b', str(bkg), '-o', str(out),
                        '-n', 'signal', '-l', '1', '--channel-map', str(mapping), '--mc-stat', 'none'])
    assert not out.exists() and first.read_bytes() == b'same retained input'


def _definition_arguments(tmp_path):
    """A fictional reviewed cutflow definition bound to the package selection that writes the trace."""
    from source_record_fixtures import cutflow
    (tmp_path / 'definition').mkdir(exist_ok=True)
    binding, _ = cutflow(tmp_path / 'definition', native=True)
    return ['--validation-definition', binding['path'], '--validation-definition-sha256', binding['sha256']]


@pytest.mark.parametrize('rows', [
    '',
    '1,1,2,.9,1,0,0,0,0,1,0\n',
    '1,1,2,nan,1,0,0,0,0,1,1\n',
    '1,1,2,.9,1,0,0,0,0,1,2\n',
    '1,1,2,.9,1,0,0,0,0,1,1\n1,1,2,.9,1,0,0,0,0,1,1\n',
    '9,1,2,.9,1,0,0,0,0,1,1\n',
])
def test_native_driver_rejects_incomplete_or_invalid_rjr_before_yield_output(tmp_path, monkeypatch, rows):
    monkeypatch.setattr(sys, 'argv', ['native_simpleanalysis', '--input', 'mock.root', '--output', str(tmp_path),
                                      *_definition_arguments(tmp_path)])
    monkeypatch.setattr(native, 'load_ntuple', lambda *args: (_objects(), [1], 1, {'w_all': [2.]}))
    def resolve(command, **kwargs):
        from pathlib import Path
        Path(command[-1]).write_text('Event,nJ,nLep,RISR,MS,PTISR,MISR,dphiISRI,NjV,NjISR,solved\n' + rows)
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', resolve)
    with pytest.raises(ValueError, match='RestFrames'):
        native.run()
    assert not (tmp_path/(native.NAME+'.txt')).exists()
    assert not (tmp_path/'FictionalRoutine701.root').exists()


def test_native_driver_cannot_overwrite_event_join_with_duplicate_id(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['native_simpleanalysis', '--input', 'mock.root', '--output', str(tmp_path)])
    monkeypatch.setattr(native, 'load_ntuple', lambda *args: ({}, [1, 1], 2, {'w_all': [2., -1.]}))
    monkeypatch.setattr(native.subprocess, 'run', lambda *args, **kwargs: pytest.fail('must reject before resolver'))
    with pytest.raises(ValueError, match='duplicate Event'):
        native.run()


def test_native_driver_retains_actual_signed_cr_moments(tmp_path, monkeypatch):
    from pathlib import Path
    input_root = tmp_path/'input.root'
    input_root.write_bytes(b'inert source bound to the stubbed ntuple reader')
    rjr_binary = tmp_path/'rjr-resolver-fixture'
    rjr_binary.write_bytes(b'inert resolver bound to the stubbed subprocess')
    monkeypatch.setattr(sys, 'argv', ['native_simpleanalysis', '--input', str(input_root),
        '--output', str(tmp_path), '--rjr-binary', str(rjr_binary), *_definition_arguments(tmp_path)])
    totals = {'w_all': [2., -1.], 'sumW': 1., 'sumW2': 5., 'Ngen': 2}
    monkeypatch.setattr(native, 'load_ntuple', lambda *args: ({}, [1, 2], 2, totals))
    selected = native.select_objects(_objects(), 0)
    monkeypatch.setattr(native, 'select_objects', lambda arrays, i, **kwargs: dict(selected))
    def resolve(command, **kwargs):
        Path(command[-1]).write_text('Event,nJ,nLep,RISR,MS,PTISR,MISR,dphiISRI,NjV,NjISR,solved\n' +
            ''.join(f'{ev},1,2,.75,1,0,0,0,0,1,1\n' for ev in [1, 2]))
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(native.subprocess, 'run', resolve)
    monkeypatch.setattr(native, 'select_regions', lambda *args, **kwargs: ({'CR_S_VV_high'}, False, False))
    captured = []
    monkeypatch.setattr(native, 'write_root', lambda path, rows, order: captured.extend(rows))
    native.run()
    assert 'CR_S_VV_high,2,1,2.23607' in (tmp_path/(native.NAME+'.txt')).read_text()
    assert [row[1] for row in captured] == [2., -1.]
    import gzip, hashlib, json
    with gzip.open(tmp_path/'compressed_trace.jsonl.gz', 'rt') as stream:
        header = json.loads(next(stream))
    assert header['metadata']['rjr_binary_sha256'] == hashlib.sha256(rjr_binary.read_bytes()).hexdigest()


def test_repeated_normalized_streams_cannot_silently_double_a_signal():
    with pytest.raises(ValueError, match='replicas must not be summed'):
        converter.build_signal_patch(workspace(['a']), [{'SR': [1.]}, {'SR': [1.]}],
            name='signal', mapping={'a': {'region': 'SR'}}, lumi=1., mc_stat='none')


def test_explicit_independent_components_sum_moments_without_exposure_guessing():
    patch, metadata = converter.build_signal_patch(workspace(['a']), [{'SR': [1.]}, {'SR': [3.]}],
        name='signal', mapping={'a': {'region': 'SR'}}, lumi=1., mc_stat='shapesys',
        input_combination='sum-independent-components')
    assert patch[0]['value']['data'] == [4.]
    assert patch[0]['value']['modifiers'][1]['data'] == pytest.approx([math.sqrt(10)])
    assert metadata['channels'][0]['sumw2'] == 10.
    assert metadata['input_combination'] == 'sum-independent-components'


def test_replica_pooling_refuses_missing_generated_exposure_and_process_evidence():
    # Both ROOTs happen to have one selected event; this is not generated exposure.
    with pytest.raises(ValueError, match='original generated exposures'):
        converter.build_signal_patch(workspace(['a']), [{'SR': [1.]}, {'SR': [3.]}],
            name='signal', mapping={'a': {'region': 'SR'}}, lumi=1., input_combination='pool-replicas', mc_stat='none')
