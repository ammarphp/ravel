"""Pure scalar-fit metadata checks and fail-closed operation-check delegation.

These checks inspect supplied declarations. They neither qualify predictions nor
infer missing uncertainties. Operation owners provide their full checks through
explicit module/function interfaces; unavailable implementations are inconclusive.
"""
from __future__ import annotations

from copy import deepcopy
from functools import partial
from importlib import import_module
import math

CHECKS = ('higgs.framework_declared', 'higgs.measurement_bundle',
          'higgs.parameterization_closure', 'higgs.scalar_basis',
          'higgs.theory_constraints', 'higgs.cross_engine', 'higgs.theory_correlation',
          'higgs.trap_TH1', 'higgs.trap_TH2', 'higgs.trap_TH3', 'higgs.trap_TH4',
          'higgs.trap_TH5', 'higgs.trap_TH6', 'higgs.trap_TH7', 'higgs.trap_TH8',
          'higgs.trap_TH9', 'higgs.trap_TH10', 'higgs.trap_TH11', 'higgs.trap_TH12')
DELEGATES = {
    'check:higgs.measurement_bundle': ('ravel.physics.higgs_measurements', 'check_measurement_bundle'),
    'check:higgs.parameterization_closure': ('ravel.physics.higgs_parameterization', 'check_parameterization_closure'),
    'check:higgs.scalar_basis': ('ravel.physics.extended_scalar', 'check_scalar_basis'),
    'check:higgs.theory_constraints': ('ravel.physics.extended_scalar', 'check_theory_constraints'),
    'check:higgs.cross_engine': ('ravel.physics.higgs_likelihood', 'check_cross_engine'),
}


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite supplied number required')
    return value


def _text(value):
    if type(value) is not str or not value.strip():
        raise ValueError('nonempty supplied text required')
    return value


def _strings(values):
    if type(values) is not list or len(set(_text(v) for v in values)) != len(values):
        raise ValueError('unique supplied text list required')
    return values


def _choice(value, allowed):
    # An undeclared label is missing evidence, never a pass.
    if _text(value) not in allowed:
        raise ValueError('declared label must be one of: ' + ', '.join(allowed))
    return value


def _count(value, minimum):
    if type(value) is not int or value < minimum:
        raise ValueError('supplied integer count required')
    return value


def _report(check_id, status, detail, trap_id=None):
    from ravel.workflow.review_projection_checks import result, _finding
    findings = []
    if status == 'failed':
        findings = [_finding(check_id.removeprefix('check:'), trap_id or 'higgs-declaration', detail, materiality='A',
                            location='supplied-document')]
    return result(check_id, findings, status=status, diagnostics={'detail': detail})


