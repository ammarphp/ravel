"""Fixed reconstructed-object selections using the preserved native SA primitives.

Every input event survives into the decision trace, including unselected events.
The adapter never assigns detector flags or treats overlapping regions as independent.
"""
import math
from pathlib import Path

from ravel.workflow.state_io import read_json, atomic_json
from ravel.workflow.science import regular


def number(value, name, *, nonnegative=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f'{name} must be finite' + (' and nonnegative' if nonnegative else ''))
    return float(value)


def selection_spec(s, contract):
    from ravel.physics.native_sa_generic import OPS
    allowed = {'name', 'lumi_fb', 'objects', 'overlap_removal', 'signal', 'btag', 'regions'}
    if not isinstance(s, dict) or set(s) - allowed or not {'name', 'objects', 'overlap_removal', 'signal', 'regions'} <= s.keys():
        raise ValueError('invalid selection fields')
    if set(s['objects']) != {'electron', 'muon', 'jet'} or set(s['signal']) != set(s['objects']):
        raise ValueError('declare baseline and signal definitions for electron, muon and jet')
    for collection, cuts in list(s['objects'].items()) + list(s['signal'].items()):
        if set(cuts) != {'pt', 'eta', 'id'}:
            raise ValueError('each object definition requires exactly pt, eta, id')
        number(cuts['pt'], 'object pt', nonnegative=True)
        if number(cuts['eta'], 'object eta') <= 0:
            raise ValueError('eta acceptance must be positive')
        if type(cuts['id']) is not int or not 0 <= cuts['id'] < 2**30:
            raise ValueError('object ID mask must be a nonnegative supported bit mask')
        mask = sum(contract['flags'][collection].values())
        if cuts['id'] & ~mask:
            raise ValueError('selection requests an undeclared object ID bit')
    for step in s['overlap_removal']:
        if set(step) != {'remove', 'near', 'dR'} or step['remove'] not in s['objects'] or step['near'] not in s['objects'] or step['remove'] == step['near']:
            raise ValueError('invalid ordered overlap-removal operation')
        if number(step['dR'], 'overlap radius') <= 0:
            raise ValueError('overlap radius must be positive')
    variables = {'nEl', 'nMu', 'nLep', 'nJet', 'nBjet', 'MET', 'HT', 'meff', 'mTlep', 'mll', 'dphiMin',
                 'jet1pt', 'jet2pt', 'jet3pt', 'jet4pt', 'lep1pt', 'lep2pt', 'mjj'}
    if not s['regions']:
        raise ValueError('at least one explicitly named region required')
    seen = set()
    for region in s['regions']:
        if set(region) != {'name', 'cuts'} or not isinstance(region['name'], str) or not region['name'] or region['name'] in seen or not region['cuts']:
            raise ValueError('regions require unique names and explicit cuts')
        seen.add(region['name'])
        for cut in region['cuts']:
            if set(cut) != {'var', 'op', 'val'} or cut['var'] not in variables or cut['op'] not in OPS:
                raise ValueError('unsupported selection variable or operation')
            number(cut['val'], 'cut threshold')
            if cut['var'] == 'nBjet' and 'btag' not in s:
                raise ValueError('nBjet selection requires an explicit b-tag definition')
    if 'btag' in s:
        b = s['btag']
        if set(b) != {'idbit', 'pt', 'eta'} or type(b['idbit']) is not int or b['idbit'] <= 0 or b['idbit'] & ~sum(contract['flags']['jet'].values()):
            raise ValueError('b-tag working point must have explicit nonzero declared flags')
        number(b['pt'], 'b-tag pt', nonnegative=True)
        if number(b['eta'], 'b-tag eta') <= 0:
            raise ValueError('b-tag eta must be positive')
    return s


