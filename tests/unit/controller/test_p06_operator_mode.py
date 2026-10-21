"""P06: the operator ledger and the one operating mode per run (A02, A04, C38, CT04, SW25).

The operator's configuration lives in the operator area of the controller home, outside the run
tree; a run freezes it once at intake, and nothing later (environment, project files, a new
operator setting, a child's request) changes the frozen record.
"""
from __future__ import annotations

import json
import os
import stat

import pytest

from test_p06_support import autonomous, frozen_store, new_store, operator_home, ownership  # noqa: F401
from ravel.controller.authority import (AuthorityRefused, effective_bounds, freeze_child, freeze_mode, frozen,
                                        narrow, operator_config)
from ravel.controller.authority import mode as mode_mod, operator


def test_controller_home_and_store_root_ignore_the_environment(operator_home, monkeypatch, tmp_path):
    before = operator.controller_home()
    root = operator_config()['store_root']
    for name in ('HOME', 'RAVEL_STATE_DIR', 'RAVEL_WORK_ROOT', 'XDG_STATE_HOME'):
        monkeypatch.setenv(name, str(tmp_path / 'elsewhere'))
    assert operator.controller_home() == before
    assert operator_config()['store_root'] == root
    assert not str(root).startswith(str(tmp_path / 'elsewhere'))


def test_default_configuration_grants_no_machine_authority(operator_home):
    config = operator_config()
    assert config['source'] == 'default' and config['entry'] is None
    assert config['mode'] == 'physicist-in-the-loop'
    assert config['allow_unconfined'] is False and config['allow_request_delegation'] is False


def test_operator_init_set_show_with_private_modes(operator_home):
    written = operator.init(mode='autonomous', budgets={'events': 5000}, wait_bound_seconds=60,
                            notify_command=['/usr/bin/true'])
    assert written['source'] == 'operator_ledger' and written['budgets']['events'] == 5000
    ledger = operator.ledger_path()
    assert stat.S_IMODE(os.stat(ledger.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(ledger).st_mode) == 0o600
    with pytest.raises(AuthorityRefused):
        operator.init(mode='physicist-in-the-loop')
    changed = operator.set_values({'budgets': {'tokens': 10}, 'r3_policy': 'conservative_default'})
    shown = operator_config()
    assert shown == changed and shown['budgets']['events'] == 5000 and shown['budgets']['tokens'] == 10
    assert shown['entry']['seq'] == 1 and shown['r3_policy'] == 'conservative_default'


def test_operator_writes_refuse_agent_sessions(operator_home, monkeypatch):
    monkeypatch.setenv('CLAUDECODE', '1')
    with pytest.raises(AuthorityRefused):
        operator.init(mode='autonomous')
    assert not operator.ledger_path().exists()


def test_invalid_operator_values_are_refused(operator_home):
    for bad in ({'budgets': {'events': -1}}, {'bounds': {'rungs': ['warp']}},
                {'notify_command': 'notify me'}, {'r3_policy': 'guess'}, {'mode': 'whatever'},
                {'store_root': 'relative/path'}, {'wait_bound_seconds': -5}):
        operator_config()
        with pytest.raises((ValueError, AuthorityRefused)):
            if not operator._ledger_rows():
                operator.init(mode='autonomous')
            operator.set_values(bad)
    assert operator_config()['mode'] == 'autonomous'


def test_a_tampered_operator_ledger_refuses(operator_home):
    operator.init(mode='physicist-in-the-loop')
    path = operator.ledger_path()
    row = json.loads(path.read_text())
    row['record']['config']['mode'] = 'autonomous'
    path.write_text(json.dumps(row) + '\n')
    with pytest.raises(ValueError):
        operator_config()


def test_a_root_owned_operator_ledger_is_the_stronger_source(operator_home, monkeypatch):
    from ravel.workflow import operating_mode
    operator.init(mode='autonomous')
    stronger = {**operator.default_config(), 'mode': 'physicist-in-the-loop'}
    rows = [{'seq': 0, 'digest': 'd' * 64, 'record': {'schema_version': 1, 'kind': 'setting',
                                                       'target': 'x', 'value': stronger}}]
    monkeypatch.setattr(operating_mode, '_operator_records', lambda kind, target: rows)
    config = operator_config()
    assert config['source'] == 'operator_ledger_root' and config['mode'] == 'physicist-in-the-loop'


def test_A04_CT04_mode_frozen_once_and_later_changes_do_not_apply(operator_home, tmp_path, monkeypatch):
    autonomous()
    store = frozen_store(tmp_path)
    record = frozen(store)
    assert record['mode'] == 'autonomous' and record['delegation'] == 'operator_configured'
    operator.set_values({'mode': 'physicist-in-the-loop', 'budgets': {'events': 1}})
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'physicist-in-the-loop')
    monkeypatch.setenv('RAVEL_AUTONOMY_BOUNDS', '{}')
    again = freeze_mode(store, {'prompt': 'Compute the fictional observable for the toy model.'})
    assert again['id'] == record['id'] and frozen(store) == record
    assert effective_bounds(store)['budgets'] == record['budgets']
    with pytest.raises(AuthorityRefused):
        freeze_mode(store, {'prompt': 'A different request.'})
    assert len(store.scan('mode')) == 1


