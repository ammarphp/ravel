"""One-call observational verification. No persistent cache or atomic-snapshot claim."""
from pathlib import Path
import hashlib
import os
import stat


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class ValidationSession:
    def __init__(self, rundir, *, resolve_path, read_json, runtime_context, digest,
                 state_name, tracked=()):
        self.rundir = Path(rundir)
        self.resolve_path = resolve_path
        self.read_json = read_json
        self.runtime_context = runtime_context
        self.digest = digest
        self.runtime = runtime_context()
        self.tracked = [(obj, digest(obj)) for obj in tracked]
        self.hashes = {}
        self.files = {}
        self.queries = {}
        self.valid_json = set()
        self.stages = {}
        self.hash_bytes = 0
        self.hash_calls = 0
        self.closed = False
        self.ledger = self.rundir / state_name
        self.ledger_existed = self.ledger.exists()
        self.ledger_digest = self.hash_file(self.ledger) if self.ledger_existed else None

    def observe(self, path):
        value = identity(Path(path).stat())
        if not stat.S_ISREG(value[2]):
            raise ValueError('artifact is not a regular file: ' + str(path))
        previous = self.files.get(str(path))
        if previous is not None and value != previous:
            raise ValueError('artifact identity changed during validation: ' + str(path))
        return value

    def hash_file(self, path):
        if self.closed:
            raise ValueError('validation session is already closed')
        path = Path(path)
        before = self.observe(path)
        if before not in self.hashes:
            value = hashlib.sha256()
            with path.open('rb') as stream:
                if identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('artifact replaced before opening: ' + str(path))
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
                    self.hash_bytes += len(block)
                if identity(os.fstat(stream.fileno())) != before:
                    raise ValueError('artifact changed while hashing: ' + str(path))
            self.hash_calls += 1
            if identity(path.stat()) != before:
                raise ValueError('artifact pathname changed while hashing: ' + str(path))
            self.hashes[before] = value.hexdigest()
        if self.observe(path) != before:
            raise ValueError('artifact changed during cache reuse: ' + str(path))
        self.files[str(path)] = before
        return self.hashes[before]

    def census(self, value, outputs):
        path = self.resolve_path(self.rundir, value, output=outputs)
        if not path.exists():
            raise ValueError('missing artifact: ' + value)
        if path.is_file():
            return path, ('file',), [path]
        if not path.is_dir():
            raise ValueError('unsupported artifact kind: ' + value)
        children = sorted(path.rglob('*'))
        if any(p.is_symlink() for p in children):
            raise ValueError('artifact directory contains an untracked symlink: ' + value)
        # Include directory identities and empty subdirectories in the ending
        # census; file content identities are checked separately using fstat.
        signature = [('root', identity(path.stat()))]
        files = []
        for child in children:
            mode = child.stat().st_mode
            if stat.S_ISDIR(mode):
                signature.append((child.relative_to(path).as_posix(), 'directory', identity(child.stat())))
            elif stat.S_ISREG(mode):
                signature.append((child.relative_to(path).as_posix(), 'file'))
                files.append(child)
            else:
                raise ValueError('unsupported artifact directory entry: ' + str(child))
        return path, tuple(signature), files

    def snapshot(self, paths, *, outputs=False):
        result = {}
        for value in paths:
            if not isinstance(value, str) or not value.strip():
                raise ValueError('artifact paths must be nonblank strings')
            path, census, files = self.census(value, outputs)
            query = (value, outputs)
            seen = self.queries.get(query)
            current = (str(path), census)
            if seen is not None and seen != current:
                raise ValueError('artifact path or inventory changed during validation: ' + value)
            self.queries[query] = current
            if not files:
                raise ValueError('empty artifact: ' + value)
            entries = []
            for item in files:
                observed = self.observe(item)
                size = observed[3]
                if outputs and size == 0:
                    raise ValueError('empty output: ' + str(item))
                content_digest = self.hash_file(item)
                if outputs and item.suffix.lower() == '.json' and observed not in self.valid_json:
                    self.read_json(item)
                    if self.observe(item) != observed:
                        raise ValueError('JSON changed during validation: ' + str(item))
                    self.valid_json.add(observed)
                entries.append({'name': '.' if item == path else item.relative_to(path).as_posix(),
                                'size': size, 'sha256': content_digest})
            if str(path) in result:
                raise ValueError('duplicate artifact path: ' + value)
            result[str(path)] = {'kind': 'file' if path.is_file() else 'directory', 'files': entries}
        return result

    def close(self):
        self.closed = True
        self.hashes.clear()
        self.stages.clear()

    def finish(self):
        if self.closed:
            raise ValueError('validation session is already closed')
        try:
            for (value, outputs), previous in self.queries.items():
                path, census, _ = self.census(value, outputs)
                if (str(path), census) != previous:
                    raise ValueError('artifact path or directory inventory changed before return: ' + value)
            for path, previous in self.files.items():
                if self.observe(path) != previous:
                    raise ValueError('artifact changed before return: ' + path)
            if self.ledger.exists() != self.ledger_existed:
                raise ValueError('execution ledger appeared or disappeared during validation')
            # A second small byte read binds ledger content as well as identity.
            if self.ledger_existed:
                expected_identity = self.files[str(self.ledger)]
                if self.observe(self.ledger) != expected_identity:
                    raise ValueError('execution ledger changed before final read')
                with self.ledger.open('rb') as stream:
                    if identity(os.fstat(stream.fileno())) != expected_identity:
                        raise ValueError('execution ledger replaced before final read')
                    final_digest = hashlib.sha256(stream.read()).hexdigest()
                    if identity(os.fstat(stream.fileno())) != expected_identity:
                        raise ValueError('execution ledger changed during final read')
                if self.observe(self.ledger) != expected_identity:
                    raise ValueError('execution ledger pathname changed during final read')
                if final_digest != self.ledger_digest:
                    raise ValueError('execution ledger changed during validation')
            if self.runtime_context() != self.runtime:
                raise ValueError('runtime changed during validation')
            if any(self.digest(obj) != before for obj, before in self.tracked):
                raise ValueError('supplied state or plan changed during validation')
            return []
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return ['validation final census unavailable: ' + str(exc)]
        finally:
            # No reuse after this logical validation call, even following error.
            self.close()
