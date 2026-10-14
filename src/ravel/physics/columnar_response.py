"""Source-declared joint selected-object and conditional trigger response.

Preparation authenticates supplied probabilities or complete unweighted joint
counts. It performs no calibration measurement, native call or independence
approximation. A table's detector applicability remains a scientific question.
"""
from copy import deepcopy
from fractions import Fraction
import math
import re
from ravel.physics import root_stream_core as c

CONDITION = 'trigger_given_complete_selected_objects_after_declared_overlap'
METHODS = ('joint_pattern_probabilities', 'joint_pattern_counts',
           'joint_or_probabilities', 'joint_or_counts')


def rational(value, probability=False):
    c.require(type(value) is str and 1 <= len(value) <= 256 and
              re.fullmatch(r'(?:[0-9]{1,128}/[0-9]{1,128}|[0-9]{1,128}(?:\.[0-9]{0,128})?|\.[0-9]{1,128})', value),
              'literal bounded exact rational calibration value required')
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('finite exact source rational denominator required') from exc
    c.require(result >= 0 and (not probability or result <= 1),
              'nonnegative ratio or probability in [0,1] required')
    return result


def represent(value):
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError('calibration factor exceeds finite native representation') from exc
    c.require(math.isfinite(result) and (value == 0 or result != 0),
              'nonzero calibration factor may not underflow or overflow')
    return result


def validate_request(value, signature, triggers):
    c.keys(value, ('schema_version', 'selection_sha256', 'conditioning', 'representation', 'sample_dsids',
                  'coordinates', 'years', 'source', 'acquisition'), 'joint response request')
    c.require(type(value['schema_version']) is int and value['schema_version'] == 1 and
              value['selection_sha256'] == signature and value['conditioning'] == CONDITION,
              'exact changed selection/WP/OR/MET and conditional law required')
    c.pin(value['source'])
    c.require(value['representation'] in ('joint_patterns', 'joint_or'), 'explicit complete joint response representation required')
    dsids = value['sample_dsids']
    c.require(type(dsids) is list and dsids and len(dsids) == len(set(dsids)) and len(dsids) <= 10000,
              'complete distinct calibrated MC sample domain required')
    for dsid in dsids: c.integer(dsid, 1, 10**12, 'calibrated DSID')
    axes = value['coordinates']
    c.require(type(axes) is list and len(axes) <= 16 and len({a['id'] for a in axes}) == len(axes),
              'bounded distinct complete response coordinates required')
    for a in axes:
        c.keys(a, ('id', 'kind', 'branch', 'object', 'rank', 'unit', 'missing'), 'response coordinate')
        c.text(a['id'])
        c.require(a['kind'] in ('scalar', 'count', 'pt', 'abs_eta', 'sum_pt', 'met'),
                  'explicit finite response coordinate kind required')
        c.require(a['unit'] == ('GeV' if a['kind'] in ('pt', 'sum_pt', 'met') else '1'),
                  'coordinate convention required')
        if a['kind'] == 'scalar':
            c.require(type(a['branch']) is str and a['branch'].isidentifier() and
                      a['object'] is None and a['rank'] is None, 'literal scalar response branch required')
        else:
            c.require(a['branch'] is None and (a['kind'] == 'met' and a['object'] is None or
                      a['kind'] != 'met' and type(a['object']) is str), 'selected coordinate source required')
            if a['kind'] in ('pt', 'abs_eta'):
                c.integer(a['rank'], 0, 10000, 'explicit post-OR pT rank')
                if a['missing'] is not None: c.scalar(a['missing'])
            else: c.require(a['rank'] is None, 'rank is not used by this coordinate')
        c.require(a['kind'] in ('pt', 'abs_eta') or a['missing'] is None,
                  'only absent object ranks have a source-declared missing coordinate')
    c.require(type(value['years']) is dict and set(value['years']) == set(triggers),
              'every original declared year must have a response domain')
    total = 0; atoms = 0
    for year, domain in value['years'].items():
        c.keys(domain, ('chains', 'cells'), 'year response domain')
        c.require(domain['chains'] == triggers[year] and len(domain['chains']) <= (12 if value['representation']=='joint_patterns' else 256),
                  'exact complete ordered trigger OR required; no channel subset')
        cells = domain['cells']; total += len(cells)
        atoms += len(cells) * (2**len(domain['chains']) if value['representation']=='joint_patterns' else 2)
        c.require(type(cells) is list and cells and len(cells) <= 256 and
                  len({x['id'] for x in cells}) == len(cells), 'explicit distinct response cells required')
        for cell in cells:
            c.keys(cell, ('id', 'bounds'), 'calibrated cell'); c.text(cell['id'])
            c.require(type(cell['bounds']) is list and len(cell['bounds']) == len(axes), 'all coordinate bounds required')
            for lohi in cell['bounds']:
                c.require(type(lohi) is list and len(lohi) == 2 and
                          math.isfinite(c.scalar(lohi[0])) and
                          (lohi[1] is None or c.scalar(lohi[1]) > lohi[0]), 'half-open finite calibration bounds required')
        for i, left in enumerate(cells):
            for right in cells[i+1:]:
                disjoint = any((a[1] is not None and a[1] <= b[0]) or
                               (b[1] is not None and b[1] <= a[0]) for a, b in zip(left['bounds'], right['bounds']))
                c.require(disjoint, 'overlapping or duplicate calibration cells refused')
    c.require(total <= 1024 and atoms <= 65536, 'prospective complete response table bound exceeded')
    acq = value['acquisition']
    c.keys(acq, ('producer', 'configuration_source', 'required_measurements', 'limitations'), 'calibration acquisition')
    c.require(acq['producer'] in ('source_joint_table', 'source_joint_unweighted_counts',
                                 'bound_native_global_lepton_efficiency'), 'supported preparation producer required')
    c.pin(acq['configuration_source'])
    c.require(type(acq['required_measurements']) is list and acq['required_measurements'] and
              type(acq['limitations']) is list and acq['limitations'], 'explicit acquisition obligations and validity limits required')
    for text in (*acq['required_measurements'], *acq['limitations']): c.text(text)
    return deepcopy(value)


