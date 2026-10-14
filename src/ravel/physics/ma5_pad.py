"""Pinned, already-built PAD/SampleAnalyzer execution via the existing worker.

Builds, installation and event generation are separate operations. The native
command is the original SampleAnalyzer executable and fixed supplied file list.
Its complete source-defined linear SAF output is ingested by ma5_family.
"""
from copy import deepcopy
import hashlib
from pathlib import Path, PurePosixPath
import re
import os
import shutil

from ravel.physics import ma5_saf, ma5_bookings, ma5_family
from ravel.workflow import science
from ravel.workflow.state_io import atomic_json


class InputCapture(ma5_saf.Capture):
    """Stream supplied events/libraries; metadata remains the bounded SAF capture.

    No supplied binary is decoded or imported. The 16 GiB per-file admission
    ceiling bounds this adapter's family; descriptor/path identities and ending
    byte hashes are rechecked, including legitimate empty runtime markers.
    """
    def __init__(self):
        super().__init__()
        self.streams = {}

    def _stream(self, path, allow_empty):
        before = self.ordinary(path)
        if not (0 if allow_empty else 1) <= before[3] <= 16 * 1024**3:
            raise ValueError('supplied event/runtime file exceeds streaming admission')
        h = hashlib.sha256()
        with path.open('rb') as stream:
            if ma5_saf._identity(os.fstat(stream.fileno())) != before:
                raise ValueError('streamed input replaced before capture')
            for block in iter(lambda: stream.read(1024**2), b''):
                h.update(block)
            if ma5_saf._identity(os.fstat(stream.fileno())) != before:
                raise ValueError('streamed input changed during capture')
        if self.ordinary(path) != before:
            raise ValueError('streamed input pathname changed')
        return before, h.hexdigest()

    def stream_pin(self, value, base, *, allow_empty=False):
        ma5_saf._keys(value, ('path', 'sha256'), 'supplied stream pin')
        if type(value['path']) is not str or not value['path'].strip() or not re.fullmatch('[0-9a-f]{64}', str(value['sha256'])):
            raise ValueError('literal supplied stream path and SHA256 required')
        p = Path(value['path']); p = p if p.is_absolute() else Path(base).absolute()/p
        fact = self._stream(p, allow_empty)
        if fact[1] != value['sha256'] or p in self.streams and self.streams[p] != (fact, allow_empty):
            raise ValueError('supplied stream bytes changed')
        self.streams[p] = (fact, allow_empty)
        return p

    def finish(self):
        super().finish()
        for p, (fact, allow_empty) in list(self.streams.items()):
            if self._stream(p, allow_empty) != fact:
                raise ValueError('ending streamed input identity or bytes changed')


def validate(task):
    return ma5_saf.validate(task)


