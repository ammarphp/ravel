"""Authority-flow rows: CHECK-IN 2, deviations, R3, steering and the final disposition decide from the
controller store only, bound to the current pins.

The adversary replays an old GO, answers ADJUST and launches anyway, attaches a GO to a stage that
already started, changes an approved input, loosens a control with a note in the run tree, asks
ordinary delegation for an R3 action, widens its own policy, treats a steering acknowledgement or the
final disposition as plan approval, tampers with the displayed check-in, or approves from a
pseudo-terminal. Oracles are the authority service's gates (``verify``, ``current``,
``authorize_effect``, ``effective_bounds``, ``deviations``) over the controller store; each positive
control obtains the same effect through the legitimate decision.
"""
from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import os
import re
import subprocess
import sys

import pytest

from nc_cases import CONTROLLER, case, require_controller
from nc_controller import capture_view, checkin_view, controller_run, operator
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, register

PLAN, PLAN_TWO = 'a' * 64, 'e' * 64
WAYPOINT, WAYPOINT_TWO, WAYPOINT_LEGACY = '1' * 64, '2' * 64, '3' * 64
SERVICE = 'ravel.controller.authority.service'
PACKAGE = 'ravel.controller.authority'
TIGHTEN = {'parameter': 'closure tolerance', 'from': '0.10', 'to': '0.05', 'why': 'the fictional pilot is precise',
           'touches': ['s03'], 'direction': 'tighten'}
LOOSEN = dict(TIGHTEN, **{'from': '0.05', 'to': '0.20', 'why': 'the fictional closure failed', 'direction': 'loosen'})
STEERING_SECTIONS = [{'id': 'preamble', 'title': 'Preamble', 'lines': ['The operator steers the run.']},
                     {'id': 'policy', 'title': 'Policy', 'lines': ['Lower the fictional ceilings.']}]


def _ci1(authority, store, plan=PLAN, rung='full', view=None, **subject):
    view = view or checkin_view(store, 'approve_plan', plan_sha256=plan)
    return _request_answered(authority, store, 'approve_plan', {'view': view, **subject}, {'rung': rung})


def _go(authority, store, ci1, waypoint=WAYPOINT):
    pins = {'approve_plan': ci1['id'], 'waypoint_sha256': waypoint}
    amended = authority.current(store, 'deviation')
    if amended is not None:
        pins.update(plan_sha256=amended['subject']['pins']['plan_sha256'], deviation=amended['id'])
    view = checkin_view(store, 'go', **pins)
    return _request_answered(authority, store, 'go', {'view': view}, {'rung': ci1['bounds']['rung']})


def _deviation_subject(store, ci1, change, plan=PLAN_TWO, previous=PLAN):
    view = checkin_view(store, 'deviation', approve_plan=ci1['id'], plan_sha256=plan, previous_plan_sha256=previous)
    return {'view': view, 'change': dict(change)}


def _deviation(authority, store, ci1, change, plan=PLAN_TWO, previous=PLAN):
    return _request_answered(authority, store, 'deviation', _deviation_subject(store, ci1, change, plan, previous), {'rung': 'full'})


def _steer(authority, store, policy):
    view = {'run_id': store.run_id, 'pins': {'mode_record': authority.frozen(store)['id']},
            'sections': deepcopy(STEERING_SECTIONS)}
    view = capture_view(store, 'steering', view)
    return _request_answered(authority, store, 'steering', {'view': view, 'policy': policy}, {})


def _effect(rung='smoke', plan=PLAN, waypoint=None, **extra):
    effect = {'id': 'nc-effect', 'rung': rung, 'pins': {'plan_sha256': plan}, **extra}
    if waypoint is None:
        effect['requires_go'] = False
    else:
        effect['go_pins'] = {'waypoint_sha256': waypoint}
    return effect


def _granted(record, decision, label=None):
    assert 'pending' not in record and record.get('decision') == decision, record
    assert label is None or record['label'] == label, record
    return record


def _held(result, reason=None):
    assert 'pending' in result and 'id' not in result, result
    pending = result['pending']
    if reason is not None:
        said = ' '.join([str(pending.get('reason', ''))] + list(pending.get('errors') or []))
        assert reason in said, pending
    return pending


_LAST_TERMINAL_ANSWER = None


def _request_answered(authority, store, kind, subject, bounds):
    """Observe the unattested display, then issue the explicit operator command.

    Terminal.ask stays an inert display fixture. It never grants trusted authority.
    """
    global _LAST_TERMINAL_ANSWER
    _LAST_TERMINAL_ANSWER = None
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = authority.request(store, kind, subject, bounds)
    observed = _LAST_TERMINAL_ANSWER
    if 'pending' not in result or observed is None:
        return result
    assert authority.current(store, kind) is None, result
    nc, decision = observed
    found = re.search(r'--code (\S+)', err.getvalue())
    assert found, err.getvalue()
    _operator_shell(nc)
    record = authority.answer(store, result['pending']['request'], found.group(1), decision)
    assert record['label'] == authority.OPERATOR_COMMAND
    return record


