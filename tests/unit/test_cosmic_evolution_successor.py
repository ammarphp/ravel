"""Narrow V2 custody controls; all authority/runtime/payloads are synthetic.

The actual ordinary parent admission is reused from the original portable
fixture. No Slurm service, native payload, model call or real study is invoked.
"""
from copy import deepcopy
from pathlib import Path
import json, os
import pytest
from cosmic_evolution_fixture import fixture, write, pin, save, policy, LIMITS, FakeController, FakeClient, inert_admission
import test_cosmic_evolution_delegation as delegation
from ravel.physics import cosmic_evolution as op, cosmic_evolution_worker as worker
from ravel.workflow import execution, state_io


def rank_fixture(tmp_path, monkeypatch, kind='nyx'):
    original = delegation.fixture
    def selected(root, **kw):
        path, d, w, s = original(root, **kw)
        d['cases'][0]['phases'][1]['payload'] = deepcopy(d['cases'][0]['phases'][-1]['payload'])
        save(path, d)
        return path, d, w, s
    monkeypatch.setattr(delegation, 'fixture', selected)
    rd, path, d, w, proposal, token = delegation.ordinary(tmp_path, monkeypatch)
    case = d['cases'][0]; phase = next(p for p in case['phases'] if p['kind'] == kind)
    cap = op._capture({'input': str(path)}, path.parent)[2]
    root = rd / proposal['output_directory'] / 'cosmic-evolution' / case['id'] / phase['id']
    native = root / 'native'; native.mkdir(parents=True)
    for row in phase['copies']:
        (native / row['to']).write_bytes(Path(row['file']['path']).read_bytes())
    handoff = worker.handoff_ic(case, phase, root.parent, native, w, execution.digest(d), cap, LIMITS) if kind == 'nyx' else None
    h = root / 'handshake'; h.mkdir()
    plan = {'rundir': str(rd), 'config_path': str(path), 'phase_id': phase['id'], 'case_id': case['id'],
        'nonce': 'fresh', 'payload': {**phase['payload'], 'path': str(Path(phase['payload']['path']).absolute())},
        'argv': phase['argv'], 'handshake': str(h), 'native_cwd': str(native), 'ranks': phase['ranks'],
        'job_id': 17, 'uid': os.getuid(), 'handshake_seconds': 5, 'payload_seconds': 15,
        'build_receipt': None, 'ic_handoff': handoff, 'parent_admission': deepcopy(token)}
    write(h / 'ack.json', {'nonce': 'fresh', 'payload': plan['payload'], 'job_id': 17, 'step_id': 3,
        'uid': os.getuid(), 'start': 100, 'delegation_sha256': execution.digest(token)})
    pp = root / 'rank-plan.json'; write(pp, plan)
    for key, value in {'SLURM_PROCID': '0', 'SLURM_JOB_ID': '17', 'SLURM_STEP_ID': '3'}.items(): monkeypatch.setenv(key, value)
    monkeypatch.setattr(worker.socket, 'gethostname', lambda: 'n0')
    calls = []; monkeypatch.setattr(worker.subprocess, 'call', lambda *a, **kw: calls.append(a[0]) or 0)
    return pp, phase, native, h, calls


@pytest.mark.parametrize('operation', ['prepare', 'prepare_context'])
def test_prepared_return_is_detached_exact_intended_document(tmp_path, operation):
    path, d, _, _ = fixture(tmp_path/'input', writer=False)
    output = tmp_path/'prepared.json'
    if operation == 'prepare': returned = op.prepare(path, write(path.parent/'policy.json', policy())['path'], output)
    else: returned = op.prepare_context(path, output)
    raw = (json.dumps(returned, indent=2, allow_nan=False)+'\n').encode()
    assert output.read_bytes() == raw
    returned['source' if operation == 'prepare' else 'inputs'] = 'caller mutation after return'
    assert output.read_bytes() == raw and json.loads(raw) != returned


@pytest.mark.parametrize('kind,attack', [('nyx','bytes'), ('nyx','ABA'), ('cosmicic','transfer')])
def test_actual_copy_drift_after_ack_consumption_refuses(tmp_path, monkeypatch, kind, attack):
    pp, phase, native, h, calls = rank_fixture(tmp_path, monkeypatch, kind)
    original = worker._document
    copied = native/phase['copies'][1 if attack == 'transfer' else 0]['to']
    raw = copied.read_bytes()
    def read(p, sha=None, **kw):
        value = original(p, sha, **kw)
        if Path(p) == h/'ack.json':
            copied.write_bytes(raw+b'changed after initial copy authentication\n')
            if attack == 'ABA': copied.write_bytes(raw)
        return value
    monkeypatch.setattr(worker, '_document', read)
    with pytest.raises(ValueError): worker.rank(pp, pin(pp)['sha256'])
    assert not calls


def test_pre_payload_checkpoint_enforces_deadline_after_delegation_read(tmp_path, monkeypatch):
    pp, phase, native, h, calls = rank_fixture(tmp_path, monkeypatch)
    clock = [0.0]; monkeypatch.setattr(worker.time, 'monotonic', lambda: clock[0])
    original = worker._admission; count = [0]
    def read(*a, **kw):
        result = original(*a, **kw); count[0] += 1
        if count[0] == 2: clock[0] = 6.0
        return result
    monkeypatch.setattr(worker, '_admission', read)
    with pytest.raises(ValueError, match='deadline'): worker.rank(pp, pin(pp)['sha256'])
    assert not calls and count[0] == 2


def test_parent_declines_ack_when_owned_step_observation_exhausts_budget(tmp_path, monkeypatch):
    path, d, w, s = fixture(tmp_path/'input', operation='site-local-execution', generated=True)
    inert_admission(monkeypatch, path.parent); monkeypatch.setenv('SLURM_JOB_ID', '17')
    clock = [0.0]; monkeypatch.setattr(worker.time, 'monotonic', lambda: clock[0])
    original = worker.OwnedStep.bind
    def bind(*a, **kw):
        result = original(*a, **kw); clock[0] = 6.0; return result
    monkeypatch.setattr(worker.OwnedStep, 'bind', bind)
    cap = op._capture(save(path, d), path.parent)[2]; out = tmp_path/'out'; out.mkdir()
    with pytest.raises(ValueError, match='deadline'):
        worker.execute(d, path, cap, s, out, tmp_path/'synthetic-run', controller_factory=FakeController, client_factory=FakeClient)
    # FakeClient writes fixture outputs inertly; the actual parent ack must never
    # be emitted after its deadline. No real payload was ever dispatched.
    assert not (out/'fixture/build/handshake/ack.json').exists()
