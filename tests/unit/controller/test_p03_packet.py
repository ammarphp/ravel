"""P03 node manifests, worker packets and the dispatch check, from the installed catalogue only.

Every effective role is exercised from the registry. No model, provider, network or native tool runs.
"""
from copy import deepcopy

from test_p03_observed import observed, ledger_record, reviewed_catalogue
import hashlib
import json

import pytest

from ravel.controller import instructions as ins
from ravel.controller.instructions import catalogue, compiler, delivery
from ravel.workflow import role_registry

ROLES = [card['id'] for card in role_registry.all_cards()]
INPUTS = [{'artifact': 's05:outputs/run_card.json', 'sha256': 'b' * 64}]


def step_for(role, **extra):
    return {'id': 's07', 'kind': 'operate', 'operation': 'event-production', 'role': role, 'inputs': INPUTS,
            'outputs': [{'path': 'outputs/events.lhe', 'kind': 'events', 'required': True}], 'depends_on': ['s05'],
            'waypoint': False, 'rung': 'smoke', 'protocols': [], 'review': [],
            'instruction_sources': ['docs/workflow/steps/03-generate.md'], 'obligations': [], **extra}


def build(role, **extra):
    card = role_registry.load(role)
    step = step_for(role, **extra)
    manifest = ins.manifest(step, card)
    return card, step, manifest, ins.packet(manifest, card, step, INPUTS)