def _scripted_terminal(nc, answers):
    """Observe scripted display responses; trusted decisions use explicit operator answers."""
    terminal = require_controller('authority.terminal')
    asked = []

    def ask(text, *, decisions, timeout=None):
        global _LAST_TERMINAL_ANSWER
        asked.append({'text': text, 'decisions': list(decisions)})
        if not answers:
            raise terminal.TerminalUnavailable('no physicist at the controller terminal')
        decision = answers.pop(0)
        _LAST_TERMINAL_ANSWER = (nc, decision)
        if decision == 'adjust':
            raise terminal.TerminalUnavailable('display observed; operator answers ADJUST explicitly')
        return {'decision': decision, 'comment': '', 'response_sha256': '1' * 64, 'prompt_sha256': '2' * 64,
                'nonce_sha256': '3' * 64, 'device': {'name': '/dev/ttys-fictional', 'rdev': 1}, 'attempts': 1}
    nc.patch.setattr(terminal, 'ask', ask)
    return asked


def _escalated(authority, store, kind, subject, bounds):
    """A decision that escalates: the pending request and the code its WAITING line shows the operator."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = authority.request(store, kind, subject, bounds)
    pending = _held(result)
    found = re.search(r'--code (\S+)', err.getvalue())
    assert found, err.getvalue()
    return pending, found.group(1)


def _operator_shell(nc):
    """The operator's own shell, outside every agent session."""
    from ravel.workflow.approval_authority import AGENT_MARKERS
    for name in AGENT_MARKERS:
        nc.patch.delenv(name, raising=False)


# ---------------------------------------------------------------- CHECK-IN 2 (A08, C16, C17, C20)

@case('A08', binding=CONTROLLER)
def test_A08_an_adjust_answer_or_a_replayed_go_never_authorizes_the_bulk_launch(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc)
    _scripted_terminal(nc, ['approve', 'go', 'adjust'])
    ci1 = _granted(_ci1(authority, store), 'approve', authority.OPERATOR_COMMAND)
    go = _granted(_go(authority, store, ci1), 'go', authority.OPERATOR_COMMAND)
    assert authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT))['go'] == go['id']  # positive control
    # A GO bound to different waypoint bytes is refused even before another decision supersedes it.
    with pytest.raises(authority.AuthorityRefused, match='stale'):
        authority.verify(store, go['id'], kind='go',
                         subject={'approve_plan': ci1['id'], 'waypoint_sha256': WAYPOINT_TWO})
    # The waypoint ran again (new evidence) and the operator answered ADJUST at CHECK-IN 2.
    adjusted = _granted(_go(authority, store, ci1, WAYPOINT_TWO), 'adjust', authority.OPERATOR_COMMAND)
    assert adjusted['authorizes_effects'] is False
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 2 GO'):
        authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT_TWO))
    with pytest.raises(authority.AuthorityRefused):
        authority.verify(store, adjusted['id'], kind='go')
    # The earlier GO replayed against the executed waypoint evidence is stale.
    with pytest.raises(authority.AuthorityRefused, match='stale|superseded'):
        authority.verify(store, go['id'], kind='go', subject={'approve_plan': ci1['id'], 'waypoint_sha256': WAYPOINT_TWO})


def _adjust_authorizes(original):
    return {**original, 'go': tuple(original['go']) + ('adjust',)}


def _pins_ignored(original):
    def verify(store, record_id, *, kind, subject=None):
        return original(store, record_id, kind=kind, subject=None)
    return verify


register(Mutation('M04', f'{SERVICE}:AUTHORIZING', _adjust_authorizes, ('A08',), binding=MUTATION_CONTROLLER,
                  why='an ADJUST answer at CHECK-IN 2 authorizes the bulk launch'),
         Mutation('M04', (f'{SERVICE}:verify', f'{PACKAGE}:verify'), _pins_ignored, ('A08',),
                  binding=MUTATION_CONTROLLER, why='authority is verified without its current pins'))


@case('C16', binding=CONTROLLER)
def test_C16_a_go_bound_to_earlier_waypoint_bytes_refuses_the_full_and_scan_launch(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store, rung='scan'), 'approve', authority.MACHINE)
    go = _granted(_go(authority, store, ci1), 'go', authority.MACHINE)
    for rung in ('full', 'scan'):
        assert authority.authorize_effect(store, _effect(rung, waypoint=WAYPOINT))['go'] == go['id']  # positive control
        # One waypoint image changed after the GO: the executed evidence has another digest.
        with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 2 GO'):
            authority.authorize_effect(store, _effect(rung, waypoint=WAYPOINT_TWO))
    assert authority.current(store, 'go', {'approve_plan': ci1['id'], 'waypoint_sha256': WAYPOINT_TWO}) is None
    assert authority.verify(store, go['id'], kind='go')['id'] == go['id'], 'the old GO stays in the history'


