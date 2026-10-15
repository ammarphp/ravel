"""Workflow-manager-first launch: each approved stage becomes a Snakemake rule before it runs.

`init` lays out <project>/workflow/ with a stable Snakefile, policy.json and an empty
index.json. `add` refuses an unapproved run dir; for an approved one it writes a
one-task site-workflow export under exports/<task>/ and its rule as rules/<task>.smk,
then records the task in index.json. The rule exists before anything runs, so an
aborted or failed run still leaves a re-executable rule. `launch` runs the task through
Snakemake, which calls `site_workflow run-step`, and writes a launch receipt that
records delivery only. Snakemake never approves; ordinary approval stays required.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from ravel.physics import root_stream, root_stream_core as core
from . import method_selection, site_workflow, wms_policy, wms_runtime
from .state_io import atomic_json, file_lock

AUDIT_LISTS = ('prompts', 'tracked_skill_sources')
AUDIT_FILES = ('token_accounting', 'environment')
WMS = {'engine': 'snakemake', 'version': '9.27.0', 'cores': 1, 'retries': 0}
TASK_ID = '[A-Za-z][A-Za-z0-9_]{0,63}'
PROFILE_VARIABLE = 'SNAKEMAKE_PROFILE'

SNAKEFILE = b"""# Owned by ravel wms init; ordinary RAVEL retains all authority.
# Stable: tasks come from index.json and their rules from rules/<task>.smk (written by
# ravel wms add). Parse time only reads index.json; nothing else runs.
import json as _ravel_json

with open(workflow.basedir + '/index.json') as _ravel_index:
    _RAVEL_TASKS = sorted(row['id'] for row in _ravel_json.load(_ravel_index)['tasks'])

rule all:
    input: ['exports/' + task + '/completed/' + task + '.json' for task in _RAVEL_TASKS]

for _ravel_task in _RAVEL_TASKS:
    include: 'rules/' + _ravel_task + '.smk'
