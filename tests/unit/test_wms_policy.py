"""Workflow-manager-first policy: direct dispatch of a governed run dir is refused."""
from contextlib import contextmanager
import json

import pytest

from ravel.workflow import research_cycle, science, wms_policy


def governed(tmp_path, required=True):
    project = tmp_path / 'project'
    (project / 'workflow').mkdir(parents=True)
    (project / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': required, 'engine': 'snakemake'}))
    rd = project / 'runs/study'
    (rd / 'inputs').mkdir(parents=True)
    return project, rd


SHA = 'a' * 64


def EXPORT(project):
    return project / 'workflow/exports/study/workflow.json'


def index(project, rd):
    (project / 'workflow/index.json').write_text(json.dumps({'schema_version': 1, 'tasks': [
        {'id': 'study', 'rundir': str(rd.resolve()), 'export': {'path': str(EXPORT(project).resolve()), 'sha256': SHA}}]}))


@contextmanager
def live_dispatch(project, rd):
    """The dispatch context as run-step enters it: indexed export, inside a live launch."""
    index(project, rd)
    with wms_policy.launch_authorization(project / 'workflow', 'study', 1, {'study': SHA}):
        with wms_policy._dispatch_context(rd, EXPORT(project), SHA, 'study'):
            yield


def test_direct_science_run_is_refused_and_names_wms_launch(tmp_path):
    _, rd = governed(tmp_path)
    with pytest.raises(ValueError, match='ravel wms launch'):
        science.run(rd)


def test_direct_research_experiment_is_refused_before_any_journal_commit(tmp_path, monkeypatch):
    project, rd = governed(tmp_path)
    cycle = project / 'cycle'
    cycle.mkdir()
    experiment = {'id': 'original', 'rundir': str(rd)}
    monkeypatch.setattr(research_cycle, '_load', lambda root, **k: (root, {'experiments': [experiment]}))
    monkeypatch.setattr(research_cycle, '_experiment_dispatch_admission', lambda state, identity: experiment)
    monkeypatch.setattr(research_cycle, '_commit', lambda *a, **k: pytest.fail('refusal must precede the dispatch boundary'))
    monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('governed run must not dispatch'))
    with pytest.raises(ValueError, match='ravel wms launch'):
        research_cycle.run_experiment(cycle, 'original')


def test_policy_off_or_absent_is_not_required(tmp_path):
    _, rd = governed(tmp_path, required=False)
    assert wms_policy.required(rd) is False
    wms_policy.require_dispatch(rd)
    other = tmp_path / 'elsewhere'
    other.mkdir()
    assert wms_policy.required(other) is False


def test_dispatch_context_lifts_only_its_own_run_and_no_environment_variable_does(tmp_path, monkeypatch):
    project, rd = governed(tmp_path)
    sibling = project / 'runs/other'
    sibling.mkdir()
    for name in ('RAVEL_WMS_DISPATCH', 'SNAKEMAKE', 'RAVEL_WMS'):
        monkeypatch.setenv(name, '1')
    with pytest.raises(ValueError):
        wms_policy.require_dispatch(rd)
    with live_dispatch(project, rd):
        wms_policy.require_dispatch(rd)
        with pytest.raises(ValueError):
            wms_policy.require_dispatch(sibling)
    with pytest.raises(ValueError):
        wms_policy.require_dispatch(rd)


def test_dispatch_context_of_a_governed_run_needs_the_indexed_export_and_a_live_launch(tmp_path):
    """A library caller cannot enter the context by hand to reach a guarded runner."""
    project, rd = governed(tmp_path)
    with pytest.raises(ValueError, match='ravel wms add'):
        with wms_policy._dispatch_context(rd, EXPORT(project), SHA, 'study'):
            pytest.fail('an unindexed run entered the dispatch context')
    index(project, rd)
    with pytest.raises(ValueError, match='only inside a live `ravel wms launch`'):
        with wms_policy._dispatch_context(rd, EXPORT(project), SHA, 'study'):
            pytest.fail('a run with no live launch entered the dispatch context')
    with pytest.raises(ValueError):
        wms_policy.require_dispatch(rd)
    ungoverned = tmp_path / 'plain/run'
    ungoverned.mkdir(parents=True)
    with wms_policy._dispatch_context(ungoverned, tmp_path / 'plain/export/workflow.json', SHA, 'study'):
        wms_policy.require_dispatch(ungoverned)


