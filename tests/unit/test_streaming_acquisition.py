"""Strict streaming source validation, exact transport, custody RSS and retained disk."""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys

import pytest

from ravel.workflow import hepdata_fetch as fetch, streaming_json

REC = {'recid': 1, 'version': 1, 'data_tables': [{'id': 1, 'name': 'Payload'}]}


class Chunks(io.BytesIO):
    def read(self, size=-1):
        assert 0 < size <= streaming_json.CHUNK
        return super().read(min(size, 3))


def summary(raw):
    with Chunks(raw) as source:
        return streaming_json.summarize(source)


@pytest.mark.parametrize('raw', [b'{"values":[0.12345678901234567890123456789,-2,1e-320]}',
    b'{"description":"efficiency \\u03bc","doi":"a","values":[{"x":"\\uD834\\uDD1E"}]}',
    b'\xef\xbb\xbf{"values":[true,false,null,"\xc3\xa9"]}', b'{"values":[[[]]]}'])
def test_streaming_summary_validates_across_chunk_boundaries(raw):
    result = summary(raw)
    assert result['object'] and result['values_nonempty']


@pytest.mark.parametrize('raw', [b'{"values":[1],"values":[2]}', b'{"a":{"x":1,"\\u0078":2}}',
    b'{"values":[NaN]}', b'{"values":[Infinity]}', b'{"values":[-Infinity]}', b'{"values":[1e999]}',
    b'{"values":[01]}', b'{"values":[1.]}', b'{"values":[1e]}', b'{"values":[+1]}',
    b'{"values":[1,]}', b'{"values":[1]', b'{"values":["\\x"]}', b'{"values":["\\u12"]}',
    b'{"values":["\n"]}', b'{"values":["\xc3"]}', b'{} garbage', b'', b'{"x":1,}', b'[truefalse]'])
def test_invalid_duplicate_nonfinite_and_truncated_payloads_refuse(raw):
    with pytest.raises(streaming_json.JSONRefused):
        summary(raw)


@pytest.mark.parametrize('raw,code', [
    (b'[' * (streaming_json.MAX_DEPTH + 1) + b'0' + b']' * (streaming_json.MAX_DEPTH + 1), 'json_depth_limit'),
    (json.dumps({'description': 'x' * (streaming_json.MAX_METADATA_CHARS + 1)}).encode(), 'json_metadata_limit'),
    (json.dumps({'x' * (streaming_json.MAX_KEY_CHARS + 1): 1}).encode(), 'json_metadata_limit'),
    (json.dumps({str(i): 0 for i in range(streaming_json.MAX_OBJECT_KEYS + 1)}).encode(), 'json_member_limit'),
    (b'1' * (streaming_json.MAX_NUMBER_CHARS + 1), 'json_number_limit'),
])
def test_explicit_validator_limits_are_typed_refusals(raw, code):
    with pytest.raises(streaming_json.JSONRefused) as caught:
        summary(raw)
    assert caught.value.code == code


def _guard_off(monkeypatch):
    monkeypatch.setattr(fetch, '_require', lambda *args, **kwargs: None)


@pytest.mark.parametrize('raw', [b'{"values":[]}', b'{"values":{}}', b'{"values":"nonempty"}',
    b'{"values":[NaN]}', b'{"values":[1]', b'{"values":[1],"values":[2]}'])
def test_online_download_refuses_corruption_and_removes_private_partial(tmp_path, monkeypatch, raw):
    _guard_off(monkeypatch)
    monkeypatch.setattr(fetch, '_open', lambda _: Chunks(raw))
    manifest = {'table_files': []}
    with pytest.raises(RuntimeError, match='partial'):
        fetch.fetch_tables_via_record_data(REC, tmp_path, manifest)
    assert manifest['table_files'] == []
    assert not list(tmp_path.rglob('*.json'))


def test_online_preserves_numeric_bytes_and_private_exclusive_destination(tmp_path, monkeypatch):
    _guard_off(monkeypatch)
    raw = b'{"description":"efficiency","values":[0.123456789012345678901234567890,-2]}\n'
    monkeypatch.setattr(fetch, '_open', lambda _: Chunks(raw))
    manifest = {'table_files': []}
    old = os.umask(0)
    try:
        fetch.fetch_tables_via_record_data(REC, tmp_path, manifest)
    finally:
        os.umask(old)
    row, = manifest['table_files']
    target = tmp_path / row['file']
    assert target.read_bytes() == raw
    assert row['source_bytes_preserved'] is True
    assert row['source_sha256'] == row['output_sha256'] == hashlib.sha256(raw).hexdigest()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(RuntimeError, match='partial'):
        fetch.fetch_tables_via_record_data(REC, tmp_path, {'table_files': []})
    assert target.read_bytes() == raw


