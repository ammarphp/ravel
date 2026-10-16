"""Workflow-manager-first launch: rules exist before execution and Snakemake runs run-step."""
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

from ravel.physics import root_stream as stream
from ravel.workflow import science, site_workflow as w, wms_launch, wms_policy, wms_runtime
from method_decision_fixture import admit_method
from root_stream_fixture import pin, put

SKIP = 'set RAVEL_TEST_SNAKEMAKE to run real Snakemake'
PLAN = {'schema_version': 2, 'stages': [{'outputs': ['outputs']}]}


def snakemake():
    argv = wms_runtime.snakemake_argv()
    if not argv or not os.environ.get('RAVEL_TEST_SNAKEMAKE'):
        pytest.skip(SKIP)
    return argv


def dry_run(project):
    done = subprocess.run([*snakemake(), '-n', '--cores', '1', '--snakefile', 'Snakefile'], cwd=project / 'workflow',
                          capture_output=True, text=True, timeout=180)
    assert done.returncode == 0, done.stdout + done.stderr
    output = done.stdout + done.stderr
    rows = re.findall(r'^(\S+)\s+(\d+)\s*$', output.split('Job stats:')[1].split('\n\n')[0], re.M)
    return {name: int(n) for name, n in rows if name not in ('job', 'total')}


def audit_files(root):
    proof = put(root, 'audit/proof.json', {'synthetic': 'software only'})
    policy = put(root, 'audit/blind-policy.json', {'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
                                                   'review_source': proof, 'original_domain': None})
    return {'prompts': [proof['path']], 'model_build': 'exact-synthetic-build', 'timestamps': ['2026-10-09T00:00:00Z'],
            'token_accounting': proof['path'], 'environment': proof['path'], 'tracked_skill_sources': [proof['path']],
            'blinding_policy': policy['path']}


