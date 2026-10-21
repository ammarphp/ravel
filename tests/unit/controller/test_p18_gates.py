"""Explicit engagement composition and fail-closed transition/recheck controls.

The core pin fixture retains scientific bytes and a separately authenticated view.
The public ledger reads the unchanged scientific pin; the engagement callback
resolves the view. Transition tests replace no ledger reader or requirement.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

import ravel.controller.engagement as engagement
from ravel.controller import ledger
from ravel.controller.engagement.records import digest
from ravel.controller.ledger import gates, state as ledger_state
from ravel.workflow import decision_gate
from p02_support import fixture_catalogue, fixture_rows, row, satisfy, use_catalogue
from test_p18_records import dispatch, setup


def prepared(monkeypatch, tmp_path):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    decision = engagement.decide(store, {'plan': scientific})
    applied = engagement.apply(scientific, decision)
    catalogue = fixture_rows() + [row('EG03', 'step.plan_bind', 'plan', 'run', package='P18')]
    use_catalogue(monkeypatch, fixture_catalogue(catalogue))
    monkeypatch.setattr(gates, '_GATE_HOOKS', {})
    ledger.materialise(store, 'intake', {'run_id': store.run_id,
                                      'deliverables': [d['id'] for d in scientific['deliverables']]})
    ledger.materialise(store, 'plan', applied)
    satisfy(store, ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'checker', 'attempt': 1}))
    satisfy(store, [k for k in ledger.pending(store) if not k.startswith('GATE-approve_plan@')])
    publish_view(store, scientific, applied)
    return store, scientific, decision, applied


def publish_view(store, scientific, applied):
    # Core pin fake: scientific bytes keep their digest; the view has its own pin.
    store.append('plan', {'plan_sha256': scientific['sha256'], 'plan': scientific,
                          'applied_plan': applied,
                          'applied_sha256': applied['engagement']['applied_sha256']})


def cold_scenario(tmp_path, spelling, scenario):
    with pytest.MonkeyPatch.context() as monkeypatch:
        store, scientific, decision, applied = prepared(monkeypatch, tmp_path)
        assert gates._GATE_HOOKS == {}  # importing the provider never composes it
        if scenario == 'absent':
            assert 'engagement_provider_missing' in {r['reason'] for r in ledger.gate(store, spelling)}
            return
        engagement.register_gates(ledger)
        engagement.register_gates(ledger)
        assert gates._GATE_HOOKS == {'engagement': engagement.gate_errors}
        assert ledger.gate(store, spelling) == []
        if scenario == 'valid':
            return
        if scenario == 'wrong':
            applied['steps'][0]['operation'] = 'other.operation'
        elif scenario == 'dropped':
            applied['steps'][0]['seats'].pop()
        elif scenario == 'recheck':
            # A passing preflight cannot be reused after a seat disappears.
            applied['checkins'][0]['seats'].clear()
            publish_view(store, scientific, applied)
            monkeypatch.setattr(decision_gate, '_controller_owner', lambda *args: store.run_id)
            monkeypatch.setattr(decision_gate, 'check', lambda *args: [])
            before = ledger.verify(store)
            errors = ledger.decide(store, tmp_path, 'approve_plan', {})
            assert any('EG03' in error.message for error in errors)
            assert ledger.verify(store) == before
            key = ledger.instance_key('GATE-approve_plan', store.run_id, {})
            assert ledger_state.load(store, full=True).instances[key].status == 'pending'
            return
        else:
            raise AssertionError(scenario)
        # Even a recomputed applied hash cannot authorize changed scientific bytes or seats.
        body = deepcopy(applied)
        body['engagement'].pop('applied_sha256')
        applied['engagement']['applied_sha256'] = digest(body)
        publish_view(store, scientific, applied)
        assert 'EG03' in {r['id'] for r in ledger.gate(store, spelling)}


@pytest.mark.parametrize('spelling', ['checkin1->execute', 'checkin1→execute'])
@pytest.mark.parametrize('scenario', ['valid', 'absent', 'wrong', 'dropped', 'recheck'])
def test_cold_process_transition_and_acting_recheck(tmp_path, spelling, scenario):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                             str(tmp_path), spelling, scenario], text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_direct_applied_plan_positive_control(monkeypatch, tmp_path):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    decision = engagement.decide(store, {'plan': scientific})
    assert engagement.check_applied(engagement.apply(scientific, decision), decision) == []


@pytest.mark.parametrize('storage', ['inline', 'blob', 'split_inline', 'split_blob'])
@pytest.mark.parametrize('mutation', ['valid', 'scientific_pin', 'applied_pin', 'dropped', 'candidate', 'bytes'])
def test_current_stored_view_is_authenticated(monkeypatch, tmp_path, storage, mutation):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    decision = engagement.decide(store, {'plan': scientific})
    applied = engagement.apply(scientific, decision)
    if mutation == 'dropped':
        applied['steps'][0]['seats'].pop()
        body = deepcopy(applied)
        body['engagement'].pop('applied_sha256')
        applied['engagement']['applied_sha256'] = digest(body)
    pin = {'plan_sha256': scientific['sha256'],
           'applied_sha256': applied['engagement']['applied_sha256']}
    if mutation == 'scientific_pin':
        pin['plan_sha256'] = '0' * 64
    elif mutation == 'applied_pin':
        pin['applied_sha256'] = '0' * 64
    split = storage.startswith('split_')
    if split:
        pin['plan'] = scientific
    if storage.endswith('inline'):
        field = 'applied_plan' if split else 'plan'
        pin[field] = deepcopy(applied)
        if mutation == 'bytes':
            pin[field]['steps'][0]['role'] = 'other-role'
    else:
        raw = json.dumps(applied).encode()
        blob = sha256(raw).hexdigest()
        store.path('blobs').mkdir()
        store.path('blobs', blob).write_bytes(b'{}' if mutation == 'bytes' else raw)
        pin['applied_blob' if split else 'blob'] = {'path': 'blobs/' + blob, 'sha256': blob}
    store.append('plan', pin)
    candidate = deepcopy(scientific)
    if mutation == 'candidate':
        candidate['steps'][0]['role'] = 'other-role'
    errors = engagement.gate_errors(store, 'checkin1→execute', plan=candidate)
    if mutation == 'valid':
        assert errors == []
    else:
        assert errors and {r['row'] for r in errors} == {'EG03'}


@pytest.mark.parametrize('path', ['../outside', '/outside', 'blobs//value', 'blobs/./value'])
def test_applied_blob_pointer_cannot_escape_custody(monkeypatch, tmp_path, path):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    engagement.decide(store, {'plan': scientific})
    store.append('plan', {'plan': scientific, 'plan_sha256': scientific['sha256'],
                          'applied_blob': {'path': path, 'sha256': '0' * 64}})
    assert {r['row'] for r in engagement.gate_errors(store, 'checkin1→execute', plan=scientific)} == {'EG03'}


@pytest.mark.parametrize('mutation', ['missing', 'wrong', 'decision'])
def test_canonical_gate_reports_plan_failures_as_EG03(monkeypatch, tmp_path, mutation):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    decision = engagement.decide(store, {'plan': scientific})
    applied = engagement.apply(scientific, decision)
    if mutation == 'missing':
        applied = None
    elif mutation == 'wrong':
        applied = scientific
    else:
        store.append('engagement-decision', {**decision, 'sha256': '0' * 64})
    errors = engagement.gate_errors(store, 'checkin1→execute', plan=applied)
    assert errors and all(r['row'] == 'EG03' for r in errors)


@pytest.mark.parametrize('broker', [None, {'requests': 0}, 'valid'])
def test_delivery_reports_independent_meter_gate(monkeypatch, tmp_path, broker):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    decision = engagement.decide(store, {'plan': scientific})
    dispatch(store, scientific, decision)
    if broker == 'valid':
        broker = {'requests': 2 * len(store.scan('step-dispatch'))}
    engagement.check_envelope(store, 'deliver', broker=broker)
    errors = engagement.gate_errors(store, 'deliver[accepted]')
    if broker and broker['requests']:
        assert errors == []
    else:
        assert 'EG09' in {r['row'] for r in errors}
        if broker:
            assert 'EG08' in {r['row'] for r in errors}


def test_unavailable_envelopes_never_satisfy_public_delivery(monkeypatch, tmp_path):
    store, scientific, decision, applied = prepared(monkeypatch, tmp_path)
    dispatch(store, scientific, decision)
    broker = {'requests': 2 * len(store.scan('step-dispatch'))}
    engagement.check_envelope(store, 'deliver', broker=broker)
    assert engagement.receipt_section(store)['accepted_allowed']
    read = engagement.data

    def unavailable(name):
        value = read(name)
        return {**value, 'status': 'unavailable'} if name == 'envelopes.json' else value

    monkeypatch.setattr(engagement, 'data', unavailable)
    engagement.register_gates(ledger)
    assert 'EG08' in {r['id'] for r in ledger.gate(store, 'deliver[accepted]')}
    assert not engagement.receipt_section(store)['accepted_allowed']
    assert ledger.gate(store, 'deliver[qualified]') == []


def test_unavailable_inventory_cannot_supply_ready_route_projection(monkeypatch, tmp_path):
    store, scientific, _ = setup(monkeypatch, tmp_path)
    read = engagement.data
    monkeypatch.setattr(engagement, 'data', lambda name: {**read(name), 'status': 'unavailable'}
                        if name == 'envelopes.json' else read(name))
    decision = engagement.decide(store, {'plan': scientific})
    assert decision['envelopes'] == {}
    assert decision['budget_authority']['class'] == 'R3'


def test_import_does_not_install_provider_or_require_ledger():
    source = ("import sys; sys.modules['ravel.controller.ledger'] = None; "
              "import ravel.controller.engagement as e; assert callable(e.register_gates)")
    result = subprocess.run([sys.executable, '-c', source], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == '__main__':
    cold_scenario(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
