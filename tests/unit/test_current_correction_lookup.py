"""Inert journal/receipt controls, not a native correction execution."""
import ast
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from ravel.workflow import execution, physics_review as review, workflow_state
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics import native_pipeline as native
from correction_lookup_fixture import (policy, make_attempt, check_packet, reject, correct,
                             accept, late_finding_context, commit_late_hold)


@pytest.fixture(autouse=True)
def inert(monkeypatch):
    monkeypatch.setattr(execution, 'runtime_context', lambda: {
        'environment_sha256': execution.digest(execution.runtime_environment()),
        'runtime': 'inert-unit-boundary'})
    def forbidden(*a, **kw):
        raise AssertionError('no process/model/native dispatch allowed in these controls')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(os, 'system', forbidden)


@pytest.fixture
def journal(tmp_path, monkeypatch):
    root = tmp_path / 'run'
    (root / 'inputs').mkdir(parents=True)
    atomic_json(root / review.POLICY, policy())
    atomic_json(root / 'inputs/checkin1_approval.json', {'synthetic': 'inert verifier boundary'})
    monkeypatch.setattr(workflow_state, 'approval_input_paths', lambda rd: [str(Path(rd) / review.POLICY)])
    monkeypatch.setattr(workflow_state, 'verify_approval', lambda *a, **kw: [])
    (root / 'inputs/settings.cfg').write_text('efficiency=0.8\n')
    (root / 'inputs/held-fixed.txt').write_text('fixed recipe\n')
    atomic_json(root / 'inputs/reference.json', {'reference': 1})
    record = make_attempt(root)
    check_packet(root, record)
    review.open_cycle(root, effective_settings=['inputs/settings.cfg'],
        stage_receipts=[record['attempt_record']], check_results='inputs/checks.json')
    reject(root)
    correction = correct(root)
    return root, correction


def test_single_authenticated_read_without_readiness_or_status(journal, monkeypatch):
    root, correction = journal
    counts = {'read': 0, 'base': 0, 'snapshots': 0}
    for name, key in [('_read', 'read'), ('_base_live', 'base'), ('_live_pins', 'snapshots')]:
        original = getattr(review, name)
        def wrapped(*a, _original=original, _key=key, **kw):
            counts[_key] += 1
            return _original(*a, **kw)
        monkeypatch.setattr(review, name, wrapped)
    monkeypatch.setattr(review, 'status', lambda *a, **kw: pytest.fail('full status is not an amendment lookup'))
    monkeypatch.setattr(review, '_correction_ready', lambda *a, **kw: pytest.fail('inspection cannot imply launch readiness'))
    assert review.current_correction(root) == correction
    assert counts == {'read': 1, 'base': 1, 'snapshots': 2}


def test_fresh_second_call_refuses_same_size_restored_mtime_drift(journal):
    root, _ = journal
    assert review.current_correction(root)
    source = root / 'inputs/settings.cfg'; stat = source.stat()
    source.write_bytes(b'x' * stat.st_size)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match='changed'):
        review.current_correction(root)


@pytest.mark.parametrize('mutation', ['journal_digest', 'checkpoint', 'deleted_event',
    'frozen_blob', 'registration', 'policy', 'approval', 'held_source', 'source_symlink'])
def test_authentication_live_source_and_frozen_evidence_refuse(journal, mutation):
    root, correction = journal
    if mutation == 'journal_digest':
        p = root / review.DIRECTORY / 'events/00000003.json'
        d = read_json(p); d['actor_id'] = 'foreign'; atomic_json(p, d)
    elif mutation == 'checkpoint':
        atomic_json(root / review.HEAD, {'sequence': 0, 'sha256': '0'*64})
    elif mutation == 'deleted_event':
        (root / review.DIRECTORY / 'events/00000002.json').unlink()
    elif mutation == 'frozen_blob':
        p = root / correction['snapshots'][0]['snapshot']; p.write_text('forged frozen blob')
    elif mutation == 'registration':
        p = root / review.REGISTRATION; d = read_json(p); d['run_id'] = 'foreign'; atomic_json(p, d)
    elif mutation == 'policy':
        p = root / review.POLICY; d = read_json(p); d['max_redos'] = 3; atomic_json(p, d)
    elif mutation == 'approval':
        (root / 'inputs/checkin1_approval.json').write_text('{"changed":true}')
    elif mutation == 'held_source':
        (root / 'inputs/held-fixed.txt').write_text('different recipe\n')
    else:
        p = root / 'inputs/settings.cfg'; raw = p.read_bytes(); p.unlink()
        target = root / 'inputs/alias-target'; target.write_bytes(raw); p.symlink_to(target)
    with pytest.raises((ValueError, OSError)):
        review.current_correction(root)