class Project(type(Path())):
    """The project path plus a run-dir factory."""


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Patched ordinary authority: approval is a switch, plans are inert files."""
    root = tmp_path / 'project'
    root.mkdir()
    python = root / 'analysis-python'
    python.write_text('#!/bin/sh\nexit 3\n')
    python.chmod(0o755)
    source = tmp_path / 'source'
    source.mkdir()
    put(source, 'module.py', b'# synthetic complete source\n')
    monkeypatch.setattr(w, '_source_assets', lambda: (source, stream.census(source)))
    approved = set()

    def verify_plan(rd, approved_flag=False, **kwargs):
        if kwargs.get('approved', approved_flag) and str(Path(rd).resolve()) not in approved:
            raise ValueError('missing or stale study approval')
        return dict(PLAN)
    monkeypatch.setattr(science, 'verify_plan', lambda rd, approved=False, **k: verify_plan(rd, approved))
    monkeypatch.setattr(science, 'execution_spec', lambda rd, **kwargs: {'mode': 'quantities'})
    wms_launch.init(root, audit=audit_files(root), python=python)

    def run_dir(name, approve=True):
        rd = root / 'runs' / name
        (rd / 'inputs').mkdir(parents=True)
        put(rd, 'inputs/science-plan.json', PLAN)
        if approve:
            approved.add(str(rd.resolve()))
        return rd
    project = Project(root)
    project.run_dir = run_dir
    return project


def test_unapproved_run_dir_is_refused_and_no_rule_is_written(project):
    rd = project.run_dir('study', approve=False)
    with pytest.raises(ValueError, match='ravel approve'):
        wms_launch.add(project, rd)
    wf = project / 'workflow'
    assert list((wf / 'rules').iterdir()) == [] and list((wf / 'exports').iterdir()) == []
    assert json.loads((wf / 'index.json').read_text())['tasks'] == []


def test_rule_exists_before_launch_and_snakemake_lists_it(project):
    entry = wms_launch.add(project, project.run_dir('study'))
    wf = project / 'workflow'
    rule = (wf / 'rules/study.smk').read_text()
    assert entry['id'] == 'study' and 'rule task_study:' in rule and 'run-step' in rule and 'rule all' not in rule
    assert entry['export']['sha256'] in rule and 'retries: 0' in rule
    assert not (wf / 'exports/study/completed/study.json').exists()
    assert dry_run(project) == {'all': 1, 'ravel_verify_study': 1, 'task_study': 1}


def test_aborted_launch_keeps_rule_and_export_and_a_fresh_attempt_is_a_new_task(project, monkeypatch):
    wms_launch.add(project, project.run_dir('first'))
    wf = project / 'workflow'
    rule_before = (wf / 'rules/first.smk').read_bytes()
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_version', lambda argv: '9.27.0')
    monkeypatch.setattr(science, 'run', lambda rundir, resume=False: 1)  # fake supervisor exit

    def execute(argv, cwd):
        assert argv[:2] == ['/synthetic/snakemake', '--snakefile'] and argv[-1] == 'exports/first/completed/first.json'
        assert argv[argv.index('--retries') + 1] == '0' and argv[argv.index('--cores') + 1] == '1'
        entry = wms_launch._entry(wf, 'first')
        try:
            w.run_step(entry['export']['path'], 'first', entry['export']['sha256'])
        except ValueError as exc:
            return 1, str(exc)
        return 0, ''
    monkeypatch.setattr(wms_launch, '_execute', execute)
    receipt = wms_launch.launch(project, 'first')
    assert receipt['exit_code'] == 1 and receipt['completion_marker'] is None
    assert receipt['scientific_acceptance_inferred'] is False and receipt['snakemake_locks_present_during_step'] == [False]
    assert (wf / 'launches/first/000001.json').is_file()
    assert (wf / 'rules/first.smk').read_bytes() == rule_before
    entry = wms_launch._entry(wf, 'first')
    w.verify(entry['export']['path'], entry['export']['sha256'])
    with pytest.raises(ValueError, match='already a task'):
        wms_launch.add(project, project / 'runs/first', task='first_again')
    assert wms_launch.add(project, project.run_dir('second'))['id'] == 'second'
    view = wms_launch.status(project)
    assert [(t['id'], t['delivered'], t['launches'], t['last_exit_code']) for t in view['tasks']] == [
        ('first', False, 1, 1), ('second', False, 0, None)]
    assert view['tasks'][0]['dispatches_without_snakemake_lock'] == 1


def test_rule_for_a_run_whose_approval_lapsed_fails_naming_ravel_approve(project, monkeypatch):
    rd = project.run_dir('study')
    entry = wms_launch.add(project, rd)
    monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('unapproved run must not dispatch'))
    monkeypatch.setattr(science, 'verify_plan', lambda rd, approved=False, **k: (_ for _ in ()).throw(ValueError('missing or stale study approval'))
                        if approved else dict(PLAN))
    with pytest.raises(ValueError, match='ravel approve'):
        w.run_step(entry['export']['path'], 'study', entry['export']['sha256'])
    assert not (project / 'workflow/exports/study/completed/study.json').exists()


def test_note_rule_depends_on_both_analysis_markers(project):
    for name in ('analysis_a', 'analysis_b'):
        wms_launch.add(project, project.run_dir(name))
    entry = wms_launch.add(project, project.run_dir('note'), ['analysis_a', 'analysis_b'])
    rule = (project / 'workflow/rules/note.smk').read_text()
    inputs = re.search(r'rule task_note:\n    input: (.*)\n', rule).group(1)
    assert "'exports/analysis_a/completed/analysis_a.json'" in inputs and "'exports/analysis_b/completed/analysis_b.json'" in inputs
    document = w.verify(entry['export']['path'], entry['export']['sha256'])
    assert [row['task'] for row in document['tasks'][0]['after']] == ['analysis_a', 'analysis_b']
    counts = dry_run(project)
    assert counts['all'] == 1 and counts['task_note'] == 1 and counts['task_analysis_a'] == 1


def test_dependency_outside_the_index_is_refused_without_a_rule(project):
    wms_launch.add(project, project.run_dir('analysis_a'))
    with pytest.raises(ValueError, match='not in the index'):
        wms_launch.add(project, project.run_dir('note'), ['analysis_a', 'absent'])
    assert not (project / 'workflow/rules/note.smk').exists()
    assert not (project / 'workflow/exports/note').exists()


def test_two_adds_make_one_workflow_with_one_rule_all_and_duplicate_ids_refuse(project):
    wms_launch.add(project, project.run_dir('one'))
    wms_launch.add(project, project.run_dir('two'))
    wf = project / 'workflow'
    texts = [(wf / 'Snakefile').read_text(), *(p.read_text() for p in sorted((wf / 'rules').glob('*.smk')))]
    assert sum(len(re.findall(r'^rule all:', t, re.M)) for t in texts) == 1
    assert (wf / 'Snakefile').read_bytes() == wms_launch.SNAKEFILE
    with pytest.raises(ValueError, match='already in the index'):
        wms_launch.add(project, project.run_dir('three'), task='one')
    assert not (wf / 'rules/three.smk').exists()
    assert dry_run(project) == {'all': 1, 'ravel_verify_one': 1, 'ravel_verify_two': 1, 'task_one': 1, 'task_two': 1}


def test_run_dir_outside_the_project_is_refused(project, tmp_path):
    outside = tmp_path / 'outside'
    (outside / 'inputs').mkdir(parents=True)
    with pytest.raises(ValueError, match='inside the project'):
        wms_launch.add(project, outside)


def test_launch_refuses_a_changed_policy(project):
    wms_launch.add(project, project.run_dir('study'))
    (project / 'workflow/policy.json').write_text(json.dumps({'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    with pytest.raises(ValueError, match='policy changed'):
        wms_launch.launch(project, 'study')


def test_cli_registers_wms(project, capsys):
    from ravel import cli
    assert cli.main(['wms', 'status', '--project', str(project)]) == 0
    assert json.loads(capsys.readouterr().out)['tasks'] == []


# Real ordinary authority: plan, approval, supervisor and delivery readers are the
# actual APIs; only the fixture's external ROOT reader is substituted in the child.
BOOTSTRAP = r'''import sys
from pathlib import Path
source, wrapper, args = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, source)
from ravel.workflow import science, site_workflow
def command(module, *rest, python=None):
    if module != 'ravel.physics.science_worker':
        raise ValueError('synthetic worker scope')
    return [sys.executable, '-B', wrapper, source, *(str(x) for x in rest)]
science.module_command = command
while args and args[0] in ('-I', '-B'):
    args = args[1:]
if args[:2] != ['-m', 'ravel.workflow.site_workflow']:
    raise SystemExit('synthetic interpreter runs only the site workflow')
raise SystemExit(site_workflow.main(args[2:]))
'''


def real_project(tmp_path, monkeypatch, python=None):
    from root_partition_ordinary_fixture import prepare_fixture
    root = tmp_path / 'project'
    root.mkdir()
    ds, a, cfg, spec, proof = prepare_fixture(root / 'source', monkeypatch)
    audit = audit_files(root)
    blind = put(root, 'audit/root-blind-policy.json', {'schema_version': 1, 'policy': 'exclude_signal_region_data_from_model_and_analysis',
                                                       'review_source': proof, 'original_domain': a['blinding']['source']})
    audit['blinding_policy'] = blind['path']
    wms_launch.init(root, audit=audit, python=python)
    return root, spec


def approved_run(rd, spec):
    science.plan(rd, spec['path'])
    admit_method(rd)  # a full approval and its launch need the run's method decision
    science.approve(rd, 'Synthetic software fixture; scripted assent is not expert review', scripted=True)
    return rd


def comparable(receipt):
    """Delivery content without run-dir paths and attempt identities."""
    result = json.loads(json.dumps(receipt['result']))
    return {k: result[k] for k in ('status', 'physics_validated', 'delivery') if k in result}


def test_launch_runs_a_real_ordinary_root_stream_stage_through_run_step(tmp_path, monkeypatch):
    project, spec = real_project(tmp_path, monkeypatch)
    from root_partition_ordinary_fixture import ordinary
    wf = project / 'workflow'
    policy = (wf / 'policy.json').read_bytes()
    (wf / 'policy.json').unlink()  # the base behaviour: a direct run with no policy
    direct_receipt = ordinary(spec, project / 'runs/direct-base')
    (wf / 'policy.json').write_bytes(policy)
    rd = approved_run(project / 'runs/study', spec)
    with pytest.raises(ValueError, match='ravel wms launch'):
        science.run(rd)
    entry = wms_launch.add(project, rd)
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_version', lambda argv: '9.27.0')

    def execute(argv, cwd):
        assert argv == ['/synthetic/snakemake', '--snakefile', str(wf / 'launches/study/000001.parse/Snakefile'), '--directory', str(wf),
                        '--cores', '1', '--retries', '0', 'exports/study/completed/study.json']
        w.run_step(entry['export']['path'], 'study', entry['export']['sha256'])
        return 0, ''
    monkeypatch.setattr(wms_launch, '_execute', execute)
    receipt = wms_launch.launch(project, 'study')
    marker = json.loads((wf / 'exports/study/completed/study.json').read_text())
    assert receipt['exit_code'] == 0 and receipt['completion_marker']['sha256'] == pin(wf / 'exports/study/completed/study.json')['sha256']
    assert marker['status'] == 'delivered' and marker['scientific_acceptance_inferred'] is False
    assert receipt['scientific_acceptance_inferred'] is False and len(receipt['dispatch_records']) == 1
    record = json.loads(Path(receipt['dispatch_records'][0]['path']).read_text())
    assert record['runtime_snapshot']['path'].startswith(str(rd / 'logs/environment/study-'))
    through_wms = stream.ordinary_delivery(rd)
    assert comparable(through_wms) == comparable(direct_receipt)
    assert sorted(through_wms) == sorted(direct_receipt)
    assert wms_launch.status(project)['tasks'][0]['delivered'] is True


def test_real_snakemake_launch_runs_run_step_under_its_lock(tmp_path, monkeypatch):
    snakemake()
    bootstrap = tmp_path / 'bootstrap.py'
    bootstrap.write_text(BOOTSTRAP)
    interpreter = tmp_path / 'analysis-python'
    project_dir = tmp_path / 'project'
    wrapper = project_dir / 'source/runtime/ordinary_reader.py'
    import sys
    interpreter.write_text(f'#!/bin/sh\nexec {sys.executable} -B {bootstrap} {Path(w.__file__).parents[2]} {wrapper} "$@"\n')
    interpreter.chmod(0o755)
    project, spec = real_project(tmp_path, monkeypatch, python=interpreter)
    rd = approved_run(project / 'runs/study', spec)
    wms_launch.add(project, rd)
    receipt = wms_launch.launch(project, 'study')
    log = Path(receipt['log']['path']).read_text()
    assert receipt['exit_code'] == 0, log
    assert receipt['snakemake_version'] == '9.27.0' and receipt['snakemake_locks_present_during_step'] == [True]
    assert receipt['completion_marker'] is not None
    assert stream.ordinary_delivery(rd)['result']['status'] == 'passed'
    view = wms_launch.status(project)['tasks'][0]
    assert view['delivered'] is True and view['dispatches_without_snakemake_lock'] == 0 and view['dispatches_outside_launch'] == 0


@pytest.mark.parametrize('entrypoint', ['science', 'cli'])
def test_indexed_run_refuses_direct_dispatch_after_policy_disabled(project, monkeypatch, capsys, entrypoint):
    from ravel import cli
    rd = project.run_dir('study')
    entry = wms_launch.add(project, rd)
    (project / 'workflow/policy.json').write_text(json.dumps(
        {'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    monkeypatch.setattr(science, 'verify_plan', lambda *a, **k: pytest.fail('direct dispatch reached plan verification'))
    if entrypoint == 'science':
        with pytest.raises(ValueError, match='ravel wms launch'):
            science.run(rd)
    else:
        monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('CLI reached science runner'))
        assert cli.main(['run', '--rundir', str(rd)]) != 0
        assert 'ravel wms launch' in capsys.readouterr().err
    assert not list((Path(entry['export']['path']).parent / 'dispatch').glob('*.json'))


@pytest.mark.parametrize('mutation', ['other_rule', 'snakefile', 'missing_rule'])
def test_launch_refuses_changed_parse_inputs_before_snakemake(project, monkeypatch, mutation):
    for name in ('a', 'b'):
        wms_launch.add(project, project.run_dir(name))
    wf = project / 'workflow'
    if mutation == 'missing_rule':
        (wf / 'rules/a.smk').unlink()
    else:
        path = wf / ('rules/a.smk' if mutation == 'other_rule' else 'Snakefile')
        path.write_bytes(path.read_bytes() + b'\nraise RuntimeError("untrusted parse input")\n')
    calls = []
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: '9.27.0')
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: (calls.append(a) or (0, '')))
    with pytest.raises(ValueError, match='Snakefile|rule'):
        wms_launch.launch(project, 'b')
    assert calls == []


def test_direct_supervisor_main_refuses_approved_governed_science(tmp_path, monkeypatch, capsys):
    from ravel.workflow import stage_supervisor
    project, spec = real_project(tmp_path, monkeypatch)
    rd = approved_run(project / 'runs/study', spec)
    plan = science.verify_plan(rd, approved=True)
    stage = plan['stages'][0]
    args = ['--stage', 'science', '--rundir', str(rd), '--log', stage['log'],
            '--kill-secs', str(plan['max_seconds']), '--cwd', str(rd)]
    for name in stage['inputs']:
        args += ['--input', name]
    for name in stage['outputs']:
        args += ['--output', name]
    assert stage_supervisor.main([*args, '--', *stage['command']]) == 2
    assert 'ravel wms launch' in capsys.readouterr().err
    assert not (rd / 'execution_state.json').exists()


def test_concurrent_launches_reserve_distinct_logs_and_receipts(project, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    wms_launch.add(project, project.run_dir('study'))
    barrier = Barrier(2)
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: '9.27.0')
    def execute(argv, cwd):
        number = barrier.wait(timeout=10)
        return 0, f'launch {number}\n'
    monkeypatch.setattr(wms_launch, '_execute', execute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(wms_launch.launch, project, 'study') for _ in range(2)]
        receipts = [f.result(timeout=20) for f in futures]
    folder = project / 'workflow/launches/study'
    assert sorted(p.name for p in folder.glob('*.json')) == ['000001.json', '000002.json']
    assert len({r['log']['path'] for r in receipts}) == 2
    assert {Path(r['log']['path']).read_text() for r in receipts} == {'launch 0\n', 'launch 1\n'}
    assert all(pin(r['log']['path']) == r['log'] for r in receipts)


def test_launch_preserves_orphan_log_and_allocates_next_number(project, monkeypatch):
    wms_launch.add(project, project.run_dir('study'))
    folder = project / 'workflow/launches/study'
    folder.mkdir()
    (folder / '000001.log').write_text('interrupted launch evidence\n')
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: '9.27.0')
    monkeypatch.setattr(wms_launch, '_execute', lambda *a: (0, 'new evidence\n'))
    receipt = wms_launch.launch(project, 'study')
    assert (folder / '000001.log').read_text() == 'interrupted launch evidence\n'
    assert Path(receipt['log']['path']).name == '000002.log'
    assert (folder / '000002.json').is_file()


def test_real_snakemake_run_step_passes_supervisor_guard_before_execution(tmp_path, monkeypatch):
    """Stop at the next supervisor boundary; no process-identity or worker fake."""
    import sys
    snakemake()
    bootstrap = tmp_path / 'bootstrap.py'
    stop = '''from ravel.workflow import stage_supervisor
 def reached_budget(*args):
     raise ValueError('synthetic stop after workflow dispatch guard')
 stage_supervisor.stage_budget_min = reached_budget
 '''.replace('\n ', '\n')
    bootstrap.write_text(BOOTSTRAP.replace('raise SystemExit(site_workflow.main(args[2:]))',
                                          stop + '\nraise SystemExit(site_workflow.main(args[2:]))'))
    interpreter = tmp_path / 'analysis-python'
    wrapper = tmp_path / 'project/source/runtime/ordinary_reader.py'
    interpreter.write_text(f'#!/bin/sh\nexec {sys.executable} -B {bootstrap} {Path(w.__file__).parents[2]} {wrapper} "$@"\n')
    interpreter.chmod(0o755)
    project, spec = real_project(tmp_path, monkeypatch, python=interpreter)
    rd = approved_run(project / 'runs/study', spec)
    wms_launch.add(project, rd)
    receipt = wms_launch.launch(project, 'study')
    log = Path(receipt['log']['path']).read_text()
    assert receipt['exit_code'] != 0
    assert 'synthetic stop after workflow dispatch guard' in log
    assert 'approved stages run only through Snakemake' not in log
    assert receipt['snakemake_locks_present_during_step'] == [True]
    assert not (rd / 'execution_state.json').exists()


def fake_manager(monkeypatch, execute):
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: '9.27.0')
    monkeypatch.setattr(wms_launch, '_execute', execute)


def dispatch_records(entry):
    return list((Path(entry['export']['path']).parent / 'dispatch').glob('*.json'))


@pytest.mark.parametrize('entrypoint', ['library', 'module', 'cli'])
def test_run_step_by_hand_is_refused_outside_a_live_launch_despite_a_snakemake_lock(project, monkeypatch, capsys, entrypoint):
    """An approved, indexed, unspent task: run-step itself is not the workflow manager."""
    from ravel import cli
    entry = wms_launch.add(project, project.run_dir('study'))
    wf = project / 'workflow'
    (wf / '.snakemake/locks').mkdir(parents=True)
    (wf / '.snakemake/locks/0.input.lock').write_text('stale or unrelated lock\n')
    monkeypatch.chdir(wf)
    monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('a hand-run step reached the runner'))
    argv = ['run-step', '--export', entry['export']['path'], '--task', 'study', '--export-sha256', entry['export']['sha256']]
    if entrypoint == 'cli':
        assert cli.main(['site-workflow', *argv]) != 0
        message = capsys.readouterr().err
    else:
        with pytest.raises(ValueError) as exc:
            if entrypoint == 'library':
                w.run_step(entry['export']['path'], 'study', entry['export']['sha256'])
            else:
                w.main(argv)
        message = str(exc.value)
    assert 'only inside a live `ravel wms launch`' in message
    assert dispatch_records(entry) == []
    assert not (wf / 'exports/study/completed/study.json').exists()


@pytest.mark.parametrize('record', ['stale', 'other-task', 'other-export'])
def test_stale_or_unrelated_launch_authorization_does_not_admit_run_step(project, monkeypatch, record):
    entry = wms_launch.add(project, project.run_dir('study'))
    other = wms_launch.add(project, project.run_dir('other'))
    wf = project / 'workflow'
    monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('an unauthorized step reached the runner'))

    def refused():
        with pytest.raises(ValueError, match='only inside a live `ravel wms launch`'):
            w.run_step(entry['export']['path'], 'study', entry['export']['sha256'])
    if record == 'stale':
        with wms_policy.launch_authorization(wf, 'study', 1, {'study': entry['export']['sha256']}) as path:
            raw = path.read_bytes()
        path.write_bytes(raw)  # the record a launcher that died would leave: content, no live holder
        refused()
    elif record == 'other-task':
        with wms_policy.launch_authorization(wf, 'other', 1, {'other': other['export']['sha256']}):
            refused()
    else:
        with wms_policy.launch_authorization(wf, 'study', 1, {'study': other['export']['sha256']}):
            refused()
    assert dispatch_records(entry) == []


def plain_export(project, rd, out, task='study'):
    """A site-workflow export of a run dir written by hand, with the project's own audit block."""
    wf = project / 'workflow'
    config = json.loads((wf / 'project.json').read_text())
    out.parent.mkdir(parents=True, exist_ok=True)
    request = {'schema_version': 1, 'site_id': config['site_id'], 'python': w._pin(config['python']),
               'tasks': [{'id': task, 'rundir': str(rd.resolve()), 'plan': w._pin(rd / science.PLAN),
                          'owner': {'kind': 'ordinary'}, 'depends_on': []}],
               'audit': wms_launch._freeze(config['audit'], out.parent / f'audit-{out.name}'), 'wms': dict(config['wms'])}
    return w.export(request, out.parent, out)['manifest']