def test_CT04_one_mode_record_per_run(operator_home, tmp_path):
    store = frozen_store(tmp_path)
    store.append('mode', {**frozen(store), 'uid': 'second', 'mode': 'autonomous'})
    with pytest.raises(AuthorityRefused):
        frozen(store)


def test_request_can_narrow_but_widens_only_with_operator_permission(operator_home, tmp_path):
    autonomous()
    narrowed = frozen_store(tmp_path, {'prompt': 'Please ask for approval before running anything heavy.'}, 'r1')
    assert frozen(narrowed)['mode'] == 'physicist-in-the-loop'
    assert frozen(narrowed)['request_statement']['text'] == 'ask for approval'
    negated = frozen_store(tmp_path, {'prompt': 'Work autonomously; do not ask for approval.'}, 'r2')
    assert frozen(negated)['mode'] == 'autonomous'
    operator.set_values({'mode': 'physicist-in-the-loop'})
    asked = frozen_store(tmp_path, {'prompt': 'Proceed autonomously within the budget.'}, 'r3')
    assert frozen(asked)['mode'] == 'physicist-in-the-loop'
    operator.set_values({'allow_request_delegation': True})
    allowed = frozen_store(tmp_path, {'prompt': 'Proceed autonomously within the budget.'}, 'r4')
    assert frozen(allowed)['mode'] == 'autonomous' and frozen(allowed)['delegation'] == 'request_stated'


@pytest.mark.parametrize('prompt', [
    "Please don't start until I give approval.",
    'Do not launch heavy compute before my approval.',
    'Do not ask for approval for small steps, but wait for my approval before unblinding.',
    'Never run the full scan without my approval.',
    'No autonomous decisions for this request.',  # an unlocated mention narrows, as in H1
])
def test_A04_a_request_that_asks_for_the_physicist_always_narrows(operator_home, tmp_path, prompt):
    autonomous()
    record = frozen(frozen_store(tmp_path, {'prompt': prompt}))
    assert record['mode'] == 'physicist-in-the-loop' and record['delegation'] is None
    assert record['request_mode'] == 'physicist-in-the-loop'


@pytest.mark.parametrize('prompt', ['Work autonomously; do not ask for approval.',
                                    "You don't need to ask me for permission.",
                                    'Compute the fictional observable for the toy model.'])
def test_A04_a_directly_negated_request_to_ask_does_not_narrow(operator_home, tmp_path, prompt):
    autonomous()
    record = frozen(frozen_store(tmp_path, {'prompt': prompt}))
    assert record['mode'] == 'autonomous' and record['delegation'] == 'operator_configured'


