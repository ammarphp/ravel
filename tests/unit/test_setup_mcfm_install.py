"""Offline installer controls using fictional sources and inert clients."""
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ravel.setup import manifest as mf, steps
from ravel.workflow import execution_backend as eb
from ravel.workflow.backends import oci_local as oci
from setup_fakes import FakeRunner

REPO = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    prefix = tmp_path / 'prefix'
    client = tmp_path / 'fake-podman'
    client.write_text('inert client')
    values = mf.variables(prefix, REPO, 'macos-arm64', jobs=3, installer_python=sys.executable,
                          container_engine=str(client))
    document, catalog = mf.load(REPO)
    monkeypatch.setattr(oci, 'host_platform', lambda: 'linux/arm64')
    return steps.Context(prefix=prefix, repo=REPO, platform_key='macos-arm64', values=values,
                         runner=FakeRunner(), fetcher=None, manifest=document, catalog=catalog,
                         base_env={'PATH': '/usr/bin:/bin'})


def image_step(ctx):
    return mf.by_id(ctx.manifest)['mcfm-amplitudes']['steps'][0]


def fake_build(ctx, monkeypatch, executed=True):
    calls = []
    def build(cf, context, tag, **kw):
        calls.append((cf, context, tag, kw))
        record = {'schema_version': 1, 'kind': 'ravel-image-build', 'executed': executed,
                  'containerfile': {'path': str(cf), 'sha256': sha(cf)},
                  'context': eb.identity(context), 'bases': oci.containerfile_bases(Path(cf).read_text()),
                  'platform': kw['platform'], 'tag': tag,
                  'client': oci.resolve_client(kw['client']), 'image': {'id': 'sha256:' + 'a' * 64}}
        eb.atomic_json(kw['receipt'], record)
        ctx.runner.images.add(record['image']['id'])
        return record
    monkeypatch.setattr(oci, 'build_image', build)
    return calls


def test_image_build_executes_and_adopts_only_matching_present_image(ctx, monkeypatch):
    calls = fake_build(ctx, monkeypatch)
    step = image_step(ctx)
    result = steps.run_step(step, ctx)
    assert len(calls) == 1
    cf, context, tag, kw = calls[0]
    assert Path(cf).name == 'Containerfile.amd64' and Path(context) == REPO / 'native/containers/mcfm'
    assert kw['execute'] is True and kw['platform'] == 'linux/amd64'
    assert kw['client'] == ctx.values['CONTAINER_ENGINE']
    assert steps.run_step(step, ctx)['adopted'] is True and len(calls) == 1
    receipt = Path(result['receipt'])
    record = json.loads(receipt.read_text())
    record['containerfile']['sha256'] = 'b' * 64
    eb.atomic_json(receipt, record)
    steps.run_step(step, ctx)
    assert len(calls) == 2 and list((ctx.prefix / 'trash').iterdir())
    ctx.runner.images.clear()
    steps.run_step(step, ctx)
    assert len(calls) == 3


@pytest.mark.parametrize('executed', [False])
def test_dry_run_never_counts_as_install(ctx, monkeypatch, executed):
    fake_build(ctx, monkeypatch, executed)
    with pytest.raises(steps.StepError, match='executed'):
        steps.run_step(image_step(ctx), ctx)


