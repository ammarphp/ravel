"""Amplitude add-on integration through a stubbed execution backend into a Gram store."""
from contextlib import contextmanager
import hashlib
import sys
import json
from pathlib import Path

import numpy as np
import pytest

from amplitude_fixtures import CONSTANTS, program_output
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

    def __init__(self, fail_stage=None, corrupt_stage=None, higgs=None):
        self.specs, self.fail_stage, self.corrupt_stage, self.higgs = [], fail_stage, corrupt_stage, higgs
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
        reject = (2,) if op == 2 else ()
        raw = program_output(op, draws, seed, channel, reject=reject, corrupt=spec['stage'] == self.corrupt_stage,
                             higgs=self.higgs)
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
           'audit_points': 2}
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