def _subject_ignored(original):
    def current(store, kind, subject=None):
        return original(store, kind, None)
    return current


register(Mutation('M04', (f'{SERVICE}:current', f'{PACKAGE}:current'), _subject_ignored, ('C16',),
                  binding=MUTATION_CONTROLLER, why='the latest authority of a kind authorizes whatever its pins'))


@case('C17', binding=CONTROLLER)
def test_C17_an_obsolete_or_legacy_go_never_authorizes_a_new_or_already_started_launch(nc):
    authority = require_controller('authority')
    common = require_controller('authority.common')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    started = common.now_ns()
    go = _granted(_go(authority, store, ci1), 'go', authority.MACHINE)
    # A GO recorded after the stage started cannot be attached to it.
    with pytest.raises(authority.AuthorityRefused, match='retrospectively'):
        authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT, started_ns=started))
    later = common.now_ns()
    assert authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT, started_ns=later))['go'] == go['id']
    # A legacy GO imported with its unattested label is not authority for a new launch.
    legacy = {k: deepcopy(v) for k, v in go.items() if k not in ('id', 'store_id', 'issuer')}
    legacy.update(uid=common.uid(), label=authority.LEGACY_TERMINAL, subject_sha256='f' * 64, time_ns=common.now_ns(),
                  subject=dict(legacy['subject'], pins={'approve_plan': ci1['id'], 'waypoint_sha256': WAYPOINT_LEGACY}))
    imported = common.append(store, common.AUTHORITY, legacy)
    with pytest.raises(authority.AuthorityRefused, match='unattested.*authorizes nothing'):
        authority.verify(store, imported['id'], kind='go')
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 2 GO'):
        authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT_LEGACY))


def _start_time_ignored(original):
    def authorize_effect(store, effect):
        if type(effect) is dict:
            effect = {k: v for k, v in effect.items() if k != 'started_ns'}
        return original(store, effect)
    return authorize_effect


register(Mutation('M04', (f'{SERVICE}:authorize_effect', f'{PACKAGE}:authorize_effect'), _start_time_ignored,
                  ('C17',), binding=MUTATION_CONTROLLER,
                  why='a GO recorded after the stage started authorizes it retrospectively'),
         Mutation('M04', 'ravel.controller.authority.common:LABELS',
                  lambda original: tuple(original) + ('terminal_operator_unattested',), ('C17',),
                  binding=MUTATION_CONTROLLER, why='an imported legacy GO counts as authority'))


@case('C20', binding=CONTROLLER)
def test_C20_an_approved_amendment_invalidates_the_earlier_go(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    go = _granted(_go(authority, store, ci1), 'go', authority.MACHINE)
    assert authority.authorize_effect(store, _effect('full', waypoint=WAYPOINT))['go'] == go['id']  # positive control
    amended = _granted(_deviation(authority, store, ci1, TIGHTEN), 'approve', authority.MACHINE)
    for plan in (PLAN_TWO, PLAN):
        message = 'no current CHECK-IN 2 GO' if plan == PLAN_TWO else 'no current CHECK-IN 1 authority'
        with pytest.raises(authority.AuthorityRefused, match=message):
            authority.authorize_effect(store, _effect('full', plan=plan, waypoint=WAYPOINT))
    # Smaller rungs run on the renewed plan authority; bulk compute waits for a GO on current evidence.
    assert authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))['deviation'] == amended['id']
    renewed = _granted(_go(authority, store, ci1, WAYPOINT_TWO), 'go', authority.MACHINE)
    granted = authority.authorize_effect(store, _effect('full', plan=PLAN_TWO, waypoint=WAYPOINT_TWO))
    assert granted['go'] == renewed['id'] and granted['deviation'] == amended['id']


def _amendments_ignored(original):
    def authorize_effect(store, effect):
        from ravel.controller.authority import common
        try:
            return original(store, effect)
        except common.AuthorityRefused as exc:
            amended = any(r['kind'] == 'deviation' and r['decision'] == 'approve'
                          for r in common.scan(store, common.AUTHORITY, common.SCHEMA))
            if 'amendment' not in str(exc) and not (amended and 'no current CHECK-IN' in str(exc)):
                raise
            return {'approve_plan': None, 'go': 'the-go-before-the-amendment', 'labels': []}
    return authorize_effect


register(Mutation('M04', (f'{SERVICE}:authorize_effect', f'{PACKAGE}:authorize_effect'), _amendments_ignored,
                  ('C20',), binding=MUTATION_CONTROLLER, why='an approved amendment leaves the earlier GO current'))


# ---------------------------------------------------------------- deviations (A09, C21, C31, C32)

