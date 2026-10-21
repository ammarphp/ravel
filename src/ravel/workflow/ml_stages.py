"""The staged ML executor: six typed stages, each one confined launch of a governed plan step.

``admit`` (dataset admission and split with provenance) -> ``features`` (feature definition and the
label-leakage screen) -> ``train`` (training launch) -> ``evaluate`` (the one read of the withheld
partition) -> ``card`` (model card) -> ``review`` (executable reviewer items, ``ml_checks``).

A stage reads only the inputs its approved launch names and writes only under ``outputs/`` of its
working directory: the declared outputs of its plan step and its typed receipt
``outputs/ml/receipt.json``. The training stage is never given the withheld partition; the plan keeps
it out of the training launch's reads, so the sandbox, not convention, keeps test data out of training
(and the stage refuses an input named ``test``). The evaluation decodes the withheld partition once,
after the models are frozen; the review recomputes every item from pinned arrays and records.

Receipt status: ``completed``; ``refused`` (a typed scientific or contract refusal: leakage, overlap,
insufficient statistics, overtraining, an invalid specification); ``held`` (a prerequisite genuinely
missing: backend, reader or device); ``budget_exhausted`` (the training budget ran out; completed
replicates are kept, the stage is incomplete); ``failed`` (an exception: a typed failure with its class,
never a refusal). On every status except ``failed`` the stage writes all its declared outputs, marking
unproduced ones as placeholders, so the governed step adopts the receipt and the route check acts on
its status; a placeholder is never a result.

Command line (the launch argv the plan approves)::

    python -I -m ravel.workflow.ml_stages <stage> --root <run root> --input <name>=<relative path> ...
        [--dataset <absolute path> --dataset-sha256 <hex>] [--wall-seconds <step wall budget>]

Exit status: 0 with a typed receipt; 1 for a failure (receipt written when possible); 2 for a usage
error. No network, no model call; this module computes, it never decides authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
import zipfile

# A launch runs with the CPUs its step reserves; numerical libraries read their thread counts once,
# when they load, so the command line sets them before numpy is imported (``--threads``, default 1).
THREAD_VARIABLES = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS',
                    'NUMEXPR_NUM_THREADS')
if __name__ == '__main__' and 'numpy' not in sys.modules:
    _threads = next((a.split('=', 1)[1] for a in sys.argv if a.startswith('--threads=')), '1')
    for _name in THREAD_VARIABLES:
        os.environ[_name] = _threads if _threads.isdigit() and 0 < int(_threads) <= 256 else '1'

import numpy as np  # noqa: E402

from . import ml_checks

SCHEMA_VERSION = 1
STAGES = ('admit', 'features', 'train', 'evaluate', 'card', 'review')
OPERATIONS = {stage: f'ml-stage-{stage}' for stage in STAGES}
RECEIPT = 'outputs/ml/receipt.json'
SPEC_KIND = 'ml-staged-spec'
PARTITIONS = ('train', 'validation', 'test')
# Declared outputs of each stage's plan step: (path, artifact kind).
OUTPUTS = {
    'admit': (('outputs/partitions/train.npz', 'table'), ('outputs/partitions/validation.npz', 'table'),
              ('outputs/partitions/test.npz', 'table'), ('outputs/partitions/identities.npz', 'table'),
              ('outputs/admission.json', 'table')),
    'features': (('outputs/features.json', 'table'),),
    'train': (('outputs/models.npz', 'selection'), ('outputs/training.json', 'table'),
              ('outputs/checkpoint.npz', 'selection'), ('outputs/checkpoint.json', 'table')),
    'evaluate': (('outputs/evaluation.json', 'table'), ('outputs/scores.npz', 'table')),
    'card': (('outputs/model_card.json', 'document'), ('outputs/model_card.md', 'document')),
    'review': (('outputs/review.json', 'document'),),
}
# The receipt is a declared artifact, so the step graph can adopt and validate it.
OUTPUTS = {stage: (*rows, (RECEIPT, 'document')) for stage, rows in OUTPUTS.items()}

# Named inputs each stage requires (besides the supplied dataset of ``admit``).
INPUTS = {
    'admit': ('spec',),
    'features': ('spec', 'admission', 'train'),
    'train': ('spec', 'admission', 'features', 'train', 'validation'),
    'evaluate': ('spec', 'admission', 'features', 'training', 'models', 'train', 'validation', 'test'),
    'card': ('spec', 'admission', 'features', 'training', 'evaluation'),
    'review': ('spec', 'admission', 'features', 'training', 'models', 'evaluation', 'scores', 'identities', 'train',
               'validation'),
}
# The withheld partition never reaches these stages.
WITHHELD_FORBIDDEN = ('admit', 'features', 'train', 'card', 'review')
FORMATS = ('npz', 'csv', 'root')
SPLITS = ('hash', 'explicit')
DEVICES = ('cpu', 'cuda:0')
ARCHITECTURES = {'logistic': ('learning_rate',), 'mlp': ('learning_rate', 'hidden_units')}
SAFE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,39}\Z')
MAX_BYTES = (1024 ** 3, 1024 ** 2, 16 * 1024 ** 3)  # default, lower and upper bound of ``max_bytes``
MAX_ROWS = 50_000_000
MARGIN = (30.0, 0.05)  # the stage stops this long (seconds, fraction) before the step's hard wall
SMOKE = {'epochs': 20, 'rows': 4000}  # the training smoke rung: one seed, these epochs and rows per partition


class StageRefused(Exception):
    """A typed refusal: the stage ran and found the request or the data inadmissible."""
    status = 'refused'

    def __init__(self, code, detail, evidence=None):
        super().__init__(f'{code}: {detail}')
        self.code, self.detail, self.evidence = code, detail, deepcopy(evidence)


class StageHeld(StageRefused):
    """A prerequisite is genuinely missing on this host (backend, reader, device)."""
    status = 'held'


class BudgetExhaustedStage(StageRefused):
    """The training budget ran out: completed replicates are kept and the stage is incomplete."""
    status = 'budget_exhausted'


class BudgetExhausted(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def identity_sha256(event_ids):
    """The population identity: the digest of its sorted event identifiers (as ``ml_exposure`` computes it)."""
    ordered = sorted(str(v) for v in event_ids)
    return hashlib.sha256(json.dumps(ordered, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def implementation():
    here = Path(__file__)
    return {'module': __name__, 'sha256': file_sha256(here), 'checks_sha256': file_sha256(Path(ml_checks.__file__)),
            'numpy': np.__version__, 'python': platform.python_version()}


# ---- the specification -------------------------------------------------------------------------

def _number(value, low, high, name, *, integer=False):
    kinds = (int,) if integer else (int, float)
    if type(value) not in kinds or isinstance(value, bool) or not math.isfinite(value) or not low <= value <= high:
        raise StageRefused('ml_spec_invalid', f'{name} must be a {"integer" if integer else "number"} in [{low}, {high}]')
    return value


def _keys(value, required, optional=(), name='object'):
    if type(value) is not dict:
        raise StageRefused('ml_spec_invalid', f'{name} must be an object')
    missing = sorted(set(required) - set(value))
    extra = sorted(set(value) - set(required) - set(optional))
    if missing or extra:
        raise StageRefused('ml_spec_invalid', f'{name}: missing {missing}, unknown {extra}')


def validate_spec(spec):
    """The staged training specification, or a typed refusal naming the first defect."""
    _keys(spec, ('kind', 'schema_version', 'study_id', 'objective', 'dataset', 'split', 'arms', 'primary_arm',
                 'seeds', 'budget', 'metrics'),
          ('intended_use', 'claim_scope', 'device', 'checks', 'max_bytes', 'description'), 'specification')
    if spec['kind'] != SPEC_KIND or spec['schema_version'] != SCHEMA_VERSION:
        raise StageRefused('ml_spec_invalid', f'kind {SPEC_KIND} version {SCHEMA_VERSION} required')
    if type(spec['study_id']) is not str or not SAFE_ID.fullmatch(spec['study_id']):
        raise StageRefused('ml_spec_invalid', 'study_id is a short safe identifier')
    if spec['objective'] != 'binary_classification':
        raise StageRefused('ml_spec_invalid', 'the staged executor trains binary classifiers')
    data = spec['dataset']
    _keys(data, ('format', 'columns', 'features'), ('tree',), 'dataset')
    if data['format'] not in FORMATS:
        raise StageRefused('ml_spec_invalid', f'dataset format is one of {FORMATS}')
    if data['format'] == 'root' and (type(data.get('tree')) is not str or not data['tree']):
        raise StageRefused('ml_spec_invalid', 'a ROOT dataset names its tree')
    _keys(data['columns'], ('label', 'event_id'), ('weight', 'group_id', 'partition'), 'dataset.columns')
    for key, value in data['columns'].items():
        if value is not None and (type(value) is not str or not value):
            raise StageRefused('ml_spec_invalid', f'column {key} is a name or null')
    features = data['features']
    if type(features) is not list or not 1 <= len(features) <= 256 or len(set(features)) != len(features) or any(
            type(f) is not str or not f for f in features):
        raise StageRefused('ml_spec_invalid', 'one to 256 unique feature names required')
    split = spec['split']
    _keys(split, ('method',), ('seed', 'fractions'), 'split')
    if split['method'] not in SPLITS:
        raise StageRefused('ml_spec_invalid', f'split method is one of {SPLITS}')
    if split['method'] == 'hash':
        _number(split.get('seed'), 0, 2 ** 32 - 1, 'split.seed', integer=True)
        fractions = split.get('fractions')
        _keys(fractions, PARTITIONS, (), 'split.fractions')
        for name in PARTITIONS:
            _number(fractions[name], 0.001, 0.998, f'split.fractions.{name}')
        if not math.isclose(sum(fractions.values()), 1.0, abs_tol=1.e-9):
            raise StageRefused('ml_spec_invalid', 'split fractions sum to one')
    elif not data['columns'].get('partition'):
        raise StageRefused('ml_spec_invalid', 'an explicit split names its partition column')
    arms = spec['arms']
    if type(arms) is not list or not 2 <= len(arms) <= 8:
        raise StageRefused('ml_spec_invalid', 'two to eight arms required')
    ids = set()
    for arm in arms:
        _arm(arm, features)
        if arm['id'] in ids:
            raise StageRefused('ml_spec_invalid', f"duplicate arm {arm['id']}")
        ids.add(arm['id'])
    roles = {a['role'] for a in arms}
    if not {'baseline', 'candidate'} <= roles:
        raise StageRefused('ml_spec_invalid', 'at least one baseline and one candidate arm required')
    primary = next((a for a in arms if a['id'] == spec['primary_arm']), None)
    if primary is None or primary['role'] != 'candidate' or primary['kind'] != 'trained':
        raise StageRefused('ml_spec_invalid', 'primary_arm names a trained candidate arm, declared before any test read')
    seeds = spec['seeds']
    if type(seeds) is not list or not 3 <= len(seeds) <= 32 or len(set(seeds)) != len(seeds):
        raise StageRefused('ml_spec_invalid', 'three to 32 distinct replicate seeds required')
    for seed in seeds:
        _number(seed, 0, 2 ** 32 - 1, 'seed', integer=True)
    budget = spec['budget']
    _keys(budget, ('epochs', 'wall_seconds'), ('replicate_wall_seconds',), 'budget')
    _number(budget['epochs'], 1, 100000, 'budget.epochs', integer=True)
    _number(budget['wall_seconds'], 1, 7 * 86400, 'budget.wall_seconds', integer=True)
    _number(budget.get('replicate_wall_seconds', budget['wall_seconds']), 1, budget['wall_seconds'],
            'budget.replicate_wall_seconds', integer=True)
    metrics = spec['metrics']
    _keys(metrics, ('operating_point',), ('calibration_bins',), 'metrics')
    _number(metrics['operating_point'], 0.001, 0.999, 'metrics.operating_point')
    _number(metrics.get('calibration_bins', 10), 2, 100, 'metrics.calibration_bins', integer=True)
    if spec.get('device', 'cpu') not in DEVICES:
        raise StageRefused('ml_spec_invalid', f'device is one of {DEVICES}')
    _number(spec.get('max_bytes', MAX_BYTES[0]), MAX_BYTES[1], MAX_BYTES[2], 'max_bytes', integer=True)
    try:
        ml_checks.thresholds(spec)
    except ValueError as exc:
        raise StageRefused('ml_spec_invalid', str(exc)) from None
    return spec


def _arm(arm, features):
    if type(arm) is not dict or type(arm.get('id')) is not str or not SAFE_ID.fullmatch(arm['id']):
        raise StageRefused('ml_spec_invalid', 'every arm has a short safe id')
    if arm.get('role') not in ('baseline', 'candidate'):
        raise StageRefused('ml_spec_invalid', f"arm {arm['id']} role is baseline or candidate")
    if 'budget' in arm:
        raise StageRefused('ml_spec_invalid', 'arms take the study budget; arm-level budgets are refused')
    if arm.get('kind') == 'cut_based':
        _keys(arm, ('id', 'role', 'kind', 'spec'), (), f"arm {arm['id']}")
        if arm['role'] != 'baseline':
            raise StageRefused('ml_spec_invalid', 'a cut is an untrained baseline')
        _keys(arm['spec'], ('feature', 'threshold', 'direction'), (), f"arm {arm['id']} cut")
        if arm['spec']['feature'] not in features or arm['spec']['direction'] not in ('above', 'below'):
            raise StageRefused('ml_spec_invalid', 'a cut names a declared feature and a direction')
        _number(arm['spec']['threshold'], -1.e100, 1.e100, 'cut threshold')
        return
    if arm.get('kind') != 'trained':
        raise StageRefused('ml_spec_invalid', f"arm {arm['id']} kind is trained or cut_based")
    _keys(arm, ('id', 'role', 'kind', 'backend', 'architecture', 'config'), ('features',), f"arm {arm['id']}")
    from ravel.physics import ml_backends
    if arm['backend'] not in ml_backends.FAMILIES or arm['architecture'] not in ARCHITECTURES or \
            arm['architecture'] not in ml_backends.FAMILIES[arm['backend']]:
        raise StageRefused('ml_spec_invalid', f"arm {arm['id']}: backend and architecture outside the allowlist")
    _keys(arm['config'], ARCHITECTURES[arm['architecture']], (), f"arm {arm['id']} config")
    _number(arm['config']['learning_rate'], 1.e-8, 1.0, 'learning_rate')
    if 'hidden_units' in arm['config']:
        _number(arm['config']['hidden_units'], 1, 128, 'hidden_units', integer=True)
    subset = arm.get('features', features)
    if type(subset) is not list or not subset or len(set(subset)) != len(subset) or any(f not in features for f in subset):
        raise StageRefused('ml_spec_invalid', f"arm {arm['id']} features are a subset of the declared features")


def arm_features(arm, features):
    if arm['kind'] == 'cut_based':
        return [arm['spec']['feature']]
    return list(arm.get('features', features))


# ---- reading supplied tables ---------------------------------------------------------------------

def _regular(path, max_bytes):
    path = Path(path)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise StageRefused('ml_input_missing', f'{path.name}: {exc.strerror}') from None
    import stat
    if not stat.S_ISREG(info.st_mode):
        raise StageRefused('ml_input_invalid', f'{path.name} is not a regular file')
    if info.st_size > max_bytes:
        raise StageRefused('ml_input_too_large', f'{path.name} has {info.st_size} bytes; the bound is {max_bytes}')
    return path


def read_table(path, data, *, max_bytes):
    """``{x, y, weight, event_id, group_id, partition}`` from a supplied NPZ, CSV or ROOT table."""
    path = _regular(path, max_bytes)
    columns, features = data['columns'], data['features']
    if data['format'] == 'npz':
        raw = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(i.file_size for i in archive.infolist()) > max_bytes:
                raise StageRefused('ml_input_too_large', 'expanded table exceeds the byte bound')
        with np.load(io.BytesIO(raw), allow_pickle=False) as found:
            names = set(found.files)
            def column(name, required=True):
                if name is None or name not in names:
                    if required:
                        raise StageRefused('ml_column_missing', f'column {name!r} is not in the table')
                    return None
                return np.asarray(found[name])
            if 'x' in names and not set(features) <= names:
                x = np.asarray(found['x'])
                if x.ndim != 2 or x.shape[1] != len(features):
                    raise StageRefused('ml_feature_shape', 'the x matrix has one column per declared feature')
            else:
                x = np.column_stack([column(f) for f in features]) if features else None
            table = {'x': x, 'y': column(columns['label']), 'weight': column(columns.get('weight'), False),
                     'event_id': column(columns['event_id']), 'group_id': column(columns.get('group_id'), False),
                     'partition': column(columns.get('partition'), False)}
    elif data['format'] == 'csv':
        table = _read_csv(path, columns, features)
    else:
        try:
            import uproot
        except ImportError:
            raise StageHeld('ml_reader_unavailable', 'reading ROOT tables needs uproot, which is not installed') from None
        wanted = list(dict.fromkeys([*features, *[c for c in columns.values() if c]]))
        with uproot.open(str(path)) as handle:
            if data['tree'] not in handle:
                raise StageRefused('ml_column_missing', f"tree {data['tree']!r} is not in the file")
            arrays = handle[data['tree']].arrays(wanted, library='np')
        table = {'x': np.column_stack([np.asarray(arrays[f]) for f in features]), 'y': arrays[columns['label']],
                 'weight': arrays.get(columns.get('weight')) if columns.get('weight') else None,
                 'event_id': arrays[columns['event_id']],
                 'group_id': arrays.get(columns.get('group_id')) if columns.get('group_id') else None,
                 'partition': arrays.get(columns.get('partition')) if columns.get('partition') else None}
    return _normalise(table, columns, data)


def _read_csv(path, columns, features):
    wanted = [*features, *[c for c in columns.values() if c]]
    rows = {name: [] for name in dict.fromkeys(wanted)}
    with open(path, newline='') as stream:
        reader = csv.reader(stream)
        header = next(reader, None)
        if header is None:
            raise StageRefused('ml_table_empty', 'the table has no header')
        index = {name: i for i, name in enumerate(header)}
        missing = [name for name in rows if name not in index]
        if missing:
            raise StageRefused('ml_column_missing', 'columns not in the table: ' + ', '.join(missing))
        for count, row in enumerate(reader):
            if count >= MAX_ROWS:
                raise StageRefused('ml_input_too_large', f'more than {MAX_ROWS} rows')
            for name in rows:
                rows[name].append(row[index[name]])
    text = {columns['event_id'], columns.get('group_id'), columns.get('partition')} - {None}
    def parsed(name):
        values = rows[name]
        if name in text:
            return np.asarray(values, dtype=str)
        try:
            return np.asarray([float(v) for v in values], dtype=float)
        except ValueError:
            raise StageRefused('ml_value_invalid', f'column {name} holds a non-numeric value') from None
    return {'x': np.column_stack([parsed(f) for f in features]), 'y': parsed(columns['label']),
            'weight': parsed(columns['weight']) if columns.get('weight') else None,
            'event_id': parsed(columns['event_id']),
            'group_id': parsed(columns['group_id']) if columns.get('group_id') else None,
            'partition': parsed(columns['partition']) if columns.get('partition') else None}


def _normalise(table, columns, data):
    x = np.asarray(table['x'])
    if x.ndim != 2 or len(x) == 0:
        raise StageRefused('ml_table_empty', 'a nonempty two-dimensional feature table is required')
    n = len(x)
    if x.dtype.kind not in 'fiub':
        raise StageRefused('ml_value_invalid', 'features are numeric')
    x = x.astype(float)
    y = np.asarray(table['y'])
    if y.shape != (n,) or y.dtype.kind not in 'fiub':
        raise StageRefused('ml_value_invalid', 'one numeric label per row')
    y = y.astype(float)
    if not set(np.unique(y).tolist()) <= {0.0, 1.0}:
        raise StageRefused('ml_label_not_binary', 'labels are 0 (background) or 1 (signal)')
    weight = np.ones(n) if table['weight'] is None else np.asarray(table['weight'], dtype=float)
    if weight.shape != (n,) or not np.isfinite(weight).all():
        raise StageRefused('ml_value_invalid', 'one finite weight per row')
    if np.any(weight < 0):
        raise StageRefused('ml_negative_weights_unsupported', 'negative event weights are not supported by these '
                           'backends; supply nonnegative weights', {'negative': int((weight < 0).sum())})
    bad = int((~np.isfinite(x)).sum())
    if bad:
        raise StageRefused('ml_nonfinite_features', f'{bad} feature values are not finite',
                           {'per_feature': {f: int((~np.isfinite(x[:, i])).sum())
                                            for i, f in enumerate(data['features'])}})
    events = np.asarray(table['event_id']).astype(str)
    groups = events if table['group_id'] is None else np.asarray(table['group_id']).astype(str)
    if events.shape != (n,) or groups.shape != (n,):
        raise StageRefused('ml_value_invalid', 'one event and group identity per row')
    unique = len(np.unique(events))
    if unique != n:
        raise StageRefused('ml_duplicate_identities', f'{n - unique} repeated event identities in the supplied table')
    if n > MAX_ROWS:
        raise StageRefused('ml_input_too_large', f'more than {MAX_ROWS} rows')
    if np.any(events == '') or np.any(groups == ''):
        raise StageRefused('ml_value_invalid', 'event and group identities are nonempty')
    partition = None if table['partition'] is None else np.asarray(table['partition']).astype(str)
    if partition is not None and partition.shape != (n,):
        raise StageRefused('ml_value_invalid', 'one partition name per row')
    return {'x': x, 'y': y, 'weight': weight, 'event_id': events, 'group_id': groups, 'partition': partition}


def hash_partition(group, seed, fractions):
    value = int(hashlib.sha256(f'{seed}:{group}'.encode()).hexdigest(), 16) / 2 ** 256
    if value < fractions['train']:
        return 'train'
    return 'validation' if value < fractions['train'] + fractions['validation'] else 'test'


def split_rows(table, split):
    if split['method'] == 'hash':
        names = np.array([hash_partition(g, split['seed'], split['fractions']) for g in table['group_id']])
    else:
        names = np.array(['validation' if v == 'val' else v for v in table['partition']])
        unknown = sorted(set(names.tolist()) - set(PARTITIONS))
        if unknown:
            raise StageRefused('ml_partition_invalid', 'explicit partitions are train, validation or test: '
                               + ', '.join(unknown[:5]))
    return {name: np.flatnonzero(names == name) for name in PARTITIONS}


def save_partition(path, table, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as stream:
        np.savez(stream, **{k: table[k][rows] for k in ('x', 'y', 'weight', 'event_id', 'group_id')})


def load_partition(path, features=None):
    with np.load(path, allow_pickle=False) as found:
        if 'placeholder' in found.files:
            raise StageRefused('ml_input_placeholder', f'{Path(path).name} is a placeholder of a refused stage')
        part = {k: np.asarray(found[k]) for k in ('x', 'y', 'weight', 'event_id', 'group_id')}
    part['event_id'] = part['event_id'].astype(str)
    part['group_id'] = part['group_id'].astype(str)
    if features is not None and part['x'].shape[1] != len(features):
        raise StageRefused('ml_feature_shape', f'{Path(path).name} has another feature count')
    return part


def class_counts(part):
    y, w = part['y'], part['weight']
    return {'rows': int(len(y)), 'signal': int((y == 1).sum()), 'background': int((y == 0).sum()),
            'signal_weight': float(w[y == 1].sum()), 'background_weight': float(w[y == 0].sum()),
            'signal_effective': ml_checks.effective_count(w[y == 1]),
            'background_effective': ml_checks.effective_count(w[y == 0])}


# ---- stages -----------------------------------------------------------------------------------

def _json(path):
    with open(path) as stream:
        value = json.load(stream)
    if type(value) is dict and value.get('placeholder'):
        raise StageRefused('ml_input_placeholder', f'{Path(path).name} is a placeholder of a refused stage')
    return value


def _spec(inputs):
    spec = _json(inputs['spec'])
    validate_spec(spec)
    return spec, digest(spec)


def _record(inputs, name, kind, spec_sha):
    value = _json(inputs[name])
    if type(value) is not dict or value.get('kind') != kind:
        raise StageRefused('ml_input_chain_broken', f'{name} is not an {kind} record')
    if value.get('spec_sha256') != spec_sha:
        raise StageRefused('ml_input_chain_broken', f'{name} was produced for another specification')
    if value.get('status') != 'completed':
        raise StageRefused('ml_input_chain_broken', f'{name} records status {value.get("status")}')
    return value


def _partition_input(inputs, name, admission):
    recorded = (admission['partitions'].get(name) or {}).get('sha256')
    if file_sha256(inputs[name]) != recorded:
        raise StageRefused('ml_input_chain_broken', f'the {name} partition differs from the admitted one')
    return load_partition(inputs[name], admission['features'])


def admit(inputs, options, out):
    spec, spec_sha = _spec(inputs)
    dataset = options.get('dataset')
    if not dataset:
        raise StageRefused('ml_dataset_missing', 'admission reads the supplied dataset its launch names')
    declared = options.get('dataset_sha256')
    if type(declared) is not str or not re.fullmatch(r'[0-9a-f]{64}', declared or ''):
        raise StageRefused('ml_dataset_unpinned', 'the supplied dataset has no intake digest; supply a file')
    max_bytes = spec.get('max_bytes', MAX_BYTES[0])
    _regular(dataset, max_bytes)
    actual = file_sha256(dataset)
    if actual != declared:
        raise StageRefused('ml_dataset_changed', 'the supplied dataset differs from its intake digest',
                           {'intake_sha256': declared, 'sha256': actual})
    table = read_table(dataset, spec['dataset'], max_bytes=max_bytes)
    rows = split_rows(table, spec['split'])
    limits = ml_checks.thresholds(spec)
    partitions, identities, hashes = {}, {}, {}
    for name in PARTITIONS:
        index = rows[name]
        path = out / 'partitions' / f'{name}.npz'
        save_partition(path, table, index)
        part = {k: table[k][index] for k in ('x', 'y', 'weight', 'event_id', 'group_id')}
        identities[name] = {'event_id': part['event_id'], 'group_id': part['group_id']}
        hashes[name] = ml_checks.row_hashes(part['x'])
        partitions[name] = {'file': f'partitions/{name}.npz', 'sha256': file_sha256(path),
                            'identity_sha256': identity_sha256(part['event_id']), **class_counts(part)}
    with open(out / 'partitions' / 'identities.npz', 'wb') as stream:
        np.savez(stream, **{f'{p}__{c}': identities[p][c] for p in PARTITIONS for c in ('event_id', 'group_id')},
                 **{f'{p}__row_hash': hashes[p] for p in PARTITIONS})
    items = [ml_checks.statistics_sizing({p: partitions[p] for p in PARTITIONS}, limits),
             ml_checks.split_disjoint(identities), ml_checks.duplicate_identities(identities),
             ml_checks.duplicate_rows(hashes['train'], {'validation': hashes['validation'], 'test': hashes['test']},
                                      limits)]
    codes = [ADMISSION_CODES[r['id']] for r in items if r['verdict'] != 'pass']
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-admission', 'spec_sha256': spec_sha,
              'source': {'path': str(dataset), 'sha256': actual, 'bytes': os.path.getsize(dataset),
                         'format': spec['dataset']['format'], 'rows': int(len(table['y']))},
              'columns': deepcopy(spec['dataset']['columns']), 'features': list(spec['dataset']['features']),
              'split': deepcopy(spec['split']), 'partitions': partitions, 'items': items,
              'identities_sha256': file_sha256(out / 'partitions' / 'identities.npz'),
              'status': 'refused' if codes else 'completed', 'codes': codes}
    _write_json(out / 'admission.json', record)
    if codes:
        raise StageRefused(codes[0], 'the admitted dataset fails ' + ', '.join(r['id'] for r in items
                                                                               if r['verdict'] != 'pass'),
                           {'items': [r for r in items if r['verdict'] != 'pass']})
    return {'spec_sha256': spec_sha}


ADMISSION_CODES = {'check:ml-statistics-sizing': 'ml_statistics_insufficient', 'check:ml-split-disjoint': 'ml_split_overlap',
                   'check:ml-duplicate-identities': 'ml_duplicate_identities', 'check:ml-duplicate-rows': 'ml_duplicate_rows'}


def features(inputs, options, out):
    spec, spec_sha = _spec(inputs)
    admission = _record(inputs, 'admission', 'ml-admission', spec_sha)
    if admission['features'] != spec['dataset']['features']:
        raise StageRefused('ml_input_chain_broken', 'the admitted features differ from the specification')
    train = _partition_input(inputs, 'train', admission)
    limits = ml_checks.thresholds(spec)
    leakage = ml_checks.label_leakage(train['x'], train['y'], train['weight'], admission['features'],
                                      admission['columns'], limits)
    preprocessing = {'fitted_on': 'train', **ml_checks.standardisation(train['x'], train['weight'])}
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-features', 'spec_sha256': spec_sha,
              'features': list(admission['features']),
              'arms': {a['id']: arm_features(a, admission['features']) for a in spec['arms']},
              'preprocessing': preprocessing, 'items': [leakage],
              'status': 'completed' if leakage['verdict'] == 'pass' else 'refused',
              'codes': [] if leakage['verdict'] == 'pass' else ['ml_label_leakage']}
    _write_json(out / 'features.json', record)
    if leakage['verdict'] != 'pass':
        raise StageRefused('ml_label_leakage', 'declared features leak the label: ' + ', '.join(
            leakage['evidence']['failing']), {'item': leakage})
    return {'spec_sha256': spec_sha}


def _device(spec):
    """The accelerator torch arms train on; numpy, scikit-learn and cut arms always run on the CPU."""
    device = spec.get('device', 'cpu')
    if device == 'cpu':
        return device
    if not any(a['kind'] == 'trained' and a['backend'] == 'torch' for a in spec['arms']):
        raise StageRefused('ml_spec_invalid', f'{device} is requested but no arm trains with torch')
    try:
        import torch
    except ImportError:
        raise StageHeld('ml_device_unavailable', f'{device} needs torch, which is not installed') from None
    if not torch.cuda.is_available():
        raise StageHeld('ml_device_unavailable', f'{device} is not visible to this launch')
    return device


def _fit_device(arm, x, y, weight, seed, epochs, deadline, device):
    """The torch logistic/MLP path on an accelerator; the state predicts through ``ml_backends.predict``."""
    import torch
    dev = torch.device(device)
    mean = np.average(x, axis=0, weights=weight)
    scale = np.sqrt(np.average((x - mean) ** 2, axis=0, weights=weight))
    scale = np.where(scale > 1.e-12, scale, 1.0)
    z = (x - mean) / scale
    generator = torch.Generator(device='cpu').manual_seed(seed)
    width = arm['config'].get('hidden_units', 8)
    mlp = arm['architecture'] == 'mlp'
    tx = torch.tensor(z, dtype=torch.float64, device=dev)
    ty = torch.tensor(y, dtype=torch.float64, device=dev)
    tw = torch.tensor(weight / weight.sum(), dtype=torch.float64, device=dev)
    w = (torch.randn((z.shape[1], width) if mlp else (z.shape[1],), generator=generator, dtype=torch.float64)
         / np.sqrt(z.shape[1])).to(dev).requires_grad_()
    b = torch.zeros(width if mlp else 1, dtype=torch.float64, device=dev, requires_grad=True)
    params = [w, b]
    if mlp:
        v = (torch.randn(width, generator=generator, dtype=torch.float64) / np.sqrt(width)).to(dev).requires_grad_()
        c = torch.zeros(1, dtype=torch.float64, device=dev, requires_grad=True)
        params += [v, c]
    rate = arm['config']['learning_rate']
    for _ in range(epochs):
        deadline()
        logits = torch.tanh(tx @ w + b) @ v + c if mlp else tx @ w + b
        loss = (torch.nn.functional.binary_cross_entropy_with_logits(logits, ty, reduction='none') * tw).sum()
        loss.backward()
        with torch.no_grad():
            for p in params:
                p -= rate * p.grad
                p.grad.zero_()
    state = dict(zip(('w', 'b', 'v', 'c'), [p.detach().cpu().numpy() for p in params]))
    return {'mean': mean, 'scale': scale, **state}


def _cut_model(arm, names):
    return {'cut_feature': np.array(names.index(arm['spec']['feature'])), 'cut_threshold': np.array(arm['spec']['threshold']),
            'cut_above': np.array(arm['spec']['direction'] == 'above')}


def _logloss(y, score, weight):
    p = np.clip(score, 1.e-12, 1 - 1.e-12)
    return float(np.average(-(y * np.log(p) + (1 - y) * np.log(1 - p)), weights=weight))


def replicate_key(arm_id, seed):
    return f'{arm_id}__seed_{seed}'


def _checkpoint(out, spec_sha, models, rows, inputs, began):
    """Persist completed replicates before the next one starts; never certify unfinished work."""
    manifest = {'replicates': [r['key'] for r in rows if r['status'] == 'completed'],
                'features': {r['key']: r['features'] for r in rows if r['status'] == 'completed'}}
    target = out / 'checkpoint.npz'
    pending = out / '.checkpoint.npz.pending'
    with pending.open('wb') as stream:
        np.savez(stream, __manifest__=np.array(json.dumps(manifest, sort_keys=True)), **models)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, target)
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-training-checkpoint',
              'spec_sha256': spec_sha, 'completed': manifest['replicates'],
              'replicates': deepcopy(rows), 'models_sha256': file_sha256(target),
              'inputs': {k: file_sha256(v) for k, v in sorted(inputs.items())},
              'wall_seconds': time.monotonic() - began, 'status': 'partial'}
    pending = out / '.checkpoint.json.pending'
    with pending.open('w') as stream:
        stream.write(json.dumps(record, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, out / 'checkpoint.json')


def train(inputs, options, out):
    if 'test' in inputs:
        raise StageRefused('ml_withheld_partition_in_training', 'the training launch was given the withheld partition')
    spec, spec_sha = _spec(inputs)
    admission = _record(inputs, 'admission', 'ml-admission', spec_sha)
    feature_record = _record(inputs, 'features', 'ml-features', spec_sha)
    data = {name: _partition_input(inputs, name, admission) for name in ('train', 'validation')}
    from ravel.physics import ml_backends
    available = ml_backends.available()
    missing = sorted({a['backend'] for a in spec['arms'] if a['kind'] == 'trained' and not available.get(a['backend'])})
    if missing:
        raise StageHeld('ml_backend_unavailable', 'training backends not installed: ' + ', '.join(missing))
    device = _device(spec)
    smoke = bool(options.get('smoke'))
    budget = deepcopy(spec['budget'])
    seeds = spec['seeds']
    if smoke:
        # The smoke rung runs the same code on one seed, few epochs and a bounded slice of each partition.
        budget['epochs'] = min(budget['epochs'], SMOKE['epochs'])
        seeds = seeds[:1]
        data = {name: {k: v[:SMOKE['rows']] for k, v in part.items()} for name, part in data.items()}
    began = time.monotonic()
    step_wall = options.get('wall_seconds')
    total = float(budget['wall_seconds'])
    if step_wall is not None:
        if budget['wall_seconds'] > step_wall and not smoke:
            raise StageRefused('ml_budget_exceeds_step', 'the specification asks for more wall time than the approved '
                               'step', {'specification': budget['wall_seconds'], 'step': step_wall})
        total = min(total, step_wall - max(MARGIN[0], MARGIN[1] * step_wall))
    per_replicate = min(float(budget.get('replicate_wall_seconds', budget['wall_seconds'])), total)
    names = admission['features']
    models, rows, exhausted = {}, [], False
    queue = [(arm, seed) for arm in spec['arms'] for seed in (seeds if arm['kind'] == 'trained' else [0])]
    for arm, seed in queue:
        key = replicate_key(arm['id'], seed)
        columns = [names.index(f) for f in feature_record['arms'][arm['id']]]
        row = {'key': key, 'arm': arm['id'], 'seed': seed, 'kind': arm['kind'], 'role': arm['role'],
               'features': feature_record['arms'][arm['id']], 'epochs': 0 if arm['kind'] == 'cut_based' else budget['epochs'],
               'wall_cap_seconds': None if arm['kind'] == 'cut_based' else per_replicate}
        if exhausted:
            rows.append({**row, 'status': 'not_started'})
            continue
        started = time.monotonic()

        def deadline(started=started):
            now = time.monotonic()
            if now - began > total or now - started > per_replicate:
                raise BudgetExhausted()
        try:
            if arm['kind'] == 'cut_based':
                model = _cut_model(arm, names)
            else:
                x = data['train']['x'][:, columns]
                if device != 'cpu' and arm['backend'] == 'torch':
                    model = _fit_device(arm, x, data['train']['y'], data['train']['weight'], seed, budget['epochs'],
                                        deadline, device)
                else:
                    model = ml_backends.fit(arm, x, data['train']['y'], data['train']['weight'], seed, budget['epochs'],
                                            deadline)
                deadline()
        except BudgetExhausted:
            exhausted = True
            rows.append({**row, 'status': 'budget_exhausted', 'wall_seconds': time.monotonic() - started})
            _checkpoint(out, spec_sha, models, rows, inputs, began)
            continue
        scores = {}
        for name in ('train', 'validation'):
            part = data[name]
            features_x = part['x'] if arm['kind'] == 'cut_based' else part['x'][:, columns]
            scores[name] = ml_backends.predict(model, features_x)
        models.update({f'{key}__{k}': np.asarray(v) for k, v in model.items()})
        rows.append({**row, 'status': 'completed', 'wall_seconds': time.monotonic() - started,
                     **{f'{name}_auc': ml_checks.roc_auc(data[name]['y'], scores[name], data[name]['weight'])
                        for name in ('train', 'validation')},
                     **{f'{name}_logloss': _logloss(data[name]['y'], scores[name], data[name]['weight'])
                        for name in ('train', 'validation')}})
        _checkpoint(out, spec_sha, models, rows, inputs, began)
    manifest = {'replicates': [r['key'] for r in rows if r['status'] == 'completed'],
                'features': {r['key']: r['features'] for r in rows if r['status'] == 'completed'}}
    with open(out / 'models.npz', 'wb') as stream:
        np.savez(stream, __manifest__=np.array(json.dumps(manifest, sort_keys=True)), **models)
    status = 'budget_exhausted' if exhausted else 'completed'
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-training', 'spec_sha256': spec_sha, 'status': status,
              'mode': 'smoke' if smoke else 'full', 'seeds': list(seeds),
              'device': device, 'budget': deepcopy(budget), 'step_wall_seconds': step_wall,
              'replicates': rows, 'models': manifest['replicates'], 'models_sha256': file_sha256(out / 'models.npz'),
              'inputs': {k: file_sha256(v) for k, v in sorted(inputs.items())},
              'wall_seconds': time.monotonic() - began, 'backends': available,
              'codes': ['ml_training_budget_exhausted'] if exhausted else []}
    _write_json(out / 'training.json', record)
    if exhausted:
        done = sum(1 for r in rows if r['status'] == 'completed')
        raise BudgetExhaustedStage('ml_training_budget_exhausted',
                                   f'the training budget ran out after {done} of {len(rows)} replicates',
                                   {'completed': done, 'replicates': len(rows), 'wall_seconds': record['wall_seconds']})
    return {'spec_sha256': spec_sha}


def load_models(path):
    with np.load(path, allow_pickle=False) as found:
        if 'placeholder' in found.files:
            raise StageRefused('ml_input_placeholder', 'models.npz is a placeholder of an incomplete stage')
        manifest = json.loads(str(found['__manifest__']))
        models = {}
        for key in manifest['replicates']:
            prefix = key + '__'
            models[key] = {name[len(prefix):]: np.asarray(found[name]) for name in found.files if name.startswith(prefix)}
    return manifest, models


SUMMARY_METRICS = ('roc_auc', 'background_rejection_at_signal_eff', 'ece', 'brier')


def summarise(rows):
    """Per arm: mean and sample standard deviation over replicates; the spread is undefined below two."""
    result = {}
    for arm in dict.fromkeys(r['id'] for r in rows):
        result[arm] = {}
        for metric in SUMMARY_METRICS:
            values = [r['metrics'][metric] for r in rows if r['id'] == arm]
            finite = [v for v in values if v is not None]
            complete = len(finite) == len(values)
            result[arm][metric] = {'mean': float(np.mean(finite)) if complete and finite else None,
                                   'spread': float(np.std(finite, ddof=1)) if complete and len(finite) >= 2 else None,
                                   'seeds': len(values), 'undefined_seeds': len(values) - len(finite)}
    return result


def _predict(model, part, columns, cut):
    from ravel.physics import ml_backends
    return ml_backends.predict(model, part['x'] if cut else part['x'][:, columns])


def evaluate(inputs, options, out):
    spec, spec_sha = _spec(inputs)
    admission = _record(inputs, 'admission', 'ml-admission', spec_sha)
    _record(inputs, 'features', 'ml-features', spec_sha)
    training = _record(inputs, 'training', 'ml-training', spec_sha)
    if training.get('mode') != 'full':
        raise StageRefused('ml_input_chain_broken', 'the evaluation reads the full training, never a smoke rung')
    if file_sha256(inputs['models']) != training['models_sha256']:
        raise StageRefused('ml_input_chain_broken', 'the models differ from the frozen training output')
    manifest, models = load_models(inputs['models'])
    data = {name: _partition_input(inputs, name, admission) for name in ('train', 'validation')}
    # The one read of the withheld partition, after the models are frozen.
    data['test'] = _partition_input(inputs, 'test', admission)
    tested = identity_sha256(data['test']['event_id'])
    if tested != admission['partitions']['test']['identity_sha256']:
        raise StageRefused('ml_withheld_population_changed', 'the withheld partition is not the admitted population')
    from ravel.physics.ml_training import metrics as score_metrics
    names = admission['features']
    point, bins = spec['metrics']['operating_point'], spec['metrics'].get('calibration_bins', 10)
    arms = {a['id']: a for a in spec['arms']}
    rows, results, arrays, overtraining_scores = [], {}, {}, {}
    for name in PARTITIONS:
        arrays[f'{name}__y'] = data[name]['y']
        arrays[f'{name}__weight'] = data[name]['weight']
    for record in training['replicates']:
        if record['status'] != 'completed':
            continue
        key, arm = record['key'], arms[record['arm']]
        cut = arm['kind'] == 'cut_based'
        columns = [names.index(f) for f in record['features']]
        scores = {name: _predict(models[key], data[name], columns, cut) for name in PARTITIONS}
        for name in PARTITIONS:
            if scores[name].shape != data[name]['y'].shape or not np.isfinite(scores[name]).all():
                raise StageRefused('ml_prediction_invalid', f'{key} predictions on {name} are invalid')
            arrays[f'{key}__{name}__score'] = scores[name]
        test_metrics, reliability, roc = score_metrics(data['test']['y'], scores['test'], data['test']['weight'], point, bins)
        results[key] = {'arm': arm['id'], 'seed': record['seed'], 'kind': arm['kind'], 'test': test_metrics,
                        'reliability': reliability, 'roc': roc,
                        'train_auc': ml_checks.roc_auc(data['train']['y'], scores['train'], data['train']['weight']),
                        'validation_auc': ml_checks.roc_auc(data['validation']['y'], scores['validation'],
                                                            data['validation']['weight'])}
        rows.append({'id': arm['id'], 'metrics': test_metrics})
        if not cut:
            overtraining_scores[key] = {part: (data[part]['y'], scores[part], data[part]['weight'])
                                        for part in ('train', 'test')}
    with open(out / 'scores.npz', 'wb') as stream:
        np.savez(stream, **arrays)
    limits = ml_checks.thresholds(spec)
    trained = sorted(overtraining_scores)
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-evaluation', 'spec_sha256': spec_sha, 'status': 'completed',
              'test_reads': 1, 'test_identity_sha256': tested, 'models_sha256': training['models_sha256'],
              'scores_sha256': file_sha256(out / 'scores.npz'), 'operating_point': point, 'calibration_bins': bins,
              'primary_arm': spec['primary_arm'], 'replicates': results, 'summary': summarise(rows),
              'overtraining': ml_checks.overtraining(overtraining_scores, trained, limits),
              'scope': 'Weighted binary classification on supplied events; seed spread is the sample standard '
                       'deviation over replicates, not a confidence interval.'}
    _write_json(out / 'evaluation.json', record)
    return {'spec_sha256': spec_sha}


def card(inputs, options, out):
    spec, spec_sha = _spec(inputs)
    admission = _record(inputs, 'admission', 'ml-admission', spec_sha)
    feature_record = _record(inputs, 'features', 'ml-features', spec_sha)
    training = _record(inputs, 'training', 'ml-training', spec_sha)
    evaluation = _record(inputs, 'evaluation', 'ml-evaluation', spec_sha)
    if training.get('mode') != 'full' or evaluation['models_sha256'] != training['models_sha256']:
        raise StageRefused('ml_input_chain_broken', 'the card describes the evaluated full training only')
    primary = next(a for a in spec['arms'] if a['id'] == spec['primary_arm'])
    limitations = ['No detector, physics or systematic-uncertainty certification; physics_validated is false.',
                   'The withheld partition was read once, after training; no model was selected on it.',
                   'Seed spread is the sample standard deviation over replicates, not a confidence interval.',
                   'Training budgets are equal epochs and wall ceilings per replicate, not equal floating-point work.']
    if evaluation['overtraining']['verdict'] != 'pass':
        limitations.append('The overtraining check failed; see the review record before any use.')
    if feature_record['items'][0]['evidence'].get('declared'):
        limitations.append('Features declared as expected to separate: '
                           + ', '.join(feature_record['items'][0]['evidence']['declared']) + '.')
    document = {
        'schema_version': SCHEMA_VERSION, 'kind': 'ml-model-card', 'spec_sha256': spec_sha, 'status': 'completed',
        'study_id': spec['study_id'], 'intended_use': spec.get('intended_use'), 'claim_scope': spec.get('claim_scope'),
        'model': {'primary_arm': primary, 'arms': deepcopy(spec['arms']), 'features': feature_record['arms'],
                  'preprocessing': {'fitted_on': feature_record['preprocessing']['fitted_on']}},
        'data': {'source': admission['source'], 'split': admission['split'],
                 'partitions': {p: {k: admission['partitions'][p][k] for k in ('rows', 'signal', 'background',
                                                                             'identity_sha256')}
                                for p in PARTITIONS}},
        'training': {'device': training['device'], 'budget': training['budget'], 'seeds': spec['seeds'],
                     'models_sha256': training['models_sha256']},
        'evaluation': {'summary': evaluation['summary'], 'operating_point': evaluation['operating_point'],
                       'overtraining': evaluation['overtraining']['verdict'],
                       'primary': {metric: values for metric, values in
                                   evaluation['summary'].get(spec['primary_arm'], {}).items()}},
        'checks': {'label_leakage': feature_record['items'][0]['verdict'],
                   'admission': {r['id']: r['verdict'] for r in admission['items']},
                   'overtraining': evaluation['overtraining']['verdict']},
        'limitations': limitations, 'physics_validated': False}
    _write_json(out / 'model_card.json', document)
    (out / 'model_card.md').write_text(render_card(document))
    return {'spec_sha256': spec_sha}


def _fmt(value):
    if value is None:
        return 'undefined'
    return f'{value:.4g}' if type(value) is float else str(value)


def render_card(document):
    primary = document['evaluation']['primary']
    lines = [f"# Model card: {document['study_id']}", '',
             f"Intended use: {document.get('intended_use') or 'not stated'}", '',
             f"Claim scope: {document.get('claim_scope') or 'not stated'}", '',
             '## Model', '', f"Primary arm: `{document['model']['primary_arm']['id']}` "
             f"({document['model']['primary_arm'].get('backend')} {document['model']['primary_arm'].get('architecture')}); "
             'declared before the withheld partition was read.', '',
             '## Data', '', f"Source digest `{document['data']['source']['sha256']}`, "
             f"{document['data']['source']['rows']} rows, split `{document['data']['split']['method']}`.", '',
             '| Partition | Rows | Signal | Background |', '|---|---:|---:|---:|']
    for name, row in document['data']['partitions'].items():
        lines.append(f"| {name} | {row['rows']} | {row['signal']} | {row['background']} |")
    lines += ['', '## Evaluation (withheld partition, mean and seed spread)', '', '| Metric | Mean | Spread |',
              '|---|---:|---:|']
    for metric, values in sorted(primary.items()):
        lines.append(f"| {metric} | {_fmt(values.get('mean'))} | {_fmt(values.get('spread'))} |")
    lines += ['', '## Checks', '', f"Label leakage: {document['checks']['label_leakage']}; overtraining: "
              f"{document['checks']['overtraining']}; admission: "
              + ', '.join(f'{k} {v}' for k, v in sorted(document['checks']['admission'].items())) + '.', '',
              '## Limitations', '', *[f'- {text}' for text in document['limitations']], '']
    return '\n'.join(lines)


def review(inputs, options, out):
    spec, spec_sha = _spec(inputs)
    admission = _record(inputs, 'admission', 'ml-admission', spec_sha)
    feature_record = _record(inputs, 'features', 'ml-features', spec_sha)
    training = _json(inputs['training'])
    if training.get('kind') != 'ml-training' or training.get('spec_sha256') != spec_sha or training.get('mode') != 'full':
        raise StageRefused('ml_input_chain_broken', 'training is not this specification\'s training record')
    evaluation = _record(inputs, 'evaluation', 'ml-evaluation', spec_sha)
    limits = ml_checks.thresholds(spec)
    data = {name: _partition_input(inputs, name, admission) for name in ('train', 'validation')}
    if file_sha256(inputs['identities']) != admission['identities_sha256']:
        raise StageRefused('ml_input_chain_broken', 'the identities differ from the admitted ones')
    with np.load(inputs['identities'], allow_pickle=False) as found:
        identities = {p: {c: found[f'{p}__{c}'].astype(str) for c in ('event_id', 'group_id')} for p in PARTITIONS}
        hashes = {p: np.asarray(found[f'{p}__row_hash']) for p in PARTITIONS}
    for name in ('train', 'validation'):
        if identity_sha256(data[name]['event_id']) != identity_sha256(identities[name]['event_id']):
            raise StageRefused('ml_input_chain_broken', f'the {name} identities differ from the partition')
    if file_sha256(inputs['scores']) != evaluation['scores_sha256']:
        raise StageRefused('ml_input_chain_broken', 'the scores differ from the evaluation record')
    if file_sha256(inputs['models']) != training.get('models_sha256') or evaluation.get('models_sha256') != training.get('models_sha256'):
        raise StageRefused('ml_input_chain_broken', 'the review models differ from the frozen evaluated training')
    manifest, models = load_models(inputs['models'])
    from ravel.physics.ml_training import metrics as score_metrics
    with np.load(inputs['scores'], allow_pickle=False) as found:
        stored = {name: np.asarray(found[name]) for name in found.files}
    by_key = {r['key']: r for r in training['replicates'] if r['status'] == 'completed'}
    if set(manifest['replicates']) != set(by_key) or set(evaluation['replicates']) != set(by_key):
        raise StageRefused('ml_input_chain_broken', 'the model and evaluation replicate populations differ')
    for name in ('train', 'validation'):
        if not all(np.array_equal(stored[f'{name}__{k}'], data[name][k]) for k in ('y', 'weight')):
            raise StageRefused('ml_input_chain_broken', 'stored score labels or weights differ from the partition')
        for key, row in by_key.items():
            columns = [admission['features'].index(f) for f in row['features']]
            predicted = _predict(models[key], data[name], columns, row['kind'] == 'cut_based')
            recorded = stored[f'{key}__{name}__score']
            if predicted.shape != recorded.shape or not np.allclose(predicted, recorded, rtol=1.e-12, atol=1.e-12):
                raise StageRefused('ml_prediction_changed', 'stored training/validation scores differ from frozen models')
    counts = {name: class_counts(data[name]) for name in ('train', 'validation')}
    counts['test'] = class_counts({'y': stored['test__y'], 'weight': stored['test__weight']})
    scores, recomputed = {}, {}
    trained = []
    for key, row in sorted(evaluation['replicates'].items()):
        parts = {p: (stored[f'{p}__y'], stored[f'{key}__{p}__score'], stored[f'{p}__weight']) for p in PARTITIONS}
        values, _, _ = score_metrics(*parts['test'], evaluation['operating_point'], evaluation['calibration_bins'])
        recomputed[key] = values
        if row['kind'] != 'cut_based':
            scores[key] = {'train': parts['train'], 'test': parts['test']}
            trained.append(key)
    items = [
        ml_checks.label_leakage(data['train']['x'], data['train']['y'], data['train']['weight'], admission['features'],
                                admission['columns'], limits),
        ml_checks.split_disjoint(identities), ml_checks.duplicate_identities(identities),
        ml_checks.duplicate_rows(hashes['train'], {'validation': hashes['validation'], 'test': hashes['test']}, limits),
        ml_checks.preprocessing_scope(data['train']['x'], data['train']['weight'], feature_record['preprocessing'], limits),
        ml_checks.statistics_sizing(counts, limits),
        ml_checks.equal_budget(training), ml_checks.replicate_count(training, spec),
        ml_checks.test_once(admission, training, evaluation),
        ml_checks.overtraining(scores, trained, limits),
        ml_checks.metric_recompute({k: v['test'] for k, v in evaluation['replicates'].items()}, recomputed, limits)]
    outcome = ml_checks.summary(items)
    record = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-review', 'spec_sha256': spec_sha,
              'status': 'completed' if outcome['passed'] else 'refused', **outcome,
              'codes': ['ml_review_failed:' + i for i in outcome['failing'] + outcome['unresolved']]}
    _write_json(out / 'review.json', record)
    if not outcome['passed']:
        first = (outcome['failing'] + outcome['unresolved'])[0]
        code = REVIEW_CODES.get(first, 'ml_review_failed')
        raise StageRefused(code, 'executable reviewer items fail: ' + ', '.join(outcome['failing'] + outcome['unresolved']),
                           {'failing': outcome['failing'], 'unresolved': outcome['unresolved']})
    return {'spec_sha256': spec_sha}


REVIEW_CODES = {'check:ml-overtraining': 'ml_overtraining', 'check:ml-label-leakage': 'ml_label_leakage',
                'check:ml-test-once': 'ml_test_once_violated', 'check:ml-split-disjoint': 'ml_split_overlap',
                'check:ml-replicate-count': 'ml_replicates_incomplete'}
RUNNERS = {'admit': admit, 'features': features, 'train': train, 'evaluate': evaluate, 'card': card, 'review': review}


# ---- receipts and the command line --------------------------------------------------------------

def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    with open(path, 'x') as stream:
        stream.write(text)


def _placeholder(path, stage, status):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.npz':
        with open(path, 'xb') as stream:
            np.savez(stream, placeholder=np.array([1]))
    elif path.suffix == '.json':
        _write_json(path, {'kind': 'ml-stage-placeholder', 'stage': stage, 'status': status, 'placeholder': True})
    else:
        path.write_text(f'Placeholder: the {stage} stage ended with status {status}; this is not a result.\n')


def run_stage(stage, inputs, options, workdir):
    """Run one stage in ``workdir`` (its outputs go under ``workdir/outputs``); return its receipt."""
    if stage not in RUNNERS:
        raise ValueError(f'unknown stage {stage!r}')
    workdir = Path(workdir)
    out = workdir / 'outputs'
    out.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    status, codes, reason, evidence = 'completed', [], None, None
    missing = [name for name in INPUTS[stage] if name not in inputs]
    try:
        if stage in WITHHELD_FORBIDDEN and 'test' in inputs:
            raise StageRefused('ml_withheld_partition_in_training' if stage == 'train' else 'ml_withheld_partition_read',
                               f'the {stage} stage is never given the withheld partition')
        if missing:
            raise StageRefused('ml_input_missing', 'the launch names no ' + ', '.join(missing))
        RUNNERS[stage](inputs, options, out)
    except StageRefused as exc:
        status, codes, reason, evidence = exc.status, [exc.code], exc.detail, exc.evidence
    placeholders = []
    for path, _ in OUTPUTS[stage]:
        target = workdir / path
        if path != RECEIPT and not target.exists():
            _placeholder(target, stage, status)
            placeholders.append(path)
    if status == 'completed' and placeholders:
        status, codes, reason = 'failed', ['ml_output_missing'], 'declared outputs were not produced: ' + ', '.join(placeholders)
    receipt = {'schema_version': SCHEMA_VERSION, 'kind': 'ml-stage-receipt', 'stage': stage,
               'operation': OPERATIONS[stage], 'status': status, 'codes': codes, 'reason': reason,
               'evidence': evidence,
               'inputs': {name: {'path': str(path), 'sha256': (file_sha256(path) if not missing and name in INPUTS[stage] and Path(path).is_file() else None)}
                          for name, path in sorted(inputs.items())},
               'outputs': {path: file_sha256(workdir / path) for path, _ in OUTPUTS[stage] if path != RECEIPT},
               'placeholders': placeholders, 'implementation': implementation(),
               'wall_seconds': time.monotonic() - began, 'physics_validated': False}
    for path in placeholders:
        receipt['outputs'][path] = file_sha256(workdir / path)
    _write_json(workdir / RECEIPT, receipt)
    return receipt


def _inputs(rows, root):
    found = {}
    for row in rows or ():
        name, sep, relative = row.partition('=')
        if not sep or not re.fullmatch(r'[a-z][a-z_]{0,31}', name) or not relative or name in found:
            raise SystemExit(f'--input expects a unique name=relative-path, not {row!r}')
        if os.path.isabs(relative) or '..' in Path(relative).parts:
            raise SystemExit(f'--input {name} must name a path inside the run root')
        found[name] = Path(os.path.normpath(os.path.join(root, relative)))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m ravel.workflow.ml_stages', description=__doc__.split('\n')[0])
    parser.add_argument('stage', choices=STAGES)
    parser.add_argument('--root', required=True, help='the run root the inputs are relative to')
    parser.add_argument('--input', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--dataset')
    parser.add_argument('--dataset-sha256')
    parser.add_argument('--wall-seconds', type=int)
    parser.add_argument('--threads', type=int, default=1, help='numerical library threads (applied before numpy loads)')
    parser.add_argument('--smoke', action='store_true', help='the training smoke rung (train stage only)')
    args = parser.parse_args(argv)
    root = args.root if os.path.isabs(args.root) else os.path.normpath(os.path.join(os.getcwd(), args.root))
    inputs = _inputs(args.input, root)
    if args.smoke and args.stage != 'train':
        raise SystemExit('--smoke applies to the train stage only')
    options = {'dataset': args.dataset, 'dataset_sha256': args.dataset_sha256, 'wall_seconds': args.wall_seconds,
               'smoke': args.smoke}
    workdir = Path(os.getcwd())
    try:
        receipt = run_stage(args.stage, inputs, options, workdir)
    except Exception as exc:  # a typed failure, never a refusal (an exception is not a scientific verdict)
        import traceback
        traceback.print_exc()
        try:
            target = workdir / RECEIPT
            if not target.exists():
                _write_json(target, {'schema_version': SCHEMA_VERSION, 'kind': 'ml-stage-receipt', 'stage': args.stage,
                                     'operation': OPERATIONS[args.stage], 'status': 'failed',
                                     'codes': ['ml_stage_exception'], 'reason': f'{type(exc).__name__}: {exc}'[:2000],
                                     'implementation': implementation(), 'physics_validated': False})
        except Exception:
            pass
        return 1
    print(json.dumps({'stage': args.stage, 'status': receipt['status'], 'codes': receipt['codes']}))
    return 1 if receipt['status'] == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
