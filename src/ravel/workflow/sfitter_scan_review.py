"""Returned signed scans -> existing SFitter domain concern and role workflow.

No fit or new journal. Recompute the source extraction before projecting actual
total rates into the native exact-normalization comparison. Isolated components
remain complete extraction evidence, never masquerade as positive total rates.
"""
from copy import deepcopy
import hashlib
import math
from pathlib import Path

import numpy as np
from ravel.physics import sfitter_scan_extraction as extraction
from ravel.physics.ma5_saf import Capture
from ravel.workflow import agent_graph, sfitter_review_protocol as protocol
from ravel.workflow import sfitter_workflow as workflow

LIMITS = [
    'The supplied observed-return and independent-sample declarations remain premises, not authenticated event or generator consumption.',
    'Total/SM rows alone are native-polynomial probes. All isolated component rows remain in the extractor residual and covariance census.',
    'Native shape central values use the exact width integral; propagated shape covariance uses an explicitly first-order delta Jacobian.',
    'Monte Carlo errors do not change the declared comparison criterion or become a native likelihood nuisance.',
    'Source recomputation and a passing concern do not grant phase advancement, reviewer votes, scientific acceptance or execution.',
    'Other domain concerns, generated-coupling inspection, source convention validity and fit qualification remain independent obligations.',
]


def _read(capture, pin, base):
    path, raw = capture.pin(pin, base)
    return path, workflow._strict_document(raw)


def _pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def _load(request, base):
    extraction._keys(request, ('schema_version', 'id', 'extraction_request', 'extraction_receipt',
                               'regime', 'criteria', 'check_ids', 'claim_scope'), 'scan-review request')
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('integer scan-review schema1 required')
    for key in ('id', 'claim_scope'):
        workflow.sfitter_native._text(request[key], key)
    checks = request['check_ids']
    if type(checks) is not list or not checks or len(set(checks)) != len(checks):
        raise ValueError('original unique scientific check IDs required')
    for name in checks:
        workflow.sfitter_native._text(name, 'original check ID')
    capture = Capture()
    rp, source_request = _read(capture, request['extraction_request'], base)
    original, wf, docs, rates, *_ = extraction._load(source_request, rp.parent)
    current = extraction.extract(source_request, rp.parent)
    cp, receipt = _read(capture, request['extraction_receipt'], base)
    extraction._keys(receipt, ('schema_version', 'kind', 'report', 'parameterization', 'workflow',
                               'handoff_eligible', 'execution_authorized', 'physics_validated',
                               'native_fit_completed'), 'extraction receipt')
    if (receipt['schema_version'] != 1 or receipt['kind'] != 'sfitter_scan_extraction_materialization'
            or receipt['execution_authorized'] is not False or receipt['physics_validated'] is not False
            or receipt['native_fit_completed'] is not False):
        raise ValueError('extraction receipt has no execution/physics authority')
    _, report = _read(capture, receipt['report'], cp.parent)
    if report != current or receipt['handoff_eligible'] is not current['handoff_eligible']:
        raise ValueError('retained extraction does not equal fresh complete source recomputation')
    if not current['handoff_eligible']:
        raise ValueError('unresolved or failed extraction needs owning-phase repair before domain review')
    hp, handoff = _read(capture, receipt['parameterization'], cp.parent)
    wp, continued = _read(capture, receipt['workflow'], cp.parent)
    offset = 0
    expected_rows = []
    for ob in wf['target']['observables']:
        n = len(ob['bins'])
        expected_rows.append({'ID': ob['ID'], 'name': ob['name'], 'modifiers': [
            {'name': term, 'data': row[offset:offset+n]}
            for term, row in zip(current['term_order'][1:], current['coefficients'][1:])],
            'scan_evidence': source_request['rates'], 'coupling_sanity_evidence': source_request['coupling_sanity_evidence'],
            'fit_diagnostics': receipt['report']})
        offset += n
    expected = workflow._absolute_pins({'schema_version': 1, 'phase': 'parameterization',
        'target_sha256': current['target_sha256'], 'sources': [source_request['rates'],
        source_request['coupling_sanity_evidence'], receipt['report']], 'payload': {'rows': expected_rows},
        'physics_validated': False, 'execution_authorized': False}, rp.parent)
    if handoff != expected:
        raise ValueError('parameterization is not the complete extracted coefficient handoff')
    original_wp = Path(source_request['workflow']['path'])
    original_wp = original_wp if original_wp.is_absolute() else rp.parent/original_wp
    expected_wf = workflow._absolute_pins(wf, original_wp.parent)
    expected_wf['handoffs']['parameterization'] = _pin(hp, capture.files[hp][1])
    if continued != expected_wf:
        raise ValueError('continued workflow changed outside its exact returned parameterization')
    workflow._resolve(continued, wp.parent)
    for pin in workflow._refs(continued):
        capture.pin(pin, wp.parent)
    _, regime = _read(capture, request['regime'], base)
    extraction._keys(request['criteria'], ('baseline', 'polynomial'), 'scan-review criteria')
    wanted = [o['ID'] for o in wf['target']['observables']]
    for kind in ('baseline', 'polynomial'):
        extraction._keys(request['criteria'][kind], wanted, 'whole-observable '+kind+' criterion')
        for criterion in request['criteria'][kind].values():
            pins = {}
            protocol._criterion(criterion, base, pins)
            for pin in pins.values():
                capture.pin(pin, base)
    for pin in workflow._refs(regime):
        capture.pin(pin, base)
    original.finish(); capture.finish()
    return capture, original, source_request, continued, docs, current, _pin(wp, capture.files[wp][1]), receipt


