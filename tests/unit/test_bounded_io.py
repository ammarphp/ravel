"""Streaming custody, delivery and archive transport preserve bytes and refusals."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tracemalloc
from types import SimpleNamespace
import zipfile

import pytest

from ravel.controller.confine import commitments, inputs
from ravel.controller.sink import presentation, common, render
from ravel.workflow import acquisition_http as acquisition, discovery_http


def sha(data):
    return hashlib.sha256(data).hexdigest()


def invoke(operation, source, private):
    if operation == 'content':
        return inputs.content(source)
    if operation == 'hash':
        return inputs.hash_copy(source)
    if operation == 'copy':
        return inputs.hash_copy(source, private / '0')
    if operation == 'commit':
        return commitments._hash(source)
    if operation == 'custody-copy':
        from ravel.controller.step.member_manifest import copy_checked
        return copy_checked(source, private / '0')
    return inputs.capture({str(source): sha(b'original')}, private)


@pytest.mark.parametrize('mode', [0o640, 0o755, 0o400])
@pytest.mark.parametrize('data', [b'', b'original', bytes(range(256)) * 9000],
                         ids=['empty', 'small', 'multiple-chunks'])
def test_input_bytes_digests_modes_and_tree_layout(tmp_path, mode, data):
    source = tmp_path / 'tree' / 'nested' / 'input'
    source.parent.mkdir(parents=True)
    source.write_bytes(data)
    source.chmod(mode)
    private = tmp_path / 'private'
    private.mkdir()
    assert inputs.content(source) == (data, mode)
    assert inputs.hash_copy(source) == (sha(data), mode)
    assert commitments._hash(source) == sha(data)
    copies = inputs.capture({str(source): sha(data)}, private, roots=(source.parents[1],))
    assert copies == {source.parents[1]: private / 'tree-0'}
    target = private / 'tree-0/nested/input'
    assert target.read_bytes() == data
    assert stat.S_IMODE(target.stat().st_mode) == mode & 0o555


@pytest.mark.parametrize('operation', ['content', 'hash', 'copy', 'capture', 'commit', 'custody-copy'])
@pytest.mark.parametrize('kind', ['symlink', 'parent-link', 'hardlink', 'directory', 'fifo'])
def test_ordinary_input_refusals(tmp_path, operation, kind):
    source = tmp_path / 'input'
    source.write_bytes(b'original')
    if kind == 'symlink':
        target = tmp_path / 'alias'
        target.symlink_to(source)
        source = target
    elif kind == 'parent-link':
        target = tmp_path / 'alias'
        target.symlink_to(tmp_path, target_is_directory=True)
        source = target / 'input'
    elif kind == 'hardlink':
        os.link(source, tmp_path / 'alias')
    elif kind == 'directory':
        source = tmp_path
    elif kind == 'fifo':
        source = tmp_path / 'pipe'
        os.mkfifo(source)
    private = tmp_path / 'private'
    private.mkdir()
    if kind == 'directory':
        expected = ValueError if operation == 'commit' else IsADirectoryError
        with pytest.raises(expected) as error:
            invoke(operation, source, private)
        prefix = f'operation commitment cannot read {source}: ' if operation == 'commit' else ''
        assert str(error.value).startswith(prefix + '[Errno 21] Is a directory: ')
        assert str(error.value).removeprefix(prefix + '[Errno 21] Is a directory: ').isdigit()
        assert not list(private.iterdir())
        return
    detail = ('traverses a symbolic link' if 'link' in kind and kind != 'hardlink'
              else 'must be an ordinary file without hard links')
    message = f'committed input {detail}: {source}'
    if operation == 'commit':
        message = f'operation commitment cannot read {source}: {message}'
    with pytest.raises(ValueError) as error:
        invoke(operation, source, private)
    assert str(error.value) == message
    assert not list(private.iterdir())


@pytest.mark.parametrize('operation', ['content', 'hash', 'copy', 'capture', 'commit', 'custody-copy'])
@pytest.mark.parametrize('field', ['st_size', 'st_mtime_ns', 'st_ctime_ns'])
def test_input_stat_races_keep_same_message_and_no_partial(tmp_path, monkeypatch, operation, field):
    source = tmp_path / 'input'
    source.write_bytes(b'original')
    private = tmp_path / 'private'
    private.mkdir()
    original = os.fstat
    calls = []
    def changing(fd):
        result = original(fd)
        calls.append(fd)
        if len(calls) == 2:
            fields = {name: getattr(result, name) for name in (
                'st_mode', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
            fields[field] += 1
            return SimpleNamespace(**fields)
        return result
    monkeypatch.setattr(inputs.os, 'fstat', changing)
    message = f'committed input changed while captured: {source}'
    if operation == 'commit':
        message = f'operation commitment cannot read {source}: {message}'
    with pytest.raises(ValueError) as error:
        invoke(operation, source, private)
    assert str(error.value) == message
    assert len(calls) == 2 and calls[0] == calls[1]
    assert not list(private.iterdir())


def test_capture_digest_mismatch_removes_partial_copy(tmp_path):
    source = tmp_path / 'input'
    source.write_bytes(b'changed')
    private = tmp_path / 'private'
    private.mkdir()
    with pytest.raises(ValueError) as error:
        inputs.capture({str(source): sha(b'original')}, private)
    assert str(error.value) == f'committed input changed while captured: {source}'
    assert not list(private.iterdir())


def test_capture_whose_copies_cannot_fit_is_refused_before_copying(tmp_path, monkeypatch):
    source = tmp_path / 'input'
    source.write_bytes(b'original')
    private = tmp_path / 'private'
    private.mkdir()
    seen = []
    monkeypatch.setattr(inputs, '_free_bytes', lambda directory: seen.append(directory) or 7)
    with pytest.raises(ValueError) as error:
        inputs.capture({str(source): sha(b'original')}, private)
    assert str(error.value) == (f'the private copies of the committed inputs need 8 bytes and {private} has 7 bytes '
                                'free; nothing was copied')
    assert seen == [private] and not list(private.iterdir())
    monkeypatch.setattr(inputs, '_free_bytes', lambda directory: 8)
    assert inputs.capture({str(source): sha(b'original')}, private)[source].read_bytes() == b'original'


@pytest.mark.parametrize('symlink', [False, True])
def test_capture_exclusive_target_is_not_overwritten_or_removed(tmp_path, symlink):
    source = tmp_path / 'input'
    source.write_bytes(b'original')
    private = tmp_path / 'private'
    private.mkdir()
    target = private / '0'
    if symlink:
        target.symlink_to(source)
    else:
        target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        inputs.capture({str(source): sha(b'original')}, private)
    assert target.is_symlink() if symlink else target.read_bytes() == b'keep'
    assert source.read_bytes() == b'original'


def test_large_sparse_capture_and_commit_have_bounded_peak(tmp_path, record_property):
    source = tmp_path / 'input'
    size = 512 << 20
    with source.open('wb') as stream:
        stream.truncate(size)
    digest = hashlib.sha256()
    block = bytes(1 << 20)
    for _ in range(size // len(block)):
        digest.update(block)
    expected = digest.hexdigest()
    private = tmp_path / 'private'
    private.mkdir()
    tracemalloc.start()
    try:
        copies = inputs.capture({str(source): expected}, private)
        assert commitments._hash(source) == expected
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    record_property('capture_commit_peak_bytes', peak)
    assert peak < 64 << 20
    target = copies[source]
    assert target.stat().st_size == size
    assert inputs.hash_copy(target)[0] == expected


def artifact(tmp_path, suffix, data):
    source = tmp_path / ('input' + suffix)
    source.write_bytes(data)
    return {'destination': source.name, 'sha256': sha(data), 'status': 'accepted',
            'step': 'step', 'output': source.name, 'artifact': 'item', 'deliverables': ['result']}


@pytest.mark.parametrize('suffix', ['.bin', '.json', *render.TEXT_HEADERS])
@pytest.mark.parametrize('qualified', [False, True])
def test_delivery_matches_whole_file_bytes_and_records(tmp_path, suffix, qualified):
    # Text that takes a notice header is decoded for its presentation; other data keeps arbitrary bytes.
    presented = suffix in render.TEXT_HEADERS or presentation.presented(suffix)
    data = b'document\x00\n' if presented else b'document\x00\xff\n'
    if suffix == '.tex':
        data = b'\\documentclass{article}\n\\begin{document}\ndocument\n\\end{document}\n'  # a complete document
    row = artifact(tmp_path, suffix, data)
    findings = SimpleNamespace(labels=[{'artifact': 'item', 'label': 'qualified note'}])
    staging = tmp_path / 'staging'
    reference_id = 'ravel-delivery-fixture'
    rows = render.copy_artifacts(tmp_path, staging, {'declared': [] if qualified else [row]},
                                 findings, 'accepted', ['notice'], qualified=[row] if qualified else (),
                                 receipt_reference=reference_id)
    relative = f'artifacts/step/{row["output"]}'
    status = 'qualified' if qualified else 'accepted'
    limitation = 'notice; qualified note'
    expected = data
    sidecar = None
    if presented:
        derived = presentation.derivative(data, suffix, status, reference_id, limitation)
        expected = derived if derived is not None else data
        if suffix in render.TEXT_HEADERS:
            notice = render.notice_lines(status, ['notice', 'qualified note'], row['destination'], sha(data), None)
            notice.append(f'Receipt reference: {reference_id}')
            expected = render.notice_header(suffix, notice).encode() + expected
    else:
        sidecar = render._json_bytes({'label': status.upper(), 'qualification': limitation,
                                      'receipt_reference': reference_id, 'receipt_path': 'delivery/RECEIPT.json',
                                      'source': row['destination'], 'source_sha256': sha(data),
                                      # The run recorded no assumptions; the sidecar carries the empty record list.
                                      'assumptions': [],
                                      'visible_notice': False, 'reason': 'scientific data; retained byte-identical'})
        assert (staging / (relative + '.provenance.json')).read_bytes() == sidecar
    assert (staging / relative).read_bytes() == expected
    reference = tmp_path / 'reference'
    render._write(reference, expected)
    assert stat.S_IMODE((staging / relative).stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)
    assert rows == [{'artifact': 'item', 'deliverables': ['result'], 'path': relative,
                     'sha256': sha(expected), 'source': row['destination'], 'source_sha256': sha(data),
                     'size': len(expected), 'notice_header': suffix in render.TEXT_HEADERS,
                     'labels': ['qualified note'], 'presentation_derivative': expected != data,
                     'visible_notice': presented, 'receipt_reference': reference_id,
                     'presentation_label': status.upper(),
                     **({'provenance_sidecar': {'path': relative + '.provenance.json', 'sha256': sha(sidecar),
                                                'size': len(sidecar)}} if sidecar is not None else {}),
                     **({'qualified': True, 'qualification': None, 'route': None} if qualified else {})}]


@pytest.mark.parametrize('suffix', ['.bin', '.md'])
def test_delivery_digest_mismatch_keeps_message_and_no_partial(tmp_path, suffix):
    row = artifact(tmp_path, suffix, b'original')
    (tmp_path / row['destination']).write_bytes(b'changed')
    staging = tmp_path / 'staging'
    with pytest.raises(common.SinkRefused) as error:
        render.copy_artifacts(tmp_path, staging, {'declared': [row]}, SimpleNamespace(labels=[]), 'accepted', [])
    assert str(error.value) == f'{row["destination"]} changed while it was being delivered'
    assert not list(staging.rglob('*.*'))


def test_binary_delivery_does_not_read_whole_file(tmp_path, monkeypatch):
    data = b'x' * (10 << 20)
    row = artifact(tmp_path, '.bin', data)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('whole-file read'))
    tracemalloc.start()
    try:
        rows = render.copy_artifacts(tmp_path, tmp_path / 'staging', {'declared': [row]},
                                     SimpleNamespace(labels=[]), 'accepted', [])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 5 << 20
    assert rows[0]['size'] == len(data) and rows[0]['sha256'] == sha(data)


def archive_bytes(kind, name='nested/input', data=b'original'):
    stream = io.BytesIO()
    if kind == 'zip':
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(name, data)
    else:
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def fake_download(tmp_path, monkeypatch, data, ceiling, *, wrapped=False, fail=False):
    output = tmp_path / 'output'
    baseline = set(tmp_path.iterdir())
    sizes = []
    class Response(io.BytesIO):
        def read(self, size=-1):
            sizes.append(size)
            assert 0 < size <= acquisition.CHUNK
            assert set(tmp_path.iterdir()) - baseline - {output}, 'archive must be on disk while receiving'
            if fail:
                raise OSError('interrupted response')
            return super().read(size)
        read1 = read
    def open_url(*args, **kwargs):
        response = Response(data)
        return acquisition.Response(response, acquisition.current()) if wrapped else response
    monkeypatch.setattr(discovery_http, 'open_url', open_url)
    with acquisition.scope(tmp_path, output, {}, ceiling, 30) as audit:
        result = acquisition.download_archive('https://example.test/archive', output)
    assert sizes
    assert set(tmp_path.iterdir()) <= baseline | {output}
    return result, audit


@pytest.mark.parametrize('kind', ['zip', 'tar'])
@pytest.mark.parametrize('wrapped', [False, True])
def test_archive_streams_to_disk_and_preserves_members(tmp_path, monkeypatch, kind, wrapped):
    data = bytes(range(256)) * 9000
    archive = archive_bytes(kind, data=data)
    result, audit = fake_download(tmp_path, monkeypatch, archive, max(len(archive), len(data)), wrapped=wrapped)
    assert result == ['nested/input']
    assert (tmp_path / 'output/nested/input').read_bytes() == data
    if wrapped:
        assert audit['bytes'] == len(archive)


@pytest.mark.parametrize('wrapped', [False, True])
def test_archive_exact_ceiling_and_overflow_cleanup(tmp_path, monkeypatch, wrapped):
    archive = archive_bytes('zip')
    fake_download(tmp_path, monkeypatch, archive, len(archive), wrapped=wrapped)
    import shutil
    shutil.rmtree(tmp_path / 'output')
    with pytest.raises(ValueError, match='^controller acquisition response byte ceiling exceeded$'):
        fake_download(tmp_path, monkeypatch, archive, len(archive) - 1, wrapped=wrapped)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('kind', ['malformed', 'unsafe', 'expanded', 'interrupted'])
def test_archive_cleans_temporary_file_on_every_failure(tmp_path, monkeypatch, kind):
    if kind == 'malformed':
        data, ceiling, error = b'not an archive', 4096, tarfile.ReadError
    elif kind == 'unsafe':
        data, ceiling, error = archive_bytes('zip', '../escape'), 4096, ValueError
    elif kind == 'expanded':
        data, ceiling, error = archive_bytes('tar', data=b'x' * 8192), 4096, ValueError
    else:
        data, ceiling, error = b'', 4096, OSError
    with pytest.raises(error):
        fake_download(tmp_path, monkeypatch, data, ceiling, fail=kind == 'interrupted')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('operation', ['content', 'hash', 'copy', 'capture', 'commit', 'custody-copy'])
def test_actual_source_mutation_is_refused(tmp_path, monkeypatch, operation):
    source = tmp_path / 'input'
    source.write_bytes(b'original')
    private = tmp_path / 'private'
    private.mkdir()
    original, calls = os.fstat, []
    def mutate(fd):
        calls.append(fd)
        if len(calls) == 2:
            with source.open('ab') as stream:
                stream.write(b'changed')
        return original(fd)
    monkeypatch.setattr(inputs.os, 'fstat', mutate)
    with pytest.raises(ValueError, match='committed input changed while captured:'):
        invoke(operation, source, private)
    assert not list(private.iterdir())


def test_acquisition_through_custody_has_bounded_process_rss_and_exact_retained_disk(tmp_path, record_property):
    """Fresh processes measure real RSS, including acquisition, host custody and input copies."""
    import subprocess
    import sys
    controller = Path(__file__).parent / 'controller'
    script = """
