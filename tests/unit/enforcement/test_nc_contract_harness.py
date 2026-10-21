"""Peer seam controls prevent fake-backed tests from masquerading as production execution."""
from copy import deepcopy
import inspect
import json
from pathlib import Path
import stat

import pytest

import nc_cases
from nc_contract import ContractHarness, FakeLedger, FakeRunStore, FakeSink, FakeStep


def _pass(env, payload):
    return {'errors': [], 'notices': [], 'disclosures': []}


def _hold(env, payload):
    return {'errors': ['scope_missing'], 'notices': [], 'disclosures': []}


def test_fake_peer_is_explicit_and_does_not_claim_architecture_acceptance(nc):
    nc.patch.setattr(nc_cases, 'controller_installed', lambda: False)
    observed = ContractHarness(nc, fake=_pass, real=_hold).run({'result': 'claimed complete'})
    assert observed.backend == 'peer-fake' and observed.allowed and observed.effects == 1
    assert observed.receipt['evidence_scope'] == 'peer-contract'
    assert 'architecture_complete' not in observed.receipt
    assert observed.receipt['label'] == 'CONTRACT VALIDATED'
    assert observed.sink == b'fictional result\n'


def test_installed_component_never_uses_the_fake_fallback(nc):
    nc.patch.setattr(nc_cases, 'controller_installed', lambda: True)
    observed = ContractHarness(nc, fake=_pass, real=_hold).run({})
    assert observed.backend == 'real-component' and not observed.allowed
    assert observed.effects == 0 and observed.receipt['reason'] == 'scope_missing'
    assert observed.sink == b'QUALIFIED: scope_missing\n'


def test_installed_adapter_failure_is_not_converted_to_fake_success(nc):
    nc.patch.setattr(nc_cases, 'controller_installed', lambda: True)

    def missing(env, payload):
        raise ImportError('missing peer entry')

    with pytest.raises(ImportError, match='missing peer entry'):
        ContractHarness(nc, fake=_pass, real=missing).run({})
    assert json.loads((nc.root / 'peer-1/observer/effects.json').read_text()) == []
    assert not (nc.root / 'peer-1/delivery').exists()


def test_installed_controller_never_uses_the_peer_catalogue(nc):
    nc.patch.setattr(nc_cases, 'controller_installed', lambda: True)
    assert nc_cases.catalogue_path().name == 'catalogue.json'


def test_refusal_then_fallback_keeps_the_adversary_bytes_unpublished(nc):
    nc.patch.setattr(nc_cases, 'controller_installed', lambda: False)
    observed = ContractHarness(nc, fake=_hold, real=_pass).run({'claim': 'finished'})
    assert observed.effects == 0
    assert observed.ledger[-1]['status'] == 'violated'
    assert (nc.root / 'peer-1/adversary/fallback.txt').read_bytes() == b'worker claims complete\n'
    assert observed.published == {'result.txt': b'QUALIFIED: scope_missing\n'}


@pytest.mark.parametrize('bad', [None, [], {'errors': 'refuse'}, {'errors': [None]}, {'notices': [1]}])
def test_malformed_probe_cannot_create_an_effect_or_delivery(nc, bad):
    with pytest.raises(ValueError):
        ContractHarness(nc, fake=lambda env, payload: bad, real=lambda env, payload: bad).run({})
    assert json.loads((nc.root / 'peer-1/observer/effects.json').read_text()) == []
    assert not (nc.root / 'peer-1/delivery').exists()


def test_store_envelopes_are_append_only_hash_chained_and_json_safe(nc):
    store = FakeRunStore('store-test', root=nc.root / 'private')
    record = {'value': [1]}
    first = store.append('fact', record)
    record['value'].append(2)
    assert store.read('fact', first)['record'] == {'value': [1]}
    second = store.append('fact', {'value': [2]})
    rows = store.scan('fact')
    assert rows[1]['prev'] == rows[0]['digest'] and rows[1]['id'] == second
    rows[0]['record']['value'].append(3)
    assert store.read('fact', first)['record'] == {'value': [1]}
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    with pytest.raises(ValueError):
        store.append('fact', {'bad': float('nan')})
    assert len(store.scan('fact')) == 2
    with pytest.raises(ValueError, match='escapes'):
        store.path('..', 'adversary')


def test_ledger_history_is_conserved_and_a_violated_component_cannot_deliver_success(nc):
    store = FakeRunStore('ledger-test', root=nc.root / 'private')
    ledger = FakeLedger()
    assert ledger.materialise(store, 'plan', {'rows': ['first', 'second']}) == ['first', 'second']
    ledger.record(store, 'first', 'satisfied', {'artifact': 'a'})
    ledger.record(store, 'second', 'violated', {'reason': 'scope_missing'})
    assert [row['entry_id'] for row in ledger.gate(store, 'deliver')] == ['second']
    history = ledger.summary(store)['events']
    assert len(history) == 4 and history[1]['status'] == 'pending'
    with pytest.raises(ValueError, match='unknown'):
        ledger.record(store, 'second', 'passed', {})


@pytest.mark.parametrize('owner,name,parameters', [
    (FakeRunStore, '__init__', ('self', 'run_id', 'root')),
    (FakeRunStore, 'append', ('self', 'kind', 'record')),
    (FakeRunStore, 'read', ('self', 'kind', 'record_id')),
    (FakeRunStore, 'scan', ('self', 'kind')),
    (FakeRunStore, 'path', ('self', 'parts')),
    (FakeStep, 'run', ('self', 'store', 'step', 'context')),
    (FakeLedger, 'materialise', ('self', 'store', 'stage', 'context')),
    (FakeLedger, 'record', ('self', 'store', 'entry_id', 'status', 'evidence')),
    (FakeLedger, 'gate', ('self', 'store', 'transition')),
    (FakeSink, 'deliver', ('self', 'store', 'plan')),
    (FakeSink, 'bounded_end', ('self', 'store', 'reason')),
    (FakeSink, 'receipt', ('self', 'store')),
])
def test_peer_fake_keeps_the_published_binding_parameter_names(owner, name, parameters):
    assert tuple(inspect.signature(getattr(owner, name)).parameters) == parameters
