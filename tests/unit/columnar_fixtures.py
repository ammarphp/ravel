"""Tiny synthetic Delphes-shaped files and a generic multilepton recipe for columnar tests."""
import copy
import math

import awkward as ak
import numpy as np
import uproot

DELPHES_FIELDS = {
    'Electron': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Muon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Charge': 'i4', 'IsolationVar': 'f4'},
    'Photon': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'E': 'f4', 'IsolationVar': 'f4'},
    'Jet': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'BTag': 'i4', 'TauTag': 'i4', 'Charge': 'i4'},
    'EFlowTrack': {'PT': 'f4', 'Eta': 'f4', 'Phi': 'f4', 'Mass': 'f4', 'Charge': 'i4', 'PID': 'i4'},
}


def random_events(n, seed=1):
    rng = np.random.default_rng(seed)
    events = []
    for _ in range(n):
        ev = {}
        for name, mean in (('Electron', 1.2), ('Muon', 1.2), ('Jet', 3.0), ('Photon', 0.5), ('EFlowTrack', 4.0)):
            k = rng.poisson(mean)
            objs = []
            for _ in range(k):
                o = {'PT': float(rng.exponential(40) + 5), 'Eta': float(rng.uniform(-3, 3)),
                     'Phi': float(rng.uniform(-math.pi, math.pi))}
                if name in ('Electron', 'Muon'):
                    o.update(Charge=int(rng.choice([-1, 1])), IsolationVar=float(rng.exponential(0.1)))
                if name == 'Jet':
                    o.update(Mass=float(rng.uniform(0, 20)), BTag=int(rng.random() < 0.3), TauTag=int(rng.random() < 0.1),
                             Charge=int(rng.choice([-1, 0, 1])))
                if name == 'Photon':
                    o.update(E=o['PT'] * math.cosh(o['Eta']), IsolationVar=float(rng.exponential(0.1)))
                if name == 'EFlowTrack':
                    o.update(Mass=0.13957, Charge=int(rng.choice([-1, 1])), PID=211)
                objs.append(o)
            objs.sort(key=lambda o: -o['PT'])
            ev[name] = objs
        ev['MET'] = float(rng.exponential(60))
        ev['METPhi'] = float(rng.uniform(-math.pi, math.pi))
        ev['Weight'] = float(rng.choice([1.0, 0.5, 2.0]))
        events.append(ev)
    return events


def write_delphes(path, events):
    data = {}
    for name, fields in DELPHES_FIELDS.items():
        rows = [ev.get(name, []) for ev in events]
        counts = [len(r) for r in rows]
        data[name] = ak.zip({f: ak.unflatten(np.array([o.get(f, 0) for r in rows for o in r], dtype=dt), counts)
                             for f, dt in fields.items()})
    ones = [1] * len(events)
    data['MissingET'] = ak.zip({'MET': ak.unflatten(np.array([ev['MET'] for ev in events], 'f4'), ones),
                                'Phi': ak.unflatten(np.array([ev['METPhi'] for ev in events], 'f4'), ones)})
    data['Event'] = ak.zip({'Weight': ak.unflatten(np.array([ev.get('Weight', 1.0) for ev in events], 'f4'), ones),
                            'Number': ak.unflatten(np.arange(len(events), dtype='i8'), ones)})
    with uproot.recreate(path) as f:
        f.mktree('Delphes', {k: v.type for k, v in data.items()},
                 counter_name=lambda c: c + '_size', field_name=lambda o, i: o + '.' + i)
        f['Delphes'].extend(data)
    return path


Z_MASS = 91.1876

