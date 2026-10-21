"""P18 mechanical policy invariants over fictional, fully local evidence."""
from collections import Counter
from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from itertools import product
import json
import math
from pathlib import Path

import pytest

from ravel.controller.engagement import facts, policy
from ravel.controller.engagement.records import EngagementRefused, TIERS, digest
from ravel.controller.judgment.classes import classify, explain, tables

_FIXTURE_PATH = Path(__file__).parents[2] / 'fixtures/engagement/fakes.py'
_SPEC = spec_from_file_location('p18_policy_fakes', _FIXTURE_PATH)
fakes = module_from_spec(_SPEC)
_SPEC.loader.exec_module(fakes)


@pytest.fixture
def fixture_world(monkeypatch):
    cards = fakes.cards()
    instructions = fakes.install_fakes(monkeypatch, cards_override=cards)
    plan = fakes.fictional_plan()
    return plan, cards, instructions, fakes.policy_for(plan, cards)


def rank(result):
    return TIERS.index(result['tier'])


def test_installed_route_steps_classify_to_their_table_class():
    from ravel.controller.routes.select import installed_specs

    table = tables()
    covered = 0
    for spec in installed_specs():
        for step in spec['steps']:
            action = facts.action_of(step)
            expected = [table['step_kind'][step['kind']]]
            unknown = []
            for field, value in [('kind', step.get('operation')), ('rung', step.get('rung'))]:
                if value is not None:
                    if value in table[field]:
                        expected.append(table[field][value])
                    else:
                        unknown.append(f'{field}={value!r}')
            # Declared step effects are factors too (after the fields, as explain reports them).
            for effect in [*(step.get('effects') or []), *((step.get('parameters') or {}).get('effects') or [])]:
                if effect in table['effects']:
                    expected.append(table['effects'][effect])
                else:
                    unknown.append(f'effect={effect!r}')
            if step.get('consequence_class'):
                expected.append(step['consequence_class'])
            observed = explain(action)
            assert observed['unknown'] == unknown, (spec['id'], step['id'], observed)
            assert observed['class'] == ('R3' if unknown else max(expected))
            if not unknown:
                covered += 1
                assert observed['unknown'] == []
    assert covered > 0
    for kind, expected in [('bookkeeping', 'R0'), ('source_lookup', 'R1'),
                           ('method_choice', 'R2'), ('prescription_change', 'R3')]:
        step = {'kind': 'review', 'operation': kind}
        assert explain(facts.action_of(step))['unknown'] == []
        assert classify(facts.action_of(step)) == expected
        for declared in ('R0', 'R1', 'R2', 'R3'):
            assert classify(facts.action_of({**step, 'consequence_class': declared})) == max(expected, declared)
    assert explain(facts.action_of({'kind': 'decide', 'operation': 'unregistered'}))['unknown']
    assert classify(facts.action_of({'kind': 'decide', 'operation': 'unregistered'})) == 'R3'


@pytest.mark.parametrize('action,expected', [
    ({'kind': 'method_choice'}, 'R2'),
    ({'kind': 'bookkeeping', 'effects': ['unblind']}, 'R3'),
    ({'kind': 'bookkeeping', 'gate': 'unblind'}, 'R3'),
    ({'kind': 'bookkeeping', 'research_choice': 'method_performance'}, 'R3'),
])
def test_decision_action_projection_retains_all_factors(action, expected):
    step = {'kind': 'decide', 'parameters': {'judgment': {'action': action}}, 'consequence_class': 'R0'}
    assert explain(facts.action_of(step))['unknown'] == []
    assert classify(facts.action_of(step)) == max('R1', expected)


@pytest.mark.parametrize('declared', ['R0', 'R1', 'R2', 'R3', 'invalid'])
def test_collected_consequence_uses_current_class_field(monkeypatch, declared):
    import ravel.controller.judgment as judgment
    monkeypatch.setattr(judgment, 'classify', classify)
    plan = fakes.fictional_plan()
    plan['steps'] = [{'id': 'choice', 'kind': 'decide', 'action': {'kind': 'method_choice'},
                      'consequence': 'R0', 'consequence_class': declared}]
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    store = fakes.FakeRunStore()
    store.append('plan', {'plan': plan, 'plan_sha256': plan['sha256']})
    collected, _ = facts.collect(store, {}, policy.load_policy())
    assert collected['consequence']['value'] == (max('R2', declared) if declared != 'invalid' else 'R3')


