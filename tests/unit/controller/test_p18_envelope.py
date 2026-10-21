"""Inert per-attempt engagement accounting and exact hard-floor controls."""
from copy import deepcopy
from pathlib import Path
import importlib.util

import pytest

from ravel.controller.engagement.envelope import evaluate, project, budget_projection
from ravel.controller.engagement.records import data
from ravel.controller.engagement import envelope
from ravel.controller.engagement.records import EngagementRefused, TIERS, digest


def complete():
    dispatches, observations, deliveries = [], [], []
    for i in range(4):
        base = {'node_id': f'node-{i}', 'step_id': f's{i}', 'seat': 'reviewer', 'attempt': 1}
        dispatches.append({**base, 'packet_tokens': 100, 'packet_sha256': str(i) * 64, 'purpose': 'review'})
        observations.append({**base, 'session_id': f'session-{i}', 'status': 'completed',
                             'usage': {'reported': True, 'turns': 2, 'input_tokens': 100,
                                       'output_tokens': 10, 'cost_usd': .01}})
        deliveries.append({**base, 'session': f'session-{i}', 'packet_tokens': 100, 'packet_sha256': str(i) * 64})
    expected = {'status': 'ready', 'floor': {'sessions': 4},
                'low': {'sessions': 4, 'calls': 4, 'input_tokens': 320, 'output_tokens': 0, 'cost_usd': 0},
                'high': {'sessions': 8, 'calls': 20, 'input_tokens': 1000, 'output_tokens': 100, 'cost_usd': 1}}
    return dispatches, observations, deliveries, expected


def check(parts, **kwargs):
    d, o, i, e = parts
    return evaluate(d, o, i, expected=e, **kwargs)


def test_EG07_EG08_envelope_floor_complete():
    result = check(complete(), broker={'requests': 8, 'tokens': 440})
    assert result['status'] == 'ok'
    assert result['accepted_allowed'] and not result['hold']
    assert all(f['status'] == 'ok' for f in result['floors'].values())


@pytest.mark.parametrize('floor,mutation', [
    ('H1', 'missing'), ('H2', 'zero'), ('H2', 'below_packet'), ('H3', 'zero_calls'),
    ('H3', 'producer_one_call'), ('H4', 'concentrated'), ('H5', 'broker_surplus'),
])
def test_EG08_EG09_envelope_floor(floor, mutation):
    parts = complete()
    d, o, _, _ = parts
    broker = None
    if mutation == 'missing': o.pop()
    if mutation == 'zero': o[0]['usage']['input_tokens'] = 0
    if mutation == 'below_packet': o[0]['usage']['input_tokens'] = 79
    if mutation == 'zero_calls': o[0]['usage']['turns'] = 0
    if mutation == 'producer_one_call':
        d[0]['purpose'] = 'producer'
        o[0]['usage']['turns'] = 1
    if mutation == 'concentrated': o[0]['usage']['turns'] = 54
    if mutation == 'broker_surplus': broker = {'requests': 9}
    result = check(parts, broker=broker)
    assert result['status'] == 'below_floor'
    assert any(row['floor'] == floor and row['seat'] for row in result['failures'])
    assert result['hold'] and not result['accepted_allowed']
    assert 'ENGAGEMENT BELOW FLOOR' in result['labels']


def test_EG07_unknown_is_not_zero_or_observed():
    parts = complete()
    parts[1][0]['usage']['reported'] = False
    result = check(parts)
    assert result['observed']['sessions'] == 3
    assert 'USAGE UNKNOWN' in result['labels']
    assert not result['accepted_allowed']
    # Wave ignores the full run's expected minimum, but still holds unknown transport evidence.
    wave = check(parts, stage='wave')
    assert wave['status'] == 'unknown' and wave['hold']


@pytest.mark.parametrize('gap', ['projection', 'cost'])
def test_EG07_EG08_statistical_unknowns_label_without_holding_a_wave(gap):
    parts = complete()
    if gap == 'projection':
        parts = parts[:3] + (None,)
    else:
        parts[1][0]['usage'].pop('cost_usd')
    wave = check(parts, stage='wave')
    assert wave['status'] == 'unknown' and not wave['hold']
    assert 'USAGE UNKNOWN' in wave['labels'] and wave['notify']
    delivery = check(parts)
    assert delivery['status'] == 'unknown' and not delivery['accepted_allowed']
    # A structural breach still holds the wave alongside the statistical gap.
    parts[1][0]['usage']['input_tokens'] = 0
    assert check(parts, stage='wave')['hold']


