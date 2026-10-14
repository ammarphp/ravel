"""Versioned worker receipts: version 1 stays valid byte for byte; version 2 binds ``review_subject``.

The receipt writer is ``agent_worker.finish`` (through ``_write_receipt``). A review dispatch whose
spec carries a review subject writes version 2 and the dispatcher registers it with the label it
computed from the transport's own verification; ``review_points`` grants credit only to a version-2
receipt whose subject matches the point. No model, network or native tool is involved.
"""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ravel.workflow import agent_worker as worker, broker, rdj_custody, role_registry
from ravel.workflow import review_points as rp
from ravel.workflow import transport_registry as tr

GOLDEN = Path(__file__).resolve().parents[1] / 'fixtures/worker_receipt_v1'
# sha256 of the golden receipt as the base code wrote it (step 0 capture).
GOLDEN_SHA = '406663e3328ce39eae77e7638069c380f608e38a8c4778b950430039b8403d13'


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('RAVEL_WORK_ROOT', raising=False)
    monkeypatch.delenv('RAVEL_SESSION_ID', raising=False)
    for name in ('state', 'home', 'run'):
        (tmp_path / name).mkdir()
    return tmp_path / 'run'


def plan(run):
    """A delegated plan with one agreement claim: its review points are blocking voting points."""
    value = {'agent_layer_epoch': 2, 'delegated': True, 'nodes': [], 'claims': [{'id': 'C1', 'kind': 'agreement'}],
             'edges': []}
    path = run / 'inputs/plan.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (run / 'inputs/task_contract.json').write_text(json.dumps({'agent_layer_epoch': 2, 'delegated': True,
                                                               'request_plan': pin}))
    facts = rp._facts(run)
    point = next(p for p in rp.pending(run) if p['row'] == 4 and p['roles'][0]['role'] == 'physics-critic')
    return facts, point


def spec(node_id, *, role='physics-critic', point_id=None, subject=None):
    parent = {'review_point_id': point_id, 'map_id': 'review:checkin2:C1' if point_id else None, 'rca_ticket': None}
    if subject is not None:
        parent['review_subject'] = subject
    return {'schema_version': 1, 'kind': 'agent-worker-spec', 'node_id': node_id, 'attempt': 1,
            'role': {'id': role, 'version': role_registry.load(role)['version'],
                     'card_sha256': role_registry.card_sha256(role)},
            'transport_preference': ['default'], 'inputs': [],
            'declared_outputs': [{'path': 'outputs/review.json', 'kind': 'review-findings', 'required': True}],
            'budgets': {'max_turns': 5, 'max_wall_seconds': 30, 'max_broker_calls': 5, 'max_cost_usd': None},
            'final_record_schema': 'reviewer.v1', 'work_order': None, 'rdj_challenges': None, 'parent': parent}


def cli_transport():
    """A built-in cli-worker declaration whose own verification can attest the transport."""
    document = next(d for d in sorted(tr.all_declarations(), key=lambda d: d['id'])
                    if d['transport_kind'] == 'cli-worker' and d['capabilities']['attestation'] == 'transport')
    return {'id': document['id'], 'transport_kind': 'cli-worker',
            'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': None}


def real_execution(node_id):
    """The execution record the cli-worker adapter hands the dispatcher after its verification passed."""
    return {'exit_status': 0, 'attestation': 'transport_attested', 'transport': cli_transport(),
            'session_id': 'session-' + node_id, 'actor_id': 'actor-' + node_id, 'cli_version': 'stub 0.0',
            'model': {'requested': 'm', 'observed': 'm', 'family': 'f-' + node_id, 'effort': None}}


def stub_execution():
    """What the stub transport hands the dispatcher: no verified envelope, so no attestation."""
    return {'exit_status': 0, 'transport': {'id': 'stub', 'transport_kind': 'stub'},
            'session_id': 'stub-session', 'actor_id': 'stub-actor'}


def close(run, s, execution):
    ws = worker.materialize(run, s)
    tool = broker.Broker(run, ws, node_id=s['node_id'], attempt=1, allowed_actions=['write'], max_calls=100)
    reply = tool.call({'call_id': 'put-' + s['node_id'], 'action': 'write',
                       'args': {'path': 'outputs/review.json', 'content': '{"findings": []}'}})
    assert reply['status'] == 'ok', reply
    return worker.finish(run, s, execution=execution,
                         final={'completed': True, 'disposition': 'supported', 'findings': []})


