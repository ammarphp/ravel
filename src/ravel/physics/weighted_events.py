"""Weighted integration points as events with named weights, and Rivet RAW normalization.

Export: every completed block of a Gram store becomes event files in which each
accepted point is one event with one named weight per stream (every hypothesis
and its signed difference to the reference). Weights are absolute: a stream's
weight is ``N * factor * Re(c^dagger G c)`` in pb, where N is the number of
attempted draws of the block, so the mean weight over the attempted draws is the
block's cross-section estimate (the Les Houches ``IDWTUP = -4`` convention).
Rejected draws carry zero weight and are not written. Large stream sets are
split into passes of at most ``max_streams`` streams; every pass carries the
reference stream as its nominal weight.

Formats: Les Houches event files (LHEF 3 named weights, for a shower) and HepMC3
ASCII (for Rivet directly, unshowered). HepMC3 events carry two beam particles
of the declared collision energy that split into the initial-state partons.

Normalization: Rivet routines usually scale a histogram by
``crossSection() / sumOfWeights()``. For a signed stream (an interference or a
difference) that ratio is meaningless. ``normalize_raw`` reads the unscaled
``/RAW/`` histograms of every stream instead and divides by the attempted draws
of the block, giving each bin in absolute units. Independent blocks then give
the mean and its covariance across every stream and bin jointly.
"""
from __future__ import annotations

import gzip
import math
from pathlib import Path
import re

import numpy as np

from . import amplitude_basis as ab
from . import amplitude_polynomial as polynomial
from . import amplitude_store as store

UNITS_PER_PB = {'fb': 1e3, 'pb': 1.0, 'nb': 1e-3}
_NAME = re.compile(r'^[A-Za-z0-9_.+-]{1,64}$')
HEPMC_VERSION = '3.02.06'


def _open(path, mode):
    path = Path(path)
    return gzip.open(path, mode + 't') if path.suffix == '.gz' else path.open(mode)


# ---------------------------------------------------------------- streams
def stream_names(hypothesis_ids, reference):
    """Event-file weight names: hypotheses, then '<id>-minus-<reference>' differences."""
    for h in hypothesis_ids:
        ab.require(isinstance(h, str) and _NAME.fullmatch(h), f'hypothesis id {h!r} must use letters, digits and _.+-')
    return [*ab.stream_names(hypothesis_ids, reference)[:len(hypothesis_ids)],
            *[f'{h}-minus-{reference}' for h in hypothesis_ids if h != reference]]


def passes(names, reference, max_streams=150):
    ab.require(type(max_streams) is int and max_streams >= 2, 'max_streams must be at least 2')
    ab.require(reference in names, 'the reference stream must be one of the streams')
    others = [n for n in names if n != reference]
    size = max_streams - 1
    return [[reference, *others[i:i + size]] for i in range(0, max(len(others), 1), size)]


def stream_weights(gram, s, basis, hypotheses, reference, *, document=None):
    """Per-point Re(c^dagger G c) for every hypothesis and difference (before the factor)."""
    values = {}
    for doc in hypotheses:
        values[doc['id']] = ab.evaluate(gram, ab.coefficients(doc, basis, s))
    out = dict(values)
    for doc in hypotheses:
        if doc['id'] != reference:
            out[f'{doc["id"]}-minus-{reference}'] = values[doc['id']] - values[reference]
    if document is not None:
        for _, name, fn in polynomial.definitions(document, basis, hypotheses):
            out[name] = fn(gram, s)
    return out


# ---------------------------------------------------------------- Les Houches
def _colours(pdg):
    """Colour lines for a colour-singlet final state from its two initial partons."""
    a, b = pdg[:2]
    if a == 21 and b == 21:
        return [(501, 502), (502, 501)]
    quark = lambda x: 1 <= abs(x) <= 6
    if quark(a) and quark(b) and a == -b:
        return [(501, 0), (0, 501)] if a > 0 else [(0, 501), (501, 0)]
    raise ValueError('event export supports gluon-gluon or quark-antiquark initial states with a colour-singlet final state')