@pytest.mark.parametrize('mutation', ['missing_packet','packet_digest','duplicate_session','duplicate_dispatch','duplicate_observation','surplus_observation'])
def test_EG08_attempt_census_cannot_be_faked(mutation):
    parts = complete()
    d, o, i, _ = parts
    if mutation == 'missing_packet': i.pop()
    if mutation == 'packet_digest': i[0]['packet_sha256'] = 'x'
    if mutation == 'duplicate_session': o[1]['session_id'] = o[0]['session_id']
    if mutation == 'duplicate_dispatch': d.append(deepcopy(d[0]))
    if mutation == 'duplicate_observation': o.append(deepcopy(o[0]))
    if mutation == 'surplus_observation':
        extra=deepcopy(o[0]); extra['attempt']=2; o.append(extra)
    assert not check(parts)['accepted_allowed']


def test_EG09_raw_cache_is_not_double_counted_and_retries_are_transport_owned():
    parts=complete()
    parts[1][0]['usage']['raw']={'input_tokens': 10, 'cache_creation_input_tokens': 30, 'cache_read_input_tokens': 60}
    parts[1][0]['transport_retries']=1
    assert check(parts, broker={'requests':9})['status']=='ok'
    assert check(parts, broker={'requests':10, 'retries':1})['status']=='below_floor'
    parts[1][0]['usage']['input_tokens']=200
    assert not check(parts)['accepted_allowed']


def test_EG09_broker_token_reconciliation():
    assert check(complete(), broker={'requests':8,'tokens':444})['status']=='ok'
    result=check(complete(),broker={'requests':8,'tokens':445})
    assert result['status']=='below_floor'
    assert result['floors']['H5']['status']=='below_floor'


def test_EG10_thresholds_do_not_weaken_structural_gates():
    parts=complete()
    parts[3]['low']['calls']=17
    result=check(parts)
    assert result['status']=='far_below' and not result['hold']
    parts[3]['low']['calls']=16
    assert check(parts)['status']=='ok'  # strict threshold
    parts[3]['high']['calls']=5
    result=check(parts)
    assert result['status']=='above_ceiling' and result['notify']
    parts[1][0]['usage']['input_tokens']=0
    result=check(parts)
    assert result['status']=='below_floor'
    assert 'ENGAGEMENT ABOVE CEILING' in result['labels']


def test_EG10_projection_requests_authority_without_lowering():
    expected=complete()[3]
    result=budget_projection(expected, {'model_calls':19})
    assert result=={'class':'R3','action':'spend_above_ceiling','dimensions':['model_calls']}
    assert budget_projection(expected, {'model_calls':20}) is None
    assert budget_projection(None,{})['class']=='R3'


def test_projection_unconfigured_cost_is_unbounded_but_explicit_caps_still_hold():
    expected = complete()[3]
    assert budget_projection(expected, {'cost_usd': None, 'model_calls': 20}) is None
    assert budget_projection(expected, {'cost_usd': .5})['dimensions'] == ['cost_usd']
    assert budget_projection(expected, {'tokens': None})['dimensions'] == ['tokens']


def test_envelope_build_formula_and_bounds():
    calibration=data('calibration.json')
    sessions=[{'packet_tokens':100,'duty_units':2,'category':'review','conditional':False}]
    result=project(sessions,calibration)
    for metric in ('sessions','calls','input_tokens','output_tokens','cost_usd'):
        assert result['floor'][metric] <= result['low'][metric] <= result['central'][metric] <= result['high'][metric]
    # Independent arithmetic for low: W=6000+100+4*1500, R=4*6100+1500*5*4/2.
    assert result['low']['input_tokens']==12100+39400
    assert result['low']['output_tokens']==5*700+2*41+800
    assert result['high']['sessions']==3


