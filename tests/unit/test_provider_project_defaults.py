"""Project restrictions survive omitted run declarations and missing defaults."""
from pathlib import Path

import pytest

from ravel.workflow import agent_graph as graph, provider_policy as policy, transport_registry as tr
from ravel.workflow.state_io import atomic_json, read_json


def declaration(*routes, level='restricted'):
    return {'level': level, 'allowed_providers': [
        {'transport_id': name, 'account_class': policy.account_class(tr.load(name))}
        for name in routes]}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    atomic_json(root / policy.PROJECT_CONFIG,
                declaration('claude-cli-worker', 'http-responses', level='internal'))
    return root


def test_inherits_at_start_with_digest_and_refuses_other_transport(project):
    run = project / 'runs' / 'new'
    expected = read_json(project / policy.PROJECT_CONFIG)
    assert policy.start(run)['data_classification'] == expected
    assert read_json(run / policy.CONFIG) == expected
    snapshot = read_json(run / policy.PROJECT_INPUT)
    assert snapshot['project_defaults'] == [
        {'project': str(project), 'data_classification': expected, 'sha256': tr.digest(expected)}]
    assert read_json(run / policy.PIN)['project_defaults_sha256'] == tr.digest(snapshot)
    assert policy.check(run, tr.load('claude-cli-worker'), 'login:subscription')
    with pytest.raises(policy.PolicyRefused, match='internal.*codex-cli-worker'):
        policy.check(run, tr.load('codex-cli-worker'), 'login:subscription')


@pytest.mark.parametrize('provision', ['argument', 'file'])
def test_run_can_narrow_project(project, provision):
    run = project / 'run'
    narrow = declaration('claude-cli-worker')
    kwargs = {'data_classification': narrow} if provision == 'argument' else {}
    if provision == 'file':
        atomic_json(run / policy.CONFIG, narrow)
    assert policy.start(run, **kwargs)['data_classification'] == narrow
    with pytest.raises(policy.PolicyRefused, match='restricted.*http-responses'):
        policy.check(run, tr.load('http-responses'), 'env:api')


@pytest.mark.parametrize('value', [declaration('claude-cli-worker', level='public'),
                                  declaration('codex-cli-worker'),
                                  declaration('claude-cli-worker', 'codex-cli-worker')])
@pytest.mark.parametrize('provision', ['argument', 'file'])
def test_widening_refused_before_pin(project, value, provision):
    run = project / 'run'
    kwargs = {'data_classification': value} if provision == 'argument' else {}
    if provision == 'file':
        atomic_json(run / policy.CONFIG, value)
    with pytest.raises(policy.PolicyRefused, match='cannot widen'):
        policy.start(run, **kwargs)
    assert not (run / policy.PIN).exists()


