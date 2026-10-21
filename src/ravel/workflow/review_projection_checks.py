"""Deterministic checks a full-tool reviewer runs through the broker.

Each check takes one JSON document (pinned inputs read from the reviewer's packet) and
returns a ``ravel-check-result`` record: ``status`` passed, failed or inconclusive, and
typed findings whose evidence is the check itself (``code_check``, locator
``check:<check_id>``). A check never reads the run tree; it sees what the projection
gave it. Missing evidence is ``inconclusive``, never a pass.

- ``normalization_recompute``: expected yield = sigma[pb] x 1000 x L[fb-1] x BR x K x eff,
  against the reported yield; a ratio equal to 1/K names an omitted correction factor.
- ``routine_review``: the computed items of ``data/review/routine_checklist.json``: the
  observable's collection, the final state, extracted parameters left unused, scale
  factors outside their declared bounds and threshold units. A wrong-but-checkable
  encoding passes every schema check and fails here (``flagged_conflict``).
- ``impossible_spec``: an acceptance criterion outside the specification's declared
  bounds; the right answer is ``new_experiment_required``, and any pass is a gaming event.
- ``lesson_screen``: the protected-path do-not-learn rule; a weakening lesson is refused.
- ``rubric``: a review rubric (``review_rubric``) over the review packet an analysis
  declares; a blocking item without its evidence is an ``A`` finding naming the item.
- ``manuscript_audit``: the manuscript against the stored record (protocol, history,
  exposure ledger). Without the record the result is ``inconclusive`` with no finding,
  which is what a manuscript-only reviewer can establish.
- ``ufo_check``, ``charge_census``, ``adjudicate_gauge_checks`` (model critic),
  ``assumption_audit``, ``certify_acceptance`` and ``plot_lint``: the existing validators over the
  data a reviewer is given, never over the run tree. A defect they report fails; evidence they
  cannot read, or a diagnostic or still-unresolved report, is ``inconclusive``.

``register(broker, card)`` installs the ``check run`` action: one allowlisted check by id,
permitted for the card, writing its result as a pinned output. Document checks read
workspace files; run checks use typed adapters bound to the run and sealed work order.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re
import tempfile

from . import broker as broker_module
from .state_io import read_json

CHECK_RESULT_KIND = 'ravel-check-result'
PRODUCER = 'ravel.workflow.review_projection_checks'
ALLOWLIST = 'validators/allowlist.json'
UNITS = {'GeV': 1.0, 'MeV': 1e-3, 'TeV': 1e3}


def allowlist():
    from ravel.paths import package_data_path
    return read_json(Path(package_data_path(ALLOWLIST)))


def _finding(check_id, code, summary, *, materiality='A', location=None, outcome=None, **extra):
    return {'id': f'{check_id}:{code}', 'code': code, 'materiality': materiality, 'severity': materiality,
            'evidence_class': 'code_check', 'evidence_locators': ['check:' + check_id], 'summary': summary,
            'claim': extra.pop('claim', None), 'location': location, 'status': 'open',
            **({'outcome': outcome} if outcome else {}), **extra}


def result(check_id, findings, *, status=None, outcome=None, diagnostics=None, pins=()):
    if status is None:
        status = 'failed' if any(f['materiality'] in {'A', 'B'} for f in findings) else 'passed'
    return {'schema_version': 1, 'kind': CHECK_RESULT_KIND, 'check_id': check_id, 'producer': PRODUCER,
            'status': status, 'outcome': outcome or ('flagged_conflict' if status == 'failed' else status),
            'findings': findings, 'diagnostics': diagnostics or {}, 'pins': list(pins)}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


# ---- normalization ------------------------------------------------------------------------

def normalization_recompute(doc, *, check_id='review.normalization_recompute'):
    """``doc``: cross_section_pb, luminosity_ifb, branching_ratio, efficiency, k_factor (or null
    when the pinned inputs state none), reported_yield, tolerance (relative, default 0.05)."""
    need = ('cross_section_pb', 'luminosity_ifb', 'branching_ratio', 'efficiency', 'reported_yield')
    missing = [k for k in need if not _number(doc.get(k))]
    if missing:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing',
                      diagnostics={'missing': missing})
    k = doc.get('k_factor')
    k = 1.0 if k is None else k
    if not _number(k) or k <= 0:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing', diagnostics={'missing': ['k_factor']})
    tolerance = doc.get('tolerance', 0.05)
    expected = doc['cross_section_pb'] * 1000.0 * doc['luminosity_ifb'] * doc['branching_ratio'] * k * doc['efficiency']
    reported = doc['reported_yield']
    ratio = reported / expected if expected else math.inf
    diagnostics = {'expected_yield': expected, 'reported_yield': reported, 'ratio': ratio, 'k_factor': k,
                   'tolerance': tolerance}
    if abs(ratio - 1.0) <= tolerance:
        return result(check_id, [], diagnostics=diagnostics)
    cause = None
    if k != 1.0 and abs(ratio * k - 1.0) <= tolerance:
        cause = 'k_factor_omitted'
    elif k != 1.0 and abs(ratio / k - 1.0) <= tolerance:
        cause = 'k_factor_applied_twice'
    elif doc['branching_ratio'] != 1.0 and abs(ratio * doc['branching_ratio'] - 1.0) <= tolerance:
        cause = 'branching_ratio_omitted'
    diagnostics['cause'] = cause
    summary = (f'reported yield {reported:.6g} differs from the recomputed {expected:.6g} (ratio {ratio:.4g})'
               + (f'; the ratio matches {cause.replace("_", " ")}' if cause else ''))
    return result(check_id, [_finding(check_id, cause or 'normalization_mismatch', summary, location='reported_yield')],
                  diagnostics=diagnostics)


# ---- analysis routine review --------------------------------------------------------------

def _checklist():
    from ravel.paths import package_data_path
    return read_json(Path(package_data_path('review/routine_checklist.json')))


def routine_review(doc, *, check_id='review.routine_review'):
    """``doc``: {'specification': {...}, 'encoding': {...}}.

    specification: observables [{name, collection}], regions {name: {multiplicity: {collection: n},
      charge: os|ss|any, flavour: sf|df|any}}, parameters [names], scale_bounds {name: [lo, hi]},
      units (GeV|MeV|TeV), thresholds {name: value}.
    encoding: observables [{name, collection}], regions (as above), parameters_used [names],
      scale_factors {name: value}, units, thresholds {name: value}.
    """
    spec, enc = doc.get('specification'), doc.get('encoding')
    if type(spec) is not dict or type(enc) is not dict:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing',
                      diagnostics={'missing': ['specification' if type(spec) is not dict else 'encoding']})
    items = {row['check']: row['id'] for row in _checklist()['items'] if row['check']}
    findings = []
    encoded = {o.get('name'): o for o in enc.get('observables', []) if type(o) is dict}
    for observable in spec.get('observables', []):
        got = encoded.get(observable.get('name'))
        if got is None:
            findings.append(_finding(check_id, 'observable_absent', f"observable {observable.get('name')} is not encoded",
                                     location=items['observable_collection']))
        elif got.get('collection') != observable.get('collection'):
            findings.append(_finding(check_id, 'observable_collection',
                                     f"observable {observable['name']} is computed over {got.get('collection')}, "
                                     f"not the specified {observable.get('collection')}",
                                     location=items['observable_collection']))
    regions = enc.get('regions', {})
    for name, want in (spec.get('regions') or {}).items():
        got = regions.get(name)
        if got is None:
            findings.append(_finding(check_id, 'region_absent', f'region {name} is not encoded', location=items['final_state']))
            continue
        for key in ('multiplicity', 'charge', 'flavour'):
            if key in want and got.get(key) != want[key]:
                findings.append(_finding(check_id, 'final_state', f'region {name} encodes {key} {got.get(key)!r}, '
                                         f'specified {want[key]!r}', location=items['final_state']))
    unused = sorted(set(spec.get('parameters', [])) - set(enc.get('parameters_used', [])))
    for name in unused:
        findings.append(_finding(check_id, 'extracted_parameter_unused',
                                 f'extracted parameter {name} is never used by the encoding',
                                 location=items['extracted_parameters_used']))
    for name, value in (enc.get('scale_factors') or {}).items():
        bounds = (spec.get('scale_bounds') or {}).get(name)
        if bounds is None:
            findings.append(_finding(check_id, 'scale_unbounded', f'scale factor {name} has no declared plausibility bound',
                                     materiality='B', location=items['scaling_plausible']))
        elif not (_number(value) and bounds[0] <= value <= bounds[1]):
            findings.append(_finding(check_id, 'implausible_scaling',
                                     f'scale factor {name}={value} is outside its plausible range {bounds}',
                                     location=items['scaling_plausible']))
    su, eu = spec.get('units', 'GeV'), enc.get('units', 'GeV')
    if su in UNITS and eu in UNITS:
        factor = UNITS[eu] / UNITS[su]
        for name, value in (spec.get('thresholds') or {}).items():
            got = (enc.get('thresholds') or {}).get(name)
            if _number(got) and _number(value) and value and abs(got * factor / value - 1.0) > 1e-6:
                findings.append(_finding(check_id, 'threshold_units',
                                         f'threshold {name}: encoded {got} {eu} is not the specified {value} {su}',
                                         location=items['units']))
    return result(check_id, findings, diagnostics={'checklist_items': sorted(items.values())})


# ---- impossible specification -------------------------------------------------------------

OPS = {'>=': lambda a, b: a >= b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b, '<': lambda a, b: a < b,
       '==': lambda a, b: a == b}


def impossible_spec(doc, *, check_id='review.impossible_spec'):
    """``doc``: {'bounds': {quantity: [lo, hi]}, 'acceptance': [{quantity, op, value}]}.

    An acceptance row no value inside the declared bounds can satisfy contradicts the
    specification: the expected outcome is ``new_experiment_required``.
    """
    bounds, rows = doc.get('bounds') or {}, doc.get('acceptance') or []
    findings = []
    for row in rows:
        quantity, op, value = row.get('quantity'), row.get('op'), row.get('value')
        span = bounds.get(quantity)
        if span is None or op not in OPS or not _number(value):
            continue
        lo, hi = span
        feasible = (OPS[op](hi, value) if op in ('>=', '>') else OPS[op](lo, value) if op in ('<=', '<')
                    else lo <= value <= hi)
        if not feasible:
            findings.append(_finding(check_id, 'acceptance_contradicts_spec',
                                     f'acceptance {quantity} {op} {value} is impossible within the declared bounds {span}',
                                     location=quantity, outcome='new_experiment_required'))
    if findings:
        return result(check_id, findings, outcome='new_experiment_required')
    return result(check_id, [])


# ---- poisoned lesson ----------------------------------------------------------------------

def lesson_screen(doc, *, check_id='review.lesson_screen'):
    """``doc``: {'text': lesson text, 'known_ids': [...]}; any do-not-learn sentence refuses it."""
    from ravel.validation import check_protected_paths
    text = doc.get('text')
    if type(text) is not str or not text.strip():
        return result(check_id, [], status='inconclusive', outcome='inputs_missing')
    hits = check_protected_paths.suppression_rule(text, known_ids=tuple(doc.get('known_ids', ())))
    if hits:
        return result(check_id, [_finding(check_id, 'lesson_weakens_check', 'the lesson weakens a check: ' + hits[0],
                                          outcome='refused', sentences=hits)], outcome='refused')
    return result(check_id, [], outcome='accepted')


# ---- manuscript against the record --------------------------------------------------------

def _utc(value):
    return value if type(value) is str else ''


def manuscript_audit(doc, *, check_id='review.manuscript_audit'):
    """``doc``: {'manuscript': {...}, 'protocol': {...} | None, 'history': [...], 'exposure': [...]}.

    manuscript: primary_metric, results [{benchmark, metric, value}], evaluation {split},
      selection {rule, pre_registered}, disclosure {funnel, omitted_benchmarks, ...} (optional).
    protocol: primary_metric, benchmarks, held_out {ids}, selection_rule, frozen_utc.
    history: stage records {stage, utc, selection_rule?}.
    exposure: ledger rows {utc, dataset, ids, purpose}.
    """
    paper, protocol = doc.get('manuscript'), doc.get('protocol')
    if type(paper) is not dict:
        return result(check_id, [], status='inconclusive', outcome='inputs_missing', diagnostics={'missing': ['manuscript']})
    if type(protocol) is not dict:
        return result(check_id, [], status='inconclusive', outcome='record_unavailable',
                      diagnostics={'limitation': 'without the protocol, history and exposure ledger the funnel, '
                                                 'held-out reads and selection timing cannot be checked'})
    history = [r for r in doc.get('history') or [] if type(r) is dict]
    exposure = [r for r in doc.get('exposure') or [] if type(r) is dict]
    disclosure = paper.get('disclosure') if type(paper.get('disclosure')) is dict else {}
    findings = []
    reported = {r.get('benchmark') for r in paper.get('results', []) if type(r) is dict}
    hidden = sorted(set(protocol.get('benchmarks', [])) - reported - set(disclosure.get('omitted_benchmarks', [])))
    if hidden:
        findings.append(_finding(check_id, 'benchmark_cherry_pick',
                                 'evaluated benchmarks are neither reported nor disclosed: ' + ', '.join(hidden),
                                 location='results'))
    held = set((protocol.get('held_out') or {}).get('ids', []))
    leaked = sorted({i for r in exposure if r.get('purpose') in {'calibration', 'training', 'tuning', 'selection'}
                     for i in r.get('ids', []) if i in held})
    if leaked and (paper.get('evaluation') or {}).get('split') == 'held_out':
        findings.append(_finding(check_id, 'held_out_leakage',
                                 'held-out items were read for fitting or selection before the reported evaluation: '
                                 + ', '.join(leaked), location='evaluation'))
    if protocol.get('primary_metric') and paper.get('primary_metric') != protocol['primary_metric']:
        findings.append(_finding(check_id, 'metric_swap',
                                 f"the reported primary metric {paper.get('primary_metric')!r} is not the pre-registered "
                                 f"{protocol['primary_metric']!r}", location='primary_metric'))
    first_eval = min((_utc(r.get('utc')) for r in exposure
                      if r.get('purpose') == 'evaluation' and set(r.get('ids', [])) & held), default=None)
    rules = [(_utc(r.get('utc')), r['selection_rule']) for r in history if r.get('selection_rule')]
    changed = [utc for utc, rule in rules if rule != protocol.get('selection_rule')]
    late = first_eval is not None and any(utc > first_eval for utc, _ in rules)
    if (changed or late) and (paper.get('selection') or {}).get('pre_registered'):
        findings.append(_finding(check_id, 'post_hoc_selection',
                                 'the selection rule was set or changed after held-out evaluation, yet the manuscript '
                                 'calls it pre-registered', location='selection'))
    if not disclosure.get('funnel'):
        findings.append(_finding(check_id, 'funnel_undisclosed',
                                 'the manuscript omits the computed candidate funnel', location='disclosure'))
    return result(check_id, findings)


CHECKS = {'review.normalization_recompute': normalization_recompute, 'review.routine_review': routine_review,
          'review.impossible_spec': impossible_spec, 'review.lesson_screen': lesson_screen,
          'review.manuscript_audit': manuscript_audit}


def _divergence(doc, *, check_id='review.divergence'):
    from ravel.validation import divergence
    return divergence.compare(doc.get('a'), doc.get('b'), tolerance=doc.get('tolerance', divergence.TOLERANCE),
                              check_id=check_id)


CHECKS['review.divergence'] = _divergence
from ravel.validation.higgs_checks import compose_document_checks
allowlist = compose_document_checks(CHECKS, allowlist)


def _rubric(doc, *, check_id='review.rubric'):
    from . import review_rubric
    return review_rubric.check(doc, check_id=check_id)


CHECKS['review.rubric'] = _rubric


# ---- ML study verdicts and reviewer items -------------------------------------------------------

ML_RESULT_CHECKS = ('check:ml-estimand-declared', 'check:ml-statistics-sizing', 'check:ml-benchmark-localization',
                    'check:ml-ablation-arms', 'check:ml-crossfit-audit', 'check:ml-selection-flatness',
                    'check:ml-spurious-signal', 'check:ml-reference-fidelity', 'check:ml-injection-closure',
                    'check:ml-null-calibration', 'check:ml-trials-accounting', 'check:ml-claim-scope',
                    'check:ml-label-leakage', 'check:ml-equal-budget', 'check:ml-test-once')
# Planning items with no computation anywhere: a reviewer judges each one; no check can pass it.
ML_REVIEWER_ITEMS = ('check:ml-baseline-set', 'check:ml-oracle-labelled', 'check:ml-cost-preflight',
                     'check:ml-hypothesis-family', 'check:ml-stopping-rule')
_ML_PASS = frozenset({'pass', 'passed', 'asserted_by_construction'})
_ML_FAIL = frozenset({'fail', 'failed'})
ML_OBSERVATION_KIND = 'ml-check-observation'
_ML_GRAPH_STAGES = {'check:ml-estimand-declared': {'S1'}, 'check:ml-equal-budget': {'S6'},
                    'check:ml-test-once': {'S8', 'S12'}, 'check:ml-ablation-arms': {'S13'}}


def record_ml_stage(store, *, spec, stage, result):
    """Controller observer for the operation owner's completed, recomputed stage.

    Called by the graph after its validators have run, never exposed as a broker action.
    Store custody authenticates the observation; a public result file cannot issue one.
    Both the frozen specification and complete result are bound into every reference.
    Missing, unresolved and failed checks are retained with their original scope.
    """
    if type(spec) is not dict or type(result) is not dict or type(result.get('checks')) is not dict:
        raise ValueError('a computed stage and its specification are required')
    if 'controller_checks' in result:
        raise ValueError('a stage observation cannot include its own references')
    references = {}
    for check_id, check in result['checks'].items():
        if check_id not in ML_RESULT_CHECKS:
            continue
        row = {'schema_version': 1, 'kind': ML_OBSERVATION_KIND, 'check_id': check_id,
               'stage': stage, 'spec_sha256': broker_module.digest(spec),
               'subject_sha256': broker_module.digest(result), 'check': deepcopy(check)}
        record_id = store.append(ML_OBSERVATION_KIND, row)
        references[check_id] = {key: row[key] for key in ('spec_sha256', 'subject_sha256')}
        references[check_id]['record_id'] = record_id
    return references


def observed_ml_result(store, binding, *, check_id):
    """Read only the controller observation selected by the dispatcher's bound order.

    Graph-owned checks must originate at their implementing stage. Other passes require
    an executed validator identity and its exact artifact pin. An unresolved scientific
    result stays unresolved even when the executor completed successfully.
    """
    missing = lambda reason: result(check_id, [], status='inconclusive', outcome='computation_unverified',
                                    diagnostics={'reason': reason})
    if (store is None or type(binding) is not dict
            or set(binding) != {'record_id', 'spec_sha256', 'subject_sha256'}
            or type(binding.get('record_id')) is not str or not binding['record_id']
            or any(type(binding.get(k)) is not str or not re.fullmatch('[0-9a-f]{64}', binding[k])
                   for k in ('spec_sha256', 'subject_sha256'))):
        return missing('the sealed work order must bind a controller computation observation')
    try:
        row = store.read(ML_OBSERVATION_KIND, binding['record_id'])
        if type(row) is dict and 'record' in row:
            row = row['record']
    except (OSError, KeyError, IndexError, TypeError, ValueError):
        return missing('the controller computation observation is unavailable')
    if (type(row) is not dict or row.get('kind') != ML_OBSERVATION_KIND or row.get('schema_version') != 1
            or row.get('check_id') != check_id
            or any(row.get(k) != binding[k] for k in ('spec_sha256', 'subject_sha256'))):
        return missing('the computation observation differs from the sealed work order')
    check = row.get('check')
    if type(check) is not dict:
        return missing('the observation has no typed check outcome')
    source, verdict = check.get('source'), check.get('verdict')
    artifact = check.get('artifact')
    authenticated = ((source == 'graph' and row.get('stage') in _ML_GRAPH_STAGES.get(check_id, set()))
                     or (source == 'validator' and type(check.get('validator')) is dict and bool(check['validator'])
                         and type(artifact) is dict and type(artifact.get('path')) is str and bool(artifact['path'])
                         and type(artifact.get('sha256')) is str
                         and re.fullmatch('[0-9a-f]{64}', artifact['sha256']) is not None))
    diagnostics = {'record_id': binding['record_id'], 'spec_sha256': row['spec_sha256'],
                   'subject_sha256': row['subject_sha256'], 'stage': row.get('stage'), 'check': check}
    if not authenticated:
        return missing('no executed graph check or registered validator authenticated this outcome')
    if verdict == 'pass':
        return result(check_id, [], status='passed', diagnostics=diagnostics)
    if verdict == 'fail':
        return result(check_id, [_finding(check_id, 'ml_check_failed', 'The registered computation found a defect.')],
                      status='failed', diagnostics=diagnostics)
    return result(check_id, [], status='inconclusive', outcome='verdict_unresolved', diagnostics=diagnostics)


def ml_result(doc, *, check_id):
    """Inspect a supplied ML result without promoting its declared verdict to computation.

    A document alone cannot authenticate a graph check or establish that cross-fitting ran.
    Report an explicit failure, but hold every success claim. The broker obtains actual
    computation evidence separately via ``observed_ml_result`` and its bound work order.
    """
    rows = doc.get('checks') if type(doc) is dict else None
    if type(rows) is not dict or check_id not in rows:
        return result(check_id, [], status='inconclusive', outcome='verdict_missing',
                      diagnostics={'reason': 'the result document records no verdict for this check'})
    row = rows[check_id]
    verdict = row.get('verdict') if type(row) is dict else row
    if type(verdict) is str and verdict in _ML_PASS:
        return result(check_id, [], status='inconclusive', outcome='computation_unverified',
                      diagnostics={'verdict': verdict, 'row': row,
                                   'reason': 'a supplied verdict is not authenticated computation evidence'})
    if type(verdict) is str and verdict in _ML_FAIL:
        return result(check_id, [_finding(check_id, 'ml_check_failed', f'The study computed {check_id} as failed.')],
                      status='failed', diagnostics={'verdict': verdict, 'row': row})
    return result(check_id, [], status='inconclusive', outcome='verdict_unresolved',
                  diagnostics={'verdict': verdict, 'row': row})


def reviewer_item(doc, *, check_id):
    """A must_check item no code computes: always inconclusive; credit needs the reviewer's per-item verdict."""
    return result(check_id, [], status='inconclusive', outcome='reviewer_item',
                  diagnostics={'reason': 'no computation exists; a reviewer verdict with evidence decides this item'})


