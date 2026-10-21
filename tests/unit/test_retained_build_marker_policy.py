"""Exact copied-input/large raw-proof controls; no worker/native/VM execution."""

from method_decision_fixture import admit_method
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest
from ravel.workflow import execution, science, physics_review as review, launch_authorization
from ravel.workflow.state_io import atomic_json, read_json
from test_science_output_policy import spec as synthetic_spec, token
from test_science_review_envelope import checks
from bound_review import bound_review

EMPTY = hashlib.sha256(b'').hexdigest()
TARGET = 'outputs/attempt-1/container-input/dependency-checkpoint/work/build/src/RestFrames-stamp/RestFrames-done'


def marker(base):
    source = base/'prepared/dependency-checkpoint/work/build/src/RestFrames-stamp/RestFrames-done'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'')
    entry = {'path': TARGET, 'role': 'retained_build_marker', 'marker_class': 'cmake_externalproject_stamp',
             'source': {'path': str(source), 'size': 0, 'sha256': EMPTY}}
    return source, {'schema_version': 1, 'allow_empty_directory_members': [entry]}


@pytest.mark.parametrize('cached', [False, True])
def test_zero_copy_requires_actual_singleton_stage_input_and_is_hashed(tmp_path, cached):
    source, policy = marker(tmp_path)
    target = tmp_path/TARGET;target.parent.mkdir(parents=True);target.write_bytes(b'')
    (tmp_path/'outputs/attempt-1/required.root').write_bytes(b'nonempty required scientific fixture')
    captured = execution.snapshot(tmp_path, [str(source)])
    session = execution._validation_session(tmp_path) if cached else None
    snap = session.snapshot if cached else lambda *a, **kw: execution.snapshot(tmp_path, *a, **kw)
    with pytest.raises(ValueError, match='approved stage input binding'):
        snap(['outputs/attempt-1'], outputs=True, output_policy=policy)
    value = snap(['outputs/attempt-1'], outputs=True, output_policy=policy, input_snapshot=captured, input_paths=[str(source)])
    rows = next(iter(value.values()))['files']
    assert next(row for row in rows if row['size'] == 0)['sha256'] == EMPTY
    (tmp_path/'outputs/attempt-1/result.json').write_bytes(b'')
    with pytest.raises(ValueError, match='inventory changed' if cached else 'empty output'):
        snap(['outputs/attempt-1'], outputs=True, output_policy=policy, input_snapshot=captured, input_paths=[str(source)])
    if session: session.close()


@pytest.mark.parametrize('case', ['undeclared', 'directory', 'missing', 'different_sha', 'nonzero_size', 'alias', 'foreign_namespace', 'scientific_name', 'wrong_marker_class', 'extra_field', 'changed_copy', 'boolean_snapshot_size'])
def test_marker_class_cannot_turn_producer_labels_into_input_authority(tmp_path, case):
    source, policy = marker(tmp_path)
    paths = [str(source)];snapshot = execution.snapshot(tmp_path, paths)
    entry = policy['allow_empty_directory_members'][0]
    target = tmp_path/TARGET;target.parent.mkdir(parents=True);target.write_bytes(b'')
    (tmp_path/'outputs/attempt-1/identity.raw').write_bytes(b'nonempty')
    if case == 'undeclared': paths = []
    elif case == 'directory': snapshot[str(source)] = {'kind': 'directory', 'files': [{'name': 'RestFrames-done', 'size': 0, 'sha256': EMPTY}]}
    elif case == 'missing': snapshot = {}
    elif case == 'different_sha': entry['source']['sha256'] = '0'*64
    elif case == 'nonzero_size': entry['source']['size'] = 1
    elif case == 'alias': entry['source']['path'] = str(source.parent/'..'/source.parent.name/source.name)
    elif case == 'foreign_namespace': entry['path'] = 'outputs/attempt-1/native-output/RestFrames-done'
    elif case == 'scientific_name': entry['path'] = TARGET.rsplit('/', 1)[0]+'/result.json'
    elif case == 'wrong_marker_class': entry['marker_class'] = 'producer-says-empty-is-safe'
    elif case == 'extra_field': entry['approved'] = True
    elif case == 'changed_copy': target.write_bytes(b'changed zero-input copy')
    elif case == 'boolean_snapshot_size': snapshot[str(source)]['files'][0]['size'] = False
    with pytest.raises(ValueError):
        execution.snapshot(tmp_path, ['outputs/attempt-1'], outputs=True, output_policy=policy, input_snapshot=snapshot, input_paths=paths)


