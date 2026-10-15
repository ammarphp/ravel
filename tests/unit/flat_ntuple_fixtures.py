"""Synthetic flat ROOT ntuples with the awkward features real analysis ntuples have.

One shared kit for every test that needs a flat-ntuple shape instead of a Delphes tree
(``columnar_fixtures.py`` writes only the Delphes layout). Everything is invented: tree,
prefixes, working-point names, trigger chains, dataset number and suffix.

Shapes written by ``write_flat_ntuple``:

- momenta in MeV, per-object jagged vectors that are *not* sorted in pT, index-aligned by a
  prefix: ``<prefix>_pt``, ``<prefix>_eta``, ``<prefix>_phi`` plus either ``<prefix>_e`` or
  ``<prefix>_m`` (an energy-only and a mass-only collection are written side by side);
- multi-part per-object fields under the same prefix: selection flags
  ``<prefix>_select_<wp>`` (int8, ROOT ``char``), scale factors ``<prefix>_effsf_<kind>``,
  trigger-match flags ``<prefix>_trigmatch_<chain>`` (int8), an integer tagger decision
  ``<prefix>_tagbin`` (int32) and a truth label ``<prefix>_truth_label`` (int32);
- a nominal suffix on some branches only (pt, energy or mass and scale factors; never
  eta, phi, flags or labels);
- event scalars: ``event_number`` (uint64), ``data_period`` (int32), one ``pass_<chain>``
  bool per chain, ``weight_mc``, ``weight_pileup`` and ``weight_extra_<name>`` for the
  names passed in ``extra_weights`` (so a file can have it and another not);
- missing transverse momentum as ``met_met``/``met_phi`` and/or ``met_px``/``met_py``, plus
  optional per-term recoil ``met_term_<term>_px``/``_py``;
- a bookkeeping histogram whose name embeds the invented dataset number, with the sum of
  weights in a declared (1-based) bin;
- a separate truth-particle collection ``truth_*`` with ``truth_m`` mass branches.

uproot writes jagged branches as counted C arrays (``int8_t[]``, ``float[]``), not as
``std::vector``. The readers treat both through the same jagged path, so these files
exercise the same code; the counter branches are named ``n_<prefix>``.
"""
from __future__ import annotations

import hashlib
import json
import math
import zlib
from dataclasses import dataclass
from pathlib import Path

import awkward as ak
import numpy as np
import uproot

DEFAULT_TREE = 'flat_tree'
DEFAULT_SUFFIX = '_NOMX'
DEFAULT_CHAINS = ('trig_alpha', 'trig_beta')
DEFAULT_DATASET_NUMBER = 987654
DEFAULT_SCOPE = 'synth_scope'
BOOKKEEPING_BIN = 2          # 1-based ROOT bin that holds the sum of weights
BOOKKEEPING_EDGES = [0.0, 1.0, 2.0, 3.0]


@dataclass(frozen=True)
class CollectionSpec:
    """One object collection. ``mass`` is ``'e'`` (energy branch) or ``'m'`` (mass branch)."""
    mass: str = 'e'
    mean: float = 2.0
    pt_scale: float = 40000.0                 # MeV, exponential scale of the pT spectrum
    mass_max: float = 15000.0                 # MeV, upper edge of the uniform mass spectrum
    flags: tuple = ('wpa',)                    # <prefix>_select_<wp>
    scale_factors: tuple = ()                  # <prefix>_effsf_<kind><suffix>
    trigger_match: tuple = ()                  # <prefix>_trigmatch_<chain>
    tagger: bool = False                       # <prefix>_tagbin
    truth_label: bool = True                   # <prefix>_truth_label
    dressed: bool = True                       # nominal suffix on pt and e/m and scale factors


def default_collections():
    return {
        'el': CollectionSpec(mass='e', mean=1.5, mass_max=0.511, flags=('wpa', 'wpb'), scale_factors=('reco', 'isol'),
                             trigger_match=('alpha',)),
        'mu': CollectionSpec(mass='m', mean=1.5, mass_max=105.7, flags=('wpa', 'wpb'), scale_factors=('reco',),
                             trigger_match=('alpha', 'beta')),
        'jet': CollectionSpec(mass='e', mean=4.0, flags=('wpa',), scale_factors=('jvt',), tagger=True),
    }


def _permute_unsorted(rng, counts, pt):
    """Shuffle objects within each event; make the first multi-object event not descending in pT."""
    order, forced = [], False
    start = 0
    for n in counts:
        idx = rng.permutation(n)
        if n >= 2 and not forced:
            if np.all(np.diff(pt[start:start + n][idx]) <= 0):
                idx = idx[::-1]
            forced = bool(np.any(np.diff(pt[start:start + n][idx]) > 0))
        order.append(idx + start)
        start += n
    return np.concatenate(order) if order else np.zeros(0, dtype=int)