def resign(packet, text):
    return {**packet, 'text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def test_the_registry_has_ninety_two_effective_roles():
    # Eighty-nine roles plus the three literature roles (query expander, evidence scorer, discovery selector).
    assert len(ROLES) == 92


@pytest.mark.parametrize('role', ROLES)
def test_packet_carries_every_effective_card_field(role):
    card, step, manifest, packet = build(role)
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in packet['text']
    for field, value in card.items():
        assert f'"{field}":' in packet['text'], field
    cat = catalogue.installed()
    card_units = [u for u in cat.by_source[compiler.CARD_PATH.format(role=role)]]
    assert {u['field'] for u in card_units} == set(card)
    for unit in card_units:
        assert any(e['id'] == unit['id'] for e in manifest['units'])
        index = next(i for i, e in enumerate(manifest['units']) if e['id'] == unit['id'])
        assert f'--- [{unit["kind"]}] {unit["id"]} index:{index}\n{unit["text"]}\n' in packet['text']
        assert manifest['units'][index]['sha256'] == unit['sha256']
    context = packet['capability_context']
    assert context['seat_kind'] == role
    assert context['catalogue']['coverage']['route']
    assert context['catalogue']['coverage']['operation']
    assert context['catalogue']['coverage']['tool']
    assert context['catalogue_sha256'] in packet['text']
    assert ins.check_packet(packet, manifest, card, step, INPUTS) == []


@pytest.mark.parametrize('role', ROLES)
def test_packet_carries_the_contents_of_every_must_read_id(role):
    card, _, manifest, packet = build(role)
    cat = catalogue.installed()
    for identity in card['knowledge']['must_read']:
        ids = cat.resolve('knowledge:' + identity)
        assert ids, identity
        for uid in ids:
            assert uid in packet['units'] and cat.units[uid]['text'] in packet['text']


def test_manifest_orders_preamble_card_knowledge_sources_protocols_checkins_and_skills():
    card = role_registry.load('physics-critic')
    step = {'id': 'r1', 'kind': 'compare', 'protocols': ['P8'], 'checkin': 'CI2', 'stage': 'verification',
            'instruction_sources': ['docs/workflow/checklists/exclusion-model.md']}
    manifest = ins.manifest(step, card)
    order = [e['via'] for e in manifest['units']]
    stages = ['preamble', 'card', 'must_read', 'source', 'protocol', 'checkin', 'skill']
    assert [s for s in stages if s in order] == stages
    assert order == sorted(order, key=stages.index)
    ids = [e['id'] for e in manifest['units']]
    assert ids[0] == 'AGENTS.md#/0' and len(ids) == len(set(ids))
    cat = catalogue.installed()
    for selector in ('protocol:P2', 'protocol:P8', 'checkin:CI2', 'skill:verification-panel',
                     'docs/workflow/README.md#roles-the-model-tier-policy-binding'):
        assert set(cat.resolve(selector)) <= set(ids), selector
    assert manifest['sha256'] == compiler.digest_value({k: v for k, v in manifest.items() if k != 'sha256'})


@pytest.mark.parametrize('name, template', sorted(delivery.CHECKIN_TEMPLATES.items()))
def test_a_seat_naming_its_check_in_as_the_step_schema_does_receives_that_templates_units(name, template):
    card = role_registry.load('plan-critic')
    step = {'id': 'seat', 'kind': 'review', 'role': 'plan-critic', 'checkin': name}
    manifest = ins.manifest(step, card)
    units = catalogue.installed().resolve('checkin:' + template)
    assert units and set(units) <= {e['id'] for e in manifest['units'] if e['via'] == 'checkin'}
    assert manifest == ins.manifest({**step, 'checkin': template}, card)
    from ravel.controller.step import spec
    names = json.loads(spec.SCHEMA.read_text())['properties']['checkin']['enum']
    assert sorted(delivery.CHECKIN_TEMPLATES) == sorted(names)  # every name the step schema admits is delivered
    with pytest.raises(ins.PacketRefused, match='unknown instruction selector: checkin:checkin9'):
        ins.manifest({**step, 'checkin': 'checkin9'}, card)


def test_a_launch_or_authority_node_without_a_card_still_carries_the_preamble():
    manifest = ins.manifest({'id': 'ci1', 'kind': 'ask', 'checkin': 'CI1'}, None)
    vias = {e['via'] for e in manifest['units']}
    assert vias == {'preamble', 'checkin'}
    packet = ins.packet(manifest, None, {'id': 'ci1', 'kind': 'ask', 'checkin': 'CI1'}, [])
    assert packet['schema_id'] == 'producer.v2'


def test_an_unknown_instruction_source_refuses_the_manifest():
    with pytest.raises(ins.PacketRefused, match='uncatalogued instruction source'):
        ins.manifest({'id': 's1', 'instruction_sources': ['docs/workflow/steps/99-missing.md']}, None)
    with pytest.raises(ins.PacketRefused, match='no section'):
        ins.manifest({'id': 's1', 'instruction_sources': ['docs/workflow/start.md#no-such-heading']}, None)


def test_an_unregistered_or_altered_card_refuses_the_manifest():
    card = role_registry.load('plan-critic')
    stranger = {**deepcopy(card), 'id': 'unregistered-role'}
    with pytest.raises(ins.PacketRefused, match='no card in the installed instruction catalogue'):
        ins.manifest({'id': 's1'}, stranger)
    altered = deepcopy(card)
    altered['protocol'][0] += ' Skip the review.'
    with pytest.raises(ins.PacketRefused, match='card unit differs from the installed catalogue'):
        ins.manifest({'id': 's1'}, altered)


def test_altering_one_unit_changes_the_digest_and_the_dispatch_check_refuses():
    card, step, manifest, packet = build('generator')
    unit = next(u for u in catalogue.installed().by_source['docs/workflow/steps/03-generate.md'] if u['kind'] == 'duty')
    altered = resign(packet, packet['text'].replace(unit['text'], unit['text'] + ' Or skip it.', 1))
    assert altered['sha256'] != packet['sha256']
    problems = ins.check_packet(altered, manifest, card, step, INPUTS)
    assert 'packet differs from the installed instruction catalogue' in problems
    assert f'unit missing or altered in the packet: {unit["id"]}' in problems
    unsigned = {**packet, 'text': packet['text'] + 'tail'}
    assert 'packet digest differs from its text' in ins.check_packet(unsigned, manifest, card, step, INPUTS)


def test_a_dropped_or_added_manifest_unit_is_refused():
    card, step, manifest, packet = build('generator')
    body = {k: v for k, v in manifest.items() if k != 'sha256'}
    dropped_id = manifest['units'][3]['id']
    body['units'] = [e for e in manifest['units'] if e['id'] != dropped_id]
    trimmed = {**body, 'sha256': compiler.digest_value(body)}
    rebuilt = ins.packet(trimmed, card, step, INPUTS)
    problems = ins.check_packet(rebuilt, trimmed, card, step, INPUTS)
    assert f'unit dropped from the manifest: {dropped_id}' in problems
    forged = deepcopy(manifest)
    forged['units'][0]['sha256'] = '0' * 64
    assert any('manifest digest differs' in p for p in ins.manifest_problems(forged, card))


def test_a_changed_catalogue_refuses_an_earlier_manifest(monkeypatch):
    card, step, manifest, _ = build('generator')
    cat = catalogue.installed()
    target = manifest['units'][5]['id']
    changed = deepcopy(cat.units[target])
    changed['text'] += ' A project-local edit.'
    changed['sha256'] = hashlib.sha256(changed['text'].encode()).hexdigest()
    fake = catalogue.Catalogue.__new__(catalogue.Catalogue)
    fake.__dict__.update(cat.__dict__)
    fake.units = {**cat.units, target: changed}
    monkeypatch.setattr(catalogue, 'installed', lambda: fake)
    with pytest.raises(ins.PacketRefused, match='unit differs from the installed catalogue: ' + target.replace('.', r'\.')):
        ins.packet(manifest, card, step, INPUTS)


def test_inputs_step_and_schema_are_bound_into_the_digest():
    card, step, manifest, packet = build('generator')
    other = [{'artifact': 's05:outputs/run_card.json', 'sha256': 'c' * 64}]
    assert ins.check_packet(packet, manifest, card, step, other)
    moved = {**step, 'rung': 'full'}
    assert ins.check_packet(packet, ins.manifest(moved, card), card, moved, INPUTS)
    reschema = {**packet, 'schema': {**packet['schema'], 'additionalProperties': True}}
    assert 'packet output schema differs from the contract' in ins.check_packet(reschema, manifest, card, step, INPUTS)


def test_context_units_go_on_demand_only_beyond_the_inline_budget(monkeypatch):
    card, step, manifest, packet = build('generator')
    context_ids = [next(e['id'] for e in manifest['units'] if e['via'] == via)
                   for via in ('preamble', 'must_read')]
    cat = reviewed_catalogue(monkeypatch, context_ids)
    from ravel.controller.instructions.budget import seat_budget
    # Fund the positive case from its declared seat window. Operation reading
    # contributes mandatory bytes independently of this context-deferral check.
    monkeypatch.setitem(cat.manifests['packet'], 'inline_tokens', seat_budget(card)['packet_tokens'])
    card, step, manifest, packet = build('generator')
    assert packet['deferred'] == []
    monkeypatch.setitem(cat.manifests['packet'], 'inline_tokens', 10)
    small = ins.packet(manifest, card, step, INPUTS)
    always = ('card', 'must_read')
    context = [e['id'] for e in manifest['units'] if e['kind'] == 'context' and e['via'] not in always]
    duty = [e['id'] for e in manifest['units'] if e['kind'] == 'duty' or e['via'] in always]
    assert small['deferred'] == context and set(duty) <= set(small['units'])
    for uid in duty:
        assert cat.units[uid]['text'] in small['text']
    for uid in context:
        index = next(i for i, e in enumerate(manifest['units']) if e['id'] == uid)
        assert f'- {uid} index:{index}' in small['text']
        assert manifest['units'][index]['sha256'] == cat.units[uid]['sha256']
    knowledge = [e['id'] for e in manifest['units'] if e['via'] == 'must_read' and e['kind'] == 'context']
    assert knowledge and set(knowledge) <= set(small['units'])  # must-read contents are never deferred
    served = ins.serve(context[0])
    assert served['text'] == cat.units[context[0]]['text'] and served['sha256'] == cat.units[context[0]]['sha256']
    with pytest.raises(KeyError):
        ins.serve('docs/workflow/start.md#nothing/0')


def test_a_step_naming_another_role_refuses_the_manifest():
    with pytest.raises(ins.PacketRefused, match="names role 'generator', not the card 'plan-critic'"):
        ins.manifest(step_for('generator'), role_registry.load('plan-critic'))


def test_a_role_seat_cannot_omit_its_effective_card():
    with pytest.raises(ins.PacketRefused, match='effective card'):
        ins.manifest(step_for('generator'), None)
    card = role_registry.load('generator')
    assert ins.manifest(step_for('generator'), card)['role'] == card['id']
    assert ins.manifest({'id': 'authority', 'kind': 'ask'}, None)['role'] is None


def test_duty_units_beyond_the_worker_context_are_refused_not_truncated():
    card, step, manifest, _ = build('figure-critic')
    budget = {'schema_version': 1, 'kind': 'instruction-packet-budget', 'packet_tokens': 1000, 'basis': 'fixture',
              'binding_model': 'fixture-model', 'tiers': ['agent'], 'candidates': []}
    with pytest.raises(ins.PacketRefused, match='mandatory packet core exceeds the packet budget for role figure-critic'):
        ins.packet(manifest, card, step, INPUTS, budget=budget)


@pytest.mark.parametrize('role', ROLES)
def test_every_role_packet_fits_the_worker_context_with_its_duty_units(role):
    card = role_registry.load(role)
    step = {'id': 'probe', 'kind': 'operate'}
    packet = ins.packet(ins.manifest(step, card), card, step, [])
    from ravel.controller.instructions import budget
    assert packet['budget'] == budget.seat_budget(card)
    assert packet['tokens'] <= packet['budget']['packet_tokens']


def test_receipt_and_store_record(tmp_path):
    card, step, manifest, packet = build('generator')
    store, session, _, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest,
                                             packet=packet, inputs=INPUTS)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    record = store.read('instruction-delivery', rid)
    assert record['manifest_sha256'] == manifest['sha256'] and record['packet_sha256'] == packet['sha256']
    assert record['units'] == [e['id'] for e in manifest['units']] and record['session'] == session
    assert record['catalogue_sha256'] == catalogue.installed().sha256
    assert record['run_id'] == store.run_id and record['attempt'] == 1


