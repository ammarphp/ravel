"""Who fills a seat and how it is dispatched (M06, M07): admitted transports, the card's identity and limits."""
from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from ravel.controller.step import cards, graph, seats, spec
from ravel.controller.step.services import StepHold, digest
from ravel.controller import authority as REAL_AUTHORITY
from ravel.workflow import agent_worker, broker, role_registry, transport_registry as tr

from test_p04_support import FakeStore, inert_worker, run_env, services_installed  # noqa: F401
from test_p04_support import context, graphs, install_plan, make_step
from test_p04_ledger_contract import contract_env, instructed_env  # noqa: F401
from test_p06_support import autonomous, operator_home, view  # noqa: F401

TRANSPORTS = sorted(p.stem for p in Path(tr.BUILTIN_DIR).glob('*.json'))


def _effect_fixture(env, monkeypatch, *, launch=False, rung='smoke'):
    """Approve the exact fixture plan through the real frozen authority service."""
    monkeypatch.setitem(sys.modules, 'ravel.controller.authority', REAL_AUTHORITY)
    autonomous()
    REAL_AUTHORITY.freeze_mode(env.store, {'prompt': 'Compute a fictional quantity.'})
    step = make_step('s1', kind='operate' if launch else 'author', role=None if launch else 'baseline-producer',
                     operation='fixture-operation' if launch else None, rung=rung,
                     budget={'wall_seconds': 60, 'broker_calls': 100, 'tokens': 1000,
                             'cost_usd': 0, 'core_hours': 0, 'events': 0, 'children': 1, 'attempts': 2},
                     parameters={'launch': {'argv': [sys.executable, '-c', 'pass'], 'stage': 'bounded-compute'}}
                     if launch else {})
    if launch:
        step['budget'].pop('children')
    pin = install_plan(env.store, [step])
    retained_plan = env.store.scan('plan')[-1]['record']
    bound_plan = json.loads(env.store.get_blob(retained_plan['blob']))
    graph.module('ledger').materialise(env.store, 'plan', {'plan': bound_plan})
    # As the controller does when it binds a plan: the plan-bind rows are recorded, the governed step verifies them.
    from ravel.controller.step import binding
    binding.record_plan_rows(env.store, bound_plan, contract_sha256=None, ledger=graph.module('ledger'))
    # This is the binding dimension table; retry limits do not describe authority resources.
    mapping = {'broker_calls': 'model_calls', 'attempts': None}
    amounts = {mapping.get(k, k): v for k, v in step['budget'].items() if mapping.get(k, k) is not None}
    stage = (spec.launch(step) or {}).get('stage') or step.get('operation') or step['kind']
    stages = sorted({stage, step.get('operation') or step['kind']})
    bounds = {'rung': rung, 'stages': stages, 'budget': amounts}
    approval = REAL_AUTHORITY.request(env.store, 'approve_plan',
        {'view': view(env.store, 'approve_plan', plan_sha256=pin)}, bounds)
    assert approval.get('decision') == 'approve' and approval['bounds'] == bounds, json.dumps(approval, sort_keys=True)
    return step, context(env.store, env.run_dir, pin, stage=stage, requires_go=True,
                         go_pins={'waypoint:s0': 'a' * 64}), amounts, approval


