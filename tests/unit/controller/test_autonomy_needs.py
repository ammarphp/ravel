"""Autonomous mode for unattended runs: the operator's grant, its bounds and the waits for a human.

Unit proofs of the needs of an unattended controller run (N1-N10) and of the gaps around it (G1-G4):
a grant a confined worker cannot create, widen, copy or re-date; bounds in units that fit supplied data and
batch work; the project instruction document pinned for every agent; a project-wide provider policy;
review without a sandbox labelled, never self-reviewed; every exhausted bound named in a qualified ending;
one notification per new wait, carrying the run name and a state code only; crashes typed as failures;
restarts that never redo work; and an audit trail of the controller's decisions. Every name is fictional.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from test_p06_support import (autonomous, frozen_store, new_store, operator_home, ownership,  # noqa: F401
                              view)
from test_p06_request import PLAN_A, ci1, effect, notifier
from ravel.controller.authority import (AuthorityRefused, MACHINE, OPERATOR_COMMAND, authorize_effect, autonomy,
                                        common, freeze_child, freeze_mode, operator, stop)

PAST = '2001-01-01T00:00:00Z'
FUTURE = '2999-01-01T00:00:00Z'


def _none_effect(**budget):
    return {'id': 'e0', 'rung': 'none', 'stage': 'fictional-stage', 'budget': budget}


def _store_with_dir(tmp_path, run_dir=None, run_id='run-0001', contract=None):
    """A frozen store whose run directory is known (the controller's RunStore carries it)."""
    run_dir = Path(run_dir or tmp_path / 'project' / 'runs' / run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    store = new_store(tmp_path, run_id)
    store.run_dir = run_dir
    freeze_mode(store, contract or {'prompt': 'Compute the fictional observable for the toy model.'},
                run_dir=run_dir)
    return store


# ---- N1: a grant a confined worker cannot create, widen or extend ------------------------------------------

def test_N1_grant_fields_are_written_by_the_operator_cli_and_validated(operator_home, tmp_path, capsys):
    from ravel.controller.authority import cli
    project = tmp_path / 'project'
    assert cli.main(['init', '--mode', 'autonomous', '--expires-at', FUTURE, '--project-scope', str(project),
                     '--deadline', FUTURE, '--deadline-margin', '43200', '--budget', 'input_bytes=1000000',
                     '--budget', 'batch_jobs=300', '--budget', 'batch_cpu_hours=40000.5']) == 0
    written = json.loads(capsys.readouterr().out)
    assert written['expires_at'] == FUTURE and written['project_scope'] == [str(project)]
    assert written['deadline'] == {'at': FUTURE, 'margin_seconds': 43200}
    assert written['budgets']['input_bytes'] == 1000000 and written['budgets']['batch_cpu_hours'] == 40000.5
    boundary = autonomy.boundary_statement()  # shown by `ravel operator status` with each run
    assert boundary['unconfined_same_uid_can_forge'] is True  # recorded honestly
    assert boundary['confined_worker_can_write_grant'] is False
    for bad in (['--expires-at', 'tomorrow'], ['--project-scope', 'relative/path'], ['--deadline', FUTURE]):
        assert cli.main(['set', *bad]) == 2


def test_N1_earlier_ledgers_without_the_optional_bounds_still_validate(operator_home):
    config = operator.default_config()
    for key in operator.OPTIONAL_BUDGET_KEYS:
        config['budgets'].pop(key)
    for key in ('expires_at', 'project_scope', 'deadline', 'instruction_document', 'disk_free_floor_bytes'):
        config.pop(key)
    checked = operator.validate(config)
    assert all(checked['budgets'][k] == operator.DEFAULT_BUDGETS[k] for k in operator.OPTIONAL_BUDGET_KEYS)
    assert checked['budgets']['input_bytes'] is None and checked['budgets']['recoveries'] == 2
    with pytest.raises(ValueError):
        operator.validate({**config, 'budgets': {k: v for k, v in config['budgets'].items() if k != 'events'}})


def test_N1_a_rewritten_grant_is_refused_at_every_admission_and_at_intake(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    assert authorize_effect(store, _none_effect())['mode_record']
    # A same-uid process without the operator key rewrites the ledger with a wider ceiling.
    path = operator.ledger_path()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[-1]['record']['config']['budgets']['wall_seconds'] = 10 ** 9
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    with pytest.raises(AuthorityRefused, match='authority_invalid'):
        authorize_effect(store, _none_effect())
    with pytest.raises(AuthorityRefused):
        operator.operator_config()  # a new run's intake reads it and refuses
    with pytest.raises(AuthorityRefused):
        freeze_mode(new_store(tmp_path, 'run-0002'), {'prompt': 'Another fictional request.'})
    [wait] = autonomy.open_waits(store)
    assert wait['code'] == 'authority_invalid'


def test_N1_an_expired_grant_and_a_run_outside_the_project_are_refused_at_intake(operator_home, tmp_path):
    from ravel.controller import entry
    autonomous(expires_at=PAST)
    with pytest.raises(AuthorityRefused, match='authority_expired'):
        _store_with_dir(tmp_path)
    operator.set_values({'expires_at': FUTURE, 'project_scope': [str(tmp_path / 'project')]})
    outside = tmp_path / 'elsewhere' / 'r1'
    with pytest.raises(AuthorityRefused, match='project_scope'):
        _store_with_dir(tmp_path, outside, run_id='run-0003')
    with pytest.raises(entry.EntryError) as refused:
        entry.start(b'A fictional request.', channel='operator-file', rundir=tmp_path / 'elsewhere' / 'r2',
                    unattended=True)
    assert refused.value.code == 'project_scope' and not (tmp_path / 'elsewhere' / 'r2').exists()
    assert _store_with_dir(tmp_path, run_id='run-0004')  # inside the project: admitted


def test_N1_N6_a_grant_that_expires_mid_run_ends_the_run_at_its_next_boundary(operator_home, tmp_path, monkeypatch):
    autonomous(expires_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 600)))
    store = _store_with_dir(tmp_path)
    assert autonomy.guard(store) == ('go', None)
    later = common.now_ns() + 3600 * 10 ** 9
    monkeypatch.setattr(common, 'now_ns', lambda: later)
    with pytest.raises(AuthorityRefused, match='authority_expired'):
        authorize_effect(store, _none_effect())
    verdict, finding = autonomy.guard(store)
    assert verdict == 'exhausted' and finding['code'] == 'authority_expired'
    reason = autonomy.ending_reason(store, 'exhausted')
    from ravel.controller.sink.deliver import ending_code
    assert 'authority_expired' in reason and ending_code(reason) == 'authority_expired'


def test_N1_revoking_the_grant_ends_frozen_runs_and_later_runs_start_without_machine_authority(operator_home, tmp_path,
                                                                                            monkeypatch):
    autonomous()
    store = _store_with_dir(tmp_path)
    from ravel.workflow.approval_authority import AGENT_MARKERS
    monkeypatch.setenv(AGENT_MARKERS[0], '1')
    with pytest.raises(AuthorityRefused, match='agent session'):
        operator.revoke_grant('fictional reason')
    monkeypatch.delenv(AGENT_MARKERS[0])
    operator.revoke_grant('the operator withdraws the grant')
    assert autonomy.guard(store)[1]['code'] == 'authority_revoked'
    from ravel.controller.authority import frozen
    later = frozen(_store_with_dir(tmp_path, run_id='run-0002'))
    assert later['mode'] == 'physicist-in-the-loop' and later['machine_checkins'] == []


def test_N1_machine_approvals_under_the_grant_carry_the_machine_label_and_the_ledger_entry(operator_home, tmp_path):
    autonomous()
    store = frozen_store(tmp_path)
    approval = ci1(store)
    assert approval['label'] == MACHINE and approval['label'] != 'human'
    assert approval['evidence']['operator_entry']['digest'] == operator._ledger_rows()[-1]['digest']


# ---- N2: bounds in units that fit supplied data and batch work ------------------------------------------

def test_N2_supplied_data_bounds_narrow_for_children_and_cap_each_effect(operator_home, tmp_path, ownership):
    autonomous(budgets={'input_bytes': 10 ** 12, 'input_files': 5000, 'batch_cpu_hours': 40000.0,
                        'batch_jobs': 300, 'stage_wall_seconds': 43200, 'children': 64, 'wall_seconds': 10 ** 6})
    parent = _store_with_dir(tmp_path)
    ownership.register(parent.run_dir, parent)
    child = new_store(tmp_path, 'run-0002')
    with pytest.raises(AuthorityRefused, match='input_bytes'):
        freeze_child(child, parent, {'prompt': 'A fictional child.'}, {'budgets': {'input_bytes': None}})
    narrowed = freeze_child(child, parent, {'prompt': 'A fictional child.'}, {'budgets': {'input_bytes': 10 ** 9}})
    assert narrowed['budgets']['input_bytes'] == 10 ** 9 and narrowed['budgets']['batch_jobs'] == 300
    with pytest.raises(AuthorityRefused, match='batch_jobs'):
        authorize_effect(parent, _none_effect(batch_jobs=301))
    with pytest.raises(AuthorityRefused, match='per-stage'):
        authorize_effect(parent, _none_effect(wall_seconds=43201))
    assert authorize_effect(parent, _none_effect(wall_seconds=43200, batch_cpu_hours=12.5, input_bytes=10 ** 6))


def test_N2_a_supplied_data_read_is_not_charged_against_the_generated_event_ceiling(tmp_path):
    from ravel.controller.step import budget, graph
    read = {'kind': 'operate', 'budget': {'wall_seconds': 60, 'input_bytes': 10 ** 9, 'input_files': 12},
            'parameters': {'launch': {'argv': ['fictional-skim'], 'cpus': 1}}}
    amounts = graph._amounts(read, None, 'launch')
    assert amounts['events'] == 0 and amounts['input_bytes'] == 10 ** 9 and amounts['input_files'] == 12
    undeclared = graph._amounts({**read, 'budget': {'wall_seconds': 60}}, None, 'launch')
    assert undeclared['events'] is None  # a launch that names neither stays unknown against an event ceiling
    store = new_store(tmp_path)
    ceilings = {d: None for d in budget.DIMENSIONS}
    ceilings.update(wall_seconds=3600, model_calls=10, children=4, events=100000, input_bytes=15 * 10 ** 8)
    first = budget.reserve(store, step_id='skim', attempt=1, amounts=amounts, ceilings=ceilings)
    assert first['amounts']['events'] == 0
    with pytest.raises(Exception) as refused:
        budget.reserve(store, step_id='skim', attempt=2, amounts=amounts, ceilings=ceilings)
    assert getattr(refused.value, 'reason', None) == 'budget_exhausted'
    assert {r['dimension'] for r in refused.value.evidence['refused']} == {'input_bytes'}
    # Records written before these dimensions existed read as zero, never as unknown.
    legacy = {d: 0 for d in ('wall_seconds', 'model_calls', 'tokens', 'cost_usd', 'core_hours', 'events', 'children')}
    budget.reserve(store, step_id='old', attempt=1, amounts=legacy, ceilings={**ceilings, 'input_bytes': None})
    assert budget.totals(store)['batch_cpu_hours']['unknown'] == 0


def test_N2_N6_the_deadline_margin_ends_new_work_and_names_the_boundary(operator_home, tmp_path):
    soon = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3600))
    autonomous(deadline={'at': soon, 'margin_seconds': 7200})
    store = _store_with_dir(tmp_path)
    with pytest.raises(AuthorityRefused, match='deadline_margin'):
        authorize_effect(store, _none_effect())
    verdict, finding = autonomy.guard(store)
    assert verdict == 'exhausted' and finding['code'] == 'deadline_margin'
    from ravel.controller.sink.deliver import ending_code
    assert ending_code(autonomy.ending_reason(store, 'exhausted')) == 'deadline'


