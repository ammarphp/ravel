"""Container launcher used by native adapters for Linux-only engines (for example MCFM)."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from ravel.workflow import execution_backend as eb
from ravel.workflow.backends import oci_local

import execution_backend_fakes as fakes

DIGEST = 'registry.example/ravel/mcfm-toolchain@sha256:' + 'e' * 64


@pytest.fixture
def podman(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_CONTAINER_HOME', str(tmp_path / 'container-home'))
    state = tmp_path / 'podman.json'
    wrapper = fakes.install(tmp_path / 'bin', 'podman', fakes.PODMAN, state)
    monkeypatch.setenv('PATH', fakes.path_with(tmp_path / 'bin'))
    return wrapper, state


def launcher(wrapper, **changes):
    value = {'kind': 'oci-local', 'image': {'reference': DIGEST, 'platform': oci_local.host_platform()},
             'client': {'path': str(wrapper), 'sha256': eb.file_sha256(wrapper)}, 'connection': 'ravel',
             'cpus': 1, 'memory_mib': 2048, 'env': {'LHAPDF_DATA_PATH': '/opt/pdf'}}
    value.update(changes)
    return value


def test_launcher_validation(podman):
    wrapper, _ = podman
    assert oci_local.validate_launcher(launcher(wrapper))
    with pytest.raises(ValueError, match='digest'):
        oci_local.validate_launcher(launcher(wrapper, image={'reference': 'fedora:41', 'platform': oci_local.host_platform()}))
    with pytest.raises(ValueError, match='changed'):
        oci_local.validate_launcher(launcher(wrapper, client={'path': str(wrapper), 'sha256': '0' * 64}))
    with pytest.raises(ValueError, match='credential'):
        oci_local.validate_launcher(launcher(wrapper, env={'API_TOKEN': 'x'}))


def test_launcher_runs_same_argv_with_identical_paths(tmp_path, podman):
    wrapper, state = podman
    tree = tmp_path / 'mcfm-build'
    tree.mkdir()
    tool = tree / 'tool.sh'
    tool.write_text('#!/bin/sh\necho "point $1" > result.txt\n')
    tool.chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    command = oci_local.launcher_command(launcher(wrapper), [str(tool), 'card.ini'], workdir=work,
                                         readonly=[tree], writable=[work], name='ravel-launch-test')
    assert command[0] == '/usr/bin/env' and f"XDG_CONFIG_HOME={tmp_path / 'container-home/config'}" in command
    assert f'{tree.resolve()}:{tree.resolve()}:ro' in command and f'{work.resolve()}:{work.resolve()}:rw' in command
    assert command[command.index('--network') + 1] == 'none' and '--rm' in command
    subprocess.run(command, check=True)
    assert (work / 'result.txt').read_text().strip() == 'point card.ini'
    run = json.loads(state.read_text())['runs'][0]
    assert run['image'] == DIGEST and run['env'] == {'LHAPDF_DATA_PATH': '/opt/pdf'}
    cleanup = oci_local.cleanup_launch(launcher(wrapper), 'ravel-launch-test')
    assert cleanup['state'] == 'absent' and cleanup['requires_recovery'] is False


def test_cli_launcher_record_and_launch(tmp_path, podman, monkeypatch, capsys):
    wrapper, state = podman
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    out = tmp_path / 'launcher.json'
    assert eb.main(['launcher', '--image-reference', DIGEST, '--cpus', '2', '--memory-mib', '1024',
                    '--env', 'LHAPDF_DATA_PATH=/opt/pdf', '--out', str(out)]) == 0
    record = json.loads(out.read_text())
    assert record['client']['sha256'] == eb.file_sha256(wrapper) and record['cpus'] == 2
    work = tmp_path / 'work'
    work.mkdir()
    capsys.readouterr()
    assert eb.main(['launch', '--launcher', str(out), '--workdir', str(work), '--writable', str(work),
                    '--', '/bin/sh', '-c', 'echo built > marker']) == 0
    assert json.loads(capsys.readouterr().out)['executed'] is False and not (work / 'marker').exists()
    # --execute runs only as an approved supervised stage that pins the launcher.
    assert eb.main(['launch', '--launcher', str(out), '--workdir', str(work), '--writable', str(work), '--execute',
                    '--', '/bin/sh', '-c', 'echo built > marker']) == 2
    assert not (work / 'marker').exists()
    from ravel.workflow import stage_supervisor
    from test_checkin2_gate import _run
    monkeypatch.setenv('WORKFLOW_STATE_UTC', '2026-10-08T00:00:00Z')
    root = _run(tmp_path, plan='smoke', checkin2=False)
    command = [sys.executable, '-m', 'ravel.workflow.execution_backend', 'launch', '--rundir', str(root),
               '--stage', 'container', '--launcher', str(out), '--workdir', str(work), '--writable', str(work),
               '--execute', '--', '/bin/sh', '-c', 'echo built > marker']
    code = stage_supervisor.supervise('container', root, 1, 'logs/container.log', command, kill_secs=60.0,
                                      poll=0.1, grace=3.0, inputs=[str(out)], required_plan='smoke')
    assert code == 0, (root / 'logs/container.log').read_text()
    assert (work / 'marker').read_text().strip() == 'built'


def test_cli_launcher_accepts_a_foreign_platform_only_with_declared_emulation(tmp_path, podman, monkeypatch, capsys):
    foreign = 'linux/amd64' if oci_local.host_platform() != 'linux/amd64' else 'linux/arm64'
    refused = tmp_path / 'refused.json'
    assert eb.main(['launcher', '--image-reference', DIGEST, '--platform', foreign, '--out', str(refused)]) == 2
    assert 'emulation' in capsys.readouterr().err and not refused.exists()
    out = tmp_path / 'launcher.json'
    assert eb.main(['launcher', '--image-reference', DIGEST, '--platform', foreign, '--emulation', '--out', str(out)]) == 0
    image = json.loads(out.read_text())['image']
    assert image == {'platform': foreign, 'reference': DIGEST, 'emulation': True}
    work = tmp_path / 'work'
    work.mkdir()
    capsys.readouterr()
    assert eb.main(['launch', '--launcher', str(out), '--workdir', str(work), '--writable', str(work), '--', 'true']) == 0
    argv = json.loads(capsys.readouterr().out)['argv']
    assert argv[argv.index('--platform') + 1] == foreign
