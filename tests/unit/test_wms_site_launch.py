"""Governed HTCondor launches with an inert scheduler; no facility execution."""
import json
import os
from pathlib import Path
import shlex

import pytest

from ravel.workflow import execution_guard, machine_lease, science, site_workflow, wms_launch, wms_site
from ravel.workflow.site_profiles import htcondor
from test_wms_launch import project, audit_files  # noqa: F401
from test_site_profiles import scheduler  # noqa: F401


@pytest.fixture
def site_project(project, scheduler, monkeypatch):
    # Replace the empty local fixture's initialization with a site initialization.
    (project / 'workflow/project.json').unlink()
    shim = project / 'ravel-snakemake'
    shim.write_text('#!/bin/sh\nprintf "9.27.0\\n"\n')
    shim.chmod(0o755)
    monkeypatch.setenv('PATH', str(project) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '8')
    monkeypatch.setattr(wms_launch.wms_runtime, '_site_wms_record', lambda: [str(shim)])
    # Synthetic shared filesystem; actual worker reachability requires qualification.
    monkeypatch.setattr(machine_lease, 'shared_filesystem', lambda *a, **k: 'nfs4')
    wms_launch.init(project, 'htcondor', audit=audit_files(project), python=project / 'analysis-python',
                    jobs=2, remote_ceiling=4, shared_state_root=project)
    policy = project / 'workflow/policy.json'
    policy.write_text(json.dumps({'schema_version': 1, 'wms_required': True, 'engine': 'snakemake',
                                  'execution_guard': 'strict'}))
    for skill in ('software-snakemake', 'software-ravel'):
        folder = project / '.claude/skills' / skill
        folder.mkdir(parents=True)
        (folder / 'SKILL.md').write_text('synthetic software skill\n')
    return project


def add(project, name='study'):
    return wms_launch.add(project, project.run_dir(name))


def test_pinned_profile_launch_receipt_and_fake_condor_submit(site_project, scheduler, monkeypatch):
    project = site_project
    entry = add(project)
    source = project / '.ravel-site/profiles/htcondor'
    original = wms_site.profile_pin(source)
    seen = []

    def execute(argv, cwd):
        decision = execution_guard.decide(shlex.join(argv), project, cwd)
        assert decision['allowed'], decision
        assert decision['rule'] == 'snakemake-governed-site'
        profile = Path(argv[argv.index('--profile') + 1])
        assert profile != source and project / 'workflow' not in profile.parents
        assert wms_site.profile_pin(profile)['sha256'] == original['sha256']
        job = project / 'job.sh'
        job.write_text('#!/bin/sh\n# properties = {"rule":"task_study","threads":1}\nexit 0\n')
        assert htcondor.submit(job, profile=json.loads((profile / 'profile.json').read_text())) == '12.0'
        # Exercise the ordinary run-step refusal and per-stage dispatch receipt.
        monkeypatch.setattr(science, 'run', lambda *a, **k: 1)
        with pytest.raises(ValueError):
            site_workflow.run_step(entry['export']['path'], 'study', entry['export']['sha256'])
        seen.append(argv)
        return 1, 'synthetic failed stage\n'
    monkeypatch.setattr(wms_launch, '_execute', execute)
    receipt = wms_launch.launch(project, 'study', jobs=3)
    assert receipt['exit_code'] == 1 and receipt['dispatch_records']
    assert receipt['snakemake_profile']['source'] == original
    assert receipt['snakemake_profile']['pinned']['sha256'] == original['sha256']
    assert receipt['snakemake_profile']['jobs'] == 3
    assert receipt['snakemake_profile']['remote_ceiling'] == 4
    assert receipt['snakemake_profile']['unchanged_after_run'] is True
    assert receipt['argv'][0] == str(project / 'ravel-snakemake')
    assert receipt['argv'][receipt['argv'].index('--retries') + 1] == '0'
    assert len(scheduler[1]()) == 1
    assert 'RAVEL_LEASE_SCOPE=batch-slot' in next(project.rglob('*.sub')).read_text()
    assert not execution_guard.decide(shlex.join(seen[0]), project, project / 'workflow')['allowed']


@pytest.mark.parametrize('change', ['bytes', 'extra-member', 'symlink', 'shim', 'ceiling'])
def test_changed_profile_or_configuration_refused_before_execution(site_project, monkeypatch, change):
    project = site_project
    add(project)
    folder = project / '.ravel-site/profiles/htcondor'
    if change == 'bytes':
        (folder / 'config.yaml').write_text('executor: local\n')
    elif change == 'extra-member':
        (folder / 'config.v9+.yaml').write_text('executor: local\n')
    elif change == 'symlink':
        (folder / 'config.yaml').unlink()
        (folder / 'config.yaml').symlink_to(project / 'analysis-python')
    elif change == 'shim':
        (project / 'ravel-snakemake').write_text('#!/bin/sh\nexit 0\n')
    else:
        path = project / 'workflow/project.json'
        config = json.loads(path.read_text())
        config['wms']['remote_ceiling'] = 8
        path.write_text(json.dumps(config))
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: pytest.fail('changed launch started'))
    with pytest.raises(ValueError):
        wms_launch.launch(project, 'study')


