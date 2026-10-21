"""Engagement attacks use actual policy, store, packets, ledger and sink bytes.

These controls exercise installed interfaces under the explicitly recorded candidate binding. Their success is distinct from a
complete controller trajectory; missing graph hooks and envelope projections stay findings.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from nc_cases import CONTROLLER, ROOT, case, require_controller
from nc_engagement import Probe
from nc_mutations import CONTROLLER as REAL, Mutation, register


def _ending(probe):
    probe.check()
    return probe.ending()


@case('EG01', binding=CONTROLLER)
def test_EG01_worker_tier_output_cannot_replace_code_decision(nc):
    probe = Probe(nc, 'eg01-code')
    state = {'plan': probe.decision['scientific_plan'], 'tier': 'lean',
             'engagement': {'tier': 'lean', 'accepted_allowed': True}}
    before = len(probe.store.scan('engagement-decision'))
    decision = probe.engagement.decide(probe.store, state)
    assert decision == probe.decision
    assert decision['tier'] == 'full', 'unknown scientific facts require the conservative tier'
    assert len(probe.store.scan('engagement-decision')) == before
    assert decision['policy_sha256'] and all('source' in f for f in decision['facts'].values())
    saved = _ending(probe)
    assert saved['engagement']['tier'] == 'full'
    assert saved['engagement']['decision_id'] == decision['record_id']
    # Positive control is determinism of the code-derived decision, independently of the worker field.
    assert probe.engagement.decide(probe.store, {'plan': decision['scientific_plan']}) == decision


@case('EG02', binding=CONTROLLER)
def test_EG02_unreviewed_low_complexity_claims_cannot_lower_engagement(nc):
    probe = Probe(nc, 'eg02-uncredited')
    facts = require_controller('engagement.facts')
    from ravel.controller.engagement.records import digest
    plan = probe.decision['scientific_plan']
    asserted = {'value': 'N0', 'plan_sha256': plan['sha256']}
    probe.store.append('engagement-novelty', asserted)
    probe.store.append('engagement-method', {'method': {'selected': {'method': 'reuse'}},
                                           'plan_sha256': plan['sha256']})
    decision = probe.engagement.decide(probe.store, {'plan': plan})
    assert decision['tier'] == 'full'
    assert decision['facts']['novelty']['value'] != 'N0'
    # A critic credit covers exact bytes and the exact scientific plan, never a newer assertion.
    subject = digest(asserted)
    record = {'plan_sha256': plan['sha256'], 'seats': {'plan-critic': {'credited': True, 'verdict': 'accept'}},
              'engagement_fact_sha256s': [subject]}
    review_id = probe.store.append('review', record)
    assert facts.credit_reviewed_facts(probe.store, plan, review_id)
    credited = probe.engagement.decide(probe.store, {'plan': plan})
    assert credited['facts']['novelty']['value'] == 'N0'
    probe.store.append('engagement-novelty', dict(asserted, extra='worker replaced the source'))
    assert probe.engagement.decide(probe.store, {'plan': plan})['facts']['novelty']['value'] != 'N0'
    _ending(probe)


@case('EG03', binding=CONTROLLER)
def test_EG03_dropping_floor_seats_refuses_the_real_ledger_edge(nc):
    probe = Probe(nc, 'eg03-seats')
    ledger = require_controller('ledger')
    # The graph composes the real gate providers at startup; this direct ledger probe must too.
    require_controller('graph').compose_services()
    plan = probe.plan
    assert probe.engagement.gate_errors(probe.store, 'checkin1->execute', plan=plan) == []
    attacked = deepcopy(plan)
    attacked['checkins'][0]['seats'] = []
    errors = probe.engagement.gate_errors(probe.store, 'checkin1->execute', plan=attacked)
    assert errors and all(e['row'] == 'EG03' for e in errors)
    from ravel.controller.engagement.records import digest

    def pin(view):
        view = deepcopy(view)
        view['engagement'].pop('applied_sha256')
        view['engagement']['applied_sha256'] = digest(view)
        scientific = probe.decision['scientific_plan']
        probe.store.append('plan', {
            'plan_sha256': scientific['sha256'],
            'blob': probe.store.put_blob(json.dumps(scientific, sort_keys=True).encode()),
            'applied_blob': probe.store.put_blob(json.dumps(view, sort_keys=True).encode()),
            'applied_sha256': view['engagement']['applied_sha256']})

    ledger.materialise(probe.store, 'intake', {'run_id': probe.store.run_id, 'route': 'calculation'})
    ledger.materialise(probe.store, 'plan', plan)
    pin(plan)
    clean = ledger.gate(probe.store, 'checkin1->execute')
    # Other obligations remain pending in this component probe. The installed engagement
    # provider must admit this exact current view, then refuse the altered one below.
    assert not [row for row in clean if row['entry'].startswith(('hook:', 'provider:'))], clean
    ledger.materialise(probe.store, 'plan', attacked)
    pin(attacked)
    unmet = ledger.gate(probe.store, 'checkin1->execute')
    # Preserve the real sink evidence even when the ledger composition is missing.
    _ending(probe)
    # A missing real provider is a wiring failure, never an acceptable refusal proxy.
    assert 'engagement_provider_missing' not in json.dumps(unmet), unmet
    assert any(row['entry'] == 'hook:engagement:EG03' for row in unmet), unmet


@case('EG04', binding=CONTROLLER)
def test_EG04_missing_folded_item_verdict_refuses_review_credit(nc):
    probe = Probe(nc, 'eg04-folded')
    instructions = require_controller('instructions')
    policy = require_controller('engagement.policy')
    plan = probe.decision['scientific_plan']
    seats = policy.seat_plan(plan, 'lean')
    folded = [s for s in seats['seats'] if s['folded_roles']]
    assert folded, 'real policy must retain folded role duties at lean'
    seat = folded[0]
    items = seat['items']
    assert items and seat['folded_cards'] and len(seat['source_seats']) > 1
    response = {'item_verdicts': [{'item': i['id'], 'verdict': 'pass',
                                 'evidence': [{'path': 'outputs/trace.json', 'pointer': '/value'}]}
                                for i in items]}
    assert instructions.check_item_verdicts(items, response) == []
    dropped = deepcopy(response)
    missing = dropped['item_verdicts'].pop()['item']
    assert any(missing in e and e.startswith('missing:')
               for e in instructions.check_item_verdicts(items, dropped))
    _ending(probe)


@case('EG05', binding=CONTROLLER)
def test_EG05_observed_trigger_records_rereview_and_never_lowers_tier(nc):
    probe = Probe(nc, 'eg05-escalation')
    original = probe.engagement.tier(probe.store)
    event = {'review': {'verdict': 'revise'}, 'step_id': probe.plan['steps'][0]['id'],
             'subject_sha256': 'a' * 64,
             'evidence': [{'kind': 'step-observation', 'record': probe.store.scan('step-observation')[0]['id']}]}
    raised = probe.engagement.observe(probe.store, event)
    assert raised['triggers'] == ['E2'] and raised['rereview']
    assert raised['old_tier'] == original == raised['new_tier'] == 'full'
    assert raised['seat_addition_class'] == 'R1' and not raised['plan_deviation']
    assert probe.engagement.observe(probe.store, event) == raised  # no duplicate retries or budget reset
    assert len(probe.store.scan('engagement-escalation')) == 1
    saved = _ending(probe)
    assert saved['engagement']['escalations']


@case('EG06', binding=CONTROLLER)
def test_EG06_environment_and_worker_files_do_not_lower_approved_tier(nc):
    probe = Probe(nc, 'eg06-switches')
    before = probe.decision
    nc.patch.setenv('RAVEL_ENGAGEMENT_TIER', 'lean')
    (probe.run_dir / 'engagement.json').write_text('{"tier":"lean"}')
    (probe.run_dir / 'outputs').mkdir(exist_ok=True)
    (probe.run_dir / 'outputs/engagement.json').write_text('{"tier":"lean"}')
    decision = probe.engagement.decide(probe.store, {'plan': before['scientific_plan'], 'tier': 'lean'})
    assert decision == before and decision['tier'] == 'full'
    assert probe.engagement.apply(before['scientific_plan'], decision) == probe.plan
    _ending(probe)


@case('EG12', binding=CONTROLLER)
def test_EG12_raise_only_never_accepts_lowering_or_unknown_tier(nc):
    probe = Probe(nc, 'eg12-raise')
    policy = require_controller('engagement.policy')
    from ravel.controller.engagement.records import EngagementRefused
    assert policy.raise_only('lean', 'full') == 'full'
    assert policy.raise_only('full', 'lean') == 'full'
    with pytest.raises(EngagementRefused):
        policy.raise_only('full', 'worker-chosen-tier')
    assert probe.engagement.decide(probe.store, {'plan': probe.decision['scientific_plan'], 'tier': 'lean'})['tier'] == 'full'
    _ending(probe)


@case('EG13', binding=CONTROLLER)
def test_EG13_lean_defers_context_but_never_duties_card_or_must_read(nc):
    probe = Probe(nc, 'eg13-packet')
    instructions = require_controller('instructions')
    policy = require_controller('engagement.policy')
    from ravel.workflow import role_registry
    from nc_engagement_binding import bind_optional_context_fixture
    card = role_registry.load('analysis-author')
    step = {'id': 'lean-producer', 'kind': 'author', 'role': card['id'],
            'engagement': deepcopy(policy.load_policy()['packet_scope']['lean'])}
    catalogue, binding = bind_optional_context_fixture(nc, card=card, step=step)
    probe.store.append('engagement-context-fixture-binding', {
        **binding, 'existing_candidate_binding': probe.binding['label']})
    context_uid = binding['unit']['id']
    step['instruction_sources'] = [context_uid]
    # Positive control: the full packet includes this exact optional input and its text.
    full = deepcopy(step)
    full['engagement'] = deepcopy(policy.load_policy()['packet_scope']['full'])
    full_manifest = instructions.manifest(full, card)
    full_packet = instructions.packet(full_manifest, card, full, [])
    assert instructions.check_packet(full_packet, full_manifest, card, full, []) == []
    assert context_uid in full_packet['units'] and context_uid not in full_packet['deferred']
    assert catalogue.units[context_uid]['text'] in full_packet['text']
    manifest = instructions.manifest(step, card)
    packet = instructions.packet(manifest, card, step, [])
    assert instructions.check_packet(packet, manifest, card, step, []) == []
    duties = {u['id'] for u in manifest['units'] if u['kind'] == 'duty' or u['via'] in ('must_read', 'card')}
    assert duties <= set(packet['units']) and not duties.intersection(packet['deferred'])
    assert json.dumps(card, indent=1, sort_keys=True, ensure_ascii=False) in packet['text']
    changed = dict(packet, text=packet['text'].replace('== Effective role card (every field) ==', ''))
    changed['sha256'] = hashlib.sha256(changed['text'].encode()).hexdigest()
    assert instructions.check_packet(changed, manifest, card, step, [])
    _ending(probe)
    contexts = {u['id'] for u in manifest['units'] if u['kind'] != 'duty' and u['via'] not in ('must_read', 'card')}
    assert contexts == {context_uid}
    assert contexts <= set(packet['deferred']), (
        'EG13 lean packet must defer the explicitly synthetic optional context input', binding, packet['deferred'])


@case('EG14', binding=CONTROLLER)
def test_EG14_scan_sample_is_seeded_complete_for_anomalies_and_requires_launches(nc):
    probe = Probe(nc, 'eg14-sample')
    policy = require_controller('engagement.policy')
    points = [f'point-{i:03d}' for i in range(20)]
    pin = probe.decision['scientific_plan_sha256']
    first = policy.scan_sample(points, 'standard', pin, anomalies=[points[-1]])
    assert first == policy.scan_sample(points, 'standard', pin, anomalies=[points[-1]])
    assert points[-1] in first and set(first) <= set(points)
    assert len(policy.scan_sample(points, 'full', pin)) == 9  # ceil(2*sqrt(20))
    receipts = [{'point_id': point, 'governed': True, 'receipt_id': 'launch-' + point} for point in points]
    clean = policy.check_scan(points, receipts, first, 'standard', pin, anomalies=[points[-1]])
    assert all(value == [] for value in clean.values()), clean
    missing = policy.check_scan(points, receipts[:-1], [p for p in first if p != points[-1]],
                                'standard', pin, anomalies=[points[-1]])
    assert missing['missing_receipts'] == [points[-1]]
    assert missing['missing_reviews'] == [points[-1]]
    # This covers the actual sampling contract; controller invocation is tracked independently.

    _ending(probe)


register(Mutation('M02', 'ravel.controller.engagement.facts:_reviewed',
                  lambda original: lambda store, record, plan_sha: bool(record), ('EG02',), binding=REAL,
                  why='uncredited engagement facts receive lowering credit'))
register(Mutation('M01', 'ravel.controller.engagement:check_applied',
                  lambda original: lambda *a, **k: [], ('EG03',), binding=REAL,
                  why='mutated engagement seat roster bypasses the plan gate'))


def test_installed_checkin_selector_resolves_the_step_schema_names_to_their_templates(nc):
    """Retired source negative (the installed resolver now names check-ins as the step schema does): each logical
    name resolves to exactly its template's units (CI1/2/3); a name with no template is still refused."""
    from nc_engagement_binding import ALIASES
    catalogue = require_controller('instructions.catalogue').installed()
    for alias, template in ALIASES.items():
        expected = catalogue.resolve_all(catalogue.manifests['checkins'].get('common', [])
                                         + catalogue.manifests['checkins'][template])
        assert catalogue.resolve('checkin:' + template) == expected
        assert catalogue.resolve('checkin:' + alias) == expected
    with pytest.raises(KeyError, match='unknown instruction selector'):
        catalogue.resolve('checkin:checkin9')


