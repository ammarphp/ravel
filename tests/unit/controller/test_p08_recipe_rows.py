"""C36 and JR04 of a judgment-route run at CHECK-IN 3: the recipe ledger the plan was approved with is preserved, and
every plan step ran through the governed step graph.

The approval (CHECK-IN 1, or a deviation's renewed approval) snapshots the recipe ledger and pins its digest in the
view; CHECK-IN 3 snapshots it again, names the approval snapshot it continues, shows every unknown and deviated row
and records C36 from the comparison. The collaborators stand in for the ledger, the store and the recipe ledger's
rebuild (``_recipe_rows``); the gate drives the same path on the real ones.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller import graph as controller_graph
from ravel.controller.judgment import checkins

RUN = 'run-fixture'
PLAN = {'sha256': 'a' * 64, 'steps': [{'id': 'derive', 'kind': 'derive', 'budget': {}}],
        'deliverables': [{'id': 'D1'}], 'parameters': {}}


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


NODES = {'C36': 'authority.ci3', 'JR04': 'judgment.fanout'}


class Ledger:
    def __init__(self):
        self.open = [f'C36@{RUN}']
        self.recorded = {}

    def pending(self, store, *, node=None, step=None, **_):
        return [k for k in self.open if NODES[k.split('@')[0]] == node and step is None]

    def record_many(self, store, changes):
        for key, status, evidence in changes:
            self.open.remove(key)
            self.recorded[key.split('@')[0]] = (status, evidence)


@pytest.fixture
def ledger(monkeypatch):
    found = Ledger()
    monkeypatch.setattr(controller_graph, 'service', lambda name: found if name == 'ledger' else None)
    return found


def _row(identity, status, requested=1.0, effective=1.0):
    return {'id': identity, 'layer': 'operation', 'field': '/' + identity, 'node_id': 'N1', 'claim_id': None,
            'requested': requested, 'requested_present': True, 'effective': effective, 'status': status}


def _views(monkeypatch, tmp_path, approved_rows, final_rows):
    store = Store()
    context = {'store': store, 'run_dir': tmp_path, 'plan': PLAN, 'state': {'plan': {'approved_sha256': PLAN['sha256']}}}
    monkeypatch.setattr(checkins, '_recipe_rows', lambda run_dir: approved_rows)
    approval = checkins.checkin('approve_plan', context)
    monkeypatch.setattr(checkins, '_recipe_rows', lambda run_dir: final_rows)
    return store, approval, checkins.checkin('final', context)


def test_C36_is_satisfied_when_checkin3_keeps_every_approved_row_and_shows_every_unknown_one(ledger, monkeypatch,
                                                                                              tmp_path):
    approved = [_row('r1', 'unknown', effective=None), _row('r2', 'matched')]
    # r1's effective value was observed after the approval: a status that moved is evidence, not a change.
    final = [_row('r1', 'matched'), _row('r2', 'matched'), _row('r3', 'unknown', effective=None)]
    store, approval, view = _views(monkeypatch, tmp_path, approved, final)
    snapshots = [r for r in store.rows if r['kind'] == checkins.RECIPE]
    assert [s['record']['checkin'] for s in snapshots] == ['approve_plan', 'final']
    assert snapshots[1]['record']['previous'] == snapshots[0]['id']
    assert approval['pins'] == {'recipe_ledger_sha256': snapshots[0]['record']['ledger_sha256']}
    assert view['pins'] == {'recipe_ledger_sha256': snapshots[1]['record']['ledger_sha256']}
    assert view['required_sections'] == ['recipe_ledger'] and view['errors'] == []
    assert view['sections'][0]['lines'] == ['unknown: r3 (operation /r3)']
    status, evidence = ledger.recorded['C36']
    assert status == 'satisfied' and evidence['approval_record'] == snapshots[0]['id']
    assert evidence['record'] == snapshots[1]['id'] and evidence['shown'] == ['r3']


@pytest.mark.parametrize('final, lost', [([_row('r2', 'matched')], ['r1']),
                                         ([_row('r1', 'unknown', requested=2.0, effective=None),
                                           _row('r2', 'matched')], ['r1'])])
def test_C36_is_violated_naming_each_approved_row_checkin3_drops_or_alters(ledger, monkeypatch, tmp_path, final, lost):
    approved = [_row('r1', 'unknown', effective=None), _row('r2', 'matched')]
    _, _, view = _views(monkeypatch, tmp_path, approved, final)
    status, evidence = ledger.recorded['C36']
    assert status == 'violated' and evidence['rows'] == lost and evidence['reason']
    assert view['errors'] == []


def test_C36_stays_pending_without_an_approval_snapshot_of_the_approved_plan(ledger, monkeypatch, tmp_path):
    store = Store()
    monkeypatch.setattr(checkins, '_recipe_rows', lambda run_dir: [])
    view = checkins.checkin('final', {'store': store, 'run_dir': tmp_path, 'plan': PLAN,
                                      'state': {'plan': {'approved_sha256': PLAN['sha256']}}})
    assert ledger.recorded == {} and ledger.open == [f'C36@{RUN}']
    assert view['sections'][0]['lines'] == ['No unknown or deviated recipe ledger row (0 row(s) recorded).']


def test_an_unreadable_recipe_ledger_is_disclosed_and_evidences_nothing(ledger, monkeypatch, tmp_path):
    def broken(run_dir):
        raise ValueError('request_plan hash differs from contract pin')
    store = Store()
    context = {'store': store, 'run_dir': tmp_path, 'plan': PLAN, 'state': {'plan': {'approved_sha256': PLAN['sha256']}}}
    monkeypatch.setattr(checkins, '_recipe_rows', broken)
    approval = checkins.checkin('approve_plan', context)
    assert approval['errors'] == [] and 'recipe_ledger_sha256' not in approval['pins']
    assert [f['text'] for f in approval['flags'] if 'cannot be rebuilt' in f['text']]
    view = checkins.checkin('final', context)
    assert view['errors'] == [] and 'cannot be rebuilt' in view['sections'][0]['lines'][0]
    assert ledger.recorded == {} and ledger.open == [f'C36@{RUN}'] and not store.scan(checkins.RECIPE)


def test_JR04_is_satisfied_at_checkin3_only_when_every_plan_step_has_its_governed_outcome(ledger, monkeypatch, tmp_path):
    ledger.open.append(f'JR04@{RUN}')
    store = Store()
    context = {'store': store, 'run_dir': tmp_path, 'plan': PLAN, 'state': {'plan': {'approved_sha256': PLAN['sha256']}}}
    monkeypatch.setattr(checkins, '_recipe_rows', lambda run_dir: [])
    checkins.checkin('final', context)
    assert 'JR04' not in ledger.recorded   # the plan's step has no governed outcome yet
    outcome = store.append('step-outcome', {'step_id': 'derive', 'attempt': 1, 'status': 'completed'})
    checkins.checkin('final', context)
    status, evidence = ledger.recorded['JR04']
    assert status == 'satisfied' and evidence['outcomes'] == {'derive': outcome} and evidence['record'] == outcome
