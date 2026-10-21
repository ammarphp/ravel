"""Actual installed packets preserve required work and reduce tier costs."""
from copy import deepcopy
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

import pytest

from ravel.controller import instructions
from ravel.controller.engagement import policy
from ravel.controller.engagement.builder import build_tier, installed_instructions
from ravel.controller.engagement.records import data, digest
from ravel.controller.instructions import catalogue, delivery
from test_p18_policy import fakes

ROOT = Path(__file__).resolve().parents[3]
SPEC = spec_from_file_location('tier_cost_builder', ROOT / 'scripts/maintenance/build_engagement_envelopes.py')
BUILD = module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


@pytest.fixture(scope='module')
def rebuilt():
    specs, pins = BUILD.route_specs(ROOT / 'src/ravel/data/controller/routes')
    sources = BUILD.source_inventory(ROOT / 'src/ravel/data')
    sources['routes'] = pins
    return BUILD.build(specs, cards=policy.role_cards(), instructions=installed_instructions(),
                       policy=policy.load_policy(), calibration=data('calibration.json'), source_pins=sources)


def test_every_installed_review_route_costs_less(rebuilt):
    specs, _ = BUILD.route_specs(ROOT / 'src/ravel/data/controller/routes')
    specs = {spec['id']: spec for spec in specs}
    cards = policy.role_cards()
    no_review = set(policy.load_policy()['no_review_routes'])
    # A route without review seats is one whose spec declares none; the policy list cannot hide a reviewed route.
    seatless = {route for route, spec in specs.items()
                if not policy.declared_seats({**spec, 'route': {'id': route}}, cards)}
    assert seatless == no_review & set(specs), (seatless, no_review)
    # The remaining entry names the resume of an existing run, not a route spec; a new non-route entry is reviewed here.
    assert no_review - set(specs) == {'resume'}
    assert set(rebuilt['routes']) == set(specs)
    for route, tiers in rebuilt['routes'].items():
        lean, standard, full = [tiers[t] for t in ('lean', 'standard', 'full')]
        if route in no_review:
            # No tier adds or removes a seat: every tier runs the same worker session per step, so sessions and
            # calls are equal, and the cost may differ only through the tier's packet text.
            for entry in (lean, standard, full):
                assert 'projection_tier' not in entry, (route, entry.get('scope_reason'))
                assert entry['central']['sessions'] == len(specs[route]['steps']), (route, entry['central'])
            for metric in ('sessions', 'calls'):
                assert lean['central'][metric] == standard['central'][metric] == full['central'][metric], (
                    route, metric)
            a, b, c = [e['central']['cost_usd'] for e in (lean, standard, full)]
            assert 0 < a <= b <= c, (route, a, b, c)
            continue
        assert 'projection_tier' not in lean, (route, lean.get('scope_reason'))
        assert 'projection_tier' not in standard, (route, standard.get('scope_reason'))
        for metric in ('sessions', 'calls', 'cost_usd'):
            a, b, c = [e['central'][metric] for e in (lean, standard, full)]
            assert a <= .75 * c, (route, metric, a, c)
            assert a <= b < c, (route, metric, a, b, c)
            assert b <= .95 * c, (route, metric, b, c)


@pytest.mark.parametrize('tier', ['lean', 'standard', 'full'])
def test_output_producing_reviews_retain_their_own_execution(tier):
    specs, _ = BUILD.route_specs(ROOT / 'src/ravel/data/controller/routes')
    count = 0
    for spec in specs:
        plan = {**spec, 'route': {'id': spec['id']}}
        seats = policy.seat_plan(plan, tier, instructions=installed_instructions(), projection=True)
        for step in plan['steps']:
            if step.get('kind') == 'review' and step.get('role') in ('physics-critic', 'integrity-auditor') and step.get('outputs'):
                key = f"producer:{step['id']}:{step['role']}"
                assert seats['bindings'][key] == key
                count += 1
    assert count


def test_committed_envelopes_are_exact_rebuilt_bytes(rebuilt):
    assert (ROOT / 'src/ravel/data/controller/engagement/envelopes.json').read_bytes() == BUILD.encode(rebuilt)


