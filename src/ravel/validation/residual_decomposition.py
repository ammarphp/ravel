"""Reproduction-residual decomposition, ``check:attribution_above_noise`` and the RCA trigger.

Input: ``claims/residual_model.json``, a binned signal model on a node lattice. Each node gives
our and the reference's claim quantity (a limit that falls as the signal grows), optional
replicas of ours (each with its seed), declared fingerprint values, and per region the
background, our signal yields with ``sumw2`` and the reference signal yields with ``staterror``.
Regions have a role (``signal`` or ``control``) and an optional flavour.

Authority (``diagnose``): the residual model counts only as the output of a registered stage
receipt from a recognized RAVEL tool (``custody_authority.stage_output``), so our yields,
``sumw2`` and replicas are code-computed. The reference values, reference ``staterror`` and
``alpha`` come only from the noise model pinned by the agreement target that the live
CHECK-IN 1 approval binds; a model that declares other values is refused. The model's nodes
must be exactly the target's compared nodes. ``delivery_errors`` (the CHECK-IN 3 and
``delivery`` gate provider) recomputes every stored decomposition and attribution check from
those custody inputs, so an edited, rehashed record is refused.

Per node, in log space, the claim residual ``total = ln(result / reference)`` splits exactly as

- ``rate``: ``-ln R``, with ``R`` the ratio of our summed signal-region yield to the reference's;
- ``shape``: the stat-only signal-region Asimov proxy ``ln(mu95_SR(ours) / mu95_SR(reference))``,
  computed identically from both sides' yields on the same background, minus the rate term;
- ``likelihood``: the remainder ``total - proxy``. It holds whatever the claim's likelihood does
  that a stat-only signal-region count does not: control-region signal, systematics, the
  statistic's construction.

Rate and shape are also resolved per flavour and per named signal region (scopes
``flavour:<f>`` and ``region:<name>``). Each term is correlated across nodes with the
declared fingerprint variables and with the built-in ``reference_cr_signal_fraction``.
``noise_model`` sets the threshold below which a term is noise. A term is attributed in a scope
only above its threshold; ``check_attribution_above_noise`` refuses any attribution claim that
is not, recomputing each comparison from the record's medians and thresholds. Fingerprint
support uses a Holm correction over every (term, variable) test. When the claim residual exceeds the agreement target's tolerance and its noise,
``open_triggers`` hands one trigger to the RCA ticket and board-epoch producers. While those
modules are absent the trigger is recorded as pending and nothing is called.

The decomposition is a diagnostic ordering of candidate explanations, not a cause.
"""
import argparse
import hashlib
import importlib
import json
import math
import os
import re
from pathlib import Path

from scipy.optimize import brentq
from scipy.stats import pearsonr, spearmanr

from ravel.validation import noise_model

