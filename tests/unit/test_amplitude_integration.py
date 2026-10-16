"""Amplitude add-on integration through a stubbed execution backend into a Gram store."""
from contextlib import contextmanager
import hashlib
import sys
import json
from pathlib import Path

import numpy as np
import pytest

from amplitude_fixtures import CONSTANTS, point_with_pair_pt, program_output
from ravel.physics import amplitude_basis as ab
from ravel.physics import amplitude_integration as ai
from ravel.physics import amplitude_predictions as ap
from ravel.physics import amplitude_records as ar
from ravel.physics import amplitude_store as store
from ravel.physics import spin0_amplitudes as sp
from ravel import addons

CARD = """[general]
nproc = 131
part = lo
[integration]
seed = 0
usesobol = .false.
"""


class FakeBackend:
    """Runs the 'program' synchronously in the stage directory; records every spec."""

    def __init__(self, fail_stage=None, corrupt_stage=None, higgs=None, exclude=(), leak=(), cuts=None, draws=None, small=()):
        self.specs, self.fail_stage, self.corrupt_stage, self.higgs = [], fail_stage, corrupt_stage, higgs
        self.exclude, self.leak, self.cuts, self.draws, self.small = exclude, leak, cuts, draws, small
        self.leases = 0

    def prepare(self, spec, *, base=None):
        self.specs.append(spec)
        return {'spec': spec, 'plan_sha256': hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
                'backend': {'local': True}}

    @contextmanager
    def capacity(self, plan, holder, **kwargs):
        self.leases += 1
        yield

    def submit(self, plan, attempt_dir):
        spec = plan['spec']
        if spec['stage'] == self.fail_stage:
            raise KeyboardInterrupt
        stage_dir = Path(spec['inputs'][0]['path']).parent
        op, draws, seed, channel = map(int, (stage_dir / 'ravel-control.dat').read_text().split())
        card_seed = [l for l in (stage_dir / 'input.ini').read_text().splitlines() if l.startswith('seed')]
        assert card_seed == [f'seed = {seed}']
        reject = (2,) if op == 2 and not self.draws else ()
        raw = program_output(op, draws, seed, channel, reject=reject, corrupt=spec['stage'] == self.corrupt_stage,
                             higgs=self.higgs, exclude=self.exclude if op else (), leak=self.leak if op == 2 else (),
                             cuts=self.cuts, small=self.small if op == 2 else (),
                             **(self.draws(op, draws, seed) if self.draws else {}))
        (stage_dir / 'amplitudes.dat').write_bytes(raw)
        if op == 1:
            (stage_dir / 'proposal-grid.bin').write_bytes(b'grid-' + str(seed).encode())
        Path(attempt_dir).mkdir(parents=True)
        return {'stage': spec['stage']}

    def observe(self, plan, handle):
        return {'state': 'succeeded', 'exit_code': 0}

    def cancel(self, plan, handle):
        return {'state': 'cancelled'}

    def fetch(self, plan, handle, base):
        return {'outputs': [o['destination'] for o in plan['spec']['outputs']]}


def _document(tmp_path, **changes):
    (tmp_path / 'mixed.ini').write_text(CARD)
    (tmp_path / 'same.ini').write_text(CARD.replace('nproc = 131', 'nproc = 131 '))
    pin = lambda name: {'path': name, 'sha256': hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}
    doc = {'schema_version': 1, 'kind': 'amplitude-integration', 'addon': 'mcfm-amplitudes', 'operation': 'blocks',
           'store': 'store',
           'backend': {'kind': 'oci-local', 'program': '/opt/mcfm/ravel_mcfm_amplitudes', 'workdir': '/work',
                       'resources': {'cpus': 1, 'memory_mib': 2048}},
           'cohorts': [{'id': 'mixed', 'channel': 1, 'card': pin('mixed.ini'), 'warmup': {'draws': 3, 'seed': 11, 'max_seconds': 60}},
                       {'id': 'same', 'channel': 2, 'card': pin('same.ini'), 'warmup': {'draws': 3, 'seed': 12, 'max_seconds': 60}}],
           'schedule': {'schema_version': 1, 'max_operation_seconds': 1000, 'blocks': [
               {'id': f'{c}-{i}', 'cohort': c, 'seed': 20 + 2 * i + (c == 'same'), 'draws': 5, 'max_seconds': 100}
               for i in range(2) for c in ('mixed', 'same')]},
           'audit_points': 2, 'safety_cuts': ['z-candidate-pt', 'small-invariants']}
    doc.update(changes)
    (tmp_path / 'doc.json').write_text(json.dumps(doc))
    return {'input': str(tmp_path / 'doc.json')}


@pytest.fixture(autouse=True)
def _checkout_addon(monkeypatch):
    monkeypatch.delenv('RAVEL_ADDON_PATH', raising=False)
    monkeypatch.delenv('RAVEL_NATIVE_BUILD', raising=False)


