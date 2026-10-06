"""Read selected continuous YODA 2 histograms without changing normalization.

Runs under the explicitly selected Rivet Python. Finalized density estimates
require matching RAW histogram geometry; arbitrary estimates/profiles fail.
"""
import math
from pathlib import Path
import sys
from ravel.workflow.state_io import atomic_json, read_json


def validate_normalized_unit(request):
    if request['normalization'] != 'normalized':
        return
    dimensions = [a['unit'] for a in request['axes'] if a['unit'] != '1']
    expected = '1'
    if request['representation'] == 'differential' and dimensions:
        expected += '/(' + '*'.join(dimensions) + ')'
    accepted = {expected}
    if len(dimensions) == 1 and request['representation'] == 'differential':
        accepted.add('1/' + dimensions[0])
    if request['unit'] not in accepted:
        raise ValueError('normalized quantity unit must be ' + expected)


def export(path, requests):
    import yoda
    if not str(yoda.__version__).startswith('2.'):
        raise ValueError('this adapter requires the YODA 2 API')
    objects = yoda.read(str(path))
    result = {}
    for request in requests:
        validate_normalized_unit(request)
        name = request['path']
        if name not in objects:
            raise ValueError('requested observable missing from upstream output: ' + name)
        obj = objects[name]
        histogram_types = ('BinnedHisto1D', 'BinnedHisto2D', 'Histo1D', 'Histo2D')
        estimate = type(obj).__name__ in ('BinnedEstimate1D', 'BinnedEstimate2D')
        raw = objects.get('/RAW' + name)
        if type(obj).__name__ not in histogram_types and not (estimate and raw is not None and type(raw).__name__ in histogram_types):
            raise ValueError('unsupported YODA quantity type: ' + type(obj).__name__)
        dim = obj.binDim()
        if dim != len(request['axes']):
            raise ValueError('declared observable dimensionality differs from YODA')
        if estimate:
            geometry = lambda h: [(tuple(b.min(d) for d in range(h.binDim())),
                                   tuple(b.max(d) for d in range(h.binDim())))
                                  for b in h.bins(includeMaskedBins=True)]
            if raw.binDim() != dim or geometry(raw) != geometry(obj):
                raise ValueError('finalized estimate and raw histogram binning differ')
        bins = []
        for b in obj.bins(includeMaskedBins=True):
            lo, hi = [b.min(d) for d in range(dim)], [b.max(d) for d in range(dim)]
            if any(x is None or not math.isfinite(x) for x in lo + hi):
                raise ValueError('categorical or unbounded bins require a distinct quantity adapter')
            if b.isMasked():
                raise ValueError('requested observable contains masked bins; define their intended comparison first')
            vol = math.prod(y-x for x, y in zip(lo, hi))
            if estimate:
                # Rivet 4 converts finalized histograms into density estimates.
                # Match the raw histogram binning before applying that convention;
                # arbitrary reference estimates/ratios do not acquire it by name.
                rb = raw.bins(includeMaskedBins=True)[len(bins)]
                if lo != [rb.min(d) for d in range(dim)] or hi != [rb.max(d) for d in range(dim)]:
                    raise ValueError('finalized estimate and raw histogram binning differ')
                low_error, high_error = b.quadSum()
                integrated = b.val() * vol
                low_error, high_error = abs(low_error) * vol, abs(high_error) * vol
                entries = rb.numEntries()
            else:
                integrated = b.sumW()
                if b.sumW2() < 0:
                    raise ValueError('negative weighted second moment')
                low_error = high_error = math.sqrt(b.sumW2())
                entries = b.numEntries()
            if vol <= 0 or not all(math.isfinite(x) for x in (integrated, low_error, high_error)):
                raise ValueError('invalid histogram bin or weighted moments')
            factor = 1./vol if request['representation'] == 'differential' else 1.
            symmetric = math.isclose(low_error, high_error, rel_tol=1e-12, abs_tol=1e-15)
            bins.append({'low': lo, 'high': hi, 'value': integrated * factor,
                         'error_low': low_error * factor, 'error_high': high_error * factor,
                         'variance': (low_error * factor)**2 if symmetric else None,
                         'integrated_sumw': integrated, 'entries': entries})
        if not bins:
            raise ValueError('requested histogram has no bins')
        if request['normalization'] == 'normalized' and not math.isclose(math.fsum(b['integrated_sumw'] for b in bins), 1., rel_tol=1e-6, abs_tol=1e-9):
            raise ValueError('normalized observable does not have unit integrated area over its finite bins: ' + name)
        result[name] = {'contract': request, 'bins': bins,
                        'storage_semantics': 'Rivet finalized density with matching RAW histogram' if estimate else 'integrated weighted histogram',
                        'flow_sumw': None if estimate else obj.sumW() - obj.sumW(False),
                        'flow_sumw2': None if estimate else obj.sumW2() - obj.sumW2(False),
                        'raw_flow_sumw': raw.sumW() - raw.sumW(False) if raw is not None else None,
                        'covariance_scope': 'upstream marginal moments; cross-bin covariance is not supplied by this histogram'}
    counters = {}
    for name, obj in objects.items():
        if '_EVTCOUNT' in name and hasattr(obj, 'sumW'):
            counters[name] = {'sumw': float(obj.sumW()), 'sumw2': float(obj.sumW2()), 'entries': float(obj.numEntries())}
    return {'yoda_version': yoda.__version__, 'all_object_paths': sorted(objects), 'observables': result, 'event_counters': counters}


if __name__ == '__main__':
    atomic_json(Path(sys.argv[3]), export(sys.argv[1], read_json(sys.argv[2])))
