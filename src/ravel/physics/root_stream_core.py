"""Closed source contracts and bounded independent-event ROOT stream moments.

No scientific SDK, remote reader or credential import at preparation. Interval
coverage is the event-identity authority; a stream result is not a mergeable
legacy quantities state with omitted identity lists.
"""
from copy import deepcopy
import math
from urllib.parse import urlsplit
from ravel.physics import quantities
from ravel.physics.dataset_query_quantities_core import Capture, keys, pin, text, integer, strict, digest

SCOPE = 'root-stream-delivery'
VERSIONS = {'numpy': '1.26.4', 'awkward': '2.6.7', 'uproot': '5.3.12',
            'fsspec': '2026.9.0', 'fsspec-xrootd': '0.5.5', 'xrootd': '6.2.0'}
KINDS = ('background_mc', 'signal_mc', 'data')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def scalar(value):
    result = quantities._number(value, 'finite ROOT stream scalar')
    if type(value) is int and int(result) != value:
        raise ValueError('integer cannot be represented exactly by float64')
    return result


def relative(value):
    from pathlib import PurePosixPath
    text(value, 'relative bundle member')
    p = PurePosixPath(value)
    require(not p.is_absolute() and p.as_posix() == value and
            not any(x in ('', '.', '..') for x in value.split('/')),
            'literal relative bundle member required')
    return value


def dataset(value):
    keys(value, ('schema_version', 'membership_authority', 'ordering', 'samples'), 'ROOT dataset')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'ROOT dataset schema1 required')
    pin(value['membership_authority'])
    require(value['ordering'] == 'declared_sample_member_source_entry', 'source order required')
    require(type(value['samples']) is list and 1 <= len(value['samples']) <= 10000, 'complete bounded samples required')
    samples, members, uris, guids = set(), set(), set(), set()
    for s in value['samples']:
        keys(s, ('id', 'kind', 'dsid', 'process', 'normalization', 'members'), 'sample')
        text(s['id']); text(s['process'])
        require(s['id'] not in samples and s['kind'] in KINDS, 'unique explicit sample/kind required')
        samples.add(s['id'])
        if s['kind'] == 'data':
            require(s['dsid'] is None and s['normalization'] is None, 'data must not inherit MC normalization')
        else:
            integer(s['dsid'], 1, 10**12, 'explicit DSID')
            n = s['normalization']
            keys(n, ('source', 'original_population', 'sum_weights', 'luminosity_fb_inverse',
                     'cross_section_pb', 'filter_efficiency', 'k_factor'), 'original MC normalization')
            pin(n['source']); pin(n['original_population'])
            require(scalar(n['sum_weights']) != 0, 'nonzero original full sum of weights required')
            for name in ('luminosity_fb_inverse', 'cross_section_pb', 'filter_efficiency', 'k_factor'):
                require(scalar(n[name]) >= 0, 'nonnegative declared MC normalization factor required')
            scale(s)
        require(type(s['members']) is list and s['members'], 'complete nonempty member population required')
        for m in s['members']:
            keys(m, ('id', 'did', 'guid', 'uri', 'tree', 'entries', 'size_bytes', 'checksum'), 'ROOT member')
            for name in ('id', 'did', 'guid', 'tree'): text(m[name], name)
            text(m['uri'], 'unsigned source URI')
            u = urlsplit(m['uri'])
            require(u.scheme in ('file', 'root') and not (u.username or u.password or u.query or u.fragment),
                    'literal file/root URI without embedded credentials required')
            require(u.path.startswith('/') and (u.scheme != 'file' or u.netloc in ('', 'localhost')) and (u.scheme != 'root' or u.hostname), 'absolute local/remote member path required')
            require(not any(c in m['uri'] for c in '*?[]\n\r'), 'membership cannot be a glob')
            require(m['id'] not in members and m['guid'] not in guids and m['uri'] not in uris,
                    'aliased/duplicate member refused')
            members.add(m['id']); guids.add(m['guid']); uris.add(m['uri'])
            integer(m['entries'], 0, 10**15, 'complete expected entries')
            integer(m['size_bytes'], 0, 10**15, 'expected member size')
            c = m['checksum']; keys(c, ('algorithm', 'value', 'authority'), 'checksum')
            import re
            require(c['algorithm'] in ('sha256', 'adler32') and type(c['value']) is str and
                    re.fullmatch('[a-f0-9]{64}' if c['algorithm'] == 'sha256' else '[a-f0-9]{8}', c['value']) is not None,
                    'explicit checksum algorithm/value required')
            pin(c['authority'])
    return deepcopy(value)


