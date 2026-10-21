"""The confined launcher: one API for every execution of authored code or a domain operation.

``popen(spec)`` starts the approved argv under the host's OS sandbox and returns the process;
the journaled command stays the approved argv because the wrapper is added at ``Popen`` time.
A launch spec is a JSON-safe object:

    {"argv": [...],                    # the approved command
     "env": {...},                     # the plan's environment capsule (scrubbed again here)
     "reads": [...], "writes": [...],  # committed inputs (read only) and declared outputs
     "limits": {"cpus": 1, "wall_seconds": 600},
     "backend": "auto" | "bwrap" | "sandbox-exec",
     "cwd": ..., "run_dir": ..., "stage": ..., "attempt_dir": ...,
     "withheld": [...], "channels": [...], "input_digests": {path: sha256},
     "controller": {"run_id": ..., "launch_id": ...}}

The sandbox reads the system runtime, the interpreter, RAVEL's installation and the toolchain
prefix read only, plus the declared reads; nothing else (no home, no store, no other
workspace, no withheld source). It writes only the declared outputs, the stage's work area
``work/<stage>`` and a private scratch directory. A declared output that does not exist yet is
created inside its nearest existing directory; anything else created there is quarantined
when ``finish`` runs, and on Linux that directory is a private staging copy from which only
declared outputs are adopted. Governed run records, RAVEL's code, settings, custody and
credentials are never writable; a declared output that overlaps one is refused before
anything starts. The network is closed: outward Unix sockets reach only declared channels and
the launch's own writable paths. Domain launches cannot declare TCP access; model-worker
egress belongs to the separate worker sandbox.

Refusal precedes every effect. Without a qualified sandbox a launch holds (``LaunchHeld``)
unless the operator's own configuration sets ``allow_unconfined: true``; it then runs with
the scrubbed environment and the record says ``UNCONFINED EXECUTION``. A sandbox that fails
its qualification probe always holds.

Measured limitation: on macOS a confined process can still read the environment of some
same-user processes through ``KERN_PROCARGS2``; no profile rule gates it. Linux launches have
their own PID namespace.

Legacy ``memory_mib`` limits per-process address space on Linux only; it does not
limit aggregate RSS. Aggregate ``aggregate_memory_mib`` (launch-tree RSS), ``processes`` (launch-tree count), and
``disk_mib`` (cumulative retained run/output/staging/scratch bytes, including failed
attempts and input copies) are recognized but unsupported: requesting any holds
before materialization or execution. There is no qualified aggregate sampler,
filesystem headroom reservation, or delegated kernel resource boundary here.
An operation-specific sampler does not qualify the generic launcher. Every
ordinary launch is labelled RESOURCE PROTECTION INCOMPLETE, including when no
aggregate limits were requested. OS confinement is not aggregate resource safety.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading

from ravel.workflow import sandbox as worker_sandbox
from ravel.controller.authority import issuer

from . import environment as envmod
from . import locations as loc
from . import runs
from .resource_mechanisms import ResourceMechanism, resource_scopes

SCHEMA_VERSION = 1
CONFINED, UNCONFINED = 'confined', 'unconfined'
UNCONFINED_LABEL = 'UNCONFINED EXECUTION'
RESOURCE_LABEL = 'RESOURCE PROTECTION INCOMPLETE'
BACKENDS = {'macos': 'sandbox-exec', 'linux': 'bwrap'}
SPEC_KEYS = frozenset({'argv', 'env', 'reads', 'writes', 'limits', 'backend', 'cwd', 'run_dir', 'stage',
                       'attempt_dir', 'withheld', 'channels', 'tcp_ports', 'input_digests', 'controller', 'label',
                       'issuer_protected'})
LIMIT_KEYS = frozenset({'cpus', 'memory_mib', 'aggregate_memory_mib', 'processes', 'disk_mib', 'wall_seconds'})
AGGREGATE_LIMIT_KEYS = frozenset({'aggregate_memory_mib', 'processes', 'disk_mib'})
MAX_STAGED_ENTRIES = 4096
# Linux system calls a confined launch never needs: the kernel keyrings hold credentials, and
# io_uring and the second x86_64 table can carry requests past a filter.
LINUX_KEYRING_SYSCALLS = {'x86_64': (248, 249, 250), 'aarch64': (217, 218, 219)}
LINUX_SHIM = (
    'import ctypes,json,os,resource,struct,sys\n'
    'rows=json.loads(sys.argv[1]);limits=json.loads(sys.argv[2]);argv=sys.argv[3:]\n'
    'libc=ctypes.CDLL(None,use_errno=True);word=ctypes.c_ulong;call=libc.syscall;call.restype=ctypes.c_long\n'
    'def refused(what):raise OSError(ctypes.get_errno(),"the launch "+what+" was refused")\n'
    'if limits.get("cpu_set"):os.sched_setaffinity(0,limits["cpu_set"])\n'
    'if limits.get("memory_bytes"):resource.setrlimit(resource.RLIMIT_AS,(limits["memory_bytes"],)*2)\n'
    # PR_SET_NO_NEW_PRIVS; both restrictions below need it.
    'if libc.prctl(38,word(1),word(0),word(0),word(0)):refused("privilege lock")\n'
    'ports=limits.get("tcp_ports") or []\n'
    'if ports:\n'
    # A Landlock rule set handling TCP bind and connect, with one connect rule per declared port.
    ' attr=ctypes.create_string_buffer(struct.pack("QQ",0,3),16)\n'
    ' ruleset=call(word(444),attr,ctypes.c_size_t(16),ctypes.c_uint(0))\n'
    ' if ruleset<0:refused("port rule set")\n'
    ' for port in ports:\n'
    '  rule=ctypes.create_string_buffer(struct.pack("QQ",2,port),16)\n'
    '  if call(word(445),ctypes.c_int(ruleset),ctypes.c_int(2),rule,ctypes.c_uint(0)):refused("port rule")\n'
    ' if call(word(446),ctypes.c_int(ruleset),ctypes.c_uint(0)):refused("port rule")\n'
    ' os.close(ruleset)\n'
    'blob=b"".join(struct.pack("HBBI",*row) for row in rows)\n'
    'buffer=ctypes.create_string_buffer(blob,len(blob))\n'
    'class Program(ctypes.Structure):_fields_=[("len",ctypes.c_ushort),("filter",ctypes.c_void_p)]\n'
    'program=Program(len(rows),ctypes.addressof(buffer))\n'
    # PR_SET_SECCOMP with SECCOMP_MODE_FILTER.
    'if libc.prctl(22,word(2),ctypes.byref(program),word(0),word(0)):refused("system-call filter")\n'
    'os.execvp(argv[0],argv)\n')
_QUALIFIED = {}
_QUALIFY_LOCK = threading.RLock()


class ConfinementRefused(ValueError):
    """A launch was refused before any effect: no event, directory or process exists."""
    launch_refused = True
    refused_by = 'confinement'


class LaunchHeld(ConfinementRefused):
    """A typed hold: the launch cannot run confined here; ``reason`` says why and what releases it."""

    def __init__(self, reason, detail):
        super().__init__(f'launch held ({reason}): {detail}; nothing was started')
        self.reason, self.detail = reason, detail


@dataclass
class Plan:
    kind: str
    record: dict
    argv: list
    backend: str | None = None
    cwd: str | None = None
    env: dict = field(default_factory=dict)
    run_dir: Path | None = None
    stage: str | None = None
    attempt_dir: Path | None = None
    outputs: list = field(default_factory=list)
    existing_outputs: list = field(default_factory=list)
    parents: list = field(default_factory=list)
    work_area: Path | None = None
    reads: list = field(default_factory=list)
    hidden: list = field(default_factory=list)
    unwritable: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    channels: list = field(default_factory=list)
    tcp_ports: list = field(default_factory=list)
    limits: dict = field(default_factory=dict)
    input_digests: dict = field(default_factory=dict)
    input_copies: dict = field(default_factory=dict)
    input_directory: Path | None = None
    input_roots: list = field(default_factory=list)
    watchdog: object | None = None
    new_session: bool = False
    custody_token: str | None = None
    scratch: Path | None = None
    staging: dict = field(default_factory=dict)
    listings: dict = field(default_factory=dict)
    created: list = field(default_factory=list)
    finished: dict | None = None


def custody_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _refuse(text):
    raise ConfinementRefused(text + '; nothing was started')


def _strings(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) or not v or '\0' in v for v in value):
        _refuse(f'launch {label} must be a list of nonempty strings')
    return list(value)


SYSTEM_ALIASES = ('/tmp', '/var', '/etc') if sys.platform == 'darwin' else ()


def _absolute(value, label):
    """The canonical form of an absolute path; protection checks then act on the real location."""
    if not os.path.isabs(value):
        _refuse(f'launch {label} {value!r} must be an absolute path')
    return loc.real(value)


def _write_path(value):
    """A declared output outside a run: absolute, and no symbolic link on the way except a system alias."""
    if not os.path.isabs(value):
        _refuse(f'launch write {value!r} must be an absolute path')
    path = Path(os.path.abspath(value))
    for candidate in (path, *path.parents):
        if candidate.is_symlink() and str(candidate) not in SYSTEM_ALIASES:
            _refuse(f'declared output {value} traverses the symbolic link {candidate}')
    return loc.real(path)


def machine_grant():
    """The live machine grant: the CPUs this controller process may use (``machine_lease.cpu_grant``)."""
    from ravel.workflow import machine_lease
    return machine_lease.cpu_grant()



def _require_supported_limits(limits):
    """Fail closed rather than project per-process controls as aggregate guarantees.

    This check also runs at start: callers can retain and mutate a prepared Plan.
    Neither an unconfined opt-in nor an available ps/proc sampler qualifies an
    aggregate boundary (detached descendants, scratch and retained copies included).
    """
    unsupported = sorted(AGGREGATE_LIMIT_KEYS.intersection(limits))
    if unsupported:
        raise LaunchHeld('resource_limit_unsupported',
            'generic local launch cannot enforce aggregate ' + ', '.join(unsupported) +
            '; use a separately qualified execution adapter covering the complete launch tree '
            'and retained run/output/staging/scratch bytes (including failed attempts and '
            'pre-materialization input copies), with receipt headroom on every filesystem; '
            'no aggregate sampling or hard bound is provided by this launcher')


def _require_operator_retention(run_dir, controller=None):
    """A finite operator storage requirement cannot be bypassed by a bare spec."""
    owner = runs.owner_of(run_dir) if run_dir is not None else None
    run_id = owner[0] if owner else (controller or {}).get('run_id')
    if run_id:
        from ravel.controller.authority import effective_bounds
        budgets = effective_bounds(runs.store(run_id)).get('budgets') or {}
    else:
        budgets = runs.operator_settings().get('budgets') or {}
    if budgets.get('retained_disk_bytes') is not None:
        raise LaunchHeld('resource_limit_unsupported',
                         'generic local launch cannot enforce the operator retained_disk_bytes ceiling; '
                         'select a separately qualified adapter covering retained copies and receipt headroom')


def _limits(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - LIMIT_KEYS:
        _refuse('launch limits allow only ' + ', '.join(sorted(LIMIT_KEYS)))
    for key, item in value.items():
        if key == 'wall_seconds':
            if type(item) not in (int, float) or not 0 < item < float('inf'):
                _refuse('launch wall_seconds must be positive and finite')
        elif type(item) is not int or item <= 0:
            _refuse(f'launch {key} must be a positive integer')
    limits = dict(value)
    if 'cpus' in limits:
        grant = machine_grant()
        if limits['cpus'] > len(grant):
            _refuse(f'the launch asks for {limits["cpus"]} CPUs; the live machine grant has {len(grant)}')
        limits['cpu_set'] = grant[:limits['cpus']]
    return limits


def _select(requested):
    available = worker_sandbox.available()
    if requested in (None, 'auto'):
        return available
    names = {v: k for k, v in BACKENDS.items()}
    if requested == 'oci-local':
        _refuse('container launches run through the oci-local execution backend, which confines them itself')
    if requested not in names:
        _refuse(f'unknown launch backend {requested!r}')
    if names[requested] != available:
        raise LaunchHeld('backend_unavailable', f'{requested} is not available on this host')
    return available


def _hold_or_unconfined(reason, detail):
    if not runs.allow_unconfined():
        raise LaunchHeld(reason, detail + '; the operator may set allow_unconfined in the operator configuration')
    return None


def require_issuer_mounts(backend, *, reads=(), writes=()):
    """Validate final host-side mounts, including adapter/runtime grants, before effects."""
    try:
        return Path(issuer.require_confined_spec({'backend': backend,
                     'reads': [str(p) for p in reads], 'writes': [str(p) for p in writes]}))
    except ValueError as exc:
        _refuse(str(exc))


def _issuer_plan(plan):
    """Recheck mutable plans at the last boundary, including implicit namespace mounts."""
    if plan.kind != CONFINED:
        if plan.record.get('issuer_protection') or plan.record.get('controller') or (
                plan.run_dir is not None and runs.owner_of(plan.run_dir)):
            require_issuer_mounts(None)
        return
    extra = [Path('/proc'), Path('/dev')] if plan.backend == 'linux' else [Path('/dev/fd')]
    protected = require_issuer_mounts(BACKENDS.get(plan.backend),
        reads=[*plan.reads, *plan.channels, *plan.input_copies.values(), *extra],
        writes=[*plan.outputs, *plan.parents, *plan.staging.values(),
                *([plan.work_area] if plan.work_area else []), *([plan.scratch] if plan.scratch else [])])
    plan.hidden = loc.depth_sorted([*plan.hidden, protected])
    plan.unwritable = loc.depth_sorted([*plan.unwritable, protected])
    plan.record['issuer_protection'] = issuer.receipt()


def _issuer_descriptors(kwargs):
    """Standard streams can also be pre-opened authority files; never inherit those."""
    protected = loc.issuer_root()
    for name, default in (('stdin', 0), ('stdout', 1), ('stderr', 2)):
        stream = kwargs.get(name)
        fd = default if stream is None else stream if isinstance(stream, int) else stream.fileno()
        if fd < 0:
            continue  # Popen creates a pipe or opens its own null device.
        try:
            info = os.fstat(fd)
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                continue
            if sys.platform.startswith('linux'):
                path = Path(os.readlink(f'/proc/self/fd/{fd}'))
            elif sys.platform == 'darwin':
                import fcntl
                path = Path(os.fsdecode(fcntl.fcntl(fd, 50, bytes(1024))).split('\0', 1)[0])
            else:
                _refuse('cannot validate inherited file descriptors on this backend')
            if loc.overlaps(loc.real(path), [protected]):
                _refuse('an inherited descriptor exposes the operator issuer')
        except OSError as exc:
            _refuse(f'cannot validate inherited descriptor: {exc}')


def prepare(spec):
    """Check a launch spec and plan its confinement; nothing is created and nothing starts."""
    from ravel.workflow import execution
    if not isinstance(spec, dict) or set(spec) - SPEC_KEYS:
        _refuse('a launch spec is an object with ' + ', '.join(sorted(SPEC_KEYS)))
    argv = _strings(spec.get('argv'), 'argv')
    if not argv:
        _refuse('a launch needs its approved argv')
    limits = _limits(spec.get('limits'))
    _require_supported_limits(limits)
    capsule = spec['env'] if spec.get('env') is not None else envmod.capsule_from(dict(os.environ))
    try:
        env, removed = envmod.scrub(capsule)
    except ValueError as exc:
        _refuse(str(exc))
    run_dir = _absolute(spec['run_dir'], 'run_dir') if spec.get('run_dir') else None
    _require_operator_retention(run_dir, spec.get('controller'))
    stage = spec.get('stage')
    if stage is not None and (type(stage) is not str or not execution.NAME.fullmatch(stage)):
        _refuse('launch stage must be a stage name')
    homes = loc.account_homes()
    unreadable = loc.depth_sorted(loc.custody_roots() + loc.credential_paths())
    installation = loc.installation_roots()
    withheld = [_absolute(p, 'withheld path') for p in _strings(spec.get('withheld'), 'withheld')]
    outputs = []
    for value in _strings(spec.get('writes'), 'writes'):
        try:
            path = (execution.resolve_path(run_dir, value, output=True) if run_dir is not None
                    else _write_path(value))
        except ValueError as exc:
            _refuse(str(exc))
        if run_dir is not None and loc.governed_output(run_dir, path):
            _refuse(f'declared output {path} overlaps a governed run record')
        if loc.overlaps(path, installation + unreadable) or any(h.is_relative_to(path) for h in homes):
            _refuse(f'declared output {path} overlaps RAVEL code, the toolchain, a home, custody or a credential store')
        if loc.overlaps(path, withheld):
            _refuse(f'declared output {path} overlaps a withheld source')
        outputs.append(path)
    reads = []
    for value in _strings(spec.get('reads'), 'reads'):
        path = _absolute(value, 'read')
        if not path.exists():
            _refuse(f'declared read {path} does not exist')
        if any(h.is_relative_to(path) for h in homes) or loc.within(path, unreadable):
            _refuse(f'declared read {path} would expose an account home, custody or a credential store')
        reads.append(path)
    digests = spec.get('input_digests') or {}
    if not isinstance(digests, dict):
        _refuse('input_digests maps committed input paths to sha256')
    for value, expected in sorted(digests.items()):
        path = _absolute(value, 'committed input')
        if not path.is_file() or not loc.within(path, reads) or not isinstance(expected, str):
            _refuse(f'committed input {path} is not a declared, readable file')
        if execution.file_hash(path) != expected:
            _refuse(f'committed input {path} changed after approval')
    ports = spec.get('tcp_ports') or []
    if not isinstance(ports, list) or any(type(p) is not int or not 0 < p < 65536 for p in ports):
        _refuse('declared TCP ports must be port numbers')
    if ports:
        _refuse('domain launches have no network; acquisition needs its governed operation')
    channels = [_absolute(p, 'channel') for p in _strings(spec.get('channels'), 'channels')]
    cwd = spec.get('cwd')
    cwd = str(_absolute(cwd, 'working directory')) if cwd else None
    record = {'schema_version': SCHEMA_VERSION, 'stage': stage, 'label': spec.get('label'),
              'argv_sha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest(),
              'environment_names': sorted(env), 'removed_environment_names': removed,
              'controller': spec.get('controller'),
              'resource_enforcement': _resource_enforcement()}
    kind = _select(spec.get('backend'))
    if kind is not None:
        try:
            qualification = qualify(kind)
        except worker_sandbox.SandboxUnavailable as exc:
            qualification, kind = {'unavailable': str(exc)}, _hold_or_unconfined('sandbox_unavailable', str(exc))
        except worker_sandbox.SandboxProbeFailed as exc:
            raise LaunchHeld('sandbox_unqualified', str(exc)) from exc
    else:
        qualification = None
        _hold_or_unconfined('sandbox_unavailable', 'no operating-system sandbox (sandbox-exec or bwrap) on this host')
    unsupported = [name for name, mechanism in _enforced(kind, limits).items() if mechanism is False]
    if unsupported:
        raise LaunchHeld('resource_limit_unsupported', 'this backend cannot enforce ' + ', '.join(unsupported) +
                         '; use a separately qualified execution adapter that enforces these resources')
    if kind is None:
        if (spec.get('issuer_protected') is not False and spec.get('issuer_protected') is not None
                or spec.get('controller') or run_dir is not None and runs.owner_of(run_dir)):
            require_issuer_mounts(None)
        env, _ = envmod.launch_environment(capsule)
        record.update(kind=UNCONFINED, label_text=UNCONFINED_LABEL, backend=None, qualification=qualification,
                      reason='no qualified sandbox; the operator configuration allows unconfined execution',
                      architecture_complete=False,
                      limits={k: v for k, v in limits.items() if k != 'cpu_set'},
                      limits_enforced=_enforced(None, limits),
                      limit_scopes=resource_scopes(_enforced(None, limits)))
        return Plan(UNCONFINED, record, argv, cwd=cwd, env=env, run_dir=run_dir, stage=stage, outputs=outputs,
                    limits=limits, input_digests={str(_absolute(p, 'committed input')): h for p, h in digests.items()})
    if ports and kind == 'linux' and not worker_sandbox.linux_port_rules():
        raise LaunchHeld('tcp_ports_unsupported', 'declared TCP ports need Landlock port rules, which this kernel lacks')
    existing = [p for p in outputs if p.exists()]
    for path in existing:
        entries = [path, *path.rglob('*')] if path.is_dir() else [path]
        if any(p.is_symlink() or (p.is_file() and p.stat().st_nlink != 1) for p in entries):
            _refuse(f'declared output {path} contains symbolic or hard links')
    parents = loc.depth_sorted(_nearest_existing(p, run_dir) for p in outputs if not p.exists())
    for parent in parents:
        if run_dir is not None and parent != run_dir and loc.governed_output(run_dir, parent):
            _refuse(f'the directory {parent} that would receive a new output holds governed records')
        if loc.overlaps(parent, installation + unreadable) or parent in homes:
            _refuse(f'the directory {parent} that would receive a new output is protected')
    work = None
    if run_dir is not None and stage is not None and not loc.within(run_dir / 'work' / stage, outputs):
        work = run_dir / 'work' / stage
        if (run_dir / 'work').is_symlink() or work.is_symlink():
            _refuse('the stage work area may not be a symbolic link')
    roots = [*loc.system_roots(), *loc.interpreter_roots(), loc.package_root(),
             *loc.executable_roots(argv[0], env.get('PATH')), *reads]
    toolchain = loc.toolchain_root()
    if toolchain is not None:
        roots.append(toolchain)
    if cwd and Path(cwd) != run_dir and not loc.within(Path(cwd), [*roots, *outputs, *parents]):
        _refuse('the working directory must be within declared reads or outputs')
    # A root that would expose a home whole, or lies in custody or a credential store, is dropped.
    roots = [r for r in roots if not any(h.is_relative_to(r) for h in homes) and not loc.within(r, unreadable)]
    from .brokers import module_invocation
    # Isolated module commands import the same installed package. Normalize only
    # this visibility query; the approved argv and controller-side broker rules stay intact.
    package_argv = [argv[0], *argv[2:]] if len(argv) >= 4 and argv[1:3] == ['-I', '-m'] else argv
    package_hidden = [] if module_invocation(package_argv) else [loc.package_root() / 'ravel']
    plan = Plan(CONFINED, record, argv, backend=kind, cwd=cwd, env=env, run_dir=run_dir, stage=stage,
                attempt_dir=_absolute(spec['attempt_dir'], 'attempt_dir') if spec.get('attempt_dir') else None,
                outputs=outputs, existing_outputs=existing, parents=parents, work_area=work,
                reads=loc.outermost(roots), hidden=[p for p in unreadable if any(p.is_relative_to(r) for r in roots)] + package_hidden,
                unwritable=loc.depth_sorted([*(loc.governed_paths(run_dir) if run_dir is not None else []),
                                             *installation, *unreadable]),
                withheld=withheld, agents=loc.agent_programs(env), channels=channels, tcp_ports=list(ports),
                limits=limits, input_digests={str(_absolute(p, 'committed input')): h for p, h in digests.items()},
                input_roots=reads,
                custody_token=secrets.token_hex(32))
    record.update(kind=CONFINED, backend=BACKENDS[kind], qualification=qualification,
                  declared_outputs=[str(p) for p in outputs], writable=[str(p) for p in existing],
                  new_output_directories=[str(p) for p in parents],
                  work_area=str(work) if work is not None else None,
                  read_roots=[str(p) for p in plan.reads], withheld=[str(p) for p in withheld],
                  agent_programs_refused=[str(p) for p in plan.agents],
                  network=({'tcp_ports': sorted(ports), 'udp': 'unfiltered' if kind == 'linux' else 'none'}
                           if ports else 'none'),
                  channels=[str(p) for p in channels],
                  limits={k: v for k, v in limits.items() if k != 'cpu_set'},
                  limits_enforced=_enforced(kind, limits),
                  limit_scopes=resource_scopes(_enforced(kind, limits)),
                  custody_sha256=custody_digest(plan.custody_token),
                  limitations=(['macos-process-arguments-readable', 'macos-memory-not-limited']
                               if kind == 'macos' else []))
    _issuer_plan(plan)
    return plan


def _resource_enforcement():
    return {'schema_version': 1, 'status': 'partial', 'label': RESOURCE_LABEL,
            'aggregate_memory_mib': 'unsupported', 'processes': 'unsupported',
            'disk_mib': 'unsupported', 'aggregate_sampling': False,
            'filesystem_receipt_headroom': 'not reserved',
            'memory_mib_scope': 'per-process address space only on Linux; not aggregate RSS',
            'reason': 'generic_backend_has_no_aggregate_boundary_or_headroom_reservation',
            'required_action': 'select a separately qualified adapter for each required guarantee'}


def _enforced(kind, limits):
    enforced = {'wall_seconds': ResourceMechanism.CONTROLLER_WATCHDOG.value} if 'wall_seconds' in limits else {}
    if 'cpus' in limits:
        enforced['cpus'] = (ResourceMechanism.LINUX_CPU_AFFINITY.value if kind == 'linux' else
                            ResourceMechanism.COOPERATIVE_THREAD_ENVIRONMENT.value if kind == 'macos' else False)
    if 'memory_mib' in limits:
        enforced['memory_mib'] = ResourceMechanism.LINUX_RLIMIT_AS.value if kind == 'linux' else False
    for name in sorted(AGGREGATE_LIMIT_KEYS.intersection(limits)):
        enforced[name] = False
    return enforced


def _nearest_existing(path, run_dir):
    current = path.parent
    while not current.exists():
        if (run_dir is not None and (current == run_dir or not current.is_relative_to(run_dir))) or current == current.parent:
            _refuse(f'output {path} has no existing directory to be created in')
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        _refuse(f'output {path} lies under {current}, which is not an ordinary directory')
    return current


# ---------------------------------------------------------------- macOS profile
def _q(path):
    return worker_sandbox.quote(str(path))


def _regex(text):
    """An SBPL regex literal; ``#"..."`` is raw (measured: a doubled backslash no longer matches)."""
    if '"' in text:
        _refuse('a protected path containing a double quote cannot be written into the sandbox profile')
    return '#"' + text + '"'


