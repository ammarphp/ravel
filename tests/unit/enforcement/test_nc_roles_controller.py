"""Role-card fields against the controller: what each field of an effective card obliges, one case per field.

Every case takes its rows from the effective role registry (``nc_cases.dimension_rows``), so a role, an
escalation value, a stop limit, a reviewer or a check added to a card is covered the day it is installed. The
adversary is a step, a final record, a session or a route that violates what the card declares; the positive
control is the same input made to conform. Oracles are written here from the card's own declaration, the closed
vocabularies and each row's specification, never from the mechanism under test. Cases bound to CONTROLLER end
with the declared ``pending-integration:`` skip while ``ravel.controller`` is not installed; the ``requires``
case runs against the installed transport registry in every tree.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from nc_cases import CONTROLLER, INSTALLED, dimension_case, dimension_rows, require_controller, role_row
from nc_controller import controller_run
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, constant, passes_through, register, returns

# The closed vocabularies the rows are written against (not read from the mechanisms).
ESCALATION_KINDS = ('stop', 'checkin_flag', 'decision_block', 'new_experiment_required')
EFFORTS = ('low', 'medium', 'high', 'max')
SEATLESS_KINDS = ('external-relay', 'host-subagent', 'cli-oneshot')
TOOL_RANKS = ('none', 'broker-readonly', 'broker-full')
ISOLATION_RANKS = ('none', 'cli-policy', 'os-sandbox-readonly', 'ravel-sandbox', 'os-sandbox')
ATTESTATION_RANKS = ('self', 'host', 'transport')
TRAP_SWEEP = 'check:validation.validate_run_state.check_trap_sweep'
TASK_CONTRACT = 'check:validation.validate_task_contract.validate'
DEVIATIONS_LEDGER = 'check:validation.verify_pack.check_deviations_ledger'
MODEL = 'claude-fixture-model'
WORKER = 'claude-cli-worker'


def _name(function, row):
    """The mutation-adequacy identifier of one parameterized row of ``function``."""
    return f'{function.__name__}[{row}]'


# ---------------------------------------------------------------- escalation: every declared value is acted on

# Per value a card may declare: whether the step halts, the side records one raise appends (store kind -> count),
# and the action the run store records for it (a stop halts and notifies; a flag is numbered for the next check-in;
# a decision block opens an RDJ case; a new-experiment request is a replan).
ESCALATION_ACTIONS = {'stop': (True, {}, 'halt_and_notify'),
                      'checkin_flag': (False, {'checkin-flag': 1}, 'checkin_flag'),
                      'decision_block': (True, {'rdj-request': 1}, 'open_rdj_case'),
                      'new_experiment_required': (True, {'replan-request': 1}, 'replan')}
SIDE_RECORDS = ('checkin-flag', 'rdj-request', 'replan-request')


@dimension_case('ROLE', 'escalation', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('escalation',)), ids=str)
def test_role_escalation_value_is_acted_on_by_the_controller_and_an_absent_field_fails_the_step(nc, row):
    validate = require_controller('step.validate')
    escalation = require_controller('step.escalation')
    card, field, index = role_row(row)
    assert field == 'escalation'
    kind = card['escalation'][index]
    assert kind in ESCALATION_KINDS, f'{card["id"]} declares {kind!r}, outside the controller vocabulary'
    halts, side, action = ESCALATION_ACTIONS[kind]
    store, _ = controller_run(nc)

    # The declared value is accepted, and the controller performs the documented action for it, and no other.
    found, errors = validate.escalation({'escalation': [{'kind': kind, 'statement': f'fictional {kind}'}]}, card)
    assert errors == [] and [item['kind'] for item in found] == [kind], (errors, found)
    outcome = escalation.handle(store, step={'id': 's01'}, attempt=1, seat='seat-one', escalations=found)
    assert outcome['escalation'] == kind and outcome['halts'] is halts, outcome
    assert bool(outcome['flags']) is (kind == 'checkin_flag'), outcome
    assert (outcome['replan'] is not None) is (kind == 'new_experiment_required'), outcome
    for record_kind in SIDE_RECORDS:
        assert len(store.scan(record_kind)) == side.get(record_kind, 0), (kind, record_kind)
    recorded = store.scan('step-escalation')
    assert len(recorded) == 1, 'every raised value leaves one record in the run store'
    assert (recorded[0]['record']['kind'], recorded[0]['record']['action']) == (kind, action), recorded
    if kind == 'checkin_flag':
        # A flag is numbered for the next check-in; a second raise by another step gets the next number.
        escalation.handle(store, step={'id': 's02'}, attempt=1, seat='seat-one', escalations=found)
        assert [row_['record']['number'] for row_ in store.scan('checkin-flag')] == [1, 2]
        assert len(store.scan('rdj-request')) == 0 and len(store.scan('replan-request')) == 0

    # A final record without the escalation field fails the step.
    assert validate.escalation({'completed': True}, card) == ([], [{'code': 'escalation_field_missing'}])
    # A value the card does not declare is never acted on; when the card declares all four, a value outside them.
    undeclared = [value for value in ESCALATION_KINDS if value not in card['escalation']]
    attack, code = (undeclared[0], 'escalation_not_declared') if undeclared else ('fictional_escalation',
                                                                                 'escalation_invalid')
    refused, errors = validate.escalation({'escalation': [{'kind': attack, 'statement': 'fictional'}]}, card)
    assert refused == [] and [error['code'] for error in errors] == [code], (attack, errors)
    # Positive control: raising nothing is not an error, and handling nothing does nothing.
    for nothing in ('none', []):
        assert validate.escalation({'escalation': nothing}, card) == ([], [])
    quiet = escalation.handle(store, step={'id': 's03'}, attempt=1, seat='seat-one', escalations=[])
    assert quiet['halts'] is False and quiet['escalation'] is None and quiet['flags'] == []


register(Mutation('M11', 'ravel.controller.step.validate:escalation',
                  passes_through(lambda result, *args, **kwargs: (result[0], [])),
                  (_name(test_role_escalation_value_is_acted_on_by_the_controller_and_an_absent_field_fails_the_step,
                         'ROLE-ablation-critic-escalation-0'),),
                  binding=MUTATION_CONTROLLER, why='a missing or undeclared escalation value is never an error'),
         Mutation('M11', 'ravel.controller.step.escalation:handle',
                  returns(lambda: {'escalation': None, 'replan': None, 'flags': [], 'records': [], 'halts': False}),
                  (_name(test_role_escalation_value_is_acted_on_by_the_controller_and_an_absent_field_fails_the_step,
                         'ROLE-ablation-critic-escalation-1'),),
                  binding=MUTATION_CONTROLLER, why='a raised escalation is recorded and acted on by no one'))


# ---------------------------------------------------------------- stop: the card bounds the worker

@dimension_case('ROLE', 'stop', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('stop',)), ids=str)
def test_role_stop_limits_come_from_the_card_and_a_step_share_only_narrows_them(nc, row):
    cards = require_controller('step.cards')
    card, field, _ = role_row(row)
    assert field == 'stop'
    stop = card['stop']

    def limits(budgets):
        return budgets['max_turns'], budgets['max_wall_seconds'], budgets['max_broker_calls']

    # A step share far above the card never widens it: the worker gets exactly the card's limits.
    wide = {'budget': {'wall_seconds': 10 ** 6, 'broker_calls': 10 ** 6, 'cost_usd': None}}
    budgets, applied = cards.worker_budgets(card, wide)
    assert limits(budgets) == tuple(max(1, stop[key]) for key in ('max_turns', 'max_wall_seconds',
                                                                   'max_broker_calls')), (card['id'], budgets)
    assert applied['card_stop']['max_wall_seconds'] == stop['max_wall_seconds']
    assert applied['max_rounds'] == stop['max_rounds']
    # The limits are read from the card, not from an executor or graph default: other limits, other budgets.
    other = deepcopy(card)
    other['stop'] = dict(stop, max_turns=3, max_wall_seconds=120, max_broker_calls=7)
    assert limits(cards.worker_budgets(other, wide)[0]) == (3, 120, 7)
    # Positive control: a narrower share narrows the card's limits (the lower of the two applies).
    narrow = {'budget': {'wall_seconds': 30, 'broker_calls': 5}}
    narrowed = cards.worker_budgets(card, narrow)[0]
    assert (narrowed['max_wall_seconds'], narrowed['max_broker_calls']) == (min(stop['max_wall_seconds'], 30),
                                                                           min(stop['max_broker_calls'], 5))
    assert narrowed['max_turns'] == max(1, stop['max_turns']), 'a share names no turn limit; the card\'s stands'
    # Cost is bounded by the card where it names one, and by the step share where the card names none.
    cost = cards.worker_budgets(card, {'budget': {'cost_usd': 0.25}})[0]['max_cost_usd']
    assert cost == (0.25 if stop['max_cost_usd'] is None else min(0.25, stop['max_cost_usd']))


def _share_widens(original):
    """The step share replaces the card's wall and broker-call limits when it names them."""
    def worker_budgets(card, step):
        share = step.get('budget') or {}
        widened = deepcopy(card)
        for key, name in (('max_wall_seconds', 'wall_seconds'), ('max_broker_calls', 'broker_calls')):
            if share.get(name) is not None:
                widened['stop'] = dict(widened['stop'], **{key: share[name]})
        return original(widened, step)
    return worker_budgets


