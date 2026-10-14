"""oci-local and site adapters against fake clients on PATH."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

from ravel.workflow import execution_backend as eb
from ravel.workflow.backends import oci_local, site_batch

import execution_backend_fakes as fakes

DIGEST = 'registry.example/ravel/tool@sha256:' + 'd' * 64


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('RAVEL_CONTAINER_HOME', str(tmp_path / 'container-home'))
    eb._INSTANCES.clear()
    # A backend job is dispatched only under the machine lease of an approved stage; these tests
    # hold it in the test lock domain as the stage's supervisor would.
    with eb.machine_lease('execution-backend adapter unit test'):
        yield


def wait_terminal(plan, handle, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        observation = eb.observe(plan, handle)
        if observation['state'] in eb.TERMINAL:
            return observation
        time.sleep(0.05)
    raise AssertionError('job did not finish')


# ---------------------------------------------------------------- oci-local
@pytest.fixture
def podman(tmp_path, monkeypatch):
    state = tmp_path / 'podman-state.json'
    fakes.install(tmp_path / 'bin', 'podman', fakes.PODMAN, state)
    monkeypatch.setenv('PATH', fakes.path_with(tmp_path / 'bin'))
    return state


def oci_spec(tmp_path, **extra):
    data = tmp_path / 'card.txt'
    data.write_text('alpha\nbeta\n')
    pdf = tmp_path / 'lhapdf'
    (pdf / 'SetA').mkdir(parents=True, exist_ok=True)
    (pdf / 'SetA/SetA.info').write_text('Flavors: [1, 2, 21]\n')
    spec = {'schema_version': 1, 'backend': 'oci-local', 'stage': 'mcfm-point',
            'argv': ['/bin/sh', '-c', 'wc -l < /ravel/input/card.txt > /ravel/output/lines.txt && test -d "$LHAPDF_DATA_PATH/SetA"'],
            'inputs': [{'path': str(data), 'mount': '/ravel/input/card.txt'}],
            'readonly_trees': [{'path': str(pdf), 'mount': '/opt/lhapdf', 'env': 'LHAPDF_DATA_PATH'}],
            'outputs': [{'name': 'lines.txt', 'destination': 'out/lines.txt'}],
            'resources': {'cpus': 2, 'memory_mib': 1024, 'wall_seconds': 600},
            'image': {'reference': DIGEST, 'platform': oci_local.host_platform()}}
    spec.update(extra)
    return spec


def test_oci_plan_pins_client_and_refuses_unpinned_or_foreign_arch(tmp_path, podman):
    plan = eb.prepare(oci_spec(tmp_path))
    assert plan['backend']['client']['sha256'] == eb.file_sha256(tmp_path / 'bin/podman')
    assert plan['backend']['container_home'] == str(tmp_path / 'container-home')
    foreign = 'linux/amd64' if oci_local.host_platform() == 'linux/arm64' else 'linux/arm64'
    with pytest.raises(ValueError, match='emulation'):
        eb.prepare(oci_spec(tmp_path, image={'reference': DIGEST, 'platform': foreign}))
    assert eb.prepare(oci_spec(tmp_path, image={'reference': DIGEST, 'platform': foreign, 'emulation': True}))
    with pytest.raises(ValueError, match='digest'):
        eb.prepare(oci_spec(tmp_path, image={'reference': 'fedora:41', 'platform': oci_local.host_platform()}))
    spec = oci_spec(tmp_path)
    del spec['inputs'][0]['mount']
    with pytest.raises(ValueError, match='guest mount'):
        eb.prepare(spec)


def test_oci_round_trip_with_readonly_mounts_and_limits(tmp_path, podman):
    plan = eb.prepare(oci_spec(tmp_path))
    handle = eb.submit(plan, tmp_path / 'attempt')
    state = json.loads(podman.read_text())
    container = next(iter(state['containers'].values()))
    assert f"{tmp_path / 'card.txt'}:/ravel/input/card.txt:ro" in container['mounts']
    assert f"{tmp_path / 'lhapdf'}:/opt/lhapdf:ro" in container['mounts']
    assert container['env']['LHAPDF_DATA_PATH'] == '/opt/lhapdf'
    assert container['host'] == {'NanoCpus': 2 * 10 ** 9, 'Memory': 1024 * 1024 ** 2, 'PidsLimit': oci_local.PIDS_LIMIT}
    create = next(c for c in state['calls'] if 'create' in c)
    assert '--network' in create and create[create.index('--network') + 1] == 'none'
    assert '--pull' in create and create[create.index('--pull') + 1] == 'never'
    assert wait_terminal(plan, handle)['state'] == 'succeeded'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    receipt = eb.fetch(plan, handle, rundir)
    assert (rundir / 'out/lines.txt').read_text().strip() == '2'
    assert receipt['outputs'][0]['sha256'] == eb.file_sha256(rundir / 'out/lines.txt')
    assert not json.loads(podman.read_text())['containers'], 'container removed after fetch'
    journal = (tmp_path / 'attempt/container-client.jsonl').read_text()
    assert '--connection' in journal


def test_oci_client_uses_prefix_xdg_dirs(tmp_path, podman, monkeypatch):
    env = oci_local.client_environment()
    home = tmp_path / 'container-home'
    assert env['XDG_CONFIG_HOME'] == str(home / 'config') and env['XDG_DATA_HOME'] == str(home / 'data')
    result = oci_local.machine('init', name='ravel', execute=False)
    assert result['executed'] is False and 'init' in result['argv']
    result = oci_local.machine('init', name='ravel', execute=True)
    machines = json.loads(podman.read_text())['machines']
    assert machines[0]['xdg_config'] == str(home / 'config')


def test_oci_cancel_stops_owned_container(tmp_path, podman, monkeypatch):
    podman.write_text(json.dumps({'hold': True}))
    plan = eb.prepare(oci_spec(tmp_path))
    handle = eb.submit(plan, tmp_path / 'attempt')
    assert eb.observe(plan, handle)['state'] == 'running'
    assert eb.cancel(plan, handle, wait_seconds=5)['state'] == 'cancelled'


def test_oci_refuses_container_not_owned(tmp_path, podman):
    plan = eb.prepare(oci_spec(tmp_path))
    handle = eb.submit(plan, tmp_path / 'attempt')
    state = json.loads(podman.read_text())
    next(iter(state['containers'].values()))['labels']['org.ravel.plan'] = 'f' * 64
    podman.write_text(json.dumps(state))
    with pytest.raises(ValueError, match='not the one this plan owns'):
        eb.observe(plan, handle)


def test_oci_recover_by_tag_after_crash(tmp_path, podman, monkeypatch):
    plan = eb.prepare(oci_spec(tmp_path))
    backend = eb.get('oci-local')
    original = backend.submit

    def crash(plan, handle):
        original(plan, handle)
        raise KeyboardInterrupt
    monkeypatch.setattr(backend, 'submit', crash)
    with pytest.raises(KeyboardInterrupt):
        eb.submit(plan, tmp_path / 'attempt', backend=backend)
    # Only the crash is undone: undoing every patch would also drop the test lock domain of the lease.
    monkeypatch.setattr(backend, 'submit', original)
    handle = eb.read_handle(tmp_path / 'attempt')
    result = eb.recover(plan, handle)
    assert result['handle']['remote']['name'] == handle['tag']
    assert result['observation']['state'] == 'succeeded'


def test_image_build_requires_digest_pinned_bases(tmp_path, podman):
    context = tmp_path / 'ctx'
    context.mkdir()
    containerfile = context / 'Containerfile'
    containerfile.write_text('FROM fedora:41\nRUN true\n')
    with pytest.raises(ValueError, match='not pinned by digest'):
        oci_local.build_image(containerfile, context, 'localhost/x', receipt=tmp_path / 'r.json')
    containerfile.write_text(f'FROM {DIGEST} AS build\nRUN true\nFROM build\n')
    dry = oci_local.build_image(containerfile, context, 'localhost/x', receipt=tmp_path / 'r.json')
    assert dry['executed'] is False and not (tmp_path / 'r.json').exists()
    record = oci_local.build_image(containerfile, context, 'localhost/x', receipt=tmp_path / 'r.json', execute=True)
    assert record['image']['id'] == 'sha256:' + 'b' * 64
    assert json.loads((tmp_path / 'r.json').read_text())['bases'] == [DIGEST]


# ---------------------------------------------------------------- site
@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    state = tmp_path / 'scheduler-state.json'
    fakes.install_scheduler(tmp_path / 'bin', state)
    monkeypatch.setenv('PATH', fakes.path_with(tmp_path / 'bin'))
    return state


def site_spec(tmp_path, scheduler_name, **extra):
    eos = tmp_path / 'eos/user/a/analysis'
    spec = {'schema_version': 1, 'backend': 'site', 'stage': 'skim-pass',
            'argv': [sys.executable, '-c', 'import os;open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"h.json"),"w").write("{\\"n\\": 3}");'
                     'open(os.path.join(os.environ["RAVEL_OUTPUT_DIR"],"skim.root"),"w").write("skim")'],
            'outputs': [{'name': 'h.json', 'destination': 'out/h.json'},
                        {'name': 'skim.root', 'remote_uri': str(eos / 'skim.root')}],
            'quantities': [{'name': 'n', 'output': 'h.json', 'pointer': '/n'}],
            'resources': {'cpus': 1, 'memory_mib': 2000, 'wall_seconds': 7200},
            'site': {'scheduler': scheduler_name, 'options': {'+JobFlavour': '"longlunch"'} if scheduler_name == 'htcondor' else {'partition': 'short'}}}
    spec.update(extra)
    return spec


@pytest.mark.parametrize('scheduler_name', ['htcondor', 'slurm'])
def test_site_round_trip_with_eos_output(tmp_path, scheduler, scheduler_name):
    plan = eb.prepare(site_spec(tmp_path, scheduler_name))
    handle = eb.submit(plan, tmp_path / 'attempt')
    job = tmp_path / 'attempt/job'
    if scheduler_name == 'htcondor':
        sub = (job / 'job.sub').read_text()
        assert 'request_memory = 2000' in sub and f'+RavelTag = "{handle["tag"]}"' in sub
        assert '+MaxRuntime = 7200' in sub and '+JobFlavour = "longlunch"' in sub
    else:
        sbatch = (job / 'job.sbatch').read_text()
        assert f'#SBATCH --job-name={handle["tag"]}' in sbatch and '#SBATCH --time=2:00:00' in sbatch
        assert '#SBATCH --partition=short' in sbatch
    assert wait_terminal(plan, handle)['state'] == 'succeeded'
    rundir = tmp_path / 'run'
    rundir.mkdir()
    receipt = eb.fetch(plan, handle, rundir)
    assert receipt['quantities'] == {'n': 3}
    assert receipt['remote_outputs'][0]['exists'] is True
    assert (tmp_path / 'eos/user/a/analysis/skim.root').read_text() == 'skim'


@pytest.mark.parametrize('scheduler_name', ['htcondor', 'slurm'])
def test_site_cancel_and_recover(tmp_path, scheduler, scheduler_name, monkeypatch):
    monkeypatch.setenv('FAKE_HOLD', '1')
    plan = eb.prepare(site_spec(tmp_path, scheduler_name))
    backend = eb.get('site')
    original = backend.submit

    def crash(plan, handle):
        original(plan, handle)
        raise RuntimeError('ssh dropped')
    monkeypatch.setattr(backend, 'submit', crash)
    with pytest.raises(RuntimeError):
        eb.submit(plan, tmp_path / 'attempt', backend=backend)
    monkeypatch.setattr(backend, 'submit', original)
    handle = eb.read_handle(tmp_path / 'attempt')
    result = eb.recover(plan, handle)
    assert result['observation']['state'] == 'running'
    assert eb.cancel(plan, result['handle'], wait_seconds=5)['state'] == 'cancelled'


def test_site_refuses_overriding_controlled_fields(tmp_path, scheduler):
    spec = site_spec(tmp_path, 'htcondor')
    spec['site']['options'] = {'executable': '/bin/evil'}
    with pytest.raises(ValueError, match='RAVEL-controlled'):
        eb.prepare(spec)


def test_site_wrapper_never_overwrites_remote_output(tmp_path, scheduler):
    plan = eb.prepare(site_spec(tmp_path, 'slurm'))
    text = site_batch.wrapper(plan)
    assert 'test ! -e' in text and 'xrdcp -f' not in text
