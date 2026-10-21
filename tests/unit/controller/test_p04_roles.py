"""Every effective role card field the governed step applies, one case per role and field (ROLE-<role>-<field>).

The cases are enumerated at collection from the installed registry, so a new role or a new card entry
without a case fails here. ``must_check`` cases cover the validators the controller runs itself; the
three delegating Higgs checks and the checks without a computation are the review package's.
"""
from __future__ import annotations

import json

import pytest

from ravel.controller.step import cards, escalation, graph, seats, spec, validate
from ravel.workflow import agent_worker, role_registry, review_projection_checks, run_validator_checks
from ravel.workflow import tool_gate, toolbelt, transport_registry as tr
from ravel.workflow.transports import cli_worker

from test_p04_support import FakeStore

CARDS = {card['id']: card for card in role_registry.all_cards()}
WORKER = tr.load('claude-cli-worker')
REVIEW_PACKAGE_CHECKS = {'check:higgs.measurement_bundle', 'check:higgs.scalar_basis', 'check:higgs.theory_constraints'}
LOW = {'tools': 'none', 'isolation': 'none', 'attestation': 'self', 'structured_output': False, 'blind_capable': False,
       'effort_control': False, 'session_id': False, 'usage_report': False}


def _rows(field):
    return [pytest.param(role, id=f'ROLE-{role}-{field}') for role in sorted(CARDS)]


def _indexed(field, predicate=lambda card, value: True):
    found = []
    for role in sorted(CARDS):
        for index, value in enumerate(CARDS[role][field]):
            if predicate(CARDS[role], value):
                found.append(pytest.param(role, index, value, id=f'ROLE-{role}-{field}-{index}'))
    return found


def _runnable(card, check):
    resolved = role_registry.resolve_self_checks([check])[0]
    computes = getattr(review_projection_checks, 'computes', None)
    if callable(computes) and not computes(resolved):
        return False   # a reviewer item is owed as a reviewer verdict, never run
    return resolved not in REVIEW_PACKAGE_CHECKS and (resolved in run_validator_checks.ADAPTERS
                                                       or resolved in review_projection_checks.CHECKS)


@pytest.fixture(scope='module')
def pin():
    return {'registry_sha256': role_registry.registry_sha256()}


@pytest.mark.parametrize('role', _rows('identity') + _rows('id') + _rows('family'))
def test_ROLE_identity_the_effective_card_is_the_registered_one_under_the_runs_pin(role, pin):
    card, card_sha, registry = cards.resolve(role, pin)
    assert card['id'] == role and card['family'] == CARDS[role]['family']
    assert card_sha == role_registry.card_sha256(role) and registry == pin['registry_sha256']


def _belt(card):
    blind = card['id'] in agent_worker.blind_roles()
    card_blind = not blind and (card.get('requires') or {}).get('blind') is True
    return cli_worker.toolbelt_for(card, WORKER, blind, blind_actions=agent_worker.blind_actions(card) if card_blind
                                   else None)