def overlay_module():
    path = REPO / 'native/setup/recipes/mcfm_overlay.py'
    spec = importlib.util.spec_from_file_location('overlay_recipe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_overlay(tmp_path):
    source, addon = tmp_path / 'source', tmp_path / 'fictional-addon'
    source.mkdir(); addon.mkdir()
    subprocess.run(['/usr/bin/git', 'init', '-q', str(source)], check=True)
    (source / 'lowint.f').write_text('old\n')
    (source / 'CMakeLists.txt').write_text('# fictional project\n')
    members = {'lowint-capture.patch': '--- a/lowint.f\n+++ b/lowint.f\n@@ -1 +1 @@\n-old\n+new\n',
               'CMakeLists-ravel.cmake': '# fictional overlay\n', 'driver.f': 'fictional\n'}
    for name, content in members.items():
        (addon / name).write_text(content)
    manifest = {'schema_version': 1, 'name': addon.name, 'license': 'GPL-3.0-or-later',
                'summary': 'Fictional overlay', 'overlay': list(members),
                'files': {name: sha(addon / name) for name in members}}
    (addon / 'addon.json').write_text(json.dumps(manifest))
    return source, addon


def test_overlay_verified_export_and_repeat(tmp_path):
    source, addon = synthetic_overlay(tmp_path)
    dest = tmp_path / 'overlay'
    overlay_module().prepare(source, dest, addon)
    assert (dest / 'lowint.f').read_text() == 'new\n'
    assert not (dest / '.git').exists()
    assert (dest / 'CMakeLists.txt').read_text().count('include(ravel/CMakeLists-ravel.cmake)') == 1
    overlay_module().prepare(source, dest, addon)
    (dest / 'lowint.f').write_text('changed\n')
    with pytest.raises(ValueError, match='changed'):
        overlay_module().prepare(source, dest, addon)


def test_overlay_bad_member_and_foreign_destination_refused(tmp_path):
    source, addon = synthetic_overlay(tmp_path)
    dest = tmp_path / 'foreign'; dest.mkdir(); (dest / 'keep').write_text('keep')
    with pytest.raises(ValueError, match='foreign'):
        overlay_module().prepare(source, dest, addon)
    (addon / 'driver.f').write_text('wrong')
    with pytest.raises(ValueError, match='sha256'):
        overlay_module().prepare(source, tmp_path / 'overlay', addon)


def compile_step(ctx):
    return next(s for s in mf.by_id(ctx.manifest)['mcfm-amplitudes']['steps'] if s['kind'] == 'container_run')


def prepare_compile(ctx, monkeypatch, fail=False):
    steps.run_step(image_step(ctx), ctx)
    step = compile_step(ctx)
    for key in ('source', 'overlay'):
        Path(mf.expand(step[key], ctx.values)).mkdir(parents=True, exist_ok=True)
    Path(ctx.values['LHAPDF_DATA']).mkdir(parents=True, exist_ok=True)
    original = ctx.runner.run
    def run(argv, **kw):
        result = original(argv, **kw)
        if '/opt/ravel/bin/build-mcfm.sh' in argv:
            build = Path(argv[-1]); (build / 'ravel_mcfm_amplitudes').write_text('fictional ELF')
            (build / 'build-receipt.json').write_text('{}')
            for name in steps.MCFM_RUNTIME_FILES:
                (build / name).write_text('fictional ' + name)
            return 1 if fail else result
        return result
    ctx.runner.run = run
    original_capture = ctx.runner.capture
    ctx.runner.capture = lambda argv, **kw: (0, '{"status":"passed"}\n') if '/opt/ravel/bin/check-mcfm.sh' in argv else original_capture(argv, **kw)
    ctx.install_authority = {'kind': 'installer-command', 'command': ['bash', 'scripts/setup/install.sh', '--only', 'mcfm-amplitudes'],
                             'license_acceptance': 'flag', 'authority': 'installer'}
    leases = []
    @contextmanager
    def lease(holder, **kw):
        leases.append((holder, kw)); yield
    monkeypatch.setattr(eb, 'machine_lease', lease)
    return step, leases


def test_compile_is_confined_leased_and_records_install(ctx, monkeypatch):
    fake_build(ctx, monkeypatch)
    step, leases = prepare_compile(ctx, monkeypatch)
    result = steps.run_step(step, ctx)
    argv = ctx.runner.calls[-1]
    assert '--network' in argv and argv[argv.index('--network') + 1] == 'none'
    assert argv[argv.index('--platform') + 1] == 'linux/amd64'
    volumes = [argv[i + 1] for i, a in enumerate(argv) if a == '-v']
    assert len([v for v in volumes if v.endswith(':rw')]) == 1
    assert len([v for v in volumes if v.endswith(':ro')]) == 2
    assert 'RAVEL_BUILD_JOBS=3' in argv and argv[-4] == '/opt/ravel/bin/build-mcfm.sh'
    assert not leases  # the machine lease admits approved study stages only
    launcher = json.loads(Path(result['launcher']).read_text())
    assert oci.validate_launcher(launcher) and launcher['image']['emulation'] is True
    bad = dict(launcher, image=dict(launcher['image'])); bad['image'].pop('emulation')
    with pytest.raises(ValueError, match='emulation'):
        oci.validate_launcher(bad)
    record = json.loads(Path(result['installation']).read_text())
    assert record['build_receipt_sha256'] == sha(Path(record['program']).parent / 'build-receipt.json')
    assert record['authority']['license_acceptance'] == 'flag'
    assert len(record['readonly_trees']) == 4
    assert steps.run_step(step, ctx)['verified'] is True


def test_rewritten_image_receipt_for_the_same_image_keeps_the_build(ctx, monkeypatch):
    fake_build(ctx, monkeypatch)
    step, _ = prepare_compile(ctx, monkeypatch)
    first = steps.run_step(step, ctx)
    receipt = Path(first['image_build_receipt'])
    record = json.loads(receipt.read_text())
    eb.atomic_json(receipt, dict(record, built_utc='2000-01-01T00:00:00Z'))
    compiles = sum('/opt/ravel/bin/build-mcfm.sh' in argv for argv in ctx.runner.calls)
    assert steps.run_step(step, ctx)['verified'] is True
    assert sum('/opt/ravel/bin/build-mcfm.sh' in argv for argv in ctx.runner.calls) == compiles
    assert not list((ctx.prefix / 'trash').glob('mcfm-build-*'))
    eb.atomic_json(receipt, dict(record, image={'id': 'sha256:' + 'd' * 64}))
    ctx.runner.images.add('sha256:' + 'd' * 64)
    assert 'verified' not in steps.run_step(step, ctx)
    assert list((ctx.prefix / 'trash').glob('mcfm-build-*'))


def test_failed_compile_preserved_and_user_argv_refused(ctx, monkeypatch):
    fake_build(ctx, monkeypatch)
    step, leases = prepare_compile(ctx, monkeypatch, fail=True)
    with pytest.raises(steps.StepError):
        steps.run_step(step, ctx)
    assert not leases and list((ctx.prefix / 'trash').glob('*/*build-receipt.json'))
    assert not Path(mf.expand(step['build'], ctx.values)).exists()
    with pytest.raises((steps.StepError, mf.ManifestError), match='argv'):
        steps.run_step(dict(step, argv=['user-command']), ctx)


@pytest.mark.parametrize('output,passes', [
    ('client notice on the error stream\n{"status":"passed"}\n', True),
    ('{"status":"failed"}\n{"status":"passed"}\n', False),
    ('passed\n', False),
])
def test_install_check_reads_the_one_json_verdict_among_client_diagnostics(ctx, monkeypatch, output, passes):
    fake_build(ctx, monkeypatch)
    step, _ = prepare_compile(ctx, monkeypatch)
    inner = ctx.runner.capture
    ctx.runner.capture = lambda argv, **kw: (0, output) if '/opt/ravel/bin/check-mcfm.sh' in argv else inner(argv, **kw)
    if passes:
        assert Path(steps.run_step(step, ctx)['installation']).is_file()
    else:
        with pytest.raises(steps.StepError, match='check failed'):
            steps.run_step(step, ctx)


def test_json_verdict_probe_is_declared_on_the_check_not_bound_to_a_group(ctx):
    from ravel.setup.doctor import Doctor
    doctor = Doctor(ctx.repo, ctx.prefix, ctx.platform, ctx.manifest, ctx.catalog,
                    environ={'PATH': '/usr/bin:/bin'}, run_probe=lambda *a, **kw: (0, 'synthetic-tool 1.0\n'))
    group = mf.by_id(ctx.manifest)['mcfm-amplitudes']
    declared = next(c for c in group['checks'] if c['id'] == 'mcfm-amplitudes')
    assert declared['probe']['json_status'] == 'passed'
    plain = {'id': 'mcfm-amplitudes', 'kind': 'probe', 'probe': {'argv': ['synthetic-tool', '--version']}}
    assert doctor.evaluate_check(group, plain)['status'] == 'ready'
    other = {'id': 'other', 'kind': 'probe', 'probe': {'argv': ['synthetic-tool'], 'json_status': 'passed'}}
    row = doctor.evaluate_check({'id': 'synthetic-group'}, other)
    assert row['status'] == 'missing' and '--only synthetic-group' in row['fix']


def test_manifest_routes_and_recipe_values():
    manifest, _ = mf.load(REPO)
    group = mf.by_id(manifest)['mcfm-amplitudes']
    assert group['size_gb'] >= 6 and group['minutes'] >= 180
    assert mf.route_for(group, 'linux-aarch64') == 'unsupported'
    # Qualified on its Linux x86_64 native route; the record names that platform.
    assert group['qualification']['status'] == 'qualified'
    assert group['qualification']['record']['platform'] == 'linux-x86_64'
    for group in manifest['groups']:
        for step in group['steps']:
            if step['kind'] == 'container_build':
                assert {'containerfile', 'context', 'platform', 'tag', 'receipt'} <= set(step)


@pytest.mark.parametrize('code,output,status,start', [
    (0, '{"status":"passed"}\n', 'ready', False),
    (0, '{"status":"failed"}\n', 'missing', False),
    (125, 'Cannot connect to Podman: machine is not running', 'missing', True),
])
def test_doctor_check_requires_passed_json(ctx, code, output, status, start):
    from ravel.setup.doctor import Doctor
    doctor = Doctor(ctx.repo, ctx.prefix, ctx.platform, ctx.manifest, ctx.catalog,
                    environ={'PATH': '/usr/bin:/bin'}, run_probe=lambda *a, **kw: (code, output))
    group = mf.by_id(ctx.manifest)['mcfm-amplitudes']
    check = next(c for c in group['checks'] if c['id'] == 'mcfm-amplitudes')
    row = doctor.evaluate_check(group, check)
    assert row['status'] == status
    if status != 'ready':
        assert 'ravel-podman machine start ravel' in row['fix'] if start else '--only mcfm-amplitudes' in row['fix']


def test_backend_execute_still_requires_study_approval(tmp_path, monkeypatch):
    from execution_backend_fakes import install, PODMAN
    client = install(tmp_path / 'bin', 'podman', PODMAN, tmp_path / 'state.json')
    monkeypatch.setattr(oci, 'host_platform', lambda: 'linux/amd64')
    launcher = {'kind': 'oci-local', 'image': {'id': 'sha256:' + 'a' * 64, 'platform': 'linux/amd64'},
                'client': oci.resolve_client(str(client)), 'connection': 'ravel', 'cpus': 1, 'memory_mib': 1024}
    path = tmp_path / 'launcher.json'; path.write_text(json.dumps(launcher))
    assert eb.main(['launch', '--launcher', str(path), '--workdir', str(tmp_path), '--execute', '--', '/fake/program']) != 0


@pytest.mark.parametrize('code,output,error', [
    (0, '{"status":"passed"}', ''),
    (1, '{"status":"failed","reason":"fictional failure"}', ''),
    (125, '', 'Cannot connect to Podman: machine is not running'),
])
def test_generated_check_wrapper_uses_inert_client(ctx, tmp_path, code, output, error):
    client = Path(ctx.values['CONTAINER_ENGINE'])
    client.write_text('#!' + sys.executable + '\nimport sys\nprint(' + repr(output) + ')\nprint(' + repr(error) + ', file=sys.stderr)\nsys.exit(' + str(code) + ')\n')
    client.chmod(0o755)
    ctx.values['HOST_PYTHON'] = sys.executable
    group = mf.by_id(ctx.manifest)['mcfm-amplitudes']
    compile = compile_step(ctx)
    launcher = {'kind': 'oci-local', 'image': {'id': 'sha256:' + 'a' * 64, 'platform': 'linux/amd64', 'emulation': True},
                'client': oci.resolve_client(str(client)), 'connection': 'ravel', 'cpus': 1, 'memory_mib': 1024}
    path = Path(mf.expand(compile['launcher'], ctx.values)); eb.atomic_json(path, launcher)
    build = Path(mf.expand(compile['build'], ctx.values)); build.mkdir(parents=True)
    wrapper = next(s for s in group['steps'] if s['kind'] == 'wrapper')
    steps.run_step(wrapper, ctx)
    proc = subprocess.run([str(ctx.prefix / 'bin' / wrapper['name'])], capture_output=True, text=True)
    assert (proc.returncode == 0) == (code == 0)
    if output:
        assert proc.stdout.strip() == output
    if error:
        assert error in proc.stderr


def test_declared_instruction_and_mirror_agree():
    """The amplitude tool handbook declares installation defaults and authority; the shipped reference page
    and its packaged mirror agree."""
    text = (REPO / 'src/ravel/data/skills/tools/mcfm-amplitudes/SKILL.md').read_text()
    for marker in ('--only mcfm-amplitudes', 'ravel-podman machine start ravel',
                   'installations/mcfm-amplitudes.json', 'ravel.paths.native_build_root()',
                   'study inputs and every backend', 'built-unqualified', 'never a human'):
        assert marker in text
    assert (REPO / 'docs/reference/amplitude-reweighting.md').read_bytes() == (REPO / 'src/ravel/data/workflow/docs/reference/amplitude-reweighting.md').read_bytes()


@pytest.mark.parametrize('held', [True, False])
def test_installation_instruction_follows_the_release_hold(tmp_path, monkeypatch, held):
    """Released, the instruction must name the installation; withheld, it must not."""
    from ravel.setup import manifest as mf
    from workflow_instruction_inventory_fixture import assert_amplitude_installation_instruction
    hold = {'groups': [{'id': 'mcfm-amplitudes'}]} if held else {'groups': []}
    monkeypatch.setattr(mf, 'view', lambda root: {'unreleased': hold})
    doc = tmp_path / 'docs/reference/amplitude-reweighting.md'
    doc.parent.mkdir(parents=True)
    doc.write_text('Install with --only mcfm-amplitudes; the record is installations/mcfm-amplitudes.json.\n')
    with pytest.raises(AssertionError):
        assert_amplitude_installation_instruction(tmp_path)
    doc.write_text('An amplitude reweighting instruction without installation text.\n')
    if held:
        assert_amplitude_installation_instruction(tmp_path)
    else:
        with pytest.raises(AssertionError):
            assert_amplitude_installation_instruction(tmp_path)


def test_image_receipt_adopts_identical_bytes_from_other_checkout(ctx, monkeypatch):
    calls = fake_build(ctx, monkeypatch)
    step = image_step(ctx); result = steps.run_step(step, ctx)
    receipt = Path(result['receipt']); record = json.loads(receipt.read_text())
    record['containerfile']['path'] = '/fictional/other/Containerfile.amd64'
    record['context']['path'] = '/fictional/other/context'
    eb.atomic_json(receipt, record)
    assert steps.run_step(step, ctx)['adopted'] is True and len(calls) == 1
    record['bases'] = ['registry.example/other@sha256:' + 'b' * 64]
    eb.atomic_json(receipt, record)
    steps.run_step(step, ctx)
    assert len(calls) == 2


def test_container_run_manifest_refuses_user_command(ctx):
    step = compile_step(ctx)
    with pytest.raises(mf.ManifestError, match='argv'):
        mf._check_step('fictional', dict(step, argv=['/bin/sh', '-c', 'arbitrary']), set())


def test_compile_refuses_foreign_nonempty_build(ctx, monkeypatch):
    fake_build(ctx, monkeypatch)
    step, _ = prepare_compile(ctx, monkeypatch)
    build = Path(mf.expand(step['build'], ctx.values)); build.mkdir()
    (build / 'keep').write_text('fictional foreign file')
    with pytest.raises(steps.Conflict, match='foreign'):
        steps.run_step(step, ctx)
    assert (build / 'keep').read_text() == 'fictional foreign file' and not ctx.runner.calls


def test_compile_refuses_symlinked_build_destination(ctx, monkeypatch, tmp_path):
    fake_build(ctx, monkeypatch)
    step, _ = prepare_compile(ctx, monkeypatch)
    other = tmp_path / 'foreign-empty'; other.mkdir()
    build = Path(mf.expand(step['build'], ctx.values)); build.symlink_to(other, target_is_directory=True)
    with pytest.raises(steps.Conflict, match='symlink'):
        steps.run_step(step, ctx)
    assert not list(other.iterdir())


def test_image_result_without_id_fails(ctx, monkeypatch):
    fake_build(ctx, monkeypatch)
    original = oci.build_image
    def missing_id(*args, **kw):
        record = original(*args, **kw); record['image'] = {}
        eb.atomic_json(kw['receipt'], record)
        return record
    monkeypatch.setattr(oci, 'build_image', missing_id)
    with pytest.raises(steps.StepError, match='image id'):
        steps.run_step(image_step(ctx), ctx)


def test_script_change_rebuilds_image(ctx, monkeypatch, tmp_path):
    calls = fake_build(ctx, monkeypatch)
    recipe = tmp_path / 'fictional-recipe'; recipe.mkdir()
    cf = recipe / 'Containerfile.amd64'; cf.write_text('FROM registry.example/base@sha256:' + 'b' * 64 + '\nCOPY script /script\n')
    script = recipe / 'script'; script.write_text('fictional old script\n')
    step = dict(image_step(ctx), containerfile=str(cf), context=str(recipe))
    steps.run_step(step, ctx); script.write_text('fictional new script\n'); steps.run_step(step, ctx)
    assert len(calls) == 2


# Linux x86_64: the program is compiled on the host with the compiler-bootstrap toolchain.

@pytest.fixture
def linux_ctx(tmp_path, monkeypatch):
    prefix = tmp_path / 'prefix'
    values = mf.variables(prefix, REPO, 'linux-x86_64', jobs=3, installer_python=sys.executable,
                          container_engine=str(tmp_path / 'unused-engine'))
    document, catalog = mf.load(REPO)
    context = steps.Context(prefix=prefix, repo=REPO, platform_key='linux-x86_64', values=values,
                            runner=FakeRunner(), fetcher=None, manifest=document, catalog=catalog,
                            base_env={'PATH': '/usr/bin:/bin'})
    toolchain = Path(values['ENVS']) / 'host-build/bin'
    toolchain.mkdir(parents=True)
    for name in ('gcc', 'g++', 'gfortran', 'cmake', 'python3'):
        (toolchain / name).write_text('fictional ' + name)
    return context


def native_step(ctx, kind='native_compile'):
    return next(s for s in mf.by_id(ctx.manifest)['mcfm-amplitudes']['steps']
                if s['kind'] == kind and s.get('platforms') == ['linux-x86_64'])


def prepare_native(ctx, monkeypatch, fail=False, verdict='{"status":"passed"}\n'):
    step = native_step(ctx)
    for key in ('source', 'overlay'):
        Path(mf.expand(step[key], ctx.values)).mkdir(parents=True, exist_ok=True)
    Path(ctx.values['LHAPDF_DATA']).mkdir(parents=True, exist_ok=True)
    original = ctx.runner.run
    envs = []
    def run(argv, **kw):
        result = original(argv, **kw)
        if any(str(a).endswith('build-mcfm.sh') for a in argv):
            envs.append(kw.get('env'))
            build = Path(argv[-1]); (build / 'ravel_mcfm_amplitudes').write_text('fictional ELF')
            (build / 'build-receipt.json').write_text('{}')
            for name in steps.MCFM_RUNTIME_FILES:
                (build / name).write_text('fictional ' + name)
            return 1 if fail else result
        return result
    ctx.runner.run = run
    inner = ctx.runner.capture
    ctx.runner.capture = lambda argv, **kw: (0, verdict) if any(str(a).endswith('check-mcfm.sh') for a in argv) else inner(argv, **kw)
    ctx.install_authority = {'kind': 'installer-command', 'command': ['bash', 'scripts/setup/install.sh', '--only', 'mcfm-amplitudes'],
                             'license_acceptance': 'flag', 'authority': 'installer'}
    leases = []
    @contextmanager
    def lease(holder, **kw):
        leases.append((holder, kw)); yield
    monkeypatch.setattr(eb, 'machine_lease', lease)
    return step, leases, envs


def test_linux_route_is_native_and_runs_no_container_step():
    manifest, _ = mf.load(REPO)
    group = mf.by_id(manifest)['mcfm-amplitudes']
    assert mf.route_for(group, 'linux-x86_64') == 'native'
    assert mf.route_for(group, 'macos-arm64') == 'container'
    linux = [s for s in group['steps'] if mf.applies(s, 'linux-x86_64')]
    assert [s['kind'] for s in linux] == ['git', 'command', 'native_compile', 'wrapper', 'command']
    mac = [s['kind'] for s in group['steps'] if mf.applies(s, 'macos-arm64')]
    assert 'native_compile' not in mac and 'container_run' in mac and 'container_build' in mac


def test_native_compile_is_leased_uses_the_toolchain_and_records_install(linux_ctx, monkeypatch):
    step, leases, envs = prepare_native(linux_ctx, monkeypatch)
    result = steps.run_step(step, linux_ctx)
    toolchain = Path(linux_ctx.values['ENVS']) / 'host-build/bin'
    argv = next(a for a in linux_ctx.runner.calls if str(a[-4]).endswith('build-mcfm.sh'))
    assert argv[0] == '/bin/bash' and Path(argv[1]) == REPO / 'native/containers/mcfm/build-mcfm.sh'
    env = envs[0]
    assert env['PATH'].split(':')[0] == str(toolchain) and env['RAVEL_BUILD_JOBS'] == '3'
    assert env['LDFLAGS'] == '-Wl,-rpath,' + str(toolchain.parent / 'lib')
    assert not leases  # the machine lease admits approved study stages only
    record = json.loads(Path(result['installation']).read_text())
    assert record['launcher'] == {'kind': 'native', 'toolchain': str(toolchain)} and 'image' not in record
    assert record['build_receipt_sha256'] == sha(Path(record['program']).parent / 'build-receipt.json')
    assert set(record['bindings']['toolchain']) == {'gcc', 'g++', 'gfortran', 'cmake', 'python3'}
    assert [Path(f['path']).name for f in record['runtime_files']] == ['process.DAT', 'br.sm1', 'br.sm2']
    assert record['authority']['license_acceptance'] == 'flag'
    assert record['build_serialization'] == 'installer prefix lock'
    compiles = len(envs)
    assert steps.run_step(step, linux_ctx)['verified'] is True and len(envs) == compiles
    (toolchain / 'gfortran').write_text('fictional other compiler')
    assert 'verified' not in steps.run_step(step, linux_ctx) and len(envs) == compiles + 1
    assert list((linux_ctx.prefix / 'trash').glob('mcfm-build-*'))


def test_native_compile_failure_is_retained_and_check_is_required(linux_ctx, monkeypatch):
    step, _, _ = prepare_native(linux_ctx, monkeypatch, fail=True)
    with pytest.raises(steps.StepError):
        steps.run_step(step, linux_ctx)
    assert list((linux_ctx.prefix / 'trash').glob('*/*build-receipt.json'))
    linux_ctx.runner = FakeRunner()
    step, _, _ = prepare_native(linux_ctx, monkeypatch, verdict='{"status":"failed"}\n')
    with pytest.raises(steps.StepError, match='check failed'):
        steps.run_step(step, linux_ctx)
    assert not Path(mf.expand(step['installation'], linux_ctx.values)).exists()


def test_native_compile_refuses_incomplete_toolchain_foreign_build_and_user_argv(linux_ctx, monkeypatch):
    step, _, _ = prepare_native(linux_ctx, monkeypatch)
    (Path(linux_ctx.values['ENVS']) / 'host-build/bin/gfortran').unlink()
    with pytest.raises(steps.StepError, match='toolchain incomplete'):
        steps.run_step(step, linux_ctx)
    with pytest.raises(steps.StepError, match='argv'):
        steps.run_step(dict(step, argv=['user-command']), linux_ctx)
    with pytest.raises(mf.ManifestError, match='argv'):
        mf._check_step('fictional', dict(step, argv=['/bin/sh', '-c', 'arbitrary']), set())
    with pytest.raises(mf.ManifestError, match='linux-x86_64 only'):
        mf._check_step('fictional', dict(step, platforms=['macos-arm64']), set())
    (Path(linux_ctx.values['ENVS']) / 'host-build/bin/gfortran').write_text('fictional gfortran')
    build = Path(mf.expand(step['build'], linux_ctx.values)); build.mkdir()
    (build / 'keep').write_text('fictional foreign file')
    with pytest.raises(steps.Conflict, match='foreign'):
        steps.run_step(step, linux_ctx)
    assert (build / 'keep').read_text() == 'fictional foreign file'


@pytest.mark.parametrize('code,output', [(0, '{"status":"passed"}'), (1, '{"status":"failed","reason":"fictional"}')])
def test_native_check_wrapper_puts_the_toolchain_first(linux_ctx, tmp_path, code, output):
    linux_ctx.values['HOST_PYTHON'] = sys.executable
    wrapper = native_step(linux_ctx, 'wrapper')
    steps.run_step(wrapper, linux_ctx)
    text = (linux_ctx.prefix / 'bin' / wrapper['name']).read_text()
    assert str(REPO / 'native/containers/mcfm/check-mcfm.sh') in text
    fake_check = tmp_path / 'check.sh'
    fake_check.write_text('test "$(command -v gfortran)" = "' + str(Path(linux_ctx.values['ENVS']) / 'host-build/bin/gfortran')
                          + '" || exit 3\necho \'' + output + '\'\nexit ' + str(code) + '\n')
    (Path(linux_ctx.values['ENVS']) / 'host-build/bin/gfortran').chmod(0o755)
    script = tmp_path / 'wrapper'
    script.write_text(text.replace(str(REPO / 'native/containers/mcfm/check-mcfm.sh'), str(fake_check)))
    proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
    assert proc.returncode == (0 if code == 0 else 1) and proc.stdout.strip() == output


def test_build_script_finds_its_receipt_writer_and_accepts_cmake_4(tmp_path):
    text = (REPO / 'native/containers/mcfm/build-mcfm.sh').read_text()
    assert 'python3 "$HERE/write_mcfm_receipt.py"' in text and '/opt/ravel/bin/write_mcfm_receipt.py' not in text
    assert 'export CMAKE_POLICY_VERSION_MINIMUM=3.5' in text
    spec = importlib.util.spec_from_file_location('receipt_writer', REPO / 'native/containers/mcfm/write_mcfm_receipt.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.provider().startswith('container image')
    import os
    os.environ['RAVEL_TOOLCHAIN_PROVIDER'] = 'native toolchain /fictional'
    try:
        assert module.provider() == 'native toolchain /fictional'
    finally:
        del os.environ['RAVEL_TOOLCHAIN_PROVIDER']


def test_overlay_refuses_a_source_that_differs_from_the_upstream_pins(tmp_path):
    source, addon = synthetic_overlay(tmp_path)
    (addon / 'upstream-api.json').write_text(json.dumps({'source_files': {'lowint.f': sha(source / 'lowint.f')}}))
    manifest = json.loads((addon / 'addon.json').read_text())
    manifest['files']['upstream-api.json'] = sha(addon / 'upstream-api.json')
    (addon / 'addon.json').write_text(json.dumps(manifest))
    overlay_module().prepare(source, tmp_path / 'overlay', addon)
    (source / 'lowint.f').write_text('old, edited\n')
    with pytest.raises(ValueError, match='lowint.f differs from the add-on pin'):
        overlay_module().prepare(source, tmp_path / 'second', addon)
    assert not (tmp_path / 'second').exists()


def test_bridge_includes_only_free_form_compatible_upstream_files():
    # Fixed-form include files with column-6 continuation lines do not compile in free-form source.
    text = (REPO / 'addons/gpl/mcfm-amplitudes/ravel_bridge.f90').read_text()
    assert "include 'zcouple_cms.f'" not in text and 'common/zcouple_cms/' in text
    pins = json.loads((REPO / 'addons/gpl/mcfm-amplitudes/upstream-api.json').read_text())['source_files']
    assert 'src/Inc/zcouple_cms.f' in pins


def test_a_group_that_runs_the_host_python_depends_on_python_host():
    # A clean prefix has no checkout environment until python-host creates it.
    manifest, _ = mf.load(REPO)
    assert 'python-host' in mf.by_id(manifest)['mcfm-amplitudes']['depends_on']
    broken = json.loads(json.dumps(manifest))
    mf.by_id(broken)['mcfm-amplitudes']['depends_on'] = ['container-runtime', 'lhapdf-sets']
    with pytest.raises(mf.ManifestError, match='python-host'):
        mf.validate(broken)


def test_overlay_recipe_name_is_snake_case_and_every_manifest_reference_resolves():
    import re
    recipes = REPO / 'native/setup/recipes'
    assert all(re.fullmatch(r'[a-z_][a-z0-9_]*\.py', p.name) for p in recipes.glob('*.py'))
    manifest = (REPO / 'native/setup/toolchain-manifest.json').read_text()
    referenced = set(re.findall(r'native/setup/recipes/[A-Za-z0-9_.-]+', manifest))
    assert 'native/setup/recipes/mcfm_overlay.py' in referenced
    assert all((REPO / path).is_file() for path in referenced)
