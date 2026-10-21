"""Private scientific file creation, independent of the invoking umask."""
from pathlib import Path
import os
import secrets
import stat


def mkdir(path):
    """Create every missing ancestor privately; refuse links in the destination."""
    path = Path(path)
    missing = []
    for parent in (path, *path.parents):
        if parent.is_symlink():
            # System aliases are resolved before examining the ordinary path.
            raise ValueError(f'private path traverses a symbolic link: {parent}; use its real path')
        if not parent.exists():
            missing.append(parent)
        elif not parent.is_dir():
            raise ValueError(f'private directory is not ordinary: {parent}')
    for parent in reversed(missing):
        try:
            parent.mkdir(mode=0o700)
        except FileExistsError:
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise ValueError(f'private directory creation raced an unsafe path: {parent}; choose a new path')
    return path


def write(path, data, *, mode=0o600, exclusive=False):
    """Write private bytes atomically, optionally preserving stricter owner permissions."""
    path = Path(path)
    mkdir(path.parent)
    mode &= 0o600
    temporary = path if exclusive else path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            if path.is_symlink():
                raise ValueError(f'private output is a link: {path}; choose an ordinary output')
            os.replace(temporary, path)
    finally:
        if not exclusive:
            temporary.unlink(missing_ok=True)


def copy(source, destination):
    """Stream a regular source to an exclusive private file without widening its mode."""
    source, destination = Path(source), Path(destination)
    mkdir(destination.parent)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'private copy requires an ordinary file: {source}')
        target = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         stat.S_IMODE(info.st_mode) & 0o600)
        with os.fdopen(target, 'wb') as output:
            while block := os.read(fd, 1024 * 1024):
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(fd)