def scale(sample):
    if sample['kind'] == 'data': return 1.0
    n = sample['normalization']
    from ravel.physics.normalization_ledger import event_scale
    return scalar(event_scale(luminosity_fb=scalar(n['luminosity_fb_inverse']), cross_section_pb=scalar(n['cross_section_pb']),
                              filter_efficiency=scalar(n['filter_efficiency']), k_factor=scalar(n['k_factor']),
                              sum_weights=scalar(n['sum_weights'])))


def analysis(value, ds):
    keys(value, ('schema_version', 'original_goal', 'branch_contract', 'weight_contract', 'quantities', 'blinding'), 'ROOT analysis')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'analysis schema1 required')
    pin(value['original_goal'])
    branches = value['branch_contract']
    require(type(branches) is list and 1 <= len(branches) <= 1024, 'explicit bounded branch census required')
    seen = {}
    for b in branches:
        keys(b, ('name', 'shape', 'dtype', 'unit'), 'branch semantics')
        text(b['name']); text(b['unit'])
        require(b['name'] not in seen and b['shape'] in ('scalar', 'jagged') and
                b['dtype'] in ('float64', 'float32', 'int64', 'uint64', 'int32', 'uint32', 'int8', 'uint8', 'bool'),
                'distinct branch shape/dtype required')
        seen[b['name']] = b
    w = value['weight_contract']
    keys(w, ('raw_mc_weight', 'scale_factors', 'variations', *(['derived_factor'] if 'derived_factor' in w else [])), 'event weights')
    if 'derived_factor' in w:
        require('__ravel_derived_nominal_factor__' not in seen, 'internal derived factor cannot be a source branch')
        f = w['derived_factor']; keys(f, ('entry', 'source', 'semantics'), 'source-derived nominal factor')
        relative(f['entry']); pin(f['source'])
        require(f['semantics'] == 'source_declared_nominal_event_sf' and not w['variations'],
                'explicit nominal-only factor law required')
    require(w['raw_mc_weight'] is None or type(w['raw_mc_weight']) is str, 'explicit raw MC branch or null required')
    require(type(w['scale_factors']) is list and len(set(w['scale_factors'])) == len(w['scale_factors']), 'distinct scalar scale factors required')
    require(type(w['variations']) is list and len(w['variations']) <= 32, 'bounded variation factors required')
    names, weighted_branches = {'nominal'}, set(w['scale_factors'])
    if w['raw_mc_weight'] is not None: weighted_branches.add(w['raw_mc_weight'])
    for v in w['variations']:
        keys(v, ('name', 'branch', 'semantics'), 'variation factor')
        text(v['name']); text(v['branch'])
        require(v['name'] not in names and v['semantics'] == 'multiplicative_event_factor', 'explicit unique variation law required')
        names.add(v['name']); weighted_branches.add(v['branch'])
    for b in weighted_branches:
        require(b in seen and seen[b]['shape'] == 'scalar' and seen[b]['dtype'] != 'bool', 'weight source must be a declared scalar numeric branch')
    if any(s['kind'] != 'data' for s in ds['samples']): require(w['raw_mc_weight'] is not None, 'MC raw weight branch required')
    qs = value['quantities']
    require(type(qs) is list and 1 <= len(qs) <= 32, 'full bounded quantity population required')
    ids = set()
    for q in qs:
        keys(q, ('id', 'contract'), 'quantity')
        text(q['id']); require(q['id'] not in ids, 'distinct quantity ids required'); ids.add(q['id'])
        c = quantities.validate(q['contract'])
        require(c['weight_names'] == ['nominal', *[v['name'] for v in w['variations']]], 'complete ordered weight population required')
        require(c['normalization']['kind'] == 'absolute' and c['normalization']['scale'] == 1.0, 'explicit output unit and source sample normalization applied once after stream accumulation required')
    b = value['blinding']
    if any(s['kind'] == 'data' for s in ds['samples']):
        keys(b, ('policy', 'source', 'blind_entry', 'allowed_regions', 'model_fields'), 'blinded data access')
        require(b['policy'] == 'exclude_signal_regions', 'data SR exclusion is mandatory')
        pin(b['source']); relative(b['blind_entry'])
        require(type(b['allowed_regions']) is list and b['allowed_regions'] and
                len(set(b['allowed_regions'])) == len(b['allowed_regions']), 'explicit admitted control/validation regions required')
        for r in b['allowed_regions']: text(r)
        keys(b['model_fields'], tuple(q['id'] for q in qs), 'allowed model quantity fields')
        for q in qs:
            allowed=b['model_fields'][q['id']]
            require(type(allowed) is list and allowed and len(set(allowed))==len(allowed) and
                    set(allowed)<=set(b['allowed_regions']) and set(allowed)<=set(x['id'] for x in q['contract']['bins']),
                    'only original allowed CR/VR bin IDs may be public data fields')
    else:
        require(b is None, 'MC-only task has no data blinding kernel')
    return deepcopy(value)


