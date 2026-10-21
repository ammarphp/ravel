"""Private controller worker configuration and owner-provided file metadata."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from ravel.workflow import sandbox
from ravel.workflow.broker import ordinary

def command(workspace, argv, *, read_paths=(), backend=None, broker_socket=None, protected=(), home=None,
            network=None, writable=None):
    """Worker OS boundary with authority isolation checked on every effective grant."""
    from . import launcher
    kind = backend or sandbox.available()
    workspace = ordinary(workspace)
    writes = ([workspace / name for name in sandbox.WORKER_WRITE_ROOTS] if writable is None
              else [Path(p) for p in writable])
    reads = [*read_paths, workspace / 'inputs', *([broker_socket] if broker_socket else [])]
    if home is not None:
        writes.append(home)
    if kind == 'linux':
        reads += ['/proc', '/dev']
        if network == 'provider':
            reads += ['/etc/resolv.conf', '/etc/hosts', '/etc/ssl', '/etc/ca-certificates', '/etc/pki']
    root = launcher.require_issuer_mounts(launcher.BACKENDS.get(kind), reads=reads, writes=writes)
    result = sandbox.command(workspace, argv, read_paths=read_paths, backend=kind,
                             broker_socket=broker_socket, protected=[*protected, root], home=home,
                             network=network, writable=writable)
    if kind == 'macos':
        result[2] += ('\n(deny file-read* file-write* (subpath ' + sandbox.quote(str(root)) + '))\n')
    return result


def private_home(workspace, home):
    """Controller workers mount owner-provided files within their own private CLI home."""
    if home is None:
        return None
    path = ordinary(home)
    if path != sandbox.cli_home_for(workspace):
        raise sandbox.ReadRootRefused('controller worker home must be its private directory beside the workspace')
    for item in (path, *path.rglob('*')):
        info = item.lstat()
        if (stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
            raise sandbox.ReadRootRefused('controller worker home must contain private ordinary files')
    return path
