"""Dedicated-interpreter HiggsTools child; no host-process Higgs import.

File protocol: python higgstools_worker.py REQUEST.json RESPONSE.json. Production
requires a live ordinary science worker and .venv-higgstools. API mapping must be
qualified against H-16's pinned release before native results are accepted.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile


def _need(condition, message):
    if not condition: raise ValueError(message)


def _read(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            _need(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON number: ' + value)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _delegated_parent(request, response):
    """Mirror the Contur live-parent witness without admitting a new execution."""
    delegation = request.get('delegation')
    _need(isinstance(delegation, dict), 'live ordinary-worker delegation required')
    _need(Path(sys.executable).parts[-3:] == ('.venv-higgstools', 'bin', 'python')
          and Path(sys.prefix).name == '.venv-higgstools', 'dedicated HiggsTools interpreter required')
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ravel.workflow import execution
    from ravel.workflow import science
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
          and spec['mode'] == request['operation']
          and str(Path(delegation['output']).relative_to(rd)) in state.get('outputs', [])
          and Path(response) == Path(delegation['output']) / 'higgstools/response.json',
          'child lacks live exact ordinary science-worker parent')
    for path, sha in delegation['input_hashes'].items():
        _need(_sha(path) == sha, 'delegated input pin changed')
    return delegation


def predictions(hp, bundle):
    """Translate declared inputs only. Unsupported upstream methods fail closed."""
    pred = hp.Predictions()
    for charged, rows in ((False, bundle['neutral_scalars']), (True, bundle['charged_scalars'])):
        for row in rows:
            particle = pred.addParticle(row['id'], 'charged' if charged else 'neutral',
                                        'undefined' if charged else row['cp'])
            particle.setMass(row['mass_gev'])
            if row['couplings']:
                try:
                    signature = inspect.signature(hp.effectiveCouplingInput)
                except (TypeError, ValueError) as exc:
                    raise ValueError('effective-coupling signature awaits pinned API qualification') from exc
                signature.bind(particle, **row['couplings'])
                parameters = list(signature.parameters.values())[1:]
                omitted = {p.name for p in parameters if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
                           and p.name not in row['couplings']}
                declared = set(bundle['provenance'].get('native_coupling_defaults', {}).get('parameters', []))
                _need(omitted <= declared, 'undeclared native effective-coupling defaults: ' + ', '.join(sorted(omitted-declared)))
                hp.effectiveCouplingInput(particle, **row['couplings'])
            particle.setTotalWidth(row['width_gev'])
            for decay, value in row['branching_ratios'].items():
                particle.setBr(decay, value)
            production = {}
            for rate in row['rates']:
                key = (rate['collider'], rate['production'])
                if 'production_pb' in rate:
                    _need(key not in production or production[key] == rate['production_pb'], 'inconsistent production factorization')
                    production[key] = rate['production_pb']
                else:
                    setter = getattr(particle, 'setChannelRate', None)
                    _need(callable(setter), 'pinned upstream has no direct sigma times BR setter; provide declared production/BR factorization')
                    setter(rate['collider'], rate['production'], rate['decay'], rate['sigma_br_pb'])
            for (collider, process), value in production.items():
                particle.setCxn(collider, process, value)
    return pred


def _bounds(hb, pred, bundle):
    selected = hb.Bounds(bundle['datasets']['hbdataset']['path'])(pred)
    rows = []
    for particle in bundle['neutral_scalars'] + bundle['charged_scalars']:
        r = selected.particleResults[particle['id']]
        # The selected result, rather than a maximum over observed channels,
        # carries the native expected-sensitivity selection.
        _need(r.limit is not None, 'no selected native limit for particle; cannot fabricate a limit id')
        rows.append({'id':particle['id'], 'allowed':bool(r.allowed), 'obsratio':float(r.obsratio),
                     'expected_ratio':float(r.expratio), 'selected_limit_id':str(r.limit.id)})
    return {'particles':rows}


def _signals(hs, pred, reference, bundle):
    signals = hs.Signals(bundle['datasets']['hsdataset']['path'])
    # The per-measurement accessor is a qualification seam, never a synthetic
    # decomposition of the native total. Fail if the pinned API lacks it.
    accessor = getattr(signals, 'chisqMeasurements', None)
    _need(callable(accessor), 'per-measurement HiggsSignals API awaits H-16 qualification')
    total = float(signals(pred))
    measurements = accessor(pred)
    _need(isinstance(measurements, dict), 'native per-measurement mapping required')
    n_obs = signals.nObservables
    n_obs = n_obs() if callable(n_obs) else n_obs
    _need(type(n_obs) is int and n_obs > 0, 'native integer observation count required')
    sm_total = float(signals(reference))
    return {'chi2_total':total, 'measurements':[{'id':str(k), 'chi2':float(v)} for k,v in measurements.items()],
            'n_obs':int(n_obs), 'sm_reference':{'chi2_total':sm_total, 'n_obs':int(n_obs), 'same_call':True,
                                              'input_sha256':bundle['sm_reference']['sha256']},
            'delta_chi2':total-sm_total}


def evaluate(request, request_sha256, *, hp, hb, hs):
    """Finite API seam exercised with synthetic objects in portable tests."""
    bundle = request['bundle']
    _need(request['operation'] in ('higgs-bounds', 'higgs-signals'), 'unknown operation')
    pred = predictions(hp, bundle)
    if request['operation'] == 'higgs-bounds':
        result = _bounds(hb, pred, bundle)
    else:
        reference_path = bundle['sm_reference']['path']
        _need(_sha(reference_path) == bundle['sm_reference']['sha256'], 'SM reference pin changed')
        sm_bundle = _read(reference_path)
        for dataset in sm_bundle['datasets'].values():
            root = Path(dataset['path'])
            if not root.is_absolute(): root = Path(reference_path).parent / root
            dataset['path'] = str(root.absolute())
        _need(sm_bundle['datasets'] == bundle['datasets'] and sm_bundle['mass_assignment'] == bundle['mass_assignment'],
              'SM reference settings differ')
        reference = predictions(hp, sm_bundle)
        result = _signals(hs, pred, reference, bundle)
    return {'schema_version':1, 'operation':request['operation'], 'request_sha256':request_sha256,
            'datasets':{k:v['commit'] for k,v in bundle['datasets'].items()}, **result}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    _need(len(argv) == 2, 'request and response paths required')
    request_path, response_path = map(Path, argv)
    _need(request_path.is_file() and not request_path.is_symlink(), 'regular JSON request required')
    request_sha = _sha(request_path)
    request = _read(request_path)
    delegation = _delegated_parent(request, response_path)
    # This is the sole import of GPL Higgs, after the interpreter/parent checks.
    import Higgs
    from Higgs import predictions as hp, bounds as hb, signals as hs
    _need(str(Higgs.__version__) == delegation['version'] == request['doctor_pins']['higgstools-python'], 'loaded HiggsTools version mismatch')
    result = evaluate(request, request_sha, hp=hp, hb=hb, hs=hs)
    _need(_sha(request_path) == request_sha and all(_sha(p) == sha for p,sha in delegation['input_hashes'].items()), 'inputs changed in child')
    data = json.dumps(result, allow_nan=False, indent=2) + '\n'
    _need(not response_path.exists() and not response_path.is_symlink(), 'response must be fresh')
    fd, temporary = tempfile.mkstemp(dir=response_path.parent, prefix='.response-')
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, response_path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
