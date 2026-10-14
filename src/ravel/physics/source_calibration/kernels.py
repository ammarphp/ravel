"""Source-ready scalar kernels for a later approved, decoded calibration graph.

No ROOT values are decoded here. Callers must supply checked object arrays,
axis routing and analysis-matched provenance. Synthetic probes verify math only.
"""
from bisect import bisect_right
import math

def findfixbin_axis(value, edges):
    """Pinned Athena policy: clamp xmin, then xmax*.999, ROOT upper-edge bin."""
    if type(value) not in (int,float) or not math.isfinite(value) or len(edges)<2 or not all(type(x) in (int,float) and math.isfinite(x) for x in edges):
        raise ValueError('finite coordinates and decoded axes required')
    if any(a>=b for a,b in zip(edges,edges[1:])):
        raise ValueError('decoded edges must increase')
    coordinate=min(max(value,edges[0]),edges[-1]*.999)
    index=bisect_right(edges,coordinate)-1
    if not 0<=index<len(edges)-1:
        raise ValueError('source clamp produced overflow; retain explicit ROOT flow semantics')
    return index,coordinate

def th2_value(x,y,xedges,yedges,values):
    """Values explicitly indexed [x bin][y bin]; never infer ROOT storage order."""
    if len(values)!=len(xedges)-1 or any(len(row)!=len(yedges)-1 for row in values):
        raise ValueError('decoded TH2 layout differs from axes')
    i,_=findfixbin_axis(x,xedges)
    j,_=findfixbin_axis(y,yedges)
    value=values[i][j]
    if not math.isfinite(value):raise ValueError('nonfinite decoded bin')
    return value

def relative_variation(nominal, magnitudes, direction):
    """CommonEfficiencyTool: sf*(1 +/- sqrt(sum((sigma*parameter)^2)))."""
    if type(direction) is not int or direction not in (-1,1) or type(nominal) not in (int,float) or nominal<0 or not math.isfinite(nominal):
        raise ValueError('valid sf and one systematic direction required')
    if not all(type(x) in (int,float) and math.isfinite(x) and x>=0 for x in magnitudes):raise ValueError('finite uncertainties required')
    out=nominal*(1+direction*math.sqrt(math.fsum(x*x for x in magnitudes)))
    if out<0:raise ValueError('negative calibrated response variation')
    return out

def faded_value(value,factor,is_nominal):
    """CommonSmearingTool title fading: (sf-1)*f+1 versus uncertainty*f."""
    if type(is_nominal) is not bool or not all(type(x) in (int,float) and math.isfinite(x) for x in [value,factor]):raise ValueError('finite fade required')
    return (value-1)*factor+1 if is_nominal else value*factor

def exclusive_probabilities(loose,medium,tight):
    """Marginal efficiencies define exclusive outcomes only with all three."""
    if not all(type(x) in (int,float) and math.isfinite(x) for x in [loose,medium,tight]) or not 0<=tight<=medium<=loose<=1:
        raise ValueError('nested calibrated absolute efficiencies required')
    return {'fail':1-loose,'loose_only':loose-medium,'medium_only':medium-tight,'tight':tight}

def exclusive_scale_factors(mc_efficiencies,data_efficiencies):
    """An ID scale factor alone cannot weight the failed tighter WP category."""
    mc=exclusive_probabilities(*mc_efficiencies)
    data=exclusive_probabilities(*data_efficiencies)
    if any(mc[k]==0 and data[k]>0 for k in mc):raise ValueError('data-support category absent from reference MC')
    ratios={key:data[key]/mc[key] if mc[key] else None for key in mc}
    if any(value is not None and not math.isfinite(value) for value in ratios.values()):
        raise ValueError('Nonfinite exclusive response ratio')
    return ratios

def joint_selection_scale_factor(mc,data,accepted_categories):
    """Use a calibrated joint table, preserving correlations and ID/trigger OR.

    Keys label exhaustive mutually exclusive outcomes. This function does not
    invent independence from per-leg SFs or construct an absolute efficiency.
    """
    if not isinstance(accepted_categories,(list,tuple)) or len(accepted_categories)!=len(set(accepted_categories)):
        raise ValueError('Unique explicit accepted categories required')
    if set(mc)!=set(data) or not set(accepted_categories)<=set(mc):raise ValueError('joint outcomes incomplete')
    for table in [mc,data]:
        if any(type(p) not in (int,float) or not math.isfinite(p) or p<0 or p>1 for p in table.values()) or not math.isclose(math.fsum(table.values()),1.,rel_tol=0.,abs_tol=1e-12):
            raise ValueError('joint probability table must be normalized')
    denominator=math.fsum(mc[k] for k in accepted_categories)
    if denominator<=0:raise ValueError('zero MC selection support')
    ratio=math.fsum(data[k] for k in accepted_categories)/denominator
    if not math.isfinite(ratio):raise ValueError('Nonfinite joint response ratio')
    return ratio