def test_A04_C38_children_narrow_only(operator_home, tmp_path):
    autonomous(budgets={'events': 1000})
    parent = frozen_store(tmp_path, run_id='parent')
    record = frozen(parent)
    child = narrow(record, {'budgets': {'events': 10}, 'bounds': {'rungs': ['dry', 'smoke']},
                            'mode': 'physicist-in-the-loop'})
    assert child['budgets']['events'] == 10 and child['mode'] == 'physicist-in-the-loop'
    for widening in ({'budgets': {'events': 2000}}, {'allow_unconfined': True},
                     {'machine_checkins': ['approve_plan', 'go', 'deviation', 'final', 'escalation']},
                     {'notify_command': ['/bin/sh']}, {'store_root': '/tmp/x'}):
        with pytest.raises((AuthorityRefused, ValueError)):
            narrow(record, widening)
    strict = narrow(record, {'mode': 'physicist-in-the-loop'})
    with pytest.raises(AuthorityRefused):
        narrow(strict, {'mode': 'autonomous'})
    store = new_store(tmp_path, 'child')
    made = freeze_child(store, parent, {'prompt': 'A child question.'}, {'budgets': {'events': 5}})
    assert made['parent'] == {'run_id': 'parent', 'mode_record': record['id']} and made['budgets']['events'] == 5
    with pytest.raises(AuthorityRefused):
        freeze_child(new_store(tmp_path, 'child2'), parent, {'prompt': 'x'}, {'budgets': {'events': 5000}})


def test_SW25_provider_policy_frozen_at_intake(operator_home, tmp_path, ownership):
    from ravel.workflow import provider_policy
    project = tmp_path / 'project'
    run_dir = project / 'runs' / 'r1'
    run_dir.mkdir(parents=True)
    (project / '.ravel').mkdir()
    entry = {'transport_id': 'fictional-transport', 'account_class': 'login:subscription'}
    (project / '.ravel/data_classification.json').write_text(json.dumps(
        {'level': 'restricted', 'allowed_providers': [entry]}))
    store = new_store(tmp_path)
    operator.init(mode='physicist-in-the-loop')
    freeze_mode(store, {'prompt': 'Fictional request.'}, run_dir=run_dir)
    ownership.register(run_dir, store)
    pinned = frozen(store)['provider_policy']['record']
    assert pinned['declared'] and pinned['data_classification']['level'] == 'restricted'
    # A rewrite after intake (widening the project default) changes nothing for the run.
    (project / '.ravel/data_classification.json').write_text(json.dumps({'level': 'public', 'allowed_providers': []}))
    (run_dir / 'inputs').mkdir()
    (run_dir / 'inputs/data_classification.json').write_text(json.dumps({'level': 'public', 'allowed_providers': []}))
    assert provider_policy.start(run_dir) == pinned
    assert provider_policy.check(run_dir, {'id': 'fictional-transport', 'account_class': 'login:subscription'},
                                 'login:subscription') == entry
    with pytest.raises(provider_policy.PolicyRefused):
        provider_policy.check(run_dir, {'id': 'other', 'account_class': 'api:metered'}, 'api:metered')
    with pytest.raises(provider_policy.PolicyRefused):
        provider_policy.approve_change(run_dir, {'level': 'public', 'allowed_providers': []}, {})


def test_CT04_legacy_mode_initialization_writes_nothing_for_a_controller_run(operator_home, tmp_path, ownership,
                                                                           monkeypatch):
    from ravel.workflow import operating_mode
    run_dir = tmp_path / 'run'
    run_dir.mkdir()
    store = ownership.register(run_dir, frozen_store(tmp_path))
    monkeypatch.setenv('RAVEL_OPERATING_MODE', 'autonomous')
    assert operating_mode.initialize(run_dir, {'prompt': 'x'}) is None
    assert operating_mode.frozen(run_dir) is None
    assert not (run_dir / operating_mode.RUN_RECORD).exists()
    assert len(store.scan('mode')) == 1  # the store keeps the run's one mode record