def analyze(request, base):
    """Produce the full check data and uncertainty census without writing/roles."""
    capture, original, source_request, wf, docs, result, wp, retained = _load(request, base)
    target = wf['target']; bins = result['bins']; points = result['raw_point_population']
    n, b = len(points), len(bins)
    Y = np.asarray(result['normalized_rates'], dtype=float)
    J = np.eye(n*b); native = Y.copy(); coverage = []; invalid = []
    data = []; independent_sm = []; start = 0
    for group_index, ob in enumerate(target['observables']):
        width = np.asarray(docs['extraction']['payload']['rows'][group_index]['bin_widths'])
        count = len(ob['bins']); subset = slice(start, start+count); selected = []
        for i, point in enumerate(points):
            row = {'point_id': point['id'], 'observable_id': ob['ID'], 'component': point['component'],
                   'role': point['role'], 'selected_weight': point['selected_weight'],
                   'weight_ids': [w['id'] for w in point['weight_population']]}
            if point['component'] not in ('total', 'sm'):
                row.update(disposition='isolated_component_extraction_evidence', native_observed=None)
                coverage.append(row); continue
            observed = Y[i, subset].copy()
            norm = float(observed @ width) if ob['normalization'] == 'normalized' else 1.
            if not math.isfinite(norm): raise ValueError('nonfinite native width integral')
            if norm <= 0:
                row.update(disposition='unresolved_native_normalization', native_observed=None, integral=norm)
                invalid.append(row); coverage.append(row); continue
            with np.errstate(all='raise'):
                try:
                    normalized = extraction._array(observed/norm, 'native observed shape')
                    if ob['normalization'] == 'normalized':
                        transform = extraction._array(np.eye(count)/norm - np.outer(normalized, width)/norm,
                                                      'native shape delta Jacobian')
                        idx = slice(i*b+start, i*b+start+count)
                        J[idx, idx] = transform
                    native[i, subset] = normalized
                except (FloatingPointError, OverflowError) as exc:
                    raise ValueError('native shape arithmetic refused') from exc
            selected.append({'coefficients': [extraction._coordinate(point['values'][axis]) for axis in target['eft']['basis']],
                             'observed': normalized.tolist()})
            row.update(disposition='native_polynomial_probe', native_observed=normalized.tolist(), integral=norm,
                       covariance_scope='first-order delta ratio' if ob['normalization']=='normalized' else 'supplied absolute-rate covariance')
            coverage.append(row)
        sm = docs['sm_template']['payload']['rows'][group_index]
        coefficients = {m['name']: m['data'] for m in workflow._strict_document(
            capture.files[Path(wf['handoffs']['parameterization']['path'])][1])['payload']['rows'][group_index]['modifiers']}
        eft = target['eft']; basis = eft['basis']
        data.append({'observable': ob['ID'], 'offset': sm['data'],
            'linear': {axis: coefficients[axis] for axis in basis},
            'square': {axis: coefficients[axis+'x'+axis] for axis in basis} if eft['quadratic'] else {},
            'mixed': {'x'.join(pair): coefficients['x'.join(pair)] for pair in eft['mixed_pairs']},
            'points': selected, 'bin_widths': width.tolist(), 'criterion': request['criteria']['polynomial'][ob['ID']]})
        for i, point in enumerate(points):
            if point['role'] == 'sm_reference':
                independent_sm.append({'observable': ob['ID'], 'point_id': point['id'],
                    'actual': {'artifact': wf['handoffs']['sm_template'], 'location': '/payload/rows/'+str(group_index)+'/data'},
                    'values': Y[i, subset].tolist(), 'criterion': request['criteria']['baseline'][ob['ID']],
                    'independence': point['independence'], 'source_point_index': i})
        start += count
    if invalid:
        covariance = None; diagnostics = None
    else:
        covariance, diagnostics = extraction._covariance(J, np.asarray(result['normalized_joint_covariance']), 'native shape full covariance')
        covariance = covariance.tolist()
        for group_index, group in enumerate(data):
            offset = sum(len(o['bins']) for o in target['observables'][:group_index]); count = len(group['bin_widths'])
            selected_rows = [i for i, p in enumerate(points) if p['component'] in ('total', 'sm')]
            for row, point_index in zip(group['points'], selected_rows):
                diagonal = [covariance[point_index*b+offset+k][point_index*b+offset+k] for k in range(count)]
                # A tiny negative from accepted numerical PSD tolerance is not
                # clipped into an invented positive error; retain unavailable.
                if all(v >= 0 for v in diagonal): row['mc_errors'] = [math.sqrt(v) for v in diagonal]
    capture.read(__file__, base); capture.read(protocol.__file__, base)
    capture.finish(); original.finish()
    inputs = {p['path']: p for p in [*extraction._pins(capture), *extraction._pins(original)]}
    return {'schema_version': 1, 'kind': 'sfitter_scan_domain_source_projection', 'id': request['id'],
        'workflow': wp, 'polynomial': data, 'independent_sm': independent_sm,
        'coverage': coverage, 'unresolved_native_normalizations': invalid,
        'complete_extraction_report': retained['report'], 'extraction_receipt': request['extraction_receipt'],
        'native_covariance': covariance,
        'covariance_coordinate_order': [{'point_id': p['id'], **bin_} for p in points for bin_ in bins],
        'native_covariance_jacobian': None if invalid else J.tolist(), 'covariance_diagnostics': diagnostics,
        'covariance_scope': 'first-order delta for normalized total/SM rows; unchanged absolute isolated-component rows; full cross terms retained',
        'inputs': sorted(inputs.values(), key=lambda p: p['path']), 'limits': LIMITS,
        'physics_validated': False, 'execution_authorized': False, 'native_fit_completed': False}