def config(value):
    if type(value) is dict and value.get('schema_version')==2:
        from ravel.physics.root_stream_partitions import config as partition_config
        return partition_config(value)
    keys(value, ('schema_version', 'dataset', 'analysis', 'bundle', 'runtime', 'site', 'limits'), 'ROOT config')
    require(type(value['schema_version']) is int and value['schema_version'] == 1, 'ROOT config schema1 required')
    pin(value['dataset']); pin(value['analysis'])
    b = value['bundle']
    keys(b, ('entry', 'blind_entry', 'files', 'review_source'), 'reviewed kernel bundle')
    relative(b['entry']); pin(b['review_source'])
    require(b['blind_entry'] is None or type(b['blind_entry']) is str, 'explicit conditional blind entry required')
    if b['blind_entry'] is not None: relative(b['blind_entry'])
    require(type(b['files']) is dict and 1 <= len(b['files']) <= 128 and b['entry'] in b['files'] and
            (b['blind_entry'] is None or b['blind_entry'] in b['files']), 'complete bounded kernel bundle required')
    for name, p in b['files'].items(): relative(name); pin(p)
    require(b['entry'].endswith('.py') and (b['blind_entry'] is None or b['blind_entry'].endswith('.py')), 'explicit Python entry required')
    rt = value['runtime']
    keys(rt, ('python', 'site_roots', 'trees', 'versions'), 'complete runtime')
    pin(rt['python']); require(rt['versions'] == VERSIONS, 'exact required site analysis versions required')
    require(type(rt['site_roots']) is list and 1 <= len(rt['site_roots']) <= 16, 'bounded site roots required')
    require(type(rt['trees']) is list and 1 <= len(rt['trees']) <= 16, 'complete runtime source trees required')
    for t in rt['trees']:
        keys(t, ('root', 'manifest'), 'runtime tree'); text(t['root']); pin(t['manifest'])
    site = value['site']
    keys(site, ('id', 'rse', 'allowed_hosts', 'read_timeout_seconds', 'credential_reference', 'durable_output_policy'), 'site policy')
    text(site['id']); text(site['rse'])
    require(type(site['allowed_hosts']) is list and site['allowed_hosts'] and len(set(site['allowed_hosts'])) == len(site['allowed_hosts']), 'explicit allowed hosts required')
    for h in site['allowed_hosts']: require(type(h) is str and h and not any(c in h for c in '/:@\n\r'), 'bare allowed hostname required')
    integer(site['read_timeout_seconds'], 1, 3600, 'finite read timeout')
    require(site['durable_output_policy'] == 'persistent_site_output', 'durable site output required')
    ref = site['credential_reference']
    if ref is not None:
        keys(ref, ('name', 'target'), 'credential reference')
        import re
        require(type(ref['name']) is str and re.fullmatch('[A-Z][A-Z0-9_]{0,127}', ref['name']) is not None and
                ref['target'] in ('X509_USER_PROXY', 'BEARER_TOKEN_FILE'), 'explicit supported private credential reference required')
    ls = value['limits']
    keys(ls, ('max_seconds', 'max_ram_mib', 'max_output_bytes', 'chunk_entries', 'max_members', 'max_chunks', 'max_quantity_dimensions'), 'stream limits')
    bounds = {'max_seconds':86400, 'max_ram_mib':131072, 'max_output_bytes':4*1024**3,
              'chunk_entries':1000000, 'max_members':1000000, 'max_chunks':10000000, 'max_quantity_dimensions':512}
    for name, maximum in bounds.items(): integer(ls[name], 1, maximum, name)
    return deepcopy(value)


