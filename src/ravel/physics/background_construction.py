"""Exact integrated supplied background bases, lowered to the full regional law.

No fit or density evaluator lives here. Bernstein, fixed integer power and
supplied piecewise-constant/linear bases are integrated as rational polynomials.
Each coefficient is the expected component count on the FULL source domain,
before explicit bin transfers. Candidate choice is a declared discrete nuisance;
neither a candidate census nor a complexity penalty is learned from the data.
"""
from copy import deepcopy
from fractions import Fraction as F
import math
from pathlib import Path
import json

from ravel.physics import statistical_construction as regional


def _keys(d, keys, name):
    regional._keys(d, keys, name)


def _interval(v):
    if type(v) is not list or len(v) != 2:
        raise ValueError('complete interval required')
    a, b = map(regional._q, v)
    if not a < b or not float(a) < float(b):
        raise ValueError('distinct ordered source and binary64 endpoints required')
    return a, b


def _polynomial_integral(coefs, a, b):
    return sum((q * (b ** (i+1) - a ** (i+1)) / (i+1) for i, q in enumerate(coefs)), F(0))


def basis_integrals(family, domain, intervals):
    """Return basis-by-bin rational fractions, normalized on the full domain.

    Null intervals are explicit absent contributions. Intervals may coincide
    for DIFFERENT disjoint event selections; they never imply independence.
    No extrapolation, midpoint approximation, clipping or bin renormalization.
    """
    a, b = _interval(domain)
    windows = []
    for w in intervals:
        if w is None:
            windows.append(None); continue
        lo, hi = _interval(w)
        if lo < a or hi > b:
            raise ValueError('background bin lies outside complete source domain')
        windows.append((lo, hi))
    kind = family.get('kind') if type(family) is dict else None
    primitives = []
    if kind == 'bernstein':
        _keys(family, {'kind','degree'}, 'Bernstein basis')
        n = family['degree']
        if type(n) is not int or not 0 <= n <= 12:
            raise ValueError('Bernstein degree must be an integer from 0 to 12')
        for i in range(n+1):
            coefs = [F(0)] * (n+1)
            for j in range(n-i+1):
                coefs[i+j] = F(math.comb(n,i)*math.comb(n-i,j)*(-1)**j)
            primitives.append(lambda lo, hi, c=coefs: (b-a)*_polynomial_integral(c,(lo-a)/(b-a),(hi-a)/(b-a)))
    elif kind == 'fixed_integer_powers':
        _keys(family, {'kind','powers'}, 'integer-power basis')
        powers = family['powers']
        if a <= 0 or type(powers) is not list or not 1 <= len(powers) <= 16 or len(set(powers)) != len(powers) or any(type(p) is not int or not -12 <= p <= 12 or p == -1 for p in powers):
            raise ValueError('unique bounded integer powers on a strictly positive domain; logarithmic -1 is unsupported')
        for p in powers:
            primitives.append(lambda lo, hi, p=p: (hi**(p+1)-lo**(p+1))/(p+1))
    elif kind in ('histogram_templates','linear_templates'):
        _keys(family, {'kind','knots','components'}, 'supplied template basis')
        knots = family['knots']; comps = family['components']
        if type(knots) is not list or not 2 <= len(knots) <= 257:
            raise ValueError('bounded complete source knot population required')
        knots = list(map(regional._q,knots))
        if knots[0] != a or knots[-1] != b or any(x >= y or float(x) >= float(y) for x,y in zip(knots,knots[1:])):
            raise ValueError('distinct knots must cover the exact complete domain')
        if type(comps) is not list or not 1 <= len(comps) <= 16:
            raise ValueError('complete bounded source component population required')
        size = len(knots) - (kind == 'histogram_templates')
        for comp in comps:
            values = regional._vector(comp,size,'source density heights, not bin counts')
            if any(v < 0 for v in values):
                raise ValueError('background density heights must be nonnegative')
            def integrate(lo, hi, values=values):
                ans=F(0)
                for j,(left,right) in enumerate(zip(knots,knots[1:])):
                    x,y=max(lo,left),min(hi,right)
                    if x >= y: continue
                    ans += values[j]*(y-x)
                    if kind == 'linear_templates':
                        slope=(values[j+1]-values[j])/(right-left)
                        ans += slope*((y-left)**2-(x-left)**2)/2
                return ans
            primitives.append(integrate)
    else:
        raise ValueError('unsupported integrated source family')
    answer=[]
    for integrate in primitives:
        total=integrate(a,b)
        if total <= 0:
            raise ValueError('source component must have positive full-domain integral')
        row=[F(0) if w is None else integrate(*w)/total for w in windows]
        if any(v < 0 or v > 1 for v in row):
            raise ValueError('invalid exact integrated fraction')
        answer.append([str(v) for v in row])
    return answer