@case('A09', binding=CONTROLLER)
def test_A09_a_changed_approved_input_blocks_launches_until_renewed_authority(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    assert authority.authorize_effect(store, _effect('smoke'))['approve_plan'] == ci1['id']  # positive control
    # The worker changed an approved input: the plan digest the controller computes is new.
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))
    change = dict(TIGHTEN, parameter='approved input settings.cfg', why='the input changed mid-run', direction='input')
    renewed = _granted(_deviation(authority, store, ci1, change), 'approve', authority.MACHINE)
    granted = authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))
    assert granted['approve_plan'] == ci1['id'] and granted['deviation'] == renewed['id']


def _any_plan(original):
    """Any current CHECK-IN 1 record authorizes whatever plan the effect names."""
    def plan_authority(store, pins, depth=64):
        found = original(store, pins, depth)
        if found[0] is not None:
            return found
        from ravel.controller.authority import service
        return service.current(store, 'approve_plan'), None
    return plan_authority


register(Mutation('M04', f'{SERVICE}:_plan_authority', _any_plan, ('A09', 'C39'), binding=MUTATION_CONTROLLER,
                  why='a changed plan runs on the earlier CHECK-IN 1 without renewed authority'))


@case('C21', binding=CONTROLLER)
def test_C21_a_course_change_is_disclosed_by_its_deviation_record_never_by_a_note_alone(nc):
    authority = require_controller('authority')
    store, run_dir = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    (run_dir / 'DEVIATIONS.md').write_text('| closure tolerance | 0.10 | 0.05 | the fictional pilot is precise |\n')
    assert authority.deviations(store) == [], 'a row in the run tree is not a disclosed deviation'
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))
    # Positive control: the deviation check-in records the exact row the disclosure shows.
    record = _granted(_deviation(authority, store, ci1, TIGHTEN), 'approve', authority.MACHINE)
    assert authority.deviations(store) == [{'id': record['id'], 'decision': 'approve', 'label': authority.MACHINE,
                                            'change': TIGHTEN, 'time_ns': record['time_ns']}]


register(Mutation('M20', (f'{SERVICE}:deviations', f'{PACKAGE}:deviations'), lambda original: lambda store: [],
                  ('C21',), binding=MUTATION_CONTROLLER, why='the user-visible disclosure omits the deviations'))


@case('C31', binding=CONTROLLER)
def test_C31_loosening_a_control_needs_renewed_exact_authority_a_note_is_not_approval(nc):
    authority = require_controller('authority')
    store, run_dir = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    (run_dir / 'DEVIATIONS.md').write_text('| closure tolerance | 0.05 | 0.20 | the fictional closure failed |\n')
    pending, code = _escalated(authority, store, 'deviation', _deviation_subject(store, ci1, LOOSEN), {'rung': 'full'})
    assert 'loosening a certification control' in pending['reason'], pending
    assert authority.current(store, 'deviation', {'plan_sha256': PLAN_TWO}) is None
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))
    # Positive controls: the operator's exact answer renews authority; a tightening is decided by machine.
    _operator_shell(nc)
    renewed = authority.answer(store, pending['request'], code, 'approve')
    assert renewed['label'] == authority.OPERATOR_COMMAND and renewed['subject']['change'] == LOOSEN
    assert authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))['deviation'] == renewed['id']
    _granted(_deviation(authority, store, ci1, TIGHTEN, plan='b' * 64), 'approve', authority.MACHINE)


register(Mutation('M04', f'{SERVICE}:_human_reasons', lambda original: lambda *a, **k: [], ('C31', 'A11', 'C07'),
                  binding=MUTATION_CONTROLLER,
                  why='an autonomous run decides loosening, R3 actions and changed requests by machine'))