RECIPE = {
    'schema_version': 1,
    'kind': 'columnar-analysis-recipe',
    'name': 'generic multilepton plus missing momentum selection',
    'description': 'Synthetic test selection with three leptons, an on-Z pair and missing momentum.',
    'weights': {'generator': 'weight', 'factors': []},
    'objects': [
        {'name': 'electrons', 'from': 'Electron', 'select': 'pt > 10 and abs(eta) < 2.47'},
        {'name': 'muons', 'from': 'Muon', 'select': 'pt > 10 and abs(eta) < 2.5'},
        {'name': 'jets', 'from': 'Jet', 'select': 'pt > 20 and abs(eta) < 2.8'},
        {'name': 'tracks', 'from': 'EFlowTrack', 'select': 'pt > 5'},
        {'overlap_removal': {'remove': 'jets', 'near': 'electrons', 'dr': 0.2}},
        {'overlap_removal': {'remove': 'electrons', 'near': 'jets', 'dr': 0.4}},
        {'overlap_removal': {'remove': 'muons', 'near': 'jets', 'dr': 0.4}},
        {'name': 'bjets', 'from_object': 'jets', 'select': 'btag == 1'},
        {'name': 'leptons', 'union': ['electrons', 'muons']},
        {'pair_split': {'from': 'leptons', 'charge': 'opposite', 'flavour': 'same', 'choose': 'closest-to-mass',
                        'target_mass': Z_MASS, 'source': 'PDG Z boson mass', 'pair': 'z_leptons', 'rest': 'other_leptons'}},
    ],
    'observables': [
        {'name': 'n_leptons', 'op': 'count', 'collection': 'leptons'},
        {'name': 'n_bjets', 'op': 'count', 'collection': 'bjets'},
        {'name': 'met', 'op': 'met', 'unit': 'GeV', 'label': 'Missing transverse momentum'},
        {'name': 'ht', 'op': 'scalar_sum', 'collections': ['jets'], 'unit': 'GeV'},
        {'name': 'mll', 'op': 'ossf_pair_mass', 'collection': 'leptons', 'choose': 'closest-to-mass',
         'target_mass': Z_MASS, 'source': 'PDG Z boson mass', 'unit': 'GeV'},
        {'name': 'mt_third', 'op': 'mt', 'object': 'other_leptons[0]', 'unit': 'GeV'},
        {'name': 'lead_lepton_pt', 'op': 'field', 'object': 'leptons[0]', 'field': 'pt', 'unit': 'GeV'},
        {'name': 'min_dphi', 'op': 'min_delta_phi_met', 'collection': 'jets', 'max_objects': 4},
        {'name': 'mt2ll', 'op': 'mt2', 'assignments': [[['leptons[0]'], ['leptons[1]']]], 'invisible_mass': 0.0,
         'source': 'massless invisible hypothesis'},
        {'name': 'met_significance', 'op': 'expr', 'expr': 'met / sqrt(ht)'},
    ],
    'regions': [
        {'name': 'two leptons', 'cuts': [{'name': 'at least two leptons', 'expr': 'n_leptons >= 2'}]},
        {'name': 'three leptons on Z', 'base': 'two leptons',
         'cuts': [{'name': 'three leptons', 'expr': 'n_leptons >= 3'},
                  {'name': 'on-Z pair', 'expr': '76 < mll < 106'},
                  {'name': 'missing momentum', 'expr': 'met > 30'}]},
    ],
    'histograms': [
        {'name': 'met in three-lepton region', 'region': 'three leptons on Z', 'observable': 'met',
         'edges': [30, 60, 120, 200], 'unit': 'GeV', 'label': 'Missing transverse momentum',
         'normalization': 'yield', 'overflow': 'separate', 'underflow': 'separate'},
        {'name': 'dilepton mass', 'region': 'two leptons', 'observable': 'mll',
         'binning': {'uniform': {'low': 0, 'high': 200, 'bins': 8}}, 'unit': 'GeV',
         'label': 'Same-flavour opposite-charge dilepton mass', 'normalization': 'yield'},
    ],
}


def recipe(**changes):
    doc = copy.deepcopy(RECIPE)
    doc.update(changes)
    return doc


# ---------------------------------------------------------------- independent per-event reference
def _dr(a, b):
    dphi = abs((a['Phi'] - b['Phi'] + math.pi) % (2 * math.pi) - math.pi)
    return math.hypot(a['Eta'] - b['Eta'], dphi)


def _p4(o, mass):
    pt, eta, phi = o['PT'], o['Eta'], o['Phi']
    px, py, pz = pt * math.cos(phi), pt * math.sin(phi), pt * math.sinh(eta)
    return px, py, pz, math.sqrt(px * px + py * py + pz * pz + mass * mass)


def reference_event(ev):
    """Plain-Python evaluation of the recipe's selection for one event (float32 inputs)."""
    f32 = lambda x: float(np.float32(x))
    def cast(objs):
        return [{k: (f32(v) if isinstance(v, float) else v) for k, v in o.items()} for o in objs]
    ele = [o for o in cast(ev['Electron']) if o['PT'] > 10 and abs(o['Eta']) < 2.47]
    mu = [o for o in cast(ev['Muon']) if o['PT'] > 10 and abs(o['Eta']) < 2.5]
    jets = [o for o in cast(ev['Jet']) if o['PT'] > 20 and abs(o['Eta']) < 2.8]
    jets = [j for j in jets if not any(_dr(j, e) < 0.2 for e in ele)]
    ele = [e for e in ele if not any(_dr(e, j) < 0.4 for j in jets)]
    mu = [m for m in mu if not any(_dr(m, j) < 0.4 for j in jets)]
    leptons = sorted([dict(o, flavour=11, mass=0.00051099895) for o in ele] + [dict(o, flavour=13, mass=0.1056583755) for o in mu],
                     key=lambda o: -o['PT'])
    best, best_pair = None, None
    for i in range(len(leptons)):
        for j in range(i + 1, len(leptons)):
            a, b = leptons[i], leptons[j]
            if a['flavour'] == b['flavour'] and a['Charge'] * b['Charge'] < 0:
                v = [x + y for x, y in zip(_p4(a, a['mass']), _p4(b, b['mass']))]
                m = math.sqrt(max(v[3] ** 2 - v[0] ** 2 - v[1] ** 2 - v[2] ** 2, 0))
                if best is None or abs(m - Z_MASS) < abs(best - Z_MASS):
                    best, best_pair = m, (i, j)
    met = f32(ev['MET'])
    weight = f32(ev['Weight'])
    two = len(leptons) >= 2
    three = two and len(leptons) >= 3 and best is not None and 76 < best < 106 and met > 30
    return {'weight': weight, 'two': two, 'three': three, 'met': met, 'mll': best}
