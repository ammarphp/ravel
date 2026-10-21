"""Preset-to-seat composition over the complete installed role census.

Every provider, executable, probe and qualification observation here is fictional.
These controls establish selection composition, never live provider reachability.
The real preset algorithms, installed declarations and both seat selectors execute.
"""
from copy import deepcopy
import json

import pytest

from ravel.controller.authority import operator
from ravel.controller.step import seats
from ravel.controller.step.services import StepHold
from ravel.workflow import model_catalogue as mc, models_cli, role_registry, transport_registry as tr


CARDS = role_registry.all_cards()
TRANSPORTS = {'anthropic': 'claude-cli-worker', 'openai': 'codex-cli-worker'}
PRESET_CLASSES = {
    'premium': {'judgment': 'top', 'agent': 'strong', 'cheap': 'mid'},
    'balanced': {'judgment': 'strong', 'agent': 'mid', 'cheap': 'small'},
    'economy': {'judgment': 'mid', 'agent': 'small', 'cheap': 'small'},
}


class Store:
    """Inert stand-in for the controller-owned append/scan custody API."""

    def __init__(self):
        self.records = {}

    def append(self, kind, record):
        self.records.setdefault(kind, []).append({'record': deepcopy(record)})
        return str(len(self.records[kind]))

    def scan(self, kind):
        return deepcopy(self.records.get(kind, []))


def _qualification(document, probe, model):
    return {
        'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': document['id'],
        'status': 'live_qualified', 'record_path': '/fictional/qualification.json',
        'executable_path': probe['executable_path'], 'executable_sha256': probe['executable_sha256'],
        'declaration_sha256': tr.declaration_sha256(document), 'probe_sha256': tr.digest(probe),
        'receipt': {'path': '/fictional/receipt.json', 'sha256': 'a' * 64, 'digest': 'c' * 64},
        'observed': {'session_id': 'fictional-' + model, 'model': model, 'requested_model': model},
        'steps': [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)],
        'rundir': '/fictional/run', 'qualified_utc': '2026-01-01T00:00:00Z',
    }


@pytest.fixture
def composition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('RAVEL_TRANSPORT_PATH', str(tmp_path / 'no-custom-transports'))
    catalogue = mc.load(builtin_only=True)
    catalogue.pop('origins', None)
    efforts = sorted({'max'} | {c['model']['effort'] for c in CARDS if c['model']['effort']})
    catalogue['models'] = [
        {'id': f'{prefix}-fictional-{class_}', 'family': family, 'class': class_,
         'tiers': list(tr.TIERS), 'context_tokens': 64000, 'max_output_tokens': 8000,
         'prices_per_million': dict.fromkeys(mc.PRICE_KEYS, 1.0), 'efforts': efforts,
         'released': 'fictional', 'status': 'current'}
        for family, prefix in [('anthropic', 'claude'), ('openai', 'gpt')]
        for class_ in mc.CLASSES
    ]
    overlay = tmp_path / 'catalogue.json'
    overlay.write_text(json.dumps(catalogue))
    monkeypatch.setenv('RAVEL_MODEL_CATALOGUE', str(overlay))

    def no_live(*args, **kwargs):
        pytest.fail('the inert preset composition must not launch a process or provider call')

    monkeypatch.setattr('subprocess.run', no_live)
    monkeypatch.setattr('urllib.request.urlopen', no_live)
    monkeypatch.setattr(tr, 'probe', no_live)
    monkeypatch.setattr('ravel.workflow.transports.cli_worker.qualify', no_live)
    # These are the sole machine-state substitutions: an inert working sandbox
    # and an inert current executable, plus supervisor observations of its CLI.
    monkeypatch.setattr(tr, 'sandbox_available', lambda: True)
    monkeypatch.setattr(tr, 'executor_problem', lambda document: None)
    documents = {family: tr.load(identity, installed_only=True)
                 for family, identity in TRANSPORTS.items()}
    probes = {}
    store = Store()
    detected = {'schema_version': 1, 'kind': 'detected-models', 'transports': []}
    for family, document in documents.items():
        probe = {
            'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
            'declaration_sha256': tr.declaration_sha256(document), 'cli_version': 'fictional 0.0.0',
            'help_sha256': 'b' * 64, 'flags': {flag: 'confirmed' for flag in tr.template_flags(document)},
            'capabilities_confirmed': {key: bool(document['capabilities'][key]) and key != 'blind_capable'
                                       for key in tr.BOOLEAN_CAPABILITIES},
            'unusable': [], 'probed_utc': '2026-01-01T00:00:00Z',
            'executable_path': '/fictional/' + document['launcher'], 'executable_sha256': 'f' * 64,
            'exit_status': 0,
        }
        probes[document['id']] = probe
        rows = [r for r in catalogue['models'] if r['family'] == family]
        for row in rows:
            tr.record_qualification(store, _qualification(document, probe, row['id']))
        detected['transports'].append({'id': document['id'], 'status': 'ok', 'models': [
            {'id': row['id'], 'status': 'qualified', 'catalogued': True} for row in rows]})
    monkeypatch.setattr(tr, 'read_probe', lambda identity: deepcopy(probes.get(identity)))
    monkeypatch.setattr(tr, 'resolve_executable', lambda document: (
        probes[document['id']]['executable_path'], probes[document['id']]['executable_sha256']))
    monkeypatch.setattr(tr, 'qualification_path', lambda _: pytest.fail('qualification must come from protected store'))
    return documents, detected, store, overlay


