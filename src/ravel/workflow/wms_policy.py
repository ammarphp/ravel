"""Project policy that approved stages run only through the workflow manager.

A project declares the policy in ``<project>/workflow/policy.json``. A run dir is
governed when any ancestor policy requires it or any ancestor project index
lists it. A nearer policy cannot lift that requirement. An index lists a run by
the identity of its directory, whatever spelling the entry uses. Governance
files are read strictly: a duplicate key, a dangling link or a relative index
entry refuses. A ``workflow/index.json`` of another tool governs nothing. Direct runners refuse a
governed run dir. Only ``site_workflow.run_step`` lifts the refusal, through an
in-process dispatch context entered after its own verify. That context opens
only for the export the project index lists for the run, and only while
``ravel wms launch`` holds a live launch authorization that names the task and
that export. A record whose holder died, a Snakemake lock and an environment
variable authorize nothing. The authorized-launch boundary and the executable
payload entries call ``require_custody``: the step's process passes through the
context, and a worker it started passes while the step holds its dispatch grant. This is discipline, not a security boundary against
code that rewrites these functions.

A run the controller owns is stricter: absence of a workflow policy is not permission.
Its launches pass only inside the controller's own dispatch context (``controller_dispatch``)
or from a process that carries the confinement custody token of a running attempt of that
run. Every governed ``ravel wms launch`` also holds a launch capability: a secret its
executor's submit command presents (``CAPABILITY_ENV``) and whose digest the live launch
record keeps, so a facility submission outside a live governed launch submits nothing.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from .state_io import read_json

POLICY = 'workflow/policy.json'
INDEX = 'workflow/index.json'
PROJECT = 'workflow/project.json'
LIVE = 'workflow/.live'
ROUTE = '`ravel wms add --project <project> --rundir <rundir>` then `ravel wms launch --project <project> --task <task>`'

_DISPATCH = ContextVar('ravel_wms_dispatch', default=frozenset())
_CONTROLLER = ContextVar('ravel_controller_dispatch', default=frozenset())
CAPABILITY_ENV = 'RAVEL_WMS_CAPABILITY'
_HELD, _HELD_GUARD = set(), threading.Lock()


def _key(rundir):
    return str(Path(rundir).expanduser().absolute().resolve())


# Optional keys owned by the execution guard (``execution_guard``) and the software skill writer (``software``).
OPTIONAL = {'execution_guard', 'software'}


def validate(document):
    if (type(document) is not dict or not {'schema_version', 'wms_required', 'engine'} <= set(document)
            or set(document) - {'schema_version', 'wms_required', 'engine'} - OPTIONAL
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or type(document['wms_required']) is not bool or document['engine'] != 'snakemake'):
        raise ValueError('workflow policy requires {schema_version: 1, wms_required: bool, engine: "snakemake"}'
                         ' and optionally execution_guard: "strict" and software')
    if 'execution_guard' in document and document['execution_guard'] != 'strict':
        raise ValueError('workflow policy execution_guard must be "strict" when present')
    if 'software' in document and (type(document['software']) is not dict
                                   or set(document['software']) - {'python_packages', 'executables'}
                                   or not all(type(v) is list and all(isinstance(n, str) for n in v)
                                              for v in document['software'].values())):
        raise ValueError('workflow policy software lists python_packages and executables by name')
    return document


def _rows(index, project):
    """Task rows of a project index with canonical run dirs; None for another tool's file.

    ``project`` says a project or policy record sits beside the index. Such an
    index must be well formed. Without one, valid JSON that carries no ``tasks``
    list belongs to another tool and governs nothing.
    """
    document = read_json(index)
    tasks = document.get('tasks') if type(document) is dict else None
    if type(tasks) is not list:
        if project:
            raise ValueError('a project index requires {"tasks": [...]}')
        return None
    rows = []
    for row in tasks:
        if type(row) is not dict or ('rundir' not in row and project):
            raise ValueError('every index task must be an object with its run dir')
        if 'rundir' not in row:
            continue
        if type(row['rundir']) is not str or not Path(row['rundir']).is_absolute():
            raise ValueError('an index run dir must be an absolute path; a relative entry is refused, not ignored')
        rows.append({**row, 'rundir': _key(row['rundir'])})
    return rows


def _scan(rundir):
    """(directory, policy requires, index row of this run) for every ancestor that governs it.

    Every governance file on the whole path is read strictly, so a malformed one
    refuses wherever it sits. A dangling link is unreadable, not absent.
    """
    start = Path(_key(rundir))
    governors = []
    for directory in (start, *start.parents):
        policy, index = directory / POLICY, directory / INDEX
        try:
            source = policy
            requires = validate(read_json(policy))['wms_required'] if os.path.lexists(policy) else False
            source = index
            rows = (_rows(index, os.path.lexists(policy) or os.path.lexists(directory / PROJECT))
                    if os.path.lexists(index) else None)
            row = next((r for r in rows or () if r['rundir'] == str(start)), None)
        except (OSError, ValueError, AttributeError, TypeError, RuntimeError) as exc:
            raise ValueError(f'workflow governance file {source} is unreadable or malformed ({exc}); repair or '
                             'remove it: a malformed file refuses dispatch and never lifts the requirement') from exc
        if requires or row is not None:
            governors.append((directory, requires, row))
        # Continue even after finding a governor: malformed outer policies refuse.
    return governors


def locate(rundir):
    """Return the nearest governing project, validating policies on the whole path."""
    governors = _scan(rundir)
    return governors[0][0] if governors else None


def required(rundir):
    return locate(rundir) is not None


def _refusal(rundir, project):
    scoped_reason = (
        '; scoped runs are not workflow-manager tasks: run it outside the governed project, '
        "or set that project's policy to not require the workflow manager. "
        'An index entry still keeps the run governed'
        if not (Path(_key(rundir)) / 'inputs/science-plan.json').is_file() else '')
    return ValueError(f'run dir {_key(rundir)} is governed by the workflow-manager project {project / "workflow"} '
                      '(its policy requires the workflow manager or its index lists this run); '
                      f'approved stages run only through Snakemake: use {ROUTE}{scoped_reason}')


def require_dispatch(rundir):
    """Refuse direct dispatch of a governed run dir outside run-step."""
    project = locate(rundir)
    if project is None or _key(rundir) in _DISPATCH.get():
        return
    raise _refusal(rundir, project)


def _controller_custody(rundir):
    """None for a run the controller does not own; False when this process holds custody; else the refusal."""
    from ravel.controller.confine import runs
    owner = runs.owner_of(Path(_key(rundir)))
    if owner is None:
        return None
    key = _key(rundir)
    if any(Path(key).is_relative_to(entered) for entered in _CONTROLLER.get()):
        return False
    from ravel.controller.confine import custody
    if custody.for_run(owner[1]):
        return False
    return ValueError(f'run dir {key} is owned by the controller: a launch or executable payload of it runs only '
                      'inside the controller\'s dispatch, or confined under one of its running attempts; the '
                      'absence of a workflow policy is not permission')


@contextmanager
def controller_dispatch(rundir):
    """Entered by the controller around the launches of a controller-owned run."""
    token = _CONTROLLER.set(_CONTROLLER.get() | {_key(rundir)})
    try:
        yield
    finally:
        _CONTROLLER.reset(token)


def require_custody(rundir):
    """Refuse a process launch or an executable payload of a governed run outside its dispatched step.

    The step's own process holds the in-process context. A worker that the step
    started is another process: it has custody while the step holds its dispatch
    grant for this run dir, and loses it when the step ends or dies.
    """
    refusal = _controller_custody(rundir)
    if refusal is False:
        return
    if refusal is not None:
        raise refusal
    governors = _scan(rundir)
    key = _key(rundir)
    if not governors or key in _DISPATCH.get():
        return
    for project, _, _ in governors:
        for path in sorted((project / LIVE).glob(f'dispatch-{_digest(key)}-*.json')):
            record = _live(path)
            if type(record) is dict and record.get('rundir') == key:
                return
    raise _refusal(rundir, governors[0][0])


def _digest(key):
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _live(path):
    """The record at ``path`` while a live process holds its lock, else None."""
    with _HELD_GUARD:
        held = str(path) in _HELD
    try:
        with Path(path).open('rb') as stream:
            if not held:
                try:
                    fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError:
                    held = True
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)
            return json.loads(stream.read()) if held else None
    except (OSError, ValueError):
        return None


@contextmanager
def _hold(path, document):
    """Write a record and hold its lock for the block; a record whose lock is free is stale."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False).encode() + b'\n')
        stream.flush()
        with _HELD_GUARD:
            _HELD.add(str(path))
        try:
            yield path
        finally:
            with _HELD_GUARD:
                _HELD.discard(str(path))
            path.unlink(missing_ok=True)
            fcntl.flock(stream, fcntl.LOCK_UN)


