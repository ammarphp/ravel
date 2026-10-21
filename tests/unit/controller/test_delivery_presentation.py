"""Detached notices on actual serialized presentation derivatives (fictional inputs)."""
from io import BytesIO
import hashlib
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from ravel.controller.sink import common, presentation, render
from p07_support import run  # noqa: F401

REFERENCE = 'ravel-delivery-0123456789abcdef'


def pdf():
    writer = PdfWriter()
    for width, rotation in ((300, 0), (400, 90)):
        page = writer.add_blank_page(width=width, height=200)
        stream = DecodedStreamObject()
        stream.set_data(b'0 0 1 rg 0 0 50 50 re f')
        page[NameObject('/Contents')] = writer._add_object(stream)
        if rotation:
            page.rotate(rotation)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def copy(tmp_path, raw, suffix, *, qualified=False, label='accepted'):
    source = tmp_path / ('plot' + suffix)
    source.write_bytes(raw)
    row = {'destination': source.name, 'step': 's1', 'output': source.name, 'artifact': 's1:' + source.name,
           'status': 'accepted', 'sha256': hashlib.sha256(raw).hexdigest(), 'deliverables': ['plot'],
           'qualification': 'Missing independent validation; illustrative only.'}
    staging = tmp_path / 'delivery'
    staging.mkdir()
    rows = render.copy_artifacts(tmp_path, staging, {'declared': [] if qualified else [row]},
                                 SimpleNamespace(labels=[]), label, [], qualified=[row] if qualified else [],
                                 receipt_reference=REFERENCE)
    assert source.read_bytes() == raw
    delivered = next(r for r in rows if r['artifact'] == row['artifact'])
    assert delivered['source_sha256'] == hashlib.sha256(raw).hexdigest()
    assert delivered['receipt_reference'] == REFERENCE
    result = (staging / delivered['path']).read_bytes()
    assert delivered['sha256'] == hashlib.sha256(result).hexdigest()
    return result, delivered, rows


@pytest.mark.parametrize('qualified', [False, True])
def test_pdf_each_page_has_visible_reference_metadata_and_added_band(tmp_path, qualified):
    raw = pdf()
    data, row, _ = copy(tmp_path, raw, '.pdf', qualified=qualified)
    assert row['presentation_derivative'] and row['visible_notice']
    delivered = PdfReader(BytesIO(data))
    assert len(delivered.pages) == 2
    assert delivered.metadata['/Label'] == ('QUALIFIED' if qualified else 'ACCEPTED')
    assert delivered.metadata['/ReceiptReference'] == REFERENCE
    for page in delivered.pages:
        text = ''.join(page.extract_text().split())
        assert REFERENCE in text and 'delivery/RECEIPT.json' in text
        assert ('QUALIFIED' in text) == qualified
        if qualified:
            assert 'Missingindependentvalidation' in text
        assert float(page.mediabox.bottom) < 0
        assert float(page.mediabox.height) > 200


@pytest.mark.parametrize('suffix,format', [('.png', 'PNG'), ('.jpg', 'JPEG'), ('.jpeg', 'JPEG'), ('.tiff', 'TIFF')])
@pytest.mark.parametrize('qualified', [False, True])
def test_raster_added_footer_metadata_and_original_pixels(tmp_path, suffix, format, qualified):
    image = Image.new('RGB', (160, 90), (20, 30, 160))
    output = BytesIO()
    image.save(output, format=format)
    raw = output.getvalue()
    data, row, _ = copy(tmp_path, raw, suffix, qualified=qualified)
    result = Image.open(BytesIO(data))
    assert result.height > image.height
    assert row['visible_notice']
    metadata = result.info if suffix == '.png' else json.loads(result.getexif()[270])
    assert metadata['ReceiptReference'] == REFERENCE
    assert metadata['Label'] == ('QUALIFIED' if qualified else 'ACCEPTED')
    assert ('QUALIFIED' in metadata['Notice']) == qualified
    if format != 'JPEG':
        assert result.convert('RGB').crop((0, 0, 160, 90)).tobytes() == image.tobytes()
    assert result.convert('RGB').crop((0, 90, result.width, result.height)).getextrema() != ((255, 255),) * 3