def _select(card, frozen, store):
    preferences, kept, dropped = seats.preferences({'agent_preferences': frozen}, card)
    assert kept == frozen['transport_preference'] and not dropped
    # Both selectors are real: seats.select delegates to transport_registry.select.
    return seats.select(card, preferences, store=store)


@pytest.mark.parametrize('family', TRANSPORTS)
@pytest.mark.parametrize('preset', PRESET_CLASSES)
def test_every_registered_role_resolves_through_real_preset_and_both_selectors(
        composition, family, preset, record_property):
    documents, detected, store, _ = composition
    frozen, omitted, _ = models_cli.preferences(preset, record=detected, preferred=[family])
    transport = documents[family]['id']
    assert not omitted and frozen['transport_preference'] == [transport]
    assert operator.agent_preference_problems(frozen) == []
    assert transport in seats.wired_transports()['wired']
    expected = {tier: next(r['id'] for r in mc.load()['models']
                          if r['family'] == family and r['class'] == class_)
                for tier, class_ in PRESET_CLASSES[preset].items()}
    assert {tier: frozen['tier_models'][tier][transport] for tier in tr.TIERS} == expected
    observed_models = {r['observed']['model'] for r in tr.store_qualifications(store).values()}
    visited, cheap, maximum = set(), set(), set()
    for registered in CARDS:
        for force_maximum in (False, True):
            card = deepcopy(registered)
            if force_maximum:
                card['model']['effort'] = 'max'
            chosen = _select(card, frozen, store)
            tier = 'cheap' if card['model'].get('cheap_ok') else card['model']['tier']
            assert chosen['transport_id'] == transport, card['id']
            assert chosen['tier'] == tier and chosen['card_tier'] == card['model']['tier'], card['id']
            assert chosen['model'] == expected[tier] and chosen['model'] in observed_models, card['id']
            assert chosen['effort'] == card['model']['effort'], card['id']
            assert chosen['catalogue'] == 'catalogued', card['id']
            visited.add(card['id'])
            if card['model'].get('cheap_ok'):
                cheap.add(card['id'])
            if force_maximum:
                maximum.add(card['id'])
    assert visited == maximum == {c['id'] for c in CARDS}
    assert cheap == {c['id'] for c in CARDS if c['model'].get('cheap_ok')} and cheap
    record_property('registered_roles', len(visited))
    record_property('selection_calls', 2 * len(visited))


@pytest.mark.parametrize('family', TRANSPORTS)
def test_catalogue_row_addition_adopts_model_without_code_or_gate_changes(composition, family):
    documents, detected, store, overlay = composition
    frozen, _, _ = models_cli.preferences('premium', record=detected, preferred=[family])
    transport = documents[family]['id']
    old = frozen['tier_models']['judgment'][transport]
    unknown = ('claude' if family == 'anthropic' else 'gpt') + '-fictional-new-top'
    bad = deepcopy(frozen)
    bad['tier_models']['judgment'][transport] = unknown
    assert operator.agent_preference_problems(bad)
    # A data-only overlay insertion establishes catalogue metadata. The inert
    # observation below separately establishes availability for the fixture.
    document = json.loads(overlay.read_text())
    row = deepcopy(next(r for r in document['models'] if r['id'] == old))
    row['id'] = unknown
    document['models'].insert(0, row)
    overlay.write_text(json.dumps(document))
    discovery = next(r for r in detected['transports'] if r['id'] == transport)
    discovery['models'].append({'id': unknown, 'status': 'qualified', 'catalogued': True})
    probe = tr.read_probe(transport)
    tr.record_qualification(store, _qualification(documents[family], probe, unknown))
    updated, _, _ = models_cli.preferences('premium', record=detected, preferred=[family])
    assert updated['tier_models']['judgment'][transport] == unknown != old
    assert operator.agent_preference_problems(updated) == []
    card = next(c for c in CARDS if c['model']['tier'] == 'judgment' and not c['model'].get('cheap_ok'))
    assert _select(card, updated, store)['model'] == unknown


@pytest.mark.parametrize('family', TRANSPORTS)
def test_qualification_custody_still_blocks_the_same_preset_when_store_empty(composition, family):
    _, detected, _, _ = composition
    frozen, _, _ = models_cli.preferences('balanced', record=detected, preferred=[family])
    card = next(c for c in CARDS if c['requires'].get('blind'))
    with pytest.raises(StepHold) as held:
        _select(card, frozen, Store())
    assert held.value.reason == 'transport_unavailable'
    assert 'qualification' in held.value.evidence['missing']
