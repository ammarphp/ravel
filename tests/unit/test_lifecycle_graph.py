"""lifecycle.drive and production.node on stub transports: CHECK-IN stops, approval records, the golden path."""
import json

import pytest

from executor_fixtures import (Workers, answer, approve_checkin1, drive, edge, interrupt_schema, no_self_checks,
                               plan, providers, run_root, science_approve)

N1 = {'id': 'N1', 'operation': 'model-events', 'rung': 'smoke'}
N2 = {'id': 'N2', 'operation': 'event-production', 'rung': 'full', 'tool': 'madgraph'}
C1 = {'id': 'C1', 'kind': 'agreement', 'absolute_yield': True}
FIRST_PASS = {'physics-critic', 'normalization-auditor', 'discrepancy-attributor', 'trap-auditor'}


@pytest.fixture
def root(tmp_path):
    return run_root(tmp_path)


def golden(root, **options):
    return plan(root, nodes=[N1, N2], edges=[edge('N1', 'N2')], claims=[C1], trap_sweep=True, **options)


def test_registered_rows_build_and_lint(tmp_path):
    from ravel.workflow import graph_registry, graph_substrate as gs
    for graph_id, instance in (('production.node', {'node_id': 'N1', 'attempt': 1}), ('lifecycle.drive', {'attempt': 1})):
        row = graph_registry.get(graph_id)
        assert row['owner'] == 'lifecycle'
        compiled = gs.build(graph_id, gs._context(tmp_path, graph_id, instance))
        assert gs.lint_graph(compiled) == [] and compiled.structure_sha256 == row['structure_sha256']


def test_checkin1_stops_and_refuses_a_resume_without_an_approval_record(root, monkeypatch):
    """Acceptance 2 (CHECK-IN 1): the plan critic runs, the lifecycle stops; an approve without a record is refused."""
    golden(root)
    no_self_checks(monkeypatch)
    workers = Workers(root)
    first = drive(root, monkeypatch, workers)
    assert interrupt_schema(first) == ['checkin1_response'], first
    assert workers.roles() == ['coordinator', 'plan-critic']
    assert (root / 'inputs/work-orders/N1.json').is_file() and (root / 'inputs/work-obligations.json').is_file()
    refused = answer(root, monkeypatch, workers, 'approve')
    assert refused['terminal']['status'] == 'hold' and refused['terminal']['reason'] == 'lifecycle_checkin_refused'
    assert not (root / 'production/nodes').exists()


def test_checkin_record_errors_bind_path_bytes_and_live_verification(root, monkeypatch):
    from ravel.workflow.graphs import lifecycle
    golden(root)
    record = approve_checkin1(root, monkeypatch)
    response = lambda **value: {'value': {'decision': 'approve', **value}}
    codes = lambda value: [e['code'] for e in lifecycle.record_errors(root, 'checkin1_response', value)]
    assert codes(response(record=record)) == []
    assert codes(None) == ['human_response_missing']
    assert codes({'value': {'decision': 'revise'}}) == ['human_not_approved']
    assert codes(response()) == ['approval_record_missing']
    assert codes(response(record={**record, 'path': 'inputs/checkin1.json'})) == ['approval_record_missing']
    (root / record['path']).write_text(json.dumps({'tampered': True}))
    assert codes(response(record=record)) == ['approval_record_invalid']
    record = {**record, 'sha256': __import__('hashlib').sha256((root / record['path']).read_bytes()).hexdigest()}
    monkeypatch.setattr(lifecycle, 'checkin1_errors', lambda root: ['approval binding changed'])
    assert codes(response(record=record)) == ['approval_record_invalid']


def test_checkin2_without_claims_stops_and_requires_the_go_record(root, monkeypatch):
    """Acceptance 2 (CHECK-IN 2): with no claim review, the lifecycle asks itself and needs checkin2_go.json."""
    plan(root, nodes=[N1, N2], edges=[edge('N1', 'N2')])
    no_self_checks(monkeypatch)
    workers = Workers(root)
    drive(root, monkeypatch, workers)
    record = approve_checkin1(root, monkeypatch)
    after_ci1 = answer(root, monkeypatch, workers, 'approve', record=record['path'])
    assert interrupt_schema(after_ci1) == ['checkin2_response'], after_ci1
    assert 'generator' in workers.roles() and 'shower-detector' not in workers.roles()
    refused = answer(root, monkeypatch, workers, 'approve')
    assert refused['terminal']['reason'] == 'lifecycle_checkin_refused'
    assert 'shower-detector' not in workers.roles()