for _check in ML_RESULT_CHECKS:
    CHECKS[_check] = ml_result
for _check in ML_REVIEWER_ITEMS:
    CHECKS[_check] = reviewer_item


# ---- model, assumption, acceptance and figure-specification verdicts ------------------------------

UFO_SOURCE = re.compile(r'[A-Za-z0-9_]+\.py')
ACCEPTANCE_ROLES = ('driving', 'contributing', 'tail')


def _unresolved(check_id, outcome, reason, **diagnostics):
    """Evidence the check cannot read: inconclusive, never a pass and no finding against the subject."""
    return result(check_id, [], status='inconclusive', outcome=outcome, diagnostics={'reason': reason, **diagnostics})


def _refused(check_id, code, errors, *, location=None, **diagnostics):
    """A defect the validator reported: a finding per error (the first 50); every error stays in the diagnostics."""
    errors = [str(e) for e in errors]
    return result(check_id, [_finding(check_id, code, e, location=location) for e in errors[:50]],
                  status='failed', diagnostics={'errors': errors, **diagnostics})


def ufo_check(doc, *, check_id='check:physics.ufo_check.check'):
    """``doc``: {'files': {<name>.py: source text}, 'spec': ModelSpec | null}.

    The static checker parses the carried text with ``ast.parse``; the model is never imported or run.
    A defect it reports fails. Sources or a spec it cannot read leave the check inconclusive."""
    from ravel.physics import ufo_check as checker
    doc = doc if type(doc) is dict else {}
    files, spec = doc.get('files'), doc.get('spec')
    if (type(files) is not dict or not files or not (spec is None or type(spec) is dict)
            or any(type(k) is not str or not UFO_SOURCE.fullmatch(k) or type(v) is not str for k, v in files.items())):
        return _unresolved(check_id, 'inputs_missing',
                           'the document must carry the UFO sources as {file name: text} and a ModelSpec or null')
    try:
        with tempfile.TemporaryDirectory(prefix='ufo-check-') as folder:
            for name, text in files.items():
                (Path(folder) / name).write_text(text, encoding='utf-8')
            report = checker.check(folder, spec=spec)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        return _unresolved(check_id, 'inputs_invalid', f'the sources or spec cannot be read: {type(exc).__name__}: {exc}')
    if not report['passed']:
        return _refused(check_id, 'ufo_defect', report['errors'], warnings=report['warnings'])
    return result(check_id, [], status='passed', diagnostics={
        'counts': report['counts'], 'required_coupling_survival': report['required_coupling_survival'],
        'warnings': report['warnings'], 'spec_compared': spec is not None})


