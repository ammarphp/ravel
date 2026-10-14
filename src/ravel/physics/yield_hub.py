"""Yield writers and source-bound ROOT dataset normalization handoff.

Dataset members retain per-sample denominators, URI, checksum and entry count.
Remote ROOT is opened by the existing uproot reader; no site tool is launched.
"""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, unquote

from . import binned_values


def delivery_checks(output, *, path, absolute_yield=False, ledger=None):
    from ravel.validation.delivery_checks import check_delivery, _write
    output = Path(output).resolve()
    row = {'path': path, 'absolute_yield': absolute_yield}
    if ledger is not None:
        row['normalization_ledger'] = _write(output, 'normalization-ledger.json', ledger)
    return check_delivery(output, {'deliverables': [row]})


def columnar_delivery_checks(output, spec, normalization, merged, regions, base):
    from copy import deepcopy
    import math
    source = normalization.get('cross_section_from') or {}
    stored = source.get('normalization_ledger') if isinstance(source, dict) else None
    ledger = deepcopy(stored['ledger']) if isinstance(stored, dict) and 'ledger' in stored else None
    if ledger is None and isinstance(source, dict) and 'sigma' in source:
        sigma = source['sigma']
        if all(sigma.get(k) for k in ('order', 'tool', 'pdf', 'scales', 'process_basis', 'source')):
            ledger = {'schema_version': 1, 'sample': 'declared columnar sample', 'sigma': sigma,
                      'br': [], 'filter_eff': None, 'k': None, 'bin_convention': 'per-bin'}
    if ledger is not None:
        events = merged['variations']['nominal']['events']
        ledger['luminosity'] = {'value': normalization['luminosity_ifb'], 'unit': 'fb^-1', 'source': normalization['luminosity_source']}
        if stored is not None:
            # A processed subset is not the original normalization population.
            if not math.isclose(ledger['generated']['sumw'], normalization['sum_of_weights'], rel_tol=1e-12):
                return delivery_checks(output, path='analysis-result.json', absolute_yield=True)
        elif spec.get('sum_of_weights') == 'all-input-events':
            ledger['generated'] = {'sumw': events['sum_generator'], 'sumw2': events['sum_generator2'], 'n_events': events['n']}
        else:
            # An external first moment supplies neither a second moment nor a
            # population count. Retain a missing-input finding instead.
            return delivery_checks(output, path='analysis-result.json', absolute_yield=True)
        ledger['selected'] = {r['name']: {'sumw': [c['sumw'] for c in r['cuts']], 'sumw2': [c['sumw2'] for c in r['cuts']]} for r in regions}
        ledger['delivered'] = {r['name']: [c['yield'] for c in r['cuts']] for r in regions}
        ledger['bin_convention'] = 'per-bin'; ledger['denominator'] = 'sumw'
        if spec.get('factor') and stored is None:
            ledger = None
    return delivery_checks(output, path='analysis-result.json', absolute_yield=normalization['mode'] != 'none', ledger=ledger)


def write(path, document):
    binned_values.validate(document)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}


def write_regions(path, names, sumw, sumw2, *, provenance):
    return write(path, binned_values.build(axes=[{'name': 'region_index', 'unit': '1'}], unit='sum of event weights',
        bins=[{'low': [i], 'high': [i+1], 'value': sumw[name], 'sumw2': sumw2[name]} for i, name in enumerate(names)],
        normalization={'kind': 'unnormalized'}, provenance={**provenance, 'region_order': list(names)}))


def write_stream(delivery, output):
    """MC convenience projections only; retain the existing blinded DATA roster."""
    pins = []
    for i, sample in enumerate(delivery['samples']):
        if sample['kind'] == 'data':
            continue
        for j, (name, quantity) in enumerate(sample['quantities'].items()):
            for k, weight in enumerate(quantity['contract']['weight_names']):
                document = binned_values.from_quantity(quantity, weight)
                document['provenance'].update(sample=sample['id'], quantity=name)
                pins.append(write(Path(output) / f'sample-{i}-quantity-{j}-weight-{k}.json', document))
    return pins


def load_dataset(pin, base):
    from . import root_stream_core as core
    capture = core.Capture(); base = Path(base)
    if type(pin) is dict and set(pin) == {'path', 'sha256'}:
        path = Path(pin['path']); path = path if path.is_absolute() else base / path
        pin = {**pin, 'size': path.stat().st_size}
    ds = core.dataset(capture.document(pin, base))
    authority = capture.document(ds['membership_authority'], base)
    if authority.get('schema_version') != 1 or authority.get('samples') != ds['samples']:
        raise ValueError('complete dataset membership differs from authority')
    files = [Path(pin['path']), Path(ds['membership_authority']['path'])]
    for sample in ds['samples']:
        if sample['kind'] == 'data':
            raise ValueError('DATA dataset requires root-stream original blinding; columnar MC adapter cannot bypass it')
        n = sample['normalization']
        original = capture.document(n['original_population'], base)
        source = capture.document(n['source'], base)
        if original.get('sample_id') != sample['id'] or original.get('dsid') != sample['dsid']:
            raise ValueError('normalization population sample identity differs')
        original_rows = {m['guid']: m for m in original['members']}
        for member in sample['members']:
            if original_rows.get(member['guid']) != {k: member[k] for k in ('guid', 'did', 'entries')}:
                raise ValueError('dataset member differs from original normalization population')
        if (source.get('sample_id') != sample['id'] or source.get('dsid') != sample['dsid'] or
                source.get('original_population_sha256') != n['original_population']['sha256'] or
                any(source.get(k) != n[k] for k in ('sum_weights', 'luminosity_fb_inverse', 'cross_section_pb', 'filter_efficiency', 'k_factor'))):
            raise ValueError('dataset normalization differs from original source')
        files += [Path(n['original_population']['path']), Path(n['source']['path'])]
        for member in sample['members']:
            capture.document(member['checksum']['authority'], base)
            files.append(Path(member['checksum']['authority']['path']))
    capture.finish()
    return ds, files


def member_path(member):
    uri = member['uri']
    return uri if uri.startswith('root://') else Path(unquote(urlsplit(uri).path))


def dataset_normalization(sample):
    n = sample['normalization']
    return {'mode': 'cross-section', 'cross_section_pb': n['cross_section_pb'],
            'cross_section_source': 'pinned original dataset normalization',
            'luminosity_ifb': n['luminosity_fb_inverse'], 'luminosity_source': 'pinned original dataset normalization',
            'sum_of_weights': n['sum_weights'], 'sum_of_weights_source': 'pinned full original population; not requested or selected N',
            'factor': {'value': n['filter_efficiency'] * n['k_factor'], 'source': 'pinned original filter efficiency times k factor'}}