def test_public_stage_plan_finish_and_reuse_bind_original_zero_bytes(tmp_path):
    source, policy = marker(tmp_path)
    binding = execution.plan_stage(tmp_path, 'science', ['/usr/bin/true'], [str(source)], ['outputs/attempt-1'], [], tmp_path, output_policy=policy)
    record = execution.begin_attempt(tmp_path, 'science', binding, 'logs/science.log')
    copy = tmp_path/TARGET;copy.parent.mkdir(parents=True);copy.write_bytes(b'')
    atomic_json(tmp_path/'outputs/attempt-1/result.json', {'scope': 'synthetic lifecycle, no worker'})
    (tmp_path/'logs/science.log').write_text('No worker or native execution\n')
    assert execution.finish_attempt(tmp_path, record, 0) == 0
    assert execution.reusable(tmp_path, 'science', binding)
    source.write_bytes(b'changed original input')
    assert execution.stage_errors(tmp_path, 'science')
    assert not execution.reusable(tmp_path, 'science', binding)


def completed(tmp_path, monkeypatch, *, large=False):
    source, policy = marker(tmp_path)
    s = synthetic_spec(tmp_path, declared=False)
    s['output_policy'] = policy
    if large: s['assumptions'].append('Large approved administrative input population fixture. '*24000)
    # A synthetic adapter input slot isolates the generic custody seam. Real
    # configured native build input enumeration is separately checked before
    # the actual successor freeze; this fixture never claims native evidence.
    original = science.task_inputs
    monkeypatch.setattr(science, 'task_inputs', lambda *a, **kw: [*original(*a, **kw), source])
    monkeypatch.setattr(launch_authorization, 'audit_launches', lambda *a, **kw: [])
    atomic_json(tmp_path/'spec.json', s);rd = tmp_path/'run'
    proposal = science.plan(rd, tmp_path/'spec.json'); admit_method(rd)
    assert str(source) in proposal['stage_binding']['input_snapshot']
    science.approve(rd, 'Synthetic source-custody lifecycle; no worker/native approval', scripted=True);token(rd)
    stage, binding, _ = science._selected(rd, proposal)
    record = execution.begin_attempt(rd, 'science', binding, stage['log']);out = rd/stage['outputs'][0]
    atomic_json(out/'result.json', {'status':'passed', 'physics_validated':False, 'value':1})
    atomic_json(out/'recipe.json', {'task':science.execution_spec(rd)['task']})
    atomic_json(out/'verification.json', {'passed':True, 'scope':'domain', 'physics_validated':False, 'expert_review':False, 'result_sha256':execution.file_hash(out/'result.json')})
    atomic_json(out/'checkin2.json', {'schema_version':1, 'kind':'checkin2', 'sections':{'waypoint':'Synthetic control', 'expectation':'Byte custody', 'ask':{'options':['GO','ADJUST']}}})
    copy = rd/TARGET;copy.parent.mkdir(parents=True);copy.write_bytes(b'')
    (rd/stage['log']).write_text('Synthetic retained stage; no worker/native\n')
    assert execution.finish_attempt(rd, record, 0) == 0
    checks(rd, record, 1, 'pass')
    cycle = review.open_cycle(rd, effective_settings=science.review_effective_settings(rd), stage_receipts=[record['attempt_record']], check_results='inputs/checks-1.json')
    return rd, record, cycle, source