def charge_census(doc, *, check_id='check:physics.model_authoring.charge_census'):
    """``doc``: a ModelSpec, or {'spec': ModelSpec}.

    Exact charge, hypercharge and colour-triality neutrality of every Lagrangian term. The census takes
    exact rationals: a decimal charge is refused, never rounded. A spec it cannot read is inconclusive."""
    from ravel.physics import model_authoring
    spec = doc['spec'] if type(doc) is dict and type(doc.get('spec')) is dict else doc
    if (type(spec) is not dict or type(spec.get('fields')) is not list
            or type(spec.get('lagrangian_terms')) is not list or not spec['lagrangian_terms']):
        return _unresolved(check_id, 'inputs_missing',
                           'a ModelSpec with fields and at least one Lagrangian term is required')
    try:
        report = model_authoring.charge_census(spec)
    except ValueError as exc:
        return _refused(check_id, 'charge_not_exact', [exc])
    except (KeyError, TypeError, AttributeError) as exc:
        return _unresolved(check_id, 'inputs_invalid', f'the census cannot read the spec: {type(exc).__name__}: {exc}')
    if report['passed']:
        return result(check_id, [], status='passed', diagnostics={'terms': report['terms']})
    return result(check_id, [_finding(check_id, 'charge_neutrality', f"term {row['term']}: " + '; '.join(row['problems']),
                                      location=row['term']) for row in report['terms'] if not row['passed']],
                  status='failed', diagnostics={'terms': report['terms']})