register(Mutation('M17', 'ravel.controller.step.cards:worker_budgets', _share_widens,
                  (_name(test_role_stop_limits_come_from_the_card_and_a_step_share_only_narrows_them,
                         'ROLE-ablation-critic-stop'),),
                  binding=MUTATION_CONTROLLER, why='a step share widens the card\'s stop limits'))


# ---------------------------------------------------------------- output: declared outputs and the card schema

# The controller form of each output family: the schema with the instruction acknowledgement, checklist and
# escalation fields. Records valid under the card's own (older) schema, and under the controller form.
CONTROLLER_FORM = {'producer': 'producer.v2', 'findings': 'findings.v3'}
ACK = {'manifest_sha256': 'a' * 64}
LEGACY_RECORDS = {
    'producer.v1': {'schema_version': 1, 'kind': 'producer-result',
                    'outputs': [{'path': 'outputs/result.json', 'kind': 'result'}], 'decisions': [],
                    'knowledge_used': [], 'handoff': None},
    'findings.v1': {'schema_version': 1, 'kind': 'findings', 'items': [], 'handoff': None},
    'findings.v2': {'schema_version': 2, 'kind': 'findings', 'items': [], 'handoff': None}}
CONTROLLER_RECORDS = {
    'producer.v2': {'schema_version': 2, 'kind': 'producer-result',
                    'outputs': [{'path': 'outputs/result.json', 'kind': 'result'}], 'decisions': [],
                    'knowledge_used': [], 'handoff': None, 'instruction_ack': ACK, 'checklist': [], 'escalation': []},
    'findings.v3': {'schema_version': 3, 'kind': 'findings', 'items': [], 'handoff': None, 'instruction_ack': ACK,
                    'checklist': [], 'escalation': [], 'item_verdicts': []}}


