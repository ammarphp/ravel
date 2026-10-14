"""Complete-category, correlation-preserving interpolation of supplied marks.

This is a new explicit piecewise-multilinear response law, NOT HistFactory
code4/code4p or moment morphing. It creates no likelihood, calibration or fit.
One latent category population is shared by every supplied nuisance anchor.
"""
from copy import deepcopy
from itertools import product
import math


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _number(x):
    _require(type(x) in (int, float) and math.isfinite(x), 'finite literal number required')
    return float(x)


def _ids(x, label):
    _require(isinstance(x, list) and x and all(isinstance(i, str) and i for i in x)
             and len(set(x)) == len(x), 'complete unique ' + label)
    return x


def prepare(document):
    """Validate an explicit new response law; source custody belongs to caller."""
    keys = {'schema_version', 'category_ids', 'destination_ids', 'fitted_destinations',
            'axes', 'reference_point', 'category_weights', 'denominator_marks',
            'scale', 'total_groups', 'anchors', 'provenance'}
    _require(type(document) is dict and set(document) == keys and
             type(document['schema_version']) is int and document['schema_version'] == 1,
             'closed response schema1 required')
    d = deepcopy(document)
    cats = _ids(d['category_ids'], 'categories'); dests = _ids(d['destination_ids'], 'destinations')
    fitted = _ids(d['fitted_destinations'], 'fitted destinations')
    _require(set(fitted) < set(dests), 'all fitted bins plus at least one explicit unfitted destination required')
    _require(len(cats) <= 64 and len(dests) <= 64, 'bounded64 category/destination coordinates')
    _require(type(d['total_groups']) is int and d['total_groups'] > 0, 'fixed positive integer N required')
    _require(_number(d['scale']) > 0, 'positive supplied normalization required')
    for key in ('category_weights', 'denominator_marks'):
        _require(isinstance(d[key], list) and len(d[key]) == len(cats), 'complete ' + key)
        for x in d[key]: _number(x)
    axes = d['axes']
    _require(isinstance(axes, list) and axes and len(axes) <= 6, 'one to six explicit axes')
    names = []
    for a in axes:
        _require(type(a) is dict and set(a) == {'name', 'knots'}, 'closed axis')
        names.append(a['name']); knots = a['knots']
        _require(isinstance(knots, list) and 2 <= len(knots) <= 5, 'two to five source knots')
        for x in knots: _number(x)
        _require(all(x < y for x, y in zip(knots, knots[1:])), 'strictly ordered knots')
    _ids(names, 'axis names')
    _require(type(d['reference_point']) is dict and set(d['reference_point']) == set(names), 'reference coordinate population')
    for a in axes: _require(_number(d['reference_point'][a['name']]) in a['knots'], 'reference must be a retained anchor')
    expected = set(product(*(a['knots'] for a in axes)))
    _require(len(expected) <= 64 and len(expected)*len(cats)*len(dests) <= 32768, 'bounded complete Cartesian anchors')
    anchors = d['anchors']; _require(isinstance(anchors, list) and len(anchors) == len(expected), 'complete Cartesian anchors required; no inferred interactions')
    seen = set()
    for a in anchors:
        _require(type(a) is dict and set(a) == {'point', 'allocation'}, 'closed anchor')
        _require(isinstance(a['point'], list) and len(a['point']) == len(axes), 'anchor coordinate dimension')
        for x in a['point']: _number(x)
        point = tuple(a['point'])
        _require(point in expected and point not in seen, 'duplicate/unknown anchor')
        seen.add(point); rows = a['allocation']
        _require(isinstance(rows, list) and len(rows) == len(cats), 'all categories at every anchor')
        for row in rows:
            _require(isinstance(row, list) and len(row) == len(dests), 'all destinations including rejected/flow states')
            _require(all(0 <= _number(x) <= 1 for x in row), 'nonnegative allocation fractions')
            _require(abs(math.fsum(row)-1) <= 1e-12, 'complete per-category allocation; no silent lost population')
    _require(seen == expected, 'missing joint anchor')
    provenance = d['provenance']
    _require(type(provenance) is dict and set(provenance) == {'category_partition', 'joint_anchor_identity', 'interpolation', 'calibration'}, 'complete scientific provenance descriptions')
    _require(all(type(v) is str and v.strip() for v in provenance.values()), 'nonempty scientific provenance')
    _require(provenance['interpolation'] == 'new_piecewise_multilinear_fixed_mark_law', 'do not claim source interpolation equivalence')
    return d