def _initial(momentum):
    """Physical (positive-energy) incoming momentum from an all-outgoing one."""
    return [-x for x in momentum] if momentum[3] < 0 else list(momentum)


def write_lhe(path, events, *, particles, weight_names, nominal, beams, attempted, unit_note=''):
    """Write LHEF 3 events. ``events`` yields (momenta[P][4] all-outgoing, scale, weights{name: pb})."""
    pdg, status = particles['pdg'], particles['status']
    ab.require(status[:2] == [-1, -1] and all(s == 1 for s in status[2:]), 'particles: two incoming (-1) then outgoing (1)')
    colours = _colours(pdg)
    ab.require(nominal in weight_names, 'the nominal weight must be one of the weight names')
    for name in weight_names:
        ab.require(_NAME.fullmatch(name), f'weight name {name!r} must use letters, digits and _.+-')
    (b1, e1), (b2, e2) = beams
    rows = []
    totals = {n: 0.0 for n in weight_names}
    count = 0
    with _open(path, 'w') as out:
        out.write('<LesHouchesEvents version="3.0">\n<header>\n')
        out.write(f'<!-- RAVEL weighted points; mean weight over {attempted} attempted draws is the cross section in pb. {unit_note} -->\n')
        out.write('<initrwgt>\n<weightgroup name="ravel-streams">\n')
        for name in weight_names:
            out.write(f'<weight id="{name}"> {name} </weight>\n')
        out.write('</weightgroup>\n</initrwgt>\n</header>\n')
        body = []
        for momenta, scale, weights in events:
            count += 1
            for n in weight_names:
                totals[n] += weights[n]
            lines = [f'<event>\n {len(pdg)} 1 {weights[nominal]:.17e} {scale:.10e} -1.0 -1.0']
            for i, (pid, st, p) in enumerate(zip(pdg, status, momenta)):
                p = _initial(p) if st == -1 else list(p)
                mass = math.sqrt(max(p[3] ** 2 - p[0] ** 2 - p[1] ** 2 - p[2] ** 2, 0.0))
                c1, c2 = colours[i] if i < 2 else (0, 0)
                mothers = (0, 0) if st == -1 else (1, 2)
                lines.append(f' {pid} {st} {mothers[0]} {mothers[1]} {c1} {c2} {p[0]:.17e} {p[1]:.17e} {p[2]:.17e} {p[3]:.17e} {mass:.10e} 0. 9.')
            lines.append('<rwgt>')
            lines += [f'<wgt id="{n}"> {weights[n]:.17e} </wgt>' for n in weight_names]
            lines.append('</rwgt>\n</event>')
            body.append('\n'.join(lines) + '\n')
        xs = totals[nominal] / attempted
        out.write(f'<init>\n {b1} {b2} {e1:.10e} {e2:.10e} 0 0 -1 -1 -4 1\n {xs:.17e} 0.0 1.0 1\n</init>\n')
        out.writelines(body)
        out.write('</LesHouchesEvents>\n')
    return {'events': count, 'attempted': attempted, 'cross_section_pb': {n: totals[n] / attempted for n in weight_names}}


def read_lhe(path):
    """Read the events written by ``write_lhe`` (or any LHEF 3 file with named weights)."""
    text = _open(path, 'r').read()
    names = re.findall(r'<weight id="([^"]+)"', text)
    events = []
    for block in re.findall(r'<event>(.*?)</event>', text, flags=re.S):
        lines = [l for l in block.strip().splitlines() if l.strip()]
        head = lines[0].split()
        n = int(head[0])
        particles = []
        for line in lines[1:1 + n]:
            f = line.split()
            particles.append({'pdg': int(f[0]), 'status': int(f[1]), 'momentum': [float(x) for x in f[6:10]]})
        weights = dict(re.findall(r'<wgt id="([^"]+)">\s*([^<\s]+)\s*</wgt>', block))
        events.append({'weight': float(head[2]), 'scale': float(head[3]), 'particles': particles,
                       'weights': {k: float(v) for k, v in weights.items()}})
    init = re.search(r'<init>\s*(.*?)</init>', text, flags=re.S).group(1).split()
    return {'weight_names': names, 'events': events, 'idwtup': int(init[8]), 'cross_section_pb': float(init[10])}