@pytest.mark.parametrize('place', ['outside-the-project', 'inside-exports'])
@pytest.mark.parametrize('indexed', [False, True])
def test_export_the_project_index_does_not_list_never_lifts_the_refusal(project, tmp_path, monkeypatch, place, indexed):
    rd = project.run_dir('study')
    wf = project / 'workflow'
    listed = wms_launch.add(project, rd) if indexed else None
    out = tmp_path / 'elsewhere/export' if place == 'outside-the-project' else wf / 'exports/second'
    manifest = plain_export(project, rd, out)
    monkeypatch.setattr(science, 'run', lambda *a, **k: pytest.fail('an unlisted export reached the runner'))
    exports = {'study': manifest['sha256']} if listed is None else {'study': listed['export']['sha256']}
    with wms_policy.launch_authorization(wf, 'study', 1, exports):  # even while a launch of the task is live
        with pytest.raises(ValueError, match='ravel wms add') as exc:
            w.run_step(manifest['path'], 'study', manifest['sha256'])
    assert 'index does not list this export' in str(exc.value)
    assert not (out / 'dispatch').exists()
    if listed is None:
        assert wms_launch.status(project)['tasks'] == []
    else:
        assert dispatch_records(listed) == []


PROBE = '''import sys
from ravel.workflow import wms_policy
try:
    wms_policy._admit(*sys.argv[1:])
except ValueError as exc:
    raise SystemExit('refused: ' + str(exc))
print('admitted')
'''


