"""Exact continuous responses on complete retained amplitude blocks.

Uses the ordinary prediction descriptor for binning, observables and units.
No event production, interpolation or polynomial assumption is involved.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import numpy as np

from . import amplitude_basis as ab, amplitude_predictions as predictions, amplitude_store as store
from . import amplitude_selection


def observation(path):
    path = Path(path).absolute()
    ab.require(not any(p.is_symlink() for p in (path, *path.parents)), 'cache/source aliases refused')
    before = path.stat()
    digest = store._sha256_file(path)
    after = path.stat()
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    ab.require(identity(before) == identity(after), 'cache/source changed during capture')
    return {'path': str(path), 'sha256': digest, 'identity': identity(after)}


def bind(template, bindings, point, basis):
    """Apply explicit affine scalar bindings to numeric hypothesis leaves only."""
    result, seen = deepcopy(template), set()
    for binding in bindings:
        ab.require(type(binding) is dict and set(binding) == {'path', 'offset', 'coefficients'}, 'binding fields differ')
        path = binding['path']
        ab.require(type(path) is list and path and all(type(k) in (str, int) for k in path), 'binding path required')
        ab.require(tuple(path) not in seen, 'duplicate binding target')
        seen.add(tuple(path))
        ab.require(type(binding['coefficients']) is dict and binding['coefficients'], 'binding coefficients required')
        parent = result
        try:
            for key in path[:-1]:
                parent = parent[key]
            ab.real(parent[path[-1]], 'bound hypothesis leaf')
            value = ab.real(binding['offset'], 'binding offset')
            for name, coefficient in binding['coefficients'].items():
                value += ab.real(coefficient) * ab.real(point[name], name)
            parent[path[-1]] = ab.real(value, 'bound value')
        except (IndexError, KeyError, TypeError) as exc:
            raise ValueError('binding target or parameter is absent') from exc
    return ab.hypothesis(result, basis)


class CachedResponse:
    """In-memory immutable captured blocks, with bounded input bytes and ending checks."""

    def __init__(self, task, base, *, hypothesis, bindings, estimator, max_cache_bytes, fiducial=None, replay=None, replay_base=None):
        ab.require(estimator in ('reference-gram', 'hypothesis-pairing'), 'explicit cache estimator required')
        ab.require(type(max_cache_bytes) is int and max_cache_bytes > 0, 'positive cache byte budget required')
        paths = predictions.inputs(task, base)
        self.inputs = [observation(p) for p in paths]
        ab.require(sum(p['identity'][2] for p in self.inputs) <= max_cache_bytes, 'cache byte budget exceeded')
        self.ctx = predictions.load(task, base)
        self.estimator, self.bindings = estimator, deepcopy(bindings)
        ab.require(type(bindings) is list, 'bindings must be a list')
        doc, manifest = self.ctx['doc'], self.ctx['manifest']
        ab.require(not any(key in doc for key in ('coupling_scaling', 'coupling_polynomial')),
                   'cached responses use complete hypotheses, not polynomial term extraction')
        self.template = next((h for h in self.ctx['hypotheses'] if h['id'] == hypothesis), None)
        self.reference = next(h for h in self.ctx['hypotheses'] if h['id'] == doc['reference'])
        ab.require(self.template is not None and hypothesis != doc['reference'], 'select a non-reference hypothesis')
        self.basis, self.edges = self.ctx['basis'], self.ctx['edges']
        self.divide = np.diff(self.edges) if doc['normalization']['representation'] == 'differential' else np.ones(len(self.edges)-1)
        self.width = len(self.edges) + 1
        self.blocks = []
        schedule = store.validate_schedule(manifest['schedule'])['blocks']
        ab.require(len(schedule) == len(manifest['blocks']) and not manifest['remaining'], 'complete scheduled block population required')
        header = manifest['header']
        ab.require(hashlib.sha256(store._canonical(header)).hexdigest() == manifest['header_sha256']
                   and hashlib.sha256(store._canonical(manifest['schedule'])).hexdigest() == manifest['schedule_sha256'],
                   'store header/schedule commitments differ')
        if fiducial is not None:
            amplitude_selection.validate(fiducial)
        self.fiducial = deepcopy(fiducial)
        observables = header['observables']
        self.i_s = observables.index(doc['observable']['invariant'])
        i_x = observables.index(doc['observable']['name'])
        factor = predictions._SCALE[doc['normalization']['unit']] / predictions._SCALE[header['factor_unit']]
        factor *= doc['normalization'].get('factor', {}).get('value', 1.)
        for planned, row in zip(schedule, manifest['blocks']):
            identity = {key: planned[key] for key in ('id', 'cohort', 'seed', 'draws')}
            ab.require(all(row[key] == value for key, value in identity.items()), 'block schedule correspondence differs')
            relative = Path(row['path'])
            ab.require(not relative.is_absolute() and len(relative.parts) == 1, 'block path must be a local member')
            block = store.read_block(self.ctx['store'] / relative)
            bh, marker = block['header'], block['marker']
            ab.require(bh['block'] == identity and marker['summary'] == row['summary']
                       and marker['sha256'] == row['sha256'] and marker['points'] == row['points']
                       and marker['header_sha256'] == hashlib.sha256(store._canonical(bh)).hexdigest(), 'block/manifest identity differs')
            for key in ('basis', 'observables', 'factor_unit', 'pairing', 'proposals'):
                ab.require(bh.get(key) == header.get(key), 'block scientific header differs: ' + key)
            summary = row['summary']
            ab.require(all(type(summary[k]) is int and summary[k] >= 0 for k in ('attempted', 'accepted', 'rejected', 'failed')),
                       'nonnegative integer draw census required')
            ab.require(summary['attempted'] == planned['draws'] == summary['accepted'] + summary['rejected'] + summary['failed']
                       and summary['accepted'] == row['points'] and summary['failed'] == 0
                       and summary.get('safety_excluded', 0) == 0, 'failed/safety/incomplete draws cannot become zeros')
            if estimator == 'hypothesis-pairing':
                ab.require('pairing' in block, 'hypothesis-pairing needs complete retained pairings, not audit samples')
            mask = np.ones(row['points'], bool)
            for cut in doc['selection']:
                x = block['observables'][:, observables.index(cut['observable'])]
                if cut['min'] is not None:
                    mask &= x >= cut['min']
                if cut['max'] is not None:
                    mask &= x < cut['max']
            if fiducial is not None:
                ab.require('momenta' in block, 'fiducial selection needs stored momenta')
                mask &= amplitude_selection.select(block['momenta'], bh['particles']['pdg'], fiducial)
            block.update(identity=identity, mask=mask, x=block['observables'][:, i_x],
                         integration_factor=block['factor'] * factor)
            self.blocks.append(block)
        self.raw_replayed = replay is not None
        if replay is not None:
            self._replay(replay, replay_base, max_cache_bytes)
        self.identity = hashlib.sha256(store._canonical({'inputs': self.inputs, 'estimator': estimator,
                                                        'fiducial': fiducial, 'bindings': bindings,
                                                        'hypothesis': hypothesis, 'replay': replay})).hexdigest()
        self.finish()

    def _replay(self, descriptor, base, maximum):
        """Reparse supplied original native returns and compare every cache row."""
        from . import amplitude_records as records
        from .source_tables import bounded_read
        ab.require(type(descriptor) is dict and set(descriptor) == {'protocol', 'blocks'}, 'raw replay needs protocol and blocks')
        protocol = records.validate_protocol(descriptor['protocol'])
        rows = descriptor['blocks']
        ab.require(type(rows) is list and [r['id'] for r in rows] == [b['identity']['id'] for b in self.blocks],
                   'raw replay must cover the complete ordered block population')
        for source, block in zip(rows, self.blocks):
            ab.require(set(source) == {'id', 'channel', 'source', 'proposal'}, 'raw replay block fields differ')
            ab.require(type(source['channel']) is int and str(source['channel']) in protocol['channels'],
                       'raw replay needs a declared integer channel')
            captured = {}
            for key in ('source', 'proposal'):
                pin = source[key]
                ab.require(type(pin) is dict and set(pin) == {'path', 'sha256'}, 'raw replay requires exact file pins')
                path = Path(pin['path'])
                path = path if path.is_absolute() else Path(base)/path
                observed = observation(path)
                ab.require(observed['sha256'] == pin['sha256'], 'raw replay source digest differs')
                existing = next((p for p in self.inputs if p['path'] == observed['path']), None)
                if existing is None:
                    self.inputs.append(observed)
                else:
                    ab.require(existing == observed, 'raw replay source observation differs')
                ab.require(sum(p['identity'][2] for p in self.inputs) <= maximum, 'raw replay exceeds cache byte budget')
                captured[key] = bounded_read(path, maximum)
            identity = block['identity']
            expected_proposal = block['header'].get('proposals', {}).get(identity['cohort'])
            ab.require(expected_proposal == source['proposal']['sha256'], 'raw replay proposal differs from cached cohort')
            parsed = records.parse(captured['source'], operation=protocol['operations']['block'],
                                   draws=identity['draws'], seed=identity['seed'], channel=source['channel'], protocol=protocol)
            ab.require(parsed['summary']['failed'] == 0 and parsed['summary']['safety_excluded'] == 0,
                       'raw replay has failed or safety-excluded draws')
            for key in ('attempted', 'accepted', 'rejected', 'failed'):
                ab.require(parsed['summary'][key] == block['marker']['summary'][key], 'raw replay draw census differs')
            ab.require(protocol['factor_unit'] == block['header']['factor_unit']
                       and protocol['channels'][str(source['channel'])]['pdg'] == block['header']['particles']['pdg'],
                       'raw replay units or particle identities differ')
            ab.require(records.oracle_check(parsed, protocol)['passed'], 'raw replay point oracle differs')
            rebuilt, _, _ = records.to_block(parsed, protocol, spin0=block['header'].get('spin0'))
            # Compare the actual storage law: only real diagonal and upper
            # Hermitian entries are serialized, not redundant roundoff entries.
            rebuilt['gram'] = ab.unpack(ab.pack(rebuilt['gram']), len(self.basis))
            for key in ('gram', 'factor', 'observables', 'momenta'):
                ab.require(np.array_equal(rebuilt[key], block[key]), 'raw replay differs from cached ' + key)
            if 'pairing' in block:
                expected = {'amplitudes': rebuilt['amplitudes'], 'identical': parsed['identical'],
                            'selected_direct': parsed['selected_direct'], 'normalization': parsed['meta'][:, 5]}
                ab.require(all(np.array_equal(v, block['pairing'][k]) for k, v in expected.items()),
                           'raw replay differs from retained pairings')

    def finish(self):
        ab.require([observation(p['path']) for p in self.inputs] == self.inputs, 'cache/source ending identity changed')

    def evaluate(self, point):
        hypothesis = bind(self.template, self.bindings, point, self.basis)
        cohorts, identities = {}, {}
        for block in self.blocks:
            s = block['observables'][:, self.i_s]
            values = []
            for h in (self.reference, hypothesis):
                coefficients = ab.coefficients(h, self.basis, s)
                if self.estimator == 'reference-gram':
                    value = ab.evaluate(block['gram'], coefficients)
                else:
                    value = ab.pairing_square(c=coefficients, exchange=np.array(block['header']['pairing']['exchange']),
                                              **block['pairing'])
                values.append(block['integration_factor'] * value)
            mask = block['mask']
            vectors = [ab.histogram(block['x'][mask], w[mask], self.edges) for w in (*values, values[1]-values[0])]
            ident = block['identity']
            cohorts.setdefault(ident['cohort'], []).append(np.concatenate(vectors))
            identities.setdefault(ident['cohort'], []).append(deepcopy(ident))
        joint = ab.centered_blocks(cohorts)
        finite = slice(2*self.width, 3*self.width-2)
        return {'point': dict(point), 'identity': self.identity, 'blocks': cohorts, 'block_ids': identities, 'joint': joint,
                'raw_replayed': self.raw_replayed,
                'difference': joint['mean'][finite] / self.divide,
                'mc_covariance': joint['covariance'][finite, finite] / np.outer(self.divide, self.divide),
                'layout': {'streams': ['reference', 'model', 'difference'], 'per_stream': 'bins, underflow, overflow',
                           'representation': 'integrated'}}


def cross_covariance(left, right):
    """Shared-block cross-state kernel; all streams and both flows are retained."""
    ab.require(left['identity'] == right['identity'] and left['block_ids'] == right['block_ids'],
               'cross-state covariance requires the same captured population and selection')
    result = np.zeros((len(left['joint']['mean']), len(right['joint']['mean'])))
    for cohort, rows in left['blocks'].items():
        a, b = np.asarray(rows), np.asarray(right['blocks'][cohort])
        n = len(a)
        result += (a-a.mean(axis=0)).T @ (b-b.mean(axis=0)) / (n*(n-1))
    return result