def object_contract(c):
    if not isinstance(c, dict) or set(c) != {'schema_version', 'level', 'source', 'energy_unit', 'flags', 'response_evidence', 'weight_names'} or c['schema_version'] != 1:
        raise ValueError('invalid reconstructed-object contract')
    if c['level'] != 'reconstructed' or c['energy_unit'] != 'GeV' or not isinstance(c['source'], str) or not c['source'].strip():
        raise ValueError('reconstructed objects require explicit GeV units and source')
    if set(c['flags']) != {'electron', 'muon', 'jet'}:
        raise ValueError('ID semantics needed for all object collections')
    for flags in c['flags'].values():
        if not isinstance(flags, dict) or any(not isinstance(k, str) or not k for k in flags):
            raise ValueError('invalid flag labels')
        vals = list(flags.values())
        if len(set(vals)) != len(vals) or any(type(v) is not int or not 0 < v < 2**30 or v & (v - 1) for v in vals):
            raise ValueError('working-point flags must be distinct single bits; aliases are forbidden')
    names = c['weight_names']
    if not names or len(names) != len(set(names)) or any(not isinstance(w, str) or not w for w in names):
        raise ValueError('unique explicit weight names required')
    if not isinstance(c['response_evidence'], list) or any(not isinstance(p, str) or not p for p in c['response_evidence']):
        raise ValueError('response_evidence must be an explicit list of supplied paths')
    return c


