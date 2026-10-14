"""One independent worker's read-only admission/calculation, then inert delivery.

Source-owned adapter declarations are not execution or scientific authority.
All participant observations remain live until callbacks and terminal checks
complete. No parent proof, persistent cache, output or scientific job lives here.
"""
from dataclasses import dataclass
import inspect
import json
import os
from pathlib import Path
import sys
import _thread


MAX_RESOURCES = 32
MAX_ARTIFACTS = 8
MAX_RESULT_BYTES = 128 * 1024**2
MAX_DELIVERY_BYTES = 256 * 1024**2


def _bytes(value):
    return (json.dumps(value, indent=2, allow_nan=False) + '\n').encode('utf-8')


@dataclass(frozen=True)
class ReadOnlyAdapterV1:
    """Exact initial public callable identities and reviewed read-only hooks."""
    bindings: tuple
    inputs: object
    calculate: object
    materialize: object
    fresh_directory: bool


def select_descriptor(module):
    descriptor = getattr(module, 'READONLY_WORKER_V1', None)
    if descriptor is None:
        return None
    if (type(descriptor) is not ReadOnlyAdapterV1 or type(descriptor.bindings) is not tuple
            or type(descriptor.fresh_directory) is not bool
            or any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                   for row in descriptor.bindings)
            or len({row[0] for row in descriptor.bindings}) != len(descriptor.bindings)
            or not {'inputs', 'run'} <= {row[0] for row in descriptor.bindings}):
        raise ValueError('closed source-owned read-only worker descriptor required')
    # A legacy injected public callback gets its old full path, not the new
    # hook's proof. Once selected, any replacement is a hard ending refusal.
    if (any(getattr(module, name, None) is not function for name, function in descriptor.bindings)
            or getattr(module, 'run_in_worker', None) is not None
            or getattr(module, 'helper_declaration', None) is not None):
        return None
    for function in (descriptor.inputs, descriptor.calculate, descriptor.materialize):
        if not callable(function):
            raise ValueError('source-owned read-only hooks must be callable')
        try:
            inspect.signature(function).bind({}, Path('.'), None)
        except (TypeError, ValueError) as exc:
            raise ValueError('read-only hook has an incompatible explicit context signature') from exc
    return descriptor


@dataclass(frozen=True)
class PreparedDelivery:
    """Detached intended bytes only; never contains a live observation."""
    proposal_bytes: bytes
    specification_bytes: bytes
    result_bytes: bytes
    artifacts: tuple
    fresh_directory: bool

    @property
    def proposal(self):
        return json.loads(self.proposal_bytes)

    @property
    def specification(self):
        return json.loads(self.specification_bytes)

    @property
    def result(self):
        return json.loads(self.result_bytes)

    def write(self, destination):
        destination = Path(destination)
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            raise ValueError('ordinary prepared-delivery destination required')
        if self.fresh_directory:
            destination.mkdir(parents=True, exist_ok=False)
        elif not destination.is_dir():
            raise ValueError('worker-owned prepared-delivery directory required')
        for name, intended in self.artifacts:
            path = destination / name
            with path.open('xb') as stream:
                stream.write(intended)
                stream.flush()
                os.fsync(stream.fileno())
            if path.is_symlink() or path.read_bytes() != intended:
                raise ValueError('prepared artifact differs from its intended bytes')
        return self.result

    def check_delivery(self, destination, common, result):
        if any(p.is_symlink() for root in (Path(destination), Path(common))
               for p in (root, *root.parents)):
            raise ValueError('ordinary prepared-delivery ancestry changed')
        if _bytes(result) != self.result_bytes:
            raise ValueError('prepared result changed during ordinary materialization')
        for name, intended in self.artifacts:
            path = Path(destination) / name
            if path.is_symlink() or path.read_bytes() != intended:
                raise ValueError('prepared artifact changed before ordinary return')
        path = Path(common) / 'result.json'
        if path.is_symlink() or path.read_bytes() != self.result_bytes:
            raise ValueError('ordinary result differs from prepared calculation')