@pytest.mark.parametrize('case', ['worker', 'launch', 'narrow', 'go_match', 'go_mismatch'])
def test_worker_effect_above_dry_is_admitted_with_the_real_authority(instructed_env, operator_home,
                                                                  monkeypatch, graphs, case):
    from ravel.controller.step.services import bound
    from ravel.controller.step import run
    env = instructed_env
    launch = case in ('launch', 'narrow')
    step, ctx, amounts, approval = _effect_fixture(env, monkeypatch, launch=launch,
                                                   rung='full' if case.startswith('go_') else 'smoke')
    if case == 'worker':
        result = run(env.store, step, ctx)
        assert result['status'] == 'completed', json.dumps(result, sort_keys=True)
        assert len(env.store.scan('step-dispatch')) == 1
        assert env.store.scan('worker-session')
        return
    if case.startswith('go_'):
        granted = REAL_AUTHORITY.request(env.store, 'go', {'view': view(env.store, 'go',
            approve_plan=approval['id'], **{'waypoint:s0': 'a' * 64})},
            {'rung': 'full', 'stages': ['author'], 'budget': amounts})
        assert granted['decision'] == 'go'
        if case == 'go_mismatch':
            ctx['go_pins'] = {'waypoint:s0': 'b' * 64}
            with pytest.raises(StepHold) as refused:
                graph._authorize(env.store, ctx, step, amounts)
            assert refused.value.reason == 'authority_refused'
            assert 'waypoint evidence' in refused.value.would_make_possible
        else:
            assert graph._authorize(env.store, ctx, step, amounts)['go'] == granted['id']
        assert env.store.scan('step-dispatch') == []
        return
    state = {'step': step, 'acting': step, 'branch': 'launch', 'context': ctx,
             'reservation': {'amounts': amounts}}
    effect_count = []
    real_popen = graph.module('confine').popen
    monkeypatch.setattr(graph.module('confine'), 'popen',
                        lambda capsule, **kw: effect_count.append(capsule) or real_popen(capsule, **kw))
    with bound(env.store):
        state['preflight'] = graph._launch_preflight(state, env.store, ctx, env.run_dir, step, None, [], [], {})
        # This authority unit calls the inner helper directly. Supply the outer
        # preflight identity; native provider enforcement has separate integration controls.
        prepared = state['preflight']
        prepared.update(plan_sha256=ctx['plan_sha256'], budget=deepcopy(amounts))
        proof = {'plan_sha256': ctx['plan_sha256'], 'step_sha256': spec.step_sha256(step),
                 'launch_sha256': prepared['launch_sha256'], 'passed': True,
                 'budget': deepcopy(amounts), 'stage': prepared.get('stage'), 'correction': None,
                 'depends_on': list(step.get('depends_on') or ()),
                 'log': str(Path(prepared['output_root']).parent / 'logs' / 'stdout'),
                 'capsule': {key: deepcopy(prepared['capsule'][key])
                             for key in ('argv', 'reads', 'writes', 'cwd')}}
        fact = graph._fact(state, 'native-launch-preflight', **proof)
        prepared['native_preflight'] = fact['record']
        expected_proof = {'step_id': step['id'], 'seat': None, 'attempt': ctx['attempt'],
                          'mechanism': 'native-launch-preflight', **deepcopy(proof)}
        pins = {'plan_sha256': ctx['plan_sha256'], 'step_sha256': spec.step_sha256(step),
                'launch_sha256': prepared['launch_sha256'], 'attempt': str(ctx['attempt']),
                'native_preflight': fact['record']}
        expected_action = {'kind': 'smoke_launch', 'step': step['id'], 'node_id': step['id'],
                           'rung': 'smoke', 'floor': step.get('consequence_class', 'R0'),
                           'view_pins': pins, 'digest': digest(pins), 'budget': deepcopy(amounts)}
        decisions = []

        def decide(store, run_dir, gate, action):
            assert store is env.store and run_dir == env.run_dir and gate == 'launch'
            assert action == expected_action
            assert store.read('step-fact', pins['native_preflight'])['record'] == expected_proof
            assert store.scan('step-launch') == []
            assert effect_count == [] and env.fakes['confine'].launched == []
            decisions.append(deepcopy(action))
            return []

        # The fixture's protected store has no controller-run binding. Isolate only
        # this independent ledger contract; real preflight and fresh authority remain active.
        monkeypatch.setattr(graph.module('ledger'), 'decide', decide)
        if case == 'narrow':
            @contextmanager
            def narrow_before_start(run_dir):
                REAL_AUTHORITY.request(env.store, 'steering', {'view': view(env.store, 'steering'),
                    'policy': {'bounds': {'allowed_stages': []}}}, {})
                assert REAL_AUTHORITY.effective_bounds(env.store)['bounds']['allowed_stages'] == []
                yield
            monkeypatch.setattr(graph, '_controller_dispatch', narrow_before_start)
            with pytest.raises(graph.LaunchNotStarted) as refused:
                graph._launch(state, {})
            assert refused.value.reason == 'authority_refused' and refused.value.not_dispatched
            assert effect_count == [] and env.fakes['confine'].launched == []
        else:
            assert graph._launch(state, {})['exit_status'] == 0
            assert len(effect_count) == 1 and len(env.fakes['confine'].launched) == 1
        assert len(decisions) == 1


