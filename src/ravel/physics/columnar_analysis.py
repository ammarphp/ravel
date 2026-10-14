"""Columnar reconstructed-event analysis as a planned, approved scientific study.

Science mode ``columnar-analysis`` applies a declarative recipe (objects, overlap removal,
isolation, efficiency maps, observables, regions, histograms and systematic variations)
to Delphes ROOT files, flat or PHYSLITE-like ntuples described by a format descriptor,
or LHE files, and delivers ``binned_values`` histograms that ``ravel fill-template``
reads, a cutflow and full provenance. The task is::

    {"recipe": "recipe.json",
     "format": "delphes" | "descriptor.json",
     "inputs": ["sample-1.root", "sample-2.root"],
     "normalization": {...} | "normalization.json",
     "chunk_size": 100000,
     "detector_card": "delphes_card.tcl"}

``normalization`` is ``{"mode": "cross-section", "cross_section_pb", "cross_section_source",
"luminosity_ifb", "luminosity_source", "sum_of_weights": "all-input-events" | number}``,
``{"mode": "event-weights-in-pb", ...}`` or ``{"mode": "none"}``; the cross section may be
``{"lhe_init": true}``, ``{"production_receipt": path, "pointer": "/json/pointer"}``,
``{"production_receipt": path}`` (the receipt's ``sigma`` block; an embedded normalization
ledger supplies sigma x k as the cross section and prod(BR) x filter as the factor),
``{"normalization_ledger": path}`` or ``{"cross_section_registry": request}``.
``detector_card`` (optional) is the Delphes card that made the events; planning checks each
efficiency map's declared semantics against the card's efficiency modules.
``analysis_spec`` (optional) is a typed analysis specification
(``ravel.workflow.analysis_spec``): planning checks every source span, refuses while a
yield- or shape-moving ambiguity is open, requires every recipe node to name the
specification items it implements, and lists the defaulted assumptions for CHECK-IN 1.

Planning compiles the recipe, loads every efficiency map and checks every declared branch
against each input file, so a mistake stops the study before approval. The worker runs the
files as partitions of one sample, merges them and writes the outputs under
``columnar-analysis/``. ``ravel columnar-analysis`` inspects files and recipes and exposes
``analyse``, ``merge`` and ``finalize`` as separate steps for partitioned execution.
"""
import argparse
import json
import math
from pathlib import Path

SCOPE = 'declared_columnar_selection_delivery'
OUTPUT = 'columnar-analysis'
TASK_KEYS = {'recipe', 'format', 'inputs', 'normalization'}
OPTIONAL = {'chunk_size', 'description', 'detector_card', 'analysis_spec'}
MAX_INPUTS = 10_000

def _load_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'regular file required: {path}')
    return json.loads(path.read_text())


def validate(task):
    """Structural check (no files read)."""
    if not isinstance(task, dict) or not TASK_KEYS <= set(task) or set(task) - TASK_KEYS - OPTIONAL:
        raise ValueError(f'columnar-analysis task needs {sorted(TASK_KEYS)} and may add {sorted(OPTIONAL)}')
    for key in ('recipe', 'format'):
        if not isinstance(task[key], str) or not task[key].strip():
            raise ValueError(f'{key} must be a path (or a built-in format name)')
    dataset_input = isinstance(task['inputs'], dict) and set(task['inputs']) == {'dataset'}
    if not dataset_input and (not isinstance(task['inputs'], list) or not 1 <= len(task['inputs']) <= MAX_INPUTS \
            or any(not isinstance(p, str) or not p.strip() for p in task['inputs'])):
        raise ValueError('inputs must be a nonempty list of event file paths')
    if not dataset_input and len(set(task['inputs'])) != len(task['inputs']):
        raise ValueError('an input file is listed twice')
    for key in ('detector_card', 'analysis_spec'):
        if key in task and (not isinstance(task[key], str) or not task[key].strip()):
            raise ValueError(f'{key} must be a path')
    if not isinstance(task['normalization'], (dict, str)):
        raise ValueError('normalization must be an object or a path to one')
    chunk = task.get('chunk_size', 100_000)
    if type(chunk) is not int or not 1 <= chunk <= 10_000_000:
        raise ValueError('chunk_size must be an integer from 1 to 10000000')