def _worker_path(path):
    """Where a worker writes a declared output: under ``outputs/`` of its own workspace."""
    return path if path.startswith('outputs/') else 'outputs/' + path


@dimension_case('ROLE', 'output', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('output',)), ids=str)
def test_role_output_declared_outputs_join_the_step_and_the_final_record_meets_the_card_schema(nc, row):
    cards = require_controller('step.cards')
    validate = require_controller('step.validate')
    from ravel.workflow import toolbelt
    card, field, _ = role_row(row)
    assert field == 'output'
    declared = card['output']['declared_outputs']
    step = {'outputs': [{'path': 'outputs/step-result.json', 'kind': 'result', 'required': True}]}

    # Every output the card declares is a row of the step, required as the card says, beside the step's own.
    expected = {'outputs/step-result.json': ('result', True)}
    expected.update({_worker_path(d['path']): (d['kind'], d['required']) for d in declared})
    rows = cards.declared_outputs(card, step)
    assert {r['path']: (r['kind'], r['required']) for r in rows} == expected, (card['id'], rows)
    # A step cannot make an output its card requires optional, and cannot drop one by not listing it.
    for entry in declared:
        optional = {'outputs': [{'path': entry['path'], 'kind': entry['kind'], 'required': False}]}
        merged = {r['path']: r['required'] for r in cards.declared_outputs(card, optional)}
        assert merged[_worker_path(entry['path'])] is entry['required'], (card['id'], entry, merged)

    # The final record is held to the card's schema in controller form, not to the hard-coded legacy record.
    family = card['output']['schema'].rpartition('.v')[0]
    schema = cards.controller_schema(card)
    assert schema == CONTROLLER_FORM[family], (card['output']['schema'], schema)
    legacy_only = {'completed': True, 'summary': 'fictional result written'}
    assert validate.card_schema_errors(card, legacy_only, schema), 'the legacy completed/summary record is no result'
    older = LEGACY_RECORDS[card['output']['schema']]
    assert toolbelt.validate_final(card, older)[1] == [], 'the attack record satisfies the card\'s own older schema'
    assert validate.card_schema_errors(card, older, schema), 'the older schema alone lacks the acknowledgement fields'
    # Positive control: a record in the controller form is accepted.
    assert validate.card_schema_errors(card, CONTROLLER_RECORDS[schema], schema) == []


def _card_outputs_ignored(original):
    """The step's outputs only: the card's declared outputs are never joined."""
    def declared_outputs(card, step):
        return original({**card, 'output': {**card['output'], 'declared_outputs': []}}, step)
    return declared_outputs


register(Mutation('M11', 'ravel.controller.step.cards:declared_outputs', _card_outputs_ignored,
                  (_name(test_role_output_declared_outputs_join_the_step_and_the_final_record_meets_the_card_schema,
                         'ROLE-detector-calibrator-output'),),
                  binding=MUTATION_CONTROLLER, why='the card\'s declared outputs are not owed'),
         Mutation('M11', 'ravel.controller.step.cards:controller_schema', lambda original: lambda card: card['output']['schema'],
                  (_name(test_role_output_declared_outputs_join_the_step_and_the_final_record_meets_the_card_schema,
                         'ROLE-ablation-critic-output'),),
                  binding=MUTATION_CONTROLLER, why='the final record is held to the older schema, not the controller form'))


# ---------------------------------------------------------------- ownership: only the owner sets its quantity

def _owned_by_other_roles(card):
    from ravel.workflow import role_registry
    mine = set(card['ownership']['owns'])
    return sorted({q for other in role_registry.all_cards() if other['id'] != card['id']
                   for q in other['ownership']['owns']} - mine)