def test_complete_open_detached_and_three_synthetic_roles_preserve_marker_scope(tmp_path, monkeypatch):
    rd, record, cycle, source = completed(tmp_path, monkeypatch)
    reg, events = review._read(rd)
    zero = next(p for p in cycle['snapshots'] if p['path'] == TARGET)
    assert review._empty_snapshot_allowed(zero, reg, cycle)
    detached = {'schema_version':1, 'registration':reg, 'events':events, 'checkpoint':read_json(rd/review.HEAD), 'action':'history', 'stage':None}
    assert review.validate_snapshot(detached, require_admission=False) == []
    source.unlink()  # Frozen classification never consults mutable original input.
    assert review.validate_snapshot(detached, require_admission=False) == []
    assert review.gate_errors(rd, 'reuse')


@pytest.mark.parametrize('location', ['check', 'setting'])
def test_zero_build_marker_is_never_scientific_or_effective_evidence(tmp_path, monkeypatch, location):
    rd, record, cycle, source = completed(tmp_path, monkeypatch)
    if location == 'setting':
        with pytest.raises(ValueError, match='missing or empty'):
            review.open_cycle(rd, effective_settings=[TARGET], stage_receipts=[record['attempt_record']], check_results='inputs/checks-1.json')
    else:
        reg, events = review._read(rd);mutated = deepcopy(cycle)
        mutated['checks'][0]['evidence'][0]['path'] = TARGET
        assert not review._empty_snapshot_allowed(next(p for p in mutated['snapshots'] if p['path'] == TARGET), reg, mutated)


def test_large_raw_approved_documents_retained_without_reclassifying_old_generic_evidence(tmp_path, monkeypatch):
    rd, record, cycle, source = completed(tmp_path, monkeypatch, large=True)
    assert review.MAX_RETAINED_BYTES == 1024*1024
    proof = cycle['receipts'][0]['incidental_output_proof']
    raw_paths = {proof[key]['path'] for key in ('specification', 'plan', 'checkin', 'approval', 'receipt')}
    large = [p for p in cycle['snapshots'] if p['size'] > review.MAX_RETAINED_BYTES and p['path'] in raw_paths]
    assert large and all(p['content_retained'] and p['snapshot'] for p in large)
    other_large = [p for p in cycle['snapshots'] if p['size'] > review.MAX_RETAINED_BYTES and p['path'] not in raw_paths]
    assert all(p['content_retained'] is False and p['snapshot'] is None for p in other_large)
    reg, events = review._read(rd)
    detached = {'schema_version':1, 'registration':reg, 'events':events, 'checkpoint':read_json(rd/review.HEAD), 'action':'history', 'stage':None}
    assert review.validate_snapshot(detached, require_admission=False) == []
    # Recorded votes are bound responses of dispatched roles; a declared reviewer name is advice only.
    for role in ['physics_critic', 'skeptical_verifier', 'physics_decider']:
        bound_review(rd, role=role, verdict='accept', summary='Synthetic administrative custody test; no native physics review', claim_scope='reproduction')
    assert review.gate_errors(rd, 'reuse') == []
    generic = rd/'generic-large.bin';generic.write_bytes(b'X'*(review.MAX_RETAINED_BYTES+1))
    pin = review._frozen_pin(rd, review._pin(rd, str(generic)))
    assert pin['content_retained'] is False and pin['snapshot'] is None
    assert not review._large_proof_document_allowed({**pin, 'content_retained':True}, reg, cycle)


