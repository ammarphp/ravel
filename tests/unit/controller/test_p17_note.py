"""P17 manuscript note build checks on fictional, offline fixture data."""
from __future__ import annotations

import hashlib
import json
import tarfile

from ravel.controller.routes.manuscript import note as manuscript_note


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path, *, result_bytes=None, quantity=0.75, claim_text='The measured value is 0.75.',
            note_text='# Fixture note\n\n[[claim:c1]]', quantity_value=None, title='Fixture note'):
    root = tmp_path / 'fixture'
    root.mkdir(parents=True)
    result = root / 'result.json'
    result.write_bytes(result_bytes if result_bytes is not None else b'{"metric":0.75}\n')
    claim_map = {
        'kind': 'manuscript-claim-map', 'schema_version': 1, 'title': title,
        'results': {'measurement': {'sha256': sha(result)}},
        'claims': [{'id': 'c1', 'text': claim_text, 'result': 'measurement',
                    'quantity': {'pointer': '/metric', 'value': quantity if quantity_value is None else quantity_value}}],
    }
    claim_path, note_path = root / 'claim-map.json', root / 'note.md'
    claim_path.write_text(json.dumps(claim_map, allow_nan=True))
    note_path.write_text(note_text)
    inputs = {'claim_map': claim_path, 'note': note_path, 'result.measurement': result}
    return inputs, result, claim_path


def sources(tmp_path, **kwargs):
    inputs, result, claim_path = fixture(tmp_path, **kwargs)
    receipt = manuscript_note.run_stage('sources', inputs, {}, tmp_path / 'sources')
    return receipt, tmp_path / 'sources', result, claim_path


def test_p17_note_sources_write_deterministic_tar_and_receipts(tmp_path):
    first, first_dir, *_ = sources(tmp_path / 'first')
    second, second_dir, *_ = sources(tmp_path / 'second')
    assert first['status'] == second['status'] == 'completed'
    assert (first_dir / 'outputs/sources.tar').read_bytes() == (second_dir / 'outputs/sources.tar').read_bytes()
    for workdir in (first_dir, second_dir):
        assert (workdir / 'outputs/integrity.json').is_file()
        assert (workdir / 'outputs/bundle.json').is_file()
        assert (workdir / 'outputs/receipt.json').is_file()
        with tarfile.open(workdir / 'outputs/sources.tar') as archive:
            assert archive.getnames() == ['main.tex']


def test_p17_changed_result_digest_refuses_integrity(tmp_path):
    inputs, result, _ = fixture(tmp_path)
    result.write_text('{"metric":0.76}\n')
    result = manuscript_note.run_stage('sources', inputs, {}, tmp_path / 'changed-work')
    assert result['status'] == 'refused' and result['codes'] == ['manuscript_integrity_failed']
    record = json.loads((tmp_path / 'changed-work/outputs/integrity.json').read_text())
    assert 'manuscript:claims-bound' in record['failing']


def test_p17_claim_quantity_must_match_result_value(tmp_path):
    receipt, workdir, *_ = sources(tmp_path, quantity=0.9, claim_text='The measured value is 0.9.')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_integrity_failed']
    record = json.loads((workdir / 'outputs/integrity.json').read_text())
    assert 'manuscript:quantities-traced' in record['failing']


def test_p17_missing_or_unknown_claim_marker_refuses(tmp_path):
    receipt, _, *_ = sources(tmp_path, note_text='# Fixture note\n\n[[claim:unknown]]')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_integrity_failed']


def test_p17_tex_unavailable_qualifies_without_manufacturing_pdf(tmp_path):
    inputs, *_ = fixture(tmp_path)
    source_dir = tmp_path / 'sources-work'
    source_receipt = manuscript_note.run_stage('sources', inputs, {}, source_dir)
    assert source_receipt['status'] == 'completed'
    pdf_inputs = {'sources': source_dir / 'outputs/sources.tar', 'bundle': source_dir / 'outputs/bundle.json'}
    source_tar_sha = sha(pdf_inputs['sources'])
    workdir = tmp_path / 'pdf-work'
    receipt = manuscript_note.run_stage('pdf', pdf_inputs, {'tex': ''}, workdir)
    assert receipt['status'] == 'qualified' and receipt['codes'] == ['manuscript_tex_unavailable']
    build = json.loads((workdir / 'outputs/build.json').read_text())
    assert build['status'] == 'qualified'
    assert not (workdir / 'outputs/manuscript.pdf').exists()
    assert sha(pdf_inputs['sources']) == source_tar_sha


def test_p17_unsafe_source_member_is_refused_before_missing_tex(tmp_path):
    inputs, *_ = fixture(tmp_path)
    source_dir = tmp_path / 'sources-work'
    manuscript_note.run_stage('sources', inputs, {}, source_dir)
    archive_path = tmp_path / 'unsafe.tar'
    with tarfile.open(archive_path, 'w') as archive:
        import io
        member = tarfile.TarInfo('../outside.tex')
        member.size = 1
        archive.addfile(member, io.BytesIO(b'x'))
    pdf_inputs = {'sources': archive_path, 'bundle': source_dir / 'outputs/bundle.json'}
    receipt = manuscript_note.run_stage('pdf', pdf_inputs, {'tex': str(tmp_path / 'no-engine')}, tmp_path / 'pdf-work')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_sources_invalid']


def test_p17_claim_source_escapes_tex_specials_and_cannot_inject_input(tmp_path):
    text = r'The literal command \input{outside} and value 0.75% remain text.'
    receipt, workdir, *_ = sources(tmp_path, claim_text=text)
    assert receipt['status'] == 'completed'
    tex = (workdir / 'outputs/sources/main.tex').read_text()
    assert r'\input' not in tex and r'\%' in tex and r'\textbackslash{}input' in tex


def test_p17_nonfinite_claim_quantity_is_invalid(tmp_path):
    receipt, *_ = sources(tmp_path, quantity_value=float('nan'))
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_claim_map_invalid']


def test_p17_free_numeric_prose_outside_claim_marker_refuses(tmp_path):
    receipt, _, *_ = sources(tmp_path, note_text='# Fixture note\n\n[[claim:c1]]\n\nThe score is 0.99.')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_integrity_failed']
    record_path = tmp_path / 'sources/outputs/integrity.json'
    assert 'manuscript:numbers-in-text' in json.loads(record_path.read_text())['failing']


def test_p17_free_number_in_the_title_refuses(tmp_path):
    receipt, workdir, *_ = sources(tmp_path, title='Fixture note 2')
    assert receipt['status'] == 'refused' and receipt['codes'] == ['manuscript_integrity_failed']
    assert 'manuscript:numbers-in-text' in json.loads((workdir / 'outputs/integrity.json').read_text())['failing']


def test_native_exception_receipt_uses_adopted_output_root(tmp_path, monkeypatch):
    output_root = tmp_path / 'outputs'
    output_root.mkdir()
    monkeypatch.chdir(output_root)
    monkeypatch.setitem(manuscript_note.RUNNERS, 'sources', lambda *args: 1 / 0)
    assert manuscript_note.main(['sources', '--root', str(tmp_path)]) == 1
    receipt = json.loads((output_root / 'receipt.json').read_text())
    assert receipt['status'] == 'failed' and receipt['codes'] == ['manuscript_stage_exception']
    assert not (output_root / 'outputs').exists()
