"""Closed standard dijet/log-polynomial densities, not an optimizer.

q=m/sqrt_s; log g=alpha*log(1-q)+sum beta_j*log(q)**j. A common
parameter-dependent centering factor cancels between each bin integral and
the full-domain integral. Unobserved mass is retained. The pure adaptive
reference reports error ESTIMATES; RooFit settings are not error certificates.
Native parity, convergence and scientific qualification remain pending.
"""
from fractions import Fraction as F
import math

KIND = 'normalized_dijet'
MAX_LOG_ENVELOPE = 80.
MAX_COEFFICIENT = F(100)

# Original API/source identity, not a claim that any configured runtime was run.
UPSTREAM_API = {'tag': 'v6-22-08', 'sources': {'RooAbsPdf.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooAbsPdf.cxx', 'sha256': '5a1ed952f945c34148b1b3a1d7f257c58a621eff1097d3aaecb41a7f406d3882'}, 'RooAbsReal.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooAbsReal.cxx', 'sha256': 'a6928c0ea1e0fb4742e570c7d8c177c549ff8491c406a91bbd3452d331a4510b'}, 'RooGenericPdf.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooGenericPdf.cxx', 'sha256': '76168f06b96fa5855ef03961d2199bd8ba89cba0e00a186edf3b04b8657a52ea'}, 'RooIntegrator1D.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooIntegrator1D.cxx', 'sha256': '37152cd13a6a3fb05fa111ae1d9853864e454d865c9b32ed24563419c5079ca5'}, 'RooNumIntConfig.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooNumIntConfig.cxx', 'sha256': '85490c034eed3b11001d9846b09c062d142fa63511faeea792c0a1a3974892da'}, 'RooRealIntegral.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooRealIntegral.cxx', 'sha256': '15a90cbfc1d23c87d6ce43e9bd93345fa8cea80a4b8bf59e294c77e3bcfbc5fc'}, 'RooRealIntegral.h': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/inc/RooRealIntegral.h', 'sha256': '74bec2783a8e9920f0d5825d081683e193bfd9219c22801455cc5c6a1da5afd2'}, 'RooWorkspace.cxx': {'url': 'https://raw.githubusercontent.com/root-project/root/v6-22-08/roofit/roofitcore/src/RooWorkspace.cxx', 'sha256': '312d2dd4fa7849e57adb1d86360a349d4f5ff54da3a3a2f9897de1062ddac077'}}}


def geometry(shape):
    from ravel.physics.statistical_construction import _q
    scale = _q(shape['sqrt_s'])
    if scale <= 0:
        raise ValueError('positive finite supplied sqrt_s required')
    def interval(raw):
        if type(raw) is not list or len(raw) != 2:
            raise ValueError('complete dijet mass interval required')
        lo, hi = (_q(v)/scale for v in raw)
        if not 0 < lo < hi < 1 or not 0 < float(lo) < float(hi) < 1:
            raise ValueError('strict finite binary64 0<m/sqrt_s<1 interval required')
        return lo, hi
    domain = interval(shape['domain'])
    raw = shape['bin_windows']
    if type(raw) is not list or not 1 <= len(raw) <= 256:
        raise ValueError('complete bounded bin-ordered dijet windows required')
    windows = []
    for row in raw:
        if row is None:
            windows.append(None); continue
        lo, hi = interval(row)
        if lo < domain[0] or hi > domain[1]:
            raise ValueError('dijet window outside full normalization domain')
        if float(hi-lo) <= 0:
            raise ValueError('dijet interval loses binary64 width')
        windows.append((lo, hi))
    return domain, windows


