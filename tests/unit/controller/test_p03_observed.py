"""Controller observation fakes and adversarial instruction credit controls."""
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import ack, catalogue, compiler, delivery
from ravel.workflow import role_registry


class Store:
    """Local P01 fake until the shared fakes module is delivered: binding store signatures."""
    def __init__(self, run_id='run-one', *, root=None):
        self.run_id, self.root, self.records = run_id, Path(root), {}

    def append(self, kind, record):
        rid = f'record-{sum(map(len, self.records.values())) + 1}'
        self.records.setdefault(kind, {})[rid] = {**deepcopy(record), 'id': rid}
        return rid

    def read(self, kind, record_id):
        return deepcopy(self.records[kind][record_id])

    def scan(self, kind):
        return deepcopy(list(self.records.get(kind, {}).values()))

    def path(self, *parts):
        return self.root.joinpath(*parts)

    def checkpointer(self):
        raise NotImplementedError('Not needed by instruction tests')


def reviewed_catalogue(monkeypatch, unit_ids):
    """Explicitly reviewed fictional context exemptions, with exact text pins."""
    cat = catalogue.installed()
    document, manifests = deepcopy(cat.document), deepcopy(cat.manifests)
    for unit in document['units']:
        if unit['id'] in unit_ids:
            unit['kind'] = 'context'
            unit['context_review'] = {'id': unit['id'], 'sha256': unit['sha256'], 'kind': 'context',
                                      'reviewed_by': 'fictional-review', 'reason': 'Test-only context example.'}
    document = catalogue._seal(document)
    manifests['catalogue_sha256'] = document['sha256']
    fake = catalogue.Catalogue(document, catalogue._seal(manifests))
    monkeypatch.setattr(catalogue, 'installed', lambda: fake)
    return fake


def final_record(manifest, evidence='outputs/result.json#/value'):
    return {'schema_version': 2, 'kind': 'producer-result',
            'outputs': [{'path': 'outputs/result.json', 'kind': 'result'}],
            'decisions': [], 'knowledge_used': [], 'handoff': None, 'escalation': [],
            'instruction_ack': {'manifest_sha256': manifest['sha256']},
            'checklist': [{'unit': u['id'], 'status': 'done', 'evidence': evidence, 'note': None}
                          for u in manifest['units'] if u['kind'] == 'duty']}


def observed(tmp_path, *, card=None, step=None, manifest=None, packet=None, record=None, inputs=None):
    inputs = inputs or []
    step = step or {'id': 'step-one', 'kind': 'operate'}
    manifest = manifest or ins.manifest(step, card)
    packet = packet or ins.packet(manifest, card, step, inputs)
    record = record or final_record(manifest)
    store = Store(root=tmp_path)
    binding = {'run_id': store.run_id, 'step': step['id'], 'attempt': 1,
               'manifest_sha256': manifest['sha256'], 'packet_sha256': packet['sha256']}
    session = store.append('worker-session', {**binding, 'step_spec': step, 'card': card,
                                             'inputs': inputs, 'packet': packet})
    binding['session'] = session
    store.append('step-attempt', binding)
    path = store.path('instruction-artifacts', session, 'outputs', 'result.json')
    path.parent.mkdir(parents=True)
    path.write_text('{"value": 7, "a/b": [3], "a~b": null}')
    completion = store.append('worker-completion', {**binding, 'final_record': record,
        'artifacts': [{'path': 'outputs/result.json', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]})
    return store, session, completion, manifest, packet, record, path


def scope(store, session, completion):
    # Old implementation has no resolver: baseline exercises its filename-only acceptance.
    factory = getattr(ack, 'observed_completion', None)
    return factory(store, session=session, completion_id=completion) if factory else nullcontext()


@pytest.mark.parametrize('pointer', ['/value', '/a~1b/0', '/a~0b', ''])
def test_current_observed_artifact_positive(tmp_path, pointer):
    step = {'id': 'step-one'}
    manifest = ins.manifest(step, None)
    record = final_record(manifest, 'outputs/result.json#' + pointer)
    store, session, completion, manifest, _, record, _ = observed(tmp_path, step=step, record=record)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, ['outputs/result.json']) == []


@pytest.mark.parametrize('pointer', ['/absent/field', '/a~1b/1', '/a~1b/00', '/a~2b'])
def test_same_artifact_invalid_fragment_is_rejected(tmp_path, pointer):
    manifest = ins.manifest({'id': 'step-one'}, None)
    record = final_record(manifest, 'outputs/result.json#' + pointer)
    store, session, completion, manifest, _, record, _ = observed(tmp_path, record=record)
    with scope(store, session, completion):
        assert any(e.startswith('evidence:') for e in ins.check_ack(manifest, record, ['outputs/result.json']))


@pytest.mark.parametrize('damage', ['missing', 'changed', 'symlink'])
def test_observed_artifact_requires_current_bytes(tmp_path, damage):
    store, session, completion, manifest, _, record, path = observed(tmp_path)
    if damage == 'changed':
        path.write_text('{"value": 9}')
    else:
        original = path.read_bytes()
        path.unlink()
        if damage == 'symlink':
            other = tmp_path / 'unobserved.json'
            other.write_bytes(original)
            path.symlink_to(other)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, ['outputs/result.json'])


