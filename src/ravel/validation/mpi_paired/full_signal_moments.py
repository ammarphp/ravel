"""Private source-only full-channel bridge after authenticated MPI trace intake.

No file access, random draw, simulator or statistical model is invoked. The
caller must establish full original-content pairing and all custody receipts.
Constant positive weights, fixed analyzed N and a declared inclusive source
rate are required. Covariances estimate Monte Carlo sampling uncertainty under
an iid supplied-event law, conditional on the fixed response/settings; they do
not describe official-template uncertainty or unknown historical covariance.
"""
import math
import json
from ravel.validation import diagnostic_plan as plans


def require(value, message):
    if not value:
        raise ValueError(message)


def specification(channel_order, channel_map, trace_regions):
    require(type(channel_order) in (list,tuple) and channel_order and len(set(channel_order))==len(channel_order),'distinct supplied channels required')
    require(type(channel_map) is list and len(channel_map)==len(channel_order),'complete supplied channel mapping required')
    require([row.get('channel') for row in channel_map]==list(channel_order),'ordered channel map differs')
    require(type(trace_regions) is list and trace_regions and len(set(trace_regions))==len(trace_regions) and all(type(x) is str and x for x in trace_regions),'complete supplied trace region population required')
    require(all(row['region'] in trace_regions for row in channel_map),'channel region absent from supplied trace population')
    predicates=[]
    for row in channel_map:
        require(set(row)=={'channel','region','equals','lengths'} and type(row['region']) is str and row['region'],'explicit channel region and predicates required')
        require(type(row['equals']) is dict and type(row['lengths']) is dict,'explicit channel predicates required')
        require(all(type(k) is str and k and type(v) in (int,float,str,bool) for k,v in row['equals'].items()),'typed equality predicates required')
        require(all(type(k) is str and k and type(v) is int and v>=0 for k,v in row['lengths'].items()),'typed length predicates required')
        predicates.append(json.dumps({k:v for k,v in row.items() if k!='channel'},sort_keys=True))
    require(len(set(predicates))==len(predicates),'channel aliases require a distinct predicate')
    return channel_map


def _field(row,path):
    value=row
    for key in path.split('.'):
        try:value=value[int(key)] if isinstance(value,list) else value[key]
        except (KeyError,IndexError,TypeError,ValueError):
            raise ValueError('Required channel predicate field absent: '+path) from None
    return value


def indicator(row,mapping,trace_regions):
    accepted=row.get('accepted_regions')
    require(type(accepted) is list and len(set(accepted))==len(accepted) and all(type(x) is str for x in accepted),'unique literal regions required')
    require(set(accepted)<=set(trace_regions),'unknown supplied trace region')
    values=[]
    for rule in mapping:
        if rule['region'] not in accepted:values.append(0);continue
        for path,length in rule['lengths'].items():
            value=_field(row,path)
            require(type(value) is list and len(value)==length,'retained channel object population differs')
        matches=True
        for path,expected in rule['equals'].items():
            value=_field(row,path)
            require(type(value) is type(expected),'retained predicate value type differs')
            matches &= value==expected
        values.append(int(matches))
    return values


def _covariance(left, right, sums_left, sums_right, scale):
    """Unbiased sample-mean covariance from exact integer sufficient statistics."""
    n, d = len(left), len(sums_left)
    joint = [[0] * d for _ in range(d)]
    for lrow, rrow in zip(left, right):
        for i, lv in enumerate(lrow):
            if lv:
                for j, rv in enumerate(rrow):
                    if rv: joint[i][j] += lv * rv
    # Integer numerator avoids cancellation for exactly identical paired arms.
    return [[scale * (n * joint[i][j] - sums_left[i] * sums_right[j]) /
             (n * n * (n - 1)) for j in range(d)] for i in range(d)]


def summarize(on_rows, off_rows, *, channel_order, channel_map, trace_regions, analyzed_events, original_events,
              cross_section_pb, kfactor, luminosity_pb_inverse):
    require(type(analyzed_events) is int and type(original_events) is int and
            1 < analyzed_events <= original_events, "Explicit analyzed/source exposures required")
    n = analyzed_events
    require(len(on_rows) == len(off_rows) == n, "Full paired exposure required, including unselected events")
    for value in (cross_section_pb, kfactor, luminosity_pb_inverse):
        require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                "Finite positive source cross section, correction and luminosity required")
    total_yield_scale = cross_section_pb * kfactor * luminosity_pb_inverse
    require(math.isfinite(total_yield_scale) and math.isfinite(total_yield_scale**2), "Rate product overflows")
    mapping = specification(channel_order,channel_map,trace_regions)
    arms = []
    all_weights = []
    for rows in (on_rows, off_rows):
        require([r.get("event_id") for r in rows] == list(range(n)) and
                all(type(r.get("event_id")) is int for r in rows), "Literal complete local trace order required")
        weights = [r.get("weight_pb") for r in rows]
        require(all(type(w) in (int, float) and math.isfinite(w) and w > 0 for w in weights),
                "Finite positive trace weights required")
        all_weights.extend(float(w).hex() for w in weights)
        arms.append([indicator(row, mapping,trace_regions) for row in rows])
    require(len(set(all_weights)) == 1, "This estimator requires identical constant weights in both arms")
    expected_weight = cross_section_pb*kfactor/n
    require(math.isclose(float.fromhex(all_weights[0]), expected_weight, rel_tol=2e-6, abs_tol=0),
            "Trace weights do not use the declared analyzed exposure and exactly one correction")
    on, off = arms
    differences = [[b-a for a,b in zip(left,right)] for left,right in zip(on,off)]
    counts = [[sum(row[i] for row in arm) for i in range(len(mapping))] for arm in arms]
    dcounts = [b-a for a,b in zip(*counts)]
    scale = total_yield_scale**2
    return {"schema_version": 1, "channel_order": list(channel_order),
        "exposure": {"original_generation_events": original_events, "analyzed_paired_events": n},
        "normalization": {"cross_section_pb": cross_section_pb, "kfactor": kfactor,
            "luminosity_pb_inverse": luminosity_pb_inverse, "correction_applications": 1,
            "expected_constant_trace_weight_pb": expected_weight,
            "yield_per_accepted_event": total_yield_scale/n},
        "counts_on": counts[0], "counts_off": counts[1],
        "yields_on": [total_yield_scale*c/n for c in counts[0]],
        "yields_off": [total_yield_scale*c/n for c in counts[1]],
        "yield_delta_off_minus_on": [total_yield_scale*c/n for c in dcounts],
        "yield_covariance_on": _covariance(on,on,counts[0],counts[0],scale),
        "yield_covariance_off": _covariance(off,off,counts[1],counts[1],scale),
        "yield_cross_covariance_on_off": _covariance(on,off,counts[0],counts[1],scale),
        "yield_delta_covariance": _covariance(differences,differences,dcounts,dcounts,scale),
        "overlap_events_on": sum(sum(row)>1 for row in on),
        "overlap_events_off": sum(sum(row)>1 for row in off),
        "scope": "Fixed-size Monte Carlo yield moments conditional on supplied-event law and current response",
        "limits": ["Local row order alone is not proof of original hard-event pairing; authenticated transport is a caller prerequisite.",
                   "Observed channel overlaps are retained in all joint moments, never silently assigned to one channel.",
                   "Source rate, K factor and luminosity are held fixed; their uncertainties are not estimated here.",
                   "No official-template or historical cross-covariance is supplied or assumed zero.",
                   "An empty observed bin has a zero plug-in covariance estimate, not a zero-acceptance proof.",
                   "These channel moments do not change the supplied primary estimand."]}
