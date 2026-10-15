"""Adoption of an external Snakefile: pinned without a parse, inspected and run only when approved.

The supervised tests run real Snakemake when RAVEL_TEST_SNAKEMAKE is set, and a
stand-in executable otherwise. The stand-in executes the Snakefile's leading Python
the way a parse does, so the parse witness means the same thing in both cases.
"""
import json
import os
from pathlib import Path
import sys

import pytest

from ravel.workflow import science, wms_adopt, wms_launch
from method_decision_fixture import admit_method
from test_science_capability_integration import review_contract
from test_wms_launch import project, fake_manager  # noqa: F401

REAL = os.environ.get('RAVEL_TEST_SNAKEMAKE')
WITNESS = 'parse-witness.txt'

SNAKEFILE = '''import pathlib
pathlib.Path("parse-witness.txt").write_text("the Snakefile was parsed\\n")
include: "rules/second.smk"

rule all:
    input: "final.txt"

rule first:
    """Make the first file."""
    output: "first.txt"
    shell: "echo first > {output}"
'''
SECOND = '''rule second:
    input: "first.txt"
    output: "final.txt"
    shell:
        "cat {input} > {output}"
'''
DRY_RUN = '''Building DAG of jobs...
Job stats:
job       count
------  -------
all           1
first         1
second        1
total         3


[Tue Jan  6 05:02:04 2026]
rule first:
    output: first.txt
    jobid: 2
    reason: Missing output files: first.txt
    resources: tmpdir=/tmp
Shell command: echo first > first.txt

[Tue Jan  6 05:02:04 2026]
rule second:
    input: first.txt
    output: final.txt
    jobid: 1
    reason: Missing output files: final.txt
    resources: tmpdir=/tmp
Shell command: cat first.txt > final.txt

[Tue Jan  6 05:02:04 2026]
rule all:
    input: final.txt
    jobid: 0
    reason: Input files updated by another job: final.txt
    resources: tmpdir=/tmp
Shell command: None
Job stats:
job       count
------  -------
all           1
first         1
second        1
total         3

This was a dry-run (flag -n). The order of jobs does not reflect the order of execution.
'''
# The same dry run after an intermediate file was removed: one more job, whose command no approval showed.
EXTRA_JOB = DRY_RUN.replace('total         3', 'total         4').replace(
    '[Tue Jan  6 05:02:04 2026]\nrule all:',
    '[Tue Jan  6 05:02:04 2026]\nrule regenerate:\n    output: seed.txt\n    jobid: 3\n'
    'Shell command: echo seed > seed.txt\n\n[Tue Jan  6 05:02:04 2026]\nrule all:', 1)
STAND_IN = '''#!{python}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args == ['--version']:
    if os.environ.get('STAND_IN_EDITS_ON_VERSION'):
        with open(os.environ['STAND_IN_EDITS_ON_VERSION'], 'a') as stream:
            stream.write('# edited while the version was read\\n')
    print('9.27.0')
    raise SystemExit(0)
with Path(__file__).with_name('calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
snakefile = args[args.index('--snakefile') + 1]
os.chdir(args[args.index('--directory') + 1])
outside = os.environ.get('STAND_IN_OUTSIDE_OUTPUT')
from snakemake.workflow import Workflow
Workflow().include(snakefile)
if '--list-rules' in args:
    print('all\\nfirst (Make the first file.)\\nsecond')
elif '--dag' in args:
    print('Building DAG of jobs...\\ndigraph snakemake_dag {{\\n\\t0[label = "all"];\\n\\t1 -> 0\\n}}')
elif '--summary' in args:
    print('Building DAG of jobs...\\noutput_file\\tdate\\trule\\tlog-file(s)\\tstatus\\tplan\\n'
          'final.txt\\t-\\tsecond\\t-\\tmissing\\tupdate pending\\nfirst.txt\\t-\\tfirst\\t-\\tmissing\\tupdate pending'
          + (f'\\n{{outside}}\\t-\\tsecond\\t-\\tmissing\\tupdate pending' if outside else ''))
elif '--dry-run' in args:
    text = {extra!r} if os.environ.get('STAND_IN_EXTRA_JOB') == '1' else {dry!r}
    # The rule that makes final.txt then also writes a second file, somewhere else.
    print(text.replace('output: final.txt', 'output: final.txt, ' + outside) if outside else text)
elif os.environ.get('STAND_IN_SKIPS_OUTPUT') != '1':
    Path('first.txt').write_text('first\\n')
    Path('final.txt').write_text('first\\n')
'''


def study():
    return {'source': 'Explicit synthetic external workflow control',
            'assumptions': ['The two-rule workflow is a synthetic engineering control'],
            'max_seconds': 300, 'approval_mode': 'scripted_yes', 'review_policy': review_contract()}


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    """A synthetic two-rule external workflow whose top level writes a parse witness."""
    base = tmp_path.resolve()
    (base / 'wf/rules').mkdir(parents=True)
    (base / 'work').mkdir()
    (base / 'wf/Snakefile').write_text(SNAKEFILE)
    (base / 'wf/rules/second.smk').write_text(SECOND)
    if REAL:
        executable = REAL
    else:
        executable = base / 'bin/workflow-manager'
        executable.parent.mkdir()
        package = executable.parent / 'snakemake'
        package.mkdir()
        (package / '__init__.py').write_text('')
        (package / 'cli.py').write_text('')
        (package / 'sourcecache.py').write_text(FAKE_SOURCECACHE)
        (package / 'workflow.py').write_text(FAKE_WORKFLOW)
        monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
        executable.write_text(STAND_IN.format(python=sys.executable, dry=DRY_RUN, extra=EXTRA_JOB))
        executable.chmod(0o755)
    return {'base': base, 'snakefile': base / 'wf/Snakefile', 'include': base / 'wf/rules/second.smk',
            'workdir': base / 'work', 'rundir': base / 'adoption', 'snakemake': str(executable)}


def adopt(workflow, **options):
    return wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study(),
                           snakemake=workflow['snakemake'], **options)


def calls(workflow):
    log = Path(workflow['snakemake']).with_name('calls.jsonl')
    return [json.loads(line) for line in log.read_text().splitlines()] if log.is_file() else []


def nothing_parsed(workflow):
    return not (workflow['workdir'] / WITNESS).exists() and (REAL or calls(workflow) == [])


def supervised():
    from ravel.workflow.execution import process_identity
    if process_identity(os.getpid()) is None:
        pytest.skip('sandbox denies process identity; the supervised stage needs the coordinator queue')


def approve_and_run(rundir):
    admit_method(rundir)
    science.approve(rundir, 'Approved synthetic external workflow control', scripted=True)
    return science.run(rundir)


def log_of(rundir):
    """Worker log and the supervisor's failure record, for a failing assertion."""
    return '\n'.join(p.read_text(errors='replace') for p in sorted(
        [*Path(rundir, 'logs').glob('science-*.log'), *Path(rundir, 'logs').glob('science.failure.json')]))


def inspected(workflow, **options):
    supervised()
    adopt(workflow, **options)
    assert nothing_parsed(workflow)
    inspect = workflow['rundir'] / 'inspect'
    assert approve_and_run(inspect) == 0, log_of(inspect)
    return wms_adopt.plan_run(workflow['rundir'])


# ----------------------------------------------------------------- acceptance 1: parse only when approved
def test_adopt_pins_the_closure_and_parses_nothing(workflow):
    result = adopt(workflow)
    record = json.loads((workflow['rundir'] / 'adoption.json').read_text())
    assert [(row['role'], row['path']) for row in record['files']] == [
        ('snakefile', str(workflow['snakefile'])), ('include', str(workflow['include']))]
    assert record['files'][1]['included_by'] == str(workflow['snakefile']) and record['files'][1]['line'] == 3
    assert all(row == {**row, **wms_adopt._pin(row['path'])} for row in record['files'])
    assert {row['name']: row['actions'] for row in record['rules']} == {'all': [], 'first': ['shell'], 'second': ['shell']}
    assert record['snakefile_parsed'] is False and result['execution_authorized'] is False
    assert nothing_parsed(workflow)
    # The inspection is planned as an ordinary study and is not approved.
    inspect = workflow['rundir'] / 'inspect'
    assert (inspect / science.PLAN).is_file() and not (inspect / science.APPROVAL).exists()
    shown = json.loads((inspect / 'inputs/checkin1.json').read_text())['sections']['i-b']['task']
    assert shown['commands'] == wms_adopt.inspection_commands(record)
    assert [row['path'] for row in shown['files']] == [str(workflow['snakefile']), str(workflow['include'])]


def test_unapproved_inspection_parses_and_writes_nothing(workflow):
    adopt(workflow)
    inspect = workflow['rundir'] / 'inspect'
    # The existing launch guard applies: no approval without the method decision, no run without approval.
    with pytest.raises(ValueError, match='method decision'):
        science.approve(inspect, 'Approved synthetic external workflow control', scripted=True)
    assert not (inspect / science.APPROVAL).exists()
    admit_method(inspect)
    with pytest.raises((ValueError, OSError)):
        science.run(inspect)
    assert nothing_parsed(workflow)
    assert not (inspect / 'outputs').exists() and wms_adopt.latest_inspection(workflow['rundir']) is None
    with pytest.raises(ValueError, match='no inspection yet'):
        wms_adopt.plan_run(workflow['rundir'])
    assert not (workflow['rundir'] / 'run').exists()


