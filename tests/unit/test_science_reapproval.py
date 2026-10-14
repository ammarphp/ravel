"""A scientific study held by steering obtains its reapproval through the approval command.

The original receipt is preserved, the reapproval is refused without a hold to reconcile or
without the authority the hold needs, and the reapproved study runs.
"""
import json

import pytest

from method_decision_fixture import admit_method
from ravel import cli
from ravel.workflow import gate_wiring as gw, rdj_custody as custody, science
from ravel.workflow.state_io import atomic_json, read_json

ARCHIVE = 'inputs/science-approvals'


def study(tmp_path, monkeypatch, *, mode='physicist'):
    from test_scientific_quantities import contract, event
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    atomic_json(tmp_path / 'contract.json', contract())
    (tmp_path / 'records.jsonl').write_text('\n'.join(
        json.dumps(e) for e in [event('a', [[.5]], 2), event('b', [[2]], -1)]) + '\n')
    atomic_json(tmp_path / 'spec.json', {
        'schema_version': 1, 'mode': 'quantities', 'source': 'synthetic signed-weight control',
        'assumptions': ['Synthetic numbers validate transport, not physics'], 'max_seconds': 45,
        'approval_mode': mode, 'task': {'contract': 'contract.json', 'records': 'records.jsonl'}})
    rd = tmp_path / 'run'
    science.plan(rd, tmp_path / 'spec.json')
    admit_method(rd)
    return science.root(rd)


def approve(rd, quote):
    return cli.main(['approve', '--rundir', str(rd), '--quote', quote])


def policy(**extra):
    return dict(autonomy='manual', checkin_thresholds={}, hard_ceilings={}, signoff_steps=[],
                unknown_cost='ask', on_pause='drain', result_acceptance='physicist', **extra)


def amended(rd):
    path = rd / 'inputs/amended.json'
    path.write_text('{"plan":"reconciled"}')
    return path


def archived(rd):
    return sorted((rd / ARCHIVE).glob('*.json')) if (rd / ARCHIVE).is_dir() else []