def test_effective_bounds_follow_approved_steering_only(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    base = effective_bounds(store)
    assert mode_mod.policy_widens(base, {'budgets': {'events': base['budgets']['events'] + 1}}) == ['budgets.events']
    assert mode_mod.policy_widens(base, {'budgets': {'events': 1}}) == []
    with pytest.raises(ValueError):
        mode_mod.policy_widens(base, {'mode': 'autonomous'})


NEW_DEFAULTS = {'harness': None, 'engagement': {'minimum_tier': None}, 'restricted_sources': None,
                'remote_job_ceiling': 0, 'procedure_byte_ceiling': 1048576,
                'agent_preferences': None, 'site_resource_ceilings': None}


def test_operator_round_trips_all_consumer_defaults(operator_home, tmp_path):
    from jsonschema import Draft202012Validator
    from ravel.controller import schema
    config = operator.init(mode='autonomous')
    assert {k: config[k] for k in NEW_DEFAULTS} == NEW_DEFAULTS
    assert operator_config() == config
    clean = {k: v for k, v in config.items() if k not in ('source', 'entry')}
    assert list(Draft202012Validator(schema('operator-config.v1')).iter_errors(clean)) == []
    store = frozen_store(tmp_path)
    assert {k: frozen(store)[k] for k in NEW_DEFAULTS} == NEW_DEFAULTS
    child = freeze_child(new_store(tmp_path, 'child-defaults'), store, {'prompt': 'Child request.'})
    assert {k: child[k] for k in NEW_DEFAULTS} == NEW_DEFAULTS


def test_authenticated_old_config_migrates_after_mac_check(operator_home):
    from ravel.controller.authority import common, issuer
    from ravel.workflow import rdj_custody
    old = operator.default_config()
    for key in NEW_DEFAULTS:
        old.pop(key, None)
    old['budgets']['tokens'] = 7
    path = operator.ledger_path()
    operator.private_dir(path.parent)
    issuer.initialize()
    context = ['operator-config', str(path.resolve())]
    record = issuer.seal({'schema_version': 1, 'kind': 'operator-config', 'action': 'init',
                          'config': old, 'config_sha256': common.digest(old), 'operator_uid': os.getuid()}, context)
    row = rdj_custody._append(path, record)
    issuer.anchor(context, [{'sha256': common.digest(row)}])
    loaded = operator_config()
    assert {k: loaded[k] for k in NEW_DEFAULTS} == NEW_DEFAULTS
    assert loaded['budgets']['tokens'] == 7
    # Even a re-chained row cannot authenticate a changed configuration.
    record['config']['budgets']['tokens'] = 8
    record['config_sha256'] = common.digest(record['config'])
    path.unlink()
    rdj_custody._append(path, record)
    with pytest.raises(AuthorityRefused):
        operator_config()


def test_route_defaults_freeze_provenance_and_preserve_explicit_ceilings(operator_home, tmp_path):
    from types import SimpleNamespace
    from ravel.controller.graph import services
    seen = []
    def defaults(route):
        seen.append(route)
        return {'children': 80, 'tokens': 20_000_000, 'model_calls': 1200}
    envelope = SimpleNamespace(defaults=defaults, data=lambda name: {'status': 'ready', 'sha256': 'e' * 64})
    operator.init(mode='autonomous', budgets={'tokens': 7})
    with services(authority=SimpleNamespace(envelope=envelope)):
        result = freeze_mode(new_store(tmp_path), {'prompt': 'Compute a toy observable.', 'route': 'toy-route'})
    assert seen == ['toy-route']
    assert result['budgets']['tokens'] == 7 and result['budgets']['children'] == 80
    assert result['budgets']['model_calls'] == 1200
    assert result['budget_source']['kind'] == 'engagement_envelope'
    assert result['budget_source']['route'] == 'toy-route'
    assert result['budget_source']['sha256'] == 'e' * 64
    assert result['budget_source']['explicit_fields'] == ['tokens']
    assert 'children' in result['budget_source']['derived_fields']


def test_absent_budgets_derive_from_the_installed_envelope(operator_home, tmp_path):
    from ravel.controller.engagement import envelope
    installed = envelope.data('envelopes.json')
    assert installed['status'] == 'ready'
    expected = installed['routes']['analysis']['full']
    operator.init(mode='autonomous')
    store = new_store(tmp_path)
    contract = {'prompt': 'Compute a fictional observable.', 'route': 'analysis'}
    result = freeze_mode(store, contract)
    ceilings = result['budgets']
    assert ceilings['children'] >= expected['high']['sessions'] > 16
    assert ceilings['tokens'] >= expected['high']['input_tokens'] + expected['high']['output_tokens'] > 5_000_000
    assert ceilings['model_calls'] >= expected['high']['calls']
    for key, amount in expected['reservations'].items():
        assert ceilings[key] >= amount
    from importlib.resources import files
    from ravel.controller.engagement.policy import role_cards
    from ravel.controller.step.graph import _amounts
    specs = json.loads(files('ravel').joinpath('data/controller/routes/analysis.json').read_text())['specs']
    spec = next(s for s in specs if s['id'] == 'analysis')
    cards = role_cards()
    declared_calls = sum(_amounts(s, cards[s['role']], 'worker')['model_calls']
                         for s in spec['steps'] if s.get('role'))
    assert expected['reservations']['model_calls'] >= declared_calls
    assert envelope.budget_projection(expected, ceilings) is None
    assert result['budget_source']['sha256'] == installed['sha256']
    assert result['budget_source']['tier'] == 'full'
    operator.set_values({'budgets': {'children': 1, 'tokens': 1}})
    assert freeze_mode(store, contract) == result
    explicit = freeze_mode(new_store(tmp_path, 'explicit'), contract)
    assert explicit['budgets']['children'] == explicit['budgets']['tokens'] == 1
    spend = envelope.budget_projection(expected, explicit['budgets'])
    assert spend['class'] == 'R3' and spend['action'] == 'spend_above_ceiling'
    assert {'children', 'tokens'} <= set(spend['dimensions'])


def test_stale_calibration_holds_default_budget_freeze(operator_home, tmp_path, monkeypatch):
    from copy import deepcopy
    from ravel.controller.engagement import envelope
    original = envelope.data
    def stale(name):
        value = deepcopy(original(name))
        if name == 'calibration.json':
            value['high_retries'] += 1
        return value
    monkeypatch.setattr(envelope, 'data', stale)
    operator.init(mode='autonomous')
    store = new_store(tmp_path)
    with pytest.raises(AuthorityRefused, match='calibration|unavailable'):
        freeze_mode(store, {'prompt': 'Compute a fictional observable.', 'route': 'analysis'})
    assert store.scan('mode') == []


def test_unavailable_envelope_holds_instead_of_using_smaller_defaults(operator_home, tmp_path, monkeypatch):
    from ravel.controller.engagement import envelope
    original = envelope.data
    monkeypatch.setattr(envelope, 'data', lambda name: {'status': 'unavailable'}
                        if name == 'envelopes.json' else original(name))
    operator.init(mode='physicist-in-the-loop')
    store = new_store(tmp_path)
    with pytest.raises(AuthorityRefused, match='unavailable'):
        freeze_mode(store, {'prompt': 'Compute a toy observable.'})
    assert store.scan('mode') == []


def test_consumer_settings_are_validated_and_frozen(operator_home, tmp_path):
    changes = {'harness': {'channel': 'trusted'}, 'engagement': {'minimum_tier': 'full'},
               'restricted_sources': '/operator/policy.json', 'remote_job_ceiling': 3,
               'procedure_byte_ceiling': 4096,
               'agent_preferences': {'kind': 'agent-preferences', 'schema_version': 1,
                                     'transport_preference': ['toy-worker'], 'tier_models': {}},
               'site_resource_ceilings': {'cpus': 2, 'memory_mb': 256}}
    operator.init(mode='autonomous', **changes)
    store = frozen_store(tmp_path)
    assert {k: frozen(store)[k] for k in changes} == changes
    operator.set_values({'remote_job_ceiling': 0, 'engagement': {'minimum_tier': 'lean'}})
    assert frozen(store)['remote_job_ceiling'] == 3
    for bad in ({'remote_job_ceiling': -1}, {'procedure_byte_ceiling': True},
                {'engagement': {'minimum_tier': 'missing'}}, {'agent_preferences': {}},
                {'site_resource_ceilings': {'cpus': -1}}, {'restricted_sources': 'relative'}):
        with pytest.raises(ValueError):
            operator.set_values(bad)