def test_the_parse_runs_inside_the_approved_inspection_and_checkin_shows_its_roster(workflow):
    planned = inspected(workflow)
    assert (workflow['workdir'] / WITNESS).read_text() == 'the Snakefile was parsed\n'
    document = json.loads(wms_adopt.latest_inspection(workflow['rundir']).read_text())
    assert document['status'] == 'passed' and document['jobs_run'] == 0
    assert [row['name'] for row in document['commands']] == ['rules', 'dag', 'summary', 'jobs']
    assert all(row['exit_code'] == 0 for row in document['commands'])
    assert all('--dry-run' in row['argv'] or '--list-rules' in row['argv'] for row in document['commands'])
    roster = document['roster']
    assert [row['name'] for row in roster['rules']] == ['all', 'first', 'second']
    assert roster['shell_commands'] == ['cat first.txt > final.txt', 'echo first > first.txt']
    assert roster['jobs_without_shell_command'] == ['all']
    assert {row['output_file']: row['rule'] for row in document['summary']} == {'final.txt': 'second', 'first.txt': 'first'}
    assert Path(document['dag']['path']).read_text().startswith('digraph ')
    # No job ran: the workflow's outputs do not exist yet.
    assert not (workflow['workdir'] / 'first.txt').exists() and not (workflow['workdir'] / 'final.txt').exists()
    # CHECK-IN 1 of the run study shows the rule roster and every shell command; nothing is approved.
    run = workflow['rundir'] / 'run'
    assert planned['execution_authorized'] is False and not (run / science.APPROVAL).exists()
    task = json.loads((run / 'inputs/checkin1.json').read_text())['sections']['i-b']['task']
    assert task['roster']['shell_commands'] == ['cat first.txt > final.txt', 'echo first > first.txt']
    assert [row['name'] for row in task['roster']['rules']] == ['all', 'first', 'second']
    assert [row['rule'] for row in task['roster']['jobs']] == ['all', 'second', 'first']
    # Every rule's own source text is shown too, for jobs that this dry run did not schedule.
    assert [(row['name'], row['line']) for row in task['rules']] == [('all', 5), ('first', 8), ('second', 1)]
    assert task['roster']['listed_without_declaration'] == []
    assert task['command'][-2:] == ['--cores', '1'] and '--dry-run' not in task['command']
    assert not (workflow['workdir'] / 'final.txt').exists()


# ----------------------------------------------------------------- acceptance 2: a changed file is refused
def test_launch_after_a_pinned_file_changed_is_refused_by_name(workflow):
    inspected(workflow)
    run = workflow['rundir'] / 'run'
    admit_method(run)
    science.approve(run, 'Approved synthetic external workflow control', scripted=True)
    before = len(calls(workflow))
    for changed in ('include', 'snakefile'):
        original = workflow[changed].read_text()
        workflow[changed].write_text(original + '\nrule added_after_approval:\n    output: "extra.txt"\n'
                                     '    shell: "echo extra > {output}"\n')
        with pytest.raises(ValueError, match='changed since adoption') as refusal:
            science.run(run)
        assert str(workflow[changed]) in str(refusal.value)
        assert wms_adopt.status(workflow['rundir'])['changed_files'] == [{'path': str(workflow[changed]), 'state': 'changed'}]
        workflow[changed].write_text(original)
    assert not (workflow['workdir'] / 'final.txt').exists() and not (run / 'outputs').exists()
    assert not (run / 'execution_attempt.json').exists()
    assert REAL or len(calls(workflow)) == before


def test_planning_the_run_after_a_change_is_refused_by_name(workflow):
    supervised()
    adopt(workflow)
    inspect = workflow['rundir'] / 'inspect'
    assert approve_and_run(inspect) == 0, log_of(inspect)
    workflow['include'].write_text(SECOND + '\n# edited after the inspection\n')
    with pytest.raises(ValueError, match='second.smk changed since adoption'):
        wms_adopt.plan_run(workflow['rundir'])
    assert not (workflow['rundir'] / 'run').exists()


# ----------------------------------------------------------------- acceptance 3: one supervised stage
def test_the_adopted_workflow_runs_as_one_supervised_stage_with_bound_outputs(workflow):
    inspected(workflow, targets=['final.txt'], outputs=['final.txt'])
    run = workflow['rundir'] / 'run'
    assert approve_and_run(run) == 0, log_of(run)
    assert (workflow['workdir'] / 'final.txt').read_text() == 'first\n'
    out = run / 'outputs/attempt-1'
    receipt = json.loads((out / 'external-workflow/receipt.json').read_text())
    assert receipt['status'] == 'passed' and receipt['exit_code'] == 0
    assert receipt['argv'][-4:] == ['--cores', '1', '--', 'final.txt'] and '--dry-run' not in receipt['argv']
    # The receipt lists the Snakefile pins.
    assert [(row['role'], row['path'], row['sha256']) for row in receipt['pins']] == [
        ('snakefile', str(workflow['snakefile']), wms_adopt._pin(workflow['snakefile'])['sha256']),
        ('include', str(workflow['include']), wms_adopt._pin(workflow['include'])['sha256'])]
    assert receipt['pins_unchanged_after_run'] is True
    assert receipt['preflight_log']['stdout']['path'] == str(out / 'external-workflow/preflight.stdout.txt')
    # The declared output is bound: a pinned copy inside the stage output.
    bound, = receipt['outputs']
    delivered = out / 'external-workflow/delivered/final.txt'
    assert bound['output'] == 'final.txt' and bound['delivered'] == wms_adopt._pin(delivered)
    assert bound['source']['sha256'] == bound['delivered']['sha256'] and delivered.read_text() == 'first\n'
    assert receipt['scientific_acceptance_inferred'] is False and receipt['records'] == 'delivery only'
    # One stage of the ordinary supervisor ran it, and its receipt binds the pinned files as inputs.
    state = json.loads((run / 'execution_state.json').read_text())
    assert list(state['stages']) == ['science']
    snapshot = json.dumps(state['stages']['science'])
    assert str(workflow['snakefile']) in snapshot and str(workflow['include']) in snapshot
    result = json.loads((out / 'result.json').read_text())
    assert result['status'] == 'passed' and result['physics_validated'] is False and result['operation'] == 'run'
    assert wms_adopt.status(workflow['rundir'])['receipts'][0]['status'] == 'passed'


# ----------------------------------------------------------------- the adapter entry requires the supervised worker
def test_the_adapter_entry_refuses_outside_the_approved_supervised_worker(workflow, tmp_path):
    adopt(workflow)
    root = workflow['rundir']
    task = json.loads((root / 'inspect.science.json').read_text())['task']
    # Neither a free destination nor the inspection study's own attempt folder admits a direct call.
    for destination in (tmp_path / 'direct-out', root / 'inspect/outputs/attempt-1'):
        with pytest.raises(ValueError, match='approved supervised'):
            wms_adopt.run(task, root, destination)
        assert not destination.exists()
    record = json.loads((root / 'adoption.json').read_text())
    run_task = {'schema_version': 1, 'operation': 'run', 'adoption': 'adoption.json', 'files': wms_adopt._shown_files(record),
                'unpinned_references': record['unpinned_references'], 'rules': record['rules'],
                'inspection': str(tmp_path / 'forged.json'), 'command': wms_adopt.run_command(record), 'roster': {}}
    with pytest.raises(ValueError, match='approved supervised'):
        wms_adopt.run(run_task, root, tmp_path / 'run-out')
    assert nothing_parsed(workflow) and not (tmp_path / 'run-out').exists()
    assert not (workflow['workdir'] / 'final.txt').exists()


def test_planning_the_run_refuses_an_inspection_that_no_supervised_attempt_produced(workflow):
    adopt(workflow)
    root = workflow['rundir']
    forged = root / 'inspect/outputs/attempt-1/external-workflow/inspection.json'
    forged.parent.mkdir(parents=True)
    forged.write_text(json.dumps({'status': 'passed', 'problems': [], 'adoption': wms_adopt._pin(root / 'adoption.json'),
                                  'roster': {'rules': [], 'jobs': [{'rule': 'all'}], 'shell_commands': []},
                                  'snakemake': {'version': '9.27.0'}, 'summary': []}))
    with pytest.raises(ValueError, match='supervised'):
        wms_adopt.plan_run(root)
    assert not (root / 'run').exists() and nothing_parsed(workflow)


# ----------------------------------------------------------------- the adapter's own steps, without the worker entry
def internal(workflow, tmp_path, **options):
    """Adoption and inspection through the adapter's own steps, for the stand-in executable."""
    if REAL:
        pytest.skip('stand-in executable only')
    adopt(workflow, **options)
    path = workflow['rundir'] / 'adoption.json'
    record = json.loads(path.read_text())
    folder = tmp_path / 'inspect-out'
    folder.mkdir()
    inspection = wms_adopt._inspect(path, record, folder)
    assert inspection['status'] == 'passed', inspection['problems']
    return path, record, inspection