def _resolve(base, value):
    if isinstance(value, str) and value.startswith('root://'):
        return value
    path = Path(value)
    return path if path.is_absolute() else Path(base) / path


def compile_task(task, base):
    """Compile the recipe against its descriptor; returns (plan, normalization, files)."""
    from ravel.physics.columnar import formats
    from ravel.physics.columnar.recipe import compile_recipe
    validate(task)
    recipe_path = _resolve(base, task['recipe'])
    recipe = _load_json(recipe_path)
    descriptor = formats.load_descriptor(task['format'], base)
    card = _resolve(base, task['detector_card']) if 'detector_card' in task else None
    plan = compile_recipe(recipe, descriptor, recipe_path.parent, detector_card=card)
    normalization = task['normalization']
    normalization_path = None
    if isinstance(normalization, str):
        normalization_path = _resolve(base, normalization)
        normalization = _load_json(normalization_path)
    files = [recipe_path] + ([card] if card is not None else [])
    plan.spec_report = None
    if 'analysis_spec' in task:
        plan.spec_report = specification_report(_resolve(base, task['analysis_spec']), plan)
        files.append(_resolve(base, task['analysis_spec']))
        files += [Path(s['path']) for s in plan.spec_report['sources']]
    if descriptor.origin.get('kind') == 'file':
        files.append(Path(descriptor.origin['path']))
    files += [Path(m.provenance['path']) for m in plan.maps.values()]
    if normalization_path is not None:
        files.append(normalization_path)
    xs = normalization.get('cross_section_pb') if isinstance(normalization, dict) else None
    if isinstance(xs, dict):
        for key in ('production_receipt', 'normalization_ledger'):
            if key in xs:
                files.append(_resolve(base, xs[key]))
        if 'cross_section_result' in xs:
            files.append(_resolve(base, xs['cross_section_result']['path']))
    plan.dataset = None
    if isinstance(task['inputs'], dict):
        from .yield_hub import load_dataset, member_path
        plan.dataset, dataset_files = load_dataset(task['inputs']['dataset'], base)
        files += [_resolve(base, str(p)) for p in dataset_files]
        if normalization != {'mode': 'dataset'}:
            raise ValueError('dataset inputs require mode dataset; original per-sample normalization cannot be overridden')
        if any(m['tree'] != plan.descriptor.doc['tree'] for s in plan.dataset['samples'] for m in s['members']):
            raise ValueError('dataset member tree differs from the columnar format descriptor')
        events = [member_path(m) for s in plan.dataset['samples'] for m in s['members']]
    else:
        events = [_resolve(base, p) for p in task['inputs']]
        if any(isinstance(p, str) and p.startswith('root://') for p in events):
            raise ValueError('remote ROOT inputs require an original pinned dataset membership')
        if normalization == {'mode': 'dataset'}:
            raise ValueError('mode dataset requires pinned dataset inputs')
    return plan, normalization, files, events


def specification_report(spec_path, plan):
    """Spans, ambiguities and recipe coverage of a typed analysis specification."""
    from ravel.workflow import analysis_spec, spec_ambiguity
    spec = analysis_spec.load(spec_path, Path(spec_path).parent)
    return {'specification': spec['pin'], 'sources': spec['sources'],
            'ambiguities': spec_ambiguity.find(spec), 'coverage': analysis_spec.coverage(spec, plan)}


