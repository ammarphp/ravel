"""Scientific studies and live steering: attempt expenditure, approval registration and operator
reapproval are decided at the serialized steering boundary, for both study versions.

Each test drives the real approval command or ``science.run`` with its real supervisor; a steering
change is injected at the named interval by wrapping the preceding step, never by replacing a check.
"""
import json

import pytest

from ravel.workflow import execution, gate_wiring as gw, rdj_custody as custody, science
from ravel.workflow.state_io import read_json
from test_science_reapproval import amended, approve, archived, reviewed_study, study
from test_science_review_envelope import planned  # noqa: F401  (fixture)


def versioned(version, tmp_path, monkeypatch, **options):
    return study(tmp_path, monkeypatch, **options) if version == 'v1' else reviewed_study(tmp_path, monkeypatch)


def resume(rd):
    event = gw.record_steering(rd, 'Continue the study.', effect='resume')
    gw.ack_steering(rd, event['event_id'], interpretation='Continue within the approved scope.')


# ---------------------------------------------------------------- D4: attempt expenditure

@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_a_pause_after_the_preliminary_check_does_not_spend_the_attempt(tmp_path, monkeypatch, version):
    rd = versioned(version, tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    preliminary = science._steering_admission

    def then_pause(rundir):
        preliminary(rundir)  # the preliminary check passes; the pause lands before the final admission
        gw.record_steering(rundir, 'Pause the study.', effect='pause')
    monkeypatch.setattr(science, '_steering_admission', then_pause)
    assert science.run(rd) != 0
    monkeypatch.setattr(science, '_steering_admission', preliminary)
    # The supervisor refused at its serialized launch: the refusal is kept, nothing ran, nothing is spent.
    record = execution.load_execution(rd)['stages']['science']
    assert record['prelaunch_refusal']['by'] == 'steering' and record['child_pid'] is None
    assert not (rd / 'execution_attempt.json').exists() and not science._attempt_spent(rd)
    kept = sorted(p.name for p in (rd / science.REFUSED_ATTEMPTS).iterdir())
    assert kept == sorted([f"{record['attempt_id']}.token.json"]
                          + ([f"{record['attempt_id']}.journal.json"] if version == 'v2' else []))
    assert science.packet(rd)['execution']['status'] == 'approved'
    # While paused the preliminary check still refuses, again without spending anything.
    with pytest.raises(ValueError, match='steering'):
        science.run(rd)
    assert not science._attempt_spent(rd)
    resume(rd)
    assert science.run(rd) == 0
    state = science.packet(rd)
    # A reviewed study's completed attempt awaits its review; a version-one study is complete.
    assert state['errors'] == [] and state['execution']['status'] == ('completed' if version == 'v1' else 'awaiting_review')
    # The one attempt is now spent.
    with pytest.raises(ValueError, match='spent'):
        science.run(rd)


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_an_attempt_that_launched_stays_spent(tmp_path, monkeypatch, version):
    rd = versioned(version, tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    assert science.run(rd) == 0
    token = (rd / 'execution_attempt.json').read_bytes()
    (rd / 'execution_attempt.json').unlink()  # removing the token does not unspend a launched attempt
    assert science._attempt_spent(rd)
    with pytest.raises(ValueError, match='spent'):
        science.run(rd)
    (rd / 'execution_attempt.json').write_bytes(token)


# ---------------------------------------------------------------- D5: approval registration under steering

BOUNDED = dict(autonomy='bounded_delegated', checkin_thresholds={}, hard_ceilings={}, signoff_steps=[],
               unknown_cost='ask', on_pause='drain', result_acceptance='physicist')
MANUAL = {**BOUNDED, 'autonomy': 'manual'}


def scripted_study(version, tmp_path, monkeypatch):
    if version == 'v1':
        return study(tmp_path, monkeypatch, mode='scripted_yes')
    from test_research_cycle import specification
    from method_decision_fixture import admit_method
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    source = specification(tmp_path, 'supplied-source', grouped=False)
    document = read_json(source['path'])
    document['approval_mode'] = 'scripted_yes'
    from ravel.workflow.state_io import atomic_json
    atomic_json(source['path'], document)
    rd = tmp_path / 'reviewed-run'
    science.plan(rd, source['path'])
    admit_method(rd)
    return science.root(rd)


def set_policy(rd, value, text):
    event = gw.set_steering_policy(rd, value, source_text=text)
    gw.ack_steering(rd, event['event_id'], interpretation='Policy retained.')
    return event


def scope_hold(rd):
    event = gw.record_steering(rd, 'Extend the study to the wider range.', effect='redirect')
    gw.ack_steering(rd, event['event_id'], interpretation='Plan revised.', amended_plan=amended(rd))
    assert not gw.dispatch_permitted(rd, 'science')[0]


def events(rd):
    return [r['record'] for r in custody.rows(rd, 'steering')]


def after_preliminary_check(monkeypatch, change):
    """Run ``change`` right after the approval writer's preliminary authority check passes."""
    preliminary = science._admit_approval

    def then_change(rd, authority):
        reapproval = preliminary(rd, authority)
        change(rd)
        return reapproval
    monkeypatch.setattr(science, '_admit_approval', then_change)
    return lambda: monkeypatch.setattr(science, '_admit_approval', preliminary)


def before_registration(monkeypatch, change):
    """Run ``change`` after the receipt was computed and before the registration transaction."""
    register = science._register_approval

    def then_register(rd, receipt, **options):
        change(rd)
        return register(rd, receipt, **options)
    monkeypatch.setattr(science, '_register_approval', then_register)
    return lambda: monkeypatch.setattr(science, '_register_approval', register)


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_a_manual_policy_recorded_during_a_machine_reapproval_refuses_it_and_keeps_the_receipt(
        tmp_path, monkeypatch, version):
    rd = scripted_study(version, tmp_path, monkeypatch)
    set_policy(rd, BOUNDED, 'Machine reapproval is delegated within the plan.')
    science.approve(rd, 'yes', scripted=True)
    original = (rd / science.APPROVAL).read_bytes()
    scope_hold(rd)
    before = events(rd)
    restore = after_preliminary_check(monkeypatch, lambda d: gw.set_steering_policy(
        d, MANUAL, source_text='Manual signoff from here on.'))
    with pytest.raises(ValueError, match='operator signoff'):
        science.approve(rd, 'yes', scripted=True)
    restore()
    # The previous current receipt stays; nothing was archived or registered for the refusal.
    assert (rd / science.APPROVAL).read_bytes() == original and archived(rd) == []
    later = events(rd)[len(before):]
    assert [e['event'] for e in later] == ['steering']  # only the operator's policy event
    assert not gw.dispatch_permitted(rd, 'science')[0]
    # The operator reapproves through the supported command (D8) and the study runs.
    gw.ack_steering(rd, later[0]['record']['event_id'], interpretation='Policy retained.')
    assert approve(rd, 'The operator re-approves the revised plan.') == 0
    assert [p.read_bytes() for p in archived(rd)] == [original]
    assert gw.dispatch_permitted(rd, 'science')[0]
    assert science.run(rd) == 0


def test_a_manual_policy_recorded_during_a_delegated_first_approval_leaves_no_receipt(planned, tmp_path, monkeypatch):
    from test_autonomy_v2_authority_joins import existing_ci1, opt_in
    rd, _ = existing_ci1(planned, tmp_path)
    source = tmp_path / 'actual-ci1-response.txt'
    source.write_text('Run autonomously within the original approved bounds.')
    opt_in(rd, source)
    before = events(rd)
    restore = before_registration(monkeypatch, lambda d: gw.set_steering_policy(
        d, MANUAL, source_text='Manual signoff from here on.'))
    with pytest.raises(ValueError, match='operator signoff'):
        science.approve_delegated(rd)
    restore()
    assert not (rd / science.APPROVAL).exists() and archived(rd) == []
    assert not any(e['event'] in ('approval', 'approval_superseded') for e in events(rd)[len(before):])


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_an_operator_reapproval_whose_checkin_changes_before_registration_keeps_the_previous_receipt(
        tmp_path, monkeypatch, version):
    rd = versioned(version, tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    original = (rd / science.APPROVAL).read_bytes()
    scope_hold(rd)
    before = events(rd)
    # The policy change rewrites CHECK-IN 1, which the operator's receipt was computed against.
    restore = before_registration(monkeypatch, lambda d: gw.set_steering_policy(
        d, MANUAL, source_text='Manual signoff from here on.'))
    assert approve(rd, 'Re-approved after the redirect.') != 0
    restore()
    assert (rd / science.APPROVAL).read_bytes() == original and archived(rd) == []
    assert [e['event'] for e in events(rd)[len(before):]] == ['steering']
    # Against the current CHECK-IN 1 the same reapproval is recorded.
    gw.ack_steering(rd, events(rd)[-1]['record']['event_id'], interpretation='Policy retained.')
    assert approve(rd, 'Re-approved after the redirect and the policy.') == 0
    assert [p.read_bytes() for p in archived(rd)] == [original]
    science.verify_plan(rd, approved=True)
    assert science.run(rd) == 0


# ---------------------------------------------------------------- D8: operator reapproval of a scripted study

@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_the_operator_reapproves_a_scripted_study_and_its_scripted_history_is_kept(tmp_path, monkeypatch, version):
    rd = scripted_study(version, tmp_path, monkeypatch)
    science.approve(rd, 'yes', scripted=True)
    original = (rd / science.APPROVAL).read_bytes()
    assert approve(rd, 'An operator approval without a hold.') != 0  # nothing to reconcile yet
    scope_hold(rd)
    # Scripted (and machine) reapproval stays refused: no policy delegates it.
    with pytest.raises(ValueError, match='operator signoff'):
        science.approve(rd, 'yes', scripted=True)
    assert (rd / science.APPROVAL).read_bytes() == original
    assert approve(rd, 'The operator re-approves the revised plan.') == 0
    # The scripted receipt stays in the history; the new receipt keeps the proposal's mode.
    assert [p.read_bytes() for p in archived(rd)] == [original]
    assert json.loads(original)['approval_mode'] == 'scripted_yes'
    current = read_json(rd / science.APPROVAL)
    assert current['approval_mode'] == 'scripted_yes' and current['quote'] == 'The operator re-approves the revised plan.'
    assert current['authority'] not in ('scripted_experiment', 'delegated_machine')
    rows = events(rd)
    assert [r['event'] for r in rows[-2:]] == ['approval_superseded', 'approval']
    assert rows[-2]['approval_sha256'] == gw._sha(original)
    assert rows[-1]['authority'] == 'unknown' and rows[-1]['proposal_approval_mode'] == 'scripted_yes'
    assert gw.dispatch_permitted(rd, 'science')[0] and gw.steering_errors(rd) == []
    science.verify_plan(rd, approved=True)
    assert science.run(rd) == 0


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_a_scripted_reapproval_is_refused_where_the_policy_requires_the_operator(tmp_path, monkeypatch, version):
    rd = scripted_study(version, tmp_path, monkeypatch)
    set_policy(rd, BOUNDED, 'Machine reapproval is delegated within the plan.')
    science.approve(rd, 'yes', scripted=True)
    original = (rd / science.APPROVAL).read_bytes()
    set_policy(rd, {**BOUNDED, 'signoff_steps': ['science']}, 'The science stage needs the operator.')
    scope_hold(rd)
    with pytest.raises(ValueError, match='operator signoff'):
        science.approve(rd, 'yes', scripted=True)
    assert (rd / science.APPROVAL).read_bytes() == original and archived(rd) == []
    assert approve(rd, 'The operator re-approves the revised plan.') == 0
    assert gw.dispatch_permitted(rd, 'science')[0]