@dimension_case('ROLE', 'ownership', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('ownership',)), ids=str)
def test_role_ownership_refuses_a_quantity_the_role_does_not_own_and_admits_its_own(nc, row):
    cards = require_controller('step.cards')
    card, field, _ = role_row(row)
    assert field == 'ownership'
    owns = list(card['ownership']['owns'])
    consumes = set(card['ownership']['inputs']) | set(card['ownership']['judges'])
    foreign = (_owned_by_other_roles(card) or ['fictional-quantity'])[0]
    assert foreign not in owns

    def step(**quantities):
        paths = [f'outputs/{name}.json' for name in quantities]
        return {'outputs': [{'path': path, 'kind': 'result', 'required': True} for path in paths],
                'parameters': {'quantities': dict(zip(paths, quantities.values()))}}

    # Another role's quantity, and a quantity nobody owns, are refused for this role: one error per output.
    for quantity in (foreign, 'fictional-unowned-quantity'):
        errors = cards.ownership_errors(card, step(a=quantity))
        assert [(e['code'], e['path'], e['quantity'], e['role']) for e in errors] == [
            ('ownership_not_owner', 'outputs/a.json', quantity, card['id'])], (card['id'], errors)
        assert errors[0]['owns'] == sorted(owns), 'the refusal records what the role does own (nothing, if empty)'
    # Only the offending output of a mixed step is refused.
    for own in owns:
        mixed = cards.ownership_errors(card, step(a=own, b=foreign))
        assert [(e['code'], e['path']) for e in mixed] == [('ownership_not_owner', 'outputs/b.json')], mixed
    # An input carrying another role's quantity must be one the card declares it consumes or judges.
    undeclared = next((q for q in [foreign, 'fictional-unowned-quantity'] if q not in consumes))
    custody = [{'artifact': 's0:outputs/a.json', 'quantity': undeclared, 'owner_role': 'fictional-other-role'}]
    errors = cards.ownership_errors(card, step(a=None), custody)
    assert [(e['code'], e['quantity']) for e in errors] == [('ownership_input_undeclared', undeclared)], errors

    # Positive control: its own quantity, no quantity at all, a declared input and its own input are admitted.
    for own in owns:
        assert cards.ownership_errors(card, step(a=own)) == [], (card['id'], own)
    assert cards.ownership_errors(card, step(a=None)) == []
    for quantity in sorted(consumes):
        declared = [{'artifact': 's0:outputs/a.json', 'quantity': quantity, 'owner_role': 'fictional-other-role'}]
        assert cards.ownership_errors(card, step(a=None), declared) == [], (card['id'], quantity)
    mine = [{'artifact': 's0:outputs/a.json', 'quantity': undeclared, 'owner_role': card['id']}]
    assert cards.ownership_errors(card, step(a=None), mine) == []


register(Mutation('M11', 'ravel.controller.step.cards:ownership_errors', returns(lambda: []),
                  (_name(test_role_ownership_refuses_a_quantity_the_role_does_not_own_and_admits_its_own,
                         'ROLE-analysis-author-ownership'),),
                  binding=MUTATION_CONTROLLER, why='any role may set any quantity'))


# ---------------------------------------------------------------- model: the requested tier and effort are compared

@dimension_case('ROLE', 'model', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('model',)), ids=str)
def test_role_model_check_refuses_credit_for_a_substituted_unobserved_or_downgraded_session(nc, row):
    cards, seats = require_controller('step.cards', 'step.seats')
    card, field, _ = role_row(row)
    assert field == 'model'
    tier, effort = card['model']['tier'], card['model']['effort']
    record = {'selection': {'model': MODEL, 'effort': effort}}

    # The tier and effort asked for at dispatch are the card's own, whatever the executor's defaults.
    assert cards.model_request(card) == {'tier': tier, 'effort': effort}
    # Positive control: the model and effort that ran are the ones requested.
    ran = seats.model_check(card, record, {'model': {'observed': MODEL}})
    assert ran['matches'] is True and 'reason' not in ran, ran
    assert ran['tier'] == tier and ran['effort_requested'] == effort and ran['model_observed'] == MODEL, ran
    # Another model answered: credit is refused and the substitution is named.
    substituted = seats.model_check(card, record, {'model': {'observed': 'claude-other-fixture-model'}})
    assert substituted['matches'] is False and substituted['reason'] == 'model_substituted', substituted
    assert substituted['model_requested'] == MODEL and substituted['model_observed'] == 'claude-other-fixture-model'
    # The requested model ran at another effort than the card asks for.
    lower = next(value for value in EFFORTS if value != effort)
    downgraded = seats.model_check(card, {'selection': {'model': MODEL, 'effort': lower}},
                                   {'model': {'observed': MODEL}})
    assert downgraded['matches'] is False and downgraded['reason'] == 'effort_substituted', downgraded
    assert downgraded['effort_requested'] == effort and downgraded['effort_launched'] == lower
    # The receipt names no model at all: nothing observed is never a match.
    for receipt in ({'model': {'observed': None}}, {'model': {}}, {}):
        unobserved = seats.model_check(card, record, receipt)
        assert unobserved['matches'] is False and unobserved['reason'] == 'model_unobserved', (receipt, unobserved)


def _always_matches(original):
    """The check records the request and reports a match whatever ran."""
    def model_check(card, dispatch_record, receipt):
        return {**original(card, dispatch_record, receipt), 'matches': True}
    return model_check