def test_card_seed_is_the_only_change():
    out = ai.card_with_seed(CARD, 77)
    assert out.splitlines() == [l if not l.startswith('seed') else 'seed = 77' for l in CARD.splitlines()]
    with pytest.raises(ValueError, match='seed'):
        ai.card_with_seed('[integration]\nusesobol = .false.\n', 1)
    with pytest.raises(ValueError, match='seed'):
        ai.card_with_seed('[integration]\nseed = 1\nseed = 2\n', 1)


@pytest.mark.usefixtures('in_process_backend_seam')
def test_blocks_run_only_through_the_backend_and_fill_a_complete_store(tmp_path):
    backend = FakeBackend()
    result = ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=backend)
    assert result['status'] == 'passed' and result['store_status'] == 'complete' and result['physics_validated'] is False
    stages = [s['stage'] for s in backend.specs]
    assert stages == ['warmup-mixed', 'warmup-same', 'mixed-0', 'same-0', 'mixed-1', 'same-1']
    spec = backend.specs[2]
    assert spec['argv'] == ['/opt/mcfm/ravel_mcfm_amplitudes', 'input.ini']
    assert spec['resources'] == {'cpus': 1, 'memory_mib': 2048, 'wall_seconds': 100}
    assert {i['mount'] for i in spec['inputs']} == {'/work/input.ini', '/work/ravel-control.dat', '/work/proposal-grid.bin'}
    assert spec['outputs'] == [{'name': 'amplitudes.dat', 'destination': 'stages/mixed-0/amplitudes.dat'}]
    assert backend.leases == 6
    manifest = store.load_manifest(tmp_path / 'store')
    assert [b['summary']['attempted'] for b in manifest['blocks']] == [5] * 4
    assert [b['summary']['rejected'] for b in manifest['blocks']] == [1] * 4
    block = store.read_block(tmp_path / 'store' / manifest['blocks'][1]['path'])
    assert block['header']['particles']['pdg'] == [21, 21, 11, -11, 11, -11]
    assert block['header']['basis'] == ['continuum', 'scalar_bottom', 'scalar_top']
    assert len(store.read_audit(tmp_path / 'store' / manifest['blocks'][0]['path'])['points']) == 2