def run_task(record, inspection_path):
    return {'schema_version': 1, 'operation': 'run', 'adoption': 'adoption.json', 'files': wms_adopt._shown_files(record),
            'unpinned_references': record['unpinned_references'], 'rules': record['rules'],
            'inspection': str(inspection_path), 'command': wms_adopt.run_command(record),
            'roster': json.loads(Path(inspection_path).read_text())['roster']}


def run_folder(tmp_path, name='run-out'):
    folder = tmp_path / name
    folder.mkdir()
    return folder


def launched(workflow):
    """Snakemake calls that would run jobs: neither a dry run nor a rule listing."""
    return [argv for argv in calls(workflow) if '--dry-run' not in argv and '--list-rules' not in argv]


def test_a_required_output_that_is_absent_fails_the_stage(workflow, tmp_path):
    path, record, inspection = internal(workflow, tmp_path, outputs=['final.txt', 'never-made.txt'])
    folder = run_folder(tmp_path)
    receipt = wms_adopt._run(path, record, inspection, folder)
    assert receipt['status'] == 'failed'
    assert receipt['problems'] == ['declared output never-made.txt is not present after the run']
    assert [row['output'] for row in receipt['outputs']] == ['final.txt'] and receipt['exit_code'] == 0


def test_outputs_default_to_the_files_the_workflow_declares(workflow, tmp_path):
    path, record, inspection = internal(workflow, tmp_path)
    receipt = wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert receipt['status'] == 'passed' and receipt['outputs_declared_by'] == 'workflow'
    assert [row['output'] for row in receipt['outputs']] == ['final.txt', 'first.txt'] and receipt['absent_outputs'] == []


def test_the_adapter_refuses_a_changed_include_and_a_foreign_roster(workflow, tmp_path):
    path, record, inspection = internal(workflow, tmp_path)
    task = run_task(record, tmp_path / 'inspect-out/inspection.json')
    with pytest.raises(ValueError, match='roster differs'):
        wms_adopt.inputs({**task, 'roster': {**task['roster'], 'shell_commands': ['echo first > first.txt']}}, workflow['rundir'])
    with pytest.raises(ValueError, match='different run command'):
        wms_adopt.inputs({**task, 'command': [*task['command'], '--forceall']}, workflow['rundir'])
    with pytest.raises(ValueError, match='different rules'):
        wms_adopt.inputs({**task, 'rules': task['rules'][:1]}, workflow['rundir'])
    executable = Path(workflow['snakemake'])
    executable.write_text(executable.read_text().replace("print('9.27.0')", "print('9.99.0')"))
    with pytest.raises(ValueError, match='Snakemake is now version 9.99.0; the inspection was made with 9.27.0'):
        wms_adopt._run(path, record, inspection, run_folder(tmp_path, 'other-version'))
    assert not (workflow['workdir'] / 'final.txt').exists()
    executable.write_text(executable.read_text().replace("print('9.99.0')", "print('9.27.0')"))
    workflow['include'].write_text(SECOND.replace('cat', 'tac'))
    with pytest.raises(ValueError, match=f"adopted workflow file {workflow['include']} changed since adoption"):
        wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert launched(workflow) == [] and not (workflow['workdir'] / 'final.txt').exists()


def test_a_file_changed_while_the_version_is_read_never_launches(workflow, tmp_path, monkeypatch):
    path, record, inspection = internal(workflow, tmp_path)
    monkeypatch.setenv('STAND_IN_EDITS_ON_VERSION', str(workflow['include']))
    with pytest.raises(ValueError, match=f"{workflow['include']} changed since adoption"):
        wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert launched(workflow) == [] and not (workflow['workdir'] / 'final.txt').exists()


def test_a_job_the_approved_roster_does_not_show_refuses_the_launch(workflow, tmp_path, monkeypatch):
    path, record, inspection = internal(workflow, tmp_path)
    # An intermediate file was removed after the inspection: the dry run now schedules a job no approval showed.
    monkeypatch.setenv('STAND_IN_EXTRA_JOB', '1')
    with pytest.raises(ValueError, match=r'regenerate \(echo seed > seed.txt\)') as refusal:
        wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert 'adopt the workflow again' in str(refusal.value)
    assert launched(workflow) == [] and not (workflow['workdir'] / 'final.txt').exists()


def test_a_snakemake_profile_never_reaches_the_workflow(workflow, tmp_path, monkeypatch):
    monkeypatch.setenv('SNAKEMAKE_PROFILE', str(tmp_path / 'unpinned-profile'))
    _, record, _ = internal(workflow, tmp_path)
    for argv in calls(workflow):
        assert argv[argv.index('--profile') + 1] == 'none' and argv[argv.index('--workflow-profile') + 1] == 'none'
    assert wms_adopt.run_command(record)[5:9] == ['--profile', 'none', '--workflow-profile', 'none']


def test_every_inspection_call_is_a_dry_run(workflow):
    adopt(workflow)
    record = json.loads((workflow['rundir'] / 'adoption.json').read_text())
    assert all('--dry-run' in argv for argv in wms_adopt.inspection_commands(record).values())