@pytest.mark.parametrize('value', [None, True, -1, float('nan'), float('inf'), '100'])
def test_EG07_invalid_usage_is_unknown(value):
    parts=complete();parts[1][0]['usage']['input_tokens']=value
    assert not check(parts,stage='wave')['accepted_allowed']


def test_EG08_wave_does_not_compare_partial_run_to_full_low():
    parts=complete();parts[3]['low']['calls']=10000
    assert check(parts,stage='wave')['status']=='ok'


def test_EG08_transport_ok_final_producer_requires_two_calls():
    parts=complete();parts[0][0]['purpose']='producer'
    parts[1][0]['status']='ok';parts[1][0]['usage']['turns']=1
    assert check(parts)['floors']['H3']['status']=='below_floor'


def retried(status):
    """Attempt 1 ends without usage; attempt 2 of the same seat completes normally."""
    d, o, i, e = complete()
    first = {'node_id': 'node-0', 'step_id': 's0', 'seat': 'reviewer', 'attempt': 1}
    d[0] = {**first, 'packet_tokens': 100, 'packet_sha256': 'f' * 64, 'purpose': 'review'}
    o[0] = {**first, 'session_id': None, 'status': status, 'usage': {'reported': False, 'turns': None,
                                                                    'input_tokens': None, 'output_tokens': None}}
    i.pop(0)
    second = {**first, 'attempt': 2}
    d.append({**second, 'packet_tokens': 100, 'packet_sha256': 'e' * 64, 'purpose': 'review'})
    o.append({**second, 'session_id': 'session-retry', 'status': 'completed',
              'usage': {'reported': True, 'turns': 2, 'input_tokens': 100, 'output_tokens': 10, 'cost_usd': .01}})
    i.append({**second, 'session': 'session-retry', 'packet_tokens': 100, 'packet_sha256': 'e' * 64})
    return d, o, i, e


def test_EG07_refused_before_start_is_released_not_a_session():
    parts = retried('refused')
    for stage in ('wave', 'deliver'):
        result = check(parts, stage=stage)
        assert result['status'] == 'ok' and not result['hold'] and result['accepted_allowed']
        assert result['released'] == ['node-0:reviewer:1'] and result['observed']['sessions'] == 4
    # A refusal that still reports spend is an ordinary session and meets every floor.
    parts[1][0]['usage'] = {'reported': True, 'turns': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0}
    parts[1][0]['session_id'] = 'session-refused'
    assert check(parts, stage='wave')['status'] == 'below_floor'


@pytest.mark.parametrize('status', ['failed', 'voided', 'ambiguous'])
def test_EG07_EG08_unfinished_attempt_labels_without_holding_later_waves(status):
    parts = retried(status)
    wave = check(parts, stage='wave')
    assert wave['status'] == 'unknown' and not wave['hold'] and 'USAGE UNKNOWN' in wave['labels']
    delivery = check(parts)
    assert delivery['status'] == 'unknown' and not delivery['accepted_allowed']
    # A completed session without usage still holds the wave.
    parts[1][-1]['usage']['reported'] = False
    assert check(parts, stage='wave')['hold']


def test_EG08_unfinished_attempt_breach_blocks_acceptance_without_holding():
    parts = retried('failed')
    parts[1][0]['usage'] = {'reported': True, 'turns': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0}
    parts[1][0]['session_id'] = 'session-crashed'
    parts[2].append({'node_id': 'node-0', 'step_id': 's0', 'seat': 'reviewer', 'attempt': 1,
                     'session': 'session-crashed', 'packet_tokens': 100, 'packet_sha256': 'f' * 64})
    wave = check(parts, stage='wave')
    assert wave['status'] == 'below_floor' and not wave['hold']
    assert not check(parts)['accepted_allowed']
    # Reusing another session's identity is a census defect and holds whatever the attempt status.
    parts[1][0]['session_id'] = 'session-retry'
    assert check(parts, stage='wave')['hold']


