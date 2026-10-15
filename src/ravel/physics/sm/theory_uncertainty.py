"""Theory bands from supplied members; GPL libraries stay in their own worker.

Class quadrature and marginal-error covariance are declared models, not likelihoods.
No native process is launched here. PDF requests are job specifications for the
existing admitted, supervised execution route; returned bytes must bind that request.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import gzip
import json
import math
from pathlib import Path
import re

import numpy as np
from jsonschema import Draft202012Validator

from ravel.physics import pdf_variations, yoda_text

DATA = Path(__file__).resolve().parents[2] / 'data' / 'sm'
CLASSES = ('scale', 'pdf', 'alphas', 'ew', 'np', 'shower', 'mpi', 'tune', 'mtop', 'mcstat')


def _number(value):
    # Reuse the established finite-number contract; no existing PDF scope changes.
    return pdf_variations._number(value)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def read_pdf_info(text):
    """Extract scalar metadata from supplied .info bytes without loading LHAPDF.

    Keep complete source text and digest so the isolated worker can bind the actual
    installed file. Missing confidence metadata stays unknown until library loading.
    """
    if not isinstance(text, str):
        raise ValueError('PDF .info text required')
    fields = {}
    for line in text.splitlines():
        match = re.match(r'^(ErrorType|NumMembers|ErrorConfLevel|AlphaS_MZ):\s*(.*?)\s*(?:#.*)?$', line)
        if match:
            key, value = match.groups()
            if key in fields:
                raise ValueError('duplicate PDF .info metadata')
            fields[key] = value.strip().strip('\"\'')
    kind = fields.get('ErrorType')
    if kind not in ('hessian', 'symmhessian', 'replicas', 'hessian+as', 'symmhessian+as', 'replicas+as'):
        raise ValueError('supported PDF .info ErrorType required')
    try:
        count = int(fields['NumMembers'])
    except (KeyError, ValueError) as exc:
        raise ValueError('PDF .info NumMembers required') from exc
    if count < 2:
        raise ValueError('PDF .info uncertainty member population required')
    cl = float(fields['ErrorConfLevel']) if 'ErrorConfLevel' in fields else None
    if cl is not None and not 0 < _number(cl) < 100:
        raise ValueError('PDF confidence level must be between zero and 100')
    alpha = float(fields['AlphaS_MZ']) if 'AlphaS_MZ' in fields else None
    if alpha is not None and _number(alpha) <= 0:
        raise ValueError('positive PDF alpha_s required')
    return {'error_type': kind, 'num_members': count, 'confidence_level_percent': cl,
            'alpha_s_mz': alpha, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'text': text}


def validate_bundle(bundle):
    """Validate schema, finite vectors, bin ordering and declared normalization."""
    schema = json.loads((DATA / 'schema/prediction-bundle.schema.json').read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(bundle), key=lambda e: str(e.path))
    if errors:
        raise ValueError('prediction bundle: ' + errors[0].message)
    n = len(bundle['central'])
    if n != len(bundle['binning']):
        raise ValueError('one central value per bin required')
    previous = None
    for cell in bundle['binning']:
        lo, hi = _number(cell['lo']), _number(cell['hi'])
        if lo >= hi or (previous is not None and lo < previous):
            raise ValueError('increasing nonoverlapping binning required')
        previous = hi
    for key in ('central',):
        for value in bundle[key]:
            _number(value)
    ids = set()
    for member in bundle['members']:
        if member['id'] in ids:
            raise ValueError('unique member ids required')
        ids.add(member['id'])
        if len(member['values']) != n:
            raise ValueError('one member value per bin required')
        for value in member['values']:
            _number(value)
        for field in ('mu_r', 'mu_f', 'alpha_s_mz', 'dyn_scale'):
            if field in member:
                _number(member[field])
    _number(bundle['inputs']['alpha_s_mz'])
    for value in bundle['inputs']['masses'].values():
        _number(value)
    if 'pdf' in bundle['inputs']:
        pdf = bundle['inputs']['pdf']
        if 'info' in pdf and pdf['info'] != read_pdf_info(pdf['info']['text']):
            raise ValueError('PDF .info metadata differs from source bytes')
        if 'alpha_s_mz' in pdf:
            _number(pdf['alpha_s_mz'])
    target = bundle.get('normalization_order', bundle['order']['qcd'])
    declaration = bundle.get('normalization_declaration')
    if target != bundle['order']['qcd'] and declaration is None:
        raise ValueError('different-order normalization declaration required')
    if declaration is not None:
        if (declaration['shape_order'] != bundle['order']['qcd']
                or declaration['cross_section_order'] != target
                or _number(declaration['factor']) <= 0):
            raise ValueError('normalization declaration differs from order or positive common factor')
    if 'band' in bundle:
        rows = [bundle['band']] + list(bundle['band']['by_class'].values())
        for row in rows:
            for key in ('minus', 'plus'):
                if len(row[key]) != n or any(_number(v) < 0 for v in row[key]):
                    raise ValueError('nonnegative band aligned with prediction bins required')
    if 'theory_covariance' in bundle:
        cov = bundle['theory_covariance']
        for value in [cov['total']] + list(cov['by_class'].values()):
            matrix = np.array(value, dtype=float)
            if (matrix.shape != (n, n) or not np.isfinite(matrix).all()
                    or not np.allclose(matrix, matrix.T, rtol=1e-12, atol=1e-12)
                    or np.linalg.eigvalsh(matrix).min() < -1e-12 * max(1, np.max(np.abs(matrix)))):
                raise ValueError('finite symmetric bin-aligned positive-semidefinite covariance required')
    return bundle


def _members(bundle, kind):
    return [m for m in bundle['members'] if m['class'] == kind]


def _prescription(bundle, kind):
    value = bundle['prescriptions'].get(kind)
    if value is None:
        raise ValueError(f'{kind} prescription required for every classified member')
    return {'method': value} if isinstance(value, str) else value


def _envelope(central, members):
    rows = np.array([central] + [m['values'] for m in members], dtype=float)
    return (np.asarray(central) - rows.min(axis=0)).tolist(), (rows.max(axis=0) - central).tolist()


def _scale(bundle, members, prescription):
    method = prescription['method']
    if method not in ('7pt-envelope', '9pt-envelope', 'independent-muR-muF'):
        raise ValueError('supported scale prescription required')
    points = {}
    dyn = {m.get('dyn_scale') for m in members}
    if len(dyn) > 1:
        raise ValueError('scale population must use one declared dynamical scale')
    for m in members:
        if 'mu_r' not in m or 'mu_f' not in m:
            raise ValueError('scale population needs explicit mu_r and mu_f ratios')
        key = (m['mu_r'], m['mu_f'])
        if key in points:
            raise ValueError('duplicate scale population point')
        points[key] = m
    central = bundle['central']
    if (1, 1) in points and points[(1, 1)]['values'] != central:
        raise ValueError('nominal scale member differs from central prediction')
    # The central point may be supplied as central rather than repeated as a stream.
    allpoints = {(r, f) for r in (.5, 1, 2) for f in (.5, 1, 2)}
    seven = allpoints - {(.5, 2), (2, .5)}
    axis = {(1, 1), (.5, 1), (2, 1), (1, .5), (1, 2)}
    actual = set(points) | {(1, 1)}
    allowed = (allpoints,) if method == '9pt-envelope' else (seven, allpoints) if method == '7pt-envelope' else (axis, seven, allpoints)
    if actual not in allowed:
        raise ValueError('complete supported scale population required; missing or foreign point')
    selected = [m for m in members if (m['mu_r'], m['mu_f']) in (allpoints if method == '9pt-envelope' else seven if method == '7pt-envelope' else axis)]
    if method == 'independent-muR-muF':
        r = _envelope(central, [m for m in selected if m['mu_f'] == 1])
        f = _envelope(central, [m for m in selected if m['mu_r'] == 1])
        minus, plus = [np.hypot(r[i], f[i]).tolist() for i in (0, 1)]
    else:
        minus, plus = _envelope(central, selected)
    return {'minus': minus, 'plus': plus, 'selected_member_ids': [m['id'] for m in selected],
            'excluded_member_ids': [m['id'] for m in members if m not in selected], 'prescription': method}


def pdf_worker_request(bundle):
    """Return a complete JSON worker input, never launch a process."""
    validate_bundle(bundle)
    pdf = bundle['inputs']['pdf']
    info = pdf.get('info')
    if info is None:
        raise ValueError('PDF .info ErrorType and complete member metadata required')
    prescription = _prescription(bundle, 'pdf')
    kind = info['error_type']
    if (prescription['method'] != 'lhapdf-error-type' or pdf['error_type'] != kind
            or prescription.get('error_type', kind) != kind):
        raise ValueError('PDF prescription must use the .info ErrorType')
    composite = kind.endswith('+as')
    components = prescription.get('components', ['pdf'])
    if components != (['pdf', 'alphas'] if composite else ['pdf']):
        raise ValueError('explicit composite components must match the .info ErrorType')
    if composite and (_members(bundle, 'alphas') or 'alphas' in bundle['prescriptions']):
        raise ValueError('PDF composite and separate alpha_s double counting refused')
    members = _members(bundle, 'pdf')
    ids = [m.get('pdf_member') for m in members]
    if any(type(i) is not int for i in ids) or sorted(ids) != list(range(info['num_members'])):
        raise ValueError('complete unique PDF member population including member zero required')
    members = sorted(members, key=lambda m: m['pdf_member'])
    if members[0]['values'] != bundle['central']:
        raise ValueError('PDF member zero differs from supplied central')
    count = len(members) - 1 - (2 if composite else 0)
    base_kind = kind.split('+')[0]
    if count < 1 or (base_kind == 'hessian' and (count < 2 or count % 2)) or (base_kind == 'replicas' and count < 2):
        raise ValueError('PDF ErrorType member count is incompatible')
    cl = _number(prescription.get('confidence_level_percent', 68.268949))
    if not 0 < cl < 100:
        raise ValueError('requested PDF confidence level must be between zero and 100')
    return {'schema_version': 1, 'kind': 'pdf-uncertainty-request', 'set': pdf['set'],
            'info': deepcopy(info), 'member_ids': list(range(info['num_members'])),
            'member_values': [m['values'] for m in members], 'confidence_level_percent': cl}


def _pdf(bundle, result):
    request = pdf_worker_request(bundle)
    if not isinstance(result, dict) or result.get('request_sha256') != _digest(request):
        raise ValueError('PDF worker request binding missing or stale')
    if (result.get('kind') != 'pdf-uncertainty-result' or result.get('schema_version') != 1
            or result.get('set') != request['set'] or result.get('info_sha256') != request['info']['sha256']
            or result.get('error_type') != request['info']['error_type']
            or result.get('member_ids') != request['member_ids']
            or result.get('confidence_level_percent') != request['confidence_level_percent']):
        raise ValueError('PDF worker request metadata differs')
    bins = result.get('bins')
    if not isinstance(bins, list) or len(bins) != len(bundle['central']):
        raise ValueError('complete PDF worker bins required')
    for row in bins:
        if not isinstance(row, dict) or not {'central', 'minus', 'plus', 'symmetric'} <= set(row):
            raise ValueError('complete PDF worker bins required')
        for key in ('central', 'minus', 'plus', 'symmetric'):
            value = _number(row[key])
            if key != 'central' and value < 0:
                raise ValueError('nonnegative PDF worker errors required')
    # Replica mean is retained separately; caller-supplied member zero stays central.
    return {'minus': [r['minus'] for r in bins], 'plus': [r['plus'] for r in bins],
            'ensemble_central': [r['central'] for r in bins], 'prescription': 'lhapdf-error-type',
            'components': ['pdf', 'alphas'] if request['info']['error_type'].endswith('+as') else ['pdf'],
            'confidence_level_percent': request['confidence_level_percent'],
            'request_sha256': result['request_sha256'], 'info_sha256': result['info_sha256']}


def _alphas(bundle, members, prescription):
    method = prescription['method']
    nominal = bundle['inputs']['alpha_s_mz']
    if method not in ('pdf-set-members', 'plus-minus-delta'):
        raise ValueError('alpha_s prescription needs member values; derivatives are never inferred')
    if len(members) != 2 or any('alpha_s_mz' not in m for m in members):
        raise ValueError('two alpha_s members with matching coupling metadata required')
    couplings = sorted(_number(m['alpha_s_mz']) for m in members)
    if not couplings[0] < nominal < couplings[1]:
        raise ValueError('alpha_s members must bracket the matrix-element coupling')
    if method == 'plus-minus-delta':
        delta = _number(prescription.get('delta'))
        if delta <= 0 or any(not math.isclose(abs(a - nominal), delta, rel_tol=1e-9, abs_tol=1e-12) for a in couplings):
            raise ValueError('alpha_s members differ from declared delta')
    for member in members:
        if member.get('pdf_alpha_s_mz') != member['alpha_s_mz']:
            raise ValueError('alpha_s variation requires matching PDF alpha_s metadata')
    # Symmetric half-difference, with supplied confidence level/step recorded verbatim.
    error = (np.abs(np.array(members[0]['values']) - members[1]['values']) / 2).tolist()
    return {'minus': error, 'plus': error, 'prescription': deepcopy(prescription)}


def _ew(bundle, members, prescription):
    roles = {m.get('role'): m for m in members}
    if len(roles) != len(members) or set(roles) != {'multiplicative', 'additive'}:
        raise ValueError('EW multiplicative and additive comparison required')
    method = prescription['method']
    if method == 'difference-as-uncertainty':
        error = np.abs(np.array(roles['multiplicative']['values']) - roles['additive']['values']).tolist()
        return {'minus': error, 'plus': error, 'prescription': method}
    if method not in roles:
        raise ValueError('supported EW prescription required')
    minus, plus = _envelope(bundle['central'], [roles[method]])
    return {'minus': minus, 'plus': plus, 'prescription': method,
            'selected_values': roles[method]['values'], 'comparison_values': roles['additive' if method == 'multiplicative' else 'multiplicative']['values']}


def band(bundle, *, pdf_result=None):
    """Return nonnegative errors by class and independent-class quadrature.

    EW members contain absolute predictions. NP members contain ratios; errors
    are deviations around ratio one applied once to the supplied central values.
    Central values are never silently replaced or renormalized.
    """
    validate_bundle(bundle)
    by_class = {}
    present = {m['class'] for m in bundle['members']} - {'unclassified'}
    if set(bundle['prescriptions']) - present:
        raise ValueError('prescription without supplied class members')
    for kind in CLASSES:
        members = _members(bundle, kind)
        if not members:
            continue
        prescription = _prescription(bundle, kind)
        if kind == 'scale':
            result = _scale(bundle, members, prescription)
        elif kind == 'pdf':
            result = _pdf(bundle, pdf_result)
        elif kind == 'alphas':
            result = _alphas(bundle, members, prescription)
        elif kind == 'ew':
            result = _ew(bundle, members, prescription)
        else:
            if kind == 'np':
                if bundle.get('np_already_applied') is not False:
                    raise ValueError('NP already applied or applicability undeclared; explicit false required')
                if prescription['method'] != 'ratio-envelope' or any(m.get('quantity') != 'ratio' for m in members):
                    raise ValueError('NP ratio-envelope needs ratio members')
                if any(v <= 0 for m in members for v in m['values']):
                    raise ValueError('positive NP ratios required')
                converted = [dict(m, values=(np.array(m['values']) * bundle['central']).tolist()) for m in members]
            else:
                if prescription['method'] != 'envelope':
                    raise ValueError(f'explicit envelope prescription required for {kind}')
                converted = members
            minus, plus = _envelope(bundle['central'], converted)
            result = {'minus': minus, 'plus': plus, 'prescription': prescription['method']}
        if any(not math.isfinite(v) for k in ('minus', 'plus') for v in result[k]):
            raise ValueError('nonfinite theory band')
        by_class[kind] = result
    out = {direction: [math.hypot(*(row[direction][i] for row in by_class.values()))
                       for i in range(len(bundle['central']))] for direction in ('minus', 'plus')}
    out.update(by_class=by_class, combination='independent-classes-quadrature',
               unclassified=[m['id'] for m in _members(bundle, 'unclassified')])
    return out


def theory_covariance(bundle, model, *, pdf_result=None):
    """Build declared marginal-error covariance: max of down/up for each bin.

    Every class needs its own bin correlation model. No scale envelope becomes a
    Gaussian law; the matrix is a declared second-moment proxy for supplied use.
    """
    bands = band(bundle, pdf_result=pdf_result)['by_class']
    if not isinstance(model, dict) or set(model) != set(bands):
        raise ValueError('explicit correlation model for exactly every theory class required')
    matrices = {}
    n = len(bundle['central'])
    for kind, row in bands.items():
        rule = model[kind]
        if rule in ('fully-correlated', 'fully correlated'):
            rho = np.ones((n, n))
        elif rule == 'uncorrelated':
            rho = np.eye(n)
        elif isinstance(rule, dict) and set(rule) == {'kind', 'values'} and rule['kind'] == 'matrix':
            rho = np.array(rule['values'], dtype=float)
            if (rho.shape != (n, n) or not np.isfinite(rho).all()
                    or not np.allclose(rho, rho.T, rtol=0, atol=1e-12)
                    or not np.allclose(rho.diagonal(), 1, rtol=0, atol=1e-12)
                    or np.max(np.abs(rho)) > 1 + 1e-12 or np.linalg.eigvalsh(rho).min() < -1e-12):
                raise ValueError('symmetric positive-semidefinite correlation matrix with unit diagonal required')
        else:
            raise ValueError('supported declared correlation model required')
        errors = np.maximum(row['minus'], row['plus'])
        matrix = rho * np.outer(errors, errors)
        if not np.isfinite(matrix).all():
            raise ValueError('nonfinite theory covariance')
        matrices[kind] = matrix.tolist()
    total = np.zeros((n, n))
    for matrix in matrices.values():
        total += matrix
    if not np.isfinite(total).all():
        raise ValueError('nonfinite total theory covariance')
    return {'by_class': matrices, 'total': total.tolist(), 'correlation_model': deepcopy(model),
            'component_groups': {kind: row.get('components', [kind]) for kind, row in bands.items()},
            'symmetrization': 'max', 'class_correlation': 'independent',
            'law': 'declared-second-moment-proxy'}


def _checks(bundle):
    pdf = bundle['inputs']['pdf']
    declared_alpha = pdf.get('alpha_s_mz')
    source_alpha = pdf.get('info', {}).get('alpha_s_mz')
    alpha = source_alpha if source_alpha is not None else declared_alpha
    nominal = bundle['inputs']['alpha_s_mz']
    metadata_agrees = (declared_alpha is None or source_alpha is None
                       or math.isclose(_number(declared_alpha), source_alpha, rel_tol=0, abs_tol=1e-12))
    consistent = alpha is not None and metadata_agrees and math.isclose(_number(alpha), nominal, rel_tol=0, abs_tol=1e-12)
    return {'check:sm.alphas_consistent': {
        'status': 'passed' if consistent else 'unknown' if alpha is None else 'failed',
        'matrix_element_alpha_s_mz': nominal, 'pdf_alpha_s_mz': alpha},
        'check:sm.prescription_declared': {'status': 'passed'},
        'check:sm.np_once': {'status': 'passed' if not _members(bundle, 'np') or bundle.get('np_already_applied') is False else 'failed'}}


def assemble(bundle, *, correlation_model, pdf_result=None):
    """Return prediction_bundle.v1 with disclosed checks and completeness."""
    validate_bundle(bundle)
    result = deepcopy(bundle)
    result['band'] = band(bundle, pdf_result=pdf_result)
    result['theory_covariance'] = theory_covariance(bundle, correlation_model, pdf_result=pdf_result)
    result['checks'] = _checks(bundle)
    result['unclassified'] = result['band']['unclassified']
    result['complete'] = not result['unclassified'] and all(c['status'] == 'passed' for c in result['checks'].values())
    result['physics_validated'] = False
    validate_bundle(result)
    return result


def classify_weight(name, generator, *, header=None, nominal_pdf_lhaid=None):
    """Classify only a supported grammar or explicit retained MG header.

    Numeric ids carry no built-in physics meaning. Full source-bound headers are
    required for those ids; unknown grammar and mixed variations stay unclassified.
    """
    maps = {p.stem: p for p in (DATA / 'weight-names').glob('*.json')}
    if generator not in maps:
        raise ValueError('supplied supported generator name map required')
    mapping = json.loads(maps[generator].read_text())
    metadata = None
    if header is not None:
        attrs = header.get('attributes', {})
        if (generator not in ('mg5-lo', 'mg5-nlo') or attrs.get('id') != name
                or set(attrs) - {'id', 'MUR', 'MUF', 'PDF', 'DYN_SCALE', 'ALPSFACT'}):
            raise ValueError('retained generator weight-header contract differs')
        metadata = {k: v for k, v in attrs.items() if k != 'id'}
    else:
        for rule in mapping['rules']:
            match = re.fullmatch(rule['pattern'], name, re.I if rule.get('ignore_case') else 0)
            if match:
                metadata = dict(rule.get('metadata', {}), **{k: v for k, v in match.groupdict().items() if v is not None})
                break
    if metadata is None:
        return {'class': 'unclassified', 'classification_reason': 'absent from generator name map'}
    if 'class' in metadata:
        return metadata
    converted = {}
    for field, target in mapping['fields'].items():
        if field in metadata:
            try:
                converted[target] = _number(float(metadata[field]))
            except (ValueError, TypeError) as exc:
                raise ValueError('finite generator weight metadata required') from exc
    for field in ('pdf_member', 'pdf_lhaid', 'dyn_scale'):
        if field in converted:
            if not converted[field].is_integer():
                raise ValueError('integer PDF identifiers and dynamical-scale indices required')
            converted[field] = int(converted[field])
    if metadata.get('ALPSFACT') not in (None, '1', '1.0'):
        return {'class': 'unclassified', 'classification_reason': 'ALPSFACT needs a supplied alpha_s interpretation'}
    if 'mu_r' in converted and 'mu_f' in converted:
        if converted['mu_r'] <= 0 or converted['mu_f'] <= 0:
            raise ValueError('positive scale ratios required')
        varied_pdf = 'pdf_lhaid' in converted and converted['pdf_lhaid'] != nominal_pdf_lhaid
        varied_scale = (converted['mu_r'], converted['mu_f']) != (1, 1)
        if varied_pdf and (nominal_pdf_lhaid is None or varied_scale):
            return dict(converted, **{'class': 'unclassified', 'classification_reason': 'mixed or undeclared scale/PDF variation'})
        converted['class'] = 'pdf' if varied_pdf else 'scale'
    elif 'pdf_member' in converted:
        converted['class'] = 'pdf'
    elif 'pdf_lhaid' in converted:
        converted['class'] = 'pdf'
    elif 'alpha_s_mz' in converted:
        converted['class'] = 'alphas'
    else:
        return {'class': 'unclassified', 'classification_reason': 'metadata does not establish a theory variation'}
    return converted


def from_member_table(bundle, generator, streams, *, headers=()):
    """Attach every supplied stream, preserving unknown streams in the bundle."""
    result = deepcopy(validate_bundle(bundle))
    if result['members']:
        raise ValueError('fresh member table required')
    header_map = {h['id']: h for h in headers}
    if len(header_map) != len(headers):
        raise ValueError('unique retained weight headers required')
    result['members'] = []
    for stream in streams:
        header = header_map.get(stream['id'])
        classification = classify_weight(stream['id'], generator, header=header,
                                         nominal_pdf_lhaid=bundle['inputs']['pdf']['lhaid'])
        if any(k in stream and stream[k] != v for k, v in classification.items()):
            raise ValueError('supplied stream contradicts generator name map')
        result['members'].append(dict(stream, **classification, **({'weight_header': deepcopy(header)} if header is not None else {})))
    result['unclassified'] = [m['id'] for m in _members(result, 'unclassified')]
    result['complete'] = False  # Only assemble can establish checks and complete uncertainty coverage.
    result['weight_name_map'] = {'generator': generator, 'sha256': hashlib.sha256((DATA / f'weight-names/{generator}.json').read_bytes()).hexdigest()}
    validate_bundle(result)
    return result


def from_yoda(bundle, text, *, observable_path, generator, nominal_weight,
              quantity, factor=1, headers=(), nominal_pdf_member=None, member_metadata=None):
    """Read all suffix streams for one explicitly selected YODA 2 observable.

    The unsuffixed path is the explicitly selected nominal described by the
    retained naming protocol. HISTO1D stores integrated sumW; density conversion
    needs a declared bin-width division. ESTIMATE1D contains final values.
    """
    if quantity not in ('integral', 'density', 'estimate') or not nominal_weight:
        raise ValueError('explicit nominal weight and YODA quantity semantics required')
    factor = _number(factor)
    if factor <= 0:
        raise ValueError('positive common YODA normalization factor required')
    objects = yoda_text.parse(text)
    if observable_path not in objects:
        raise ValueError('explicit nominal YODA path missing')
    nominal = objects[observable_path]
    if nominal['kind'].split('_V')[0] not in ('HISTO1D', 'ESTIMATE1D'):
        raise ValueError('decoded one-dimensional YODA prediction required')
    bins = [{'lo': lo, 'hi': hi} for lo, hi in zip(nominal['edges'][:-1], nominal['edges'][1:])]
    def values(obj):
        if obj['edges'] != nominal['edges']:
            raise ValueError('all YODA members need identical binning')
        kind = obj['kind'].split('_V')[0]
        if (quantity == 'estimate' and kind != 'ESTIMATE1D') or (quantity != 'estimate' and kind != 'HISTO1D'):
            raise ValueError('YODA quantity does not match object type')
        vals = [_number(v) * factor for v in yoda_text.values(obj)]
        return [v / w for v, w in zip(vals, yoda_text.widths(obj))] if quantity == 'density' else vals
    result = deepcopy(bundle)
    result['central'] = values(nominal)
    result['binning'] = bins
    streams = []
    metadata = dict(member_metadata or {})
    for path, obj in objects.items():
        if path.startswith(observable_path + '['):
            if not path.endswith(']') or '[' in path[len(observable_path) + 1:-1] or not path[len(observable_path) + 1:-1]:
                raise ValueError('ambiguous YODA weight suffix')
            name = path[len(observable_path) + 1:-1]
            row_metadata = metadata.pop(name, {})
            if set(row_metadata) - {'pdf_member', 'pdf_alpha_s_mz', 'role', 'quantity'}:
                raise ValueError('only declared PDF member, coupling and correction metadata may supplement a stream')
            streams.append(dict(row_metadata, id=name, values=values(obj)))
    if metadata:
        raise ValueError('YODA member metadata names absent streams')
    if any(s['id'] == nominal_weight for s in streams):
        raise ValueError('nominal weight duplicated as a suffix stream')
    result = from_member_table(result, generator, streams, headers=headers)
    if nominal_pdf_member is not None:
        if type(nominal_pdf_member) is not int or nominal_pdf_member != 0:
            raise ValueError('explicit PDF nominal member zero required')
        result['members'].insert(0, {'id': nominal_weight, 'class': 'pdf', 'pdf_member': 0, 'values': result['central'][:]})
    result['source'] = {'format': 'yoda-text', 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                        'observable_path': observable_path, 'nominal_weight': nominal_weight,
                        'quantity': quantity, 'common_factor': factor}
    return result


def validate(task):
    if not isinstance(task, dict) or set(task) != {'input', 'output'}:
        raise ValueError('theory-uncertainty task requires supplied input and output contract')
    from ravel.physics.supplied_contracts import output_contract
    output_contract(task['output'])


def inputs(task, base):
    validate(task)
    path = pdf_variations._regular(task['input'], base)
    config = json.loads(path.read_text())
    _validate_config(config)
    files = [path]
    if 'yoda' in config:
        files.append(pdf_variations._pin(config['yoda']['input'], path.parent))
    if 'pdf_result' in config:
        files.append(pdf_variations._pin(config['pdf_result'], path.parent))
    return files


def _validate_config(config):
    if (not isinstance(config, dict) or not {'bundle', 'correlation_model'} <= set(config)
            or set(config) - {'bundle', 'correlation_model', 'pdf_result', 'member_table', 'yoda'}
            or 'member_table' in config and 'yoda' in config):
        raise ValueError('closed theory-uncertainty input with one supplied member source required')
    if 'member_table' in config:
        spec = config['member_table']
        if not {'generator', 'streams'} <= set(spec) or set(spec) - {'generator', 'streams', 'headers'}:
            raise ValueError('closed supplied member-table contract required')
    if 'yoda' in config:
        spec = config['yoda']
        if (not {'input', 'observable_path', 'generator', 'nominal_weight', 'quantity'} <= set(spec)
                or set(spec) - {'input', 'observable_path', 'generator', 'nominal_weight', 'quantity',
                                'factor', 'headers', 'nominal_pdf_member', 'member_metadata'}):
            raise ValueError('closed supplied YODA contract required')


def run(task, base, output):
    """Pure supplied-data adapter; a PDF result must be produced separately.

    The registration lane wires this into the existing science worker. No native
    runtime, transport registry, launch guard or orchestration code is changed.
    """
    files = inputs(task, base)
    before = {str(p): pdf_variations._hash(p) for p in files}
    config = json.loads(files[0].read_text())
    _validate_config(config)
    bundle = config['bundle']
    if 'member_table' in config:
        bundle = from_member_table(bundle, **config['member_table'])
    if 'yoda' in config:
        spec = dict(config['yoda'])
        source = pdf_variations._pin(spec.pop('input'), files[0].parent)
        text = gzip.decompress(source.read_bytes()).decode() if source.suffix == '.gz' else source.read_text()
        bundle = from_yoda(bundle, text, **spec)
    pdf_result = None
    if 'pdf_result' in config:
        pdf_result = json.loads(pdf_variations._pin(config['pdf_result'], files[0].parent).read_text())
    result = assemble(bundle, correlation_model=config['correlation_model'], pdf_result=pdf_result)
    if files != inputs(task, base) or before != {str(p): pdf_variations._hash(p) for p in files}:
        raise ValueError('supplied theory inputs changed during evaluation')
    from ravel.physics.supplied_contracts import publish
    path = publish(output, result, task['output'])
    return {'status': 'passed' if result['complete'] else 'incomplete',
            'physics_validated': False, 'output': path.name, 'checks': result['checks']}
