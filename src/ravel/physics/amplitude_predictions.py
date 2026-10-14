"""Science mode ``amplitude-predictions``: binned predictions for any hypothesis from a Gram store.

The measurement is supplied data: the observable, its bin edges (literal or read
from a HEPData table), point-level selection cuts on stored observables, the
representation (integrated or differential) and any cited normalization factor.
No analysis, table or edge is built in. A Rivet routine as the fiducial
definition goes through ``weighted-events`` instead.

Input document (``kind: amplitude-predictions``)::

    {"schema_version": 1, "kind": "amplitude-predictions",
     "store": "store",                       # directory with manifest.json
     "hypotheses": [<amplitude_basis hypothesis>, ...], "reference": "SM",
     "reference_description": "Standard Model continuum and 125 GeV Higgs boson",
     "observable": {"name": "mass_gev", "label": "Four-lepton invariant mass", "unit": "GeV",
                    "invariant": "s_gev2"},
     "binning": {"edges": [...]} | {"hepdata": {"path": "table.yaml", "sha256": "...", "variable": 0}},
     "selection": [{"observable": "mass_gev", "min": 70.0, "max": null}],
     "normalization": {"unit": "fb", "representation": "differential",
                       "factor": {"value": 1.0, "source": "..."}},
     "coupling_scaling": {"parameter": "kappa", "power": 1, "states": [1], "mc_covariance_at": 1.0}}

``invariant`` names the stored observable holding the partonic invariant s that
the propagators use. Each block contributes its histogram of every stream (each
hypothesis, and each hypothesis minus the reference); blocks of one cohort are
independent equal-exposure estimates, and cohorts (for example separately
integrated channels) add. With ``coupling_scaling`` the listed states scale as
kappa^power, and each hypothesis difference is decomposed exactly into a
constant, an interference (kappa^power) and a pure-signal (kappa^(2 power)) term.

Outputs: ``predictions.json`` (all streams, flows, the joint covariance and
census), ``binned/<stream>.json`` (RAVEL ``binned_values`` results) and
``differential-likelihood-input.json`` (the signal and hypotheses blocks of a
``differential-likelihood`` document).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from . import amplitude_basis as ab
from . import amplitude_store as store

MODE = 'amplitude-predictions'
SCOPE = 'amplitude_basis_binned_predictions'
REPRESENTATIONS = ('integrated', 'differential')
UNITS = ('fb', 'pb', 'nb')
_SCALE = {'fb': 1e3, 'pb': 1.0, 'nb': 1e-3}


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _regular(path, root):
    p = Path(path)
    p = p if p.is_absolute() else Path(root) / p
    p = p.absolute()
    ab.require(not any(q.is_symlink() for q in (p, *p.parents)), f'{p} must not traverse a symlink')
    return p


def _document(task, base):
    ab.require(type(task) is dict and set(task) == {'input'}, 'task needs exactly input (the document path)')
    path = _regular(task['input'], base)
    ab.require(path.is_file(), f'{path} is not a file')
    return path, json.loads(path.read_text())


def _edges(binning, root):
    ab.require(type(binning) is dict and len(binning) == 1 and set(binning) <= {'edges', 'hepdata'},
               'binning needs edges or hepdata')
    if 'edges' in binning:
        return ab.edges_from(binning['edges']), []
    from . import source_tables
    spec = binning['hepdata']
    ab.require(type(spec) is dict and {'path', 'sha256'} <= set(spec) <= {'path', 'sha256', 'variable'},
               'hepdata binning needs path and sha256 (and optional variable)')
    path = _regular(spec['path'], root)
    table = source_tables.read_table_snapshot(path.read_bytes(), {'path': str(path), 'sha256': spec['sha256']})
    axes = table['payload']['independent_variables']
    index = spec.get('variable', 0)
    ab.require(type(index) is int and 0 <= index < len(axes), 'hepdata variable index out of range')
    rows = axes[index]['values']
    edges = [float(source_tables.number(rows[0]['low']))]
    for row in rows:
        low, high = float(source_tables.number(row['low'])), float(source_tables.number(row['high']))
        ab.require(low == edges[-1], 'hepdata bins must be contiguous')
        edges.append(high)
    return ab.edges_from(edges), [path]


def load(task, base):
    path, doc = _document(task, base)
    root = path.parent
    required = {'schema_version', 'kind', 'store', 'hypotheses', 'reference', 'reference_description', 'observable',
                'binning', 'selection', 'normalization'}
    ab.require(type(doc) is dict and required <= set(doc) <= required | {'coupling_scaling', 'description'},
               'document needs ' + ', '.join(sorted(required)) + ' (optional coupling_scaling, description)')
    ab.require(doc['schema_version'] == 1 and doc['kind'] == MODE, f'schema_version 1 and kind {MODE} required')
    store_dir = _regular(doc['store'], root)
    manifest = store.store_blocks(store_dir)
    ab.require(manifest['status'] == 'complete', 'the store is incomplete; resume its schedule first')
    header = manifest['header']
    basis = ab.Basis.from_document(header['basis'])
    hyps = [ab.hypothesis(h, basis) for h in doc['hypotheses']]
    ids = [h['id'] for h in hyps]
    ab.stream_names(ids, doc['reference'])
    ab.text(doc['reference_description'], 'reference_description')
    obs = doc['observable']
    ab.require(type(obs) is dict and set(obs) == {'name', 'label', 'unit', 'invariant'},
               'observable needs name, label, unit and invariant')
    for key in ('name', 'label', 'unit', 'invariant'):
        ab.text(obs[key], f'observable {key}')
    for key in ('name', 'invariant'):
        ab.require(obs[key] in header['observables'], f'observable {obs[key]!r} is not stored in the blocks')
    edges, tables = _edges(doc['binning'], root)
    ab.require(type(doc['selection']) is list, 'selection is a list of cuts (empty for none)')
    for cut in doc['selection']:
        ab.require(type(cut) is dict and set(cut) == {'observable', 'min', 'max'}, 'a cut needs observable, min and max')
        ab.require(cut['observable'] in header['observables'], f'cut observable {cut["observable"]!r} is not stored')
        for key in ('min', 'max'):
            if cut[key] is not None:
                ab.real(cut[key], f'cut {key}')
    norm = doc['normalization']
    ab.require(type(norm) is dict and {'unit', 'representation'} <= set(norm) <= {'unit', 'representation', 'factor'},
               'normalization needs unit and representation (optional factor)')
    ab.require(norm['unit'] in UNITS and norm['representation'] in REPRESENTATIONS,
               f'normalization unit in {UNITS}, representation in {REPRESENTATIONS}')
    if 'factor' in norm:
        f = norm['factor']
        ab.require(type(f) is dict and set(f) == {'value', 'source'}, 'a normalization factor needs value and source')
        ab.real(f['value'], 'normalization factor')
        ab.text(f['source'], 'normalization factor source')
    scaling = doc.get('coupling_scaling')
    if scaling is not None:
        ab.require(type(scaling) is dict and set(scaling) == {'parameter', 'power', 'states', 'mc_covariance_at'},
                   'coupling_scaling needs parameter, power, states and mc_covariance_at')
        ab.text(scaling['parameter'], 'coupling parameter')
        ab.require(type(scaling['power']) is int and 1 <= scaling['power'] <= 8, 'coupling power from 1 to 8')
        ab.require(type(scaling['states']) is list and scaling['states'] and all(type(i) is int and i >= 0 for i in scaling['states']),
                   'states lists the indices of the scaled states')
        ab.real(scaling['mc_covariance_at'], 'mc_covariance_at')
        ref = next(h for h in hyps if h['id'] == doc['reference'])
        ab.require(not any(i < len(ref['states']) for i in scaling['states']), 'the reference hypothesis cannot contain scaled states')
    return {'path': path, 'doc': doc, 'store': store_dir, 'manifest': manifest, 'basis': basis, 'hypotheses': hyps,
            'edges': edges, 'tables': tables}


def validate(task):
    ab.require(type(task) is dict and set(task) == {'input'} and isinstance(task['input'], str) and task['input'],
               'task needs exactly input (the document path)')
    return task


def inputs(task, base):
    ctx = load(task, base)
    files = [ctx['path'], ctx['store'] / store.MANIFEST, *ctx['tables']]
    for row in ctx['manifest']['blocks']:
        files += [ctx['store'] / row['path'], store.marker_path(ctx['store'] / row['path'])]
    return files


def _split(doc, indices):
    """Hypothesis with only the unscaled states, and the scaled states alone."""
    keep = [s for i, s in enumerate(doc['states']) if i not in indices]
    scaled = [s for i, s in enumerate(doc['states']) if i in indices]
    return {**doc, 'states': keep}, {'id': doc['id'], 'constant': {}, 'states': scaled}


def streams(ctx):
    """Stream definitions: (name, kind, function of (gram, s) -> per-point weight)."""
    doc, basis, hyps = ctx['doc'], ctx['basis'], ctx['hypotheses']
    reference = next(h for h in hyps if h['id'] == doc['reference'])
    rows = []

    def quad(h):
        return lambda G, s: ab.evaluate(G, ab.coefficients(h, basis, s))

    rows += [(h['id'], 'prediction', quad(h)) for h in hyps]
    rows += [(f'{h["id"]}-minus-{reference["id"]}', 'difference',
              (lambda h: lambda G, s: quad(h)(G, s) - quad(reference)(G, s))(h)) for h in hyps if h is not reference]
    scaling = doc.get('coupling_scaling')
    if scaling is not None:
        for h in hyps:
            if h is reference or not any(i < len(h['states']) for i in scaling['states']):
                continue
            fixed, scaled = _split(h, scaling['states'])

            def interference(G, s, fixed=fixed, scaled=scaled):
                c0, c1 = ab.coefficients(fixed, basis, s), ab.coefficients(scaled, basis, s)
                return 2.0 * np.einsum('nk,nkl,nl->n', np.conj(c0), G, c1).real
            rows.append((f'{h["id"]}:constant', 'term', (lambda f: lambda G, s: quad(f)(G, s) - quad(reference)(G, s))(fixed)))
            rows.append((f'{h["id"]}:interference', 'term', interference))
            rows.append((f'{h["id"]}:pure-signal', 'term', (lambda sc: lambda G, s: quad(sc)(G, s) if sc['states'] else 0 * s)(scaled)))
    return rows


def block_vectors(ctx, definitions):
    doc = ctx['doc']
    header = ctx['manifest']['header']
    names = header['observables']
    i_obs, i_s = names.index(doc['observable']['name']), names.index(doc['observable']['invariant'])
    cuts = [(names.index(c['observable']), c['min'], c['max']) for c in doc['selection']]
    to_unit = _SCALE[doc['normalization']['unit']] / _SCALE[header['factor_unit']]
    factor = to_unit * (doc['normalization'].get('factor', {}).get('value', 1.0))
    width = len(ctx['edges']) + 1
    cohorts, census = {}, []
    for row in ctx['manifest']['blocks']:
        ab.require(row['summary']['failed'] == 0, f'block {row["id"]} has failed draws; a failed draw is not a zero')
        vector = np.zeros(len(definitions) * width)
        selected = 0
        for chunk in store.iter_chunks(ctx['store'] / row['path']):
            obs = chunk['observables']
            mask = np.ones(len(obs), dtype=bool)
            for i, lo, hi in cuts:
                if lo is not None:
                    mask &= obs[:, i] >= lo
                if hi is not None:
                    mask &= obs[:, i] < hi
            if not mask.any():
                continue
            selected += int(mask.sum())
            G, s, x = chunk['gram'][mask], obs[mask, i_s], obs[mask, i_obs]
            w0 = chunk['factor'][mask] * factor
            for j, (_, _, fn) in enumerate(definitions):
                vector[j * width:(j + 1) * width] += ab.histogram(x, w0 * fn(G, s), ctx['edges'])
        cohorts.setdefault(row['cohort'], []).append(vector)
        census.append({'id': row['id'], 'cohort': row['cohort'], 'points': row['points'], 'selected': selected,
                       **row['summary']})
    return cohorts, census


def predict(ctx):
    definitions = streams(ctx)
    cohorts, census = block_vectors(ctx, definitions)
    joint = ab.centered_blocks(cohorts)
    edges = ctx['edges']
    nb = len(edges) - 1
    width = nb + 2
    differential = ctx['doc']['normalization']['representation'] == 'differential'
    divide = np.diff(edges) if differential else np.ones(nb)
    out = {}
    for j, (name, kind, _) in enumerate(definitions):
        sl = slice(j * width, (j + 1) * width)
        mean = joint['mean'][sl]
        cov = joint['covariance'][sl, sl][:nb, :nb] / np.outer(divide, divide)
        out[name] = {'kind': kind, 'values': (mean[:nb] / divide).tolist(), 'underflow': float(mean[nb]),
                     'overflow': float(mean[nb + 1]), 'mc_covariance': cov.tolist(),
                     'uncertainty': np.sqrt(np.clip(np.diag(cov), 0, None)).tolist()}
    return {'streams': out, 'definitions': [(n, k) for n, k, _ in definitions], 'joint': joint, 'census': census,
            'divide': divide}


def binned_values(ctx, name, stream):
    doc = ctx['doc']
    obs, norm = doc['observable'], doc['normalization']
    unit = norm['unit'] + ('/' + obs['unit'] if norm['representation'] == 'differential' else '')
    edges = ctx['edges']
    return {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': obs['label'], 'unit': obs['unit']}],
            'unit': unit, 'representation': norm['representation'],
            'bins': [{'low': [float(lo)], 'high': [float(hi)], 'value': v, 'uncertainty': u}
                     for lo, hi, v, u in zip(edges[:-1], edges[1:], stream['values'], stream['uncertainty'])],
            'underflow': stream['underflow'], 'overflow': stream['overflow'],
            'description': f'{name}: amplitude-basis prediction ({stream["kind"]}); flows are integrated {norm["unit"]}'}


def likelihood_input(ctx, prediction):
    doc = ctx['doc']
    ref = doc['reference']
    scaling = doc.get('coupling_scaling')
    rows = []
    for h in ctx['hypotheses']:
        if h['id'] == ref:
            continue
        name = f'{h["id"]}-minus-{ref}'
        terms_present = scaling is not None and f'{h["id"]}:interference' in prediction['streams']
        if terms_present:
            p, k = scaling['power'], scaling['parameter']
            terms = [{'powers': {}, 'values': prediction['streams'][f'{h["id"]}:constant']['values'], 'kind': 'other'},
                     {'powers': {k: p}, 'values': prediction['streams'][f'{h["id"]}:interference']['values'], 'kind': 'interference'},
                     {'powers': {k: 2 * p}, 'values': prediction['streams'][f'{h["id"]}:pure-signal']['values'], 'kind': 'pure-signal'}]
            kappa = scaling['mc_covariance_at']
            cov = _term_covariance(ctx, prediction, h['id'], kappa, p)
        else:
            terms = [{'powers': {}, 'values': prediction['streams'][name]['values'], 'kind': 'other'}]
            cov = prediction['streams'][name]['mc_covariance']
        rows.append({'id': h['id'], 'coordinates': _coordinates(h), 'terms': terms, 'mc_covariance': cov})
    signal = {'convention': 'difference-to-reference', 'difference_reference': doc['reference_description']}
    if scaling is not None:
        signal['parameters'] = [{'name': scaling['parameter'], 'unit': '', 'label': 'Coupling scale factor'}]
    return {'schema_version': 1, 'kind': 'differential-likelihood-input', 'signal': signal, 'hypotheses': rows,
            'reference_prediction': {'values': prediction['streams'][ref]['values'], 'description': doc['reference_description']},
            'note': 'MC covariance of each difference; with coupling scaling it is evaluated at mc_covariance_at.'}


def _term_covariance(ctx, prediction, hid, kappa, power):
    """MC covariance of constant + kappa^p interference + kappa^2p pure signal, bins only."""
    names = [n for n, _ in prediction['definitions']]
    nb = len(ctx['edges']) - 1
    width = nb + 2
    weights = {f'{hid}:constant': 1.0, f'{hid}:interference': kappa ** power, f'{hid}:pure-signal': kappa ** (2 * power)}
    C = prediction['joint']['covariance']
    total = np.zeros((nb, nb))
    for a, wa in weights.items():
        ia = names.index(a) * width
        for b, wb in weights.items():
            ib = names.index(b) * width
            total += wa * wb * C[ia:ia + nb, ib:ib + nb]
    return (total / np.outer(prediction['divide'], prediction['divide'])).tolist()


def _coordinates(h):
    out = {}
    for i, state in enumerate(h['states']):
        out[f'state{i}_mass_gev'] = state['mass_gev']
        out[f'state{i}_width_gev'] = state['width_gev']
    return out


def run(task, base, output):
    ctx = load(task, base)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    prediction = predict(ctx)
    (out / 'binned').mkdir(exist_ok=True)
    written = []
    for name, stream in prediction['streams'].items():
        path = out / 'binned' / (name.replace(':', '--') + '.json')
        path.write_text(json.dumps(binned_values(ctx, name, stream), indent=2) + '\n')
        written.append(str(path))
    likelihood = likelihood_input(ctx, prediction)
    (out / 'differential-likelihood-input.json').write_text(json.dumps(likelihood, indent=2) + '\n')
    joint = prediction['joint']
    record = {'schema_version': 1, 'mode': MODE, 'status': 'passed', 'status_scope': SCOPE, 'physics_validated': False,
              'edges': ctx['edges'].tolist(), 'observable': ctx['doc']['observable'],
              'normalization': ctx['doc']['normalization'], 'selection': ctx['doc']['selection'],
              'streams': {n: {k: v for k, v in s.items() if k != 'mc_covariance'} for n, s in prediction['streams'].items()},
              'joint_layout': {'streams': [n for n, _ in prediction['definitions']], 'per_stream': 'bins, underflow, overflow',
                               'units': 'integrated (not divided by bin width)'},
              'joint_covariance': joint['covariance'].tolist(), 'covariance_semantics': joint['semantics'],
              'blocks': prediction['census'],
              'inputs': [{'path': str(p), 'sha256': _sha256(p)} for p in inputs(task, base)]}
    (out / 'predictions.json').write_text(json.dumps(record, indent=2) + '\n')
    summary = [f'{len(prediction["streams"])} streams in {len(ctx["edges"]) - 1} bins from {len(prediction["census"])} blocks.']
    return {'status': 'passed', 'status_scope': SCOPE, 'physics_validated': False, 'summary': summary,
            'outputs': ['predictions.json', 'differential-likelihood-input.json', *[str(Path(p).relative_to(out)) for p in written]],
            'limitations': ['Predictions are exact recombinations of the stored points; their accuracy is that of the '
                            'amplitudes, integration and selection that produced the store.',
                            'The covariance is the centered estimate from independent blocks, not a calibrated coverage.']}
