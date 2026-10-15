"""Optional RooFit minimizer for the general captured amplitude objective.

The callback evaluates the same captured numerical law; this bridge does not
constitute an independent amplitude implementation. Native execution needs the
ordinary approved science worker and a supplied pinned runtime closure.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .. import amplitude_basis as ab, amplitude_response
from . import record

ASSET = Path(__file__).parents[2]/'data/amplitude_fit/RavelCachedObjective.cxx'


def runtime_inputs(ctx, spec):
    from .. import regional_expected
    ab.require(type(spec) is dict and set(spec) == {'version', 'files'}, 'native runtime needs version and complete file pins')
    ab.text(spec['version'], 'native version')
    ab.require(type(spec['files']) is list and spec['files'], 'complete native runtime file census required')
    paths = []
    for pin in spec['files']:
        ab.require(type(pin) is dict and set(pin) == {'path', 'sha256'}, 'runtime file needs path and sha256')
        path = ctx.path(pin['path'])
        observed = amplitude_response.observation(path)
        ab.require(observed['sha256'] == pin['sha256'], 'runtime file bytes differ')
        ctx.pins[str(path)] = pin['sha256']
        pin['path'] = str(path)
        paths.append(path)
    code = [ASSET, Path(__file__), Path(regional_expected.__file__)]
    for path in code:
        ctx.pins[str(path)] = amplitude_response.observation(path)['sha256']
    ab.require(len(set(paths)) == len(paths), 'native runtime census repeats files')
    return [*paths, *code]


def authorized(task, output):
    from ravel.workflow import science
    out = Path(output).resolve()
    for root in out.parents:
        if (root/'inputs/science-plan.json').is_file():
            plan = science.verify_worker(root)
            spec = science.execution_spec(root)
            ab.require(spec['mode'] == 'differential-likelihood' and spec['task'] == task
                       and out.is_relative_to(root/plan['output_directory']), 'native profile approved task/output differs')
            return
    raise ValueError('native cached profile requires the ordinary admitted science worker')


def load(runtime):
    before = [amplitude_response.observation(p['path']) for p in runtime['files']]
    ab.require(all(p['sha256'] == q['sha256'] for p, q in zip(before, runtime['files'])), 'native runtime changed')
    import ROOT
    ab.require(str(ROOT.gROOT.GetVersion()) == runtime['version'], 'loaded ROOT version differs')
    loaded = libraries(ROOT, runtime)
    ROOT.gROOT.SetBatch(True)
    ab.require(not hasattr(ROOT, 'RavelCachedObjective'), 'fresh native objective interpreter required')
    ab.require(ROOT.gInterpreter.Declare(ASSET.read_text()), 'native objective declaration failed')
    return ROOT, before, loaded


def libraries(ROOT, runtime):
    import sys
    declared = {str(Path(p['path']).resolve()): p['sha256'] for p in runtime['files']}
    loaded = []
    for token in str(ROOT.gSystem.GetLibraries()).split():
        if token.startswith('-L'):
            continue
        if token.startswith('-l'):
            resolved = ROOT.gSystem.DynamicPathName('lib'+token[2:]+'.so', True)
            if not resolved:
                resolved = ROOT.gSystem.DynamicPathName('lib'+token[2:]+'.dylib', True)
            ab.require(bool(resolved), 'loaded native library cannot be resolved')
            path = Path(str(resolved)).resolve()
        else:
            path = Path(token).resolve()
        observed = amplitude_response.observation(path)
        ab.require(declared.get(str(path)) == observed['sha256'], 'loaded library outside supplied closure')
        loaded.append(observed)
    ab.require(loaded, 'actual native library census absent')
    module = Path(ROOT.__file__).resolve()
    ab.require(declared.get(str(module)) == hashlib.sha256(module.read_bytes()).hexdigest(), 'loaded ROOT module outside supplied closure')
    interpreter = Path(sys.executable).resolve()
    ab.require(declared.get(str(interpreter)) == amplitude_response.observation(interpreter)['sha256'],
               'actual Python interpreter outside supplied native closure')
    return loaded


def minimize(ROOT, parameters, start, fixed, evaluate, path, tolerance):
    """Save and re-read each raw RooFitResult, then restore all coordinate errors."""
    from .. import regional_expected as native
    workspace = ROOT.RooWorkspace('cached_coordinates')
    for p in parameters:
        variable = ROOT.RooRealVar(p['name'], p['label'], p['value'], p['min'], p['max'])
        variable.setConstant(p['constant'])
        variable.setError(p['error'])
        getattr(workspace, 'import')(variable)
    shape = {'coordinates': {p['name']: {} for p in parameters}}
    initial = native._state(workspace, shape)
    errors = native._errors(workspace, initial)
    names = [p['name'] for p in parameters]
    args = ROOT.RooArgList()
    for name in names:
        args.add(workspace.var(name))
    # RooFit's error level is 0.5: the callback returns NLL, not twice NLL.
    callback = lambda values: .5*evaluate(dict(zip(names, map(float, values))))
    objective = ROOT.RavelCachedObjective('cached_objective', args, callback)
    raw = {}
    try:
        for name, value in start.items():
            workspace.var(name).setVal(value)
        for name, value in fixed.items():
            workspace.var(name).setVal(value)
            workspace.var(name).setConstant(True)
        state = native._state(workspace, shape)
        fit = native._profile_fit(ROOT, objective, workspace, shape, path, state)
        raw['fit'] = record.clean(fit)
        fitted = {name: float(workspace.var(name).getVal()) for name in names}
        if fit['performed']:
            source = ROOT.TFile.Open(str(path), 'READ')
            ab.require(bool(source) and not source.IsZombie(), 'raw fit cannot be reopened')
            try:
                saved = source.Get('profile_fit')
                ab.require(bool(saved), 'raw profile fit is absent')
                readback = {'status': int(saved.status()), 'cov_qual': int(saved.covQual()), 'edm': float(saved.edm()),
                            'min_nll': float(saved.minNll()), 'invalid_nll': int(saved.numInvalidNLL()),
                            'status_history': [{'label': str(saved.statusLabelHistory(i)), 'code': int(saved.statusCodeHistory(i))}
                                               for i in range(saved.numStatusHistory())],
                            'floating_parameters': [{'name': v.GetName(), 'value': float(v.getVal()), 'error': float(v.getError())}
                                                    for v in saved.floatParsFinal()],
                            'constant_parameters': [{'name': v.GetName(), 'value': float(v.getVal())} for v in saved.constPars()],
                            'covariance': [[float(saved.covarianceMatrix()[i][j]) for j in range(saved.floatParsFinal().getSize())]
                                           for i in range(saved.floatParsFinal().getSize())]}
            finally:
                source.Close()
            ab.require(record.clean(readback) == record.clean({k: fit[k] for k in readback}), 'raw fit fields changed on readback')
            raw['readback'] = record.clean(readback)
            raw['raw_result'] = amplitude_response.observation(path)
            accepted = (fit['status'] == fit['migrad_status'] == fit['hesse_status'] == 0 and fit['cov_qual'] == 3
                        and math.isfinite(fit['edm']) and fit['edm'] <= tolerance and fit['invalid_nll'] == 0)
        else:
            accepted = True
        raw.update(initial_state=initial, initial_errors=errors, final_state=native._state(workspace, shape))
    finally:
        native._restore(workspace, initial)
        native._restore_errors(workspace, errors)
    raw.update(restored_state=native._state(workspace, shape), restored_errors=native._errors(workspace, initial))
    ab.require(raw['restored_state'] == initial and raw['restored_errors'] == errors, 'native coordinate restoration differs')
    return fitted, raw, accepted
