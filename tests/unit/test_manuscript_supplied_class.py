"""Synthetic source custody, supplied requirements and export refusal controls."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from ravel.workflow import manuscript_format as mf, manuscript_production as mp
from ravel.workflow import submission_export as se
from test_manuscript_build import fixture, put
from test_manuscript_six_findings import authored
from test_submission_export import accepted_analysis


def test_public_export_refuses_supplied_bundle_file_and_alias(tmp_path, monkeypatch):
    request, rd = accepted_analysis(tmp_path, monkeypatch)
    asset = put(request.parent, 'fictional.cls', 'Synthetic class bytes.\n')
    bundle = {'kind': 'user-supplied-class', 'redistributable': False, 'files': [asset]}
    record = put(request.parent, 'bundle.json', bundle)
    alias = request.parent / 'renamed.sty'
    alias.write_bytes(Path(asset['path']).read_bytes())
    value = json.loads(request.read_text())
    value['recipe'].append(record['path'])
    value['code'].append(str(alias))
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='non-redistributable'):
        se.export(request, tmp_path / 'public')
    assert not (tmp_path / 'public/submission').exists()


def test_required_supplied_sentence_is_a_finding():
    contract = {'profile': 'user', 'stage': 'draft', 'article_type': 'fictional',
        'rules': [{'id': 'disclosure', 'kind': 'required_text', 'scope': 'document',
            'value': 'These results use simulated pseudo-data.', 'origin': 'user', 'source_basis': None},
            {'id': 'sections', 'kind': 'required_sections', 'scope': 'main',
             'value': ['background'], 'origin': 'user', 'source_basis': None}]}
    note = {'paragraphs': [{'section': 'results', 'text': 'Synthetic result.'}], 'figures': [], 'citations': []}
    assert set(mf.assess(contract, note, template=None)['mechanical_failures']) == {'disclosure', 'sections'}
    note['paragraphs'].append({'section': 'background', 'text': 'These results use simulated pseudo-data.'})
    assert mf.assess(contract, note, template=None)['mechanical_failures'] == []


def test_private_authored_package_preserves_bundle_and_nested_files(tmp_path, monkeypatch):
    bundle_holder = {}
    def supplied(request, value, base):
        from ravel.physics.manuscript_assets import supplied_bundle
        folder = base / 'class-source'; folder.mkdir()
        (folder / 'fictional.cls').write_text(r'\ProvidesClass{fictional}\LoadClass{article}' + '\n')
        (folder / 'styles').mkdir()
        (folder / 'styles/fictional.sty').write_text('% Synthetic style\n')
        bundle = supplied_bundle(folder)
        bundle_holder.update(bundle)
        fmt = json.loads(Path(request['formatting']['path']).read_text())
        fmt['template_assets'] = [bundle]
        fmt['render']['class'] = 'source-template'
        template = (r'\documentclass{fictional}\usepackage{zref-user,zref-abspage}'
                    r'\input{styles/fictional.sty}\begin{document}' + '\n%RAVEL_BODY%\n' + r'\end{document}' + '\n')
        request['template'] = put(base, 'template.tex', template)
        value['template_units'] = [{'id': 'template-layout', 'kind': 'other', 'start': 0, 'end': len(template),
            'rendered_section': None, 'evidence_ids': [], 'citation_ids': [], 'method_ids': [], 'uncertainties': []}]
        request['formatting'] = put(base, 'format.json', fmt)
    _, _, collected = authored(tmp_path, monkeypatch, change=supplied)
    package = collected['package']
    mp.verify_author(package, base_dir=tmp_path / 'note')
    bundle = package['template_assets'][0]
    assert bundle['kind'] == 'user-supplied-class' and bundle['redistributable'] is False
    assert len(bundle['files']) == 2
    assert {p['sha256'] for p in bundle['files']} == {p['sha256'] for p in bundle_holder['files']}
    assert (tmp_path / 'note/styles/fictional.sty').is_file()
    assert r'\documentclass{fictional}' in Path(package['latex']['path']).read_text()
    assert package['formatting_assessment']['template_assets'][0]['redistributable'] is False


def test_bundle_build_uses_supervised_fake_compiler(tmp_path, monkeypatch):
    from ravel.physics.manuscript_assets import supplied_bundle
    from ravel.physics import manuscript_build as mb
    from ravel.physics import reinterpret_db
    from test_manuscript_build import inert_compiler
    task, config, package = fixture(tmp_path, monkeypatch)
    folder = tmp_path / 'bundle'; folder.mkdir()
    (folder / 'fictional.cls').write_text(r'\ProvidesClass{fictional}\LoadClass{article}' + '\n')
    package['template_assets'] = [supplied_bundle(folder)]
    config['package'] = put(tmp_path, 'package.json', package)
    put(tmp_path, 'config.json', config)
    monkeypatch.setattr(mb, '_approved', lambda *a: {'max_seconds': 30})
    inert_compiler(monkeypatch, tmp_path)
    result = mb.run(task, tmp_path, tmp_path / 'output')
    assert result['status'] == 'passed'
    assert (tmp_path / 'output/source/fictional.cls').is_file()
    assert result['template_assets'] == package['template_assets']


def test_bundle_rejects_symlinks_and_changed_leaf(tmp_path):
    from ravel.physics.manuscript_assets import supplied_bundle, pins
    folder = tmp_path / 'bundle'; folder.mkdir()
    leaf = folder / 'fictional.cls'; leaf.write_text('synthetic')
    record = supplied_bundle(folder)
    leaf.write_text('mutated')
    with pytest.raises(ValueError):
        pins([record], tmp_path, verify=True)
    leaf.unlink(); leaf.symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError):
        supplied_bundle(folder)


def test_public_export_accepts_metadata_without_restricted_bytes(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    asset = put(request.parent, 'fictional.cls', 'Private synthetic class.\n')
    record = put(request.parent, 'bundle.json', {'kind': 'user-supplied-class', 'redistributable': False, 'files': [asset]})
    value = json.loads(request.read_text()); value['recipe'].append(record['path']); request.write_text(json.dumps(value))
    result = se.export(request, tmp_path / 'public')
    assert se.verify(result['package'])['passed']


def test_public_export_cannot_hide_bundle_record_in_text_extension(tmp_path, monkeypatch):
    request, _ = accepted_analysis(tmp_path, monkeypatch)
    asset = put(request.parent, 'fictional.cls', 'Private synthetic class.\n')
    record = put(request.parent, 'bundle.txt', {'kind': 'user-supplied-class', 'redistributable': False, 'files': [asset]})
    value = json.loads(request.read_text()); value['recipe'].append(record['path']); value['code'].append(asset['path'])
    request.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='non-redistributable'):
        se.export(request, tmp_path / 'public')


@pytest.mark.parametrize('sentence,section,ceiling', [('Synthetic disclosure one.', 'background', 3),
                                                   ('Synthetic disclosure two.', 'validation', 6)])
def test_requester_pack_changes_without_product_edits(tmp_path, sentence, section, ceiling):
    pack = {'schema_version': 1, 'kind': 'note-rule-pack', 'id': 'ANA-0001', 'title': 'Fictional note',
        'origin': 'user', 'source_basis': None, 'max_main_pages': ceiling, 'max_figures': None, 'max_tables': None,
        'excluded_sections': ['appendix'], 'required_semantics': [section], 'main_text_semantics': [section],
        'allow_user_count_exclusions': True, 'requires_supplied_requirements': False, 'required_sentences': [sentence]}
    pack_pin = put(tmp_path, 'rules.json', pack)
    render = {'class': 'article', 'frontmatter': 'title-before-abstract', 'graphics': 'inline', 'line_numbers': False,
        'appendices': 'after-references', 'citation_style': 'numeric-brackets', 'post_reference_sections': [], 'quantitative_position': 'main'}
    contract = mf.build_note_contract(pack, pack_pin, stage='draft', article_type='fictional', render=render)
    mf.load(put(tmp_path, 'format.json', contract), tmp_path, {})
    required = next(r['value'] for r in contract['rules'] if r['kind'] == 'required_sections')
    note = {'paragraphs': [{'section': s, 'text': sentence if s == section else 'Synthetic.'} for s in required], 'figures': [], 'citations': []}
    assert mf.assess(contract, note, template=None, compiled_pages={'main_text_pages': ceiling})['mechanical_failures'] == []
    assert not mf.counted(contract, 'appendix', 'pages')


def test_only_the_named_vendored_folder_is_outside_the_asset_guard(tmp_path):
    from ravel.physics.manuscript_assets import refuse_public_assets
    stage = tmp_path / 'stage'
    asset = put(tmp_path, 'fictional.cls', 'Private synthetic class.\n')
    # The framework's own data declares the record shape with no files; a vendored copy is not a bundle.
    (stage / 'vendor/ravel/data').mkdir(parents=True)
    (stage / 'vendor/ravel/data/shape.json').write_text(json.dumps(
        {'kind': 'user-supplied-class', 'redistributable': False, 'files': []}))
    refuse_public_assets(stage, exclude=('vendor/ravel',))
    # A staged listing that names the vendored file by path does not bring it back into the guard.
    (stage / 'listing.json').write_text(json.dumps({'files': [{'path': 'vendor/ravel/data/shape.json'}]}))
    refuse_public_assets(stage, exclude=('vendor/ravel',))
    with pytest.raises(ValueError, match='nonempty complete supplied bundle'):
        refuse_public_assets(stage)
    # Outside the named folder a supplied record and its bytes are still refused.
    (stage / 'run').mkdir()
    (stage / 'run/bundle.json').write_text(json.dumps(
        {'kind': 'user-supplied-class', 'redistributable': False, 'files': [asset]}))
    (stage / 'run/fictional.cls').write_bytes(Path(asset['path']).read_bytes())
    with pytest.raises(ValueError, match='non-redistributable'):
        refuse_public_assets(stage, exclude=('vendor/ravel',))
