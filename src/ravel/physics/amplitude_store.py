"""Binary Gram-matrix stores for weighted integration points, written in resumable blocks.

A block file holds one independent, equal-exposure integration block::

    b'RAVG1\\n' | uint64 header length | JSON header | records

Every record is little-endian float64: the integration factor (absolute units
named by ``factor_unit``), the declared observables, the momenta of the declared
particles (px, py, pz, E per particle, when ``particles`` is declared) and the
packed Gram matrix (K*K reals, see ``amplitude_basis.pack``). The weight of
hypothesis theta at a point is ``factor * Re(c^dagger G c)``.

A block is written to ``<name>.partial`` and becomes readable only when
``finish`` renames it and writes ``<name>.complete.json`` with its sha256, point
count and integration census. ``audit_points`` keeps the full amplitude arrays of
the first points in ``<name>.audit.npy`` for later cross-checks.

``run_schedule`` runs a declared list of blocks through a producer, records a
manifest after every completed block and resumes after an interruption from the
first missing block. Completed blocks are checked against their sha256 before a
resume continues; a changed header or schedule cannot resume.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time

import numpy as np

from . import amplitude_basis as ab

MAGIC = b'RAVG1\n'
FORMAT = 'ravel-gram-block'
MANIFEST = 'manifest.json'
_SUMMARY = ('attempted', 'accepted', 'rejected', 'failed')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def marker_path(path):
    path = Path(path)
    return path.with_name(path.name + '.complete.json')


def audit_path(path):
    path = Path(path)
    return path.with_name(path.name + '.audit.npy')


def partial_path(path):
    path = Path(path)
    return path.with_name(path.name + '.partial')


def validate_header(header):
    ab.require(type(header) is dict, 'block header must be an object')
    basis = ab.Basis.from_document(header.get('basis'))
    observables = header.get('observables', [])
    ab.require(type(observables) is list and all(isinstance(o, str) and o for o in observables)
               and len(set(observables)) == len(observables), 'observables must be unique names')
    particles = header.get('particles')
    if particles is not None:
        ab.require(type(particles) is dict and type(particles.get('pdg')) is list and particles['pdg']
                   and type(particles.get('status')) is list and len(particles['status']) == len(particles['pdg'])
                   and all(type(v) is int for v in particles['pdg'] + particles['status']),
                   'particles need pdg and status lists of equal length')
    ab.text(header.get('factor_unit'), 'factor_unit')
    audit = header.get('audit_points', 0)
    ab.require(type(audit) is int and audit >= 0, 'audit_points must be a non-negative integer')
    return {'k': len(basis), 'observables': len(observables),
            'momenta': 0 if particles is None else 4 * len(particles['pdg']),
            'particles': 0 if particles is None else len(particles['pdg']), 'audit': audit}


def _layout(shape):
    return 1 + shape['observables'] + shape['momenta'] + shape['k'] ** 2


class BlockWriter:
    """Stream points of one block to disk; nothing is readable until ``finish``."""

    def __init__(self, path, header):
        self.path = Path(path)
        self.header = {**header, 'format': FORMAT, 'schema_version': 1}
        self.shape = validate_header(self.header)
        ab.require(not self.path.exists() and not marker_path(self.path).exists(), f'block {self.path} already exists')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._partial = partial_path(self.path)
        self._stream = self._partial.open('wb')
        raw = _canonical(self.header)
        self._stream.write(MAGIC + struct.pack('<Q', len(raw)) + raw)
        self.points = 0
        self._audit = []
        self.state = 'open'

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if self.state == 'open':
            self.abandon()
            if kind is None:
                raise ValueError(f'block {self.path} was neither finished nor abandoned')
        return False

    def append(self, *, gram, factor, observables=None, momenta=None, amplitudes=None):
        ab.require(self.state == 'open', 'block writer is closed')
        gram = np.asarray(gram, dtype=complex)
        n = gram.shape[0] if gram.ndim == 3 else -1
        k = self.shape['k']
        ab.require(gram.shape == (n, k, k), f'gram must have shape (points, {k}, {k})')
        factor = np.asarray(factor, dtype=float)
        ab.require(factor.shape == (n,), 'factor needs one value per point')
        obs = np.zeros((n, 0)) if observables is None else np.asarray(observables, dtype=float)
        ab.require(obs.shape == (n, self.shape['observables']), f'observables must have shape (points, {self.shape["observables"]})')
        if self.shape['momenta']:
            mom = np.asarray(momenta, dtype=float)
            ab.require(mom.shape == (n, self.shape['particles'], 4), 'momenta must have shape (points, particles, 4)')
            mom = mom.reshape(n, -1)
        else:
            ab.require(momenta is None, 'momenta given but the header declares no particles')
            mom = np.zeros((n, 0))
        packed = ab.pack(gram)
        ab.require(np.allclose(gram, ab.unpack(packed, k), rtol=1e-12, atol=1e-300 + 1e-12 * np.abs(gram).max(initial=0)),
                   'gram matrices must be Hermitian')
        rows = np.concatenate([factor[:, None], obs, mom, packed], axis=1)
        ab.require(np.isfinite(rows).all(), 'stored values must be finite')
        if self.shape['audit'] and self.points < self.shape['audit'] and amplitudes is not None:
            take = min(n, self.shape['audit'] - self.points)
            self._audit.append(np.asarray(amplitudes, dtype=complex)[:take])
        self._stream.write(rows.astype('<f8').tobytes())
        self.points += n

    def finish(self, summary):
        ab.require(self.state == 'open', 'block writer is closed')
        ab.require(type(summary) is dict and set(_SUMMARY) <= set(summary), 'summary needs ' + ', '.join(_SUMMARY))
        for key in _SUMMARY:
            ab.require(type(summary[key]) is int and summary[key] >= 0, f'summary {key} must be a non-negative integer')
        ab.require(summary['attempted'] == summary['accepted'] + summary['rejected'] + summary['failed'],
                   'attempted must equal accepted + rejected + failed')
        ab.require(summary['accepted'] == self.points, 'accepted must equal the stored points')
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._stream.close()
        marker = {'schema_version': 1, 'format': FORMAT, 'points': self.points, 'summary': dict(summary),
                  'header_sha256': hashlib.sha256(_canonical(self.header)).hexdigest()}
        if self._audit:
            audit = np.concatenate(self._audit)
            with audit_path(self.path).open('wb') as stream:
                np.save(stream, audit, allow_pickle=False)
            marker['audit'] = {'points': list(range(len(audit))), 'sha256': _sha256_file(audit_path(self.path))}
        os.replace(self._partial, self.path)
        marker['sha256'] = _sha256_file(self.path)
        tmp = marker_path(self.path).with_suffix('.tmp')
        tmp.write_bytes(json.dumps(marker, indent=2, sort_keys=True).encode() + b'\n')
        os.replace(tmp, marker_path(self.path))
        self.state = 'finished'
        return marker

    def abandon(self):
        if self.state == 'open':
            self._stream.close()
            self._partial.unlink(missing_ok=True)
            self.state = 'abandoned'


def _open(path):
    path = Path(path)
    marker_file = marker_path(path)
    if not path.is_file() or not marker_file.is_file():
        raise FileNotFoundError(f'no completed block at {path}')
    ab.require(not path.is_symlink() and not marker_file.is_symlink(), 'blocks must not be symlinks')
    marker = json.loads(marker_file.read_text())
    ab.require(_sha256_file(path) == marker.get('sha256'), f'block {path} differs from its recorded sha256')
    with path.open('rb') as stream:
        ab.require(stream.read(len(MAGIC)) == MAGIC, f'{path} is not a Gram block')
        (length,) = struct.unpack('<Q', stream.read(8))
        header = json.loads(stream.read(length))
    shape = validate_header(header)
    offset = len(MAGIC) + 8 + length
    width = _layout(shape)
    body = path.stat().st_size - offset
    ab.require(body == marker['points'] * width * 8, f'block {path} has an incomplete record')
    return header, shape, marker, offset, width


def header_size(path):
    with Path(path).open('rb') as stream:
        stream.read(len(MAGIC))
        (length,) = struct.unpack('<Q', stream.read(8))
    return len(MAGIC) + 8 + length


def _split(rows, shape):
    n = rows.shape[0]
    o, m, k = shape['observables'], shape['momenta'], shape['k']
    out = {'factor': rows[:, 0].copy(), 'observables': rows[:, 1:1 + o].copy(),
           'gram': ab.unpack(rows[:, 1 + o + m:], k)}
    if m:
        out['momenta'] = rows[:, 1 + o:1 + o + m].reshape(n, shape['particles'], 4).copy()
    return out


def iter_chunks(path, chunk_points=65536):
    """Yield the points of a completed block in chunks, without loading the whole block."""
    ab.require(type(chunk_points) is int and chunk_points > 0, 'chunk_points must be a positive integer')
    header, shape, marker, offset, width = _open(path)
    with Path(path).open('rb') as stream:
        stream.seek(offset)
        left = marker['points']
        while left:
            take = min(left, chunk_points)
            rows = np.frombuffer(stream.read(take * width * 8), dtype='<f8').reshape(take, width)
            yield _split(rows, shape)
            left -= take


def read_block(path):
    header, shape, marker, offset, width = _open(path)
    with Path(path).open('rb') as stream:
        stream.seek(offset)
        rows = np.frombuffer(stream.read(), dtype='<f8').reshape(marker['points'], width)
    return {**_split(rows, shape), 'header': header, 'marker': marker}


def read_header(path):
    return _open(path)[0]


def read_audit(path):
    marker = _open(path)[2]
    ab.require('audit' in marker, f'block {path} keeps no audit amplitudes')
    ab.require(_sha256_file(audit_path(path)) == marker['audit']['sha256'], 'audit file differs from its recorded sha256')
    with audit_path(path).open('rb') as stream:
        amplitudes = np.load(stream, allow_pickle=False)
    return {'points': marker['audit']['points'], 'amplitudes': amplitudes}


# ---------------------------------------------------------------- schedules
def validate_schedule(schedule):
    ab.require(type(schedule) is dict and schedule.get('schema_version') == 1, 'schedule schema_version 1 required')
    blocks = schedule.get('blocks')
    ab.require(type(blocks) is list and blocks, 'schedule needs blocks')
    budget = schedule.get('max_operation_seconds')
    ab.require(type(budget) in (int, float) and math.isfinite(budget) and budget > 0, 'max_operation_seconds must be positive')
    ids, seeds, draws = set(), set(), {}
    for block in blocks:
        ab.require(type(block) is dict and {'id', 'cohort', 'seed', 'draws', 'max_seconds'} <= set(block),
                   'each block needs id, cohort, seed, draws and max_seconds')
        ab.require(isinstance(block['id'], str) and block['id'] and '/' not in block['id'] and block['id'] not in ids,
                   'block ids must be unique names')
        ids.add(block['id'])
        ab.text(block['cohort'], 'cohort')
        ab.require(type(block['seed']) is int and block['seed'] > 0 and block['seed'] not in seeds,
                   'every block needs its own positive seed')
        seeds.add(block['seed'])
        ab.require(type(block['draws']) is int and block['draws'] > 0, 'draws must be a positive integer')
        ab.require(draws.setdefault(block['cohort'], block['draws']) == block['draws'],
                   f'cohort {block["cohort"]} blocks need equal exposure (draws)')
        ab.require(type(block['max_seconds']) in (int, float) and block['max_seconds'] > 0, 'block max_seconds must be positive')
    for cohort in draws:
        ab.require(sum(b['cohort'] == cohort for b in blocks) >= 2, f'cohort {cohort} needs at least two blocks')
    return schedule


def load_manifest(directory):
    return json.loads((Path(directory) / MANIFEST).read_text())


def _write_manifest(directory, manifest):
    path = Path(directory) / MANIFEST
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


def run_schedule(directory, schedule, produce, *, header, clock=time.monotonic, block_header=None):
    """Run (or resume) every block of ``schedule``.

    ``produce(block, writer)`` appends the points of one block and returns its
    integration census. Each block runs under its own ``max_seconds`` wall, which
    the producer enforces. A new block starts only while the operation has used
    less than ``max_operation_seconds``; the rest stay in ``remaining`` for a later
    resume. ``block_header(block)`` may add block-specific header fields (for
    example the particle identities of the block's channel).
    """
    validate_schedule(schedule)
    validate_header(header)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    identity = {'header_sha256': hashlib.sha256(_canonical(header)).hexdigest(),
                'schedule_sha256': hashlib.sha256(_canonical(schedule)).hexdigest()}
    if (directory / MANIFEST).exists():
        manifest = load_manifest(directory)
        ab.require(manifest.get('header_sha256') == identity['header_sha256'],
                   'store header differs from the header of the interrupted operation; start a new store')
        ab.require(manifest.get('schedule_sha256') == identity['schedule_sha256'],
                   'schedule differs from the schedule of the interrupted operation; start a new store')
        for row in manifest['blocks']:
            _open(directory / row['path'])
    else:
        manifest = {'schema_version': 1, 'format': 'ravel-gram-store', **identity, 'header': header,
                    'schedule': schedule, 'blocks': [], 'status': 'incomplete', 'operations': 0}
    manifest['operations'] += 1
    done = {row['id'] for row in manifest['blocks']}
    todo = [b for b in schedule['blocks'] if b['id'] not in done]
    for block in todo:
        stale = partial_path(directory / f'{block["id"]}.ravg')
        stale.unlink(missing_ok=True)
    start = clock()
    manifest['remaining'] = [b['id'] for b in todo]
    _write_manifest(directory, manifest)
    for block in todo:
        if clock() - start >= schedule['max_operation_seconds']:
            break
        path = directory / f'{block["id"]}.ravg'
        meta = {k: block[k] for k in ('id', 'cohort', 'seed', 'draws')}
        extra = block_header(dict(block)) if block_header is not None else {}
        writer = BlockWriter(path, {**header, **extra, 'block': meta})
        try:
            summary = produce(dict(block), writer)
            ab.require(summary.get('attempted') == block['draws'], f'block {block["id"]} must account for all {block["draws"]} draws')
            marker = writer.finish(summary)
        except BaseException:
            writer.abandon()
            _write_manifest(directory, manifest)
            raise
        clock()
        manifest['blocks'].append({**meta, 'path': path.name, 'sha256': marker['sha256'], 'points': marker['points'],
                                   'summary': marker['summary']})
        manifest['remaining'].remove(block['id'])
        manifest['status'] = 'complete' if not manifest['remaining'] else 'incomplete'
        _write_manifest(directory, manifest)
    order = [b['id'] for b in schedule['blocks']]
    manifest['blocks'].sort(key=lambda row: order.index(row['id']))
    manifest['status'] = 'complete' if not manifest['remaining'] else 'incomplete'
    _write_manifest(directory, manifest)
    return manifest


def store_blocks(directory):
    """Completed blocks of a store, verified, in schedule order."""
    manifest = load_manifest(directory)
    for row in manifest['blocks']:
        _open(Path(directory) / row['path'])
    return manifest