def test_discharge_marks_each_stated_obligation_from_the_acknowledgement(tmp_path):
    card, step, manifest, packet = build('generator')
    stated = ins.obligations(manifest)
    purpose, protocol, knowledge = 'ROLE-generator-purpose', 'ROLE-generator-protocol-0', 'ROLE-generator-knowledge'
    store, session, completion, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest,
                                                       packet=packet, inputs=INPUTS)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    final = store.records['worker-completion'][completion]['final_record']
    for row in final['checklist']:
        if row['unit'] == stated[protocol][0]:
            row.update(status='not_applicable', note='')
        if row['unit'] == stated[knowledge][0]:
            row.update(status='blocked', note='The handbook is withheld.')
    entries = {purpose: 'e1', protocol: 'e2', knowledge: 'e3', 'NOT-STATED': 'e4'}
    statuses = ins.discharge(store, entries, manifest, receipt_id=rid, ack_errors=[], record=ledger_record)
    assert statuses == {purpose: 'satisfied', protocol: 'violated', knowledge: 'pending', 'NOT-STATED': 'violated'}
    calls = store.scan('ledger-record')
    assert [c['entry_id'] for c in calls] == ['e4', 'e2', 'e1']
    assert calls[2]['evidence']['units'] == stated[purpose] and calls[2]['evidence']['ack'] == store.records['worker-completion'][completion]['id']


