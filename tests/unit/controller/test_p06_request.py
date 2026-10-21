"""P06: decisions come only from the controller's authority sources, and gates read only the store.

Covers the authority rows A01, A02, A05, A08, A09, A11, C05, C07, C09, C15-C17, C20, C21, C23, C31,
C32, C37-C39, C42, G05, G11, GATE-unblind, GATE-spend_above_ceiling, CHECKIN-1/2/3/deviation/
escalation/final, CT07 and the joint JR08 timeout. Every refusal has a positive control.
"""
from __future__ import annotations

import json
import re
import sys

import pytest

from test_p06_support import autonomous, frozen_store, new_store, operator_home, ownership, view, retain_view  # noqa: F401
from ravel.controller.authority import (AuthorityRefused, MACHINE, OPERATOR_COMMAND, TERMINAL, LEGACY_TERMINAL, answer,
                                        authorize_effect, current, deviations, effective_bounds, render_checkin,
                                        request, verify)
from ravel.controller.authority import common, operator, terminal

PLAN_A, PLAN_B = 'a' * 64, 'b' * 64
WAYPOINT, WAYPOINT_2 = 'c' * 64, 'e' * 64


def test_cost_request_retains_compiler_and_reading_before_requesting_signoff(tmp_path, operator_home, monkeypatch):
    from copy import deepcopy
    from ravel.controller.authority import retained
    from ravel.controller.step import graph, operations
    from ravel.controller.step.services import StepHold
    from test_p04_reserve import _top_step

    autonomous()
    store = frozen_store(tmp_path)
    source = view(store, 'approve_plan', plan_sha256=PLAN_A)
    source['items']['questions'] = ['Does the supplied input apply throughout the requested domain?']
    retain_view(store, 'approve_plan', source,
                facts=[{'id': 'domain', 'type': 'applicability', 'value': 'inferred'}])
    original = retained.current(store, 'approve_plan')
    monkeypatch.setattr(operations, 'current_plan', lambda *_: deepcopy(original['plan']))
    with pytest.raises(StepHold) as held:
        graph._cost_signoff(store, _top_step(), {'events': 100, 'wall_seconds': 50}, {'plan_sha256': PLAN_A})
    assert held.value.reason == 'awaiting_authority'
    assert not held.value.evidence['pending'].get('errors')
    assert held.value.evidence['pending']['request']
    captured = retained.current(store, 'r3_action')
    assert captured['plan'] == original['plan']
    assert captured['reading']['inferred_critical_facts'] == original['reading']['inferred_critical_facts']
    assert captured['view']['items'] == retained.view_items(original['plan'], original['reading'])
    assert captured['view']['flags'][:-1] == original['view']['flags']
    assert captured['view']['flags'][-1]['kind'] == 'risk'
    assert retained.current(store, 'approve_plan') == original
    assert store.scan('authority') == []


def test_cost_request_refuses_unauthenticated_reading_instead_of_recapturing_it(tmp_path, operator_home, monkeypatch):
    from copy import deepcopy
    from ravel.controller.authority import retained
    from ravel.controller.step import graph, operations
    from ravel.controller.step.services import StepHold
    from test_p04_reserve import _top_step

    autonomous()
    store = frozen_store(tmp_path)
    view(store, 'approve_plan', plan_sha256=PLAN_A)
    original = retained.current(store, 'approve_plan')
    monkeypatch.setattr(operations, 'current_plan', lambda *_: deepcopy(original['plan']))
    store.append('authority-context', {**original, 'reading': {**original['reading'], 'flags': []}})
    with pytest.raises(StepHold) as held:
        graph._cost_signoff(store, _top_step(), {'events': 100, 'wall_seconds': 50}, {'plan_sha256': PLAN_A})
    assert held.value.reason == 'authority_refused'
    assert store.scan('authority-request') == []
    assert store.scan('authority') == []


def ci1(store, plan=PLAN_A, rung='full'):
    return request(store, 'approve_plan', {'view': view(store, 'approve_plan', plan_sha256=plan)},
                   {'rung': rung})


def go(store, approval, waypoint=WAYPOINT):
    return request(store, 'go', {'view': view(store, 'go', approve_plan=approval['id'], waypoint_sha256=waypoint)},
                   {'rung': 'full'})


