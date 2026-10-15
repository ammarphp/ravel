"""Conformance: governing source restrictions refuse before source IO and retain receipts."""
import importlib
import json
from pathlib import Path

import pytest

import synthetic_identifiers as syn

from ravel.workflow import hepdata_fetch as hf
from ravel.plotting import fetch_figures as ff, digitize



def rule(kind='forbidden-source', **selectors):
    return {'kind': kind, 'statement': 'Declared source restriction', 'evidence': [],
            'origin': 'harness', **selectors}


def governed(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'inputs').mkdir(exist_ok=True)
    contract = {'schema_version': 1, 'prompt': 'Compute a supplied prediction.',
                'task_mode': 'reproduce', 'detector_mode': 'particle-level',
                'stat_mode': 'best-sr-counting', 'required_user_inputs': [], 'assumptions': [],
                'compute_plan': 'none', 'approval_required': True, 'forbidden_sources': rows}
    (root / 'inputs/task_contract.json').write_text(json.dumps(contract))
    return root


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    calls = []
    def opener(*args, **kwargs):
        calls.append(args)
        raise AssertionError('network opener called')
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', opener)
    monkeypatch.setattr(hf.discovery_http, '_urlopen', opener)
    monkeypatch.setattr(hf.discovery_http, 'open_url', opener)
    monkeypatch.setattr(hf.discovery_http, 'fetch_hepdata_record', opener)
    import hepdata_cli.api
    class InertClient:
        download = staticmethod(opener)
    monkeypatch.setattr(hepdata_cli.api, 'Client', InertClient)
    yield calls
    assert calls == []


def guard():
    return importlib.import_module('ravel.workflow.restriction_guard')


def refused(root, action):
    with pytest.raises(ValueError, match='source restriction.*receipt') as exc:
        action()
    receipts = list((root / 'logs/source-receipts').glob('*.json'))
    assert receipts
    receipt = json.loads(receipts[-1].read_text())
    assert receipt['allowed'] is False
    assert receipt['tool'] and receipt['source']
    assert any(str(p) in str(exc.value) for p in receipts)
    return receipt


@pytest.mark.parametrize('entry', ['main', 'routine', 'get_json', '_open', 'tables', 'bulk', 'offline', 'offline_cli'])
def test_each_table_entry_refuses_before_io(tmp_path, entry, monkeypatch):
    run = governed(tmp_path / 'run', [rule(identifiers={'inspire': ['ins1004'], 'hepdata': ['1001']})])
    out = run / 'outputs/values'
    rec = {'recid': 1001, 'record': {'inspire_id': '1004'}, 'data_tables': [{'id': 1, 'name': 'Table 1'}]}
    calls = {
        'main': lambda: hf.main(['--inspire', '1004', '--out', str(out)]),
        'routine': lambda: hf.main(['--routine', 'SYN_9009_I1004', '--out', str(out), '--tables', '--download-likelihood']),
        'get_json': lambda: hf.get_json('https://www.hepdata.net/record/ins1004?format=json'),
        '_open': lambda: hf._open('https://www.hepdata.net/record/ins1004?format=json'),
        'tables': lambda: hf.fetch_tables_via_record_data(rec, out, {'table_files': []}, get_json_fn=lambda u: pytest.fail('source callback called')),
        'bulk': lambda: hf._tables_via_hepdata_cli('ins1004', out, {'table_files': []}),
        'offline': lambda: hf.fetch_offline_fixture(run / 'inputs/fixture', out, tables=True),
        'offline_cli': lambda: hf.main(['--offline-fixture', str(run / 'inputs/fixture'), '--offline', '--tables', '--download-likelihood', '--out', str(out)]),
    }
    if entry in ('get_json', '_open'):
        monkeypatch.chdir(run)
    receipt = refused(run, calls[entry])
    assert receipt['rules']
    assert not out.exists()