def _population(d, latent):
    _require(type(latent) is dict and set(latent) == set(d['category_ids']), 'same complete latent MC categories required')
    p = [_number(latent[k]) for k in d['category_ids']]
    _require(all(0 <= v <= 1 for v in p) and abs(math.fsum(p)-1) <= 1e-12, 'physical complete simplex; no renormalization')
    den = math.fsum(x*y for x, y in zip(p, d['denominator_marks']))
    _require(math.isfinite(den) and den > 0, 'positive expected signed denominator required')
    return p, den


def _intervals(d, point):
    _require(type(point) is dict and set(point) == {a['name'] for a in d['axes']}, 'complete response coordinate map')
    result=[]
    for axis in d['axes']:
        x = _number(point[axis['name']]); knots=axis['knots']
        _require(knots[0] <= x <= knots[-1], 'outside supplied interpolation hull; no extrapolation')
        options=[i for i in range(len(knots)-1) if knots[i] <= x <= knots[i+1]]
        result.append(options)
    return result


def _marks(d, point, cell, derivative_axis=None):
    table={tuple(a['point']):a['allocation'] for a in d['anchors']}
    c=len(d['category_ids']); b=len(d['destination_ids'])
    terms=[[[] for _ in range(c)] for _ in range(b)]
    for corner in product((0, 1), repeat=len(d['axes'])):
        weight=1.; coordinate=[]
        for j, (axis, interval, side) in enumerate(zip(d['axes'], cell, corner)):
            lo, hi=axis['knots'][interval:interval+2]; x=point[axis['name']]
            coordinate.append((lo, hi)[side])
            weight *= ((-1 if side==0 else 1)/(hi-lo) if j==derivative_axis
                       else ((hi-x)/(hi-lo) if side==0 else (x-lo)/(hi-lo)))
        rows=table[tuple(coordinate)]
        for i in range(b):
            for k in range(c): terms[i][k].append(weight*rows[k][i]*d['category_weights'][k])
    return [[math.fsum(t) for t in row] for row in terms]


def evaluate(document, latent, point):
    """Mean, full latent Jacobian and both one-sided nuisance derivatives.

The p Jacobian uses ambient coordinates; simplex tangent columns are obtained by
subtracting one reference-category column. Kink derivatives are never averaged.
"""
    d=prepare(document); p,den=_population(d,latent); intervals=_intervals(d,point)
    cell=[v[0] for v in intervals]; M=_marks(d,point,cell); scale=d['scale']
    raw=[math.fsum(x*y for x,y in zip(row,p)) for row in M]
    values=[scale*(x/den) for x in raw]
    fitted=[d['destination_ids'].index(i) for i in d['fitted_destinations']]
    _require(all(values[i]>=0 for i in fitted), 'negative latent fitted yield; no clipping')
    latent_jac=[[scale*(M[i][k]/den-(raw[i]/den)*(d['denominator_marks'][k]/den))
                 for k in range(len(p))] for i in range(len(M))]
    directional={}; nondifferentiable=[]
    for j,axis in enumerate(d['axes']):
        options=intervals[j]; sides={}
        x=point[axis['name']]
        for interval in options:
            dc=cell.copy();dc[j]=interval
            dm=_marks(d,point,dc,derivative_axis=j)
            value=[scale*(math.fsum(a*b for a,b in zip(row,p))/den) for row in dm]
            # At an interior point both limiting derivatives are the same.
            if x>axis['knots'][interval]: sides['left']=value
            if x<axis['knots'][interval+1]: sides['right']=value
        unique=(len(sides)==1 or sides.get('left')==sides.get('right'))
        directional[axis['name']]={'sides':sides, 'derivative':next(iter(sides.values())) if unique else None,
                                    'two_sided':len(sides)==2,'unique':unique}
        if not unique:nondifferentiable.append(axis['name'])
    numbers=values+[x for row in latent_jac for x in row]+[x for a in directional.values() for v in a['sides'].values() for x in v]
    _require(all(math.isfinite(x) for x in numbers), 'response arithmetic overflow')
    return {'destination_ids':d['destination_ids'],'category_ids':d['category_ids'],
            'values':values,'expected_denominator':den,'latent_jacobian':latent_jac,
            'nuisance_derivatives':directional,'nondifferentiable_axes':nondifferentiable,
            'mark_matrix':M,'scope':'supplied fixed-mark response law; no inferred calibration/likelihood/fit'}