@pytest.fixture
def default_projections(monkeypatch):
    routes = {}
    for name in ('route-a', 'route-b'):
        routes[name] = {}
        for index, tier in enumerate(TIERS, 1):
            high = {'sessions': index, 'calls': index + 1, 'input_tokens': index + 2,
                    'output_tokens': 1, 'cost_usd': 0}
            if name == 'route-b':
                high.update(sessions=index + 4, input_tokens=1)
            routes[name][tier] = {'status': 'ready', 'high': high,
                                  'reservations': {'model_calls': index + 5}}
    installed = {'routes': routes}
    monkeypatch.setattr(envelope, 'installed_projection', lambda: installed)
    return installed


@pytest.mark.parametrize('tier,expected', [
    ('lean', {'children': 2, 'model_calls': 8, 'tokens': 5}),
    ('standard', {'children': 3, 'model_calls': 9, 'tokens': 7}),
    ('full', {'children': 4, 'model_calls': 10, 'tokens': 8}),
])
def test_defaults_select_tier_round_margin_and_cover_reservations(default_projections, tier, expected):
    assert envelope.defaults('route-a', tier) == expected
    assert envelope.defaults({'id': 'route-a', 'tier': tier}) == expected
    assert envelope.defaults('route-a') == {'children': 4, 'model_calls': 10, 'tokens': 8}


def test_defaults_before_routing_take_dimension_wise_maximum(default_projections):
    assert envelope.defaults(None) == {'children': 9, 'model_calls': 10, 'tokens': 8}
    assert envelope.defaults(None, 'lean') == {'children': 7, 'model_calls': 8, 'tokens': 5}


@pytest.mark.parametrize('route,tier', [('absent', 'full'), ('route-a', 'absent')])
def test_defaults_unknown_route_or_tier_refuse(default_projections, route, tier):
    with pytest.raises(EngagementRefused):
        envelope.defaults(route, tier)


@pytest.mark.parametrize('mutation', ['status', 'missing_high', 'negative', 'boolean', 'nonfinite'])
def test_defaults_invalid_entry_refuses(default_projections, mutation):
    entry = default_projections['routes']['route-a']['full']
    if mutation == 'status':
        entry['status'] = 'unavailable'
    elif mutation == 'missing_high':
        entry.pop('high')
    else:
        entry['high']['calls'] = {'negative': -1, 'boolean': True, 'nonfinite': float('inf')}[mutation]
    with pytest.raises(EngagementRefused):
        envelope.defaults('route-a')


def installed_data_override(monkeypatch):
    """Use installed bytes and retain their complete source inventory."""
    installed = deepcopy(data('envelopes.json'))
    original_data = envelope.data
    monkeypatch.setattr(envelope, 'data', lambda name: installed if name == 'envelopes.json' else original_data(name))
    return installed, original_data


def test_installed_projection_detects_content_drift(monkeypatch):
    installed, _ = installed_data_override(monkeypatch)
    installed['reason'] = 'changed after sealing'
    with pytest.raises(EngagementRefused, match='digest mismatch'):
        envelope.installed_projection()


@pytest.mark.parametrize('error', [FileNotFoundError('missing'), ValueError('invalid document')])
def test_installed_projection_missing_or_malformed_input_refuses(monkeypatch, error):
    def unavailable(name):
        raise error
    monkeypatch.setattr(envelope, 'data', unavailable)
    with pytest.raises(EngagementRefused, match='unavailable'):
        envelope.installed_projection()


@pytest.mark.parametrize('filename,message', [
    ('calibration.json', 'calibration stale'), ('policy.json', 'policy stale'),
])
def test_installed_projection_detects_input_drift(monkeypatch, filename, message):
    installed, original_data = installed_data_override(monkeypatch)
    changed = deepcopy(original_data(filename))
    if filename == 'calibration.json':
        changed['high_retries'] += 1
    else:
        changed['sha256'] = '0' * 64
    monkeypatch.setattr(envelope, 'data', lambda name: (
        installed if name == 'envelopes.json' else changed if name == filename else original_data(name)))
    with pytest.raises(EngagementRefused, match=message):
        envelope.installed_projection()


