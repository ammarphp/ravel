"""Figure digitisation, reference comparison and comparison figures as a planned scientific study.

Science mode ``figure-comparison`` runs an ordered list of operations, each driven by its
own specification file::

    {"operations": [
        {"name": "published", "kind": "digitize", "specification": "digitise.json"},
        {"name": "agreement", "kind": "compare", "specification": "compare.json"},
        {"name": "plane", "kind": "parameter-plane", "specification": "plane.json"},
        {"name": "figure", "kind": "measurement-overlay", "specification": "overlay.json"}]}

A later operation can read an earlier one through ``{"operation": "<name>", ...}`` sources
(a digitised series) or ``"comparison": {"operation": "<name>"}`` (a comparison object).
Planning reads every specification, checks those references and lists every file the study
reads, so a missing input stops the study before approval. Each operation writes into
``figure-comparison/<name>/``. Machine comparison only; it is not physics review.
"""
import argparse
import json
import sys
from pathlib import Path

SCOPE = 'declared_figure_digitisation_and_reference_comparison'
OUTPUT = 'figure-comparison'
KINDS = ('digitize', 'compare', 'parameter-plane', 'measurement-overlay')
FILE_KEYS = ('path', 'digitized', 'hepdata', 'inference')
MAX_OPERATIONS = 200


def validate(task):
    """Structural check (no files read)."""
    if not isinstance(task, dict) or set(task) - {'operations', 'description'} or 'operations' not in task:
        raise ValueError('figure-comparison task needs operations and may add a description')
    ops = task['operations']
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPERATIONS:
        raise ValueError(f'operations must be a list of 1 to {MAX_OPERATIONS} entries')
    names = []
    for op in ops:
        if not isinstance(op, dict) or set(op) != {'name', 'kind', 'specification'}:
            raise ValueError('each operation needs exactly name, kind and specification')
        if op['kind'] not in KINDS:
            raise ValueError(f'operation kind must be one of {KINDS}')
        name = op['name']
        if not isinstance(name, str) or not name or not name.replace('-', '').replace('_', '').isalnum():
            raise ValueError('operation names are letters, digits, hyphens or underscores')
        if not isinstance(op['specification'], str) or not op['specification'].strip():
            raise ValueError('specification must be a path')
        names.append(name)
    if len(set(names)) != len(names):
        raise ValueError('operation names must be unique')


def _walk(node, found_files, found_ops):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FILE_KEYS and isinstance(value, str):
                found_files.append(value)
            elif key == 'operation' and isinstance(value, str):
                found_ops.append(value)
            else:
                _walk(value, found_files, found_ops)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found_files, found_ops)


def _plan(task, base):
    from ravel.plotting.figure_io import load_spec, resolve
    validate(task)
    base = Path(base)
    files, seen, plan = [], [], []
    for op in task['operations']:
        spec_path = resolve(base, op['specification'])
        spec, spec_dir = load_spec(spec_path)
        referenced, operations = [], []
        _walk(spec, referenced, operations)
        for name in operations:
            if name not in seen:
                raise ValueError(f'operation {op["name"]} reads {name!r}, which is not an earlier operation')
        if op['kind'] == 'digitize' and not referenced:
            raise ValueError(f'digitisation {op["name"]} needs a source path')
        files.append(spec_path)
        files.extend(resolve(spec_dir, value) for value in referenced)
        plan.append((op, spec_path))
        seen.append(op['name'])
    return plan, list(dict.fromkeys(files))


def inputs(task, base):
    """Every specification and every file the specifications read."""
    _, files = _plan(task, base)
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'input must be a regular file: {path}')
    return files


def _run_one(op, spec_path, out, context):
    from ravel.plotting import digitize, measurement_overlay, parameter_plane, reference_metrics
    target = out / op['name']
    kind = op['kind']
    if kind == 'digitize':
        doc = digitize.run_spec(spec_path, target)
        record = {'series': [s['name'] for s in doc['series']], 'review_overlay': f'{op["name"]}/review.png',
                  'files': [f'{op["name"]}/digitized.json', f'{op["name"]}/review.png']}
    elif kind == 'compare':
        target.mkdir(parents=True, exist_ok=False)
        doc = reference_metrics.run_spec(spec_path, target / 'comparison.json', context)
        record = {'verdict': doc.get('verdict'), 'comparison_kind': doc.get('comparison_kind'),
                  'summary': doc.get('summary', []), 'files': [f'{op["name"]}/comparison.json']}
    else:
        module = parameter_plane if kind == 'parameter-plane' else measurement_overlay
        doc = module.run_spec(spec_path, target, context)
        record = {'plot_lint': doc['plot_lint'], 'figures': sorted({Path(f['path']).stem for f in doc['files']}),
                  'files': [f'{op["name"]}/{f["path"]}' for f in doc['files']] + [f'{op["name"]}/{doc["name"]}.json']}
        if kind == 'measurement-overlay' and doc.get('comparison'):
            record['verdict'] = doc['comparison'].get('verdict')
    context[op['name']] = doc
    return {'name': op['name'], 'kind': kind, **record}