@pytest.mark.parametrize('entry', ['main', 'arxiv', '_open', 'metadata', 'archive', 'map', 'page', 'resolve'])
def test_each_figure_entry_refuses_before_io(tmp_path, monkeypatch, entry):
    run = governed(tmp_path / 'run', [rule(identifiers={'inspire': ['ins1004'], 'arxiv': [syn.arxiv(4)]}, paths=['fictional-note.pdf'])])
    monkeypatch.chdir(run)
    out = run / 'outputs/gallery'
    doc = run / 'inputs/fictional-note.pdf'
    calls = {
        'main': lambda: ff.main(['--inspire', 'ins1004', '--out', str(out)]),
        'arxiv': lambda: ff.main(['--arxiv', syn.arxiv(4), '--out', str(out), '--map-captions', '--figure', '1']),
        '_open': lambda: ff._open('https://arxiv.org/pdf/' + syn.arxiv(4)),
        'metadata': lambda: ff.arxiv_from_inspire('ins1004'),
        'archive': lambda: ff.extract_figure_files(doc, out),
        'map': lambda: ff.build_figure_map(doc, {}, syn.arxiv(4)),
        'page': lambda: ff.pdf_page_route(doc, '1', out),
        'resolve': lambda: ff.resolve_figure('1', None, out, doc, out, syn.arxiv(4)),
    }
    refused(run, calls[entry])
    assert not out.exists()


@pytest.mark.parametrize('entry', ['parse', 'inventory', 'run', 'cli', 'load_series'])
def test_each_digitize_entry_refuses_before_source_read(tmp_path, monkeypatch, entry):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', paths=['fictional-note.pdf'])])
    monkeypatch.chdir(run)
    doc = run / 'inputs/fictional-note.pdf'
    spec = run / 'inputs/spec.json'
    spec.write_text(json.dumps({'schema_version': 1, 'source': {'path': str(doc)}}))
    out = run / 'outputs/digitized'
    def cli():
        from ravel.physics import figure_comparison
        assert figure_comparison.main(['digitize', '--spec', str(spec), '--out', str(out)]) == 2
        assert list((run / 'logs/source-receipts').glob('*.json'))
    calls = {
        'parse': lambda: digitize.parse_pdf_page(doc),
        'inventory': lambda: digitize.inventory(doc),
        'run': lambda: digitize.run_spec(spec, out),
        'load_series': lambda: digitize.load_series({'kind': 'digitized-series', 'source': {'path': str(doc)}, 'series': [{'name': 'curve'}]}, 'curve'),
    }
    if entry == 'cli':
        cli()
    else:
        refused(run, calls[entry])
    assert not out.exists()


@pytest.mark.parametrize('route', ['explicit', 'output', 'cwd', 'outside_output'])
def test_governing_contract_routes(tmp_path, monkeypatch, route):
    run = governed(tmp_path / 'run', [rule()])
    nested = run / 'work/nested'
    nested.mkdir(parents=True)
    kwargs = {'rundir': run} if route == 'explicit' else {'output': nested / 'values.json'}
    if route in ('cwd', 'outside_output'):
        monkeypatch.chdir(nested)
        kwargs = {} if route == 'cwd' else {'output': tmp_path / 'elsewhere/values.json'}
    refused(run, lambda: guard().require('test-reader', {'classes': ['published-values']}, **kwargs))


def test_nested_runs_all_bind_and_repeated_receipts_are_preserved(tmp_path):
    outer = governed(tmp_path / 'outer', [rule()])
    inner = governed(outer / 'inner', [rule()])
    for _ in range(2):
        refused(inner, lambda: guard().require('test-reader', {'quantities': ['limit']}, output=inner / 'outputs/x'))
    assert len(list((outer / 'logs/source-receipts').glob('*.json'))) == 2
    assert len(list((inner / 'logs/source-receipts').glob('*.json'))) == 2


@pytest.mark.parametrize('bad', ['json', 'schema', 'rows', 'duplicate', 'directory', 'unreadable'])
def test_invalid_contract_fails_closed(tmp_path, monkeypatch, bad):
    run = governed(tmp_path / 'run', [])
    path = run / 'inputs/task_contract.json'
    if bad == 'json': path.write_text('{')
    elif bad == 'schema': path.write_text('{}')
    elif bad == 'rows': path.write_text(json.dumps({'forbidden_sources': 'invalid'}))
    elif bad == 'duplicate': path.write_text('{"schema_version":1,"forbidden_sources":[],"forbidden_sources":[]}')
    elif bad == 'directory': path.unlink(); path.mkdir()
    else:
        original = Path.open
        def opening(self, *args, **kwargs):
            if self == path: raise PermissionError('unreadable contract')
            return original(self, *args, **kwargs)
        monkeypatch.setattr(Path, 'open', opening)
    refused(run, lambda: guard().require('test-reader', {'quantities': ['limit']}, rundir=run))


