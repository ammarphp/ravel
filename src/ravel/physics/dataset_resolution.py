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

``expand`` accepts a member-rule JSON with one tree/kind, a DSID process_map,
and rules containing pattern, dsid_pattern and campaign_pattern. The extraction
regexes declare named groups ``dsid`` and ``campaign``; an optional campaign_map
translates the captured tag. Raw container membership is kept and pinned.

Missing campaigns use campaigns.expected (or the MC luminosity-table keys),
with campaigns.missing_rule or each sample's missing_campaign_rule: exclude,
available-luminosity-only, or scale-to-full. The last also requires an assumption
(campaigns.assumption or sample.scale_assumption). The normalization provenance
records missing_campaigns keyed by sample, including total luminosity_used in
fb-1. Multiple dataset shards in a campaign_group share its full denominator.

For a whitespace table headed ``DSID sigma efficiency factor``, pass
``--xsec-db-descriptor descriptor.json`` with this descriptor::

    {"columns": {"dsid": "DSID", "cross_section": "sigma",
                 "filter_efficiency": "efficiency", "k_factor": "factor"},
     "cross_section_unit": "pb"}

Bookkeeping uses --workers (default 4), --timeout (60 seconds per attempt),
--retries (default 0), and --cache (default sum-weights-cache.json beside the
resolved document). The .bookkeeping.json sidecar reports timing and failures,
including on incomplete reads. Cache identity includes GUID, Adler32 and the
declared bookkeeping object/DSID; successful per-file entries alone are saved.
"""
from __future__ import annotations

import argparse
from collections import deque
from copy import deepcopy
import fnmatch
import hashlib
import json
import math
import multiprocessing
from multiprocessing.connection import wait
from pathlib import Path
import re
import sys
import time

from ravel.workflow.state_io import atomic_json, file_lock, read_json

XSEC_UNITS = {'pb': 1.0, 'nb': 1000.0, 'fb': 0.001, 'ub': 1.0e6}
LUMI_UNITS = {'fb-1': 1.0, 'pb-1': 0.001}
KINDS = ('background_mc', 'signal_mc', 'data')
MISSING_RULES = ('exclude', 'available-luminosity-only', 'scale-to-full')


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
def expand(container, member_rule, out, *, client=None, listing=None):
    """Expand direct dataset members using supplied regexes and a DSID process map.

    Rules contain ``pattern``, ``dsid_pattern`` (named group ``dsid``), and
    ``campaign_pattern`` (named group ``campaign``); optional ``campaign_map``
    translates captured tags. Tree/kind/process_map are declared once at the top.
    A listing is a JSON array of list_content rows, or {container, members}.
    Nested containers are refused rather than silently recursively flattened.
    """
    _require(isinstance(container, str) and all(container.split(':', 1)) and ':' in container,
             'container must be scope:name')
    spec = read_json(member_rule)
    _require(isinstance(spec, dict) and spec.get('schema_version') == 1, 'member-rule schema_version 1 required')
    _require(set(spec) <= {'schema_version', 'rules', 'tree', 'kind', 'process_map', 'campaigns', 'rse', 'scheme'},
             'unknown member-rule fields')
    _require(spec.get('kind') in ('background_mc', 'signal_mc'), 'expansion requires an MC kind')
    _require(isinstance(spec.get('tree'), str) and spec['tree'].strip(), 'member-rule needs tree')
    _require(isinstance(spec.get('process_map'), dict), 'member-rule needs process_map keyed by DSID')
    _require(isinstance(spec.get('rules'), list) and spec['rules'], 'member-rule needs rules')
    compiled = []
    for rule in spec['rules']:
        _require(isinstance(rule, dict) and {'pattern', 'dsid_pattern', 'campaign_pattern'} <= set(rule) and
                 set(rule) <= {'pattern', 'dsid_pattern', 'campaign_pattern', 'campaign_map'},
                 'each member rule needs pattern, dsid_pattern, campaign_pattern')
        _require('campaign_map' not in rule or isinstance(rule['campaign_map'], dict), 'campaign_map must be an object')
        dsid_re, campaign_re = re.compile(rule['dsid_pattern']), re.compile(rule['campaign_pattern'])
        _require('dsid' in dsid_re.groupindex and 'campaign' in campaign_re.groupindex,
                 'extraction patterns need named dsid and campaign groups')
        compiled.append((re.compile(rule['pattern']), dsid_re, campaign_re, rule))
    out = Path(out)
    authority_path = out.with_name(out.stem + '.container.json')
    _require(not out.exists() and not authority_path.exists(), 'expansion output or raw response already exists')
    if listing is not None:
        supplied = read_json(listing)
        if isinstance(supplied, dict):
            _require(supplied.get('container') == container, 'listing names a different container')
            members = supplied['members']
        else:
            members = supplied
        source = {'kind': 'listing', 'listing': _pin(listing)}
    else:
        client = client or rucio_client()
        scope, name = container.split(':', 1)
        members = [dict(r) for r in client.list_content(scope=scope, name=name)]
        # Rucio versions may return DIDType enums rather than JSON strings.
        members = [{k: (getattr(v, 'name', v) if k == 'type' else v) for k, v in m.items()} for m in members]
        source = {'kind': 'rucio'}
    _require(isinstance(members, list) and members, f'container {container} has no members')
    authority = _write(authority_path, {'schema_version': 1, 'container': container,
                                       'source': source, 'member_rule': _pin(member_rule), 'members': members})
    samples, failures, seen = [], [], set()
    for member in members:
        _require(isinstance(member, dict) and all(isinstance(member.get(k), str) and member[k] for k in ('scope', 'name')),
                 'container member needs scope and name')
        did = f"{member['scope']}:{member['name']}"
        hits = [r for r in compiled if r[0].search(did)]
        if did in seen or member.get('type', 'DATASET') != 'DATASET':
            failures.append(f'{did}: duplicate or non-dataset member')
        elif len(hits) != 1:
            failures.append(f'{did}: matches {len(hits)} member rules (exactly one required)')
        else:
            _, dsid_re, campaign_re, rule = hits[0]
            dsids, campaigns = list(dsid_re.finditer(did)), list(campaign_re.finditer(did))
            if len(dsids) != 1 or len(campaigns) != 1:
                failures.append(f'{did}: extraction must match dsid and campaign exactly once')
                continue
            dsid_text, campaign = dsids[0].group('dsid'), campaigns[0].group('campaign')
            if not dsid_text or not dsid_text.isdecimal() or int(dsid_text) <= 0 or not campaign:
                failures.append(f'{did}: invalid DSID or campaign extraction')
                continue
            dsid = int(dsid_text)
            if 'campaign_map' in rule:
                campaign = rule['campaign_map'].get(campaign)
            process = spec['process_map'].get(str(dsid))
            if not isinstance(campaign, str) or not campaign.strip() or not isinstance(process, str) or not process.strip():
                failures.append(f'{did}: campaign or process has no declared mapping')
                continue
            samples.append({'id': f'mc{dsid}.{hashlib.sha256(did.encode()).hexdigest()[:16]}',
                            'kind': spec['kind'], 'dsid': dsid, 'process': process, 'tree': spec['tree'],
                            'campaign': campaign, 'campaign_group': f"{spec['kind']}.{dsid}", 'dids': [did]})
        seen.add(did)
    _require(not failures, 'container expansion refused:\n' + '\n'.join(failures))
    result = {'schema_version': 1, 'samples': samples, 'expansion_authority': authority}
    for key in ('campaigns', 'rse', 'scheme'):
        if key in spec:
            result[key] = spec[key]
    atomic_json(out, result)
    return result


def load_declaration(path):
    doc = read_json(path)
    _require(isinstance(doc, dict) and doc.get('schema_version') == 1, 'declaration schema_version 1 required')
    _require(set(doc) <= {'schema_version', 'rse', 'samples', 'campaigns', 'split_by_campaign', 'scheme', 'expansion_authority'},
             'unknown declaration fields')
    _require(isinstance(doc.get('samples'), list) and doc['samples'], 'declaration needs samples')
    ids = set()
    for s in doc['samples']:
        required = {'id', 'kind', 'dsid', 'process', 'tree', 'dids'}
        _require(required <= set(s) and set(s) <= required | {'campaign', 'campaign_group', 'missing_campaign_rule', 'scale_assumption'},
                 'each sample needs id, kind, dsid, process, tree, dids and only supported campaign fields')
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
        for key in ('process', 'tree', 'campaign', 'campaign_group'):
            if key in s:
                _require(isinstance(s[key], str) and s[key].strip(), f'sample {key} must be a nonempty name')
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
            campaign = s.get('campaign') if 'campaign' in s else _campaign(doc, did)
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
                            'campaign': campaign, 'members': members,
                            'campaign_group': s.get('campaign_group', f"{s['kind']}.{s['dsid']}.{s['process']}"),
                            **{k: s[k] for k in ('missing_campaign_rule', 'scale_assumption') if k in s}})
    result = {'schema_version': 1, 'kind': 'ravel-resolved-members', 'declaration': _pin(declaration),
              'membership_authority': authority, 'samples': samples, 'campaigns': doc.get('campaigns', {})}
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
    _require(lines, 'cross-section database has no header')
    header = [h.split('/')[0] for h in lines[0].replace(':', ' ').split()]
    index = {}
    for key, name in columns.items():
        _require(header.count(name) == 1, f'column {name} must occur exactly once in the cross-section database header')
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
        _require(all(math.isfinite(row[k]) and row[k] >= 0 for k in
                     ('cross_section_pb', 'filter_efficiency', 'k_factor')), 'cross-section factors must be finite and nonnegative')
        rows.append(row)
    return rows


def _xsec(rows, dsid, select):
    matches = [r for r in rows if r['dsid'] == dsid and all(r.get(k) == v for k, v in (select or {}).items())]
    _require(matches, f'DSID {dsid} is not in the cross-section database')
    _require(len(matches) == 1, f'DSID {dsid} has {len(matches)} cross-section rows; exactly one required (declare select if needed)')
    return matches[0]


def _open_uri(uri):
    import uproot
    return uproot.open(uri[len('file://'):] if uri.startswith('file://') else uri)


def _read_member_sum_weights(member, sample, bookkeeper):
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


def _cache_key(member, sample, bookkeeper):
    adler = member.get('checksum', {})
    _require(adler.get('algorithm') == 'adler32' and
             re.fullmatch('[0-9a-fA-F]{1,8}', str(adler.get('value', ''))) is not None and member.get('guid'),
             f"bookkeeping cache requires GUID and Adler32 for {member['id']}")
    # The file identity is not sufficient if the caller changes the bin/branch.
    context = json.dumps({'dsid': sample['dsid'], 'bookkeeper': bookkeeper}, sort_keys=True)
    return json.dumps([member['guid'], adler['value'].lower().zfill(8),
                       hashlib.sha256(context.encode()).hexdigest()])


def _load_cache(cache):
    if isinstance(cache, dict):
        doc = cache
    elif cache is not None and Path(cache).exists():
        doc = read_json(cache)
    else:
        doc = {'schema_version': 1, 'entries': {}}
    _require(doc.get('schema_version') == 1 and isinstance(doc.get('entries'), dict), 'bookkeeping cache schema_version 1 required')
    return doc


def _save_cache(cache, entries):
    if cache is None:
        return
    if isinstance(cache, dict):
        cache['entries'].update(entries)
    else:
        path = Path(cache)
        with file_lock(path.with_name(path.name + '.lock')):
            current = _load_cache(path)
            current['entries'].update(entries)
            atomic_json(path, current)


def _bookkeeping_child(conn, member, sample, bookkeeper):
    try:
        value, origin = _read_member_sum_weights(member, sample, bookkeeper)
        _require(math.isfinite(value), f"non-finite sum of weights for {member['id']}")
        conn.send((True, value, origin))
    except Exception as exc:
        conn.send((False, f'{type(exc).__name__}: {exc}'))
    finally:
        conn.close()


def _reap(process):
    process.join(timeout=0.1)
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)
    _require(not process.is_alive(), f'bookkeeping worker {process.pid} could not be stopped')
    process.close()


def _bookkeeping(jobs, bookkeeper, *, cache=None, workers=4, timeout=60.0, retries=0):
    """Hard per-attempt deadlines; at most workers independent reader processes.

    Failed/partial batch results never become a normalization dataset. Successful
    individual cache entries survive a failed batch so its retry need not reread
    healthy files. The parent alone merges and atomically saves the cache.
    """
    _require(type(workers) is int and 1 <= workers <= 64, 'bookkeeping workers must be an integer from 1 to 64')
    _require(type(retries) is int and retries >= 0, 'bookkeeping retries must be a nonnegative integer')
    _require(isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and math.isfinite(timeout) and timeout > 0,
             'bookkeeping timeout must be finite and positive')
    start = time.monotonic()
    cache_doc = _load_cache(cache)
    entries, results, failures, pending, active = {}, {}, {}, deque(), {}
    hits, reads, attempts = 0, 0, 0
    for member, sample in jobs:
        key = _cache_key(member, sample, bookkeeper)
        cached = cache_doc['entries'].get(key)
        if cached is not None:
            _require(isinstance(cached, dict) and cached.get('complete') is True and
                     isinstance(cached.get('sum_weights'), (int, float)) and math.isfinite(cached['sum_weights']) and
                     isinstance(cached.get('object'), str), f"invalid cached bookkeeping for {member['id']}")
            results[member['id']] = (float(cached['sum_weights']), cached['object'])
            hits += 1
        else:
            pending.append((member, sample, key, 0))
    # fork preserves injected reader seams in synthetic tests; spawn on platforms
    # without fork. No socket server or site credential handling is introduced.
    ctx = multiprocessing.get_context('fork' if 'fork' in multiprocessing.get_all_start_methods() else 'spawn')
    try:
        while pending or active:
            while pending and len(active) < workers:
                job = pending.popleft()
                parent, child = ctx.Pipe(duplex=False)
                process = ctx.Process(target=_bookkeeping_child, args=(child, job[0], job[1], bookkeeper))
                try:
                    process.start()
                except BaseException:
                    parent.close(); child.close()
                    raise
                child.close()
                active[parent] = (process, time.monotonic() + timeout, job)
                attempts += 1
            ready = wait(active, timeout=max(0, min(deadline for _, deadline, _ in active.values()) - time.monotonic()))
            for conn, (process, deadline, job) in list(active.items()):
                if conn not in ready and time.monotonic() < deadline and process.is_alive():
                    continue
                member, sample, key, attempt = job
                if conn in ready or conn.poll():
                    try:
                        reply = conn.recv()
                    except (EOFError, OSError):
                        reply = (False, 'bookkeeping reader exited without a result')
                else:
                    reply = (False, f'bookkeeping timeout after {timeout:g}s' if time.monotonic() >= deadline
                             else 'bookkeeping reader exited without a result')
                conn.close()
                _reap(process)
                del active[conn]
                if reply[0]:
                    results[member['id']] = (reply[1], reply[2])
                    entries[key] = {'complete': True, 'sum_weights': reply[1], 'object': reply[2]}
                    reads += 1
                elif attempt < retries:
                    pending.append((member, sample, key, attempt + 1))
                else:
                    failures[member['id']] = reply[1]
    finally:
        for conn, (process, _, _) in active.items():
            conn.close()
            _reap(process)
    _save_cache(cache, entries)
    elapsed = time.monotonic() - start
    timing = {'complete': not failures, 'workers': workers, 'timeout_seconds': timeout, 'retries': retries,
              'files': len(jobs), 'cache_hits': hits, 'files_read': reads, 'attempts': attempts,
              'elapsed_seconds': elapsed, 'files_per_second': reads / elapsed if elapsed else 0.0,
              'failures': failures}
    return results, timing


def member_sum_weights(member, sample, bookkeeper, *, cache=None, timeout=60.0, retries=0):
    results, timing = _bookkeeping([(member, sample)], bookkeeper, cache=cache, workers=1, timeout=timeout, retries=retries)
    _require(timing['complete'], f"bookkeeping failed: {timing['failures']}")
    return results[member['id']]


def _campaign_plan(doc, mc, lumi_doc):
    config = doc.get('campaigns', {})
    data_campaigns = {s.get('campaign') for s in doc['samples'] if s['kind'] == 'data'}
    expected = config.get('expected', [c for c in lumi_doc['campaigns'] if c not in data_campaigns])
    _require(isinstance(expected, list) and expected and len(set(expected)) == len(expected) and
             all(isinstance(c, str) and c for c in expected), 'expected campaigns must be unique nonempty names')
    lumis = {c: float(v) * LUMI_UNITS[lumi_doc['unit']] for c, v in lumi_doc['campaigns'].items()}
    _require(all(math.isfinite(v) and v >= 0 for v in lumis.values()), 'campaign luminosities must be finite and nonnegative')
    _require(set(expected) <= set(lumis), f'luminosity table has no entry for expected campaigns {sorted(set(expected) - set(lumis))}')
    groups, ledger, policies, errors = {}, {}, {}, []
    for sample in mc:
        group = sample.get('campaign_group', f"{sample['kind']}.{sample['dsid']}.{sample['process']}")
        groups.setdefault(group, []).append(sample)
    for group, samples in groups.items():
        _require(len({(s['kind'], s['dsid'], s['process']) for s in samples}) == 1, f'campaign group {group} mixes physical samples')
        present = {s.get('campaign') for s in samples}
        _require(present <= set(expected), f'sample {group} has undeclared campaigns {sorted(map(str, present - set(expected)))}')
        missing = sorted(set(expected) - present)
        rules = {s.get('missing_campaign_rule', config.get('missing_rule')) for s in samples}
        assumptions = {s.get('scale_assumption', config.get('assumption')) for s in samples}
        _require(len(rules) == 1 and len(assumptions) == 1, f'sample {group} has inconsistent missing-campaign declarations')
        rule, assumption = next(iter(rules)), next(iter(assumptions))
        _require(rule is None or rule in MISSING_RULES, f'sample {group} has unsupported missing-campaign rule {rule}')
        if missing and rule is None:
            errors.append(f"sample {group} ({', '.join(s['id'] for s in samples)}) missing campaigns {', '.join(missing)}; declare a missing-campaign rule")
            continue
        if missing and rule == 'scale-to-full':
            _require(isinstance(assumption, str) and assumption.strip(), f'sample {group} scale-to-full needs a stated assumption')
        available, full = math.fsum(lumis[c] for c in present), math.fsum(lumis[c] for c in expected)
        _require(not (missing and rule == 'scale-to-full') or available > 0, f'sample {group} has no positive available luminosity')
        used = 0.0 if missing and rule == 'exclude' else full if missing and rule == 'scale-to-full' else available
        for s in samples:
            ledger[s['id']] = {'missing': missing, 'rule': rule, 'luminosity_used': used,
                               'unit': 'fb-1', 'campaign_group': group, 'available_luminosity': available}
            if assumption is not None:
                ledger[s['id']]['assumption'] = assumption
            policies[s['id']] = {'excluded': bool(missing and rule == 'exclude'),
                                 'luminosity': lumis[s['campaign']] * (full / available if missing and rule == 'scale-to-full' else 1),
                                 'group': (group, s['campaign'])}
    _require(not errors, 'missing campaigns:\n' + '\n'.join(errors))
    return ledger, policies


def normalize(resolved, out, *, xsec_db=None, xsec_descriptor=None, lumi=None, bookkeeper=None,
              cache=None, workers=4, timeout=60.0, retries=0):
    resolved_path, out = Path(resolved), Path(out)
    doc = read_json(resolved_path)
    _require(doc.get('kind') == 'ravel-resolved-members', 'resolved members document required')
    _require(isinstance(doc.get('samples'), list) and doc['samples'], 'resolved document needs samples')
    _require(all(isinstance(s.get('id'), str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', s['id']) and
                 s['id'] not in ('.', '..') for s in doc['samples']) and
             len({s['id'] for s in doc['samples']}) == len(doc['samples']), 'resolved sample ids must be unique plain names')
    _require(not out.exists(), f'{out} already exists')
    mc = [s for s in doc['samples'] if s['kind'] != 'data']
    sources_dir = out.with_name(out.stem + '.sources')
    _require(not sources_dir.exists(), f'{sources_dir} already exists')
    provenance = {'schema_version': 1, 'resolved_members': _pin(resolved_path), 'per_member_sum_weights': {},
                  'missing_campaigns': {}}
    policies, group_members, group_sums = {}, {}, {}
    if mc:
        _require(None not in (xsec_db, xsec_descriptor, lumi, bookkeeper),
                 'MC samples need a cross-section database, its descriptor, a luminosity table and a bookkeeper descriptor')
        descriptor = read_json(xsec_descriptor)
        rows = parse_xsec_db(xsec_db, descriptor)
        xsecs, errors = {}, []
        for dsid in sorted({s['dsid'] for s in mc}):
            try:
                xsecs[dsid] = _xsec(rows, dsid, descriptor.get('select'))
            except ValueError as exc:
                errors.append(str(exc))
        _require(not errors, 'cross-section database resolution refused:\n' + '\n'.join(errors))
        lumi_doc = read_json(lumi)
        _require(lumi_doc.get('unit') in LUMI_UNITS, f'luminosity table must declare unit, one of {sorted(LUMI_UNITS)}')
        provenance['missing_campaigns'], policies = _campaign_plan(doc, mc, lumi_doc)
        keeper = read_json(bookkeeper)
        table = None
        if keeper.get('kind') == 'table':
            table = read_json(keeper['table'])['values']
            provenance['sum_weights_table'] = _pin(keeper['table'])
        provenance.update(xsec_db=_pin(xsec_db), xsec_descriptor=_pin(xsec_descriptor), luminosity=_pin(lumi),
                          bookkeeper=_pin(bookkeeper))
        jobs = [(m, s) for s in mc if not policies[s['id']]['excluded'] for m in s['members']]
        _require(len({m['id'] for m, _ in jobs}) == len(jobs), 'duplicate bookkeeping member IDs')
        if table is not None:
            missing_rows = [m['id'] for m, _ in jobs if m['id'] not in table]
            _require(not missing_rows, f'sum-of-weights table has no rows for {missing_rows}')
            results = {m['id']: (float(table[m['id']]), 'table') for m, _ in jobs}
            _require(all(math.isfinite(value) for value, _ in results.values()), 'sum-of-weights table needs finite values')
        else:
            cache = cache if cache is not None else resolved_path.with_name('sum-weights-cache.json')
            results, timing = _bookkeeping(jobs, keeper, cache=cache, workers=workers, timeout=timeout, retries=retries)
            _write(out.with_name(out.stem + '.bookkeeping.json'), timing)
            _require(timing['complete'], 'bookkeeping incomplete:\n' + '\n'.join(f'{k}: {v}' for k, v in timing['failures'].items()))
            provenance['bookkeeping'] = timing
        for member, sample in jobs:
            value, origin = results[member['id']]
            provenance['per_member_sum_weights'][member['id']] = {'sum_weights': value, 'object': origin}
            group = policies[sample['id']]['group']
            group_members.setdefault(group, []).append(member)
            group_sums.setdefault(group, []).append(value)
        group_sums = {group: math.fsum(values) for group, values in group_sums.items()}
        _require(all(value != 0 for value in group_sums.values()), 'sample has a zero sum of weights')
    _require(any(s['kind'] == 'data' or not policies[s['id']]['excluded'] for s in doc['samples']),
             'all samples were excluded by their missing-campaign rules; no dataset written')
    sources_dir.mkdir(parents=True)
    samples = []
    for s in doc['samples']:
        if s['kind'] != 'data' and policies[s['id']]['excluded']:
            continue
        sample = {'id': s['id'], 'kind': s['kind'], 'dsid': s['dsid'], 'process': s['process'], 'normalization': None,
                  'members': deepcopy(s['members'])}
        if s['kind'] != 'data':
            group = policies[s['id']]['group']
            total = group_sums[group]
            row = xsecs[s['dsid']]
            luminosity = policies[s['id']]['luminosity']
            original = _write(sources_dir / f"{s['id']}.population.json",
                              {'schema_version': 1, 'sample_id': s['id'], 'dsid': s['dsid'],
                               'members': [{'guid': m['guid'], 'did': m['did'], 'entries': m['entries']} for m in group_members[group]]})
            values = {'sum_weights': total, 'luminosity_fb_inverse': luminosity, 'cross_section_pb': row['cross_section_pb'],
                      'filter_efficiency': row['filter_efficiency'], 'k_factor': row['k_factor']}
            source = _write(sources_dir / f"{s['id']}.normalization.json",
                            {'schema_version': 1, 'sample_id': s['id'], 'dsid': s['dsid'],
                             'original_population_sha256': original['sha256'],
                             'missing_campaigns': provenance['missing_campaigns'][s['id']], **values})
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
    e = sub.add_parser('expand', help='expand container dataset members using declared regexes and process mappings')
    e.add_argument('--container', required=True)
    e.add_argument('--member-rule', type=Path, required=True)
    e.add_argument('--out', type=Path, required=True)
    e.add_argument('--listing', type=Path, help='supplied list_content rows instead of querying rucio')
    r = sub.add_parser('resolve', help='resolve declared dataset DIDs into ROOT members')
    r.add_argument('--declaration', type=Path, required=True)
    r.add_argument('--out', type=Path, required=True)
    r.add_argument('--listing', type=Path, help='supplied listing instead of querying rucio')
    n = sub.add_parser('normalize', help='build the root-stream dataset with MC normalization')
    n.add_argument('--resolved', type=Path, required=True)
    n.add_argument('--out', type=Path, required=True)
    n.add_argument('--xsec-db', type=Path)
    n.add_argument('--xsec-descriptor', '--xsec-db-descriptor', dest='xsec_descriptor', type=Path,
                   help='JSON column mapping and cross_section_unit for the supplied header table')
    n.add_argument('--lumi', type=Path)
    n.add_argument('--bookkeeper', type=Path)
    n.add_argument('--cache', type=Path, help='GUID/Adler32/bookkeeper cache (default beside resolved members)')
    n.add_argument('--workers', type=int, default=4)
    n.add_argument('--timeout', type=float, default=60.0, help='per-file attempt deadline in seconds')
    n.add_argument('--retries', type=int, default=0)
    args = ap.parse_args(argv)
    try:
        if args.command == 'expand':
            result = expand(args.container, args.member_rule, args.out, listing=args.listing)
            print(json.dumps({'out': str(args.out), 'samples': len(result['samples'])}, indent=2))
        elif args.command == 'resolve':
            result = resolve(args.declaration, args.out, listing=args.listing)
            print(json.dumps({'out': str(args.out), 'samples': [{'id': s['id'], 'members': len(s['members'])} for s in result['samples']]}, indent=2))
        else:
            result = normalize(args.resolved, args.out, xsec_db=args.xsec_db, xsec_descriptor=args.xsec_descriptor,
                               lumi=args.lumi, bookkeeper=args.bookkeeper, cache=args.cache,
                               workers=args.workers, timeout=args.timeout, retries=args.retries)
            print(json.dumps({'out': str(args.out), 'samples': [{'id': s['id'], 'normalization': s['normalization'] and
                              {k: s['normalization'][k] for k in ('sum_weights', 'luminosity_fb_inverse', 'cross_section_pb',
                                                                  'filter_efficiency', 'k_factor')}} for s in result['samples']]}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, re.error) as exc:
        print(f'ravel ntuples: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
