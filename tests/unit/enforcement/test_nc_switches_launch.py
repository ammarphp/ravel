"""Launch switch rows: nothing chosen by the environment, a committed file or a worker's shell unlocks a launch.

The adversary is whatever can reach a launch from outside the controller: a worker that calls the
facility submit console script itself, a shell that unsets the agent-session markers, a process
environment that raises a ceiling or names a restricted-source list, a committed policy file, an
authored script (a construction check or a nested stage) that tries the store, the network and a
model program, a call made outside every substrate node, and a worker that writes its CLI login
home or opens a socket to a host that is not the model endpoint. Oracles are read from outside the
launch: the inert scheduler stub's call log, process-start counters, sentinel bytes, listener
connections, the controller store's own records, and each refusal's exact type and message
fragment. Every case ends with a positive control through the same entry.

A refusal is checked with ``_refused``, which turns any other outcome (a return, another type,
another message) into an ``AssertionError``: a disabled mechanism then fails an expectation and is
never mistaken for an unrelated error. Hostile writes target paths under the case's own root only.
"""
from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from nc_adversary import InstalledWorker, sandbox_or_skip
from nc_cases import CONTROLLER, FIXTURES, SANDBOX_BLOCKED, case, require_controller
from nc_controller import HostileLaunch, controller_run, operator
from nc_effects import Sentinels
from nc_mutations import CONTROLLER as MUTATION_CONTROLLER, Mutation, constant, register, returns

FINAL = {'completed': True, 'summary': 'fictional result written'}
LAUNCH = [sys.executable, '-c', "print('inert')"]


# ------------------------------------------------------------------------------ shared helpers

def _refused(call, kind, fragment, what):
    """The exception ``call`` raises, checked from outside the mechanism: its type and a message fragment.

    Anything else (the call returns, another type, another message) is an oracle failure, so a
    disabled mechanism is reported as a failed expectation, never as an unrelated error.
    """
    try:
        returned = call()
    except (KeyboardInterrupt, pytest.skip.Exception):
        raise
    except BaseException as exc:
        assert isinstance(exc, kind) and fragment in str(exc), (
            f'{what}: expected {kind.__name__} containing {fragment!r}; got {type(exc).__name__}: {str(exc)[:400]}')
        return exc
    raise AssertionError(f'{what}: expected {kind.__name__} containing {fragment!r}; the call returned {returned!r}')


class _Popen:
    """Every ``subprocess.Popen`` start in this process as an argv list (the real Popen still runs)."""

    def __init__(self, patch):
        self.argvs = []
        real, outer = subprocess.Popen, self

        class Counting(real):
            def __init__(self, args, *more, **named):
                outer.argvs.append([str(part) for part in ([args] if isinstance(args, (str, bytes)) else args)])
                super().__init__(args, *more, **named)
        patch.setattr(subprocess, 'Popen', Counting)

    def starts_of(self, *words):
        """Argument vectors that contain every one of ``words`` as an element."""
        return [argv for argv in self.argvs if all(word in argv for word in words)]


def _launch_sandbox_or_skip(confine):
    """Skip with the declared reason when this host offers no qualified launch sandbox."""
    offered = {name: state for name, state in confine.backends().items() if name in ('sandbox-exec', 'bwrap')}
    if 'available' not in offered.values():
        pytest.skip(f'{SANDBOX_BLOCKED} no qualified launch sandbox on this host: {offered}')


def _without_wrapper_when_labelled(label):
    """Remove only a labelled launch's Linux wrapper, preserving real qualification."""
    def build(original):
        def linux_argv(plan, env):
            if plan.record.get('label') == label:
                return list(plan.argv)
            return original(plan, env)
        return linux_argv
    return build


def _fake_model_cli(nc):
    """A stand-in model program: any start leaves a call file and connects to the case's listener."""
    calls = nc.path('effects', 'model-calls', 'placeholder').parent
    cli = nc.path('tools', 'claude')
    cli.write_text(f'#!{sys.executable} -B\nimport socket, uuid\n'
                   f'open({str(calls / "call-")!r} + uuid.uuid4().hex, "w").write("called")\n'
                   f'socket.create_connection(("127.0.0.1", {nc.effects.listener.port}), timeout=2).close()\n')
    cli.chmod(0o755)
    return cli, calls


# --------------------------------------------------------------------------------------- SW12