MODEL = 'claims/residual_model.json'
PENDING = os.path.join('claims', 'rca_triggers.json')
TARGETS = 'inputs/agreement_targets.json'
NOISE_KIND = 'residual-reference-noise'
CLAIM_ID = re.compile(r'C[0-9]+')
CHECK_ID = 'attribution_above_noise'
PRODUCER = 'ravel.validation.residual_decomposition'
CR_FRACTION = 'reference_cr_signal_fraction'
TERMS = ('rate', 'shape', 'likelihood')
SCOPED_TERMS = ('rate', 'shape')
AGGREGATIONS = ('per_node', 'fraction_within', 'median_abs', 'max_abs')
RCA_SEAM = ('ravel.workflow.rca_ticket', 'open_ticket')
BOARD_SEAM = ('ravel.workflow.research_board', 'open_epoch')
Z95 = 1.959963984540054
MIN_CORRELATION_NODES = 4
_DEFAULT = object()


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _finite(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or (positive and value <= 0) or value < 0:
        raise ValueError(f'{label} must be a finite {"positive" if positive else "nonnegative"} number')
    return float(value)


def _vector(values, n, label, positive=False):
    if not isinstance(values, list) or (n is not None and len(values) != n) or not values:
        raise ValueError(f'{label} must list one value for each of the region\'s bins')
    return [_finite(v, f'{label}[{i}]', positive) for i, v in enumerate(values)]


def validate(model):
    """Refuse a malformed residual model; return the declared fingerprint names."""
    if not isinstance(model, dict) or model.get('schema_version') != 1 or model.get('kind') != 'residual-model':
        raise ValueError('a residual model is {"schema_version": 1, "kind": "residual-model", ...}')
    if model.get('response') != 'inverse':
        raise ValueError('response must be "inverse": the decomposition covers limits that fall as the '
                         'signal grows; another quantity needs its own proxy')
    nodes = model.get('nodes')
    if not isinstance(nodes, list) or not nodes:
        raise ValueError('a residual model needs a nonempty node list')
    ids, declared = set(), None
    for node in nodes:
        nid = node.get('id')
        if not isinstance(nid, str) or not nid or nid in ids:
            raise ValueError('every node needs a distinct id')
        ids.add(nid)
        for key in ('result', 'reference'):
            _finite(node.get(key), f'node {nid} {key}', positive=True)
        if 'replicas' in node:
            replicas = node['replicas']
            if not isinstance(replicas, list) or len(replicas) < 3 or not all(
                    isinstance(r, dict) and set(r) == {'value', 'seed'} and type(r['seed']) is int for r in replicas) \
                    or len({r['seed'] for r in replicas}) != len(replicas):
                raise ValueError(f'node {nid} replicas need at least three {{"value", "seed"}} rows with distinct '
                                 'producer-recorded seeds')
            _vector([r['value'] for r in replicas], None, f'node {nid} replicas', positive=True)
        names = set(node.get('fingerprints') or {})
        for name, value in (node.get('fingerprints') or {}).items():
            if name == CR_FRACTION or isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                raise ValueError(f'node {nid} fingerprint {name} must be a finite number with a declared name '
                                 f'other than the computed {CR_FRACTION}')
        if declared is None:
            declared = names
        elif names != declared:
            missing = sorted(declared ^ names)
            raise ValueError(f'node {nid} declares a different fingerprint set; differs on {missing}')
        regions = node.get('regions')
        if not isinstance(regions, list) or not regions:
            raise ValueError(f'node {nid} needs regions')
        names_seen = set()
        for region in regions:
            name = region.get('name')
            label = f'node {nid} region {name}'
            if not isinstance(name, str) or not name or name in names_seen:
                raise ValueError(f'node {nid} region names must be distinct strings')
            names_seen.add(name)
            if region.get('role') not in ('signal', 'control'):
                raise ValueError(f'{label} role must be signal or control')
            if 'flavour' in region and (not isinstance(region['flavour'], str) or ':' in region['flavour']
                                        or not region['flavour']):
                raise ValueError(f'{label} flavour must be a nonempty string without ":"')
            n = len(_vector(region.get('background'), None, f'{label} background'))
            ours, ref = region.get('ours') or {}, region.get('reference') or {}
            yields = _vector(ours.get('yield'), n, f'{label} ours yield bins')
            sumw2 = _vector(ours.get('sumw2'), n, f'{label} ours sumw2 bins')
            if any(y > 0 and w == 0 for y, w in zip(yields, sumw2)):
                raise ValueError(f'{label} declares sumw2 = 0 for a bin with a yield; a simulated yield has '
                                 'nonzero statistical variance')
            _vector(ref.get('yield'), n, f'{label} reference yield bins')
            _vector(ref.get('staterror'), n, f'{label} reference staterror bins')
        signal = [r for r in regions if r['role'] == 'signal']
        if not signal:
            raise ValueError(f'node {nid} has no signal region')
        for side in ('ours', 'reference'):
            if not sum(sum(r[side]['yield']) for r in signal) > 0:
                raise ValueError(f'node {nid} has no {side} signal-region yield')
    return sorted(declared or ())


def sr_asimov_mu95(signal, background):
    """Stat-only median expected mu95 (asymptotic CLs) on the background-only Asimov dataset.

    q_A(mu) = 2 sum[mu s - b ln(1 + mu s / b)]; the median expected CLs is 2 (1 - Phi(sqrt q_A)),
    which equals 0.05 at sqrt q_A = 1.95996.
    """
    # A bin without background has unbounded stat-only sensitivity; it is left out of the proxy.
    pairs = [(float(s), float(b)) for s, b in zip(signal, background) if s > 0 and b > 0]
    if not pairs:
        return None

    def q(mu):
        return 2.0 * sum(mu * s - b * math.log1p(mu * s / b) for s, b in pairs) - Z95 ** 2

    high = 1.0
    while q(high) < 0:
        high *= 4.0
        if high > 1e15:
            raise ValueError('the signal-region proxy has no finite root')
    return brentq(q, 0.0, high, xtol=1e-14, rtol=1e-15, maxiter=500)


def _flatten(regions, side):
    signal, background = [], []
    for region in regions:
        signal += region[side]['yield']
        background += region['background']
    return signal, background


def _proxy_and_rate(regions):
    """(ln R, ln mu95_SR(ours)/mu95_SR(reference)) over the given signal regions, or None."""
    ours, background = _flatten(regions, 'ours')
    ref, _ = _flatten(regions, 'reference')
    if not sum(ours) > 0 or not sum(ref) > 0:
        return None
    mu_ours, mu_ref = sr_asimov_mu95(ours, background), sr_asimov_mu95(ref, background)
    if mu_ours is None or mu_ref is None:
        return None
    return math.log(sum(ours) / sum(ref)), math.log(mu_ours / mu_ref)


def _flavours(node):
    return sorted({r['flavour'] for r in node['regions'] if r['role'] == 'signal' and 'flavour' in r})


def node_terms(node):
    """The decomposition terms of one node, keyed for the noise model."""
    signal = [r for r in node['regions'] if r['role'] == 'signal']
    found = _proxy_and_rate(signal)
    if found is None:
        raise ValueError(f'node {node["id"]} has no signal-region bin with signal and background on both sides')
    log_rate, proxy = found
    total = math.log(node['result'] / node['reference'])
    terms = {'total': total, 'proxy': proxy, 'rate': -log_rate, 'shape': proxy + log_rate,
             'likelihood': total - proxy}
    groups = [(f'flavour:{f}', [r for r in signal if r.get('flavour') == f]) for f in _flavours(node)]
    groups += [(f'region:{r["name"]}', [r]) for r in signal]
    for scope, regions in groups:
        found = _proxy_and_rate(regions)
        terms[f'{scope}:rate'] = None if found is None else -found[0]
        terms[f'{scope}:shape'] = None if found is None else found[1] + found[0]
    return terms


def _fingerprints(node, declared):
    values = {name: float(node['fingerprints'][name]) for name in declared}
    control = [r for r in node['regions'] if r['role'] == 'control']
    if control:
        cr = sum(sum(r['reference']['yield']) for r in control)
        everything = sum(sum(r['reference']['yield']) for r in node['regions'])
        values[CR_FRACTION] = cr / everything if everything > 0 else 0.0
    return values


def _region_rows(node):
    rows = {}
    for region in node['regions']:
        ours, ref = sum(region['ours']['yield']), sum(region['reference']['yield'])
        row = {'role': region['role'], 'flavour': region.get('flavour'),
               'rate_ratio': ours / ref if ref > 0 else None, 'proxy': None}
        if region['role'] == 'signal':
            found = _proxy_and_rate([region])
            row['proxy'] = None if found is None else found[1]
        rows[region['name']] = row
    return rows


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def _constant(values):
    return max(values) - min(values) <= 1e-9 * max(1.0, max(abs(v) for v in values))


def _correlation(xs, ys):
    """Pearson and Spearman over nodes; a constant variable or term has no correlation."""
    row = {'n': len(xs), 'pearson': None, 'spearman': None, 'p_value': None, 'p_adjusted': None,
           'supported': False}
    if len(xs) < 3 or _constant(xs) or _constant(ys):
        return row
    pearson = pearsonr(xs, ys)
    spearman = spearmanr(xs, ys)
    row.update(pearson=float(pearson[0]), spearman=float(spearman[0]), p_value=float(pearson[1]))
    row['supported'] = len(xs) >= MIN_CORRELATION_NODES and row['p_value'] < 0.05
    return row


def _holm(fingerprints):
    """Holm step-down over every (term, variable) test: many declared variables cannot fish."""
    tests = sorted((row['p_value'], term, variable) for term, rows in fingerprints.items()
                   for variable, row in rows.items() if row['p_value'] is not None)
    running = 0.0
    for i, (p_value, term, variable) in enumerate(tests):
        running = max(running, min(1.0, (len(tests) - i) * p_value))
        row = fingerprints[term][variable]
        row['p_adjusted'] = running
        row['supported'] = row['n'] >= MIN_CORRELATION_NODES and running < 0.05


def _above(value, threshold):
    return threshold is not None and abs(value) > threshold


def _scope_attribution(values_by_term, thresholds):
    terms, ranked = {}, []
    for term, values in values_by_term.items():
        if not values:
            continue
        median, threshold = _median(values), thresholds.get(term)
        above = _above(median, threshold)
        terms[term] = {'median': median, 'threshold': threshold, 'above_noise': above}
        if above:
            ranked.append((abs(median) / threshold if threshold > 0 else math.inf, term))
    ranked.sort(reverse=True)
    return terms, [term for _, term in ranked]


def _exceedance(nodes, noise, rule):
    if rule is None:
        return None
    if rule.get('aggregation') not in AGGREGATIONS:
        raise ValueError(f'tolerance aggregation must be one of {AGGREGATIONS}')
    threshold = _finite(rule.get('threshold'), 'tolerance threshold', positive=True)
    relative = [n['result'] / n['reference'] - 1.0 for n in nodes]
    if rule['aggregation'] == 'median_abs':
        above_tolerance = _median([abs(r) for r in relative]) > threshold
    else:
        # fraction_within declares no required fraction; every node outside the bound is a feature.
        above_tolerance = any(abs(r) > threshold for r in relative)
    # The node and median channels share the false-alarm rate: noise alone opens a ticket with
    # probability about alpha, not 2 alpha.
    alpha, n = noise['alpha'], len(nodes)
    node_scale = noise_model.node_multiplier(n, alpha / 2) / noise_model.node_multiplier(n, alpha)
    median_scale = noise_model.scope_multiplier(alpha / 2) / noise_model.scope_multiplier(alpha)
    features = []
    by_id = {row['id']: row for row in noise['nodes']}
    for node, rel in zip(nodes, relative):
        limit = node_scale * by_id[node['id']]['threshold']['total']
        if abs(rel) > threshold and abs(node['terms']['total']) > limit:
            features.append({'scope': f'node:{node["id"]}', 'relative': rel, 'total': node['terms']['total'],
                             'threshold': limit})
    median_total = _median([n['terms']['total'] for n in nodes])
    median_threshold = median_scale * noise['scopes']['all']['median_threshold']['total']
    if abs(math.expm1(median_total)) > threshold and abs(median_total) > median_threshold:
        features.append({'scope': 'all', 'relative': math.expm1(median_total), 'total': median_total,
                         'threshold': median_threshold})
    return {'rule': dict(rule), 'relative': relative, 'above_tolerance': above_tolerance,
            'beyond_noise': above_tolerance and bool(features), 'features': features if above_tolerance else []}


def decompose(model, *, tolerance_rule=None, alpha=noise_model.DEFAULT_ALPHA, inputs=None):
    """The residual decomposition record of a residual model (pure; no files). ``inputs`` names
    the custody inputs it was computed from; ``diagnose`` supplies them."""
    declared = validate(model)
    noise = noise_model.build(model, node_terms, alpha)
    noise_by_id = {row['id']: row for row in noise['nodes']}
    nodes = []
    for node in model['nodes']:
        terms = node_terms(node)
        threshold = noise_by_id[node['id']]['threshold']
        nodes.append({'id': node['id'], 'coordinates': node.get('coordinates'), 'result': node['result'],
                      'reference': node['reference'],
                      'terms': {k: terms[k] for k in ('total', 'proxy') + TERMS},
                      'scoped': {scope: {t: terms[f'{scope}:{t}'] for t in SCOPED_TERMS}
                                 for scope in sorted({k.rpartition(':')[0] for k in terms if ':' in k})},
                      'above_noise': {t: _above(terms[t], threshold.get(t)) for t in TERMS + ('total',)},
                      'regions': _region_rows(node), 'fingerprints': _fingerprints(node, declared)})
    attribution = {}
    terms, ranked = _scope_attribution({t: [n['terms'][t] for n in nodes] for t in TERMS + ('total',)},
                                       noise['scopes']['all']['median_threshold'])
    ranked = [t for t in ranked if t != 'total']
    attribution['all'] = {'n_nodes': len(nodes), 'terms': terms, 'ranked': ranked,
                          'assigned': ranked[0] if ranked else None}
    for scope in sorted({s for n in nodes for s in n['scoped']}):
        values = {t: [n['scoped'][scope][t] for n in nodes
                      if scope in n['scoped'] and n['scoped'][scope][t] is not None] for t in SCOPED_TERMS}
        terms, ranked = _scope_attribution(values, noise['scopes'].get(scope, {}).get('median_threshold', {}))
        attribution[scope] = {'n_nodes': len(values['rate']), 'terms': terms, 'ranked': ranked,
                              'assigned': ranked[0] if ranked else None}
    variables = sorted({k for n in nodes for k in n['fingerprints']})
    fingerprints = {}
    for term in TERMS + ('total',):
        fingerprints[term] = {}
        for variable in variables:
            pairs = [(n['fingerprints'][variable], n['terms'][term]) for n in nodes if variable in n['fingerprints']]
            fingerprints[term][variable] = _correlation([p[0] for p in pairs], [p[1] for p in pairs])
    _holm(fingerprints)
    record = {'schema_version': 1, 'kind': 'residual-decomposition', 'response': model['response'],
              'model_sha256': _digest(model), 'alpha': alpha, 'nodes': nodes, 'noise': noise,
              'attribution': attribution, 'fingerprints': fingerprints,
              'exceedance': _exceedance(nodes, noise, tolerance_rule),
              'limitation': 'diagnostic ordering of candidate explanations; a term above noise is a '
                            'feature to explain, not an established cause'}
    if inputs is not None:
        record['inputs'] = inputs
    record['sha256'] = _digest(record)
    return record


def _intact(record):
    body = {k: v for k, v in record.items() if k != 'sha256'}
    return record.get('kind') == 'residual-decomposition' and record.get('sha256') == _digest(body)


def check_attribution_above_noise(record, claims):
    """check:attribution_above_noise: refuse every attribution claim on a feature below its threshold.

    A claim is ``{"term": rate|shape|likelihood, "scope": "all"|"flavour:<f>"|"region:<name>"|"node:<id>",
    "fingerprint": <variable>?}``. A fingerprint claim also needs a supported plane-wide correlation.
    """
    refusals = []
    if not _intact(record):
        refusals.append({'claim': None, 'reason': 'the decomposition record does not match its sha256'})
    if not isinstance(claims, list) or not claims:
        refusals.append({'claim': None, 'reason': 'no attribution claim to check; an empty check passes nothing'})
        claims = []
    nodes = {n['id']: n for n in record.get('nodes', [])}
    node_thresholds = {n['id']: n['threshold'] for n in (record.get('noise') or {}).get('nodes', [])}
    for claim in claims:
        if not isinstance(claim, dict):
            refusals.append({'claim': claim, 'reason': 'an attribution claim is an object'})
            continue
        term, scope = claim.get('term'), claim.get('scope', 'all')
        if not isinstance(scope, str):
            refusals.append({'claim': claim, 'reason': 'scope must be a string'})
            continue
        if scope.startswith('node:'):
            node = nodes.get(scope[len('node:'):])
            if node is None:
                refusals.append({'claim': claim, 'reason': f'{scope} is not a node of the decomposition'})
                continue
            if term not in TERMS:
                refusals.append({'claim': claim, 'reason': f'term {term!r} is not one of {TERMS}'})
                continue
            threshold = node_thresholds.get(node['id'], {}).get(term)
            if threshold is None:
                refusals.append({'claim': claim, 'reason': f'{term} at {scope} has no noise budget; the likelihood '
                                                            'term needs replicas of our result'})
            elif not _above(node['terms'][term], threshold):
                refusals.append({'claim': claim, 'reason': f'{term} at {scope} ({node["terms"][term]:.4g}) is '
                                                            'below its noise threshold'})
        else:
            entry = record.get('attribution', {}).get(scope)
            if entry is None:
                refusals.append({'claim': claim, 'reason': f'scope {scope} is not in the decomposition'})
                continue
            if term not in entry['terms'] or term == 'total':
                refusals.append({'claim': claim, 'reason': f'term {term!r} is not attributable in {scope}'})
                continue
            row = entry['terms'][term]
            if row['threshold'] is None:
                refusals.append({'claim': claim, 'reason': f'{term} in {scope} has no noise budget; the likelihood '
                                                            'term needs replicas of our result'})
            elif not _above(row['median'], row['threshold']):
                refusals.append({'claim': claim, 'reason': f'{term} median in {scope} ({row["median"]:.4g}) is '
                                                            f'below its noise threshold ({row["threshold"]})'})
        variable = claim.get('fingerprint')
        if variable is not None:
            corr = record.get('fingerprints', {}).get(term, {}).get(variable)
            if scope != 'all':
                refusals.append({'claim': claim, 'reason': 'fingerprint correlations are plane-wide (scope all)'})
            elif corr is None:
                refusals.append({'claim': claim, 'reason': f'fingerprint {variable!r} is not declared'})
            elif not corr['supported']:
                refusals.append({'claim': claim, 'reason': f'fingerprint {variable!r} correlation with {term} is '
                                                            f'not supported (n={corr["n"]}, p={corr["p_value"]})'})
    return {'schema_version': 1, 'kind': 'ravel-check-result', 'check_id': CHECK_ID,
            'producer': PRODUCER, 'status': 'failed' if refusals else 'passed',
            'decomposition_sha256': record.get('sha256'), 'claims': claims, 'refusals': refusals, 'pins': []}


def _resolve(module, name):
    """The seam callable, or None while its producer module is absent."""
    try:
        found = importlib.import_module(module)
    except ImportError:
        return None
    target = getattr(found, name, None)
    return target if callable(target) else None


def trigger(record, claim_id):
    """The trigger handed to the RCA ticket (its symptom) and board-epoch producers."""
    exceedance = record['exceedance']
    seeds = []
    for scope, entry in sorted(record['attribution'].items()):
        for term in entry['ranked']:
            row = entry['terms'][term]
            seeds.append({'kind': 'term', 'scope': scope, 'term': term, 'median': row['median'],
                          'threshold': row['threshold']})
    for term in record['attribution']['all']['ranked']:
        for variable, corr in sorted(record['fingerprints'][term].items()):
            if corr['supported']:
                seeds.append({'kind': 'fingerprint', 'term': term, 'variable': variable,
                              'pearson': corr['pearson'], 'spearman': corr['spearman'], 'p_value': corr['p_value']})
    return {'schema_version': 1, 'trigger_id': record['sha256'], 'claim_id': claim_id,
            'origin': f'check:{CHECK_ID}',
            'symptom': {'finding_id': None, 'trigger_id': record['sha256']},
            'quantity_trace': [{'node': n['id'], 'result': n['result'], 'reference': n['reference'],
                                'relative': rel} for n, rel in zip(record['nodes'], exceedance['relative'])],
            'tolerance_rule': exceedance['rule'], 'features': exceedance['features'], 'seeds': seeds,
            'min_hypotheses': 2}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=1, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def _record_pending(rundir, item, pending):
    path = Path(rundir) / PENDING
    current = {'schema_version': 1, 'kind': 'rca-triggers', 'triggers': []}
    if path.is_file():
        current = json.loads(path.read_text(encoding='utf-8'))
    if any(row['trigger_id'] == item['trigger_id'] for row in current['triggers']):
        return
    current['triggers'].append({'trigger_id': item['trigger_id'], 'claim_id': item['claim_id'],
                                'pending': pending, 'trigger': item})
    _write_json(path, current)


def open_triggers(rundir, record, *, claim_id, rca=_DEFAULT, board=_DEFAULT):
    """Open one RCA ticket and one board epoch when the residual exceeds tolerance beyond noise.

    ``rca`` and ``board`` are ``callable(rundir, trigger) -> dict``. By default they resolve to
    ``ravel.workflow.rca_ticket.open_ticket`` and ``ravel.workflow.research_board.open_epoch``;
    a side whose module is absent is recorded in ``claims/rca_triggers.json`` as pending.
    """
    if record.get('exceedance') is None:
        raise ValueError('the decomposition has no agreement tolerance rule; a trigger needs the target tolerance')
    if not _intact(record):
        raise ValueError('the decomposition record does not match its sha256')
    if not record['exceedance']['beyond_noise']:
        return {'status': 'no_trigger', 'above_tolerance': record['exceedance']['above_tolerance']}
    item = trigger(record, claim_id)
    seams = {'rca': _resolve(*RCA_SEAM) if rca is _DEFAULT else rca,
             'board': _resolve(*BOARD_SEAM) if board is _DEFAULT else board}
    results, pending = {}, []
    for side, call in seams.items():
        if call is None:
            pending.append(side)
            results[side] = None
        else:
            results[side] = call(str(rundir), item)
    if pending:
        _record_pending(rundir, item, pending)
    return {'status': 'pending' if pending else 'opened', 'pending': pending, 'trigger': item, **results}


def paths(claim_id):
    """Run-relative records of one agreement claim's diagnosis."""
    if not isinstance(claim_id, str) or not CLAIM_ID.fullmatch(claim_id):
        raise ValueError('an agreement claim id is C<n>')
    base = f'claims/residual/{claim_id}'
    return {'decomposition': f'{base}/decomposition.json', 'noise': f'{base}/noise_model.json',
            'check': f'{base}/attribution_check.json'}


def _sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _approved_target(rundir, claim_id):
    """The agreement target of ``claim_id`` as the live CHECK-IN 1 approval bound it."""
    from ravel.workflow.custody_authority import approved_checkin1
    checkin = approved_checkin1(rundir)
    section = (checkin.get('sections') or {}).get('agreement_targets') or {}
    row = next((r for r in section.get('claims') or [] if isinstance(r, dict) and r.get('claim_id') == claim_id
                and r.get('status') == 'valid' and isinstance(r.get('target'), dict)), None)
    if row is None:
        raise ValueError(f'claim {claim_id} has no valid agreement-target record in the approved CHECK-IN 1; the '
                         'residual diagnosis binds to the agreement target and its tolerance rule')
    path = Path(rundir) / TARGETS
    if not path.is_file() or _sha_file(path) != section.get('record_sha256'):
        raise ValueError(f'{TARGETS} changed after the CHECK-IN 1 approval')
    return row['target']


def _reference_noise(rundir, target):
    """The approved reference noise model: reference values, staterror and alpha by node."""
    pin = (target.get('noise_model') or {}).get('pin')
    if pin is None:
        raise ValueError('the approved agreement target pins no noise model; reference noise comes only from '
                         'the approved plan')
    locator = pin['locator']
    path = Path(locator) if os.path.isabs(locator) else Path(rundir) / locator
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f'the approved noise model {locator} is unreadable: {exc}') from None
    if hashlib.sha256(raw).hexdigest() != pin['sha256']:
        raise ValueError(f'the approved noise model {locator} differs from its pin')
    value = _strict(raw)
    if not isinstance(value, dict) or value.get('kind') != NOISE_KIND or not isinstance(value.get('nodes'), list):
        raise ValueError(f'the approved noise model is not a {NOISE_KIND} record')
    alpha = value.get('alpha', noise_model.DEFAULT_ALPHA)
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not 0.0 < alpha < 1.0:
        raise ValueError('the approved noise model alpha must lie in (0, 1)')
    return value, {'locator': locator, 'sha256': pin['sha256']}, float(alpha)


