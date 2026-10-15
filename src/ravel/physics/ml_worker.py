"""Manifest-interpreter array worker; fit never receives test split arrays."""
from __future__ import annotations

import importlib
import importlib.metadata
import json
from pathlib import Path
import sys
import zipfile

MAX_BYTES = 64 * 1024**2
MAX_CONTROL_BYTES = 1024**2


def probe():
    result = {'torch': False, 'torch-geometric': False, 'versions': {}}
    for backend, package in (('torch', 'torch'), ('torch-geometric', 'torch_geometric')):
        try:
            importlib.import_module(package)
            result['versions'][backend] = importlib.metadata.version(package)
            result[backend] = True
        except (ImportError, OSError, RuntimeError):
            pass
    result['torch-geometric'] &= result['torch']
    return result


def load_arrays(path, allowed=None):
    """Bound both compressed and expanded bytes; reject names before decoding."""
    import numpy as np
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('array file exceeds byte ceiling or is missing')
    with zipfile.ZipFile(path) as archive:
        rows = archive.infolist()
        names = [r.filename.removesuffix('.npy') for r in rows]
        if (sum(r.file_size for r in rows) > MAX_BYTES or len(names) != len(set(names))
                or any(not r.filename.endswith('.npy') or '/' in r.filename for r in rows)
                or allowed is not None and not set(names) <= set(allowed)):
            raise ValueError('worker arrays violate custody or expanded byte ceiling')
    with np.load(path, allow_pickle=False) as archive:
        return {k: archive[k] for k in archive.files}


def validate_arrays(arrays, action):
    import numpy as np
    required = {'train_x', 'train_y', 'train_weight'} if action == 'fit' else {'predict_x'}
    validation = {'val_x', 'val_y', 'val_weight'} if action == 'fit' else set()
    if set(arrays) not in (required, required | validation):
        raise ValueError('worker arrays allow training and validation only for fit; unlabeled prediction features only for predict')
    if sum(np.asarray(a).nbytes for a in arrays.values()) > MAX_BYTES:
        raise ValueError('worker arrays exceed memory ceiling')
    for value in arrays.values():
        a = np.asarray(value)
        if a.dtype.kind not in 'fiu' or not np.isfinite(a).all():
            raise ValueError('worker arrays must be finite numeric values')
    for split in (('train', 'val') if validation <= set(arrays) and action == 'fit' else ('train',) if action == 'fit' else ('predict',)):
        x = np.asarray(arrays[split + '_x'])
        if x.ndim not in (2, 3) or not all(x.shape):
            raise ValueError('worker feature arrays require nonempty event dimensions')
        if action == 'fit':
            y, weight = np.asarray(arrays[split + '_y']), np.asarray(arrays[split + '_weight'])
            if y.shape != (len(x),) or weight.shape != y.shape or not np.isin(y, [0, 1]).all() or np.any(weight < 0) or weight.sum() <= 0:
                raise ValueError('invalid label or weight arrays')
    if action == 'fit' and 'val_x' in arrays and arrays['val_x'].shape[1:] != arrays['train_x'].shape[1:]:
        raise ValueError('validation feature arrays differ from training shape')


def _local_backends():
    # The ML environment need not contain an installed copy of RAVEL.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ravel.physics import ml_backends
    return ml_backends


def validate_state(state):
    """Accept only the numeric checkpoint schema of the installed algorithms."""
    import numpy as np
    if 'graph_nodes' in state:
        expected = {'mean', 'scale', 'graph_nodes', 'graph_features', 'graph_hidden', 'edge_index',
                    'parameter:conv.bias', 'parameter:conv.lin.weight',
                    'parameter:head.weight', 'parameter:head.bias'}
    else:
        expected = {'mean', 'scale', 'w', 'b'} | ({'v', 'c'} if 'v' in state else set())
    if set(state) != expected:
        raise ValueError('worker model state arrays outside checkpoint schema')
    if any(np.asarray(a).dtype.kind not in 'fiu' or not np.isfinite(a).all() for a in state.values()):
        raise ValueError('worker model state requires finite numeric arrays')
    if np.any(state['scale'] <= 0):
        raise ValueError('worker model state scale must be positive')


def execute(request):
    import numpy as np
    common = {'schema_version', 'action', 'arrays', 'output'}
    action = request.get('action')
    expected = common | ({'arm', 'seed', 'epochs'} if action == 'fit' else {'backend', 'state'})
    if type(request.get('schema_version')) is not int or request['schema_version'] != 1 or action not in ('fit', 'predict') or set(request) != expected:
        raise ValueError('worker request fields refuse test split arrays and undeclared inputs')
    allowed = {'train_x', 'train_y', 'train_weight', 'val_x', 'val_y', 'val_weight'} if action == 'fit' else {'predict_x'}
    arrays = load_arrays(request['arrays'], allowed)
    validate_arrays(arrays, action)
    if action == 'fit':
        if type(request['seed']) is not int or request['seed'] < 0 or type(request['epochs']) is not int or request['epochs'] <= 0:
            raise ValueError('worker requires integer seed and positive epochs')
        arm = request['arm']
        if set(arm) - {'id', 'backend', 'architecture', 'config'} or arm.get('backend') not in ('torch', 'torch-geometric'):
            raise ValueError('worker supports declared native ML arms only')
        config_keys = ({'learning_rate', 'hidden_units', 'nodes', 'edge_index'} if arm.get('architecture') == 'gnn'
                       else {'learning_rate', 'hidden_units'} if arm.get('architecture') == 'mlp' else {'learning_rate'})
        if not isinstance(arm.get('config'), dict) or set(arm['config']) != config_keys:
            raise ValueError('worker model configuration fields outside array custody')
        backends = _local_backends()
        if arm.get('architecture') not in backends.FAMILIES[arm['backend']]:
            raise ValueError('unsupported ML architecture')
        result = backends._runtime_local_fit(arm, arrays['train_x'], arrays['train_y'], arrays['train_weight'],
                                            request['seed'], request['epochs'], lambda: None)
    else:
        if request['backend'] not in ('torch', 'torch-geometric'):
            raise ValueError('unsupported prediction backend')
        state = load_arrays(request['state'])
        validate_state(state)
        result = {'scores': _local_backends()._runtime_local_predict(state, arrays['predict_x'])}
    if not result or any(np.asarray(v).dtype.kind == 'O' for v in result.values()):
        raise ValueError('invalid worker output arrays')
    with Path(request['output']).open('xb') as stream:
        np.savez(stream, **result)


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError('duplicate worker request field')
        result[key] = value
    return result


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args == ['probe']:
        print(json.dumps(probe(), allow_nan=False))
    elif len(args) == 2 and args[0] == 'execute':
        with Path(args[1]).open('rb') as stream:
            raw = stream.read(MAX_CONTROL_BYTES + 1)
        if len(raw) > MAX_CONTROL_BYTES:
            raise ValueError('worker request exceeds byte ceiling')
        def reject(value):
            raise ValueError('nonfinite worker request')
        execute(json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject))
    else:
        raise ValueError('worker requires probe or execute with one request file')


if __name__ == '__main__':
    main()
