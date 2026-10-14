"""Resolve grid datasets into ROOT members and build MC normalization from supplied sources.

``ravel ntuples resolve`` turns declared samples (dataset DIDs, process, DSID,
tree) into resolved members: one row per file with DID, GUID, Adler32, size,
entries and a ``root://`` URI at the chosen storage element. It asks rucio at
the site (the user's own proxy and rucio configuration are used; nothing is
copied) or reads a supplied listing with the same content. The raw responses are
kept and pinned as the checksum and membership authority. Campaigns come from
declared rules (for example an r-tag pattern to a campaign name); they are data,
never built in.

``ravel ntuples normalize`` builds the ``root-stream`` dataset document:

- the full sum of weights per sample, read per member from a declared
  bookkeeping object (a histogram bin or a tree branch sum) or a supplied table;
- cross section, filter efficiency and k-factor from a supplied cross-section
  database, with the column names and cross-section unit declared;
- luminosity per campaign from a supplied table with its unit.

Nothing is assumed. A DSID absent from the database, a bookkeeping object of a
different DSID, a missing unit or a sample spanning campaigns is refused.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import fnmatch
import hashlib
import json
import math
from pathlib import Path
import re
import sys

from ravel.workflow.state_io import atomic_json, read_json

XSEC_UNITS = {'pb': 1.0, 'nb': 1000.0, 'fb': 0.001, 'ub': 1.0e6}
LUMI_UNITS = {'fb-1': 1.0, 'pb-1': 0.001}
KINDS = ('background_mc', 'signal_mc', 'data')


def _pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _write(path, value):
    atomic_json(path, value)
    return _pin(path)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


# ---------------------------------------------------------------- declaration
def load_declaration(path):
    doc = read_json(path)
    _require(isinstance(doc, dict) and doc.get('schema_version') == 1, 'declaration schema_version 1 required')
    _require(set(doc) <= {'schema_version', 'rse', 'samples', 'campaigns', 'split_by_campaign', 'scheme'},
             'unknown declaration fields')
    _require(isinstance(doc.get('samples'), list) and doc['samples'], 'declaration needs samples')
    ids = set()
    for s in doc['samples']:
        _require(set(s) == {'id', 'kind', 'dsid', 'process', 'tree', 'dids'}, 'each sample needs id, kind, dsid, process, tree, dids')
        _require(isinstance(s['id'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', s['id']) is not None and s['id'] not in ids,
                 'sample ids must be unique plain names')
        ids.add(s['id'])
        _require(s['kind'] in KINDS, f'sample kind must be one of {KINDS}')
        if s['kind'] == 'data':
            _require(s['dsid'] is None, 'data samples have no DSID')
        else:
            _require(type(s['dsid']) is int and s['dsid'] > 0, 'MC samples need an integer DSID')
        _require(isinstance(s['dids'], list) and s['dids'] and all(isinstance(d, str) and ':' in d for d in s['dids']),
                 'dids must be scope:name strings')
    for rule in doc.get('campaigns', {}).get('rules', []):
        _require(set(rule) == {'pattern', 'campaign'}, 'campaign rules have pattern and campaign')
        re.compile(rule['pattern'])
    return doc


def _campaign(doc, did):
    rules = doc.get('campaigns', {}).get('rules', [])
    if not rules:
        return None
    hits = {r['campaign'] for r in rules if re.search(r['pattern'], did)}
    _require(len(hits) == 1, f'dataset {did} matches {len(hits)} campaign rules; exactly one is required')
    return hits.pop()


def _check_dsid(sample, did):
    if sample['kind'] == 'data':
        return
    parts = did.split(':', 1)[1].split('.')
    if len(parts) > 1 and parts[1].isdigit() and int(parts[1]) != sample['dsid']:
        raise ValueError(f"dataset {did} names DSID {parts[1]} but sample {sample['id']} declares DSID {sample['dsid']}")


# ---------------------------------------------------------------- sources
def rucio_client():
    try:
        from rucio.client import Client
    except ImportError as exc:
        raise ValueError('rucio-clients is not installed in this environment (requirements-site.txt)') from exc
    return Client()


def _query(client, did, rse, scheme):
    scope, name = did.split(':', 1)
    files = [dict(r) for r in client.list_files(scope, name)]
    replicas = {}
    if files:
        dids = [{'scope': f['scope'], 'name': f['name']} for f in files]
        for row in client.list_replicas(dids, schemes=[scheme], rse_expression=rse):
            uris = []
            for at, pfns in (row.get('rses') or {}).items():
                if rse is None or at == rse:
                    uris.extend(pfns)
            replicas[f"{row['scope']}:{row['name']}"] = sorted(uris)
    return {'files': files, 'replicas': replicas}


def resolve(declaration, out, *, client=None, listing=None):
    doc = load_declaration(declaration)
    out = Path(out)
    _require(not out.exists(), f'{out} already exists')
    rse, scheme = doc.get('rse'), doc.get('scheme', 'root')
    if listing is not None:
        supplied = read_json(listing)
        source = {'kind': 'listing', 'listing': _pin(listing)}
        responses = {did: {'files': supplied['files'][did],
                           'replicas': {f"{f['scope']}:{f['name']}": supplied['replicas'].get(f"{f['scope']}:{f['name']}", [])
                                        for f in supplied['files'][did]}}
                     for s in doc['samples'] for did in s['dids']}
    else:
        client = client or rucio_client()
        source = {'kind': 'rucio'}
        responses = {did: _query(client, did, rse, scheme) for s in doc['samples'] for did in s['dids']}
    authority_path = out.with_name(out.stem + '.responses.json')
    _require(not authority_path.exists(), f'{authority_path} already exists')
    authority = _write(authority_path, {'schema_version': 1, 'source': source, 'rse': rse, 'scheme': scheme,
                                        'responses': responses})
    samples = []
    for s in doc['samples']:
        groups = {}
        for did in s['dids']:
            _check_dsid(s, did)
            campaign = _campaign(doc, did)
            rows = responses[did]['files']
            _require(rows, f'dataset {did} has no files')
            for f in rows:
                key = f"{f['scope']}:{f['name']}"
                uris = [u for u in responses[did]['replicas'].get(key, []) if u.startswith(scheme + '://')]
                _require(uris, f'file {key} has no {scheme} replica at {rse}')
                _require(f.get('events') is not None, f'file {key} has no entries (events) in the catalogue')
                adler = f.get('adler32')
                _require(isinstance(adler, str) and re.fullmatch(r'[0-9a-fA-F]{1,8}', adler) is not None, f'file {key} has no Adler32')
                member = {'id': key, 'did': key, 'guid': f['guid'], 'uri': uris[0], 'tree': s['tree'],
                          'entries': int(f['events']), 'size_bytes': int(f['bytes']),
                          'checksum': {'algorithm': 'adler32', 'value': adler.lower().zfill(8), 'authority': authority}}
                groups.setdefault(campaign, []).append(member)
        if len(groups) > 1 and not doc.get('split_by_campaign'):
            raise ValueError(f"sample {s['id']} spans campaigns {sorted(map(str, groups))}; set split_by_campaign or declare one sample per campaign")
        for campaign, members in groups.items():
            sid = f"{s['id']}.{campaign}" if doc.get('split_by_campaign') and campaign else s['id']
            samples.append({'id': sid, 'kind': s['kind'], 'dsid': s['dsid'], 'process': s['process'],
                            'campaign': campaign, 'members': members})
    result = {'schema_version': 1, 'kind': 'ravel-resolved-members', 'declaration': _pin(declaration),
              'membership_authority': authority, 'samples': samples}
    atomic_json(out, result)
    return result


# ---------------------------------------------------------------- normalization
def parse_xsec_db(path, descriptor):
    columns = descriptor.get('columns', {})
    _require({'dsid', 'cross_section', 'filter_efficiency', 'k_factor'} <= set(columns),
             'cross-section descriptor needs dsid, cross_section, filter_efficiency and k_factor columns')
    unit = descriptor.get('cross_section_unit')
    _require(unit in XSEC_UNITS, f'cross-section descriptor must declare cross_section_unit, one of {sorted(XSEC_UNITS)}')
    lines = [l for l in Path(path).read_text().splitlines() if l.strip() and not l.lstrip().startswith('#')]
    header = [h.split('/')[0] for h in lines[0].replace(':', ' ').split()]
    index = {}
    for key, name in columns.items():
        _require(name in header, f'column {name} is not in the cross-section database header')
        index[key] = header.index(name)
    rows = []
    for line in lines[1:]:
        fields = line.split()
        _require(len(fields) == len(header), 'cross-section database row has a different number of fields than its header')
        row = {'dsid': int(fields[index['dsid']])}
        for key in ('cross_section', 'filter_efficiency', 'k_factor'):
            row[key] = float(fields[index[key]])
        if 'etag' in index:
            row['etag'] = fields[index['etag']]
        row['cross_section_pb'] = row.pop('cross_section') * XSEC_UNITS[unit]
        rows.append(row)
    return rows


def _xsec(rows, dsid, select):
    matches = [r for r in rows if r['dsid'] == dsid and all(r.get(k) == v for k, v in (select or {}).items())]
    _require(matches, f'DSID {dsid} is not in the cross-section database')
    values = {(r['cross_section_pb'], r['filter_efficiency'], r['k_factor']) for r in matches}
    _require(len(values) == 1, f'DSID {dsid} has several different cross-section rows; declare a select (for example etag)')
    return matches[0]


def _open_uri(uri):
    import uproot
    return uproot.open(uri[len('file://'):] if uri.startswith('file://') else uri)


def member_sum_weights(member, sample, bookkeeper):
    kind = bookkeeper.get('kind')
    if kind == 'histogram':
        pattern = bookkeeper['object'].replace('{dsid}', str(sample['dsid']))
        with _open_uri(member['uri']) as f:
            names = sorted({k.split(';')[0] for k in f.keys(recursive=False)})
            hits = [n for n in names if fnmatch.fnmatchcase(n, pattern)]
            _require(len(hits) == 1, f"bookkeeper object {pattern} found {len(hits)} times in {member['id']}")
            values = f[hits[0]].values(flow=True)
            bin_number = bookkeeper['bin']
            _require(type(bin_number) is int and 0 <= bin_number < len(values), 'bookkeeper bin is outside the histogram')
            return float(values[bin_number]), hits[0]
    if kind == 'tree-sum':
        with _open_uri(member['uri']) as f:
            array = f[bookkeeper['tree']][bookkeeper['branch']].array(library='np')
            return math.fsum(float(x) for x in array), f"{bookkeeper['tree']}/{bookkeeper['branch']}"
    raise ValueError('bookkeeper kind must be histogram, tree-sum or table')


def normalize(resolved, out, *, xsec_db=None, xsec_descriptor=None, lumi=None, bookkeeper=None):
    resolved_path, out = Path(resolved), Path(out)
    doc = read_json(resolved_path)
    _require(doc.get('kind') == 'ravel-resolved-members', 'resolved members document required')
    _require(not out.exists(), f'{out} already exists')
    mc = [s for s in doc['samples'] if s['kind'] != 'data']
    sources_dir = out.with_name(out.stem + '.sources')
    _require(not sources_dir.exists(), f'{sources_dir} already exists')
    provenance = {'schema_version': 1, 'resolved_members': _pin(resolved_path), 'per_member_sum_weights': {}}
    if mc:
        _require(None not in (xsec_db, xsec_descriptor, lumi, bookkeeper),
                 'MC samples need a cross-section database, its descriptor, a luminosity table and a bookkeeper descriptor')
        descriptor = read_json(xsec_descriptor)
        rows = parse_xsec_db(xsec_db, descriptor)
        lumi_doc = read_json(lumi)
        _require(lumi_doc.get('unit') in LUMI_UNITS, f'luminosity table must declare unit, one of {sorted(LUMI_UNITS)}')
        keeper = read_json(bookkeeper)
        table = None
        if keeper.get('kind') == 'table':
            table = read_json(keeper['table'])['values']
            provenance['sum_weights_table'] = _pin(keeper['table'])
        provenance.update(xsec_db=_pin(xsec_db), xsec_descriptor=_pin(xsec_descriptor), luminosity=_pin(lumi),
                          bookkeeper=_pin(bookkeeper))
    sources_dir.mkdir(parents=True)
    samples = []
    for s in doc['samples']:
        sample = {'id': s['id'], 'kind': s['kind'], 'dsid': s['dsid'], 'process': s['process'], 'normalization': None,
                  'members': deepcopy(s['members'])}
        if s['kind'] != 'data':
            sums = []
            for m in s['members']:
                if table is not None:
                    _require(m['id'] in table, f"sum-of-weights table has no row for {m['id']}")
                    value, origin = float(table[m['id']]), 'table'
                else:
                    value, origin = member_sum_weights(m, s, keeper)
                provenance['per_member_sum_weights'][m['id']] = {'sum_weights': value, 'object': origin}
                sums.append(value)
            total = math.fsum(sums)
            _require(total != 0, f"sample {s['id']} has a zero sum of weights")
            row = _xsec(rows, s['dsid'], descriptor.get('select'))
            _require(s.get('campaign') in lumi_doc.get('campaigns', {}),
                     f"luminosity table has no entry for campaign {s.get('campaign')!r} of sample {s['id']}")
            luminosity = float(lumi_doc['campaigns'][s['campaign']]) * LUMI_UNITS[lumi_doc['unit']]
            original = _write(sources_dir / f"{s['id']}.population.json",
                              {'schema_version': 1, 'sample_id': s['id'], 'dsid': s['dsid'],
                               'members': [{'guid': m['guid'], 'did': m['did'], 'entries': m['entries']} for m in s['members']]})
            values = {'sum_weights': total, 'luminosity_fb_inverse': luminosity, 'cross_section_pb': row['cross_section_pb'],
                      'filter_efficiency': row['filter_efficiency'], 'k_factor': row['k_factor']}
            source = _write(sources_dir / f"{s['id']}.normalization.json",
                            {'schema_version': 1, 'sample_id': s['id'], 'dsid': s['dsid'],
                             'original_population_sha256': original['sha256'], **values})
            sample['normalization'] = {'source': source, 'original_population': original, **values}
        samples.append(sample)
    authority = _write(sources_dir / 'membership.json', {'schema_version': 1, 'samples': samples})
    dataset = {'schema_version': 1, 'membership_authority': authority, 'ordering': 'declared_sample_member_source_entry',
               'samples': samples}
    from ravel.physics import root_stream_core
    root_stream_core.dataset(dataset)
    atomic_json(out, dataset)
    atomic_json(out.with_name(out.stem + '.provenance.json'), provenance)
    return dataset


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog='ravel ntuples', description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    r = sub.add_parser('resolve', help='resolve declared dataset DIDs into ROOT members')
    r.add_argument('--declaration', type=Path, required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--listing', type=Path, help='supplied listing instead of querying rucio')
    n = sub.add_parser('normalize', help='build the root-stream dataset with MC normalization')
    n.add_argument('--resolved', type=Path, required=True)
    n.add_argument('--out', type=Path, required=True)
    n.add_argument('--xsec-db', type=Path)
    n.add_argument('--xsec-descriptor', type=Path)
    n.add_argument('--lumi', type=Path)
    n.add_argument('--bookkeeper', type=Path)
    args = ap.parse_args(argv)
    try:
        if args.command == 'resolve':
            result = resolve(args.declaration, args.out, listing=args.listing)
            print(json.dumps({'out': str(args.out), 'samples': [{'id': s['id'], 'members': len(s['members'])} for s in result['samples']]}, indent=2))
        else:
            result = normalize(args.resolved, args.out, xsec_db=args.xsec_db, xsec_descriptor=args.xsec_descriptor,
                               lumi=args.lumi, bookkeeper=args.bookkeeper)
            print(json.dumps({'out': str(args.out), 'samples': [{'id': s['id'], 'normalization': s['normalization'] and
                              {k: s['normalization'][k] for k in ('sum_weights', 'luminosity_fb_inverse', 'cross_section_pb',
                                                                  'filter_efficiency', 'k_factor')}} for s in result['samples']]}, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f'ravel ntuples: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