def _coordinates(value):
    if not isinstance(value, list) or not value or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
        raise ValueError('every residual-model node needs numeric coordinates')
    return tuple(float(x) for x in value)


def _bind(model, target, noise):
    """Refuse a model whose nodes, reference values or reference noise differ from the approved ones."""
    nodes = model.get('nodes') if isinstance(model, dict) else None
    if not isinstance(nodes, list):
        raise ValueError('a residual model needs a node list')
    compared = sorted(_coordinates(c) for c in (target.get('nodes') or {}).get('compared') or [])
    if sorted(_coordinates(n.get('coordinates')) for n in nodes) != compared:
        raise ValueError('the residual model\'s nodes differ from the agreement target\'s compared nodes')
    approved = {_coordinates(n.get('coordinates')): n for n in noise['nodes'] if isinstance(n, dict)}
    for node in nodes:
        reference = approved.get(_coordinates(node['coordinates']))
        if reference is None or reference.get('reference') != node.get('reference'):
            raise ValueError(f'node {node.get("id")} reference differs from the approved noise model')
        regions = {r.get('name'): r for r in node.get('regions') or []}
        declared = reference.get('regions') or {}
        if set(regions) != set(declared) or any(
                (regions[name].get('reference') or {}).get('staterror') != declared[name].get('staterror')
                for name in regions):
            raise ValueError(f'node {node.get("id")} reference staterror differs from the approved noise model')


