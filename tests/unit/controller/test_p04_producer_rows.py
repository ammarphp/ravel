"""A producer's P05 and ``ROLE-<card>-sees``, each from the action that enforces it.

P05: every quantity the producer consumed from an upstream step (an upstream custody input whose bytes its broker
reads show) is that step's adopted, accepted output; a mismatch refuses the step, and a producer that consumed no
upstream quantity hands none off (not applicable, with what it was given and read). ``ROLE-<card>-sees``: the card's
sees constraint reached the worker in its delivered packet and its inputs pass the card's forbidden-input screen.
Custody, the store and the run directory stand in; the gate drives the same rows on the real ones.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller.instructions import compiler
from ravel.controller.step import custody, graph
from ravel.workflow import role_registry

CARD = role_registry.load('calculation')
UPSTREAM = {'artifact': 's1:outputs/table.json', 'step_id': 's1', 'path': 'outputs/table.json',
            'destination': 'steps/s1/outputs/table.json', 'sha256': 'b' * 64, 'status': 'accepted', 'quantity': None,
            '_record_id': 'custody-000004-fixture'}
SEES = f"{compiler.CARD_PATH.format(role=CARD['id'])}#sees/0"


class Store:
    def __init__(self, reads=()):
        self.rows = [{'id': f'broker-evidence-{n:06d}-x', 'kind': 'broker-evidence', 'seq': n,
                      'record': {'node_id': 'ctl.s2', 'worker_attempt': 1,
                                 'input_pins': [{'path': f'agent-work/ctl.s2/1/inputs/{n}.json', 'sha256': sha}]}}
                     for n, sha in enumerate(reads, start=1)]

    def append(self, kind, record):
        identifier = f'{kind}-{len(self.rows) + 1:06d}-x'
        self.rows.append({'id': identifier, 'kind': kind, 'seq': len(self.rows) + 1, 'record': record})
        return identifier

    def scan(self, kind):
        return [r for r in self.rows if r['kind'] == kind]


def _rows(monkeypatch, tmp_path, *, found=(), current=None, reads=(), units=None, receipt_id='delivery-1'):
    store = Store(reads)
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(custody, 'input_errors', lambda *a, **k: ([], [dict(r) for r in found], []))
    monkeypatch.setattr(custody, 'custody_index', lambda s: dict(current if current is not None else
                                                                   {r['artifact']: r for r in found}))
    expected = compiler.digest_text(json.dumps(CARD['sees'], sort_keys=True, ensure_ascii=False))
    manifest = {'sha256': 'm' * 64, 'units': units if units is not None else [{'id': SEES, 'sha256': expected}]}
    state = {'step': {'id': 's2', 'depends_on': ['s1']}, 'acting': {'id': 's2', 'kind': 'derive', 'parameters': {}},
             'context': {'run_dir': str(tmp_path), 'attempt': 1}, 'observation': {'instruction_receipt': receipt_id}}
    return graph._producer_rows(state, store, CARD, {'node_id': 'ctl.s2', 'attempt': 1}, {'manifest': manifest})


def test_a_producer_that_consumed_no_upstream_quantity_hands_none_off(monkeypatch, tmp_path):
    rows, refusals = _rows(monkeypatch, tmp_path)
    assert refusals == [] and rows['P05']['status'] == 'not_applicable'
    assert rows['P05']['evidence']['reason'] == 'not_applicable:no_upstream_quantity_consumed'
    assert rows['P05']['evidence']['label'] == 'no chain handoff'
    assert rows['P05']['evidence']['record'].startswith('step-fact-')


def test_an_upstream_input_the_worker_never_read_is_no_handoff(monkeypatch, tmp_path):
    rows, refusals = _rows(monkeypatch, tmp_path, found=[UPSTREAM], reads=['c' * 64])
    assert refusals == [] and rows['P05']['status'] == 'not_applicable'


def test_a_consumed_upstream_quantity_equal_to_its_adopted_output_is_preserved(monkeypatch, tmp_path):
    rows, refusals = _rows(monkeypatch, tmp_path, found=[UPSTREAM], reads=['b' * 64])
    assert refusals == [] and rows['P05']['status'] == 'satisfied'


def test_a_consumed_upstream_quantity_that_differs_from_its_adopted_output_refuses_the_step(monkeypatch, tmp_path):
    readopted = {UPSTREAM['artifact']: {**UPSTREAM, 'sha256': 'd' * 64, '_record_id': 'custody-000009-fixture'}}
    rows, refusals = _rows(monkeypatch, tmp_path, found=[UPSTREAM], current=readopted, reads=['b' * 64])
    assert rows['P05']['status'] == 'violated' and rows['P05']['evidence']['reason'] == 'chain_handoff_mismatch'
    assert rows['P05']['evidence']['label'] == 'CHAIN HANDOFF MISMATCH'
    assert refusals and refusals[0]['code'] == 'chain_handoff_mismatch'
    assert refusals[0]['handoffs'][0]['adopted_sha256'] == 'd' * 64


def test_the_card_sees_constraint_is_recorded_from_the_delivered_packet(monkeypatch, tmp_path):
    rows, _ = _rows(monkeypatch, tmp_path)
    sees = rows[f"ROLE-{CARD['id']}-sees"]
    assert sees['status'] == 'satisfied' and sees['evidence']['instruction_receipt'] == 'delivery-1'
    assert sees['evidence']['unit'] == SEES and sees['evidence']['removed'] == []


@pytest.mark.parametrize('units, receipt_id, reason', [
    ([], 'delivery-1', 'sees_unit_not_delivered'),
    ([{'id': SEES, 'sha256': '0' * 64}], 'delivery-1', 'sees_unit_not_delivered'),
    (None, None, 'no_instruction_receipt'),
])
def test_a_sees_constraint_not_delivered_is_violated(monkeypatch, tmp_path, units, receipt_id, reason):
    rows, _ = _rows(monkeypatch, tmp_path, units=units, receipt_id=receipt_id)
    sees = rows[f"ROLE-{CARD['id']}-sees"]
    assert sees['status'] == 'violated' and reason in sees['evidence']['reason']


CONFINED = {'T04': {'status': 'satisfied', 'evidence': {'mechanism': 'confine.prepare_and_finish',
                                                        'record': 'launch-finished-fixture'}}}


def _launch_rows(monkeypatch, tmp_path, *, found=(), current=None, enforced=CONFINED):
    store = Store()
    monkeypatch.setattr(graph, '_store', lambda state: store)
    monkeypatch.setattr(custody, 'input_errors', lambda *a, **k: ([], [dict(r) for r in found], []))
    monkeypatch.setattr(custody, 'custody_index', lambda s: dict(current if current is not None else
                                                                   {r['artifact']: r for r in found}))
    state = {'step': {'id': 's2', 'depends_on': ['s1']}, 'acting': {'id': 's2', 'kind': 'operate', 'parameters': {}},
             'context': {'run_dir': str(tmp_path), 'attempt': 1}}
    return graph._launch_chain_rows(state, store, {'finished_id': 'launch-finished-fixture'}, enforced)


def test_a_confined_launch_with_no_upstream_input_hands_none_off(monkeypatch, tmp_path):
    rows = _launch_rows(monkeypatch, tmp_path)
    assert rows['P05']['status'] == 'not_applicable'
    assert rows['P05']['evidence']['reason'] == 'not_applicable:no_upstream_quantity_consumed'


def test_a_confined_launch_consumed_the_adopted_upstream_bytes(monkeypatch, tmp_path):
    rows = _launch_rows(monkeypatch, tmp_path, found=[UPSTREAM])
    assert rows['P05']['status'] == 'satisfied'
    assert rows['P05']['evidence']['mechanism'] == 'chain-handoffs-checked'


def test_a_confined_launch_whose_upstream_was_readopted_is_a_chain_mismatch(monkeypatch, tmp_path):
    readopted = {UPSTREAM['artifact']: {**UPSTREAM, 'sha256': 'd' * 64}}
    rows = _launch_rows(monkeypatch, tmp_path, found=[UPSTREAM], current=readopted)
    assert rows['P05']['status'] == 'violated' and rows['P05']['evidence']['reason'] == 'chain_handoff_mismatch'


def test_a_launch_without_its_confined_input_proof_records_nothing(monkeypatch, tmp_path):
    assert _launch_rows(monkeypatch, tmp_path, found=[UPSTREAM], enforced={}) == {}
    unproved = {'T04': {'status': 'satisfied', 'evidence': {'mechanism': 'worker_claim'}}}
    assert _launch_rows(monkeypatch, tmp_path, found=[UPSTREAM], enforced=unproved) == {}