def test_environment_and_explicit_unrestricted_run_cannot_lift_refusal(tmp_path, monkeypatch):
    run = governed(tmp_path / 'run', [rule()])
    other = governed(tmp_path / 'other', [])
    monkeypatch.chdir(run)
    for key in ('RAVEL_RUN_DIR', 'RAVEL_STATE_DIR', 'RAVEL_SOURCE_POLICY', 'RAVEL_ALLOW_FORBIDDEN', 'RAVEL_OFFLINE'):
        monkeypatch.setenv(key, str(other))
    refused(run, lambda: guard().require('test-reader', {'quantities': ['limit']}, rundir=other, output=tmp_path / 'outside'))


def test_metadata_allowed_but_named_document_refused(tmp_path):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', identifiers={'arxiv': [syn.arxiv(4)]}, scope={'quantities': ['limit']})])
    guard().require('text-reader', {'path': str(run / 'inputs/fictional-note.pdf'), 'identifiers': {'arxiv': [syn.arxiv(4)]}, 'quantities': ['text']}, rundir=run)
    governed(run, [rule(paths=['fictional-note.pdf'])])
    refused(run, lambda: guard().require('text-reader', {'path': str(run / 'inputs/fictional-note.pdf'), 'quantities': ['text']}, rundir=run))


def test_local_pdf_gallery_is_qualitative_and_inherits_restriction(tmp_path):
    from pypdf import PdfWriter
    run = governed(tmp_path / 'run', [rule('no-value-extraction', paths=['fictional-note.pdf'])])
    doc = run / 'inputs/fictional-note.pdf'
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    with doc.open('wb') as stream: writer.write(stream)
    out = run / 'outputs/gallery'
    ff.main(['--pdf', str(doc), '--out', str(out)])
    manifest = json.loads((out / 'figure_manifest.json').read_text())
    assert manifest['usage'] == 'qualitative'
    assert manifest['source']['path'] == str(doc)
    figure = out / manifest['figures'][0]['path']
    assert figure.is_file()
    spec = run / 'inputs/spec.json'
    spec.write_text(json.dumps({'source': {'path': str(figure)}}))
    receipt = refused(run, lambda: digitize.run_spec(spec, run / 'outputs/values'))
    assert receipt['source']['path'] == 'fictional-note.pdf'


def test_symlink_output_and_source_aliases_do_not_escape_policy(tmp_path):
    run = governed(tmp_path / 'run', [rule(paths=['fictional-note.pdf'])])
    doc = run / 'inputs/fictional-note.pdf'; doc.write_text('synthetic text')
    alias = tmp_path / 'alias.pdf'; alias.symlink_to(doc)
    link = tmp_path / 'output'; link.symlink_to(run)
    refused(run, lambda: guard().require('text-reader', {'path': str(alias), 'quantities': ['text']}, output=link / 'outputs/x'))


@pytest.mark.parametrize('entry', ['archive', 'page', 'tables'])
def test_identity_restriction_refuses_opaque_cached_sources(tmp_path, entry):
    run = governed(tmp_path / 'run', [rule(identifiers={'inspire': ['ins1004']})])
    out = run / 'outputs/values'
    source = run / 'inputs/fictional-note.pdf'
    action = {
        'archive': lambda: ff.extract_figure_files(source, out),
        'page': lambda: ff.pdf_page_route(source, '1', out),
        'tables': lambda: hf.fetch_tables_via_record_data({'recid': 1001, 'data_tables': [{'id': 1, 'name': 'Table 1'}]}, out, {'table_files': []}, get_json_fn=lambda u: pytest.fail('source callback called')),
    }[entry]
    refused(run, action)
    assert not out.exists()


def test_proven_unrelated_record_remains_readable(tmp_path):
    run = governed(tmp_path / 'run', [rule(identifiers={'inspire': ['ins1004']})])
    guard().require('test-reader', {'identifiers': {'inspire': ['ins1008']}, 'quantities': ['limit']}, rundir=run)
    assert not (run / 'logs').exists()


def test_receipt_symlink_does_not_write_outside_the_run(tmp_path):
    run = governed(tmp_path / 'run', [rule()])
    elsewhere = tmp_path / 'elsewhere'; elsewhere.mkdir()
    (run / 'logs').symlink_to(elsewhere)
    with pytest.raises(ValueError, match='receipt'):
        guard().require('test-reader', {'quantities': ['limit']}, rundir=run)
    assert list(elsewhere.iterdir()) == []