def integration_policy(policy):
    from ravel.physics.statistical_construction import _keys, _q
    _keys(policy, {'native','reference'}, 'dijet integration policy')
    native = policy['native']; ref = policy['reference']
    _keys(native, {'engine','absolute_tolerance','relative_tolerance','max_steps'}, 'native dijet integrator')
    if native['engine'] != 'RooIntegrator1D' or type(native['max_steps']) is not int or not 8 <= native['max_steps'] <= 20:
        raise ValueError('supported bounded adaptive RooIntegrator1D required')
    _keys(ref, {'absolute_tolerance','relative_tolerance','max_depth','max_evaluations',
                'maximum_probability_error','maximum_gradient_error'}, 'reference dijet integrator')
    for settings in (native, ref):
        for key in ('absolute_tolerance','relative_tolerance'):
            if not F(1,10**14) <= _q(settings[key]) <= F(1,10**6):
                raise ValueError('explicit integration tolerances in [1e-14,1e-6] required')
    if type(ref['max_depth']) is not int or not 4 <= ref['max_depth'] <= 24 or type(ref['max_evaluations']) is not int or not 32 <= ref['max_evaluations'] <= 200000:
        raise ValueError('bounded prospective reference depth/evaluation limits required')
    for key in ('maximum_probability_error','maximum_gradient_error'):
        if not F(1,10**12) <= _q(ref[key]) <= F(1,10**4):
            raise ValueError('explicit bounded reference estimated-error limits required')
    return native, ref


def _features(q, count, center):
    l, l0 = math.log(q), math.log(center)
    return [math.log1p(-q)-math.log1p(-center)] + [l**j-l0**j for j in range(1,count)]


def _envelope(domain, bounds):
    a,b = map(float,domain); center = (a+b)/2
    ends = [_features(a,len(bounds),center), _features(b,len(bounds),center)]
    # Every feature is monotone on (0,1). Triangle bounds cover all parameter
    # combinations and the entire continuum, including nuisance shifts.
    return math.fsum(max(abs(float(lo)),abs(float(hi)))*max(abs(ends[0][i]),abs(ends[1][i])) for i,(lo,hi) in enumerate(bounds))


def validate(shape, parameters, auxiliary, bin_count):
    from ravel.physics.statistical_construction import _keys, _q, _vector
    _keys(shape, {'kind','sqrt_s','domain','bin_windows','parameters','parameter_response','integration'}, 'dijet shape')
    names = shape['parameters']; response = shape['parameter_response']; k = len(auxiliary['names'])
    if shape['kind'] != KIND or type(names) is not list or not 2 <= len(names) <= 5 or len(set(names)) != len(names) or type(response) is not list or len(response) != len(names):
        raise ValueError('ordered alpha,beta1..betaJ coefficient population required; 1<=J<=4')
    domain, windows = geometry(shape)
    if len(windows) != bin_count:
        raise ValueError('complete all-bin dijet shape required')
    integration_policy(shape['integration'])
    byname = {p['name']:p for p in parameters}; bounds = []
    for name, row in zip(names,response):
        p = byname.get(name)
        if p is None or p['role'] != 'coefficient':
            raise ValueError('every dijet exponent must be a declared physical coefficient')
        r = _vector(row,k,'complete correlated dijet coefficient response')
        lo,hi = map(_q,p['bounds'])
        offset = sum((r[i]*_q(auxiliary['observed'][i]) for i in range(k)),F())
        lo += offset; hi += offset
        for j, limits in enumerate(auxiliary['eta_bounds']):
            c = sum((r[i]*_q(auxiliary['factor'][i][j]) for i in range(k)),F())
            x,y = (c*_q(v) for v in limits); lo += min(x,y); hi += max(x,y)
        if max(abs(lo),abs(hi)) > MAX_COEFFICIENT:
            raise ValueError('complete effective dijet coefficient box exceeds |coefficient|<=100')
        bounds.append((lo,hi))
    envelope = _envelope(domain,bounds)
    if envelope > MAX_LOG_ENVELOPE:
        raise ValueError('complete centered dijet log-density box exceeds |log g|<=80')
    tail = math.exp(-2*envelope)
    if any(w is not None and float((w[1]-w[0])/(domain[1]-domain[0]))*tail == 0 for w in windows):
        raise ValueError('positive dijet bin probability may underflow over admitted box')
    return domain, windows