def test_returned_object_does_not_mutate_next_authenticated_lookup(journal):
    root, correction = journal
    value = review.current_correction(root); value['stages'].append('foreign-stage')
    assert review.current_correction(root) == correction


def test_inspection_does_not_remove_launch_specific_stage_gate(journal):
    root, correction = journal
    assert review.current_correction(root) == correction
    assert review.gate_errors(root, 'correction', 'foreign-stage')
    assert review.correction_execution_errors(root, 'detector', ['foreign'], ['inputs/settings.cfg'],
        ['outputs/produced.json'], [], str(root), 'logs/detector.log')


def test_failed_current_amendment_cannot_be_returned(journal):
    root, correction = journal
    review.fail_correction(root, correction_id=correction['correction_id'], reason='retained synthetic failure')
    assert review.current_correction(root) is None
    with pytest.raises(ValueError, match='no current admitted correction'):
        review.admitted_correction(root)
    assert review.gate_errors(root, 'correction', 'detector')


def test_absence_does_not_create_registration_or_authority(tmp_path):
    root = tmp_path / 'absent'; root.mkdir()
    before = list(root.iterdir())
    assert review.current_correction(root) is None
    assert list(root.iterdir()) == before
    with pytest.raises(ValueError, match='no current admitted correction'):
        review.admitted_correction(root)


def test_presence_of_corrupted_review_never_falls_back(tmp_path):
    root = tmp_path / 'bad'; (root / review.DIRECTORY).mkdir(parents=True)
    atomic_json(root / review.HEAD, {'sequence': 1, 'sha256': '0'*64})
    with pytest.raises(ValueError, match='registration is missing'):
        review.current_correction(root)


@pytest.mark.parametrize('control', ['registration', 'head', 'events'])
def test_dangling_control_path_never_falls_back(tmp_path, control):
    root = tmp_path / 'bad'; (root / review.DIRECTORY).mkdir(parents=True)
    value = {'registration': review.REGISTRATION, 'head': review.HEAD,
             'events': review.DIRECTORY + '/events'}[control]
    (root / value).symlink_to(root / 'missing-target')
    with pytest.raises(ValueError, match='symlink'):
        review.current_correction(root)


def test_hold_cannot_return_old_correction(journal):
    root, correction = journal
    fresh = make_attempt(root, value=2)
    check_packet(root, fresh)
    review.open_cycle(root, effective_settings=['inputs/settings.cfg'],
        stage_receipts=[fresh['attempt_record']], check_results='inputs/checks.json',
        correction_id=correction['correction_id'])
    accept(root, closes=['F1'])
    assert review.current_correction(root) is None
    context, path = late_finding_context(root)
    commit_late_hold(root, context, path)
    with pytest.raises(ValueError, match='scientific hold'):
        review.current_correction(root)
    assert review.gate_errors(root, 'reuse')


def test_native_uses_current_lookup_and_keeps_exact_derivative_checks(tmp_path, monkeypatch):
    root = tmp_path
    plan = {'rundir': str(root)}
    monkeypatch.setattr(review, 'active', lambda *a, **kw: pytest.fail('no redundant active census'))
    monkeypatch.setattr(review, 'status', lambda *a, **kw: pytest.fail('no full status census'))
    monkeypatch.setattr(review, 'current_correction', lambda *a, **kw: None)
    assert native.native_correction(plan) is None
    monkeypatch.setattr(review, 'current_correction', lambda *a, **kw:
        {'snapshots': [], 'effective_settings': [], 'stages': []})
    plan.update(plan_path=str(root/'derivative.json'), effective_settings=str(root/'effective.json'), sources=[])
    with pytest.raises(ValueError, match='explicitly bound effective settings'):
        native.native_correction(plan)