def _matrix(matrix, n):
    if type(matrix) is not list or len(matrix) != n or any(type(r) is not list or len(r) != n for r in matrix):
        raise ValueError('square supplied covariance or correlation required')
    for i in range(n):
        for j in range(n):
            _number(matrix[i][j])
            if not math.isclose(matrix[i][j], matrix[j][i], rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError('symmetric matrix required')
    # The complete toolchain includes NumPy. No native scientific program runs here.
    import numpy as np
    if float(np.linalg.eigvalsh(matrix).min()) < -1e-10:
        raise ValueError('positive semidefinite matrix required')
    return matrix


def _trap_conflict(trap_id, doc):
    if trap_id == 'TH1':
        measurements, joint = doc['measurements'], doc['joint_likelihoods']
        if type(measurements) is not list or not measurements or type(joint) is not list:
            raise ValueError('measurement population and overlap declarations required')
        for row in measurements:
            for key in ('id', 'event_set', 'representation'):
                _text(row[key])
        _strings([row['id'] for row in measurements])
        # Measurements built from the same events are correlated whatever their representation.
        for i, left in enumerate(measurements):
            for right in measurements[i+1:]:
                if left['event_set'] == right['event_set']:
                    linked = any({p['left'], p['right']} == {left['id'], right['id']} and _text(p['source']) for p in joint)
                    if not linked:
                        return True
        return False
    if trap_id == 'TH2':
        experiments = _strings(doc['experiments'])
        components = doc['theory_components']
        if not experiments or type(components) is not list or not components:
            raise ValueError('experiments and signal theory components required')
        for row in components:
            _text(row['process']); _text(row['source']); _text(row['id'])
            names = _strings(row['experiments']); definitions = row['definitions']
            if not names or not set(names) <= set(experiments) or type(definitions) is not list or len(definitions) != len(names):
                raise ValueError('one theory definition per experiment required')
            for definition in definitions:
                _text(definition)
            matrix = _matrix(row['correlation'], len(names))
            if any(matrix[i][i] != 1 for i in range(len(names))) or any(abs(v) > 1 for r in matrix for v in r):
                raise ValueError('unit-diagonal bounded correlation required')
            if len(set(definitions)) > 1:
                return True
            origins = _strings(row['origins'])
            if not origins:
                raise ValueError('uncertainty origins required')
            if {'table', 'program'} <= set(origins):
                return True
            # One physical source is fully correlated; any decorrelation needs located evidence.
            if any(matrix[i][j] < 1 for i in range(len(names)) for j in range(i)) and not row['decorrelation_evidence']:
                return True
        # Splitting one physical source into experiment-specific rows cannot evade correlation review.
        for i, left in enumerate(components):
            for right in components[i+1:]:
                if (left['source'], left['process']) == (right['source'], right['process']):
                    return True
        return False
    if trap_id == 'TH3':
        predicted, measured = _number(doc['prediction_mass_gev']), _number(doc['measurement_mass_gev'])
        if predicted == measured:
            return False
        shift = doc['mass_translation']
        return not (type(shift) is dict and _number(shift['from']) == predicted and _number(shift['to']) == measured and _text(shift['source']))
    if trap_id == 'TH4':
        a, b = doc['prediction_loop_mode'], doc['measurement_loop_mode']
        if type(a) is not dict or type(b) is not dict or not a or set(a) != set(b):
            raise ValueError('matched loop-channel declarations required')
        if any(v not in ('resolved', 'effective') for v in [*a.values(), *b.values()]):
            raise ValueError('resolved or effective loop mode required')
        return a != b
    if trap_id == 'TH5':
        p = doc['parameterization']; free = {name.lower() for name in _strings(p['free'])}
        if not (free & {'br_bsm', 'br_undet'} and free & {'kappa_v', 'kappa_w', 'kappa_z'}):
            return False
        if p['width_constraint']:
            _text(p['width_constraint']); return False
        bound = p['kappa_v_upper_bound']
        return bound is None or _number(bound) > 1
    if trap_id == 'TH6':
        p = doc['likelihood']; down, up = _number(p['errors']['down']), _number(p['errors']['up'])
        distance = _number(p['distance_to_boundary'])
        if min(down, up) <= 0 or distance < 0:
            raise ValueError('positive errors and nonnegative boundary distance required')
        approximation = _choice(p['approximation'], ('symmetric-gaussian', 'asymmetric', 'full-likelihood'))
        return approximation == 'symmetric-gaussian' and down != up and distance <= max(down, up)
    if trap_id == 'TH7':
        p = doc['scalar_conventions']
        if p['source_cos_ba_sign'] not in (-1, 1) or p['target_cos_ba_sign'] not in (-1, 1):
            raise ValueError('explicit cosine signs required')
        available, retained = _strings(p['available_branches']), _strings(p['retained_branches'])
        if not available or not retained or not set(retained) <= set(available):
            raise ValueError('supplied and retained Yukawa branches required')
        missing = set(available) - set(retained)
        return bool(missing and not p['branch_restriction_evidence'])
    if trap_id == 'TH8':
        p = doc['basis']; source, target = _text(p['tan_beta_basis']), _text(p['prediction_basis'])
        if source == target:
            return False
        transport = p['transport']
        return not (type(transport) is dict and transport['from'] == source and transport['to'] == target and _text(transport['source']))
    if trap_id == 'TH9':
        p = doc['exclusion']; ratio = _number(p['ratio'])
        method = _choice(p['method'], ('expected-channel-selection', 'combined-likelihood'))
        interpretation = _choice(p['interpretation'], ('selected-channel-95cl', 'combined-95cl'))
        if ratio < 0:
            raise ValueError('nonnegative exclusion ratio required')
        return method == 'expected-channel-selection' and ratio > 1 and interpretation == 'combined-95cl'
    if trap_id == 'TH10':
        p = doc['gof']; purpose = _text(p['purpose']); statistic = _text(p['statistic'])
        dof = _count(p['dof'], 1)
        if not 0 <= _number(p['p_value']) <= 1:
            raise ValueError('bounded p-value required')
        if purpose == 'confidence-region' and statistic == 'delta_chi2':
            # The dimension is the number of jointly estimated parameters; profiled ones do not count.
            return dof != _count(p['parameters_of_interest'], 1)
        if purpose == 'goodness-of-fit':
            residual = _count(p['observables'], 1) - _count(p['fitted_parameters'], 0)
            if residual < 1:
                raise ValueError('positive residual dimension required')
            return dof != residual
        raise ValueError('declared statistic purpose and applicable dimension required')
    if trap_id == 'TH11':
        p = doc['dataset_release']; used, required = _text(p['used']), _text(p['required'])
        _text(p['required_source']); claim = _choice(p['claim'], ('current', 'historical'))
        return used != required and claim == 'current'
    if trap_id == 'TH12':
        p = doc['averaging']; values = p['values']
        if type(values) is not list or len(values) < 2:
            raise ValueError('multiple supplied measurements required')
        matrix = _matrix(p['covariance'], len(values)); threshold = _number(p['tension_threshold'])
        if threshold <= 0:
            raise ValueError('positive supplied tension threshold required')
        for i, row in enumerate(values):
            _number(row['value']); error = _number(row['uncertainty'])
            if error <= 0 or not math.isclose(matrix[i][i], error ** 2, rel_tol=1e-8):
                raise ValueError('covariance diagonal must match supplied uncertainties')
        tension = False
        for i, a in enumerate(values):
            for j, b in enumerate(values[:i]):
                variance = matrix[i][i] + matrix[j][j] - 2 * matrix[i][j]
                difference = abs(a['value'] - b['value'])
                if difference > threshold * math.sqrt(max(0., variance)):
                    tension = True
        return tension and not p['tension_statement']
    raise ValueError('unresolved trap: ' + trap_id)


def check_trap(trap_id, doc, *, check_id=None):
    """Report a conflict, a clean supplied declaration, or missing/invalid evidence."""
    identity = check_id or 'check:higgs.trap_' + trap_id
    try:
        conflict = _trap_conflict(trap_id, doc)
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return _report(identity, 'inconclusive', str(exc))
    return _report(identity, 'failed' if conflict else 'passed',
                   'Supplied declaration conflicts with ' + trap_id if conflict else 'Supplied declaration passes ' + trap_id, trap_id)


def _delegate(identity, doc):
    module, function = DELEGATES[identity]
    try:
        implementation = getattr(import_module(module), function)
        report = implementation(deepcopy(doc))
        if not isinstance(report, dict) or report.get('status') not in {'passed', 'failed', 'inconclusive'}:
            raise ValueError('operation check must return a typed status record')
        if report['status'] == 'passed' and any(f.get('materiality') in {'A', 'B'} for f in report.get('findings', [])):
            raise ValueError('operation check cannot pass material findings')
    except (ImportError, AttributeError, ValueError, TypeError, KeyError) as exc:
        return _report(identity, 'inconclusive', f'awaits operation implementation: {module}.{function}: {exc}')
    from ravel.workflow.review_projection_checks import result
    return result(identity, report.get('findings', []), status=report['status'],
                  outcome=report.get('outcome'), diagnostics={'operation_check': report})


def run_check(doc, *, check_id):
    """Run only a declared, pure check ID; never load a module supplied by a caller."""
    identity = check_id if check_id.startswith('check:') else 'check:' + check_id
    if identity[6:] not in CHECKS:
        raise ValueError('unresolved Higgs check: ' + identity)
    if identity.startswith('check:higgs.trap_'):
        return check_trap(identity.split('trap_', 1)[1], doc, check_id=identity)
    if identity == 'check:higgs.theory_correlation':
        return check_trap('TH2', doc, check_id=identity)
    if identity == 'check:higgs.framework_declared':
        try:
            framework = doc['framework']
            for key in ('name', 'basis', 'truncation', 'width_policy', 'source'):
                _text(framework[key])
        except (KeyError, TypeError, ValueError) as exc:
            return _report(identity, 'inconclusive', str(exc))
        return _report(identity, 'passed', 'Framework and applicability declarations supplied; no physics qualification implied.')
    return _delegate(identity, doc)


def resolve(identity):
    """Resolve a card alias to an explicit document-check adapter."""
    normalized = identity.removeprefix('check:')
    if normalized not in CHECKS:
        raise ValueError('unresolved Higgs check: ' + identity)
    return partial(run_check, check_id='check:' + normalized)


def card_errors(card):
    """Refuse unresolved aliases and reviewer reads conflicting with blindness."""
    errors = []
    for identity in card['must_check']:
        if identity.startswith('check:higgs.'):
            try:
                resolve(identity)
            except ValueError as exc:
                errors.append(str(exc))
    if card['independence']['kind'] in ('voting', 'specialist'):
        reads = card['knowledge']['must_read'] + card['knowledge']['derive']
        if any(r.split(':', 1)[0] == 'producer_headline' for r in reads):
            errors.append('reviewer cannot read producer_headline')
    return errors


def extend_checks(checks):
    """Compose broker document-check aliases while preserving original adapters."""
    added = {('check:' + identity): partial(run_check, check_id='check:' + identity) for identity in CHECKS}
    if checks.keys() & added.keys():
        raise ValueError('Higgs check identity collision')
    return {**checks, **added}


def compose_document_checks(checks, read_allowlist):
    """One broker seam joins pure adapters and their registered allowlist rows."""
    from ravel.paths import package_data_path
    from ravel.workflow.higgs_registration import compose
    checks.update(extend_checks({}))

    def registered_allowlist():
        return compose(read_allowlist(), package_data_path('validators/allowlist.json'))

    return registered_allowlist