def test_indexed_run_stays_governed_after_policy_removal(tmp_path):
    project, rd = governed(tmp_path)
    (project / 'workflow/index.json').write_text(json.dumps({'schema_version': 1, 'tasks': [{'id': 'a', 'rundir': str(rd.resolve())}]}))
    (project / 'workflow/policy.json').unlink()
    assert wms_policy.required(rd) is True


@pytest.mark.parametrize('document', [{'schema_version': 1, 'wms_required': 'yes', 'engine': 'snakemake'},
                                      {'schema_version': 1, 'wms_required': True, 'engine': 'make'},
                                      {'schema_version': 1, 'wms_required': True},
                                      {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake', 'unlisted': 1},
                                      {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake',
                                       'execution_guard': 'off'},
                                      {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake',
                                       'software': {'python_packages': 'numpy'}}])
def test_malformed_policy_refuses_rather_than_lifting(tmp_path, document):
    project, rd = governed(tmp_path)
    (project / 'workflow/policy.json').write_text(json.dumps(document))
    with pytest.raises(ValueError):
        wms_policy.require_dispatch(rd)


@pytest.mark.parametrize('indexed', [False, True])
def test_nearer_off_policy_cannot_lift_ancestor_governance(tmp_path, indexed):
    project, rd = governed(tmp_path, required=not indexed)
    if indexed:
        (project / 'workflow/index.json').write_text(json.dumps(
            {'schema_version': 1, 'tasks': [{'id': 'a', 'rundir': str(rd.resolve())}]}))
    nested = rd.parent / 'workflow'
    nested.mkdir()
    (nested / 'policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    assert wms_policy.required(rd) is True
    with pytest.raises(ValueError, match='ravel wms launch'):
        science.run(rd)


def test_malformed_outer_policy_refuses_even_with_nearer_valid_policy(tmp_path):
    project, rd = governed(tmp_path, required=False)
    nested = rd.parent / 'workflow'
    nested.mkdir()
    (nested / 'policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    (project / 'workflow/policy.json').write_text('{')
    with pytest.raises(ValueError):
        wms_policy.require_dispatch(rd)


@pytest.mark.parametrize('entrypoint', ['cli', 'library'])
def test_governed_scoped_run_refuses_before_runner_or_plan(tmp_path, monkeypatch, capsys, entrypoint):
    from ravel import cli
    from ravel.workflow import scoped
    _, rd = governed(tmp_path)
    (rd / 'inputs/scoped-plan.json').write_text('{}')
    reason = 'scoped runs are not workflow-manager tasks'
    monkeypatch.setattr(scoped, 'verify_plan', lambda *a, **k: pytest.fail('must refuse before reading scoped plan'))
    if entrypoint == 'cli':
        monkeypatch.setattr(scoped, 'run', lambda *a, **k: pytest.fail('CLI must refuse before choosing a runner'))
        assert cli.main(['run', '--rundir', str(rd)]) != 0
        message = capsys.readouterr().err
        assert reason in message
    else:
        with pytest.raises(ValueError, match=reason) as exc:
            scoped.run(rd)
        message = str(exc.value)
    assert 'outside the governed project' in message
    assert 'policy to not require the workflow manager' in message
    assert not (rd / 'logs').exists()


def test_supervisor_dispatch_context_passes_guard_and_resets(tmp_path, monkeypatch):
    from ravel.workflow import stage_supervisor
    project, rd = governed(tmp_path)
    (rd / 'inputs/science-plan.json').write_text('{}')
    def reached_budget(*args):
        raise RuntimeError('scientific supervisor reached')
    monkeypatch.setattr(stage_supervisor, 'stage_budget_min', reached_budget)
    with live_dispatch(project, rd):
        with pytest.raises(RuntimeError, match='scientific supervisor reached'):
            stage_supervisor.supervise('science', str(rd), 0, 'logs/worker.log', ['inert'])
    with pytest.raises(ValueError, match='ravel wms launch'):
        stage_supervisor.supervise('science', str(rd), 0, 'logs/worker.log', ['inert'])


def test_engineering_only_supervisor_does_not_use_scientific_policy_guard(tmp_path, monkeypatch):
    from ravel.workflow import stage_supervisor
    _, rd = governed(tmp_path)
    def reached_budget(*args):
        raise RuntimeError('engineering supervisor reached')
    monkeypatch.setattr(stage_supervisor, 'stage_budget_min', reached_budget)
    monkeypatch.setattr(wms_policy, 'require_dispatch',
                        lambda *a: pytest.fail('an engineering-only stage must not reach the policy guard'))
    with pytest.raises(RuntimeError, match='engineering supervisor reached'):
        stage_supervisor.supervise('build', str(rd), 0, 'logs/build.log', ['inert'], _engineering_only=True)


def test_direct_backend_supervisor_without_parent_authority_refuses(tmp_path, monkeypatch):
    """Worker-owned backend stores retain parent approval, not a process-local context."""
    from ravel.workflow import stage_supervisor
    _, store = governed(tmp_path)
    monkeypatch.setattr(stage_supervisor, 'backend_stage',
                        lambda *a, **k: (['inert'], [], []))
    monkeypatch.setattr(wms_policy, 'require_dispatch',
                        lambda *a: pytest.fail('backend store must use its parent-authority gate'))
    # A backend stage with no approval route is refused as an unchecked dispatch before its plan is read.
    with pytest.raises(ValueError, match='unchecked scientific dispatch refused'):
        stage_supervisor.supervise('build', str(store), 0, 'logs/build.log',
                                  kill_secs=1, backend_plan='synthetic-backend-plan.json')
    assert not (store / 'execution_state.json').exists()


@pytest.mark.parametrize('route', ['scoped', 'compute-rung', 'authorization-plan', 'native-plan'])
def test_direct_supervisor_refuses_every_approval_route_in_a_governed_project(tmp_path, monkeypatch, capsys, route):
    """A governed run dir has no direct supervisor route, whichever approval the stage would use."""
    from ravel.workflow import stage_supervisor
    _, rd = governed(tmp_path)
    kwargs, argv = {}, []
    if route == 'scoped':
        (rd / 'inputs/scoped-plan.json').write_text(json.dumps({'mode': 'likelihood'}))
    elif route == 'compute-rung':
        kwargs, argv = {'required_plan': 'full'}, ['--required-plan', 'full']
    elif route == 'authorization-plan':
        kwargs = {'authorization_plan': 'inputs/synthetic-plan.json'}
    else:
        (rd / 'inputs/native_execution_plan.json').write_text('{}')
    monkeypatch.setattr(stage_supervisor, 'stage_budget_min',
                        lambda *a: pytest.fail('a governed approved stage reached the supervisor'))
    with pytest.raises(ValueError, match='approved stages run only through Snakemake'):
        stage_supervisor.supervise('statistics', str(rd), 10, 'logs/worker.log', ['inert'], **kwargs)
    if route != 'authorization-plan':
        assert stage_supervisor.main(['--stage', 'statistics', '--rundir', str(rd), '--events', '10',
                                      '--log', 'logs/worker.log', *argv, '--', 'inert']) == 2
        assert 'approved stages run only through Snakemake' in capsys.readouterr().err
    assert not (rd / 'logs').exists() and not (rd / 'execution_state.json').exists()


def test_refusal_names_the_governing_project_when_only_its_index_governs(tmp_path):
    project, rd = governed(tmp_path, required=False)
    (rd / 'inputs/science-plan.json').write_text('{}')
    (project / 'workflow/index.json').write_text(json.dumps(
        {'schema_version': 1, 'tasks': [{'id': 'a', 'rundir': str(rd.resolve())}]}))
    with pytest.raises(ValueError, match='ravel wms launch') as exc:
        wms_policy.require_dispatch(rd)
    message = str(exc.value)
    assert str((project / 'workflow').resolve()) in message and 'index lists this run' in message
    assert 'governed by the workflow-manager policy' not in message


@pytest.mark.parametrize('name, content', [('policy.json', '{'), ('policy.json', '{"wms_required": false}'),
                                           ('index.json', '{'), ('index.json', '{"tasks": [7]}')])
def test_malformed_governance_file_on_the_path_is_named_in_the_refusal(tmp_path, name, content):
    project, rd = governed(tmp_path, required=False)
    outer = tmp_path / 'workflow'
    outer.mkdir()
    (outer / name).write_text(content)
    with pytest.raises(ValueError) as exc:
        wms_policy.require_dispatch(rd)
    assert str((outer / name).resolve()) in str(exc.value)


def off_policy_project_with_index(tmp_path, rundir_text):
    project, rd = governed(tmp_path, required=False)
    (project / 'workflow/index.json').write_text(json.dumps(
        {'schema_version': 1, 'tasks': [{'id': 'a', 'rundir': rundir_text(project, rd)}]}))
    return project, rd


@pytest.mark.parametrize('spelling', ['parent-segment', 'symlink-alias'])
def test_index_membership_is_run_directory_identity_not_path_spelling(tmp_path, spelling):
    def text(project, rd):
        if spelling == 'parent-segment':
            return str(project.resolve() / 'runs/../runs/study')
        alias = tmp_path / 'alias'
        alias.symlink_to(project / 'runs', target_is_directory=True)
        return str(alias / 'study')
    _, rd = off_policy_project_with_index(tmp_path, text)
    assert wms_policy.required(rd) is True
    with pytest.raises(ValueError, match='index lists this run'):
        wms_policy.require_dispatch(rd)


def test_relative_index_run_dir_is_refused_and_named_not_treated_as_a_nonmember(tmp_path):
    project, rd = off_policy_project_with_index(tmp_path, lambda project, rd: 'runs/study')
    with pytest.raises(ValueError, match='absolute') as exc:
        wms_policy.require_dispatch(rd)
    assert str((project / 'workflow/index.json').resolve()) in str(exc.value)


def test_policy_with_a_duplicate_key_refuses_instead_of_taking_the_last_value(tmp_path):
    project, rd = governed(tmp_path)
    (project / 'workflow/policy.json').write_text(
        '{"schema_version":1,"wms_required":true,"wms_required":false,"engine":"snakemake"}')
    with pytest.raises(ValueError, match='duplicate') as exc:
        wms_policy.require_dispatch(rd)
    assert str((project / 'workflow/policy.json').resolve()) in str(exc.value)


@pytest.mark.parametrize('name', ['policy.json', 'index.json'])
def test_dangling_governance_link_refuses_instead_of_counting_as_absent(tmp_path, name):
    project, rd = governed(tmp_path, required=False)
    outer = tmp_path / 'workflow'
    outer.mkdir()
    (outer / name).symlink_to(tmp_path / 'absent-target.json')
    with pytest.raises(ValueError, match='unreadable or malformed') as exc:
        wms_policy.require_dispatch(rd)
    assert str(outer.resolve() / name) in str(exc.value)


@pytest.mark.parametrize('content', ['[]', '{"tasks": {"a": 1}}', '{"version": 2}', '"text"'])
def test_another_tools_workflow_index_does_not_refuse_an_ungoverned_run(tmp_path, content):
    project, rd = governed(tmp_path, required=False)
    (project / 'workflow/policy.json').unlink()
    (project / 'workflow/index.json').write_text(content)
    outer = tmp_path / 'workflow'
    outer.mkdir()
    (outer / 'index.json').write_text(content)
    assert wms_policy.required(rd) is False
    wms_policy.require_dispatch(rd)


@pytest.mark.parametrize('sibling', ['project.json', 'policy.json'])
@pytest.mark.parametrize('content', ['[]', '{"tasks": {"a": 1}}', '{"schema_version": 1, "tasks": [{"id": "a"}]}'])
def test_malformed_index_of_a_ravel_project_still_refuses(tmp_path, sibling, content):
    project, rd = governed(tmp_path, required=False)
    if sibling == 'project.json':
        (project / 'workflow/policy.json').unlink()
        (project / 'workflow/project.json').write_text('{}')
    (project / 'workflow/index.json').write_text(content)
    with pytest.raises(ValueError, match='unreadable or malformed') as exc:
        wms_policy.require_dispatch(rd)
    assert str((project / 'workflow/index.json').resolve()) in str(exc.value)


BOUNDARY = 'approved stages run only through Snakemake'


def test_governed_authorized_popen_refuses_before_any_process_starts(tmp_path, monkeypatch):
    """The common authorized-launch boundary, reached with its approval checks passing."""
    from ravel.workflow import launch_authorization
    _, rd = governed(tmp_path)
    monkeypatch.setattr(launch_authorization, '_prepare_popen_authorization', lambda *a, **k: {'sequence': 1, 'sha256': SHA})
    monkeypatch.setattr(launch_authorization.subprocess, 'Popen',
                        lambda *a, **k: pytest.fail('a governed run started a process outside the workflow manager'))
    with pytest.raises(ValueError, match=BOUNDARY):
        launch_authorization.authorized_popen(rd, 'full', ['inert'], context={'kind': 'synthetic'})
    assert sorted(p.name for p in rd.iterdir()) == ['inputs']


@pytest.mark.parametrize('entry', ['generate', 'generate_activated'])
def test_governed_native_generation_refuses_before_the_generator_command(tmp_path, monkeypatch, entry):
    """Initial native attempts pass approval without a running supervisor; governance still refuses them."""
    from ravel.physics import native_pipeline
    _, rd = governed(tmp_path)
    for name in ('verify_execution_approval', 'verify_effective_settings', 'verify_native_stage_authority'):
        monkeypatch.setattr(native_pipeline, name, lambda *a, **k: None)
    monkeypatch.setattr(native_pipeline, 'checked_linker', lambda plan: pytest.fail('governed generation reached its linker'))
    monkeypatch.setattr(native_pipeline.subprocess, 'run',
                        lambda *a, **k: pytest.fail('governed generation reached the generator command'))
    with pytest.raises(ValueError, match=BOUNDARY):
        getattr(native_pipeline, entry)({'rundir': str(rd), 'generator_command': ['inert']})
    assert not (rd / 'work').exists()


@pytest.mark.parametrize('payload', ['generate', 'likelihood'])
def test_governed_scoped_payload_library_call_refuses(tmp_path, payload):
    from ravel.physics import scoped as payloads
    _, rd = governed(tmp_path)
    with pytest.raises(ValueError, match=BOUNDARY):
        getattr(payloads, payload)(rd, {'generation': {}, 'likelihood': {}}, rd / 'outputs')
    assert not (rd / 'work').exists() and not (rd / 'outputs').exists()


CUSTODY = '''import sys
from ravel.workflow import wms_policy
try:
    wms_policy.require_custody(sys.argv[1])
except ValueError as exc:
    raise SystemExit('refused: ' + str(exc))
'''


def test_child_worker_has_custody_only_while_its_step_holds_the_dispatch_grant(tmp_path):
    """The in-process context cannot cross a process boundary; the step's live grant does."""
    import subprocess
    import sys
    project, rd = governed(tmp_path)
    sibling = project / 'runs/other'
    sibling.mkdir()

    def child(path):
        return subprocess.run([sys.executable, '-B', '-c', CUSTODY, str(path)], capture_output=True, text=True, timeout=120)
    with pytest.raises(ValueError, match=BOUNDARY):
        wms_policy.require_custody(rd)
    assert child(rd).returncode != 0
    with live_dispatch(project, rd):
        wms_policy.require_custody(rd)
        assert child(rd).returncode == 0
        refused = child(sibling)
        assert refused.returncode != 0 and BOUNDARY in refused.stderr
    after = child(rd)
    assert after.returncode != 0 and BOUNDARY in after.stderr
    assert list((project / 'workflow/.live').glob('*')) == []
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    wms_policy.require_custody(elsewhere)
    assert child(elsewhere).returncode == 0


def test_execution_guard_and_software_keys_are_the_only_optional_policy_keys():
    base = {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'}
    document = {**base, 'execution_guard': 'strict', 'software': {'python_packages': ['numpy'], 'executables': []}}
    assert wms_policy.validate(document) is document
    with pytest.raises(ValueError):
        wms_policy.validate({**base, 'execution_guard': True})


def test_live_site_launch_binds_exact_argv_profile_and_ceiling(tmp_path):
    project, rd = governed(tmp_path)
    wf = project / 'workflow'
    command = ['/synthetic/ravel-snakemake', '--profile', '/shared/.ravel-site/profile', '--jobs', '2']
    profile = {'path': '/shared/.ravel-site/profile', 'sha256': SHA}
    with wms_policy.launch_authorization(wf, 'a', 1, {'a': SHA}, argv=command, site_profile=profile, jobs=2) as path:
        record = wms_policy._live(path)
        assert record['argv'] == command and record['site_profile'] == profile and record['jobs'] == 2
    assert wms_policy._live(path) is None