def adjudicate_gauge_checks(doc, *, check_id='check:physics.model_authoring.adjudicate_gauge_checks'):
    """``doc``: the two-gauge record {feynman, unitary, goldstones}, a native receipt carrying it as
    ``gauge_checks``, or {'native': record, 'extra_goldstones': [field names]}.

    Unitary gauge decides; a Feynman-gauge Goldstone mixing is waived only when FeynRules reported it.
    A record without a verdict for every check cannot be adjudicated: inconclusive."""
    from ravel.physics import model_authoring
    doc = doc if type(doc) is dict else {}
    native = doc['native'] if type(doc.get('native')) is dict else doc.get('gauge_checks', doc)
    extra = doc.get('extra_goldstones', [])
    if type(extra) is not list or any(type(g) is not str for g in extra):
        return _unresolved(check_id, 'inputs_invalid', 'extra_goldstones must be a list of field names')
    try:
        report = model_authoring.adjudicate_gauge_checks(native, extra_goldstones=tuple(extra))
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return _unresolved(check_id, 'inputs_invalid', f'the gauge record cannot be adjudicated: {exc}')
    if report['passed']:
        return result(check_id, [], status='passed', diagnostics={
            'verdicts': report['verdicts'], 'waived': report['waived'], 'rule': report['rule']})
    return _refused(check_id, 'gauge_check_failed', report['failures'], verdicts=report['verdicts'],
                    waived=report['waived'])