def test_discharge_counts_a_wrong_manifest_against_every_obligation(tmp_path):
    card, step, manifest, packet = build('generator')
    store, session, completion, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest,
                                                       packet=packet, inputs=INPUTS)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    final = store.records['worker-completion'][completion]['final_record']
    final['instruction_ack']['manifest_sha256'] = '0' * 64
    statuses = ins.discharge(store, {'ROLE-generator-purpose': 'e1'}, manifest, receipt_id=rid,
                             ack_errors=[], record=ledger_record)
    assert statuses == {'ROLE-generator-purpose': 'violated'}
    assert any(e.startswith('manifest:') for e in store.scan('ledger-record')[-1]['evidence']['errors'])
    uid = ins.obligations(manifest)['ROLE-generator-purpose'][0]
    next(r for r in final['checklist'] if r['unit'] == uid).update(status='blocked', note='Withheld.')
    assert ins.discharge(store, {'ROLE-generator-purpose': 'e1'}, manifest, receipt_id=rid,
                         ack_errors=[], record=ledger_record) == {'ROLE-generator-purpose': 'violated'}


def test_discharge_leaves_an_obligation_only_context_units_state_pending(tmp_path, monkeypatch):
    card, step, manifest, packet = build('generator')
    stated = ins.obligations(manifest)
    reviewed_catalogue(monkeypatch, stated['ROLE-generator-operations-0'])
    card, step, manifest, packet = build('generator')
    store, session, _, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest,
                                             packet=packet, inputs=INPUTS)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    statuses = ins.discharge(store, {'ROLE-generator-operations-0': 'e1', 'ROLE-generator-purpose': 'e2'},
                             manifest, receipt_id=rid, ack_errors=[], record=ledger_record)
    assert statuses == {'ROLE-generator-operations-0': 'pending', 'ROLE-generator-purpose': 'satisfied'}
    assert [(r['entry_id'], r['status']) for r in store.scan('ledger-record')] == [('e2', 'satisfied')]


def test_delivery_does_not_credit_other_mechanisms_even_when_their_units_are_duties(tmp_path):
    card, step, manifest, packet = build('generator')
    store, session, _, _, _, _, _ = observed(tmp_path, card=card, step=step, manifest=manifest,
                                             packet=packet, inputs=INPUTS)
    rid = ins.record_delivery(store, manifest, packet, session=session)
    assert ins.discharge(store, {'ROLE-generator-operations-0': 'e1'}, manifest, receipt_id=rid,
                         record=ledger_record) == {'ROLE-generator-operations-0': 'pending'}
    assert store.scan('ledger-record') == []


def test_packet_text_is_deterministic():
    _, _, _, first = build('physics-critic')
    _, _, _, second = build('physics-critic')
    assert first == second
    assert first['text'].startswith(delivery.PACKET_FORMAT + '\n')