# ---- N3: the project instruction document reaches every agent with a receipt -----------------------------

def test_N3_the_declared_document_is_pinned_at_intake_and_a_change_waits_for_the_operator(operator_home, tmp_path,
                                                                                         monkeypatch):
    from ravel.workflow import project_instructions
    command, log = notifier(tmp_path)
    document = tmp_path / 'project' / 'AGENTS.md'
    document.parent.mkdir(parents=True)
    document.write_text('Fictional project rules: cite every input.\n')
    autonomous(instruction_document=str(document), notify_command=command)
    store = _store_with_dir(tmp_path)
    from ravel.controller.authority import frozen
    frozen_pin = frozen(store)['instruction_pin']
    assert frozen_pin['sha256'] == project_instructions.pin(document)['sha256'] and frozen_pin['source'] == 'operator'
    autonomy.pin_instructions(store, store.run_dir, frozen(store))
    assert project_instructions.for_run(store.run_dir)['sha256'] == frozen_pin['sha256']
    assert autonomy.current_instruction_sha256(store.run_dir) == frozen_pin['sha256']
    assert autonomy.guard(store) == ('go', None)
    document.write_text('Fictional project rules, edited during the run.\n')
    verdict, finding = autonomy.guard(store)
    assert verdict == 'wait' and finding['code'] == 'instruction_changed'
    with pytest.raises(AuthorityRefused, match='instruction_changed'):
        authorize_effect(store, _none_effect())  # no worker or launch starts on the changed text
    autonomy.guard(store)
    assert log.read_text().splitlines() == [f'{store.run_id} | WAITING_FOR_HUMAN instruction_changed']
    from ravel.workflow.approval_authority import AGENT_MARKERS
    monkeypatch.setenv(AGENT_MARKERS[0], '1')
    with pytest.raises(project_instructions.ProjectInstructionsError, match='agent'):
        project_instructions.repin(store.run_dir, approved_by='an agent', statement='self-approved')
    monkeypatch.delenv(AGENT_MARKERS[0])
    project_instructions.repin(store.run_dir, approved_by='the operator', statement='template update')
    assert autonomy.guard(store) == ('go', None)
    assert [w['phase'] for w in autonomy.waits(store).values()] == ['resolved']