@contextmanager
def launch_authorization(workflow, task, number, exports, *, capability=None, controller_run=None,
                         capability_scope=None, **governed):
    """Held by ``ravel wms launch`` while Snakemake runs.

    ``exports`` maps each task this launch may run (the target and the tasks it
    depends on) to its indexed export digest. run-step is admitted only while
    this record is held, so a Snakemake lock, an earlier launch or a record left
    by a launcher that died authorizes nothing.

    The launch's capability is exported to its executor in ``CAPABILITY_ENV`` while the
    record is held; the record keeps only its digest. A controller run passes the token
    it minted into its store (``confine.mint_capability``) as ``capability`` with its
    ``controller_run`` id. Alternatively ``capability_scope`` supplies an explicitly
    approved cumulative job count and resource maxima and this adapter mints/revokes
    through the binding RunStore. A controller-owned workflow never falls back to a
    local token. Trusted WMS script generation remains a prerequisite; scope alone is
    not approval, and an optional script digest pins exact generated contents.
    """
    import secrets
    from ravel.controller.confine import capability as capabilities, runs
    workflow = Path(workflow).resolve()
    owners = set()
    owner = runs.owner_of(workflow)
    if owner is not None:
        owners.add(owner[0])
    index = workflow / 'index.json'
    if os.path.lexists(index):
        for row in _rows(index, True):
            if row.get('id') in exports:
                owner = runs.owner_of(row['rundir'])
                if owner is not None:
                    owners.add(owner[0])
    if len(owners) > 1 or (owners and controller_run is not None and owners != {controller_run}):
        raise ValueError('a controller launch must name the controller run that owns its workflow tasks')
    if owners and controller_run is None:
        controller_run = next(iter(owners))
    if capability is not None and controller_run is None:
        raise ValueError('a controller launch capability needs its controller run id')
    if capability is not None and capability_scope is not None:
        raise ValueError('pass an existing capability or an approved capability_scope, not both')
    minted_store, launch_id = None, f'wms-{task}-{number:06d}'
    if controller_run is not None:
        if capability is None:
            if capability_scope is None:
                raise ValueError('a controller-owned workflow needs its controller capability or approved capability_scope')
            # No job-count or resource approval is inferred from concurrency or a profile.
            if not {'resource_maxima', 'max_jobs'} <= set(capability_scope):
                raise ValueError('controller capability_scope requires approved resource_maxima and cumulative max_jobs')
            scope = dict(capability_scope)
            if scope.get('workflow_dir', str(workflow)) != str(workflow):
                raise ValueError('controller capability_scope workflow differs from this launch')
            if 'tasks' in scope and not set(scope['tasks']) <= set(exports):
                raise ValueError('controller capability_scope tasks exceed this launch')
            scope.update(workflow_dir=str(workflow), tasks=scope.get('tasks', sorted(exports)))
            pin = governed.get('site_profile')
            if pin is not None:
                if scope.get('profile_sha256', pin['sha256']) != pin['sha256']:
                    raise ValueError('controller capability_scope profile differs from this launch')
                scope['profile_sha256'] = pin['sha256']
            minted_store = runs.store(controller_run)
            capability = capabilities.mint_capability(minted_store, launch_id, scope)
        match = capabilities.TOKEN.fullmatch(capability) if isinstance(capability, str) else None
        if match is None or match.group(1) != controller_run:
            raise ValueError('controller launch requires a capability for its own run')
    elif capability_scope is not None:
        raise ValueError('an approved capability_scope needs a controller run')
    token = capability or ('rwl1.' + secrets.token_urlsafe(32))
    document = {'schema_version': 1, 'kind': 'launch', 'task': task, 'launch': number, 'pid': os.getpid(),
                'exports': dict(exports), 'capability_sha256': capabilities.digest(token), **governed}
    if controller_run is not None:
        document['controller_run'] = controller_run
    previous = os.environ.get(CAPABILITY_ENV)
    try:
        with _hold(workflow / LIVE.split('/', 1)[1] / f'launch-{task}-{number:06d}.json', document) as path:
            os.environ[CAPABILITY_ENV] = token
            try:
                yield path
            finally:
                if previous is None:
                    os.environ.pop(CAPABILITY_ENV, None)
                else:
                    os.environ[CAPABILITY_ENV] = previous
    finally:
        if minted_store is not None:
            capabilities.revoke_capability(minted_store, launch_id)