def _protected_entries(directory, keep):
    """Existing entries of ``directory`` a launch may not write, recursing into ancestors of ``keep``."""
    found = []
    try:
        entries = sorted(Path(directory).iterdir())
    except OSError:
        return found
    if len(entries) > MAX_STAGED_ENTRIES:
        _refuse(f'{directory} holds more than {MAX_STAGED_ENTRIES} entries; declare a dedicated output directory')
    for entry in entries:
        if entry in keep:
            continue
        if any(k.is_relative_to(entry) for k in keep) and entry.is_dir() and not entry.is_symlink():
            found += _protected_entries(entry, keep)
            continue
        found.append(entry)
    return found


def _writable(plan):
    return [*plan.existing_outputs, *([plan.work_area] if plan.work_area else []), plan.scratch]


def macos_profile(plan):
    _issuer_plan(plan)
    writable = _writable(plan)
    readable = loc.outermost([*plan.reads, *writable, *plan.outputs])
    lines = ['(version 1)', '(deny default)', '(allow process-exec)', '(allow process-fork)',
             '(allow signal (target self) (target pgrp) (target children))', '(allow sysctl-read)',
             '(allow ipc-posix-sem)', '(allow ipc-posix-shm)',
             '(allow mach-lookup (global-name "com.apple.system.opendirectoryd.libinfo")'
             ' (global-name "com.apple.system.opendirectoryd.membership"))',
             '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/zero") (literal "/dev/random")'
             ' (literal "/dev/urandom") (literal "/dev/dtracehelper") (subpath "/dev/fd"))',
             '(allow file-read-metadata (literal "/dev") (literal "/etc") (literal "/tmp") (literal "/var"))',
             '(allow file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/dtracehelper")'
             ' (subpath "/dev/fd"))',
             '(allow file-ioctl (literal "/dev/null") (literal "/dev/zero") (literal "/dev/dtracehelper"))']
    lines += ['(allow file-read* (subpath ' + _q(p) + '))' for p in readable]
    anchors = [Path(plan.cwd)] if plan.cwd else []
    ancestors = sorted({str(a) for p in [*readable, *plan.channels, *anchors] for a in (p, *p.parents)})
    if ancestors:
        lines.append('(allow file-read-metadata ' + ' '.join('(literal ' + _q(a) + ')' for a in ancestors) + ')')
    # A missing leaf does not make its whole parent writable. Only directories on the
    # declared output path may be created; siblings stay denied by default.
    for output in plan.outputs:
        lines.append('(allow file-write* (subpath ' + _q(output) + '))')
        for parent in output.parents:
            if parent in plan.parents:
                break
            lines.append('(allow file-write-create (literal ' + _q(parent) + '))')
    if plan.work_area is not None:
        lines.append('(allow file-write-create (literal ' + _q(plan.work_area.parent) + '))')
    keep = [*plan.outputs, *([plan.work_area] if plan.work_area else []), plan.scratch]
    lines += ['(deny file-write* (subpath ' + _q(e) + '))'
              for parent in plan.parents for e in _protected_entries(parent, keep)]
    lines += ['(allow file-write* (subpath ' + _q(p) + '))' for p in writable]
    for p in [*plan.outputs, *writable]:
        lines.append('(allow network-bind (local unix-socket (subpath ' + _q(p) + ')))')
        lines.append('(allow network-inbound (local unix-socket (subpath ' + _q(p) + ')))')
        lines.append('(allow network-outbound (remote unix-socket (subpath ' + _q(p) + ')))')
    lines += ['(allow network-outbound (remote unix-socket (path ' + _q(p) + ')))' for p in plan.channels]
    for port in plan.tcp_ports:
        lines.append(f'(allow network-outbound (remote tcp "*:{port}"))')
    if plan.tcp_ports:
        lines += ['(allow network-outbound (remote unix-socket (path "/private/var/run/mDNSResponder")))',
                  '(allow system-socket)', '(allow mach-lookup (global-name "com.apple.dnssd.service"))']
    # Governed records, installed code, custody and credentials: the final word.
    lines += ['(deny file-write* (subpath ' + _q(p) + '))' for p in plan.unwritable]
    if plan.run_dir is not None:
        logs = str(plan.run_dir / 'logs')
        lines += ['(deny file-write* (regex ' + _regex('^' + re.escape(logs) + '/' + pattern + '$') + '))'
                  for pattern in loc.GOVERNED_LOG_PATTERNS]
    lines += ['(deny file-read* (subpath ' + _q(p) + '))' for p in [*plan.hidden, *plan.withheld]]
    lines += ['(deny process-exec (literal ' + _q(p) + '))' for p in plan.agents]
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------- Linux namespace
def linux_filter(machine=None, network=False):
    """Classic-BPF rows refusing keyring calls, io_uring and the x32 table; another architecture ends the process.

    Without a declared port, ``socket`` for any family but the local one is refused too (the worker
    filter's no-socket rule). Binding and listening stay allowed: a local socket lives in the launch's
    own paths, and the private network namespace has no route out.
    """
    machine = machine or platform.machine()
    machine = {'arm64': 'aarch64', 'amd64': 'x86_64'}.get(machine, machine)
    if machine not in worker_sandbox.LINUX_SYSCALLS:
        raise worker_sandbox.SandboxUnavailable('sandbox_unavailable')
    architecture, numbers = worker_sandbox.LINUX_SYSCALLS[machine]
    load, equal, at_least, result = 0x20, 0x15, 0x35, 0x06
    refused = (worker_sandbox.LINUX_IO_URING_SETUP, *LINUX_KEYRING_SYSCALLS[machine])
    rows = [(load, 4), (equal, architecture, None, 'kill'), (load, 0),
            (at_least, worker_sandbox.LINUX_X32_SYSCALL_BIT, 'refuse', None)]
    rows += [(equal, number, 'refuse', None) for number in refused]
    if not network:
        # The first argument (offset 16) is the family; only AF_UNIX (1) is admitted.
        rows += [(equal, numbers['socket'], None, 'allow'), (load, 16), (equal, 1, 'allow', 'refuse')]
    labels = {'allow': len(rows), 'refuse': len(rows) + 1, 'kill': len(rows) + 2}
    program = []
    for index, row in enumerate(rows):
        if row[0] == load:
            program.append((load, 0, 0, row[1]))
        else:
            jump = lambda label: 0 if label is None else labels[label] - index - 1
            program.append((row[0], jump(row[2]), jump(row[3]), row[1]))
    return program + [(result, 0, 0, worker_sandbox.SECCOMP_ALLOW), (result, 0, 0, worker_sandbox.SECCOMP_REFUSE),
                      (result, 0, 0, worker_sandbox.SECCOMP_KILL_PROCESS)]


