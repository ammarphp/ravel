"""Absent events close standing rows only with complete authenticated coverage."""
import json

import pytest

from ravel.controller import authority, graph, ledger
from ravel.controller.authority import common, standing
from ravel.controller.ledger import state
from ravel.controller.store import RunStore, JOURNAL, HEAD, StoreTampered
from test_p06_support import autonomous, operator_home  # noqa: F401

ROWS = ('A09', 'A10', 'A11', 'B05', 'C20', 'C21', 'C31', 'C32', 'C37', 'C38', 'C39', 'C40',
        'CT07', 'G06', 'G11', 'SW03', 'SW04', 'SW05')


@pytest.fixture
def run(tmp_path, operator_home):
    autonomous()
    store = RunStore.create(tmp_path / 'run', root=tmp_path / 'store')
    yield store
    state.forget(store)


def intake(store):
    identifier = store.append('intake', {'request': 'fictional request'})
    ledger.materialise(store, 'intake', {'run_id': store.run_id, 'task_mode': 'calculation', 'deliverables': ['D1']})
    return identifier


def boundary(store):
    return authority.delivery_decision(store, {'gate': 'delivery', 'plan_sha256': 'a' * 64})['id']


def instances(store):
    return {row.id: row for row in state.load(store, full=True).instances.values()}


def record(store, decision):
    with graph.services(ledger=ledger):
        return authority.record_standing_rows(store, decision)


def test_zero_events_with_registered_recorders_and_complete_chain_are_typed_na(run):
    composition = authority.register_recorders(run)
    start = intake(run)
    decision = boundary(run)
    head = run.head()
    result = record(run, decision)
    assert result['recorded'] and not result['pending']
    rows = instances(run)
    for row in ROWS:
        assert rows[row].status == 'not_applicable'
        evidence = rows[row].evidence
        assert evidence['event_kind'] == standing.ROW_EVENTS[row]
        assert evidence['journal_head_digest'] == head['digest'] and evidence['event_count'] == 0
        assert evidence['composition'] == composition['id']
        assert evidence['verified_range'] == {'from_seq': 1, 'through_seq': head['seq'], 'intake': start,
                                               'delivery_decision': decision, 'decision_seq': head['seq']}
    # No ordinary duty or conserved original deliverable is waved through by the absence path.
    assert rows['R05'].status == rows['CT01'].status == 'pending'
    assert rows['C25'].status == 'pending'  # the run-binding event did occur
    assert all(row.status != 'satisfied' for row in rows.values())


@pytest.mark.parametrize('fault', ['chain_gap', 'tampered', 'late_recorder', 'missing_recorder',
                                  'unissued_composition', 'changed_recorder', 'incomplete_append',
                                  'missing_decision', 'foreign_decision', 'head_tampered', 'rechained'])
def test_each_failed_precondition_leaves_the_row_pending(run, fault):
    if fault not in ('late_recorder', 'missing_recorder', 'unissued_composition'):
        authority.register_recorders(run)
    intake(run)
    if fault == 'late_recorder':
        authority.register_recorders(run)
    if fault == 'unissued_composition':
        run.append(standing.COMPOSITION, {'schema': standing.COMPOSITION_SCHEMA, 'uid': 'forged',
                                         'run_id': run.run_id, 'recorders': {}})
    if fault == 'changed_recorder':
        # An authenticated composition missing this specific recorder does not prove coverage.
        # Append a new run instead of changing the old MAC or backdating registration.
        from unittest.mock import patch
        with patch.object(standing, '_definition', return_value={'different': 'definition'}):
            decision = boundary(run)
            assert standing.absence_evidence(run, decision) == {}
            record(run, decision)
        assert instances(run)['A09'].status == 'pending'
        return
    decision = boundary(run)
    run.head()  # warm the incremental cache: fresh verification must still catch earlier edits
    path = run.root / JOURNAL
    lines = path.read_bytes().splitlines(keepends=True)
    if fault == 'chain_gap':
        path.write_bytes(b''.join(lines[:1] + lines[2:]))
    elif fault == 'tampered':
        assert b'fictional request' in b''.join(lines)
        path.write_bytes(b''.join(lines).replace(b'fictional request', b'fabricat request'))
    elif fault == 'incomplete_append':
        with path.open('ab') as stream:
            stream.write(b'{"unfinished":')
    elif fault == 'rechained':
        from ravel.controller.store import _digest, GENESIS
        # A complete rewrite with new envelope hashes cannot change the issuer's
        # authenticated decision-boundary commitment to the original chain head.
        rewritten, previous = [], GENESIS
        for raw in lines:
            entry = json.loads(raw)
            if entry['kind'] == 'intake':
                entry['record']['request'] = 'different request'
            entry['prev'] = previous
            body = {k: v for k, v in entry.items() if k not in ('id', 'digest')}
            entry['id'] = f"{entry['kind']}-{entry['seq']:06d}-{_digest(body)[:12]}"
            entry['digest'] = _digest({k: v for k, v in entry.items() if k != 'digest'})
            previous = entry['digest']
            rewritten.append(entry)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rewritten))
        (run.root / HEAD).write_text(json.dumps({'seq': len(rewritten), 'digest': previous}))
    elif fault == 'head_tampered':
        (run.root / HEAD).write_text(json.dumps({'seq': run.head()['seq'], 'digest': 'f' * 64}))
    elif fault == 'missing_decision':
        decision = None
    elif fault == 'foreign_decision':
        decision = 'delivery-decision-foreign'
    assert standing.absence_evidence(run, decision) == {}
    # The ledger was already cached. Failure of the journal proof must write nothing,
    # including when a fresh ledger read itself would refuse the corrupt journal.
    before = path.read_bytes()
    assert record(run, decision) == {'recorded': [], 'pending': []}
    assert path.read_bytes() == before
    if fault == 'incomplete_append':
        # A reader refuses the never-acknowledged crash tail; append recovery discards only those bytes.
        with pytest.raises(StoreTampered, match='incomplete'):
            instances(run)
        run.append('observation', {'value': 'after recovery'})
    if fault not in ('chain_gap', 'tampered', 'head_tampered', 'rechained'):
        assert instances(run)['A09'].status == 'pending'