@pytest.mark.parametrize('mutation,message', [
    ('source', 'source stale'), ('routes', 'route inventory stale'),
])
def test_installed_projection_detects_source_inventory_drift(monkeypatch, mutation, message):
    installed, _ = installed_data_override(monkeypatch)
    if mutation == 'source':
        key = next(key for key in installed['source_pins'] if key not in ('builder', 'routes', 'capabilities'))
        installed['source_pins'][key] = '0' * 64
    else:
        installed['source_pins']['routes']['absent.json'] = '0' * 64
    installed['sha256'] = digest({k: v for k, v in installed.items() if k != 'sha256'})
    with pytest.raises(EngagementRefused, match=message):
        envelope.installed_projection()


def test_builder_reserves_conditional_calls_producer_stops_and_effect_children():
    root = Path(__file__).parents[3]

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    builder = load('p18_envelope_builder', root / 'scripts/maintenance/build_engagement_envelopes.py')
    fakes = load('p18_envelope_fakes', root / 'tests/fixtures/engagement/fakes.py')
    plan = fakes.fictional_plan()
    plan['id'] = plan['route']['id']
    cards = fakes.cards()
    cards['generator']['stop'] = {'max_turns': 103}
    cards['trap-auditor']['stop'] = {'max_turns': 107}
    cards['generator']['knowledge']['consult'] = [{'when': 'failure', 'role': 'trap-auditor'}]
    plan['steps'][0]['budget'] = {'tokens': 2000000}
    plan['steps'].extend({'id': kind, 'kind': kind} for kind in ('operate', 'acquire', 'subgraph'))
    calibration = data('calibration.json')
    arguments = dict(cards=cards, instructions=fakes.FakeInstructions,
                     policy=fakes.policy_for(plan, cards), calibration=calibration, source_pins={})
    first = builder.build([plan], **arguments)
    assert builder.encode(first) == builder.encode(builder.build([plan], **arguments))
    for tier in TIERS:
        sessions = first['packets'][plan['id']][tier]
        producers = [s for s in sessions if s['category'] == 'producer']
        conditional = [s for s in sessions if s['category'] == 'consult']
        assert producers and all(s['reserved_calls'] == 103 for s in producers)
        assert any(s['reserved_tokens'] == 2000000 for s in producers)
        assert conditional and all(s['conditional'] and s['reserved_calls'] == 107 for s in conditional)
        retries = calibration['high_retries']
        entry = first['routes'][plan['id']][tier]
        reservations = entry['reservations']
        assert reservations['children'] == len(sessions) + 3 + retries
        assert reservations['model_calls'] == sum(s.get('reserved_calls', 0) for s in sessions) + retries * 107
        assert reservations['tokens'] == (sum(s.get('reserved_tokens', 0) for s in sessions)
                                           + retries * max(s.get('reserved_tokens', 0) for s in sessions))
        assert entry['high']['sessions'] >= reservations['children']
        assert entry['high']['calls'] >= reservations['model_calls']
        assert entry['high']['input_tokens'] + entry['high']['output_tokens'] >= reservations['tokens']


class _Store:
    """A journal with the RunStore scan/append surface; nothing else."""

    def __init__(self):
        self.journal = []

    def append(self, kind, record):
        self.journal.append((kind, {'id': f'r{len(self.journal)}', 'record': deepcopy(record)}))
        return self.journal[-1][1]['id']

    def scan(self, kind):
        return [deepcopy(row) for found, row in self.journal if found == kind]


def _plan_built_run(source='plan'):
    """A decided run whose envelope is its own plan's projection (a judgment plan), with complete usage."""
    from ravel.controller.engagement.records import DECISION, append
    dispatches, observations, deliveries, expected = complete()
    store = _Store()
    for kind, found in (('step-dispatch', dispatches), ('step-observation', observations),
                        ('instruction-delivery', deliveries)):
        for row in found:
            store.append(kind, {**row, 'kind': 'instruction-delivery-session'} if kind == 'instruction-delivery' else row)
    plan = {'id': 'plan', 'route': {'id': 'judgment', 'spec_sha256': None}, 'steps': []}
    plan['sha256'] = digest(plan)
    entry = {**deepcopy(expected), 'source': source, 'plan_sha256': plan['sha256']}
    decision = append(store, DECISION, {
        'policy_id': 'p', 'policy_version': 1, 'policy_sha256': '0' * 64, 'facts': {}, 'minimum_tiers': {},
        'computed_tier': 'full', 'tier': 'full', 'reasons': [], 'seat_plan': {}, 'seat_plan_sha256': '1' * 64,
        'correction_bound': 1, 'packet_scope': {}, 'envelopes': {t: deepcopy(entry) for t in TIERS},
        'projected_envelope': deepcopy(entry), 'budget_authority': None, 'operator_minimum': None,
        'physicist_raise_ids': [], 'authority_record_ids': [], 'scientific_plan_sha256': plan['sha256'],
        'scientific_plan': plan})
    return store, decision