def _hide(paths):
    """bwrap arguments that hide existing paths: an empty directory or an empty file in their place."""
    out = []
    for path in loc.outermost(paths):
        if path.is_symlink() or not path.exists():
            continue
        out += (['--tmpfs', str(path), '--remount-ro', str(path)] if path.is_dir()
                else ['--ro-bind', '/dev/null', str(path)])
    return out


def linux_argv(plan, env):
    _issuer_plan(plan)
    writable = _writable(plan)
    argv = [shutil.which('bwrap') or 'bwrap', '--die-with-parent', '--unshare-all',
            *(['--share-net'] if plan.tcp_ports else []), *(['--new-session'] if plan.new_session else []),
            '--clearenv']
    for name, value in sorted(env.items()):
        argv += ['--setenv', name, value]
    argv += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/dev/shm', '--tmpfs', '/tmp']
    for alias in loc.LINUX_MERGED_ALIASES:
        path = Path(alias)
        if path.is_symlink() and path.exists():
            argv += ['--symlink', os.readlink(path), alias]
    if plan.tcp_ports:
        for path in ('/run/systemd/resolve',):
            if Path(path).exists():
                argv += ['--ro-bind', path, path]
    keep = [*plan.outputs, *([plan.work_area] if plan.work_area else []), plan.scratch]
    mounts = [(p, ['--ro-bind', str(p), str(p)]) for p in plan.reads
              if not loc.within(p, [*plan.parents, *writable])]
    mounts += [(p, ['--ro-bind', str(p), str(p)]) for p in plan.channels]
    # A directory receiving new outputs is a private staging copy: its existing entries are
    # mounted read only, deeper writable mounts follow, and only declared outputs are adopted.
    for index, parent in enumerate(plan.parents):
        mounts.append((parent, ['--bind', str(plan.staging[parent]), str(parent)]))
        for entry in plan.listings[parent]:
            path = parent / entry
            if path in keep or path in plan.parents[index + 1:]:
                continue
            # Merely creating an output in a directory grants no read access to siblings.
            if loc.within(path, plan.reads):
                mounts.append((path, ['--ro-bind', str(path), str(path)]))
    mounts += [(p, ['--bind', str(p), str(p)]) for p in writable]
    mounts += [(p, ['--ro-bind', str(copy), str(p)]) for p, copy in plan.input_copies.items()]
    for _, args in sorted(mounts, key=lambda m: (len(m[0].parts), str(m[0]))):
        argv += args
    # An absent namespace path is already denied. Creating a mask outside every
    # mount would expose new directory names while enumerating a hidden home.
    argv += _hide([p for p in [*plan.hidden, *plan.withheld]
                   if loc.within(p, [*plan.reads, *writable, *plan.parents])])
    for program in plan.agents:
        if program.is_file() and not program.is_symlink() and loc.within(program, plan.reads):
            argv += ['--ro-bind', '/dev/null', str(program)]
    # Namespace ancestors are scaffolding, not output grants. In particular /tmp is
    # its own mount and does not inherit the root mount's read-only flag.
    argv += ['--remount-ro', '/tmp', '--remount-ro', '/']
    if plan.cwd:
        if not loc.within(Path(plan.cwd), [*plan.reads, *plan.parents, *writable]):
            # An empty run directory is a working-directory anchor, never a read grant.
            argv[-2:-2] = ['--dir', plan.cwd]
        argv += ['--chdir', plan.cwd]
    limits = {k: v for k, v in (('cpu_set', plan.limits.get('cpu_set')),
                                ('memory_bytes', plan.limits.get('memory_mib', 0) * 1024 * 1024 or None),
                                ('tcp_ports', plan.tcp_ports)) if v}
    shim = [sys.executable, '-I', '-S', '-B', '-c', LINUX_SHIM,
            json.dumps(linux_filter(network=bool(plan.tcp_ports)), separators=(',', ':')),
            json.dumps(limits, separators=(',', ':'))]
    return argv + ['--', *shim, *plan.argv]