def inputs(task, base):
    """Every file the study reads; each event file is checked against the descriptor."""
    plan, normalization, files, events = compile_task(task, base)
    report = plan.spec_report
    if report is not None:
        blocking = report['ambiguities']['blocking']
        if blocking:
            raise ValueError('the analysis specification has open ambiguities that move yields or shapes: '
                             + '; '.join(f'{b["item"]} {b["category"]} ({b["reason"]})' for b in blocking))
        cov = report['coverage']
        if not cov['passed']:
            raise ValueError('the recipe does not implement the specification: ' + json.dumps(
                {k: cov[k] for k in ('nodes_without_spec_item', 'unknown_spec_items', 'unimplemented_spec_items',
                                     'normalization_basis_errors') if cov[k]}))
    for path in events:
        remote = isinstance(path, str) and path.startswith('root://')
        if not remote and (path.is_symlink() or not path.is_file()):
            raise ValueError(f'event file must be a regular file: {path}')
        plan.descriptor.check_file(path, variations=plan.variations, collections=plan.source_collections,
                                   event_fields=plan.event_fields)
    if not isinstance(normalization, dict) or normalization.get('mode') not in ('cross-section', 'event-weights-in-pb', 'none', 'dataset'):
        raise ValueError('normalization mode must be cross-section, event-weights-in-pb or none')
    return [*files, *[p for p in events if not isinstance(p, str) or not p.startswith('root://')]]


def run(task, base, destination):
    from ravel.physics.columnar import engine
    plan, normalization, _, events = compile_task(task, base)
    chunk = task.get('chunk_size', 100_000)
    if plan.dataset is not None:
        from .yield_hub import member_path, dataset_normalization
        samples = []
        for index, sample in enumerate(plan.dataset['samples']):
            paths = [member_path(m) for m in sample['members']]
            partials = [engine.analyse({'inputs': [{'path': str(path), 'file_index': i,
                         'expected_entries': member['entries'], 'source_checksum': member['checksum']}],
                         'chunk_size': chunk}, plan) for i, (path, member) in enumerate(zip(paths, sample['members']))]
            summary = engine.finalize(engine.merge(partials), plan, dataset_normalization(sample),
                                      out_dir=Path(destination) / OUTPUT / f'sample-{index}', input_files=paths, base=base)
            samples.append({'sample': sample['id'], 'dsid': sample['dsid'], 'normalization': summary['normalization'],
                            'histograms': summary['histograms'], 'events': summary['events'],
                            'check_results': summary['check_results'],
                            'files': [{**f, 'path': f'{OUTPUT}/sample-{index}/{f["path"]}'} for f in summary['files']]})
        return {'status': 'passed', 'kind': 'columnar-analysis', 'status_scope': SCOPE, 'physics_validated': False,
                'samples': samples, 'files': [f for s in samples for f in s['files']],
                'check_results': [{**row, 'sample': s['sample']} for s in samples for row in s['check_results']],
                'limitations': ['Each MC sample uses its pinned full original denominator. Remote checksum identity is declared; no byte-level remote checksum verification is inferred.']}
    partials = [engine.analyse({'inputs': [{'path': str(p), 'file_index': i}], 'chunk_size': chunk}, plan)
                for i, p in enumerate(events)]
    merged = engine.merge(partials)
    out = Path(destination) / OUTPUT
    summary = engine.finalize(merged, plan, normalization, out_dir=out, input_files=events, base=base)
    final = {}
    for variation, regions in summary['cutflows'].items():
        if variation != 'nominal':
            continue
        for region in regions:
            last = region['cuts'][-1]
            final[region['name']] = {'raw': last['raw'], 'yield': last['yield'], 'uncertainty': last['yield_uncertainty']}
    return {
        'status': 'passed', 'kind': 'columnar-analysis', 'status_scope': SCOPE, 'physics_validated': False,
        'recipe': plan.doc['name'], 'output_directory': OUTPUT,
        'analysis_result': {'path': f'{OUTPUT}/analysis-result.json', 'sha256': summary['result_sha256']},
        'files': [{**f, 'path': f'{OUTPUT}/{f["path"]}'} for f in summary['files']],
        'histograms': {name: {'file': f'{OUTPUT}/{h["nominal"]["file"]}', 'unit': h['nominal']['unit'],
                              'labels': next(x.labels for x in plan.histograms if x.name == name),
                              'axis_units': next(x.units for x in plan.histograms if x.name == name),
                              'variations': h['variations']}
                       for name, h in summary['histograms'].items()},
        'region_yields': final,
        'specification': None if plan.spec_report is None else {
            'pin': plan.spec_report['specification'], 'sources': plan.spec_report['sources'],
            'assumptions': plan.spec_report['ambiguities']['assumptions'],
            'coverage_passed': plan.spec_report['coverage']['passed']},
        'normalization': {k: v for k, v in summary['normalization'].items() if k != 'coverage'},
        'events': summary['events'],
        'check_results': summary['check_results'],
        'limitations': [
            'Selections, histograms and normalisation follow the declared recipe and inputs only.',
            'The uncertainty in each bin is the Monte Carlo statistical uncertainty.',
            'Detector fidelity, generator accuracy and agreement with a published result are not established here.'],
    }