@pytest.mark.usefixtures('in_process_backend_seam')
def test_reference_hypothesis_reproduces_the_program_squares(tmp_path):
    ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=FakeBackend())
    manifest = store.load_manifest(tmp_path / 'store')
    reference = {'id': 'SM', 'constant': {'continuum': 1}, 'states': [
        {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar_bottom': 1, 'scalar_top': 1}}]}
    basis = ab.Basis(manifest['header']['basis'])
    for row in manifest['blocks']:
        block = store.read_block(tmp_path / 'store' / row['path'])
        cohort = row['cohort']
        raw = program_output(2, 5, row['seed'], 1 if cohort == 'mixed' else 2, reject=(2,))
        parsed = ar.parse(raw, operation=2, draws=5, seed=row['seed'], channel=1 if cohort == 'mixed' else 2,
                          protocol=addons.resolve('mcfm-amplitudes').manifest['protocol'])
        weights = ab.evaluate(block['gram'], ab.coefficients(reference, basis, block['observables'][:, 0]))
        np.testing.assert_allclose(weights, parsed['meta'][:, 6], rtol=1e-10)


@pytest.mark.usefixtures('in_process_backend_seam')
def test_interrupted_operation_resumes_without_repeating_warmups(tmp_path):
    task = _document(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        ai.run(task, tmp_path, tmp_path / 'out', backend=FakeBackend(fail_stage='mixed-1'))
    partial = store.load_manifest(tmp_path / 'store')
    assert partial['status'] == 'incomplete' and [b['id'] for b in partial['blocks']] == ['mixed-0', 'same-0']
    backend = FakeBackend()
    result = ai.run(task, tmp_path, tmp_path / 'out2', backend=backend)
    assert [s['stage'] for s in backend.specs] == ['mixed-1', 'same-1']
    assert result['store_status'] == 'complete'


@pytest.mark.usefixtures('in_process_backend_seam')
def test_block_that_differs_from_the_program_oracle_is_not_stored(tmp_path):
    with pytest.raises(ValueError, match='squared amplitudes'):
        ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=FakeBackend(corrupt_stage='same-0'))
    assert [b['id'] for b in store.load_manifest(tmp_path / 'store')['blocks']] == ['mixed-0']


@pytest.mark.usefixtures('in_process_backend_seam')
def test_predictions_from_an_integrated_store(tmp_path):
    ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=FakeBackend())
    hyp = {'id': 'SM', 'constant': {'continuum': 1}, 'states': [
        {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar_bottom': 1, 'scalar_top': 1}}]}
    heavy = json.loads(json.dumps(hyp))
    heavy['id'] = 'S500'
    heavy['states'].append({'mass_gev': 500.0, 'width_gev': 50.0, 'propagator': 'fixed-width', 'couplings': {'scalar_top': 0.3}})
    doc = {'schema_version': 1, 'kind': 'amplitude-predictions', 'store': 'store', 'hypotheses': [hyp, heavy],
           'reference': 'SM', 'reference_description': 'reference', 'selection': [],
           'observable': {'name': 'mass_gev', 'label': 'Four-lepton invariant mass', 'unit': 'GeV', 'invariant': 's_gev2'},
           'binning': {'edges': [0.0, 200.0, 400.0, 2000.0]}, 'normalization': {'unit': 'fb', 'representation': 'integrated'}}
    (tmp_path / 'pred.json').write_text(json.dumps(doc))
    result = ap.run({'input': str(tmp_path / 'pred.json')}, tmp_path, tmp_path / 'pred')
    assert result['status'] == 'passed'


@pytest.mark.usefixtures('in_process_backend_seam')
def test_point_oracle_operation(tmp_path):
    points = {'convention': 'all-outgoing (px, py, pz, E) in GeV',
              'points': [{'momenta': [[0, 0, -1, -1]] * 6, 'direct_pairing': True}] * 3}
    (tmp_path / 'points.json').write_text(json.dumps(points))
    task = _document(tmp_path, operation='point-oracle', oracle={
        'cohort': 'same', 'seed': 5, 'max_seconds': 30,
        'points': {'path': 'points.json', 'sha256': hashlib.sha256((tmp_path / 'points.json').read_bytes()).hexdigest()}})
    backend = FakeBackend()
    result = ai.run(task, tmp_path, tmp_path / 'out', backend=backend)
    assert result['status'] == 'passed' and result['points'] == 3
    assert (tmp_path / 'store/stages/oracle-same/ravel-points.dat').read_text().count('\n') == 21


@pytest.mark.usefixtures('in_process_backend_seam')
def test_spin0_members_join_after_closure_with_the_program_amplitudes(tmp_path):
    members = [{'id': 'top-even', 'quark_mass_gev': 173.0, 'production': 'even', 'decay': 'g1'},
               {'id': 'top-odd', 'quark_mass_gev': 173.0, 'production': 'odd', 'decay': 'g4'}]
    phases = np.exp(1j * np.linspace(0.1, 2.0, 16)) * 3.0

    def higgs(p):
        d = sp.amplitudes(p[None], members[:1], CONSTANTS)[0, :, 0] * phases
        w = sp.amplitudes(p[None, [0, 1, 2, 5, 4, 3]], members[:1], CONSTANTS)[0, :, 0] * phases
        return d, w
    spin0 = {'members': members, 'constants': CONSTANTS,
             'closure': {'members': ['top-even'], 'program_members': ['scalar_bottom', 'scalar_top'], 'rtol': 1e-8}}
    result = ai.run(_document(tmp_path, spin0=spin0), tmp_path, tmp_path / 'out', backend=FakeBackend(higgs=higgs))
    assert result['store_status'] == 'complete' and all(c['passed'] for c in result['closures'])
    manifest = store.load_manifest(tmp_path / 'store')
    assert manifest['header']['basis'] == ['continuum', 'scalar_bottom', 'scalar_top', 'top-even', 'top-odd']
    path = tmp_path / 'store' / manifest['blocks'][0]['path']
    audit = store.read_audit(path)['amplitudes']
    # The aligned CP-even member equals the program's scalar numerator exactly.
    np.testing.assert_allclose(audit[:, 0, :, 3], audit[:, 0, :, 2], rtol=1e-8, atol=1e-14)


def test_unknown_channel_and_addon_are_refused(tmp_path):
    task = _document(tmp_path)
    doc = json.loads(Path(task['input']).read_text())
    doc['cohorts'][0]['channel'] = 9
    Path(task['input']).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='channel'):
        ai.load(task, tmp_path)
    doc['cohorts'][0]['channel'] = 1
    doc['addon'] = 'not-installed'
    Path(task['input']).write_text(json.dumps(doc))
    with pytest.raises(addons.AddonNotFound):
        ai.load(task, tmp_path)


def test_record_census_errors():
    protocol = addons.resolve('mcfm-amplitudes').manifest['protocol']
    raw = program_output(2, 3, 7, 1, reject=(2,))
    parsed = ar.parse(raw, operation=2, draws=3, seed=7, channel=1, protocol=protocol)
    assert parsed['summary']['accepted'] == 2 and len(parsed['meta']) == 2
    with pytest.raises(ValueError, match='control'):
        ar.parse(raw, operation=2, draws=3, seed=8, channel=1, protocol=protocol)
    with pytest.raises(ValueError, match='COMPLETE'):
        ar.parse(raw.rsplit(b' COMPLETE', 1)[0], operation=2, draws=3, seed=7, channel=1, protocol=protocol)
    lines = raw.decode().splitlines()
    swapped = [l for l in lines if not l.startswith(' A 2 6 2 2 2 2')]
    with pytest.raises(ValueError):
        ar.parse(('\n'.join(swapped) + '\n').encode(), operation=2, draws=3, seed=7, channel=1, protocol=protocol)
    # An exclusion must carry exactly the excluded weight its cut declares.
    raw = program_output(2, 3, 7, 1, small=(2,))
    assert ar.parse(raw, operation=2, draws=3, seed=7, channel=1, protocol=protocol)['summary']['excluded'] == 1
    claimed = raw.replace(b' EXCLUDE 2 2 0 0', b' EXCLUDE 2 2 0 1')
    with pytest.raises(ValueError, match='excluded weight its cut declares'):
        ar.parse(claimed, operation=2, draws=3, seed=7, channel=1, protocol=protocol)


def _amplitude_spec(store, seed='1'):
    (store / 'stages/warmup-c1').mkdir(parents=True, exist_ok=True)
    card = store / 'stages/warmup-c1/input.ini'
    card.write_text(f'seed = {seed}\n')
    return {'schema_version': 1, 'backend': 'native', 'stage': 'warmup-c1',
            'argv': [sys.executable, '-c', 'import os;open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"amplitudes.dat"),"w").write("1 2\\n")'],
            'inputs': [{'path': str(card)}],
            'outputs': [{'name': 'amplitudes.dat', 'destination': 'stages/warmup-c1/amplitudes.dat'}],
            'resources': {'cpus': 1, 'memory_mib': 128, 'wall_seconds': 60}}


def test_native_amplitude_stage_refuses_outside_an_approved_stage(tmp_path, monkeypatch):
    """No approval, no native job: drive_stage from a bare directory starts nothing."""
    from ravel.physics import backend_driver
    from ravel.workflow import execution_backend as eb, machine_lease
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.delenv(machine_lease.ENV, raising=False)
    eb._INSTANCES.clear()
    store = tmp_path / 'store'
    with pytest.raises(ValueError, match='approved supervised stage'):
        backend_driver.drive_stage(_amplitude_spec(store), store, poll=0.1)
    with pytest.raises(ValueError, match='approved supervised stage'):
        backend_driver.drive(_amplitude_spec(store), store / 'attempt', store, poll=0.1)
    assert not (store / 'logs/execution').exists() and not list(store.rglob('launcher.json'))


DRIVER = ('import json,sys\n'
          'from ravel.physics import backend_driver\n'
          'receipt = backend_driver.drive_stage(json.load(open(sys.argv[1])), sys.argv[2], poll=0.1)\n'
          'print(json.dumps({"plan": receipt["plan"]}))\n')


def test_native_amplitude_stage_runs_nested_in_an_approved_stage(tmp_path, monkeypatch):
    """The scientific worker of an approved stage drives the amplitude stage under its own job's lease."""
    from ravel.workflow import execution, execution_backend as eb, machine_lease, stage_supervisor
    from ravel.workflow.state_io import atomic_json
    from test_checkin2_gate import _run
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    monkeypatch.delenv(machine_lease.ENV, raising=False)
    eb._INSTANCES.clear()
    root = _run(tmp_path, plan='smoke', checkin2=False)
    store = tmp_path / 'store'

    def outer(stage, seed):
        spec_file = tmp_path / f'{stage}-spec.json'
        atomic_json(spec_file, _amplitude_spec(store, seed))
        return stage_supervisor.supervise(stage, root, 10, f'logs/{stage}.log',
                                          [sys.executable, '-c', DRIVER, str(spec_file), str(store)],
                                          kill_secs=120.0, poll=0.1, grace=3.0, inputs=[str(spec_file)],
                                          required_plan='smoke')
    assert outer('amplitudes', '1') == 0, (root / 'logs/amplitudes.log').read_text()
    assert (store / 'stages/warmup-c1/amplitudes.dat').read_text() == '1 2\n'
    record = execution.load_execution(store)['stages']['warmup-c1']
    assert record['status'] == 'succeeded' and record['parent_authority']['stage'] == 'amplitudes'
    assert str(store / 'backend-plans/warmup-c1.json') in record['inputs']
    # A changed amplitude stage under the same name is a changed study.
    assert outer('amplitudes-again', '2') != 0
    assert 'changed study' in (root / 'logs/amplitudes-again.log').read_text()
    assert machine_lease.holder() is None


def test_run_stage_uses_the_supervised_driver_without_a_double(monkeypatch):
    from ravel.physics import amplitude_integration as ai, backend_driver
    seen = []
    monkeypatch.setattr(backend_driver, 'drive_stage', lambda spec, store: seen.append(spec['stage']) or (_ for _ in ()).throw(RuntimeError('stop')))
    monkeypatch.setattr(ai, '_prepare_stage', lambda *a, **k: (Path('/nonexistent'), []))
    monkeypatch.setattr(ai, '_stage_spec', lambda ctx, name, *a: {'stage': name})
    with pytest.raises(RuntimeError, match='stop'):
        ai.run_stage({'protocol': {}, 'store': Path('/nonexistent')}, 'warmup-c1', {}, 'w', 1, 1, 1)
    assert seen == ['warmup-c1']


def test_a_new_child_plan_must_derive_from_the_store_or_the_approved_inputs(tmp_path, monkeypatch):
    """drive_stage admits a child plan only when every input lies in the store or is a pinned input of the
    approving stage, and its wall time fits the approved ceiling; a refused plan is never pinned."""
    from ravel.physics import backend_driver
    from ravel.workflow import execution, execution_backend as eb, stage_supervisor
    eb._INSTANCES.clear()
    pinned = tmp_path / 'approved-card.ini'
    pinned.write_text('seed = 1\n')
    monkeypatch.setattr(backend_driver, 'calling_authority', lambda: {
        'rundir': str(tmp_path / 'run'), 'stage': 'amplitudes', 'attempt_id': 'a1', 'max_seconds': 100})
    monkeypatch.setattr(execution, 'load_execution', lambda rundir: {'stages': {'amplitudes': {
        'input_snapshot': {str(pinned.resolve()): {'kind': 'file'}}}}})
    launched = []
    monkeypatch.setattr(stage_supervisor, 'supervise', lambda *a, **k: launched.append(a[0]) or 1)
    store = tmp_path / 'store'
    outside = tmp_path / 'elsewhere.ini'
    outside.write_text('seed = 9\n')
    spec = _amplitude_spec(store)
    spec['inputs'].append({'path': str(outside)})
    with pytest.raises(ValueError, match='approved inputs'):
        backend_driver.drive_stage(spec, store)
    spec = _amplitude_spec(store)
    spec['resources']['wall_seconds'] = 101
    with pytest.raises(ValueError, match='ceiling'):
        backend_driver.drive_stage(spec, store)
    assert launched == [] and not list((store / 'backend-plans').glob('*.json'))
    spec = _amplitude_spec(store)
    spec['inputs'].append({'path': str(pinned)})
    with pytest.raises(backend_driver.StageFailed):
        backend_driver.drive_stage(spec, store)  # admitted: the (stubbed) supervisor runs it
    assert launched == ['warmup-c1']


def test_a_submission_that_failed_after_recording_an_identity_is_cancelled(tmp_path, in_process_backend_seam):
    from types import SimpleNamespace
    from ravel.physics import backend_driver
    calls = []

    def submit(plan, attempt_dir):
        Path(attempt_dir).mkdir(parents=True)
        (Path(attempt_dir) / 'handle.json').write_text(json.dumps({'remote': {'pid': 1}}))
        raise OSError('lost the connection after the job started')
    fake = SimpleNamespace(
        HANDLE_NAME='handle.json', prepare=lambda spec, base: {'plan_sha256': 'p', 'spec': spec}, submit=submit,
        read_handle=lambda attempt: json.loads((Path(attempt) / 'handle.json').read_text()),
        cancel=lambda plan, handle: calls.append(handle['remote']))
    spec = {'stage': 's', 'resources': {'wall_seconds': 1}}
    with pytest.raises(OSError, match='lost the connection'):
        backend_driver.drive(spec, tmp_path / 'attempt', tmp_path, backend=fake)
    assert calls == [{'pid': 1}]


def _installed(tmp_path, monkeypatch):
    prefix = tmp_path / 'native'
    build = prefix / 'tools/mcfm-build'; build.mkdir(parents=True)
    program = build / 'ravel_mcfm_amplitudes'; program.write_text('fictional program')
    receipt = build / 'build-receipt.json'; receipt.write_text('{}')
    launcher = prefix / 'containers/mcfm-amplitudes-launcher.json'; launcher.parent.mkdir()
    launcher.write_text('{}')
    record = {'schema_version': 1, 'kind': 'ravel-amplitude-installation', 'group': 'mcfm-amplitudes',
              'image': {'id': 'sha256:' + 'b' * 64, 'platform': 'linux/amd64', 'emulation': True},
              'program': str(program), 'program_sha256': hashlib.sha256(program.read_bytes()).hexdigest(),
              'readonly_trees': [{'path': str(p), 'mount': str(p)} for p in (build, prefix / 'source', prefix / 'overlay', prefix / 'pdf')],
              'build_receipt': str(receipt), 'build_receipt_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest(),
              'launcher': str(launcher), 'site': {'client': str(prefix / 'inert-client'), 'connection': 'ravel', 'network': 'none'},
              'env': {'LHAPDF_DATA_PATH': str(prefix / 'pdf')}}
    path = prefix / 'installations/mcfm-amplitudes.json'; path.parent.mkdir()
    path.write_text(json.dumps(record))
    monkeypatch.setenv('RAVEL_NATIVE_BUILD', str(prefix))
    return path, record


def test_installation_defaults_preserve_explicit_fields_and_pin_record(tmp_path, monkeypatch):
    path, record = _installed(tmp_path, monkeypatch)
    task = _document(tmp_path, backend={'kind': 'oci-local', 'resources': {'cpus': 1, 'memory_mib': 1024}})
    ctx = ai.load(task, tmp_path)
    assert ctx['doc']['backend']['program'] == record['program']
    assert ctx['doc']['backend']['image'] == record['image']
    assert ctx['doc']['backend']['readonly_trees'] == record['readonly_trees']
    assert path in ai.inputs(task, tmp_path)
    before = ai._stage_spec(ctx, 'fictional', tmp_path / 'store/stages/fictional', ['input.ini'], ['out'], 60)
    pin = next(i for i in before['inputs'] if i['path'] == str(path))
    assert pin['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    from ravel.workflow import execution_backend
    execution_backend.validate_spec(before)
    from ravel.workflow.backends.oci_local import OciLocalBackend
    OciLocalBackend().validate(before)
    doc = json.loads(Path(task['input']).read_text()); doc['backend']['program'] = '/fictional/own'
    doc['backend']['image'] = {'id': 'sha256:' + 'c' * 64, 'platform': 'linux/amd64'}
    Path(task['input']).write_text(json.dumps(doc))
    changed = ai.load(task, tmp_path)['doc']['backend']
    assert changed['program'] == '/fictional/own' and changed['image']['id'] == 'sha256:' + 'c' * 64
    record['env']['LHAPDF_DATA_PATH'] = '/fictional/new-pdf'; path.write_text(json.dumps(record))
    after = ai._stage_spec(ai.load(task, tmp_path), 'fictional', tmp_path / 'store/stages/fictional', ['input.ini'], ['out'], 60)
    assert pin != next(i for i in after['inputs'] if i['path'] == str(path))
    with pytest.raises(ValueError, match='changed'):
        ai._stage_spec(ctx, 'fictional', tmp_path / 'store/stages/fictional', ['input.ini'], ['out'], 60)


def test_example_checks_with_installed_program(tmp_path, monkeypatch):
    import copy
    from ravel.physics import amplitude_cli
    _installed(tmp_path, monkeypatch)
    example = copy.deepcopy(amplitude_cli.EXAMPLES['amplitude-integration'])
    assert 'program' not in example['backend'] and 'image' not in example['backend']
    (tmp_path / 'mixed.ini').write_text(CARD)
    example['cohorts'][0]['card']['sha256'] = hashlib.sha256((tmp_path / 'mixed.ini').read_bytes()).hexdigest()
    path = tmp_path / 'example.json'; path.write_text(json.dumps(example))
    assert amplitude_cli.check('amplitude-integration', path)['status'] == 'checked'


def test_installation_changed_receipt_is_refused(tmp_path, monkeypatch):
    path, record = _installed(tmp_path, monkeypatch)
    task = _document(tmp_path, backend={'kind': 'oci-local', 'resources': {'cpus': 1, 'memory_mib': 1024}})
    Path(record['build_receipt']).write_text('{"changed":true}')
    with pytest.raises(ValueError, match='receipt'):
        ai.load(task, tmp_path)


def test_complete_explicit_backend_does_not_depend_on_installed_runtime(tmp_path, monkeypatch):
    path, record = _installed(tmp_path, monkeypatch)
    Path(record['build_receipt']).unlink()
    backend = {'kind': 'oci-local', 'program': '/fictional/own', 'resources': {'cpus': 1, 'memory_mib': 1024},
               'image': {'id': 'sha256:' + 'c' * 64, 'platform': 'linux/amd64'}, 'readonly_trees': []}
    task = _document(tmp_path, backend=backend)
    assert ai.load(task, tmp_path)['doc']['backend'] == backend
    assert path not in ai.inputs(task, tmp_path)


def test_native_installation_fills_program_and_passes_the_card_in_place(tmp_path, monkeypatch):
    path, record = _installed(tmp_path, monkeypatch)
    oci_record = dict(record)
    native = {k: v for k, v in record.items() if k not in ('image', 'site')}
    native['launcher'] = {'kind': 'native', 'toolchain': '/fictional/toolchain/bin'}
    data = Path(native['program']).parent / 'process.DAT'; data.write_text('fictional process table')
    native['runtime_files'] = [{'path': str(data), 'sha256': hashlib.sha256(data.read_bytes()).hexdigest()}]
    Path(native['program']).chmod(0o755)
    path.write_text(json.dumps(native))
    task = _document(tmp_path, backend={'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 1024}})
    ctx = ai.load(task, tmp_path)
    backend = ctx['doc']['backend']
    assert backend['program'] == native['program'] and backend['env'] == native['env']
    assert 'image' not in backend and 'readonly_trees' not in backend and 'workdir' not in backend
    stage = tmp_path / 'store/stages/fictional'
    spec = ai._stage_spec(ctx, 'fictional', stage, ['input.ini'], ['out'], 60)
    # The program finds its control, points and grid files next to the card it is given.
    assert spec['argv'] == [native['program'], str(stage / 'input.ini')]
    assert any(i['path'] == str(path) for i in spec['inputs'])
    from ravel.workflow import execution_backend
    execution_backend.validate_spec(spec)
    from ravel.workflow.backends.native import NativeBackend
    NativeBackend().validate(spec)
    assert data in ai.inputs(task, tmp_path)
    cohort = next(iter(ctx['cohorts'].values()))
    stage_dir, files = ai._prepare_stage(ctx, 'copies', cohort, 1, 10, 3)
    assert 'process.DAT' in files and (stage_dir / 'process.DAT').read_text() == 'fictional process table'
    data.write_text('changed')
    with pytest.raises(ValueError, match='runtime file .* changed'):
        ai._prepare_stage(ctx, 'copies', cohort, 1, 10, 3)
    oci_task = _document(tmp_path, backend={'kind': 'oci-local', 'resources': {'cpus': 1, 'memory_mib': 1024}})
    with pytest.raises(ValueError, match='built for the native backend'):
        ai.load(oci_task, tmp_path)
    path.write_text(json.dumps(oci_record))
    task = _document(tmp_path, backend={'kind': 'native', 'resources': {'cpus': 1, 'memory_mib': 1024}})
    with pytest.raises(ValueError, match='built for the oci-local backend'):
        ai.load(task, tmp_path)


# ---------------------------------------------------------------- declared safety cuts
def _pair_pts(momenta, identical):
    pairs = [(3, 4), (5, 6)] + ([(3, 6), (5, 4)] if identical else [])
    return np.array([[np.hypot(*(p[i - 1, :2] + p[j - 1, :2])) for i, j in pairs] for p in momenta])


def _invariants(momenta):
    out = []
    for p in momenta:
        dot = lambda i, j: p[i - 1, 3] * p[j - 1, 3] - p[i - 1, :3] @ p[j - 1, :3]
        values = [abs(p[j - 1, 3]) / 100 for j in (3, 4, 5, 6)]
        values += [abs(dot(j, k) / p[j - 1, 3] / p[k - 1, 3]) for j in (3, 4, 5, 6) for k in (1, 2, 3, 4, 5, 6) if k > j or k < 3]
        out.append(min(values))
    return np.array(out)


@pytest.mark.usefixtures('in_process_backend_seam')
def test_draws_below_a_declared_cut_are_excluded_at_sampling_and_measured(tmp_path):
    backend = FakeBackend(exclude=(3,), small=(5,))
    result = ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=backend)
    manifest = store.load_manifest(tmp_path / 'store')
    declared = addons.resolve('mcfm-amplitudes').manifest['protocol']['safety_cuts']
    assert manifest['header']['safety_cuts'] == declared and result['safety']['cuts'] == declared
    for row in manifest['blocks']:
        s = row['summary']
        # Draw 2 is rejected; draw 3 (low Z pT, measured weight) and draw 5 (collinear leptons, unmeasured
        # weight) are excluded: all stay in the exposure, none is stored.
        assert (s['attempted'], s['accepted'], s['rejected'], s['excluded']) == (5, 2, 1, 2) and row['points'] == 2
        assert s['safety']['by_cut'] == {'z-candidate-pt': 1, 'small-invariants': 1} and s['safety']['weight_unmeasured'] == 1
        assert s['safety']['exposure_fraction'] == 2 / 5 and 0 < s['safety']['weight_fraction'] < 1
        block = store.read_block(tmp_path / 'store' / row['path'])
        assert (_pair_pts(block['momenta'], row['cohort'] == 'same') >= 0.1).all()
        assert (_invariants(block['momenta']) >= 1e-9).all()
    total = result['safety']['blocks']
    assert (total['attempted'], total['excluded'], total['stored']) == (20, 8, 8) and total['exposure_fraction'] == 0.4
    assert total['by_cut'] == {'z-candidate-pt': 4, 'small-invariants': 4} and total['weight_unmeasured'] == 4
    assert total['weight_fraction'] == pytest.approx(
        sum(r['summary']['safety']['weight_excluded'] for r in manifest['blocks'])
        / sum(r['summary']['safety']['weight_excluded'] + r['summary']['safety']['weight_stored'] for r in manifest['blocks']))
    assert [a['id'] for a in result['assumptions']] == ['safety-cut:z-candidate-pt', 'safety-cut:small-invariants']
    assert all('restricted phase space' in a['statement'] for a in result['assumptions'])
    assert 'unmeasured' in result['assumptions'][1]['statement']
    assert all(w['safety']['census']['excluded'] == 1 for w in result['warmups'])  # three warm-up draws
    assert any('Safety cuts excluded 8 of 20' in line for line in result['summary'])


@pytest.mark.usefixtures('in_process_backend_seam')
def test_a_program_that_stores_a_point_below_its_declared_cut_is_refused(tmp_path):
    with pytest.raises(ValueError, match='declared safety cuts'):
        ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=FakeBackend(leak=(4,)))
    assert store.load_manifest(tmp_path / 'store')['blocks'] == []


@pytest.mark.usefixtures('in_process_backend_seam')
def test_a_cut_the_program_applies_but_does_not_declare_is_refused(tmp_path):
    with pytest.raises(ValueError, match='undeclared cut is refused'):
        ai.run(_document(tmp_path), tmp_path, tmp_path / 'out', backend=FakeBackend(cuts=[('pair_pt_min', 0.2)]))


def test_undeclared_or_unaccepted_cuts_are_refused_at_plan_time(tmp_path):
    backend = FakeBackend()
    both = ['z-candidate-pt', 'small-invariants']
    for cuts, message in ((both + ['lepton-pt'], 'not declared'), (['lepton-pt'], 'not declared'),
                          ([], 'must accept exactly'), (['z-candidate-pt'], 'must accept exactly'),
                          (both + ['z-candidate-pt'], 'must accept exactly')):
        task = _document(tmp_path, safety_cuts=cuts)
        with pytest.raises(ValueError, match=message):
            ai.load(task, tmp_path)
        with pytest.raises(ValueError, match=message):
            ai.run(task, tmp_path, tmp_path / 'out', backend=backend)
    task = _document(tmp_path)
    doc = json.loads(Path(task['input']).read_text())
    doc.pop('safety_cuts')
    Path(task['input']).write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='must accept exactly'):
        ai.load(task, tmp_path)
    assert backend.specs == [] and not (tmp_path / 'store').exists()


def test_a_producer_declaration_is_validated():
    protocol = addons.resolve('mcfm-amplitudes').manifest['protocol']
    cut = protocol['safety_cuts'][0]
    for change in ({'kind': 'lepton_pt_min'}, {'min_gev': 0}, {'pairs': [[3, 3]]}, {'pairs': [[3, 7]]}, {'source': ''},
                   {'excluded_weight': 'assumed'}):
        with pytest.raises(ValueError):
            ar.validate_protocol({**protocol, 'safety_cuts': [{**cut, **change}]})
    small = protocol['safety_cuts'][1]
    for change in ({'minimum': -1.0}, {'particles': [3, 1]}, {'beams': []}, {'reference_energy_gev': 0}, {'min_gev': 0.1}):
        with pytest.raises(ValueError):
            ar.validate_protocol({**protocol, 'safety_cuts': [{**small, **change}]})
    with pytest.raises(ValueError, match='each safety cut needs'):
        ar.validate_protocol({**protocol, 'safety_cuts': [{k: v for k, v in cut.items() if k != 'reason'}]})


@pytest.mark.usefixtures('in_process_backend_seam')
def test_the_restricted_region_integral_is_unbiased(tmp_path):
    """Excluded draws stay in the exposure, so the store's block mean estimates the integral over the admitted region.

    Each draw is uniform in the Z candidate pT u in [0, 1) GeV and carries the integration
    factor f(u) / (N |M|^2), with |M|^2 the program's own square. The stored blocks, read back
    and weighted with the reference hypothesis as every prediction does, then estimate the
    integral of f over u >= 0.1 only. Normalising by the stored points instead would converge
    to a value larger by 1/0.9; the test tells the two apart.
    """
    f = lambda u: 1.0 + 3.0 * u * u
    exact = (1.0 - 0.1) + (1.0 - 0.1 ** 3)
    n, blocks = 150, 20

    def draws(op, count, seed):
        u = np.random.default_rng(seed).uniform(0.0, 1.0, size=count)
        momenta = [point_with_pair_pt(seed * 1000 + i, x) for i, x in enumerate(u)]
        fields = lambda draw, p, square: [1.0 / count, f(u[draw - 1]) / square, 1.0, 1.0, 1.0, 0.1, 0.2, 100.0, 1e4]
        return {'momenta': momenta, 'weights': fields}
    schedule = {'schema_version': 1, 'max_operation_seconds': 10000, 'blocks': [
        {'id': f'mixed-{i}', 'cohort': 'mixed', 'seed': 100 + i, 'draws': n, 'max_seconds': 100} for i in range(blocks)]}
    task = _document(tmp_path, schedule=schedule)
    doc = json.loads(Path(task['input']).read_text()); doc['cohorts'] = doc['cohorts'][:1]
    Path(task['input']).write_text(json.dumps(doc))
    result = ai.run(task, tmp_path, tmp_path / 'out', backend=FakeBackend(draws=draws))
    manifest = store.load_manifest(tmp_path / 'store')
    reference = {'id': 'SM', 'constant': {'continuum': 1}, 'states': [
        {'mass_gev': 125.0, 'width_gev': 0.004, 'propagator': 'fixed-width', 'couplings': {'scalar_bottom': 1, 'scalar_top': 1}}]}
    basis = ab.Basis(manifest['header']['basis'])
    estimates, per_point = [], []
    for row in manifest['blocks']:
        block = store.read_block(tmp_path / 'store' / row['path'])
        w = block['factor'] * ab.evaluate(block['gram'], ab.coefficients(reference, basis, block['observables'][:, 0]))
        assert row['summary']['attempted'] == n == row['points'] + row['summary']['excluded']
        estimates.append(w.sum())
        per_point.append(w.sum() * n / row['points'])
    mean, error = np.mean(estimates), np.std(estimates, ddof=1) / np.sqrt(blocks)
    assert abs(mean - exact) < 4 * error
    assert abs(np.mean(per_point) - exact) > 4 * error
    # The measured excluded share of the draws matches the admitted fraction of the uniform proposal.
    assert result['safety']['blocks']['exposure_fraction'] == pytest.approx(0.1, abs=0.04)
