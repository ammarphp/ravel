"""Shared fixtures of the P17 tests: synthetic tables, staged specifications, a fake run store with
custody records, and an inert launcher that runs a plan step's approved argv in the governed step's
directory layout (``steps/<id>/attempts/<n>/outputs``) the way the confined launcher would, without a
model, a provider, a network or a native scientific tool. The fixtures are fictional.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[3]
ROUTES = REPO / 'src' / 'ravel' / 'data' / 'controller' / 'routes'
PLACEHOLDER = re.compile(r'\{([a-z][a-z0-9_]*)\}')
THREADS = {'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---- data and specifications --------------------------------------------------------------------

def table(path, *, n=1200, seed=3, features=4, leak=False, noise=0, partition=None, copy_rows=0):
    """A fictional weighted binary table (NPZ reference schema); returns its digest."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.4).astype(float)
    shifts = np.array([1.0, 0.6, 0.0, 0.3] + [0.0] * max(0, features - 4))[:features]
    x = rng.normal(size=(n, features)) + y[:, None] * shifts
    if leak:
        x[:, features - 1] = y + rng.normal(scale=1.e-3, size=n)
    if noise:
        x = np.column_stack([x, rng.normal(size=(n, noise))])
    if copy_rows:
        x[-copy_rows:] = x[:copy_rows]
    arrays = {'x': x, 'y': y, 'weight': rng.uniform(0.5, 1.5, size=n),
              'event_id': np.array([f'ev{i}' for i in range(n)]), 'group_id': np.array([f'gr{i}' for i in range(n)])}
    if partition is not None:
        arrays['partition'] = np.asarray(partition)
    with open(path, 'wb') as stream:
        np.savez(stream, **arrays)
    return sha(path)


def spec(*, features=4, epochs=60, wall=600, seeds=(1, 2, 3), **overrides):
    names = [f'f{i}' for i in range(features)]
    document = {
        'kind': 'ml-staged-spec', 'schema_version': 1, 'study_id': 'fixture_study', 'objective': 'binary_classification',
        'intended_use': 'a fictional fixture for the staged executor tests',
        'claim_scope': 'separation of two fictional classes on fixture data',
        'dataset': {'format': 'npz', 'columns': {'label': 'y', 'weight': 'weight', 'event_id': 'event_id',
                                                 'group_id': 'group_id'}, 'features': names},
        'split': {'method': 'hash', 'seed': 11, 'fractions': {'train': 0.6, 'validation': 0.2, 'test': 0.2}},
        'arms': [{'id': 'cut', 'role': 'baseline', 'kind': 'cut_based',
                  'spec': {'feature': 'f0', 'threshold': 0.5, 'direction': 'above'}},
                 {'id': 'linear', 'role': 'baseline', 'kind': 'trained', 'backend': 'numpy', 'architecture': 'logistic',
                  'config': {'learning_rate': 0.5}},
                 {'id': 'network', 'role': 'candidate', 'kind': 'trained', 'backend': 'numpy', 'architecture': 'mlp',
                  'config': {'learning_rate': 0.5, 'hidden_units': 6}}],
        'primary_arm': 'network', 'seeds': list(seeds), 'budget': {'epochs': epochs, 'wall_seconds': wall},
        'metrics': {'operating_point': 0.5, 'calibration_bins': 10}}
    document.update(deepcopy(overrides))
    return document


def overtrain_spec():
    """Few events, many noise features and a wide network trained long: it memorises its training set."""
    document = spec(features=4, epochs=1500)
    document['dataset']['features'] = [f'f{i}' for i in range(40)]
    document['arms'] = [{'id': 'linear', 'role': 'baseline', 'kind': 'trained', 'backend': 'numpy',
                         'architecture': 'logistic', 'config': {'learning_rate': 0.5}},
                        {'id': 'network', 'role': 'candidate', 'kind': 'trained', 'backend': 'numpy',
                         'architecture': 'mlp', 'config': {'learning_rate': 1.0, 'hidden_units': 64}}]
    document['split']['fractions'] = {'train': 0.5, 'validation': 0.2, 'test': 0.3}
    document['checks'] = {'min_class_count': 10}
    return document