@pytest.mark.parametrize('damage', ['delete', 'directory', 'invalid', 'symlink', 'unreadable'])
def test_damaged_project_default_refuses_existing_and_new_runs(project, damage, monkeypatch):
    run = project / 'run'
    policy.start(run)
    path = project / policy.PROJECT_CONFIG
    if damage == 'delete':
        path.unlink()
    elif damage == 'directory':
        path.unlink(); path.mkdir()
    elif damage == 'invalid':
        path.write_text('{')
    elif damage == 'symlink':
        target = project / 'replacement.json'
        target.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(target)
    else:
        original = Path.open
        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError('synthetic unreadable default')
            return original(self, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', denied)
    for root in (run, project / 'fresh'):
        with pytest.raises(policy.PolicyRefused):
            policy.check(root, tr.load('http-responses'), 'env:api')


@pytest.mark.parametrize('damage', ['delete', 'edit'])
def test_project_input_snapshot_cannot_disappear_or_change(project, damage):
    run = project / 'run'
    policy.start(run)
    if damage == 'delete':
        (run / policy.PROJECT_INPUT).unlink()
    else:
        saved = read_json(run / policy.PROJECT_INPUT)
        saved['project_defaults'][0]['data_classification']['allowed_providers'] = []
        atomic_json(run / policy.PROJECT_INPUT, saved)
    with pytest.raises(policy.PolicyRefused):
        policy.start(run)


def test_project_changes_cannot_widen_saved_default_or_run(project):
    run = project / 'run'
    previous = policy.start(run)
    wider = declaration('claude-cli-worker', 'http-responses', 'codex-cli-worker', level='internal')
    atomic_json(project / policy.PROJECT_CONFIG, wider)
    from test_provider_policy import approval
    replacement = {'data_classification': wider, 'declared': True}
    with pytest.raises(policy.PolicyRefused, match='cannot widen'):
        policy.approve_change(run, wider, approval(previous, replacement))
    assert policy.check(run, tr.load('http-responses'), 'env:api')
    atomic_json(project / policy.PROJECT_CONFIG, declaration('claude-cli-worker'))
    with pytest.raises(policy.PolicyRefused, match='cannot widen'):
        policy.start(run)


def test_approved_run_narrowing(project):
    run = project / 'run'
    previous = policy.start(run)
    narrow = declaration('claude-cli-worker')
    from test_provider_policy import approval
    replacement = {'data_classification': narrow, 'declared': True}
    policy.approve_change(run, narrow, approval(previous, replacement))
    assert policy.start(run) == replacement


def test_nested_project_cannot_shadow_outer_default(project):
    child = project / 'nested'
    atomic_json(child / policy.PROJECT_CONFIG,
                declaration('claude-cli-worker', 'codex-cli-worker', level='public'))
    assert policy.start(child / 'run')['data_classification'] == declaration(
        'claude-cli-worker', level='internal')


def test_moved_run_retains_original_project_floor(project, tmp_path):
    import shutil
    run = project / 'run'
    policy.start(run)
    moved = tmp_path / 'moved'
    shutil.move(run, moved)
    (project / policy.PROJECT_CONFIG).unlink()
    with pytest.raises(policy.PolicyRefused):
        policy.start(moved)


def test_no_project_default_keeps_implicit_public(tmp_path):
    run = tmp_path / 'run'
    assert policy.start(run) == {'data_classification': policy.PUBLIC, 'declared': False}
    assert not (run / policy.PROJECT_INPUT).exists()
    assert policy.check(run, tr.load('http-responses'), 'env:api') is None


def test_unpinned_external_request_inherits_project_without_pinning_project(project):
    assert policy.inherited_declaration(project / 'legacy-graph') == read_json(
        project / policy.PROJECT_CONFIG)
    assert not (project / policy.PIN).exists()
    assert not (project / 'legacy-graph').exists()


def test_dispatch_without_run_uses_current_project(project, monkeypatch):
    monkeypatch.chdir(project)
    with pytest.raises(policy.PolicyRefused, match='internal.*codex-cli-worker'):
        policy.check(None, tr.load('codex-cli-worker'), 'login:subscription')


def test_graph_creation_inherits_before_restricted_pin_validation(project, monkeypatch):
    from test_provider_policy import graph_spec
    from ravel.workflow import gate_wiring
    monkeypatch.setattr(gate_wiring, 'initialize_steering', lambda *a, **kw: None)
    atomic_json(project / policy.PROJECT_CONFIG, declaration('claude-cli-worker'))
    pin = {'id': 'data', 'path': str(project / 'data.txt'), 'sha256': 'a' * 64, 'restricted': True}
    run = project / 'graph'
    graph.create(run, graph_spec([pin]))
    assert read_json(run / policy.CONFIG) == declaration('claude-cli-worker')
    narrow = project / 'narrow'
    graph.create(narrow, graph_spec([], declaration()))
    assert read_json(narrow / policy.CONFIG) == declaration()
    refused = project / 'refused'
    with pytest.raises(policy.PolicyRefused, match='cannot widen'):
        graph.create(refused, graph_spec([], declaration('codex-cli-worker')))
    assert not refused.exists()


def test_cli_creation_records_project_policy(project, capsys):
    from ravel import cli
    run = project / 'run'
    assert cli.main(['initiate', '--prompt', 'Calculate 2 + 2.', '--out', str(run)]) == 0
    assert read_json(run / policy.CONFIG) == read_json(project / policy.PROJECT_CONFIG)
    assert read_json(run / policy.PROJECT_INPUT)['project_defaults'][0]['sha256']
    capsys.readouterr()


def test_study_claimed_from_policy_custody_inherits_project(project, tmp_path, monkeypatch):
    from ravel.workflow import gate_wiring, science
    from test_live_steering import policy as steering
    from test_research_cycle import specification
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    root = project / 'scientific-study'
    source = specification(tmp_path, 'supplied-source', grouped=False)
    gate_wiring.set_steering_policy(root, steering(), source_text='Keep the declared bounds.', authority='unknown')
    science.plan(root, source['path'])
    assert read_json(root / policy.CONFIG) == read_json(project / policy.PROJECT_CONFIG)
    assert read_json(root / policy.PIN)['project_defaults_sha256']