# ----------------------------------------------------------------- containment
def test_a_declared_output_through_a_link_that_leaves_the_working_directory_is_refused(workflow, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (workflow['workdir'] / 'linked').symlink_to(outside)
    with pytest.raises(ValueError, match='linked/result.txt is outside the working directory'):
        adopt(workflow, outputs=['linked/result.txt'])
    assert not workflow['rundir'].exists()


def test_an_output_folder_retargeted_after_adoption_refuses_the_launch(workflow, tmp_path):
    (workflow['workdir'] / 'results').mkdir()
    path, record, inspection = internal(workflow, tmp_path, outputs=['results/final.txt'])
    outside = tmp_path / 'outside'
    outside.mkdir()
    (workflow['workdir'] / 'results').rmdir()
    (workflow['workdir'] / 'results').symlink_to(outside)
    with pytest.raises(ValueError, match='results/final.txt is outside the working directory'):
        wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert launched(workflow) == []


@pytest.mark.parametrize('name', ['{base}/outside/leak.txt', '../leak.txt'])
@pytest.mark.parametrize('appears', ['at the inspection', 'after the inspection'])
def test_a_workflow_output_outside_the_working_directory_refuses_the_launch(workflow, tmp_path, monkeypatch, name, appears):
    """Naming the outputs to deliver does not switch off the check of the other files the workflow writes."""
    name = name.format(base=workflow['base'])
    if appears == 'at the inspection':
        monkeypatch.setenv('STAND_IN_OUTSIDE_OUTPUT', name)
    path, record, inspection = internal(workflow, tmp_path, outputs=['final.txt'])
    assert (name in [row['output_file'] for row in inspection['summary']]) == (appears == 'at the inspection')
    # Afterwards the dry run before launch is the one place that shows the new output.
    monkeypatch.setenv('STAND_IN_OUTSIDE_OUTPUT', name)
    with pytest.raises(ValueError) as refusal:
        wms_adopt._run(path, record, inspection, run_folder(tmp_path))
    assert f'output {name} is outside the working directory; Snakemake was not started' in str(refusal.value)
    assert launched(workflow) == [] and not (workflow['workdir'] / 'final.txt').exists()


def test_a_linked_member_of_an_output_folder_is_neither_read_nor_copied(workflow, tmp_path):
    secret = tmp_path / 'outside.txt'
    secret.write_text('outside the working directory\n')
    folder = workflow['workdir'] / 'results'
    folder.mkdir()
    (folder / 'kept.txt').write_text('kept\n')
    (folder / 'leak.txt').symlink_to(secret)
    record = {'workdir': str(workflow['workdir']), 'outputs': ['results']}
    out = run_folder(tmp_path)
    bound, absent, required = wms_adopt._deliver(record, [], out)
    assert [row['source']['path'] for row in bound] == [str(folder / 'kept.txt')]
    assert absent == [{'path': 'results/leak.txt', 'reason': 'outside the working directory'}] and required
    assert not (out / 'delivered/results/leak.txt').exists()


# ----------------------------------------------------------------- static closure
def closure(tmp_path, text, **files):
    base = tmp_path.resolve() / 'static'
    (base / 'work').mkdir(parents=True)
    for name, content in files.items():
        path = base / name.replace('__', '/')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (base / 'Snakefile').write_text(text)
    return base, wms_adopt.scan(base / 'Snakefile', base / 'work')


def test_includes_in_blocks_branches_and_nested_files_are_pinned(tmp_path):
    text = ('if True:\n    include: "a.smk"\nelse:\n    include: "b.smk"\ninclude:\n    "c.smk"\n'
            'module other:\n    snakefile: "mod/Snakefile"\n    config: config\n')
    base, found = closure(tmp_path, text, **{'a.smk': 'include: "sub/d.smk"\n', 'b.smk': '', 'c.smk': '',
                                             'sub__d.smk': 'rule deep:\n    output: "x"\n    run:\n        pass\n',
                                             'mod__Snakefile': ''})
    assert sorted((row['role'], Path(row['path']).relative_to(base).as_posix()) for row in found['files']) == [
        ('include', 'a.smk'), ('include', 'b.smk'), ('include', 'c.smk'), ('include', 'sub/d.smk'),
        ('module', 'mod/Snakefile'), ('snakefile', 'Snakefile')]
    assert found['rules'] == [{'name': 'deep', 'file': str(base / 'sub/d.smk'), 'line': 1, 'actions': ['run'],
                               'source': 'rule deep:\n    output: "x"\n    run:\n        pass\n'}]
    assert [(row['path'], row['line'], row['role']) for row in found['includes']] == [
        ('a.smk', 2, 'include'), ('b.smk', 4, 'include'), ('c.smk', 5, 'include'), ('mod/Snakefile', 8, 'module'),
        ('sub/d.smk', 1, 'include')]
    assert found['includes'][-1] == {'file': str(base / 'a.smk'), 'line': 1, 'path': 'sub/d.smk', 'role': 'include',
                                     'resolved': str(base / 'sub/d.smk')}


def test_python_api_includes_and_an_include_named_by_a_directive_are_scanned(tmp_path):
    text = ('workflow.include("late.smk")\nrule a:\n    output: "a.txt"\n    script: "shared.smk"\n'
            'include: "shared.smk"\n')
    base, found = closure(tmp_path, text, **{'late.smk': '', 'shared.smk': 'include: "deep.smk"\n', 'deep.smk': ''})
    assert sorted((row['role'], Path(row['path']).relative_to(base).as_posix()) for row in found['files']) == [
        ('include', 'deep.smk'), ('include', 'late.smk'), ('script', 'shared.smk'), ('snakefile', 'Snakefile')]
    assert sorted((row['path'], row['line']) for row in found['includes']) == [
        ('deep.smk', 1), ('late.smk', 1), ('shared.smk', 5)]


def test_an_include_outside_the_allowed_roots_is_refused(tmp_path):
    elsewhere = tmp_path.resolve() / 'elsewhere/rules.smk'
    elsewhere.parent.mkdir()
    elsewhere.write_text('')
    with pytest.raises(ValueError, match='outside the allowed roots') as refusal:
        closure(tmp_path, f'include: "{elsewhere}"\n')
    assert 'nothing was parsed' in str(refusal.value)
    base = tmp_path.resolve() / 'static'
    assert wms_adopt.scan(base / 'Snakefile', base / 'work', [elsewhere.parent])['files'][1]['path'] == str(elsewhere)


def test_retargeting_an_include_link_after_adoption_is_refused_by_name(workflow):
    rules = workflow['base'] / 'wf/rules'
    (rules / 'v1.smk').write_text(SECOND)
    (rules / 'v2.smk').write_text(SECOND.replace('cat', 'tac'))
    (rules / 'current.smk').symlink_to('v1.smk')
    workflow['snakefile'].write_text(SNAKEFILE.replace('rules/second.smk', 'rules/current.smk'))
    adopt(workflow)
    record = json.loads((workflow['rundir'] / 'adoption.json').read_text())
    wms_adopt.check_pins(record)
    (rules / 'current.smk').unlink()
    (rules / 'current.smk').symlink_to('v2.smk')
    assert wms_adopt.changed_files(record) == [
        (f"{workflow['snakefile']}:3 include rules/current.smk", f"now resolves to {rules / 'v2.smk'}, adopted as "
         f"{rules / 'v1.smk'}"), (str(rules / 'v2.smk'), 'is newly named by the workflow')]
    with pytest.raises(ValueError, match='include rules/current.smk now resolves to .*v2.smk'):
        wms_adopt.check_pins(record)


def test_the_inspection_checkin_shows_every_rule_with_its_source(workflow):
    workflow['include'].write_text(SECOND + '\nrule unused:\n    output: "unused.txt"\n    shell:\n        """\n'
                                   '        echo one > {output}\n\n          echo two >> {output}\n        """\n')
    adopt(workflow)
    shown = json.loads((workflow['rundir'] / 'inspect/inputs/checkin1.json').read_text())['sections']['i-b']['task']
    rules = {row['name']: row for row in shown['rules']}
    assert list(rules) == ['all', 'first', 'second', 'unused']
    assert rules['first']['file'] == str(workflow['snakefile']) and rules['first']['line'] == 8
    assert rules['first']['source'] == ('rule first:\n    """Make the first file."""\n    output: "first.txt"\n'
                                        '    shell: "echo first > {output}"\n')
    assert rules['unused']['source'].endswith('        echo one > {output}\n\n          echo two >> {output}\n        """\n')


def test_a_line_the_snakefile_printed_is_not_a_rule():
    rules, printed, undeclared = wms_adopt.parse_rules('phantom\nall\nfirst (Make the first file.)\nnot a rule name\n',
                                                       [{'name': 'all', 'actions': []}, {'name': 'first', 'actions': ['shell']}])
    assert [row['name'] for row in rules] == ['all', 'first']
    assert printed == ['not a rule name'] and undeclared == ['phantom']
    used = wms_adopt.parse_rules('other_tool\n', [{'name': 'other_*', 'actions': ['use rule']}])
    assert [row['name'] for row in used[0]] == ['other_tool'] and used[2] == []


@pytest.mark.parametrize('text, message', [
    ('include: "rules/" + name + ".smk"\n', r'Snakefile:1: `include:` is not a literal path'),
    ('x = 1\ninclude: f"{x}.smk"\n', r'Snakefile:2: `include:` is not a literal path'),
    ('include: "https://example.invalid/rules.smk"\n', 'names remote code'),
    ('include: "absent.smk"\n', 'absent.smk is not a regular file'),
    ('module other:\n    snakefile: github("owner/repository", path="Snakefile")\n', '`snakefile:` is not a literal path'),
    ('module other:\n    meta_wrapper: "v1/meta/tool"\n', 'names remote code'),
    ('rule broken:\n    shell: "unterminated\n', 'cannot be read as Snakefile text'),
])
def test_a_file_that_cannot_be_pinned_refuses_the_adoption(tmp_path, text, message):
    with pytest.raises(ValueError, match=message) as refusal:
        closure(tmp_path, text)
    assert 'nothing was parsed' in str(refusal.value)


def test_referenced_files_are_pinned_and_the_rest_is_listed(tmp_path):
    text = ('configfile: "settings.yaml"\nrule a:\n    output: "a.txt"\n    conda: "envs/a.yaml"\n'
            '    script:\n        "scripts/a.py"\nrule b:\n    output: "b.txt"\n    script: "scripts/{wildcards.x}.py"\n'
            'rule c:\n    output: "c.txt"\n    wrapper: "v1/bio/tool"\nrule d:\n    output: "d.txt"\n    notebook: path_of_notebook\n')
    base, found = closure(tmp_path, text, **{'work__settings.yaml': 'k: 1\n', 'envs__a.yaml': '', 'scripts__a.py': ''})
    assert sorted((row['role'], Path(row['path']).relative_to(base).as_posix()) for row in found['files']) == [
        ('conda', 'envs/a.yaml'), ('configfile', 'work/settings.yaml'), ('script', 'scripts/a.py'), ('snakefile', 'Snakefile')]
    assert [(row['directive'], row['line'], row['reason']) for row in found['unpinned_references']] == [
        ('script', 9, 'a pattern or remote name'), ('wrapper', 12, 'remote wrapper code'), ('notebook', 15, 'not a literal path')]
    assert {row['name']: row['actions'] for row in found['rules']} == {
        'a': ['script'], 'b': ['script'], 'c': ['wrapper'], 'd': ['notebook']}


def test_adopt_refusals_leave_no_folder_and_parse_nothing(workflow, monkeypatch):
    for options, message in [({'targets': ['--forceall']}, 'must be a plain name'), ({'cores': 0}, 'positive integer'),
                             ({'outputs': ['../outside.txt']}, 'inside the working directory'),
                             ({'pins': [workflow['base'] / 'absent.py']}, 'is not a regular file')]:
        with pytest.raises(ValueError, match=message):
            adopt(workflow, **options)
        assert not workflow['rundir'].exists()
    with pytest.raises(ValueError, match='requires exactly'):
        wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], {'source': 'incomplete'},
                        snakemake=workflow['snakemake'])
    with pytest.raises(ValueError, match='absent-snakemake is not an executable file'):
        wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study(),
                        snakemake=str(workflow['base'] / 'absent-snakemake'))
    with monkeypatch.context() as patch:
        patch.setattr(wms_adopt.wms_runtime, 'snakemake_argv', lambda: [])
        with pytest.raises(ValueError, match='no Snakemake executable found'):
            wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], study())
    # A study the science planner refuses removes the folder the adoption created.
    with pytest.raises(ValueError):
        wms_adopt.adopt(workflow['snakefile'], workflow['workdir'], workflow['rundir'], {**study(), 'max_seconds': 0},
                        snakemake=workflow['snakemake'])
    assert not workflow['rundir'].exists() and nothing_parsed(workflow)
    helper = workflow['base'] / 'wf/helper.py'
    helper.write_text('VALUE = 1\n')
    result = adopt(workflow, pins=[helper])
    assert result['files'][-1] == {'role': 'declared', **wms_adopt._pin(helper), 'included_by': None, 'line': None}
    with pytest.raises(ValueError, match='already exists'):
        adopt(workflow)