def effective_parameters(shape, values, theta):
    from ravel.physics.statistical_construction import _q
    if len(theta) != len(shape['parameter_response'][0]):
        raise ValueError('complete dijet auxiliary state required')
    return [values[name]+sum((_q(r)*t for r,t in zip(row,theta)),F()) for name,row in zip(shape['parameters'],shape['parameter_response'])]


def reference(shape, coefficients):
    """Adaptive Simpson/Richardson estimates for density AND all moments.

    The evaluation budget covers denominator and every requested numerator.
    Failure to meet any estimated error/depth/budget limit is an explicit error.
    No clipping, midpoint bins, surviving-bin renormalization or fallback.
    """
    from ravel.physics.statistical_construction import _q
    domain,windows = geometry(shape); _, settings = integration_policy(shape['integration'])
    if type(coefficients) not in (list,tuple) or len(coefficients) != len(shape['parameters']):
        raise ValueError('complete effective dijet coefficient point required')
    coefficients = [float(_q(str(v))) for v in coefficients]
    if max(map(abs,coefficients)) > float(MAX_COEFFICIENT) or _envelope(domain,[(v,v) for v in coefficients]) > MAX_LOG_ENVELOPE:
        raise ValueError('dijet point outside admitted numerical envelope')
    a,b = map(float,domain); center = (a+b)/2; span = b-a; count = len(coefficients)
    abs_tol,rel_tol = (float(_q(settings[key])) for key in ('absolute_tolerance','relative_tolerance'))
    evaluations = 0; subdivisions = 0; cache = {}
    def evaluate(u):
        nonlocal evaluations
        if u in cache:
            return cache[u]
        if evaluations >= settings['max_evaluations']:
            raise ValueError('dijet reference evaluation budget exhausted')
        f = _features(a+span*u,count,center)
        value = math.exp(math.fsum(c*v for c,v in zip(coefficients,f)))
        ans = [value]+[value*v for v in f]
        if not all(math.isfinite(v) for v in ans):
            raise ValueError('nonfinite dijet reference integrand')
        evaluations += 1; cache[u] = ans
        return ans
    def simpson(lo,hi,x,y,z):
        return [(hi-lo)*(p+4*q+r)/6 for p,q,r in zip(x,y,z)]
    def integrate(lo,hi):
        def recurse(lo,hi,x,y,z,coarse,depth,tol):
            nonlocal subdivisions
            mid = (lo+hi)/2; lmid = (lo+mid)/2; rmid = (mid+hi)/2
            if lo == lmid or mid == rmid:
                raise ValueError('dijet reference subdivision loses binary64 width')
            l,r = evaluate(lmid),evaluate(rmid)
            left,right = simpson(lo,mid,x,l,y),simpson(mid,hi,y,r,z)
            fine = [v+w for v,w in zip(left,right)]
            delta = [(v-w)/15 for v,w in zip(fine,coarse)]
            errors = [abs(d)+32*math.ulp(1.)*abs(v) for d,v in zip(delta,fine)]
            if all(e <= tol+rel_tol*abs(v) for e,v in zip(errors,fine)):
                return [v+d for v,d in zip(fine,delta)],errors
            if depth >= settings['max_depth']:
                raise ValueError('dijet reference depth limit exhausted before estimated convergence')
            subdivisions += 1
            lv,le = recurse(lo,mid,x,l,y,left,depth+1,tol/2)
            rv,re = recurse(mid,hi,y,r,z,right,depth+1,tol/2)
            return [v+w for v,w in zip(lv,rv)],[v+w for v,w in zip(le,re)]
        x,y,z = evaluate(lo),evaluate((lo+hi)/2),evaluate(hi)
        return recurse(lo,hi,x,y,z,simpson(lo,hi,x,y,z),0,abs_tol)
    whole,we = integrate(0.,1.); den = whole[0]; de = we[0]
    if not math.isfinite(den) or not den > de >= 0:
        raise ValueError('positive full-domain reference normalization unresolved')
    answer,grad,pe,ge = [],[],[],[]
    for window in windows:
        if window is None:
            answer.append(0.); grad.append([0.]*count); pe.append(0.); ge.append([0.]*count); continue
        if window == domain:
            answer.append(1.); grad.append([0.]*count); pe.append(0.); ge.append([0.]*count); continue
        lo,hi = (float((v-domain[0])/(domain[1]-domain[0])) for v in window)
        num,ne = integrate(lo,hi); prob = num[0]/den
        perr = (ne[0]+abs(prob)*de)/(den-de)
        moment = [v/den for v in whole[1:]]
        merr = [(e+abs(v)*de)/(den-de) for e,v in zip(we[1:],moment)]
        nj = [v/den for v in num[1:]]
        nerr = [(e+abs(v)*de)/(den-de) for e,v in zip(ne[1:],nj)]
        derivative = [v-prob*w for v,w in zip(nj,moment)]
        gerr = [e+abs(prob)*f+abs(w)*perr+perr*f for e,f,w in zip(nerr,merr,moment)]
        if not 0 < prob <= 1 or not all(math.isfinite(v) for v in derivative+gerr+[perr]):
            raise ValueError('invalid dijet normalized integral arithmetic')
        if perr > float(_q(settings['maximum_probability_error'])) or max(gerr) > float(_q(settings['maximum_gradient_error'])):
            raise ValueError('dijet reference estimated normalized error exceeds declared limits')
        answer.append(prob); grad.append(derivative); pe.append(perr); ge.append(gerr)
    return {'fractions':answer,'gradient':grad,'estimated_probability_error':pe,
            'estimated_gradient_error':ge,'evaluations':evaluations,'subdivisions':subdivisions,
            'error_semantics':'adaptive Simpson/Richardson estimates, not certified bounds',
            'normalization':'one full supplied domain; unobserved mass retained','clipping_applied':False}