register(Mutation('M06', 'ravel.controller.step.seats:model_check', _always_matches,
                  (_name(test_role_model_check_refuses_credit_for_a_substituted_unobserved_or_downgraded_session,
                         'ROLE-ablation-critic-model'),),
                  binding=MUTATION_CONTROLLER, why='the model and effort that ran are never compared with the card'))


# ---------------------------------------------------------------- independence: fresh session, distinct actors

def _session(session_id, role, actor, *, fresh=True):
    return {'session_id': session_id, 'role': role, 'actor_id': actor, 'fresh': fresh}


@dimension_case('ROLE', 'independence', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('independence',)), ids=str)
def test_role_independence_refuses_a_reused_stale_or_forbidden_actor_session_for_the_seat(nc, row):
    require_controller('store')
    from ravel.workflow import review_independence as independence
    card, field, _ = role_row(row)
    assert field == 'independence'
    role = card['id']
    forbidden = list(card['independence']['distinct_actor_from'])
    # The run so far: a producer, and one session of an actor for every role the card must differ from.
    started = [_session('session-producer', 'fictional-producer', 'actor-producer')]
    started += [_session(f'session-{other}', other, f'actor-{other}') for other in forbidden]

    def refusal(session):
        return independence.seat_refusal(card, session, [*started, session])

    # A session id another seat already holds is never reused.
    assert refusal(_session('session-producer', role, 'actor-new')) == 'session_reused'
    # A resumed session is refused where the card needs a fresh one.
    resumed = _session('session-resumed', role, 'actor-new', fresh=False)
    assert refusal(resumed) == ('session_not_fresh' if card['independence']['fresh_session'] else None)
    # An actor that holds a role in distinct_actor_from in another session is refused, naming the role.
    for other in forbidden:
        assert refusal(_session(f'session-by-{other}', role, f'actor-{other}')) == 'actor_not_distinct:' + other
    # Positive control: a fresh session of a new actor holds the seat, as does an actor of an unnamed role.
    assert refusal(_session('session-new', role, 'actor-new')) is None
    assert refusal(_session('session-other', role, 'actor-producer')) is None


register(Mutation('M16', 'ravel.workflow.review_independence:seat_refusal', returns(None),
                  (_name(test_role_independence_refuses_a_reused_stale_or_forbidden_actor_session_for_the_seat,
                         'ROLE-ablation-critic-independence'),),
                  binding=MUTATION_CONTROLLER, why='a seat session is accepted whatever the card requires'))


# ---------------------------------------------------------------- reviewed_by: the reviewer seat is owed

@dimension_case('ROLE', 'reviewed_by', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('reviewed_by',)), ids=str)
def test_role_reviewed_by_seat_is_owed_before_delivery_whatever_the_plan_lists(nc, row):
    require_controller()
    from ravel.workflow import review_points
    card, field, index = role_row(row)
    assert field == 'reviewed_by'
    reviewers = list(card['reviewed_by'])
    reviewer = reviewers[index]

    # A plan that lists no seat still owes this reviewer: blocking, at the delivery gate.
    owed = review_points.reviewed_by_seats(card['id'], seats=[])
    assert [seat['role'] for seat in owed] == reviewers, owed
    seat = owed[index]
    assert seat['blocking'] is True and seat['gate'] == 'delivery' and seat['count'] == 1, seat
    # A caller-supplied seat list can add seats, never remove the card's reviewers.
    extra = review_points.reviewed_by_seats(card['id'], seats=['fictional-extra-seat'])
    assert [s['role'] for s in extra] == reviewers
    step_graph = require_controller('step.graph')
    assert reviewer in step_graph._seat_roles(None, {'review': []}, card, {}), 'seat derivation adds the reviewer'
    # Positive control: a seat that is held is not owed again (as a role id or as a seat record).
    others = [r for r in reviewers if r != reviewer]
    assert [s['role'] for s in review_points.reviewed_by_seats(card['id'], seats=[reviewer])] == others
    assert [s['role'] for s in review_points.reviewed_by_seats(card['id'], seats=[{'role': reviewer}])] == others
    assert review_points.reviewed_by_seats(card['id'], seats=reviewers) == []


def _plan_seats_replace_the_card(original):
    """A plan that lists any seat is taken as the whole review: the card's reviewers are no longer owed."""
    def reviewed_by_seats(role, seats=()):
        return original(role, seats=seats) if not list(seats) else []
    return reviewed_by_seats


register(Mutation('M15', 'ravel.workflow.review_points:reviewed_by_seats', _plan_seats_replace_the_card,
                  (_name(test_role_reviewed_by_seat_is_owed_before_delivery_whatever_the_plan_lists,
                         'ROLE-analysis-author-reviewed_by-0'),),
                  binding=MUTATION_CONTROLLER, why='a plan that lists a seat removes the card\'s reviewers'),
         Mutation('M15', 'ravel.workflow.review_points:reviewed_by_seats', returns(lambda: []),
                  (_name(test_role_reviewed_by_seat_is_owed_before_delivery_whatever_the_plan_lists,
                         'ROLE-analysis-author-reviewed_by-1'),),
                  binding=MUTATION_CONTROLLER, why='the card\'s reviewer seat is never derived'))


