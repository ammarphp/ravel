"""Supplied tree-level parton records -> coherent, named NNPDF PDF variations.

No events are generated or reconstructed. Fixed response/normalization inputs
are consumed verbatim. This first operation supports ONLY the complete installed
NNPDF30_nlo_as_0118 replica set and PDF-only, counterterm-free LO reweighting.
It preserves member-zero, replica-mean, PDF covariance and MC covariance as
distinct quantities. No PDF-to-likelihood compression or physics acceptance.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SET = 'NNPDF30_nlo_as_0118'
VERSION = '6.5.6'
MEMBERS = 101
FLAVORS = [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5, 21]
SCOPE = 'PDF-only tree-level fixed-parton-record reweighting with supplied fixed response'
LIMITS = [
    'No NLO counterterms, changed alpha_s, scales, amplitudes, shower, tune, decays or detector response.',
    'Source declarations require separate physics adjudication; this operation cannot prove their physical truth.',
    'All replicas are retained. No automatic Hessian conversion, nuisance compression or likelihood acceptance.',
    'PDF ensemble covariance and Poissonized independent-event MC covariance are separate, conditional quantities.',
    'Host OS libraries remain outside the finite installed runtime capsule.',
]


def _keys(obj, required, label='object'):
    if not isinstance(obj, dict) or set(obj) != set(required):
        raise ValueError(label + ': exact keys required')


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('nonempty identity required')
    return value


def _number(value):
    if type(value) not in (float, int):
        raise ValueError('finite number required')
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError('finite number required') from exc
    if not math.isfinite(result):
        raise ValueError('finite number required')
    return result


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA256 required')
    return value


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _regular(value, base, directory=False):
    p = Path(_text(value)).expanduser()
    p = p if p.is_absolute() else Path(base) / p
    if any(q.is_symlink() for q in (p, *p.parents)) or not (p.is_dir() if directory else p.is_file()):
        raise ValueError('regular non-symlink path required: ' + str(p))
    return p.resolve()


def _pin(pin, base):
    _keys(pin, ('path', 'sha256'), 'pin')
    p = _regular(pin['path'], base)
    if _hash(p) != _sha(pin['sha256']):
        raise ValueError('source pin differs: ' + str(p))
    return p


def _library(pin, base):
    _keys(pin, ('load_path', 'path', 'sha256'), 'native library topology')
    physical = _pin({'path': pin['path'], 'sha256': pin['sha256']}, base)
    load = Path(pin['load_path'])
    load = load if load.is_absolute() else Path(base) / load
    if any(p.is_symlink() for p in load.parents) or not load.is_file() or load.resolve() != physical:
        raise ValueError('native library load alias changed')
    return physical


def _read(path):
    from ravel.workflow.state_io import read_json
    return read_json(path)


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def data_census(root):
    """Closed set/config/index membership, including unexpected files and aliases."""
    root = _regular(str(root), '.', directory=True)
    files = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('PDF data aliases forbidden')
        if not p.is_dir():
            if not p.is_file():
                raise ValueError('regular PDF asset required')
            files[p.relative_to(root).as_posix()] = _hash(p)
    expected = {'lhapdf.conf', 'pdfsets.index', SET + '/' + SET + '.info'} | {
        SET + '/' + SET + '_%04d.dat' % i for i in range(MEMBERS)}
    if set(files) != expected:
        raise ValueError('complete exact PDF member/config/index census differs')
    return {'schema_version': 1, 'files': files}


def _data(spec, base):
    _keys(spec, ('root', 'manifest'), 'PDF data tree')
    root = _regular(spec['root'], base, directory=True)
    manifest = _pin(spec['manifest'], base)
    if _read(manifest) != data_census(root):
        raise ValueError('PDF data bytes or membership changed')
    return root, manifest


def validate(task):
    _keys(task, ('config',), 'PDF variation task')
    _text(task['config'])
    return deepcopy(task)


def validate_config(c):
    _keys(c, ('schema_version', 'source', 'runtime', 'pdf_data', 'records',
              'max_seconds', 'max_ram_mib'), 'PDF variation config')
    if type(c['schema_version']) is not int or c['schema_version'] != 1:
        raise ValueError('unsupported PDF variation version')
    _text(c['source'])
    _keys(c['runtime'], ('python', 'python_manifest', 'native_libraries'), 'runtime')
    for pin in [c['runtime']['python'], c['runtime']['python_manifest'], c['records']]:
        _keys(pin, ('path', 'sha256'), 'file pin'); _text(pin['path']); _sha(pin['sha256'])
    libs = c['runtime']['native_libraries']
    if not isinstance(libs, list) or not 1 <= len(libs) <= 32:
        raise ValueError('explicit finite native libraries required')
    for pin in libs:
        _keys(pin, ('load_path', 'path', 'sha256')); _text(pin['load_path']); _text(pin['path']); _sha(pin['sha256'])
    if type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 300:
        raise ValueError('native time ceiling must be 1..300 seconds')
    if type(c['max_ram_mib']) is not int or not 512 <= c['max_ram_mib'] <= 4096:
        raise ValueError('native RAM ceiling must be 512..4096 MiB')
    return c


def validate_records(doc):
    _keys(doc, ('schema_version', 'kind', 'source', 'pdf', 'perturbative_contract',
                'normalization', 'source_inputs', 'regions', 'events'), 'parton records')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1 or doc['kind'] != 'pdf-fixed-parton-records':
        raise ValueError('unsupported parton record schema')
    _text(doc['source'])
    _keys(doc['pdf'], ('set', 'data_version', 'nominal_member', 'members', 'error_type'))
    if doc['pdf'] != {'set': SET, 'data_version': 2, 'nominal_member': 0,
                      'members': list(range(MEMBERS)), 'error_type': 'replicas'}:
        raise ValueError('complete ordered NNPDF replica set required; no missing, Hessian or mixed members')
    # Also reject bool masquerading as integer in equality above.
    if any(type(i) is not int for i in doc['pdf']['members']) or type(doc['pdf']['nominal_member']) is not int or type(doc['pdf']['data_version']) is not int:
        raise ValueError('exact integer PDF metadata required')
    p = doc['perturbative_contract']
    _keys(p, ('hard_order', 'counterterms', 'operation', 'scale_source', 'alpha_s_policy',
              'response_policy', 'group_rule', 'definition'))
    if (p['hard_order'], p['counterterms'], p['operation'], p['alpha_s_policy'], p['response_policy'], p['group_rule']) != (
            'LO', 'none', 'pdf_only', 'unchanged_all_members', 'fixed_supplied', 'independent_single_event'):
        raise ValueError('only explicit counterterm-free LO PDF-only fixed-response operation is supported')
    _text(p['scale_source'])
    _text(p['definition'])
    n = doc['normalization']
    _keys(n, ('nominal_weight_unit', 'output_unit', 'factor', 'factor_policy', 'definition'))
    if (n['nominal_weight_unit'], n['output_unit'], n['factor_policy']) != (
            'supplied_integral_contribution', 'expected_events', 'fixed_common_to_all_members') or _number(n['factor']) <= 0:
        raise ValueError('explicit positive fixed weight-to-events normalization required')
    _text(n['definition'])
    pins = doc['source_inputs']
    if not isinstance(pins, list) or not 1 <= len(pins) <= 64:
        raise ValueError('explicit source input file pins required')
    origins = set()
    for pin in pins:
        _keys(pin, ('path', 'sha256')); _text(pin['path']); _sha(pin['sha256'])
        if pin['sha256'] in origins: raise ValueError('duplicate source input bytes')
        origins.add(pin['sha256'])
    regions = doc['regions']
    if not isinstance(regions, list) or not 1 <= len(regions) <= 32:
        raise ValueError('1..32 explicit complete regions/bins required')
    names = []
    for r in regions:
        _keys(r, ('id', 'channel', 'bin', 'definition'))
        for v in r.values(): _text(v)
        if r['id'] in names: raise ValueError('duplicate region identity')
        names.append(r['id'])
    if len({(r['channel'], r['bin']) for r in regions}) != len(regions):
        raise ValueError('duplicate likelihood channel/bin coordinate')
    events = doc['events']
    if not isinstance(events, list) or not 1 <= len(events) <= 4096:
        raise ValueError('1..4096 full supplied event groups required')
    ids = set()
    for e in events:
        _keys(e, ('id', 'input_sha256', 'encounter_ordinal', 'pdg1', 'pdg2', 'x1', 'x2',
                  'q_factorization_gev', 'nominal_weight', 'response'))
        _sha(e['input_sha256'])
        if e['input_sha256'] not in origins: raise ValueError('unbound input encounter origin')
        if type(e['encounter_ordinal']) is not int or e['encounter_ordinal'] < 0 or e['id'] != e['input_sha256'] + ':' + str(e['encounter_ordinal']) or e['id'] in ids:
            raise ValueError('unique byte-bound input encounter identity required')
        ids.add(e['id'])
        for key in ('pdg1', 'pdg2'):
            if type(e[key]) is not int or e[key] not in FLAVORS:
                raise ValueError('explicit supported parton PDG required; gluon is 21')
        for key in ('x1', 'x2'):
            if not 0 < _number(e[key]) < 1: raise ValueError('parton x must be in (0,1)')
        if not 0 < _number(e['q_factorization_gev']) <= 100000:
            raise ValueError('explicit factorization Q in GeV required; SCALUP is not inferred')
        _number(e['nominal_weight'])
        _keys(e['response'], names, 'complete fixed response')
        if any(not 0 <= _number(v) <= 1 for v in e['response'].values()):
            raise ValueError('supplied fixed region multipliers must lie in [0,1]')
    return doc


def _load(task, base):
    validate(task)
    path = _regular(task['config'], base)
    return path, validate_config(_read(path))


def inputs(task, base):
    path, c = _load(task, base)
    root, manifest = _data(c['pdf_data'], path.parent)
    python = _pin(c['runtime']['python'], path.parent)
    if not os.access(python, os.X_OK): raise ValueError('executable native Python required')
    support = _pin(c['runtime']['python_manifest'], path.parent)
    runtime = _read(support)
    if runtime.get('python_sha256') != c['runtime']['python']['sha256'] or not runtime.get('files'):
        raise ValueError('installed Python manifest differs')
    deps = [_pin(p, path.parent) for p in runtime['files']]
    libs = [_library(p, path.parent) for p in c['runtime']['native_libraries']]
    record = _pin(c['records'], path.parent)
    records = validate_records(_read(record))
    origins = [_pin(pin, record.parent) for pin in records['source_inputs']]
    package = Path(__file__).resolve().parents[1]
    return sorted(set([path, python, support, record, manifest, *origins, *libs, *deps,
                       *[root / name for name in data_census(root)['files']],
                       *[p.resolve() for p in package.rglob('*.py')]]))


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds'] + 60


def _checked_product(a, b):
    value = a * b
    if not math.isfinite(value) or (a != 0 and b != 0 and value == 0):
        raise ValueError('nonfinite or underflowed PDF/yield arithmetic')
    return value


def _ratio(a, b):
    value = a / b
    if not math.isfinite(value) or (a != 0 and value == 0):
        raise ValueError('nonfinite or underflowed PDF ratio')
    return value


def _sum(values):
    try:
        value = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ValueError('nonfinite accumulated PDF/yield arithmetic') from exc
    return _number(value)


def transport(doc, evaluated):
    """Pure arithmetic: preserve complete event/member identity and shared regions.

    evaluated rows contain raw, unclipped native x*f values and alpha_s(Q).
    Fake/source fixtures may call this routine without loading any native module.
    """
    validate_records(doc)
    _keys(evaluated, ('schema_version', 'set', 'data_version', 'member_ids', 'events'))
    if (type(evaluated['schema_version']) is not int or evaluated['schema_version'] != 1 or
            evaluated['set'] != SET or type(evaluated['data_version']) is not int or evaluated['data_version'] != 2 or
            evaluated['member_ids'] != list(range(MEMBERS)) or any(type(v) is not int for v in evaluated['member_ids'])):
        raise ValueError('evaluated full member identity differs')
    rows = evaluated['events']
    if not isinstance(rows, list) or len(rows) != len(doc['events']):
        raise ValueError('native full event population differs')
    by_id = {}
    for row in rows:
        _keys(row, ('id', 'pdg1', 'pdg2', 'x1', 'x2', 'q_factorization_gev', 'xf1', 'xf2', 'alpha_s'))
        if row['id'] in by_id: raise ValueError('duplicate native event identity')
        by_id[row['id']] = row
    regions = [r['id'] for r in doc['regions']]
    vectors = {i: [] for i in range(MEMBERS)}
    event_weights = []
    for e in sorted(doc['events'], key=lambda x: x['id']):
        if e['id'] not in by_id: raise ValueError('native event identity missing')
        row = by_id[e['id']]
        for key in ('pdg1', 'pdg2', 'x1', 'x2', 'q_factorization_gev'):
            if type(row[key]) is bool or row[key] != e[key]: raise ValueError('native parton/scale point differs')
        arrays = []
        for key in ('xf1', 'xf2', 'alpha_s'):
            if not isinstance(row[key], list) or len(row[key]) != MEMBERS: raise ValueError('complete PDF vectors required')
            arrays.append([_number(v) for v in row[key]])
        a, b, alpha = arrays
        if a[0] == 0 or b[0] == 0: raise ValueError('zero nominal PDF density; no epsilon substitution')
        if any(v <= 0 or abs(v-alpha[0]) > 128*sys.float_info.epsilon*max(v, alpha[0]) for v in alpha):
            raise ValueError('changed alpha_s is unsupported')
        weights = []
        for member in range(MEMBERS):
            ratio = _checked_product(_ratio(a[member], a[0]), _ratio(b[member], b[0]))
            if not math.isfinite(ratio): raise ValueError('nonfinite PDF ratio')
            w = _checked_product(_number(e['nominal_weight']), ratio)
            w = _checked_product(w, _number(doc['normalization']['factor']))
            weights.append(w)
            vectors[member].append([_checked_product(w, _number(e['response'][r])) for r in regions])
        event_weights.append({'id': e['id'], 'named_weights': dict(zip(weight_names(), weights))})
    yields = [[_sum(g[j] for g in vectors[i]) for j in range(len(regions))] for i in range(MEMBERS)]
    for row in yields:
        for v in row: _number(v)
    mean = [_sum(row[j] for row in yields[1:]) / (MEMBERS-1) for j in range(len(regions))]
    cov = [[_sum(_checked_product(row[j]-mean[j], row[k]-mean[k]) for row in yields[1:]) / (MEMBERS-2)
            for k in range(len(regions))] for j in range(len(regions))]
    mc = [[_sum(_checked_product(g[j], g[k]) for g in vectors[0]) for k in range(len(regions))] for j in range(len(regions))]
    correlations = [[(cov[j][k] / math.sqrt(cov[j][j])) / math.sqrt(cov[k][k]) if cov[j][j] > 0 and cov[k][k] > 0 else None
                     for k in range(len(regions))] for j in range(len(regions))]
    result = {'schema_version': 1, 'scope': SCOPE, 'physics_validated': False,
              'region_basis': deepcopy(doc['regions']), 'weight_names': weight_names(),
              'event_weights': event_weights, 'member_yields': yields,
              'nominal_member_zero': yields[0], 'replica_mean': mean,
              'pdf_covariance': cov, 'pdf_correlation': correlations,
              'pdf_uncertainty_semantics': 'unbiased_replica_sample_covariance_members_1_to_100',
              'nominal_mc_covariance': mc,
              'mc_uncertainty_semantics': 'poissonized_independent_single_event_uncentered_second_moment',
              'normalization': deepcopy(doc['normalization']), 'limitations': LIMITS}
    # Reject overflow in matrices too. Null correlation is an explicit zero-variance boundary.
    for matrix in (cov, mc):
        for row in matrix:
            for value in row: _number(value)
    return result


def weight_names():
    return ['nominal'] + ['pdf:' + SET + ':member:%04d' % i for i in range(1, MEMBERS)]


def evaluate(doc, lhapdf):
    """Actual library calls, only inside the approved native worker."""
    validate_records(doc)
    if lhapdf.version() != VERSION: raise ValueError('qualified native API is LHAPDF 6.5.6')
    pdfset = lhapdf.getPDFSet(SET)
    if (pdfset.name, pdfset.size, pdfset.dataversion, pdfset.errorType) != (SET, MEMBERS, 2, 'replicas'):
        raise ValueError('loaded PDF set metadata differs')
    pdfs = pdfset.mkPDFs()
    if len(pdfs) != MEMBERS or [p.memberID for p in pdfs] != list(range(MEMBERS)):
        raise ValueError('loaded PDF member census differs')
    for p in pdfs:
        if p.type != ('central' if p.memberID == 0 else 'replica'):
            raise ValueError('native central/replica member type differs')
        if sorted(p.flavors()) != FLAVORS or int(p.info().get_entry('ForcePositive')) != 0:
            raise ValueError('flavors differ or PDF positivity clipping enabled')
    rows = []
    for e in doc['events']:
        q = e['q_factorization_gev']
        if any(not p.inRangeXQ(e['x1'], q) or not p.inRangeXQ(e['x2'], q) for p in pdfs):
            raise ValueError('PDF grid extrapolation is unsupported')
        rows.append({**{k: e[k] for k in ('id', 'pdg1', 'pdg2', 'x1', 'x2', 'q_factorization_gev')},
                     'xf1': [p.xfxQ(e['pdg1'], e['x1'], q) for p in pdfs],
                     'xf2': [p.xfxQ(e['pdg2'], e['x2'], q) for p in pdfs],
                     'alpha_s': [p.alphasQ(q) for p in pdfs]})
    raw = {'schema_version': 1, 'set': SET, 'data_version': pdfset.dataversion,
           'member_ids': [p.memberID for p in pdfs], 'events': rows}
    result = transport(doc, raw)
    library = []
    for j in range(len(doc['regions'])):
        values = [row[j] for row in result['member_yields']]
        u = pdfset.uncertainty(values, cl=68.268949, alternative=False)
        target = [result['replica_mean'][j], math.sqrt(result['pdf_covariance'][j][j])]
        got = [_number(u.central), _number(u.errsymm)]
        # Explicit mechanical agreement budget; this is not an analysis tolerance.
        if any(not math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-10) for a, b in zip(got, target)):
            raise ValueError('independent replica arithmetic disagrees with LHAPDF uncertainty')
        library.append({'central': got[0], 'symmetric_error': got[1], 'confidence_level_percent': 68.268949})
    result['native_uncertainties'] = library
    result['native_version'] = VERSION
    return raw, result


def _approved(task, output):
    for rd in (Path(output).absolute(), *Path(output).absolute().parents):
        if (rd / 'inputs/science-plan.json').is_file():
            from ravel.workflow import science
            selected = science.verify_worker(rd)
            spec = science.execution_spec(rd)
            if spec['mode'] != 'pdf-variations' or spec['task'] != task or Path(output).resolve() != (rd / selected['output_directory']).resolve():
                raise ValueError('PDF operation differs from exact approved task/output')
            return rd, selected
    raise ValueError('PDF execution requires an approved supervised science worker')


def run(task, base, output):
    rd, selected = _approved(task, output)
    path, c = _load(task, base)
    if c['max_seconds'] > selected['max_seconds']: raise ValueError('native budget exceeds supervisor')
    files = inputs(task, base)
    before = {str(p): _hash(p) for p in files}
    out = _regular(str(output), '.', directory=True)
    work = rd / 'work/pdf-variations' / out.name
    if work.exists() or any(q.is_symlink() for q in (work, *work.parents)):
        raise ValueError('fresh regular attempt workspace required')
    work.mkdir(parents=True)
    root, _ = _data(c['pdf_data'], path.parent)
    grid = work / 'pdf-data'
    grid.mkdir()
    for name in data_census(root)['files']:
        p = grid / name; p.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(root / name, p)
    if data_census(grid) != data_census(root): raise ValueError('copied PDF data differs')
    record = _pin(c['records'], path.parent)
    shutil.copyfile(record, work / 'parton-records.json')
    _write(out / 'native-input.json', {'grid_root': str(grid), 'records': str(work / 'parton-records.json'),
            'records_sha256': c['records']['sha256'], 'config_sha256': before[str(path)],
            'native_libraries': [{'load_path': str(Path(p['load_path']) if Path(p['load_path']).is_absolute() else path.parent / p['load_path']),
                                  'path': str(_library(p, path.parent)), 'sha256': p['sha256']}
                                 for p in c['runtime']['native_libraries']]})
    from ravel.physics.reinterpret_db import execute_native
    receipt = execute_native([str(_pin(c['runtime']['python'], path.parent)), '-I', '-B', str(Path(__file__).resolve()),
              '--native-worker', str(out / 'native-input.json'), '--out', str(out)], out, c)
    raw = _read(out / 'native-pdf-evaluations.json')
    native = _read(out / 'pdf-variations.json')
    expected = transport(_read(record), raw)
    if any(native.get(k) != v for k, v in expected.items()) or native.get('config_sha256') != before[str(path)] or native.get('records_sha256') != c['records']['sha256']:
        raise ValueError('native PDF output is not the exact independently transported input')
    if native.get('native_libraries') != [dict(path=str(_library(p, path.parent)), sha256=p['sha256']) for p in c['runtime']['native_libraries']]:
        raise ValueError('observed native library binding differs')
    from ravel.physics.model_tool_bridge import imported_sources
    imported_sources(native['imported_source_files'], before)
    if before != {str(p): _hash(p) for p in inputs(task, base)} or data_census(grid) != data_census(root) or _hash(work / 'parton-records.json') != c['records']['sha256']:
        raise ValueError('source/runtime/member membership changed during execution')
    result = {'status': 'passed', 'physics_validated': False, 'scope': SCOPE,
              'native_execution': receipt, 'output': 'pdf-variations.json', 'limitations': LIMITS}
    _write(out / 'result.json', result)
    return result


def observed_libraries(pins):
    # Darwin installed prerequisite only; no inferred loader binding from ldd/otool text.
    if sys.platform != 'darwin':
        raise ValueError('this first native capsule requires Darwin loader observation')
    import ctypes
    system = ctypes.CDLL(None)
    system._dyld_image_count.restype = ctypes.c_uint32
    system._dyld_get_image_name.argtypes = [ctypes.c_uint32]
    system._dyld_get_image_name.restype = ctypes.c_char_p
    loaded = {str(Path(system._dyld_get_image_name(i).decode()).resolve())
              for i in range(system._dyld_image_count())}
    rows = []
    for pin in pins:
        p = _library(pin, '.')
        if str(p) not in loaded: raise ValueError('declared native dependency was not actually loaded')
        rows.append({'path': str(p), 'sha256': _hash(p)})
    return rows


def bind_data_paths(lhapdf, root):
    # LHAPDF appends its install prefix unless the path string ends in ::.
    # setVerbosity initializes the singleton configuration, so bind FIRST.
    lhapdf.setPaths([str(root), '', ''])
    if lhapdf.paths() != [str(root)]:
        raise ValueError('ambient/fallback PDF data paths are forbidden')
    for name in data_census(root)['files']:
        selected = lhapdf.findFile(name)
        if selected is None or Path(selected).resolve() != (Path(root) / name).resolve():
            raise ValueError('native PDF lookup did not select copied bound data')
    lhapdf.setVerbosity(0)


def native_worker(request, out):
    if _hash(request['records']) != request['records_sha256']:
        raise ValueError('native record bytes differ')
    grid = _regular(request['grid_root'], '.', directory=True)
    os.environ['LHAPDF_DATA_PATH'] = str(grid) + '::'
    os.environ.pop('LHAPATH', None)
    import lhapdf
    libraries = observed_libraries(request['native_libraries'])
    bind_data_paths(lhapdf, grid)
    raw, result = evaluate(_read(request['records']), lhapdf)
    imported = {}
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            p = Path(filename).resolve()
            if p.is_file(): imported[str(p)] = _hash(p)
    result.update({'config_sha256': request['config_sha256'], 'records_sha256': request['records_sha256'],
                   'imported_source_files': [{'path': p, 'sha256': v} for p, v in sorted(imported.items())],
                   'python_version': sys.version, 'native_libraries': libraries})
    _write(Path(out) / 'native-pdf-evaluations.json', raw)
    _write(Path(out) / 'pdf-variations.json', result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-worker'); parser.add_argument('--out')
    args = parser.parse_args(argv)
    if not args.native_worker or not args.out:
        parser.error('only approved private native worker is supported; prepare with ravel science plan')
    native_worker(_read(args.native_worker), args.out)


if __name__ == '__main__':
    main()
