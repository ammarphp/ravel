"""Plan-bound scan review populations with inert point execution and the real ledger."""
from copy import deepcopy
import json

import pytest

from ravel.controller import engagement, ledger
from ravel.controller.engagement import policy
from ravel.controller.engagement.records import digest
from ravel.controller.ledger import state as ledger_state
from ravel.controller.routes.analysis import execution, scan
from ravel.controller.sink import checks
from p02_support import (FakeStore, INTAKE, RUN, fixture_catalogue, row, satisfy,
                              use_catalogue)
from p09_support import compile_plan, contract, reading
from test_p18_policy import fakes


def applied_scan(monkeypatch, *, expanded=False, tier='standard', anomaly=True):
    if expanded:
        plan = compile_plan('analysis.scan', reading(scan=True, values=tuple(range(1, 17))), contract('scan'))
        cards = policy.role_cards()
        points = [p['id'] for p in plan['parameters']['grid']['points']]
        if anomaly:
            plan['parameters']['scan_anomalies'] = [points[-1]]
    else:
        points = [f'p{i:02d}' for i in range(16)]
        plan = {'route': {'id': 'analysis.scan'}, 'deliverables': [], 'checkins': [],
                'steps': [{'id': 'grid', 'kind': 'produce', 'role': 'generator',
                           'review': ['physics-critic'], 'points': points,
                           'scan_anomalies': points[-1:] if anomaly else []}]}
        cards = fakes.cards()
        cards['generator']['reviewed_by'] = []
    plan['sha256'] = digest({k: v for k, v in plan.items() if k != 'sha256'})
    installed = fakes.policy_for(plan, cards)
    for rules in installed['seat_plans'][plan['route']['id']].values():
        rules['standard'] = 'keep'
    installed['sha256'] = digest({k: v for k, v in installed.items() if k != 'sha256'})
    monkeypatch.setattr(policy, 'load_policy', lambda: deepcopy(installed))
    roster = policy.seat_plan(plan, tier, installed, cards=cards, instructions=fakes.FakeInstructions)
    decision = {'policy_sha256': installed['sha256'], 'scientific_plan': plan,
                'scientific_plan_sha256': plan['sha256'], 'seat_plan': roster,
                'seat_plan_sha256': roster['sha256'], 'tier': tier,
                'correction_bound': installed['correction_rounds'][tier],
                'packet_scope': installed['packet_scope'][tier]}
    decision['sha256'] = digest(decision)
    return plan, engagement.apply(plan, decision), points


def scan_store(monkeypatch, tmp_path, scientific, applied, *, every_point=False, blobs=False):
    rows = [row('X-POINT', 'route.analysis.scan', 'plan', 'point'),
            row('X-REVIEW', 'review.credit', 'review', 'seat', cls='R')]
    if every_point:
        rows.append(row('ROLE-checker-every-point', 'step.packet[checker]', 'plan', 'point', cls='I',
                        ledger_class='role/instruction', waivability='never'))
    installed_rows = ledger.load_catalogue().rows
    declared = set(applied.get('obligations', []))
    for step in applied['steps']:
        declared.update(step.get('obligations', []))
    rows.extend(json.loads(json.dumps(installed_rows[rid], default=dict)) for rid in sorted(declared))
    use_catalogue(monkeypatch, fixture_catalogue(rows))
    store = FakeStore(RUN, root=tmp_path)
    ledger.materialise(store, 'intake', {**INTAKE, 'deliverables': []})
    pin = {'plan': scientific, 'plan_sha256': scientific['sha256'], 'applied_plan': applied,
           'applied_sha256': applied['engagement']['applied_sha256']}
    if blobs:
        from hashlib import sha256
        store.path('blobs').mkdir()
        for key, target in [('plan', 'blob'), ('applied_plan', 'applied_blob')]:
            raw = json.dumps(pin.pop(key), sort_keys=True).encode()
            pointer = sha256(raw).hexdigest()
            store.path('blobs', pointer).write_bytes(raw)
            pin[target] = pointer
    store.append('plan', pin)
    ledger.materialise(store, 'plan', {'plan': applied})
    keys = ledger.materialise(store, 'review', {'step': 'plan_review', 'seat': 'plan-critic', 'attempt': 1})
    satisfy(store, keys)
    return store