def run(task, base, destination):
    plan, _ = _plan(task, base)
    out = Path(destination) / OUTPUT
    out.mkdir(parents=True, exist_ok=False)
    context, operations = {}, []
    for op, spec_path in plan:
        operations.append(_run_one(op, spec_path, out, context))
    return {
        'status': 'passed', 'kind': 'figure-comparison', 'status_scope': SCOPE, 'physics_validated': False,
        'output_directory': OUTPUT, 'operations': operations,
        'verdicts': {o['name']: o['verdict'] for o in operations if o.get('verdict')},
        'limitations': [
            'Digitised series are approximate; check each review overlay before relying on them.',
            'Verdicts are machine comparisons under declared transformations and tolerances, not physics review.',
            'Agreement with a published figure does not establish the physics of either result.'],
    }


def write_figures(result, out):
    """Figures and tables the operations wrote, relative to the attempt directory."""
    figures, tables = [], []
    for op in result.get('operations', []):
        prefix = f'{OUTPUT}/{op["name"]}'
        if op['kind'] == 'digitize':
            figures.append({'stem': f'{prefix}/review', 'files': [f'{prefix}/review.png'],
                            'caption': 'Digitisation review: extracted points and calibration anchors'})
            tables.append({'stem': f'{prefix}/digitized', 'files': [f'{prefix}/digitized.json']})
        elif op['kind'] == 'compare':
            tables.append({'stem': f'{prefix}/comparison', 'files': [f'{prefix}/comparison.json']})
        else:
            for stem in op['figures']:
                figures.append({'stem': f'{prefix}/{stem}',
                                'files': [f'{OUTPUT}/{f}' for f in op['files'] if Path(f).stem == stem
                                          and not f.endswith('.json')]})
            tables.extend({'stem': f'{OUTPUT}/{Path(f).with_suffix("")}', 'files': [f'{OUTPUT}/{f}']}
                          for f in op['files'] if f.endswith('.json'))
    return {'status': 'passed' if figures or tables else 'not_applicable', 'figures': figures, 'tables': tables,
            'scope': 'Declared digitisation, comparison and figure specifications; machine checks only'}


def main(argv=None):
    """``ravel figure <digitize|plane|measurement> --spec S --out D`` and ``ravel figure plan``."""
    parser = argparse.ArgumentParser(prog='ravel figure', description='Digitise published figures, compare with '
                                     'references and draw parameter-plane and measurement figures.')
    sub = parser.add_subparsers(dest='action', required=True)
    for action, text in (('digitize', 'digitise a vector PDF or raster figure (writes digitized.json and '
                                      'review.png)'),
                         ('plane', 'draw a parameter-plane figure'),
                         ('measurement', 'draw a measurement overlay with ratio and official figure')):
        p = sub.add_parser(action, help=text)
        p.add_argument('--spec', required=True, type=Path)
        p.add_argument('--out', required=True, type=Path, help='new or empty output directory')
    p = sub.add_parser('inventory', help='list the drawn paths, fills and text of one PDF page')
    p.add_argument('pdf', type=Path)
    p.add_argument('--page', type=int, default=1)
    p = sub.add_parser('plan', help='check a figure-comparison task and list the files it reads')
    p.add_argument('--task', required=True, type=Path)
    p.add_argument('--base', type=Path, default=Path('.'))
    args = parser.parse_args(argv)
    try:
        if args.action == 'digitize':
            from ravel.plotting import digitize
            doc = digitize.run_spec(args.spec, args.out)
            summary = {'series': {s['name']: sum(len(g['x']) for g in s.get('segments', [])) for s in doc['series']},
                       'review_overlay': str(Path(args.out) / 'review.png')}
        elif args.action == 'plane':
            from ravel.plotting import parameter_plane
            doc = parameter_plane.run_spec(args.spec, args.out)
            summary = {'figure': [f['path'] for f in doc['files']], 'plot_lint': doc['plot_lint']}
        elif args.action == 'measurement':
            from ravel.plotting import measurement_overlay
            doc = measurement_overlay.run_spec(args.spec, args.out)
            summary = {'figure': [f['path'] for f in doc['files']], 'plot_lint': doc['plot_lint'],
                       'comparison': (doc.get('comparison') or {}).get('verdict')}
        elif args.action == 'inventory':
            from ravel.plotting import digitize
            summary = digitize.inventory(args.pdf, args.page)
        else:
            task = json.loads(args.task.read_text())
            summary = {'inputs': [str(p) for p in inputs(task, args.base)]}
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