def test_launch_authorization_reaches_a_child_process_only_while_the_launch_lives(project, monkeypatch):
    import sys
    rd = project.run_dir('study')
    entry = wms_launch.add(project, rd)
    probe = [sys.executable, '-B', '-c', PROBE, str(rd), entry['export']['path'], entry['export']['sha256'], 'study']

    def execute(argv, cwd):
        done = subprocess.run(probe, capture_output=True, text=True, timeout=120)
        return done.returncode, done.stdout + done.stderr
    fake_manager(monkeypatch, execute)
    receipt = wms_launch.launch(project, 'study')
    assert receipt['exit_code'] == 0 and Path(receipt['log']['path']).read_text().strip() == 'admitted'
    after = subprocess.run(probe, capture_output=True, text=True, timeout=120)
    assert after.returncode != 0 and 'only inside a live `ravel wms launch`' in after.stderr
    assert list((project / 'workflow/.live').glob('*')) == []


def test_launch_of_a_later_task_authorizes_the_unfinished_tasks_it_depends_on(project, monkeypatch):
    first = wms_launch.add(project, project.run_dir('first'))
    wms_launch.add(project, project.run_dir('note'), ['first'])
    unrelated = wms_launch.add(project, project.run_dir('unrelated'))
    seen = {}

    def execute(argv, cwd):
        seen['first'] = wms_policy._admit(first['rundir'], first['export']['path'], first['export']['sha256'], 'first')
        with pytest.raises(ValueError, match='only inside a live `ravel wms launch`'):
            wms_policy._admit(unrelated['rundir'], unrelated['export']['path'], unrelated['export']['sha256'], 'unrelated')
        return 0, ''
    fake_manager(monkeypatch, execute)
    wms_launch.launch(project, 'note')
    assert seen['first'] == project.resolve()


