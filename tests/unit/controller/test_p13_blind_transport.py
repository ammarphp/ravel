"""Restricted review transport controls; no provider, network or native launch.

Qualifications below are synthetic controller observations, never host qualification evidence.
"""
from copy import deepcopy
import json

import pytest

from ravel.workflow import review_independence, review_points, role_registry, transport_registry as tr


class Store:
    """Minimal append/scan fake with the bound RunStore signatures."""
    def __init__(self):
        self.records = {}

    def append(self, kind, record):
        self.records.setdefault(kind, []).append({'record': deepcopy(record)})
        return str(len(self.records[kind]))

    def scan(self, kind):
        return deepcopy(self.records.get(kind, []))


BLIND_CARDS = [card for card in role_registry.all_cards() if card.get('requires', {}).get('blind') is True]


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(tr, 'executor_problem', lambda document: None)
    monkeypatch.setattr(tr, 'sandbox_available', lambda: True)
    document = tr.load('claude-cli-worker', installed_only=True)
    probe = {
        'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
        'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'synthetic 0.0.0',
        'help_sha256': 'b' * 64, 'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
        'capabilities_confirmed': {key: bool(document['capabilities'][key]) and key != 'blind_capable'
                                   for key in tr.BOOLEAN_CAPABILITIES},
        'unusable': [], 'probed_utc': '2026-01-01T00:00:00Z', 'executable_path': '/synthetic/cli',
        'executable_sha256': 'f' * 64, 'exit_status': 0,
    }
    record = {
        'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
        'status': 'live_qualified', 'record_path': '/synthetic/qualification.json',
        'executable_path': '/synthetic/cli', 'executable_sha256': 'f' * 64,
        'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': tr.digest(probe),
        'receipt': {'path': '/synthetic/receipt.json', 'sha256': 'a' * 64, 'digest': 'c' * 64},
        'observed': {'session_id': 'synthetic-session', 'model': 'claude-synthetic-reviewer'},
        'steps': [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)],
        'rundir': '/synthetic/run', 'qualified_utc': '2026-01-01T00:00:00Z',
    }
    preferences = {'schema_version': 1, 'kind': 'agent-preferences',
                   'families': {card['family']: [document['id']] for card in BLIND_CARDS},
                   'tier_models': {tier: {document['id']: 'claude-synthetic-reviewer'} for tier in tr.TIERS}}
    return document, probe, record, preferences


def select(card, transport, store, **changes):
    document, probe, _, preferences = transport
    kwargs = {'probes': {document['id']: probe}, 'executables': {document['id']: probe['executable_sha256']},
              'controller': True, 'qualifications': tr.store_qualifications(store)}
    kwargs.update(changes)
    return tr.select(card, preferences, **kwargs)


def test_G03_blind_seat_census_includes_registered_extensions():
    assert len(BLIND_CARDS) == 27
    assert len({card['id'] for card in BLIND_CARDS}) == 27


@pytest.mark.parametrize('card', BLIND_CARDS, ids=lambda card: card['id'])
def test_G03_CF14_all_blind_seats_select_a_store_qualified_restricted_worker(card, transport, monkeypatch):
    store = Store()
    with pytest.raises(tr.TransportRefusal) as absent:
        select(card, transport, store)
    assert 'qualification' in absent.value.missing
    tr.record_qualification(store, transport[2])
    # No legacy state file or probe subprocess may supply the qualification.
    monkeypatch.setattr(tr, 'qualification_path', lambda _: pytest.fail('read outside protected store'))
    chosen = select(card, transport, store, assigned={'producer': {'family': 'anthropic'}})
    assert chosen['transport_id'] == transport[0]['id'] and chosen['family'] == 'anthropic'


@pytest.mark.parametrize('damage', ['probe', 'executable', 'declaration', 'sandbox', 'registration', 'step'])
def test_SW09_G03_stale_or_incomplete_qualification_cannot_seat_a_blind_reviewer(transport, monkeypatch, damage):
    document, probe, record, _ = transport
    store = Store()
    if damage == 'declaration':
        record['declaration_sha256'] = '0' * 64
    if damage == 'probe':
        record['probe_sha256'] = '0' * 64
    if damage == 'step':
        record['steps'][0]['passed'] = False
        # Direct invalid store insertion models corrupt/incomplete evidence, not acceptance.
        store.append(tr.QUALIFICATION_KIND, record)
    elif damage != 'registration':
        tr.record_qualification(store, record)
    if damage == 'sandbox':
        monkeypatch.setattr(tr, 'sandbox_available', lambda: False)
    changes = {'executables': {document['id']: '0' * 64}} if damage == 'executable' else {}
    with pytest.raises(tr.TransportRefusal) as failure:
        select(BLIND_CARDS[0], transport, store, **changes)
    assert not any('distinct_family_from' in reason for reason in failure.value.missing)


