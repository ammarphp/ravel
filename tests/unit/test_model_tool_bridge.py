"""Adverse custody/effective-point controls; fixtures do not execute a generator."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from ravel.physics import model_tool_bridge as bridge
from ravel.validation import model_tool_witness as witness

CARD = 'BLOCK SMINPUTS\n 1 128\nBLOCK MASS\n 11 0\n 13 0\n'


def config():
    pin = {'path': '/bound/file', 'sha256': 'a'*64}
    tree = {'root': '/bound/source', 'manifest': pin}
    return {'schema_version': 1, 'source': 'attributed controlled UFO source',
        'runtime': {'madgraph_tree': tree, 'python': pin, 'python_manifest': pin},
        'model_tree': tree, 'trusted_ufo_python': True, 'parameter_card': pin,
        'processes': [{'id': 'leptons', 'initial_pdgs': [-11, 11], 'final_pdgs': [-13, 13],
                       'orders': {'QED': 2, 'QCD': 0}, 'forbidden_pdgs': [23, 25]}],
        'seeds': [19, 101], 'energy_gev': 100., 'max_seconds': 60, 'max_ram_mib': 1024}


def native(c):
    snapshot = {'external_parameters': [{'name': name, 'block': block, 'codes': [code],
                    'observed_value': {'real': value, 'imag': 0.}}
               for name, block, code, value in [('alpha', 'sminputs', 1, 128.), ('Me', 'mass', 11, 0.), ('MM', 'mass', 13, 0.)]],
        'parameters': {'alpha': {'real': 128., 'imag': 0.}},
        'couplings': {'GC': {'real': 0., 'imag': .3}}}
    point = {'ordered_leg_pdgs': [-11, 11, -13, 13], 'effective_masses_gev': {'-11': 0., '11': 0., '-13': 0., '13': 0.},
        'ordered_leg_states': [False, False, True, True], 'effective_orders': {'QED': 2, 'QCD': 0},
        'effective_forbidden_pdgs': [23, 25], 'effective_perturbation_couplings': [],
        'momenta_gev': [[50., 0., 0., 50.], [50., 0., 0., -50.], [50., 50., 0., 0.], [50., -50., 0., 0.]], 'm2': 1.}
    return {'restriction_applied': False, 'model_point': deepcopy(snapshot), 'checks': [
        {'process_id': 'leptons', 'seed': seed, 'evaluator_snapshots': [deepcopy(snapshot), deepcopy(snapshot)],
         'permutation': {'native_passed': True, 'values': [1., 1., 1.]},
         'lorentz': {'m2_values': [1., 1., 1.]}, 'evaluations': [deepcopy(point), deepcopy(point)]}
        for seed in c['seeds']]}


def test_nonvacuous_synthetic_card_and_phase_witness():
    c = config()
    result = witness.adjudicate(native(c), c, CARD)
    assert result['passed'] and result['observed_phase_points'] == 4
    assert result['independent_amplitude_or_lagrangian_validation'] is False


@pytest.mark.parametrize('defect', ['changed_card', 'missing_card', 'extra_card', 'missing_evaluator', 'different_evaluators',
    'zero_amplitude', 'permutation', 'lorentz', 'off_shell', 'conservation', 'wrong_energy', 'wrong_legs',
    'missing_observations', 'nonfinite_coupling'])
def test_actual_observation_failures_are_not_native_passes(defect):
    c = config(); data = native(c); row = data['checks'][0]; card = CARD
    if defect == 'changed_card': card = card.replace('1 128', '1 129')
    elif defect == 'missing_card': card = card.replace(' 13 0\n', '')
    elif defect == 'extra_card': card += ' 15 0\n'
    elif defect == 'missing_evaluator': row['evaluator_snapshots'].pop()
    elif defect == 'different_evaluators': row['evaluator_snapshots'][1]['couplings']['GC']['imag'] = .4
    elif defect == 'zero_amplitude': row['permutation']['values'] = [0., 0.]
    elif defect in ('permutation', 'lorentz'):
        key = 'values' if defect == 'permutation' else 'm2_values'
        row[defect][key] = [1., 1.01]
    elif defect == 'off_shell': row['evaluations'][0]['momenta_gev'][2][0] = 51.
    elif defect == 'conservation': row['evaluations'][0]['momenta_gev'][3] = [50., 0., 50., 0.]
    elif defect == 'wrong_energy': c['energy_gev'] = 101.
    elif defect == 'wrong_legs': row['evaluations'][0]['ordered_leg_pdgs'][-1] = 15
    elif defect == 'missing_observations': row['evaluations'] = []
    elif defect == 'nonfinite_coupling': row['evaluator_snapshots'][0]['couplings']['GC']['real'] = float('nan')
    result = witness.adjudicate(data, c, card)
    assert not result['passed'] and result['failures']


@pytest.mark.parametrize('defect', ['duplicate_case', 'missing_seed', 'restriction'])
def test_complete_process_seed_coverage_and_full_model(defect):
    c = config(); data = native(c)
    if defect == 'duplicate_case': data['checks'][1] = data['checks'][0]
    elif defect == 'missing_seed': data['checks'].pop()
    else: data['restriction_applied'] = True
    with pytest.raises(ValueError): witness.adjudicate(data, c, CARD)


@pytest.mark.parametrize('card', ['BLOCK MASS\n11 0\n11 0\n', 'DECAY 6 Auto\n', 'DECAY 6 -1\n',
    'BLOCK MASS Q=100\n11 0\n', 'DECAY 6 1\n 1 2 5 24\n', 'BLOCK MASS\n11 NaN\n'])
def test_ambiguous_implicit_or_nonfinite_cards_refused(card):
    with pytest.raises(ValueError): witness.card_values(card)


@pytest.mark.parametrize('defect', ['trust', 'one_seed', 'duplicate_seed', 'loop_order', 'free_process_text',
    'multiparticle', 'bad_energy', 'extra_command', 'negative_forbidden'])
def test_bounded_typed_native_protocol(defect):
    c = config()
    if defect == 'trust': c['trusted_ufo_python'] = False
    elif defect == 'one_seed': c['seeds'] = [1]
    elif defect == 'duplicate_seed': c['seeds'] = [1, 1]
    elif defect == 'loop_order': c['processes'][0]['orders']['QED'] = 99
    elif defect == 'free_process_text': c['processes'][0]['initial_pdgs'] = ['p', 'p']
    elif defect == 'multiparticle': c['processes'][0]['final_pdgs'].append(22)
    elif defect == 'bad_energy': c['energy_gev'] = float('inf')
    elif defect == 'extra_command': c['processes'][0]['command'] = 'launch'
    elif defect == 'negative_forbidden': c['processes'][0]['forbidden_pdgs'] = [-23]
    with pytest.raises(ValueError): bridge.validate_config(c)


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def bound_fixture(tmp_path):
    c = config(); mg = tmp_path/'mg'; mg.mkdir(); (mg/'VERSION').write_text('version = 2.9.27\n')
    model = tmp_path/'model'; model.mkdir()
    for name in ('parameters.py', 'particles.py', 'vertices.py', 'couplings.py', 'object_library.py', 'lorentz.py', '__init__.py'):
        (model/name).write_text('# synthetic source-only fixture, never executed\n')
    for key, root in [('madgraph_tree', mg), ('model_tree', model)]:
        manifest = tmp_path/(key+'.json'); manifest.write_text(json.dumps(bridge.source_tree(root)))
        tree = {'root': str(root), 'manifest': pin(manifest)}
        if key == 'model_tree': c[key] = tree
        else: c['runtime'][key] = tree
    python = Path(sys.executable).resolve(); c['runtime']['python'] = pin(python)
    dependency = tmp_path/'dependency.py'; dependency.write_text('# bound support fixture\n')
    support = tmp_path/'python.json'; support.write_text(json.dumps({'python_sha256': pin(python)['sha256'], 'files': [pin(dependency)]}))
    c['runtime']['python_manifest'] = pin(support)
    card = tmp_path/'param_card.dat'; card.write_text(CARD); c['parameter_card'] = pin(card)
    doc = tmp_path/'config.json'; doc.write_text(json.dumps(c))
    return {'config': str(doc)}, c, mg, model


def test_source_tree_added_file_invalidates_bound_census(tmp_path):
    task, _, mg, _ = bound_fixture(tmp_path)
    assert bridge.inputs(task, tmp_path)
    (mg/'extra.py').write_text('# newly unbound import\n')
    with pytest.raises(ValueError, match='complete source census'): bridge.inputs(task, tmp_path)


def test_model_custody_and_native_input_validation_do_not_execute_ufo(tmp_path):
    task, _, _, model = bound_fixture(tmp_path)
    files = bridge.inputs(task, tmp_path)
    assert model/'parameters.py' in files
    (model/'parameters.py').write_text('raise RuntimeError("must never import during intake")\n')
    with pytest.raises(ValueError, match='source census'): bridge.inputs(task, tmp_path)


@pytest.mark.parametrize('kind', ['escape', 'directory', 'dangling'])
def test_source_alias_custody_defects(kind, tmp_path):
    root = tmp_path/'root'; root.mkdir(); outside = tmp_path/'outside'; outside.write_text('bytes')
    if kind == 'directory': (root/'link').symlink_to(tmp_path, target_is_directory=True)
    elif kind == 'dangling': (root/'link').symlink_to(root/'absent')
    else: (root/'link').symlink_to(outside)
    with pytest.raises(ValueError): bridge.source_tree(root)


def test_internal_regular_alias_snapshot_retains_bytes(tmp_path):
    root = tmp_path/'root'; root.mkdir(); (root/'data.py').write_text('original\n'); (root/'alias.py').symlink_to('data.py')
    manifest = tmp_path/'manifest.json'; manifest.write_text(json.dumps(bridge.source_tree(root)))
    out = tmp_path/'copy'; bridge._copy({'root': str(root), 'manifest': pin(manifest)}, tmp_path, out)
    assert not (out/'alias.py').is_symlink() and (out/'alias.py').read_text() == 'original\n'


def test_no_native_execution_or_output_creation_without_actual_worker(tmp_path, monkeypatch):
    task, _, _, _ = bound_fixture(tmp_path); out = tmp_path/'outputs'
    from ravel.physics import reinterpret_db
    monkeypatch.setattr(reinterpret_db, 'execute_native', lambda *a: pytest.fail('unapproved native call'))
    with pytest.raises(ValueError, match='approved supervised'): bridge.run(task, tmp_path, out)
    assert not out.exists()


def test_different_case_couplings_cannot_share_one_model_point():
    c = config(); data = native(c)
    for snapshot in data['checks'][1]['evaluator_snapshots']:
        snapshot['couplings']['GC']['imag'] = .4
    result = witness.adjudicate(data, c, CARD)
    assert not result['passed'] and 'different effective model points' in result['failures'][0]['reason']


@pytest.mark.parametrize('field,value', [('ordered_leg_states', [True, True, False, False]),
    ('effective_orders', {'QED': 2}), ('effective_forbidden_pdgs', []), ('effective_perturbation_couplings', ['QCD'])])
def test_actual_process_definition_must_match_supplied_tree_contract(field, value):
    c = config(); data = native(c)
    data['checks'][0]['evaluations'][0][field] = value
    result = witness.adjudicate(data, c, CARD)
    assert not result['passed'] and 'declared tree process' in result['failures'][0]['reason']


@pytest.mark.parametrize('defect', ['empty', 'duplicate', 'unbound', 'changed', 'extra_field'])
def test_imported_source_census_refuses_unbound_or_ambiguous_receipts(defect):
    row = {'path': '/approved/dependency.py', 'sha256': 'a'*64}
    allowed = {row['path']: row['sha256']}
    assert bridge.imported_sources([row], allowed) == 1
    rows = [deepcopy(row)]
    if defect == 'empty': rows = []
    elif defect == 'duplicate': rows.append(deepcopy(row))
    elif defect == 'unbound': rows[0]['path'] = '/unbound/dependency.py'
    elif defect == 'changed': rows[0]['sha256'] = 'b'*64
    else: rows[0]['unapproved'] = True
    with pytest.raises(ValueError): bridge.imported_sources(rows, allowed)
