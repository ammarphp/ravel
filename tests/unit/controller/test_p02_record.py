"""P02 status recording: allowed transitions, evidence, waivers, conservation, tamper detection and the clock."""
from __future__ import annotations

import json
import importlib
import threading
import time

import pytest

from ravel.controller import ledger
from ravel.controller.ledger import state as state_module
from p02_support import (INTAKE, PLAN, RUN, FakeStore, authority, fixture_store,  # noqa: F401
                              satisfy)


def k(row, **scope):
    return ledger.instance_key(row, RUN, scope)


@pytest.fixture
def run(fixture_store):
    ledger.materialise(fixture_store, 'intake', INTAKE)
    ledger.materialise(fixture_store, 'plan', {'plan': PLAN, 'route': 'analysis'})
    return fixture_store


def code(callable_, *args):
    with pytest.raises(ledger.LedgerError) as raised:
        callable_(*args)
    return raised.value.code


@pytest.fixture(autouse=True)
def authenticated_reader(monkeypatch):
    """An explicit authority-service fake for the existing record-class controls.

    These unsigned fixture records test scope and labels after authentication. Production authentication is the
    injected provider's responsibility; the missing-reader and rejected-reader controls below exercise refusal.
    """
    module = importlib.import_module('ravel.controller.ledger.record')
    monkeypatch.setattr(module, '_authority_reader', None)

    def read(store, record_id):
        for envelope in store.scan('authority'):
            body = envelope.get('record', envelope)
            if record_id in (body.get('uid'), envelope.get('id'), body.get('id')):
                return body
        raise KeyError(record_id)

    ledger.register_authority_reader(read)


# ---- transitions ----------------------------------------------------------------------------------------

STEPS = {
    'satisfied': {'mechanism': 'fixture'},
    'violated': {'reason': 'fixture violation'},
    'not_applicable': {'reason': 'fixture reason'},
}


@pytest.mark.parametrize('first,second,allowed', [
    ('satisfied', 'satisfied', True), ('satisfied', 'violated', True), ('satisfied', 'not_applicable', False),
    ('violated', 'satisfied', False), ('violated', 'violated', False), ('violated', 'not_applicable', False),
    ('not_applicable', 'violated', True), ('not_applicable', 'satisfied', False),
    ('not_applicable', 'not_applicable', False),
])
def test_p02_only_allowed_transitions_are_recorded(run, first, second, allowed):
    entry = k('X-INTAKE')
    ledger.record(run, entry, first, STEPS[first])
    if allowed:
        ledger.record(run, entry, second, STEPS[second])
        assert state_module.load(run, full=True).instances[entry].status == second
    else:
        assert code(ledger.record, run, entry, second, STEPS[second]) == 'transition_refused'
        assert state_module.load(run, full=True).instances[entry].status == first


def test_p02_violated_is_final_and_nothing_returns_to_pending(run):
    entry = k('X-INTAKE')
    assert code(ledger.record, run, entry, 'pending', {'reason': 'x'}) == 'transition_refused'
    ledger.record(run, entry, 'violated', {'reason': 'refused launch', 'refusal': {'code': 'no_authority'}})
    for status in ('satisfied', 'waived', 'not_applicable', 'violated', 'pending'):
        assert code(ledger.record, run, entry, status, {'reason': 'x', 'mechanism': 'x'}) in (
            'transition_refused', 'waiver_refused', 'authority_missing')
    assert code(ledger.record, run, 'X-INTAKE@run-two', 'satisfied', {'mechanism': 'x'}) == 'entry_unknown'
    assert code(ledger.record, run, entry, 'done', {}) == 'status_unknown'


