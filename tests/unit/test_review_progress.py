"""Synthetic no-progress controls: no model, numerical or native execution."""
from copy import deepcopy

import pytest

from ravel.workflow import physics_review as review
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run, opened, correct, make_attempt, check_packet, reject, accept
from bound_review import bound_review


def repeated_run(run, *, limit=3, values=(1, 1)):
    root, _ = run
    policy = read_json(root / review.POLICY); policy['max_redos'] = limit
    atomic_json(root / review.POLICY, policy)
    opened(run); reject(root)
    for index, value in enumerate(values):
        (root / 'inputs/settings.cfg').write_text(f'value={index + 2}\n')
        correction = review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                                 stages=['detector'], recheck_checks=['agreement'])
        attempt = make_attempt(root, value=value); check_packet(root, attempt)
        opened((root, attempt), correction_id=correction['correction_id'])
        reject(root, name=f'F{index + 2}')
    return root


def test_two_unchanged_redos_route_history_to_decider_and_preserve_refusal(run):
    root = repeated_run(run)
    state = review.status(root)
    assert state['state'] == 'send_back'
    assert state['redo_counts_by_stage'] == {'detector': 2}
    assert state['redos_remaining'] == 1
    candidates = state['limitation_candidates']; assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate['consecutive_no_progress'] == 2
    assert candidate['route'] == 'physics_decider' and candidate['classification'] == 'limitation_candidate'
    assert len(candidate['history']) == 2 and all(not r['progress'] for r in candidate['history'])
    assert candidate['finding']['id'] == 'F1'  # original evidence remains visible
    (root / 'inputs/settings.cfg').write_text('value=4\n')
    with pytest.raises(ValueError, match='no progress after two redos'):
        review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                    stages=['detector'], recheck_checks=['agreement'])
    assert review.status(root)['redos_used'] == 2
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')


def test_changed_cited_result_resets_no_progress_counter(run):
    root = repeated_run(run, values=(1, 2))
    state = review.status(root)
    assert state['limitation_candidates'] == []
    assert state['finding_progress'][0]['consecutive_no_progress'] == 0
    (root / 'inputs/settings.cfg').write_text('value=4\n')
    correction = review.authorize_correction(root, actor_id='physicist', changed_paths=['inputs/settings.cfg'],
                                            stages=['detector'], recheck_checks=['agreement'])
    assert correction['redo_number'] == 3


def test_exhausted_bounds_have_stable_human_wait_and_no_approved_progress(run):
    root = repeated_run(run, limit=2)
    first = review.status(root); second = review.status(root)
    waiting = first['waiting_for_human']
    assert waiting == second['waiting_for_human']
    assert waiting['message'].startswith('WAITING FOR A HUMAN since ')
    assert 'exhausted' in waiting['reason'] and waiting['needed']
    assert first['last_approved_progress_utc'] is None
    assert first['seconds_since_last_approved_progress'] is None


def test_escalation_is_machine_record_and_cannot_preserve_compute_acceptance(run):
    root, _ = run; opened(run); accept(root)
    prior = review.status(root)
    assert prior['last_approved_progress_utc'] and prior['seconds_since_last_approved_progress'] >= 0
    record = review.escalate(root, reason='A new boundary needs a decision.', needed='Review the retained scope.')
    assert record['authority'] == 'machine_escalation' and record['execution_authorized'] is False
    assert review.escalate(root, reason=record['reason'], needed=record['needed']) == record
    state = review.status(root)
    assert state['state'] == 'escalated'
    assert state['waiting_for_human']['since_utc'] == record['utc']
    assert state['last_approved_progress_utc'] == prior['last_approved_progress_utc']
    assert review.gate_errors(root, 'bulk') and review.gate_errors(root, 'delivery')
    reg, events = review._read(root)
    document = {'schema_version': 1, 'registration': reg, 'events': events,
                'checkpoint': read_json(root / review.HEAD), 'action': 'history', 'stage': None}
    assert review.validate_snapshot(document, require_admission=False) == []
    bad = deepcopy(document); bad['events'][-1]['execution_authorized'] = True
    assert review.validate_snapshot(bad, require_admission=False)


def test_graph_unchanged_requests_keep_refusal_and_report_candidate_without_calls(tmp_path):
    from test_finding_routing import graph_fixture, classified
    from ravel.workflow import agent_graph
    root, sha = graph_fixture(tmp_path, reworks=3)
    first = agent_graph.rework(root, findings=[classified(sha=sha)], reason='repair')
    agent_graph.rework(root, findings=[classified(sha=sha)], reason='unchanged retry')
    state = agent_graph.rework(root, findings=[classified(sha=sha)], reason='unchanged retry again')
    assert state['reworks'] == first['reworks'] == 1
    assert state['usage']['calls'] == first['usage']['calls'] == 0
    assert state['nodes'] == first['nodes']
    candidate = state['limitation_candidates'][0]
    assert candidate['unchanged_requests'] == 2 and len(candidate['history']) == 3
    assert candidate['route'] == 'physics_decider' and candidate['execution_authorized'] is False
    assert state['redo_counts_by_stage']['produce'] == 1