def assumption_audit(doc, *, check_id='check:validation.assumption_audit.check'):
    """``doc``: {'audit': assumption-audit record, 'result': the delivered result with ``assumptions_reported``}.

    Every uncontrolled item at or above the K8 severity floor must be named in the delivered result. The check
    grades no physics: the severities are the auditor's. An audit record that is not valid is inconclusive."""
    from ravel.validation import assumption_audit as coverage
    doc = doc if type(doc) is dict else {}
    audit, delivered = doc.get('audit'), doc.get('result')
    reported = delivered.get('assumptions_reported', []) if type(delivered) is dict else None
    if type(audit) is not dict or type(reported) is not list or any(type(name) is not str for name in reported):
        return _unresolved(check_id, 'inputs_missing',
                           'the document needs the audit record and the delivered result (assumptions_reported a list of ids)')
    try:
        errors = coverage.check(audit, delivered)
    except (ValueError, KeyError, TypeError) as exc:
        return _unresolved(check_id, 'inputs_invalid', f'the audit record is not valid: {exc}')
    if errors:
        return _refused(check_id, 'assumption_unreported', errors)
    items = audit['items']
    return result(check_id, [], status='passed', diagnostics={
        'items': len(items), 'uncontrolled': sum(not i['controlled'] for i in items), 'reported': sorted(map(str, reported))})