def _efficiency(value, method, n):
    pattern = method.startswith('joint_pattern')
    count = method.endswith('_counts')
    if pattern:
        c.require(type(value) is list and len(value) == 2**n,
                  'all joint trigger atoms including zero/failed outcome required')
        if count:
            for x in value: c.integer(x, 0, 10**15, 'original unweighted joint atom count')
            total = sum(value); c.require(total > 0, 'full nonzero calibration denominator required')
            atoms = [Fraction(x, total) for x in value]
        else:
            atoms = [rational(x, True) for x in value]
            c.require(sum(atoms, Fraction()) == 1, 'exact complete joint probabilities must sum to one')
        return sum(atoms[1:], Fraction()), [str(x) for x in atoms]
    if count:
        c.keys(value, ('passed', 'total'), 'full joint event OR counts')
        c.integer(value['total'], 1, 10**15, 'original calibration denominator')
        c.integer(value['passed'], 0, value['total'], 'joint OR passing count')
        q = Fraction(value['passed'], value['total'])
    else:
        q = rational(value, True)
    return q, None


def prepare(request, request_pin, payload, signature, triggers):
    """Actual finite count/probability lowering; no fitted efficiency invented."""
    request = validate_request(request, signature, triggers); c.pin(request_pin)
    if payload is None:
        return {'ready': False, 'request': deepcopy(request), 'request_pin': deepcopy(request_pin),
                'missing': ['complete_joint_selected_object_and_conditional_trigger_response'],
                'next_action': 'Supply the declared source joint probabilities or complete unweighted joint counts, then rerun ntuple-inventory.',
                'physics_validated': False}
    c.keys(payload, ('schema_version', 'request_sha256', 'method', 'source', 'inputs', 'cells'), 'calibration payload')
    c.require(type(payload['schema_version']) is int and payload['schema_version'] == 1 and
              payload['request_sha256'] == request_pin['sha256'] and payload['method'] in METHODS,
              'payload must bind the exact source request and supported joint method')
    c.require(payload['method'].startswith('joint_pattern') == (request['representation']=='joint_patterns'),
              'payload must retain the original complete joint representation')
    c.pin(payload['source'])
    c.require(type(payload['inputs']) is list and len(payload['inputs']) <= 64, 'complete bounded calibration input roster required')
    for pin in payload['inputs']: c.pin(pin)
    roster = [(y, x['id']) for y, d in request['years'].items() for x in d['cells']]
    c.require(type(payload['cells']) is list and [(x['year'], x['id']) for x in payload['cells']] == roster,
              'complete ordered year/cell population required')
    compiled = []
    for row in payload['cells']:
        c.keys(row, ('year', 'id', 'data', 'mc', 'selected_object_ratio'), 'joint response cell')
        n = len(triggers[row['year']]); data, da = _efficiency(row['data'], payload['method'], n)
        mc, ma = _efficiency(row['mc'], payload['method'], n)
        obj = rational(row['selected_object_ratio'])
        # Zero support is retained as unavailable, never replaced by unity.
        sf = None if mc == 0 else obj * data / mc
        compiled.append({**deepcopy(row), 'epsilon_data': str(data), 'epsilon_mc': str(mc),
                         'data_atoms': da, 'mc_atoms': ma,
                         'event_factor': None if sf is None else represent(sf)})
    return {'ready': True, 'request': request, 'request_pin': deepcopy(request_pin),
            'method': payload['method'], 'cells': compiled, 'original_payload': deepcopy(payload),
            'arithmetic': 'exact rational joint probability/count lowering; final factor finite binary64',
            'detector_calibration_qualified': False, 'physics_validated': False}


def factor(compiled, year, dsid, coordinates, trigger_passed):
    req = compiled['request']
    c.require(compiled['ready'] and dsid in req['sample_dsids'] and year in req['years'],
              'actual MC year/DSID outside calibrated source domain')
    cells = req['years'][year]['cells']
    matches = [x['id'] for x in cells if all(b[0] <= z and (b[1] is None or z < b[1])
                                             for b, z in zip(x['bounds'], coordinates))]
    c.require(len(coordinates) == len(req['coordinates']) and len(matches) == 1,
              'actual selected event has no unique calibrated support; no extrapolation')
    row = next(x for x in compiled['cells'] if x['year'] == year and x['id'] == matches[0])
    if not trigger_passed:
        # No region is filled. This is an explicitly unapplied correction,
        # never evidence of efficiency=1; the full original exposure stays.
        return 1.0
    c.require(row['event_factor'] is not None and rational(row['epsilon_mc'], True) > 0,
              'accepted event has zero MC trigger support; no unity fallback')
    return row['event_factor']