def test_scope_hold_on_an_approved_study_is_reconciled_by_the_approval_command(tmp_path, monkeypatch):
    rd = study(tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    original = (rd / science.APPROVAL).read_bytes()
    event = gw.record_steering(rd, 'Extend the study to the wider range.', effect='redirect')
    gw.ack_steering(rd, event['event_id'], interpretation='Plan revised.', amended_plan=amended(rd))
    assert not gw.dispatch_permitted(rd, 'science')[0]
    # The held launch is refused before the study's one attempt is spent.
    with pytest.raises(ValueError, match='steering'):
        science.run(rd)
    assert not (rd / 'execution_attempt.json').exists()
    assert approve(rd, 'Re-approved after the redirect.') == 0
    # Append-only: the original receipt is preserved byte for byte and the new one is current.
    assert [p.read_bytes() for p in archived(rd)] == [original]
    current = read_json(rd / science.APPROVAL)
    assert current['quote'] == 'Re-approved after the redirect.' and (rd / science.APPROVAL).read_bytes() != original
    events = [r['record'] for r in custody.rows(rd, 'steering')]
    superseded = [e for e in events if e['event'] == 'approval_superseded']
    assert len(superseded) == 1 and superseded[0]['approval_sha256'] == gw._sha(original)
    assert events[-1]['event'] == 'approval' and events[-1]['approval_sha256'] == gw._approval_digest(rd)
    assert events[-1]['authority'] == 'unknown'
    assert gw.dispatch_permitted(rd, 'science')[0] and gw.steering_errors(rd) == []
    assert science.run(rd) == 0
    assert science.packet(rd)['lifecycle_verdict'] == 'PASS'


def test_policy_change_after_approval_is_reconciled_by_the_approval_command(tmp_path, monkeypatch):
    rd = study(tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    changed = gw.set_steering_policy(rd, policy(), source_text='Keep manual signoff from here on.')
    gw.ack_steering(rd, changed['event_id'], interpretation='Policy retained.')
    with pytest.raises((ValueError, OSError)):
        science.run(rd)
    assert approve(rd, 'Re-approved under the recorded policy.') == 0
    assert len(archived(rd)) == 1
    assert science.run(rd) == 0


def test_reapproval_without_a_hold_to_reconcile_is_refused(tmp_path, monkeypatch, capsys):
    rd = study(tmp_path, monkeypatch)
    assert approve(rd, 'Approved as planned.') == 0
    original = (rd / science.APPROVAL).read_bytes()
    capsys.readouterr()
    assert approve(rd, 'A second approval nobody asked for.') != 0
    assert 'already recorded' in capsys.readouterr().err
    assert (rd / science.APPROVAL).read_bytes() == original and archived(rd) == []
    assert not any(r['record']['event'] == 'approval_superseded' for r in custody.rows(rd, 'steering'))


def test_scripted_reapproval_of_a_scope_hold_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    rd = study(tmp_path, monkeypatch, mode='scripted_yes')
    science.approve(rd, 'yes', scripted=True)
    original = (rd / science.APPROVAL).read_bytes()
    event = gw.record_steering(rd, 'Extend the study to the wider range.', effect='redirect')
    gw.ack_steering(rd, event['event_id'], interpretation='Plan revised.', amended_plan=amended(rd))
    before = custody.rows(rd, 'steering')
    with pytest.raises(ValueError, match='authority'):
        science.approve(rd, 'yes', scripted=True)
    assert (rd / science.APPROVAL).read_bytes() == original and archived(rd) == []
    assert custody.rows(rd, 'steering') == before
    # A custody row for the unchanged receipt reconciles nothing either.
    custody.append(rd, 'steering', {'event': 'approval', 'approval_sha256': gw._approval_digest(rd),
                                    'authority': 'scripted_experiment'})
    assert not gw.dispatch_permitted(rd, 'science')[0]
    with pytest.raises(ValueError, match='steering'):
        science.run(rd)
    assert not (rd / 'execution_attempt.json').exists()


def test_refused_first_approval_leaves_no_receipt_behind(tmp_path, monkeypatch):
    """A manual policy recorded before CHECK-IN 1 refuses a machine approval before it writes."""
    rd = study(tmp_path, monkeypatch, mode='scripted_yes')
    configured = gw.set_steering_policy(rd, policy(), source_text='Keep manual signoff.')
    gw.ack_steering(rd, configured['event_id'], interpretation='Policy retained.')
    with pytest.raises(ValueError, match='authority'):
        science.approve(rd, 'yes', scripted=True)
    assert not (rd / science.APPROVAL).exists()
    # The refusal repeats itself; it is never replaced by "approval already recorded".
    with pytest.raises(ValueError, match='authority'):
        science.approve(rd, 'yes', scripted=True)


def test_operator_quote_approves_a_study_under_a_manual_policy(tmp_path, monkeypatch):
    rd = study(tmp_path, monkeypatch)
    configured = gw.set_steering_policy(rd, policy(), source_text='Keep manual signoff.')
    gw.ack_steering(rd, configured['event_id'], interpretation='Policy retained.')
    assert approve(rd, 'Approved under the manual policy.') == 0
    assert archived(rd) == []
    assert science.run(rd) == 0


def reviewed_study(tmp_path, monkeypatch):
    """A prospective reviewed (version two) study approved by operator quote."""
    from test_research_cycle import specification
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    source = specification(tmp_path, 'supplied-source', grouped=False)
    document = read_json(source['path'])
    document['approval_mode'] = 'physicist'
    atomic_json(source['path'], document)
    rd = tmp_path / 'reviewed-run'
    science.plan(rd, source['path'])
    admit_method(rd)
    return science.root(rd)


def test_reviewed_study_reapproval_preserves_the_receipt_and_verifies(tmp_path, monkeypatch):
    rd = reviewed_study(tmp_path, monkeypatch)
    assert science.review_enabled(rd)
    assert approve(rd, 'Approved as planned.') == 0
    original = (rd / science.APPROVAL).read_bytes()
    assert approve(rd, 'Nothing to reconcile.') != 0
    event = gw.record_steering(rd, 'Extend the study to the wider range.', effect='redirect')
    gw.ack_steering(rd, event['event_id'], interpretation='Plan revised.', amended_plan=amended(rd))
    with pytest.raises(ValueError, match='steering'):
        science.run(rd)
    assert not (rd / 'execution_attempt.json').exists()
    assert approve(rd, 'Re-approved after the redirect.') == 0
    assert [p.read_bytes() for p in archived(rd)] == [original]
    science.verify_plan(rd, approved=True)
    assert gw.dispatch_permitted(rd, 'science')[0]
    assert science.run(rd) == 0
