"""Exact HS3 graph import and native RooFit likelihood evaluation.

Planning reads supplied JSON and source bytes only. Native ROOT runs exclusively
as a child of the existing scientific-study worker. No HistFactory-to-pyhf or
template reconstruction occurs in this adapter.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

MAX_GRAPH_BYTES = 16 * 1024 * 1024
SECTIONS = ('distributions', 'functions', 'data', 'domains', 'parameter_points', 'likelihoods', 'analyses')
MODIFIERS = {'normfactor', 'normsys', 'histosys', 'shapesys', 'shapefactor', 'staterror'}
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(label + ' requires exactly ' + ', '.join(sorted(expected)))


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite numeric ' + label + ' required')
    return float(value)


def unique(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError('duplicate JSON key: ' + k)
        result[k] = v
    return result


def document(raw):
    if not raw or len(raw) > MAX_GRAPH_BYTES:
        raise ValueError('nonempty bounded HS3 JSON required')
    def reject(s):
        raise ValueError('nonfinite JSON token: ' + s)
    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    except RecursionError as exc:
        raise ValueError('HS3 JSON nesting exceeds parser bound') from exc


def named(rows, label):
    if not isinstance(rows, list) or len(rows) > 50000:
        raise ValueError('bounded named sequence required: ' + label)
    result = {}
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get('name'), str) or not NAME.fullmatch(r['name']) or r['name'] in result:
            raise ValueError('unique native-valid name required: ' + label)
        result[r['name']] = r
    return result


def names(rows, known, label):
    if not isinstance(rows, list) or not rows or any(not isinstance(s, str) or s not in known for s in rows) or len(set(rows)) != len(rows):
        raise ValueError('complete unique resolved names required: ' + label)
    return rows


def axes(rows, label):
    result = named(rows, label)
    bins = 1
    for a in result.values():
        edges = a.get('edges')
        if edges is not None:
            if not isinstance(edges, list) or len(edges) < 2 or len(edges) > 100000:
                raise ValueError('bounded histogram edges required')
            values = [finite(v, 'axis edge') for v in edges]
            if any(b <= a for a, b in zip(values, values[1:])):
                raise ValueError('strictly increasing bin edges required')
            bins *= len(edges) - 1
        elif 'nbins' in a:
            if type(a['nbins']) is not int or not 0 < a['nbins'] <= 100000:
                raise ValueError('positive bounded nbins required')
            bins *= a['nbins']
        for k in ('min', 'max'):
            if k in a and a[k] is not None:
                finite(a[k], 'domain bound')
        if a.get('min') is not None and a.get('max') is not None and a['min'] >= a['max']:
            raise ValueError('ordered domain bounds required')
    if bins > 1000000:
        raise ValueError('histogram cell count exceeds contract')
    return result, bins


def binned(data, bins, label):
    if not isinstance(data, dict) or not isinstance(data.get('contents'), list) or len(data['contents']) != bins:
        raise ValueError('complete histogram contents required: ' + label)
    if any(finite(v, label) < 0 for v in data['contents']):
        raise ValueError('negative binned likelihood content: ' + label)
    if 'errors' in data:
        if not isinstance(data['errors'], list) or len(data['errors']) != bins or any(finite(v, 'histogram error') < 0 for v in data['errors']):
            raise ValueError('complete nonnegative histogram errors required')


def inspect_graph(raw, supported_types):
    """Check the selected source family without evaluating or rewriting it.