def sha256(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('mutation', ['other_rule', 'snakefile', 'index', 'concurrent_add'])
def test_parse_inputs_changed_after_the_launch_check_never_reach_snakemake(project, monkeypatch, mutation):
    """Snakemake parses the frozen verified copies; the receipt pins exactly those bytes."""
    for name in ('a', 'b'):
        wms_launch.add(project, project.run_dir(name))
    third = project.run_dir('third')
    wf = project / 'workflow'
    verified = {'Snakefile': (wf / 'Snakefile').read_bytes(), 'index.json': (wf / 'index.json').read_bytes(),
                'rules/a.smk': (wf / 'rules/a.smk').read_bytes(), 'rules/b.smk': (wf / 'rules/b.smk').read_bytes()}
    parsed = {}

    def execute(argv, cwd):
        # The moment Snakemake would read its Snakefile, the index and every included rule.
        if mutation == 'concurrent_add':
            wms_launch.add(project, third)
        elif mutation == 'index':
            (wf / 'index.json').write_text(json.dumps({'schema_version': 1, 'tasks': []}))
        else:
            path = wf / ('rules/a.smk' if mutation == 'other_rule' else 'Snakefile')
            path.write_bytes(path.read_bytes() + b'\nraise RuntimeError("untrusted parse input")\n')
        base = Path(argv[argv.index('--snakefile') + 1]).parent
        assert argv[argv.index('--directory') + 1] == str(wf) and cwd == wf
        for path in sorted(p for p in base.rglob('*') if p.is_file()):
            parsed[str(path.relative_to(base))] = path.read_bytes()
        return 0, ''
    fake_manager(monkeypatch, execute)
    receipt = wms_launch.launch(project, 'b')
    assert parsed == verified
    pins = receipt['parse_inputs']
    assert pins['snakefile']['sha256'] == sha256(verified['Snakefile'])
    assert pins['index']['sha256'] == sha256(verified['index.json'])
    assert [(Path(p['path']).name, p['sha256']) for p in pins['rules']] == [
        ('a.smk', sha256(verified['rules/a.smk'])), ('b.smk', sha256(verified['rules/b.smk']))]
    assert all(pin(p['path']) == p for p in (pins['snakefile'], pins['index'], *pins['rules']))
    assert pins['unchanged_after_run'] is True


def test_frozen_parse_copy_altered_during_the_run_is_recorded_in_the_receipt(project, monkeypatch):
    wms_launch.add(project, project.run_dir('study'))

    def execute(argv, cwd):
        copy = Path(argv[argv.index('--snakefile') + 1]).parent / 'rules/study.smk'
        copy.chmod(0o644)
        copy.write_bytes(copy.read_bytes() + b'\n# altered while the manager ran\n')
        return 0, ''
    fake_manager(monkeypatch, execute)
    assert wms_launch.launch(project, 'study')['parse_inputs']['unchanged_after_run'] is False


@pytest.mark.parametrize('layout', ['default-profile', 'empty-folder', 'dangling-link'])
def test_launch_refuses_a_workflow_profiles_folder_before_snakemake(project, monkeypatch, layout):
    """Snakemake applies <workflow>/profiles/default as unrecorded command-line options."""
    wms_launch.add(project, project.run_dir('study'))
    wf = project / 'workflow'
    if layout == 'dangling-link':
        (wf / 'profiles').symlink_to(project / 'absent-profiles')
    else:
        (wf / 'profiles').mkdir()
    if layout == 'default-profile':
        (wf / 'profiles/default').mkdir()
        (wf / 'profiles/default/config.yaml').write_text('dry-run: true\n')
    calls = []
    fake_manager(monkeypatch, lambda *a: (calls.append(a) or (0, '')))
    with pytest.raises(ValueError, match='profile') as exc:
        wms_launch.launch(project, 'study')
    assert str(wf / 'profiles') in str(exc.value)
    assert calls == [] and not (wf / 'launches/study').exists()


@pytest.mark.parametrize('profile', ['/synthetic/profile', None])
def test_launch_runs_snakemake_without_the_profile_environment_variable(project, monkeypatch, profile):
    from types import SimpleNamespace
    wms_launch.add(project, project.run_dir('study'))
    if profile is None:
        monkeypatch.delenv('SNAKEMAKE_PROFILE', raising=False)
    else:
        monkeypatch.setenv('SNAKEMAKE_PROFILE', profile)
    monkeypatch.setenv('RAVEL_SYNTHETIC_KEPT', 'kept')
    seen = []
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: '9.27.0')

    def run(argv, **kwargs):
        seen.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(wms_launch.subprocess, 'run', run)
    receipt = wms_launch.launch(project, 'study')
    assert len(seen) == 1 and 'SNAKEMAKE_PROFILE' not in seen[0] and seen[0]['RAVEL_SYNTHETIC_KEPT'] == 'kept'
    assert os.environ.get('SNAKEMAKE_PROFILE') == profile
    assert receipt['snakemake_profile'] == {'workflow_profiles_folder': False,
                                            'SNAKEMAKE_PROFILE': 'absent' if profile is None else 'removed'}