def advisory(run, point, node_id):
    found = next(p for p in rp.pending(run) if p['id'] == point['id'])
    return next(r['advisory'] for r in found['receipts'] if f'/{node_id}/' in r['path'])


# ---------------------------------------------------------------- 1. version 1 is unchanged


def seat_golden(run):
    """Place the base-written receipt in a fresh run's dispatcher custody, byte for byte."""
    s = json.loads((GOLDEN / 'spec.json').read_text())
    ws = worker.materialize(run, s)
    for name in ('receipt.json', 'transcript.jsonl', 'final.json', 'outputs/review.json'):
        shutil.copyfile(GOLDEN / name.replace('/', '__'), ws / name)
    record_path = worker._record_path(run, s['node_id'], 1)
    record = json.loads(record_path.read_text())
    record['receipt'] = {'path': broker.logical(run, ws / 'receipt.json'), 'sha256': broker.sha(ws / 'receipt.json')}
    record_path.write_text(json.dumps(record))
    return s, ws


def test_a_base_written_receipt_still_validates_byte_for_byte(env):
    raw = (GOLDEN / 'receipt.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == GOLDEN_SHA
    s, ws = seat_golden(env)
    loaded = worker.load_receipt(env, s['node_id'], 1)
    assert loaded == json.loads(raw) and worker.receipt_version(loaded) == 1
    assert set(loaded) == worker.RECEIPT_FIELDS == worker.RECEIPT_VERSIONS[1]
    assert (ws / 'receipt.json').read_bytes() == raw and broker.sha(ws / 'receipt.json') == GOLDEN_SHA
    assert (env / 'agent-work' / s['node_id'] / '1/receipt.json').read_bytes() == raw
    # The transcript link the base code wrote is the digest the new code recomputes.
    row = json.loads((GOLDEN / 'transcript.jsonl').read_text())
    assert row['ravel']['receipt_sha256'] == worker._link_digest(loaded)


def test_a_dispatch_without_a_review_subject_still_writes_version_one(env):
    receipt = close(env, spec('plain'), real_execution('plain'))
    golden = json.loads((GOLDEN / 'receipt.json').read_text())
    assert receipt['schema_version'] == 1 and 'review_subject' not in receipt
    assert set(receipt) == set(golden) == worker.RECEIPT_FIELDS
    # A version-1 receipt is never registered for review credit.
    assert not any(r['record']['path'].startswith('agent-work/plain/') for r in rdj_custody.rows(env, 'workers'))


# ---------------------------------------------------------------- 2. version 2 binds review_subject


def test_a_review_dispatch_writes_version_two_and_binds_its_subject(env):
    facts, point = plan(env)
    subject = rp.review_subject(facts, point)
    receipt = close(env, spec('v2', point_id=point['id'], subject=subject), real_execution('v2'))
    assert receipt['schema_version'] == 2 and receipt['review_subject'] == subject
    assert set(receipt) == worker.RECEIPT_VERSIONS[2] and worker.receipt_version(receipt) == 2
    assert worker.load_receipt(env, 'v2', 1) == receipt
    row = json.loads(broker.locate(env, receipt['transcript']['path']).read_text())
    assert row['ravel']['receipt_sha256'] == worker._link_digest(receipt)

    # Changing review_subject after writing fails the digest check, even with the custody pin re-pointed.
    ws = worker.workspace(env, 'v2', 1)
    forged = {**receipt, 'review_subject': {**subject, 'sha256': '0' * 64}}
    (ws / 'receipt.json').write_text(json.dumps(forged, indent=2, sort_keys=True))
    with pytest.raises(ValueError, match='pin changed'):
        worker.load_receipt(env, 'v2', 1)
    record_path = worker._record_path(env, 'v2', 1)
    record = json.loads(record_path.read_text())
    record['receipt']['sha256'] = broker.sha(ws / 'receipt.json')
    record_path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='digest does not match'):
        worker.load_receipt(env, 'v2', 1)


@pytest.mark.parametrize('subject, point_id', [
    ({'sha256': 'a' * 64}, 'P'),                       # no scope
    ({'scope': 'claim:C1', 'sha256': 'A' * 64}, 'P'),  # not a lower-case digest
    ({'scope': '', 'sha256': 'a' * 64}, 'P'),          # empty scope
    ({'scope': 'claim:C1', 'sha256': 'a' * 64}, None),  # a subject without its review point
], ids=['no_scope', 'bad_digest', 'empty_scope', 'no_point'])
def test_a_malformed_review_subject_is_refused_at_dispatch(env, subject, point_id):
    with pytest.raises(ValueError):
        worker.materialize(env, spec('bad', point_id=point_id, subject=subject))