def test_golden_path_on_stub_transports(root, monkeypatch):
    """Acceptance 4: plan critic, two production workers, a parallel first pass and a CHECK-IN 3 triad.

    The lifecycle stops at CHECK-IN 1, 2 and 3; each resume names its approval record.
    """
    golden(root)
    no_self_checks(monkeypatch)
    workers = Workers(root)
    first = drive(root, monkeypatch, workers)
    assert interrupt_schema(first) == ['checkin1_response']
    record = approve_checkin1(root, monkeypatch)
    second = answer(root, monkeypatch, workers, 'approve', record=record['path'])
    assert interrupt_schema(second) == ['checkin2_response'], second
    approval = science_approve(root)
    third = answer(root, monkeypatch, workers, 'approve', record=approval['path'])
    assert interrupt_schema(third) == ['checkin3_response'], third
    final = answer(root, monkeypatch, workers, 'approve', record=approval['path'])
    assert final['terminal'] is None and final['interrupts'] == [] and final['next'] == [], final
    roles = workers.roles()
    assert roles[:2] == ['coordinator', 'plan-critic']
    assert roles.index('generator') < min(roles.index(r) for r in FIRST_PASS) < roles.index('shower-detector')
    assert FIRST_PASS <= set(roles) and {'skeptical-verifier', 'physics-decider'} <= set(roles)
    from ravel.workflow import production_executor as executor, review_points
    for node, role in (('N1', 'generator'), ('N2', 'shower-detector')):
        record = executor.node_record(root, node)
        assert record['executor'] == 'worker' and record['receipt']['role'] == role
        assert record['scientific_acceptance'] is False
        assert (root / f'outputs/{node}/obligations.json').is_file()
    assert review_points.pending(root) == [] or all(p['when']['at'].startswith('node:') for p in review_points.pending(root))


def test_ravel_drive_on_stub_ravel_loop_stops_at_checkin1_and_resumes(root, monkeypatch, capsys):
    """``ravel drive`` dispatches the coordinator card on ravel-loop and resumes on drive respond."""
    from ravel.workflow import agent_worker, graph_nodes
    from ravel.workflow.graphs import lifecycle
    from ravel.workflow import decision_gate
    golden(root)
    no_self_checks(monkeypatch)
    workers = Workers(root)
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    monkeypatch.setattr(decision_gate, 'check', lambda *a, **k: [])
    try:
        assert lifecycle.main(['--rundir', str(root), '--transport', 'ravel-loop']) == 0
        stopped = json.loads(capsys.readouterr().out)
        assert interrupt_schema(stopped) == ['checkin1_response']
        assert workers.calls[0]['role'] == 'coordinator'
        assert all(c['transport_preference'] == ['ravel-loop'] for c in workers.calls if c['map_id'] == 'lifecycle')
        record = approve_checkin1(root, monkeypatch)
        assert lifecycle.main(['respond', '--rundir', str(root), '--decision', 'approve', '--record', record['path']]) == 0
        resumed = json.loads(capsys.readouterr().out)
        assert interrupt_schema(resumed) == ['checkin2_response']
        assert executor_done(root, 'N1')
    finally:
        graph_nodes.forget_handled()


def executor_done(root, node_id):
    from ravel.workflow import production_executor as executor
    return executor.node_record(root, node_id) is not None


def test_production_node_with_host_waiver_runs_without_a_worker(root, monkeypatch):
    from ravel.workflow import production_executor as executor
    from ravel.workflow.graphs import production
    from ravel.workflow import agent_worker, graph_nodes
    plan(root, nodes=[N1])
    executor.seal_orders(root)
    approve_checkin1(root, monkeypatch)
    executor.waive(root, 'N1', 'the host prepared the smoke card')
    workers = Workers(root)
    monkeypatch.setattr(agent_worker, 'dispatch', workers)
    try:
        observation = production.run(root, 'N1', gate_check=lambda *a: [], gate_providers=providers)
    finally:
        graph_nodes.forget_handled()
    assert observation['terminal'] is None, observation
    assert workers.calls == []
    assert executor.node_record(root, 'N1')['executor'] == 'host'


