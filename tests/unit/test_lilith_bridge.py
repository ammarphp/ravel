"""Synthetic file-protocol and admission controls for an isolated likelihood engine."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


def bridge():
    return importlib.import_module('ravel.physics.lilith_bridge')


def bundle():
    return {'schema_version': 1, 'kind': 'higgs-sector-bundle',
            'input_kind': 'effective-couplings', 'charged_scalars': [],
            'neutral_scalars': [{'id': 'scalar-a', 'cp': 'even', 'mass_gev': 126.,
                'width_gev': .01, 'rates': [], 'couplings': {'vector': 1., 'fermion': -1.},
                'branching_ratios': {'hidden': .1, 'unseen': .2}}],
            'provenance': {'coupling_normalization': 'SM amplitude'}}


def database():
    return {'version': 'synthetic-v1', 'mass_window_gev': [120., 130.],
            'measurement_ids': ['ANA-0001', 'ANA-0002'], 'sha256': 'a' * 64}


def mapping():
    return {'couplings': {name: ('vector' if name in ('WW', 'ZZ') else 'fermion')
                          for name in bridge().COUPLINGS},
            'branching_ratios': {'invisible': 'hidden', 'undetected': 'unseen'},
            'precision': 'BEST-QCD'}


def request():
    return bridge().build_request(bundle(), bundle(), database(), mapping(),
                                  sector_validator=lambda value: value)


def test_poisoned_module_guard(monkeypatch):
    class Poison:
        def __getattr__(self, name):
            raise AssertionError('external package imported in host')
    monkeypatch.setitem(sys.modules, 'lilith', Poison())
    mod = bridge()
    assert mod.WORKER.name == 'lilith_worker.py'
    assert 'import lilith' not in Path(mod.__file__).read_text()
    assert request()['operation'] == 'higgs-lilith'


def test_mass_outside_database_refused():
    bad = bundle()
    bad['neutral_scalars'][0]['mass_gev'] = 131.
    with pytest.raises(ValueError, match='mass window'):
        bridge().build_request(bad, bundle(), database(), mapping(), sector_validator=lambda x: x)


def test_fake_worker_roundtrip(tmp_path):
    fake = Path(__file__).parents[1] / 'fixtures/higgs/lilith/fake_worker.py'
    def launch(command, output, resources):
        subprocess.run(command, check=True, timeout=10)
    result = bridge().exchange(request(), tmp_path / 'exchange',
                               [sys.executable, '-B', str(fake)], launch=launch,
                               resources={'max_seconds': 10, 'max_ram_mib': 64})
    assert result['minus2_log_likelihood'] == 8.
    assert result['delta_chi2'] == 3.
    assert result['n_obs'] == 3
    assert result['database']['version'] == 'synthetic-v1'
    assert result['physics_validated'] is False


def result(delta, ids):
    return {'operation': 'higgs-signals', 'status': 'passed', 'delta_chi2': delta,
            'measurements': [{'id': x, 'chi2': 1.} for x in ids],
            'comparison_input_sha256': 'b' * 64,
            'datasets': {'hsdataset': 'c' * 40}}


def test_cross_engine_discrepancy_lists_database_difference():
    other = {'operation': 'higgs-lilith', 'status': 'passed', 'delta_chi2': 14.,
             'database': database(), 'comparison_input_sha256': 'b' * 64}
    check = bridge().cross_engine(result(10., ['ANA-0001', 'ANA-0003']), other)
    assert check['status'] == 'finding'
    assert check['tolerance'] == 1.5
    assert check['only_higgs_signals'] == ['ANA-0003']
    assert check['only_lilith'] == ['ANA-0002']
    assert check['check'] == 'check:higgs.cross_engine'


@pytest.mark.parametrize('change,pattern', [
    (lambda b, d, m: b['neutral_scalars'][0].update(cp='mixed'), 'CP-even'),
    (lambda b, d, m: b['neutral_scalars'][0]['couplings'].pop('vector'), 'missing coupling'),
    (lambda b, d, m: b['neutral_scalars'][0]['branching_ratios'].pop('hidden'), 'missing BR'),
    (lambda b, d, m: b['neutral_scalars'][0]['branching_ratios'].update(hidden=.9), 'sum exceeds'),
    (lambda b, d, m: b['neutral_scalars'][0]['couplings'].update(vector=float('nan')), 'finite'),
    (lambda b, d, m: b['neutral_scalars'][0].update(mass_gev=True), 'finite'),
    (lambda b, d, m: b.update(charged_scalars=[{'id': 'charged-a'}]), 'charged'),
    (lambda b, d, m: b.update(input_kind='direct-rates'), 'direct rates'),
    (lambda b, d, m: b['provenance'].update(coupling_normalization='unspecified'), 'normalization'),
    (lambda b, d, m: d.update(measurement_ids=['ANA-0001', 'ANA-0001']), 'duplicate'),
    (lambda b, d, m: d.update(mass_window_gev=[130., 120.]), 'invalid'),
    (lambda b, d, m: m['couplings'].pop('tt'), 'complete'),
])
def test_no_silent_input_defaults(change, pattern):
    b, d, m = bundle(), database(), mapping()
    change(b, d, m)
    with pytest.raises(ValueError, match=pattern):
        bridge().build_request(b, bundle(), d, m, sector_validator=lambda x: x)


def test_signed_couplings_and_escaped_identity():
    import xml.etree.ElementTree as ET
    b = bundle()
    b['neutral_scalars'][0]['id'] = 'scalar<&'
    root = ET.fromstring(bridge().reduced_couplings_xml(b, database(), mapping()))
    assert root[0].attrib['part'] == 'scalar<&'
    assert root.find("./reducedcouplings/C[@to='tt']").text == '-1.0'
    assert root.find("./reducedcouplings/extraBR/BR[@to='invisible']").text == '0.1'


@pytest.mark.parametrize('delta,expected', [(11.5, 'passed'), (11.5001, 'finding'),
                                          (-10., 'finding')])
def test_comparison_tolerance_boundary(delta, expected):
    other = {'operation': 'higgs-lilith', 'status': 'passed', 'delta_chi2': delta,
             'database': database(), 'comparison_input_sha256': 'b' * 64}
    assert bridge().cross_engine(result(10., ['ANA-0001']), other)['status'] == expected


def test_different_physical_inputs_refused():
    other = {'operation': 'higgs-lilith', 'status': 'passed', 'delta_chi2': 10., 'database': database(),
             'comparison_input_sha256': 'd' * 64}
    with pytest.raises(ValueError, match='same physical'):
        bridge().cross_engine(result(10., ['ANA-0001']), other)


@pytest.mark.parametrize('status', [None, 'failed'])
@pytest.mark.parametrize('side', [0, 1])
def test_comparison_requires_explicit_passed_status(status, side):
    pair = [result(10., ['ANA-0001']),
            {'operation': 'higgs-lilith', 'status': 'passed', 'delta_chi2': 10.,
             'database': database(), 'comparison_input_sha256': 'b' * 64}]
    if status is None:
        del pair[side]['status']
    else:
        pair[side]['status'] = status
    with pytest.raises(ValueError, match='failed engine result'):
        bridge().cross_engine(*pair)


def raw_response(req):
    return {'schema_version': 1, 'operation': 'higgs-lilith', 'request_sha256': 'f' * 64,
            'comparison_input_sha256': req['comparison_input_sha256'], 'database': req['database'],
            'minus2_log_likelihood': 8., 'n_obs': 3,
            'sm_reference': {'same_call': True, 'minus2_log_likelihood': 5., 'n_obs': 3,
                            'input_sha256': hashlib.sha256(req['sm_xml'].encode()).hexdigest()}}


@pytest.mark.parametrize('change,pattern', [
    (lambda r: r.update(request_sha256='a' * 64), 'request identity'),
    (lambda r: r['database'].update(version='synthetic-v2'), 'database mismatch'),
    (lambda r: r.update(n_obs=True), 'n_obs'),
    (lambda r: r.update(minus2_log_likelihood=float('inf')), 'finite'),
    (lambda r: r.update(delta_chi2=100.), 'incorrect delta'),
    (lambda r: r['sm_reference'].update(same_call=False), 'same-call'),
    (lambda r: r.update(p_value=.5), 'p-value'),
    (lambda r: r.update(comparison_input_sha256='d' * 64), 'comparison input'),
])
def test_stale_or_invalid_response_refused(change, pattern):
    req = request()
    raw = copy.deepcopy(raw_response(req))
    change(raw)
    with pytest.raises(ValueError, match=pattern):
        bridge().finalize_result(raw, req, 'f' * 64)


def test_unapproved_run_never_launches(tmp_path, monkeypatch):
    from ravel.physics import reinterpret_db
    def forbidden(*args, **kwargs):
        raise AssertionError('unapproved child launched')
    monkeypatch.setattr(reinterpret_db, 'execute_native', forbidden)
    with pytest.raises(ValueError, match='approved ordinary'):
        bridge().run({'input': 'absent.json'}, tmp_path, tmp_path / 'out')


def test_worker_without_delegation_never_imports_engine(tmp_path, monkeypatch):
    worker = importlib.import_module('ravel.physics.lilith_worker')
    monkeypatch.setitem(sys.modules, 'lilith', None)
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request()))
    with pytest.raises(ValueError, match='delegation'):
        worker.main([str(path), str(tmp_path / 'response.json')])
    assert not (tmp_path / 'response.json').exists()


def test_worker_api_seam_with_synthetic_engine():
    from types import SimpleNamespace
    worker = importlib.import_module('ravel.physics.lilith_worker')
    req = request()
    req['database_list'] = 'synthetic.list'
    class Engine:
        def __init__(self, **kwargs):
            self.dbversion = 'synthetic-v1'
            self.exp_ndf = 3
            self.calls = 0
        def readexpinput(self, path):
            assert path == 'synthetic.list'
        def readuserinput(self, xml):
            assert '<lilithinput>' in xml
        def computelikelihood(self):
            self.calls += 1
            self.l = 8. if self.calls == 1 else 5.
    raw = worker.evaluate(req, SimpleNamespace(Lilith=Engine))
    assert raw['minus2_log_likelihood'] == 8.
    assert raw['sm_reference']['minus2_log_likelihood'] == 5.


def test_sector_validator_dependency():
    try:
        importlib.import_module('ravel.physics.higgstools_bridge')
    except ImportError:
        pytest.xfail('awaits the sector-bundle validator')
    with pytest.raises(ValueError, match='invalid higgs-sector'):
        bridge().build_request(bundle(), bundle(), database(), mapping())


@pytest.fixture
def pinned_envelope(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'ravel.physics.higgstools_bridge',
                        SimpleNamespace(validate_bundle=lambda x: x))
    def pin(path):
        return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    def doc(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return pin(path)
    python = tmp_path / '.venv-lilith/bin/python'
    python.parent.mkdir(parents=True)
    python.write_text('inert dedicated interpreter fixture')
    python.chmod(0o700)
    source = tmp_path / 'engine-source.py'
    source.write_text('synthetic source bytes')
    member = tmp_path / 'measurements.xml'
    member.write_text('<synthetic/>')
    list_file = tmp_path / 'database.list'
    list_file.write_text('measurements.xml\n')
    db = database()
    db.update(sha256=pin(list_file)['sha256'], list_file=pin(list_file),
              files=[pin(list_file), pin(member)])
    doctor = {'groups': [{'group': 'lilith', 'checks': [
        {'id': 'lilith-python', 'status': 'ready', 'found': 'synthetic-version'},
        {'id': 'lilith-database', 'status': 'ready', 'found': db['sha256']}]}]}
    envelope = {'schema_version': 1, 'operation': 'higgs-lilith', 'bundle': doc('sector.json', bundle()),
                'sm_bundle': doc('reference.json', bundle()), 'database': doc('db.json', db),
                'doctor_report': doc('doctor.json', doctor), 'mapping': mapping(),
                'runtime': {'python': pin(python), 'version': 'synthetic-version', 'files': [pin(source)]},
                'max_seconds': 60, 'max_ram_mib': 512}
    input_path = tmp_path / 'input.json'
    input_path.write_text(json.dumps(envelope))
    task = {'input': str(input_path)}
    return task, python, member


@pytest.mark.parametrize('missing', ['list_file', 'files'])
def test_database_inventory_pins_required(tmp_path, pinned_envelope, missing):
    task = pinned_envelope[0]
    envelope = json.loads(Path(task['input']).read_text())
    db_path = Path(envelope['database']['path'])
    db = json.loads(db_path.read_text())
    del db[missing]
    db_path.write_text(json.dumps(db))
    envelope['database']['sha256'] = hashlib.sha256(db_path.read_bytes()).hexdigest()
    Path(task['input']).write_text(json.dumps(envelope))
    with pytest.raises(ValueError, match='database'):
        bridge().inputs(task, tmp_path)


def test_interpreter_and_input_pins(tmp_path, pinned_envelope):
    task, python, member = pinned_envelope
    assert python in bridge().inputs(task, tmp_path)
    assert bridge().execution_seconds(task, tmp_path) == 65
    member.write_text('<changed/>')
    with pytest.raises(ValueError, match='bound input changed'):
        bridge().inputs(task, tmp_path)


def test_admitted_adapter_uses_bounded_launcher(tmp_path, pinned_envelope, monkeypatch):
    from ravel.physics import reinterpret_db
    task, python, member = pinned_envelope
    out = tmp_path / 'outputs'
    out.mkdir()
    monkeypatch.setattr(bridge(), '_approved', lambda task, output: (
        tmp_path, {'max_seconds': 65}, {'child_identity': 'synthetic-process', 'fingerprint': 'synthetic-binding'}))
    calls = []
    fake = Path(__file__).parents[1] / 'fixtures/higgs/lilith/fake_worker.py'
    def launch(command, output, resources):
        calls.append(command)
        assert command[:3] == [str(python), '-B', str(bridge().WORKER)]
        assert resources['max_seconds'] == 60
        subprocess.run([sys.executable, '-B', str(fake), *command[-2:]], check=True, timeout=10)
    monkeypatch.setattr(reinterpret_db, 'execute_native', launch)
    value = bridge().run(task, tmp_path, out)
    assert len(calls) == 1
    assert value['runtime_version'] == 'synthetic-version'
    assert value['delta_chi2'] == 3.
    assert value['imported_sources']


def test_delegated_receipt_requires_bound_import_census():
    req = request()
    req['delegation'] = {'input_hashes': {'synthetic-source.py': 'a' * 64}}
    raw = raw_response(req)
    with pytest.raises(ValueError, match='census'):
        bridge().finalize_result(raw, req, 'f' * 64)
    raw['imported_sources'] = [{'path': 'other-source.py', 'sha256': 'a' * 64}]
    with pytest.raises(ValueError, match='unbound'):
        bridge().finalize_result(raw, req, 'f' * 64)


def test_worker_entrypoint_with_synthetic_engine(tmp_path, monkeypatch):
    from types import SimpleNamespace
    worker = importlib.import_module('ravel.physics.lilith_worker')
    req = request()
    req['database_list'] = 'synthetic.list'
    req['runtime_version'] = 'synthetic-version'
    engine_source = tmp_path / 'synthetic-source.py'
    engine_source.write_text('synthetic source bytes')
    source_sha = hashlib.sha256(engine_source.read_bytes()).hexdigest()
    req['delegation'] = {'input_hashes': {str(engine_source): source_sha}}
    class Engine:
        def __init__(self, **kwargs):
            self.dbversion = 'synthetic-v1'
            self.exp_ndf = 3
            self.calls = 0
        def readexpinput(self, path):
            pass
        def readuserinput(self, xml):
            pass
        def computelikelihood(self):
            self.calls += 1
            self.l = 8. if self.calls == 1 else 5.
    monkeypatch.setitem(sys.modules, 'lilith', SimpleNamespace(
        Lilith=Engine, __version__='synthetic-version'))
    monkeypatch.setattr(worker, 'delegated_parent', lambda request, response: request['delegation'])
    monkeypatch.setattr(worker, 'imported_sources', lambda d: [
        {'path': str(engine_source), 'sha256': source_sha}])
    source, output = tmp_path / 'request.json', tmp_path / 'response.json'
    source.write_text(json.dumps(req))
    assert worker.main([str(source), str(output)]) == 0
    value = bridge().finalize_result(json.loads(output.read_text()), req,
                                     hashlib.sha256(source.read_bytes()).hexdigest())
    assert value['delta_chi2'] == 3.