# ---------------------------------------------------------------- start and finish
def _scratch_parent(env):
    value = os.environ.get('TMPDIR')
    return loc.real(value if value and os.path.isabs(value) else tempfile.gettempdir())


def start(plan, popen=None, **kwargs):
    """Start the plan's argv; the only step that creates anything."""
    # These Popen options can replace the wrapper, run code before confinement or
    # inherit descriptors that bypass filesystem and socket restrictions.
    if (kwargs.get('shell') or kwargs.get('executable') is not None or kwargs.get('preexec_fn') is not None
            or kwargs.get('pass_fds') or kwargs.get('close_fds') is False):
        _refuse('subprocess overrides may not bypass the confined launcher')
    _require_supported_limits(plan.limits)
    _require_operator_retention(plan.run_dir, plan.record.get('controller'))
    unsupported = [name for name, mechanism in _enforced(plan.backend, plan.limits).items() if mechanism is False]
    if unsupported:
        raise LaunchHeld('resource_limit_unsupported', 'this backend cannot enforce ' + ', '.join(unsupported) +
                         '; use a separately qualified execution adapter that enforces these resources')
    if 'umask' in kwargs and kwargs['umask'] != 0o077:
        _refuse('launch umask must be 0077 for private generated artifacts')
    kwargs['umask'] = 0o077
    popen = subprocess.Popen if popen is None else popen
    # Recompute at the enforcing action, including manually constructed/replayed plans.
    # A prepared record or an absent limit never establishes an aggregate guarantee.
    plan.record['resource_enforcement'] = _resource_enforcement()
    _issuer_plan(plan)
    if plan.kind == CONFINED:
        _issuer_descriptors(kwargs)
    from ravel.workflow.execution import file_hash
    for path, expected in plan.input_digests.items():
        if not Path(path).is_file() or file_hash(path) != expected:
            _refuse(f'committed input {path} changed after confinement planning')
    kwargs.pop('env', None)
    if plan.cwd is None and kwargs.get('cwd') is not None and plan.kind == CONFINED:
        _refuse('a confined launch declares its working directory in its spec')
    if plan.cwd is not None:
        kwargs['cwd'] = plan.cwd
    if plan.kind != CONFINED:
        _journal(plan, 'admitted')
        process = popen(plan.argv, env=plan.env, **kwargs)
        process.ravel_confinement = plan
        _watch(plan, process)
        return process
    # A child that shares a controlling terminal could push input into it (TIOCSTI); a caller
    # without one (a supervisor, a backend launcher) keeps the launch in its process group.
    plan.new_session = not kwargs.get('start_new_session', False) and _controlling_terminal()
    try:
        _journal(plan, 'admitted')
        _materialize(plan)
        _issuer_plan(plan)
        if plan.cwd is None:
            # Without a declared working directory the launch starts in its own scratch.
            kwargs['cwd'] = str(plan.scratch / 'tmp')
        extra = {envmod.CUSTODY: plan.custody_token}
        env, _ = envmod.launch_environment(plan.env, plan.scratch, extra)
        if 'cpus' in plan.limits:
            for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
                         'VECLIB_MAXIMUM_THREADS'):
                env[name] = str(plan.limits['cpus'])
        plan.record['environment_names'] = sorted(env)
        if plan.backend == 'macos':
            argv = ['/usr/bin/sandbox-exec', '-p', macos_profile(plan), *plan.argv]
            launch_env = env
        else:
            argv = linux_argv(plan, env)
            launch_env = {'PATH': env.get('PATH', os.defpath)}
        prefix = argv[:len(argv) - len(plan.argv)]
        plan.record['wrapper_sha256'] = hashlib.sha256(json.dumps(prefix).encode()).hexdigest()
        process = popen(argv, env=launch_env, **kwargs)
    except BaseException:
        _discard(plan)
        raise
    process.ravel_confinement = plan
    _watch(plan, process)
    return process


