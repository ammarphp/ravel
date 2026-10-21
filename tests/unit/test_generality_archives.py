"""Synthetic archive coverage; no external source material is used."""
import gzip
import io
import json
import stat
import tarfile
import zipfile

import pytest

from ravel.validation import check_generality as cg

TERM = 'Cobalt' + ' Meadow'
DENY = cg.Denylist([cg.entry_for(TERM, 'external')])


def zipped(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in members:
            archive.writestr(name, value)
    return out.getvalue()


def tarred(value, mode='w', kind=None):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode=mode) as archive:
        info = tarfile.TarInfo('note.txt')
        info.size = len(value)
        if kind is not None:
            info.type = kind
            info.linkname = 'elsewhere'
            info.size = 0
        archive.addfile(info, io.BytesIO(value))
    return out.getvalue()


def scan(name, data):
    return cg.scan_bytes(name, data, DENY, citations={})


@pytest.mark.parametrize('rule', [
    'unscanned-large-file', 'unscanned-archive-unsupported', 'unscanned-archive-depth-limit',
    'unscanned-archive-byte-limit', 'unscanned-archive-member-limit', 'unscanned-archive-malformed',
    'unscanned-archive-truncated', 'unscanned-archive-special-member', 'unscanned-archive-encrypted',
    'unscanned-future-reader-gap',
])
def test_inspection_gaps_retain_incomplete_status_under_exact_exemptions(rule):
    hits = [cg.Hit('pack.zip!member', 0, rule)]
    kept, stale = cg.apply_allowlist(hits, {'pack.zip': [rule]}, {'pack.zip'})
    assert kept == hits and stale
    assert cg.summary(kept)['complete'] is False
    assert cg.summary(kept)['clean'] is False