def test_document_text_stays_readable_under_extraction_rule(tmp_path):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', paths=['fictional-note.pdf'])])
    doc = run / 'inputs/fictional-note.pdf'; doc.write_text('Supplied object definitions.')
    guard().require('text-reader', {'path': str(doc), 'classes': ['public-metadata'], 'quantities': ['text']}, rundir=run)
    assert doc.read_text() == 'Supplied object definitions.'
    governed(run, [rule(paths=['fictional-note.pdf'])])
    refused(run, lambda: guard().require('text-reader', {'path': str(doc), 'quantities': ['text']}, rundir=run))


def test_empty_contract_census_does_not_mistake_existing_output_for_run(tmp_path):
    output = tmp_path / 'existing.json'; output.write_text('{}')
    guard().require('test-reader', {'quantities': ['limit']}, output=output)


@pytest.mark.parametrize('entry', ['local_gallery', 'local_cli', 'tex_members'])
def test_named_document_refuses_every_local_figure_route(tmp_path, monkeypatch, entry):
    run = governed(tmp_path / 'run', [rule(paths=['fictional-note.pdf'])])
    monkeypatch.chdir(run)
    doc = run / 'inputs/fictional-note.pdf'
    out = run / 'outputs/gallery'
    action = {'local_gallery': lambda: ff._local_pdf_gallery(doc, out),
              'local_cli': lambda: ff.main(['--pdf', str(doc), '--out', str(out)]),
              'tex_members': lambda: ff._read_tex_members(doc)}[entry]
    refused(run, action)
    assert not out.exists()


@pytest.mark.parametrize('entry', ['specification', 'series_document'])
def test_source_metadata_arguments_cannot_lift_numeric_refusal(tmp_path, monkeypatch, entry):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', paths=['fictional-note.pdf'])])
    source = {'path': str(run / 'inputs/fictional-note.pdf'), 'quantities': ['text'], 'classes': ['public-metadata']}
    spec = run / 'inputs/spec.json'; spec.write_text(json.dumps({'schema_version': 1, 'source': source}))
    monkeypatch.chdir(run)
    action = (lambda: digitize.run_spec(spec, run / 'outputs/values')) if entry == 'specification' else (
        lambda: digitize.load_series({'kind': 'digitized-series', 'source': source, 'series': [{'name': 'curve'}]}, 'curve'))
    refused(run, action)


def test_directory_glob_binds_through_output_and_source_symlinks(tmp_path):
    run = governed(tmp_path / 'run', [rule(paths=['refs/**/*.pdf'])])
    doc = run / 'inputs/refs/nested/fictional-note.pdf'
    doc.parent.mkdir(parents=True); doc.write_text('synthetic text')
    source_alias = tmp_path / 'document.pdf'; source_alias.symlink_to(doc)
    output_alias = tmp_path / 'output'; output_alias.symlink_to(run)
    refused(run, lambda: guard().require('text-reader', {'path': str(source_alias), 'quantities': ['text']}, output=output_alias / 'outputs/x'))


@pytest.mark.parametrize('declared,requested', [(syn.arxiv(4), syn.arxiv(4) + 'v2'), (syn.arxiv(4) + 'v1', syn.arxiv(4)),
                                                ('ins1004', 'ins01004')])
def test_identity_spelling_variants_still_bind(tmp_path, monkeypatch, declared, requested):
    key = 'inspire' if declared.startswith('ins') else 'arxiv'
    run = governed(tmp_path / 'run', [rule(identifiers={key: [declared]})])
    monkeypatch.chdir(run)
    out = run / 'outputs/gallery'
    flag = '--inspire' if key == 'inspire' else '--arxiv'
    refused(run, lambda: ff.main([flag, requested, '--out', str(out)]))
    assert not out.exists()


# Review findings: each test exercises a reviewed bypass or false refusal.

def test_caller_manifest_identity_cannot_replace_record_identity(tmp_path):
    run = governed(tmp_path / 'run', [rule(identifiers={'inspire': ['ins1004']})])
    out = run / 'outputs/values'
    rec = {'recid': 1001, 'inspire_id': '1004', 'data_tables': [{'id': 1, 'name': 'Table 1'}]}
    refused(run, lambda: hf.fetch_tables_via_record_data(
        rec, out, {'table_files': [], 'inspire': 'ins1008'}, get_json_fn=lambda u: pytest.fail('source callback called')))
    assert not out.exists()


