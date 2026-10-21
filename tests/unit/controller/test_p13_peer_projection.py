"""Exact P04 projection and materialization path, without any supervisor or worker launch.

Transport and authority boundaries are inert here; their admission is tested separately.
Packet building, packet verification, card screening, pin checks and materialization are real.
"""
from copy import deepcopy
import hashlib
import re
from pathlib import Path
import subprocess
from types import FunctionType, SimpleNamespace

import pytest

from ravel.workflow import agent_worker, broker, review_projection, role_registry
from ravel.workflow.transports import cli_worker
from test_p13_blind_transport import BLIND_CARDS, Store
from test_p13_peer_screen import CANARIES
from test_p13_peer_wiring import step_seats  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
PATCH = ROOT / 'tests/fixtures/peer_contracts/worker-projection.patch'


def _patched_sources(tmp_path):
    """Reconstruct exact full-function preimages, including the prior screened-copy seam."""
    files = {}
    current = None
    for line in PATCH.read_text().splitlines(keepends=True):
        if line.startswith('--- a/'):
            current = line.removeprefix('--- a/').strip()
            files[current] = []
        elif line.startswith('@@'):
            match = re.match(r'@@ -(\d+),(\d+) \+(\d+),(\d+) @@', line)
            files[current].append((tuple(map(int, match.groups())), []))
        elif current is not None and files[current] and line[:1] in (' ', '+', '-') and not line.startswith('+++ '):
            files[current][-1][1].append(line)
    results = {}
    # Each hunk retains the complete edited function. Applying it to an isolated
    # exact preimage avoids ambiguous long blank padding in a synthetic whole
    # module, while retaining every production patch payload byte unchanged.
    for name, hunks in files.items():
        results[name] = []
        for index, ((_, old_count, _, new_count), body) in enumerate(hunks):
            before = ''.join(line[1:] for line in body if line[:1] in (' ', '-'))
            expected = ''.join(line[1:] for line in body if line[:1] in (' ', '+'))
            assert len(before.splitlines()) == old_count
            assert len(expected.splitlines()) == new_count
            copied = tmp_path / 'peer' / Path(name).stem / str(index)
            path = copied / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(before)
            fragment = copied / 'exact-function.patch'
            fragment.write_text(f'--- a/{name}\n+++ b/{name}\n'
                + f'@@ -1,{old_count} +1,{new_count} @@\n' + ''.join(body))
            applied = subprocess.run(['patch', '--batch', '-p1', '-d', str(copied), '-i', str(fragment)],
                                     capture_output=True, text=True, check=False)
            assert applied.returncode == 0, applied.stdout + applied.stderr
            assert 'fuzz' not in applied.stdout and 'offset' not in applied.stdout
            assert path.read_text() == expected
            results[name].append(path.read_text())
    return results