def test_N3_a_project_declaration_names_the_document(operator_home, tmp_path):
    project = tmp_path / 'project'
    (project / '.ravel').mkdir(parents=True)
    (project / 'AGENTS.md').write_text('Fictional project rules.\n')
    (project / '.ravel' / 'project-instructions.json').write_text(json.dumps(
        {'schema_version': 1, 'kind': 'project-instructions-declaration', 'path': 'AGENTS.md'}))
    autonomous()
    from ravel.controller.authority import frozen
    store = _store_with_dir(tmp_path)
    assert frozen(store)['instruction_pin']['source'] == 'project'


# ---- N4: one provider policy for the whole project -------------------------------------------------------

def test_N4_a_dispatch_to_a_family_the_project_does_not_admit_is_refused_before_any_process(tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    project = tmp_path / 'project'
    (project / '.ravel').mkdir(parents=True)
    (project / '.ravel' / 'data_classification.json').write_text(json.dumps({
        'level': 'restricted', 'allowed_providers': [{'transport_id': 'fictional-admitted-worker',
                                                      'account_class': 'login:subscription'}]}))
    run = project / 'runs' / 'r1'
    run.mkdir(parents=True)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('a process started'))
    for family in ('fictional-other-worker', 'fictional-third-worker'):
        with pytest.raises(StepHold) as held:
            graph._provider_admission(run, {'id': family, 'auth': {'kind': 'login'}, 'billing': 'subscription'})
        assert held.value.reason == 'provider_policy_refused' and held.value.evidence['not_dispatched'] is True
    graph._provider_admission(run, {'id': 'fictional-admitted-worker', 'auth': {'kind': 'login'},
                                    'billing': 'subscription'})


