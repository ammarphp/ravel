"""Governed-step flow rows: admission, seats, consults, custody and reservations decide from controller facts.

The adversary plans a compute step under a role that is not its production executor, answers two
seats from one session, substitutes a cheaper model, skips a required consult, asks for an exec tool
or another argv than the plan approved, consumes a sibling's output before it exists, copies an
unreceipted output into a stage directory under a forged clock, offers an unknown cost as zero,
reuses a failed or foreign pilot, launches an uncalibrated top rung, swaps a tool version, or asks
for a delegate. Oracles are the step package's own checks and holds over the controller store (and
the plan check before CHECK-IN 1); positive controls pass the same checks with governed values.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sys
import time

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import checkin_view, controller_run, store_root
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

# Tool names (and broker actions) that would let a worker start another agent, a model program or a shell.
DELEGATING = {'task', 'agent', 'delegate', 'spawn', 'spawn_agent', 'subagent', 'run_agent', 'exec', 'bash', 'shell'}
DELEGATING_PREFIXES = ('delegate', 'spawn', 'subagent', 'agent_')


def _installed_compute():
    """An installed compute operation whose production executor is registered: the amplitude
    cross-check where the tree ships it, otherwise the first calculation operation it ships."""
    from nc_cases import _package_json
    signatures = _package_json('operation_signatures.json')['operations']
    executors = _package_json('roles', 'executors.json')['operations']
    if 'amplitude-crosscheck' in signatures:
        return 'amplitude-crosscheck'
    return sorted(name for name, role in executors.items() if role == 'calculation' and name in signatures)[0]


COMPUTE = _installed_compute()
STEP = 'ravel.controller.step'


def _hold(call, *reasons):
    """The typed hold ``call`` raises (its reason is one of ``reasons``); anything else fails the oracle."""
    services = require_controller('step.services')
    try:
        returned = call()
    except services.StepHold as exc:
        assert exc.reason in reasons, (exc.reason, reasons, getattr(exc, 'evidence', None))
        return exc
    except Exception as exc:  # noqa: BLE001 - an untyped failure is not the typed hold the row requires
        raise AssertionError(f'expected a typed hold {reasons}; got {type(exc).__name__}: {str(exc)[:400]}') from None
    raise AssertionError(f'expected a typed hold {reasons}; the call returned {str(returned)[:300]}')


def _step(step_id, kind='derive', *, role='calculation', **fields):
    step = {'id': step_id, 'kind': kind, 'role': role, 'inputs': [], 'depends_on': [],
            'outputs': [{'path': f'outputs/{step_id}.json', 'kind': 'result', 'required': True}],
            'waypoint': False, 'rung': None, 'budget': {}, 'protocols': [], 'review': [], 'instruction_sources': [],
            'obligations': [], 'parameters': {}}
    step.update(fields)
    return step


def _compute_step(step_id='s05', *, rung='full', **fields):
    launch = {'argv': [sys.executable, '-c', "print('inert')"], 'cpus': 1}
    return _step(step_id, 'operate', operation=COMPUTE, rung=rung, budget={'wall_seconds': 60, 'events': 10},
                 parameters={'launch': launch, 'process_sha256': 'c' * 64}, **fields)


def _context(nc, store, run_dir, **extra):
    return {'run_id': store.run_id, 'store_root': str(store_root(nc)), 'run_dir': str(run_dir), 'attempt': 1, **extra}


def _plan_record(store, steps):
    """The approved plan in the store, as the controller pins it at CHECK-IN 1."""
    body = {'kind': 'fictional-plan', 'steps': deepcopy(steps)}
    sha = require_controller('step.services').digest(body)  # the controller's canonical plan digest
    document = dict(body, sha256=sha)
    blob = store.put_blob(json.dumps(document, sort_keys=True).encode())
    store.append('plan', {'schema_version': 1, 'plan_sha256': sha, 'blob': blob})
    return sha


# ---------------------------------------------------------------- R13 executor role

@case('R13', binding=CONTROLLER)
def test_R13_a_compute_step_without_its_production_executor_is_refused_before_approval_and_at_dispatch(nc):
    operations = require_controller('step.operations')
    planning = require_controller('judgment.planning')
    from test_nc_judgment_protocols import _frame, _plan, _step as _plan_step_row
    table = operations.executors()
    required = table['operations'][COMPUTE]
    # Dispatch: the step names another role, or the table has no executor for the operation.
    wrong = _compute_step(role='analysis-author')
    assert [e['code'] for e in operations.executor_errors(wrong)] == ['executor_role_mismatch']
    unmapped = dict(table, operations={k: v for k, v in table['operations'].items() if k != COMPUTE})
    assert [e['code'] for e in operations.executor_errors(_compute_step(role=None), table=unmapped)] == \
        ['executor_role_missing']
    assert operations.executor_errors(_compute_step(role=required)) == []  # positive control
    # Before approval: the plan the CHECK-IN 1 view is rendered from cannot carry the substitute executor.
    frame = _frame('a' * 64)
    plan = _plan(frame, [_plan_step_row('s1', 'operate', operation=COMPUTE, role='analysis-author'),
                         _plan_step_row('s2')])
    plan['frame_sha256'] = planning.digest(frame)
    problems = planning.check_plan(plan, frame, operations={COMPUTE}, routes=set(), roles=None)
    assert any('executor' in p for p in problems), (
        'the plan check admits a compute step under a role that is not its production executor', problems)


register(Mutation('M06', f'{STEP}.operations:executor_errors', lambda original: lambda *a, **k: [], ('R13',),
                  binding=MUTATION_CONTROLLER, why='any role runs any compute operation'))


# ---------------------------------------------------------------- I05, I08, T09 seats

@case('I05', binding=CONTROLLER)
def test_I05_one_worker_session_cannot_answer_two_seats_and_is_never_credited(nc):
    seats = require_controller('step.seats')
    from ravel.workflow import review_independence as independence
    from test_nc_review_credit import _recorded
    seen = {'session-producer'}
    reused = {'attestation': 'transport_attested', 'session_id': 'session-producer'}
    assert [e['code'] for e in seats.fresh_session_errors(reused, seen)] == ['session_reused']
    unattested = {'attestation': 'self_attested', 'session_id': 'session-other'}
    assert [e['code'] for e in seats.fresh_session_errors(unattested, seen)] == ['session_not_attested']
    assert [e['code'] for e in seats.fresh_session_errors({'attestation': 'transport_attested'}, seen)] == \
        ['session_missing']
    fresh = {'attestation': 'transport_attested', 'session_id': 'session-critic'}
    assert seats.fresh_session_errors(fresh, seen) == []  # positive control
    # The producer's session recorded on the critic seat is uncredited by the one credit decision.
    _, _, query = _recorded(nc, name='nc-run-reused', reviewer_session='session-producer')
    assert independence.decide(query)['independent'] is False


register(Mutation('M06', f'{STEP}.seats:fresh_session_errors', lambda original: lambda *a, **k: [], ('I05',),
                  binding=MUTATION_CONTROLLER, why='a seat session is never compared with the run\'s earlier sessions'))


@case('I08', binding=CONTROLLER)
def test_I08_a_substituted_model_or_effort_refuses_credit(nc):
    seats = require_controller('step.seats')
    from ravel.workflow import role_registry
    card = role_registry.load('calculation')
    effort = card['model']['effort']
    dispatched = {'selection': {'model': 'claude-opus-5-5', 'effort': effort}}
    for observed, reason in (('claude-haiku-5-5', 'model_substituted'), (None, 'model_unobserved')):
        result = seats.model_check(card, dispatched, {'model': {'observed': observed}})
        assert result['matches'] is False and result['reason'] == reason, result
    lowered = {'selection': {'model': 'claude-opus-5-5', 'effort': 'low' if effort != 'low' else 'medium'}}
    result = seats.model_check(card, lowered, {'model': {'observed': 'claude-opus-5-5'}})
    assert result['matches'] is False and result['reason'] == 'effort_substituted', result
    # Positive control: a dated release of the requested model at the requested effort matches.
    assert seats.model_check(card, dispatched, {'model': {'observed': 'claude-opus-5-5-20261001'}})['matches'] is True


register(Mutation('M06', f'{STEP}.seats:model_matches', lambda original: lambda requested, observed: True, ('I08',),
                  binding=MUTATION_CONTROLLER, why='the observed model is never compared with the requested one'))


@case('T09', binding=CONTROLLER)
def test_T09_a_missing_or_unadmitted_transport_holds_the_step_before_any_substitute(nc):
    seats = require_controller('step.seats')
    from ravel.workflow import role_registry
    card = role_registry.load('calculation')
    _hold(lambda: seats.preferences({}, card), 'agent_preferences_missing')
    frozen = {'kind': 'agent-preferences', 'schema_version': 1,
              'transport_preference': ['fictional-transport', 'claude-cli-oneshot']}
    held = _hold(lambda: seats.preferences({'agent_preferences': frozen}, card), 'no_admitted_transport')
    dropped = {row['transport']: row['reason'] for row in held.evidence['dropped']}
    assert dropped == {'fictional-transport': 'undeclared', 'claude-cli-oneshot': 'transport_kind:cli-oneshot'}
    # Positive control: an admitted worker transport is kept, and only it.
    frozen['transport_preference'].append('claude-cli-worker')
    _, kept, _ = seats.preferences({'agent_preferences': frozen}, card)
    assert kept == ['claude-cli-worker']


register(Mutation('M06', f'{STEP}.seats:admitted', lambda original: lambda ids: (list(ids), []), ('T09',),
                  binding=MUTATION_CONTROLLER, why='every declared transport may fill a controller seat'))


# ---------------------------------------------------------------- CF04 consults

def _consult_rows():
    from ravel.workflow import consults
    binding = next(b for b in consults.bindings()['consults'].values() if b['tools'])
    role = binding['role']
    rows = [{'when': when, 'role': role} for when in ('before_first_smoke', 'on_use', 'failure', 'contested_node')]
    return role, binding['tools'][0], {'id': 'fictional-card', 'knowledge': {'consult': rows}}


@case('CF04', binding=CONTROLLER)
def test_CF04_a_fired_consult_trigger_requires_its_consult_and_a_missing_one_holds_the_step(nc):
    cards = require_controller('step.cards')
    graph = require_controller('step.graph')
    role, tool, card = _consult_rows()
    smoke = _step('s04', rung='smoke')
    expected = {
        'before_first_smoke': (smoke, {'smoke_done': False}),
        'on_use': (_step('s04'), {'operation_tools': [tool]}),
        'failure': (_step('s04'), {'prior_failure': True}),
        'contested_node': (_step('s04'), {'contested': True}),
    }
    for when, (step, facts) in expected.items():
        assert cards.consult_triggers(card, step, facts) == [{'role': role, 'when': when}], when
    assert cards.consult_triggers(card, smoke, {'smoke_done': True}) == []
    # The consult the trigger requires did not complete: the step holds.
    store, run_dir = controller_run(nc)
    state = {'context': _context(nc, store, run_dir), 'step': smoke, 'acting': smoke, 'results': {},
             'preflight': {'consults_pending': [{'role': role, 'when': 'before_first_smoke'}]}}
    _hold(lambda: graph.consult_join(state), 'consult_missing')
    # Positive control: a completed consult record is written into the packet and recorded once.
    record = {'kind': 'consult-record', 'summary': 'fictional advice'}
    state['results'] = {f'consult:{role}:1': {'results': {'seat': {'status': 'completed', 'record': record,
                                                                   'receipt_sha256': 'd' * 64}}}}
    joined = graph.consult_join(state)
    assert [r['role'] for r in joined['consult']['records']] == [role]
    assert joined['evaluations']['CF04']['status'] == 'satisfied'


register(Mutation('M06', f'{STEP}.cards:consult_triggers', lambda original: lambda *a, **k: [], ('CF04',),
                  binding=MUTATION_CONTROLLER, why='no consult trigger ever fires'))


# ---------------------------------------------------------------- CF11, E01 exec and approved bytes

@case('CF11', binding=CONTROLLER)
def test_CF11_no_exec_tool_reaches_a_worker_and_a_launch_runs_only_the_approved_argv(nc):
    cards = require_controller('step.cards')
    operations = require_controller('step.operations')
    from ravel.workflow import role_registry, transport_registry as tr
    from ravel.workflow.transports import cli_worker
    card = role_registry.load('calculation')
    forged = {'tools': [{'name': 'exec'}], 'manifest_sha256': 'e' * 64}
    assert [e['code'] for e in cards.exec_errors(card, forged)] == ['exec_tool_present']
    hidden = {'tools': [{'name': 'run_check', 'executes_through': {'action': 'exec'}}]}
    assert [e['code'] for e in cards.exec_errors(card, hidden)] == ['exec_tool_present']
    belt = cli_worker.toolbelt_for(card, tr.load('claude-cli-worker'), False)
    assert cards.exec_errors(card, belt) == [], 'the installed worker toolbelt has no exec tool'  # positive control
    # A launch whose argv differs from the approved plan step is a plan change, refused before it starts.
    store, run_dir = controller_run(nc)
    approved = _compute_step()
    sha = _plan_record(store, [approved])
    context = _context(nc, store, run_dir, plan_sha256=sha)
    other = deepcopy(approved)
    other['parameters']['launch']['argv'] = [sys.executable, '-c', "print('a different program')"]
    _hold(lambda: operations.plan_step(store, other, context), 'plan_step_changed')
    assert operations.plan_step(store, approved, context)[0] == approved  # positive control


def _any_bytes_approved(original):
    def plan_step(store, step, context):
        plan = original.__globals__['current_plan'](store, context)
        return deepcopy(step), plan['sha256'], 'plan_step'
    return plan_step


register(Mutation('M07', f'{STEP}.cards:exec_errors', lambda original: lambda *a, **k: [], ('CF11',),
                  binding=MUTATION_CONTROLLER, why='a toolbelt with an exec tool reaches the worker'),
         Mutation('M08', f'{STEP}.operations:plan_step', _any_bytes_approved, ('CF11', 'E01'),
                  binding=MUTATION_CONTROLLER, why='a launch runs whatever bytes the step carries now'))


@case('E01', binding=CONTROLLER)
def test_E01_a_substituted_tool_version_is_a_plan_change_that_needs_renewed_authority(nc):
    operations = require_controller('step.operations')
    authority = require_controller('authority')
    store, run_dir = controller_run(nc, mode='autonomous')
    approved = _compute_step()
    approved['parameters']['tool_version'] = '1.0.0'
    sha = _plan_record(store, [approved])
    view = checkin_view(store, 'approve_plan', plan_sha256=sha)
    ci1 = authority.request(store, 'approve_plan', {'view': view}, {'rung': 'full'})
    assert ci1.get('decision') == 'approve', ci1
    # The required runtime is missing; the worker swaps in another version of the tool.
    swapped = deepcopy(approved)
    swapped['parameters']['tool_version'] = '0.9.0'
    _hold(lambda: operations.plan_step(store, swapped, _context(nc, store, run_dir, plan_sha256=sha)),
          'plan_step_changed')
    swapped_sha = _plan_record(store, [swapped])
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(store, {'id': 'nc-swap', 'rung': 'smoke', 'pins': {'plan_sha256': swapped_sha},
                                           'requires_go': False})
    # Positive control: a disclosed deviation renews authority for the changed plan.
    change = {'parameter': 'tool version', 'from': '1.0.0', 'to': '0.9.0', 'why': 'the required runtime is missing',
              'touches': ['s05'], 'direction': 'input'}
    deviation_view = checkin_view(store, 'deviation', approve_plan=ci1['id'], plan_sha256=swapped_sha,
                                  previous_plan_sha256=sha)
    renewed = authority.request(store, 'deviation', {'view': deviation_view, 'change': change}, {'rung': 'full'})
    assert renewed.get('decision') == 'approve', renewed
    granted = authority.authorize_effect(store, {'id': 'nc-swap', 'rung': 'smoke', 'pins': {'plan_sha256': swapped_sha},
                                                 'requires_go': False})
    assert granted['deviation'] == renewed['id']
    assert operations.plan_step(store, swapped, _context(nc, store, run_dir, plan_sha256=swapped_sha))[0] == swapped


# ---------------------------------------------------------------- C19, T06 custody

def _drop_unreceipted(original):
    def input_errors(store, step, run_dir, *, ancestors=()):
        errors, found, run_inputs = original(store, step, run_dir, ancestors=ancestors)
        return [e for e in errors if e['code'] != 'predecessor_unreceipted'], found, run_inputs
    return input_errors


@case('C19', binding=CONTROLLER)
def test_C19_a_future_sibling_output_cannot_be_declared_as_an_input_without_its_receipt(nc):
    custody = require_controller('step.custody')
    from test_nc_step import _adopted
    store, run_dir = controller_run(nc)
    consumer = _step('s02', depends_on=['s01'], inputs=[{'artifact': 's03:outputs/s03.json'}])
    codes = [e['code'] for e in custody.input_errors(store, consumer, run_dir)[0]]
    assert codes == ['predecessor_unreceipted'], codes
    # Positive control: once the producer's output is adopted and accepted, a dependent consumer reads it.
    accepted = _adopted(nc, store, run_dir, _step('s03'), {'outputs/s03.json': '{"value": 3}'})
    reader = _step('s04', depends_on=['s03'], inputs=[{'artifact': accepted[0]['artifact']}])
    assert custody.input_errors(store, reader, run_dir)[0] == []


@case('T06', binding=CONTROLLER)
def test_T06_an_output_copied_into_a_stage_directory_under_a_forged_clock_is_not_a_launch_output(nc):
    custody = require_controller('step.custody')
    from test_nc_step import _adopted
    store, run_dir = controller_run(nc)
    started = time.time_ns()
    nc.patch.setenv('WORKFLOW_STATE_UTC', '2001-01-01T00:00:00Z')
    copied = run_dir / custody.destination('s01', 'outputs/s01.json')
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_text('{"value": 999}')
    assert 's01:outputs/s01.json' not in custody.custody_index(store), 'no launch of the controller produced it'
    consumer = _step('s02', depends_on=['s01'], inputs=[{'artifact': 's01:outputs/s01.json'}])
    assert [e['code'] for e in custody.input_errors(store, consumer, run_dir)[0]] == ['predecessor_unreceipted']
    # The controller's journal keeps its own clock: a record written now carries now.
    accepted = _adopted(nc, store, run_dir, _step('s05'), {'outputs/s05.json': '{"value": 5}'})
    entries = [e for e in store.scan('custody') if (e.get('record') or {}).get('artifact') == accepted[0]['artifact']]
    assert entries and all(e['time_ns'] >= started for e in entries), entries
    reader = _step('s06', depends_on=['s05'], inputs=[{'artifact': accepted[0]['artifact']}])
    assert custody.input_errors(store, reader, run_dir)[0] == []  # positive control


register(Mutation('M09', f'{STEP}.custody:input_errors', _drop_unreceipted, ('C19', 'T06'),
                  binding=MUTATION_CONTROLLER, why='an input without a custody record is consumed'))


# ---------------------------------------------------------------- C12, C13, C02 reservations

def _amounts(**values):
    from test_nc_budget import amounts
    return amounts(**values)


@case('C12', binding=CONTROLLER)
def test_C12_an_unknown_cost_is_never_reserved_as_zero(nc):
    budget = require_controller('step.budget')
    from test_nc_budget import CEILINGS
    store, _ = controller_run(nc, mode='autonomous')
    ceilings = dict(CEILINGS, core_hours=2)
    held = _hold(lambda: budget.reserve(store, step_id='s05', attempt=1, amounts=_amounts(core_hours=None),
                                        ceilings=ceilings), 'budget_unknown_request')
    assert [r['dimension'] for r in held.evidence['refused']] == ['core_hours']
    assert store.scan('budget-reservation') == []
    # A dimension without a configured ceiling is unbounded and reported as unknown, never as zero.
    record = budget.reserve(store, step_id='s06', attempt=1, amounts=_amounts(tokens=None), ceilings=ceilings)
    totals = budget.totals(store, ceilings)
    assert totals['tokens']['unknown'] == 1 and totals['tokens']['ceiling'] is None, totals['tokens']
    # An observed outcome with no measurement is charged its whole reservation, not zero.
    budget.settle(store, record['key'], status='settled', measured={'wall_seconds': None})
    assert budget.totals(store, ceilings)['model_calls']['charged'] == 1
    budget.reserve(store, step_id='s07', attempt=1, amounts=_amounts(core_hours=1), ceilings=ceilings)  # positive


def _unknown_as_zero(original):
    def reserve(store, **kw):
        kw['amounts'] = {d: (0 if v is None else v) for d, v in kw['amounts'].items()}
        return original(store, **kw)
    return reserve


register(Mutation('M17', f'{STEP}.budget:reserve', _unknown_as_zero, ('C12',), binding=MUTATION_CONTROLLER,
                  why='an unknown amount is reserved as zero'))


@case('C13', binding=CONTROLLER)
def test_C13_a_failed_or_foreign_pilot_never_calibrates_a_production_cost(nc):
    budget = require_controller('step.budget')
    store, _ = controller_run(nc, mode='autonomous')
    production = _compute_step()
    pilot = _compute_step('s04', rung='pilot')
    budget.record_calibration(store, pilot, status='failed', measured={'events': 10, 'wall_seconds': 5})
    store.append(budget.CALIBRATION, {'schema_version': 1, 'kind': budget.CALIBRATION, 'step_id': 's04',
                                      'operation': COMPUTE, 'process_sha256': budget.process_pin(production),
                                      'machine_sha256': 'f' * 64, 'rung': 'pilot', 'status': 'succeeded',
                                      'measured': {'events': 10, 'wall_seconds': 5}})
    assert budget.calibration(store, production) is None
    assert [e['code'] for e in budget.calibration_errors(store, production)] == ['uncalibrated_top_rung_cost']
    # Positive control: a succeeded pilot of the same process on this machine calibrates the cost.
    budget.record_calibration(store, pilot, status='succeeded', measured={'events': 10, 'wall_seconds': 5})
    assert budget.calibration(store, production) is not None
    assert budget.calibration_errors(store, production) == []


def _any_pilot(original):
    def calibration(store, step):
        rows = [r for r in original.__globals__['records'](store, original.__globals__['CALIBRATION'])
                if r.get('operation') == step.get('operation')]
        return rows[-1] if rows else None
    return calibration


register(Mutation('M17', f'{STEP}.budget:calibration', _any_pilot, ('C13',), binding=MUTATION_CONTROLLER,
                  why='any earlier pilot of the operation calibrates production, failed or foreign'))


@case('C02', binding=CONTROLLER)
def test_C02_an_uncalibrated_top_rung_cost_holds_without_the_physicists_own_signoff(nc):
    graph = require_controller('step.graph')
    budget = require_controller('step.budget')
    store, run_dir = controller_run(nc, mode='autonomous')
    step = _compute_step()
    (run_dir / 'inputs').mkdir(exist_ok=True)
    (run_dir / 'inputs' / 'human_signoff.json').write_text(json.dumps({'step': 's05', 'signed_by': 'physicist',
                                                                          'decision': 'admit'}))
    state = {'context': _context(nc, store, run_dir), 'step': step}
    # Observe the refusal before calibration; assert its intended cause after the positive control.
    try:
        graph.reserve(state)
    except Exception as exc:
        refused = exc
    else:
        raise AssertionError('uncalibrated production was reserved without human signoff')
    assert store.scan(budget.RESERVATION) == [], 'nothing is reserved for the uncalibrated top rung'
    # Positive control: a succeeded pilot of the same process on this machine admits the reservation.
    budget.record_calibration(store, _compute_step('s04', rung='pilot'), status='succeeded',
                              measured={'events': 10, 'wall_seconds': 5})
    reserved = graph.reserve(state)
    assert reserved['reservation']['record_id'] and reserved['evaluations']['C02']['status'] == 'satisfied'
    assert getattr(refused, 'reason', None) in ('awaiting_authority', 'uncalibrated_top_rung_cost'), (
        'SOURCE-GAP C02 P04/P06: production cost signoff must retain its compiler/reading view',
        type(refused).__name__, str(refused), getattr(refused, 'evidence', None))


register(Mutation('M17', f'{STEP}.budget:calibration_errors', lambda original: lambda *a, **k: [], ('C02', 'C13'),
                  binding=MUTATION_CONTROLLER, why='a top-rung cost is reserved without calibration or signoff'))


# ---------------------------------------------------------------- I03 delegates and capacity

@case('I03', binding=CONTROLLER)
def test_I03_a_worker_has_no_delegate_or_model_program_and_one_short_capacity_holds_before_dispatch(nc):
    budget = require_controller('step.budget')
    environment = require_controller('confine.environment')
    from ravel.workflow import role_registry, transport_registry as tr
    from ravel.workflow.transports import cli_worker
    from test_nc_budget import CEILINGS
    tools, document = [], tr.load('claude-cli-worker')
    for card in role_registry.all_cards():
        tools += cli_worker.toolbelt_for(card, document, False).get('tools', [])
    assert tools, 'the installed cards receive toolbelts'
    delegating = sorted({t['name'] for t in tools
                         if t['name'].lower() in DELEGATING or t['name'].lower().startswith(DELEGATING_PREFIXES)
                         or (t.get('executes_through') or {}).get('action') in DELEGATING})
    assert delegating == [], delegating
    env, removed = environment.scrub({'PATH': '/usr/bin:/bin', 'ANTHROPIC_API_KEY': 'nc-fictional',
                                      'OPENAI_API_KEY': 'nc-fictional', 'CLAUDE_CODE_OAUTH_TOKEN': 'nc-fictional'})
    assert set(removed) >= {'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN'} and 'PATH' in env
    store, _ = controller_run(nc, mode='autonomous')
    ceilings = dict(CEILINGS, children=2)
    for n in (1, 2):
        budget.reserve(store, step_id=f's0{n}', attempt=1, amounts=_amounts(), ceilings=ceilings)  # positive
    held = _hold(lambda: budget.reserve(store, step_id='s03', attempt=1, amounts=_amounts(), ceilings=ceilings),
                 'budget_exhausted')
    assert [r['dimension'] for r in held.evidence['refused']] == ['children']
