"""Closed, continuously normalized exponential/power counts; no fitting engine.

ROOT RooExponential uses exp(c*x). Here t=(x-a)/(b-a) and lambda=c*(b-a),
so the full-domain yield is independent of c. Bin integrals are not midpoint
values. The Python reference and emitted RooFormulaVar use different stable
forms of the same integral. Native evaluation/fit parity remains unqualified.
The floating-power family transforms positive x to log coordinates and reuses
the same integral kernel; source windows and full-domain yields stay explicit.
"""
from fractions import Fraction as F
import math

MAX_DIMENSIONLESS_SLOPE = F(50)


def geometry(domain, windows):
    from ravel.physics.statistical_construction import _q
    def interval(v):
        if type(v) is not list or len(v) != 2:
            raise ValueError('complete exponential interval required')
        lo, hi = map(_q, v)
        if lo >= hi or float(lo) >= float(hi):
            raise ValueError('distinct exponential interval endpoints required')
        return lo, hi
    a, b = interval(domain)
    # Width itself must have a nonzero finite binary64 representation.
    _q(str(b-a))
    out = []
    if type(windows) is not list or not 1 <= len(windows) <= 128:
        raise ValueError('full bin-ordered exponential windows required')
    for w in windows:
        if w is None:
            out.append(None); continue
        lo, hi = interval(w)
        if lo < a or hi > b:
            raise ValueError('exponential window outside full normalization domain')
        l, h = (lo-a)/(b-a), (hi-a)/(b-a)
        if float(l) >= float(h):
            raise ValueError('normalized exponential window loses binary64 width')
        out.append((l, h))
    return b-a, out


def validate(shape, parameters, auxiliary, bin_count):
    if type(shape) is dict and shape.get('kind') == 'normalized_power':
        return _validate_power(shape, parameters, auxiliary, bin_count)
    from ravel.physics.statistical_construction import _keys, _q, _vector
    _keys(shape, {'kind','domain','bin_windows','slope_parameter','slope_log_response'}, 'parametric shape')
    if shape['kind'] != 'normalized_exponential' or len(shape['bin_windows']) != bin_count:
        raise ValueError('complete normalized exponential shape required')
    width, windows = geometry(shape['domain'], shape['bin_windows'])
    p = next((p for p in parameters if p['name'] == shape['slope_parameter']), None)
    if p is None or p['role'] != 'coefficient':
        raise ValueError('exponential slope must be a declared coefficient in inverse-x units')
    r = _vector(shape['slope_log_response'],len(auxiliary['names']),'correlated physical slope response')
    offset = sum((r[i]*_q(v) for i,v in enumerate(auxiliary['observed'])),F())
    slopes = [sum((r[i]*_q(auxiliary['factor'][i][j]) for i in range(len(r))),F()) for j in range(len(r))]
    lo, hi = map(_q,p['bounds'])
    lo += offset; hi += offset
    for c, bounds in zip(slopes,auxiliary['eta_bounds']):
        x,y = (c*_q(b) for b in bounds); lo += min(x,y); hi += max(x,y)
    if max(abs(lo*width),abs(hi*width)) > MAX_DIMENSIONLESS_SLOPE:
        raise ValueError('complete exponential slope box exceeds numerical envelope |c*(b-a)|<=50')
    # On t in [0,1], the normalized density is >= exp(-max|lambda|).
    # Refuse a source bin whose positive probability may underflow, rather than
    # silently turning it into an absent contribution in a native mean.
    tail = math.exp(-float(max(abs(lo*width),abs(hi*width))))
    if any(w is not None and float(w[1]-w[0])*tail == 0 for w in windows):
        raise ValueError('positive exponential window is not representable over the whole slope box')
    return width, windows


def effective_slope(shape, values, theta):
    from ravel.physics.statistical_construction import _q
    if shape.get('kind') == 'normalized_power':
        return values[shape['exponent_parameter']] + sum((_q(r)*t for r,t in zip(shape['exponent_response'],theta)),F())
    return values[shape['slope_parameter']] + sum((_q(r)*t for r,t in zip(shape['slope_log_response'],theta)),F())


