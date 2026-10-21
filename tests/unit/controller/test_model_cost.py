"""Measured accounting uses only the reconciled provider census, with fictional prices."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ravel.controller import entry, model_cost, testing
from ravel.controller.engagement import recalibrate
from ravel.controller.sink import evidence
from ravel.controller.store import RunStore


TOKENS = ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens', 'output_tokens')
CARDS = {
    'maker': {'family': 'production', 'model': {'tier': 'agent'}},
    'checker': {'family': 'review', 'model': {'tier': 'judgment'}},
    'advisor': {'family': 'consult', 'model': {'tier': 'agent'}},
    'decision': {'family': 'rdj', 'model': {'tier': 'judgment'}},
}
PRICES = {'input': 2, 'cache_write': 3, 'cache_read': 1, 'output': 8}


def price(usage, model):
    status = 'model_unknown' if model == 'unknown-model' or model is None else 'priced'
    valid = all(type(usage.get(k)) is int and usage[k] >= 0 for k in TOKENS)
    if not valid:
        status = 'usage_incomplete'
    cost = sum(usage[k] * PRICES[p] for k, p in zip(TOKENS, PRICES)) / 1e6 if status == 'priced' else None
    return {'status': status, 'cost_usd': cost, 'model': model,
            'prices_per_million': dict(PRICES) if status == 'priced' else None,
            'price_basis': 'fictional accounting prices'}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cost, 'model_catalogue', SimpleNamespace(price=price))
    monkeypatch.setattr(model_cost.role_registry, 'load', lambda role: deepcopy(CARDS[role]))
    with testing.seams(True):
        return RunStore.create(tmp_path / 'artifacts', root=tmp_path / 'stores', run_id='run-cost-fixture')


def add_session(store, *, index=0, role='maker', purpose='producer', requests=2, output=20,
                model='observed-model', dispatch=True, tier=None, attempt=1, seat=None):
    node = f'node-{index}'
    if dispatch:
        selection = {'transport_id': 'fixture-transport', 'model': 'requested-model',
                     'family': 'fixture-family', 'effort': 'medium'}
        if tier:
            selection['tier'] = tier
        store.append('step-dispatch', {'node_id': node, 'attempt': attempt,
                     'seat': seat if seat is not None else f'seat:{role}:1', 'step_id': f'step-{index}',
                     'purpose': purpose, 'selection': selection, 'card_sha256': 'a' * 64})
        store.append('step-observation', {'node_id': node, 'attempt': attempt,
                     'model': {'observed': model}, 'usage': {'output_tokens': 999999}})
    return {'status': 'reported', 'node_id': node, 'attempt': attempt, 'session_id': f'session-{index}',
            'agent': 'fixture-agent', 'requests': requests,
            'usage': dict(zip(TOKENS, (100, 30, 10, output)))}


def census(store, rows, status='reported', problems=()):
    return store.append('provider-counter', {'kind': 'provider-counter', 'status': status,
                                            'sessions': rows, 'problems': list(problems)})


def test_join_groups_and_orphan(store):
    rows = [add_session(store), add_session(store, index=1, role='checker', purpose='review',
            model='second-model', tier='agent'), add_session(store, index=2, dispatch=False)]
    census(store, rows)
    joined = model_cost.sessions(store)
    first = joined[0]
    assert {key: first[key] for key in ('node_id', 'attempt', 'seat', 'role', 'card_tier', 'selected_tier',
            'purpose', 'transport', 'model_requested', 'model_observed', 'family', 'effort', 'requests')} == {
        'node_id': 'node-0', 'attempt': 1, 'seat': 'seat:maker:1', 'role': 'maker', 'card_tier': 'agent',
        'selected_tier': 'agent', 'purpose': 'producer', 'transport': 'fixture-transport',
        'model_requested': 'requested-model', 'model_observed': 'observed-model',
        'family': 'fixture-family', 'effort': 'medium', 'requests': 2}
    assert first['usage'] == rows[0]['usage']
    assert first['price']['cost_usd'] == pytest.approx(price(rows[0]['usage'], 'observed-model')['cost_usd'])
    assert joined[1]['card_tier'] == 'judgment' and joined[1]['selected_tier'] == 'agent'
    assert joined[2]['role'] is None and joined[2]['reason'] == 'dispatch_missing'
    result = model_cost.summary(store)
    assert result['kind'] == 'model-cost' and result['schema_version'] == 1
    assert result['status'] == 'partial' and result['counter_status'] == 'reported'
    assert result['by_role']['maker']['tokens'] == rows[0]['usage']
    assert result['by_tier']['agent']['sessions'] == 2
    assert result['by_tier']['agent']['tokens'] == {k: rows[0]['usage'][k] * 2 for k in TOKENS}
    assert result['by_model']['second-model']['tokens'] == rows[1]['usage']
    assert result['total']['requests'] == 6 and result['total']['sessions'] == 3
    assert result['total']['cost_usd'] is None
    assert result['total']['cost_usd_priced_part'] == pytest.approx(2 * first['price']['cost_usd'])


def test_unknown_model_is_never_a_partial_total(store):
    rows = [add_session(store), add_session(store, index=1, role='checker', purpose='review', model='unknown-model')]
    census(store, rows)
    result = model_cost.summary(store)
    assert result['status'] == 'partial' and result['unpriced_models'] == ['unknown-model']
    assert result['by_role']['checker']['unpriced'] == 1
    assert result['by_tier']['judgment']['cost_usd'] is None
    assert result['total']['cost_usd'] is None and result['total']['unpriced'] == 1
    assert result['by_role']['maker']['cost_usd'] == result['total']['cost_usd_priced_part']


def test_status_rules_counter_problems_and_latest_snapshot(store, monkeypatch):
    assert model_cost.summary(store)['status'] == 'unknown'
    census(store, [])
    assert model_cost.summary(store)['status'] == 'measured'
    row = add_session(store)
    census(store, [row])
    assert model_cost.summary(store)['status'] == 'measured'
    problem = {'reason': 'provider_receipt_missing', 'node_id': 'other-node', 'attempt': 1}
    census(store, [row], 'unknown', [problem])
    result = model_cost.summary(store)
    assert result['status'] == 'partial' and problem in result['problems']
    assert result['total']['cost_usd'] is None and result['total']['requests'] is None
    assert result['total']['requests_reported_part'] == row['requests']
    assert len(model_cost.sessions(store)) == 1
    census(store, [], 'unknown', [problem])
    assert model_cost.summary(store)['status'] == 'unknown'
    census(store, [row])
    monkeypatch.setattr(model_cost, 'model_catalogue', None)
    assert model_cost.sessions(store)[0]['price']['status'] == 'catalogue_unavailable'
    assert model_cost.summary(store)['total']['cost_usd'] is None


def test_unobserved_model_stays_unpriced_attempt_join_and_idempotent_record(store):
    row = add_session(store, attempt=2)
    store.append('step-observation', {'node_id': row['node_id'], 'attempt': 2, 'model': {}})
    store.append('step-observation', {'node_id': row['node_id'], 'attempt': 1, 'model': {'observed': 'wrong-model'}})
    census(store, [row])
    assert model_cost.sessions(store)[0]['model_observed'] is None
    assert model_cost.sessions(store)[0]['price']['model'] is None
    assert model_cost.sessions(store)[0]['price']['cost_usd'] is None
    assert model_cost.summary(store)['by_model']['unknown']['unpriced'] == 1
    model_cost.record(store)
    model_cost.record(store)
    assert len(store.scan('model-cost')) == 1
    changed = deepcopy(row)
    changed['requests'] += 1
    census(store, [changed])
    model_cost.record(store)
    assert len(store.scan('model-cost')) == 2


def test_mixed_model_counters_keep_total_price_unknown(store):
    row = add_session(store)
    row['models'] = ['requested-model', 'another-model']
    census(store, [row])
    result = model_cost.summary(store)
    assert result['total']['cost_usd'] is None
    assert any(p['reason'] == 'provider_model_attribution_incomplete' for p in result['problems'])


def test_missing_counter_never_uses_observation_usage_and_role_fallback(store):
    row = add_session(store, seat='producer')
    result = model_cost.summary(store)
    assert result['total']['cost_usd'] is None and result['total']['requests'] is None
    assert result['total']['tokens'] == dict.fromkeys(TOKENS)
    assert model_cost.sessions(store) == []
    census(store, [row])
    assert model_cost.sessions(store)[0]['role'] == 'producer'


def test_incomplete_usage_remains_unknown(store):
    row = add_session(store)
    del row['usage']['cache_read_input_tokens']
    census(store, [row])
    joined = model_cost.sessions(store)[0]
    assert joined['usage']['cache_read_input_tokens'] is None
    assert joined['price']['status'] == 'usage_incomplete'
    assert model_cost.summary(store)['total']['tokens']['cache_read_input_tokens'] is None


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None,
                                           p.stat().st_mode, p.stat().st_mtime_ns)
            for p in root.rglob('*')}


def test_receipt_evidence_and_status_are_read_only(store):
    census(store, [add_session(store)])
    before, head = snapshot(store.store_root), store.head()
    assert evidence.gather(store)['model_cost'] == model_cost.summary(store)
    assert entry.status(store.run_id, root=store.store_root)['model_cost'] == model_cost.summary(store)
    assert store.head() == head and snapshot(store.store_root) == before


def test_views_report_cost_errors_without_writing(store, monkeypatch):
    def broken(_store):
        raise RuntimeError('fictional failure')
    monkeypatch.setattr(model_cost, 'summary', broken)
    before = snapshot(store.store_root)
    expected = {'status': 'unknown', 'error': 'RuntimeError'}
    assert evidence.gather(store)['model_cost'] == expected
    assert entry.status(store.run_id, root=store.store_root)['model_cost'] == expected
    assert snapshot(store.store_root) == before


def test_recalibration_percentiles_insufficient_and_apply(store):
    installed = recalibrate.installed_calibration()
    rows = [add_session(store, index=i, requests=n, output=n * n) for i, n in enumerate((1, 2, 3, 4, 10))]
    rows.append(add_session(store, index=5, role='checker', purpose='review', requests=50, output=5000))
    census(store, rows)
    measurement = recalibrate.measure([store])
    assert measurement['sessions'] == 6 and measurement['runs'] == 1
    # Linear interpolation at (N - 1) * p followed by ceil.
    assert measurement['calls']['producer'] == {'low': 2, 'central': 3, 'high': 6}
    assert measurement['output_per_call']['producer'] == {'low': 2, 'central': 3, 'high': 6}
    assert measurement['calls']['review'] == installed['calls']['review']
    assert 'review' in measurement['insufficient'] and 'producer' not in measurement['insufficient']
    assert measurement['prices_per_million'] == {'uncached': 2, 'write': 3, 'read': 1, 'output': 8}
    assert measurement['basis'].startswith('measured from 6 sessions of 1 runs; digest ')
    assert len(measurement['basis'].rsplit(' ', 1)[1]) == 64
    original = deepcopy(installed)
    calibration = recalibrate.apply(installed, measurement)
    assert installed == original and calibration['ack_tokens_per_unit'] == installed['ack_tokens_per_unit']
    assert calibration['calls'] == measurement['calls']
    assert calibration['parameters']['central']['output_per_call'] == {
        k: v['central'] for k, v in measurement['output_per_call'].items()}
    assert calibration['parameters']['high']['S'] == installed['parameters']['high']['S']
    assert calibration['price_basis'].startswith('measured ')
    measurement.pop('price_basis')
    assert recalibrate.apply(installed, measurement)['price_basis'].startswith('measured ')


def test_applied_category_outputs_are_consumed_by_projection(store):
    from ravel.controller.engagement.envelope import project
    rows = [add_session(store, index=i, requests=n, output=n * n) for i, n in enumerate((1, 2, 3, 4, 10))]
    census(store, rows)
    calibration = recalibrate.apply(recalibrate.installed_calibration(), recalibrate.measure([store]))
    session = {'category': 'producer', 'packet_tokens': 100, 'duty_units': 0}
    result = project([session], calibration)
    assert result['central']['output_tokens'] == 3 * 3 + calibration['parameters']['central']['record_tokens']


def test_measure_digest_and_run_population_are_stable(store):
    census(store, [add_session(store)])
    first = recalibrate.measure([store])
    assert recalibrate.measure([store, store]) == first
    assert first['sessions'] == 1 and first['runs'] == 1


@pytest.mark.parametrize('role,purpose,seat,expected', [
    ('maker', 'producer', None, 'producer'), ('checker', 'review', None, 'review'),
    ('advisor', 'producer', None, 'consult'), ('decision', 'review', None, 'checkin'),
    ('checker', 'producer', None, 'judgment'),
    ('checker', 'review', 'checkin:checkpoint:checker', 'checkin'),
])
def test_category_mapping(store, role, purpose, seat, expected):
    row = add_session(store, role=role, purpose=purpose, seat=seat)
    census(store, [row])
    assert recalibrate.category(model_cost.sessions(store)[0]) == expected


def test_weighted_prices_and_unpriced_preserve_reference(store):
    def varied(usage, model):
        result = price(usage, model)
        if model == 'second-model':
            result['prices_per_million'] = {k: 2 * v for k, v in PRICES.items()}
            result['cost_usd'] *= 2
        return result
    model_cost.model_catalogue.price = varied
    first = add_session(store)
    second = add_session(store, index=1, model='second-model')
    second['usage'] = {k: v * 3 for k, v in first['usage'].items()}
    census(store, [first, second])
    measured = recalibrate.measure([store])
    assert measured['prices_per_million'] == {'uncached': 3.5, 'write': 5.25, 'read': 1.75, 'output': 14}
    second['usage']['output_tokens'] = 0
    second['requests'] = 0
    census(store, [first, second])
    assert recalibrate.measure([store])['calls'] == recalibrate.installed_calibration()['calls']
    third = add_session(store, index=2, model='unknown-model')
    census(store, [first, second, third])
    assert recalibrate.measure([store])['prices_per_million'] == recalibrate.installed_calibration()['prices_per_million']


def test_recalibration_check_codes_and_source_only_write(store, tmp_path, monkeypatch, capsys):
    census(store, [add_session(store)])
    source = tmp_path / 'checkout'
    target = source / 'src/ravel/data/controller/engagement/calibration.json'
    target.parent.mkdir(parents=True)
    (source / 'pyproject.toml').write_text('[project]\nname = "fixture"\n')
    (source / 'scripts/maintenance').mkdir(parents=True)
    (source / 'scripts/maintenance/build_engagement_envelopes.py').write_text('')
    target.write_text(json.dumps(recalibrate.installed_calibration()))
    monkeypatch.setattr(recalibrate, 'calibration_path', lambda: target)
    monkeypatch.setattr(recalibrate, 'store_root', lambda: store.store_root)
    assert recalibrate.main(['--runs', store.run_id, '--check']) == 1
    assert 'measurement' in capsys.readouterr().out
    assert recalibrate.main(['--runs', store.run_id, '--write']) == 0
    assert 'build_engagement_envelopes.py' in capsys.readouterr().out
    assert recalibrate.main(['--runs', store.run_id, '--check']) == 0
    packaged = tmp_path / 'site-packages/ravel/data/controller/engagement/calibration.json'
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes(target.read_bytes())
    monkeypatch.setattr(recalibrate, 'calibration_path', lambda: packaged)
    assert recalibrate.main(['--runs', store.run_id, '--write']) != 0
    assert 'source checkout' in capsys.readouterr().err
    before = snapshot(store.store_root)
    assert recalibrate.main(['--runs', 'run-absent', '--check']) != 0
    assert snapshot(store.store_root) == before