# ---------------------------------------------------------------- HepMC3
def write_hepmc3(path, events, *, particles, weight_names, sqrt_s_gev, beam_pdg, attempted, cross_sections=None):
    """HepMC3 ASCII events: two beams, each splitting into one initial parton, then the final state."""
    pdg, status = particles['pdg'], particles['status']
    ab.require(status[:2] == [-1, -1] and all(s == 1 for s in status[2:]), 'particles: two incoming (-1) then outgoing (1)')
    for name in weight_names:
        ab.require(_NAME.fullmatch(name), f'weight name {name!r} must use letters, digits and _.+-')
    ebeam = float(sqrt_s_gev) / 2.0
    count = 0
    totals = {n: 0.0 for n in weight_names}
    with _open(path, 'w') as out:
        out.write(f'HepMC::Version {HEPMC_VERSION}\nHepMC::Asciiv3-START_EVENT_LISTING\n')
        out.write('W ' + ' '.join(weight_names) + '\n')
        for momenta, _scale, weights in events:
            nfinal = len(pdg) - 2
            out.write(f'E {count} 3 {4 + nfinal}\nU GEV MM\n')
            out.write('W ' + ' '.join(f'{weights[n]:.17e}' for n in weight_names) + '\n')
            if cross_sections is not None:
                xs = [cross_sections[n] for n in weight_names]
                extra = ''.join(f' {x:.17e} 0' for x in xs[1:])
                out.write(f'A 0 GenCrossSection {xs[0]:.17e} 0 -1 {attempted}{extra}\n')
            for n in weight_names:
                totals[n] += weights[n]
            out.write(f'P 1 0 {beam_pdg} 0 0 {ebeam:.17e} {ebeam:.17e} 0 4\n')
            out.write(f'P 2 0 {beam_pdg} 0 0 {-ebeam:.17e} {ebeam:.17e} 0 4\n')
            p1, p2 = _initial(momenta[0]), _initial(momenta[1])
            out.write(f'P 3 1 {pdg[0]} {p1[0]:.17e} {p1[1]:.17e} {p1[2]:.17e} {p1[3]:.17e} 0 21\n')
            out.write(f'P 4 2 {pdg[1]} {p2[0]:.17e} {p2[1]:.17e} {p2[2]:.17e} {p2[3]:.17e} 0 21\n')
            out.write('V -3 0 [3,4]\n')
            for i, (pid, p) in enumerate(zip(pdg[2:], momenta[2:])):
                mass = math.sqrt(max(p[3] ** 2 - p[0] ** 2 - p[1] ** 2 - p[2] ** 2, 0.0))
                out.write(f'P {5 + i} -3 {pid} {p[0]:.17e} {p[1]:.17e} {p[2]:.17e} {p[3]:.17e} {mass:.10e} 1\n')
            count += 1
        out.write('HepMC::Asciiv3-END_EVENT_LISTING\n')
    return {'events': count, 'attempted': attempted, 'cross_section_pb': {n: totals[n] / attempted for n in weight_names}}


def read_hepmc3(path):
    names, events, current = [], [], None
    with _open(path, 'r') as stream:
        for line in stream:
            f = line.split()
            if not f:
                continue
            if f[0] == 'W' and current is None:
                names = f[1:]
            elif f[0] == 'E':
                current = {'particles': [], 'weights': {}}
                events.append(current)
            elif f[0] == 'W':
                current['weights'] = dict(zip(names, map(float, f[1:])))
            elif f[0] == 'P':
                current['particles'].append({'id': int(f[1]), 'pdg': int(f[3]), 'momentum': [float(x) for x in f[4:8]],
                                             'status': int(f[9])})
    return {'weight_names': names, 'events': events}