def _compute(rundir, claim_id, model_receipt):
    """The decomposition recomputed from custody inputs: the approved target and noise model, and
    the residual model as the registered output of ``model_receipt``."""
    from ravel.workflow.custody_authority import stage_output
    target = _approved_target(rundir, claim_id)
    path = Path(rundir) / MODEL
    sha = _sha_file(path)
    stage_output(rundir, model_receipt, MODEL, sha)
    model = _strict(path.read_bytes())
    noise, noise_pin, alpha = _reference_noise(rundir, target)
    _bind(model, target, noise)
    inputs = {'claim_id': claim_id, 'model': {'path': MODEL, 'sha256': sha, 'receipt_id': model_receipt},
              'noise_model': noise_pin}
    return decompose(model, tolerance_rule=target['tolerance_rule'], alpha=alpha, inputs=inputs)


def _pin(rundir, rel):
    return {'path': rel, 'sha256': _sha_file(Path(rundir) / rel)}


def _strict(raw):
    def refuse(name):
        raise ValueError(f'non-finite JSON constant {name}')
    return json.loads(raw, parse_constant=refuse)


def diagnose(rundir, claim_id, *, model_receipt, attributions=None, rca=_DEFAULT, board=_DEFAULT):
    """Decompose a run's residual model against its approved agreement target and open any trigger.

    ``model_receipt`` is the ``stage:<name>:<attempt_id>`` receipt that produced
    ``claims/residual_model.json``. There is no caller-supplied target or false-alarm rate."""
    rundir = Path(rundir)
    record = _compute(rundir, claim_id, model_receipt)
    files = paths(claim_id)
    noise = {**record['noise'], 'claim_id': claim_id, 'inputs': record['inputs']}
    _write_json(rundir / files['noise'], noise)
    _write_json(rundir / files['decomposition'], record)
    out = {'decomposition': files['decomposition'], 'noise_model': files['noise'], 'check': None}
    if attributions is not None:
        result = check_attribution_above_noise(record, attributions)
        result['pins'] = [_pin(rundir, files['decomposition']), _pin(rundir, files['noise'])]
        _write_json(rundir / files['check'], result)
        out['check'] = result['status']
    out['trigger'] = open_triggers(rundir, record, claim_id=claim_id, rca=rca, board=board)
    return out