# ---- evidence ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('entry,status,evidence,expected', [
    ('X-INTAKE', 'satisfied', {}, 'evidence_missing'),
    ('X-INTAKE', 'satisfied', {'note': 'looks fine'}, 'evidence_missing'),
    ('X-INTAKE', 'violated', {'refusal': {'code': 'x'}}, 'reason_missing'),
    ('X-INTAKE', 'not_applicable', {'mechanism': 'x'}, 'reason_missing'),
    ('X-INTAKE', 'satisfied', {'mechanism': ('tuple',)}, 'evidence_invalid'),
    ('X-INTAKE', 'satisfied', {'mechanism': float('nan')}, 'evidence_invalid'),
    ('X-INTAKE', 'satisfied', {'mechanism': 'x' * 70000}, 'evidence_invalid'),
    ('X-INTAKE', 'satisfied', ['mechanism'], 'evidence_invalid'),
])
def test_p02_each_status_needs_its_evidence(run, entry, status, evidence, expected):
    assert code(ledger.record, run, k(entry), status, evidence) == expected


def test_p02_review_gated_rows_need_a_credit_and_instructed_rows_an_acknowledgement(run):
    review = ledger.materialise(run, 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1})
    credit_row = next(key for key in review if key.startswith('X-REVIEW@'))
    assert code(ledger.record, run, credit_row, 'satisfied', {'receipt': 'r1'}) == 'credit_missing'
    assert code(ledger.record, run, credit_row, 'not_applicable', {'reason': 'no subject'}) == 'credit_missing'
    ledger.record(run, credit_row, 'satisfied', {'credit': 'credit-7'})
    seat = ledger.materialise(run, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    instructed = next(key for key in seat if key.startswith('X-ROLE-maker@'))
    assert code(ledger.record, run, instructed, 'satisfied', {'instruction_receipt': 'i1'}) == 'ack_missing'
    ledger.record(run, instructed, 'satisfied', {'instruction_receipt': 'i1', 'ack': 'checklist#3'})


# ---- waivers -------------------------------------------------------------------------------------------

@pytest.mark.parametrize('row,stage,context', [
    ('X-SEAT', 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'}),   # independence
    ('X-REVIEW', 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1}),                          # review credit
    ('X-LAUNCH', 'dispatch', {'step': 's2', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'launch',
                              'point': 'p1'}),                                                        # confinement
    ('X-ROLE-maker', 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 2, 'seat_kind': 'worker'}),  # instruction
    ('X-ART', 'deliver', {'artifacts': ['a1']}),                                                      # sink, custody
    ('X-SINK', 'deliver', {'artifacts': ['a1']}),
    ('GATE-launch', None, None),                                                                      # inner guard
])
def test_p02_waiver_refused_for_each_non_waivable_class(run, row, stage, context):
    keys = ledger.materialise(run, stage, context) if stage else ledger.pending(run)
    entry = next(key for key in keys if key.startswith(f'{row}@'))
    uid = authority(run, obligations=[row, entry])
    assert code(ledger.record, run, entry, 'waived', {'authority': uid}) == 'waiver_refused'
    assert state_module.load(run, full=True).instances[entry].status == 'pending'


def test_p02_installed_non_waivable_classes_cannot_be_waived():
    catalogue = ledger.load_catalogue()
    samples = {
        'independence': [r for r in catalogue.rows.values() if r['ledger_class'] == 'delegation/independence'],
        'review credit': [r for r in catalogue.rows.values() if r['ledger_class'] == 'review/credit'],
        'custody': [r for r in catalogue.rows.values() if 'M09' in r['mechanisms']],
        'sink': [r for r in catalogue.rows.values() if r['node'] == 'controller.deliver' and r['id'] != 'D02'],
        'confinement': [r for r in catalogue.rows.values() if 'M08' in r['mechanisms']],
        'instruction': [r for r in catalogue.rows.values() if r['class'] == 'I' or 'M12' in r['mechanisms']],
    }
    for name, rows in samples.items():
        assert rows, name
        assert all(r['waivability'] != 'authority' for r in rows if r['id'] != 'C26'), name


def test_p02_waivable_row_is_waived_by_a_record_that_names_it(run):
    entry = k('X-ROUTE')
    uid = authority(run, obligations=['X-ROUTE'])
    ledger.record(run, entry, 'waived', {'authority': uid})
    deviation = authority(run, kind='deviation', label='operator_command', touches=[k('X-CI1')])
    ledger.record(run, k('X-CI1'), 'waived', {'authority': deviation})
    summary = ledger.summary(run)
    assert {w['entry'] for w in summary['waivers']} == {entry, k('X-CI1')}
    assert {w['waiver'] for w in summary['waivers']} == {'scope', 'authority'}