def _load(task, base):
    validate(task); c = InputCapture(); path, raw = c.read(task['input'], base); doc = ma5_saf._json(raw)
    ma5_saf._keys(doc, ('schema_version', 'analysis', 'source', 'bookings', 'upstream', 'runtime',
        'events', 'staged_assets', 'population', 'max_seconds', 'max_ram_mib'), 'PAD supplied-event input')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1: raise ValueError('PAD schema1 required')
    if not re.fullmatch(r'[A-Za-z0-9_]+', str(doc['analysis'])): raise ValueError('native analysis identity required')
    for key, low, high in (('max_seconds', 1, 3600), ('max_ram_mib', 512, 8192)):
        if type(doc[key]) is not int or not low <= doc[key] <= high: raise ValueError('explicit native resource bound required')
    source, payload = c.pin(doc['source'], path.parent); expected = ma5_bookings.compile_source(payload.decode())
    booking_path, b = c.pin(doc['bookings'], path.parent); declared = ma5_saf._json(b)
    declaration_keys = (*expected, 'source', 'scope')
    if 'physics_configuration' in expected: declaration_keys += ('configuration_sources',)
    ma5_saf._keys(declared, declaration_keys, 'PAD bookings')
    q, text = c.pin(declared['source'], booking_path.parent)
    if q != source or text != payload or {k: declared[k] for k in expected} != expected: raise ValueError('PAD source/output contract differs')
    ma5_bookings.configuration_sources(expected, declared, c, booking_path.parent)
    ma5_saf._keys(doc['upstream'], ('manager', 'saf_writer', 'configuration', 'core', 'revision'), 'PAD upstream API')
    if type(doc['upstream']['revision']) is not str or not doc['upstream']['revision'].strip(): raise ValueError('upstream revision required')
    for key in ('manager', 'saf_writer', 'configuration', 'core'): c.pin(doc['upstream'][key], path.parent)
    # Refuse unsupported writer naming/colliding regions before any dispatch.
    _, core = c.pin(doc['upstream']['core'], path.parent)
    ma5_family.native_paths(doc['analysis'], expected['regions'], core.decode())
    ma5_saf._keys(doc['runtime'], ('executable', 'main', 'build_receipt', 'files'), 'built PAD runtime')
    executable = c.stream_pin(doc['runtime']['executable'], path.parent)
    if not os.access(executable, os.X_OK): raise ValueError('built executable permission required')
    main, b = c.pin(doc['runtime']['main'], path.parent); main_text = ma5_bookings.clean(b.decode())
    calls = re.findall(r'InitializeAnalyzer\s*\(\s*"([^"\\]*)"\s*,\s*"([^"\\]*)"', main_text)
    if calls != [(doc['analysis'], 'analysis.saf')]: raise ValueError('main must register exactly the requested routine/analysis.saf')
    if not re.search(r'Initialize\s*\(\s*argc\s*,\s*argv\s*,\s*"pdg.ma5"\s*\)', main_text):
        raise ValueError('source-bound standard file-list and PDG initialization required')
    if 'InitializeWriter' in main_text: raise ValueError('new event output/shower is outside PAD supplied-analysis scope')
    _, b = c.pin(doc['runtime']['build_receipt'], path.parent); receipt = ma5_saf._json(b)
    ma5_saf._keys(receipt, ('executable', 'main', 'source', 'assets', 'runtime_files', 'scope'), 'declared build receipt')
    if receipt['executable'] != doc['runtime']['executable'] or receipt['main'] != doc['runtime']['main'] or receipt['source'] != doc['source']:
        raise ValueError('compiled-source identity differs from declared build receipt')
    if receipt['assets'] != doc['staged_assets'] or receipt['runtime_files'] != doc['runtime']['files']:
        raise ValueError('full asset/runtime population differs from declared build receipt')
    if type(receipt['scope']) is not str or not receipt['scope'].strip(): raise ValueError('build observation scope required')
    if type(doc['runtime']['files']) is not list or not doc['runtime']['files']: raise ValueError('complete declared runtime files required')
    for pin in doc['runtime']['files']: c.stream_pin(pin, path.parent, allow_empty=True)
    if type(doc['staged_assets']) is not dict or 'pdg.ma5' not in doc['staged_assets']: raise ValueError('complete PDG and requested analysis assets required')
    for rel, pin in doc['staged_assets'].items():
        name = PurePosixPath(rel)
        if name.is_absolute() or '..' in name.parts or not rel or str(name) != rel: raise ValueError('canonical owned asset path required')
        c.stream_pin(pin, path.parent)
    if type(doc['events']) is not list or not 1 <= len(doc['events']) <= 128: raise ValueError('complete supplied event-file list required')
    events = []
    for pin in doc['events']:
        p = c.stream_pin(pin, path.parent)
        if '\n' in str(p) or '\r' in str(p): raise ValueError('event file-list injection refused')
        if p in events: raise ValueError('duplicate event file would repeat exposure')
        events.append(p)
    ma5_saf._keys(doc['population'], ('expected_initial_entries', 'description', 'basis', 'weight_convention', 'response'), 'PAD scientific population')
    n = doc['population']['expected_initial_entries']
    if type(n) is not int or not 1 <= n <= 10**9: raise ValueError('original complete event denominator required')
    for k in ('description', 'weight_convention', 'response'):
        if type(doc['population'][k]) is not str or not doc['population'][k].strip(): raise ValueError('explicit population/response/weight attribution required')
    if doc['population']['basis'] not in ('bsm', 'sm', 'sm_plus_bsm', 'signed_interference'): raise ValueError('exact event prediction basis required')
    c.finish(); return path, doc, expected, c, executable, events


