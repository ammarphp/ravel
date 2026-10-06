"""Run a supplied, source-bound upstream SimpleAnalysis executable on slim ROOT.

The binary build is an explicit supplied attestation, not reconstructed from its
filename. No detector conversion, container provisioning or smearing is inferred.
"""
import csv
import math
import os
from pathlib import Path
import re
import subprocess
from ravel.workflow.science import regular
from ravel.workflow.state_io import read_json, atomic_json
from ravel.workflow.execution import file_hash


def validate(task):
    if set(task) != {'backend', 'routine', 'source_root', 'events', 'object_contract', 'runtime', 'regions'} or task['backend'] != 'simpleanalysis':
        raise ValueError('invalid SimpleAnalysis task fields')
    r = task['runtime']
    if not isinstance(r, dict) or set(r) != {'executable', 'build_manifest', 'artifacts', 'environment'} or not r['artifacts']:
        raise ValueError('SimpleAnalysis requires binary, build manifest, dependency artifacts and environment')
    from ravel.physics.existing_events import ENVIRONMENT
    if not isinstance(r['environment'], dict) or set(r['environment']) - ENVIRONMENT or any(not isinstance(v, str) for v in r['environment'].values()):
        raise ValueError('invalid runtime environment')
    if not isinstance(task['regions'], list) or not task['regions'] or len(set(task['regions'])) != len(task['regions']) or any(not isinstance(x,str) or not re.fullmatch('[A-Za-z0-9_]+', x) or x == 'All' for x in task['regions']):
        raise ValueError('explicit unique analysis region names required')


def source(task, base):
    from ravel.analysis_catalog import load_catalog, resolve, verify_source
    catalog = load_catalog(); row = resolve(catalog, task['routine'])
    if row['framework'] != 'simpleanalysis':
        raise ValueError('expected a SimpleAnalysis routine')
    root = (Path(base) / task['source_root']).resolve()
    checked = verify_source(catalog, row, root)
    if checked['status'] != 'PASS':
        raise ValueError('upstream source check failed: ' + '; '.join(checked['issues']))
    manifest_path = regular(task['runtime']['build_manifest'], base)
    manifest = read_json(manifest_path)
    if set(manifest) != {'schema_version', 'source_revision', 'framework_revision', 'binary_sha256', 'source_sha256', 'build_log', 'build_log_sha256', 'description'} or manifest['schema_version'] != 1:
        raise ValueError('invalid supplied build attestation')
    binary = regular(task['runtime']['executable'], base)
    if (manifest['source_revision'] != catalog['sources']['simpleanalysis']['revision']
            or manifest['framework_revision'] != 'd9f8c7044dacd40b0a8f42795181f99e2c6d6e7b'
            or manifest['binary_sha256'] != file_hash(binary)):
        raise ValueError('binary/source/framework differs from build attestation')
    sources = [root/f['path'] for f in row['source_files']]
    if manifest['source_sha256'] != {f['path']: file_hash(root/f['path']) for f in row['source_files']}:
        raise ValueError('selected routine source differs from the build attestation')
    build_log = regular(manifest['build_log'], base)
    if file_hash(build_log) != manifest['build_log_sha256'] or not isinstance(manifest['description'],str) or not manifest['description'].strip():
        raise ValueError('missing or changed build evidence')
    sources += [root/m['path'] for a in row.get('external_assets',[]) for m in a['matches']]
    return row, [binary, manifest_path, build_log, *sources], manifest


def inputs(task, base):
    validate(task)
    _, files, _ = source(task, base)
    files += [regular(task[k], base) for k in ('events', 'object_contract')]
    contract = read_json(regular(task['object_contract'], base))
    files.append(regular(contract['object_definitions'], base))
    files += [regular(p, base) for p in contract['response_evidence']]
    for p in task['runtime']['artifacts']:
        path = (Path(base)/p).resolve()
        if not path.exists():
            raise ValueError('missing runtime dependency artifact')
        files.append(path)
    return files


def exact_event_id(value):
    # Never coerce a floating event key through a lossy join.
    if isinstance(value, bool) or not math.isfinite(value) or int(value) != value:
        raise ValueError('event identifier must be an exact finite integer')
    return int(value)


def read_input(path, contract):
    try:
        import uproot
    except ImportError as exc:
        raise ValueError('SimpleAnalysis slim ROOT transport requires ravel-hep[science]') from exc
    if set(contract) != {'schema_version','level','energy_unit','source','object_definitions','response_evidence','weight_names','independent_events'} or contract['schema_version'] != 1:
        raise ValueError('invalid SimpleAnalysis slim-object contract')
    if contract['level'] != 'reconstructed' or contract['energy_unit'] != 'GeV' or contract['independent_events'] is not True:
        raise ValueError('this adapter requires reconstructed GeV slim inputs and independent event numbers')
    if not contract['source'] or not contract['object_definitions'] or contract['weight_names'] != ['nominal']:
        raise ValueError('declare object definitions and a single nominal weight stream')
    with uproot.open(path) as f:
        t = f['ntuple']
        if not {'EventNumber','mcWeights'} <= set(t.keys()):
            raise ValueError('slim input is missing event identity or nominal weight')
        a = t.arrays(['EventNumber','mcWeights'],library='ak')
        events = {}
        for eid, weights in zip(a['EventNumber'], a['mcWeights']):
            eid = exact_event_id(eid)
            if len(weights) != 1 or not math.isfinite(float(weights[0])) or float(weights[0]) == 0:
                raise ValueError('one finite nonzero weight required; upstream skips zero-weight events')
            if int(eid) in events:
                raise ValueError('duplicate independent event identifier')
            events[int(eid)] = float(weights[0])
    if not events or math.fsum(events.values()) == 0:
        raise ValueError('empty or zero-normalization sample')
    return events