def run(task, base, out):
    from ravel.physics.native_sa_generic import select_event, passes
    from ravel.physics.sa_native_core import Obj
    contract = object_contract(read_json(regular(task['object_contract'], base)))
    spec = selection_spec(read_json(regular(task['selection'], base)), contract)
    events = read_json(regular(task['events'], base))
    if not isinstance(events, list) or not events:
        raise ValueError('events must be a nonempty JSON array')
    names, regions = contract['weight_names'], [r['name'] for r in spec['regions']]
    groups, seen, traces, totals = {}, set(), [], [0.] * len(names)
    raw = {r: 0 for r in regions}
    overlap = {r: {q: 0 for q in regions} for r in regions}
    for event in events:
        if set(event) != {'event_id', 'group_id', 'weights', 'objects', 'met'}:
            raise ValueError('invalid reconstructed event fields')
        eid, gid = event['event_id'], event['group_id']
        if not isinstance(eid, str) or not eid or eid in seen or not isinstance(gid, str) or not gid:
            raise ValueError('events need unique stable IDs and explicit independent-group IDs')
        seen.add(eid)
        if set(event['weights']) != set(names):
            raise ValueError('missing or extra event weights')
        weights = [number(event['weights'][w], 'weight') for w in names]
        objects = {}
        if set(event['objects']) != {'electron', 'muon', 'jet'}:
            raise ValueError('all reconstructed collections must be explicitly present')
        for typ, name in enumerate(('electron', 'muon', 'jet')):
            collection = event['objects'][name]
            if not isinstance(collection, list):
                raise ValueError('object collection must be a list')
            objects[name] = []
            for obj in collection:
                if set(obj) != {'pt', 'eta', 'phi', 'mass', 'charge', 'idbits'}:
                    raise ValueError('object kinematics, charge and ID flags must all be explicit')
                for field in ('pt', 'mass'):
                    number(obj[field], field, nonnegative=True)
                for field in ('eta', 'phi'):
                    number(obj[field], field)
                if abs(obj['eta']) > 20 or abs(obj['phi']) > math.pi:
                    raise ValueError('object eta/phi outside supported numerical domain')
                if type(obj['charge']) is not int or obj['charge'] not in (-1, 0, 1):
                    raise ValueError('object charge must be -1, 0 or 1')
                mask = sum(contract['flags'][name].values())
                if type(obj['idbits']) is not int or obj['idbits'] < 0 or obj['idbits'] & ~mask:
                    raise ValueError('object carries undeclared ID flags')
                objects[name].append(Obj(obj['pt'], obj['eta'], obj['phi'], obj['mass'], obj['charge'], obj['idbits'], typ))
        if set(event['met']) != {'pt', 'phi'}:
            raise ValueError('MET requires pt and phi')
        mpt = number(event['met']['pt'], 'MET', nonnegative=True)
        phi = number(event['met']['phi'], 'MET phi')
        if abs(phi) > math.pi:
            raise ValueError('MET phi outside radians domain')
        values = select_event(spec, objects['electron'], objects['muon'], objects['jet'], Obj(mpt, 0, phi, 0, 0, 0, 0))
        if any(not math.isfinite(v) for v in values.values()):
            raise ValueError('nonfinite selection observable')
        # The preserved kernel uses zero/sentinel values when an object does not
        # exist. They are not measurable masses/angles and must not pass a cut.
        requirements = {'mll': ('nLep', 2), 'mjj': ('nJet', 2), 'mTlep': ('nLep', 1), 'dphiMin': ('nJet', 1)}
        requirements.update({f'jet{i}pt': ('nJet', i) for i in range(1, 5)})
        requirements.update({f'lep{i}pt': ('nLep', i) for i in range(1, 3)})
        unavailable = {v for v, (count, minimum) in requirements.items() if values[count] < minimum}
        selected = [r['name'] for r in spec['regions'] if not any(c['var'] in unavailable for c in r['cuts']) and passes(r, values)]
        values.update({v: None for v in unavailable})
        traces.append({'event_id': eid, 'group_id': gid, 'regions': selected, 'variables': values, 'weights': event['weights']})
        g = groups.setdefault(gid, [[0.] * len(regions) for _ in names])
        for r in selected:
            raw[r] += 1
            for q in selected:
                overlap[r][q] += 1
            for i, w in enumerate(weights):
                g[i][regions.index(r)] += w
        totals = [a+b for a, b in zip(totals, weights)]
    yields = {w: [math.fsum(g[i][j] for g in groups.values()) for j in range(len(regions))] for i, w in enumerate(names)}
    covariance = {w: [[math.fsum(g[i][j] * g[i][k] for g in groups.values()) for k in range(len(regions))]
                      for j in range(len(regions))] for i, w in enumerate(names)}
    comparison = {'performed': False, 'matched_events': 0, 'mismatches': []}
    if 'reference' in task:
        ref = read_json(regular(task['reference'], base))
        if set(ref) != {'source', 'events'} or not isinstance(ref['source'], str) or not ref['source'].strip():
            raise ValueError('reference decisions require source provenance')
        expected = {}
        for row in ref['events']:
            if set(row) != {'event_id', 'regions'} or row['event_id'] in expected or len(row['regions']) != len(set(row['regions'])) or set(row['regions']) - set(regions):
                raise ValueError('invalid or duplicate reference event decisions')
            expected[row['event_id']] = set(row['regions'])
        if set(expected) != seen:
            raise ValueError('reference event population differs, including rejected events')
        bad = [t['event_id'] for t in traces if set(t['regions']) != expected[t['event_id']]]
        comparison = {'performed': True, 'source': ref['source'], 'matched_events': len(traces) - len(bad), 'mismatches': bad}
    out = Path(out)
    atomic_json(out / 'decisions.json', traces)
    result = {'status': 'failed' if comparison['mismatches'] else 'passed', 'physics_validated': False,
              'scope': 'Declared reconstructed-object selection and optional same-event decision agreement',
              'events': len(events), 'independent_groups': len(groups), 'region_names': regions,
              'weight_names': names, 'sumw_all_events': totals, 'yields': yields, 'covariance': covariance,
              'raw_selected': raw, 'region_overlap_counts': overlap, 'reference_comparison': comparison,
              'response_evidence_supplied': len(contract['response_evidence']),
              'limitations': ['Object flags and efficiencies are supplied, not calibrated by this adapter.',
                  'Region covariance is conditional Poisson group MC covariance, not experimental background covariance.',
                  'Decision agreement does not establish detector response or paper reproduction.']}
    if 'mapping' in task:
        from ravel.physics.region_mapping import apply_mapping
        result['likelihood_mapping'] = apply_mapping(read_json(regular(task['mapping'], base)), result, base, out)
    return result
