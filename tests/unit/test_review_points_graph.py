"""Synthetic controls for the review.points graph; inert worker stubs, no model or native calls."""
import hashlib
import json
from pathlib import Path

import pytest

from executor_fixtures import reviewed
from ravel.workflow import agent_worker, graph_nodes


PROVIDERS = ('review_points', 'rdj', 'ceilings', 'executor', 'spawn_rows', 'input_closure', 'raw_launch')
FIRST_PASS = {'physics-critic', 'normalization-auditor', 'discrepancy-attributor', 'trap-auditor'}


def review():
    from ravel.workflow.graphs import review as module
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def plan(root, *, delegated):
    """One agreement claim with an absolute yield and a trap sweep: four first-pass roles."""
    value = {'nodes': [], 'edges': [], 'trap_sweep': True,
             'claims': [{'id': 'C1', 'kind': 'agreement', 'absolute_yield': True}]}
    pin = write(root / 'inputs/request_plan.json', value)
    pin['path'] = 'inputs/request_plan.json'
    contract_path = root / 'inputs/task_contract.json'
    contract = json.loads(contract_path.read_text()) if contract_path.exists() else {}
    write(contract_path, {**contract, 'agent_layer_epoch': 2, 'delegated': delegated, 'request_plan': pin})


class Workers:
    """Stands in for agent_worker.dispatch: records each request and closes it with a real worker receipt."""

    def __init__(self, root, *, fail_once=(), findings=None):
        self.root = Path(root)
        self.fail = set(fail_once)
        self.findings = findings or {}
        self.calls = []

    def __call__(self, rundir, spec, **options):
        assert graph_nodes.TRIPWIRE.get()['ravel_kind'] == 'agent'
        assert graph_nodes.TRIPWIRE.get()['role'] == spec['role']['id']
        role = spec['role']['id']
        ws = agent_worker.materialize(rundir, spec, **{k: v for k, v in options.items()
                                                       if k in ('graph', 'framework_step', 'packet', 'protected', 'effect')})
        packet = json.loads((ws / 'inputs/review-packet.json').read_text())
        self.calls.append({'role': role, 'round': packet['round'], 'packet': packet})
        if role in self.fail:
            self.fail.discard(role)
            return agent_worker.finish(rundir, spec, final=None, execution={'exit_status': 1})
        findings = [{'summary': 'synthetic', **f} for f in self.findings.get(role, [])]
        worker = reviewed(rundir, spec, ws, findings, **options)
        assert worker['status'] == 'ok' and worker['schema_version'] == 3 and worker['actor_id'], worker
        assert worker['review_subject']['sha256'] == packet['subject_sha256']
        return worker

    def rounds(self):
        found = {}
        for call in self.calls:
            found.setdefault(call['round'], []).append(call['role'])
        return {k: sorted(v) for k, v in sorted(found.items())}


def run_review(root, monkeypatch, workers, *, at='checkin2:C1', attempt=1, responses=None, gate_check=None):
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    providers = lambda gate: {p: True for p in PROVIDERS}
    try:
        return review().run(root, at, attempt=attempt, responses=responses,
                            gate_check=gate_check or (lambda *a: []), gate_providers=providers)
    finally:
        graph_nodes.forget_handled()


@pytest.fixture
def root(tmp_path):
    from rdj_fixtures import Run
    return Run(tmp_path.resolve() / 'run', snapshot=False).root


def state(root, observation):
    from ravel.workflow import graph_substrate as gs
    ctx = gs._context(root, 'review.points', observation['instance'])
    with gs.saver(root) as checkpointer:
        app = gs.build('review.points', ctx, checkpointer=checkpointer)
        return app.get_state({'configurable': {'thread_id': observation['thread_id']}}).values


def test_registered_rows_build_and_lint(tmp_path):
    from ravel.workflow import graph_registry, graph_substrate as gs
    for graph_id in ('review.points', 'review.item'):
        row = graph_registry.get(graph_id)
        assert row['owner'] == 'review-points'
        compiled = gs.build(graph_id, gs._context(tmp_path, graph_id, {'at': 'checkin3', 'attempt': 1}))
        assert gs.lint_graph(compiled) == []
        assert compiled.structure_sha256 == row['structure_sha256']


