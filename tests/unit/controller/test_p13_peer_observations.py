"""P13/P04 protected worker observation seams; inert controller custody controls only.

The internal worker verifier is replaced with an explicit proof double. It represents
already-verified protected packet/output custody, never a host report or a physics result.
No model, worker process, native job, peer checkout write or external service is used.
"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ravel.workflow import review_dispatch as rd, review_independence as ri  # noqa: E402
from test_p13_review_independence import controller, EXPOSURE, SHA, query  # noqa: E402, F401


def receipt(role, session, actor, *, model='claude-synthetic-control'):
    return {'role': {'id': role}, 'session_id': session, 'actor_id': actor,
            'model': {'observed': model}, 'attestation': 'transport_attested',
            'transport': {'id': 'claude-cli-worker', 'transport_kind': 'cli-worker'}}


def protected_worker_proof(q, reviewer):
    """Only the trusted verifier's return shape; the public receipt does not issue it."""
    return {'binding': deepcopy(q), 'context_id': rd._session(reviewer),
            'dispatch_id': 'protected-dispatch-control',
            'packet': {'builder': 'ravel.workflow.review_projection', 'projection_verified': True,
                       'author_summary': False, 'sha256': q['packet_sha256'] or SHA['packet'],
                       'subject_sha256': q['subject_sha256']},
            'read_boundary': 'packet_only', 'read_boundary_verified': True,
            'exposure': deepcopy(EXPOSURE), 'exposure_verified': True, 'output_unmodified': True}


def observed_pair(store, *, reused=False):
    producer = receipt('screen-producer', 'producer-session', 'producer-actor')
    reviewer = receipt('plan-critic', 'producer-session' if reused else 'review-session', 'reviewer-actor')
    for item, node, kind in ((producer, 'producer-node', 'producer'), (reviewer, 'review-node', 'reviewer')):
        rd.capture_worker_session(store, receipt=item, step_id='step-control', seat=f'{node}:1', role_kind=kind)
    return producer, reviewer