# ---------------------------------------------------------------- must_check: run by the controller or owed as a verdict

def _resolved(check):
    """The validator a card's check id names: a trap reference is the trap-sweep validator."""
    return TRAP_SWEEP if check.startswith('trap:') else check


def _computed(check):
    """Whether any code can pass ``check``: a registered run adapter, or a registered document check that is not
    a reviewer-item placeholder. A placeholder answers ``inconclusive`` with the outcome ``reviewer_item`` whatever
    it is given: nothing computes the item, so only a reviewer's verdict can decide it. Read from the registries,
    never from ``validator_ids``."""
    from ravel.workflow import review_projection_checks as projection, run_validator_checks as run_checks
    if check in run_checks.ADAPTERS:
        return True
    if check not in projection.CHECKS:
        return False
    try:
        return projection.run_check(check, {}).get('outcome') != 'reviewer_item'
    except Exception:  # a check that cannot even read an empty document is still computed code
        return True


def _plant(nc, check):
    """A run directory whose evidence violates ``check`` where one can be built, else an empty one."""
    import json
    run = nc.root / 'subject-run'
    (run / 'inputs').mkdir(parents=True)
    if check == TASK_CONTRACT:
        (run / 'inputs' / 'task_contract.json').write_text(json.dumps({'task_mode': 'fictional-mode'}))
    elif check == DEVIATIONS_LEDGER:
        (run / 'outputs').mkdir()
        (run / 'outputs' / 'adjusted.json').write_text(json.dumps({'deviations': [{'what': 'an adjustment'}]}))
    return run


@dimension_case('ROLE', 'must_check', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('must_check',)), ids=str)
def test_role_must_check_item_is_run_by_the_controller_or_owed_as_a_reviewer_verdict(nc, row):
    import json
    validate = require_controller('step.validate')
    instructions = require_controller('instructions')
    from ravel.workflow import role_registry
    from ravel.validation import validate_run_state
    card, field, index = role_row(row)
    assert field == 'must_check'
    check = card['must_check'][index]
    resolved = _resolved(check)
    # A check some code computes is run by the controller itself; one nothing computes is owed as a reviewer item.
    computed = _computed(resolved)
    runnable, reviewer_only = validate.validator_ids(card)
    where = 'runnable' if resolved in runnable else 'reviewer-only' if resolved in reviewer_only else 'neither'
    expected = 'runnable' if computed else 'reviewer-only'
    assert where == expected, (f'{card["id"]}: {check} is listed as {where} but is '
                               + ('computed by code' if computed else 'computed by no code (a reviewer decides it)')
                               + f', so it belongs with the {expected} checks'
                               + ('' if computed else '; a validator that can never pass rejects the step before review'))

    single = {**card, 'must_check': [check], 'reviewed_by': [], 'family': 'specialist-review',
              'independence': {**card['independence'], 'kind': 'specialist'}}
    run = _plant(nc, resolved)
    report = validate.run_validators(single, {'id': 's01'}, run_dir=run, scratch=nc.root / 'scratch-planted')
    if not computed:
        # The controller runs nothing for it and reports the item as owed to the reviewer.
        assert report['results'] == [] and report['reviewer_items'] == [resolved], report
    else:
        # The controller runs the validator itself over a subject that violates (or never evidences) the check:
        # the report names this check, and it does not pass. A producer's own self-check is not the credit.
        assert [r['check_id'] for r in report['results']] == [resolved], report
        assert report['passed'] is False and report['results'][0]['status'] != 'passed', report
        if resolved == TASK_CONTRACT:
            assert report['results'][0]['status'] == 'failed', report
            good = nc.root / 'good-run'
            (good / 'inputs').mkdir(parents=True)
            contract = validate_run_state._base_contract(task_mode='reproduce', compute_plan='smoke')
            (good / 'inputs' / 'task_contract.json').write_text(json.dumps(contract))
            assert validate.run_validators(single, {'id': 's01'}, run_dir=good,
                                           scratch=nc.root / 'scratch-good')['passed'] is True  # positive control
        elif resolved == DEVIATIONS_LEDGER:
            clean = nc.root / 'clean-run'
            clean.mkdir()
            assert validate.run_validators(single, {'id': 's01'}, run_dir=clean,
                                           scratch=nc.root / 'scratch-clean')['passed'] is True  # positive control

    # The check is also owed as a reviewer item, and a review that skips it earns no credit.
    items = instructions.reviewer_items({'units': []}, card)
    mine = [item for item in items if item['kind'] == 'must_check' and item['check'] == check]
    assert len(mine) == 1, (card['id'], check, [item['id'] for item in items])
    item = mine[0]['id']
    answered = [{'item': i['id'], 'verdict': 'pass', 'evidence': ['outputs/review.json#/checks'], 'note': None}
                for i in items]
    assert instructions.check_item_verdicts(items, {'item_verdicts': answered}) == []  # positive control
    skipped = [v for v in answered if v['item'] != item]
    assert any(e.startswith('missing:') and item in e for e in
               instructions.check_item_verdicts(items, {'item_verdicts': skipped}))
    assert any(e.startswith('missing:') and item in e for e in
               instructions.check_item_verdicts(items, {'item_verdicts': []}))
    bare = [dict(v, evidence=[]) if v['item'] == item else v for v in answered]
    assert any(e.startswith('evidence:') and item in e for e in
               instructions.check_item_verdicts(items, {'item_verdicts': bare}))
    # A producer this card reviews owes the check itself before delivery (the union of its reviewers' checks).
    for producer in role_registry.all_cards():
        if card['id'] in producer['reviewed_by']:
            owed = set(sum(validate.validator_ids(producer), []))
            assert resolved in owed, f'{producer["id"]} does not owe {resolved} reviewed by {card["id"]}'