# ----------------------------------------------------------------- reading Snakemake's output
def test_dry_run_jobs_keep_multi_line_shell_commands_and_python_actions():
    text = DRY_RUN.replace('Shell command: cat first.txt > final.txt',
                           'Shell command: \n        cat first.txt > final.txt\n        echo second >> final.txt\n        ')
    jobs, total = wms_adopt.parse_jobs(text.replace('rule second:', 'localcheckpoint second:'))
    assert total == 3 and [(job['rule'], job['jobid']) for job in jobs] == [('first', 2), ('second', 1), ('all', 0)]
    # The command text is kept exactly as Snakemake printed it, indentation included.
    assert jobs[1] == {'rule': 'second', 'jobid': 1, 'input': ['first.txt'], 'output': ['final.txt'],
                       'shell': '\n        cat first.txt > final.txt\n        echo second >> final.txt\n        '}
    assert jobs[2]['shell'] is None
    rules, printed, _ = wms_adopt.parse_rules('a line the Snakefile printed\nall\nfirst (Make the first file.)\n',
                                              [{'name': 'all', 'actions': []}, {'name': 'first', 'actions': ['shell']}])
    assert printed == ['a line the Snakefile printed']
    assert rules == [{'name': 'all', 'docstring': None, 'declared_actions': []},
                     {'name': 'first', 'docstring': 'Make the first file.', 'declared_actions': ['shell']}]
    listed = wms_adopt.roster(rules, jobs)
    assert listed['jobs_without_shell_command'] == ['all'] and [job['rule'] for job in listed['jobs']] == ['all', 'second', 'first']
    assert wms_adopt.parse_jobs('Building DAG of jobs...\nNothing to be done.\n') == ([], 0)


def test_an_inspection_whose_job_count_disagrees_fails(workflow, tmp_path):
    if REAL:
        pytest.skip('stand-in executable only')
    executable = Path(workflow['snakemake'])
    executable.write_text(executable.read_text().replace('total         3', 'total         4'))
    adopt(workflow)
    path = workflow['rundir'] / 'adoption.json'
    document = wms_adopt._inspect(path, json.loads(path.read_text()), run_folder(tmp_path, 'out'))
    assert document['status'] == 'failed' and document['problems'] == ['the dry run states 4 jobs and 3 were read']


# ----------------------------------------------------------------- registration and command line
def test_the_mode_is_registered_through_the_provider_seam():
    from ravel.validation import signature_conformance
    spec = {'mode': 'external-workflow', 'task': {}}
    assert science.PROVIDER_MODES == {'external-workflow': 'ravel.workflow.wms_adopt'}
    assert science.adapter(spec) is wms_adopt and science._new_capability(spec)
    assert science.applicability('external-workflow') == {'scope': 'general'}
    # The mode joins MODES and the static catalogue together with its descriptor; until then it is a provider mode.
    assert 'external-workflow' not in science.MODES
    with pytest.raises(ValueError, match='invalid science mode'):
        science.validate({**study(), 'schema_version': 2, 'max_attempts': 1, 'mode': 'unregistered-workflow', 'task': {}})
    assert [error for error in signature_conformance.conformance() if 'external-workflow' in error] == []
    with pytest.raises(ValueError, match='requires exactly'):
        wms_adopt.validate({'schema_version': 1, 'operation': 'run', 'adoption': 'adoption.json'})
    with pytest.raises(ValueError, match='inspect or run'):
        wms_adopt.validate({'schema_version': 1, 'operation': 'launch'})


def test_command_line_adopts_reports_status_and_keeps_other_operations_for_their_owner(workflow, capsys):
    from ravel import cli
    (workflow['base'] / 'study.json').write_text(json.dumps(study()))
    assert cli.main(['wms', 'adopt', '--snakefile', str(workflow['snakefile']), '--workdir', str(workflow['workdir']),
                     '--rundir', str(workflow['rundir']), '--study', str(workflow['base'] / 'study.json'),
                     '--snakemake', workflow['snakemake'], '--target', 'final.txt', '--output', 'final.txt']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed['snakefile_parsed'] is False and printed['commands']['jobs'][-2:] == ['--', 'final.txt']
    assert nothing_parsed(workflow)
    assert cli.main(['wms', 'adopt-status', '--adoption', str(workflow['rundir'])]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown['changed_files'] == [] and shown['inspection'] is None and shown['run_planned'] is False
    assert cli.main(['wms', 'adopt-run', '--adoption', str(workflow['rundir'])]) == 2
    assert 'no inspection yet' in capsys.readouterr().err
    try:
        import ravel.workflow.wms_launch  # noqa: F401
    except ImportError:
        assert cli.main(['wms', 'launch']) == 2
        assert 'unknown `ravel wms` operation' in capsys.readouterr().err


# Synthetic modules implement only the include interface used by these controls.
FAKE_SOURCECACHE = '''from pathlib import Path
class LocalSourceFile:
    def __init__(self, path): self.path = str(path)
    def get_path_or_uri(self): return self.path
    def get_basedir(self): return str(Path(self.path).parent)
def infer_source_file(value, basedir=None):
    if isinstance(value, LocalSourceFile): return value
    path = Path(value)
    return LocalSourceFile(path if path.is_absolute() else Path(basedir or Path.cwd()) / path)
'''
FAKE_WORKFLOW = '''from pathlib import Path
from .sourcecache import infer_source_file
class Workflow:
    def __init__(self): self.included_stack = []
    def include(self, snakefile, overwrite_default_target=False, print_compilation=False, basedir=None):
        if basedir is None and self.included_stack: basedir = self.included_stack[-1].get_basedir()
        source = infer_source_file(snakefile, basedir)
        self.included_stack.append(source)
        try:
            text = Path(source.get_path_or_uri()).read_text().split('\\ninclude:')[0].split('\\nrule ')[0]
            exec(compile(text, source.get_path_or_uri(), 'exec'), {'workflow': self})
        finally: self.included_stack.pop()
'''


def as_member(record, path):
    """Record `path` the way `--member` does: pinned and named as a workflow member."""
    record['files'].append({'role': 'member', **wms_adopt._pin(path), 'included_by': None, 'line': None})
    record['members'].append(str(path))


def include_fixture(tmp_path, text, folder='include-boundary', **members):
    """An executable fake manager with a real include entry point and a parse witness."""
    base = tmp_path.resolve() / folder
    (base / 'bin/snakemake').mkdir(parents=True)
    (base / 'work').mkdir()
    (base / 'bin/snakemake/__init__.py').write_text('')
    (base / 'bin/snakemake/sourcecache.py').write_text(FAKE_SOURCECACHE)
    (base / 'bin/snakemake/workflow.py').write_text(FAKE_WORKFLOW)
    (base / 'bin/snakemake/cli.py').write_text('')
    manager = base / 'bin/workflow-manager'
    manager.write_text(f'#!{sys.executable}\nimport sys\nfrom snakemake.workflow import Workflow\n'
                       'Workflow().include(sys.argv[sys.argv.index("--snakefile") + 1])\n')
    manager.chmod(0o755)
    source = base / 'Snakefile'
    source.write_text(text)
    for name, content in members.items():
        (base / name).write_text(content)
    record = {'snakefile': wms_adopt._pin(source), 'workdir': str(base / 'work'),
              'snakemake': [str(manager)], 'roots': [], 'outputs': [], 'targets': [], 'cores': 1,
              **wms_adopt.scan(source, base / 'work')}
    return base, record


@pytest.mark.parametrize('dry_run', [True, False])
def test_computed_include_outside_record_is_refused_before_parse(tmp_path, monkeypatch, dry_run):
    base, record = include_fixture(tmp_path, 'loader = workflow.include\nloader("computed-" + "member.smk")\n',
                                   **{'computed-member.smk': 'from pathlib import Path\nPath("member-parsed").touch()\n'})
    # Inert custody stands in for the separately tested science-worker authorization.
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None, raising=False)
    argv = wms_adopt.run_command(record)
    if dry_run:
        argv.append('--dry-run')
    code, _, streams = wms_adopt._call(record, argv, run_folder(base), 'manager')
    assert code != 0
    assert f"include refused: {base / 'computed-member.smk'} is outside the adoption record" in Path(
        streams['stderr']['path']).read_text()
    assert not (base / 'work/member-parsed').exists()


def test_changed_include_digest_is_refused_at_include_entry(tmp_path, monkeypatch):
    text = ('from pathlib import Path\n'
            'Path(workflow.included_stack[-1].get_basedir(), "member.smk").write_text('
            '"from pathlib import Path\\nPath(\\\"member-parsed\\\").touch()\\n")\n'
            'loader = workflow.include\nloader("member.smk")\n')
    base, record = include_fixture(tmp_path, text, **{'member.smk': '# approved member\n'})
    as_member(record, base / 'member.smk')
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None, raising=False)
    code, _, streams = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert code != 0
    assert f"include refused: {base / 'member.smk'} changed from its adoption digest" in Path(
        streams['stderr']['path']).read_text()
    assert not (base / 'work/member-parsed').exists()


