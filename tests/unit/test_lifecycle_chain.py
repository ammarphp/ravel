"""Fictional calculation, named-weight export, analysis and inference on inert transports."""
import json

from executor_fixtures import (Workers, answer, approve_checkin1, drive, edge, interrupt_schema,
                               no_self_checks, plan, run_root, science_approve)
from ravel.workflow import production_executor as executor


def test_four_node_chain_routes_every_worker_in_topological_order(tmp_path, monkeypatch):
    from rdj_fixtures import Run
    from ravel.workflow import stage_supervisor
    root = run_root(tmp_path)
    identities = ['Z-calculate', 'T-export', 'B-analyze', 'A-infer']
    operations = ['amplitude-integration', 'weighted-events', 'analyze', 'differential-likelihood']
    nodes = [{'id': node, 'operation': op, 'rung': 'full' if i == 3 else 'smoke',
              'fields': [{'pointer': '/weight_names', 'value': ['nominal', 'variation'],
                          'authority': 'user', 'evidence': 'fictional supplied contract'}],
              'outputs': [{'path': f'outputs/{node}/artifact.json', 'kind': 'document', 'required': True}],
              'stage': {'name': f'fictional-{i}', 'argv': ['inert-worker', str(i)], 'events': 0,
                        'outputs': [f'outputs/{node}/artifact.json']}}
             for i, (node, op) in enumerate(zip(identities, operations))]
    plan(root, nodes=list(reversed(nodes)), edges=[edge(a, b) for a, b in zip(identities, identities[1:])],
         claims=[{'id': 'F-comparison', 'kind': 'agreement', 'absolute_yield': True}], trap_sweep=True)
    no_self_checks(monkeypatch)
    launched = []

    def supervise(name, rundir, events, logrel, cmd, **options):
        i = int(cmd[1])
        if i:
            previous = json.loads((root / f'outputs/{identities[i-1]}/artifact.json').read_text())
            assert previous['weight_names'] == ['nominal', 'variation']
        artifact = {'weight_names': ['nominal', 'variation'], 'synthetic': True,
                    'points': [[1, 2]], 'stage_index': i}
        if i == 1:
            artifact['events'] = [{'weights': {'nominal': 1, 'variation': 2}}]
        Run.stage(type('R', (), {'root': root, 'put': Run.put})(), name,
                  f'outputs/{identities[i]}/artifact.json', artifact, register=False)
        launched.append(identities[i])
        return 0

    monkeypatch.setattr(stage_supervisor, 'supervise', supervise)
    workers = Workers(root)
    first = drive(root, monkeypatch, workers, gate_check=executor.gate_errors)
    assert interrupt_schema(first) == ['checkin1_response'], first
    assert not launched and workers.roles() == ['coordinator', 'plan-critic']
    assert [executor.load_order(root, node)['role'] for node in identities] == [
        executor.executors()['operations'][op] for op in operations]
    record = approve_checkin1(root, monkeypatch)
    second = answer(root, monkeypatch, workers, 'approve', record=record['path'])
    assert interrupt_schema(second) == ['checkin2_response'], second
    assert launched == identities[:3]
    approval = science_approve(root)
    third = answer(root, monkeypatch, workers, 'approve', record=approval['path'])
    assert interrupt_schema(third) == ['checkin3_response'], json.dumps(third, indent=2)
    final = answer(root, monkeypatch, workers, 'approve', record=approval['path'])
    assert final['terminal'] is None and final['next'] == [] and final['interrupts'] == [], final
    production = [c for c in workers.calls if c['map_id'].startswith('production:')]
    assert [c['node_id'] for c in production] == identities
    assert [c['role'] for c in production] == [executor.executors()['operations'][op] for op in operations]
    assert launched == identities
    assert all(executor.node_record(root, node)['executor'] == 'worker' for node in identities)


def test_unmapped_compute_is_refused_before_checkin1_interrupt(tmp_path, monkeypatch):
    root = run_root(tmp_path)
    signatures = json.loads((executor.DATA.parent.parent / 'operation_signatures.json').read_text())
    signatures['operations']['fictional-unrouted'] = {
        'implementation': {'kind': 'science-mode'}, 'effects': [], 'stages': [], 'tools': []}
    path = tmp_path / 'signatures.json'
    path.write_text(json.dumps(signatures))
    monkeypatch.setattr(executor, 'SIGNATURES', path, raising=False)
    plan(root, nodes=[{'id': 'U-unknown', 'operation': 'fictional-unrouted', 'rung': 'full'}])
    no_self_checks(monkeypatch)
    workers = Workers(root)
    observation = drive(root, monkeypatch, workers)
    assert observation['terminal']['reason'] == 'executor_role_missing', observation
    assert observation['interrupts'] == []
    assert not (root / 'inputs/checkin1_approval.json').exists()
    assert not (root / 'inputs/work-orders').exists()
    assert not (root / 'production/nodes').exists()
    assert all(not c['map_id'].startswith('production:') for c in workers.calls)


def test_envelope_only_plan_reaches_checkin1(tmp_path, monkeypatch):
    """A plan whose only node is a coordinator envelope has nothing to route and is not refused."""
    root = run_root(tmp_path)
    plan(root, nodes=[{'id': 'F-envelope', 'kind': 'envelope', 'operation': None, 'rung': 'none'}])
    no_self_checks(monkeypatch)
    observation = drive(root, monkeypatch, Workers(root))
    assert interrupt_schema(observation) == ['checkin1_response'], observation
    assert not (root / 'inputs/work-orders').exists()


def test_unroutable_node_found_after_approval_is_a_typed_hold(tmp_path, monkeypatch):
    """A run approved before its plan was routable holds with the executor's code, not a traceback."""
    from ravel.workflow import graph_nodes
    from ravel.workflow.graphs import lifecycle
    root = run_root(tmp_path)
    plan(root, nodes=[{'id': 'U-unknown', 'operation': 'fictional-unrouted', 'rung': 'full'}])
    approve_checkin1(root, monkeypatch)
    try:
        lifecycle.derive(root)
    except graph_nodes.RecoveryHold as hold:
        assert hold.reason == 'executor_role_missing' and 'U-unknown' in hold.would_make_possible
    else:
        raise AssertionError('an unroutable approved plan must hold')