def _runnable_checks_dropped(original):
    """Every check is reviewer-only: the controller runs none of the validators itself."""
    def validator_ids(card):
        runnable, reviewer_only = original(card)
        return [], sorted(set(runnable) | set(reviewer_only))
    return validator_ids


register(Mutation('M10', 'ravel.controller.step.validate:validator_ids', _runnable_checks_dropped,
                  (_name(test_role_must_check_item_is_run_by_the_controller_or_owed_as_a_reviewer_verdict,
                         'ROLE-ablation-critic-must_check-0'),),
                  binding=MUTATION_CONTROLLER, why='the controller runs no must_check validator itself'),
         Mutation('M14', ('ravel.controller.instructions.ack:check_item_verdicts',
                          'ravel.controller.instructions:check_item_verdicts'),
                  passes_through(lambda errors, *args, **kwargs: [e for e in errors if not e.startswith('missing:')]),
                  (_name(test_role_must_check_item_is_run_by_the_controller_or_owed_as_a_reviewer_verdict,
                         'ROLE-ablation-critic-must_check-0'),),
                  binding=MUTATION_CONTROLLER, why='a review that skips an item is credited'))


# ---------------------------------------------------------------- dispatch: a seat never goes to a seatless route

def _preferences(card, order):
    return {'schema_version': 1, 'kind': 'agent-preferences', 'families': {card.get('family'): list(order)},
            'tier_models': {tier: {transport: MODEL for transport in order} for tier in
                            ('judgment', 'agent', 'cheap')},
            'model_families': {}}


def _declared_transports():
    """``(id, kind)`` of every shipped transport declaration, read from the package data."""
    import json
    from ravel.paths import package_data_path
    found = []
    for path in sorted(package_data_path('transports').glob('*.json')):
        document = json.loads(path.read_text())
        found.append((document['id'], document['transport_kind']))
    return found


def _session_record(session_id, role, transport_kind):
    return {'session_id': session_id, 'seat': role, 'step_id': 's01', 'role': role, 'card_id': role,
            'role_kind': 'reviewer', 'actor_id': 'actor-reviewer', 'model': MODEL, 'transport_id': WORKER,
            'transport_kind': transport_kind, 'fresh': True, 'parent_transcript_supplied': False}


@dimension_case('ROLE', 'dispatch', binding=CONTROLLER)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('dispatch',)), ids=str)
def test_role_dispatch_never_fills_a_controller_seat_from_a_host_relay_or_one_shot_route(nc, row):
    require_controller('store')
    from ravel.workflow import review_dispatch, transport_registry as tr
    card, field, _ = role_row(row)
    assert field == 'dispatch'
    role = card['id']
    declared = _declared_transports()
    seatless = [(transport, kind) for transport, kind in declared if kind in SEATLESS_KINDS]
    assert {kind for _, kind in seatless} == set(SEATLESS_KINDS), 'every seatless kind has a shipped route'

    # A preference list naming only a seatless route is refused, naming the route kind; so is a list of all of them.
    for transport, kind in seatless:
        with pytest.raises(tr.TransportRefusal) as refused:
            tr.select(card, _preferences(card, [transport]), controller=True, qualifications=())
        assert refused.value.missing == ['controller:' + kind], (role, transport, refused.value.missing)
    with pytest.raises(tr.TransportRefusal) as refused:
        tr.select(card, _preferences(card, [transport for transport, _ in seatless]), controller=True,
                  qualifications=())
    assert set(refused.value.missing) == {'controller:' + kind for kind in SEATLESS_KINDS}, refused.value.missing
    # The controller's own filter of the operator's preferences drops each such route; with none left the seat
    # holds, missing, and is never moved to another route.
    seats, services = require_controller('step.seats', 'step.services')
    ids = [transport for transport, _ in seatless]

    def frozen(order):
        return {'agent_preferences': {'schema_version': 1, 'kind': 'agent-preferences', 'transport_preference': order}}

    with pytest.raises(services.StepHold) as held:
        seats.preferences(frozen(ids), card)
    assert held.value.reason == 'no_admitted_transport', held.value.reason
    _, kept, dropped = seats.preferences(frozen([*ids, WORKER]), card)
    assert kept == [WORKER] and {d['transport'] for d in dropped} == set(ids), (kept, dropped)
    assert all(kind in d['reason'] for d in dropped for transport, kind in seatless if transport == d['transport'])
    # A session on such a route never holds the seat: it is not recorded.
    store, _ = controller_run(nc)
    for kind in SEATLESS_KINDS:
        with pytest.raises(ValueError):
            review_dispatch.record_session(store, _session_record(f'session-{kind}', role, kind))
    assert store.scan('review-session') == []
    # Positive control: the restricted worker is refused for no seatless reason, and its session is recorded.
    with pytest.raises(tr.TransportRefusal) as unqualified:
        tr.select(card, _preferences(card, [WORKER]), controller=True, qualifications=())
    assert not [m for m in unqualified.value.missing if m.startswith('controller:')], unqualified.value.missing
    review_dispatch.record_session(store, _session_record('session-worker', role, 'cli-worker'))
    assert [r['record']['session_id'] for r in store.scan('review-session')] == ['session-worker']


