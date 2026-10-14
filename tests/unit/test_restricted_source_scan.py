"""Restricted-source guard on a synthetic document and a synthetic deny list only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts' / 'maintenance' / 'restricted_source_scan.py'
spec = importlib.util.spec_from_file_location('restricted_source_scan', SCRIPT)
scan_module = importlib.util.module_from_spec(spec); spec.loader.exec_module(scan_module)

DOCUMENT = b'%PDF-1.4 fabricated restricted brief; invented content for a guard test\n'
DIGEST = hashlib.sha256(DOCUMENT).hexdigest()
FINGERPRINT = 'zq-invented-marker-7731'


def deny_list(tmp_path, **changes):
    owner = tmp_path / 'owner'; owner.mkdir(exist_ok=True)
    doc = {'schema_version': 1, 'kind': 'restricted-sources',
           'documents': [{'label': 'synthetic-brief', 'sha256': DIGEST}], 'fingerprints': [FINGERPRINT]}
    doc.update(changes)
    path = owner / 'restricted-sources.json'; path.write_text(json.dumps(doc))
    return path


def tree(tmp_path, files):
    root = tmp_path / 'stage'
    for name, text in files.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    return root


def run(tmp_path, files, **kwargs):
    root = tree(tmp_path, files)
    deny = scan_module.load_deny_list(deny_list(tmp_path))
    return scan_module.scan([root], deny, root=root, **kwargs)


def test_negative_first_listed_hash_citation_in_a_module_is_found(tmp_path):
    findings = run(tmp_path, {'src/pkg/selection.py': f'# Supplied brief SHA {DIGEST}.\nTABLE = ()\n'})
    kinds = {(f['path'], f['kind']) for f in findings}
    assert ('src/pkg/selection.py', 'listed-hash') in kinds
    assert ('src/pkg/selection.py', 'uncited-document-hash') in kinds
    assert all(f['line'] == 1 for f in findings)


def test_hash_case_fingerprint_and_any_file_type_are_found_without_echoing_them(tmp_path, capsys):
    root = tree(tmp_path, {'docs/notes.md': f'see {DIGEST.upper()}\n',
                           'tests/fixture.json': json.dumps({'x': 'prefix ' + FINGERPRINT.upper()})})
    code = scan_module.main(['--deny-list', str(deny_list(tmp_path)), '--root', str(root), str(root)])
    out = capsys.readouterr().out
    assert code == 1
    assert 'docs/notes.md:1: listed-hash' in out and 'tests/fixture.json:1: fingerprint' in out
    assert DIGEST not in out.lower() and FINGERPRINT not in out.lower()


@pytest.mark.parametrize('text', [
    f"# Specification sha256 {DIGEST[::-1]}\n# https://example.org/public/spec.pdf\n",
    f"PINS = {{'vendor/docs/NOTES.md': '{DIGEST[::-1]}'}}\n",
    f"ARCHIVE_SHA = '{DIGEST[::-1]}'\n",
    f"value = 0x{DIGEST[::-1]}\n"])
def test_software_pins_and_publicly_cited_documents_are_not_uncited_citations(tmp_path, text):
    assert run(tmp_path, {'src/pkg/pins.py': text}) == []


@pytest.mark.parametrize('text', [
    f"INPUTS_PDF_SHA = '{DIGEST[::-1]}'\n",
    f"# The supplied input document fixes these roles.\n# Its sha256:\nX = '{DIGEST[::-1]}'\n"])
def test_unlisted_document_hash_in_src_without_public_url_is_found(tmp_path, text):
    findings = run(tmp_path, {'src/pkg/m.py': text, 'tests/m.py': text})
    assert [(f['path'], f['kind']) for f in findings] == [('src/pkg/m.py', 'uncited-document-hash')]


def test_cli_requires_an_owner_list_outside_the_scanned_tree(tmp_path, monkeypatch, capsys):
    root = tree(tmp_path, {'src/clean.py': 'X = 1\n'})
    monkeypatch.delenv(scan_module.ENV, raising=False)
    assert scan_module.main(['--root', str(root), str(root)]) == 2
    inside = root / 'restricted-sources.json'; inside.write_text(deny_list(tmp_path).read_text())
    assert scan_module.main(['--deny-list', str(inside), '--root', str(root), str(root)]) == 2
    inside.unlink()
    bad = deny_list(tmp_path, documents=[{'label': 'x', 'sha256': 'not-a-hash'}])
    assert scan_module.main(['--deny-list', str(bad), '--root', str(root), str(root)]) == 2
    monkeypatch.setenv(scan_module.ENV, str(deny_list(tmp_path)))
    assert scan_module.main(['--root', str(root), str(root)]) == 0
    assert scan_module.main(['--hash-citations-only', '--root', str(root), str(root)]) == 0
    assert 'restricted_source_scan: 0 finding(s)' in capsys.readouterr().err


def test_repository_src_cites_no_document_hash_without_a_public_url():
    assert scan_module.scan([ROOT / 'src'], None, root=ROOT) == []