def fractions(shape, coefficients):
    result = reference(shape,coefficients)
    return result['fractions'],result['gradient']


def coordinate_gradient(shape, bin_gradient, name, auxiliary):
    from ravel.physics.statistical_construction import _q
    if name in shape['parameters']:
        return bin_gradient[shape['parameters'].index(name)]
    if name.startswith('ravel_aux_'):
        j = int(name[len('ravel_aux_'):]); k = len(auxiliary['names'])
        return math.fsum(v*float(sum((_q(row[i])*_q(auxiliary['factor'][i][j]) for i in range(k)),F())) for v,row in zip(bin_gradient,shape['parameter_response']))
    return 0.


def native_payload(shape, index, names, auxiliary, coefficients):
    """Closed RooGenericPdf expression and original raw-integral declarations."""
    from ravel.physics.statistical_construction import _q
    domain,windows = geometry(shape); prefix = 'ravel_shape_'+str(index)
    a,b = domain; center = float((a+b)/2); n = lambda v: format(float(v),'.17g')
    factories = []; effective = []; k = len(auxiliary['names'])
    for i,(name,row) in enumerate(zip(shape['parameters'],shape['parameter_response'])):
        r = list(map(_q,row)); offset = sum((r[j]*_q(auxiliary['observed'][j]) for j in range(k)),F())
        slopes = [sum((r[j]*_q(auxiliary['factor'][j][h]) for j in range(k)),F()) for h in range(k)]
        expression = '@'+str(names.index(name))+'+('+n(offset)+')'+''.join('+('+n(v)+')*@'+str(len(names)-k+j) for j,v in enumerate(slopes) if v)
        ename = prefix+'_parameter_'+str(i); effective.append(ename)
        factories.append('expr::'+ename+'("'+expression+'",'+','.join(names)+')')
    # RooFormula/TFormula supports log, not Python log1p. Physical domain is
    # strictly inside (0,1); both native endpoint operations are source bounded.
    features = ['log(1-@0)-('+n(math.log1p(-center))+')'] + ['pow(log(@0),'+str(j)+')-('+n(math.log(center)**j)+')' for j in range(1,len(effective))]
    expression = 'exp('+ '+'.join('@'+str(j+1)+'*('+f+')' for j,f in enumerate(features))+')'
    factories.append('EXPR::'+prefix+'_pdf("'+expression+'",'+','.join([prefix+'_x']+effective)+')')
    active = [{'name':'ravel_fraction_'+str(bi)+'_'+str(index),'range':prefix+'_range_'+str(bi),'interval':[n(v) for v in w],'numerator':prefix+'_integral_'+str(bi)} for bi,w in enumerate(windows) if w is not None and _q(coefficients[bi])]
    declaration = {'pdf':prefix+'_pdf','variable':prefix+'_x','denominator':prefix+'_integral_full',
        'range':prefix+'_range_full','domain':[n(a),n(b)],'bins':active,'settings':shape['integration']['native']}
    return prefix+'_x['+n((a+b)/2)+','+n(a)+','+n(b)+']',factories,declaration