# ---- N5: review without a sandbox is labelled, never self-reviewed --------------------------------------

def test_N5_a_review_seat_without_the_worker_sandbox_holds_labelled(tmp_path, monkeypatch):
    from ravel.controller.step import graph
    from ravel.controller.step.services import StepHold
    from ravel.workflow import sandbox
    monkeypatch.setattr(sandbox, 'available', lambda: None)
    with pytest.raises(StepHold) as held:
        graph._review_sandbox(new_store(tmp_path), {'purpose': 'review', 'role': 'fictional-critic'}, {'kind': 'review'})
    assert held.value.reason == 'worker_sandbox_unavailable'
    assert held.value.evidence['label'] == 'INDEPENDENT REVIEW INCOMPLETE'
    assert held.value.evidence['driver_self_review'] == 'never'
    monkeypatch.setattr(sandbox, 'available', lambda: 'linux')
    assert graph._review_sandbox(new_store(tmp_path, 'run-0002'), None, {'kind': 'operate'}) is None


# ---- N7: one notification per new wait, with the run name and a state code only ----------------------------

def test_N7_each_new_wait_notifies_once_and_a_status_poll_never_does(operator_home, tmp_path, capsys, monkeypatch):
    from ravel.controller.authority import cli
    command, log = notifier(tmp_path)
    autonomous(notify_command=command, disk_free_floor_bytes=10 ** 18)
    store = _store_with_dir(tmp_path)
    for _ in range(3):
        assert autonomy.guard(store)[1]['code'] == 'disk_exhausted'
    monkeypatch.setattr(common, 'open_store', lambda identifier: store)
    assert cli.main(['status', '--run', store.run_id]) == 0
    status = json.loads(capsys.readouterr().out)
    assert [w['code'] for w in status['waits']] == ['disk_exhausted']
    lines = log.read_text().splitlines()
    assert lines == [f'{store.run_id} | WAITING_FOR_HUMAN disk_exhausted'], lines
    assert 'floor' not in log.read_text()  # the reason stays on the controller's host


def test_N7_repeated_launch_failures_and_reported_conditions_wait_until_the_operator_acknowledges(operator_home,
                                                                                               tmp_path):
    command, log = notifier(tmp_path)
    autonomous(notify_command=command)
    store = _store_with_dir(tmp_path)
    for _ in range(autonomy.LAUNCH_FAILURE_LIMIT):
        store.append('step-launch', {'phase': 'refused', 'reason': 'fictional', 'time_ns': common.now_ns()})
    autonomy.report_condition(store, 'jobs_held', subject='fictional-cluster.0')
    verdict, finding = autonomy.guard(store)
    assert verdict == 'wait' and {w['code'] for w in autonomy.open_waits(store)} == {'jobs_held', 'launch_failures'}
    with pytest.raises(AuthorityRefused):
        authorize_effect(store, _none_effect())
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={},
                        reason='inspected the failures and the held jobs')
    assert autonomy.guard(store) == ('go', None)
    assert len(log.read_text().splitlines()) == 2
    with pytest.raises(AuthorityRefused, match='nothing to resume'):
        stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='again')


