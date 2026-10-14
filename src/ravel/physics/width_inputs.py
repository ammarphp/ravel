"""Materialize pinned table sources selected by a supplied source package.

Published postfit samples remain references. Integer counts, joint auxiliary
laws, operative model cards and responses are never inferred from them.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
from pathlib import Path
import yaml

from ravel.physics import source_tables, mass_width_grid, supplied_contracts as contracts
from ravel.physics.ma5_saf import Capture, _json, _keys
from ravel.workflow import task_completion, science

SCOPE = 'supplied_source_width_input_materialization'


def require(ok, message):
    if not ok: raise ValueError(message)


def validate(task):
    contracts.fields(task, ('input', 'input_sha256'))
    _keys(task, ('input', 'input_sha256'), 'width-inputs task')
    require(type(task['input']) is str and task['input'], 'input pathname required')
    require(type(task['input_sha256']) is str and len(task['input_sha256']) == 64 and
            all(c in '0123456789abcdef' for c in task['input_sha256']), 'literal input SHA256 required')


def number(token): return Fraction(source_tables.number(token))
def exact(token): return str(number(token))


def table(raw, pin, mapping):
    """Retain the complete source table; mapping declares exact column metadata."""
    contracts.fields(mapping, ('axis_header', 'columns', 'role'))
    t = source_tables.read_table_snapshot(raw, pin)['payload']
    require(len(t['independent_variables']) == 1, 'one complete source axis required')
    axis = t['independent_variables'][0]
    require(axis['header'] == mapping['axis_header'] and set(axis) == {'header', 'values'},
            'source axis differs from supplied coordinate/units mapping')
    columns = t['dependent_variables']
    require(type(mapping['columns']) is list and len(columns) == len(mapping['columns']), 'complete ordered supplied column mapping required')
    for col, declared in zip(columns, mapping['columns']):
        _keys(declared, ('header', 'qualifiers'), 'source column mapping')
        require(col['header'] == declared['header'] and col.get('qualifiers', []) == declared['qualifiers'],
                'source column differs from supplied header/qualifier mapping')
        for value in col['values']:
            require(set(value) == {'value'} and number(value['value']) >= 0, 'finite nonnegative reference sample required')
    if mapping['role'] == 'region':
        windows = []
        for value in axis['values']:
            require(set(value) == {'low', 'high'} and 0 <= number(value['low']) < number(value['high']), 'complete source windows required')
            windows.append([exact(value['low']), exact(value['high'])])
        require(all(a[1] == b[0] for a, b in zip(windows, windows[1:])), 'complete contiguous source windows required')
        return t, windows
    require(mapping['role'] == 'limit', 'supported supplied reference table role required')
    masses = []
    for value in axis['values']:
        require(set(value) == {'value'} and number(value['value']) > 0, 'positive literal mass samples required')
        mass = number(value['value']); masses.append(int(mass) if mass.denominator == 1 else float(mass))
    require(all(a < b for a, b in zip(masses, masses[1:])), 'complete increasing source mass samples required')
    return t, masses


def parse_package(package, payloads, pins):
    """Interpret authenticated buffers using only the selected package mappings."""
    contracts.fields(package, ('sources', 'submission', 'tables', 'reference_metadata', 'analysis'))
    _keys(package, ('schema_version', 'sources', 'submission', 'tables', 'reference_metadata', 'analysis'), 'supplied source package')
    require(type(package['schema_version']) is int and package['schema_version'] == 1, 'source-package schema1 required')
    require(set(payloads) == set(pins) == set(package['sources']), 'complete supplied source census required')
    for name, raw in payloads.items():
        require(hashlib.sha256(raw).hexdigest() == pins[name]['sha256'] == package['sources'][name]['sha256'], 'supplied source digest differs: '+name)
    require(package['submission'] in payloads, 'supplied submission source key required')
    documents = [source_tables._node(n, set(), [0]) for n in yaml.compose_all(payloads[package['submission']].decode(), Loader=yaml.SafeLoader)]
    by_file = {}
    for document in documents:
        if 'data_file' in document:
            require(document['data_file'] not in by_file, 'unique submission/table mapping required')
            by_file[document['data_file']] = document
    mappings = package['tables']
    require(type(mappings) is list and 1 <= len(mappings) <= 64, 'bounded complete source table mappings required')
    files = [m['file'] for m in mappings]; ids = [m['id'] for m in mappings]
    require(len(set(files)) == len(files) and len(set(ids)) == len(ids) and set(files) == set(by_file) == set(payloads)-{package['submission']},
            'no unused, omitted or duplicate source table mapping permitted')
    regions = []; limits = {}; windows = None
    for mapping in mappings:
        _keys(mapping, ('id', 'file', 'role', 'axis_header', 'columns', 'quantity', 'unit', 'applicability'), 'source extraction mapping')
        filename = mapping['file']; t, nodes = table(payloads[filename], pins[filename], mapping)
        if mapping['role'] == 'region':
            require(windows is None or windows == nodes, 'all selected region windows must agree'); windows = nodes
            regions.append({'id': mapping['id'], 'source': pins[filename], 'metadata': by_file[filename], 'payload': t,
                'series_exact': {c['header']['name']: [exact(v['value']) for v in c['values']] for c in t['dependent_variables']},
                'statistical_role': 'published_postfit_plot_reference_only'})
        else:
            require(len(t['dependent_variables']) == 2, 'explicit ordered observed/expected reference pair required')
            quantity = mapping['quantity']; require(type(quantity) is str and quantity and quantity not in limits, 'unique explicit reference quantity required')
            for key in ('unit', 'applicability'): require(type(mapping[key]) is str and mapping[key], 'explicit reference '+key+' required')
            limits[quantity] = {'mass_GeV': nodes, 'source': pins[filename], 'metadata': by_file[filename], 'payload': t,
                'observed_exact': [exact(v['value']) for v in t['dependent_variables'][0]['values']],
                'expected_exact': [exact(v['value']) for v in t['dependent_variables'][1]['values']],
                'quantity': quantity, 'unit': mapping['unit'], 'applicability': mapping['applicability']}
    require(regions and limits, 'supplied regional and limit reference tables required')
    meta = deepcopy(package['reference_metadata'])
    _keys(meta, ('schema_version', 'kind', 'energy_tev', 'lumi_fb', 'uncertainty_law', 'source_discrepancies',
                'observations_reconstructed', 'coupling_to_width_or_rate_map', 'source_origin_scope'), 'reference metadata')
    require(meta['observations_reconstructed'] is False and meta['coupling_to_width_or_rate_map'] is None,
            'postfit references cannot invent observations or a coupling projection')
    require(meta['energy_tev'] == package['analysis']['energy_tev'] and meta['lumi_fb'] == package['analysis']['lumi_fb'], 'reference/analysis exposure differs')
    meta.update(windows_GeV=windows, regions=regions, limits=limits,
                region_bin_denominator=sum(len(r['payload']['independent_variables'][0]['values']) for r in regions),
                region_series_value_denominator=sum(len(c['values']) for r in regions for c in r['payload']['dependent_variables']),
                limit_value_denominator=sum(len(row['observed_exact'])+len(row['expected_exact']) for row in limits.values()))
    # Preserve the established reference-key order for migration identity.
    order=('schema_version','kind','energy_tev','lumi_fb','windows_GeV','regions','limits','region_bin_denominator',
           'region_series_value_denominator','limit_value_denominator','uncertainty_law','source_discrepancies',
           'observations_reconstructed','coupling_to_width_or_rate_map','source_origin_scope')
    return {key: meta[key] for key in order}


def _load(task, base):
    validate(task); c = mass_width_grid.InputCapture()
    path, raw = c.read(task['input'], base, task['input_sha256']); d = _json(raw)
    contracts.fields(d, ('source_package', 'axes', 'output'))
    _keys(d, ('schema_version', 'goal_binding', 'source_package', 'axes', 'point_inputs', 'regional_input',
             'native_runtime', 'native_fit', 'review_policy', 'child_seconds', 'assumptions', 'output'), 'supplied width producer')
    require(type(d['schema_version']) is int and d['schema_version'] == 2, 'explicit producer schema2 required')
    _keys(d['output'], ('references', 'recipe', 'specification', 'receipt', 'study'), 'source materialization output contract')
    for name in ('references', 'recipe', 'specification', 'receipt'): contracts.output_contract(d['output'][name])
    require(len({d['output'][k]['filename'] for k in ('references','recipe','specification','receipt')}) == 4, 'distinct materialization outputs required')
    mass_width_grid.output_spec(d['output']['study'])
    base = path.parent
    projection = task_completion.binding_projection(d['goal_binding'], base_dir=base)
    for pin in projection['input_pins']: mass_width_grid.read(c, pin, base, document=False)
    packagepath, package = mass_width_grid.read(c, d['source_package'], base)
    contracts.fields(package, ('sources', 'analysis', 'tables'))
    require(type(package['sources']) is dict and 2 <= len(package['sources']) <= 65, 'bounded complete supplied source inventory required')
    payloads, pins = {}, {}
    for name, pin in package['sources'].items():
        p, payloads[name] = mass_width_grid.read(c, pin, packagepath.parent, document=False)
        pins[name] = {'path': str(p), 'sha256': hashlib.sha256(payloads[name]).hexdigest(), 'size': len(payloads[name])}
    reference = parse_package(package, payloads, pins)
    from ravel.workflow.scan_orchestrator import enumerate_axes
    grid = enumerate_axes(d['axes'], maximum=128)
    require(type(d['point_inputs']) is list and len(d['point_inputs']) <= len(grid), 'bounded supplied attachment census required')
    cells = []
    for row in d['point_inputs']:
        _keys(row, ('coordinate', 'generation_request', 'response', 'missing'), 'width point attachment')
        require(row['coordinate'] in grid, 'foreign point attachment refused')
    for coordinate in grid:
        matches = [r for r in d['point_inputs'] if r['coordinate'] == coordinate]
        require(len(matches) <= 1, 'unique exact point attachment required')
        row = deepcopy(matches[0]) if matches else {'coordinate': coordinate, 'generation_request': None, 'response': None, 'missing': []}
        for key in ('generation_request', 'response'):
            if row[key] is not None:
                p, _ = mass_width_grid.read(c, row[key], base); row[key] = {**row[key], 'path': str(p)}
        cells.append(row)
    for key in ('regional_input', 'native_runtime', 'native_fit', 'review_policy'):
        if d[key] is not None:
            p, _ = mass_width_grid.read(c, d[key], base); d[key] = {**d[key], 'path': str(p)}
    analysis = deepcopy(package['analysis'])
    analysis['references'] = [{**pin, 'path': str(mass_width_grid.read(c, pin, packagepath.parent, document=False)[0])} for pin in analysis['references']]
    analysis['references'].extend(pins.values())
    recipe = {k: deepcopy(d[k]) for k in ('goal_binding', 'regional_input', 'native_runtime', 'native_fit', 'review_policy', 'child_seconds', 'assumptions')}
    recipe.update(schema_version=2, analysis=analysis, axes=d['axes'], cells=cells, output=d['output']['study'])
    require(d['review_policy'] is not None, 'independent ordinary review policy required for prepared width recipe')
    _, policy = mass_width_grid.read(c, d['review_policy'], base)
    science.validate({'schema_version': 2, 'mode': 'mass-width-grid', 'source': 'Supplied source-package width input preparation',
        'assumptions': d['assumptions'], 'max_seconds': 60, 'approval_mode': 'physicist', 'max_attempts': 1,
        'review_policy': policy, 'goal_binding': d['goal_binding'], 'task': {'input': str(path)}})
    _, _, law, _ = mass_width_grid._load_document(path, deepcopy(recipe), c)
    require(analysis['region_ids'] == [r['id'] for r in reference['regions']], 'source/analysis region populations differ')
    for pin in [d['regional_input'], *(r['response'] for r in cells)]:
        if pin is not None:
            _, doc = mass_width_grid.read(c, pin, base)
            require([[str(mass_width_grid.q(x)) for x in w] for w in doc['windows']] == reference['windows_GeV'],
                    'supplied law/response must retain every selected source window')
    return path, d, reference, recipe, c


def inputs(task, base):
    _, _, _, _, c = _load(task, base); c.finish()
    return [*c.files, *c.streams, Path(__file__).resolve(), Path(contracts.__file__).resolve(),
            Path(source_tables.__file__).resolve(), Path(mass_width_grid.__file__).resolve()]


def execution_seconds(task, base): return 60


def goal_inputs(spec, base):
    _, d, _, _, c = _load(spec['task'], base)
    require(spec.get('schema_version') == 2 and spec.get('goal_binding') == d['goal_binding'], 'original width question must remain bound on ordinary producer'); c.finish()


def run(task, base, output):
    path, d, reference, recipe, c = _load(task, base); out = Path(output).absolute()
    require('..' not in out.parts and not out.exists() and not any(p.is_symlink() for p in (out, *out.parents)), 'fresh canonical materialization destination required')
    require(not any(p.is_relative_to(out) for p in c.files), 'output may not contain original inputs')
    out.mkdir(parents=True); emitted = Capture()
    refpin = mass_width_grid._emit_result(out, reference, d['output']['references'], emitted)
    recipe['analysis']['references'].append(refpin)
    recipepin = mass_width_grid._emit_result(out, recipe, d['output']['recipe'], emitted)
    _, _, _, downstream = mass_width_grid._load({'input': recipepin['path']}, out)
    _, policy = mass_width_grid.read(c, d['review_policy'], path.parent)
    spec = {'schema_version': 2, 'mode': 'mass-width-grid', 'source': 'Complete supplied mass/width source package',
            'assumptions': d['assumptions'], 'max_seconds': 60, 'approval_mode': 'physicist', 'max_attempts': 1,
            'review_policy': policy, 'goal_binding': d['goal_binding'], 'task': {'input': recipepin['path']}}
    science.validate(spec); specpin = mass_width_grid._emit_result(out, spec, d['output']['specification'], emitted)
    result = {'schema_version': 1, 'kind': 'supplied-width-input-materialization', 'status': 'passed', 'status_scope': SCOPE,
              'goal_binding': d['goal_binding'], 'references': refpin, 'recipe': recipepin, 'specification': specpin,
              'mass_denominator': len(recipe['axes'][0]['values']), 'cell_denominator': len(recipe['cells']),
              'region_bin_denominator': reference['region_bin_denominator'], 'limit_value_denominator': reference['limit_value_denominator'],
              'source_discrepancies': reference['source_discrepancies'],
              'missing_scientific_inputs': [{'coordinate': row['coordinate'], 'obligations': [*recipe['analysis']['missing'], *row['missing'],
                  *([] if row['response'] else ['Width-specific complete response, card, exposure and uncertainty population absent.']),
                  *([] if row['generation_request'] else ['Source-matched operative generation request absent.']),
                  *([] if d['native_runtime'] is not None else ['Exact native likelihood runtime and fit prescription absent.'])]} for row in recipe['cells']],
              'input_pins': [{'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)} for p, (_, raw) in c.files.items()] +
                  [{'path': str(p), 'sha256': fact[1], 'size': fact[0][3]} for p, (fact, _) in c.streams.items()],
              'execution_authorized': False, 'generated_events': 0, 'fits': 0, 'physics_validated': False, 'original_task_complete': False,
              'next_command': ['ravel', 'plan', '--rundir', '<fresh-goal-child>', '--spec', specpin['path']]}
    c.finish(); downstream.finish(); emitted.finish()
    target = out/d['output']['receipt']['filename']
    try:
        mass_width_grid._emit_result(out, result, d['output']['receipt'], emitted)
        c.finish(); downstream.finish(); emitted.finish()
    except Exception:
        if target.exists(): target.rename(target.with_name('failed-'+target.name))
        raise
    return result


def write_report(result, out):
    return [('Complete width-input population', {key: result[key] for key in ('cell_denominator','region_bin_denominator','limit_value_denominator')},
        {'unit': 'source cells', 'normalization': 'Published postfit references only; no reconstructed law, response, coupling map or physics acceptance'})]