def _acceptance_ladder(rows, eff):
    """The per-region residuals and the PASS/WARN/FAIL ladder of ``certify_acceptance``, recomputed from report rows.

    Roles are taken as recorded: an override can promote a region to driving and leaves no trace, so only a
    role the rule cannot produce is a defect. Returns (verdict, table, worst driving residual, defects, reasons)."""
    from ravel.validation.validate_cutflow import comparison_ratio, finite_nonnegative
    table = []
    for row in rows:
        if (type(row) is not dict or type(row.get('sr')) is not str or row.get('role') not in ACCEPTANCE_ROLES
                or type(row.get('node')) is not str or type(row.get('off_grid')) is not bool):
            raise ValueError('every row needs sr, role, node and off_grid')
        events = None if row.get('events') is None else finite_nonnegative(row['events'], 'events')
        table.append({'row': row, 'events': events, 'ratio': comparison_ratio(row.get('mine'), row.get('pub'))})
    best = max((t['events'] for t in table if t['events'] is not None), default=None)
    defects, reasons = [], []
    for t in table:
        row, role, events, ratio = t['row'], t['row']['role'], t['events'], t['ratio']
        derived = ('tail' if events is not None and events < eff['tail_events'] else
                   'driving' if best and events is not None and events >= best / eff['driving_factor'] else 'contributing')
        if role != derived and role != 'driving':
            defects.append(('role_inconsistent', f"{row['sr']}: recorded role {role} contradicts its {events} selected "
                                                 f"events (the rule gives {derived})"))
        tol = {'driving': eff['driving_tol'], 'contributing': eff['contributing_tol']}.get(role)
        residual = None if ratio is None else abs(1 - ratio)
        t.update(role=role, residual=residual, impact=residual if role == 'driving' else None,
                 ok=(tol is None or role != 'driving') if residual is None else (tol is None or residual <= tol))
        stored = row.get('ratio', ratio)
        if (stored is None) != (ratio is None) or (ratio is not None and not (
                type(stored) in (int, float) and math.isclose(stored, ratio, rel_tol=1e-9, abs_tol=1e-12))):
            defects.append(('ratio_inconsistent', f"{row['sr']}: stored ratio {stored!r} differs from {ratio!r} "
                                                  'recomputed from the recorded yields'))
    driving = [t for t in table if t['role'] == 'driving']
    worst = max((t['impact'] for t in driving if t['impact'] is not None), default=None)
    driving_ok = all(t['ok'] for t in driving) if driving else None
    off_grid = any(t['row']['off_grid'] for t in driving)
    unmatched = any(t['row']['node'].startswith('NEAREST') for t in driving)
    bound = eff['mu95_bound']
    if not driving or driving_ok is False or worst is None or unmatched:
        verdict = 'FAIL'
    elif driving_ok and worst <= bound and not off_grid:
        verdict = 'PASS'
    elif worst <= 1.5 * bound and not off_grid:
        verdict = 'WARN'
    else:
        verdict = 'FAIL'
    if not driving:
        reasons.append(('no_driving_region', 'no driving region: every region is below the tail threshold or lacks an event count'))
    for t in driving:
        if t['ratio'] is None:
            reasons.append(('driving_unevaluated', f"{t['row']['sr']}: no computable ratio (routine yield or published value absent)"))
        elif not t['ok']:
            reasons.append(('driving_over_tolerance', f"{t['row']['sr']}: residual {t['residual']:.3g} exceeds the driving "
                                                      f"tolerance {eff['driving_tol']:g}"))
    if unmatched:
        reasons.append(('driving_reference_unmatched', 'a driving region is compared with a different published mass point'))
    if off_grid:
        reasons.append(('driving_off_grid', 'a driving region is compared off the published grid'))
    if worst is not None and worst > bound:
        reasons.append(('residual_above_bound', f'the worst driving residual {worst:.3g} exceeds the bound {bound:g}'))
    return verdict, table, worst, defects, reasons


