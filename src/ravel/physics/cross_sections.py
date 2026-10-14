"""Signal cross sections from pinned published tables under an explicitly selected convention.

The registry (``data/cross_sections/registry.json``) lists the LHC SUSY Cross
Section Working Group tables (NNLL-fast and Resummino) with their production
state basis, collision energy, perturbative order, PDF set, scale choice,
source URL, citation and sha256. A request names the basis, the energy and the
convention (order, PDF, scale). The service then:

* returns the published value at a node, or interpolates log sigma linearly in
  log mass between nodes (bilinear in the log masses on two-dimensional grids);
* never extrapolates and never substitutes another convention, order or flat
  correction factor when the selected table is missing;
* rescales by a declared number of degenerate states only where the table
  records the physics rule that allows it;
* sums charge-conjugate states only from tables of the same convention.

An MG5-computed cross section is a separate source with its own convention
(``mg5_record``); a correction factor between two records is accepted only
when they describe the same basis, energy, masses, charge and state count.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from ravel.paths import package_data_path

ORDERS = ('LO', 'NLO', 'NLO+NLL', 'NNLO+NNLL', 'aNNLO+NNLL')
AS_PUBLISHED = 'as-published'
SCOPE = 'Published reference cross sections under an explicitly selected convention'
LIMITATIONS = [
    'Values are the published table numbers; interpolation is log-log between nodes and never extrapolates.',
    'The table describes its own simplified spectrum (decoupled states, degeneracies); applying it to another '
    'spectrum is a declared assumption of the request.',
]


class ConventionUnavailable(ValueError):
    """The selected basis, energy and convention have no pinned table."""


_REGISTRY = None


def registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = json.loads(package_data_path('cross_sections', 'registry.json').read_text())
    return _REGISTRY


def table_path(entry):
    return package_data_path('cross_sections', *entry['file'].split('/'))


def table_entry(table_id):
    for entry in registry()['tables']:
        if entry['id'] == table_id:
            return entry
    raise ValueError(f'unknown cross-section table {table_id!r}')


def load_table(entry):
    raw = table_path(entry).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry['sha256']:
        raise RuntimeError(f'pinned table {entry["file"]} changed (sha256 {digest} != {entry["sha256"]})')
    return json.loads(raw)


def verify_registry():
    failures = []
    for entry in registry()['tables']:
        try:
            load_table(entry)
        except (OSError, RuntimeError, ValueError) as exc:
            failures.append({'id': entry['id'], 'error': str(exc)})
    return {'passed': not failures, 'tables': len(registry()['tables']), 'failures': failures}


# ------------------------------------------------------------------ fetch

def _download(url):
    import ssl
    import urllib.request
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    request = urllib.request.Request(url, headers={'User-Agent': 'ravel-hep'})
    with urllib.request.urlopen(request, timeout=30, context=context) as response:
        return response.read()


def fetch(table_id, destination):
    """Download one pinned table from its recorded URL and verify its sha256; fail loudly."""
    entry = table_entry(table_id)
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    try:
        raw = _download(entry['source_url'])
    except Exception as exc:  # network, TLS or HTTP failure: no fallback
        raise RuntimeError(f'could not fetch {entry["source_url"]}: {exc}') from exc
    digest = hashlib.sha256(raw).hexdigest()
    if digest != entry['sha256']:
        raise RuntimeError(f'fetched bytes differ from the pinned sha256 ({digest} != {entry["sha256"]})')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return {'id': table_id, 'path': str(destination), 'sha256': digest, 'source_url': entry['source_url']}


# ------------------------------------------------------------- interpolation

def _key_value(key):
    return float(str(key).replace('p', '.'))


def _node_value(node):
    if not isinstance(node, dict) or 'xsec_pb' not in node:
        return None
    value = node['xsec_pb']
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    return node


def _uncertainty(node):
    sigma = node['xsec_pb']
    if 'unc_up_pb' in node or 'unc_down_pb' in node:
        up, down = abs(node.get('unc_up_pb', 0.0)), abs(node.get('unc_down_pb', 0.0))
    elif 'unc_pb' in node:
        up = down = abs(node['unc_pb'])
    else:
        up = down = None
    rel = {'relative_up': None if up is None else up / sigma, 'relative_down': None if down is None else down / sigma}
    for name in ('scale', 'pdf'):
        if f'unc_{name}_up_pb' in node:
            rel[f'relative_{name}_up'] = abs(node[f'unc_{name}_up_pb']) / sigma
            rel[f'relative_{name}_down'] = abs(node[f'unc_{name}_down_pb']) / sigma
    return rel


def _bracket(keys, value, label):
    values = sorted((_key_value(k), k) for k in keys)
    if not values:
        raise ValueError(f'empty grid for {label}')
    for v, k in values:
        if math.isclose(v, value, rel_tol=0, abs_tol=1e-9):
            return [(v, k)], 0.0
    if value < values[0][0] or value > values[-1][0]:
        raise ValueError(f'{label} = {value:g} is outside the table range '
                         f'{values[0][0]:g}..{values[-1][0]:g}; no extrapolation')
    for (v0, k0), (v1, k1) in zip(values, values[1:]):
        if v0 < value < v1:
            if v0 <= 0:
                raise ValueError(f'nonpositive {label} node; log interpolation undefined')
            return [(v0, k0), (v1, k1)], (math.log(value) - math.log(v0)) / (math.log(v1) - math.log(v0))
    raise ValueError(f'could not bracket {label} = {value:g}')


def _combine(nodes, weights):
    """Log-linear combination of sigma and linear combination of relative uncertainties."""
    log_sigma = sum(w * math.log(n['xsec_pb']) for n, w in zip(nodes, weights))
    sigma = math.exp(log_sigma)
    rels = [_uncertainty(n) for n in nodes]
    combined = {}
    for key in rels[0]:
        values = [r.get(key) for r in rels]
        combined[key] = None if any(v is None for v in values) else sum(w * v for v, w in zip(values, weights))
    return sigma, combined


def interpolate(entry, data, masses):
    names = [p['name'] for p in sorted(entry['parameters'], key=lambda p: p['key_level'])]
    if set(masses) != set(names):
        raise ValueError(f'basis {entry["basis"]} needs masses {names}; got {sorted(masses)}')
    for name in names:
        value = masses[name]
        if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'mass {name} must be a positive finite number')
    if len(names) == 1:
        points, f = _bracket(data, float(masses[names[0]]), names[0])
        nodes = [_node_value(data[k]) for _, k in points]
        if any(n is None for n in nodes):
            raise ValueError('the bracketing table node is empty or nonpositive; no interpolation across it')
        if len(nodes) == 1:
            return nodes[0]['xsec_pb'], _uncertainty(nodes[0]), 'exact node'
        sigma, rel = _combine(nodes, [1.0 - f, f])
        return sigma, rel, f'log-log between {points[0][0]:g} and {points[1][0]:g}'
    outer, outer_f = _bracket(data, float(masses[names[0]]), names[0])
    corners, weights, description = [], [], []
    for i, (ov, ok) in enumerate(outer):
        inner_data = data[ok]
        try:
            inner, inner_f = _bracket(inner_data, float(masses[names[1]]), names[1])
        except ValueError as exc:
            raise ValueError(f'the published grid has no rectangle around the request: {exc}') from exc
        wo = 1.0 if len(outer) == 1 else (1.0 - outer_f if i == 0 else outer_f)
        for j, (iv, ik) in enumerate(inner):
            wi = 1.0 if len(inner) == 1 else (1.0 - inner_f if j == 0 else inner_f)
            node = _node_value(inner_data[ik])
            if node is None:
                raise ValueError('a grid corner is empty or nonpositive; no interpolation across it')
            corners.append(node); weights.append(wo * wi); description.append(f'({ov:g},{iv:g})')
    if len(corners) == 1:
        return corners[0]['xsec_pb'], _uncertainty(corners[0]), 'exact node'
    if len(corners) not in (2, 4):
        raise ValueError('incomplete grid rectangle')
    sigma, rel = _combine(corners, weights)
    return sigma, rel, 'log-bilinear over ' + ' '.join(description)


# ------------------------------------------------------------------ lookup

def _pdf_matches(requested, entry):
    pdf = entry['convention']['pdf']
    if requested == AS_PUBLISHED:
        return True
    return pdf is not None and requested.lower() in pdf.lower()


def _scale_matches(requested, entry):
    scale = entry['convention']['scale']
    return requested == AS_PUBLISHED or (scale is not None and requested.lower() == scale.lower())


def _describe(entry):
    c = entry['convention']
    return (f'{entry["id"]}: order {c["order"]}, PDF {c["pdf"] or "not stated in the table"}, '
            f'scale {c["scale"] or "not stated in the table"}')


def _gap(basis, sqrt_s, order):
    for gap in registry()['gaps']:
        if gap['basis'] in ('*', basis) and gap['sqrt_s_GeV'] in ('*', sqrt_s) and gap['order'] in ('*', order):
            return gap
    return None


def _select(basis, sqrt_s, convention, charge):
    tables = [t for t in registry()['tables'] if t['basis'] == basis]
    if not tables:
        known = sorted({t['basis'] for t in registry()['tables']} | {a['basis'] for a in registry()['aliases']})
        raise ValueError(f'unknown production basis {basis!r}; known bases: {", ".join(known)}')
    order = convention['order']
    at_energy = [t for t in tables if t['sqrt_s_GeV'] == sqrt_s]
    candidates = [t for t in at_energy if t['convention']['order'] == order]
    if not candidates:
        gap = _gap(basis, sqrt_s, order)
        available = '; '.join(_describe(t) for t in at_energy) or 'none at this energy'
        raise ConventionUnavailable(
            f'no pinned {basis} table at {sqrt_s} GeV with order {order}'
            + (f' (declared gap: {gap["reason"]})' if gap else '') + f'. Available: {available}')
    candidates = [t for t in candidates if _pdf_matches(convention['pdf'], t)]
    if not candidates:
        raise ConventionUnavailable(f'no {basis} {order} table at {sqrt_s} GeV with PDF {convention["pdf"]!r}. '
                                    'Available: ' + '; '.join(_describe(t) for t in at_energy))
    candidates = [t for t in candidates if _scale_matches(convention['scale'], t)]
    if not candidates:
        raise ConventionUnavailable(f'no {basis} {order} table with scale {convention["scale"]!r}')
    charged = any(t['charge'] is not None for t in candidates)
    if charged:
        if charge not in ('plus', 'minus', 'sum'):
            raise ValueError(f'basis {basis} is charge resolved; declare charge as plus, minus or sum')
        exact = [t for t in candidates if t['charge'] == charge]
        if exact:
            candidates = exact
        elif charge == 'sum':
            parts = {c: [t for t in candidates if t['charge'] == c] for c in ('plus', 'minus')}
            if all(len(v) == 1 for v in parts.values()):
                return 'sum', [parts['plus'][0], parts['minus'][0]]
            raise ConventionUnavailable(f'no summed {basis} table and no unique charge tables to add')
        else:
            raise ConventionUnavailable(f'no {charge} charge {basis} table under this convention')
    elif charge is not None:
        raise ValueError(f'basis {basis} is not charge resolved; omit charge')
    if len(candidates) > 1:
        raise ConventionUnavailable('ambiguous convention; narrow the PDF or scale. Candidates: '
                                    + '; '.join(_describe(t) for t in candidates))
    return 'single', candidates


def validate_request(request):
    allowed = {'schema_version', 'basis', 'sqrt_s_GeV', 'convention', 'masses', 'charge', 'state_count',
               'selection_statement', 'spectrum', 'spectrum_assumption'}
    if not isinstance(request, dict) or request.get('schema_version') != 1:
        raise ValueError('cross-section request schema_version 1 required')
    extra = set(request) - allowed
    if extra:
        raise ValueError('unknown request keys: ' + ', '.join(sorted(extra)))
    for key in ('basis', 'sqrt_s_GeV', 'convention', 'masses'):
        if key not in request:
            raise ValueError(f'request needs {key}')
    convention = request['convention']
    if not isinstance(convention, dict) or 'order' not in convention:
        raise ValueError('the request must select the perturbative order in convention.order')
    if convention['order'] not in ORDERS:
        raise ValueError('convention.order must be one of ' + ', '.join(ORDERS))
    for key in ('pdf', 'scale'):
        if not isinstance(convention.get(key), str) or not convention[key].strip():
            raise ValueError(f"convention.{key} must name the {key} or be '{AS_PUBLISHED}'")
    if set(convention) - {'order', 'pdf', 'scale'}:
        raise ValueError('convention keys are order, pdf and scale')
    if not isinstance(request['masses'], dict) or not request['masses']:
        raise ValueError('masses must map parameter names to GeV values')
    if 'spectrum' in request:
        spectrum = request['spectrum']
        if not isinstance(spectrum, dict) or not spectrum or set(spectrum) - {'decoupling', 'state_count'}:
            raise ValueError('spectrum must describe decoupling and/or state_count')
        if 'decoupling' in spectrum and (not isinstance(spectrum['decoupling'], str)
                                        or not spectrum['decoupling'].strip()):
            raise ValueError('spectrum.decoupling must describe the requested partner spectrum')
        if 'state_count' in spectrum:
            if type(spectrum['state_count']) is not int or spectrum['state_count'] < 1:
                raise ValueError('spectrum.state_count must be a positive integer')
            if spectrum['state_count'] != request.get('state_count'):
                raise ValueError('spectrum.state_count must agree with request.state_count')
    if 'spectrum_assumption' in request and (not isinstance(request['spectrum_assumption'], str)
                                            or not request['spectrum_assumption'].strip()):
        raise ValueError('spectrum_assumption must state the approximation being declared')
    return request


def _spectrum_assumption(request, entries):
    """Compare declared partner content with every selected table, without inventing spectra."""
    requested = dict(request.get('spectrum') or {})
    if request.get('state_count') is not None:
        requested['state_count'] = request['state_count']
    descriptions = [{k: e.get(k) for k in ('id', 'decoupling', 'state_count', 'comment', 'note')}
                    for e in entries]
    mismatch = any(any(requested[k] != e.get(k) for k in requested) for e in entries)
    # Published multiplicity rescaling is already an explicit, sourced rule;
    # it is not an arbitrary approximation to a different partner spectrum.
    unsupported = any(
        ('decoupling' in requested and requested['decoupling'] != e.get('decoupling'))
        or ('state_count' in requested and requested['state_count'] != e.get('state_count')
            and not e.get('state_rescaling')) for e in entries)
    statement = request.get('spectrum_assumption')
    if unsupported and not statement:
        raise ValueError(f'requested spectrum {requested!r} differs from table spectra {descriptions!r}; '
                         'no rescaling rule covers this difference; declare spectrum_assumption')
    if not mismatch:
        return None
    return {'requested': requested, 'tables': descriptions,
            'statement': statement or '; '.join(e['state_rescaling'] for e in entries if e.get('state_rescaling'))}


def lookup(request, *, base="."):
    if "table" in request or request.get("kind") == "cross-section-batch":
        from ravel.physics.xsec_conventions import lookup as supplied_lookup
        return supplied_lookup(request, base)
    validate_request(request)
    basis, sqrt_s, convention = request['basis'], request['sqrt_s_GeV'], request['convention']
    alias = next((a for a in registry()['aliases'] if a['basis'] == basis), None)
    target = alias['target'] if alias else basis
    kind, entries = _select(target, sqrt_s, convention, request.get('charge'))
    assumption = _spectrum_assumption(request, entries)
    parts = []
    for entry in entries:
        sigma, rel, how = interpolate(entry, load_table(entry)['data'], request['masses'])
        parts.append((entry, sigma, rel, how))
    if kind == 'sum':
        sigma = sum(p[1] for p in parts)
        rel = {}
        for key in parts[0][2]:
            values = [p[2].get(key) for p in parts]
            rel[key] = None if any(v is None for v in values) else sum(v * p[1] for v, p in zip(values, parts)) / sigma
        how = '; '.join(f'{p[0]["charge"]}: {p[3]}' for p in parts)
        combination = {'rule': 'sum of the plus and minus charge tables of the same convention; '
                               'relative uncertainties combined linearly (fully correlated)',
                       'tables': [p[0]['id'] for p in parts]}
    else:
        (_, sigma, rel, how), combination = parts[0], None
    reference = entries[0]
    rescaling = None
    if reference['state_count'] is not None:
        requested = request.get('state_count')
        if type(requested) is not int or requested < 1:
            raise ValueError(f'basis {target} counts degenerate states; declare state_count '
                             f'(the table assumes {reference["state_count"]})')
        if requested != reference['state_count']:
            if reference['state_rescaling']:
                factor = requested / reference['state_count']
                sigma *= factor
                rescaling = {'factor': factor, 'table_state_count': reference['state_count'],
                             'requested_state_count': requested, 'rule': reference['state_rescaling']}
    elif request.get('state_count') is not None:
        raise ValueError(f'basis {target} has no state count; omit state_count')
    up = None if rel.get('relative_up') is None else rel['relative_up'] * sigma
    down = None if rel.get('relative_down') is None else rel['relative_down'] * sigma
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': sqrt_s, 'masses': request['masses'],
            'charge': request.get('charge'), 'state_count': request.get('state_count'),
            'sigma_pb': sigma, 'uncertainty': {'up_pb': up, 'down_pb': down, **rel},
            'interpolation': how,
            'convention': {'order': convention['order'], 'pdf_requested': convention['pdf'],
                           'scale_requested': convention['scale'], 'pdf': reference['convention']['pdf'],
                           'scale': reference['convention']['scale'],
                           'order_as_published': reference['convention']['order_as_published']},
            'selection_statement': request.get('selection_statement'),
            'spectrum_assumption': assumption,
            'alias': alias, 'charge_combination': combination, 'state_rescaling': rescaling,
            'table': _table_record(reference),
            'tables': [_table_record(e) for e in entries],
            'source': {'kind': 'published-table'}}


def _table_record(entry):
    return {'id': entry['id'], 'file': entry['file'], 'sha256': entry['sha256'], 'source_url': entry['source_url'],
            'citation': entry['citation'], 'tool': entry['tool'], 'decoupling': entry['decoupling'],
            'comment': entry['comment'], 'note': entry['note']}


# ------------------------------------------------------------- MG5 and k

def _banner_sigma(path):
    import re
    text = Path(path).read_text(errors='replace')
    found = re.findall(r'Integrated weight \(pb\)\s*:\s*([0-9.eE+-]+)', text)
    if len(found) != 1:
        raise ValueError('banner must contain exactly one "Integrated weight (pb)" line')
    return float(found[0])


def mg5_record(*, basis, sqrt_s_GeV, masses, convention, state_count=None, charge=None, sigma_pb=None,
               uncertainty_pb=None, banner=None):
    """An MG5-computed cross section with its own declared convention (LO or NLO)."""
    if convention.get('order') not in ('LO', 'NLO'):
        raise ValueError('an MG5 fixed-order cross section has order LO or NLO; resummed orders come from tables')
    for key in ('pdf', 'scale'):
        if not isinstance(convention.get(key), str) or not convention[key].strip():
            raise ValueError(f'MG5 convention needs {key}')
    source = {'kind': 'mg5'}
    if banner is not None:
        value = _banner_sigma(banner)
        if sigma_pb is not None and not math.isclose(value, sigma_pb, rel_tol=1e-9):
            raise ValueError('declared sigma differs from the banner value')
        sigma_pb = value
        source.update(path=str(Path(banner).resolve()),
                      sha256=hashlib.sha256(Path(banner).read_bytes()).hexdigest())
    if isinstance(sigma_pb, bool) or type(sigma_pb) not in (int, float) or not math.isfinite(sigma_pb) or sigma_pb <= 0:
        raise ValueError('a positive MG5 cross section (or its banner) is required')
    return {'schema_version': 1, 'basis': basis, 'sqrt_s_GeV': sqrt_s_GeV, 'masses': dict(masses),
            'charge': charge, 'state_count': state_count, 'sigma_pb': float(sigma_pb),
            'uncertainty': {'up_pb': uncertainty_pb, 'down_pb': uncertainty_pb},
            'convention': dict(convention), 'source': source}


def k_factor(numerator, denominator):
    """Ratio of two records on an identical basis; refuses unlike quantities."""
    keys = ('basis', 'sqrt_s_GeV', 'masses', 'charge', 'state_count')
    differ = [k for k in keys if numerator.get(k) != denominator.get(k)]
    if differ:
        raise ValueError('k-factor needs like-for-like records; they differ in ' + ', '.join(differ))
    return {'k_factor': numerator['sigma_pb'] / denominator['sigma_pb'],
            'numerator': {'sigma_pb': numerator['sigma_pb'], 'convention': numerator['convention'],
                          'source': numerator.get('table', numerator.get('source'))},
            'denominator': {'sigma_pb': denominator['sigma_pb'], 'convention': denominator['convention'],
                            'source': denominator.get('source')},
            'basis': {k: numerator.get(k) for k in keys}}


# ------------------------------------------------------- science-mode adapter

def validate(task):
    from ravel.physics import declared_study
    return declared_study.validate_task(task)


def inputs(task, base):
    from ravel.physics import declared_study
    path, request = declared_study.load_request(task, base)
    if 'table' in request or request.get('kind') == 'cross-section-batch':
        from ravel.physics.xsec_conventions import inputs as supplied_inputs
        return declared_study.inputs(path, [__file__, *supplied_inputs(request, path.parent)])
    result = lookup(request)
    tables = [table_path(table_entry(t['id'])) for t in result['tables']]
    return declared_study.inputs(path, [__file__, package_data_path('cross_sections', 'registry.json'), *tables])


def run(task, base, output):
    from ravel.physics import declared_study
    path, request = declared_study.load_request(task, base)
    result = lookup(request, base=path.parent)
    payload = {
        'schema_version': 1, 'kind': 'cross-section', 'status': 'passed', 'physics_validated': False, 'scope': SCOPE,
        'request': {'path': str(path), 'sha256': declared_study.sha256(path)},
        'cross_section': result, 'limitations': LIMITATIONS}
    if request.get('kind') == 'cross-section-batch':
        from ravel.physics.xsec_conventions import deliver_batch
        payload.update({k: result[k] for k in ('study_id', 'datasets', 'output_format', 'points')})
        return deliver_batch(output, payload)
    return declared_study.deliver(output, 'cross-section.json', payload)



def main(argv=None):
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("supplied", "correct"):
        from ravel.physics.xsec_conventions import main as convention_main
        return convention_main(argv)
    parser = argparse.ArgumentParser(prog='ravel xsec', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    from ravel.physics.xsec_conventions import register_cli
    register_cli(sub)
    lk = sub.add_parser('lookup', help='look up a cross section under an explicit convention')
    lk.add_argument('--request', required=True, type=Path)
    lk.add_argument('--out', type=Path)
    ls = sub.add_parser('list', help='list pinned tables, aliases and declared gaps')
    ls.add_argument('--basis')
    sub.add_parser('verify', help='check every pinned table against its sha256')
    fe = sub.add_parser('fetch', help='re-download one table from its pinned URL and verify it')
    fe.add_argument('--table', required=True)
    fe.add_argument('--out', required=True, type=Path)
    from ravel.physics import declared_study
    declared_study.plan_arguments(sub.add_parser('plan', help='prepare an approvable cross-section study'))
    args = parser.parse_args(argv)
    if args.command == 'plan':
        return declared_study.prepare(args, mode='cross-section',
                                      assumptions=['The request selects the production basis and convention.',
                                                   'Values come from the pinned published table named in the result.'])
    if args.command == 'lookup':
        result = lookup(json.loads(args.request.read_text()), base=args.request.parent)
        from ravel.physics.xsec_conventions import emit
        return emit(result, args.out)
    if args.command == 'verify':
        report = verify_registry()
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    if args.command == 'fetch':
        print(json.dumps(fetch(args.table, args.out), indent=2))
        return 0
    rows = [t for t in registry()['tables'] if args.basis in (None, t['basis'])]
    for t in rows:
        c = t['convention']
        print(f'{t["id"]:45s} {t["basis"]:32s} {t["sqrt_s_GeV"]:>6} {c["order"]:11s} '
              f'charge={t["charge"] or "-":5s} states={t["state_count"] or "-"} PDF={c["pdf"] or "not stated"}')
    for a in registry()['aliases']:
        if args.basis in (None, a['basis'], a['target']):
            print(f'alias {a["basis"]} -> {a["target"]}: {a["rule"]}')
    for g in registry()['gaps']:
        if args.basis in (None, g['basis']):
            print(f'gap {g["basis"]} {g["sqrt_s_GeV"]} {g["order"]}: {g["reason"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