def test_adopted_manager_call_refuses_without_supervised_custody(tmp_path):
    base, record = include_fixture(tmp_path, 'from pathlib import Path\nPath("root-parsed").touch()\n')
    with pytest.raises(ValueError, match='supervised'):
        wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert not (base / 'work/root-parsed').exists()


@pytest.mark.parametrize('withdrawn', ['worker', 'method', 'dispatch', 'record'])
@pytest.mark.parametrize('checks_passed', [0, 1, 2])
def test_each_manager_call_rechecks_custody_until_the_process_starts(tmp_path, monkeypatch, withdrawn, checks_passed):
    """The approved worker, the method admission, the dispatch grant and the record are read at every check."""
    from ravel.workflow import method_selection, wms_policy
    base, record = include_fixture(tmp_path, 'from pathlib import Path\nPath("root-parsed").touch()\n')
    adoption = base / 'adoption.json'
    adoption.write_text(json.dumps({'schema_version': 1, 'kind': 'workflow-adoption', **record}))
    record = json.loads(adoption.read_text())
    task, study, seen = {'adoption': str(adoption)}, base / 'study', []

    def check(name):
        def checked(*arguments):
            seen.append(name)
            if name == withdrawn and seen.count(name) > checks_passed:
                raise ValueError(f'{name} authority was withdrawn')
            return study
        return checked
    monkeypatch.setattr(wms_adopt, '_approved', check('worker'))
    monkeypatch.setattr(method_selection, 'require_launch', check('method'))
    monkeypatch.setattr(wms_policy, 'require_custody', check('dispatch'))
    read = wms_adopt._record
    def changing(*arguments):
        path, current = read(*arguments)
        seen.append('record')
        return path, ({**current, 'cores': 2} if withdrawn == 'record' and seen.count('record') > checks_passed else current)
    monkeypatch.setattr(wms_adopt, '_record', changing)
    token = wms_adopt._CUSTODY.set((task, base, study / 'outputs/attempt-1', wms_adopt._pin(adoption)))
    try:
        with pytest.raises(ValueError, match='withdrawn|adoption record changed before supervised launch'):
            wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
        assert not (base / 'work/root-parsed').exists()
        # With every authority in place the same call starts the manager, after three checks.
        withdrawn, seen[:] = None, []
        code, _, _ = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base, 'granted'), 'manager')
    finally:
        wms_adopt._CUSTODY.reset(token)
    assert code == 0 and (base / 'work/root-parsed').exists()
    assert seen == ['worker', 'method', 'dispatch', 'record'] * 3


def combined_entry(project, tmp_path, monkeypatch, name='adopted', adoptions=None):
    """Add one approved adoption study to the project; `adoptions` maps each run dir to its record."""
    base, record = include_fixture(tmp_path, '# synthetic workflow\n', folder=f'workflow-{name}')
    adoption = base / 'adoption.json'
    adoption.write_text(json.dumps({'schema_version': 1, 'kind': 'workflow-adoption', **record}))
    rd = project.run_dir(name)
    adoptions = {} if adoptions is None else adoptions
    adoptions[str(rd.resolve())] = adoption
    monkeypatch.setattr(science, 'execution_spec', lambda rundir, **k: (
        {'mode': 'external-workflow', 'task': {'operation': 'run', 'adoption': str(adoptions[str(Path(rundir).resolve())])}}
        if str(Path(rundir).resolve()) in adoptions else {'mode': 'quantities'}))
    entry = wms_launch.add(project, rd, task=name)
    return entry, adoption


@pytest.mark.parametrize('changed', ['adoption', 'manifest'])
def test_combined_launch_refuses_a_changed_record_pair(project, tmp_path, monkeypatch, changed):
    entry, adoption = combined_entry(project, tmp_path, monkeypatch)
    dispatched = []
    fake_manager(monkeypatch, lambda *a: (dispatched.append(a) or (0, 'synthetic manager\n')))
    def version(argv):
        path = adoption if changed == 'adoption' else Path(entry['export']['path'])
        path.write_bytes(path.read_bytes() + b'\n')
        return '9.27.0'
    monkeypatch.setattr(wms_launch.wms_runtime, 'snakemake_version', version)
    with pytest.raises(ValueError, match='(adoption|export|manifest).*?(changed|differs|digest)'):
        wms_launch.launch(project, 'adopted')
    assert dispatched == []


def test_combined_launch_binds_unchanged_pair_in_one_receipt(project, tmp_path, monkeypatch):
    entry, adoption = combined_entry(project, tmp_path, monkeypatch)
    dispatched = []
    def execute(argv, cwd):
        from ravel.workflow import wms_policy
        assert any(wms_policy._live(p) for p in (cwd / '.live').glob('launch-*.json'))
        dispatched.append(argv)
        return 0, 'synthetic manager\n'
    fake_manager(monkeypatch, execute)
    receipt = wms_launch.launch(project, 'adopted')
    assert len(dispatched) == 1
    assert receipt['workflow_bindings'] == [{'task': 'adopted', 'manifest': entry['export'],
                                              'adoption': wms_adopt._pin(adoption)}]


def test_combined_launch_rechecks_the_pair_at_dispatch(project, tmp_path, monkeypatch):
    entry, adoption = combined_entry(project, tmp_path, monkeypatch)
    dispatched = []
    fake_manager(monkeypatch, lambda *a: (dispatched.append(a) or (0, 'synthetic manager\n')))
    freeze = wms_launch._freeze_parse
    def freeze_then_edit(*arguments):
        # The record changes after the last check under the project lock, before the manager starts.
        frozen = freeze(*arguments)
        adoption.write_bytes(adoption.read_bytes() + b'\n')
        return frozen
    monkeypatch.setattr(wms_launch, '_freeze_parse', freeze_then_edit)
    with pytest.raises(ValueError, match='adoption record .* changed from its indexed digest'):
        wms_launch.launch(project, 'adopted')
    assert dispatched == []
    assert list((project / 'workflow/launches/adopted').glob('*.json')) == []


def test_an_adoption_outside_the_launch_does_not_refuse_another_task(project, tmp_path, monkeypatch):
    adoptions = {}
    earlier, record = combined_entry(project, tmp_path, monkeypatch, 'earlier', adoptions)
    later, _ = combined_entry(project, tmp_path, monkeypatch, 'later', adoptions)
    dispatched = []
    fake_manager(monkeypatch, lambda *a: (dispatched.append(a) or (0, 'synthetic manager\n')))
    # The earlier workflow was edited in place after its study, for example for a later adoption.
    source = Path(json.loads(record.read_text())['snakefile']['path'])
    source.write_text(source.read_text() + '# edited for a later adoption\n')
    receipt = wms_launch.launch(project, 'later')
    assert len(dispatched) == 1
    assert [row['task'] for row in receipt['workflow_bindings']] == ['later']
    # Its own launch, and a launch that depends on it, still refuse by name.
    with pytest.raises(ValueError, match=f'adopted workflow file {source} changed since adoption'):
        wms_launch.launch(project, 'earlier')
    assert len(dispatched) == 1


def test_a_changed_adoption_of_a_dependency_refuses_the_launch(project, tmp_path, monkeypatch):
    adoptions = {}
    _, record = combined_entry(project, tmp_path, monkeypatch, 'earlier', adoptions)
    base, later = include_fixture(tmp_path, '# synthetic workflow\n', folder='workflow-later')
    adoption = base / 'adoption.json'
    adoption.write_text(json.dumps({'schema_version': 1, 'kind': 'workflow-adoption', **later}))
    rd = project.run_dir('later')
    adoptions[str(rd.resolve())] = adoption
    wms_launch.add(project, rd, after=['earlier'], task='later')
    dispatched = []
    fake_manager(monkeypatch, lambda *a: (dispatched.append(a) or (0, 'synthetic manager\n')))
    receipt = wms_launch.launch(project, 'later')
    assert sorted(row['task'] for row in receipt['workflow_bindings']) == ['earlier', 'later']
    source = Path(json.loads(record.read_text())['snakefile']['path'])
    source.write_text(source.read_text() + '# edited after the study was added\n')
    with pytest.raises(ValueError, match=f'adopted workflow file {source} changed since adoption'):
        wms_launch.launch(project, 'later')
    assert len(dispatched) == 1


