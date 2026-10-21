"""Interpreter bootstrap for an adopted workflow's before-load include checks.

This file runs in the selected workflow-manager interpreter. It uses the manager's
source resolver and wraps its include method before the console entry parses any
workflow. It imports no RAVEL dependencies into that separate environment, and
takes its own folder off the import path so that no RAVEL module can be imported there.

A workflow manager starts further interpreters of its own, for example one for each
Python job, and each of them parses the workflow again. A copy of this file named
`sitecustomize.py`, alone in a folder that the bootstrap puts on `PYTHONPATH`, runs
at the start of every such interpreter and wraps the same include method there,
against the same adoption record.
"""
import os
import sys

RECORD_VARIABLE = 'RAVEL_ADOPTION_RECORD'
DIGEST_VARIABLE = 'RAVEL_ADOPTION_RECORD_SHA256'
HOOK = 'sitecustomize.py'

if __name__ == '__main__':
    # Python puts a script's folder first on the import path. This folder holds RAVEL's
    # modules: neither the manager nor the workflow may import one by a bare name.
    _HERE = os.path.realpath(os.path.dirname(__file__))
    sys.path[:] = [entry for entry in sys.path if not entry or os.path.realpath(entry) != _HERE]


def read_record(path, digest):
    """The adoption record of this call, refused when its bytes differ from the digest."""
    import hashlib
    import json
    if not path or not digest:
        raise ValueError('include refused: this manager interpreter names no adoption record')
    with open(path, 'rb') as stream:
        raw = stream.read()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('include refused: interpreter adoption record changed')
    return json.loads(raw)


def checked_include(workflow, record):
    """`workflow.include` with each member checked against the record before it is parsed."""
    import hashlib
    import importlib
    import inspect
    from pathlib import Path
    original = workflow.include
    signature = inspect.signature(original)
    roots = [Path(root).resolve() for root in
             (os.path.dirname(record['snakefile']['path']), record['workdir'], *record['roots'])]
    # Workflow source whose rules the adoption read and showed: the Snakefile, each include and each member.
    members = {record['snakefile']['path'], *record['members'], *(row['resolved'] for row in record['includes'])}
    allowed = {}
    for row in record['files']:
        path = row['path']
        if path in allowed and allowed[path] != row['sha256']:
            raise ValueError(f'include refused: conflicting adoption digests for {path}')
        allowed[path] = row['sha256']

    def checked(self, snakefile, *args, **kwargs):
        sources = importlib.import_module('snakemake.sourcecache')
        arguments = signature.bind(self, snakefile, *args, **kwargs).arguments
        basedir = arguments.get('basedir')
        if basedir is None and self.included_stack:
            basedir = self.included_stack[-1].get_basedir()
        source = sources.infer_source_file(snakefile, basedir)
        if not isinstance(source, sources.LocalSourceFile):
            raise ValueError(f'include refused: {source} is not an adopted local file')
        try:
            path = Path(_source_path(source)).resolve(strict=True)
            if not any(path == root or root in path.parents for root in roots):
                raise ValueError(f'include refused: {path} is outside the allowed roots')
            expected = allowed.get(str(path))
            if expected is None:
                raise ValueError(f'include refused: {path} is outside the adoption record')
            if str(path) not in members:
                raise ValueError(f'include refused: {path} is pinned, but it was not adopted as a workflow member, '
                                 'so its rules were not shown; adopt the workflow again and name it with --member')
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError(f'include refused: {path} changed from its adoption digest')
        except OSError as exc:
            raise ValueError(f'include refused: {source} cannot be read ({exc})') from exc
        # Use the checked canonical destination, rather than re-following an include link.
        return original(self, sources.infer_source_file(str(path)), *args, **kwargs)

    return checked


def _source_path(source):
    """The local path of a source file across workflow-manager releases (a newer one asks whether
    secrets may be dropped from a URI; a local file has none)."""
    import inspect
    method = source.get_path_or_uri
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    return method(False) if 'secret_free' in parameters else method()


def include_boundary(record):
    from contextlib import contextmanager
    import importlib

    @contextmanager
    def boundary():
        # Import the CLI first: it establishes the manager's API/workflow import order.
        importlib.import_module('snakemake.cli')
        workflow = importlib.import_module('snakemake.workflow').Workflow
        original = workflow.include
        workflow.include = checked_include(workflow, record)
        try:
            yield
        finally:
            workflow.include = original
    return boundary()


class _StartedBelow:
    """Wrap the include method when a manager interpreter started below the bootstrap loads it."""

    def find_spec(self, name, path=None, target=None):
        if name != 'snakemake.workflow':
            return None
        import importlib.util
        sys.meta_path.remove(self)
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.loader is not None:
            load = spec.loader.exec_module

            def exec_module(module):
                load(module)
                # A record that is absent or changed fails this import: the manager parses nothing.
                record = read_record(os.environ.get(RECORD_VARIABLE), os.environ.get(DIGEST_VARIABLE))
                module.Workflow.include = checked_include(module.Workflow, record)
            spec.loader.exec_module = exec_module
        return spec


def _customize():
    sys.meta_path.insert(0, _StartedBelow())
    # This file shadows a site customization of the manager's environment: run that one too.
    import importlib.machinery
    import importlib.util
    here = os.path.realpath(os.path.dirname(__file__))
    rest = [entry for entry in sys.path if os.path.realpath(entry or os.curdir) != here]
    spec = importlib.machinery.PathFinder.find_spec('sitecustomize', rest)
    if spec is not None and spec.loader is not None:
        spec.loader.exec_module(importlib.util.module_from_spec(spec))


def main(argv=None):
    import argparse
    from pathlib import Path
    import runpy
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--record-sha256', required=True)
    parser.add_argument('--hook', type=Path, required=True)
    parser.add_argument('--manager', type=Path, required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    record = read_record(args.record, args.record_sha256)
    if sorted(os.listdir(args.hook)) != [HOOK] or (args.hook / HOOK).read_bytes() != Path(__file__).read_bytes():
        raise ValueError(f'include refused: {args.hook} is not the include check of this call')
    # Every interpreter that this one starts runs the hook first and reads the same record.
    os.environ.update({'PYTHONPATH': str(args.hook), RECORD_VARIABLE: str(args.record),
                       DIGEST_VARIABLE: args.record_sha256})
    # Match Python console-script import semantics in this same interpreter.
    sys.path.insert(0, str(args.manager.parent))
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    sys.argv = [str(args.manager), *arguments]
    with include_boundary(record):
        runpy.run_path(str(args.manager), run_name='__main__')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
elif __name__ == 'sitecustomize':
    _customize()
