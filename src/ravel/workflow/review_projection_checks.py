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

``register(broker, card)`` installs the ``check run`` action: one allowlisted check by id,
permitted for the card, writing its result as a pinned output. Document checks read
workspace files; run checks use typed adapters bound to the run and sealed work order.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path

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
        if check_id in ADAPTERS:
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
                'input_paths': paths if check_id in CHECKS else (['inputs/work-order.json'] if order else []),
                'output_paths': [out], 'validator_executed': executed,
                'exit_status': 0 if value['status'] == 'passed' else 1}
    target.register('check run', handler, derivation='registered_validator', validator_ids=ids)