@pytest.mark.parametrize('dimension', ['unknown', 'children', 'broker_calls', 'attempts'])
def test_effect_budget_uses_the_binding_dimensions_without_silent_loss(instructed_env, operator_home,
                                                                      monkeypatch, dimension):
    env = instructed_env
    step, ctx, amounts, _ = _effect_fixture(env, monkeypatch)
    captured = []
    authorize = REAL_AUTHORITY.authorize_effect
    monkeypatch.setattr(REAL_AUTHORITY, 'authorize_effect', lambda store, effect: captured.append(effect)
                        or authorize(store, effect))
    if dimension == 'unknown':
        with pytest.raises(StepHold) as refused:
            graph._authorize(env.store, ctx, step, {**amounts, 'unrecognized_resource': 0})
        assert refused.value.reason == 'budget_dimension_unknown' and captured == []
        return
    budget = {**amounts, 'broker_calls': amounts['model_calls']} if dimension == 'broker_calls' else dict(amounts)
    if dimension == 'broker_calls':
        budget.pop('model_calls')
    elif dimension == 'attempts':
        budget['attempts'] = 2
    assert graph._authorize(env.store, ctx, step, budget)['approve_plan']
    assert captured[0]['budget'] == amounts
    assert captured[0]['stage'] == 'author' and captured[0]['requires_go'] is True
    assert captured[0]['go_pins'] == ctx['go_pins']


@pytest.mark.parametrize('transport_id', TRANSPORTS)
def test_I03_T01_only_restricted_admitted_cli_workers_and_the_ravel_loop_fill_a_controller_seat(transport_id):
    document = tr.load(transport_id)
    problem = seats.admission_problem(document)
    kind = document['transport_kind']
    if kind == 'ravel-loop':
        assert problem is None
    elif kind == 'cli-worker':
        rule = seats.LAUNCHER_RESTRICTIONS.get(document['launcher'])
        if rule is None or not rule['admitted']:
            assert problem == 'launcher:' + document['launcher']
        elif ((document.get('worker_surface') or {}).get('mcp') or {}).get('config') != rule['surface']:
            # A known launcher without its broker-only surface is still not admitted.
            assert problem == 'unrestricted:worker_surface.mcp'
        else:
            assert problem is None, problem
            template = document['argv_template']
            assert all(flag in template for flag in rule['flags'])
            assert all(template[template.index(flag) + 1] == value
                       for flag, value in rule['placeholders'].items())
            assert document['worker_surface']['mcp']['config'] == rule['surface']
    else:
        # Admission of a restricted worker never admits its one-shot or host routes.
        assert problem == 'transport_kind:' + kind


@pytest.mark.parametrize('transport_id', ['claude-cli-worker', 'codex-cli-worker', 'gemini-cli-worker'])
def test_I03_T01_every_admitted_cli_restriction_is_required(transport_id):
    original = tr.load(transport_id, installed_only=True)
    rule = seats.LAUNCHER_RESTRICTIONS[original['launcher']]
    assert seats.admission_problem(original) is None
    for flag in rule['flags']:
        damaged = deepcopy(original)
        damaged['argv_template'].remove(flag)
        assert seats.admission_problem(damaged) == 'unrestricted:' + flag
    for flag in rule['placeholders']:
        damaged = deepcopy(original)
        damaged['argv_template'][damaged['argv_template'].index(flag) + 1] = 'unrestricted-fixture'
        assert seats.admission_problem(damaged) == 'unrestricted:' + flag
    for surface in (None, 'unrestricted-fixture'):
        damaged = deepcopy(original)
        if surface is None:
            damaged.pop('worker_surface')
        else:
            damaged['worker_surface']['mcp']['config'] = surface
        assert seats.admission_problem(damaged) == 'unrestricted:worker_surface.mcp'
    damaged = deepcopy(original)
    damaged['launcher'] = 'unregistered-fixture'
    assert seats.admission_problem(damaged) == 'launcher:unregistered-fixture'