def test_installed_folded_seats_fit_runtime_shape():
    from ravel.controller import graph
    ins, cards, rules = installed_instructions(), policy.role_cards(), policy.load_policy()
    specs, _ = BUILD.route_specs(ROOT / 'src/ravel/data/controller/routes')
    count = 0
    for plan in specs:
        plan['route'] = {'id': plan['id']}
        plan['deliverables'] = [{**d, 'id': d.get('id', f'claim-{i}')}
                                for i, d in enumerate(plan.get('deliverables', []))]
        for tier in ('lean', 'standard'):
            seats = policy.seat_plan(plan, tier, rules, cards=cards, instructions=ins, projection=True)
            for seat in seats['seats']:
                if not seat['folded_roles']:
                    continue
                purpose = {'checkin2': 'waypoint', 'checkin3': 'final', 'attack': 'attacks',
                           'integrity': 'integrity'}.get(seat['category'])
                if purpose is None:
                    continue
                # Bind each descriptor in turn, including templates with several
                # verifier groups; test its actual runtime fields and sources.
                applied = {**plan, 'sha256': digest(plan), 'engagement': {'seat_plan': {'seats': [seat]}}}
                step = graph._seat_step(seat['role'], purpose=purpose, plan=applied)
                man = ins.manifest(step, seat['card'])
                packet = ins.packet(man, seat['card'], step, [])
                owed = {u['id'] for m in seat['manifests'][1:] for u in m['units'] if u['kind'] == 'duty'}
                assert owed <= set(packet['units'])
                assert packet['tokens'] <= packet['budget']['packet_tokens']
                assert not ins.check_packet(packet, man, seat['card'], step, [])
                count += 1
    assert count


def inert_plan(*, required=True):
    plan = fakes.fictional_plan()
    plan['steps'] = [{'id': 's1', 'kind': 'operate', 'operation': 'event-production', 'role': 'generator',
                      'rung': 'smoke' if required else 'reuse', 'review': [], 'waypoint': False}]
    plan['deliverables'] = [{'id': 'claim-1', 'step': 's1'}]
    if required:
        plan['checkins'][-1]['seats'].append('normalization-auditor')
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    return plan


def seats_for(plan, tier='lean'):
    cards = policy.role_cards()
    rules = fakes.policy_for(plan, cards)
    ins = installed_instructions()
    seats = policy.seat_plan(plan, tier, rules, cards=cards, instructions=ins)
    assert not seats['errors']
    return cards, rules, ins, seats


def test_lean_preserves_producer_fired_consult_and_required_specialist():
    plan = inert_plan()
    cards, rules, ins, seats = seats_for(plan)
    _, sessions = build_tier(plan, plan, 'lean', cards, ins, rules, data('calibration.json'))
    assert any(s['key'] == 'producer:s1:generator' for s in sessions)
    fired = [c for c in cards['generator']['knowledge']['consult'] if c['when'] == 'before_first_smoke']
    assert fired
    for consult in fired:
        assert any(s['key'] == f"consult:s1:{consult['role']}:before_first_smoke" for s in sessions)
    source = 'checkin:checkin3:normalization-auditor'
    seat = next(s for s in seats['seats'] if s['key'] == seats['bindings'][source])
    assert source in seat['source_seats']
    man = ins.manifest(seat['step'], seat['card'])
    packet = ins.packet(man, seat['card'], seat['step'], [])
    specialist = next(s for s in policy.declared_seats(plan, cards) if s['key'] == source)
    own = ins.manifest(specialist['step'], cards[specialist['role']])
    assert {u['id'] for u in own['units'] if u['kind'] == 'duty'} <= set(packet['units'])


def test_simple_lean_adds_no_unneeded_role_or_session():
    plan = inert_plan(required=False)
    cards, rules, ins, seats = seats_for(plan)
    _, lean = build_tier(plan, plan, 'lean', cards, ins, rules, data('calibration.json'))
    _, full = build_tier(plan, plan, 'full', cards, ins, rules, data('calibration.json'))
    assert {s['key'] for s in lean} <= {s['key'] for s in full}
    declared = {s['role'] for s in policy.declared_seats(plan, cards)}
    floors = {'plan-critic', 'physics-critic', 'skeptical-verifier', 'physics-decider', 'integrity-auditor'}
    assert all(s['role'] in declared | floors for s in seats['seats'])
    assert not any(s.get('trigger') == 'before_first_smoke' for s in lean)
    # Every obligation survives as exactly one source seat, including folded seats.
    complete = policy.seat_plan(plan, 'full', rules, cards=cards, instructions=ins)
    assert sorted(k for s in seats['seats'] for k in s['source_seats']) == sorted(complete['bindings'])