def construct(spec):
    """Preserve the complete signal/control/auxiliary law in EVERY candidate."""
    if len(json.dumps(spec,allow_nan=False)) > 4*1024*1024:
        raise ValueError('background construction exceeds 4 MiB')
    _keys(spec, {'schema_version','baseline','domain','bin_windows','transfer','candidates','penalty','census'}, 'background construction')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('background schema 1 required')
    base=deepcopy(spec['baseline']); n=len(base['bins']); k=len(base['auxiliary']['names'])
    # Baseline is a partial mean decomposition: a common rate may first be
    # used by the transfer. Validate the ENTIRE assembled law below, not a
    # fictitious baseline-only fit that would require dummy zero terms.
    sources={r['id'] for r in base['sources']}
    _interval(spec['domain'])
    if type(spec['bin_windows']) is not list or len(spec['bin_windows']) != n:
        raise ValueError('complete bin-ordered source windows required')
    transfer=spec['transfer']
    _keys(transfer, {'coefficients','powers','log_response','source'}, 'shared transfer')
    coefs=regional._vector(transfer['coefficients'],n,'shared bin transfers')
    pmap={p['name']:p for p in base['parameters']}
    if any(v < 0 for v in coefs) or transfer['source'] not in sources or type(transfer['powers']) is not dict:
        raise ValueError('source-bound nonnegative transfers required')
    for name,power in transfer['powers'].items():
        if name not in pmap or pmap[name]['role'] != 'rate' or type(power) is not int or not 1 <= power <= 5:
            raise ValueError('transfer powers require declared nonnegative physical rates')
    if type(transfer['log_response']) is not list or len(transfer['log_response']) != n:
        raise ValueError('complete shared correlation response required')
    for row in transfer['log_response']: regional._vector(row,k,'shared auxiliary log response')
    penalty=spec['penalty']
    _keys(penalty, {'kind','factor','source','justification'}, 'model complexity penalty')
    if penalty['kind'] != 'fixed_nll_per_floating_background_coefficient' or regional._q(penalty['factor']) < 0 or penalty['source'] not in sources:
        raise ValueError('explicit bounded source-defined NLL correction required')
    regional._text(penalty['justification'],'penalty justification')
    _keys(spec['census'], {'source','statement'}, 'complete candidate census')
    if spec['census']['source'] not in sources: raise ValueError('unbound candidate census')
    regional._text(spec['census']['statement'],'complete candidate census statement')
    candidates=spec['candidates']
    if type(candidates) is not list or not 2 <= len(candidates) <= 16:
        raise ValueError('complete population of 2 to 16 candidates required')
    out=[]; ids=set()
    for candidate in candidates:
        _keys(candidate, {'id','family','parameters','source'}, 'background candidate')
        ident=regional._id(candidate['id'])
        if ident in ids or candidate['source'] not in sources: raise ValueError('unique bound candidate required')
        ids.add(ident)
        family=candidate['family']; continuous=type(family) is dict and family.get('kind') in ('exponential','floating_power')
        dijet=type(family) is dict and family.get('kind') in ('dijet3','dijet4','dijet_log_polynomial')
        pars=candidate['parameters']; document=deepcopy(base); extras={}
        if continuous:
            power=family['kind']=='floating_power'
            coordinate_key,response_key=('exponents','exponent_response') if power else ('slopes','slope_log_response')
            _keys(family, {'kind',coordinate_key,response_key}, 'continuous background mixture')
            slopes=family[coordinate_key]; rs=family[response_key]
            if type(slopes) is not list or not 1 <= len(slopes) <= 8 or len(set(slopes)) != len(slopes) or type(rs) is not list or len(rs) != len(slopes):
                raise ValueError('complete bounded independent exponential component slopes required')
            if type(pars) is not list or len(pars) != 2*len(slopes):
                raise ValueError('declare component yields followed by every physical slope coefficient')
            for p,name,r in zip(pars[len(slopes):],slopes,rs):
                if p.get('name') != name or p.get('role') != 'coefficient' or name in pmap or p.get('source') != candidate['source']:
                    raise ValueError('candidate-specific source-bound continuous slope required')
                regional._vector(r,k,'full slope correlation response')
                document['parameters'].append(deepcopy(p))
            width, windows=(regional.parametric_shapes.power_geometry if power else regional.parametric_shapes.geometry)(spec['domain'],spec['bin_windows'])
            fractions=[['0' if w is None else '1' for w in windows] for _ in slopes]
            extras={'integrated_fractions':None,'fraction_semantics':'continuous full-domain normalized bin integrals, recomputed at every '+('exponent' if power else 'slope')+' state'}
            yields=pars[:len(slopes)]
        elif dijet:
            _keys(family, {'kind','sqrt_s','parameters','parameter_response','integration'}, 'continuous dijet family')
            shape_names=family['parameters']; shape_response=family['parameter_response']
            required={'dijet3':2,'dijet4':3}.get(family['kind'])
            if type(shape_names) is not list or not 2 <= len(shape_names) <= 5 or required is not None and len(shape_names) != required:
                raise ValueError('complete standard dijet coefficient population required')
            if type(pars) is not list or len(pars) != 1+len(shape_names):
                raise ValueError('one full-domain yield followed by alpha,beta1..betaJ required')
            for p,name in zip(pars[1:],shape_names):
                if p.get('name') != name or p.get('role') != 'coefficient' or name in pmap or p.get('source') != candidate['source']:
                    raise ValueError('candidate-specific source-bound dijet coefficient required')
                document['parameters'].append(deepcopy(p))
            dijet_shape={'kind':regional.continuous_dijet_shapes.KIND,'sqrt_s':family['sqrt_s'],
                'domain':deepcopy(spec['domain']),'bin_windows':deepcopy(spec['bin_windows']),
                'parameters':deepcopy(shape_names),'parameter_response':deepcopy(shape_response),'integration':deepcopy(family['integration'])}
            _,windows=regional.continuous_dijet_shapes.validate(dijet_shape,document['parameters'],base['auxiliary'],n)
            fractions=[['0' if w is None else '1' for w in windows]]
            extras={'integrated_fractions':None,'fraction_semantics':'continuous full-domain normalized dijet bin integrals at every complete coefficient state'}
            yields=pars[:1]
        else:
            fractions=basis_integrals(family,spec['domain'],spec['bin_windows'])
            if type(pars) is not list or len(pars) != len(fractions): raise ValueError('one complete declared coefficient per integrated component required')
            yields=pars
        for j,(p,row) in enumerate(zip(yields,fractions)):
            if p.get('role') != 'rate' or p.get('name') in pmap or p.get('source') != candidate['source']:
                raise ValueError('candidate-specific nonnegative expected full-domain rates required')
            document['parameters'].append(deepcopy(p))
            if not any(F(f)*t for f,t in zip(row,coefs)):
                raise ValueError('candidate component has no support in any modeled observation')
            powers=dict(transfer['powers']); powers[p['name']]=1
            term={'id':ident+'_component_'+str(j),'basis':'background',
                'coefficients':[str(F(f)*t) for f,t in zip(row,coefs)],'powers':powers,
                'log_response':deepcopy(transfer['log_response']),'source':candidate['source']}
            if continuous:
                term['shape']={'kind':'normalized_power' if power else 'normalized_exponential','domain':deepcopy(spec['domain']),
                    'bin_windows':deepcopy(spec['bin_windows']),
                    ('exponent_parameter' if power else 'slope_parameter'):slopes[j],
                    ('exponent_response' if power else 'slope_log_response'):deepcopy(rs[j])}
            elif dijet:
                term['shape']=deepcopy(dijet_shape)
            document['terms'].append(term)
        # Closed original namespace/domain/mean construction guards apply after
        # lowering, including every original signed SR/CR contribution.
        regional.validate(document)
        out.append({'id':ident,'document':document,'integrated_fractions':fractions,
            'floating_background_coefficients':sum(not p['fixed'] for p in pars),
            'penalty_nll':str(regional._q(penalty['factor'])*sum(not p['fixed'] for p in pars)),**extras})
    return out