def _conditional_mean(lam, lo, hi):
    w = hi-lo; z = lam*w
    if abs(z) < 0.1:
        # Bernoulli series through z^11: omitted error O(w*z^13).
        return lo+w*(0.5+z/12-z**3/720+z**5/30240-z**7/1209600+z**9/47900160-691*z**11/1307674368000)
    return lo+w/(-math.expm1(-z))-1/lam


def fractions(shape, slope):
    """Bin probabilities and d/d(physical slope); no clipping/renormalization."""
    if shape.get('kind') == 'normalized_power':
        return power_fractions(shape, slope)
    width, windows = geometry(shape['domain'],shape['bin_windows'])
    lam = float(F(slope)*width)
    if not math.isfinite(lam) or abs(lam) > float(MAX_DIMENSIONLESS_SLOPE):
        raise ValueError('exponential slope outside admitted numerical envelope')
    answer, derivative = [], []
    whole_mean = _conditional_mean(lam,0.,1.)
    for w in windows:
        if w is None:
            answer.append(0.); derivative.append(0.); continue
        lo,hi = map(float,w); span = float(w[1]-w[0])
        if lam == 0:
            value = span
        elif abs(lam) < 1e-5:
            # exprel(0)=1 also covers a subnormal lambda*span that rounds to
            # zero, without losing the finite positive width/zero-slope limit.
            exprel = lambda z: math.expm1(z)/z if z else 1.
            value = span*math.exp(lam*lo)*exprel(lam*span)/exprel(lam)
        elif lam > 0:
            value = math.exp(lam*(hi-1))*(-math.expm1(-lam*span))/(-math.expm1(-lam))
        else:
            value = math.exp(lam*lo)*(-math.expm1(lam*span))/(-math.expm1(lam))
        diff = value*float(width)*(_conditional_mean(lam,lo,hi)-whole_mean)
        if not 0 < value <= 1 or not math.isfinite(diff):
            raise ValueError('nonfinite/out-of-domain exponential integral arithmetic')
        answer.append(value); derivative.append(diff)
    return answer, derivative


def native_fraction_expression(window):
    """Closed RooFormulaVar formula with @0=lambda; no user expressions.

    sinhc Taylor evaluation near zero avoids a removable 0/0 and cancellation.
    Eight powers give omitted relative error <1e-36 at the 1e-3 branch.
    """
    lo, hi = window
    n = lambda q: format(float(q),'.17g')
    def sinhc(z):
        return '((abs('+z+')<0.001)?(1+pow('+z+',2)/6.0+pow('+z+',4)/120.0+pow('+z+',6)/5040.0+pow('+z+',8)/362880.0):(sinh('+z+')/('+z+')))'
    return '('+n(hi-lo)+'*exp(@0*'+n((lo+hi-1)/2)+')*'+sinhc('(@0*'+n((hi-lo)/2)+')')+'/'+sinhc('(@0*0.5)')+')'


def parameter(shape):
    return shape['exponent_parameter'] if shape['kind'] == 'normalized_power' else shape['slope_parameter']


def parameter_response(shape):
    return shape['exponent_response'] if shape['kind'] == 'normalized_power' else shape['slope_log_response']