def test_N7_a_wait_past_the_wait_bound_ends_the_run_qualified(operator_home, tmp_path, monkeypatch):
    from ravel.controller import entry
    autonomous(wait_bound_seconds=60, disk_free_floor_bytes=10 ** 18)
    store = _store_with_dir(tmp_path)
    assert autonomy.guard(store)[0] == 'wait'
    assert entry.human_wait(store, unattended=False) != []  # an interactive driver returns with the wait open
    later = common.now_ns() + 120 * 10 ** 9
    monkeypatch.setattr(common, 'now_ns', lambda: later)
    monkeypatch.setattr(entry.time, 'time_ns', lambda: later)
    assert entry.human_wait(store, unattended=True, sleep=lambda s: None, poll_seconds=0) == []
    verdict, finding = autonomy.guard(store)
    assert verdict == 'exhausted' and 'wait bound' in finding['reason']



def _tampered(store, line, field, value):
    """``store`` reopened after one journal record's ``field`` was edited in place (its chain no longer verifies)."""
    from ravel.controller import store as store_module
    journal = store.root / store_module.JOURNAL
    lines = journal.read_text(encoding='utf-8').splitlines()
    edited = json.loads(lines[line])
    edited['record'][field] = value
    lines[line] = json.dumps(edited, sort_keys=True, separators=(',', ':'))
    journal.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return store_module.RunStore(store.run_id, root=store.store_root)


def test_N7_a_tampered_ledger_refuses_the_autonomy_census_and_never_reads_as_no_findings(operator_home, tmp_path):
    from ravel.controller import store as store_module
    store = store_module.RunStore.create(tmp_path / 'runs' / 'fictional-run', root=tmp_path / 'ledger')
    assert autonomy.condition_findings(store) == [] and autonomy.open_waits(store) == []  # nothing recorded yet
    for _ in range(autonomy.LAUNCH_FAILURE_LIMIT):
        store.append('step-launch', {'phase': 'refused', 'reason': 'fictional', 'time_ns': common.now_ns()})
    autonomy.report_condition(store, 'jobs_held', subject='fictional-cluster.0')
    assert {r['code'] for r in autonomy.condition_findings(store)} == {'jobs_held', 'launch_failures'}
    reopened = _tampered(store, 1, 'phase', 'finished')
    assert reopened.verify() != []
    for census in (autonomy.condition_findings, autonomy.waits, autonomy.open_waits):
        with pytest.raises(store_module.StoreTampered):
            census(reopened)
    with pytest.raises(store_module.StoreTampered):
        autonomy.ending_reason(reopened, 'bounded ending')

# ---- N8: stop reports what is alive; a crash is a typed failure ------------------------------------------

def test_N8_a_crash_is_a_typed_failure_and_a_refusal_stays_a_refusal():
    from ravel.transports.ravel_loop import _failure_status
    assert _failure_status({'failure_kind': 'exception', 'error_type': 'KeyError'}) == 'failed'
    assert _failure_status({'failure_kind': 'exception', 'error_type': 'GuardError'}) == 'refused'
    assert _failure_status({'failure_kind': 'gate_refused', 'error_type': 'GateRefused'}) == 'refused'
    assert _failure_status({'failure_kind': 'ambiguous', 'error_type': 'Ambiguous'}) == 'ambiguous'
    from ravel.workflow import graph_nodes
    try:
        {}['fictional']
    except KeyError as exc:
        _, record = graph_nodes.failure_record({}, 'fictional-node', exc)
    assert record['failure_kind'] == 'exception' and 'KeyError' in record['traceback']