def inputs(task, base):
    _, _, _, c, _, _ = _load(task, base)
    return [*sorted(set(c.files) | set(c.streams)), Path(__file__).resolve(), Path(ma5_family.__file__).resolve(), Path(ma5_bookings.__file__).resolve(), Path(ma5_saf.__file__).resolve(), Path(ma5_saf.reader.__file__).resolve()]


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds'] + 30


def run(task, base, output):
    out = Path(output).resolve()
    # Only the ordinary admitted worker can dispatch; this function grants no approval.
    found = None
    for rd in out.parents:
        if (rd/science.PLAN).is_file():
            selected = science.verify_worker(rd); spec = science.execution_spec(rd)
            if spec['mode'] != 'ma5-pad' or spec['task'] != task or out != (rd/selected['output_directory']).resolve():
                raise ValueError('PAD worker differs from ordinary approved plan')
            found = selected; break
    if found is None: raise ValueError('ordinary approved PAD worker required')
    path, doc, expected, c, executable, events = _load(task, base)
    if execution_seconds(task, base) > found['max_seconds']: raise ValueError('complete native/readback bound exceeds admitted stage')
    out.mkdir(parents=True, exist_ok=True)
    work = out/'pad-work'; build = work/'Build'; inp = work/'Input'
    build.mkdir(parents=True, exist_ok=False); inp.mkdir()
    for rel, pin in doc['staged_assets'].items():
        original = c.stream_pin(pin, path.parent); destination = build/rel; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        if science.execution.file_hash(destination) != pin['sha256']:
            raise ValueError('staged PAD asset bytes differ')
    listing = inp/'supplied.list'; listing.write_text(''.join(str(p)+'\n' for p in events))
    command = [str(executable), str(listing)]
    atomic_json(out/'pad-dispatch.json', {'command': command, 'cwd': str(build), 'events': doc['events'],
        'source': doc['source'], 'runtime': doc['runtime'], 'population': doc['population'], 'new_generated_events': 0})
    from ravel.physics.reinterpret_db import execute_native
    c.finish()
    receipt = execute_native(command, build, doc)
    c.finish()
    root = work/'Output/SAF/supplied'/(doc['analysis']+'_0')
    names = c.census(root)
    files = {rel: hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in names}
    general = {'schema_version': 2, 'analysis': doc['analysis'], 'source': doc['source'], 'bookings': doc['bookings'],
        'upstream': {k: doc['upstream'][k] for k in ('manager', 'saf_writer', 'core', 'revision')},
        'views': {'native': {'root': str(root), 'files': files, 'expected_initial_entries': doc['population']['expected_initial_entries'],
            'population_description': doc['population']['description']}}, 'population_scope': doc['population']['description']}
    # Resolve every original pin at its original base, never reinterpret relative paths at output.
    for key in ('source', 'bookings'):
        general[key] = dict(general[key], path=str(c.pin(general[key], path.parent)[0]))
    for key in ('manager', 'saf_writer', 'core'):
        general['upstream'][key] = dict(general['upstream'][key], path=str(c.pin(general['upstream'][key], path.parent)[0]))
    # The booking declaration may contain a relative source; materialize an exact bound copy.
    booking_path, b = c.pin(doc['bookings'], path.parent); book = ma5_saf._json(b); book['source'] = general['source']
    if 'configuration_sources' in book:
        book['configuration_sources'] = {key: dict(pin, path=str(c.pin(pin, booking_path.parent)[0]))
                                         for key, pin in book['configuration_sources'].items()}
    atomic_json(out/'pad-bookings.json', book); general['bookings'] = {'path': str(out/'pad-bookings.json'), 'sha256': hashlib.sha256((out/'pad-bookings.json').read_bytes()).hexdigest()}
    atomic_json(out/'pad-readback-input.json', general)
    result = ma5_family.run({'input': str(out/'pad-readback-input.json')}, out, out/'pad-readback')
    result.update(kind='native-supplied-ma5-pad', native_engine_executed=True, native_execution=receipt,
        runtime=deepcopy(doc['runtime']), population=deepcopy(doc['population']), source_consumption_verified=False,
        scope='Complete supplied-event native PAD linear SAF delivery; no CLs or joint independence')
    result['limitations'].append('Declared build/routine/runtime pins are not continuous source, card or loaded-library tracing; detector and statistical qualification remain separate.')
    atomic_json(out/'pad-result.json', result); c.finish(); return result