def _inert_scheduler(nc):
    """An inert ``condor_submit`` first on PATH. Each call appends one line to a counter file outside every
    job directory: its arguments and the ``arguments`` line of the submit description (the job it was given)."""
    folder = nc.path('bin', 'placeholder').parent
    calls = nc.path('effects', 'condor-calls.jsonl')
    tool = folder / 'condor_submit'
    tool.write_text(f'#!{sys.executable}\nimport json, sys\n'
                    'text = open(sys.argv[-1]).read()\n'
                    'line = next((l for l in text.splitlines() if l.startswith("arguments")), "")\n'
                    f'record = json.dumps({{"argv": sys.argv[1:], "arguments": line}})\n'
                    f'open({str(calls)!r}, "a").write(record + "\\n")\n'
                    'print("12.0")\n')
    tool.chmod(0o755)
    nc.patch.setenv('PATH', f'{folder}{os.pathsep}{os.environ["PATH"]}')
    return lambda: [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []


# The console script's body (``ravel-wms-condor-submit``), run as a separate process.
CONSOLE_PROGRAM = ('import sys\nfrom ravel.workflow.site_profiles.htcondor import submit_main\n'
                   'raise SystemExit(submit_main(sys.argv[1:]))\n')


def _job_script(path, rule):
    path.write_text('#!/bin/sh\n# properties = ' + json.dumps({'threads': 1, 'rule': rule}) + '\nexit 0\n')
    return path


@case('SW12', binding=CONTROLLER)
def test_SW12_the_facility_submit_console_script_refuses_a_job_without_the_capability_of_its_live_launch(nc):
    confine = require_controller('confine')
    from ravel.workflow import wms_policy
    from ravel.workflow.site_profiles import htcondor, render
    store, _ = controller_run(nc)
    scheduler = _inert_scheduler(nc)
    workflow = nc.path('workflow', 'run-keys.json').parent
    (workflow / 'run-keys.json').write_text(json.dumps({'alpha': '012abc', 'beta': '345def'}))
    alpha = _job_script(workflow / 'job-alpha.sh', 'task_alpha')
    profile = nc.path('profile.json')
    profile.write_text(json.dumps(render('htcondor', project_id='project-a', options={'workflow_dir': str(workflow)})))

    def submit():
        """The console script's entry (``ravel-wms-condor-submit``) on the job: (status, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = htcondor.submit_main(['--profile', str(profile), str(alpha)])
            except SystemExit as stop:
                status = stop.code
        return status, out.getvalue(), err.getvalue()

    def submissions():
        return [row['record'] for row in store.scan('wms-submission')]

    # 1. A direct call with no capability submits nothing: through the entry, and as a separate process.
    status, _, err = submit()
    assert status == 1 and 'no launch capability was presented' in err, ('no capability', status, err)
    assert scheduler() == [] and list(workflow.rglob('submit-*')) == [] and submissions() == []
    child = subprocess.run([sys.executable, '-c', CONSOLE_PROGRAM, '--profile', str(profile), str(alpha)],
                           capture_output=True, text=True, timeout=120, env=dict(os.environ))
    assert child.returncode == 1 and 'no launch capability was presented' in child.stderr, child
    assert scheduler() == []
    # 2. A well-formed capability this run never minted, outside any live launch, submits nothing either.
    nc.patch.setenv(wms_policy.CAPABILITY_ENV, f'rwc1.{store.run_id}.launch-9.' + 'x' * 43)
    status, _, err = submit()
    assert status == 1 and 'belongs to no live governed launch' in err, ('forged capability', status, err)
    nc.patch.delenv(wms_policy.CAPABILITY_ENV)
    assert scheduler() == [] and submissions() == []
    # 3. The supervised launch mints one capability for its approved task; the executor it starts presents it.
    token = confine.mint_capability(store, 'launch-1', {'workflow_dir': str(workflow), 'tasks': ['alpha'],
                                                         'rules': ['task_alpha'], 'max_jobs': 1})
    exports = {'alpha': 'a' * 64, 'beta': 'b' * 64}
    original = alpha.read_text()
    with wms_policy.launch_authorization(workflow, 'alpha', 1, exports, capability=token,
                                         controller_run=store.run_id):
        # The job script edited after minting to another task's rule is outside the capability.
        alpha.write_text(original.replace('task_alpha', 'task_beta'))
        status, _, err = submit()
        assert status == 1 and "rule 'task_beta' is outside the capability" in err, ('edited job', status, err)
        assert scheduler() == [] and submissions() == []
        # Positive control: the approved job is submitted once, and the stub received exactly that job.
        alpha.write_text(original)
        status, out, err = submit()
        assert status == 0 and out.strip() == '12.0', ('approved job', status, out, err)
        calls = scheduler()
        assert len(calls) == 1, calls
        retained = submissions()[0]
        frozen = Path(retained['snapshot_path'])
        wrappers = list(nc.root.glob('.ravel-controller-submissions/*/run.sh'))
        assert len(wrappers) == 1 and str(wrappers[0]) in calls[0]['arguments'], calls
        descriptor = json.loads((wrappers[0].parent / 'job.json').read_bytes())
        assert descriptor['script_sha256'] == retained['jobscript_sha256']
        assert Path(descriptor['script_path']).read_bytes() == frozen.read_bytes()
        assert frozen.read_bytes() == alpha.read_bytes()
        assert __import__('hashlib').sha256(frozen.read_bytes()).hexdigest() == retained['jobscript_sha256']
        assert [(row['task'], row['jobscript']) for row in submissions()] == [('alpha', str(alpha))]
        # The capability admits one job: a replay is refused and the stub is not called again.
        status, _, err = submit()
        assert status == 1 and 'admits 1 job(s) and all were submitted' in err, ('replay', status, err)
        assert len(scheduler()) == 1
    # The capability ends with its launch: the same token, presented later, submits nothing.
    nc.patch.setenv(wms_policy.CAPABILITY_ENV, token)
    status, _, err = submit()
    assert status == 1 and 'belongs to no live governed launch' in err, ('stale capability', status, err)
    assert len(scheduler()) == 1


class _EveryTask(dict):
    """A launch record's task map that lists every task."""
    def __bool__(self):
        return True

    def __contains__(self, key):
        return True


def _launch_that_admits_any_job(original):
    return lambda workflow: {'exports': _EveryTask(), 'task': 'any'}


_SUBMIT_GATE = ('ravel.workflow.site_profiles.htcondor:bind_submission',)
def _without_task_rule_scope(original):
    def scope(value):
        admitted = original(value)
        return {key: item for key, item in admitted.items() if key not in ('tasks', 'rules')}
    return scope


_SCOPE = 'ravel.controller.confine.capability:_scope'
register(Mutation('SW12', _SUBMIT_GATE, returns(None), ('SW12',), binding=MUTATION_CONTROLLER,
                  why='the console script submits without asking for a launch capability'),
         Mutation('SW12', 'ravel.workflow.wms_policy:governed_submission', _launch_that_admits_any_job, ('SW12',),
                  binding=MUTATION_CONTROLLER, why='any process counts as the executor of a live governed launch'),
         Mutation('SW12', _SCOPE, _without_task_rule_scope, ('SW12',), binding=MUTATION_CONTROLLER,
                  why='the minted capability is never checked against its scope'))


# --------------------------------------------------------------------------------------- SW17

class _WatchedMarkers(tuple):
    """The agent-session marker names, counting every read of them."""
    reads = 0

    def __iter__(self):
        type(self).reads += 1
        return super().__iter__()

    def __contains__(self, item):
        type(self).reads += 1
        return super().__contains__(item)

    def __getitem__(self, item):
        type(self).reads += 1
        return super().__getitem__(item)


@case('SW17', binding=CONTROLLER)
def test_SW17_unsetting_the_agent_markers_does_not_unlock_engineering_only_dispatch_of_a_controller_run(nc):
    confine = require_controller('confine')
    from ravel.workflow import approval_authority, stage_supervisor
    _, run_dir = controller_run(nc)
    names = tuple(approval_authority.AGENT_MARKERS)
    for name in names:
        nc.patch.delenv(name, raising=False)
    watched = type('Watched', (_WatchedMarkers,), {'reads': 0})(names)
    nc.patch.setattr(approval_authority, 'AGENT_MARKERS', watched)
    popen = _Popen(nc.patch)
    refusal = 'engineering-only dispatch is unavailable for a controller-owned run'

    def dispatch(run, log):
        return lambda: stage_supervisor.supervise('probe', str(run), 0, log, LAUNCH, kill_secs=10.0, stall_secs=10.0,
                                                  poll=0.2, grace=1.0, _engineering_only=True)

    # The same refusal whether the markers are unset (the attack) or set: the decision never depends on them.
    unset = _refused(dispatch(run_dir, 'logs/probe.log'), ValueError, refusal, 'markers unset')
    nc.patch.setenv(names[-1], '1')
    marked = _refused(dispatch(run_dir, 'logs/probe.log'), ValueError, refusal, 'marker set')
    assert str(unset) == str(marked)
    nc.patch.delenv(names[-1])
    assert popen.starts_of(*LAUNCH) == [] and not (run_dir / 'logs').exists(), 'nothing was started or recorded'
    assert watched.reads == 0, 'controller mode never reads the agent-session markers'
    # A governed launch carries no marker either, so a launched stage cannot inherit or present a session.
    scrubbed, removed = confine.environment.scrub({**{name: '1' for name in names}, 'LANG': 'C'})
    assert scrubbed == {'LANG': 'C'} and sorted(removed) == sorted(names), (scrubbed, removed)
    # Positive control, same entry on a run the controller does not own: there the markers decide.
    legacy = nc.path('legacy-run', 'placeholder').parent
    nc.patch.setenv(names[-1], '1')
    _refused(dispatch(legacy, 'logs/probe.log'), ValueError, 'cannot carry scientific authority or an agent session',
             'legacy run with a marker')
    assert watched.reads > 0 and popen.starts_of(*LAUNCH) == []
    nc.patch.delenv(names[-1])
    assert dispatch(legacy, 'logs/probe.log')() == 0, 'unsetting the markers unlocks the 1.1.0 dispatch of a legacy run'
    assert len(popen.starts_of(*LAUNCH)) == 1


def _keeps_agent_markers(original):
    """The environment scrub lets the agent-session markers through (the qualification probe is unaffected)."""
    from ravel.workflow import approval_authority
    markers = tuple(approval_authority.AGENT_MARKERS)
    return lambda name, kept=(): None if name in markers else original(name, kept)


register(Mutation('SW17', 'ravel.workflow.stage_supervisor:_controller_run', returns(None), ('SW17',),
                  binding=MUTATION_CONTROLLER, why='a controller-owned run is dispatched like a legacy run'),
         Mutation('SW17', 'ravel.controller.confine.environment:forbidden', _keeps_agent_markers, ('SW17',),
                  binding=MUTATION_CONTROLLER, why='a governed launch inherits the agent-session markers'))


# --------------------------------------------------------------------------------------- SW22

FINGERPRINT = 'zq-invented-marker-7731'
RESTRICTED_VARIABLE = 'RAVEL_RESTRICTED_SOURCES'


def _keeps_the_restricted_list_variable(original):
    """The environment scrub lets this one RAVEL override through (the qualification probe is unaffected)."""
    def forbidden(name, kept=()):
        return None if name == RESTRICTED_VARIABLE else original(name, kept)
    return forbidden


@case('SW22', binding=CONTROLLER)
def test_SW22_the_restricted_source_policy_of_a_controller_run_does_not_follow_the_environment(nc):
    confine = require_controller('confine')
    _launch_sandbox_or_skip(confine)
    launch = HostileLaunch(nc)
    secret = nc.effects.canary('owner-list')
    owner = nc.path('owner', 'restricted-sources.json')
    owner.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources', 'documents': [],
                                 'fingerprints': [FINGERPRINT], 'note': secret.value}))
    # A. A governed launch never receives the variable, whether the controller has it set or the stage's capsule
    #    offers it, and cannot read the list; its environment is the same with the variable and without it.
    nc.patch.setenv(RESTRICTED_VARIABLE, str(owner))
    launch.run([{'op': 'env'}, {'op': 'read', 'path': str(owner)}], env={RESTRICTED_VARIABLE: str(owner)})
    assert launch.returncode == 0, launch.stderr
    with_variable = set(launch.record['environment_names'])
    seen = next(a['result'] for a in launch.observed() if a['op'] == 'env')
    assert RESTRICTED_VARIABLE not in with_variable and RESTRICTED_VARIABLE not in seen
    assert secret.found_in(launch.run_dir, launch.store.root) == [], 'the stage read the owner list'
    nc.patch.delenv(RESTRICTED_VARIABLE)
    launch.run([{'op': 'env'}])
    assert launch.returncode == 0 and set(launch.record['environment_names']) == with_variable
    assert launch.report.is_file(), 'positive control: the stage ran and wrote its declared output'
    # B. The controller-side restricted-source check (the generality gate, run from inside a controller-owned run)
    #    must not come back clean because the variable is absent: the policy is the run's pinned one, and absence is
    #    not permission. NOT IMPLEMENTED by the confinement package (the gate and the export scan still read the
    #    process environment): the last assertion fails until the controller-side check refuses or pins its list.
    gate = importlib.import_module('ravel.validation.check_generality')
    tree = nc.path('delivery-tree', 'notes.txt').parent
    (tree / 'notes.txt').write_text(f'a line carrying {FINGERPRINT}\n')
    elsewhere = nc.path('legacy-run', 'placeholder').parent

    def scan(cwd, listed):
        nc.patch.delenv(RESTRICTED_VARIABLE, raising=False)
        if listed:
            nc.patch.setenv(RESTRICTED_VARIABLE, str(owner))
        here = os.getcwd()
        os.chdir(cwd)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return gate.main(['--tree', str(tree)])
        finally:
            os.chdir(here)

    assert scan(elsewhere, listed=True) == 1, 'positive control: the owner list names the fingerprint'
    assert scan(elsewhere, listed=False) == 0, 'outside a controller run the absence of the list reduces the check'
    assert scan(launch.run_dir, listed=False) != 0, (
        f'NOT IMPLEMENTED (P05): in a controller-owned run the absence of {RESTRICTED_VARIABLE} still yields a clean '
        "restricted-source scan; the policy must come from the run's pinned policy and absence must refuse")