def effect(plan='smoke', plan_sha256=PLAN_A, waypoint=WAYPOINT, **extra):
    return {'id': 'e1', 'rung': plan, 'pins': {'plan_sha256': plan_sha256},
            'go_pins': {'waypoint_sha256': waypoint}, **extra}


def r3(store, gate='unblind', default='hold'):
    subject = {'view': view(store, 'r3_action', action_sha256='f' * 64), 'gate': gate}
    if default is not None:
        subject['conservative_default'] = default
    return request(store, 'r3_action', subject, {})


@pytest.fixture
def physicist(monkeypatch):
    """The physicist at the controller terminal (seam over ``terminal.ask``; the real TTY path is
    exercised in test_p06_terminal.py). Answers come from ``answers``; calls are recorded."""
    calls, answers = [], []

    def ask(text, *, decisions, timeout=None):
        calls.append({'text': text, 'decisions': list(decisions)})
        if not answers:
            raise terminal.TerminalUnavailable('no physicist at the terminal in this test')
        decision, comment = answers.pop(0)
        return {'decision': decision, 'comment': comment, 'response_sha256': '1' * 64, 'prompt_sha256': '2' * 64,
                'nonce_sha256': '3' * 64, 'device': {'name': '/dev/ttys999', 'rdev': 1}, 'attempts': 1}
    monkeypatch.setattr(terminal, 'ask', ask)
    return calls, answers


def notifier(tmp_path):
    log = tmp_path / 'notified.log'
    script = tmp_path / 'notify.py'
    script.write_text('import sys\nopen(sys.argv[1], "a").write(" | ".join(sys.argv[2:]) + "\\n")\n')
    return [sys.executable, str(script), str(log)], log


# ------------------------------------------------------------------ sources and labels

def test_A05_autonomous_checkin1_resolves_inside_bounds_with_the_machine_label(operator_home, tmp_path, physicist):
    autonomous()
    store = frozen_store(tmp_path)
    record = ci1(store)
    assert record['label'] == MACHINE and record['decision'] == 'approve' and record['source'] == 'operator_ledger'
    assert record['human_identity_authenticated'] is False and record['review_credit'] is False
    assert record['evidence']['mode_record'] == common.read(store, 'mode', record['mode_record'])['id']
    assert verify(store, record['id'], kind='ci1', subject={'plan_sha256': PLAN_A})['id'] == record['id']
    assert physicist[0] == []  # the machine path never touches the terminal
    assert ci1(store)['id'] == record['id']  # the same subject is decided once


def test_physicist_approval_is_never_synthesised(operator_home, tmp_path, physicist):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    go(store, approval)
    r3(store, default=None)
    labels = {row['label'] for row in store.scan('authority')}
    assert TERMINAL not in labels and labels <= {MACHINE}


def test_out_of_bounds_checkin_escalates_instead_of_machine_approval(operator_home, tmp_path):
    autonomous(bounds={'rungs': ['none', 'dry', 'smoke']})
    store = frozen_store(tmp_path)
    held = ci1(store, rung='full')
    assert 'pending' in held and 'outside the operator bounds' in held['pending']['reason']
    assert store.scan('authority') == []
    assert ci1(store, plan=PLAN_B, rung='smoke')['label'] == MACHINE


def test_C07_changed_statistic_or_inferred_critical_fact_is_not_machine_approved(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    changed = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256=PLAN_A),
                                     'request_pins': {'statistic': {'requested': 'cls95', 'planned': 'z-score'}}},
                      {'rung': 'smoke'})
    assert 'pending' in changed and 'requested statistic' in changed['pending']['reason']
    invented = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256=PLAN_B),
                                      'inferred_critical_facts': ['efficiency 0.4 assumed']}, {'rung': 'smoke'})
    assert 'pending' in invented and 'inferred critical facts' in invented['pending']['reason']
    kept = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256='9' * 64),
                                  'request_pins': {'statistic': {'requested': 'cls95', 'planned': 'cls95'}}},
                   {'rung': 'smoke'})
    assert kept['label'] == MACHINE