"""


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _project(project):
    return Path(project).expanduser().absolute().resolve()


def _workflow(project):
    wf = _project(project) / 'workflow'
    core.require((wf / 'project.json').is_file(), f'no workflow-manager project at {wf}; run `ravel wms init` first')
    return wf


def _read(path):
    return json.loads(Path(path).read_bytes())


def _file(value, base, label):
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else base / path).absolute()
    core.require(path.is_file(), f'{label} record {path} is not a regular file')
    return str(path)


def _audit(audit, base):
    """Validate the audit block of plain paths; records are frozen per task at add."""
    core.keys(audit, ('prompts', 'model_build', 'timestamps', 'token_accounting', 'environment',
                      'tracked_skill_sources', 'blinding_policy'), 'project audit block')
    core.text(audit['model_build'], 'model build')
    core.require(type(audit['timestamps']) is list and all(type(x) is str for x in audit['timestamps']), 'timestamp list required')
    value = {'model_build': audit['model_build'], 'timestamps': list(audit['timestamps'])}
    for name in AUDIT_LISTS:
        core.require(type(audit[name]) is list and audit[name], f'nonempty {name} list required')
        value[name] = [_file(x, base, name) for x in audit[name]]
    for name in (*AUDIT_FILES, 'blinding_policy'):
        value[name] = _file(audit[name], base, name)
    return value


def init(project, profile='local', *, audit, python=None, site_id='local'):
    """Lay out a project workflow and require the workflow manager for its runs."""
    core.require(profile == 'local', 'only the local profile is supported (cores 1, retries 0)')
    root = _project(project)
    core.require(root.is_dir(), f'project directory {root} must exist')
    wf = root / 'workflow'
    wf.mkdir(exist_ok=True)
    with file_lock(wf / '.wms.lock', blocking=False):
        config = {'schema_version': 1, 'profile': profile, 'site_id': core.text(site_id, 'site id'),
                  'python': _file(python or os.path.realpath(sys.executable), root, 'python'),
                  'audit': _audit(audit, root), 'wms': dict(WMS)}
        if (wf / 'project.json').exists():
            core.require(_read(wf / 'project.json') == config, 'project workflow already initialized differently; preserve it')
        if (wf / 'policy.json').exists():
            wms_policy.validate(_read(wf / 'policy.json'))
        else:
            atomic_json(wf / 'policy.json', {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake'})
        if (wf / 'Snakefile').exists():
            core.require((wf / 'Snakefile').read_bytes() == SNAKEFILE, 'existing project Snakefile differs from the stable generated one')
        else:
            with (wf / 'Snakefile').open('xb') as stream:
                stream.write(SNAKEFILE)
        if not (wf / 'index.json').exists():
            atomic_json(wf / 'index.json', {'schema_version': 1, 'tasks': []})
        for name in ('rules', 'exports', 'launches', 'audit', 'requests'):
            (wf / name).mkdir(exist_ok=True)
        if not (wf / 'project.json').exists():
            atomic_json(wf / 'project.json', config)
    return {'workflow': str(wf), 'policy': site_workflow._pin(wf / 'policy.json'),
            'snakefile': site_workflow._pin(wf / 'Snakefile'), 'execution_authorized': False}


def _freeze(audit, folder):
    """Copy the growing audit records as of add; the export pins the copies.

    The final submission binds the final logs. The blinding policy keeps its
    original pin and is validated by the export exactly as before.
    """
    folder.mkdir(parents=True)
    def copy(source, role, number):
        target = folder / f'{role}-{number}-{Path(source).name}'
        shutil.copyfile(source, target)
        return site_workflow._pin(target)
    frozen = {'model_build': audit['model_build'], 'timestamps': [*audit['timestamps'], _utc().replace('+00:00', 'Z')],
              'blinding_policy': site_workflow._pin(audit['blinding_policy'])}
    for name in AUDIT_LISTS:
        frozen[name] = [copy(x, name, i) for i, x in enumerate(audit[name])]
    for name in AUDIT_FILES:
        frozen[name] = copy(audit[name], name, 0)
    return frozen


def _approved(rd):
    from . import science
    try:
        return science.verify_plan(rd, approved=True)
    except (ValueError, OSError, KeyError) as exc:
        raise ValueError(f'run dir {rd} has no current approved plan ({exc}); approve it with '
                         f'`ravel approve --rundir {rd}`; the workflow manager never approves') from exc


def add(project, rundir, after=(), *, task=None):
    """Emit the rule for one approved run dir before anything runs it."""
    from . import science
    wf = _workflow(project)
    config = _read(wf / 'project.json')
    rd = science.root(rundir)
    core.require(wf.parent in rd.parents, f'run dir {rd} must be inside the project {wf.parent} so its policy governs direct dispatch')
    with file_lock(wf / '.wms.lock', blocking=False):
        index = _read(wf / 'index.json')
        identity = task or re.sub('[^A-Za-z0-9_]', '_', rd.name)
        identity = identity if re.match('[A-Za-z]', identity) else 't_' + identity
        core.require(re.fullmatch(TASK_ID, identity) is not None and identity not in site_workflow.RESERVED_TASK_IDS,
                     f'task id {identity!r} must match {TASK_ID} and not be a reserved Snakemake name')
        known = {row['id']: row for row in index['tasks']}
        core.require(identity not in known, f'task id {identity} is already in the index; add a fresh approved attempt under a new task id')
        core.require(str(rd) not in {row['rundir'] for row in index['tasks']}, f'run dir {rd} is already a task; one run dir is dispatched once')
        after = list(after)
        core.require(len(set(after)) == len(after), 'distinct --after tasks required')
        leftovers = [str(p) for p in (wf / 'audit' / identity, wf / 'requests' / f'{identity}.json', wf / 'exports' / identity,
                                      wf / 'rules' / f'{identity}.smk') if p.exists()]
        core.require(not leftovers, f'an earlier add of task {identity} stopped part-way; preserve or move {", ".join(leftovers)} or use a new task id')
        missing = [x for x in after if x not in known]
        core.require(not missing, f'--after names tasks that are not in the index: {", ".join(missing)}')
        plan = _approved(rd)
        binding = plan.get('research_binding')
        owner = ({'kind': 'research_cycle', 'cycle': binding['root'], 'experiment': binding['experiment_id']}
                 if binding is not None else {'kind': 'ordinary'})
        request = {'schema_version': 1, 'site_id': config['site_id'], 'python': site_workflow._pin(config['python']),
                   'tasks': [{'id': identity, 'rundir': str(rd), 'plan': site_workflow._pin(rd / science.PLAN), 'owner': owner,
                              'depends_on': [], 'after': [{'task': x, 'export': known[x]['export']['path'],
                                                           'export_sha256': known[x]['export']['sha256']} for x in after]}],
                   'audit': _freeze(config['audit'], wf / 'audit' / identity), 'wms': dict(config['wms'])}
        root_stream.write_new(wf / 'requests' / f'{identity}.json', request)
        exported = site_workflow.export(request, wf, wf / 'exports' / identity)
        document = site_workflow.verify(exported['manifest']['path'], exported['manifest']['sha256'])
        raw = site_workflow.project_rule(exported['manifest']['path'], document, wf)
        with (wf / 'rules' / f'{identity}.smk').open('xb') as stream:
            stream.write(raw)
        entry = {'id': identity, 'rundir': str(rd), 'owner': owner, 'after': after, 'export': exported['manifest'],
                 'rule': site_workflow._pin(wf / 'rules' / f'{identity}.smk'),
                 'policy': _policy_pin(wf),
                 'added_utc': _utc(), 'execution_authorized': False}
        from . import wms_adopt
        binding = wms_adopt.export_binding(rd, plan, entry['export'])
        if binding is not None:
            entry['workflow_binding'] = binding
        index['tasks'].append(entry)
        atomic_json(wf / 'index.json', index)
    return entry


def _entry(wf, task):
    entry = next((row for row in _read(wf / 'index.json')['tasks'] if row['id'] == task), None)
    core.require(entry is not None, f'task {task} is not in the index; add it with `ravel wms add` first')
    return entry


def _closure(index, task):
    """Export digest of the task and of every task it depends on: what one launch may run."""
    rows = {row['id']: row for row in index['tasks']}
    exports, pending = {}, [task]
    while pending:
        row = rows[pending.pop()]
        if row['id'] not in exports:
            exports[row['id']] = row['export']['sha256']
            pending.extend(row['after'])
    return exports


def _execute(argv, cwd):
    # Snakemake turns every key of the profile named in this variable into an option no receipt shows.
    environment = {name: value for name, value in os.environ.items() if name != PROFILE_VARIABLE}
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=environment)
    return done.returncode, done.stdout + done.stderr


def _parse_inputs(wf, task):
    """The index entry of the task and the verified bytes Snakemake parses, each file read once."""
    index_raw = (wf / 'index.json').read_bytes()
    index = json.loads(index_raw)
    entry = next((row for row in index['tasks'] if row['id'] == task), None)
    core.require(entry is not None, f'task {task} is not in the index; add it with `ravel wms add` first')
    pinned = entry['policy']
    core.require(_policy_pin(wf) == pinned,
                 f'workflow policy changed since task {task} was added; '
                 + ('remove workflow/policy.json again' if pinned is None else
                    f"restore workflow/policy.json to the pinned content (sha256 {pinned['sha256']})")
                 + f' or acknowledge the change with `ravel wms revalidate --project {wf.parent} --task {task}`')
    core.require((wf / 'Snakefile').is_file() and (wf / 'Snakefile').read_bytes() == SNAKEFILE,
                 'project Snakefile differs from the stable generated one')
    from . import wms_adopt
    # Only the task and the tasks it depends on can run in this launch. An adoption outside them is
    # not read, so a workflow edited after its own study does not refuse the other tasks of the project.
    bound = _closure(index, task)
    rules = {}
    for row in index['tasks']:
        if row['id'] in bound:
            wms_adopt.check_launch_binding(row)
        rule, recorded = wf / 'rules' / f"{row['id']}.smk", row.get('rule')
        raw = rule.read_bytes() if rule.is_file() else None
        core.require(raw is not None and type(recorded) is dict and recorded.get('path') == str(rule)
                     and recorded.get('sha256') == hashlib.sha256(raw).hexdigest() and recorded.get('size') == len(raw),
                     f"workflow rule for task {row['id']} is missing or changed since add")
        rules[row['id']] = raw
    return entry, index_raw, rules


def launch_adopted(record, argv, folder, name, stdout, stderr, outputs=()):
    """Adoption hook: only the approved supervised worker starts this interpreter."""
    from . import wms_adopt
    wms_adopt.require_launch_custody(record)
    command = wms_adopt.interpreter_command(record, argv, folder, name)
    removed = {PROFILE_VARIABLE, 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUSERBASE', 'PYTHONSTARTUP'}
    environment = {key: value for key, value in os.environ.items() if key not in removed}
    environment['PYTHONNOUSERSITE'] = '1'
    wms_adopt.require_launch_custody(record)
    wms_adopt.check_pins(record)
    outside = wms_adopt._outside(Path(record['workdir']), outputs)
    core.require(not outside, 'output ' + ', '.join(outside) + ' is outside the working directory')
    return subprocess.run(command, cwd=record['workdir'], stdin=subprocess.DEVNULL,
                          stdout=stdout, stderr=stderr, env=environment).returncode


def _policy_pin(wf):
    policy = wf / 'policy.json'
    return site_workflow._pin(policy) if policy.is_file() else None


def revalidate(project, task):
    """Acknowledge a policy change for one indexed task, so its launch is not stranded.

    The run stays governed through its index entry whatever the policy now says.
    This re-pins the current policy for the task after checking that every
    governance file is well formed, the plan is still approved and the export and
    rule are unchanged. It approves nothing and runs nothing.
    """
    wf = _workflow(project)
    with file_lock(wf / '.wms.lock', blocking=False):
        index = _read(wf / 'index.json')
        entry = next((row for row in index['tasks'] if row['id'] == task), None)
        core.require(entry is not None, f'task {task} is not in the index; add it with `ravel wms add` first')
        previous, current = entry['policy'], _policy_pin(wf)
        core.require(current != previous, f'workflow policy of task {task} is unchanged; nothing to revalidate')
        core.require(wms_policy.required(entry['rundir']), f"run dir {entry['rundir']} is no longer governed")
        rule = wf / 'rules' / f'{task}.smk'
        core.require(rule.is_file() and site_workflow._pin(rule) == entry['rule'],
                     f'workflow rule for task {task} is missing or changed since add')
        _approved(Path(entry['rundir']))
        site_workflow.verify(entry['export']['path'], entry['export']['sha256'])
        entry['policy'] = current
        entry.setdefault('policy_revalidations', []).append({'utc': _utc(), 'previous': previous, 'current': current})
        atomic_json(wf / 'index.json', index)
    return entry


def _freeze_parse(folder, index_raw, rules):
    """Write the verified parse inputs as read-only copies; Snakemake parses these, not the project files."""
    (folder / 'rules').mkdir(parents=True)

    def write(path, raw):
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o444)
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}
    return {'snakefile': write(folder / 'Snakefile', SNAKEFILE), 'index': write(folder / 'index.json', index_raw),
            'rules': [write(folder / 'rules' / f'{name}.smk', raw) for name, raw in sorted(rules.items())]}


def launch(project, task, cores=1):
    """Run one indexed task (and any unfinished --after tasks) through Snakemake.

    The Snakefile, the index and every indexed rule are verified and copied under
    the project lock into launches/<task>/<n>.parse/. Snakemake parses those
    copies, so a later edit or a concurrent add cannot change what this launch
    parses, and the receipt pins them. A profiles folder in the workflow refuses
    and SNAKEMAKE_PROFILE never reaches Snakemake: a profile is an unpinned
    source of command-line options.
    """
    core.require(cores == 1, 'the local profile runs one core with no retries')
    wf = _workflow(project)
    core.require(not os.path.lexists(wf / 'profiles'),
                 f'{wf / "profiles"} would be loaded by Snakemake as a workflow profile that no pin covers; a profile '
                 'rewrites the launch (dry run, executor, submit command): move it out of the project workflow')
    entry, _, _ = _parse_inputs(wf, task)
    # A run dir that lost its method decision is refused by name, before its plan is read or Snakemake starts.
    method_selection.require_launch(entry['rundir'])
    site_workflow.verify(entry['export']['path'], entry['export']['sha256'])
    snakemake = wms_runtime.snakemake_argv()
    core.require(snakemake, 'no Snakemake executable found; set RAVEL_SNAKEMAKE or install the site WMS environment')
    version = wms_runtime.snakemake_version(snakemake)  # read before the stage, so nothing can fail on it afterwards
    target = f'exports/{task}/completed/{task}.json'
    folder = wf / 'launches' / task
    with file_lock(wf / '.wms.lock'):
        # The binding read: these bytes are checked and frozen while no add can run.
        current, index_raw, rules = _parse_inputs(wf, task)
        core.require(current['export'] == entry['export'], f'index entry of task {task} changed during launch')
        folder.mkdir(parents=True, exist_ok=True)
        number = max((int(p.stem) for p in folder.iterdir()
                      if p.suffix in ('.log', '.json') and p.stem.isdecimal()), default=0) + 1
        log_stream = (folder / f'{number:06d}.log').open('x')
        parse = _freeze_parse(folder / f'{number:06d}.parse', index_raw, rules)
    argv = [*snakemake, '--snakefile', parse['snakefile']['path'], '--directory', str(wf),
            '--cores', '1', '--retries', '0', target]
    authorized = _closure(json.loads(index_raw), task)
    # A launch of a later task also runs its unfinished dependencies: their dispatch records belong to this receipt.
    folders = [Path(row['export']['path']).parent / 'dispatch' for row in json.loads(index_raw)['tasks'] if row['id'] in authorized]
    dispatched = lambda: {p for folder in folders if folder.is_dir() for p in folder.glob('*.json')}
    before = dispatched()
    profile = {'workflow_profiles_folder': False,
               PROFILE_VARIABLE: 'removed' if PROFILE_VARIABLE in os.environ else 'absent'}
    start = _utc()
    with log_stream, wms_policy.launch_authorization(wf, task, number, authorized):
        # Recheck the combined records at dispatch, after version discovery and parse freezing.
        from . import wms_adopt
        for row in json.loads(index_raw)['tasks']:
            if row['id'] in authorized:
                wms_adopt.check_launch_binding(row)
        code, log = _execute(argv, wf)
        log_stream.write(log)
    end = _utc()
    marker = wf / target
    frozen = [parse['snakefile'], parse['index'], *parse['rules']]
    parse['unchanged_after_run'] = all(Path(p['path']).is_file() and site_workflow._pin(p['path']) == p for p in frozen)
    receipt = {'schema_version': 1, 'task': task, 'argv': argv, 'snakemake_version': version,
               'start_utc': start, 'end_utc': end, 'exit_code': code, 'parse_inputs': parse, 'snakemake_profile': profile,
               'completion_marker': None, 'dispatch_records': [], 'snakemake_locks_present_during_step': [],
               'log': site_workflow._pin(folder / f'{number:06d}.log'), 'incomplete': None,
               'records': 'delivery only', 'scientific_acceptance_inferred': False}
    receipt['workflow_bindings'] = [
        {'task': row['id'], **row['workflow_binding']} for row in json.loads(index_raw)['tasks']
        if row['id'] in authorized and 'workflow_binding' in row]
    reading = marker
    try:
        # The stage has run: a record that cannot be read marks the receipt incomplete, it does not lose the receipt.
        receipt['completion_marker'] = site_workflow._pin(marker) if marker.is_file() else None
        for reading in sorted(dispatched() - before):
            locks = _read(reading)['snakemake_locks_present']
            receipt['dispatch_records'].append(site_workflow._pin(reading))
            receipt['snakemake_locks_present_during_step'].append(locks)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        receipt['incomplete'] = f'delivery record {reading} could not be read after the run ({exc})'
    root_stream.write_new(folder / f'{number:06d}.json', receipt)
    return receipt


def status(project):
    """Per-task delivery, launches and dispatches; exposes steps that bypassed Snakemake."""
    wf = _workflow(project)
    rows = []
    # A dependency is dispatched inside the launch of a later task, so receipts of every task count.
    launched = {r['path'] for p in sorted((wf / 'launches').glob('*/*.json')) for r in _read(p)['dispatch_records']}
    for entry in _read(wf / 'index.json')['tasks']:
        launches = [_read(p) for p in sorted((wf / 'launches' / entry['id']).glob('*.json'))]
        dispatch = Path(entry['export']['path']).parent / 'dispatch'
        records = sorted(dispatch.glob('*.json')) if dispatch.is_dir() else []
        rows.append({'id': entry['id'], 'rundir': entry['rundir'], 'after': entry['after'],
                     'delivered': (wf / 'exports' / entry['id'] / 'completed' / f"{entry['id']}.json").is_file(),
                     'launches': len(launches), 'last_exit_code': launches[-1]['exit_code'] if launches else None,
                     'dispatches': len(records),
                     'dispatches_without_snakemake_lock': sum(not _read(p)['snakemake_locks_present'] for p in records),
                     'dispatches_outside_launch': sum(str(p) not in launched for p in records)})
    policy = wf / 'policy.json'
    return {'workflow': str(wf), 'policy': _read(policy) if policy.is_file() else None, 'tasks': rows,
            'scientific_acceptance_inferred': False}


def main(argv=None):
    p = argparse.ArgumentParser(prog='ravel wms', description=__doc__)
    sub = p.add_subparsers(dest='operation', required=True)
    i = sub.add_parser('init', help='lay out <project>/workflow and require the workflow manager')
    i.add_argument('--project', type=Path, required=True)
    i.add_argument('--audit', type=Path, required=True, help='JSON audit block of record paths')
    i.add_argument('--python', type=Path)
    i.add_argument('--site-id', default='local')
    i.add_argument('--profile', default='local')
    a = sub.add_parser('add', help='emit the rule for an approved run dir before it runs')
    a.add_argument('--project', type=Path, required=True)
    a.add_argument('--rundir', type=Path, required=True)
    a.add_argument('--task')
    a.add_argument('--after', action='append', default=[])
    l = sub.add_parser('launch', help='run an indexed task through Snakemake run-step')
    l.add_argument('--project', type=Path, required=True)
    l.add_argument('--task', required=True)
    l.add_argument('--cores', type=int, default=1)
    s = sub.add_parser('status', help='show delivery, launches and dispatches per task')
    s.add_argument('--project', type=Path, required=True)
    r = sub.add_parser('revalidate', help='acknowledge a policy change for one indexed, still approved task')
    r.add_argument('--project', type=Path, required=True)
    r.add_argument('--task', required=True)
    t = sub.add_parser('retry', help='plan a fresh attempt of a failed partition task, or register an approved one')
    t.add_argument('--project', type=Path, required=True)
    t.add_argument('--task', required=True)
    arguments = list(sys.argv[1:] if argv is None else argv)
    # External Snakefile adoption owns only its own operation names; the launch operations above parse here.
    if arguments and arguments[0] in ('adopt', 'adopt-run', 'adopt-status'):
        from . import wms_adopt
        return wms_adopt.main(arguments)
    args = p.parse_args(arguments)
    if args.operation == 'init':
        value = init(args.project, args.profile, audit=_read(args.audit), python=args.python, site_id=args.site_id)
    elif args.operation == 'add':
        value = add(args.project, args.rundir, args.after, task=args.task)
    elif args.operation == 'launch':
        value = launch(args.project, args.task, args.cores)
    elif args.operation == 'revalidate':
        value = revalidate(args.project, args.task)
    elif args.operation == 'retry':
        from . import wms_retry
        value = wms_retry.retry(args.project, args.task)
    else:
        value = status(args.project)
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 1 if args.operation == 'launch' and value['exit_code'] != 0 else 0


if __name__ == '__main__':
    raise SystemExit(main())