def test_multiframe_tiff_is_refused_without_silent_frame_loss(tmp_path):
    output = BytesIO()
    image = Image.new('RGB', (50, 50))
    image.save(output, format='TIFF', save_all=True, append_images=[image])
    with pytest.raises(common.SinkRefused, match='multiple image frames.*separate PNG or PDF'):
        copy(tmp_path, output.getvalue(), '.tiff')


def test_svg_footer_is_visible_in_extra_canvas_and_xml_is_inert(tmp_path):
    raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200"><path d="M0 0L100 100"/></svg>'
    data, row, _ = copy(tmp_path, raw, '.svg', qualified=True)
    root = ET.fromstring(data)
    assert float(root.get('viewBox').split()[-1]) > 200
    visible = ''.join(e.text or '' for e in root.iter() if e.tag.endswith('text'))
    assert REFERENCE in visible and 'QUALIFIED' in visible
    assert REFERENCE in next(e.text for e in root.iter() if e.tag.endswith('metadata'))
    assert row['visible_notice']
    for text in (e for e in root.iter() if e.tag.endswith('text')):
        assert float(text.get('y')) > 200


@pytest.mark.parametrize('payload', [b'<script/>', b'<foreignObject/>', b'<image href="https://example.test/x"/>',
                                     b'<path onclick="alert(1)"/>', b'<animate/>', b'<style/>'])
def test_svg_rejects_active_or_external_content(payload):
    with pytest.raises(common.SinkRefused, match='Cannot visibly label .svg'):
        presentation.derivative(b'<svg width="300" height="200">' + payload + b'</svg>', '.svg', 'accepted', REFERENCE)


def test_tex_notice_is_typeset_and_escaped_and_comments_not_selected(tmp_path):
    raw = b'% \\begin{document}\n\\documentclass{article}\n\\begin{document}\nScientific text.\n\\end{document}\n'
    data, row, _ = copy(tmp_path, raw, '.tex', qualified=True)
    assert row['visible_notice'] and row['notice_header']
    text = data.decode()
    start = text.index('\\begin{document}\nScientific') if '\\begin{document}\nScientific' in text else -1
    assert start == -1
    assert '\\begin{document}\n\\par\\begingroup\\small\\noindent' in text
    assert 'QUALIFIED: Missing independent validation' in text
    assert 'Scientific text.' in text
    escaped = presentation.tex(b'\\begin{document}x', ['limit_1 & 20% # $ {x} \\']).decode()
    assert r'limit\_1 \& 20\% \# \$ \{x\} \textbackslash{}' in escaped


@pytest.mark.parametrize('suffix,raw', [('.pdf', b'broken'), ('.png', b'broken'), ('.svg', b'<svg>'),
                                       ('.tex', b'% no document'), ('.gif', b'GIF89a')])
def test_corrupt_or_unsupported_presentation_refuses(suffix, raw):
    with pytest.raises(common.SinkRefused, match='Repair/export'):
        presentation.derivative(raw, suffix, 'qualified', REFERENCE)


def test_missing_dependency_is_typed_with_remedy(monkeypatch):
    def missing(*args):
        raise ImportError('pypdf unavailable')
    monkeypatch.setattr(presentation, '_pdf', missing)
    with pytest.raises(common.SinkRefused, match='install the project figures profile'):
        presentation.derivative(pdf(), '.pdf', 'accepted', REFERENCE)


def test_scientific_binary_stays_identical_with_inventoried_sidecar(tmp_path):
    raw = b'\x00\xffscientific array'
    data, row, rows = copy(tmp_path, raw, '.npy', qualified=True)
    assert data == raw and row['visible_notice'] is False
    sidecar = row['provenance_sidecar']
    assert len(rows) == 1
    notice = json.loads((tmp_path / 'delivery' / sidecar['path']).read_bytes())
    assert notice['label'] == 'QUALIFIED' and notice['receipt_reference'] == REFERENCE
    assert notice['visible_notice'] is False
    assert sidecar['sha256'] == hashlib.sha256((tmp_path / 'delivery' / sidecar['path']).read_bytes()).hexdigest()