class Adder:
    """Bounded floating expansion for streaming sums (no event list)."""
    def __init__(self): self.partials = []
    def add(self, value):
        value = scalar(value); i = 0
        for p in self.partials:
            if abs(value) < abs(p): value, p = p, value
            hi = scalar(value + p); lo = p - (hi - value)
            if lo:
                self.partials[i] = lo; i += 1
            value = hi
        self.partials[i:] = [value]
        require(len(self.partials) <= 2048, 'finite sum expansion ceiling exceeded')
    def value(self): return scalar(math.fsum(self.partials))


class Moments:
    """One event is one independent group; its multiple fills stay correlated."""
    def __init__(self, contract):
        self.contract = quantities.validate(contract)
        self.bins = self.contract['bins']; self.names = self.contract['weight_names']
        self.stride = len(self.bins) + 2; d = self.stride * len(self.names)
        self.sums = [Adder() for _ in range(d)]
        self.products = [[Adder() for _ in range(d)] for _ in range(d)]
        self.counts = dict.fromkeys(('records','fills','in_range','flow','empty_records'), 0)
        self.negative = dict.fromkeys(self.names, 0)
    def event(self, weights, fills):
        keys(weights, self.names, 'complete event weights')
        require(type(fills) is list, 'event fill list required')
        multiplicities = {}
        for fill in fills:
            require(type(fill) is list and len(fill) == len(self.contract['axes']), 'fill dimensions differ')
            for x in fill: scalar(x)
            i = next((j for j, b in enumerate(self.bins) if all(lo <= x < hi for x,lo,hi in zip(fill,b['low'],b['high']))), len(self.bins))
            multiplicities[i] = multiplicities.get(i,0) + 1
            self.counts['fills'] += 1
            self.counts['in_range' if i < len(self.bins) else 'flow'] += 1
        self.counts['records'] += 1; self.counts['empty_records'] += not fills
        vector = {}
        for k, name in enumerate(self.names):
            w = scalar(weights[name]); self.negative[name] += w < 0
            for i, n in multiplicities.items(): vector[k*self.stride+i] = scalar(w*n)
            vector[k*self.stride+len(self.bins)+1] = w
        for i, a in vector.items():
            self.sums[i].add(a)
            for j, b in vector.items():
                if j >= i: self.products[i][j].add(scalar(a*b))
    def result(self, sample_scale):
        d = len(self.sums)
        state = {'sumw':[a.value() for a in self.sums],
                 'second_moment':[[self.products[min(i,j)][max(i,j)].value() for j in range(d)] for i in range(d)],
                 'counts':dict(self.counts), 'negative_weight_records':dict(self.negative)}
        c = deepcopy(self.contract); c['normalization']['scale'] = scalar(sample_scale)
        result = quantities._project(c, state)
        result['kind'] = 'stream_weighted_quantities'
        result['identity_scope'] = 'authenticated complete member-entry interval census; one independent physical event per source entry'
        return result


def weights(sample, contract, row):
    if sample['kind'] == 'data':
        return {'nominal':1.0, **{v['name']:1.0 for v in contract['variations']}}
    nominal = scalar(row[contract['raw_mc_weight']])
    for name in contract['scale_factors']: nominal = scalar(nominal*scalar(row[name]))
    if 'derived_factor' in contract:
        factor = scalar(row['__ravel_derived_nominal_factor__'])
        require(factor >= 0, 'nonnegative source-declared nominal SF required')
        nominal = scalar(nominal * factor)
    return {'nominal':nominal, **{v['name']:scalar(nominal*scalar(row[v['branch']])) for v in contract['variations']}}