def test_exact_exemption_for_unreadable_archive_exits_incomplete(tmp_path, capsys):
    archive = tmp_path / 'pack.zip'
    archive.write_bytes(b'broken')
    hits = scan(archive.name, archive.read_bytes())
    rules = sorted({h.rule for h in hits if h.rule.startswith('unscanned-')})
    assert rules
    allow = tmp_path / 'allow.json'
    allow.write_text(json.dumps({'allow': {archive.name: rules}}))
    assert cg.main(['--root', str(tmp_path), '--allowlist', str(allow), '--json', str(archive)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['complete'] is False and report['clean'] is False


def test_complete_clean_and_complete_flagged_scans_are_distinct():
    assert cg.summary([])['complete'] is True and cg.summary([])['clean'] is True
    report = cg.summary([cg.Hit('notes.txt', 1, 'denylist:external')])
    assert report['complete'] is True and report['clean'] is False


@pytest.mark.parametrize('mode,suffix', [('w', '.tar'), ('w:gz', '.tar.gz'),
                                          ('w:bz2', '.tar.bz2'), ('w:xz', '.tar.xz')])
def test_tar_members_are_scanned(mode, suffix):
    assert any(h.rule == 'denylist:external' and '!note.txt' in h.path
               for h in scan('bundle' + suffix, tarred(TERM.encode(), mode)))


def test_nested_archive_and_magic_detection():
    data = zipped([('inner.bin', tarred(TERM.encode()))])
    assert any(h.rule == 'denylist:external' and '!inner.bin!note.txt' in h.path
               for h in scan('bundle.bin', data))


@pytest.mark.parametrize('name,data', [('bad.zip', b'broken'), ('bad.tar', b'broken'),
                                      ('bad.gz', b'broken'), ('bad.rar', b'broken')])
def test_unreadable_archives_fail_closed(name, data):
    assert any(h.rule.startswith('unscanned-archive-') for h in scan(name, data))


def test_cumulative_byte_limit(monkeypatch):
    monkeypatch.setattr(cg, 'MAX_ARCHIVE_BYTES', 12)
    hits = scan('bundle.zip', zipped([('a', b'generic text'), ('b', b'generic text')]))
    assert any(h.rule == 'unscanned-archive-byte-limit' for h in hits)


def test_member_limit(monkeypatch):
    monkeypatch.setattr(cg, 'MAX_ARCHIVE_MEMBERS', 1)
    hits = scan('bundle.zip', zipped([('a', b'ok'), ('b', b'ok')]))
    assert any(h.rule == 'unscanned-archive-member-limit' for h in hits)


def test_depth_limit(monkeypatch):
    monkeypatch.setattr(cg, 'MAX_ARCHIVE_DEPTH', 1)
    hits = scan('bundle.zip', zipped([('inner.zip', zipped([('a', b'ok')]))]))
    assert any(h.rule == 'unscanned-archive-depth-limit' for h in hits)


@pytest.mark.parametrize('kind', [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
                                   tarfile.CHRTYPE, tarfile.BLKTYPE])
def test_tar_special_members_fail_closed(kind):
    assert any(h.rule == 'unscanned-archive-special-member'
               for h in scan('bundle.tar', tarred(b'', kind=kind)))


def test_zip_symlink_fails_closed():
    info = zipfile.ZipInfo('link')
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    assert any(h.rule == 'unscanned-archive-special-member'
               for h in scan('bundle.zip', zipped([(info, b'target')])) )


def test_gzip_expansion_is_bounded(monkeypatch):
    monkeypatch.setattr(cg, 'MAX_ARCHIVE_BYTES', 8)
    assert any(h.rule == 'unscanned-archive-byte-limit'
               for h in scan('bundle.gz', gzip.compress(b'x' * 100)))


def test_clean_archives_remain_clean():
    assert scan('bundle.zip', zipped([('note.txt', b'plain generic text')])) == []
    assert scan('bundle.tar', tarred(b'plain generic text')) == []


@pytest.mark.parametrize('field,value,rule', [(8, 99, 'unscanned-archive-unsupported'),
                                             (6, 1, 'unscanned-archive-encrypted')])
def test_zip_unreadable_member_encodings(field, value, rule):
    import struct
    data = bytearray(zipped([('note.txt', b'generic text')]))
    struct.pack_into('<H', data, field, value)
    central = data.index(b'PK\x01\x02')
    struct.pack_into('<H', data, central + field + 2, value)
    assert any(h.rule == rule for h in scan('bundle.zip', bytes(data)))


@pytest.mark.parametrize('data', [tarred(b'generic text')[:1024],
                                   tarred(b'generic text')[:600],
                                   tarred(b'generic text')[:1024] + b'x' * 1024])
def test_tar_truncation_or_unparsed_trailing_data_fail_closed(data):
    assert any(h.rule.startswith('unscanned-archive-') for h in scan('bundle.tar', data))


def test_names_and_original_findings_survive_archive_failure():
    data = zipped([(TERM + '.txt', b'generic text'), ('broken.zip', b'broken')])
    hits = scan('bundle.zip', data)
    assert any(h.rule == 'denylist:external' for h in hits)
    assert any(h.rule == 'unscanned-archive-malformed' for h in hits)


def test_malformed_archive_preserves_plain_content_findings():
    hits = scan('broken.zip', TERM.encode())
    assert any(h.rule == 'denylist:external' for h in hits)
    assert any(h.rule == 'unscanned-archive-malformed' for h in hits)


def test_legacy_tar_and_prefixed_zip_are_detected_by_content():
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo('note.txt')
        info.size = len(TERM.encode())
        archive.addfile(info, io.BytesIO(TERM.encode()))
    legacy = bytearray(out.getvalue())
    legacy[257:265] = b'\0' * 8
    legacy[148:156] = b' ' * 8
    legacy[148:156] = (f'{sum(legacy[:512]):06o}\0 ').encode()
    for data in (bytes(legacy), b'generic executable prefix' + zipped([('note.txt', TERM)])):
        assert any(h.rule == 'denylist:external' and '!note.txt' in h.path
                   for h in scan('bundle.bin', data))


@pytest.mark.parametrize('nested', [False, True])
def test_archive_comments_are_scanned_at_every_depth(nested):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.comment = TERM.encode()
        archive.writestr('note.txt', 'generic text')
    data = out.getvalue()
    if nested:
        data = zipped([('inner.zip', data)])
    assert any(h.rule == 'denylist:external' for h in scan('bundle.zip', data))


def gzip_metadata(flag, value):
    data = bytearray(gzip.compress(b'generic text', mtime=0))
    data[3] = flag
    extra = (len(value).to_bytes(2, 'little') + value) if flag == 4 else value + b'\0'
    return bytes(data[:10]) + extra + bytes(data[10:])


@pytest.mark.parametrize('flag', [4, 8, 16])
@pytest.mark.parametrize('concatenated', [False, True])
def test_all_gzip_optional_metadata_is_scanned(flag, concatenated):
    data = gzip_metadata(flag, TERM.encode())
    if concatenated:
        data = gzip.compress(b'prefix', mtime=0) + data
    assert any(h.rule == 'denylist:external' and h.path.endswith('!@metadata')
               for h in scan('bundle.gz', data))


def test_gzip_unknown_header_flags_fail_closed():
    data = bytearray(gzip.compress(b'generic text'))
    data[3] |= 0x80
    assert any(h.rule == 'unscanned-archive-unsupported' for h in scan('bundle.gz', bytes(data)))


@pytest.mark.parametrize('field', ['uname', 'gname', 'linkname'])
def test_tar_text_header_fields_are_scanned(field):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as archive:
        info = tarfile.TarInfo('note.txt')
        setattr(info, field, TERM)
        archive.addfile(info, io.BytesIO(b''))
    assert any(h.rule == 'denylist:external' for h in scan('bundle.tar', out.getvalue()))


@pytest.mark.parametrize('prefix,suffix', [(TERM.encode(), b''), (b'', TERM.encode())])
def test_zip_prefix_and_trailing_bytes_are_scanned(prefix, suffix):
    data = prefix + zipped([('note.txt', b'generic text')]) + suffix
    assert any(h.rule == 'denylist:external' for h in scan('bundle.zip', data))


@pytest.mark.parametrize('kind', ['bz2', 'xz'])
def test_compressed_stream_trailing_bytes_fail_closed(kind):
    import bz2
    import lzma
    compressor = bz2.compress if kind == 'bz2' else lzma.compress
    data = compressor(b'generic text') + b'invalid trailing text'
    assert any(h.rule.startswith('unscanned-archive-') for h in scan('bundle.' + kind, data))