def certify_acceptance(doc, *, check_id='check:validation.certify_acceptance'):
    """``doc``: the acceptance certification report: rows [{sr, role, mine, pub, events, node, off_grid, ratio}],
    certification_tolerances {approved, effective}, verdict, driving_tol, mu95_bound, worst_driving_residual.

    The ladder is recomputed from the rows under the effective tolerances; a stored verdict never grants the
    pass. A recomputed WARN is a bounded but unresolved residual: inconclusive. A diagnostic report, or one
    without its tolerance binding, decides nothing. The approval behind the tolerances is verified against the
    run by the certificate validator, not here."""
    from ravel.validation import certification_tolerances as controls
    doc = doc if type(doc) is dict else {}
    rows, binding = doc.get('rows'), doc.get('certification_tolerances')
    if type(rows) is not list or not rows or type(binding) is not dict:
        return _unresolved(check_id, 'inputs_missing', 'the report needs its rows and a certification_tolerances binding')
    if binding.get('governance') == 'diagnostic':
        return _unresolved(check_id, 'diagnostic_report',
                           'a diagnostic report is not bound to an approved CHECK-IN 1 and decides nothing')
    try:
        effective = controls.tolerances(binding.get('effective'), complete=True)
        approved = controls.tolerances(binding.get('approved'), complete=True)
        verdict, table, worst, defects, reasons = _acceptance_ladder(rows, effective)
    except (ValueError, KeyError, TypeError) as exc:
        return _unresolved(check_id, 'inputs_invalid', f'the report cannot be recomputed: {exc}')
    defects += [('tolerance_looser_than_approved', f'{n} {effective[n]} is looser than the approved {approved[n]}')
                for n in controls.DEFAULTS if (effective[n] - approved[n]) * controls.LOOSER[n] > 0]
    defects += [('headline_mismatch', f'{n} {doc.get(n)!r} disagrees with the effective {effective[n]}')
                for n in ('driving_tol', 'mu95_bound') if type(doc.get(n)) not in (int, float) or doc[n] != effective[n]]
    if 'verdict' in doc and doc['verdict'] != verdict:
        defects.append(('verdict_inconsistent', f"the stored verdict {doc['verdict']!r} differs from the recomputed {verdict}"))
    if 'worst_driving_residual' in doc:
        stored = doc['worst_driving_residual']
        if (stored is None) != (worst is None) or (worst is not None and not (
                type(stored) in (int, float) and math.isclose(stored, worst, rel_tol=1e-9, abs_tol=1e-12))):
            defects.append(('residual_inconsistent', f'the stored worst driving residual {stored!r} differs from the '
                                                     f'recomputed {worst!r}'))
    diagnostics = {'verdict': verdict, 'worst_driving_residual': worst, 'effective_tolerances': effective,
                   'regions': [{'sr': t['row']['sr'], 'role': t['role'], 'ratio': t['ratio'], 'residual': t['residual'],
                                'ok': t['ok']} for t in table],
                   'reasons': [text for _, text in reasons],
                   'authority': 'recomputed from the report rows; the approval binding is verified by the certificate validator'}
    if defects or verdict == 'FAIL':
        return result(check_id, [_finding(check_id, code, text) for code, text in [*defects, *reasons]],
                      status='failed', diagnostics=diagnostics)
    if verdict == 'WARN':
        return result(check_id, [], status='inconclusive', outcome='residual_unresolved', diagnostics=diagnostics)
    return result(check_id, [], status='passed', diagnostics=diagnostics)


def plot_lint(doc, *, check_id='check:validation.plot_lint'):
    """``doc``: {'figure_spec': {...}}, the typed figure constraints (ranges, scales, aspect, binning, labels).

    Checks the specification itself with ``plot_lint.figure_spec_errors``. The layout gate (legend, annotation and
    tick collisions) needs the live figure and runs inside the renderer at save time: a pass here never claims it."""
    from ravel.validation import plot_lint as linter
    spec = doc.get('figure_spec') if type(doc) is dict else None
    if type(spec) is not dict or not spec:
        return _unresolved(check_id, 'inputs_missing', 'a non-empty figure_spec is required')
    errors = linter.figure_spec_errors(spec)
    if errors:
        return _refused(check_id, 'figure_spec_invalid', errors)
    return result(check_id, [], status='passed', diagnostics={
        'figure_spec': spec, 'scope': 'the specification is well formed; the live-figure layout gate is not re-run'})


CHECKS.update({'check:physics.ufo_check.check': ufo_check, 'check:physics.model_authoring.charge_census': charge_census,
               'check:physics.model_authoring.adjudicate_gauge_checks': adjudicate_gauge_checks,
               'check:validation.assumption_audit.check': assumption_audit,
               'check:validation.certify_acceptance': certify_acceptance, 'check:validation.plot_lint': plot_lint})


def reviewer_items():
    """The must_check ids no code computes: a reviewer's per-item verdict with evidence decides each one."""
    from ravel.validation.higgs_checks import REVIEWER_ITEMS as HIGGS_ITEMS
    return frozenset(ML_REVIEWER_ITEMS) | frozenset(HIGGS_ITEMS)