def test_N8_a_crash_in_the_historical_gate_is_recorded_failed_not_refused(tmp_path, monkeypatch):
    from ravel.workflow import historical_qualification as h
    out = tmp_path / 'gate'
    contract = {'old_runtime': {'environment': {}, 'cwd': str(tmp_path), 'interpreter_invocation': sys.executable,
                                'interpreter_binary': {'path': 'supplied-binary', 'sha256': 'a' * 64}}}
    route = {'key': 'preparation', 'contract_sha256': h.digest(contract),
             'helper_source': h.pin(Path(h.__file__).resolve()), 'request_root': str(out),
             'interpreter_binary': contract['old_runtime']['interpreter_binary'], 'interpreter_invocation': sys.executable}

    class Registration:
        KEY_ENV = 'TEST_KEY'
        DEADLINE_ENV = 'TEST_DEADLINE'
        digest = staticmethod(h.digest)

        @staticmethod
        def wait_closed(key, deadline):
            raise KeyError('fictional crash')

    class Child:
        pid, returncode = 123, 7

        def poll(self):
            return 7
    monkeypatch.setattr(h, '_registration_module', lambda: (Registration, {'declaration': {'helpers': [route]}}))
    monkeypatch.setattr(h, '_check_sources', lambda c: None)
    monkeypatch.setattr(h.subprocess, 'Popen', lambda *a, **k: Child())
    with pytest.raises(KeyError):
        h.validate_historical(contract, out)
    record = json.loads((out / 'refusal.json').read_text())
    assert record['status'] == 'failed' and record['failure_class'] == 'KeyError'
    assert Path(record['traceback_ref']).is_file() and 'fictional crash' in Path(record['traceback_ref']).read_text()


def test_N8_stop_now_ends_the_registered_groups_and_reports_none_alive(operator_home, tmp_path, monkeypatch, capsys):
    from ravel.controller.authority import cli
    autonomous()
    store = _store_with_dir(tmp_path)
    registry = store.root / 'graph' / 'agent-work' / 'processes.json'
    registry.parent.mkdir(parents=True)
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
    try:
        registry.write_text(json.dumps({'schema_version': 1, 'kind': 'process-registry', 'processes': [
            {'id': 'worker-1', 'pid': child.pid, 'pgid': child.pid, 'role': 'worker', 'state': 'running'}]}))
        monkeypatch.setattr(common, 'open_store', lambda identifier: store)
        assert cli.main(['stop', '--run', store.run_id, '--reason', 'operator stop', '--now']) == 0
        result = json.loads(capsys.readouterr().out)
        assert result['state'] == 'stop_requested' and result['alive'] == []
        assert [t['gone'] for t in result['terminated']] == [True]
        assert child.wait(timeout=10) is not None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_N8_stop_reports_the_process_groups_still_alive(tmp_path):
    store = new_store(tmp_path)
    registry = store.root / 'graph' / 'agent-work' / 'processes.json'
    registry.parent.mkdir(parents=True)
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
    try:
        registry.write_text(json.dumps({'schema_version': 1, 'kind': 'process-registry', 'processes': [
            {'id': 'worker-1', 'pid': child.pid, 'pgid': child.pid, 'role': 'worker', 'state': 'running'}]}))
        [alive] = autonomy.alive(store)
        assert alive['pgid'] == child.pid and alive['role'] == 'worker'
    finally:
        child.kill()
        child.wait()
    assert autonomy.alive(store) == []


# ---- N10: the controller's decisions in the prompt log's companion audit file -----------------------------

def test_N10_machine_approvals_escalations_and_waits_are_audited(operator_home, tmp_path, ownership):
    from ravel.workflow import prompt_log
    autonomous()
    store = _store_with_dir(tmp_path)
    ownership.register(store.run_dir, store)
    ci1(store)
    autonomy.report_condition(store, 'proxy_expired', subject='fictional credential')
    autonomy.guard(store)
    rows = prompt_log.controller_decisions(store.run_dir)
    approval = next(r for r in rows if r['event'] == 'authority')
    assert approval['label'] == MACHINE and approval['rule'].startswith('approve_plan:')
    assert approval['timestamp'].endswith('Z') and len(approval['evidence_sha256']) == 64
    assert any(r['event'] == 'wait' and r['kind'] == 'proxy_expired' for r in rows)
    assert prompt_log.controller_decisions(tmp_path / 'not-a-controller-run') is None


# ---- G1: an operator pause and resume reach an autonomous run at its next boundary ------------------------

def test_G1_pause_waits_at_the_boundary_and_resume_continues(operator_home, tmp_path):
    autonomous()
    store = _store_with_dir(tmp_path)
    stop.record_control(store, 'pause', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='look')
    verdict, finding = autonomy.guard(store)
    assert verdict == 'wait' and finding['code'] == 'paused'
    with pytest.raises(AuthorityRefused, match='pause'):
        authorize_effect(store, _none_effect())
    stop.record_control(store, 'resume', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='go on')
    assert autonomy.guard(store) == ('go', None)
    assert authorize_effect(store, _none_effect())


# ---- G2: a stage launch under the operator's bounds carries the machine label -----------------------------