# ---- in-process stages ---------------------------------------------------------------------------

STAGE_INPUTS = {
    'admit': ('spec',),
    'features': ('spec', 'admission', 'train'),
    'train': ('spec', 'admission', 'features', 'train', 'validation'),
    'evaluate': ('spec', 'admission', 'features', 'training', 'models', 'train', 'validation', 'test'),
    'card': ('spec', 'admission', 'features', 'training', 'evaluation'),
    'review': ('spec', 'admission', 'features', 'training', 'models', 'evaluation', 'scores', 'identities', 'train',
               'validation'),
}
SOURCES = {'spec': 'spec.json', 'admission': 'admit/outputs/admission.json',
           'train': 'admit/outputs/partitions/train.npz', 'validation': 'admit/outputs/partitions/validation.npz',
           'test': 'admit/outputs/partitions/test.npz', 'identities': 'admit/outputs/partitions/identities.npz',
           'features': 'features/outputs/features.json', 'training': 'train/outputs/training.json',
           'models': 'train/outputs/models.npz', 'evaluation': 'evaluate/outputs/evaluation.json',
           'scores': 'evaluate/outputs/scores.npz'}


class Pipeline:
    """The six stages run in-process (``ml_stages.run_stage``), each in its own working directory."""

    def __init__(self, root, document, *, data=None, digest=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'spec.json').write_text(json.dumps(document))
        self.data = data
        self.digest = digest
        self.receipts = {}

    def run(self, stage, *, extra=(), drop=(), **options):
        from ravel.workflow import ml_stages
        names = [n for n in STAGE_INPUTS[stage] if n not in drop] + list(extra)
        inputs = {name: self.root / SOURCES[name] for name in names}
        if stage == 'admit':
            options = {'dataset': str(self.data), 'dataset_sha256': self.digest, **options}
        workdir = self.root / stage
        receipt = ml_stages.run_stage(stage, inputs, options, workdir)
        self.receipts[stage] = receipt
        return receipt

    def record(self, stage, name):
        return json.loads((self.root / stage / 'outputs' / name).read_text())

    def all(self, *, stop_at_refusal=True):
        from ravel.workflow import ml_stages
        for stage in ml_stages.STAGES:
            receipt = self.run(stage)
            if stop_at_refusal and receipt['status'] != 'completed':
                return receipt
        return None


# ---- a fake run store with custody ---------------------------------------------------------------

class Store:
    """A ``RunStore`` stand-in: append-only envelopes (``{"id", "kind", "record"}``) and a path root."""

    def __init__(self, root=None, run_id='run-fixture'):
        self.run_id = run_id
        self.rows = []
        self.root = Path(root) if root is not None else None

    def append(self, kind, record):
        json.dumps(record, allow_nan=False)
        identifier = f'{kind}-{len(self.rows) + 1:06d}'
        self.rows.append({'id': identifier, 'kind': kind, 'record': deepcopy(record)})
        return identifier

    def scan(self, kind):
        return [deepcopy(r) for r in self.rows if r['kind'] == kind]

    def latest(self, kind):
        rows = self.scan(kind)
        return rows[-1] if rows else None

    def path(self, *parts):
        return self.root.joinpath(*parts)


def adopt(store, run_dir, step_id, workdir, outputs, *, status='accepted', attempt=1):
    """Copy declared outputs (``outputs/...`` under ``workdir``) to ``steps/<id>/`` with custody records."""
    adopted = []
    for path in outputs:
        source = Path(workdir) / path
        if not source.is_file():
            continue
        destination = f'steps/{step_id}/{path}'
        target = Path(run_dir) / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        record = {'schema_version': 1, 'artifact': f'{step_id}:{path}', 'step_id': step_id, 'attempt': attempt,
                  'path': path, 'destination': destination, 'sha256': sha(target), 'status': status}
        store.append('custody', record)
        adopted.append(record)
    return adopted