# ---------------------------------------------------------------- export of a store
def block_events(path, basis, hypotheses, reference, *, s_observable, scale_observable, names, chunk_points=65536,
                 document=None):
    """Yield (momenta, scale, weights in pb) for every point of one completed block."""
    header = store.read_header(path)
    observables = header['observables']
    ab.require(s_observable in observables, f'observable {s_observable!r} is not stored')
    ab.require(scale_observable in observables, f'observable {scale_observable!r} is not stored')
    ab.require(header.get('particles') is not None, 'the store keeps no momenta; events cannot be written')
    to_pb = 1.0 / UNITS_PER_PB[header['factor_unit']]
    attempted = _attempted(path)
    i_s, i_q = observables.index(s_observable), observables.index(scale_observable)
    for chunk in store.iter_chunks(path, chunk_points):
        values = stream_weights(chunk['gram'], chunk['observables'][:, i_s], basis, hypotheses, reference, document=document)
        factor = chunk['factor'] * to_pb * attempted
        for j in range(len(factor)):
            yield (chunk['momenta'][j].tolist(), float(chunk['observables'][j, i_q]),
                   {n: float(factor[j] * values[n][j]) for n in names})


def _attempted(path):
    import json
    return json.loads(store.marker_path(path).read_text())['summary']['attempted']


# ---------------------------------------------------------------- Pythia
def pythia_card(lhe_path, settings):
    """Pythia command file for a signed, weighted LHEF 3 file; physics settings are declared data."""
    ab.require(type(settings) is list and all(isinstance(s, str) and '=' in s and '\n' not in s for s in settings),
               'shower settings must be "Key = value" lines')
    keys = [s.split('=', 1)[0].strip().lower() for s in settings]
    for forbidden in ('beams:frametype', 'beams:lhef', 'main:numberofevents'):
        ab.require(forbidden not in keys, f'{forbidden} is set by RAVEL')
    return '\n'.join(['Beams:frameType = 4', f'Beams:LHEF = {lhe_path}', *settings]) + '\n'


# ---------------------------------------------------------------- Rivet RAW
def read_yoda(text):
    """Histo1D objects of a YODA 2 text file: path -> edges, sumw, sumw2 and flows."""
    out = {}
    for path, body in re.findall(r'BEGIN YODA_HISTO1D_V3 (\S+)\n(.*?)END YODA_HISTO1D_V3', text, flags=re.S):
        edges = re.search(r'Edges\(A1\): \[([^\]]*)\]', body)
        ab.require(edges is not None, f'{path}: no edges')
        e = [float(x) for x in edges.group(1).split(',')]
        rows = [[float(x) for x in line.split()] for line in body.splitlines()
                if line.strip() and not line.startswith(('#', 'Path', 'Title', 'Type', '---', 'Edges'))]
        ab.require(len(rows) == len(e) + 1 and all(len(r) == 5 for r in rows), f'{path}: unexpected bin rows')
        rows = np.array(rows)
        out[path] = {'edges': e, 'sumw': rows[1:-1, 0], 'sumw2': rows[1:-1, 1],
                     'underflow': rows[0, 0], 'overflow': rows[-1, 0],
                     'underflow_sumw2': rows[0, 1], 'overflow_sumw2': rows[-1, 1]}
    return out


def raw_path(histogram, stream, nominal):
    """Rivet's RAW path of one histogram for one weight stream."""
    ab.require(histogram.startswith('/') and not histogram.startswith('/RAW/'), 'histogram path like /ANALYSIS/name')
    return f'/RAW{histogram}' if stream == nominal else f'/RAW{histogram}[{stream}]'


def normalize_raw(histos, *, histogram, streams, nominal, attempted, weight_unit='pb', unit='fb'):
    """Absolute per-bin values per stream: sum of weights in the bin / attempted draws."""
    ab.require(type(attempted) is int and attempted > 0, 'attempted draws must be a positive integer')
    scale = UNITS_PER_PB[unit] / UNITS_PER_PB[weight_unit] / attempted
    out, edges = {}, None
    for stream in streams:
        path = raw_path(histogram, stream, nominal)
        ab.require(path in histos, f'{path} is missing from the Rivet output')
        h = histos[path]
        ab.require(edges is None or h['edges'] == edges, f'{path} has different bin edges')
        edges = h['edges']
        out[stream] = {'values': (np.asarray(h['sumw']) * scale).tolist(),
                       'underflow': h['underflow'] * scale, 'overflow': h['overflow'] * scale}
    return {'edges': edges, 'unit': unit, 'streams': out}