def _fixture(root):
    (root / 'tables').mkdir(parents=True)
    (root / 'models').mkdir()
    rec = {'recid': 1001, 'version': 1, 'data_tables': [{'id': 1, 'name': 'Table 1'}],
           'resources': [{'url': 'https://example.invalid/model.tar.gz', 'description': 'likelihood'}]}
    (root / 'record.json').write_text(json.dumps(rec))
    (root / 'tables/1.json').write_text(json.dumps({'values': [{'x': 1}], 'description': 'synthetic'}))
    (root / 'likelihoods.json').write_text(json.dumps({'https://example.invalid/model.tar.gz': ['models/bkg.json']}))
    (root / 'models/bkg.json').write_text(json.dumps({'channels': []}))
    return root


@pytest.mark.parametrize('member', ['fixture/tables/1.json', 'fixture/record.json', 'fixture/likelihoods.json', 'fixture/models/bkg.json'])
def test_offline_fixture_members_are_admitted_by_their_own_paths(tmp_path, member):
    run = governed(tmp_path / 'run', [rule(paths=[member])])
    fixture = _fixture(run / 'inputs/fixture')
    out = run / 'outputs/values'
    refused(run, lambda: hf.fetch_offline_fixture(fixture, out, tables=True, download_likelihood=True))
    assert not (out / 'hepdata_manifest.json').exists()
    assert not (out / 'tables').exists()


def test_offline_fixture_unrelated_member_rule_still_copies(tmp_path):
    run = governed(tmp_path / 'run', [rule(paths=['fixture/tables/9.json'])])
    fixture = _fixture(run / 'inputs/fixture')
    manifest = hf.fetch_offline_fixture(fixture, run / 'outputs/values', tables=True, download_likelihood=True)
    assert manifest['errors'] == [] and manifest['status'] == 'OK'


def test_symlink_followed_by_parent_reference_finds_the_physical_run(tmp_path):
    run = governed(tmp_path / 'run', [rule()])
    (run / 'sub').mkdir()
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'link').symlink_to(run / 'sub')
    refused(run, lambda: guard().require('test-reader', {'quantities': ['limit']},
                                         output=str(outside / 'link') + '/../outputs/x'))


def test_source_symlink_followed_by_parent_reference_keeps_its_input_path(tmp_path):
    run = governed(tmp_path / 'run', [rule(paths=['refs/fictional-note.pdf'])])
    (run / 'inputs/refs').mkdir(); (run / 'inputs/sub').mkdir()
    (run / 'inputs/refs/fictional-note.pdf').write_text('synthetic text')
    outside = tmp_path / 'outside'; outside.mkdir()
    (outside / 'link').symlink_to(run / 'inputs/sub')
    refused(run, lambda: guard().require('text-reader', {'path': str(outside / 'link') + '/../refs/fictional-note.pdf',
                                                         'quantities': ['text']}, rundir=run))


def test_runs_sharing_one_contract_file_each_bind(tmp_path):
    shared = governed(tmp_path / 'shared', [rule(paths=['fictional-note.pdf'])]) / 'inputs/task_contract.json'
    first, second = tmp_path / 'first', tmp_path / 'second'
    for run in (first, second):
        (run / 'inputs').mkdir(parents=True)
        (run / 'inputs/task_contract.json').symlink_to(shared)
        (run / 'inputs/fictional-note.pdf').write_text('synthetic text')
    with pytest.raises(ValueError, match='source restriction'):
        guard().require('text-reader', {'path': str(second / 'inputs/fictional-note.pdf'), 'quantities': ['text']},
                        rundir=first, output=second / 'outputs/x')
    assert list((second / 'logs/source-receipts').glob('*.json'))
    receipt = json.loads(next((second / 'logs/source-receipts').glob('*.json')).read_text())
    assert receipt['rules'] and receipt['source']['path'] == 'fictional-note.pdf'


def test_unrelated_nearer_manifest_does_not_hide_gallery_provenance(tmp_path):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', paths=['fictional-note.pdf'])])
    doc = run / 'inputs/fictional-note.pdf'; doc.write_text('synthetic text')
    gallery = tmp_path / 'gallery'; (gallery / 'figures').mkdir(parents=True)
    page = gallery / 'figures/page1.pdf'; page.write_text('synthetic page')
    (gallery / 'figure_manifest.json').write_text(json.dumps({'usage': 'qualitative', 'source': {'path': str(doc)},
        'figures': [{'path': 'figures/page1.pdf'}]}))
    (gallery / 'figures/figure_manifest.json').write_text(json.dumps({'usage': 'qualitative',
        'source': {'path': str(tmp_path / 'other.pdf')}, 'figures': [{'path': 'other.pdf'}]}))
    receipt = refused(run, lambda: guard().require('digitize', {'path': str(page)}, rundir=run))
    assert receipt['source']['path'] == 'fictional-note.pdf'