register(Mutation('SW22', 'ravel.controller.confine.environment:forbidden', _keeps_the_restricted_list_variable,
                  ('SW22',), binding=MUTATION_CONTROLLER,
                  why='the environment scrub passes the restricted-source list variable to a governed launch'))


# --------------------------------------------------------------------------------------- SW24

def _environment_wins(original):
    """The ceiling is read as for a legacy caller: from the variable or the state file, whatever the run."""
    return lambda rundir=None: original(None)


@case('SW24', binding=CONTROLLER)
def test_SW24_the_environment_cannot_raise_the_remote_job_ceiling_of_a_controller_run(nc):
    require_controller('confine')
    from ravel.workflow import execution_backend
    operator(nc).init('physicist-in-the-loop', '--remote-job-ceiling', '1')
    _, run_dir = controller_run(nc)
    nc.patch.setenv('RAVEL_REMOTE_JOB_CEILING', '64')
    state = execution_backend.state_dir()
    assert os.path.realpath(state).startswith(os.path.realpath(nc.root.parent)), 'a test lock domain, not the machine'
    state.mkdir(parents=True, exist_ok=True)
    (state / 'remote-ceiling.json').write_text('{"max_jobs": 64}')
    # The variable and the owner-set state file are both ignored: the operator's configuration (default 1) rules.
    assert execution_backend.remote_ceiling(run_dir) == 1
    with contextlib.ExitStack() as stack:
        assert stack.enter_context(execution_backend.remote_slot('nc-holder-a', rundir=run_dir)) == 0
        _refused(lambda: stack.enter_context(execution_backend.remote_slot('nc-holder-b', rundir=run_dir)),
                 ValueError, 'remote job ceiling of 1 is reached', 'a second remote job of the controller run')
    # Positive control, same entries for a caller the controller does not own: the documented override holds.
    legacy = nc.path('legacy-run', 'placeholder').parent
    assert execution_backend.remote_ceiling() == 64 and execution_backend.remote_ceiling(legacy) == 64
    with contextlib.ExitStack() as stack:
        slots = [stack.enter_context(execution_backend.remote_slot(f'nc-holder-{n}', rundir=legacy))
                 for n in range(3)]
    assert slots == [0, 1, 2]


