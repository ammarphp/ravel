"""Read declared YODA 2 histograms, scalar counters and profile means.

Runs under the explicitly selected Rivet Python. Finalized density estimates
require matching RAW histogram geometry; arbitrary estimates/profiles fail.
Scalar counters and profiles retain upstream moments, with no bin-width conversion.
Profile means retain YODA's marginal standard-error convention, including its
absolute weighted-variance convention for signed weights. Those errors are not
an experimental covariance or a calibrated signed-weight inference model.
"""
import math
from decimal import Decimal, InvalidOperation, localcontext
import gzip
import re
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


def validate_profile_request(request):
    """A profile's dependent mean is neither a bin integral nor a density."""
    if (request['representation'] != 'mean' or request['normalization'] != 'absolute'
            or not isinstance(request['axes'], list) or not 1 <= len(request['axes']) <= 2):
        raise ValueError('profile_mean requires one or two axes, mean representation and absolute normalization')


def _geometry(obj):
    dim = obj.binDim()
    return [(tuple(b.min(d) for d in range(dim)), tuple(b.max(d) for d in range(dim)))
            for b in obj.bins(includeMaskedBins=True)]


def _rounded_token(token):
    """Enclose a decimal text token's pre-serialization value by half a digit.

    The interval comes from the actual token exponent/precision, never from a
    data-fitted relative tolerance. Binary endpoints are rounded outwards.
    """
    with localcontext() as context:
        context.prec = max(len(token) + 30, 80)
        try:
            value = Decimal(token)
        except InvalidOperation as exc:
            raise ValueError('invalid YODA decimal token') from exc
        if not value.is_finite():
            raise ValueError('nonfinite YODA decimal token')
        half_digit = Decimal(5).scaleb(value.as_tuple().exponent - 1)
        low, high = float(value-half_digit), float(value+half_digit)
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError('YODA rounding interval is nonfinite')
    return (math.nextafter(low, -math.inf), math.nextafter(high, math.inf))


def _interval(values):
    low, high = min(values), max(values)
    if not math.isfinite(low) or not math.isfinite(high):
        raise ValueError('profile rounding propagation overflows')
    return math.nextafter(low, -math.inf), math.nextafter(high, math.inf)


def _add(a, b):
    return _interval((a[0]+b[0], a[1]+b[1]))


def _subtract(a, b):
    return _interval((a[0]-b[1], a[1]-b[0]))


def _yoda_subtract(a, b):
    """Enclose YODA2.1.3 subtract()/fuzzyEquals(), including zero snapping.

    MathUtils.h uses |a-b| < 1e-5*(|a|+|b|)/2 or both |a|,|b|<1e-5.
    A possible zero branch is included; an unresolved denominator is refused.
    """
    difference = _subtract(a, b)
    aa, bb, delta = _absolute(a), _absolute(b), _absolute(difference)
    threshold = _multiply((1e-5/2, 1e-5/2), _add(aa, bb))
    if delta[1] < threshold[0] or max(aa[1], bb[1]) < 1e-5:
        return 0., 0.
    if delta[0] < threshold[1] or (aa[0] < 1e-5 and bb[0] < 1e-5):
        return min(difference[0], 0.), max(difference[1], 0.)
    return difference


def _multiply(a, b):
    return _interval(tuple(x*y for x in a for y in b))


def _divide(a, b):
    if b[0] <= 0 <= b[1]:
        raise ValueError('serialized profile moments do not resolve a nonzero denominator')
    return _interval(tuple(x/y for x in a for y in b))


def _square(a):
    low = 0. if a[0] <= 0 <= a[1] else min(x*x for x in a)
    high = max(x*x for x in a)
    result = _interval((low, high))
    return (0. if low == 0 else result[0], result[1])


def _absolute(a):
    if a[0] <= 0 <= a[1]:
        return 0., max(abs(x) for x in a)
    return min(abs(x) for x in a), max(abs(x) for x in a)


def _sqrt(a):
    if a[1] < 0:
        raise ValueError('profile rounding interval is negative under a square root')
    low = math.sqrt(max(a[0], 0.))
    return (0. if low == 0 else math.nextafter(low, -math.inf),
            math.nextafter(math.sqrt(a[1]), math.inf))


