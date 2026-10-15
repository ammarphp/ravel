"""Source-bound slide controls; all native and author authorities are inert."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.physics import manuscript_build as mb
from ravel.workflow import site_workflow
from test_manuscript_build import put


def source(root, monkeypatch):
    result = put(root, 'result.json', {'score': '1.2300', 'reference': '2.3400'})
    image = put(root, 'figure.pdf', '%PDF-SYNTHETIC\n')
    note = put(root, 'note.md', 'Synthetic score 1.2300 and reference 2.3400.\n')
    package = {'manuscript': note, 'latex': put(root, 'note.tex', '1.2300 and 2.3400'),
        'figures': [image], 'template_assets': [], 'source_base': str(root)}
    binding = {'rundir': str(root / 'note-run'), 'receipt': result, 'result': result}
    monkeypatch.setattr(mb, 'verified_result', lambda *a, **k: {'package': package,
        'config': {'max_seconds': 30}, 'input_paths': [result['path'], image['path']], 'proof_pins': [result]})
    audit = put(root, 'audit.json', {'totals': {'input_tokens': 120, 'output_tokens': 30}})
    spec = {'schema_version': 1, 'kind': 'supplied-slide-content', 'title': 'ANA-0001',
        'quantities': [{'id': 'score', 'label': 'Score', 'artifact': result, 'pointer': '/score'},
                       {'id': 'reference', 'label': 'Reference', 'artifact': result, 'pointer': '/reference'}],
        'slides': [{'title': 'Result', 'sections': [], 'quantities': ['score', 'reference'], 'figures': [image['path']]}],
        'audit': audit, 'theme': None}
    return binding, spec, package


def test_missing_compiler_writes_exact_source_without_launch(tmp_path, monkeypatch, capsys):
    from ravel.physics import manuscript_slides as ms
    binding, spec, _ = source(tmp_path, monkeypatch)
    monkeypatch.setattr(ms.shutil, 'which', lambda *a: None)
    report = ms.prepare(binding, spec, tmp_path / 'deck', minutes=7, base_dir=tmp_path)
    tex = (tmp_path / 'deck/slides.tex').read_text()
    assert '1.2300' in tex and '2.3400' in tex and '120' in tex and '30' in tex
    assert r'\documentclass{beamer}' in tex and '7 minutes' in tex
    assert report['compiled'] is False and report['native_calls'] == 0
    assert 'did not compile' in report['message']


@pytest.mark.parametrize('fault', ['absent-number', 'number-substring', 'foreign-result', 'foreign-figure', 'missing-reference'])
def test_changed_or_unbound_content_refused(tmp_path, monkeypatch, fault):
    from ravel.physics import manuscript_slides as ms
    binding, spec, package = source(tmp_path, monkeypatch)
    if fault == 'absent-number':
        package['manuscript'] = put(tmp_path, 'note.md', 'Synthetic note omitting values.')
        package['latex'] = put(tmp_path, 'note.tex', 'Synthetic source omitting values.')
    if fault == 'number-substring':
        package['manuscript'] = put(tmp_path, 'note.md', 'Different score 11.2300 and reference 2.3400.')
        package['latex'] = put(tmp_path, 'note.tex', 'Different score 11.2300 and reference 2.3400.')
    if fault == 'foreign-result':
        spec['quantities'][0]['artifact'] = put(tmp_path, 'foreign.json', {'score': '1.2300'})
    if fault == 'foreign-figure':
        spec['slides'][0]['figures'] = [put(tmp_path, 'foreign.pdf', '%PDF-SYNTHETIC')['path']]
    if fault == 'missing-reference':
        spec['quantities'][1]['pointer'] = '/missing'
    with pytest.raises(ValueError):
        ms.prepare(binding, spec, tmp_path / 'deck', minutes=3, base_dir=tmp_path)
    assert not (tmp_path / 'deck').exists()


def test_slide_native_entry_refuses_before_effect(tmp_path, monkeypatch):
    from ravel.physics import manuscript_slides as ms
    called = []
    monkeypatch.setattr(ms, 'load', lambda *a, **k: called.append('load'))
    with pytest.raises(ValueError, match='ordinary approved'):
        ms.run({'config': 'absent.json'}, tmp_path, tmp_path / 'output')
    assert called == [] and not (tmp_path / 'output').exists()


def test_manuscript_task_rule_rebuild_routes_through_ordinary_manager(tmp_path):
    doc = {'python': {'path': '/synthetic/python'}, 'tasks': []}
    task = {'id': 'note', 'mode': 'manuscript-build', 'depends_on': []}
    rule = '\n'.join(site_workflow.task_rule(task, tmp_path / 'export.json', doc, tmp_path, 'verified.json'))
    assert 'rule task_note:' in rule and 'run-step' in rule and '--task note' in rule
    assert "completed/note.json" in rule and 'retries: 0' in rule


def test_fresh_manuscript_rerun_builds_through_manager_and_spent_run_refuses(tmp_path, monkeypatch):
    from ravel.workflow import science
    from ravel.physics import root_stream
    from test_site_workflow import workflow_fixture
    from test_manuscript_build import fixture, inert_compiler
    observed = []
    for index in range(2):
        base = tmp_path / str(index)
        task, config, package = fixture(base / 'note-origin', monkeypatch)
        package['latex'] = put(base / 'note-origin', 'note.tex', 'Synthetic successor ' + str(index))
        config['package'] = put(base / 'note-origin', 'package.json', package)
        put(base / 'note-origin', 'config.json', config)
        calls = inert_compiler(monkeypatch, base / 'note-origin')
        request, rd, _ = workflow_fixture(base / 'manager', monkeypatch)
        monkeypatch.setattr(science, 'execution_spec', lambda *a, **k: {'mode': 'manuscript-build', 'task': task})
        exported = site_workflow.export(request, base / 'manager', base / 'export')
        def run(rundir, resume):
            assert resume is False
            out = Path(rundir) / 'outputs'; out.mkdir()
            result = mb.run(task, base / 'note-origin', out / 'manuscript-build')
            observed.append((out / 'manuscript-build/source/note.tex').read_bytes())
            put(out, 'result.json', result)
            put(out, 'verification.json', {'passed': True, 'physics_validated': False})
            return 0
        monkeypatch.setattr(science, 'run', run)
        monkeypatch.setattr(root_stream, 'ordinary_delivery', lambda run, **k: {'outputs': [
            ms_pin(Path(run) / 'outputs/result.json'), ms_pin(Path(run) / 'outputs/verification.json')]})
        site_workflow.run_step(exported['manifest']['path'], 'analyze', exported['manifest']['sha256'])
        assert len(calls) == 3
        with pytest.raises(ValueError, match='spent WMS'):
            site_workflow.run_step(exported['manifest']['path'], 'analyze', exported['manifest']['sha256'])
    assert observed == [b'Synthetic successor 0', b'Synthetic successor 1']


def ms_pin(path):
    from ravel.physics.manuscript_slides import _pin
    return _pin(path)


def test_cli_has_manuscript_command(capsys):
    from ravel import cli
    with pytest.raises(SystemExit) as exc:
        cli.main(['manuscript', '--help'])
    assert exc.value.code == 0
    assert 'slides' in capsys.readouterr().out


@pytest.mark.parametrize('failure', [None, 'undeclared', 'mutated-source'])
def test_slide_build_uses_admitted_note_runtime_and_supervisor(tmp_path, monkeypatch, failure):
    from ravel.physics import manuscript_slides as ms, reinterpret_db
    from test_manuscript_build import fixture
    binding, spec, _ = source(tmp_path / 'note', monkeypatch)
    _, config, _ = fixture(tmp_path / 'runtime-origin', monkeypatch)
    tree = tmp_path / 'runtime-origin/runtime'
    put(tree, 'beamer.cls', 'Synthetic beamer bytes; never executed.')
    manifest = put(tmp_path / 'runtime-origin', 'runtime-manifest.json', {'schema_version': 1,
        'files': {p.name: ms._pin(p)['sha256'] for p in tree.iterdir()}})
    config['runtime']['asset_trees'][0]['manifest'] = {k: manifest[k] for k in ('path', 'sha256')}
    prior = mb.verified_result
    monkeypatch.setattr(mb, 'verified_result', lambda *a, **k: {**prior(*a, **k), 'config': config})
    report = ms.prepare(binding, spec, tmp_path / 'deck', minutes=4, base_dir=tmp_path / 'note')
    task = {'config': report['build_config']['path']}
    calls = []
    monkeypatch.setattr(mb, '_approved', lambda *a: {'max_seconds': 30})
    def native(argv, work, limits):
        work = Path(work); calls.append(argv)
        put(work, 'native-stdout.log', 'Pages: 4\n'); put(work, 'native-stderr.log', 'Synthetic\n')
        put(work, 'native-process.json', {'synthetic': True}); put(work, 'native-execution.json', {'synthetic': True})
        if Path(argv[0]).name == 'pdflatex':
            (work / 'slides.pdf').write_bytes(b'%PDF-SYNTHETIC')
            inputs = [str(work / 'slides.tex'), str(tree / 'beamer.cls')]
            if failure == 'undeclared':
                inputs.append(put(work, 'hidden.sty', 'undeclared')['path'])
            if failure == 'mutated-source':
                (work / 'slides.tex').write_text('changed by fake compiler')
            put(work, 'slides.fls', ''.join('INPUT ' + name + '\n' for name in inputs))
        return {'command': argv, 'synthetic': True}
    monkeypatch.setattr(reinterpret_db, 'execute_native', native)
    if failure:
        with pytest.raises(ValueError):
            mb.run(task, tmp_path, tmp_path / 'built')
        assert not (tmp_path / 'built/slides-build.json').exists()
    else:
        result = mb.run(task, tmp_path, tmp_path / 'built')
        assert result['compiled'] and result['pages'] == 4 and len(calls) == 3
        assert result['quantities']['score']['rendered'].encode() == b'1.2300'
        assert all('-no-shell-escape' in call and '-recorder' in call for call in calls[:2])
