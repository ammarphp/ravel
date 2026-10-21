"""Instruction custody and evidence through the real protected store and ledger."""
from copy import deepcopy
import hashlib

import pytest

from ravel.controller import instructions, ledger
from ravel.controller.instructions.custody import session_observation
from ravel.controller.ledger.state import load
from ravel.controller.store import RunStore
from ravel.workflow import role_registry
from test_p03_observed import final_record


@pytest.mark.parametrize('damage', [None, 'fragment', 'bytes', 'stale', 'receipt'])
def test_real_store_instruction_discharge(tmp_path, damage):
    store = RunStore('run-custody', root=tmp_path / 'store')
    step = {'id': 'step-one', 'kind': 'operate', 'role': 'generator'}
    card = role_registry.load(step['role'])
    manifest = instructions.manifest(step, card)
    packet = instructions.packet(manifest, card, step, [])
    ledger.materialise(store, 'intake', {'run_id': store.run_id})
    ledger.materialise(store, 'plan', {'plan': {'steps': [step]}})
    keys = ledger.materialise(store, 'dispatch', {'step': step['id'], 'seat': 'producer',
                                               'role': step['role'], 'attempt': 1, 'seat_kind': 'worker'})
    row = 'ROLE-generator-purpose'
    entry = next(k for k in keys if k.startswith(row + '@'))
    binding = {'run_id': store.run_id, 'step': step['id'], 'attempt': 1,
               'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256']}
    session = store.append('worker-session', {**binding, 'packet': packet, 'step_spec': step,
                                             'card': card, 'inputs': []})
    store.append('step-attempt', {**binding, 'session': session})
    final = final_record(manifest, 'outputs/result.json#/absent' if damage == 'fragment'
                         else 'outputs/result.json#/value')
    target = store.path('instruction-artifacts', session, 'outputs', 'result.json')
    target.parent.mkdir(parents=True)
    target.write_bytes(b'{"value": 7}')
    completion = store.append('worker-completion', {**binding, 'session': session, 'final_record': final,
        'artifacts': [{'path': 'outputs/result.json', 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}]})
    observed = session_observation(store, session, manifest)
    assert observed['id'] == session
    receipt = instructions.record_delivery(store, manifest, packet, session=session)
    if damage == 'bytes':
        target.write_bytes(b'{"value": 8}')
    elif damage == 'stale':
        store.append('step-attempt', {**binding, 'session': 'later-session', 'attempt': 2})
    elif damage == 'receipt':
        forged = deepcopy(store.read('instruction-delivery', receipt)['record'])
        forged['packet_sha256'] = '0' * 64
        receipt = store.append('instruction-delivery', forged)
    status = 'satisfied' if damage is None else 'violated'
    assert instructions.discharge(store, {row: entry}, manifest, receipt_id=receipt) == {row: status}
    instance = load(store, full=True).instances[entry]
    assert instance.status == status
    if damage is None:
        assert instance.evidence['ack'] == completion
        assert store.read('worker-completion', instance.evidence['ack'])['record']['session'] == session
    else:
        assert isinstance(instance.evidence['reason'], str) and instance.evidence['reason']
