"""Capture ordinary committed input files without writable aliases.

Linux mounts these private copies at the approved paths. The source directory of a copy
is never mounted into the child, even when the child has a writable scratch directory.
Bytes are hashed and copied in bounded chunks, and a capture whose copies the private
directory's file system cannot hold is refused before anything is copied.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import stat


CHUNK = 1 << 20


@contextmanager
def _ordinary(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f'committed input traverses a symbolic link: {path}')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f'committed input must be an ordinary file without hard links: {path}')
        yield stream, stat.S_IMODE(before.st_mode)
        after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError(f'committed input changed while captured: {path}')


def content(path):
    with _ordinary(path) as (stream, mode):
        data = stream.read()
    return data, mode


def hash_copy(path, target=None):
    """Hash one checked descriptor, optionally copying its bytes to a new file."""
    created = False
    try:
        with _ordinary(path) as (source, mode):
            digest = hashlib.sha256()
            if target is None:
                while chunk := source.read(CHUNK):
                    digest.update(chunk)
            else:
                with Path(target).open('xb') as destination:
                    created = True
                    while chunk := source.read(CHUNK):
                        digest.update(chunk)
                        destination.write(chunk)
        return digest.hexdigest(), mode
    except BaseException:
        if created:
            Path(target).unlink()
        raise


def _free_bytes(directory):
    return shutil.disk_usage(directory).free


def capture(digests, directory, *, roots=()):
    """Copy and verify all pinned files; return original absolute path -> private copy.

    The copies' total size is accounted against the free space of ``directory`` first, so a launch
    whose private copies cannot fit is refused before its first byte is copied.
    """
    from .locations import outermost
    needed = sum(os.lstat(source).st_size for source in digests)
    free = _free_bytes(directory)
    if needed > free:
        raise ValueError(f'the private copies of the committed inputs need {needed} bytes and {directory} has '
                         f'{free} bytes free; nothing was copied')
    copies = {}
    trees = outermost(root for root in roots if root.is_dir() and any(
        Path(path).is_relative_to(root) for path in digests))
    for number, root in enumerate(trees):
        target = directory / ('tree-' + str(number))
        target.mkdir()
        copies[root] = target
    for number, (source, expected) in enumerate(sorted(digests.items())):
        root = next((p for p in trees if Path(source).is_relative_to(p)), None)
        target = copies[root] / Path(source).relative_to(root) if root else directory / str(number)
        target.parent.mkdir(parents=True, exist_ok=True)
        actual, mode = hash_copy(source, target)
        if actual != expected:
            target.unlink()
            raise ValueError(f'committed input changed while captured: {source}')
        target.chmod(mode & 0o555)
        if root is None:
            copies[Path(source)] = target
    return copies