# ---------------------------------------------------------------- figures
def write_figures(result, out):
    """One figure per one-dimensional nominal histogram, with natural-language labels."""
    from ravel.physics.columnar.figures import histogram_figure
    out = Path(out)
    figures = []
    for name, entry in result.get('histograms', {}).items():
        if len(entry['labels']) != 1:
            continue
        doc = json.loads((out / entry['file']).read_text())
        stem = f'{OUTPUT}/figures/' + Path(entry['file']).stem
        figures.append(histogram_figure(doc, title=name, out=out / stem))
        figures[-1]['stem'] = stem
        figures[-1]['files'] = [f'{stem}.pdf', f'{stem}.png']
    tables = [{'stem': f'{OUTPUT}/cutflow', 'files': [f'{OUTPUT}/cutflow.json', f'{OUTPUT}/analysis-result.json'],
               'normalization': 'Declared normalisation; Monte Carlo statistical uncertainties'}]
    return {'status': 'passed' if figures else 'not_applicable', 'figures': figures, 'tables': tables,
            'scope': 'Declared selection and histograms on the supplied events; no published-reference comparison'}


# ---------------------------------------------------------------- command line
def _partition_inputs(values):
    out = []
    for i, value in enumerate(values):
        path, _, rest = value.partition('@')
        item = {'path': path, 'file_index': i}
        if rest:
            index, _, span = rest.partition(':')
            item['file_index'] = int(index)
            if span:
                start, _, stop = span.partition('-')
                item['entry_start'], item['entry_stop'] = int(start), int(stop)
        out.append(item)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel columnar-analysis', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    inspect = sub.add_parser('inspect', help='check a file against a format descriptor and list its branch types')
    inspect.add_argument('--format', required=True, help='built-in name (delphes) or descriptor JSON')
    inspect.add_argument('--input', required=True, type=Path)
    check = sub.add_parser('validate', help='compile a recipe and check it against event files; no events are processed')
    check.add_argument('--recipe', required=True, type=Path)
    check.add_argument('--format', required=True)
    check.add_argument('--input', action='append', default=[], type=Path)
    check.add_argument('--detector-card', type=Path, help='Delphes card checked against the efficiency-map semantics')
    spec_check = sub.add_parser('spec-check', help='check a typed analysis specification against a recipe')
    spec_check.add_argument('--spec', required=True, type=Path)
    spec_check.add_argument('--recipe', required=True, type=Path)
    spec_check.add_argument('--format', required=True)
    part = sub.add_parser('analyse', help='additive sums for one partition (a step of an approved execution plan)')
    part.add_argument('--recipe', required=True, type=Path)
    part.add_argument('--format', required=True)
    part.add_argument('--input', action='append', required=True,
                      help='PATH or PATH@FILE_INDEX or PATH@FILE_INDEX:START-STOP (repeatable)')
    part.add_argument('--chunk-size', type=int, default=100_000)
    part.add_argument('--detector-card', type=Path)
    part.add_argument('--out', required=True, type=Path, help='new partial-result JSON file')
    join = sub.add_parser('merge', help='add partial results (refuses overlapping entry ranges)')
    join.add_argument('partials', nargs='+', type=Path)
    join.add_argument('--out', required=True, type=Path)
    fin = sub.add_parser('finalize', help='normalise merged sums and write histograms, cutflow and provenance')
    fin.add_argument('--recipe', required=True, type=Path)
    fin.add_argument('--format', required=True)
    fin.add_argument('--partial', required=True, type=Path)
    fin.add_argument('--normalization', required=True, type=Path)
    fin.add_argument('--input', action='append', default=[], type=Path, help='event files (for an LHE cross section)')
    fin.add_argument('--out', required=True, type=Path, help='new output directory')
    fin.add_argument('--detector-card', type=Path)
    plot = sub.add_parser('plot', help='stacked control plot of one histogram from several finalised results')
    plot.add_argument('--entry', action='append', required=True,
                      help='RESULT_DIR::PROCESS LABEL::background|signal|pseudo-data (repeatable)')
    plot.add_argument('--histogram', required=True)
    plot.add_argument('--out', required=True, type=Path, help='output stem (without extension)')
    plot.add_argument('--log', action='store_true')
    args = parser.parse_args(argv)
    from ravel.physics.columnar import engine, formats
    from ravel.physics.columnar.recipe import compile_recipe
    try:
        if args.command == 'inspect':
            report = formats.load_descriptor(args.format, Path.cwd()).check_file(args.input)
            print(json.dumps(report, indent=2))
        elif args.command == 'spec-check':
            descriptor = formats.load_descriptor(args.format, Path.cwd())
            plan = compile_recipe(_load_json(args.recipe), descriptor, args.recipe.resolve().parent)
            print(json.dumps(specification_report(args.spec, plan), indent=2))
        elif args.command in ('validate', 'analyse', 'finalize'):
            descriptor = formats.load_descriptor(args.format, Path.cwd())
            plan = compile_recipe(_load_json(args.recipe), descriptor, args.recipe.resolve().parent,
                                  detector_card=args.detector_card)
            if args.command == 'validate':
                for path in args.input:
                    descriptor.check_file(path, variations=plan.variations, collections=plan.source_collections,
                                          event_fields=plan.event_fields)
                print(json.dumps({'recipe': plan.doc['name'], 'recipe_sha256': plan.recipe_sha256,
                                  'objects': sorted(plan.object_fields), 'observables': [o.name for o in plan.observables],
                                  'regions': list(plan.regions), 'histograms': [h.name for h in plan.histograms],
                                  'systematics': [s['name'] for s in plan.systematics],
                                  'collections_read': plan.source_collections, 'event_fields_read': plan.event_fields,
                                  'checked_inputs': [str(p) for p in args.input],
                                  'detector_card_check': plan.card_report}, indent=2))
            elif args.command == 'analyse':
                partial = engine.analyse({'inputs': _partition_inputs(args.input), 'chunk_size': args.chunk_size}, plan)
                _write_new(args.out, partial)
                print(json.dumps({'out': str(args.out), 'events': partial['variations']['nominal']['events']}))
            else:
                merged = _load_json(args.partial)
                result = engine.finalize(merged, plan, _load_json(args.normalization), out_dir=args.out,
                                         input_files=args.input, base=Path.cwd())
                print(json.dumps({'out': str(args.out), 'files': result['files'], 'scale': result['normalization']['scale']}, indent=2))
        elif args.command == 'merge':
            merged = engine.merge(_load_json(p) for p in args.partials)
            _write_new(args.out, merged)
            print(json.dumps({'out': str(args.out), 'events': merged['variations']['nominal']['events']}))
        elif args.command == 'plot':
            from ravel.physics.columnar.figures import control_plot
            entries = []
            for value in args.entry:
                parts = value.split('::')
                if len(parts) != 3:
                    raise ValueError('--entry is RESULT_DIR::PROCESS LABEL::ROLE')
                entries.append({'result': Path(parts[0]), 'label': parts[1], 'role': parts[2]})
            receipt = control_plot(entries, args.histogram, args.out, log=args.log)
            print(json.dumps(receipt, indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'columnar-analysis refused: {exc}\n')
    return 0


def _write_new(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(document, allow_nan=False) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