def test_CT07_physicist_mode_takes_answers_only_at_the_controller_terminal(operator_home, tmp_path, physicist):
    calls, answers = physicist
    store = frozen_store(tmp_path)
    held = ci1(store)
    assert 'pending' in held and len(calls) == 1 and store.scan('authority') == []
    pending = store.scan('authority-request')[0]
    with pytest.raises(AuthorityRefused):
        answer(store, pending['uid'], 'ANY-CODE', 'approve')
    answers.append(('approve', 'Approved; keep the smoke rung small.'))
    held = ci1(store)
    assert 'pending' in held and held['unattested_record']
    record = common.read(store, common.AUTHORITY, held['unattested_record'], common.SCHEMA)
    assert record['label'] == LEGACY_TERMINAL and record['decision'] == 'approve'
    assert record['comment'] == 'Approved; keep the smoke rung small.' and record['source'] == 'controller_terminal'
    assert 'CHECK-IN 1' in calls[-1]['text'] and calls[-1]['decisions'] == ['approve', 'adjust', 'reject']


# ------------------------------------------------------------------ typed check-ins

def test_C05_C15_C23_checkin_rendered_from_state_and_validated_before_assent(operator_home, tmp_path, physicist):
    calls, answers = physicist
    store = frozen_store(tmp_path)
    state = view(store, 'approve_plan', plan_sha256=PLAN_A)
    artifact = render_checkin('ci1', state)
    hidden = {**artifact, 'flags': artifact['flags'][1:]}
    no_channel = {**artifact, 'alteration_channel': False}
    stale = {**artifact, 'pins': {'plan_sha256': PLAN_B}}
    reordered = {**artifact, 'sections': list(reversed(artifact['sections']))}
    edited = {**artifact, 'summary': 'A different summary.'}
    for copy, reason in ((hidden, 'hides flag'), (no_channel, 'alteration channel'), (stale, 'pin plan_sha256'),
                         (reordered, 'out of order'), (edited, 'tampered or stale')):
        held = request(store, 'ci1', {'view': state, 'checkin': copy}, {'rung': 'smoke'})
        assert held['pending']['reason'] == 'check-in incomplete'
        assert any(reason in e for e in held['pending']['errors']), held['pending']['errors']
    incomplete = dict(state, sections=[])
    held = request(store, 'ci1', {'view': incomplete}, {'rung': 'smoke'})
    assert any('lacks required sections: preamble' in e for e in held['pending']['errors'])
    assert calls == [] and store.scan('authority') == []
    answers.append(('approve', ''))
    held = request(store, 'ci1', {'view': state, 'checkin': artifact}, {'rung': 'smoke'})
    assert 'pending' in held and held['unattested_record']
    assert common.read(store, common.AUTHORITY, held['unattested_record'], common.SCHEMA)['label'] == LEGACY_TERMINAL
    assert 'Is one point enough?' in calls[0]['text'] and 'Boundary: one model point only' in calls[0]['text']