def test_EG01_exhaustive_single_factor_lattice():
    installed = policy.load_policy()
    axes = {'route': ['analysis', 'analysis.scan', 'research'],
            'deliverables': [0, 2, 3, 6, 7], 'consequence': ['R0', 'R1', 'R2', 'R3'],
            'compute': ['C0', 'C1', 'C2', 'C3'], 'novelty': ['N0', 'N1', 'N2'],
            'special': [[], ['mixed_request'], ['unblinding']]}
    names = list(axes)
    results = {}
    for indices in product(*(range(len(axes[n])) for n in names)):
        checked = fakes.checked_facts(**{n: axes[n][i] for n, i in zip(names, indices)})
        result = policy.tier(checked, installed)
        independent_ranks = ([0, 1, 2], [0, 0, 1, 1, 2], [0, 0, 1, 2],
                             [0, 0, 1, 2], [0, 1, 2], [0, 1, 2])
        expected = max(values[i] for values, i in zip(independent_ranks, indices))
        assert rank(result) == expected
        assert max(TIERS.index(v) for v in result['minimum_tiers'].values()) == expected
        assert len(result['reasons']) == len(names)
        assert all(r['source'] == 'fixture:' + r['fact'] for r in result['reasons'])
        results[indices] = rank(result)
    for indices, value in results.items():
        for axis, name in enumerate(names):
            if indices[axis] + 1 < len(axes[name]):
                following = list(indices)
                following[axis] += 1
                assert results[tuple(following)] >= value, (name, indices)


@pytest.mark.parametrize('name', facts.FACTS)
@pytest.mark.parametrize('defect', ['missing', 'unchecked', 'no_source', 'unknown'])
def test_EG02_unchecked_or_unknown_is_full(name, defect):
    checked = fakes.checked_facts()
    if defect == 'missing':
        checked.pop(name)
    elif defect == 'unchecked':
        checked[name]['checker'] = 'worker'
    elif defect == 'no_source':
        checked[name]['source'] = ''
    else:
        checked[name]['value'] = None
    assert policy.tier(checked, policy.load_policy())['tier'] == 'full'


@pytest.mark.parametrize('computed,requested', product(TIERS, TIERS))
def test_EG12_raise_only_never_lowers(computed, requested):
    # A minimum or raise below the current tier has no effect; it never lowers or aborts the decision.
    assert policy.raise_only(computed, requested) == TIERS[max(TIERS.index(computed), TIERS.index(requested))]
    assert policy.raise_only(computed, None) == computed


def test_EG02_compute_thresholds_preserve_or_raise_engagement():
    from ravel.workflow.method_selection import validate_method_decision
    method = json.loads((Path(__file__).parents[2] / 'fixtures/method_decisions/standard_table.json').read_text())
    installed = policy.load_policy()
    for hours, points, expected in [(200, 1, 'C0'), (200.01, 1, 'C2'),
                                     (2000, 25, 'C2'), (2000.01, 25, 'C3'), (2000, 26, 'C3')]:
        candidate = deepcopy(method)
        candidate['cost_forecast']['cpu_hours'] = hours
        assert validate_method_decision(candidate) == []
        observed = facts.compute_class(candidate, installed, points=points)
        assert observed == expected
        lower = policy.tier(fakes.checked_facts(compute=observed), installed)
        assert rank(lower) >= installed['tier_rules']['compute'][expected]
    for points in (-1, 1.5, True):
        assert facts.compute_class(method, installed, points=points) == 'C3'


def duty_multiset(seats):
    return Counter((item['id'], item['source_binding'])
                   for seat in seats if not seat.get('conditional')
                   for item in seat['items'] if item.get('kind') == 'duty')