def _card(role='baseline-producer'):
    return role_registry.load(role)


class _Unqualified:
    """A run store holding no operator-run transport qualification."""

    def scan(self, kind):
        return []


def _context(order):
    return {'agent_preferences': {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': order,
                                  'tier_models': {t: {'claude-cli-worker': 'claude-fixture-model'}
                                                  for t in ('judgment', 'agent', 'cheap')}}}


def test_SW06_host_subagents_one_shots_and_the_relay_are_dropped_from_the_seat_preferences():
    prefs, kept, dropped = seats.preferences(_context(['host-subagent-claude', 'claude-cli-oneshot', 'external-relay',
                                                       'codex-cli-worker', 'claude-cli-worker']), _card())
    assert kept == ['codex-cli-worker', 'claude-cli-worker']
    assert prefs['families'] == {_card()['family']: kept}
    assert [d['transport'] for d in dropped] == ['host-subagent-claude', 'claude-cli-oneshot', 'external-relay']
    assert [d['reason'] for d in dropped] == ['transport_kind:host-subagent', 'transport_kind:cli-oneshot',
                                              'transport_kind:external-relay']


def test_a_seat_with_no_admitted_transport_holds_and_names_what_was_dropped():
    with pytest.raises(StepHold) as held:
        seats.preferences(_context(['host-subagent-claude', 'external-relay']), _card())
    assert held.value.reason == 'no_admitted_transport' and len(held.value.evidence['dropped']) == 2
    with pytest.raises(StepHold) as missing:
        seats.preferences({}, _card())
    assert missing.value.reason == 'agent_preferences_missing'


def test_T09_E01_a_transport_without_its_probe_holds_with_the_missing_items_and_no_substitute(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    prefs, _, _ = seats.preferences(_context(['claude-cli-worker']), _card())
    with pytest.raises(StepHold) as held:
        seats.select(_card(), prefs, store=_Unqualified())
    assert held.value.reason == 'transport_unavailable'
    assert held.value.evidence['missing'] and all(not m.startswith('transport_kind') for m in held.value.evidence['missing'])


def test_a_wired_ravel_loop_still_holds_if_its_dispatch_adapter_is_removed(monkeypatch):
    assert 'ravel-loop' in seats.wired_kinds()
    card = _card()
    prefs = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: ['ravel-loop-anthropic']},
             'tier_models': {t: {'ravel-loop-anthropic': 'claude-fixture-model'} for t in tr.TIERS},
             'model_families': {}}
    monkeypatch.setattr(tr, 'select', lambda card, prefs, **k: {'transport_id': 'ravel-loop-anthropic',
                                                                'model': 'claude-fixture-model', 'family': 'anthropic',
                                                                'effort': card['model']['effort']})
    monkeypatch.setattr(seats, 'wired_kinds', lambda: ('cli-worker',))
    with pytest.raises(StepHold) as held:
        seats.select(card, prefs, store=_Unqualified())
    assert held.value.reason == 'transport_adapter_unavailable'
    assert held.value.evidence['selection']['transport_id'] == 'ravel-loop-anthropic'