def _journal(plan, event, result=None):
    controller = plan.record.get('controller') or {}
    run_id = controller.get('run_id')
    if not run_id and plan.run_dir is not None:
        owned = runs.owner_of(plan.run_dir)
        run_id = owned[0] if owned else None
    if run_id:
        # RunStore supplies the clock and hash chain; no environment clock enters this record.
        runs.store(run_id).append('confinement-launch', {'event': event, 'argv': plan.argv,
                                  'confinement': plan.record, **({'result': result} if result else {})})


def _watch(plan, process):
    seconds = plan.limits.get('wall_seconds')
    if seconds is None:
        return
    def expired():
        if process.poll() is None:
            plan.record['wall_limit_exceeded'] = True
            _end_survivors(plan)
            try:
                process.kill()
            except ProcessLookupError:
                pass
    plan.watchdog = threading.Timer(seconds, expired)
    plan.watchdog.daemon = True
    plan.watchdog.start()


def _controlling_terminal():
    try:
        fd = os.open('/dev/tty', os.O_RDONLY | os.O_NOCTTY)
    except OSError:
        return False
    os.close(fd)
    return True


def popen(spec, **popen_kwargs):
    """Start ``spec['argv']`` confined; see the module docstring. Refusals and holds raise before any effect.

    A ``cwd`` given to ``Popen`` is the launch's declared working directory unless the spec names one.
    """
    if isinstance(spec, dict) and not spec.get('cwd') and popen_kwargs.get('cwd') is not None:
        spec = {**spec, 'cwd': os.fspath(popen_kwargs['cwd'])}
    return start(prepare(spec), **popen_kwargs)