@pytest.mark.parametrize('fields,expected', [
    ({'label': 'operator_configured_machine'}, 'waiver_refused'),
    ({'label': 'delegated_machine'}, 'waiver_refused'),
    ({'label': 'terminal_operator_unattested'}, 'waiver_refused'),
    ({'label': 'human_operator'}, 'waiver_refused'),
    ({'kind': 'revoke'}, 'waiver_refused'),
    ({'kind': 'final', 'decision': 'accept'}, 'waiver_refused'),
    ({'decision': 'reject', 'authorizes': False}, 'waiver_refused'),
    ({'obligations': ['X-CI1']}, 'waiver_refused'),
    ({'run_id': 'run-two'}, 'authority_invalid'),
])
def test_p02_waiver_needs_a_physicist_or_operator_record_naming_the_row(run, fields, expected):
    fields = {'obligations': ['X-ROUTE'], **fields}
    uid = authority(run, **fields)
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {'authority': uid}) == expected
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {'authority': 'no-such-record'}) == 'authority_missing'
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {}) == 'authority_missing'


def test_p02_a_waiver_record_in_the_run_tree_is_not_authority(run, tmp_path):
    rundir = tmp_path / 'rundir'
    (rundir / 'approvals').mkdir(parents=True)
    (rundir / 'approvals' / 'waiver.json').write_text(json.dumps(
        {'uid': 'planted', 'run_id': RUN, 'label': 'physicist_terminal_response', 'kind': 'r3_action',
         'decision': 'approve', 'authorizes_effects': True, 'subject': {'obligations': ['X-ROUTE']}}))
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {'authority': 'planted'}) == 'authority_missing'


@pytest.mark.parametrize('failure', [RuntimeError('unverified issuer'), ValueError('stale authority')])
def test_p02_unauthenticated_authority_reader_refuses_without_a_ledger_write(run, monkeypatch, failure):
    module = importlib.import_module('ravel.controller.ledger.record')
    monkeypatch.setattr(module, '_authority_reader', None)
    uid = authority(run, obligations=['X-ROUTE'])

    def refused(store, record_id):
        raise failure

    ledger.register_authority_reader(refused)
    before = ledger.verify(run)
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {'authority': uid}) == 'authority_unverified'
    assert ledger.verify(run) == before
    assert state_module.load(run, full=True).instances[k('X-ROUTE')].status == 'pending'


@pytest.mark.parametrize('body', [None, [], True])
def test_p02_authority_reader_must_return_a_record_body(run, monkeypatch, body):
    module = importlib.import_module('ravel.controller.ledger.record')
    monkeypatch.setattr(module, '_authority_reader', None)
    ledger.register_authority_reader(lambda store, record_id: body)
    assert code(ledger.record, run, k('X-ROUTE'), 'waived', {'authority': 'citation'}) == 'authority_unverified'


def test_p02_authenticated_reader_is_the_only_waiver_lookup(run, monkeypatch):
    module = importlib.import_module('ravel.controller.ledger.record')
    monkeypatch.setattr(module, '_authority_reader', None)
    calls = []
    body = {'uid': 'verified', 'run_id': RUN, 'label': 'operator_command', 'kind': 'r3_action',
            'decision': 'approve', 'authorizes_effects': True, 'subject': {'obligations': ['X-ROUTE']}}

    def read(store, record_id):
        calls.append((store, record_id))
        return body

    scan = run.scan

    def no_raw_authority(kind):
        assert kind != 'authority'
        return scan(kind)

    monkeypatch.setattr(run, 'scan', no_raw_authority)
    ledger.register_authority_reader(read)
    ledger.register_authority_reader(read)
    with pytest.raises(ValueError):
        ledger.register_authority_reader(lambda store, record_id: body)
    with pytest.raises(TypeError):
        ledger.register_authority_reader(None)
    ledger.record(run, k('X-ROUTE'), 'waived', {'authority': 'verified'})
    assert calls == [(run, 'verified')]
    assert state_module.load(run, full=True).instances[k('X-ROUTE')].status == 'waived'