# ---------------------------------------------------------------- 3. credit from a real transport


def test_a_real_transport_version_two_receipt_with_a_matching_subject_earns_credit(env):
    facts, point = plan(env)
    assert not rp.satisfied(env, point['id'])
    close(env, spec('real', point_id=point['id'], subject=rp.review_subject(facts, point)), real_execution('real'))
    assert rp.satisfied(env, point['id'])
    report = next(r for r in rp.checkin3_section(env)['review_receipts'] if '/real/' in r['path'])
    assert report['attestation'] == 'transport_attested' and report['independent'] and report['advisory'] is None


@pytest.mark.parametrize('change', ['digest', 'scope', 'other_point'])
def test_a_mismatched_subject_is_refused(env, change):
    facts, point = plan(env)
    subject = rp.review_subject(facts, point)
    if change == 'digest':
        subject['sha256'] = hashlib.sha256(b'another subject').hexdigest()
    elif change == 'scope':
        subject['scope'] = 'plan'
    else:
        other = next(p for p in rp.derive(facts) if p['id'] != point['id'] and p['row'] == 4)
        subject = rp.review_subject(facts, other)
    close(env, spec('mismatch', point_id=point['id'], subject=subject), real_execution('mismatch'))
    assert not rp.satisfied(env, point['id'])
    assert advisory(env, point, 'mismatch') == 'review_subject'


def test_a_version_one_receipt_earns_no_review_credit_but_stays_valid(env):
    facts, point = plan(env)
    receipt = close(env, spec('legacy', point_id=point['id']), real_execution('legacy'))
    assert receipt['schema_version'] == 1
    # Even registered with a transport label, as receipts were before version 2, it predates the subject.
    rdj_custody.register_worker_receipt(env, 'agent-work/legacy/1/receipt.json', verified_label='transport_attested')
    assert not rp.satisfied(env, point['id'])
    assert advisory(env, point, 'legacy') == 'receipt_predates_review_subject'
    assert rp.credit_refusal(receipt, facts, point) == 'receipt_predates_review_subject'
    assert worker.load_receipt(env, 'legacy', 1) == receipt


def test_the_base_written_golden_receipt_predates_review_subject(env):
    facts, point = plan(env)
    golden = json.loads((GOLDEN / 'receipt.json').read_text())
    assert rp.credit_refusal(golden, facts, point) == 'receipt_predates_review_subject'


# ---------------------------------------------------------------- 4. the stub transport earns nothing new


def test_a_stub_transport_receipt_cannot_earn_independent_credit(env):
    facts, point = plan(env)
    receipt = close(env, spec('stub', point_id=point['id'], subject=rp.review_subject(facts, point)), stub_execution())
    assert receipt['schema_version'] == 2 and receipt['attestation'] == 'self_attested'
    row = next(r['record'] for r in rdj_custody.rows(env, 'workers') if r['record']['path'].startswith('agent-work/stub/'))
    assert row['verified_label'] == 'self_attested'
    assert not rp.satisfied(env, point['id'])
    report = next(r for r in rp.checkin3_section(env)['review_receipts'] if '/stub/' in r['path'])
    assert report['independent'] is False and report['advisory'] == 'self_attested'


def test_editing_the_attestation_field_after_registration_earns_nothing(env):
    facts, point = plan(env)
    close(env, spec('edit', point_id=point['id'], subject=rp.review_subject(facts, point)), stub_execution())
    path = env / 'agent-work/edit/1/receipt.json'
    value = json.loads(path.read_text())
    path.write_text(json.dumps({**value, 'attestation': 'transport_attested'}))
    assert not rp.satisfied(env, point['id'])
    assert advisory(env, point, 'edit') == 'receipt_unregistered'


def test_an_unregistered_version_two_receipt_earns_nothing(env, monkeypatch):
    facts, point = plan(env)
    monkeypatch.setattr(rdj_custody, 'register_worker_receipt', lambda *a, **k: None)
    close(env, spec('unreg', point_id=point['id'], subject=rp.review_subject(facts, point)), real_execution('unreg'))
    assert not rp.satisfied(env, point['id'])
    assert advisory(env, point, 'unreg') == 'receipt_unregistered'