@pytest.mark.parametrize('selected', TIERS)
def test_EG04_CF08_STEP_09_verify_folding_preserves_exact_duties_and_source_bindings(fixture_world, selected):
    plan, cards, instructions, installed = fixture_world
    full = policy.seat_plan(plan, 'full', installed, cards=cards, instructions=instructions)
    result = policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)
    assert result['errors'] == []
    # A reviewed_by-only role is a real source seat, including on a step with no explicit reviewers.
    derived='step:s2:object-selection-mapper'
    assert full['bindings'][derived]==derived
    assert (result['bindings'][derived]==derived) is (selected!='lean')
    if selected=='standard':
        assert result['bindings']['step:s1:object-selection-mapper']!='step:s1:object-selection-mapper'
    assert duty_multiset(result['seats']) == duty_multiset(full['seats'])
    active = {s['key']: s for s in result['seats'] if not s.get('conditional')}
    assert result['bindings'].keys() == full['bindings'].keys()
    assert Counter(source for s in active.values() for source in s['source_seats']) == Counter(full['bindings'].keys())
    for source, target in result['bindings'].items():
        assert source in active[target]['source_seats']
    fixed = 'checkin:checkin1:plan-critic'
    assert result['bindings'][fixed] == fixed
    assert active[fixed]['role'] == 'plan-critic'
    assert result['authority_nodes'] == ['checkin1', 'checkin2', 'checkin3']
    assert set(result['claim_coverage']) == {'claim-1', 'claim-2'}
    for claim, seat_key in result['claim_coverage'].items():
        assert any(i.get('claim_id') == claim for i in active[seat_key]['items'])
    attacks = [s for s in active.values() if s.get('attacks_required')]
    assert len(attacks) == 1
    assert attacks[0]['attacks_required'] == result['attacks_required'] == 3
    assert attacks[0]['attacks_before_verdict'] is True
    assert len([i for i in attacks[0]['items'] if i['kind'] == 'attack']) == 3


@pytest.mark.parametrize('conflict', ['distinct_actor', 'input_overlap', 'blind_capability'])
def test_EG04_independence_conflicts_keep_seat_separate(fixture_world, conflict):
    plan, cards, instructions, installed = fixture_world
    target = cards['skeptical-verifier']
    source = cards['physics-decider']
    if conflict == 'distinct_actor':
        source['independence']['distinct_actor_from'] = [target['id']]
    elif conflict == 'input_overlap':
        source['sees']['forbidden_inputs'] = ['restricted']
        target['sees']['required_inputs'] = ['restricted']
    else:
        source['independence']['blind'] = True
        target['blind_capable'] = False
    result = policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)
    key = 'checkin:checkin3:physics-decider'
    assert result['bindings'][key] == key
    assert any(s['key'] == key for s in result['seats'])


@pytest.mark.parametrize('conflict', ['target_distinct_from_source', 'carried_role_distinct_from_source',
                                      'source_distinct_from_carried_role'])
def test_EG04_F12_fold_refuses_every_carried_actor_conflict(conflict):
    def card(role, distinct=()):
        return {'id': role, 'independence': {'fresh_session': True, 'distinct_actor_from': list(distinct)}, 'sees': {}}
    target, source = card('final-reviewer'), card('folded-reviewer')
    if conflict == 'target_distinct_from_source':
        target['independence']['distinct_actor_from'] = ['folded-reviewer']
    elif conflict == 'carried_role_distinct_from_source':
        target['folded_cards'] = [card('carried-reviewer', ['folded-reviewer'])]
    else:
        target['folded_cards'] = [card('carried-reviewer')]
        source['independence']['distinct_actor_from'] = ['carried-reviewer']
    assert policy.fold_constraints(target, source) is None
    # Positive control: the same cards without the actor conflict fold with the union of constraints.
    clean = card('final-reviewer', ['producer-role'])
    clean['folded_cards'] = [card('carried-reviewer', ['other-producer'])]
    merged = policy.fold_constraints(clean, card('folded-reviewer', ['third-producer']))
    assert merged['distinct_actor_from'] == ['other-producer', 'producer-role', 'third-producer']


@pytest.mark.parametrize('difference', ['role', 'subject', 'attempt', 'constraints', 'duties',
                                       'missing_subject', 'missing_attempt'])
def test_CF08_deduplication_requires_exact_role_subject_constraints_duties(difference):
    first = {'key': 'a', 'role': 'physics-critic', 'subject_sha256': digest('subject'), 'attempt': 1,
             'constraints': {'blind': True}, 'items': [{'id': 'duty-1'}]}
    same = {**deepcopy(first), 'key': 'b'}
    kept, bindings = policy.deduplicate([first, same])
    assert len(kept) == 1 and bindings == {'a': 'a', 'b': 'a'}
    different = {**deepcopy(first), 'key': 'c'}
    if difference == 'role':
        different['role'] = 'skeptical-verifier'
    elif difference == 'subject':
        different['subject_sha256'] = digest('other')
    elif difference == 'attempt':
        different['attempt'] = 2
    elif difference == 'constraints':
        different['constraints']['blind'] = False
    elif difference == 'duties':
        different['items'].append({'id': 'duty-2'})
    elif difference == 'missing_subject':
        first.pop('subject_sha256')
        different.pop('subject_sha256')
    else:
        first.pop('attempt')
        different.pop('attempt')
    kept, bindings = policy.deduplicate([first, different])
    assert len(kept) == 2 and bindings == {'a': 'a', 'c': 'c'}