@pytest.fixture
def folded():
    _, _, ins, seats = seats_for(inert_plan())
    seat = next(s for s in seats['seats'] if s['folded_roles'])
    man = ins.manifest(seat['step'], seat['card'])
    return ins, seat, man


def test_folded_units_are_delivered_inline_and_acknowledged(folded):
    ins, seat, man = folded
    packet = ins.packet(man, seat['card'], seat['step'], [])
    own = {u['id'] for u in seat['manifests'][0]['units']}
    owed = {u['id'] for m in seat['manifests'][1:] for u in m['units']}
    assert owed - own
    assert owed <= {u['id'] for u in man['units']}
    assert all(u['via'] == 'folded' for u in man['units'] if u['id'] in owed - own)
    cat = catalogue.installed()
    for index, row in enumerate(man['units']):
        if row['kind'] == 'duty':
            assert row['id'] in packet['units']
            assert delivery._unit_block(cat.units[row['id']], index) in packet['text']
    assert 'List every duty index exactly once' in packet['text']
    assert not ins.check_packet(packet, man, seat['card'], seat['step'], [])


@pytest.mark.parametrize('defect', ['absent', 'changed'])
def test_folded_catalogue_mutation_refuses(folded, defect):
    ins, seat, _ = folded
    step = deepcopy(seat['step'])
    folded_man = step['engagement']['folded_manifests'][0]
    row = folded_man['units'][-1]
    if defect == 'absent':
        row['id'] = 'fictional:absent'
    else:
        row['sha256'] = '0' * 64
    folded_man['sha256'] = digest({k: v for k, v in folded_man.items() if k != 'sha256'})
    with pytest.raises(instructions.PacketRefused, match='folded'):
        ins.manifest(step, seat['card'])


def test_dispatch_refuses_removed_folded_duty(folded):
    ins, seat, man = folded
    packet = ins.packet(man, seat['card'], seat['step'], [])
    index, row = next((i, u) for i, u in enumerate(man['units']) if u['via'] == 'folded' and u['kind'] == 'duty')
    block = delivery._unit_block(catalogue.installed().units[row['id']], index)
    packet['text'] = packet['text'].replace(block, '')
    packet['sha256'] = sha256(packet['text'].encode()).hexdigest()
    assert ins.check_packet(packet, man, seat['card'], seat['step'], [])


def test_final_packet_includes_deferred_index_in_context_limit(folded, monkeypatch):
    ins, seat, man = folded
    cat = deepcopy(catalogue.installed())
    uid, text = 'fictional:context', 'Supporting context available through logged retrieval.'
    cat.units[uid] = {'id': uid, 'kind': 'context', 'sha256': sha256(text.encode()).hexdigest(), 'text': text}
    monkeypatch.setattr(delivery, '_cat', lambda: cat)
    man = deepcopy(man)
    man['units'].append({'id': uid, 'kind': 'context', 'sha256': cat.units[uid]['sha256'], 'via': 'folded'})
    man['sha256'] = digest({k: v for k, v in man.items() if k != 'sha256'})
    packet = ins.packet(man, seat['card'], seat['step'], [])
    assert packet['deferred'] == [uid]
    budget = {**packet['budget'], 'packet_tokens': packet['tokens'] - 1}
    with pytest.raises(instructions.PacketRefused, match='exceeds the packet budget'):
        ins.packet(man, seat['card'], seat['step'], [], budget=budget)