def _approve(store, decision, **changes):
    pins = {'plan_sha256': decision['scientific_plan_sha256'],
            'engagement_envelope_sha256': envelope.envelope_binding(decision)}
    record = {'kind': 'approve_plan', 'decision': 'approve', 'authorizes_effects': True, 'subject': {'pins': pins}}
    for key, value in changes.items():
        if key in pins:
            pins[key] = value
        else:
            record[key] = value
    store.append('authority', record)


def test_EG08_judgment_plan_envelope_counts_only_when_its_approval_binds_it():
    broker = {'requests': 8, 'tokens': 440}
    store, decision = _plan_built_run()
    # Without an approval binding the plan's own projection, the plan has no envelope: usage stays unknown.
    unbound = envelope.check_envelope(store, 'deliver', broker=broker)
    assert unbound['status'] == 'unknown' and not unbound['accepted_allowed']
    assert {'floor': 'projection', 'seat': 'run', 'reason': 'envelope unavailable', 'holds': False} in unbound['unknown']
    # Approvals that do not authorize effects, approve another plan or bind another envelope bind nothing.
    for changes in ({'authorizes_effects': False}, {'plan_sha256': 'f' * 64},
                    {'engagement_envelope_sha256': 'e' * 64}, {'engagement_envelope_sha256': None},
                    {'kind': 'final'}):
        _approve(store, decision, **changes)
        refused = envelope.check_envelope(store, 'deliver', broker=broker)
        assert refused['status'] == 'unknown' and not refused['accepted_allowed'], changes
    # The plan approval that binds it: the deliver-stage check uses the plan's envelope.
    _approve(store, decision)
    bound = envelope.check_envelope(store, 'deliver', broker=broker)
    assert bound['status'] == 'ok' and bound['accepted_allowed'] and bound['unknown'] == [], bound
    assert bound['expected']['plan_sha256'] == decision['scientific_plan_sha256']


def test_EG08_installed_route_envelope_needs_no_plan_binding():
    store, decision = _plan_built_run(source=None)
    assert envelope.envelope_binding(decision) is None
    found = envelope.check_envelope(store, 'deliver', broker={'requests': 8, 'tokens': 440})
    assert found['status'] == 'ok' and found['accepted_allowed'], found


def test_EG08_plan_projection_uses_the_route_builder_and_refuses_stale_inputs(monkeypatch):
    from ravel.controller.engagement import builder
    calls = []
    def build_tiers(plan, spec, tiers, **arguments):
        calls.append((plan['route'], tuple(tiers), sorted(arguments)))
        return {t: {'status': 'ready', 'tier': t} for t in tiers}, {}
    monkeypatch.setattr(builder, 'build_tiers', build_tiers)
    monkeypatch.setattr(builder, 'installed_projection', lambda: {'status': 'ready'})
    plan = {'id': 'p', 'route': {'id': 'judgment', 'spec_sha256': None}, 'steps': [], 'deliverables': [{}]}
    plan['sha256'] = digest(plan)
    built = builder.plan_projection(plan)
    assert calls == [({'id': 'judgment', 'spec_sha256': None}, TIERS,
                      ['calibration', 'cards', 'instructions', 'policy'])]
    assert set(built) == set(TIERS) and all(e['source'] == 'plan' and e['plan_sha256'] == plan['sha256']
                                            for e in built.values())
    def stale():
        raise EngagementRefused('engagement calibration stale; rebuild before deriving budgets')
    monkeypatch.setattr(builder, 'installed_projection', stale)
    with pytest.raises(EngagementRefused, match='stale'):
        builder.plan_projection(plan)
    with pytest.raises(EngagementRefused):
        builder.plan_projection({k: v for k, v in plan.items() if k != 'sha256'})