def _ancestors(pid=None):
    """This process and its ancestors up to init, from /proc or the system ``ps``; never the caller's PATH."""
    import shutil
    import subprocess
    pid = os.getpid() if pid is None else pid
    chain, parents = [], None
    for _ in range(512):
        chain.append(pid)
        if pid <= 1:
            break
        try:
            with open(f'/proc/{pid}/stat', encoding='utf-8') as stream:
                parent = int(stream.read().rsplit(')', 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            if parents is None:
                ps = shutil.which('ps', path='/bin:/usr/bin')
                if ps is None:
                    raise ValueError('process ancestry is unavailable; nothing was submitted')
                done = subprocess.run([ps, '-A', '-o', 'pid=', '-o', 'ppid='], capture_output=True, text=True,
                                      timeout=20, check=False, stdin=subprocess.DEVNULL)
                if done.returncode:
                    raise ValueError('process ancestry is unavailable; nothing was submitted')
                parents = {int(a): int(b) for a, b in (line.split() for line in done.stdout.splitlines() if line.strip())}
            parent = parents.get(pid)
        if parent is None or parent == pid:
            break
        pid = parent
    return chain


def governed_submission(workflow):
    """The live governed launch of ``workflow`` whose capability this process presents, else refuse.

    The process must carry the launch's capability (``CAPABILITY_ENV``) and descend from the
    process that holds the launch record, as the executor the launch starts does.
    """
    from ravel.controller.confine.capability import digest as capability_digest
    token = os.environ.get(CAPABILITY_ENV)
    if not token:
        raise ValueError('no launch capability was presented: a facility submission runs only from the executor '
                         'of a live governed `ravel wms launch`; nothing was submitted')
    expected = capability_digest(token)
    live = Path(workflow) / LIVE.split('/', 1)[1]
    ancestry = set(_ancestors())
    for path in sorted(live.glob('launch-*.json')) if live.is_dir() else ():
        record = _live(path)
        if (type(record) is dict and record.get('kind') == 'launch' and record.get('capability_sha256') == expected
                and record.get('pid') in ancestry):
            return record
    raise ValueError('the presented capability belongs to no live governed launch of this workflow that this '
                     'process descends from; nothing was submitted')


def _admit(rundir, export, export_sha256, task):
    """Project whose index lists this export of a governed run, inside a live launch of it.

    None for an ungoverned run, which needs no workflow manager.
    """
    governors = _scan(rundir)
    if not governors:
        return None
    key, manifest = _key(rundir), os.path.realpath(export)
    for project, _, row in governors:
        listed = row.get('export') if row is not None else None
        if (type(listed) is dict and row.get('id') == task and type(listed.get('path')) is str
                and os.path.realpath(listed['path']) == manifest and listed.get('sha256') == export_sha256):
            break
    else:
        raise ValueError(f'run dir {key} is governed by the workflow-manager project {governors[0][0] / "workflow"}, '
                         f'whose index does not list this export ({manifest}) for task {task}; only the export '
                         f'written by `ravel wms add` is dispatched: use {ROUTE}')
    for path in sorted((project / LIVE).glob('launch-*.json')):
        record = _live(path)
        if type(record) is dict and type(record.get('exports')) is dict and record['exports'].get(task) == export_sha256:
            return project
    raise ValueError(f'run-step of governed run dir {key} runs only inside a live `ravel wms launch` of task {task} '
                     'or of a task that depends on it; a Snakemake lock, an earlier launch or a step run by hand '
                     f'does not authorize it: use {ROUTE}')


@contextmanager
def _dispatch_context(rundir, export, export_sha256, task):
    """Entered only by site_workflow.run_step after its own verify.

    A governed run enters only with its indexed export inside a live launch, and
    the step then holds a dispatch grant that its child workers can check.
    """
    project = _admit(rundir, export, export_sha256, task)
    key = _key(rundir)
    token = _DISPATCH.set(_DISPATCH.get() | {key})
    try:
        if project is None:
            yield
        else:
            name = f'dispatch-{_digest(key)}-{os.getpid()}-{time.time_ns()}.json'
            with _hold(project / LIVE / name, {'schema_version': 1, 'kind': 'dispatch', 'rundir': key, 'task': task,
                                              'export_sha256': export_sha256, 'pid': os.getpid()}):
                yield
    finally:
        _DISPATCH.reset(token)