def enter_grid(store, applied, reviewed, *, omit=None):
    step = applied['steps'][0]
    for point in step['points']:
        if point == omit:
            continue
        ledger.materialise(store, 'dispatch', {'step': step['id'], 'seat': 'generator',
                                               'seat_kind': 'worker', 'point': point, 'attempt': 1})
    # A review attempt records the card that sat it, as the controller does; the gate matches seats by card.
    review = next(s for s in step['seats'] if s['kind'] == 'review')
    for point in reviewed:
        keys = ledger.materialise(store, 'review', {'step': step['id'], 'seat': review['seat'],
                                                    'role': review['role'], 'point': point, 'attempt': 1})
        satisfy(store, keys)
    satisfy(store, [key for key in ledger.pending(store) if key.startswith('X-POINT@')])


def test_scan_declares_sample_before_dispatch_and_keeps_all_point_steps(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch, expanded=True)
    declaration = applied['engagement']['seat_plan']['scan_review']
    sample = declaration['populations'][0]['review_point_ids']
    assert declaration['seed_sha256'] == scientific['sha256']
    assert points[-1] in sample
    assert sample == policy.scan_sample(points, 'standard', scientific['sha256'], [points[-1]])
    assert scan.membership_errors(applied) == []
    point_steps = scan.point_steps(applied)
    assert list(point_steps) == points and all(len(rows) == 1 for rows in point_steps.values())
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    launches, reviews = [], []
    for step in applied['steps']:
        point = scan.point_of(step)[0]
        for seat in step['seats']:
            if seat['kind'] == 'review':
                assert point is None or point in sample
                stage = 'review'
                if point:
                    reviews.append(point)
            else:
                stage = 'dispatch'
                if point:
                    launches.append(point)
            keys = ledger.materialise(store, stage, {'step': step['id'], 'seat': seat['seat'],
                                                       'role': seat['role'],
                                                       'point': point if step.get('points') else None,
                                                       'seat_kind': 'review' if stage == 'review' else 'worker',
                                                       'attempt': 1})
            satisfy(store, keys)
    assert sorted(launches) == sorted(points)
    assert set(reviews) == set(sample) and len(set(reviews)) < len(points)
    assert not [r for r in ledger.gate(store, 'execute→final_review')
                if r['reason'] in ('seat_missing', 'scan_review_invalid')]
    receipts = [{'point_id': p, 'governed': True, 'receipt_id': 'receipt:' + p} for p in launches]
    assert all(not v for v in policy.check_scan(points, receipts, sample, 'standard', scientific['sha256'],
                                                [points[-1]]).values())
    missing = policy.check_scan(points, receipts[:-1], sample, 'standard', scientific['sha256'], [points[-1]])
    assert missing['missing_receipts'] == [launches[-1]]


