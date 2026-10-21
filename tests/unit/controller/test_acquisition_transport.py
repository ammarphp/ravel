"""Byte transport evidence, without interpreting scientific quantities."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from pathlib import Path
from threading import Thread
import urllib.request

import pytest

from ravel.workflow import acquisition_http, discovery_http, hepdata_fetch, resource_census, restriction_guard
from ravel.controller.routes.analysis import common, execution

RAW = b'{"values":[{"value":0.123456789012345678901234567890}],"basis":["signed"],"units":"pb","covariance":[[1,-0.00000000000000000000000001]],"signed_terms":[-2,3]}\n'
REC = {'recid': 1, 'version': 1, 'data_tables': [{'id': 2, 'name': 'Table 1'}]}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_default_http_table_transport_preserves_complete_response_bytes(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(RAW)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    monkeypatch.setattr(restriction_guard, 'require', lambda *a, **k: None)
    monkeypatch.setattr(hepdata_fetch, '_require', lambda *a, **k: None)
    original_resolve = socket.getaddrinfo
    def resolve(host, port, *args, **kwargs):
        if host == '127.0.0.1':  # the existing local byte-transport server only
            return original_resolve(host, port, *args, **kwargs)
        assert host == 'www.hepdata.net'
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '',
                 ('8.8.8.8', port))]
    monkeypatch.setattr(acquisition_http.socket, 'getaddrinfo', resolve)
    def transport(request, **kwargs):
        return urllib.request.urlopen('http://127.0.0.1:%s/table' % server.server_port,
                                      timeout=kwargs['timeout'])
    monkeypatch.setattr(discovery_http, '_urlopen', transport)
    manifest = {'table_files': []}
    try:
        with acquisition_http.scope(tmp_path, tmp_path, {'classes': ['hepdata']}, 4096, 10) as audit:
            hepdata_fetch.fetch_tables_via_record_data(REC, str(tmp_path), manifest)
        row, = manifest['table_files']
        assert (tmp_path / row['file']).read_bytes() == RAW
        assert row['source_bytes_preserved'] is True
        assert row['source_sha256'] == row['output_sha256'] == sha(RAW)
        assert audit['bytes'] == len(RAW)
        assert hepdata_fetch.get_json('https://www.hepdata.net/record/test') == json.loads(RAW)
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_custom_json_reader_preserves_whole_object_without_claiming_response_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(hepdata_fetch, '_require', lambda *a, **k: None)
    doc = json.loads(RAW)
    manifest = {'table_files': []}
    hepdata_fetch.fetch_tables_via_record_data(REC, str(tmp_path), manifest,
                                              get_json_fn=lambda _: doc)
    row, = manifest['table_files']
    output = (tmp_path / row['file']).read_bytes()
    assert json.loads(output) == doc
    assert row['source_bytes_preserved'] is False and row['source_sha256'] is None
    assert row['output_sha256'] == sha(output)


@pytest.fixture
def transfer(tmp_path, monkeypatch):
    monkeypatch.setattr(restriction_guard, 'require', lambda *a, **k: None)
    @contextmanager
    def scope(*args):
        yield {}
    monkeypatch.setattr(acquisition_http, 'scope', scope)
    def run(step_id='acquire.data', declared=None, legacy=None):
        output = tmp_path / 'outputs'
        def fetch(args):
            if step_id == 'acquire.data':
                folder = Path(args[4]); folder.mkdir(parents=True, exist_ok=True)
                manifest = {'table_files': [{'file': 'table.json'}]}
                if declared is not None:
                    manifest['acquired_member_manifest'] = declared
                if legacy is not None:
                    manifest['acquired_members'] = legacy
                (folder / 'hepdata_manifest.json').write_text(json.dumps(manifest))
                (folder / 'table.json').write_bytes(RAW)
            else:
                Path(args[3]).write_bytes(b'{"metadata":"uninterpreted"}')
            return 0
        monkeypatch.setattr(resource_census, 'main', fetch)
        args = (['--fetch-published-data', '--inspire', 'ins1', '--out', 'hepdata',
                 '--download-likelihood', '--tables'] if step_id == 'acquire.data'
                else ['--reading', 'reading.json', '--controller-output', 'census.json'])
        relative = 'hepdata/hepdata_manifest.json' if step_id == 'acquire.data' else 'census.json'
        step = {'id': step_id, 'kind': 'acquire', 'operation': 'acquire-published',
                'parameters': {'task': {'max_bytes': 100000},
                               'launch': {'argv': ['python', '-m', 'ravel.workflow.resource_census'] + args}},
                'outputs': [{'path': 'outputs/' + relative}], 'inputs': []}
        result = execution.acquire(step, {'run_dir': str(tmp_path)}, output_root=output, inputs=[])
        return output, result
    return run


@pytest.mark.parametrize('step_id,representation', [('inputs.census', 'metadata'), ('acquire.data', 'file_bytes')])
def test_receipt_inventory_names_actual_uninterpreted_output_bytes(transfer, step_id, representation):
    output, result = transfer(step_id)
    members = [{'path': p.relative_to(output).as_posix(), 'sha256': sha(p.read_bytes())}
               for p in sorted(output.rglob('*')) if p.is_file()]
    assert result['quantity_transport'] == {
        'kind': 'uninterpreted_source_transfer', 'representation': representation,
        'members': members, 'inventory_sha256': common.digest(members), 'source_fields_transformed': False,
        'source_quantities': ['text'] if representation == 'metadata' else ['values']}
    if step_id == 'acquire.data':
        manifest = json.loads((output / 'hepdata/hepdata_manifest.json').read_bytes())
        member, = manifest['acquired_member_manifest']['members']
        assert (output / 'hepdata' / member['blob']).read_bytes() == RAW
        assert manifest['table_files'] == [{'file': 'table.json'}]
        assert (output / 'hepdata/table.json').read_bytes() == RAW
        inventory = [{'path': 'table.json', 'sha256': sha(RAW), 'bytes': len(RAW),
                      'blob': 'table.json'}]
        assert result['member_inventory'] == inventory
        assert result['member_inventory_sha256'] == common.digest(inventory)


def declared_member():
    return {'path': 'table.json', 'sha256': sha(RAW), 'bytes': len(RAW), 'blob': 'table.json'}


@pytest.mark.parametrize('fault', ['blob', 'digest', 'changed-bytes', 'path', 'missing', 'duplicate', 'size', 'version'])
def test_preexisting_member_manifest_must_match_exact_local_inventory(transfer, fault):
    member = declared_member()
    if fault == 'blob': member['blob'] = '../outside'
    elif fault == 'digest': member['sha256'] = '0' * 64
    elif fault == 'changed-bytes':
        member.update(sha256=sha(b'{}'), bytes=2, blob='table.json')
    elif fault == 'path': member['path'] = '../table.json'
    elif fault == 'size': member['bytes'] += 1
    members = [] if fault == 'missing' else [member, member] if fault == 'duplicate' else [member]
    manifest = {'schema_version': 2 if fault == 'version' else 1, 'members': members}
    with pytest.raises(ValueError, match='member'):
        transfer(declared=manifest)


def test_valid_preexisting_manifest_references_roundtrip(transfer):
    output, result = transfer(declared={'schema_version': 1, 'members': [declared_member()]})
    assert result['exit_status'] == 0
    assert (output / 'hepdata' / declared_member()['blob']).read_bytes() == RAW


@pytest.mark.parametrize('legacy', [[], [{'path': 'table.json', 'content_base64': '!!!', 'sha256': sha(RAW)}]])
def test_legacy_embedding_is_refused_without_decode(transfer, legacy):
    with pytest.raises(ValueError, match='legacy acquisition embedding'):
        transfer(legacy=legacy)


def test_changed_stream_hash_cannot_produce_completed_receipt(transfer, monkeypatch):
    from ravel.controller.confine import inputs
    from ravel.controller.step import member_manifest
    original = inputs.hash_copy
    count = 0
    def changed(path, target=None):
        nonlocal count
        count += 1
        result = original(path, target)
        if Path(path).name == 'table.json' and count > 1:
            return '0' * 64, result[1]
        return result
    monkeypatch.setattr(inputs, 'hash_copy', changed)
    monkeypatch.setattr(member_manifest, 'hash_copy', changed)
    with pytest.raises(ValueError, match='member bytes or digest changed'):
        transfer()


def acquisition_pipeline(directory, size, *, fault=None):
    """Inert source, real host receipt/adoption/acceptance/input verification and copies."""
    from ravel.controller.step import custody, graph, host_operations
    from ravel.controller.step.services import digest
    from test_p04_support import FakeStore
    directory = Path(directory)
    run = directory / 'run'
    run.mkdir()
    output = run / 'attempts/acquire/outputs'
    member_path = 'hepdata/hepdata_manifest.json'
    plan_path = 'outputs/' + member_path
    step = {'id': 'acquire.data', 'kind': 'acquire', 'operation': 'acquire-published', 'role': None,
            'depends_on': [], 'inputs': [], 'outputs': [{'path': plan_path, 'kind': 'artifact', 'required': True}],
            'parameters': {'task': {'max_bytes': size + (1 << 20)}, 'launch': {'argv': ['python', '-m',
                'ravel.workflow.resource_census', '--fetch-published-data', '--inspire', 'ins1', '--out',
                'hepdata', '--download-likelihood', '--tables']}}}
    @contextmanager
    def scope(*args):
        yield {}
    def fetch(args):
        root = Path(args[4]); root.mkdir(parents=True)
        (root / 'hepdata_manifest.json').write_text(json.dumps({'table_files': [{'file': 'payload.bin'}]}))
        block = b'x' * (1 << 20)
        with (root / 'payload.bin').open('xb') as stream:
            remaining = size
            while remaining:
                count = min(len(block), remaining)
                stream.write(block[:count]); remaining -= count
        return 0
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(resource_census, 'main', fetch)
        patch.setattr(acquisition_http, 'scope', scope)
        patch.setattr(restriction_guard, 'require', lambda *args, **kwargs: None)
        acquired = execution.acquire(step, {'run_dir': str(run)}, output_root=output, inputs=[])
    store = FakeStore(directory / 'store', run_dir=run)
    plan_bytes = json.dumps({'steps': [step]}).encode()
    store.append('plan', {'blob': store.put_blob(plan_bytes)})
    decision = host_operations.admit(store, step, 1)
    launch_sha = digest(step)
    started = store.append('step-launch', {'phase': 'started', 'step_id': step['id'], 'attempt': 1,
        'host_decision': decision, 'launch_sha256': launch_sha})
    inventory = graph._inventory(output)
    launch = {'journal_id': started, 'launch_sha256': launch_sha, 'output_root': str(output),
              'inventory': inventory, 'exit_status': 0, 'backend': 'controller-acquisition'}
    store.append('step-launch', {'phase': 'finished', 'step_id': step['id'], 'attempt': 1, 'started': started,
        'inventory': inventory, 'exit_status': 0, 'timed_out': False, 'backend': 'controller-acquisition',
        'acquisition': acquired})
    if fault == 'inventory':
        (output / 'extra').write_bytes(b'uncredited')
    elif fault == 'symlink':
        blob = output / 'hepdata/payload.bin'
        blob.rename(blob.with_suffix('.source')); blob.symlink_to(blob.with_suffix('.source'))
    adopted = custody.launch_adoption(store, run_dir=run, step=step, attempt=1, card=None, launch=launch,
        outputs=[{'plan_path': plan_path, 'kind': 'artifact', 'required': True}], inputs_custody=[])
    accepted = custody.accept(store, adopted, 'accepted')
    record, = accepted
    if fault in ('digest', 'size', 'missing', 'extra'):
        blob = run / record['attachments'][0]['destination']
        if fault == 'digest': blob.write_bytes(b'y' * size)
        elif fault == 'size':
            with blob.open('ab') as stream: stream.write(b'y')
        elif fault == 'missing': blob.unlink()
        else: (blob.parent / ('0' * 64)).write_bytes(b'extra')
    elif fault in ('undeclared-attachment', 'missing-attachments', 'missing-producer'):
        if fault in ('missing-attachments', 'missing-producer'):
            record.pop('attachments')
            if fault == 'missing-producer':
                record.pop('producer')
        else:
            record['attachments'].append(dict(record['attachments'][0], path='extra'))
        store.append('custody', {k: v for k, v in record.items() if k != 'record_id'})
    consumer = {'id': 'consume', 'depends_on': [step['id']],
                'inputs': [{'artifact': record['artifact'], 'sha256': record['sha256']}]}
    errors, found, _ = custody.input_errors(store, consumer, run)
    if fault:
        assert errors and not found
        return
    assert not errors and len(found) == 1
    pins = graph._copy_inputs(run, Path('packet'), [{'artifact': record['artifact'], 'sha256': record['sha256'],
         'kind': 'artifact', 'custody': found[0]}], store=store)
    assert len(pins) == 2
    manifest_size = (output / member_path).stat().st_size
    retained = sum(path.stat().st_size for path in directory.rglob('*') if path.is_file())
    assert retained == 3 * size + 3 * manifest_size + len(plan_bytes)
    assert sum(path.is_file() for path in run.rglob('*')) == 6
    return {'size': size, 'retained_bytes': retained, 'manifest_bytes': manifest_size,
            'plan_bytes': len(plan_bytes)}


@pytest.mark.parametrize('fault', ['digest', 'size', 'missing', 'extra', 'undeclared-attachment', 'missing-attachments', 'missing-producer'])
def test_real_adoption_rechecks_exact_member_attachments(tmp_path, fault):
    acquisition_pipeline(tmp_path, 4096, fault=fault)


@pytest.mark.parametrize('fault', ['inventory', 'symlink'])
def test_real_adoption_refuses_inventory_changes(tmp_path, fault):
    from ravel.controller.step.services import StepHold
    with pytest.raises((StepHold, ValueError)):
        acquisition_pipeline(tmp_path, 4096, fault=fault)


def test_copy_capacity_refuses_before_adoption_creates_any_output(tmp_path, monkeypatch):
    import shutil
    from types import SimpleNamespace
    from ravel.controller.step.services import StepHold
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    with pytest.raises(StepHold) as held:
        acquisition_pipeline(tmp_path, 4096)
    assert held.value.reason == 'copy_storage_refused'
    assert 'filesystem cannot cover' in held.value.would_make_possible
    assert not (tmp_path / 'run/steps').exists()


def test_oversized_legacy_metadata_is_refused_before_json_decode(tmp_path, monkeypatch):
    from ravel.controller.step import member_manifest
    source = tmp_path / 'manifest.json'
    with source.open('wb') as stream:
        stream.truncate(member_manifest.MAX_MANIFEST_BYTES + 1)
    def forbidden(*args, **kwargs):
        raise AssertionError('oversized metadata reached JSON decoding')
    monkeypatch.setattr(member_manifest.json, 'loads', forbidden)
    with pytest.raises(ValueError, match='metadata exceeds'):
        member_manifest.load(source)


def test_equal_digests_cannot_declare_different_sizes():
    from ravel.controller.step import member_manifest
    one = declared_member()
    other = {**one, 'path': 'other', 'blob': 'other', 'bytes': one['bytes'] + 1}
    with pytest.raises(ValueError, match='one byte size'):
        member_manifest.rows({member_manifest.KEY: {'schema_version': 1, 'members': [one, other]}})


def test_authored_manifest_cannot_authorize_nested_member_inputs(tmp_path):
    from ravel.controller.step import custody, graph, member_manifest
    from test_p04_support import FakeStore
    run = tmp_path / 'run'; run.mkdir()
    output = tmp_path / 'outputs'; output.mkdir()
    payload = output / 'table.json'; payload.write_bytes(RAW)
    manifest = output / 'manifest.json'
    manifest.write_text(json.dumps({member_manifest.KEY: {'schema_version': 1, 'members': [declared_member()]}}))
    inventory = graph._inventory(output)
    step = {'id': 'authored', 'operation': None, 'kind': 'operate', 'parameters': {},
            'outputs': [{'path': 'outputs/manifest.json'}]}
    store = FakeStore(tmp_path / 'store', run_dir=run)
    adopted = custody.launch_adoption(store, run_dir=run, step=step, attempt=1, card=None,
        launch={'output_root': str(output), 'inventory': inventory, 'backend': 'inert', 'exit_status': 0},
        outputs=[{'plan_path': 'outputs/manifest.json', 'required': True, 'kind': 'artifact'}], inputs_custody=[])
    record, = custody.accept(store, adopted, 'accepted')
    assert 'attachments' not in record
    pins = graph._copy_inputs(run, Path('packet'), [{'artifact': record['artifact'], 'sha256': record['sha256'],
        'kind': 'artifact', 'custody': record}], store=store)
    assert len(pins) == 1
    assert not list((run / 'packet').rglob('table.json'))


def test_member_population_is_bounded_before_index_serialization(tmp_path, monkeypatch):
    from ravel.controller.step import member_manifest
    monkeypatch.setattr(member_manifest, 'MAX_MEMBER_ENTRIES', 2)
    for name in ('a', 'b', 'c'):
        (tmp_path / name).touch()
    with pytest.raises(ValueError, match='entry ceiling'):
        member_manifest.member_files(tmp_path)


def test_governed_copy_cannot_remove_its_authority_record(tmp_path, monkeypatch):
    from ravel.controller.confine import runs
    from ravel.controller.step import member_manifest
    from ravel.controller.step.services import StepHold
    from test_p04_support import FakeStore
    root = tmp_path / 'run'; root.mkdir()
    source = root / 'source'; source.write_bytes(RAW)
    target = root / 'copy'
    store = FakeStore(tmp_path / 'store', run_id='bound-run', run_dir=root)
    monkeypatch.setattr(runs, 'owner_of', lambda _: ('bound-run', root))
    # The actual authority reader must refuse the missing initialized mode/key;
    # the ownership marker cannot be downgraded to an unowned library copy.
    with pytest.raises((ValueError, StepHold)):
        member_manifest.admit_copies(root, [(source, target, sha(RAW))], store=store)
    assert not target.exists()