register(Mutation('SW24', 'ravel.workflow.execution_backend:remote_ceiling', _environment_wins, ('SW24',),
                  binding=MUTATION_CONTROLLER, why='the remote job ceiling follows the environment variable'))


# --------------------------------------------------------------------------------------- SW27

STRICT_POLICY = {'schema_version': 1, 'wms_required': True, 'engine': 'snakemake', 'execution_guard': 'strict'}
RELAXED_POLICY = {'schema_version': 1, 'wms_required': False, 'engine': 'snakemake'}


def _git(project, *args):
    """``git`` in a fixture repository under the case's root, with none of the caller's GIT_* variables."""
    env = {name: value for name, value in os.environ.items() if not name.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
    subprocess.run(['git', '-c', 'user.name=fictional', '-c', 'user.email=fictional@example.org',
                    '-c', 'commit.gpgsign=false', '-C', str(project), *args], check=True, capture_output=True, env=env)


def _guarded_project(root):
    """A fictional project whose strict workflow policy is committed, with the software skills the guard asks for."""
    (root / 'workflow').mkdir(parents=True)
    (root / 'workflow' / 'policy.json').write_text(json.dumps(STRICT_POLICY))
    for name in ('software-git', 'software-snakemake', 'software-ravel'):
        (root / '.claude' / 'skills' / name).mkdir(parents=True)
        (root / '.claude' / 'skills' / name / 'SKILL.md').write_text(f'---\nname: {name}\n---\n')
    for step in (('init', '-q'), ('add', '-A'), ('commit', '-q', '-m', 'project')):
        _git(root, *step)
    return root


@case('SW27', binding=CONTROLLER)
def test_SW27_a_committed_relaxed_policy_does_not_relax_the_guard_of_a_controller_run_and_workers_have_no_git(nc):
    require_controller('confine')
    from ravel.workflow import execution_guard
    project = _guarded_project(nc.root / 'project')
    _, run_dir = controller_run(nc)
    # On a legacy run strict mode allows the allowed git commands, so a worker can commit a relaxed policy ...
    assert execution_guard.decide('git commit -m relax', project)['allowed'] is True
    (project / 'workflow' / 'policy.json').write_text(json.dumps(RELAXED_POLICY))
    _git(project, 'add', '-A')
    _git(project, 'commit', '-q', '-m', 'relax the guard')
    # ... and then the guard no longer holds (positive control: the attack is real where the controller is absent).
    relaxed = execution_guard.decide('bash -c "anything"', project)
    assert (relaxed['mode'], relaxed['allowed'], relaxed['rule']) == ('off', True, 'not-strict'), relaxed
    # In a controller-owned run the committed relaxation is never read: strict, from the installed rules.
    for command in ('bash -c "anything"', 'python3 -c "print(1)"'):
        decision = execution_guard.decide(command, project, cwd=run_dir)
        assert (decision['mode'], decision['allowed']) == ('strict', False), (command, decision)
    # Workers have no git write: the commands that would commit a policy are refused by rule.
    for command in ('git add .', 'git commit -m relax', 'git add workflow/policy.json'):
        decision = execution_guard.decide(command, project, cwd=run_dir)
        assert (decision['allowed'], decision['rule']) == (False, 'git-write'), (command, decision)
    assert execution_guard.decide('git -C . commit -m relax', project, cwd=run_dir)['allowed'] is False
    # Positive control: read-only git inspection stays allowed in the controller run.
    status = execution_guard.decide('git status', project, cwd=run_dir)
    assert (status['mode'], status['allowed'], status['rule']) == ('strict', True, 'git-status'), status


register(Mutation('SW27', 'ravel.workflow.execution_guard:controller_run', returns(None), ('SW27',),
                  binding=MUTATION_CONTROLLER, why='the guard does not recognise a controller-owned run'),
         Mutation('SW27', 'ravel.workflow.execution_guard:GIT_WRITE_SUBCOMMANDS', constant(frozenset()), ('SW27',),
                  binding=MUTATION_CONTROLLER, why='a controller run is allowed git add and git commit'))


# --------------------------------------------------------------------------------------- SW35

CHECK_TOOL = r'''#!PYTHON -B
import json, socket, subprocess, sys
from pathlib import Path
attempts = json.loads(ATTEMPTS)
log = []
def attempt(op, func):
    try:
        log.append({'op': op, 'ok': True, 'result': func()})
    except BaseException as exc:
        log.append({'op': op, 'ok': False, 'error': type(exc).__name__})
def write(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text)
    return str(path)
for item in attempts:
    op = item['op']
    if op == 'write':
        attempt(op, lambda: write(item['path'], item['text']))
    elif op == 'steal':
        attempt(op, lambda: write(item['to'], Path(item['path']).read_text()))
    elif op == 'connect':
        attempt(op, lambda: socket.create_connection(('127.0.0.1', item['port']), timeout=2).close())
    elif op == 'exec':
        attempt(op, lambda: subprocess.run(item['argv'], capture_output=True, timeout=10).returncode)
write(sys.argv[1], 'declared plugin output')
write('attempts.json', json.dumps(log))
'''


def _construction_session(nc, root, tool):
    """The checks session of a fictional construction directory, started as its approval would start it."""
    from ravel.physics import routine_build
    from ravel.workflow import agentrivet_checks
    session = agentrivet_checks.Session.__new__(agentrivet_checks.Session)
    session.request, session.request_pin, session.root, session.routine = {}, {}, root, 'FictionalRoutine'
    build = {'path': str(tool), 'identity': routine_build.executable_identity(tool)}
    session.checks = {'schema_version': 1,
                      'runtime': {'rivet_build': build, 'rivet': None, 'python': None, 'environment': {}},
                      'compile': {'max_probes': 2, 'timeout_seconds': 60}, 'sample': None}
    session.table_map, session.contract, session.histograms, session.reference = None, [], (lambda: []), None
    session.directory = root / 'checks'
    session.directory.mkdir()
    session.approval = {'path': str(root / 'checks-approval.json'), 'sha256': 'c' * 64}
    session.reservation = 'operation:fictional-construction'
    session.records = {}
    return session


@case('SW35', binding=CONTROLLER)
def test_SW35_a_construction_check_launches_confined_and_its_journal_is_written_by_the_controller(nc):
    confine = require_controller('confine')
    _launch_sandbox_or_skip(confine)
    from ravel.workflow import launch_authorization
    store, run_dir = controller_run(nc)
    root = run_dir / 'construction'
    (root / 'logs' / 'authorization').mkdir(parents=True)
    (root / 'tools').mkdir()
    secret = nc.effects.canary('credential')
    credentials = nc.path('account', '.aws', 'credentials')
    credentials.write_text(f'[default]\naws_secret_access_key = {secret.value}\n')
    cli, calls = _fake_model_cli(nc)
    forged = root / 'logs' / 'authorization' / '00000099.json'
    journal = store.root / 'journal.jsonl'
    journal_before = journal.read_bytes()
    workdir = root / 'checks' / 'probe-01'  # the check's own work directory: the one place it may write
    attempts = [{'op': 'write', 'path': str(forged), 'text': '{"event": "authorized", "forged": true}'},
                {'op': 'write', 'path': str(journal), 'text': '{"forged": true}\n'},
                {'op': 'write', 'path': str(root / 'undeclared.json'), 'text': '{}'},
                {'op': 'steal', 'path': str(credentials), 'to': str(workdir / 'stolen.txt')},
                {'op': 'connect', 'port': nc.effects.listener.port},
                {'op': 'exec', 'argv': [str(cli), '-p', 'fictional request']}]
    tool = root / 'tools' / 'rivet-build'
    tool.write_text(CHECK_TOOL.replace('PYTHON', sys.executable).replace('ATTEMPTS', repr(json.dumps(attempts))))
    tool.chmod(0o755)
    session = _construction_session(nc, root, tool)
    popen = _Popen(nc.patch)
    head = store.head()['seq']
    observe_error, record = None, None
    try:
        record = session.observe('// a fictional routine draft\n')
    except Exception as exc:
        observe_error = exc
    # Effects come from outside the check, even if its hostile journal write made
    # the subsequent observer/store fold raise. Unrelated errors remain errors.
    assert nc.effects.listener.accepted == 0 and list(calls.iterdir()) == []
    assert not forged.exists() and not (root / 'undeclared.json').exists() and not (workdir / 'stolen.txt').exists()
    assert secret.found_in(run_dir, store.root) == [] and journal.read_bytes().startswith(journal_before)
    assert [argv for argv in popen.argvs if argv[0] == str(tool)] == []
    if observe_error is not None:
        raise observe_error
    assert store.verify() == []
    # The check was launched through the confined launcher: the bare tool was never the started program.
    started = popen.starts_of(str(tool))
    assert len(started) == 1 and Path(started[0][0]).name in ('sandbox-exec', 'bwrap'), started
    assert [argv for argv in popen.argvs if argv[0] == str(tool)] == []
    # The journal is the controller's: two events, mirrored from the store, the launch event naming its sandbox.
    events = launch_authorization._events(root)
    assert [e['event'] for e in events] == ['authorized', 'launched'] and events[1]['confinement']['kind'] == 'confined'
    assert [row['record']['sha256'] for row in store.scan(launch_authorization.STORE_KIND)] == [
        e['sha256'] for e in events]
    assert store.head()['seq'] - head == 4 and launch_authorization.store_mirror_errors(root) == []
    assert [r['record']['event'] for r in store.scan('confinement-launch')] == ['admitted', 'finished']
    # Positive control: the check still ran and produced its declared output.
    assert record['compile']['status'] == 'passed' and (workdir / 'RivetFictionalRoutine.so').is_file()
    report = json.loads((workdir / 'attempts.json').read_text())
    assert [a['op'] for a in report] == ['write', 'write', 'write', 'steal', 'connect', 'exec']


register(Mutation('SW35', 'ravel.workflow.agentrivet_checks:Session._confinement', returns(None), ('SW35',),
                  binding=MUTATION_CONTROLLER, why='a construction check starts with a direct, unconfined Popen'),
         Mutation('SW35', 'ravel.controller.confine.launcher:linux_argv',
                  _without_wrapper_when_labelled('agentrivet-construction-check'), ('SW35',),
                  binding=MUTATION_CONTROLLER, why='the construction check runs without the OS sandbox'))


# --------------------------------------------------------------------------------------- SW36

NESTED_STAGE = 'nc-nested-stage'
PARENT_STAGE = 'nc-parent-stage'


def _any_command_is_a_broker(original):
    return lambda root, command: {'class': 'controller-side', 'entry_point': 'fictional', 'reason': 'fictional'}


def _planned_without_the_sandbox(original):
    """The nested stage's actual Linux argv omits its sandbox; its Plan stays confined."""
    def linux_argv(plan, env):
        if plan.record.get('stage') == NESTED_STAGE:
            return list(plan.argv)
        return original(plan, env)
    return linux_argv


def _started_without_the_wrapper(original):
    """Inject the actual start function's Popen to remove only the nested wrapper."""
    def start(plan, *args, **kwargs):
        if plan.record.get('stage') == NESTED_STAGE:
            popen = kwargs.pop('popen', None) or subprocess.Popen
            def bare(_wrapped_argv, *more, **named):
                return popen(list(plan.argv), *more, **named)
            kwargs['popen'] = bare
        return original(plan, *args, **kwargs)
    return start


@case('SW36', binding=CONTROLLER)
def test_SW36_a_nested_stage_runs_its_authored_script_confined_and_the_legacy_paths_are_refused(nc):
    confine = require_controller('confine')
    _launch_sandbox_or_skip(confine)
    from ravel.workflow import execution, execution_backend, method_selection, stage_supervisor
    store, run_dir = controller_run(nc)
    inputs, work, outputs = run_dir / 'inputs', run_dir / 'work', run_dir / 'outputs' / 'nested'
    for folder in (inputs, work, outputs):
        folder.mkdir(parents=True)
    script, plan_file, report = work / 'authored.py', work / 'attempts.json', outputs / 'report.json'
    shutil.copy(FIXTURES / 'scripts' / 'hostile.py', script)
    approval = inputs / 'approval.json'
    cli, calls = _fake_model_cli(nc)
    other = nc.effects.sentinels('other-workspace', {'outputs/result.json': '{"fictional": 1}'})
    journal = store.root / 'journal.jsonl'
    journal_before = journal.read_bytes()
    plan_file.write_text(json.dumps([
        {'op': 'write', 'path': str(journal), 'text': '{"forged": true}\n'},
        {'op': 'write', 'path': str(approval), 'text': '{"approved": true}'},
        {'op': 'write', 'path': str(other.root / 'outputs/result.json'), 'text': '{"fictional": 2}'},
        {'op': 'connect', 'port': nc.effects.listener.port},
        {'op': 'exec', 'argv': [str(cli), '-p', 'fictional request']}]))
    command = [sys.executable, '-B', str(script), str(plan_file), str(report)]
    context = {'stage': NESTED_STAGE, 'node_id': NESTED_STAGE,
               'stage_spec': {'inputs': [str(work)], 'outputs': [str(report)]}}

    def decide(cmd, legacy_science=False):
        return stage_supervisor._controller_launch(run_dir, NESTED_STAGE, cmd, context, str(work),
                                                   legacy_science=legacy_science)

    # The legacy paths: a version-one study is refused, and so is engineering-only dispatch (no launch decided).
    _refused(lambda: decide(command, legacy_science=True), confine.ConfinementRefused, 'version-one',
             'legacy scientific dispatch')
    _refused(lambda: stage_supervisor.supervise(NESTED_STAGE, str(run_dir), 0, 'logs/nested.log', command,
                                                kill_secs=10.0, _engineering_only=True),
             ValueError, 'engineering-only dispatch is unavailable for a controller-owned run', 'engineering dispatch')
    # A registered broker keeps the controller's environment; an authored script that looks like one does not.
    broker = [sys.executable, '-m', 'ravel.workflow.execution_backend', 'worker', '--rundir', str(run_dir)]
    assert decide(broker)['class'] == 'controller-side', 'positive control: the registered broker entry point'
    impostor = nc.path('other-env', 'bin', 'python')
    impostor.symlink_to(sys.executable)
    for authored in ([str(impostor), '-m', 'ravel.workflow.execution_backend', 'worker', '--rundir', str(run_dir)],
                     [sys.executable, '-m', 'ravel.workflow.execution_backend', 'doctor'],
                     [sys.executable, '-c', 'import ravel'], ['/bin/sh', str(script)]):
        planned = decide(authored)
        assert isinstance(planned, confine.Plan) and planned.kind == confine.CONFINED, authored
    # Exercise the supervisor's public launch resolver and the resulting real launcher.
    # Full scientific stage admission has separate review/authority prerequisites; this
    # control supplies no substitute review verdict or approval and claims only the
    # nested launch boundary. The legacy supervisor dispatch refusals were checked above.
    popen = _Popen(nc.patch)
    plan = decide(command)
    assert isinstance(plan, confine.Plan) and plan.kind == confine.CONFINED
    launch_error, process, finished = None, None, None
    try:
        process = confine.start(plan, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate(timeout=120)
        finished = confine.finish(process)
    except Exception as exc:
        launch_error = exc
    # Independent launch/effect counters run before any possibly damaged store
    # fold or re-raised API error. A bare hostile start is an observed effect.
    assert command not in popen.argvs, 'the authored script was started as a bare Popen of the approved argv'
    assert nc.effects.listener.accepted == 0 and list(calls.iterdir()) == [] and other.changes() == []
    assert not approval.exists() and journal.read_bytes().startswith(journal_before)
    if launch_error is not None:
        raise launch_error
    started = popen.starts_of(str(script))
    assert len(started) == 1 and Path(started[0][0]).name in ('sandbox-exec', 'bwrap'), started
    assert store.verify() == []
    assert [r['record']['event'] for r in store.scan('confinement-launch')] == ['admitted', 'finished']
    assert process.returncode == 0, stderr.decode(errors='replace')
    assert plan.record['kind'] == 'confined' and plan.record['declared_outputs'] == [str(report)]
    assert finished['errors'] == [] and str(report) in finished['adopted']
    assert [a['op'] for a in json.loads(report.read_text())] == ['write', 'write', 'write', 'connect', 'exec']



register(Mutation('SW36', 'ravel.workflow.stage_supervisor:_controller_launch', returns(None), ('SW36',),
                  binding=MUTATION_CONTROLLER, why='a nested stage of a controller run takes the legacy Popen path'),
         Mutation('SW36', ('ravel.controller.confine.brokers:entry_point', 'ravel.controller.confine:entry_point'),
                  _any_command_is_a_broker, ('SW36',), binding=MUTATION_CONTROLLER,
                  why='every command counts as a registered controller-side broker'),
         Mutation('SW36', 'ravel.controller.confine.launcher:linux_argv',
                  _planned_without_the_sandbox, ('SW36',), binding=MUTATION_CONTROLLER,
                  why='the authored script of a nested stage is planned without the OS sandbox'),
         Mutation('SW36', ('ravel.controller.confine.launcher:start', 'ravel.controller.confine:start'),
                  _started_without_the_wrapper, ('SW36',), binding=MUTATION_CONTROLLER,
                  why='the authored script of a nested stage is started without the OS sandbox'))


# --------------------------------------------------------------------------------------- SW38

def _never_called_for_the_launch_layer(original):
    """The launch layer is declared in the tripwire table but its check never runs."""
    return lambda layer: None if layer == 'authorized_popen' else original(layer)


@case('SW38', binding=CONTROLLER)
def test_SW38_a_launch_outside_a_substrate_node_trips_the_controller_mode_tripwire(nc):
    require_controller('confine')
    from ravel.workflow import agent_tripwire, graph_nodes, launch_authorization
    store, run_dir = controller_run(nc)
    (run_dir / 'outputs').mkdir()
    context = {'stage': 'fit', 'node_id': 'fit', 'kind': 'scientific-stage',
               'stage_spec': {'inputs': [], 'outputs': [str(run_dir / 'outputs')]}}
    popen = _Popen(nc.patch)

    def launch():
        return launch_authorization.authorized_popen(run_dir, 'full', LAUNCH, context=context, cwd=str(run_dir))

    nc.patch.setenv(agent_tripwire.ENV, '0')  # the environment asks for the tripwire to be off
    seen = len(agent_tripwire.OBSERVED)
    with agent_tripwire.controller_scope(store.run_id):
        # A launch made outside every substrate node: the tripwire raises, and the test asserts the check happened.
        _refused(launch, agent_tripwire.TripwireViolation, 'authorized_popen: no_substrate_context',
                 'a launch outside a substrate node')
        verdicts = agent_tripwire.OBSERVED[seen:]
        assert [(v['layer'], v['ok'], v['reason'], v['mode']) for v in verdicts] == [
            ('authorized_popen', False, 'no_substrate_context', 'block')], verdicts
        assert verdicts[0].get('requested_mode') == '0', 'the lower request is kept in the verdict, not honoured'
        assert popen.starts_of(*LAUNCH) == [] and launch_authorization._events(run_dir) == []
        # Positive control, same entry: inside a node whose kind may act at this layer the tripwire passes
        # (the verdict is recorded as ok) and the launch goes on to its next gate, which refuses it here.
        marker = graph_nodes.TRIPWIRE.set({'ravel_kind': 'effect', 'graph_id': 'nc-graph', 'role': None,
                                           'node': 'launch'})
        try:
            later = _refused(launch, ValueError, 'owned by the controller', 'the launch inside a substrate node')
        finally:
            graph_nodes.TRIPWIRE.reset(marker)
        assert not isinstance(later, agent_tripwire.TripwireViolation)
        assert [(v['layer'], v['ok']) for v in agent_tripwire.OBSERVED[seen:]] == [
            ('authorized_popen', False), ('authorized_popen', True)]
    assert popen.starts_of(*LAUNCH) == []


register(Mutation('SW38', 'ravel.workflow.agent_tripwire:check', _never_called_for_the_launch_layer, ('SW38',),
                  binding=MUTATION_CONTROLLER, why='the launch layer of the tripwire is declared but never checked'))


# --------------------------------------------------------------------------------------- SW40

@case('SW40', binding=CONTROLLER)
def test_SW40_a_worker_writes_no_cli_login_home_reaches_no_non_model_host_and_its_egress_is_labelled(nc):
    confine = require_controller('confine')
    sandbox_or_skip(nc)
    worker = InstalledWorker(nc)
    login = nc.root / 'claude-login'
    home = Sentinels(login, {'credentials.json': '{"fictional": "login state"}'})
    port = nc.effects.listener.port
    worker.scenario({'actions': [
        {'op': 'list'},
        {'op': 'native_write', 'path': str(login / 'planted.json'), 'text': 'forged'},
        {'op': 'native_write', 'path': str(login / 'credentials.json'), 'text': 'forged'},
        {'op': 'connect', 'port': port},
        {'op': 'call', 'name': 'ws_write', 'arguments': {'path': 'outputs/result.txt', 'content': 'fictional'}},
    ], 'final': FINAL})
    spec = worker.spec()
    receipt = worker.dispatch(spec)
    # The worker did try (its own account; the counters below are the oracle): two writes and one socket.
    attempts = [a['op'] for a in worker.adversary_log(spec)['log']]
    assert attempts.count('native_write') == 2 and attempts.count('connect') == 1, attempts
    # Positive control: the worker still did its admitted work through the broker.
    assert receipt['status'] == 'ok', receipt.get('failure')
    assert [o['path'] for o in receipt['credited_outputs']] == ['outputs/result.txt']
    # A socket to a host that is not the model endpoint is refused by the profile.
    assert nc.effects.listener.accepted == 0
    # The egress the profile does allow is labelled, never claimed to be the model endpoint alone.
    workspace = nc.path('probe-workspace', 'inputs', 'placeholder').parent.parent
    for name in ('outputs', 'scratch'):
        (workspace / name).mkdir(exist_ok=True)
    closed = confine.probe('worker', {'workspace': str(workspace), 'tools': ['read'], 'network': None})
    provider = confine.probe('worker', {'workspace': str(workspace), 'tools': ['read'], 'network': 'provider'})
    assert closed['egress_label'] == 'none'
    assert provider['egress_label'] in ('worker egress: any TCP 443 host',
                                        'worker egress: unrestricted (no port rules on this kernel)'), provider
    # NOT IMPLEMENTED (P05, with a one-line change in the CLI worker transport): the login directory is bound
    # read-write (the receipt says it is not owned), so the worker's writes land in the real directory.
    assert home.changes() == [], (
        f'NOT IMPLEMENTED: the worker wrote the real CLI login home {home.changes()}; it must get a private '
        'scratch copy')


register(Mutation('SW40', 'ravel.workflow.sandbox:egress', returns('none'), ('SW40',), binding=MUTATION_CONTROLLER,
                  why='the worker egress is reported as none while the profile allows provider traffic'))


# --------------------------------------------------------------------------------------- SW41

@case('SW41', binding=CONTROLLER)
def test_SW41_a_controller_run_launch_needs_the_controller_dispatch_though_no_policy_governs_the_run(nc):
    require_controller('confine')
    from ravel.workflow import launch_authorization, wms_policy
    store, run_dir = controller_run(nc)
    (run_dir / 'outputs').mkdir()
    context = {'stage': 'fit', 'node_id': 'fit', 'kind': 'scientific-stage',
               'stage_spec': {'inputs': [], 'outputs': [str(run_dir / 'outputs')]}}
    popen = _Popen(nc.patch)
    fragment = 'the absence of a workflow policy is not permission'
    assert wms_policy.locate(run_dir) is None, 'no policy or index governs this run directory'

    def launch():
        return launch_authorization.authorized_popen(run_dir, 'full', LAUNCH, context=context, cwd=str(run_dir))

    # Outside the controller's dispatch the launch is refused before anything is recorded or started ...
    from ravel.workflow import agent_tripwire, graph_nodes
    _refused(launch, agent_tripwire.TripwireViolation, 'controller launch requires an admitted substrate context',
             'the launch of a controller run outside its dispatch')
    _refused(lambda: wms_policy.require_custody(run_dir), ValueError, fragment, 'the custody check')
    assert popen.starts_of(*LAUNCH) == [] and launch_authorization._events(run_dir) == []
    assert store.scan(launch_authorization.STORE_KIND) == []
    # ... and a process that presents some other attempt's custody secret has no custody either.
    nc.patch.setenv('RAVEL_STAGE_CUSTODY', 'f' * 64)
    _refused(lambda: wms_policy.require_custody(run_dir), ValueError, fragment, 'a foreign custody secret')
    nc.patch.delenv('RAVEL_STAGE_CUSTODY')
    # Positive control, same entries: inside the controller's dispatch the custody check passes and the launch
    # goes on to its next gate (here the approval gate, which refuses a run with no approval).
    token = graph_nodes.TRIPWIRE.set({'ravel_kind': 'effect', 'graph_id': 'controller.step',
                                      'role': None, 'node': 'launch'})
    try:
        with wms_policy.controller_dispatch(run_dir):
            assert wms_policy.require_custody(run_dir) is None
            later = _refused(launch, ValueError, 'launch authorization refused', 'the launch inside the dispatch')
            assert fragment not in str(later)
    finally:
        graph_nodes.TRIPWIRE.reset(token)
    # A run the controller does not own, with no policy, keeps the 1.1.0 behaviour.
    legacy = nc.path('legacy-run', 'placeholder').parent
    assert wms_policy.require_custody(legacy) is None


register(Mutation('SW41', 'ravel.workflow.wms_policy:_controller_custody', returns(None), ('SW41',),
                  binding=MUTATION_CONTROLLER, why='the custody check lets a controller run pass for lack of a policy'))