def test_installed_envelope_projection_is_current_and_covers_every_route_and_tier(nc):
    from ravel.controller.engagement.envelope import defaults, installed_projection
    from ravel.controller.engagement.records import data
    installed = installed_projection()
    assert installed == data('envelopes.json') and installed['status'] == 'ready'
    routes = set()
    for path in (ROOT / 'src/ravel/data/controller/routes').glob('*.json'):
        document = json.loads(path.read_text())
        routes.update(spec['id'] for spec in document.get('specs', [document]))
    assert set(installed['routes']) == routes and routes
    for route, tiers in installed['routes'].items():
        assert set(tiers) == {'lean', 'standard', 'full'}, route
        for tier, projection in tiers.items():
            assert projection['status'] == 'ready', (route, tier, projection)
            budget = defaults(route, tier)
            assert budget and all(value > 0 for value in budget.values()), (route, tier, budget)
            assert all(projection['low'][metric] <= projection['central'][metric]
                       <= projection['high'][metric] for metric in projection['central'])


def test_installed_synthetic_floor_steps_are_not_checkin_templates(nc):
    catalogue = require_controller('instructions.catalogue').installed()
    for category in ('attack', 'integrity'):
        assert category not in catalogue.manifests['checkins']
        with pytest.raises(KeyError, match='unknown instruction selector'):
            catalogue.resolve('checkin:' + category)