def build_flat_arrays(*, events, seed, collections=None, nominal_suffix=DEFAULT_SUFFIX, extra_weights=(),
                      trigger_chains=DEFAULT_CHAINS, met_form='polar', met_terms=(), truth_particles=True,
                      period=1):
    """Return ``{branch name: numpy/awkward array}`` exactly as written (deterministic for ``seed``).

    ``met_form`` is ``'polar'`` (magnitude and phi), ``'cartesian'`` (px, py) or ``'both'``.
    """
    if not isinstance(events, int) or events < 1:
        raise ValueError('events must be a positive integer')
    if met_form not in ('polar', 'cartesian', 'both'):
        raise ValueError("met_form must be 'polar', 'cartesian' or 'both'")
    collections = default_collections() if collections is None else collections
    rng = np.random.default_rng(seed)
    sfx = nominal_suffix
    out = {}
    for prefix, spec in collections.items():
        if spec.mass not in ('e', 'm'):
            raise ValueError(f'{prefix}: mass must be "e" or "m"')
        counts = rng.poisson(spec.mean, events)
        counts[0] = max(int(counts[0]), 2)              # one multi-object event for the unsorted check
        total = int(counts.sum())
        pt = rng.exponential(spec.pt_scale, total) + 5000.0
        eta = rng.uniform(-2.5, 2.5, total)
        phi = rng.uniform(-math.pi, math.pi, total)
        mass = rng.uniform(0.0, spec.mass_max, total)
        energy = np.sqrt((pt * np.cosh(eta)) ** 2 + mass ** 2)
        perm = _permute_unsorted(rng, counts, pt)
        fields = {}
        suffix = sfx if spec.dressed else ''
        fields['pt' + suffix] = pt[perm].astype('f4')
        fields['eta'] = eta[perm].astype('f4')
        fields['phi'] = phi[perm].astype('f4')
        if spec.mass == 'e':
            fields['e' + suffix] = energy[perm].astype('f4')
        else:
            fields['m' + suffix] = mass[perm].astype('f4')
        for wp in spec.flags:
            fields[f'select_{wp}'] = (rng.random(total) < 0.7)[perm].astype('i1')
        for kind in spec.scale_factors:
            fields[f'effsf_{kind}' + suffix] = rng.normal(1.0, 0.03, total)[perm].astype('f4')
        for chain in spec.trigger_match:
            fields[f'trigmatch_{chain}'] = (rng.random(total) < 0.5)[perm].astype('i1')
        if spec.tagger:
            fields['tagbin'] = rng.integers(0, 6, total)[perm].astype('i4')
        if spec.truth_label:
            fields['truth_label'] = rng.integers(0, 4, total)[perm].astype('i4')
        out[prefix] = ak.zip({k: ak.unflatten(v, counts) for k, v in fields.items()})
    if truth_particles:
        counts = rng.poisson(5.0, events)
        counts[0] = max(int(counts[0]), 2)
        total = int(counts.sum())
        tpt = rng.exponential(60000.0, total) + 1000.0
        out['truth'] = ak.zip({k: ak.unflatten(v, counts) for k, v in {
            'pt': tpt.astype('f4'), 'eta': rng.uniform(-4, 4, total).astype('f4'),
            'phi': rng.uniform(-math.pi, math.pi, total).astype('f4'),
            'm': rng.uniform(0.0, 175000.0, total).astype('f4'),
            'pdgid': rng.choice([-13, -11, 11, 13, 21, 22, 5, -5], total).astype('i4'),
            'status': rng.integers(1, 4, total).astype('i4')}.items()})
    scalars = {'event_number': (np.arange(events, dtype='u8') + np.uint64(rng.integers(1, 10 ** 6))),
               'data_period': np.full(events, int(period), dtype='i4')}
    for chain in trigger_chains:
        scalars[f'pass_{chain}'] = rng.random(events) < 0.6
    scalars['weight_mc'] = rng.choice([1.0, 0.5, 2.0, -1.0], events).astype('f4')
    scalars['weight_pileup'] = rng.normal(1.0, 0.1, events).astype('f4')
    for name in extra_weights:
        scalars[f'weight_extra_{name}'] = rng.normal(1.0, 0.05, events).astype('f4')
    met = rng.exponential(50000.0, events)
    met_phi = rng.uniform(-math.pi, math.pi, events)
    if met_form in ('polar', 'both'):
        scalars['met_met'] = met.astype('f4')
        scalars['met_phi'] = met_phi.astype('f4')
    if met_form in ('cartesian', 'both'):
        scalars['met_px'] = (met * np.cos(met_phi)).astype('f4')
        scalars['met_py'] = (met * np.sin(met_phi)).astype('f4')
    for term in met_terms:
        px, py = rng.normal(0.0, 20000.0, events), rng.normal(0.0, 20000.0, events)
        scalars[f'met_term_{term}_px'] = px.astype('f4')
        scalars[f'met_term_{term}_py'] = py.astype('f4')
    out.update(scalars)
    return out