def test_notification_is_opt_in_argv_only_and_does_not_grant_authority(run, monkeypatch):
    from ravel.workflow import scientific_autonomy
    import subprocess
    from types import SimpleNamespace
    root, _ = run; opened(run)
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda argv, **kwargs: calls.append((argv, kwargs)) or SimpleNamespace(returncode=0))
    assert scientific_autonomy.notify_waiting(root)['status'] == 'disabled'
    assert scientific_autonomy.notify_waiting(root, command=['local-notifier'])['status'] == 'not_waiting'
    assert calls == []
    review.escalate(root, reason='Boundary reached.\nInput still missing.', needed='Supply the missing source.')
    result = scientific_autonomy.notify_waiting(root, command=['local-notifier', '--quiet'])
    argv, options = calls[0]
    assert argv == ['local-notifier', '--quiet', str(root), 'Boundary reached. Input still missing.']
    assert options['shell'] is False and options['stdin'] is subprocess.DEVNULL and options['timeout'] == 10
    assert set(options['env']) <= {'PATH', 'LANG'}
    assert result['execution_authorized'] is False
    assert review.gate_errors(root, 'bulk')
    with pytest.raises(ValueError, match='argv list'):
        scientific_autonomy.notify_waiting(root, command='unsafe shell string')


def test_escalation_refuses_new_cycle_votes(run):
    root, _ = run; opened(run)
    review.escalate(root, reason='The approved boundary was reached.', needed='Review the allowed scope.')
    before = (root / review.HEAD).read_bytes()
    with pytest.raises(ValueError, match='cannot receive another review'):
        review.submit_review(root, role='physics_critic', actor_id='critic', verdict='accept',
                             summary='An attempted override.', findings=[], claim_scope='diagnostic')
    assert (root / review.HEAD).read_bytes() == before
    assert review.gate_errors(root, 'delivery')


@pytest.mark.parametrize('scientific_route', [False, True])
def test_public_status_shows_wait_and_progress_on_both_routes(run, monkeypatch, capsys, scientific_route):
    from types import SimpleNamespace
    from ravel import cli
    from ravel.workflow import current_state, science
    import json
    root, _ = run; opened(run)
    review.escalate(root, reason='Input boundary.', needed='Supply the missing source.')
    packet = lambda *a, **k: {'execution': {'status': 'approved'}, 'next_required': 'old action'}
    monkeypatch.setattr(current_state, 'build_packet', packet)
    monkeypatch.setattr(science, 'packet', packet)
    if scientific_route:
        (root / 'inputs/science-plan.json').write_text('{}')
    args = SimpleNamespace(rundir=root, write=False, retained_study=False, notification_command=None)
    assert cli._status(args) == 0
    value = json.loads(capsys.readouterr().out)
    assert value['next_required'].startswith('WAITING FOR A HUMAN since ')
    assert value['physics_review']['redo_counts_by_stage'] == {}
    assert value['physics_review']['last_approved_progress_utc'] is None


def test_escalation_without_original_contract_reports_unavailable_and_cli_failure(run, tmp_path, capsys):
    import json
    root, _ = run; opened(run)
    request = tmp_path / 'escalation.json'
    atomic_json(request, {'reason': 'Source unavailable.', 'needed': 'Review the original scope.'})
    assert review.main(['--rundir', str(root), 'escalate', '--request', str(request)]) == 1
    response = json.loads(capsys.readouterr().out)
    assert response['qualified_ending']['status'] == 'unavailable'
    assert response['qualified_ending']['reason']
    assert response['qualified_ending']['execution_authorized'] is False
    assert review.status(root)['state'] == 'escalated'
    assert not (root / 'outputs/completion/qualified-delivery.json').exists()
    _, events = review._read(root)
    assert 'qualified_ending' not in events[-1]
    assert response['sha256'] == events[-1]['sha256']


def test_ordinary_and_stopped_reviews_do_not_invoke_new_terminal_reporting(run, monkeypatch):
    from ravel.workflow import task_completion
    root, _ = run; opened(run)
    calls = []
    monkeypatch.setattr(task_completion, 'qualified_delivery', lambda *a, **kw: calls.append('report'))
    bound_review(root, role='physics_critic', verdict='accept',
                 summary='Current scoped evidence.', claim_scope='diagnostic')
    # A decider vote is dispatched only after both independent decisions; the stop (any role ends the
    # cycle, and the ending does not depend on it) is the verifier's, which keeps two bound reviews.
    bound_review(root, role='skeptical_verifier', verdict='stop',
                 summary='Retain the existing stopping boundary.')
    assert calls == [] and review.status(root)['state'] == 'stopped'


def test_limitation_only_vote_with_zero_redos_is_not_an_exhausted_defect_route(run, monkeypatch):
    from ravel.workflow import task_completion
    from test_finding_routing import journal_classified
    root, _ = run
    policy = read_json(root / review.POLICY); policy['max_redos'] = 0
    atomic_json(root / review.POLICY, policy)
    opened(run)
    finding = journal_classified(root, 'limitation')
    calls = []
    monkeypatch.setattr(task_completion, 'qualified_delivery', lambda *a, **kw: calls.append('report'))
    event = bound_review(root, role='physics_critic', verdict='send_back',
                         summary='Retain the source limitation.', findings=[finding])
    assert calls == [] and 'qualified_ending' not in event
    assert review.status(root)['state'] == 'awaiting_review'