def test_CF10_protected_same_family_worker_observations_credit_and_label(tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    _, reviewer = observed_pair(store)
    q = query(tmp_path)
    monkeypatch.setattr(rd, '_worker', lambda binding: protected_worker_proof(binding, reviewer))
    rd.capture_worker_review(store, q)
    decision = ri.decide(q)
    assert decision['independent'] is True
    assert decision['family_relation'] == 'same'
    assert decision['label'] == 'separate session, same model family'
    assert decision['evidence_boundary'] == ri.CONTROLLER_STORE


def test_CF10_reused_worker_session_is_observed_but_never_credited(tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    _, reviewer = observed_pair(store, reused=True)
    q = query(tmp_path)
    monkeypatch.setattr(rd, '_worker', lambda binding: protected_worker_proof(binding, reviewer))
    rd.capture_worker_review(store, q)
    sessions = store.scan(rd.SESSION_KIND)
    assert len(sessions) == 2 and sessions[-1]['fresh'] is False
    assert ri.decide(q)['independent'] is False


def test_CF10_missing_protected_packet_yields_no_review_observation(tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    observed_pair(store)
    q = query(tmp_path)
    # A raw instruction packet or absent projection cannot produce this verifier proof.
    monkeypatch.setattr(rd, '_worker', lambda binding: None)
    assert rd.capture_worker_review(store, q) is None
    assert store.scan(rd.REVIEW_KIND) == []
    assert ri.decide(q)['independent'] is False


def test_CF10_repeated_worker_observations_are_idempotent(tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    producer, reviewer = observed_pair(store)
    q = query(tmp_path)
    monkeypatch.setattr(rd, '_worker', lambda binding: protected_worker_proof(binding, reviewer))
    rd.capture_worker_review(store, q)
    initial = deepcopy(store.kinds)
    assert rd.capture_worker_session(store, receipt=producer, step_id='step-control',
                                     seat='producer-node:1', role_kind='producer') is None
    assert rd.capture_worker_session(store, receipt=reviewer, step_id='step-control',
                                     seat='review-node:1', role_kind='reviewer') is None
    assert rd.capture_worker_review(store, q) is None
    assert store.kinds == initial
    assert ri.decide(q)['independent'] is True


@pytest.mark.parametrize('field,value', [('actor_id', 'changed-actor'), ('attestation', 'unattested')])
def test_CF10_changed_worker_session_observation_is_refused(tmp_path, controller, field, value):
    store = controller(tmp_path)
    _, reviewer = observed_pair(store)
    changed = deepcopy(reviewer)
    changed[field] = value
    with pytest.raises(ValueError, match='session observation changed'):
        rd.capture_worker_session(store, receipt=changed, step_id='step-control',
                                  seat='review-node:1', role_kind='reviewer')
    assert len(store.scan(rd.SESSION_KIND)) == 2


def test_CF10_changed_verified_review_observation_is_refused(tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    _, reviewer = observed_pair(store)
    q = query(tmp_path)
    proof = protected_worker_proof(q, reviewer)
    monkeypatch.setattr(rd, '_worker', lambda binding: deepcopy(proof))
    rd.capture_worker_review(store, q)
    proof['output_unmodified'] = False
    with pytest.raises(ValueError, match='review observation changed'):
        rd.capture_worker_review(store, q)
    assert len(store.scan(rd.REVIEW_KIND)) == 1


def test_CF10_prelaunch_refusal_without_child_session_has_no_session_observation(tmp_path, controller):
    store = controller(tmp_path)
    refused = receipt('plan-critic', None, None)
    assert rd.capture_worker_session(store, receipt=refused, step_id='step-control',
                                     seat='review-node:1', role_kind='reviewer') is None
    assert store.scan(rd.SESSION_KIND) == []


def patch_hunks():
    path = Path(__file__).resolve().parents[3] / 'tests/fixtures/peer_contracts/worker-observations.patch'
    hunks = []
    for line in path.read_text().splitlines():
        if line.startswith('@@'):
            hunks.append([])
        elif hunks and line[:1] in (' ', '+', '-'):
            hunks[-1].append(line)
    return hunks


def patched_decision():
    """Reconstruct the changed function from its exact new-side patch hunk.

    Only the unchanged three-line prefix falls outside that hunk; all observation,
    decision and label code executed here comes from the delivered patch.
    """
    hunk = next(h for h in patch_hunks() if any('decided = independence.decide(query)' in s for s in h))
    body = '\n'.join(s[1:] for s in hunk if s[:1] in (' ', '+'))
    body = body.split('\ndef credit(state):', 1)[0]
    prefix = ("def _decision(run_dir, receipt_sha, receipt, subject_sha):\n"
              "    independence = module('independence')\n"
              "    query = {'run': str(Path(run_dir).resolve()), 'role': (receipt.get('role') or {}).get('id'),\n")
    namespace = {'Path': Path, 'deepcopy': deepcopy, 'module': lambda name: ri}
    exec(compile(prefix + body + '\n', '<P04 decision integration fragment>', 'exec'), namespace)
    return namespace['_decision']


def test_CF10_P04_decision_fragment_captures_then_preserves_family_label_and_boundary(
        tmp_path, controller, monkeypatch):
    store = controller(tmp_path)
    _, reviewer = observed_pair(store)
    reviewer['final_record'] = {'sha256': SHA['output']}
    monkeypatch.setattr(rd, '_worker', lambda binding: protected_worker_proof(binding, reviewer))
    actual = patched_decision()(tmp_path, SHA['receipt'], reviewer, SHA['subject'])
    assert actual['credited'] is True
    assert actual['family_relation'] == 'same'
    assert actual['label'] == 'separate session, same model family'
    assert actual['evidence_boundary'] == ri.CONTROLLER_STORE
    assert len(store.scan(rd.REVIEW_KIND)) == 1
    # The caller's row retains the same fields; the patch may not replace them with an unknown family.
    caller = '\n'.join(s[1:] for h in patch_hunks() for s in h if s[:1] in (' ', '+'))
    assert "family_relation=decided['family_relation'], label=decided['label']" in caller
    assert "evidence_boundary=decided['evidence_boundary']" in caller


def observation_fragment():
    hunk = next(h for h in patch_hunks() if any('capture_worker_session' in s for s in h))
    added = [s[1:] for s in hunk if s.startswith('+')]
    # The fragment was inside the worker branch; remove that branch's indentation.
    body = '\n'.join(s[4:] for s in added)
    source = 'def observed(state, node_id, attempt, run_dir, receipt):\n' + body + '\n'
    namespace = {'_seat': lambda state: state.get('seat')}
    exec(compile(source, '<P04 observation integration fragment>', 'exec'), namespace)
    return namespace['observed']


@pytest.mark.parametrize('kind,purpose,role_kind', [
    ('analysis', None, 'producer'), ('review', None, 'reviewer'),
    ('analysis', 'review', 'reviewer'), ('analysis', 'consult', 'producer')])
def test_CF10_P04_observe_fragment_records_unique_attempt_seat_and_actual_role_kind(
        tmp_path, controller, kind, purpose, role_kind):
    store = controller(tmp_path)
    state = {'acting': {'id': 'step-control', 'kind': kind},
             'seat': None if purpose is None else {'purpose': purpose}}
    worker = receipt('plan-critic' if role_kind == 'reviewer' else 'screen-producer',
                     'session-control', 'actor-control')
    observation_fragment()(state, 'worker-node', 3, tmp_path, worker)
    rows = store.scan(rd.SESSION_KIND)
    assert len(rows) == 1
    assert rows[0]['seat'] == 'worker-node:3'
    assert rows[0]['step_id'] == 'step-control' and rows[0]['role_kind'] == role_kind


def test_CF10_P04_legacy_observation_fragment_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, 'controller_store', lambda root: None)
    def unexpected(*args, **kwargs):
        raise AssertionError('an unowned run must not write controller observations')
    monkeypatch.setattr(rd, 'capture_worker_session', unexpected)
    state = {'acting': {'id': 'step-control', 'kind': 'analysis'}}
    observation_fragment()(state, 'worker-node', 1, tmp_path,
                           receipt('screen-producer', 'session-control', 'actor-control'))