def _materialize(plan):
    plan.scratch = Path(tempfile.mkdtemp(prefix='ravel-launch-', dir=_scratch_parent(plan.env)))
    plan.created.append(plan.scratch)
    for sub in set(envmod.SCRATCH.values()):
        (plan.scratch / sub).mkdir()
    plan.record['scratch'] = str(plan.scratch)
    if plan.backend == 'linux' and plan.input_digests:
        from .inputs import capture
        plan.input_directory = Path(tempfile.mkdtemp(prefix='ravel-inputs-', dir=_scratch_parent(plan.env)))
        try:
            plan.input_copies = capture(plan.input_digests, plan.input_directory, roots=plan.input_roots)
        except (OSError, ValueError) as exc:
            _refuse(str(exc))
    if plan.work_area is not None and plan.backend == 'linux' and not plan.work_area.exists():
        missing = [p for p in (plan.work_area.parent, plan.work_area) if not p.exists()]
        plan.work_area.mkdir(parents=True)
        plan.created += missing
    for parent in plan.parents:
        names = sorted(os.listdir(parent))
        if len(names) > MAX_STAGED_ENTRIES:
            _refuse(f'{parent} holds more than {MAX_STAGED_ENTRIES} entries; declare a dedicated output directory')
        plan.listings[parent] = names
    if plan.backend == 'linux' and plan.parents:
        base = (plan.attempt_dir / 'confinement' if plan.attempt_dir is not None else plan.scratch / 'confinement')
        for index, parent in enumerate(plan.parents):
            staging = base / 'staging' / str(index)
            staging.mkdir(parents=True)
            plan.staging[parent] = staging


