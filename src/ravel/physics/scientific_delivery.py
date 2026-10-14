"""Connect primary resource capture, a complete supplied portfolio and report delivery.

Uses the existing TLS acquisition, strict source tables, original-task binding,
scientific_report and ordinary study/publication adapters. No new runner, plotter,
likelihood, catalogue-completeness assertion or automatic scientific approval.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

from ravel.physics import source_tables
from ravel.physics.published_summary import _json, digest
from ravel.workflow.state_io import atomic_json

DOCUMENT = 4 * 1024 * 1024
TOTAL = 200 * 1024 * 1024
MAX_CELLS = 32768
BASIS = ('model', 'resonance', 'spin', 'decay', 'production', 'width',
         'energy_tev', 'branching_convention', 'interference', 'quantity', 'unit', 'domain')
FORMATS = ('text', 'pdf', 'json', 'hepdata_yaml', 'hepdata_record_data')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected), 'closed delivery declaration required')


def text(value):
    require(type(value) is str and value.strip() and len(value.encode()) <= 8000,
            'explicit bounded source meaning required')
    return value


def identity(value):
    from ravel.workflow.candidate_experiments import identity as check
    return check(value)


def pin(path, raw):
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


class Snapshots:
    """Reuse the strict primary-table reader; classify/copy only captured bytes."""
    def __init__(self, base):
        self.base = Path(base).absolute()
        self.raw = {}; self.pins = {}; self.total = 0
        require(self.base.is_dir() and not any(p.is_symlink() for p in (self.base, *self.base.parents)),
                'canonical source base required')

    def file(self, expected, limit=DOCUMENT):
        keys(expected, ('path', 'sha256', 'size'))
        text(expected['path'])
        from ravel.workflow.candidate_experiments import sha
        sha(expected['sha256'])
        require(type(expected['size']) is int and 0 < expected['size'] <= limit,
                'bounded nonempty source pin required')
        p = Path(expected['path']); p = p if p.is_absolute() else self.base / p
        require('..' not in p.parts, 'canonical source path required')
        p = p.absolute()
        if str(p) in self.pins:
            require(self.pins[str(p)] == {**expected, 'path': str(p)}, 'conflicting source pin')
            return self.raw[str(p)], p
        require(len(self.pins) < 512, 'complete input census exceeds512; no truncation')
        require(self.total + expected['size'] <= TOTAL, 'complete source graph exceeds200MiB')
        raw = source_tables.bounded_read(p, limit=limit)
        require(pin(p, raw) == {**expected, 'path': str(p)}, 'source bytes differ from pin')
        self.raw[str(p)] = raw; self.pins[str(p)] = pin(p, raw); self.total += len(raw)
        return raw, p

    def document(self, expected):
        return _json(self.file(expected)[0])

    def capture(self, path):
        p = Path(path).absolute()
        if str(p) in self.pins:
            return self.pins[str(p)]
        raw = source_tables.bounded_read(p, limit=DOCUMENT)
        expected = pin(p, raw)
        require(self.total + len(raw) <= TOTAL and len(self.pins) < 512,
                'complete planned source graph exceeds budget')
        self.raw[str(p)] = raw; self.pins[str(p)] = expected; self.total += len(raw)
        return expected

    def finish(self):
        for path, expected in self.pins.items():
            require(pin(Path(path), source_tables.bounded_read(Path(path), limit=expected['size'])) == expected,
                    'source changed before delivery')


def _url(value):
    text(value); u = urlsplit(value)
    require(u.scheme == 'https' and u.netloc and not u.username and not u.password and not u.fragment,
            'explicit HTTPS primary URL required')
    return value


def acquire(request, destination, *, opener=None):
    """Capture one record's complete declared table population and primary assets.

    Explicit context-only tables remain in the census. Acquisition establishes
    downloaded byte identity, not original precision, applicability or truth.
    The supplied opener is for portable transport controls, never a TLS fallback.
    """
    from ravel.workflow.hepdata_fetch import _open, record_data_index, classify
    keys(request, ('schema_version', 'record_url', 'expected_recid', 'expected_version',
                   'table_dispositions', 'assets', 'max_total_bytes'))
    require(type(request['schema_version']) is int and request['schema_version'] == 1,
            'primary acquisition/v1 required')
    for field in ('expected_recid', 'expected_version'):
        require(type(request[field]) is int and request[field] > 0, 'literal record/version required')
    require(type(request['max_total_bytes']) is int and 1 <= request['max_total_bytes'] <= TOTAL,
            'explicit acquisition byte budget required')
    out = Path(destination).absolute()
    require(not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)),
            'fresh primary acquisition directory required')
    out.mkdir(parents=True)
    captured = []; total = 0; manifest = None

    def download(url, name, limit):
        nonlocal total
        url = _url(url)
        remaining = request['max_total_bytes'] - total
        require(remaining > 0, 'source acquisition total budget exhausted')
        with (opener or _open)(url, timeout=30) as response:
            actual_url = _url(response.geturl()) if hasattr(response, 'geturl') else url
            # read is bounded before any allocation of the full response body.
            allowance=min(limit,remaining);chunks=[];count=0
            while True:
                chunk=response.read(min(65536,allowance+1-count))
                require(type(chunk) is bytes,'literal response bytes required')
                if not chunk:break
                chunks.append(chunk);count+=len(chunk)
                require(count<=allowance,'source response exceeds finite byte budget')
            raw=b''.join(chunks)
        require(type(raw) is bytes and 0 < len(raw) <= min(limit, remaining),
                'source response exceeds finite byte budget or is empty')
        path = out / name; path.write_bytes(raw); total += len(raw)
        fact = {'requested_url': url, 'resolved_url': actual_url, 'pin': pin(path, raw)}
        captured.append(fact)
        return raw, fact

    try:
        raw, record_fact = download(request['record_url'], 'record.json', DOCUMENT)
        record = _json(raw)
        require(type(record) is dict, 'literal HEPData record required')
        # No inferred version=1, truthy bool IDs, duplicate table or mirror ambiguity.
        recid = record.get('recid', (record.get('record') or {}).get('recid'))
        version = record.get('version', (record.get('record') or {}).get('version'))
        require(type(recid) is type(version) is int and (recid, version) ==
                (request['expected_recid'], request['expected_version']), 'exact record/version mismatch')
        for field, value in (('recid', recid), ('version', version)):
            mirror = (record.get('record') or {}).get(field, value)
            require(type(mirror) is int and mirror == value, 'record mirror identity differs')
        _, _, index = record_data_index(record)
        require(0 < len(index) <= 128 and len({i for i, _ in index}) == len(index),
                'complete unique bounded record table census required')
        for row in record['data_tables']:
            require(type(row['id']) is int and row['id'] > 0, 'literal table ID required')
        dispositions = request['table_dispositions']
        require(type(dispositions) is list and len(dispositions) == len(index),
                'every record table needs an explicit disposition')
        declared = {}
        for row in dispositions:
            keys(row, ('id', 'state', 'reason')); text(row['reason'])
            require(type(row['id']) is int and row['id'] not in declared and row['state'] in ('capture', 'context'),
                    'unique table capture/context disposition required')
            declared[row['id']] = row
        require(set(declared) == {i for i, _ in index}, 'record table cannot disappear from capture census')
        tables = []
        for tid, name in index:
            row = {**declared[tid], 'name': name, 'source': None, 'format': 'hepdata_record_data'}
            if row['state'] == 'capture':
                body, fact = download(f'https://www.hepdata.net/record/data/{recid}/{tid}/{version}',
                                      f'table-{tid}.json', DOCUMENT)
                doc = _json(body)
                require(type(doc) is dict and doc.get('name') == name and type(doc.get('values')) is list
                        and doc['values'], 'table response name/full values mismatch')
                row.update(source=fact, classification=classify(doc.get('description') or '', name))
            tables.append(row)
        assets = request['assets']; require(type(assets) is list and len(assets) <= 64, 'bounded primary asset census')
        ids = set()
        for asset in assets:
            keys(asset, ('id', 'url', 'format', 'expected_sha256'))
            identity(asset['id']); require(asset['id'] not in ids and asset['format'] in FORMATS,
                                         'unique typed primary asset required'); ids.add(asset['id'])
            body, fact = download(asset['url'], 'asset-' + asset['id'], 16 * 1024 * 1024)
            require(asset['expected_sha256'] is None or hashlib.sha256(body).hexdigest() == asset['expected_sha256'],
                    'expected primary asset digest mismatch')
            fact.update(id=asset['id'], format=asset['format'])
        manifest = {'schema_version': 1, 'kind': 'primary-resource-capture/v1', 'record': record_fact,
                    'recid': recid, 'version': version, 'tables': tables, 'assets': captured[1+sum(r['state']=='capture' for r in tables):],
                    'total_bytes': total, 'full_record_table_census_retained': True,
                    'all_tables_acquired': all(r['state']=='capture' for r in tables),
                    'source_truth_authenticated': False, 'scientific_acceptance': False}
        for fact in captured:
            p = Path(fact['pin']['path'])
            require(pin(p, source_tables.bounded_read(p, limit=fact['pin']['size'])) == fact['pin'],
                    'captured source changed before manifest')
        atomic_json(out / 'primary-resources.json', manifest)
        return manifest
    except Exception as error:
        atomic_json(out / 'acquisition-failure.json', {'status': 'failed', 'error': str(error),
                    'captured': captured, 'total_bytes': total, 'success_manifest_written': False})
        raise


def _table(resource, snapshot):
    raw, _ = snapshot.file(resource['pin'])
    if resource['format'] == 'hepdata_yaml':
        return source_tables.read_table_snapshot(raw, resource['pin'])
    require(resource['format'] == 'hepdata_record_data', 'declared HEPData table format required')
    doc = _json(raw)
    require(type(doc) is dict and type(doc.get('x_count')) is int and 1 <= doc['x_count'] <= 4,
            'literal bounded record/data axis count required')
    headers = doc.get('headers'); rows = doc.get('values')
    require(type(headers) is list and doc['x_count'] < len(headers) <= doc['x_count'] + 32 and
            all(type(h) is dict and set(h) == {'name', 'colspan'} and h['colspan'] == 1
                and type(h['colspan']) is int and type(h['name']) is str for h in headers),
            'unambiguous complete flat record/data headers required')
    require(type(rows) is list and 0 < len(rows) <= MAX_CELLS, 'bounded complete record/data rows required')
    n = doc['x_count']; groups = list(range(len(headers) - n))
    xs = [[] for _ in range(n)]; ys = [[] for _ in groups]
    for row in rows:
        keys(row, ('x', 'y'))
        require(type(row['x']) is list and len(row['x']) == n and type(row['y']) is list and
                len(row['y']) == len(groups), 'complete record/data rectangular population required')
        for i, value in enumerate(row['x']):
            require(type(value) is dict and set(value) in ({'value'}, {'low', 'high'}), 'literal source coordinates required')
            xs[i].append(deepcopy(value))
        ordered = {}
        for value in row['y']:
            require(type(value) is dict and {'value', 'group'} <= set(value) <= {'value', 'group', 'errors'} and
                    type(value['group']) is int and value['group'] in groups and value['group'] not in ordered,
                    'every exact record/data dependent group required')
            ordered[value['group']] = {k:deepcopy(v) for k,v in value.items() if k != 'group'}
        for group in groups: ys[group].append(ordered[group])
    # No undocumented qualifier remapping: retain the whole original block.
    axes = [{'header': deepcopy(headers[i]), 'values': values} for i, values in enumerate(xs)]
    cols = [{'header': deepcopy(headers[n+i]), 'qualifiers': deepcopy(doc.get('qualifiers', {})), 'values': values}
            for i, values in enumerate(ys)]
    return {'source': resource['pin'], 'rows': len(rows), 'payload': {'independent_variables': axes,
            'dependent_variables': cols}, 'original_record_data': doc, 'error_law_inferred': False}


def _header_unit(header):
    import re
    if 'units' in header:
        return header['units'] if type(header['units']) is str and header['units'].strip() else None
    # Record/data encodes the unit in its literal flat header; do not guess from quantity.
    name=header.get('name')
    match=re.search(r' \[([^\[\]]+)\]$',name) if type(name) is str else None
    return match.group(1) if match else None


def _basis(value):
    keys(value, BASIS)
    for k, v in value.items():
        if v is None: continue
        if k == 'spin': require(type(v) is int and v >= 0, 'literal spin or unknown required')
        elif k == 'energy_tev': require(type(v) in (int,float) and math.isfinite(v) and v > 0,
                                      'finite positive TeV energy or unknown required')
        else: text(v)
    return deepcopy(value)


def _source_number(value):
    """Explicit decimal→binary64 display projection, never an accuracy proof."""
    from decimal import Decimal, InvalidOperation
    if value is None or value == '-': return None
    if type(value) is dict:
        value=str(source_tables.number(value))
    require(type(value) in (str,int,float), 'literal source numeric display token required')
    try:
        d=Decimal(str(value))
        result=float(d)
    except (ValueError,InvalidOperation,OverflowError):
        raise ValueError('finite representable source display number required') from None
    require(d.is_finite() and math.isfinite(result) and (not d or result != 0),
            'source display overflow/underflow refused')
    return result


def _publication_quantities(bindings, loaded, tables, studies):
    """Exact full source series↔existing publication manifest, without resampling."""
    index={(t['study_id'],t['resource_id']):t for t in tables}
    selected={}; expected={}
    for pid,panel in loaded['panels'].items():
        for curve in panel['manifest']['curves']:
            if curve['draw']=='none':continue
            for name,values in curve['resolved'].items():
                if name=='mass_gev' or name in ('obs','exp','theory') and any(v is not None for v in values):
                    expected[pid,curve['survey_id'],name]=values
    for b in bindings:
        keys(b, ('study_id','panel_id','curve_id','series','source_id','column'))
        key=(b['panel_id'],b['curve_id'],b['series'])
        require(key in expected and key not in selected and b['study_id'] in studies,
                'unique complete source-to-publication series join required')
        require(any(c['id']==b['study_id'] and c['panel_id']==b['panel_id'] and c['curve_id']==b['curve_id']
                for c in loaded['figure_contract']['candidates']), 'publication numeric origin must match candidate study')
        table=index.get((b['study_id'],b['source_id']))
        require(table is not None, 'publication needs an actual delivered primary table')
        payload=table['complete_table']['payload']
        if b['series']=='mass_gev':
            require(b['column'] is None and len(payload['independent_variables'])==1 and
                    all(set(v)=={'value'} for v in payload['independent_variables'][0]['values']),
                    'mass display requires exact source point coordinates; histogram relabeling refused')
            require(_header_unit(payload['independent_variables'][0]['header'])=='GeV',
                    'mass display needs literal GeV source coordinate unit; no implicit conversion')
            values=[v['value'] for v in payload['independent_variables'][0]['values']]
        else:
            require(type(b['column']) is int and any(d['index']==b['column'] and d['state']=='deliver'
                    for d in table['column_dispositions']), 'publication source column must be delivered completely')
            values=[v['value'] for v in payload['dependent_variables'][b['column']]['values']]
        projection=[_source_number(v) for v in values]
        require(projection==expected[key], 'publication series differs from full source coordinate/value projection')
        selected[key]=projection
    require(selected.keys()==expected.keys(), 'no nonnull publication series or coordinate may lack primary quantity mapping')


def validate(task):
    keys(task, ('schema_version', 'input', 'input_sha256'))
    require(type(task['schema_version']) is int and task['schema_version'] == 1, 'delivery task/v1 required')
    text(task['input'])
    from ravel.workflow.candidate_experiments import sha
    sha(task['input_sha256'])
    return dict(task)


def _load(task, base):
    from ravel.workflow import task_completion, science
    validate(task); session = Snapshots(base)
    path = Path(task['input']); path = path if path.is_absolute() else Path(base) / path
    raw = source_tables.bounded_read(path, limit=DOCUMENT)
    request_pin = pin(path.absolute(), raw)
    require(request_pin['sha256'] == task['input_sha256'], 'delivery request hash mismatch')
    session.raw[str(path.absolute())] = raw; session.pins[str(path.absolute())] = request_pin; session.total = len(raw)
    request = _json(raw)
    keys(request, ('schema_version', 'kind', 'parent', 'questions', 'discovery', 'resources',
                   'acquisition', 'knowledge', 'studies', 'routes', 'publication_required'))
    require(type(request['schema_version']) is int and request['schema_version'] == 1 and
            request['kind'] == 'scientific-delivery/v1' and type(request['publication_required']) is bool,
            'closed original-question delivery/v1 required')
    projection = task_completion.binding_projection(request['parent'], base_dir=base)
    for fact in projection['input_pins']: session.file(fact)
    resources = request['resources']; require(type(resources) is dict and 0 < len(resources) <= 128,
                                              'bounded complete primary resource graph required')
    for rid, resource in resources.items():
        identity(rid); keys(resource, ('pin', 'format', 'citation')); text(resource['citation'])
        require(resource['format'] in FORMATS, 'declared primary source format required')
        session.file(resource['pin'], limit=16*1024*1024 if resource['format'] == 'pdf' else DOCUMENT)
    if request['acquisition'] is not None:
        acquired = session.document(request['acquisition'])
        keys(acquired, ('schema_version','kind','record','recid','version','tables','assets','total_bytes',
                        'full_record_table_census_retained','all_tables_acquired','source_truth_authenticated','scientific_acceptance'))
        require(acquired['schema_version']==1 and type(acquired['schema_version']) is int and
                acquired['kind']=='primary-resource-capture/v1' and acquired['source_truth_authenticated'] is False and
                acquired['scientific_acceptance'] is False, 'literal unqualified primary capture required')
        record=session.document(acquired['record']['pin'])
        from ravel.workflow.hepdata_fetch import record_data_index
        require(type(acquired['recid']) is type(acquired['version']) is int and acquired['recid']>0 and acquired['version']>0,
                'literal retained record/version required')
        require(type(record.get('recid',(record.get('record') or {}).get('recid'))) is int and
                type(record.get('version',(record.get('record') or {}).get('version'))) is int,
                'record/version cannot default or coerce')
        recid,version,index=record_data_index(record)
        for field,value in (('recid',recid),('version',version)):
            mirror=(record.get('record') or {}).get(field,value)
            require(type(mirror) is int and mirror==value,'retained record mirror identity differs')
        require(0<len(index)<=128 and len({i for i,_ in index})==len(index) and
                all(type(r['id']) is int and r['id']>0 for r in record['data_tables']),
                'complete literal unique record table IDs required')
        require((acquired['recid'],acquired['version'])==(recid,version) and
                [(r['id'],r['name']) for r in acquired['tables']]==index and
                acquired['full_record_table_census_retained'] is True and
                acquired['all_tables_acquired']==all(r['state']=='capture' for r in acquired['tables']),
                'acquisition manifest differs from complete retained record census')
        constituents=[acquired['record']]
        for row in acquired['tables']:
            keys(row,('id','name','state','reason','source','format',*(['classification'] if row['state']=='capture' else [])))
            require(row['format']=='hepdata_record_data','literal table capture format required');text(row['reason'])
            require(row['state'] in ('capture','context') and (row['source'] is not None)==(row['state']=='capture'),
                    'exact capture/context table source association required')
            if row['source'] is not None:
                keys(row['source'],('requested_url','resolved_url','pin'))
                require(row['source']['requested_url']==f'https://www.hepdata.net/record/data/{recid}/{row["id"]}/{version}',
                        'captured table origin URL differs from record/table/version')
                _url(row['source']['resolved_url'])
                doc=session.document(row['source']['pin'])
                require(doc.get('name')==row['name'] and type(doc.get('values')) is list and doc['values'],
                        'captured table must match original record identity/full values')
                constituents.append(row['source'])
        constituents += acquired['assets']
        for fact in constituents: session.file(fact['pin'], limit=16*1024*1024)
        require(type(acquired['total_bytes']) is int and acquired['total_bytes']==sum(f['pin']['size'] for f in constituents),
                'complete captured byte census differs')
        declared = {(r['pin']['sha256'], r['pin']['size']) for r in resources.values()}
        require(all((r['source']['pin']['sha256'], r['source']['pin']['size']) in declared
                    for r in acquired['tables'] if r['source'] is not None), 'captured tables must remain delivery resources')
    knowledge=None
    if request['knowledge'] is not None:
        from ravel.workflow import physics_knowledge
        knowledge_request=session.document(request['knowledge'])
        _,knowledge_path=session.file(request['knowledge'])
        for fact in physics_knowledge.input_pins(knowledge_request,knowledge_path.parent): session.file(fact)
        knowledge=physics_knowledge.retrieve(knowledge_request,knowledge_path.parent)
    qs = request['questions']; require(type(qs) is list and 0 < len(qs) <= 32, 'complete requested quantity census required')
    qindex = {}; obligations = {r['obligation_id'] for r in projection['assignment']['coverage']}
    for q in qs:
        keys(q, ('id', 'obligation_ids', 'quantity')); identity(q['id']); text(q['quantity'])
        require(q['id'] not in qindex and type(q['obligation_ids']) is list and q['obligation_ids'] and
                len(set(q['obligation_ids'])) == len(q['obligation_ids']) and set(q['obligation_ids']) <= obligations,
                'quantity must bind exact existing assignment obligations')
        qindex[q['id']] = q
    require({o for q in qs for o in q['obligation_ids']} == obligations, 'no assigned original obligation may vanish')
    discovery = request['discovery']; keys(discovery, ('as_of', 'scope', 'source_ids', 'candidate_ids'))
    text(discovery['as_of']); text(discovery['scope'])
    require(type(discovery['source_ids']) is list and discovery['source_ids'] and set(discovery['source_ids']) <= resources.keys(),
            'dated discovery source closure required')
    ids = discovery['candidate_ids']; require(type(ids) is list and 0 < len(ids) <= 64 and len(set(ids)) == len(ids),
                                             'unique complete supplied discovery census required')
    for sid in ids: identity(sid)
    studies = request['studies']; require(type(studies) is list and len(studies) == len(ids), 'every supplied candidate needs a study disposition')
    sindex = {}; cells = []; tables = []; groups = {}; obligations_out = []
    for study in studies:
        keys(study, ('id', 'question_ids', 'source_ids', 'basis', 'applicability', 'tables', 'limitations'))
        sid = identity(study['id']); require(sid in ids and sid not in sindex, 'unique candidate study identity required')
        require(type(study['question_ids']) is list and study['question_ids'] and set(study['question_ids']) <= qindex.keys(),
                'study requested quantity binding required')
        require(type(study['source_ids']) is list and study['source_ids'] and set(study['source_ids']) <= resources.keys(),
                'study primary evidence closure required')
        basis = _basis(study['basis']); app = study['applicability']; keys(app, ('state', 'reason', 'evidence_ids'))
        require(app['state'] in ('source_declared', 'unresolved', 'incompatible'), 'supplied applicability, not acceptance, required')
        text(app['reason']); require(type(app['evidence_ids']) is list and app['evidence_ids'] and
              set(app['evidence_ids']) <= set(study['source_ids']), 'located applicability source evidence required')
        require(type(study['limitations']) is list and study['limitations'], 'explicit scientific limits required')
        for note in study['limitations']: text(note)
        unresolved = [k for k,v in basis.items() if v is None]
        require(not unresolved or app['state'] != 'source_declared', 'unknown basis cannot claim source-declared compatibility')
        # Unknown or incompatible studies never coalesce merely because of equal nulls.
        group = digest(basis) if not unresolved and app['state'] == 'source_declared' else 'unresolved-' + sid
        groups.setdefault(group, {'basis':basis,'study_ids':[],'common_curve_authorized':False})['study_ids'].append(sid)
        declared_tables = study['tables']; require(type(declared_tables) is list and len(declared_tables) <= 16,
                                                 'bounded complete supplied study table population required')
        require(declared_tables or app['state'] != 'source_declared', 'source-declared study needs actual quantities')
        seen = set()
        for definition in declared_tables:
            keys(definition, ('source_id', 'expected_rows', 'expected_axes_sha256', 'columns'))
            tid = definition['source_id']; require(tid in study['source_ids'] and tid not in seen, 'unique source-bound study table required'); seen.add(tid)
            table = _table(resources[tid], session)
            axes = table['payload']['independent_variables']; columns = table['payload']['dependent_variables']
            require(type(definition['expected_rows']) is int and definition['expected_rows'] == table['rows'] and
                    digest(axes) == definition['expected_axes_sha256'], 'exact full table row/geometry declaration differs')
            dispositions = definition['columns']; require(type(dispositions) is list and len(dispositions) == len(columns),
                                                        'every dependent column needs a disposition')
            by_index = {}
            for d in dispositions:
                keys(d, ('index', 'state', 'reason')); text(d['reason'])
                require(type(d['index']) is int and 0 <= d['index'] < len(columns) and d['index'] not in by_index and
                        d['state'] in ('deliver', 'context'), 'unique complete dependent-column disposition required')
                by_index[d['index']] = d
            require(any(d['state']=='deliver' for d in dispositions), 'study table needs at least one delivered dependent column')
            unknown = 0; count = 0
            for j,column in enumerate(columns):
                if by_index[j]['state']!='deliver':continue
                unit=_header_unit(column['header'])
                require(app['state']!='source_declared' or unit is not None and unit==basis['unit'],
                        'source-declared basis unit must equal literal delivered source unit; unknown/conversion refused')
            for j, column in enumerate(columns):
                if by_index[j]['state'] != 'deliver': continue
                for row, value in enumerate(column['values']):
                    require(type(value) is dict and 'value' in value, 'complete dependent cell payload required')
                    central = value['value']; missing = central is None or central == '-'
                    unknown += missing; count += 1
                    cells.append({'id': 'cell-'+digest([sid,tid,j,row]), 'study_id':sid, 'resource_id':tid,
                          'column':j,'row':row, 'coordinates':[a['values'][row] for a in axes],
                          'header':column['header'], 'qualifiers':column.get('qualifiers',[]),
                          'payload':deepcopy(value), 'status':'unknown' if missing else 'literal_source'})
            require(len(cells) <= MAX_CELLS, 'full selected source population exceeds32768 cells; no truncation')
            tables.append({'study_id':sid,'resource_id':tid,'source':resources[tid]['pin'],
                           'complete_table':table, 'column_dispositions':dispositions,
                           'selected_cells':count,'unknown_cells':unknown})
            if unknown: obligations_out.append({'study_id':sid,'kind':'unknown_source_cells','count':unknown,'state':'open'})
        if unresolved or app['state'] != 'source_declared': obligations_out.append({'study_id':sid,'kind':'applicability',
                                  'unknown_basis_fields':unresolved,'state':'open','reason':app['reason']})
        sindex[sid] = deepcopy(study)
    require(set(sindex) == set(ids) and {q for s in studies for q in s['question_ids']} == qindex.keys(),
            'complete candidate and requested-quantity portfolio required')
    routes = request['routes']; require(type(routes) is list and len(routes) <= 32, 'bounded prospective ordinary route census required')
    prepared_routes = []; rids = set()
    for route in routes:
        keys(route, ('id', 'study_ids', 'role', 'spec', 'quantity_bindings')); rid = identity(route['id'])
        require(rid not in rids and type(route['study_ids']) is list and route['study_ids'] and
                set(route['study_ids']) <= sindex.keys() and route['role'] in ('study', 'publication'), 'unique complete route binding required'); rids.add(rid)
        spec = session.document(route['spec']); science.validate(spec)
        require(spec['schema_version'] == 2 and spec.get('goal_binding') == request['parent'] and
                spec['mode'] != 'scientific-delivery', 'prospective existing route must retain exact parent and v2 policy')
        _, spec_path = session.file(route['spec'])
        files = science.task_inputs(spec, spec_path.parent)
        for p in files: session.capture(p)
        require(type(route['quantity_bindings']) is list and len(route['quantity_bindings'])<=128, 'bounded exact publication quantity mappings required')
        require((spec['mode']=='published-summary')==(route['role']=='publication'),
                'publication mode requires publication role and complete quantity joins')
        if route['role'] == 'study': require(not route['quantity_bindings'], 'ordinary study routes do not certify publication quantities')
        if route['role'] == 'publication':
            require(spec['mode'] == 'published-summary' and spec['task']['schema_version'] == 2,
                    'existing publication figure contract/v2 required')
            from ravel.physics import published_summary
            loaded = published_summary._load(spec['task'], spec_path.parent)
            target = {'census':loaded['search_census'],'parent':loaded['parent'],'figure':loaded['figure_contract']}
            require(set(target['census']['candidate_ids']) == set(ids), 'publication cannot narrow supplied candidate denominator')
            original = session.document(request['parent']['contract'])
            require(target['parent']['prompt'] == original['prompt'], 'publication must preserve literal original question')
            panel_bases = {}
            for candidate in target['figure']['candidates']:
                declared = sindex[candidate['id']]['basis']
                require(all(declared.get(k) == v for k,v in candidate['model_basis'].items()), 'publication candidate changed model/production/width/BR basis')
                if candidate['panel_id'] is not None:
                    require(all(v is not None for v in declared.values()) and
                            sindex[candidate['id']]['applicability']['state']=='source_declared',
                            'publication needs explicit source-declared full domain/interference applicability')
                    pid = candidate['panel_id']
                    require(pid not in panel_bases or panel_bases[pid] == declared,
                            'incompatible domain/interference cannot share a publication panel')
                    panel_bases[pid] = declared
            require(set(route['study_ids']) == set(ids), 'publication must bind complete supplied study population')
            _publication_quantities(route['quantity_bindings'],loaded,tables,sindex)
        prepared_routes.append({**deepcopy(route), 'spec':session.pins[str(spec_path)],'specification':spec, 'input_paths':[str(p) for p in files],
                                'source_base_dir':str(spec_path.parent),
                                'execution_authorized':False,'scientific_acceptance':False})
    if request['publication_required'] and not any(r['role']=='publication' for r in routes):
        obligations_out.append({'kind':'publication_route','state':'open','reason':'Existing exact figure contract/runtime/source inputs must be supplied before publication preparation.'})
    session.finish()
    return request, session, {'kind':'scientific-delivery-portfolio/v1','original_task':projection,
        'knowledge_context':knowledge,'questions':deepcopy(qs),'discovery':deepcopy(discovery),'studies':list(sindex.values()),
        'basis_groups':list(groups.values()),'tables':tables,'cells':cells,'routes':prepared_routes,
        'delivery_limits':{'source_bytes':TOTAL,'input_files':512,'selected_cells':MAX_CELLS,'portfolio_bytes':32*1024*1024,'report_cells_per_page':32},
        'continuation_obligations':obligations_out,'complete_supplied_candidate_census':True,
        'complete_selected_cell_census':True,'current_literature_census_qualified':False,
        'common_basis_physics_qualified':False,'parent_task_complete':False,
        'publication_delivered':False,'statistical_inference':None,'physics_validated':False}


def inputs(task, base):
    _, session, _ = _load(task, base)
    return [Path(p) for p in session.pins]


def inputs_for_spec(spec, base):
    """Bind the outer ordinary goal to the same admitted input snapshot."""
    request,session,_=_load(spec['task'],base)
    require(spec.get('goal_binding')==request['parent'],
            'ordinary scientific-delivery goal must equal the exact original parent')
    return [Path(p) for p in session.pins]


def _report_pages(result, out):
    """Every selected cell exposed, using existing typed-artifact and report slots."""
    from ravel.workflow import scientific_report
    rows = [{'id':c['id'], 'coordinate':json.dumps(c['coordinates'],sort_keys=True,allow_nan=False),
             'source_value':json.dumps(c['payload'],sort_keys=True,allow_nan=False),
             'meaning':json.dumps({'header':c['header'],'qualifiers':c['qualifiers'],'status':c['status']},sort_keys=True,allow_nan=False)}
            for c in result['cells']]
    basis = b'Literal source-cell transcriptions from the full selected table population. No error-law, likelihood, conversion or applicability inference.\n'
    documents = []
    for start in range(0, len(rows), 32):
        page = out/f'page-{start//32:03d}'; page.mkdir()
        chunk = rows[start:start+32]; data = page/'cells.json'; atomic_json(data, {'cells':chunk})
        # Existing report requires relative basis/tool paths; each page is standalone.
        (page/'basis.txt').write_bytes(basis)
        fields = ('coordinate','source_value','meaning'); facts=[]
        for row in chunk:
            for field in fields:
                facts.append({'id':row['id']+'-'+field,'selector':{'kind':'record','pointer':'/cells','id_field':'id','row_id':row['id'],'field':field},
                    'quantity_id':None,'context_selector':None,'label':row['id']+' '+field,'unit':'literal source JSON',
                    'scope':'Exact selected source cell including unknown tokens and original errors; no conversion',
                    'population':row['id'],'limitations':['Basis/applicability is declared; report delivery cannot accept the original task.']})
        artifact = {'schema_version':1,'basis':[pin(Path('basis.txt'), (page/'basis.txt').read_bytes())],
            'tools':{'table':pin(Path('cells.json'),data.read_bytes())},'contract':{
            'source_scope':'Complete page of literal supplied primary-resource cells',
            'tool_fields':[{'field':'cells','type':{'type':'array','items':{'type':'object','properties':{k:'string' for k in ('id',*fields)}},'max_items':32},
                           'source':{'kind':'direct','tool_id':'table','pointer':'/cells'}}],
            'interpretation_fields':[],'unresolved_semantics':[{'field':'cells','reason':'Applicability, original error law and task completeness remain open.'}],'max_artifact_bytes':128000},'interpretation':{}}
        recipe={'schema_version':1,'title':'Primary study portfolio: '+result['original_task']['original_request'],
            'artifact_request':artifact,'context':None,'facts':facts,'sections':[{'id':'cells','kind':'table',
            'caption':'Every selected row on this page; source JSON preserves literal values, errors and nulls.',
            'columns':list(fields),'rows':[{'id':r['id'],'facts':[r['id']+'-'+f for f in fields]} for r in chunk]}],
            'interpretation':[]}
        delivered = scientific_report.compose(recipe,base_dir=page)
        atomic_json(page/'report-request.json',recipe); atomic_json(page/'report.json',delivered)
        (page/'report.md').write_text(delivered['report_text'])
        documents.append({'id':page.name,'cell_ids':[r['id'] for r in chunk], 'files':[pin(p,p.read_bytes()) for p in (page/'basis.txt',page/'cells.json',page/'report-request.json',page/'report.json',page/'report.md')]})
    require([i for p in documents for i in p['cell_ids']] == [c['id'] for c in result['cells']], 'full report cell exposure differs')
    return documents


def run(task, base, out):
    request, session, result = _load(task,base)
    out = Path(out).absolute()
    require(not out.exists() and not any(p.is_symlink() for p in (out,*out.parents)), 'fresh delivery destination required')
    out.mkdir(parents=True); (out/'sources').mkdir(); (out/'routes').mkdir()
    source_copies=[]
    for index,(path,raw) in enumerate(session.raw.items()):
        destination=out/'sources'/f'{index:03d}-{Path(path).name}'
        destination.write_bytes(raw)
        source_copies.append({'original':session.pins[path],'copy':pin(destination,raw)})
    result['report_pages']=_report_pages(result,out)
    result['source_copies']=source_copies
    for route in result['routes']:
        destination=out/'routes'/(route['id']+'.science.json'); atomic_json(destination,route['specification'])
        route['prepared_spec']=pin(destination,destination.read_bytes())
        route['planning_instruction']='plan_route(result, route_id, rundir) uses the original pinned specification and current ordinary science planner; copied spec is a retained witness, not a relocated input base.'
    result.update(status='passed',status_scope='source_bound_scientific_delivery_preparation',
                  scientific_acceptance=False,execution_authorized=False,native_calls=0,model_calls=0)
    session.finish()
    # New outputs are part of the same delivery postcondition, not unverified strings.
    for item in source_copies:
        p=Path(item['copy']['path']); require(pin(p,source_tables.bounded_read(p,limit=item['copy']['size']))==item['copy'], 'copied source changed')
    result['input_snapshot']=list(session.pins.values())
    for page in result['report_pages']:
        for fact in page['files']:
            p=Path(fact['path']);require(pin(p,source_tables.bounded_read(p,limit=fact['size']))==fact,'generated report changed before delivery')
    for route in result['routes']:
        fact=route['prepared_spec'];p=Path(fact['path']);require(pin(p,source_tables.bounded_read(p,limit=fact['size']))==fact,'prepared route changed before delivery')
    require(len(json.dumps(result,allow_nan=False).encode())<=32*1024*1024,'complete portfolio exceeds32MiB; no truncation')
    atomic_json(out/'portfolio.json',result)
    return result


def plan_route(result, route_id, rundir):
    """Materialize the selected existing ordinary plan; never approve or run it."""
    from ravel.workflow import science
    require(result.get('kind')=='scientific-delivery-portfolio/v1' and
            result.get('scientific_acceptance') is False and result.get('execution_authorized') is False,
            'unqualified prepared portfolio required')
    routes=[r for r in result['routes'] if r['id']==route_id]
    require(len(routes)==1, 'exact selected ordinary route required')
    session=Snapshots(routes[0]['source_base_dir'])
    for fact in result['input_snapshot']: session.file(fact,limit=16*1024*1024)
    route=routes[0];doc=session.document(route['spec'])
    require(doc==route['specification'], 'prospective route specification differs from retained preparation')
    _,path=session.file(route['spec'])
    # Metadata planning reuses the normal source/runtime/review gates.
    planned=science.plan(rundir,path)
    session.finish()
    return planned


def write_report(result, out):
    require(result.get('kind')=='scientific-delivery-portfolio/v1' and result.get('physics_validated') is False,
            'literal source delivery result required')
    out=Path(out)
    lines=['# Original research question','',result['original_task']['original_request'],'',
           '| Supplied study | Quantity IDs | Basis group | Applicability |','|---|---|---|---|']
    for study in result['studies']:
        group=next(i for i,g in enumerate(result['basis_groups']) if study['id'] in g['study_ids'])
        escape=lambda v:str(v).replace('|','\\|').replace('\n',' ')
        lines.append('| '+' | '.join(escape(v) for v in (study['id'],','.join(study['question_ids']),group,study['applicability']['state']))+' |')
    lines+=['','Complete selected-cell reports:']
    for page in result['report_pages']:
        require({Path(f['path']).name for f in page['files']}=={
            'basis.txt','cells.json','report-request.json','report.json','report.md'} and len(page['files'])==5,
            'complete generated page source/report census required')
        for page_pin in page['files']:
            page_path=Path(page_pin['path'])
            require(pin(page_path,source_tables.bounded_read(page_path,limit=page_pin['size']))==page_pin,
                    'page report changed before top-level delivery')
        reports=[f for f in page['files'] if Path(f['path']).name=='report.md']
        require(len(reports)==1,'exact retained page report required')
        fact=reports[0];path=Path(fact['path'])
        require(pin(path,source_tables.bounded_read(path,limit=fact['size']))==fact,
                'page report changed before top-level delivery')
        lines.append(f"- [{page['id']}](<{path}>): {len(page['cell_ids'])} original cells")
    lines+=['','The supplied candidate denominator and all original parent obligations remain retained. Discovery completeness, model/width/energy/BR/interference applicability, scientific reviews and genuine publication runtime/PNG/PDF QA are not inferred.','',
            'Continuation obligations:',json.dumps(result['continuation_obligations'],indent=2,allow_nan=False)]
    atomic_json(out/'scientific-delivery-report.json',result)
    (out/'scientific-delivery-report.md').write_text('\n'.join(lines)+'\n')
    return [{'stem':'scientific-delivery-report','files':['scientific-delivery-report.json','scientific-delivery-report.md'],
             'normalization':'Whole literal source population and separate exact declared bases; no scaling, statistical law or publication success'}]


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['acquire']); parser.add_argument('request');parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    raw=source_tables.bounded_read(Path(args.request).absolute(),limit=DOCUMENT)
    result=acquire(_json(raw),args.out)
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__': main()