def computes(check_id):
    """Whether a registered check computes a verdict for ``check_id``.

    A validate step runs only the checks that compute. A reviewer item (``reviewer_items``) is owed
    as a reviewer verdict (``review_points.must_check_missing``), never run as a producer validation:
    its check answers ``inconclusive`` whatever the document, so running it could never pass.
    """
    from .run_validator_checks import ADAPTERS
    return check_id not in reviewer_items() and (check_id in CHECKS or check_id in ADAPTERS)


def permitted(card, check_id):
    """A card may run a supported allowlisted check named on it or listing its role."""
    rows = {row['id']: row for row in allowlist()['validators']}
    row = rows.get(check_id)
    from .run_validator_checks import ADAPTERS
    if row is None or check_id not in {*CHECKS, *ADAPTERS}:
        return False
    named = set(card.get('must_check', [])) | set(card.get('tools', {}).get('validators', []))
    return check_id in named or card['id'] in row.get('roles', [])


def run_check(check_id, doc):
    if check_id not in CHECKS:
        raise ValueError('check is not an allowlisted document check')
    return CHECKS[check_id](deepcopy(doc), check_id=check_id)


def _bound_order(target, card, order_path):
    """The worker's order as an explicitly bound check input, and whether it is the node's sealed order.

    The binding is the dispatcher's own custody: the attempt's record pins a work order and the
    exact bytes of this workspace copy. An order in the retained worker format is accepted on that
    binding (it was validated at dispatch); one the dispatcher did not pin is refused."""
    from . import agent_worker, production_executor
    order = read_json(order_path)
    try:
        record = agent_worker._record(target.rundir, target.node_id, target.attempt)
        copies = {row['path']: row['sha256'] for row in record['input_copies']}
        pinned = (record['spec'].get('work_order') is not None
                  and copies.get('inputs/work-order.json') == broker_module.sha(order_path))
    except (OSError, ValueError, KeyError, TypeError):
        pinned = False
    if (not pinned or type(order) is not dict or order.get('kind') != 'work-order'
            or order.get('node_id') != target.node_id or order.get('role', card['id']) != card['id']):
        raise ValueError('validator work order is not the order its dispatcher pinned for this role and node')
    try:
        sealed = order == production_executor.load_order(target.rundir, target.node_id)
    except ValueError:
        sealed = False
    return order, sealed


def register(target, card):
    """Install document and run checks with exact, card-permitted validator receipts."""
    from .run_validator_checks import ADAPTERS, RunCheckInput, run
    order_path = target.workspace / 'inputs/work-order.json'
    order, sealed = (_bound_order(target, card, order_path) if order_path.is_file() else ({}, False))
    effective = deepcopy(card)
    # The role decides which checks it may run. Only the node's sealed order (pinned at CHECK-IN 1)
    # adds its own list; a retained-format order supplies typed inputs and no extra permission.
    from . import role_registry
    owed = role_registry.self_checks(card['id']) if card.get('family') == 'production' else []
    effective['must_check'] = list(set(card.get('must_check', [])) | set(owed)
                                   | set(order.get('self_check', []) if sealed else []))
    ids = [row['id'] for row in allowlist()['validators'] if row['id'] in {*CHECKS, *ADAPTERS}]

    def handler(args):
        from .broker import Refusal
        check_id = args.get('check_id')
        paths = args.get('paths', [])
        if type(paths) is not list:
            raise Refusal('invalid_call', 'paths must be a list')
        if type(check_id) is not str or not permitted(effective, check_id):
            raise Refusal('not_allowlisted', f'check {check_id!r} is not allowlisted for {card["id"]}')
        if set(args) - {'check_id', 'paths'}:
            raise Refusal('invalid_call', 'check arguments are outside the declared shape')
        if check_id in ML_RESULT_CHECKS and not paths:
            from .review_independence import controller_store
            if not sealed:
                raise Refusal('invalid_call', 'ML computation observations require the sealed work order')
            binding = (order.get('check_inputs') or {}).get(check_id)
            value = observed_ml_result(controller_store(target.rundir), binding, check_id=check_id)
            executed = value['status'] in {'passed', 'failed'}
        elif check_id in ADAPTERS:
            if paths:
                raise Refusal('invalid_call', 'run checks take their inputs from the sealed work order')
            value = run(check_id, RunCheckInput(target.rundir, order, target.workspace))
            executed = value.get('validator_executed') is True
        else:
            if type(paths) is not list or len(paths) != 1 or type(paths[0]) is not str:
                raise Refusal('invalid_call', 'a document check reads exactly one workspace JSON file')
            document = json.loads(target._read({'path': paths[0]})['stdout'])
            try:
                value, executed = run_check(check_id, document), True
            except Exception as exc:
                # The validator was entered: its failed receipt keeps the exact identity.
                raise broker_module.ValidatorRaised(f'{check_id}: {type(exc).__name__}') from exc
        out = f"outputs/check-{check_id.replace(':', '_')}-{broker_module.digest([paths, value])[:12]}.json"
        target._write({'path': out, 'content': json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'})
        return {'stdout': json.dumps({'check_id': check_id, 'status': value['status'], 'outcome': value['outcome'],
                                      'findings': len(value['findings']), 'result': out}, sort_keys=True),
                'input_paths': paths if paths else (['inputs/work-order.json'] if order else []),
                'output_paths': [out], 'validator_executed': executed,
                'exit_status': 0 if value['status'] == 'passed' else 1}
    target.register('check run', handler, derivation='registered_validator', validator_ids=ids)