def write_native_population(spec, output, *, runtime, fit, candidate_seconds, overhead_seconds):
    """Prepare a normal source-bound serial native study; do not run or approve."""
    rows=construct(spec)
    if fit.get('method') != 'MultiDimFit' or fit.get('data') != 'observed' or 'saved_fit' in fit or fit.get('absolute_nll') is not True:
        raise ValueError('observed absolute native grid scans required for discrete comparison')
    if type(candidate_seconds) is not list or len(candidate_seconds) != len(rows) or any(type(s) is not int or not 1 <= s <= 86400 for s in candidate_seconds):
        raise ValueError('complete prospective per-candidate native ceilings required')
    if type(overhead_seconds) is not int or not 1 <= overhead_seconds <= 3600 or sum(candidate_seconds)+overhead_seconds > 86400:
        raise ValueError('bounded explicit total native-plus-custody budget required')
    out=Path(output).absolute()
    if out.exists() or any(p.is_symlink() for p in (out,*out.parents)): raise ValueError('fresh nonsymlink preparation root required')
    out.mkdir(parents=True)
    source=out/'background.json'; source.write_text(json.dumps(spec,sort_keys=True,indent=2)+'\n')
    import hashlib
    pin=lambda p: {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    population=[]
    for row,seconds in zip(rows,candidate_seconds):
        handoff=regional.write_native_bundle(row['document'],out/row['id'],runtime=runtime,fit=fit,max_seconds=seconds)
        population.append({'id':row['id'],'input':pin(Path(handoff['task']['input']))})
    config={'schema_version':1,'construction':pin(source),'candidates':population,
            'overhead_seconds':overhead_seconds,'max_seconds':sum(candidate_seconds)+overhead_seconds}
    path=out/'discrete-study.json'; path.write_text(json.dumps(config,sort_keys=True,indent=2)+'\n')
    return {'mode':'background-discrete-profile','task':{'input':str(path)},'max_seconds':config['max_seconds'],
            'candidate_count':len(rows),'ordinary_admission_pending':True,'native_calls_executed':0}
