"""Lossless signal-strength limit transport, independent of inference libraries.

``limits`` is the authoritative versioned representation. Existing scalar aliases
remain for compatibility but must agree with it. A scan boundary is not a root.
Legacy scalars without numerical evidence are explicitly ``legacy_reported``;
they can be shown in historical comparisons, never promoted to certified roots.
New engines without convergence evidence use ``unverified`` instead.

This module validates numerical representation, not likelihood correctness,
coverage, detector acceptance, or the appropriateness of a scientific claim.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re


STATUSES = frozenset({'resolved', 'below_scan', 'above_scan', 'missing',
                      'unverified', 'legacy_reported'})
LEGACY_NOTE = 'Historical reported value; numerical crossing evidence was not recorded.'
NUMERICAL_METADATA = ('inference', 'fit_diagnostics', 'numerical_evidence', 'optimizer', 'model_scope',
                      'at_mu_floor', 'at_poi_cap', 'median_at_cap', 'band_degenerate')


def _number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f'{label} must be a finite nonnegative number (not bool)')
    return float(value)


def _same(a, b):
    return a is None and b is None or (a is not None and b is not None and
           type(a) in (int, float) and type(b) in (int, float) and
           math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12))


@dataclass(frozen=True)
class LimitCurve:
    value: float | None
    status: str
    bracket: tuple[float | None, float | None] | None = None

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f'unknown limit status {self.status!r}')
        if self.status == 'missing':
            if self.value is not None or self.bracket is not None:
                raise ValueError('missing limit must have null value and bracket')
            return
        _number(self.value, 'limit value')
        if self.value == 0 and self.status in ('resolved', 'legacy_reported'):
            raise ValueError('resolved/reported upper limits must be positive')
        if self.bracket is not None:
            if not isinstance(self.bracket, (tuple, list)) or len(self.bracket) != 2:
                raise ValueError('limit bracket must have exactly two endpoints')
            lo, hi = (None if v is None else _number(v, 'bracket endpoint') for v in self.bracket)
            valid = (self.status == 'resolved' and lo is not None and hi is not None and lo <= self.value <= hi
                     or self.status == 'below_scan' and lo is None and hi == self.value
                     or self.status == 'above_scan' and hi is None and lo == self.value)
            if not valid:
                raise ValueError('bracket must contain the root or encode the declared one-sided bound')

    def usable(self, *, allow_legacy=False):
        return self.status == 'resolved' or (allow_legacy and self.status == 'legacy_reported')

    def exclusion(self, threshold=1.0, *, allow_legacy=False):
        """Known one-sided bounds can prove only the appropriate direction.

        Returned False means *not excluded by this upper-limit test*, not allowed
        by all data or models. None means the limit does not decide the question.
        """
        threshold = _number(threshold, 'test threshold')
        if self.usable(allow_legacy=allow_legacy):
            return self.value < threshold
        if self.status == 'below_scan' and self.value <= threshold:
            return True  # root < lower scan endpoint <= tested signal
        if self.status == 'above_scan' and self.value >= threshold:
            return False  # root > upper scan endpoint >= tested signal
        return None

    def to_dict(self):
        return {'value': self.value, 'status': self.status,
                'bracket': list(self.bracket) if self.bracket is not None else None}


@dataclass(frozen=True)
class LimitResult:
    observed: LimitCurve
    expected: tuple[LimitCurve, ...]
    origin: str = 'declared'
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if len(self.expected) != 5:
            raise ValueError('expected limits require five ordered slots [-2,-1,median,+1,+2]')
        # Compare known roots; censored endpoints need not be mutually ordered.
        known = [c.value for c in self.expected if c.usable(allow_legacy=True)]
        if any(a > b for a, b in zip(known, known[1:])):
            raise ValueError('resolved/reported expected limits must be ordered')
        lower, open_lower = 0., False
        for c in self.expected:
            if c.status in ('resolved', 'legacy_reported'):
                lo = hi = c.value
                open_lo = open_hi = False
            elif c.status == 'below_scan':
                lo, hi, open_lo, open_hi = 0., c.value, False, True
            elif c.status == 'above_scan':
                lo, hi, open_lo, open_hi = c.value, math.inf, True, False
            else:
                continue
            if lower > hi or lower == hi and (open_lower or open_hi):
                raise ValueError('expected bounds contradict quantile ordering')
            if lo > lower:
                lower, open_lower = lo, open_lo
            elif lo == lower:
                open_lower |= open_lo
        if not isinstance(self.origin, str) or not self.origin:
            raise ValueError('limit origin must be a nonempty string')
        if any(not isinstance(n, str) for n in self.notes):
            raise ValueError('limit notes must be strings')

    def curve(self, kind='observed'):
        if kind == 'observed':
            return self.observed
        if kind == 'expected':
            return self.expected[2]
        if type(kind) is int and 0 <= kind < 5:
            return self.expected[kind]
        raise ValueError(f'unknown limit curve {kind!r}')

    def to_dict(self):
        return {'schema_version': 1, 'quantity': 'signal_strength',
                'observed': self.observed.to_dict(),
                'expected': [c.to_dict() for c in self.expected],
                'origin': self.origin, 'notes': list(self.notes)}

    def scaled(self, factor):
        factor = _number(factor, 'limit scale')
        if factor == 0:
            raise ValueError('limit scale must be positive')
        def scale(c):
            return LimitCurve(c.value * factor if c.value is not None else None, c.status,
                              tuple(v * factor if v is not None else None for v in c.bracket) if c.bracket else None)
        return LimitResult(scale(self.observed), tuple(scale(c) for c in self.expected),
                           self.origin, self.notes)


def _curve(doc):
    if not isinstance(doc, dict) or set(doc) != {'value', 'status', 'bracket'}:
        raise ValueError('typed curve requires exactly value, status, bracket')
    return LimitCurve(doc['value'], doc['status'],
                      tuple(doc['bracket']) if isinstance(doc['bracket'], list) else doc['bracket'])


def _aliases(doc):
    def alias(names):
        found = [doc[n] for n in names if n in doc]
        if found and any(not _same(found[0], v) for v in found[1:]):
            raise ValueError(f'conflicting scalar aliases {names}')
        return found[0] if found else None
    observed = alias(('obs_limit', 'mu95_obs'))
    bands = [doc[n] for n in ('exp_limits', 'mu95_exp_band') if n in doc and doc[n] is not None]
    for band in bands:
        if not isinstance(band, list) or len(band) != 5:
            raise ValueError('expected band must contain five values or null slots')
    if len(bands) == 2 and any(not _same(a, b) for a, b in zip(*bands)):
        raise ValueError('conflicting expected band aliases')
    median = alias(('mu95_exp', 'exp_median', 'mu95_expected'))
    band = list(bands[0]) if bands else [None] * 5
    if median is not None:
        if bands and not _same(band[2], median):
            raise ValueError('expected median disagrees with band')
        band[2] = median
    return observed, band


def read_limits(doc, *, source='legacy'):
    """Read and cross-check typed output or adapt an explicit legacy representation.

    Legacy quality flags never imply that unaffected curves were resolved. A
    global ambiguous floor/degenerate-band flag conservatively marks the affected
    legacy values unverified. Modern per-curve statuses identify the affected
    curves precisely; conflicting flags fail rather than override silently.
    """
    if not isinstance(doc, dict):
        raise ValueError('limit artifact must be an object')
    obs, band = _aliases(doc)
    typed = doc.get('limits')
    status = doc.get('limit_status')
    brackets = doc.get('limit_brackets')
    if typed is not None:
        required = {'schema_version', 'quantity', 'observed', 'expected', 'origin', 'notes'}
        if not isinstance(typed, dict) or set(typed) != required or type(typed['schema_version']) is not int \
                or typed['schema_version'] != 1 or typed['quantity'] != 'signal_strength':
            raise ValueError('unsupported or malformed typed limits schema')
        if not isinstance(typed['expected'], list) or not isinstance(typed['notes'], list):
            raise ValueError('typed expected limits and notes must be arrays')
        result = LimitResult(_curve(typed['observed']), tuple(_curve(c) for c in typed['expected']),
                             typed['origin'], tuple(typed['notes']))
        if any(n in doc for n in ('obs_limit', 'mu95_obs')) and not _same(obs, result.observed.value):
            raise ValueError('observed scalar conflicts with typed limit')
        if any(doc.get(n) is not None for n in ('exp_limits', 'mu95_exp_band')):
            if any(not _same(a, c.value) for a, c in zip(band, result.expected)):
                raise ValueError('expected scalar band conflicts with typed limits')
        for n in ('mu95_exp', 'exp_median', 'mu95_expected'):
            if n in doc and not _same(doc[n], result.expected[2].value):
                raise ValueError('expected scalar median conflicts with typed limit')
    else:
        if status is not None:
            if not isinstance(status, dict) or set(status) != {'observed', 'expected'} \
                    or not isinstance(status['expected'], list) or len(status['expected']) != 5:
                raise ValueError('limit_status requires observed and five expected statuses')
            statuses = [status['observed'], *status['expected']]
        else:
            fallback = 'legacy_reported' if source == 'legacy' else 'unverified'
            statuses = [fallback if v is not None else 'missing' for v in [obs, *band]]
            archive_floor = source == 'legacy' and obs == 1.0 and all(v == 1.0 for v in band)
            if doc.get('quality') or doc.get('at_mu_floor') or archive_floor:
                statuses = ['unverified' if v is not None else 'missing' for v in [obs, *band]]
            if doc.get('band_degenerate'):
                statuses[1:] = ['unverified' if v is not None else 'missing' for v in band]
            if doc.get('at_poi_cap') and obs is not None:
                statuses[0] = 'above_scan'
            if doc.get('median_at_cap') and band[2] is not None:
                statuses[3] = 'above_scan'
        bs = [None] * 6
        if brackets is not None:
            if not isinstance(brackets, dict) or set(brackets) != {'observed', 'expected'} \
                    or not isinstance(brackets['expected'], list) or len(brackets['expected']) != 5:
                raise ValueError('limit_brackets requires observed and five expected brackets')
            bs = [brackets['observed'], *brackets['expected']]
        curves = tuple(LimitCurve(v, s, tuple(b) if isinstance(b, list) else b)
                       for v, s, b in zip([obs, *band], statuses, bs))
        notes = (LEGACY_NOTE,) if 'legacy_reported' in statuses else ()
        if doc.get('quality'):
            notes += (f"Original quality flag: {doc['quality']}",)
        result = LimitResult(curves[0], curves[1:], 'declared' if status else source, notes)
    curves = [result.observed, *result.expected]
    if status is not None and status != {'observed': curves[0].status,
                                        'expected': [c.status for c in curves[1:]]}:
        raise ValueError('limit_status conflicts with typed limits')
    if brackets is not None and brackets != {'observed': curves[0].to_dict()['bracket'],
                                            'expected': [c.to_dict()['bracket'] for c in curves[1:]]}:
        raise ValueError('limit_brackets conflicts with typed limits')
    for flag in ('at_mu_floor', 'at_poi_cap', 'median_at_cap', 'band_degenerate'):
        if flag in doc and type(doc[flag]) is not bool:
            raise ValueError(f'{flag} must be Boolean')
    if status is not None or typed is not None:
        if 'at_poi_cap' in doc and doc['at_poi_cap'] != (curves[0].status == 'above_scan'):
            raise ValueError('observed cap flag conflicts with per-curve status')
        if 'median_at_cap' in doc and doc['median_at_cap'] != (curves[3].status == 'above_scan'):
            raise ValueError('median cap flag conflicts with per-curve status')
        if doc.get('at_mu_floor') and not any(c.status in ('below_scan', 'unverified') for c in curves):
            raise ValueError('floor flag conflicts with per-curve statuses')
        if doc.get('quality') and all(c.usable(allow_legacy=True) or c.status == 'missing' for c in curves):
            raise ValueError('quality flag conflicts with all-resolved/reported limits')
        if doc.get('quality') == 'capped' and not any(c.status in ('above_scan', 'unverified') for c in curves):
            raise ValueError('capped quality flag conflicts with per-curve statuses')
        if doc.get('quality') in ('floored', 'floored-legacy') and not any(c.status in ('below_scan', 'unverified') for c in curves):
            raise ValueError('floored quality flag conflicts with per-curve statuses')
    return result


def attach_limits(doc, *, result=None, source='legacy'):
    """Attach canonical representation and aliases; preserve unrelated diagnostics."""
    result = result or read_limits(doc, source=source)
    doc['limits'] = result.to_dict()
    doc['limit_status'] = {'observed': result.observed.status,
                           'expected': [c.status for c in result.expected]}
    doc['limit_brackets'] = {'observed': result.observed.to_dict()['bracket'],
                             'expected': [c.to_dict()['bracket'] for c in result.expected]}
    doc['limit_eligibility'] = {
        'observed_root': result.observed.usable(),
        'expected_roots': [c.usable() for c in result.expected],
        'historical_only': any(c.status == 'legacy_reported' for c in [result.observed, *result.expected]),
    }
    return doc


def point_value(doc, kind='observed', *, allow_legacy=False):
    c = read_limits(doc).curve(kind)
    return c.value if c.usable(allow_legacy=allow_legacy) else None


def rescale_artifact(doc, factor):
    """Scale mu values and root brackets once, updating every present alias."""
    result = read_limits(doc).scaled(factor)
    for k in ('obs_limit', 'mu95_obs'):
        if k in doc:
            doc[k] = result.observed.value
    for k in ('exp_limits', 'mu95_exp_band'):
        if k in doc:
            doc[k] = [c.value for c in result.expected]
    for k in ('exp_median', 'mu95_exp', 'mu95_expected'):
        if k in doc:
            doc[k] = result.expected[2].value
    if 'excluded_obs' in doc:
        doc['excluded_obs'] = result.observed.exclusion()
    attach_limits(doc, result=result)
    return doc


def claim_errors(doc, *, allow_legacy=False):
    """Check asserted eligibility/verdict, never trusting cached Boolean metadata."""
    try:
        result = read_limits(doc)
    except (ValueError, TypeError) as e:
        return [str(e)]
    errors = []
    if doc.get('excluded_obs') is not None:
        verdict = result.observed.exclusion(allow_legacy=allow_legacy)
        if type(doc['excluded_obs']) is not bool or verdict is None or doc['excluded_obs'] != verdict:
            errors.append('excluded_obs is unsupported by the observed limit status/value')
    if 'limit_eligibility' in doc:
        canonical = {}
        attach_limits(canonical, result=result)
        if doc['limit_eligibility'] != canonical['limit_eligibility']:
            errors.append('limit_eligibility conflicts with recomputed per-curve eligibility')
    return errors


def prose_errors(text, doc):
    """Targeted check of explicit mu95 obs/exp assertions, not a semantic LLM judge."""
    result = read_limits(doc)
    errors = []
    pattern = re.compile(r'\b(?:mu|µ)\s*95[_\s-]*(obs|exp)(?:ected|erved)?\s*([=<>]|is)\s*([0-9.eE+-]+)', re.I)
    for m in pattern.finditer(text):
        curve = result.curve('observed' if m[1].lower() == 'obs' else 'expected')
        if curve.usable():
            continue
        line = text[text.rfind('\n', 0, m.start()) + 1:text.find('\n', m.end()) if '\n' in text[m.end():] else len(text)]
        qualifier = re.search(r'\b(bound|ceiling|floor|censored|unresolved|unverified|legacy|historical)\b', line, re.I)
        correct_inequality = (m[2] == '<' and curve.status == 'below_scan' or
                              m[2] == '>' and curve.status == 'above_scan')
        if not qualifier and not correct_inequality:
            errors.append(f'prose presents {m[0]} as a root despite status={curve.status}')
    return errors


def _source_path(rundir, relative):
    """Scientific sources use exact local paths, never basename fallback or attempt archives."""
    root = Path(rundir).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('limit source must be an exact run-relative path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.is_relative_to(root / 'logs'):
        raise ValueError('limit source cannot escape the run or name historical logs')
    if path.name in ('result.json', 'scan.json', 'current_state.json', 'execution_state.json'):
        raise ValueError('limit pack source must be a primary inference artifact, not another headline/view')
    if not path.is_file():
        raise ValueError(f'limit source is missing: {relative}')
    return path


def bind_source(doc, rundir, relative):
    """Bind an identity transport to current primary inference bytes.

    This deliberately has no user-declared multiplicative-transform escape hatch.
    Scientific renormalization needs its own verified source/parameter operation.
    """
    path = _source_path(rundir, relative)
    doc['limit_source'] = {'schema_version': 1, 'path': path.relative_to(Path(rundir).resolve()).as_posix(),
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'operation': 'identity'}
    errors = source_errors(doc, rundir, required=True)
    if errors:
        raise ValueError('; '.join(errors))
    return doc


def source_errors(doc, rundir, *, required=False, expected_path=None):
    """Verify a pack's mathematical claims against its actual primary artifact.

    ``expected_path`` is the gate's independently selected/certified statistics
    artifact. Matching a pack's self-selected pointer alone cannot transfer a
    certificate from a different exclusion file.
    """
    try:
        binding = doc.get('limit_source')
        pointer = (doc.get('pointers') or {}).get('exclusion')
        if binding is None:
            if required:
                return ['current result pack lacks a bound primary limit source']
            if pointer is None:
                return []  # original unbound historical record, never a fresh certification
            relative = pointer
        else:
            if not isinstance(binding, dict) or set(binding) != {'schema_version', 'path', 'sha256', 'operation'} \
                    or type(binding['schema_version']) is not int or binding['schema_version'] != 1 \
                    or binding['operation'] != 'identity' \
                    or not isinstance(binding['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', binding['sha256']):
                raise ValueError('malformed or unsupported limit source binding')
            relative = binding['path']
            if pointer is not None and pointer != relative:
                raise ValueError('exclusion pointer conflicts with bound primary limit source')
        path = _source_path(rundir, relative)
        if expected_path is not None:
            expected = Path(expected_path)
            if not expected.is_absolute():
                expected = Path(rundir) / expected
            if path != expected.resolve():
                raise ValueError('pack primary limit source differs from the current certified statistics artifact')
        payload = path.read_bytes()
        if binding is not None and hashlib.sha256(payload).hexdigest() != binding['sha256']:
            raise ValueError('primary limit source bytes changed after packing')
        source = json.loads(payload)
        actual, original = read_limits(doc), read_limits(source)
        if ([actual.observed.to_dict(), *[c.to_dict() for c in actual.expected]] !=
                [original.observed.to_dict(), *[c.to_dict() for c in original.expected]]):
            raise ValueError('pack limits/statuses/brackets differ from the bound primary inference artifact')
        for key in ('m_parent', 'm_lsp', 'routine', 'analysis_id', 'model', 'lumi_fb',
                    'sigma_lo_pb', 'sigma_scale_k', 'sigma_ref_fb', *NUMERICAL_METADATA):
            if key in source and key in doc and doc[key] != source[key]:
                raise ValueError(f'pack {key} differs from the bound primary inference artifact')
        from ravel.workflow.result_pack import headline_errors
        errors = headline_errors(doc, source, rundir)
        if errors:
            return errors
        return []
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        return [str(exc)]