def routine_scaled(raw, *, cross_section, sum_of_weights):
    """What a routine's ``scale(h, crossSection()/sumOfWeights())`` produces (for comparison only)."""
    return np.asarray(raw) * (cross_section / sum_of_weights)


def block_vector(normalized, streams):
    """Flatten one block: per stream, the bins then underflow and overflow."""
    rows = []
    for stream in streams:
        s = normalized['streams'][stream]
        rows += [*s['values'], s['underflow'], s['overflow']]
    return np.array(rows)


# ---------------------------------------------------------------- science mode
MODE = 'weighted-events'
SCOPE = 'weighted_points_particle_level_predictions'


def validate(task):
    ab.require(type(task) is dict and set(task) == {'input'} and isinstance(task['input'], str) and task['input'],
               'task needs exactly input (the document path)')
    return task


def load(task, base):
    """Mode document (``kind: weighted-events``)::

        {"schema_version": 1, "kind": "weighted-events", "operation": "export" | "rivet",
         "store": "store", "hypotheses": [...], "reference": "SM",
         "reference_description": "...", "invariant": "s_gev2", "scale": "factorization_scale_gev",
         "beams": {"pdg": 2212, "sqrt_s_gev": 13000.0}, "max_streams": 150, "format": "hepmc3" | "lhe",
         "unit": "fb",
         "shower": {"program": "pythia_shower", "settings": ["PartonLevel:MPI = off", ...]},   # optional
         "rivet": {"program": "rivet", "analyses": ["NAME"], "options": [],
                   "histograms": [{"path": "/NAME/d01-x01-y01", "label": "...", "unit": "GeV",
                                   "representation": "differential"}]},
         "backend": {"kind": "native", "resources": {...}, ...}}
    """
    validate(task)
    import json
    path = Path(task['input'])
    path = (path if path.is_absolute() else Path(base) / path).absolute()
    doc = json.loads(path.read_text())
    required = {'schema_version', 'kind', 'operation', 'store', 'hypotheses', 'reference', 'reference_description',
                'invariant', 'scale', 'beams', 'max_streams', 'format', 'unit'}
    optional = {'shower', 'rivet', 'backend', 'description', 'coupling_scaling', 'coupling_polynomial'}
    ab.require(type(doc) is dict and required <= set(doc) <= required | optional, 'document needs ' + ', '.join(sorted(required)))
    ab.require(doc['schema_version'] == 1 and doc['kind'] == MODE, f'schema_version 1 and kind {MODE} required')
    ab.require(doc['operation'] in ('export', 'rivet'), 'operation must be export or rivet')
    ab.require(doc['format'] in ('hepmc3', 'lhe'), 'format must be hepmc3 or lhe')
    ab.require(doc['unit'] in UNITS_PER_PB, f'unit must be one of {sorted(UNITS_PER_PB)}')
    ab.require(type(doc['beams']) is dict and set(doc['beams']) == {'pdg', 'sqrt_s_gev'}, 'beams need pdg and sqrt_s_gev')
    ab.real(doc['beams']['sqrt_s_gev'], 'sqrt_s_gev')
    store_dir = (path.parent / doc['store']).absolute()
    manifest = store.store_blocks(store_dir)
    ab.require(manifest['status'] == 'complete', 'the store is incomplete; resume its schedule first')
    basis = ab.Basis.from_document(manifest['header']['basis'])
    hyps = [ab.hypothesis(h, basis) for h in doc['hypotheses']]
    names = stream_names([h['id'] for h in hyps], doc['reference'])
    names += [t['weight'] for terms in polynomial.terms(doc, hyps).values() for t in terms]
    ab.require(len(set(names)) == len(names) and all(_NAME.fullmatch(n) for n in names),
               'distinct portable weight names of at most 64 characters required')
    groups = passes(names, doc['reference'], doc['max_streams'])
    if doc['operation'] == 'rivet':
        ab.require('rivet' in doc and 'backend' in doc, 'the rivet operation needs rivet and backend')
        r = doc['rivet']
        ab.require(type(r) is dict and set(r) == {'program', 'analyses', 'options', 'histograms'}, 'rivet needs program, analyses, options and histograms')
        ab.require(r['analyses'] and all(isinstance(a, str) and _NAME.fullmatch(a) for a in r['analyses']), 'analyses are routine names')
        ab.require(all(isinstance(o, str) and o.startswith('--') and o not in ('--skip-weights',) for o in r['options']),
                   'rivet options are long flags; --skip-weights is refused because every stream is needed')
        for h in r['histograms']:
            ab.require(type(h) is dict and set(h) == {'path', 'label', 'unit', 'representation'}
                       and h['representation'] in ('integrated', 'differential'), 'histograms need path, label, unit and representation')
        if doc['format'] == 'lhe':
            ab.require('shower' in doc, 'LHE events reach Rivet through the declared shower')
        if 'shower' in doc:
            pythia_card('events.lhe', doc['shower']['settings'])
            ab.require(doc['format'] == 'lhe', 'the shower reads LHE events')
    return {'path': path, 'doc': doc, 'store': store_dir, 'manifest': manifest, 'basis': basis, 'hypotheses': hyps,
            'names': names, 'passes': groups}