@pytest.mark.parametrize('kind, body, affected', [
    ('authority-request', {'kind': 'deviation'}, ('A09', 'C20', 'C21', 'C31', 'C32')),
    ('authority', {'kind': 'revoke'}, ('A10', 'B05', 'C40', 'G06', 'SW05')),
    ('authority-request', {'kind': 'r3_action', 'subject': {'gate': 'unblind'}}, ('A11', 'G11')),
    ('authority-request', {'kind': 'steering'}, ('C37', 'C38', 'C39', 'SW03')),
    ('authority', {'label': common.LEGACY_TERMINAL}, ('CT07',)),
    ('judgment-event', {'event': 'replan_requested'}, ('JR07',)),
    ('authority-request', {'kind': 'escalation'}, ('JR08',)),
])
def test_one_event_present_is_never_reclassified_as_absent(run, kind, body, affected):
    authority.register_recorders(run)
    intake(run)
    run.append(kind, body)
    decision = boundary(run)
    evidence = standing.absence_evidence(run, decision)
    assert not set(affected) & set(evidence)
    record(run, decision)
    rows = instances(run)
    for row in affected:
        if row in rows:
            assert rows[row].status == 'pending'
    assert rows['CT07'].status == ('pending' if 'CT07' in affected else 'not_applicable')


def test_executed_evidence_is_preserved_and_registration_cannot_be_backdated(run):
    first = authority.register_recorders(run)
    intake(run)
    key = ledger.instance_key('A09', run.run_id, {})
    executed = run.append('executed-deviation', {'parameter': 'precision'})
    ledger.record(run, key, 'satisfied', {'record': executed})
    assert authority.register_recorders(run) == first
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'satisfied'
    assert instances(run)['A09'].evidence == {'record': executed}


def test_events_after_an_older_boundary_are_not_hidden_by_its_range(run):
    authority.register_recorders(run)
    intake(run)
    decision = boundary(run)
    run.append('authority-request', {'kind': 'deviation'})
    record(run, decision)
    assert instances(run)['A09'].status == 'pending'


def test_registration_of_another_event_kind_does_not_credit_a_missing_recorder(run):
    definitions = {kind: standing._definition(kind) for kind in standing.PRODUCERS if kind != 'deviation'}
    common.append(run, standing.COMPOSITION, {
        'schema': standing.COMPOSITION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
        'run_id': run.run_id, 'time_ns': common.now_ns(), 'journal_head': run.head(),
        'recorders': definitions})
    intake(run)
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'pending'
    assert instances(run)['CT07'].status == 'not_applicable'


def test_late_registration_of_one_kind_cannot_repair_missing_intake_coverage(run):
    partial = {kind: standing._definition(kind) for kind in standing.PRODUCERS if kind != 'deviation'}
    for when in ('before', 'after'):
        common.append(run, standing.COMPOSITION, {
            'schema': standing.COMPOSITION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
            'run_id': run.run_id, 'time_ns': common.now_ns(), 'journal_head': run.head(),
            'recorders': partial if when == 'before' else {
                kind: standing._definition(kind) for kind in standing.PRODUCERS}})
        if when == 'before':
            intake(run)
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'pending'
    assert instances(run)['CT07'].status == 'not_applicable'


def test_a_resumed_delivery_cannot_reuse_absence_after_an_event_occurs(run):
    authority.register_recorders(run)
    intake(run)
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'not_applicable'
    run.append('authority-request', {'kind': 'deviation'})
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'violated'
    assert instances(run)['CT07'].status == 'not_applicable'
    assert run.latest('standing-row-revalidation')['record']['rows']['CT07']['event_count'] == 0


def test_a_recorder_coverage_gap_cannot_be_hidden_by_later_reregistration(run):
    authority.register_recorders(run)
    intake(run)
    for enabled in (False, True):
        definitions = {kind: standing._definition(kind) for kind in standing.PRODUCERS
                       if enabled or kind != 'deviation'}
        common.append(run, standing.COMPOSITION, {
            'schema': standing.COMPOSITION_SCHEMA, 'schema_version': 1, 'uid': common.uid(),
            'run_id': run.run_id, 'time_ns': common.now_ns(), 'journal_head': run.head(),
            'recorders': definitions})
    record(run, boundary(run))
    assert instances(run)['A09'].status == 'pending'
    assert instances(run)['CT07'].status == 'not_applicable'