def test_declared_subset_closes_only_review_population(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    enter_grid(store, applied, sample)
    assert ledger.gate(store, 'execute→final_review') == []
    assert len(ledger_state.load(store, full=True).latest_seats()) == len(points) + len(sample) + 1
    satisfy(store, ledger.materialise(store, 'review', {'step': 'final_review', 'seat': 'skeptical-verifier',
                                                        'attempt': 1}))
    ledger.materialise(store, 'deliver', {'artifacts': []})
    assert ledger.gate(store, 'deliver[accepted]') == []


@pytest.mark.parametrize('damage', ['seed', 'population', 'sample', 'anomaly', 'digest', 'missing'])
def test_changed_declaration_blocks_acceptance(monkeypatch, tmp_path, damage):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    changed = deepcopy(applied)
    declaration = changed['engagement']['seat_plan']['scan_review']
    if damage == 'seed':
        declaration['seed_sha256'] = digest('other-plan')
    elif damage == 'population':
        declaration['populations'][0]['point_ids'].pop()
    elif damage == 'sample':
        declaration['populations'][0]['review_point_ids'] = []
    elif damage == 'anomaly':
        declaration['populations'][0]['anomalies'] = []
    elif damage == 'missing':
        changed['engagement']['seat_plan'].pop('scan_review')
    else:
        changed['engagement']['applied_sha256'] = '0' * 64
    if damage != 'digest':
        roster = changed['engagement']['seat_plan']
        roster['sha256'] = digest({k: v for k, v in roster.items() if k != 'sha256'})
        changed['engagement']['seat_plan_sha256'] = roster['sha256']
        changed['engagement'].pop('applied_sha256')
        changed['engagement']['applied_sha256'] = digest(changed)
    store = scan_store(monkeypatch, tmp_path, scientific, changed)
    enter_grid(store, changed, sample)
    assert any(r['reason'] == 'scan_review_invalid' for r in ledger.gate(store, 'deliver[accepted]'))


def test_missing_review_and_producer_receipt_stay_open(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    omitted = next(p for p in points if p not in sample)
    enter_grid(store, applied, sample[1:], omit=omitted)
    holes = ledger.gate(store, 'execute→final_review')
    assert any(r['reason'] == 'seat_missing' and sample[0] in r['entry'] for r in holes)
    assert any(r['reason'] == 'seat_missing' and omitted in r['entry'] for r in holes)


def test_every_point_instruction_rows_are_not_discharged_by_review_sample(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied, every_point=True)
    enter_grid(store, applied, sample)
    current = ledger_state.load(store, full=True)
    satisfy(store, [key for key in ledger.pending(store)
                    if key.startswith('ROLE-checker-every-point@')
                    and current.instances[key].scope.get('point') in sample])
    holes = ledger.gate(store, 'execute→final_review')
    assert len([r for r in holes if r['id'] == 'ROLE-checker-every-point']) == len(points) - len(sample)


def test_sink_shows_sample_and_total_population(monkeypatch):
    _, applied, points = applied_scan(monkeypatch)
    findings = checks.Findings()
    checks._engagement(findings, {'plan': {'plan': applied}, 'engagement': {
        'available': True, 'labels': [], 'envelope_status': 'ok', 'accepted_allowed': True}})
    sample = applied['engagement']['seat_plan']['scan_review']['populations'][0]['review_point_ids']
    assert any(label['label'] == 'SCAN REVIEW POPULATION' and
               f'{len(sample)} of {len(points)}' in label['text'] for label in findings.labels)


def test_other_seed_cannot_substitute_its_reviews(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    required = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    other = policy.scan_sample(points, 'standard', digest('other-seed'), points[-1:])
    assert set(required) != set(other)
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    enter_grid(store, applied, other)
    rows = ledger.gate(store, 'deliver[accepted]')
    assert any(r['reason'] == 'review_point_undeclared' for r in rows)
    assert any(r['reason'] == 'seat_missing' for r in rows)


def test_scan_operation_requests_keep_every_point_once(monkeypatch):
    _, applied, points = applied_scan(monkeypatch, expanded=True)
    requests = [execution.request(step, {'plan': applied})
                for step in applied['steps'] if scan.point_of(step)[0] is not None]
    assert sorted(r['point'] for r in requests) == sorted(points)
    assert all(r['plan_sha256'] == applied['sha256'] for r in requests)


def test_blob_pins_bind_declared_review_population(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied, blobs=True)
    enter_grid(store, applied, sample)
    assert ledger.gate(store, 'execute→final_review') == []


def test_population_must_be_declared_before_point_dispatch(monkeypatch, tmp_path):
    scientific, applied, points = applied_scan(monkeypatch)
    sample = policy.scan_sample(points, 'standard', scientific['sha256'], points[-1:])
    store = scan_store(monkeypatch, tmp_path, scientific, applied)
    pin = store.scan('plan')[0]['record']
    store.rewrite([e for e in store.entries() if e['kind'] != 'plan'])
    enter_grid(store, applied, sample)
    store.append('plan', pin)
    assert any(r['reason'] == 'scan_review_invalid' for r in ledger.gate(store, 'deliver[accepted]'))