def test_k_of_n_rerun_dispatches_only_missing_roles(root, monkeypatch):
    """after k of N first-pass reviewers finish, the next pass dispatches only the N-k others."""
    plan(root, delegated=True)
    workers = Workers(root, fail_once={'discrepancy-attributor', 'trap-auditor'})
    observation = run_review(root, monkeypatch, workers)
    assert observation['terminal'] is None and not observation['next'], observation
    rounds = workers.rounds()
    assert set(rounds[0]) == FIRST_PASS and len(rounds[0]) == len(FIRST_PASS)
    assert rounds[1] == ['discrepancy-attributor', 'trap-auditor']
    assert rounds[2] == ['skeptical-verifier'] and rounds[3] == ['physics-decider']
    from ravel.workflow import review_points
    assert [p['id'] for p in review_points.pending(root) if p['when']['at'] == 'checkin2:C1'] == []


def test_new_attempt_after_partial_panel_dispatches_only_missing(root, monkeypatch):
    plan(root, delegated=True)
    first = Workers(root, fail_once=set(FIRST_PASS) - {'physics-critic'})
    from ravel.workflow.graphs import review as module
    monkeypatch.setattr(module, 'MAX_ROUNDS', 1)
    observation = run_review(root, monkeypatch, first)
    assert observation['terminal']['status'] == 'escalate', observation
    monkeypatch.setattr(module, 'MAX_ROUNDS', 6)
    second = Workers(root)
    observation = run_review(root, monkeypatch, second, attempt=2)
    assert observation['terminal'] is None, observation
    assert second.rounds()[0] == sorted(FIRST_PASS - {'physics-critic'})
    assert 'physics-critic' not in [c['role'] for c in second.calls]


def test_verifier_sees_findings_not_the_verdict(root, monkeypatch):
    plan(root, delegated=True)
    finding = {'id': 'F1', 'materiality': 'C', 'evidence_class': 'opinion', 'summary': 'synthetic residual',
               'verdict': 'reject', 'vote': 'reject'}
    workers = Workers(root, findings={'physics-critic': [finding]})
    run_review(root, monkeypatch, workers)
    verifier = [c['packet'] for c in workers.calls if c['role'] == 'skeptical-verifier']
    assert len(verifier) == 1
    seen = [f for found in verifier[0]['findings'].values() for f in found]
    assert any(f.get('summary') == 'synthetic residual' for f in seen)
    text = json.dumps(verifier[0])
    assert 'verdict' not in text and 'reject' not in text and 'vote' not in text
    first = [c['packet'] for c in workers.calls if c['role'] == 'physics-critic']
    assert first[0]['findings'] == {}


def _interrupt(observation, schema_id):
    found = [i for i in observation['interrupts'] if i['schema_id'] == schema_id]
    assert len(found) == 1, observation
    return found[0]['id']


def test_checkin2_human_resume_without_science_approve_is_refused(root, monkeypatch):
    plan(root, delegated=False)
    workers = Workers(root)
    observation = run_review(root, monkeypatch, workers)
    pending = _interrupt(observation, 'checkin2_response')
    refused = run_review(root, monkeypatch, workers, responses={pending: {'decision': 'approve', 'note': 'looks fine'}})
    assert refused['terminal']['status'] == 'hold' and refused['terminal']['reason'] == 'review_gate_refused', refused
    errors = state(root, refused)['gates']['checkin2_accept']['errors']
    assert [e['code'] for e in errors] == ['science_approve_missing']


def test_checkin2_resume_with_forged_or_changed_approval_is_refused(root, monkeypatch):
    plan(root, delegated=False)
    workers = Workers(root)
    forged = write(root / 'inputs/science-approval.json', {'schema_version': 2, 'generated_by': 'someone.else',
                                                           'quote': 'yes'})
    observation = run_review(root, monkeypatch, workers)
    pending = _interrupt(observation, 'checkin2_response')
    record = {'path': 'inputs/science-approval.json', 'sha256': forged['sha256']}
    refused = run_review(root, monkeypatch, workers, responses={pending: {'decision': 'approve', 'record': record}})
    assert [e['code'] for e in state(root, refused)['gates']['checkin2_accept']['errors']] == ['science_approve_invalid']


