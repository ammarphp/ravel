"""Explicit relative denominator search restriction; no density or solver call."""
import math


def relative_denominator_domain(denominator_marks, *, denominator_floor):
    """Build (d/max|d|)·p >= epsilon without rescaling physical halfspaces.

    This changes the old absolute numerical floor, not the density's D>0
    support. It remains a search restriction and provides no optimum/globality
    guarantee. Binary64 division is checked for loss of a nonzero coefficient.
    """
    if (type(denominator_floor) not in (int,float) or not math.isfinite(denominator_floor)
            or not 0 < denominator_floor < 1):
        raise ValueError('explicit dimensionless denominator floor in (0,1) required')
    if not isinstance(denominator_marks,(list,tuple)) or len(denominator_marks)<2:
        raise ValueError('complete fixed-N category denominator vector required')
    d=list(denominator_marks)
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in d):
        raise ValueError('finite literal denominator marks required')
    if not any(x>0 for x in d):
        raise ValueError('positive expected denominator is impossible on the simplex')
    scale=max(abs(x) for x in d)
    row=[x/scale for x in d]
    if any(x!=0 and y==0 for x,y in zip(d,row)):
        raise ValueError('denominator normalization loses a nonzero coefficient; explicit alternative parameterization required')
    return {'denominator_row':row,'denominator_scale':scale,
            'denominator_floor':float(denominator_floor),
            'policy':'relative_max_abs_denominator_floor_v1',
            'density_support_changed':False,'physical_halfspaces_changed':False,
            'numerical_search_policy_changed':True,'global_optimum_coverage':False,
            'scope':'Dimensionless numerical denominator floor. Exact physical constraints and their literal activity rules remain unchanged.'}
