"""Execute one captured facility job inside the qualified local OS sandbox.

The scheduler wrapper runs this trusted module with an isolated interpreter. Only
explicit file inputs and a fresh output directory enter the payload's sandbox.
A facility must qualify its interpreter installation and shared-filesystem paths;
this module never exports the controller store or accepts an unconfined fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .capability import ordinary_input

KEYS = {'schema_version', 'script_path', 'script_sha256', 'reads', 'output_dir', 'resources'}
LIMITS = {'cpus', 'memory_mib', 'wall_seconds'}
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


def _verified_file(value, expected):
    path = ordinary_input(value)
    if not isinstance(expected, str) or not SHA256.fullmatch(expected):
        raise ValueError('job input requires a sha256 digest')
    from ravel.workflow.execution import file_hash
    if file_hash(path) != expected:
        raise ValueError('captured job script or declared input digest changed; nothing was started')
    return path


def validate(document):
    if type(document) is not dict or set(document) != KEYS or type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('a version 1 captured job descriptor is required')
    script = _verified_file(document['script_path'], document['script_sha256'])
    reads = document['reads']
    if type(reads) is not dict:
        raise ValueError('job reads must map explicit input files to sha256 digests')
    for value, expected in reads.items():
        _verified_file(value, expected)
    limits = document['resources']
    if type(limits) is not dict or set(limits) != LIMITS or any(type(v) is not int or v <= 0 for v in limits.values()):
        raise ValueError('job resources require positive integer cpus/memory_mib/wall_seconds')
    value = document['output_dir']
    if not isinstance(value, str) or not os.path.isabs(value) or '..' in Path(value).parts:
        raise ValueError('job output directory must be absolute')
    output = Path(value)
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('job output directory cannot traverse symbolic links')
    if any(p == output or p.is_relative_to(output) for p in [script, *(Path(v) for v in reads)]):
        raise ValueError('job outputs cannot contain captured inputs')
    return script, output


def _receipt(output, record):
    fd, value = tempfile.mkstemp(prefix='.receipt-', dir=output)
    temporary = Path(value)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, sort_keys=True, allow_nan=False)
            stream.write('\n')
        os.replace(temporary, output / 'receipt.json')
    finally:
        temporary.unlink(missing_ok=True)


def run(document):
    """Run one exact payload, finish its sandbox, write its receipt and return exit status."""
    from ravel.controller import confine
    script, output = validate(document)
    missing = []
    ancestor = output
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    digests = {str(script): document['script_sha256'], **document['reads']}
    spec = {'argv': ['/bin/sh', str(script)], 'reads': list(digests),
            'input_digests': digests, 'writes': [str(output)], 'cwd': str(output),
            'env': {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'RAVEL_OUTPUT_DIR': str(output)},
            'limits': dict(document['resources']), 'label': 'captured-facility-job'}
    # prepare/start are the same two operations popen uses. Inspecting the prepared
    # plan before start additionally rules out the operator's unconfined fallback.
    try:
        plan = confine.prepare(spec)
        if plan.kind != confine.CONFINED:
            raise confine.LaunchHeld('sandbox_required', 'facility jobs never run unconfined')
    except BaseException:
        for directory in missing:
            try:
                directory.rmdir()
            except OSError:
                break
        raise
    with (output / 'stdout').open('wb') as stdout, (output / 'stderr').open('wb') as stderr:
        process = confine.start(plan, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        code = None
        try:
            code = process.wait(timeout=document['resources']['wall_seconds'])
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            code = 124
        finally:
            finish = confine.finish(process)
    _receipt(output, {'schema_version': 1, 'exit_code': code, 'script_sha256': document['script_sha256'],
                      'confinement': plan.record, 'finish': finish})
    return code if code >= 0 else 128 - code


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('descriptor')
    args = parser.parse_args(argv)
    try:
        descriptor = ordinary_input(args.descriptor)
        return run(json.loads(descriptor.read_text()))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