def test_G2_a_launch_admitted_under_the_operator_bounds_is_machine_labelled_or_refused_typed(operator_home, tmp_path):
    autonomous(budgets={'batch_jobs': 10})
    store = frozen_store(tmp_path)
    ci1(store, rung='smoke')
    admitted = authorize_effect(store, effect('smoke', stage='fictional-site-launch', budget={'batch_jobs': 10}))
    assert admitted['labels'] == [MACHINE]
    with pytest.raises(AuthorityRefused, match='batch_jobs'):
        authorize_effect(store, effect('smoke', stage='fictional-site-launch', budget={'batch_jobs': 11}))
    with pytest.raises(AuthorityRefused, match='exceeds the approved compute plan'):
        authorize_effect(store, effect('full', plan_sha256=PLAN_A))


# ---- G3, G4: relocated, grandchild and reused-path runs -----------------------------------------------

def test_G3_a_grandchild_inherits_the_stop_and_the_narrowed_bounds(operator_home, tmp_path, ownership):
    autonomous(budgets={'children': 64})
    root = _store_with_dir(tmp_path)
    ownership.register(root.run_dir, root)
    child = new_store(tmp_path, 'run-0002')
    freeze_child(child, root, {'prompt': 'A fictional child.'}, {'budgets': {'children': 8}})
    ownership.register(tmp_path / 'child', child)
    grandchild = new_store(tmp_path, 'run-0003')
    frozen = freeze_child(grandchild, child, {'prompt': 'A fictional grandchild.'})
    assert frozen['budgets']['children'] == 8 and frozen['parent']['run_id'] == child.run_id
    stop.record_control(root, 'stop', label=OPERATOR_COMMAND, source='operator_cli', evidence={}, reason='halt')
    with pytest.raises(AuthorityRefused, match='stop'):
        authorize_effect(grandchild, _none_effect())


def test_G3_G4_a_moved_run_refuses_typed_and_a_reused_path_starts_its_own_run(operator_home, tmp_path):
    import shutil
    from ravel.controller import entry
    operator.init(mode='physicist-in-the-loop')
    first = entry.start(b'A fictional request.', channel='terminal', rundir=tmp_path / 'runs' / 'r1')
    path = first.run_dir
    moved = tmp_path / 'runs' / 'moved'
    os.rename(path, moved)
    with pytest.raises(entry.EntryError) as refused:
        entry.open_for_resume(first.run_id)
    assert refused.value.code == 'run_relocated' and str(path) in str(refused.value)
    os.rename(moved, path)
    assert entry.open_for_resume(first.run_id).run_id == first.run_id
    shutil.rmtree(path)
    second = entry.start(b'Another fictional request.', channel='terminal', rundir=path)
    [reuse] = [row['record'] for row in second.scan('path-reuse')]
    assert reuse['previous_run'] == first.run_id and reuse['previous_store'] is True
    with pytest.raises(entry.EntryError) as replaced:
        entry.open_for_resume(first.run_id)
    assert replaced.value.code == 'run_directory_replaced'
    assert entry.open_for_resume(second.run_id).run_id == second.run_id


# ---- G5: an operator qualification made before the run is adopted at intake --------------------------------

def _qualification(executable_sha='e' * 64):
    from ravel.workflow import transport_registry as tr
    return {'schema_version': 1, 'kind': tr.QUALIFICATION_KIND, 'transport_id': 'fictional-cli-worker',
            'status': 'live_qualified', 'record_path': '/fictional/record.json', 'executable_path': '/fictional/bin/cli',
            'executable_sha256': executable_sha, 'declaration_sha256': 'd' * 64, 'probe_sha256': 'p' * 64,
            'receipt': {'path': '/fictional/receipt.json', 'sha256': 'r' * 64, 'digest': 'g' * 64},
            'observed': {'model': 'fictional-model'}, 'rundir': '/fictional/qualification',
            'qualified_utc': '2026-01-01T00:00:00Z',
            'steps': [{'step': name, 'passed': True} for name in sorted(tr.QUALIFICATION_STEPS)]}


@pytest.fixture
def fictional_transport(monkeypatch):
    from ravel.workflow import transport_registry as tr
    current = {'executable': 'e' * 64}
    monkeypatch.setattr(tr, 'load', lambda transport_id: {'id': transport_id, 'transport_kind': 'cli-worker'})
    monkeypatch.setattr(tr, 'declaration_sha256', lambda document: 'd' * 64)
    monkeypatch.setattr(tr, 'resolve_executable', lambda document, *a, **k: ('/fictional/bin/cli', current['executable']))
    return current