@pytest.fixture
def projection_path(tmp_path, monkeypatch, step_seats):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    parts = _patched_sources(tmp_path)
    graph_parts = parts['src/ravel/controller/step/graph.py']
    worker_source = parts['src/ravel/workflow/agent_worker.py'][0]
    # Reconstitute the absent peer's fail-closed controller schema registration;
    # its exact _validate body is unchanged and still runs on every specification.
    namespace = dict(vars(agent_worker))
    namespace.update(CONTROLLER_SCHEMA='controller.v1', CONTROLLER_PACKET_AS='inputs/packet.md')
    namespace['FINAL_SCHEMAS'] = {**agent_worker.FINAL_SCHEMAS, 'controller.v1': lambda final: False}
    namespace['_validate'] = FunctionType(agent_worker._validate.__code__, namespace)
    class MaterializeRefused(ValueError):
        not_dispatched = True
    namespace['MaterializeRefused'] = MaterializeRefused
    exec(compile(worker_source, 'peer-agent-worker.py', 'exec'), namespace)
    monkeypatch.setattr(agent_worker, '_validate', namespace['_validate'])
    monkeypatch.setattr(cli_worker, 'CONTROLLER_PACKET', 'packet.md', raising=False)
    monkeypatch.setattr(cli_worker, 'toolbelt_for', lambda *a, **k: {'manifest_sha256': 'c' * 64, 'tools': []})
    seats = step_seats[0]
    selected = {'transport_id': 'claude-cli-worker', 'model': 'claude-synthetic-reviewer', 'effort': 'high'}
    inert_seats = SimpleNamespace(preferences=lambda *a: ({}, ['claude-cli-worker'], []),
                                 select=lambda *a, **k: deepcopy(selected), worker_spec=seats.worker_spec)
    class StepHold(ValueError):
        def __init__(self, code, message, **kwargs):
            super().__init__(message)
            self.code = code
    budgets = {'max_turns': 2, 'max_wall_seconds': 30, 'max_broker_calls': 4, 'max_cost_usd': None}
    inert_cards = SimpleNamespace(ownership_errors=lambda *a: [], exec_errors=lambda *a: [],
        worker_budgets=lambda *a: (budgets, {}), declared_outputs=lambda *a: [], worker_outputs=lambda rows: rows,
        consult_triggers=lambda *a: [])
    writes = []
    def write(path, raw):
        writes.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    graph = {'Path': Path, 'hashlib': hashlib, 'deepcopy': deepcopy, 'digest': broker.digest,
        'StepHold': StepHold, 'seats': inert_seats, 'cards': inert_cards, '_seat': lambda state: state.get('seat'),
        '_attempt': lambda state: 1, '_node_id': lambda state: 'controller-seat', '_seat_key': lambda state: 'review',
        '_authorize': lambda *a: None, '_facts': lambda *a: {}, '_consult_done': lambda *a: False,
        'records': lambda *a: [], 'DISPATCH': 'step-dispatch', '_write_once': write,
        '_run_dir': lambda state: state['run_dir'], '_worker_summary': lambda *a: {},
        '_controller_facts': lambda *a: {}, 'nodes': SimpleNamespace(agent=lambda *a, **kw: kw)}
    for source in graph_parts[:3]:
        exec(compile(source, 'peer-controller-step.py', 'exec'), graph)
    return graph, namespace, writes, StepHold


def setup_run(tmp_path, card, *, subject='b' * 64, parameters=None):
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'inputs').mkdir()
    model = run / 'inputs/model.json'
    model.write_text('{"mass": 17}\n')
    planted = {CANARIES[kind] for kind in card['sees']['forbidden_inputs'] if kind in CANARIES}
    for rel in planted:
        path = run / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'CANARY-PRIVATE-CONTENT\n')
    instruction = run / 'inputs/controller/packet.md'
    instruction.parent.mkdir(parents=True)
    instruction.write_text('Trusted controller instruction for this role.\n')
    packet_sha = broker.sha(instruction)
    acting = {'id': 'fictional-operation', 'kind': 'review', 'parameters': parameters or {}}
    seat = {'purpose': 'review', 'role': card['id'], 'n': 1, 'subject': {'sha256': subject}} if subject else None
    state = {'step': {'id': 'fictional-step'}, 'acting': acting, 'seat': seat,
        'card': {'sha256': role_registry.card_sha256(card['id'])}, 'reservation': {'amounts': {}}, 'run_dir': run,
        'packet': {'path': instruction.relative_to(run).as_posix(), 'file_sha256': packet_sha,
                   'sha256': packet_sha, 'inputs': []}}
    rows = [{'artifact': 'inputs/model.json', 'sha256': broker.sha(model)}]
    return run, state, rows


def preflight(graph, run, state, rows, card):
    return graph['_worker_preflight'](state, Store(), {}, run, state['acting'], card, [], rows, {})