def native_bridge_lines(declaration):
    """Original ROOT v6-22-08 APIs; executed only by the ordinary native route.

    No NormSet command: both numerator and denominator are RAW integrals.
    The pdf owns a special copied config, retained by serialized integrals.
    minSteps=maxSteps+1 disables only early ZERO threshold convergence. Ordinary
    tolerance convergence stays enabled (fixSteps=0). One trapezoidal invocation
    uses at most 2**(maxSteps-1)+1 density evaluations, not a whole-fit bound.
    """
    d = declaration; settings = d['settings']; steps = settings['max_steps']
    lines = ['import ROOT','density = self.modelBuilder.out.pdf('+repr(d['pdf'])+')',
             'variable = self.modelBuilder.out.var('+repr(d['variable'])+')',
             'if not density or not variable: raise ValueError("constructed dijet density absent")',
             'config = density.specialIntegratorConfig(True)',
             'config.method1D().setLabel("RooIntegrator1D")',
             'config.setEpsAbs('+repr(float(F(settings['absolute_tolerance'])))+')',
             'config.setEpsRel('+repr(float(F(settings['relative_tolerance'])))+')',
             'section = config.getConfigSection("RooIntegrator1D")',
             'section.find("sumRule").setLabel("Trapezoid")',
             'section.find("extrapolation").setLabel("Wynn-Epsilon")',
             'section.find("maxSteps").setVal('+repr(steps)+')',
             'section.find("minSteps").setVal('+repr(steps+1)+')',
             'section.find("fixSteps").setVal(0)',
             'arguments = ROOT.RooArgSet(variable)',
             'self._ravel_numerical_objects = getattr(self,"_ravel_numerical_objects",[])',
             'self._ravel_numerical_objects.extend([config,arguments])']
    for name,range_,interval in [(d['denominator'],d['range'],d['domain'])]+[(b['numerator'],b['range'],b['interval']) for b in d['bins']]:
        lines += ['variable.setRange('+repr(range_)+','+','.join(interval)+')',
                  'integral = density.createIntegral(arguments,ROOT.RooFit.NumIntConfig(config),ROOT.RooFit.Range('+repr(range_)+'))',
                  'if not integral: raise ValueError("constructed raw dijet integral absent")',
                  'integral.SetName('+repr(name)+')',
                  'if getattr(self.modelBuilder.out,"import")(integral,ROOT.RooFit.RecycleConflictNodes()): raise ValueError("constructed raw dijet integral import failed")',
                  'self._ravel_numerical_objects.append(integral)']
    for b in d['bins']:
        expression = 'expr::'+b['name']+'("@0/@1",'+b['numerator']+','+d['denominator']+')'
        lines.append('self.modelBuilder.factory_('+repr(expression)+')')
    return ['        '+line for line in lines]