def joint_covariance(document, latent, points):
    """Full same-population template covariance across all requested points.

Exact for fixed-N sample means with constant denominator marks; otherwise a
first-order ratio-of-sums delta approximation. Neither defines a MC likelihood.
"""
    d=prepare(document);p,den=_population(d,latent)
    _require(isinstance(points,list) and 1<=len(points)<=32, 'bounded explicit point population')
    rows=[];basis=[]
    for n,point in enumerate(points):
        value=evaluate(d,latent,point)
        rows.extend(value['latent_jacobian'])
        basis.extend({'point_index':n,'destination':i} for i in d['destination_ids'])
    _require(len(rows)<=512,'bounded covariance coordinates')
    centers=[math.fsum(x*y for x,y in zip(row,p)) for row in rows]
    # Centered Gram form avoids cancellation when the full-population rate is fixed.
    centered=[[x-c for x in row] for row,c in zip(rows,centers)]
    cov=[[math.fsum(p[k]*a[k]*b[k] for k in range(len(p)))/d['total_groups']
          for b in centered] for a in centered]
    _require(all(math.isfinite(x) for row in cov for x in row),'covariance overflow')
    return {'basis':basis,'covariance':cov,'scope':('exact_fixed_N_linear_estimator_covariance' if len(set(d['denominator_marks']))==1 else 'first_order_shared_denominator_delta_covariance'),
            'same_population_cross_covariance_retained':True,'likelihood_inferred':False}


def empirical_group_mean(rows, scale=1.):
    """Estimate a known-divisor IID-group mean and its full sample covariance.

    Rows are complete independent generator groups, including zero-selection
    groups. This is an empirical centered estimate, not the known-category
    population covariance above and not a finite-MC auxiliary likelihood.
    A finite population second moment is a separate physical requirement.
    """
    _require(type(rows) is list and 1 <= len(rows) <= 20000, 'complete bounded IID groups required')
    width = len(rows[0]); n = len(rows)
    _require(1 <= width <= 512 and width*width*n <= 2000000, 'complete group covariance budget exceeded')
    _require(all(type(r) is list and len(r) == width for r in rows), 'same complete coordinate population required')
    clean = [[_number(x) for x in r] for r in rows]; k = _number(scale)
    _require(k > 0, 'positive known external normalization required')
    means = [math.fsum(r[i] for r in clean)/n for i in range(width)]
    values = [k*x for x in means]
    centered = [[x-m for x, m in zip(r, means)] for r in clean]
    covariance = None if n == 1 else [[k*k*math.fsum(r[i]*r[j] for r in centered)/(n*(n-1))
                                     for j in range(width)] for i in range(width)]
    _require(all(math.isfinite(x) for x in values) and
             (covariance is None or all(math.isfinite(x) for row in covariance for x in row)),
             'empirical group moments overflow')
    return {'values': values, 'covariance': covariance, 'groups': n,
            'scope': 'estimated_centered_fixed_N_IID_group_mean_covariance' if n > 1 else 'single_group_covariance_unavailable',
            'population_second_moment_established': False, 'likelihood_inferred': False}


def response(latent, nominal, source_point, configuration, source_data):
    """Existing JointPublishedFiniteMC callback; no new statistical engine."""
    _require(type(configuration) is dict and set(configuration)=={'data_id','axis_to_source'},'closed callback configuration')
    d=prepare(source_data[configuration['data_id']]); mapping=configuration['axis_to_source']
    _require(type(mapping) is dict and set(mapping)=={a['name'] for a in d['axes']} and
             all(type(v) is str and v for v in mapping.values()) and len(set(mapping.values()))==len(mapping),'one-to-one named source coordinates')
    reference=evaluate(d,latent,d['reference_point']); order=[d['destination_ids'].index(i) for i in d['fitted_destinations']]
    _require(isinstance(nominal,list) and len(nominal)==len(order),'nominal MC bin order')
    _require(all(math.isclose(_number(nominal[j]),reference['values'][i],rel_tol=1e-12,abs_tol=1e-12) for j,i in enumerate(order)), 'nominal MC marks/normalization differ from response reference')
    result=evaluate(d,latent,{axis:source_point[name] for axis,name in mapping.items()})
    return [result['values'][i] for i in order]