def test_production_node_launch_runs_through_the_gated_effect_and_registers(root, monkeypatch):
    """The node's stage goes through gate(launch) and the supervisor; the receipt and origin are registered."""
    import sys
    from rdj_fixtures import Run
    from ravel.workflow import agent_worker, graph_nodes, stage_supervisor
    from ravel.workflow import production_executor as executor
    from ravel.workflow.graphs import production
    stage = {'name': 'limits', 'argv': [sys.executable, '-m', 'ravel.physics.pyhf_exclude'], 'events': 1,
             'outputs': ['outputs/limits.json']}
    plan(root, nodes=[{**N2, 'stage': stage}])
    no_self_checks(monkeypatch)
    executor.seal_orders(root)
    from ravel.workflow import work_dispatch
    work_dispatch.pin_obligations(root)
    approve_checkin1(root, monkeypatch)
    launched = []

    def supervise(name, rundir, events, logrel, cmd, **options):
        launched.append({'name': name, 'cmd': cmd, 'rung': options['required_plan']})
        Run.stage(type('R', (), {'root': root, 'put': Run.put})(), name, 'outputs/limits.json', {'mu': 1.0},
                  register=False)
        return 0
    monkeypatch.setattr(stage_supervisor, 'supervise', supervise)
    monkeypatch.setattr(agent_worker, 'dispatch', Workers(root))
    try:
        observation = production.run(root, 'N2', gate_check=lambda r, g, a: executor.gate_errors(r, g, a),
                                     gate_providers=providers)
    finally:
        graph_nodes.forget_handled()
    assert observation['terminal'] is None, observation
    assert launched == [{'name': 'limits', 'cmd': stage['argv'], 'rung': 'full'}]
    record = executor.node_record(root, 'N2')
    assert record['stage']['receipt_id'].startswith('stage:limits:')
    assert record['stage']['module_origin']['module'] == 'ravel.physics.pyhf_exclude'


def test_production_node_launch_refused_without_credit_never_starts(root, monkeypatch):
    import sys
    from ravel.workflow import graph_nodes, stage_supervisor
    from ravel.workflow import production_executor as executor
    from ravel.workflow.graphs import production
    stage = {'name': 'shower', 'argv': [sys.executable, '-c', 'pass'], 'events': 1}
    plan(root, nodes=[{**N2, 'stage': stage}], delegated=True)
    executor.seal_orders(root)
    executor.waive(root, 'N2', 'host-authored card')
    monkeypatch.setattr(stage_supervisor, 'supervise', lambda *a, **k: pytest.fail('launched without credit'))
    try:
        observation = production.run(root, 'N2', gate_check=lambda r, g, a: executor.gate_errors(r, g, a),
                                     gate_providers=providers)
    finally:
        graph_nodes.forget_handled()
    assert observation['terminal']['reason'] == 'executor_waiver_unauthorized', observation
    assert executor.node_record(root, 'N2') is None


def test_production_node_adoption_refused_is_a_typed_hold(root, monkeypatch):
    """Without the CHECK-IN 1 obligations pin, adoption refuses before copying; the node holds."""
    from ravel.workflow import agent_worker, graph_nodes
    from ravel.workflow import production_executor as executor
    from ravel.workflow.graphs import production
    plan(root, nodes=[N1])
    no_self_checks(monkeypatch)
    executor.seal_orders(root)
    approve_checkin1(root, monkeypatch)
    monkeypatch.setattr(agent_worker, 'dispatch', Workers(root))
    try:
        observation = production.run(root, 'N1', gate_check=lambda *a: [], gate_providers=providers)
    finally:
        graph_nodes.forget_handled()
    assert observation['terminal']['reason'] == 'production_adoption_refused', observation
    assert observation['interrupts'] == [] and not (root / 'outputs/N1').exists()