def test_real_computed_include_is_refused(tmp_path, monkeypatch):
    manager = os.environ.get('RAVEL_TEST_SNAKEMAKE')
    if not manager:
        pytest.skip('set RAVEL_TEST_SNAKEMAKE to run the real computed-include refusal')
    base = tmp_path.resolve()
    source = base / 'Snakefile'
    source.write_text('loader = workflow.include\nloader("computed-" + "member.smk")\n'
                      'rule all:\n    input: []\n')
    member = base / 'computed-member.smk'
    member.write_text('from pathlib import Path\nPath("member-parsed").touch()\n')
    record = {'snakefile': wms_adopt._pin(source), 'workdir': str(base), 'snakemake': [manager],
              'roots': [], 'outputs': [], 'targets': [], 'cores': 1, **wms_adopt.scan(source, base)}
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None, raising=False)
    code, _, streams = wms_adopt._call(record, wms_adopt.inspection_commands(record)['rules'],
                                      run_folder(base), 'real-manager')
    assert code != 0
    # The refusal names the computed member: a refusal of the Snakefile itself would not pass.
    assert f'include refused: {member} is outside the adoption record' in Path(streams['stderr']['path']).read_text()
    assert not (base / 'member-parsed').exists()


def test_real_include_control_skips_naming_its_gate(tmp_path, monkeypatch):
    monkeypatch.delenv('RAVEL_TEST_SNAKEMAKE', raising=False)
    with pytest.raises(pytest.skip.Exception, match='RAVEL_TEST_SNAKEMAKE'):
        test_real_computed_include_is_refused(tmp_path, monkeypatch)


@pytest.mark.parametrize('linked', [False, True])
def test_recorded_computed_include_loads_the_canonical_member(tmp_path, monkeypatch, linked):
    base, record = include_fixture(tmp_path, 'loader = workflow.include\nloader("computed-" + "member.smk")\n',
                                   **{'member.smk': 'from pathlib import Path\nPath("member-parsed").touch()\n'})
    target = base / 'computed-member.smk'
    if linked:
        target.symlink_to(base / 'member.smk')
    else:
        target.write_bytes((base / 'member.smk').read_bytes())
    as_member(record, target.resolve())
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    code, _, _ = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert code == 0 and (base / 'work/member-parsed').exists()
    snapshot = base / 'run-out/manager.include-record.json'
    assert json.loads(snapshot.read_text()) == record
    assert snapshot.stat().st_mode & 0o222 == 0


def test_site_shim_uses_declared_interpreter_and_clears_python_overrides(tmp_path, monkeypatch):
    from ravel.workflow import site_contract
    base, record = include_fixture(tmp_path, '# synthetic workflow\n')
    manager = Path(record['snakemake'][0])
    manager.write_text(manager.read_text() + '\nimport json, os\nprint(json.dumps({key: os.environ.get(key) '
                       'for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "PYTHONSTARTUP", '
                       '"PYTHONNOUSERSITE", "SNAKEMAKE_PROFILE")}))\n')
    shim = base / 'bin/ravel-snakemake'
    shim.write_text('#!/bin/sh\nexit 41\n')
    shim.chmod(0o755)
    record['snakemake'] = [str(shim)]
    # The shim's own prefix holds its record: a prefix named by the environment is not consulted.
    monkeypatch.setenv('RAVEL_SITE_PREFIX', str(base / 'another-prefix'))
    monkeypatch.setenv('PYTHONPATH', str(base / 'unreviewed-imports'))
    monkeypatch.setenv('PYTHONHOME', str(base / 'unreviewed-home'))
    monkeypatch.setenv('PYTHONUSERBASE', str(base / 'unreviewed-user-site'))
    monkeypatch.setenv('PYTHONSTARTUP', str(base / 'unreviewed-startup'))
    monkeypatch.setenv('SNAKEMAKE_PROFILE', str(base / 'unreviewed-profile'))
    def read_wms_record(prefix):
        if Path(prefix) != base:
            raise ValueError('WMS installation record missing or invalid')
        return {'shim': str(shim), 'snakemake': str(manager)}
    monkeypatch.setattr(site_contract, 'read_wms_record', read_wms_record)
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    code, text, _ = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert code == 0
    # The supplied import path never arrives. The one entry is this call's own folder, which holds
    # only the include check that interpreters started by the manager run first.
    hook = base / 'run-out/manager.include-hook'
    assert json.loads(text) == {'PYTHONPATH': str(hook), 'PYTHONHOME': None, 'PYTHONUSERBASE': None,
                                'PYTHONSTARTUP': None, 'PYTHONNOUSERSITE': '1', 'SNAKEMAKE_PROFILE': None}
    assert [path.name for path in hook.iterdir()] == ['sitecustomize.py']
    assert (hook / 'sitecustomize.py').read_bytes() == Path(wms_adopt.__file__).with_name('wms_include.py').read_bytes()


def test_the_bootstrap_keeps_ravel_modules_off_the_manager_import_path(tmp_path, monkeypatch):
    base, record = include_fixture(tmp_path, '# synthetic workflow\n')
    manager = Path(record['snakemake'][0])
    manager.write_text(manager.read_text() + 'import importlib.util, json\n'
                       'print(json.dumps({"path": sys.path, "found": [name for name in ("wms_adopt", "science", '
                       '"execution") if importlib.util.find_spec(name)]}))\n')
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    code, text, _ = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert code == 0
    seen = json.loads(text)
    # The manager's own folder leads, as for a console entry; the folder of RAVEL's modules is absent.
    assert seen['path'][0] == str(manager.parent) and seen['found'] == []
    assert str(Path(wms_adopt.__file__).parent) not in [os.path.realpath(entry) for entry in seen['path'] if entry]


def test_a_manager_without_a_python_entry_is_refused_by_that_reason(tmp_path, monkeypatch):
    base, record = include_fixture(tmp_path, 'from pathlib import Path\nPath("root-parsed").touch()\n')
    manager = Path(record['snakemake'][0])
    manager.write_text('#!/bin/sh\nexit 41\n')
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    with pytest.raises(ValueError, match=f'adopted manager {manager} must name its Python interpreter by absolute path'):
        wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert not (base / 'work/root-parsed').exists()


# ----------------------------------------------------------------- manager interpreters started for jobs
# The entry of `python -m snakemake`: a fresh manager interpreter parses the workflow again.
FAKE_MAIN = '''import os, sys
from snakemake.workflow import Workflow
os.chdir(sys.argv[sys.argv.index("--directory") + 1])
Workflow().include(sys.argv[sys.argv.index("--snakefile") + 1])
'''
# A manager that runs one job in a fresh interpreter of its own, the way a Python job is run.
SPAWNS_A_JOB = '''import subprocess
from pathlib import Path
if GENERATES:
    # An earlier job of the same run wrote a workflow member that no adoption recorded.
    Path(sys.argv[sys.argv.index("--snakefile") + 1]).with_name("generated.smk").write_text(
        'from pathlib import Path\\nPath("member-parsed").touch()\\n')
raise SystemExit(subprocess.run([sys.executable, "-m", "snakemake", *sys.argv[1:]],
                                cwd=Path(__file__).parent).returncode)
'''
REPARSED = ('from pathlib import Path\n'
            'with open("parses.txt", "a") as stream:\n    stream.write("parsed\\n")\n'
            'loader = workflow.include\n'
            'if Path(workflow.included_stack[-1].get_basedir(), "generated.smk").exists():\n'
            '    loader("generated.smk")\n')


@pytest.mark.parametrize('generates', [True, False])
def test_a_manager_interpreter_started_for_a_job_checks_each_include_before_parse(tmp_path, monkeypatch, generates):
    base, record = include_fixture(tmp_path, REPARSED)
    manager = Path(record['snakemake'][0])
    (manager.parent / 'snakemake/__main__.py').write_text(FAKE_MAIN)
    manager.write_text(manager.read_text() + f'GENERATES = {generates}\n' + SPAWNS_A_JOB)
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    code, _, streams = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    # Both interpreters parsed the adopted Snakefile; only the second met the unrecorded member.
    assert (base / 'work/parses.txt').read_text() == 'parsed\nparsed\n'
    if generates:
        assert code != 0
        assert f"include refused: {base / 'generated.smk'} is outside the adoption record" in Path(
            streams['stderr']['path']).read_text()
        assert not (base / 'work/member-parsed').exists()
    else:
        assert code == 0, streams


def test_a_manager_interpreter_that_lost_its_adoption_record_parses_nothing(tmp_path, monkeypatch):
    base, record = include_fixture(tmp_path, REPARSED)
    manager = Path(record['snakemake'][0])
    (manager.parent / 'snakemake/__main__.py').write_text(FAKE_MAIN)
    # The record this call checks against is edited after the first interpreter read it.
    manager.write_text(manager.read_text() + 'import os\nos.chmod(os.environ["RAVEL_ADOPTION_RECORD"], 0o644)\n'
                       'open(os.environ["RAVEL_ADOPTION_RECORD"], "a").write("\\n")\nGENERATES = False\n' + SPAWNS_A_JOB)
    monkeypatch.setattr(wms_adopt, 'require_launch_custody', lambda record: None)
    code, _, streams = wms_adopt._call(record, wms_adopt.run_command(record), run_folder(base), 'manager')
    assert code != 0 and 'include refused: interpreter adoption record changed' in Path(streams['stderr']['path']).read_text()
    assert (base / 'work/parses.txt').read_text() == 'parsed\n'