@pytest.mark.parametrize('selected,multiplier', [('standard', 1), ('full', 2)])
@pytest.mark.parametrize('count', [0, 1, 2, 9, 25, 40])
def test_EG14_scan_sample_deterministic_sqrt_plus_anomalies(selected, multiplier, count):
    points = [f'p{i:03d}' for i in range(count)]
    seed = digest('fictional-plan')
    expected_count = min(count, math.ceil(multiplier * math.sqrt(count)))
    sampled = policy.scan_sample(points, selected, seed)
    assert len(sampled) == expected_count
    assert sampled == policy.scan_sample(list(reversed(points)), selected, seed)
    anomalies = points[-2:]
    with_anomalies = policy.scan_sample(points, selected, seed, anomalies)
    assert set(with_anomalies) == set(sampled) | set(anomalies)


def test_EG14_scan_receipt_and_review_holes():
    points = [f'p{i}' for i in range(9)]
    seed = digest('fictional-plan')
    sampled = policy.scan_sample(points, 'standard', seed)
    receipts = [{'point_id': p, 'governed': True, 'receipt_id': 'receipt:' + p} for p in points]
    result = policy.check_scan(points, receipts, sampled, 'standard', seed)
    assert all(not v for v in result.values())
    receipts[0]['governed'] = False
    receipts[1].pop('receipt_id')
    receipts += [deepcopy(receipts[2]), {'point_id': 'outside', 'governed': True, 'receipt_id': 'extra'}]
    result = policy.check_scan(points, receipts, sampled[1:], 'standard', seed)
    assert result == {'missing_receipts': ['p0', 'p1'], 'surplus_receipts': ['outside'],
                      'duplicate_receipts': ['p2'], 'missing_reviews': sampled[:1]}


def test_EG13_packet_defers_only_optional_context_and_rebuild_detects_loss(fixture_world):
    plan, cards, instructions, installed = fixture_world
    result = policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)
    folded = next(s for s in result['seats'] if s['folded_roles'])
    card = folded['card']
    assert card == cards[folded['role']]
    assert folded['step']['engagement']['items'] == folded['items']
    assert folded['step']['engagement']['folded_manifests'] == folded['manifests'][1:]
    assert folded['step']['engagement']['folded_cards'] == folded['folded_cards']
    step = {**folded['step'], 'engagement': {**folded['step']['engagement'], 'inline_context_tokens': 0}}
    manifest = instructions.manifest(step, card)
    packet = instructions.packet(manifest, card, step, [])
    assert packet['card'] == card
    assert packet['must_read']
    assert packet['deferred_reads'] and all(u['kind'] == 'context' for u in packet['deferred_reads'])
    assert Counter(u['id'] for u in packet['units'] + packet['deferred_reads']) == Counter(u['id'] for u in manifest['units'])
    assert all(u in packet['units'] for u in packet['must_read'])
    assert instructions.check_packet(packet, manifest, card, step, []) == []
    packet['units'].pop()
    assert instructions.check_packet(packet, manifest, card, step, [])


@pytest.mark.parametrize('consequence', ['R0', 'R1', 'R2', 'R3'])
def test_EG03_decision_cases_precede_effects_and_retain_authority(fixture_world, consequence, monkeypatch):
    plan, cards, instructions, installed = fixture_world
    import ravel.controller.judgment as judgment
    monkeypatch.setattr(judgment, 'classify', classify)
    plan['steps'].append({'id': 's3', 'kind': 'decide', 'role': 'physics-decider',
                          'action': {'kind': 'reversible_choice'}, 'consequence_class': consequence})
    result = policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)
    assert result['rdj_cases'] == ([{'step_id': 's3', 'before_effect': True}] if consequence in ('R2', 'R3') else [])
    assert result['r3_authority'] == (['s3'] if consequence == 'R3' else [])
    assert set(result['authority_nodes']) == {'checkin1', 'checkin2', 'checkin3'}