@pytest.mark.parametrize(('prerequisite', 'reason'), [
    ('qualification', 'qualification'), ('sandbox', 'sandbox_unavailable'),
    ('endpoint', 'endpoint:undeclared'),
])
def test_a_wired_loop_without_its_prerequisites_never_fills_a_blind_seat(
        tmp_path, monkeypatch, prerequisite, reason):
    from ravel.workflow import sandbox
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setattr(sandbox, 'available', lambda: None if prerequisite == 'sandbox' else 'inert-test-seam')
    monkeypatch.setattr(tr, 'sandbox_available', lambda: True)
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('an unavailable loop must not launch'))
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: pytest.fail('no live provider in this control'))
    identity = 'ravel-loop-responses'
    if prerequisite == 'endpoint':
        document = deepcopy(tr.load(identity, installed_only=True))
        document.pop('endpoint')
        load = tr.load
        monkeypatch.setattr(tr, 'load', lambda name, **kwargs: document if name == identity else load(name, **kwargs))
    card = _card('physics-critic')
    assert card['requires']['blind'] is True
    prefs = {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card['family']: [identity]},
             'tier_models': {tier: {identity: 'gpt-fixture-model'} for tier in tr.TIERS}}
    # This calls the real transport selector. A wired adapter cannot substitute
    # for current qualification, host confinement, or a configured endpoint.
    with pytest.raises(StepHold) as held:
        seats.select(card, prefs, store=_Unqualified())
    assert held.value.reason == 'transport_unavailable'
    assert reason in held.value.evidence['missing']


def test_selection_carries_no_family_constraint_for_a_controller_seat(monkeypatch):
    seen = []
    monkeypatch.setattr(tr, 'select', lambda card, prefs, **k: seen.append(card['model']) or
                        {'transport_id': 'claude-cli-worker', 'model': 'm', 'family': 'anthropic', 'effort': None})
    seats.select(_card('ml-reviewer'), {}, store=_Unqualified())
    assert seen[0]['distinct_family_from'] == [] and _card('ml-reviewer')['model']['tier'] == seen[0]['tier']


def _admitted_toolbelt(card):
    """The toolbelt the governed step admits for ``card`` on the restricted worker (as preflight builds it)."""
    from ravel.workflow.transports import cli_worker
    blind = card['id'] in agent_worker.blind_roles()
    card_blind = not blind and (card.get('requires') or {}).get('blind') is True
    belt = cli_worker.toolbelt_for(card, tr.load('claude-cli-worker'), blind,
                                   blind_actions=agent_worker.blind_actions(card) if card_blind else None)
    return {'manifest_sha256': belt['manifest_sha256'], 'tools': sorted(t['name'] for t in belt['tools'])}


def _controller_spec(node='ctl.s1', **changes):
    card = _card()
    value = seats.worker_spec(node_id=node, attempt=1, card=card, card_sha256=role_registry.card_sha256(card['id']),
                              transports=['claude-cli-worker'],
                              inputs=[{'pin': {'path': 'inputs/controller/p.md', 'sha256': '0' * 64},
                                       'as': 'inputs/packet.md'}],
                              outputs=[{'path': 'outputs/result.json', 'kind': 'result', 'required': True}],
                              budgets={'max_turns': 4, 'max_wall_seconds': 60, 'max_broker_calls': 4,
                                       'max_cost_usd': None}, map_id='controller:s1')
    value.update(changes)
    return value