def inputs(task, base):
    ctx = load(task, base)
    files = [ctx['path'], ctx['store'] / store.MANIFEST]
    for row in ctx['manifest']['blocks']:
        files += [ctx['store'] / row['path'], store.marker_path(ctx['store'] / row['path'])]
    return files


def export(ctx, out):
    """Event files for every block and pass; returns rows with paths and attempted draws."""
    doc = ctx['doc']
    rows = []
    for block in ctx['manifest']['blocks']:
        path = ctx['store'] / block['path']
        header = store.read_header(path)
        attempted = block['summary']['attempted']
        for k, group in enumerate(ctx['passes']):
            events = list(block_events(path, ctx['basis'], ctx['hypotheses'], doc['reference'], s_observable=doc['invariant'],
                                       scale_observable=doc['scale'], names=group, document=doc))
            target = out / 'events' / block['id'] / (f'pass-{k}.hepmc' if doc['format'] == 'hepmc3' else f'pass-{k}.lhe')
            target.parent.mkdir(parents=True, exist_ok=True)
            if doc['format'] == 'hepmc3':
                xs = {n: sum(e[2][n] for e in events) / attempted for n in group}
                receipt = write_hepmc3(target, events, particles=header['particles'], weight_names=group,
                                       sqrt_s_gev=doc['beams']['sqrt_s_gev'], beam_pdg=doc['beams']['pdg'],
                                       attempted=attempted, cross_sections=xs)
            else:
                e = doc['beams']['sqrt_s_gev'] / 2
                receipt = write_lhe(target, events, particles=header['particles'], weight_names=group, nominal=doc['reference'],
                                    beams=((doc['beams']['pdg'], e), (doc['beams']['pdg'], e)), attempted=attempted)
            rows.append({'block': block['id'], 'cohort': block['cohort'], 'pass': k, 'streams': group, 'path': str(target),
                         'attempted': attempted, 'events': receipt['events']})
    return rows


def _spec(ctx, name, argv, stage_dir, files, outputs, base):
    be = ctx['doc']['backend']
    workdir = be.get('workdir')
    spec = {'schema_version': 1, 'backend': be['kind'], 'stage': name, 'argv': argv,
            'inputs': [{'path': str(stage_dir / f), **({'mount': f'{workdir}/{f}'} if workdir else {})} for f in files],
            'outputs': [{'name': o, 'destination': str((stage_dir / o).relative_to(base))} for o in outputs],
            'resources': dict(be['resources'])}
    for key in ('image', 'readonly_trees', 'env', 'workdir', 'site'):
        if key in be:
            spec[key] = be[key]
    return spec


