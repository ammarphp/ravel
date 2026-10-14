"""Noise model for a reproduction residual: the size below which a feature is not interpretable.

Every decomposition term is a function of the per-bin signal yields on both sides. Our side
declares each bin's ``sumw2``; the reference declares each bin's ``staterror``. The noise of a
term is the linear propagation of those per-bin variances through the term (a numerical
Jacobian), with bins independent. Where replicas of our claim quantity exist (at least three,
each from a distinct producer-recorded seed), our side of the total residual is the larger of
the propagated noise and the replica scatter's 95% chi-square upper bound, so a few
near-identical replicas cannot shrink it.

Thresholds use one declared false-alarm rate ``alpha``:

- per node, a Sidak multiplier over the number of nodes, so that noise alone crosses some
  node's threshold with probability ``alpha`` across the lattice;
- per scope (all nodes, the nodes of one flavour, or one named signal region), the two-sided ``alpha`` quantile times
  the standard error of a median, ``sqrt(pi/2) * rms(sigma) / sqrt(n)``.

The likelihood term is the claim residual minus the signal-region proxy. Without a joint
estimate of their correlation it takes the uncorrelated sum of both noises, the conservative
choice. Control-region and fit noise reach our result only through replicas, so without them
the likelihood term has no noise budget and no threshold: it is not attributable. The record is
advisory input to ``check:attribution_above_noise``; it does not assert that a feature above
threshold has any particular physical cause.
"""
import math

from scipy.stats import chi2, norm

DEFAULT_ALPHA = 0.05
MEDIAN_SE = math.sqrt(math.pi / 2.0)
_STEP = 1e-5


def node_multiplier(n_nodes, alpha=DEFAULT_ALPHA):
    """Two-sided Sidak multiplier: noise alone crosses some node threshold with probability alpha."""
    if n_nodes < 1 or not 0.0 < alpha < 1.0:
        raise ValueError('node_multiplier needs at least one node and 0 < alpha < 1')
    per_node = 1.0 - (1.0 - alpha) ** (1.0 / n_nodes)
    return float(norm.isf(per_node / 2.0))


def scope_multiplier(alpha=DEFAULT_ALPHA):
    return float(norm.isf(alpha / 2.0))


def _bins(node):
    """(side, region index, bin index, variance) for every declared bin."""
    rows = []
    for r, region in enumerate(node['regions']):
        for b, w2 in enumerate(region['ours']['sumw2']):
            rows.append(('ours', r, b, float(w2)))
        for b, err in enumerate(region['reference']['staterror']):
            rows.append(('reference', r, b, float(err) ** 2))
    return rows


def _shifted(node, side, r, b, delta):
    regions = []
    for i, region in enumerate(node['regions']):
        if i != r:
            regions.append(region)
            continue
        yields = list(region[side]['yield'])
        yields[b] += delta
        regions.append({**region, side: {**region[side], 'yield': yields}})
    return {**node, 'regions': regions}


def propagated(node, term_fn):
    """Per-term propagated standard deviations, split into our side and the reference side."""
    base = term_fn(node)
    variance = {key: {'ours': 0.0, 'reference': 0.0} for key in base}
    for side, r, b, var in _bins(node):
        if var == 0.0:
            continue
        y = float(node['regions'][r][side]['yield'][b])
        h = _STEP * max(abs(y), math.sqrt(var), 1e-12)
        low = max(y - h, 0.0)  # a yield is never shifted below zero; one-sided at a zero yield
        up, down = term_fn(_shifted(node, side, r, b, h)), term_fn(_shifted(node, side, r, b, low - y))
        for key in base:
            if base[key] is None or up.get(key) is None or down.get(key) is None:
                continue
            slope = (up[key] - down[key]) / (y + h - low)
            variance[key][side] += slope * slope * var
    return {key: {side: math.sqrt(v) for side, v in sides.items()} for key, sides in variance.items()}, base


def _replica_sigma(node):
    """95% upper bound on the log-space SD of our result over its replicas, or None."""
    replicas = node.get('replicas')
    if not replicas:
        return None
    logs = [math.log(float(r['value'])) for r in replicas]
    n = len(logs)
    mean = sum(logs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in logs) / (n - 1))
    return sd * math.sqrt((n - 1) / chi2.ppf(0.05, n - 1))


def node_noise(node, term_fn, k_node):
    split, base = propagated(node, term_fn)
    sigma = {}
    for key, sides in split.items():
        if base[key] is None:
            continue
        sigma[key] = math.hypot(sides['ours'], sides['reference'])
    proxy = split['proxy']
    replica = _replica_sigma(node)
    if replica is None:
        # Our claim quantity responds to the same per-bin noise as its signal-region proxy; the
        # likelihood term's control-region and fit noise is unmeasured, so it gets no threshold.
        sigma['total'] = sigma['proxy']
        sigma.pop('likelihood', None)
    else:
        sigma['total'] = math.hypot(max(replica, proxy['ours']), proxy['reference'])
        sigma['likelihood'] = math.hypot(sigma['total'], sigma['proxy'])
    return {'id': node['id'], 'k_node': k_node, 'sigma': sigma,
            'threshold': {key: k_node * value for key, value in sigma.items()},
            'sigma_sources': {'bins': len(_bins(node)), 'replicas': len(node.get('replicas') or [])}}


def scope_threshold(sigmas, alpha=DEFAULT_ALPHA):
    """Threshold on a scope median from its nodes' standard deviations."""
    if not sigmas:
        return None
    rms = math.sqrt(sum(s * s for s in sigmas) / len(sigmas))
    return scope_multiplier(alpha) * MEDIAN_SE * rms / math.sqrt(len(sigmas))


def build(model, term_fn, alpha=DEFAULT_ALPHA):
    """The noise record of a residual model: per-node sigmas and thresholds, per-scope median thresholds."""
    nodes = model['nodes']
    k_node = node_multiplier(len(nodes), alpha)
    rows = [node_noise(node, term_fn, k_node) for node in nodes]
    keys = sorted({key for row in rows for key in row['sigma']})
    scopes = {}
    for key in keys:
        scope, _, term = key.rpartition(':') if ':' in key else ('all', '', key)
        sigmas = [row['sigma'][key] for row in rows if key in row['sigma']]
        entry = scopes.setdefault(scope, {'n_nodes': len(sigmas), 'median_threshold': {}})
        entry['median_threshold'][term] = scope_threshold(sigmas, alpha)
    return {'schema_version': 1, 'kind': 'residual-noise-model', 'alpha': alpha,
            'scope_multiplier': scope_multiplier(alpha), 'node_multiplier': k_node,
            'definition': ('linear propagation of our sumw2 and the reference staterror through each term; '
                           'our side of the total is floored by the 95% upper bound of the replica scatter '
                           'when replicas exist, and the likelihood term needs replicas; Sidak per-node and '
                           'median-standard-error per-scope thresholds at false-alarm alpha'),
            'nodes': rows, 'scopes': scopes}