def _profile_rounding_bounds(tokens, dim):
    """Propagate actual W,Q,A,B text intervals through YODA's mean/stdErr.

    A=sum(w*y), B=sum(w*y*y), Q=sum(w*w). The weighted unbiased variance
    is abs((B*W-A*A)/(W*W-Q)); stdErr squared additionally multiplies Q/W².
    This is a numerical enclosure of serialized native moments, not a new
    uncertainty estimator or an experimental/statistical calibration.
    """
    keys = ('sumW', 'sumW2', f'sumW(A{dim+1})', f'sumW2(A{dim+1})')
    w, q, a, b = (_rounded_token(tokens[k]) for k in keys)
    if q[0] < 1e-5:
        raise ValueError('serialized profile second moment does not resolve YODA nonzero effective entries')
    w2 = _square(w)
    variance = _absolute(_divide(_yoda_subtract(_multiply(b, w), _square(a)), _yoda_subtract(w2, q)))
    # Mirror the native floating-point evaluation order. Algebraic equivalence
    # alone does not enclose each source intermediate's rounding.
    effective_entries = _divide(w2, q)
    stderr = _sqrt(_divide(variance, effective_entries))
    return {'mean': list(_divide(a, w)), 'stderr': list(stderr),
            'moment_tokens': {k: tokens[k] for k in keys},
            'moment_intervals': {k: list(_rounded_token(tokens[k])) for k in keys},
            'formula': 'mean=A/W; effective_entries=(W*W)/Q; stderr=sqrt(abs(subtract(B*W,A*A)/subtract(W*W,Q))/effective_entries)',
            'native_arithmetic': 'YODA2.1.3 StatsUtils.h and MathUtils.h: both subtractions use fuzzyEquals zero snapping at source tolerance1e-5; Q<1e-5 makes effective entries undefined.',
            'precision_policy': 'Half the actual last decimal digit per serialized token; outward binary interval arithmetic, no global fitted tolerance.'}


def _profile_text_rows(path, name, obj):
    opener = gzip.open if str(path).endswith('.gz') else open
    try:
        with opener(path, 'rt', encoding='utf-8') as stream:
            text = stream.read()
    except (OSError, UnicodeError) as exc:
        raise ValueError('finalized profile estimate requires retained source-format precision evidence') from exc
    blocks = re.findall(r'^BEGIN YODA_(?:PROFILE|ESTIMATE)[12]D_V3 ([^\n]+)\n(.*?)^END YODA_(?:PROFILE|ESTIMATE)[12]D_V3\s*$', text, re.M | re.S)
    matching = [body for label, body in blocks if label == name]
    if len(matching) != 1:
        raise ValueError('profile rounding requires one matching YODA V3 text object')
    columns, rows = None, []
    for line in matching[0].splitlines():
        if line.startswith('# sumW') or line.startswith('# value '):
            columns = line[1:].split()
        elif columns is not None and line.strip() and not line.startswith('#'):
            fields = line.split()
            if len(fields) != len(columns):
                raise ValueError('profile source-format column population differs')
            rows.append(dict(zip(columns, fields)))
    native = obj.bins(includeOverflows=True, includeMaskedBins=True)
    if len(rows) != len(native):
        raise ValueError('profile source-format bin population differs')
    return {tuple([b.min(d) for d in range(obj.binDim())] + [b.max(d) for d in range(obj.binDim())]): row
            for b, row in zip(native, rows)}


def _estimate_rounding_bounds(tokens, native):
    value = _rounded_token(tokens['value'])
    if float(tokens['value']) != float(native.val()):
        raise ValueError('finalized profile estimate differs from retained source-format value')
    errors = []
    for prefix in ('errDn', 'errUp'):
        columns = [k for k in tokens if k.startswith(prefix+'(')]
        if not columns:
            raise ValueError('finalized profile estimate has no serialized marginal errors')
        total = (0., 0.)
        for column in columns:
            total = _add(total, _square(_rounded_token(tokens[column])))
        errors.append(list(_sqrt(total)))
    for actual, enclosure in zip((abs(float(x)) for x in native.quadSum()), errors):
        if not enclosure[0] <= actual <= enclosure[1]:
            raise ValueError('finalized profile estimate differs from retained source-format errors')
    return {'value': list(value), 'error_low': errors[0], 'error_high': errors[1],
            'tokens': tokens}


def _overlap(a, b):
    return max(a[0], b[0]) <= min(a[1], b[1])