def input_pins(request, base):
    return analyze(request, base)['inputs']


def prepare(request_pin, base, output):
    """Write actual protocolV3 data/request/report; no role or journal mutation."""
    source = Capture(); rp, request = _read(source, request_pin, base)
    projection = analyze(request, rp.parent)
    for pin in projection['inputs']: source.pin(pin, rp.parent)
    out = Path(output).absolute()
    if ('..' in out.parts or out.exists() or any(p.is_symlink() for p in (out, *out.parents))
            or any(out.is_relative_to(p.parent) for p in source.files)):
        raise ValueError('fresh review output must preserve all original evidence directories')
    out.mkdir(parents=True); generated = Capture(); written = set()
    def write(name, value):
        written.add(name)
        return extraction._write(out/name, value, out, generated)
    pp = write('scan-domain-projection.json', projection)
    checks = []
    for i, row in enumerate(projection['polynomial']):
        if row['points']:
            checks.append({'id': 'polynomial_'+str(i), 'concern': 'coefficient_baseline',
                'observables': [row['observable']], 'method': 'polynomial',
                'data': {'artifact': pp, 'location': '/polynomial/'+str(i)}})
    for i, row in enumerate(projection['independent_sm']):
        data = {'actual': row['actual'], 'reference': {'artifact': pp, 'location': '/independent_sm/'+str(i)+'/values'},
                'criterion': row['criterion']}
        pin = write('baseline-'+str(i)+'.json', data)
        checks.append({'id': 'baseline_'+str(i), 'concern': 'coefficient_baseline',
            'observables': [row['observable']], 'method': 'vector_agreement', 'data': {'artifact': pin, 'location': ''}})
    if projection['unresolved_native_normalizations']:
        pin = write('unresolved-normalization.json', {'description': 'Actual total/SM returns contain nonpositive or nonfinite native width integrals; no shape reference is invented.',
            'evidence': [{'artifact': pp, 'location': '/unresolved_native_normalizations'}]})
        checks.append({'id': 'unresolved_normalization', 'concern': 'coefficient_baseline',
            'observables': sorted({r['observable_id'] for r in projection['unresolved_native_normalizations']}),
            'method': 'prescribed', 'data': {'artifact': pin, 'location': ''}})
    # Carry every original extraction dependency into the existing protocol's
    # retained source census. A projection's embedded pin list alone is not an
    # input graph traversal. Acceptance definitions stay byte-identical; this
    # derived regime only extends its provenance source list.
    regime_path, regime = _read(source, request['regime'], rp.parent)
    regime = workflow._absolute_pins(regime, rp.parent)
    regime['sources'] = list({p['path']: p for p in [*regime['sources'],
        _pin(regime_path, source.files[regime_path][1]), *projection['inputs']]}.values())
    regime_pin = write('review-regime.json', regime)
    domain = workflow._absolute_pins({'schema_version': 1, 'id': request['id'], 'workflow': projection['workflow'],
        'stage': 'parameterization', 'regime': regime_pin, 'checks': checks,
        'required_concerns': ['coefficient_baseline'], 'check_mapping': {'coefficient_baseline': request['check_ids']},
        'claim_scope': request['claim_scope']}, rp.parent)
    dp = write('domain-request.json', domain)
    report = protocol.context(domain, out)
    dr = write('domain-report.json', report)
    for pin in report['inputs']:
        if not Path(pin['path']).is_relative_to(out): source.pin(pin, out)
    receipt = {'schema_version': 1, 'kind': 'sfitter_scan_domain_preparation', 'source_request': _pin(rp, source.files[rp][1]),
        'projection': pp, 'protocol_request': dp, 'protocol_report': dr,
        'next': 'existing sfitter_review_protocol.prepare_role with exact protocol_request; actual registered judgment required',
        'physics_validated': False, 'execution_authorized': False, 'native_fit_completed': False}
    write('domain-preparation-receipt.json', receipt)
    if {p.relative_to(out).as_posix() for p in out.rglob('*')} != written:
        raise ValueError('ending domain preparation member census changed')
    source.finish(); generated.finish()
    return receipt


def graph(request, base, request_pin):
    pins = list({p['path']: p for p in [request_pin, *input_pins(request, base)]}.values())
    if len(pins) > 128: raise ValueError('whole scan review source graph exceeds input bound')
    return agent_graph.validate({'schema_version': 1, 'graph_id': request['id']+'_domain',
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 1, 'max_wall_seconds': 60, 'max_reworks': 0},
        'nodes': [{'id': 'domain', 'kind': 'tool', 'role': 'designer', 'depends_on': [],
            'inputs': [{'id': 'request' if p['path']==request_pin['path'] else 'source'+str(i), **p} for i,p in enumerate(pins)],
            'packet': None, 'action': 'sfitter-scan-review', 'parameters': {'request_input': 'request'}, 'max_attempts': 1}]})