def test_C05_C23_an_empty_or_placeholder_required_section_holds_the_checkin(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    state = view(store, 'approve_plan', plan_sha256=PLAN_A)
    route = {'id': 'variant', 'title': 'Task variant', 'lines': ['One model point; counting only.']}
    for hollow in ([], ['TBD'], ['  placeholder.', '...'], ['<TODO>']):
        sections = state['sections'] + [dict(route, lines=hollow)]
        held = request(store, 'ci1', {'view': dict(state, sections=sections, required_sections=['variant'])},
                       {'rung': 'smoke'})
        assert any('lacks required sections: variant' in e for e in held['pending']['errors']), hollow
        preamble = [dict(state['sections'][0], lines=hollow)]
        held = request(store, 'ci1', {'view': dict(state, sections=preamble)}, {'rung': 'smoke'})
        assert any('lacks required sections: preamble' in e for e in held['pending']['errors']), hollow
    assert store.scan('authority') == []
    complete = dict(state, sections=state['sections'] + [route], required_sections=['variant'])
    retain_view(store, 'approve_plan', complete)
    assert request(store, 'ci1', {'view': complete}, {'rung': 'smoke'})['label'] == MACHINE


def test_CHECKIN_1_CHECKIN_2_CHECKIN_3_CHECKIN_deviation_CHECKIN_final_need_the_current_checkin1(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    for kind, extra in (('go', {'waypoint_sha256': WAYPOINT}), ('final', {'result_sha256': 'd' * 64}),
                        ('deviation', {'plan_sha256': PLAN_B, 'previous_plan_sha256': PLAN_A})):
        subject = {'view': view(store, kind, approve_plan='forged-record', **extra)}
        if kind == 'deviation':
            subject['change'] = {'parameter': 'tolerance', 'from': '0.10', 'to': '0.05', 'why': 'tighter control',
                                 'touches': ['s01'], 'direction': 'tighten'}
        with pytest.raises(AuthorityRefused):
            request(store, kind, subject, {})
    (tmp_path / 'inputs').mkdir()
    (tmp_path / 'inputs/checkin1_approval.json').write_text(json.dumps({'authority': 'human_operator'}))
    with pytest.raises(AuthorityRefused):
        verify(store, 'forged-record', kind='ci1')
    approval = ci1(store)
    assert go(store, approval)['label'] == MACHINE


def test_CHECKIN_escalation_offers_options_and_needs_them(operator_home, tmp_path, physicist):
    calls, answers = physicist
    store = frozen_store(tmp_path)
    state = view(store, 'escalation', question_sha256='5' * 64)
    held = request(store, 'escalation', {'view': dict(state, options=[])}, {})
    assert held['pending']['reason'] == 'check-in incomplete'
    for options in ([{'id': 'keep blinded', 'text': 'x'}], [{'id': 'reject', 'text': 'x'}],
                    [{'id': 'hold', 'text': 'x'}, {'id': 'HOLD', 'text': 'y'}]):
        held = request(store, 'escalation', {'view': dict(state, options=options)}, {})
        assert any('one-word ids' in e for e in held['pending']['errors']), held
    assert calls == []
    answers.append(('hold', 'Use the coarse binning.'))
    record = request(store, 'escalation', {'view': state}, {})
    assert record['decision'] == 'answer' and record['option'] == 'hold' and record['label'] == LEGACY_TERMINAL
    assert calls[-1]['decisions'] == ['hold', 'proceed', 'reject']


# ------------------------------------------------------------------ R3, escalation, defaults

def test_A11_G11_GATE_unblind_GATE_spend_above_ceiling_never_resolve_by_machine(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    for gate in ('unblind', 'spend_above_ceiling'):
        held = r3(store, gate=gate, default=None)
        assert 'pending' in held and 'R3 decision' in held['pending']['reason']
    with pytest.raises(ValueError):
        r3(store, gate='unblind', default='proceed')  # a default may never take the unblinding effect
    assert store.scan('authority') == []


def test_JR08_timeout_takes_the_recorded_default_or_holds(operator_home, tmp_path, monkeypatch):
    autonomous(wait_bound_seconds=60)
    store = frozen_store(tmp_path)
    clock = [common.now_ns()]
    monkeypatch.setattr(common, 'now_ns', lambda: clock[0])
    held = r3(store, default='hold')
    assert 'pending' in held and held['pending']['wait_bound_seconds'] == 60
    nodefault = request(store, 'escalation', {'view': view(store, 'escalation', question_sha256='6' * 64)}, {})
    assert 'pending' in nodefault
    clock[0] += 61 * 10**9
    record = r3(store, default='hold')
    assert record['decision'] == 'default' and record['option'] == 'hold' and record['label'] == MACHINE
    assert record['evidence']['r3_policy'] == 'escalate_and_wait' and record['evidence']['waited_seconds'] >= 60
    assert 'pending' in request(store, 'escalation', {'view': view(store, 'escalation', question_sha256='6' * 64)}, {})


def test_conservative_default_policy_takes_the_default_at_once(operator_home, tmp_path):
    command, log = notifier(tmp_path)
    autonomous(r3_policy='conservative_default', notify_command=command)
    store = frozen_store(tmp_path)
    record = r3(store, gate='spend_above_ceiling', default='hold')
    assert record['decision'] == 'default' and record['option'] == 'hold'
    assert not log.exists()  # nothing waits for a human, so nobody is notified
    assert 'pending' in r3(store, gate=None, default=None)
    assert len(log.read_text().splitlines()) == 1


def test_GATE_unblind_the_physicist_choosing_the_option_without_its_effect_declines_the_action(
        operator_home, tmp_path, physicist):
    calls, answers = physicist
    store = frozen_store(tmp_path)
    answers.extend([('hold', 'Keep it blinded for now.'), ('proceed', 'Open it; the controls are final.')])
    kept = r3(store, default=None)
    assert kept['decision'] == 'reject' and kept['option'] == 'hold' and kept['authorizes_effects'] is False
    with pytest.raises(AuthorityRefused, match='authorizes nothing'):
        verify(store, kept['id'], kind='r3_action')
    held = request(store, 'r3_action', {'view': view(store, 'r3_action', action_sha256='0' * 64), 'gate': 'unblind'}, {})
    assert 'pending' in held and held['unattested_record']
    opened = common.read(store, common.AUTHORITY, held['unattested_record'], common.SCHEMA)
    assert opened['decision'] == 'approve' and opened['option'] == 'proceed' and opened['label'] == LEGACY_TERMINAL
    assert opened['authorizes_effects'] is False
    with pytest.raises(AuthorityRefused):
        verify(store, opened['id'], kind='r3_action')


def test_GATE_spend_above_ceiling_an_operator_hold_or_a_default_authorizes_nothing(
        operator_home, tmp_path, capfd, monkeypatch):
    autonomous(wait_bound_seconds=60)
    store = frozen_store(tmp_path)
    clock = [common.now_ns()]
    monkeypatch.setattr(common, 'now_ns', lambda: clock[0])

    def spend(action, default=None):
        subject = {'view': view(store, 'r3_action', action_sha256=action), 'gate': 'spend_above_ceiling'}
        if default is not None:
            subject['conservative_default'] = default
        return request(store, 'r3_action', subject, {})

    held = spend('1' * 64)
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    kept = answer(store, held['pending']['request'], code, 'hold')
    assert kept['decision'] == 'reject' and kept['option'] == 'hold' and kept['label'] == OPERATOR_COMMAND
    with pytest.raises(AuthorityRefused, match='authorizes nothing'):
        verify(store, kept['id'], kind='r3_action')
    assert 'pending' in spend('2' * 64, default='hold')
    clock[0] += 61 * 10**9
    default = spend('2' * 64, default='hold')
    assert default['decision'] == 'default' and default['authorizes_effects'] is False
    with pytest.raises(AuthorityRefused, match='authorizes nothing'):
        verify(store, default['id'], kind='r3_action')
    held = spend('3' * 64)
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    spent = answer(store, held['pending']['request'], code, 'proceed')
    assert verify(store, spent['id'], kind='r3_action')['id'] == spent['id']


def test_notifications_carry_no_request_text_or_scientific_data(operator_home, tmp_path):
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = frozen_store(tmp_path)
    held = request(store, 'ci1', {'view': view(store, 'approve_plan', plan_sha256=PLAN_A),
                                  'inferred_critical_facts': ['efficiency 0.4 assumed']}, {'rung': 'smoke'})
    assert 'pending' in held and 'inferred critical facts' in held['pending']['reason']
    stored = common.read(store, 'authority-request', held['pending']['request'])
    assert stored['subject']['inferred_critical_facts'] == ['efficiency 0.4 assumed']  # kept in the store
    deviation(store, ci1(store))
    sent = log.read_text()
    # N7: the notification carries the run name and a state code only; the reason stays in the store.
    assert f'{store.run_id} | WAITING_FOR_HUMAN approve_plan' in sent and 'DEVIATION_RECORDED' in sent
    assert 'inferred critical facts' not in sent and 'WAITING FOR A HUMAN since' not in sent
    for private in ('efficiency', '0.4', 'tolerance', '0.10', '0.05', 'tighter control', 'toy model'):
        assert private not in sent, private


def test_escalation_notifies_once_and_an_operator_answer_with_the_code_resolves_it(operator_home, tmp_path, capfd):
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = frozen_store(tmp_path)
    held = r3(store, default=None)
    again = r3(store, default=None)
    assert held['pending']['request'] == again['pending']['request']
    lines = log.read_text().splitlines()
    assert lines == [f'{store.run_id} | WAITING_FOR_HUMAN r3_action'], lines  # N7: run name and state code only
    code = re.search(r'--code (\S+)', capfd.readouterr().err).group(1)
    with pytest.raises(AuthorityRefused):
        answer(store, held['pending']['request'], 'WRONG-CODE', 'proceed')
    with pytest.raises(AuthorityRefused):
        answer(store, held['pending']['request'], code, 'not-an-option')
    record = answer(store, held['pending']['request'], code, 'proceed', text='Open it; the control region is final.')
    assert record['label'] == OPERATOR_COMMAND and record['decision'] == 'approve' and record['option'] == 'proceed'
    assert r3(store, default=None)['id'] == record['id']
    with pytest.raises(AuthorityRefused):
        answer(store, held['pending']['request'], code, 'hold')
    assert len(log.read_text().splitlines()) == 1


# ------------------------------------------------------------------ effects

def test_A01_G05_heavy_compute_needs_the_exact_current_checkin1(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    assert authorize_effect(store, effect('dry'))['approve_plan'] is None
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke'))
    approval = ci1(store, rung='smoke')
    assert authorize_effect(store, effect('smoke'))['approve_plan'] == approval['id']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full'))  # beyond the approved rung
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke', plan_sha256=PLAN_B))  # changed plan
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke', budget={'events': 10**12}))  # out of envelope


def test_A08_C16_C17_go_binds_the_current_approval_and_waypoint_evidence(operator_home, tmp_path, physicist):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full'))  # no GO yet
    grant = go(store, approval)
    assert authorize_effect(store, effect('full'))['go'] == grant['id']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full', waypoint=WAYPOINT_2))  # stale waypoint bytes
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full', started_ns=grant['time_ns'] - 1))  # retrospective GO
    renewed = ci1(store, plan=PLAN_B)
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full', plan_sha256=PLAN_B))  # the old GO binds the old approval
    assert renewed['label'] == MACHINE


def test_A08_adjust_never_becomes_go(operator_home, tmp_path, capfd):
    autonomous(machine_checkins=['approve_plan'])
    store = frozen_store(tmp_path)
    approval = ci1(store)
    held = go(store, approval)
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    adjusted = answer(store, held['pending']['request'], code, 'adjust',
                      text='Rerun the smoke rung with more events first.')
    assert adjusted['decision'] == 'adjust' and adjusted['authorizes_effects'] is False
    with pytest.raises(AuthorityRefused):
        verify(store, adjusted['id'], kind='go')
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full'))
    assert authorize_effect(store, effect('smoke'))['approve_plan'] == approval['id']


def deviation(store, approval, direction='tighten', **change):
    row = {'parameter': 'tolerance', 'from': '0.10', 'to': '0.05', 'why': 'a tighter control after the smoke rung',
           'touches': ['s01'], 'direction': direction, **change}
    return request(store, 'deviation', {'view': view(store, 'deviation', approve_plan=approval['id'],
                                                     plan_sha256=PLAN_B, previous_plan_sha256=PLAN_A),
                                        'change': row}, {'rung': 'full'})


def test_A09_C20_C21_deviation_renews_plan_authority_invalidates_the_old_go_and_is_disclosed(operator_home, tmp_path):
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = frozen_store(tmp_path)
    approval = ci1(store)
    go(store, approval)
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke', plan_sha256=PLAN_B))  # changed plan, no renewed authority
    amended = deviation(store, approval)
    assert amended['label'] == MACHINE
    assert authorize_effect(store, effect('smoke', plan_sha256=PLAN_B))['deviation'] == amended['id']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('full', plan_sha256=PLAN_B))  # the GO predates the amendment
    fresh = go(store, approval, waypoint=WAYPOINT_2)
    assert authorize_effect(store, effect('full', plan_sha256=PLAN_B, waypoint=WAYPOINT_2))['go'] == fresh['id']
    # C21: the course change is disclosed at once and listed for the delivery.
    assert any(line.endswith('DEVIATION_RECORDED') for line in log.read_text().splitlines())
    assert deviations(store)[0]['change']['parameter'] == 'tolerance'


def test_C31_C32_loosening_needs_renewed_exact_authority_and_rows_are_exact(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    loosened = deviation(store, approval, direction='loosen', to='0.20')
    assert 'pending' in loosened and 'loosening a certification control' in loosened['pending']['reason']
    vague = deviation(store, approval, why=' ')
    assert vague['pending']['reason'] == 'check-in incomplete'
    assert any('parameter/from/to/why/touches' in e for e in vague['pending']['errors'])
    assert deviation(store, approval)['label'] == MACHINE


def test_C37_C38_steering_narrows_by_machine_and_widening_needs_a_human(operator_home, tmp_path):
    autonomous(budgets={'events': 1000})
    store = frozen_store(tmp_path)
    ci1(store)
    narrowed = request(store, 'steering', {'view': view(store, 'steering', policy_sha256='7' * 64),
                                           'policy': {'budgets': {'events': 10}}}, {})
    assert narrowed['label'] == MACHINE and effective_bounds(store)['budgets']['events'] == 10
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke', budget={'events': 11}))
    assert authorize_effect(store, effect('smoke', budget={'events': 10}))
    widened = request(store, 'steering', {'view': view(store, 'steering', policy_sha256='8' * 64),
                                          'policy': {'budgets': {'events': 5000}}}, {})
    assert 'pending' in widened and 'steering widens budgets.events' in widened['pending']['reason']
    assert effective_bounds(store)['budgets']['events'] == 10


def test_C39_steering_never_installs_a_plan(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    steering = request(store, 'steering', {'view': view(store, 'steering', policy_sha256='7' * 64),
                                           'policy': {'budgets': {'events': 10}}}, {})
    with pytest.raises(AuthorityRefused):
        verify(store, steering['id'], kind='ci1')
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke'))


def test_C42_final_disposition_authorizes_nothing_and_credits_no_review(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    final = request(store, 'ci3', {'view': view(store, 'final', approve_plan=approval['id'], result_sha256='d' * 64)}, {})
    assert final['kind'] == 'final' and final['decision'] == 'accept'
    assert final['authorizes_effects'] is False and final['review_credit'] is False
    for kind in ('final', 'ci1', 'go'):
        with pytest.raises(AuthorityRefused):
            verify(store, final['id'], kind=kind)


def test_A02_C09_run_tree_files_are_never_authority(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    run_dir = tmp_path / 'run'
    (run_dir / 'inputs').mkdir(parents=True)
    for name, body in (('checkin1_approval.json', {'authority': 'human_operator', 'approved_plan': 'full'}),
                       ('checkin2_go.json', {'decision': 'GO'}), ('autonomy-declaration.json', {'actions': ['approve_plan']})):
        (run_dir / 'inputs' / name).write_text(json.dumps(body))
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('smoke'))
    approval = ci1(store, rung='smoke')
    for path in (run_dir / 'inputs').iterdir():
        path.unlink()
    assert authorize_effect(store, effect('smoke'))['approve_plan'] == approval['id']
    assert current(store, 'ci1', {'plan_sha256': PLAN_A})['id'] == approval['id']


def test_a_record_from_another_run_or_without_a_label_is_refused(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    other = frozen_store(tmp_path, run_id='run-other')
    foreign = ci1(other)
    with pytest.raises(AuthorityRefused):
        verify(store, foreign['id'], kind='ci1')
    forged = {**foreign, 'run_id': store.run_id, 'uid': 'forged', 'label': 'human_operator'}
    forged.pop('id')
    store.append('authority', forged)
    with pytest.raises(AuthorityRefused):
        verify(store, 'forged', kind='ci1')


def test_a_waiver_names_its_obligations_and_never_resolves_by_machine(operator_home, tmp_path, capfd):
    autonomous(r3_policy='conservative_default', wait_bound_seconds=0)
    store = frozen_store(tmp_path)
    subject = {'view': view(store, 'r3_action', action_sha256='f' * 64), 'conservative_default': 'hold',
               'obligations': ['R05']}
    held = request(store, 'r3_action', subject, {})
    assert 'pending' in held and 'waiving ledger obligations' in held['pending']['reason']
    assert store.scan('authority') == []  # no machine default carries a waiver
    with pytest.raises(ValueError):
        request(store, 'final', {'view': view(store, 'final', approve_plan='x', result_sha256='d' * 64),
                                 'obligations': ['R05']}, {})
    code = re.search(r'--code (\S+)', capfd.readouterr().err).group(1)
    record = answer(store, held['pending']['request'], code, 'proceed', text='Waive R05 for this fictional run.')
    assert record['label'] == OPERATOR_COMMAND and record['subject']['obligations'] == ['R05']
    assert request(store, 'r3_action', subject, {})['id'] == record['id']


def test_a_higher_rung_is_a_new_decision_bound_to_its_own_bounds(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    smoke_only = ci1(store, rung='smoke')
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, effect('pilot'))
    full = ci1(store, rung='full')
    assert full['id'] != smoke_only['id'] and full['bounds']['rung'] == 'full'
    go(store, full)
    assert authorize_effect(store, effect('full'))['approve_plan'] == full['id']


def test_a_pause_hold_is_not_answerable_and_a_later_escalation_still_notifies(operator_home, tmp_path, capfd):
    from ravel.controller.authority import stop
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = frozen_store(tmp_path)
    stop.record_control(store, 'pause', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='pause')
    held = r3(store, default=None)
    assert 'pause requested' in held['pending']['reason'] and not log.exists()
    with pytest.raises(AuthorityRefused, match='pause requested'):
        answer(store, held['pending']['request'], 'ANY-CODE', 'proceed')
    capfd.readouterr()
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='resume')
    escalated = r3(store, default=None)
    assert escalated['pending']['request'] != held['pending']['request']
    assert len(log.read_text().splitlines()) == 1
    code = re.search(r'--code (\S+)', capfd.readouterr().err).group(1)
    assert answer(store, escalated['pending']['request'], code, 'hold')['option'] == 'hold'


def test_every_record_and_operator_configuration_validates_against_its_published_schema(
        operator_home, tmp_path, physicist, capfd):
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    from ravel.controller.authority import operator as ledger, stop
    schemas = files('ravel').joinpath('data/controller/schemas')
    from ravel.controller.authority.schema import authority_record
    base = json.loads(schemas.joinpath('authority-record.v1.json').read_text())
    records = Draft202012Validator(authority_record(base))
    configs = Draft202012Validator(json.loads(schemas.joinpath('operator-config.v1.json').read_text()))
    autonomous(wait_bound_seconds=0)
    store = frozen_store(tmp_path)
    approval = ci1(store)
    go(store, approval)
    deviation(store, approval)
    r3(store, default='hold')
    held = r3(store, gate='spend_above_ceiling', default=None)
    code = re.findall(r'--code (\S+)', capfd.readouterr().err)[-1]
    answer(store, held['pending']['request'], code, 'proceed', text='Spend it; fictional budget.')
    request(store, 'ci3', {'view': view(store, 'final', approve_plan=approval['id'], result_sha256='d' * 64)}, {})
    stop.record_control(store, 'stop', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='done')
    bodies = store.scan('authority')
    assert {b['kind'] for b in bodies} == {'approve_plan', 'go', 'deviation', 'r3_action', 'final', 'stop'}
    for body in bodies:
        response = common.read(store, 'authority', next(r['id'] for r in common.scan(store, 'authority')
                                                       if r['uid'] == body['uid']))
        assert list(records.iter_errors(response)) == [], body['kind']
        assert store.read('authority', response['id']) == body
    for row in ledger._ledger_rows():
        assert list(configs.iter_errors(row['record']['config'])) == []


def test_notify_uses_the_frozen_operator_command_only(operator_home, tmp_path):
    from ravel.controller.authority import notify, operator as ledger
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = frozen_store(tmp_path)
    ledger.set_values({'notify_command': None})  # a later operator change does not reach a frozen run
    assert notify(store, 'QUALIFIED ENDING: the event budget ran out')['status'] == 'sent'
    assert 'QUALIFIED ENDING' in log.read_text()
    quiet = frozen_store(tmp_path, run_id='run-quiet')
    assert notify(quiet, 'nothing configured')['status'] == 'disabled'


def test_an_effect_may_name_its_rung_as_plan_but_not_two_rungs(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store, rung='smoke')
    alias = {'id': 'e2', 'plan': 'smoke', 'pins': {'plan_sha256': PLAN_A}}
    assert authorize_effect(store, alias)['approve_plan'] == approval['id']
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, {**alias, 'rung': 'full'})
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, {'id': 'e3', 'pins': {'plan_sha256': PLAN_A}})