# ---- conservation of original obligations (R05) -------------------------------------------------------------

def close_step_one(run):
    ledger.materialise(run, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    ledger.materialise(run, 'review', {'step': 's1', 'seat': 'checker', 'attempt': 1})
    satisfy(run, [key for key in ledger.pending(run, step='s1')])


def test_p02_conserved_obligation_needs_a_closed_covering_step(run):
    entry = k('X-KEEP', deliverable='D1')
    assert code(ledger.record, run, entry, 'satisfied', {'mechanism': 'x'}) == 'cover_missing'
    assert code(ledger.record, run, entry, 'satisfied', {'covered_by': ['s2']}) == 'cover_refused'   # not D1's step
    assert code(ledger.record, run, entry, 'satisfied', {'covered_by': ['s1']}) == 'cover_refused'   # s1 not closed
    assert code(ledger.record, run, entry, 'not_applicable', {'reason': 'dropped'}) == 'conservation_refused'
    close_step_one(run)
    ledger.record(run, entry, 'satisfied', {'covered_by': ['s1']})
    other = k('X-KEEP', deliverable='D2')
    uid = authority(run, obligations=[other])
    ledger.record(run, other, 'waived', {'authority': uid})   # an authorized boundary covers it
    assert ledger.summary(run)['deliverables']['open'] == []


def test_p02_parent_join_satisfies_only_covered_obligations(run):
    assert ledger.parent_join(run) == []
    close_step_one(run)
    assert ledger.parent_join(run) == [k('X-KEEP', deliverable='D1')]
    state = state_module.load(run, full=True)
    assert state.instances[k('X-KEEP', deliverable='D2')].status == 'pending'
    assert state.instances[k('X-KEEP', deliverable='D1')].evidence['covered_by'] == ['s1']


# ---- the chain ---------------------------------------------------------------------------------------------

def tampered(run, mutate):
    entries = run.entries()
    mutate(entries)
    run.rewrite(entries)
    state_module.forget(run)


def ledger_lines(entries):
    return [i for i, e in enumerate(entries) if e['kind'] == 'ledger']


@pytest.mark.parametrize('mutation', ['edit', 'delete', 'swap', 'duplicate', 'reseal-without-prev', 'foreign'])
def test_p02_tampered_chain_is_detected(run, mutation):
    satisfy(run, [k('X-INTAKE')])
    before = ledger.verify(run)
    assert before['verified'] and before['events'] == 3

    def mutate(entries):
        lines = ledger_lines(entries)
        if mutation == 'edit':
            entries[lines[2]]['record']['body']['changes'][0]['to'] = 'waived'
        elif mutation == 'delete':
            del entries[lines[1]]
        elif mutation == 'swap':
            entries[lines[1]], entries[lines[2]] = entries[lines[2]], entries[lines[1]]
            entries[lines[1]]['record']['seq'], entries[lines[2]]['record']['seq'] = 1, 2
        elif mutation == 'duplicate':
            entries.append(json.loads(json.dumps(entries[lines[2]])))
        elif mutation == 'reseal-without-prev':
            from ravel.controller.ledger import chain
            record = entries[lines[1]]['record']
            record['body']['instances'] = record['body']['instances'][:1]
            entries[lines[1]]['record'] = chain.seal(record['seq'], record['prev'], record['body'])
        else:
            from ravel.controller.ledger import chain
            entries.append({**entries[lines[2]], 'record': chain.seal(3, '1' * 64, {'event': 'status', 'run_id': RUN,
                                                                                    'time_ns': 1, 'changes': []})})
    tampered(run, mutate)
    result = ledger.verify(run)
    assert not result['verified'] and result['error']
    assert [row['reason'] for row in ledger.gate(run, 'deliver[qualified]')] == ['chain_broken']
    assert [row['reason'] for row in ledger.gate(run, 'intake→route_select')] == ['chain_broken']
    assert ledger.summary(run)['chain']['verified'] is False
    assert code(ledger.record, run, k('X-ROUTE'), 'satisfied', {'mechanism': 'x'}) == 'chain_broken'
    assert code(ledger.materialise, run, 'deliver', {'artifacts': ['a1']}) == 'chain_broken'


def test_p02_a_shortened_ledger_is_detected_by_the_process_that_saw_it(run):
    satisfy(run, [k('X-INTAKE')])
    head = ledger.verify(run)['head']
    entries = run.entries()
    run.rewrite([e for e in entries if e is not entries[ledger_lines(entries)[-1]]])
    result = ledger.verify(run)
    assert not result['verified'] and 'lost events' in result['error']
    state_module.forget(run)   # a fresh process sees a shorter valid chain: the receipt's head digest differs
    assert ledger.verify(run)['head'] != head


def test_p02_store_bookkeeping_and_envelopes_do_not_change_the_ledger(tmp_path, monkeypatch):
    from p02_support import fixture_catalogue, use_catalogue
    use_catalogue(monkeypatch, fixture_catalogue())
    heads = []
    for bare in (False, True):
        store = FakeStore(RUN, root=tmp_path / str(bare), bare=bare)
        ledger.materialise(store, 'intake', INTAKE)
        ledger.record(store, k('X-INTAKE'), 'satisfied', {'mechanism': 'fixture'})
        state = state_module.load(store, full=True)
        heads.append(({key: i.status for key, i in state.instances.items()}, state.events))
        state_module.forget(store)
    assert heads[0] == heads[1]


def test_p02_events_use_the_controller_clock_not_clock_variables(run, monkeypatch):
    for name in ('WORKFLOW_STATE_UTC', 'GATE_TIMESTAMP', 'RAVEL_CLOCK_UTC', 'SOURCE_DATE_EPOCH'):
        monkeypatch.setenv(name, '2001-01-01T00:00:00Z' if 'UTC' in name else '978307200')
    before = time.time_ns()
    ledger.record(run, k('X-INTAKE'), 'satisfied', {'mechanism': 'fixture'})
    after = time.time_ns()
    stamped = run.scan('ledger')[-1]['record']['body']['time_ns']
    assert before <= stamped <= after


def test_p02_a_batch_is_recorded_whole_or_not_at_all(run):
    events = len(run.scan('ledger'))
    assert code(ledger.record_many, run, [(k('X-INTAKE'), 'satisfied', {'mechanism': 'x'}),
                                          (k('X-ROUTE'), 'satisfied', {})]) == 'evidence_missing'
    assert len(run.scan('ledger')) == events
    assert code(ledger.record_many, run, [(k('X-INTAKE'), 'satisfied', {'mechanism': 'x'}),
                                          (k('X-INTAKE'), 'violated', {'reason': 'x'})]) == 'change_invalid'
    ledger.record_many(run, [])
    assert len(run.scan('ledger')) == events


def test_p02_concurrent_writers_keep_one_chain(run):
    keys = ledger.pending(run)
    keys = [key for key in keys if '/deliverable=' not in key][:8]
    errors = []

    def write(key):
        try:
            satisfy(run, [key])
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(key,)) for key in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    result = ledger.verify(run)
    assert result['verified'] and result['events'] == 2 + len(keys)
    state = state_module.load(run, full=True)
    assert all(state.instances[key].status == 'satisfied' for key in keys)


def test_p02_refusals_are_counted_for_the_receipt(run):
    ledger.record(run, k('X-STANDING'), 'satisfied', {'mechanism': 'command policy'})
    ledger.record(run, k('X-STANDING'), 'satisfied', {'mechanism': 'command policy',
                                                      'refusal': {'command': 'approve', 'code': 'controller_owned'}})
    seat = ledger.materialise(run, 'dispatch', {'step': 's1', 'seat': 'maker', 'attempt': 1, 'seat_kind': 'worker'})
    tool = next(key for key in seat if key.startswith('X-SEAT@'))
    ledger.record(run, tool, 'violated', {'reason': 'tool outside the belt', 'refusal': {'tool': 'shell'}})
    summary = ledger.summary(run)
    assert summary['refusals'] == 2
    assert {r['entry'] for r in summary['refusal_events']} == {k('X-STANDING'), tool}
    assert [v['entry'] for v in summary['violations']] == [tool]
