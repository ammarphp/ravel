"""Usage-aware startup recommendations preserve effective card requirements."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from test_models_setup import operator_home  # noqa: F401
from ravel.paths import package_data_path
from ravel.workflow import model_catalogue as mc, transport_registry as tr

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'model-state'))
    documents = [json.loads((package_data_path('transports') / (name + '.json')).read_text())
                 for name in ('claude-cli-worker', 'codex-cli-worker')]
    catalogue = mc.load(builtin_only=True)
    template = deepcopy(catalogue['models'][0])
    catalogue['models'] = []
    prefs = {'schema_version': 1, 'kind': 'agent-preferences',
             'transport_preference': [d['id'] for d in documents],
             'tier_models': {t: {} for t in tr.TIERS}}
    for document, family, prefix, price in zip(documents, ('anthropic', 'openai'), ('claude', 'gpt'), (8, 2)):
        model = {**deepcopy(template), 'id': prefix + '-fixture-capable', 'family': family,
                 'tiers': list(tr.TIERS), 'status': 'current',
                 'prices_per_million': {k: price for k in mc.PRICE_KEYS}}
        catalogue['models'].append(model)
        for tier in tr.TIERS:
            prefs['tier_models'][tier][document['id']] = model['id']
    monkeypatch.setattr(mc, 'load', lambda **kwargs: deepcopy(catalogue))
    monkeypatch.setattr('ravel.controller.step.seats.wired_transports', lambda: {
        'wired': prefs['transport_preference'], 'excluded': [], 'kinds': ['cli-worker']})
    return documents, prefs, catalogue


def context(prefs, *, remaining=150, reset='2030-01-01T01:00:00Z', plan='included'):
    first, second = prefs['transport_preference']
    return {'schema_version': 1, 'kind': 'model-usage-context',
            'observed_utc': '2030-01-01T00:00:00Z', 'valid_until_utc': '2030-01-01T00:30:00Z',
            'expected_run_seconds': 3600,
            'accounts': [
                {'transports': [first], 'plan': plan,
                 'windows': [{'unit': 'tokens', 'remaining': remaining, 'resets_utc': reset}]},
                {'transports': [second], 'plan': 'metered',
                 'windows': [{'unit': 'tokens', 'remaining': 10000, 'resets_utc': reset}]}]}


def history(*, agent=200):
    return {'schema_version': 1, 'kind': 'model-cost', 'status': 'measured',
            'counter_status': 'reported', 'problems': [],
            'by_tier': {tier: {'requests': 1, 'tokens': dict(zip(mc._USAGE_KEYS, (amount, 0, 0, 0)))}
                        for tier, amount in [('judgment', 100), ('agent', agent), ('cheap', 10)]}}


def selected(prefs, tier):
    return next((t, prefs['tier_models'][tier][t]) for t in prefs['transport_preference']
                if t in prefs['tier_models'][tier])


def test_remaining_usage_produces_a_capable_mixed_allocation(inventory):
    from ravel.setup import model_usage
    from ravel.setup.models_setup import static_role_coverage
    documents, prefs, _ = inventory
    low, report = model_usage.recommend(prefs, documents=documents, context=context(prefs),
                                        prior_runs=[history()], now=NOW)
    high, _ = model_usage.recommend(prefs, documents=documents, context=context(prefs, remaining=1000),
                                    prior_runs=[history()], now=NOW)
    assert selected(low, 'judgment')[0] == documents[0]['id']
    assert selected(low, 'agent')[0] == documents[1]['id']
    assert all(selected(high, tier)[0] == documents[0]['id'] for tier in tr.TIERS)
    assert report['status'] == 'recommended'
    assert report['demand']['agent']['input_tokens'] == 200
    assert not static_role_coverage(low, documents)['uncovered']


def test_plan_and_reset_window_change_the_allocation(inventory):
    from ravel.setup import model_usage
    documents, prefs, _ = inventory
    choose = lambda value: model_usage.recommend(prefs, documents=documents, context=value,
                                                prior_runs=[history()], now=NOW)[0]
    included = choose(context(prefs, remaining=1000))
    metered = choose(context(prefs, remaining=1000, plan='metered'))
    far = choose(context(prefs, remaining=1000, reset='2030-01-02T00:00:00Z'))
    assert selected(included, 'agent')[0] != selected(metered, 'agent')[0]
    assert selected(included, 'agent')[0] != selected(far, 'agent')[0]


def test_measured_prior_demand_changes_the_recommendation(inventory):
    from ravel.setup import model_usage
    documents, prefs, _ = inventory
    small, _ = model_usage.recommend(prefs, documents=documents, context=context(prefs),
                                     prior_runs=[history(agent=20)], now=NOW)
    large, _ = model_usage.recommend(prefs, documents=documents, context=context(prefs),
                                     prior_runs=[history()], now=NOW)
    assert selected(small, 'agent')[0] != selected(large, 'agent')[0]


@pytest.mark.parametrize('change', ['absent', 'partial', 'incomplete', 'stale', 'future'])
def test_unknown_evidence_keeps_the_preset_and_records_its_reason(inventory, change):
    from ravel.setup import model_usage
    documents, prefs, _ = inventory
    usage, prior = context(prefs), [history()]
    if change == 'absent':
        prior = []
    elif change == 'partial':
        prior[0]['status'] = 'partial'
    elif change == 'incomplete':
        prior[0]['by_tier']['agent']['tokens']['output_tokens'] = None
    elif change == 'stale':
        usage['valid_until_utc'] = '2029-12-31T23:59:00Z'
    else:
        usage['observed_utc'] = '2030-01-01T00:01:00Z'
    result, report = model_usage.recommend(prefs, documents=documents, context=usage, prior_runs=prior, now=NOW)
    assert result == prefs
    assert report['status'] == 'unknown' and report['reasons']


def test_shared_account_capacity_is_aggregated_and_exhaustion_holds(inventory):
    from ravel.setup import model_usage
    documents, prefs, _ = inventory
    usage = context(prefs)
    usage['accounts'] = [{'transports': prefs['transport_preference'], 'plan': 'included',
                          'windows': [{'unit': 'tokens', 'remaining': 250,
                                       'resets_utc': '2030-01-01T01:00:00Z'}]}]
    with pytest.raises(ValueError, match='capacity'):
        model_usage.recommend(prefs, documents=documents, context=usage, prior_runs=[history()], now=NOW)


def test_alternative_model_uses_catalogue_prices_and_keeps_deciding_floors(inventory):
    from ravel.setup import model_usage
    from ravel.setup.models_setup import static_role_coverage
    documents, prefs, catalogue = inventory
    alternative = deepcopy(prefs)
    original = catalogue['models'][0]
    small = {**deepcopy(original), 'id': 'claude-fixture-small', 'class': 'small',
             'tiers': ['cheap'], 'efforts': [], 'prices_per_million': {k: 0 for k in mc.PRICE_KEYS}}
    catalogue['models'].append(small)
    # A cheap row suggested for a deciding tier stays ineligible.
    alternative['tier_models']['judgment'][documents[0]['id']] = small['id']
    usage = context(prefs, remaining=1000, plan='metered')
    result, _ = model_usage.recommend(prefs, alternatives=[alternative], documents=documents,
                                      context=usage, prior_runs=[history()], now=NOW)
    assert selected(result, 'judgment')[1] != small['id']
    assert not static_role_coverage(result, documents)['uncovered']


def test_input_reader_rejects_secret_shaped_fields_without_echo(tmp_path):
    from ravel.setup import model_usage
    path = tmp_path / 'usage.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'model-usage-context',
                                'credential': 'private-fixture-value'}))
    with pytest.raises(ValueError) as error:
        model_usage.load_context(path)
    assert 'private-fixture-value' not in str(error.value)


def test_usage_snapshot_uses_the_transport_registrys_identifier_contract(inventory):
    from ravel.setup import model_usage
    _, prefs, _ = inventory
    usage = context(prefs)
    identifier = 'worker.v1'
    assert tr.IDENT.fullmatch(identifier)
    usage['accounts'][0]['transports'] = [identifier]
    assert model_usage.validate_context(usage) == usage


def test_guided_setup_consumes_usage_and_saves_the_capable_recommendation(
        inventory, operator_home, tmp_path, monkeypatch, capsys):
    from ravel.controller.authority import operator
    from ravel.setup import model_usage, models_setup as setup
    documents, prefs, _ = inventory
    snapshot = tmp_path / 'account.json'
    prior = tmp_path / 'prior.json'
    snapshot.write_text(json.dumps(context(prefs)))
    prior.write_text(json.dumps(history()))
    monkeypatch.setattr(tr, 'all_declarations', lambda: documents)
    monkeypatch.setattr(setup, 'discover_providers', lambda docs: {'clis': {}})
    monkeypatch.setattr(setup.models, 'detect_models', lambda docs: {
        'governed_inventory': {'wired': prefs['transport_preference'], 'excluded': []},
        'transports': [{'id': d['id'], 'status': 'ok', 'models': [
            {'id': prefs['tier_models']['judgment'][d['id']], 'status': 'declared', 'catalogued': True}]}
                       for d in documents]})
    monkeypatch.setattr(setup.models, 'preferences', lambda preset, **kwargs: (deepcopy(prefs), [], kwargs['record']))
    monkeypatch.setattr(setup.models, 'estimate', lambda *args, **kwargs: {})
    monkeypatch.setattr(setup.models, 'print_estimate', lambda record: None)
    recommend = model_usage.recommend
    monkeypatch.setattr(model_usage, 'recommend', lambda *args, **kwargs: recommend(*args, **kwargs, now=NOW))
    monkeypatch.setattr('subprocess.run', lambda *args, **kwargs: pytest.fail('metadata input needs no model command'))
    assert setup.main(['--yes', '--usage-context', str(snapshot), '--prior-usage', str(prior)]) == 0
    result = operator.operator_config()['agent_preferences']
    assert selected(result, 'judgment')[0] == documents[0]['id']
    assert selected(result, 'agent')[0] == documents[1]['id']
    record = json.loads((tr.state_dir() / 'models-setup.usage.json').read_text())
    assert record['status'] == 'recommended' and record['prior_usage_sha256']
    assert (tr.state_dir() / 'models-setup.usage.json').stat().st_mode & 0o777 == 0o600
    assert 'Usage recommendation: measured prior-run scenario' in capsys.readouterr().out


@pytest.mark.parametrize('mode', ['complete', 'failed', 'plan', 'dry-run', 'json'])
def test_installer_invokes_setup_at_the_requested_startup_boundary(tmp_path, monkeypatch, capsys, mode):
    from types import SimpleNamespace
    from ravel.setup import installer, models_setup
    calls = []
    fake = SimpleNamespace(run=lambda *args: {'status': 'incomplete' if mode == 'failed' else 'complete'},
                           plan=lambda *args: {}, dry_run=lambda *args: {})
    monkeypatch.setattr(installer, 'Installer', lambda *args, **kwargs: fake)
    monkeypatch.setattr(installer, 'write_pointer', lambda *args: None)
    monkeypatch.setattr(models_setup, 'main', lambda args: calls.append(args) or print('model setup output') or 0)
    args = ['--setup-models', '--yes', '--model-usage-context', 'account.json',
            '--model-prior-usage', 'prior.json', '--model-prior-run', 'prior-run']
    if mode in ('plan', 'dry-run', 'json'):
        args += ['--json']
    if mode in ('plan', 'dry-run'):
        args += ['--' + mode]
    assert installer.main(args, repo=tmp_path) == (1 if mode == 'failed' else 0)
    if mode in ('failed', 'plan', 'dry-run'):
        assert calls == []
    else:
        assert calls == [['--yes', '--usage-context', 'account.json', '--prior-usage', 'prior.json',
                          '--prior-run', 'prior-run']]
    if mode == 'json':
        output = capsys.readouterr()
        assert json.loads(output.out)['model_setup_exit_code'] == 0
        assert 'model setup output' in output.err


def test_existing_run_usage_comes_from_the_controller_counter_and_closes_its_view(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from ravel.controller import model_cost
    from ravel.controller.diagnostics import cli
    from ravel.setup import model_usage
    calls = []
    store = SimpleNamespace(snapshot=nullcontext, close=lambda: calls.append('closed'))
    monkeypatch.setattr(cli, 'open_store', lambda run_id: calls.append(run_id) or store)
    monkeypatch.setattr(model_cost, 'summary', lambda value: history() if value is store else None)
    assert model_usage.load_run('prior-run') == history()
    assert calls == ['prior-run', 'closed']


@pytest.mark.parametrize('change', ['expired', 'unknown', 'unpriced'])
def test_account_gaps_stay_explicit_and_a_reset_grants_no_new_capacity(inventory, change):
    from ravel.setup import model_usage
    documents, prefs, catalogue = inventory
    usage = context(prefs, remaining=1000)
    if change == 'expired':
        usage['accounts'][0]['windows'][0]['resets_utc'] = '2029-12-31T23:59:00Z'
    elif change == 'unknown':
        usage['accounts'][0]['windows'][0]['remaining'] = None
    else:
        catalogue['models'][0]['prices_per_million'] = None
        usage['accounts'][0]['plan'] = 'metered'
        usage['accounts'][0]['windows'][0]['unit'] = 'usd'
    result, report = model_usage.recommend(prefs, documents=documents, context=usage,
                                           prior_runs=[history()], now=NOW)
    assert all(selected(result, tier)[0] == documents[1]['id'] for tier in tr.TIERS)
    assert report['unknown_capacity_components'] == 0


def test_an_incapable_low_cost_alternative_cannot_mask_exhausted_capable_capacity(inventory):
    from ravel.setup import model_usage
    documents, prefs, catalogue = inventory
    low = {**deepcopy(catalogue['models'][0]), 'id': 'claude-fixture-low-effort', 'efforts': [],
           'prices_per_million': {key: 0 for key in mc.PRICE_KEYS}}
    catalogue['models'].append(low)
    alternative = deepcopy(prefs)
    for tier in tr.TIERS:
        alternative['tier_models'][tier] = {documents[0]['id']: low['id']}
    usage = context(prefs, remaining=0)
    usage['accounts'] = [{'transports': prefs['transport_preference'], 'plan': 'metered',
                          'windows': [{'unit': 'usd', 'remaining': 0,
                                       'resets_utc': '2030-01-01T01:00:00Z'}]}]
    with pytest.raises(ValueError, match='capacity'):
        model_usage.recommend(prefs, alternatives=[alternative], documents=documents,
                              context=usage, prior_runs=[history()], now=NOW)


def test_model_changes_follow_capacity_pressure_and_preserve_a_funded_preset(inventory):
    from ravel.setup import model_usage
    documents, prefs, catalogue = inventory
    transport = documents[0]['id']
    prefs['transport_preference'] = [transport]
    for tier in tr.TIERS:
        prefs['tier_models'][tier] = {transport: catalogue['models'][0]['id']}
    economical = {**deepcopy(catalogue['models'][0]), 'id': 'claude-fixture-economical',
                  'prices_per_million': {key: 2 for key in mc.PRICE_KEYS}}
    catalogue['models'].append(economical)
    alternative = deepcopy(prefs)
    for tier in tr.TIERS:
        alternative['tier_models'][tier][transport] = economical['id']
    usage = {'schema_version': 1, 'kind': 'model-usage-context',
             'observed_utc': '2030-01-01T00:00:00Z', 'valid_until_utc': '2030-01-01T00:30:00Z',
             'expected_run_seconds': 3600,
             'accounts': [{'transports': [transport], 'plan': 'metered',
                           'windows': [{'unit': 'usd', 'remaining': .001,
                                        'resets_utc': '2030-01-01T01:00:00Z'}]}]}
    constrained, _ = model_usage.recommend(prefs, alternatives=[alternative], documents=documents,
                                          context=usage, prior_runs=[history()], now=NOW)
    assert selected(constrained, 'agent')[1] == economical['id']
    usage['accounts'][0]['windows'][0]['remaining'] = 1
    funded, _ = model_usage.recommend(prefs, alternatives=[alternative], documents=documents,
                                     context=usage, prior_runs=[history()], now=NOW)
    assert all(selected(funded, tier)[1] == catalogue['models'][0]['id'] for tier in tr.TIERS)