def test_digitizer_file_digest_is_admitted_before_reading(tmp_path, monkeypatch):
    run = governed(tmp_path / 'run', [rule(paths=['fictional-note.pdf'])])
    doc = run / 'inputs/fictional-note.pdf'; doc.write_text('synthetic text')
    monkeypatch.chdir(run)
    reads = []
    monkeypatch.setattr(digitize, 'read_bytes', lambda path: reads.append(path) or b'')
    refused(run, lambda: digitize.sha256_file(doc))
    assert reads == []


def test_digitizer_numeric_label_parser_is_not_public():
    assert not hasattr(digitize, 'numeric_labels')
    assert callable(digitize._numeric_labels)


def test_unlisted_scoped_quantity_binds_numeric_table_extraction(tmp_path):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', identifiers={'inspire': ['ins1004']},
                                           scope={'quantities': ['cross-section']})])
    out = run / 'outputs/values'
    rec = {'recid': 1001, 'inspire_id': '1004', 'data_tables': [{'id': 1, 'name': 'Table 1'}]}
    refused(run, lambda: hf.fetch_tables_via_record_data(rec, out, {'table_files': []},
                                                         get_json_fn=lambda u: pytest.fail('source callback called')))


def _tarball(path):
    import io, tarfile
    with tarfile.open(path, 'w:gz') as tf:
        data = b'synthetic figure'
        info = tarfile.TarInfo('fig1.png'); info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    return path


def test_tables_only_rule_permits_figure_extraction(tmp_path):
    run = governed(tmp_path / 'run', [rule(classes=['tables'])])
    tarpath = _tarball(run / 'inputs' / (syn.arxiv(9) + '.tar.gz'))
    extracted = ff.extract_figure_files(tarpath, run / 'outputs/gallery/figures')
    assert list(extracted) == ['fig1.png']
    assert not (run / 'logs').exists()


def test_unrelated_arxiv_request_keeps_its_identity_through_figure_routes(tmp_path, monkeypatch):
    run = governed(tmp_path / 'run', [rule(identifiers={'arxiv': [syn.arxiv(4)]})])
    monkeypatch.chdir(run)
    source = _tarball(tmp_path / 'source.tar.gz')
    class Response:
        def __init__(self, url): self.url = url
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            if '/e-print/' in self.url: return source.read_bytes()
            raise OSError('synthetic: no document')
    monkeypatch.setattr(ff, '_open', lambda url, timeout=60: Response(url))
    out = run / 'outputs/gallery'
    ff.main(['--arxiv', syn.arxiv(9), '--out', str(out)])
    assert (out / 'figures/fig1.png').is_file()
    assert not (run / 'logs').exists()


def test_metadata_only_record_lookup_is_not_numeric_extraction(tmp_path, monkeypatch):
    run = governed(tmp_path / 'run', [rule('no-value-extraction', identifiers={'inspire': ['ins1004']})])
    out = run / 'outputs/record'
    lookups = []
    monkeypatch.setattr(hf.discovery_http, 'fetch_hepdata_record', lambda ref: lookups.append(ref) or {
        'status': 'OK', 'record': {'data_tables': []}, 'ref': 'ins1004', 'url': 'https://www.hepdata.net/record/ins1004'})
    hf.main(['--inspire', '1004', '--out', str(out)])
    assert lookups == ['ins1004']
    assert not (run / 'logs').exists()
    refused(run, lambda: hf.main(['--inspire', '1004', '--out', str(out), '--tables']))


def test_input_root_rule_does_not_bind_a_same_named_file_elsewhere(tmp_path):
    run = governed(tmp_path / 'run', [rule(paths=['fictional-note.pdf'])])
    other = run / 'inputs/allowed/fictional-note.pdf'
    other.parent.mkdir(); other.write_text('synthetic text')
    guard().require('text-reader', {'path': str(other), 'quantities': ['text']}, rundir=run)
    outside = tmp_path / 'fictional-note.pdf'; outside.write_text('synthetic text')
    guard().require('text-reader', {'path': str(outside), 'quantities': ['text']}, rundir=run)
    assert not (run / 'logs').exists()