def _discard(plan):
    if plan.input_directory is not None:
        shutil.rmtree(plan.input_directory, ignore_errors=True)
    if plan.scratch is not None:
        shutil.rmtree(plan.scratch, ignore_errors=True)
    for path in reversed(plan.created):
        try:
            path.rmdir()
        except OSError:
            pass


def _move(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(str(source), str(destination))


def _undeclared(directory, keep):
    """Entries under ``directory`` that are neither declared outputs nor ancestors of one."""
    found = []
    for entry in sorted(Path(directory).iterdir()):
        if entry in keep:
            continue
        if any(k.is_relative_to(entry) for k in keep) and entry.is_dir() and not entry.is_symlink():
            found += _undeclared(entry, keep)
            continue
        found.append(entry)
    return found


def survivors(token):
    """Processes still carrying this launch's custody secret (found by that secret, never by name)."""
    marker = f'{envmod.CUSTODY}={token}'
    found = []
    if sys.platform.startswith('linux'):
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                if marker.encode() in (entry / 'environ').read_bytes().split(b'\0'):
                    found.append(int(entry.name))
            except OSError:
                continue
        return found
    ps = shutil.which('ps', path='/bin:/usr/bin')
    if ps is None:
        return found
    try:
        done = subprocess.run([ps, '-A', '-E', '-ww', '-o', 'pid=,command='], capture_output=True, text=True,
                              timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return found
    for line in done.stdout.splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[0].isdigit() and marker in fields[1].split() and int(fields[0]) != os.getpid():
            found.append(int(fields[0]))
    return found


def _end_survivors(plan):
    """Kill whatever the launch left running; a confined launch never outlives its finish."""
    import signal
    ended = []
    for pid in survivors(plan.custody_token):
        try:
            os.kill(pid, signal.SIGKILL)
            ended.append(pid)
        except (ProcessLookupError, PermissionError):
            continue
    return ended


def _inventory(paths):
    from ravel.workflow import execution
    rows = []
    for path in paths:
        if path.is_file() and not path.is_symlink():
            rows.append({'path': str(path), 'size': path.stat().st_size, 'sha256': execution.file_hash(path)})
        elif path.is_dir() and not path.is_symlink():
            files = [p for p in sorted(path.rglob('*')) if p.is_file() and not p.is_symlink()]
            rows.append({'path': str(path), 'files': len(files), 'size': sum(p.stat().st_size for p in files)})
        else:
            rows.append({'path': str(path), 'absent': not os.path.lexists(path)})
    return rows


def finish(target):
    """Adopt declared outputs, quarantine everything else the launch created, remove scratch.

    ``target`` is the started process or its plan. Returns the observed writes and the output inventory.
    """
    plan = getattr(target, 'ravel_confinement', target)
    if plan is None or not isinstance(plan, Plan):
        return None
    if plan.finished is not None:
        return plan.finished
    if plan.watchdog is not None:
        plan.watchdog.cancel()
    result = {'adopted': [], 'quarantined': [], 'errors': []}
    if plan.kind == CONFINED:
        # Stop descendants before inspecting or adopting any writable output.
        result['orphans_ended'] = _end_survivors(plan)
        quarantine = (plan.attempt_dir / 'confinement' / 'undeclared' if plan.attempt_dir is not None
                      else (plan.scratch.parent / (plan.scratch.name + '.undeclared')))
        keep = [*plan.outputs, *([plan.work_area] if plan.work_area else [])]
        for index, parent in enumerate(plan.parents):
            try:
                if plan.backend == 'linux':
                    staging = plan.staging[parent]
                    for output in [o for o in plan.outputs if o.is_relative_to(parent) and not os.path.lexists(o)]:
                        source = staging / output.relative_to(parent)
                        if os.path.lexists(source):
                            _move(source, output)
                            result['adopted'].append(str(output))
                    placeholders = set(plan.listings[parent])
                    for entry in sorted(staging.iterdir()):
                        if entry.name in placeholders:
                            try:
                                entry.rmdir() if entry.is_dir() and not entry.is_symlink() else entry.unlink()
                            except OSError:
                                pass
                            continue
                        result['quarantined'].append(str(parent / entry.relative_to(staging)))
                    if result['quarantined']:
                        result['quarantine'] = str(staging.parent)
                else:
                    existing = set(plan.listings[parent])
                    for entry in sorted(parent.iterdir()):
                        if entry.name in existing or entry in keep:
                            continue
                        targets = (_undeclared(entry, keep) if any(k.is_relative_to(entry) for k in keep)
                                   and entry.is_dir() and not entry.is_symlink() else [entry])
                        for found in targets:
                            _move(found, quarantine / str(index) / found.relative_to(parent))
                            result['quarantined'].append(str(found))
                    if result['quarantined']:
                        result['quarantine'] = str(quarantine)
            except (OSError, ValueError) as exc:
                result['errors'].append(f'{parent}: {exc}')
        if plan.work_area is not None and plan.backend == 'linux':
            for path in (plan.work_area, plan.work_area.parent):
                if path in plan.created:
                    try:
                        path.rmdir()
                    except OSError:
                        break
        if plan.scratch is not None:
            shutil.rmtree(plan.scratch, ignore_errors=True)
            result['scratch_removed'] = not plan.scratch.exists()
    result['quarantined'] = sorted(set(result['quarantined']))
    result['outputs'] = _inventory(plan.outputs)
    returncode = getattr(target, 'returncode', None)
    if returncode is not None:
        result['exit_status'] = returncode
    plan.finished = result
    if plan.input_directory is not None:
        shutil.rmtree(plan.input_directory, ignore_errors=True)
    _journal(plan, 'finished', result)
    return result


def backends():
    """Which launch backends this host offers: ``available`` or the reason it does not."""
    kind = worker_sandbox.available()
    out = {}
    for name, platform_name in (('sandbox-exec', 'macos'), ('bwrap', 'linux')):
        if kind != platform_name:
            out[name] = ('not this platform' if (sys.platform == 'darwin') != (platform_name == 'macos')
                         else f'{name} not found')
            continue
        try:
            qualify(kind)
            out[name] = 'available'
        except (worker_sandbox.SandboxUnavailable, worker_sandbox.SandboxProbeFailed) as exc:
            out[name] = f'unqualified: {exc}'
    client = shutil.which('podman')
    out['oci-local'] = ('client present; qualified by `ravel backend doctor` (this check never starts it)'
                        if client else 'podman client not found')
    return out


# ---------------------------------------------------------------- qualification
QUALIFY_PROGRAM = r'''
import errno, json, os, socket, sys
paths = json.loads(sys.argv[1])
denied = (errno.EACCES, errno.EPERM, errno.EROFS, errno.ENOENT, errno.ENOTDIR)
result = {}
def attempt(name, action):
    try:
        action()
        result[name] = 'allowed'
    except OSError as error:
        result[name] = 'denied' if error.errno in denied else 'error-%d' % error.errno
def write(path, mode='w'):
    with open(path, mode) as stream:
        stream.write('probe')
def read(path):
    with open(path) as stream:
        stream.read()
attempt('write_declared_output', lambda: write(paths['output_file']))
attempt('create_declared_output', lambda: write(paths['new_output']))
attempt('write_governed_record', lambda: write(paths['governed'], 'a'))
attempt('create_governed_record', lambda: write(paths['new_governed']))
attempt('write_installed_code', lambda: os.close(os.open(paths['installed'], os.O_CREAT | os.O_EXCL | os.O_WRONLY)))
attempt('read_shared_temporary', lambda: read(paths['canary']))
attempt('read_issuer_key', lambda: read(paths['issuer_key']))
attempt('write_issuer_root', lambda: write(paths['issuer_probe']))
attempt('list_home', lambda: [n for n in os.listdir(paths['home']) if n not in paths['home_allowed']] or (_ for _ in ()).throw(OSError(errno.ENOENT, 'empty')))
def connect():
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(('127.0.0.1', paths['port']))
    except OSError as error:
        # A private network namespace answers with a refusal of its own; the parent's listener
        # (``host_listener_reached``) is the proof that nothing reached the host.
        if error.errno in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT,
                           errno.EADDRNOTAVAIL, None):
            raise PermissionError(errno.EPERM, 'no route to the host')
        raise
    finally:
        s.close()
attempt('connect_host_port', connect)
result['environment_marker'] = paths['marker'] in os.environ
result['temporary_is_private'] = os.environ.get('TMPDIR', '').startswith(os.environ.get('HOME', '//').rsplit('/', 1)[0] + '/')
print(json.dumps(result))
'''


def qualify(kind):
    """Execute the denial probes once per process and backend; raise unless every one holds."""
    with _QUALIFY_LOCK:
        if kind not in _QUALIFIED:
            _QUALIFIED[kind] = _probe(kind)
        return _QUALIFIED[kind]


def _probe(kind):
    from ravel import paths as ravel_paths
    marker = 'RAVEL_CONFINEMENT_PROBE_' + secrets.token_hex(4).upper()
    work = Path(tempfile.mkdtemp(prefix='ravel-confinement-probe-', dir=_scratch_parent({})))
    listener = None
    installed = Path(ravel_paths.__file__).parent / f'.confinement-probe-{secrets.token_hex(8)}'
    home = loc.account_homes()[0]
    try:
        root = work / 'run'
        (root / 'inputs').mkdir(parents=True)
        (root / 'out').mkdir()
        governed = root / 'inputs' / 'approval.json'
        governed.write_text('approved')
        canary = work / 'canary.txt'
        canary.write_text('shared temporary area')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(0.2)
        source = dict(envmod.capsule_from(dict(os.environ)), **{marker: 'probe'})
        _QUALIFIED[kind] = {'backend': kind, 'probing': True}
        try:
            plan = prepare({'argv': [sys.executable, '-I', '-S', '-B', '-c', QUALIFY_PROGRAM], 'env': source,
                            'run_dir': str(root), 'stage': 'probe', 'cwd': str(root), 'reads': [str(root)],
                            'writes': [str(root / 'out'), str(root / 'new.json')]})
        finally:
            _QUALIFIED.pop(kind, None)
        allowed_home = sorted({r.relative_to(home).parts[0] for r in plan.reads if r.is_relative_to(home) and r != home})
        program = {'output_file': str(root / 'out' / 'x.txt'), 'new_output': str(root / 'new.json'),
                   'governed': str(governed), 'new_governed': str(root / 'task_contract.json'),
                   'installed': str(installed), 'canary': str(canary), 'home': str(home),
                   'home_allowed': allowed_home, 'port': listener.getsockname()[1], 'marker': marker,
                   'issuer_key': str(loc.issuer_root() / 'issuer.key'),
                   'issuer_probe': str(loc.issuer_root() / ('.negative-probe-' + secrets.token_hex(8)))}
        plan.argv = [*plan.argv, json.dumps(program)]
        try:
            process = start(plan, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            out, err = process.communicate(timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise worker_sandbox.SandboxUnavailable(f'launch sandbox unavailable: {exc}') from exc
        finally:
            finished = finish(plan)
        text = err.decode(errors='replace')
        if process.returncode != 0:
            if ('sandbox_apply' in text or 'sandbox_init' in text or (kind == 'linux' and 'bwrap: ' in text and any(
                    m in text for m in ('No permissions to create new namespace', 'Creating new namespace failed',
                                        'setting up uid map', 'Operation not permitted')))):
                raise worker_sandbox.SandboxUnavailable('launch sandbox unavailable: ' + text.strip()[-500:])
            raise worker_sandbox.SandboxProbeFailed('launch sandbox probe failed: ' + text.strip()[-500:])
        checks = json.loads(out.decode().strip().splitlines()[-1])
        try:
            listener.accept()[0].close()
            checks['host_listener_reached'] = True
        except (socket.timeout, OSError):
            checks['host_listener_reached'] = False
        checks['governed_record_unchanged'] = governed.read_text() == 'approved'
        checks['governed_name_absent'] = not (root / 'task_contract.json').exists()
        checks['declared_outputs_present'] = (root / 'new.json').is_file() and (root / 'out' / 'x.txt').is_file()
        checks['installed_code_unchanged'] = not installed.exists()
        expected = {'write_declared_output': 'allowed', 'create_declared_output': 'allowed',
                    'write_governed_record': 'denied', 'write_installed_code': 'denied',
                    'read_shared_temporary': 'denied', 'list_home': 'denied', 'connect_host_port': 'denied',
                    'read_issuer_key': 'denied', 'write_issuer_root': 'denied',
                    'environment_marker': False, 'temporary_is_private': True, 'host_listener_reached': False,
                    'governed_record_unchanged': True, 'governed_name_absent': True,
                    'declared_outputs_present': True, 'installed_code_unchanged': True}
        if kind == 'macos':
            expected['create_governed_record'] = 'denied'
        wrong = sorted(k for k, v in expected.items() if checks.get(k) != v)
        if wrong:
            failure = worker_sandbox.SandboxProbeFailed(f'launch sandbox probe did not confirm {wrong}')
            failure.checks = checks
            raise failure
        return {'backend': BACKENDS[kind], 'confirmed': True, 'checks': checks,
                'quarantined_probe_writes': finished['quarantined'] if finished else []}
    finally:
        if listener is not None:
            listener.close()
        if installed.exists():
            installed.unlink()
        shutil.rmtree(work, ignore_errors=True)