@pytest.mark.parametrize('count', [0, -1, 5, True, 2.5])
def test_jobs_outside_declared_ceiling_refused(site_project, monkeypatch, count):
    add(site_project)
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: pytest.fail('unbounded launch started'))
    with pytest.raises(ValueError):
        wms_launch.launch(site_project, 'study', jobs=count)


def test_owner_ceiling_is_rechecked_at_launch(site_project, monkeypatch):
    add(site_project)
    monkeypatch.setenv('RAVEL_REMOTE_JOB_CEILING', '1')
    with pytest.raises(ValueError, match='ceiling'):
        wms_launch.launch(site_project, 'study')


def test_strict_guard_allows_only_exact_live_governed_form(site_project, monkeypatch):
    project = site_project
    add(project)
    def execute(argv, cwd):
        assert execution_guard.decide(shlex.join(argv), project, cwd)['allowed']
        variants = []
        for flag, value in [('--profile', '/other/profile'), ('--jobs', '5'), ('--retries', '1'),
                            ('--directory', str(project)), ('--cores', '2')]:
            changed = list(argv)
            changed[changed.index(flag) + 1] = value
            variants.append(changed)
        variants += [argv + ['--executor', 'local'], argv + ['--profile', argv[argv.index('--profile') + 1]],
                     ['snakemake', *argv[1:]], argv + ['--rerun-incomplete'],
                     [*argv[:-1], 'all'], ['snakemake', '--jobs', '5', 'study']]
        for changed in variants:
            result = execution_guard.decide(shlex.join(changed), project, cwd)
            assert not result['allowed'], changed
        # The pinned directory's digest is rechecked even when argv is exact.
        path = Path(argv[argv.index('--profile') + 1]) / 'config.yaml'
        path.chmod(0o644)
        original = path.read_bytes()
        path.write_bytes(original + b'dry-run: true\n')
        assert not execution_guard.decide(shlex.join(argv), project, cwd)['allowed']
        path.write_bytes(original)
        hidden = Path(argv[argv.index('--snakefile') + 1]).parent / 'profiles'
        hidden.mkdir()
        assert not execution_guard.decide(shlex.join(argv), project, cwd)['allowed']
        hidden.rmdir()
        return 1, ''
    monkeypatch.setattr(wms_launch, '_execute', execute)
    wms_launch.launch(project, 'study')
    assert not execution_guard.decide('ravel-snakemake --profile /other --jobs 2', project)['allowed']
    assert execution_guard.decide('ravel wms retry --project . --task study', project)['allowed']
    # Re-pinning a changed policy stays outside the agent's strict command set.
    assert not execution_guard.decide('ravel wms revalidate --project . --task study', project)['allowed']


def test_site_project_cannot_use_a_plain_local_snakemake_execution(site_project, monkeypatch):
    # Tracking is authenticated at its own seam: this is about the launch form,
    # even when a caller supplies a tracked and unchanged Snakefile.
    monkeypatch.setattr(execution_guard, '_snakefile_problem', lambda *a: None)
    wf = site_project / 'workflow'
    result = execution_guard._snakemake(['snakemake', '--jobs', '9', 'study'],
                                        site_project, wf, execution_guard.data())
    assert not result['allowed'] and result['rule'] == 'snakemake-site-profile'
    assert execution_guard._snakemake(['snakemake', '-n'], site_project, wf, execution_guard.data())['allowed']


def test_node_local_state_refused_at_init_and_launch(site_project, monkeypatch):
    add(site_project)
    monkeypatch.setattr(machine_lease, 'shared_filesystem', lambda *a, **k: None)
    monkeypatch.setenv('_CONDOR_SCRATCH_DIR', str(site_project.parent))
    with pytest.raises(ValueError, match='node-local state'):
        wms_launch.launch(site_project, 'study', jobs=2)
    other = site_project / 'other'
    other.mkdir()
    with pytest.raises(ValueError, match='node-local state'):
        wms_launch.init(other, 'htcondor', audit=audit_files(other), jobs=2, remote_ceiling=4,
                        shared_state_root=site_project)
    assert not (other / '.ravel-site').exists()


def test_shared_declaration_must_cover_state(site_project):
    with pytest.raises(ValueError, match='inside the declared'):
        wms_site.shared_state(site_project, site_project / 'workflow')
    with pytest.raises(ValueError, match='shared-state-root'):
        wms_site.shared_state(site_project, None)


def test_htcondor_init_is_idempotent_and_never_rewrites_pinned_profile(site_project):
    pin = wms_site.profile_pin(site_project / '.ravel-site/profiles/htcondor')
    wms_launch.init(site_project, 'htcondor', audit=audit_files(site_project), python=site_project / 'analysis-python',
                    jobs=2, remote_ceiling=4, shared_state_root=site_project)
    assert wms_site.profile_pin(pin['path']) == pin