def test_checkin2_resume_with_science_approve_passes(root, monkeypatch):
    plan(root, delegated=False)
    workers = Workers(root)
    approval = write(root / 'inputs/science-approval.json',
                     {'schema_version': 2, 'generated_by': 'ravel.workflow.science.approve', 'quote': 'approved as planned',
                      'approval_mode': 'human', 'expert_review': False})
    observation = run_review(root, monkeypatch, workers)
    pending = _interrupt(observation, 'checkin2_response')
    record = {'path': 'inputs/science-approval.json', 'sha256': approval['sha256']}
    accepted = run_review(root, monkeypatch, workers, responses={pending: {'decision': 'approve', 'record': record}})
    assert accepted['terminal'] is None and not accepted['next'], accepted
    assert state(root, accepted)['gates']['checkin2_accept']['errors'] == []


def test_a_finding_routes_to_rca_seam_listed_as_skipped(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    r = Run(tmp_path.resolve() / 'run', snapshot=False)
    plan(r.root, delegated=True)
    locator = r.check_result('closure')
    finding = {'materiality': 'A', 'evidence_class': 'code_check', 'evidence_locators': [locator]}
    workers = Workers(r.root, findings={'physics-critic': [finding]})
    observation = run_review(r.root, monkeypatch, workers)
    assert observation['terminal']['reason'] == 'rca_ticket_required', observation
    values = state(r.root, observation)
    rca = [v for k, v in values['results'].items() if k.startswith('rca:')]
    assert rca and rca[0]['status'] == 'skipped' and rca[0]['reason'] == 'awaits rca.ticket'
    assert rca[0]['findings'][0]['evidence_locators'] == [locator]


@pytest.mark.skip(reason='awaits rca.ticket')
def test_a_finding_runs_rca_ticket_subgraph():
    from ravel.workflow import graph_registry
    assert {'id': 'rca.ticket', 'version': 1} in graph_registry.get('review.points')['subgraphs']


def test_epoch_one_run_holds_without_dispatch(tmp_path, monkeypatch):
    root = tmp_path.resolve() / 'run'
    write(root / 'inputs/task_contract.json', {'agent_layer_epoch': 1})
    workers = Workers(root)
    observation = run_review(root, monkeypatch, workers)
    assert observation['terminal']['status'] == 'hold' and workers.calls == []


def test_research_orchestrator_review_delegates_epoch_two(root, monkeypatch):
    from ravel.workflow import research_orchestrator
    from ravel.workflow.graphs import review as module
    plan(root, delegated=True)
    seen = []
    monkeypatch.setattr(module, 'run', lambda rundir, at, **k: seen.append((Path(rundir), at)) or {'terminal': None})
    result = research_orchestrator.review(root, root / 'review-out', host=None, model='synthetic', reasoning_effort='low',
                                          max_output_tokens=1, max_wall_seconds=1, claim_scope='C1')
    assert seen == [(root, 'checkin2:C1')]
    assert result['phase'] == 'review_points' and result['execution_authorized'] is False
    assert not (root / 'review-out').exists()


def test_cli_review_run_routes_to_graph_and_keeps_other_subcommands(root, monkeypatch, capsys):
    from ravel import cli
    from ravel.workflow import review_points
    from ravel.workflow.graphs import review as module
    seen = []
    monkeypatch.setattr(module, 'run', lambda rundir, at, **k: seen.append((at, k['attempt'])) or {'terminal': None})
    assert cli.main(['review', 'run', '--rundir', str(root), '--at', 'checkin3', '--attempt', '2']) == 0
    assert seen == [('checkin3', 2)]
    monkeypatch.setattr(review_points, 'main', lambda argv: seen.append(tuple(argv)) or 0)
    assert cli.main(['review', 'pending', '--rundir', str(root)]) == 0
    assert seen[-1] == ('pending', '--rundir', str(root))
