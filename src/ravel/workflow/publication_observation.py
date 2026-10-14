"""Private, per-pure-method publication path observation.

Mechanical descriptors come from the shared anchored core. This adapter owns
its exact live Session gate and closes before return; it grants no worker,
author, approval, acquisition, presentation or native execution authority.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import threading
import types

from . import publication_runtime as pr, report_integrity as ri
from .validation_io import ValidationSession


_CORE = getattr(ri, '_AnchoredDirectoryCore', None)
_IDENTITY = getattr(ri, '_anchored_identity', None)
_CORE_METHODS = (() if _CORE is None else tuple((name, getattr(_CORE, name))
    for name in ('__init__', '_directory', '_chain', 'close_all')))
_OS = tuple((name, getattr(os, name)) for name in ('open', 'close', 'fstat', 'lstat', 'stat', 'fdopen', 'getpid'))
_THREAD_ID = threading.get_ident
_CORE_CLOSE_ALL = None if _CORE is None else _CORE.close_all
_PROOF_FACTORY = pr._build_runtime_proof
_OWNER_READER_CODE = next((value for value in _PROOF_FACTORY.__code__.co_consts
    if type(value) is types.CodeType and value.co_name == '<lambda>'), None)
_SESSION_METHODS = tuple((name, getattr(ValidationSession, name)) for name in (
    'retain_path_identity', 'regular_file', 'observe', 'hash_file'))


def _supported(proof, *, origins=True):
    if (_CORE is None or _IDENTITY is None or
            not all(hasattr(os, name) for name in ('O_DIRECTORY', 'O_NOFOLLOW'))):
        return False
    if (type(proof) is not pr._BuildRuntimeProof or
            type(proof.session) is not ValidationSession):
        return False
    if (pr._build_runtime_proof is not _PROOF_FACTORY or
            type(proof.owners) is not types.FunctionType or
            proof.owners.__code__ is not _OWNER_READER_CODE):
        return False
    if (getattr(ri, '_AnchoredDirectoryCore', None) is not _CORE or
            getattr(ri, '_anchored_identity', None) is not _IDENTITY or
            any(getattr(_CORE, name) is not owner for name, owner in _CORE_METHODS) or
            any(getattr(os, name) is not owner for name, owner in _OS) or
            threading.get_ident is not _THREAD_ID or
            any(getattr(ValidationSession, name) is not owner for name, owner in _SESSION_METHODS) or
            any(getattr(getattr(proof.session, name), '__func__', None) is not owner
                for name, owner in _SESSION_METHODS)):
        return False
    if origins:
        for function in (_IDENTITY, *(f for _, f in _CORE_METHODS)):
            if (type(function) is not types.FunctionType or function.__module__ != ri.__name__ or
                    Path(function.__code__.co_filename).resolve() != Path(ri.__file__).resolve()):
                return False
    if not any(value is proof and type(key) is tuple and key and
               key[0] == 'publication-unqualified-runtime-proof/v1'
               for key, value in proof.session.proofs.items()):
        return False
    return True


class _PublicationPaths:
    """Own one finite operation, never default Session.finish's callback scope."""
    def __init__(self, proof):
        if not _supported(proof):
            raise ValueError('exact source-owned publication observation required')
        self.proof = proof
        self.owner_reader = proof.owners
        self.session = proof.session
        proof.live()
        self.run_spelling = str(self.session.rundir)
        self.core = _CORE(self.session)
        self.pid, self.thread = os.getpid(), threading.get_ident()
        self.active = False
        self.closed = False
        self.kinds = {}
        self.leaf_fds = {}

    def __enter__(self):
        if self.closed or self.active:
            raise ValueError('publication observation cannot be reused')
        self.active = True
        try:
            _CHECK_OWNER(self)
        except BaseException as error:
            failures = _CLOSE_OWNER(self)
            if failures:
                error.add_note('publication descriptor cleanup failed: ' + repr(failures))
            raise
        return self

    def check(self):
        if (not self.active or self.closed or os.getpid() != self.pid or
                threading.get_ident() != self.thread or not _supported(self.proof, origins=False) or
                self.session.closed or str(self.session.rundir) != self.run_spelling or
                self.proof.owners is not self.owner_reader or
                any(current is not original for current, original in self.owner_reader()) or
                observation is not _FACTORY_OWNER or _supported is not _SUPPORTED_OWNER or
                any(getattr(_PublicationPaths, name) is not owner for name, owner in _PATH_METHODS)):
            raise ValueError('live same-process/thread publication observation required')

    def path(self, value, *, directory=False):
        _CHECK_OWNER(self)
        p = Path(value).absolute()
        # Noncanonical spellings keep the complete incumbent reader. No path
        # normalization or partial anchor becomes a new admission rule.
        if (os.fspath(value) != str(p) or p.anchor != os.sep or
                '..' in p.parts or p == Path(os.sep)):
            return pr._regular(value, directory=directory)
        observed = {}
        chain = tuple(reversed(p.parents))
        for q in chain:
            identity = _IDENTITY(os.lstat(q))[:3]
            if not stat.S_ISDIR(identity[2]):
                raise ValueError('publication snapshots require regular non-alias paths')
            observed[q] = identity
        leaf = _IDENTITY(os.lstat(p))
        if not (stat.S_ISDIR(leaf[2]) if directory else stat.S_ISREG(leaf[2])):
            raise ValueError('regular publication file/directory required')
        prior = self.core.records.get(p)
        if prior is not None:
            if self.kinds[p] != directory or (leaf[:3] if directory else leaf) != (
                    prior[3][:3] if directory else prior[3]):
                raise ValueError('publication path identity changed during observation')
            self.core._chain(prior, observed=observed)
            return p
        if len(self.core.records) >= self.core.MAX_PATH_RECORDS:
            return pr._regular(value, directory=directory)
        parent_fd = None
        for q in chain:
            parent_fd = self.core._directory(q, observed[q], parent_fd)
            if parent_fd is None:
                return pr._regular(value, directory=directory)
        record = (p, (p, *p.parents), chain, leaf)
        # Facts came from these fresh literal names, not a stored positive.
        self.core._chain(record, observed=observed)
        self.session.retain_path_identity(p, leaf[:3] if directory else leaf)
        self.core.records[p] = record
        self.kinds[p] = directory
        return p

    def ending(self, value, *, directory=False):
        p = _PATH_OWNER(self, value, directory=directory)
        record = self.core.records.get(p)
        if record is None:
            return pr._regular(value, directory=directory).stat()
        parent = self.core._chain(record)
        current = os.stat(p.name, dir_fd=parent, follow_symlinks=False)
        actual = _IDENTITY(current)
        if (actual[:3] if directory else actual) != (record[3][:3] if directory else record[3]):
            raise ValueError('publication named member changed during observation')
        return current

    def identity(self, value, *, _closer=os.close):
        p = _PATH_OWNER(self, value)
        record = self.core.records.get(p)
        if record is None:
            return pr._identity(value)
        parent = self.core._chain(record)
        fd = os.open(p.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        self.leaf_fds[fd] = record[3]
        try:
            before = os.fstat(fd)
            if _IDENTITY(before) != record[3]:
                raise ValueError('publication input changed before descriptor read')
            digest = hashlib.sha256()
            with os.fdopen(fd, 'rb', closefd=False) as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b''):
                    digest.update(block)
            after = os.fstat(fd)
            if (_IDENTITY(after) != record[3] or
                    _IDENTITY(_ENDING_OWNER(self, p)) != record[3]):
                raise ValueError('publication input changed while read')
            return {'path': str(p), 'sha256': digest.hexdigest(),
                    'size': after.st_size, 'identity': list(_IDENTITY(after))}
        finally:
            _closer(fd)
            self.leaf_fds.pop(fd, None)

    def terminal(self):
        _CHECK_OWNER(self)
        self.proof.live()
        # No supplied callback and no default Session.finish guarantee: this
        # pure method has finished all its work before checking original facts.
        for path in tuple(self.core.records):
            _ENDING_OWNER(self, path, directory=self.kinds[path])
        for path, (_, expected) in tuple(self.core.directories.items()):
            if _IDENTITY(os.lstat(path))[:3] != expected:
                raise ValueError('publication ancestor changed at operation tail')

    def close(self, *, _closer=os.close, _core_close=_CORE_CLOSE_ALL):
        failures = []
        for fd in tuple(self.leaf_fds):
            try:
                _closer(fd)
            except BaseException as error:
                failures.append(error)
        self.leaf_fds.clear()
        failures.extend(_core_close(self.core, _closer))
        self.kinds.clear()
        self.active = False
        self.closed = True
        return failures

    def __exit__(self, kind, error, traceback):
        failure = None
        try:
            if error is None:
                _TERMINAL_OWNER(self)
        except BaseException as found:
            failure = found
        finally:
            closing = _CLOSE_OWNER(self)
        if closing:
            if error is not None:
                error.add_note('publication descriptor cleanup failed: ' + repr(closing))
            elif failure is not None:
                failure.add_note('publication descriptor cleanup failed: ' + repr(closing))
            else:
                raise ValueError('publication descriptor cleanup failed: ' + repr(closing))
        if failure is not None:
            raise failure
        return False


_CLOSE_OWNER = _PublicationPaths.close
_CHECK_OWNER = _PublicationPaths.check
_PATH_OWNER = _PublicationPaths.path
_ENDING_OWNER = _PublicationPaths.ending
_TERMINAL_OWNER = _PublicationPaths.terminal
_PATH_METHODS = tuple((name, getattr(_PublicationPaths, name)) for name in (
    '__init__', '__enter__', 'check', 'path', 'ending', 'identity', 'terminal', 'close', '__exit__'))


def observation(proof):
    if (_supported is not _SUPPORTED_OWNER or
            any(getattr(_PublicationPaths, name) is not owner for name, owner in _PATH_METHODS)
            or not _supported(proof)):
        return None
    return _PublicationPaths(proof)


_SUPPORTED_OWNER = _supported
_FACTORY_OWNER = observation
