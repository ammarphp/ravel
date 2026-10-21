"""A decide step's C01, E28 and C08 come from the actions that enforce them.

C01 (method ladder) and E28 (operating protocol) are discharged only by the step's RDJ case as the plan-approval
mapping credits it, and only when the packet that RDJ seat was delivered carried the method ladder and the protocol
units the step needs. C08 comes from the step's own judgment record as the governed step stored it, checked against
the step as planned once the controller's decide close found it: not applicable, citing the record, when the decision
adopted no default. The collaborators stand in for the ledger, the store and the mapping; the gate drives the same
path on the real ones.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller import graph as controller_graph
from ravel.controller.instructions import catalogue as instruction_catalogue
from ravel.controller.judgment import checkins, records, steps
from ravel.workflow import rdj_approval

RUN = 'run-fixture'
NODES = {'C01': 'judgment.method_ladder', 'E28': 'judgment.protocol', 'C08': 'judgment.default'}
RDJ_STEP = 'judgment-rdj-choose-0-1'
STEP = {'id': 'choose', 'kind': 'decide', 'protocols': [], 'consequence_class': 'R2',
        'parameters': {'judgment': {'triggers': [], 'spec_sha256': 'a' * 64,
                                    'action': {'summary': 'Choose the method.'}}}}


class Store:
    def __init__(self):
        self.rows = []

    def append(self, kind, record):
        identifier = f'{kind}-{len(self.rows) + 1:06d}-fixture'
        self.rows.append({'id': identifier, 'kind': kind, 'seq': len(self.rows) + 1,
                          'record': json.loads(json.dumps(record))})
        return identifier

    def scan(self, kind):
        return [json.loads(json.dumps(r)) for r in self.rows if r['kind'] == kind]

    def read(self, kind, identifier):
        return next(json.loads(json.dumps(r)) for r in self.rows if r['id'] == identifier)


class Ledger:
    def __init__(self, rows):
        self.open = [f'{row}@{RUN}/step=choose' for row in rows]
        self.recorded = {}

    def pending(self, store, *, node=None, step=None, **_):
        return [k for k in self.open if NODES[k.split('@')[0]] == node and f'/step={step}' in k]

    def record_many(self, store, changes):
        for key, status, evidence in changes:
            self.open.remove(key)
            self.recorded[key.split('@')[0]] = (status, evidence)


@pytest.fixture
def ledger(monkeypatch):
    found = Ledger(NODES)
    monkeypatch.setattr(controller_graph, 'service', lambda name: found if name == 'ledger' else None)
    return found


def _units(*selectors):
    catalogue = instruction_catalogue.installed()
    return sorted({u for s in selectors for u in catalogue.resolve(s)})


def _delivered(store, units):
    store.append('instruction-packet', {'step_id': RDJ_STEP, 'manifest': {'sha256': 'm' * 64,
                                                                          'units': [{'id': u} for u in units]}})
    store.append('instruction-delivery', {'kind': 'instruction-delivery-session', 'delivery': 'delivery-000001-x',
                                          'manifest_sha256': 'm' * 64, 'step_id': RDJ_STEP})


@pytest.mark.parametrize('selectors, recorded', [
    ((steps.METHOD_LADDER, 'protocol:common'), {'C01', 'E28'}),
    (('protocol:common',), {'E28'}),
    ((), set()),
])
def test_C01_E28_are_discharged_by_the_credited_rdj_case_only_for_the_duties_its_seat_was_delivered(
        ledger, monkeypatch, selectors, recorded):
    store = Store()
    monkeypatch.setattr(rdj_approval, 'case', lambda s, digest: (
        {'credit': 'step-credit-000009-x', 'step_id': RDJ_STEP, 'session': 'session-1'}, None))
    _delivered(store, _units(*selectors))
    checkins._decide_rows(store, {'steps': [STEP]})
    assert set(ledger.recorded) == recorded
    for row in recorded:
        status, evidence = ledger.recorded[row]
        assert status == 'satisfied' and evidence['credit'] == 'step-credit-000009-x'
        assert evidence['instruction_receipt'] == 'delivery-000001-x' and evidence['rdj_step'] == RDJ_STEP


def test_C01_E28_stay_pending_without_a_credited_approving_rdj_case(ledger, monkeypatch):
    store = Store()
    monkeypatch.setattr(rdj_approval, 'case', lambda s, digest: (None, 'its RDJ case has verdict revise, not approve'))
    _delivered(store, _units(steps.METHOD_LADDER, 'protocol:common'))
    checkins._decide_rows(store, {'steps': [STEP]})
    assert ledger.recorded == {} and len(ledger.open) == 3


def _record(**changes):
    record = {'schema_version': 1, 'kind': 'judgment-record', 'id': 'judgment-choose', 'step': 'choose',
              'question': 'Which method?', 'chosen': 'direct', 'rationale': 'The cheaper sufficient method.',
              'options': [{'id': 'direct', 'description': 'Derive directly.', 'predicted_consequences': 'Exact.'},
                          {'id': 'sampled', 'description': 'Sample.', 'predicted_consequences': 'Noisy.'}],
              'action': {'summary': 'Choose the method.'}, 'triggers': [], 'protocol_evidence': {},
              'reversibility': {'kind': 'reversible', 'note': 'Before any effect.'},
              'budget_impact': {'note': 'Nothing is spent.'}}
    record.update(changes)
    return record


def _stored(store, record, *, step=None):
    """The record as the governed step's validate node stores it (``records.record_judgment``) and the controller's
    decide close reads it back: the stored body with its ``judgment_id``."""
    identifier = records.record_judgment(store, record, step=step, plan_class='R2')
    return {**store.read('judgment-record', identifier)['record'], 'judgment_id': identifier}


def test_C08_a_decision_that_adopts_no_default_is_not_applicable_citing_its_stored_record(ledger):
    store = Store()
    stored = _stored(store, _record(), step={'id': 'choose', 'kind': 'decide', 'protocols': []})
    assert checkins.decided(STEP, stored, {'store': store}) == []
    status, evidence = ledger.recorded['C08']
    assert status == 'not_applicable' and evidence['reason'] == 'not_applicable:no_default_adopted'
    assert evidence['record'] == stored['judgment_id'] and evidence['sha256'] == stored['record_sha256']
    assert evidence['chosen'] == 'direct'
    # The route check stores nothing: the validate node is the one place a record is stored.
    assert len([r for r in store.rows if r['kind'] == 'judgment-record']) == 1


@pytest.mark.parametrize('step, record, expected', [
    # Stored without its step's planned triggers, the record still has to satisfy the step as planned.
    ({**STEP, 'parameters': {'judgment': {**STEP['parameters']['judgment'], 'triggers': ['adopt_default']}}},
     _record(), 'did not receive the instruction units of'),
    (STEP, _record(step='other'), "names step 'other'"),
])
def test_a_stored_record_that_does_not_satisfy_the_planned_step_holds_it_and_discharges_nothing(ledger, step, record,
                                                                                               expected):
    store = Store()
    stored = _stored(store, record)
    problems = checkins.decided(step, stored, {'store': store})
    assert any(expected in p for p in problems), problems
    assert ledger.recorded == {}


def test_a_step_that_is_not_a_decision_is_not_checked(ledger):
    assert checkins.decided({**STEP, 'kind': 'derive'}, {}, {'store': Store()}) == []