def rivet_rows(ctx, rows, out, backend=None):
    """Run (shower and) Rivet per event file through the backend; return parsed RAW histograms per row."""
    import shutil
    from . import backend_driver
    doc = ctx['doc']
    r = doc['rivet']
    results = []
    for row in rows:
        stage_dir = out / 'stages' / f'{row["block"]}-pass-{row["pass"]}'
        stage_dir.mkdir(parents=True, exist_ok=True)
        events = 'events.hepmc'
        if doc['format'] == 'lhe':
            shutil.copyfile(row['path'], stage_dir / 'events.lhe')
            from ravel.validation.lhe_check import check_science
            check_science(stage_dir / 'events.lhe', output=stage_dir / 'events.lhe_check.json')
            (stage_dir / 'shower.cmnd').write_text(pythia_card('events.lhe', doc['shower']['settings']))
            spec = _spec(ctx, f'shower-{row["block"]}-{row["pass"]}', [doc['shower']['program'], 'shower.cmnd', events,
                         str(row['events'])], stage_dir, ['events.lhe', 'shower.cmnd'], [events], out)
            backend_driver.drive(spec, stage_dir / 'backend-shower', out, backend=backend)
        else:
            shutil.copyfile(row['path'], stage_dir / events)
        argv = [r['program'], *[x for a in r['analyses'] for x in ('-a', a)], *r['options'], '-o', 'rivet.yoda', events]
        spec = _spec(ctx, f'rivet-{row["block"]}-{row["pass"]}', argv, stage_dir, [events], ['rivet.yoda'], out)
        backend_driver.drive(spec, stage_dir / 'backend-rivet', out, backend=backend)
        results.append({**row, 'histograms': read_yoda((stage_dir / 'rivet.yoda').read_text())})
    return results


def predictions(ctx, results):
    """Mean and joint block covariance of every declared histogram and stream."""
    doc = ctx['doc']
    out = {}
    for spec in doc['rivet']['histograms']:
        cohorts, edges, census = {}, None, []
        expected_rows = {(b['id'], k) for b in ctx['manifest']['blocks'] for k in range(len(ctx['passes']))}
        ab.require(len(results) == len(expected_rows) and {(r['block'], r['pass']) for r in results} == expected_rows,
                   'RAW block/pass exposure roster differs')
        for block in ctx['manifest']['blocks']:
            ab.require(block['summary']['failed'] == 0, 'RAW block contains failed draws')
            vector = []
            for k, group in enumerate(ctx['passes']):
                row = next(x for x in results if x['block'] == block['id'] and x['pass'] == k)
                ab.require(row['attempted'] == block['summary']['attempted'] and row['cohort'] == block['cohort']
                           and row['streams'] == group and row['events'] == block['points'],
                           'RAW attempted-draw exposure or stream pass differs')
                streams = [s for s in group if k == 0 or s != doc['reference']]
                norm = normalize_raw(row['histograms'], histogram=spec['path'], streams=streams, nominal=doc['reference'],
                                     attempted=row['attempted'], unit=doc['unit'])
                ab.require(edges is None or edges == norm['edges'], 'RAW bin edges differ across blocks or passes')
                edges = norm['edges']
                vector.append(block_vector(norm, streams))
            cohorts.setdefault(block['cohort'], []).append(np.concatenate(vector))
            census.append({'id': block['id'], 'cohort': block['cohort'], 'attempted': block['summary']['attempted'],
                           'events': block['points']})
        joint = ab.centered_blocks(cohorts)
        nb = len(edges) - 1
        divide = np.diff(edges) if spec['representation'] == 'differential' else np.ones(nb)
        streams = {}
        for j, name in enumerate(ctx['names']):
            sl = slice(j * (nb + 2), (j + 1) * (nb + 2))
            cov = joint['covariance'][sl, sl][:nb, :nb] / np.outer(divide, divide)
            mean = joint['mean'][sl]
            streams[name] = {'values': (mean[:nb] / divide).tolist(), 'underflow': float(mean[nb]), 'overflow': float(mean[nb + 1]),
                             'mc_covariance': cov.tolist(), 'uncertainty': np.sqrt(np.clip(np.diag(cov), 0, None)).tolist()}
        out[spec['path']] = {'edges': edges, 'streams': streams, 'joint_covariance': joint['covariance'].tolist(), 'spec': spec,
                            'joint_layout': {'streams': ctx['names'], 'per_stream': 'bins, underflow, overflow',
                                             'units': 'integrated (not divided by bin width)'},
                            'covariance_semantics': joint['semantics'], 'blocks': census,
                            'provenance': {'stage': 'rivet-selected', 'showered': 'shower' in doc, 'histogram': spec['path'],
                                           'normalization': 'RAW/attempted-draws', 'weight_unit': 'pb',
                                           'unit': doc['unit'], 'representation': spec['representation']}}
    return out