def test_EG03_unclassified_policy_seat_is_kept_and_errors(fixture_world):
    plan, cards, instructions, installed = fixture_world
    plan['steps'][0]['review'].append('trap-auditor')
    result = policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)
    key = 'step:s1:trap-auditor'
    assert result['bindings'][key] == key
    assert any(key in message for message in result['errors'])
    plan['steps'][0]['review'].append('unregistered-role')
    with pytest.raises(EngagementRefused, match='unknown seat role'):
        policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)


@pytest.mark.parametrize('route', ['inspect', 'legacy'])
@pytest.mark.parametrize('selected', TIERS)
def test_EG03_no_review_routes_have_empty_floors(route, selected, fixture_world):
    plan, cards, instructions, installed = fixture_world
    plan['route']['id'] = route
    result = policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)
    assert result['seats'] == [] and result['bindings'] == {}
    assert result['authority_nodes'] == [] and result['claim_coverage'] == {}
    assert result['attacks_required'] == 0 and result['errors'] == []
    assert result['sha256'] == digest({k: v for k, v in result.items() if k != 'sha256'})


@pytest.mark.parametrize('selected', ['standard', 'full'])
def test_EG03_claim_seats_cover_each_claim_at_most_six(selected, fixture_world):
    _, cards, instructions, _ = fixture_world
    plan = fakes.fictional_plan(claims=7)
    installed = fakes.policy_for(plan, cards)
    result = policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)
    assert set(result['claim_coverage']) == {d['id'] for d in plan['deliverables']}
    assert sorted(Counter(result['claim_coverage'].values()).values()) == [1, 6]
    with pytest.raises(EngagementRefused, match='lean claim coverage exceeded'):
        policy.seat_plan(plan, 'lean', installed, cards=cards, instructions=instructions)
    plan['deliverables'][1]['id'] = plan['deliverables'][0]['id']
    with pytest.raises(EngagementRefused, match='duplicate deliverable'):
        policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)


@pytest.mark.parametrize('selected', ['lean', 'standard'])
def test_EG03_research_folds_preserve_duties_and_prepare_seats(selected, fixture_world):
    _, cards, instructions, _ = fixture_world
    plan = fakes.fictional_plan(route='research')
    installed = fakes.policy_for(plan, cards)
    result = policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)
    full = policy.seat_plan(plan, 'full', installed, cards=cards, instructions=instructions)
    assert set(result['bindings']) == set(full['bindings'])
    assert len(result['seats']) < len(full['seats'])
    assert {i['id'] for s in result['seats'] for i in s['items']} == {i['id'] for s in full['seats'] for i in s['items']}
    assert set(result['claim_coverage']) == set(full['claim_coverage'])
    assert result['attacks_required'] == full['attacks_required'] == 3
    assert result['bindings']['checkin:checkin1:plan-critic'] == 'checkin:checkin1:plan-critic'
    retained = {s['key']: s for s in result['seats']}
    for source in full['seats']:
        target = retained[result['bindings'][source['key']]]
        for field in ('required_inputs', 'forbidden_inputs', 'distinct_actor_from'):
            assert set(source['constraints'][field]) <= set(target['constraints'][field])
        for field in ('fresh_session', 'blind'):
            if source['constraints'][field]:
                assert target['constraints'][field]
    plan = fakes.fictional_plan()
    plan['steps'][0]['parameters'] = {'phase': 'prepare'}
    installed = fakes.policy_for(plan, cards)
    result = policy.seat_plan(plan, selected, installed, cards=cards, instructions=instructions)
    assert all(source == target for source, target in result['bindings'].items() if source.startswith('step:s1:'))


@pytest.mark.parametrize('points,tier,seed,anomalies', [
    (['p1'], 'lean', digest('plan'), []),
    (['p1', 'p1'], 'standard', digest('plan'), []),
    (['p1'], 'standard', digest('plan'), ['outside']),
    (['p1'], 'standard', 'unbound', []),
])
def test_EG14_scan_refuses_invalid_population_or_seed(points, tier, seed, anomalies):
    with pytest.raises(EngagementRefused):
        policy.scan_sample(points, tier, seed, anomalies)


def test_EG12_raise_only_refuses_unknown_tier():
    with pytest.raises(EngagementRefused):
        policy.raise_only('lean', 'unknown')