import json, resource, runpy, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
namespace = runpy.run_path(str(Path(sys.argv[1]) / 'test_acquisition_transport.py'))
result = namespace['acquisition_pipeline'](sys.argv[2], int(sys.argv[3]))
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result['peak_rss_bytes'] = peak if sys.platform == 'darwin' else peak * 1024
print(json.dumps(result))
"""
    results = []
    for size in (8 << 20, 64 << 20):
        directory = tmp_path / str(size)
        directory.mkdir()
        child = subprocess.run([sys.executable, '-c', script, str(controller), str(directory), str(size)],
                               check=True, capture_output=True, text=True, timeout=120)
        results.append(json.loads(child.stdout.splitlines()[-1]))
    small, large = results
    for label, result in zip(('small', 'large'), results):
        record_property('acquisition_' + label, json.dumps(result, sort_keys=True))
        assert result['retained_bytes'] == (3 * result['size'] + 3 * result['manifest_bytes']
                                            + result['plan_bytes'])
    # A fixed member population may vary in allocator/import overhead, not by corpus size.
    assert large['peak_rss_bytes'] - small['peak_rss_bytes'] < 24 << 20
    assert large['manifest_bytes'] < 4096


@pytest.mark.parametrize('chunk', [1, 2, 7, 1024])
@pytest.mark.parametrize('raw', [
    b'{"safe":[1,{"truth":2}],"text":"escaped \\"truth\\": is a value"}',
    b'{"tr\\u0075th" \n :0,"x":{"reasoning":"secret"}}',
    b'{"truthful":0,"text":"truth","reasoning_value":"x"}',
    b'{"truth":"x","truth":"second","nested":[{"result_summary":1}]}',
])
def test_streaming_field_screen_preserves_existing_key_refusals(tmp_path, monkeypatch, raw, chunk):
    from ravel.controller.step import member_manifest
    from ravel.workflow import review_projection
    source = tmp_path / 'source.json'; source.write_bytes(raw)
    monkeypatch.setattr(member_manifest, 'CHUNK', chunk)
    forbidden = ('truth', 'reasoning', 'result_summary')
    _, old_fields = review_projection._withhold('source.json', raw, forbidden)
    sha, fields = member_manifest.screen_json_keys(source, forbidden)
    assert fields == sorted(set(old_fields))
    assert sha == hashlib.sha256(raw).hexdigest()


def test_field_screen_memory_is_bounded_for_a_large_string_value(tmp_path):
    from ravel.controller.step import member_manifest
    source = tmp_path / 'source.json'
    with source.open('wb') as stream:
        stream.write(b'{"data":"')
        block = b'x' * (1 << 20)
        for _ in range(12):
            stream.write(block)
        stream.write(b'","tr\\u0075th":true}')
    tracemalloc.start()
    try:
        _, fields = member_manifest.screen_json_keys(source, ('truth',))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert fields == ['truth']
    assert peak < 4 << 20


@pytest.mark.parametrize('target_link', [False, True])
def test_binary_delivery_preserves_exclusive_target(tmp_path, target_link):
    row = artifact(tmp_path, '.bin', b'original')
    staging = tmp_path / 'staging'
    target = staging / 'artifacts/step' / row['output']
    target.parent.mkdir(parents=True)
    if target_link:
        target.symlink_to(tmp_path / row['destination'])
    else:
        target.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        render.copy_artifacts(tmp_path, staging, {'declared': [row]},
                              SimpleNamespace(labels=[]), 'accepted', [])
    assert target.is_symlink() if target_link else target.read_bytes() == b'keep'


@pytest.mark.parametrize('consumer', ['capture', 'sink'])
def test_copy_read_failure_cleans_new_file(tmp_path, monkeypatch, consumer):
    source = tmp_path / 'input.bin'
    source.write_bytes(b'original')
    private = tmp_path / 'private'
    private.mkdir()
    original = inputs.os.fdopen if consumer == 'capture' else Path.open
    class Interrupted(io.BytesIO):
        calls = 0
        def read(self, size=-1):
            self.calls += 1
            if self.calls > 1:
                raise OSError('interrupted input')
            return b'original'
        def fileno(self):
            return self.descriptor.fileno()
        def __exit__(self, *args):
            self.descriptor.close()
            return super().__exit__(*args)
    if consumer == 'capture':
        def fdopen(fd, mode):
            if mode != 'rb':
                return original(fd, mode)
            stream = Interrupted()
            stream.descriptor = original(fd, mode)
            return stream
        monkeypatch.setattr(inputs.os, 'fdopen', fdopen)
        with pytest.raises(OSError, match='^interrupted input$'):
            inputs.capture({str(source): sha(b'original')}, private)
        assert not list(private.iterdir())
    else:
        def open_path(path, mode='r', *args, **kwargs):
            if path != source or mode != 'rb':
                return original(path, mode, *args, **kwargs)
            stream = Interrupted()
            stream.descriptor = original(path, mode, *args, **kwargs)
            return stream
        monkeypatch.setattr(Path, 'open', open_path)
        row = {'destination': source.name, 'sha256': sha(b'original'), 'status': 'accepted',
               'step': 'step', 'output': source.name, 'artifact': 'item', 'deliverables': []}
        with pytest.raises(OSError, match='^interrupted input$'):
            render.copy_artifacts(tmp_path, private, {'declared': [row]},
                                  SimpleNamespace(labels=[]), 'accepted', [])
        assert not list(private.rglob('*.bin'))
