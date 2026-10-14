"""General source-bound linear SAF family using the existing MA5 reader.

No compiler/runtime is invoked. Each arbitrary supplied analysis has its own
literal source bookings, upstream format/API pins and complete named views.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from ravel.physics import ma5_saf as legacy, ma5_bookings


def native_paths(analysis, regions, core_source):
    """Source-derive physical writer roles; keep original logical region IDs."""
    if type(analysis) is not str or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}', analysis):
        raise ValueError('safe explicit native analyzer name required')
    source = ma5_bookings.clean(core_source)
    compact = re.sub(r'"(?:\\.|[^"\\])*"|\s+',
                     lambda m: m[0] if m[0].startswith('"') else '', source)
    expressions = ('analyzers_[i]->Output()+"/"+analyzers_[i]->name()+".saf"',
                   'analyzers_[i]->Output()+"/Histograms/histos.saf"',
                   'myanalysis->Output()+"/Cutflows/"+CleanName(myRS->GetName())+".saf"')
    if any(compact.count(x) != 1 for x in expressions):
        raise ValueError('unsupported source-defined native SAF writer roles')
    replace = ('voidReplaceAll(std::string&name,conststd::string&In,conststd::string&Out)'
               '{size_tpos=name.find(In);while(pos!=std::string::npos)'
               '{name.replace(pos,In.size(),Out);pos=name.find(In);}}')
    if compact.count(replace) != 1:
        raise ValueError('unsupported native ReplaceAll algorithm')
    bodies = re.findall(r'std::stringCleanName\(conststd::string&name\)\{([^{}]*)\}', compact)
    if len(bodies) != 1:
        raise ValueError('one literal source CleanName body required')
    body = bodies[0]
    pattern = r'ReplaceAll\(tmp,("(?:\\.|[^"\\])*"),("(?:\\.|[^"\\])*")\);'
    calls = list(re.finditer(pattern, body))
    if not calls or re.sub(pattern, '', body) != 'std::stringtmp=name;returntmp;':
        raise ValueError('dynamic native filename cleaning unsupported')
    rules = [(json.loads(m[1]), json.loads(m[2])) for m in calls]
    if any(not old or old in new for old, new in rules):
        raise ValueError('nonterminating source filename cleaning unsupported')
    # Source ReplaceAll rescans from the beginning, not a single replacement.
    paths, used = {}, set()
    for region in regions:
        value = region
        for old, new in rules:
            count = 0
            while old in value:
                value = value.replace(old, new, 1); count += 1
                if count > 4096 or len((value+'.saf').encode()) > 255:
                    raise ValueError('native filename exceeds finite portable component bound')
        if len((value+'.saf').encode()) > 255:
            raise ValueError('native filename exceeds finite portable component bound')
        if not value or value in ('.', '..') or any(x in value for x in '/\\\n\r\x00'):
            raise ValueError('unsafe source-derived native cutflow name')
        path = 'Cutflows/'+value+'.saf'
        if path in used:
            raise ValueError('distinct source regions collide after native filename cleaning')
        paths[region] = path; used.add(path)
    return {'analysis_file': analysis+'.saf', 'histograms': 'Histograms/histos.saf',
            'cutflow_files': paths, 'cleaning_rules': [list(x) for x in rules]}


def layout(doc, expected, capture, base):
    _, raw = capture.pin(doc['upstream']['core'], base)
    return native_paths(doc['analysis'], expected['regions'], raw.decode())


def load(task, base):
    legacy.validate(task); c = legacy.Capture()
    path, raw = c.read(task['input'], base); doc = legacy._json(raw)
    legacy._keys(doc, ('schema_version', 'analysis', 'source', 'bookings', 'upstream', 'views', 'population_scope'), 'general SAF input')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 2:
        raise ValueError('general SAF schema2 required')
    if type(doc['analysis']) is not str or not doc['analysis'].strip() or type(doc['population_scope']) is not str or not doc['population_scope'].strip():
        raise ValueError('analysis identity and supplied population scope required')
    source_path, source = c.pin(doc['source'], path.parent)
    expected = ma5_bookings.compile_source(source.decode())
    booking_path, raw = c.pin(doc['bookings'], path.parent); declared = legacy._json(raw)
    declaration_keys = (*expected, 'source', 'scope')
    if 'physics_configuration' in expected: declaration_keys += ('configuration_sources',)
    legacy._keys(declared, declaration_keys, 'general source bookings')
    p, s = c.pin(declared['source'], booking_path.parent)
    if p != source_path or s != source or {k: declared[k] for k in expected} != expected:
        raise ValueError('source-defined complete booking denominator differs')
    if type(declared['scope']) is not str or not declared['scope'].strip(): raise ValueError('booking scope required')
    ma5_bookings.configuration_sources(expected, declared, c, booking_path.parent)
    legacy._keys(doc['upstream'], ('manager', 'saf_writer', 'core', 'revision'), 'upstream format API')
    if type(doc['upstream']['revision']) is not str or not doc['upstream']['revision'].strip(): raise ValueError('source revision attribution required')
    for key in ('manager', 'saf_writer', 'core'): c.pin(doc['upstream'][key], path.parent)
    paths = layout(doc, expected, c, path.parent)
    c.native_file_mapping = paths
    if type(doc['views']) is not dict or not 1 <= len(doc['views']) <= 16:
        raise ValueError('one to sixteen complete named views required')
    contents, roots = {}, set()
    for name, view in doc['views'].items():
        if type(name) is not str or not name.strip(): raise ValueError('named view required')
        legacy._keys(view, ('root', 'files', 'expected_initial_entries', 'population_description'), 'named SAF view')
        if type(view['expected_initial_entries']) is not int or not 0 <= view['expected_initial_entries'] <= 10**9:
            raise ValueError('explicit complete original event denominator required')
        if type(view['population_description']) is not str or not view['population_description'].strip(): raise ValueError('view population attribution required')
        root = Path(view['root']); root = root if root.is_absolute() else path.parent / root
        c.census(root); identity = root.stat(); physical = (identity.st_dev, identity.st_ino)
        if physical in roots: raise ValueError('each named view must have a distinct physical root')
        roots.add(physical)
        required = {paths['analysis_file'], paths['histograms'], *paths['cutflow_files'].values()}
        if type(view['files']) is not dict or set(view['files']) != required or c.census(root) != required:
            raise ValueError('complete native SAF membership differs')
        c.roots[root] = required; contents[name] = {}
        for rel in sorted(required):
            _, b = c.pin({'path': str(root/rel), 'sha256': view['files'][rel]}, path.parent)
            contents[name][rel] = b.decode()
    c.finish()
    return doc, expected, contents, c


def inputs(task, base):
    doc, expected, texts, c = load(task, base)
    paths = c.native_file_mapping
    for name in texts: legacy._view(texts[name], expected, doc['views'][name]['expected_initial_entries'],
                                  analysis_file=paths['analysis_file'], cutflow_files=paths['cutflow_files'])
    c.finish()
    return [*sorted(c.files), Path(__file__).resolve(), Path(ma5_bookings.__file__).resolve(), Path(legacy.reader.__file__).resolve()]


def run(task, base, output):
    doc, expected, texts, c = load(task, base)
    paths = c.native_file_mapping
    views = {name: legacy._view(value, expected, doc['views'][name]['expected_initial_entries'],
                               analysis_file=paths['analysis_file'], cutflow_files=paths['cutflow_files']) for name, value in texts.items()}
    c.finish()
    result = {'kind': 'complete-supplied-ma5-family', 'status': 'passed', 'physics_validated': False,
        'analysis': doc['analysis'], 'views': views, 'source_bookings': expected, 'population_scope': doc['population_scope'],
        'native_file_mapping': paths,
        'population_descriptions': {k: v['population_description'] for k, v in doc['views'].items()},
        'source': deepcopy(doc['source']), 'upstream': deepcopy(doc['upstream']),
        'input_pins': [{'path': str(p), 'sha256': hashlib.sha256(b).hexdigest()} for p, (_, b) in sorted(c.files.items())],
        'native_engine_executed': False, 'events_generated': 0, 'same_event_population_validated': False,
        'scope': 'Complete source-defined supported linear SAF records and raw sign channels; no statistical inference',
        'limitations': ['No per-bin second moments, cross-bin or cross-region covariance is invented.',
                       'Named views retain their independent original populations; no same-event join is inferred.',
                       'Literal Initialize booking family only; dynamic or non-linear plots require a separate source-qualified contract.',
                       'Supplied source/API bytes and output correspondence do not establish executable, detector or physics fidelity.']}
    out = Path(output); out.mkdir(parents=True, exist_ok=False)
    legacy._write_result(out, result, task); c.finish(); return result