def parse_outputs(directory, routine, expected, regions):
    import uproot
    directory = Path(directory)
    with (directory/'selection.txt').open() as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ['SR','events','acceptance','err']:
            raise ValueError('unsupported SimpleAnalysis yield serialization')
        rows = {}
        for r in reader:
            name = r['SR']
            if name.startswith(routine+'__'):
                name = name[len(routine)+2:]
            elif name.startswith(routine+'_'):
                name = name[len(routine)+1:]
            elif name.startswith(routine):
                name = name[len(routine):]
            if name in rows:
                raise ValueError('duplicate upstream region')
            vals = [float(r[k]) for k in ('events','acceptance','err')]
            if not all(math.isfinite(x) for x in vals) or vals[0] < 0 or vals[0] != int(vals[0]):
                raise ValueError('invalid upstream moments')
            rows[name] = vals
    if 'All' not in rows or not set(regions) <= set(rows):
        raise ValueError('upstream omitted requested regions or all-event exposure')
    denom = math.fsum(expected.values())
    sumw2 = math.fsum(w*w for w in expected.values())
    if rows['All'][0] != len(expected) or not math.isclose(rows['All'][1],denom,rel_tol=2e-5,abs_tol=1e-8) or not math.isclose(rows['All'][2],sumw2,rel_tol=2e-5,abs_tol=1e-8):
        raise ValueError('upstream all-event exposure differs from input census')
    with uproot.open(directory/'selection.root') as f:
        trees = [obj for key,obj in f.items() if hasattr(obj,'arrays') and key.split(';')[0].endswith('ntuple')]
        if len(trees) != 1:
            raise ValueError('exactly one output decision tree required')
        tree = trees[0]
        required = ['Event','eventWeight',*regions]
        # Unselected regions may never acquire an ntuple branch; the explicit
        # zero count in the independent summary is required before filling zero.
        absent = set(required) - set(tree.keys())
        if absent - {r for r in regions if rows[r][0] == 0}:
            raise ValueError('missing upstream decision branch')
        data = tree.arrays([k for k in required if k not in absent],library='np')
    traces, seen = [], set()
    for i,e in enumerate(data['Event']):
        eid = exact_event_id(e)
        if eid not in expected or eid in seen or not math.isclose(float(data['eventWeight'][i]),expected[eid],rel_tol=2e-6,abs_tol=1e-8):
            raise ValueError('upstream decision event identities or weights differ')
        seen.add(eid)
        contributions = {r: 0. if r in absent else float(data[r][i]) for r in regions}
        if any(not math.isfinite(v) for v in contributions.values()):
            raise ValueError('nonfinite per-event region contribution')
        traces.append({'event_id':str(eid),'regions':[r for r,v in contributions.items() if v != 0], 'contributions':contributions})
    if seen != set(expected):
        raise ValueError('upstream omitted rejected input events')
    yields = [math.fsum(t['contributions'][r] for t in traces) for r in regions]
    covariance = [[math.fsum(t['contributions'][r]*t['contributions'][q] for t in traces) for q in regions] for r in regions]
    for i,r in enumerate(regions):
        if (rows[r][0] != sum(r in t['regions'] for t in traces)
                or not math.isclose(yields[i]/denom,rows[r][1],rel_tol=2e-5,abs_tol=1e-8)
                or not math.isclose(math.sqrt(covariance[i][i])/denom,rows[r][2],rel_tol=2e-5,abs_tol=1e-8)):
            raise ValueError('upstream per-event contributions disagree with region summary')
    return {'events':len(expected),'region_names':regions,'yields':{'nominal':yields},'covariance':{'nominal':covariance},
            'region_overlap_counts':{r:{q:sum(r in t['regions'] and q in t['regions'] for t in traces) for q in regions} for r in regions},
            'decisions':traces, 'all_upstream_regions':sorted(set(rows)-{'All'}), 'sumw_all_events':[denom]}


def run(task, base, out):
    validate(task)
    row, _, manifest = source(task, base)
    contract = read_json(regular(task['object_contract'],base))
    expected = read_input(regular(task['events'],base),contract)
    out = Path(out)
    env = os.environ.copy(); env.update(task['runtime']['environment'])
    env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    command = [str(regular(task['runtime']['executable'],base)), '-a',row['name'],'-o',str(out/'selection'),'-n','-w','0',str(regular(task['events'],base))]
    from ravel.physics.existing_events import _call
    _call(command,out,env,out/'simpleanalysis.log')
    result = parse_outputs(out,row['name'],expected,task['regions'])
    atomic_json(out/'decisions.json',result.pop('decisions'))
    result.update(status='passed',physics_validated=False,scope='Supplied upstream binary on existing reconstructed slim events',
                  routine=row['id'],build_attestation=manifest,
                  limitations=['Build/source correspondence is a supplied attestation, not an independently repeated build.',
                    'No detector conversion or smearing is inferred; object-response evidence requires separate validation.',
                    'Only declared regions and a nominal independent-event weight stream are transported.',
                    'Marginal ROOT/CSV precision is retained; no limits are inferred from overlapping region yields.'])
    return result