def delivery_errors(rundir):
    """CHECK-IN 3 and ``delivery`` provider: every approved agreement claim of an epoch-2 run needs
    a stored decomposition equal to its recomputation from custody inputs, and any stored
    attribution check must equal its recomputation."""
    from ravel.validation.validate_checkin import _sibling_contract
    rundir = Path(rundir)
    contract = _sibling_contract(str(rundir))
    if not isinstance(contract, dict) or contract.get('agent_layer_epoch', 1) < 2:
        return []
    try:
        checkin = json.loads((rundir / 'inputs/checkin1.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        return [f'CHECK-IN 1 unreadable for the residual diagnosis: {exc}']
    section = (checkin.get('sections') or {}).get('agreement_targets') if isinstance(checkin, dict) else None
    claims = [r['claim_id'] for r in (section or {}).get('claims') or []
              if isinstance(r, dict) and r.get('status') == 'valid']
    errors = []
    for claim_id in claims:
        files = paths(claim_id)
        try:
            stored = _strict((rundir / files['decomposition']).read_bytes())
        except (OSError, ValueError):
            errors.append(f'agreement claim {claim_id} has no residual decomposition; run residual_decomposition '
                          'before delivery')
            continue
        try:
            recomputed = _compute(rundir, claim_id, stored['inputs']['model']['receipt_id'])
        except Exception as exc:  # noqa: BLE001 - any failure to recompute refuses delivery
            errors.append(f'agreement claim {claim_id} residual decomposition cannot be recomputed from custody '
                          f'inputs: {exc}')
            continue
        if stored != recomputed:
            errors.append(f'agreement claim {claim_id} residual decomposition differs from the one recomputed from '
                          'custody inputs')
            continue
        if (rundir / files['check']).exists():
            try:
                check = _strict((rundir / files['check']).read_bytes())
                again = check_attribution_above_noise(recomputed, check['claims'])
                same = (again['status'], again['refusals']) == (check['status'], check['refusals'])
            except (OSError, ValueError, KeyError, TypeError):
                same = False
            if not same:
                errors.append(f'agreement claim {claim_id} attribution check differs from its recomputation')
    return errors


def gate_errors(rundir, gate, action):
    """Decision-gate ``delivery`` provider over ``delivery_errors``."""
    if gate != 'delivery':
        return []
    from ravel.workflow.decision_gate import GateError
    try:
        errors = delivery_errors(rundir)
    except Exception as exc:  # noqa: BLE001 - unreadable evidence refuses delivery
        errors = [f'residual diagnosis evidence unreadable: {exc}']
    return [GateError('residual_diagnosis', gate, 'residual_diagnosis', error,
                      'Run residual_decomposition on the registered residual model and keep its records unedited.',
                      (f'check:{CHECK_ID}',)) for error in errors]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--rundir', required=True, type=Path)
    ap.add_argument('--claim', required=True, help='the agreement claim id (C<n>)')
    ap.add_argument('--model-receipt', required=True,
                    help='stage:<name>:<attempt_id> receipt that produced claims/residual_model.json')
    ap.add_argument('--attributions', type=Path, help='JSON list of attribution claims to check')
    args = ap.parse_args(argv)
    claims = _strict(args.attributions.read_text(encoding='utf-8')) if args.attributions else None
    try:
        out = diagnose(args.rundir, args.claim, model_receipt=args.model_receipt, attributions=claims)
    except (ValueError, OSError) as exc:
        print(json.dumps({'status': 'refused', 'error': str(exc)}))
        return 2
    print(json.dumps({k: (v['status'] if k == 'trigger' else v) for k, v in out.items()}, sort_keys=True))
    return 1 if out['check'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