def test_catalogue_metadata_read_is_bounded_and_oversize_refused(monkeypatch):
    _guard_off(monkeypatch)
    class Oversize:
        def __enter__(self): self.remaining = fetch.METADATA_BYTES + 1; return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert 0 < size <= streaming_json.CHUNK
            count = min(size, self.remaining)
            self.remaining -= count
            return b' ' * count
    monkeypatch.setattr(fetch, '_open', lambda _: Oversize())
    with pytest.raises(streaming_json.JSONRefused, match='16 MiB'):
        fetch.get_json('https://example.invalid/metadata')


def write_payload(path, size, *, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = b'{"description":"efficiency","values":["' if table else b'{"channels":[{"name":"channel","data":"'
    suffix = b'"]}\n' if table else b'"}]}\n'
    remaining = size - len(prefix) - len(suffix)
    assert remaining >= 0
    with path.open('xb') as target:
        target.write(prefix)
        while remaining:
            count = min(remaining, streaming_json.CHUNK)
            target.write(b'x' * count)
            remaining -= count
        target.write(suffix)


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(streaming_json.CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fixture_tree(root, total, count=16):
    root.mkdir()
    record = {'recid': 1, 'data_tables': [{'id': i + 1, 'name': 'Table ' + str(i + 1)} for i in range(count)],
              'resources': [{'url': 'https://example.invalid/models', 'description': 'pyhf likelihood'}]}
    (root / 'record.json').write_text(json.dumps(record))
    paths = ['models/model-' + str(i) + '.json' for i in range(count)]
    (root / 'likelihoods.json').write_text(json.dumps({'https://example.invalid/models': paths}))
    for i in range(count):
        write_payload(root / ('tables/' + str(i + 1) + '.json'), total // (count * 2), table=True)
        write_payload(root / paths[i], total // (count * 2), table=False)
    return record, paths


@pytest.mark.parametrize('fault', ['duplicate', 'nonfinite', 'truncated', 'empty-values', 'path', 'symlink', 'tamper'])
def test_offline_validates_all_members_before_first_payload_output(tmp_path, monkeypatch, fault):
    _guard_off(monkeypatch)
    root, out = tmp_path / 'fixture', tmp_path / 'out'
    fixture_tree(root, 4096, count=2)
    target = root / 'models/model-1.json'
    if fault == 'duplicate': target.write_bytes(b'{"x":1,"x":2}')
    elif fault == 'nonfinite': target.write_bytes(b'{"x":1e999}')
    elif fault == 'truncated': target.write_bytes(b'{"x":[1]')
    elif fault == 'empty-values': (root / 'tables/2.json').write_bytes(b'{"values":[]}')
    elif fault == 'path':
        (root / 'likelihoods.json').write_text(json.dumps({'https://example.invalid/models': ['models/../../outside']}))
    elif fault == 'symlink':
        target.unlink(); target.symlink_to(root / 'models/model-0.json')
    elif fault == 'tamper':
        original = fetch._verify_pin
        changed = False
        def tamper(pin):
            nonlocal changed
            if not changed:
                changed = True
                target.write_bytes(b'{}')
            return original(pin)
        monkeypatch.setattr(fetch, '_verify_pin', tamper)
    result = fetch.fetch_offline_fixture(root, out, tables=True, download_likelihood=True)
    assert result['status'] == 'ERROR' and result['errors']
    assert not list(out.rglob('*_data.json')) and not list(out.rglob('model-*.json'))


def rss_online(directory, size):
    """Actual source downloader -> actual acquire -> receipt/custody -> worker input copies."""
    controller = Path(__file__).parent / 'controller'
    sys.path.insert(0, str(controller))
    harness = runpy.run_path(str(controller / 'test_acquisition_transport.py'))
    from ravel.controller.routes.analysis import execution
    from ravel.workflow import resource_census
    directory = Path(directory)
    directory.mkdir()
    source = directory.parent / ('source-' + str(size) + '.json')
    write_payload(source, size, table=True)
    original = execution.acquire
    def acquire(step, context, **kwargs):
        def download(args):
            output = Path(args[4]); output.mkdir(parents=True)
            manifest = {'table_files': []}
            fetch.fetch_tables_via_record_data(REC, output, manifest)
            (output / 'hepdata_manifest.json').write_text(json.dumps(manifest))
            return 0
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(resource_census, 'main', download)
            return original(step, context, **kwargs)
    class FileResponse:
        def __enter__(self): self.source = source.open('rb'); return self
        def __exit__(self, *args): self.source.close()
        def read(self, count):
            assert 0 < count <= streaming_json.CHUNK
            return self.source.read(count)
    with pytest.MonkeyPatch.context() as patch:
        _guard_off(patch)
        patch.setattr(execution, 'acquire', acquire)
        patch.setattr(fetch, '_open', lambda _: FileResponse())
        result = harness['acquisition_pipeline'](directory, size)
    source.unlink()
    return result


def rss_offline(directory, size):
    directory = Path(directory); directory.mkdir()
    root, output = directory / 'fixture', directory / 'output'
    fixture_tree(root, size)
    with pytest.MonkeyPatch.context() as patch:
        _guard_off(patch)
        patch.setattr(fetch, '_open', lambda *args, **kwargs: pytest.fail('offline transport used'))
        old = os.umask(0)
        try:
            manifest = fetch.fetch_offline_fixture(root, output, tables=True, download_likelihood=True)
        finally:
            os.umask(old)
    assert manifest['status'] == 'OK', manifest['errors']
    assert len(manifest['fixture_files']) == 34 and len(manifest['table_files']) == 16
    for row in manifest['table_files']:
        table_id = int(row['name'].split()[-1])
        original = root / 'tables' / (str(table_id) + '.json')
        assert digest_file(original) == digest_file(output / row['file']) == row['source_sha256']
        assert row['source_bytes_preserved']
    for original in (root / 'models').glob('*.json'):
        assert digest_file(original) == digest_file(output / 'models' / original.name)
    payload_bytes = sum(path.stat().st_size for path in (output / 'tables').glob('*'))
    payload_bytes += sum(path.stat().st_size for path in (output / 'models').glob('*'))
    assert payload_bytes == size
    for path in output.rglob('*'):
        if path.is_file():
            assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    retained = sum(path.stat().st_size for path in directory.rglob('*') if path.is_file())
    metadata = sum((root / name).stat().st_size for name in ('record.json', 'likelihoods.json'))
    assert retained == 2 * size + metadata + (output / 'hepdata_manifest.json').stat().st_size
    return {'size': size, 'retained_bytes': retained, 'payload_copies': 2, 'members': 32}


@pytest.mark.parametrize('operation', ['rss_online', 'rss_offline'])
def test_actual_fetch_payloads_and_many_members_have_bounded_rss_and_exact_disk(tmp_path, record_property, operation):
    script = """
import json, resource, runpy, sys
namespace = runpy.run_path(sys.argv[1])
result = namespace[sys.argv[2]](sys.argv[3], int(sys.argv[4]))
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result['peak_rss_bytes'] = peak if sys.platform == 'darwin' else peak * 1024
print(json.dumps(result))
"""
    results = []
    for size in (8 << 20, 64 << 20):
        destination = tmp_path / str(size)
        child = subprocess.run([sys.executable, '-c', script, str(Path(__file__).resolve()), operation,
                                str(destination), str(size)], check=True, capture_output=True, text=True, timeout=180)
        results.append(json.loads(child.stdout.splitlines()[-1]))
    record_property(operation, json.dumps(results, sort_keys=True))
    assert results[1]['peak_rss_bytes'] - results[0]['peak_rss_bytes'] < 24 << 20


def test_offline_preserves_original_numeric_lexemes_and_model_member_list(tmp_path, monkeypatch):
    _guard_off(monkeypatch)
    root, out = tmp_path / 'fixture', tmp_path / 'output'
    fixture_tree(root, 2048, count=1)
    table = b'{"description":"efficiency","values":[0.123456789012345678901234567890,-2]}\n'
    model = b'{"signed_terms":[-2,3],"value":0.123456789012345678901234567890}\n'
    (root / 'tables/1.json').write_bytes(table)
    (root / 'models/model-0.json').write_bytes(model)
    result = fetch.fetch_offline_fixture(root, out, tables=True, download_likelihood=True)
    assert result['status'] == 'OK', result['errors']
    assert (out / result['table_files'][0]['file']).read_bytes() == table
    assert (out / 'models/model-0.json').read_bytes() == model
    assert {row['file'] for row in result['fixture_files']} == {
        'record.json', 'tables/1.json', 'likelihoods.json', 'models/model-0.json'}