def test_the_include_check_runs_the_site_customization_it_shadows(tmp_path):
    import shutil
    import subprocess
    hook, other = tmp_path / 'hook', tmp_path / 'site'
    hook.mkdir()
    other.mkdir()
    shutil.copyfile(Path(wms_adopt.__file__).with_name('wms_include.py'), hook / 'sitecustomize.py')
    (other / 'sitecustomize.py').write_text('import sys\nsys.customized_by_the_environment = True\n')
    done = subprocess.run([sys.executable, '-c', 'import sys; print(sys.customized_by_the_environment)'],
                          env={'PYTHONPATH': f'{hook}{os.pathsep}{other}'}, capture_output=True, text=True)
    assert done.stdout.strip() == 'True', done.stderr


# ----------------------------------------------------------------- members loaded through computed includes
MEMBER = ('from pathlib import Path\nPath("member-parsed").touch()\n\n'
          'rule extra_selected:\n    output: "extra.txt"\n    shell: "echo selected > {output}"\n\n'
          'rule extra_unselected:\n    output: "unselected.txt"\n    shell:\n        "echo unselected > {output}"\n')


def loads_through_an_alias(workflow, member):
    """The Snakefile loads `member` through an alias, which the text scan does not read as an include."""
    member.parent.mkdir(parents=True, exist_ok=True)
    member.write_text(MEMBER)
    workflow['snakefile'].write_text(SNAKEFILE.replace(
        'include: "rules/second.smk"', f'loader = workflow.include\nloader({str(member)!r})\ninclude: "rules/second.smk"'))


def inspect_directly(workflow, tmp_path, **options):
    """Adoption and the inspection calls through the adapter's own steps; the inspection may fail."""
    if REAL:
        pytest.skip('stand-in executable only')
    adopt(workflow, **options)
    path = workflow['rundir'] / 'adoption.json'
    folder = run_folder(tmp_path, 'inspect-out')
    return wms_adopt._inspect(path, json.loads(path.read_text()), folder), folder


def test_a_pinned_file_outside_the_allowed_roots_is_refused_at_include_entry(workflow, tmp_path):
    member = tmp_path.resolve() / 'outside/member.smk'
    loads_through_an_alias(workflow, member)
    inspection, folder = inspect_directly(workflow, tmp_path, pins=[member])
    assert inspection['status'] == 'failed'
    assert f'include refused: {member} is outside the allowed roots' in (folder / 'rules.stderr.txt').read_text()
    assert not (workflow['workdir'] / 'member-parsed').exists()


def test_a_member_outside_the_allowed_roots_needs_its_root_named(workflow, tmp_path):
    member = tmp_path.resolve() / 'outside/member.smk'
    loads_through_an_alias(workflow, member)
    with pytest.raises(ValueError, match=f'workflow member {member} is outside the allowed roots') as refusal:
        adopt(workflow, members=[member])
    assert 'nothing was parsed' in str(refusal.value) and not workflow['rundir'].exists()
    inspection, _ = inspect_directly(workflow, tmp_path, members=[member], roots=[member.parent])
    assert inspection['status'] == 'passed', inspection['problems']
    assert (workflow['workdir'] / 'member-parsed').exists()


def test_a_pinned_file_that_is_no_workflow_member_is_refused_at_include_entry(workflow, tmp_path):
    member = workflow['base'] / 'wf/rules/member.smk'
    loads_through_an_alias(workflow, member)
    inspection, folder = inspect_directly(workflow, tmp_path, pins=[member])
    # The pin alone shows none of the file's rules, so the file is not loaded as workflow source.
    shown = json.loads((workflow['rundir'] / 'inspect/inputs/checkin1.json').read_text())['sections']['i-b']['task']
    assert 'extra_unselected' not in [row['name'] for row in shown['rules']]
    assert inspection['status'] == 'failed'
    assert (f'include refused: {member} is pinned, but it was not adopted as a workflow member'
            in (folder / 'rules.stderr.txt').read_text())
    assert not (workflow['workdir'] / 'member-parsed').exists()


def test_a_workflow_member_is_scanned_and_its_rules_are_in_the_first_checkin(workflow, tmp_path):
    member = workflow['base'] / 'wf/rules/member.smk'
    loads_through_an_alias(workflow, member)
    (member.parent / 'deeper.smk').write_text('rule deepest:\n    output: "deep.txt"\n    shell: "echo deep > {output}"\n')
    member.write_text(MEMBER + 'include: "deeper.smk"\n')
    inspection, _ = inspect_directly(workflow, tmp_path, members=[member])
    record = json.loads((workflow['rundir'] / 'adoption.json').read_text())
    assert record['members'] == [str(member)]
    assert [(row['role'], Path(row['path']).name) for row in record['files']] == [
        ('snakefile', 'Snakefile'), ('member', 'member.smk'), ('include', 'second.smk'), ('include', 'deeper.smk')]
    # The first CHECK-IN shows the member's rules, selected or not, and those of the file it includes.
    shown = json.loads((workflow['rundir'] / 'inspect/inputs/checkin1.json').read_text())['sections']['i-b']['task']
    rules = {row['name']: row for row in shown['rules']}
    assert list(rules) == ['all', 'first', 'extra_selected', 'extra_unselected', 'second', 'deepest']
    assert rules['extra_unselected'] == {
        'name': 'extra_unselected', 'file': str(member), 'line': 8, 'actions': ['shell'],
        'source': 'rule extra_unselected:\n    output: "unselected.txt"\n    shell:\n        "echo unselected > {output}"\n'}
    assert rules['extra_selected']['source'].endswith('    shell: "echo selected > {output}"\n')
    assert inspection['status'] == 'passed', inspection['problems']
    assert (workflow['workdir'] / 'member-parsed').exists()
    # A member is pinned like every adopted file: a change after adoption refuses by name.
    member.write_text(MEMBER)
    with pytest.raises(ValueError, match=f'adopted workflow file {member} changed since adoption'):
        wms_adopt.check_pins(record)


# ----------------------------------------------------------------- the interpreter of the manager's console entry
def first_line(workflow, line):
    """Replace the first line of the stand-in console entry; `None` leaves the entry without one."""
    executable = Path(workflow['snakemake'])
    body = executable.read_text()
    body = body.split('\n', 1)[1] if body.startswith('#!') else body
    executable.write_text(('' if line is None else line + '\n') + body)


def on_search_path(tmp_path, monkeypatch, name='python3'):
    """An interpreter that only the search path names: a launcher of this Python in a folder of its own."""
    folder = tmp_path.resolve() / 'search-path'
    folder.mkdir()
    (folder / name).write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n')
    (folder / name).chmod(0o755)
    monkeypatch.setenv('PATH', f"{folder}{os.pathsep}{os.environ['PATH']}")
    return str(folder / name)


@pytest.mark.parametrize('line', ['#!/usr/bin/env python3', '#!/usr/bin/env -S python3 -B'])
def test_a_console_entry_that_finds_its_interpreter_through_env_is_inspected(workflow, tmp_path, monkeypatch, line):
    python = on_search_path(tmp_path, monkeypatch)
    first_line(workflow, line)
    path, record, inspection = internal(workflow, tmp_path)
    assert record['interpreter'] == {'python': [python, *line.split()[3:]], 'entry': workflow['snakemake']}
    assert inspection['snakemake']['version'] == '9.27.0' and (workflow['workdir'] / WITNESS).exists()
    # The run starts the interpreter found at adoption, whatever the search path holds by then.
    monkeypatch.setenv('PATH', str(tmp_path / 'another-search-path'))
    command = wms_adopt.interpreter_command(record, wms_adopt.run_command(record), run_folder(tmp_path), 'bound')
    assert command[:len(record['interpreter']['python'])] == record['interpreter']['python']
    receipt = wms_adopt._run(path, record, inspection, run_folder(tmp_path, 'bound-run'))
    assert receipt['status'] == 'passed' and receipt['snakemake']['version'] == '9.27.0'


def test_an_interpreter_named_at_adoption_runs_a_console_entry_that_names_none(workflow, tmp_path):
    for line in (None, '#!/usr/bin/env interpreter-that-no-search-path-holds', '#!/bin/sh'):
        first_line(workflow, line)
        with pytest.raises(ValueError, match='must name its Python interpreter by absolute path'):
            adopt(workflow)
        assert not workflow['rundir'].exists() and nothing_parsed(workflow)
    with pytest.raises(ValueError, match='absent-python is not an executable file'):
        adopt(workflow, interpreter=str(workflow['base'] / 'absent-python'))
    first_line(workflow, None)
    path, record, inspection = internal(workflow, tmp_path, interpreter=sys.executable)
    assert record['interpreter'] == {'python': [sys.executable], 'entry': workflow['snakemake']}
    assert inspection['snakemake']['version'] == '9.27.0' and (workflow['workdir'] / WITNESS).exists()
