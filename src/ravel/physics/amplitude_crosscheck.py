"""Science mode ``amplitude-crosscheck``: compare stored recombinations with an independent matrix-element program.

The independent program is JHUGen/MELA, run only through the execution backend
(normally a digest-pinned container). RAVEL writes the points of one stored
block, a small driver script and the declared MELA configuration into a stage
directory; the stage returns one squared matrix element per point. The
comparison fits one constant normalization (the programs use different overall
constants and coupling conventions) and reports the largest relative deviation
from it. Agreement within the declared tolerance supports the phase and coupling
conventions of the stored amplitudes; it does not certify either program.

MELA settings are supplied data: the process, matrix-element and production
names, resonance masses and widths, and coupling attributes are applied by name.
The driver calls only ``computeP``; ``compute4FermionWeight`` is refused because
it changes the event weight definition.

Input document (``kind: amplitude-crosscheck``)::

    {"schema_version": 1, "kind": "amplitude-crosscheck", "store": "store", "block": "mixed-0",
     "max_points": 200, "tolerance": 1e-3,
     "hypothesis": <amplitude_basis hypothesis>,
     "mela": {"sqrts_tev": 13, "reference_mass_gev": 125.0, "verbosity": "ERROR",
              "process": ["bkgZZ_SMHiggs", "JHUGen", "ZZGG"],
              "resonances": [{"index": 0, "mass_gev": 125.0, "width_gev": 0.004}],
              "couplings": {"ghz1": [2.0, 0.0]}, "call": "computeP"},
     "backend": {"kind": "oci-local", "program": "python3", "workdir": "/work", "image": {...},
                 "resources": {"cpus": 1, "memory_mib": 2048, "wall_seconds": 600}}}
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import numpy as np

from . import amplitude_basis as ab
from . import amplitude_store as store
from . import backend_driver

MODE = 'amplitude-crosscheck'
SCOPE = 'amplitude_basis_independent_crosscheck'
ALLOWED_CALLS = ('computeP',)
FORBIDDEN = ('compute4FermionWeight',)
_ATTRIBUTE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')

DRIVER = r'''"""RAVEL driver for JHUGen/MELA point evaluation (runs inside the cross-check stage)."""
import json
import sys

import ROOT  # noqa: F401  (MELA's Python bindings need ROOT's TLorentzVector)
from Mela import Mela, SimpleParticle_t, SimpleParticleCollection_t, TVar


def vector(p):
    return ROOT.TLorentzVector(p[0], p[1], p[2], p[3])


def main(points_path, config_path, out_path):
    points = json.load(open(points_path))
    config = json.load(open(config_path))
    if config["call"] != "computeP":
        raise SystemExit("only computeP is allowed")
    mela = Mela(config["sqrts_tev"], config["reference_mass_gev"], getattr(TVar, config["verbosity"]))
    values = []
    for row in points["points"]:
        momenta, pdg = row["momenta"], points["pdg"]
        mothers = SimpleParticleCollection_t([SimpleParticle_t(pdg[i], vector([-x for x in momenta[i]])) for i in (0, 1)])
        daughters = SimpleParticleCollection_t([SimpleParticle_t(pdg[i], vector(momenta[i])) for i in range(2, len(pdg))])
        mela.setInputEvent(daughters, SimpleParticleCollection_t(), mothers, True)
        mela.setProcess(*[getattr(TVar, name) for name in config["process"]])
        for r in config["resonances"]:
            mela.setMelaHiggsMassWidth(r["mass_gev"], r["width_gev"], r["index"])
        for name, value in config["couplings"].items():
            setattr(mela, name, value)
        values.append(float(mela.computeP(False)))
        mela.resetInputEvent()
    json.dump({"values": values}, open(out_path, "w"))


if __name__ == "__main__":
    main(*sys.argv[1:4])
'''


def validate_mela(config):
    required = {'sqrts_tev', 'reference_mass_gev', 'verbosity', 'process', 'resonances', 'couplings', 'call'}
    ab.require(type(config) is dict and set(config) == required, 'mela needs ' + ', '.join(sorted(required)))
    text = json.dumps(config)
    for name in FORBIDDEN:
        ab.require(name not in text, f'{name} is refused: it changes the event weight definition')
    ab.require(config['call'] in ALLOWED_CALLS, f'mela call must be one of {ALLOWED_CALLS}')
    ab.require(type(config['process']) is list and len(config['process']) == 3
               and all(isinstance(x, str) and _ATTRIBUTE.fullmatch(x) for x in config['process']),
               'process names the MELA process, matrix element and production')
    ab.require(isinstance(config['verbosity'], str) and _ATTRIBUTE.fullmatch(config['verbosity']), 'verbosity is a TVar name')
    for r in config['resonances']:
        ab.require(type(r) is dict and set(r) == {'index', 'mass_gev', 'width_gev'} and type(r['index']) is int,
                   'resonances need index, mass_gev and width_gev')
    ab.require(type(config['couplings']) is dict, 'couplings is an object of MELA attribute names')
    for name, value in config['couplings'].items():
        ab.require(_ATTRIBUTE.fullmatch(name), f'coupling attribute {name!r} is not a plain name')
        ab.require(type(value) in (int, float) or (type(value) is list and all(type(v) in (int, float) for v in value)),
                   f'coupling {name} must be a number or a list of numbers')
    return config


def compare(ravel, independent, tolerance):
    """Fit one constant ratio and report the largest relative deviation from it."""
    ravel, independent = np.asarray(ravel, dtype=float), np.asarray(independent, dtype=float)
    ab.require(ravel.shape == independent.shape and ravel.size >= 2, 'both programs need the same points')
    ab.require(np.all(independent != 0) and np.all(np.isfinite(independent)), 'independent values must be finite and nonzero')
    ratio = ravel / independent
    constant = float(np.median(ratio))
    ab.require(constant != 0, 'the normalization constant vanishes')
    deviation = float(np.max(np.abs(ratio / constant - 1.0)))
    return {'passed': deviation <= tolerance, 'normalization_constant': constant, 'max_relative_deviation': deviation,
            'tolerance': tolerance, 'points': int(ravel.size),
            'scope': 'agreement up to one constant; supports conventions, certifies neither program'}


def validate(task):
    ab.require(type(task) is dict and set(task) == {'input'} and isinstance(task['input'], str) and task['input'],
               'task needs exactly input (the document path)')
    return task


def load(task, base):
    validate(task)
    path = Path(task['input'])
    path = (path if path.is_absolute() else Path(base) / path).absolute()
    doc = json.loads(path.read_text())
    required = {'schema_version', 'kind', 'store', 'block', 'max_points', 'tolerance', 'hypothesis', 'mela', 'backend'}
    ab.require(type(doc) is dict and required <= set(doc) <= required | {'description'}, 'document needs ' + ', '.join(sorted(required)))
    ab.require(doc['schema_version'] == 1 and doc['kind'] == MODE, f'schema_version 1 and kind {MODE} required')
    validate_mela(doc['mela'])
    ab.require(type(doc['max_points']) is int and 2 <= doc['max_points'] <= 100000, 'max_points from 2 to 100000')
    ab.real(doc['tolerance'], 'tolerance')
    be = doc['backend']
    ab.require(type(be) is dict and {'kind', 'program', 'resources'} <= set(be)
               <= {'kind', 'program', 'resources', 'image', 'readonly_trees', 'env', 'workdir', 'site'},
               'backend needs kind, program and resources')
    store_dir = (path.parent / doc['store']).absolute()
    manifest = store.store_blocks(store_dir)
    row = next((b for b in manifest['blocks'] if b['id'] == doc['block']), None)
    ab.require(row is not None, f'block {doc["block"]} is not a completed block of the store')
    basis = ab.Basis.from_document(manifest['header']['basis'])
    hyp = ab.hypothesis(doc['hypothesis'], basis)
    return {'path': path, 'doc': doc, 'store': store_dir, 'block': store_dir / row['path'], 'basis': basis, 'hypothesis': hyp}


def inputs(task, base):
    ctx = load(task, base)
    return [ctx['path'], ctx['store'] / store.MANIFEST, ctx['block'], store.marker_path(ctx['block'])]


def stage(ctx, stage_dir):
    doc = ctx['doc']
    block = store.read_block(ctx['block'])
    n = min(doc['max_points'], len(block['factor']))
    header = block['header']
    ab.require('momenta' in block, 'the block keeps no momenta')
    names = header['observables']
    ab.require('s_gev2' in names, 'the block needs the s_gev2 observable')
    s = block['observables'][:n, names.index('s_gev2')]
    ravel = ab.evaluate(block['gram'][:n], ab.coefficients(ctx['hypothesis'], ctx['basis'], s))
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / 'points.json').write_text(json.dumps({'pdg': header['particles']['pdg'],
                                                       'points': [{'momenta': p.tolist()} for p in block['momenta'][:n]]}))
    (stage_dir / 'mela.json').write_text(json.dumps(doc['mela']))
    (stage_dir / 'mela_points.py').write_text(DRIVER)
    be = doc['backend']
    workdir = be.get('workdir')
    where = (lambda f: f'{workdir}/{f}') if workdir else (lambda f: str(stage_dir / f))
    spec = {'schema_version': 1, 'backend': be['kind'], 'stage': 'amplitude-crosscheck',
            'argv': [be['program'], where('mela_points.py'), where('points.json'), where('mela.json'), 'values.json'],
            'inputs': [{'path': str(stage_dir / f), **({'mount': where(f)} if workdir else {})}
                       for f in ('mela_points.py', 'points.json', 'mela.json')],
            'outputs': [{'name': 'values.json', 'destination': str((stage_dir / 'values.json').relative_to(ctx['store']))}],
            'resources': dict(be['resources']), 'description': 'independent matrix-element cross-check'}
    for key in ('image', 'readonly_trees', 'env', 'workdir', 'site'):
        if key in be:
            spec[key] = be[key]
    return spec, ravel


def run(task, base, output, *, backend=None):
    ctx = load(task, base)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    stage_dir = ctx['store'] / 'crosscheck' / hashlib.sha256(ctx['path'].read_bytes()).hexdigest()[:16]
    ab.require(not (stage_dir / 'values.json').exists(), f'{stage_dir} already holds a cross-check result')
    spec, ravel = stage(ctx, stage_dir)
    attempt = stage_dir / 'backend'
    receipt = backend_driver.drive(spec, attempt, ctx['store'], backend=backend)
    values = json.loads((stage_dir / 'values.json').read_text())['values']
    result = compare(ravel, values, float(ctx['doc']['tolerance']))
    record = {'schema_version': 1, 'mode': MODE, 'status': 'passed' if result['passed'] else 'failed', 'status_scope': SCOPE,
              'physics_validated': False, 'comparison': result, 'plan_sha256': receipt['plan_sha256'],
              'hypothesis': ctx['hypothesis']['id'], 'block': ctx['doc']['block'],
              'summary': [f'independent matrix elements agree within {result["max_relative_deviation"]:.3g} '
                          f'of one constant at {result["points"]} points' if result['passed'] else
                          f'independent matrix elements deviate by {result["max_relative_deviation"]:.3g} from one constant']}
    (out / 'crosscheck.json').write_text(json.dumps(record, indent=2) + '\n')
    return record
