"""Closed IRIS/ServiceX source contracts and grouped histogram delivery.

No ServiceX, DAOD, Awkward or ROOT import in this module. Event-common weights
are broadcast to fills exactly as in the released IRIS notebooks. The existing
quantity engine owns moments; the categorical joint basis is a bookkeeping
index, not a physical observable or an independent-object sampling law.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

from ravel.physics import quantities
from ravel.workflow.state_io import _unique

SCOPE = 'dataset-query-quantities-delivery'
VERSION = '3.3.1'
MAX_DOCUMENT = 8 * 1024**2
OPERATIONS = ('query_and_analyze', 'analyze_returned_native_files', 'observe_existing_remote_request')
TERMINAL = ('Complete', 'Fatal', 'Canceled', 'BadDataset')
DATA = Path(__file__).parents[1] / 'data/iris'


def keys(value, names, label):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('closed ' + label + ' required')


def text(value, label='text', maximum=4096):
    if type(value) is not str or not value.strip() or value != value.strip() or len(value.encode()) > maximum:
        raise ValueError('bounded literal ' + label + ' required')
    return value


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('bounded integer ' + label + ' required')
    return value


def number(value):
    return quantities._number(value, 'IRIS finite scalar')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def strict(raw):
    def reject(value):
        raise ValueError('nonfinite JSON: ' + value)
    def finite(value):
        result=float(value)
        if not math.isfinite(result):raise ValueError('nonfinite JSON number')
        return result
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject, parse_float=finite)


def pin(value):
    keys(value, ('path', 'sha256', 'size'), 'source pin')
    text(value['path'], 'source path')
    if type(value['sha256']) is not str or re.fullmatch('[a-f0-9]{64}', value['sha256']) is None:
        raise ValueError('literal source digest required')
    integer(value['size'], 0, 4 * 1024**3, 'source bytes')
    return value


class Capture:
    """Fresh authenticated snapshots; no cross-call content/authority cache."""
    def __init__(self):
        self.rows = {}

    def read(self, declaration, base, limit=MAX_DOCUMENT):
        pin(declaration)
        if declaration['size'] > limit:
            raise ValueError('declared source exceeds this consumption bound')
        from ravel.workflow.research_cycle import _bounded_source_snapshot
        path = Path(declaration['path'])
        path, raw = _bounded_source_snapshot(path if path.is_absolute() else Path(base) / path, limit)
        if len(raw) != declaration['size'] or hashlib.sha256(raw).hexdigest() != declaration['sha256']:
            raise ValueError('consumed source bytes differ from admitted pin')
        row = {'path': str(path), 'sha256': declaration['sha256'], 'size': len(raw)}
        if path in self.rows and self.rows[path] != row:
            raise ValueError('inconsistent source identity in one observation')
        self.rows[path] = row
        return path, raw

    def document(self, declaration, base):
        return strict(self.read(declaration, base)[1])

    def finish(self):
        for p in list(self.rows):
            self.read(self.rows[p], p.parent, max(MAX_DOCUMENT, self.rows[p]['size']))


def public_uri(value):
    text(value, 'nonsecret source URI')
    parsed = urlsplit(value)
    if parsed.scheme not in ('root', 'https', 'http', 'file') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('explicit unsigned source URI without embedded credentials required')
    return value


def dataset(document):
    keys(document, ('schema_version', 'membership_authority', 'datasets', 'source_filter', 'ordering', 'prefix'), 'complete dataset')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('dataset schema1 required')
    pin(document['membership_authority'])
    text(document['source_filter'], 'source-defined filter')
    if document['ordering'] != 'declared_member_then_source_entry':
        raise ValueError('explicit source order required; completion order is not event order')
    if document['prefix'] is not None:
        keys(document['prefix'], ('events', 'source'), 'source-defined prefix')
        integer(document['prefix']['events'], 1, 1000000, 'source prefix'); pin(document['prefix']['source'])
    if type(document['datasets']) is not list or not 1 <= len(document['datasets']) <= 64:
        raise ValueError('complete bounded DID population required')
    ids, dids, uris = set(), set(), set()
    for d in document['datasets']:
        keys(d, ('did', 'members'), 'dataset DID')
        text(d['did'], 'literal DID')
        if d['did'] in dids or type(d['members']) is not list or not d['members']:
            raise ValueError('unique DIDs and full member populations required')
        dids.add(d['did'])
        for m in d['members']:
            keys(m, ('id', 'uri', 'events'), 'dataset member')
            text(m['id'], 'source member id'); public_uri(m['uri'])
            if m['id'] in ids or m['uri'] in uris:
                raise ValueError('source member aliases/duplicates refused')
            if m['events'] is not None:
                integer(m['events'], 0, 1000000000000, 'source exposure')
            ids.add(m['id']); uris.add(m['uri'])
    if len(ids) > 20000:
        raise ValueError('complete source member census exceeds 20k bound')
    return deepcopy(document)


class MissingColumnarInput(ValueError):
    """A supplied columnar contract omitted a required input."""


class MissingServiceEndpoint(MissingColumnarInput):
    """A dispatching operation names no ServiceX endpoint; none is shipped, installed or read from the home directory."""


def context_description():
    return 'inspect supplied dataset, query, observable and presentation requirements; no dispatch'


def presentation(document, *, components):
    """Validate independent, supplied component and output choices."""
    required = ('plot_kind', 'formats')
    if type(document) is dict and set(required) - set(document):
        raise MissingColumnarInput('missing columnar presentation inputs: ' + ', '.join(sorted(set(required) - set(document))))
    keys(document, required, 'columnar presentation')
    kind = document['plot_kind']
    if kind not in ('histogram', 'dataset_stack', 'none'):
        raise ValueError('supported supplied columnar plot_kind required')
    if kind == 'dataset_stack' and not components:
        raise ValueError('dataset_stack requires explicitly supplied dataset_components')
    formats = document['formats']
    if (type(formats) is not list or any(type(v) is not str or v not in ('png', 'pdf') for v in formats)
            or len(formats) != len(set(formats)) or (bool(formats) != (kind != 'none'))):
        raise ValueError('explicit unique PNG/PDF formats for plots, empty formats for none required')
    return deepcopy(document)


def contract(document):
    required = ('schema_version', 'task_id', 'source_question', 'observables', 'weight_names', 'weight_semantics', 'scale_factor_semantics', 'source_filter', 'sampling_law', 'event_domain', 'dataset_components', 'presentation')
    if type(document) is dict and set(required) - set(document):
        raise MissingColumnarInput('missing columnar inputs: ' + ', '.join(sorted(set(required) - set(document))))
    keys(document, required, 'columnar analysis contract')
    if type(document['schema_version']) is not int or document['schema_version'] != 1:
        raise ValueError('analysis contract schema1 required')
    text(document['task_id'], 'supplied study label')
    pin(document['source_question'])
    domain = document['event_domain']
    keys(domain, ('datasets', 'prefix'), 'declared event domain')
    quantities._unique(domain['datasets'], 'declared dataset identifiers')
    for name in domain['datasets']:text(name, 'declared dataset identifier')
    if domain['prefix'] is not None:
        keys(domain['prefix'], ('events', 'source'), 'declared event prefix')
        integer(domain['prefix']['events'], 1, 1000000, 'declared event prefix')
        pin(domain['prefix']['source'])
    if type(document['dataset_components']) is not bool:
        raise ValueError('explicit dataset_components boolean required')
    presentation(document['presentation'], components=document['dataset_components'])
    if document['sampling_law'] != 'poissonized_independent_groups_event_common_weights':
        raise ValueError('explicit existing grouped moment law required')
    quantities._unique(document['weight_names'], 'named weights')
    for k in ('weight_semantics', 'scale_factor_semantics', 'source_filter'):
        text(document[k], k)
    rows = document['observables']
    if type(rows) is not list or not 1 <= len(rows) <= 32:
        raise ValueError('whole bounded observable population required')
    ids = set(); dimensions = 0
    for obs in rows:
        keys(obs, ('id', 'quantity', 'metric_scope'), 'observable')
        text(obs['id'], 'observable id')
        if obs['id'] in ids or obs['metric_scope'] != 'raw_unweighted_fills_per_selected_event':
            raise ValueError('unique observables and explicit unweighted metric scope required')
        ids.add(obs['id'])
        q = quantities.validate(obs['quantity'])
        if q['weight_names'] != document['weight_names']:
            raise ValueError('all observables must retain the same named event weights')
        dimensions += len(q['bins'])
    if (dimensions + 2) * len(document['weight_names']) > 512:
        raise ValueError('complete joint coordinate population exceeds finite 512 bound')
    return deepcopy(document)



def original_domain(a, ds):
    """Keep the supplied dataset population and event domain unchanged."""
    if 'event_domain' not in a:
        raise MissingColumnarInput('missing columnar input: event_domain')
    domain = a['event_domain']
    required = set(domain['datasets'])
    if {d['did'] for d in ds['datasets']} != required:
        raise ValueError('complete declared dataset population required')
    prefix = ds['prefix']
    if prefix != domain['prefix']:
        raise ValueError('declared event prefix differs from dataset')
    if prefix is not None:
        if any(m['events'] is None for d in ds['datasets'] for m in d['members']):
            raise ValueError('source-event counts/association required before applying a prefix')
    return deepcopy(domain)


def native_population(census, manifest, rows):
    """Returned native row counts, not a proof of original DID/query semantics.

    A connected source/return component may be many-to-many. Its complete
    returned row census must equal its exported source-member population.
    Original member/entry association remains a source-bound scientific input.
    """
    if type(census) is not list or len(census)!=len(manifest['files']):
        raise ValueError('complete native API row census required')
    by_id={r['id']:r for r in manifest['files']};counts={}
    for row in census:
        keys(row, ('id','rows','source_members','api'), 'native API row census')
        integer(row['rows'],0,1000000000000,'actual native rows');text(row['api'],'native row API')
        if row['id'] not in by_id or row['id'] in counts or row['source_members']!=by_id[row['id']]['source_members']:
            raise ValueError('native row census member association differs')
        counts[row['id']]=row['rows']
    if sum(counts.values())!=len(rows):raise ValueError('native API rows differ from complete exported source-event records')
    unseen=set(by_id)
    while unseen:
        files={next(iter(unseen))};members=set()
        while True:
            new_members={m for f in files for m in by_id[f]['source_members']}
            new_files={f for f in by_id if set(by_id[f]['source_members']) & new_members}
            if new_members==members and new_files==files:break
            members,files=new_members,new_files
        if sum(counts[f] for f in files)!=sum(manifest['exposure'][m]['returned_events'] for m in members):
            raise ValueError('connected native file/source exposure population differs')
        unseen-=files
    return deepcopy(census)


def _component_quantities(a, ds, population, outputs, budget):
    """DID bins with one full-population denominator, using existing moments.

    Cross-DID/shared-group moments stay in the augmented raw state. Each DID
    marginal uses the original quantity Jacobian with the SAME denominator;
    it is never normalized independently. Per-DID marginal errors are not
    quadrature-summed into a total. The original full quantity owns that total.
    """
    dids=[d['did'] for d in ds['datasets']]
    member_did={m['id']:i for i,d in enumerate(ds['datasets']) for m in d['members']}
    answer={};used=0
    for o in a['observables']:
        q=o['quantity'];n=len(q['bins']);size=n*len(dids);weights=q['weight_names']
        if (size+2)*len(weights)>512:raise ValueError('complete DID moment coordinates exceed finite512 bound')
        records=[];support={}
        for r in population:
            fills=[]
            for f in r['fills'][o['id']]:
                index=next((i for i,b in enumerate(q['bins']) if all(lo<=x<hi for lo,x,hi in zip(b['low'],f,b['high']))),None)
                fills.append([-0.5] if index is None else [member_did[r['member_id']]*n+index+0.5])
            records.append({'event_id':r['event_id'],'group_id':r['group_id'],'shard_id':'complete-source-population','weights':r['weights'],'fills':fills})
            represented=support.setdefault(r['group_id'],set())
            for k in range(len(weights)):
                offset=k*(size+2);represented.add(offset+size+1)
                represented.update(offset+(int(f[0]) if f[0]>=0 else size) for f in fills)
        work=sum(len(v)*(len(v)+1)//2 for v in support.values());used+=work
        if used>budget:raise ValueError('actual grouped DID products exceed admitted bound')
        norm={'kind':'normalized','scope':'in_range'} if q['normalization'].get('scope')=='in_range' else {'kind':'absolute','scale':1,'unit':q['input_weight_unit']}
        raw_contract={'schema_version':1,'axes':[{'name':'DID_bin_index','unit':'1'}],
            'bins':[{'id':str(i),'low':[i],'high':[i+1]} for i in range(size)],
            'weight_names':weights,'input_weight_unit':q['input_weight_unit'],'representation':'integrated','normalization':norm}
        raw=quantities.calculate(raw_contract,records,finalize=False)
        marginals={}
        for di,did in enumerate(dids):
            indices=[k*(size+2)+di*n+i for k in range(len(weights)) for i in range(n+2)]
            # Flow is common/full-population custody, not an individual DID flow.
            for k in range(len(weights)):
                indices[k*(n+2)+n]=k*(size+2)+size
                indices[k*(n+2)+n+1]=k*(size+2)+size+1
            state={**raw['state'],'sumw':[raw['state']['sumw'][i] for i in indices],
                'second_moment':[[raw['state']['second_moment'][i][j] for j in indices] for i in indices]}
            projected=quantities._project(q,state)
            marginals[did]={'values':projected['values'],'covariance':projected['covariance'],'covariance_order':projected['covariance_order'],
                'denominators':projected['denominators'],'flow_policy':'Full-population flow remains in raw custody; not an individual DID flow estimate'}
        values={did:marginals[did]['values'] for did in dids}
        residual={w:[number(outputs[o['id']]['values'][w][i]-quantities._sum(values[d][w][i] for d in dids)) for i in range(n)] for w in weights}
        answer[o['id']]={'unit':outputs[o['id']]['unit'],'normalization':deepcopy(q['normalization']),
            'values':values,'marginals':marginals,'raw_joint_moments':raw,'raw_basis':[{'index':di*n+i,'did':did,'bin_id':b['id']} for di,did in enumerate(dids) for i,b in enumerate(q['bins'])],
            'component_error_policy':'Existing grouped marginal propagation with full shared denominator; cross-DID raw moments retained. Plot uses the full total covariance, never independent component quadrature.',
            'aggregation_roundoff_residual':residual}
    return {'did_order':dids,'member_to_did':{m['id']:d['did'] for d in ds['datasets'] for m in d['members']},'observables':answer},used


def config(c):
    keys(c, ('schema_version', 'operation', 'dataset', 'analysis', 'bundle', 'runtime', 'service', 'returned', 'remote_request', 'max_seconds', 'max_ram_mib', 'max_output_bytes', 'max_event_rows', 'max_group_products', 'trusted_native_source'), 'IRIS config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or c['operation'] not in OPERATIONS or c['trusted_native_source'] is not True:
        raise ValueError('explicit trusted IRIS operation required')
    for name in ('dataset', 'analysis'):
        pin(c[name])
    keys(c['bundle'], ('entry', 'files'), 'source bundle')
    text(c['bundle']['entry'], 'native plugin entry')
    if type(c['bundle']['files']) is not dict or not 1 <= len(c['bundle']['files']) <= 128 or c['bundle']['entry'] not in c['bundle']['files']:
        raise ValueError('complete finite source bundle required')
    for rel, p in c['bundle']['files'].items():
        if Path(rel).is_absolute() or '..' in Path(rel).parts or rel.endswith('.pyc'):
            raise ValueError('literal relative source bundle member required')
        pin(p)
    rt = c['runtime']
    keys(rt, ('python', 'site_roots', 'trees', 'versions', 'backend'), 'native runtime')
    pin(rt['python'])
    if rt['backend'] not in ('awkward-hist', 'root-rdataframe') or type(rt['site_roots']) is not list or not rt['site_roots'] or type(rt['trees']) is not list or not rt['trees']:
        raise ValueError('explicit native Awkward or RDataFrame runtime required')
    packages = ('servicex', 'awkward', 'hist', 'uproot', 'numpy', 'func_adl_servicex_xaodr25') if rt['backend'] == 'awkward-hist' else ('servicex', 'ROOT', 'numpy', 'func_adl_servicex_xaodr25')
    keys(rt['versions'], packages, 'exact runtime package versions')
    for name, version in rt['versions'].items():
        text(version, name+' version')
    if rt['versions']['servicex'] != VERSION:
        raise ValueError('prospective pinned ServiceX3.3.1 required; original IRIS environment equivalence unknown')
    for tree in rt['trees']:
        keys(tree, ('root', 'manifest'), 'complete runtime tree'); text(tree['root']); pin(tree['manifest'])
    for site in rt['site_roots']:
        text(site, 'site root')
    integer(c['max_seconds'], 1, 86400, 'native seconds'); integer(c['max_ram_mib'], 128, 8192, 'native RAM MiB')
    integer(c['max_output_bytes'], 1024, 4 * 1024**3, 'complete output bytes')
    integer(c['max_event_rows'], 1, 1000000, 'complete event rows'); integer(c['max_group_products'], 1, 2000000, 'group products')
    if c['operation'] == 'analyze_returned_native_files':
        pin(c['returned'])
        if c['service'] is not None or c['remote_request'] is not None:
            raise ValueError('returned-file analysis has no service dispatch or credential')
    else:
        if c['service'] is None or type(c['service']) is dict and not c['service'].get('endpoint'):
            raise MissingServiceEndpoint(
                c['operation'] + ' dispatches to a ServiceX endpoint and the configuration names none: supply your own '
                'HTTPS endpoint as service.endpoint and, when it needs an access token, the environment variable that '
                'holds it as service.credential_reference. RAVEL ships no endpoint and does not read servicex.yaml; '
                'use analyze_returned_native_files for native files you already hold.')
        keys(c['service'], ('endpoint', 'credential_reference', 'codegen', 'result_format', 'cancel_if_failed'), 'native service')
        public_uri(c['service']['endpoint'])
        if urlsplit(c['service']['endpoint']).scheme != 'https':
            raise ValueError('explicit HTTPS service required')
        ref = c['service']['credential_reference']
        if ref is not None:
            keys(ref, ('kind', 'name'), 'native secret reference')
            if ref['kind'] != 'environment' or re.fullmatch('[A-Z][A-Z0-9_]{1,127}', ref['name']) is None:
                raise ValueError('approved native-only credential environment name required')
        text(c['service']['codegen'])
        if c['service']['result_format'] not in ('root', 'parquet') or type(c['service']['cancel_if_failed']) is not bool or c['returned'] is not None:
            raise ValueError('explicit service native format/cancellation policy required')
        if c['operation'] == 'query_and_analyze' and c['remote_request'] is not None:
            raise ValueError('fresh query must not inherit an existing request')
        if c['operation'] == 'observe_existing_remote_request':
            keys(c['remote_request'], ('id', 'intent', 'cancel'), 'existing remote request')
            text(c['remote_request']['id']); pin(c['remote_request']['intent'])
            if type(c['remote_request']['cancel']) is not bool:
                raise ValueError('explicit observation cancellation intent required')
    return deepcopy(c)


def returned(document, ds):
    keys(document, ('schema_version', 'origin', 'source_dataset_sha256', 'files', 'exposure', 'source_filter'), 'native returned-file manifest')
    if type(document['schema_version']) is not int or document['schema_version'] != 1 or document['source_dataset_sha256'] != digest(ds) or document['source_filter'] != ds['source_filter']:
        raise ValueError('returned native population must bind exact dataset and filter')
    if document['origin'] not in ('supplied_native_return', 'fresh_service_return'):
        raise ValueError('explicit supplied or fresh native return required; ambient cache reuse is not admitted')
    expected = {m['id']:m for d in ds['datasets'] for m in d['members']}
    if type(document['exposure']) is not dict or set(document['exposure']) != set(expected):
        raise ValueError('complete original member exposure required')
    for name, row in document['exposure'].items():
        keys(row, ('source_events', 'returned_events'), 'source/returned exposure')
        if row['source_events'] is not None:
            integer(row['source_events'], 0, 1000000000000, 'source events')
        integer(row['returned_events'], 0, 1000000000000, 'returned events')
        if expected[name]['events'] is not None and row['source_events'] != expected[name]['events']:
            raise ValueError('original source exposure changed')
    if type(document['files']) is not list or not 1 <= len(document['files']) <= 20000:
        raise ValueError('full native file population required')
    ids, paths, covered = set(), set(), set()
    for row in document['files']:
        keys(row, ('id', 'pin', 'format', 'source_members'), 'native returned member')
        text(row['id']); pin(row['pin'])
        if row['format'] not in ('root', 'parquet') or row['id'] in ids or row['pin']['path'] in paths or row['pin']['size'] == 0:
            raise ValueError('unique nonempty ROOT/Parquet returns required; JSON is not DAOD')
        if type(row['source_members']) is not list or not row['source_members'] or len(set(row['source_members'])) != len(row['source_members']) or not set(row['source_members']) <= set(expected):
            raise ValueError('explicit complete many-to-many source/return correspondence required')
        ids.add(row['id']); paths.add(row['pin']['path']); covered.update(row['source_members'])
    if covered != set(expected):
        raise ValueError('returned files omit original source members')
    return deepcopy(document)


def analyze(a, ds, manifest, rows, *, max_rows, max_products):
    """Adjudicate complete native export and reuse existing quantity moments."""
    a, ds, manifest = contract(a), dataset(ds), returned(manifest, ds)
    original_domain(a,ds)
    if a['source_filter'] != ds['source_filter']:
        raise ValueError('query and analysis source filters differ')
    if type(rows) is not list or not 1 <= len(rows) <= max_rows:
        raise ValueError('complete event population exceeds declared bound or is absent')
    members = [m['id'] for d in ds['datasets'] for m in d['members']]
    index = {n:i for i,n in enumerate(members)}
    ids, source_entries, selected = set(), set(), []
    observed = dict.fromkeys(members, 0);largest_entry=dict.fromkeys(members,-1)
    obs_ids = [o['id'] for o in a['observables']]
    for r in rows:
        keys(r, ('event_id', 'group_id', 'member_id', 'source_entry', 'selected', 'weights', 'fills'), 'native event export')
        for k in ('event_id', 'group_id', 'member_id'):text(r[k], k)
        if r['event_id'] in ids or r['member_id'] not in index or type(r['selected']) is not bool:
            raise ValueError('unique events, known source members and explicit selection required')
        integer(r['source_entry'], 0, 1000000000000, 'source entry')
        key = (r['member_id'], r['source_entry'])
        if key in source_entries:
            raise ValueError('source entry appears more than once')
        ids.add(r['event_id']); source_entries.add(key); observed[r['member_id']] += 1
        largest_entry[r['member_id']]=max(largest_entry[r['member_id']],r['source_entry'])
        keys(r['weights'], a['weight_names'], 'all named signed weights')
        for w in r['weights'].values():number(w)
        keys(r['fills'], obs_ids, 'whole observable fills')
        for o in a['observables']:
            fills = r['fills'][o['id']]
            if type(fills) is not list or not r['selected'] and fills:
                raise ValueError('unselected events cannot carry selected fills')
            for f in fills:
                if type(f) is not list or len(f) != len(o['quantity']['axes']):raise ValueError('native fill dimensionality differs')
                for v in f:number(v)
    if observed != {n:r['returned_events'] for n,r in manifest['exposure'].items()}:
        raise ValueError('exported event census differs from complete native return exposure')
    source_prefix = ds['prefix'] is not None
    if source_prefix:
        # Exact unique entries plus this bounded domain prove complete supplied
        # source-event records at the checkpoints, not the native query premise.
        for m in [m for d in ds['datasets'] for m in d['members']]:
            exposure=manifest['exposure'][m['id']]
            total=m['events']
            if total is None or exposure['source_events']!=total or exposure['returned_events']!=total or observed[m['id']]!=total:
                raise ValueError('prefix requires complete known source-event exposure; filtered/unknown returns refused')
            if largest_entry[m['id']]>=total:
                raise ValueError('source-entry domain is not the complete declared 0..N-1 population')
    # Source order, never asynchronous download/completion order. The original
    # source prefix is explicit; no other row/event thinning is performed.
    ordered = sorted(rows, key=lambda r:(index[r['member_id']], r['source_entry']))
    prefix = ds['prefix']
    retained = ordered if prefix is None else ordered[:prefix['events']]
    selected = [r for r in retained if r['selected']]
    population = retained if source_prefix else selected
    if not population:raise ValueError('native event denominator is empty')
    records = lambda fills:[{'event_id':r['event_id'], 'group_id':r['group_id'], 'shard_id':'complete-source-population', 'weights':r['weights'], 'fills':fills(r)} for r in population]
    basis = [(o['id'], b['id']) for o in a['observables'] for b in o['quantity']['bins']]
    coordinates = {pair:i for i,pair in enumerate(basis)}
    def joint_fills(r):
        output = []
        for o in a['observables']:
            for f in r['fills'][o['id']]:
                found = next((b for b in o['quantity']['bins'] if all(lo <= x < hi for lo,x,hi in zip(b['low'],f,b['high']))), None)
                output.append([coordinates[o['id'],found['id']]+0.5] if found is not None else [-0.5])
        return output
    joint_records = records(joint_fills)
    # Count represented grouped coordinates only after full row/weight census.
    grouped = {}
    for r in joint_records:
        g = grouped.setdefault(r['group_id'], {})
        for k,w in enumerate(a['weight_names']):
            offset=k*(len(basis)+2)
            g.setdefault(offset+len(basis)+1, []).append(r['weights'][w])
            for f in r['fills']:
                i=int(f[0]) if f[0]>=0 else len(basis)
                g.setdefault(offset+i, []).append(r['weights'][w])
    # quantities.calculate multiplies every represented group coordinate,
    # including exact zero/cancellation entries. Count that actual loop, not
    # only nonzero mathematical support; zero weights cannot evade the budget.
    joint_products = sum(len(g)*(len(g)+1)//2 for g in grouped.values())
    observable_products=0
    for o in a['observables']:
        support={};nb=len(o['quantity']['bins'])
        for r in population:
            s=support.setdefault(r['group_id'],set())
            for k,w in enumerate(a['weight_names']):
                offset=k*(nb+2);s.add(offset+nb+1)
                for f in r['fills'][o['id']]:
                    i=next((i for i,b in enumerate(o['quantity']['bins']) if all(lo<=x<hi for lo,x,hi in zip(b['low'],f,b['high']))),nb)
                    s.add(offset+i)
        observable_products+=sum(len(s)*(len(s)+1)//2 for s in support.values())
    products=joint_products+observable_products
    if products > max_products:raise ValueError('actual grouped joint products exceed admitted bound')
    joint_contract={'schema_version':1,'axes':[{'name':'source_observable_bin_index','unit':'1'}],
        'bins':[{'id':str(i),'low':[i],'high':[i+1]} for i in range(len(basis))],
        'weight_names':a['weight_names'],'input_weight_unit':a['observables'][0]['quantity']['input_weight_unit'],
        'representation':'integrated','normalization':{'kind':'absolute','scale':1,'unit':a['observables'][0]['quantity']['input_weight_unit']}}
    if any(o['quantity']['input_weight_unit'] != joint_contract['input_weight_unit'] for o in a['observables']):
        raise ValueError('common signed weights must carry the same input units')
    joint=quantities.calculate(joint_contract,joint_records)
    outputs={};metrics={};fill_diagonals={}
    for o in a['observables']:
        outputs[o['id']]=quantities.calculate(o['quantity'],records(lambda r:r['fills'][o['id']]))
        fills=[f for r in selected for f in r['fills'][o['id']]]
        metrics[o['id']]={'scope':'raw_unweighted_fills_per_original_source_prefix_event' if source_prefix else o['metric_scope'],'declared_legacy_scope':o['metric_scope'],'selected_events':len(selected),'entries':len(fills),
            'metric_denominator_events':len(population),'metric_event_scope':'original_source_prefix_including_zero_object_events' if source_prefix else 'selected_events',
            'avg_entries_per_event':number(len(fills)/len(population)),
            'raw_unweighted_axis_means':[number(quantities._sum(f[i] for f in fills)/len(fills)) if fills else None for i in range(len(o['quantity']['axes']))],
            'empty_mean':'unknown_not_zero' if not fills else None}
        diagonal={}
        for weight in a['weight_names']:
            cells=[[] for _ in range(len(o['quantity']['bins'])+1)]
            for r in population:
                square=number(r['weights'][weight]*r['weights'][weight])
                for f in r['fills'][o['id']]:
                    i=next((i for i,b in enumerate(o['quantity']['bins']) if all(lo<=x<hi for lo,x,hi in zip(b['low'],f,b['high']))),len(cells)-1)
                    cells[i].append(square)
            diagonal[weight]={'bin_sumw2':[quantities._sum(v) for v in cells[:-1]],'flow_sumw2':quantities._sum(cells[-1])}
        fill_diagonals[o['id']]={'values':diagonal,'scope':'Raw per-fill Hist.Weight diagonal; not shared-event/group covariance or a physics uncertainty qualification'}
    components=None;component_products=0
    if a['dataset_components']:
        components,component_products=_component_quantities(a,ds,population,outputs,max_products-products)
    products+=component_products
    return {'kind':'iris_grouped_columnar_quantities','plot_kind':a['presentation']['plot_kind'],'plot_formats':a['presentation']['formats'],'observables':outputs,'raw_unweighted_metrics':metrics,
        'upstream_per_fill_diagonal':fill_diagonals,
        'joint_raw_moments':joint,'joint_basis':[{'index':i,'observable':o,'bin_id':b} for i,(o,b) in enumerate(basis)],
        'cross_observable_normalized_covariance':'not_projected; full raw shared-group/denominator moments retained',
        'full_returned_events':len(rows),'source_prefix_events':len(retained),'selected_events':len(selected),
        'full_member_exposure':manifest['exposure'],'dataset_components':components,'actual_group_products':products,
        'source_event_association':'Authenticated supplied member/count/entry and query-source premises; returned row counts do not independently prove original DID identity or query semantics',
        'group_product_accounting':{'joint':joint_products,'separate_observables':observable_products,'DID_components':component_products,'includes_represented_zero_entries':True},
        'source_order_commitment':digest(members),'physics_validated':False,
        'uncertainty_scope':joint['uncertainty_scope'],'scale_factor_semantics':a['scale_factor_semantics']}


def remote_status(value):
    """Whitelist public observations; never serialize native secret fields."""
    fields=('request_id','status','files','files_completed','files_failed','files_remaining')
    answer={k:getattr(value,k,None) for k in fields}
    if hasattr(answer['status'],'value'):answer['status']=answer['status'].value
    text(answer['request_id'],'remote request id')
    if answer['status'] not in (*TERMINAL,'Submitted','Lookup','Pending Lookup','PendingLookup','Running'):
        raise ValueError('unrecognized remote state remains unresolved')
    for k in fields[2:]:
        if answer[k] is not None:integer(answer[k],0,1000000000000,k)
    answer['terminal_observed']=answer['status'] in TERMINAL
    return answer