Distribution/function execution is delegated to the bound native importer.
Unsupported domains, datasets and modifiers refuse explicitly; every original
property (including ROOT_internal metadata) remains in the unchanged file.
"""
    d = document(raw)
    if not isinstance(d, dict) or set(d) - (set(SECTIONS) | {'metadata', 'misc'}):
        raise ValueError('unsupported HS3 top-level section')
    if not isinstance(d.get('metadata'), dict) or d['metadata'].get('hs3_version') != '0.2':
        raise ValueError('source family requires declared HS3 0.2')
    tables = {s: named(d.get(s, []), s) for s in SECTIONS}
    if any(not tables[s] for s in SECTIONS if s != 'functions'):
        raise ValueError('complete analyses/likelihoods/distributions/data/domains/points required')
    all_types = sorted({r.get('type') for s in ('distributions', 'functions') for r in tables[s].values() if isinstance(r.get('type'), str)})
    for s in ('distributions', 'functions'):
        for r in tables[s].values():
            if r.get('type') not in supported_types:
                raise ValueError('unsupported native importer type: ' + str(r.get('type')))
    if set(tables['distributions']) & set(tables['functions']):
        raise ValueError('ambiguous distribution/function identity')
    domains = {}
    for name, r in tables['domains'].items():
        if r.get('type') != 'product_domain':
            raise ValueError('unsupported native domain type')
        domains[name] = axes(r.get('axes'), name)[0]
    if 'default_domain' not in domains:
        raise ValueError('native default_domain required')
    points = {}
    for name, r in tables['parameter_points'].items():
        p = named(r.get('parameters'), 'point ' + name)
        for n, v in p.items():
            finite(v.get('value'), 'parameter value')
            if 'const' in v and type(v['const']) is not bool:
                raise ValueError('Boolean native constant flag required')
            a = domains['default_domain'].get(n, {})
            if a.get('min') is not None and v['value'] < a['min'] or a.get('max') is not None and v['value'] > a['max']:
                raise ValueError('parameter point outside source default domain')
        points[name] = p
    if 'default_values' not in points:
        raise ValueError('native default_values parameter point required')
    data_inventory = {}
    for n, r in tables['data'].items():
        if r.get('type') != 'binned':
            raise ValueError('unsupported dataset type: ' + str(r.get('type')))
        a, bins = axes(r.get('axes'), n)
        binned(r, bins, n)
        data_inventory[n] = {'axes': list(a), 'bins': bins, 'sum_weights': sum(r['contents'])}
    modifiers = {}
    for n, r in tables['distributions'].items():
        if r['type'] != 'histfactory_dist':
            continue
        a, bins = axes(r.get('axes'), n)
        samples = named(r.get('samples'), 'samples ' + n)
        if not samples:
            raise ValueError('nonempty HistFactory sample graph required')
        for sn, sample in samples.items():
            binned(sample.get('data'), bins, n + '/' + sn)
            if not isinstance(sample.get('modifiers'), list):
                raise ValueError('complete sample modifier sequence required')
            for mod in sample['modifiers']:
                if not isinstance(mod, dict) or mod.get('type') not in MODIFIERS:
                    raise ValueError('unsupported HistFactory modifier')
                modifiers[mod['type']] = modifiers.get(mod['type'], 0) + 1
                if 'constraint_name' in mod and mod['constraint_name'] not in tables['distributions']:
                    raise ValueError('dangling named modifier constraint')
                if mod['type'] == 'histosys':
                    for direction in ('lo', 'hi'):
                        binned(mod.get('data', {}).get(direction), bins, 'histosys ' + direction)
                if mod['type'] == 'normsys':
                    for direction in ('lo', 'hi'):
                        finite(mod.get('data', {}).get(direction), 'normsys ' + direction)
                if 'vals' in mod.get('data', {}):
                    vals = mod['data']['vals']
                    if not isinstance(vals, list) or len(vals) != bins or any(finite(v, 'modifier value') < 0 for v in vals):
                        raise ValueError('complete nonnegative modifier values required')
    if not isinstance(d.get('misc', {}), dict):
        raise ValueError('HS3 misc mapping required')
    internal = d.get('misc', {}).get('ROOT_internal', {})
    if not isinstance(internal, dict):
        raise ValueError('ROOT_internal map required')
    for section in ('ModelConfigs', 'combined_distributions', 'combined_datasets', 'attributes'):
        if section in internal and not isinstance(internal[section], dict):
            raise ValueError('unsupported ROOT_internal section form: ' + section)
    if any(not isinstance(v, dict) for v in internal.get('ModelConfigs', {}).values()):
        raise ValueError('ROOT ModelConfig metadata mapping required')
    for section in ('combined_distributions', 'combined_datasets'):
        for combined_name, combined in internal.get(section, {}).items():
            if not isinstance(combined_name, str) or not NAME.fullmatch(combined_name) or not isinstance(combined, dict):
                raise ValueError('named ROOT combined object required')
            labels, indices = combined.get('labels'), combined.get('indices')
            if (not isinstance(combined.get('index_cat'), str) or not NAME.fullmatch(combined['index_cat'])
                or not isinstance(labels, list) or not labels or not all(isinstance(s, str) and NAME.fullmatch(s) for s in labels)
                or len(set(labels)) != len(labels) or not isinstance(indices, list) or len(indices) != len(labels)
                or any(type(i) is not int for i in indices) or len(set(indices)) != len(indices)):
                raise ValueError('complete unique ROOT category labels/indices required')
            if section == 'combined_distributions':
                if len(names(combined.get('distributions'), tables['distributions'], 'all combined distributions')) != len(labels):
                    raise ValueError('combined PDF/category dimension mismatch')
            elif any(combined_name + '_' + label not in tables['data'] for label in labels):
                raise ValueError('unresolved original combined dataset component')
    bindings, shared = {}, {}
    for n, analysis in tables['analyses'].items():
        likelihood_name = analysis.get('likelihood')
        if likelihood_name not in tables['likelihoods']:
            raise ValueError('unresolved analysis likelihood')
        l = tables['likelihoods'][likelihood_name]
        dist = names(l.get('distributions'), tables['distributions'], 'likelihood distributions')
        data = names(l.get('data'), tables['data'], 'likelihood datasets')
        names(analysis.get('domains'), tables['domains'], 'analysis domains')
        poi = names(analysis.get('parameters_of_interest'), points['default_values'], 'analysis POI')
        aux = l.get('aux_distributions', [])
        if aux:
            names(aux, tables['distributions'], 'external constraints')
        mc = internal.get('ModelConfigs', {}).get(n, {})
        mcname = mc.get('mcName', n)
        pdfname = mc.get('pdfName', dist[0] if len(dist) == 1 else n + '_simPdf')
        if not NAME.fullmatch(mcname) or not NAME.fullmatch(pdfname):
            raise ValueError('invalid native ModelConfig/PDF name')
        combined = internal.get('combined_distributions', {}).get(pdfname)
        if len(dist) > 1:
            if not isinstance(combined, dict) or combined.get('distributions') != dist:
                raise ValueError('multi-channel execution requires exact original combined-distribution binding')
            labels, indices = combined.get('labels'), combined.get('indices')
            if not isinstance(labels, list) or len(labels) != len(dist) or len(set(labels)) != len(labels) or not all(isinstance(s, str) and NAME.fullmatch(s) for s in labels):
                raise ValueError('unique native combined channel labels required')
            if not isinstance(indices, list) or len(indices) != len(labels) or any(type(i) is not int for i in indices) or len(set(indices)) != len(indices):
                raise ValueError('unique native category indices required')
            matches = []
            for dn, dc in internal.get('combined_datasets', {}).items():
                if dc == {k: combined[k] for k in ('index_cat', 'labels', 'indices')} and [dn + '_' + label for label in labels] == data:
                    matches.append(dn)
            if len(matches) != 1:
                raise ValueError('ambiguous or missing source combined dataset')
            dataset = matches[0]
        elif len(data) == 1:
            dataset = data[0]
        else:
            raise ValueError('unsupported dataset/distribution combination')
        domain_axes = sorted({v for dn in analysis['domains'] for v in domains[dn]})
        domain_definitions = sorted(json.dumps(domains[dn], sort_keys=True, separators=(',', ':')) for dn in analysis['domains'])
        signature = (pdfname, dist, sorted(poi), domain_definitions, aux)
        if mcname in shared and shared[mcname] != signature:
            raise ValueError('shared ModelConfig name hides differing source model/domain definitions')
        shared[mcname] = signature
        bindings[n] = {'analysis': n, 'likelihood': likelihood_name, 'model_config': mcname,
                       'pdf': pdfname, 'dataset': dataset, 'data_components': data,
                       'distributions': dist, 'parameters_of_interest': sorted(poi),
                       'domain_parameters': domain_axes, 'domain_names': analysis['domains'], 'external_constraints': aux,
                       'data_observables': sorted({a['name'] for dn in data for a in tables['data'][dn]['axes']}),
                       'category': combined if combined else None}
    return {'document': d, 'tables': tables, 'domains': domains, 'points': points,
            'bindings': bindings, 'inventory': {'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw), 'hs3_metadata': d['metadata'], 'counts': {s: len(tables[s]) for s in SECTIONS},
            'types': all_types, 'modifiers': modifiers, 'datasets': data_inventory, 'bindings': bindings}}


def evaluation_points(graph, selection):
    keys(selection, {'analysis', 'parameter_point', 'points'}, 'HS3 evaluation selection')
    if selection['analysis'] not in graph['bindings'] or selection['parameter_point'] not in graph['points']:
        raise ValueError('source-resolved selected analysis and parameter point required')
    baseline = graph['points'][selection['parameter_point']]
    default = graph['points']['default_values']
    # A partial named snapshot is applied on top of the complete source default.
    baseline = {**default, **baseline}
    domain_variables = {n for domain in graph['domains'].values() for n in domain}
    rows = selection['points']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError('one to 256 explicit evaluation points required')
    seen, result = set(), []
    for row in rows:
        keys(row, {'id', 'parameters'}, 'evaluation point')
        if not isinstance(row['id'], str) or not NAME.fullmatch(row['id']) or row['id'] in seen or not isinstance(row['parameters'], dict):
            raise ValueError('unique native-valid point identifier and parameter overrides required')
        seen.add(row['id'])
        values = {n: v['value'] for n, v in baseline.items()}
        # ROOT configureVariable explicitly sets false when a selected source
        # snapshot omits const; do not inherit a prior snapshot's true flag.
        constants = {n: v.get('const', False) or n not in domain_variables for n, v in baseline.items()}
        for n, v in row['parameters'].items():
            finite(v, 'override')
            if n not in values or constants[n]:
                raise ValueError('override must name a nonconstant original parameter')
            if n in graph['bindings'][selection['analysis']]['data_observables']:
                raise ValueError('original data covariates cannot be changed by a parameter override')
            values[n] = v
        # Check the COMPLETE merged point. Defaults and named snapshots can
        # violate an analysis domain even when no parameter override is supplied.
        for dn in dict.fromkeys(['default_domain', *graph['bindings'][selection['analysis']]['domain_names']]):
            for n, v in values.items():
                a = graph['domains'][dn].get(n, {})
                if a.get('min') is not None and v < a['min'] or a.get('max') is not None and v > a['max']:
                    raise ValueError('effective point outside source domain' if dn == 'default_domain' else 'effective point outside selected analysis domain')
        result.append({'id': row['id'], 'values': values, 'constants': constants, 'overrides': row['parameters']})
    return result


def source_types(paths):
    required = {'JSONFactories_HistFactory.cxx', 'JSONFactories_RooFitCore.cxx', 'RooFitHS3_wsfactoryexpressions.cxx',
                'RooJSONFactoryWSTool.cxx', 'Domains.cxx', 'ModelConfig.cxx'}
    byname = {Path(p).name: Path(p) for p in paths}
    if not required <= set(byname) or len(byname) != len(paths):
        raise ValueError('unambiguous complete selected native importer/ModelConfig source evidence required')
    result = set()
    for name in ('JSONFactories_HistFactory.cxx', 'JSONFactories_RooFitCore.cxx'):
        result.update(re.findall(r'registerImporter(?:<[^\n;]*?>)?\s*\(\s*"([^"]+)"', byname[name].read_text()))
    raw = byname['RooFitHS3_wsfactoryexpressions.cxx'].read_text()
    match = re.search(r'R"\((\{.*\})\)"', raw, re.DOTALL)
    if match is None:
        raise ValueError('source factory-expression registry not found')
    result.update(document(match.group(1).encode()))
    if not result:
        raise ValueError('empty source importer registry')
    return sorted(result)


def derivative_kernel():
    """Load the adjacent admitted pure kernel, including in the staged contract."""
    path = Path(__file__).with_name('native_likelihood_derivatives.py')
    spec = importlib.util.spec_from_file_location('ravel_hs3_derivative_kernel', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured_points(configuration, graph, configuration_directory=None):
    """Use the existing point evaluator; opt-in derivatives select one anchor.

    Every generated assignment is re-admitted by the original source snapshot
    and selected domains. Roles here describe source coordinates; the native
    ModelConfig must separately confirm each axis is a POI/nuisance rather than
    an observable, implicit global or unrelated parameter.
    """
    anchor_rows = evaluation_points(graph, configuration['selection'])
    if 'derivatives' not in configuration:
        return anchor_rows, None
    choice = configuration['derivatives']
    keys(choice, {'axes', 'max_points'}, 'HS3 derivative selection')
    if len(anchor_rows) != 1:
        raise ValueError('opt-in derivatives require exactly one explicit source anchor')
    anchor = anchor_rows[0]
    binding = graph['bindings'][configuration['selection']['analysis']]
    parameters = []
    selected_domains = list(dict.fromkeys(['default_domain', *binding['domain_names']]))
    for name, value in anchor['values'].items():
        lows, highs = [], []
        for domain in selected_domains:
            axis = graph['domains'][domain].get(name, {})
            edges = axis.get('edges')
            lo, hi = (edges[0], edges[-1]) if edges else (axis.get('min'), axis.get('max'))
            if lo is not None: lows.append(lo)
            if hi is not None: highs.append(hi)
        bounds = {'min': max(lows) if lows else None, 'max': min(highs) if highs else None}
        role = ('observable' if name in binding['data_observables'] else
                'fixed' if anchor['constants'][name] else
                'poi' if name in binding['parameters_of_interest'] else 'nuisance')
        parameters.append({'name': name, 'value': value, 'constant': anchor['constants'][name],
                           'kind': 'continuous', 'role': role, 'bounds': bounds})
    runtime = json.loads(json.dumps(configuration['runtime']))
    base = Path(configuration_directory) if configuration_directory is not None else None
    for pin in [runtime['python'], *runtime['artifacts'], *runtime['importer_sources'],
                *runtime['modules'].values(), *runtime['loaded_libraries'].values()]:
        path = Path(pin['path'])
        if not path.is_absolute():
            if base is None: raise ValueError('resolved runtime paths required in staged derivative request')
            path = base / path
        pin['path'] = str(path.resolve())
    canonical = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    definition = {'binding': binding, 'selection_anchor': anchor,
                  'nll': configuration['nll'], 'parameters': parameters,
                  'contract_sha256': digest(__file__),
                  'worker_sha256': digest(Path(__file__).with_name('hs3_native.py') if Path(__file__).with_name('hs3_native.py').exists() else Path(__file__).with_name('native_worker.py')),
                  'kernel_sha256': digest(Path(__file__).with_name('native_likelihood_derivatives.py')),
                  'nll_convention': 'NLL_not_minus_two_log_likelihood'}
    request = {'schema_version': 1, 'kind': 'native-likelihood-stencil',
               'identity': {'model_sha256': graph['inventory']['sha256'], 'runtime_binding_sha256': canonical(runtime),
                            'evaluation_definition_sha256': canonical(definition)},
               'parameters': parameters, 'axes': choice['axes'], 'max_points': choice['max_points']}
    kernel = derivative_kernel()
    plan = kernel.compile_stencil(request)
    selection = dict(configuration['selection'])
    selection['points'] = kernel.native_point_overrides(plan, anchor['overrides'])
    points = evaluation_points(graph, selection)
    expected = [{p['name']: {'value': p['value'], 'constant': p['constant']} for p in row['parameters']} for row in plan['points']]
    actual = [{n: {'value': v, 'constant': row['constants'][n]} for n, v in row['values'].items()} for row in points]
    if actual != expected:
        raise ValueError('derivative assignments differ from complete source-resolved points')
    return points, plan


def derivative_observations(native, plan):
    """Called only AFTER validate_native; raw complete native rows stay retained."""
    kernel = derivative_kernel()
    kernel.validate_plan(plan)
    rows = []
    for row in native['evaluations']:
        assigned = row['source_assignments']
        if set(assigned) != set(plan['parameter_order']):
            raise ValueError('complete native source coordinate denominator differs')
        rows.append({'id': row['id'], 'parameters': [{'name': n, **assigned[n]} for n in plan['parameter_order']], 'nll': row['nll']})
    result = {'schema_version': 1, 'kind': 'native-likelihood-stencil-observations',
              'identity': plan['identity'], 'plan_sha256': plan['plan_sha256'], 'rows': rows}
    kernel.reduce_observations(plan, result)
    return result


def validate(task):
    keys(task, {'input'}, 'hs3-likelihood task')
    if not isinstance(task['input'], str) or not task['input']:
        raise ValueError('HS3 configuration input required')


def configuration(task, base, *, _session=None):
    from ravel.workflow.science import regular
    from ravel.workflow.state_io import read_json
    validate(task)
    cp = regular(task['input'], base, _session=_session)
    c = _session.read_document(cp) if _session else read_json(cp)
    expected = {'schema_version', 'source', 'model', 'provenance', 'runtime', 'selection', 'nll', 'max_seconds'}
    keys(c, expected | ({'derivatives'} if isinstance(c, dict) and 'derivatives' in c else set()), 'HS3 configuration')
    if type(c['schema_version']) is not int or c['schema_version'] != 1 or not isinstance(c['source'], str) or not c['source'].strip() or type(c['max_seconds']) is not int or not 1 <= c['max_seconds'] <= 86400:
        raise ValueError('HS3 source, schema and bounded complete execution required')
    def pin(v, executable=False):
        keys(v, {'path', 'sha256'}, 'HS3 input pin')
        if not isinstance(v['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', v['sha256']):
            raise ValueError('lowercase source SHA256 required')
        p = regular(v['path'], cp.parent, _session=_session)
        if (_session.hash_file(p) if _session else digest(p)) != v['sha256'] or executable and not os.access(p, os.X_OK):
            raise ValueError('changed HS3 source/runtime pin or non-executable Python')
        return p
    model = pin(c['model'])
    if not isinstance(c['provenance'], list) or not c['provenance']:
        raise ValueError('source attribution/evidence pins required')
    provenance = [pin(v) for v in c['provenance']]
    r = c['runtime']
    keys(r, {'python', 'artifacts', 'importer_sources', 'modules', 'loaded_libraries', 'environment', 'root_version', 'importer_config'}, 'HS3 runtime')
    python = pin(r['python'], True)
    if not isinstance(r['artifacts'], list) or not r['artifacts'] or not isinstance(r['importer_sources'], list) or not r['importer_sources']:
        raise ValueError('native runtime and primary importer source closure required')
    artifacts = [pin(v) for v in r['artifacts']]
    sources = [pin(v) for v in r['importer_sources']]
    if len(set(artifacts)) != len(artifacts) or len(set(sources)) != len(sources):
        raise ValueError('duplicate runtime/source fact')
    for category in ('modules', 'loaded_libraries'):
        if not isinstance(r[category], dict) or not r[category]:
            raise ValueError('exact native module and loaded image binding required')
        for name, v in r[category].items():
            if not isinstance(name, str) or not name or pin(v) not in artifacts:
                raise ValueError('every native origin/image must be an approved runtime artifact')
    if set(r['modules']) != {'ROOT', 'cppyy'}:
        raise ValueError('exact ROOT/cppyy module origins required')
    if not {'libCore', 'libRooFitCore', 'libRooFitHS3', 'libHistFactory'} <= set(r['loaded_libraries']):
        raise ValueError('complete core/likelihood/HS3/HistFactory loaded image expectations required')
    if not isinstance(r['environment'], dict) or not r['environment'] or any(not isinstance(k, str) or not isinstance(v, str) or '\0' in k + v or '=' in k for k, v in r['environment'].items()):
        raise ValueError('closed explicit native launch environment required')
    if r['environment'].get('PYTHONDONTWRITEBYTECODE') != '1' or r['environment'].get('PYTHONNOUSERSITE') != '1':
        raise ValueError('native source imports must disable bytecode writes and user site')
    if r['environment'].get('PYTHONCOERCECLOCALE') != '0' or not r['environment'].get('LC_CTYPE'):
        raise ValueError('explicit native locale without silent Python locale coercion required')
    if not isinstance(r['root_version'], str) or not re.fullmatch(r'\d+\.\d+\.\d+', r['root_version']):
        raise ValueError('literal native ROOT version required')
    keys(r['importer_config'], {'allowExportInvalidNames', 'allowSanitizeNames', 'importNoDomainParametersAsRooConstVars'}, 'native importer config')
    if r['importer_config'] != {'allowExportInvalidNames': False, 'allowSanitizeNames': False, 'importNoDomainParametersAsRooConstVars': True}:
        raise ValueError('exact unsanitized/native no-domain constant import semantics required')
    keys(c['nll'], {'extended', 'offset', 'eval_backend', 'num_cpu', 'constraints', 'global_observables_source'}, 'native NLL options')
    if c['nll'] != {'extended': True, 'offset': False, 'eval_backend': 'legacy', 'num_cpu': 1, 'constraints': 'all_pdf_parameters', 'global_observables_source': 'model'}:
        raise ValueError('complete source-model constraints/global observables and fixed native evaluation options required')
    graph = inspect_graph(model.read_bytes(), source_types(sources))
    evaluated, stencil = configured_points(c, graph, cp.parent)
    files = list(dict.fromkeys([cp, model, *provenance, python, *artifacts, *sources,
                               Path(__file__).resolve(), Path(__file__).with_name('hs3_native.py').resolve()]))
    if stencil is not None:
        files.append(Path(__file__).with_name('native_likelihood_derivatives.py').resolve())
    return c, cp, model, python, graph, evaluated, files


def inputs(task, base, *, _session=None):
    return configuration(task, base, _session=_session)[-1]


def execution_seconds(task, base, *, _session=None):
    return configuration(task, base, _session=_session)[0]['max_seconds']


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def validate_native(native, request):
    from ravel.physics.hs3_native import HELPER
    runtime = request['configuration']['runtime']
    if (native.get('status') != 'passed' or native.get('model_sha256') != request['model_sha256']
        or native.get('binding') != request['binding'] or native.get('root_version') != runtime['root_version']
        or native.get('source_export_metadata') != request['inventory']['hs3_metadata']
        or native.get('nll_options') != request['configuration']['nll']
        or native.get('native_helper_sha256') != hashlib.sha256(HELPER.encode()).hexdigest()):
        raise ValueError('native HS3 delivery identity differs from approved source/selection/runtime')
    for phase in ('runtime_before', 'runtime_after'):
        observed = native.get(phase, {})
        if (observed.get('root_version') != runtime['root_version'] or observed.get('modules') != runtime['modules']
            or observed.get('required_loaded_images') != runtime['loaded_libraries']
            or observed.get('environment') != runtime['environment'] or observed.get('cwd') != request['output']
            or observed.get('python') != runtime['python']):
            raise ValueError('native phase identity/loaded image/environment differs from exact original launch')
    rows = native.get('evaluations')
    if not isinstance(rows, list) or len(rows) != len(request['points']):
        raise ValueError('complete native evaluation denominator required')
    for row, point in zip(rows, request['points']):
        expected = {n: {'value': v, 'constant': point['constants'][n]} for n, v in point['values'].items()}
        if row.get('id') != point['id'] or row.get('source_overrides') != point['overrides'] or row.get('source_assignments') != expected:
            raise ValueError('native evaluated point differs from source values/flags/order')
        finite(row.get('nll'), 'native NLL')
        if row.get('delta_nll_from_first') != row['nll'] - rows[0]['nll']:
            raise ValueError('native NLL difference changed')
    plan = request.get('derivative_plan')
    if ('derivatives' in request['configuration']) != (plan is not None):
        raise ValueError('explicit derivative configuration/plan presence differs')
    if plan is not None:
        derivative_kernel().validate_plan(plan)
        if native.get('derivative_plan_sha256') != plan['plan_sha256']:
            raise ValueError('actual derivative plan identity differs')
        mc = native['workspace_inventory']['model_config']
        pois, nuisances = set(mc['parameters_of_interest']), set(mc['nuisance_parameters'])
        forbidden = set(mc['global_observables']) | set(mc['conditional_observables']) | set(mc['observables'])
        for axis in plan['axis_order']:
            if axis not in pois | nuisances or axis in forbidden:
                raise ValueError('actual ModelConfig derivative axis role differs: ' + axis)
        derivative_observations(native, plan)


def run(task, base, out):
    """Launch only from the common approved worker, retaining unsuccessful work."""
    out = Path(out)
    if out.is_symlink() or any(p.is_symlink() for p in out.parents):
        raise ValueError('ordinary owned output directory required')
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    try:
        c, cp, model, python, graph, points, files = configuration(task, base)
        _, stencil = configured_points(c, graph, cp.parent)
        original = {str(p): digest(p) for p in files}
        for p, name in ((model, 'original-hs3.json'), (Path(__file__), 'hs3_contract.py'), (Path(__file__).with_name('hs3_native.py'), 'native_worker.py')):
            target = out / name
            if target.exists():
                raise ValueError('fresh native HS3 output required')
            shutil.copyfile(p, target)
        if stencil is not None:
            shutil.copyfile(Path(__file__).with_name('native_likelihood_derivatives.py'), out / 'native_likelihood_derivatives.py')
            _write(out / 'derivative-plan.json', stencil)
        req = {'configuration': c, 'model': str((out / 'original-hs3.json').absolute()),
               'model_sha256': digest(model), 'contract_sha256': digest(out / 'hs3_contract.py'),
               'worker_sha256': digest(out / 'native_worker.py'), 'points': points,
               'inventory': graph['inventory'], 'supported_types': source_types([Path(p['path']) if Path(p['path']).is_absolute() else cp.parent / p['path'] for p in c['runtime']['importer_sources']]),
               'binding': graph['bindings'][c['selection']['analysis']], 'output': str(out.absolute())}
        if stencil is not None:
            req['derivative_plan'] = stencil
            req['derivative_kernel_sha256'] = digest(out / 'native_likelihood_derivatives.py')
        # Resolve every native pin to its actual approved ordinary path.
        for key in ('python',):
            req['configuration']['runtime'][key]['path'] = str(python)
        for key in ('artifacts', 'importer_sources'):
            for v in req['configuration']['runtime'][key]:
                v['path'] = str((cp.parent / v['path']).resolve())
        for key in ('modules', 'loaded_libraries'):
            for v in req['configuration']['runtime'][key].values():
                v['path'] = str((cp.parent / v['path']).resolve())
        _write(out / 'native-request.json', req)
        argv = [str(python), '-B', str((out / 'native_worker.py').absolute()), str((out / 'native-request.json').absolute())]
        _write(out / 'launch.json', {'argv': argv, 'cwd': str(out.absolute()), 'environment': c['runtime']['environment'], 'input_sha256': original, 'group_owner': 'existing scientific-study supervisor'})
        remaining = c['max_seconds'] - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError('HS3 complete deadline spent in admission')
        # One combined byte stream, with an explicit launch prefix; no invented
        # stderr content and no empty scientific file exception is needed.
        with (out / 'native-combined.log').open('xb') as log:
            log.write((json.dumps({'kind': 'launch_prefix', 'argv': argv}) + '\n').encode()); log.flush()
            proc = subprocess.run(argv, cwd=out, env=c['runtime']['environment'], stdout=log, stderr=subprocess.STDOUT, timeout=remaining, check=False)
        if proc.returncode != 0:
            raise ValueError('native HS3 import/evaluation returned ' + str(proc.returncode))
        native = document((out / 'native-evaluation.json').read_bytes())
        if stencil is not None and digest(out / 'native_likelihood_derivatives.py') != req['derivative_kernel_sha256']:
            raise ValueError('staged derivative kernel drift during evaluation')
        validate_native(native, req)
        derivatives = None
        if stencil is not None:
            observations = derivative_observations(native, stencil)
            _write(out / 'derivative-observations.json', observations)
            derivatives = derivative_kernel().reduce_observations(stencil, observations)
            _write(out / 'derivative-estimates.json', derivatives)
        for name in ('native-roundtrip-hs3.json', 'imported-workspace.root', 'imported-workspace-inventory.json'):
            if not (out / name).is_file() or (out / name).is_symlink() or not (out / name).stat().st_size:
                raise ValueError('complete retained original native workspace delivery required: ' + name)
        if any(digest(p) != sha for p, sha in original.items()):
            raise ValueError('HS3 source/runtime drift during native evaluation')
        if time.monotonic() - started > c['max_seconds']:
            raise ValueError('HS3 complete execution deadline spent before final delivery')
        result = {'status': 'passed', 'physics_validated': False, 'scope': 'Exact original HS3 native import and fixed-point RooFit NLL delivery',
                  'source': c['source'], 'source_inventory': graph['inventory'], 'native': native,
                  'runtime_qualified_for_this_model': True, 'input_sha256': original,
                  'limitations': ['Source-export ROOT metadata and observed importing ROOT version are distinct.',
                  'No optimizer, profile, CLs, coverage, signal-template validity or paper reproduction is claimed.',
                  'Native evaluation retains importer-specific interpolation and constraints; cross-version fidelity requires its own independent qualification.']}
        if derivatives is not None:
            result['derivatives'] = derivatives
    except (ValueError, OSError, KeyError, TypeError, ImportError, RuntimeError, subprocess.SubprocessError) as exc:
        result = {'status': 'failed', 'physics_validated': False, 'runtime_qualified_for_this_model': False,
                  'scope': 'Retained unsuccessful native HS3 attempt', 'error': {'type': type(exc).__name__, 'message': str(exc)},
                  'limitations': ['Failure is not a likelihood value or an authorized retry. The common supervisor owns process-group recovery.']}
    result['retained_artifacts'] = [{'path': p.relative_to(out).as_posix(), 'bytes': p.stat().st_size, 'sha256': digest(p)} for p in sorted(out.rglob('*')) if p.is_file() and not p.is_symlink()]
    _write(out / 'hs3-likelihood.json', result)
    return result