def _profile_moments(bin, dim):
    """Keep the actual running sums, not histogram-derived mean errors.

    In YODA, sumWX2 means sum(w*x*x), whereas sumW2 means sum(w*w).
    These are not sufficient statistics for an arbitrary independent-group
    covariance of the ratio sum(w*y)/sum(w).
    """
    coordinates = 'XYZ'[:dim + 1]
    result = {'sumw': float(bin.sumW()), 'sumw2': float(bin.sumW2()),
              'entries': float(bin.numEntries()),
              'coordinate_sumw': [float(getattr(bin, 'sumW' + c)()) for c in coordinates],
              'coordinate_squared_sumw': [float(getattr(bin, 'sumW' + c + '2')()) for c in coordinates],
              'coordinate_cross_sumw': [float(getattr(bin, 'sumW' + a + b)())
                                        for i, a in enumerate(coordinates) for b in coordinates[i + 1:]]}
    values = [result['sumw'], result['sumw2'], result['entries'],
              *result['coordinate_sumw'], *result['coordinate_squared_sumw'], *result['coordinate_cross_sumw']]
    if not all(math.isfinite(v) for v in values) or result['sumw2'] < 0 or result['entries'] < 0:
        raise ValueError('invalid profile running moments or entries')
    return result


def _profile_mean(name, obj, raw, request, source_path=None):
    validate_profile_request(request)
    profile_types = ('BinnedProfile1D', 'BinnedProfile2D', 'Profile1D', 'Profile2D')
    estimates = ('BinnedEstimate1D', 'BinnedEstimate2D')
    selected_raw = name.startswith('/RAW/') and type(obj).__name__ in profile_types
    if selected_raw:
        raw = obj
    estimate = type(obj).__name__ in estimates
    if type(obj).__name__ not in profile_types and not estimate:
        raise ValueError('profile_mean requires a Profile or finalized BinnedEstimate')
    if raw is None or type(raw).__name__ not in profile_types:
        raise ValueError('profile_mean requires a matching RAW Profile')
    dim = obj.binDim()
    if dim != len(request['axes']) or raw.binDim() != dim or _geometry(raw) != _geometry(obj):
        raise ValueError('profile and matching RAW Profile binning differ')
    bins = []
    raw_text = _profile_text_rows(source_path, '/RAW'+name, raw) if estimate else None
    estimate_text = _profile_text_rows(source_path, name, obj) if estimate else None
    for b, rb in zip(obj.bins(includeMaskedBins=True), raw.bins(includeMaskedBins=True)):
        lo, hi = [b.min(d) for d in range(dim)], [b.max(d) for d in range(dim)]
        if any(x is None or not math.isfinite(x) for x in lo + hi) or any(y <= x for x, y in zip(lo, hi)):
            raise ValueError('categorical or unbounded profile bins require a distinct quantity adapter')
        if b.isMasked() or rb.isMasked():
            raise ValueError('requested profile contains masked bins; define their intended comparison first')
        raw_moments = _profile_moments(rb, dim)
        final_moments = None if estimate else _profile_moments(b, dim)
        if final_moments is not None and not math.isclose(final_moments['entries'], raw_moments['entries'], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('profile and matching RAW Profile entries differ')
        source = rb if estimate else b
        mean, error = float(source.mean(dim + 1)), float(source.stdErr(dim + 1))
        if not all(math.isfinite(v) for v in (mean, error)) or error < 0:
            raise ValueError('profile mean or upstream standard error is undefined; empty, cancelling or low-statistics bin')
        if estimate:
            value = float(b.val())
            low_error, high_error = (abs(float(v)) for v in b.quadSum())
            # A RAW association alone cannot establish the semantics of a
            # ratio, asymmetry or another finalize() transformation. Only the
            # untransformed native profile mean and error are admitted here.
            key = tuple(lo+hi)
            tokens = raw_text[key]
            for column, expected in [('sumW', raw_moments['sumw']), ('sumW2', raw_moments['sumw2']),
                    (f'sumW(A{dim+1})', raw_moments['coordinate_sumw'][-1]),
                    (f'sumW2(A{dim+1})', raw_moments['coordinate_squared_sumw'][-1])]:
                if float(tokens[column]) != expected:
                    raise ValueError('profile moments differ from retained source-format values')
            rounding = {'raw': _profile_rounding_bounds(tokens, dim),
                        'estimate': _estimate_rounding_bounds(estimate_text[key], b)}
            if not all(math.isfinite(v) for v in (value, low_error, high_error)) or not all(
                    _overlap(left, right) for left, right in (
                        (rounding['raw']['mean'], rounding['estimate']['value']),
                        (rounding['raw']['stderr'], rounding['estimate']['error_low']),
                        (rounding['raw']['stderr'], rounding['estimate']['error_high']))):
                raise ValueError('finalized profile estimate differs from RAW mean/errors; derived profile transformation needs a distinct contract')
        else:
            value, low_error, high_error = mean, error, error
            rounding = None
        variance = low_error * low_error
        if not math.isfinite(variance):
            raise ValueError('invalid profile marginal variance')
        bins.append({'low': lo, 'high': hi, 'value': value, 'error_low': low_error,
                     'error_high': high_error, 'variance': variance, 'integrated_sumw': None,
                     'entries': raw_moments['entries'], 'raw_profile': raw_moments,
                     'final_profile': final_moments, 'serialization_bounds': rounding})
    if not bins:
        raise ValueError('requested profile has no bins')
    return {'contract': request, 'quantity_kind': 'profile_mean', 'bins': bins,
            'storage_semantics': 'untransformed finalized profile mean with matching RAW Profile' if estimate else 'native weighted profile mean',
            'support_tier': 'native profile moments and upstream marginal mean errors; no measurement inference',
            'raw_mean_comparison': {'scope': 'Actual source-format decimal precision intervals propagated through weighted profile moments; consistency only, source semantics still require routine review'} if estimate else None,
            'moment_semantics': {'coordinate_order': [a['name'] for a in request['axes']] + ['dependent_variable'],
                                 'cross_order': [[i, j] for i in range(dim + 1) for j in range(i + 1, dim + 1)],
                                 'sumw2': 'sum(weight^2)', 'coordinate_squared_sumw': 'sum(weight*coordinate^2)',
                                 'coordinate_cross_sumw': 'sum(weight*coordinate_i*coordinate_j)'},
            'flow_sumw': None if estimate else obj.sumW() - obj.sumW(False),
            'flow_sumw2': None if estimate else obj.sumW2() - obj.sumW2(False),
            'raw_flow_sumw': raw.sumW() - raw.sumW(False),
            'raw_flow_sumw2': raw.sumW2() - raw.sumW2(False),
            'covariance_scope': 'YODA weighted-mean marginal standard errors only; running moments do not supply cross-bin or independent-group covariance',
            'uncertainty_scope': 'YODA stdErr of the dependent coordinate, with absolute weighted variance for signed weights; inferential calibration is not established',
            'unit_scope': 'caller-declared dependent-variable unit; no bin-width conversion or unit-area normalization'}


def _counter_moments(obj):
    moments = {'sumw': float(obj.sumW()), 'sumw2': float(obj.sumW2()),
               'entries': float(obj.numEntries())}
    if not all(math.isfinite(x) for x in moments.values()) or moments['sumw2'] < 0 or moments['entries'] < 0:
        raise ValueError('invalid scalar Counter weighted moments or entries')
    return moments


def _scalar_counter(name, obj, raw, request):
    if request['axes'] != [] or request['representation'] != 'integrated' or request['normalization'] != 'absolute':
        raise ValueError('scalar_counter requires zero axes, integrated representation and absolute normalization')
    if type(obj).__name__ not in ('Counter', 'Estimate0D'):
        raise ValueError('scalar_counter requires a Counter or finalized Estimate0D')
    # A selected RAW Counter supplies its own moments. Finalized estimates must
    # never acquire Counter moments merely from their reported value/errors.
    selected_raw = name.startswith('/RAW/') and type(obj).__name__ == 'Counter'
    if selected_raw:
        raw = obj
    if raw is None or type(raw).__name__ != 'Counter':
        raise ValueError('scalar_counter requires a matching RAW Counter')
    raw_moments = _counter_moments(raw)
    final_moments = _counter_moments(obj) if type(obj).__name__ == 'Counter' else None
    if final_moments is not None:
        if not math.isclose(final_moments['entries'], raw_moments['entries'], rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError('scalar Counter and matching RAW Counter entries differ')
        value = final_moments['sumw']
        low_error = high_error = math.sqrt(final_moments['sumw2'])
        variance = final_moments['sumw2']
    else:
        value = float(obj.val())
        low_error, high_error = (abs(float(x)) for x in obj.quadSum())
        variance = low_error * low_error if math.isclose(low_error, high_error, rel_tol=1e-12, abs_tol=1e-15) else None
    if not all(math.isfinite(x) for x in (value, low_error, high_error)) or variance is not None and not math.isfinite(variance):
        raise ValueError('invalid scalar Counter value or marginal errors')
    return {'contract': request, 'quantity_kind': 'scalar_counter',
            'bins': [{'low': [], 'high': [], 'value': value,
                      'error_low': low_error, 'error_high': high_error,
                      'variance': variance, 'integrated_sumw': value,
                      'entries': raw_moments['entries']}],
            'storage_semantics': ('RAW integrated weighted Counter' if selected_raw else
                                  'finalized scalar estimate with matching RAW Counter' if final_moments is None else
                                  'integrated weighted Counter with matching RAW Counter'),
            'final_counter': None if selected_raw else final_moments,
            'raw_counter': raw_moments,
            'flow_sumw': None, 'flow_sumw2': None, 'raw_flow_sumw': None,
            'covariance_scope': 'upstream scalar marginal moments/errors only; cross-counter and event-group covariance is not supplied',
            'unit_scope': 'caller-declared unit for upstream output; no conversion or normalization inferred; routine normalization requires review'}


def export(path, requests):
    import yoda
    if not str(yoda.__version__).startswith('2.'):
        raise ValueError('this adapter requires the YODA 2 API')
    objects = yoda.read(str(path))
    result = {}
    cumulant = None
    if any(r.get('quantity_kind')=='native_cumulant' for r in requests):
        if str(yoda.__version__) != '2.1.3':
            raise ValueError('native cumulant writer semantics require reviewed YODA2.1.3')
        from ravel.physics.native_cumulant import export_family
        cumulant = export_family(path, requests)
    for request in requests:
        name = request['path']
        if name not in objects:
            raise ValueError('requested observable missing from upstream output: ' + name)
        obj = objects[name]
        raw = objects.get('/RAW' + name)
        kind = request.get('quantity_kind')
        if kind == 'native_cumulant':
            result[name] = cumulant['observables'][name]
            continue
        if kind == 'scalar_counter':
            result[name] = _scalar_counter(name, obj, raw, request)
            continue
        if kind == 'profile_mean':
            if str(yoda.__version__) != '2.1.3':
                raise ValueError('profile uncertainty/rounding semantics require reviewed YODA2.1.3')
            result[name] = _profile_mean(name, obj, raw, request, path)
            continue
        if kind == 'native_categorical':
            if str(yoda.__version__) != '2.1.3':
                raise ValueError('native categorical serialized semantics require reviewed YODA2.1.3')
            from ravel.physics.native_categorical import export_quantity
            result[name] = export_quantity(path, request)
            continue
        if kind == 'native_density_estimate':
            if str(yoda.__version__) != '2.1.3':
                raise ValueError('native density serialized semantics require reviewed YODA2.1.3')
            from ravel.physics.native_density import transport
            result[name] = transport(path, request)
            continue
        if kind == 'native_derived_estimate':
            if str(yoda.__version__) != '2.1.3':
                raise ValueError('native derived serialized semantics require reviewed YODA2.1.3')
            from ravel.physics.native_estimate import transport
            result[name] = transport(path, request)
            continue
        if kind is not None:
            raise ValueError('unsupported explicit YODA quantity_kind: ' + str(kind))
        if request['representation'] not in ('integrated', 'differential') or request['normalization'] not in ('absolute', 'normalized'):
            raise ValueError('histogram requires explicit integrated/differential representation and absolute/normalized normalization')
        validate_normalized_unit(request)
        histogram_types = ('BinnedHisto1D', 'BinnedHisto2D', 'Histo1D', 'Histo2D')
        estimate = type(obj).__name__ in ('BinnedEstimate1D', 'BinnedEstimate2D')
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
    delivery = {'yoda_version': yoda.__version__, 'all_object_paths': sorted(objects), 'observables': result, 'event_counters': counters}
    if cumulant is not None:
        if sorted(objects) != sorted(o['path'] for o in cumulant['transport']['whole_native_object_inventory']):
            raise ValueError('native API and retained writer object inventories differ')
        delivery['native_cumulant_transport'] = cumulant['transport']
    return delivery


if __name__ == '__main__':
    atomic_json(Path(sys.argv[3]), export(sys.argv[1], read_json(sys.argv[2])))