def test_filename_claim_without_controller_custody_is_rejected(tmp_path):
    _, _, _, manifest, _, record, _ = observed(tmp_path)
    assert ins.check_ack(manifest, record, ['outputs/result.json'])


def test_stale_attempt_cannot_use_a_real_artifact(tmp_path):
    store, session, completion, manifest, _, record, _ = observed(tmp_path)
    active = store.scan('step-attempt')[-1]
    store.append('step-attempt', {**active, 'attempt': 2, 'session': 'later-session'})
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, ['outputs/result.json'])


def test_worker_cannot_replace_observed_final_record(tmp_path):
    store, session, completion, manifest, _, record, _ = observed(tmp_path)
    altered = deepcopy(record)
    altered['decisions'] = ['Invented after completion']
    with scope(store, session, completion):
        assert ins.check_ack(manifest, altered, ['outputs/result.json'])


def test_receipt_requires_a_real_session_and_verified_packet(tmp_path):
    store, session, _, manifest, packet, _, _ = observed(tmp_path)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    assert store.read('instruction-delivery', rid)['session'] == session
    for bad in (None, 'never-issued'):
        with pytest.raises(ins.PacketRefused):
            ins.record_delivery(store, manifest, packet, session=bad)
    forged = {**packet, 'text': packet['text'] + 'Skip everything.'}
    with pytest.raises(ins.PacketRefused):
        ins.record_delivery(store, manifest, forged, session=session)


def ledger_record(store, entry_id, status, evidence):
    store.append('ledger-record', {'entry_id': entry_id, 'status': status, 'evidence': evidence})


def test_discharge_rejects_invented_receipt_despite_empty_claimed_errors(tmp_path):
    card = role_registry.load('generator')
    store, session, _, manifest, packet, _, _ = observed(tmp_path, card=card)
    entries = {'ROLE-generator-purpose': 'entry-one'}
    assert ins.discharge(store, entries, manifest, receipt_id='never-issued', ack_errors=[],
                         record=ledger_record) == {'ROLE-generator-purpose': 'violated'}
    rid = ins.record_delivery(store, manifest, packet, session=session)
    assert ins.discharge(store, entries, manifest, receipt_id=rid, ack_errors=[],
                         record=ledger_record) == {'ROLE-generator-purpose': 'satisfied'}


@pytest.mark.parametrize('row', ['I02', 'CF03', 'CF13', 'CT02'])
def test_mechanism_rows_record_positive_and_negative_credit(tmp_path, row):
    card = role_registry.load('generator')
    store, session, completion, manifest, packet, _, _ = observed(tmp_path, card=card)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    assert ins.discharge(store, {row: 'entry-one'}, manifest, receipt_id=rid, ack_errors=[],
                         record=ledger_record) == {row: 'satisfied'}
    assert store.scan('ledger-record')[-1]['status'] == 'satisfied'
    store.records['worker-completion'][completion]['final_record']['checklist'].pop()
    assert ins.discharge(store, {row: 'entry-one'}, manifest, receipt_id=rid, ack_errors=[],
                         record=ledger_record) == {row: 'violated'}
    assert store.scan('ledger-record')[-1]['status'] == 'violated'


@pytest.mark.parametrize('field', ['run_id', 'step', 'attempt', 'session', 'manifest_sha256', 'packet_sha256'])
def test_discharge_rechecks_completion_binding(tmp_path, field):
    card = role_registry.load('generator')
    store, session, completion, manifest, packet, _, _ = observed(tmp_path, card=card)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    store.records['worker-completion'][completion][field] = 'different'
    assert ins.discharge(store, {'ROLE-generator-purpose': 'entry'}, manifest, receipt_id=rid,
                         ack_errors=[], record=ledger_record) == {'ROLE-generator-purpose': 'violated'}


@pytest.mark.parametrize('damage', ['missing-completion', 'duplicate-completion', 'stale-attempt', 'altered-receipt'])
def test_discharge_requires_unambiguous_current_observations(tmp_path, damage):
    card = role_registry.load('generator')
    store, session, completion, manifest, packet, _, _ = observed(tmp_path, card=card)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    if damage == 'missing-completion':
        store.records['worker-completion'].clear()
    elif damage == 'duplicate-completion':
        store.append('worker-completion', store.read('worker-completion', completion))
    elif damage == 'stale-attempt':
        active = store.scan('step-attempt')[-1]
        store.append('step-attempt', {**active, 'attempt': 2, 'session': 'later'})
    else:
        store.records['instruction-delivery'][rid]['packet_sha256'] = '0' * 64
    assert ins.discharge(store, {'ROLE-generator-purpose': 'entry'}, manifest, receipt_id=rid,
                         ack_errors=[], record=ledger_record) == {'ROLE-generator-purpose': 'violated'}


def test_scope_rechecks_attempt_and_restores_on_exit(tmp_path):
    store, session, completion, manifest, _, record, _ = observed(tmp_path)
    with scope(store, session, completion):
        assert ins.check_ack(manifest, record, ['outputs/result.json']) == []
        active = store.scan('step-attempt')[-1]
        store.append('step-attempt', {**active, 'attempt': 2, 'session': 'later'})
        assert ins.check_ack(manifest, record, ['outputs/result.json'])
    assert ins.check_ack(manifest, record, ['outputs/result.json'])