def test_SW09_a_live_label_in_the_declaration_never_substitutes_for_store_evidence(transport):
    document, probe, _, _ = transport
    document['qualification']['status'] = 'live_qualified'
    assert tr.qualification_status(document, probe, registered={}) == 'declared'
    assert tr.qualification_status(document, probe, registered=frozenset()) == 'declared'
    assert tr.qualification_status(document, probe) == 'live_qualified'  # legacy behaviour


def test_SW09_a_hand_written_state_record_does_not_fill_an_empty_controller_store(transport):
    document, _, record, _ = transport
    path = tr.qualification_path(document['id'])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    with pytest.raises(tr.TransportRefusal):
        select(BLIND_CARDS[0], transport, Store())


@pytest.mark.parametrize('damage', ['missing', 'failed', 'inconclusive', 'duplicate', 'version'])
def test_SW09_store_registration_refuses_incomplete_conformance_records(transport, damage):
    record = transport[2]
    if damage == 'missing':
        record['steps'].pop()
    elif damage == 'duplicate':
        record['steps'].append(record['steps'][0])
    elif damage == 'version':
        record['schema_version'] = 2
    else:
        record['steps'][0]['passed'] = False if damage == 'failed' else None
    store = Store()
    with pytest.raises(ValueError):
        tr.record_qualification(store, record)
    assert tr.store_qualifications(store) == {}


@pytest.mark.parametrize('damage', ['missing', 'failed', 'none', 'version'])
def test_SW09_the_operator_register_refuses_incomplete_conformance_records(transport, tmp_path, damage):
    register = tmp_path / 'operator-store' / tr.QUALIFICATION_REGISTER
    complete = deepcopy(transport[2])
    assert tr.register_qualification(complete, register)['record_sha256'] == tr.digest(complete)  # positive control
    record = transport[2]
    if damage == 'missing':
        record['steps'].pop()
    elif damage == 'failed':
        record['steps'][0]['passed'] = False
    elif damage == 'none':
        record['steps'] = []
    else:
        record['schema_version'] = 2
    with pytest.raises(ValueError):
        tr.register_qualification(record, register)
    assert tr.registered_qualifications(register) == {tr.digest(complete)}


def test_SW09_store_records_are_digest_bound(transport):
    document, probe, record, _ = transport
    store = Store()
    tr.record_qualification(store, record)
    qualifications = tr.store_qualifications(store)
    assert tr.read_qualification(document, probe, registered=qualifications) == record
    qualifications[tr.digest(record)]['observed']['session_id'] = 'changed'
    assert tr.read_qualification(document, probe, registered=qualifications) is None


def test_G03_review_preflight_uses_the_controller_store(transport, tmp_path, monkeypatch):
    document, probe, record, preferences = transport
    (tmp_path / 'inputs').mkdir()
    # A controller run's seats are judged on the frozen agent preferences of its mode, never a run-tree copy.
    (tmp_path / 'inputs/agent_preferences.json').write_text(json.dumps({'schema_version': 1, 'kind': 'nothing'}))
    frozen = {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': [document['id']],
              'tier_models': preferences['tier_models']}
    store = Store()
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: store)
    monkeypatch.setattr(review_points, '_controller_preferences', lambda found: deepcopy(frozen))
    monkeypatch.setattr(tr, 'read_probe', lambda _: probe)
    monkeypatch.setattr(tr, 'resolve_executable', lambda _: ('/synthetic/cli', probe['executable_sha256']))
    points = [{'blocking': True, 'attestation_min': 'transport', 'roles': [{'role': c['id']} for c in BLIND_CARDS]}]
    assert len(review_points.dispatchability(tmp_path, points)) == 27
    tr.record_qualification(store, record)
    assert review_points.dispatchability(tmp_path, points) == []


def test_G03_review_preflight_does_not_fall_back_when_store_reading_fails(tmp_path, monkeypatch):
    def broken(root):
        raise OSError('unreadable controller store')
    monkeypatch.setattr(review_independence, 'controller_store', broken)
    monkeypatch.setattr(tr, 'select', lambda *args, **kwargs: pytest.fail('legacy selection attempted'))
    errors = review_points.dispatchability(tmp_path, [])
    assert len(errors) == 1 and errors[0].code == 'review_transport_missing'
