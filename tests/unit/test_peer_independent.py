"""Independent software controls; all scientific/native dispatch is inert."""
import hashlib
import json
from pathlib import Path
import pytest
from ravel.physics import parameter_space_sampling as a, parameter_space_sampling_core as core
from test_parameter_space_sampling import fixture


def write_witness(root, name, value):
    (root / (name + '.json')).write_text(json.dumps(value, indent=2, allow_nan=False))


def emcee_projection(root, monkeypatch, coordinate):
    task, doc, ip = fixture(root, monkeypatch, method='EMCEE', count=8)
    info = core.ini(ip.read_bytes(), doc)
    info['figures'] = []
    raw = {'result/ScanResult.txt': b'x,y,f,dwell\n.5,.5,1,1\n',
           'result/All_ScanResult.txt': b'x,y,f,dwell\n.5,.5,1,1\n',
           'result/EMCEEChain.txt': ('log_probability,x,y\n' + ('-1,' + coordinate + ',.5\n') * 8).encode()}
    files = {k: {'size': len(v), 'sha256': hashlib.sha256(v).hexdigest()} for k, v in raw.items()}
    obs = {'status': 'completed', 'counts': {}, 'workers': [],
           'samplers': {'EMCEE': {'chain_unit_coordinates': [[[.5, .5]] * 8],
                                   'log_probability': [[-1] * 8],
                                   'acceptance_fraction': [.5] * 8}}}
    return a.project(doc, info, files, raw.__getitem__, obs), raw, info


def test_exact_chain_coordinate_positive(tmp_path, monkeypatch):
    result, raw, info = emcee_projection(tmp_path, monkeypatch, '.5')
    assert result['issues'] == []
    assert result['sampler_population']['complete_slots'] == 8


def test_emcee_physical_table_must_match_full_retained_chain(tmp_path, monkeypatch):
    result, raw, info = emcee_projection(tmp_path, monkeypatch, '42')
    write_witness(tmp_path, 'emcee-coordinate-witness', {
        'retained_unit_chain': result['observation']['samplers']['EMCEE']['chain_unit_coordinates'],
        'declared_parameters': info['parameters'], 'native_table': raw['result/EMCEEChain.txt'].decode(),
        'issues': result['issues'], 'physical_table_coordinate': 42,
        'source_flat_prior_coordinate': .5,
        'scope': 'API delivery consistency, no sampler or likelihood called'})
    assert result['issues'], 'corrupted physical chain coordinates were admitted as complete delivery'


def fake_run(root, monkeypatch, mutation=None):
    task, doc, ip = fixture(root, monkeypatch)
    out = root / 'output'
    monkeypatch.setattr(a, '_approved', lambda *args: (root, {'max_seconds': 20}))
    from ravel.physics import reinterpret_db
    seen = {}
    def fake_execute(argv, native, resources):
        req = core.strict((native / 'request.json').read_bytes())
        seen['request'] = req
        result = Path(req['work']) / 'result'
        (result / 'Figures').mkdir(parents=True)
        (result / 'ScanResult.txt').write_bytes(b'x,y,f\n1,2,3\n')
        (result / 'Figures/Color_x_y_f.png').write_bytes(b'explicit inert software figure')
        (native / 'observation.json').write_text(json.dumps({'status': 'completed',
            'counts': {'evaluations': 4}, 'workers': [], 'samplers': {}}))
        return {'returncode': 0, 'inert_scientific_transport': True}
    monkeypatch.setattr(reinterpret_db, 'execute_native', fake_execute)
    original_write = a.atomic_json
    def intercepted_write(path, value):
        original_write(path, value)
        path = Path(path)
        if path.name != mutation:
            return
        changed = json.loads(path.read_bytes())
        if mutation == 'request.json':
            changed['config']['resources']['max_evaluations'] = 1000
        elif mutation == 'raw-census.json':
            changed['files']['work/result/ScanResult.txt']['sha256'] = '0' * 64
        elif mutation == 'parameter-space-sampling.json':
            changed['physics_validated'] = True
        path.write_text(json.dumps(changed, allow_nan=False))
        seen['changed_path'] = str(path)
        seen['changed_value'] = changed
    monkeypatch.setattr(a, 'atomic_json', intercepted_write)
    value = a.run(task, root, out)
    return value, seen


def test_actual_adapter_positive_inert_transport(tmp_path, monkeypatch):
    value, seen = fake_run(tmp_path, monkeypatch)
    assert value['status'] == 'passed' and value['physics_validated'] is False
    assert seen['request']['config']['resources']['max_evaluations'] == 100
    persisted = core.strict((tmp_path / 'output/parameter-space-sampling.json').read_bytes())
    assert persisted == value


@pytest.mark.parametrize('target', ['request.json', 'raw-census.json', 'parameter-space-sampling.json'])
def test_generated_output_change_before_first_observed_pin_must_refuse(tmp_path, monkeypatch, target):
    try:
        value, seen = fake_run(tmp_path, monkeypatch, target)
    except (ValueError, RuntimeError, OSError):
        return
    write_witness(tmp_path, 'generated-output-witness', {
        'target': target, 'api_status': value['status'], 'api_physics_validated': value['physics_validated'],
        'api_resources': value['resources'], 'changed_path': seen['changed_path'],
        'changed_value': seen['changed_value'], 'errors': value['errors'],
        'scope': 'intended generated bytes versus delivered bytes; inert native seam'})
    assert value['status'] != 'passed', 'changed emitted bytes became the first admitted baseline'