@pytest.mark.parametrize('card', BLIND_CARDS, ids=lambda card: card['id'])
def test_G03_CF09_all_blind_cards_project_authenticate_and_materialize_without_raw_artifacts(
        projection_path, tmp_path, card):
    graph, worker, writes, _ = projection_path
    run, state, rows = setup_run(tmp_path, card)
    prepared = preflight(graph, run, state, rows, card)
    assert writes == []  # Validation-only screened-copy path never writes raw artifacts.
    assert prepared['review_packet'] is not None
    assert len(prepared['spec']['inputs']) == 1
    assert prepared['spec']['inputs'][0]['as'] == 'inputs/packet.md'
    manifest, artifacts = review_projection.load(prepared['review_packet'])
    assert manifest['role'] == card['id'] and manifest['subject_sha256'] == 'b' * 64
    assert manifest['review_point_id'] == f"controller:fictional-step:{card['id']}:1"
    assert not any(b'CANARY-PRIVATE-CONTENT' in raw for raw in artifacts.values())
    state['preflight'] = prepared
    dispatch = graph['_dispatch_node']()
    assert dispatch['packet'](state) == prepared['review_packet']
    controller = {'packet_sha256': state['packet']['file_sha256']}
    ws = worker['materialize'](run, prepared['spec'], packet=dispatch['packet'](state), controller=controller)
    assert (ws / 'inputs/packet.md').read_bytes() == (run / state['packet']['path']).read_bytes()
    assert (ws / 'inputs/packet/manifest.json').is_file()
    assert not (ws / 'inputs/artifacts').exists()
    assert all(b'CANARY-PRIVATE-CONTENT' not in path.read_bytes() for path in ws.rglob('*') if path.is_file())
    # A safe raw input is still outside the projected controller envelope.
    extra = deepcopy(prepared['spec'])
    extra['attempt'] = 2
    extra['inputs'].append({'pin': {'path': rows[0]['artifact'], 'sha256': rows[0]['sha256']}, 'as': 'inputs/raw.json'})
    with pytest.raises(ValueError, match='raw inputs'):
        worker['materialize'](run, extra, packet=prepared['review_packet'], controller=controller)
    assert not worker['workspace'](run, extra['node_id'], 2).exists()


@pytest.mark.parametrize('parameters,expected', [
    ({'subject_plan_sha256': 'd' * 64, 'subject_sha256': 'e' * 64}, 'd' * 64),
    ({'subject_sha256': 'e' * 64}, 'e' * 64),
    ({}, None),
])
def test_G03_direct_projected_seat_and_credit_share_explicit_input_subject_basis(
        projection_path, tmp_path, parameters, expected):
    graph, _, _, _ = projection_path
    card = role_registry.load('physics-critic')
    run, state, rows = setup_run(tmp_path, card, subject=None, parameters=parameters)
    prepared = preflight(graph, run, state, rows, card)
    manifest, _ = review_projection.load(prepared['review_packet'])
    assert prepared['inputs'] == [row['artifact'] for row in rows]
    basis = expected or broker.digest(sorted(prepared['inputs']))
    assert manifest['subject_sha256'] == basis
    assert prepared['spec']['parent']['review_subject'] == {
        'scope': 'controller-step:fictional-step', 'sha256': basis}
    assert prepared['spec']['parent']['review_point_id'] == manifest['review_point_id']


@pytest.mark.parametrize('damage', ['missing_packet', 'wrong_instruction_digest', 'work_order'])
def test_G03_projected_controller_materialization_refuses_changed_instruction_or_work_order(
        projection_path, tmp_path, damage):
    graph, worker, _, _ = projection_path
    card = role_registry.load('physics-critic')
    run, state, rows = setup_run(tmp_path, card)
    prepared = preflight(graph, run, state, rows, card)
    spec = prepared['spec']
    controller = {'packet_sha256': state['packet']['file_sha256']}
    packet = prepared['review_packet']
    if damage == 'missing_packet':
        packet = None
    elif damage == 'wrong_instruction_digest':
        controller['packet_sha256'] = '0' * 64
    else:
        spec['work_order'] = {'path': rows[0]['artifact'], 'sha256': rows[0]['sha256']}
    with pytest.raises(ValueError):
        worker['materialize'](run, spec, packet=packet, controller=controller)
    assert not worker['workspace'](run, spec['node_id'], spec['attempt']).exists()
