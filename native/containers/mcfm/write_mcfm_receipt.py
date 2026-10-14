"""Write the MCFM build receipt for RAVEL's MCFM amplitude program.

Runs inside the toolchain container with the standard library only. Paths are
host paths mounted at identical container paths, so every pin is valid on the
host. Compilers and system libraries come from the image; their identity is
recorded in toolchain.json and linked-libraries.json inside the build directory,
which are the pinned toolchain and linked inputs (the image digest is recorded by
the launcher that ran this build).
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess

OVERLAY = ('ravel_bridge.f90', 'ravel_driver.f90', 'lowint-capture.patch', 'CMakeLists-ravel.cmake')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pin(path):
    # The adapter's file pins carry exactly path and sha256.
    path = Path(path)
    return {'path': str(path), 'sha256': sha(path)}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return pin(path)


def main():
    ap = argparse.ArgumentParser()
    for name in ('upstream', 'overlay', 'build', 'commit', 'command'):
        ap.add_argument('--' + name, required=True)
    args = ap.parse_args()
    overlay, build = Path(args.overlay), Path(args.build)
    binary = build / 'ravel_mcfm_amplitudes'
    compiled = {}
    for path in sorted(overlay.rglob('*')):
        if path.is_file():
            compiled[path.relative_to(overlay).as_posix()] = sha(path)
    tools = {}
    for tool in ('gcc', 'g++', 'gfortran', 'cmake'):
        located = subprocess.run(['sh', '-c', f'command -v {tool}'], capture_output=True, text=True).stdout.strip()
        real = str(Path(located).resolve())
        version = subprocess.run([tool, '--version'], capture_output=True, text=True).stdout.splitlines()[0]
        tools[tool] = {'path': real, 'sha256': sha(real), 'version': version}
    toolchain = write(build / 'toolchain.json', {'schema_version': 1, 'machine': platform.machine(), 'tools': tools,
                                                 'provided_by': 'container image (digest in the launcher record)'})
    libraries = []
    for line in subprocess.run(['ldd', str(binary)], capture_output=True, text=True).stdout.splitlines():
        parts = line.split('=>')
        target = (parts[1] if len(parts) > 1 else parts[0]).strip().split(' (')[0].strip()
        if target.startswith('/') and Path(target).is_file():
            libraries.append({'path': str(Path(target).resolve()), 'sha256': sha(Path(target).resolve())})
    linked = write(build / 'linked-libraries.json', {'schema_version': 1, 'binary': str(binary), 'libraries': libraries,
                                                     'provided_by': 'container image (digest in the launcher record)'})
    built_libraries = sorted(p for p in (build / 'local/lib').rglob('*') if p.is_file()) if (build / 'local/lib').is_dir() else []
    receipt = {
        'schema_version': 1,
        'source_commit': args.commit,
        'binary_sha256': sha(binary),
        'overlay_sources': {name: sha(overlay / 'ravel' / name) for name in OVERLAY},
        'compiled_source_sha256': hashlib.sha256(encoded(compiled)).hexdigest(),
        'toolchain_inputs': [toolchain],
        'linked_inputs': [linked, *[pin(p) for p in built_libraries]],
        'build_command': ['/bin/bash', '-c', args.command],
        'build_status': 'completed',
    }
    (build / 'build-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
