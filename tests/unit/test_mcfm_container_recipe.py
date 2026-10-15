"""MCFM container recipe: pinned base, receipt writer agreement with the GPL four-lepton add-on."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.workflow.backends import oci_local

RECIPE = Path(__file__).resolve().parents[2] / 'native/containers/mcfm'
ASSETS = Path(__file__).resolve().parents[2] / 'addons/gpl/mcfm-amplitudes'
COMMIT = json.loads((ASSETS / 'addon.json').read_text())['upstream']['commit']


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def test_containerfile_base_is_refused_until_its_digest_is_recorded():
    text = (RECIPE / 'Containerfile').read_text()
    base = json.loads((RECIPE / 'base-image.json').read_text())
    digest = base['base']['digest']
    assert digest and digest.startswith('sha256:') and len(digest) == 71
    assert oci_local.containerfile_bases(text) == [f"registry.fedoraproject.org/fedora@{digest}"]
    placeholder = text.replace(digest, 'sha256:RECORD-DIGEST-AT-FIRST-APPROVED-PULL')
    with pytest.raises(ValueError, match='not pinned by digest'):
        oci_local.containerfile_bases(placeholder)
    assert base['mcfm']['commit'] == COMMIT and base['base']['platform'] == 'linux/arm64'


def test_scripts_parse():
    for name in ('build-mcfm.sh', 'check-mcfm.sh'):
        subprocess.run(['bash', '-n', str(RECIPE / name)], check=True)
    assert COMMIT in (RECIPE / 'build-mcfm.sh').read_text()


def test_receipt_writer_matches_adapter_contract(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    for tool in ('gcc', 'g++', 'gfortran', 'cmake'):
        (bin_dir / tool).write_text(f'#!/bin/sh\necho "{tool} (fake) 14.2.1"\n')
        (bin_dir / tool).chmod(0o755)
    lib = tmp_path / 'usr/lib64/libgfortran.so.5'
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b'lib')
    (bin_dir / 'ldd').write_text(f'#!/bin/sh\necho "\tlibgfortran.so.5 => {lib} (0x0000)"\necho "\tlinux-vdso.so.1 (0x0)"\n')
    (bin_dir / 'ldd').chmod(0o755)
    overlay = tmp_path / 'overlay'
    (overlay / 'ravel').mkdir(parents=True)
    (overlay / 'src/Procdep').mkdir(parents=True)
    (overlay / 'src/Procdep/lowint.f').write_text('lowint\n')
    for name in ('ravel_bridge.f90', 'ravel_driver.f90', 'lowint-capture.patch', 'CMakeLists-ravel.cmake'):
        (overlay / 'ravel' / name).write_bytes((ASSETS / name).read_bytes())
    build = tmp_path / 'build'
    (build / 'local/lib').mkdir(parents=True)
    (build / 'local/lib/libqcdloop.a').write_bytes(b'archive')
    (build / 'ravel_mcfm_amplitudes').write_bytes(b'\x7fELF fake')
    env = {'PATH': f'{bin_dir}:/usr/bin:/bin'}
    subprocess.run([sys.executable, str(RECIPE / 'write_mcfm_receipt.py'), '--upstream', str(tmp_path / 'up'),
                    '--overlay', str(overlay), '--build', str(build), '--commit', COMMIT,
                    '--command', 'cmake -S x -B y'], check=True, env=env)
    receipt = json.loads((build / 'build-receipt.json').read_text())
    assert set(receipt) == {'schema_version', 'source_commit', 'binary_sha256', 'overlay_sources', 'compiled_source_sha256',
                            'toolchain_inputs', 'linked_inputs', 'build_command', 'build_status'}
    assert receipt['source_commit'] == COMMIT and receipt['build_status'] == 'completed'
    roster = {p.relative_to(overlay).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(overlay.rglob('*')) if p.is_file()}
    assert receipt['compiled_source_sha256'] == hashlib.sha256(encoded(roster)).hexdigest()
    assert receipt['overlay_sources'] == {n: hashlib.sha256((ASSETS / n).read_bytes()).hexdigest()
                                          for n in ('ravel_bridge.f90', 'ravel_driver.f90', 'lowint-capture.patch', 'CMakeLists-ravel.cmake')}
    for pin in receipt['toolchain_inputs'] + receipt['linked_inputs']:
        assert set(pin) == {'path', 'sha256'} and Path(pin['path']).is_relative_to(build)
    linked = json.loads((build / 'linked-libraries.json').read_text())
    assert linked['libraries'][0]['path'] == str(lib.resolve())


@pytest.mark.parametrize('recipe', ['mcfm', 'jhugen-mela'])
def test_amd64_containerfile_pins_the_amd64_base_by_digest(recipe):
    root = RECIPE.parent / recipe
    text = (root / 'Containerfile.amd64').read_text()
    base = json.loads((root / 'base-image.json').read_text())['base_amd64']
    assert base['platform'] == 'linux/amd64' and base['digest'].startswith('sha256:') and len(base['digest']) == 71
    assert 'FROM --platform=linux/amd64 ' in text
    assert oci_local.containerfile_bases(text) == [f"registry.fedoraproject.org/fedora@{base['digest']}"]
    arm = json.loads((root / 'base-image.json').read_text())['base']
    assert base['digest'] != arm['digest']


def test_wget_stand_in_serves_only_prefetched_files(tmp_path):
    shim = RECIPE.parent / 'jhugen-mela/wget-from-cache.sh'
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'collier-1.2.0.tar.gz').write_bytes(b'archive')
    work = tmp_path / 'work'
    work.mkdir()
    env = {'PATH': '/usr/bin:/bin', 'RAVEL_FETCH_CACHE': str(cache)}
    ok = subprocess.run(['bash', str(shim), '--no-check-certificate', '-q', 'https://host.example/dir/collier-1.2.0.tar.gz'],
                        cwd=work, env=env)
    assert ok.returncode == 0 and (work / 'collier-1.2.0.tar.gz').read_bytes() == b'archive'
    renamed = subprocess.run(['bash', str(shim), '-O', 'x.tgz', 'https://host.example/collier-1.2.0.tar.gz'], cwd=work, env=env)
    assert renamed.returncode == 0 and (work / 'x.tgz').read_bytes() == b'archive'
    missing = subprocess.run(['bash', str(shim), 'https://host.example/other.so'], cwd=work, env=env, capture_output=True)
    assert missing.returncode == 8 and not (work / 'other.so').exists()
    unset = subprocess.run(['bash', str(shim), 'https://host.example/collier-1.2.0.tar.gz'], cwd=work,
                           env={'PATH': '/usr/bin:/bin'}, capture_output=True)
    assert unset.returncode != 0


def test_jhugen_mela_amd64_image_carries_tcsh_and_the_fetch_stand_in():
    text = (RECIPE.parent / 'jhugen-mela/Containerfile.amd64').read_text()
    assert ' tcsh ' in text and 'wget-from-cache.sh' in text