def test_rendered_references_preserve_items_and_runtime_packet(folded):
    ins, seat, man = folded
    from ravel.controller import graph
    plan = inert_plan()
    plan['engagement'] = {'seat_plan': {'seats': [seat]}}
    # Exercise the runtime seat's duplicate reviewer items as well as its union.
    purpose = {'checkin2': 'waypoint', 'checkin3': 'final'}[seat['category']]
    step = graph._seat_step(seat['role'], purpose=purpose, plan=plan)
    before = deepcopy(step)
    runtime_man = ins.manifest(step, seat['card'])
    packet = ins.packet(runtime_man, seat['card'], step, [])
    rendered = json.loads(packet['text'].split('== Step specification (step.v1) ==\n', 1)[1].split('\n\n== ', 1)[0])
    assert step == before
    for i, (original, shown) in enumerate(zip(seat['items'], rendered['engagement']['items'], strict=True)):
        assert shown['id'] == original['id']
        assert shown.get('check') == original.get('check')
        if 'census_ref' in shown:
            assert rendered['review_census_groups'][shown['census_ref']] == original['census']
        else:
            assert shown.get('census') == original.get('census')
        source = shown.get('source', {'review_required': 'producer checklist', 'must_check': 'reviewer card'}.get(shown['kind']))
        assert source == original.get('source')
        if 'source_seat_ref' in shown:
            source = rendered['review_source_seats'][shown['source_seat_ref']]
            assert source == original['source_seat']
            assert shown['id'][len(source) + 1:] == original['source_item_id']
        if 'unit_index' in shown:
            row = runtime_man['units'][shown['unit_index']]
            assert row['id'] == original['unit'] == shown['unit']
            assert row['sha256'] == original['sha256'] == shown['sha256']
            assert 'text' not in shown and original['text'] in packet['text']
        assert rendered['parameters']['reviewer_items'][i] == {'id': original['id'], 'engagement_item_index': i}
    assert rendered['engagement']['folded_manifests']
    for original, shown in zip(seat['manifests'][1:], rendered['engagement']['folded_manifests'], strict=True):
        assert shown['sha256'] == original['sha256'] and 'units' not in shown
    assert not ins.check_packet(packet, runtime_man, seat['card'], step, [])
    # The projection and runtime go through the same exact renderer and guard.
    assert not ins.check_packet(ins.packet(man, seat['card'], seat['step'], []), man, seat['card'], seat['step'], [])


def test_final_same_role_seat_carries_reviews_without_merging_independent_actors():
    plan = inert_plan()
    plan['steps'].append({'id': 's2', 'kind': 'review', 'role': 'physics-critic', 'review': []})
    plan['steps'][0]['review'] = ['physics-critic']
    cards, rules, ins, lean = seats_for(plan)
    source = 'step:s1:physics-critic'
    assert lean['bindings'][source] == 'checkin:checkin3:physics-critic'
    verifier = next(s for s in lean['seats'] if s['key'] == 'checkin:checkin3:skeptical-verifier')
    assert 'physics-critic' in verifier['constraints']['distinct_actor_from']
    assert source not in verifier['source_seats']
    full = policy.seat_plan(plan, 'full', rules, cards=cards, instructions=ins)
    assert full['bindings'][source] == source
    original = {i['id'] for s in full['seats'] for i in s['items']}
    assert original == {i['id'] for s in lean['seats'] for i in s['items']}


def test_fold_probe_includes_final_claims_attacks_and_constraints():
    cards = fakes.cards()
    plan = fakes.fictional_plan()
    rules = fakes.policy_for(plan, cards)

    class FinalOnly(fakes.FakeInstructions):
        @staticmethod
        def packet(man, card, step, inputs):
            engagement = step.get('engagement', {})
            if engagement.get('folded_manifests') and card['id'] == 'skeptical-verifier':
                assert any(i['kind'] == 'claim' for i in engagement['items'])
                assert engagement['constraints']['fresh_session']
                assert 'generator' in engagement['constraints']['distinct_actor_from']
                raise ValueError('final union does not fit')
            return fakes.FakeInstructions.packet(man, card, step, inputs)

    seats = policy.seat_plan(plan, 'lean', rules, cards=cards, instructions=FinalOnly)
    assert all(not s['folded_roles'] for s in seats['seats'] if s['role'] == 'skeptical-verifier')
    attack = next(s for s in seats['seats'] if s.get('attacks_required'))
    assert len([i for i in attack['items'] if i['kind'] == 'attack']) == 3


@pytest.mark.parametrize('state', ['ready', 'projected', 'missing'])
def test_checkin_shows_central_cost_and_typed_projection(state):
    from ravel.controller.graph import engagement_section
    entry = lambda n, cost: {'status': 'ready', 'central': {'sessions': n, 'calls': n * 3, 'cost_usd': cost}}
    chosen = entry(6, 3)
    if state == 'projected':
        chosen['projection_tier'] = 'full'
        chosen['scope_reason'] = 'fictional scope unavailable'
    decision = {'tier': 'lean', 'computed_tier': 'lean',
                'envelopes': {'full': entry(10, 5), **({'lean': chosen} if state != 'missing' else {})}}
    text = '\n'.join(engagement_section(decision)['lines'])
    if state == 'ready':
        assert 'at lean: 6 sessions, 18 calls, USD 3' in text
        assert 'at full: 10 sessions, 30 calls, USD 5' in text
        assert 'saving USD 2' in text and '40.0%' in text
    elif state == 'projected':
        assert 'projection_tier=full' in text and 'fictional scope unavailable' in text
    else:
        assert 'central cost: unavailable' in text and 'lean' in text