def power_geometry(domain, windows):
    """Positive finite x domain, transformed t=log(x/a)/log(b/a).

    The existing exponential kernel integrates x**p dx after q=(p+1)*L.
    L<=50 bounds the binary64 log-coordinate map; |q|<=50 is checked separately.
    Original physical edges remain in the source document, never replaced.
    """
    from ravel.physics.statistical_construction import _q
    geometry(domain, windows)  # Existing complete physical interval checks.
    a,b=map(_q,domain)
    if a <= 0:
        raise ValueError('floating-power domain must be strictly positive')
    def log_ratio(lo,hi):
        try:
            ratio=float((hi-lo)/lo)
        except OverflowError:
            raise ValueError('floating-power log-domain envelope exceeded') from None
        if not math.isfinite(ratio):
            raise ValueError('floating-power log-domain envelope exceeded')
        return math.log1p(ratio)
    length=log_ratio(a,b)
    if not 0 < length <= 50:
        raise ValueError('floating-power domain requires 0<log(b/a)<=50')
    mapped=[]
    for w in windows:
        if w is None:
            mapped.append(None); continue
        lo,hi=map(_q,w)
        left=0. if lo == a else log_ratio(a,lo)/length
        right=1. if hi == b else log_ratio(a,hi)/length
        if not 0 <= left < right <= 1:
            raise ValueError('floating-power log window loses binary64 width')
        mapped.append((F(left),F(right)))
    return F(length),mapped


def _validate_power(shape, parameters, auxiliary, bin_count):
    from ravel.physics.statistical_construction import _keys,_q,_vector
    _keys(shape,{'kind','domain','bin_windows','exponent_parameter','exponent_response'},'floating-power shape')
    if len(shape['bin_windows']) != bin_count:
        raise ValueError('complete normalized floating-power shape required')
    length,windows=power_geometry(shape['domain'],shape['bin_windows'])
    p=next((p for p in parameters if p['name'] == shape['exponent_parameter']),None)
    if p is None or p['role'] != 'coefficient':
        raise ValueError('power exponent must be a declared dimensionless coefficient')
    r=_vector(shape['exponent_response'],len(auxiliary['names']),'correlated physical exponent response')
    offset=sum((r[i]*_q(v) for i,v in enumerate(auxiliary['observed'])),F())
    slopes=[sum((r[i]*_q(auxiliary['factor'][i][j]) for i in range(len(r))),F()) for j in range(len(r))]
    lo,hi=map(_q,p['bounds']); lo+=offset; hi+=offset
    for c,bounds in zip(slopes,auxiliary['eta_bounds']):
        x,y=(c*_q(b) for b in bounds); lo+=min(x,y); hi+=max(x,y)
    envelope=max(abs((lo+1)*length),abs((hi+1)*length))
    if envelope > MAX_DIMENSIONLESS_SLOPE:
        raise ValueError('complete power exponent box exceeds numerical envelope |(p+1)*log(b/a)|<=50')
    tail=math.exp(-float(envelope))
    if any(w is not None and float(w[1]-w[0])*tail == 0 for w in windows):
        raise ValueError('positive power window is not representable over the whole exponent box')
    return length,windows


def power_fractions(shape, exponent):
    """Normalized integrals and d/dp; p=-1 logarithmic, p=0 constant.

    Bin fractions are never renormalized over observed/surviving windows.
    The constant branch converts the original rational width ratio directly.
    Its nonzero exponent derivative still comes from the log-coordinate score.
    """
    length,windows=power_geometry(shape['domain'],shape['bin_windows'])
    p=F(exponent); q=(p+1)*length
    transformed={'domain':['0','1'],'bin_windows':[None if w is None else [str(v) for v in w] for w in windows]}
    values,derivatives=fractions(transformed,q)
    derivatives=[v*float(length) for v in derivatives]
    if p == 0:
        a,b=map(F,shape['domain'])
        exact=[0. if w is None else float((F(w[1])-F(w[0]))/(b-a)) for w in shape['bin_windows']]
        derivatives=[d*(new/old) if old else 0. for d,new,old in zip(derivatives,exact,values)]
        values=exact
    return values,derivatives


def native_power_fraction_expression(shape, index, length, window):
    """@0=q, same stable kernel, explicit original-x constant integral."""
    a,b=map(F,shape['domain']); lo,hi=map(F,shape['bin_windows'][index])
    constant=format(float((hi-lo)/(b-a)),'.17g')
    return '((@0=='+format(float(length),'.17g')+')?'+constant+':'+native_fraction_expression(window)+')'