@case('C32', binding=CONTROLLER)
def test_C32_a_tightened_control_needs_its_exact_parameter_from_to_why_row(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    vague = [{**TIGHTEN, 'why': ' '}, {**TIGHTEN, 'touches': []}, {k: v for k, v in TIGHTEN.items() if k != 'from'},
             {**TIGHTEN, 'direction': 'stricter'}]
    for change in vague:
        _held(_deviation(authority, store, ci1, change), 'exact parameter/from/to/why/touches/direction row')
    assert authority.deviations(store) == []
    _granted(_deviation(authority, store, ci1, TIGHTEN), 'approve', authority.MACHINE)  # positive control


def _row_unchecked(original):
    def prepare(store, kind, subject, bounds):
        prepared = original(store, kind, subject, bounds)
        prepared['errors'] = [e for e in prepared.get('errors', []) if 'deviation states' not in e]
        return prepared
    return prepare


register(Mutation('M11', f'{SERVICE}:_prepare', _row_unchecked, ('C32',), binding=MUTATION_CONTROLLER,
                  why='a deviation is decided without its exact change row'))


# ---------------------------------------------------------------- R3 and changed requests (A11, C07)

@case('A11', binding=CONTROLLER)
def test_A11_ordinary_delegation_never_unblinds_or_spends_above_the_ceiling(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    codes = {}
    for gate in ('unblind', 'spend_above_ceiling'):
        subject = {'view': checkin_view(store, 'r3_action', approve_plan=ci1['id']), 'gate': gate}
        pending, codes[gate] = _escalated(authority, store, 'r3_action', subject, {})
        assert f'R3 decision ({gate})' in pending['reason'], pending
    assert authority.current(store, 'r3_action') is None
    with pytest.raises(authority.AuthorityRefused, match='exceeds the ceiling'):
        authority.authorize_effect(store, _effect('smoke', budget={'core_hours': 10_000}))
    # Positive control: the operator's answer to the R3 request is its authority, for the chosen option only.
    _operator_shell(nc)
    approved = authority.answer(store, pending['request'], codes['spend_above_ceiling'], 'proceed')
    assert approved['label'] == authority.OPERATOR_COMMAND and approved['option'] == 'proceed'
    assert authority.current(store, 'r3_action')['id'] == approved['id']


@case('C07', binding=CONTROLLER)
def test_C07_delegated_approval_cannot_change_the_prescribed_statistic_or_a_user_boundary(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    changed = {'statistic': {'requested': 'fictional-delta-chi2', 'planned': 'fictional-cls'}}
    _held(_ci1(authority, store, request_pins=changed), 'the plan changes the requested statistic')
    boundary = {'boundary': {'requested': 'one model point only', 'planned': 'ten model points'}}
    _held(_ci1(authority, store, plan='b' * 64, request_pins=boundary), 'the plan changes the requested boundary')
    invented = ['the fictional detector efficiency is 0.9']
    _held(_ci1(authority, store, plan='c' * 64, inferred_critical_facts=invented), 'inferred critical facts')
    assert authority.current(store, 'approve_plan') is None
    # Positive control: a plan that keeps the requested statistic is approved within the bounds.
    kept = {'statistic': {'requested': 'fictional-delta-chi2', 'planned': 'fictional-delta-chi2'}}
    _granted(_ci1(authority, store, plan='d' * 64, request_pins=kept), 'approve', authority.MACHINE)


# ---------------------------------------------------------------- steering (C37, C38, C39)

@case('C37', binding=CONTROLLER)
def test_C37_a_steering_ceiling_is_consumed_by_every_later_effect(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    effect = _effect('smoke', budget={'events': 1_000})
    assert authority.authorize_effect(store, effect)['approve_plan']  # positive control: within the frozen ceiling
    _granted(_steer(authority, store, {'budgets': {'events': 0}}), 'approve', authority.MACHINE)
    assert authority.effective_bounds(store)['budgets']['events'] == 0
    with pytest.raises(authority.AuthorityRefused, match='events=1000 exceeds the ceiling 0'):
        authority.authorize_effect(store, effect)


def _steering_ignored(original):
    def effective_bounds(store):
        from ravel.controller.authority import mode
        record = mode.frozen(store)
        return {'budgets': deepcopy(record['budgets']), 'bounds': deepcopy(record['bounds']),
                'mode_record': record['id'], 'steering_records': []}
    return effective_bounds


register(Mutation('M17', ('ravel.controller.authority.mode:effective_bounds', f'{PACKAGE}:effective_bounds'),
                  _steering_ignored, ('C37',), binding=MUTATION_CONTROLLER,
                  why='steering ceilings are recorded and never consumed'))


@case('C38', binding=CONTROLLER)
def test_C38_a_policy_change_cannot_approve_its_own_widening(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ceiling = authority.effective_bounds(store)['budgets']['core_hours']
    _held(_steer(authority, store, {'budgets': {'core_hours': ceiling * 4}}), 'steering widens budgets.core_hours')
    narrowed = _granted(_steer(authority, store, {'bounds': {'rungs': ['none', 'dry', 'smoke']}}), 'approve',
                        authority.MACHINE)  # positive control: narrowing is the machine's to approve
    _held(_steer(authority, store, {'bounds': {'rungs': ['none', 'dry', 'smoke', 'pilot', 'full']}}),
          'steering widens bounds.rungs')
    # A policy edit that removes a signoff (more machine check-ins) is not a steering policy at all.
    with pytest.raises((authority.AuthorityRefused, ValueError)):
        _steer(authority, store, {'machine_checkins': ['approve_plan', 'go', 'deviation', 'final', 'r3_action']})
    effective = authority.effective_bounds(store)
    assert effective['budgets']['core_hours'] == ceiling and effective['bounds']['rungs'] == ['none', 'dry', 'smoke']
    assert effective['steering_records'] == [narrowed['id']]


register(Mutation('M04', 'ravel.controller.authority.mode:policy_widens', lambda original: lambda current, policy: [],
                  ('C38',), binding=MUTATION_CONTROLLER, why='a steering policy approves its own widening'))


@case('C39', binding=CONTROLLER)
def test_C39_an_acknowledged_steering_event_installs_no_plan(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    steering = _granted(_steer(authority, store, {'budgets': {'events': 50_000}}), 'approve', authority.MACHINE)
    with pytest.raises(authority.AuthorityRefused):
        authority.verify(store, steering['id'], kind='approve_plan')
    # A redirect to a new plan after the acknowledgement has no CHECK-IN 1 authority.
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(store, _effect('smoke', plan=PLAN_TWO))
    assert authority.authorize_effect(store, _effect('smoke'))['approve_plan'] == ci1['id']  # positive control


# ---------------------------------------------------------------- final disposition, stop (C42, B05)

@case('C42', binding=CONTROLLER)
def test_C42_the_final_disposition_is_neither_review_credit_nor_approval_of_a_new_attempt(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    # The final task is R3: its disposition is the operator's renewed answer on the final view, never a machine one.
    pending, code = _escalated(authority, store, 'final',
                               {'view': checkin_view(store, 'final', approve_plan=ci1['id'])}, {})
    _operator_shell(nc)
    final = _granted(authority.answer(store, pending['request'], code, 'accept'), 'accept', authority.OPERATOR_COMMAND)
    assert final['authorizes_effects'] is False and final['review_credit'] is False
    for kind in ('final', 'approve_plan', 'go'):
        with pytest.raises(authority.AuthorityRefused):
            authority.verify(store, final['id'], kind=kind)
    attempt, _ = controller_run(nc, 'nc-run-new-attempt')
    with pytest.raises(authority.AuthorityRefused):
        authority.verify(attempt, final['id'], kind='approve_plan')
    with pytest.raises(authority.AuthorityRefused, match='no current CHECK-IN 1 authority'):
        authority.authorize_effect(attempt, _effect('smoke'))
    # Positive control: the new attempt's own CHECK-IN 1 authorizes it.
    own = _granted(_ci1(authority, attempt), 'approve', authority.MACHINE)
    assert authority.authorize_effect(attempt, _effect('smoke'))['approve_plan'] == own['id']


def _disposition_authorizes(original):
    def verify(store, record_id, *, kind, subject=None):
        from ravel.controller.authority import common
        try:
            record = common.read(store, common.AUTHORITY, record_id, common.SCHEMA)
        except KeyError:
            return original(store, record_id, kind=kind, subject=subject)
        if record.get('kind') == 'final' and record.get('decision') == 'accept':
            return record
        return original(store, record_id, kind=kind, subject=subject)
    return verify


register(Mutation('M04', (f'{SERVICE}:verify', f'{PACKAGE}:verify'), _disposition_authorizes, ('C42',),
                  binding=MUTATION_CONTROLLER, why='an accepted final disposition is presented as authority'))


@case('B05', binding=CONTROLLER)
def test_B05_a_stop_survives_a_controller_restart_and_refuses_every_later_effect(nc):
    authority = require_controller('authority')
    store_module = require_controller('store')
    store, run_dir = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    authority.authorize_effect(store, _effect('smoke'))  # positive control: the running run admits it
    status, text = operator(nc)('stop', '--run', store.run_id, '--reason', 'fictional stop during parent completion')
    assert status == 0, text
    authority.observe_stop(store, 'draining', {'fictional': 'the parent is completing'})
    for path in sorted(run_dir.rglob('*'), reverse=True):
        if path.is_file() and path.name != 'controller-run.json':
            path.unlink()
    restarted = store_module.RunStore(store.run_id)
    assert authority.stop_state(restarted) == 'draining'
    with pytest.raises(authority.AuthorityRefused, match='the run is draining'):
        authority.authorize_effect(restarted, _effect('smoke'))
    with pytest.raises(authority.AuthorityRefused):
        authority.check(restarted, 'nested submission of a descendant')
    view = checkin_view(restarted, 'go', approve_plan=ci1['id'], waypoint_sha256=WAYPOINT)
    _held(authority.request(restarted, 'go', {'view': view}, {'rung': 'full'}), 'the run is draining')
    authority.observe_stop(restarted, 'stopped', {'reaped': ['fictional-descendant']})
    assert authority.stop_state(restarted) == 'stopped'
    with pytest.raises(authority.AuthorityRefused):
        authority.authorize_effect(restarted, _effect('smoke'))
    status, text = operator(nc)('resume', '--run', store.run_id, '--reason', 'fictional resume by the operator')
    assert status == 0 and authority.stop_state(restarted) == 'running'  # positive control: the operator resumes


register(Mutation('M18', ('ravel.controller.authority.stop:check', f'{PACKAGE}:check'),
                  lambda original: lambda store, action='effect': {'state': 'running'}, ('B05',),
                  binding=MUTATION_CONTROLLER, why='effects are admitted without reading the stop state'))


# ---------------------------------------------------------------- check-in presentation (A03, A06, C03, C05, C14, C15, C36)

@case('A03', binding=CONTROLLER)
def test_A03_an_agent_with_a_pseudo_terminal_and_no_markers_cannot_approve_a_controller_run(nc):
    authority = require_controller('authority')
    require_controller('command_policy')
    from test_nc_switches import PTY_APPROVE, REFUSED, _cli
    store, run_dir = controller_run(nc)
    _operator_shell(nc)  # the adversary unset every agent-session marker
    argv = ['approve', '--rundir', str(run_dir), '--plan', 'smoke', '--quote', 'Approved (fictional).']
    status, text = _cli(argv)
    assert status != 0 and REFUSED in text, text[-400:]
    child = subprocess.run([sys.executable, '-c', PTY_APPROVE, *argv], capture_output=True, text=True,
                           env=dict(os.environ), timeout=120)
    assert child.stdout.strip() != '0' and REFUSED in child.stderr, (child.stdout, child.stderr[-400:])
    assert [r for r in authority.records(store) if r['label'] == authority.TERMINAL or r['kind'] == 'approve_plan'] == []
    assert authority.current(store, 'approve_plan') is None
    # Positive control: the display is observed, then an explicit operator command grants approval.
    _scripted_terminal(nc, ['approve'])
    _granted(_ci1(authority, store), 'approve', authority.OPERATOR_COMMAND)


register(Mutation('M22', ('ravel.controller.command_policy:check',), lambda original: lambda argv: None, ('A03',),
                  binding=MUTATION_CONTROLLER, why='the command policy never refuses'))


def _sectioned_view(store, required, sections, **items):
    view = checkin_view(store, 'approve_plan', plan_sha256=PLAN)
    view['required_sections'] = list(required)
    view['sections'] = deepcopy(view['sections']) + deepcopy(sections)
    view['items'] = dict(view['items'], **items)
    return view


@case('C03', binding=CONTROLLER)
def test_C03_an_omitted_empty_or_placeholder_variant_section_holds_ci1(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    variant = {'id': 'variant', 'title': 'Task variant', 'lines': ['Variant: fictional single-point calculation.']}
    _held(_ci1(authority, store, view=_sectioned_view(store, ['variant'], [])), 'lacks required sections: variant')
    for hollow in ([], ['TBD']):
        view = _sectioned_view(store, ['variant'], [dict(variant, lines=hollow)])
        _held(_ci1(authority, store, view=view))
    assert authority.current(store, 'approve_plan') is None
    view = capture_view(store, 'approve_plan', _sectioned_view(store, ['variant'], [variant]))
    _granted(_ci1(authority, store, view=view), 'approve', authority.MACHINE)


@case('A06', binding=CONTROLLER)
def test_A06_an_empty_figures_section_or_a_placeholder_cost_never_reaches_approval(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc, mode='autonomous')
    figures = {'id': 'figures', 'title': 'Figures', 'lines': ['Figure 1: the fictional observable against the coupling.']}
    cost = {'id': 'cost', 'title': 'Cost', 'lines': ['Forecast: 0.2 core-hours, 1 model call (fictional pilot).']}
    _held(_ci1(authority, store, view=_sectioned_view(store, ['figures', 'cost'], [cost])), 'lacks required sections')
    for hollow in ([dict(figures, lines=[]), cost], [figures, dict(cost, lines=['placeholder'])]):
        _held(_ci1(authority, store, view=_sectioned_view(store, ['figures', 'cost'], hollow)))
    assert authority.current(store, 'approve_plan') is None
    view = capture_view(store, 'approve_plan', _sectioned_view(store, ['figures', 'cost'], [figures, cost]))
    _granted(_ci1(authority, store, view=view), 'approve', authority.MACHINE)  # positive control


def _tampered(common, artifact, key, row):
    """``artifact`` without ``row``, re-digested as the adversary would."""
    copy = deepcopy(artifact)
    if key == 'flags':
        copy['flags'] = [f for f in copy['flags'] if f['text'] != row]
    else:
        copy['items'][key] = [r for r in copy['items'][key] if r != row]
    for section in copy['sections']:
        section['lines'] = [line for line in section['lines'] if row not in line]
    copy['sha256'] = common.digest({k: v for k, v in copy.items() if k != 'sha256'})
    return copy


@case('C05', binding=CONTROLLER)
def test_C05_a_displayed_check_in_without_an_open_ambiguity_or_child_node_is_refused(nc):
    authority = require_controller('authority')
    common = require_controller('authority.common')
    store, _ = controller_run(nc, mode='autonomous')
    ambiguity, child = 'Which fictional coupling convention applies?', 's02 child: fit the fictional constant'
    view = _sectioned_view(store, [], [], ambiguities=[ambiguity], steps=['s01 derive the observable', child])
    view = capture_view(store, 'approve_plan', view)
    rendered = authority.render_checkin('approve_plan', view)
    for key, row in (('ambiguities', ambiguity), ('steps', child)):
        tampered = _tampered(common, rendered, key, row)
        _held(authority.request(store, 'approve_plan', {'view': view, 'checkin': tampered}, {'rung': 'full'}), 'omits')
    assert authority.current(store, 'approve_plan') is None
    granted = authority.request(store, 'approve_plan', {'view': view, 'checkin': rendered}, {'rung': 'full'})
    _granted(granted, 'approve', authority.MACHINE)  # positive control: the faithful rendering


@case('C14', binding=CONTROLLER)
def test_C14_a_result_sensitive_assumption_moved_to_a_footer_is_surfaced_as_hidden(nc):
    authority = require_controller('authority')
    common = require_controller('authority.common')
    store, _ = controller_run(nc, mode='autonomous')
    view = _sectioned_view(store, [], [])
    view = capture_view(store, 'approve_plan', view)
    sensitive = view['flags'][0]['text']
    tampered = _tampered(common, authority.render_checkin('approve_plan', view), 'flags', sensitive)
    tampered['sections'].append({'id': 'footer', 'title': 'Notes', 'lines': [f'(also assumed: {sensitive})']})
    tampered['sha256'] = common.digest({k: v for k, v in tampered.items() if k != 'sha256'})
    pending = _held(authority.request(store, 'approve_plan', {'view': view, 'checkin': tampered}, {'rung': 'full'}),
                    'hides flag 1')
    assert any(sensitive[:40] in e for e in pending['errors']), pending
    _granted(_ci1(authority, store, view=view), 'approve', authority.MACHINE)  # positive control


for _case in ('C05', 'C14', 'C36'):
    register(Mutation('M05', 'ravel.controller.authority.checkin:validate', lambda original: lambda *a, **k: [],
                      (_case,), binding=MUTATION_CONTROLLER, why='a supplied check-in is presented without validation'))


@case('C15', binding=CONTROLLER)
def test_C15_the_terminal_shows_every_flag_and_question_and_keeps_the_alteration_channel(nc):
    authority = require_controller('authority')
    store, _ = controller_run(nc)
    asked = _scripted_terminal(nc, ['approve'])
    view = _sectioned_view(store, [], [], questions=['Which fictional scale applies?'])
    view = capture_view(store, 'approve_plan', view)
    hidden = authority.render_checkin('approve_plan', view)
    hidden.update(alteration_channel=False, decisions=['approve'])
    _held(authority.request(store, 'approve_plan', {'view': view, 'checkin': hidden}, {'rung': 'full'}),
          'removes the response or alteration channel')
    assert asked == [], 'a check-in without its alteration channel is never presented for assent'
    _granted(_ci1(authority, store, view=view), 'approve', authority.OPERATOR_COMMAND)  # positive control
    shown = asked[-1]
    for flag in view['flags']:
        assert flag['text'] in shown['text'], flag
    assert 'Which fictional scale applies?' in shown['text'] and 'alteration' in shown['text']
    assert {'adjust', 'reject'} <= set(shown['decisions'])


def _flags_hidden(original):
    def text(artifact):
        return original(dict(artifact, sections=[s for s in artifact['sections'] if s.get('id') != 'flags']))
    return text


register(Mutation('M05', 'ravel.controller.authority.checkin:text', _flags_hidden, ('C15',),
                  binding=MUTATION_CONTROLLER, why='the terminal rendering hides the numbered flags'))


@case('C36', binding=CONTROLLER)
def test_C36_the_final_check_in_keeps_every_unknown_recipe_row(nc):
    authority = require_controller('authority')
    common = require_controller('authority.common')
    store, _ = controller_run(nc, mode='autonomous')
    ci1 = _granted(_ci1(authority, store), 'approve', authority.MACHINE)
    recipe = {'id': 'recipe', 'title': 'Recipe ledger',
              'lines': ['generator: fictional-gen 1.0', 'unknown: shower seed', 'unknown: tune variation']}
    view = checkin_view(store, 'final', approve_plan=ci1['id'])
    view.update(required_sections=['recipe'], sections=view['sections'] + [recipe])
    view = capture_view(store, 'final', view)
    rendered = authority.render_checkin('final', view)
    dropped = deepcopy(rendered)
    for section in dropped['sections']:
        if section['id'] == 'recipe':
            section['lines'] = [line for line in section['lines'] if not line.startswith('unknown:')]
    dropped['sha256'] = common.digest({k: v for k, v in dropped.items() if k != 'sha256'})
    _held(authority.request(store, 'final', {'view': view, 'checkin': dropped}, {}), 'tampered or stale copy')
    absent = dict(view, sections=[s for s in view['sections'] if s['id'] != 'recipe'])
    _held(authority.request(store, 'final', {'view': absent}, {}), 'lacks required sections: recipe')
    # Positive control: the faithful rendering is presented, and the R3 final task waits for the operator's answer.
    pending, code = _escalated(authority, store, 'final', {'view': view, 'checkin': rendered}, {})
    _operator_shell(nc)
    _granted(authority.answer(store, pending['request'], code, 'accept'), 'accept', authority.OPERATOR_COMMAND)