class WorkerReadOnlyObservation:
    """One worker, one calculation and a fixed two-phase participant ending."""
    def __init__(self, rundir, *, process_binding=None):
        from . import execution
        self.rundir = Path(rundir)
        # Descriptor discovery happens only at the incumbent adapter resolution
        # inside independent worker admission, never from an unverified hint.
        self.module, self.descriptor = None, None
        self.pid = os.getpid()
        self.thread = _thread.get_ident()
        self.process_binding = process_binding
        self.active = False
        self.closed = False
        self.draining = False
        self.calculated = False
        self.resources = {}
        self.arguments = []
        self.path_arguments = []
        self.ending_checks = []
        self.session = execution._validation_session(self.rundir)
        self._initial_descriptor = None
        self._delivery = None

    def __enter__(self):
        if self.active or self.closed:
            raise ValueError('read-only worker owner cannot be reused')
        self.active = True
        try:
            self.check_identity()
        except BaseException as primary:
            self.close(primary)
            raise
        return self

    def require_active(self):
        if (not self.active or self.closed or os.getpid() != self.pid
                or _thread.get_ident() != self.thread):
            raise ValueError('active same-process read-only worker owner required')

    def check_identity(self, *, resources=True):
        self.require_active()
        if self.process_binding is not None:
            module, reader, original = self.process_binding
            if (module.process_identity is not reader
                    or (os.getpid(), os.getppid()) != original[:2]
                    or not resources and reader(os.getpid()) != original[2]):
                raise ValueError('independent worker process ownership changed')
        if self.descriptor is not None and (getattr(self.module, 'READONLY_WORKER_V1', None) is not self._initial_descriptor
                or any(getattr(self.module, name, None) is not function
                       for name, function in self.descriptor.bindings)
                or getattr(self.module, 'run_in_worker', None) is not None
                or getattr(self.module, 'helper_declaration', None) is not None):
            raise ValueError('selected read-only adapter changed during observation')
        for factory, resource in self.resources.items():
            module = sys.modules.get(factory.__module__)
            if module is None or getattr(module, factory.__name__, None) is not factory:
                raise ValueError('read-only participant factory changed during observation')
            if resources:
                resource.readonly_check()

    def resource(self, factory):
        self.check_identity()
        if factory not in self.resources:
            if self.draining:
                raise ValueError('new participant after read-only ending freeze')
            if len(self.resources) >= MAX_RESOURCES:
                raise ValueError('read-only participant population exceeds bound')
            resource = factory()
            self.resources[factory] = resource
            resource.__enter__()
        return self.resources[factory]

    def add_ending_check(self, function):
        self.require_active()
        if self.draining or len(self.ending_checks) >= 32:
            raise ValueError('bounded ending callbacks must be declared before drain')
        self.ending_checks.append(function)

    def inputs(self, module, task, base, role):
        self.check_identity()
        if role not in ('original', 'effective') or self.draining:
            raise ValueError('exact worker admission role required')
        if self.module is None:
            self.module = module
            self.descriptor = select_descriptor(module)
            self._initial_descriptor = self.descriptor
        elif self.descriptor is not None and module is not self.module:
            raise ValueError('worker adapter differs between original and effective admission')
        if self.descriptor is None:
            return None
        self.arguments.append((role, task, _bytes(task), Path(base)))
        self.session.track(task)
        paths = self.descriptor.inputs(task, base, self)
        if type(paths) not in (list, tuple):
            raise ValueError('complete explicit read-only input path population required')
        for path in paths:
            self.session.require_regular(Path(path))
            self.session.hash_file(Path(path))
        # Path objects are not JSON values. Keep their original sequence and
        # exact spelled population, while the Session owns file/ancestry facts.
        self.path_arguments.append((paths, type(paths), tuple(str(p) for p in paths)))
        return paths

    def calculate(self, task, base):
        self.check_identity()
        if self.descriptor is None or self.calculated or self.draining:
            raise ValueError('one read-only calculation per worker observation required')
        effective = [row for row in self.arguments if row[0] == 'effective']
        if (not effective or _bytes(task) != effective[-1][2]
                or Path(base) != effective[-1][3]):
            raise ValueError('calculation differs from admitted effective task/base')
        self.calculated = True
        self.session.track(task)
        result = self.descriptor.calculate(task, base, self)
        if (type(result) is not dict or result.get('physics_validated') is not False
                or result.get('status') not in ('passed', 'failed')):
            raise ValueError('read-only result must retain its explicit evidence boundary')
        self.session.track(result)
        return result

    def materialize(self, proposal, specification, result):
        self.check_identity()
        if not self.calculated or self.draining or self._delivery is not None:
            raise ValueError('one materialization before read-only ending required')
        artifacts = self.descriptor.materialize(result, specification, self)
        if type(artifacts) is not tuple or not 1 <= len(artifacts) <= MAX_ARTIFACTS:
            raise ValueError('bounded complete prepared artifact tuple required')
        names = []
        for row in artifacts:
            if (type(row) is not tuple or len(row) != 2 or type(row[0]) is not str
                    or not row[0] or '/' in row[0] or '\\' in row[0]
                    or row[0] in ('.', '..') or type(row[1]) is not bytes):
                raise ValueError('exact leaf artifact name and immutable bytes required')
            names.append(row[0])
        if len(set(names)) != len(names):
            raise ValueError('duplicate prepared artifact name')
        values = tuple(_bytes(v) for v in (proposal, specification, result))
        if len(values[-1]) > MAX_RESULT_BYTES or sum(map(len, values)) + sum(len(v) for _, v in artifacts) > MAX_DELIVERY_BYTES:
            raise ValueError('prepared delivery exceeds complete byte bound')
        for value in (proposal, specification, result):
            self.session.track(value)
        self._delivery = (proposal, specification, result, values, artifacts)

    def _participants(self):
        rows = [self.session]
        for resource in self.resources.values():
            rows.extend(resource.readonly_sessions())
        if len(rows) > 129 or len({id(s) for s in rows}) != len(rows):
            raise ValueError('bounded distinct read-only participant roster required')
        return tuple(rows)

    def finish(self):
        self.check_identity()
        if self.draining or self._delivery is None:
            raise ValueError('prepared delivery required before fixed ending')
        self.draining = True
        for resource in self.resources.values():
            resource.readonly_freeze()
        participants = self._participants()
        for session in participants:
            session.readonly_freeze()
        checks = tuple(self.ending_checks)
        for session in participants:
            session.readonly_drain()
            self.check_identity()
        for check in checks:
            check()
            self.check_identity()
        if (len(checks) != len(self.ending_checks)
                or any(a is not b for a, b in zip(checks, self.ending_checks))
                or self._participants() != participants):
            raise ValueError('read-only ending roster changed during drain')
        # All original observations remain live. No ordinary finish() has
        # cleared producer facts before a later worker callback can touch them.
        for session in participants:
            session.readonly_terminal()
        self.check_identity(resources=False)
        proposal, specification, result, intended, artifacts = self._delivery
        if (tuple(_bytes(v) for v in (proposal, specification, result)) != intended
                or any(_bytes(task) != raw for _, task, raw, _ in self.arguments)
                or any(type(paths) is not kind or tuple(str(p) for p in paths) != before
                       for paths, kind, before in self.path_arguments)):
            raise ValueError('read-only arguments or delivery changed at complete ending')
        return PreparedDelivery(*intended, artifacts, self.descriptor.fresh_directory)

    def close(self, primary=None):
        failures = []
        self.active = False
        self.closed = True
        for resource in self.resources.values():
            try:
                resource.readonly_close()
            except BaseException as exc:
                failures.append(exc)
        try:
            self.session.close()
        except BaseException as exc:
            failures.append(exc)
        self.resources.clear()
        self.arguments.clear()
        self.path_arguments.clear()
        self.ending_checks.clear()
        self._delivery = None
        if failures:
            if primary is not None:
                for failure in failures:
                    primary.add_note('read-only cleanup failure: ' + str(failure))
            else:
                failure = failures[0]
                for other in failures[1:]:
                    failure.add_note('read-only cleanup failure: ' + str(other))
                raise failure

    def __exit__(self, kind, primary, traceback):
        self.close(primary)
        return False