# ---- plans --------------------------------------------------------------------------------------

def route_spec(route_id):
    for name in ('ml.json', 'manuscript.json'):
        document = json.loads((ROUTES / name).read_text())
        for row in document['specs'] if document.get('kind') == 'route-spec-family' else [document]:
            if row['id'] == route_id:
                return row
    raise KeyError(route_id)


def _substitute(value, names):
    if type(value) is str:
        return PLACEHOLDER.sub(lambda m: str(names[m.group(1)]) if names.get(m.group(1)) is not None else m.group(0), value)
    if type(value) is list:
        return [_substitute(v, names) for v in value]
    if type(value) is dict:
        return {k: _substitute(v, names) for k, v in value.items()}
    return deepcopy(value)


DEFAULT_STEP = {'inputs': [], 'outputs': [], 'depends_on': [], 'waypoint': False, 'rung': None, 'budget': {},
                'protocols': [], 'review': [], 'instruction_sources': [], 'obligations': []}


def plan(route_id, parameters, *, deliverables=()):
    """A plan of the route spec with its placeholders bound: the controller core's compiler when it is
    installed, else the same template substitution done here (the spec has no ``foreach``)."""
    document = route_spec(route_id)
    try:
        from ravel.controller.routes import compiler
    except ImportError:
        compiler = None
    reading = {'facts': [], 'constraints': [], 'deliverables': [
        {'id': f'D{i}', 'artifact': {'kind': a} if a else None, 'claim_kind': c} for i, (a, c) in enumerate(deliverables, 1)]}
    if compiler is not None:
        return compiler.compile(document, reading, {}, parameters=parameters)
    steps = [_substitute({**deepcopy(DEFAULT_STEP), **row}, parameters) for row in document['steps']]
    rows = []
    for deliverable in reading['deliverables']:
        artifact = (deliverable.get('artifact') or {}).get('kind')
        row = {'id': deliverable['id'], 'status': 'open', 'step': None, 'output': None,
               'claim_kind': deliverable['claim_kind'], 'artifact_kind': artifact}
        for rule in document['deliverables']:
            match = rule['match']
            if ('artifact' in match and artifact not in match['artifact']) or (
                    'claim' in match and deliverable['claim_kind'] not in match['claim']):
                continue
            row.update(status='mapped', step=rule['step'], output=rule['output'])
            break
        rows.append(row)
    found = {'schema_version': 1, 'kind': 'controller-plan', 'revision': 0,
             'route': {'id': document['id'], 'version': document['version'], 'spec_sha256': '0' * 64},
             'parameters': parameters, 'steps': steps, 'deliverables': rows,
             'waypoints': [s['id'] for s in steps if s.get('waypoint')], 'checkins': document.get('checkins', [])}
    found['sha256'] = hashlib.sha256(json.dumps(found, sort_keys=True).encode()).hexdigest()
    return found


# ---- the inert launcher ---------------------------------------------------------------------------

def child_env():
    from ravel.workflow import machine_lease
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8', **THREADS,
           **machine_lease.child_env()}
    source = str(REPO / 'src')
    env['PYTHONPATH'] = source
    return env


def launch(run_dir, step, *, attempt=1, timeout=600):
    """Run the step's approved argv once in ``steps/<id>/attempts/<n>/outputs`` (cwd), as the governed step does.

    The interpreter runs in isolated mode in the plan; the test runs the same argv with the
    checkout's sources on the module path (``-I`` would ignore it), so ``-I`` is dropped here only.
    """
    argv = list(step['parameters']['launch']['argv'])
    argv = [sys.executable if a == argv[0] else a for a in argv[:1]] + [a for a in argv[1:] if a != '-I']
    workdir = Path(run_dir) / 'steps' / step['id'] / 'attempts' / str(attempt) / 'outputs'
    workdir.mkdir(parents=True, exist_ok=True)
    found = subprocess.run(argv, cwd=workdir, env=child_env(), capture_output=True, text=True, timeout=timeout)
    return found, workdir
