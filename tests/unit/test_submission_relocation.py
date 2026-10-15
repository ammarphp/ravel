"""Portable packages and release-tree contracts, using local fictional fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import io

import pytest

from ravel.workflow import submission_export as se, procedure_export as pe
from test_submission_export import accepted_analysis, GIT


# The fixture release carries the running package's version: the release route refuses a
# release whose pyproject version differs from the running RAVEL, so a stamped export of this
# file must build its fixture at the version it runs.
VERSION = se._package_metadata()['version']
TAG = 'v' + VERSION


def git(root, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME='fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
               GIT_COMMITTER_NAME='fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid')
    return subprocess.run([GIT, '-C', str(root), *args], check=True, capture_output=True, env=env).stdout


def checkout(tmp_path, monkeypatch):
    import ravel
    monkeypatch.setattr(ravel, "__version__", VERSION)
    root = tmp_path / 'framework'; root.mkdir()
    files = {'pyproject.toml': f'''[project]\nname = "ravel-hep"\nversion = "{VERSION}"\nreadme = "docs/use.md"\nlicense-files = ["LICENSE"]\n[project.urls]\nRepository = "https://example.invalid/framework"\n[tool.hatch.build.targets.sdist]\ninclude = ["src/ravel", "pyproject.toml", "assets/*.txt"]\n[tool.hatch.build.hooks.custom]\npath = "build_fixture.py"\n''',
             'src/ravel/__init__.py': f'__version__ = "{VERSION}"\n', 'docs/use.md': 'Synthetic framework\n',
             'LICENSE': 'Synthetic license\n', 'build_fixture.py': '# synthetic build hook\n',
             'assets/value.txt': 'value\n', 'private.txt': 'not shipped\n',
             # The release's own restricted-source scan; the vendor route runs it and it does not ship.
             se.RESTRICTED_SCAN: (Path(se.__file__).resolve().parents[3] / se.RESTRICTED_SCAN).read_text()}
    for name, raw in files.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(raw)
    git(root, 'init', '-q'); git(root, 'add', '.'); git(root, 'commit', '-qm', 'fixture'); git(root, 'tag', TAG)
    return root


def package(tmp_path, monkeypatch, **kwargs):
    request, run = accepted_analysis(tmp_path, monkeypatch)
    out = Path(se.export(request, tmp_path / 'repository', **kwargs)['package'])
    return out, run


def test_exporting_interpreter_mutation_is_refused_by_checksum(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    snake = out / 'procedure/Snakefile'; snake.write_text(f'shell: "{sys.executable} -m ravel"\n')
    report = se._check(out)
    assert any('procedure/Snakefile' in error and 'sha256' in error for error in report['errors'])


@pytest.mark.parametrize('path', ['/outside/run/input.json', '/outside/framework/module.py', '/outside/user-area/data'])
def test_unlisted_text_is_refused_by_roster(tmp_path, monkeypatch, path):
    out, _ = package(tmp_path, monkeypatch)
    (out / 'unlisted.txt').write_text(path)
    assert any('unlisted.txt' in error and 'not listed' in error for error in se._check(out)['errors'])


def test_inner_workflow_outputs_do_not_break_package_check(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    if os.environ.get('RAVEL_TEST_SNAKEMAKE'):
        bindir = tmp_path / 'procedure-bin'; bindir.mkdir()
        entry = bindir / 'ravel'
        entry.write_text(f'#!{sys.executable}\nfrom ravel.cli import main\nraise SystemExit(main())\n')
        entry.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
        done = subprocess.run([os.environ['RAVEL_TEST_SNAKEMAKE'], '--cores', '1', '--executor', 'local',
                               '--snakefile', 'Snakefile'], cwd=out / 'procedure', env=env, capture_output=True, text=True)
        assert done.returncode == 0, done.stdout + done.stderr
    for name in ('procedure/completed/node_0.json', 'procedure/.snakemake/x', 'nested/.snakemake/x'):
        target = out / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text('{}')
    assert se.verify(out)['passed']
    (out / 'procedure/unknown.txt').write_text('unlisted')
    assert not se.verify(out)['passed']


def test_embedded_pins_and_node_verification_survive_copy(tmp_path, monkeypatch):
    out, original = package(tmp_path, monkeypatch)
    snake = (out / 'procedure/Snakefile').read_text()
    assert 'ravel procedure verify-node' in snake and sys.executable not in snake
    shutil.rmtree(original)
    fresh = tmp_path / 'other-parent' / 'copy'; shutil.copytree(out, fresh)
    doc = pe.verify(fresh / 'procedure', deep=True)
    assert doc['run'] == '../run' and all(not Path(pin['path']).is_absolute() for pin in doc['source_pins'])
    digest = se.file_sha256(fresh / 'procedure/procedure.json')
    for index in range(len(doc['nodes'])):
        pe.verify_node(fresh / 'procedure', index, digest, fresh / f'procedure/completed/node_{index}.json')
    assert se.verify(fresh, fresh_clone=True)['passed']
    assert not any(str(original) in path.read_text(errors='ignore') for path in fresh.rglob('*')
                   if path.is_file() and path.suffix not in ('.gz', '.blob'))


@pytest.mark.parametrize('invalid', ['untagged', 'dirty', 'version', 'commit'])
def test_framework_source_refuses_invalid_release(tmp_path, monkeypatch, invalid):
    source = checkout(tmp_path, monkeypatch)
    if invalid == 'dirty': (source / 'assets/value.txt').write_text('modified')
    elif invalid in ('untagged', 'commit'):
        (source / 'private.txt').write_text('next'); git(source, 'add', '.'); git(source, 'commit', '-qm', 'next')
    else:
        import ravel
        monkeypatch.setattr(se, '_package_metadata', lambda: {'distribution': 'ravel-hep', 'version': '9.9.9'})
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='tag|tracked|version|release'):
        se.export(request, tmp_path / 'repo', framework_source='release:' + TAG if invalid == 'commit' else 'vendor',
                  framework_checkout=source)


def test_vendor_matches_tag_archive_and_manifest(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    out, _ = package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    vendor = out / 'vendor/ravel'; manifest = json.loads((vendor / 'VENDOR-MANIFEST.json').read_text())
    assert manifest['tag'] == TAG and manifest['commit'] == git(source, 'rev-parse', 'HEAD').decode().strip()
    rows = {row['path']: row for row in manifest['files']}
    assert set(rows) == {'pyproject.toml', 'src/ravel/__init__.py', 'docs/use.md', 'LICENSE', 'build_fixture.py', 'assets/value.txt'}
    archive = tarfile.open(fileobj=io.BytesIO(git(source, 'archive', TAG, '--', *rows)))
    for name, row in rows.items():
        raw = (vendor / name).read_bytes()
        assert raw == archive.extractfile(name).read()
        assert row['sha256'] == hashlib.sha256(raw).hexdigest()
        assert row['blob_id'] == git(source, 'rev-parse', f'{TAG}:{name}').decode().strip()
    assert (out / 'environment/ravel-requirements.txt').read_text() == './vendor/ravel\n'
    (vendor / 'assets/value.txt').write_text('tampered')
    assert not se.verify(out)['passed']


def test_release_pin_and_unshipped_changes(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch); (source / 'private.txt').write_text('unshipped change allowed')
    out, _ = package(tmp_path, monkeypatch, framework_source='release:' + TAG, framework_checkout=source)
    assert (out / 'environment/ravel-requirements.txt').read_text() == 'ravel-hep @ git+https://example.invalid/framework@' + git(source, 'rev-parse', 'HEAD').decode().strip() + '\n'
    record = json.loads((out / 'submission.json').read_text())['framework']
    assert record['tag'] == TAG and record['url'] == 'https://example.invalid/framework'


def test_layout_root_snakefile_and_renamed_target(tmp_path, monkeypatch):
    layout = {'schema_version': 1, 'subdir': '.', 'snakefile': 'Snakefile', 'rerun_target': 'rerun',
              'required_files': ['Makefile', 'REPRODUCE.md']}
    out, _ = package(tmp_path, monkeypatch, layout=layout)
    assert out.name == 'repository' and (out / 'Snakefile').exists()
    assert 'rerun' in (out / 'Makefile').read_text()
    assert 'make env' in (out / 'REPRODUCE.md').read_text()


@pytest.mark.parametrize('field,value', [('subdir', '../escape'), ('snakefile', '/outside/Snakefile'),
                                        ('required_files', ['../outside']), ('rerun_target', 'bad; touch x')])
def test_layout_refuses_escape(tmp_path, monkeypatch, field, value):
    layout = {'schema_version': 1, 'subdir': 'submission', 'snakefile': 'Snakefile', 'rerun_target': 'reproduce',
              'required_files': []}; layout[field] = value
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='layout|relative|target'):
        se.export(request, tmp_path / 'repo', layout=layout)


@pytest.mark.xfail(__import__('importlib.util').util.find_spec('ravel.workflow.replay') is None,
                   strict=True, reason='awaits governed replay')
def test_governed_replay_template_integration():
    from ravel.workflow import replay
    assert 'approval' in replay.template_text()


@pytest.mark.skipif(not os.environ.get('RAVEL_TEST_SNAKEMAKE'), reason='set RAVEL_TEST_SNAKEMAKE to run real Snakemake')
def test_real_clean_clone_make_check(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    git(out.parent, 'init', '-q'); git(out.parent, 'add', '.'); git(out.parent, 'commit', '-qm', 'package')
    target = tmp_path / 'another-parent/clone'; target.parent.mkdir()
    git(out.parent, 'clone', '--quiet', str(out.parent), str(target))
    bindir = tmp_path / 'bin'; bindir.mkdir()
    (bindir / 'snakemake').symlink_to(os.environ['RAVEL_TEST_SNAKEMAKE'])
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'])
    done = subprocess.run(['make', 'check'], cwd=target / 'submission', env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    from ravel import cli
    assert cli.main(['export-submission', 'verify', '--package', str(target / 'submission'), '--fresh-clone']) == 0


def test_staged_new_shipped_file_invalidates_release(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    (source / 'src/ravel/new.py').write_text('# added\n'); git(source, 'add', '.')
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='tracked'):
        se.export(request, tmp_path / 'repo', framework_source='vendor', framework_checkout=source)


def test_root_launcher_is_relative_with_separate_package(tmp_path, monkeypatch):
    layout = {'schema_version': 1, 'subdir': 'bundle', 'snakefile': 'Snakefile', 'rerun_target': 'rerun', 'required_files': []}
    out, _ = package(tmp_path, monkeypatch, layout=layout)
    launcher = (out.parent / 'Snakefile').read_text()
    assert "workdir: 'bundle'" in launcher and "include: 'bundle/Snakefile'" in launcher
    assert 'rerun' in (out / 'Makefile').read_text()


def test_json_escape_cannot_hide_a_known_root(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    (out / 'escaped.json').write_text('{"path": "\\u002foutside\\u002frun"}')
    assert any('escaped.json' in e and 'absolute' in e for e in se._check(out, roots=['/outside/run'])['errors'])


def test_relative_procedure_pin_cannot_escape_package(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    docpath = out / 'procedure/procedure.json'; doc = json.loads(docpath.read_text())
    external = tmp_path / 'external.json'; external.write_text('{}')
    doc['source_pins'][0].update(path='../../../external.json', size=2, sha256=se.file_sha256(external))
    docpath.write_text(json.dumps(doc))
    closurepath = out / 'procedure/closure.json'; closure = json.loads(closurepath.read_text())
    row = next(r for r in closure['files'] if r['path'] == 'procedure.json')
    row.update(sha256=se.file_sha256(docpath), size=docpath.stat().st_size); closurepath.write_text(json.dumps(closure))
    with pytest.raises(ValueError, match='escape|inside'):
        pe.verify(out / 'procedure', deep=True)


@pytest.mark.parametrize('text', ['#!/outside/exporting/python\nprint(1)\n',
                                 'file:///outside/run/data.json',
                                 '{"pin": "prefix:/outside/module.py"}'])
def test_literal_known_root_is_detected_in_path_syntax(text):
    assert se._absolute_paths(text, ['/outside'])


def test_runtime_expressions_and_remote_uris_do_not_name_known_roots():
    assert not se._absolute_paths('#!/bin/sh\ncd "$PWD/.bin"\nhttps://example.invalid/source\n${CURDIR}/.bin\n', ['/outside'])


def test_external_evidence_is_copied_and_bound_inside_package(tmp_path, monkeypatch):
    original_build = pe.build
    external = tmp_path / 'evidence.json'; external.write_text('{"value": 7}')
    def build(*args, **kwargs):
        document = original_build(*args, **kwargs)
        document['source_pins'].append(pe._source(external))
        return document
    monkeypatch.setattr(pe, 'build', build)
    out, _ = package(tmp_path, monkeypatch)
    external.unlink()
    document = pe.verify(out / 'procedure', deep=True)
    assert any('evidence/' in pin['path'] for pin in document['source_pins'])
    assert se.verify(out, fresh_clone=True)['passed']


def test_vendor_text_with_known_checkout_root_is_refused(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    (source / 'src/ravel/__init__.py').write_text('SOURCE = ' + repr(str(source)) + '\n')
    git(source, 'add', '.'); git(source, 'commit', '-qm', 'literal path'); git(source, 'tag', 'v1.0.1')
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='vendor/ravel/src/ravel/__init__.py.*absolute'):
        se.export(request, tmp_path / 'repo', framework_source='vendor', framework_checkout=source)


def test_generated_setup_script_is_shipped_unchanged(tmp_path, monkeypatch):
    from ravel.workflow import environment_export as ee
    out, _ = package(tmp_path, monkeypatch)
    assert (out / 'environment/setup.sh').read_text() == ee.SETUP
    projected = [row['path'] for row in json.loads((out / 'submission.json').read_text())['path_projections']]
    assert 'environment/setup.sh' not in projected
    assert not se._absolute_paths('cd "$(CDPATH= cd -P "$(dirname "$0")/.." && pwd)"\n')
    assert se._absolute_paths('cd "$(dirname "$0")" /outside/run\n', ['/outside/run']) == ['/outside/run']


def test_vendor_uses_one_git_executable(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    commands, run = [], subprocess.run
    def record(argv, *args, **kwargs):
        commands.append(argv[0]); return run(argv, *args, **kwargs)
    monkeypatch.setattr(se.subprocess, 'run', record)
    package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    assert GIT in commands and 'git' not in commands


def test_source_comment_is_not_a_machine_path(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    (request.parent / 'routine.cc').write_text('// select events\nint pass() { return 1; }\n')
    document = json.loads(request.read_text()); document['code'].append('routine.cc')
    request.write_text(json.dumps(document))
    se.export(request, tmp_path / 'repository')


def test_json_pointer_in_run_input_is_copied_unchanged(tmp_path, monkeypatch):
    request, run = accepted_analysis(tmp_path, monkeypatch)
    patch = [{'op': 'add', 'path': '/channels/0/samples/0', 'value': {'name': 'signal', 'data': [1.0]}}]
    (run / 'inputs/patch.json').write_text(json.dumps(patch))
    out = Path(se.export(request, tmp_path / 'repository')['package'])
    assert json.loads((out / 'run/inputs/patch.json').read_text()) == patch


def test_relative_rule_expression_is_not_a_machine_path(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    raw = 'receipt = config["x"] + "/y.json"\n'
    (request.parent / 'selection.py').write_text(raw)
    out = Path(se.export(request, tmp_path / 'repository')['package'])
    assert (out / 'code/selection.py').read_text() == raw


def test_vendor_accepts_release_source_with_tool_path_constants(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    (source / 'src/ravel/__init__.py').write_text(f'__version__ = "{VERSION}"\nGIT = "/usr/bin/git"\n')
    git(source, 'add', '.'); git(source, 'commit', '-qm', 'tool path'); git(source, 'tag', 'v1.0.1')
    out, _ = package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    assert se.verify(out)['passed']


def test_recipe_json_pointer_exports(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    raw = '{"pointer": "/channels/0/samples/0"}\n'
    (request.parent / 'recipe.json').write_text(raw)
    out = Path(se.export(request, tmp_path / 'repo')['package'])
    assert (out / 'recipe/recipe.json').read_text() == raw


def test_review_snapshot_remains_content_addressed(tmp_path, monkeypatch):
    request, run = accepted_analysis(tmp_path, monkeypatch)
    raw = b'{"pointer": "/channels/0/samples/0"}'
    digest = hashlib.sha256(raw).hexdigest()
    snapshot = run / 'logs/physics_review/snapshots' / (digest + '.blob')
    snapshot.parent.mkdir(parents=True, exist_ok=True); snapshot.write_bytes(raw)
    out = Path(se.export(request, tmp_path / 'repo')['package'])
    copied = out / 'run' / snapshot.relative_to(run)
    assert copied.read_bytes() == raw and se.file_sha256(copied) == copied.stem


@pytest.mark.parametrize('location', ['run', 'interpreter', 'framework', 'home'])
def test_export_refuses_literal_known_root(tmp_path, monkeypatch, location):
    request, run = accepted_analysis(tmp_path, monkeypatch)
    roots = {'run': str(run), 'interpreter': sys.executable,
             'framework': str(Path(se.__file__).resolve().parents[3]), 'home': str(Path.home())}
    (request.parent / 'selection.py').write_text('SOURCE = ' + repr(roots[location]) + '\n')
    with pytest.raises(ValueError, match='code/selection.py.*absolute'):
        se.export(request, tmp_path / 'repo')


def test_input_with_known_root_is_refused_without_rewrite(tmp_path, monkeypatch):
    request, run = accepted_analysis(tmp_path, monkeypatch)
    pin = run / 'inputs/path.json'; raw = json.dumps({'source': str(run / 'data')})
    pin.write_text(raw)
    with pytest.raises(ValueError, match='run/inputs/path.json.*absolute'):
        se.export(request, tmp_path / 'repo')
    assert pin.read_text() == raw


def test_path_scan_does_not_read_above_eight_mib(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    large = out / 'code/large.txt'; large.write_bytes(b'x' * (se.RUN_RECORD_MAX_BYTES + 1))
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert path != large, 'large packaged text must not be read for the path scan'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    se._check(out, roots=['/outside'])


def test_default_pin_uses_checked_package_metadata(tmp_path, monkeypatch):
    import tomllib
    project = tomllib.loads((Path(se.__file__).resolve().parents[3] / 'pyproject.toml').read_text())['project']
    out, _ = package(tmp_path, monkeypatch)
    assert (out / 'environment/ravel-requirements.txt').read_text() == f"{project['name']}=={project['version']}\n"
    manifest = json.loads((out / se.MANIFEST).read_text())
    assert manifest['code_version']['ravel_version'] == project['version']
    pin = out / 'environment/ravel-requirements.txt'; pin.write_text('ravel-hep==99.0.0\n')
    for row in manifest['files']:
        if row['path'] == 'environment/ravel-requirements.txt':
            row.update(sha256=se.file_sha256(pin), size=pin.stat().st_size)
    (out / se.MANIFEST).write_text(json.dumps(manifest))
    assert any('framework pin' in e for e in se._check(out)['errors'])


def test_release_requirement_uses_tag_commit_and_omits_unused_tree(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    out, _ = package(tmp_path, monkeypatch, framework_source='release:' + TAG, framework_checkout=source)
    commit = git(source, 'rev-parse', TAG + '^{commit}').decode().strip()
    assert (out / 'environment/ravel-requirements.txt').read_text().endswith('@' + commit + '\n')
    assert 'release_tree' not in json.loads((out / se.MANIFEST).read_text())['framework']


def test_tracked_unlisted_bin_command_is_refused(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    command = out / '.bin/ravel'; command.parent.mkdir(); command.write_text('#!/bin/sh\nexit 0\n')
    git(out.parent, 'init', '-q'); git(out.parent, 'add', '.'); git(out.parent, 'commit', '-qm', 'fixture')
    assert any('.bin/ravel' in e and 'not listed' in e for e in se._check(out)['errors'])


def test_fresh_copy_skips_nested_work_directories(tmp_path, monkeypatch):
    out, _ = package(tmp_path, monkeypatch)
    work = out / 'procedure/.snakemake'; work.mkdir(); (work / 'cache').write_text('working state')
    observed = []
    def dry_run(fresh):
        observed.append(list(Path(fresh).rglob('.snakemake')))
        return {'status': 'passed', 'detail': 'inert workflow check'}
    monkeypatch.setattr(se, 'snakemake_dry_run', dry_run)
    assert se.verify(out, fresh_clone=True)['passed']
    assert observed == [[]]



def source_tree_fixture(tmp_path, monkeypatch):
    """The current source contract in an isolated, locally tagged fixture."""
    import ravel
    import tomllib
    root = Path(se.__file__).resolve().parents[3]
    source = tmp_path / 'source'; source.mkdir()
    raw = git(root, 'archive', 'HEAD')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(source, filter='data')
    # Exercise the proposed hook seam without changing the fixture's source roster.
    changed = git(root, 'diff', '--name-only').decode().splitlines()
    for name in (*changed, 'src/ravel/submission_build.py'):
        if (root / name).is_file():
            (source / name).write_bytes((root / name).read_bytes())
    version = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
    monkeypatch.setattr(ravel, '__version__', version)
    git(source, 'init', '-q'); git(source, 'add', '.'); git(source, 'commit', '-qm', 'fixture')
    git(source, 'tag', 'v' + version)
    return source


def fake_hook_inputs(source, monkeypatch):
    """Run only hook input selection through an inert build interface."""
    import runpy
    import types
    interface = types.ModuleType('hatchling.builders.hooks.plugin.interface')
    interface.BuildHookInterface = object
    monkeypatch.setitem(sys.modules, interface.__name__, interface)
    hook_type = runpy.run_path(str(source / 'hatch_build.py'))['CustomBuildHook']
    hook = hook_type(); hook.root = str(source); hook.target_name = 'sdist'
    data = {'force_include': {}}
    hook.initialize('fixture', data)
    return {Path(p).relative_to(source).as_posix() for p in data['force_include']}


def test_vendor_contains_every_build_hook_input(tmp_path, monkeypatch):
    source = source_tree_fixture(tmp_path, monkeypatch)
    expected = fake_hook_inputs(source, monkeypatch)
    out, _ = package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    vendor = out / 'vendor/ravel'
    assert not [name for name in sorted(expected) if not (vendor / name).is_file()]
    fake_hook_inputs(vendor, monkeypatch)
    assert not list(vendor.rglob('__pycache__'))
    assert se.verify(out, fresh_clone=False)['passed']


def test_hook_input_selection_leaves_no_source_bytecode(tmp_path, monkeypatch):
    source = source_tree_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    fake_hook_inputs(source, monkeypatch)
    assert not list(source.rglob('__pycache__'))
    assert sys.dont_write_bytecode is False


@pytest.mark.parametrize('tracked', [False, True])
def test_setup_command_links_are_allowed_only_when_untracked(tmp_path, monkeypatch, tracked):
    out, _ = package(tmp_path, monkeypatch)
    targets = {'.bin/ravel': '../.venv-analysis/bin/ravel', '.bin/snakemake': '../.venv-wms/bin/snakemake'}
    for name, target in targets.items():
        link = out / name; link.parent.mkdir(exist_ok=True)
        command = (link.parent / target).resolve(); command.parent.mkdir(parents=True, exist_ok=True)
        command.write_text('#!/bin/sh\nexit 0\n'); command.chmod(0o755)
        link.symlink_to(target)
    git(out.parent, 'init', '-q')
    if tracked: git(out.parent, 'add', 'submission/.bin')
    report = se._check(out)
    assert report['passed'] is not tracked, report['errors']


def test_installed_metadata_supplies_default_identity(tmp_path, monkeypatch):
    import importlib.metadata
    import types
    monkeypatch.setattr(se, '__file__', str(tmp_path / 'site/ravel/workflow/submission_export.py'))
    monkeypatch.setattr(importlib.metadata, 'distribution', lambda name:
                        types.SimpleNamespace(metadata={'Name': name}, version='7.2.1'))
    assert se._package_metadata() == {'distribution': 'ravel-hep', 'version': '7.2.1'}


def test_environment_target_prevents_source_bytecode(tmp_path, monkeypatch):
    """An inert installer stands in for the package loader; no build or install runs."""
    out, _ = package(tmp_path, monkeypatch)
    vendor = out / 'vendor/ravel'; vendor.mkdir(parents=True)
    (vendor / 'loader_fixture.py').write_text('VALUE = 1\n')
    (out / 'environment/setup.sh').write_text(
        'set -eu\ncd vendor/ravel\n"$FIXTURE_PYTHON" -c "import loader_fixture"\n')
    env = dict(os.environ, FIXTURE_PYTHON=sys.executable, PYTHONPATH='')
    env.pop('PYTHONDONTWRITEBYTECODE', None)
    done = subprocess.run(['make', 'env'], cwd=out, env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not list(vendor.rglob('__pycache__'))


def test_filesystem_root_is_never_a_known_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: Path('/')))
    roots = se._known_roots(tmp_path / 'run')
    assert '/' not in roots
    assert not se._absolute_paths('{"pointer": "/channels/0"}\n', roots)


def restricted_list(tmp_path, fingerprint):
    owner = tmp_path / 'owner'; owner.mkdir(exist_ok=True)
    path = owner / 'restricted-sources.json'
    path.write_text(json.dumps({'schema_version': 1, 'kind': 'restricted-sources', 'documents': [],
                                'fingerprints': [fingerprint]}))
    return path


def test_vendor_records_the_restricted_source_scan(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    monkeypatch.delenv('RAVEL_RESTRICTED_SOURCES', raising=False)
    out, _ = package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    manifest = json.loads((out / 'vendor/ravel/VENDOR-MANIFEST.json').read_text())
    assert manifest['restricted_source_scan'] == {'deny_list': 'none', 'findings': 0}
    assert se.RESTRICTED_SCAN not in {row['path'] for row in manifest['files']}
    assert se.verify(out)['passed']


def test_vendor_with_a_clean_deny_list_records_it_without_its_path(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    listed = restricted_list(tmp_path, 'zq-invented-marker-7731')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(listed))
    out, _ = package(tmp_path, monkeypatch, framework_source='vendor', framework_checkout=source)
    text = (out / 'vendor/ravel/VENDOR-MANIFEST.json').read_text()
    assert json.loads(text)['restricted_source_scan'] == {'deny_list': 'supplied', 'findings': 0}
    assert str(listed) not in text and 'zq-invented-marker-7731' not in text


def test_vendor_refuses_a_restricted_source_finding_and_leaves_no_package(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    (source / 'assets/value.txt').write_text('value zq-invented-marker-7731\n')
    git(source, 'commit', '-qam', 'fixture finding'); git(source, 'tag', '-f', TAG)
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(restricted_list(tmp_path, 'zq-invented-marker-7731')))
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=r'1 restricted-source finding\(s\): assets/value.txt') as refused:
        se.export(request, tmp_path / 'repository', framework_source='vendor', framework_checkout=source)
    assert 'zq-invented-marker-7731' not in str(refused.value)
    assert not (tmp_path / 'repository').exists()


def test_vendor_refuses_an_invalid_deny_list_and_a_release_without_the_scan(tmp_path, monkeypatch):
    source = checkout(tmp_path, monkeypatch)
    bad = tmp_path / 'owner-bad.json'; bad.write_text('{"schema_version": 2}')
    monkeypatch.setenv('RAVEL_RESTRICTED_SOURCES', str(bad))
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='deny list'):
        se.export(request, tmp_path / 'repository', framework_source='vendor', framework_checkout=source)
    monkeypatch.delenv('RAVEL_RESTRICTED_SOURCES')
    git(source, 'rm', '-q', se.RESTRICTED_SCAN); git(source, 'commit', '-qm', 'no scan'); git(source, 'tag', '-f', TAG)
    with pytest.raises(ValueError, match='carries no restricted-source scan'):
        se.export(request, tmp_path / 'repository', framework_source='vendor', framework_checkout=source)
    assert not (tmp_path / 'repository').exists()