register(Mutation('M06', 'ravel.workflow.review_dispatch:SEATLESS_TRANSPORTS', constant(frozenset()),
                  (_name(test_role_dispatch_never_fills_a_controller_seat_from_a_host_relay_or_one_shot_route,
                         'ROLE-ablation-critic-dispatch'),),
                  binding=MUTATION_CONTROLLER, why='a host, relay or one-shot session holds a seat'),
         Mutation('M06', 'ravel.workflow.transport_registry:CONTROLLER_SEATLESS', constant(()),
                  (_name(test_role_dispatch_never_fills_a_controller_seat_from_a_host_relay_or_one_shot_route,
                         'ROLE-analysis-author-dispatch'),),
                  binding=MUTATION_CONTROLLER, why='controller selection accepts relay and host routes'),
         Mutation('M06', 'ravel.controller.step.seats:admitted', lambda original: lambda ids: (list(ids), []),
                  (_name(test_role_dispatch_never_fills_a_controller_seat_from_a_host_relay_or_one_shot_route,
                         'ROLE-physics-critic-dispatch'),),
                  binding=MUTATION_CONTROLLER, why='the preference filter admits every route a seat is offered'))


# ---------------------------------------------------------------- requires: no route below the card's minimum

def _below(ranks, minimum):
    """The rank just below ``minimum``, or None when nothing is lower."""
    position = ranks.index(minimum)
    return ranks[position - 1] if position else None


@dimension_case('ROLE', 'requires', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('requires',)), ids=str)
def test_role_requires_names_each_requirement_a_route_falls_below(nc, row):
    from ravel.workflow import transport_registry as tr
    card, field, _ = role_row(row)
    assert field == 'requires'
    requires = card['requires']
    declared = tr.load(WORKER)
    full = dict(declared['capabilities'])
    # The qualification of the shipped worker is declared only; a qualified copy isolates the card's own minima.
    qualified = deepcopy(declared)
    qualified['qualification'] = {'status': 'live_qualified', 'record': None}
    voting = card['independence']['kind'] == 'voting'

    # Positive control: the worker's own capabilities meet every minimum; a voting seat still needs its
    # qualification, which the declared worker lacks.
    assert tr.unmet(qualified, dict(full), card) == [], (card['id'], requires)
    assert tr.unmet(declared, dict(full), card) == (['qualification'] if voting else [])

    # Each requirement the card declares is named when the route falls below it, and only that one (a blind
    # seat also needs a sandbox, so a route below the isolation minimum is not blind-capable either).
    attacks = []
    lower = _below(TOOL_RANKS, requires['tools'])
    if lower:
        attacks.append(({'tools': lower}, {'tools'}))
    lower = _below(ISOLATION_RANKS, requires['isolation_min'])
    if lower:
        attacks.append(({'isolation': lower}, {'isolation'} | ({'blind'} if requires['blind'] else set())))
    lower = _below(ATTESTATION_RANKS, requires['attestation_min'])
    if lower:
        attacks.append(({'attestation': lower}, {'attestation'}))
    if requires['structured_output']:
        attacks.append(({'structured_output': False}, {'structured_output'}))
    if requires['blind']:
        attacks.append(({'blind_capable': False}, {'blind'}))
    for change, expected in attacks:
        missing = tr.unmet(qualified, {**full, **change}, card)
        assert set(missing) == expected and len(missing) == len(expected), (card['id'], change, missing)
    # Every capability at its floor: a route that offers nothing is below every minimum the card declares.
    floor = {'tools': 'none', 'isolation': 'none', 'attestation': 'self', 'structured_output': False,
             'blind_capable': False, 'effort_control': False, 'session_id': False, 'usage_report': False}
    everything = set().union(*[expected for _, expected in attacks]) if attacks else set()
    assert set(tr.unmet(qualified, floor, card)) == everything | ({'isolation'} if voting else set())


register(Mutation('M08', 'ravel.workflow.transport_registry:unmet', returns(lambda: []),
                  (_name(test_role_requires_names_each_requirement_a_route_falls_below, 'ROLE-ablation-critic-requires'),),
                  why='a route below the card\'s minimum is never refused'))