def test_large_proof_bound_refuses_oversize_even_when_source_is_resealed(tmp_path, monkeypatch):
    rd, record, cycle, source = completed(tmp_path, monkeypatch)
    reg, _ = review._read(rd);cycle = deepcopy(cycle);reg = deepcopy(reg)
    proof = cycle['receipts'][0]['incidental_output_proof']
    raw = json.dumps({'schema_version':2, 'oversized_self_resealed_fixture': 'X'*(review.MAX_INCIDENTAL_DOCUMENT_BYTES+1)})
    doc = proof['specification'];doc.update(text=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
    for pin in cycle['snapshots']:
        if pin['path'] == doc['path']:
            pin.update(sha256=doc['sha256'], size=len(raw.encode()), content_retained=True, snapshot=f'{review.DIRECTORY}/snapshots/{doc["sha256"]}.blob')
    for pin in reg['bindings']:
        if pin['path'] == doc['path']:pin['sha256'] = doc['sha256']
    with pytest.raises(ValueError, match='oversized'):
        review._incidental_output_paths(reg, cycle)


def reseal_documents(reg, cycle, documents):
    """Adversarial local rewrite; hashes are consistency, not authentication."""
    proof = cycle['receipts'][0]['incidental_output_proof']
    def commit(key):
        doc = proof[key]
        raw = json.dumps(documents[key], indent=2, allow_nan=False)+'\n'
        doc.update(text=raw, sha256=hashlib.sha256(raw.encode()).hexdigest())
        for pin in cycle['snapshots']:
            if pin['path'] == doc['path']:
                pin.update(sha256=doc['sha256'], size=len(raw.encode()), content_retained=True,
                           snapshot=f'{review.DIRECTORY}/snapshots/{doc["sha256"]}.blob')
        for pin in reg['bindings']:
            if pin['path'] == doc['path']:pin['sha256'] = doc['sha256']
    commit('specification');commit('plan')
    documents['checkin'] = science.make_checkin(documents['specification'], proof['plan']['sha256'],
        documents['plan']['stages'][0], base=documents['plan']['base_dir'],
        method_decision=documents.get('method_decision'))
    commit('checkin')
    documents['approval'].update(plan_sha256=proof['plan']['sha256'], checkin_sha256=proof['checkin']['sha256'])
    registered = {p['path']:p['sha256'] for p in reg['bindings']}
    documents['approval']['input_fingerprint'] = hashlib.sha256(''.join(registered[p] for p in [science.PLAN, science.SPEC, 'inputs/checkin1.json', science.REVIEW_POLICY, science.METHOD_DECISION]).encode()).hexdigest()
    commit('approval');commit('receipt')
    cycle['receipts'][0]['receipt_sha256'] = documents['receipt']['receipt_sha256']


@pytest.mark.parametrize('case', ['directory_snapshot', 'missing_snapshot', 'not_declared', 'boolean_snapshot_size'])
def test_fully_resealed_frozen_proof_cannot_replace_singleton_input_authority(tmp_path, monkeypatch, case):
    rd, _, cycle, source = completed(tmp_path, monkeypatch)
    reg, _ = review._read(rd)
    assert TARGET in review._incidental_output_paths(reg, cycle)
    cycle, reg = deepcopy(cycle), deepcopy(reg)
    proof = cycle['receipts'][0]['incidental_output_proof']
    docs = {key:json.loads(proof[key]['text']) for key in ('specification','plan','checkin','approval','receipt')}
    record, binding = docs['receipt'], docs['plan']['stage_binding']
    if case == 'directory_snapshot':
        record['input_snapshot'][str(source)] = {'kind':'directory', 'files':[{'name':source.name,'size':0,'sha256':EMPTY}]}
    elif case == 'missing_snapshot':
        record['input_snapshot'].pop(str(source))
    elif case == 'not_declared':
        record['inputs'].remove(str(source))
    else:
        record['input_snapshot'][str(source)]['files'][0]['size'] = False
    keys = ('command','cwd','inputs','outputs','input_snapshot','parents','runtime')
    for key in keys:binding[key] = deepcopy(record[key])
    binding['fingerprint'] = execution.digest({key:value for key,value in binding.items() if key != 'fingerprint'})
    record['fingerprint'] = binding['fingerprint']
    record['receipt_sha256'] = execution.receipt_digest(record)
    reseal_documents(reg, cycle, docs)
    # The bound prepared capsule is authenticated before the singleton copy policy.
    with pytest.raises(ValueError, match='prepared capsule differs from planned source/runtime/interpreter binding'):
        review._incidental_output_paths(reg, cycle)


def test_aggregate_raw_proof_budget_is_independent_of_each_document_cap(tmp_path, monkeypatch):
    rd, _, cycle, _ = completed(tmp_path, monkeypatch)
    reg, _ = review._read(rd)
    proof = cycle['receipts'][0]['incidental_output_proof']
    keys = ('specification','plan','checkin','approval','receipt')
    total = sum(len(proof[key]['text'].encode()) for key in keys)
    assert all(len(proof[key]['text'].encode()) < review.MAX_INCIDENTAL_DOCUMENT_BYTES for key in keys)
    monkeypatch.setattr(review, 'MAX_INCIDENTAL_PROOF_BYTES', total-1)
    with pytest.raises(ValueError, match='oversized'):
        review._incidental_output_paths(reg, cycle)


@pytest.mark.parametrize('mutation', ['replacement','same_inode_restored_mtime','growth'])
def test_bounded_raw_document_read_checks_ending_descriptor_and_path(tmp_path, monkeypatch, mutation):
    import os
    source = tmp_path/'approved-plan.json';source.write_bytes(b'{"same":"bytes"}')
    original = Path.open
    before = source.stat()
    class ChangedAfterRead:
        def __init__(self, stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self, *args):return self.stream.__exit__(*args)
        def fileno(self):return self.stream.fileno()
        def read(self, size):
            value = self.stream.read(size)
            if mutation == 'replacement':
                replacement = tmp_path/'replacement';replacement.write_bytes(value)
                replacement.replace(source)
            else:
                with original(source, 'wb') as stream:
                    stream.write(value+b'new' if mutation == 'growth' else b'{"same":"other"}')
                os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
            return value
    def opening(path, mode='r', *args, **kwargs):
        stream = original(path, mode, *args, **kwargs)
        return ChangedAfterRead(stream) if path == source and mode == 'rb' else stream
    monkeypatch.setattr(Path, 'open', opening)
    with pytest.raises(ValueError, match='changed'):
        review._read_raw_proof_document(tmp_path, source.name)


def test_raw_document_read_refuses_declared_oversize_before_open(tmp_path, monkeypatch):
    source = tmp_path/'approved-plan.json';source.write_bytes(b'X'*33)
    monkeypatch.setattr(review, 'MAX_INCIDENTAL_DOCUMENT_BYTES', 32)
    monkeypatch.setattr(Path, 'open', lambda *args, **kwargs:pytest.fail('oversized proof read reached open'))
    with pytest.raises(ValueError, match='exceeds retained limit'):
        review._read_raw_proof_document(tmp_path, source.name)


@pytest.mark.parametrize('mutation', ['missing', 'bytes'])
def test_frozen_method_proof_is_required_and_byte_bound(tmp_path, monkeypatch, mutation):
    rd, _, cycle, _ = completed(tmp_path, monkeypatch)
    reg, _ = review._read(rd)
    proof = cycle['receipts'][0]['incidental_output_proof']
    assert proof['method_decision']['path'] == science.METHOD_DECISION
    assert review._incidental_output_paths(reg, cycle)
    if mutation == 'missing':
        del proof['method_decision']
    else:
        proof['method_decision']['text'] = '{}'
    with pytest.raises(ValueError):
        review._incidental_output_paths(reg, cycle)


def test_frozen_method_proof_does_not_read_current_method_bytes(tmp_path, monkeypatch):
    rd, _, cycle, _ = completed(tmp_path, monkeypatch)
    reg, _ = review._read(rd)
    expected = review._incidental_output_paths(reg, cycle)
    (rd / science.METHOD_DECISION).unlink()
    assert review._incidental_output_paths(reg, cycle) == expected