def _types(arrays):
    return {k: (v.type if isinstance(v, ak.Array) else ak.Array(v).type) for k, v in arrays.items()}


def write_flat_ntuple(path, *, events=20, seed=1, collections=None, nominal_suffix=DEFAULT_SUFFIX, tree=DEFAULT_TREE,
                      extra_weights=(), bookkeeping=None, trigger_chains=DEFAULT_CHAINS, met_form='polar',
                      met_terms=(), truth_particles=True, period=1):
    """Write one synthetic file and return its pinned record.

    ``bookkeeping`` is ``None`` for the default (invented dataset number, sum of weights taken
    from the written ``weight_mc``), ``False`` for no histogram, or a dict with any of
    ``dataset_number``, ``sum_weights``, ``name`` (a ``{dsid}`` template).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = build_flat_arrays(events=events, seed=seed, collections=collections, nominal_suffix=nominal_suffix,
                               extra_weights=extra_weights, trigger_chains=trigger_chains, met_form=met_form,
                               met_terms=met_terms, truth_particles=truth_particles, period=period)
    sum_weights = float(arrays['weight_mc'].astype('f8').sum())
    hist = None
    if bookkeeping is not False:
        cfg = dict(bookkeeping or {})
        dsid = int(cfg.get('dataset_number', DEFAULT_DATASET_NUMBER))
        sumw = float(cfg.get('sum_weights', sum_weights))
        hist = {'name': str(cfg.get('name', 'Bookkeeper_{dsid}_1_nomx')).format(dsid=dsid), 'dataset_number': dsid,
                'bin': BOOKKEEPING_BIN, 'sum_weights': sumw}
    with uproot.recreate(path) as f:
        f.mktree(tree, _types(arrays), counter_name=lambda c: 'n_' + c, field_name=lambda o, i: f'{o}_{i}')
        f[tree].extend(arrays)
        if hist is not None:
            counts = np.array([float(events), hist['sum_weights'], float((arrays['weight_mc'].astype('f8') ** 2).sum())])
            f[hist['name']] = (counts, np.array(BOOKKEEPING_EDGES))
    raw = path.read_bytes()
    suffixed = sorted(n for n in _branch_names(arrays) if n.endswith(nominal_suffix)) if nominal_suffix else []
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
            'adler32': f'{zlib.adler32(raw):08x}', 'tree': tree, 'entries': events, 'seed': seed,
            'nominal_suffix': nominal_suffix, 'suffixed_branches': suffixed, 'bookkeeping': hist,
            'sum_weights': sum_weights, 'extra_weights': list(extra_weights)}


def _branch_names(arrays):
    for k, v in arrays.items():
        if isinstance(v, ak.Array) and v.fields:
            for field in v.fields:
                yield f'{k}_{field}'
        else:
            yield k


def fake_replica_catalogue(root, container, members, *, scope=DEFAULT_SCOPE, host='fixture.example.invalid'):
    """Write a replica catalogue JSON for an invented container and return its path.

    ``members`` maps member-dataset name to a list of records from ``write_flat_ntuple``.
    The file carries the nested view (container -> datasets -> files) and the supplied-listing
    view (``files`` by dataset DID, ``replicas`` by file DID) that ``ravel ntuples resolve`` reads.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    nested, files, replicas = [], {}, {}
    for dataset, records in members.items():
        did = f'{scope}:{dataset}'
        rows = []
        for i, rec in enumerate(records):
            name = Path(rec['path']).name
            uri = f'root://{host}/{rec["path"]}'
            guid = hashlib.sha256(f'{dataset}/{name}/{rec["sha256"]}'.encode()).hexdigest()[:32].upper()
            rows.append({'scope': scope, 'name': name, 'guid': guid, 'adler32': rec['adler32'],
                         'bytes': rec['size'], 'events': rec['entries']})
            replicas[f'{scope}:{name}'] = [uri]
        files[did] = rows
        nested.append({'did': did, 'files': [dict(r, uri=replicas[f"{scope}:{r['name']}"][0]) for r in rows]})
    doc = {'container': {'did': f'{scope}:{container}', 'datasets': nested}, 'files': files, 'replicas': replicas}
    out = root / f'{container}.replicas.json'
    out.write_text(json.dumps(doc, indent=1, sort_keys=True))
    return out