@pytest.mark.parametrize('change', ['removed', 'disabled', 'reformatted'])
@pytest.mark.parametrize('entrypoint', ['library', 'cli'])
def test_revalidate_acknowledges_a_policy_change_so_a_governed_indexed_task_can_launch(project, monkeypatch, capsys, change, entrypoint):
    from ravel import cli
    rd = project.run_dir('study')
    added = wms_launch.add(project, rd)
    policy = project / 'workflow/policy.json'
    if change == 'removed':
        policy.unlink()
    elif change == 'disabled':
        policy.write_text(json.dumps({'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}))
    else:
        policy.write_text(json.dumps({'engine': 'snakemake', 'wms_required': True, 'schema_version': 1}))
    fake_manager(monkeypatch, lambda *a: (0, ''))
    with pytest.raises(ValueError, match='policy changed') as exc:
        wms_launch.launch(project, 'study')
    assert 'ravel wms revalidate' in str(exc.value) and added['policy']['sha256'] in str(exc.value)
    assert wms_policy.required(rd) is True
    if entrypoint == 'library':
        entry = wms_launch.revalidate(project, 'study')
    else:
        assert cli.main(['wms', 'revalidate', '--project', str(project), '--task', 'study']) == 0
        entry = json.loads(capsys.readouterr().out)
    current = None if change == 'removed' else pin(policy)
    assert entry['policy'] == current and entry == wms_launch._entry(project / 'workflow', 'study')
    assert [(r['previous'], r['current']) for r in entry['policy_revalidations']] == [(added['policy'], current)]
    assert {k: entry[k] for k in ('id', 'rundir', 'export', 'rule', 'after')} == {
        k: added[k] for k in ('id', 'rundir', 'export', 'rule', 'after')}
    assert entry['execution_authorized'] is False
    assert wms_launch.launch(project, 'study')['exit_code'] == 0


@pytest.mark.parametrize('fault', ['approval-lapsed', 'malformed-policy', 'changed-rule', 'unknown-task', 'unchanged'])
def test_revalidate_is_bounded_to_an_approved_intact_task_whose_policy_changed(project, monkeypatch, fault):
    rd = project.run_dir('study')
    wms_launch.add(project, rd)
    wf = project / 'workflow'
    before = (wf / 'index.json').read_bytes() if fault != 'unchanged' else None
    if fault != 'unchanged':
        (wf / 'policy.json').unlink()
    task, message = 'study', 'ravel approve'
    if fault == 'approval-lapsed':
        monkeypatch.setattr(science, 'verify_plan', lambda rd, approved=False, **k: (_ for _ in ()).throw(
            ValueError('missing or stale study approval')) if approved else dict(PLAN))
    elif fault == 'malformed-policy':
        (wf / 'policy.json').write_text('{"schema_version":1,"wms_required":true,"wms_required":false,"engine":"snakemake"}')
        message = 'unreadable or malformed'
    elif fault == 'changed-rule':
        (wf / 'rules/study.smk').write_bytes((wf / 'rules/study.smk').read_bytes() + b'\n# edited\n')
        message = 'rule'
    elif fault == 'unknown-task':
        task, message = 'absent', 'not in the index'
    else:
        before, message = (wf / 'index.json').read_bytes(), 'unchanged'
    with pytest.raises(ValueError, match=message):
        wms_launch.revalidate(project, task)
    assert (wf / 'index.json').read_bytes() == before


def test_launch_whose_dispatch_record_cannot_be_read_still_writes_a_receipt_marked_incomplete(project, monkeypatch):
    entry = wms_launch.add(project, project.run_dir('study'))
    version_read_before_the_stage = []
    monkeypatch.setattr(wms_runtime, 'snakemake_argv', lambda explicit=None: ['/synthetic/snakemake'])
    monkeypatch.setattr(wms_runtime, 'snakemake_version', lambda argv: version_read_before_the_stage.append(True) or '9.27.0')

    def execute(argv, cwd):
        assert version_read_before_the_stage == [True]
        folder = Path(entry['export']['path']).parent / 'dispatch'
        folder.mkdir()
        (folder / '000001.json').write_text('{')
        return 0, 'stage ran\n'
    monkeypatch.setattr(wms_launch, '_execute', execute)
    receipt = wms_launch.launch(project, 'study')
    assert receipt == json.loads((project / 'workflow/launches/study/000001.json').read_text())
    assert receipt['exit_code'] == 0 and receipt['incomplete'] and '000001.json' in receipt['incomplete']
    assert receipt['log'] == pin(project / 'workflow/launches/study/000001.log')
    assert version_read_before_the_stage == [True]


def test_dependency_dispatched_inside_a_later_launch_is_attached_to_that_receipt(project, monkeypatch):
    first = wms_launch.add(project, project.run_dir('first'))
    wms_launch.add(project, project.run_dir('note'), ['first'])

    def execute(argv, cwd):
        folder = Path(first['export']['path']).parent / 'dispatch'
        folder.mkdir()
        (folder / '000001.json').write_text(json.dumps({'schema_version': 1, 'task': 'first', 'snakemake_locks_present': True}))
        return 1, ''
    fake_manager(monkeypatch, execute)
    receipt = wms_launch.launch(project, 'note')
    assert [Path(r['path']).parent.parent.name for r in receipt['dispatch_records']] == ['first']
    rows = {row['id']: row for row in wms_launch.status(project)['tasks']}
    assert rows['first']['dispatches'] == 1 and rows['first']['dispatches_outside_launch'] == 0
    assert receipt['incomplete'] is None


def test_local_project_refuses_site_job_options_and_preserves_legacy_config(project):
    config = json.loads((project / 'workflow/project.json').read_text())
    assert config['profile'] == 'local' and config['wms'] == wms_launch.WMS and 'site' not in config
    with pytest.raises(ValueError, match='--jobs requires'):
        wms_launch.launch(project, 'unused', jobs=2)
    with pytest.raises(ValueError, match='site options require'):
        wms_launch.init(project, audit=audit_files(project), jobs=2)