class Stream:
    """Complete ordered range ledger plus bounded moments, never chunk-normalized."""
    def __init__(self, ds, a, limits):
        self.ds, self.a, self.limits = ds, a, limits
        self.members = [(s,m) for s in ds['samples'] for m in s['members']]
        require(len(self.members) <= limits['max_members'], 'full source members exceed bound')
        self.index = 0; self.offset = 0; self.coverage = []; self.chunks = 0
        self.raw = {s['id']:(Adder(),Adder()) for s in ds['samples'] if s['kind'] != 'data'}
        self.moments = {s['id']:{q['id']:Moments(q['contract']) for q in a['quantities']} for s in ds['samples']}
        require(sum((len(q['contract']['bins'])+2)*len(q['contract']['weight_names']) for q in a['quantities']) <= limits['max_quantity_dimensions'], 'quantity dimension bound exceeded')
    def chunk(self, sample_id, member_id, start, stop, entries, records, weight_rows):
        require(self.index < len(self.members), 'additional source member refused')
        s,m = self.members[self.index]
        require((sample_id,member_id)==(s['id'],m['id']) and start==self.offset and type(stop) is int and
                (start < stop <= m['entries'] or start == stop == m['entries'] == 0) and stop-start<=self.limits['chunk_entries'],
                'complete ordered nonoverlapping source range required')
        require(type(entries) is list and entries == sorted(set(entries)) and all(type(x) is int and start<=x<stop for x in entries), 'exact admitted source entry order required')
        if s['kind'] != 'data': require(entries==list(range(start,stop)), 'MC chunk cannot omit source events')
        require(type(records) is list and type(weight_rows) is list and len(records)==len(entries)==len(weight_rows), 'kernel must return every admitted row, including empty fills')
        for entry,record,row in zip(entries,records,weight_rows):
            keys(record, ('source_entry','fills'), 'kernel event output')
            require(type(record['source_entry']) is int and record['source_entry']==entry, 'kernel source identity differs')
            keys(record['fills'], tuple(q['id'] for q in self.a['quantities']), 'complete observable fills')
            if s['kind'] != 'data':
                raw = scalar(row[self.a['weight_contract']['raw_mc_weight']])
                self.raw[s['id']][0].add(raw); self.raw[s['id']][1].add(scalar(raw*raw))
            event_weights = weights(s,self.a['weight_contract'],row)
            for q in self.a['quantities']: self.moments[s['id']][q['id']].event(event_weights,record['fills'][q['id']])
        self.chunks += 1; require(self.chunks<=self.limits['max_chunks'], 'full source chunk limit exceeded')
        # No blinded SR counts, selected indices or rows in public coverage.
        self.coverage.append({'sample':s['id'],'member':m['id'],'start':start,'stop':stop})
        self.offset = stop
        if stop == m['entries']: self.index += 1; self.offset = 0
    def finish(self):
        require(self.index == len(self.members) and self.offset == 0, 'complete original member/entry population is unfinished')
        return {'schema_version':1,'kind':'root-stream-moments','samples':[
            {'id':s['id'],'kind':s['kind'],'dsid':s['dsid'],'normalization':deepcopy(s['normalization']),
             'raw_mc_weights':None if s['kind']=='data' else {'sumw':self.raw[s['id']][0].value(),'sumw2':self.raw[s['id']][1].value(),'scope':'analyzed original entries; retained full denominator is separate'},
             'weight_contract':deepcopy(self.a['weight_contract']),
             'quantities':{q:self.moments[s['id']][q].result(scale(s)) for q in self.moments[s['id']]}}
            for s in self.ds['samples']], 'coverage':deepcopy(self.coverage),'coverage_sha256':digest(self.coverage),
            'sampling_law':'poissonized_independent_physical_events_with_event_common_weights',
            'blinding':'Restricted machine census; public DATA projection requires original allowed-model-fields policy', 'physics_validated':False}
