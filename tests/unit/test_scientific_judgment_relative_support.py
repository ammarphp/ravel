"""Pure public role preparation; synthetic journal votes, no model/native calls."""
from copy import deepcopy
from pathlib import Path
import pytest
from ravel.workflow import scientific_judgment as judgment, physics_review as review
from ravel.workflow import agent_graph, execution
from ravel.workflow.state_io import atomic_json, read_json
from test_physics_review import run, opened, finding


@pytest.fixture
def cycle(run):
    opened(run)
    return run[0]


def record(root, tmp_path, *, role, absolute=False, verdict='accept'):
    actors = {'physics_critic': 'critic', 'skeptical_verifier': 'skeptic'}
    path = (tmp_path / 'external' if absolute else root / 'inputs') / (role + '.json')
    path.parent.mkdir(exist_ok=True)
    value = {'kind': 'scientific_review', 'summary': 'synthetic retained public role output',
             'verdict': verdict, 'origin': role}
    atomic_json(path, {'result': {'kind': 'model_result', 'value': value}})
    pins = [review._pin(root, str(path)), review._pin(root, review.POLICY)]
    event = review.submit_review(root, role=role, actor_id=actors[role], verdict=verdict,
        summary='Synthetic journal control; no actual scientific vote',
        findings=[finding()] if verdict == 'send_back' else [],
        claim_scope='reproduction' if verdict == 'accept' else None,
        supporting_artifacts=pins)
    assert event['supporting_artifacts'] == pins
    return path, value


def prepare(root, out, role):
    return judgment.prepare_role(root, out, role=role,
        actor_id='physicist' if role == 'synthesizer' else 'improver',
        model='pure-control', reasoning_effort='high', max_output_tokens=1024,
        max_wall_seconds=20, claim_scope='reproduction' if role == 'synthesizer' else None)


def actual(binding):
    packet = Path(binding['graph_root']).parent / 'context'
    manifest = read_json(packet / 'manifest.json')
    artifact = next(row for row in manifest['artifacts'] if row['id'] == 'actual_role_judgments')
    return read_json(packet / artifact['path'])


@pytest.mark.parametrize('role', ['synthesizer', 'improver'])
@pytest.mark.parametrize('absolute', [False, True])
def test_public_prepare_from_foreign_cwd_binds_actual_run_support(cycle, tmp_path, monkeypatch, role, absolute):
    root = cycle
    sources = [record(root, tmp_path, role='physics_critic', absolute=absolute,
                      verdict='send_back' if role == 'improver' else 'accept')]
    if role == 'synthesizer':
        sources.append(record(root, tmp_path, role='skeptical_verifier', absolute=absolute))
    foreign = tmp_path / 'foreign'; (foreign / 'inputs').mkdir(parents=True)
    for source, value in sources:
        atomic_json(foreign / 'inputs' / source.name, {'result': {'kind': 'model_result',
                    'value': dict(value, summary='wrong cwd decoy')}})
    atomic_json(foreign / review.POLICY, {'decoy': True})
    monkeypatch.chdir(foreign)
    before = review._read(root)
    binding = prepare(root, tmp_path / 'prepared', role)
    rows = actual(binding)
    assert [row['actual_public_role_outputs'] for row in rows] == [[value] for _, value in sources]
    assert [row['role'] for row in rows] == [value['origin'] for _, value in sources]
    assert review._read(root) == before
    request = read_json(binding['request']['path'])
    assert request['rundir'] == str(root) and request['execution_authorized'] is False
    assert request['actor_identity_authenticated'] is False
    assert agent_graph.status(binding['graph_root'])['usage']['calls'] == 0
    assert review.status(root)['state'] == ('send_back' if role == 'improver' else 'awaiting_review')


@pytest.mark.parametrize('change', ['missing', 'changed', 'symlink', 'ancestor_symlink'])
@pytest.mark.parametrize('role', ['synthesizer', 'improver'])
def test_recorded_support_damage_refuses_before_role_graph(cycle, tmp_path, monkeypatch, change, role):
    path, _ = record(cycle, tmp_path, role='physics_critic',
                     verdict='send_back' if role == 'improver' else 'accept')
    if role == 'synthesizer': record(cycle, tmp_path, role='skeptical_verifier')
    if change == 'missing': path.unlink()
    elif change == 'changed': path.write_bytes(path.read_bytes() + b' ')
    elif change == 'symlink':
        target = tmp_path / 'same-bytes.json'; target.write_bytes(path.read_bytes()); path.unlink(); path.symlink_to(target)
    else:
        folder = cycle / 'inputs'; moved = cycle / 'moved-inputs'; folder.rename(moved); folder.symlink_to(moved, target_is_directory=True)
    foreign = tmp_path / 'foreign'; foreign.mkdir(); monkeypatch.chdir(foreign)
    out = tmp_path / 'refused'
    with pytest.raises((ValueError, OSError)):
        prepare(cycle, out, role)
    assert not (out / 'graph').exists()


def test_same_cwd_legacy_prepare_and_empty_support_still_work(cycle, tmp_path, monkeypatch):
    for role, actor in [('physics_critic', 'critic'), ('skeptical_verifier', 'skeptic')]:
        review.submit_review(cycle, role=role, actor_id=actor, verdict='accept',
            summary='Synthetic empty-support control', claim_scope='reproduction', supporting_artifacts=[])
    monkeypatch.chdir(cycle)
    binding = prepare(cycle, tmp_path / 'empty-support', 'synthesizer')
    assert [row['actual_public_role_outputs'] for row in actual(binding)] == [[], []]
    assert agent_graph.status(binding['graph_root'])['usage']['calls'] == 0


def test_late_bound_support_drift_is_read_from_authenticated_buffer(cycle, tmp_path, monkeypatch):
    path, _ = record(cycle, tmp_path, role='physics_critic')
    record(cycle, tmp_path, role='skeptical_verifier')
    before = judgment._read_pin
    def changed(pin):
        if Path(pin['path']) == path:
            path.write_bytes(path.read_bytes() + b' ')
        return before(pin)
    monkeypatch.setattr(judgment, '_read_pin', changed)
    foreign = tmp_path / 'foreign'; foreign.mkdir(); monkeypatch.chdir(foreign)
    with pytest.raises(ValueError, match='consumed input changed'):
        prepare(cycle, tmp_path / 'late', 'synthesizer')
    assert not (tmp_path / 'late/graph').exists()


def test_registered_actor_and_independent_prior_reviews_stay_required(cycle, tmp_path, monkeypatch):
    foreign = tmp_path / 'foreign'; foreign.mkdir(); monkeypatch.chdir(foreign)
    with pytest.raises(ValueError, match='both actual independent'):
        prepare(cycle, tmp_path / 'premature', 'synthesizer')
    for role in ['physics_critic', 'skeptical_verifier']: record(cycle, tmp_path, role=role)
    with pytest.raises(ValueError, match='wrong registered role actor'):
        judgment.prepare_role(cycle, tmp_path / 'wrong-actor', role='synthesizer', actor_id='critic',
            model='pure-control', reasoning_effort='high', max_output_tokens=1024, max_wall_seconds=20)
    assert not (tmp_path / 'wrong-actor').exists()