@pytest.mark.parametrize('role', _rows('dispatch'))
def test_ROLE_dispatch_a_seat_is_a_controller_dispatch_on_an_admitted_route_only(role):
    card = CARDS[role]
    order = ['host-subagent-claude', 'external-relay', 'claude-cli-oneshot', 'claude-cli-worker']
    context = {'agent_preferences': {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': order}}
    _, kept, dropped = seats.preferences(context, card)
    assert kept == ['claude-cli-worker'] and len(dropped) == 3
    worker = seats.worker_spec(node_id=spec.worker_node('s1'), attempt=1, card=card,
                               card_sha256=role_registry.card_sha256(role), transports=kept,
                               inputs=[{'pin': {'path': 'inputs/controller/p.md', 'sha256': '0' * 64},
                                        'as': 'inputs/packet.md'}], outputs=[],
                               budgets=cards.worker_budgets(card, {'budget': {}})[0], map_id='controller:s1')
    assert agent_worker._validate(worker)['final_record_schema'] == agent_worker.CONTROLLER_SCHEMA
    with pytest.raises(agent_worker.SeatRefused):
        agent_worker.dispatch('/nonexistent-run', worker, host_adapter=object())


@pytest.mark.parametrize('role', _rows('model'))
def test_ROLE_model_the_tier_and_effort_requested_are_the_ones_observed(role):
    card = CARDS[role]
    assert cards.model_request(card) == {'tier': card['model']['tier'], 'effort': card['model']['effort']}
    record = {'selection': {'model': 'claude-fixture-model', 'effort': card['model']['effort']}}
    assert seats.model_check(card, record, {'model': {'observed': 'claude-fixture-model'}})['matches'] is True
    assert seats.model_check(card, record, {'model': {'observed': 'claude-cheaper-model'}})['matches'] is False
    other = next(e for e in ('low', 'medium', 'high', 'max') if e != card['model']['effort'])
    assert seats.model_check(card, {'selection': {**record['selection'], 'effort': other}},
                             {'model': {'observed': 'claude-fixture-model'}})['matches'] is False


@pytest.mark.parametrize('role', _rows('requires'))
def test_ROLE_requires_a_route_below_the_cards_minimum_is_refused_before_launch(role):
    card = CARDS[role]
    requires = card['requires']
    expected = set()
    if tr.TOOLS.index(requires['tools']) > 0:
        expected.add('tools')
    if requires['structured_output']:
        expected.add('structured_output')
    if tr.ISOLATION.index(requires['isolation_min']) > 0 or tr.is_voting(card):
        expected.add('isolation')
    if tr.ATTESTATION.index(requires['attestation_min']) > 0:
        expected.add('attestation')
    missing = set(tr.unmet(WORKER, LOW, card))
    if requires['blind']:
        # A blind seat needs a blind-admissible route; an unqualified sandbox worker reads as qualification.
        assert missing & {'blind', 'qualification'}
    assert expected <= missing | {'qualification'}
    assert bool(missing) is bool(expected or requires['blind'])


@pytest.mark.parametrize('role', _rows('stop'))
def test_ROLE_stop_the_cards_limits_bound_the_worker_and_its_reservation(role):
    card = CARDS[role]
    stop = card['stop']
    budgets, applied = cards.worker_budgets(card, {'budget': {}})
    assert budgets['max_turns'] == max(1, stop['max_turns'])
    assert budgets['max_wall_seconds'] == stop['max_wall_seconds'] <= 2700
    assert budgets['max_broker_calls'] == max(1, stop['max_broker_calls'])
    assert applied['card_broker_calls'] == stop['max_broker_calls'] and applied['max_rounds'] == stop['max_rounds']
    wide, _ = cards.worker_budgets(card, {'budget': {'wall_seconds': 10 ** 6, 'broker_calls': 10 ** 6}})
    assert wide == budgets
    amounts = graph._amounts({'budget': {}}, card, 'worker')
    assert amounts['wall_seconds'] == budgets['max_wall_seconds'] and amounts['model_calls'] == budgets['max_turns']


@pytest.mark.parametrize('role', _rows('tools'))
def test_ROLE_tools_the_worker_toolbelt_grants_no_exec_and_only_executable_actions(role):
    card = CARDS[role]
    belt = _belt(card)
    actions = set(toolbelt.allowed_actions(belt['tools']))
    assert cards.exec_errors(card, belt) == []
    # The admitted broker actions, written out: a new executable action is reviewed here before a card may grant it.
    admitted = {'read', 'write', 'knowledge query', 'literature query', 'review-context read', 'check run'}
    assert actions <= admitted and 'exec' not in actions
    assert set(toolbelt.knowledge_ops(belt['tools'])) <= set(card['knowledge']['may_query'])
    if card['tools']['exec_argv_prefixes']:
        assert any(row['tool'] == 'exec' for row in belt['absent'])   # declared, never granted


@pytest.mark.parametrize('role, index, operation', _indexed('operations'))
def test_ROLE_operations_an_action_the_card_does_not_grant_is_denied_by_the_broker(role, index, operation, tmp_path):
    card = CARDS[role]
    belt = _belt(card)
    guard = tool_gate.broker_guard(belt['tools'], rundir=tmp_path)
    granted = {t['executes_through']['action'] for t in belt['tools'] if t['executes_through']['action']}
    if operation in granted:
        tool = next(t for t in belt['tools'] if t['executes_through']['action'] == operation)
        assert toolbelt.match(belt['tools'], operation, {**tool['executes_through']['fixed_args']}) in (tool, None)
    else:
        refusal = guard(operation, {}, tmp_path)
        assert refusal is not None and refusal['code'] == 'not_allowlisted'
    assert guard('exec', {'argv': ['true']}, tmp_path)['code'] == 'not_allowlisted'


@pytest.mark.parametrize('role', _rows('output'))
def test_ROLE_output_declared_outputs_join_the_step_and_the_schema_has_its_controller_form(role):
    card = CARDS[role]
    rows = cards.declared_outputs(card, {'outputs': [{'path': 'outputs/step.json', 'kind': 'result', 'required': True}]})
    paths = {row['path'] for row in rows}
    assert 'outputs/step.json' in paths
    for row in card['output']['declared_outputs']:
        assert spec.worker_path(row['path']) in paths
    assert cards.controller_schema(card) in ('producer.v2', 'findings.v3')
    assert card['output']['sidecar'] in (True, False)


@pytest.mark.parametrize('role', _rows('ownership'))
def test_ROLE_ownership_only_the_owner_sets_its_quantity(role):
    card = CARDS[role]
    owns = card['ownership']['owns']
    for quantity in owns:
        step = {'outputs': [{'path': 'outputs/q.json', 'kind': 'k', 'required': True}],
                'parameters': {'quantities': {'outputs/q.json': quantity}}}
        assert cards.ownership_errors(card, step) == []
    foreign = next(q for q in role_registry.registry_document()['quantity_kinds'] if q not in owns)
    step = {'outputs': [{'path': 'outputs/q.json', 'kind': 'k', 'required': True}],
            'parameters': {'quantities': {'outputs/q.json': foreign}}}
    assert cards.ownership_errors(card, step)[0]['code'] == 'ownership_not_owner'


@pytest.mark.parametrize('role, index, kind', _indexed('escalation'))
def test_ROLE_escalation_the_controller_acts_on_each_value_the_card_declares(role, index, kind, tmp_path):
    card = CARDS[role]
    found, errors = validate.escalation({'escalation': [{'kind': kind, 'statement': 'fixture', 'evidence': []}]}, card)
    assert errors == [] and [f['kind'] for f in found] == [kind]
    store = FakeStore(tmp_path / 'store')
    handled = escalation.handle(store, step={'id': 's1'}, attempt=1, seat=None, escalations=found)
    assert handled['escalation'] == kind and handled['halts'] is (kind in escalation.HALTING)
    action = store.records('step-escalation')[0].get('action')
    assert action == {'stop': 'halt_and_notify', 'checkin_flag': 'checkin_flag', 'decision_block': 'open_rdj_case',
                      'new_experiment_required': 'replan'}[kind]


def _plant(run, check):
    if check == 'check:validation.verify_pack.check_deviations_ledger':
        (run / 'outputs').mkdir(parents=True, exist_ok=True)
        (run / 'outputs/adjusted.json').write_text(json.dumps({'deviations': [{'what': 'an adjustment'}]}))


@pytest.mark.parametrize('role, index, check', _indexed('must_check', _runnable))
def test_ROLE_must_check_the_controller_runs_the_validator_itself_and_refuses_a_defect(role, index, check, tmp_path):
    card = CARDS[role]
    resolved = role_registry.resolve_self_checks([check])[0]
    assert resolved in validate.validator_ids(card)[0]
    single = {**card, 'must_check': [check], 'reviewed_by': [], 'family': 'specialist-review',
              'independence': {**card['independence'], 'kind': 'specialist'}}
    _plant(tmp_path, resolved)
    report = validate.run_validators(single, {'id': 's1'}, run_dir=tmp_path, scratch=tmp_path / 'scratch')
    assert [r['check_id'] for r in report['results']] == [resolved]
    assert report['passed'] is False
