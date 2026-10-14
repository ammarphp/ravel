"""Normalization ledger: every factor between generated weights and delivered yields.

A ledger records, for one sample, the luminosity, the cross section with its
convention (order, tool, PDF, scales, production basis, pinned source), the
branching fractions with their source, the generator-filter efficiency, the
correction factor with its numerator and denominator bases, the generated
weight sums, the selected per-bin weight sums, the bin convention and the
normalization the target publication uses. ``check`` recomputes every delivered
yield

    y_k = sigma[pb] * k * prod(BR) * filter * L[pb^-1] * sumw_k / sumw_generated

with ``math.fsum`` in a recorded order to a relative tolerance (1e-12 by
default) and names the cause of each disagreement: a factor applied twice or
omitted, a pb/fb swap, a per-GeV versus per-bin template, a requested event
count used as the denominator, or mismatched correction bases. It never
rescales anything.

``from_native_normalization`` and ``from_cross_section`` build ledgers from the
existing generator normalization record and the cross-section registry;
``engine_normalization`` gives the columnar analysis engine's normalization
block, and ``check_engine_scale`` verifies the scale the engine applied.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

SCHEMA = 1
SIGMA_UNITS = {'pb': 1.0, 'fb': 1e-3, 'nb': 1e3, 'mb': 1e9}
LUMI_UNITS = {'pb^-1': 1.0, 'fb^-1': 1e3, 'ab^-1': 1e6}
ORDERS = ('LO', 'NLO', 'NLO+NLL', 'NNLO', 'NNLO+NNLL', 'aNNLO+NNLL', 'N3LO')
BR_SOURCES = ('slha', 'decay_table', 'paper_assumption', 'generator')
BIN_CONVENTIONS = ('per-bin', 'per-unit-width')
BASIS_KEYS = ('final_states', 'multiplicities', 'generation_cuts', 'pdf')
SUMMATION_ORDER = ('scale = sigma_pb * k * prod(BR in listed order) * filter * L_pb^-1 / sumw_generated; '
                   'y_k = scale * sumw_k (per-unit-width: divided by the bin width); '
                   'sums of weights use math.fsum')


def _num(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    if positive and value <= 0:
        raise ValueError(f'{name} must be positive')
    if nonnegative and value < 0:
        raise ValueError(f'{name} must be nonnegative')
    return float(value)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be stated')
    return value


def event_scale(*, luminosity_fb, cross_section_pb, filter_efficiency, k_factor, sum_weights):
    """Per-event-weight scale L * sigma * filter * k / sumw (pb x fb^-1 -> events)."""
    return (float(luminosity_fb) * 1000 * float(cross_section_pb) * float(filter_efficiency)
            * float(k_factor) / float(sum_weights))


def validate(ledger):
    if not isinstance(ledger, dict) or ledger.get('schema_version') != SCHEMA:
        raise ValueError('normalization ledger schema_version 1 required')
    allowed = {'schema_version', 'sample', 'luminosity', 'sigma', 'br', 'filter_eff', 'k', 'generated', 'selected',
               'bin_convention', 'observable_normalized', 'target_normalization', 'delivered', 'denominator',
               'cross_checks', 'sources', 'summation_order', 'sigma_alternates'}
    extra = set(ledger) - allowed
    if extra:
        raise ValueError('unknown ledger keys: ' + ', '.join(sorted(extra)))
    for key in ('sample', 'luminosity', 'sigma', 'generated', 'selected', 'bin_convention'):
        if key not in ledger:
            raise ValueError(f'ledger needs {key}')
    lumi = ledger['luminosity']
    if lumi.get('unit') not in LUMI_UNITS:
        raise ValueError(f'luminosity unit must be one of {", ".join(LUMI_UNITS)}')
    _num(lumi.get('value'), 'luminosity', positive=True)
    _text(lumi.get('source'), 'luminosity source')
    sigma = ledger['sigma']
    if sigma.get('unit') not in SIGMA_UNITS:
        raise ValueError(f'cross-section unit must be one of {", ".join(SIGMA_UNITS)}')
    _num(sigma.get('value'), 'cross section', positive=True)
    if sigma.get('order') not in ORDERS:
        raise ValueError('cross-section order must be one of ' + ', '.join(ORDERS))
    for key in ('tool', 'pdf', 'scales', 'process_basis', 'source'):
        _text(sigma.get(key), f'cross-section {key}')
    alternates = ledger.get('sigma_alternates', [])
    if not isinstance(alternates, list):
        raise ValueError('sigma_alternates must be a list')
    for row in alternates:
        if not isinstance(row, dict) or set(row) != {'order', 'pdf', 'value_pb', 'source'}:
            raise ValueError('each sigma_alternates entry needs order, pdf, value_pb and source')
        if row['order'] not in ORDERS:
            raise ValueError('alternate cross-section order must be one of ' + ', '.join(ORDERS))
        _num(row['value_pb'], 'alternate cross section', positive=True)
        _text(row['pdf'], 'alternate cross-section pdf')
        _text(row['source'], 'alternate cross-section source')
    for row in ledger.get('br') or []:
        if row.get('source') not in BR_SOURCES:
            raise ValueError('each branching fraction needs a source: ' + ', '.join(BR_SOURCES))
        _num(row.get('value'), 'branching fraction', nonnegative=True)
        _text(row.get('detail'), 'branching-fraction detail')
    if ledger.get('filter_eff') is not None:
        f = ledger['filter_eff']
        _num(f.get('value'), 'filter efficiency', positive=True)
        _text(f.get('source'), 'filter-efficiency source')
    if ledger.get('k') is not None:
        k = ledger['k']
        _num(k.get('value'), 'k factor', positive=True)
        if type(k.get('applied_once')) is not bool:
            raise ValueError('k.applied_once must be true or false')
        for side in ('numerator_basis', 'denominator_basis'):
            if not isinstance(k.get(side), dict) or k[side].get('order') not in ORDERS:
                raise ValueError(f'k.{side} needs an order and its basis')
    gen = ledger['generated']
    _num(gen.get('sumw'), 'generated sum of weights')
    _num(gen.get('sumw2'), 'generated sum of squared weights', nonnegative=True)
    if ledger['bin_convention'] not in BIN_CONVENTIONS:
        raise ValueError('bin_convention is per-bin or per-unit-width')
    regions = ledger['selected']
    if not isinstance(regions, dict) or not regions:
        raise ValueError('selected maps region names to per-bin sumw and sumw2')
    for name, r in regions.items():
        if not isinstance(r.get('sumw'), list) or not r['sumw'] or len(r.get('sumw2', [])) != len(r['sumw']):
            raise ValueError(f'region {name}: sumw and sumw2 lists of equal nonzero length required')
        for value in r['sumw']:
            _num(value, f'{name} sumw')
        for value in r['sumw2']:
            _num(value, f'{name} sumw2', nonnegative=True)
        if ledger['bin_convention'] == 'per-unit-width':
            edges = r.get('bin_edges')
            if not isinstance(edges, list) or len(edges) != len(r['sumw']) + 1:
                raise ValueError(f'region {name}: per-unit-width yields need bin_edges')
            for edge in edges:
                _num(edge, 'bin edge')
            if any(b <= a for a, b in zip(edges, edges[1:])):
                raise ValueError('bin edges must strictly increase')
    if ledger.get('denominator', 'sumw') not in ('sumw', 'requested_N', 'n_events'):
        raise ValueError('denominator is sumw, requested_N or n_events')
    return ledger


def sigma_pb(ledger):
    s = ledger['sigma']
    return s['value'] * SIGMA_UNITS[s['unit']]


def luminosity_inv_pb(ledger):
    lumi = ledger['luminosity']
    return lumi['value'] * LUMI_UNITS[lumi['unit']]


def br_product(ledger):
    product = 1.0
    for row in ledger.get('br') or []:
        product *= row['value']
    return product


def factors(ledger):
    """Every multiplicative factor, in the recorded order."""
    k = (ledger.get('k') or {}).get('value', 1.0)
    filt = (ledger.get('filter_eff') or {}).get('value', 1.0)
    return {'sigma_pb': sigma_pb(ledger), 'k': k, 'br_product': br_product(ledger), 'filter': filt,
            'luminosity_inv_pb': luminosity_inv_pb(ledger), 'sumw_generated': ledger['generated']['sumw']}


def applied_sigma_pb(ledger):
    f = factors(ledger)
    return f['sigma_pb'] * f['k'] * f['br_product'] * f['filter']


def scale(ledger):
    f = factors(ledger)
    if f['sumw_generated'] <= 0:
        raise ValueError('the generated sum of weights is not positive')
    return f['sigma_pb'] * f['k'] * f['br_product'] * f['filter'] * f['luminosity_inv_pb'] / f['sumw_generated']


def expected_yields(ledger):
    s = scale(ledger)
    out = {}
    for name, r in ledger['selected'].items():
        values = [s * w for w in r['sumw']]
        errors = [s * math.sqrt(w2) for w2 in r['sumw2']]
        if ledger['bin_convention'] == 'per-unit-width':
            widths = [b - a for a, b in zip(r['bin_edges'], r['bin_edges'][1:])]
            values = [v / w for v, w in zip(values, widths)]
            errors = [e / w for e, w in zip(errors, widths)]
        out[name] = {'values': values, 'errors': errors}
    return out


def _close(a, b, rel_tol):
    return math.isclose(a, b, rel_tol=rel_tol, abs_tol=0.0) or (a == 0 and b == 0)


def _diagnose(ledger, delivered, expected, rel_tol):
    """Name the factor that explains a uniform ratio between delivered and expected yields."""
    ratios = []
    for name, values in delivered.items():
        for d, e in zip(values, expected[name]['values']):
            if e != 0:
                ratios.append(d / e)
    if not ratios:
        return []
    f = factors(ledger)
    causes = []
    tol = max(rel_tol, 1e-9)
    candidates = [('unit_swap', 1000.0, 'a pb/fb conversion was applied the wrong way (factor 1000)'),
                  ('unit_swap', 1e-3, 'a pb/fb conversion was applied the wrong way (factor 1/1000)')]
    if f['k'] != 1.0:
        candidates += [('k_applied_twice', f['k'], 'the correction factor k was applied twice'),
                       ('k_omitted', 1 / f['k'], 'the correction factor k was not applied')]
    if f['br_product'] not in (0.0, 1.0):
        candidates += [('br_omitted', 1 / f['br_product'], 'the branching fractions were not applied'),
                       ('br_applied_twice', f['br_product'], 'the branching fractions were applied twice')]
    if f['filter'] != 1.0:
        candidates += [('filter_omitted', 1 / f['filter'], 'the filter efficiency was not applied'),
                       ('filter_applied_twice', f['filter'], 'the filter efficiency was applied twice')]
    requested = ledger['generated'].get('requested_N')
    if requested:
        candidates.append(('requested_N_denominator', f['sumw_generated'] / requested,
                           'the requested event count was used instead of the generated sum of weights'))
    uniform = all(_close(r, ratios[0], 1e-9) for r in ratios)
    if uniform:
        for code, value, text in candidates:
            if _close(ratios[0], value, tol):
                causes.append({'code': code, 'ratio': ratios[0], 'explanation': text})
    else:
        for name, values in delivered.items():
            r = ledger['selected'][name]
            if 'bin_edges' in r:
                widths = [b - a for a, b in zip(r['bin_edges'], r['bin_edges'][1:])]
                exp = expected[name]['values']
                if ledger['bin_convention'] == 'per-bin' and all(
                        _close(d, e / w, 1e-9) for d, e, w in zip(values, exp, widths)):
                    causes.append({'code': 'bin_convention', 'region': name,
                                   'explanation': 'delivered yields are per unit width (Events/GeV) but the ledger '
                                                  'declares per-bin yields'})
                if ledger['bin_convention'] == 'per-unit-width' and all(
                        _close(d, e * w, 1e-9) for d, e, w in zip(values, exp, widths)):
                    causes.append({'code': 'bin_convention', 'region': name,
                                   'explanation': 'delivered yields are per bin but the ledger declares per unit width'})
    return causes


def _basis_mismatch(k, sigma):
    num, den = k['numerator_basis'], k['denominator_basis']
    problems = [f'{key}: numerator {num.get(key)!r} vs denominator {den.get(key)!r}'
                for key in BASIS_KEYS if num.get(key) != den.get(key)]
    if den.get('order') != sigma['order']:
        problems.append(f'the denominator order {den.get("order")} is not the order of the applied cross section '
                        f'({sigma["order"]})')
    if den.get('pdf') is not None and den.get('pdf') != sigma['pdf']:
        problems.append(f'the denominator PDF {den.get("pdf")} is not the PDF of the applied cross section ({sigma["pdf"]})')
    if num.get('order') == den.get('order'):
        problems.append('numerator and denominator have the same order')
    return problems


def _sigma_source_check(sigma):
    """Resolve a registry ID/hash (including builder pins) and compare its own convention."""
    from ravel.physics import cross_sections as xs
    rows = xs.registry()['tables']
    source = sigma['source']
    pin = sigma.get('pin') or {}
    claims = [{'id': source, 'sha256': pin.get('sha256')}, *(sigma.get('tables') or [])]
    failures, entries = [], []
    seen = set()
    for claim in claims:
        identity, digest = claim.get('id'), claim.get('sha256')
        if (identity, digest) in seen:
            continue
        seen.add((identity, digest))
        by_source = [e for e in rows if identity in (e['id'], e['sha256'])]
        candidates = by_source or [e for e in rows if digest and e['sha256'] == digest]
        if by_source and digest:
            candidates = [e for e in by_source if e['sha256'] == digest]
            if not candidates:
                failures.append({'code': 'sigma_table_pin_mismatch', 'explanation':
                                 f'source {identity!r} has registry hashes {[e["sha256"] for e in by_source]!r}; '
                                 f'ledger pin is {digest!r}'})
                continue
        if not candidates:
            if claim is not claims[0]:
                failures.append({'code': 'sigma_table_unknown', 'explanation':
                                 f'no registry table matches {identity!r}, sha256 {digest!r}'})
            continue
        if len(candidates) != 1:
            failures.append({'code': 'sigma_table_ambiguous', 'explanation':
                             f'registry source {identity!r} resolves to {len(candidates)} tables; supply its sha256'})
            continue
        entry = candidates[0]
        entries.append(entry)
        c = entry['convention']
        expected = {'order': c['order'], 'pdf': c['pdf'] or xs.AS_PUBLISHED,
                    'process_basis': entry['basis']}
        for key, value in expected.items():
            actual = sigma[key]
            if key == 'process_basis' and actual != value:
                alias = sigma.get('basis_alias')
                if alias in xs.registry()['aliases'] and alias['basis'] == actual and alias['target'] == value:
                    continue
            if actual != value:
                failures.append({'code': 'sigma_table_mismatch', 'table': entry['id'], 'field': key,
                                 'explanation': f'ledger sigma.{key} {actual!r} differs from registry table '
                                                f'{entry["id"]!r} {key} {value!r}'})
    warnings = []
    if not entries and not failures:
        warnings.append({'code': 'source_unpinned', 'explanation':
                         f'cross-section source {source!r} is not bound to a pinned registry table'})
    return failures, warnings


def _integrated_total(ledger, expected):
    values = []
    for name, region in expected.items():
        if ledger['bin_convention'] == 'per-unit-width':
            edges = ledger['selected'][name]['bin_edges']
            values.extend(v * (b - a) for v, a, b in zip(region['values'], edges, edges[1:]))
        else:
            values.extend(region['values'])
    return math.fsum(values)


def check(ledger, *, delivered=None, certifier_sigma_fb=None, rel_tol=1e-12):
    """Typed failures and warnings; recomputes delivered yields when given."""
    validate(ledger)
    failures, warnings, checkin2 = [], [], []

    def fail(code, text, **extra):
        failures.append({'code': code, 'explanation': text, **extra})

    f = factors(ledger)
    gen = ledger['generated']
    if gen['sumw'] <= 0:
        fail('sumw_nonpositive', 'the generated sum of weights is not positive; nothing can be normalized')
    for row in ledger.get('br') or []:
        if row['value'] > 1:
            fail('br_above_one', f'branching fraction {row["detail"]} exceeds one')
        if row['value'] == 1 and row['source'] == 'paper_assumption' and not row.get('statement'):
            fail('br_assumption_undeclared', f'BR = 1 for {row["detail"]} needs the quoted assumption')
    if f['br_product'] > 1:
        fail('br_product_above_one', 'the product of branching fractions exceeds one')
    k = ledger.get('k')
    if k is not None:
        if not k['applied_once']:
            fail('k_applied_twice', 'the correction factor is recorded as applied more than once')
        if k['numerator_basis'].get('order') == ledger['sigma']['order'] and k['value'] != 1:
            fail('k_on_corrected_sigma', f'the cross section is already at {ledger["sigma"]["order"]}, the order of '
                 'the k numerator; applying k again double counts')
        mismatch = _basis_mismatch(k, ledger['sigma'])
        if mismatch:
            fail('k_basis_mismatch', 'correction-factor bases differ: ' + '; '.join(mismatch))
        if ledger.get('observable_normalized') and k['value'] != 1:
            warnings.append({'code': 'k_noop_on_normalized_observable',
                             'explanation': 'a uniform k on a shape-normalized observable has no effect'})
    denominator = ledger.get('denominator', 'sumw')
    if denominator != 'sumw':
        unit = gen.get('n_events') is not None and _close(gen['sumw'], float(gen['n_events']), 1e-12)
        if denominator == 'requested_N' or not unit:
            fail('requested_N_denominator', f'the denominator is {denominator}, not the processed sum of weights; '
                 'only unit-weight samples with sumw equal to the event count may use the count')
    if gen.get('negative_fraction'):
        warnings.append({'code': 'negative_weights', 'explanation': f'{gen["negative_fraction"]:.3%} of generated '
                         'weights are negative; the denominator is their signed sum'})
    target = ledger.get('target_normalization')
    if target and target.get('order') and target['order'] != (k['numerator_basis']['order'] if k else ledger['sigma']['order']):
        effective = k['numerator_basis']['order'] if k else ledger['sigma']['order']
        warnings.append({'code': 'order_differs_from_target',
                         'explanation': f'the applied normalization is {effective}; the target uses {target["order"]}'})
        checkin2.append(f'Normalization order {effective} differs from the target publication ({target["order"]}, '
                        f'{target.get("locator", "location not quoted")}).')
    for cc in ledger.get('cross_checks') or []:
        value = _num(cc.get('sigma_pb'), 'cross-check cross section', positive=True)
        tol = _num(cc.get('rel_tol', 0.1), 'cross-check tolerance', positive=True)
        reference = f['sigma_pb'] if cc.get('compare_to', 'sigma') == 'sigma' else f['sigma_pb'] * f['k']
        if abs(value / reference - 1) > tol:
            warnings.append({'code': 'cross_check_differs', 'explanation':
                             f'{cc.get("tool", "independent calculation")} ({cc.get("order")}, {cc.get("pdf")}) gives '
                             f'{value:.6g} pb vs {reference:.6g} pb', 'calculator': cc})
    if certifier_sigma_fb is not None:
        applied_fb = applied_sigma_pb(ledger) * 1000
        if not _close(float(certifier_sigma_fb), applied_fb, 1e-9):
            fail('certifier_sigma_differs', f'the certifier uses {certifier_sigma_fb:.10g} fb; the ledger applies '
                 f'{applied_fb:.10g} fb')
    expected = expected_yields(ledger) if gen['sumw'] > 0 else {}
    sigma_failures, sigma_warnings = _sigma_source_check(ledger['sigma'])
    failures.extend(sigma_failures)
    warnings.extend(sigma_warnings)
    alternates = []
    for index, row in enumerate(ledger.get('sigma_alternates', [])):
        alternate = copy.deepcopy(ledger)
        alternate['sigma'] = {key: ledger['sigma'][key] for key in ('tool', 'scales', 'process_basis')}
        alternate['sigma'].update(value=row['value_pb'], unit='pb', order=row['order'], pdf=row['pdf'],
                                  source=row['source'])
        if ledger['sigma'].get('basis_alias'):
            alternate['sigma']['basis_alias'] = ledger['sigma']['basis_alias']
        fs, ws = _sigma_source_check(alternate['sigma'])
        failures.extend({**r, 'sigma_alternate': index} for r in fs)
        warnings.extend({**r, 'sigma_alternate': index} for r in ws)
        yields = expected_yields(alternate) if expected else {}
        alternates.append({**row, 'ratio': row['value_pb'] / f['sigma_pb'], 'expected': yields,
                           'delivered_total': _integrated_total(ledger, yields) if yields else None,
                           'total_convention': 'sum of integrated bin yields; overlapping regions are not deduplicated'})
    mismatches = []
    if delivered is not None and expected:
        for name in expected.keys() - delivered.keys():
            fail('missing_region', f'delivered region {name} is missing')
        for name, values in delivered.items():
            if name not in expected:
                fail('unknown_region', f'delivered region {name} is not in the ledger')
                continue
            exp = expected[name]['values']
            if len(values) != len(exp):
                fail('bin_count', f'region {name}: {len(values)} delivered bins vs {len(exp)} in the ledger')
                continue
            for i, (d, e) in enumerate(zip(values, exp)):
                if not _close(_num(d, 'delivered yield'), e, rel_tol):
                    mismatches.append({'region': name, 'bin': i, 'delivered': d, 'expected': e})
        if mismatches:
            causes = _diagnose(ledger, {k: v for k, v in delivered.items() if k in expected and len(v) == len(expected[k]['values'])}, expected, rel_tol)
            fail('yield_recomputation', f'{len(mismatches)} delivered bins differ from the recomputed yields',
                 bins=mismatches[:20], causes=causes)
            for c in causes:
                fail(c['code'], c['explanation'])
    return {'passed': not failures, 'failures': failures, 'warnings': warnings, 'checkin2_items': checkin2,
            'factors': f, 'scale': scale(ledger) if gen['sumw'] > 0 else None,
            'applied_sigma_pb': applied_sigma_pb(ledger), 'expected': expected,
            'sigma_alternates': alternates,
            'summation_order': SUMMATION_ORDER, 'rel_tol': rel_tol}


# ---------------------------------------------------------------- builders

def from_cross_section(lookup, *, process_basis=None, tool=None):
    """Ledger sigma block from a cross-section registry lookup or an MG5 record."""
    conv = lookup['convention']
    source = lookup.get('table') or lookup.get('source') or {}
    pin = None
    if source.get('sha256'):
        pin = {'path': source.get('file') or source.get('path'), 'sha256': source['sha256']}
    return {'value': lookup['sigma_pb'], 'unit': 'pb', 'order': conv['order'],
            'tool': tool or source.get('tool') or source.get('kind', 'unknown'),
            'pdf': conv.get('pdf') or conv.get('pdf_requested'), 'scales': conv.get('scale') or conv.get('scale_requested'),
            'process_basis': process_basis or lookup['basis'], 'pin': pin,
            'source': source.get('id') or source.get('source_url') or source.get('kind', 'declared'),
            'tables': copy.deepcopy(lookup.get('tables', [])), 'basis_alias': copy.deepcopy(lookup.get('alias')),
            'spectrum_assumption': copy.deepcopy(lookup.get('spectrum_assumption'))}


def from_native_normalization(record, *, luminosity, selected, sample, sigma_convention, k_bases=None,
                              bin_convention='per-bin', target_normalization=None):
    """Ledger from a native_normalization record (kept unchanged under sources)."""
    if record.get('status') != 'resolved' or record.get('correction_applications') != 1:
        raise ValueError('a resolved native normalization with one correction application is required')
    gen = record['generation']
    ledger = {
        'schema_version': SCHEMA, 'sample': sample, 'luminosity': luminosity,
        'sigma': {'value': record['cross_section_pb'], 'unit': 'pb', **sigma_convention,
                  'pin': (record.get('sources') or [None])[0]},
        'br': [], 'filter_eff': None, 'k': None,
        'generated': {'requested_N': gen.get('n_events'), 'n_events': gen.get('n_events'), 'sumw': gen['sumw'],
                      'sumw2': gen['sumw2'],
                      'negative_fraction': gen.get('negative_weights', 0) / gen['n_events'] if gen.get('n_events') else 0},
        'selected': selected, 'bin_convention': bin_convention, 'observable_normalized': False,
        'target_normalization': target_normalization, 'denominator': 'sumw',
        'sources': {'native_normalization': copy.deepcopy(record)}, 'summation_order': SUMMATION_ORDER}
    if record['kfactor'] != 1:
        if not k_bases:
            raise ValueError('a k factor other than one needs its numerator and denominator bases')
        ledger['k'] = {'value': record['kfactor'], 'applied_once': True, **k_bases}
    factors_record = record.get('decay_factors')
    if factors_record:
        for row in factors_record['per_particle']:
            if row['factor'] != 1.0:
                ledger['br'].append({'value': row['factor'], 'source': 'decay_table' if row['source'] != 'madspin'
                                     else 'generator', 'detail': f'particle {row["particle"]} via {row["source"]}'})
        if factors_record['filters']:
            ledger['filter_eff'] = {'value': factors_record['filter_factor'],
                                    'source': '; '.join(f['source'] for f in factors_record['filters'])}
    return validate(ledger)


def engine_normalization(ledger, *, receipt=None, pointer='/normalization_ledger/applied_sigma_pb'):
    """The columnar engine's cross-section normalization block for this ledger.

    The engine computes sigma * 1000 * L[fb^-1] * factor / sum_of_weights; the
    ledger's sigma * k goes in as the cross section and prod(BR) * filter as
    the factor, so the engine scale equals ``scale(ledger)``.
    """
    validate(ledger)
    f = factors(ledger)
    spec = {'mode': 'cross-section',
            'cross_section_source': f'{ledger["sigma"]["source"]} ({ledger["sigma"]["order"]}, {ledger["sigma"]["pdf"]})'
                                    + (f' x k = {f["k"]:.10g}' if f['k'] != 1 else ''),
            'luminosity_ifb': luminosity_inv_pb(ledger) / 1000, 'luminosity_source': ledger['luminosity']['source'],
            'sum_of_weights': f['sumw_generated'], 'sum_of_weights_source': 'normalization ledger: generated sumw'}
    if receipt is not None:
        spec['cross_section_pb'] = {'production_receipt': str(receipt), 'pointer': pointer}
    else:
        spec['cross_section_pb'] = f['sigma_pb'] * f['k']
    other = f['br_product'] * f['filter']
    if other != 1.0:
        spec['factor'] = {'value': other, 'source': 'normalization ledger: branching fractions x filter efficiency'}
    return spec


def check_engine_scale(ledger, resolved, *, rel_tol=1e-12):
    """The scale the analysis engine applied must equal the ledger scale."""
    expected = scale(ledger)
    got = resolved.get('scale')
    ok = isinstance(got, (int, float)) and _close(float(got), expected, rel_tol)
    return {'passed': ok, 'engine_scale': got, 'ledger_scale': expected, 'rel_tol': rel_tol}


def receipt_block(ledger):
    """What a production receipt embeds: the ledger plus the applied cross section and its convention."""
    validate(ledger)
    s = ledger['sigma']
    return {'normalization_ledger': {**ledger, 'applied_sigma_pb': applied_sigma_pb(ledger)},
            'sigma_pb': applied_sigma_pb(ledger),
            'sigma_source': s['source'],
            'sigma_convention': {'order': s['order'], 'tool': s['tool'], 'pdf': s['pdf'], 'scales': s['scales'],
                                 'process_basis': s['process_basis']}}


def checkin_lines(report, ledger):
    """Plain lines for CHECK-IN 2: the factors, the checks and what to inspect before changing cuts."""
    f = report['factors']
    lines = [f'Sample {ledger["sample"]}: sigma {ledger["sigma"]["value"]:.6g} {ledger["sigma"]["unit"]} '
             f'({ledger["sigma"]["order"]}, {ledger["sigma"]["tool"]}, {ledger["sigma"]["pdf"]}, '
             f'{ledger["sigma"]["scales"]}); k {f["k"]:.6g}; product of branching fractions {f["br_product"]:.6g}; '
             f'filter {f["filter"]:.6g}; luminosity {ledger["luminosity"]["value"]:g} {ledger["luminosity"]["unit"]}; '
             f'generated sum of weights {f["sumw_generated"]:.10g}.',
             'Ledger checks: ' + ('passed.' if report['passed'] else
                                  '; '.join(x['explanation'] for x in report['failures']))]
    lines += [w['explanation'] for w in report['warnings']]
    lines += report['checkin2_items']
    for row in report.get('sigma_alternates', []):
        lines.append(f'Alternate convention {row["order"]}, {row["pdf"]} ({row["source"]}): '
                     f'{row["value_pb"]:.6g} pb; recomputed total {row["delivered_total"]}; '
                     f'ratio to primary {row["ratio"]:.6g}. Primary delivered numbers are unchanged.')
    lines.append('Before changing any cut, inspect this ledger and the uniform efficiency factors; '
                 'no yield is rescaled automatically.')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel normalization-ledger', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('check', help='check a ledger and optionally recompute delivered yields')
    c.add_argument('--ledger', required=True, type=Path)
    c.add_argument('--delivered', type=Path, help='JSON mapping region names to delivered per-bin yields')
    c.add_argument('--certifier-sigma-fb', type=float)
    c.add_argument('--rel-tol', type=float, default=1e-12)
    e = sub.add_parser('engine', help='print the analysis-engine normalization block for a ledger')
    e.add_argument('--ledger', required=True, type=Path)
    e.add_argument('--receipt')
    args = parser.parse_args(argv)
    ledger = json.loads(args.ledger.read_text())
    if args.command == 'engine':
        print(json.dumps(engine_normalization(ledger, receipt=args.receipt), indent=2))
        return 0
    delivered = json.loads(args.delivered.read_text()) if args.delivered else None
    report = check(ledger, delivered=delivered, certifier_sigma_fb=args.certifier_sigma_fb, rel_tol=args.rel_tol)
    print(json.dumps({k: v for k, v in report.items() if k != 'expected'}, indent=2))
    for line in checkin_lines(report, ledger):
        print(line)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