def test_G5_an_operator_qualification_is_adopted_into_each_later_run_with_provenance(operator_home, tmp_path,
                                                                                    fictional_transport):
    from ravel.controller import entry
    from ravel.controller.authority import qualifications
    from ravel.workflow import transport_registry as tr
    operator.init(mode='autonomous')
    record = _qualification()
    retained = qualifications.record(record)
    store = new_store(tmp_path)
    [adopted] = entry.adopt_qualifications(store)
    assert adopted['record_sha256'] == tr.digest(record) == retained['record_sha256']
    assert adopted['provenance'] == {'source': 'operator_area', 'row_digest': retained['row'], 'row_seq': retained['seq']}
    assert tr.store_qualifications(store) == {tr.digest(record): record}  # what seat selection counts (SW09)
    assert entry.adopt_qualifications(store) == []  # adopted once


def test_G5_a_changed_executable_or_an_unregistered_record_is_not_adopted(operator_home, tmp_path, fictional_transport):
    from ravel.controller import entry
    from ravel.controller.authority import qualifications
    from ravel.workflow import transport_registry as tr
    operator.init(mode='autonomous')
    qualifications.record(_qualification())
    fictional_transport['executable'] = 'f' * 64  # the executable changed after the qualification
    assert entry.adopt_qualifications(new_store(tmp_path, 'run-0001')) == []
    fictional_transport['executable'] = 'e' * 64
    _, register = qualifications._paths()
    register.write_text('')  # no longer registered
    store = new_store(tmp_path, 'run-0002')
    assert entry.adopt_qualifications(store) == [] and tr.store_qualifications(store) == {}
    # A record written beside the run (same-user state) is never adopted: only the operator area counts.
    tr.qualification_path('fictional-cli-worker').parent.mkdir(parents=True, exist_ok=True)
    tr.qualification_path('fictional-cli-worker').write_text(json.dumps(_qualification()))
    assert entry.adopt_qualifications(new_store(tmp_path, 'run-0003')) == []


def test_G5_edited_operator_qualification_records_are_refused(operator_home, tmp_path, fictional_transport):
    from ravel.controller import entry
    from ravel.controller.authority import qualifications
    operator.init(mode='autonomous')
    qualifications.record(_qualification())
    path, _ = qualifications._paths()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['record']['qualification']['executable_sha256'] = 'f' * 64
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    store = new_store(tmp_path)
    assert entry.adopt_qualifications(store) == []
    assert store.scan(qualifications.ADOPTION)[-1]['status'] == 'refused'


@pytest.mark.parametrize('changed', [None, 'declaration', 'composite'])
def test_G5_loop_adoption_checks_the_composite_identity(operator_home, tmp_path, monkeypatch, changed):
    from ravel.controller import entry
    from ravel.controller.authority import qualifications
    from ravel.workflow import transport_registry as tr
    from ravel.workflow.transports import ravel_loop
    operator.init(mode='autonomous')
    document = tr.load('ravel-loop-local')
    probe = ravel_loop.current_probe(document)[0]
    record = {**_qualification(), 'transport_id': document['id'],
              'executable_path': probe['executable_path'], 'executable_sha256': probe['executable_sha256'],
              'declaration_sha256': probe['declaration_sha256'], 'probe_sha256': tr.digest(probe)}
    qualifications.record(record)
    if changed == 'declaration':
        monkeypatch.setattr(tr, 'declaration_sha256', lambda doc: 'f' * 64)
    elif changed == 'composite':
        original = tr.file_sha256
        monkeypatch.setattr(tr, 'file_sha256', lambda path: 'f' * 64
                            if str(path).endswith('ravel_loop_worker.py') else original(path))
    store = new_store(tmp_path)
    adopted = entry.adopt_qualifications(store)
    assert bool(adopted) is (changed is None)
    assert bool(tr.store_qualifications(store)) is (changed is None)


def test_G5_a_seat_without_an_adoptable_qualification_holds_with_the_operator_remedy(tmp_path, monkeypatch):
    from ravel.controller.step import seats
    from ravel.controller.step.services import StepHold
    from ravel.workflow import transport_registry as tr

    def refuse(card, prefs, **kwargs):
        assert kwargs['qualifications'] == {}
        raise tr.TransportRefusal('no qualified transport', ['qualification:fictional-cli-worker'])
    monkeypatch.setattr(tr, 'select', refuse)
    card = {'id': 'fictional-critic', 'family': 'review', 'model': {'distinct_family_from': []}}
    prefs = {'families': {'review': ['fictional-cli-worker']}}
    with pytest.raises(StepHold) as held:
        seats.select(card, prefs, store=new_store(tmp_path))
    assert held.value.reason == 'transport_unavailable'
    assert held.value.evidence['remedy'] == [
        'ravel transport qualify fictional-cli-worker --rundir <empty dir> --model <model> --for-operator']
