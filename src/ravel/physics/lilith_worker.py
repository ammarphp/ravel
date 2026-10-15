"""Dedicated-interpreter child: REQUEST.json RESPONSE.json, live parent required.

The external package is imported only after the delegated admission witness. Its
pinned API and metadata accessors require qualification in the installed runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON number')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def delegated_parent(request, response):
    delegation = request.get('delegation')
    _need(isinstance(delegation, dict), 'live ordinary-worker delegation required')
    _need(Path(sys.executable).parts[-3:] == ('.venv-lilith', 'bin', 'python')
          and Path(sys.prefix).name == '.venv-lilith', 'dedicated interpreter required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ravel.workflow import execution, science
    rd = Path(delegation['rundir'])
    plan = _read(rd / science.PLAN)
    approval = _read(rd / science.APPROVAL)
    spec = science.execution_spec(rd)
    state = execution.load_execution(rd)['stages'].get('science', {})
    _need(os.getppid() == delegation['parent_pid'] == state.get('child_pid')
          and state.get('status') == 'running'
          and delegation['parent_identity'] == state.get('child_identity') == execution.process_identity(os.getppid())
          and delegation['fingerprint'] == state.get('fingerprint') == plan['stage_binding']['fingerprint']
          and approval.get('plan_sha256') == _sha(rd / science.PLAN)
          and spec['mode'] == 'higgs-lilith'
          and str(Path(delegation['output']).relative_to(rd)) in state.get('outputs', [])
          and Path(response) == Path(delegation['output']) / 'lilith/response.json',
          'child lacks exact live admitted parent')
    for path, sha in delegation['input_hashes'].items():
        _need(_sha(path) == sha, 'delegated input changed')
    from ravel.physics.lilith_bridge import _load
    _, expected, _, files = _load(spec['task'], Path(plan['base_dir']))
    _need({k: v for k, v in request.items() if k != 'delegation'} == expected,
          'child request differs from admitted task inputs')
    _need(delegation['input_hashes'] == {str(p): _sha(p) for p in files},
          'child inventory differs from admitted task inputs')
    return delegation


def evaluate(request, engine):
    """Pinned API seam, exercised with a synthetic engine in host unit controls."""
    from ravel.physics.lilith_bridge import finalize_result, validate_database
    validate_database(request['database'])
    model = engine.Lilith(verbose=False, timer=False)
    model.readexpinput(request['database_list'])
    _need(str(model.dbversion) == request['database']['version'], 'native database version mismatch')
    _need(type(model.exp_ndf) is int and model.exp_ndf > 0, 'native observation count unavailable')
    n_obs = model.exp_ndf
    model.readuserinput(request['xml'])
    model.computelikelihood()
    value = float(model.l)
    model.readuserinput(request['sm_xml'])
    model.computelikelihood()
    _need(model.exp_ndf == n_obs, 'native population changed for SM reference')
    _need(str(model.dbversion) == request['database']['version'], 'native database changed for SM reference')
    raw = {'schema_version': 1, 'operation': 'higgs-lilith', 'request_sha256': '',
           'database': request['database'], 'comparison_input_sha256': request['comparison_input_sha256'],
           'minus2_log_likelihood': value, 'n_obs': n_obs,
           'sm_reference': {'same_call': True, 'minus2_log_likelihood': float(model.l),
                            'n_obs': model.exp_ndf,
                            'input_sha256': hashlib.sha256(request['sm_xml'].encode()).hexdigest()}}
    if 'runtime_version' in request:
        raw['runtime_version'] = str(engine.__version__)
    # Main adds the request digest and import census after both evaluations.
    finalize_result(raw, {k: v for k, v in request.items() if k != 'delegation'}, '')
    return raw


def imported_sources(delegation):
    """Require imported external engine/dependency bytes in the admitted inventory."""
    rows = {}
    allowed = delegation['input_hashes']
    for name, module in list(sys.modules.items()):
        if name.split('.')[0] not in ('lilith', 'numpy', 'scipy', 'lxml'):
            continue
        source = getattr(module, '__file__', None)
        if not source:
            continue
        path = Path(source)
        if path.suffix == '.pyc' and path.parent.name == '__pycache__':
            path = path.parent.parent / (path.name.split('.')[0] + '.py')
        _need(path.is_file(), 'native imported source unavailable')
        digest = _sha(path)
        _need(allowed.get(str(path)) == digest, 'native imported unbound engine/dependency source')
        rows[str(path)] = digest
    _need(rows, 'native import census empty')
    return [{'path': path, 'sha256': sha} for path, sha in sorted(rows.items())]


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    _need(len(args) == 2, 'request and response paths required')
    request_path, response = map(Path, args)
    request_sha = _sha(request_path)
    request = _read(request_path)
    delegation = delegated_parent(request, response)
    import lilith
    _need(str(lilith.__version__) == request['runtime_version'], 'native runtime version mismatch')
    result = evaluate(request, lilith)
    result['request_sha256'] = request_sha
    result['runtime_version'] = str(lilith.__version__)
    result['imported_sources'] = imported_sources(delegation)
    from ravel.physics.lilith_bridge import finalize_result
    finalize_result(result, request, request_sha)
    _need(_sha(request_path) == request_sha, 'native request changed')
    for path, sha in delegation['input_hashes'].items():
        _need(_sha(path) == sha, 'native input changed')
    _need(not response.exists() and not response.is_symlink(), 'fresh response required')
    response.write_text(json.dumps(result, allow_nan=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