def test_profile_copy_is_frozen_before_scheduler_parse(site_project, monkeypatch):
    add(site_project)
    def execute(argv, cwd):
        original = Path(argv[argv.index('--profile') + 1]) / 'config.yaml'
        before = original.read_bytes()
        (site_project / '.ravel-site/profiles/htcondor/config.yaml').write_text('executor: local\n')
        assert original.read_bytes() == before
        return 1, ''
    monkeypatch.setattr(wms_launch, '_execute', execute)
    assert wms_launch.launch(site_project, 'study')['snakemake_profile']['unchanged_after_run']


def test_cli_site_init_and_launch_flags(site_project, monkeypatch, capsys):
    add(site_project)
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: (1, 'synthetic failure'))
    assert wms_launch.main(['launch', '--project', str(site_project), '--task', 'study', '--jobs', '2']) == 1
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['snakemake_profile']['jobs'] == 2
    with pytest.raises(SystemExit):
        wms_launch.main(['launch', '--project', str(site_project), '--task', 'study', '--retries', '1'])


def test_site_runtime_ignores_unrelated_snakemake_override(site_project, monkeypatch):
    add(site_project)
    monkeypatch.setenv('RAVEL_SNAKEMAKE', '/other/snakemake')
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_argv', lambda *a: pytest.fail('site launch used local resolution'))
    monkeypatch.setattr(wms_launch, '_execute', lambda argv, cwd: (1, 'synthetic failure'))
    assert wms_launch.launch(site_project, 'study')['argv'][0] == str(site_project / 'ravel-snakemake')


def test_cli_initializes_site_profile_with_explicit_contract(site_project, monkeypatch, capsys):
    other = site_project / 'fresh'
    other.mkdir()
    audit = other / 'audit.json'
    audit.write_text(json.dumps(audit_files(other)))
    assert wms_launch.main(['init', '--project', str(other), '--audit', str(audit), '--profile', 'htcondor',
                            '--jobs', '2', '--remote-ceiling', '4', '--shared-state-root', str(site_project)]) == 0
    config = json.loads((other / 'workflow/project.json').read_text())
    assert config['profile'] == 'htcondor' and config['wms']['retries'] == 0
    assert config['site']['profile']['sha256'] == wms_site.profile_pin(other / '.ravel-site/profiles/htcondor')['sha256']


def test_project_ceiling_does_not_widen_an_approved_partition_fanout(site_project, monkeypatch):
    add(site_project)
    # The existing partition validator authenticates the master and checks exact
    # profile/cores/jobs/ceiling equality. Reach that boundary for a changed count.
    monkeypatch.setattr(science, 'execution_spec', lambda *a, **k: {'mode': 'root-stream', 'task': {}})
    def approved_fanout(spec, rd, capture, wms, tasks, masters):
        assert wms['jobs'] == 3 and wms['remote_ceiling'] == 4
        raise ValueError('WMS profile differs from the fan-out approved at CHECK-IN 1')
    monkeypatch.setattr(site_workflow, '_partition_task', approved_fanout)
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: pytest.fail('widened partition launch started'))
    # Use an already authenticated export at the helper's seam: its real verify
    # also checks the exact approved partition fan-out before this launch check.
    row = wms_launch._entry(site_project / 'workflow', 'study')
    document = json.loads(Path(row['export']['path']).read_text())
    monkeypatch.setattr(site_workflow, 'verify', lambda *a: document)
    with pytest.raises(ValueError, match='fan-out approved'):
        wms_launch.launch(site_project, 'study', jobs=3)


@pytest.mark.parametrize('options', [{'lease_scope': 'machine'}, {'workflow_dir': '/other/workflow'}])
def test_reinitialization_refuses_conflicting_site_options_without_rewriting_pins(site_project, options):
    before = wms_site.profile_pin(site_project / '.ravel-site/profiles/htcondor')
    with pytest.raises(ValueError, match='governed site options'):
        wms_launch.init(site_project, 'htcondor', audit=audit_files(site_project),
                        python=site_project / 'analysis-python', jobs=2, remote_ceiling=4,
                        shared_state_root=site_project, site_options=options)
    assert wms_site.profile_pin(before['path']) == before


def test_site_default_keeps_environment_python_launcher_and_local_default_is_unchanged(site_project, monkeypatch):
    launcher = site_project / 'environment-python'
    launcher.symlink_to(site_project / 'analysis-python')
    monkeypatch.setattr(wms_launch.sys, 'executable', str(launcher))
    remote = site_project / 'default-site'
    remote.mkdir()
    wms_launch.init(remote, 'htcondor', audit=audit_files(remote), jobs=2, remote_ceiling=4,
                    shared_state_root=site_project)
    config = json.loads((remote / 'workflow/project.json').read_text())
    assert config['python'] == str(launcher)
    local = site_project / 'default-local'
    local.mkdir()
    wms_launch.init(local, audit=audit_files(local))
    assert json.loads((local / 'workflow/project.json').read_text())['python'] == str(launcher.resolve())