def test_SW06_I03_a_host_adapter_never_fills_a_controller_seat(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'
    run.mkdir()
    with pytest.raises(agent_worker.SeatRefused):
        agent_worker.dispatch(run, _controller_spec(), host_adapter=object())
    legacy = dict(_controller_spec(), final_record_schema='producer.v1')
    with pytest.raises(agent_worker.SeatRefused):
        agent_worker.dispatch(run, legacy, host_adapter=object(), controller={'schema': {}})
    assert not list((tmp_path / 'state').rglob('*.worker.json'))   # nothing was materialized


def test_a_controller_seat_spec_is_launched_only_with_its_launch_facts(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'
    run.mkdir()
    with pytest.raises(agent_worker.SeatRefused):
        agent_worker.launch(run, _controller_spec())
    assert agent_worker.FINAL_SCHEMAS[agent_worker.CONTROLLER_SCHEMA]({'anything': True}) is False


def test_a_controller_final_record_counts_only_against_the_schema_its_descriptor_pinned():
    schema = {'type': 'object', 'required': ['a'], 'properties': {'a': {'const': 1}}}
    facts = {'schema': schema, 'schema_sha256': broker.digest(schema)}
    assert agent_worker._controller_final({'a': 1}, facts) is True
    assert agent_worker._controller_final({'a': 2}, facts) is False
    assert agent_worker._controller_final({'a': 1}, {**facts, 'schema_sha256': '0' * 64}) is False
    assert agent_worker._controller_final({'a': 1}, None) is False


def test_the_cli_adapter_refuses_a_packet_copy_that_differs_from_the_controllers(run_env, inert_worker):
    from ravel.workflow.transports import cli_worker
    run = run_env.run_dir
    packet = run / 'inputs/controller/p.md'
    packet.parent.mkdir(parents=True)
    packet.write_text('packet text')
    value = _controller_spec()
    value['inputs'][0]['pin'] = {'path': 'inputs/controller/p.md', 'sha256': broker.sha(packet)}
    ws = agent_worker.materialize(run, value)
    schema = {'type': 'object'}
    facts = {'schema': schema, 'schema_sha256': tr.digest(schema), 'packet_sha256': '1' * 64,
             'selection': {'transport_id': 'claude-cli-worker', 'model': 'claude-fixture-model', 'effort': 'high'}}
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(run, value, ws, controller=facts)
    assert refused.value.missing == ['controller:packet']
    with pytest.raises(cli_worker.LaunchRefused) as missing:
        cli_worker.prepare_launch(run, value, ws)
    assert missing.value.missing == ['controller:facts']


def test_the_cli_adapter_prompt_is_the_packet_and_the_final_schema_is_the_packets(run_env, inert_worker):
    from ravel.workflow.transports import cli_worker
    run = run_env.run_dir
    packet = run / 'inputs/controller/p.md'
    packet.parent.mkdir(parents=True)
    packet.write_text('ravel-instruction-packet-v1\nthe exact packet text\n')
    value = _controller_spec()
    value['inputs'][0]['pin'] = {'path': 'inputs/controller/p.md', 'sha256': broker.sha(packet)}
    ws = agent_worker.materialize(run, value)
    schema = {'type': 'object', 'properties': {'escalation': {'type': 'array'}}}
    prefs, _, _ = seats.preferences(_context(['claude-cli-worker']), _card())
    facts = {'schema': schema, 'schema_sha256': tr.digest(schema), 'packet_sha256': broker.sha(packet),
             'selection': seats.select(_card(), prefs, store=run_env.store), 'toolbelt': _admitted_toolbelt(_card())}
    descriptor = cli_worker.prepare_launch(run, value, ws, controller=facts)
    prompt = Path(descriptor['transport']['stdin']['path']).read_text()
    assert prompt.startswith('ravel-instruction-packet-v1\nthe exact packet text\n')
    assert 'acknowledgement' in prompt and 'outputs/result.json' in prompt
    argv = descriptor['argv']
    assert json.loads(argv[argv.index('--json-schema') + 1]) == schema
    assert argv[argv.index('--tools') + 1] == '' and '--restricted' in argv and '--strict-mcp-config' in argv
    assert descriptor['transport']['controller']['schema_sha256'] == tr.digest(schema)


def test_CF02_the_cards_stop_limits_bound_the_worker_below_the_executor_default():
    card = _card()
    executors = json.loads((Path(agent_worker.__file__).parents[1] / 'data/roles/executors.json').read_text())
    budgets, applied = cards.worker_budgets(card, {'budget': {}})
    assert budgets['max_wall_seconds'] == card['stop']['max_wall_seconds'] < executors['budgets']['max_wall_seconds']
    assert budgets['max_turns'] == card['stop']['max_turns'] and budgets['max_broker_calls'] == card['stop'][
        'max_broker_calls']
    narrowed, _ = cards.worker_budgets(card, {'budget': {'wall_seconds': 30, 'broker_calls': 5}})
    assert narrowed['max_wall_seconds'] == 30 and narrowed['max_broker_calls'] == 5
    wider, _ = cards.worker_budgets(card, {'budget': {'wall_seconds': 10 ** 6}})
    assert wider['max_wall_seconds'] == card['stop']['max_wall_seconds']   # a share never widens the card
    zero = {**card, 'stop': {**card['stop'], 'max_broker_calls': 0}}
    spec_budgets, applied = cards.worker_budgets(zero, {'budget': {}})
    assert spec_budgets['max_broker_calls'] == 1 and applied['card_broker_calls'] == 0


def test_G01_an_unregistered_role_or_an_alias_never_names_a_seat():
    pin = {'registry_sha256': role_registry.registry_sha256()}
    with pytest.raises(StepHold) as unknown:
        cards.resolve('no-such-role', pin)
    assert unknown.value.reason == 'role_unregistered'
    alias = next(iter(role_registry.registry_document()['aliases']))
    with pytest.raises(StepHold) as aliased:
        cards.resolve(alias, pin)
    assert aliased.value.reason == 'role_alias_not_canonical'
    with pytest.raises(StepHold) as unpinned:
        cards.resolve('baseline-producer', {})
    assert unpinned.value.reason == 'role_registry_unpinned'


def test_SW28_a_registration_dropped_after_intake_changes_nothing_for_the_run(monkeypatch):
    pin = {'registry_sha256': role_registry.registry_sha256()}
    card, card_sha, _ = cards.resolve('baseline-producer', pin)
    assert card_sha == role_registry.card_sha256('baseline-producer')
    real = role_registry.registry_document

    def repointed(**kwargs):
        document = real(**kwargs)
        document['aliases'] = {**document['aliases'], 'fixture-alias': 'baseline-producer'}
        return document
    monkeypatch.setattr(role_registry, 'registry_document', repointed)
    with pytest.raises(StepHold) as changed:
        cards.resolve('baseline-producer', pin)
    assert changed.value.reason == 'role_registry_changed'


def test_the_registry_is_pinned_at_the_first_step_when_intake_named_no_digest(tmp_path):
    store = FakeStore(tmp_path / 'store')
    first = graph.registry_pin(store, {})
    assert first == role_registry.registry_sha256()
    store.entries[0]['record']['registry_sha256'] = '0' * 64
    assert graph.registry_pin(store, {}) == '0' * 64   # later steps compare with the run's first pin
    assert graph.registry_pin(store, {'registry_sha256': 'f' * 64}) == 'f' * 64


@pytest.mark.parametrize('observed, effort, reason', [
    ('claude-fixture-model', 'high', None), ('claude-fixture-model-20261001', 'high', None),
    (None, 'high', 'model_unobserved'), ('claude-other-model', 'high', 'model_substituted'),
    ('claude-fixture-model', 'low', 'effort_substituted')])
def test_I08_the_model_and_effort_that_ran_are_the_ones_the_card_asked_for(observed, effort, reason):
    card = _card()
    record = {'selection': {'model': 'claude-fixture-model', 'effort': effort}}
    result = seats.model_check(card, record, {'model': {'observed': observed}})
    assert result['matches'] is (reason is None) and result.get('reason') == reason
    assert result['tier'] == card['model']['tier'] and result['effort_requested'] == card['model']['effort']


def test_I05_a_seat_session_must_be_fresh_and_transport_attested():
    ok = {'attestation': 'transport_attested', 'session_id': 'sess-a'}
    assert seats.fresh_session_errors(ok, set()) == []
    assert seats.fresh_session_errors(ok, {'sess-a'}) == [{'code': 'session_reused', 'session_id': 'sess-a'}]
    host = {'attestation': 'host_attested', 'session_id': 'sess-b'}
    assert seats.fresh_session_errors(host, set())[0]['code'] == 'session_not_attested'
    assert seats.fresh_session_errors({'attestation': 'transport_attested'}, set()) == [{'code': 'session_missing'}]


def test_CF11_an_exec_tool_in_a_worker_toolbelt_is_refused():
    card = _card()
    assert cards.exec_errors(card, {'tools': [{'name': 'ws_read', 'executes_through': {'action': 'read'}}]}) == []
    assert cards.exec_errors(card, {'tools': [{'name': 'exec', 'executes_through': {'action': 'exec'}}]}) == [
        {'code': 'exec_tool_present', 'role': card['id']}]


def test_worker_node_ids_are_broker_identities_and_never_collide():
    assert spec.worker_node('s1') == 'ctl.s1' and broker.ID.fullmatch(spec.worker_node('s1'))
    a, b = spec.worker_node('a:b'), spec.worker_node('a_b')
    assert a != b and broker.ID.fullmatch(a)
    long = spec.worker_node('x' * 127, 'seat:' + 'r' * 60 + ':1')
    assert len(long) <= 128 and broker.ID.fullmatch(long)


def test_E02_a_transport_dropped_from_the_admitted_set_is_never_probed_or_selected(monkeypatch):
    read = []
    monkeypatch.setattr(tr, 'read_probe', lambda transport_id: read.append(transport_id) or None)
    monkeypatch.setattr(tr, 'resolve_executable', lambda document: (None, None))
    monkeypatch.setattr(tr, 'executor_problem', lambda document: None)
    prefs, kept, dropped = seats.preferences(_context(['codex-cli-worker', 'host-subagent-codex', 'claude-cli-worker']),
                                             _card())
    with pytest.raises(StepHold) as held:
        seats.select(_card(), prefs, store=_Unqualified())
    assert kept == ['codex-cli-worker', 'claude-cli-worker']
    assert read == kept and set(read) <= set(kept) and 'host-subagent-codex' not in read
    assert [d['transport'] for d in dropped] == ['host-subagent-codex']
    assert dropped[0]['reason'] == 'transport_kind:host-subagent'
    assert held.value.reason == 'transport_unavailable' and 'probe' in held.value.evidence['missing']


def test_a_legacy_dispatch_on_a_controller_owned_run_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    run = tmp_path / 'run'
    run.mkdir()
    monkeypatch.setattr(agent_worker, 'controller_run', lambda rundir: 'run-p04-fixture')
    legacy = dict(_controller_spec(), final_record_schema='producer.v1')
    with pytest.raises(agent_worker.SeatRefused):
        agent_worker.launch(run, legacy)
    assert not list((tmp_path / 'state').rglob('*.worker.json'))


def test_the_cli_adapter_refuses_a_toolbelt_other_than_the_one_the_step_admitted(run_env, inert_worker):
    from ravel.workflow.transports import cli_worker
    run = run_env.run_dir
    packet = run / 'inputs/controller/p.md'
    packet.parent.mkdir(parents=True)
    packet.write_text('ravel-instruction-packet-v1\nthe exact packet text\n')
    value = _controller_spec()
    value['inputs'][0]['pin'] = {'path': 'inputs/controller/p.md', 'sha256': broker.sha(packet)}
    ws = agent_worker.materialize(run, value)
    schema = {'type': 'object'}
    prefs, _, _ = seats.preferences(_context(['claude-cli-worker']), _card())
    facts = {'schema': schema, 'schema_sha256': tr.digest(schema), 'packet_sha256': broker.sha(packet),
             'selection': seats.select(_card(), prefs, store=run_env.store),
             'toolbelt': {**_admitted_toolbelt(_card()), 'manifest_sha256': '0' * 64}}
    with pytest.raises(cli_worker.LaunchRefused) as refused:
        cli_worker.prepare_launch(run, value, ws, controller=facts)
    assert refused.value.missing == ['controller:toolbelt']


def test_SW38_the_worker_launch_and_broker_layers_refuse_a_call_outside_every_substrate_node(tmp_path, monkeypatch):
    from ravel.workflow import agent_tripwire
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv(agent_tripwire.ENV, '1')
    run = tmp_path / 'run'
    run.mkdir()
    with pytest.raises(agent_tripwire.TripwireViolation, match='agent_worker.launch'):
        agent_worker.launch(run, _controller_spec(), controller={})
    assert not list((tmp_path / 'state').rglob('*.worker.json'))   # refused before any custody record
    ws = broker.work_root(run) / 'n1' / '1'
    for name in ('inputs', 'outputs', 'scratch', 'calls'):
        (ws / name).mkdir(parents=True)
    tool = broker.Broker(run, ws, node_id='n1', attempt=1, allowed_actions=['write'], max_calls=4)
    with pytest.raises(agent_tripwire.TripwireViolation, match='broker.call'):
        tool.call({'call_id': 'c1', 'action': 'write', 'args': {'path': 'outputs/x', 'content': 'x'}})
    assert not (ws / 'outputs/x').exists()