def _binned(spec, edges, name, stream, unit):
    unit = unit + ('/' + spec['unit'] if spec['representation'] == 'differential' else '')
    return {'schema_version': 1, 'kind': 'binned_values', 'axes': [{'name': spec['label'], 'unit': spec['unit']}],
            'unit': unit, 'representation': spec['representation'],
            'bins': [{'low': [lo], 'high': [hi], 'value': v, 'uncertainty': u}
                     for lo, hi, v, u in zip(edges[:-1], edges[1:], stream['values'], stream['uncertainty'])],
            'underflow': stream['underflow'], 'overflow': stream['overflow'],
            'description': f'{name}: Rivet RAW histogram normalized by attempted draws'}


def run(task, base, output, *, backend=None):
    import json
    ctx = load(task, base)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    rows = export(ctx, out)
    (out / 'events.json').write_text(json.dumps({'unit': 'pb (mean over attempted draws is the cross section)',
                                                 'files': rows}, indent=2) + '\n')
    result = {'schema_version': 1, 'mode': MODE, 'status': 'passed', 'status_scope': SCOPE, 'physics_validated': False,
              'files': len(rows), 'summary': [f'{len(rows)} event files for {len(ctx["names"])} streams.']}
    if ctx['doc']['operation'] == 'rivet':
        results = rivet_rows(ctx, rows, out, backend)
        preds = predictions(ctx, results)
        doc = ctx['doc']
        for path, pred in preds.items():
            stem = path.strip('/').replace('/', '--')
            folder = out / 'binned' / stem
            folder.mkdir(parents=True, exist_ok=True)
            for name, stream in pred['streams'].items():
                (folder / f'{name}.json').write_text(json.dumps(_binned(pred['spec'], pred['edges'], name, stream, doc['unit']), indent=2) + '\n')
            fragment = {'schema_version': 1, 'kind': 'differential-likelihood-input',
                        'signal': {'convention': 'difference-to-reference', 'difference_reference': doc['reference_description']},
                        'hypotheses': [{'id': h['id'], 'coordinates': {}, 'terms': [
                            {'powers': {}, 'values': pred['streams'][f'{h["id"]}-minus-{doc["reference"]}']['values'], 'kind': 'other'}],
                            'mc_covariance': pred['streams'][f'{h["id"]}-minus-{doc["reference"]}']['mc_covariance']}
                            for h in ctx['hypotheses'] if h['id'] != doc['reference']],
                        'reference_prediction': {'values': pred['streams'][doc['reference']]['values'],
                                                 'description': doc['reference_description']}}
            if doc.get('coupling_scaling') or doc.get('coupling_polynomial'):
                from . import rivet_fit
                selected = rivet_fit.selected_prediction(doc, ctx['hypotheses'], pred)
                fragment = rivet_fit.likelihood_input(doc, ctx['hypotheses'], selected)
            (folder / 'differential-likelihood-input.json').write_text(json.dumps(fragment, indent=2) + '\n')
        (out / 'predictions.json').write_text(json.dumps({p: {k: v for k, v in x.items() if k != 'spec'} for p, x in preds.items()},
                                                         indent=2) + '\n')
        result['summary'].append(f'{len(preds)} Rivet histograms normalized from RAW over {len(ctx["manifest"]["blocks"])} blocks.')
    (out / 'weighted-events.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