def test_delivery_receipt_reference_is_stable_through_rewrite_and_verifies(run):
    run.complete()
    receipt = run.deliver()
    reference = receipt['delivery']['receipt_reference']
    assert reference.startswith('ravel-delivery-')
    assert receipt['delivery']['receipt_path'] == 'delivery/RECEIPT.json'
    assert all(r['receipt_reference'] == reference for r in receipt['delivery']['artifacts'])
    inventory = json.loads(run.delivered('INVENTORY.json').read_text())
    assert inventory['receipt_reference'] == reference
    assert inventory['artifacts'] == receipt['delivery']['artifacts']
    rewritten = render.rewrite_receipt(run.dir, receipt, {'declared': [], 'open': [], 'extras': [], 'excluded': []},
                                       SimpleNamespace(labels=[]))
    assert rewritten['delivery']['receipt_reference'] == reference
    assert json.loads(run.delivered('RECEIPT.json').read_text())['delivery']['receipt_reference'] == reference


def test_full_write_loops_and_fsyncs_parent(tmp_path, monkeypatch):
    real_write = render.os.write
    real_fsync = render.os.fsync
    syncs = []
    monkeypatch.setattr(render.os, 'write', lambda fd, data: real_write(fd, data[:3]))
    monkeypatch.setattr(render.os, 'fsync', lambda fd: (syncs.append(fd), real_fsync(fd))[1])
    path = tmp_path / 'output'
    render._write(path, b'full payload across writes')
    assert path.read_bytes() == b'full payload across writes'
    assert len(syncs) == 2


def test_zero_progress_write_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(render.os, 'write', lambda fd, data: 0)
    with pytest.raises(OSError, match='no progress'):
        render._write(tmp_path / 'output', b'payload')


def test_svg_source_viewport_and_styles_do_not_hide_or_move_notice():
    raw = b'<svg width="300" height="200" opacity="0"><rect width="100%" height="100%"/></svg>'
    data = presentation.derivative(raw, '.svg', 'qualified', REFERENCE, 'Validation pending')
    root = ET.fromstring(data)
    source = root.find('svg')
    assert source.get('height') == '200.0' and source.get('opacity') == '0'
    assert root.get('opacity') is None
    assert root.find("g[@id='ravel-provenance']") is not None


def test_pdf_extract_text_failure_refuses(monkeypatch):
    from pypdf._page import PageObject
    monkeypatch.setattr(PageObject, 'extract_text', lambda *args, **kwargs: '')
    with pytest.raises(common.SinkRefused, match='extract-text verification'):
        presentation.derivative(pdf(), '.pdf', 'accepted', REFERENCE)


def test_high_depth_tiff_requires_explicit_presentation_export():
    image = Image.new('I;16', (50, 50))
    output = BytesIO()
    image.save(output, format='TIFF')
    with pytest.raises(common.SinkRefused, match='high-depth'):
        presentation.derivative(output.getvalue(), '.tiff', 'accepted', REFERENCE)


def test_mutated_data_provenance_sidecar_invalidates_current_receipt(run):
    from ravel.controller import sink
    run.complete()
    receipt = run.deliver()
    artifact = next(row for row in receipt['delivery']['artifacts'] if row.get('provenance_sidecar'))
    sidecar = run.delivered(artifact['provenance_sidecar']['path'])
    sidecar.write_text('{"label": "ACCEPTED WITHOUT LIMITATIONS"}\n')
    observed = sink.receipt(run.store)
    assert observed['verification']['delivery_intact'] is False
    assert observed['accepted'] is False and observed['architecture_complete'] is False
    assert any(artifact['provenance_sidecar']['path'] in reason
               for reason in observed['verification']['problems'])
